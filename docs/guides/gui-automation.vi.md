<!-- i18n-source-sha256: 696652d73445aaa9f3fc920f090fdaad3b7dd627a2bba4f5c8530f054a937506 -->
# Tự động hóa GUI máy tính

`local-shell-mcp` có thể quan sát và điều khiển các ứng dụng desktop gốc trên Linux, Windows và macOS. Bề mặt công khai được giữ nhỏ một cách có chủ đích:

| Công cụ | Mục đích |
|---|---|
| `gui_list` | Liệt kê các cửa sổ ứng dụng đang hiển thị và báo backend gốc cùng các khả năng đang hoạt động. |
| `gui_state` | Quan sát một cửa sổ. Trả về `state_id` ngắn hạn, các phần tử accessibility, hình học cửa sổ và tùy chọn ảnh chụp MCP gốc. |
| `gui_action` | Thực thi hành động ngữ nghĩa hoặc theo tọa độ đúng trên lần quan sát đó. |

Cả ba công cụ đều nhận `machine` tùy chọn, vì vậy cùng một quy trình có thể nhắm tới worker desktop đã kết nối.

## Quan sát trước, hành động sau

Bắt đầu bằng `gui_list`, chọn `window_id` rồi gọi `gui_state`. Nếu `element_id` accessibility được trả về đại diện cho control mục tiêu, hãy ưu tiên dùng nó:

```text
gui_list
  -> gui_state(window_id)
  -> gui_action(window_id, state_id, [{type: "click", element_id: "e17"}])
  -> gui_state(window_id)
```

Chỉ dùng tọa độ `x`/`y` tương đối với cửa sổ khi giao diện không có phần tử accessibility hữu ích, chẳng hạn canvas hoặc control tự vẽ. Biên phần tử và ảnh chụp trả về dùng cùng không gian pixel logic tương đối với cửa sổ, kể cả desktop HiDPI/Retina. Tọa độ thô nằm ngoài cửa sổ đã chọn sẽ bị từ chối.

`state_id` hết hạn sau 30 giây và chỉ dùng một lần. Hành động theo tọa độ cũng xác minh cửa sổ mục tiêu chưa bị di chuyển hoặc đổi kích thước kể từ lúc quan sát. Nếu kiểm tra thất bại, hãy gọi lại `gui_state` thay vì dùng tọa độ cũ.

Các hành động hỗ trợ gồm `click`, `double_click`, `right_click`, `move`, `scroll`, `drag`, `type`, `key`, `set_value`, `focus` và `wait`.

## Điều khiển thủ công trong Native WebUI

Native WebUI có trang **Desktop** để con người trực tiếp điều khiển cùng các backend GUI gốc. Chọn máy và cửa sổ, sau đó tương tác với hình ảnh cửa sổ bằng nhấp, nhấp đúp, nhấp phải, kéo, bánh xe, phím tắt hoặc ô văn bản cho IME/CJK.

Đường dẫn này cố ý tách khỏi ngữ nghĩa `state_id` của model. Mỗi frame hiển thị mang hình học cửa sổ đã quan sát; mọi yêu cầu nhập của người dùng đều xác minh cửa sổ vẫn có đúng hình học đó trước khi bơm input. Nếu cửa sổ đã di chuyển, đổi kích thước hoặc biến mất, hành động bị từ chối và WebUI làm mới quan sát. Tọa độ thô luôn bị giới hạn trong cửa sổ đã chọn.

Hành động bàn phím và văn bản sẽ đặt focus rõ ràng vào cửa sổ gốc đã chọn trước khi bơm input. WebUI dùng polling ảnh chụp nhẹ thay cho streaming video VNC/WebRTC; RPC chỉ dành cho remote `gui_human_action` là thao tác nội bộ controller-worker, không phải công cụ MCP công khai cho model.

## Backend gốc

| Nền tảng | Accessibility / điều khiển ngữ nghĩa | Chụp và input thô |
|---|---|---|
| Windows | Microsoft UI Automation | Chụp cửa sổ và input chuột/bàn phím Windows gốc |
| macOS | Accessibility (`AXUIElement`) | `screencapture` cho cửa sổ đã chọn và input Quartz `CGEvent` |
| Linux | AT-SPI | Input/chụp X11 gốc; Wayland dùng chụp desktop gốc và XDG Desktop Portal RemoteDesktop/ScreenCast |

Khi có thể, hành động ngữ nghĩa được thử trước. Vì vậy nút có hành động invoke/press gốc có thể được kích hoạt mà không cần đoán tọa độ pixel. Tọa độ trực quan vẫn là fallback cho nội dung không accessible hoặc tự vẽ.

## Thiết lập nền tảng

### Windows

Chạy LSM trong cùng phiên desktop tương tác với các ứng dụng cần điều khiển. Cài đặt `local-shell-mcp` cơ bản vẫn an toàn cho headless và không bắt buộc adapter Windows UI Automation; chỉ cài extra `local-shell-mcp[gui]` khi cần điều khiển GUI Windows cục bộ.

### macOS

Cấp cho tiến trình host LSM:

- quyền **Accessibility** cho điều khiển ngữ nghĩa và input;
- quyền **Screen Recording** cho ảnh chụp màn hình.

Gói cơ bản không yêu cầu PyObjC. Chỉ cài extra `local-shell-mcp[gui]` khi cần điều khiển GUI macOS cục bộ; máy không dùng công cụ GUI không cần các framework này.

### Linux

Phiên desktop phải cung cấp AT-SPI. Trên Debian/Ubuntu, các binding hệ thống cần thiết thường được cài bằng:

```bash
sudo apt install python3-gi gir1.2-atspi-2.0
```

Gói cơ bản không bắt buộc adapter Python X11 hoặc D-Bus. Extra `local-shell-mcp[gui]` tùy chọn cài chúng cho GUI cục bộ. Worker remote phát hiện phiên Linux đang hoạt động trước mọi bootstrap phụ thuộc GUI: X11 chỉ cần adapter X11, Wayland chỉ cần adapter D-Bus và worker headless không cài cả hai. Trên Wayland, fallback pointer/bàn phím thô dùng API XDG Desktop Portal RemoteDesktop, vì vậy desktop có thể hiển thị trình chọn quyền/phiên một lần. Hỗ trợ portal KDE và GNOME. Ảnh chụp cửa sổ dùng đường chụp gốc có sẵn và fallback sang Screenshot portal khi cần.

Worker LSM thường khởi động ngoài môi trường đăng nhập đồ họa. Backend Linux khôi phục `DISPLAY`, `WAYLAND_DISPLAY`, `XDG_SESSION_TYPE` và các biến liên quan từ môi trường systemd của người dùng khi chúng không được kế thừa trực tiếp.

## Desktop từ xa

Công cụ GUI chạy trên máy đã chọn, không chạy trên controller. Worker remote phải thuộc người dùng/phiên sở hữu desktop mục tiêu. Adapter GUI được tải lazy và chỉ áp dụng cho lời gọi GUI: khởi động worker thông thường và việc dùng shell/files/browser không cài hoặc import chúng. Trên Linux, worker headless trả về GUI không khả dụng trước mọi GUI pip bootstrap; worker đồ họa chỉ kiểm tra hoặc cài adapter cần cho phiên X11 hoặc Wayland đang hoạt động.

Ảnh chụp trả về từ `gui_state` remote được truyền qua đường truyền file của LSM và đưa cho model dưới dạng nội dung ảnh MCP gốc; chúng không được nhúng vào phản hồi JSON của worker.
