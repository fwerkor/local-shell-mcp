import { atom } from 'jotai';
import { serverPreferences } from './serverPreferences';
import { atomWithStorage } from 'jotai/utils';
import type { SyncStorage } from 'jotai/vanilla/utils/atomWithStorage';

/**
 * Create a simple atom with server-owned preference persistence
 * Uses Jotai's atomWithStorage with getOnInit for proper SSR support
 *
 * @param key - server preference key
 * @param defaultValue - default value if no saved value exists
 * @returns Jotai atom with server preference persistence
 */
export function createStorageAtom<T>(key: string, defaultValue: T) {
  const storage: SyncStorage<T> = {
    getItem: (name, fallback) => serverPreferences.get(name, fallback),
    setItem: (name, value) => serverPreferences.set(name, value),
    removeItem: (name) => serverPreferences.set(name, defaultValue),
    subscribe: (name, callback, fallback) =>
      serverPreferences.subscribe(name, () => callback(serverPreferences.get(name, fallback))),
  };
  return atomWithStorage<T>(key, defaultValue, storage, { getOnInit: true });
}

/**
 * Create an atom with server-owned preference persistence and side effects
 * Useful when you need to apply changes to the DOM or trigger other actions
 *
 * @param key - server preference key
 * @param defaultValue - default value if no saved value exists
 * @param onWrite - callback function to run when the value changes
 * @returns Jotai atom with server preference persistence and side effects
 */
export function createStorageAtomWithEffect<T>(
  key: string,
  defaultValue: T,
  onWrite: (value: T) => void,
) {
  const baseAtom = createStorageAtom(key, defaultValue);

  return atom(
    (get) => get(baseAtom),
    (get, set, newValue: T) => {
      set(baseAtom, newValue);
      if (typeof window !== 'undefined') {
        onWrite(newValue);
      }
    },
  );
}

/**
 * Create a SyncStorage adapter that reads/writes to localStorage but does NOT
 * subscribe to browser `storage` events. This prevents cross-tab synchronization
 * for atoms where each tab should maintain independent state.
 *
 * Use this for atoms that represent per-tab working state (e.g., favorites toggle,
 * MCP server selections) rather than user preferences.
 */
export function createTabIsolatedStorage<Value>(): SyncStorage<Value> {
  return {
    getItem(key: string, initialValue: Value): Value {
      if (typeof window === 'undefined') {
        return initialValue;
      }
      try {
        const stored = localStorage.getItem(key);
        if (stored === null) {
          return initialValue;
        }
        return JSON.parse(stored) as Value;
      } catch {
        return initialValue;
      }
    },
    setItem(key: string, newValue: Value): void {
      if (typeof window === 'undefined') {
        return;
      }
      try {
        localStorage.setItem(key, JSON.stringify(newValue));
      } catch {
        // quota exceeded or other write error — silently ignore
      }
    },
    removeItem(key: string): void {
      if (typeof window === 'undefined') {
        return;
      }
      try {
        localStorage.removeItem(key);
      } catch {
        // silently ignore
      }
    },
    // subscribe intentionally omitted — prevents cross-tab sync via storage events
  };
}

/**
 * Create an atom with localStorage persistence that does NOT sync across tabs.
 * Parallels `createStorageAtom` but uses tab-isolated storage.
 *
 * @param key - localStorage key
 * @param defaultValue - default value if no saved value exists
 * @returns Jotai atom with localStorage persistence, isolated per tab
 */
export function createTabIsolatedAtom<T>(key: string, defaultValue: T) {
  return atomWithStorage<T>(key, defaultValue, createTabIsolatedStorage<T>(), {
    getOnInit: true,
  });
}
