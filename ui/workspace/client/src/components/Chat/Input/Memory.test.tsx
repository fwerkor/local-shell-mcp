import { fireEvent, render, screen } from '@testing-library/react';
import Memory from './Memory';

let mockEnabled = false;
let mockOptedOut = false;
let mockCanEdit = true;
let mockAvailable = true;
const mockToggle = jest.fn();

jest.mock('~/hooks', () => ({
  useLocalize: () => (key: string) => key,
  useAuthContext: () => ({ user: { personalization: { memories: !mockOptedOut } } }),
}));
jest.mock('~/Providers', () => ({
  useBadgeRowContext: () => ({
    features: {
      current: { memory: mockEnabled },
      canEdit: mockCanEdit,
      toggle: mockToggle,
    },
  }),
}));
jest.mock('~/data-provider', () => ({
  useGetStartupConfig: () => ({ data: { interface: { memories: mockAvailable } } }),
}));
jest.mock('@librechat/client', () => ({
  CheckboxButton: ({
    checked,
    disabled,
    setValue,
    label,
  }: {
    checked: boolean;
    disabled: boolean;
    setValue: (change: { value: boolean }) => void;
    label: string;
  }) => (
    <button
      role="checkbox"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => setValue({ value: !checked })}
    >
      {label}
    </button>
  ),
}));

beforeEach(() => {
  mockEnabled = false;
  mockOptedOut = false;
  mockCanEdit = true;
  mockAvailable = true;
  mockToggle.mockClear();
});

test('keeps the conversation switch visible when off and updates the server-backed setting', () => {
  const { rerender } = render(<Memory />);
  const toggle = screen.getByRole('checkbox', { name: 'com_ui_memory' });
  expect(toggle).not.toBeChecked();
  fireEvent.click(toggle);
  expect(mockToggle).toHaveBeenCalledWith('memory', true);
  mockEnabled = true;
  rerender(<Memory key="updated" />);
  const updated = screen.getByRole('checkbox');
  expect(updated).toBeChecked();
  fireEvent.click(updated);
  expect(mockToggle).toHaveBeenLastCalledWith('memory', false);
});

test('global opt-out disables the conversation switch without changing its stored preference', () => {
  mockEnabled = true;
  mockOptedOut = true;
  const { rerender } = render(<Memory />);
  const toggle = screen.getByRole('checkbox', { name: 'com_ui_memory' });
  expect(toggle).toBeDisabled();
  expect(toggle).not.toBeChecked();
  fireEvent.click(toggle);
  expect(mockToggle).not.toHaveBeenCalled();
  mockOptedOut = false;
  rerender(<Memory key="updated" />);
  expect(screen.getByRole('checkbox')).toBeEnabled();
  expect(screen.getByRole('checkbox')).toBeChecked();
});

test('disables controls while settings load and hides unavailable memory', () => {
  mockCanEdit = false;
  const { rerender } = render(<Memory />);
  expect(screen.getByRole('checkbox')).toBeDisabled();
  mockAvailable = false;
  rerender(<Memory key="updated" />);
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
});
