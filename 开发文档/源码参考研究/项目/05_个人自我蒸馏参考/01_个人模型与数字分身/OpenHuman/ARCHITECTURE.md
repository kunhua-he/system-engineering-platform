```text
OpenHuman monorepo
│
├─ React/Vite UI (app/src)
│  ├─ main.tsx: polyfills, analytics/Sentry, deep-link/bootstrap
│  ├─ App.tsx: Redux persistence + provider/gate chain + HashRouter
│  ├─ services/coreRpcClient.ts: JSON-RPC URL/token/transport selection
│  ├─ services/socketService.ts: Socket.IO event stream → Redux/runtime
│  └─ pages/features/components/store: screens, domain UI, client state
│                         │
│                         │ Tauri IPC: core_rpc_url/core_rpc_token,
│                         │ relay_http_rpc, lifecycle/window/file commands
│                         ▼
├─ Tauri desktop shell (app/src-tauri)
│  ├─ lib.rs: Wry host, plugins, commands, lifecycle/tray
│  ├─ core_process.rs: CoreProcessHandle + embedded Tokio core task
│  └─ core_rpc.rs: host-side authenticated HTTP relay
│       │
│       │ in-process call: run_server_embedded_with_ready + bearer in memory
│       ▼
├─ Rust core library (src/lib.rs → src/core + src/openhuman)
│  ├─ CoreBuilder/CoreRuntime: composition (ServiceSet + DomainSet)
│  ├─ core/jsonrpc.rs: Axum routes, auth, JSON-RPC/SSE/Socket.IO boundary
│  ├─ core/all.rs: controller schemas, handlers, domain/capability filtering
│  ├─ openhuman/agent: prompts, sessions, tools, orchestration, learning
│  ├─ openhuman/memory: host RPC/tools/guards over extracted memory engine
│  ├─ openhuman/config/security/runtime/inference: policy and platform services
│  └─ channels/flows/skills/mcp/meet/web3/voice/...: feature domains
│       │
│       ├─ Config + security policy + approval/sandbox gates
│       ├─ TinyAgents harness: model/tool loop, middleware, retry, limits
│       ├─ TinyMemory/TinyCortex: SQLite, ingestion, retrieval, memory tree
│       ├─ tinybus modules: separately compiled trusted native capabilities
│       └─ API/Socket.IO/HTTP/OS keyring/external connectors
│                         │
│                         ▼
└─ Local workspace state + external services
   ├─ config.toml, profile homes, sessions/*.jsonl, SQLite memory stores
   ├─ memory tree / wiki / embeddings / sync-source artifacts
   ├─ TinyHumans backend + OpenAI-compatible providers + integrations
   └─ messaging channels, MCP servers, managed runtimes, desktop OS APIs

Primary request path:
User → React event → coreRpcClient → (direct HTTP or Tauri relay) →
Bearer/CORS middleware → rpc_handler → invoke_method →
ControllerSchema validation → registered domain handler → policy/store/tool/
provider → RpcSuccess/RpcFailure → React state and Socket.IO progress events.

Agent turn path:
chat/channel/CLI entry → Agent session + prompt/memory context →
ChatTurnGraph → run_turn_via_tinyagents_shared → TinyAgents AgentHarness
(model calls ↔ tool calls ↔ middleware/policy) → progress/journal/transcript,
usage and final response.

Memory path:
doc_put/doc_ingest/sync source → MemoryGuard (taint/scope/budget) →
MemoryProvider capability → TinyMemory/TinyCortex engine → SQLite/chunks/
embeddings/tree/graph → recall/query/context → prompt or RPC response.
```

# OpenHuman 架构文档

## 项目定位

OpenHuman 是一个面向个人工作与社区协作的本地优先 AI assistant / agent harness：桌面端用 React + Vite 提供 UI，用 Tauri v2（当前 shell 类型为 Wry）承载桌面能力；Rust core 负责配置、认证、JSON-RPC、模型调用、工具执行、记忆、编排、连接器和安全策略。README 将产品定位为持久记忆、工作流编排和研究/执行能力的个人 AI；`AGENTS.md` 将当前可交付运行范围明确为 Windows/macOS/Linux 桌面端。

核心架构判断：它不是“前端调用一组云 API”的薄客户端，而是一个可组合的 Rust runtime。桌面 shell、standalone CLI、HTTP API、MCP/stdio host 和库内嵌入都复用 `CoreBuilder`/`CoreRuntime`、controller registry 和 domain services；桌面 UI 只负责呈现、导航和桥接。

## 真实目录/分层与职责

以下按实际源码与当前模块声明整理，不把 `vendor/` 子模块内部所有文件展开。

### 仓库级目录

- `app/`：pnpm workspace `openhuman-app`。
  - `app/src/`：React/TypeScript UI、Redux store、providers、services、pages、features、components、工具函数和 iOS/远程 transport。
  - `app/src-tauri/`：桌面 Tauri crate；与 root Rust crate 是独立 Cargo world，有独立 lock/target。
  - `app/src-tauri-mobile/`：实验性移动 host；桌面 `app/src-tauri/src/lib.rs` 明确拒绝移动 target，移动 host 单独存在。
  - `app/test/`：Vitest 配置、测试 setup、mock API、浏览器/桌面 E2E 辅助代码。
- `src/`：root Rust crate `openhuman`，产出 `openhuman-core` 和库 `openhuman_core`。
  - `src/main.rs`：core 二进制入口；dotenv、Sentry（feature 开启时）、secret scrub，再委派 `run_core_from_args`。
  - `src/lib.rs`：公共库入口，导出 `api`、`core`、`embed`、`openhuman`、`rpc`，并暴露 `CoreBuilder`、`CoreRuntime`、`DomainSet`、`ServiceSet`、`agent_progress`。
  - `src/core/`：传输与运行时内核，不承载具体业务域；含 CLI、JSON-RPC、controller registry、事件总线、运行时 composition、认证、日志和 observability。
  - `src/openhuman/`：业务域集合；当前模块声明包括 `agent`、`memory`、`config`、`security`、`inference`、`runtime`、`sandbox`、`skills`、`flows`、`mcp`、`channels`、`meet`、`voice`、`web3`、`desktop`、`platform`、`threads`、`subconscious`、`integrations`、`hosted`、`tinyplace` 等。
  - `src/embed/`：面向嵌入 host 的 typed facade/contract；公共 embed API 在 `src/lib.rs` 的 `CoreBuilder`/`CoreRuntime` re-export。
  - `src/api/`：TinyHumans backend SDK 之上的 OpenHuman adapter（配置、JWT、错误分类、产品身份），不是第二套路由定义。
  - `src/rpc/`：RPC 结果/错误等公共抽象。
  - `src/bin/`：受 `bin-tools` 等 feature 约束的 backfill、probe、审计和 benchmark binaries。
- `tests/`：root Rust integration/E2E tests；`tests/raw_coverage/` 的多个模块由 `build.rs` 聚合到 `raw_coverage_all`。
- `gitbooks/developing/`：架构、前端、Tauri shell、agent harness、E2E/testing 等开发文档。
- `docs/`：更深的实现/计划/迁移材料。
- `vendor/`：TinyAgents、TinyCortex、TinyMemory、TinyFlows、TinyChannels、TinyPlace、TinyHumans SDK、TinyBus、TinyWallet 等 path/git-submodule 依赖。
- `scripts/`：构建、mock backend、Rust mock 测试、E2E、CI feature/coverage、文档生成和 release 辅助。

### 前端层 `app/src/`

- `main.tsx`：最早期 polyfill、IPC fallback、Sentry/GA、deep-link listener、active-user bootstrap，然后按窗口类型渲染 `App`/mascot/notch/overlay。
- `App.tsx`：实际 provider/gate 顺序为 `Sentry.ErrorBoundary → Redux Provider → PersistGate → ThemeProvider → I18nProvider → BootCheckGate → CoreStateProvider → (desktop SocketProvider) → ChatRuntimeProvider → HashRouter → CommandProvider → ServiceBlockingGate → AppShell`，该顺序由 `@generated-source:provider-chain` 注释和生成文档共同约束。
- `AppRoutes.tsx`：HashRouter 路由、公开/受保护路由和兼容重定向；核心产品面包括 `/chat`、`/human`、`/brain`、`/flows`、`/orchestration`、`/connections`、`/settings/*`、`/agent-world/*` 等。
- `store/`：Redux Toolkit slices；`store/index.ts` 是 reducer/persist 的权威装配点，`userScopedStorage.ts` 使用户状态按 active user 隔离。
- `providers/`：core snapshot、socket 生命周期、chat/tool/approval 事件的 React context。
- `services/`：`coreRpcClient.ts`、`coreCommandClient.ts`、`socketService.ts`、`apiClient.ts`、`backendUrl.ts`、`services/api/*` 和 `transport/*`。
- `lib/`：i18n、MCP helper、AI context helper、tunnel crypto、平台和公共渲染逻辑；prompt 文件由 core 侧资源读取，不由 UI 负责加载。
- `pages/`、`features/`、`components/`：按路由/业务垂直/共享 UI 分层；规则和状态应留在 core/services/store，而不是散落在组件中。

### 桌面 shell `app/src-tauri/`

- `src/lib.rs`：桌面入口 `run()`、Tauri plugin 注册、窗口/tray/lifecycle、`tauri::generate_handler!` IPC 清单；使用 `tauri::Wry`。
- `src/main.rs`：Tauri binary entry。
- `src/core_process.rs`：`CoreProcessHandle`；生成 32-byte hex bearer，启动 root core 的 embedded server task，处理 ready signal、端口冲突、旧 listener 回收、重启与 shutdown。
- `src/core_rpc.rs`：shell 侧 RPC URL/token 辅助和 `relay_http_rpc`，用于 webview 不能直接访问非 loopback 明文 HTTP 时的 relay。
- `src/workspace_paths.rs`、`src/artifact_commands.rs`、`src/file_logging.rs`：受路径策略约束的 workspace 文件、artifact 导出和日志目录能力。
- `src/dictation_hotkeys.rs`、`src/ptt_hotkeys.rs`、`src/ptt_overlay.rs`、`src/companion*`、`src/native_notifications/`：桌面输入、通知和窗口能力。
- `src/loopback_oauth.rs`、`src/mcp_commands.rs`、`src/imessage_scanner.rs`、`src/webview_apis.rs`：OAuth、MCP 辅助、原生 iMessage 读取及仍保留的 webview API bridge。

### Rust core 运行时与 controller 层

