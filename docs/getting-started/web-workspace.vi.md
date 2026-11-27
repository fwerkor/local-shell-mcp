<!-- i18n-source-sha256: 01cf883cb71925e93fabc21d32315ef8c869ee2ea548e54a0347e2f6b730a327 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Quy trình khởi động nhanh cho WebUI Chat

Trang làm việc chung của LSM được tích hợp các tính năng như trò chuyện thông qua AI, các dự án, các “Người lãnh đạo” và các trang quản lý của người điều khiển hệ thống. Trang này được vận hành bởi trình điều khiển Python, và sử dụng cơ sở dữ liệu SQLite để xử lý các tác vụ liên quan. Không cần phải có máy chủ trò chuyện riêng biệt. Các client bên ngoài như [ChatGPT](chatgpt-connector.md) và [Gemini](gemini-spark.md) vẫn được hỗ trợ.

## 1. Khởi động Controller

Hãy làm theo hướng dẫn [tiếp nhận cài đặt](quickstart.md) để chọn môi trường chạy phù hợp với bạn. Hãy đảm bảo rằng giao diện WebUI được kích hoạt, và sử dụng cơ chế lưu trữ liên tục. Các thiết lập mặc định sẽ được áp dụng theo quy định thông thường.

```env
LOCAL_SHELL_MCP_STATE_BACKEND=sqlite
LOCAL_SHELL_MCP_UI_ENABLED=true
```

Sau khi xuất khẩu môi trường hoạt động của dịch vụ của bạn, hãy khởi động máy chủ điều khiển.

```sh
local-shell-mcp --mode mcp
```

Đối với việc phát hành dưới dạng một hàng duy nhất, hãy sử dụng tập tin thực thi đã tải về. Controller được cài đặt sẽ chạy phần mềm giao diện người dùng đã được biên dịch; công cụ xây dựng JavaScript chỉ cần được sử dụng để tạo các bản mã nguồn. Xem [Hướng dẫn xây dựng WebUI](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md) để biết thêm chi tiết.

## 2. Mở không gian làm việc trên trình duyệt

Hãy truy cập trang web `http://127.0.0.1:8765/ui` từ máy chủ Controller. Hoặc bạn có thể truy cập bằng URL HTTPS được cấu hình, kết thúc bằng chữ `/ui`. Hãy đăng nhập với thông tin xác thực LSM đã được cấu hình cho phiên bản triển khai này. Hãy sử dụng giao thức HTTPS để truy cập từ xa. Các trang chat và trang điều khiển sử dụng cùng một nguồn gốc.

## 3. Thêm kênh mô hình

Hãy mở công cụ chọn mô hình và quản lý kênh truyền thông. Thêm một kênh API vào hoặc kết nối với tài khoản được hỗ trợ. Đối với các điểm cuối tương thích với OpenAI, hãy nhập tên kênh, chọn Chat Completions, nhập URL cơ sở của API và thông tin xác thực. Sau đó, bạn có thể tìm kiếm các mô hình hoặc nhập ID của mô hình đã biết. Hãy lưu lại cấu hình và chọn một mô hình phù hợp.

Đối với dịch vụ suy luận cục bộ, hãy sử dụng địa chỉ mà có thể truy cập được từ Controller, chứ không chỉ từ trình duyệt của bạn. Ví dụ, `http://127.0.0.1:8080/v1` là địa chỉ phù hợp nếu dịch vụ suy luận hoạt động trên địa chỉ này trong mạng tên miền của Controller. Xem [Channels and models](../chat/channels.md) để biết thêm thông tin về các giao thức, quyền truy cập vào tài khoản, việc phát hiện mô hình, và các giới hạn liên quan đến ngữ cảnh.

## 4. Chạy tác vụ đầu tiên

Hãy bắt đầu một cuộc trò chuyện và đặt một câu hỏi đơn giản để kiểm tra khả năng kết nối của mô hình. Sau đó, hãy thử sử dụng công cụ chỉ có chức năng đọc dữ liệu mà thôi.

