# OpenCode 架构建档

> 本文是对当前本地源码快照的全量静态架构记录，不是实现计划，也不把规格文档当成已实现事实。
>
> - 仓库：`~/Documents/Agent/github 源码参考/10_agent_platform_reference/01_成品Agent平台/opencode`
> - 当前代码基线：`ba72a6ff2b62aaf614b8e745193e86a51be6142c`（`dev` 与 `origin/dev`，2026-08-21）
> - 许可证：MIT；语言/运行时：TypeScript ESM monorepo，Bun workspace
> - 读取范围：根 README、根及局部 AGENTS、CONTEXT/specs、依赖清单、入口、核心模型、事件/存储、LLM、权限/工具、HTTP API、CLI/TUI/UI、SDK 和测试；另对最新版本做增量复核。
> - 本次边界：只新增本文件；不改源码、依赖、测试、配置，不安装依赖、不启动服务、不构建、不运行测试、不提交 Git。

## 1. 项目定位

OpenCode 是一个以 CLI/TUI 为主、同时提供 Web、Desktop、HTTP Server、Promise/Effect Client、嵌入式 SDK、插件/MCP/LSP 扩展面的开源 AI coding agent 平台。它把一个 coding session 拆成：

1. 受 Schema/Protocol 约束的公共契约；
2. Location/Project 作用域的运行时服务；
3. SQLite 持久化的 Session、消息、事件和投影；
4. Provider/Model → LLM 流式请求 → Tool settlement → durable history 的闭环；
5. 多种交互表面通过 HTTP API/SDK 或进程内服务复用能力。

当前仓库不是单一运行时：**V1/legacy 的 `packages/opencode` 主链路与 V2/current 的 `packages/core + packages/server + packages/protocol + packages/client + packages/sdk-next` 并行存在**。阅读任何行为时必须注明 V1 或 V2，不能把设计规格或 V2 代码的状态套到 V1。

### 1.1 最新版本增量审计

2026-08-22 核对本地 `dev` 与 `origin/dev`，两者均指向 `ba72a6ff2b62aaf614b8e745193e86a51be6142c`，无提交差异。此前独立工作区
`~/Documents/Agent/源码研究工作区/opencode-最新版本` 读取最新提交，未覆盖本项目原工作树。
从 `67a04787` 到 `b155b156` 共变更 787 个文件；大量变化属于前端、多语言、发布版本和供应商适配，以下只记录影响底座判断的源码证据：

- `packages/core/src/repository.ts` 与 `repository-cache.ts` 已形成远程仓库引用解析和缓存闭环：支持 GitHub `owner/repo` 简写、远程 URL、host/path、分支校验；缓存按 remote + branch 分目录；刷新时加文件锁、fetch、切换远程分支并 hard reset，返回 `cached/cloned/refreshed` 和结构化错误。
- `packages/core/src/session/projector.ts` 继续把 `SessionEvent` 投影到 SQLite 的 Session、Message、Part、Input 等读模型；消息采用 Schema 编解码，工具/assistant 状态更新和 token/cost 累加都在投影边界处理，旧 assistant 未完成行会被更新轮次抑制，避免错误恢复旧执行。
- `packages/core/src/session/runner/llm.ts` 已能把 V2 历史、Context Epoch、Agent、Model、ToolRegistry、Snapshot 和 Compaction 组装成一次明确的 `llm.stream(request)`；工具调用先持久化并执行，再等待 tool fibers、重载投影历史后继续下一轮；最后一步关闭工具并注入最大步数提示。
- 最新 runner 的源码注释仍明确列出未闭环项：集群级 durable ownership、durable run status/recovery、provider retry/watchdog、完整插件/MCP/structured-output 工具策略、取消结算、增量 snapshot/patch、最终状态维护和后台清理。因此不能把 V2 目标规格写成生产能力全部完成。
- `packages/opencode/src/provider/transform.ts` 的 Provider 适配继续承担协议边界：统一清理孤立 surrogate、限制输出 token、处理图片/音频/视频/PDF modality、Anthropic/Bedrock 空消息、OpenAI Responses 加密 reasoning 状态，并按 npm Provider 映射 `providerOptions` 键。该类兼容逻辑应留在适配层，不能渗入正式业务语义。

**最新版本裁决：** OpenCode 的 durable event + projector + 输入 admission + 有界 tool settlement + 独立仓库缓存，是可吸收的底座模式；V2 集群恢复、完整 provider/tool 覆盖和 post-run maintenance 仍列为待核，不能当作已完成工业闭环。

## 2. 总体文本流程图

### 2.1 入口与运行时总览

```text
用户 / 自动化调用方
   │
   ├─ `opencode` CLI：packages/opencode/src/index.ts
   │      ├─ 默认 TUI：Worker/RPC → @opencode-ai/tui → SDK/事件
   │      ├─ `run`：单次 prompt / JSON event 输出 / mini 交互
   │      ├─ `serve`：启动 HTTP listener
   │      └─ `web`：启动 HTTP listener 并打开 Web UI
   │
   ├─ Web App：packages/app（SolidJS + Vite）
   ├─ Desktop：packages/desktop（Electron main/preload/renderer，复用 app）
   ├─ HTTP Client：packages/client（Promise 或 Effect）
   └─ Embedded SDK：packages/sdk-next（同一进程内的 HTTP router，无监听/网络）
            │
            ▼
   公共契约层：Schema → Protocol → Server API
            │
            ▼
   路由/中间件：认证、Schema 错误、Location、Session Location、授权
            │
            ▼
   服务组装：Server handlers → Core Session / Project / Provider / Permission / Tool
            │
            ▼
   持久化与事件：SQLite + EventV2 durable log + projector + PubSub
            │
            ▼
   Session runner（V2）或 SessionPrompt/Processor（V1）
            │
            ▼
   LLM route（@opencode-ai/llm native）或 AI SDK
            │
            ▼
   provider stream：text / reasoning / tool-call / tool-result / finish / error
            │
            ├─ 本地工具：权限 → decode → execute → encode → bound output → durable result
            ├─ provider-hosted tool：保留 providerExecuted，不走本地 dispatcher
            └─ 文件变更：snapshot 影子 Git → patch/file diff
            │
            ▼
   durable message/event projection → HTTP SSE / TUI / Web / Desktop / SDK consumer
```

### 2.2 V2 Session：输入 admission 与执行分离

```text
sessions.create({ location, id?, agent?, model? })
   │
   ▼
SessionV2.Service.create
   ├─ 解析 Location → Project
   ├─ 生成/复用 Session ID
   └─ publish session.created（durable）
         └─ SessionProjector → session 表

sessions.prompt({ sessionID, id?, prompt, delivery?, resume? })
   │
   ▼
SessionV2.Service.prompt（uninterruptible）
   ├─ 校验 Session 存在
   ├─ 生成/复用 message ID
   ├─ SessionInput.admit
   │    └─ publish session.next.prompt.admitted
   │         └─ session_input(admitted_seq, promoted_seq=NULL)
   ├─ 相同 ID + 相同内容 → 返回同一 admission receipt
   ├─ 相同 ID + Session/prompt/delivery 不同 → PromptConflictError
   └─ resume !== false → SessionExecution.wake(sessionID)

SessionExecution（进程全局）
   │  SessionRunCoordinator：同一 Session 串行，不同 Session 可并发；wake 合并
   ▼
SessionStore.get(sessionID) → LocationServiceMap.get(session.location)
   ▼
Location-scoped SessionRunner.run({ sessionID, force })
   ├─ initialize/reconcile Context Epoch
   ├─ promote steer；空闲边界 FIFO promote 一个 queue
   ├─ reload projected history
   ├─ resolve Agent + Catalog Model + effective ToolRegistry
   ├─ 一次显式 llm.stream(request)
   │    ├─ provider event → LLMEventPublisher → durable Session events
   │    ├─ local tool-call → ToolRegistry.settle → typed result / bounded output
   │    └─ stream 结束后 await 所有 tool fibers
   ├─ step ended → usage / snapshot / file diff
   └─ 有 continuation → reload history → 下一 provider turn
         │
         ├─ Context overflow → 一次 compaction → fresh Context Epoch → 重试逻辑
         └─ idle/error/interrupted → durable projected state + live notifications
```

