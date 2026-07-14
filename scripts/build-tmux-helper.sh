#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "usage: $0 OUTPUT_PATH [linux/amd64|linux/arm64]" >&2
  exit 2
fi

output_path=$1
platform=${2:-}
if [[ -z "$platform" ]]; then
  case "$(uname -m)" in
    x86_64|amd64) platform=linux/amd64 ;;
    aarch64|arm64) platform=linux/arm64 ;;
    *) echo "unsupported Linux architecture: $(uname -m)" >&2; exit 2 ;;
  esac
fi

case "$platform" in
  linux/amd64|linux/arm64) ;;
  *) echo "unsupported helper platform: $platform" >&2; exit 2 ;;
esac

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
tmp_dir=$(mktemp -d)
cleanup() { rm -rf "$tmp_dir"; }
trap cleanup EXIT

mkdir -p "$(dirname "$output_path")"
docker buildx build \
  --platform "$platform" \
  --file "$repo_root/scripts/tmux-helper.Dockerfile" \
  --output "type=local,dest=$tmp_dir/out" \
  "$repo_root"
install -m 0755 "$tmp_dir/out/tmux" "$output_path"
"$output_path" -V
