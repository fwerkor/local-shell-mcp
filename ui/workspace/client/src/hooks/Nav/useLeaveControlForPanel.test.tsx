import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import useLeaveControlForPanel from './useLeaveControlForPanel';

function PanelButton({ panelId }: { panelId: string }) {
  const leaveControlForPanel = useLeaveControlForPanel();
  const location = useLocation();
  return (
    <>
      <span data-testid="path">{location.pathname}</span>
      <button onClick={() => leaveControlForPanel(panelId)}>Select panel</button>
    </>
  );
}

function clickPanel(from: string, panelId: string) {
  render(
    <MemoryRouter initialEntries={[from]}>
      <PanelButton panelId={panelId} />
    </MemoryRouter>,
  );
  fireEvent.click(screen.getByRole('button', { name: 'Select panel' }));
  return screen.getByTestId('path').textContent;
}

describe('leaving the controller for a sidebar panel', () => {
  it.each(['agents', 'conversations', 'mcp-builder'])(
    'opens the chat workspace when selecting %s from controller settings',
    (panelId) => {
      expect(clickPanel('/control/overview', panelId)).toBe('/c/new');
    },
  );

  it('supports the controller root URL', () => {
    expect(clickPanel('/control', 'agents')).toBe('/c/new');
  });

  it('does not navigate when the selected link is still the controller', () => {
    expect(clickPanel('/control/overview', 'lsm-control')).toBe('/control/overview');
  });

  it('does not discard an open conversation on an ordinary panel selection', () => {
    expect(clickPanel('/c/existing-conversation', 'agents')).toBe('/c/existing-conversation');
  });

  it('does not intercept unrelated paths', () => {
    expect(clickPanel('/control-room', 'agents')).toBe('/control-room');
  });
});
