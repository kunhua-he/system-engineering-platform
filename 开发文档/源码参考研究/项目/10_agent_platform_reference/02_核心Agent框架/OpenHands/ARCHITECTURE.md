# OpenHands Agent Canvas 深度架构审计

> 审计对象：`/Users/hekunhua/Documents/Agent/github 源码参考/10_agent_platform_reference/02_核心Agent框架/OpenHands`
>
> 审计基线：提交 `6dcc9f5`（`refactor: finish the microagent→skill rename in the frontend (#16672)`）。本次只读取源码、配置、测试、README、`docs/`、根 `AGENTS.md` 和既有 `细探-OpenHands.md`，只修改本文件；没有删除或改写既有细探。
>
> 重要边界：这个仓库不是经典 Python Agent 引擎，也不是 Agent Server。它是 `@openhands/agent-canvas` React/TypeScript 前端和本地栈启动器。真正的 Agent loop、工具执行、事件持久化服务、runtime provider、workspace 实现和 LLM provider 由 `@openhands/typescript-client` 对接的外部 Agent Server / `openhands-sdk` 运行时提供。本报告只把本仓库能证明的事实写成已实现；外部能力统一标为“未在本仓库可证”。

## 0. 证据等级

本报告使用以下证据等级，避免把 README 或类型声明冒充运行时事实：

| 等级 | 含义 | 本仓库中的典型证据 |
|---|---|---|
| L0 | 目录、包元数据、静态配置或明确仓库边界 | `package.json`、`config/defaults.json`、根 `AGENTS.md` |
| L1 | 可直接阅读的实现路径和符号 | `src/contexts/conversation-websocket-context.tsx::ConversationWebSocketProvider` |
| L2 | 单元/组件测试验证的行为 | `__tests__/hooks/use-websocket.test.ts`、`src/api/*/*.test.ts` |
| L3 | 真实 Agent Server 或真实运行时的端到端测试 | `tests/e2e/live/real-agent-server-conversation.spec.ts` |
| L4 | 生产/跨平台/外部 provider 的运行证据 | 本仓库当前没有可复核的 L4 证据；`docs/TESTING_MATRIX.md` 明确列出未覆盖项 |

结论中的“已实现”通常至少有 L1；“已验证”会明确给出 L2/L3；只有说明或外部包的能力不会升级为本仓库实现。

## 1. 一句话定位与系统边界

Agent Canvas 是一个多后端控制平面：浏览器通过 typed client、Cloud proxy 和 WebSocket 创建/恢复会话、发送用户消息、读取事件和运行时文件/终端结果，并渲染聊天、终端、文件、浏览器、设置、MCP、Skills、Plugins 和 Automation UI。它可以启动一个本地三服务栈，但本地启动器只是进程编排，不是 Agent 执行引擎。

### 1.1 本仓库拥有的职责

- React Router 页面、布局、Provider、Zustand/React Query 状态。
- Local/Cloud backend registry、会话路由、会话元数据和认证 UI。
- 对话创建/发送/暂停/恢复/删除/分支的客户端适配。
- REST 事件历史、WebSocket 实时事件、去重、排序和 UI 投影。
- runtime host 上的终端、文件、VS Code、Git、MCP、Skills、Profiles 等 API 适配。
- 本地 `uvx` Agent Server/Automation/Vite/Ingress 的启动、代理、状态目录和进程清理。
- Mock-LLM、Live Agent Server、Docker E2E 的测试编排。

### 1.2 明确不拥有的职责

- Agent 的 system prompt、ReAct/goal loop、上下文构造、condenser 内部算法。
- Agent 对工具调用的决策、工具 schema 执行、bash 子进程、文件编辑、浏览器驱动。
- 事件账本的服务端写入、事件父子链、恢复语义和服务端幂等保证。
- Docker/VM/cloud sandbox 的创建、回收、资源配额和崩溃恢复。
- OpenAI/Anthropic/其他 provider 的真实 LLM 请求、重试、计费和 provider 状态。
- Agent Server、Cloud App API、Cloud runtime、Automation Server 的 endpoint 实现。

证据：根 `AGENTS.md:24-41` 把这些职责分别归属 `software-agent-sdk`、`typescript-client` 和 `extensions`；`README.md:124-135` 也把 Agent Server 描述为外部 REST backend；`package.json:22-72` 只有客户端依赖，没有 Python engine 源码。

## 2. 真实部署拓扑

### 2.1 本地/npm 开发栈

```text
Browser
  │
  ▼
Ingress :8000  (scripts/ingress.mjs 或 static-server.mjs)
  ├── /*                         → static/Vite Agent Canvas
  ├── /api/*, /sockets           → Agent Server :18000
  └── /api/automation/*          → Automation :18001

Agent Server / uvx / Docker
  ├── external openhands-agent-server / openhands-sdk
  ├── external tools/workspace/runtime/provider
  └── persisted ~/.openhands state
```

