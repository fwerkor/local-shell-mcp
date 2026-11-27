<!-- i18n-source-sha256: 91fa7e8e41354be2761864ffe05d1efb85063953c79a40065ad61661cc15b836 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Quản lý và khắc phục sự cố

## Kiến trúc triển khai

Giao diện người dùng WebUI được phục vụ bởi Python Controller, và nơi lưu trữ dữ liệu của giao diện này cũng giống như các điểm cuối REST và MCP. Hệ thống lưu trữ dữ liệu mặc định sử dụng SQLite. Các tệp tin cài đặt được phát hành bao gồm cả các tài nguyên cần thiết để xây dựng giao diện người dùng. Việc xây dựng giao diện từ mã nguồn yêu cầu việc sử dụng các công cụ build JavaScript; không cần phải chạy Python Controller để thực hiện việc này. Node.js, MongoDB, Meilisearch, và hệ thống lưu trữ dữ liệu LibreChat cũng không cần thiết.

Hãy sử dụng tài liệu hướng dẫn [Quickstart](../getting-started/quickstart.md) và tài liệu hướng dẫn cấu hình [Configuration reference](../reference/configuration.md). Đối với việc xây dựng từ mã nguồn, hãy tham khảo hướng dẫn xây dựng giao diện WebUI tại [WebUI build instructions](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md).

## Đảm bảo tính an toàn trong quá trình triển khai.

Hãy sử dụng một proxy ngược có độ tin cậy cao, hoặc công cụ kết nối mạng dựa trên giao thức HTTPS. Đồng thời, cần áp dụng các biện pháp xác thực và sử dụng thông tin mật khó bị đánh cắp. Hãy giữ cho Controller nằm trong khu vực an toàn của container hoặc VM. Hạn chế việc truy cập vào hệ thống từ bên ngoài, đồng thời bảo vệ các thông tin cần thiết để truy cập hệ thống. Đừng để bất kỳ điểm tiếp nhận dữ liệu nào được công khai trên Internet.

Proxy cần hỗ trợ việc truyền dữ liệu một cách liên tục, không cần lưu trữ dữ liệu cho đến khi hoàn thành. Cần hỗ trợ việc sử dụng WebSocket cho các giao diện yêu cầu điều này. Đặt thời gian chờ phù hợp cho các yêu cầu dữ liệu lớn, đồng thời cho phép tải dữ liệu với kích thước tối đa được cho phép. Giữ URL công khai nhất quán với nguồn gốc trình duyệt và các kết nối OAuth. Không sửa chữa các lỗi liên quan đến TLS bằng cách vô hiệu hóa việc kiểm tra chứng chỉ SSL trên toàn cục.

Các yêu cầu được gửi đến Controller. Các thông điệp, tệp đính kèm và kết quả từ các công cụ có thể được gửi đến các API được chọn. Hãy xem xét kỹ lưỡng các điều khoản xử lý dữ liệu của nhà cung cấp trước khi sử dụng các nội dung nhạy cảm. Đồng thời, hãy bảo vệ các bí mật liên quan đến MCP và các token dùng để kích hoạt người dùng bên ngoài.

## Trạng thái hiện tại, bản sao dự phòng và việc nâng cấp hệ thống

Định dạng mặc định của thư mục là `.local-shell-mcp`, nằm trong khu vực làm việc được cấu hình. Giá trị `LOCAL_SHELL_MCP_STATE_DIR` có thể thay đổi giá trị này. Cơ sở dữ liệu được chia sẻ là `lsm.sqlite3`. Các thông tin liên quan đến chat, dự án, thiết lập, các tác nhân, bộ nhớ, lịch trình và trạng thái thực thi đều được lưu trữ trên máy chủ. Còn các tệp đính kèm, tệp trong khu vực làm việc, và các tài nguyên khác thì có thể được lưu trữ bên ngoài cơ sở dữ liệu.

