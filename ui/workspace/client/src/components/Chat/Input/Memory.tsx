import { memo } from 'react';
import { Brain } from 'lucide-react';
import { CheckboxButton } from '@librechat/client';
import { useLocalize, useAuthContext } from '~/hooks';
import { useBadgeRowContext } from '~/Providers';
import { useGetStartupConfig } from '~/data-provider';
import { badgeAccents } from './accents';

function Memory() {
  const localize = useLocalize();
  const { user } = useAuthContext();
  const features = useBadgeRowContext()?.features;
  const { data: startupConfig } = useGetStartupConfig();

  if (startupConfig?.interface?.memories !== true || !features) {
    return null;
  }

  const optedOut = user?.personalization?.memories === false;
  return (
    <CheckboxButton
      disabled={optedOut || !features.canEdit}
      checked={!optedOut && (features.current?.memory ?? false)}
      setValue={({ value }) => features.toggle('memory', value === true)}
      label={localize('com_ui_memory')}
      isCheckedClassName={badgeAccents.purple}
      icon={<Brain className="icon-md" aria-hidden="true" />}
    />
  );
}

export default memo(Memory);
