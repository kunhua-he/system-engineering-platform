# OpenHands Agent Canvas 架构取证

> 项目根：`~/Documents/Agent/github 源码参考/10_agent_platform_reference/02_核心Agent框架/OpenHands`
> 当前提交：`bad1687dec93c5b3edbef837ab2dc12638964031`
> 远程默认分支：`origin/main` 当前为 `bad1687dec93c5b3edbef837ab2dc12638964031`；源码参考仓库已 fast-forward 到该提交，平台侧只维护本唯一文档。
> 本文是该仓库唯一架构取证文档；只描述当前仓库可证明的事实。

## 1. 顶部流程图

```text
浏览器 React Canvas
  │ 路由、状态、事件投影
  ▼
ConversationWebSocketProvider
  ├─ REST history → useEventStore
  ├─ conversation WebSocket → 事件解析/去重/副作用投影
  ├─ sendMessage ─┬─ OPEN socket: {message, run:true}
  │               └─ 非 OPEN: typed ConversationClient.sendEvent
  └─ client tool Action
       └─ launch_child → local/cloud child → reportLaunchResult → sendMessage
  │
  ├─ Local typed Agent Server / runtime
  └─ Cloud App API → task polling → conversation_url + session_api_key
                         └─ cloud proxy → 外部 Agent Server sandbox

外部 Agent Server / SDK / workspace / sandbox / LLM provider
  （Agent loop、工具执行、事件持久化、资源回收不在本仓库）
```

## 2. 仓库身份、代码地图与证据等级

当前记录以提交 `bad1687dec...` 为基线，源码参考根目录存在已同步的 `.codegraph/`。执行：

```text
codegraph explore "ConversationWebSocketProvider sendMessage createConversation useWebSocket handleLaunchChildConversationAction call paths"
```

CodeGraph 返回 40 个符号，确认主链：`ConversationWebSocketProvider → handleLaunchChildConversationAction → reportLaunchResult → AgentServerConversationService.sendMessage → callCloudProxy`；并标出 `createConversation`、`useWebSocket` 的调用方及对应测试。源码树统计（同步后）：1,898 个被 CodeGraph 索引的文件、20,142 个节点、54,750 条边；工作树可见文件 2,233 个，其中 `src/` 1,359 个，`tests/` 与 `__tests__/` 604 个。`src/api` 是 HTTP/typed 适配，`contexts` 是 React 连接与副作用，`hooks` 是 transport/query/mutation，`services` 是动作桥，`stores` 是浏览器投影，`types/agent-server` 是事件 wire union，`routes` 是页面入口，`electron/` 是桌面壳，`scripts/`、`docker/`、`helm/` 是启动/打包/部署边界。

证据等级：L0=目录/配置/版本；L1=当前函数体和调用链；L2=单元/组件测试；L3=真实或 mock Agent Server E2E；L4=生产、外部 SDK/server/runtime/provider。本文未把外部类型或 mock 结果升级为 L4。

## 3. 调用链取证

### 3.1 创建会话与发送消息

- `AgentServerConversationService.createConversation`，`src/api/conversation-service/agent-server-conversation-service.api.ts:402-523`：Cloud 组装扁平 `AppConversationStartRequest` 并返回异步 task；Local 并行读取 settings/profiles，解析绝对 workspace，构造加密 settings 后调用 `ConversationClient.createConversation`，Local task 直接标记 `READY`。客户端创建超时常量为 5 分钟（同文件 `:75-78`）。
- Local 成功后若没有 `getEffectiveLocalBackend()` 抛 `NoBackendAvailableError`；Cloud READY、sandbox provisioning 和 secrets 解析由外部 task polling 负责。
- `ConversationWebSocketProvider.sendMessage`，`src/contexts/conversation-websocket-context.tsx:1048-1097`：当前 socket 非 OPEN 时，无 conversation id 直接抛错；否则调用 typed `sendEvent(..., {run:true})`，失败归一为可见错误后再次抛出；OPEN 时 `socket.send` 同步异常也被捕获。返回 `{queued:true/false}` 仅表示请求进入 REST/WS，不表示 Agent 已执行。

### 3.2 实时事件、重连与副作用

- `ConversationWebSocketProvider`，`src/contexts/conversation-websocket-context.tsx:121-766`：先装载 REST history，再用 `resend_mode=since + after_timestamp` 接 WebSocket；无可用锚点时退化 `resend_mode=all`。事件 id 先在 `useEventStore` 去重，重复事件跳过 toast、终端、浏览器、缓存和 client-tool 等非幂等副作用；JSON 解析异常在 `:748-750` 仅告警。
- `useWebSocket.connectWebSocket`，`src/hooks/use-websocket.ts:38-120`：OPEN 时先发 session auth；非 1000 close 设置错误，满足 reconnect enabled、实例仍被允许、未达 maxAttempts 才在 3 秒后重连。
- effect cleanup，`src/hooks/use-websocket.ts:122-157`，及 `disconnect` `:168-180`：先撤销重连资格、清 timer、从 WeakSet 删除 socket，再 close，避免卸载触发重连。close/error 不发送远端取消。
- 规划连接使用 `resend_all=true` 与 `/events/count` 帧数 barrier（`conversation-websocket-context.tsx:958-1011`），不是主会话时间戳接缝；count/stream 不一致时无额外完整性校验。

### 3.3 Child conversation 动作

