import { fireEvent, render, screen } from '@testing-library/react';
import { RowMenu } from './SteerMenu';

jest.mock('~/hooks/useKeyboardShortcuts', () => ({
  useShortcutAriaKey: () => undefined,
  useShortcutDisplay: () => undefined,
}));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/utils', () => ({ cn: (...classes: string[]) => classes.join(' ') }));

it('offers only actions for the specific message', async () => {
  const edit = jest.fn();
  render(
    <RowMenu
      label="More options"
      entries={[{ key: 'edit', label: 'Edit message', icon: null, onClick: edit }]}
    />,
  );
  fireEvent.click(screen.getByRole('button', { name: 'More options' }));
  const item = await screen.findByRole('menuitem', { name: 'Edit message' });
  expect(screen.getAllByRole('menuitem')).toHaveLength(1);
  fireEvent.click(item);
  expect(edit).toHaveBeenCalledTimes(1);
});

it('does not render a menu button without message actions', () => {
  render(<RowMenu label="More options" entries={[]} />);
  expect(screen.queryByRole('button', { name: 'More options' })).not.toBeInTheDocument();
});
