import { apiBaseUrl, request } from 'librechat-data-provider';

type Preferences = Record<string, unknown>;
type Listener = (value: unknown) => void;

const endpoint = (owner: string) =>
  `${apiBaseUrl()}/api/user/preferences?owner=${encodeURIComponent(owner)}`;

/** Account preferences are cached only in memory. A session change invalidates queued writes. */
export class ServerPreferences {
  private values: Preferences = {};
  private confirmed: Preferences = {};
  private listeners = new Map<string, Set<Listener>>();
  private generation = 0;
  private owner: string | undefined;
  private revisions = new Map<string, number>();
  private queue: Promise<void> = Promise.resolve();

  constructor(
    private readonly fetchPreferences: (owner: string) => Promise<Preferences>,
    private readonly patchPreferences: (changes: Preferences, owner: string) => Promise<unknown>,
    private readonly reportError: (error: unknown) => void,
  ) {}

  has(key: string) {
    return Object.hasOwn(this.values, key);
  }

  get<T>(key: string, fallback: T): T {
    const value = this.values[key];
    if (!this.has(key) || (value === null && fallback === undefined)) return fallback;
    if (
      fallback !== null &&
      fallback !== undefined &&
      (typeof value !== typeof fallback ||
        Array.isArray(value) !== Array.isArray(fallback) ||
        value === null)
    )
      return fallback;
    return value as T;
  }

  subscribe(key: string, listener: Listener) {
    const listeners = this.listeners.get(key) ?? new Set<Listener>();
    this.listeners.set(key, listeners);
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
      if (!listeners.size) this.listeners.delete(key);
    };
  }

  private publish(key: string) {
    this.listeners.get(key)?.forEach((listener) => listener(this.values[key]));
  }

  private replace(values: Preferences) {
    this.values = { ...values };
    this.confirmed = { ...values };
    this.listeners.forEach((_listeners, key) => this.publish(key));
  }

  reset() {
    this.generation++;
    this.owner = undefined;
    this.revisions.clear();
    this.queue = Promise.resolve();
    this.replace({});
  }

  async load(owner: string) {
    this.reset();
    const generation = this.generation;
    const values = await this.fetchPreferences(owner);
    if (!values || typeof values !== 'object' || Array.isArray(values)) {
      throw new Error('Invalid server preferences');
    }
    if (generation !== this.generation) return false;
    this.owner = owner;
    this.replace(values);
    return true;
  }

  set(key: string, value: unknown) {
    const owner = this.owner;
    const stored = value === undefined ? null : value;
    if (!owner) {
      // Login appearance is ephemeral; account hydration replaces it.
      if (key === 'theme' && !Object.is(this.values[key], stored)) {
        this.values[key] = stored;
        this.publish(key);
      }
      return;
    }
    if (this.has(key) && Object.is(this.values[key], stored)) return;
    const revision = (this.revisions.get(key) ?? 0) + 1;
    this.revisions.set(key, revision);
    this.values[key] = stored;
    this.publish(key);
    const generation = this.generation;
    this.queue = this.queue.then(async () => {
      if (generation !== this.generation) return;
      try {
        await this.patchPreferences({ [key]: stored }, owner);
        if (generation === this.generation) this.confirmed[key] = stored;
      } catch (error) {
        if (generation !== this.generation) return;
        if (this.revisions.get(key) === revision) {
          if (Object.hasOwn(this.confirmed, key)) this.values[key] = this.confirmed[key];
          else delete this.values[key];
          this.publish(key);
        }
        this.reportError(error);
      }
    });
  }
}

export const serverPreferences = new ServerPreferences(
  (owner) => request.get(endpoint(owner)),
  (changes, owner) => request.patch(endpoint(owner), changes),
  (error) => {
    console.error('Could not save user preference', error);
    window.dispatchEvent(new Event('lsm:preference-save-error'));
  },
);