`specs/v2/session.md`描述了该目标闭环；源码证据显示其核心 admission、durable event、projector、local runner 已存在，但仍有明确的 `OperationUnavailableError` 和 TODO/follow-up，见“未确认项与缺口”。

### 2.3 V1/legacy Session：消息处理主链路

```text
HTTP/CLI/TUI prompt
   ▼
packages/opencode/src/session/prompt.ts
   ▼
SessionPrompt / SessionProcessor
   ├─ load instruction + AGENTS.md
   ├─ load reminders / plan-build mode
   ├─ MessageV2 / SQLite history → provider ModelMessage[]
   └─ LLM.Service.stream
         ├─ default：AI SDK streamText
         └─ experimental native：@opencode-ai/llm LLMClient.stream
                  │
                  ▼
          SessionProcessor.handleEvent
          ├─ text/reasoning part 增量写入
          ├─ tool-call：pending → running；权限/doom_loop 检查
          ├─ tool-result/error：completed/error
          ├─ step-finish：usage、snapshot patch、summary、overflow 判定
          └─ interrupted/error：cleanup 未完成 tool、assistant、status
                  │
                  ▼
          compaction / retry / continue / stop
                  │
                  ▼
          EventV2Bridge → TUI/Web/SDK 事件与旧版投影
```

V1 主应用组合位于 `packages/opencode/src/effect/app-runtime.ts`：Database、Config、Provider、Agent、Permission、Session、SessionProcessor、LLM、MCP、LSP、ToolRegistry、Snapshot 等以 `LayerNode`/ManagedRuntime 组装。

## 3. 真实分层与依赖方向

### 3.1 契约与协议

| 层 | 真实包/入口 | 所有权与边界 |
|---|---|---|
| Schema leaf | `packages/schema` | 浏览器安全、可序列化的 ID、Session/Message/Event/Location/Model/Provider/Permission 等契约；不放服务、数据库、注册表或宿主副作用。`packages/schema/AGENTS.md`明确要求 `schema <- protocol <- server`。|
| Protocol | `packages/protocol` | 用 Effect HttpApi 组合 `/api/...` endpoint、query/payload、错误、middleware 位置、事件与分页 cursor；只依赖 Schema + Effect。|
| Server API | `packages/server` | 给 Protocol 注入具体 Location/SessionLocation middleware key，组合 handlers 与 Core services；`packages/server/src/api.ts`导出 `Api`。|
| Legacy/experimental API | `packages/opencode/src/server/routes/instance/httpapi` | 另一套由 `InstanceHttpApi`/`RootHttpApi`/`OpenCodeHttpApi`组成的旧/实验 HTTP surface，仍大量使用 `SessionV1`/V1 permission。|

### 3.2 运行时核心

| 层 | 真实包/目录 | 主要职责 |
|---|---|---|
| Core runtime | `packages/core` | Effect 服务、Location/Project、Database、EventV2、V2 Session、Context Epoch、Runner、PermissionV2、ToolRegistry、Snapshot、PTY、Provider/Model catalog、插件 host。|
| LLM abstraction | `packages/llm` | Effect Schema-first 的 `LLMRequest`/Message/LLMEvent；Route = Protocol + Endpoint + Auth + Framing；`LLMClient.stream/generate/prepare`；不持有 Session 权限/插件/telemetry。|
| Legacy application | `packages/opencode` | CLI/HTTP listener 组装、V1 SessionPrompt/Processor、V1 Permission、工具实现、MCP/LSP、provider auth/config、snapshot、share、旧兼容 API。|
| Storage adapters | `effect-drizzle-sqlite`、`effect-sqlite-node`、`packages/core/src/database` | Drizzle over SQLite 的 Effect 适配；Bun/Node 条件入口。|

### 3.3 传输与消费表面

| 表面 | 真实包 | 关系 |
|---|---|---|
| Promise client | `packages/client/src/generated` | 从 `ClientApi` 生成，零 Effect；手写/生成 runtime 处理 fetch、HTTP status、JSON、SSE、`ClientError`。|
| Effect client | `packages/client/src/generated-effect`、`src/effect.ts` | 从同一 Protocol projection 生成，依赖 Effect + Schema + Protocol，不依赖 Core/Server；bundle boundary test 固化该约束。|
| Embedded SDK | `packages/sdk-next/src/opencode.ts` | 创建 Server router 的 in-memory web handler，再以 Effect HttpClient 注入 fetch；复用同一 handlers/codecs/errors，无 listener、无网络；另暴露 `tools.register`。|
| Legacy SDK | `packages/sdk`、`packages/sdk/js` | 旧生成 SDK，V1/兼容表面；根 AGENTS要求变更 public Protocol/Server HttpApi 后由 `packages/client`生成新 SDK，legacy JS SDK另行脚本生成。|
| TUI | `packages/tui` | OpenTUI/Solid 终端 UI；SDKProvider、Sync、Permission、Project、Event、Plugin runtime；由 `packages/opencode` Worker/RPC 或外部 server 提供 transport。|
| Web app | `packages/app` | SolidJS + Vite，使用 client/core/schema/session-ui/ui 等；独立 unit/browser/e2e 测试。|
| Desktop | `packages/desktop` | Electron + electron-vite；renderer 只调用 preload 的 `window.api`，main IPC 在 `src/main/ipc.ts`注册；复用 app/ui。|

### 3.4 依赖图

```text
@opencode-ai/schema
        │
        ▼
@opencode-ai/protocol ────────────────┐
        │                              │
        ▼                              │
@opencode-ai/server                    │
        │                              │
        ├──────────────┐               │
        ▼              ▼               │
packages/opencode   sdk-next ◀─ client ┘
        │              │        ▲
        ▼              │        │
      core ────────► server ────┘
        │
        ├─ llm
        ├─ schema
        ├─ plugin
        └─ sqlite/drizzle/effect

TUI/Web/Desktop 是消费表面；legacy opencode 同时消费旧 SDK 和 current packages。
```

根 `AGENTS.md`的硬约束是：Schema → Core/Protocol → Server；Client runtime 不得依赖 Core/Server；`sdk-next`才允许组合 Client、Core、Server。该方向是实际 import boundary test 的验收对象，而不是只存在于文档中的偏好。

## 4. 目录地图（真实重点）

