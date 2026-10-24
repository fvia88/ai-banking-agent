import type { StoredSubscription, SubscriptionCandidate } from './api';

interface Props {
  candidates: SubscriptionCandidate[];
  records: StoredSubscription[];
  accountId?: string;
  onRequestCancellation: (message: string) => void;
}

export function SubscriptionsPanel({ candidates, records, accountId, onRequestCancellation }: Props) {
  return (
    <section style={{ marginBottom: '24px', borderTop: '2px solid #ccc', paddingTop: '16px' }}>
      <h3>Subscriptions</h3>
      <p>Account: <code>{accountId || 'No account available'}</code></p>
      <h4>Recurring-charge evidence</h4>
      <p>Patterns in past charges do not establish an active subscription or cancellation permission.</p>
      {candidates.length === 0 && <p>No recurring-charge patterns detected in this account's history.</p>}
      <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
        {candidates.map((candidate) => (
          <div key={candidate.subscription_id} style={{ border: '1px solid #ff9800', borderRadius: '6px', padding: '12px', background: '#fff8e1' }}>
            <strong>{candidate.merchant}</strong>
            <div>{candidate.estimated_amount} CNY / {candidate.cadence}</div>
            <div>{candidate.confidence < 0.7 ? 'Possible recurring charge' : 'Recurring pattern'}</div>
            <small>Evidence confidence: {(candidate.confidence * 100).toFixed(0)}% · {candidate.evidence_transaction_ids.length} charges</small>
            <details>
              <summary>Supporting transactions</summary>
              <ul>{candidate.evidence_transaction_ids.map((id) => <li key={id}><code>{id}</code></li>)}</ul>
            </details>
          </div>
        ))}
      </div>
      <h4>Verified subscription records</h4>
      <p>Status comes from stored demo records. Merchant cancellation is simulated and requires your confirmation.</p>
      {records.length === 0 && <p>No verified subscription records for this account.</p>}
      <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
        {records.map((record) => {
          const canCancel = record.status === 'active' && record.cancellation_supported;
          return (
            <div key={record.subscription_id} style={{ border: '1px solid #ccc', borderRadius: '6px', padding: '12px' }}>
              <strong>{record.merchant}</strong>
              <div>{record.estimated_amount} CNY / {record.cadence}</div>
              <div>Status: {record.status === 'cancelled' ? 'Cancelled (simulated)' : 'Active'}</div>
              <div><small>{record.status === 'cancelled' ? 'Historical charges remain visible as evidence.' : record.cancellation_supported ? 'Simulated cancellation supported' : 'Cancellation not supported'}</small></div>
              <button
                disabled={!canCancel}
                onClick={() => onRequestCancellation(`Cancel ${record.merchant} subscription`)}
                style={{ marginTop: '8px', padding: '4px 8px', cursor: canCancel ? 'pointer' : 'default' }}
              >
                {record.status === 'cancelled' ? 'Already cancelled' : canCancel ? 'Request cancellation in chat' : 'Cancellation unavailable'}
              </button>
            </div>
          );
        })}
      </div>
    </section>
  );
}
