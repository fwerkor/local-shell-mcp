/** Only controller attachment URLs may receive the workspace bearer token. */
export function isControllerAttachmentImage(url: string, endpoint: string, page: string): boolean {
  try {
    const origin = new URL(page).origin;
    const image = new URL(url, page);
    const prefix = new URL(endpoint, page);
    return (
      image.origin === origin &&
      prefix.origin === origin &&
      image.pathname.startsWith(prefix.pathname) &&
      /^[^/]+(?:\/[^/]+)?$/.test(image.pathname.slice(prefix.pathname.length))
    );
  } catch {
    return false;
  }
}

const rasterTypes = new Set([
  'image/png',
  'image/jpeg',
  'image/gif',
  'image/webp',
  'image/bmp',
  'image/avif',
  'image/x-icon',
  'image/vnd.microsoft.icon',
  'image/tiff',
]);

/** Downloads intentionally use octet-stream; only raster images become blob URLs. */
export async function readAttachmentImage(response: Response): Promise<Blob> {
  if (!response.ok) {
    throw new Error(`Image download failed: ${response.status}`);
  }
  const blob = await response.blob();
  const header = response.headers.get('X-File-Metadata');
  const type = header ? JSON.parse(decodeURIComponent(header)).type : blob.type;
  if (!rasterTypes.has(type)) {
    throw new Error('Unsupported attachment image type');
  }
  return blob.slice(0, blob.size, type);
}
