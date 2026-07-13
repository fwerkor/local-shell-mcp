# REST API

主要接口是 `/mcp` 上的 MCP。同时也提供 REST 面，用于健康检查、文件链接、连接器式 search / fetch，以及部分工具调用。

## 健康检查

```http
GET /healthz
```

返回服务健康状态和基础状态信息。

## MCP

```http
POST /mcp
```

ChatGPT 和其它 MCP 客户端使用的 streamable HTTP MCP 端点。

## 连接器发现

只读连接器式操作：

```text
search
fetch
```

这些操作用于常规 ChatGPT 连接器行为，不暴露完整 coding-agent 工具面。

## 通过 REST 调用工具

REST 工具调用使用一致的成功 / 错误 envelope。校验错误会返回结构化 `ok: false` payload，而不是原始框架异常。

## Agent Skills

固定 Skill Registry 也通过 REST 提供：

```text
GET  /tools/skills_list
POST /tools/skill_load   {"name": "debugging"}
```

Skill 目录修改会在下一次调用时生效，不会改变 MCP 工具列表。

## 文件链接

带 token 的文件下载由内置 HTTP app 提供。链接是 bearer URL，支持 TTL、可选最大下载次数和撤销。

## 认证

公开部署应使用 OAuth。开发时可以启用 localhost 绕过认证，但未认证的公网访问是不安全的。
