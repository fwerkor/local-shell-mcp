FROM archlinux:latest AS aur-builder

RUN pacman -Sy --noconfirm archlinux-keyring \
  && pacman -S --needed --noconfirm \
    base-devel \
    ca-certificates \
    git \
    rust \
    sudo \
    python-build \
    python-hatchling \
    python-installer \
    python-setuptools \
    python-wheel \
  && useradd -m -u 10001 builder \
  && echo "builder ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/builder-nopasswd \
  && chmod 0440 /etc/sudoers.d/builder-nopasswd \
  && mkdir -p /tmp/aur /tmp/aur-packages \
  && chown builder:builder /tmp/aur /tmp/aur-packages \
  && sed -i 's|^#PKGDEST=.*|PKGDEST=/tmp/aur-packages|' /etc/makepkg.conf

USER builder
WORKDIR /tmp/aur
RUN git clone https://aur.archlinux.org/paru.git \
  && cd paru \
  && makepkg -si --needed --noconfirm

WORKDIR /tmp/aur
RUN paru -S --needed --noconfirm --removemake \
    python-docx \
    python-docx2txt \
    python-extract-msg \
    python-httpx-sse \
    python-mammoth \
    python-msoffcrypto-tool \
    python-pdfplumber \
    python-pptx \
    python-pypdfium2 \
    python-pyxlsb \
    python-sse-starlette \
    python-uv-dynamic-versioning \
  && paru -S --needed --noconfirm --removemake python-mcp

FROM archlinux:latest

ENV PYTHONUNBUFFERED=1 \
    LOCAL_SHELL_MCP_WORKSPACE_ROOT=/workspace \
    LOCAL_SHELL_MCP_HOST=0.0.0.0 \
    LOCAL_SHELL_MCP_PORT=8765 \
    DOCKER_PERSISTENT_CREDENTIALS=true \
    DOCKER_CREDENTIALS_DIR=/persist/credentials

RUN pacman -Sy --noconfirm archlinux-keyring \
  && pacman -S --needed --noconfirm \
    bash \
    zsh \
    zsh-completions \
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
    neovim \
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
    python-aiofiles \
    python-beautifulsoup4 \
    python-chardet \
    python-charset-normalizer \
    python-click \
    python-cryptography \
    python-dotenv \
    python-ebooklib \
    python-fastapi \
    python-feedparser \
    python-filetype \
    python-fsspec \
    python-h11 \
    python-html5lib \
    python-httptools \
    python-httpx \
    python-jsonschema \
    python-lxml \
    python-magic \
    python-markdown \
    python-mistune \
    python-numpy \
    python-odfpy \
    python-olefile \
    python-opencv \
    python-openpyxl \
    python-pandas \
    python-pathspec \
    python-pdfminer \
    python-pillow \
    python-pydantic \
    python-pydantic-settings \
    python-pyarrow \
    python-pyjwt \
    python-pymupdf \
    python-pypdf \
    python-python-multipart \
    python-reportlab \
    python-requests \
    python-rich \
    python-scikit-learn \
    python-scipy \
    python-starlette \
    python-statsmodels \
    python-tqdm \
    python-typer \
    python-typing-inspection \
    python-typing_extensions \
    python-uvloop \
    python-watchfiles \
    python-websockets \
    python-xlsxwriter \
    python-xlrd \
    python-xlwt \
    python-yaml \
    uvicorn \
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
    lazygit \
    yazi \
    fzf \
    github-cli \
    pre-commit \
    uv

COPY --from=aur-builder /tmp/aur-packages /tmp/aur-packages
RUN pacman -U --needed --noconfirm /tmp/aur-packages/*.pkg.tar.zst \
  && rm -rf /tmp/aur-packages \
  && pacman -Scc --noconfirm

RUN npm install -g yarn pnpm typescript ts-node

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE /app/
COPY src /app/src
RUN uv sync --locked --no-dev \
  && /app/.venv/bin/python -m compileall -q /app/src \
  && mkdir -p /usr/local/bin \
  && printf '#!/usr/bin/env bash\nexec /app/.venv/bin/python -m local_shell_mcp.main "$@"\n' > /usr/local/bin/local-shell-mcp \
  && chmod +x /usr/local/bin/local-shell-mcp
COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN useradd -m -u 10001 agent \
  && mkdir -p /workspace /workspace/.local-shell-mcp /persist/credentials \
  && echo "agent ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/agent-nopasswd \
  && chmod 0440 /etc/sudoers.d/agent-nopasswd \
  && chown -R agent:agent /workspace /app /home/agent /persist/credentials \
  && chmod +x /usr/local/bin/docker-entrypoint.sh

WORKDIR /workspace

VOLUME ["/workspace", "/persist/credentials"]

EXPOSE 8765
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["local-shell-mcp", "--mode", "mcp"]
