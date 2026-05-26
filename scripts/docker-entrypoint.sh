#!/usr/bin/env bash
set -euo pipefail

workspace="${LOCAL_SHELL_MCP_WORKSPACE_ROOT:-/workspace}"
allow_full_container="$(printf '%s' "${LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER:-false}" | tr '[:upper:]' '[:lower:]')"

if [ "$(id -u)" = "0" ]; then
  mkdir -p "$workspace" "$workspace/.local-shell-mcp"
  if [ "$allow_full_container" = "true" ] || [ "$allow_full_container" = "1" ] || [ "$allow_full_container" = "yes" ] || [ "$allow_full_container" = "on" ]; then
    exec "$@"
  fi
  if [ "${LOCAL_SHELL_MCP_CHOWN_WORKSPACE:-true}" != "false" ]; then
    chown -R agent:agent "$workspace"
  fi
  exec runuser -u agent -- "$@"
fi

exec "$@"
