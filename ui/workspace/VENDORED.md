# Vendored LibreChat source

- Original project: https://github.com/LibreChat-AI/LibreChat
- Original release: v0.8.8
- Original commit: `e8f3be08623663d4ad7f7241e693c94469b63bb0`
- License: MIT, preserved at `LICENSE`
- Local frontend copy: `ui/workspace/`
- Modification: Local Shell MCP authentication, identity and scoped API proxy,
  chat permissions, file upload, native Controller React pages, branding,
  navigation and homepage.

The source is committed directly to this repository and has no nested
`.git` directory, submodule, source download or patch step. Builds use the
Controller build scripts; Node is build-time only. Do not run a standalone upstream clone to prepare it.

Upstream updates must be reviewed deliberately: compare upstream against the
currently vendored commit, retain MIT notices, port the LSM changes within
`ui/workspace/`, run application builds and integration tests and update this
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

## Python port source lock

The original integrated lockfile pins `@librechat/agents 4.0.1` (upstream tag
commit `c4ffb9b1b78421bf63eba3e56993017f922387f3`), LangGraph `1.4.8` and
checkpoint `1.1.3`. See `UPSTREAM_LOCK.json` and `PORTING_MAP.md` for the
source-level mapping, reviewed differences and verification status. A clean
pinned reference checkout is used only during development; it is neither
started as a service nor consulted by production builds. The existing dirty
reference directory is not accepted as pristine upstream source.

`node scripts/export-librechat-reference.cjs <LibreChat-root> <agents-root>`
extracts original schema and pure resume/protocol functions into test fixtures.
These carry upstream licenses and source hashes. They are development oracles,
not a hidden Node backend. Do not equate an approximate custom Agent feature
with the pinned implementation.
