import { fireEvent, render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import ChatToolManagement from './ChatToolManagement';

let mockEnabled = false;
let mockOptedOut = false;
let mockCanEdit = true;
let mockAvailable = true;
let mockMcpSelected: string[] | null = [];
const mockToggle = jest.fn();
const mockToggleServer = jest.fn();

jest.mock('~/hooks', () => ({
  useLocalize: () => (key: string) => key,
  useHasAccess: () => true,
  useAuthContext: () => ({ user: { personalization: { memories: !mockOptedOut } } }),
}));
jest.mock('~/Providers', () => ({
  useBadgeRowContext: () => ({
    agentsConfig: { capabilities: ['web_search', 'memory'] },
    webSearch: { toggleState: true },
    features: {
      current: { memory: mockEnabled },
      registered: [{ name: 'snowluma', enabled: true, tool_count: 12 }],
      selected: mockMcpSelected,
      servers: {},
      canEdit: mockCanEdit,
      toggle: mockToggle,
      toggleServer: mockToggleServer,
    },
  }),
}));
jest.mock('~/data-provider', () => ({
  useGetStartupConfig: () => ({ data: { interface: { memories: mockAvailable } } }),
}));
jest.mock('@librechat/client', () => ({
  TooltipAnchor: ({ render }: { render: ReactNode }) => render,
  PinIcon: () => null,
}));
jest.mock(
  '~/components/SidePanel/Agents/Tools/ToolManagementDialog',
  () =>
    ({
      open,
      children,
      onSelectKind,
    }: {
      open: boolean;
      children: ReactNode;
      onSelectKind: (kind: string) => void;
    }) =>
      open ? (
        <div role="dialog">
          <button onClick={() => onSelectKind('tool')}>Machines</button>
          {children}
        </div>
      ) : null,
);
jest.mock(
  '~/components/SidePanel/Agents/Tools/ToolCard',
  () =>
    ({
      item,
      selected,
      disabled,
      onToggle,
    }: {
      item: { name: string };
      selected: boolean;
      disabled: boolean;
      onToggle: () => void;
    }) => (
      <button type="button" aria-pressed={selected} disabled={disabled} onClick={onToggle}>
        {item.name}
      </button>
    ),
);
jest.mock('~/components/SidePanel/Agents/Tools/LsmAgentMachineAccess', () => ({
  useLsmMachines: () => ({ data: { machines: [] } }),
}));
jest.mock('~/components/SidePanel/Agents/Tools/LsmExternalMcpServers', () => ({
  ExternalMcpServerList: ({
    selected,
    onToggle,
  }: {
    selected: string[];
    onToggle: (name: string, value: boolean) => void;
  }) => (
    <button
      aria-pressed={selected?.includes('snowluma')}
      onClick={() => onToggle('snowluma', true)}
    >
      snowluma
    </button>
  ),
}));
jest.mock('./LsmChatPermissions', () => ({
  __esModule: true,
  default: () => <div>Permission controls</div>,
  useDraftMachinePermissions: () => ({}),
}));

beforeEach(() => {
  mockEnabled = false;
  mockOptedOut = false;
  mockCanEdit = true;
  mockAvailable = true;
  mockMcpSelected = [];
  mockToggle.mockClear();
  mockToggleServer.mockClear();
});

function openPanel() {
  const view = render(<ChatToolManagement />);
  fireEvent.click(screen.getByRole('button', { name: 'com_lsm_ui_tool_options' }));
  return view;
}

test('the composer opens one shared panel with memory, machines and individual MCP servers', () => {
  openPanel();
  expect(screen.getByRole('dialog')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'com_ui_memory' })).toHaveAttribute(
    'aria-pressed',
    'false',
  );
  expect(screen.getByText('Permission controls')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'com_ui_memory' }));
  expect(mockToggle).toHaveBeenCalledWith('memory', true);
  fireEvent.click(screen.getByRole('button', { name: 'snowluma' }));
  expect(mockToggleServer).toHaveBeenCalledWith('snowluma', true);
  fireEvent.click(screen.getByRole('button', { name: 'Machines' }));
  expect(screen.getByText('Permission controls')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'snowluma' })).not.toBeInTheDocument();
});

test('keeps permission management reachable when memory is disabled or unavailable', () => {
  mockAvailable = false;
  mockCanEdit = false;
  openPanel();
  expect(screen.queryByRole('button', { name: 'com_ui_memory' })).not.toBeInTheDocument();
  expect(screen.getByText('Permission controls')).toBeInTheDocument();
});

test('global memory opt-out does not change the stored conversation preference', () => {
  mockEnabled = true;
  mockOptedOut = true;
  openPanel();
  const memory = screen.getByRole('button', { name: 'com_ui_memory' });
  expect(memory).toBeDisabled();
  expect(memory).toHaveAttribute('aria-pressed', 'false');
  fireEvent.click(memory);
  expect(mockToggle).not.toHaveBeenCalled();
});
