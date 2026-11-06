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
