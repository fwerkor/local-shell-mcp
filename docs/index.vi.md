<!-- i18n-source-sha256: a66d491558f07c419c8b5958d36c47cd90b081fc1c81f015bb62398cfd573e55 -->
<div class="hero-shell" markdown>
<span class="hero-eyebrow">Không gian làm việc AI tự lưu trữ · Mặt phẳng điều khiển MCP</span>

# local-shell-mcp

Trò chuyện, dự án, tệp, thiết bị đầu cuối, máy từ xa và công cụ AI trong một giao diện tự lưu trữ. Kết nối các máy khách MCP bên ngoài khi bạn cần chúng.

<div class="hero-actions" markdown>
[Bắt đầu](getting-started/quickstart.md){ .hero-action .hero-action--primary }
[Web workspace](getting-started/web-workspace.md){ .hero-action .hero-action--secondary }
[Tham chiếu tools](reference/tools.md){ .hero-action .hero-action--secondary }
</div>
</div>

<div class="feature-grid" markdown>
<div class="feature-card" markdown>
### Môi trường coding thực
Chạy tests, kiểm tra repositories, patch files, vận hành Git và giữ audit trail từ một MCP endpoint.
</div>

<div class="feature-card" markdown>
### Không gian làm việc web hợp nhất
Sử dụng lịch sử dự án và trò chuyện tích hợp cùng với các tệp Bộ điều khiển, thiết bị đầu cuối, máy tính để bàn, phiên, điều khiển từ xa và kiểm tra. Các máy khách MCP bên ngoài vẫn là tùy chọn.
</div>

<div class="feature-card" markdown>
### Điều khiển remote machine
Gắn máy sau NAT, firewall hoặc HPC qua outbound worker connections mà không mở SSH ports.
</div>
</div>

## Cung cấp những gì

`local-shell-mcp` cung cấp không gian làm việc AI tự lưu trữ thống nhất và máy chủ MCP cho các máy khách bên ngoài. Nó cung cấp shell, shell liên tục, hệ thống tệp, tìm kiếm, bản vá, Git, Playwright, kiểm toán, các phiên logic bền bỉ với các gói Mục tiêu tùy chọn, liên kết tệp được mã hóa và các công cụ làm việc từ xa thông qua các điểm cuối MCP được xác thực.

Dùng khi AI cần inspect repository, chạy tests, edit files, operate Git, thu browser evidence, tạo downloadable artifacts hoặc điều khiển remote machine chỉ có thể outbound connect tới control server.

## Kiến trúc

```text
Lớp runtime: Docker / VS Code extension / binary / Python / stdio
Lớp exposure: localhost / HTTPS proxy / tunnel / stdio pipe
Lớp máy khách: WebUI / Gemini / ChatGPT / máy khách MCP chung thống nhất
Workspace được kiểm soát: /workspace or configured workspace root
Remote workers tùy chọn: outbound machine connections
```

Isolation boundary dự kiến là container hoặc VM chạy service.

## Bắt đầu theo kịch bản

| Kịch bản | Bắt đầu ở đây | Lý do |
|---|---|---|
| Không gian làm việc của trình duyệt chính | [Unified web workspace](getting-started/web-workspace.md) | Các trang trò chuyện, dự án và kiểm soát LSM có thông tin đăng nhập chung |
| Triển khai bộ điều khiển đầu tiên | [Quickstart](getting-started/quickstart.md) | Docker Compose, OAuth và phiên trình duyệt đầu tiên |
| Chọn runtime layer | [Runtime choices](guides/deployment.md) | Giải thích Docker, VS Code, binary, Python và stdio là các runtime option riêng |
| Kết nối Gemini Spark | [Gemini Custom Apps](getting-started/gemini-spark.md) | Tính đủ điều kiện, URL HTTPS MCP, OAuth và thử nghiệm |
| Thêm ChatGPT làm client | [ChatGPT connector](getting-started/chatgpt-connector.md) | Endpoint, OAuth, prompt an toàn đầu tiên, tool discovery |
| Thêm LSM vào DeepSeek Harness | [Plugin DeepSeek Harness](clients/deepseek-harness.md) | Cài repository này như DSH bundle đồng thời giữ toàn bộ LSM tool và remote-worker surface |
| Chạy từ VS Code | [VS Code extension runtime](installation/vscode-extension.md) | Editor-launched runtime và lưu ý host safety |
| Học cách vận hành toolset | [Usage patterns](guides/usage-patterns.md) | Prompt templates và hướng dẫn chọn tools |
| Hiểu từng tool | [Tools reference](reference/tools.md) | Purpose, inputs, returns, combinations và notes của từng tool |
| Kết nối HPC, NPU/GPU hoặc server node | [Remote workers](guides/remote-workers.md) | Outbound worker join flow và remote tool usage |
| Chia sẻ generated files | [File links](guides/file-links.md) | Tokenized download URL có TTL và revocation |
| Harden deployment | [Security](security.md) | Isolation, OAuth, workspace scope và audit logs |

## Các family tool chính

| Family | Ví dụ | Dùng cho |
|---|---|---|
| Shell and Python | `run_shell`, `run_python`, `shell_start` | Builds, tests, scripts, long-running processes |
| Files and search | `file_tree`, `file_grep`, `file_read`, `file_patch` | Repository inspection và precise edits |
| Git | `run_shell`, `run_shell`, `run_shell`, `run_shell` | Reviewable source-control workflows |
| Sessions và goals | `session_manage`, `plan_manage` | Durable task handoff, progress report và optional Goal mode |
| Browser | `browser_session`, `browser_snapshot`, `browser_act`, `browser_run_script` | Persistent interaction, UI checks, screenshots, rendered docs, page text |
| File links | `link_create`, `link_revoke` | Download generated artifacts từ chat |
| Remote workers | `remote_manage`, `run_shell`, `remote_transfer` | Machines sau NAT, firewalls hoặc cluster login flows |

## Workflow điển hình

### Mã hóa trong không gian làm việc web

1. Khởi động Bộ điều khiển LSM và [unified web workspace](getting-started/web-workspace.md) tùy chọn.
2. Mở `/ui` và đăng nhập bằng thông tin nhận dạng LSM.
3. Định cấu hình điểm cuối mô hình và mở cuộc trò chuyện mới.
4. Yêu cầu mô hình kiểm tra kho lưu trữ và chạy kiểm tra chỉ đọc trước.
5. Sau khi chấp thuận, cho phép patch files, tests, diff review, commit và push.
6. Review audit log khi task liên quan file links hoặc remote systems.

### Remote HPC hoặc accelerator host

1. Tạo one-time remote worker invite.
2. Dán generated command trên remote host.
3. Dùng normal tools với `machine`; Git qua `run_shell` và transfer qua `remote_transfer`.
4. Revoke worker sau task.

### Artifact generation

1. Để AI generate file dưới `/workspace`.
2. Tạo tokenized file link với TTL/download limits.
3. Chia sẻ link trong chat.
4. Revoke khi xong.

## Ngôn ngữ

Site này được build bằng native MkDocs i18n plugin. Dùng language selector trong header để chuyển giữa English và translated pages. Page không có translation fallback sang English.
