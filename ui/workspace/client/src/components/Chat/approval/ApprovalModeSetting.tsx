import { useId } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { request } from 'librechat-data-provider';
import useLocalize from '~/hooks/useLocalize';

type Mode = 'automatic' | 'dangerous' | 'all' | 'inherit';
type Preference = { mode: Mode; effective: Exclude<Mode, 'inherit'> };
const labels = {
  automatic: 'com_ui_tool_approval_auto',
  dangerous: 'com_ui_tool_approval_dangerous',
  all: 'com_ui_tool_approval_all',
  inherit: 'com_ui_tool_approval_inherit',
} as const;

export function ApprovalModeSelect({
  value, onChange, inherit = false, disabled = false, effective,
}: {
  value: Mode;
  onChange: (mode: Mode) => void;
  inherit?: boolean;
  disabled?: boolean;
  effective?: Preference['effective'];
}) {
  const id = useId();
  const localize = useLocalize();
  return (
    <div className="my-2 flex min-w-0 flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium text-text-primary">
        {localize('com_ui_tool_approval_mode')}
      </label>
      <select id={id} value={value} disabled={disabled}
        className="w-full rounded-lg border border-border-medium bg-surface-primary px-2 py-1.5 text-sm text-text-primary disabled:opacity-50"
        onChange={(event) => onChange(event.target.value as Mode)}>
        {inherit && <option value="inherit">{localize(labels.inherit)}{effective ? ` (${localize(labels[effective])})` : ''}</option>}
        {(['automatic', 'dangerous', 'all'] as const).map((mode) =>
          <option key={mode} value={mode}>{localize(labels[mode])}</option>)}
      </select>
      <p className="text-xs text-text-secondary">{localize('com_ui_tool_approval_description')}</p>
    </div>
  );
}

export default function ApprovalModeSetting({ conversationId }: { conversationId?: string }) {
  const client = useQueryClient();
  const localize = useLocalize();
  const queryKey = ['lsm', 'approval-mode', conversationId ?? 'global'];
  const url = conversationId ? `/api/lsm/approval/${encodeURIComponent(conversationId)}` : '/api/lsm/approval';
  const query = useQuery<Preference>({ queryKey, queryFn: () => request.get(url), retry: false });
  const mutation = useMutation({
    mutationFn: (mode: Mode): Promise<Preference> => request.put(url, { mode }),
    onSuccess: (data) => {
      client.setQueryData(queryKey, data);
      void client.invalidateQueries({ queryKey: ['lsm', 'approval-mode'] });
    },
  });
  return (
    <>
      <ApprovalModeSelect value={query.data?.mode ?? (conversationId ? 'inherit' : 'automatic')}
        inherit={!!conversationId} disabled={!query.data || mutation.isLoading}
        effective={query.data?.effective} onChange={(mode) => mutation.mutate(mode)} />
      {(query.isError || mutation.isError) && <p role="alert" className="text-xs text-status-error">{localize('com_ui_approval_error')}</p>}
    </>
  );
}
