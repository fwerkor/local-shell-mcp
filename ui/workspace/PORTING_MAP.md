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
路由transition，并通过checkpoint保证回放幂等。原自研 `delegate_agent`、`handoff_agent` 已被删除；当前接入原生工具，
完整多Agent图调度仍有未完成项，见下表。

## 文件与函数映射

“部分”表示已有可用代码，但未经完整行为对照或已发现差异；不表示该模块验收完成。
“未实现”也包括已有同名或近似自研功能但尚未按原版实现的情况。

| LibreChat/agents 原实现 | Python/LSM 对应 | 状态 | 具体差异 |
| --- | --- | --- | --- |
| `LibreChat:api/server/controllers/agents/protocol.js` — `getRequestedGenerationProtocol / negotiate*` | `webui/generation_protocol.py; generations.py; generation_routes.py` | 完成（协议协商函数） | 2197组body/query/header组合与原版Node函数差分一致；SQLite固定首次job版本，HTTP/SSE入口使用协商结果。整个request/resume controller及图级恢复仍不完整。 |
| `LibreChat:api/server/controllers/agents/request.js` — `generation ingress / disconnect` | `webui/generation_routes.py:start_generation` | 部分 | 缺失完整入口预检及断线处置语义 |
| `LibreChat:api/server/controllers/agents/resume.js` — `resume / checkpoint ownership CAS` | `webui/generation_routes.py:resume_generation` | 部分 | 批审批claim、已审核证据、owner/generation checkpoint与pending tools重放已接入；完整actor/steer/子中断聚合仍缺失 |
| `LibreChat:packages/data-provider/src/types/runs.ts` — `TContextUsageEvent / TTokenBudgetBreakdown` | `webui/context_budget.py; agent_runner.py; generations.py` | 部分 | 已发布SSE `on_context_usage`并在assistant.metadata.contextUsage持久化，重新加载与SSE断线重播可读；尚缺完整provider token校准/usage rollup |
| `agents:src/types/graph.ts` — `ContextUsageEvent` | `webui/context_budget.py` | 部分 | 原schema预算字段已接入，用离线BPE计算System/summary/tool schema/messages各份额；provider实际计费和精确prune仍未移植 |
| `LibreChat:api/server/controllers/agents/callbacks.js` — `Agent execution events` | `webui/generation_routes.py:_run_model` | 部分 | 工具name/args/completion/result字段对齐React并持久化；完整callbacks、子运行progress和actor生命周期未全部移植 |
| `LibreChat:api/server/controllers/agents/client.js` — `AgentClient / history / run lifecycle` | `webui/generations.py; generation_routes.py` | 部分 | 未移植完整AgentClient和事件actor生命周期 |
| `LibreChat:api/server/services/Endpoints/agents/build.js` — `buildOptions` | `webui/generation_routes.py:start_generation` | 部分 | project字段修复；spec、ephemeralAgent、完整模型参数未对齐 |
| `LibreChat:api/server/services/Endpoints/agents/initialize.js` — `agent graph loading` | `webui/delegation.py` | 未实现 | 现有简单子任务调用不等价，禁止标记完成 |
| `LibreChat:packages/api/src/agents/runtime.ts` — `AgentExecutionContext` | `webui/generation_routes.py` | 未实现 | 缺少原版transport-free执行上下文 |
| `LibreChat:packages/api/src/agents/load.ts` — `loadAgent / loadEphemeralAgent` | `webui/agents.py; generation_routes.py` | 部分 | 可选工具、spec、ephemeral选择未完成等价移植 |
| `LibreChat:packages/api/src/agents/initialize.ts` — `initializeAgent` | `webui/lsm_tool_registry.py; generation_routes.py` | 部分 | 原生LSM复用有效；LibreChat工具选择/资源/上下文未完整移植 |
| `LibreChat:packages/api/src/agents/run.ts` — `createRun / buildSubagentConfigs / buildAgentInput` | `webui/delegation.py; generation_routes.py` | 未实现 | delegate_agent/handoff_agent与原版graph/Command/子图不等价 |
| `LibreChat:packages/api/src/agents/hitl/askUserQuestionTool.ts` — `AskUserQuestionToolDefinition / createAskUserQuestionTool` | `webui/ask_user_tools.py` | 部分 | 原版schema已精确导出/移植，1–4问题payload和UTF-16长度上限已验证；图级interrupt/checkpoint完整语义仍待移植 |
| `LibreChat:packages/api/src/agents/hitl/resume.ts` — `resolveAskUserQuestionResume / mapToolApprovalResolutions` | `webui/generations.py:answer_question / claim_approval; webui/tool_approval.py` | 部分 | Ask User恢复校验与原Node函数91组输入差分一致，答案按id保存与恢复；approval仍缺批次/edit/respond等原版语义；审批决策映射/校验60组原Node差分一致并接入claim；实际批次执行仍未完成 |
| `LibreChat:packages/api/src/agents/hitl/answers.ts` — `retained answers / branch ordering` | `webui/generations.py:history` | 部分 | 已改活动分支；尚无跨compact保留用户回答/来源信任标记 |
| `LibreChat:packages/api/src/agents/hitl/policy.ts` — `approval rules / deny-ask-allow / policy hashing` | `webui/nested_mcp.py` | 未实现 | 当前对所有nested MCP强制approval，不是原版policy机制 |
| `LibreChat:packages/api/src/agents/checkpointer.ts` — `durable checkpointer` | `webui/checkpoints.py; agent_runner.py` | 部分 | 统一SQLite tuple/pending-write存储、owner/generation隔离、proposal/结果/完成状态恢复已接入；完整LangChain类序列化与graph actor链未实现 |
| `LibreChat:packages/api/src/agents/compaction.ts` — `summary checkpoint / manual outcome` | `webui/compaction.py; generations.py; agent_runner.py` | 部分 | 2079组原函数固定向量全通过；已去除50消息截断，实现完整当前分支历史+有效summary边界、手动compact、失败保原消息；事件actor和语义索引待完整移植 |
| `LibreChat:packages/api/src/memory/protection.ts` — `projectStoredMemories` | `webui/memory_protection.py; memory_routes.py; memory.py` | 部分 | 已支持memory字段选中、starter/custom过滤、历史记录安全投影；regex引擎是带时间上限的Python适配，非完全RE2JS |
| `LibreChat:packages/api/src/memory/handlers.ts` — `blockFilteredMemoryContent / createMemoryManagementHandlers` | `webui/memory_protection.py; memory_routes.py` | 部分 | POST/PATCH及agent memory写入均在SQLite写前检查；内容过滤返回原版字段结构，旧行GET保留统计字段并屏蔽内容；完整跨source/audit尚未移植 |
| `LibreChat:packages/api/src/agents/memory.ts` — `createMemoryProcessor / processMemory` | `webui/memory_agent.py; generation_routes.py` | 部分 | 原版Memory Agent显式`agent.enabled`与模型/Agent配置、仅由用户触发写入的prompt约束、BPE历史窗口、toolEnd执行、SQLite写入与源attachment事件已接入；完整Graph步骤、provider初始化/跨source过滤与usage仍未等价 |
| `LibreChat:api/server/controllers/agents/client.js` — `useMemory / runMemory` | `webui/memory_agent.py; generation_routes.py` | 部分 | 用户真实对话中并行发起自动memory任务，主响应结束前收敛，人工中断会取消；手动compaction不会自动触发MemoryRun；原完整event-actor/side-effect审批尚未移植 |
| `LibreChat:packages/api/src/agents/memory.ts` — `registerMemoryTools / tool usage guard` | `webui/memory.py; memory_routes.py; agent_runner.py; sqlite_store.py` | 部分 | 已实现显式capability/Agent marker、写删可选工具、命中规则和prompt guard、SQLite分区/事务/配额、REST，真实工具流和重启验证；缺少原RBAC/filters完全等价 |
| `LibreChat:packages/api/src/agents/attachments.ts` — `attachment limits / model-bound files` | `webui/attachments.py` | 部分 | LSM真实路径上传已实现；原版资源分类和模型输入链未完成 |
| `LibreChat:packages/api/src/agents/tools.ts` — `runtime tools / registry adaptation` | `webui/lsm_tool_registry.py` | 部分 | 复用LSM注册表；尚未按原版Agent选择与系统注入拆开 |
| `LibreChat:packages/data-schemas/src/schema/agent.ts` — `Agent schema / settings / graph / subagents` | `webui/agents.py; agent_validation.py` | 部分 | 原版HTTP validation.ts、参数sanitizer与owner引用约束已移植；完整资源能力/模型catalog/skill加载策略仍不完整 |
| `LibreChat:packages/data-schemas/src/schema/message.ts` — `message content persistence` | `webui/storage.py` | 部分 | messages关系表；高级content与run状态恢复未完整 |
| `LibreChat:packages/data-schemas/src/schema/convo.ts` — `conversation / branch / archive` | `webui/storage.py; conversation_routes.py` | 部分 | 基础CRUD/分支/归档；其余模型字段和hooks未全面对照 |
| `LibreChat:packages/data-schemas/src/schema/chatProject.ts` — `project membership and resources` | `webui/storage.py` | 部分 | 项目关联/默认权限；完整资源与消息语义待移植 |
| `LibreChat:packages/data-provider/src/createPayload.ts` — `React request payload` | `ui/workspace/packages/data-provider/src/createPayload.ts` | 部分 | 前端复用；后端尚未消费所有原版字段 |
| `LibreChat:packages/data-provider/src/runSteps.ts` — `execution event types` | `ui/workspace/packages/data-provider/src/runSteps.ts; generation_routes.py` | 部分 | 共享前端类型复用；后端事件仅子集 |
| `LibreChat:client/src/components/Chat/Messages/Content/AskUserQuestions.tsx` — `batched questions UI` | `ui/workspace/client/src/components/Chat/Messages/Content/AskUserQuestions.tsx` | 部分 | 原组件未修改；双问题选择/提交/同generation恢复真实Chromium E2E已通过；完整恢复/保留答案链仍待验收 |
| `LibreChat:client/src/components/SidePanel/Agents/Advanced/AgentSubagents.tsx` — `optional subagent configuration` | `ui/workspace/client/src/components/SidePanel/Agents/Advanced/AgentSubagents.tsx; webui/subagents.py` | 部分 | 原版配置保留，Python已正确消费enabled/allowSelf/agent_ids；graph子团队尚未执行 |
| `agents:src/graphs/Graph.ts` — `agent graph / tools / checkpoint` | `webui/agent_runtime.py; agent_runner.py` | 部分 | 标准model/tools节点循环与checkpoint游标已接入；summary节点、完整reducers/actor事件与breaker仍不完整 |
| `agents:src/graphs/MultiAgentGraph.ts` — `multi-agent routing / commands` | `webui/handoff.py; agent_runner.py` | 部分 | 原生transfer工具与单目标Agent切换已接入；parallel Send、direct-edge fanout/fanin尚未完整集成 |
| `agents:src/graphs/handoff.ts` — `HandoffRouting / mergeHandoffState` | `webui/handoff.py; agent_runner.py` | 部分 | 路由预算/transition幂等/状态已源码差分验证并接入单目标切换；全图并行调度仍待完成 |
| `agents:src/tools/SubagentTool.ts` — `buildSubagentToolParams / createSubagentToolDefinition` | `webui/subagents.py; agent_runner.py` | 部分 | 原生subagent schema、可选配置、隔离上下文和共享原生工具执行已接入；graph团队、后台/线程宿主与完整子运行事件仍缺失 |
| `agents:src/hitl/askUserQuestions.ts` — `askUserQuestions / interrupt / resolution` | `webui/ask_user_tools.py; agent_runner.py; checkpoints.py` | 部分 | 原schema/批答案/恢复校验和checkpoint pending-call重放已接入；子中断聚合、retained answers与完整actor链未完成 |
| `agents:src/hitl/askUserQuestionsInterrupt.ts` — `request/interrupt guards` | `webui/ask_user_tools.py` | 部分 | 原请求校验、payload与批次UI已验证；完整SDK图级中断/恢复语义仍待补齐 |
| `agents:src/tools/ToolNode.ts` — `parallel tool execution / interruption` | `webui/agent_execution.py; approval_runtime.py; agent_runner.py` | 部分 | 直接批工具并发、interrupt-first和结果重放已接入；eager/event paths、引用、完整hook与多子中断合并仍缺失 |
| `LibreChat:api/server/controllers/PluginController.js` — `getAvailableTools` | `webui/agent_routes.py:tool_catalog` | 部分 | Ask User原manifest和authenticated形状已复用；其余builtin/toolkit/过滤策略仍待移植 |
| `LibreChat:api/app/clients/tools/manifest.json` — `ask_user_question manifest entry` | `webui/ask_user_tools.py:ASK_USER_MANIFEST` | 部分 | 原始条目精确复用并做catalog接口测试，其他LSM适用工具仍待审计 |

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

