import { atom } from 'recoil';
import { serverPreferences } from './serverPreferences';

// Improved helper function to create atoms with localStorage
export function atomWithLocalStorage<T>(
  key: string,
  defaultValue: T,
  normalizeSavedValue: (value: T) => T = (value) => value,
) {
  return atom<T>({
    key,
    default: defaultValue,
    effects_UNSTABLE: [
      ({ setSelf, onSet }) => {
        /**
         * The default is captured when the module is evaluated, which can be
         * long before anything subscribes — a login screen resized before the
         * app mounts, for instance. Every path that falls back to it re-checks
         * that assumption here. A caller without a normalizer gets the identity
         * function, so this is inert for them.
         */
        const resolveDefault = () => normalizeSavedValue(defaultValue);
        const savedValue = localStorage.getItem(key);

        if (savedValue === null) {
          const normalizedDefault = resolveDefault();
          if (!Object.is(normalizedDefault, defaultValue)) {
            setSelf(normalizedDefault);
          }
        }
        if (savedValue !== null) {
          try {
            const parsedValue = JSON.parse(savedValue) as T;
            const normalizedValue = normalizeSavedValue(parsedValue);
            if (!Object.is(normalizedValue, parsedValue)) {
              localStorage.setItem(key, JSON.stringify(normalizedValue));
            }
            setSelf(normalizedValue);
          } catch (e) {
            console.error(
              `Error parsing localStorage key "${key}", \`savedValue\`: defaultValue, error:`,
              e,
            );
            /** The stored value is unusable, so the normalized default replaces it. */
            const normalizedDefault = resolveDefault();
            localStorage.setItem(key, JSON.stringify(normalizedDefault));
            setSelf(normalizedDefault);
          }
        }

        onSet((newValue: T) => {
          localStorage.setItem(key, JSON.stringify(newValue));
        });
      },
    ],
  });
}

/** Server-owned account preference; no browser persistence or legacy-value import. */
export function atomWithServerPreference<T>(
  key: string,
  defaultValue: T,
  normalize: (value: T) => T = (value) => value,
) {
  const read = () => normalize(serverPreferences.get(key, defaultValue));
  return atom<T>({
    key,
    default: defaultValue,
    effects_UNSTABLE: [
      ({ setSelf, onSet }) => {
        setSelf(read());
        const unsubscribe = serverPreferences.subscribe(key, () => setSelf(read()));
        onSet((value, _old, isReset) =>
          serverPreferences.set(key, normalize(isReset ? defaultValue : value)),
        );
        return unsubscribe;
      },
    ],
  });
}
