#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

rm -f .coverage .coverage.* coverage.json coverage.xml
export LOCAL_SHELL_MCP_COVERAGE=1
python -m coverage run --parallel-mode -m pytest -q

python scripts/ci-smoke.py --mode http --auth none
python scripts/ci-smoke.py --mode mcp --auth oauth
python scripts/ui-pty-smoke.py --tui ui/dist/local-shell-mcp-tui
python scripts/ui-smoke.py

python -m coverage combine
python -m coverage report
python -m coverage json
python -m coverage xml
python scripts/check-coverage.py coverage.json
