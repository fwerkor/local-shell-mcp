import { fireEvent, render, screen } from '@testing-library/react';
import type { MenuItemProps } from '~/common';
import ToolsDropdown from './ToolsDropdown';

let mockEnabled = false;
let mockOptedOut = false;
let mockCanEdit = true;
let mockAvailable = true;
const mockToggle = jest.fn();

jest.mock('~/hooks', () => ({
  useLocalize: () => (key: string) => key,
  useHasAccess: () => true,
  useAgentCapabilities: () => ({ webSearchEnabled: true }),
  useAuthContext: () => ({ user: { personalization: { memories: !mockOptedOut } } }),
}));
jest.mock('~/Providers', () => ({
  useBadgeRowContext: () => ({
    webSearch: { toggleState: true },
    features: {
      current: { memory: mockEnabled },
      registered: [],
      canEdit: mockCanEdit,
      toggle: mockToggle,
    },
  }),
}));
jest.mock('~/data-provider', () => ({
  useGetStartupConfig: () => ({ data: { interface: { memories: mockAvailable } } }),
}));
jest.mock('@ariakit/react', () => ({ MenuButton: () => null }));
jest.mock('./ArtifactsSubMenu', () => () => null);
jest.mock('~/utils', () => ({ cn: (...classes: string[]) => classes.filter(Boolean).join(' ') }));
jest.mock('@librechat/client', () => ({
  DropdownPopup: ({ items }: { items: MenuItemProps[] }) => (
    <div role="menu">
      {items.map((item, index) => {
        const props = {
          role: item.ariaChecked === undefined ? 'menuitem' : 'menuitemcheckbox',
          'aria-checked': item.ariaChecked,
          'aria-disabled': item.disabled,
          onClick: () => {
            if (!item.disabled) {
              item.onClick?.({} as Parameters<NonNullable<MenuItemProps['onClick']>>[0]);
            }
          },
        };
        return (
          <div key={index}>
            {typeof item.render === 'function'
              ? item.render(props)
              : (item.render ?? <div {...props}>{item.label}</div>)}
          </div>
        );
      })}
    </div>
  ),
  TooltipAnchor: () => null,
  PinIcon: () => null,
  MCPIcon: () => null,
}));
beforeEach(() => {
  mockEnabled = false;
  mockOptedOut = false;
  mockCanEdit = true;
  mockAvailable = true;
  mockToggle.mockClear();
});

test('keeps the conversation switch visible when off and updates the server-backed setting', () => {
  const { rerender } = render(<ToolsDropdown />);
  const toggle = screen.getByRole('menuitemcheckbox', { name: 'com_ui_memory' });
  expect(screen.getByRole('menuitemcheckbox', { name: /com_ui_web_search/ })).toBeChecked();
  expect(toggle).not.toBeChecked();
  fireEvent.click(toggle);
  expect(mockToggle).toHaveBeenCalledWith('memory', true);
  mockEnabled = true;
  rerender(<ToolsDropdown key="updated" />);
  const updated = screen.getByRole('menuitemcheckbox', { name: 'com_ui_memory' });
  expect(updated).toBeChecked();
  fireEvent.click(updated);
  expect(mockToggle).toHaveBeenLastCalledWith('memory', false);
});

test('global opt-out disables the conversation switch without changing its stored preference', () => {
  mockEnabled = true;
  mockOptedOut = true;
  const { rerender } = render(<ToolsDropdown />);
  const toggle = screen.getByRole('menuitemcheckbox', { name: 'com_ui_memory' });
  expect(toggle).toHaveAttribute('aria-disabled', 'true');
  expect(toggle).not.toBeChecked();
  fireEvent.click(toggle);
  expect(mockToggle).not.toHaveBeenCalled();
  mockOptedOut = false;
  rerender(<ToolsDropdown key="updated" />);
  expect(screen.getByRole('menuitemcheckbox', { name: 'com_ui_memory' })).toHaveAttribute(
    'aria-disabled',
    'false',
  );
  expect(screen.getByRole('menuitemcheckbox', { name: 'com_ui_memory' })).toBeChecked();
});

test('disables controls while settings load and hides unavailable memory', () => {
  mockCanEdit = false;
  const { rerender } = render(<ToolsDropdown />);
  expect(screen.getByRole('menuitemcheckbox', { name: 'com_ui_memory' })).toHaveAttribute(
    'aria-disabled',
    'true',
  );
  mockAvailable = false;
  rerender(<ToolsDropdown key="updated" />);
  expect(screen.queryByRole('menuitemcheckbox', { name: 'com_ui_memory' })).not.toBeInTheDocument();
});

test('shows memory for agent chats without ephemeral tools, but not in secondary composers', () => {
  const { rerender } = render(<ToolsDropdown showEphemeralTools={false} />);
  expect(screen.getByRole('menuitemcheckbox', { name: 'com_ui_memory' })).toBeInTheDocument();
  rerender(<ToolsDropdown showMemory={false} />);
  expect(screen.queryByRole('menuitemcheckbox', { name: 'com_ui_memory' })).not.toBeInTheDocument();
});
