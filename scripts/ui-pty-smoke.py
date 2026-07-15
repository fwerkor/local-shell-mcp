from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parents[1]
TUI_NAME = "local-shell-mcp-tui.exe" if os.name == "nt" else "local-shell-mcp-tui"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_health(port: int, process: subprocess.Popen[str], timeout_s: float = 30) -> None:
    deadline = time.monotonic() + timeout_s
    url = f"http://127.0.0.1:{port}/healthz"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise RuntimeError(
                f"PTY smoke server exited with {process.returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}"
            )
        try:
            with urllib.request.urlopen(url, timeout=1) as response:  # noqa: S310
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.1)
    raise TimeoutError(f"Server did not become healthy within {timeout_s}s: {url}")


async def receive_activity(
    websocket,  # noqa: ANN001
    *,
    label: str,
    minimum_bytes: int = 128,
    timeout_s: float = 15,
) -> bytes:
    deadline = asyncio.get_running_loop().time() + timeout_s
    output = bytearray()
    while len(output) < minimum_bytes:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError(
                f"PTY produced only {len(output)} bytes during {label}; "
                f"tail={bytes(output[-500:])!r}"
            )
        try:
            message = await asyncio.wait_for(websocket.recv(), timeout=remaining)
        except TimeoutError as exc:
            raise TimeoutError(
                f"PTY produced only {len(output)} bytes during {label}; "
                f"tail={bytes(output[-500:])!r}"
            ) from exc
        if isinstance(message, str):
            output.extend(message.encode("utf-8", errors="replace"))
        else:
            output.extend(message)
    if b"Unable to start the TUI" in output or b"platform unsupported" in output:
        raise RuntimeError(f"OpenTUI startup failed during {label}: {bytes(output)!r}")
    return bytes(output)


async def drain_websocket(websocket) -> None:  # noqa: ANN001
    while True:
        try:
            await asyncio.wait_for(websocket.recv(), timeout=0.1)
        except TimeoutError:
            return


async def exercise_websocket(port: int) -> None:
    uri = f"ws://127.0.0.1:{port}/ui/ws?cols=120&rows=36"
    async with websockets.connect(uri, subprotocols=["lsm-ui"], max_size=8 * 1024 * 1024) as websocket:
        initial = await receive_activity(websocket, label="initial render", minimum_bytes=512)
        if b"\x1b" not in initial:
            raise AssertionError("Initial OpenTUI output did not contain ANSI control sequences")

        await drain_websocket(websocket)
        await websocket.send(json.dumps({"type": "resize", "cols": 58, "rows": 28}))
        resized = await receive_activity(websocket, label="live resize", minimum_bytes=256)
        if b"\x1b" not in resized:
            raise AssertionError("Resized OpenTUI output did not contain ANSI control sequences")

        await drain_websocket(websocket)
        await websocket.send(b"\x1bOR")
        switched = await receive_activity(websocket, label="screen switch", minimum_bytes=256)
        if b"\x1b" not in switched:
            raise AssertionError("Screen-switch output did not contain ANSI control sequences")


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the native OpenTUI PTY WebSocket bridge")
    parser.add_argument(
        "--tui",
        type=Path,
        default=ROOT / "ui" / "dist" / TUI_NAME,
        help="Path to the platform-native OpenTUI sidecar",
    )
    args = parser.parse_args()
    tui_path = args.tui.resolve()
    if not tui_path.is_file():
        raise FileNotFoundError(f"Native OpenTUI sidecar not found: {tui_path}")

    port = free_port()
    with tempfile.TemporaryDirectory(prefix="local-shell-mcp-ui-pty-") as temp_dir:
        root = Path(temp_dir)
        workspace = root / "workspace"
        workspace.mkdir()
        env = os.environ.copy()
        env.update(
            {
                "PYTHONPATH": str(ROOT / "src"),
                "LOCAL_SHELL_MCP_HOST": "127.0.0.1",
                "LOCAL_SHELL_MCP_PORT": str(port),
                "LOCAL_SHELL_MCP_WORKSPACE_ROOT": str(workspace),
                "LOCAL_SHELL_MCP_STATE_DIR": str(root / "state"),
                "LOCAL_SHELL_MCP_MODE": "mcp",
                "LOCAL_SHELL_MCP_AUTH_MODE": "none",
                "LOCAL_SHELL_MCP_REMOTE_ENABLED": "false",
                "LOCAL_SHELL_MCP_UI_WALLPAPER": "none",
                "LOCAL_SHELL_MCP_UI_TUI_COMMAND": str(tui_path),
            }
        )
        if os.getenv("LOCAL_SHELL_MCP_COVERAGE") == "1":
            env["COVERAGE_PROCESS_START"] = str(ROOT / "pyproject.toml")
            env["COVERAGE_FILE"] = str(ROOT / ".coverage")
            env["PYTHONPATH"] = os.pathsep.join(
                item
                for item in (str(ROOT), str(ROOT / "src"), env.get("PYTHONPATH", ""))
                if item
            )
        process = subprocess.Popen(  # noqa: S603
            [sys.executable, "-m", "local_shell_mcp.main", "--mode", "mcp", "--no-remote"],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        failure: BaseException | None = None
        try:
            wait_for_health(port, process)
            asyncio.run(exercise_websocket(port))
        except BaseException as exc:
            failure = exc
        finally:
            process.terminate()
            try:
                stdout, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate(timeout=5)
        if failure is not None:
            raise RuntimeError(
                f"PTY smoke failed: {failure}\nserver stdout:\n{stdout}\nserver stderr:\n{stderr}"
            ) from failure

    print(f"Human UI PTY smoke test passed: {sys.platform} / {tui_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
