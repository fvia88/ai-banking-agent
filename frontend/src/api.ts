// frontend/src/api.ts

export interface Account {
  account_id: string;
  user_id: string;
  currency: string;
  balance: string | number;
  locked: boolean;
}

export interface AccountsResponse {
  accounts: Account[];
}

export interface Transaction {
  transaction_id: string;
  account_id: string;
  timestamp: string;
  amount: string | number;
  direction: 'debit' | 'credit';
  merchant: string;
  category: string;
  note?: string;
}

export interface TransactionsResponse {
  transactions: Transaction[];
}

const DEMO_USER_ID = 'usr_demo_01';

export async function fetchAccounts(): Promise<AccountsResponse> {
  const res = await fetch('/api/v1/accounts', {
    headers: { 'X-Demo-User-Id': DEMO_USER_ID },
  });
  if (!res.ok) throw new Error(`Failed to fetch accounts: ${res.statusText}`);
  return res.json();
}

export async function fetchTransactions(): Promise<TransactionsResponse> {
  const res = await fetch('/api/v1/transactions', {
    headers: { 'X-Demo-User-Id': DEMO_USER_ID },
  });
  if (!res.ok) throw new Error(`Failed to fetch transactions: ${res.statusText}`);
  return res.json();
}

export interface ActionProposal {
  proposal_id: string;
  tool: string;
  arguments: {
    action_id?: string;
    action_digest?: string;
    tier?: 'YELLOW' | 'RED' | 'GREEN';
    recipient_id?: string;
    amount?: string;
    currency?: string;
    subscription_id?: string;
    [key: string]: any;
  };
  rationale?: string;
}

export interface ChatOutput {
  conversation_id: string;
  reply: string;
  actions: ActionProposal[];
  status: string;
}

export interface ChatMessage {
  sender: 'user' | 'agent';
  text: string;
  actions?: ActionProposal[];
}

export async function sendChatMessage(
  message: string,
  conversationId: string = 'conv_ui_01'
): Promise<ChatOutput> {
  const res = await fetch('/api/v1/chat', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Demo-User-Id': DEMO_USER_ID,
    },
    body: JSON.stringify({
      conversation_id: conversationId,
      message,
    }),
  });
  if (!res.ok) throw new Error(`Chat error: ${res.statusText}`);
  return res.json();
}

export interface ExecutionResult {
  action_id: string;
  status: string;
  message: string;
  audit_id: string;
}

export async function confirmAction(
  actionId: string,
  digest: string
): Promise<ExecutionResult> {
  const res = await fetch(`/api/v1/actions/${actionId}/confirm`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Demo-User-Id': DEMO_USER_ID,
    },
    body: JSON.stringify({
      confirmation_id: `conf_${Date.now()}`,
      action_digest: digest,
      idempotency_key: `idemp_${Date.now()}`,
    }),
  });
  if (!res.ok) {
    const errData = await res.json().catch(() => ({}));
    throw new Error(errData.detail || `Confirm failed: ${res.statusText}`);
  }
  return res.json();
}

export async function verifyAction(
  actionId: string,
  code: string
): Promise<ExecutionResult> {
  const res = await fetch(`/api/v1/actions/${actionId}/verify`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Demo-User-Id': DEMO_USER_ID,
    },
    body: JSON.stringify({
      verification_code: code,
      idempotency_key: `idemp_verify_${Date.now()}`,
    }),
  });
  if (!res.ok) {
    const errData = await res.json().catch(() => ({}));
    throw new Error(errData.detail || `Verify failed: ${res.statusText}`);
  }
  return res.json();
}

export interface SubscriptionCandidate {
  subscription_id: string;
  merchant: string;
  estimated_amount: string | number;
  cadence: string;
  confidence: number;
  cancellation_supported: boolean;
}

export interface SubscriptionReport {
  candidates: SubscriptionCandidate[];
}

export interface AuditEvent {
  audit_id: string;
  action_id: string;
  event_type: string;
  timestamp: string;
  reason_code: string;
}

export interface AuditResponse {
  events: AuditEvent[];
}

export async function fetchSubscriptions(): Promise<SubscriptionReport> {
  const res = await fetch('/api/v1/subscriptions', {
    headers: { 'X-Demo-User-Id': DEMO_USER_ID },
  });
  if (!res.ok) throw new Error(`Failed to fetch subscriptions: ${res.statusText}`);
  return res.json();
}

export async function fetchAuditLogs(): Promise<AuditResponse> {
  const res = await fetch('/api/v1/audit', {
    headers: { 'X-Demo-User-Id': DEMO_USER_ID },
  });
  if (!res.ok) throw new Error(`Failed to fetch audit logs: ${res.statusText}`);
  return res.json();
}