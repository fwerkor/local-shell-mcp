#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import NoReturn

import httpx

ROOT = Path(__file__).resolve().parents[1]
OAUTH_PIN = "ci-local-shell-mcp-pin"
OAUTH_SECRET = "ci-local-shell-mcp-secret-0123456789abcdef0123456789abcdef"


def unused_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def fail(message: str) -> NoReturn:
    raise SystemExit(message)


def server_command(mode: str) -> list[str]:
    return [
        sys.executable,
        "-c",
        "from local_shell_mcp.main import main; main(['--mode', " + repr(mode) + "])",
    ]


async def wait_for_health(base_url: str, process: subprocess.Popen[str], timeout_s: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_s
    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=2.0) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                fail(f"server exited before becoming healthy with code {process.returncode}")
            try:
                response = await client.get(f"{base_url}/healthz")
                if response.status_code == 200 and response.json().get("ok") is True:
                    return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
            await asyncio.sleep(0.25)
    fail(f"server did not become healthy within {timeout_s:.0f}s: {last_error!r}")


async def run_http_smoke(base_url: str) -> None:
    async with httpx.AsyncClient(timeout=20.0) as client:
        version = await client.get(f"{base_url}/version")
        version.raise_for_status()
        if not version.json().get("version"):
            fail("/version did not return a project version")

        write = await client.post(
            f"{base_url}/tools/write_file",
            json={"path": "ci-smoke.txt", "content": "hello from ci\n", "overwrite": True},
        )
        write.raise_for_status()

        read = await client.post(f"{base_url}/tools/read_file", json={"path": "ci-smoke.txt"})
        read.raise_for_status()
        if read.json().get("content") != "hello from ci\n":
            fail("read_file did not return the content written by write_file")

        shell = await client.post(
            f"{base_url}/tools/run_shell",
            json={"command": "echo ci-shell-ok", "cwd": ".", "timeout_s": 10},
        )
        shell.raise_for_status()
        if "ci-shell-ok" not in shell.json().get("stdout", ""):
            fail("run_shell did not echo expected output")

        listing = await client.post(f"{base_url}/tools/list_files", json={"path": "."})
        listing.raise_for_status()
        names = {item.get("path") for item in listing.json()}
        if "ci-smoke.txt" not in names:
            fail("list_files did not include ci-smoke.txt")


async def run_mcp_probe(base_url: str, auth: str) -> None:
    command = [sys.executable, str(ROOT / "scripts" / "probe-mcp.py"), base_url]
    if auth == "oauth":
        command.extend(["--pin", OAUTH_PIN])
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=60, check=False)
    print(completed.stdout, end="")
    print(completed.stderr, end="", file=sys.stderr)
    if completed.returncode != 0:
        fail(f"MCP probe failed with exit code {completed.returncode}")


def start_server(mode: str, auth: str, workspace: Path, port: int) -> subprocess.Popen[str]:
    base_url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.update(
        {
            "LOCAL_SHELL_MCP_MODE": mode,
            "LOCAL_SHELL_MCP_HOST": "127.0.0.1",
            "LOCAL_SHELL_MCP_PORT": str(port),
            "LOCAL_SHELL_MCP_WORKSPACE_ROOT": str(workspace),
            "LOCAL_SHELL_MCP_AUTH_MODE": auth,
            "LOCAL_SHELL_MCP_REMOTE_ENABLED": "true",
            "LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN": OAUTH_PIN,
            "LOCAL_SHELL_MCP_OAUTH_JWT_SECRET": OAUTH_SECRET,
            "LOCAL_SHELL_MCP_PUBLIC_BASE_URL": base_url if auth == "oauth" else "",
        }
    )
    return subprocess.Popen(
        server_command(mode),
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def stop_server(process: subprocess.Popen[str]) -> str:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
    output = process.stdout.read() if process.stdout is not None else ""
    return output


async def run(mode: str, auth: str) -> None:
    port = unused_port()
    base_url = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="local-shell-mcp-ci-") as workspace_str:
        workspace = Path(workspace_str)
        process = start_server(mode, auth, workspace, port)
        output = ""
        try:
            await wait_for_health(base_url, process)
            if mode == "http":
                await run_http_smoke(base_url)
            else:
                await run_mcp_probe(base_url, auth)
        finally:
            output = stop_server(process)
            if output:
                print("--- local-shell-mcp server log ---")
                print(output, end="")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run local-shell-mcp CI endpoint smoke tests.")
    parser.add_argument("--mode", choices=["http", "mcp"], required=True)
    parser.add_argument("--auth", choices=["none", "oauth"], default="none")
    args = parser.parse_args()
    asyncio.run(run(args.mode, args.auth))


if __name__ == "__main__":
    main()
