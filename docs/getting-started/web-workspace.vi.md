<!-- i18n-source-sha256: 474398c2065f510156f7fba24967ca8f6600b586ffb1e002416b7a10dc34c3dc -->
# Không gian làm việc web hợp nhất

**Không gian làm việc web LSM hợp nhất** là cách được khuyến nghị để sử dụng local-shell-mcp hàng ngày. Nó kết hợp trò chuyện AI, lịch sử dự án và mặt phẳng điều khiển LSM trong một giao diện đáp ứng, dựa trên giao diện người dùng LibreChat đã được sửa đổi và cung cấp. Bạn vẫn có thể kết nối các máy khách MCP bên ngoài như [ChatGPT](chatgpt-connector.md) hoặc [Gemini](gemini-spark.md).

Không gian làm việc **tự lưu trữ và tùy chọn cài đặt**: đây là một dịch vụ web riêng biệt, không phải là một phần của hình ảnh Bộ điều khiển tối thiểu, gói Thực thi độc lập hoặc gói Công nhân từ xa. Việc triển khai chỉ dành cho bộ điều khiển giữ lại giao diện người dùng trình duyệt gốc và OpenTUI.

## Trong không gian làm việc có gì?

| Khu vực | Bạn có thể làm gì |
|---|---|
| Trò chuyện và dự án | Chọn mô hình đã định cấu hình, tạo cuộc hội thoại, sắp xếp dự án, tìm các cuộc trò chuyện trước đây và lưu trữ các cuộc trò chuyện. Lịch sử vẫn còn trên máy chủ. |
| Tổng quan về bộ điều khiển | Xem tình trạng, hoạt động gần đây và các máy được kết nối. |
| Tập tin | Duyệt và quản lý các tập tin cục bộ hoặc từ xa. |
| Thiết bị đầu cuối | Làm việc với các thiết bị đầu cuối liên tục trên Bộ điều khiển hoặc Công nhân. |
| Máy tính để bàn | Kiểm tra và kiểm soát các phiên GUI từ xa. |
| Phiên | Kiểm tra các nhiệm vụ LSM lâu bền và vòng đời của chúng. |
| Điều khiển từ xa | Kết nối và quản lý Công nhân đi. |
| Kiểm toán | Kiểm tra hoạt động của công cụ có nguồn gốc từ mô hình. |
| MCP lồng nhau | Đăng ký, chỉnh sửa, kích hoạt, vô hiệu hóa, làm mới và xóa các máy chủ MCP bên ngoài đằng sau LSM. |

Các tuyến Bộ điều khiển là `/control/overview`, `/control/files`, `/control/terminals`, `/control/desktop`, `/control/sessions`, `/control/remotes` và `/control/audit`. Trò chuyện mở ra tại `/c/new`. Trình quản lý MCP LSM kiểm soát **Đăng ký MCP lồng nhau của LSM**; nó không tạo sổ đăng ký thứ hai trong LibreChat.

## Triển khai ngăn xếp trò chuyện tùy chọn

1. [Install and start an LSM Controller](quickstart.md) với OAuth, một không gian làm việc được cách ly thích hợp và bộ lưu trữ trạng thái `file` hoặc `redis` liên tục. Cài đặt Docker Compose và sao chép kho lưu trữ vào máy chủ đang chạy ngăn xếp web.
2. Cung cấp **hai nguồn gốc HTTPS trên cùng một trang**, chẳng hạn như `https://lsm.example.org` cho Bộ điều khiển và `https://chat.example.org` cho không gian làm việc. Dịch vụ trò chuyện không được hiển thị trực tiếp trên mạng không đáng tin cậy.
3. Tạo một bí mật cầu nối với `openssl rand -hex 32`. Định cấu hình các biến môi trường này trên **Dịch vụ bộ điều khiển**, sử dụng bí mật đó, sau đó khởi động lại:

```env
LOCAL_SHELL_MCP_LIBRECHAT_URL=https://chat.example.org
LOCAL_SHELL_MCP_LIBRECHAT_BRIDGE_SECRET=paste-the-same-64-hex-character-secret-on-both-services
```

4. Trong quá trình kiểm tra kho lưu trữ, hãy định cấu hình ngăn xếp web tùy chọn. Sử dụng tệp môi trường riêng tư hoặc xuất các giá trị hiển thị bên dưới; tạo ra những bí mật mạnh mẽ độc đáo và không cam kết chúng:

```sh
export LSM_PUBLIC_ORIGIN=https://lsm.example.org
export LIBRECHAT_PUBLIC_URL=https://chat.example.org
export LSM_LIBRECHAT_BRIDGE_SECRET="paste-the-secret-from-controller-config"
export JWT_SECRET="$(openssl rand -hex 32)"
export JWT_REFRESH_SECRET="$(openssl rand -hex 32)"
export CREDS_KEY="$(openssl rand -hex 32)"
export CREDS_IV="$(openssl rand -hex 16)"
export MEILI_MASTER_KEY="$(openssl rand -hex 32)"
export LSM_DOCKER_NETWORK=local-shell-mcp_default
```

5. Kết xuất cấu hình riêng tư, sau đó xây dựng và bắt đầu ngăn trò chuyện được triển khai riêng:

```sh
python3 integrations/librechat/render_config.py
docker compose -f integrations/librechat/compose.yaml build chat
docker compose -f integrations/librechat/compose.yaml up -d
```

