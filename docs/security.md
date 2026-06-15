# Security

Use OAuth for public deployments. Keep `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN` and `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET` strong and private.

By default, path operations are workspace-scoped and sensitive path fragments are blocked. Full-container mode disables built-in workspace and path restrictions and is intended for disposable containers or VMs.

Generated file download links are public bearer URLs. They rely on high-entropy tokens, TTLs, optional download-count limits, optional size limits, and revocation.
