import { memo, useCallback } from 'react';
import { Bookmark } from 'lucide-react';
import { Button, TooltipAnchor, useToastContext } from '@librechat/client';
import { Constants } from 'librechat-data-provider';
import type { MessageBookmark } from '~/data-provider/messageBookmarks';
import { useMessageBookmarks, useChangeMessageBookmark } from '~/data-provider/messageBookmarks';
import { useLocalize } from '~/hooks';
import { NotificationSeverity } from '~/common';
import { hoverButtonClasses } from './styles';

function MessageBookmarkButton({
  messageId,
  conversationId,
  isLast,
}: {
  messageId: string;
  conversationId?: string | null;
  isLast: boolean;
}) {
  const localize = useLocalize();
  const { showToast } = useToastContext();
  const enabled =
    !!conversationId &&
    conversationId !== Constants.NEW_CONVO &&
    conversationId !== Constants.PENDING_CONVO &&
    !!messageId;
  const select = useCallback(
    (items: MessageBookmark[]) => items.some((item) => item.messageId === messageId),
    [messageId],
  );
  const query = useMessageBookmarks(enabled, select);
  const mutation = useChangeMessageBookmark();
  if (!enabled) return null;
  const saved = query.data === true;
  const label = localize(saved ? 'com_ui_message_bookmark_remove' : 'com_ui_message_bookmark_add');
  return (
    <TooltipAnchor
      description={label}
      render={
        <Button
          variant="ghost"
          size="icon"
          aria-label={label}
          aria-pressed={saved}
          className={hoverButtonClasses({ isActive: saved, isLast, className: '' })}
          disabled={query.isLoading || query.isError || mutation.isLoading}
          onClick={() =>
            mutation.mutate(
              { messageId, remove: saved },
              {
                onError: () =>
                  showToast({
                    message: localize('com_ui_message_bookmark_error'),
                    severity: NotificationSeverity.ERROR,
                  }),
              },
            )
          }
        >
          <Bookmark className="size-[19px]" fill={saved ? 'currentColor' : 'none'} />
        </Button>
      }
    />
  );
}

export default memo(MessageBookmarkButton);
