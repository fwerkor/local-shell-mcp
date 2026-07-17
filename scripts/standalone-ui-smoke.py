from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import websockets


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _read_log(path: Path) -> str:
    with contextlib.suppress(OSError):
        return path.read_text(encoding="utf-8", errors="replace")
    return ""


def _logs(stdout_path: Path, stderr_path: Path) -> tuple[str, str]:
    return _read_log(stdout_path), _read_log(stderr_path)


def wait_for_http(
    port: int,
    process: subprocess.Popen[bytes],
    stdout_path: Path,
    stderr_path: Path,
    timeout_s: float = 45,
) -> None:
    deadline = time.monotonic() + timeout_s
    checks = {
        "/healthz": None,
        "/ui": b"local-shell-mcp",
        "/ui/assets/web.js": None,
        "/ui/assets/web.css": None,
    }
    pending = dict(checks)
    while pending and time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = _logs(stdout_path, stderr_path)
            raise RuntimeError(
                f"Server exited with {process.returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}"
            )
        for path, expected in list(pending.items()):
            try:
                with urllib.request.urlopen(  # noqa: S310
                    f"http://127.0.0.1:{port}{path}", timeout=1
                ) as response:
                    body = response.read()
                    if response.status == 200 and (expected is None or expected in body):
                        pending.pop(path)
            except (urllib.error.URLError, TimeoutError):
                pass
        if pending:
            time.sleep(0.1)
    if pending:
        raise TimeoutError(f"HTTP UI checks did not become ready: {sorted(pending)}")


async def receive_render(websocket, *, minimum_bytes: int, timeout_s: float = 20) -> bytes:  # noqa: ANN001
    deadline = asyncio.get_running_loop().time() + timeout_s
    output = bytearray()
    while len(output) < minimum_bytes:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            break
        try:
            message = await asyncio.wait_for(websocket.recv(), timeout=remaining)
        except TimeoutError:
            break
        output.extend(message.encode("utf-8", errors="replace") if isinstance(message, str) else message)
    rendered = bytes(output)
    if b"Unable to start the TUI" in rendered or b"OpenTUI runtime not found" in rendered:
        raise RuntimeError(f"Embedded TUI failed to start: {rendered[-1000:]!r}")
    if len(rendered) < minimum_bytes:
        raise TimeoutError(
            f"TUI rendered only {len(rendered)} bytes; tail={rendered[-1000:]!r}"
        )
    if b"\x1b" not in rendered:
        raise AssertionError("TUI output contains no ANSI control sequence")
    return rendered


async def exercise_websocket(port: int) -> None:
    uri = f"ws://127.0.0.1:{port}/ui/ws?cols=120&rows=36"
    async with websockets.connect(
        uri,
        subprotocols=["lsm-ui"],
        max_size=8 * 1024 * 1024,
    ) as websocket:
        await receive_render(websocket, minimum_bytes=512)
        await websocket.send('{"type":"resize","cols":70,"rows":28}')
        await receive_render(websocket, minimum_bytes=128)
        await websocket.send(b"\x1bOR")
        await receive_render(websocket, minimum_bytes=128)


def _stop_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(  # noqa: S603, S607
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=8)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Smoke-test WebUI assets and its PTY-backed OpenTUI runtime"
    )
    parser.add_argument("--server", required=True, type=Path)
    parser.add_argument(
        "--use-environment-tui",
        action="store_true",
        help="Keep LOCAL_SHELL_MCP_UI_TUI_COMMAND instead of requiring an embedded runtime",
    )
    args = parser.parse_args()
    server = args.server.resolve()
    if not server.is_file():
        raise FileNotFoundError(server)

    port = free_port()
    with tempfile.TemporaryDirectory(prefix="local-shell-mcp-standalone-ui-") as temp_dir:
        root = Path(temp_dir)
        workspace = root / "workspace"
        workspace.mkdir()
        stdout_path = root / "server.stdout.log"
        stderr_path = root / "server.stderr.log"
        env = os.environ.copy()
        env.update(
            {
                "LOCAL_SHELL_MCP_HOST": "127.0.0.1",
                "LOCAL_SHELL_MCP_PORT": str(port),
                "LOCAL_SHELL_MCP_WORKSPACE_ROOT": str(workspace),
                "LOCAL_SHELL_MCP_STATE_DIR": str(root / "state"),
                "LOCAL_SHELL_MCP_MODE": "mcp",
                "LOCAL_SHELL_MCP_AUTH_MODE": "none",
                "LOCAL_SHELL_MCP_REMOTE_ENABLED": "false",
                "LOCAL_SHELL_MCP_UI_ENABLED": "true",
                "LOCAL_SHELL_MCP_UI_WALLPAPER": "none",
            }
        )
        if not args.use_environment_tui:
            env.pop("LOCAL_SHELL_MCP_UI_TUI_COMMAND", None)

        failure: BaseException | None = None
        with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
            process = subprocess.Popen(  # noqa: S603
                [str(server), "--mode", "mcp", "--no-remote"],
                cwd=server.parent,
                env=env,
                stdout=stdout_file,
                stderr=stderr_file,
            )
            try:
                wait_for_http(port, process, stdout_path, stderr_path)
                asyncio.run(exercise_websocket(port))
            except BaseException as exc:
                failure = exc
            finally:
                _stop_process_tree(process)

        stdout, stderr = _logs(stdout_path, stderr_path)
        if failure is not None:
            raise RuntimeError(
                f"Standalone UI smoke failed: {failure}\nstdout:\n{stdout}\nstderr:\n{stderr}"
            ) from failure

    mode = "configured" if args.use_environment_tui else "embedded"
    print(f"Standalone UI smoke passed with {mode} TUI: {server.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
