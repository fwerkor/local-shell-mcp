<!-- i18n-source-sha256: 594169d44520f8abd7cebee1bfa42c5ff0ca31f424115d438107ed01b77fa604 -->
# Lựa chọn runtime và mô hình deployment

`local-shell-mcp` có hai quyết định bổ sung:

1. **Runtime**: process server chạy như thế nào và kiểm soát workspace nào.
2. **Giao diện**: sử dụng [unified web workspace](../getting-started/web-workspace.md) tùy chọn hoặc kết nối ứng dụng khách MCP bên ngoài như Gemini hoặc ChatGPT.

Giao diện hàng ngày được đề xuất là không gian làm việc web tự lưu trữ (trò chuyện, dự án và trang kiểm soát LSM). Nó được triển khai riêng biệt với Bộ điều khiển. Docker, phần mở rộng VS Code, các tệp nhị phân phát hành, các bản cài đặt Python và chế độ stdio là những cách để chạy Bộ điều khiển; các ứng dụng trò chuyện bên ngoài vẫn là ứng dụng khách tùy chọn.

```text
Runtime layer                      Exposure layer                 Client layer
-------------------------------    ---------------------------    ----------------------
Docker Chỉ soạn thảo HTTP cục bộ Không gian làm việc web hợp nhất
VS Code extension                  HTTPS reverse proxy/tunnel     Generic MCP client
Standalone binary                  stdio process pipe             VS Code extension UI
pipx / source checkout             remote-worker outbound join    REST-style diagnostics
```

Một thiết lập tự lưu trữ phổ biến là:

```text
Trình duyệt -> https://chat.example.com (không gian làm việc web thống nhất)
        -> Bộ điều khiển local-shell-mcp đã được xác thực
        -> không gian làm việc được kiểm soát và công nhân đi làm
Máy khách bên ngoài tùy chọn -> https://mcp.example.com/mcp
```

Setup MCP client cục bộ có thể đơn giản hơn:

```text
Local MCP client
  -> starts local-shell-mcp --mode stdio
  -> controlled workspace
```

## Ma trận lựa chọn runtime

