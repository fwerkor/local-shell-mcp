import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { RecoilRoot, useSetRecoilState } from 'recoil';
import { SettingsTabValues } from 'librechat-data-provider';
import GlobalSettings from './GlobalSettings';
import { settingsTabState } from './state';

jest.mock('./Dialog', () => ({
  __esModule: true,
  default: ({
    initialTab,
    onOpenChange,
  }: {
    initialTab: string;
    onOpenChange: (open: boolean) => void;
  }) => (
    <div role="dialog" aria-label={initialTab}>
      <button onClick={() => onOpenChange(false)}>Close</button>
    </div>
  ),
}));

function Harness() {
  const setTab = useSetRecoilState(settingsTabState);
  const location = useLocation();
  return (
    <>
      <span data-testid="path">{location.pathname + location.hash}</span>
      <button onClick={() => setTab(SettingsTabValues.GENERAL)}>Account settings</button>
      <button onClick={() => setTab('models')}>Model settings</button>
      <GlobalSettings />
    </>
  );
}

function mount(path: string) {
  return render(
    <RecoilRoot>
      <MemoryRouter initialEntries={[path]}>
        <Harness />
      </MemoryRouter>
    </RecoilRoot>,
  );
}

describe('unified settings', () => {
  it('opens the same dialog from account and model shortcuts without navigating', async () => {
    mount('/c/new');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Account settings'));
    expect(
      await screen.findByRole('dialog', { name: SettingsTabValues.GENERAL }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByText('Close'));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Model settings'));
    expect(await screen.findByRole('dialog', { name: 'models' })).toBeInTheDocument();
    expect(screen.getByTestId('path')).toHaveTextContent('/c/new');
  });

  it.each([
    ['/control/settings', 'controller'],
    ['/control/settings#models', 'models'],
  ])('redirects legacy URL %s to the unified dialog', async (path, tab) => {
    mount(path);
    expect(await screen.findByRole('dialog', { name: tab })).toBeInTheDocument();
    expect(screen.getByTestId('path')).toHaveTextContent('/control/overview');
    fireEvent.click(screen.getByText('Close'));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