## 共享执行循环集成（待全量验收）

新增`agent_runtime.py`/`agent_execution.py`/`agent_runner.py`，父子Agent使用同一provider与
LSM MCP分发入口。标准model→tools→model路径按节点计算递归预算，不再使用自研三轮上限。
`subagent`与配置生成的`transfer_to_<id>`已接入生产generation入口；旧`delegation.py`
和`delegate_agent`/`handoff_agent`工具定义已删除。新数据库不再创建旧delegations表；
已有数据库中的表不做破坏性删除。

统一SQLite saver保存执行游标、Agent、消息、待执行调用与已完成的ToolMessage。
已验证模型完成节点重开后不重复请求provider、工具结果写入后重开不重复调用原生执行器。
这不消除外部副作用发生后、结果落盘前的崩溃窗口，也不等于完整LangGraph scheduler。

审批执行改为原版可选endpoint policy（endpoints.agents.toolApproval），而非强制每次MCP
调用审批。原版approve/reject/edit/respond转换及批次claim已接入共享执行器；
真实批量file_write验证edit仅写入批准路径，reject无执行。工具选择在暂停/审批前也会校验。

事件字段对照React `useStepHandler.ts`，使用原版tool_call.name/args和
on_run_step_completed.result；工具结果保留到最终消息及SQLite历史。

