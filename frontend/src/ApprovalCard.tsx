import type { ActionProposal } from './api';
import type { ActionUiState } from './approvalState';
import { mergeApprovalState } from './approvalState';

interface Props {
  action: ActionProposal;
  state?: ActionUiState;
  continuationError?: string;
  onConfirm: (actionId: string, digest: string) => void;
  onVerify: (actionId: string, code: string) => void;
  onCodeChange: (actionId: string, code: string) => void;
  onRetry: (actionId: string) => void;
}

export function ApprovalCard({ action, state, continuationError, onConfirm, onVerify, onCodeChange, onRetry }: Props) {
  const { action_id: actionId, action_digest: digest } = action.approval;
  const { status, tier } = mergeApprovalState(state, action.approval);
  const terminalRefusal = ['FAILED', 'REJECTED', 'CANCELLED'].includes(status);

  return (
    <div style={{ background: '#fff', border: `2px solid ${tier === 'RED' ? '#d32f2f' : '#fbc02d'}`,
      borderRadius: '6px', padding: '10px', color: '#333', marginTop: '8px', fontSize: '13px' }}>
      <div>
        <strong>📋 Action:</strong> <code>{action.tool}</code>
        <span style={{ marginLeft: '8px', padding: '2px 6px', borderRadius: '4px',
          background: tier === 'RED' ? '#ffebee' : '#fffde7',
          color: tier === 'RED' ? '#d32f2f' : '#f57f17', fontWeight: 'bold' }}>
          Tier: {tier}
        </span>
      </div>
      {action.tool === 'request_transfer' && (
        <>
          <div style={{ marginTop: '4px' }}><strong>Amount:</strong> {action.arguments.amount} {action.arguments.currency}</div>
          <div><strong>Recipient:</strong> <code>{action.arguments.recipient_id}</code></div>
        </>
      )}
      {action.tool === 'request_subscription_cancel' && (
        <div><strong>Subscription ID:</strong> <code>{action.arguments.subscription_id}</code></div>
      )}
      <div style={{ color: '#777', fontSize: '11px', marginTop: '4px' }}>
        Ticket ID: <code>{actionId}</code>
        <div style={{ marginTop: '8px', paddingTop: '6px', borderTop: '1px dashed #ccc' }}>
          {status === 'PENDING_CONFIRMATION' && (
            <button onClick={() => onConfirm(actionId, digest)}
              style={{ padding: '4px 10px', background: '#2e7d32', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer', fontWeight: 'bold' }}>
              ✅ Confirm &amp; Execute
            </button>
          )}
          {status === 'PENDING_MFA' && (
            <div style={{ background: '#fff3e0', padding: '6px', borderRadius: '4px' }}>
              <div style={{ background: '#fff', border: '1px dashed #e65100', padding: '6px', borderRadius: '4px', marginBottom: '6px' }}>
                <small style={{ fontWeight: 'bold' }}>📨 Demo inbox (simulated, no SMS/email sent)</small>
                <div><small>{state?.inboxMessage || 'No code yet. Check the backend console.'}</small></div>
              </div>
              <small style={{ color: '#e65100', fontWeight: 'bold' }}>🔒 Enter the OTP code from your demo inbox:</small>
              <div style={{ display: 'flex', gap: '4px', marginTop: '4px' }}>
                <input type="text" placeholder="6-digit code" value={state?.mfaCode || ''}
                  onChange={e => onCodeChange(actionId, e.target.value)} style={{ padding: '4px', width: '100px' }} />
                <button onClick={() => onVerify(actionId, state?.mfaCode || '')}
                  style={{ padding: '4px 8px', background: '#d32f2f', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer' }}>
                  Verify
                </button>
              </div>
              {state?.error && <small style={{ color: '#c62828' }}>⚠️ {state.error}</small>}
            </div>
          )}
          {status === 'COMPLETED' && (
            <div style={{ color: '#2e7d32', fontWeight: 'bold' }}>🎉 {state?.message || 'Executed successfully!'}</div>
          )}
          {terminalRefusal && (
            <div style={{ color: '#c62828', fontWeight: 'bold' }}>❌ {state?.message || state?.error || `${status}.`}</div>
          )}
          {status === 'PENDING_CONFIRMATION' && state?.error && (
            <div style={{ color: '#c62828' }}>{state.error}</div>
          )}
          {continuationError && (
            <div><small>{continuationError}</small>{' '}
              <button onClick={() => onRetry(actionId)}>Retry conversation update</button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
