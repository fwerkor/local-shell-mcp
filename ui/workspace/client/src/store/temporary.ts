import { atomWithLocalStorage, atomWithServerPreference } from '~/store/utils';

const isTemporary = atomWithLocalStorage('isTemporary', false);
const defaultTemporaryChat = atomWithServerPreference('defaultTemporaryChat', false);

export default {
  isTemporary,
  defaultTemporaryChat,
};