- `src/core/runtime/builder.rs`：`CoreBuilder` 初始化 `CoreContext`，`CoreRuntime::invoke` 做进程内 dispatch，`CoreRuntime::serve` 选择 HTTP/background services。
- `ServiceSet` 独立控制 transport/background work：`rpc_http`、`socketio`、`cron`、`channels`、`heartbeat`、memory queue、harness init、skill catalog、MCP boot、integrations、memory sync、orchestration 等。
- `DomainSet` 独立控制 live domain family：agent、memory、threads、config、security、flows、skills、mcp、meet、channels、web3、voice、media、medulla、inference、integrations、automation、runtimes、desktop、hosted、relay、modules、platform。
- `src/core/all.rs`：聚合各域的 `all_*_registered_controllers()`/schemas，登记 `DomainGroup` 与可选 memory `Capability`，校验重复方法并过滤当前 runtime surface。RPC namespace 是字符串契约，不由目录名推导。
- `src/core/types.rs`、`src/core/mod.rs`：RPC envelope、`HostKind`、`ControllerSchema`/`FieldSchema`/`TypeSchema` 等跨 transport contract。
- `src/core/dispatch.rs`：动态/内部方法和 unknown-method 处理；`src/core/cli.rs`、`src/core/jsonrpc.rs` 共用 controller/dispatch 能力。
- `src/core/bus.rs`、`src/core/events.rs`、`src/core/socketio.rs`：typed event bus、`DomainEvent`、Socket.IO 实时桥；事件 subscriber 通常在各域 `bus.rs` 中实现。

### Agent 域

- `src/openhuman/agent/harness/session/`：OpenHuman 产品会话壳。`types.rs` 的 `Agent`/`AgentBuilder` 持有 model source、tool registry/spec、memory、prompt/context manager、workspace、profile、transcript、progress、policy 和 hook 状态；`builder.rs` 构造，`turn/` 驱动 turn 生命周期，`runtime.rs` 提供 `run_single`/interactive，`transcript*` 保持 JSONL 兼容。
- `src/openhuman/agent/tinyagents/`：唯一生产 agent-loop adapter。它把 OpenHuman `Provider`/`Tool`/`ChatMessage` 接到 TinyAgents `ChatModel`/`Tool`/`Message`，组装 `AgentHarness`、model routes、retry、budget/context middleware、tool policy、steering、stop hooks、observability、subagent graph 和 replay。
- `src/openhuman/agent/harness/session/turn/graph.rs`：chat turn 的薄 graph wrapper，向 `run_turn_via_tinyagents_shared` 传入模型、消息、可见工具、迭代上限、progress sink、context window、run queue、sandbox/policy。
- `src/openhuman/agent/messages.rs`：持久 transcript 的 `ChatMessage` 和结构化 `ConversationMessage`（Chat、AssistantToolCalls、ToolResults）；运行时模型消息转换在 `message_convert`/TinyAgents adapter。
- `src/openhuman/agent/prompts/`、`src/openhuman/agent/context/`：系统 prompt section、profile/MEMORY/SOUL/工具/连接器/记忆注入和 context reduction。
- `src/openhuman/agent/registry/`、`src/openhuman/agent/profiles/`：built-in/custom agent definitions 与持久 profile；`profiles/types.rs` 的 `AgentProfile` 用 allowlist、model/temperature、SOUL、memory source、dedicated memory/workspace 等字段描述会话人格。
- `src/openhuman/agent/tools.rs`、`src/openhuman/tools/`：agent-facing tool trait/spec、domain-owned tool implementations、registry/policy/status；controller RPC 与 agent tools 是两套 surface，但都在 `core/all.rs`/tool aggregation 中受 domain/capability policy 约束。
- `src/openhuman/agent/triage/`、`orchestration/`、`learning/`、`experience/`、`harness_init/`、`session_db/`：触发器 triage、子 agent/团队编排、学习/经验、启动初始化和 durable run/session side effects。

### Memory 域

- `src/openhuman/memory/mod.rs` 明确把 memory 分为 host layer 与 extracted engine。host 负责 `schemas`/`read_rpc`、agent tools、`guard`、driver binding、`ops`、memory agent、global singleton 和 `host_impls`。
- `vendor/tinymemory/core/`/`vendor/tinycortex/` 承载 SQLite/vector store、ingestion、recall/query/search、queue、conversation/people/goals、summary tree、provider sync 等引擎能力；OpenHuman 通过 re-export/adapter 保持历史 import 与 wire types。
- `src/openhuman/memory/api.rs` 是 tinybus memory contract 的 re-export，不是复制的 API 定义；`capabilities`、`provider`、`chunks`、`error`、`recall`、`tree`、`wire` 等跨模块 contract 来自 `tinymemory-api`。
- `src/openhuman/memory/ops/documents.rs`：`PutDocParams`、`IngestDocParams`、`QueryNamespaceParams`、`RecallNamespaceParams` 等输入模型；`doc_put`、`doc_ingest`、`doc_list`、`doc_delete`、`clear_namespace`、`context_query`、`context_recall` 和 envelope-style `memory_*` handler 都在这里。
- `src/openhuman/memory/guard/`：每个 provider call 的 taint/scope/budget/security gate；`active_memory_guard()` 先选择 capability，再调用 `MemoryProvider`。
- `src/openhuman/memory/tree/`、`sync/`、`sources/`、`conversations/`、`people/`、`goals/`、`diff/`、`tool_memory/`：tree/retrieval、外部源同步、会话记忆、联系人、目标、git diff、工具规则等 host RPC/tool seams。

### 其他核心域

- `config/`：`Config` 及 migrations/loader/RPC。`Config` 是 `config.toml` 根模型，包含 `workspace_dir`/`action_dir`、backend/inference/model routes、autonomy/privacy/sandbox/runtime/scheduler、agent/profile、memory/tree/sources、MCP、channels、voice 等配置节。
- `security/`：approval、credentials/keyring、encryption、prompt-injection、egress、devices、path/command policy。`action_dir` 是 agent 行动根，`workspace_dir` 是内部状态根；源码把两者分开并在 policy 中 fail-closed。
- `inference/`：provider factory、model routing、HTTP/OpenAI-compatible endpoint、embeddings、TokenJuice、cost/usage；模型 provider 字符串由 config schema/factory 解析。
- `runtime/` 与 `sandbox/`：managed Node/Python、runtime pool、JavaScript execution、CWD jail 和平台 sandbox。
- `skills/`：SKILL.md metadata/catalog、install/parse/inject、runtime run/cancel/log；源码与架构文档均表明旧 QuickJS per-skill VM 已移除，执行走 runtime/tool harness。
- `flows/`：tinyflows workflow graph 的 create/run/schedule 与 Rhai/语言工作流 seam（`flows` feature 开启时）。
- `mcp/`：静态配置 server、动态 registry/OAuth/audit、stdio/HTTP MCP host；`mcp::http_client` 是总是编译的共享 transport seam。
- `channels/`、`meet/`、`voice/`、`web3/`、`tinyplace/`、`integrations/`、`hosted/`、`desktop/`、`platform/`：外部消息/会议/语音/钱包与 x402/A2A/后端代理/桌面状态和健康等产品能力。

## 核心数据流

### 桌面启动与 RPC

1. Tauri `run()` 创建 `CoreProcessHandle`，并由前端 `start_core_process` 触发 `ensure_running()`。
2. `ensure_running()` 调用 root crate 的 `run_server_embedded_with_ready`，服务器作为当前 Tauri 进程内 Tokio task 运行；bearer 通过参数/内存交接，不依赖 sidecar 进程。
3. 前端 `coreRpcClient.ts` 解析 stored URL、Tauri `core_rpc_url` 或默认 loopback URL；token 从 stored token、Tauri `core_rpc_token` 或 injected native-window global 获取。
4. loopback/可信源直接 `fetch POST /rpc`；非 loopback 的明文 HTTP 走 `invoke('relay_http_rpc')`，由 shell 侧 reqwest 发出。
5. `core/jsonrpc.rs` 的 auth/CORS/log middleware 后进入 `rpc_handler`；方法优先查 controller schema，转换/校验 object params，再调用 registry handler，未命中时落到 `core::dispatch`。
6. 成功返回 JSON-RPC 2.0 `result`；失败返回 code `-32000` 与可选 structured error data。confirmed session expiry 还会发布 `DomainEvent::SessionExpired`，由 credentials subscriber 清理会话。

### Agent turn 与实时进度

1. web chat/channel/CLI 入口从 Config、AgentProfile、agent registry、memory loader、connected integrations 和 tool policy 构造 `Agent`。
2. session turn 组装 system prompt、profile/SOUL/MEMORY、retrieved context、历史 transcript 和当前消息。
3. `turn/graph.rs` 将这些内容交给 `run_turn_via_tinyagents_shared`；TinyAgents harness 注册 model/tools，执行 model/tool 迭代，应用 retry、budget、context compression、unknown/invalid-tool policy、approval/sandbox、stop/steering 和 depth/wall-clock limits。
4. `OpenhumanEventBridge` 将 harness events 转成 `AgentProgress`；Socket.IO/web chat 把 token/tool/subagent/usage/approval 事件送回前端。turn outcome 保存结构化 conversation、usage/cost、tool outcomes、cap/breaker 状态。
5. `transcript_history`/session DB 以 JSONL/SQLite 等持久化会话；post-turn hooks 可写经验、学习、memory tree 或 journal。工具结果还可经 TokenJuice/payload summarizer 压缩后再进入上下文。

### Memory 写入、索引与召回

- `doc_put` 接收 namespace/key/title/content/source/priority/tags/metadata/category/session/document id，默认以 `MemoryTaint::Internal` 进入 `MemoryGuard`。
- guard 依据当前 driver/capabilities、source scope、budget 和 security policy 决定是否允许，并将调用交给 `MemoryProvider`。
- TinyMemory/TinyCortex 负责 document/chunk、embedding/retrieval、entity/relation、SQLite 持久化、tree summary 和同步队列；host 不假装知道模块内的 extraction counts，`doc_ingest` 在 module boundary 下返回 `driver-managed` 摘要。
- `memory_query_namespace`/`memory_recall_context` 生成 `MemoryRetrievalContext` 与 LLM-ready context message；recall 结果可带 entity、relation、chunk、score、metadata 和 citation/reference。
- 外部 connectors、workspace folders/repos/RSS/web 等由 `memory/sources` 与 `memory/sync` 按 `Config.memory_sync_interval_secs`/ServiceSet 调度，写入时保留 external provenance。

### Domain/feature gating

`DomainSet` 是运行时 gate，`Cargo.toml` features 是编译期 gate；二者都可使 controller 从 `/schema`/`/rpc` 消失、使 agent tool 不注册、使 store/subscriber 不初始化。root Cargo 的 contributor default set 与 `scripts/ci/product-features.txt` 产品 set 分离；`app/src-tauri/Cargo.toml` 显式转发产品 features，并在 `app/src-tauri/src/lib.rs` 用 compile-time assertions 检查至少 `voice` 与 `http-server`。这是防止“构建成功但 shipped surface 静默缺失”的关键设计。

## 关键类/函数/数据模型及相对路径

### 入口与组合

- `src/main.rs`: `main()`。
- `src/lib.rs`: `run_core_from_args()`、`CoreBuilder`/`CoreRuntime`/`DomainSet`/`ServiceSet` re-export、`agent_progress`。
- `src/core/cli.rs`: `run_from_cli_args()`、`run_server_command()`、`run_call_command()`。
- `src/core/runtime/builder.rs`: `CoreBuilder::new/build`、`CoreRuntime::invoke/serve`、`ServiceSet`、`DomainSet`、`TokenSource`。
- `app/src-tauri/src/core_process.rs`: `CoreProcessHandle::new/ensure_running/restart`、`generate_rpc_token()`。

### RPC/registry

