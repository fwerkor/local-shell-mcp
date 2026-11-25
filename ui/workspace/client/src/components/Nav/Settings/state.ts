import { atom } from 'recoil';
import type { SettingsTab } from './types';

export const settingsTabState = atom<SettingsTab | null>({
  key: 'settingsTabState',
  default: null,
});
