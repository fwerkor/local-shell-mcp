"""Low-bandwidth human desktop transport, independent of tool/audit RPCs."""
from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import hmac
import io
import json
import secrets
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .fs_ops import release_temp_file_lease, temp_dir, workspace_root

MAX_FRAME_BYTES = 128 * 1024
FRAME_INTERVAL_S = 0.9
FRAME_WIDTH = 1280
FRAME_HEIGHT = 800
FRAME_QUALITY = 46
STREAM_IDLE_S = 120.0
RETAINED_OBSERVATIONS = 3
MAX_WORKER_ACTION_RESPONSE_BYTES = 512 * 1024


@dataclass(frozen=True)
class FrameProfile:
    width: int
    height: int
    quality: int
    max_bytes: int
    interval: float


# A small ladder allows rapid downgrade and cautious recovery. All levels
# stay within the existing wire-size limit and screenshot policy.
FRAME_PROFILES = (
    FrameProfile(480, 300, 30, 12 * 1024, 0.9),
    FrameProfile(800, 500, 38, 32 * 1024, 0.55),
    FrameProfile(1280, 800, 46, 64 * 1024, 0.35),
    FrameProfile(1600, 1000, 56, 96 * 1024, 0.22),
    FrameProfile(1920, 1080, 66, MAX_FRAME_BYTES, 0.15),
)
ADAPTIVE_OBSERVATIONS = 12
FRAME_ACK_TIMEOUT_S = 10.0


@dataclass
class AdaptivePacer:
    level: int = 2
    healthy: int = 0
    unchanged: int = 0
    delivery_s: float = 0.0

    @property
    def profile(self) -> FrameProfile:
        return FRAME_PROFILES[self.level]

    def congested(self) -> None:
        self.level = max(0, self.level - 1)
        self.healthy = 0

    def sample(self, size: int, elapsed: float) -> None:
        if size <= 0 or elapsed <= 0:
            return
        # Observed delivery time includes transport, queueing and decoding.
        # React immediately to slower service and recover gradually.
        self.delivery_s = max(elapsed, 0.75 * self.delivery_s + 0.25 * elapsed)
        if elapsed > max(0.25, self.profile.interval * 0.85):
            self.congested()
        elif elapsed < self.profile.interval * 0.45:
            self.healthy += 1
            if self.healthy >= 5:
                self.level = min(len(FRAME_PROFILES) - 1, self.level + 1)
                self.healthy = 0
        else:
            self.healthy = 0

    @property
    def network_interval(self) -> float:
        return max(self.profile.interval, min(4.0, self.delivery_s * 1.15))

    def interval(self, changed: bool, interactive: bool = False) -> float:
        self.unchanged = 0 if changed or interactive else min(8, self.unchanged + 1)
        # Idle capture is cheap and bounded; input/refresh restores normal pacing.
        return max(self.network_interval, min(0.9, 0.15 * self.unchanged))


