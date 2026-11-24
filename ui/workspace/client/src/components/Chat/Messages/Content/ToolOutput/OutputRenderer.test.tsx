import { fireEvent, render, screen } from '@testing-library/react';
import copy from 'copy-to-clipboard';
import useLazyHighlight from '../Parts/useLazyHighlight';
import OutputRenderer from './OutputRenderer';

jest.mock('@librechat/client', () => ({
  Button: ({ children, onClick }: { children: React.ReactNode; onClick: () => void }) => (
    <button onClick={onClick}>{children}</button>
  ),
}));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/components/Messages/Content/CopyButton', () => ({
  __esModule: true,
  default: ({ onClick }: { onClick: () => void }) => (
    <button onClick={onClick}>{'com_ui_copy'}</button>
  ),
}));
jest.mock('copy-to-clipboard', () => jest.fn(() => true));
jest.mock('../Parts/useLazyHighlight', () => {
  const { createElement } = jest.requireActual<typeof import('react')>('react');
  return {
    __esModule: true,
    default: jest.fn((code: string | undefined) =>
      code ? [createElement('span', { key: 'token', className: 'hljs-attr' }, code)] : null,
    ),
  };
});

const highlight = useLazyHighlight as jest.Mock;

describe('tool result JSON highlighting', () => {
  it('tokenizes structured JSON and renders highlighted elements, including nested values', () => {
    const value = { ok: true, count: 3, data: { message: '完成', next: null } };
    const { container } = render(<OutputRenderer text={JSON.stringify(value)} />);

    expect(highlight).toHaveBeenCalledWith(JSON.stringify(value, null, 2), 'json');
    expect(container.querySelector('code.language-json .hljs-attr')).toHaveTextContent(
      '"ok": true',
    );
    expect(container.querySelector('code')).toHaveTextContent('"message": "完成"');
  });

  it('also tokenizes JSON embedded in MCP text content blocks', () => {
    const payload = { ok: true, data: { stdout: 'hello\nworld', duration_ms: 37309 } };
    const content = JSON.stringify([{ type: 'text', text: JSON.stringify(payload) }]);
    const { container } = render(<OutputRenderer text={content} />);

    expect(highlight).toHaveBeenCalledWith(JSON.stringify(payload, null, 2), 'json');
    expect(container.querySelector('code.language-json')).toHaveTextContent('37309');
  });

  it('leaves ordinary output and malformed JSON as plain text', () => {
    const { container, rerender } = render(<OutputRenderer text={'Shell output:\nDone'} />);
    expect(container.querySelector('code.language-json')).toBeNull();
    expect(screen.getByText(/Shell output:/)).toBeInTheDocument();

    rerender(<OutputRenderer text={'{"broken": true,}'} />);
    expect(container.querySelector('code.language-json')).toBeNull();
    expect(container.querySelector('pre')).toHaveTextContent('{"broken": true,}');
    expect(highlight).toHaveBeenLastCalledWith(undefined, 'json');
  });

  it('highlights only visible lines until expanded and copies the full result', () => {
    const value = Object.fromEntries(Array.from({ length: 30 }, (_, i) => [`key${i}`, i]));
    const pretty = JSON.stringify(value, null, 2);
    const { container } = render(<OutputRenderer text={JSON.stringify(value)} />);

    expect(highlight).toHaveBeenLastCalledWith(pretty.split('\n').slice(0, 15).join('\n'), 'json');
    fireEvent.click(screen.getByRole('button', { name: 'com_ui_show_more' }));
    expect(highlight).toHaveBeenLastCalledWith(pretty, 'json');
    fireEvent.click(screen.getByRole('button', { name: 'com_ui_copy' }));
    expect(copy).toHaveBeenCalledWith(pretty, { format: 'text/plain' });
    expect(container.querySelector('code.language-json')).toHaveTextContent('"key29": 29');
  });

  it('renders JSON strings as text rather than HTML', () => {
    const { container } = render(
      <OutputRenderer text={JSON.stringify({ html: '<img src=x onerror=alert(1)>' })} />,
    );
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('code')).toHaveTextContent('<img src=x onerror=alert(1)>');
  });

  it('avoids expensive tokenization for very large expanded results', () => {
    const value = { body: 'a'.repeat(100_001) };
    const { container } = render(<OutputRenderer text={JSON.stringify(value)} />);
    expect(highlight).toHaveBeenCalledWith(undefined, 'json');
    expect(container.querySelector('code.language-json')).toHaveTextContent('"body"');
  });
});
