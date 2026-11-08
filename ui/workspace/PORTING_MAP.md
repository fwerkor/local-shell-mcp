# LibreChat 源码级移植映射

本清单替代“同名功能即可算完成”的旧判断。PR #343 保持 Draft。

## 固定源码基线

- LibreChat `v0.8.8`: `e8f3be08623663d4ad7f7241e693c94469b63bb0`。
- 原集成 lockfile 的 `@librechat/agents 4.0.1`: tag commit `c4ffb9b1b78421bf63eba3e56993017f922387f3`。
- 原集成 lockfile 的 LangGraph `1.4.8`、checkpoint `1.1.3`。
- 逐文件 SHA-256 与差异记录见 `UPSTREAM_LOCK.json`。参考目录独立于有本地修改的旧clone。
- Node/TypeScript 仅作为开发时的源码与行为对照，不成为Controller运行依赖。

## 已核对的关键调用链

`buildOptions → loadAgent/loadEphemeralAgent → initializeAgent → createRun/buildAgentInput
→ @librechat/agents Graph/MultiAgentGraph → ToolNode/interrupt/checkpointer → callbacks
→ SSE → React runSteps/问答与审批组件`。

Ask User 的工具名和interrupt判别均为 `ask_user_question`；当前原版向模型暴露
`{questions:[{id,header?,question,description?,options?,multiSelect?}]}`（1–4题）。
单问题旧参数只用于checkpoint兼容。回答保持 `{answers:{id:string}}`；工具是否启用、
HITL能力、admin过滤以及子图禁止暂停均在run构造时处理，与机器授权独立。

Subagents 使用 `agent.subagents.enabled/allowSelf/agent_ids` 配置和动态子类型，
隔离子图可带自己的工具。Handoff 使用 `Command.PARENT/Send`、带作用域和预算的
路由transition，并通过checkpoint保证回放幂等。当前 `delegate_agent`、`handoff_agent`
不能作为原版等价实现证据，必须被原版机制替代后删除。

## 文件与函数映射

“部分”表示已有可用代码，但未经完整行为对照或已发现差异；不表示该模块验收完成。
“未实现”也包括已有同名或近似自研功能但尚未按原版实现的情况。

