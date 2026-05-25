ARG PLAYWRIGHT_VERSION=1.59.0
FROM mcr.microsoft.com/playwright/python:v${PLAYWRIGHT_VERSION}-noble
ARG PLAYWRIGHT_VERSION

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LOCAL_SHELL_MCP_WORKSPACE_ROOT=/workspace \
    LOCAL_SHELL_MCP_HOST=0.0.0.0 \
    LOCAL_SHELL_MCP_PORT=8765

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    git \
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
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE /app/
COPY src /app/src
RUN pip install --no-cache-dir -e . "playwright==${PLAYWRIGHT_VERSION}"

RUN useradd -m -u 10001 agent && mkdir -p /workspace /workspace/.local-shell-mcp && chown -R agent:agent /workspace /app
USER agent
WORKDIR /workspace

EXPOSE 8765
CMD ["local-shell-mcp", "--mode", "mcp"]
