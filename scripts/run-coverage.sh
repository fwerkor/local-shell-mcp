#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

rm -f .coverage .coverage.* coverage.xml
python -m coverage run --parallel-mode -m pytest -q

export LOCAL_SHELL_MCP_COVERAGE=1
python -m coverage run --parallel-mode scripts/ci-smoke.py --mode http --auth none
python -m coverage run --parallel-mode scripts/ci-smoke.py --mode mcp --auth oauth
python -m coverage run --parallel-mode scripts/ui-pty-smoke.py --tui ui/dist/local-shell-mcp-tui
python -m coverage run --parallel-mode scripts/ui-smoke.py

python -m coverage combine
python -m coverage report
python -m coverage xml
