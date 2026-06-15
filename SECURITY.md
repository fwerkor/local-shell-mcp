# Security Policy

`local-shell-mcp` intentionally exposes powerful shell, filesystem, Git, browser, file-link, and remote-machine control tools to MCP clients. Treat any connected model or client as able to control the configured workspace, container, or VM.

## Supported versions

Security fixes target the latest release and the `main` branch. Users should upgrade promptly because the project evolves quickly and older releases may have weaker safeguards.

## Reporting a vulnerability

Please report suspected vulnerabilities privately by opening a GitHub security advisory for this repository, or by contacting the maintainer through the repository owner's public GitHub profile if advisories are unavailable.

Include:

- A clear description of the vulnerability.
- A minimal reproduction or attack path.
- Affected version or commit.
- Deployment mode: Docker, binary, VS Code extension, remote worker, or custom setup.
- Whether the service was public, authenticated, or running with full-container mode.

Do not publish exploit details until a fix or mitigation is available.

## Deployment rules

For public deployments:

1. Keep OAuth enabled.
2. Use HTTPS.
3. Use a long random `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN`.
4. Use a long random `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET`.
5. Do not mount `/var/run/docker.sock`.
6. Do not mount the host root filesystem.
7. Do not expose `LOCAL_SHELL_MCP_AUTH_MODE=none` beyond loopback.
8. Run in a disposable container or VM.
9. Treat `/workspace/.local-shell-mcp`, credential volumes, SSH keys, Git tokens, and generated file-link tokens as sensitive.

## Full-container mode

`LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true` intentionally relaxes workspace restrictions and disables important denylists. Use it only inside disposable containers or VMs that do not expose host-control primitives.

## Credentials

Avoid placing long-lived credentials in environment variables visible to spawned shell processes. Prefer deploy keys, short-lived GitHub App tokens, isolated test accounts, or per-repository credentials. Review audit logs and run secret scans before pushing changes.

## Remote workers

Remote workers can run commands and manipulate files on joined machines. Use one-time invites, revoke unused workers, and avoid attaching machines that contain unrelated secrets or production data.

## File links

Tokenized file links are bearer URLs. Use TTL and download limits for sensitive files, revoke links when they are no longer needed, and avoid exposing private artifacts unnecessarily.
