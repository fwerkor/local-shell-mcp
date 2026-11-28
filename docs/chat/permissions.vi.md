<!-- i18n-source-sha256: e5ebd5f8cfb42332f4e38d63eabe47a6274ceacf919130202203bd85917f3469 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Công cụ, máy tính và quyền truy cập.

## Các lớp xác thực.

Một công cụ được liệt kê trong danh sách này không đảm bảo rằng người dùng có quyền thực thi công cụ đó. Việc xác thực hiệu quả đòi hỏi sự kết hợp giữa các hạn chế từ phía Controller, phạm vi quyền của người dùng đã được xác thực, chính sách máy chủ, khả năng của các công cụ, và sự chấp thuận từ phía người dùng. Chỉ có những hướng dẫn rõ ràng thôi là không đủ để đảm bảo quyền truy cập vào công cụ đó.

Các máy tính đã đăng ký, bao gồm cả máy tính dùng để thực hiện các tác vụ điều khiển cục bộ, mặc định được cấp quyền đọc/ghi dữ liệu cho chính máy tính đó. Tuy nhiên, việc cấp quyền này nên được hạn chế trong những trường hợp cần thiết. Các tên máy tính không rõ ràng sẽ không được cấp quyền đọc/ghi dữ liệu. Cục điều khiển có thể tắt chức năng thực hiện các tác vụ từ xa hoặc từ máy tính cục bộ.

## Quyền truy cập vào máy móc

| Truy cập | Ý nghĩa/Chức năng |
|---|---|
| không có | Các hoạt động của máy móc không thể thực hiện được. |
| Chỉ đọc | Chỉ những thao tác được xếp loại là “chỉ đọc” mới được phép thực hiện. Việc thực hiện các thao tác khác như sử dụng shell hoặc Python để thực hiện các tác vụ tự do không được coi là một thao tác “chỉ đọc”. |
| Đọc/ghi | Cho phép các thao tác đọc, chỉnh sửa hoặc thực thi được thực hiện bởi những người được ủy quyền. Tuy nhiên, vẫn còn một số hạn chế khác cần tuân thủ. |
| Kế thừa | Hãy sử dụng các mặc định phù hợp ở cấp độ cao hơn, thay vì phải áp dụng các quy tắc bổ sung một cách cụ thể. |

![Quyền truy cập và chế độ phê duyệt của máy trong một cuộc trò chuyện](../assets/chat/machine-permissions.png)

Đặt giá trị mặc định toàn cục, thiết lập ghi đè theo dự án và theo từng cuộc trò chuyện trong phần quyền truy cập máy. Thiết lập của cuộc trò chuyện được ưu tiên hơn thiết lập dự án, còn thiết lập dự án được ưu tiên hơn mặc định toàn cục. Agent có thể hạn chế quyền truy cập thêm theo từng máy hoặc chính sách mặc định của mình; quyền được cấp rõ ràng cho Agent không thể vượt qua giới hạn của danh tính đã xác thực hoặc của Controller.

Ví dụ: chính sách toàn cục cho phép đọc/ghi, dự án ghi đè thành chỉ đọc và Agent được cấp quyền đọc/ghi thì cuộc trò chuyện trong dự án có quyền chỉ đọc, trừ khi chính sách của cuộc trò chuyện ghi đè rõ ràng. Tuy vậy, thiết lập đọc/ghi của cuộc trò chuyện không thể vượt quá giới hạn chỉ đọc của Agent.

Việc thực hiện các tác vụ có kế hoạch với một “Agent” cụ thể sẽ sử dụng chính chính sách của máy tính thuộc về Agent đó, cùng với các phạm vi thực thi được lưu trữ. Điều này khác với việc kế thừa các tùy chọn cấu hình thông thường từ máy tính chát. Xem thêm mục [Mục tiêu và tự động hóa](automation.md). Hãy sử dụng một “Agent” chuyên dụng để thực hiện các tác vụ không cần người quản lý.

## Xác nhận từ phía công cụ

| Chế độ hoạt động | Hành vi |
|---|---|
| tự động | Các lệnh được phê duyệt sẽ được thực hiện mà không cần xác nhận bổ sung, trừ khi có chính sách riêng biệt yêu cầu điều đó. |
| Xem xét các hoạt động rủi ro | Người quản lý yêu cầu xem xét lại các hoạt động được coi là nguy hiểm, bao gồm cả những lệnh dòng lệnh tự ý và nhiều cuộc gọi ngoại tuyến khác. |
| Xem lại tất cả các công cụ | Yêu cầu được phê duyệt trước khi sử dụng các công cụ thông thường. |

Thiết lập phê duyệt của cuộc trò chuyện có thể kế thừa mặc định của Agent và mặc định toàn cục. Các quy tắc từ chối hoặc phê duyệt rõ ràng hiện có vẫn được áp dụng. Agent con không thể nới lỏng chế độ phê duyệt của Agent cha. Phê duyệt độc lập với quyền truy cập: phê duyệt một thao tác máy bị từ chối không cấp quyền truy cập máy.

