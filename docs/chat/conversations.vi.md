<!-- i18n-source-sha256: 012f0d9f7b350fcf47e3fd6afdf2fc9e7044ff28cb2eca7c029c3d6af35f3b04 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Thông tin về cuộc trò chuyện và dự án.

## Tạo và tiếp tục một cuộc trò chuyện mới.

Hãy mở một cuộc trò chuyện mới, chọn kênh/người dùng hoặc nhân viên cần giao nhiệm vụ, sau đó nhập tin nhắn cần gửi đi. Cuộc trò chuyện diễn ra trên trình quản lý, và thông tin được truyền về trình duyệt. Việc tải lại trang hoặc đóng tab không có nghĩa là việc thực hiện nhiệm vụ đã bị hủy bỏ. Bạn có thể sử dụng nút “Dừng” để ngắt quá trình thực hiện nhiệm vụ, và kiểm tra trạng thái của nhiệm vụ trước khi bắt đầu một nhiệm vụ mới.

Các cuộc trò chuyện được lưu giữ sẽ vẫn giữ liên kết với mô hình/Agents tương ứng của chúng. Bạn có thể chọn mô hình khác nếu muốn. Cuộc trò chuyện không phải là “Logical Session”: nó chứa các tin nhắn từ người dùng và các thông tin liên quan đến mô hình. Trong khi đó, “Logical Session” thì chứa các mục tiêu công việc, tiến độ và kế hoạch liên quan đến công cụ sử dụng. Hãy giữ lại các ID liên quan khi chuyển giao một nhiệm vụ dài hạn.

## Sắp xếp và tìm kiếm công việc cần thực hiện.

Hãy sử dụng các dự án để kết hợp các cuộc trò chuyện có liên quan lại với nhau, đồng thời thiết lập quyền truy cập chung cho các máy tính tham gia vào dự án đó. Một dự án có thể chứa nhiều cuộc trò chuyện riêng biệt. Hãy di chuyển hoặc tạo các cuộc trò chuyện vào dự án phù hợp, thay vì giả định rằng các cuộc trò chuyện này có cùng nội dung như nhau. Dự án đang hoạt động có thể cung cấp thông tin về cách sắp xếp các cuộc trò chuyện trong dự án đó cho Agent.

Các thẻ giúp phân loại các cuộc trò chuyện; các điểm đánh dấu tin nhắn cho biết vị trí của từng tin nhắn, và giúp người dùng có thể quay lại những kết quả hữu ích. Những tính năng này khác với việc ghim một cuộc trò chuyện cụ thể vào một vị trí nhất định. Hãy sử dụng tiêu đề cuộc trò chuyện, chức năng tìm kiếm, chức năng lưu trữ và các chỉ báo để giúp người dùng dễ dàng quản lý các thông tin liên quan đến cuộc trò chuyện của mình.

Việc lưu trữ các cuộc trò chuyện giúp chuyển chúng ra khỏi danh sách thông thường, mà không xóa đi dữ liệu đã được lưu lại. Có thể khôi phục các cuộc trò chuyện này từ giao diện lưu trữ khi cần thiết. Việc xóa một cuộc trò chuyện là hành động có hại; vì vậy không nên sử dụng phương pháp này để thay thế việc lưu trữ các cuộc trò chuyện. Phiên bản hiện tại sử dụng cơ sở dữ liệu SQLite để lưu trữ thông tin về các cuộc trò chuyện. Đừng cố gắng sử dụng định dạng lưu trữ cũ của Hosted Chat.

## Các thao tác gửi tin nhắn và thực hiện các nhiệm vụ

Các tùy chọn liên quan đến thông điệp có sẵn phụ thuộc vào nội dung của thông điệp và trạng thái hiện tại của nó. Nếu cần thiết, bạn có thể chỉnh sửa hoặc thử lại quá trình thực hiện thông điệp đó. Ngoài ra, bạn cũng có thể xóa các lần thực hiện thông điệp do người dùng/trợ lý thực hiện nếu chúng không còn cần thiết nữa. Việc xóa thông tin sẽ làm thay đổi lịch sử cuộc trò chuyện được lưu lại, và điều này có thể ảnh hưởng đến các tình huống sau này. Việc xóa thông tin không thể khôi phục lại các lệnh được thực hiện bằng shell, các bản ghi nhật ký từ xa, hoặc các thao tác cập nhật dữ liệu qua Git hay các tác động bên ngoài khác.

