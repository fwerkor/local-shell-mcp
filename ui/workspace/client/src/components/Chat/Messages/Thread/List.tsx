import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Constants, dataService, QueryKeys } from 'librechat-data-provider';
import type { TMessage } from 'librechat-data-provider';
import type { RefObject } from 'react';
import type { ThreadRow } from '~/utils/thread';
import type { TMessageProps } from '~/common';
import { toHistoryStub } from '~/utils/tokens';
import { registerVirtualThreadCapture } from '~/hooks/Messages/virtualThreadCapture';
import Row from './Row';

const RECENT_ROWS = 30;
const INITIAL_ROWS = 16;
const VIRTUAL_THRESHOLD = 40;
const BODY_BATCH = 30;

type ListProps = {
  rows: ThreadRow[];
  currentEditId: TMessageProps['currentEditId'];
  setCurrentEditId: TMessageProps['setCurrentEditId'];
  scrollableRef: RefObject<HTMLDivElement | null>;
  conversationId?: string | null;
  anchorBottom: boolean;
  target: string | null;
  isSubmitting: boolean;
  isFetching: boolean;
};

type RowProps = Pick<ListProps, 'currentEditId' | 'setCurrentEditId'> & {
  row: ThreadRow;
  mounted: boolean;
  parentReady: boolean;
  failed: boolean;
  retry: () => void;
};

function estimateHeight(message: TMessage) {
  return Math.min(
    1200,
    (message.isCreatedByUser ? 72 : 140) + Math.ceil((message.text?.length ?? 0) / 90) * 20,
  );
}

/** A lightweight anchor remains in the DOM for bookmarks, the navigation rail
 *  and native scroll anchoring. The expensive Markdown/tool/component tree is
 *  removed when it leaves the overscan window. Measured heights survive that
 *  removal, so returning to an already visited message does not jump. */
const VirtualRow = memo(function VirtualRow({
  row,
  mounted,
  parentReady,
  failed,
  retry,
  ...edit
}: RowProps) {
  const ref = useRef<HTMLDivElement>(null);
  const height = useRef(0);
  const previousId = useRef(row.message.messageId);
  if (previousId.current !== row.message.messageId) {
    previousId.current = row.message.messageId;
    height.current = 0;
  }
  const renderBody = mounted && !row.message.historyStub && parentReady;
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element || !renderBody) return;
    const measure = () => {
      const next = element.getBoundingClientRect().height;
      if (next > 0) height.current = next;
    };
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [renderBody, row.message.messageId]);

  return (
    <div
      ref={ref}
      data-history-row={row.message.messageId}
      data-history-body={renderBody ? 'mounted' : 'placeholder'}
      className="flow-root"
    >
      {renderBody ? (
        <Row row={row} {...edit} />
      ) : (
        <div
          id={row.message.messageId}
          className="message-render"
          style={{ height: height.current || estimateHeight(row.message) }}
          aria-hidden={!mounted}
        >
          {mounted && failed ? (
            <button type="button" onClick={retry} className="mx-auto my-3 text-sm underline">
              Retry loading message
            </button>
          ) : null}
        </div>
      )}
    </div>
  );
});

/** Only render the latest/visible rows. Keep a compact message graph in the
 *  ordinary cache: selection and usage still see every branch, while the
 *  server supplies old assistant bodies in bounded batches. */
