"""Persistent transcripts must never replay banking operations or leak owners."""
import json
from decimal import Decimal
import pytest
from app.db.models import AccountModel, ChatMessageModel, UserModel, ConversationModel, TransactionModel
from app.services.adapters import agent_service
from app.services.session_store import clear_conversation_state, conversation_key
from app.services.chat_history import save_message

HEADERS = {'X-Demo-User-Id': 'usr_demo_01'}


@pytest.fixture(autouse=True)
def real_agent_with_offline_interpretation(monkeypatch):
    monkeypatch.setattr(agent_service, 'use_mock', False)
    monkeypatch.setenv('AGENT_PROVIDER', 'mock')


def create(client):
    result = client.post('/api/v1/conversations', headers=HEADERS)
    assert result.status_code == 201, result.text
    return result.json()['conversation_id']


def send(client, conversation, message):
    result = client.post('/api/v1/chat', headers=HEADERS,
        json={'conversation_id': conversation, 'message': message})
    assert result.status_code == 200, result.text
    return result.json()


def history(client, conversation, **params):
    result = client.get(f'/api/v1/conversations/{conversation}', headers=HEADERS, params=params)
    assert result.status_code == 200, result.text
    return result.json()


def test_transcript_survives_memory_cache_clear_and_new_chats_are_independent(client):
    first = create(client)
    send(client, first, 'Transfer to Bob')
    clear_conversation_state(conversation_key('usr_demo_01', first))
    saved = history(client, first)
    assert [m['sender'] for m in saved['messages']] == ['user', 'agent']
    assert saved['messages'][0]['text'] == 'Transfer to Bob'
    assert saved['conversation']['title'] == 'Transfer to Bob'
    assert not saved['messages'][1]['actions']
    second = create(client)
    assert second != first and not history(client, second)['messages']
    assert not send(client, second, '40')['actions']  # No Bob inherited.
    resumed = send(client, first, '40')
    assert resumed['actions'][0]['arguments']['recipient_id'] == 'usr_bob_01'
    assert resumed['actions'][0]['arguments']['amount'] == '40.00'
    assert len(history(client, first)['messages']) == 4


def test_history_reads_refresh_action_status_without_executing_or_calling_ai(client, db_session, monkeypatch):
    conversation = create(client)
    proposed = send(client, conversation, 'Transfer 1 to Bob')['actions'][0]
    action = proposed['approval']
    first = history(client, conversation)
    assert first['messages'][-1]['actions'][0]['approval']['status'] == 'PENDING_CONFIRMATION'
    assert db_session.get(AccountModel, 'acc_cny_001').balance == Decimal('15250.00')
    result = client.post(f"/api/v1/actions/{action['action_id']}/confirm", headers=HEADERS,
        json={'confirmation_id': 'history_confirmation', 'action_digest': action['action_digest'],
              'idempotency_key': 'history_execution'})
    assert result.status_code == 200 and result.json()['status'] == 'COMPLETED', result.text
    from agent import service
    def unavailable():
        raise AssertionError('Reading history must not invoke a model')
    monkeypatch.setattr(service, 'get_provider', unavailable)
    count = db_session.query(TransactionModel).count()
    for _ in range(2):
        reopened = history(client, conversation)
        assert reopened['messages'][-1]['actions'][0]['approval']['status'] == 'COMPLETED'
    assert db_session.query(TransactionModel).count() == count
    assert db_session.get(AccountModel, 'acc_cny_001').balance == Decimal('15249.00')


