import { Constants, QueryKeys } from 'librechat-data-provider';
import type { TMessage } from 'librechat-data-provider';
import type { QueryClient } from '@tanstack/react-query';

const MAX_INACTIVE_HISTORIES = 3;
const HISTORY_CACHE_MS = 2 * 60_000;

/** Automatic query GC cannot distinguish an inactive pane from a generation
 *  still running in the background. Only our settled-history budget may evict
 *  message queries. Install the default before creating any query observers. */
export function configureMessageCache(client: QueryClient) {
  client.setQueryDefaults([QueryKeys.messages], { cacheTime: Infinity });
}

export function installMessageCacheBudget(client: QueryClient) {
  const idleSince = new Map<string, number>();
  let queued = false;
  let disposed = false;
  const prune = () => {
    queued = false;
    if (disposed) return;
    const now = Date.now();
    const jobs = client.getQueryData<{ activeJobIds?: string[] }>([QueryKeys.activeJobs]);
    const active = new Set(jobs?.activeJobIds ?? []);
    const inactive = client
      .getQueryCache()
      .findAll([QueryKeys.messages])
      .filter((query) => {
        const id = query.queryKey[1];
        if (
          typeof id !== 'string' ||
          !id ||
          id === Constants.NEW_CONVO ||
          id === Constants.PENDING_CONVO ||
          active.has(id) ||
          query.getObserversCount() !== 0 ||
          query.state.fetchStatus !== 'idle'
        )
          return false;
        const messages = query.state.data as TMessage[] | undefined;
        const tail = messages?.[messages.length - 1];
        // An optimistic tail or unknown active-job status cannot be discarded.
        if (tail && (!tail.createdAt || !tail.updatedAt || (tail.unfinished && !jobs)))
          return false;
        if (!idleSince.has(id)) idleSince.set(id, now);
        return true;
      })
      .sort(
        (a, b) =>
          (idleSince.get(String(b.queryKey[1])) ?? now) -
            (idleSince.get(String(a.queryKey[1])) ?? now) ||
          b.state.dataUpdatedAt - a.state.dataUpdatedAt,
      );
    inactive.forEach((query, index) => {
      const id = String(query.queryKey[1]);
      if (index >= MAX_INACTIVE_HISTORIES || now - (idleSince.get(id) ?? now) >= HISTORY_CACHE_MS) {
        client.removeQueries({ queryKey: query.queryKey, exact: true });
      }
    });
  };
  const schedule = () => {
    if (!queued) {
      queued = true;
      queueMicrotask(prune);
    }
  };
  const unsubscribe = client.getQueryCache().subscribe((event) => {
    const [prefix, id] = event.query.queryKey;
    if (prefix === QueryKeys.messages && typeof id === 'string') {
      if (event.type === 'removed' || event.type === 'observerAdded') idleSince.delete(id);
      if (event.type === 'observerRemoved' && event.query.getObserversCount() === 0) {
        idleSince.set(id, Date.now());
      }
    }
    if (
      (event.type === 'observerRemoved' || event.type === 'updated') &&
      (prefix === QueryKeys.messages || prefix === QueryKeys.activeJobs)
    )
      schedule();
  });
  const interval = setInterval(prune, 15_000);
  schedule();
  return () => {
    disposed = true;
    unsubscribe();
    clearInterval(interval);
    idleSince.clear();
  };
}
