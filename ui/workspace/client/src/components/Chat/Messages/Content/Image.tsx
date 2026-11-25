import React, { useState, useRef, useMemo, useEffect } from 'react';
import { Skeleton } from '@librechat/client';
import { apiBaseUrl, request } from 'librechat-data-provider';
import { cn, toAbsoluteFilePath } from '~/utils';
import { useLocalize } from '~/hooks';
import DialogImage from './DialogImage';
import { isControllerAttachmentImage, readAttachmentImage } from './attachmentImage';

/** Max display height for chat images (Tailwind JIT class) */
export const IMAGE_MAX_H = 'max-h-[45vh]' as const;
/** Matches the `max-w-lg` Tailwind class on the wrapper button (32rem = 512px at 16px base) */
const IMAGE_MAX_W_PX = 512;

/** Caches image dimensions by src so remounts can reserve space */
const dimensionCache = new Map<string, { width: number; height: number }>();
/** Tracks URLs that have been fully painted — skip skeleton on remount */
const paintedUrls = new Set<string>();

/** Test-only: resets module-level caches */
export function _resetImageCaches(): void {
  dimensionCache.clear();
  paintedUrls.clear();
}

function computeHeightStyle(w: number, h: number): React.CSSProperties {
  return { height: `min(45vh, ${(h / w) * 100}vw, ${(h / w) * IMAGE_MAX_W_PX}px)` };
}

const Image = ({
  imagePath,
  altText,
  className,
  alignRight = false,
  args,
  width,
  height,
}: {
  imagePath: string;
  altText: string;
  className?: string;
  alignRight?: boolean;
  args?: {
    prompt?: string;
    quality?: 'low' | 'medium' | 'high';
    size?: string;
    style?: string;
    [key: string]: unknown;
  };
  width?: number;
  height?: number;
}) => {
  const localize = useLocalize();
  const [isOpen, setIsOpen] = useState(false);
  const [attachment, setAttachment] = useState<{ source: string; url: string; size: number }>();
  const [failedSource, setFailedSource] = useState<string>();
  const [loadedSource, setLoadedSource] = useState<string>();
  const triggerRef = useRef<HTMLButtonElement>(null);

  /** Root-relative server paths (`/images/...` static, `/api/...` downloads and
   *  share routes) are resolved against the API base so they load under a
   *  subpath deployment. */
  const absoluteImageUrl = useMemo(() => toAbsoluteFilePath(imagePath, apiBaseUrl()), [imagePath]);

  const protectedImage = isControllerAttachmentImage(
    absoluteImageUrl,
    toAbsoluteFilePath('/api/files/download/', apiBaseUrl()),
    window.location.href,
  );
  const displayUrl = protectedImage
    ? attachment?.source === absoluteImageUrl
      ? attachment.url
      : undefined
    : absoluteImageUrl;
  const failed = failedSource === absoluteImageUrl;

  useEffect(() => {
    if (!protectedImage) {
      return;
    }
    const controller = new AbortController();
    let objectUrl: string | undefined;
    setFailedSource(undefined);
    setLoadedSource(undefined);
    setAttachment(undefined);
    request
      .authenticatedFetch(absoluteImageUrl, { signal: controller.signal, redirect: 'error' })
      .then(readAttachmentImage)
      .then((blob) => {
        if (controller.signal.aborted) {
          return;
        }
        objectUrl = URL.createObjectURL(blob);
        setAttachment({ source: absoluteImageUrl, url: objectUrl, size: blob.size });
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setFailedSource(absoluteImageUrl);
        }
      });
    return () => {
      controller.abort();
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [absoluteImageUrl, protectedImage]);

  const downloadImage = async () => {
    if (protectedImage) {
      if (!displayUrl || failed) {
        return;
      }
      const link = document.createElement('a');
      link.href = displayUrl;
      link.download = altText || 'image.png';
      document.body.appendChild(link);
      link.click();
      link.remove();
      return;
    }
    try {
      const response = await fetch(absoluteImageUrl);
      if (!response.ok) {
        throw new Error(`Failed to fetch image: ${response.status}`);
      }

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);

      const link = document.createElement('a');
      link.href = url;
      link.download = altText || 'image.png';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);

      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error('Download failed:', error);
      const link = document.createElement('a');
      link.href = absoluteImageUrl;
      link.download = altText || 'image.png';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    }
  };

  useEffect(() => {
    if (width && height && absoluteImageUrl) {
      dimensionCache.set(absoluteImageUrl, { width, height });
    }
  }, [absoluteImageUrl, width, height]);

  const dims = width && height ? { width, height } : dimensionCache.get(absoluteImageUrl);
  const hasDimensions = !!(dims?.width && dims?.height);
  const heightStyle = hasDimensions ? computeHeightStyle(dims.width, dims.height) : undefined;
  const showSkeleton =
    !failed &&
    hasDimensions &&
    (!displayUrl || loadedSource !== displayUrl) &&
    (protectedImage || !paintedUrls.has(absoluteImageUrl));

  return (
    <div className={alignRight ? 'ml-auto' : undefined}>
      <button
        ref={triggerRef}
        type="button"
        aria-label={`View ${altText} in dialog`}
        aria-haspopup="dialog"
        onClick={() => setIsOpen(true)}
        disabled={!displayUrl || failed}
        className={cn(
          'relative mt-1 w-full max-w-lg cursor-pointer overflow-hidden rounded-lg border border-border-light text-text-secondary-alt shadow-md transition-shadow',
          'focus:outline-none focus-visible:ring-2 focus-visible:ring-text-primary focus-visible:ring-offset-2 focus-visible:ring-offset-surface-primary',
          className,
        )}
        style={heightStyle}
      >
        {showSkeleton && <Skeleton className="absolute inset-0" aria-hidden="true" />}
        {failed ? (
          <span role="alert" className="relative block p-3">
            {localize('com_ui_error')}: {altText}
          </span>
        ) : displayUrl ? (
          <img
            alt={altText}
            src={displayUrl}
            onLoad={() => {
              setLoadedSource(displayUrl);
              if (!protectedImage) {
                paintedUrls.add(absoluteImageUrl);
              }
            }}
            onError={() => setFailedSource(absoluteImageUrl)}
            className={cn(
              'relative block text-transparent',
              hasDimensions
                ? 'size-full object-contain'
                : cn('h-auto w-auto max-w-full', IMAGE_MAX_H),
            )}
          />
        ) : (
          <span className="relative block p-3">{localize('com_ui_loading')}</span>
        )}
      </button>
      <DialogImage
        isOpen={isOpen && !!displayUrl && !failed}
        onOpenChange={setIsOpen}
        src={displayUrl}
        byteSize={
          protectedImage && attachment?.source === absoluteImageUrl ? attachment.size : undefined
        }
        downloadImage={downloadImage}
        args={args}
        triggerRef={triggerRef}
      />
    </div>
  );
};

export default Image;
