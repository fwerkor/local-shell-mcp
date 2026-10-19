from __future__ import annotations

import asyncio
import base64
import io
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from starlette.applications import Starlette

import local_shell_mcp.desktop_stream as stream_module
import local_shell_mcp.gui as gui
import local_shell_mcp.human_ui as human_ui
import local_shell_mcp.remote_worker_routes as worker_routes
from local_shell_mcp.settings import get_settings


@pytest.fixture(autouse=True)
def configure(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_UI_ENABLED", "true")
    get_settings.cache_clear()
    stream_module.STREAMS.clear()
    yield
    stream_module.STREAMS.clear()
    get_settings.cache_clear()


def test_image_is_resized_and_bounded(tmp_path):
    path = tmp_path / "frame.png"
    Image.new("RGB", (2560, 1440), "green").save(path)
    data = stream_module.compress_frame(path)
    assert data.startswith(b"\xff\xd8\xff")
    assert len(data) < stream_module.MAX_FRAME_BYTES
    with Image.open(io.BytesIO(data)) as image:
        assert image.width <= stream_module.FRAME_WIDTH
        assert image.height <= stream_module.FRAME_HEIGHT


def test_worker_frames_deduplicate_and_keep_only_newest():
    stream = stream_module.DesktopStream("node", "win")
    stream_module.STREAMS[stream.key] = stream
    metadata = {"type": "frame", "observation_id": "o1", "bounds": {"x": 0, "y": 0, "width": 10, "height": 10}}
    frame = base64.b64encode(b"\xff\xd8\xfftest").decode()
    stream_module.worker_frame(stream.key, stream.secret, "node", {"frame": metadata, "image": frame})
    assert stream.frames.qsize() == 1
    stream_module.worker_frame(stream.key, stream.secret, "node", {"frame": {**metadata, "observation_id": "o2"}})
    assert stream.frames.qsize() == 1
    newest, image = stream.frames.get_nowait()
    assert newest["observation_id"] == "o2"
    assert image == b"\xff\xd8\xfftest"


def test_worker_stream_rejects_other_workers_and_invalid_credentials():
    stream = stream_module.DesktopStream("owner", "win")
    stream_module.STREAMS[stream.key] = stream
    for secret, machine in [(stream.secret, "attacker"), ("wrong", "owner")]:
        with pytest.raises(PermissionError):
            stream_module.worker_frame(stream.key, secret, machine, {})
    with pytest.raises(ValueError):
        stream_module.worker_frame(stream.key, stream.secret, "owner", {"frame": {"type": "frame", "bounds": {}}})
    with pytest.raises(ValueError):
        stream_module.worker_frame(stream.key, stream.secret, "owner", {"frame": {"type": "frame", "observation_id": "o", "bounds": {}}, "image": "%%%"})
    stream.last_contact = time.monotonic() - stream_module.STREAM_IDLE_S - 1
    with pytest.raises(PermissionError):
        stream_module.worker_frame(stream.key, stream.secret, "owner", {})
    assert stream.key not in stream_module.STREAMS


def test_worker_stream_returns_action_batches_and_forced_keyframes():
    stream = stream_module.DesktopStream("node", "win")
    stream_module.STREAMS[stream.key] = stream
    action = {"observation_id": "obs", "bounds": {}, "action": {"type": "key", "keys": ["ENTER"]}}
    stream.actions.put_nowait(action)
    stream.force_frame = True
    result = stream_module.worker_frame(stream.key, stream.secret, "node", {})
    assert result == {"actions": [action], "refresh": True}
    assert stream_module.worker_frame(stream.key, stream.secret, "node", {}) == {"actions": [], "refresh": False}
    stream_module.worker_frame(stream.key, stream.secret, "node", {"errors": ["stale"]})
    assert stream.frames.get_nowait()[0]["type"] == "error"


def test_controller_worker_stream_post_auth(monkeypatch):
    stream = stream_module.DesktopStream("node", "win")
    stream_module.STREAMS[stream.key] = stream
    monkeypatch.setattr(worker_routes.remote, "remote_manager", lambda: SimpleNamespace(
        _worker_by_token=lambda token: SimpleNamespace(name="node") if token == "valid" else (_ for _ in ()).throw(PermissionError("unauthorized"))
    ))
    with TestClient(Starlette(routes=worker_routes.remote_routes())) as client:
        uri = f"/remote/gui/stream/{stream.key}"
        assert client.post(uri, json={}, headers={"Authorization": "Bearer wrong", "x-lsm-desktop-secret": stream.secret}).status_code == 403
        assert client.post(uri, json={}, headers={"Authorization": "Bearer valid", "x-lsm-desktop-secret": "bad"}).status_code == 403
        response = client.post(uri, json={}, headers={"Authorization": "Bearer valid", "x-lsm-desktop-secret": stream.secret})
        assert response.status_code == 200
        assert response.json() == {"actions": [], "refresh": False}


class FakeManager:
    def __init__(self, root: Path):
        self.root = root
        self.captured = 0
        self.discarded = []
        self.actions = []

    async def list_windows(self):
        return {"capabilities": {"capture_requires_focus": False}}

    async def frame(self, window_id):
        self.captured += 1
        path = self.root / f"gui-frame-{self.captured}.png"
        Image.new("RGB", (200, 100), "blue").save(path)
        return {"window": {"bounds": {"x": 100, "y": 50, "width": 200, "height": 100}},
                "observation_id": f"obs-{self.captured}", "observation_ttl_s": 25,
                "capabilities": {"coordinate_input": True}, "screenshot_path": str(path)}

    async def discard_frame_observation(self, window_id, observation_id):
        self.discarded.append(observation_id)

    async def human_act(self, window_id, observation_id, bounds, actions):
        self.actions.append((window_id, observation_id, bounds, actions))


def test_local_websocket_sends_image_and_accepts_input(tmp_path, monkeypatch):
    manager = FakeManager(tmp_path)
    monkeypatch.setattr(stream_module, "temp_dir", lambda: tmp_path)
    monkeypatch.setattr(gui, "get_gui_manager", lambda: manager)
    with (
        TestClient(Starlette(routes=human_ui.ui_routes())) as client,
        client.websocket_connect("/ui/ws/desktop?machine=local&window_id=win", subprotocols=["lsm-ui"]) as ws,
    ):
        assert ws.receive_json() == {"type": "ready"}
        frame = ws.receive_json()
        assert frame["type"] == "frame", frame
        assert frame["image"] is True
        assert frame["bounds"] == {"x": 100, "y": 50, "width": 200, "height": 100}
        assert ws.receive_bytes().startswith(b"\xff\xd8\xff")
        ws.send_json({"type": "action", "observation_id": frame["observation_id"], "bounds": frame["bounds"], "action": {"type": "click", "x": 10, "y": 20}})
        ws.send_json({"type": "refresh"})
        # Receive frames until the input task runs, without coupling the test to scheduling.
        for _ in range(4):
            next_frame = ws.receive_json()
            if next_frame.get("image"):
                ws.receive_bytes()
            if manager.actions:
                break
        assert manager.actions[0][0:2] == ("win", frame["observation_id"])
    assert manager.discarded


def test_remote_websocket_uses_only_start_stop_rpc(monkeypatch):
    calls = []

    async def fake_remote_call(machine, tool, args, timeout_s=None):
        calls.append((machine, tool))
        if tool == "gui_stream_start":
            return {"started": True}
        assert tool == "gui_stream_stop"
        return {"stopped": True}

    monkeypatch.setattr(human_ui, "_remote_call", fake_remote_call)
    with (
        TestClient(Starlette(routes=human_ui.ui_routes())) as client,
        client.websocket_connect("/ui/ws/desktop?machine=node&window_id=win") as ws,
    ):
        assert ws.receive_json() == {"type": "ready"}
        stream = next(iter(stream_module.STREAMS.values()))
        metadata = {"type": "frame", "observation_id": "obs", "ttl_s": 20,
                    "bounds": {"x": 0, "y": 0, "width": 20, "height": 10}, "coordinate_input": True}
        stream_module.worker_frame(stream.key, stream.secret, "node", {"frame": metadata, "image": base64.b64encode(b"\xff\xd8\xffdata").decode()})
        assert ws.receive_json()["type"] == "frame"
        assert ws.receive_bytes() == b"\xff\xd8\xffdata"
        ws.send_json({"type": "action", "observation_id": "obs", "bounds": metadata["bounds"], "action": {"type": "click", "x": 5, "y": 5}})
        ws.send_json({"type": "refresh"})
    assert calls == [("node", "gui_stream_start"), ("node", "gui_stream_stop")]
    assert stream_module.STREAMS == {}

@pytest.mark.asyncio
async def test_capture_frame_cleanup_success_failure(tmp_path, monkeypatch):
    manager = FakeManager(tmp_path)
    monkeypatch.setattr(stream_module, "temp_dir", lambda: tmp_path)
    monkeypatch.setattr(stream_module, "release_temp_file_lease", lambda path: None)
    data, image = await stream_module.capture_frame(manager, "win")
    assert data["observation_id"] == "obs-1"
    assert image.startswith(b"\xff\xd8\xff")
    assert not (tmp_path / "gui-frame-1.png").exists()

    def broken(_path):
        raise ValueError("bad frame")

    monkeypatch.setattr(stream_module, "compress_frame", broken)
    with pytest.raises(ValueError, match="bad frame"):
        await stream_module.capture_frame(manager, "win")
    assert manager.discarded == ["obs-2"]
    assert not (tmp_path / "gui-frame-2.png").exists()


def test_post_frame_serialization_and_rejects_wrong_response(monkeypatch):
    import urllib.request

    requests = []

    class Response:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self, size):
            assert size == 16 * 1024
            return self.body

    def fake_open(request, timeout):
        requests.append(request)
        assert timeout == 30
        return Response(b'{"actions":[],"refresh":false}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_open)
    stream_module.configure_worker_stream("https://controller/", {"Authorization": "Bearer worker"})
    result = stream_module._post_frame("https://controller/remote/gui/stream/s", {"frame": {"type": "frame"}}, "secret")
    assert result == {"actions": [], "refresh": False}
    request = requests[0]
    assert request.get_header("Authorization") == "Bearer worker"
    assert request.get_header("X-lsm-desktop-secret") == "secret"
    assert json.loads(request.data) == {"frame": {"type": "frame"}}
    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: Response(b"[]"))
    with pytest.raises(ValueError, match="Invalid desktop controller response"):
        stream_module._post_frame("https://controller/remote/gui/stream/s", {}, "secret")


