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

export type ActionStatus = 'PROPOSED' | 'PENDING_CONFIRMATION' | 'PENDING_MFA' | 'COMPLETED' | 'REJECTED' | 'FAILED' | 'CANCELLED';
export type ApprovalTier = 'YELLOW' | 'RED';

export interface ApprovalMetadata {
  action_id: string;
  action_digest: string;
  tier: ApprovalTier;
  status: ActionStatus;
}

interface TransferArguments {
  source_account_id: string;
  recipient_id: string;
  amount: string;
  currency: 'CNY';
}

interface CancellationArguments {
  subscription_id: string;
}

export type ActionProposal = {
  proposal_id: string;
  approval: ApprovalMetadata;
  rationale?: string;
} & (
  | { tool: 'request_transfer'; arguments: TransferArguments }
  | { tool: 'request_subscription_cancel'; arguments: CancellationArguments }
);

export interface ChatOutput {
  conversation_id: string;
  reply: string;
  actions: ActionProposal[];
  status: ActionStatus;
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
  status: ActionStatus;
  message: string;
  audit_id: string;
}

export interface ConfirmActionRequest {
  confirmation_id: string;
  action_digest: string;
  idempotency_key: string;
}

export interface VerifyActionRequest {
  verification_code: string;
  idempotency_key: string;
}

export interface CancelApprovalRequest {
  action_digest: string;
  idempotency_key: string;
}

export async function fetchActionStatus(actionId: string): Promise<ApprovalMetadata> {
  const res = await fetch(`/api/v1/actions/${encodeURIComponent(actionId)}`, {
    headers: { 'X-Demo-User-Id': DEMO_USER_ID },
  });
  if (!res.ok) throw new Error('Could not retrieve the bank status for this approval');
  return res.json();
}

export async function cancelAction(actionId: string, digest: string): Promise<ExecutionResult> {
  const res = await fetch(`/api/v1/actions/${encodeURIComponent(actionId)}/cancel`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Demo-User-Id': DEMO_USER_ID },
    body: JSON.stringify({ action_digest: digest, idempotency_key: `cancel_${actionId}` } satisfies CancelApprovalRequest),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || 'Cancellation could not be applied');
  }
  return res.json();
}

export interface ContinuationOutput {
  execution: ExecutionResult;
  chat: ChatOutput;
}

export async function continueAction(actionId: string): Promise<ContinuationOutput | null> {
  const res = await fetch(`/api/v1/actions/${encodeURIComponent(actionId)}/continue`, {
    method: 'POST', headers: { 'X-Demo-User-Id': DEMO_USER_ID },
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    // Mock and pre-migration tickets retain their ordinary approval UI.
    if (res.status === 409 && data.detail === 'This action has no real-agent conversation link') return null;
    throw new Error(data.detail || 'Conversation update unavailable');
  }
  return res.json();
}

export async function confirmAction(
  actionId: string,
  digest: string
): Promise<ExecutionResult> {
  const res = await fetch(`/api/v1/actions/${encodeURIComponent(actionId)}/confirm`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Demo-User-Id': DEMO_USER_ID,
    },
    body: JSON.stringify({
      confirmation_id: `conf_${Date.now()}`,
      action_digest: digest,
      idempotency_key: `idemp_${Date.now()}`,
    } satisfies ConfirmActionRequest),
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
  const res = await fetch(`/api/v1/actions/${encodeURIComponent(actionId)}/verify`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Demo-User-Id': DEMO_USER_ID,
    },
    body: JSON.stringify({
      verification_code: code,
      idempotency_key: `idemp_verify_${Date.now()}`,
    } satisfies VerifyActionRequest),
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
  evidence_transaction_ids: string[];
  cancellation_supported: boolean;
}

export interface StoredSubscription {
  subscription_id: string;
  user_id: string;
  merchant: string;
  estimated_amount: string;
  cadence: string;
  status: 'active' | 'cancelled';
  cancellation_supported: boolean;
}

export async function fetchStoredSubscriptions(): Promise<StoredSubscription[]> {
  const res = await fetch('/api/v1/subscriptions/records', {
    headers: { 'X-Demo-User-Id': DEMO_USER_ID },
  });
  if (!res.ok) throw new Error(`Failed to fetch verified subscriptions: ${res.statusText}`);
  return res.json();
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

export interface DemoInboxMessage {
  action_id: string;
  code: string;
  expires_at: string;
  attempts_remaining: number;
  message: string;
}

// Simulated OTP delivery channel (no SMS/email is sent)
export async function fetchDemoInbox(): Promise<DemoInboxMessage[]> {
  const res = await fetch('/api/v1/demo/otp-inbox', {
    headers: { 'X-Demo-User-Id': DEMO_USER_ID },
  });
  if (!res.ok) throw new Error(`Failed to fetch demo inbox: ${res.statusText}`);
  return res.json();
}
