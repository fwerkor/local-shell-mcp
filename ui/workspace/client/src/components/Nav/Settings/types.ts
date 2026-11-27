import { createElement } from 'react';
import { MessageSquare, Info, Server, Layers, Keyboard } from 'lucide-react';
import { SettingsTabValues } from 'librechat-data-provider';
import { GearIcon, DataIcon, SpeechIcon } from '@librechat/client';
import type { ComponentType, ReactNode } from 'react';
import type { TranslationKeys } from '~/hooks';

export type SettingsTab =
  | SettingsTabValues.GENERAL
  | SettingsTabValues.CHAT
  | SettingsTabValues.SPEECH
  | SettingsTabValues.DATA
  | SettingsTabValues.ABOUT
  | 'models'
  | 'shortcuts'
  | 'controller';

export type SectionId =
  | 'appearance'
  | 'layout'
  | 'accessibility'
  | 'admin'
  | 'sending'
  | 'commands'
  | 'messages'
  | 'conversations'
  | 'prompts'
  | 'stt'
  | 'tts'
  | 'memory'
  | 'codeExecution'
  | 'data'
  | 'apiKeys'
  | 'danger'
  | 'profile'
  | 'security'
  | 'billing'
  | 'about'
  | 'models'
  | 'shortcuts'
  | 'controller';

export interface SettingsContextValue {
  balanceEnabled: boolean;
  hasAnyPersonalizationFeature: boolean;
  hasMemoryOptOut: boolean;
  hasStatefulCodeSessions: boolean;
  hasRemoteAgents: boolean;
  hasUserProvidedEndpoints: boolean;
  hasMultiConvo: boolean;
  hasPrompts: boolean;
  isLocalProvider: boolean;
  twoFactorEnabled: boolean;
  allowAccountDeletion: boolean;
  aboutEnabled: boolean;
  engineTTS: string;
  adminPanelURL: string;
}

export interface SettingEntry {
  id: string;
  tab: SettingsTab;
  section: SectionId;
  labelKey: TranslationKeys;
  keywords?: string[];
  Component: ComponentType;
  show?: (ctx: SettingsContextValue) => boolean;
}

export interface SectionMeta {
  id: SectionId;
  labelKey: TranslationKeys;
  icon?: ReactNode;
  danger?: boolean;
}

export interface TabMeta {
  id: SettingsTab;
  labelKey: TranslationKeys;
  icon: ReactNode;
  sections: SectionMeta[];
  show?: (ctx: SettingsContextValue) => boolean;
}

export const TABS: TabMeta[] = [
  {
    id: SettingsTabValues.GENERAL,
    labelKey: 'com_nav_setting_general',
    icon: createElement(GearIcon),
    sections: [
      { id: 'profile', labelKey: 'com_ui_settings_section_profile' },
      { id: 'appearance', labelKey: 'com_ui_settings_section_appearance' },
      { id: 'layout', labelKey: 'com_ui_settings_section_layout' },
      { id: 'accessibility', labelKey: 'com_ui_settings_section_accessibility' },
    ],
  },
  {
    id: SettingsTabValues.CHAT,
    labelKey: 'com_nav_setting_chat',
    icon: createElement(MessageSquare, { className: 'icon-sm', 'aria-hidden': true }),
    sections: [
      { id: 'sending', labelKey: 'com_ui_settings_section_sending' },
      { id: 'commands', labelKey: 'com_ui_settings_section_commands' },
      { id: 'messages', labelKey: 'com_ui_settings_section_messages' },
      { id: 'conversations', labelKey: 'com_ui_settings_section_conversations' },
      { id: 'prompts', labelKey: 'com_ui_settings_section_prompts' },
    ],
  },
  {
    id: 'shortcuts',
    labelKey: 'com_shortcut_keyboard_shortcuts',
    icon: createElement(Keyboard, { className: 'icon-sm', 'aria-hidden': true }),
    sections: [{ id: 'shortcuts', labelKey: 'com_shortcut_keyboard_shortcuts' }],
  },
  {
    id: SettingsTabValues.SPEECH,
    labelKey: 'com_nav_setting_speech',
    icon: createElement(SpeechIcon, { className: 'icon-sm' }),
    sections: [
      { id: 'stt', labelKey: 'com_ui_settings_section_stt' },
      { id: 'tts', labelKey: 'com_ui_settings_section_tts' },
    ],
  },
  {
    id: SettingsTabValues.DATA,
    labelKey: 'com_ui_settings_tab_data',
    icon: createElement(DataIcon),
    sections: [
      { id: 'memory', labelKey: 'com_ui_settings_section_memory' },
      { id: 'codeExecution', labelKey: 'com_ui_settings_section_code_execution' },
      { id: 'data', labelKey: 'com_ui_settings_section_data' },
      { id: 'apiKeys', labelKey: 'com_ui_settings_section_api_keys' },
      { id: 'danger', labelKey: 'com_ui_settings_section_danger_zone', danger: true },
    ],
  },
  {
    id: 'models',
    labelKey: 'com_lsm_settings_models',
    icon: createElement(Layers, { className: 'icon-sm', 'aria-hidden': true }),
    sections: [{ id: 'models', labelKey: 'com_lsm_settings_models' }],
  },
  {
    id: 'controller',
    labelKey: 'com_lsm_settings_title',
    icon: createElement(Server, { className: 'icon-sm', 'aria-hidden': true }),
    sections: [{ id: 'controller', labelKey: 'com_lsm_settings_title' }],
  },
  {
    id: SettingsTabValues.ABOUT,
    labelKey: 'com_nav_setting_about',
    icon: createElement(Info, { className: 'icon-sm', 'aria-hidden': true }),
    sections: [{ id: 'about', labelKey: 'com_nav_setting_about' }],
    show: (ctx) => ctx.aboutEnabled,
  },
];