@pytest.mark.asyncio
async def test_worker_stream_success_deduplicates_and_runs_actions(monkeypatch):
    manager = FakeManager(Path("/tmp"))
    import local_shell_mcp.gui as native_gui

    monkeypatch.setattr(native_gui, "get_gui_manager", lambda: manager)
    monkeypatch.setattr(stream_module, "FRAME_INTERVAL_S", 0.005)
    stream_module.configure_worker_stream("https://controller", {"Authorization": "Bearer worker"})
    frame_count = 0
    requests = []

    async def capture(_manager, window_id):
        nonlocal frame_count
        frame_count += 1
        return {
            "window": {"bounds": {"x": 0, "y": 0, "width": 10, "height": 10}},
            "observation_id": f"obs-{frame_count}",
            "observation_ttl_s": 20,
            "capabilities": {"coordinate_input": True},
        }, b"\xff\xd8\xffsame"

    def post(url, payload, secret):
        requests.append(payload)
        if len(requests) == 1:
            return {"actions": [
                {"observation_id": "obs-1", "bounds": {}, "action": {"type": "click", "x": 1, "y": 1}},
                "invalid",
            ], "refresh": False}
        return {"actions": [], "refresh": False}

    monkeypatch.setattr(stream_module, "capture_frame", capture)
    monkeypatch.setattr(stream_module, "_post_frame", post)
    task = asyncio.create_task(stream_module._worker_stream_loop("stream", "secret", "win"))
    for _ in range(50):
        if len(requests) >= 3:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(requests) >= 3
    assert "image" in requests[0]
    assert "image" not in requests[1]
    assert manager.actions[0][1] == "obs-1"
    assert len(manager.discarded) >= 3


