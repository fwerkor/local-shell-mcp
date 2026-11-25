import { isControllerAttachmentImage, readAttachmentImage } from './attachmentImage';

const page = 'https://controller.example/workspace/chat';
const endpoint = '/workspace/api/files/download/';

describe('controller attachment images', () => {
  it.each(['id', 'owner/id'])('recognizes protected attachment %s under a base path', (id) => {
    expect(isControllerAttachmentImage(endpoint + id, endpoint, page)).toBe(true);
  });

  it.each([
    'https://other.example/workspace/api/files/download/id',
    '//other.example/workspace/api/files/download/id',
    '/workspace/api/files/download/',
    '/workspace/api/files/download/id/extra/segment',
    '/workspace/images/image.png',
    'blob:https://controller.example/image',
    'data:image/png;base64,abc',
  ])('does not send authorization to %s', (url) => {
    expect(isControllerAttachmentImage(url, endpoint, page)).toBe(false);
  });

  function response(status: number, type: string): Response {
    return {
      ok: status === 200,
      status,
      headers: { get: () => encodeURIComponent(JSON.stringify({ type })) },
      blob: async () => new Blob(['image bytes'], { type: 'application/octet-stream' }),
    } as unknown as Response;
  }

  it('restores the raster MIME type while keeping the original bytes', async () => {
    const blob = await readAttachmentImage(response(200, 'image/png'));
    expect(blob.type).toBe('image/png');
    expect(blob.size).toBe(11);
  });

  it('rejects authorization failures and active content', async () => {
    await expect(readAttachmentImage(response(401, 'image/png'))).rejects.toThrow('401');
    await expect(readAttachmentImage(response(200, 'text/html'))).rejects.toThrow('Unsupported');
    await expect(readAttachmentImage(response(200, 'image/svg+xml'))).rejects.toThrow(
      'Unsupported',
    );
  });
});