```text
opencode/
├── package.json                  # Bun 1.3.14 工作区、根脚本；根测试明确拒绝执行
├── bun.lock                      # 已存在的锁文件（本次未读取/修改依赖）
├── README.md                     # 产品定位、安装、Agent、Desktop、贡献入口
├── AGENTS.md                     # 依赖方向、生成、测试/typecheck、V2 Session 约束
├── CONTEXT.md                    # Session Runtime / Client / SDK 术语与设计关系
├── specs/v2/                     # V2 config/session/instructions/provider/tools 等设计规格
├── specs/effect/                 # Effect 迁移约定
├── packages/
│   ├── schema/                   # 浏览器安全的契约
│   ├── protocol/                 # 类型化 HttpApi 分组、错误和中间件位置
│   ├── server/                   # 当前 V2 处理器、路由和中间件
│   ├── core/                     # Effect 运行时、V2 Session、事件、SQLite、工具
│   ├── llm/                      # 原生 LLM 路由、协议、Provider、流事件
│   ├── opencode/                 # legacy/兼容主程序、CLI、V1 session、旧 HttpApi
│   ├── client/                   # Promise/Effect 生成客户端
│   ├── sdk-next/                 # 嵌入式当前宿主
│   ├── sdk/js/                   # 旧版 JS SDK
│   ├── cli/                      # 独立的新 CLI/service 命令框架
│   ├── tui/                      # OpenTUI 终端界面
│   ├── app/                      # SolidJS/Vite 网页应用
│   ├── desktop/                  # Electron 桌面外壳
│   ├── ui/, session-ui/          # UI 基础组件和会话界面
│   ├── plugin/, mcp/lsp 相关实现  # 扩展面（部分位于 opencode/core）
│   ├── codemode/, containers/     # 代码执行/容器相关包
│   ├── effect-*                  # SQLite/Drizzle Effect 适配器
│   └── console/, stats/, web/...  # 控制台、统计、文档、营销及辅助界面
```

按当前 tracked TypeScript/TSX 文件的静态计数，重点包规模约为：`opencode` 664、`core` 477、`app` 532、`tui` 204、`ui` 199、`session-ui` 94、`llm` 105、`schema` 71、`client` 16、`protocol` 24、`server` 29、`sdk-next` 6；这是源码地图，不等价于运行时加载量。

## 5. 核心数据模型与持久化

### 5.1 公共领域模型

- **Location**：`{ directory: AbsolutePath, workspaceID? }`；Location middleware 把 request query/header 解析为 Location，再从 `LocationServiceMap`提供 Location-scoped services。
- **Project**：`id/worktree/vcs/name/icon/commands/time/sandboxes`；Session 创建时按 Location directory resolve project，并确保 Project 投影存在。
- **Session**：V2 `Session.Info`包含 `id/parentID/projectID/agent/model/cost/tokens/time/title/location/subpath/revert`；V1 `SessionInfo`仍在 legacy 读写路径中使用更多兼容字段。
- **Model/Provider**：Model.Ref = `{ id, providerID, variant? }`；Catalog 维护 provider/model capabilities、endpoint、request options、variants、limits、cost、availability。Provider/Model ID 是品牌化 Schema 类型。
- **Session input**：`Admitted = { admittedSeq, id, sessionID, prompt, delivery, timeCreated, promotedSeq? }`；`delivery`区分 `steer` 与 `queue`。
- **Session message**：V2 union 包含 `user/system/synthetic/assistant/compaction/agent-switched/model-switched/shell`；Assistant content 包含 text/reasoning/tool，Tool state 为 pending/running/completed/error。
- **Event**：Schema 定义 `{ id, type, data, durable? }`；durable event 附带 `aggregateID/seq/version`，通过 manifest 区分 latest 与 versioned durable definition。
- **Permission**：V2 Rule = `{ action, resource, effect: allow|deny|ask }`；Request 关联 session、资源、保存规则与 tool source；V1 则是 `{ permission, pattern, action }`，两套并存。

### 5.2 SQLite 与事件表

`packages/core/src/database/database.ts`初始化 SQLite：WAL、`synchronous=NORMAL`、busy timeout、cache size、foreign keys，并调用 `DatabaseMigration.apply`。数据库路径由 `OPENCODE_DB`或 Global data path 决定；测试可切到 `:memory:`或临时路径。

核心 Drizzle 表（源码直接声明于 `packages/core/src/**/*.sql.ts`）：

| 表 | 关键字段/用途 |
|---|---|
| `project` | Project 投影与 worktree/VCS 元数据。|
| `session` | Session identity、project/workspace/parent、directory、title、agent/model、token/cost、revert、timestamps。|
| `message`、`part` | V1/兼容消息与 part 投影。|
| `todo` | Session todo，`(session_id, position)`复合主键。|
| `session_message` | V2 projected message；`session_id + seq`唯一，按 aggregate sequence 读取。|
| `session_input` | V2 durable inbox；`admitted_seq`、可空 `promoted_seq`、delivery；有 pending/admission/promoted 索引。|
| `session_context_epoch` | Session baseline、Context Snapshot、baseline sequence；Compaction/move 时重置或替换。|
| `event_sequence` | 每个 aggregate 最新 seq 与可选 replay owner。|
| `event` | durable event log；`aggregate_id + seq`唯一，type/data JSON；外键级联到 event_sequence。|
| `permission` | project-scoped saved permission，`project_id + action + resource`唯一。|
| `workspace`、credential、account、share 等 | control-plane/认证/分享等配套投影。|

### 5.3 Durable event 与 projector

```text
EventV2.publish(definition, data)
   ▼
若 definition.durable：立即事务
   ├─ 读取 event_sequence.latest
   ├─ 校验 replay owner / seq / aggregate
   ├─ 在同一事务运行 registered projectors
   ├─ 可选 commit hook（例如 Context Snapshot advance）
   ├─ upsert event_sequence(seq, owner)
   └─ insert event(id, aggregate_id, seq, versioned type, JSON data)
   ▼
事务提交后 notify：typed PubSub + all PubSub + durable aggregate wake
   ▼
readAggregate / durable stream：SQLite 历史 + sliding dirty wake 后增量重读
```

`SessionProjector`注册 Created/Updated/PromptAdmitted/Prompted/Step/Tool/Text/Reasoning/Compaction/Revert 等 projector，把 durable event 映射到 Session、SessionInput、SessionMessage、Context Epoch 等读模型。事件 replay 依靠 aggregate sequence，不依靠内存通知；`sessions.events`是“历史重放 + 新 durable event tail”，live-only fragment 不进入该可重放流。

## 6. 关键数据流

### 6.1 Prompt admission → provider turn

1. Client/Server handler decode `PromptInput.Prompt`、Session ID、delivery、resume。
2. `SessionV2.prompt`以 uninterruptible effect 校验 Session，生成或复用 message ID。
3. `SessionInput.admit`先查现存 admission；新记录发布 `PromptAdmitted`并由 projector 写入 `session_input`。
4. `resume !== false`只做 advisory wake；它不是 durable execution identity。
5. Runner 在 safe provider-turn boundary 读取 SessionInput：批量 promote steer；空闲时最多 promote 一个 queue，再重评 continuation。
6. Projector 对 Prompted 写入 `session_message`并设置 `promoted_seq`；模型看到的是 projected history，不是尚未 promoted 的 inbox。
7. Runner 解析 System Context、Agent、Model、工具目录，创建一个 `LLM.request`，只调用一次 `llm.stream(request)`。
8. LLM events 经 publisher 追加 durable Session event，SessionProjector 更新可查询 message/read model。

### 6.2 Tool settlement

```text
LLM tool-call
  ▼
ToolRegistry.materialize(agent permissions)
  ├─ whole-tool deny → 不广告 definition
  └─ 仍由 captured registration settle，registry 不承担权限授权
  ▼
Tool.make canonical value
  ├─ decode input Schema
  ├─ execute(input, { sessionID, agent, assistantMessageID, toolCallID })
  ├─ encode output Schema
  ├─ optional structured output
  ├─ toModelOutput(text/file)
  └─ ToolOutputStore.bound(max lines 或 max bytes)
          ├─ 小结果 → ToolResultValue + model content
          └─ 超限 → 有界 head/tail + managed output path
  ▼
Session event：Tool.Called / Tool.Success / Tool.Failed
  ▼
await all started tool fibers → reload history → continuation provider turn
```

