<!-- i18n-source-sha256: d33afa60bf803b367c950dbadf80fa77167568a970adcac204cdea7e9e965e45 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Nhân viên và kỹ năng cần thiết

## Khi nào nên tạo ra một “Agent”?

Chát trực tiếp là công cụ hữu ích để giải quyết các vấn đề hoặc nhiệm vụ mang tính chất một lần duy nhất. “Agent” là những cấu hình được lưu trữ, có thể được sử dụng lại nhiều lần; chúng có thể được dùng trong các cuộc trò chuyện định kỳ, hoặc được giao cho các agent khác thực hiện. Các agent khác nhau có thể sử dụng các kênh truyền thông, mô hình xử lý, hướng dẫn và chính sách truy cập khác nhau. Tuy nhiên, chúng đều chia sẻ cùng một “Controller”. Không nhất thiết phải có cùng phạm vi bộ nhớ hay công cụ để thực hiện các tác vụ này.

## Thiết lập một đại diện/agent.

Quản lý các Agente từ giao diện WebUI: Hãy tạo một Agente mới, đặt cho nó một tên dễ nhận biết, và chọn mô hình phù hợp cho Agente đó. Ghi lại các hướng dẫn cần thiết để thực hiện công việc, kết quả mong muốn, các ràng buộc và yêu cầu kiểm tra. Thiết lập các chức năng cần thiết cho Agente, sau đó lưu lại và bắt đầu một cuộc trò chuyện mới với Agente đó.

![Agent Builder với hướng dẫn, công cụ, quyền hạn và thiết lập Skill](../assets/chat/agent-builder.png)

Ví dụ, một người kiểm tra tài liệu có thể có những hướng dẫn như sau:

```text
Hãy kiểm tra những thay đổi đã được thực hiện so với phiên bản chính hiện tại.
Kiểm tra lại kho lưu trữ và kết quả các bài kiểm tra trước khi đưa ra kết luận.
Đừng chỉnh sửa các tệp tin, cũng đừng gửi các bản cập nhật lên hệ thống hay triển khai bất cứ điều gì.
Báo cáo những phát hiện cụ thể, kèm theo đường dẫn và bằng chứng liên quan.
```

Các hướng dẫn là rất hữu ích để điều chỉnh hành vi của máy tính, nhưng chúng không phải là giới hạn quyền truy cập. Hãy thiết lập quyền truy cập của máy tính chỉ ở mức đọc thôi; đồng thời, nên loại bỏ những chức năng bên ngoài không cần thiết nếu người kiểm tra không muốn thay đổi bất cứ điều gì trong hệ thống. Xem thêm mục [Công cụ và quyền truy cập](permissions.md).

Tốt nhất là nên sử dụng các nhân viên riêng để đảm nhận các nhiệm vụ khác nhau, chẳng hạn như kiểm tra mã nguồn, triển khai và vận hành hệ thống. Hãy cấp cho từng nhân viên quyền truy cập tối thiểu cần thiết, đồng thời cung cấp cho họ những công cụ phù hợp với vai trò của họ. Nếu một nhân viên không thể bắt đầu công việc của mình, hãy kiểm tra lại kênh liên lạc và các công cụ mà nhân viên đó sử dụng trước khi thay đổi các thiết lập không liên quan đến nhiệm vụ của họ.

## Skills

Các gói kỹ năng này chứa các hướng dẫn sử dụng và các tệp liên quan đến kỹ năng đó. Thông thường, các gói kỹ năng này được lưu dưới dạng tệp có tên là `SKILL.md`. Các gói kỹ năng này có thể được quản lý thông qua giao diện WebUI; bạn có thể kích hoạt các kỹ năng cần thiết và đưa chúng vào khả năng sử dụng của các tác nhân hoặc người dùng. Mô hình có thể phát hiện và tải nội dung liên quan đến các kỹ năng này khi cần thiết. Một kỹ năng có thể mô tả quy trình công việc, cung cấp các ví dụ hoặc chứa các script. Tuy nhiên, kỹ năng này không tự động thực thi các script hay cấp thêm quyền hạn cho máy tính.

Hãy kiểm tra các kỹ năng được nhập từ bên ngoài trước khi kích hoạt chúng. Xử lý các hướng dẫn và tệp tin liên quan đến các kỹ năng này như bất kỳ mã hoặc lệnh nào do bên thứ ba cung cấp. Hãy đặt tên và mô tả cho các kỹ năng một cách rõ ràng, để mô hình có thể nhận diện chúng dễ dàng. Hãy phân biệt rõ các tham chiếu lớn với các công việc nhỏ, có thể được sử dụng độc lập. Các thông tin về cơ sở dữ liệu và các lệnh được sử dụng trong Controller sẽ được giải thích trong [Skills](../guides/skills.md).

Trình tự hành động tự động và các thông tin liên quan đến bộ nhớ được ghi lại một cách tự động, nhằm tránh việc phải viết lại lệnh hệ thống trong mỗi lần giao tiếp. Các thay đổi trong phạm vi chức năng của các kỹ năng có thể được áp dụng ngay lập tức; hãy sử dụng một cuộc trò chuyện mới khi kiểm tra các thông tin tự động đã được chỉnh sửa. Kỹ năng được kích hoạt một cách cố ý sẽ khác với hình ảnh tự động được tạo ra ban đầu.

