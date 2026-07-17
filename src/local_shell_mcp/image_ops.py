from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps

from .fs_ops import relative_display, resolve_path

MAX_VIEW_IMAGE_BYTES = 20 * 1024 * 1024
MAX_PREVIEW_SOURCE_PIXELS = 25_000_000


@dataclass(frozen=True)
class ImageFile:
    path: str
    data: bytes
    format: str
    mime_type: str
    size: int


@dataclass(frozen=True)
class ImagePreview:
    rgba: bytes
    width: int
    height: int
    cell_width: int
    cell_height: int
    original_width: int
    original_height: int


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


def make_image_preview(
    image: ImageFile,
    max_columns: int,
    max_rows: int,
) -> ImagePreview:
    """Decode a bounded first-frame RGBA thumbnail for OpenTUI's pixel buffer."""

    columns = max(2, min(int(max_columns), 200))
    rows = max(1, min(int(max_rows), 100))
    # OpenTUI's supersampled renderer consumes a 2x2 source-pixel block for
    # each terminal cell, so the source raster may be twice the cell bounds
    # in both dimensions.
    max_pixel_width = columns * 2
    max_pixel_height = rows * 2

    with Image.open(BytesIO(image.data)) as opened:
        opened.seek(0)
        oriented = ImageOps.exif_transpose(opened)
        original_width, original_height = oriented.size
        if original_width <= 0 or original_height <= 0:
            raise ValueError("Image has invalid dimensions")
        if original_width * original_height > MAX_PREVIEW_SOURCE_PIXELS:
            raise ValueError(
                "Refusing to decode image preview with "
                f"{original_width * original_height} pixels; max is {MAX_PREVIEW_SOURCE_PIXELS}"
            )
        frame = oriented.convert("RGBA")
        frame.thumbnail(
            (max_pixel_width, max_pixel_height),
            Image.Resampling.LANCZOS,
            reducing_gap=3.0,
        )
        width, height = frame.size
        rgba = frame.tobytes()

    return ImagePreview(
        rgba=rgba,
        width=width,
        height=height,
        # Keep a two-column minimum for the preview render box while reporting
        # the actual 2x2 supersampling footprint for normal images.
        cell_width=max(2, (width + 1) // 2),
        cell_height=(height + 1) // 2,
        original_width=original_width,
        original_height=original_height,
    )
