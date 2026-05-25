#!/usr/bin/env bash
set -euo pipefail

workspace="${LOCAL_SHELL_MCP_WORKSPACE_ROOT:-/workspace}"

if [ "$(id -u)" = "0" ]; then
  mkdir -p "$workspace" "$workspace/.local-shell-mcp"
  if [ "${LOCAL_SHELL_MCP_CHOWN_WORKSPACE:-true}" != "false" ]; then
    chown -R agent:agent "$workspace"
  fi
  exec runuser -u agent -- "$@"
fi

exec "$@"