- `handleLaunchChildConversationAction`，`src/services/child-conversation-launch.ts:505-536`：先 `claimToolCall(parent, toolCallId)`，重复调用直接返回；参数非法转 corrective guidance；local/cloud launch 异常转失败结果；`reportLaunchResult` 失败只 `console.warn`，函数不 reject。
- `launchCloudChild`，同文件 `:386-448`：无 Cloud backend 返回失败；创建 task 后 `waitForCloudConversationId`（`:365-383`）轮询，间隔/总时限受常量约束，ERROR 转失败，超时可返回仍 provisioning 的 task；本地父会话与 Cloud child 不建立 parent link。
- `reportLaunchResult`，`:459-497`：先 toast，再检查 goal 是否 active；非 active 才通过 `AgentServerConversationService.sendMessage` 把 child 结果交回 Agent。该消息会触发服务端当前 `/goal` 的新一轮语义，故 active 时刻意不发送。

## 4. 状态、资源与失败矩阵

| 场景 | Canvas 已实现 | 未证明/风险 |
|---|---|---|
| 正常创建 | Local typed create；Cloud task polling；workspace 元数据写本地 store | 服务端 loop、事件提交顺序 L4 |
| 正常消息 | WS 发送或 REST fallback，统一 `run:true` | queued 不等于执行成功 |
| 断线重连 | 3 秒重连、实例资格和 timer 清理、事件 id 去重 | 时间戳不是严格游标；服务端 replay/丢帧 L4 |
| 发送失败 | 无 id/REST/WS 异常均抛出并写错误 store | 请求可能已在远端成功但客户端超时 |
| Cloud provisioning 超时 | child poll 有界；创建 5 分钟；bash proxy 为 command timeout+10 秒 | 远端 task 是否继续、孤儿 sandbox 回收 L4 |
| 用户暂停/离开 | mutation 更新 UI 为 PAUSED，阻止旧 host socket；卸载关 socket | 未证明 Agent loop、工具进程、容器真正停止 |
| client tool 重放 | toolCallId localStorage claim；重复跳过 | storage 损坏/跨 tab 竞态时可重复启动；无 TTL |
| 崩溃/重启 | dev launcher 进程组信号、Docker entrypoint cleanup | 事件账本、active tool、volume、租约、provider 恢复 L4 |
| 删除会话 | 远端 delete 后移除本地 metadata | runtime/container/files 清理由外部服务负责 |

关键资源边界：`useEventStore` 仅内存投影；bash-events socket 断开会 reject waiting/pending/active Promise，但不发送远端 kill；Cloud runtime 使用 session API key，经 cloud proxy；路径读取通过 `requirePathInsideDirectory` 守住 workspace 内边界（`agent-server-conversation-service.api.ts:628-648`）。

## 5. 并发、权限与多入口一致性

- 主会话、规划会话、bash-events 是三条不同 transport；不能用某一通道成功推断另一通道的取消或执行状态。
- REST history 与 WS overlap 依赖事件 id；无 id 事件、同时间戳事件和跨会话 id 冲突无严格保证。
- Cloud bearer 只到 App API，runtime host 使用 conversation session key；本仓库不 materialize provider secret。
- Local 无 sandbox 模式可让外部 Agent Server 直接访问主机 filesystem/network；Docker 仅挂载 `$PROJECTS_PATH` 并持久化 `~/.openhands`，Canvas 不实现隔离策略、quota 或 seccomp。
- `createConversation` 的 Cloud/Local、`sendMessage` 的 WS/REST、child 的 local/cloud 都共享公开 service 入口，但后端状态语义不对称（Cloud fork 不支持，local child 可能 shared fallback）。

## 6. 测试证据

- L2：`__tests__/hooks/use-websocket.test.ts`（auth 首帧、连接、错误、query 参数）；`__tests__/contexts/conversation-websocket-context.test.tsx`；`__tests__/api/agent-server-conversation-service.test.ts`；`__tests__/api/cloud/conversation-create.test.ts`。
- L3：`tests/e2e/mock-llm/conversations/mock-llm-conversation.spec.ts` 覆盖 Canvas→外部 Agent Server→mock LLM trajectory、terminal observation、事件 API、worktree 和 resume；`tests/e2e/live/real-agent-server-conversation.spec.ts` 覆盖真实 Agent Server/LLM 工具路径。
- 已知缺口：CodeGraph 标记 `CreateConversationOptions` 无直接覆盖测试；WebSocket 广播/close 部分测试因 MSW 跨测试污染跳过；无服务端 loop 取消、tool 已执行但 observation 丢失、WS/REST 乱序、sandbox 崩溃回收、provider retry/rate-limit 的本仓库证据。

## 7. 外部未读范围与平台映射

当前记录未读取 `node_modules`、凭据、构建产物，也未启动服务或安装依赖。未读且必须在外部仓库核验的范围：`software-agent-sdk`/Agent Server 的 Agent loop、event append/search/resend、工具 subprocess timeout/kill、workspace/git worktree、Docker/VM/Cloud sandbox provision/lease/GC、LLM/ACP provider retry 与预算。

映射到系统工程平台时，Canvas 适合作为“项目适配层/前端核心”的 transport 与 UI 投影样板；统一能力调用、权限租约、任务状态机、事件账本、资源协调和 provider 适配必须落到平台运行核心/支持库，不能把 OpenHands 前端 store 或 WebSocket 重连当作权威账本。建议保留的能力候选：会话创建/恢复、事件流订阅、路径约束、受控命令执行、子会话编排；每项都需补服务端 execution id、取消确认、游标补偿和资源终态证据。