Khi cố gắng thực hiện lại một lần nữa sau khi thất bại, hãy đọc kỹ thông tin về các lỗi xảy ra, và kiểm tra xem các lệnh được thực hiện trước đó đã diễn ra như thế nào. Nếu việc ghi dữ liệu có thể thành công trước khi kết nối bị gián đoạn, hãy kiểm tra trạng thái bên ngoài trước khi tiếp tục quá trình này. Nếu còn một thông báo nào đang chờ xử lý, hoặc một quá trình khác đang diễn ra, hãy sử dụng các công cụ và thông tin hiện có để quản lý tình hình, thay vì cho rằng nhiều quá trình cùng lúc diễn ra trong cùng một chat. Bảng hiển thị các thông báo chờ giúp bạn kiểm tra các lần thực hiện tiếp theo; công cụ hướng dẫn sẽ cố gắng đưa ra các chỉ dẫn một cách an toàn, sau khi các lệnh đang được thực hiện hoàn tất. Cả hai thao tác này đều không làm hủy bỏ những gì đã được thực hiện trước đó.

## Các tệp đính kèm, bản xem trước và các tài liệu liên quan.

Hãy sử dụng chức năng quản lý tệp tin để tải lên các tập tin hoặc hình ảnh được hỗ trợ. Việc tải lên các tệp tin có giới hạn là 32 MiB mỗi lần. Các giới hạn khác trong quá trình triển khai có thể làm giảm giới hạn này. Các tệp tin được tải lên sẽ được lưu trữ trong Controller, và có thể được truy cập thông qua các mô hình liên quan. Việc xử lý hình ảnh đòi hỏi phải có các mô hình và công cụ hỗ trợ việc nhận dữ liệu từ hình ảnh. Việc tải lên các tệp tin không có nghĩa là người dùng được phép truy cập vào các tệp tin ở nơi khác, dù đó là nội bộ hay xa xôi.

Khi yêu cầu một tệp tin được tạo ra, hãy chỉ định rõ đường dẫn, định dạng và nội dung của tệp tin đó. Hãy kiểm tra xem tệp tin đã được tạo hay chưa trước khi chia sẻ nó. Có thể tải xuống hoặc xem trước các tệp tin được hỗ trợ từ chat. Tệp tin được tạo bởi Worker có thể cần được chuyển đến Controller hoặc có thể được lưu dưới dạng liên kết tệp tin. Xem thêm [Liên kết tệp tin](../guides/file-links.md).

Trình hiển thị các tác phẩm nghệ thuật có thể hiển thị React, HTML, SVG, Markdown và Mermaid trong một cửa sổ phụ, thay vì chỉ hiển thị dưới dạng mã nguồn. Trong cài đặt các tác phẩm của Agent, mặc định sẽ sử dụng các hướng dẫn tiêu chuẩn; shadcn/ui cung cấp hướng dẫn chi tiết về cách sử dụng các thành phần và thư viện liên quan; còn tùy chọn “Tùy chỉnh” thì cho phép hiển thị nội dung một cách tự do, mà không cần sử dụng các hướng dẫn tiêu chuẩn. Hãy coi nội dung được tạo ra như là nội dung không đáng tin cậy; hãy kiểm tra nó trước khi sử dụng bên ngoài môi trường xem trước. Các tệp có chứa nội dung Office được hiển thị hoặc tải xuống khác với các tác phẩm giao diện người dùng được tạo ra.

Xin đừng tải lên các thông tin cá nhân, khóa riêng hoặc các tài liệu mà bạn không có quyền gửi cho nhà cung cấp dịch vụ được chọn. Việc xóa các văn bản và tệp tin liên quan là hai việc khác nhau; việc xóa chúng trên máy tính cũng là hai việc khác nhau nữa.

## Sở thích/Ưu tiên

Các cuộc trò chuyện và các tùy chọn của người dùng, chẳng hạn như các tùy chọn liên quan đến công cụ và các phím tắt trên bàn phím, đều được quản lý thông qua giao diện WebUI. Các tùy chọn này được lưu trữ trên máy chủ nơi mà chúng được triển khai. Bạn có thể truy cập mục Cài đặt để điều chỉnh hành vi của bàn phím; cần phân biệt rõ việc gửi tin nhắn với việc nhập dòng mới. Các tùy chọn liên quan đến công cụ cũng nên được điều chỉnh riêng biệt, không nên kết hợp chúng với quyền truy cập của người dùng. Xem thêm mục [Công cụ và quyền truy cập](permissions.md) và [Bộ nhớ và ngữ cảnh](context.md).
