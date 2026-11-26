import type { TConversationTag } from 'librechat-data-provider';
import BookmarkEmptyState from './BookmarkEmptyState';
import BookmarkCard from './BookmarkCard';
import { useLocalize } from '~/hooks';

interface BookmarkListProps {
  bookmarks: TConversationTag[];
  moveRow: (dragIndex: number, hoverIndex: number) => void;
  isFiltered?: boolean;
  finishReorder: (dropped: boolean) => void;
  reorderDisabled: boolean;
}

export default function BookmarkList({
  bookmarks,
  moveRow,
  isFiltered = false,
  finishReorder,
  reorderDisabled,
}: BookmarkListProps) {
  const localize = useLocalize();

  if (bookmarks.length === 0) {
    return <BookmarkEmptyState isFiltered={isFiltered} />;
  }

  return (
    <div className="space-y-2" role="list" aria-label={localize('com_ui_bookmarks')}>
      {bookmarks.map((bookmark, index) => (
        <div key={bookmark._id} role="listitem">
          <BookmarkCard
            bookmark={bookmark}
            position={index}
            moveRow={moveRow}
            finishReorder={finishReorder}
            reorderDisabled={reorderDisabled}
          />
        </div>
      ))}
    </div>
  );
}
