import type { StoredSubscription, SubscriptionCandidate } from './api';

interface Props {
  candidates: SubscriptionCandidate[];
  records: StoredSubscription[];
  accountId?: string;
  onRequestCancellation: (message: string) => void;
}

export function SubscriptionsPanel({ candidates, records, accountId, onRequestCancellation }: Props) {
  return (
    <div className="subscriptions-panel">
      <p className="subscription-account">Selected account: <code>{accountId || 'No account available'}</code></p>
      <div className="section-heading"><h2>Verified subscription records</h2><span className="count-badge">{records.length}</span></div>
      <p className="section-description">Status comes from stored demo records. Merchant cancellation is simulated and requires your confirmation.</p>
      {records.length === 0 && <div className="empty-state">No verified subscription records for this account.</div>}
      <div className="subscription-grid">
        {records.map(record => {
          const canCancel = record.status === 'active' && record.cancellation_supported;
          return <div key={record.subscription_id} className={`subscription-card ${record.status === 'cancelled' ? 'is-cancelled' : ''}`}>
            <strong>{record.merchant}</strong>
            <div className="subscription-price">{record.estimated_amount} CNY<span>/ {record.cadence}</span></div>
            <div className="subscription-status">Status: {record.status === 'cancelled' ? 'Cancelled (simulated)' : 'Active'}</div>
            <small>{record.status === 'cancelled' ? 'Historical charges remain visible as evidence.' : record.cancellation_supported ? 'Simulated cancellation supported' : 'Cancellation not supported'}</small>
            <button className="secondary-button" disabled={!canCancel} onClick={() => onRequestCancellation(`Cancel ${record.merchant} subscription`)}>{record.status === 'cancelled' ? 'Already cancelled' : canCancel ? 'Request cancellation in chat' : 'Cancellation unavailable'}</button>
          </div>;
        })}
      </div>
      <div className="section-heading"><h2>Recurring-charge evidence</h2><span className="count-badge">{candidates.length}</span></div>
      <p className="section-description">Patterns in past charges do not establish an active subscription or cancellation permission.</p>
      {candidates.length === 0 && <div className="empty-state">No recurring-charge patterns detected in this account’s history.</div>}
      <div className="subscription-grid">
        {candidates.map(candidate => <div key={candidate.subscription_id} className="subscription-card">
          <strong>{candidate.merchant}</strong>
          <div className="subscription-price">{candidate.estimated_amount} CNY<span>/ {candidate.cadence}</span></div>
          <div className="subscription-status">{candidate.confidence < 0.7 ? 'Possible recurring charge' : 'Recurring pattern'}</div>
          <small>Evidence confidence: {(candidate.confidence * 100).toFixed(0)}% · {candidate.evidence_transaction_ids.length} charges</small>
          <details><summary>Supporting transactions</summary><ul>{candidate.evidence_transaction_ids.map(id => <li key={id}><code>{id}</code></li>)}</ul></details>
        </div>)}
      </div>
    </div>
  );
}
