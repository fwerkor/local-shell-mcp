<!-- i18n-source-sha256: 01c14c19cf5addf99299993b57542259bcb40bbfb13600758b516a86c89e716b -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Các mục tiêu cần đạt được, các cuộc trò chuyện được lên lịch trước, và những công việc cần hoàn thành trong thời gian dài.

## Hãy chọn cơ chế phù hợp nhất.

| Cơ chế | Mục đích |
|---|---|
| Việc tạo ra những cuộc trò chuyện thông thường | Hãy trả lời cho câu hỏi hiện tại, bao gồm việc sử dụng các công cụ cần thiết để thực hiện nhiệm vụ đó. |
| Mục tiêu giao tiếp/Thông tin | Hãy tiếp tục thực hiện kế hoạch hoạt động logic này trong suốt toàn bộ phạm vi mô hình. |
| Chát theo lịch trình đã định | Khởi động một “Agent” với lệnh được lưu trữ, theo một nhịp lặp định kỳ. |
| Công việc lâu dài hoặc công việc cuối cùng trong cuộc đời | Chạy lệnh một cách độc lập, không phụ thuộc vào yêu cầu từ một mô hình cụ thể nào. |
| Thực thể phụ thuộc | Giao nhiệm vụ có giới hạn cho một thẻ người dùng khác. |

Cuộc trò chuyện được lên lịch không phải là một tác vụ tồn tại liên tục trong hệ thống. Một “Logical Session” cũng không phải là một cuộc trò chuyện hay một tiến trình của hệ điều hành. Việc hủy bỏ một cuộc trò chuyện không nhất thiết sẽ dẫn đến việc chấm dứt tất cả các tác vụ được thực hiện trong quá trình trò chuyện đó.

## Mục tiêu giao tiếp/Thông tin

Đối với những công việc phức tạp, hãy yêu cầu Agent xác định rõ mục tiêu cụ thể và lập kế hoạch chi tiết bằng cách sử dụng các công cụ Logic Session. Kế hoạch này ghi lại các bước cần thực hiện cùng với trạng thái của từng bước đó. Chương trình chat có thể tiếp tục thực hiện kế hoạch đang được triển khai ngay cả khi có sự thay đổi trong lịch trình hoạt động của mô hình, mà không cần chờ đợi yêu cầu từ người dùng mới hoặc thời gian chờ từ nền tảng MCP Live Workspace.

Hãy kiểm tra kế hoạch và tiến độ của nó. Nếu cần thiết, hãy tạm dừng, tiếp tục hoặc hủy bỏ kế hoạch đó bằng các công cụ tương ứng. Việc tiếp tục phải dựa trên một kế hoạch còn hoạt động và một lệnh thực hiện hợp lệ; không nên tiếp tục một kế hoạch đã hoàn thành, bị chặn hoặc bị hủy bỏ. Những phản hồi giống nhau liên tục sẽ khiến hệ thống tạm dừng, thay vì tiếp tục trong vòng lặp vô hạn (hiện tại, điều này xảy ra sau ba lần thay đổi không đáng kể). Hãy giải quyết những trở ngại thực sự trước khi tiếp tục kế hoạch.

Hãy xác định các tiêu chí để đánh giá việc hoàn thành công việc. Ví dụ: kiểm tra lại kho lưu trữ, thực hiện các thay đổi cần thiết, chạy các bài kiểm tra liên quan và báo cáo về những trường hợp không thành công. Yêu cầu Agent ghi lại chính xác các ID của các lần commit cũng như kết quả của các bài kiểm tra; đừng chỉ dựa vào kế hoạch của mình để đánh giá việc hoàn thành công việc.

Cơ chế đặt mục tiêu của khách hàng bên ngoài là một hệ thống riêng biệt. Xem thêm [Human interface](../guides/human-interface.md) để biết chi tiết về quy trình chuyển đổi giữa Logical Session và Live Workspace.

## Hãy tạo một cuộc trò chuyện có chương trình lịch trình cụ thể.

![Thanh bên trò chuyện theo lịch với lịch mẫu đã tắt](../assets/chat/scheduled-chats.png)

