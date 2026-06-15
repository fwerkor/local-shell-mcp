# Sécurité

Pour une exposition publique, activez OAuth et ne montez pas le Docker socket, la racine de l’hôte ni des identifiants longue durée.

Mandatory rules:

1. Keep OAuth enabled for public deployments.
2. Do not mount `/var/run/docker.sock`.
3. Do not mount the host root filesystem.
4. Do not expose unauthenticated MCP tools on the public internet.
5. Treat file links and credential volumes as sensitive.
6. Use disposable containers or VMs when granting broad authority.