V1 的 `packages/opencode/src/tool/tool.ts`与 V2 `packages/core/src/tool/tool.ts`不是同一个定义接口：V1 使用 `Tool.define`和 `ctx.ask`，V2 使用 opaque `Tool.make`、`ToolRegistry`和 Location-scoped registration。V2 Core Tool AGENTS 明确要求不要再引入第二套 executable representation。

### 6.3 Permission flow

- V1：`Permission.evaluate(permission, pattern, ...rulesets)`使用 `findLast`，后写规则覆盖前写；无命中默认 `ask`；`once/always/reject`通过 Deferred；always 可写入当前 session approved state。
- V2：`PermissionV2.evaluate(action, resource, ...rulesets)`同样后写覆盖；无 agent permissions 时注入全局 deny；saved project rules作为 allow 合并；`ask/assert`创建 pending request；reply always 可写 `permission`表并级联放行可被 saved rules 覆盖的 pending。
- 工具 definition visibility 只代表目录过滤，不替代执行授权；真实授权由叶子工具闭包获取 Permission service 并执行。
- Legacy `--auto/--yolo/--dangerously-skip-permissions`在 CLI 层转为自动批准语义；这是 V1 CLI 参数，不应误标为 V2 默认行为。

### 6.4 Context Epoch 与 compaction

```text
Location-scoped Context Sources
  ├─ environment/date
  ├─ global/upward project AGENTS.md（当前实现 slice）
  ├─ system-context registry built-ins
  └─ selected-agent skill/reference guidance
         ▼
SystemContext.combine → initialize/reconcile/replace
         ▼
session_context_epoch(baseline, snapshot, baseline_seq)
         ├─ unchanged：复用 baseline
         ├─ updated：发布一个 chronological ContextUpdated event，commit 同步 snapshot
         ├─ replacement ready：以最新 baseline_seq替换 epoch
         └─ blocked：保留旧状态，不带不完整 baseline 运行
         ▼
SessionHistory.entriesForRunner(baseline_seq)
         ▼
LLM system baseline + chronological messages + projected conversation
```

V1 `SessionProcessor`按 token/overflow 触发 compaction，保留 tail/summary；V2 `SessionRunner`在 provider turn 前估算 request/context budget，支持 automatic/overflow-triggered compaction，完成 checkpoint 后重建 Context Epoch。两套 compaction 代码与状态模型并存。

### 6.5 文件变更证据

Snapshot 在 V1 `packages/opencode/src/snapshot`及 V2 Core `snapshot`提供工作区变更追踪：为每个 project/worktree 使用影子 Git 仓库，capture start/end，生成 tree/hash，再生成 FileDiff；V1 Processor 在 step-finish/cleanup 时把 patch part 写进 Session。该机制是文件变更证据与 revert 的来源，不等同于业务数据库事务回滚。

## 7. API、CLI 与 SDK

### 7.1 Current Protocol/Server `/api` surface

权威结构是 `packages/protocol/src/api.ts`的 group composition，Server 以具体 middleware 构造 `Api`；`packages/client/src/contract.ts`再投影为 client group 名称。主要公共分组：

- `health`：健康检查。
- `location`：解析 directory/workspace location。
- `agents`、`models`、`providers`：Agent 与 Provider/Model catalog。
- `sessions`：V2 Session CRUD/分页、active、switchAgent、switchModel、prompt、compact、wait、revert stage/clear/commit、context、history、durable SSE events、interrupt、message。
- `messages`：Session message 分页读取。
- `integrations`、`credentials`：provider integration/auth credential。
- `permissions`：request/saved permission 与 Session permission reply。
- `files`、`commands`、`skills`、`references`：Location-scoped filesystem/command/skill/reference 查询。
- `events`：instance-wide live SSE（无 Session durable replay 保证）。
- `ptys`：PTY CRUD；PTY WebSocket/连接票据为特殊 transport。
- `questions`：question list/reply/reject。
- `projectCopies`：实验性 project copy。

V2 Session 代表性 wire routes（`packages/protocol/src/groups/session.ts`）：

```text
GET  /api/session
POST /api/session
GET  /api/session/active
GET  /api/session/:sessionID
POST /api/session/:sessionID/agent
POST /api/session/:sessionID/model
POST /api/session/:sessionID/prompt
POST /api/session/:sessionID/compact
POST /api/session/:sessionID/wait
POST /api/session/:sessionID/revert/stage
POST /api/session/:sessionID/revert/clear
POST /api/session/:sessionID/revert/commit
GET  /api/session/:sessionID/context
GET  /api/session/:sessionID/history?after=&limit=
GET  /api/session/:sessionID/event?after=   # SSE：历史 durable + live durable tail
POST /api/session/:sessionID/interrupt
GET  /api/session/:sessionID/message/:messageID
```

Handler 的职责是 domain error → declared HTTP error 的边界转换。例如 `Session.NotFoundError`映射为 `SessionNotFoundError`，prompt ID 冲突映射为 `ConflictError`，当前还不可用的 compact/wait 映射为 `ServiceUnavailableError`。

### 7.2 Legacy/experimental HTTP API

`packages/opencode/src/server/routes/instance/httpapi/groups/session.ts`仍暴露旧 `/session` surface，包括：

```text
/session、/session/status、/session/:id、/children、/todo、/diff
/session/:id/message、/message/:messageID
POST /session（create）、PATCH /session/:id、DELETE /session/:id
POST /session/:id/fork、/abort、/init、/share、/summarize
POST /session/:id/message（prompt）、/prompt_async、/command、/shell
POST /session/:id/revert、/unrevert
POST /session/:id/permissions/:permissionID
DELETE/PATCH message/part
```

它的 handlers 直接依赖 `packages/opencode`内的 V1 `SessionPrompt`、`SessionCompaction`、`SessionRevert`、`Permission`、`EventV2Bridge`等服务。文档或客户端看到同名 session 能力时必须核对 path 前缀和使用的 handler 包。

### 7.3 CLI

`packages/opencode/src/index.ts`以 yargs 注册主命令：`acp`、`mcp`、TUI default、`attach`、`run`、`generate`、`debug`、`account/console`、`providers`、`agent`、`upgrade`、`uninstall`、`serve`、`web`、`models`、`stats`、`export`、`import`、`github`、`pr`、`session`、`plugin`、`db`。

重点入口：

- 默认 `$0 [project]`：`packages/opencode/src/cli/cmd/tui.ts`启动 Worker/RPC；本地模式把 fetch 映射到 worker/server，外部网络参数则连接 listener。
- `run [message..]`：非交互单 prompt；支持 `--continue/--session/--fork`、`--model provider/model`、`--agent`、`--format json`、文件附件、`--attach`、`--auto/--yolo`；事件订阅按 session 输出 text/tool/step/error，直至 idle。
- `run --mini`：直接交互模式；本地 in-process server 或 `--attach`远端 server。
- `serve`：`Server.listen(opts)`，headless HTTP listener；无密码时源码会明确输出 unsecured warning。
- `web`：同样 listen，然后打开 Web interface。
- 独立 `packages/cli/src/index.ts`是另一套 Effect CLI/service framework，包含 serve/service/migrate/api/debug 等命令，不应与 `packages/opencode`的 yargs 入口混为一个实现。

### 7.4 Promise/Effect Client

