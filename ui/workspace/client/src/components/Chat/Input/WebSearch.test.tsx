import { render, screen } from '@testing-library/react';
import WebSearch from './WebSearch';

let mockPinned = false;
let mockEnabled = false;
let mockHasAccess = true;
const mockChange = jest.fn();

jest.mock('~/hooks', () => ({
  useLocalize: () => (key: string) => key,
  useHasAccess: () => mockHasAccess,
}));
jest.mock('~/Providers', () => ({
  useBadgeRowContext: () => ({
    webSearch: {
      isPinned: mockPinned,
      toggleState: mockEnabled,
      debouncedChange: mockChange,
    },
    searchApiKeyForm: { badgeTriggerRef: null },
    features: { canEdit: true },
  }),
}));
jest.mock('@librechat/client', () => ({
  CheckboxButton: ({ checked, label }: { checked: boolean; label: string }) => (
    <button role="checkbox" aria-checked={checked}>
      {label}
    </button>
  ),
}));

beforeEach(() => {
  mockPinned = false;
  mockEnabled = false;
  mockHasAccess = true;
});

test.each([false, true])('hides the unpinned shortcut with search enabled=%s', (enabled) => {
  mockEnabled = enabled;
  render(<WebSearch />);
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  expect(mockChange).not.toHaveBeenCalled();
});

test.each([false, true])('shows the pinned shortcut with search enabled=%s', (enabled) => {
  mockPinned = true;
  mockEnabled = enabled;
  render(<WebSearch />);
  expect(screen.getByRole('checkbox', { name: 'com_ui_search' })).toHaveAttribute(
    'aria-checked',
    String(enabled),
  );
});

test('unpinning an active shortcut hides it without disabling search', () => {
  mockPinned = true;
  mockEnabled = true;
  const { rerender } = render(<WebSearch />);
  expect(screen.getByRole('checkbox')).toBeChecked();
  mockPinned = false;
  rerender(<WebSearch key="unpinned" />);
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  expect(mockChange).not.toHaveBeenCalled();
  mockPinned = true;
  rerender(<WebSearch key="repinned" />);
  expect(screen.getByRole('checkbox')).toBeChecked();
});

test('does not display a pinned shortcut without permission', () => {
  mockPinned = true;
  mockHasAccess = false;
  render(<WebSearch />);
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
});
