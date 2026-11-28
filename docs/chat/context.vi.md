<!-- i18n-source-sha256: 214687d6067b7dc2dd2b6eec1a207aa50be3ab9550d081f8a60e3013684c0250 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Thông tin về bộ nhớ, bối cảnh và mức độ sử dụng token

## Ba loại trạng thái khác nhau của nhà nước

| Chính phủ/Quốc gia | Mục đích |
|---|---|
| Lịch sử cuộc trò chuyện | Các tin nhắn gốc và thông tin liên quan đến hoạt động của các công cụ được lưu trữ bởi người quản lý. |
| Cửa sổ ngữ cảnh | Đó là tập hợp các lệnh, cấu trúc công cụ, thông tin về quá khứ, bản tóm tắt và các dữ liệu khác được gửi trong một yêu cầu mô hình cụ thể. |
| Tình trạng trí nhớ kéo dài/ Bảo lưu thông tin trong trí nhớ | Những thông tin và sở thích có thể được sử dụng lại trong các cuộc trò chuyện khác nhau, trong phạm vi bộ nhớ liên quan. |

Một cuộc trò chuyện dài có thể vượt quá giới hạn về không gian lưu trữ của mô hình, mà vẫn không làm mất đi toàn bộ lịch sử cuộc trò chuyện đó. Việc lưu trữ thông tin không có nghĩa là toàn bộ lịch sử cuộc trò chuyện sẽ được gửi đến mọi yêu cầu từ mô hình.

## Quản lý bộ nhớ

![Thanh bên quản lý bộ nhớ với một mục mẫu](../assets/chat/memory-management.png)

Bộ nhớ được kích hoạt mặc định, trừ khi người dùng tắt nó theo cài đặt của mình, hoặc do các hạn chế liên quan đến tính năng giao tiếp hoặc chức năng của Agent. Bạn có thể sử dụng trang quản lý bộ nhớ để xem và chỉnh sửa các thông tin được lưu trữ trong bộ nhớ. Yêu cầu Agent ghi nhớ những thông tin hữu ích, quy tắc hoặc sở thích của người dùng, sau đó kiểm tra kết quả trên giao diện bộ nhớ.

Khi chỉnh sửa thông tin trong bảng nhớ, hãy sử dụng các ký tự có chứa chữ cái viết thường và dấu gạch dưới (ví dụ: `repository_conventions`). Giới hạn độ dài của thông tin là 10.000 ký tự; người dùng có thể tự đặt giới hạn này trong quá trình cài đặt. Nếu một thông tin bị từ chối, hãy kiểm tra lỗi liên quan, thay vì phải chia các thông tin mật thành nhiều khóa riêng biệt.

Bộ nhớ có thể sử dụng một kho lưu trữ chung cho tất cả các tác nhân, hoặc một phạm vi lưu trữ riêng cho từng tác nhân, tùy theo cấu hình của tác nhân đó. Đừng lưu trữ các khóa API, mật khẩu hoặc dữ liệu nhạy cảm khác vào bộ nhớ. Việc tắt bộ nhớ sẽ ngăn chặn việc sử dụng bộ nhớ trong phạm vi liên quan; điều này không giống như việc xóa các thông tin đã lưu trữ hoặc loại bỏ những phần liên quan đến lịch sử đối thoại.

Khi bị xử lý, mô hình sử dụng hàm `set_memory` để tạo hoặc cập nhật các cấu hình tương ứng; giá trị rỗng sẽ loại bỏ thông tin đó. Hàm `find_memory` giúp lấy ra các cấu hình tùy theo truy vấn hoặc khóa cụ thể. Truy vấn rỗng sẽ liệt kê tất cả các cấu hình đã được lưu trữ. Thẻ tùy chọn `include_conversations` cho phép tìm kiếm văn bản từ các cuộc trò chuyện khác. Hệ thống pagination sử dụng các tham số `page` (mặc định là 1) và `limit` (mặc định là 10; giới hạn tối đa là 50). Việc lấy ra thông tin về quá khứ này dựa trên văn bản trong các cuộc trò chuyện, chứ không phải các ghi chép về việc sử dụng công cụ. Việc lấy thông tin được thực hiện theo mức độ liên quan; vì vậy hãy sử dụng tên hoặc thuật ngữ chính xác để làm rõ truy vấn của bạn nếu cần thiết.

Việc đưa thông tin vào bộ nhớ tự động/kiến thức vào hệ thống được duy trì ổn định trong suốt quá trình diễn ra cuộc trò chuyện, nhằm bảo toàn các tiền tố dành cho lệnh yêu cầu từ nhà cung cấp dịch vụ. Việc chỉnh sửa thông tin đã lưu trong bộ nhớ không làm thay đổi những gì đã được đưa vào bộ nhớ trước đó. Việc truy xuất thông tin một cách trực tiếp sẽ giúp truy cập vào dữ liệu hiện tại; nếu cần, bạn có thể bắt đầu một cuộc trò chuyện mới.

## Khả năng xử lý thông tin/ dữ liệu

Hãy xác định giới hạn thực tế của từng mô hình trong kênh của nó. Controller sẽ ước tính lượng đầu vào mà mô hình có thể nhận được, và dành ra một khoảng không gian để lưu trữ kết quả đầu ra. Mức độ tối ưu hóa ngân sách hiện tại là 85%, còn tỷ lệ dự phòng là 5%. Con số này có thể không chính xác đối với các công cụ phân loại dữ liệu không quen thuộc, hoặc đối với các yêu cầu đa phương thức.

