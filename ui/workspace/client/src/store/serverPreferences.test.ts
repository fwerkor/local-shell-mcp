import { ServerPreferences } from './serverPreferences';

jest.mock('librechat-data-provider', () => ({
  apiBaseUrl: () => '',
  request: { get: jest.fn(), patch: jest.fn() },
}));

const flush = async () => {
  await new Promise<void>((resolve) => setTimeout(resolve, 0));
};

describe('server preferences', () => {
  it('supports anonymous appearance without writing it to an account', async () => {
    const patch = jest.fn();
    const prefs = new ServerPreferences(async () => ({ theme: 'light' }), patch, jest.fn());
    const listener = jest.fn();
    prefs.subscribe('theme', listener);
    prefs.set('theme', 'dark');
    expect(prefs.get('theme', 'system')).toBe('dark');
    expect(listener).toHaveBeenLastCalledWith('dark');
    await prefs.load('alice');
    expect(prefs.get('theme', 'system')).toBe('light');
    expect(patch).not.toHaveBeenCalled();
  });

  it('ignores legacy browser preferences and hydrates from the account', async () => {
    localStorage.setItem('autoExpandTools', 'true');
    const prefs = new ServerPreferences(async () => ({}), jest.fn(), jest.fn());
    await prefs.load('alice');
    expect(prefs.get('autoExpandTools', false)).toBe(false);
    localStorage.removeItem('autoExpandTools');
  });

  it('publishes loaded values and persists only changed keys in order', async () => {
    const patch = jest.fn().mockResolvedValue({});
    const prefs = new ServerPreferences(async () => ({ autoExpandTools: true }), patch, jest.fn());
    const listener = jest.fn();
    prefs.subscribe('autoExpandTools', listener);
    await prefs.load('alice');
    expect(prefs.get('autoExpandTools', false)).toBe(true);
    expect(listener).toHaveBeenLastCalledWith(true);
    prefs.set('autoExpandTools', false);
    prefs.set('showThinking', true);
    await flush();
    expect(patch.mock.calls).toEqual([
      [{ autoExpandTools: false }, 'alice'],
      [{ showThinking: true }, 'alice'],
    ]);
    expect(prefs.get('autoExpandTools', true)).toBe(false);
  });

  it('rolls back a failed change and reports the error', async () => {
    const error = new Error('offline');
    const report = jest.fn();
    const prefs = new ServerPreferences(
      async () => ({ autoExpandTools: false }),
      jest.fn().mockRejectedValue(error),
      report,
    );
    await prefs.load('alice');
    prefs.set('autoExpandTools', true);
    expect(prefs.get('autoExpandTools', false)).toBe(true);
    await flush();
    expect(prefs.get('autoExpandTools', true)).toBe(false);
    expect(report).toHaveBeenCalledWith(error);
  });

  it('discards queued writes and late responses from a previous account', async () => {
    let resolve!: (value: Record<string, unknown>) => void;
    const patch = jest.fn().mockResolvedValue({});
    const prefs = new ServerPreferences(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
      patch,
      jest.fn(),
    );
    const loading = prefs.load('alice');
    prefs.reset();
    resolve({ autoExpandTools: true });
    expect(await loading).toBe(false);
    expect(prefs.get('autoExpandTools', false)).toBe(false);

    const next = prefs.load('bob');
    resolve({});
    await next;
    prefs.set('autoExpandTools', true);
    prefs.reset();
    await flush();
    expect(patch).not.toHaveBeenCalled();
  });
});
