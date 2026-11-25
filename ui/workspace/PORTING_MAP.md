# LibreChat 源码级移植映射

本清单替代“同名功能即可算完成”的旧判断。PR #343 已合入；Actions 独立 PR #349 保持 Draft。

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
| `LibreChat:packages/api/src/memory/handlers.ts` — `blockFilteredMemoryContent / createMemoryManagementHandlers` | `webui/memory_protection.py; memory_routes.py` | 部分 | POST/PATCH及agent memory写入均在SQLite写前检查；内容过滤返回原版字段结构，旧行GET保留统计字段并屏蔽内容；跨source核心审计与真实model/tool链已接入，原RE2JS/全路由adapter仍未移植 |
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
- 源码索引差分：`semantic_index.py`已实现`@librechat/agents@4.0.1` 的 `snapshotCompactionSemanticIndex`、`renderCompactionSemanticIndex` 及可信`provider provenance`读入，包含前后端身份、修订冲突、未提交/脱敏排除、XML安全预算、覆盖均衡算法；用锁定TypeScript代码生成的230组fixture（包含代理校验）差分全部通过，并在`_summarize_history`及自动预算触发链中接入（只有可信上下文提供索引时才注入）。通过`semantic_index_source.py`从owner受限的SQLite消息祖先链自动提取可信的工具outcome，以及显式声明了intentToolNames时的工具intent；只有与将摘要的model-visible工具调用/结果一对一精确匹配才绑定有效provenance。已加入匹配实际provider-facing assistant content+reasoning后才认证的`activity_phase`/`reasoning_label`来源索引（含pending/ malformed遮蔽），并实现超过256条时前64、后128、每类首尾8条的有限覆盖保留和原总条数计数；完整collector的revision hash合并/流式增量、Graph事件actor仍归Graph集成PR。
- Provider Token 校准：主模型适配器现解析OpenAI Chat Completions usage (`prompt_tokens`/`completion_tokens`)、Anthropic (`message_start`+`message_delta`，包含cache read/write token)及Gemini `usageMetadata`，SSE工具流同样接入。`ModelUsage`作为独立元数据交由AgentLoop处理，不进入答案或checkpoint。按锁定`messages/prune.ts`的累计raw/provider计数（ratio钳制0.5至5），在同一SQLite事务内写入运行状态与会话元数据，跨重启和后续会话读取；预调用`calculate_budget`和`on_context_usage`使用已确认校准，未收到usage时保持BPE估计1.0。所有OpenAI-compatible endpoint统一请求`stream_options.include_usage`，不支持时自动重试且不带该字段。Google/Anthropic流直接读取原生使用量。主模型计算正常完成而usage保存失败时，不影响用户答复。Fading v2预算梯和provider视图裁剪已单独实现；按tool name的精确原生token分配、provider账单估算仍未移植。
- Fading Tier：已直接调用锁定TS源码生成450组边界/随机向量，`fading.py`的v2预算梯、caps、tier seed/resolve/掩蔽/版本迁移全数等价。`agent_runner`在每次模型调用前按校准上下文压力与本轮并行工具宽度递进并将v2 tier按Agent/model/owner持久化，自动或手动Compaction成功后重置。Provider-only `fading_projection.py`对工具消息文本与工具入参作深拷贝裁剪；文字裁剪现使用独立的`truncation_source.py`，300组从锁定TypeScript`truncateToolInput`/`truncateToolResultContent`直接执行生成的边界差分向量完全一致（含UTF-16代理对、换行边界、head-tail比例），输入JSON包装仍在预算不足时保证合法结构；SQLite历史/暂停恢复原始值不变；未提供maxContextTokens时维持原行为。验证source tier v2、跨重启owner、正常问答及摘要重置。完整`originalToolContent`/RE2JS与Prune的原结构化序列化策略尚有差异。
- 未完全等价：源RBAC（适配为LSM单用户owner）、精确RE2JS与部分REST content adapter/Graph来源属性、按provider native消息格式计算、跨tool pair的intra-turn fallback、语义索引collector修订哈希/完整事件actor、自定义摘要策略的Graph reducer；这些仍标记“部分”，不可用这批纯函数向量充当整套图运行时已完成的证据。
- Memory字段过滤：按原版保护来源配置读取 `webui.filters.config` 或 `endpoints.filters`，支持`memories.pii.fields`、starter三规则、custom regex及`audit`不阻止行为；旧记录在GET与模型上下文读取前按最新policy投影，原始SQLite行不篡改且总token按存储值计算；写入新记录或修改在提交前阻止并返回不泄漏原值的`content_filter_block`。为规避Python正则退化，超时及不支持的pattern在memory路径 fail-closed，Memory audit-only现在通过安全元数据日志输出；完整RE2JS与部分其它来源的REST适配仍未移植。

- **Content filters跨来源**：新`webui/content_filters.py`按锁定`protection/runtime.ts`配置类别覆盖13种来源（包括`assembled_context`、model/tool参数、消息、memory、文件/Prompt/Action元数据的纯函数检查）。严格依据`fields`选择（`modelParameters`遵循原版`stop`/`request_fields`/`response_format`/`metadata`字段映射及`options`/`model_parameters`嵌套别名），默认三starter+自定义线性语法白名单、嵌套键值遍历/大小/数量上限；全局自定义pattern数256与regex总长8192。audit-only模式按source/field/provenance/rule聚合记录元数据并排除原文，审计设施故障不影响允许的请求；block模式失败前返回`content_filter_block`，无用户文本。真实HTTP chat启动、Agent instructions/model parameters、AgentLoop assembled context、model tool-call入参在checkpoint和SSE写入**前**遮蔽、工具执行前校验、输出回传前遮蔽、Memory GET与写入前audit均覆盖回归。**局限**：Python timeout regex是保守RE2JS适配，不等于原JS RE2Set；完整文件扫描/Action/Prompt/Feedback等独立REST adapter尚依赖对应并行PR，也不声称已经完全移植。
- Memory启动兼容：`regex`与BPE tokenizer同属可选 `.[webui]`，在`memory_protection.py`按需加载。没有安装WebUI extra的纯Controller Wheel仍可正常启动；如启用了Memory PII过滤而regex缺失，策略执行安全拒绝并遮蔽字段，不会以错误忽略过滤。覆盖独立Python子进程模拟`ModuleNotFoundError: regex`，这修复此前GitHub CI wheel和独立包启动失败。
- Agent `useMemory` read-only上下文与原版保持一致：配置Memory并获用户授权时，主Agent即使不含`memory`工具也能读取withoutKeys；只有确实注册inline memory capability时才得到withKeys和`set_memory/delete_memory` guard。自动MemoryRun的默认指令文本已与原版`getDefaultInstructions`对齐。
- 可选自动Memory Agent：源配置`memory.agent.enabled=true`且提供同owner的`agent.id`或`provider`+`model`后，使用现有Provider流、BPE裁剪的用户对话窗口、原Memory tool接口和共享SQLite记录执行MemoryRun；每条记忆写入由`MemoryRepository`事务校验，再把工具artifact以原`attachment` SSE形状持久化。默认关闭、用户opt-out后不再执行、授权过期后禁止写入、手动compact不触发、模型处理失败不影响原会话、外部取消同步撤销同一run内的自动任务。自动MemoryRun现与主Agent一致，对实际将送入Memory模型的instructions、assembled-context做跨来源policy检查，在内存工具写入前检查toolArguments source，避免memory单独运行路径绕过项目过滤策略。已验证原SSE tool_call碎片经真实loopback HTTP服务复原、落库、重启回放及无效Agent/权限/Policy边界。
- 失败隔离：自动Memory Agent的配置/初始化/可选Tokenizer缺失等异常只记录为MemoryRun失败，主Agent已成功的回答照常提交；回归测试模拟独立Memory任务启动后抛出异常，验证主对话仍完成。
- 自动Memory Agent仍非上游LangGraph内部Run等价：无完整hook/model-bound所有来源检查、token使用量/独立Agent流事件、Graph actor调度；它是源码gate+数据/工具协议的Python接入，完整等价需与并行graph/protocol端口衔接，不能宣称整套Memory已完成。

**WebUI发行适配：** PyPI Wheel 保持 `webui` 可选 extra；Docker和单二进制发行始终提供完整WebUI，构建时额外安装 `.[webui]` 并收集 tiktoken。Worker 通过显式源文件白名单打包，不携带 tokenizer 或 WebUI 编码数据。
## Multi-agent StateGraph runtime (2026-11-11, independent Draft PR)

Baseline: LibreChat v0.8.8 at `e8f3be08623663d4ad7f7241e693c94469b63bb0`;
`@librechat/agents@4.0.1` at `c4ffb9b1b78421bf63eba3e56993017f922387f3`;
original integrated **JS** `@langchain/langgraph@1.4.8`,
`@langchain/langgraph-checkpoint@1.1.3`, `@langchain/core@1.2.8`.
The upstream `bun.lock` newer agents version is **not** the runtime baseline.