Bộ phận xử lý nội dung này có thể bao gồm các chỉ thị hệ thống, cấu hình của các công cụ, định nghĩa về các công cụ được sử dụng, các tệp đính kèm, thông điệp trước đó và kết quả từ các công cụ đó. Người cung cấp có thể sử dụng công cụ phân tích khác nhau hoặc tạo thêm các token nội bộ. Hãy coi việc hiển thị nội dung này như một hướng dẫn hoạt động, chứ không phải là sự đảm bảo từ người cung cấp.

## Hiệu năng nén tự động

Khi ngân sách trong một bối cảnh cụ thể yêu cầu phải được tối ưu hóa, người quản lý sẽ tạo hoặc cập nhật bản tóm tắt các thông tin liên quan đến các phiên bản trước đó của mô hình. Bản tóm tắt này sẽ lưu giữ những thông tin quan trọng như mục tiêu, các ràng buộc, quyết định được đưa ra, tiến độ thực hiện, các thông tin cần thiết để xác định vị trí của mô hình, kết quả từ các công cụ hỗ trợ, và các bước tiếp theo cần thực hiện. Thông tin gốc vẫn được lưu trữ để có thể kiểm tra lại sau này. Bản tóm tắt này chỉ là bản sao giả định do mô hình tạo ra, chứ không phải là bản sao chính xác của thông tin gốc.

Việc nén dữ liệu diễn ra trước khi có yêu cầu tiếp theo; do đó, cần giảm kích thước bối cảnh dữ liệu. Nếu quá trình nén thất bại, hệ thống sẽ tự động thử lại theo cách xử lý lỗi của nó. Không nên tiếp tục quá trình nén với dữ liệu đã quá lớn. Hãy kiểm tra trạng thái nén và các lỗi cụ thể nếu quá trình nén không thể tiếp tục được. Các tin nhắn gần đây và mối quan hệ giữa các công cụ cần được duy trì một cách nhất quán. Các kết quả từ các công cụ đã hoàn thành không nên được viết lại chỉ để giảm kích thước bối cảnh dữ liệu.

Một tệp đính kèm lớn hoặc kết quả từ một công cụ có thể vẫn vượt quá ngân sách quy định. Hãy yêu cầu kết quả có giới hạn, hoặc chỉ lấy những phần cần thiết của kết quả đó thay vì phải chèn lại toàn bộ dữ liệu vào bối cảnh dữ liệu.

## Mức sử dụng dữ liệu và số lần truy cập bộ nhớ

Trình bày thông tin về mức sử dụng dữ liệu trong quá trình giao tiếp giữa các yêu cầu, cũng như thông tin về bối cảnh dữ liệu. Mức sử dụng dữ liệu tích lũy qua các yêu cầu khác nhau trong quá trình giao tiếp. Các chỉ số về bộ nhớ mô tả việc lưu trữ dữ liệu từ nhà cung cấp khi có sẵn. Mức độ sử dụng bối cảnh dữ liệu đo lường mức độ hoạt động của mô hình, chứ không phải tổng số dữ liệu đã được sử dụng trong các yêu cầu trước đó.

Ví dụ, một yêu cầu chứa 20.000 token đầu vào, sau đó là một yêu cầu khác chứa 25.000 token đầu vào, sẽ tiêu tốn tổng cộng 45.000 token đầu vào. Tuy nhiên, yêu cầu thứ hai chỉ sử dụng khoảng 25.000 token trong khả năng của bối cảnh dữ liệu hiện tại. Token được lưu trữ trong bộ nhớ không phải là miễn phí, trừ khi nhà cung cấp quy định khác. Mức giới hạn bối cảnh dữ liệu lớn hơn sẽ làm thay đổi khả năng của mô hình, chứ không làm thay đổi mức sử dụng dữ liệu trước đó.

Việc nén dữ liệu có thể làm giảm mức độ sử dụng hiện tại của các tài nguyên, đồng thời cũng làm tăng lượng tiêu thụ của hệ thống. Việc chuyển đổi giữa các mô hình khác nhau sẽ làm thay đổi giới hạn liên quan đến việc sử dụng các tài nguyên đó; tuy nhiên, lượng tiêu thụ trước đây vẫn được giữ nguyên. Nếu nhà cung cấp không cung cấp thông tin về mức sử dụng chính xác hoặc thông tin về bộ nhớ đệm, thì các ước tính và chỉ số liên quan có thể không chính xác. Để thực hiện việc điều chỉnh tài chính một cách chính xác, hãy sử dụng dữ liệu thanh toán và giá cả của nhà cung cấp, chứ không chỉ dựa vào thông tin hiển thị trên LSM.

## Giảm chi phí và duy trì thông tin quan trọng.

Hãy duy trì sự ổn định trong các chỉ thị được gửi đi. Tránh việc tạo ra những kết quả quá lớn không cần thiết. Hãy sử dụng phương pháp truy xuất dữ liệu một cách hiệu quả. Khi cần chuyển công việc sang người khác, hãy lưu lại bản tóm tắt ngắn gọn với thông tin chính xác về đường dẫn, mã nhận diện, kết quả thu được và những vấn đề chưa được giải quyết. Hãy kiểm tra lại các thông tin quan trọng so với nguồn dữ liệu gốc hoặc kết quả từ công cụ, thay vì chỉ dựa vào bản tóm tắt được tạo ra.
