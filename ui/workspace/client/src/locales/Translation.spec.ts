import i18n, { changeLanguageSafely, normalizeLocale, supportedLocales } from './i18n';

describe('WebUI locales', () => {
  afterEach(async () => {
    await changeLanguageSafely('en');
  });

  it('normalizes stored language codes and browser locale variants', () => {
    expect(normalizeLocale('ja-JP')).toBe('ja');
    expect(normalizeLocale('ru-RU')).toBe('ru');
    expect(normalizeLocale('zh-Hant-HK')).toBe('zh-Hant');
    expect(normalizeLocale('pt-BR')).toBe('pt-BR');
    expect(normalizeLocale('pt')).toBe('pt-PT');
    expect(normalizeLocale('ar-EG')).toBe('ar');
    expect(normalizeLocale('not-a-language')).toBe('en');
    expect(supportedLocales).toHaveLength(41);
  });

  it.each([
    ['zh-Hans', '上下文窗口', '项目'],
    ['ja', 'コンテキストウィンドウ', 'プロジェクト'],
    ['ru', 'Контекстное окно', 'Проекты'],
  ])('loads visible context and project labels in %s', async (locale, context, projects) => {
    await changeLanguageSafely(locale);
    expect(i18n.t('com_ui_context_window')).toBe(context);
    expect(i18n.t('com_ui_projects')).toBe(projects);
    expect(i18n.t('com_ui_output')).not.toBe('Output');
    expect(i18n.t('com_ui_context_free')).not.toBe('Free space');
    expect(document.documentElement.lang).toBe(locale);
  });

  it.each(supportedLocales)('loads retained dynamic and common keys in %s', async (locale) => {
    await changeLanguageSafely(locale);
    for (const key of [
      'com_ui_special_var_current_date',
      'com_ui_special_var_desc_current_date',
      'com_ui_context_window',
      'com_ui_context_cache_hit_rate',
      'com_ui_context_input_composition',
      'com_ui_projects',
    ] as const) {
      const value = i18n.getResource(locale, 'translation', key);
      expect(typeof value).toBe('string');
      expect(value).not.toBe('');
      expect(i18n.t(key)).toBe(value);
    }
  });

  it.each([
    ['en', 'Tags', 'No tags yet', 'No tags match your search', 'Bookmarks'],
    ['zh-Hans', '标签', '还没有标签', '没有标签符合您的搜索', '书签'],
    ['zh-Hant', '標籤', '尚無標籤', '沒有符合搜尋條件的標籤', '書籤'],
  ])(
    'distinguishes conversation tags from message bookmarks in %s',
    async (locale, tags, empty, noMatch, bookmarks) => {
      await changeLanguageSafely(locale);
      expect(i18n.t('com_ui_bookmarks')).toBe(tags);
      expect(i18n.t('com_ui_no_bookmarks_title')).toBe(empty);
      expect(i18n.t('com_ui_no_bookmarks_match')).toBe(noMatch);
      expect(i18n.t('com_shortcut_open_bookmarks')).toBe(tags);
      expect(i18n.t('com_ui_message_bookmarks')).toBe(bookmarks);
    },
  );

  it('sets RTL direction when loading Arabic', async () => {
    await changeLanguageSafely('ar');
    expect(document.documentElement.dir).toBe('rtl');
  });
});