@pytest.mark.asyncio
async def test_worker_stream_action_errors_and_focus_sensitive_heartbeat(monkeypatch):
    import local_shell_mcp.gui as native_gui
    manager = FakeManager(Path("/tmp"))

    async def listing():
        return {"capabilities": {"capture_requires_focus": True}}

    async def rejected(*_):
        raise RuntimeError("stale")

    manager.list_windows = listing
    manager.human_act = rejected
    monkeypatch.setattr(native_gui, "get_gui_manager", lambda: manager)
    monkeypatch.setattr(stream_module, "FRAME_INTERVAL_S", 0.005)
    stream_module.configure_worker_stream("https://controller", {"Authorization": "Bearer worker"})
    counter = 0
    requests = []

    async def capture(*_):
        nonlocal counter
        counter += 1
        return {
            "window": {"bounds": {}}, "observation_id": f"o{counter}",
            "observation_ttl_s": 20, "capabilities": {"coordinate_input": True},
        }, b"\xff\xd8\xffsame"

    def post(url, payload, secret):
        requests.append(payload)
        if len(requests) == 2:
            return {"actions": [{"observation_id": "o1", "bounds": {}, "action": {"type": "click", "x": 1, "y": 1}}], "refresh": True}
        return {"actions": [], "refresh": False}

    monkeypatch.setattr(stream_module, "capture_frame", capture)
    monkeypatch.setattr(stream_module, "_post_frame", post)
    task = asyncio.create_task(stream_module._worker_stream_loop("stream-wayland", "secret", "win"))
    for _ in range(50):
        if len(requests) >= 5:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert counter == 2  # No ongoing intrusive Wayland window focus/capture.
    assert "errors" in requests[2]
    assert "image" not in requests[3]