## Việc phân công công việc và giao nhiệm vụ cho các thành viên phụ

Các đại lý có thể giao nhiệm vụ có giới hạn cho các đại lý con, khi điều đó là khả thi. Một đại lý con có thể sử dụng đại lý chính để thực hiện công việc của mình. Đại lý chính sẽ phối hợp việc thực hiện nhiệm vụ, đọc kết quả mà đại lý con đưa ra, và có thể tiếp tục quá trình thực hiện nhiệm vụ đó từ điểm đã lưu trước đó. Các hoạt động của đại lý con có thể được theo dõi từ giao diện trò chuyện của đại lý chính; tuy nhiên, giao diện này không phải là nơi để người dùng có thể tự điều chỉnh hoặc chỉnh sửa các thông tin liên quan đến cuộc trò chuyện.

Hãy sử dụng phương thức phân công công việc cho những nhiệm vụ có thể tách rời nhau, như việc đánh giá các tài liệu riêng biệt, hoặc điều tra các giả thuyết khác nhau. Hãy cung cấp cho thành viên con một mục tiêu cụ thể, phạm vi nhiệm vụ và kết quả mong muốn. Tránh việc ghi dữ liệu vào cùng một tập tin trong nhiều lúc cùng một lúc, trừ khi công việc đó được phân công rõ ràng.

Lập trình viên phải tuân thủ các giới hạn được quy định bởi người quản lý cấp cao. Lập trình viên không được phép truy cập vào bất kỳ máy tính hay dịch vụ nào mà người quản lý cấp cao không thể sử dụng được. Chính sách xác nhận của lập trình viên con không được làm suy yếu chính sách của người quản lý cấp cao. Các tác vụ do lập trình viên con thực hiện có thể tiêu thụ các token và thời gian một cách độc lập; vì vậy cần kiểm tra hoạt động và kết quả của chúng khi đánh giá chi phí và tiến độ công việc.

## Các công cụ, hành động và tài liệu liên quan đến việc phân công công việc

Agent Builder cung cấp danh sách các công cụ có sẵn cùng với các tùy chọn cấu hình nâng cao. Hãy chỉ chọn những tính năng mà bạn thực sự cần sử dụng. Đối với các hành động HTTP được mô tả bằng OpenAPI, hãy kiểm tra kỹ thông tin về điểm cuối, yêu cầu xác thực và các thao tác được phép trước khi kết nối với hành động đó. Các hành động này có thể có chính sách xác thực riêng; việc cấp quyền cho một máy tính không có nghĩa là nó sẽ đồng ý hoặc từ chối các yêu cầu xác thực từ bên thứ ba. Hãy kiểm tra phản hồi của hành động trước khi coi rằng việc thay đổi từ xa đã hoàn tất.

Đối với nội dung giao diện người dùng được tạo ra, hãy thiết lập việc hiển thị các thành phần liên quan theo cách được mô tả trong [Conversations and projects](conversations.md). Đoạn mã được tạo ra không phải là phần mở rộng đáng tin cậy của Controller.

## Mẫu thông tin đại lý thực tế

- **Nhà điều tra chỉ có quyền đọc thông tin mà thôi; không được phép ghi chép hay sửa đổi thông tin đó.** Kiểm tra các bản ghi nhật ký và nguồn dữ liệu liên quan; so sánh các bằng chứng có sẵn; báo cáo về nguyên nhân xảy ra sự việc đó. Không được thực hiện bất kỳ thay đổi nào đối với các bản ghi nhật ký hoặc nguồn dữ liệu đó.
- **Người thực hiện công việc:** Chỉnh sửa cơ sở dữ liệu, thực hiện các bài kiểm tra cần thiết, báo cáo về những sự khác biệt và các lỗi chưa được giải quyết. Nếu cần thiết, yêu cầu phải có sự phê duyệt trước khi thực hiện các thao tác nhạy cảm.
- **Agent giám sát:** Kiểm tra các máy tính được chỉ định, báo cáo về trạng thái của chúng, các lỗi phát sinh và tiến độ thực hiện công việc. Không nên khởi động lại các tác vụ trừ khi có sự cho phép rõ ràng từ người quản lý.
- **Nhân viên nghiên cứu:** Cho phép việc tìm kiếm thông tin trên mạng, trích dẫn các tài liệu gốc, phân biệt được những bằng chứng thực tế với những giả thuyết mang tính suy đoán. Ngoài ra, chỉ sử dụng các công cụ máy móc khi thực sự cần thiết.

Các mẫu này chỉ là hướng dẫn mà thôi; chúng không phải là các thiết lập sẵn được tích hợp trong hệ thống. Bạn cần tự cấu hình quyền truy cập và khả năng của từng nhân viên, sao cho chúng phù hợp với nhiệm vụ mà họ được giao.
