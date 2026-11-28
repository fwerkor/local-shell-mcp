<!-- i18n-source-sha256: a40a962d4db93cc0aac03601ffd13b21ab3a504c9bff930ab4b8173c4cfa4537 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Kênh truyền và các mô hình

## Hãy tạo một kênh truyền thông.

Hãy mở công cụ chọn mô hình trong Chat, sau đó nhập thông tin liên quan đến việc quản lý kênh chat. Chọn tùy chọn **Thêm kênh**, chọn loại kết nối phù hợp, nhập các thông tin cần thiết, rồi lưu lại. Sau đó, hãy chọn một mô hình từ kênh chat đó để tạo một cuộc trò chuyện mới. Nếu muốn sử dụng nhân viên cá nhân, hãy chọn kênh và mô hình tương ứng trong cài đặt nhân viên.

Các kênh chat này thuộc sở hữu của người quản trị, chứ không phải là thiết lập cá nhân của từng người dùng. Trong các môi trường có xác thực, việc quản lý các kênh chat cần sử dụng quyền truy cập `admin:config`. Người quản trị có thể thiết lập các kênh chat chung mà không cần phân phát chìa khóa API cho các người dùng.

![Hãy thêm một kênh mẫu vào trong hộp thoại thiết lập kênh thực tế.](../assets/chat/channel-settings.png)

Một kênh API bình thường sẽ có tên gọi, giao thức truyền dữ liệu, địa chỉ URL cơ sở, thông tin xác thực và các mã định danh của mô hình dữ liệu. Hãy sử dụng chìa khóa API được cấp cho điểm cuối cụ thể đó, chứ không phải mật khẩu của tài khoản LSM. LSM sẽ gửi yêu cầu từ phía Controller; địa chỉ URL hoạt động trên máy tính cá nhân có thể không hoạt động khi được gửi từ phía Controller.

| Giao thức/Quy trình | URL cơ sở của API ví dụ: | Sử dụng |
|---|---|---|
| OpenAI Chat Completions | `https://api.openai.com/v1` | Các cổng kết nối chat tương thích với OpenAI, cùng với các máy chủ suy luận cục bộ. |
| OpenAI Responses | `https://api.openai.com/v1` | Một công cụ giúp truy cập vào API “Responses”. |
| người bản địa nhân loại | `https://api.anthropic.com/v1` | Các API tương thích với các thông điệp do OpenAI tạo ra. |
| Google Gemini bản địa | `https://generativelanguage.googleapis.com/v1beta` | Các API tương thích với chức năng tạo nội dung của Gemini. |

Hãy sử dụng URL cơ sở mà nhà cung cấp yêu cầu, thay vì sử dụng URL đầy đủ như `/chat/completions`. Những công cụ tự nhận mình tương thích với OpenAI có thể hỗ trợ chức năng tạo nội dung, nhưng không hỗ trợ chức năng trả lời, gọi công cụ, truyền dữ liệu qua nhiều kênh, hoặc chức năng suy luận. Hãy chọn công cụ mà nó thực sự hỗ trợ. Ví dụ về URL chỉ là ví dụ minh họa, không phải là cam kết về khả năng truy cập miễn phí hay tính sẵn có của dịch vụ.

## Các điểm cuối cục bộ và tùy chỉnh.

Đối với máy chủ tương thích với OpenAI, vốn hoạt động trên chính Controller, địa chỉ URL cơ bản có thể là `http://127.0.0.1:8080/v1`. Khi chạy trong Docker, “loopback” đề cập đến container đó, chứ không phải máy chủ vật lý. Hãy sử dụng địa chỉ mà có thể truy cập được từ mạng của Controller. Việc đăng ký một Worker từ xa thì chưa đủ để khiến API suy luận của Worker có thể được sử dụng.

Đối với URL của mô hình, cần sử dụng HTTPS, trừ trường hợp sử dụng HTTP trên các địa chỉ loopback (`localhost`, `127.0.0.1`, `::1`). Điểm cuối HTTP trên địa chỉ LAN hoặc tên dịch vụ Docker phải được kết nối thông qua gateway HTTPS. Tùy chọn “Hosted Chat private-endpoint” không còn phù hợp nữa. URL cơ sở không được chứa các thông tin xác thực, các phần tử hoặc chuỗi truy vấn.