- `@opencode-ai/client`：生成脚本 `packages/client/script/build.ts`从 `ClientApi`编译 contract，一次生成 Promise 与 Effect 两个输出。Promise 根入口不带 Effect/Core/Server runtime dependency，`make({ baseUrl, fetch?, headers? })`同步构造、按调用执行 fetch，声明的 HTTP 错误保留结构化 body，基础设施错误统一 `ClientError`。
- SSE：Promise client 返回 lazy `AsyncIterable`，第一次 `next()`才建立连接；Effect client 返回 `Stream`。两者不自动 reconnect。
- `@opencode-ai/client/effect`：使用 Effect `HttpApiClient`，返回 decoded Schema values；依赖仅 Effect/Schema/Protocol；`sessions.events`与 `events.subscribe`分别代表 durable Session stream 和 instance-wide live stream。
- 生成文件 `src/generated`/`src/generated-effect`禁止直接编辑；变更 public Protocol/Server HttpApi 后应在 `packages/client`执行 `bun run generate`，这是维护说明，不是本次执行动作。

### 7.5 Embedded SDK

`packages/sdk-next/src/opencode.ts`的 `OpenCode.create()`：

1. 建立 Effect Scope/MemoMap；
2. 构造 ApplicationTools/PermissionSaved 等 host-level services；
3. `createEmbeddedRoutes()`构造与 Server 相同的 router/handlers；
4. `HttpRouter.toWebHandler`建立进程内 handler；
5. 将 handler 注入 Effect FetchHttpClient，复用生成的 Effect Client；
6. 返回扁平的 `sessions`、`events`等 client capability 和 `tools.register`；Scope close 时释放 router、DB、services、fibers、registrations。

SDK 测试明确验证：embedded client 使用真实 router/handlers、Session admission 与 durable event、Location-owned runner events、不同 embedded hosts 的 live notification 隔离、Layer service 构造；这证明它不是绕过 HTTP 边界的第二套业务实现。

## 8. 技术栈

| 分类 | 真实技术 |
|---|---|
| 语言/模块 | TypeScript、ESM、Bun 1.3.14 workspace、部分 Node/Electron 环境条件分支 |
| Effect runtime | `effect` 4 beta、Effect Schema、Layer/Context/Scope/Fiber/Stream/PubSub/HttpApi |
| HTTP | Effect unstable HttpApi/HttpRouter/HttpApiBuilder、Node HTTP server；Hono/OpenAPI 仍在依赖面/legacy 生态中 |
| 数据库 | SQLite；Drizzle ORM/Drizzle Kit；Effect SQLite adapters；WAL + migration |
| LLM | 自研 `@opencode-ai/llm`（Route/Protocol/Endpoint/Auth/Framing/Transport）、Vercel AI SDK 6、各家 `@ai-sdk/*` provider、GitLab workflow provider |
| Schema/serialization | Effect Schema、JSON codecs、branded IDs、OpenAPI from HttpApi |
| 工具/执行 | Bun/Node child process、`cross-spawn`、PTY、tree-sitter bash/powershell、ripgrep、Git snapshot |
| UI | SolidJS、OpenTUI、Vite、Tailwind CSS、Shiki/Marked、Playwright、Storybook |
| Desktop | Electron 42、electron-vite、electron-builder、preload IPC |
| 扩展 | Plugin host、MCP SDK/OAuth、LSP、ACP、provider plugins、application/location tool registrations |
| 可观测性 | Effect OpenTelemetry、OpenTelemetry SDK/exporter、Sentry（Web/Desktop/App dependency surface） |
| 依赖管理 | Bun workspace/catalog/lockfile、patches、Turbo、oxlint、Prettier、Husky |

根 `package.json`的 catalog 明确包含 Effect、Drizzle、AI SDK、Hono、Solid、Vite、Playwright、TypeScript、Electron 等版本；本次未安装或解析依赖。

## 9. 测试与验证结构

### 9.1 仓库约束

- 根 `package.json`的 `test` 是故意输出 “do not run tests from root” 并 exit 1；根 AGENTS要求从 package directory 执行测试。
- Typecheck 使用 package 的 `bun typecheck`/`tsgo --noEmit`，不直接调用 `tsc`。
- 测试优先 `testEffect(...)`、Effect Layer、scoped temp directory；server 测试优先 `NodeHttpServer.layerTest`和相对 HttpClient；避免把 `Bun.serve`当作 Effect middleware 测试后端。
- LLM provider tests 默认 fixture/cassette replay；真实 provider 调用需要 `RECORD=true`和 API key，本次未触发。

### 9.2 已看到的测试层次

按 `git ls-files`对 tracked TypeScript/TSX 的静态计数，重点测试树约为：`packages/core/test` 157、`packages/opencode/test` 289、`packages/tui/test` 51、`packages/app/test-browser` 12、`packages/app/e2e` 107、`packages/client/test` 4、`packages/sdk-next/test` 2、`packages/schema/test` 6、`packages/protocol/test` 1；计数只用于地图，不表示测试已通过。

- **Schema contract tests**：optional encode/decode、公共 identifier 唯一性、当前契约避免 `Schema.Any`/mutable wrapper、V1 event isolation。
- **Core/LLM unit tests**：Schema、provider route、tool runtime、session/event/history、SQLite repository、Effect services。
- **Legacy opencode tests**：Session processor/prompt/message/compaction/retry/LLM、tool read/edit/shell/task/skill/truncation、snapshot/storage/project、provider、MCP/LSP、server HTTP API。
- **权限与安全行为**：V1 shell 测试验证 bash pattern、always arity、外部目录路径、PowerShell AST/路径；已有历史研究文档补充 `findLast`、settle、output bound、snapshot 结论。
- **HTTP/OpenAPI**：`httpapi-public-openapi.test.ts`验证 `/api` auth response、event union/SSE schema、typed errors、required bodies、provider/model/session/permission/question/PTY routes；server AGENTS要求 middleware order 与 tiny probe。
- **SDK/import boundary**：client root 必须无 Effect/Schema/Protocol/Core/Server runtime 输入；effect entry 允许 Effect/Schema/Protocol 但拒绝 Core/Server；sdk-next bundle 必须包含 client/core/server；embedded tests 走真实 in-memory router。
- **UI**：App unit/browser、Playwright e2e、性能稳定性和 timeline tests；TUI component/app lifecycle/CLI sync tests；UI/Storybook stories。

### 9.3 本次验证状态

本次只做静态读取与文件审计，按用户要求**未执行**安装、构建、typecheck、测试、启动 server/TUI 或 runtime probe。因此本文没有“测试通过”结论；测试章节记录的是源码中存在的验证意图与测试拓扑。

## 10. 未确认项、实现缺口与阅读边界

以下项目是源码明确显示的未完成、并行迁移或需要后续核实的内容，不是猜测：

