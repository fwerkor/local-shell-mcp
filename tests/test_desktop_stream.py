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
            assert timeout_s >= (
                human_ui.REMOTE_QUEUE_TIMEOUT_S + 180 + human_ui.REMOTE_RESULT_GRACE_S
            )
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
            assert size == stream_module.MAX_WORKER_ACTION_RESPONSE_BYTES + 1
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
                {"request_id": 33, "observation_id": "obs-1", "bounds": {}, "action": {"type": "click", "x": 1, "y": 1}},
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
    assert requests[1]["acks"] == [{"request_id": 33, "ok": True}]
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
async def test_focus_sensitive_action_in_frame_response_triggers_next_capture(monkeypatch):
    import local_shell_mcp.gui as native_gui

    manager = FakeManager(Path("/tmp"))

    async def listing():
        return {"capabilities": {"capture_requires_focus": True}}

    manager.list_windows = listing
    monkeypatch.setattr(native_gui, "get_gui_manager", lambda: manager)
    monkeypatch.setattr(stream_module, "FRAME_INTERVAL_S", 0.005)
    stream_module.configure_worker_stream("https://controller", {"Authorization": "Bearer worker"})
    captures = 0
    posts = []

    async def capture(*_):
        nonlocal captures
        captures += 1
        return {
            "window": {"bounds": {}}, "observation_id": f"o{captures}",
            "observation_ttl_s": 20, "capabilities": {"coordinate_input": True},
        }, b"\xff\xd8\xffsame"

    def post(url, payload, secret):
        posts.append(payload)
        if len(posts) == 1:
            return {"actions": [{"request_id": 7, "observation_id": "o1", "bounds": {},
                                 "action": {"type": "click", "x": 1, "y": 1}}], "refresh": False}
        return {"actions": [], "refresh": False}

    monkeypatch.setattr(stream_module, "capture_frame", capture)
    monkeypatch.setattr(stream_module, "_post_frame", post)
    task = asyncio.create_task(stream_module._worker_stream_loop("focus-action", "secret", "win"))
    for _ in range(50):
        if len(posts) >= 3:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert captures == 2
    assert posts[1]["frame"]["observation_id"] == "o2"
    assert posts[1]["acks"] == [{"request_id": 7, "ok": True}]
    assert len(manager.actions) == 1


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


def test_worker_stream_acks_and_first_contact_startup():
    stream = stream_module.DesktopStream("node", "win")
    stream_module.STREAMS[stream.key] = stream
    assert stream.last_contact is None  # Worker startup can take longer than the steady-state idle timeout.
    result = stream_module.worker_frame(
        stream.key, stream.secret, "node",
        {"acks": [{"request_id": 7, "ok": True}, {"request_id": 8, "ok": False, "message": "stale"}]},
    )
    assert result == {"actions": [], "refresh": False}
    assert stream.acknowledgements.get_nowait() == {"type": "action-ack", "request_id": 7, "ok": True}
    assert stream.acknowledgements.get_nowait() == {
        "type": "action-ack", "request_id": 8, "ok": False, "message": "stale",
    }
    for acks in (["bad"], [{"request_id": True, "ok": True}], [{"request_id": 1, "ok": "yes"}], [{}], [{}] * 9):
        with pytest.raises(ValueError, match="Invalid desktop acknowledgement"):
            stream_module.worker_frame(stream.key, stream.secret, "node", {"acks": acks})
    stream.last_contact = time.monotonic() - stream_module.STREAM_IDLE_S - 1
    with pytest.raises(PermissionError, match="expired"):
        stream_module.worker_frame(stream.key, stream.secret, "node", {})
    assert stream.key not in stream_module.STREAMS


