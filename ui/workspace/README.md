# local-shell-mcp WebUI

The React application is maintained as part of the local-shell-mcp `ui/` tree.
The original source comes from LibreChat v0.8.8 (license in `LICENSE`, history
and changes in `VENDORED.md`). Its compiled output is served by the Python
Controller at the same origin as LSM's REST and MCP endpoints.

The JavaScript toolchain is used only at **build time**, and is never
required to run the Controller or Python Worker. The old LibreChat Express
backend, MongoDB, Meilisearch and Docker Compose integration are not shipped.

Build the UI using Bun v1.3.14:

```sh
cd ui/workspace
bun install --frozen-lockfile
bun run frontend
cd ../..
python scripts/embed-react-webui.py
```

The resulting `ui/workspace/frontend.tar.gz` is a deterministic archive of
compiled React assets without redundant precompressed copies or source maps.
Official Controller onefile releases embed that file and extract it under
`.local-shell-mcp/runtime/webui/` only when needed. Worker wheels exclude it.

Backend integration is implemented by `src/local_shell_mcp/webui/`. The
corresponding API contract inventory is in
`ui/workspace/API_CONTRACT.md`. **Until the full Agent
and control API parity tests pass, this tree remains a work-in-progress and
must not be deployed in place of the production Controller.**
