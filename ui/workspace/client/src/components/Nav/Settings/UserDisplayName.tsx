import { useEffect, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { apiBaseUrl, QueryKeys, request } from 'librechat-data-provider';
import type { TUser } from 'librechat-data-provider';
import { useToastContext } from '@librechat/client';
import { useGetUserQuery } from '~/data-provider';
import { useLocalize } from '~/hooks';

export default function UserDisplayName() {
  const localize = useLocalize();
  const { showToast } = useToastContext();
  const { data: user } = useGetUserQuery();
  const queryClient = useQueryClient();
  const [name, setName] = useState(user?.name || '');
  const savedName = user?.name || '';

  useEffect(() => {
    setName(savedName);
  }, [savedName]);

  const mutation = useMutation(
    (value: string) => request.patch(`${apiBaseUrl()}/api/user`, { name: value }),
    {
      onSuccess: (updatedUser: TUser) => {
        queryClient.setQueryData([QueryKeys.user], updatedUser);
        showToast({ message: localize('com_ui_preferences_updated'), status: 'success' });
      },
      onError: () => {
        showToast({ message: localize('com_ui_error_updating_preferences'), status: 'error' });
      },
    },
  );

  const trimmedName = name.trim();
  const isValid = trimmedName.length <= 80 && !/\p{C}/u.test(trimmedName);

  return (
    <form
      className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (isValid && trimmedName !== savedName) {
          mutation.mutate(trimmedName);
        }
      }}
    >
      <div className="min-w-0">
        <label htmlFor="webui-display-name">{localize('com_ui_display_name')}</label>
        <p className="mt-1 text-xs text-text-secondary">
          {localize('com_ui_display_name_description')}
        </p>
      </div>
      <div className="flex w-full shrink-0 gap-2 sm:w-auto">
        <input
          id="webui-display-name"
          type="text"
          autoComplete="nickname"
          maxLength={80}
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder={localize('com_ui_display_name_placeholder')}
          className="focus-visible:ring-ring min-w-0 flex-1 rounded-lg border border-border-medium bg-surface-primary px-3 py-2 text-sm text-text-primary placeholder:text-text-tertiary focus-visible:outline-none focus-visible:ring-2 sm:w-48"
          disabled={mutation.isLoading}
        />
        <button
          type="submit"
          disabled={mutation.isLoading || !isValid || trimmedName === savedName}
          className="rounded-lg bg-surface-active px-3 py-2 text-sm text-text-primary hover:bg-surface-active-alt disabled:cursor-not-allowed disabled:opacity-50"
        >
          {localize('com_ui_save')}
        </button>
      </div>
    </form>
  );
}
