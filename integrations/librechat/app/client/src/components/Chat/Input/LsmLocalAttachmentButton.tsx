import { useState } from 'react';
import { useAuthContext } from '~/hooks';

export default function LsmLocalAttachmentButton() {
  const { token } = useAuthContext();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const upload = async (file: File | undefined) => {
    if (!file || busy) return;
    if (file.size <= 0 || file.size > 32 * 1024 * 1024) {
      setError('Attachments must be between 1 byte and 32 MiB');
      return;
    }
    const origin = document.querySelector<HTMLMetaElement>('meta[name="lsm-parent-origin"]')?.content;
    if (origin && window.parent !== window) {
      window.parent.postMessage({ type: 'lsm:upload', file }, origin);
      return;
    }
    setBusy(true);
    setError('');
    try {
      const response = await fetch('/api/lsm/controller/librechat/upload?name=' + encodeURIComponent(file.name), {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/octet-stream',
          ...(token ? { Authorization: 'Bearer ' + token } : {}),
        },
        body: file,
      });
      const result = await response.json() as {
        ok?: boolean;
        message?: string;
        data?: { path?: string };
      };
      if (!response.ok || !result.ok || !result.data?.path) {
        throw new Error(result.message || 'LSM file upload failed');
      }
      window.dispatchEvent(new CustomEvent('lsm:local-attachment', { detail: { path: result.data.path } }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="relative flex items-center">
      <label
        title="Attach a file to the LSM local machine"
        className={'inline-flex items-center rounded-lg border border-border-medium px-2 py-1.5 text-xs ' +
          (busy ? 'cursor-wait opacity-60' : 'cursor-pointer hover:bg-surface-hover')}
      >
        <span>{busy ? 'Uploading…' : 'Attach to LSM'}</span>
        <input type="file" className="sr-only" disabled={busy} aria-label="Upload to LSM local machine"
          onChange={(event) => {
            void upload(event.target.files?.item(0) ?? undefined);
            event.target.value = '';
          }}
        />
      </label>
      {error && <span role="alert" title={error} className="ml-1 max-w-36 truncate text-xs text-red-500">{error}</span>}
    </div>
  );
}