function List({
  rows,
  currentEditId,
  setCurrentEditId,
  scrollableRef,
  conversationId,
  anchorBottom,
  target,
  isSubmitting,
  isFetching,
}: ListProps) {
  const queryClient = useQueryClient();
  const listRef = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState<Set<string>>(() => new Set());
  const [captureAll, setCaptureAll] = useState(false);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const retry = useCallback(() => {
    setFailed(false);
    setAttempt((n) => n + 1);
  }, []);
  const virtual = rows.length > VIRTUAL_THRESHOLD && typeof IntersectionObserver !== 'undefined';
  const idsKey = JSON.stringify(rows.map((row) => row.message.messageId));
  const rowIds: string[] = useMemo(() => JSON.parse(idsKey), [idsKey]);
  const queryKey = useMemo(() => [QueryKeys.messages, conversationId ?? ''], [conversationId]);

  // Ancestor DOM refs attach after child layout effects on first mount.
  useEffect(() => {
    setVisible(new Set());
    const root = scrollableRef.current;
    const list = listRef.current;
    if (!virtual || !root || !list) return;
    const observer = new IntersectionObserver(
      (entries) => {
        setVisible((previous) => {
          const next = new Set(previous);
          let changed = false;
          for (const entry of entries) {
            const id = (entry.target as HTMLElement).dataset.historyRow;
            if (!id) continue;
            if (entry.isIntersecting && !next.has(id)) {
              next.add(id);
              changed = true;
            }
            if (!entry.isIntersecting && next.delete(id)) changed = true;
          }
          return changed ? next : previous;
        });
      },
      { root, rootMargin: '100% 0px 100% 0px' },
    );
    for (const element of list.querySelectorAll('[data-history-row]')) observer.observe(element);
    return () => observer.disconnect();
  }, [rowIds, scrollableRef, virtual]);

  const mounted = useMemo(() => {
    const ids = new Set(visible);
    if (!virtual || captureAll) for (const id of rowIds) ids.add(id);
    else {
      // Keep the streaming tail alive even while the reader browses history.
      for (const id of rowIds.slice(-INITIAL_ROWS)) ids.add(id);
      if (!anchorBottom && visible.size === 0) {
        for (const id of rowIds.slice(0, INITIAL_ROWS)) ids.add(id);
      }
    }
    if (target) ids.add(target);
    if (typeof currentEditId === 'string') ids.add(currentEditId);
    return ids;
  }, [visible, rowIds, virtual, captureAll, anchorBottom, target, currentEditId]);
  const needed = useMemo(() => {
    const ids = new Set(mounted);
    // A response's rerun action reads its original user turn synchronously.
    for (const row of rows) {
      if (mounted.has(row.message.messageId) && row.message.parentMessageId) {
        ids.add(row.message.parentMessageId);
      }
    }
    return ids;
  }, [mounted, rows]);
  const stubs = new Set(
    rows.filter((row) => row.message.historyStub).map((row) => row.message.messageId),
  );
  const missingKey = JSON.stringify(rowIds.filter((id) => needed.has(id) && stubs.has(id)));

  useEffect(() => {
    const ids: string[] = JSON.parse(missingKey);
    if (!ids.length || isFetching || !conversationId || conversationId === Constants.NEW_CONVO)
      return;
    let cancelled = false;
    setFailed(false);
    const hydrate = async () => {
      const pages: TMessage[] = [];
      for (let i = 0; i < ids.length; i += BODY_BATCH) {
        pages.push(
          ...(await dataService.getHistoryBodies(conversationId, ids.slice(i, i + BODY_BATCH))),
        );
        if (cancelled) return;
      }
      const bodies = new Map(pages.map((message) => [message.messageId, message]));
      const current = queryClient.getQueryData<TMessage[]>(queryKey) ?? [];
      if (
        current.some(
          (message) =>
            ids.includes(message.messageId) &&
            message.historyStub &&
            bodies.get(message.messageId)?.updatedAt !== message.updatedAt,
        )
      ) {
        setFailed(true);
        void queryClient.invalidateQueries(queryKey);
        return;
      }
      queryClient.setQueryData<TMessage[]>(queryKey, (previous) =>
        previous?.map((message) => {
          const body = bodies.get(message.messageId);
          return message.historyStub && body && body.updatedAt === message.updatedAt
            ? body
            : message;
        }),
      );
    };
    void hydrate().catch(() => {
      if (!cancelled) setFailed(true);
    });
    return () => {
      cancelled = true;
    };
  }, [missingKey, conversationId, queryClient, queryKey, isFetching, attempt]);

  const mountedKey = JSON.stringify([...needed].sort());
  useEffect(() => {
    if (!virtual || captureAll || isSubmitting || isFetching || !conversationId) return;
    const timer = window.setTimeout(() => {
      const active = queryClient.getQueryData<{ activeJobIds?: string[] }>([QueryKeys.activeJobs]);
      if (active?.activeJobIds?.includes(conversationId)) return;
      const keep = new Set<string>(JSON.parse(mountedKey));
      queryClient.setQueryData<TMessage[]>(queryKey, (previous) => {
        if (!previous) return previous;
        for (const message of previous.slice(-RECENT_ROWS)) keep.add(message.messageId);
        let changed = false;
        const next = previous.map((message) => {
          if (
            keep.has(message.messageId) ||
            message.historyStub ||
            message.unfinished ||
            !message.createdAt ||
            !message.updatedAt
          )
            return message;
          changed = true;
          return toHistoryStub(message);
        });
        return changed ? next : previous;
      });
    }, 800);
    return () => window.clearTimeout(timer);
  }, [
    mountedKey,
    virtual,
    captureAll,
    isSubmitting,
    isFetching,
    conversationId,
    queryClient,
    queryKey,
    missingKey,
  ]);

  useEffect(() => {
    if (!conversationId || conversationId === Constants.NEW_CONVO) return;
    return registerVirtualThreadCapture(async () => {
      const release = () => setCaptureAll(false);
      try {
        const cached = queryClient.getQueryData<TMessage[]>(queryKey) ?? [];
        if (cached.some((message) => message.historyStub)) {
          const full = await dataService.getMessagesByConvoId(conversationId);
          const byId = new Map(full.map((message) => [message.messageId, message]));
          if (cached.some((message) => message.historyStub && !byId.has(message.messageId))) {
            throw new Error('Historical message no longer exists');
          }
          queryClient.setQueryData<TMessage[]>(queryKey, (previous) =>
            previous?.map((message) =>
              message.historyStub ? (byId.get(message.messageId) ?? message) : message,
            ),
          );
        }
        setCaptureAll(true);
        // Do not silently capture placeholders if a commit or a query
        // notification was delayed by a long-running render.
        for (let frame = 0; frame < 120; frame++) {
          await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
          if (
            listRef.current &&
            !listRef.current.querySelector('[data-history-body="placeholder"]')
          ) {
            return release;
          }
        }
        throw new Error('Full message thread did not finish mounting');
      } catch (error) {
        release();
        throw error;
      }
    });
  }, [conversationId, queryClient, queryKey]);

  return (
    <div ref={listRef}>
      {rows.map((row) => (
        <VirtualRow
          key={row.depth}
          row={row}
          mounted={mounted.has(row.message.messageId)}
          parentReady={!row.message.parentMessageId || !stubs.has(row.message.parentMessageId)}
          failed={failed}
          retry={retry}
          currentEditId={currentEditId}
          setCurrentEditId={setCurrentEditId}
        />
      ))}
    </div>
  );
}

export default memo(List);
