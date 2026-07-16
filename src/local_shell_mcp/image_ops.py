from __future__ import annotations

from dataclasses import dataclass

from .fs_ops import relative_display, resolve_path

MAX_VIEW_IMAGE_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class ImageFile:
    path: str
    data: bytes
    format: str
    mime_type: str
    size: int


def assert_view_image_size(size: int) -> None:
    if size <= 0:
        raise ValueError("Image file is empty")
    if size > MAX_VIEW_IMAGE_BYTES:
        raise ValueError(
            f"Refusing image of {size} bytes; max is {MAX_VIEW_IMAGE_BYTES}"
        )


def detect_image_type(header: bytes) -> tuple[str, str]:
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", "image/png"
    if header.startswith(b"\xff\xd8\xff"):
        return "jpeg", "image/jpeg"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "gif", "image/gif"
    if len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "webp", "image/webp"
    raise ValueError("Unsupported image format; expected PNG, JPEG, GIF, or WebP")


def read_image(path: str) -> ImageFile:
    resolved = resolve_path(path, must_exist=True)
    if not resolved.is_file():
        raise IsADirectoryError(str(resolved))

    expected_size = resolved.stat().st_size
    assert_view_image_size(expected_size)
    with resolved.open("rb") as handle:
        data = handle.read(MAX_VIEW_IMAGE_BYTES + 1)
    assert_view_image_size(len(data))
    image_format, mime_type = detect_image_type(data[:16])

    return ImageFile(
        path=relative_display(resolved),
        data=data,
        format=image_format,
        mime_type=mime_type,
        size=len(data),
    )