```text
Hãy liệt kê các tệp tin trong thư mục gốc của không gian làm việc của Controller.
Xin hãy cho tôi biết bạn đã kiểm tra chiếc máy nào, và tổng kết kết quả của việc kiểm tra đó như thế nào.
Xin đừng thay đổi các tập tin hoặc thực hiện bất kỳ thao tác ghi dữ liệu nào.
```

Hãy kiểm tra kết quả thực tế của công cụ đó. Nếu có công cụ nào bị thiếu, hãy kiểm tra các tùy chọn liên quan đến công cụ trong chat, cài đặt của người quản lý và quyền truy cập của máy tính. Hãy sử dụng người quản lý đã được lưu trước đó để thực hiện các nhiệm vụ lặp đi lặp lại, và thiết lập quyền truy cập cho người quản lý đó một cách rõ ràng. Xem thêm [Công cụ và quyền truy cập](../chat/permissions.md).

![Trò chuyện qua WebUI với hình ảnh minh họa cụ thể](../assets/chat/chat-workspace.png)

Các hình ảnh chụp màn hình trong hướng dẫn này và các trang tiếp theo được lấy từ một hệ thống kiểm soát độc lập, sử dụng mô hình minh họa cụ thể. Những hình ảnh này không chứa thông tin về tài khoản sản xuất hay các cuộc trò chuyện nào cả. Các nhãn giao diện người dùng bằng tiếng Anh có thể khác với ngôn ngữ được chọn trong hệ thống.

## 5. Khám phá không gian làm việc

| Khu vực/Phạm vi | Để làm gì nhỉ? |
|---|---|
| Trò chuyện và quản lý dự án | Khởi tạo và tìm kiếm các cuộc trò chuyện; tổ chức các dự án, gán nhãn cho chúng, và lưu lại các tin nhắn cần thiết. |
| Agents | Các mô hình, hướng dẫn và cấu hình công cụ có thể được sử dụng lại nhiều lần. |
| Ký ức và kỹ năng | Quản lý các kiến thức và hướng dẫn có thể được sử dụng lại. |
| Các cuộc trò chuyện được lên lịch. | Chạy chương trình của người quản lý đã được lưu lại, với câu hỏi lặp đi lặp lại. |
| Tệp tin và môi trường hoạt động. | Hãy kiểm tra hoặc thực hiện các thao tác liên quan đến môi trường Controller và Worker. |
| Màn hình làm việc. | Kiểm tra và kiểm soát các phiên làm việc từ xa. |
| Các phiên họp, công việc và việc kiểm toán | Kiểm tra các tác vụ có tính chất bền vững, tiến độ thực hiện công việc, cũng như hoạt động của các công cụ hỗ trợ trong quá trình thực hiện công việc. |
| Các máy móc và các thiết bị bên ngoài | Quản lý công nhân và các máy chủ MCP được đặt trong cấu trúc lồng nhau. |

Bộ công cụ điều khiển chính xác sẽ phụ thuộc vào cách bạn triển khai hệ thống, tài khoản của bạn, cũng như các tính năng được kích hoạt trong hệ thống đó. Việc đóng cửa trình duyệt không có nghĩa là quá trình tạo dữ liệu trên máy chủ sẽ bị ngừng hoàn toàn; hãy sử dụng công cụ “stop” khi bạn cần ngắt quá trình này lại.

## Những bước tiếp theo

Hãy đọc hướng dẫn sử dụng WebUI Chat tại địa chỉ [WebUI Chat guide](../chat/index.md) để biết chi tiết về quy trình hoạt động của hệ thống. Ngoài ra, hãy tham khảo phần [Administration and troubleshooting](../chat/administration.md) để biết cách thiết lập hệ thống, sao lưu dữ liệu và khắc phục các lỗi có thể xảy ra.