| Upstream source and event/state contract | Python WebUI implementation | Evidence / limitation |
|---|---|---|
| `src/messages/reducer.ts`, `@langchain/langgraph.messagesStateReducer` | `webui/message_reducers.py`: `messages` merge/replace/RemoveMessage/remove-all, `agentMessages` last-value | `tests/fixtures/librechat/graph_runtime_real_reference.cjs` instantiates actual JS `HumanMessage` / `AIMessage` / `ToolMessage` / `RemoveMessage` from exact locked npm packages (11 real-object vectors); `test_webui_graph_real_differential.py`. Canonical LSM dictionaries at Python boundary, not an independent JS BaseMessage class hierarchy. |
| `src/graphs/MultiAgentGraph.ts:createWorkflow`, `src/graphs/Graph.ts` | `webui/graph_runtime.py`: Python `StateGraph(MultiAgentState)` with official `Command` / `Send`, direct/default fan-out, conditional source handoff routing, join edges, prompted fan-in, per-node AgentRunner | Original JS real-class `StateGraph` fan-out/barrier, `Command` and `Send` traces matched to real Python LangGraph 1.0.10. Multiple entry/superstep, direct+handoff exclusive dispatch, parallel receivers tested. AgentRunner is still the only model/provider/tool loop. |
| `graphs/handoff.ts:HandoffRouting/mergeHandoffState` | existing `webui/handoff.py` reducers and pending transfer commands; `graph_runtime.py` owns routing | Existing source-oracle handoff reducers retained; native graph converts to actual Python `Send`, never schedules using the old single-destination fallback. Shared transitions are checkpointed and merged in graph channels. |
| `packages/api/src/agents/run.ts:buildSubagentConfigs` | `webui/subagents.py` graph-team configurations, `graph_runtime.py` child isolated namespace | Owned member verification, DAG entry/result, foreground child context and filtered final tool result tested. Subgraph child uses the same generation, grants, executor and checkpoint backend. |
| `agents/checkpoints/saver.ts`, `@langchain/langgraph-checkpoint` | `webui/graph_checkpoint.py:OwnedGraphCheckpointer` wraps existing `SQLiteCheckpointSaver` and SDK's typed `serde`, preserving `Send` and pending writes | Durable graph/parent-child checkpoints in unified `.local-shell-mcp/` SQLite, restart after cancellation and new runner replay, owner rejection, list/async API and pending Send tested. No Worker import or Node/Mongo runtime dependency. |
| `agents/hitl/resume.ts`, AskUser, Approval | Existing `webui/generation_routes.py`, `generations.py`, `AgentRunner._pause` | Graph-node Ask User and file-write tool approval verified by actual pending action, one-shot claim, HTTP resume and second Runner. Existing machine ACL and scopes still gate actual LSM execution; enabling tool never grants access. |
| `Run` callbacks and background Subagent hosts | Existing `GenerationStore` event log and graph-node tool events | **Not complete**: durable background child task/thread queue and continuation are not implemented by this PR; current explicit refusal remains. Full structured RunStepState/Graph stream and arbitrary JS BaseMessage/tool-call fidelity remain outstanding and depend on host-message protocol work. |

`pyproject.toml` defines optional `webui-graph` dependency (`langgraph>=1.0.10,<1.1`,
`langchain-core>=1.2.8,<2`). CI test jobs install this Controller-only extra. The browser/source E2E job
installs exact original JS npm runtime versions in a temporary oracle-only
directory, and runs the live original-message classes and graph traces with
`LSM_REQUIRE_SOURCE_ORACLES=1`, without leaking Node into production.
Production Worker distribution remains independent of LangGraph, Bun, Node and Mongo.
No changes to underlying LSM MCP registration/execution, machine permission scopes,
Shell/Job/File implementations, timeout policy, idempotency or audit hooks.

To rerun in a clean isolated worktree: `PYTHONPATH="$PWD/src" .venv/bin/python -m pytest -q tests/test_webui_full_graph_runtime.py tests/test_webui_graph_real_differential.py tests/test_webui_graph_checkpoint_reducer.py`.
For the real JS oracle provide Node, the exact pinned npm packages and
`LSM_JS_ORACLE_ROOT` pointing at their installed package root. A committed fixture
retains the reference output for test environments without Node dependencies.
CI coverage gates remain unchanged (global ≥95%, per module ≥90%).

### Graph checkpoint and HTTP recovery contract

`MultiAgentState` uses the original source channel names: `messages` (ID-aware
LangGraph message reducer), `agentMessages` (last-value replacement),
`handoffState` (source merge reducer), `subagentResult` (designated team sink)
and `manualSummary` (optional summary). A node emits existing generation events
`on_run_step` / `on_message_delta` / `on_run_step_completed`; tools retain the
source event IDs and full owner ACL. The graph adds no separate provider loop
or task dispatcher.

Checkpoint identity: `(owner, conversation_id, run_id + ':graph:' + namespace)`
for graph supersteps, `(owner, conversation_id, run_id, checkpoint_ns=namespace)`
for per-node model/tool states. The single unified SQLite database stores
`pendingWrites` and serialized SDK `Send` instances; runtime extras are
Controller-only, not Worker dependencies. A resumed `ainvoke(None)` reads the
latest graph checkpoint and executes only unfinished nodes. On a cooperative
Controller shutdown (not explicit Abort), running generations retain their
checkpoint and status. A client can `POST /api/agents/chat/resume` with
`conversationId` (and optionally `generationCreatedAt`) to use the **existing**
`_start_task` generation scheduler; no duplicate initial `on_run_step` or SSE
deltas are emitted. Previously sent text is reconstructed from the owner-scoped
`generation_events`. This recovery path rechecks machine ACL and grant scopes;
a missing checkpoint or an expired/mismatched generation identity is rejected.

The no-action recovery path assumes the project's single active Controller
process; **no cross-process SQLite execution lease** is introduced. An HA
multi-Controller deployment would need a shared generation-lease protocol.
Restart after a previously consumed Ask User response before the continuation
has created a checkpoint also needs a durable input replay record. Detached
background child threads are still explicitly unavailable until the shared
host task/thread store and message-protocol PRs land.

### 2026-11-12 — 后台 Subagent / 子线程宿主与重启恢复（PR #354 续）

固定参考仍是 LibreChat `e8f3be08` 与原集成 npm `@librechat/agents@4.0.1`
(`c4ffb9b1`)，**没有**使用上游 bun.lock 的不同 agents 版本。
关键对应关系：

| 固定原版调用链 | Python/SQLite 一对一执行位置 | 证据与保留限制 |
|---|---|---|
| `Graph.ts:subagentTool → SubagentExecutor.executeInBackground` | `subagents.invoke_subagent → SQLiteSubagentTaskHost.start → _ensure_active → AgentRunner.run` | 根父调用 ID、Agent ID、run ID 与可信 conversation 作用域在首次 SQLite `BEGIN IMMEDIATE` 中写入，然后才允许启动后台模型/工具；重试参数不一致拒绝。独立 child Generation 与既有 AgentRunner/StateGraph 共用执行器，**没有实现新的 Graph 或 LSM 工具调度器**。 |
| `types/subagentTasks.ts` + `InMemorySubagentTaskStore.ts` | `webui/subagent_task_host.py` 与共享 `sqlite_store.py` 中的 task/thread/control/invocation 表 | 完整任务状态、capacity、过期清理、一次性 result claim，`steer/queue/interrupt/cancel_message` 受限 message length、control count 与 SQLite 回执；收敛在工具、preempt、turn 边界，checkpoint 写成功后 ack。真实 npm 4.0.1 类和 `HumanMessage`/`AIMessage` 的差分见 `subagent_task_real_reference.cjs`。 |
| `subagentThreads.ts:SubagentThreadTaskStore` | `SQLiteSubagentTaskHost.start` 的 owned-thread 查询与 `initial_messages` | 线程属于 `(owner, parent_conversation_id, subagent_type)`，完成后持久化 history，后续 `subagent_thread_id` 创建新的 child generation；父子任务使用相同根 conversation 授权，嵌套 parentRunId 还须由可信 active task lineage 证实。 |
| `background.ts:registerBackgroundTaskTool / runCheckBackgroundTask` | `agent_runner._context/_invoke` → `check_background_task_tools / host.check` | 与原版相同的 `check_background_task` 工具名、枚举、参数长度限制，模型不能通过 task id 查看/取消他人 scope；按 `run+agent+tool_call_id` 做不可变 control invocation fence，失败的模糊重放不伪装成已接受。 |
| 原宿主对任务生命周期的拥有权 | `main.py:lifespan → active_child_generations/recover_subagent_tasks` | Controller 启动时保留可恢复 child generation 的 running 状态；SQLite 租约过期后自动认领，不必等待用户再轮询。每次执行有独立 lease token；持有者续租，失去授权/租约后下一个模型/工具检查拒绝，取消报告与真正任务终态区分。 |

