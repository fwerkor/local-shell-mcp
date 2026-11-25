import { atom } from 'recoil';
import { SettingsViews, LocalStorageKeys } from 'librechat-data-provider';
import type { TOptionSettings } from '~/common';
import { CHAT_TITLE_IN_TAB_KEY } from '~/utils/documentTitle';
import { atomWithLocalStorage, atomWithServerPreference } from '~/store/utils';
import { STTEndpoints } from '~/common';

const VALID_SPEECH_ENGINES = new Set<string>(Object.values(STTEndpoints));
const LEGACY_EXTERNAL_STT_ENGINES = new Set<string>(['openai', 'azureOpenAI']);
const LEGACY_EXTERNAL_TTS_ENGINES = new Set<string>([
  'openai',
  'azureOpenAI',
  'elevenlabs',
  'localai',
]);

const normalizeSavedSpeechEngine = (
  engine: string,
  legacyExternalEngines: ReadonlySet<string>,
): string => {
  if (VALID_SPEECH_ENGINES.has(engine)) return engine;
  return legacyExternalEngines.has(engine) ? STTEndpoints.external : STTEndpoints.browser;
};

// Static atoms without localStorage
const staticAtoms = {
  abortScroll: atom<boolean>({ key: 'abortScroll', default: false }),
  optionSettings: atom<TOptionSettings>({ key: 'optionSettings', default: {} }),
  currentSettingsView: atom<SettingsViews>({
    key: 'currentSettingsView',
    default: SettingsViews.default,
  }),
  showPopover: atom<boolean>({ key: 'showPopover', default: false }),
  speechSettingsInitialized: atom<boolean>({ key: 'speechSettingsInitialized', default: false }),
};

/** Read synchronously: `useMediaQuery` only resolves after the first paint. */
function isSmallViewport(): boolean {
  return typeof window !== 'undefined' && window.matchMedia('(max-width: 768px)').matches;
}