def test_local_desktop_action_acknowledged_after_execution(tmp_path, monkeypatch):
    manager = FakeManager(tmp_path)
    monkeypatch.setattr(stream_module, "temp_dir", lambda: tmp_path)
    monkeypatch.setattr(gui, "get_gui_manager", lambda: manager)
    with (TestClient(Starlette(routes=human_ui.ui_routes())) as client,
          client.websocket_connect("/ui/ws/desktop?machine=local&window_id=win") as ws):
        assert ws.receive_json() == {"type": "ready"}
        frame = ws.receive_json()
        ws.receive_bytes()
        ws.send_json({"type": "action", "request_id": 42, "observation_id": frame["observation_id"],
                      "bounds": frame["bounds"], "action": {"type": "click", "x": 10, "y": 20}})
        for _ in range(5):
            message = ws.receive_json()
            if message.get("image"):
                ws.receive_bytes()
            if message.get("type") == "action-ack":
                assert message == {"type": "action-ack", "request_id": 42, "ok": True}
                break
        else:
            pytest.fail("Local action was not acknowledged")
        assert len(manager.actions) == 1


def test_remote_desktop_action_ack_reaches_browser(monkeypatch):
    async def call(machine, tool, args, timeout_s=None):
        return {"started": True}
    monkeypatch.setattr(human_ui, "_remote_call", call)
    with (TestClient(Starlette(routes=human_ui.ui_routes())) as client,
          client.websocket_connect("/ui/ws/desktop?machine=node&window_id=win") as ws):
        assert ws.receive_json() == {"type": "ready"}
        stream = next(iter(stream_module.STREAMS.values()))
        stream_module.worker_frame(stream.key, stream.secret, "node",
                                   {"acks": [{"request_id": 99, "ok": False, "message": "input rejected"}]})
        assert ws.receive_json() == {
            "type": "action-ack", "request_id": 99, "ok": False, "message": "input rejected",
        }


@pytest.mark.asyncio
async def test_desktop_stream_reserves_capacity_during_handshake(monkeypatch):
    monkeypatch.setattr(human_ui, "_websocket_principal", lambda ws: object())
    monkeypatch.setattr(human_ui, "require_scopes", lambda *args: None)
    monkeypatch.setenv("LOCAL_SHELL_MCP_UI_TERMINAL_MAX_SESSIONS", "1")
    get_settings.cache_clear()

    class PendingSocket:
        def __init__(self):
            self.query_params = {"machine": "node", "window_id": "win"}
            self.headers = {}
            self.entered = asyncio.Event()
            self.release = asyncio.Event()
            self.closed = []

        async def accept(self, **kwargs):
            self.entered.set()
            await self.release.wait()

        async def close(self, code=1000, reason=""):
            self.closed.append(code)

    first, second = PendingSocket(), PendingSocket()
    task = asyncio.create_task(human_ui.ui_desktop_websocket(first))
    await asyncio.wait_for(first.entered.wait(), timeout=1)
    assert len(stream_module.STREAMS) == 1
    await human_ui.ui_desktop_websocket(second)
    assert second.closed == [4429]
    assert len(stream_module.STREAMS) == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stream_module.STREAMS == {}


def test_desktop_stream_live_credential_revoked_while_idle(tmp_path, monkeypatch):
    from starlette.websockets import WebSocketDisconnect

    manager = FakeManager(tmp_path)
    live = {"valid": True}
    monkeypatch.setattr(stream_module, "temp_dir", lambda: tmp_path)
    monkeypatch.setattr(gui, "get_gui_manager", lambda: manager)
    monkeypatch.setattr(human_ui, "_live_websocket_credentials", lambda _: ("live-id", "test-token"))
    monkeypatch.setattr(human_ui, "get_live_channel_manager", lambda: SimpleNamespace(
        authenticate=lambda token: SimpleNamespace(live_id="live-id") if live["valid"] else None
    ))
    monkeypatch.setattr(human_ui, "DESKTOP_CREDENTIAL_WATCH_INTERVAL_S", 0.02)
    with (TestClient(Starlette(routes=human_ui.ui_routes())) as client,
          client.websocket_connect("/ui/ws/desktop?machine=local&window_id=win") as ws):
        assert ws.receive_json() == {"type": "ready"}
        frame = ws.receive_json()
        if frame["image"]:
            ws.receive_bytes()
        live["valid"] = False
        with pytest.raises(WebSocketDisconnect) as error:
            for _ in range(10):
                message = ws.receive_json()
                if message.get("image"):
                    ws.receive_bytes()
        assert error.value.code == 4401


