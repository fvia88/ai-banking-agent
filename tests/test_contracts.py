import json
from decimal import Decimal
from pathlib import Path
import pytest
from pydantic import ValidationError
from contracts.models import (Account, User, Recipient, Transaction, Subscription, ChatInput,
                              ActionProposal, BankingContext, SpendingReport, SubscriptionCandidate)
from contracts.enums import ToolName
from contracts.tool_schemas import validate_tool_arguments

ROOT = Path(__file__).resolve().parents[1]
def load(name):
    return json.loads((ROOT / 'fixtures' / name).read_text(encoding='utf-8'))

@pytest.mark.parametrize('filename,model', [
 ('users.json',User),('accounts.json',Account),('recipients.json',Recipient),
 ('transactions.json',Transaction),('subscriptions.json',Subscription)])
def test_all_fixture_rows_validate(filename, model):
    rows=load(filename)
    assert rows
    for row in rows:
        instance=model.model_validate(row)
        assert instance.model_validate_json(instance.model_dump_json()) == instance

def test_money_is_decimal_and_json_string():
    a=Account.model_validate(load('accounts.json')[0])
    assert a.balance == Decimal('5000.00')
    assert '"5000.00"' in a.model_dump_json()

def test_timezone_required():
    row=load('transactions.json')[0].copy()
    row['timestamp']='2026-10-14T09:00:00'
    with pytest.raises(ValidationError): Transaction.model_validate(row)

def test_negative_transfer_rejected():
    with pytest.raises(ValidationError):
        validate_tool_arguments(ToolName.REQUEST_TRANSFER,dict(source_account_id='account_001',recipient_id='recipient_alice',amount='-1.00',currency='CNY'))

def test_transfer_valid():
    a=validate_tool_arguments(ToolName.REQUEST_TRANSFER,dict(source_account_id='account_001',recipient_id='recipient_alice',amount='500.00',currency='CNY'))
    assert a.amount == Decimal('500.00')

def test_unknown_extra_tool_arg_rejected():
    with pytest.raises(ValidationError):
        validate_tool_arguments(ToolName.GET_BALANCE,{'account_id':'account_001','admin':True})

def test_chat_input_does_not_accept_user_id():
    with pytest.raises(ValidationError):
        ChatInput(conversation_id='c1',message='hello',user_id='attacker')

def test_expected_cases_unique():
    rows=load('expected_cases.json')
    assert len(rows)>=12
    assert len({r['case_id'] for r in rows})==len(rows)

def test_october_expected_spending_matches_fixture():
    rows=[Transaction.model_validate(t) for t in load('transactions.json')]
    oct_debits=[t for t in rows if t.timestamp.strftime('%Y-%m')=='2026-10' and t.direction.value=='debit']
    total=sum((t.amount for t in oct_debits),Decimal('0.00'))
    expected=next(c for c in load('expected_cases.json') if c['case_id']=='T12')
    assert total == Decimal(expected['expected_total_spending'])
    categories={}
    for t in oct_debits: categories[t.category]=categories.get(t.category,Decimal('0.00'))+t.amount
    assert {k:f'{v:.2f}' for k,v in categories.items()}==expected['expected_category_totals']

def test_sample_proposal_validates():
    proposal=ActionProposal(proposal_id='p1',tool='request_transfer',arguments={'source_account_id':'account_001','recipient_id':'recipient_alice','amount':'500.00','currency':'CNY'})
    assert validate_tool_arguments(proposal.tool,proposal.arguments).amount == Decimal('500.00')
