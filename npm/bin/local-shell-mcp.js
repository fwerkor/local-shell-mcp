#!/usr/bin/env node

import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import { chmod, mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { homedir, tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const packageJson = JSON.parse(await readFile(join(packageRoot, "package.json"), "utf8"));

function platformAsset() {
  const key = `${process.platform}/${process.arch}`;
  const assets = {
    "linux/x64": "local-shell-mcp-linux-x86_64",
    "linux/arm64": "local-shell-mcp-linux-aarch64",
    "darwin/x64": "local-shell-mcp-macos-x86_64",
    "darwin/arm64": "local-shell-mcp-macos-aarch64",
    "win32/x64": "local-shell-mcp-windows-x86_64.exe"
  };
  const asset = assets[key];
  if (!asset) {
    throw new Error(
      `No local-shell-mcp standalone executable is published for ${key}. ` +
        "Use the Python, Docker, or source installation instead."
    );
  }
  return asset;
}

function cacheRoot() {
  if (process.env.LOCAL_SHELL_MCP_NPM_CACHE) return process.env.LOCAL_SHELL_MCP_NPM_CACHE;
  if (process.platform === "win32" && process.env.LOCALAPPDATA) {
    return join(process.env.LOCALAPPDATA, "local-shell-mcp", "npm");
  }
  if (process.platform === "darwin") {
    return join(homedir(), "Library", "Caches", "local-shell-mcp", "npm");
  }
  return join(process.env.XDG_CACHE_HOME || join(homedir(), ".cache"), "local-shell-mcp", "npm");
}

async function fetchBytes(url) {
  const response = await fetch(url, {
    headers: { "User-Agent": `local-shell-mcp-npm/${packageJson.version}` },
    redirect: "follow"
  });
  if (!response.ok) throw new Error(`HTTP ${response.status} while downloading ${url}`);
  return Buffer.from(await response.arrayBuffer());
}

function checksumFor(checksumText, asset) {
  for (const line of checksumText.split(/\r?\n/)) {
    const match = line.match(/^([0-9a-fA-F]{64})\s+\*?(.+)$/);
    if (match && match[2] === asset) return match[1].toLowerCase();
  }
  throw new Error(`SHA256SUMS does not contain ${asset}`);
}

async function ensureBinary() {
  if (process.env.LOCAL_SHELL_MCP_BINARY) return process.env.LOCAL_SHELL_MCP_BINARY;

  const version = packageJson.version;
  const releaseTag = packageJson.localShellMcp?.releaseTag;
  if (!releaseTag || version.includes("dev")) {
    throw new Error("This development npm package is not bound to a published local-shell-mcp release.");
  }

  const asset = platformAsset();
  const destination = join(cacheRoot(), version, asset);
  const marker = `${destination}.sha256`;
  try {
    const [binary, recorded] = await Promise.all([readFile(destination), readFile(marker, "utf8")]);
    const actual = createHash("sha256").update(binary).digest("hex");
    if (actual === recorded.trim()) return destination;
  } catch {
    // Missing or stale cache entries are replaced below.
  }

  const base = `https://github.com/fwerkor/local-shell-mcp/releases/download/${encodeURIComponent(releaseTag)}`;
  const [binary, checksumBytes] = await Promise.all([
    fetchBytes(`${base}/${asset}`),
    fetchBytes(`${base}/SHA256SUMS`)
  ]);
  const expected = checksumFor(checksumBytes.toString("utf8"), asset);
  const actual = createHash("sha256").update(binary).digest("hex");
  if (actual !== expected) {
    throw new Error(`Checksum mismatch for ${asset}: expected ${expected}, got ${actual}`);
  }

  await mkdir(dirname(destination), { recursive: true });
  const temporary = join(tmpdir(), `local-shell-mcp-${process.pid}-${Date.now()}`);
  try {
    await writeFile(temporary, binary, { mode: 0o755 });
    if (process.platform !== "win32") await chmod(temporary, 0o755);
    await rm(destination, { force: true });
    await rename(temporary, destination);
    await writeFile(marker, `${expected}\n`, "utf8");
  } finally {
    await rm(temporary, { force: true }).catch(() => {});
  }
  return destination;
}

async function main() {
  const binary = await ensureBinary();
  const child = spawn(binary, process.argv.slice(2), { stdio: "inherit" });
  child.once("error", (error) => {
    console.error(`local-shell-mcp: failed to start ${binary}: ${error.message}`);
    process.exitCode = 1;
  });
  child.once("exit", (code, signal) => {
    if (signal) {
      process.kill(process.pid, signal);
      return;
    }
    process.exitCode = code ?? 1;
  });
}

main().catch((error) => {
  console.error(`local-shell-mcp: ${error.message}`);
  process.exitCode = 1;
});