## 8. 验证记录

```text
git rev-parse HEAD                    -> b1f0accae1657e46a200214e3559af856ba7ae44
codegraph explore（主调用链查询）    -> 退出码 0，返回 29 个符号
文档结构断言                         -> 退出码 0
git diff --check                      -> 退出码 0
git status --short -- ARCHITECTURE.md -> ?? ARCHITECTURE.md（唯一文档未跟踪）
```

未运行 E2E/真实 provider；当前记录验证是静态取证和文档校验，不宣称生产运行成功。

## 9. 当前源码深挖：目录与模块职责

当前 checkout 约 1,893 个文件、20,015 个 CodeGraph 节点、54,415 条边；CodeGraph `sync` 显示索引已是最新。目录命名与职责如下：

```text
src/api/                         REST/typed API、Agent Server/Cloud service adapter
src/contexts/                    Conversation React provider、事件副作用与连接状态
src/hooks/                       WebSocket、query、mutation、auth hooks
src/services/                    child conversation、launch、report、workspace bridge
src/stores/                      event/conversation/local metadata 投影
src/types/agent-server/          Agent Server event union、guards、wire payload
src/components/conversation-events/ 事件渲染、tool/observation/terminal 展示
src/routes/                      Canvas、conversation、settings 页面入口
__tests__/                       hooks/context/service/api/component contract tests
tests/e2e/                       mock-LLM、live Agent Server、Cloud/Local workflow tests
app/                             前端构建与部署入口（若由当前 package 配置启用）
```

本仓库是 OpenHands Canvas/控制前端，不是 Agent Server 核心。Agent loop、工具 subprocess、模型 provider、sandbox lease 和事件 durable append 位于外部 Agent Server/SDK；本档案只把本仓库可证明的请求、事件与资源边界记录为 L1/L2，并将外部运行时明确标为 L4 未验证。

## 10. 五条以上真实函数体调用链

### 10.1 会话创建（Local/Cloud 分叉）

```text
Conversation UI action
  → AgentServerConversationService.createConversation
  → normalize settings / workspace / profile
  → Local: ConversationClient.createConversation
  → Cloud: AppConversationStartRequest → task polling
  → conversation id + READY/provisioning metadata
  → ConversationWebSocketProvider load history/connect
```

证据：`src/api/conversation-service/agent-server-conversation-service.api.ts:402-523`。Local 先读取 settings/profiles、解析绝对 workspace、构造加密 settings，创建失败或无 backend 时返回 typed error；Cloud 创建异步 task，后端是否完成 sandbox/secret/provider 初始化不在本仓库。

### 10.2 WebSocket 建连、认证、重连与消息发送

```text
useWebSocket(url, options)
  → connectWebSocket:34-118
  → new WebSocket + WeakSet reconnect permission
  → onopen → sendWebSocketAuth:4-18
  → onmessage callback → ConversationWebSocketProvider event reducer
  → onclose → 3s timer / maxAttempts / instance permission
  → sendMessage:157-164 或 reconnect:180-204
```

卸载/`disconnect` 先清除 `shouldReconnect`、timer 和该 socket 的 WeakSet 资格，再 close；因此本地不会因正常卸载触发重连。该实现没有远端取消语义，close 只改变前端连接状态。

### 10.3 事件历史、重放与副作用投影

```text
ConversationWebSocketProvider mount
  → REST history
  → derive resend cursor (since/after_timestamp 或 all)
  → WebSocket conversation events
  → useEventStore id 去重
  → event type guard
  → transcript/terminal/browser/client-tool/toast 投影
  → React render
```

重复事件按 event id 跳过非幂等副作用；无 id 或跨会话重复无法由该 store 严格证明。规划连接使用 `/events/count` barrier 和 `resend_all`，与主会话的时间戳接缝不同，不能统一宣称全局 cursor。

### 10.4 Agent message fallback

```text
ConversationWebSocketProvider.sendMessage:1048-1097
  → socket OPEN? socket.send({message, run:true})
  → 非 OPEN: typed AgentServerConversationService.sendEvent
  → request error normalization
  → visible error store + throw
```

返回的 `queued` 只表示请求进入本地 transport，不代表 Agent Server 已接受、模型已执行或最终消息已落库。客户端超时后远端可能已经成功，重复点击存在 duplicate user message 风险，除非服务端使用稳定 idempotency key。

### 10.5 Child conversation launch

```text
client tool event
  → handleLaunchChildConversationAction:505-536
  → claimToolCall(parent, toolCallId)
  → validateLaunchParams
  → launchLocalChild 或 launchCloudChild
  → local workspaceMode(shared/new_worktree) 或 cloud task poll
  → reportLaunchResult:459-497
  → active goal? skip : AgentServerConversationService.sendMessage
```

Local child 先解析父 workspace；worktree 创建失败时降级 shared 并返回 `isolation_note`。Cloud child 在 `CLOUD_START_POLL_INTERVAL_MS=3000`、总超时 180 秒窗口内轮询 conversation id；超时可能仍返回 provisioning task。claim 只防同一 `toolCallId` 重放，不能替代服务端 child execution lease。

### 10.6 Agent settings 与工具可见性

