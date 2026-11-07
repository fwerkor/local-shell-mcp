/** Single-user login entry. LSM remains the authentication authority. */
export default function Login() {
  const origin = document.querySelector<HTMLMetaElement>('meta[name="lsm-parent-origin"]')?.content;
  const url = origin ? origin.replace(/\/$/, '') + '/ui#/hosted-chat' : '/ui#/hosted-chat';
  return (
    <div className="space-y-4 text-center">
      <p className="text-sm text-text-secondary">
        Access to this workspace is controlled by local-shell-mcp.
      </p>
      <a
        href={url}
        target="_top"
        className="block w-full rounded-xl bg-surface-active-alt px-5 py-3 text-sm font-semibold text-text-primary transition-colors hover:bg-surface-hover"
      >
        Continue with LSM
      </a>
      <p className="text-xs text-text-secondary">
        No separate chat account or password is required.
      </p>
    </div>
  );
}