L0: `config/defaults.json:19-35` 固定默认端口、状态目录和外部包名；`README.md:63-104` 明确无 sandbox 直接访问主机文件系统，Docker 通过 `PROJECTS_PATH` 挂载目录。L1: `scripts/dev-with-automation.mjs` 负责 spawn 多服务和 Ingress；`docker/entrypoint.sh:180-220` 负责容器内 Agent Server、Automation 和存储目录。

### 2.2 Cloud 会话

```text
Browser Canvas
  │ REST app API / cloud proxy
  ▼
Cloud App API ── asynchronous start task ──► Cloud conversation
                                             │
                                             ├── conversation_url
                                             ├── session_api_key
                                             └── per-conversation runtime sandbox
                                                   │ REST/WebSocket
                                                   ▼
                                             external Agent Server runtime
```

L1: `src/api/conversation-service/agent-server-conversation-service.api.ts::createConversation` 在 Cloud 发送扁平 `AppConversationStartRequest`，由 `useTaskPolling` 等待；`src/api/event-service/event-service.api.ts::searchEvents` 把历史放在 Cloud App API，把 live count/confirmation 放到 runtime host；`src/api/runtime-service/agent-server-runtime-service.ts::executeCommand` 通过 `callCloudProxy` 访问 runtime，避免 CORS。Cloud sandbox 的实际 provisioning、容器/VM 生命周期和恢复不可在本仓库证明。

## 3. 分层（L0-L4）

### L0：启动、配置和封装

- `bin/agent-canvas.mjs`：npm CLI，解析 `--public`、`--frontend-only`、`--backend-only`、端口和版本信息。
- `scripts/dev-safe.mjs`：最小 Agent Server + Vite。
- `scripts/dev-with-automation.mjs`：Agent Server、Automation、Ingress、Vite/static 的完整编排。
- `scripts/static-server.mjs`、`scripts/ingress.mjs`：静态服务、路由代理、`/server_info.runtime_services` 注入。
- `docker/entrypoint.sh`、`docker/Dockerfile`：容器内进程和持久化目录。
- `config/defaults.json`：Agent Server `1.42.1`、Automation `1.7.1`、最低兼容 Agent Server `1.28.0`、端口、包名和路径。

### L1：应用宿主和服务适配

- `src/entry.client.tsx`、`src/root.tsx`、`src/routes.ts`：hydrate、MSW、认证/后端 gate、路由。
- `src/api/agent-server-client-options.ts`：统一 typed-client host/session key/timeout 选项。
- `src/api/backend-registry/`：backend、active selection、健康、认证和最后会话。
- `src/api/conversation-service/`：会话 wire normalize、创建、消息、历史相关适配。
- `src/api/cloud/`：Cloud App API、proxy、Cloud conversation/profile/settings/git/sandbox/secrets。
- `src/api/runtime-service/agent-server-runtime-service.ts`：runtime command/file seam。
- `src/stores/`、`src/hooks/query/`、`src/hooks/mutation/`：前端投影和缓存，不是服务端状态机。

### L2：事件/交互/工具结果 UI

- `src/types/agent-server/core/`：Agent Server event union 类型和 type guards。
- `src/contexts/conversation-websocket-context.tsx`：历史门控、socket handlers、side effects、消息发送。
- `src/stores/use-event-store.ts`：原始事件与 UI 事件的全局内存账本。
- `src/hooks/use-bash-command-runner.ts`：独立 bash-events WebSocket 的请求关联。
- `src/services/child-conversation-launch.ts`：client-defined `launch_child_conversation` 动作桥。

### L3：真实服务端集成测试

- `tests/e2e/live/real-agent-server-conversation.spec.ts`：真实 LLM + Agent Server + terminal tool + events API + UI。
- `tests/e2e/mock-llm/`：生产形态 Agent Canvas 栈 + 外部 SDK `TestLLM`，覆盖 OpenHands trajectory、ACP、Automation、文件和认证。
- `__tests__/`、`src/**/*.test.ts(x)`：服务适配和 UI/状态单元测试。

### L4：当前不可证内容

本仓库没有 `runtime/`、`agent/`、`event/`、`server/`、sandbox provider 或 LLM provider 的实现目录。下列问题必须去 `OpenHands/software-agent-sdk`、Cloud 服务或对应 provider 仓库审计，不能从 Canvas 类型和 E2E 结果推断：Agent loop 的循环不变量、工具实际执行权限、服务端事件 append/commit 顺序、容器隔离、runtime 回收、LLM 重试/计费、跨进程崩溃恢复和服务端幂等。

## 4. 会话创建、恢复、分支和状态

### 4.1 Local 创建

`AgentServerConversationService.createConversation`（`src/api/conversation-service/agent-server-conversation-service.api.ts:390-513`）执行：

