#!/usr/bin/env python3
"""Snapshot the pinned LibreChat Artifact prompts for the Python-only runtime.

Run at port/update time, not in production. No JavaScript or dependency is
executed; the source templates are static and component records are literals.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

PROMPTS = "packages/api/src/prompts/artifacts/index.ts"
COMPONENTS = "packages/api/src/prompts/artifacts/components.ts"


def literal(source: str, offset: int) -> tuple[str, int]:
    index = offset
    while source[index].isspace():
        index += 1
    delimiter = source[index]
    if delimiter not in {"'", '"', "`"}:
        raise ValueError(f"Unsupported component literal at offset {index}")
    index += 1
    output: list[str] = []
    while index < len(source):
        char = source[index]
        if char == delimiter:
            return "".join(output), index + 1
        if char == "\\":
            index += 1
            if index == len(source):
                raise ValueError("Unterminated escape")
            escaped = source[index]
            if escaped in {"\\", "'", '"', "`"}:
                char = escaped
            elif escaped == "n":
                char = "\n"
            elif escaped == "r":
                char = "\r"
            elif escaped == "t":
                char = "\t"
            else:
                raise ValueError(f"Unhandled upstream template escape: {escaped}")
        output.append(char)
        index += 1
    raise ValueError("Unterminated JavaScript literal")


def js_dedent(value: str) -> str:
    """Pinned dedent template-tag indentation, without interpolated values."""
    lines = value.split("\n")
    indents = [len(match.group(1)) for line in lines if (match := re.match(r"^(\s+)\S+", line))]
    if indents:
        indent = min(indents)
        value = "\n".join(line[indent:] if line[:1] in {" ", "\t"} else line for line in lines)
    return value.strip().replace(r"\n", "\n")


def snapshot(upstream: Path) -> dict:
    prompt_source = (upstream / PROMPTS).read_text(encoding="utf-8")
    component_source = (upstream / COMPONENTS).read_text(encoding="utf-8")
    prompts = {}
    for label, symbol in (("anthropic", "artifactsPrompt"), ("openai", "artifactsOpenAIPrompt")):
        marker = f"const {symbol} = dedent"
        begin = prompt_source.index(marker) + len(marker)
        value, end = literal(prompt_source, begin)
        if prompt_source[end] != ";":
            raise ValueError(f"Unexpected extra content in {symbol}")
        prompts[label] = js_dedent(value)
    components = []
    for match in re.finditer(r"\bcomponentName\s*:\s*[\'\"\x60]", component_source):
        name, end = literal(component_source, match.end() - 1)
        imported = re.search(r"\bimportDocs\s*:", component_source[end:])
        if imported is None:
            raise ValueError(f"Missing importDocs for {name}")
        import_docs, end = literal(component_source, end + imported.end())
        usage = re.search(r"\busageDocs\s*:", component_source[end:])
        if usage is None:
            raise ValueError(f"Missing usageDocs for {name}")
        usage_docs, _ = literal(component_source, end + usage.end())
        components.append({"name": name, "import": import_docs, "usage": usage_docs})
    # JS object spreads overwrite duplicate component keys without reordering them.
    deduplicated = {item["name"]: item for item in components}
    if len(components) != 47 or len(deduplicated) != 33:
        raise ValueError("Pinned Shadcn component list was not parsed completely")
    components = list(deduplicated.values())
    return {
        "sourceCommit": "e8f3be08623663d4ad7f7241e693c94469b63bb0",
        "sourceSha256": {
            path: hashlib.sha256((upstream / path).read_bytes()).hexdigest()
            for path in (PROMPTS, COMPONENTS)
        },
        "prompts": prompts,
        "components": components,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("src/local_shell_mcp/webui/artifact_prompt_snapshot.json"),
    )
    args = parser.parse_args()
    data = snapshot(args.upstream)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Exported {len(data['components'])} upstream components")


if __name__ == "__main__":
    main()
