import React, { useRef } from 'react';
import { useDrag, useDrop } from 'react-dnd';
import { GripVertical } from 'lucide-react';
import { useSetAtom } from 'jotai';
import { chatFilterTagsAtom } from '~/components/Conversations/chatFilters';
import { useActivePanel, DEFAULT_PANEL } from '~/Providers';
import type { TConversationTag } from 'librechat-data-provider';
import { TooltipAnchor } from '@librechat/client';
import BookmarkCardActions from './BookmarkCardActions';
import { useLocalize } from '~/hooks';
import { cn } from '~/utils';

interface BookmarkCardProps {
  bookmark: TConversationTag;
  position: number;
  moveRow: (dragIndex: number, hoverIndex: number) => void;
  finishReorder: (dropped: boolean) => void;
  reorderDisabled: boolean;
}

interface DragItem {
  index: number;
}

export default function BookmarkCard({
  bookmark,
  position,
  moveRow,
  finishReorder,
  reorderDisabled,
}: BookmarkCardProps) {
  const ref = useRef<HTMLDivElement>(null);
  const localize = useLocalize();
  const setTags = useSetAtom(chatFilterTagsAtom);
  const { setActive } = useActivePanel();

  const [, drop] = useDrop({
    accept: 'bookmark',
    canDrop: () => !reorderDisabled,
    drop: () => ({ accepted: true }),
    hover(item: DragItem) {
      if (reorderDisabled || !ref.current || item.index === position) {
        return;
      }
      moveRow(item.index, position);
      item.index = position;
    },
  });

  const [{ isDragging }, drag] = useDrag({
    type: 'bookmark',
    canDrag: () => !reorderDisabled,
    item: { index: position },
    end: (_item, monitor) => finishReorder(monitor.didDrop()),
    collect: (monitor) => ({
      isDragging: monitor.isDragging(),
    }),
  });

  drop(ref);
  const handleRef = useRef<HTMLSpanElement>(null);
  drag(handleRef);

  return (
    <div
      ref={ref}
      className={cn(
        'flex items-center gap-2 rounded-lg px-3 py-2.5',
        'border border-border-light bg-transparent',
        'hover:bg-surface-secondary',
        isDragging && 'opacity-50',
      )}
    >
      {/* Drag handle */}
      <span ref={handleRef} className={cn('shrink-0', !reorderDisabled && 'cursor-move')}>
        <GripVertical className="size-4 text-text-tertiary" aria-hidden="true" />
      </span>

      {/* Tag name */}
      <button
        type="button"
        className="min-w-0 flex-1 rounded text-left text-sm font-semibold text-text-primary hover:underline"
        onClick={() => {
          setTags([bookmark.tag]);
          setActive(DEFAULT_PANEL);
        }}
      >
        <span className="block truncate">{bookmark.tag}</span>
        {bookmark.description && (
          <span className="block truncate text-xs font-normal text-text-secondary">
            {bookmark.description}
          </span>
        )}
      </button>

      {/* Count badge */}
      <TooltipAnchor
        description={`${bookmark.count} ${localize(bookmark.count === 1 ? 'com_ui_conversation' : 'com_ui_conversations')}`}
        side="top"
        render={
          <span className="shrink-0 rounded-full bg-surface-tertiary px-2 py-0.5 text-xs text-text-secondary">
            {bookmark.count}
          </span>
        }
      />

      {/* Actions */}
      <div className="shrink-0">
        <BookmarkCardActions bookmark={bookmark} />
      </div>
    </div>
  );
}
