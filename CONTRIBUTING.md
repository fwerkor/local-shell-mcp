# Contributing to local-shell-mcp

Thanks for improving `local-shell-mcp`. This project exposes powerful machine-control tools, so changes should be practical, testable, and conservative about safety boundaries.

## Development setup

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev,docs]'
```

Useful checks:

```bash
ruff check .
pytest -q
mkdocs build --strict
npm --prefix vscode-extension install
npm --prefix vscode-extension run compile
```

## Contribution workflow

1. Open or find an issue before large changes.
2. Keep pull requests focused. Prefer small, reviewable commits.
3. Add or update tests for behavior changes.
4. Update documentation when tool names, configuration, security behavior, or setup steps change.
5. Run `secret_scan` or equivalent checks before pushing anything that may contain credentials.
6. Do not include generated build artifacts such as `site/`, caches, local credentials, or editor state.

## Code style

- Python code must pass `ruff check .`.
- Tests should be deterministic and avoid real external services unless explicitly marked or mocked.
- Public tool descriptions should be precise and operationally useful for AI clients.
- Security-sensitive changes should include tests that cover denied paths, redaction, authentication, timeout, or scoping behavior.

## Tool surface changes

When adding, removing, or renaming MCP tools:

- Update `tests/test_tool_surface.py`.
- Update documentation under `docs/reference/`.
- Consider ChatGPT connector compatibility and output schemas.
- Avoid exposing new host-control surfaces by default.

## Remote worker changes

Remote worker behavior should preserve outbound-only connectivity and near-parity with local tools. Add tests for command execution, file transfer, git operations, and capability filtering when relevant.

## Commit messages

Use concise imperative messages, for example:

```text
Add HTTP validation coverage
Fix remote worker file transfer cleanup
Document GitHub Pages deployment
```

## Pull request checklist

Before requesting review:

- [ ] `ruff check .` passes.
- [ ] `pytest -q` passes.
- [ ] `mkdocs build --strict` passes when documentation changes.
- [ ] VS Code extension compiles when extension files change.
- [ ] README/docs/config examples are updated when user-facing behavior changes.
- [ ] No secrets, credentials, local tunnel tokens, or generated artifacts are committed.