Khi sử dụng triển khai Docker Compose gốc, các biến Trình điều khiển ở trên thuộc về `.env` gốc và được chuyển tiếp đến vùng chứa. Các giá trị dịch vụ trò chuyện có thể được cung cấp thông qua xuất shell hoặc tệp môi trường riêng tư. Vùng chứa Bộ điều khiển phải có thể truy cập được từ vùng chứa trò chuyện tại `http://local-shell-mcp:8765` trên mạng Docker có tên. Cổng proxy ngược `127.0.0.1:3080` về nguồn gốc trò chuyện HTTPS, bảo toàn máy chủ bên ngoài và tuân theo [deployment and security notes](https://github.com/fwerkor/local-shell-mcp/blob/main/integrations/librechat/README.md) trong kho lưu trữ. Ngăn xếp web chạy Node.js, MongoDB, Meilisearch và SearXNG; họ **không** được bao gồm trong Công nhân. Việc triển khai riêng biệt này không được bắt đầu bằng `docker compose up -d` đơn giản trong thư mục gốc của kho lưu trữ.

## Đăng nhập và sử dụng trò chuyện

1. Mở `https://lsm.example.org/ui`, xác thực bằng thông tin đăng nhập **LSM Controller** và thực hiện chuyển giao một lần vào không gian làm việc trên web. Bạn không tạo tài khoản người dùng LibreChat thứ hai.
2. Định cấu hình nhà cung cấp LLM có sẵn hoặc điểm cuối mô hình cho dịch vụ trò chuyện. Không gian làm việc cung cấp giao diện trò chuyện và cầu nối công cụ; **nó không bao gồm tín dụng mô hình hoặc API**.
3. Tạo một cuộc trò chuyện. Các công cụ tìm kiếm trên web và LSM được bật theo mặc định, tùy thuộc vào quyền của Bộ điều khiển. Sử dụng các điều khiển **Web**, **LSM**, **External MCP** và **Memory** cho mỗi cuộc trò chuyện nếu cần.
4. Bắt đầu với yêu cầu chỉ đọc: "Kiểm tra trạng thái Bộ điều khiển và liệt kê thư mục gốc của không gian làm việc. Không sửa đổi tệp."
5. Điều hướng đến **Tệp**, **Thiết bị đầu cuối**, **Máy tính để bàn**, **Phiên**, **Điều khiển từ xa** hoặc **Kiểm tra** để kiểm tra và kiểm soát trực tiếp.

Nội dung tải lên trò chuyện (tối đa 32 MiB) được lưu trữ trong không gian làm việc của Bộ điều khiển và đường dẫn tuyệt đối của chúng được cung cấp cho mô hình. Tải lên trình duyệt không cấp thêm quyền truy cập tệp. Các lệnh gọi công cụ hướng tới mô hình chuyển qua ủy quyền, kiểm tra LSM và bộ định tuyến làm việc từ xa.

## MCP bên ngoài, bảo mật và dữ liệu

Sử dụng thanh bên MCP của không gian làm việc để quản lý các máy chủ MCP bên ngoài lồng nhau. Điều này hỗ trợ các máy chủ stdio cục bộ và máy chủ HTTP, bao gồm các biến môi trường riêng tư và tiêu đề yêu cầu. Bí mật không được trả lại cho trình duyệt. Nút chuyển đổi trò chuyện **MCP bên ngoài** cho phép tìm kiếm, kiểm tra và gọi các công cụ lồng nhau; nó không cấp mô hình `mcp_manage` khi các công cụ LSM gốc bị tắt. Quản lý giao diện người dùng được bảo vệ bằng ủy quyền của Bộ điều khiển thông thường.

Tin nhắn trò chuyện, dự án và kho lưu trữ được lưu trữ phía máy chủ trong MongoDB của ngăn xếp web; tìm kiếm sử dụng Meilisearch. Bộ điều khiển sở hữu riêng các quyền của công cụ, danh tính Công nhân, trạng thái phiên và kiểm tra. Sao lưu cả hai kho dữ liệu nếu bạn cần giữ lại toàn bộ lịch sử. Phần phụ trợ trò chuyện là một người dùng dưới thông tin đăng nhập của LSM; không tiết lộ công khai API hoặc cơ sở dữ liệu nội bộ của nó.

Giao diện người dùng là một ứng dụng cấp cao nhất, **không phải iframe**. Nếu dịch vụ trò chuyện tùy chọn không được định cấu hình, `/ui` sẽ tiếp tục phục vụ LSM WebUI gốc. OpenTUI gốc và các ứng dụng khách bên ngoài vẫn được hỗ trợ.

## Khắc phục sự cố

- **Chuyển hướng vẫn còn trên giao diện người dùng gốc:** kiểm tra `LOCAL_SHELL_MCP_LIBRECHAT_URL`, chương trình phụ trợ trạng thái Bộ điều khiển liên tục và proxy ngược HTTPS của ngăn xếp web.
- **Đăng nhập hoặc chuyển giao không thành công:** xác minh chính xác cùng một bí mật cầu nối dài 32 byte hoặc dài hơn ở cả hai bên, khớp với nguồn gốc của cùng một trang web, HTTPS và đồng hồ máy chủ.
- **Tải trò chuyện nhưng không thể trả lời:** thiết lập điểm cuối mô hình thực tế hoặc thông tin xác thực API và kiểm tra nhật ký vùng chứa trò chuyện.
- **Thiếu công cụ MCP:** xác minh phạm vi Bộ điều khiển và chuyển đổi cho mỗi cuộc hội thoại; sổ đăng ký máy chủ lồng nhau tách biệt với cơ sở dữ liệu LibreChat MCP.
- **Tệp hoặc phiên xuất hiện trống:** xác minh rằng cuộc trò chuyện đến đúng Bộ điều khiển và không gian làm việc, đồng thời kiểm tra nhật ký xác thực API của nó.

Để biết chi tiết triển khai và cập nhật, hãy xem [the vendored integration README](https://github.com/fwerkor/local-shell-mcp/blob/main/integrations/librechat/README.md) và [human interface guide](../guides/human-interface.md).
