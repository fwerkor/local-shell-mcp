#!/usr/bin/env python3
"""Validate the chat WebUI's lazy-loaded translation catalogs."""
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "ui/workspace/client/src"
LOCALES = ROOT / "locales"
REPO = Path(__file__).resolve().parents[1]
TOKEN = re.compile(r"\{\{[^{}]+\}\}|</?\d+>|</?[a-zA-Z][^>]*>")
# Product, API and platform labels intentionally keep their original names.
UNCHANGED_LABELS = {
    "com_ui_code_environment_shell_posix",
    "com_ui_web_search_scraper_keenable",
    "com_ui_web_search_scraper_serper",
    "com_ui_web_search_scraper_tavily",
    "com_lsm_channel_protocol_openai",
}
# Distinct actions and states should not collapse into the same label.
DISTINCT_STATES = (
    ("enabled", "disabled"), ("enable", "disable"), ("on", "off"),
    ("open", "close"), ("read", "write"), ("allow", "deny"),
    ("saved", "saving"), ("running", "completed"), ("running", "stopped"),
    ("running", "failed"), ("success", "error"), ("ascending", "descending"),
    ("add", "remove"), ("start", "stop"), ("show", "hide"), ("yes", "no"),
    ("public", "private"), ("accept", "reject"), ("checked", "checking"),
    ("deleted", "deleting"), ("expanded", "collapsed"), ("expand", "collapse"),
    ("select_all", "deselect_all"), ("connect", "disconnect"),
    ("connected", "disconnected"), ("manual", "auto"), ("revoke", "grant"),
    ("copy", "copied"),
)


def quality_findings(english: dict[str, str], catalog: dict[str, str]) -> list[str]:
    """Heuristics only: flag likely fallbacks and indistinguishable controls."""
    findings = []
    keys = english.keys() & catalog.keys()
    for key in sorted(keys):
        value = catalog[key]
        if not isinstance(value, str):
            continue
        # Exclude short labels (often shared loanwords) and language endonyms.
        if (value == english[key] and key not in UNCHANGED_LABELS
                and not key.startswith("com_nav_lang_")
                and len(TOKEN.sub("", value).split()) >= 3
                and re.search(r"[a-zA-Z]{3,}", value)):
            findings.append(f"{key}: possible untranslated English text")
        for first, second in DISTINCT_STATES:
            if not key.endswith("_" + first):
                continue
            other = key[:-len(first)] + second
            if (other in keys and isinstance(catalog[other], str)
                    and english[key].strip().casefold() != english[other].strip().casefold()
                    and value.strip().casefold() == catalog[other].strip().casefold()):
                findings.append(f"{key} / {other}: identical labels for distinct states")
    return findings



def read_catalog(path: Path) -> dict[str, str]:
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{path}: duplicate key {key}")
            result[key] = value
        return result

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)


def report_unreferenced(keys: set[str]) -> None:
    """Report candidates, not proof of dead keys: some labels come from API data."""
    result = subprocess.run(
        ["git", "grep", "-I", "-h", "-E", "com_|chat_direction", "--",
         ":!**/translation.json", ":!ui/workspace/PORTING_INVENTORY.json"],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8",
        errors="replace", check=False,
    )
    if result.returncode not in (0, 1):
        print("Skipping translation reference audit: Git search unavailable", file=sys.stderr)
        return
    tokens = set(re.findall(r"[A-Za-z0-9_]+", result.stdout))
    plural = re.compile(r"_(?:zero|one|two|few|many|other|plural|\d+)$")
    # Dynamic variable names, machine permission levels, API categories/errors.
    dynamic = ("com_ui_special_var_", "com_lsm_agent_machine_",
               "com_agents_category_", "com_ui_agent_category_", "com_error_")
    candidates = sorted(
        key for key in keys
        if key not in tokens and plural.sub("", key) not in tokens
        and not key.startswith(dynamic)
    )
    if candidates:
        print(f"Translation audit: {len(candidates)} keys without direct references "
              "(review dynamic/API consumers before removal)")
        print("  " + ", ".join(candidates))


def main() -> int:
    english = read_catalog(LOCALES / "en/translation.json")
    source = (LOCALES / "i18n.ts").read_text(encoding="utf-8")
    locales = set(re.findall(r"'([^']+)'", source.split("export const supportedLocales = [", 1)[1].split("]", 1)[0]))
    loaders = set(re.findall(r"import\('\./([^/]+)/translation\.json'\)", source))
    files = {path.parent.name: path for path in LOCALES.glob("*/translation.json")}
    errors = []
    quality = []
    if set(files) != locales or loaders != locales - {"en"}:
        errors.append("Locale catalogs, supportedLocales and lazy loaders are out of sync")
    for locale, path in sorted(files.items()):
        catalog = read_catalog(path)
        if locale != "en":
            quality.extend(f"{locale}: {finding}" for finding in quality_findings(english, catalog))
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
    if quality:
        print(f"Translation quality audit: {len(quality)} candidates (review in context)")
        print("\n".join(f"  {finding}" for finding in quality))
    else:
        print("Translation quality audit: no fallback or state-collision candidates")
    report_unreferenced(set(english))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