Mở chức năng quản lý các cuộc trò chuyện được lên lịch. Tạo một lịch trình với tên gọi rõ ràng, chọn nhân viên phụ trách việc quản lý cuộc trò chuyện này, chỉ định khu vực giờ làm việc và tần suất thực hiện các cuộc trò chuyện. Chọn đối tượng mà cuộc trò chuyện sẽ được gửi đến; nếu cần, có thể chọn một dự án cụ thể để bắt đầu cuộc trò chuyện. Sau đó, lưu lại lịch trình và kích hoạt nó. Sử dụng chức năng kiểm soát việc thực hiện các cuộc trò chuyện để kiểm tra lại cấu hình trước khi bắt đầu thực hiện chúng.

Các chế độ thực hiện được hỗ trợ bao gồm: hàng giờ, hàng ngày, trong các ngày làm việc, hàng tuần, và chế độ thực hiện liên tục. Chế độ thực hiện liên tục bắt đầu sau khoảng thời gian được thiết lập; khi không có khoảng thời gian dừng nào, hệ thống sẽ tiếp tục thực hiện công việc mà không ngừng nghỉ. Các lịch trình lặp lại thông thường yêu cầu khoảng cách ít nhất là 5 phút giữa các lần thực hiện. Hãy sử dụng khu vực múi giờ được chỉ định rõ ràng, chẳng hạn như `Asia/Shanghai` hoặc `UTC`. Hãy kiểm tra lại lịch trình tiếp theo sau khi lưu cài đặt.

Ví dụ cron chạy lúc 09:00 vào các ngày trong tuần:

```text
0 9 * * 1-5
```

Điều này sử dụng giờ múi thời gian được chọn, chứ không nhất thiết phải là giờ múi thời gian của hệ thống của người quản trị. Hãy kiểm tra xem liệu giờ múi thời gian được chọn có áp dụng chế độ “daylight saving” hay không.

## Đối tượng của cuộc trò chuyện

- **Hội thoại mới mỗi lần chạy:** Hãy bắt đầu một cuộc trò chuyện riêng biệt cho mỗi trường hợp cụ thể. Điều này rất hữu ích để có thể ghi lại các báo cáo một cách riêng biệt.
- **Dùng lại một hội thoại:** Hãy tạo một cuộc trò chuyện ở lần chạy đầu tiên, sau đó có thể tái sử dụng cuộc trò chuyện đó trong các lần chạy tiếp theo. Điều này rất hữu ích để giám sát tình hình một cách liên tục.
- **Dùng hội thoại hiện có:** Hãy chọn một cuộc trò chuyện đã tồn tại, và cuộc trò chuyện này sẽ được sắp xếp lịch trình để mỗi người có cơ hội phát biểu ý kiến của mình.

Những cuộc trò chuyện đã được tái sử dụng hoặc vẫn còn tồn tại có thể phát triển thêm, và cần được sắp xếp lại một cách hợp lý. Hãy chọn những cuộc trò chuyện riêng biệt khi không cần phải lưu lại bối cảnh lịch sử của chúng. Các lệnh thực hiện có thể được lên lịch tùy theo việc kênh liên lạc và mô hình được chọn vẫn còn hoạt động hay không.

## Quyền truy cập không được kiểm soát

Controller quản lý việc thực thi theo lịch, sử dụng tên các phạm vi đã được cấp quyền và lưu lại thay vì giữ token đăng nhập trình duyệt. Khi cần cấp quyền, hãy lưu hoặc chạy lịch theo cách thủ công. Quyền máy của Agent được chỉ định sẽ áp dụng; các thiết lập ghi đè quyền máy thông thường của dự án hoặc cuộc trò chuyện không phải chính sách máy của lịch. Các giới hạn của Controller, thông tin cấp quyền đã lưu, khả năng và phê duyệt công cụ vẫn áp dụng.

Đối với máy chủ MCP bên ngoài yêu cầu xác thực, việc đăng nhập tương tác không tự động đồng nghĩa với quyền có thể gia hạn để thực thi không có người giám sát. Nếu giao diện lịch báo cần xác thực lại hoặc quyền truy cập không giám sát, hãy xử lý thông tin xác thực riêng của máy chủ hoặc loại bỏ phụ thuộc đó trước khi bật lịch. Không dùng lại token trình duyệt để thay thế.

