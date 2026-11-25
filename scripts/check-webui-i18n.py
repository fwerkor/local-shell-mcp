#!/usr/bin/env python3
"""Validate the chat WebUI's lazy-loaded translation catalogs."""
from collections import Counter
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1] / "ui/workspace/client/src"
LOCALES = ROOT / "locales"
TOKEN = re.compile(r"\{\{[^{}]+\}\}|</?\d+>|</?[a-zA-Z][^>]*>")


def read_catalog(path: Path) -> dict[str, str]:
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{path}: duplicate key {key}")
            result[key] = value
        return result

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)


def main() -> int:
    english = read_catalog(LOCALES / "en/translation.json")
    source = (LOCALES / "i18n.ts").read_text(encoding="utf-8")
    locales = set(re.findall(r"'([^']+)'", source.split("export const supportedLocales = [", 1)[1].split("]", 1)[0]))
    loaders = set(re.findall(r"import\('\./([^/]+)/translation\.json'\)", source))
    files = {path.parent.name: path for path in LOCALES.glob("*/translation.json")}
    errors = []
    if set(files) != locales or loaders != locales - {"en"}:
        errors.append("Locale catalogs, supportedLocales and lazy loaders are out of sync")
    for locale, path in sorted(files.items()):
        catalog = read_catalog(path)
        missing = set(english) - set(catalog)
        extra = set(catalog) - set(english)
        if missing or extra:
            errors.append(f"{locale}: missing={sorted(missing)}, extra={sorted(extra)}")
        for key in english.keys() & catalog.keys():
            value = catalog[key]
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{locale}: empty or invalid value for {key}")
            elif Counter(TOKEN.findall(value)) != Counter(TOKEN.findall(english[key])):
                errors.append(f"{locale}: interpolation/markup mismatch for {key}")
            elif re.search(r"ZXQPH\d+QXZ", value, re.I):
                errors.append(f"{locale}: untranslated placeholder marker in {key}")
            elif "librechat" in value.casefold():
                errors.append(f"{locale}: stale product name in {key}")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Validated {len(files)} WebUI locale catalogs × {len(english)} messages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
