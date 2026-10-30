<!-- i18n-source-sha256: 53d1b81800534bc6d5334883b7de74660c988088c66f492ddbd68aced8797379 -->
# Trò chuyện được lưu trữ (tùy chọn)

Trò chuyện được lưu trữ là ứng dụng trò chuyện BYOK và ứng dụng MCP Apps tự lưu trữ, được tích hợp vào giao diện con người của LSM. Đây **không phải** là chế độ Phiên logic: các cuộc hội thoại có danh tính độc lập và có thể tùy ý đính kèm Phiên logic LSM hiện có. ChatGPT và các ứng dụng khách bên ngoài khác tiếp tục làm việc với cùng các phiên và công cụ LSM.

## Kích hoạt

Trò chuyện được lưu trữ bị tắt theo mặc định. Đặt:

```env
LOCAL_SHELL_MCP_HOSTED_CHAT_ENABLED=true
```

Khởi động lại Bộ điều khiển và mở **Trò chuyện được lưu trữ** ngay bên dưới bộ chọn Giao diện người dùng web / TUI. Tính năng này cũng có mục nhập trên thanh trên cùng trên thiết bị di động. Máy chủ trò chuyện sử dụng danh tính và phạm vi LSM OAuth hiện có. Bộ điều khiển tương tự vận hành máy chủ MCP được sử dụng bởi vòng lặp công cụ của mô hình; Công nhân không thể bắt đầu thực hiện.

## Hồ sơ người mẫu

Chọn **Hồ sơ mô hình** để tạo/chỉnh sửa hồ sơ có tên, URL cơ sở API tương thích với HTTPS OpenAI, ID mô hình và Khóa API tùy chọn. Nhiều hồ sơ có thể cùng tồn tại và các cuộc hội thoại có thể chuyển đổi mô hình.

Hồ sơ, cuộc hội thoại, lịch sử tin nhắn hoàn chỉnh và kết quả cuộc gọi công cụ được **lưu trên máy chủ** thông qua chương trình phụ trợ trạng thái LSM đã định cấu hình. Phạm vi của họ được gắn với hiệu trưởng được xác thực. Khóa API được mã hóa bằng AES-GCM và không bao giờ được trả về từ điểm cuối danh sách hồ sơ hoặc chi tiết hồ sơ. Nó không được lưu trữ trong bộ lưu trữ của trình duyệt, được gửi đến mô hình dưới dạng lời nhắc hoặc được đưa vào nhật ký kiểm tra. Máy chủ trò chuyện chỉ chuyển nó tới API mô hình đã chọn.

Quá trình triển khai dựa trên tệp đầu tiên sẽ tạo `hosted-chat-encryption-key` trong thư mục trạng thái với chế độ 0600. **Sao lưu tệp này cùng với dữ liệu trạng thái. Nếu không có nó, các Khóa API đã lưu sẽ không thể được giải mã.** Nếu Bộ điều khiển sử dụng Redis, nhiều bản sao hoặc chương trình phụ trợ trạng thái không phải tệp khác, hãy định cấu hình khóa 32 byte URL-safe-base64 ổn định, được chia sẻ:

```env
LOCAL_SHELL_MCP_HOSTED_CHAT_ENCRYPTION_KEY=<base64url-encoded 32 random bytes>
```

Không xoay cài đặt này mà không di chuyển các cấu hình được mã hóa. Không sử dụng bộ lưu trữ trạng thái trong bộ nhớ khi cần có các cuộc hội thoại lâu dài.

Theo mặc định, chỉ các điểm cuối của mô hình HTTPS có tên máy chủ DNS mới được chấp nhận; các điểm cuối cục bộ/riêng tư và HTTP bị từ chối để giảm rủi ro giả mạo yêu cầu phía máy chủ. Quản trị viên cố tình lưu trữ một cổng mô hình riêng tư đáng tin cậy có thể chọn tham gia:

```env
LOCAL_SHELL_MCP_HOSTED_CHAT_ALLOW_PRIVATE_ENDPOINTS=true
```

Không bật tính năng này trên Bộ điều khiển nhiều người dùng không đáng tin cậy trừ khi người dùng được phép liên hệ với các dịch vụ nội bộ.

## Cuộc trò chuyện và ứng dụng MCP

