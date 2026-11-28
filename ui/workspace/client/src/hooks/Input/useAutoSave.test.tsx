import { useRef, useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { useForm } from 'react-hook-form';
import { RecoilRoot } from 'recoil';
import type { ExtendedFile, ChatFormValues } from '~/common';
import { ChatFormProvider, useChatFormContext } from '~/Providers/ChatFormContext';
import { getDraft } from '~/utils/drafts';
import { useAutoSave } from './useAutoSave';

jest.mock('~/Providers', () => jest.requireActual('~/Providers/ChatFormContext'));
jest.mock('~/utils', () => jest.requireActual('~/utils/drafts'));
jest.mock('~/hooks/Files/useFileHandling', () => ({ hasInFlightUpload: () => false }));
jest.mock('~/data-provider', () => ({ useGetFiles: () => ({ data: undefined }) }));
jest.mock('~/store', () => {
  const { atom } = jest.requireActual('recoil');
  const submission = atom({ key: 'draft-test-submission', default: null });
  return {
    __esModule: true,
    default: {
      saveDrafts: atom({ key: 'draft-test-save', default: true }),
      submissionByIndex: () => submission,
    },
  };
});

function Composer({
  conversationId,
  running = false,
}: {
  conversationId: string;
  running?: boolean;
}) {
  const { register, setValue, reset } = useChatFormContext();
  const textAreaRef = useRef<HTMLTextAreaElement | null>(null);
  const [files, setFiles] = useState(new Map<string, ExtendedFile>());
  const consume = useAutoSave({
    conversationId,
    isSubmitting: running,
    textAreaRef,
    files,
    setFiles,
  });
  const { ref, ...field } = register('text');
  return (
    <>
      <textarea
        aria-label="message"
        {...field}
        ref={(node) => {
          ref(node);
          textAreaRef.current = node;
        }}
      />
      <button onClick={() => setValue('text', 'programmatic draft')}>Insert</button>
      <button
        onClick={() => {
          consume();
          reset();
        }}
      >
        Send
      </button>
    </>
  );
}

function Harness(props: { conversationId: string; running?: boolean }) {
  const methods = useForm<ChatFormValues>({ defaultValues: { text: '' } });
  return (
    <RecoilRoot>
      <ChatFormProvider {...methods}>
        <Composer {...props} />
      </ChatFormProvider>
    </RecoilRoot>
  );
}

const message = () => screen.getByRole('textbox', { name: 'message' });

beforeEach(() => localStorage.clear());

it('preserves independent drafts on immediate conversation switches, including a running chat', () => {
  const view = render(<Harness conversationId="chat-a" running />);
  fireEvent.change(message(), { target: { value: 'A unsent 中文' } });
  view.rerender(<Harness conversationId="chat-b" running />);
  expect(message()).toHaveValue('');
  fireEvent.change(message(), { target: { value: 'B unsent' } });
  view.rerender(<Harness conversationId="chat-a" />);
  expect(message()).toHaveValue('A unsent 中文');
  view.rerender(<Harness conversationId="chat-b" />);
  expect(message()).toHaveValue('B unsent');
  expect(getDraft('chat-a')).toBe('A unsent 中文');
});

it('restores after unmount and does not resurrect cleared or consumed text', () => {
  const view = render(<Harness conversationId="chat-a" />);
  fireEvent.click(screen.getByText('Insert'));
  expect(getDraft('chat-a')).toBe('programmatic draft');
  view.unmount();
  const reopened = render(<Harness conversationId="chat-a" />);
  expect(message()).toHaveValue('programmatic draft');
  fireEvent.change(message(), { target: { value: '' } });
  reopened.unmount();
  const again = render(<Harness conversationId="chat-a" />);
  expect(message()).toHaveValue('');
  fireEvent.change(message(), { target: { value: 'sent' } });
  fireEvent.click(screen.getByText('Send'));
  again.rerender(<Harness conversationId="chat-b" />);
  again.rerender(<Harness conversationId="chat-a" />);
  expect(message()).toHaveValue('');
});

it('restores the new-chat draft separately from saved conversations', () => {
  const view = render(<Harness conversationId="new" />);
  fireEvent.change(message(), { target: { value: 'new draft' } });
  view.rerender(<Harness conversationId="chat-a" />);
  expect(message()).toHaveValue('');
  fireEvent.change(message(), { target: { value: 'saved draft' } });
  view.rerender(<Harness conversationId="new" />);
  expect(message()).toHaveValue('new draft');
});

it('keeps a new-chat pending draft out of an unrelated conversation', () => {
  const view = render(<Harness conversationId="new" running />);
  fireEvent.change(message(), { target: { value: 'pending follow-up' } });
  view.rerender(<Harness conversationId="chat-a" />);
  expect(message()).toHaveValue('');
  view.rerender(<Harness conversationId="new" running />);
  expect(message()).toHaveValue('pending follow-up');
});