def test_desktop_stream_local_cache_bounded(tmp_path, monkeypatch):
    manager = FakeManager(tmp_path)
    active = set()
    peak = 0
    old_frame = manager.frame
    old_discard = manager.discard_frame_observation

    async def frame(window):
        nonlocal peak
        data = await old_frame(window)
        active.add(data["observation_id"])
        peak = max(peak, len(active))
        assert peak <= stream_module.RETAINED_OBSERVATIONS
        return data

    async def discard(window, observation):
        active.discard(observation)
        await old_discard(window, observation)

    manager.frame = frame
    manager.discard_frame_observation = discard
    monkeypatch.setattr(stream_module, "temp_dir", lambda: tmp_path)
    monkeypatch.setattr(stream_module, "FRAME_INTERVAL_S", 0.005)
    monkeypatch.setattr(gui, "get_gui_manager", lambda: manager)
    with (TestClient(Starlette(routes=human_ui.ui_routes())) as client,
          client.websocket_connect("/ui/ws/desktop?machine=local&window_id=win") as ws):
        assert ws.receive_json() == {"type": "ready"}
        for _ in range(8):
            message = ws.receive_json()
            if message.get("image"):
                ws.receive_bytes()
    assert peak == stream_module.RETAINED_OBSERVATIONS
    assert active == set()


def test_frame_budget_rejects_incompressible_output(tmp_path, monkeypatch):
    path = tmp_path / "gui-frame-big.png"
    Image.new("RGB", (1800, 1000), "white").save(path)

    def oversized_save(self, fp, *args, **kwargs):
        fp.write(b"x" * (stream_module.MAX_FRAME_BYTES + 1))

    monkeypatch.setattr(Image.Image, "save", oversized_save)
    with pytest.raises(ValueError, match="budget"):
        stream_module.compress_frame(path)


@pytest.mark.asyncio
async def test_capture_rejects_external_file_before_reading(tmp_path, monkeypatch):
    manager = FakeManager(tmp_path)
    external = tmp_path / "not-internal.png"
    external.write_bytes(b"private")
    monkeypatch.setattr(stream_module, "temp_dir", lambda: tmp_path)
    async def external_frame(window_id):
        return {"observation_id": "bad", "screenshot_path": str(external)}
    manager.frame = external_frame
    with pytest.raises(ValueError, match="not an internal"):
        await stream_module.capture_frame(manager, "win")
    assert manager.discarded == ["bad"]
    assert external.read_bytes() == b"private"


def test_worker_ack_queue_limits_memory_and_rejects_invalid_packets():
    stream = stream_module.DesktopStream("node", "win")
    stream_module.STREAMS[stream.key] = stream
    for i in range(4):
        stream_module.worker_frame(stream.key, stream.secret, "node", {
            "acks": [{"request_id": i * 8 + j + 1, "ok": True} for j in range(8)]
        })
    assert stream.acknowledgements.qsize() == 32
    with pytest.raises(ValueError, match="queue is full"):
        stream_module.worker_frame(stream.key, stream.secret, "node",
                                   {"acks": [{"request_id": 44, "ok": True}]})
    for acks in ("not-list", 0, False):
        with pytest.raises(ValueError, match="acknowledgements"):
            stream_module.worker_frame(stream.key, stream.secret, "node", {"acks": acks})


