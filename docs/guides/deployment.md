# Runtime choices and deployment model

`local-shell-mcp` has two complementary decisions:

1. **Runtime**: how the server process runs and what workspace it controls.
2. **Interface**: use the optional [unified web workspace](../getting-started/web-workspace.md), or connect an external MCP client such as Gemini or ChatGPT.

The recommended daily interface is the self-hosted web workspace (chat, projects and LSM control pages). It is deployed separately from the Controller. **The standalone single-file release executable is the recommended Controller runtime.** It does not require an installed Python interpreter, Docker, or a source checkout. Docker Compose, the VS Code extension, Python installs, source checkout, and stdio are alternatives; external chat apps remain optional clients.

```text
Runtime layer                      Exposure layer                 Client layer
-------------------------------    ---------------------------    ----------------------
Docker Compose                     local HTTP only                Unified web workspace
VS Code extension                  HTTPS reverse proxy/tunnel     Generic MCP client
Standalone binary                  stdio process pipe             VS Code extension UI
pipx / source checkout             remote-worker outbound join    REST-style diagnostics
```

A common self-hosted setup is:

```text
Browser -> https://chat.example.com (unified web workspace)
        -> authenticated local-shell-mcp Controller
        -> controlled workspace and outbound Workers
Optional external client -> https://mcp.example.com/mcp
```

A local MCP-client setup can be simpler:

```text
Local MCP client
  -> starts local-shell-mcp --mode stdio
  -> controlled workspace
```

**For public HTTP access, prefer a direct deployment on a public server or forwarding through one** with an HTTPS reverse proxy. **Cloudflare Tunnel is not recommended** for file-intensive workflows: slow client-side uploads can make file uploads and transfers impractical. Keep it as a fallback when a public server or forwarding path is unavailable. See [network connectivity](../clients/connectivity.md).

## Runtime choice matrix

| Runtime | Best for | Isolation boundary | Toolchain source | External MCP access | Page |
|---|---|---|---|---|---|
| **Standalone single-file binary (recommended)** | Most deployments on supported OS/architectures | Host or VM | Host tools | Add HTTPS proxy/tunnel | [Standalone binary](../installation/binary.md) |
| Docker Compose | Disposable container environments and repeatable workspaces | Container | Lean Controller image; install task-specific toolchains separately | Add HTTPS proxy or tunnel | [Docker Compose](../installation/docker.md) |
| Docker Compose + tunnel sidecar | Fallback only; not recommended for file transfers | Container | Project image | Optional Compose `tunnel` profile; potentially slow uploads | [Docker Compose](../installation/docker.md#cloudflare-tunnel-sidecar) |
| VS Code extension | Starting/stopping a server from an editor workspace | Usually host process | Host tools, plus configured executable | Add external HTTPS tunnel/proxy for ChatGPT | [VS Code extension](../installation/vscode-extension.md) |
| Source checkout / `pipx` | Python development, customization, or package-based installs | Host virtualenv or VM | Python package plus host tools | Add HTTPS proxy/tunnel | [Python install](../installation/python.md) |
| Stdio mode | Local MCP clients that spawn tools directly | Client process boundary | Host tools | Not usable by ChatGPT web/app | [Stdio mode](../installation/stdio.md) |

## Client connection matrix

| Interface | Requires public HTTPS | Uses `/mcp` | Requires OAuth | Typical runtime |
|---|---:|---:|---:|---|
| Unified LSM web workspace | Yes for remote access; local proxy also possible | Internally | LSM login | Controller plus separate web stack |
| Gemini Spark / Custom Apps | Yes | Yes | Yes for public use | Any HTTP Controller |
| ChatGPT custom MCP connector | Yes | Yes | Yes for public use | Docker, VS Code extension, binary, or Python |
| Generic local MCP client over stdio | No | No | No | `local-shell-mcp --mode stdio` |
| Generic HTTP MCP client | Usually no for localhost; yes across networks | Yes | Recommended outside localhost | Any HTTP runtime |
| VS Code extension helper flow | Only if ChatGPT must connect | Yes when copying ChatGPT URL | Recommended for ChatGPT | VS Code-launched runtime |

See the [unified web workspace](../getting-started/web-workspace.md), [Gemini Spark](../getting-started/gemini-spark.md), [ChatGPT connector](../getting-started/chatgpt-connector.md), [generic MCP clients](../clients/generic-mcp.md), and [network connectivity](../clients/connectivity.md).

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
| Are compilers and browsers preinstalled? | No; install what the task needs | Only if installed on host | Only if installed on host |
| Is it easy to reset? | Remove/recreate container and workspace volume | Depends on workspace | Depends on host/VM |
| Is it appropriate for arbitrary package installs? | Yes, if disposable | Riskier on host | Riskier unless inside VM |

## Recommended selection

Use the **single-file standalone binary** first: download the appropriate release executable, grant execute permission when necessary, and start it under a restricted service account with a dedicated workspace. No Docker, Python runtime, or source checkout is required for the core Controller. See the [binary install guide](../installation/binary.md).

Use the **VS Code extension** when the workflow starts from an editor and you want a local launcher. It is still a runtime. Remote web clients need a reachable HTTPS proxy or tunnel.

Use a **source checkout** when developing or debugging local-shell-mcp itself, or when customizing code. Install it into a Python virtual environment; see the [Python/source guide](../installation/python.md).

Use **`pipx`** when you want an isolated packaged Python install without maintaining a checkout. For untrusted or disposable workloads, **Docker Compose** remains a useful alternative; direct public-server exposure or a standard reverse proxy is preferred over Cloudflare Tunnel for high-volume file uploads.

Use **stdio mode** only for local MCP clients that can spawn the server process. It is not a public deployment and it is not usable by ChatGPT web/app directly.

## Public endpoint rule

For external HTTP MCP clients such as Gemini and ChatGPT, the MCP endpoint is:

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

- [Unified web workspace](../getting-started/web-workspace.md)
- [Gemini Spark / Custom Apps](../getting-started/gemini-spark.md)
- [ChatGPT connector](../getting-started/chatgpt-connector.md)
- [Generic MCP clients](../clients/generic-mcp.md)
- [Public HTTPS exposure](../clients/connectivity.md)
