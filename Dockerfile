# check=skip=SecretsUsedInArgOrEnv
ARG BUN_VERSION=1.3.14
FROM oven/bun:${BUN_VERSION} AS ui-builder
WORKDIR /source
COPY ui /source/ui
COPY src/local_shell_mcp /source/src/local_shell_mcp
RUN cd /source/ui && bun install --frozen-lockfile && bun run build

ARG PLAYWRIGHT_VERSION=1.59.0
FROM mcr.microsoft.com/playwright/python:v${PLAYWRIGHT_VERSION}-noble
ARG PLAYWRIGHT_VERSION
ARG TARGETARCH
ARG YAZI_VERSION=26.5.6

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LOCAL_SHELL_MCP_WORKSPACE_ROOT=/workspace \
    LOCAL_SHELL_MCP_HOST=0.0.0.0 \
    LOCAL_SHELL_MCP_PORT=8765 \
    LOCAL_SHELL_MCP_PERSISTENT_CREDENTIALS=true \
    LOCAL_SHELL_MCP_CREDENTIALS_DIR=/persist/credentials

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    sudo \
    curl \
    git \
    gh \
    jq \
    openssh-client \
    patch \
    ripgrep \
    tmux \
    tree \
    vim-tiny \
    wget \
    zip \
    unzip \
    build-essential \
    autoconf \
    automake \
    clang \
    cmake \
    gdb \
    lldb \
    libtool \
    make \
    ninja-build \
    pkg-config \
    python3-dev \
    python3-pip \
    python3-venv \
    pipx \
    nodejs \
    npm \
    golang-go \
    rustc \
    cargo \
    openjdk-21-jdk \
    maven \
    gradle \
    ruby-full \
    php-cli \
    php-curl \
    php-dev \
    php-mbstring \
    php-xml \
    composer \
    perl \
    lua5.4 \
    luarocks \
    r-base \
    shellcheck \
    sqlite3 \
    file \
    libmagic1 \
    pandoc \
    poppler-utils \
    tesseract-ocr \
    libreoffice-calc \
    libreoffice-impress \
    libreoffice-writer \
  && rm -rf /var/lib/apt/lists/*

RUN set -eux; \
  case "${TARGETARCH}" in \
    amd64) yazi_target="x86_64-unknown-linux-gnu" ;; \
    arm64) yazi_target="aarch64-unknown-linux-gnu" ;; \
    *) echo "Unsupported Yazi architecture: ${TARGETARCH}" >&2; exit 1 ;; \
  esac; \
  curl -fsSL "https://github.com/sxyazi/yazi/releases/download/v${YAZI_VERSION}/yazi-${yazi_target}.zip" -o /tmp/yazi.zip; \
  unzip -q /tmp/yazi.zip -d /tmp/yazi; \
  install -m 0755 "/tmp/yazi/yazi-${yazi_target}/yazi" /usr/local/bin/yazi; \
  install -m 0755 "/tmp/yazi/yazi-${yazi_target}/ya" /usr/local/bin/ya; \
  rm -rf /tmp/yazi /tmp/yazi.zip

RUN npm install -g yarn pnpm typescript ts-node

WORKDIR /app
COPY requirements-agent.txt pyproject.toml README.md LICENSE /app/
RUN pip install --no-cache-dir -r requirements-agent.txt
COPY src /app/src
COPY --from=ui-builder /source/src/local_shell_mcp/ui_static /app/src/local_shell_mcp/ui_static
COPY --from=ui-builder /source/ui/dist/local-shell-mcp-tui /usr/local/bin/local-shell-mcp-tui
RUN pip install --no-cache-dir -e ".[dev]" "playwright==${PLAYWRIGHT_VERSION}" \
  && chmod 0755 /usr/local/bin/local-shell-mcp-tui

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
