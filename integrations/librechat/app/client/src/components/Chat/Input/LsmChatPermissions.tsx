import { useEffect, useState } from 'react';
import { request } from 'librechat-data-provider';

type Preferences = { web: boolean; lsm: boolean; memory: boolean };
const DEFAULTS: Preferences = { web: true, lsm: true, memory: true };

export default function LsmChatPermissions({ conversationId }: { conversationId?: string | null }) {
  const [prefs, setPrefs] = useState<Preferences>(DEFAULTS);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const available = !!conversationId && conversationId !== 'new';

  useEffect(() => {
    setPrefs(DEFAULTS);
    setError('');
    if (!available) return;
    let cancelled = false;
    void request.get<Preferences>(`/api/lsm/preferences/${encodeURIComponent(conversationId)}`)
      .then((stored) => { if (!cancelled) setPrefs(stored); })
      .catch(() => { if (!cancelled) setError('Unable to load chat permissions'); });
    return () => { cancelled = true; };
  }, [available, conversationId]);

  const update = async (field: keyof Preferences, enabled: boolean) => {
    if (!available || busy) return;
    const previous = prefs;
    const next = { ...prefs, [field]: enabled };
    if (field === 'lsm' && enabled) next.web = true;
    if (field === 'web' && !enabled) next.lsm = false;
    setPrefs(next);
    setBusy(true);
    setError('');
    try {
      const saved = await request.put(`/api/lsm/preferences/${encodeURIComponent(conversationId)}`, next) as Preferences;
      setPrefs(saved);
    } catch {
      setPrefs(previous);
      setError('Unable to update chat permissions');
    } finally {
      setBusy(false);
    }
  };

  if (!available) return null;
  return (
    <details className="relative text-xs" aria-label="Conversation permissions">
      <summary className="cursor-pointer rounded-lg border border-border-medium px-2 py-1.5">Permissions</summary>
      <div className="absolute bottom-full right-0 z-50 mb-2 min-w-52 rounded-lg border border-border-medium bg-surface-primary p-3 shadow-lg">
        <strong className="mb-2 block">This conversation</strong>
        {(['web', 'lsm', 'memory'] as const).map((field) => (
          <label className="my-2 flex cursor-pointer items-center justify-between gap-4" key={field}>
            <span>{field === 'web' ? 'Web search' : field === 'lsm' ? 'LSM tools' : 'Cross-chat memory'}</span>
            <input
              type="checkbox"
              checked={prefs[field]}
              disabled={busy}
              onChange={(event) => { void update(field, event.target.checked); }}
            />
          </label>
        ))}
        <p className="text-text-secondary">LSM tools require web access. Memory off prevents this chat from loading long-term memories.</p>
        {error && <p role="alert" className="mt-2 text-red-500">{error}</p>}
      </div>
    </details>
  );
}
