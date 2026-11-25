import { renderHook } from '@testing-library/react';
import React from 'react';
import { AuthContext } from '~/hooks/AuthContext';
import useSideNavLinks from './useSideNavLinks';

jest.mock('~/hooks/AuthContext', () => ({
  AuthContext: require('react').createContext(undefined),
}));
jest.mock('~/hooks', () => ({
  useAgentCapabilities: () => ({}),
  useGetAgentsConfig: () => ({}),
  useHasAccess: () => false,
}));
jest.mock('@librechat/client', () => ({ MCPIcon: () => null, AttachmentIcon: () => null }));
jest.mock('~/components/SidePanel/MCPBuilder/LsmNestedMcpPanel', () => () => null);
jest.mock('~/components/SidePanel/Agents/AgentPanelSwitch', () => () => null);
jest.mock('~/components/SidePanel/Bookmarks/BookmarkPanel', () => () => null);
jest.mock('~/components/SidePanel/Builder/PanelSwitch', () => () => null);
jest.mock('~/components/SidePanel/Schedules', () => ({ SchedulePanel: () => null }));
jest.mock('~/components/SidePanel/Memories', () => ({ MemoryPanel: () => null }));
jest.mock('~/components/SidePanel/Files/Panel', () => () => null);
jest.mock('~/components/Prompts', () => ({ PromptsAccordion: () => null }));
jest.mock('~/components/Skills', () => ({ SkillsAccordion: () => null }));

describe('native scheduled chat navigation', () => {
  const options = { keyProvided: false, interfaceConfig: {}, endpointsConfig: {} };

  it.each([true, false])('uses the authenticated session (authenticated=%s)', (isAuthenticated) => {
    const auth = { isAuthenticated } as React.ContextType<typeof AuthContext>;
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <AuthContext.Provider value={auth}>{children}</AuthContext.Provider>
    );
    const { result } = renderHook(() => useSideNavLinks(options), { wrapper });
    expect(result.current.some((link) => link.id === 'schedules')).toBe(isAuthenticated);
    expect(result.current.some((link) => link.id === 'parameters')).toBe(false);
    if (isAuthenticated) {
      expect(result.current[0].id).toBe('schedules');
    }
  });
});