尚未完成：并行handoff接收者、direct-edge图、graph子团队、后台/子线程宿主、
完整子Agent中断合并与事件、summary/Memory/Actions/Artifacts及完整actor恢复。
当前单目标handoff和前台孤立subagent测试通过，不应表述为这些大模块全部等价。

本轮本地全量验收：2287 passed、2 skipped；总覆盖率95.30%，所有模块至少90%；
HTTP、MCP、PTY、browser smoke通过。随后补充的React原生工具卡片及历史刷新用例
与批次Ask User合计2项浏览器测试通过。新运行时尚须当前提交的跨平台CI验收。


## 原版聊天附件链路（2026-11-09）

| 原版源码 | Python/LSM | 状态与必要适配 |
| --- | --- | --- |
| `api/server/routes/files/files.js:handleFileUpload`、`images.js`、`multer.js` | `webui/attachments.py:upload_react_file/publish_attachment` | 部分；multipart、服务端UUID、temp_file_id、解码文件名、flat DTO；32MiB流式安全存储复用原上传发布器 |
| `api/server/services/Files/process.js:processAgentFileUpload`、`packages/api/src/files/sse.ts:sendUploadSuccess` | `upload_react_file` | JSON成功响应字段及message对齐；可选上传SSE未启用；Agent resource/OCR/RAG未实现并明确拒绝 |
| `client/.../Files/AttachFileChat.tsx`、`useFileHandling.ts`、`createPayload.ts` | 保留原组件与状态；`ChatForm.tsx`恢复原调用 | 已验证实际Chromium选文件→原multipart→消息files；删除自研上传按钮/文本框事件桥 |
| Agent输入文件解析 | `generations.py:begin/history` | LSM必要适配：文件ID按当前owner从SQLite查真实Controller路径传给模型，不信任客户端filepath；历史保留原files DTO |