| LibreChat/agents 原实现 | Python/LSM 对应 | 状态 | 具体差异 |
| --- | --- | --- | --- |
| `LibreChat:api/server/controllers/agents/protocol.js` — `getRequestedGenerationProtocol / negotiate*` | `webui/generation_protocol.py; generations.py; generation_routes.py` | 完成（协议协商函数） | 2197组原Node差分与SQLite/HTTP不可升级测试；完整controller恢复仍缺失 |
| `LibreChat:api/server/controllers/agents/request.js` — `generation ingress / disconnect` | `webui/generation_routes.py:start_generation` | 部分 | 缺失完整入口预检及断线处置语义 |
| `LibreChat:api/server/controllers/agents/resume.js` — `resume / checkpoint ownership CAS` | `webui/generation_routes.py:resume_generation` | 部分 | 当前仅单action及自研resumeHistory；无原版checkpoint/actor恢复链 |
| `LibreChat:api/server/controllers/agents/callbacks.js` — `Agent execution events` | `webui/generation_routes.py:_run_model` | 部分 | 手工生成部分事件，非原版callbacks完整移植 |
| `LibreChat:api/server/controllers/agents/client.js` — `AgentClient / history / run lifecycle` | `webui/generations.py; generation_routes.py` | 部分 | 未移植完整AgentClient和事件actor生命周期 |
| `LibreChat:api/server/services/Endpoints/agents/build.js` — `buildOptions` | `webui/generation_routes.py:start_generation` | 部分 | project字段修复；spec、ephemeralAgent、完整模型参数未对齐 |
| `LibreChat:api/server/services/Endpoints/agents/initialize.js` — `agent graph loading` | `webui/delegation.py` | 未实现 | 现有简单子任务调用不等价，禁止标记完成 |
| `LibreChat:packages/api/src/agents/runtime.ts` — `AgentExecutionContext` | `webui/generation_routes.py` | 未实现 | 缺少原版transport-free执行上下文 |
| `LibreChat:packages/api/src/agents/load.ts` — `loadAgent / loadEphemeralAgent` | `webui/agents.py; generation_routes.py` | 部分 | 可选工具、spec、ephemeral选择未完成等价移植 |
| `LibreChat:packages/api/src/agents/initialize.ts` — `initializeAgent` | `webui/lsm_tool_registry.py; generation_routes.py` | 部分 | 原生LSM复用有效；LibreChat工具选择/资源/上下文未完整移植 |
| `LibreChat:packages/api/src/agents/run.ts` — `createRun / buildSubagentConfigs / buildAgentInput` | `webui/delegation.py; generation_routes.py` | 未实现 | delegate_agent/handoff_agent与原版graph/Command/子图不等价 |
| `LibreChat:packages/api/src/agents/hitl/askUserQuestionTool.ts` — `AskUserQuestionToolDefinition / createAskUserQuestionTool` | `webui/ask_user_tools.py` | 未实现 | 当前ask_user单问题工具名/schema/上限/返回值均与原版不同 |
| `LibreChat:packages/api/src/agents/hitl/resume.ts` — `resolveAskUserQuestionResume / mapToolApprovalResolutions` | `webui/generations.py:answer_question / claim_approval` | 部分 | answers被拼接为字符串；approval只approve/reject单个，缺edit/respond和批次 |
| `LibreChat:packages/api/src/agents/hitl/answers.ts` — `retained answers / branch ordering` | `webui/generations.py:history` | 部分 | 已改活动分支；尚无跨compact保留用户回答/来源信任标记 |
| `LibreChat:packages/api/src/agents/hitl/policy.ts` — `approval rules / deny-ask-allow / policy hashing` | `webui/nested_mcp.py` | 未实现 | 当前对所有nested MCP强制approval，不是原版policy机制 |
| `LibreChat:packages/api/src/agents/checkpointer.ts` — `durable checkpointer` | `sqlite_store.py; webui/generations.py` | 部分 | SQLite保存事件与history不等于LangGraph checkpoint/channel/task语义 |
| `LibreChat:packages/api/src/agents/compaction.ts` — `summary checkpoint / manual outcome` | `webui/generations.py:history` | 未实现 | 50消息截断无summary，不能标记compact完成 |
| `LibreChat:packages/api/src/agents/memory.ts` — `registerMemoryTools / tool usage guard` | `webui/misc_routes.py` | 未实现 | memory权限返回关闭；无对应持久化与工具执行 |
| `LibreChat:packages/api/src/agents/attachments.ts` — `attachment limits / model-bound files` | `webui/attachments.py` | 部分 | LSM真实路径上传已实现；原版资源分类和模型输入链未完成 |
| `LibreChat:packages/api/src/agents/tools.ts` — `runtime tools / registry adaptation` | `webui/lsm_tool_registry.py` | 部分 | 复用LSM注册表；尚未按原版Agent选择与系统注入拆开 |
| `LibreChat:packages/data-schemas/src/schema/agent.ts` — `Agent schema / settings / graph / subagents` | `webui/agents.py` | 部分 | 保存部分JSON字段；原版验证/继承/version/图配置未完整移植 |
| `LibreChat:packages/data-schemas/src/schema/message.ts` — `message content persistence` | `webui/storage.py` | 部分 | messages关系表；高级content与run状态恢复未完整 |
| `LibreChat:packages/data-schemas/src/schema/convo.ts` — `conversation / branch / archive` | `webui/storage.py; conversation_routes.py` | 部分 | 基础CRUD/分支/归档；其余模型字段和hooks未全面对照 |
| `LibreChat:packages/data-schemas/src/schema/chatProject.ts` — `project membership and resources` | `webui/storage.py` | 部分 | 项目关联/默认权限；完整资源与消息语义待移植 |
| `LibreChat:packages/data-provider/src/createPayload.ts` — `React request payload` | `ui/workspace/packages/data-provider/src/createPayload.ts` | 部分 | 前端复用；后端尚未消费所有原版字段 |
| `LibreChat:packages/data-provider/src/runSteps.ts` — `execution event types` | `ui/workspace/packages/data-provider/src/runSteps.ts; generation_routes.py` | 部分 | 共享前端类型复用；后端事件仅子集 |
| `LibreChat:client/src/components/Chat/Messages/Content/AskUserQuestions.tsx` — `batched questions UI` | `ui/workspace/client/src/components/Chat/Messages/Content/AskUserQuestions.tsx` | 部分 | React原组件保留；批问题/回答协议和真实React E2E已验证，图级恢复仍缺失 |
| `LibreChat:client/src/components/SidePanel/Agents/Advanced/AgentSubagents.tsx` — `optional subagent configuration` | `ui/workspace/client/src/components/SidePanel/Agents/Advanced/AgentSubagents.tsx` | 部分 | 原React配置保留；Python目前误读为id数组 |
| `agents:src/graphs/Graph.ts` — `agent graph / tools / checkpoint` | `webui/generation_routes.py` | 未实现 | 当前手写循环不是源码级图执行移植 |
| `agents:src/graphs/MultiAgentGraph.ts` — `multi-agent routing / commands` | `webui/delegation.py` | 未实现 | handoff机制未等价 |
| `agents:src/graphs/handoff.ts` — `HandoffRouting / mergeHandoffState` | `webui/delegation.py` | 未实现 | 缺预算、作用域、幂等transition、持久handoff结果 |
| `agents:src/tools/SubagentTool.ts` — `buildSubagentToolParams / createSubagentToolDefinition` | `webui/delegation.py` | 未实现 | 原版subagent_type/description/config动态枚举，当前自研工具不等价 |
| `agents:src/hitl/askUserQuestions.ts` — `askUserQuestions / interrupt / resolution` | `webui/ask_user_tools.py; generations.py` | 部分 | 已移植1–4问题及按id回答；SDK图级interrupt/checkpoint尚未等价 |
| `agents:src/hitl/askUserQuestionsInterrupt.ts` — `request/interrupt guards` | `webui/ask_user_tools.py` | 部分 | 已移植请求校验与批次payload，完整SDK中断状态机仍待移植 |
| `agents:src/tools/ToolNode.ts` — `parallel tool execution / interruption` | `webui/generation_routes.py` | 未实现 | 当前串行循环，未移植原版并发/中断/回放行为 |

