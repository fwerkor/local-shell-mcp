/** A retry is an ephemeral notification, never assistant message content. */
export function modelRetryNotice(
  data: unknown,
  label: string,
): string | undefined {
  if (data == null || typeof data !== 'object') {
    return;
  }
  const { attempt, maximum, delaySeconds, httpStatus } = data as Record<
    string,
    unknown
  >;
  if (
    typeof attempt !== 'number' ||
    !Number.isInteger(attempt) ||
    typeof maximum !== 'number' ||
    !Number.isInteger(maximum) ||
    attempt < 1 ||
    attempt > maximum ||
    typeof delaySeconds !== 'number' ||
    !Number.isFinite(delaySeconds) ||
    delaySeconds < 0
  ) {
    return;
  }
  const status = typeof httpStatus === 'number' ? `HTTP ${httpStatus} · ` : '';
  return `${status}${label} ${attempt}/${maximum} · ${Math.ceil(delaySeconds)}s`;
}
