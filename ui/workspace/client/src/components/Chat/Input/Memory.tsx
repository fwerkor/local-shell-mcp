import React, { memo } from 'react';
import { Brain } from 'lucide-react';
import { CheckboxButton } from '@librechat/client';
import { useLocalize, useAuthContext } from '~/hooks';
import { useBadgeRowContext } from '~/Providers';
import { useGetStartupConfig } from '~/data-provider';
import { badgeAccents } from './accents';

function Memory() {
  const localize = useLocalize();
  const { user } = useAuthContext();
  const context = useBadgeRowContext();
  const { toggleState: memoryActive, debouncedChange, isPinned } = context?.memory ?? {};

  const { data: startupConfig } = useGetStartupConfig();
  const canUseMemory = startupConfig?.interface?.memories === true;

  const hasOptedOut = user?.personalization?.memories === false;

  if (!canUseMemory || hasOptedOut) {
    return null;
  }

  return (
    (memoryActive || isPinned) && (
      <CheckboxButton
        disabled={!context?.features.canEdit}
        checked={memoryActive}
        setValue={debouncedChange}
        label={localize('com_ui_memory')}
        isCheckedClassName={badgeAccents.purple}
        icon={<Brain className="icon-md" aria-hidden="true" />}
      />
    )
  );
}

export default memo(Memory);
