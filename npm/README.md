# local-shell-mcp npm launcher

This is the official npm launcher for [local-shell-mcp](https://github.com/fwerkor/local-shell-mcp).
It downloads the matching release-attached standalone executable from the project's GitHub Release,
verifies it against `SHA256SUMS`, caches it locally, and then passes through all command-line arguments.

```bash
npx local-shell-mcp --help
```

A global install also exposes the short `lsm` command:

```bash
npm install -g local-shell-mcp
lsm --help
```

The npm package is a launcher, not a separate JavaScript implementation of the server.