原版JSON上传返回值保留`file_id/temp_file_id/filepath/filename/type/source/bytes/context`。
浏览器filepath是认证下载URL，物理路径只从服务端所有权查询进入模型上下文。
已验证：真实React上传/模型输入、缺失/重复/他人文件ID、空文件、超限流、坏multipart、
无效临时ID、存储失败回滚、已删除文件下载404。文件不会自动复制到Remote Worker。
未完成：Agent资源版本事务、文件删除API、OCR/RAG、图片预览/Provider多模态直送、可选上传SSE。


## Agent资源事务、运行中授权及迁移恢复（2026-11-09）

| 原版/LSM边界 | 实际模块 | 已验证行为及限制 |
| --- | --- | --- |
| `data-schemas/src/methods/agent.ts:addAgentResourceFile/updateAgent/removeAgentResourceFiles` | `webui/agents.py:add_resource_file/_update_locked/remove_resource_files` | 原addToSet成员去重、operator写前版本、重复operator仍造版本、pullAll不造版本；同SQLite事务绑定真实附件，归属与并发检查。不是OCR/RAG processing实现 |
| 上述原函数及版本辅助函数（AST原样提取） | `tests/fixtures/librechat/agent_resource_operators.cjs` 与source/golden/oracle | 执行原版函数的30条操作序列、115次状态转换与Python成员/版本快照逐项相等；测试Mongo适配器只覆盖这些operator和无code-environment依赖分支，不宣称完整Mongo/Agent Runtime等价 |
| LSM统一执行权限 | `lsm_tool_registry.py:_await_authorized` | 等待原生调用时每0.5秒重验授权；撤权/过期取消该调用并等待原生清理，原生不可取消写入继续原子收敛。已返回后台job与Remote取消传播仍须独立验收 |
| 已发布文件状态→统一SQLite | `sqlite_store.py:migrate_files/_import_legacy_file` | 删除tombstone防旧文件复活；复用现有1MiB分块存储导入超64MiB文件；源stat一致性、摘要、所有行/chunk/journal事务回滚，保留原件。32个迁移测试含65MiB和重启恢复通过；不替代真实用户生产备份验收 |

