export default function LsmLocalAttachmentButton() {
  const upload = (file: File | undefined) => {
    const origin = document.querySelector<HTMLMetaElement>('meta[name="lsm-parent-origin"]')?.content;
    if (!origin || window.parent === window || !file) return;
    if (file.size <= 0 || file.size > 32 * 1024 * 1024) {
      window.alert('LSM attachments must be between 1 byte and 32 MiB');
      return;
    }
    window.parent.postMessage({ type: 'lsm:upload', file }, origin);
  };
  return (
    <label
      title="Attach a file to the LSM local machine"
      className="inline-flex cursor-pointer items-center rounded-lg border border-border-medium px-2 py-1.5 text-xs"
    >
      <span>Attach to LSM</span>
      <input
        type="file"
        className="sr-only"
        aria-label="Upload to LSM local machine"
        onChange={(event) => {
          upload(event.target.files?.item(0) ?? undefined);
          event.target.value = '';
        }}
      />
    </label>
  );
}