Hãy sử dụng TLS cho các điểm cuối xa, hạn chế truy cập vào các cổng riêng tư đáng tin cậy. Đồng thời, cần kiểm tra mã định danh của các mô hình trước khi gửi dữ liệu đến máy chủ suy luận. Đừng bao giờ để lại chìa khóa API trong các thông báo, hình ảnh màn hình, chuỗi truy vấn hoặc cấu hình được công bố. Hãy để chìa khóa API trống khi chỉnh sửa kênh hiện có, để bảo toàn chìa khóa đã lưu lại. Chỉ nên sử dụng kết nối không cần chìa khóa khi dịch vụ hỗ trợ điều này.

## Các mặc định được cấu hình trong môi trường

Các thông tin về OpenAI có thể được cấu hình trước khi bắt đầu sử dụng, bằng cách sử dụng các giá trị như `LOCAL_SHELL_MCP_MODEL_BASE_URL` (hoặc `OPENAI_BASE_URL`), `LOCAL_SHELL_MCP_MODEL`, và `LOCAL_SHELL_MCP_MODEL_API_KEY` (hoặc `OPENAI_API_KEY`). Các thông tin về Anthropic và Google cũng có thể được truy cập thông qua các giá trị như `ANTHROPIC_API_KEY` và `GOOGLE_KEY` / `GOOGLE_API_KEY`. Các thông tin được lưu trữ sẽ có hiệu lực hơn so với các mặc định do môi trường cung cấp. Hãy sử dụng các kênh có tên để kết nối nhiều điểm cuối khác nhau. Các mặc định được cấu hình trong môi trường không phải là cách để bảo vệ bí mật của dịch vụ.

## Xác thực tài khoản ChatGPT

Kênh account/Codex sử dụng quy trình xác thực dựa trên tài khoản ChatGPT, thay vì sử dụng chìa khóa API thông thường. Hãy bắt đầu quá trình xác thực từ bảng quản lý kênh, sau đó đăng nhập vào trang xác thực chính thức. Trong trường hợp triển khai trên máy tính cục bộ, quá trình xác thực có thể diễn ra tự động. Nếu trình duyệt không thể truy cập được địa chỉ URL liên quan đến quá trình xác thực, hãy sao chép toàn bộ địa chỉ URL đó vào ô địa chỉ của trình duyệt và nhập vào hộp thoại xác thực. Không mong đợi sự thành công trong quá trình kết nối tại địa chỉ này.

Coi URL callback là thông tin xác thực: không bao giờ gửi nó trong cuộc trò chuyện hoặc công khai. Controller lưu thông tin cấp quyền trên máy chủ và làm mới thông tin xác thực khi có thể. Cấp quyền lại nếu tài khoản hết hạn hoặc quyền truy cập bị thu hồi. Các mô hình khả dụng, giới hạn gói và cách sử dụng được phép do dịch vụ tài khoản thượng nguồn quyết định; LSM không cung cấp thêm hạn mức đăng ký.

## Mô hình khám phá và các giới hạn liên quan đến bối cảnh

Hãy bật tính năng tự động tìm kiếm để yêu cầu thông tin về mô hình từ nhà cung cấp dịch vụ. Thực thể Controller sẽ tự động cập nhật thông tin này định kỳ (hiện tại là mỗi mười phút). Người dùng cũng có thể tự động cập nhật thông tin đó. Nếu việc tìm kiếm không thành công, dữ liệu về mô hình vẫn được lưu giữ như trước. Nếu nhà cung cấp dịch vụ không có endpoint để truy xuất danh sách các mô hình phù hợp, hãy tắt tính năng tự động tìm kiếm và nhập các mã định danh của mô hình một lần cho mỗi dòng.

Tính năng khám phá nhận diện siêu dữ liệu cửa sổ ngữ cảnh rõ ràng, gồm `limit.context` lồng nhau của OpenCode Go/Zen, `context_length` của OpenRouter, `max_model_len` của vLLM và `inputTokenLimit` của Gemini. Nếu chỉ có độ dài đầu vào tối đa thì dùng làm giá trị dự phòng; giới hạn đầu ra và tên mô hình không xác định dung lượng ngữ cảnh. Nếu thiếu cả hai thông tin thì cửa sổ ngữ cảnh vẫn chưa xác định.