- `src/core/jsonrpc.rs`: `rpc_handler()`、`invoke_method()`、`invoke_method_inner()`、`build_core_http_router()`、`run_server_embedded_with_ready()`。
- `src/core/all.rs`: `ControllerSchema` registry aggregation, `DomainGroup`, `RegisteredController`, `rpc_method_name()`、schema/handler lookup and validation.
- `src/core/mod.rs`: `ControllerSchema`、`FieldSchema`、`TypeSchema`。
- `src/core/types.rs`: `RpcRequest`、`RpcSuccess`、`RpcFailure`、`RpcError`、`InvocationResult`、`AppState`、`HostKind`。

### Agent and conversation

- `src/openhuman/agent/harness/session/types.rs`: `Agent`、`AgentBuilder`。
- `src/openhuman/agent/harness/session/turn/graph.rs`: `ChatTurnGraph`、`run_chat_turn_graph()`。
- `src/openhuman/agent/tinyagents/mod.rs`: `run_turn_via_tinyagents_shared()`、`TinyagentsTurnOutcome`、harness policy/adapter and progress bridge.
- `src/openhuman/agent/messages.rs`: `ChatMessage`、`ConversationMessage`、`ToolResultMessage`。
- `src/openhuman/agent/profiles/types.rs`: `AgentProfile`、`AgentProfilesState`、`profile_signature()`。
- `src/openhuman/agent/prompts/`: system prompt and built-in agent prompt resources.

### Memory/config/security

- `src/openhuman/memory/mod.rs`: host/engine split and public re-exports.
- `src/openhuman/memory/api.rs`: TinyMemory bus contract re-export.
- `src/openhuman/memory/ops/documents.rs`: `PutDocParams`、`IngestDocParams`、`doc_put()`、`doc_ingest()`、`clear_namespace()`、recall/query handlers.
- `vendor/tinymemory/core/src/traits.rs`: authoritative `Memory`/`MemoryEntry`/`MemoryCategory`/`MemoryTaint`/`RecallOpts` types (re-exported by OpenHuman).
- `vendor/tinymemory/core/src/rpc_models.rs`: `ApiEnvelope`/`ApiMeta`、document/thread/retrieval request/response models.
- `src/openhuman/config/schema/types.rs`: `Config`、`ModelRegistryEntry`、agent/memory/runtime/security/model route configuration sections.
- `src/openhuman/config/ops/loader.rs` and `src/openhuman/config/schema/load/impl_load.rs`: config load/merge/env override path.
- `src/openhuman/security/policy.rs` and `src/openhuman/security/approval/`: command/path classification, tier decisions, approval requests and TTL behavior.

### Frontend/shell bridge

- `app/src/main.tsx`: browser/native-window bootstrap.
- `app/src/App.tsx`: provider/gate chain and shell selection.
- `app/src/services/coreRpcClient.ts`: `callCoreRpc()`、URL/token resolution、`CoreRpcError` classification and direct-vs-relay transport.
- `app/src/services/socketService.ts`: local core Socket.IO client and Redux event dispatch.
- `app/src/store/index.ts`: Redux reducer map and persistence transforms.
- `app/src-tauri/src/lib.rs`: `generate_handler!` authoritative Tauri IPC registration; key commands include `core_rpc_url`, `core_rpc_token`, `start_core_process`, `restart_core_process`, `relay_http_rpc`, workspace/artifact/update/window/hotkey/notification/MCP/OAuth commands.

## API/CLI/SDK入口

### HTTP/API

When the `http-server` feature is enabled, `build_core_http_router()` exposes:

- `GET /`、`GET /health`、`GET /schema`：root/health/schema discovery。
- `POST /rpc`：authenticated JSON-RPC 2.0; `/rpc` body cap is 64 MiB for image-bearing chat requests.
- `GET /events`、`GET /events/webhooks`、`GET /events/domain`：SSE event surfaces。
- `GET /ws/dictation`：dictation websocket。
- `GET /auth`、`GET /auth/telegram`、`GET /oauth/mcp/callback`：desktop/Telegram/MCP OAuth callbacks。
- `/v1` nested inference router：OpenAI-compatible `/v1/chat/completions` and `/v1/models`.
- Optional AgentBox routes (`POST /run`, `GET /jobs/{id}`, `GET /health`) when `OPENHUMAN_AGENTBOX_MODE=1`-style enablement is active.
- Socket.IO is attached when `socketio_enabled` is true; it carries live web-channel/agent progress events, not the controller schema contract.

RPC names are `openhuman.<namespace>_<function>`; controller schema’s internal dotted name is `<namespace>.<function>` (`ControllerSchema::method_name()`), and tests explicitly pin the distinction.

### Tauri IPC

The authoritative list is the `tauri::generate_handler!` block in `app/src-tauri/src/lib.rs`. The shell bridge includes core URL/token, start/restart/recovery, `relay_http_rpc`, update, workspace path validation/open/reveal/preview, artifact export, logs, windows/tray, dictation/PTT/companion hotkeys, notifications, MCP helpers and loopback OAuth. Frontend code should use `app/src/services/coreRpcClient.ts` and typed `app/src/utils/tauriCommands/*`, not scatter raw `invoke`/fetch calls through components.

### CLI

`openhuman-core` (`src/main.rs` → `run_core_from_args` → `src/core/cli.rs`) supports:

- `openhuman run` / `serve` with `--host`, `--port`, `--jsonrpc-only`, `--headless-api` and verbose logging.
- `openhuman call --method <name> --params '<json>'` for direct in-process controller invocation.
- `openhuman mcp`/`mcp-server`, `memory`, `tree-summarizer`, `subconscious`/`sub`, `agent`, `sentry-test` and generic `openhuman <namespace> <function> ...` dispatch.
- `openhuman tui`/`chat` when the `tui` feature is compiled; a bare interactive CLI can auto-launch TUI, while pipes/Docker/headless paths stay CLI.

### Library/SDK seams

- Rust embedders use `openhuman_core::CoreBuilder::new(HostKind).services(...).domains(...).token(...).build()`, then `CoreRuntime::invoke()` or `serve()`; `ServiceSet::none/headless_api/desktop/embedded` and `DomainSet::full/harness/kernel/none` are the composition presets.
- In-process embedders can observe agent progress through `openhuman_core::agent_progress::{with_progress_sink, ProgressSink, AgentProgress}`.
- Backend routes, URL construction, auth headers and response envelopes come from `vendor/tinyhumans-sdk`; `src/api/` adds OpenHuman-specific config/JWT/error policy.
- TinyAgents/TinyCortex/TinyMemory/TinyFlows/TinyChannels/TinyPlace/TinyBus/TinyWallet are Rust crate seams, not a separate OpenHuman HTTP SDK. The frontend’s `CoreTransport` abstraction in `app/src/services/transport/` provides LAN/tunnel/cloud transport variants for the experimental mobile/remote client.

## 技术栈和依赖

| 层 | 实际源码/清单确认的技术 |
|---|---|
| Desktop UI | React `19.1`、TypeScript `~5.8.3`、Vite `^8.0.0`、React Router `^7.13.0`、Tailwind CSS、Redux Toolkit `^2.11.2`、redux-persist、Socket.IO client `^4.8.3` |
| Desktop host | Tauri `2.11` + Wry、global-shortcut/deep-link/notification/opener/updater/single-instance plugins；`app/src-tauri/Cargo.toml` links `openhuman_core` path dependency with explicit product features |
| Rust core | Rust 2021 crate `openhuman`/`openhuman_core` version `0.63.9`、Tokio、Axum、Socketioxide、Serde/Serde JSON、`async-trait`、`anyhow`/`thiserror` |
| Agent | vendored TinyAgents `2.1`；model/tool registries、AgentHarness、middleware/retry/steering；OpenHuman adapter in `src/openhuman/agent/tinyagents/` |
| Memory | vendored TinyMemory/TinyCortex/TinyCortex API、rusqlite `=0.40.0` bundled、SQLite-backed store/tree/queue/recall/sync；embedding routes由配置和 inference provider 决定 |
| Workflow/integration | TinyFlows `0.8`、TinyChannels、TinyPlace SDK、TinyHumans SDK、MCP hand-rolled stdio/HTTP/JSON-RPC、Composio/Recall/task-source adapters |
| Network | reqwest `0.12`、tokio-tungstenite、rustls `0.23`；Windows target 可额外启用 native-tls/SChannel |
| Security | `aes-gcm`、`argon2`、`chacha20poly1305`、`x25519-dalek`、`hkdf`、`zeroize`、`keyring`；approval/path/command policy + Docker/Landlock/Bubblewrap/Firejail/AppContainer 等 sandbox seams |
| Runtime | managed Node (`xz2` gated) / Python、runtime pool、JavaScript/native tool dispatcher、workspace/action roots |
| Observability | tracing/log、可选 Sentry、file logging、AgentProgress/journal/cost accounting；前端 Sentry/analytics |
| Test/quality | Vitest + jsdom + Testing Library、WDIO/Appium/tauri-driver desktop E2E、Rust unit/integration/E2E、mock Axum/Node backend、coverage/diff-cover CI |

Root Cargo 的 default contributor feature set 实际为 `media, skills, flows, mcp, channels, medulla, http-server, scheduler-gate, file-logging, modules`；`voice`、`web3`、`inference`、`documents` 等在产品构建中由 `scripts/ci/product-features.txt` 和 `app/src-tauri/Cargo.toml` 显式转发。该差异必须保留，不能把 bare `cargo test` 的 contributor set 当成 shipped product set。

## 架构判断与未确认项

### 已确认的架构判断

1. **主边界是 Rust core，而不是 Tauri shell。** `app/src-tauri/src/lib.rs` 的 core 逻辑来自 `openhuman_core` path dependency；controller、memory、agent、security 和 persistence 均在 root `src/`/vendor，而 shell 主要是 IPC、窗口、生命周期和 OS glue。
2. **当前桌面 core 是 in-process。** `core_process.rs` 直接 spawn `run_server_embedded_with_ready`；没有依赖 `app/src-tauri/binaries/` 的 sidecar staging。`app/package.json` 的 `core:stage` 也明确是 no-op。
3. **controller registry 是 RPC/CLI 的核心契约。** 领域通过 `all_*_registered_controllers()` 接入 `core/all.rs`；schema 校验、`DomainSet`、memory capability 过滤在 transport boundary 统一处理，避免在 CLI/JSON-RPC 中堆业务分支。
4. **Agent loop 已集中到 TinyAgents。** `agent/harness/session` 保留产品会话/持久化/提示词外壳，真正 model↔tool loop 由 `agent/tinyagents` adapter 的 `AgentHarness` 驱动；该边界有 `TinyagentsTurnOutcome`、progress bridge、policy/middleware 和 transcript conversion。
5. **Memory 是“host policy + extracted engine + bus contract”三段式。** OpenHuman host 负责 RPC/tools/guard/driver/host callbacks；TinyMemory/TinyCortex 负责引擎；`memory/api.rs` 只导出真正跨 TinyBus 的类型，避免复制 wire types。
6. **运行时服务和领域能力是正交的。** `ServiceSet` 决定是否启 cron/channels/HTTP 等后台服务，`DomainSet` 决定 controller/tool/store/subscriber 是否 live；这是 headless/harness/library host 可复用的关键。
7. **安全边界与数据根分离是核心设计。** `Config` 及 security policy 明确区分 action root 与内部 workspace root；approval gate、command classification、sandbox、memory taint 和 CORS/bearer 共同限制 agent 的副作用。
8. **测试设计重视契约和负向行为。** controller registry 测 duplicate/missing/unknown params 和 feature absence；memory tests 覆盖 put→recall→clear；JSON-RPC E2E 使用真实 Axum router + mock upstream；Sentry smoke 验证 transient drop 与 permanent/aggregate 保留；前端 E2E 还覆盖跨 chat recall、core port reset、工具/设置/频道等路径。

