ARG BASE_IMAGE=archlinux:latest
FROM ${BASE_IMAGE}
ARG KEYRING_PACKAGE=archlinux-keyring

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    LOCAL_SHELL_MCP_WORKSPACE_ROOT=/workspace \
    LOCAL_SHELL_MCP_HOST=0.0.0.0 \
    LOCAL_SHELL_MCP_PORT=8765 \
    LOCAL_SHELL_MCP_PERSISTENT_CREDENTIALS=true \
    LOCAL_SHELL_MCP_CREDENTIALS_DIR=/persist/credentials

RUN pacman -Sy --noconfirm "${KEYRING_PACKAGE}" \
  && pacman -S --needed --noconfirm \
    bash \
    zsh \
    ca-certificates \
    sudo \
    curl \
    git \
    jq \
    openssh \
    patch \
    ripgrep \
    tmux \
    tree \
    vim \
    wget \
    zip \
    unzip \
    base-devel \
    autoconf \
    automake \
    clang \
    cmake \
    gdb \
    lldb \
    libtool \
    make \
    ninja \
    pkgconf \
    python \
    python-pip \
    python-virtualenv \
    python-pipx \
    nodejs \
    npm \
    go \
    rust \
    jdk21-openjdk \
    maven \
    gradle \
    ruby \
    php \
    composer \
    perl \
    lua \
    luarocks \
    r \
    shellcheck \
    sqlite \
    file \
    pandoc \
    poppler \
    tesseract \
    libreoffice-fresh \
  && pacman -Scc --noconfirm

RUN npm install -g yarn pnpm typescript ts-node

WORKDIR /app
COPY requirements-agent.txt pyproject.toml README.md LICENSE /app/
RUN pip install --no-cache-dir -r requirements-agent.txt
COPY src /app/src
RUN pip install --no-cache-dir -e .

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
