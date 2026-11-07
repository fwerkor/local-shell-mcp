<!-- i18n-source-sha256: b7c3dfd7dc21a498f8410a88a8a52094ca0349856dfa43d267e3fe7bb273685a -->
# Kết nối Gemini Spark / Ứng dụng tùy chỉnh

Tính năng **ứng dụng được kết nối tùy chỉnh** của Gemini (trước đây được mô tả là **Spark**) cho phép người dùng Gemini đủ điều kiện kết nối máy chủ MCP từ xa. LSM có thể cung cấp điểm cuối MCP. Đây là **kết nối máy khách thay thế** với [unified web workspace](web-workspace.md), [ChatGPT](chatgpt-connector.md) và các máy khách MCP khác; nó không thay thế hoặc triển khai Bộ điều khiển LSM.

Google hiện hạn chế các ứng dụng tùy chỉnh đối với **người dùng từ 18 tuổi trở lên ở Hoa Kỳ**, đăng nhập bằng **Tài khoản Google cá nhân** và **Bật hoạt động**. Tính năng này có sẵn bằng **tiếng Anh**. Các kết nối phải được tạo trên ứng dụng web Gemini, mặc dù sau này các ứng dụng được kết nối có thể được sử dụng trên thiết bị di động. Tính khả dụng và nhãn giao diện người dùng có thể thay đổi; tham khảo [official Gemini custom apps instructions](https://support.google.com/gemini/answer/17209137).

## Trước khi kết nối

- Bắt đầu thời gian chạy LSM, chẳng hạn như với [Docker Compose](../installation/docker.md) và xác minh tình trạng của nó.
- Hiển thị điểm cuối MCP của nó qua **HTTPS có thể truy cập công khai** và luôn bật OAuth.
- Biết chi tiết xác thực của Bộ điều khiển và chỉ phê duyệt phạm vi bạn cần.
- Sử dụng không gian làm việc hoặc vùng chứa bị hạn chế. Gemini có thể yêu cầu các hoạt động có hiệu ứng thực sự trên các tập tin, máy móc và thiết bị đầu cuối.

Điểm cuối để vào Gemini là:

```text
https://your-public-host.example.com/mcp
```

Không nhập giao diện người dùng web (`/ui`), URL LibreChat hoặc nguồn gốc trang web mà không có `/mcp`. Triển khai công khai không được tắt xác thực để khắc phục lỗi kết nối.

## Kết nối ở cung Song Tử

1. Trên máy tính, mở [Gemini](https://gemini.google.com/) và đăng nhập bằng tài khoản cá nhân đủ điều kiện.
2. Mở **Cài đặt và trợ giúp → Ứng dụng được kết nối**. Tùy thuộc vào giao diện hiện tại, nó có thể nằm trong **Thông tin cá nhân → Ứng dụng được kết nối**.
3. Trong **Ứng dụng tùy chỉnh**, hãy chọn **Thêm ứng dụng tùy chỉnh** hoặc sử dụng trường URL ứng dụng tùy chỉnh.
4. Dán URL LSM HTTPS `/mcp`, sau đó chọn **Tiếp theo**.
5. Hoàn tất quy trình OAuth và sự đồng ý bằng Bộ điều khiển LSM. LSM hỗ trợ khám phá OAuth và đăng ký ứng dụng khách động. Thay vào đó, nếu Gemini yêu cầu thông tin xác thực ứng dụng khách OAuth thủ công, hãy kiểm tra các tùy chọn nâng cao và thiết lập LSM OAuth của bạn trước khi tiếp tục.
6. Trong cuộc trò chuyện với Song Tử, hãy nhập `@` và chọn ứng dụng tùy chỉnh được kết nối để yêu cầu công cụ LSM.

Bắt đầu bằng: "Sử dụng ứng dụng LSM được kết nối để kiểm tra môi trường và liệt kê các tệp không gian làm việc. Không sửa đổi bất cứ điều gì." Kiểm tra kết quả của công cụ và kiểm tra Bộ điều khiển trước khi thử thao tác ghi.

## Giới hạn và khắc phục sự cố

- **Không có tùy chọn Ứng dụng tùy chỉnh:** xác nhận tính đủ điều kiện của tài khoản, khu vực, độ tuổi, ngôn ngữ và tính đủ điều kiện của Hoạt động duy trì. Đây là hạn chế về tính khả dụng của phía Gemini, không phải lỗi cấu hình LSM.
- **URL bị từ chối:** sử dụng điểm cuối HTTPS `/mcp` có thể truy cập từ bên ngoài; kiểm tra khám phá OAuth và proxy ngược của bạn.
- **OAuth không thành công:** kiểm tra màn hình ủy quyền LSM, đăng ký ứng dụng khách, URL gọi lại và phạm vi được cấp. Không xuất bản điểm cuối MCP chưa được xác thực.
- **Một công cụ bị thiếu hoặc bị lỗi:** Hỗ trợ lược đồ/công cụ MCP phía máy khách có thể khác nhau. Hãy thử một cuộc gọi chỉ đọc đơn giản và kiểm tra nhật ký và kiểm tra LSM; Khả năng tương thích hoàn toàn với mọi tính năng của máy khách Gemini không được đảm bảo.
- **Ngắt kết nối:** quay lại **Ứng dụng đã kết nối** để tắt, hủy liên kết hoặc xóa LSM khi không còn cần thiết.

[official guide](https://support.google.com/gemini/answer/17209137) của Google mô tả luồng và tính khả dụng của Ứng dụng tùy chỉnh mới nhất. Thay vào đó, để tích hợp Gemini dựa trên CLI cục bộ, hãy xem [Gemini CLI's MCP documentation](https://geminicli.com/docs/tools/mcp-server/). LSM [ChatGPT connector tutorial](chatgpt-connector.md) vẫn có sẵn độc lập.
