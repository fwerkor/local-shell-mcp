/* Memories */
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import { QueryKeys, MutationKeys, dataService } from 'librechat-data-provider';
import type {
  UseQueryOptions,
  UseMutationOptions,
  QueryObserverResult,
} from '@tanstack/react-query';
import type { TUserMemory, MemoriesResponse, UpdateMemoryResponse } from 'librechat-data-provider';

export const useMemoriesQuery = (
  config?: UseQueryOptions<MemoriesResponse>,
): QueryObserverResult<MemoriesResponse> => {
  return useQuery<MemoriesResponse>([QueryKeys.memories], () => dataService.getMemories(), {
    refetchOnWindowFocus: 'always',
    refetchOnReconnect: 'always',
    refetchOnMount: 'always',
    ...config,
  });
};

export type DeleteMemoryParams = { key?: string; id?: string; agentId?: string };
export const useDeleteMemoryMutation = () => {
  const queryClient = useQueryClient();
  return useMutation(
    ({ key, id, agentId }: DeleteMemoryParams) => {
      if (id) {
        return dataService.deleteMemoryById(id, agentId);
      }
      if (key) {
        return dataService.deleteMemory(key, agentId);
      }
      throw new Error('Memory address is required.');
    },
    {
      onSuccess: () => {
        queryClient.invalidateQueries([QueryKeys.memories]);
      },
    },
  );
};

export type UpdateMemoryParams = {
  key?: string;
  id?: string;
  value: string;
  originalKey?: string;
  agentId?: string;
};
export const useUpdateMemoryMutation = (
  options?: UseMutationOptions<UpdateMemoryResponse, Error, UpdateMemoryParams>,
) => {
  const queryClient = useQueryClient();
  return useMutation(
    ({ key, id, value, originalKey, agentId }: UpdateMemoryParams) => {
      if (id) {
        return dataService.updateMemoryById(id, value, key, agentId);
      }
      if (key) {
        return dataService.updateMemory(key, value, originalKey, agentId);
      }
      throw new Error('Memory address is required.');
    },
    {
      ...options,
      onSuccess: (...params) => {
        queryClient.invalidateQueries([QueryKeys.memories]);
        options?.onSuccess?.(...params);
      },
    },
  );
};

export type UpdateMemoryPreferencesParams = { memories: boolean };
export type UpdateMemoryPreferencesResponse = {
  updated: boolean;
  preferences: { memories: boolean };
};

export const useUpdateMemoryPreferencesMutation = (
  options?: UseMutationOptions<
    UpdateMemoryPreferencesResponse,
    Error,
    UpdateMemoryPreferencesParams
  >,
) => {
  const queryClient = useQueryClient();
  return useMutation<UpdateMemoryPreferencesResponse, Error, UpdateMemoryPreferencesParams>(
    [MutationKeys.updateMemoryPreferences],
    (preferences: UpdateMemoryPreferencesParams) =>
      dataService.updateMemoryPreferences(preferences),
    {
      ...options,
      onSuccess: (...params) => {
        queryClient.invalidateQueries([QueryKeys.user]);
        options?.onSuccess?.(...params);
      },
    },
  );
};

export type CreateMemoryParams = { key: string; value: string; agentId?: string };
export type CreateMemoryResponse = { created: boolean; memory: TUserMemory };

export const useCreateMemoryMutation = (
  options?: UseMutationOptions<CreateMemoryResponse, Error, CreateMemoryParams>,
) => {
  const queryClient = useQueryClient();
  return useMutation<CreateMemoryResponse, Error, CreateMemoryParams>(
    ({ key, value, agentId }: CreateMemoryParams) =>
      dataService.createMemory({ key, value, agentId }),
    {
      ...options,
      onSuccess: (data, variables, context) => {
        void queryClient.invalidateQueries([QueryKeys.memories]);
        options?.onSuccess?.(data, variables, context);
      },
    },
  );
};
