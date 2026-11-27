import { fireEvent, render, screen } from '@testing-library/react';
import { RecoilRoot } from 'recoil';
import { KeyboardShortcutsSettings } from './KeyboardShortcutsDialog';
import { useShortcutBindings } from '~/hooks/useKeyboardShortcuts';

jest.mock('~/hooks', () => ({
  useLocalize: () => (key: string) => key,
}));
jest.mock('~/utils', () => ({
  cn: (...classes: unknown[]) => classes.filter(Boolean).join(' '),
}));
jest.mock('~/store', () => {
  const { atom } = jest.requireActual('recoil');
  return {
    __esModule: true,
    default: {
      shortcutsEnabled: atom({ key: 'testShortcutsEnabled', default: true }),
    },
  };
});
jest.mock('~/hooks/useKeyboardShortcuts', () => ({
  isMac: false,
  useShortcutBindings: jest.fn(),
}));

const setBinding = jest.fn();
const resetBinding = jest.fn();
const resetAll = jest.fn();

beforeEach(() => {
  jest.mocked(useShortcutBindings).mockReturnValue({
    bindings: [
      {
        id: 'submitMessage',
        binding: { ctrl: true, alt: false, meta: false, shift: false, key: 'Enter' },
        isCustom: true,
        labelKey: 'com_shortcut_submit_message',
        groupKey: 'com_shortcut_group_general',
      },
    ],
    bindingMap: new Map(),
    setBinding,
    resetBinding,
    resetAll,
  });
});

it('edits and resets the shared shortcut controls directly in settings', () => {
  render(
    <RecoilRoot>
      <KeyboardShortcutsSettings />
    </RecoilRoot>,
  );
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  fireEvent.click(screen.getByTestId('edit-shortcut-submitMessage'));
  fireEvent.keyDown(screen.getByTestId('shortcut-recorder-submitMessage'), {
    key: 'Enter',
    ctrlKey: true,
    altKey: true,
  });
  expect(setBinding).toHaveBeenCalledWith('submitMessage', {
    ctrl: true,
    alt: true,
    meta: false,
    shift: false,
    key: 'Enter',
  });
  fireEvent.click(screen.getByText('com_shortcut_reset_all'));
  expect(resetAll).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('switch', { name: 'com_shortcut_keyboard_shortcuts' }));
  expect(screen.getByTestId('edit-shortcut-submitMessage')).toBeDisabled();
});
