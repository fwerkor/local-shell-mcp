#!/usr/bin/env python3
"""Inventory the pinned production sources without implying behavior parity."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def inventory(librechat: Path, agents: Path) -> dict:
    lock = json.loads((ROOT / "ui/workspace/UPSTREAM_LOCK.json").read_text())
    mapped = {(m["repository"], m["path"]): m for m in lock["modules"]}
    roots = {
        "LibreChat": (librechat, ["api/server", "api/models", "api/app/clients", "api/strategies",
            "packages/api/src", "packages/data-provider/src", "packages/data-schemas/src",
            "client/src/components/Chat", "client/src/components/SidePanel/Agents",
            "client/src/hooks/SSE", "client/src/data-provider"]),
        "agents": (agents, ["src"]),
    }
    result = []
    for repository, (checkout, folders) in roots.items():
        paths = set()
        for folder in folders:
            paths.update((checkout / folder).rglob("*"))
        for path in sorted(paths):
            relative = path.relative_to(checkout).as_posix()
            if (not path.is_file() or path.suffix not in {".js", ".cjs", ".mjs", ".ts", ".tsx", ".json"}
                or any(part in {"__tests__", "__mocks__", "__test-utils__", "scripts", "node_modules"}
                       for part in path.relative_to(checkout).parts)
                or any(token in path.name for token in [".test.", ".spec."])
                or path.name.endswith(".d.ts")):
                continue
            mapping = mapped.get((repository, relative))
            result.append({"repository": repository, "path": relative,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "python_lsm": mapping["python_lsm"] if mapping else None,
                "status": mapping["status"] if mapping else "未移植/待源码审计",
                "reviewed_mapping": mapping is not None,
                "difference": mapping["difference"] if mapping else "No verified source-level mapping yet"})
    counts = Counter(item["repository"] for item in result)
    return {"source_lock": "UPSTREAM_LOCK.json", "scope": "Production backend/shared/runtime and retained Agent client source",
        "warning": "Inventory counts are not functional parity or test coverage percentages.",
        "counts": dict(counts), "reviewed_mapping_count": sum(item["reviewed_mapping"] for item in result),
        "modules": result}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("librechat", type=Path)
    parser.add_argument("agents", type=Path)
    args = parser.parse_args()
    result = inventory(args.librechat, args.agents)
    output = ROOT / "ui/workspace/PORTING_INVENTORY.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"Inventoried {len(result['modules'])} production modules; {result['reviewed_mapping_count']} reviewed mappings")


if __name__ == "__main__":
    main()