1. 读取 settings/profile，生成 UUID。
2. 将默认相对目录解析为绝对目录（`resolveAbsoluteAgentServerPath`），避免上传路径落到错误根目录。
3. 无显式 workspace 时默认 `new_worktree`，有显式 workspace 时默认 `local_repo`。
4. 通过 `buildStartConversationRequestWithEncryptedSettings` 发送加密 settings、初始消息、parent、plugins、`worktree`。
5. 以 `CREATE_CONVERSATION_TIMEOUT_MS = 5min` 创建；Local 返回 `READY`，不做 task polling。
6. repo/branch/workspace/profile 等 UI 元数据写入 `conversation-metadata-store`，因为 Agent Server runtime 不负责这些 Canvas badge 元数据。

这证明了客户端启动 payload 和 workspace mode，不证明服务端如何创建 worktree、如何启动 Agent loop 或如何持久化事件。

### 4.2 Cloud 创建和 reconnect

Cloud 创建返回 `task-*` 或 working task；`useTaskPolling` 负责等待 `app_conversation_id`、sandbox 状态和 runtime URL。Cloud send path（同文件 `:344-387`）若缺 `conversation_url`/`session_api_key` 会重新 batch-get；随后请求 runtime `/api/conversations/{id}/events`。

`src/contexts/websocket-provider-wrapper.tsx` 在 Cloud sandbox `PAUSED` 时不给 WebSocket provider 传旧 runtime URL，防止恢复前连接旧 sandbox。`useResumeConversation` 只调用统一 resume mutation 并 invalidate queries；真正 sandbox resume/restart 不在本仓库。

### 4.3 Fork/branch

`useForkConversation`（`src/hooks/mutation/use-fork-conversation.ts:22-75`）先用 `getEventParentId` 支持 edit-message 分支，再调用 `forkConversation`。Local only；`from_event_id` 决定复制到哪个事件。客户端兼容旧 Agent Server：低于 `1.31.0` 可能复制整条会话，因此只有返回 `leaf_event_id` 与预期一致时才把消息视为已排除。Cloud 分支明确抛出“不支持”。

### 4.4 Child conversation

`src/services/child-conversation-launch.ts` 是一个真实的客户端工具动作桥：

- `validateLaunchParams` 校验 target、task、repository/branch/isolation 的交叉约束。
- local child 继承父 workspace；`worktree` 失败或 scratch workspace 无 commit 时降级 `shared`，并在结果中报告冲突风险（`:253-323`）。
- Cloud child 自己 provision isolated sandbox，默认继承父 repo，但 local parent id 不发送给 Cloud，因此 `parent_link=false`（`:386-448`）。
- Cloud start 轮询 3 秒、总上限 180 秒；超时返回仍在 provisioning 的 task，而不是无限等待（`:357-384`）。

## 5. 事件账本与 Agent loop 边界

### 5.1 前端事件账本

`src/stores/use-event-store.ts` 的 `EventState` 是全局单会话内存投影，不是数据库账本：

- `events` 保存 raw `OpenHandsEvent`，`uiEvents` 保存 `handleEventForUI` 投影。
- `eventIds: Set<string|number>` 做 O(1) id 去重。
- `addEvents` 对 REST history 和 older pagination 批量去重后按 ISO timestamp 排序。
- `addEvent` 只在相邻同 sender 的 streaming delta 上合并；无 id 的事件不能被 id 去重。
- `loadedConversationId` 与 clear 操作原子更新，避免切换会话时半清空状态。

### 5.2 REST + WebSocket 双账本接缝

`ConversationWebSocketProvider`（`src/contexts/conversation-websocket-context.tsx:253-381`）先取 REST history，等 refetch settle 后以最新事件 timestamp 构造 `resend_mode=since&after_timestamp=...`。空历史或 history 错误时使用 `resend_mode=all`，依赖 event id 去重弥合 REST/WS race。旧事件由 `useLoadOlderEvents` 分页，不是一次性全载入。

planning 子会话是不同实现：使用 `resend_all=true`，先通过 `EventService.getEventCount` 取得 expected count，再以收到帧数判断 history loading（同文件 `:958-1011`）。这不是严格的事件游标协议；服务端发送丢帧、重复帧或 count 与 stream 不一致时，本仓库没有额外一致性校验。

### 5.3 replay 副作用保护

主/规划 WS handler 在 `addEvent` 前读取 `eventIds`；重复事件仍进入 store（被忽略），但跳过非幂等副作用（错误 banner、terminal append、browser state、cache invalidation、child launch 等）（`:517-530`、`:740-755`）。这是重要的客户端 replay 防护，但不等于服务端工具执行幂等：网络重试、服务端重放、浏览器 localStorage 失败的语义仍由外部 runtime 决定。

### 5.4 Agent loop

本仓库只观察 loop 的边界：用户消息通过 WS `{...message, run:true}` 发送；socket 不可用时通过 `ConversationClient.sendEvent(..., {run:true})` 排队（`:1046-1097`）；事件 union 能渲染 action/message/observation/state/error/streaming/condensation/pause。Agent 如何从 LLM response 选择 tool、执行工具、追加 observation、继续/暂停/结束 loop，没有源码证据，等级为 L4 未在本仓库可证。

