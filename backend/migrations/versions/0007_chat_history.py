"""Persist display messages independently of agent working memory."""
from alembic import op
import sqlalchemy as sa

revision = "0007_chat_history"
down_revision = "0006_safety_lock"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    columns = {column['name'] for column in sa.inspect(connection).get_columns('agent_conversations')}
    for name, kind, default in (
        ('title', sa.String(80), sa.text("'New chat'")),
        ('created_at', sa.DateTime(), sa.func.current_timestamp()),
        ('updated_at', sa.DateTime(), sa.func.current_timestamp()),
    ):
        if name not in columns:
            # Nullable addition + backfill also works on populated SQLite DBs.
            op.add_column('agent_conversations', sa.Column(name, kind, nullable=True))
            connection.execute(sa.text(f'UPDATE agent_conversations SET {name} = ' +
                ("'New chat'" if name == 'title' else 'CURRENT_TIMESTAMP') + f' WHERE {name} IS NULL'))
            with op.batch_alter_table('agent_conversations') as batch:
                batch.alter_column(name, existing_type=kind, nullable=False, server_default=default)
    if 'chat_messages' not in sa.inspect(connection).get_table_names():
        op.create_table('chat_messages',
            sa.Column('message_id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('user_id', sa.String(64), nullable=False),
            sa.Column('conversation_id', sa.String(128), nullable=False),
            sa.Column('sender', sa.String(8), nullable=False),
            sa.Column('text', sa.Text(), nullable=False),
            sa.Column('response_json', sa.Text(), nullable=True),
            sa.Column('event_key', sa.String(160), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['user_id', 'conversation_id'],
                ['agent_conversations.user_id', 'agent_conversations.conversation_id']),
            sa.UniqueConstraint('user_id', 'conversation_id', 'event_key', name='uq_chat_message_event'))
        op.create_index('ix_chat_messages_conversation', 'chat_messages', ['user_id', 'conversation_id', 'message_id'])


def downgrade():
    raise RuntimeError('Automatic destructive downgrade is disabled; restore a reviewed backup instead.')