@pytest.mark.asyncio
async def test_worker_acknowledges_completed_and_failed_focus_sensitive_actions(monkeypatch):
    manager = FakeManager(Path("/tmp"))
    async def listing():
        return {"capabilities": {"capture_requires_focus": True}}
    async def act(window, observation, bounds, actions):
        if actions[0]["x"] == 2:
            raise ValueError("outdated frame")
    manager.list_windows = listing
    manager.human_act = act
    monkeypatch.setattr(gui, "get_gui_manager", lambda: manager)
    monkeypatch.setattr(stream_module, "FRAME_INTERVAL_S", 0.005)
    stream_module.configure_worker_stream("https://controller", {"Authorization": "Bearer worker"})
    sent = []
    async def capture(*_):
        return {
            "window": {"bounds": {"x": 0, "y": 0, "width": 100, "height": 100}},
            "observation_id": "o1",
            "observation_ttl_s": 20,
        }, b"\xff\xd8\xffframe"
    def post(url, payload, secret):
        sent.append(payload)
        if len(sent) == 2:
            return {"actions": [
                {"request_id": 1, "observation_id": "o1", "bounds": {}, "action": {"type": "click", "x": 1, "y": 1}},
                {"request_id": 2, "observation_id": "o1", "bounds": {}, "action": {"type": "click", "x": 2, "y": 2}},
                None,
            ], "refresh": False}
        return {"actions": [], "refresh": False}
    monkeypatch.setattr(stream_module, "capture_frame", capture)
    monkeypatch.setattr(stream_module, "_post_frame", post)
    task = asyncio.create_task(stream_module._worker_stream_loop("s-acks", "secret", "win"))
    for _ in range(50):
        if len(sent) >= 4:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    acks = [ack for entry in sent for ack in entry.get("acks", [])]
    assert acks == [
        {"request_id": 1, "ok": True},
        {"request_id": 2, "ok": False, "refresh": True, "message": "outdated frame"},
    ]
    assert all("errors" not in entry for entry in sent)


def test_desktop_local_failing_action_returns_negative_ack(tmp_path, monkeypatch):
    manager = FakeManager(tmp_path)
    async def fail(*_):
        raise ValueError("observation expired")
    manager.human_act = fail
    monkeypatch.setattr(stream_module, "temp_dir", lambda: tmp_path)
    monkeypatch.setattr(gui, "get_gui_manager", lambda: manager)
    with (TestClient(Starlette(routes=human_ui.ui_routes())) as client,
          client.websocket_connect("/ui/ws/desktop?machine=local&window_id=win") as ws):
        assert ws.receive_json() == {"type": "ready"}
        frame = ws.receive_json()
        ws.receive_bytes()
        ws.send_json({"type": "action", "request_id": 9, "observation_id": frame["observation_id"],
                      "bounds": frame["bounds"], "action": {"type": "click", "x": 1, "y": 1}})
        while True:
            result = ws.receive_json()
            if result.get("image"):
                ws.receive_bytes()
            if result.get("type") == "action-ack":
                assert result == {"type": "action-ack", "request_id": 9, "ok": False,
                                  "refresh": True, "message": "observation expired"}
                break
        ws.send_json({"type": "action", "request_id": 10, "bounds": {}, "action": {"type": "bad"}})
        while True:
            result = ws.receive_json()
            if result.get("image"):
                ws.receive_bytes()
            if result.get("type") == "action-ack":
                assert result["request_id"] == 10 and result["ok"] is False
                break


def test_remote_desktop_input_queue_full_returns_negative_ack(monkeypatch):
    async def call(machine, tool, args, timeout_s=None):
        return {"started": True}
    monkeypatch.setattr(human_ui, "_remote_call", call)
    with (TestClient(Starlette(routes=human_ui.ui_routes())) as client,
          client.websocket_connect("/ui/ws/desktop?machine=node&window_id=win") as ws):
        assert ws.receive_json() == {"type": "ready"}
        stream = next(iter(stream_module.STREAMS.values()))
        for i in range(stream.actions.maxsize):
            stream.actions.put_nowait({"request_id": i})
        ws.send_json({"type": "action", "request_id": 17, "observation_id": "obs",
                      "bounds": {}, "action": {"type": "click", "x": 1, "y": 1}})
        assert ws.receive_json() == {"type": "action-ack", "request_id": 17,
                                    "ok": False, "message": "Desktop input queue is full"}