**边界说明：** 后台子任务的模型、工具调用和 checkpoint 持续复用原有
`AgentRunner`、`OwnedGraphCheckpointer`、`GenerationStore`、`lsm_tool_registry`，
没有修改 Job/Shell/File 执行实现或机器 `none/read/write` 权限模型。
权限、已启用工具、有效 grant、scope 和 owner 在线上运行前及各工具调用前重新检查。
单 Controller 中断与重新启动、嵌套 root→middle→leaf、续线程、取消/远端租约、
控制回执、线程跨作用域阻断均有实测；原版 JS TaskStore 的真实对象对照纳入源码 CI。

尚需另行完成：原版 background completion wakeup/attachment/普通工具后台化，
跨 Controller 的外部 event/control routing、所有 Hook 回调和富媒体 RunStepState，
以及全量自动问答/审批事件的 host actor 恢复。上述不应以当前子任务成功测试冒充
整个 LibreChat 运行时等价。保持全局 ≥95% 和单模块 ≥90% 的覆盖门槛不变。

### 2026-11-12 — 与 Artifacts Draft PR #352 的原版 child-thread guard 接口

按 PR #352 明确公开的接口而非臆造 UUID/提示词识别：
`packages/api/src/agents/guard.ts:isSubagentThreadWriteBlocked` 的 Python Artifacts
实现依赖 `webui/child_thread_activity.py:ActiveChildThreads` 和
`active_subagent_threads` 表。这个模块仍归 PR #352 所有；**本 PR 不复制其表或写入路由**。
后台任务宿主现在在首个原子 task intent 中保存 host 产生的 UUID 和 parent run
身份；`ActiveChildThreads.activate(owner, childConversationId, parentRunId)`
发生在 `GenerationStore.begin(trusted_new_conversation_id=...)` 创建 child conversation
**之前**，而非在文件编辑时推断。另一个同幂等键调用在 `child_registered=1`
持久确认之前不能执行子模型。如果进程在 marker 持久化后、task admission 确认前崩溃，
恢复时仅凭 `(owner,child_id,parent_run_id)` 的原版宿主标记重建 admission；无可信
标记则拒绝启动。运行最终完成/取消/错误后，调用
`ActiveChildThreads.settle(owner, childConversationId, parentRunId)`，不删除已登记子线程，
以便 PR #352 的 artifact mutation guard 按源码一直保持只读。

`tests/test_webui_subagent_task_artifact_guard.py` 在无 PR #352 情况下使用其实际
`activate/settle` API 的可验证契约替身，覆盖创建前登记、所有者范围、正常终态、取消、
幂等重放、缺失可信 marker 的 fail-closed、恢复重建以及非法外部 conversation ID。
待 PR #352 合入，需要用其真实 `ActiveChildThreads` 与 Artifact 编辑路由联合测试，
才可以把本项由“部分/依赖 PR #352”提升为完整等价；此前不声称写保护端到端验收。

### 2026-11-12 — child terminal publication / stale lease CI hardening

PR #354 的多平台 CI（`334e111d`）暴露一个真实可观察的竞态：`_execute`
先提交 `subagent_tasks.status='completed'`，随后才在 `finally` 调用
PR #352 的 `ActiveChildThreads.settle`。另一个 Controller 或测试观察者可能
见到已完成的 task，却仍看到 child 活跃。这一顺序已更正：成功、失败、取消和
过期的每个终态发布路径，在释放任务终态之前先通过 PR #352 原始 API 持久化
保护标记；不在持有同一 SQLite 写锁时重入该 API。若两个提交之间崩溃，task
仍为 running，而 child 标记已只读，重试可以安全再调用幂等 `settle`。

修复同时涵盖失去执行租约后旧 Controller 继续 `GenerationStore.finish` 的风险：
子 generation 只允许在同一租约成功提交任务终态后才完成；父调用请求取消期间
不应把晚到的模型结果改写为成功。新测试覆盖原子可观察顺序、迟到租约接管、
取消与正常结束。此外，跨平台 Job 测试夹具 `_wait_job` 原先把过渡态
`retrying` 当成终态，导致 macOS 的 `exit_code=None` 偶发失败；现只在
取得实际退出码后返回，生产 Job/Shell 实现保持不变。

### 2026-11-12 — 长租约远程重连的持续恢复

对照原版 `packages/api/src/agents/subagentThreads.ts` 租约续期以及
`triggers/README.md` 的 idle recovery 语义，Controller 启动时的一次性
`lease_until` 计时器不足以恢复续过租的子任务：其他正常 Controller 在第一次
租约到期前续期会阻止认领，后续掉线则使任务永久遗留 `running`。

`recover_subagent_tasks` 现在针对尚由远端持有的任务维护有界、可取消的
SQLite 租约 watcher：不抢占有效租约、不重写任务身份，重复启动不会增加同一任务
的 watcher，远端续租后继续读取真实 `lease_until`，真正超时才调用现有
`_ensure_active` 按 CAS 认领，并在本机恢复 `AgentRunner` 后退出 watcher。
`shutdown_subagent_tasks` 会取消和收拢 watcher，避免泄漏异步任务。
回归测试模拟远端第一次续租后才停止续约，验证不提前接管、最终正确恢复结果。
这属于子任务租约恢复，不等于原版所有 Agent Trigger 的自动 completion
wakeup/外部队列/跨 Controller 事件协议已经移植；后者仍单列为未完成。

### 2026-11-12 — Windows CI 调度时间容限

当前 CI Windows x86_64 Python 3.12 曾在高负载下因两个测试中固定的
2 秒/4 秒短等待而偶发失败：`test_job_mutation_recovery` 在拦截
`start_shell` 前尚未得到调度，`test_webui_subagent_task_host_edges` 的
异步 Child Generation 尚未完成。测试等待窗口改为有上界的 15 秒和
20 秒，继续验证真实启动/终态、所有权及 `exit_code`，失败时显示受限状态。
没有放宽任何生产操作 timeout 或权限检查。

### 2026-11-13 — 持久 Subagent Completion Wakeup（原版 source 部分移植）

源码锁定：`packages/api/src/agents/subagentDelivery.ts`、
`subagentCompletionWakeup.ts`、`subagentThreads.ts`、
`api/server/services/Endpoints/agents/subagentThreadStore.js` 和
`packages/api/src/agents/triggers/README.md`。SHA-256 和逐符号对应见
`UPSTREAM_LOCK.json`、`PORTING_INVENTORY.json`；`@librechat/agents@4.0.1`
的工具 Schema 保持原版 JS 真实类差分不变。

`webui/subagent_wakeup.py` 使用统一 SQLite 中的 `subagent_wakeups` 作为
可信内部 `AgentContinueTriggerEnvelope` 队列，**在子 task intent 的同一个
BEGIN IMMEDIATE 事务中预登记**，且只有原 owner + parent Agent + run +
responseMessageId 绑定允许派发。源码默认启用，管理员可用
`settings.backgroundTasks.completionWakeups=false` 关闭。宿主工具返回
源码 `SUBAGENT_WAKEUP_GUIDANCE`，禁止无意义地反复 poll。

子结果落地后仅在父 generation 完成时启动续接：先验证可信父 Agent 和
原 reply，选当前 branch 中最新 assistant descendant（含兄弟 completion
链），保留有上界的宿主 orchestration snapshot；调用现有
`GenerationStore.begin`（受约束的 internal `_connection`）与子任务
`result_claimed=1` **同一 SQLite 原子提交**。并发手动 poll 在该事务前
领取时会撤销 wakeup；自动续接抢先时 poll 显示 `delivery_scheduled`。
授权过期、父 generation 失败、Agent 删除或分支不匹配均安全拒绝，
不执行模型。已经被派发的 generation 由原 `generation_routes._start_task`
执行：保留原 MCP/Ask User 设置和不可提升的旧授权，复用 Provider、
AgentRunner/StateGraph、generation SSE 和持久事件，不新建模型调度器。

任务 crash 后以稳定 task ID 和原有 generation run ID 重接，不重复创建
模型会话；`recover_orphans` 跳过尚有有效 wakeup 归属的根 generation，
lease 延续/抢占由 SQLite 控制；失效后释放自动 claim 供人工领取。
后续仍需补齐全局原版 Agent Trigger 的外部事件、死信重排、重试退避、
富媒体 artifact delivery 和所有 Controller 之间对根生成 actor 的 HA
强拥有权与恢复语义，不能把本次局部可信内部触发说成整个 JS Trigger
子系统的 100% 等价移植。

测试拆为 `test_webui_subagent_wakeup.py`、`_guard.py`、`_recovery.py`，
共 32 个真实 SQLite E2E/异常/并发/恢复测试，包括一例真实 Parent AgentRunner
调用 + SSE on_run_step 与最终 responseMessage 持久化；共享 fixture 在
`tests/wakeup_helpers.py`，原版 source-locked UI CI 增加了全部三个文件。

### 2026-11-13 — 对接已合入 main 的 PR #353 持久原生 Job

