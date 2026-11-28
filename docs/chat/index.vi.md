<!-- i18n-source-sha256: 8ec601aa8e9c57afef769d8346567626355ccf88e122e3296735b7af3639c562 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# WebUI Chat

LSM WebUI Chat là một không gian làm việc dành cho các trợ lý AI, được xây dựng bên trong hệ thống Controller. Bạn có thể sử dụng chính mô hình AI của mình hoặc một tài khoản được hỗ trợ để truy cập vào công cụ và máy tính của riêng mình. Không cần phải sử dụng bất kỳ ứng dụng khách ngoại tuyến nào cả. Các ứng dụng khách bên ngoài vẫn có thể kết nối với hệ thống Controller một cách độc lập.

## Những bộ phận này kết hợp với nhau như thế nào?

- **Controller:** Đó là dịch vụ Python chịu trách nhiệm xử lý các yêu cầu từ trình duyệt, thực hiện các lệnh cần thiết, lên lịch thực hiện các công việc, và duy trì trạng thái ổn định của hệ thống.
- **Kênh truyền dữ liệu:** Đó là kết nối với API của một mô hình cụ thể, hoặc việc xác thực tài khoản được hỗ trợ. Kênh này có các thông tin cá nhân riêng biệt, giao thức sử dụng, danh sách các mô hình và các thiết lập liên quan.
- **Mô hình:** Đây là mã định danh của một mô hình trong một kênh truyền thông cụ thể. Việc sử dụng cùng một mã định danh cho hai kênh truyền thông không có nghĩa là chúng thuộc cùng một điểm cuối.
- **Người đại diện:** Đó là một cấu hình có thể được tái sử dụng, bao gồm cả mô hình, hướng dẫn, công cụ, kỹ năng và quyền hạn cần thiết để thực hiện công việc.
- **Trò chuyện:** Các tin nhắn đã được lưu lại, các thiết lập liên quan, lịch sử thực hiện các tác vụ, và mối liên hệ giữa mô hình/Agent với các tác vụ được thực hiện.
- **Dự án:** Một nhóm các cuộc trò chuyện có những quy tắc chung được chia sẻ giữa các thành viên trong nhóm.
- **Nhân viên:** Đó là mục tiêu thực thi được kết nối với hệ thống bên ngoài. Nó không phải là nhà cung cấp mô hình hay máy chủ trò chuyện riêng biệt.
- **Logical Session**: Đây là một công cụ dùng để xác định danh tính của các tác vụ trên phía máy khách, khác với ID của cuộc trò chuyện thông thường. Một chat có thể sử dụng Logical Session để theo dõi các mục tiêu, tiến độ công việc và hoạt động liên quan đến các công cụ được sử dụng trong quá trình trò chuyện.

API của mô hình này nhận vào các thông tin liên quan đến ngữ cảnh mà mô hình có thể hiểu được, cùng với kết quả từ các công cụ được sử dụng. Trình điều khiển sẽ thực thi các công cụ được phép sử dụng; mô hình không trực tiếp kết nối với bất kỳ công cụ nào, cũng không nhận được khóa API của mô hình từ bất kỳ nguồn nào. Bộ trình chiếu trên trình duyệt sẽ hiển thị quá trình trò chuyện và kiểm soát hoạt động của trình điều khiển.

## Hãy chọn một người hướng dẫn phù hợp.

| Tôi muốn… | Đọc |
|---|---|
| Cài đặt, đăng nhập và thực hiện nhiệm vụ đầu tiên. | [Quy trình bắt đầu nhanh](../getting-started/web-workspace.md) |
| Kết nối với API hoặc tài khoản cần sử dụng. | [Các kênh và mô hình](channels.md) |
| Xây dựng các tác nhân có thể được sử dụng lại, đồng thời phân công công việc cho chúng. | [Tác nhân và kỹ năng](agents.md) |
| Quản lý các cuộc trò chuyện, tệp tin và dự án. | [Các cuộc trò chuyện](conversations.md) |
| Hiểu rõ cách lưu trữ thông tin và quản lý ngân sách liên quan đến các cuộc trò chuyện. | [Bộ nhớ và bối cảnh](context.md) |
| Hạn chế việc thực thi các công cụ MCP, đồng thời quản lý chúng một cách hiệu quả. | [Các công cụ và quyền hạn](permissions.md) |
| Thực hiện các tác vụ và lịch trình trong thời gian dài. | [Mục tiêu và việc tự động hóa](automation.md) |
| Tìm kiếm thông tin trên web và đọc các tài liệu liên quan. | [Tìm kiếm trên mạng](../guides/webui-network-search.md) |
| Vận hành, sao lưu và gỡ lỗi các bản triển khai. | [Quản lý và khắc phục sự cố](administration.md) |

## Những nguyên tắc cơ bản.

Hãy bắt đầu với việc yêu cầu chỉ xem nội dung của một máy tính cụ thể. Kiểm tra kết quả đầu ra của công cụ trước khi thực hiện bất kỳ thay đổi nào. Một mô hình có thể không chính xác, ngay cả khi công cụ hoạt động tốt. Các thông tin liên quan đến tài khoản, lưu trữ tin nhắn, quyền truy cập máy tính và sự chấp thuận của công cụ là những yếu tố riêng biệt; việc thay đổi một trong số chúng không đồng nghĩa với việc có quyền truy cập vào các yếu tố còn lại. Đặc biệt, điểm kết nối công khai nên được bảo vệ như một cơ sở điều khiển từ xa.

Đối với đường dẫn kết nối bên ngoài giữa MCP và khách hàng, xin xem mục [Kết nối khách hàng](../clients/connectivity.md). Đối với các tham số cần thiết để sử dụng công cụ này, xin xem mục [Tài liệu tham khảo về công cụ](../reference/tools.md).
