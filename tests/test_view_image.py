from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

import pytest
from mcp.types import CallToolResult, ImageContent, TextContent
from PIL import Image

import local_shell_mcp.tools as tools
from local_shell_mcp.image_ops import (
    MAX_VIEW_IMAGE_BYTES,
    assert_view_image_size,
    detect_image_type,
    make_image_preview,
    read_image,
)
from local_shell_mcp.settings import get_settings

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _configure(tmp_path: Path, monkeypatch, *, remote_enabled: bool = True) -> None:
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", str(remote_enabled).lower())
    get_settings.cache_clear()


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (b"\x89PNG\r\n\x1a\nrest", ("png", "image/png")),
        (b"\xff\xd8\xffrest", ("jpeg", "image/jpeg")),
        (b"GIF87arest", ("gif", "image/gif")),
        (b"GIF89arest", ("gif", "image/gif")),
        (b"RIFF\x00\x00\x00\x00WEBPrest", ("webp", "image/webp")),
    ],
)
def test_detect_image_type(header, expected):
    assert detect_image_type(header) == expected


def test_make_image_preview_returns_bounded_rgba(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    buffer = BytesIO()
    Image.new("RGB", (100, 50), (12, 34, 56)).save(buffer, format="PNG")
    (tmp_path / "wide.png").write_bytes(buffer.getvalue())

    preview = make_image_preview(read_image("wide.png"), max_columns=12, max_rows=4)

    assert (preview.original_width, preview.original_height) == (100, 50)
    assert (preview.width, preview.height) == (24, 6)
    assert (preview.cell_width, preview.cell_height) == (12, 3)
    assert preview.cell_width <= 12
    assert preview.cell_height <= 4
    assert len(preview.rgba) == 24 * 6 * 4


def test_make_image_preview_compensates_for_terminal_cell_aspect(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    buffer = BytesIO()
    Image.new("RGB", (474, 316), (12, 34, 56)).save(buffer, format="WEBP")
    (tmp_path / "landscape.webp").write_bytes(buffer.getvalue())

    preview = make_image_preview(
        read_image("landscape.webp"),
        max_columns=61,
        max_rows=34,
        cell_height_to_width=2.75,
    )

    assert (preview.width, preview.height) == (122, 29)
    assert (preview.cell_width, preview.cell_height) == (61, 15)
    rendered_ratio = preview.cell_width / (preview.cell_height * 2.75)
    source_ratio = preview.original_width / preview.original_height
    assert rendered_ratio == pytest.approx(source_ratio, rel=0.02)


def test_image_validation_errors(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="empty"):
        assert_view_image_size(0)
    with pytest.raises(ValueError, match="max"):
        assert_view_image_size(MAX_VIEW_IMAGE_BYTES + 1)
    with pytest.raises(ValueError, match="Unsupported"):
        detect_image_type(b"not an image")

    (tmp_path / "folder").mkdir()
    with pytest.raises(IsADirectoryError):
        read_image("folder")

    oversized = tmp_path / "oversized.png"
    oversized.write_bytes(b"\x89PNG\r\n\x1a\n")
    with oversized.open("r+b") as handle:
        handle.truncate(MAX_VIEW_IMAGE_BYTES + 1)
    with pytest.raises(ValueError, match="max"):
        read_image("oversized.png")


@pytest.mark.asyncio
async def test_view_image_returns_native_mcp_image_content(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    (tmp_path / "pixel.png").write_bytes(PNG)

    result = await tools.build_mcp().call_tool("view_image", {"path": "pixel.png"})

    assert isinstance(result, CallToolResult)
    assert result.isError is False
    assert result.structuredContent == {
        "ok": True,
        "path": "pixel.png",
        "machine": None,
        "mime_type": "image/png",
        "bytes": len(PNG),
        "message": "",
        "error_type": None,
    }
    image = next(item for item in result.content if isinstance(item, ImageContent))
    text = next(item for item in result.content if isinstance(item, TextContent))
    assert image.mimeType == "image/png"
    assert base64.b64decode(image.data) == PNG
    assert "pixel.png" in text.text


@pytest.mark.asyncio
async def test_view_image_reuses_remote_transfer_protocol(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    remote_calls = []
    staged_paths = []

    async def fake_remote_transfer_data(machine, tool, args, timeout_s=None):
        remote_calls.append((machine, tool, args, timeout_s))
        assert tool == "transfer_stat"
        return {
            "path": "images/remote.png",
            "type": "file",
            "size": len(PNG),
        }

    async def fake_copy_remote_file_to_local(
        machine,
        source_path,
        destination_path,
        overwrite=True,
        chunk_size=None,
    ):
        assert machine == "node"
        assert source_path == "images/remote.png"
        assert overwrite is True
        assert chunk_size is None
        destination = tools.resolve_path(destination_path)
        destination.write_bytes(PNG)
        staged_paths.append(destination)
        return {"bytes": len(PNG)}

    monkeypatch.setattr(tools, "_remote_transfer_data", fake_remote_transfer_data)
    monkeypatch.setattr(
        tools,
        "_copy_remote_file_to_local",
        fake_copy_remote_file_to_local,
    )

    result = await tools.build_mcp().call_tool(
        "view_image",
        {"path": "images/remote.png", "machine": "node"},
    )

    assert isinstance(result, CallToolResult)
    assert result.isError is False
    assert result.structuredContent["machine"] == "node"
    assert result.structuredContent["path"] == "images/remote.png"
    assert [call[1] for call in remote_calls] == ["transfer_stat"]
    assert staged_paths and all(not path.exists() for path in staged_paths)


@pytest.mark.asyncio
async def test_view_image_returns_structured_errors(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    (tmp_path / "plain.txt").write_text("not an image", encoding="utf-8")

    invalid = await tools.build_mcp().call_tool("view_image", {"path": "plain.txt"})
    assert isinstance(invalid, CallToolResult)
    assert invalid.isError is True
    assert invalid.structuredContent["ok"] is False
    assert invalid.structuredContent["error_type"] == "ValueError"

    _configure(tmp_path, monkeypatch, remote_enabled=False)
    disabled = await tools.build_mcp().call_tool(
        "view_image",
        {"path": "remote.png", "machine": "node"},
    )
    assert isinstance(disabled, CallToolResult)
    assert disabled.isError is True
    assert "disabled" in disabled.structuredContent["message"]
