# Runtime choices and deployment model

`local-shell-mcp` has two independent decisions:

1. **Runtime**: how the server process runs and what workspace it controls.
2. **Client connection**: how ChatGPT or another MCP client reaches that server.

Do not treat ChatGPT as a deployment method. ChatGPT is a client. Docker, the VS Code extension, release binaries, Python installs, and stdio mode are runtime choices.

```text
Runtime layer                      Exposure layer                 Client layer
-------------------------------    ---------------------------    ----------------------
Docker Compose                     local HTTP only                ChatGPT custom MCP
VS Code extension                  HTTPS reverse proxy/tunnel     Generic MCP client
Standalone binary                  stdio process pipe             VS Code extension UI
pipx / source checkout             remote-worker outbound join    REST-style diagnostics
```

A common public setup is:

```text
ChatGPT
  -> https://mcp.example.com/mcp
  -> reverse proxy or tunnel
  -> local-shell-mcp runtime
  -> controlled workspace
```

A local MCP-client setup can be simpler:

```text
Local MCP client
  -> starts local-shell-mcp --mode stdio
  -> controlled workspace
```

## Runtime choice matrix

| Runtime | Best for | Isolation boundary | Toolchain source | Public ChatGPT access | Page |
|---|---|---|---|---|---|
| Docker Compose | Most coding-agent workloads and repeatable workspaces | Container | Project image includes broad default tooling | Add HTTPS proxy or tunnel | [Docker Compose](../installation/docker.md) |
| Docker Compose + tunnel sidecar | One-stack public deployment with Cloudflare Tunnel | Container | Project image | Built into Compose `tunnel` profile | [Docker Compose](../installation/docker.md#cloudflare-tunnel-sidecar) |
| VS Code extension | Starting/stopping a server from an editor workspace | Usually host process | Host tools, plus configured executable | Add external HTTPS tunnel/proxy for ChatGPT | [VS Code extension](../installation/vscode-extension.md) |
| Standalone binary | Hosts or VMs where Docker is unavailable | Host or VM | Host tools | Add HTTPS proxy/tunnel | [Standalone binary](../installation/binary.md) |
| `pipx` / source install | Python-native use, debugging, development | Host virtualenv or VM | Python package plus host tools | Add HTTPS proxy/tunnel | [Python install](../installation/python.md) |
| Stdio mode | Local MCP clients that spawn tools directly | Client process boundary | Host tools | Not usable by ChatGPT web/app | [Stdio mode](../installation/stdio.md) |

## Client connection matrix

| Client path | Requires public HTTPS | Uses `/mcp` | Requires OAuth | Typical runtime |
|---|---:|---:|---:|---|
| ChatGPT custom MCP connector | Yes | Yes | Yes for public use | Docker, VS Code extension, binary, or Python |
| Generic local MCP client over stdio | No | No | No | `local-shell-mcp --mode stdio` |
| Generic HTTP MCP client | Usually no for localhost; yes across networks | Yes | Recommended outside localhost | Any HTTP runtime |
| VS Code extension helper flow | Only if ChatGPT must connect | Yes when copying ChatGPT URL | Recommended for ChatGPT | VS Code-launched runtime |

See [ChatGPT connector](../getting-started/chatgpt-connector.md), [generic MCP clients](../clients/generic-mcp.md), and [network connectivity](../clients/connectivity.md).

## What each runtime controls

Every runtime launches the same server code and exposes the same MCP tool families when enabled:

- Shell and persistent shell sessions.
- Filesystem, search, and patch tools.
- Git operations.
- Browser automation through Playwright.
- Audit log and task-state tools.
- Tokenized file links.
- Optional remote-worker lifecycle and machine-routed tools.

The difference is not the abstract API. The difference is the **operating environment** behind that API.

| Question | Docker Compose | VS Code extension | Binary / Python |
|---|---|---|---|
| Where do commands run? | Inside the container | Usually on the host workspace | In the host or VM process environment |
| What is the default workspace? | Mounted `/workspace` | Current VS Code folder or configured path | `LOCAL_SHELL_MCP_WORKSPACE_ROOT` |
| Are compilers and browsers preinstalled? | Broadly yes | Only if installed on host | Only if installed on host |
| Is it easy to reset? | Remove/recreate container and workspace volume | Depends on workspace | Depends on host/VM |
| Is it appropriate for arbitrary package installs? | Yes, if disposable | Riskier on host | Riskier unless inside VM |

## Recommended selection

Use **Docker Compose** first unless you have a reason not to. It gives the clearest safety boundary and the most complete default toolchain.

Use the **VS Code extension** when the workflow starts from an editor and you want a local launcher. It is still a runtime. It does not by itself make the server reachable from ChatGPT; add a tunnel or reverse proxy when using ChatGPT web/app.

Use a **standalone binary** when Docker is unavailable but a VM, container host, or dedicated user account already provides a boundary.

Use **`pipx` or source install** for development and debugging of `local-shell-mcp` itself, or when a Python-based environment is easier to maintain.

Use **stdio mode** only for local MCP clients that can spawn the server process. It is not a public deployment and it is not usable by ChatGPT web/app directly.

## Public endpoint rule

For HTTP MCP clients such as ChatGPT, the MCP endpoint is:

```text
https://your-public-host.example.com/mcp
```

`LOCAL_SHELL_MCP_PUBLIC_BASE_URL` is the origin only:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

Do not append `/mcp` to `LOCAL_SHELL_MCP_PUBLIC_BASE_URL`.

## Runtime pages

- [Docker Compose](../installation/docker.md)
- [VS Code extension](../installation/vscode-extension.md)
- [Standalone binary](../installation/binary.md)
- [Python, `pipx`, and source install](../installation/python.md)
- [Stdio mode](../installation/stdio.md)

## Client pages

- [ChatGPT connector](../getting-started/chatgpt-connector.md)
- [Generic MCP clients](../clients/generic-mcp.md)
- [Public HTTPS exposure](../clients/connectivity.md)
