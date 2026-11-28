import { render, screen } from '@testing-library/react';
import type { Context } from 'react';
import type { TConversation, TMessage } from 'librechat-data-provider';
import HoverButtons from './HoverButtons';

type LoadingState = { loading: boolean; submitting: boolean };
jest.mock('~/Providers', () => {
  const { createContext, useContext } = jest.requireActual<typeof import('react')>('react');
  const state = createContext<LoadingState>({ loading: false, submitting: false });
  return {
    state,
    useMessagesIsSubmitting: () => useContext(state).submitting,
    useMessagesLoadingTail: () => useContext(state).loading,
    useOptionalMessagesOperations: () => ({ getMessages: () => undefined }),
  };
});
const State = jest.requireMock('~/Providers').state as Context<LoadingState>;
jest.mock('~/hooks', () => ({
  useLocalize: () => (key: string) => key,
  useGenerationsByLatest: () => ({
    hideEditButton: true,
    regenerateEnabled: true,
    isActiveStreamingMessage: false,
  }),
}));
jest.mock('jotai', () => ({ useAtomValue: () => null }));
jest.mock('recoil', () => ({ useRecoilState: () => [false] }));
jest.mock('~/store', () => ({ __esModule: true, default: {} }));
jest.mock('~/store/steer', () => ({ revealedQueuedTurnFamily: () => null }));
jest.mock('~/utils', () => ({
  cn: (...classes: string[]) => classes.filter(Boolean).join(' '),
  isTemporaryConversation: () => false,
}));
jest.mock('@librechat/client', () => ({
  Button: ({ children, ...props }: React.ComponentProps<'button'>) => (
    <button {...props}>{children}</button>
  ),
  TooltipAnchor: ({ render }: { render: React.ReactNode }) => render,
  MorphIcon: () => null,
  RegenerateIcon: () => null,
  Spinner: () => null,
}));
jest.mock('./Content/editableParts', () => ({ hasEditablePart: () => false }));
jest.mock('~/components/Conversations', () => ({ Fork: () => null }));
jest.mock('./MessageAudio', () => () => null);
jest.mock('./MessageBookmarkButton', () => () => null);
jest.mock('./DeleteMessageTurnButton', () => () => null);
jest.mock('lucide', () => ({ Copy: () => null, Check: () => null }));
jest.mock('librechat-data-provider', () => ({
  findMessageById: () => undefined,
  isUserInitiatedCompaction: () => false,
}));

const conversation = { conversationId: 'conversation' } as TConversation;
const props = {
  index: 0,
  isEditing: false,
  enterEdit: jest.fn(),
  copyToClipboard: jest.fn(),
  getCanCopy: () => true,
  conversation,
  message: { messageId: 'latest', isCreatedByUser: false } as TMessage,
  regenerate: jest.fn(),
  handleContinue: jest.fn(),
  latestMessageId: 'latest',
  isLast: true,
};

function toolbar(loading: boolean, submitting: boolean, overrides = {}) {
  return (
    <State.Provider value={{ loading, submitting }}>
      <HoverButtons {...props} {...overrides} />
    </State.Provider>
  );
}

test('replaces completion actions with a loading status during history reconciliation', () => {
  const { rerender } = render(toolbar(true, false));
  expect(screen.getByRole('status')).toHaveTextContent('com_ui_loading');
  expect(screen.queryByTestId('copy-response-button')).not.toBeInTheDocument();
  expect(screen.queryByTestId('regenerate-generation-button')).not.toBeInTheDocument();

  rerender(toolbar(false, true));
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
  expect(screen.queryByTestId('copy-response-button')).not.toBeInTheDocument();

  rerender(toolbar(false, false));
  expect(screen.getByTestId('copy-response-button')).toBeInTheDocument();
  expect(screen.getByTestId('regenerate-generation-button')).toBeInTheDocument();
});

test('retains completed older response actions while the tail is loading', () => {
  render(
    toolbar(true, false, {
      message: { ...props.message, messageId: 'older' },
      isLast: false,
    }),
  );
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
  expect(screen.getByTestId('copy-response-button')).toBeInTheDocument();
});

test('uses the visible leaf when the selected tail id has not caught up to history', () => {
  render(toolbar(true, false, { latestMessageId: 'stale' }));
  expect(screen.getByRole('status')).toHaveTextContent('com_ui_loading');
});
