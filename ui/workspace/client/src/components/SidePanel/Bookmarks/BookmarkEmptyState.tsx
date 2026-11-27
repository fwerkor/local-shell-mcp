import { Tag } from 'lucide-react';
import { EmptyState } from '@librechat/client';
import { useLocalize } from '~/hooks';

interface BookmarkEmptyStateProps {
  isFiltered?: boolean;
}

export default function BookmarkEmptyState({ isFiltered = false }: BookmarkEmptyStateProps) {
  const localize = useLocalize();

  if (isFiltered) {
    return <EmptyState icon={Tag} description={localize('com_ui_no_bookmarks_match')} />;
  }

  return (
    <EmptyState
      icon={Tag}
      title={localize('com_ui_no_bookmarks_title')}
      description={localize('com_ui_add_first_bookmark')}
    />
  );
}