def compress_frame(path: Path, profile: FrameProfile | None = None) -> bytes:
    from PIL import Image
    with Image.open(path) as opened:
        image = opened.convert("RGB")
        image.thumbnail((profile.width, profile.height) if profile else (FRAME_WIDTH, FRAME_HEIGHT), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        for _ in range(5):
            for quality in ((profile.quality, min(32, profile.quality), 22) if profile else (FRAME_QUALITY, 32, 22)):
                output.seek(0)
                output.truncate(0)
                image.save(output, "JPEG", quality=quality, optimize=True)
                if output.tell() <= (profile.max_bytes if profile else MAX_FRAME_BYTES):
                    return output.getvalue()
            image.thumbnail((max(240, image.width * 3 // 4), max(160, image.height * 3 // 4)))
    raise ValueError("Desktop frame could not fit the transfer budget")


async def capture_frame(manager: Any, window_id: str, profile: FrameProfile | None = None) -> tuple[dict[str, Any], bytes]:
    data = await manager.frame(window_id)
    started = time.monotonic()
    path = Path(str(data["screenshot_path"])).expanduser()
    if not path.is_absolute():
        path = workspace_root() / path
    root = temp_dir().resolve()
    if path.parent.resolve() != root or path.resolve().parent != root or not path.name.startswith("gui-frame-") or not path.name.endswith(".png"):
        await manager.discard_frame_observation(window_id, data["observation_id"])
        raise ValueError("Desktop frame is not an internal GUI screenshot")
    try:
        image = await asyncio.to_thread(compress_frame, path, profile) if profile else await asyncio.to_thread(compress_frame, path)
        data["observation_ttl_s"] = max(
            0.0, float(data["observation_ttl_s"]) - (time.monotonic() - started)
        )
        return data, image
    except BaseException:
        with contextlib.suppress(Exception):
            await manager.discard_frame_observation(window_id, data["observation_id"])
        raise
    finally:
        path.unlink(missing_ok=True)
        release_temp_file_lease(path)


def frame_metadata(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "frame",
        "bounds": data["window"]["bounds"],
        "observation_id": data["observation_id"],
        "ttl_s": data["observation_ttl_s"],
        "coordinate_input": data.get("capabilities", {}).get("coordinate_input") is True,
    }


@dataclass
class DesktopStream:
    machine: str
    window_id: str
    key: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    secret: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    frames: asyncio.Queue[tuple[dict[str, Any], bytes]] = field(
        default_factory=lambda: asyncio.Queue(maxsize=1)
    )
    actions: asyncio.Queue[dict[str, Any]] = field(
        default_factory=lambda: asyncio.Queue(maxsize=8)
    )
    acknowledgements: asyncio.Queue[dict[str, Any]] = field(
        default_factory=lambda: asyncio.Queue(maxsize=32)
    )
    pending_live_actions: dict[int, str] = field(default_factory=dict)
    last_contact: float | None = None
    force_frame: bool = False
    adaptive: bool = False
    pacer: AdaptivePacer = field(default_factory=AdaptivePacer)

    def enqueue_frame(self, metadata: dict[str, Any], image: bytes) -> None:
        if metadata.get("type") == "frame":
            metadata = {**metadata, "_queued_at": time.monotonic()}
        if self.frames.full():
            _, queued_image = self.frames.get_nowait()
            if self.adaptive and image and queued_image:
                self.pacer.congested()
            if not image and metadata.get("type") == "frame":
                image = queued_image
        self.frames.put_nowait((metadata, image))
        self.last_contact = time.monotonic()

    def drain_actions(self) -> list[dict[str, Any]]:
        result = []
        while not self.actions.empty():
            result.append(self.actions.get_nowait())
        return result


STREAMS: dict[str, DesktopStream] = {}


def worker_frame(stream_id: str, secret: str, machine: str, body: dict[str, Any]) -> dict[str, Any]:
    stream = STREAMS.get(stream_id)
    if (stream is None or stream.machine != machine
            or not hmac.compare_digest(stream.secret, secret)):
        raise PermissionError("Unknown desktop stream")
    if stream.last_contact is not None and time.monotonic() - stream.last_contact > STREAM_IDLE_S:
        STREAMS.pop(stream_id, None)
        raise PermissionError("Desktop stream expired")
    raw = body.get("image")
    metadata = body.get("frame")
    if metadata is not None:
        if not isinstance(metadata, dict) or metadata.get("type") != "frame":
            raise ValueError("Invalid desktop frame metadata")
        if not isinstance(metadata.get("observation_id"), str) or not isinstance(metadata.get("bounds"), dict):
            raise ValueError("Incomplete desktop observation")
    errors = body.get("errors")
    acks = body.get("acks", [])
    if not isinstance(acks, list) or len(acks) > 8:
        raise ValueError("Invalid desktop acknowledgements")
    for ack in acks:
        if (not isinstance(ack, dict)
                or not isinstance(ack.get("request_id"), int)
                or isinstance(ack["request_id"], bool)
                or not isinstance(ack.get("ok"), bool)):
            raise ValueError("Invalid desktop acknowledgement")
    if stream.acknowledgements.qsize() + len(acks) > stream.acknowledgements.maxsize:
        raise ValueError("Desktop acknowledgement queue is full")
    if isinstance(metadata, dict) and isinstance(errors, list):
        for error in errors[:1]:
            if isinstance(error, str):
                metadata = {**metadata, "warning": error[:240]}
    if raw is not None:
        if not isinstance(raw, str) or len(raw) > MAX_FRAME_BYTES * 2:
            raise ValueError("Invalid desktop frame")
        try:
            image = base64.b64decode(raw, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise ValueError("Invalid desktop image encoding") from exc
        if len(image) > MAX_FRAME_BYTES or not image.startswith(b"\xff\xd8\xff"):
            raise ValueError("Invalid JPEG frame")
        stream.enqueue_frame(metadata, image)
    elif metadata is not None:
        stream.enqueue_frame(metadata, b"")
    if metadata is None and isinstance(errors, list):
        for error in errors[:1]:
            if isinstance(error, str):
                stream.enqueue_frame({"type": "error", "message": error[:240]}, b"")
    stream.last_contact = time.monotonic()
    for ack in acks:
        stream.acknowledgements.put_nowait({
            "type": "action-ack",
            "request_id": ack["request_id"],
            "ok": ack["ok"],
            **({"message": str(ack["message"])[:240]} if not ack["ok"] and "message" in ack else {}),
            **({"refresh": True} if ack.get("refresh") is True else {}),
        })
    refresh = stream.force_frame
    stream.force_frame = False
    result = {"actions": stream.drain_actions(), "refresh": refresh}
    if stream.adaptive:
        result["profile_level"] = stream.pacer.level
        result["interval_s"] = stream.pacer.network_interval
    return result


_WORKER_STREAM_TASKS: dict[str, asyncio.Task[None]] = {}
_WORKER_SERVER = ""
_WORKER_HEADERS: dict[str, str] = {}


def configure_worker_stream(server: str, headers: dict[str, str]) -> None:
    global _WORKER_SERVER, _WORKER_HEADERS
    _WORKER_SERVER = server.rstrip("/")
    _WORKER_HEADERS = dict(headers)


def _post_frame(url: str, payload: dict[str, Any], secret: str) -> dict[str, Any]:
    encoded = json.dumps(payload, separators=(",", ":")).encode()
    request = urllib.request.Request(
        url, data=encoded, method="POST",
        headers={"Content-Type": "application/json", "X-LSM-Desktop-Secret": secret, **_WORKER_HEADERS},
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310 - worker's enrolled controller
        payload = response.read(MAX_WORKER_ACTION_RESPONSE_BYTES + 1)
        if len(payload) > MAX_WORKER_ACTION_RESPONSE_BYTES:
            raise ValueError("Desktop controller response is too large")
        value = json.loads(payload)
        if not isinstance(value, dict):
            raise ValueError("Invalid desktop controller response")
        return value


async def _worker_stream_loop(stream_id: str, secret: str, window_id: str) -> None:
    from .gui import get_gui_manager

    manager = None
    url = f"{_WORKER_SERVER}/remote/gui/stream/{stream_id}"
    previous_image = b""
    observations: list[str] = []
    force_frame = True
    pending_errors: list[str] = []
    pending_acks: list[dict[str, Any]] = []
    adaptive = False
    pacer = AdaptivePacer()
    controller_level = len(FRAME_PROFILES) - 1
    controller_interval = 0.0

    def feedback(result: dict[str, Any], size: int, elapsed: float) -> None:
        nonlocal adaptive, controller_level, controller_interval
        level = result.get("profile_level")
        if type(level) is int and 0 <= level < len(FRAME_PROFILES):
            adaptive = True
            controller_level = level
            interval = result.get("interval_s")
            controller_interval = (max(FRAME_PROFILES[level].interval, min(4.0, interval))
                                   if type(interval) in (int, float) and 0 < interval <= 4.0
                                   else FRAME_PROFILES[level].interval)
            if size:
                pacer.sample(size, elapsed)

    try:
        manager = get_gui_manager()
        capabilities = (await manager.list_windows()).get("capabilities", {})
        focus_sensitive = capabilities.get("capture_requires_focus") is True
        while True:
            started = time.monotonic()
            if focus_sensitive and not force_frame:
                payload = {}
                if pending_errors:
                    payload["errors"] = pending_errors
                if pending_acks:
                    payload["acks"] = pending_acks
                result = await asyncio.to_thread(_post_frame, url, payload, secret)
                feedback(result, 0, 0)
                pending_errors = []
                pending_acks = []
                for entry in result.get("actions", []):
                    if not isinstance(entry, dict):
                        continue
                    try:
                        await manager.human_act(window_id, entry["observation_id"], entry["bounds"], [entry["action"]])
                        force_frame = True
                    except Exception as exc:
                        if isinstance(entry.get("request_id"), int):
                            pending_acks.append({"request_id": entry["request_id"], "ok": False, "refresh": True, "message": str(exc)[:240]})
                        else:
                            pending_errors.append(str(exc)[:240])
                    else:
                        if isinstance(entry.get("request_id"), int):
                            pending_acks.append({"request_id": entry["request_id"], "ok": True})
                force_frame = force_frame or bool(result.get("refresh"))
                await asyncio.sleep(max(0.05, (min(0.35, pacer.profile.interval) if adaptive else FRAME_INTERVAL_S) - (time.monotonic() - started)))
                continue
            if len(observations) >= (ADAPTIVE_OBSERVATIONS if adaptive else RETAINED_OBSERVATIONS):
                await manager.discard_frame_observation(window_id, observations.pop(0))
            profile = FRAME_PROFILES[min(pacer.level, controller_level)] if adaptive else None
            data, image = await capture_frame(manager, window_id, profile) if profile else await capture_frame(manager, window_id)
            observation = data["observation_id"]
            changed = force_frame or hashlib.blake2s(image).digest() != previous_image
            payload: dict[str, Any] = {"frame": frame_metadata(data)}
            if pending_errors:
                payload["errors"] = pending_errors
                pending_errors = []
            if pending_acks:
                payload["acks"] = pending_acks
                pending_acks = []
            if changed:
                payload["image"] = base64.b64encode(image).decode("ascii")
                previous_image = hashlib.blake2s(image).digest()
            try:
                sent_at = time.monotonic()
                result = await asyncio.to_thread(_post_frame, url, payload, secret)
                feedback(result, len(payload.get("image", "")), time.monotonic() - sent_at)
                force_frame = bool(result.get("refresh"))
                for entry in result.get("actions", []):
                    if not isinstance(entry, dict):
                        continue
                    # The browser action carries the exact captured observation and geometry.
                    try:
                        await manager.human_act(window_id, entry["observation_id"], entry["bounds"], [entry["action"]])
                    except Exception as exc:
                        if isinstance(entry.get("request_id"), int):
                            pending_acks.append({"request_id": entry["request_id"], "ok": False, "refresh": True, "message": str(exc)[:240]})
                        else:
                            pending_errors.append(str(exc)[:240])
                    else:
                        if focus_sensitive:
                            force_frame = True
                        if isinstance(entry.get("request_id"), int):
                            pending_acks.append({"request_id": entry["request_id"], "ok": True})
            finally:
                observations.append(observation)
            interval = max(controller_interval, pacer.interval(changed, bool(result.get("actions")) or force_frame)) if adaptive else FRAME_INTERVAL_S
            await asyncio.sleep(max(0.05, interval - (time.monotonic() - started)))
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        with contextlib.suppress(Exception):
            await asyncio.to_thread(_post_frame, url, {"errors": [str(exc)[:240]]}, secret)
    finally:
        if manager is not None:
            for observation_id in observations:
                with contextlib.suppress(Exception):
                    await manager.discard_frame_observation(window_id, observation_id)
        if _WORKER_STREAM_TASKS.get(stream_id) is asyncio.current_task():
            _WORKER_STREAM_TASKS.pop(stream_id, None)


def start_worker_stream(stream_id: str, secret: str, window_id: str) -> None:
    if not _WORKER_SERVER or not _WORKER_HEADERS or not stream_id or not secret or not window_id:
        raise ValueError("Desktop worker stream is not configured")
    previous = _WORKER_STREAM_TASKS.pop(stream_id, None)
    if previous:
        previous.cancel()
    _WORKER_STREAM_TASKS[stream_id] = asyncio.create_task(
        _worker_stream_loop(stream_id, secret, window_id), name=f"desktop-stream-{stream_id}"
    )


def stop_worker_stream(stream_id: str) -> None:
    task = _WORKER_STREAM_TASKS.pop(stream_id, None)
    if task:
        task.cancel()