### 文档/源码漂移与未确认项

- `gitbooks/developing/architecture/tauri-shell.md` 的部分段落仍描述 CEF、child provider webviews、CDP scanners 和旧 sidecar 形态；当前 `app/src-tauri/src/lib.rs` 使用 `tauri::Wry`，`core_process.rs` 是 in-process，`AGENTS.md` 也记录了相关 scanner/Meet/CDP 移除。后续维护应以当前源码、`AGENTS.md` 和 Cargo manifests 为准，并刷新历史文档。
- `app/src-tauri/src/lib.rs` 中 `core_rpc_token` 附近仍有 sidecar-era 注释措辞，但同文件和 `core_process.rs` 的实际调用是内存 bearer handoff；注释与实现需要单独清理，本文不把旧注释当成运行时事实。
- `gitbooks/developing/architecture.md` 的产品叙述仍带有早期 CEF/Telegram/旧 skill/旧本地 Whisper 描述；当前 feature 注释和 `AGENTS.md` 说明旧 QuickJS/本地 Whisper/相关 CEF 路径已经改变。具体版本/发布产物行为未在本次只读分析中运行验证。
- TinyAgents/TinyCortex/TinyMemory 等 vendor 子模块是当前 checkout 的 path source，但本次没有读取每个子模块的完整 README/全部内部实现；本文只读取并引用了 OpenHuman 直接依赖的 contract/trait/rpc model 与 OpenHuman adapter seam。若要做 vendor 内部架构评审，应另开只读任务。
- 记忆引擎的具体 SQLite schema、embedding provider 的真实运行时选择、外部后端当前 API 响应和模块 release artifact 是否可加载，均未因本任务限制而安装依赖、运行服务或发起网络验证；本文只记录源码声明的边界。
- 本次没有执行 build/test/service；因此文档验证是静态读取、路径核对和文件完整性验证，不是编译/运行通过声明。

## 本次实际读取与范围

已实际读取（均为相对路径）：

- `README.md`
- `AGENTS.md`
- `gitbooks/developing/architecture.md`
- `gitbooks/developing/architecture/frontend.md`
- `gitbooks/developing/architecture/tauri-shell.md`
- `gitbooks/developing/architecture/agent-harness.md`（通过缓存分页读取其完整工具输出，并以当前源码交叉核对）
- `Cargo.toml`、`app/package.json`、`app/src-tauri/Cargo.toml`、`package.json`
- `src/main.rs`、`src/lib.rs`、`src/core/mod.rs`、`src/core/all.rs`、`src/core/cli.rs`、`src/core/jsonrpc.rs`、`src/core/types.rs`、`src/core/runtime/builder.rs`
- `src/openhuman/mod.rs`、`src/openhuman/agent/mod.rs`、`src/openhuman/agent/tinyagents/mod.rs`、`src/openhuman/agent/harness/session/mod.rs`、`src/openhuman/agent/harness/session/types.rs`、`src/openhuman/agent/harness/session/turn/graph.rs`、`src/openhuman/agent/messages.rs`
- `src/openhuman/agent/profiles/types.rs`、`src/openhuman/agent/profiles/ops.rs`
- `src/openhuman/config/mod.rs`、`src/openhuman/config/schema/types.rs`
- `src/openhuman/memory/mod.rs`、`src/openhuman/memory/api.rs`、`src/openhuman/memory/ops/mod.rs`、`src/openhuman/memory/ops/documents.rs`
- `vendor/tinymemory/core/src/traits.rs`、`vendor/tinymemory/core/src/rpc_models.rs`
- `app/src/main.tsx`、`app/src/App.tsx`、`app/src/services/coreRpcClient.ts`、`app/src-tauri/src/core_process.rs`、`app/src-tauri/src/lib.rs`
- `tests/json_rpc_e2e.rs`、`tests/memory_roundtrip_e2e.rs`、`tests/observability_smoke.rs`、`src/core/all_tests.rs`
- `app/test/vitest.config.ts`、`app/test/core-rpc-node.test.ts`、`app/test/e2e/specs/memory-roundtrip.spec.ts`、`scripts/test-rust-with-mock.sh`

本文件已吸收此前 `细探-OpenHuman.md` 的源码分析结论；后续只维护本文件，旧细探笔记不再作为独立事实源。

本文件只在项目根新增/更新 `ARCHITECTURE.md`；未安装依赖、未运行服务或测试、未修改既有源码、未提交 Git。

---

## 第三轮：通用底座映射（基于当前 checkout 的真实源码）

### 1. 证据边界与裁决口径

本轮不是把 OpenHuman 的目录名直接改写成平台目录，而是把已存在的通用契约、宿主适配、运行时治理和外部入口拆开。证据优先级为：当前源码/`Cargo.toml` → 当前 vendor 子模块源码 → `AGENTS.md`/开发文档 → 旧细探线索。当前 checkout 的正式文档已声明旧 `细探-OpenHuman.md` 已吸收；本轮在项目根及其研究父目录未发现仍可单独读取的 `*细探*` 文件，因此不把不存在的旧笔记当作证据。

本轮增加的结论分为三类：

- **吸收**：源码已经把通用边界做成独立 crate/trait/adapter，可作为平台底座模式。
- **隔离**：能力有通用形状，但产品策略、身份、权限、持久化 owner 或外部 provider 仍必须留在 OpenHuman 宿主。
- **待核**：存在源码或测试线索，但未在本轮运行真实构建、服务、第三方 provider 或跨进程恢复，不能写成“运行已证实”。

代码图证据不适用于本项目：OpenHuman 没有 `.codegraph/` 索引；因此本轮所有源码事实均来自目标仓库本地文件读取，不借用其他仓库的代码图、记忆或验证记录。

### 2. 四层映射总表

| 组件/能力 | 支持库（通用契约/原子机制） | 模块库（领域装配/语义适配） | 运行核心（生命周期/并发/持久化协调） | 统一网关（公开入口/认证/投影） |
|---|---|---|---|---|
| TinyAgents | `vendor/tinyagents/src/harness/` 的 `ChatModel`/`Tool`/middleware/limits/retry/stream；`registry` 的命名能力目录、`ModelCatalog`、`ModelRouter`；`graph` 的节点、`Command`、`Checkpoint`、`Interrupt`、reducer、子 agent；`harness::run_queue` 的三 lane 队列和 `CancellationToken` | `src/openhuman/agent/tinyagents/`：OpenHuman `Provider`/`Tool`/`ChatMessage` ↔ TinyAgents 类型转换、工具策略、prompt/context 组装、子 agent、progress/replay | `src/openhuman/agent/harness/session/` 的产品会话壳、turn graph、run queue、wall-clock/取消上下文、transcript/session DB、workspace 与预算；宿主决定模型路由、重试、深度和策略 | `src/core/jsonrpc.rs`、CLI、channel/HTTP/MCP 入口；只接收请求、认证、创建 run/session identity、发布 progress/结果，不直接实现 model↔tool loop |
| TinyFlows | `vendor/tinyflows/src/model/` 的可序列化 `WorkflowGraph`/`Node`/`Edge`/inputs/agent definitions；`compiler`/`validate`；`engine` 的 graph lowering、branch/fan-out/fan-in、`RunInput`、合作取消；`caps` 的宿主能力 trait | `src/openhuman/flows/tinyflows/` 的 `build_capabilities`、LLM/tool/http/code/agent/memory/state/resolver adapter；`src/openhuman/flows/` 的 flow builder、节点语义、发现和工具 | `src/openhuman/flows/store.rs` 的 `flow_definitions`/`flow_state`/`flow_runs`/revisions；`checkpoint_sqlite.rs` 的 `checkpoints.db`；`run_registry.rs` 的 in-flight token、RAII deregistration、resume/cancel 并发保护；启动、孤儿 run 对账和审批恢复 | `src/openhuman/flows/schemas.rs`/`ops.rs`、`core/all.rs` 的 flow RPC/controller；网关不得绕过 `WorkflowStore` 或直接把模型输出当作执行结果 |
| TinyChannels | `vendor/tinychannels/src/traits.rs` 的 `Channel`/`ChannelMessage`/`SendMessage`；`channel/` 的 inbound envelope/outbound intent/session key/receipt；`delivery/` 的 durable queue、retry/backoff、unknown-send reconciliation；`host/` 的 object-safe capability surface；各 provider 的 transport adapter | `src/openhuman/channels/host/` 把 STT/TTS、approval、reaction、conversation、event sink、lifecycle、allowlist 映射到 OpenHuman；`providers/` 和 runtime dispatch 只组合 provider 与 agent 语义 | `src/openhuman/channels/runtime/` 的 listener/dispatch/supervision、并发上限、启动/停止；宿主提供 durable delivery store、连接凭据和 session history；provider 任务必须由 runtime 统一取消、回收和重启 | channel controller schemas/ops、webhook/relay/Socket.IO/HTTP 入口负责认证、连接管理和状态投影；外部平台错误转换在 gateway/adapter，不泄漏 provider SDK 类型到 agent loop |
| TinyMemory/TinyCortex | `vendor/tinymemory/api/` 的 engine-neutral value/error/capability/provider/health/version/wire contract；`tinymemory` 的 driver registry、mandatory capability composition；`vendor/tinycortex` 的 SQLite/vector/chunk/tree/retrieval/ingest primitives | `src/openhuman/memory/` 的 RPC schemas/read RPC、agent tools、memory guard、driver binding、config mapping、host seam、memory agent；`src/openhuman/flows/tinyflows/memory_adapter.rs` 只把 flow scope 映射到既有 memory API | `tinymemory-core` 的 store/ingestion/queue/worker/tree/sync 运行机制由引擎持有；OpenHuman 持有 per-workspace singleton、guard 调用顺序、连接/迁移/后台 service 生命周期和 provider admission；第三方 driver 不能自报 embedded/external class | memory controller/RPC、MCP/CLI、agent tools 是唯一公开读写面；gateway 负责 namespace/scope/taint/approval/auth 及结果 envelope，不能把 `UnifiedMemory`/SQLite 连接暴露给调用方 |
| TinyBus | `vendor/tinybus/crates/tinybus/` 的 `Connection`、broker、message、proxy、service/interface、generic typed `EventBus`、transport、version/attestation；bounded outbox/signal buffer | `src/core/events.rs` 的 `DomainEvent` 目录和 `src/openhuman/*/bus.rs` 的事件订阅/投影；事件名称、payload、domain 由 OpenHuman 定义，TinyBus 不认识产品语义 | `src/core/bus.rs` 的初始化、memory/UDS transport 选择、connection/name/subscription 生命周期、断线/关闭诊断；跨进程 provider 是独立 crash domain | controller/HTTP/SSE/Socket.IO 把内部事件投影给 UI/客户端；TinyBus 本身不是业务网关，也不能成为第二套 RPC registry |

