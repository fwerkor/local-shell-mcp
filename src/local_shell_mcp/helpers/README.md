# Bundled helpers

Release and Docker builds generate platform-specific helper binaries below this directory.
They are intentionally not committed to Git.

Linux builds currently bundle a statically linked tmux helper. At runtime, local-shell-mcp
prefers an administrator-configured or system tmux and falls back to the bundled helper.
