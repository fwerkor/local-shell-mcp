import { atom } from 'recoil';
import { atomWithServerPreference } from '~/store/utils';
import { PromptsEditorMode } from '~/common';

// Static atoms without localStorage
const staticAtoms = {
  // `name` filter
  promptsName: atom<string>({ key: 'promptsName', default: '' }),
  // `category` filter
  promptsCategory: atom<string>({ key: 'promptsCategory', default: '' }),
  // `pageNumber` filter
  promptsPageNumber: atom<number>({ key: 'promptsPageNumber', default: 1 }),
  // `pageSize` filter
  promptsPageSize: atom<number>({ key: 'promptsPageSize', default: 10 }),
};

// Atoms with localStorage
const localStorageAtoms = {
  autoSendPrompts: atomWithServerPreference('autoSendPrompts', true),
  alwaysMakeProd: atomWithServerPreference('alwaysMakeProd', true),
  // Editor mode
  promptsEditorMode: atomWithServerPreference<PromptsEditorMode>(
    'promptsEditorMode',
    PromptsEditorMode.SIMPLE,
  ),
};

export default { ...staticAtoms, ...localStorageAtoms };