**层间硬边界：**支持库只拥有稳定、可替换、宿主无关的 trait/value/error/transport 原语；模块库只做领域编排和一次语义转换；运行核心只拥有 run/session/queue/checkpoint/worker/connection 的生命周期与一致性；网关只拥有认证、公开 schema、请求路由和结果/事件投影。模型人格、OpenHuman prompt、用户身份、namespace 选择、审批理由、工具 allowlist、业务状态转换属于上层 Agent/宿主，不下沉为 Tiny* 通用能力。

### 3. 契约、事件、队列、会话、模型、存储的唯一 owner

| 对象 | 通用契约事实 | 唯一 owner 与禁止旁路 |
|---|---|---|
| 请求/结果/错误 | TinyAgents/TinyFlows/TinyMemory/TinyChannels 各自有 typed trait 和 error；TinyBus message/event 有序列化边界 | 网关负责外部 envelope；模块负责一次转换；禁止 controller、provider、agent tool 各自翻译同一错误码 |
| 事件 | TinyBus `Event<E>` 只要求 `domain()`，domain 变成 object path，`try_publish` 先本地投递再写 bus；OpenHuman `DomainEvent` 是产品 catalog | `src/core/events.rs` 是 catalog owner，`core::bus` 是 transport owner，gateway 只能订阅/投影；事件不能用 RPC 返回值旁路替代 |
| Agent 活动队列 | TinyAgents `RunQueue` 是内存、线程安全、三 lane FIFO：`Steer`（下一安全边界）、`Followup`（当前 run 后新 turn）、`Collect`（下一安全边界上下文）；源码没有容量/持久化 | OpenHuman run/session runtime 决定 admission、上限、溢出和清理；不能把三 lane 当 durable job queue，也不能让网关直接 mutate 内部 `Vec` |
| Flow/Memory/Delivery 队列 | TinyCortex queue 将 chunk 写入与 follow-up job 在同一 `chunks.db` 事务中；TinyChannels delivery queue 先持久化 outbound intent，再平台发送，支持 `SendAttemptStarted`/`UnknownAfterSend`；TinyFlows engine 只执行，不拥有 host workflow catalog | memory queue owner 是 TinyCortex store/worker；delivery queue store 由宿主实现但语义由 TinyChannels 定义；flow catalog/checkpoint owner 是 OpenHuman `flows/store` + `checkpoints.db`；三类队列不得合并成一个“任务表” |
| 会话与链路 id | TinyAgents `SessionRecord` 有 parent/session_key/thread/model/status/usage/transcript；TinyFlows `RunId` 同时是 checkpointer `thread_id`，`RunOrigin` 记录 caller；TinyChannels 用 channel/account/conversation/thread/sender 规则生成 session key | OpenHuman session/profile/transcript 是产品 owner；flow 的 host-generated `run_id` 必须跨 resume 稳定；channel inbound 必须先规范化再生成 key；gateway 只接受/返回 correlation id，不允许 caller 自定审批去重 key |
| 模型 | TinyAgents `ChatModel`/`ModelProfile`/`ModelRegistry`/`ModelCatalog`/`ModelRouter` 只做 provider-neutral resolution、capability gate、usage/cost 形状；TinyFlows `LlmProvider` 只收 JSON request/response | OpenHuman `inference`、Config、route policy、credential/egress/成本策略是 owner；模块把产品 Provider 适配为 TinyAgents/TinyFlows 模型，不把 OpenAI SDK/凭据类型带进通用支持库 |
| 存储 | TinyAgents 可选 SQLite session/checkpointer、File/InMemory checkpointer；TinyFlows 可选 file workflow store；TinyMemory `Memory`/`MemoryProvider`、TinyCortex SQLite/vector/tree；TinyChannels delivery store 是 trait | 每一种事实只有一个写 owner：flow definition/run/checkpoint、memory document/chunk/tree、channel delivery/receipt、agent transcript/run ledger 分开；网关和模型只能经公开 service/trait 读写，禁止直连 SQLite |

### 4. 通用基础能力与上层 Agent 语义分界

**应归通用底座的部分：** typed request/response/error；对象安全 capability trait；provider/model/tool 名称解析；schema/version/migration；graph 节点调度、reducer、checkpoint、interrupt、fan-out/fan-in；合作取消和 deadline 传播；bounded transport queue、retry/backoff、idempotency/receipt、unknown-send reconciliation；session/run identity 的结构字段；health/shutdown；event serialization/routing；storage adapter trait、原子写、事务和可重放记录。

**必须留在 OpenHuman Agent/宿主的部分：**“这是哪个用户/人格/社区”、SOUL/MEMORY/prompt section、工具可见性与安全 tier、taint/PII/redaction/egress、approval 的产品策略、flow scope 到 `flow_<id>` 的可信来源、channel 是否响应的 reaction gate、记忆 namespace/跨 session 访问策略、模型 provider credential 和 fallback 选择、经验/学习/子 agent 的产品语义、RPC 方法名和客户端 UI 投影。TinyFlows 的 `memory` node 是 host delivery surface，不拥有记忆权限；TinyChannels 的 `TurnDispatcher` 是宿主注入的能力，不等于 channel crate 定义 Agent。

**不可接受的“通用化”方式：**把 `AgentProfile`、OpenHuman `DomainEvent`、approval decision、用户 namespace、provider secret、OpenHuman `ChatMessage` 或业务 tool result 下沉到 Tiny*；在每个 provider 复制一套 session key/error/retry；绕过 `MemoryGuard`、`ChannelHost`、`WorkflowStore` 或 `run_turn_via_tinyagents_shared` 直接调用引擎；把“模型生成了某状态”当作状态 owner。

### 5. 唯一可审计链路

```text
UI / CLI / channel webhook / MCP / embedded host
  → 统一网关：认证、schema、限流、公开 request/response、correlation_id
  → 运行核心：CoreRuntime/controller dispatch，创建 host-owned session/run_id，绑定 cancellation/deadline/ledger
  → 模块库：agent turn / flow / channel / memory 领域编排，只做一次参数和结果转换
  → 支持库契约：TinyAgents / TinyFlows / TinyChannels / TinyMemory / TinyBus typed trait
  → provider/engine：模型、工具、channel SDK、TinyCortex driver、TinyBus peer
  → 权威存储：transcript/run ledger、flow DB/checkpoints、delivery queue/receipt、memory SQLite/chunks/tree
  → 统一事件/诊断/资源释放
  → 网关 projection：RpcSuccess/RpcFailure、SSE/Socket.IO progress、receipt/status/history
```

每个原子能力必须只有一个公开 owner、一个注册/调用入口和一个错误映射点。`src/openhuman/agent/tinyagents`、`flows/tinyflows`、`channels/host`、`memory/guard` 是四个明确适配点；它们可以组合多个底座能力，但不能各自再建一套模型路由、任务队列、事件总线或持久化协议。TinyBus 事件链与 RPC 链并行但不侧写事实：事件用于通知/投影，权威状态仍由对应 store/service 写入。

### 6. 资源生命周期与失败终态

| 资源 | 创建/持有者 | 正常完成 | 业务失败 | 超时/主动取消 | 宿主崩溃/重启后的要求 |
|---|---|---|---|---|---|
| Agent model/tool stream、middleware、response cache | TinyAgents harness 创建；OpenHuman adapter 提供 model/tool；run runtime 持有 | 发出 terminal outcome，flush journal/usage，关闭 stream/cache 引用 | 保留结构化 failure/tool outcome；retry 只由单一 harness policy 执行 | OpenHuman 设置 `max_wall_clock_ms`（默认源码常量 600 秒，可 env 覆盖）；TinyAgents token/graph cancellation 是 cooperative，正在执行的 node/call 可能先完成，宿主仍须 hard abort 超时任务 | 新进程不得继承“running”假状态；session/run ledger 标为 interrupted/recoverable，未提交副作用不得伪造成功 |
| RunQueue / steering / sub-agent | TinyAgents `RunQueue` 与 cancellation token；OpenHuman `run_cancellation_context`/subagent depth 持有 | 逐 lane drain，run guard/drop 清理 | 清空或保留可诊断 item 由宿主策略决定，不能静默重放 | cancel 后下一安全边界停止新工作；followup 不应在取消 run 内执行 | in-memory queue 丢失是预期，durable follow-up 必须先落 host ledger/queue；子 agent 父子 lineage 必须可判定 |
| Flow graph/checkpoint/flow DB | engine 运行 graph；OpenHuman store/checkpointer 持有 SQLite 连接和文件 | `flow_runs`/steps 与 checkpoint 完成，RAII run guard 移除 in-flight 项 | 记录 `Failed`、error、diagnosis；checkpoint 不删除历史 | engine `CancellationToken` 只在 node boundary 生效；审批是 `PendingApproval`，不是失败；resume 使用同一 host `run_id`/thread_id | `Running` 进程消失后启动扫描改为 `Interrupted`；checkpoint/revision 保留；恢复必须防重复 resume 和 stale checkpoint |
| Channel listener、mpsc、typing/draft、provider connection | `channels/runtime` 启动/监督；TinyChannels `Channel`/`ProviderContext` 持有 provider | stop typing/finalize draft、关闭 listener/HTTP/WS、注销 lifecycle hook | provider error 分类为 permanent/transient，状态进入诊断，不能无限重启 | listener cancellation 要关闭 sender/child task；send deadline 不能只取消等待而不标记 attempt | outbound 已持久化但平台发送未知时进入 `UnknownAfterSend`，重连先 reconcile，不能盲目重复发送；连接/订阅 RAII 释放 |
| Durable delivery queue/receipt | TinyChannels 语义，host 实现 `DeliveryQueueStore`；每项带 idempotency intent | ack 后移除 pending，保存 receipt | `sent_before_error`、permanent、retry_count 进入失败/待恢复分支 | backoff、最多 `MAX_RETRIES=5`（源码常量）；主动 cancel 不得丢掉已经持久化的 intent | `SendAttemptStarted`/`UnknownAfterSend` 必须可读；恢复统计区分 recovered/failed/deferred/skipped，平台确认后才 ack |
| Memory connection、transaction、embedding、ingest job/worker | TinyCortex store/queue/worker；OpenHuman guard/driver/global singleton | 同一事务提交 document/chunk + job；worker mark done；查询返回 citation/provenance | typed `MemoryError`/opaque backend error、job failed 可重排；taint 不得被降级丢弃 | worker lease/deadline 释放 claim；embedding/LLM call 超时不能让 SQLite transaction 长时间持有 | stale lock/job recovery；SQLite WAL/连接重建；driver `shutdown` 幂等，rebind/进程退出调用两次也不能 double-free |
| TinyBus connection/outbox/signal subscription | `Connection` 创建 writer/dispatch task、bounded outbox 1024、signal buffer 256；`EventBus` attach subscription RAII | drop last handle 关闭 transport；subscription handle drop 取消 handler | `try_send`/broker error 必须告警；本地 loopback 已投递不应被描述成完全丢失 | call 默认 30 秒 deadline，超时只停止等待，不取消远端工作；调用方需用 correlation/remote cancellation 另行治理 | dispatch task、socket/UDS、well-known name 必须释放；peer 消失由 NameOwnerChanged/health 触发恢复，不靠无限等待 |

