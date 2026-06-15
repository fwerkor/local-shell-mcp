## Summary

- 

## Validation

- [ ] `ruff check .`
- [ ] `pytest -q`
- [ ] `mkdocs build --strict` if docs changed
- [ ] VS Code extension compile if extension files changed

## Safety checklist

- [ ] No secrets, tunnel tokens, OAuth pins, private keys, or bearer file-link URLs are committed.
- [ ] New or changed MCP tools are documented and tested.
- [ ] Host-control, remote-worker, file-link, or credential behavior is explicitly described.
- [ ] Backwards compatibility impact is noted.
