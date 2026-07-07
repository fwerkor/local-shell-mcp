#!/usr/bin/env python3
"""Validate localized MkDocs pages for common i18n regressions."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
MKDOCS = REPO / "mkdocs.yml"
DOCS = REPO / "docs"

# These exact phrases came from the previous generated placeholder pages and
# should not appear in localized documents. Product names and tool identifiers
# are intentionally not treated as errors.
PLACEHOLDER_PHRASES = (
    "Runtime defines how the server process runs",
    "Use this page when the selected Runtime or Client path matches the title",
    "Choose the Runtime installation page first",
    "confirms runtime settings and workspace",
    "Prefer small, verifiable steps",
    "## Documentation paths",
    "## Core architecture",
    "## Key safety rule",
    "localized version",
    "Tool names, parameter names",
    "Search workspace files and return ChatGPT connector-compatible results",
    "**Overview.**",
    "**Inputs.**",
    "**Returns.**",
    "Common combinations",
)

CHINESE_PLACEHOLDER_PHRASES = (
    "Clone the repository",
    "Use this MCP endpoint",
    "Recommended first prompt",
    "Remote workers connect outbound",
    "Basic flow:",
    "Mandatory rules:",
)

FULL_TRANSLATION_LOCALES = {"zh", "zh-Hant"}
FULL_TRANSLATION_EXCLUDES = {
    "docs/reference/tools.zh.md",
    "docs/reference/tools.zh-Hant.md",
}


def collect_nav_titles(items: Iterable[object]) -> set[str]:
    titles: set[str] = set()
    for item in items:
        if isinstance(item, str):
            titles.add(item)
            continue
        if not isinstance(item, dict):
            continue
        for title, value in item.items():
            titles.add(str(title))
            if isinstance(value, list):
                titles.update(collect_nav_titles(value))
    return titles


def main() -> int:
    config = yaml.safe_load(MKDOCS.read_text(encoding="utf-8"))
    nav_titles = collect_nav_titles(config.get("nav", []))
    languages = config["plugins"][1]["i18n"]["languages"]

    errors: list[str] = []
    localized_locales: set[str] = set()

    for language in languages:
        locale = language["locale"]
        if locale == "en":
            continue
        localized_locales.add(locale)
        translations = set(language.get("nav_translations", {}))
        missing = sorted(nav_titles - translations)
        if missing:
            errors.append(f"{locale}: missing nav translations: {', '.join(missing)}")

    for path in DOCS.rglob("*.md"):
        parts = path.name.split(".")
        if len(parts) < 3 or parts[-2] not in localized_locales:
            continue
        text = path.read_text(encoding="utf-8")
        for phrase in PLACEHOLDER_PHRASES:
            if phrase in text:
                rel = path.relative_to(REPO)
                errors.append(f"{rel}: placeholder English phrase remains: {phrase}")
                break

        locale = parts[-2]
        rel = path.relative_to(REPO).as_posix()
        if locale in FULL_TRANSLATION_LOCALES:
            for phrase in CHINESE_PLACEHOLDER_PHRASES:
                if phrase in text:
                    errors.append(f"{rel}: untranslated Chinese page phrase remains: {phrase}")
                    break

        if locale in FULL_TRANSLATION_LOCALES and rel not in FULL_TRANSLATION_EXCLUDES:
            source_name = ".".join(parts[:-2] + [parts[-1]])
            source_path = path.with_name(source_name)
            if source_path.exists():
                source_lines = [line for line in source_path.read_text(encoding="utf-8").splitlines() if line.strip()]
                localized_lines = [line for line in text.splitlines() if line.strip()]
                if len(localized_lines) < max(4, int(len(source_lines) * 0.85)):
                    errors.append(
                        f"{rel}: localized page is too short "
                        f"({len(localized_lines)} nonblank lines vs {len(source_lines)} source lines)"
                    )

    if errors:
        print("Documentation i18n check failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Documentation i18n check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