PR #353 新增 `agent_durable_tasks` 和按 `(owner,conversation_id,run_id)`
验证的不可冒用原生 Job/Shell 持久所有权。其 `run_id` 必须属于所记录的
实际 conversation；原版 Subagent 继承机器权限的 context 却属于父 conversation。
本合并保留两条**不可混淆的可信维度**：
`AgentRunner.generation.conversation_id` 负责 native Job 持久拥有权、
`AgentRunner.authorization_conversation_id` 负责每个机器操作的权限检查。
`lsm_tool_registry.call_tool` 在内部接收原授权 scope，传给
`durable_tasks.reserve` 时同时记录独立 `authorization_conversation_id`，
PR #353 的 `_revoked` 使用该可信 parent scope 检查权限变更，同时先验证
child conversation 原拥有权及 child run 的显式取消。旧版本只有 PR #353
表时使用同步 `PRAGMA table_info` + `BEGIN IMMEDIATE` 安全迁移新增字段，
默认 NULL 维持现有根任务兼容性；不复制/重写任何 Job/Shell/Worker RPC。

`tests/test_webui_graph_durable_bridge.py` 真实 SQLite 验证：child run 可以
创建受父会话 machine policy 约束的原生 Job intent；子会话单独的 `none`
权限不被冒用作为授权；父会话撤权触发 `mark_revoked` 的 durable cancel，
并测试对 PR #353 旧数据库的原地升级。源码锁定的 Graph/Ask User
测试不因此修改原版 `@librechat/agents@4.0.1` 工具参数 schema。

### 2026-11-13 — 嵌套 Background Subagent 可信续接边界与内部幂等键

完整跨平台回归发现在根会话内托管的中间 Subagent，其 `parent_run_id`
实际属于隐藏 child conversation。它是可信且合法的嵌套 task，却没有根会话
的 assistant `responseMessageId` 分支可以用于自动续接。
`register_wakeup` 现在通过 owner、实际 child run 和仍在运行的
`subagent_tasks.child_run_id` 证实此嵌套关系，并仅关闭缺少准确目标分支的
**嵌套自动续接**；child 仍正常执行、保存 thread、轮询/控制/领取结果。
绝不把隐藏 child 的完成通知伪装为根 conversation 的新模型轮次。
真实 `test_webui_subagent_task_nested.py` 验证根 child 获得一个 wakeup，
嵌套 child 则不登记错误的第二个 wakeup。

普通 HTTP 请求可见 task ID，但不能占用服务器生成的
`clientRequestId=subagent:<opaque>` 或
`clientRequestId=subagent-wakeup:<opaque>`。`GenerationStore.begin`
将这两种命名空间只开放给可信内部 child conversation 分配或原子 SQLite
wakeup 连接；浏览器直接提交立即拒绝，防止内部续接幂等性被用户预占。
`test_webui_generations.py` 覆盖无写入副作用的拒绝路径。

### 2026-11-13 — 完成续接消息的 child transcript 归属与并发竞争回归

原版 `createSubagentCompletionWakeupResolver` 在尝试将 child 结果注入根父
conversation 前校验源 child conversation 的存在和归属。Python
`process_wakeups` 现使用实际 `(child_run_id, child_conversation_id, owner)`
查询已提交的 child，并验证已存档 metadata 的 `subagentTask` 与
`parentConversationId`；child 被删除、元数据格式不合法或归属信息不匹配
时仅撤销自动事件，保留人工可领取的终态，不会把孤儿内容注入父 Agent。
child run 尚在 `running/requires_action` 时等待持久终态，不用抢先注入消息。

新增真实 SQLite 并发回归：手工 `check_background_task` 与自动
`process_wakeups` 同时竞争同一终态，原子领取唯一获胜者；两条兄弟 child
完成时先派发一个续接，第二条排队到第一个 parent assistant message
写入，再挂接到其最新 descendant 分支。还补齐了删除 child、伪造元数据、
非法 JSON 和终态持久化前的 fail-closed 行为。固定源码后单独测试
`subagent_wakeup.py` 分支覆盖率为 **93.9%**（38 测试通过）。

## 2026-11-12 人工交互移植增量

源码、HTTP/SSE、SQLite恢复、原React浏览器验证与未完成范围详见 HUMAN_INTERACTION_PORT.md。新增原版 Ask User 显式审批优先级、原 resumeState 与 sync、同一决策崩溃恢复。仍未验收完整 steer/arm/cancel、actor 和多 Agent 并行子图调度；状态标记为部分。

### 2026-11-14 — Source Agent Trigger Retry/Dead Letter 与父续接租约隔离

对照锁定源码 `packages/api/src/agents/triggers/engine.ts` 中
`DEFAULT_MAX_ATTEMPTS=8`、`DEFAULT_RETRY_BASE_MS=1000`、
`DEFAULT_RETRY_CAP_MS=300000`、`retryAt`，在内部 Subagent 完成事件队列
增加持久 attempt、可领取截止时刻、错误类型和有界 failure history，
迁移旧 SQLite 表时保留已提交任务。调度器派发失败时按原版半区间随机
指数退避，同一个 task ID 重放**原有根 generation**，不重复创建对话。
每次认领使用新的高熵租约令牌（包括同进程重试）；旧持有者无权结算失败。
达到 8 次上限后落持久死信，释放 child 的自动结果占用供人工领取；
`get_dead_wakeups` 和 `requeue_dead_wakeup` 是可信、owner-scoped 的内部接口，
未引入未经授权的公开路由/Agent 工具。手动 requeue 位于新队列尾部，
增加持久 requeue ordinal 与新的 generation 幂等 key，避免采用旧失败轮次。

跨 Controller 根 generation 在真实 `AgentRunner._check_grant`、
Graph 子节点、模型 token/SSE 回调及最终完成写入之前检查 SQLite
`(owner,run_id,task_id,lease_owner,lease_until)`。本地 worker 活跃期间
按 token CAS 续租；租约被其他 Controller 领取后，旧 actor 不能继续写
消息、tool、checkpoint 或结算回执，新的 actor 从旧 generation checkpoint
恢复。测试采用真实模型流中途劫持 lease 的 E2E；另有 8 次退避、死信重排、
过期授权、旧版本 SQLite 原地升级，以及冒用旧 token 失败的定向回归。

这实现的是**内部 Subagent continuation** 的 bounded retry 和 actor fencing。
原版通用 fire/steer/batch webhook、绑定/密钥管理、多租户队列、批处理及
全局 Agent Trigger 调度仍是独立后续移植项，不据此声称完全一致。

### 2026-11-14 — JS source waitingRetryAfter 差分和跨进程 Ready 通知

新增 SHA-256 完全相同的上游原版 `triggers/backoff.ts` TypeScript fixture，
CI 用 Bun 直接执行原始 `waitingRetryAfter`，验证 Python
`waiting_retry_seconds` 在 5s/60s 限界、按等待年龄 10% 回退及
Math.ceil 浮点临界点上的逐例完全一致。源码锁与执行器 SHA-256 记录在
`UPSTREAM_LOCK.json`；同页新增 `triggers/engine.ts` 的重试/租约映射。

未满足 readiness 的 parent/child 在统一 SQLite 中设置
`next_attempt_at`，不增加失败 attempt。为避免错过跨 Controller 通知，
在父 `runs.status` 终态和子 `subagent_tasks.status` 终态的**同一个 SQLite
写入事务**中使用数据库 trigger 清空该截止时间；即使负责原任务的
Controller 已经退出，另一 Controller 的 poll 也会立即发现可领取事件。
旧数据库从 `CREATE TRIGGER IF NOT EXISTS` 安全迁移，测试覆盖进行中 child
和等待中 parent 两种情况的自动唤醒、超过五秒但无需等待实际 timeout 的路径。

本次仅提供内部 Subagent 完成事件的有界重试、死信及安全自动续接。
其它 Agent Trigger 类型尚未引入未经授权的公共 HTTP 入口。

### 2026-11-14 — 原版 Agent Trigger Remote Source、Fire 与受保护的绑定 Continue

锁定 `triggers/{ingress,bindings,envelope,delivery,engine}.ts` 和
`agents/json.ts` 原版 SHA-256。按原版 `POST /api/agents/v1/events`、
`GET /api/agents/v1/events/:deliveryId`、
`POST /api/agents/v1/events/bindings` 接入现有 Starlette 路由。
原 LibreChat 使用 Remote Agents API Key，LSM 以 OAuth
`admin:config` 受控管理的独立、可撤销 event-source bearer key
（`/api/agents/v1/event-source-keys`，只返回一次明文）承载对应身份；
控制器 OAuth、UI cookie、普通 MCP key **不能**冒充远程事件源。
事件 `source`、`principal`、`receivedAt` 在可信中间件重建；强制单个
`Idempotency-Key`，禁止多值 headers/非法字符，单包限制 1MiB，
事件结果查询只返回来源可见的状态、有限错误类型及受限结果标识。

`webui/event_triggers.py` 以独立 SQLite `agent_event_source_keys`、
`agent_event_bindings`、`agent_event_deliveries` 表实现 `trigger_` SHA256
原版投递键、内容指纹冲突、默认和显式 lane（SQLite seq 按入队先后）、
重试限制、令牌 fenced 的跨 Controller 恢复与 source key 即时撤权。
`fire` 使用原有 `GenerationStore.begin` + `AgentRunner` + SSE；入队与
生成记录原子提交，重启/调度失败不会分配第二个根 generation。
远程 API Key 不继承机器控制权限、MCP 工具或无人批准的 HITL 操作。
所有 HTTP 普通 Chat 接口拒绝 clientRequestId=`trigger_*` 预占内部事件。

