# Keamanan

Untuk deployment publik, aktifkan OAuth dan jangan mount Docker socket, root host, atau kredensial jangka panjang.

Mandatory rules:

1. Keep OAuth enabled for public deployments.
2. Do not mount `/var/run/docker.sock`.
3. Do not mount the host root filesystem.
4. Do not expose unauthenticated MCP tools on the public internet.
5. Treat file links and credential volumes as sensitive.
6. Use disposable containers or VMs when granting broad authority.
