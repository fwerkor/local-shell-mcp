# File links

`local-shell-mcp` can expose files from the controlled workspace through high-entropy bearer URLs. This is useful when the AI generates reports, archives, PDFs, screenshots, or other artifacts that must be downloaded from or displayed in chat.

## When to use file links

Use file links for:

- Generated PDFs or reports.
- Screenshots and browser artifacts.
- Build outputs.
- Logs that are too large to paste.
- Archives prepared for manual inspection.

Do not use file links for secrets, private keys, credential stores, or unrelated personal data.

## Typical flow

1. Generate or locate a file under `/workspace`.
2. Call `create_file_link` with a TTL and optional download limit. Set `inline=true` when the file should render directly in a browser or Markdown image; the default is `false`, which forces attachment download behavior.
3. Share the returned URL.
4. Revoke the link when no longer needed.

## Relevant tools

| Tool | Purpose |
|---|---|
| `create_file_link` | Create a tokenized URL for a workspace file. |
| `list_file_links` | Show active links. |
| `revoke_file_link` | Disable a link before expiry. |

## Controls

Configuration options include:

- `LOCAL_SHELL_MCP_FILE_DOWNLOAD_ENABLED`
- `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_TTL_S`
- `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_TTL_S`
- `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_MAX_DOWNLOADS`
- `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_FILE_BYTES`

Use shorter TTLs for sensitive artifacts and set maximum download counts when a link is intended for a single recipient.

## Security notes

File links are bearer URLs. Anyone with the URL can download the file until it expires, reaches its download limit, or is revoked. Treat them like temporary secrets.