Hãy xác định rõ cửa sổ con của từng mô hình khi chúng được biết đến. Giá trị cụ thể cho từng mô hình sẽ thay thế các thông tin meta trong cơ sở dữ liệu, hoặc bù đắp cho những giá trị còn thiếu. Trình soạn thảo chấp nhận việc sử dụng từ 1 đến 2.000.000 ký tự; đây chỉ là phạm vi cấu hình, chứ không phải là đảm bảo rằng nhà cung cấp hỗ trợ khả năng xử lý như vậy. Hãy sử dụng giới hạn thực tế cho việc triển khai của bạn, đồng thời xem xét đến các thiết lập trên phía máy chủ và những giới hạn của chính mô hình đó.

## Phép lấy mẫu dữ liệu, quá trình suy luận và cách sử dụng dữ liệu thu được

Các thiết lập mặc định liên quan đến kênh và mô hình sẽ quyết định các thông số yêu cầu được hỗ trợ bởi nhà cung cấp được chọn. Trình tạo chat có thể hiển thị thông tin về quy trình xử lý dữ liệu khi có sẵn. Các giao thức khác nhau có cách xử lý dữ liệu khác nhau; một tùy chọn có thể không được hỗ trợ bởi một mô hình cụ thể nào đó. Hãy bắt đầu từ các thiết lập mặc định của nhà cung cấp, sau đó chỉ thay đổi một thiết lập tại một thời điểm.

Các tổ chức phi chính phủ có thể yêu cầu thông tin về mức sử dụng token trong quá trình truyền dữ liệu. Nếu nhà cung cấp từ chối việc cung cấp thông tin này, thì các tổ chức phi chính phủ có thể chuyển sang phương pháp khác để truyền dữ liệu. Một điểm cuối không trả lại thông tin về mức sử dụng dữ liệu thì sẽ không thể cung cấp thông tin về chi phí hoặc thống kê về việc lưu trữ dữ liệu được. Xem [Memory and context](context.md) để biết cách phân biệt giữa tổng lượng dữ liệu được sử dụng và khả năng lưu trữ hiện tại của hệ thống.

## Thay đổi và xóa kênh truyền dữ liệu

Một cuộc trò chuyện vẫn giữ nguyên mô hình/Người đại diện và lịch sử giao dịch của nó. Cần phải thay đổi mô hình này một cách cẩn thận khi chuyển đổi điểm cuối hoặc khắc phục các vấn đề liên quan đến nhà cung cấp dịch vụ. Việc đặt tên lại một kênh đang được sử dụng bị hạn chế để bảo vệ các tham chiếu đến kênh đó. Việc xóa một kênh đang được sử dụng đòi hỏi sự xác nhận thêm: lịch sử giao dịch vẫn được giữ lại, nhưng các Người đại diện và cuộc trò chuyện liên quan đến kênh đã bị xóa cần phải chọn một kênh thay thế phù hợp trước khi tiếp tục quá trình giao dịch.

Các thiết lập kênh được thực hiện trên phía máy chủ, chứ không phải chỉ có sẵn trong trình duyệt. Các thông tin xác thực không được truyền về thông qua các phản hồi thông thường từ kênh truyền thông. Hãy bảo vệ thư mục state của Controller và các bản sao lưu của nó như những dữ liệu chứa thông tin xác thực.

## Danh sách các bước cần thực hiện để kết nối

1. Hãy xác nhận rằng Controller có thể truy cập được đến địa chỉ IP của máy chủ API, và rằng giao thức TLS được áp dụng một cách chính xác.
2. Xác nhận đường dẫn cơ bản, giao thức, thông tin đăng nhập và ID mô hình chính xác.
3. Khởi động lại quá trình khám phá hoặc nhập vào một mô hình đã biết.
4. Gửi một yêu cầu ngắn gọn bằng văn bản đơn giản, sau đó kiểm tra việc gọi công cụ một cách đơn giản.
5. Kiểm tra chi tiết các lỗi liên quan đến trạng thái HTTP, thời gian chờ hoặc các tùy chọn không được hỗ trợ. Đừng lặp đi lặp lại việc gửi yêu cầu với thông tin đăng nhập không hợp lệ.

Xem [Administration and troubleshooting](administration.md) để biết cách xử lý các vấn đề liên quan đến giới hạn tốc độ, sự gián đoạn trong quá trình truyền dữ liệu và các lỗi liên quan đến quyền truy cập.
