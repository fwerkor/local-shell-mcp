/** Default disclosure policy; manual user toggles are handled by the component. */
export function shouldExpandToolGroup({
  autoExpand,
  withinActivityPhase,
  hasPendingApproval,
  hasPendingAuthRequest,
}: {
  autoExpand: boolean;
  withinActivityPhase: boolean;
  hasPendingApproval: boolean;
  hasPendingAuthRequest: boolean;
}): boolean {
  return (autoExpand && !withinActivityPhase) || hasPendingApproval || hasPendingAuthRequest;
}
