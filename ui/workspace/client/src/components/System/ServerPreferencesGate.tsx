import { useEffect, useState, type ReactNode } from 'react';
import { useLocalize } from '~/hooks';
import { useAuthContext } from '~/hooks/AuthContext';
import { serverPreferences } from '~/store/serverPreferences';
import { useToastContext } from '@librechat/client';

/** Hydrate account settings before mounting the authenticated chat tree. */
export default function ServerPreferencesGate({ children }: { children: ReactNode }) {
  const { isAuthenticated, user } = useAuthContext();
  const owner = isAuthenticated ? user?.id : undefined;
  const [loadedOwner, setLoadedOwner] = useState<string>();
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const { showToast } = useToastContext();
  const localize = useLocalize();

  useEffect(() => {
    const notify = () =>
      showToast({ message: localize('com_ui_error_updating_preferences'), status: 'error' });
    window.addEventListener('lsm:preference-save-error', notify);
    return () => window.removeEventListener('lsm:preference-save-error', notify);
  }, [showToast, localize]);

  useEffect(() => {
    let active = true;
    setLoadedOwner(undefined);
    setFailed(false);
    if (owner) {
      serverPreferences
        .load(owner)
        .then((loaded) => {
          if (active && loaded) setLoadedOwner(owner);
        })
        .catch(() => {
          if (active) setFailed(true);
        });
    }
    return () => {
      active = false;
      serverPreferences.reset();
    };
  }, [owner, attempt]);

  if (isAuthenticated && (!owner || owner !== loadedOwner)) {
    return (
      <div role="status" className="flex min-h-screen items-center justify-center gap-3">
        {failed ? (
          <>
            <span>{localize('com_ui_error_updating_preferences')}</span>
            <button className="underline" onClick={() => setAttempt((n) => n + 1)}>
              {localize('com_ui_retry')}
            </button>
          </>
        ) : (
          <span>{localize('com_ui_loading')}</span>
        )}
      </div>
    );
  }
  return <>{children}</>;
}