Hãy tạo bản sao lưu toàn bộ thư mục state, cùng với các thiết lập cần thiết bên ngoài thư mục đó. Đồng thời, hãy chuẩn bị các tệp tin liên quan đến môi trường triển khai và thông tin riêng tư cần thiết. Hãy coi trọng việc sao lưu dữ liệu một cách cẩn thận. Việc sao lưu chỉ bao gồm cơ sở dữ liệu có thể làm mất đi các tệp đính kèm hoặc các thiết lập liên quan. Hãy sử dụng cơ chế sao lưu hiệu quả từ phía Controller, hoặc sử dụng cơ chế sao lưu từ SQLite. Việc sao lưu chỉ bao gồm tệp cơ sở dữ liệu chính của SQLite có thể làm mất đi nội dung được ghi vào cơ sở dữ liệu WAL. Hãy kiểm tra bản sao lưu bằng cách khôi phục chúng vào một môi trường thử nghiệm riêng biệt.

Trước khi thực hiện việc nâng cấp, hãy ghi lại phiên bản hiện tại của hệ thống, đường dẫn để chạy chương trình, cấu hình, vị trí lưu trữ dữ liệu, và các tác vụ đang được thực hiện. Hãy tạm dừng hoặc loại bỏ các tác vụ liên quan trước khi nâng cấp. Sau đó, sao lưu toàn bộ dữ liệu một cách đúng cách. Hãy kiểm tra lại các chức năng như xác thực người dùng, lịch sử trò chuyện, quá trình tạo mô hình, việc truyền dữ liệu qua streaming, các tác vụ được lên lịch… Việc chuyển đổi sang phiên bản mới của SQLite được hỗ trợ ngay khi khởi động lại hệ thống. Hãy giữ lại các tệp dữ liệu cũ cho đến khi bạn xác nhận rằng việc chuyển đổi đã diễn ra thành công. Đừng thay thế thư mục lưu trữ dữ liệu chính bằng một thư mục test rỗng.

Việc rollback không chỉ đơn thuần là thay đổi cấu hình của cơ sở dữ liệu; nó còn giúp khôi phục trạng thái ban đầu khi có sự thay đổi trong cơ sở dữ liệu. Hãy khôi phục trạng thái tương thích khi cần thiết, và tránh việc sử dụng hai Controller được cấu hình riêng biệt trên cùng một hệ thống lưu trữ.

## Điều tra nguyên nhân gây ra sự cố.

| Các triệu chứng. | Kiểm tra trước tiên. |
|---|---|
| Không thể tải nội dung giao diện người dùng. | Process của bộ điều khiển, gói phần mềm frontend, đường dẫn URL chính xác, công cụ lưu trữ và việc xác thực người dùng. |
| Thiếu model cần thiết. | Cấu hình kênh truyền thông, ID của model, quyền truy cập tài khoản. |
| Lỗi HTTP 401/403 từ nhà cung cấp dịch vụ. | Chìa khóa API/tài khoản, quyền truy cập của nhà cung cấp dịch vụ, kênh và giao thức được chọn. |
| HTTP 429 | Hạn chế về tốc độ truyền dữ liệu, số lượng yêu cầu đồng thời, trạng thái tài khoản/chi phí. |
| HTTP 400/413/422 | Tính tương thích của các yêu cầu, kích thước dữ liệu đầu vào, giới hạn về số lượng tệp đính kèm, các tham số của model. |
| Lỗi HTTP 5xx hoặc thời gian chờ quá dài. | Tình trạng sức khỏe của nhà cung cấp dịch vụ, mạng, khả năng phục vụ của hệ thống, thời gian chờ của proxy. |
| Việc truyền dữ liệu bị ngừng lại. | Cần kết nối lại hoặc khôi phục lại trạng thái ban đầu; kiểm tra tình trạng phát sinh lỗi và thông tin chi tiết về lỗi đó. |
| Phần mềm không thể sử dụng được. | Tính năng tùy chọn: Khả năng của các nhân viên, danh sách quyền truy cập của máy móc, phạm vi quyền truy cập theo chuẩn OAuth, các thiết bị điều khiển. |
| Nhân viên không có mặt trên hệ thống | Đăng ký người lao động, kết nối ra ngoài, thông tin về hoạt động của hệ thống, và các bản ghi nhật ký của Controller. |
| Chưa có xác nhận/đề xuất nào được thực hiện. | Mở cuộc trò chuyện và kiểm tra các hành động cần thực hiện. |
| Lịch trình không được thực hiện. | Trạng thái được kích hoạt, khu vực múi giờ, thiết bị/ kênh truyền thông, mục tiêu, quyền hạn đã lưu lại, lần thực hiện cuối cùng. |

