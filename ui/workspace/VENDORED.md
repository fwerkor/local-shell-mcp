# Vendored LibreChat source

- Original project: https://github.com/LibreChat-AI/LibreChat
- Original release: v0.8.8
- Original commit: `e8f3be08623663d4ad7f7241e693c94469b63bb0`
- License: MIT, preserved at `app/LICENSE`
- Local copy: `integrations/librechat/app/`
- Modification: Local Shell MCP authentication, identity and scoped API proxy,
  chat permissions, file upload, native Controller React pages, branding,
  navigation and homepage.

The source is committed directly to this repository and has no nested
`.git` directory, submodule, source download or patch step. Builds use the
included `app/Dockerfile`. Do not run a standalone upstream clone to prepare it.

Upstream updates must be reviewed deliberately: compare upstream against the
currently vendored commit, retain MIT notices, port the LSM changes within
`app/`, run application builds and integration tests and update this
document's version/commit. Never automatically download or execute an
unreviewed upstream revision during builds.

## LSM-specific pruning policy

This is a deliberately scoped **single-user** derivative, not a general
LibreChat distribution. We removed standalone OAuth/social/password/LDAP/SAML
sign-in, admin routes, account-management CLI, RUM and Insights collection,
standalone Redis/search/deployment stacks, migration/localization maintenance
scripts, experimental runtimes, and unused benchmark harnesses. The embedded
chat UI includes English, Simplified Chinese and Traditional Chinese; other
languages fall back to English. Controller docs and native UI locales are
maintained independently.

Keep the chat and Agent runtimes, projects and conversation history, provider
selection/BYOK, search, memories, subagents, Ask User, MCP gateway, local
upload integration, Controller settings, and unified Control UI. Services may
still be needed by those systems after their standalone HTTP routes are removed.
PWA stale-asset recovery remains enabled without upstream browser telemetry.

For every update, run `npm run check:lsm`, `npm run frontend`, client TypeScript
checking and the Controller's Python integration tests before publishing.