```text
agent-server settings payload
  → toRecord/normalizeSecretString
  → shouldIncludeTool:631-644
  → DEFAULT_TOOL_NAMES + browser/task gating
  → configured tools schema clone
  → build conversation request encrypted settings
```

`enable_sub_agents` 和 browser capability 决定特殊 tool set；配置 tools 必须是 `{name, params}` 记录。订阅模型在 `assertSubscriptionAuthReady:1242-1252` 检查连接状态，不在前端保存 provider secret。

## 11. 数据、事件与持久化边界

### 11.1 前端状态

| 状态 | owner | 生命周期 | 失败语义 |
|---|---|---|---|
| conversation metadata | local store/query cache | 页面/会话级 | REST 失败显示错误，不证明远端删除 |
| event store | 内存 React/store | socket/session 级 | 重载需 history+resend；内存丢失 |
| tool claim | localStorage key 前缀 | 浏览器持久 | 无 TTL，跨 tab 竞态和清理失败可能重复/永久阻塞 |
| websocket instance | hook ref + WeakSet | 连接级 | close/error 触发状态转移；不持久化 cursor |
| child launch result | toast + agent message | 一次动作 | report 失败仅 warn，可能没有回传父 Agent |

### 11.2 外部事实源

Agent Server conversation、event append、run status、tool execution、workspace filesystem、Cloud task、sandbox/VM、LLM usage 和 provider retry 均是外部 owner。本仓库只持有 request/response projection 和短期 UI state，不能从 Canvas store 推断完整事实账本。

### 11.3 认证与权限

- WebSocket 首帧可发送 `session_api_key`；无 key 时不发送 auth frame。
- Cloud App API bearer 与 runtime host session key 是不同信任边界，Canvas 不应把 runtime key 暴露给不受信组件。
- child launch 参数在前端校验 target/task/isolation，但最终权限、parent link、workspace access 必须由 Agent Server 再校验。
- Local workspace 路径通过 `requirePathInsideDirectory` 约束在父 workspace；shared fallback 明确提示 siblings 可能冲突。
- tool visibility 受 `enable_sub_agents`、browser flag、server availability 和 configured tools 共同影响，前端可见不等于服务端执行授权。

## 12. 失败、取消、崩溃与资源矩阵

| 场景 | 当前源码行为 | 资源边界 | 证据/缺口 |
|---|---|---|---|
| 建连正常 | onopen 发 auth、清错误、重置 attempt | WebSocket ref | L1；未运行真实 server |
| 非正常 close | 设置 error，符合条件 3 秒后重连 | timer、旧 socket WeakSet | L1/L2；无远端 resume 证明 |
| 手动 disconnect | revoke reconnect permission 后 close | timer/socket | L1；不发送远端 stop |
| 消息发送异常 | WS/REST typed error 归一并抛出 | request promise | L1；远端可能已成功 |
| 事件 JSON 错误 | warning，继续 connection | frame discarded | L1；可能丢事件 |
| 重复事件 | event id 去重，跳过副作用 | memory event store | L1/L2；无 id 事件风险 |
| Cloud start polling error | status error 转 LaunchFailure | poll timer/task | L1；远端 task GC 未知 |
| Cloud start timeout | 返回 provisioning/task 信息或错误 | poll timer | L1；sandbox 是否继续未知 |
| Local worktree fail | retry shared，返回 isolation_note | git process/worktree | L1；shared collision 风险 |
| Child claim duplicate | claimToolCall 返回既有结果 | localStorage | L1/L2；无 TTL/跨 tab 原子性 |
| Goal inactive | 不发送 launch result message | toast only | L1；父 Agent 可能不知道 child |
| Browser/client tool disconnect | 前端 promise reject/状态清理 | socket/listener | L1；外部 tool 是否 kill 未知 |
| Agent Server cancel | 本仓库只有 stop/message API 适配 | remote run | L0/L1；服务端取消未读 |
| Canvas 崩溃 | 浏览器内存 projection 丢失 | local cache/history reload | L1；服务端事件/任务依赖外部 durable owner |
| Agent Server 崩溃 | Canvas reconnect/history/resend | remote run/sandbox | L0；接管、lease、orphan 未验证 |
| Cloud proxy 崩溃 | HTTP/SSE 错误、可能重连 | bearer/session key | L1；unknown-after-send 未证明 |

取消与重连必须分开：`useWebSocket.disconnect` 只阻止新的连接；它不取消模型、工具、sandbox 或 Cloud task。真正取消需要 Agent Server 的 run/stop contract 和执行 owner ack，本仓库没有可证明的终态确认。

## 13. 测试映射与验证等级

| 领域 | 代表测试 | 静态覆盖 | 当前记录执行 |
|---|---|---|---|
| WebSocket hook | `__tests__/hooks/use-websocket.test.ts` | auth 首帧、close/error、query、reconnect | 未执行 |
| Conversation context | `__tests__/contexts/conversation-websocket-context.test.tsx` | history、event、send fallback、dedupe | 未执行 |
| Child launch | `__tests__/services/child-conversation-launch.test.ts` | validation、claim、local/cloud、report | 未执行 |
| Service API | `__tests__/api/agent-server-conversation-service.test.ts`、`__tests__/api/cloud/conversation-create.test.ts` | request shape、workspace、poll | 未执行 |
| Event rendering | `__tests__/components/conversation-events/**` | event guards、tool/observation/ACP render | 未执行 |
| Mock E2E | `tests/e2e/mock-llm/conversations/mock-llm-conversation.spec.ts` | Canvas→Agent Server→mock LLM | 未执行 |
| Live E2E | `tests/e2e/live/real-agent-server-conversation.spec.ts` | 真实 Agent Server/provider（需环境） | 未执行 |

