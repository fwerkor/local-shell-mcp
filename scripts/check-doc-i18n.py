#!/usr/bin/env python3
"""Validate that every localized MkDocs page is current with the English source."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
MKDOCS = REPO / "mkdocs.yml"
DOCS = REPO / "docs"
SOURCE_MARKER_RE = re.compile(r"^<!-- i18n-source-sha256: ([0-9a-f]{64}) -->$")

# Exact English fragments from old generated placeholder pages. Technical
# identifiers and product names are intentionally excluded from this list.
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


def i18n_languages(config: dict[str, object]) -> list[dict[str, object]]:
    for plugin in config.get("plugins", []):
        if isinstance(plugin, dict) and "i18n" in plugin:
            value = plugin["i18n"]
            if isinstance(value, dict):
                return list(value.get("languages", []))
    raise RuntimeError("mkdocs.yml does not configure the i18n plugin")


def localized_name(source: Path, locale: str) -> Path:
    return source.with_name(f"{source.stem}.{locale}{source.suffix}")


def strip_source_marker(text: str) -> str:
    lines = text.splitlines()
    if lines and SOURCE_MARKER_RE.fullmatch(lines[0]):
        return "\n".join(lines[1:]) + ("\n" if text.endswith("\n") else "")
    return text


def heading_levels(text: str) -> list[int]:
    return [len(match.group(1)) for match in re.finditer(r"^(#{1,6})\s+", text, re.M)]


def fence_signature(text: str) -> list[str]:
    return re.findall(r"^```([^\s`]*)", text, re.M)


def table_row_count(text: str) -> int:
    return sum(
        1
        for line in text.splitlines()
        if line.lstrip().startswith("|") and line.rstrip().endswith("|")
    )


def link_targets(text: str) -> list[str]:
    return re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", text)


def tool_headings(text: str) -> list[str]:
    return re.findall(r"^###\s+`([^`]+)`\s*$", text, re.M)


def admonition_signature(text: str) -> tuple[list[str], int]:
    kinds = re.findall(r"^\s*!!!\s+(\S+)", text, re.M)
    tabs = len(re.findall(r"^\s*===\s+", text, re.M))
    return kinds, tabs


def nonblank_count(text: str) -> int:
    return sum(bool(line.strip()) for line in text.splitlines())


def main() -> int:
    config = yaml.safe_load(MKDOCS.read_text(encoding="utf-8"))
    nav_titles = collect_nav_titles(config.get("nav", []))
    languages = i18n_languages(config)
    locales = [str(item["locale"]) for item in languages if item.get("locale") != "en"]
    locale_set = set(locales)
    errors: list[str] = []

    for language in languages:
        locale = str(language["locale"])
        if locale == "en":
            continue
        translations = set(language.get("nav_translations", {}))
        missing = sorted(nav_titles - translations)
        if missing:
            errors.append(f"{locale}: missing nav translations: {', '.join(missing)}")

    localized_suffix = re.compile(
        r"\.(?:" + "|".join(re.escape(locale) for locale in sorted(locale_set, key=len, reverse=True)) + r")\.md$"
    )
    sources = sorted(path for path in DOCS.rglob("*.md") if not localized_suffix.search(path.name))

    for source in sources:
        source_text = source.read_text(encoding="utf-8")
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        source_rel = source.relative_to(REPO).as_posix()
        source_nonblank = max(1, nonblank_count(source_text))
        source_headings = heading_levels(source_text)
        source_fences = fence_signature(source_text)
        source_tables = table_row_count(source_text)
        source_links = link_targets(source_text)
        source_tool_headings = tool_headings(source_text)
        source_admonitions = admonition_signature(source_text)

        for locale in locales:
            localized = localized_name(source, locale)
            rel = localized.relative_to(REPO).as_posix()
            if not localized.exists():
                errors.append(f"{rel}: missing localized page for {source_rel}")
                continue

            raw = localized.read_text(encoding="utf-8")
            first_line = raw.splitlines()[0] if raw.splitlines() else ""
            marker = SOURCE_MARKER_RE.fullmatch(first_line)
            if not marker:
                errors.append(f"{rel}: missing i18n source hash marker")
            elif marker.group(1) != source_hash:
                errors.append(
                    f"{rel}: stale translation; source hash {marker.group(1)} != current {source_hash}"
                )

            text = strip_source_marker(raw)
            if text.strip() == source_text.strip():
                errors.append(f"{rel}: page is an untranslated copy of English")

            for phrase in PLACEHOLDER_PHRASES:
                if phrase in text:
                    errors.append(f"{rel}: old placeholder English phrase remains: {phrase}")
                    break

            if heading_levels(text) != source_headings:
                errors.append(f"{rel}: heading-level structure differs from {source_rel}")
            if fence_signature(text) != source_fences:
                errors.append(f"{rel}: fenced-code structure differs from {source_rel}")
            if table_row_count(text) != source_tables:
                errors.append(f"{rel}: Markdown table row count differs from {source_rel}")
            if link_targets(text) != source_links:
                errors.append(f"{rel}: Markdown link targets differ from {source_rel}")
            if tool_headings(text) != source_tool_headings:
                errors.append(f"{rel}: tool heading sequence differs from {source_rel}")
            if admonition_signature(text) != source_admonitions:
                errors.append(f"{rel}: admonition/tab structure differs from {source_rel}")

            localized_nonblank = nonblank_count(text)
            if localized_nonblank < max(4, int(source_nonblank * 0.85)):
                errors.append(
                    f"{rel}: localized page is too short "
                    f"({localized_nonblank} nonblank lines vs {source_nonblank} source lines)"
                )

    # Localized pages must also have an English counterpart. This catches stale
    # pages left behind after an English page is renamed or removed.
    for path in DOCS.rglob("*.md"):
        match = localized_suffix.search(path.name)
        if not match:
            continue
        locale = next((value for value in locales if path.name.endswith(f".{value}.md")), None)
        if locale is None:
            continue
        source = path.with_name(path.name[: -len(f".{locale}.md")] + ".md")
        if not source.exists():
            errors.append(f"{path.relative_to(REPO)}: localized page has no English source")

    if errors:
        print("Documentation i18n check failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"Documentation i18n check passed: {len(sources)} pages x {len(locales)} locales.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
