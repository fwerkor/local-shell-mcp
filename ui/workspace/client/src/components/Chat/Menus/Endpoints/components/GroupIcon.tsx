import { memo } from 'react';
import { ProviderIcon } from '@librechat/client';
import { resolveProviderId } from 'librechat-data-provider';
import { EntityEndpointMark, isEntityEndpoint } from '~/components/Endpoints/EntityEndpointMark';

interface GroupIconProps {
  iconURL: string;
  groupName: string;
}

function GroupIcon({ iconURL, groupName }: GroupIconProps) {
  return (
    <div className="relative" style={{ width: 20, height: 20, margin: '2px' }} title={groupName}>
      {isEntityEndpoint(iconURL) ? (
        <EntityEndpointMark endpoint={iconURL} />
      ) : (
        <ProviderIcon
          provider={resolveProviderId(iconURL)}
          size={20}
          className="icon-md shrink-0"
        />
      )}
    </div>
  );
}

export default memo(GroupIcon);