证据等级：L0=配置/文档；L1=当前函数体和行号；L2=测试源码存在；L3=当前记录隔离测试退出码 0；L4=真实 Agent Server/Cloud/provider/sandbox/崩溃现场。当前记录新增最高 L2。

## 14. 未读范围与平台映射

### 未读/未验证

1. 未读取外部 Agent Server 的真正 Agent loop、事件 append/search、run state machine、tool subprocess、sandbox lease/GC、provider retry/usage 和 ACP runtime。
2. 未读取完整 Cloud backend/task worker、workspace/git worktree 服务端、VM/container 生命周期和 secrets broker。
3. 未逐一核对全部 Canvas route、event union、client tool handler、browser/terminal UI 与所有 API payload schema。
4. 未安装依赖、启动 dev server、连接 WebSocket、执行 mock/live E2E、注入网络断开或进程崩溃。
5. 未验证事件 id 全局唯一、REST history 与 WS resend 的严格顺序、跨 tab localStorage claim 原子性、远端 stop 的终态确认。

### 平台映射

| OpenHands 能力 | 系统工程平台候选 | 裁决 |
|---|---|---|
| Conversation service | 统一网关/项目适配层 | 保留 DTO、Local/Cloud adapter；execution owner 必须下沉平台运行核心。 |
| WebSocket hook + event store | 统一网关事件订阅模块 | 吸收重连资格、cursor/resend、去重；不能把内存 store 当事实账本。 |
| Child launch service | 模块库·任务编排 | 吸收 parent scope、worktree/shared 隔离、poll 超时；补 durable lease/terminal ack。 |
| Tool visibility/settings | 公共契约 + 权限模块 | 服务端二次授权、能力 registry、secret boundary 必须唯一。 |
| Workspace path guard | 支持库·文件系统安全 | 保留 root boundary、symlink/path 校验；补文件句柄/制品生命周期。 |
| Cloud/local adapter | 项目适配层 | 只绑定环境和 provider，不复制 Agent loop 或 sandbox 实现。 |
| Agent event types | 公共契约·事件 schema | 保留 discriminated union/type guards；补 event id/seq/attempt/idempotency。 |

本项目最有价值的参考是“前端 transport 与外部 Agent runtime 的边界显式化”；最危险的误用是把 WebSocket reconnect、toast、localStorage claim 或 queued 返回值误当作执行成功、取消成功或崩溃恢复证据。

## 15. 交互契约详表

### 15.1 ConversationWebSocketProvider 责任

`ConversationWebSocketProvider` 是浏览器侧协调器，不是执行器。其责任限定为：

- 读取 conversation history 并建立初始事件锚点；
- 为主会话、规划会话、bash-events 选择不同 socket/transport；
- 将事件 union 映射到 `useEventStore`、消息列表、terminal、browser、client-tool 和 toast；
- 对带 event id 的事件做幂等去重；
- 在 socket 非 OPEN 时使用 typed REST/event fallback；
- 将 reconnect/cleanup 状态暴露给 UI；
- 将 child launch 结果通过 toast 或新 user message 投影回 Agent Server。

它不负责：模型重试、工具超时、sandbox kill、provider quota、Cloud task lease、消息 durable append、取消确认或运行终态判断。

### 15.2 WebSocket 状态机

```text
UNMOUNTED
  └─ effect(url) → CONNECTING
CONNECTING
  ├─ open → OPEN (auth first frame, attempts=0)
  ├─ error/close → DISCONNECTED + error
  └─ cleanup/disconnect → CLOSED (reconnect forbidden)
OPEN
  ├─ message → callback/event projection
  ├─ error → DISCONNECTED
  ├─ close normal(1000) → DISCONNECTED(no error)
  └─ close abnormal → RECONNECT_WAIT if enabled/allowed
RECONNECT_WAIT
  ├─ timer 3s → CONNECTING
  ├─ max attempts → DISCONNECTED
  └─ unmount/manual disconnect → CLOSED
```

`allowedToReconnectRef` 按 socket 实例，而非仅 URL，避免旧 socket 的迟到 close 事件重启新 socket。该机制是前端连接安全阀，不是服务端事件 cursor。

### 15.3 Child launch 状态机

```text
RECEIVED tool_call
  → CLAIMED(toolCallId)
  → VALIDATED(target/task/title/repository/branch/isolation)
  → LOCAL_CREATING(workspaceMode) | CLOUD_STARTING(task)
  → LOCAL_READY(conversation_id) | CLOUD_POLLING
  → LAUNCHED(parent_link/isolation metadata)
  → REPORTED(toast + optional Agent message)
```

非法参数在 `validateLaunchParams` 产生 corrective guidance；claim 重放返回之前结果；local worktree 失败只允许一次 shared fallback；cloud polling 到达上限后不得把 provisioning 当 READY。任何 report 失败都只告警，调用方必须通过 UI/日志发现父 Agent 未收到结果。

## 16. 资源生命周期与泄漏风险

