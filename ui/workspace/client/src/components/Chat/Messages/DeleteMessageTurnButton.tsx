import { memo, useRef, useState } from 'react';
import { Trash2 } from 'lucide-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Button,
  OGDialog,
  OGDialogTemplate,
  OGDialogTrigger,
  TooltipAnchor,
  useToastContext,
} from '@librechat/client';
import { QueryKeys, request } from 'librechat-data-provider';
import { useLocalize } from '~/hooks';
import { NotificationSeverity } from '~/common';
import { hoverButtonClasses } from './styles';

function DeleteMessageTurnButton({
  messageId,
  conversationId,
  isLast,
  disabled,
}: {
  messageId: string;
  conversationId?: string | null;
  isLast: boolean;
  disabled: boolean;
}) {
  const localize = useLocalize();
  const { showToast } = useToastContext();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const mutation = useMutation(
    () =>
      request.delete(
        `/api/messages/${encodeURIComponent(conversationId ?? '')}/${encodeURIComponent(messageId)}`,
      ),
    {
      onSuccess: async () => {
        setOpen(false);
        await Promise.all([
          client.invalidateQueries([QueryKeys.messages]),
          client.invalidateQueries(['messageBookmarks']),
        ]);
      },
      onError: () =>
        showToast({
          message: localize('com_ui_message_turn_delete_error'),
          severity: NotificationSeverity.ERROR,
        }),
    },
  );
  if (!conversationId || !messageId) return null;

  const label = localize('com_ui_message_turn_delete');
  return (
    <OGDialog open={open} onOpenChange={setOpen} triggerRef={triggerRef}>
      <OGDialogTrigger asChild>
        <TooltipAnchor
          description={label}
          render={
            <Button
              ref={triggerRef}
              variant="ghost"
              size="icon"
              aria-label={label}
              className={hoverButtonClasses({ isLast, className: '' })}
              disabled={disabled || mutation.isLoading}
              onClick={() => setOpen(true)}
            >
              <Trash2 className="size-[19px]" aria-hidden="true" />
            </Button>
          }
        />
      </OGDialogTrigger>
      <OGDialogTemplate
        showCloseButton={false}
        title={label}
        className="max-w-[450px]"
        main={
          <p className="text-left text-sm text-text-secondary">
            {localize('com_ui_message_turn_delete_confirm')}
          </p>
        }
        selection={{
          selectHandler: () => {
            if (!disabled && !mutation.isLoading) mutation.mutate();
          },
          selectClasses:
            'bg-surface-destructive text-text-on-status hover:bg-surface-destructive-hover',
          selectText: localize('com_ui_delete'),
        }}
      />
    </OGDialog>
  );
}

export default memo(DeleteMessageTurnButton);