资源终态验收不能只看返回值：必须读回 `flow_runs`/checkpoint、delivery pending/failed、memory job locks、session status、子进程/连接/订阅和临时文件，确认没有无界残留。TinyAgents `RunQueue` 和 TinyBus broadcast 是内存/通知机制，不得当作崩溃恢复事实源。

### 7. 失败、超时、取消、崩溃矩阵

| 场景 | TinyAgents | TinyFlows | TinyChannels | TinyMemory/TinyBus | 验收判据 |
|---|---|---|---|---|---|
| 非法参数/未知能力 | schema/tool policy 返回 recoverable tool error 或 registry diagnostic；不调用 provider | `validate`/input resolver 在执行前拒绝；未知 capability 不得静默 no-op | channel definition/credentials/session envelope 先校验；未知 channel 不能发送 | capability admission/driver accessor 不匹配、未知 domain/path 返回 typed error | 请求未产生外部副作用；错误只在唯一映射点转换 |
| provider 暂时失败/断线 | `RetryPolicy` 有界重试，区分 retryable model error 与 permanent error | capability error 进入 node/run status，`on_error` 只能按显式 graph policy 处理 | provider health/连接状态；delivery backoff/reconcile | driver health false；bus transport 可重连但 event notification 不冒充事实提交 | 重试次数有上限，backoff 可观察，状态最终 settled 或明确 recoverable |
| 超时 | OpenHuman 600s wall-clock + 每次 call 剩余预算；远端 SDK 是否真的取消需另验 | node 已执行不被假定可抢占；run 标记 partial/cancelled 或 interrupted | 发送/监听超时停止等待并保留 send-attempt 状态 | TinyBus 30s call timeout 不取消远端；memory worker/embedding 要释放 lease/connection | 无“超时即成功”；读回 ledger/queue/checkpoint/locks |
| 主动取消 | `CancellationToken`/steering/abort guard；只阻止下一边界新工作 | run registry token + graph token；审批 pending 与 cancel 分离 | runtime 取消 listener/dispatch/task；已持久化 outbound 保留 | queue job 可重排；EventBus subscription drop；driver shutdown 幂等 | cancel 请求幂等，重复 cancel 不破坏新 registration/新 run |
| 进程崩溃/强杀 | session/run 从 running 重建为 interrupted；内存 queue 丢弃但 durable ledger 可审计 | checkpoint chain 保留，孤儿 run sweep；同一 run 不允许双 resume；flow DB 与 checkpoint 分离事实明确 | unknown send 不可猜；重连 reconcile；关闭 provider/child tasks | memory stale locks/jobs recovery；bus name/connection/receiver 清理；不把本地 event buffer当持久事件 | 新进程独立读回状态，重复恢复幂等，无 half-committed success |
| 重复提交/重复事件 | stable session/run id、tool call/result、subagent lineage 可去重 | host `run_id` 与 checkpoint thread_id 稳定；duplicate resume/registration 有保护 | intent idempotency key、receipt、session key | memory upsert `(namespace,key)`；TinyBus 本地 loopback+broker 不重复给同一订阅者 | 同一语义请求最多一个外部副作用；重复操作结果可解释 |

### 8. L0-L4 验证分层

| 等级 | 验证对象 | 本轮证据/命令 | 通过含义与当前状态 |
|---|---|---|---|
| **L0 证据身份** | 根目录、源码路径、vendor 版本、旧细探是否存在、修改范围 | 目标路径本地读取；`AGENTS.md`、`ARCHITECTURE.md`、各 `Cargo.toml`；`find` 类搜索等价由文件索引完成 | 已完成静态核对；OpenHuman 代码图不可用，不能把其他项目图当证据 |
| **L1 文档/契约静态** | Markdown 结构、四层映射、唯一链路、矩阵、源码路径存在、只改正式文档 | `python3 -c` 断言 `ARCHITECTURE.md` 非空且含 `第三轮`、`TinyAgents`、`TinyFlows`、`TinyChannels`、`TinyMemory`、`L0-L4`、`失败`、`崩溃`；`git diff --check`；`git diff --name-only` | 本轮应执行并记录退出码 0；只证明文档与范围，不证明 Rust 行为 |
| **L2 类型/编译契约** | root/app Cargo manifests、feature/path 依赖、adapter 类型边界 | 受控命令：`cargo metadata --no-deps --format-version 1 --offline`（不编译、不启动、不触碰外部服务） | 可证明 manifest 可解析；本轮不把 metadata 当 `cargo check`，实际 compile 仍待核 |
| **L3 隔离运行** | TinyAgents/TinyFlows/TinyChannels/TinyMemory 单元与 hermetic mock：cancel/timeout/retry/checkpoint/queue/receipt/driver audit | 待执行：各 vendor workspace 的 `cargo test` 或 OpenHuman 定向 `cargo test`，必须固定 feature、报告 skip、禁止网络/真实账号 | 当前 ARCHITECTURE 旧轮已明确“未运行 build/test”；本轮不伪造通过 |
| **L4 真实链路** | OpenHuman core + Tauri/HTTP/RPC/channel/provider/memory SQLite/WAL/跨进程 crash/restart | 待执行：产品 feature 集构建、`scripts/test-rust-with-mock.sh`、`pnpm test`/定向 E2E、真实 bus/driver/provider（按环境） | 只有 L4 才能把“声明边界”升级为“运行证据”；外部服务缺失必须标 HOST_UNAVAILABLE/未验证 |

**本轮实际验证口径：**执行文档静态检查、范围检查和 `cargo metadata --no-deps --offline`；不运行依赖安装、服务、完整编译、第三方账号或真实 channel/memory provider。若任何命令失败，只记录失败与原因，不用历史平台项目的成功记录替代 OpenHuman 证据。

### 9. 第三轮裁决与后续装配计划

- **吸收**：TinyAgents 的 provider-neutral harness/graph/registry、TinyFlows 的 graph+caps seam、TinyChannels 的 envelope/intent/delivery/host seam、TinyMemory 的 contract+driver admission/TinyCortex engine split、TinyBus 的 generic typed event/peer transport，均可作为“支持库契约 + 宿主适配 + 运行核心治理”的参考底座。
- **隔离**：OpenHuman `AgentProfile`/prompt/security/approval、`DomainEvent` catalog、flow/channel/memory RPC、credential/namespace/connector policy 和 product stores 继续由模块库/运行核心/网关拥有；不能因 crate 独立就宣称已完成平台迁移。
- **待核**：跨组件统一 correlation/idempotency 规范、TinyAgents session ledger 与 OpenHuman session DB 是否可合并、TinyFlows `checkpoints.db` 与 flow DB 的备份/恢复原子性、TinyChannels delivery store 的具体 OpenHuman 实现、TinyMemory driver rebind/真实外部 provider、TinyBus UDS crash/reconnect 均需 L3/L4 复核。
- **装配顺序**：先冻结公共错误/资源/identity 字段 → 再冻结 support-library trait 与 capability registry → 再由模块库实现一次性 adapter → 运行核心接入生命周期/队列/ledger/checkpoint → 最后网关注册 schema/controller/event projection；任何一步缺测试不得新增第二入口。

本节是 OpenHuman 的第三轮底座映射输入，不是对系统工程平台生产底座的直接修改；后续如要落平台，必须另有需求登记、能力复用裁决、占用租约、验收契约和独立工作包。

---

## 第二轮源码核对：真实入口、运行状态与恢复边界

本节补充一次面向“能否从真实入口跑通并在失败后解释状态”的源码核对。它不删除或改写前面的细探结论；前文的底座映射回答“哪些能力适合抽象”，本节回答“当前 checkout 中请求从哪里进入、由谁持有状态、失败后落在哪里”。证据来自当前仓库的 `src/`、`app/src/`、`app/src-tauri/src/` 和 `vendor/` 直接依赖；没有把 README 或旧文档中的入口当成运行事实。

### 10. 真实入口矩阵

| 入口 | 真实源码入口 | 运行形态 | 认证/状态边界 | 结果与进度 |
|---|---|---|---|---|
| 桌面 UI | `app/src/main.tsx` → `App.tsx` → `coreRpcClient.ts` | Tauri webview；首次需要 `start_core_process` | shell 通过 `core_rpc_url`/`core_rpc_token` 给前端短期 bearer；非 loopback 明文 HTTP 经 `relay_http_rpc` | `/rpc` 返回 JSON-RPC；Socket.IO 将 token/tool/subagent/usage/approval 事件投影回 Redux |
| Tauri shell | `app/src-tauri/src/lib.rs` 的 `run()` 与 `generate_handler!` | Wry 宿主；`CoreProcessHandle` 在同一进程 Tokio task 内启动 core | URL/token、窗口、workspace/artifact、OAuth、MCP、通知和 hotkey 是 shell IPC；业务 controller 不在 shell 实现 | `core_process.rs` 的 ready/restart/shutdown 状态决定 webview 是否可用 |
| 独立 core CLI | `src/main.rs` → `openhuman_core::run_core_from_args` → `core::cli::run_from_cli_args` | 独立 Rust 进程；先加载 dotenv、初始化 master key，再解析全局 provider/model 覆盖 | `HostKind::detect_standalone()`；CLI 覆盖只存在于本进程，不改写 `config.toml` | `run/serve` 启服务器；`call` 直调 controller；`mcp`/`mcp-server` 走 stdio JSON-RPC；`memory`、`agent`、`sub`、TUI 等走专用命令 |
| HTTP/API | `core::jsonrpc::build_core_http_router` | Axum router；可选 HTTP server、SSE、Socket.IO、`/v1` 兼容 API | bearer/CORS/middleware 在 `rpc_handler` 前统一处理；controller schema 先校验参数，再进入 registry | `/rpc` 是 controller 唯一公开调用面；`/events*`/Socket.IO 是事件面，不是事实写入面 |
| AgentBox | `agent::agentbox::http::router`，由 core router 按 `OPENHUMAN_AGENTBOX_MODE=1` 挂载 | `POST /run` 返回 202，Tokio spawn 异步 job；`GET /jobs/{id}` 轮询 | 当前 `JobStore` 是进程内 `Arc<RwLock<HashMap>>`，不是 durable job store；单 job 有 `job_timeout` | `pending → running → completed/failed`；终态按 retention sweep，进程崩溃会丢失全部 AgentBox job 状态 |
| 嵌入 host | `CoreBuilder::new(...).services(...).domains(...).build()` → `CoreRuntime::invoke/serve` | Tauri、CLI、stdio MCP、云/团队 server 和测试 harness 可复用同一 core library | `HostKind`、`ServiceSet`、`DomainSet`、token source 由宿主显式组合；不是另一套路由 | in-process embedder 可用 `agent_progress::with_progress_sink` 接收实时 turn 事件 |

