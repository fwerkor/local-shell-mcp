import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { request } from 'librechat-data-provider';
import Image from './Image';

jest.mock('librechat-data-provider', () => ({
  apiBaseUrl: () => '',
  request: { authenticatedFetch: jest.fn() },
}));
jest.mock('@librechat/client', () => ({ Skeleton: () => <div data-testid="skeleton" /> }));
jest.mock('~/utils', () => ({
  cn: (...values: string[]) => values.filter(Boolean).join(' '),
  toAbsoluteFilePath: (path: string) => path,
}));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('./DialogImage', () => ({
  __esModule: true,
  default: ({
    isOpen,
    src,
    downloadImage,
  }: {
    isOpen: boolean;
    src: string;
    downloadImage: () => void;
  }) =>
    isOpen ? (
      <button data-testid="dialog-image" data-src={src} onClick={downloadImage}>
        download
      </button>
    ) : null,
}));

const fetchAttachment = jest.mocked(request.authenticatedFetch);
const createObjectURL = jest.fn(() => 'blob:http://localhost:3080/attachment');
const revokeObjectURL = jest.fn();
const path = '/api/files/download/image-id';

beforeEach(() => {
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectURL });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeObjectURL });
});

function imageResponse(): Response {
  return {
    ok: true,
    headers: { get: () => encodeURIComponent(JSON.stringify({ type: 'image/png' })) },
    blob: async () => new Blob(['bytes']),
  } as unknown as Response;
}

it('loads a private attachment with authenticated fetch, previews and downloads the blob, then revokes it', async () => {
  fetchAttachment.mockResolvedValueOnce(imageResponse());
  const click = jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  const { unmount } = render(
    <Image imagePath={path} altText="photo.png" width={100} height={100} />,
  );
  expect(screen.queryByRole('img')).toBeNull();
  const img = await screen.findByRole('img', { name: 'photo.png' });
  expect(fetchAttachment).toHaveBeenCalledWith(
    path,
    expect.objectContaining({ redirect: 'error', signal: expect.anything() }),
  );
  expect(img.getAttribute('src')).toBe('blob:http://localhost:3080/attachment');
  fireEvent.load(img);
  expect(screen.queryByTestId('skeleton')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'View photo.png in dialog' }));
  const dialog = screen.getByTestId('dialog-image');
  expect(dialog.getAttribute('data-src')).toBe(img.getAttribute('src'));
  fireEvent.click(dialog);
  expect(click).toHaveBeenCalledTimes(1);
  unmount();
  expect(revokeObjectURL).toHaveBeenCalledWith('blob:http://localhost:3080/attachment');
});

it('shows a visible error and stops loading when the private download fails', async () => {
  fetchAttachment.mockRejectedValueOnce(new Error('401'));
  render(<Image imagePath={path} altText="photo.png" width={100} height={100} />);
  await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('photo.png'));
  expect(screen.queryByTestId('skeleton')).toBeNull();
  expect(screen.queryByRole('img')).toBeNull();
});

it('does not authenticate third-party image URLs', () => {
  const url = 'https://other.example/api/files/download/image-id';
  render(<Image imagePath={url} altText="external" />);
  expect(screen.getByRole('img').getAttribute('src')).toBe(url);
  expect(fetchAttachment).not.toHaveBeenCalled();
});