@pytest.mark.asyncio
async def test_worker_regular_mode_reports_failed_input_without_killing_stream(monkeypatch):
    manager = FakeManager(Path("/tmp"))
    async def reject(*_):
        raise ValueError("observation mismatch")
    manager.human_act = reject
    monkeypatch.setattr(gui, "get_gui_manager", lambda: manager)
    monkeypatch.setattr(stream_module, "FRAME_INTERVAL_S", 0.005)
    stream_module.configure_worker_stream("https://controller", {"Authorization": "Bearer worker"})
    posts = []

    async def capture(*_):
        return {"window": {"bounds": {}}, "observation_id": "o1",
                "observation_ttl_s": 20}, b"\xff\xd8\xffdata"

    def post(url, payload, secret):
        posts.append(payload)
        if len(posts) == 1:
            return {"actions": [{"request_id": 17, "observation_id": "o1",
                                 "bounds": {}, "action": {"type": "click", "x": 1, "y": 1}}]}
        return {"actions": []}

    monkeypatch.setattr(stream_module, "capture_frame", capture)
    monkeypatch.setattr(stream_module, "_post_frame", post)
    task = asyncio.create_task(stream_module._worker_stream_loop("failed-input", "secret", "win"))
    for _ in range(40):
        if len(posts) >= 5:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert posts[1]["acks"] == [
        {"request_id": 17, "ok": False, "refresh": True, "message": "observation mismatch"},
    ]
    assert all("errors" not in entry for entry in posts)
    assert len(manager.discarded) >= 2


def test_remote_stream_delivers_fatal_worker_errors(monkeypatch):
    from starlette.websockets import WebSocketDisconnect

    async def call(machine, tool, args, timeout_s=None):
        return {}
    monkeypatch.setattr(human_ui, "_remote_call", call)
    with (TestClient(Starlette(routes=human_ui.ui_routes())) as client,
          client.websocket_connect("/ui/ws/desktop?machine=node&window_id=win") as ws):
        assert ws.receive_json() == {"type": "ready"}
        stream = next(iter(stream_module.STREAMS.values()))
        stream.enqueue_frame({"type": "error", "message": "Desktop access denied"}, b"")
        assert ws.receive_json() == {
            "type": "error", "message": "Desktop access denied", "image": False,
        }
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_local_focus_sensitive_stream_only_refreshes_on_demand(tmp_path, monkeypatch):
    manager = FakeManager(tmp_path)
    async def listing():
        return {"capabilities": {"capture_requires_focus": True}}
    manager.list_windows = listing
    monkeypatch.setattr(gui, "get_gui_manager", lambda: manager)
    monkeypatch.setattr(stream_module, "temp_dir", lambda: tmp_path)
    monkeypatch.setattr(stream_module, "FRAME_INTERVAL_S", 0.005)
    with (TestClient(Starlette(routes=human_ui.ui_routes())) as client,
          client.websocket_connect("/ui/ws/desktop?machine=local&window_id=win") as ws):
        assert ws.receive_json() == {"type": "ready"}
        first = ws.receive_json()
        ws.receive_bytes()
        ws.send_json({"type": "refresh"})
        second = ws.receive_json()
        if second.get("image"):
            ws.receive_bytes()
        assert first["observation_id"] != second["observation_id"]
    assert manager.captured == 2
    assert len(manager.discarded) == 2


@pytest.mark.asyncio
async def test_local_refresh_during_frame_send_is_not_lost(monkeypatch, tmp_path):
    manager = FakeManager(tmp_path)
    monkeypatch.setattr(gui, "get_gui_manager", lambda: manager)
    monkeypatch.setattr(human_ui, "_websocket_principal", lambda _: object())
    monkeypatch.setattr(human_ui, "require_scopes", lambda *_: None)
    monkeypatch.setattr(stream_module, "FRAME_INTERVAL_S", 0.005)
    captured = 0

    async def capture(*_):
        nonlocal captured
        captured += 1
        return {
            "window": {"bounds": {"x": 0, "y": 0, "width": 20, "height": 10}},
            "observation_id": f"obs-{captured}", "observation_ttl_s": 20,
            "capabilities": {"coordinate_input": True},
        }, b"\xff\xd8\xffunchanged"

    monkeypatch.setattr(stream_module, "capture_frame", capture)

    class PausedSocket:
        query_params = {"machine": "local", "window_id": "win"}
        headers = {}

        def __init__(self):
            self.incoming = asyncio.Queue()
            self.frames = []
            self.second_started = asyncio.Event()
            self.release_second = asyncio.Event()
            self.third_sent = asyncio.Event()

        async def accept(self, **_):
            pass

        async def send_text(self, raw):
            packet = json.loads(raw)
            if packet["type"] != "frame":
                return
            self.frames.append(packet)
            if len(self.frames) == 2:
                self.second_started.set()
                await self.release_second.wait()
            if len(self.frames) == 3:
                self.third_sent.set()

        async def send_bytes(self, data):
            pass

        async def receive(self):
            return await self.incoming.get()

        async def close(self, **_):
            pass

    socket = PausedSocket()
    task = asyncio.create_task(human_ui.ui_desktop_websocket(socket))
    try:
        await asyncio.wait_for(socket.second_started.wait(), timeout=2)
        assert socket.frames[0]["image"] is True
        assert socket.frames[1]["image"] is False
        stream = next(iter(stream_module.STREAMS.values()))
        socket.incoming.put_nowait({"type": "websocket.receive", "text": '{"type":"refresh"}'})
        for _ in range(100):
            if stream.force_frame:
                break
            await asyncio.sleep(0.002)
        assert stream.force_frame is True
        socket.release_second.set()
        await asyncio.wait_for(socket.third_sent.wait(), timeout=2)
        assert socket.frames[2]["image"] is True
        socket.incoming.put_nowait({"type": "websocket.disconnect"})
        await asyncio.wait_for(task, timeout=2)
    finally:
        socket.release_second.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