| 资源 | 创建点 | 持有者 | 正常释放 | 失败/取消 | 崩溃后现场 |
|---|---|---|---|---|---|
| WebSocket | `connectWebSocket` | hook instance | cleanup/disconnect close | remove WeakSet before close | browser closes socket; remote run unknown |
| reconnect timer | onclose | hook ref | clear on reconnect/cleanup | maxAttempts stops | page crash drops timer |
| event subscription | provider effect | conversation context | unsubscribe on unmount | parse errors skip frame | server cursor/history recovery external |
| localStorage tool claim | `claimToolCall` | browser profile | result overwrite/consumer | storage error may duplicate | stale key may block future tool |
| REST task poll | cloud launch | child launch service | success/error/timeout | timeout returns diagnostic | remote task may continue |
| local worktree | Agent Server create call | external server/workspace | server cleanup | fallback shared on create failure | orphan worktree external |
| cloud sandbox | Cloud task | external backend | backend GC | proxy/client timeout | lease/GC unknown |
| session API key | cloud response | service/client request | memory/request scope | auth error | not persisted by Canvas |
| terminal/browser client tool | event handler | external Agent Server | remote runtime | socket reject only | process/tab orphan unknown |
| React event store | provider/store | browser memory | unmount/reload | event dropped | no durable copy |

### 16.1 资源正确性裁决

1. Canvas 关闭 socket 不等价于停止 Agent；停止必须由 Agent Server 暴露可确认的 run cancellation contract。
2. Cloud task timeout 只结束前端 polling，不代表 Cloud worker、workspace、container 或 provider request 已终止。
3. localStorage claim 没有 TTL、owner token 或 compare-and-set 证明；应在平台侧以 durable idempotency record 替代。
4. event store 去重依赖 event id；清空内存后必须通过 history + cursor/resend 重建，否则 UI 只能展示部分事实。
5. worktree/shared fallback 是明确的资源隔离降级，必须在用户可见结果中保留 isolation metadata，不能静默宣称隔离。

## 17. 并发、顺序与权限边界

### 17.1 并发

- WebSocket reconnect timer 与 manual reconnect 可能交错；实现通过清 timer、撤销旧实例资格降低重复连接，但未由当前记录运行验证竞态。
- REST history、WS replay 和 live frame 存在 overlap；事件 id 去重只覆盖带 id 事件，不能确保跨通道全序。
- Child launch claim 是浏览器本地作用域；多个 tab/设备可能各自 claim 同一 tool call。
- Local/cloud child launch 的异步 task 与父会话生命周期脱钩；父页面关闭后 task 是否 cancel 由外部服务决定。
- 多个 UI 组件可同时发送 `run:true`；客户端没有统一 per-conversation send lease 或 monotonic turn id。

### 17.2 顺序

| 顺序关系 | 当前机制 | 保证强度 |
|---|---|---|
| history → WS | after timestamp/since/all | 部分；服务端边界未验证 |
| WS frame → UI effect | event id dedupe | 仅带 id，非全局序 |
| tool call → child launch | claimToolCall | 浏览器局部幂等 |
| child launch → parent report | active goal 检查 | report 可能被跳过 |
| Cloud task → conversation id | poll interval/timeout | provisioning 可持续 |
| close → remote cancel | 无调用 | 不保证 |

### 17.3 权限

权限分为四层：Canvas route/session access、WebSocket session authentication、Cloud API bearer/runtime session key、Agent Server tool/workspace policy。任何一层通过都不能替代下一层授权。`settings.tools` 是请求建议集合，不能作为服务端 allowlist 的唯一事实；`enable_sub_agents` 只控制是否暴露任务工具，最终 child launch 仍需 parent/session/workspace 权限。

## 18. 失败恢复设计与缺口

### 18.1 正常/失败/超时/取消/崩溃矩阵（扩展）

| 执行单元 | 正常 | 业务失败 | 超时 | 主动取消 | 进程崩溃 |
|---|---|---|---|---|---|
| Canvas connect | open+auth | error/close | browser/network timeout | disconnect | browser reload |
| history fetch | events loaded | HTTP error | request timeout | abort/unmount | no local durable history |
| live event | parse/project | malformed frame warning | heartbeat absent (server unknown) | unsubscribe | reconnect+resend attempt |
| send user message | queued/run accepted | typed error | client timeout ambiguous | no local cancel ack | remote may continue |
| local child | READY id | create failure/fallback | external request timeout | no explicit stop | server-owned cleanup unknown |
| cloud child | task→id | task ERROR | 180s poll timeout | no explicit stop | Cloud lease/GC unknown |
| client tool | result event | observation error | socket/promise reject | local reject only | remote process unknown |

### 18.2 平台侧必须补充

- `execution_id`, `attempt`, `event_seq`, `idempotency_key` 统一贯穿 message/run/tool/child；
- cancel request、owner acknowledgement、terminal event 三段式取消；
- Cloud/local workspace 与 sandbox lease 的 owner/fencing/expiry/reaper；
- history/resend 的严格 cursor、gap detection、replay window 和 event retention；
- unknown-after-send reconciliation 与第三方 message id 查询；
- 浏览器 UI 重连后的 session authorization refresh 和权限撤销；
- child launch 的跨设备 dedupe、结果投递 receipt 和孤儿 task 扫描。

## 19. 验证命令与现场状态

