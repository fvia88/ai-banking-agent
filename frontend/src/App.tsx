// frontend/src/App.tsx
import { useState, useEffect, useRef } from 'react';
import { fetchAccounts, fetchTransactions, sendChatMessage, confirmAction, verifyAction, continueAction, fetchSubscriptions, fetchStoredSubscriptions, fetchAuditLogs, fetchDemoInbox } from './api';
import type { Account, Transaction, ChatMessage, ActionProposal, SubscriptionCandidate, StoredSubscription, AuditEvent, DemoInboxMessage } from './api';
import { SubscriptionsPanel } from './SubscriptionsPanel';
import { ApprovalCard } from './ApprovalCard';
import type { ActionUiState } from './approvalState';
import { mergeApprovalState } from './approvalState';

export default function App() {
  // Banking data state
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [subscriptions, setSubscriptions] = useState<SubscriptionCandidate[]>([]);
  const [storedSubscriptions, setStoredSubscriptions] = useState<StoredSubscription[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditEvent[]>([]);
  const [showAudit, setShowAudit] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Chat state
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      sender: 'agent',
      text: 'Hello Alice! I am your Banking AI Assistant. How can I assist with your bills, transfers, or subscriptions today?',
    },
  ]);
  const [inputMessage, setInputMessage] = useState<string>('');
  const [sending, setSending] = useState<boolean>(false);
  const deliveredUpdates = useRef(new Set<string>());
  const [continuationErrors, setContinuationErrors] = useState<Record<string, string>>({});
  const [actionStates, setActionStates] = useState<
      Record<string, ActionUiState>
    >({});

  async function loadData() {
    setLoading(true);
    setError(null);
    try {
      const [accRes, txRes, subRes, audRes, storedRes] = await Promise.all([
        fetchAccounts(),
        fetchTransactions(),
        fetchSubscriptions(),
        fetchAuditLogs(),
        fetchStoredSubscriptions(),
      ]);
      setAccounts(accRes.accounts);
      setTransactions(txRes.transactions);
      setSubscriptions(subRes.candidates);
      setStoredSubscriptions(storedRes);
      setAuditLogs(audRes.events);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Error connecting to backend');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, []);

  function rememberApprovals(actions: ActionProposal[]) {
    if (!actions.length) return;
    setActionStates(prev => {
      const next = { ...prev };
      for (const action of actions) {
        next[action.approval.action_id] = mergeApprovalState(next[action.approval.action_id], action.approval);
      }
      return next;
    });
  }

  async function handleSend() {
    if (!inputMessage.trim() || sending) return;

    const userText = inputMessage.trim();
    setInputMessage('');
    
    // Append user message immediately
    setMessages((prev) => [...prev, { sender: 'user', text: userText }]);
    setSending(true);

    try {
      const response = await sendChatMessage(userText);
      rememberApprovals(response.actions);
      
      // Append AI response with any proposed actions
      setMessages((prev) => [
        ...prev,
        {
          sender: 'agent',
          text: response.reply,
          actions: response.actions,
        },
      ]);
    } catch (err: unknown) {
      setMessages((prev) => [
        ...prev,
        {
          sender: 'agent',
          text: `⚠️ Error: ${err instanceof Error ? err.message : 'Failed to reach AI'}`,
        },
      ]);
    } finally {
      setSending(false);
    }
  }

  async function updateConversation(actionId: string) {
    try {
      const update = await continueAction(actionId);
      if (!update) return;
      setActionStates(prev => ({ ...prev, [actionId]: {
        ...prev[actionId], status: update.execution.status, message: update.execution.message,
        tier: update.execution.status === 'PENDING_MFA' ? 'RED' : prev[actionId]?.tier,
      } }));
      if (update.execution.status === 'PENDING_MFA') {
        const inbox = await fetchDemoInbox().catch((): DemoInboxMessage[] => []);
        setActionStates(prev => ({ ...prev, [actionId]: {
          ...prev[actionId], inboxMessage: inbox.find(m => m.action_id === actionId)?.message,
        } }));
      }
      const key = `${actionId}:${update.execution.status}`;
      rememberApprovals(update.chat.actions);
      if (!deliveredUpdates.current.has(key)) {
        deliveredUpdates.current.add(key);
        setMessages(prev => [...prev, {
          sender: 'agent', text: update.chat.reply, actions: update.chat.actions,
        }]);
      }
      setContinuationErrors(prev => {
        const next = { ...prev }; delete next[actionId]; return next;
      });
    } catch {
      // The bank transaction already has its own committed outcome. A failed
      // agent notification must never turn a successful transfer into "failed".
      setContinuationErrors(prev => ({ ...prev,
        [actionId]: 'Conversation update unavailable. Retry to retrieve the bank status and notify the agent.',
      }));
    }
  }

  // handle clicking confirm
  async function handleConfirm(actionId: string, digest: string) {
    try {
      const res = await confirmAction(actionId, digest);
      if (res.status === 'PENDING_MFA') {
        setActionStates((prev) => ({
          ...prev,
          [actionId]: { status: 'PENDING_MFA', tier: 'RED', message: res.message, mfaCode: '' },
        }));
        // Simulated OTP delivery: show the code from the demo inbox
        const inbox = await fetchDemoInbox().catch((): DemoInboxMessage[] => []);
        const inboxMessage = inbox.find((m) => m.action_id === actionId)?.message;
        setActionStates((prev) => ({
          ...prev,
          [actionId]: { ...prev[actionId], inboxMessage },
        }));
      } else if (res.status === 'COMPLETED') {
        setActionStates((prev) => ({
          ...prev,
          [actionId]: { ...prev[actionId], status: 'COMPLETED', message: res.message },
        }));
        await loadData(); // Auto-refreshes balance!
      }
    } catch (err: unknown) {
      setActionStates((prev) => ({
        ...prev,
        [actionId]: { ...prev[actionId], status: prev[actionId]?.status || 'PENDING_CONFIRMATION', error: err instanceof Error ? err.message : 'Failed' },
      }));
    }
    await updateConversation(actionId);
  }

  // handle entering the MFA code
  async function handleVerify(actionId: string, code: string) {
    try {
      const res = await verifyAction(actionId, code);
      if (res.status === 'COMPLETED') {
        setActionStates((prev) => ({
          ...prev,
          [actionId]: { ...prev[actionId], status: 'COMPLETED', message: res.message },
        }));
        await loadData(); // Auto-refreshes balance!
      }
    } catch (err: unknown) {
      setActionStates((prev) => ({
        ...prev,
        [actionId]: { ...prev[actionId], error: err instanceof Error ? err.message : 'Invalid code' },
      }));
    }
    await updateConversation(actionId);
  }

  return (
    <div style={{ padding: '24px', fontFamily: 'sans-serif', maxWidth: '850px', margin: '0 auto' }}>
      <h2>🏦 AI Banking Agent Dashboard</h2>
      <p>
        <strong>Current User:</strong> Alice Wang (<code>usr_demo_01</code>)
        <button onClick={loadData} style={{ marginLeft: '16px', padding: '4px 12px', cursor: 'pointer' }}>
          🔄 Refresh Balances
        </button>
      </p>
      {loading && <p style={{ color: '#666', fontStyle: 'italic' }}>⏳ Loading live data from bank vault...</p>}

      {error && (
        <div style={{ padding: '12px', background: '#ffebee', color: '#c62828', borderRadius: '4px', marginBottom: '16px' }}>
          <strong>Error:</strong> {error}
        </div>
      )}

      {/* Account Balance Card */}
      <section style={{ marginBottom: '24px' }}>
        <h3>💳 Bank Accounts</h3>
        {accounts.map((acc) => (
          <div
            key={acc.account_id}
            style={{
              border: '2px solid #2e7d32',
              borderRadius: '8px',
              padding: '16px',
              background: '#f1f8e9',
            }}
          >
            <strong>Account:</strong> <code>{acc.account_id}</code> | <strong>Status:</strong>{' '}
            {acc.locked ? '🔒 Locked' : '✅ Active'}
            <div style={{ fontSize: '24px', fontWeight: 'bold', color: '#1b5e20', marginTop: '6px' }}>
              {acc.balance} {acc.currency}
            </div>
          </div>
        ))}
      </section>

      {/* Chat Section */}
      <section style={{ border: '1px solid #ccc', borderRadius: '8px', padding: '16px', marginBottom: '24px', background: '#fafafa' }}>
        <h3>💬 AI Banking Assistant</h3>
        
        {/* Messages Feed */}
        <div style={{ minHeight: '220px', maxHeight: '380px', overflowY: 'auto', marginBottom: '16px', padding: '8px', background: '#fff', border: '1px solid #eee', borderRadius: '4px' }}>
          {messages.map((m, idx) => (
            <div
              key={idx}
              style={{
                marginBottom: '14px',
                textAlign: m.sender === 'user' ? 'right' : 'left',
              }}
            >
              <div
                style={{
                  display: 'inline-block',
                  padding: '10px 14px',
                  borderRadius: '12px',
                  background: m.sender === 'user' ? '#1976d2' : '#f0f0f0',
                  color: m.sender === 'user' ? '#fff' : '#222',
                  maxWidth: '75%',
                  textAlign: 'left',
                }}
              >
                {m.text}

                {/* Render Proposed Action Cards if attached */}
                {m.actions && m.actions.length > 0 && (
                  <div style={{ marginTop: '10px' }}>
                    {m.actions.map(act => (
                      <ApprovalCard key={act.approval.action_id} action={act}
                        state={actionStates[act.approval.action_id]}
                        continuationError={continuationErrors[act.approval.action_id]}
                        onConfirm={handleConfirm} onVerify={handleVerify} onRetry={updateConversation}
                        onCodeChange={(actionId, code) => setActionStates(prev => ({
                          ...prev, [actionId]: { ...prev[actionId],
                            status: prev[actionId]?.status ?? act.approval.status, mfaCode: code, error: undefined },
                        }))} />
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
          {sending && <p style={{ color: '#888', fontStyle: 'italic' }}>🤖 Agent is typing...</p>}
        </div>

        {/* Input Bar */}
        <div style={{ display: 'flex', gap: '8px' }}>
          <input
            type="text"
            value={inputMessage}
            placeholder="Type 'Transfer 500 CNY to Bob' or 'Cancel my subscription'..."
            onChange={(e) => setInputMessage(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSend()}
            style={{ flex: 1, padding: '10px', borderRadius: '4px', border: '1px solid #ccc' }}
          />
          <button
            onClick={handleSend}
            disabled={sending || !inputMessage.trim()}
            style={{ padding: '10px 20px', cursor: 'pointer', background: '#1976d2', color: '#fff', border: 'none', borderRadius: '4px' }}
          >
            Send
          </button>
        </div>
      </section>

      {/* Transactions Section */}
      <section>
        <h3>📜 Recent Transactions</h3>
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
          <thead>
            <tr style={{ borderBottom: '2px solid #ccc' }}>
              <th style={{ padding: '8px' }}>Date</th>
              <th style={{ padding: '8px' }}>Merchant</th>
              <th style={{ padding: '8px' }}>Category</th>
              <th style={{ padding: '8px', textAlign: 'right' }}>Amount</th>
            </tr>
          </thead>
          <tbody>
            {transactions.map((tx) => (
              <tr key={tx.transaction_id} style={{ borderBottom: '1px solid #eee' }}>
                <td style={{ padding: '8px' }}>{new Date(tx.timestamp).toLocaleDateString()}</td>
                <td style={{ padding: '8px' }}>{tx.merchant}</td>
                <td style={{ padding: '8px' }}>{tx.category}</td>
                <td
                  style={{
                    padding: '8px',
                    textAlign: 'right',
                    fontWeight: 'bold',
                    color: tx.direction === 'credit' ? '#2e7d32' : '#c62828',
                  }}
                >
                  {tx.direction === 'credit' ? '+' : '-'}
                  {tx.amount} CNY
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <SubscriptionsPanel
        candidates={subscriptions}
        records={storedSubscriptions}
        accountId={accounts.map((account) => account.account_id).sort()[0]}
        onRequestCancellation={setInputMessage}
      />

      {/* --- 2. AUDIT TRAIL LOG VIEWER --- */}
      <section style={{ borderTop: '2px solid #ccc', paddingTop: '16px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h3>🛡️ Bank Immutable Audit Trail ({auditLogs.length} events)</h3>
          <button
            onClick={() => setShowAudit(!showAudit)}
            style={{ padding: '4px 10px', cursor: 'pointer' }}
          >
            {showAudit ? '🔼 Hide Audit Log' : '🔽 Show Audit Log'}
          </button>
        </div>

        {showAudit && (
          <div style={{ maxHeight: '220px', overflowY: 'auto', background: '#263238', color: '#eceff1', padding: '10px', borderRadius: '4px', fontSize: '12px', fontFamily: 'monospace' }}>
            {auditLogs.length === 0 && <p>No audit events recorded yet.</p>}
            {auditLogs.map((log) => (
              <div key={log.audit_id} style={{ borderBottom: '1px solid #37474f', paddingBottom: '6px', marginBottom: '6px' }}>
                <span style={{ color: '#80cbc4' }}>[{new Date(log.timestamp).toLocaleTimeString()}]</span>{' '}
                <strong style={{ color: '#ffb74d' }}>{log.event_type}</strong> |{' '}
                <span>Action: <code>{log.action_id}</code></span> |{' '}
                <span style={{ color: '#a5d6a7' }}>Reason: {log.reason_code}</span>
              </div>
            ))}
          </div>
        )}
      </section>

    </div>
  );
}
