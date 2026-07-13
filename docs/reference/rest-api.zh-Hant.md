# REST API

主要接口是 `/mcp` 上的 MCP。同時也提供 REST 面，用於健康檢查、文件鏈接、連接器式 search / fetch，以及部分工具調用。

## 健康檢查

```http
GET /healthz
```

返回服務健康狀態和基礎狀態信息。

## MCP

```http
POST /mcp
```

ChatGPT 和其它 MCP 客戶端使用的 streamable HTTP MCP 端點。

## 連接器發現

只讀連接器式操作：

```text
search
fetch
```

這些操作用於常規 ChatGPT 連接器行爲，不暴露完整 coding-agent 工具面。

## 通過 REST 調用工具

REST 工具調用使用一致的成功 / 錯誤 envelope。校驗錯誤會返回結構化 `ok: false` payload，而不是原始框架異常。

## Agent Skills

固定 Skill Registry 也透過 REST 提供：

```text
GET  /tools/skills_list
POST /tools/skill_load   {"name": "debugging"}
```

Skill 目錄修改會在下一次調用時生效，不會改變 MCP 工具列表。

## 文件鏈接

帶 token 的文件下載由內置 HTTP app 提供。鏈接是 bearer URL，支持 TTL、可選最大下載次數和撤銷。

## 認證

公開部署應使用 OAuth。開發時可以啓用 localhost 繞過認證，但未認證的公網訪問是不安全的。