1. **V2 operation gaps**：`packages/core/src/session.ts`的 `shell`、`skill`、`compact`、`wait`当前返回 `OperationUnavailableError`；current Server handler 相应把 compact/wait 转成 503 ServiceUnavailable。不能把 Protocol endpoint 存在写成能力已闭环。
2. **V2 runner follow-ups**：`packages/core/src/session/runner/llm.ts`注释列出 clustered ownership、durable status/recovery、provider retry/watchdog、完整 plugin/MCP/structured-output tool policy、stream delta coalescing、post-run maintenance 等未完成项。
3. **Context parity**：`specs/v2/session.md`将 configured/remote/nested instructions、provider-family baseline、prompt overrides、plugin transforms、structured-output policy、native template/@ mention、agent/reference expansion 等标为 partial/missing；当前只证明已有实现 slice，不能证明完整 V1 parity。
4. **V1/V2 并存**：`packages/opencode`的实际默认 `run/TUI/HTTP`链路仍包含 V1 `SessionPrompt`/`SessionProcessor`/V1 Permission；V2 current packages 是迁移目标和独立 API，是否所有产品表面都已切换未在当前审计 runtime 验证。
5. **Generated artifacts**：Client generated files是编译产物；README/AGENTS规定 API 变更后 regenerate，但本次没有执行 generate，也没有确认生成物与所有当前 Protocol 定义的 drift。
6. **Legacy SDK surface**：仓库同时有 `packages/sdk`、`packages/sdk/js`、`packages/client`、`sdk-next`；legacy SDK 与 current generated client 的命名、返回 envelope、错误模型不可自动等同。
7. **Network/Provider coverage**：`specs/v2/provider-model.md`明确当前 native runner 只覆盖有限 OpenAI Responses/Completions、Anthropic、指定 AI SDK 路由；Google/Azure/Bedrock/OpenRouter/GitHub Copilot 等特定行为仍是 future provider slices。V1 AI SDK provider surface 更宽，但当前审计未逐个 provider runtime 验证。
8. **Bash security boundary**：V2 specs明确 bash 使用宿主 filesystem/process/network authority；绝对命令参数扫描是 advisory，真正强制的是 external workdir authority。不能把 tree-sitter/路径检查描述成完整 sandbox。
9. **Compaction semantics split**：V1 与 V2 都有 compaction，但 message model、history boundary、Context Epoch、provider-native metadata 的处理不同；需以具体入口追踪，不能混写为一个 compactor。
10. **Database migration compatibility**：已读取 schema/迁移入口，但未运行 migration、rollback、旧库兼容或 catalog probe；现有表结构说明是声明式源码事实，不是已验证数据库实例状态。
11. **Runtime lifecycle**：Server listener、embedded Scope、Location services、SessionExecution process-global coordinator 的生命周期设计已在源码/测试中出现；未启动服务，因此未验证多 host、并发、断线、重连、崩溃恢复和跨进程行为。
12. **工作树边界**：此前建档时项目工作树有未跟踪的 `ARCHITECTURE.md` 和 `历史研究-opencode.md`；最新版本在独立工作区 `~/Documents/Agent/源码研究工作区/opencode-最新版本` 只读复核，未覆盖原工作树。

## 11. 权威阅读索引

### 产品与规则

- `README.md`：产品定位、安装、Desktop beta、build/plan/general agents。
- `AGENTS.md`：依赖方向、SDK 生成、测试/typecheck入口、V2 Session 约束。
- `CONTEXT.md`：System Context、Context Epoch、Session Input、Client/SDK IR 等术语与关系。
- `specs/v2/session.md`：V2 Session、admission、runner、events、compaction、context parity、tool registry 状态。
- `specs/v2/provider-model.md`：Provider/Model catalog、native route 支持边界。

### 核心实现

- `packages/core/src/session.ts`：V2 Session Service 与 prompt admission、read/query/revert façade。
- `packages/core/src/session/input.ts`：durable inbox、steer/queue promotion。
- `packages/core/src/session/runner/llm.ts`：V2 provider turn、tool settlement、compaction/continuation。
- `packages/core/src/session/projector.ts`：durable events → SQLite read models。
- `packages/core/src/event.ts`、`packages/core/src/event/sql.ts`：aggregate sequence、durable event transaction/replay/stream。
- `packages/core/src/session/sql.ts`、`packages/core/src/database/database.ts`：Session/Message/Input/Epoch/SQLite 初始化。
- `packages/core/src/permission.ts`、`packages/core/src/tool/registry.ts`、`packages/core/src/tool/tool.ts`：V2 permission/tool boundaries。
- `packages/opencode/src/effect/app-runtime.ts`、`packages/opencode/src/session/processor.ts`、`packages/opencode/src/session/llm.ts`：V1 主运行时、事件处理、双 LLM runtime。

### API/消费端

- `packages/protocol/src/api.ts`、`packages/protocol/src/groups/session.ts`：current HttpApi contract。
- `packages/server/src/routes.ts`、`packages/server/src/handlers/session.ts`：current route assembly/handler。
- `packages/opencode/src/server/routes/instance/httpapi/api.ts`、`groups/session.ts`、`handlers/session.ts`：legacy/experimental HttpApi。
- `packages/client/src/contract.ts`、`script/build.ts`、`src/generated*`：Promise/Effect client generation。
- `packages/sdk-next/src/opencode.ts`、`src/index.ts`：embedded host。
- `packages/opencode/src/index.ts`、`cli/cmd/run.ts`、`cli/cmd/tui.ts`：CLI/TUI entry.

### 文档归并边界

本文件已吸收此前 `历史研究-opencode.md` 的源码分析结论；后续只维护本文件，历史研究笔记不再作为独立事实源。

## 12. 专项闭环：项目、会话与事件账本

本节把容易被混淆的“项目边界、会话执行、事件历史”拆成三个不同层次。以下结论以当前工作树源码为准，V2 与 V1 仍分别标注。

### 12.1 项目作用域

`Location` 是请求和运行时服务的入口键，至少包含绝对目录和可选 workspace ID；`LocationServiceMap` 按 Location 建立服务组，因此同一进程可以承载多个项目作用域，但不能把不同 Location 的服务或事件混用。Session 创建时由 Location 解析 Project，并将 Project 读模型作为会话的归属。

Project 不是 Git 工作树的替代物：Project 保存 worktree/VCS/name 等元数据；Snapshot 使用项目工作树的影子 Git 记录前后状态并生成 FileDiff。revert 依靠 snapshot/patch 证据，不是对业务 SQLite 事务做回滚。

### 12.2 会话状态与执行所有权

V2 会话的 durable 身份、输入 inbox、投影消息、Context Epoch 和事件 aggregate 均以 Session ID 关联。`SessionRunCoordinator` 在进程内按 Session ID 串行 drain，同一 Session 的重复 `run` 会加入当前执行，`wake` 只合并一个后续唤醒；不同 Session 可并发。`interrupt` 标记 stopping 后中断 owner fiber，并等待清理。

这是一种**单进程所有权**，不是集群租约：runner 源码明确把 durable multi-node ownership、durable run status/recovery 列为未完成项。跨进程或多节点部署不能从该协调器推导出 exactly-once 执行。

### 12.3 事件账本与读模型

Durable `EventV2.publish` 在一个 SQLite immediate transaction 内完成：读取 aggregate 最新序号、校验 owner/sequence、运行注册 projector、执行可选 commit hook、更新 `event_sequence`、插入带 versioned type 的 `event` 行；事务提交后才通过 PubSub 唤醒订阅者。事件序列是可重放事实源，PubSub 只负责实时通知。

关键不变量如下：

| 不变量 | 违反时的处理 |
|---|---|
| aggregate 字段必须是字符串且与目标 aggregate 一致 | `InvalidDurableEventError` |
| 新事件序号必须等于 latest + 1 | 拒绝并终止该事件提交 |
| 相同 ID/序号的 replay 必须 type、data 深相等 | 相同则幂等；不同则判定 replay diverged |
| strict owner replay 只能由当前 owner 执行 | 拒绝 owner mismatch |
| projector 与事件写入在同一事务 | projector 失败时不产生半条 durable event |
| bounded subscriber 队列不得无限增长 | 丢弃时返回 `SubscriberOverflowError` |

因此“事件已通知”不等于“事件已持久化”；对恢复和审计应读取 SQLite durable event stream，而不是 instance-wide live stream。Projector 是可查询 Session/Message/Part/Input/Epoch 的读模型写入者，投影缺失或历史版本不兼容时必须按账本错误处理，不能以实时通知补偿。

## 13. 输入准入、工具执行与 Provider 边界

### 13.1 输入准入

`SessionInput.admit` 先按 message ID 查询 durable inbox；已有记录直接返回，形成相同 ID 的幂等 receipt。新输入发布 `PromptAdmitted`，要求事件携带 aggregate sequence；投影写入 `session_input` 时用冲突检测避免 admission 与 message 生命周期交叉。

