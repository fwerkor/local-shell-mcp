import { createBrowserRouter, Navigate, Outlet } from 'react-router-dom';
import { ApiErrorWatcher } from '~/components/Auth';
import LsmLogin from '~/components/LSM/Login';
import { MarketplaceProvider } from '~/components/Agents/MarketplaceContext';
import AgentMarketplace from '~/components/Agents/Marketplace';
import { AuthContextProvider } from '~/hooks/AuthContext';
import RouteErrorBoundary from './RouteErrorBoundary';
import LoginLayout from './Layouts/Login';
import ChatRoute from './ChatRoute';
import LsmControl from '~/components/LSM/Control';
import Search from './Search';
import { OAuthError, OAuthSuccess } from '~/components/OAuth';
import Root from './Root';

const AuthLayout = () => (
  <AuthContextProvider>
    <Outlet />
    <ApiErrorWatcher />
  </AuthContextProvider>
);

const loadProjectsView = () =>
  import('~/components/Projects').then((m) => ({
    Component: m.ProjectsView,
  }));

const loadProjectWorkspace = () =>
  import('~/components/Projects').then((m) => ({
    Component: m.ProjectWorkspace,
  }));

const baseEl = document.querySelector('base');
const baseHref = baseEl?.getAttribute('href') || '/';

export const router = createBrowserRouter(
  [
    {
      element: <AuthLayout />,
      errorElement: <RouteErrorBoundary />,
      children: [
        // OAuth callbacks open in a separate tab. These pages must render
        // without the authenticated chat layout or the login redirect gate.
        { path: 'oauth/success', element: <OAuthSuccess /> },
        { path: 'oauth/error', element: <OAuthError /> },
        {
          path: '/',
          element: <LoginLayout />,
          children: [
            {
              path: 'login',
              element: <LsmLogin />,
            },
          ],
        },
        {
          path: '/',
          element: <Root />,
          children: [
            {
              index: true,
              element: <Navigate to="/control/overview" replace={true} />,
            },
            {
              path: 'control/:section?',
              element: <LsmControl />,
            },
            {
              path: 'c/:conversationId?',
              element: <ChatRoute />,
            },
            {
              path: 'search',
              element: <Search />,
            },
            {
              path: 'projects',
              lazy: loadProjectsView,
            },
            {
              path: 'projects/:projectId',
              lazy: loadProjectWorkspace,
            },
            {
              path: 'agents',
              element: (
                <MarketplaceProvider>
                  <AgentMarketplace />
                </MarketplaceProvider>
              ),
            },
            {
              path: 'agents/:category',
              element: (
                <MarketplaceProvider>
                  <AgentMarketplace />
                </MarketplaceProvider>
              ),
            },
          ],
        },
      ],
    },
  ],
  { basename: baseHref },
);