## 6. WebSocket、会话重连与消息可靠性

### 6.1 Conversation WebSocket

`src/hooks/use-websocket.ts`：

- `onopen` 先发送 `session_api_key`，再调用上层 `onOpen`。
- 使用 `WeakSet<WebSocket>` 标记允许重连的具体实例，unmount/显式 disconnect 会先删除实例再 close。
- 默认 3 秒重连，`maxAttempts` 默认为无限；成功后重置 attempt count。
- cleanup 清理 timeout、禁止 reconnect、close 当前 socket。

L2：`__tests__/hooks/use-websocket.test.ts` 验证连接、只保留最新 raw frame、错误、query params、auth frame 顺序；文件头明确部分广播/close 测试因 MSW 跨测试污染被 skip，属于测试缺口而非可靠性证明。

### 6.2 消息发送 fallback

WS open 时直接 send；否则 REST queue。这个 fallback 只说明请求已提交给服务端，不说明 Agent 已经执行。由于 fallback 和 WS 发送之间可能发生 race，前端依赖服务端事件 id 和 optimistic user message text matching；服务端是否去重相同用户消息在本仓库不可证。

### 6.3 Bash WebSocket

`src/hooks/use-bash-command-runner.ts` 使用 `/sockets/bash-events`：请求先进入 waiting/pending FIFO，收到 `BashCommand` echo 后绑定 server `command_id`，再按 command id 聚合 stdout/stderr，收到非空 `exit_code` resolve。关闭/error/unmount 会 reject 所有 waiting/pending/active command，且明确没有自动重连和 command replay。长命令断线后不会自动续跑，调用方只能收到失败。

### 6.4 Cloud runtime host 和认证

Cloud App API 用 bearer；runtime REST/WS 用 conversation `session_api_key`，浏览器 REST 通过 `/api/cloud-proxy` server-side hop。`src/utils/websocket-url.ts` 只构造 `ws/wss` host/path；auth frame 在 `use-websocket.ts` 和 bash runner 的 `onopen` 发送。反向代理必须转发 Upgrade/Connection，`docs/SELF_HOSTING.md:226-230` 给出 nginx 配置；本仓库没有生产 ingress/nginx 的 L4 运行证明。

## 7. 工具调用、终端和文件

### 7.1 工具调用是服务端事件，本仓库是观察者/动作桥

`src/types/agent-server/core/events/` 定义 action/observation/message 等 wire 类型；Canvas 根据 type guards 渲染结果或触发有限的 client-side action。`tools/canvas_ui_tool.py` 只是为旧持久化 metadata 保持可导入的兼容 shim（`docker/entrypoint.sh:163-165` 设置 `OH_EXTRA_PYTHON_PATH`），不是完整工具实现。

### 7.2 Terminal

- Agent 产生的 `ExecuteBashActionEvent`/`ExecuteBashObservationEvent` 在 conversation WS 中被投影到 terminal store（`conversation-websocket-context.tsx:619-632`）。
- UI/automation 需要执行命令时走 `AgentServerRuntimeService.executeCommand`，Local 使用 typed `RemoteWorkspace.executeCommand`，Cloud 使用 runtime proxy `/api/bash/execute_bash_command`，timeout 默认 30 秒且 proxy timeout 为 command timeout + 10 秒（`src/api/runtime-service/agent-server-runtime-service.ts:24-67`）。
- 独立 `useBashCommandRunner` 通过 bash-events socket 获取逐块输出；它不实现 shell、超时 kill 或 process cleanup，这些属于外部 Agent Server/runtime。

### 7.3 文件和路径安全

`AgentServerConversationService.readConversationFile` 对 Cloud 和 Local 都要求路径位于 workspace 内；`requirePathInsideDirectory` 规范化 `.`/`..`，越界抛错（`:200-231`、`:616-637`）。这是 Canvas 侧路径守卫，不是 sandbox 级别隔离，也不能替代服务端文件 API 的鉴权。

### 7.4 Tool action 幂等

`handleLaunchChildConversationAction` 用 `localStorage[openhands-child-conversation-launches:<parent>]` 记录 `toolCallId`，在网络工作前 claim，防止 replay 启动第二个、可能计费的 Cloud child（`child-conversation-launch.ts:196-227`）。但 storage corrupt/full/unavailable 时代码选择放行并接受 replay risk；记录没有 TTL/上限/跨 tab 原子 compare-and-set。因此这是 best-effort UI 幂等，不是可靠账本。`canvas_ui` 类 action 的具体幂等逻辑在 `src/services/canvas-ui.ts`，而服务端工具/LLM tool call 幂等未在本仓库可证。

## 8. Workspace、worktree、sandbox 和 cloud runtime

### 8.1 Local workspace

