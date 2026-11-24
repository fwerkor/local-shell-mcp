import { fireEvent, render, screen } from '@testing-library/react';
import Conversation from './Convo';

jest.mock('react-dnd', () => ({ useDrag: () => [{}, () => undefined] }));
jest.mock('recoil', () => ({ useRecoilValue: () => [] }));
jest.mock('react-router-dom', () => ({ useParams: () => ({ conversationId: 'another-chat' }) }));
jest.mock('librechat-data-provider', () => ({ Constants: { NEW_CONVO: 'new' } }));
jest.mock('@librechat/client', () => ({
  Spinner: () => null,
  useToastContext: () => ({ showToast: jest.fn() }),
  useMediaQuery: () => false,
}));
jest.mock('~/data-provider', () => ({
  useGetStartupConfig: () => ({ data: { sharedLinksEnabled: false } }),
  usePinConversationMutation: () => ({ mutate: jest.fn() }),
  useUpdateConversationMutation: () => ({ mutateAsync: jest.fn() }),
}));
jest.mock('~/hooks', () => ({
  useNavigateToConvo: () => ({ navigateToConvo: jest.fn() }),
  useLocalize: () => (key: string) => key,
  useShiftKey: () => false,
}));
jest.mock('~/store', () => ({
  __esModule: true,
  default: { allConversationsSelector: {} },
}));
jest.mock('~/utils', () => ({
  cn: (...classes: string[]) => classes.filter(Boolean).join(' '),
  logger: { error: jest.fn() },
  setDocumentTitle: jest.fn(),
}));
jest.mock('./ConvoActions', () => ({
  __esModule: true,
  default: ({
    contextMenuPoint,
    isPopoverActive,
    hasInteracted,
    onOpenChange,
  }: {
    contextMenuPoint: { x: number; y: number } | null;
    isPopoverActive: boolean;
    hasInteracted: boolean;
    onOpenChange: (open: boolean) => void;
  }) => (
    <button
      data-testid="convo-options"
      data-point={contextMenuPoint ? `${contextMenuPoint.x}:${contextMenuPoint.y}` : 'none'}
      data-open={String(isPopoverActive)}
      data-interacted={String(hasInteracted)}
      onClick={() => onOpenChange(false)}
    />
  ),
}));
jest.mock('./ConvoLink', () => ({
  __esModule: true,
  default: ({ onRename, children }: { onRename: () => void; children: React.ReactNode }) => (
    <button data-testid="start-rename" onClick={onRename}>
      {children}
    </button>
  ),
}));
jest.mock('./ConversationEndpointIcon', () => ({ __esModule: true, default: () => null }));
jest.mock('./RenameForm', () => ({
  __esModule: true,
  default: () => <input aria-label="Rename" />,
}));
jest.mock('./UnpinButton', () => ({ __esModule: true, default: () => null }));

function renderConversation() {
  return render(
    <Conversation
      conversation={
        { conversationId: 'chat-1', title: 'Example' } as React.ComponentProps<
          typeof Conversation
        >['conversation']
      }
      retainView={jest.fn()}
      toggleNav={jest.fn()}
    />,
  );
}

function rightClick(x: number, y: number): MouseEvent {
  const event = new MouseEvent('contextmenu', {
    bubbles: true,
    cancelable: true,
    clientX: x,
    clientY: y,
  });
  fireEvent(screen.getByTestId('convo-item'), event);
  return event;
}

describe('conversation row context menu', () => {
  it('intercepts the browser menu and opens the existing actions at the mouse position', () => {
    renderConversation();
    expect(screen.getByTestId('convo-options')).toHaveAttribute('data-interacted', 'false');

    expect(rightClick(120, 340).defaultPrevented).toBe(true);
    expect(screen.getByTestId('convo-options')).toHaveAttribute('data-interacted', 'true');
    expect(screen.getByTestId('convo-options')).toHaveAttribute('data-open', 'true');
    expect(screen.getByTestId('convo-options')).toHaveAttribute('data-point', '120:340');

    rightClick(450, 210);
    expect(screen.getByTestId('convo-options')).toHaveAttribute('data-point', '450:210');
    fireEvent.click(screen.getByTestId('convo-options'));
    expect(screen.getByTestId('convo-options')).toHaveAttribute('data-open', 'false');
    expect(screen.getByTestId('convo-options')).toHaveAttribute('data-point', 'none');
  });

  it('leaves the native context menu available during inline rename', () => {
    renderConversation();
    fireEvent.click(screen.getByTestId('start-rename'));
    expect(screen.getByRole('textbox', { name: 'Rename' })).toBeInTheDocument();
    expect(rightClick(120, 340).defaultPrevented).toBe(false);
  });
});