CLI 的实际分派不是“所有命令都转成 RPC”：`run/serve` 建 HTTP/core 服务，`call` 使用 `invoke_method`，MCP 使用 stdio server，TUI 直接驱动 runtime，`agent`/`memory`/`subconscious`/`tree-summarizer` 各自进入领域命令。通用 namespace 只在最后才按 `<namespace> <function>` 解析。因此客户端、CLI、MCP 和嵌入 host 共享 controller registry，但共享的是契约与 dispatch，不是相同的 transport。

### 11. Agent、工具、模型和渠道的真实调用链

#### Agent 与工具

Agent 的产品会话由 `agent/harness/session/types.rs` 的 `Agent`/`AgentBuilder` 持有：模型 source、工具 `Arc<Vec<Box<dyn Tool>>>`、预序列化 `ToolSpec`、memory、prompt/context manager、profile、workspace、transcript locator、event context、progress sink、policy 和迭代上限。`AgentBuilder` 是构造边界；`Agent::run_single`/interactive 与 session turn 是执行边界。

单轮并非 controller 直接调用 provider：

```text
入口（web chat / channel / CLI / AgentBox）
  → AgentBuilder / profile / config / memory / connected integrations
  → prompt + transcript + retrieved context + visible tool allowlist
  → ChatTurnGraph::run_chat_turn_graph
  → run_turn_via_tinyagents_shared
  → TinyAgents AgentHarness
  → model response
  → native tool calls 或 prompt-guided XML/P-Format recovery
  → ToolPolicy / approval / sandbox / tool execution
  → next model iteration 或 terminal outcome
```

`agent/tinyagents/model.rs` 是模型适配的关键证据：OpenHuman `ChatResponse` 被转换为 TinyAgents `ModelResponse`，同时保留 reasoning block、native tool calls、prompt-guided tool calls、token breakdown、charged USD 和 context window；未知工具由 TinyAgents `RunPolicy::unknown_tool` 处理，而不是在 provider 中静默忽略。工具 registry/spec 与 controller registry 是两套 surface：前者供模型回合使用，后者供 RPC/CLI 使用，但工具的安全过滤仍受宿主 policy 和 domain/capability gating 约束。

#### 模型

模型的真实 owner 是 `openhuman/inference/provider` + `Config`，不是 TinyAgents。渠道启动时 `channels/runtime/startup.rs::resolve_chat_workload` 先读取 `provider_for_role("chat", config)`：空值、`cloud` 或 managed inference id 走 cloud model；其他值走统一 workload factory，按 provider slug 构造专用 channel provider。相同的 workload resolution 还应覆盖 web/CLI/AgentBox 的 session factory；模型 source 在 Agent 内被共享给子 agent，使连接池、重试预算和 rate-limit 状态不被每个子 agent 复制。

模型路由至少有四个状态维度必须分开记录：配置中的 provider/model route、当前已解析的 model、请求级 usage/cost/context window、provider failure classification。429/408/502/503/504 等暂时错误由 provider/retry 层有限重试与 fallback；Sentry 过滤只是观测降噪，不能当作请求恢复机制。认证过期、用户配置错误、预算耗尽和网络抖动分别进入不同错误分类，不能一概写为“模型失败”。

#### 渠道

`channels/runtime/startup.rs::start_channels` 不是简单地启动几个 connector。它先初始化 TinyBus 和健康订阅者，再注册 conversation persistence、memory sync、Composio/Meet/task-source、approval/artifact/egress surface、agent handlers、AgentDefinitionRegistry 和周期任务，之后构造模型、runtime adapter、action sandbox/projects root，最后按配置创建 provider listener 与 dispatch loop。没有频道配置时，这条 runtime 可能不启动；因此必须把 always-on bootstrap subscriber 与 channel-dependent subscriber 分开核对。

`channels/runtime/supervision.rs::spawn_supervised_listener` 是渠道恢复入口：listener 返回 `Ok(())` 也按意外退出处理（例如 Discord reconnect/invalid-session/Close），发布 `ChannelDisconnected`/`HealthRestarted`，使用带上限的 jitter backoff 后重启；`tx.is_closed()` 才是 supervisor 的合作停止条件。成功重连不能把 backoff 永久重置为初始值，否则会形成 reconnect storm。渠道 outbound 仍应遵循 TinyChannels 的 intent/receipt/unknown-send 语义，不能因为 listener 重新连上就把未知发送当作失败或成功。

### 12. 状态、持久化与事实 owner

| 状态/数据 | 当前 owner 与形式 | 是否 durable | 重启后的真实含义 |
|---|---|---:|---|
| Agent transcript | `agent/harness/session/transcript*.rs` 的 append-only `session_raw` JSONL；`SessionTranscriptHistory` 绑定具体 transcript stem，保留 `_meta`、tool calls、reasoning、usage、compaction、`interrupted` | 是 | 通过 root thread/agent 的 locator 恢复；不能仅靠 TinyAgents `ChatHistory::messages`，因为会丢 request id、tool calls、turn usage 和 `_meta` rollups |
| Thread/UI projection | `threads/transcript_view` 从 transcript 投影；TUI/前端只保存视图和 Redux 状态 | transcript 是，视图缓存不一定 | 视图可重建；投影不是事实源，不能用 UI 已显示消息证明已持久化 |
| AgentBox job | `agentbox/store.rs` 的内存 HashMap；terminal retention sweep，running/pending 不 sweep | 否 | 进程退出后 job id 不可查询；必须向调用方暴露这种非 durable 语义，不能承诺 crash recovery |
| Agent/turn runtime | TinyAgents RunQueue、steering、progress sink、cancellation token、子 agent handles | 主要是内存 | 队列可丢失；若 follow-up/子任务需要恢复，必须先写 OpenHuman session/run ledger 或领域 durable queue |
| Flow | `flows/store.rs` 的 definitions/state/runs 与 `checkpoints.db` | 是 | orphan sweep 将消失的 running run 标成 interrupted；同一 host `run_id`/checkpoint thread_id 才允许 resume，禁止重复恢复造成双执行 |
| Memory | TinyCortex SQLite/vector/chunks/tree/queue；OpenHuman memory host 负责 guard、driver、singleton 和同步订阅 | 是 | stale lock/job 需要 recovery，embedding/ingest 不能把长期 SQLite transaction 当作外部模型调用容器 |
| Channel delivery | TinyChannels intent/attempt/receipt + host `DeliveryQueueStore` | 设计上是 | `SendAttemptStarted` 后无确认进入 `UnknownAfterSend`，重连先 reconcile；不得用“请求超时”推断平台未收到 |
| 配置/凭据/根目录 | `config.toml`/profile home；keyring/master key；security policy 区分 `workspace_dir` 与 `action_dir` | 部分加密持久化 | 启动先加载 dotenv 和 master key；凭据、session JWT、provider key 不能进入 prompt、日志或 status projection |

这里存在一个重要的边界：OpenHuman 有多个“状态”对象，但没有一个通用状态表可以替代它们。Agent transcript、flow checkpoint、delivery receipt、memory job 和 AgentBox polling record 必须分别读取；RPC/Socket.IO/前端 Redux 只是结果或事件投影。

### 13. 资源生命周期与失败恢复补充

#### 正常路径

1. 宿主建立 `CoreRuntime`，按 `ServiceSet` 启动 HTTP/Socket.IO/cron/channels/memory sync/MCP 等后台服务，按 `DomainSet` 注册 controller、tool、store 和 subscriber。
2. 入口为请求创建 correlation/session/run identity；Agent factory 绑定 profile、model source、tools、memory、workspace、transcript locator 和 progress sink。
3. TinyAgents harness 在单一回合内持有 model/tool stream、middleware、retry budget、context reduction 和 cancellation；每个工具调用经过 policy/approval/sandbox，再把结果转回 model loop。
4. terminal outcome 写 transcript/usage/journal 及领域事实；事件总线和 Socket.IO/SSE 只通知变化。随后 run guard、stream、task、subscription、连接和临时资源释放。

#### 失败路径

- **参数/schema/未知能力**：在 RPC/controller、flow validate 或 tool policy 边界拒绝，不能创建 provider side effect。
- **模型暂时失败**：由 provider/retry/fallback 做有限次数处理；最终结果必须是 settled failure 或 recoverable，不以空回复冒充成功。
- **工具失败/审批等待**：工具结果保留结构化错误；approval 是 `PendingApproval` 状态，不能被压扁成失败，也不能在重启后自动批准。
- **超时**：AgentBox `timeout(job_timeout, invocation)` 将 job 标成 failed；TinyAgents/OpenHuman turn 的 wall-clock、单 call budget 和 TinyBus 的 30 秒等待必须区分，因为“停止等待”不等于“远端工作已取消”。
- **主动取消**：cancellation token、run registry 和 listener `tx` 关闭应幂等；取消只阻止下一个安全边界的新工作，已经持久化的 delivery intent、transcript 和 checkpoint 不能被静默删除。
- **渠道断线**：supervisor 以 `Ok(())` 和 `Err` 都进入重连/健康路径，指数 backoff + bounded jitter；发送中的 attempt 由 delivery receipt 决定是否可重试。
- **进程崩溃/强杀**：启动扫描 durable run/checkpoint/delivery/memory job，把无 owner 的 running 状态改成 interrupted/recoverable 或 unknown；内存 RunQueue、progress event、AgentBox HashMap 直接丢失是已知语义。恢复必须使用稳定 id、lease/reconciliation 和幂等保护，不能凭“上次没有返回错误”重放外部副作用。

### 14. 第二轮核对结论

1. **真实主入口是 `CoreRuntime`，不是某个前端页面。** UI、Tauri、CLI、MCP、HTTP、AgentBox 和 embed host 最终都汇入 core 的 composition/registry/dispatch；不同入口只改变 transport、HostKind 和服务集合。
2. **Agent 是产品 session shell + TinyAgents loop。** profile、prompt、memory、workspace、transcript、tool visibility 和 approval 留在 OpenHuman；模型↔工具迭代、middleware、retry、limits 和 progress adapter 由 TinyAgents 接管。
3. **渠道是受监督的长生命周期运行时。** startup 负责注册跨域 subscriber 与资源，supervision 负责 listener 退出、健康事件、backoff、jitter 和合作停止；渠道连接恢复不等于消息投递恢复。
4. **状态事实按领域分片持久化。** transcript、flow、memory、delivery 和 AgentBox job 的 owner/恢复能力不同；只有 durable store 才能作为崩溃恢复依据。
5. **当前最容易误读的地方是 AgentBox。** 它有真实 HTTP 入口和明确状态机，但 `JobStore` 仅内存；文档、客户端和未来平台映射都必须把它标为“可轮询但不可重启恢复”，除非后续源码引入 durable store。
6. **失败恢复的最小审计闭环**是：记录稳定 identity → 记录 attempt/状态 → 释放或续租资源 → 重启扫描孤儿状态 → reconcile 未知外部副作用 → 只在幂等条件满足时 resume。事件、日志和 UI 状态不能替代这条闭环。

本轮仍未执行构建、启动服务、真实 provider/channel、数据库崩溃注入或跨进程 kill/restart；以上“真实入口”指源码入口已核对，不等于运行时 L3/L4 证据。仅修改本文件，保留既有细探和第三轮内容。

---

## 第四轮：深审裁决（交互线、状态、资源、恢复与文档冲突）