`createConversation` 使用绝对 `working_dir`，`workspaceMode` 映射到 `worktree: true/false`。`WorkspacesService`（`src/api/workspaces-service/workspaces-service.api.ts`）只通过 typed `WorkspacesClient` 读写服务端保存的 workspace list；注释说明实际持久化为 `workspace/.openhands/workspaces.json`，但文件系统读写实现属于外部 Agent Server。

### 8.2 Worktree 分支策略

local child 默认 `new_worktree`；如果父会话没有 selected repository/explicit workspace，认为 scratch repo 没有 commit，预先降级 shared。即使有 metadata，真正 `git worktree add` 失败也降级 shared，并把“两个 agent 可能冲突”报告给用户。该策略避免 launch 全失败，但牺牲隔离；shared fallback 是明确的风险而不是隐藏的兼容层。

### 8.3 Container/local sandbox

README 的无 sandbox 模式明确 Agent Server 直接运行在安装主机并拥有完整 filesystem/network；Docker 模式只把 `$PROJECTS_PATH` 挂载到 `/projects`，并把 `~/.openhands` 持久化。Canvas 没有 sandbox policy、seccomp、容器生命周期或 workspace mount 实现。Docker image 的 entrypoint 仅启动外部 server/backend，不能证明工具进程被隔离。

### 8.4 Cloud sandbox

Cloud 的 `conversation_url`、`sandbox_status`、`session_api_key` 是客户端路由信息。暂停时阻止连接旧 host；resume 后等待查询刷新。sandbox provisioning、pause/resume/terminate、闲置回收、磁盘/CPU/网络 quota、宿主崩溃后的任务恢复，全部 L4 未在本仓库可证。

## 9. LLM/provider、ACP 和 model switch

- `SettingsService`/Profiles API 传递 LLM profile 和 encrypted secret 引用；Canvas 不 materialize provider secret。
- Local `switchProfile` 获取加密 profile，调用 `ConversationClient.switchLLM`，生成新的 `usage_id` 并保持 `stream:true`（`agent-server-conversation-service.api.ts:815-881`）。Cloud 只把 profile name 发送到 App API，由服务端解析 profile。
- ACP 只在 Canvas 保存 `agent_kind=acp`、server/command/args/model 并渲染 ACP events；真实 subprocess、stdio JSON-RPC、`session/set_model` 和 provider CLI 在外部 Agent Server/ACP runtime。
- `tests/e2e/mock-llm/scripts/mock-llm-server.py` 使用外部 `openhands-sdk` `TestLLM`；`mock-acp-server.py` 使用外部 `acp` library。这些是测试 provider，不是本仓库 provider 实现。

L2/L3 能证明 profile 配置、mock trajectory 和一条真实工具调用路径；不能证明 provider 重试、流式 token 顺序、预算计费、rate limit、上下文压缩或 provider 崩溃恢复。

## 10. 取消、暂停、超时、崩溃恢复

### 已在本仓库实现

- 对话暂停 mutation 调 `pauseConversation`，成功后同步 patch `execution_status` 和 `sandbox_status` 为 `PAUSED`，立即避免旧 runtime WS 连接（`use-unified-stop-conversation.ts:52-70`）。
- Cloud child poll 上限 180 秒；create conversation client timeout 5 分钟；bash command proxy timeout 为 command timeout + 10 秒。
- WebSocket cleanup 清理 retry timer 并禁止旧实例重连；bash socket close/error/unmount reject 所有 pending promises。
- dev launcher 使用 detached process group；`scripts/dev-process-utils.mjs::signalProcessTree` 在 POSIX 对负 pid 发信号，Windows 用 `taskkill /t /f`。`createShutdownHookRegistry` 汇总退出钩子。
- Docker entrypoint `cleanup` kill 子 PID、wait 后退出；Playwright mock config 用 `gracefulShutdown: SIGTERM`，避免直接 SIGKILL 留下 detached 子进程。

### 未在本仓库证明

- pause/stop 是否取消 Agent loop、杀掉 bash/browser 子进程、释放容器和 runtime。
- command timeout 是否真的 kill 子进程，超时后的 stdout/事件是否最终一致。
- Agent Server/Cloud 崩溃后 conversation 是否可恢复、事件是否 exactly-once/at-least-once。
- 进程重启后的 active tool、LLM stream、租约、volume、network 和临时文件回收。
- server-side cancellation 与 client-side WebSocket close 的竞态处理。

## 11. 资源清理与幂等审计

| 对象 | Canvas 侧事实 | 结论 |
|---|---|---|
| Conversation UI socket | unmount/URL change 关闭 socket，清 timer | L1 已实现；服务端连接回收 L4 |
| Bash promises | close/error/unmount 全部 reject 并清 map/queue | L1 已实现；远端命令 kill L4 |
| Agent child launch | toolCallId localStorage claim，失败时接受 replay risk | L1 best-effort，不是可靠幂等 |
| Conversation delete | 删除远端会话后移除本地 metadata | L1；runtime/container/files 清理 L4 |
| Test conversations | Live afterEach/afterAll 删除并失败即报错；mock suite 部分 best-effort | L2/L3；强杀后残留需外部审计 |
| Dev services | POSIX process group / Windows taskkill；Docker entrypoint 直接 kill PID | L1；异常崩溃/孤儿进程的 L4 证据不足 |
| Automation workspace/DB | config/entrypoint 创建目录，E2E 每次清理 `.tmp` 和 automation DB | L1/L2；生产 retention/GC L4 |
| Event store | id 去重、排序、conversation switch 原子清空 | L1；不持久化，不是 server ledger |

