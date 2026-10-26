import type { ActionStatus, ApprovalMetadata, ApprovalTier } from './api';

export interface ActionUiState {
  status?: ActionStatus;
  tier?: ApprovalTier;
  message?: string;
  mfaCode?: string;
  error?: string;
  inboxMessage?: string;
}

type TerminalStatus = 'COMPLETED' | 'REJECTED' | 'FAILED' | 'CANCELLED';
const terminal = (status?: ActionStatus): status is TerminalStatus =>
  !!status && ['COMPLETED', 'REJECTED', 'FAILED', 'CANCELLED'].includes(status);

export function mergeApprovalState(state: ActionUiState | undefined, approval: ApprovalMetadata): ActionUiState & Pick<ApprovalMetadata, 'status' | 'tier'> {
  // A delayed proposal/replay cannot reopen a terminal ticket or undo MFA.
  const previous = state?.status;
  const status = terminal(previous) ? previous
    : terminal(approval.status) ? approval.status
    : state?.status === 'PENDING_MFA' || approval.status === 'PENDING_MFA' ? 'PENDING_MFA'
    : state?.status ?? approval.status;
  return { ...state, status,
    tier: state?.tier === 'RED' || approval.tier === 'RED' || status === 'PENDING_MFA' ? 'RED' : 'YELLOW' };
}