const preferenceAtoms = {
  // General settings
  sidebarExpanded: atomWithLocalStorage(
    'unifiedSidebarExpanded',
    !isSmallViewport(),
    /**
     * The mobile drawer covers the viewport, so a persisted open state would
     * launch the app into the navigation instead of the conversation.
     * Normalized during atom initialization so the closed state reaches the
     * first paint rather than animating shut after it.
     */
    (saved) => (isSmallViewport() ? false : saved),
  ),
  enableUserMsgMarkdown: atomWithServerPreference<boolean>(
    LocalStorageKeys.ENABLE_USER_MSG_MARKDOWN,
    true,
  ),
  keepScreenAwake: atomWithLocalStorage('keepScreenAwake', true),
  newChatSwitchToHistory: atomWithServerPreference('newChatSwitchToHistory', true),
  chatTitleInTab: atomWithServerPreference(CHAT_TITLE_IN_TAB_KEY, true),

  // Chat settings
  enterToSend: atomWithServerPreference('enterToSend', true),
  /** What Enter does while a run is generating: steer (inject mid-run) or queue (send after). */
  duringRunDefaultAction: atomWithServerPreference<'steer' | 'queue'>(
    'duringRunDefaultAction',
    'steer',
  ),
  /**
   * Whether a steer interrupts generation at the next safe boundary instead of
   * waiting for the run's next tool step. Orthogonal to
   * `duringRunDefaultAction`: that chooses steer-vs-queue, this chooses how
   * soon a steer lands. The composer's interrupt button always interrupts
   * regardless — this only governs the default Enter/steer route.
   */
  steerInterruptsByDefault: atomWithServerPreference('steerInterruptsByDefault', false),
  maximizeChatSpace: atomWithServerPreference('maximizeChatSpace', false),
  chatDirection: atomWithServerPreference('chatDirection', 'LTR'),
  autoExpandTools: atomWithServerPreference(LocalStorageKeys.AUTO_EXPAND_TOOLS, false),
  saveDrafts: atomWithServerPreference('saveDrafts', true),
  /**
   * Whether long user messages render collapsed to a preview with a
   * "Show more" toggle. The clamp is visual only; the full text stays in
   * the DOM, copyable and searchable.
   */
  collapseLongUserMessages: atomWithServerPreference('collapseLongUserMessages', false),
  /**
   * Whether pasting a large block of text attaches it as a `.txt` file instead of
   * flooding the composer. The text still reaches the model in full.
   */
  pasteLongTextAsFile: atomWithServerPreference('pasteLongTextAsFile', true),
  showScrollButton: atomWithServerPreference('showScrollButton', true),
  forkSetting: atomWithServerPreference('forkSetting', ''),
  splitAtTarget: atomWithServerPreference('splitAtTarget', false),
  rememberDefaultFork: atomWithServerPreference(LocalStorageKeys.REMEMBER_FORK_OPTION, false),
  saveBadgesState: atomWithServerPreference('saveBadgesState', false),
  /** User preference for downscaling images before upload; ignored when the admin config sets it */
  clientImageResize: atomWithServerPreference('clientImageResize', false),
  /**
   * Whether copying a message also puts a rendered HTML version on the
   * clipboard, so apps that ignore Markdown (Teams, Outlook, Word) paste the
   * formatting instead of the raw syntax.
   */
  copyRichText: atomWithServerPreference('copyRichText', false),

  // Beta features settings
  modularChat: atomWithServerPreference('modularChat', true),
  LaTeXParsing: atomWithServerPreference('LaTeXParsing', true),
  centerFormOnLanding: atomWithServerPreference('centerFormOnLanding', true),
  /**
   * Whether the mobile drawer stops short of the edge, leaving a strip of the
   * conversation visible that also closes it when tapped. Off by default: the
   * drawer covers the screen and the swipe closes it.
   */
  mobileDrawerStrip: atomWithLocalStorage('mobileDrawerStrip', false),
  showFooter: atomWithServerPreference('showFooter', true),

  // Commands settings
  atCommand: atomWithServerPreference('atCommand', true),
  plusCommand: atomWithServerPreference('plusCommand', true),
  slashCommand: atomWithServerPreference('slashCommand', true),
  dollarCommand: atomWithServerPreference('dollarCommand', true),

  // Speech settings
  conversationMode: atomWithServerPreference('conversationMode', false),
  advancedMode: atomWithServerPreference('advancedMode', false),

  speechToText: atomWithServerPreference('speechToText', true),
  engineSTT: atomWithServerPreference('engineSTT', 'browser', (engine) =>
    normalizeSavedSpeechEngine(engine, LEGACY_EXTERNAL_STT_ENGINES),
  ),
  languageSTT: atomWithServerPreference('languageSTT', ''),
  autoTranscribeAudio: atomWithServerPreference('autoTranscribeAudio', false),
  decibelValue: atomWithLocalStorage('decibelValue', -45),
  autoSendText: atomWithServerPreference('autoSendText', -1),

  textToSpeech: atomWithServerPreference('textToSpeech', true),
  engineTTS: atomWithServerPreference('engineTTS', 'browser', (engine) =>
    normalizeSavedSpeechEngine(engine, LEGACY_EXTERNAL_TTS_ENGINES),
  ),
  voice: atomWithLocalStorage<string | undefined>('voice', undefined),
  cloudBrowserVoices: atomWithLocalStorage('cloudBrowserVoices', false),
  languageTTS: atomWithServerPreference('languageTTS', ''),
  automaticPlayback: atomWithServerPreference('automaticPlayback', false),
  playbackRate: atomWithServerPreference<number | null>('playbackRate', null),
  cacheTTS: atomWithServerPreference('cacheTTS', true),

  // Account settings
  UsernameDisplay: atomWithServerPreference('UsernameDisplay', true),
};

export default { ...staticAtoms, ...preferenceAtoms };