Sử dụng các công cụ giám sát chỉ có chức năng đọc dữ liệu thôi. Hãy mô tả rõ ràng những đối tượng được phép giám sát, kết quả mong muốn và các hành động cần thực hiện để tránh những tình huống không mong muốn. Nếu một nhiệm vụ được lên lịch cần sự can thiệp hoặc sự chấp thuận từ con người, hãy kiểm tra các hoạt động đang diễn ra; đừng cho rằng việc thực hiện nhiệm vụ mà không có sự giám sát sẽ mang lại quyền truy cập không giới hạn. Ví dụ về thông báo giám sát:

```text
Kiểm tra công việc đào tạo được chỉ định và các bản ghi nhật ký liên quan.
Báo cáo bước hiện tại, tổng số dữ liệu được xử lý, thời gian dự kiến hoàn thành, cũng như bất kỳ lỗi nào phát sinh.
Đừng thay đổi các tập tin, khởi động lại công việc hoặc thực hiện các tác vụ mới.
Nếu dữ liệu không có sẵn, hãy báo cáo lý do chính xác.
```

## Quá trình vận hành và khôi phục hệ thống

Bộ điều khiển này duy trì các lịch trình, trạng thái và các giao dịch liên quan đến việc thực hiện các tác vụ một cách có hệ thống, nhằm tránh việc xảy ra tình trạng bắt đầu quá nhiều lần cùng một lúc. Không cần thiết phải để tab trình duyệt mở liên tục. Đừng cho rằng những sự kiện đã bị bỏ lỡ sẽ được thực hiện lại, hoặc rằng tất cả các tác vụ bên ngoài vẫn tiếp tục diễn ra sau khi bộ điều khiển được khởi động lại. Hãy kiểm tra lần thực hiện gần nhất, lần thực hiện tiếp theo, cũng như các thông tin liên quan đến việc trò chuyện sau thời gian ngừng hoạt động của hệ thống.

Hãy vô hiệu hóa các lịch trình để ngăn chặn việc xảy ra các sự kiện tự động trong tương lai. Hãy kiểm tra từng sự kiện đang diễn ra một cách riêng biệt; việc dừng các lịch trình không có nghĩa là việc thực hiện các công việc đó sẽ bị hủy bỏ. Hãy loại bỏ những lịch trình không còn cần thiết nữa, và thu hồi quyền truy cập của các thành viên không còn cần thiết nữa.

Một công việc hoặc thiết bị được tạo ra bởi WebUI Agent có thể tiếp tục hoạt động sau khi quá trình xử lý dữ liệu hoàn tất. Việc khởi động lại Controller không nhất thiết sẽ dẫn đến việc hủy bỏ các công việc do Agent thực hiện. Các sự cố như mất quyền truy cập vào máy tính, hoặc thời hạn cấp quyền kết thúc, có thể khiến các công việc do Agent thực hiện bị hủy bỏ. Nếu Worker không còn hoạt động, việc hủy bỏ các công việc đó có thể sẽ chờ đến khi Worker trở lại mới được thực hiện. Hãy kiểm tra chính công việc hoặc thiết bị đó trước khi kết luận rằng quá trình xử lý đã kết thúc. Agent chỉ có thể gửi hoặc dừng các công việc do mình thực hiện thông qua công cụ WebUI. Các client MCP bên ngoài vẫn giữ nguyên chức năng của chúng như ban đầu.

Các công cụ liên quan đến quá trình hoạt động của các đại lý và các tác vụ phụ cũng có chu kỳ hoạt động riêng của chúng. Một kết quả có thể vẫn chưa được gửi đi sau khi quá trình thực hiện hoàn tất; hãy kiểm tra bảng thông tin về các tác vụ phụ để thu thập kết quả, hoặc để hệ thống tự động tiếp tục thực hiện tác vụ chính. Đừng tạo ra các tác vụ trùng lặp chỉ vì kết quả chưa được hiển thị.

Đối với các lệnh mà cần được thực hiện sau khi kết thúc việc sử dụng từng công cụ riêng lẻ, hãy sử dụng các công việc được theo dõi bởi LSM hoặc các terminal có khả năng tồn tại trong thời gian dài. Hãy lưu kết quả vào tệp nhật ký, ghi lại mã định danh của các công việc, và kiểm tra tiến độ thực hiện công việc. Xem thêm [Các mẫu sử dụng](../guides/usage-patterns.md).
