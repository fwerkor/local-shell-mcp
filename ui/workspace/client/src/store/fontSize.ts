import { serverPreferences } from './serverPreferences';
import { applyFontSize } from '@librechat/client';
import { createStorageAtomWithEffect } from './jotai-utils';

const DEFAULT_FONT_SIZE = 'text-base';

/**
 * This atom stores the user's font size preference
 */
export const fontSizeAtom = createStorageAtomWithEffect<string>(
  'fontSize',
  DEFAULT_FONT_SIZE,
  applyFontSize,
);

/**
 * Initialize font size and follow the authenticated account
 * Apply the server preference to the DOM, including after login and logout.
 */
export const initializeFontSize = () => {
  const apply = () => applyFontSize(serverPreferences.get('fontSize', DEFAULT_FONT_SIZE));
  apply();
  return serverPreferences.subscribe('fontSize', apply);
};