## 12. 测试证据与缺口

### 12.1 有效覆盖

- `__tests__/hooks/use-websocket.test.ts`：连接、auth 首帧、query params、错误和 raw message 不无界增长；同时显式记录 MSW broadcast 跨测试污染导致的 skipped tests。
- `__tests__/build-websocket-url.test.ts`：HTTP/HTTPS、外部 runtime host、端口、fallback 和特殊 conversation id。
- `src/api/event-service/event-service.api.test.ts`、`src/api/agent-server-adapter.test.ts`：history/runtime 适配和 wire normalize。
- `tests/e2e/mock-llm/conversations/mock-llm-conversation.spec.ts`：完整 Canvas → Agent Server → mock LLM trajectory，验证 terminal observation、事件 API、worktree payload 和离开后 resume。
- `tests/e2e/live/real-agent-server-conversation.spec.ts`：真实 LLM、真实 Agent Server、终端工具、events API 和 UI；测试后删除 conversation/profile。
- `playwright.mock-llm.config.ts:128-166`：隔离 state/automation DB、随机 session key、full stack readiness probe、SIGTERM graceful shutdown。

### 12.2 明确缺口（L4）

`docs/TESTING_MATRIX.md:88-97` 明确 CI 尚未覆盖真实 ACP credentials、macOS、public auth、subscription login、Windows；表格中的许多 OS/Agent smoke cell 仍为未勾选。当前也没有本仓库可复核的：

- Agent loop 单步/多步/goal cancellation/condensation 的服务端测试。
- 断线发生在 tool 已执行但 observation 未到达时的恢复测试。
- WS replay、REST/WS 并发写入、时间戳相同/乱序/无 id 事件的一致性测试。
- localStorage 写满、跨 tab 同一 toolCall claim、重复 child launch 的竞态测试。
- Docker/VM/cloud runtime 崩溃、sandbox 回收、workspace mount 泄漏和进程树残留测试。
- provider rate-limit、stream reset、成本/预算边界和 LLM retry 语义测试。

## 13. 审计结论

1. **Canvas 的前端事件处理是“至少一次接收 + id 去重 + 副作用去重”的投影层，不是事件账本。** REST history + `since` WS 是合理的接缝，但 planning 的 count-based `resend_all` 和无 timestamp/id 的事件仍有一致性边界。
2. **会话分支语义是非对称的。** Local 支持 event fork 和 worktree/shared fallback；Cloud child 可启动独立 sandbox，但不保持 local parent link；Cloud conversation fork 明确未支持。
3. **工具动作只有部分幂等。** replayed event 在 handler 层被挡住，child launch 还有 localStorage ledger；ledger 不可用时主动放行，服务端工具幂等未证明。
4. **runtime 与 sandbox 的关键安全边界在外部。** 无 sandbox 运行模式拥有主机 filesystem/network；Docker 只提供挂载和进程包装；本仓库没有能力证明隔离、quota、回收或崩溃恢复。
5. **取消/超时主要是客户端 transport 和 UI 状态语义。** socket 会关、promise 会 reject、poll 会停止，但 Agent loop、子进程、容器和 provider 请求是否停止必须审计外部 SDK/server。
6. **测试最强证据是 L2/L3 的前端到真实/模拟 Agent Server 路径，不是 L4 生产运行证据。** 既有 `细探-OpenHands.md` 的 manifest/automation 结论仍有效，但不能替代本报告对 runtime、event、server、sandbox、workspace、tools 和 provider 的边界审计。

## 14. 后续应在外部仓库核验的最小清单

如果要完成真正的后端架构审计，应在 `OpenHands/software-agent-sdk` 单独建立证据链，至少读取并测试：

- Agent loop/goal runner、condenser、pause/resume/cancel 和 tool-call dispatch。
- Event store append、parent_id、timestamp/id 分配、REST search、WS resend cursor 和 crash replay。
- `openhands-tools` 的 bash/file/browser/MCP 实现及其 subprocess timeout/kill。
- `openhands-workspace` 的 local/container/remote provider、git worktree、mount 和 cleanup。
- Agent Server REST/WebSocket handlers、conversation persistence、server restart 和 idempotency。
- LLM/provider adapter、stream retry、budget/usage accounting、ACP subprocess lifecycle。
- Docker/Cloud runtime provision、heartbeat、pause/terminate、orphan cleanup、resource quota。

