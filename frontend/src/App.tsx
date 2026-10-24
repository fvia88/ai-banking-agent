// frontend/src/App.tsx
import { useState, useEffect } from 'react';
import { fetchAccounts, fetchTransactions, sendChatMessage, confirmAction, verifyAction, fetchSubscriptions, fetchStoredSubscriptions, fetchAuditLogs, fetchDemoInbox } from './api';
import type { Account, Transaction, ChatMessage, SubscriptionCandidate, StoredSubscription, AuditEvent, DemoInboxMessage } from './api';
import { SubscriptionsPanel } from './SubscriptionsPanel';

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
  const [actionStates, setActionStates] = useState<
      Record<string, { status: string; message?: string; mfaCode?: string; error?: string; inboxMessage?: string }>
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

  async function handleSend() {
    if (!inputMessage.trim() || sending) return;

    const userText = inputMessage.trim();
    setInputMessage('');
    
    // Append user message immediately
    setMessages((prev) => [...prev, { sender: 'user', text: userText }]);
    setSending(true);

    try {
      const response = await sendChatMessage(userText);
      
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

  // handle clicking confirm
  async function handleConfirm(actionId: string, digest: string) {
    try {
      const res = await confirmAction(actionId, digest);
      if (res.status === 'PENDING_MFA') {
        setActionStates((prev) => ({
          ...prev,
          [actionId]: { status: 'PENDING_MFA', message: res.message, mfaCode: '' },
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
          [actionId]: { status: 'COMPLETED', message: res.message },
        }));
        await loadData(); // Auto-refreshes balance!
      }
    } catch (err: unknown) {
      setActionStates((prev) => ({
        ...prev,
        [actionId]: { status: 'FAILED', error: err instanceof Error ? err.message : 'Failed' },
      }));
    }
  }

  // handle entering the MFA code
  async function handleVerify(actionId: string, code: string) {
    try {
      const res = await verifyAction(actionId, code);
      if (res.status === 'COMPLETED') {
        setActionStates((prev) => ({
          ...prev,
          [actionId]: { status: 'COMPLETED', message: res.message },
        }));
        await loadData(); // Auto-refreshes balance!
      }
    } catch (err: unknown) {
      setActionStates((prev) => ({
        ...prev,
        [actionId]: { ...prev[actionId], error: err instanceof Error ? err.message : 'Invalid code' },
      }));
    }
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
                    {m.actions.map((act, aIdx) => (
                      <div
                        key={aIdx}
                        style={{
                          background: '#fff',
                          border: `2px solid ${act.arguments.tier === 'RED' ? '#d32f2f' : '#fbc02d'}`,
                          borderRadius: '6px',
                          padding: '10px',
                          color: '#333',
                          marginTop: '8px',
                          fontSize: '13px',
                        }}
                      >
                        <div>
                          <strong>📋 Action:</strong> <code>{act.tool}</code>
                          <span
                            style={{
                              marginLeft: '8px',
                              padding: '2px 6px',
                              borderRadius: '4px',
                              background: act.arguments.tier === 'RED' ? '#ffebee' : '#fffde7',
                              color: act.arguments.tier === 'RED' ? '#d32f2f' : '#f57f17',
                              fontWeight: 'bold',
                            }}
                          >
                            Tier: {act.arguments.tier || 'YELLOW'}
                          </span>
                        </div>

                        {act.arguments.amount && (
                          <div style={{ marginTop: '4px' }}>
                            <strong>Amount:</strong> {act.arguments.amount} {act.arguments.currency}
                          </div>
                        )}
                        {act.arguments.recipient_id && (
                          <div>
                            <strong>Recipient:</strong> <code>{act.arguments.recipient_id}</code>
                          </div>
                        )}
                        {act.arguments.subscription_id && (
                          <div>
                            <strong>Subscription ID:</strong> <code>{act.arguments.subscription_id}</code>
                          </div>
                        )}
                        {act.arguments.action_id && (
                          <div style={{ color: '#777', fontSize: '11px', marginTop: '4px' }}>
                            Ticket ID: <code>{act.arguments.action_id}</code>
                            {act.arguments.action_id && act.arguments.action_digest && (
                              <div style={{ marginTop: '8px', paddingTop: '6px', borderTop: '1px dashed #ccc' }}>
                                {/* 1. Confirm Button (Shown if not confirmed yet) */}
                                {(!actionStates[act.arguments.action_id] || actionStates[act.arguments.action_id].status === 'PENDING_CONFIRMATION') && (
                              <button
                                onClick={() => handleConfirm(act.arguments.action_id!, act.arguments.action_digest!)}
                                style={{ padding: '4px 10px', background: '#2e7d32', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer', fontWeight: 'bold' }}
                              >
                                ✅ Confirm & Execute
                              </button>
                            )}

                            {/* 2. MFA Input (Shown if Red tier) */}
                            {actionStates[act.arguments.action_id]?.status === 'PENDING_MFA' && (
                              <div style={{ background: '#fff3e0', padding: '6px', borderRadius: '4px' }}>
                                <div style={{ background: '#fff', border: '1px dashed #e65100', padding: '6px', borderRadius: '4px', marginBottom: '6px' }}>
                                  <small style={{ fontWeight: 'bold' }}>📨 Demo inbox (simulated, no SMS/email sent)</small>
                                  <div><small>{actionStates[act.arguments.action_id]?.inboxMessage || 'No code yet. Check the backend console.'}</small></div>
                                </div>
                                <small style={{ color: '#e65100', fontWeight: 'bold' }}>🔒 Enter the OTP code from your demo inbox:</small>
                                <div style={{ display: 'flex', gap: '4px', marginTop: '4px' }}>
                                  <input
                                    type="text"
                                    placeholder="6-digit code"
                                    value={actionStates[act.arguments.action_id]?.mfaCode || ''}
                                    onChange={(e) => {
                                      const val = e.target.value;
                                      setActionStates((prev) => ({
                                        ...prev,
                                        [act.arguments.action_id!]: { ...prev[act.arguments.action_id!], mfaCode: val, error: undefined },
                                      }));
                                    }}
                                    style={{ padding: '4px', width: '100px' }}
                                  />
                                  <button
                                    onClick={() => handleVerify(act.arguments.action_id!, actionStates[act.arguments.action_id!]?.mfaCode || '')}
                                    style={{ padding: '4px 8px', background: '#d32f2f', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer' }}
                                  >
                                    Verify
                                  </button>
                                </div>
                                {actionStates[act.arguments.action_id]?.error && (
                                  <small style={{ color: '#c62828' }}>⚠️ {actionStates[act.arguments.action_id]?.error}</small>
                                )}
                              </div>
                            )}

                            {/* 3. Completed Badge */}
                            {actionStates[act.arguments.action_id]?.status === 'COMPLETED' && (
                              <div style={{ color: '#2e7d32', fontWeight: 'bold' }}>
                                🎉 {actionStates[act.arguments.action_id]?.message || 'Executed successfully!'}
                              </div>
                            )}

                            {/* 4. Failed Badge */}
                            {actionStates[act.arguments.action_id]?.status === 'FAILED' && (
                              <div style={{ color: '#c62828', fontWeight: 'bold' }}>
                                ❌ {actionStates[act.arguments.action_id]?.error || 'Failed.'}
                              </div>
                            )}
                          </div>
                        )}
                          </div>
                        )}
                      </div>
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