`continue` 严格要求 API-key 所属直接子 Agent 绑定，服务器完全覆盖调用者
提供的 conversation/agent/branch；原始 `Constants.NO_PARENT` 首轮
和最新真实 assistant 后续分支分别由 Controller 指定。绑定须先由
PR #352 `ActiveChildThreads.activate` 在子会话公开前登记只读保护，
**在 PR #352 尚未合入时安全返回 503**，绝不创建未保护的子会话。
不可用时仍可使用 `fire`；其它 Agent 的 Draft PR 不会被本 PR 自动合入。

新的 SHA-256 字节完全一致的 `triggers/envelope.ts` 与依赖
`agents/json.ts` fixture 由 Bun **直接执行**；与 Python 逐例核对
fire/continue/steer 投递 identity、CJK 字符和可信 source 字段。
另外覆盖完整 ASGI Key 生命周期、授权撤销即时杀死 leased actor、
多 Controller 抢占和同一 run 恢复、顺序 lane 排他/跨 lane 并发、
真实模型 SSE、8 次失败/死信以及含伪造目标的绑定 API。

仍需后续独立实现/合入原版 `steer`（由 Draft #358 承接 Graph/HITL）、
expectedAction host-observed 证据、750ms/8 项 coalescing、全局多来源
Trigger 管理。当前 unsupported modes 和 contracts **拒绝入队**，
没有假装完成或将不可信请求直接送到 Subagent completion 队列。


## Artifacts model generation, original previews, active-thread edit fence (incremental)

Pinned source: LibreChat 0.8.8 `e8f3be08623663d4ad7f7241e693c94469b63bb0`.
This section supplements the existing Artifacts editor/source-vector port above;
it does not replace that implementation.

| Behavior | Pinned source | Python/React path | State / evidence |
| --- | --- | --- | --- |
| Prompt selection and Agent capability | `packages/api/src/prompts/artifacts/index.ts` and `packages/api/src/agents/initialize.ts` | `webui/artifact_prompts.py`, `generation_routes.py`, `generations.py` | Done for default/shadcnui/custom mode and openai/anthropic/google selectors. Original JS `generateArtifactsPrompt` and nested `generateShadcnPrompt` output compared byte-for-byte across 15 provider-mode combinations. |
| Source-locked Shadcn component docs | `packages/api/src/prompts/artifacts/components.ts` and `generate.ts` | `artifact_prompt_snapshot.json` and `scripts/export-librechat-artifact-prompts.py` | Done, 47 source records -> 33 effective keys after object spreads; SHA-256 of pinned source stored; source-locked build-time extraction, no Node at runtime. |
| Agent / child / handoff system injection | `packages/api/src/agents/initialize.ts`; `@librechat/agents` 4.0.1 runtime | `generation_routes._start_task`, `subagents.invoke_subagent`, `agent_runner.AgentRunner` | Done for existing supported Python graph paths. Ephemeral mode saved in SQLite run state for resume; no mutation of saved Agent instructions. Tests check real run-loop, immutable idempotent mode snapshot, incremental stream events, persistence, edit and next model-turn read; a separate Ask User / HTTP resume test proves the restored checkpoint contains exactly one original Shadcn system prompt. |
| Artifact output delta / final history | `api/server/controllers/agents/callbacks.js`; `api/app/clients/prompts/formatMessages.js` | Existing `GenerationStore.append/finish/history` and retained `ArtifactRow` | Text Artifact format passes through unchanged; streamed partial text, full final structured text and saved edits are retained. Generated multi-artifact cards verified in original Chromium; no parallel rich/tool payload protocol introduced. |
| Child thread read-only from registration through settlement | `packages/api/src/agents/guard.ts`; `api/server/services/Endpoints/agents/subagentThreadStore.js` | `webui/child_thread_activity.py`; `artifact_routes._update`; shared SQLite `active_subagent_threads` | Owner-scoped child registry checked inside the same SQLite write transaction as edit, before static metadata and reserved UUID checks. Trusted `activate` verifies owner/active parent run and forbids parent thread; `settle` verifies run ownership while retaining permanent read-only identity. A deleted parent generation cannot unlock its child. The **full graph task owner must wire its actual child creation/settlement paths** to these calls before runtime-wide active thread parity can be claimed. |
| Preview MIME routing | `client/src/utils/artifacts.ts`, `client/src/components/Artifacts/ArtifactPreview.tsx` | Original retained React preview and Monaco components | HTML, React, Mermaid, SVG (including `image/svg` alias), Markdown, synthetic DOCX/spreadsheet/presentation previews and source-only code bucket now exercised in real Chromium. Office controls expose preview-only tabs; code exposes source-only. Downloaded bytes/filenames tested for model-supplied preview HTML and code. The source-mapped Python Office **binary-to-static-escaped-HTML conversion** is now tested using the original LibreChat `.docx` fixture; the real browser opens the final SQLite-persisted card, and downloads **exact original ZIP/DOCX bytes**, not the derived HTML. Full original CDN-based high-fidelity visual rendering is still out of scope. No custom editor/preview replacement. |
| Canonical file-backed Artifact download and metadata | `packages/data-provider/src/data-service.ts:getFileDownload`; `api/server/routes/files/files.js:getDownloadFileMetadata` | `webui/attachments.py:download_react_file`; original `useArtifactDownload` and `useAttachmentLink` | The retained frontend requests `GET /api/files/download/:userId/:file_id`; the old Python implementation only exposed `/:file_id` and could not serve original-file panel downloads. Both routes now resolve through the same owner-scoped SQLite record with authenticated principal/path-owner match, content-disposition, original `application/octet-stream` bytes and URL-encoded **allowlisted** `X-File-Metadata` (no owner, text, physical path). Wrong-owner/missing records get 404; the legacy single-ID route still works. Real Chromium plus SQLite test proves original DOCX archive survives the view/download path without substituting cached HTML. Static HTML production from actual Office binary input now works through `publish_office_tool_output` for authorized native local file writes; async content extraction/agent resource/remote tool callbacks remain shared integration work. |
| Trusted native tool-produced Office files | `api/server/controllers/agents/callbacks.js:on_tool_end`; `packages/api/src/files/documents/html.ts:bufferToOfficeHtml`; `zipSafety.ts` | `agent_runner.AgentRunner._completed` + `webui/office_preview.py` + `GenerationStore.finish` | Completed for **authorized local `file_write`** Office outputs (.docx, .xlsx, .xls, .ods, .csv, .pptx, .potx). The existing LSM native file-write must succeed and return matching filename/bytes/SHA-256; no model-provided path is opened. Source bytes are published through the existing `publish_attachment` with SQLite run owner/status validation and an atomic original `attachment` SSE. Retry of the same call+content reuses the first file without a second event; `GenerationStore.finish` attaches it to final message/SQLite metadata for refresh. Invalid preview formats retain downloadable raw bytes with `failed` status. Six pinned LibreChat office binaries, actual original-model `file_write` dispatch and real Chromium DOCX→HTML→download pass. Tool UI events omit large base64, native args/checkpoint remain untouched. Remote files, arbitrary shell outputs, MCP image/UI resources and Graph-child tool callbacks **not ported here**. |
| Safe Office HTML fallback | `packages/api/src/files/documents/html.ts` and `zipSafety.ts` | `webui/office_preview.py` | Escaped static HTML, 512KiB output cap; actual ZIP inflation 25MiB per entry / 100MiB total, DTD/ENTITY refusal, max 5,000 rows / 500 slides / 256 cols. Original XLS BIFF via `xlrd>=2.0.2,<3` (pure Python); other parsers stdlib. No required Node or LibreOffice runtime. The original CDN-based high-fidelity DOCX/PPTX renderers are deliberately not claimed; current output is semantic/text-and-table preview only. |
| Offline and CSP limits | Original `@codesandbox/sandpack-react` `SandpackProvider` and preview components | Retained frontend assets | Chromium with all non-loopback requests blocked confirmed `*.sandpack-static-server.codesandbox.io/__csb_relay/` for static HTML/SVG/Markdown and `2-19-8-sandpack.codesandbox.io/` for React. Monaco editor offline **does not imply offline Sandpack runtime**; blocked-network test only asserts the shell/cards, not that external previews rendered. Mermaid panel did not require an iframe in this test. |
| Tool-produced artifacts, filtering | `api/server/controllers/agents/callbacks.js`, `packages/api/src/mcp/parsers.ts`, original host content-filter helpers | Existing tool event/attachment and message protocol paths | **Not complete**: upstream callback's file-backed artifact attachment events, `files` mapping, content-filter host policy, image/UI resource projections and full rich/tool history await their owners' shared message-protocol/attachment implementations. No duplicate payload representation was created. |

Evidence commands (independent worktree):