### 15. 审计范围与证据边界

本轮在目标 checkout 内分段读取了 React/Vite、Tauri、CLI/HTTP/MCP、TinyAgents、TinyChannels、AgentBox/JobStore、Rust integration tests 与开发文档。目标仓库没有 `.codegraph/` 索引，CodeGraph 首次探测明确不可用；因此本轮不借用其他仓库的代码图、MCP、Hermes、记忆或验证证据。只修改根 `ARCHITECTURE.md`，不修改源码和既有开发文档。

以下判断按证据强度区分：源码中的状态机、路由、存储和调用关系是“当前实现”；测试注释、设计文档和架构矩阵中的要求是“设计/验收约束”，不能自动升级为已实现能力。未执行编译、服务、真实 provider/channel、数据库故障注入或跨进程重启，所以本节不声明运行通过。

### 16. 端到端交互线

#### 桌面 UI 到 Rust core

```text
main.tsx
  → primeActiveUserId（优先读取 Rust active_user.toml）
  → React provider/gate chain
  → BootCheckGate/CoreStateProvider
  → coreRpcClient.callCoreRpc
  → 可信 loopback fetch，或非可信明文 HTTP 经 Tauri relay_http_rpc
  → /rpc auth/CORS/log middleware
  → legacy alias rewrite
  → core dispatch：core methods → controller registry → unknown method
  → domain handler / Agent / store / provider
  → JSON-RPC result；Socket.IO/SSE 仅作 progress/event projection
  → ChatRuntimeProvider / Redux / 页面
```

`PersistGate` 只保证 Redux 持久化片段完成 rehydrate；它不保证 core 已启动、Socket.IO 已连接、transcript 已落盘或后台任务可恢复。`BootCheckGate` 与 `CoreStateProvider` 解决 core snapshot，但 UI 的 socket、chat runtime 和页面状态仍是投影层。`chatRuntime` 只持久化 ready artifacts，streaming buffer、tool timeline 和 inference status 不应被解释为重启后的事实。

#### CLI、HTTP、MCP 与 AgentBox

CLI 并非所有命令都转成 HTTP：`run/serve` 启 core server，`call` 走进程内 `invoke_method`，`mcp`/`mcp-server` 使用 stdio JSON-RPC，TUI 直接驱动 runtime，领域专用命令进入各自 domain。HTTP `/rpc`、CLI controller dispatch 和 MCP host 共享 registry/契约，但 transport、认证和生命周期不同。AgentBox 是额外的 HTTP polling surface，不是 `/rpc` controller，也不是 durable scheduler。

AgentBox 当前实际链路为：`POST /run` 校验非空 `payload.message` → `JobStore::insert_pending` → `tokio::spawn` → `CoreAgentInvoker` 订阅 web-channel 事件并调用 `start_chat` → 按 `request_id` 等待 `chat_done/chat_error` → `JobStore` 写 `completed/failed` → `GET /jobs/{id}` 轮询。invoker 在 broadcast receiver lagged 或 closed 时立即失败，避免把丢失 terminal event 伪装成普通 timeout。

#### Channel outbound

TinyChannels 的 outbound 线必须是：intent 先进入宿主 `DeliveryQueueStore` → 标记 `SendAttemptStarted` → provider send → receipt 后 ack；`sent_before_error` 或平台结果不明时写 `UnknownAfterSend`，重启/重连先调用 `reconcile_unknown_send`。`UnknownSendReconciliation::Sent` 才允许 ack；`NotSent` 只有 `SendAttemptStarted` 状态允许重新发送；`UnknownAfterSend` 的 `NotSent`、`Unresolved` 或缺少 reconciliation 结果会移入 failed，而不是猜测未发送后盲重试。该语义与“连接恢复”分离。

### 17. 状态与资源裁决

| 表面 | 当前状态 | 事实 owner | 终态/资源边界 | 重启语义 |
|---|---|---|---|---|
| UI boot/socket/chat | Redux + providers；socket 按用户保存连接状态但不持久化 | Rust snapshot、Socket.IO 与 React store 各自负责自己的层 | provider cleanup/HMR stop；UI projection 可重建 | rehydrate 后重新 bootstrap/reconnect，不能恢复 streaming buffer |
| RPC | request → dispatch → JSON-RPC result；unknown method 返回 `unknown method: ...` | `core::dispatch` + controller registry | legacy alias 在 lookup 前重写；已知 probe unknown 只 debug/不报 Sentry，其他 unknown warn triage | 受 `DomainSet`/feature surface 影响的方法可合法变 unknown，不能把所有 unknown 当 bug |
| Agent turn | TinyAgents harness + OpenHuman session/transcript | session/transcript/run ledger | cooperative cancellation 在安全边界生效；timeout/drop 不等于 provider 已停止 | stale turn snapshot 和 orphaned `running` agent run 启动时标为 interrupted；内存 queue/progress 丢失 |
| AgentBox | `pending → running → completed/failed` | 进程内 `Arc<RwLock<HashMap>>` JobStore | terminal retention sweep；pending/running 不 sweep；每 job timeout 只写 failed | **不可恢复**：进程退出后 job id 不可查询；没有 cancel endpoint、durable ledger、orphan sweep 或 resume |
| TinyChannels delivery | pending + attempt/retry/recovery marker | 宿主实现 `DeliveryQueueStore`，TinyChannels 定义状态机 | `MAX_RETRIES=5`；permanent 进入 failed；未知平台结果保留 pending + unknown marker | 先 reconcile，平台确认后 ack；不能用 HTTP timeout 推断未发送 |
| TinyBus/event | bounded transport/broadcast notification | bus transport + `DomainEvent` catalog | 订阅/连接 drop 释放任务；事件不承担事实提交 | 本地 event buffer 不是持久事件；peer 恢复依赖健康/name-owner 机制 |

资源检查不能只看 HTTP 返回：必须同时检查 run/session status、transcript、delivery pending/failed、checkpoint、memory job lease/lock、socket/listener/subscription、临时目录和 Tauri 子进程。尤其 AgentBox 的 `tokio::time::timeout` 会取消等待中的 future，但不能证明由 `start_chat` 已经启动的外部 provider 或后台副作用已停止；因此 timeout 后只应宣称 job failed/unknown boundary，不宣称全链路取消。

### 18. Unknown-send、unknown-method 与取消

- **unknown-send** 是外部平台副作用不确定：必须保留 intent、attempt 时间、retry count、错误和 `UnknownAfterSend`，恢复时先 reconciliation。没有 receipt 不能 ack；没有可靠 reconciliation 也不能把重发当作安全默认值。
- **unknown-method** 是公开能力面不匹配：dispatch 先处理 legacy alias，再查 core methods 和 registry；`DomainSet`/Cargo feature 关闭的 controller 会从 live surface 消失。前端和 CLI 应依据 `/schema`/构建 surface，而不是对未知方法无限重试。
- **主动取消 Agent turn** 由 TinyAgents token、OpenHuman run context、run registry 和工具/监听器的合作停止共同完成，只保证在下一个安全边界不开始新工作。已持久化 transcript、checkpoint、delivery intent 不得因取消静默删除。
- **AgentBox 取消缺口**：当前 `/run` 和 `/jobs/{id}` 路由没有 cancel route；`JobStore` 也不保存每 job 的 cancellation token/abort handle。调用方无法区分“用户取消”“job timeout”“invoker error”，只能看到 `failed` 和字符串 error。这是当前实现缺口，不应在文档中描述成完整 cancel 状态机。
- **渠道监听取消** 以 supervisor 的 sender/child task 生命周期为边界；listener 正常返回也按意外退出进入监督/重连，只有合作关闭条件才停止。发送取消与 listener 重连不是同一操作。

### 19. 文档重复与冲突清单

| 文档 | 冲突 | 裁决 |
|---|---|---|
| `gitbooks/developing/architecture/tauri-shell.md` | 仍写 CEF child webviews、CDP scanners、provider webviews 和 CEF cache；当前源码/`AGENTS.md` 以 Wry、移除 scanner、in-process core 为准 | 以源码和本文件为准；该文档是过期历史说明，不能作为当前运行拓扑 |
| `CONTRIBUTING.md`、`CONTRIBUTING-BEGINNERS.md` | 仍把 Tauri/CEF、vendored CEF CLI 作为当前桌面构建前提 | 与当前 Wry 运行事实冲突；需单独维护文档清理任务，不能在本轮只改根文档后视为已解决 |
| `AGENTS.md` vs `gitbooks/developing/architecture/frontend.md` | AGENTS 已声明 Wry/in-process；frontend 文档 provider relationship 仍出现 CEF `WebviewHost` 与旧描述 | provider chain 以 `App.tsx` 的 generated source 为准；文档生成可刷新链条，但不会自动修复所有历史拓扑文字 |
| `ARCHITECTURE.md` 前文 vs AgentBox 源码 | 前文恢复矩阵描述了 durable run/recoverable 设计要求，容易被读成 AgentBox 已支持恢复 | 本轮明确拆开：flow/session/delivery 有各自 durable 语义；AgentBox JobStore 当前非 durable、不可 resume |
| TinyChannels 设计/实现 vs OpenHuman host | vendor 已提供完整 unknown-send/recovery contract，但本轮未找到 OpenHuman 具体 `DeliveryQueueStore` 实现的运行验证 | 只能确认 vendor contract；OpenHuman channel 的真实 durable store 接线仍是待核，不得写成已完成端到端保证 |

重复维护风险集中在三类目录：`App.tsx` generated provider chain 与 `frontend.md`、Tauri shell 历史拓扑与 `AGENTS.md`/源码、根 ARCHITECTURE 的设计矩阵与具体状态实现。后续应选择单一生成源或在文档中标注“设计约束/当前实现/待核”，避免同一状态机被复制后各自漂移。

### 20. 本轮结论与优先修复项

1. **P0 文档正确性**：将 AgentBox 明确标为 ephemeral polling job；禁止承诺重启恢复、取消或幂等重放。
2. **P1 运行可靠性**：若 AgentBox 需要生产级语义，应引入 durable job ledger、稳定状态/attempt 记录、每 job cancellation handle、启动 orphan reconciliation、查询幂等和明确 `cancelled/timeout/unknown` 状态；不能只把 HashMap 换成更长 retention。
3. **P1 外部副作用**：核对 OpenHuman channel host 是否实际实现 TinyChannels `DeliveryQueueStore` 与 `reconcile_unknown_send`；若未接线，必须把 unknown-send 章节标为 contract-only。
4. **P2 文档治理**：刷新或删除 CEF/CDP/旧 sidecar 叙述，保留历史迁移说明时加日期和“非当前运行事实”标记；generated provider chain 继续只从 `App.tsx` 生成。
5. **P2 验证缺口**：补 AgentBox timeout 后 provider 副作用、cancel/restart、JobStore eviction、unknown-send 三分支、unknown-method feature/domain gating、Tauri startup recovery 的隔离测试；当前 `tests/agentbox_e2e.rs` 明确 `#[ignore]`，不能算端到端通过。

本轮未运行测试或构建。已完成的是本地分段源码/测试/文档静态审计与根文档更新；CodeGraph 不可用，MCP/Hermes 未使用。
