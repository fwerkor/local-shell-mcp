# WebUI translations

The chat and integrated Controller interface support 41 locales. English is
bundled initially; other locales are loaded on demand. The language picker
uses each language's own name and browser language preferences are normalized
to a supported locale.

When adding or changing a message, update every catalog in this directory.
Keep interpolation names (for example `{{count}}`) and markup placeholders
unchanged. Preserve product and protocol names and use the language's natural
technical terminology. Run `python scripts/check-webui-i18n.py` from the
repository root to verify catalog coverage and placeholder integrity. The check
also reports likely untranslated English sentences, identical translations for distinct
UI states, and keys without direct source references. These quality heuristics
are advisory: they cannot establish semantic accuracy or replace contextual
review by a fluent speaker. Review dynamic keys,
API-provided labels, and plural forms before removing candidates; do not delete
keys solely because the audit reports them.

Some entries were restored from upstream translations and missing entries
were filled with machine translation. Native-speaker review and terminology
corrections are welcome.
