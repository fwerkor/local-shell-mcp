#!/usr/bin/env bash
set -euo pipefail

workspace="${LOCAL_SHELL_MCP_WORKSPACE_ROOT:-/workspace}"
allow_full_container="$(printf '%s' "${LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER:-false}" | tr '[:upper:]' '[:lower:]')"
persist_credentials="$(printf '%s' "${LOCAL_SHELL_MCP_PERSISTENT_CREDENTIALS:-true}" | tr '[:upper:]' '[:lower:]')"
credentials_dir="${LOCAL_SHELL_MCP_CREDENTIALS_DIR:-/persist/credentials}"

is_truthy() {
  case "$1" in
    true|1|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

prepare_parent() {
  local path="$1"
  mkdir -p "$(dirname "$path")"
}

link_dir() {
  local source="$1"
  local target="$2"

  prepare_parent "$target"
  mkdir -p "$source"

  if [ -L "$target" ]; then
    local current
    current="$(readlink "$target")"
    if [ "$current" = "$source" ]; then
      return 0
    fi
    rm -f "$target"
  fi

  if [ -e "$target" ]; then
    if [ -d "$target" ]; then
      shopt -s dotglob nullglob
      local entries=("$target"/*)
      if [ "${#entries[@]}" -gt 0 ]; then
        cp -a "${entries[@]}" "$source"/ 2>/dev/null || true
      fi
      rm -rf "$target"
      shopt -u dotglob nullglob
    else
      local backup="${source}.bak.$(date +%s)"
      mv "$target" "$backup"
    fi
  fi

  ln -s "$source" "$target"
}

link_file() {
  local source="$1"
  local target="$2"

  prepare_parent "$target"
  mkdir -p "$(dirname "$source")"

  if [ ! -e "$source" ]; then
    : > "$source"
  fi

  if [ -L "$target" ]; then
    local current
    current="$(readlink "$target")"
    if [ "$current" = "$source" ]; then
      return 0
    fi
    rm -f "$target"
  fi

  if [ -e "$target" ]; then
    if [ -f "$target" ]; then
      if [ ! -e "$source" ]; then
        mv "$target" "$source"
      else
        cat "$target" >> "$source" 2>/dev/null || true
        rm -f "$target"
      fi
    else
      local backup="${source}.bak.$(date +%s)"
      mv "$target" "$backup"
    fi
  fi

  ln -s "$source" "$target"
}

setup_persistent_credentials() {
  local target_user="$1"
  local target_home="$2"

  if ! is_truthy "$persist_credentials"; then
    return 0
  fi

  mkdir -p "$credentials_dir"

  link_dir "$credentials_dir/gh" "$target_home/.config/gh"
  link_file "$credentials_dir/gitconfig" "$target_home/.gitconfig"
  link_file "$credentials_dir/git-credentials" "$target_home/.git-credentials"
  link_dir "$credentials_dir/ssh" "$target_home/.ssh"
  link_file "$credentials_dir/netrc" "$target_home/.netrc"
  link_dir "$credentials_dir/gnupg" "$target_home/.gnupg"

  chmod 700 "$credentials_dir" 2>/dev/null || true
  chmod 700 "$credentials_dir/ssh" "$credentials_dir/gnupg" 2>/dev/null || true
  chmod 600 "$credentials_dir/git-credentials" "$credentials_dir/netrc" 2>/dev/null || true

  if [ "$(id -u)" = "0" ]; then
    chown -R "$target_user:$target_user" "$credentials_dir" "$target_home/.config" "$target_home/.gitconfig" "$target_home/.git-credentials" "$target_home/.ssh" "$target_home/.netrc" "$target_home/.gnupg" 2>/dev/null || true
  fi
}

if [ "$(id -u)" = "0" ]; then
  mkdir -p "$workspace" "$workspace/.local-shell-mcp" "$credentials_dir"
  if is_truthy "$allow_full_container"; then
    setup_persistent_credentials root /root
    exec "$@"
  fi
  setup_persistent_credentials agent /home/agent
  if [ "${LOCAL_SHELL_MCP_CHOWN_WORKSPACE:-true}" != "false" ]; then
    chown -R agent:agent "$workspace"
  fi
  exec runuser -u agent -- "$@"
fi

setup_persistent_credentials "$(id -un)" "${HOME:-/home/agent}"
exec "$@"
