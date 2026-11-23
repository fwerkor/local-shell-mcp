import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import type { NavLink } from '~/common';
import ShortcutTargets from './ShortcutTargets';

const mockSetActive = jest.fn();
jest.mock('~/Providers', () => ({
  useActivePanel: () => ({ active: 'lsm-control', setActive: mockSetActive }),
  resolveActivePanel: (active: string) => active,
}));

const links = [
  { id: 'agents', title: 'com_sidepanel_agent_builder' },
  { id: 'lsm-control', title: 'com_nav_control_panel' },
] as NavLink[];

function CurrentPath() {
  return <span data-testid="path">{useLocation().pathname}</span>;
}

describe('mobile sidebar keyboard navigation', () => {
  it('leaves controller settings for the selected panel', () => {
    render(
      <MemoryRouter initialEntries={['/control/settings']}>
        <ShortcutTargets links={links} />
        <CurrentPath />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByTestId('nav-panel-agents'));
    expect(mockSetActive).toHaveBeenCalledWith('agents');
    expect(screen.getByTestId('path')).toHaveTextContent('/c/new');
  });
});