原生执行中撤权、过期、调用隔离、Agent自身工具、protected写入收敛等30项测试通过。
资源事务含真实磁盘发布回滚和多线程追加无丢失，16项测试通过。


## SDK Graph构造语义与执行准入（2026-11-09）

| 原版源码 | Python对应 | 实际状态 |
| --- | --- | --- |
| `graphs/MultiAgentGraph.ts:constructor/validateEdgeAgents/categorizeEdges/validateCommandRoutedDirectEdges/analyzeGraph/computeParallelCapability/resolveEntryReachability/validateHandoffScopes` | `webui/graph_topology.py:GraphTopology` | 原函数AST提取后的Node构造oracle与967组Python拓扑、分组、可达性、错误结果逐项相等；不执行StateGraph |
| `MultiAgentGraph.categorizeEdges`的隐式边规则 | `handoff.py:outgoing_handoff_edges` | 无edgeType的1→1边按上游生成transfer工具；默认single-source fan-out按direct处理，不再静默漏掉普通handoff |
| 当前可执行子集准入（LSM必要适配） | `graph_topology.py:admit_agent_graph`、`AgentRunner._context/_dispatch` | 所有成员重验owner；direct/多入口图当前明确拒绝，多个handoff提案在路由状态/完成结果写入前拒绝，避免运行局部图冒充成功 |

原版构造函数仅替换无模型作用的StandardGraph agent-context初始化和HandoffRouting构造记录，
createHandoffTools在oracle中禁用；原构造/验证方法体不改写，fixture含SDK commit/hash和MIT license。
保存到SQLite的隐式单边Agent真实经过同一模型/工具循环，已验证parent→owned child完成；
unsupported direct/default-fanout在首次provider调用前拒绝。原单目标handoff回归保留。

这不是parallel/direct-edge执行完成：完整SDK执行仍依赖消息ID归约器、agentMessages替换通道、
runStep/handoff reducers、superstep checkpoint与子图中断恢复；没有使用gather拼接文本替代。

## Artifact editor backend source port

Source: `packages/api/src/artifacts/update.ts`, `packages/api/src/utils/latex.ts`,
`api/server/routes/messages.js` (`POST /artifact/:messageId`), and the immutable
child policy in `packages/api/src/agents/guard.ts` / `subagentThreadIds.ts` at
LibreChat `e8f3be08623663d4ad7f7241e693c94469b63bb0`.

