import { useId } from 'react';
import type { ActionProposal } from './api';
import type { ActionUiState } from './approvalState';
import { mergeApprovalState } from './approvalState';

interface Props {
  action: ActionProposal;
  state?: ActionUiState;
  continuationError?: string;
  busy?: boolean;
  onConfirm: (actionId: string, digest: string) => void;
  onCancel: (actionId: string, digest: string) => void;
  onVerify: (actionId: string, code: string) => void;
  onCodeChange: (actionId: string, code: string) => void;
  onRetry: (actionId: string) => void;
}

export function ApprovalCard({ action, state, continuationError, busy = false, onConfirm, onCancel, onVerify, onCodeChange, onRetry }: Props) {
  const otpInputId = useId();
  const { action_id: actionId, action_digest: digest } = action.approval;
  const { status, tier } = mergeApprovalState(state, action.approval);
  const terminalRefusal = ['FAILED', 'REJECTED'].includes(status);

  return (
    <div className="approval-card" aria-label={action.tool === 'request_transfer' ? 'Transfer approval' : 'Subscription cancellation approval'}>
      <div className="approval-heading">
        <strong>{action.tool === 'request_transfer' ? 'Review your transfer' : 'Review subscription cancellation'}</strong>
        <span className={`tier-badge ${tier === 'RED' ? 'tier-red' : ''}`}>Tier: {tier}</span>
      </div>
      <div className="approval-details">
        {action.tool === 'request_transfer' && <>
          <div className="approval-amount">{action.arguments.amount} {action.arguments.currency}</div>
          <div><strong>Recipient:</strong> <code>{action.arguments.recipient_id}</code></div>
        </>}
        {action.tool === 'request_subscription_cancel' && <div><strong>Subscription ID:</strong> <code>{action.arguments.subscription_id}</code></div>}
      </div>
      <details className="ticket-details"><summary>Approval details</summary><code>Action: {action.tool}</code><code>Ticket ID: {actionId}</code></details>
      <div className="approval-controls" aria-busy={busy}>
        {status === 'PENDING_CONFIRMATION' && <button disabled={busy} className="confirm-button" onClick={() => onConfirm(actionId, digest)}>Confirm &amp; Execute</button>}
        {status === 'PENDING_MFA' && <div className="mfa-section">
          <div className="demo-inbox"><small><strong>Demo inbox (simulated, no SMS/email sent)</strong></small><div>{state?.inboxMessage || 'No code yet. Check the backend console.'}</div></div>
          <label className="mfa-label" htmlFor={otpInputId}>Enter the OTP code from your demo inbox:</label>
          <div className="otp-row">
            <input id={otpInputId} type="text" inputMode="numeric" autoComplete="one-time-code" placeholder="6-digit code" value={state?.mfaCode || ''} onChange={event => onCodeChange(actionId, event.target.value)} />
            <button disabled={busy} className="confirm-button" onClick={() => onVerify(actionId, state?.mfaCode || '')}>Verify</button>
          </div>
          {state?.error && <div className="outcome-error" role="alert">{state.error}</div>}
        </div>}
        {(status === 'PENDING_CONFIRMATION' || status === 'PENDING_MFA') && <button disabled={busy} className="cancel-button" onClick={() => onCancel(actionId, digest)}>Cancel approval</button>}
        {status === 'COMPLETED' && <div className="outcome-message" role="status">{state?.message || 'Executed successfully!'}</div>}
        {status === 'CANCELLED' && <div className="outcome-message outcome-cancelled" role="status">Approval cancelled. This ticket can no longer execute.</div>}
        {terminalRefusal && <div className="outcome-error" role="alert">{state?.message || state?.error || `${status}.`}</div>}
        {status === 'PENDING_CONFIRMATION' && state?.error && <div className="outcome-error" role="alert">{state.error}</div>}
        {continuationError && <div className="continuation-notice"><small>{continuationError}</small><button disabled={busy} onClick={() => onRetry(actionId)}>Retry conversation update</button></div>}
      </div>
    </div>
  );
}