def test_desktop_local_disabled_by_settings(monkeypatch):
    from starlette.websockets import WebSocketDisconnect

    monkeypatch.setattr(human_ui, "get_settings", lambda: SimpleNamespace(
        ui_enabled=True, ui_path="ui", disable_local=True, ui_terminal_max_sessions=8,
        auth_mode="none",
    ))
    with TestClient(Starlette(routes=human_ui.ui_routes())) as client:
        with (pytest.raises(WebSocketDisconnect) as denied,
              client.websocket_connect("/ui/ws/desktop?machine=local&window_id=win") as ws):
            ws.receive_json()
        assert denied.value.code == 4403


def test_remote_worker_action_response_supports_four_max_length_text_inputs(monkeypatch):
    import urllib.request

    actions = [{"request_id": i, "observation_id": "observation",
                "bounds": {"x": 0, "y": 0, "width": 100, "height": 100},
                "action": {"type": "type", "text": "x" * 4096}} for i in range(4)]
    data = json.dumps({"actions": actions}).encode()
    assert len(data) > 16 * 1024

    class Response:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self, size):
            assert size == stream_module.MAX_WORKER_ACTION_RESPONSE_BYTES + 1
            return self.body[:size]

    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *args, **kwargs: Response(data))
    assert stream_module._post_frame("https://controller/remote/gui/stream/id", {}, "secret") == {
        "actions": actions,
    }
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *args, **kwargs: Response(b"x" * (stream_module.MAX_WORKER_ACTION_RESPONSE_BYTES + 1)))
    with pytest.raises(ValueError, match="response is too large"):
        stream_module._post_frame("https://controller/remote/gui/stream/id", {}, "secret")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["manager", "discovery"])
async def test_worker_reports_initial_gui_discovery_failure_and_cleans_task(monkeypatch, failure_stage):
    manager = FakeManager(Path("/tmp"))
    async def fail_listing():
        raise RuntimeError("GUI permission denied")
    manager.list_windows = fail_listing

    def manager_factory():
        if failure_stage == "manager":
            raise RuntimeError("GUI setup unavailable")
        return manager

    monkeypatch.setattr(gui, "get_gui_manager", manager_factory)
    stream_module.configure_worker_stream("https://controller", {"Authorization": "Bearer worker"})
    posts = []
    def post(url, payload, secret):
        posts.append(payload)
        return {"actions": [], "refresh": False}
    monkeypatch.setattr(stream_module, "_post_frame", post)
    stream_module.start_worker_stream("initial-error", "secret", "win")
    task = stream_module._WORKER_STREAM_TASKS["initial-error"]
    await asyncio.wait_for(task, timeout=2)
    assert posts == [{"errors": ["GUI setup unavailable" if failure_stage == "manager" else "GUI permission denied"]}]
    assert "initial-error" not in stream_module._WORKER_STREAM_TASKS


