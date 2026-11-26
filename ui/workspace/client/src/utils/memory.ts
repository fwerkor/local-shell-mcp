import type { Agents, TUserMemory, MemoryArtifact } from 'librechat-data-provider';
import type { TranslationKeys } from '~/hooks/useLocalize';

type MemoryKeyErrorParams = {
  key: string;
  memories?: TUserMemory[];
  agentId?: string;
  originalKey?: string;
};

type MemoryApiError = {
  response?: { data?: { error?: string } };
};

/** Mirrors the `key` validator on the memory schema in `packages/data-schemas`. */
export const MEMORY_KEY_PATTERN = /^[a-z_]+$/;

const samePartition = (memory: TUserMemory, agentId?: string) =>
  (memory.agentId ?? undefined) === (agentId ?? undefined);

/**
 * Validates a memory key the same way the server does, plus a partition-aware
 * duplicate check so the conflict surfaces before the request is sent.
 * @returns the localization key of the failure, or null when the key is valid
 */
export function getMemoryKeyError({
  key,
  memories,
  agentId,
  originalKey,
}: MemoryKeyErrorParams): TranslationKeys | null {
  const trimmed = key.trim();

  if (!trimmed) {
    return 'com_ui_field_required';
  }

  if (!MEMORY_KEY_PATTERN.test(trimmed)) {
    return 'com_ui_memory_key_validation';
  }

  if (trimmed === originalKey) {
    return null;
  }

  const isTaken = memories?.some(
    (memory) => memory.key === trimmed && samePartition(memory, agentId),
  );

  return isTaken === true ? 'com_ui_memory_key_exists' : null;
}

/**
 * @returns the localization key of the failure, or null when the value is valid
 */
export function getMemoryValueError(value: string): TranslationKeys | null {
  return value.trim() ? null : 'com_ui_field_required';
}

export function getMemoryApiErrorMessage(error: Error, fallback: string): string {
  if (!('response' in error)) {
    return fallback;
  }

  const message = (error as Error & MemoryApiError).response?.data?.error;
  return typeof message === 'string' && message.trim() ? message : fallback;
}

/** Only successful mutations warrant a refresh; quota errors do not. */
export function isMemoryMutation(artifact?: MemoryArtifact): boolean {
  return artifact?.type === 'update' || artifact?.type === 'delete';
}

/** The controller includes the memory artifact on completed inline tool steps. */
export function isMemoryToolMutation(call?: Agents.ToolCall): boolean {
  if (call?.name !== 'set_memory' && call?.name !== 'delete_memory') {
    return false;
  }
  const { artifact } = call as Agents.ToolCall & { artifact?: { memory?: MemoryArtifact } };
  return isMemoryMutation(artifact?.memory);
}