## 后续审计范围

本表是第一轮源码级清单，不是限定范围。还须把 Actions、Artifacts、各provider adapter、
Memory、Context、资源生命周期、Agent Builder全部设置、完整conversation API、
事件actor与checkpoint存储、并发和取消恢复细分到函数与行为测试。

完整功能覆盖率尚无法给出可信百分比；当前没有任何高级Agent模块被宣称完整等价。
每个模块仅在原版测试/实际接口与Python差分验证通过后才能改为“完成”。

## 首批源码移植验证（Ask User）

- 工具定义/schema与从固定源码AST提取的原定义完全相等，移除自研`ask_user`名称。
- 91组batch/legacy恢复输入与原版Node函数逐例差分一致，包括UTF-16边界与错误优先级。
- 批次payload、按问题ID保存与回答、无效回答不消耗action、SQLite重开后恢复均已测试。
- 原版React双问题stepper选择、提交并恢复同一generation的Chromium E2E通过，未修改问答组件。
- 以上仅完成schema/回答验证和现有持久化接入；LangGraph图级interrupt、完整checkpoint、
  retained answers、admin gating与其他Agent机制仍未全部移植，故该模块继续标记“部分”。

## 审批恢复校验源码移植

`tool_approval.py`移植原版`isToolApprovalPayloadValid`、
`mapToolApprovalResolutions`和`resolveToolApprovalResume`，包括ID覆盖、
拒绝重复/外来决策、逐工具allowed_decisions、edit/respond必需字段以及错误优先级。
60组输入与原Node函数差分一致，现已用于SQLite原子claim前的权限校验。