def test_remote_stream_idle_timeout_allows_valid_long_running_gui_operations():
    stream = stream_module.DesktopStream("node", "win")
    stream_module.STREAMS[stream.key] = stream
    stream.last_contact = time.monotonic() - 45
    assert stream_module.worker_frame(stream.key, stream.secret, "node", {}) == {
        "actions": [], "refresh": False,
    }
    assert stream.key in stream_module.STREAMS


def test_worker_disconnect_is_reported_and_stream_is_released(monkeypatch):
    from starlette.websockets import WebSocketDisconnect

    async def remote_call(machine, tool, args, timeout_s=None):
        return {"started": True}

    monkeypatch.setattr(human_ui, "_remote_call", remote_call)
    monkeypatch.setattr(human_ui, "DESKTOP_FRAME_WAIT_S", 0.02)
    with (TestClient(Starlette(routes=human_ui.ui_routes())) as client,
          client.websocket_connect("/ui/ws/desktop?machine=node&window_id=win") as ws):
        assert ws.receive_json() == {"type": "ready"}
        stream = next(iter(stream_module.STREAMS.values()))
        stream.last_contact = time.monotonic() - stream_module.STREAM_IDLE_S - 1
        assert ws.receive_json() == {
            "type": "error", "message": "Remote desktop worker stopped responding",
        }
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
    assert stream.key not in stream_module.STREAMS


def test_stream_reports_remaining_ttl_after_compression(tmp_path, monkeypatch):
    manager = FakeManager(tmp_path)
    monkeypatch.setattr(stream_module, "temp_dir", lambda: tmp_path)
    compress = stream_module.compress_frame

    def slow_compress(path):
        time.sleep(0.035)
        return compress(path)

    monkeypatch.setattr(stream_module, "compress_frame", slow_compress)
    data, image = asyncio.run(stream_module.capture_frame(manager, "win"))
    assert image.startswith(b"\xff\xd8\xff")
    assert 24.0 < data["observation_ttl_s"] < 24.98


def test_remote_queued_frame_ttl_does_not_restart_on_delivery(monkeypatch):
    async def remote_call(machine, tool, args, timeout_s=None):
        return {"started": True}

    monkeypatch.setattr(human_ui, "_remote_call", remote_call)
    with (TestClient(Starlette(routes=human_ui.ui_routes())) as client,
          client.websocket_connect("/ui/ws/desktop?machine=node&window_id=win") as ws):
        assert ws.receive_json() == {"type": "ready"}
        stream = next(iter(stream_module.STREAMS.values()))
        stream.enqueue_frame({
            "type": "frame", "bounds": {"x": 0, "y": 0, "width": 20, "height": 10},
            "observation_id": "one", "ttl_s": 8, "coordinate_input": True,
        }, b"\xff\xd8\xfftest")
        # Simulate two seconds of controller-side queueing.
        stream.frames._queue[0][0]["_queued_at"] -= 2
        delivered = ws.receive_json()
        assert 5.0 < delivered["ttl_s"] < 6.1
        assert "_queued_at" not in delivered
        ws.receive_bytes()


@pytest.mark.parametrize("machine", ["local", "node"])
def test_desktop_live_channel_records_only_successful_gui_actions(tmp_path, monkeypatch, machine):
    events = []
    channel = SimpleNamespace(
        authenticate=lambda _: SimpleNamespace(live_id="live-1"),
        publish_channel=lambda *args, **kwargs: events.append((args, kwargs)),
    )
    monkeypatch.setattr(human_ui, "_live_websocket_credentials", lambda _: ("live-1", "token"))
    monkeypatch.setattr(human_ui, "get_live_channel_manager", lambda: channel)
    monkeypatch.setattr(stream_module, "temp_dir", lambda: tmp_path)
    monkeypatch.setattr(gui, "get_gui_manager", lambda: FakeManager(tmp_path))
    async def remote_call(machine, tool, args, timeout_s=None):
        return {"started": True}
    monkeypatch.setattr(human_ui, "_remote_call", remote_call)

    with (TestClient(Starlette(routes=human_ui.ui_routes())) as client,
          client.websocket_connect(f"/ui/ws/desktop?machine={machine}&window_id=win") as ws):
        assert ws.receive_json() == {"type": "ready"}
        if machine == "local":
            frame = ws.receive_json()
            if frame.get("image"):
                ws.receive_bytes()
        else:
            frame = {"observation_id": "obs", "bounds": {}}
        ws.send_json({"type": "action", "request_id": 12,
                      "observation_id": frame["observation_id"],
                      "bounds": frame["bounds"], "action": {"type": "click", "x": 1, "y": 1}})
        if machine == "node":
            stream = next(iter(stream_module.STREAMS.values()))
            for _ in range(200):
                if not stream.actions.empty():
                    break
                time.sleep(0.005)
            assert stream_module.worker_frame(stream.key, stream.secret, machine, {})["actions"][0]["request_id"] == 12
            stream_module.worker_frame(stream.key, stream.secret, machine, {
                "acks": [{"request_id": 12, "ok": True}],
            })
        for _ in range(6):
            ack = ws.receive_json()
            if ack.get("image"):
                ws.receive_bytes()
            if ack.get("type") == "action-ack":
                assert ack["request_id"] == 12 and ack["ok"] is True
                break
        else:
            pytest.fail("Expected action acknowledgement")
        assert events
        assert events[-1] == (
            ("live-1", "human.action"),
            {"actor": "human", "data": {
                "action": "gui.action", "machine": machine, "window_id": "win", "actions": ["click"],
            }},
        )


