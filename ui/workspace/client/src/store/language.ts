import { atom } from 'recoil';
import { atomWithServerPreference } from './utils';

const defaultLang = () =>
  (typeof navigator !== 'undefined' ? navigator.language || navigator.languages?.[0] : null) ??
  'en';

const lang = atomWithServerPreference('lang', defaultLang());
const languageLoading = atom<boolean>({
  key: 'languageLoading',
  default: false,
});

export default { lang, languageLoading };