```text
git rev-parse HEAD
  -> b1f0accae1657e46a200214e3559af856ba7ae44 (exit 0)
codegraph status
  -> 1,893 files / 20,015 nodes / 54,415 edges, index up to date (exit 0)
codegraph sync
  -> Already up to date (exit 0)
codegraph explore "session conversation WebSocket agent loop tool sandbox child launch event queue cancel"
  -> 46 symbols, exit 0
python static structure assertion
  -> document >=500 lines, current HEAD, required anchors (exit 0)
git diff --check
  -> exit 0
git status --short
  -> ?? .codegraph/ and ?? ARCHITECTURE.md only
```

当前记录不执行依赖安装、前端构建、Agent Server 启动、Cloud 登录、真实 WebSocket、mock/live E2E 或任何凭据读取；这些属于下一验证级别，不能由静态文档检查替代。

## 20. 事件与 API 契约核对

### 20.1 事件 union

`src/types/agent-server/core/openhands-event.ts` 及 `type-guards.ts` 将 Agent Server 事件按 discriminated union 暴露给前端。代表类别包括：

- conversation state/status：开始、运行、暂停、完成、错误、恢复；
- message/assistant：文本增量、最终消息、reasoning、usage；
- tool/action/observation：工具调用、参数、执行开始/结束、观察结果和错误；
- terminal/browser：命令输出、退出码、浏览器动作与截图引用；
- ACP：`ACPToolCallEvent` 等编辑器协议事件；
- client tool：需要浏览器回调的请求与结果；
- plan/task/child：子会话、计划节点和异步任务状态。

type guards 只保证 JSON 形状和 discriminant；不保证事件来自受信会话、顺序连续、唯一或已持久化。连接上下文必须先完成 conversation/session authorization，再接受事件副作用。

### 20.2 API/transport 入口

| 入口 | 请求承载 | 返回/事件 | 权限 owner | 失败边界 |
|---|---|---|---|---|
| Local conversation API | typed JSON + encrypted settings | task/status/conversation id | Agent Server local auth | backend unavailable/workspace invalid |
| Cloud App API | bearer + start request | provisioning task/poll result | Cloud app | task error/timeout/secret unavailable |
| Conversation WS | auth frame + message/event | event union/live stream | session API key | close/error/reconnect |
| REST event fallback | typed send event | accepted/error | Agent Server | HTTP timeout/duplicate ambiguity |
| Bash events socket | command/event frames | terminal output | sandbox/session | reject on disconnect |
| Client tool bridge | event + toolCall id | browser/client result | browser session policy | stale claim/unknown tool |

### 20.3 API 契约不能过度推断

Canvas service 对请求字段做 normalize/clone、workspace path 检查和工具 gating，但不会验证 Agent Server 内部的模型 token budget、tool subprocess policy、container network policy、Cloud quota 或 provider retry。前端收到 `status=READY` 只代表 API/任务层声明，不代表第一个模型请求成功。

## 21. 复核结论

1. OpenHands Canvas 的唯一稳定价值是把多种前端入口归一到 Conversation service + event projection + child launch adapter；Agent loop 和执行事实位于外部 Agent Server。
2. WebSocket reconnect、history/resend 和 event-id dedupe 形成有限的客户端恢复策略，但没有全局 event ledger、gap proof 或终态确认。
3. Child local/cloud launch 已有参数校验、workspace 隔离提示、poll 有界和 tool-call claim；没有跨设备 idempotency、lease fencing、cancel ack 或 orphan GC 证据。
4. tool visibility、session API key、Cloud bearer、workspace path 和 parent link 体现了多层权限；最终执行权限必须由服务端重新验证。
5. Canvas 不应把 UI store、queued 返回值、toast、socket close 或 localStorage claim 映射为平台成功/取消/恢复事实；这些只能作为边缘投影或幂等提示。
6. 平台吸收时应先定义统一 `ExecutionContext`、`EventEnvelope`、`ArtifactRef`、`CancelRequest/CancelAck`、`Lease/Fencing` 和 `ProjectionCursor`，再接入 OpenHands adapter。

### 21.1 维护规则

每次修改 conversation creation、WebSocket reconnect、event dedupe、child launch、workspace isolation 或 tool settings 时，必须同步更新：

- 顶部流程图与真实函数行号；
- 状态/资源/失败矩阵；
- 测试路径和实际退出码；
- 外部 Agent Server 未读范围；
- 平台映射中的 owner 与禁止过度推断项。

本档案不创建平行“研究材料”文件；所有新增证据应去重后回写本文件，并以对应 Git HEAD 绑定。

静态证据与运行证据必须分栏记录，不能用组件测试替代外部服务验证。
任何新 adapter 都必须声明其状态 owner、取消入口、超时、资源释放和崩溃恢复策略。
客户端投影丢失时只能通过服务端 history/resend 恢复，不能凭 UI 内存状态补写事实。
本项目映射结论默认 L1/L2，除非有可重放的真实 Agent Server 运行证据。
文档验证退出码 0 只代表本文格式和锚点检查通过。

## 22. 整项目目录导航与入口责任

本节把源码目录名和实际责任对齐，便于后续按入口继续下钻，而不是只依赖文件名猜测：