```sh
PYTHONPATH="$PWD/src" python -m pytest -q tests/test_webui_artifact_prompts.py tests/test_webui_artifact_routes.py tests/test_webui_artifacts_source.py
PYTHONPATH="$PWD/src" python -m pytest -q tests/test_webui_artifact_browser.py tests/test_webui_artifact_preview_browser.py tests/test_webui_artifact_file_download_browser.py tests/test_webui_attachments.py tests/test_webui_office_preview.py tests/test_webui_office_runtime.py
# Source-differential oracle only; Node and npm dedent are BUILD/TEST dependencies,
# not needed by the Python+SQLite controller:
node scripts/check-librechat-artifact-prompt-diff.cjs /path/to/pinned-LibreChat /path/to/dedent-1.7.0
```

Original editor's retry/invalid input/owner boundaries still apply. New tests additionally
cover active and settled child mutation denial (including deleted parent run),
partial Artifact cancellation, multiple independent Artifacts and repeated editing,
and two competing edits with the same original source (one 200, the stale second 400).
The focused source/editor/preview suite passed 49 tests before the additional
original-file download E2E, with 98.3% branch coverage across the four
Artifacts-specific Python modules. The previous full isolated suite passed 2346
cases and 95.33% global branch coverage; the added download route is being
re-checked in CI (do not infer a new full-suite pass from the earlier run). No remaining behavior is
represented as fully source-equivalent merely because an identically named
frontend feature appears. The new Office preview's separate source-differential
format fixtures and security tests are in `tests/test_webui_office_preview.py`,
native runtime/owner/idempotency tests in `tests/test_webui_office_runtime.py`, and
native-file-write-to-React replay in `test_webui_artifact_file_download_browser.py`.

### 2026-11-14 — 合并 source Graph/HITL #358、Artifacts #352、Remote Event Steer/Batch/ExpectedAction

已将最新 `origin/main`、原版 Graph/HITL/Steer 集成 PR #358 和源 Artifacts/Office
PR #352 合入 PR #354 的独立 worktree（仅代码分支；不操作另两个 PR）。
Graph 代次 ownership 与 SQLite actor lease、审批中断、原版 SSE/RunStepState、
Tool Approval/Ask User 和真正的 Artifacts child 活动只读标记同时生效。
外部 Event Actor 可以严格使用 *已完成* 的父 Agent assistant reply 预登记
`ActiveChildThreads.reserve_for_completed_parent`，并保留永久不可编辑的子会话
保护；不能把已完成父 generation 当作当前运行中的普通 Subagent。

`triggers/host.ts` 的 `steer` 复用既有 `SteeringStore.enqueue`，一次性
`clientSteerId=trigger_*` 与原本 SSE 事件；在**同一 SQLite 事务**中复核
事件源密钥、owner、lease 和 generation CreatedAt，旧 Controller 被撤权后
不得再修改 steering FIFO。即便入队完成后程序崩溃，重试也复用原
Steer receipt 而非二次注入。

`triggers/batch.ts` observational bound-child `continue` 支持 opt-in
`coalesce.key`、750ms 聚合窗口、8 项最大批次与 512KiB 上限，
按源 occurredAt、接收时间、事件 ID、delivery key 稳定排序，
组装真实 `kind:librechat.agent_event_batch` JSON 输入，成员 receipt 由
root terminal 同步结算；无绑定/expectedAction/steer 不能合并。

`triggers/expectedAction.ts` 用 byte-pinned 原 TS `matchesExpectedAction`
Bun 差分覆盖完整工具名、`_mcp_` 前缀、JSON 参数解析和递归 subset
匹配。任务终态只能根据本机宿主保存的
`on_run_step_completed.data.result.tool_call` 证据确认动作是否发生；
仅模型文字、失败工具结果、错误参数与无效生成不作为成功证据。暂停的人审
必须等持久审批完成后再判断。

尚需进一步处理 source `background.ts` 普通工具后台化、事件源完整的
Detached Action 证据持久重传、复杂跨机 Coalescing 操作回执与剩余
源 Graph RunStepState 边缘消息类型。本节不代表这几项已经全部完成。

### PR #354 — Graph、普通工具后台化与 Detached Action 终态续接补齐（2026-11-16）

本节为当前三个明确缺口的源码对照和验证界限；不表示其余 LibreChat 全模块都已移植。

1. `packages/api/src/agents/background.ts`：可配置原生工具 `run_in_background` 参数、原
   LSM tool registry + machine ACL + OAuth scope 审计执行、同会话 10 并发/同 owner 40 并发、
   单次可认领 SQLite 结果，`check_background_task` 与 Subagent 任务统一入口、
   跨进程取消意图及租约检测。进程重启后的不可确认工具结果为 `uncertain`，绝不自动重跑
   可能已发生副作用的调用。原版对非对象工具/内置控制/文件/图像/MCP request-scoped
   资源排除；已通过真实 AgentRunner→native call_tool→任务认领/取消的回归。
2. `packages/api/src/agents/triggers/detachedAction.ts`：一个绑定 `continue` 投递最多拥有
   一个匹配 `expectedAction` 的后台工具，在同一 SQLite 事务登记工具与行动证据；
   `mark_running`、原始宿主终态证据（结果/错误按源长度上限）、进程失联的
   `launch_indeterminate`、恢复后完整验证、原式一次性内部
   `librechat.event_actor.detached_completion` 续接投递均已接通。工具启动回执、
   模型声称与 `ok:false` 都不能冒充成功；取消/撤销来源后不能生成续接。原始
   `detachedAction.ts` 纯解析函数使用 Bun 直接转译锁定源码片段差分测试，
   UTF-16 字符串长度、JSON 安全整数、字段边界逐一验证。
3. `@librechat/agents Graph.ts`、`api/server/controllers/agents/callbacks.js`、
   `packages/data-provider/src/runSteps.ts`：Graph 原版 `entryAgentId`、`resultAgentId`、
   `graphAgentIds`、`maxHandoffs` 被 Agent SQLite 配置正确保留；串行隐含输出不会
   再进入最终回复或 live SSE；图成员工具调用持久化 `on_run_step`、
   `on_run_step_completed` 和原版 `on_run_step_closed`（终态、可信时间戳与持续时长），
   刷新后可按 stepId 恢复。外部事件来源的执行租约沿所有 LangGraph 节点
   传递；路由提示仅添加一次。真实 Graph + 独立 SQL 读取的 SSE/历史测试覆盖。

所有源文件 SHA-256 保存在 `UPSTREAM_LOCK.json`。相关新测试已并入 CI 选择清单。


#### Source graph Actor 分支覆盖核验

源 Graph/HITL 审批和断点恢复进一步覆盖：批准、拒绝、后台禁止人工交互、
Ask User 批次限制、LangGraph 交接、可信 checkpoint 重放、过期 Agent、
审批批次续接、Steer 去重、子任务控制的提交和确认。
Artifacts 完成态父会话注册及 Detached Action 的原子 CAS 重试、撤权、未知
启动结果另有针对性测试。项目要求全量覆盖率≥95%、逐模块≥90%，
使用同一个完整测试样本加增量源分支样本验证；CI 再次独立复核。

## Provider 消息历史与 MCP 富媒体迁移（PR #343 后续独立分支）

| 固定原版源码 | Python/SQLite 的唯一消息表示 | 范围、证据及保留差异 |
| --- | --- | --- |
| LibreChat `e8f3be08`: `api/app/clients/prompts/formatMessages.js` (`formatMessage`/`formatAgentMessages`) | `webui/message_dto.py` + `webui/generations.py:history` | 原版真实JS源码、`@langchain/core@1.2.8`导出5组差分向量，对应测试逐条一致。分轮/并行工具锚点、ID、签名、steer、图文顺序保留。继续兼容旧无完整调用结果的message（不能事后恢复已丢失的原始结果）。 |
| LibreChat `e8f3be08`: `packages/api/src/mcp/parsers.ts` | `webui/mcp_content.py` | 使用原TS源码和固定的TypeScript 5.9.3导出13组text/image/resource/blob/ui/unknown provider差分向量；原生MCP结果外壳保留在SQLite/checkpoint。`mcp_result_envelope`按LSM嵌套MCP结果形状解包。 |
| agents `c4ffb9b1`: `src/messages/core.ts` / `utils/truncation.ts` | `webui/mcp_projection.py` + `webui/agent_runner.py` | 保持400000字符*仅模型输入投影*阈值；React预览独立截断；SQLite保存完整原始工具输出，并在历史回放每次工具批次处重新投影富媒体。原JS的projection/provenance深层属性保留策略与provider Responses API原生映射尚非逐字段全等。 |
| agents `4.0.1` + `@langchain/anthropic@1.5.2`、`@langchain/google-genai@2.2.0`、`@langchain/openai@1.5.x` | `webui/provider_tool_protocols.py` + `webui/providers.py` / `webui/agent_runtime.py` | OpenAI-compatible、Anthropic、Gemini合法wire结构；并行工具调用、SSE增量工具参数与错误、image block和Gemini `thoughtSignature`。三套真实本地HTTP/SSE mock provider均完成file_read→tool result→继续生成→SQLite重开→下一轮历史回放；**未使用真实厂商凭据、未作厂商验收**。 |
| 保留原版React `runSteps`/SSE和LSM注册工具 | `webui/generation_routes.py` / `webui/lsm_tool_registry.py` | 新增`runs.state.modelSteps`原序列，`messages.content`继续供React调用卡片显示；独立worktree无生产部署。Worker无新增Node依赖。完整LangGraph graph/Command/人工交互由其余独立分支移植，不在本分支重复定义DTO。 |