这些事项在当前仓库只能记录为 L4 未证，不能用 Canvas 的 wire type、mock LLM 或 UI E2E 结果越级推断。

## 15. 本次分段审计补充：真实交互线

下面按浏览器中一次对话的实际顺序重排调用链。它比按目录阅读更接近故障定位路径，也明确指出每个交界处的权威状态在哪里。

```text
conversation query
  ├─ Local: AgentServerConversationService / typed ConversationClient
  └─ Cloud: App API start task → polling → conversation_url + session_api_key
                         │
                         ▼
useConversationHistory
  └─ REST event search → useEventStore.addEvents
                         │
                         ▼
history query settles
  └─ main WS: resend_mode=since + after_timestamp
       └─ no usable timestamp/error: resend_mode=all
                         │
                         ▼
useWebSocket.onopen
  └─ session auth frame → JSON event → type guard
       ├─ useEventStore.addEvent(raw + UI projection)
       ├─ event id duplicate? stop non-idempotent UI side effects
       ├─ state/metrics/error/cache stores
       ├─ terminal/browser projection
       └─ canvas_ui / launch_child client-side action bridge
                         │
                         ▼
sendMessage
  ├─ open WS: { ...message, run: true }
  └─ not open: ConversationClient.sendEvent(..., { run: true })
```

这条线有四个不能混淆的事实：

1. REST history 是主会话的初始快照，WebSocket 是尾部实时传输；前端不是通过 WebSocket 独立建立完整的持久化账本。
2. `resend_mode=since` 使用时间戳而非事件游标。相同时间戳、缺失时间戳、服务端排序差异和 timestamp 边界语义都依赖服务端实现与客户端 id 去重兜底。
3. WebSocket fallback 的 `sendEvent` 表示请求已交给服务端排队/执行入口，不表示 Agent 已开始或成功完成；optimistic message 仍依靠后续用户事件回显清理。
4. Cloud 的事件历史和 runtime live endpoint 不是同一上游：历史在 App API，count/confirmation/runtime WS 在 sandbox host，并分别使用 bearer 与 session API key。

### 15.1 规划子会话是另一条线

规划连接固定使用 `resend_all=true`，连接打开后再调用 runtime `/events/count`，通过收到的帧数达到 expected count 判断历史加载完成。事件仍进入与主会话相同的全局 store，并加 `isFromPlanningAgent` 标记；终端、错误、状态和 file observation 也复用主 handler 的一部分副作用。

这不是主会话 `REST → since` 协议的简单变体，而是 count-based stream barrier。count 请求失败时直接结束 loading；重复帧、丢帧、count 变化或同 id 跨主/规划会话冲突，当前前端没有独立的完整性校验。规划事件使用全局 `eventIds`，因此事件 id 若不在服务端全局唯一，可能误判为重复。

### 15.2 两种命令通道不能互换

`AgentServerRuntimeService.executeCommand` 是一次性 REST/typed-client 请求，默认 timeout 为 30 秒，Cloud proxy 的 HTTP timeout 为命令 timeout 加 10 秒；它返回聚合的 `exit_code/stdout/stderr`。

`useBashCommandRunner` 是独立的 `/sockets/bash-events` 流式协议：请求先进入 waiting/pending FIFO，收到 `BashCommand` 回显后取得服务端 `command_id`，再按 id 聚合输出直到非空 `exit_code`。该 hook 没有自动重连、重放、客户端计时器或远端 kill；连接断开会拒绝所有 waiting/pending/active Promise。因此同一个“终端命令”在 UI 中可能走两条语义不同的 transport，不能用一个通道的成功/取消结论推断另一个通道。

## 16. 事件账本、重连和恢复矩阵

| 阶段 | 当前实现 | 账本/恢复含义 | 主要风险 |
|---|---|---|---|
| REST 初始历史 | `useConversationHistory` → `addEvents` | 内存快照，按 id 去重并按 timestamp 排序 | 页面刷新依赖服务端历史；Cloud 分页过滤失败时只保留初始页 |
| 主 WS 首连 | `since + after_timestamp` 或 `all` | 通过 overlap + id 去重接缝 | 时间戳不是严格游标；无 id 事件不可去重 |
| 主 WS 断线 | 3 秒后重连，默认无限次数 | 重连后的 backlog 作为 replay | 旧 anchor、服务端 resend 语义和事件 id 唯一性未由本仓库保证 |
| 主 WS replay | `addEvent` 先登记，重复则跳过副作用 | UI 侧至少一次接收、best-effort 副作用去重 | 不保护服务端工具再次执行，也不恢复丢失的事件 |
| 规划 WS 历史/重连 | `resend_all` + count | 帧数达到 count 即结束历史态 | count/stream 不具备游标一致性；全局 id 可能跨会话碰撞 |
| Bash WS 断线 | reject 全部队列和活动命令 | 不重放、不续接 | 命令可能已在远端执行但结果未返回，客户端只看到失败 |
| Cloud pause/resume | pause 后本地 cache 标记 PAUSED，阻止旧 URL 建 WS；resume 后依赖查询刷新 | 只恢复路由和 UI 连接条件 | sandbox 是否继续、重启还是重建以及事件补偿均未证 |
| 进程/容器崩溃 | launcher 有退出钩子和进程组清理 | 仅本地启动器资源回收路径 | Agent loop、子进程、volume、租约、工具和 provider 的崩溃恢复未证 |