@pytest.mark.asyncio
async def test_worker_stream_start_stop_replaces_existing_task(monkeypatch):
    import local_shell_mcp.gui as native_gui

    monkeypatch.setattr(native_gui, "get_gui_manager", lambda: FakeManager(Path("/tmp")))
    stream_module.configure_worker_stream("https://controller", {"Authorization": "Bearer worker"})
    with pytest.raises(ValueError):
        stream_module.start_worker_stream("", "secret", "win")

    async def sleeping_stream(*_):
        await asyncio.sleep(30)

    monkeypatch.setattr(stream_module, "_worker_stream_loop", sleeping_stream)
    stream_module.start_worker_stream("s", "secret", "win")
    first = stream_module._WORKER_STREAM_TASKS["s"]
    await asyncio.sleep(0)
    stream_module.start_worker_stream("s", "secret", "win")
    assert first.cancelled() is False
    await asyncio.sleep(0)
    assert first.cancelled() is True
    last = stream_module._WORKER_STREAM_TASKS["s"]
    stream_module.stop_worker_stream("s")
    await asyncio.sleep(0)
    assert last.cancelled() is True
    stream_module.stop_worker_stream("s")


@pytest.mark.asyncio
async def test_worker_stream_reports_network_failure_and_cleans_up(monkeypatch):
    import local_shell_mcp.gui as native_gui

    manager = FakeManager(Path("/tmp"))
    monkeypatch.setattr(native_gui, "get_gui_manager", lambda: manager)
    stream_module.configure_worker_stream("https://controller", {"Authorization": "Bearer worker"})
    requests = []

    async def capture(*_):
        return {"window": {"bounds": {}}, "observation_id": "o1", "observation_ttl_s": 20}, b"\xff\xd8\xffframe"

    def fail(url, payload, secret):
        requests.append(payload)
        if len(requests) == 1:
            raise RuntimeError("connection lost")
        raise RuntimeError("still offline")

    monkeypatch.setattr(stream_module, "capture_frame", capture)
    monkeypatch.setattr(stream_module, "_post_frame", fail)
    await stream_module._worker_stream_loop("dead", "secret", "win")
    assert requests[1] == {"errors": ["connection lost"]}
    assert manager.discarded == ["o1"]


def test_desktop_websocket_rejects_missing_target_and_unauthorized(monkeypatch):
    from starlette.websockets import WebSocketDisconnect

    with TestClient(Starlette(routes=human_ui.ui_routes())) as client:
        with (
            pytest.raises(WebSocketDisconnect) as missing,
            client.websocket_connect("/ui/ws/desktop?machine=local") as ws,
        ):
            ws.receive_json()
        assert missing.value.code == 4403
        monkeypatch.setattr(human_ui, "_websocket_principal", lambda ws: None)
        with (
            pytest.raises(WebSocketDisconnect) as denied,
            client.websocket_connect("/ui/ws/desktop?machine=local&window_id=win") as ws,
        ):
            ws.receive_json()
        assert denied.value.code == 4401


def test_desktop_stream_capacity_and_unknown_target(monkeypatch):
    from starlette.websockets import WebSocketDisconnect

    first = stream_module.DesktopStream("local", "win")
    stream_module.STREAMS[first.key] = first
    monkeypatch.setattr(human_ui, "get_settings", lambda: SimpleNamespace(
        ui_enabled=True, ui_path="ui", ui_terminal_max_sessions=1, disable_local=False, auth_mode="none",
    ))
    with TestClient(Starlette(routes=human_ui.ui_routes())) as client:
        with (
            pytest.raises(WebSocketDisconnect) as full,
            client.websocket_connect("/ui/ws/desktop?machine=local&window_id=win") as ws,
        ):
            ws.receive_json()
        assert full.value.code == 4429
    with pytest.raises(PermissionError):
        stream_module.worker_frame("missing", "secret", "node", {})


