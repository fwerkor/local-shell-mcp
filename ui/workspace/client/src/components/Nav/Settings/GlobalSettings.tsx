import { lazy, Suspense, useEffect } from 'react';
import { useRecoilState } from 'recoil';
import { useLocation, useNavigate } from 'react-router-dom';
import { settingsTabState } from './state';

const SettingsDialog = lazy(() => import('./Dialog'));

export default function GlobalSettings() {
  const [tab, setTab] = useRecoilState(settingsTabState);
  const { pathname, hash } = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    if (pathname.replace(/\/+$/, '') !== '/control/settings') return;
    setTab(hash === '#models' ? 'models' : 'controller');
    navigate('/control/overview', { replace: true });
  }, [pathname, hash, navigate, setTab]);

  if (tab === null) return null;

  return (
    <Suspense fallback={null}>
      <SettingsDialog
        key={tab}
        open
        initialTab={tab}
        onOpenChange={(open) => {
          if (!open) setTab(null);
        }}
      />
    </Suspense>
  );
}
