import { useEffect, useState } from 'react';
import { Outlet, useNavigate } from 'react-router-dom';
import type { TStartupConfig } from 'librechat-data-provider';
import { REDIRECT_PARAM, hasStoredRedirect } from '~/utils';
import { useLocalize } from '~/hooks';
import { useGetStartupConfig } from '~/data-provider';
import AuthLayout from '~/components/Auth/AuthLayout';

export default function StartupLayout({ isAuthenticated }: { isAuthenticated?: boolean }) {
  const [startupConfig, setStartupConfig] = useState<TStartupConfig | null>(null);
  const {
    data,
    isFetching,
    error: startupConfigError,
  } = useGetStartupConfig({
    enabled: isAuthenticated ? startupConfig === null : true,
  });
  const localize = useLocalize();
  const navigate = useNavigate();

  useEffect(() => {
    if (isAuthenticated) {
      const hasPendingRedirect =
        new URLSearchParams(window.location.search).has(REDIRECT_PARAM) || hasStoredRedirect();
      if (!hasPendingRedirect) {
        navigate('/control/overview', { replace: true });
      }
    }
    if (data) {
      setStartupConfig(data);
    }
  }, [isAuthenticated, navigate, data]);

  useEffect(() => {
    document.title = startupConfig?.appTitle || 'local-shell-mcp';
  }, [startupConfig?.appTitle]);

  return (
    <AuthLayout
      header={localize('com_auth_welcome_back')}
      isFetching={isFetching}
      startupConfig={startupConfig}
      startupConfigError={startupConfigError}
    >
      <Outlet />
    </AuthLayout>
  );
}
