# check=skip=SecretsUsedInArgOrEnv
ARG BUN_VERSION=1.3.14
FROM oven/bun:${BUN_VERSION} AS ui-builder
WORKDIR /source
COPY ui /source/ui
COPY src/local_shell_mcp /source/src/local_shell_mcp
RUN cd /source/ui && bun install --frozen-lockfile && bun run build:web

FROM alpine:3.22 AS tmux-builder
ARG TMUX_VERSION=3.5a
ARG TMUX_SHA256=16216bd0877170dfcc64157085ba9013610b12b082548c7c9542cc0103198951
RUN apk add --no-cache \
    build-base \
    bison \
    ca-certificates \
    curl \
    libevent-dev \
    libevent-static \
    linux-headers \
    ncurses-dev \
    ncurses-static \
    pkgconf
WORKDIR /build
RUN curl -fsSL "https://github.com/tmux/tmux/releases/download/${TMUX_VERSION}/tmux-${TMUX_VERSION}.tar.gz" -o tmux.tar.gz \
  && echo "${TMUX_SHA256}  tmux.tar.gz" | sha256sum -c - \
  && tar -xzf tmux.tar.gz
WORKDIR /build/tmux-${TMUX_VERSION}
RUN LIBEVENT_CFLAGS="$(pkg-config --cflags libevent)" \
    LIBEVENT_LIBS="$(pkg-config --static --libs libevent)" \
    LIBTINFO_CFLAGS="$(pkg-config --cflags ncursesw)" \
    LIBTINFO_LIBS="$(pkg-config --static --libs ncursesw)" \
    LDFLAGS="-static" \
    ./configure \
  && make -j"$(getconf _NPROCESSORS_ONLN)" \
  && strip tmux \
  && ./tmux -V \
  && mkdir -p /out \
  && install -m 0755 tmux /out/tmux

FROM python:3.12-slim-bookworm
ARG TARGETARCH

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LOCAL_SHELL_MCP_WORKSPACE_ROOT=/workspace \
    LOCAL_SHELL_MCP_HOST=0.0.0.0 \
    LOCAL_SHELL_MCP_PORT=8765 \
    LOCAL_SHELL_MCP_PERSISTENT_CREDENTIALS=true \
    LOCAL_SHELL_MCP_CREDENTIALS_DIR=/persist/credentials \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

# Only runtime utilities are installed. Development toolchains, office suites,
# data-science environments, Node.js, and OpenTUI remain opt-in.
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    file \
    gh \
    git \
    jq \
    libmagic1 \
    openssh-client \
    patch \
    passwd \
    ripgrep \
    sqlite3 \
    sudo \
    tmux \
    tree \
    unzip \
    util-linux \
    vim-tiny \
    wget \
    zip \
  && rm -rf /var/lib/apt/lists/*


WORKDIR /app
COPY pyproject.toml hatch_build.py README.md LICENSE /app/
COPY src /app/src
COPY --from=tmux-builder /out/tmux /tmp/local-shell-mcp-tmux
RUN set -eux; \
  case "${TARGETARCH}" in \
    amd64) helper_arch="x86_64" ;; \
    arm64) helper_arch="aarch64" ;; \
    *) echo "Unsupported tmux helper architecture: ${TARGETARCH}" >&2; exit 1 ;; \
  esac; \
  install -d "/app/src/local_shell_mcp/helpers/linux-${helper_arch}"; \
  install -m 0755 /tmp/local-shell-mcp-tmux "/app/src/local_shell_mcp/helpers/linux-${helper_arch}/tmux"; \
  rm -f /tmp/local-shell-mcp-tmux
COPY --from=ui-builder /source/src/local_shell_mcp/ui_static /app/src/local_shell_mcp/ui_static
# Browser automation is optional; neither Playwright nor browser runtimes
# belong in the base image.
RUN pip install --no-cache-dir -e . \
  && rm -rf /root/.cache/pip \
  && python -c "import zstandard" \
  && test -s /app/src/local_shell_mcp/ui_static/index.html \
  && test -s /app/src/local_shell_mcp/ui_static/web.js \
  && test -s /app/src/local_shell_mcp/ui_static/web.css \
  && test ! -e /app/src/local_shell_mcp/ui_runtime \
  && test ! -d "${PLAYWRIGHT_BROWSERS_PATH}"

COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN useradd -m -u 10001 agent \
  && mkdir -p /workspace /workspace/.local-shell-mcp /persist/credentials \
  && echo "agent ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/agent-nopasswd \
  && chmod 0440 /etc/sudoers.d/agent-nopasswd \
  && chown -R agent:agent /workspace /app \
  && chmod +x /usr/local/bin/docker-entrypoint.sh
WORKDIR /workspace

VOLUME ["/workspace", "/persist/credentials"]

EXPOSE 8765
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["local-shell-mcp", "--mode", "mcp"]
