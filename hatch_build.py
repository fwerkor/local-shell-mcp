from __future__ import annotations

import os
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface
from packaging.tags import sys_tags


class CustomBuildHook(BuildHookInterface):
    """Include a generated, platform-native TUI runtime in wheel builds."""

    def initialize(self, version: str, build_data: dict[str, object]) -> None:
        if self.target_name != "wheel":
            return

        executable_name = "local-shell-mcp-tui.exe" if os.name == "nt" else "local-shell-mcp-tui"
        payload = (
            Path(self.root)
            / "src"
            / "local_shell_mcp"
            / "ui_runtime"
            / f"{executable_name}.gz"
        )
        if not payload.is_file():
            # Source-only and sdist builds remain possible without Bun. Official wheel
            # workflows compile the runtime before invoking the wheel builder.
            return

        platform_tag = next(
            tag.platform
            for tag in sys_tags()
            if "manylinux" not in tag.platform and "musllinux" not in tag.platform
        )
        build_data["tag"] = f"py3-none-{platform_tag}"
        build_data["pure_python"] = False
        build_data["force_include"][str(payload)] = (
            f"local_shell_mcp/ui_runtime/{payload.name}"
        )
