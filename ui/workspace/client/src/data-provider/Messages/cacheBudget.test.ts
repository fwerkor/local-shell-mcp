import { QueryClient, QueryObserver } from '@tanstack/react-query';
import { QueryKeys } from 'librechat-data-provider';
import { configureMessageCache, installMessageCacheBudget } from './cacheBudget';

test('settled histories are bounded but observed and background histories survive', async () => {
  const client = new QueryClient();
  configureMessageCache(client);
  const stop = installMessageCacheBudget(client);
  const key = (id: string) => [QueryKeys.messages, id];
  try {
    client.setQueryData([QueryKeys.activeJobs], { activeJobIds: ['running'] });
    client.setQueryData(key('running'), [{ messageId: 'run', unfinished: true }]);
    client.setQueryData(key('observed'), []);
    const observer = new QueryObserver(client, { queryKey: key('observed'), enabled: false });
    const unsubscribe = observer.subscribe(() => undefined);
    for (let index = 0; index < 8; index++) client.setQueryData(key('closed-' + index), []);
    await Promise.resolve();
    expect(client.getQueryCache().findAll([QueryKeys.messages])).toHaveLength(5);
    expect(client.getQueryData(key('running'))).toBeDefined();
    expect(client.getQueryData(key('observed'))).toBeDefined();
    unsubscribe();
    await Promise.resolve();
    expect(client.getQueryCache().findAll([QueryKeys.messages])).toHaveLength(4);
  } finally {
    stop();
    client.clear();
  }
});