Python: `webui/artifacts.py` and `webui/artifact_routes.py`; the original React
artifact editor's POST route is registered before generic message routes.
Original code is transpiled by `scripts/export-librechat-artifacts.cjs`, with
source/fixture SHA-256 provenance and 630 parser/replacement vectors. Unicode
offsets and submitted-path lengths follow JavaScript UTF-16 semantics, including
fenced/unclosed blocks and LaTeX preprocessing reversal. SQLite updates preserve
other content and metadata, commit atomically, and retain source path provenance.

Validated: actual Node-vs-Python behavior, owner denial, missing/invalid edits,
reconnect persistence, immutable child/reserved thread rejection, failed SQLite
write rollback and successful retry. New parser module coverage is 97.6%; route
coverage is 100% in the focused suite.

Scope remains **partial Artifacts parity**: this ports text-artifact editing,
not all model/tool artifact production callbacks or host content-filter policy.
The active background child-task store guard awaits the full graph host; durable
child metadata and the original reserved UUID namespace are already read-only.
Malformed non-integer indexes/non-string edit bodies are rejected with 400 at the
Python boundary rather than surfacing the upstream route's accidental 500.

The retained React Artifact editor now loads its original Monaco component from
self-hosted build assets (`/monaco/vs`), including the upstream MIT license. The
build copies the installed, lockfile-resolved Monaco assets; production requires
no CDN or Node service. A real Chromium test blocks every external request,
uses the original radio controls and editor, saves through the original route,
then reloads and verifies the persisted code. Editor assets revalidate on each
page load to prevent a stale AMD loader after a Controller upgrade. Oracle
fixtures use explicit UTF-8 and LF checkout to preserve source hashes on Windows.

Text-history replay now reads persisted structured text parts before
the top-level text snapshot, following the field precedence in the original
`api/app/clients/prompts/formatMessages.js:formatAgentMessages`. Consequently
an artifact edit reaches the next model turn while the source editor contract
still leaves unrelated top-level text untouched. Full rich/tool-step history
reconstruction is not claimed by this text-history change.

The full editor browser flow also continues the chat after reload and asserts
that the model sees the edited code. This uncovered and fixed an existing
conversation DTO mismatch: `convoSchema.agent_id` is optional but not nullable,
so an unassigned Agent is omitted instead of serialized as null. The retained
React schema remains unchanged.

## Memory / 上下文预算 / 语义压缩移植（本PR）