`delivery=steer` 在活动执行的安全边界批量提升；`delivery=queue` 在空闲边界按 admitted sequence FIFO 一次提升一个，随后再提升 steer。提升会发布 `Prompted` 并设置 `promoted_seq`。相同 ID 但 session、prompt 或 delivery 不同必须视为冲突，而不是覆盖旧输入。`resume` 只是 advisory wake，不是 durable execution identity。

### 13.2 工具注册、授权与结算

V2 `Tool.make` 以 Schema 定义输入/输出，执行函数只能返回结构化 ToolFailure 或 Schema 合法输出；definition、permission 和 settle runtime 通过 WeakMap 绑定，避免外部伪造 executable tool。`ToolRegistry.materialize` 根据 agent ruleset 隐藏 whole-tool deny 的 definition，但 definition visibility 不等于授权；实际 settle 仍在工具闭包内完成。

一次本地工具调用的边界为：

```text
LLM tool-call
  → durable Tool.Called
  → registry 按当次 materialization 校验 registration identity
  → decode input Schema
  → 工具执行/权限叶子检查
  → encode output / structured output
  → ToolOutputStore.bound 限制大小并可写 managed output
  → durable Tool.Success 或 Tool.Failed
  → 等待全部 tool fiber
  → reload projected history，开始后续 provider turn
```

stale registration、未知工具、输入/输出 Schema 错误和权限拒绝都必须变成结构化 tool result 或明确中断；不能把异常文本当作成功结果。Provider-hosted tool 标记为 `providerExecuted`，不经过本地 dispatcher，必须单独计入事件和失败矩阵。

### 13.3 Provider 路由

V2 Core 只持有 Provider/Model 的 Schema 类型和请求模型；实际 provider catalog、认证、AI SDK/native route 兼容和 `providerOptions` 由 legacy `packages/opencode` 的 provider 适配层承担。适配层可按 npm provider 动态加载 bundled SDK，并处理 endpoint、凭据、区域、请求头、模态输入和协议差异；这些兼容细节不应泄漏到 Session/Tool 领域语义。

V2 runner 每个 provider turn 构造一次 `LLM.request` 并调用一次 `llm.stream`。文本、reasoning、tool-call、provider error 和 finish 通过 publisher 写入 durable Session event；context overflow 在 assistant 尚未开始时进入一次 compaction/retry 路径。当前源码仍未提供完整 provider retry/watchdog、所有 provider parity 或 durable retry status，故网络成功、重试成功与会话成功不能互相替代。

## 14. 远程仓库缓存、资源与进程边界

### 14.1 远程仓库缓存

`RepositoryCache.ensure` 将 remote reference 解析、branch 校验、缓存目录创建、已有仓库复用判断、clone/fetch/checkout/reset 封装在 `EffectFlock` 锁内。缓存路径按 remote/branch 形成稳定目录；已有目录若 origin 不匹配会删除后重建，匹配时返回 `cached`，首次为 `cloned`，refresh 或分支不匹配为 `refreshed`。刷新顺序是 fetch remotes、可选 fetch branch、checkout remote branch、hard reset 到请求分支或默认远端分支。

错误按 invalid repository/branch、clone、fetch、checkout、reset、lock 和一般 cache operation 分类，调用方可以区分输入错误、远程失败和本地缓存失败。该缓存是工作副本，不是事件账本；hard reset 可能丢弃缓存副本本地改动，必须由调用方明确选择 refresh。

### 14.2 资源所有权

| 资源 | 所有者 | 有界措施 | 失败/取消结论 |
|---|---|---|---|
| SQLite connection/事务 | Database/Scope | WAL、busy timeout、immediate transaction、Scope finalizer | 事务失败回滚；未证明跨进程迁移协调 |
| PubSub/Stream/Queue | Event Service/订阅 Scope | 可选 bounded queue、overflow error、finalizer shutdown | 订阅者不消费会失败，不允许无限堆积 |
| Session runner fiber | Location-scoped coordinator | 每 Session 单 owner、wake 合并、FiberSet 等待 tool settlement | interrupt 会清理未完成工具；集群恢复未实现 |
| 工具输出 | ToolOutputStore | 最大行/字节、超限转 managed output path | 不得把无限 stdout 注入模型上下文 |
| Provider stream | LLM client/runner Scope | Abort signal、stream finalization、tool fiber join | provider error 或取消会标记未结算工具失败 |
| 子进程/PTY | AppProcess/PTY service | timeout、AbortSignal、输出字节上限、scoped handle | 代码有 scope 关闭语义；宿主被 SIGKILL 后孤儿进程仍未现场证明 |
| 远程缓存锁 | EffectFlock | 按 localPath 锁定单次 cache operation | lock failure 结构化返回；锁跨机器语义未验证 |

### 14.3 进程边界

AppProcess 统一描述 child command，收集 stdout/stderr 时可分别设置最大字节数，支持 timeout、AbortSignal、stdin 和 stream 模式；非零 exit code、超时、取消和 spawn 缺陷均包装为 `AppProcessError`。该边界只保证调用器可观察的退出与输出，不等于沙箱：Bash/宿主 filesystem/process/network authority 仍由上层策略决定。

TUI、Web、Desktop、HTTP server 和 embedded SDK 是不同消费/宿主表面。embedded SDK 使用同一 router/handlers 的进程内 web handler，不新增业务执行实现；Desktop 的 Electron main/preload/renderer 通过 IPC 分隔权限。V1 Worker/RPC、V2 Server listener 与 embedded Scope 不应被写成同一个进程拓扑。当前未执行多进程、断线重连或强杀后的端口/子进程清点。

## 15. 失败矩阵（专项版）

| 边界 | 失败输入/事件 | 代码策略 | 当前证据等级 |
|---|---|---|---|
| Project/Location | 目录或 workspace 无法解析 | Location/Project service 返回 domain error，禁止跨 Location 复用 | L0-L1，未做运行探针 |
| Session admission | 相同 ID 内容不同 | 幂等查询后由调用层判冲突；不得覆盖旧 admission | L1，竞态未压测 |
| Event ledger | sequence、aggregate、owner 或 replay data 漂移 | 事务内拒绝；相同事件仅允许幂等 replay | L1，未做故障注入 |
| Projector | projector/Schema 解码失败 | durable transaction 失败，不承诺半投影可恢复 | L0-L1，旧版本迁移未运行 |
| Live event | bounded subscriber 队列满 | `SubscriberOverflowError`，调用者必须重读 durable stream | L0，未验证消费者策略 |
| Tool admission | whole-tool deny、未知名、stale registration | 不广告或返回结构化错误；不执行陈旧 registration | L1，未做权限全矩阵 |
| Tool execution | 输入/输出 Schema 不合法 | `ToolFailure`，记录 Tool.Failed | L1，未做每工具真实执行 |
| Tool output | 超过行/字节上限 | head/tail 或 managed path，限制模型可见内容 | L0-L1，未压测极限 |
| Provider | header timeout、stream error、429/5xx | Abort/error event；部分 V1 有适配/fallback，V2 retry/watchdog 未闭环 | L0-L1，无真实凭据验证 |
| Context | request overflow | assistant 尚未开始时 compaction 后重建一次；重复 overflow 失败 | L1，未执行边界注入 |
| Process | non-zero、timeout、abort、输出过大 | AppProcessError、截断标志、scope/abort 清理 | L0-L1，未证明 SIGKILL 无残留 |
| Repository cache | remote/branch/lock/clone/fetch/reset 失败 | 分类错误，锁内操作；不伪造 cached/cloned/refreshed 状态 | L1，未做真实远端失败矩阵 |
| Host crash | runner、server、子进程、relay 突然消失 | 依赖 durable history/resume 和分散 cleanup；无完整 durable run recovery | **未验证高风险** |