差分向量生成（仅测试工具；无需Node作为运行时）：

```sh
node scripts/export-librechat-message-vectors.cjs /path/to/librechat-e8f3be08 /path/to/npm-deps-core-1.2.8
node scripts/export-librechat-mcp-vectors.cjs /path/to/librechat-e8f3be08 /path/to/npm-deps-typescript-5.9.3
PYTHONPATH="$PWD/src" pytest -q tests/test_webui_message_parity.py tests/test_webui_provider_http_e2e.py
```

LSM消息DTO为`{role, content, tool_calls?, tool_call_id?, name?, reasoning?, artifact?, raw_result?, is_error?, provider_data?}`；graph runtime应直接读写这套表示。原生工具依旧使用原有LSM注册表、权限、审计和执行器。Provider输出时转换为厂商wire形状并剔除本地私有字段；不得将UI预览当成历史真相。

## Attachment lifecycle, reference ownership and resource processing (Python/SQLite)

Reference revisions: LibreChat `e8f3be08623663d4ad7f7241e693c94469b63bb0`
(`api/server/routes/files/files.js`, `api/server/services/Files/process.js`,
`packages/api/src/files/deletion.ts`, `api/app/clients/prompts/formatMessages.js`),
and `@librechat/agents@4.0.1` (`c4ffb9b1b78421bf63eba3e56993017f922387f3`).

| Original behavior / API | Python port | Status and intentional differences |
| --- | --- | --- |
| `POST /api/files`, `POST /api/files/images`, native Controller upload | `webui/attachments.py:upload_react_file`, `publish_attachment`, `upload_attachment` | Owner-scoped Controller-local storage; `O_EXCL`, inode/size/SHA fingerprint, file and directory sync, SQLite upload intent; no external staging bridge |
| `GET /api/files`, `GET /api/files/agent/:agent_id`, download | `webui/attachments.py:list_react_files`, `agent_files`, `download_react_file` | Authenticated owner-scoped DTOs; download bytes remain private; paths provided to the *model* only through authorized context/history |
| `DELETE /api/files`, `buildDeleteFilesResponse`, `partitionAgentResourceFiles` | `webui/attachments.py:delete_react_files`, `webui/file_deletion.py` | Response and partition order ported; source fixture executes Node for differential parity; no Mongo transaction or Node runtime |
| `deleteAgentResourceFiles`, last-owner reference, global owner deletion | `AttachmentDeletionStore._prepare`, `_finish`, `_remove_references` | **Stronger local guarantee**: `BEGIN IMMEDIATE` covers the final reference check, unlink, filesystem isolation, metadata and all-Agent reference cleanup; other Agent writers share SQLite writer serialization |
| Native file and resource binding | `AgentRepository.add_resource_file(...,db=db)` | Binding and physical metadata publish atomically in one SQLite transaction |
| `processAgentFileUpload` context extraction | `extract_context_text`, `agent_context_messages` | UTF-8 text, optional PDF text and DOCX extraction, 128 KiB budget; extracted text is injected as untrusted user-level source material, not privileged instructions |
| `processAgentFileUpload` OCR, configured RAG, `file_search`, `execute_code`, `image_edit` | N/A | **Not ported**. Explicit 501 for unsupported permanent resource uploads. Native file tools remain LSM's existing authorized tool registry; raw upload is **not** represented as OCR, vector embedding or code environment provisioning |
| Provider-native image/audio/video handling | Existing provider and generation components | Not complete: byte upload and Controller path are available, but provider media transformations, speech-to-text and image embeddings are not claimed |

**Deletion and crash ordering:** persist `attachment_deletions` (`prepared`) → re-read
current metadata and Agent references under SQLite `BEGIN IMMEDIATE` → rename blob
to a same-directory quarantine and `fsync` its directory → delete metadata,
clean Agent references and mark intent `committed` in the *same* SQLite commit →
delete quarantine and release intent. A process-wide RLock is insufficient: the
implementation uses the existing cross-process `.local-shell-mcp/locks` flock /
Windows file lock plus SQLite's single writer transaction. Interrupted precommit
operations restore bytes using atomic hardlink-with-EXCL (no overwrite of an
external reconstruction). Postcommit quarantine is removed. Collision or
missing evidence retains intent and bytes for inspection. Competing writes may
bind another Agent *between* prepared and final checks; the final check detects
that and commits only a detach. This is verified with real spawned processes.

**Upload ordering:** persist `attachment_uploads` intent → exclusive creation,
record inode and fsync parent → stream, flush and fsync bytes → persist hash and
size → extract optional text → commit attachment row, resource association and
intent removal atomically. Lost commit acknowledgement is handled by SQLite
readback: published bytes must not be deleted. Recovery waits one hour to avoid
collecting a concurrently active upload, and cleans only provably uncommitted
files that still match inode, size and SHA-256. Unknown identity, external
replacement or inaccessible DB retains the intent and file. State and content
stay under the same `.local-shell-mcp/` root. Existing records are not migrated
by destructive deletion.

**Validation:** Python route/upload/delete, restart, fault injection (including
uncertain postcommit acknowledgement and external inode reconstruction),
cross-process competing reference writers/deleters, and Node fixture differential.
The original React UI components and preexisting LSM file execution tools are
unchanged; no duplicate file execution implementation is introduced.

**Remaining parity blockers:** full configured OCR (incl. scanned PDFs), RAG
extraction/chunking/vector storage and cleanup, execute_code/image_edit
deployment and secondary-storage deletion, provider-native image/audio payload
conversion, all project-specific retention semantics and true remote-machine
resource provisioning. These are not silently downgraded to raw upload.

### Canonical tool-generated file attachments and deferred preview

Source: LibreChat `e8f3be08623663d4ad7f7241e693c94469b63bb0`
`api/server/controllers/agents/callbacks.js:createToolEndCallback`,
`writeAttachment`, `writeAttachmentUpdate`, `buildResponsesAttachment`,
`packages/data-provider/src/types/files.ts:TFilePreview`, original
`client/src/hooks/SSE/useAttachmentHandler.ts` and
`client/src/hooks/Files/useAttachmentPreviewSync.ts`.

- `webui/tool_attachments.py` now maps *already-published and owned*
  Controller files (not paths or remote code environment file IDs) to actual
  Agent tool-call identities. Linking requires the caller's active run,
  persisted matching `on_run_step` and matching file owner; insertion and
  replayable `{"event":"attachment","data":...}` happen in a single SQLite
  transaction. `webui/agent_runner.py:_completed` consumes only explicit
  native structured `artifact.files[].file_id` metadata from the existing LSM
  tool executor, refusing guessed ownership and reusing its original file
  execution logic.
- The existing React file DTO is used directly, extended with canonical
  `messageId` (assistant response ID), `toolCallId`, `conversationId`;
  subsequent status updates reuse the **same file_id**. The original React
  listener upserts by file identity and tool-call scope. There is no parallel
  artifact payload or separate file execution engine.
- `tool_attachment_links` uses SQLite foreign keys with delete cascade, and
  `webui/generations.py:finish` saves assistant attachments in the final
  message. `webui/storage.py:WorkspaceRepository.messages` overlays the
  current owner-filtered link records on reload. Deleted links never reappear
  through a historical message snapshot; attachment-only assistant turns
  persist even when the text is empty.
- `update_attachment_preview` persists `pending/ready/failed` and emits
  repeat `attachment` events while the run is live. After completion, a
  canonical file record updates persisted message metadata. Authenticated,
  owner-scoped `GET /api/files/{file_id}/preview` implements the retained
  React polling contract; it returns no-store JSON and 404 after deletion.
  Untrusted arbitrary HTML remains **unsupported** (the original sanitizing
  office renderer is not ported); previews accept bounded text only.
- Last-Agent-reference deletion also checks user message file descriptors and
  canonical tool attachment links in the same `BEGIN IMMEDIATE` transaction.
  Concurrent message creation and tool linking both participate in SQLite
  writer serialization. Owner-requested global deletion still removes the file
  and all links. Removed conversation history may leave an unreferenced blob
  until explicit owner cleanup; a full retention/TTL sweeper is still blocked.

### Non-destructive Windows upload identity upgrade

Earlier PR drafts recorded `st_dev` / `st_ino` as SQLite `INTEGER`; Windows
can report unsigned NTFS file IDs greater than signed 64-bit. Fresh databases
use TEXT and all existing databases are additively migrated with a dedicated
`file_identity TEXT` column. New upload intents write a decimal device/inode
pair into the TEXT field; recovery accepts exact legacy INTEGER identities
only when SQLite retained them without REAL precision loss. Unknown and
rounded legacy values are retained, never deleted based on a guess.
A regression starts from a legacy INTEGER schema and verifies original data
survives and new uploads publish correctly.

