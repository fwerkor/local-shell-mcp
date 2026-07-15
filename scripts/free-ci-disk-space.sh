#!/usr/bin/env bash
set -euo pipefail

# GitHub's Ubuntu images contain large SDKs that are unrelated to this Docker
# build. The local-shell-mcp image intentionally includes several development
# toolchains, so reclaim the hosted-runner copies before BuildKit expands them.
sudo rm -rf \
  /usr/local/lib/android \
  /usr/share/dotnet \
  /opt/ghc \
  /usr/local/.ghcup \
  /opt/hostedtoolcache/CodeQL \
  /opt/hostedtoolcache/Ruby \
  /opt/hostedtoolcache/go \
  /opt/hostedtoolcache/node || true
sudo apt-get clean
docker system prune --all --force --volumes || true
df -h /
