import { fireEvent, render, screen } from '@testing-library/react';
import { EModelEndpoint } from 'librechat-data-provider';
import AttachFileMenu from './AttachFileMenu';

let mockSharePoint = false;
let mockContext = false;
const mockHandleFileChange = jest.fn();

jest.mock('recoil', () => ({ useRecoilState: () => [{}, jest.fn()] }));
jest.mock('~/store', () => ({ ephemeralAgentByConvoId: jest.fn() }));
jest.mock('~/data-provider', () => ({
  useGetStartupConfig: () => ({ data: { sharePointFilePickerEnabled: mockSharePoint } }),
}));
jest.mock('~/hooks', () => ({
  useLocalize: () => (key: string) => key,
  useGetAgentsConfig: () => ({}),
  useAgentCapabilities: () => ({ contextEnabled: mockContext }),
  useAgentToolPermissions: () => ({}),
  useFileHandlingNoChatContext: () => ({ handleFileChange: mockHandleFileChange }),
}));
jest.mock('~/hooks/Files/useSharePointFileHandling', () => ({
  useSharePointFileHandlingNoChatContext: () => ({}),
}));
jest.mock('~/hooks/useKeyboardShortcuts', () => ({
  useShortcutHint: () => 'Attach files',
  useShortcutAriaKey: () => 'Control+U',
}));
jest.mock('~/components/SharePoint', () => ({ SharePointPickerDialog: () => null }));
jest.mock('~/utils', () => ({ cn: (...values: string[]) => values.filter(Boolean).join(' ') }));
jest.mock('@ariakit/react', () => ({ MenuButton: () => null }));
jest.mock('@librechat/client', () => {
  const React = jest.requireActual('react');
  return {
    FileUpload: React.forwardRef(({ children, handleFileChange }: any, ref: any) => (
      <>
        <input type="file" ref={ref} onChange={handleFileChange} />
        {children}
      </>
    )),
    TooltipAnchor: ({ render }: any) => render,
    IconButton: ({ label, disabled, onClick, id, children }: any) => (
      <button aria-label={label} disabled={disabled} onClick={onClick} id={id}>
        {children}
      </button>
    ),
    DropdownPopup: ({ items }: any) => (
      <div data-testid="upload-menu">
        {items.map((item: any) => (
          <button key={item.label} onClick={item.onClick}>
            {item.label}
          </button>
        ))}
      </div>
    ),
    AttachmentIcon: () => null,
    SharePointIcon: () => null,
  };
});

beforeEach(() => {
  mockSharePoint = false;
  mockContext = false;
});

function mount(overrides: Partial<React.ComponentProps<typeof AttachFileMenu>> = {}) {
  return render(
    <AttachFileMenu
      conversationId="new"
      endpoint={EModelEndpoint.openAI}
      isUnifiedMode={false}
      files={new Map()}
      setFiles={jest.fn()}
      setFilesLoading={jest.fn()}
      conversation={null}
      {...overrides}
    />,
  );
}

test('opens the native picker directly for a single provider destination with its MIME filter', () => {
  const { container } = mount();
  const input = container.querySelector('input[type=file]') as HTMLInputElement;
  const click = jest.spyOn(input, 'click');
  expect(screen.queryByTestId('upload-menu')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'com_sidepanel_attach_files' }));
  expect(click).toHaveBeenCalledTimes(1);
  expect(input.accept).toContain('image/*');
  expect(input.accept).toContain('application/pdf');
  fireEvent.change(input, { target: { files: [new File(['pdf'], 'a.pdf')] } });
  expect(mockHandleFileChange).toHaveBeenCalledWith(expect.anything(), undefined);
});

test('preserves direct upload in unified mode', () => {
  const { container } = mount({ isUnifiedMode: true });
  const input = container.querySelector('input[type=file]') as HTMLInputElement;
  const click = jest.spyOn(input, 'click');
  fireEvent.click(screen.getByRole('button', { name: 'com_sidepanel_attach_files' }));
  expect(click).toHaveBeenCalledTimes(1);
  expect(input.accept).toBe('');
});

test('does not open the picker when disabled', () => {
  const { container } = mount({ disabled: true });
  const click = jest.spyOn(container.querySelector('input')!, 'click');
  fireEvent.click(screen.getByRole('button', { name: 'com_sidepanel_attach_files' }));
  expect(click).not.toHaveBeenCalled();
});

test('keeps the menu when a second upload destination exists', () => {
  mockContext = true;
  mount();
  expect(screen.getByTestId('upload-menu')).toBeInTheDocument();
  expect(screen.getByText('com_ui_upload_ocr_text')).toBeInTheDocument();
});

test.each([false, true])('keeps the SharePoint source menu (unified: %s)', (isUnifiedMode) => {
  mockSharePoint = true;
  mount({ isUnifiedMode });
  expect(screen.getByText('com_files_upload_sharepoint')).toBeInTheDocument();
});
