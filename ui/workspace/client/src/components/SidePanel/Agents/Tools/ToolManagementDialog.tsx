import type { ReactNode, RefObject } from 'react';
import { Search } from 'lucide-react';
import {
  Input,
  OGDialog,
  OGDialogTitle,
  OGDialogContent,
  OGDialogDescription,
  useMediaQuery,
} from '@librechat/client';
import { useLocalize } from '~/hooks';
import MarketplaceSidebar, { MarketplaceFilterBar } from './MarketplaceSidebar';
import type { AgentItemKind, ItemFilter } from './items/types';

type View = NonNullable<ItemFilter['view']>;
type Kind = AgentItemKind | 'all';

export default function ToolManagementDialog({
  open,
  onOpenChange,
  view,
  kind,
  onSelectView,
  onSelectKind,
  search,
  onSearch,
  counts,
  totalCount,
  onCreateNew,
  chatMode = false,
  children,
  dialogs,
  triggerRef,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  view: View;
  kind: Kind;
  onSelectView: (view: View) => void;
  onSelectKind: (kind: Kind) => void;
  search: string;
  onSearch: (search: string) => void;
  counts: Record<AgentItemKind, number>;
  totalCount: number;
  onCreateNew?: (kind: 'mcp' | 'action') => void;
  chatMode?: boolean;
  children: ReactNode;
  dialogs?: ReactNode;
  triggerRef?: RefObject<HTMLButtonElement | null>;
}) {
  const localize = useLocalize();
  const isDesktop = useMediaQuery('(min-width: 768px)');
  return (
    <OGDialog open={open} onOpenChange={onOpenChange} triggerRef={triggerRef}>
      {/* The body carries the height from md, the way it did before this change, so
          the shell wraps it and the two cannot disagree: an explicit height on the
          shell would leave its difference from the body's 840px ceiling as dead
          space below the catalog on a tall screen. Below md the shell is the
          full-bleed sheet and the body is capped to the same 100dvh, because its
          `h-full` resolves against a grid area sized to the whole catalog. */}
      <OGDialogContent className="h-[100dvh] max-h-[100dvh] w-full max-w-full overflow-hidden rounded-none border-border-medium p-0 shadow-xl md:h-auto md:max-h-[92vh] md:w-11/12 md:max-w-[1200px] md:rounded-2xl">
        <OGDialogTitle className="sr-only">{localize('com_ui_tools_marketplace')}</OGDialogTitle>
        <OGDialogDescription className="sr-only">
          {localize('com_ui_tools_marketplace_description')}
        </OGDialogDescription>
        {/* min-w-0: as a grid item of the dialog content, an `auto` minimum would
            size this column to the chip row's min-content and overflow the viewport. */}
        <div className="flex h-full max-h-[100dvh] min-w-0 flex-col md:h-[88vh] md:max-h-[840px] md:flex-row">
          {isDesktop && (
            <MarketplaceSidebar
              activeView={view}
              activeKind={kind}
              onSelectView={onSelectView}
              onSelectKind={onSelectKind}
              counts={counts}
              totalCount={totalCount}
              onCreateNew={onCreateNew}
              chatMode={chatMode}
            />
          )}
          <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            {/* md:pl-6, not md:px-6: a responsive variant is emitted after the base
                utilities, so md:px-6 would reset the pr-12 that keeps the search
                field clear of the dialog's close button. */}
            <div className="flex items-center gap-2 px-4 py-3 pr-12 md:py-4 md:pl-6">
              <div className="relative flex-1">
                <Search
                  className="pointer-events-none absolute left-3 top-1/2 z-[1] size-4 -translate-y-1/2 text-text-tertiary"
                  aria-hidden="true"
                />
                <Input
                  type="text"
                  value={search}
                  onChange={(e) => onSearch(e.target.value)}
                  placeholder={localize('com_ui_tools_marketplace_search')}
                  aria-label={localize('com_ui_tools_marketplace_search')}
                  className="bg-transparent pl-9"
                />
              </div>
            </div>
            {!isDesktop && (
              <MarketplaceFilterBar
                activeView={view}
                activeKind={kind}
                onSelectView={onSelectView}
                onSelectKind={onSelectKind}
                counts={counts}
                totalCount={totalCount}
                onCreateNew={onCreateNew}
                chatMode={chatMode}
              />
            )}
            <div className="lsm-tool-management min-h-0 flex-1 overflow-y-auto p-3 md:p-4">
              {children}
            </div>
          </div>
        </div>
        {dialogs}
      </OGDialogContent>
    </OGDialog>
  );
}
