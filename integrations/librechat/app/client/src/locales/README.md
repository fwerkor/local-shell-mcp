# Locales in the LSM chat shell

The bundled LibreChat shell supports English, Simplified Chinese and Traditional
Chinese. Other browser languages fall back to English. The Controller has its
own independent, fully translated documentation and WebUI.

Keep this set in sync with `i18n.ts` and the Appearance language selector. If
another language is required, add the translation and loader together rather
than copying the upstream locale catalog in full.
