import { serverPreferences } from '~/store/serverPreferences';
import { LocalStorageKeys } from 'librechat-data-provider';

export const CHAT_TITLE_IN_TAB_KEY = 'chatTitleInTab';
export const DEFAULT_APP_TITLE = 'local-shell-mcp';

export const hasRealTitle = (title?: string | null): title is string =>
  title != null && title !== '' && title !== 'New Chat';

const getAppTitle = (): string => {
  try {
    return localStorage.getItem(LocalStorageKeys.APP_TITLE) || DEFAULT_APP_TITLE;
  } catch {
    return DEFAULT_APP_TITLE;
  }
};

/** Read the same in-memory account preference as the Recoil atom. */
export const isChatTitleInTabEnabled = (): boolean =>
  serverPreferences.get(CHAT_TITLE_IN_TAB_KEY, true);

/**
 * Sets the tab title to the conversation title, or to the app title when the
 * conversation title is empty or the user opted out.
 * Pass `enabled` when the atom's value is already known, since Recoil writes to
 * the preference cache after the change handler runs.
 */
export const setDocumentTitle = (title?: string | null, enabled?: boolean): void => {
  const showChatTitle = enabled ?? isChatTitleInTabEnabled();
  document.title = showChatTitle && title != null && title !== '' ? title : getAppTitle();
};
