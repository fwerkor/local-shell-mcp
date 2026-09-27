<!-- i18n-source-sha256: 696652d73445aaa9f3fc920f090fdaad3b7dd627a2bba4f5c8530f054a937506 -->
# 桌面 GUI 自動化

`local-shell-mcp` 可以觀察並控制 Linux、Windows 與 macOS 上的原生桌面應用程式。公開介面刻意保持精簡：

| 工具 | 用途 |
|---|---|
| `gui_list` | 列出可見的應用程式視窗，並回報目前原生後端及其能力。 |
| `gui_state` | 觀察一個視窗。回傳短期有效的 `state_id`、無障礙元素、視窗幾何資訊，以及可選的原生 MCP 截圖。 |
| `gui_action` | 針對這次精確觀察執行語意動作或座標動作。 |

三個工具都接受可選的 `machine` 參數，因此同一套流程也能操作已連線的桌面 worker。

## 先觀察，再操作

先呼叫 `gui_list`，選擇一個 `window_id`，再呼叫 `gui_state`。若回傳的無障礙 `element_id` 能代表目標控制項，應優先使用它：

```text
gui_list
  -> gui_state(window_id)
  -> gui_action(window_id, state_id, [{type: "click", element_id: "e17"}])
  -> gui_state(window_id)
```

只有在介面沒有可用無障礙元素（例如畫布或自繪控制項）時，才使用視窗相對的 `x`/`y` 座標。回傳的元素邊界與截圖使用相同的視窗相對邏輯像素空間，包括 HiDPI/Retina 桌面。超出所選視窗的原始座標會被拒絕。

`state_id` 會在 30 秒後過期，而且只能使用一次。座標動作也會驗證目標視窗自觀察後沒有移動或改變大小。如果任一檢查失敗，請重新呼叫 `gui_state`，不要重用過期座標。

支援的動作包括 `click`、`double_click`、`right_click`、`move`、`scroll`、`drag`、`type`、`key`、`set_value`、`focus` 與 `wait`。

## Native WebUI 中的人工控制

Native WebUI 提供 **Desktop** 頁面，可直接人工控制相同的原生 GUI 後端。選擇機器與視窗後，可以在即時視窗影像上執行單擊、雙擊、右擊、拖曳、滾輪、鍵盤快捷鍵，也可透過文字欄位進行 IME/CJK 輸入。

這條路徑與模型使用的 `state_id` 語意刻意分離。每個顯示 frame 都帶有觀察到的視窗幾何資訊；每次人工輸入請求在注入前都會驗證視窗幾何仍完全一致。若視窗已移動、縮放或消失，動作會被拒絕，WebUI 會重新整理觀察。原始座標始終限制在所選視窗內。

鍵盤與文字動作會在注入前明確聚焦所選原生視窗。WebUI 使用輕量截圖輪詢，而不是 VNC/WebRTC 視訊串流；僅供遠端使用的 `gui_human_action` RPC 是 controller 到 worker 的內部操作，並不是暴露給模型的 MCP 工具。

## 原生後端

| 平台 | 無障礙 / 語意控制 | 截圖與原始輸入 |
|---|---|---|
| Windows | Microsoft UI Automation | 視窗截圖以及 Windows 原生滑鼠與鍵盤輸入 |
| macOS | Accessibility（`AXUIElement`） | 對所選視窗使用 `screencapture`，並透過 Quartz `CGEvent` 輸入 |
| Linux | AT-SPI | X11 原生輸入/截圖；Wayland 使用原生桌面截圖，並以 XDG Desktop Portal RemoteDesktop/ScreenCast 實作原始輸入 |

在可行時會優先嘗試語意動作。因此，具有原生 invoke/press 動作的按鈕可以直接啟用，不必猜測像素座標。對於無法存取或自繪內容，視覺座標仍作為備援方案。

## 平台設定

### Windows

LSM 應執行在與目標應用程式相同的互動式桌面工作階段。基礎 `local-shell-mcp` 安裝保持 headless 安全，不強制依賴 Windows UI Automation adapter；只有需要本機 Windows GUI 控制時才安裝可選的 `local-shell-mcp[gui]` extra。

### macOS

向 LSM 主機程序授予：

- 用於語意控制和輸入的 **輔助使用** 權限。
- 用於截圖的 **螢幕錄製** 權限。

基礎套件不強制依賴 PyObjC。只有需要本機 macOS GUI 控制時才安裝可選的 `local-shell-mcp[gui]` extra；從不使用 GUI 工具的機器不需要這些 framework。

### Linux

桌面工作階段必須提供 AT-SPI。Debian/Ubuntu 系統通常可透過以下命令安裝所需的系統 binding：

```bash
sudo apt install python3-gi gir1.2-atspi-2.0
```

基礎套件不強制依賴 Python X11 或 D-Bus adapter。可選的 `local-shell-mcp[gui]` extra 會為本機 GUI 使用安裝它們。遠端 worker 在任何 GUI 依賴 bootstrap 前先偵測目前 Linux 工作階段：X11 只需要 X11 adapter，Wayland 只需要 D-Bus adapter，headless worker 兩者都不安裝。在 Wayland 上，原始指標/鍵盤備援使用 XDG Desktop Portal RemoteDesktop API，因此桌面可能首次顯示權限/工作階段選擇器。支援 KDE 與 GNOME 的 portal 實作。視窗截圖優先使用可用的原生桌面截圖路徑，必要時退回 Screenshot portal。

LSM worker 經常在圖形登入環境之外啟動。若相關變數未直接繼承，Linux backend 會從使用者 systemd 環境恢復 `DISPLAY`、`WAYLAND_DISPLAY`、`XDG_SESSION_TYPE` 等變數。

## 遠端桌面

GUI 工具實際執行在所選機器上，而不是 controller。遠端 worker 必須屬於擁有目標桌面的使用者/工作階段。GUI adapter 採惰性載入且只作用於 GUI 呼叫：一般 worker 啟動以及 shell/files/browser 使用不會安裝或匯入它們。在 Linux 上，headless worker 會在任何 GUI pip bootstrap 前回傳 GUI 不可用；圖形 worker 只檢查或安裝目前 X11/Wayland 工作階段所需的 adapter。

遠端 `gui_state` 回傳的截圖會透過 LSM 檔案傳輸路徑傳送，並以原生 MCP 影像內容提供給模型；不會嵌入 worker 的 JSON 回應。