**专项总裁决：** OpenCode 当前最稳固的架构事实是 Location/Project 作用域、SessionInput admission、SQLite durable event + projector、Schema 工具结算、有界输出、按键串行 runner 和锁保护的远程仓库缓存。最主要的未闭环是集群所有权、durable run recovery、provider retry/watchdog、取消结算、插件/MCP/structured-output 完整策略、后台维护和宿主崩溃后的资源证明；这些必须保持为缺口，不能用接口存在、cleanup 函数存在或测试文件存在替代运行证据。

## 16. 深度取证补充（2026-08-21）

### 16.1 关键节点九字段

| 节点 | 目的 | 输入 | 输出 | 状态 | 资源 | 错误边界 | 证据 | 权限/重试 |
|---|---|---|---|---|---|---|---|---|
| `SessionInput.admit` | 将用户 prompt 写入 durable inbox | message/session/prompt/delivery | admission receipt + seq | admitted/promoted | SQLite + EventV2 | `LifecycleConflict`、缺 durable seq | `packages/core/src/session/input.ts:41-80` | 调用者授权；同 ID 幂等，不自动重试 |
| `SessionRunCoordinator` | 按 Session 串行执行 | session key、force/wake | `run`/`interrupt` completion | active/pendingWake/stopping | FiberSet、Deferred、Scope | runner error/interrupt | `packages/core/src/session/run-coordinator.ts:24-103` | 进程内 owner；wake 合并 |
| `SessionRunner.runTurn` | 执行一轮 provider + tools | projected history、model、agent、tools | durable text/tool/step events | streaming/settled/continuation | LLM stream、tool fibers、snapshot | provider/overflow/tool/interrupt | `packages/core/src/session/runner/llm.ts:173-348` | Location 校验；overflow 仅一次 compaction |
| `ToolRegistry.settle` | 校验并执行本地工具 | ToolCall + registration identity | bounded ToolResult | registered/settled/failed | ToolOutputStore、Scope registration | unknown/stale/schema/tool failure | `packages/core/src/tool/registry.ts:50-82` | Permission materialize + stale identity |
| `EventV2.commitDurableEvent` | 事件账本与投影原子提交 | typed event、aggregate/seq | event row + projector read model | appended/replayed/rejected | SQLite transaction、PubSub | aggregate/owner/sequence/replay divergence | `packages/core/src/event.ts:205-340` | strict owner；同事件深相等幂等 |
| `RepositoryCache.ensure` | 管理远程仓库工作副本 | remote reference/branch/refresh | cached/cloned/refreshed + path | locked/checked-out/reset | EffectFlock、Git、filesystem | clone/fetch/checkout/reset/lock | `packages/core/src/repository-cache.ts:124-211` | branch 白名单；refresh 是显式操作 |
| `AppProcess.run` | 受控子进程执行 | command、timeout/signal、output limits | exit/stdout/stderr | spawned/exited/aborted | scoped child process | `AppProcessError` | `packages/core/src/process.ts:139-212` | 超时/取消可中断；非零需 `requireSuccess` |

### 16.2 正常与异常矩阵

| 场景 | 已实现路径 | 结论 |
|---|---|---|
| 正常 | admit → projector → coordinator → `llm.stream` → tool settle → `Step.Ended` | 本地源码链路完整，L1 |
| Provider 错误 | publisher 记录 provider error，未结算工具转 failed，assistant 失败 | 无 V2 durable retry/watchdog，L1 |
| Context overflow | assistant 尚未开始时 compaction，重建 request；再次 overflow 终止 | 一次恢复上限，L1 |
| Tool 拒绝/失败 | Permission Deferred reject 或 ToolFailure 转结构化结果；等待 fibers | 用户拒绝会中断当前审计，L1 |
| 超时 | `AppProcess.run` `Effect.timeoutOrElse` 返回 `AppProcessError(Timed out)` | Scope 清理有代码证据，未做强杀探针 |
| 取消 | 清空 tool fibers，发布 Tool.Failed/assistant interrupted | 取消结算与最终 durable run status 仍缺失 |
| 崩溃/强杀 | 可从 durable event/history 重放；本地 owner、子进程、后台维护不保证恢复 | 高风险未验证，L0-L1 |

### 16.3 证据等级与平台映射

## 17. 本次复审源码增量：输入准入、事件投影与上下文代际（2026-08-21）

### 17.1 V2 输入先落账再调度

`packages/core/src/session/sql.ts` 的 `session_input` 表同时保存 `delivery`、`admitted_seq` 和 pending 索引；同一 session 的 admitted sequence 唯一。生成的 SDK 将 V2 prompt 暴露为 `/api/session/{sessionID}/prompt`，请求可携带 `delivery: "steer" | "queue"` 与 `resume`。这表明输入接收（admission）和 agent-loop 执行是两个阶段，不能用内存队列替代持久账本。

### 17.2 Durable event 是 projector 的前置条件

`packages/core/src/session/projector.ts` 对缺失 `event.durable.seq` 直接终止，并将 admitted sequence、delivery 和 promoted sequence 写入读模型；消息更新器对 `session.next.prompt.admitted`、compaction started/delta/ended 等事件分别投影。重放必须按 aggregate sequence，不能只按时间戳或 UI 消息顺序。

### 17.3 Permission 在工具执行前合并

`packages/opencode/src/session/tools.ts` 将 agent、session 和 MCP server 规则合并成 ruleset；命中未知权限时通过 `ctx.ask` 产生审批事件。`packages/core/src/permission.ts` 对重复 pending permission id 直接 fail-fast，避免两个请求同时结算同一审批。工具 settle 发生在 runner、background job 和 registry 多个调用面，错误结果保持 `ToolFailure`/`ToolResultValue` 结构而不直接抛出到传输层。

### 17.4 Context Epoch 保护压缩期间的一致性

`packages/core/src/session/context-epoch.ts` 为每个 session 持久化 baseline、snapshot 与 baseline sequence；系统上下文变化会生成 replacement generation，只有在 admitted context 可用时才替换。`packages/opencode/src/session/compaction.ts` 写入 compaction part，支持 tail turns、插件改写 prompt 和 `experimental.compaction.autocontinue`；自动续跑带 `compaction_continue` 元数据，以区别用户新输入。

### 17.5 当前审计边界

证据来自本地 `.codegraph` 查询 `prompt/settle/projector/context-epoch/compaction/permission` 及当前源码；未调用 MCP、未构建或运行服务。Provider 的 67 个 runtime 实现仍需按具体 provider 逐一复核，当前档案不把接口分派误写成单一实现。

- `L0`：源码、注释或规格声明；`L1`：静态调用链/测试代码存在；`L2`：目标包测试真实通过；`L3`：本地 HTTP/DB/provider/process 探针通过；`L4`：发布、多进程、崩溃恢复和资源清点证据。当前审计未安装、未启动、未执行测试，因此新增结论最高为 L1。
- 可吸收为支持库：EventV2 账本与 projector、Effect Schema/协议编解码、LLM Route、Tool registry/output bound、Permission Deferred、AppProcess、Git remote cache。
- 可吸收为模块库：Session admission/runner、Location 服务组装、远程仓库引用工作副本、HTTP/SSE 消费。
- 可吸收为运行核心：按 Session keyed coordinator、durable replay、Scope/Fiber 生命周期、统一错误边界。集群所有权、durable run recovery、provider retry/watchdog、完整插件/MCP 策略不得标为已完成能力。