| 目录/入口 | 当前源码责任 | 不应误判为 |
|---|---|---|
| `src/routes/`、`src/root.tsx` | React Router 页面装载、认证和全局 provider 组合 | Agent 执行循环 |
| `src/contexts/` | 会话 WebSocket、事件副作用、登录/配置上下文 | 权威事件账本 |
| `src/api/` | Cloud/Local HTTP、typed client、重试、path 和 payload 适配 | 后端业务状态机 |
| `src/hooks/` | React query、连接重试、命令/上传 mutation 和 UI 生命周期 | 独立后台 worker |
| `src/services/` | child conversation、client tool、自动化、通知等跨 API 编排 | 通用模块库能力注册表 |
| `src/stores/` | 会话列表、事件、设置、toast 等浏览器投影 | 可恢复的服务端事实源 |
| `src/types/agent-server/` | Agent Server 事件 union、鉴别器和展示所需类型 | 事件真实性/顺序校验器 |
| `src/components/` | Canvas、会话、工具、设置、Git/MCP/Skills 面板 | 领域服务实现 |
| `scripts/` | dev/build/static/ingress/automation/desktop 辅助入口 | 运行核心的统一调度器 |
| `docker/`、`helm/`、`electron/` | 容器、Kubernetes、桌面发行包装 | 统一资源租约实现 |
| `tools/`、`examples/` | Agent Canvas 工具和示例 | 生产能力注册表 |

当前有三种可运行形态：

1. `npm run dev` 通过 `scripts/dev-with-automation.mjs` 组合前端、额外后端和自动化服务；实际 Agent loop 仍由外部 Agent Server 提供。
2. `npm run dev:static`/`npm run start` 只提供构建后的静态 Canvas，API/WS 仍需配置到 Local 或 Cloud backend。
3. Electron 和 Docker/Helm 是分发/宿主包装，改变启动与网络边界，不改变 `ConversationService → EventProjection` 的核心前端调用契约。

## 23. 当前版本新增的可导航证据

远程更新后新增或改动的入口必须纳入后续审计：

- `src/utils/websocket-handshake.ts`：将 WebSocket handshake/auth 的构造边界抽成可测试工具；它只准备连接协议，不确认会话授权已被服务端接受。
- `src/utils/vscode-origin.ts` 与 `src/hooks/query/use-unified-vscode-url.ts`：根据后端 runtime 信息拼接 VS Code/Agent Canvas URL；URL 可达性和反向代理路由仍由 `scripts/ingress.mjs`、Docker/Helm 和宿主配置决定。
- `src/contexts/conversation-websocket-context.tsx`、`src/hooks/use-websocket.ts`：重连、history/resend、事件去重和 cleanup 的代码路径有新增测试；仍不能证明外部 Agent Server 的 replay 完整性。
- `scripts/dev-safe.mjs`、`scripts/dev-with-automation.mjs`、`scripts/static-server.mjs`、`docker/entrypoint.sh`：启动/停止脚本现在包含更多进程组和路由处理；这些脚本的清理证据只覆盖本地 launcher 进程，不能外推到 sandbox、容器卷、远端 task 或 provider 进程。
- `__tests__/scripts/docker-vscode-route-sync.test.ts`、`__tests__/scripts/vscode-base-path-opt-in.test.ts`、`__tests__/utils/vscode-origin.test.ts`：新增测试证明配置/路由拼接契约，不证明真实 Docker、Ingress 或 VS Code 连接。

## 24. 平台分层选择：模块库、支持库与项目适配层

把 OpenHands 能力吸收进系统工程平台时，选择依据应是“是否需要替换第三方/系统边界”，而不是目录名：

| OpenHands 事实 | 平台归属建议 | 原因与边界 |
|---|---|---|
| `ConversationService` 的创建/恢复/消息发送协议 | 模块库公开能力 | 它组合会话、事件和权限语义；模块只持有能力 id/契约版本，不直接导入 SDK |
| WebSocket/REST/Cloud proxy/typed SDK | 支持库适配层 | 这些是外部协议和第三方边界，需要统一错误、超时、重试、响应关闭 |
| workspace path 校验、命令执行、事件解析 | 支持库原子能力 + 模块门面 | 路径/进程/事件转换是可复用原子能力；模块负责把它们组合成会话流程 |
| Cloud/Local、provider、容器、桌面、端口和密钥引用 | 项目适配层 | 只绑定环境、版本、权限、路径、密钥引用和中文别名，不下沉到正式代码 |
| 事件账本、租约、取消确认、资源终态 | 运行核心/平台控制面 | Canvas 的 store、socket close 和 `queued` 返回都不足以承担这些权威事实 |

决策规则：能被两个以上项目复用且只涉及一个外部边界的，优先做支持库原子能力；需要组合多个能力形成完整用户流程的，做模块库；只因部署环境、版本、路径、权限或密钥不同的，留在项目适配层；任何需要写权威账本、分配租约、回收资源或裁决并发的，不放在前端适配器中。

## 25. 本次源码同步后的验证状态

```text
git fetch origin main && git merge --ff-only origin/main
  -> origin/main = bad1687dec93c5b3edbef837ab2dc12638964031 (exit 0)
codegraph sync
  -> 39 changed files; 1,898 files / 20,142 nodes / 54,750 edges (exit 0)
codegraph status
  -> index is up to date (exit 0)
git diff --check -- ARCHITECTURE.md
  -> 待平台文档目录回写后执行
```

本次同步仍未执行 `npm install`、`npm run lint`、`npm run test`、真实 Agent Server、Docker、Helm、Cloud、WebSocket 或 provider 验证。远程版本更新带来的新测试和启动脚本已记录为源码证据，但只有对应命令实际退出码为 0 后，才能提升到运行验证等级。
