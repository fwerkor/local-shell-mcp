<!-- i18n-source-sha256: bb7b6aa220cafcc7318d2cc50e01ae98fb5ea2f1ff04c87d5cc7b90a7b322134 -->
# 渠道与模型

## 配置渠道

打开聊天页面的模型选择器，进入渠道管理。选择**添加渠道**，选择连接类型，填写必要信息后保存。从该渠道选择一个模型并新建会话；使用自定义智能体时，则在智能体配置中选择渠道和模型。

渠道由 Controller 管理，而非个人聊天设置。启用认证的部署中，渠道管理需要 `admin:config` Scope。管理员可以配置共享渠道，无需将 API Key 分发给聊天用户。

![实际渠道配置对话框中的添加渠道界面](../assets/chat/channel-settings.png)

普通 API 渠道包含名称、提供方协议、Base URL、凭证及模型标识。使用该端点签发的 API Key，不要填写 LSM 登录密码。模型请求由 Controller 发出，因此电脑上可访问的 URL 未必能被 Controller 访问。

| 协议 | API Base URL 示例 | 用途 |
|---|---|---|
| OpenAI Chat Completions | `https://api.openai.com/v1` | OpenAI 兼容网关与本地推理服务 |
| OpenAI Responses | `https://api.openai.com/v1` | 提供 Responses API 的网关 |
| 人为原住民 | `https://api.anthropic.com/v1` | 兼容 Anthropic Messages 的 API |
| 谷歌双子座原生 | `https://generativelanguage.googleapis.com/v1beta` | 兼容 Gemini generateContent 的 API |

按照提供方要求填写基础地址，而不是以 `/chat/completions` 等结尾的完整生成请求 URL。兼容 OpenAI 的网关不一定支持 Responses、工具调用、流式用量、多模态输入或推理参数。选择实际受支持的协议。上述地址只是协议示例，并不表示免费或保证可用。

## 本地及自定义端点

如果 OpenAI 兼容推理服务运行在 Controller 本机，Base URL 可以是 `http://127.0.0.1:8080/v1`。Docker 中的 loopback 指容器自身，而非宿主机。应使用 Controller 网络命名空间可达的地址。注册远程 Worker 并不会自动使其推理 API 可达。

模型 URL 校验要求 HTTPS，仅允许直接使用 loopback 主机（`localhost`、`127.0.0.1`、`::1`）的 HTTP 地址。局域网 IP 或 Docker 服务名上的 HTTP 端点需要通过 HTTPS 网关提供；旧版 Hosted Chat 私有端点开关已不适用。Base URL 不得包含内嵌凭证、片段或查询字符串。

远程端点使用 TLS，私有网关仅向可信环境开放，并核对推理服务的模型标识。不要将 API Key 放进提示词、截图、查询字符串或公开配置。编辑已有渠道时留空 Key 会保留现有凭证；仅在服务确实支持无 Key 请求时使用无凭证连接。

## 通过环境变量配置默认渠道

启动前可以通过 `LOCAL_SHELL_MCP_MODEL_BASE_URL`（或 `OPENAI_BASE_URL`）、`LOCAL_SHELL_MCP_MODEL` 和 `LOCAL_SHELL_MCP_MODEL_API_KEY`（或 `OPENAI_API_KEY`）配置内置 OpenAI 渠道。内置 Anthropic、Google 渠道分别读取 `ANTHROPIC_API_KEY` 和 `GOOGLE_KEY` / `GOOGLE_API_KEY`。已经保存的内置渠道优先于环境变量派生的默认值；多个独立端点应使用命名渠道。环境变量同样需要作为服务凭证保护。

## ChatGPT 账户授权

账户/Codex 渠道采用受支持的 ChatGPT 账户授权流程，不需要普通 API Key。从渠道管理发起授权，在官方授权页面登录。本地部署可以自动接收回调。如果浏览器无法访问 loopback 监听器，从地址栏复制完整回调 URL，粘贴到授权对话框。手动流程中 loopback 页面出现连接失败是正常的。

回调 URL 属于凭证，不应发送到聊天中或公开分享。Controller 在服务端保存授权并在可行时刷新凭证。账户失效或授权撤销后需要重新授权。模型可用性、套餐额度与使用规则取决于上游账户服务，LSM 不会提供额外订阅额度。

## 自动发现模型与上下文长度

开启自动发现后，Controller 向提供方获取模型信息，并定期刷新（当前每十分钟一次），也可以手动刷新。发现失败时保留已保存的模型数据。如果提供方没有兼容的模型列表接口，关闭自动发现并逐行填写模型标识。

自动发现可识别明确的上下文窗口元数据，包括 OpenCode Go/Zen 嵌套的 `limit.context`、OpenRouter 的 `context_length`、vLLM 的 `max_model_len` 和 Gemini 的 `inputTokenLimit`。如果只返回最大输入长度，则将其作为备用值；输出上限和模型名称不能确定上下文容量。如果两者均未报告，上下文窗口仍为未知。

已知模型上下文长度时，为每个模型填写实际限制。显式配置覆盖自动发现的元数据或补充未知值。编辑器接受 1 至 2,000,000 Token；这只是配置范围，不意味着提供方支持这么大的窗口。应综合模型自身限制及推理服务配置填写实际值。

对于可识别的官方供应商端点，可以通过精确匹配供应商和模型 ID，从公开 models.dev 目录补齐缺失的上下文长度。供应商元数据优先于这一备用来源，手动覆盖优先于两者。Controller 共享六小时的内存目录缓存；获取失败时保留上一次成功的缓存，并在十分钟后重试。不会向 models.dev 发送渠道凭据、URL 或模型 ID。对于未知端点及未匹配的 ID，如果供应商未报告限制，则保持未知。

## 采样、推理与用量

渠道/模型默认参数控制所选提供方支持的请求选项。聊天输入区可能提供推理强度控制。不同协议的采样和推理选项并不相同，有些模型不支持某些设置。建议从提供方默认值开始，每次调整一个参数。

LSM 可以请求精确的流式 Token 用量，并在提供方明确拒绝该选项时回退。不返回用量的端点无法提供精确的费用或缓存统计。参见[记忆与上下文](context.md)，了解累计消耗与当前窗口容量的区别。

## 修改和删除渠道

会话保留所选模型/智能体和历史。切换端点或排查提供方问题时，明确选择所需模型。正在使用的渠道受到重命名限制，以保护已有引用。删除正在使用的渠道需要额外确认：历史仍然保留，但引用该渠道的智能体和会话必须选择可用的替代渠道才能继续执行。

渠道配置保存于服务端，并非仅存在浏览器中的预设。普通渠道列表接口不会返回凭证。应将 Controller 状态目录及备份视为含有凭证的敏感数据。

## 连接检查清单

1. 确认 Controller 能访问 API 主机，TLS 验证成功。
2. 核对基础路径、协议、凭证及精确模型 ID。
3. 刷新模型发现，或手动填入一个确定可用的模型。
4. 先发送简短文本请求，再测试小型工具调用。
5. 查看上游 HTTP 状态、超时和不支持选项等详细错误，不要反复重试无效凭证。

有关限额、流式中断和授权错误的处理，参见[管理与故障排查](administration.md)。