Tạo cuộc trò chuyện bằng hồ sơ mẫu đã lưu. Mỗi lượt được gửi sẽ trở thành một tác vụ nền do máy chủ sở hữu; đóng trình duyệt không hủy tác vụ. Các cuộc gọi văn bản và công cụ đã hoàn thành được kiểm tra lâu dài giữa các bước mô hình/công cụ. Dừng lại một cách rõ ràng để làm gián đoạn. Khi khởi động lại Bộ điều khiển, các lần chạy bị gián đoạn được đánh dấu như vậy và có thể được tiếp tục ở lượt mới, nhưng **các lệnh gọi công cụ không xác định kết quả sẽ không bao giờ được tự động phát lại**.

Toàn bộ lịch sử tin nhắn của cuộc trò chuyện sẽ được lưu giữ trong bộ nhớ. Chỉ một cửa sổ giới hạn gần đây được gửi đến mô hình cùng một lúc để kiểm soát kích thước ngữ cảnh. Các lệnh gọi công cụ được gửi qua điểm cuối MCP đã được xác thực của LSM, duy trì tất cả các quyền của công cụ thông thường và hành vi kiểm tra/kiểm tra trước.

Lưu trữ sẽ ẩn cuộc trò chuyện khỏi danh sách thông thường và lưu dưới dạng `.json.zst` bằng bộ nén zstd đã dùng trong Audit. Nội dung lưu trữ không được lập chỉ mục tìm kiếm thông thường. Tại **Archived conversations** có thể tìm theo tiêu đề, xem chỉ đọc, khôi phục hoặc xóa vĩnh viễn. Bản sao mới được ghi trước khi xóa bản cũ để tránh mất dữ liệu.

### Hội thoại dài và nén ngữ cảnh

Toàn bộ tin nhắn và kết quả công cụ vẫn được giữ trên máy chủ. Cửa sổ ngữ cảnh được cấu hình trong hồ sơ mô hình: mặc định **32.768 token**, từ 8.192 đến 1.000.000. Cách ước lượng thận trọng theo UTF-8 tính cả định nghĩa công cụ. Khi gần **80%** cửa sổ, cùng mô hình sẽ tóm tắt các lượt hoàn tất trước đó, giữ mục tiêu, giới hạn, quyết định, tệp, kết quả và việc còn lại. Bản tóm tắt được lưu riêng; mô hình chỉ nhận tóm tắt và các tin nhắn gốc mới nhất.

Ngân sách được tính lại sau mỗi lần gọi công cụ. **Compact** cho phép nén thủ công khi không có lượt đang chạy. Nếu thất bại, bản tóm tắt cũ và lịch sử gốc không thay đổi. Số token chỉ là ước tính; lượt hiện tại quá lớn sẽ bị từ chối chứ không tự động cắt bỏ.

Mở **Không gian làm việc trực tiếp** để hiển thị tài nguyên Ứng dụng `workspace_open` MCP hiện có của LSM bên trong chế độ xem được nhúng. Máy chủ sử dụng cầu nối `@modelcontextprotocol/ext-apps` cho vòng đời ứng dụng, gia hạn thông tin xác thực, lệnh gọi công cụ và hành động giữa con người với đại lý. Không có trình quản lý tệp, thiết bị đầu cuối, kiểm toán hoặc giao diện người dùng công việc thứ hai nào được triển khai.

Tùy chọn đính kèm `session_id` cho phép Trò chuyện được lưu trữ sử dụng và hiển thị Phiên logic hiện có; nó không phân loại lại Phiên hoặc cấp quyền sở hữu Phiên trò chuyện được lưu trữ. Mã nhận dạng cuộc trò chuyện và mã nhận dạng Phiên hợp lý là riêng biệt.

## ranh giới

- Các yêu cầu mô hình sử dụng tính năng Hoàn thành trò chuyện tương thích với OpenAI với tính năng gọi công cụ; các giao thức của nhà cung cấp khác yêu cầu bộ chuyển đổi.
- Các biện pháp bảo vệ mỗi lượt bảo vệ việc lặp lại mô hình giới hạn và lệnh gọi công cụ. Các nhiệm vụ dài hơn có thể được tiếp tục ở lượt mới bằng cách sử dụng lịch sử lâu dài.
- Việc xóa cuộc trò chuyện là rõ ràng. Không có việc trục xuất lịch sử tự động nào được thực hiện.
- Bộ điều khiển phải có khả năng truy cập mạng bằng ứng dụng khách MCP của chính nó và trình duyệt phải được cấp phép cho API LSM Live Workspace.