def test_stream_rejects_bad_jpeg_and_bounds_and_preserves_warning():
    stream = stream_module.DesktopStream("node", "win")
    stream_module.STREAMS[stream.key] = stream
    bounds = {"x": 0, "y": 0, "width": 1, "height": 1}
    meta = {"type": "frame", "observation_id": "obs", "bounds": bounds}
    with pytest.raises(ValueError, match="Invalid JPEG"):
        stream_module.worker_frame(stream.key, stream.secret, "node", {"frame": meta, "image": base64.b64encode(b"not-jpeg").decode()})
    with pytest.raises(ValueError, match="Invalid desktop frame"):
        stream_module.worker_frame(stream.key, stream.secret, "node", {"frame": meta, "image": "x" * (stream_module.MAX_FRAME_BYTES * 2 + 1)})
    with pytest.raises(ValueError, match="Invalid desktop frame metadata"):
        stream_module.worker_frame(stream.key, stream.secret, "node", {"frame": {"type": "error"}})
    stream_module.worker_frame(stream.key, stream.secret, "node", {"frame": meta, "errors": ["stale"]})
    result, image = stream.frames.get_nowait()
    assert result["warning"] == "stale"
    assert image == b""


def test_remote_endpoint_rejects_malformed_requests(monkeypatch):
    stream = stream_module.DesktopStream("node", "win")
    stream_module.STREAMS[stream.key] = stream
    monkeypatch.setattr(worker_routes.remote, "remote_manager", lambda: SimpleNamespace(
        _worker_by_token=lambda token: SimpleNamespace(name="node")
    ))
    with TestClient(Starlette(routes=worker_routes.remote_routes())) as client:
        uri = f"/remote/gui/stream/{stream.key}"
        headers = {"Authorization": "Bearer valid", "x-lsm-desktop-secret": stream.secret}
        assert client.post(uri, json=[], headers=headers).status_code == 400
        assert client.post(uri, json={"frame": {"type": "frame"}}, headers=headers).status_code == 400
        assert client.post(uri, json={"frame": {"type": "frame", "bounds": {}, "observation_id": "id"}, "image": "broken"}, headers=headers).status_code == 400


@pytest.mark.asyncio
async def test_failing_native_capture_does_not_silently_keep_remote_stream_alive(monkeypatch):
    import local_shell_mcp.gui as native_gui

    manager = FakeManager(Path("/tmp"))
    monkeypatch.setattr(native_gui, "get_gui_manager", lambda: manager)
    stream_module.configure_worker_stream("https://controller", {"Authorization": "Bearer worker"})
    posts = []

    async def capture(*_):
        raise RuntimeError("screen denied")

    def post(url, payload, secret):
        posts.append(payload)
        return {"actions": [], "refresh": False}

    monkeypatch.setattr(stream_module, "capture_frame", capture)
    monkeypatch.setattr(stream_module, "_post_frame", post)
    await stream_module._worker_stream_loop("s", "secret", "win")
    assert posts == [{"errors": ["screen denied"]}]
    assert stream_module._WORKER_STREAM_TASKS.get("s") is None


@pytest.mark.asyncio
async def test_capture_accepts_workspace_relative_internal_screenshot(tmp_path, monkeypatch):
    manager = FakeManager(tmp_path)
    monkeypatch.setattr(stream_module, "temp_dir", lambda: tmp_path)
    monkeypatch.setattr(stream_module, "workspace_root", lambda: tmp_path.parent)
    monkeypatch.setattr(stream_module, "release_temp_file_lease", lambda path: None)
    original_frame = manager.frame

    async def relative_frame(window_id):
        data = await original_frame(window_id)
        data["screenshot_path"] = str(Path(data["screenshot_path"]).relative_to(tmp_path.parent))
        return data

    manager.frame = relative_frame
    data, image = await stream_module.capture_frame(manager, "win")
    assert data["observation_id"] == "obs-1"
    assert image.startswith(b"\xff\xd8\xff")


def test_local_wayland_capture_waits_for_manual_refresh(tmp_path, monkeypatch):
    manager = FakeManager(tmp_path)
    monkeypatch.setattr(stream_module, "temp_dir", lambda: tmp_path)
    monkeypatch.setattr(gui, "get_gui_manager", lambda: manager)

    async def list_windows():
        return {"capabilities": {"capture_requires_focus": True}}

    manager.list_windows = list_windows
    with (
        TestClient(Starlette(routes=human_ui.ui_routes())) as client,
        client.websocket_connect("/ui/ws/desktop?machine=local&window_id=win") as ws,
    ):
        assert ws.receive_json() == {"type": "ready"}
        frame = ws.receive_json()
        assert frame["image"] is True
        ws.receive_bytes()
        time.sleep(0.11)
        assert manager.captured == 1
        ws.send_json({"type": "refresh"})
        refreshed = ws.receive_json()
        assert refreshed["type"] == "frame"
        assert refreshed["image"] is True
        ws.receive_bytes()
        assert manager.captured == 2