def test_remote_desktop_failed_gui_ack_does_not_publish_live_activity(monkeypatch):
    events = []
    channel = SimpleNamespace(
        authenticate=lambda _: SimpleNamespace(live_id="live-1"),
        publish_channel=lambda *a, **k: events.append((a, k)),
    )
    monkeypatch.setattr(human_ui, "_live_websocket_credentials", lambda _: ("live-1", "token"))
    monkeypatch.setattr(human_ui, "get_live_channel_manager", lambda: channel)
    async def remote_call(machine, tool, args, timeout_s=None):
        return {"started": True}
    monkeypatch.setattr(human_ui, "_remote_call", remote_call)
    with (TestClient(Starlette(routes=human_ui.ui_routes())) as client,
          client.websocket_connect("/ui/ws/desktop?machine=node&window_id=win") as ws):
        assert ws.receive_json() == {"type": "ready"}
        ws.send_json({"type": "action", "request_id": 15,
                      "observation_id": "obs", "bounds": {},
                      "action": {"type": "key", "keys": ["ENTER"]}})
        stream = next(iter(stream_module.STREAMS.values()))
        for _ in range(200):
            if not stream.actions.empty():
                break
            time.sleep(0.005)
        assert stream_module.worker_frame(stream.key, stream.secret, "node", {})["actions"][0]["request_id"] == 15
        stream_module.worker_frame(stream.key, stream.secret, "node", {
            "acks": [{"request_id": 15, "ok": False, "refresh": True, "message": "stale"}],
        })
        assert ws.receive_json() == {
            "type": "action-ack", "request_id": 15, "ok": False, "refresh": True, "message": "stale",
        }
        assert not events


def test_worker_frame_overwrites_pending_image_with_new_keyframe():
    stream = stream_module.DesktopStream('node', 'win')
    first = {'type': 'frame', 'observation_id': 'old', 'bounds': {}}
    stream.enqueue_frame(first, b'\xff\xd8\xffold')
    stream.enqueue_frame({**first, 'observation_id': 'new'}, b'\xff\xd8\xffnew')
    assert stream.frames.qsize() == 1
    metadata, image = stream.frames.get_nowait()
    assert metadata['observation_id'] == 'new'
    assert image == b'\xff\xd8\xffnew'
    assert isinstance(metadata['_queued_at'], float)


def test_worker_frame_ignores_non_string_error_messages():
    stream = stream_module.DesktopStream('node', 'win')
    stream_module.STREAMS[stream.key] = stream
    metadata = {'type': 'frame', 'observation_id': 'o1', 'bounds': {}}
    stream_module.worker_frame(stream.key, stream.secret, 'node', {
        'frame': metadata, 'errors': [{'private': 'do-not-reflect'}],
    })
    received, _ = stream.frames.get_nowait()
    assert received.get('warning') is None
    stream_module.worker_frame(stream.key, stream.secret, 'node', {
        'errors': [False],
    })
    assert stream.frames.empty()
