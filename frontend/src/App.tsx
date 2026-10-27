// frontend/src/App.tsx
import { useState, useEffect, useRef } from 'react';
import { fetchAccounts, fetchTransactions, sendChatMessage, confirmAction, verifyAction, cancelAction, fetchActionStatus, continueAction, fetchSubscriptions, fetchStoredSubscriptions, fetchAuditLogs, fetchDemoInbox } from './api';
import type { Account, Transaction, ChatMessage, ActionProposal, SubscriptionCandidate, StoredSubscription, AuditEvent, DemoInboxMessage } from './api';
import { SubscriptionsPanel } from './SubscriptionsPanel';
import { ApprovalCard } from './ApprovalCard';
import type { ActionUiState } from './approvalState';
import { mergeApprovalState } from './approvalState';
import { Icon } from './Icon';
import banklyLogo from './assets/bankly.png';
import './App.css';

export default function App() {
  const [view, setView] = useState<'chat' | 'transactions' | 'subscriptions' | 'audit'>('chat');
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const composer = useRef<HTMLTextAreaElement>(null);
  const messageEnd = useRef<HTMLDivElement>(null);
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
      text: 'Hi Alice, I’m bank.ly (帮客力). I can help you understand your spending, check your balance, manage subscriptions, and prepare transfers.',
    },
  ]);
  const [inputMessage, setInputMessage] = useState<string>('');
  const [sending, setSending] = useState<boolean>(false);
  const deliveredUpdates = useRef(new Set<string>());
  const inFlightActions = useRef(new Set<string>());
  const [busyActions, setBusyActions] = useState<Record<string, boolean>>({});
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

  async function runAction(actionId: string, operation: () => Promise<void>) {
    if (inFlightActions.current.has(actionId)) return;
    inFlightActions.current.add(actionId);
    setBusyActions(prev => ({ ...prev, [actionId]: true }));
    try {
      await operation();
    } finally {
      inFlightActions.current.delete(actionId);
      setBusyActions(prev => ({ ...prev, [actionId]: false }));
    }
  }

  async function handleCancel(actionId: string, digest: string) {
    try {
      const result = await cancelAction(actionId, digest);
      setActionStates(prev => ({ ...prev, [actionId]: {
        ...prev[actionId], status: result.status, message: result.message,
        mfaCode: undefined, inboxMessage: undefined, error: undefined,
      } }));
    } catch (err: unknown) {
      const error = err instanceof Error ? err.message : 'Cancellation could not be applied';
      try {
        // A confirmation may have won the race, or the cancellation response
        // may have been lost after commit. Read bank state before labelling it.
        const approval = await fetchActionStatus(actionId);
        setActionStates(prev => ({ ...prev, [actionId]: {
          ...mergeApprovalState(prev[actionId], approval),
          message: approval.status === 'CANCELLED' ? 'Approval is cancelled. This ticket can no longer execute.'
            : approval.status === 'COMPLETED' ? 'The bank completed this action; cancellation was not applied.' : undefined,
          error: approval.status === 'CANCELLED' ? undefined : error,
        } }));
      } catch {
        setActionStates(prev => ({ ...prev, [actionId]: { ...prev[actionId],
          error: 'Cancellation outcome could not be verified. Retry cancellation to retrieve the bank outcome.',
        } }));
      }
    }
    await loadData();
    await updateConversation(actionId);
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
      await loadData();
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
      await loadData();
    }
    await updateConversation(actionId);
  }

  useEffect(() => {
    if (view === 'chat') messageEnd.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, sending, view]);

  function navigate(next: typeof view) {
    setView(next);
    setSidebarOpen(false);
  }

  function draftMessage(text: string) {
    navigate('chat');
    setInputMessage(text);
    requestAnimationFrame(() => composer.current?.focus());
  }

  function money(amount: string | number, currency = 'CNY') {
    const value = Number(amount);
    return Number.isFinite(value)
      ? new Intl.NumberFormat('en', { style: 'currency', currency, currencyDisplay: 'code' }).format(value)
      : `${amount} ${currency}`;
  }

  const navigation = [
    { id: 'chat', label: 'AI assistant', icon: 'chat' },
    { id: 'transactions', label: 'Transactions', icon: 'activity' },
    { id: 'subscriptions', label: 'Subscriptions', icon: 'repeat' },
    { id: 'audit', label: 'Activity & audit', icon: 'shield' },
  ] as const;
  const currentView = navigation.find(item => item.id === view)!;
  const locked = accounts.some(account => account.locked);

  return (
    <div className="bankly-app">
      {sidebarOpen && <button className="sidebar-backdrop" aria-label="Close navigation" onClick={() => setSidebarOpen(false)} />}
      <aside className={`sidebar ${sidebarOpen ? 'sidebar-open' : ''}`} aria-label="Main navigation">
        <a className="brand" href="#assistant" onClick={event => { event.preventDefault(); navigate('chat'); }}>
          <img className="brand-logo" src={banklyLogo} alt="bank.ly mascot logo" />
          <span><strong>bank<span className="brand-blue">.ly</span></strong><span className="brand-chinese" lang="zh">帮客力</span></span>
        </a>
        <button className="mobile-close icon-button" aria-label="Close navigation" onClick={() => setSidebarOpen(false)}><Icon name="close" /></button>
        <div className="workspace-label">YOUR WORKSPACE</div>
        <nav className="navigation">
          {navigation.map(item => <button key={item.id} className={`nav-item ${view === item.id ? 'is-active' : ''}`} aria-current={view === item.id ? 'page' : undefined} onClick={() => navigate(item.id)}>
            <Icon name={item.icon} /><span>{item.label}</span>{item.id === 'chat' && <span className="nav-tag">AI</span>}
          </button>)}
        </nav>
        <div className="sidebar-balance">
          <div className="balance-label"><Icon name="wallet" /><span>Your accounts</span><button className="icon-button" onClick={loadData} disabled={loading} aria-label="Refresh balances and banking data"><Icon name="refresh" className={loading ? 'is-spinning' : ''} width="15" height="15" /></button></div>
          {accounts.map(account => <div className="sidebar-account" key={account.account_id}>
            <strong>{money(account.balance, account.currency)}</strong>
            <div className="account-caption"><span className={`status-dot ${account.locked ? 'dot-warning' : ''}`} />{account.locked ? 'Account locked' : 'Available balance'}</div>
            <details className="account-details"><summary>Account details</summary><code>{account.account_id}</code></details>
          </div>)}
          {!accounts.length && <p className="muted">{loading ? 'Loading accounts…' : 'No accounts available'}</p>}
        </div>
        <div className="sidebar-note"><Icon name="shield" width="17" height="17" /><p>You stay in control.<br /><span>Review every financial action.</span></p></div>
        <div className="profile"><span className="profile-avatar">AW</span><div><strong>Alice Wang</strong><span>Demo account</span></div><span className="demo-label">DEMO</span></div>
      </aside>

      <main className="main-workspace">
        <header className="workspace-header">
          <div className="header-title"><button className="mobile-menu icon-button" aria-label="Open navigation" aria-expanded={sidebarOpen} onClick={() => setSidebarOpen(true)}><Icon name="menu" /></button><span>{currentView.label}</span>{view === 'chat' && <span className="header-version">bank.ly <span lang="zh">帮客力</span></span>}</div>
          <span className={`workspace-badge ${locked ? 'badge-warning' : ''}`}><span className={`status-dot ${locked ? 'dot-warning' : ''}`} />{locked ? 'Safety lock active' : 'Demo workspace'}</span>
        </header>

        {error && <div className="app-notice notice-error" role="alert"><span>{error}</span><button onClick={loadData} className="text-button">Try again</button></div>}
        {locked && <div className="app-notice notice-warning" role="alert"><Icon name="lock" /><span>Transfers and subscription cancellations are locked. Read-only queries remain available. A demo operator must review and reset an automatic safety lock before new actions can proceed.</span></div>}

        <section className="chat-view" hidden={view !== 'chat'} aria-label="Conversation with bank.ly">
          <div className="chat-scroll" role="log" aria-label="Chat messages" aria-live="polite" aria-relevant="additions">
            <div className="conversation-content">
              {messages.length === 1 ? <div className="welcome">
                <img className="welcome-logo" src={banklyLogo} alt="bank.ly 帮客力" />
                <span className="eyebrow">A LITTLE CLARITY FOR YOUR MONEY</span>
                <h1>Good to see you, Alice<span className="brand-blue">.</span></h1>
                <p>Your money, made simpler. Ask bank.ly to check a balance,<br className="desktop-break" /> make sense of spending, or prepare your next transfer.</p>
                <div className="suggestion-grid">
                  {[
                    { icon: 'wallet', label: 'Check my balance', detail: 'A clear picture of your account', prompt: 'What is my balance?' },
                    { icon: 'activity', label: 'Understand my spending', detail: 'See where your money goes', prompt: 'Analyze my spending' },
                    { icon: 'repeat', label: 'Review subscriptions', detail: 'Explore recurring charges', prompt: 'List my subscriptions' },
                    { icon: 'arrow', label: 'Prepare a transfer', detail: 'You review before anything moves', prompt: 'Transfer to Bob' },
                  ].map(item => <button className="suggestion" key={item.label} onClick={() => draftMessage(item.prompt)}><Icon name={item.icon as 'wallet' | 'activity' | 'repeat' | 'arrow'} /><strong>{item.label}</strong><span>{item.detail}</span></button>)}
                </div>
              </div> : messages.map((message, index) => <article key={index} className={`message message-${message.sender}`}>
                {message.sender === 'agent' && <div className="assistant-avatar" aria-hidden="true"><img src={banklyLogo} alt="" /></div>}
                <div className="message-body">
                  {message.sender === 'agent' && <div className="message-author">bank.ly <span lang="zh">帮客力</span></div>}
                  <div className="message-text">{message.text}</div>
                  {message.actions?.map(action => <ApprovalCard key={action.approval.action_id} action={action}
                    state={actionStates[action.approval.action_id]}
                    continuationError={continuationErrors[action.approval.action_id]}
                    busy={busyActions[action.approval.action_id]}
                    onConfirm={(id, digest) => runAction(id, () => handleConfirm(id, digest))}
                    onCancel={(id, digest) => runAction(id, () => handleCancel(id, digest))}
                    onVerify={(id, code) => runAction(id, () => handleVerify(id, code))}
                    onRetry={id => runAction(id, () => updateConversation(id))}
                    onCodeChange={(actionId, code) => setActionStates(prev => ({
                      ...prev, [actionId]: { ...prev[actionId],
                        status: prev[actionId]?.status ?? action.approval.status, mfaCode: code, error: undefined },
                    }))} />)}
                </div>
              </article>)}
              {sending && <div className="thinking" role="status"><span /><span /><span /><span className="thinking-label">bank.ly is thinking</span></div>}
              <div ref={messageEnd} />
            </div>
          </div>
          <div className="composer-area">
            <form className="composer" onSubmit={event => { event.preventDefault(); void handleSend(); }}>
              <label className="sr-only" htmlFor="bankly-message">Message bank.ly</label>
              <textarea ref={composer} id="bankly-message" rows={2} value={inputMessage} placeholder="Ask bank.ly anything about your money…"
                onChange={event => setInputMessage(event.target.value)}
                onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void handleSend(); } }} />
              <div className="composer-toolbar"><span><Icon name="shield" width="14" height="14" />Financial actions need your approval</span><button className="send-button" type="submit" disabled={sending || !inputMessage.trim()} aria-label="Send message"><Icon name="send" /></button></div>
            </form>
            <p className="composer-note">bank.ly can make mistakes. Review details before approving. <span>Synthetic banking demo.</span></p>
          </div>
        </section>

        <section className="data-view" hidden={view !== 'transactions'} aria-label="Recent transactions">
          <div className="page-heading"><div><span className="eyebrow">YOUR MONEY IN MOTION</span><h1>Transactions</h1><p>Your recent account activity, all in one place.</p></div><button className="secondary-button" onClick={loadData} disabled={loading}><Icon name="refresh" />Refresh</button></div>
          <div className="table-panel"><div className="panel-heading"><h2>Recent activity</h2><span className="count-badge">{transactions.length} transactions</span></div><div className="table-scroll"><table><thead><tr><th>Date</th><th>Merchant</th><th>Category</th><th className="text-right">Amount</th></tr></thead><tbody>
            {transactions.map(transaction => <tr key={transaction.transaction_id}><td className="date-cell">{new Date(transaction.timestamp).toLocaleDateString()}</td><td className="merchant-cell">{transaction.merchant}</td><td><span className="category-pill">{transaction.category}</span></td><td className={`amount-cell ${transaction.direction === 'credit' ? 'amount-credit' : ''}`}>{transaction.direction === 'credit' ? '+' : '−'}{money(transaction.amount)}</td></tr>)}
          </tbody></table></div>{!transactions.length && <div className="empty-state">{loading ? 'Loading activity…' : 'No transactions to show yet.'}</div>}</div>
        </section>

        <section className="data-view" hidden={view !== 'subscriptions'} aria-label="Subscriptions">
          <div className="page-heading"><div><span className="eyebrow">MAKE ROOM FOR WHAT MATTERS</span><h1>Subscriptions</h1><p>Understand recurring charges. Stay in control of your subscriptions.</p></div><button className="secondary-button" onClick={loadData} disabled={loading}><Icon name="refresh" />Refresh</button></div>
          <SubscriptionsPanel candidates={subscriptions} records={storedSubscriptions} accountId={accounts.map(account => account.account_id).sort()[0]} onRequestCancellation={draftMessage} />
        </section>

        <section className="data-view" hidden={view !== 'audit'} aria-label="Bank audit trail">
          <div className="page-heading"><div><span className="eyebrow">TRANSPARENCY AT EVERY STEP</span><h1>Activity &amp; audit</h1><p>A record of your banking actions and the checks behind them.</p></div><button className="secondary-button" onClick={loadData} disabled={loading}><Icon name="refresh" />Refresh</button></div>
          <div className="table-panel"><div className="panel-heading"><h2><Icon name="shield" />Bank audit trail</h2><button className="secondary-button" onClick={() => setShowAudit(!showAudit)} aria-expanded={showAudit}>{showAudit ? 'Hide Audit Log' : 'Show Audit Log'}<span className="count-badge">{auditLogs.length}</span></button></div>
            {showAudit ? <div className="audit-list">{auditLogs.length === 0 && <div className="empty-state">No audit events recorded yet.</div>}{auditLogs.map(log => <article key={log.audit_id} className="audit-event"><span className="audit-mark"><Icon name="shield" width="17" height="17" /></span><div><strong>{log.event_type}</strong><p>Reason: {log.reason_code}</p><details><summary>Action details</summary><code>{log.action_id}</code></details></div><time dateTime={log.timestamp}>{new Date(log.timestamp).toLocaleString()}</time></article>)}</div> : <div className="empty-state"><Icon name="shield" width="30" height="30" /><p>Your audit trail is ready to review.</p><span>Expand the log to see recorded decisions and actions.</span></div>}
          </div>
        </section>
      </main>
    </div>
  );
}
