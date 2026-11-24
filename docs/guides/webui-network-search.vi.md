<!-- i18n-source-sha256: 78ec7a5b5dc75473db69b12cf1626f81c3071f52661bf1023047af5d6d24e3ee -->
# Tìm kiếm web và đọc tài liệu trong WebUI

Tìm kiếm web được bật mặc định trong trò
chuyện WebUI. Bạn có thể tắt riêng cho từng
cuộc trò chuyện bằng công tắc bên dưới ô nhập
tin nhắn; lựa chọn được lưu cùng cuộc trò
chuyện. Không cần khóa API của nhà cung cấp
hay quyền shell của Worker.

Agent chỉ có hai công cụ đọc.
`web_search(query)` trả về tiêu đề, URL và
phần trích của kết quả tìm kiếm công khai.
Công cụ ưu tiên `ddgs` nếu được cài đặt, nếu
không sẽ thử Bing RSS không cần khóa. Dịch vụ
công cộng có thể giới hạn yêu cầu hoặc không
phản hồi.

`web_fetch(url, query?, offset?, limit?)` đọc
HTML, văn bản thuần, JSON, XML, Markdown và
PDF. Khi gặp trang tóm tắt arXiv, công cụ cố
mở bản toàn văn HTML trước rồi thử PDF nếu
không có. Không cần API tìm kiếm học thuật
riêng.

Ở lần đọc đầu tiên, toàn bộ văn bản được lưu
trong bộ nhớ đệm riêng của Controller nếu thư
mục có quyền ghi. Bộ nhớ đệm tách theo người
dùng, hết hạn sau 24 giờ và tối đa 80 tệp mỗi
người. Mỗi lần thường trả tối đa 8000 ký tự;
có thể đọc tiếp bằng từ khóa, vị trí hoặc
giới hạn, tối đa 12000 ký tự mỗi lần gọi.

Dung lượng tải xuống tối đa 20 MiB, văn bản
trích xuất tối đa 3 MiB. Địa chỉ mạng riêng,
thông tin đăng nhập trong URL, cổng không
chuẩn và chuyển hướng nguy hiểm bị từ chối.
Kết nối chỉ đến IP công khai đã xác minh để
ngăn DNS rebinding.

PDF được đọc bằng PyMuPDF hoặc dự phòng
`pypdf`. Bản quét không có lớp văn bản cần
OCR và sẽ báo lỗi rõ ràng. Bộ mã ký tự HTML
được nhận dạng theo khai báo; định dạng không
hỗ trợ sẽ bị từ chối.

Liên kết xuất hiện trong thẻ kết quả công cụ.
Câu trả lời nên dẫn URL gốc và số trang PDF
nếu có thể. Nội dung ngoài không đáng tin cậy
và không được phép thay đổi yêu cầu của người
dùng hoặc cấu hình Agent.
