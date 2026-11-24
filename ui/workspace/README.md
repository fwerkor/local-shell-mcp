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

The resulting `ui/workspace/frontend.tar.gz` is a **gitignored, generated**
archive of compiled React assets without redundant precompressed copies or
source maps. It is never committed to Git. CI and release builds automatically
compile the React app and regenerate the archive on clean checkouts before
packaging the Python wheel or standalone Controller. Docker builds also generate
it from source. Wheels and Controller releases embed the archive; at runtime,
Controller extracts it under `.local-shell-mcp/runtime/webui/` on demand.
Neither running the Controller nor running a Worker requires Bun or Node.js.

For a local wheel build, run the commands above first; a bare `pip wheel`
without a compiled frontend will not build React automatically, because
Python-only environments may deliberately lack the JavaScript toolchain.

Backend integration is implemented by `src/local_shell_mcp/webui/`. The
corresponding API contract inventory is in
`ui/workspace/API_CONTRACT.md`. **Until the full Agent
and control API parity tests pass, this tree remains a work-in-progress and
must not be deployed in place of the production Controller.**
