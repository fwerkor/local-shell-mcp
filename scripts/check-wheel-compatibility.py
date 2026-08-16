#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import re
import struct
import zipfile
from pathlib import Path

MANYLINUX_GLIBC_MAX = (2, 17)
LINUX_TARGETS = {
    "linux-x86_64": ("manylinux_2_17_x86_64", 62),
    "linux-aarch64": ("manylinux_2_17_aarch64", 183),
}
OTHER_TARGETS = {
    "macos-x86_64": ("macosx_", "x86_64"),
    "macos-aarch64": ("macosx_", "arm64"),
    "windows-x86_64": ("win_amd64", None),
}


def normalize_target(value: str) -> str:
    return value.removeprefix("wheel-")


def wheel_tags(archive: zipfile.ZipFile) -> set[str]:
    metadata_name = next(name for name in archive.namelist() if name.endswith(".dist-info/WHEEL"))
    metadata = archive.read(metadata_name).decode("utf-8")
    return {
        line.removeprefix("Tag: ").strip()
        for line in metadata.splitlines()
        if line.startswith("Tag: ")
    }


def embedded_tui(archive: zipfile.ZipFile) -> bytes:
    payload_name = next(
        name
        for name in archive.namelist()
        if name.endswith("local_shell_mcp/ui_runtime/local-shell-mcp-tui.gz")
    )
    return gzip.decompress(archive.read(payload_name))


def elf_machine(binary: bytes) -> int:
    if binary[:4] != b"\x7fELF":
        raise ValueError("embedded Linux TUI is not an ELF executable")
    if len(binary) < 20:
        raise ValueError("embedded Linux TUI has a truncated ELF header")
    byte_order = {1: "<", 2: ">"}.get(binary[5])
    if byte_order is None:
        raise ValueError("embedded Linux TUI has an unknown ELF byte order")
    return struct.unpack_from(f"{byte_order}H", binary, 18)[0]


def glibc_versions(binary: bytes) -> set[tuple[int, int]]:
    return {
        (int(major), int(minor))
        for major, minor in re.findall(rb"GLIBC_(\d+)\.(\d+)", binary)
    }


def check_linux(target: str, wheel: Path, archive: zipfile.ZipFile, tags: set[str]) -> None:
    platform_tag, expected_machine = LINUX_TARGETS[target]
    expected_tag = f"py3-none-{platform_tag}"
    if tags != {expected_tag}:
        raise SystemExit(f"{wheel.name}: expected wheel tag {expected_tag}, got {sorted(tags)}")
    if platform_tag not in wheel.name:
        raise SystemExit(f"{wheel.name}: filename does not contain {platform_tag}")

    binary = embedded_tui(archive)
    machine = elf_machine(binary)
    if machine != expected_machine:
        raise SystemExit(
            f"{wheel.name}: embedded TUI ELF machine {machine} does not match {expected_machine}"
        )

    versions = glibc_versions(binary)
    if not versions:
        raise SystemExit(f"{wheel.name}: could not determine embedded TUI GLIBC requirements")
    highest = max(versions)
    if highest > MANYLINUX_GLIBC_MAX:
        raise SystemExit(
            f"{wheel.name}: embedded TUI requires GLIBC {highest[0]}.{highest[1]}, "
            f"above the manylinux_2_17 baseline"
        )
    print(
        f"{wheel.name}: {expected_tag}; embedded TUI GLIBC <= "
        f"{highest[0]}.{highest[1]}"
    )


def check_other(target: str, wheel: Path, tags: set[str]) -> None:
    platform_prefix, architecture = OTHER_TARGETS[target]
    if len(tags) != 1:
        raise SystemExit(f"{wheel.name}: expected one wheel tag, got {sorted(tags)}")
    tag = next(iter(tags))
    if not tag.startswith(f"py3-none-{platform_prefix}"):
        raise SystemExit(f"{wheel.name}: unexpected wheel tag {tag}")
    if architecture and architecture not in tag:
        raise SystemExit(f"{wheel.name}: expected architecture {architecture} in {tag}")
    print(f"{wheel.name}: {tag}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", help="release target, optionally prefixed with wheel-")
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()

    target = normalize_target(args.target)
    if target not in LINUX_TARGETS | OTHER_TARGETS:
        raise SystemExit(f"unsupported wheel target: {target}")
    if not args.wheel.is_file():
        raise SystemExit(f"wheel not found: {args.wheel}")

    with zipfile.ZipFile(args.wheel) as archive:
        tags = wheel_tags(archive)
        if target in LINUX_TARGETS:
            check_linux(target, args.wheel, archive, tags)
        else:
            check_other(target, args.wheel, tags)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
