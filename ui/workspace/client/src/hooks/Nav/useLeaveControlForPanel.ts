import { useCallback } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

/** Sidebar panels live alongside chat, not inside the controller page. */
export default function useLeaveControlForPanel() {
  const { pathname } = useLocation();
  const navigate = useNavigate();

  return useCallback(
    (panelId: string) => {
      if (
        panelId !== 'lsm-control' &&
        (pathname === '/control' || pathname.startsWith('/control/'))
      ) {
        navigate('/c/new');
      }
    },
    [navigate, pathname],
  );
}
