<!-- i18n-source-sha256: ed47d5e0691f17af5cd4758981c31957e299202bf72433b34b4656346312091e -->
# Runtime binary độc lập

Khuyến nghị **tệp thực thi Controller duy nhất** từ GitHub Releases, không cần Python, Docker hay mã nguồn.

Đây là lựa chọn runtime. Truy cập ChatGPT được cấu hình riêng qua endpoint HTTPS `/mcp`.

## Artifact release

GitHub Releases build executable tự chứa cho các nền tảng phổ biến:

| Platform artifact | Archive |
|---|---|
| `local-shell-mcp-linux-x86_64` | `.tar.gz` |
| `local-shell-mcp-linux-aarch64` | `.tar.gz` |
| `local-shell-mcp-macos-x86_64` | `.tar.gz` |
| `local-shell-mcp-macos-aarch64` | `.tar.gz` |
| `local-shell-mcp-windows-x86_64` | `.zip` |

Mỗi archive chứa executable, README, license và file quickstart ngắn.

Có thể tải trực tiếp **một tệp thực thi duy nhất**. Tệp chỉ chứa Controller và WebUI gốc; chat, cơ sở dữ liệu, Worker, công cụ và trình duyệt cần cài riêng.

## Cài đặt

1. Tải tệp thực thi hoặc gói nén phù hợp từ [GitHub Releases](https://github.com/fwerkor/local-shell-mcp/releases/latest).
2. Nếu chọn gói nén, hãy giải nén.
3. Đặt executable trên `PATH` hoặc ghi lại absolute path.
4. Chạy `local-shell-mcp --help` để xác nhận binary khởi động.

Ví dụ: tải trực tiếp tệp Linux x86_64; nền tảng khác chọn tệp phù hợp:

```bash
mkdir -p ~/lsm && cd ~/lsm
curl -fL https://github.com/fwerkor/local-shell-mcp/releases/latest/download/local-shell-mcp-linux-x86_64 -o local-shell-mcp
chmod +x local-shell-mcp
./local-shell-mcp --help
```

Người dùng Windows nên chạy `local-shell-mcp.exe` từ PowerShell hoặc thêm directory chứa nó vào `PATH`.

## Minimal local run

```bash
mkdir -p ~/local-shell-mcp-workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT=~/local-shell-mcp-workspace
~/lsm/local-shell-mcp --mode mcp
```

Trong terminal khác:

```bash
curl -i http://127.0.0.1:8765/healthz
```

## Public HTTP MCP run

Với ChatGPT hoặc public HTTP MCP client, cấu hình các nhóm sau:

| Setting | Purpose |
|---|---|
| `LOCAL_SHELL_MCP_WORKSPACE_ROOT` | Directory do tool điều khiển |
| `LOCAL_SHELL_MCP_HOST` and `LOCAL_SHELL_MCP_PORT` | Local bind address và port |
| `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` | Public HTTPS origin không có `/mcp` |
| `LOCAL_SHELL_MCP_AUTH_MODE` | Dùng `oauth` cho public deployment |
| OAuth PIN and JWT secret settings | Cần cho public OAuth authorization |

Expose local HTTP port qua reverse proxy hoặc tunnel. Public endpoint:

```text
https://your-public-host.example.com/mcp
```

## YAML config

YAML config có thể chứa runtime default không phải secret:

```yaml
host: 127.0.0.1
port: 8765
mode: mcp
workspace_root: /srv/local-shell-mcp/workspace
auth_mode: oauth
public_base_url: https://your-public-host.example.com
```

Chạy:

```bash
local-shell-mcp --config /path/to/config.yaml
```

Environment variable có prefix `LOCAL_SHELL_MCP_` ghi đè giá trị YAML.

## Trách nhiệm host toolchain

Binary đóng gói ứng dụng Python, không phải mọi developer tool. MCP tool gọi các chương trình có sẵn trên host.

Cài những gì task của bạn cần:

| Capability | Host packages to consider |
|---|---|
| Search and shell ergonomics | `ripgrep`, `tree`, `jq`, `curl`, `wget`; Linux release đã có static tmux helper |
| Git workflows | `git`, `gh`, OpenSSH client, credential helpers |
| Python projects | Python, pip, venv, project-specific compilers and headers |
| Node projects | Node.js, npm, pnpm, yarn |
| Rust/Go/Java/C++ | Cargo/rustc, Go, JDK, Maven/Gradle, compilers, CMake, Ninja |
| Browser automation | Playwright browser binaries and OS dependencies |
| Document conversion | LibreOffice, Pandoc, Poppler utilities |

Binary chứa Controller; công cụ bên ngoài và trình duyệt là tùy chọn. Chat và lịch sử cần [không gian web](../getting-started/web-workspace.md) với cơ sở dữ liệu riêng.

## Dịch vụ chạy lâu dài

Với persistent public deployment, chạy binary dưới process supervisor của hệ điều hành. Giữ các thực hành sau:

- Dùng dedicated low-privilege OS account.
- Dùng dedicated workspace directory.
- Lưu sensitive value ngoài world-readable file.
- Tự động restart khi lỗi.
- Kiểm tra `/healthz` sau mỗi restart.
- Giữ log cho troubleshooting.

## Cập nhật

1. Thay file thực thi mới rồi khởi động lại Controller:
2. Verify checksum nếu muốn.
3. Thay executable.
4. Restart process manager.
5. Kiểm tra `/healthz`.
6. Yêu cầu client chạy `environment_get` trước khi tiếp tục.

## Ghi chú an toàn

Binary chạy với privilege của user hệ điều hành. Với public deployment, dùng dedicated low-privilege user, dedicated workspace và biên VM/container nếu có thể.

Không đặt `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true` cho binary chạy trực tiếp trên personal host. Setting này dành cho disposable container hoặc VM.
