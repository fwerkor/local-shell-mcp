<!-- i18n-source-sha256: 6c9270cab0f3c147ed3790b5042770b1c949119bd63f60b171b4647fb16850ef -->
# WebUI Chat 快速入门

统一 LSM Web 工作区集成 AI 聊天、项目、智能体与 Controller 运维页面，由 Python Controller 提供服务，共享其认证和 SQLite 数据库，无需独立聊天服务器。仍支持 [ChatGPT](chatgpt-connector.md)、[Gemini](gemini-spark.md) 等外部 MCP 客户端。

## 1. 启动 Controller

按照[安装快速入门](quickstart.md)选择部署方式。确认 WebUI 已启用并使用持久化存储。以下为正常默认值：

```env
LOCAL_SHELL_MCP_STATE_BACKEND=sqlite
LOCAL_SHELL_MCP_UI_ENABLED=true
```

导出服务环境变量后，启动 Controller：

```sh
local-shell-mcp --mode mcp
```

单文件发行版使用下载的可执行文件。已安装的 Controller 提供编译好的前端，仅源码构建需要 JavaScript 工具链。参见[WebUI 构建说明](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md)。

## 2. 打开浏览器工作区

在 Controller 主机访问 `http://127.0.0.1:8765/ui`，远程访问时使用已配置的 HTTPS 地址及 `/ui` 路径。通过部署中配置的 LSM 认证登录。远程访问应使用经过认证的 HTTPS。聊天与控制面页面共享同一源地址。

## 3. 添加模型渠道

打开模型选择器及渠道管理。添加 API 渠道或连接受支持的账户。对于典型 OpenAI 兼容端点，填写渠道名称、选择 Chat Completions 协议、填写 API Base URL 和凭证，再自动发现模型或手动填写已知模型 ID。保存配置并选择模型。

本地推理服务的地址必须能被 Controller 访问，而非仅浏览器可访问。例如，若推理服务在 Controller 网络命名空间内监听对应地址，则可填写 `http://127.0.0.1:8080/v1`。协议、账户授权、自动发现和窗口限制详见[渠道与模型](../chat/channels.md)。

## 4. 运行第一个任务

新建会话并提出简单问题，验证模型连接。随后尝试只读工具请求：

```text
列出 Controller 工作区根目录中的文件。
告诉我检查的是哪台机器，并总结结果。
不要修改文件或执行任何写操作。
```

查看实际工具结果。如果工具缺失，检查聊天工具开关、智能体设置及机器权限。重复任务可使用已保存的智能体，并明确配置其访问权限。参见[工具与权限](../chat/permissions.md)。

## 5. 探索工作区

| 区域 | 用途 |
|---|---|
| 聊天与项目 | 新建和搜索会话、整理项目、标签和消息书签 |
| 智能体 | 复用模型、指令及工具配置 |
| 记忆与 Skill | 管理可复用知识与指令 |
| 定时会话 | 使用周期性提示词运行已保存智能体 |
| 文件与终端 | 检查或操作 Controller 和 Worker 环境 |
| 桌面 | 检查和控制支持的远程 GUI 会话 |
| Session、Job 与审计 | 查看持久任务、执行进度及工具活动 |
| 机器与外部 MCP | 管理 Worker 与嵌套 MCP 服务器 |

具体控件取决于部署、账户和启用能力。关闭浏览器不会自动取消服务端推理；需要中断时应使用停止控件。

## 后续阅读

完整工作流程参见 [WebUI Chat 指南](../chat/index.md)，生产部署、备份与错误恢复参见[管理与故障排查](../chat/administration.md)。