Hãy xem xét kỹ lưỡng các lập luận, mục tiêu và những tác động có thể xảy ra trước khi quyết định đồng ý. Đối với các quy trình làm việc không được kiểm soát, cần phải cài đặt chương trình phân loại và chính sách phê duyệt một cách cẩn thận. Việc yêu cầu sự phê duyệt từ con người có thể làm chậm tiến độ công việc. Đừng mở rộng quyền truy cập chỉ để loại bỏ các yêu cầu cần được xử lý.

## Các công cụ MCP bản địa và các công cụ ngoại vi

Các công cụ bản địa hoạt động trên Controller và các Workers được đăng ký thông qua LSM. Bộ quản lý công cụ bao gồm các chức năng liên quan đến việc xử lý tập tin, shell và các tác vụ, cũng như các chức năng liên quan đến trình duyệt và giao diện người dùng. Ngoài ra, bộ quản lý công cụ còn hỗ trợ các chức năng liên quan đến việc phát hiện máy tính từ xa, các phiên làm việc logic, và nhiều chức năng khác nữa. Vui lòng tham khảo tài liệu hướng dẫn sử dụng công cụ tại địa chỉ [Tools reference](../reference/tools.md) để biết chi tiết về cấu trúc các đối số cần sử dụng. Để kết nối các máy tính từ xa, vui lòng tham khảo tài liệu tại địa chỉ [Remote workers](../guides/remote-workers.md).

Quản lý các máy chủ MCP được đặt trong cấu hình lồng nhau trong WebUI. Các cấu hình hỗ trợ bao gồm việc sử dụng phương thức truyền dữ liệu cục bộ và phương thức truyền dữ liệu qua HTTP từ xa. Ngoài ra, còn có khả năng sử dụng các biến môi trường hoặc tiêu đề cụ thể của từng máy chủ. Hãy bật chức năng MCP bên ngoài trong chat và trong các công cụ liên quan. Công cụ này có thể phát hiện, kiểm tra và kích hoạt các công cụ bên ngoài có sẵn; quyền truy cập và việc xác thực các công cụ này vẫn được áp dụng như bình thường.

Công cụ MCP bên ngoài có thể hoạt động độc lập với ACL máy gốc: API từ xa bên ngoài có thể sửa đổi tài nguyên ngay cả khi quyền truy cập máy cục bộ bị tắt. Kiểm tra riêng các quyền và thông tin xác thực của dịch vụ bên ngoài. Không cài đặt máy chủ stdio không đáng tin cậy trên Controller chứa tệp nhạy cảm.

## Yêu cầu người dùng và tùy chọn chức năng

“Ask User” cho phép các tác nhân yêu cầu thông tin từ con người một cách có hệ thống, thay vì phải tự suy đoán. Các tác nhân cũng có thể sử dụng công cụ điều khiển để trả lời các câu hỏi được đưa ra. Đây là yêu cầu về thông tin, chứ không phải là yêu cầu được phép vượt qua các hạn chế của công cụ. Khi nhiệm vụ không được xử lý, cần hướng dẫn các tác nhân cách xử lý những tình huống bất định, và kiểm tra các tương tác đang chờ xử lý trước khi cho rằng nhiệm vụ đã hoàn thành.

Công cụ này cho phép kiểm soát các chức năng như tìm kiếm mạng, sử dụng công cụ MCP bên ngoài, và quản lý bộ nhớ. Những chức năng này được cung cấp cho mô hình; chúng không liên quan đến việc xác thực người dùng. Việc vô hiệu hóa một chức năng không làm mất đi kết quả đã được ghi lại trước đó. Tính năng tìm kiếm mạng được kích hoạt mặc định, và nó sử dụng các công cụ web chỉ có quyền đọc thông tin. Xem thêm [Tài liệu hướng dẫn về tìm kiếm mạng](../guides/webui-network-search.md).

## Kiểm toán và xác minh

Hãy kiểm tra các lệnh được thực thi bởi công cụ đó, cùng với kết quả mà chúng mang lại trong chat. Hãy mở rộng thông tin chi tiết khi xác định nguyên nhân gây ra sự cố. Lịch sử giám sát của Controller ghi lại các hoạt động của các công cụ tự động; các tác vụ/phiên làm việc cũng được ghi lại để biết được tình trạng thực hiện các tác vụ đó như thế nào. Một phản hồi API thành công có nghĩa là công cụ đã trả về kết quả, nhưng điều đó không có nghĩa là thao tác yêu cầu đã đạt được mục tiêu của mình. Hãy kiểm tra lại các thông tin liên quan đến việc ghi dữ liệu, trạng thái các tác vụ từ xa, và tình trạng triển khai một cách độc lập. Xem thêm thông tin trong [Lịch sử giám sát](../guides/audit-log.md).