因此“重连成功”在本仓库只表示新的浏览器 WebSocket 建立并收到帧；它不等同于 Agent loop 恢复、正在执行的工具继续、事件 exactly-once 或 sandbox 健康恢复。

## 17. 取消、超时和崩溃恢复的审计结论

前端可观察到的取消语义是：pause mutation 成功后把 `execution_status` 和 `sandbox_status` 一起 patch 为 `PAUSED`，导航离开当前对话，并阻止向旧 sandbox host 建立连接。创建会话、Cloud child provisioning 和 HTTP command 分别有 5 分钟、180 秒和 `timeout + 10 秒` 的客户端/代理上限。WebSocket unmount/disconnect 会清理 timer、撤销旧实例的重连资格并关闭连接。

这些动作都不是服务端取消确认。当前代码没有把 `AbortSignal`、tool execution id、process id 或 server cancellation acknowledgement 贯穿到 Agent loop；bash socket 的 Promise reject 也没有发送远端 cancel。故以下状态在浏览器看来可能相同，但后果不同：

- 用户主动 pause 后 Agent loop 已停止；
- pause 请求成功但工具仍在远端运行；
- runtime 已崩溃，事件尚未写入历史；
- WebSocket 断开但远端命令已完成，结果只等待重连/历史补偿；
- 客户端 timeout 返回失败，但服务端请求后来成功。

若产品需要“取消即停止”和“崩溃后可恢复”，外部 Agent Server/runtime 必须提供可核验的 execution id、取消确认、事件游标/补偿、工具终态和 sandbox lease；仅修改 Canvas 的 loading、toast 或 socket 状态不足以满足该语义。

## 18. 文档质量审计

### 已满足

- 根文档、`docs/architecture.md`、README 的系统边界一致：Canvas 是 React/TypeScript 控制面，Agent loop、工具、workspace、sandbox 和 provider 属于外部服务。
- 端口、版本、包名和状态路径可回溯到 `config/defaults.json`；本地无 sandbox 与 Docker 挂载风险在 README 中有显式警告。
- 本文将“实现事实”“测试验证”和“外部未证”分级，避免把 wire types、mock LLM 或 UI E2E 写成后端保证。

### 仍需维护

- `docs/TESTING_MATRIX.md` 的多项安装/OS/Agent feature cell 仍为空，不能被当前 mock-LLM E2E 覆盖替代。
- `docs/architecture.md` 是高层介绍，未描述主会话 `REST → since WS`、规划 count barrier、bash 独立 socket 和 Cloud 双上游；本文的交互线应作为详细事实源，代码改动时同步更新。
- 本仓库没有被纳入的外部 SDK/server 源码，因此 `runtime/agent/event/server/workspace/sandbox/provider` 的后端文档只能列为核验清单，不能伪装成已审计实现。
- 部分源码仍有 `TODO: Tests`（例如状态更新分支），且 WebSocket 测试存在 MSW broadcast 跨测试污染导致的 skip；这些应在测试矩阵中保持可见，而不是标记为完整覆盖。

## 19. 本次审计最终结论

OpenHands 当前仓库的真实产品是“多后端 Agent Canvas + 本地栈启动器”。它把会话、事件、终端和云 sandbox 的 transport 接到外部 Agent Server，但不拥有后端 Agent 执行语义。最可靠的内部保证是：历史与实时事件的前端拼接、事件 id 的局部去重、重连 replay 时的 UI 副作用抑制、Cloud pause 时避免旧 host 连接、以及开发进程的有限清理。最重要的未决保证是：服务端事件账本的提交顺序和游标、工具执行幂等、取消是否真正终止、timeout 后的远端状态、sandbox 生命周期/隔离/回收、provider retry/budget，以及进程崩溃后的恢复。

任何声称“Agent 已取消”“工具未重复执行”“sandbox 已回收”或“事件已完整恢复”的结论，都必须在外部 Agent Server、software-agent-sdk、tools/workspace provider、Cloud runtime 和 provider 测试中补齐证据；本仓库的 UI 状态和 WebSocket 重连不能单独证明这些结论。

## 20. 施工材料吸收记录

已人工回读并吸收 `细探-OpenHands.md` 的增量事实：Canvas 前端事件投影与外部 Agent Server 的边界、主会话 `REST history → since WebSocket` 接缝、规划会话 `resend_all + count` barrier、bash 独立流式通道、事件 id 去重、Cloud 双上游、pause/resume 与远端取消不等价，以及 sandbox/provider/工具资源的未闭合恢复边界。旧材料不再作为并行事实源。
