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
import ServerPreferencesGate from '~/components/System/ServerPreferencesGate';

const AuthLayout = () => (
  <AuthContextProvider>
    <ServerPreferencesGate>
      <Outlet />
    </ServerPreferencesGate>
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

const loadSkillsView = () =>
  import('~/components/Skills/layouts/SkillsView').then((m) => ({
    Component: m.default,
  }));

const baseEl = document.querySelector('base');
const baseHref = baseEl?.getAttribute('href') || '/';

export const router = createBrowserRouter(
  [
    // Provider callbacks open in a separate tab without a workspace login
    // cookie. These are intentionally outside AuthContextProvider: the latter
    // redirects unauthenticated pages to /login before the user can see the
    // completion outcome, even when Python serves the public SPA correctly.
    { path: 'oauth/success', element: <OAuthSuccess /> },
    { path: 'oauth/error', element: <OAuthError /> },
    {
      element: <AuthLayout />,
      errorElement: <RouteErrorBoundary />,
      children: [
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
              element: <Navigate to="/control/workspace" replace={true} />,
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
              path: 'skills',
              lazy: loadSkillsView,
            },
            {
              path: 'skills/new',
              lazy: loadSkillsView,
            },
            {
              path: 'skills/:skillId',
              lazy: loadSkillsView,
            },
            {
              path: 'skills/:skillId/edit',
              lazy: loadSkillsView,
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