The original React file-chip removal button, its deferred DELETE mutation,
real Chromium upload, SQLite byte deletion and reload were all exercised;
this does not claim remote machine file staging or full media conversion.
PDF and DOCX optional text parsers were run against real generated documents,
with 64-page PDF and 128-KiB extraction limits. Scanned pages still require
OCR; file_search vector extraction and execution-session file downloads still
require their dedicated upstream-style processors.

**Tool-completion crash boundary:** the native LSM tool result remains the
single execution result. When it contains explicit published Controller
`artifact.files[].file_id` references, `GenerationStore.append_tool_completion`
commits the `on_run_step_completed` record, `tool_attachment_links`, and
original `attachment` SSE events within **one** `BEGIN IMMEDIATE`
transaction. A failed file-link SQL write rolls back the completion and all
links; a lost acknowledgement may be retried by the immutable run-step ID
without duplicating events. A mutated replay is rejected. Foreign/remote
unpublished file IDs are skipped and do not falsely materialize files.
This covers the tool completion-to-file link window. Graph checkpoint and
external code-environment file download/recovery remain separate projects.


## LibreChat Actions 独立移植（Draft PR #349）

固定上游 `e8f3be08623663d4ad7f7241e693c94469b63bb0`，npm Agent SDK
`4.0.1` / `c4ffb9b1b78421bf63eba3e56993017f922387f3`。对应文件 SHA-256
已写入 `UPSTREAM_LOCK.json`；`scripts/generate-actions-oracle.cjs` 直接运行原版
TypeScript 模块，导出解析器、工具定义与域名验证的原版结果。生成结果封存于
`tests/fixtures/librechat/actions_source_oracle.json`，并在 Python CI 中逐项比较。

- **Action存储与API（部分）**：`webui/actions.py`、`webui/action_routes.py`、
  SQLite `action_records`。原 `GET /api/agents/actions`、`POST /api/agents/actions/:agent_id`、
  `DELETE /api/agents/actions/:agent_id/:action_id` 格式保持；POST响应为
  `[updatedAgent, updatedAction]`。支持创建、枚举、修改、删除、多操作工具绑定、
  版本记录和SQLite重启恢复。Agent `actions` 引用与 `tools` 字符串使用原版规则；
  所有读取/写入都校验用户和Agent所有权，同域不同operationId不互相删除。
- **模型schema和实际执行（部分）**：`webui/action_spec.py`、
  `webui/action_runtime.py`、`webui/agent_runner.py`。调用仍进入已有工具审批、
  已选工具检查和Agent授权路径；Action仅执行指定OpenAPI HTTP接口，
  不创建第二套LSM文件、命令或嵌套MCP执行器。原工具名和标准化形态保持一致。
- **安全（已测的范围）**：`api_key/oauth_client_id/oauth_client_secret`与普通metadata
  分离，使用Fernet加密的SQLite blob和仅属主可读的
  `.local-shell-mcp/actions-fernet.key`。敏感字段不进入Model schema、普通Action GET、
  Agent配置、历史版本；响应回显密钥也会脱敏。原React的两处凭据调试日志已移除。
  防SSRF：限制HTTP/HTTPS及同域、验证DNS全部返回地址、公网IP默认允许、
  内网需操作员显式白名单、实际请求连接固定经检验的IP；不跟随HTTP跳转、不使用
  环境代理；HTTPS保留SNI/校验证书；响应上限256KiB，HTTP超时20秒，
  async CancelledError向上传播。`LSM_ACTION_ALLOWED_DOMAINS`可选限制目标域，
  `LSM_ACTION_ALLOWED_ADDRESSES`仅管理员环境白名单（`host:port`，不可由模型设置）。
- **原版Actions OAuth2授权**：`webui/action_oauth.py`、`webui/action_routes.py`、
  `webui/action_runtime.py`及`agent_runner.py`，对应上游
  `api/server/routes/actions.js`（`bind`/`callback`）、`ActionService.js`（登录提示、
  令牌复用和刷新）、`packages/api/src/oauth/tokens.ts`（code exchange/refresh）和
  React `ToolCall.tsx`。使用外部提供的HTTPS访问地址
  `LOCAL_SHELL_MCP_PUBLIC_BASE_URL`构建`/api/actions/:action_id/oauth/callback`；
  无公网域名时允许回环地址的HTTP（仅本地开发）。保留原版React消耗的
  `on_run_step_delta`工具调用auth URL、过期时间及登录完成清空事件。
  `/api/actions/:action_id/oauth/bind`要求原LSM已认证身份及同源POST，
  设置HttpOnly/Secure/SameSite=Lax、按Action区分且与owner绑定的CSRF cookie；
  callback是唯一豁免Bearer认证的Action路由，严格要求10分钟内一次性state、
  CSRF cookie、Action归属及版本吻合。专用`action_oauth_flows`状态表只保存state
  的SHA-256摘要；原React需要重放的授权URL（包含原始state）仍须存在受限的
  Generation SSE历史，不能把SSE事件表称为完全不含state；
  access/refresh token与API Key分离，使用Fernet加密存入SQLite，
  支持到期刷新及同进程同Action并发刷新去重，不会转为匿名执行；
  真实token交换使用HTTPS+DNS/IP固定、完整证书校验、不跟随跳转、禁用代理和32KiB上限。
  OAuth首次等待已改为SQLite `requires_action` 持久检查点：模型的待执行工具调用
  和React登录SSE delta同时保存，Controller关闭或重启时不会继续占用协程；
  OAuth成功/失败结果页必须位于React `AuthContextProvider`路由之外：原外层
  AuthLayout会在未带聊天登录态的IdP回调弹窗上重定向到`/login`，尽管Python
  前端资源路径已匿名放行。现对真实`LOCAL_SHELL_MCP_AUTH_MODE=oauth`使用
  无WebUI会话的Chromium浏览器验证，两页不发生该跳转。
  OAuth回调具备有效的WebUI登录会话时，先重新核验机器权限并自动启动原图工具节点；
  否则由原聊天页的Bearer授权`resume`/`status`/`stream`重新附着，
  成功页通过同源BroadcastChannel仅传递公开的Action ID，原标签页自行鉴权。
  Tool Approval已通过时若OAuth尚未授权，Agent先保留已审批的SQLite
  `approvedToolBatch`、暂停工具执行并展示OAuth登录；登录后沿原审批和检查点路径继续，
  拒绝的工具不会发起登录也不会执行；在同批存在多个OAuth调用时先顺序授权，
  确认所有必需令牌后才发送外部请求。
  已授权的Action在调用HTTP前持久记录`dispatching`，完成后将结果持久写入图
  checkpoint及事件；Controller异常重启时，仅在未发送HTTP或已确认结果落盘的
  情况下继续原图。对于可能产生副作用且HTTP已启动但结果未知的调用，
  采用fail-closed中断，**不自动重试可能重复的外部请求**。
  10分钟授权state到期后可在已认证状态查询中原子更新SSE链接，旧state作废；
  多个并发请求只会发起一次新的授权。撤销WebUI/机器授权后不可借助callback的
  OAuth CSRF cookie提升执行权限；生成已主动取消或被新状态取代时，回调会在
  一次性state消费前拒绝其令牌交换，也不会自动恢复外部请求。
  **边界**：生产第三方IdP人工授权尚无真实凭据可验收（测试使用受控模拟IdP）；
  需由部署者提供可用外部HTTPS域名及OAuth提供方的客户端配置。
  无法区分HTTP发送后崩溃是否已在外部生效，因而不会假称所有副作用可exactly-once。
- **测试**：`tests/test_webui_actions.py`、`test_webui_actions_edges.py`、
  `test_webui_actions_source_oracle.py`，分别覆盖原React API契约、真实本地
  HTTP服务的成功/错误/取消/超时、多工具、重启和跨owner隔离；
  存储和执行的异常/安全分支；原版TypeScript执行所得的10组OpenAPI schema/
  10组工具名/10组域校验共31个差分断言。测试依赖Node仅在重新生成oracle时需要，
  生产服务及Worker运行时不引入Node/Mongo。
  工作区运行命令：`PYTHONPATH="$PWD/src" python -m pytest -q tests/test_webui_actions*.py`。
  `tests/test_webui_action_oauth.py`还覆盖CSRF绑定、state一次性消费、过期、
  Owner隔离、令牌加密及刷新、HTTPS IP pinning/禁止代理/错误体，
  `test_webui_agent_runner.py`覆盖原始模型调用→OAuth授权提示→HTTP callback→
  真实本地Action服务→模型恢复的完整链路；`test_webui_action_oauth_recovery.py`
  验证SQLite重开、原检查点续跑、Auth cookie与机器权限撤销、重复发送保护、
  HTTP结果落盘后崩溃以及过期链接并发轮换。`test_webui_action_oauth_browser.py`
  使用真实Chromium检查OAuth结果页和跨同源标签的恢复通知。
  新OAuth模块本地分支覆盖率96%+；
  Actions各模块覆盖率须≥90%，全仓总覆盖率须由最新CI验收。