本次没有把这些纯函数测试冒充完整审批运行时：现有执行层仍只支持单个nested MCP
暂停和approve/reject；批次执行、edit/respond实际执行与graph checkpoint仍待按原版移植。

## 必要的前端依赖适配

原版`client/package.json`中的`rehype-katex ^6.0.3`、`rehype-highlight ^6.0.0`
使用unified 10类型，与`react-markdown ^9.0.1`的unified 11形成插件类型冲突。
保留组件，通过对应插件7.x对齐unified 11，并继续运行Markdown原测试和完整typecheck。
移动后的TS依赖解析也必须隔离native UI的React 19；不能以any或降低strict掩盖此问题。

原版`useLazyHighlight.ts`直接使用lowlight 2的命名导出`lowlight`。升级rehype插件后显式声明该直接依赖，避免错误拾取插件内部lowlight 3；保留原hook代码及行为。

## 可复现全量源码清单

`PORTING_INVENTORY.json`由`scripts/inventory-librechat-port.py`从两个固定源码树生成，
列出生产后端、共享schema、SDK运行时与相关Agent前端模块的每个路径及SHA-256。
未建立函数级映射的条目明确标为未移植/待源码审计，不以文件数量估算功能完成率。
首批详细映射还新增了PluginController和原Ask User manifest两个来源，问答目录与临时
Agent的可选开关已接通；这与LSM机器执行权限是相互独立的检查。

发行审计另外发现原CI/Release依赖已提交的旧React压缩包，未随当前源码重新构建、Docker未打包React源码。
已补充build-only React构建和确定性archive步骤，并使单二进制smoke检查`/c/new`。
这些发行调整须以实际build/start/restart结果验收，不能仅以YAML存在判定完成。

## 2026-11-09 发行与权限回归

- `2c693afb`恢复原生write操作同时要求shell:read和shell:write的scope关系，不能仅凭机器write授权绕过原执行入口。
- `08d545d9`将React archive打入wheel；安装到独立virtualenv后的真实CLI启动、`/c/new`、API与PTY/WebSocket smoke通过。
- 原archive是已跟踪文件，本轮更新了它；此前“未生成”的表述不准确，实际缺陷是CI未刷新旧archive，以及wheel完全未包含它。
- `20830300`补齐锁文件中同版本Rolldown、Lightning CSS和Rollup的各平台native包。14个optionalDependencies记录已逐一对照registry元数据，冻结安装通过；跨平台构建仍以最新CI结果为准。
- 本地完整coverage脚本：2202 passed、2 skipped；HTTP/MCP/PTY/browser smoke通过，总覆盖率95.13%，所有模块至少90%。
- CI `42498081888`中五个平台wheel启动验证通过，但Windows binary及ARM64 Docker曾继续暴露Lightning CSS缺失。该运行不是全绿；`20830300`对应的新CI尚待最终验收。

高级Agent运行时的未完成项保持不变，不能用上述发行验证代替LibreChat行为等价验收。

## 生成协议源码移植

已逐函数移植`controllers/agents/protocol.js`的版本解析、三通道协商及已有job版本上限。
2197组body/query/header组合与已固定的原Node模块差分一致；另验证重复HTTP标记、
冲突标记、SQLite幂等重试、数据库重开及缺失旧metadata时保持v1。
生产入口在首次事务中固定协商版本，后续重试、SSE、状态查询、停止和恢复不能升级它。

这只完成协议协商模块。`request.js`的完整preflight、actor、steer恢复、v1历史适配与
LangGraph checkpoint仍未完整移植，不能因此宣称conversation恢复整体等价。
