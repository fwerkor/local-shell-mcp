# WebUI translations

The chat and integrated Controller interface support 41 locales. English is
bundled initially; other locales are loaded on demand. The language picker
uses each language's own name and browser language preferences are normalized
to a supported locale.

When adding or changing a message, update every catalog in this directory.
Keep interpolation names (for example `{{count}}`) and markup placeholders
unchanged. Preserve product and protocol names and use the language's natural
technical terminology. Run `python scripts/check-webui-i18n.py` from the
repository root to verify catalog coverage and placeholder integrity.

Some entries were restored from upstream translations and missing entries
were filled with machine translation. Native-speaker review and terminology
corrections are welcome.
