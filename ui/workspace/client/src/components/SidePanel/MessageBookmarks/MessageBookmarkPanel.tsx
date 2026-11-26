import { useState } from 'react';
import { Bookmark, Pencil, Trash2, Check, X } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import { QueryKeys } from 'librechat-data-provider';
import type { TConversation } from 'librechat-data-provider';
import { useQueryClient } from '@tanstack/react-query';
import { Button, Spinner, useMediaQuery, useToastContext } from '@librechat/client';
import type { MessageBookmark } from '~/data-provider/messageBookmarks';
import { useChangeMessageBookmark, useMessageBookmarks } from '~/data-provider/messageBookmarks';
import { useLocalize } from '~/hooks';
import useSidebarToggle from '~/hooks/Nav/useSidebarToggle';
import useNavigateToConvo, { supersedeNavigation } from '~/hooks/Conversations/useNavigateToConvo';
import { NotificationSeverity } from '~/common';

export default function MessageBookmarkPanel() {
  const localize = useLocalize();
  const navigate = useNavigate();
  const client = useQueryClient();
  const { navigateToConvo } = useNavigateToConvo();
  const { conversationId } = useParams();
  const mobile = useMediaQuery('(max-width: 768px)');
  const { setSidebarOpen } = useSidebarToggle();
  const { showToast } = useToastContext();
  const query = useMessageBookmarks();
  const mutation = useChangeMessageBookmark();
  const [search, setSearch] = useState('');
  const [editing, setEditing] = useState<string | null>(null);
  const [title, setTitle] = useState('');
  const error = () =>
    showToast({
      message: localize('com_ui_message_bookmark_error'),
      severity: NotificationSeverity.ERROR,
    });
  const jump = (item: MessageBookmark) => {
    const open = () => {
      if (conversationId === item.conversationId) {
        supersedeNavigation();
        navigate(
          `/c/${encodeURIComponent(item.conversationId)}?message=${encodeURIComponent(item.messageId)}`,
        );
      } else {
        navigateToConvo(
          client.getQueryData<TConversation>([QueryKeys.conversation, item.conversationId]) ??
            ({
              conversationId: item.conversationId,
              title: item.conversationTitle,
            } as TConversation),
          { currentConvoId: conversationId, messageId: item.messageId },
        );
      }
    };
    if (mobile) setSidebarOpen(false, open);
    else open();
  };
  const save = (item: MessageBookmark) =>
    mutation.mutate(
      { messageId: item.messageId, title },
      {
        onSuccess: () => setEditing(null),
        onError: error,
      },
    );
  const items = (query.data ?? []).filter((item) =>
    [item.title, item.preview, item.conversationTitle].some((text) =>
      text.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()),
    ),
  );
  return (
    <div className="flex h-full min-h-0 flex-col gap-2 px-3 pb-3">
      <input
        aria-label={localize('com_ui_search')}
        placeholder={localize('com_ui_search')}
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        className="w-full rounded-lg border border-border-medium bg-transparent px-3 py-2 text-sm"
      />
      {query.isLoading && <Spinner />}
      {query.isError && (
        <Button variant="outline" onClick={() => void query.refetch()}>
          {localize('com_ui_message_bookmark_error')}
        </Button>
      )}
      {!query.isLoading && !query.isError && items.length === 0 && (
        <p className="p-3 text-sm text-text-secondary">{localize('com_ui_nothing_found')}</p>
      )}
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto">
        {items.map((item) => (
          <div key={item.messageId} className="rounded-lg border border-border-light p-2">
            {editing === item.messageId ? (
              <form
                className="flex items-center gap-1"
                onSubmit={(event) => {
                  event.preventDefault();
                  save(item);
                }}
              >
                <input
                  autoFocus
                  maxLength={256}
                  value={title}
                  aria-label={localize('com_ui_rename')}
                  onChange={(event) => setTitle(event.target.value)}
                  className="min-w-0 flex-1 rounded border border-border-medium bg-transparent p-1 text-sm"
                />
                <Button
                  type="submit"
                  size="icon"
                  variant="ghost"
                  disabled={mutation.isLoading}
                  aria-label={localize('com_ui_save')}
                >
                  <Check className="size-4" />
                </Button>
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  onClick={() => setEditing(null)}
                  aria-label={localize('com_ui_cancel')}
                >
                  <X className="size-4" />
                </Button>
              </form>
            ) : (
              <div className="flex items-start gap-1">
                <button
                  type="button"
                  className="min-w-0 flex-1 rounded p-1 text-left hover:bg-surface-hover"
                  onClick={() => jump(item)}
                >
                  <span className="flex items-center gap-2 text-sm font-medium">
                    <Bookmark className="size-4 shrink-0" />
                    <span className="truncate">
                      {item.title ||
                        item.preview ||
                        item.conversationTitle ||
                        localize('com_ui_untitled')}
                    </span>
                  </span>
                  <span className="mt-1 block truncate text-xs text-text-secondary">
                    {item.conversationTitle}
                  </span>
                  {item.preview && (
                    <span className="mt-1 line-clamp-2 break-words text-xs text-text-secondary">
                      {item.preview}
                    </span>
                  )}
                  <time
                    dateTime={item.createdAt}
                    className="mt-1 block text-xs text-text-secondary"
                  >
                    {new Date(item.createdAt).toLocaleString()}
                  </time>
                </button>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={localize('com_ui_rename')}
                  onClick={() => {
                    setEditing(item.messageId);
                    setTitle(item.title);
                  }}
                >
                  <Pencil className="size-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  disabled={mutation.isLoading}
                  aria-label={localize('com_ui_message_bookmark_remove')}
                  onClick={() =>
                    mutation.mutate({ messageId: item.messageId, remove: true }, { onError: error })
                  }
                >
                  <Trash2 className="size-4" />
                </Button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