- 固定源：LibreChat `e8f3be08623663d4ad7f7241e693c94469b63bb0`，npm agents `4.0.1` / `c4ffb9b1b78421bf63eba3e56993017f922387f3`，见 `UPSTREAM_LOCK.json` 中各源文件SHA256。
- 功能映射：memory routes/model/handlers → `memory_routes.py`、`memory.py`、`sqlite_store.py`；SDK compaction纯函数 → `compaction.py`；trigger/recency/budget → `context_budget.py`；model stream与checkpoint切换 → `agent_runner.py`、`generations.py`。SQLite `webui_memories` 使用 owner/agent/key 事务唯一约束，数据位于现有 `.local-shell-mcp/lsm.sqlite3`。
- 原启用前提：有memory配置、Agent endpoint `memory` capability 和 Agent.tools `memory`，用户未opt-out；UI查询单独遵循原memory权限集合。机器授权与工具启用完全分开。原管理员配置存储在同一用户 `endpoints.memory`/`webui.memory.config` 键；默认不自动开启。
- token：单独的可选 WebUI 依赖 `tiktoken`，`o200k_base.tiktoken.gz` 随Wheel发行（gzip压缩后1.69 MB，内存解压，SHA256校验原始内容）；SHA256 `446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d`，首次使用绝不下载。主Worker不依赖它。
- compaction：前置模型调用生成摘要，只有完整非空结果才存入当前run的 `summaryCheckpoint` 并在结束事务中提交为有效message part。旧消息永不删除。读取完整活动分支，遇最后有效summary载体停止回溯；失败/取消/崩溃或无效summary不替换历史。图检查点继续使用原有 `SQLiteCheckpointSaver`。
- 已验证：纯函数2079组源向量、memory SQLite CRUD+并发/配额/隔离、51轮长会话/tool结果配对/思考内容、失败与取消、完整HTTP/SSE summarizer和原版React浏览器下一轮及刷新后恢复。
- context usage：原版 `on_context_usage` 事件形状接入SSE重播；根据每次模型调用前的有效消息计算system、summary、tool schema及message份额，写入同一run的state并在结束事务中固定到 `responseMessage.metadata.contextUsage`，React刷新后可恢复。该预算是离线BPE保守估计，缺少provider真实token校准/请求cache/fading费用，不能当作provider计费统计；只有指定了合法max context时才生成快照。授权后的启动配置开放原版上下文用量UI，匿名仍不暴露接口能力。
- 新增Windows粗粒度事件循环下GUI TTL回归稳定性测试；新增真实SQLite重启后“摘要已完成但answer崩溃”与“摘要失败”两种历史恢复测试，CI旧Linux安装失败是Runner解析Ubuntu包源域名中断，未擅改构建依赖。
- 未完全等价：源RBAC（适配为LSM单用户owner）、完整跨source filter审计/RE2JS、SDK provider token校准和按provider native消息格式计算、跨tool pair的intra-turn fallback、动态semantic index/完整事件actor、自定义摘要策略的Graph reducer；这些仍标记“部分”，不可用这批纯函数向量充当整套图运行时已完成的证据。
- Memory字段过滤：按原版保护来源配置读取 `webui.filters.config` 或 `endpoints.filters`，支持`memories.pii.fields`、starter三规则、custom regex及`audit`不阻止行为；旧记录在GET与模型上下文读取前按最新policy投影，原始SQLite行不篡改且总token按存储值计算；写入新记录或修改在提交前阻止并返回不泄漏原值的`content_filter_block`。为规避Python正则退化，超时及不支持的pattern在memory路径 fail-closed，完整原RE2JS与跨source事件审计尚未移植。

- Memory启动兼容：`regex`与BPE tokenizer同属可选 `.[webui]`，在`memory_protection.py`按需加载。没有安装WebUI extra的纯Controller Wheel仍可正常启动；如启用了Memory PII过滤而regex缺失，策略执行安全拒绝并遮蔽字段，不会以错误忽略过滤。覆盖独立Python子进程模拟`ModuleNotFoundError: regex`，这修复此前GitHub CI wheel和独立包启动失败。
- Agent `useMemory` read-only上下文与原版保持一致：配置Memory并获用户授权时，主Agent即使不含`memory`工具也能读取withoutKeys；只有确实注册inline memory capability时才得到withKeys和`set_memory/delete_memory` guard。自动MemoryRun的默认指令文本已与原版`getDefaultInstructions`对齐。
- 可选自动Memory Agent：源配置`memory.agent.enabled=true`且提供同owner的`agent.id`或`provider`+`model`后，使用现有Provider流、BPE裁剪的用户对话窗口、原Memory tool接口和共享SQLite记录执行MemoryRun；每条记忆写入由`MemoryRepository`事务校验，再把工具artifact以原`attachment` SSE形状持久化。默认关闭、用户opt-out后不再执行、授权过期后禁止写入、手动compact不触发、模型处理失败不影响原会话、外部取消同步撤销同一run内的自动任务。已验证原SSE tool_call碎片经真实loopback HTTP服务复原、落库、重启回放及无效Agent/权限/Policy边界。
- 失败隔离：自动Memory Agent的配置/初始化/可选Tokenizer缺失等异常只记录为MemoryRun失败，主Agent已成功的回答照常提交；回归测试模拟独立Memory任务启动后抛出异常，验证主对话仍完成。
- 自动Memory Agent仍非上游LangGraph内部Run等价：无完整hook/model-bound所有来源检查、token使用量/独立Agent流事件、Graph actor调度；它是源码gate+数据/工具协议的Python接入，完整等价需与并行graph/protocol端口衔接，不能宣称整套Memory已完成。

**WebUI发行适配：** PyPI Wheel 保持 `webui` 可选 extra；Docker和单二进制发行始终提供完整WebUI，构建时额外安装 `.[webui]` 并收集 tiktoken。Worker 通过显式源文件白名单打包，不携带 tokenizer 或 WebUI 编码数据。
