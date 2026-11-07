import { isAllowedLsmControllerPath, isLsmSettingsOriginAllowed } from './controller';

describe('LSM Controller settings proxy', () => {
  it('permits only the new explicit settings actions and methods', () => {
    expect(isAllowedLsmControllerPath('settings/view', 'GET')).toBe(true);
    expect(isAllowedLsmControllerPath('settings/save', 'POST')).toBe(true);
    expect(isAllowedLsmControllerPath('settings/restart', 'POST')).toBe(true);
    for (const path of ['settings/view', 'settings/save', 'settings/restart']) {
      expect(isAllowedLsmControllerPath(path, 'HEAD')).toBe(false);
    }
    expect(isAllowedLsmControllerPath('settings/save', 'GET')).toBe(false);
    expect(isAllowedLsmControllerPath('settings/restart', 'GET')).toBe(false);
    expect(isAllowedLsmControllerPath('settings/view', 'POST')).toBe(false);
    expect(isAllowedLsmControllerPath('settings/remove', 'POST')).toBe(false);
    expect(isAllowedLsmControllerPath('settings/save/extra', 'POST')).toBe(false);
  });

  it('accepts same-origin browser mutations but rejects cross-site and absent origins', () => {
    expect(isLsmSettingsOriginAllowed('https://lsm.example', 'lsm.example', 'same-origin')).toBe(true);
    expect(isLsmSettingsOriginAllowed('http://localhost:3080', 'localhost:3080', undefined)).toBe(true);
    expect(isLsmSettingsOriginAllowed('https://lsm.example', 'lsm.example', 'cross-site')).toBe(false);
    expect(isLsmSettingsOriginAllowed('https://lsm.example', 'lsm.example', 'same-site')).toBe(false);
    expect(isLsmSettingsOriginAllowed('https://evil.example', 'lsm.example', 'same-origin')).toBe(false);
    expect(isLsmSettingsOriginAllowed(undefined, 'lsm.example', undefined)).toBe(false);
    expect(isLsmSettingsOriginAllowed('null', 'lsm.example', undefined)).toBe(false);
    expect(isLsmSettingsOriginAllowed('https://lsm.example:444', 'lsm.example', undefined)).toBe(false);
  });
});
