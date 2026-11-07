import useLocalize from '~/hooks/useLocalize';
/** Single-user login entry. LSM remains the authentication authority. */
export default function Login() {
  const localize = useLocalize();
  const url = document.querySelector<HTMLMetaElement>('meta[name="lsm-ui-entry-url"]')?.content ||
    '/ui/#/hosted-chat';
  return (
    <div className="space-y-4 text-center">
      <p className="text-sm text-text-secondary">
        {localize('com_lsm_login_description')}
      </p>
      <a
        href={url}
        target="_top"
        className="block w-full rounded-xl bg-surface-active-alt px-5 py-3 text-sm font-semibold text-text-primary transition-colors hover:bg-surface-hover"
      >
        {localize('com_lsm_login_continue')}
      </a>
      <p className="text-xs text-text-secondary">
        {localize('com_lsm_login_info')}
      </p>
    </div>
  );
}
