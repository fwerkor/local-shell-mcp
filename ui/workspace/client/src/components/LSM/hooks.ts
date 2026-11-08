import { useCallback } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { QueryKeys, read, write, type RecordValue } from 'librechat-data-provider';

export function controllerKey(route: string, params: RecordValue = {}) {
  return [QueryKeys.lsmController, route, params] as const;
}

export function useControllerQuery<T>(
  route: string, params: Record<string, string | number | undefined> = {},
  options: { enabled?: boolean; refetchInterval?: number | false } = {},
) {
  return useQuery({
    queryKey: controllerKey(route, params),
    queryFn: () => read<T>(route, params),
    ...options,
  });
}

export function useControllerMutation<T = RecordValue>() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ route, body }: { route: string; body: RecordValue }) => write<T>(route, body),
    onSuccess: () => client.invalidateQueries({ queryKey: [QueryKeys.lsmController] }),
  });
}

/** Query-backed service for imperative operations (selection, polling, binary viewers). */
export function useControllerServices() {
  const client = useQueryClient();
  const mutation = useControllerMutation();
  const query = useCallback(
    <T,>(route: string, params: Record<string, string | number | undefined> = {}) =>
      client.fetchQuery({
        queryKey: controllerKey(route, params),
        queryFn: () => read<T>(route, params),
        staleTime: 0,
      }),
    [client],
  );
  const mutate = useCallback(
    <T,>(route: string, body: RecordValue): Promise<T> =>
      mutation.mutateAsync({ route, body }) as Promise<T>,
    [mutation.mutateAsync],
  );
  return { read: query, write: mutate };
}