def test_continuation_is_saved_once_even_when_delivery_is_retried(client, db_session):
    conversation = create(client)
    action = send(client, conversation, 'Transfer 1 to Bob')['actions'][0]['approval']
    result = client.post(f"/api/v1/actions/{action['action_id']}/confirm", headers=HEADERS,
        json={'confirmation_id': 'history_confirm', 'action_digest': action['action_digest'],
              'idempotency_key': 'history_execute'})
    assert result.status_code == 200, result.text
    for _ in range(2):
        delivered = client.post(f"/api/v1/actions/{action['action_id']}/continue", headers=HEADERS)
        assert delivered.status_code == 200, delivered.text
    messages = history(client, conversation)['messages']
    assert len(messages) == 3
    assert messages[-1]['event_key'] == f"{action['action_id']}:COMPLETED"
    assert 'is complete' in messages[-1]['text']
    assert db_session.get(AccountModel, 'acc_cny_001').balance == Decimal('15249.00')


def test_history_and_lists_are_owner_scoped(client, db_session):
    conversation = create(client)
    send(client, conversation, 'What is my balance?')
    db_session.add(UserModel(user_id='other_user', username='Other', is_locked=False))
    db_session.commit()
    other = {'X-Demo-User-Id': 'other_user'}
    assert client.get(f'/api/v1/conversations/{conversation}', headers=other).status_code == 404
    assert client.get('/api/v1/conversations', headers=other).json()['conversations'] == []
    assert client.get('/api/v1/conversations', headers=HEADERS).json()['conversations'][0]['conversation_id'] == conversation
    assert client.get('/api/v1/conversations?limit=0', headers=HEADERS).status_code == 422


def test_message_pages_are_ordered_and_do_not_duplicate(client, db_session):
    conversation = create(client)
    for i in range(5):
        save_message(db_session, 'usr_demo_01', conversation, 'user', f'message {i}')
    db_session.commit()
    recent = history(client, conversation, limit=2)
    assert [m['text'] for m in recent['messages']] == ['message 3', 'message 4']
    assert recent['has_more'] is True
    older = history(client, conversation, limit=2, before_id=recent['messages'][0]['id'])
    assert [m['text'] for m in older['messages']] == ['message 1', 'message 2']
    oldest = history(client, conversation, limit=2, before_id=older['messages'][0]['id'])
    assert [m['text'] for m in oldest['messages']] == ['message 0']
    assert oldest['has_more'] is False


def test_conversation_list_pages_and_legacy_state_do_not_invent_messages(client, db_session):
    db_session.add(ConversationModel(user_id='usr_demo_01', conversation_id='legacy',
                                    state_json=json.dumps({'conversation_id': 'legacy'})))
    db_session.commit()
    assert history(client, 'legacy')['messages'] == []
    create(client)
    first = client.get('/api/v1/conversations?limit=1', headers=HEADERS).json()
    second = client.get('/api/v1/conversations?limit=1&offset=1', headers=HEADERS).json()
    assert first['has_more'] and not second['has_more']
    assert first['conversations'][0]['conversation_id'] != second['conversations'][0]['conversation_id']


def test_migration_preserves_existing_agent_draft(tmp_path):
    from sqlalchemy import create_engine, text
    from alembic import command
    from alembic.config import Config
    from app.db.migrate import BACKEND_ROOT, upgrade_database
    engine = create_engine(f"sqlite:///{(tmp_path / 'history_migration.db').as_posix()}")
    config = Config(str(BACKEND_ROOT / 'alembic.ini'))
    config.set_main_option('script_location', str(BACKEND_ROOT / 'migrations'))
    with engine.begin() as conn:
        config.attributes['connection'] = conn
        command.upgrade(config, '0006_safety_lock')
        conn.execute(text("INSERT INTO agent_conversations VALUES ('u', 'old', :state)"), {'state': '{"pending_transfer":"keep"}'})
    upgrade_database(engine)
    upgrade_database(engine)
    with engine.connect() as conn:
        row = conn.execute(text('SELECT state_json, title, created_at, updated_at FROM agent_conversations')).one()
        assert row[0] == '{"pending_transfer":"keep"}' and row[1] == 'New chat'
        assert row[2] and row[3]
        assert conn.scalar(text('SELECT COUNT(*) FROM chat_messages')) == 0
    engine.dispose()
