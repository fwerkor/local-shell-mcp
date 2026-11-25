import { useRecoilValue } from 'recoil';
import { Dropdown, Spinner } from '@librechat/client';
import { useLocalize } from '~/hooks';
import { normalizeLocale, supportedLocales } from '~/locales/i18n';
import english from '~/locales/en/translation.json';
import { cn } from '~/utils';
import store from '~/store';

type PortalElement = ((element: HTMLElement) => HTMLElement | null) | HTMLElement | null;

export const ThemeSelector = ({
  theme,
  onChange,
  portal = true,
  portalElement,
  popoverClassName,
}: {
  theme: string;
  onChange: (value: string) => void;
  portal?: boolean;
  portalElement?: PortalElement;
  popoverClassName?: string;
}) => {
  const localize = useLocalize();

  const themeOptions = [
    { value: 'system', label: localize('com_nav_theme_system') },
    { value: 'dark', label: localize('com_nav_theme_dark') },
    { value: 'light', label: localize('com_nav_theme_light') },
    { value: 'high-contrast-light', label: localize('com_nav_theme_high_contrast_light') },
    { value: 'high-contrast-dark', label: localize('com_nav_theme_high_contrast_dark') },
  ];

  const labelId = 'theme-selector-label';

  return (
    <div className="flex items-center justify-between">
      <div id={labelId}>{localize('com_nav_theme')}</div>

      <Dropdown
        value={theme}
        onChange={onChange}
        options={themeOptions}
        sizeClasses={cn('z-50 w-[180px]', popoverClassName)}
        testId="theme-selector"
        aria-labelledby={labelId}
        portal={portal}
        portalElement={portalElement}
      />
    </div>
  );
};

const languageLabels = {
  'ar': 'com_nav_lang_arabic',
  'bo': 'com_nav_lang_tibetan',
  'bs': 'com_nav_lang_bosnian',
  'ca': 'com_nav_lang_catalan',
  'cs': 'com_nav_lang_czech',
  'da': 'com_nav_lang_danish',
  'de': 'com_nav_lang_german',
  'en': 'com_nav_lang_english',
  'es': 'com_nav_lang_spanish',
  'et': 'com_nav_lang_estonian',
  'fa': 'com_nav_lang_persian',
  'fi': 'com_nav_lang_finnish',
  'fr': 'com_nav_lang_french',
  'he': 'com_nav_lang_hebrew',
  'hu': 'com_nav_lang_hungarian',
  'hy': 'com_nav_lang_armenian',
  'id': 'com_nav_lang_indonesia',
  'is': 'com_nav_lang_icelandic',
  'it': 'com_nav_lang_italian',
  'ja': 'com_nav_lang_japanese',
  'ka': 'com_nav_lang_georgian',
  'ko': 'com_nav_lang_korean',
  'lt': 'com_nav_lang_lithuanian',
  'lv': 'com_nav_lang_latvian',
  'nb': 'com_nav_lang_norwegian_bokmal',
  'nl': 'com_nav_lang_dutch',
  'nn': 'com_nav_lang_norwegian_nynorsk',
  'pl': 'com_nav_lang_polish',
  'pt-BR': 'com_nav_lang_brazilian_portuguese',
  'pt-PT': 'com_nav_lang_portuguese',
  'ru': 'com_nav_lang_russian',
  'sk': 'com_nav_lang_slovak',
  'sl': 'com_nav_lang_slovenian',
  'sv': 'com_nav_lang_swedish',
  'th': 'com_nav_lang_thai',
  'tr': 'com_nav_lang_turkish',
  'ug': 'com_nav_lang_uyghur',
  'uk': 'com_nav_lang_ukrainian',
  'vi': 'com_nav_lang_vietnamese',
  'zh-Hans': 'com_nav_lang_chinese',
  'zh-Hant': 'com_nav_lang_traditional_chinese',
} as const;

export const LangSelector = ({
  langcode,
  onChange,
  portal = true,
  portalElement,
  popoverClassName,
}: {
  langcode: string;
  onChange: (value: string) => void;
  portal?: boolean;
  portalElement?: PortalElement;
  popoverClassName?: string;
}) => {
  const localize = useLocalize();
  const isLanguageLoading = useRecoilValue(store.languageLoading);

  const languageOptions = [
    { value: 'auto', label: localize('com_nav_lang_auto') },
    ...supportedLocales.map((value) => ({ value, label: english[languageLabels[value]].trim() })),
  ];

  const labelId = 'language-selector-label';

  return (
    <div className="flex items-center justify-between">
      <div id={labelId}>{localize('com_nav_language')}</div>

      <div className="flex items-center gap-2">
        {isLanguageLoading && (
          <span
            role="status"
            aria-label={localize('com_ui_loading')}
            className="flex size-5 items-center justify-center text-text-secondary"
          >
            <Spinner className="size-4" />
          </span>
        )}
        <Dropdown
          value={langcode === 'auto' ? 'auto' : normalizeLocale(langcode)}
          onChange={onChange}
          sizeClasses={cn('z-50 w-[220px]', popoverClassName)}
          options={languageOptions}
          aria-labelledby={labelId}
          portal={portal}
          portalElement={portalElement}
          searchable
          searchPlaceholder={localize('com_ui_search_language')}
          searchEmptyText={localize('com_ui_no_results_found')}
        />
      </div>
    </div>
  );
};