| Thời gian chạy | Tốt nhất cho | Ranh giới cách ly | Nguồn chuỗi công cụ | Truy cập MCP bên ngoài | Trang |
|---|---|---|---|---|---|
| Docker Soạn | Hầu hết khối lượng công việc của tác nhân mã hóa và không gian làm việc có thể lặp lại | thùng chứa | Hình ảnh Bộ điều khiển tinh gọn; cài đặt riêng các chuỗi công cụ dành riêng cho nhiệm vụ | Thêm proxy hoặc đường hầm HTTPS | [Docker Compose](../installation/docker.md) |
| Docker Compose + xe sidecar đường hầm | Triển khai Bộ điều khiển công cộng với Đường hầm Cloudflare | thùng chứa | Hình ảnh dự án | Được tích hợp vào hồ sơ Compose `tunnel` | [Docker Compose](../installation/docker.md#cloudflare-tunnel-sidecar) |
| VS Code extension | Start/stop server từ editor workspace | Thường là host process | Host tools cộng executable cấu hình | Thêm HTTPS tunnel/proxy ngoài cho ChatGPT | [VS Code extension](../installation/vscode-extension.md) |
| Standalone binary | Host hoặc VM không có Docker | Host or VM | Host tools cộng executable cấu hình | Thêm HTTPS proxy hoặc tunnel | [Standalone binary](../installation/binary.md) |
| `pipx` / source install | Dùng Python-native, debugging, development | Host virtualenv or VM | Python package cộng host tools | Thêm HTTPS proxy hoặc tunnel | [Python install](../installation/python.md) |
| Stdio mode | MCP client cục bộ spawn process trực tiếp | Client process boundary | Host tools cộng executable cấu hình | Không dùng được với ChatGPT web/app | [Stdio mode](../installation/stdio.md) |

## Ma trận kết nối client

| Giao diện | Yêu cầu HTTPS công khai | Sử dụng `/mcp` | Yêu cầu OAuth | Thời gian chạy điển hình |
|---|---:|---:|---:|---|
| Không gian làm việc web LSM hợp nhất | Có để truy cập từ xa; proxy cục bộ cũng có thể | Nội bộ | Đăng nhập LSM | Bộ điều khiển cộng với ngăn xếp web riêng biệt |
| Gemini Spark / Ứng dụng tùy chỉnh | Có | Có | Có để sử dụng công cộng | Bất kỳ bộ điều khiển HTTP nào |
| ChatGPT custom MCP connector | Có | Có | Có khi dùng công khai | Docker, VS Code extension, binary, or Python |
| Generic local MCP client over stdio | Không | Không | Không | `local-shell-mcp --mode stdio` |
| Generic HTTP MCP client | Thường không ở localhost; có qua mạng | Có | Khuyến nghị ngoài localhost | Any HTTP runtime |
| VS Code extension helper flow | Chỉ khi ChatGPT cần connect | Có khi copy URL ChatGPT | Khuyến nghị cho ChatGPT | VS Code-launched runtime |

Xem [unified web workspace](../getting-started/web-workspace.md), [Gemini Spark](../getting-started/gemini-spark.md), [ChatGPT connector](../getting-started/chatgpt-connector.md), [generic MCP clients](../clients/generic-mcp.md) và [network connectivity](../clients/connectivity.md).

## Mỗi runtime kiểm soát gì

Mỗi runtime khởi chạy cùng server code và cung cấp cùng các family MCP tools khi được bật:

- Shell và persistent shell sessions.
- Filesystem, search và patch tools.
- Git operations.
- Browser automation qua Playwright.
- Audit log và task-state tools.
- Tokenized file links.
- Optional remote-worker lifecycle và machine-routed tools.

Khác biệt không nằm ở abstract API mà ở **operating environment** phía sau.

| Câu hỏi | Docker Compose | VS Code extension | Binary / Python |
|---|---|---|---|
| Command chạy ở đâu? | Trong container | Thường trên host workspace | Trong host hoặc VM process environment |
| Default workspace? | Mounted `/workspace` | Folder VS Code hiện tại hoặc path cấu hình | `LOCAL_SHELL_MCP_WORKSPACE_ROOT` |
| Trình biên dịch và trình duyệt có được cài đặt sẵn không? | KHÔNG; cài đặt những gì nhiệm vụ cần | Chỉ khi được cài đặt trên máy chủ | Chỉ khi được cài đặt trên máy chủ |
| Reset dễ không? | Tạo lại container và workspace volume | Phụ thuộc workspace | Phụ thuộc host/VM |
| Phù hợp arbitrary package install? | Có nếu disposable | Rủi ro hơn trên host | Rủi ro hơn ngoài VM |

## Lựa chọn khuyến nghị

Trước tiên hãy sử dụng **Docker Compose** trừ khi bạn có lý do để không làm vậy. Nó đưa ra ranh giới an toàn rõ ràng mà không yêu cầu chuỗi công cụ phát triển được cài đặt sẵn lớn.

Sử dụng **tiện ích mở rộng Mã VS** khi quy trình làm việc bắt đầu từ trình chỉnh sửa và bạn muốn có trình khởi chạy cục bộ. Nó vẫn là một thời gian chạy. Máy khách web từ xa cần có proxy hoặc đường hầm HTTPS có thể truy cập được.

Dùng **standalone binary** khi Docker không khả dụng nhưng VM, container host hoặc dedicated user account đã tạo boundary.

Dùng **`pipx` hoặc source install** để development/debugging `local-shell-mcp` hoặc khi Python-based environment dễ duy trì hơn.

Chỉ dùng **stdio mode** cho MCP client cục bộ có thể spawn server process. Nó không phải public deployment và không dùng trực tiếp được từ ChatGPT web/app.

## Quy tắc public endpoint

Đối với các máy khách HTTP MCP bên ngoài như Gemini và ChatGPT, điểm cuối MCP là:

```text
https://your-public-host.example.com/mcp
```

`LOCAL_SHELL_MCP_PUBLIC_BASE_URL` chỉ là origin:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

Không thêm `/mcp` vào `LOCAL_SHELL_MCP_PUBLIC_BASE_URL`.

## Trang runtime

- [Docker Compose](../installation/docker.md)
- [VS Code extension](../installation/vscode-extension.md)
- [Standalone binary](../installation/binary.md)
- [Python, `pipx`, and source install](../installation/python.md)
- [Stdio mode](../installation/stdio.md)

## Trang client

- [Unified web workspace](../getting-started/web-workspace.md)
- [Gemini Spark / Custom Apps](../getting-started/gemini-spark.md)
- [ChatGPT connector](../getting-started/chatgpt-connector.md)
- [Generic MCP clients](../clients/generic-mcp.md)
- [Public HTTPS exposure](../clients/connectivity.md)
