#!/usr/bin/env node
const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const extensionRoot = path.resolve(__dirname, "..");
const repoRoot = path.resolve(extensionRoot, "..");
const pkg = require(path.join(extensionRoot, "package.json"));
const out = path.join(repoRoot, "dist", `local-shell-mcp-vscode-${pkg.version}.vsix`);
const vsce = process.platform === "win32" ? "vsce.cmd" : "vsce";

fs.mkdirSync(path.dirname(out), { recursive: true });
execFileSync(vsce, ["package", "--no-dependencies", "--out", out], {
  cwd: extensionRoot,
  stdio: "inherit",
});
