import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { QueryKeys, request } from 'librechat-data-provider';
import { useToastContext } from '@librechat/client';
import { NotificationSeverity } from '~/common';
import { Plus } from 'lucide-react';
import { Button, FilterInput, OGDialogTrigger, TooltipAnchor } from '@librechat/client';
import type { ConversationTagsResponse, TConversationTag } from 'librechat-data-provider';
import { BookmarkContext, useBookmarkContext } from '~/Providers/BookmarkContext';
import { BookmarkEditDialog } from '~/components/Bookmarks';
import BookmarkCardSkeleton from './BookmarkCardSkeleton';
import { PanelContent } from '~/components/ui';
import BookmarkList from './BookmarkList';
import { useLocalize } from '~/hooks';

const removeDuplicates = (bookmarks: TConversationTag[]) => {
  const seen = new Set();
  return bookmarks.filter((bookmark) => {
    const duplicate = seen.has(bookmark._id);
    seen.add(bookmark._id);
    return !duplicate;
  });
};

const BookmarkTable = ({ isLoading = false }: { isLoading?: boolean }) => {
  const localize = useLocalize();
  const [rows, setRows] = useState<ConversationTagsResponse>([]);
  const rowsRef = useRef<ConversationTagsResponse>([]);
  const client = useQueryClient();
  const { showToast } = useToastContext();
  const [searchQuery, setSearchQuery] = useState('');
  const [createOpen, setCreateOpen] = useState(false);

  const { bookmarks = [] } = useBookmarkContext();

  useEffect(() => {
    const _bookmarks = removeDuplicates(bookmarks).sort((a, b) => a.position - b.position);
    rowsRef.current = _bookmarks;
    setRows(_bookmarks);
  }, [bookmarks]);

  const reorder = useMutation((tags: string[]) => request.put('/api/tag-order', { tags }), {
    onSuccess: () => {
      client.setQueryData([QueryKeys.conversationTags], rowsRef.current);
    },
    onError: () => {
      rowsRef.current = [...bookmarks].sort((a, b) => a.position - b.position);
      setRows(rowsRef.current);
      showToast({
        message: localize('com_ui_bookmarks_update_error'),
        severity: NotificationSeverity.ERROR,
      });
    },
    onSettled: () => client.invalidateQueries([QueryKeys.conversationTags]),
  });
  const moveRow = useCallback((dragIndex: number, hoverIndex: number) => {
    const next = [...rowsRef.current];
    if (dragIndex < 0 || dragIndex >= next.length || hoverIndex < 0 || hoverIndex >= next.length)
      return;
    const [movedRow] = next.splice(dragIndex, 1);
    next.splice(hoverIndex, 0, movedRow);
    rowsRef.current = next.map((row, index) => ({ ...row, position: index }));
    setRows(rowsRef.current);
  }, []);
  const finishReorder = (dropped: boolean) => {
    if (!dropped) {
      rowsRef.current = [...bookmarks].sort((a, b) => a.position - b.position);
      setRows(rowsRef.current);
      return;
    }
    reorder.mutate(rowsRef.current.map((row) => row.tag));
  };

  const filteredRows = rows.filter((row) =>
    [row.tag, row.description ?? ''].some((text) =>
      text.toLowerCase().includes(searchQuery.toLowerCase()),
    ),
  );

  return (
    <BookmarkContext.Provider value={{ bookmarks }}>
      <div
        role="region"
        aria-label={localize('com_ui_bookmarks')}
        className="flex min-h-0 flex-1 flex-col"
      >
        {/* Sticky header: filter + create */}
        <div className="flex shrink-0 items-center gap-2 px-3 pb-2">
          <FilterInput
            inputId="bookmarks-filter"
            label={localize('com_ui_bookmarks_filter')}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            containerClassName="flex-1"
          />
          <BookmarkEditDialog context="BookmarkTable" open={createOpen} setOpen={setCreateOpen}>
            <OGDialogTrigger asChild>
              <TooltipAnchor
                description={localize('com_ui_bookmarks_new')}
                side="bottom"
                render={
                  <Button
                    variant="outline"
                    size="icon"
                    className="size-9 shrink-0 bg-transparent"
                    aria-label={localize('com_ui_bookmarks_new')}
                    onClick={() => setCreateOpen(true)}
                  >
                    <Plus className="size-4" aria-hidden="true" />
                  </Button>
                }
              />
            </OGDialogTrigger>
          </BookmarkEditDialog>
        </div>

        {/* Only the list scrolls */}
        <PanelContent
          isLoading={isLoading}
          skeleton={<BookmarkCardSkeleton />}
          className="px-3 pb-3"
        >
          <BookmarkList
            bookmarks={filteredRows}
            moveRow={moveRow}
            finishReorder={finishReorder}
            reorderDisabled={searchQuery.length > 0 || reorder.isLoading}
            isFiltered={searchQuery.length > 0}
          />
        </PanelContent>
      </div>
    </BookmarkContext.Provider>
  );
};

export default BookmarkTable;