Đừng cho rằng tất cả các lỗi HTTP đều xuất phát từ cùng một dịch vụ. Hãy phân biệt rõ giữa các loại lỗi như: lỗi khi đăng nhập bằng LSM, lỗi từ API của nền tảng upstream, lỗi từ bên ngoài (MCP), và lỗi trong quá trình truyền dữ liệu của Worker. Hãy kiểm tra chi tiết các lỗi đó, cũng như các bản ghi nhật ký liên quan. Trước khi chia sẻ thông tin này, hãy xóa bỏ các thông tin quan trọng như khóa đăng nhập, token truyền dữ liệu, và URL liên kết.

## Các dịch vụ có khả năng tái tạo lại quá trình xử lý lỗi.

Trước khi mô hình bắt đầu phản hồi, các lỗi kết nối tạm thời và một số lỗi HTTP (408, 429, 500, 502, 503, 504) có thể được thử lại với thời gian chờ giới hạn. Các khoảng chờ thông thường hiện tại là 1, 2, 4, 8, 16, 30, 30 và 30 giây (tám lần thử lại sau yêu cầu đầu tiên). HTTP Retry-After có thể kéo dài khoảng chờ đến 120 giây; một số lỗi truyền phát thêm độ lệch ngẫu nhiên. Giới hạn thử lại áp dụng cho từng yêu cầu mô hình, không phải tổng số lần trong cả cuộc trò chuyện. Việc nén ngữ cảnh có cơ chế khôi phục riêng. Giới hạn tốc độ do hết tín dụng có thể kéo dài đến khi nhà cung cấp bổ sung hạn mức. Thử lại tự động không bảo đảm thành công và không làm gói đăng ký trở thành không giới hạn.

Sự gián đoạn trong quá trình xử lý yêu cầu khác với lỗi xảy ra trước khi hệ thống trả lời yêu cầu đầu tiên. Đừng tin tưởng vào việc tự động thực hiện lại các thao tác đã được thực hiện một phần. Hãy kiểm tra lại dữ liệu đã lưu và trạng thái bên ngoài trước khi tái gửi yêu cầu. Nếu quá trình xử lý vẫn đang diễn ra, hãy kết nối lại thay vì bắt đầu lại từ đầu. Nếu quá trình xử lý thất bại, hãy sử dụng các chức năng hồi phục hoặc tái gửi yêu cầu một cách phù hợp, hoặc bắt đầu một cuộc trò chuyện mới nếu cuộc trò chuyện ban đầu không thể tiếp tục được.

Những lỗi liên quan đến việc nén ngữ cảnh nên được kiểm tra riêng biệt so với các lỗi thông thường trong quá trình tạo mô hình. Hãy kiểm tra giới hạn ngữ cảnh, tính tương thích giữa các mô hình, kết quả từ công cụ, và quy định về quỹ đất có sẵn. Xem thêm phần [Memory and context](context.md).

## Nội dung cần ghi trong bản báo cáo lỗi là gì?

Hãy ghi lại phiên bản và phương thức cài đặt của LSM, hệ điều hành sử dụng, loại giao thức được sử dụng, loại điểm cuối đã được xử lý an ninh, ID của mô hình, khoảng thời gian tương ứng, các bước cần thực hiện để tạo ra tình huống tương tự, thông tin liên quan đến trạng thái chat/điều khiển, cũng như thông tin chi tiết về các lỗi xảy ra. Đối với các vấn đề xảy ra từ xa, hãy ghi rõ phiên bản của Worker, tên máy tính, và trạng thái của chức năng heartbeat/poll. Nếu có thể, hãy đưa vào một ví dụ cụ thể về cách tạo ra tình huống tương tự. Đừng bao giờ gửi các khóa API, token OAuth, thông tin cá nhân hoặc dữ liệu không cần thiết.
