import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import test from "node:test";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const launcher = join(root, "bin", "local-shell-mcp.js");

test("launcher passes arguments to an explicitly configured executable", () => {
  const result = spawnSync(process.execPath, [launcher, "--version"], {
    encoding: "utf8",
    env: { ...process.env, LOCAL_SHELL_MCP_BINARY: process.execPath }
  });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, new RegExp(`^v${process.versions.node.replaceAll(".", "\\.")}`));
});
