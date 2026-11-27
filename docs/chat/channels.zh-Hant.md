<!-- i18n-source-sha256: 1ae8eb8721f33a8ea3b4af13daa70bdc7c4a6f751bf32d0c3e895be3c8a39323 -->
# 渠道與模型

## 配置渠道

開啟聊天頁面的模型選擇器，進入渠道管理。選擇**新增渠道**，選擇連線型別，填寫必要資訊後儲存。從該渠道選擇一個模型並新建會話；使用自定義智慧體時，則在智慧體配置中選擇渠道和模型。

渠道由 Controller 管理，而非個人聊天設定。啟用認證的部署中，渠道管理需要 `admin:config` Scope。管理員可以配置共享渠道，無需將 API Key 分發給聊天使用者。

普通 API 渠道包含名稱、提供方協議、Base URL、憑證及模型標識。使用該端點簽發的 API Key，不要填寫 LSM 登入密碼。模型請求由 Controller 發出，因此電腦上可訪問的 URL 未必能被 Controller 訪問。

| 協議 | API Base URL 示例 | 用途 |
|---|---|---|
| OpenAI Chat Completions | `https://api.openai.com/v1` | OpenAI 相容閘道器與本地推理服務 |
| OpenAI Responses | `https://api.openai.com/v1` | 提供 Responses API 的閘道器 |
| Anthropic 原生協議 | `https://api.anthropic.com/v1` | 相容 Anthropic Messages 的 API |
| Google Gemini 原生協議 | `https://generativelanguage.googleapis.com/v1beta` | 相容 Gemini generateContent 的 API |

按照提供方要求填寫基礎地址，而不是以 `/chat/completions` 等結尾的完整生成請求 URL。相容 OpenAI 的閘道器不一定支援 Responses、工具呼叫、流式用量、多模態輸入或推理引數。選擇實際受支援的協議。上述地址只是協議示例，並不表示免費或保證可用。

## 本地及自定義端點

如果 OpenAI 相容推理服務執行在 Controller 本機，Base URL 可以是 `http://127.0.0.1:8080/v1`。Docker 中的 loopback 指容器自身，而非宿主機。應使用 Controller 網路名稱空間可達的地址。註冊遠端 Worker 並不會自動使其推理 API 可達。

模型 URL 校驗要求 HTTPS，僅允許直接使用 loopback 主機（`localhost`、`127.0.0.1`、`::1`）的 HTTP 地址。區域網 IP 或 Docker 服務名上的 HTTP 端點需要透過 HTTPS 閘道器提供；舊版 Hosted Chat 私有端點開關已不適用。Base URL 不得包含內嵌憑證、片段或查詢字串。

遠端端點使用 TLS，私有閘道器僅向可信環境開放，並核對推理服務的模型標識。不要將 API Key 放進提示詞、截圖、查詢字串或公開配置。編輯已有渠道時留空 Key 會保留現有憑證；僅在服務確實支援無 Key 請求時使用無憑證連線。

## 透過環境變數配置預設渠道

啟動前可以透過 `LOCAL_SHELL_MCP_MODEL_BASE_URL`（或 `OPENAI_BASE_URL`）、`LOCAL_SHELL_MCP_MODEL` 和 `LOCAL_SHELL_MCP_MODEL_API_KEY`（或 `OPENAI_API_KEY`）配置內建 OpenAI 渠道。內建 Anthropic、Google 渠道分別讀取 `ANTHROPIC_API_KEY` 和 `GOOGLE_KEY` / `GOOGLE_API_KEY`。已經儲存的內建渠道優先於環境變數派生的預設值；多個獨立端點應使用命名渠道。環境變數同樣需要作為服務憑證保護。

## ChatGPT 賬戶授權

賬戶/Codex 渠道採用受支援的 ChatGPT 賬戶授權流程，不需要普通 API Key。從渠道管理發起授權，在官方授權頁面登入。本地部署可以自動接收回撥。如果瀏覽器無法訪問 loopback 監聽器，從位址列複製完整回撥 URL，貼上到授權對話方塊。手動流程中 loopback 頁面出現連線失敗是正常的。

回撥 URL 屬於憑證，不應傳送到聊天中或公開分享。Controller 在服務端儲存授權並在可行時重新整理憑證。賬戶失效或授權撤銷後需要重新授權。模型可用性、套餐額度與使用規則取決於上游賬戶服務，LSM 不會提供額外訂閱額度。

## 自動發現模型與上下文長度

開啟自動發現後，Controller 向提供方獲取模型資訊，並定期重新整理（當前每十分鐘一次），也可以手動重新整理。發現失敗時保留已儲存的模型資料。如果提供方沒有相容的模型列表介面，關閉自動發現並逐行填寫模型標識。

已知模型上下文長度時，為每個模型填寫實際限制。顯式配置覆蓋自動發現的後設資料或補充未知值。編輯器接受 1 至 2,000,000 Token；這只是配置範圍，不意味著提供方支援這麼大的視窗。應綜合模型自身限制及推理服務配置填寫實際值。

## 取樣、推理與用量

渠道/模型預設引數控制所選提供方支援的請求選項。聊天輸入區可能提供推理強度控制。不同協議的取樣和推理選項並不相同，有些模型不支援某些設定。建議從提供方預設值開始，每次調整一個引數。

LSM 可以請求精確的流式 Token 用量，並在提供方明確拒絕該選項時回退。不返回用量的端點無法提供精確的費用或快取統計。參見[記憶與上下文](context.md)，瞭解累計消耗與當前視窗容量的區別。

## 修改和刪除渠道

會話保留所選模型/智慧體和歷史。切換端點或排查提供方問題時，明確選擇所需模型。正在使用的渠道受到重新命名限制，以保護已有引用。刪除正在使用的渠道需要額外確認：歷史仍然保留，但引用該渠道的智慧體和會話必須選擇可用的替代渠道才能繼續執行。

渠道配置儲存於服務端，並非僅存在瀏覽器中的預設。普通渠道列表介面不會返回憑證。應將 Controller 狀態目錄及備份視為含有憑證的敏感資料。

## 連線檢查清單

1. 確認 Controller 能訪問 API 主機，TLS 驗證成功。
2. 核對基礎路徑、協議、憑證及精確模型 ID。
3. 重新整理模型發現，或手動填入一個確定可用的模型。
4. 先傳送簡短文字請求，再測試小型工具呼叫。
5. 檢視上游 HTTP 狀態、超時和不支援選項等詳細錯誤，不要反覆重試無效憑證。

有關限額、流式中斷和授權錯誤的處理，參見[管理與故障排查](administration.md)。
