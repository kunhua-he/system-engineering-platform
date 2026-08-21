# Claude Code 源码快照架构档案

> **唯一权威架构文档。** 本文只描述当前目录中的 Claude Code source-map 泄露镜像与可由源码确认的事实；原有 `细探-Claude-Code.md` 保留为历史细探证据，不再作为后续维护入口。后续若继续研究，只更新本文，并回到当前源码复核。
>
> **研究边界：** 该目录是 Anthropic 专有源码的公开暴露快照，README 将用途限定为教育、供应链与防御性安全研究；本文不复制源码、不改源码、不提供商业或对抗性使用指导。

## 1. 项目身份、证据边界与现状

### 1.1 身份与规模

| 项目 | 现场事实 |
|---|---|
| 项目根 | `/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/非Git源码/Claude-Code` |
| 内容类型 | npm 分发 source-map 暴露的 TypeScript 源码快照；不是官方 Git 仓库 |
| 现场规模 | 1,904 个文件；其中 `src/` 1,902 个文件；约 30,430,109 bytes |
| 文件类型 | `.ts` 1,332；`.tsx` 552；`.js` 18；`.md` 2 |
| README 基线 | 公开暴露日期 2026-03-31；TypeScript(strict)、Bun、React+Ink；README 声称约 1,900 文件、512,000+ 行 |
| 顶层内容 | `README.md`、`细探-Claude-Code.md`、`ARCHITECTURE.md`、`src/` |
| Git | 当前目录及其父级未发现 Git 仓库；`git status` 返回“not a git repository” |
| 依赖/构建材料 | 未发现项目根 `package.json`、`bun.lock*`、`tsconfig*.json`、npm/pnpm/yarn lock；快照不能直接按完整项目构建 |
| 测试材料 | 未发现 `tests/`、`__tests__/`、`*.test.ts(x)`；源码中存在 `src/tools/testing/TestingPermissionTool.tsx` 等测试辅助代码，但不是可运行测试套件证据 |

**证据路径：** `README.md:39-49,53-95,227-241`；现场盘点命令见本文 §10。

### 1.2 代码图与项目绑定结果

本轮按任务要求先调用 `project_context`，但专属 MCP 返回的绑定项目是 **`华世王镞_v3`**，根目录为 `/Users/hekunhua/Documents/Agent/PHP/华世王镞_v3`，MCP 实例标识为 `project_toolkit`，不是本任务目标。随后调用 `codegraph_explore` 时显式传入目标根，返回：目标目录不存在 `.codegraph/`，未建立代码图，不能查询符号或调用图。

因此本档案的源码证据来自当前快照的现场盘点、`README.md`、旧细探和定向源码阅读；**不把错误项目的代码图结果冒充为 Claude Code 代码图，也不把代码图缺失写成代码图通过。**

## 2. 总体流程图

```text
Bun 启动 src/main.tsx
  ├─ 顶层预取：profileCheckpoint / startMdmRawRead / startKeychainPrefetch
  ├─ Commander 参数与环境、托管设置、GrowthBook、插件/技能、MCP/LSP 初始化
  ├─ initializeToolPermissionContext() 建立权限上下文
  └─ REPL / print / SDK(headless) 选择
        │
        ▼
  QueryEngine.submitMessage()
    ├─ processUserInput() 解析用户输入与 slash command
    ├─ 组装 system init、system prompt、tools、agents、MCP clients
    ├─ recordTranscript() 先写用户消息，保证中途 Stop/崩溃后可 resume
    └─ query()
          │
          ▼
    queryLoop
      ├─ prependUserContext + appendSystemContext + tool schema/cache
      ├─ services/api/claude.ts → Anthropic/兼容 provider 流式 API
      ├─ assistant tool_use
      │     └─ toolOrchestration / StreamingToolExecutor
      │           └─ hasPermissionsToUseTool()
      │                 ├─ 整工具规则 → 工具 checkPermissions()
      │                 ├─ Bash：AST/语义/注入/路径/复合命令/沙箱/规则
      │                 ├─ deny / ask / allow + 可解释 decisionReason
      │                 └─ dontAsk、auto、acceptEdits、allowlist、classifier 收口
      ├─ allow → 工具执行 → tool_result → 继续模型循环
      ├─ 超上下文 → shouldAutoCompact() → compactConversation()
      │     ├─ PreCompact hooks → 摘要 API（PTL 截断重试）
      │     ├─ compact_boundary + summary + 保留段/附件/工具 delta
      │     └─ 失败计数与熔断；成功后重建上下文
      └─ result / error / abort
            ├─ recordTranscript() 写 JSONL（队列、100ms 批排空、100MB 分块）
            └─ gracefulShutdown / cleanupRegistry

--resume：loadTranscriptFile → 进度桥接/skip-set/snips/保留段重链
        → parentUuid 对话链 → 恢复 REPL 或 headless session

CCR 远程可选旁路：
initUpstreamProxy → CA bundle + localhost CONNECT/WebSocket relay
→ HTTPS_PROXY/SSL_CERT_FILE 等子进程环境 → CCR upstream
```

## 3. 真实分层与目录地图

```text
src/
├── main.tsx                         CLI 入口、启动编排、模式选择、优雅退出
├── QueryEngine.ts                   SDK/headless 会话级查询门面与状态
├── query.ts                         流式模型调用、工具循环、compact/recovery 状态机
├── Tool.ts                          Tool / ToolUseContext / 权限及进度类型契约
├── tools.ts                         工具全集、feature/env 过滤、默认 preset
├── commands.ts                      slash command 注册、feature 条件与懒加载
├── types/                           消息、权限、日志、SDK、工具等类型
├── schemas/                         Zod/配置相关 schema
├── hooks/                           Permission、生命周期、Pre/Post/Stop hooks
├── utils/permissions/               权限规则、决策管线、文件/路径安全
├── tools/BashTool/                  Bash 解析、沙箱、注入、重定向、超时与执行
├── tools/*Tool/                     文件、网络、MCP、Agent、Skill、任务等工具
├── services/api/                    Anthropic API、stream、retry、错误/成本
├── services/mcp/                    MCP 配置、连接、工具/资源/认证
├── services/compact/                自动/手动压缩、PTL 重试、边界/附件重建
├── utils/sessionStorage.ts          JSONL transcript、队列、resume、链修复
├── ink/                             React reconciler、Yoga、终端 frame/diff
├── components/、screens/、hooks/    Ink UI、REPL、交互状态
├── tasks/、coordinator/             本地/远程/多代理任务与协作
├── bridge/、remote/、server/        IDE/移动/远程/服务器边界
├── plugins/、skills/                插件与技能加载、缓存、命令注入
├── state/、bootstrap/、migrations/  状态、启动状态、配置迁移
├── upstreamproxy/                   CCR 出网代理与 WebSocket relay
└── native-ts/、keybindings/、vim/、voice/ 等专项子系统
```

### 技术栈与依赖边界

| 边界 | 当前源码显示 |
|---|---|
| 运行时/语言 | Bun；TypeScript strict；部分 CCR 路径兼容 Node |
| CLI/UI | `@commander-js/extra-typings`；React；自研/封装 Ink renderer；Yoga 布局 |
| 模型 | `@anthropic-ai/sdk`；`services/api/claude.ts` 支持 provider/fallback、stream、thinking、tool use |
| Schema | Zod v4；`src/utils/api.ts` 将 `inputSchema` 转 JSON Schema |
| 工具协议 | Anthropic tool schema；MCP SDK、MCP resources/elicitation；LSP |
| 搜索/执行 | ripgrep；Bash/PowerShell；tree-sitter Bash WASM（不可用时 legacy fallback） |
| 认证/出网 | OAuth、JWT、macOS Keychain；CCR upstream proxy、CA bundle、CONNECT over WebSocket |
| 观测/旗标 | GrowthBook/Statsig feature gates、事件遥测、OpenTelemetry/gRPC（README 声明） |

## 4. 契约与边界

### 4.1 启动契约

- `src/main.tsx:1-21` 在其余重型 import 前运行 `profileCheckpoint`、`startMdmRawRead`、`startKeychainPrefetch`；这是真实的顶层副作用和并行预取，不是 README 推测。
- `src/main.tsx:585-602` 的 `main()` 处理启动阶段，并注册 `SIGINT`；print/headless 模式避免与自身 handler 重复退出。
- `src/main.tsx:1747-1749` 调用 `initializeToolPermissionContext`，权限上下文在工具调用前建立。
- `src/main.tsx:3134-3146` 等路径调用 `launchRepl`；CLI 还存在 print、remote/direct-connect 等分支。
- `bun:bundle feature()` 与环境变量共同决定工具、命令、bridge、assistant、voice、remote、classifier 等是否进入当前构建；因此“源码存在”不等于“当前产物可达”。

### 4.2 QueryEngine / 查询契约

`src/QueryEngine.ts:130-172` 的 `QueryEngineConfig` 约束了 `cwd`、`tools`、`commands`、`mcpClients`、`agents`、`canUseTool`、AppState getter/setter、文件状态缓存、模型/预算/最大轮数、abort controller、SDK 状态等；`src/QueryEngine.ts:184-207` 明确一个 `QueryEngine` 对应一个会话，持有消息、权限拒绝、usage、文件缓存和 abort controller。

`submitMessage()` 的真实边界是：

1. `processUserInput()` 处理 prompt/slash command（`QueryEngine.ts:335-427`）；
2. 用户消息先进入 `mutableMessages` 并在 API 循环前 `recordTranscript()`（`QueryEngine.ts:430-463`）；
3. 加载 skills/plugins，yield system init（`QueryEngine.ts:529-554`）；
4. `query()` 产生流式消息、工具结果、compact boundary 和最终 result（`QueryEngine.ts:675-751` 及后续）。

成功结果包括 `duration_ms`、API 时长、turn 数、cost、usage、modelUsage、permission_denials、session id 等（`QueryEngine.ts:618-637`）。中途终止不应被当作成功；`query.ts:231-236` 说明 query generator 抛错或 `.return()` 时不会发出正常 completed lifecycle。

### 4.3 Tool 契约与注册

- `Tool.ts:15-21` 定义工具输入 JSON Schema；`Tool.ts:123-138` 定义不可变 `ToolPermissionContext`（mode、三类规则、附加工作目录、bypass/auto/headless 标志）；`Tool.ts:158-183` 的 `ToolUseContext` 绑定 options、abort、AppState、文件状态、MCP clients、hooks/UI 回调、资源更新和消息链。
- `tools.ts:173-193` 将 `getAllBaseTools()` 作为工具全集事实源；`tools.ts:193-250` 按环境、feature、权限模式和测试环境动态加入/移除工具。`tools.ts:253-260` 说明 blanket deny 还会在请求前从模型可见工具中筛掉。
- 工具模块通常同时提供 input schema、prompt、`checkPermissions`、执行函数和 UI/progress；不能仅以工具文件存在判断已注册或可达。
- `src/utils/api.ts:134-220` 形成 API 工具 schema：Zod → JSON Schema，session-stable base schema 缓存；strict、eager input streaming、defer loading、cache control 由 feature、模型和请求 overlay 决定。

### 4.4 权限契约

权限决策返回 `allow | deny | ask | passthrough` 语义，并携带 `decisionReason`；`src/utils/permissions/permissions.ts:473-480` 是总入口，`503-548` 在末端收口 `dontAsk` 与自动模式，避免早退绕过模式转换。当前源码可确认的顺序为：

```text
整工具 deny
 → 工具/内容 ask 与 tool.checkPermissions
 → 工具实现的 deny/安全检查
 → bypass 或 allow 规则
 → passthrough/ask
 → dontAsk→deny；auto→安全检查/交互要求/acceptEdits/allowlist/classifier
```

Bash 专用边界在 `src/tools/BashTool/bashPermissions.ts:1663-1768`：先 tree-sitter AST 或 parse-unavailable fallback，too-complex 仍尊重精确 deny；`1771-1806` 做语义级危险检查；`1829-1843` 做沙箱 auto-allow；`1845-1876` 先查 exact rule，再并行检查 Bash prompt deny/ask。工具实现最终仍必须在 `BashTool.tsx:539-541` 调用 `bashToolHasPermission`。

权限持久化在 `src/utils/permissions/PermissionUpdate.ts:55-187`：`setMode`、add/replace/remove rules、add/remove directories 更新内存上下文；`supportsPersistence()`（`208-215`）只认 `localSettings`、`userSettings`、`projectSettings`。`policySettings`、CLI/session 等来源不能由该函数简单视为同一持久化目标。

### 4.5 会话/JSONL 契约

- `sessionStorage.ts:202-229` 根据 session/project 目录生成 JSONL 路径，原始 transcript 读取上限为 50MB。
- `sessionStorage.ts:129-155` 将 user/assistant/attachment/system 视为 transcript chain participant，progress 为 UI 临时状态，避免污染 `parentUuid` 链。
- `sessionStorage.ts:532-568` 的 `Project` 持有 per-file write queue、pending count、flush resolver、active drain；flush timer 100ms、单批最大 100MB。
- `sessionStorage.ts:606-686` 将 entry 按文件串行排队、批量 JSONL append，目录 0700、文件 0600；每个 entry 的 Promise 在对应批次 append 后 resolve。
- `sessionStorage.ts:1408-1412` 的 `recordTranscript` 负责消息链持久化，`1583-1585` 的 `flushSessionStorage()` 等待 Project flush。
- resume 在 `sessionStorage.ts:1839-1982` 进行 preserved segment 重链、snip removed UUID 撤销；`loadTranscriptFile`（源码搜索结果指向 `2306-2314`、`3468-3470`）读取并重建消息链。

**限制：** JSONL 追加依赖单进程队列和内核 append 原子性；现场未见跨进程 flock 的证据。旧细探所述 tail 扫描、SDK 外部 metadata 吸收和 pre-compact chain 修复应作为当前源码的补充线索，后续必须在具体函数上继续核实。

### 4.6 MCP/SDK/远程边界

- `main.tsx` 引入 `services/mcp/client.ts`、MCP config、官方 registry、resource prefetch；`ToolUseContext` 有 MCP clients、resources 和 URL elicitation handler（`Tool.ts:158-203`）。MCP 工具仍要经过统一 tool permission 入口。
- `entrypoints/agentSdkTypes.ts:1-31` 导出 SDK core/runtime/control/tool/settings 类型；但当前快照中公开函数 `tool`、`createSdkMcpServer`、`query`、V2 session、`getSessionMessages`、`listSessions` 等在 `73-182` 明确 `throw new Error('not implemented...')`。这说明“类型/门面存在”不能计为 SDK runtime 已实现；真实 CLI `QueryEngine` 路径与这些导出 stub 必须分开记录。
- `src/upstreamproxy/upstreamproxy.ts:79-152` 仅当 `CLAUDE_CODE_REMOTE`、`CCR_UPSTREAM_PROXY_ENABLED`、session id、token 均满足时初始化；失败统一禁用代理并保留可工作的会话。

## 5. 关键节点与真实对接链

| 节点 | 真实调用/输入输出 | 状态与失败分支 | 证据 |
|---|---|---|---|
| 启动预取 | `main.tsx` 顶层调用 MDM/keychain prefetch；输出缓存/预取句柄 | 模块加载前启动；主启动继续，具体失败处理在被调用模块 | `src/main.tsx:1-21` |
| 权限初始化 | CLI allowed/denied tools → `initializeToolPermissionContext` → AppState context | 配置/策略决定可见工具；模式与规则进入三桶 | `src/main.tsx:120-123,1747-1749`；`PermissionUpdate.ts:55-95` |
| 用户输入 | `QueryEngine.submitMessage` → `processUserInput` → messages/model/commands | slash command 可改变 messages/model；异常不应伪造 API success | `QueryEngine.ts:335-427,430-463` |
| 系统提示词/工具 schema | `fetchSystemPromptParts` + `utils/api.toolToAPISchema` → model request | 静态基础 schema session 缓存；动态 tool loading/cache overlay 每请求变化 | `QueryEngine.ts:72,675-686`；`utils/api.ts:134-220` |
| 模型流 | `query` → `deps.callModel` → `services/api/claude.ts` | stream event/assistant/tool_use；fallback 由 `FallbackTriggeredError` 切 model；异常进入 query error | `query.ts:219-238,650-686,893-952` |
| 工具授权 | tool_use → `wrappedCanUseTool` → `hasPermissionsToUseTool` → tool check | deny/ask/allow；headless 无 prompt 时可 auto-deny；AbortError/UserAbort rethrow | `QueryEngine.ts:243-260`；`permissions.ts:473-548` |
| Bash 安全 | command → AST/semantic/legacy → sandbox/rules/path/subcommands → PermissionResult | too-complex/parse unavailable 默认 ask；exact deny 不降级；复杂命令、重定向与注入走多层检查 | `bashPermissions.ts:1663-1827,1829-1876` |
| 工具执行 | allow → `toolOrchestration`/`StreamingToolExecutor` → tool result | 结果继续 query；工具 abort/异常由 query/工具边界处理 | `query.ts:96-99`；`QueryEngine.ts:675-686` |
| 权限并发裁决 | local UI / hook / classifier / bridge / channel → `claim()` → `resolveOnce()` | 先 claim 者胜；其他回调退出；abort 会清理订阅/队列 | `interactiveHandler.ts:46-75,108-146,356-405,410-493` |
| 会话落盘 | messages → `recordTranscript` → per-file queue → JSONL append | 100ms drain、100MB chunk、每 entry Promise；append 失败尝试建目录重写 | `sessionStorage.ts:606-686` |
| 自动压缩 | `shouldAutoCompact` → `compactConversation` → summary/attachments/boundary | source guard、disabled flag、context collapse suppress；连续失败熔断 | `autoCompact.ts:160-238,241-265,312-349` |
| 压缩重建 | PreCompact hooks → summary API → PTL truncation → attachments/MCP/agent delta → boundary | no summary/API error/prompt-too-long 均记录失败；成功清 cache 并重建 | `compact.ts:387-515,517-599` |
| resume | JSONL → progress bridge → snip/preserved relink → chain | malformed preserved metadata 可 no-op；空消息报错/返回空 | `sessionStorage.ts:1839-1982,2306-2314` |
| CCR proxy | token → CA bundle → relay listener → unlink token → child env | CA/relay 失败 fail-open；listener 成功后才 unlink token | `upstreamproxy.ts:105-150` |
| relay | CONNECT fragments → WS → protobuf chunks → client TLS | header >8192→400；非 CONNECT→405；WS 未建立→502；已建立后只 close | `relay.ts:295-342,378-427` |

## 6. 资源生命周期与所有权

| 资源 | 创建/持有 | 正常释放 | 失败、超时、取消、崩溃处理 | 残留验证状态 |
|---|---|---|---|---|
| QueryEngine 消息/文件 cache | constructor 接收 `initialMessages`/`readFileCache`；每会话持有 | compact 清 file cache；会话结束由外层 shutdown/GC | abort 由共享 `AbortController` 传播；进程崩溃依赖已排队 transcript 与 resume | 静态可见；无运行时内存/heap 实测 |
| AbortController/permission callbacks | QueryEngine 或 ToolUseContext 注入；interactive handler 注册 local/hook/classifier/bridge/channel | `claim()` 后取消其他 racer；abort listener `once`/显式移除 | 用户 Esc、SIGINT、API user abort 应进入 abort；某些 async provider 行为未实测 | `interactiveHandler.ts` 有清理代码，未做竞态执行验证 |
| transcript 文件/目录 | Project 首次写入 materialize；append queue 持有 entry resolve | drain 后 resolve；flush 等 pending 清空；cleanup reappend metadata | append 失败 mkdir 重试；进程 kill 可能留下已写前缀/未 drain 队列；resume 通过链修复 | 路径/权限/队列规则有源码证据；未实际写临时 session 验证 |
| JSONL chain metadata | `uuid`/`parentUuid`、compact boundary、snip/preserved segment | 追加式；不物理删除，加载期 skip/relink | 畸形 preserved chain 可 no-op，snip 用 removed UUID；崩溃恢复依赖边界之前已持久化 | 未用样本 JSONL 做 round-trip |
| API HTTP/stream | `services/api/claude.ts`/provider 创建；query 消费 async stream | stream 结束或 abort；cost/usage 更新 | retry/fallback/error 分类；prompt-too-long 触发 compact/recovery；provider 实测缺失 | 仅源码结构证据；无 API key/外部服务实测 |
| Bash 子进程/沙箱 | BashTool 执行器创建 shell/后台任务，SandboxManager 提供边界 | 正常退出或 tool stop；后台任务由 task/stop 体系管理 | 默认/最大 timeout、autobackground、run_in_background；崩溃/孤儿进程未在本轮运行验证 | 旧细探与 prompt 记录限制；源码未构成现场清理证据 |
| MCP/LSP client | main/services 初始化连接、资源与工具 | shutdown/cleanup registry | server unavailable、elicitation、tool error 走 MCP 错误/用户交互；断线重连未做运行验证 | 代码路径存在，连接生命周期未实测 |
| Permission dialog/bridge/channel | interactive handler 建 queue item、remote request、abort listener | `removeFromQueue`、unsubscribe、cancelRequest、clear classifier state | claim winner；channel send 失败只记录错误，local dialog 作为底 | 静态清理路径明确；多路并发未实测 |
| CCR relay/WS/timer | relay 绑定 localhost ephemeral port；每连接 WS、pending buffers、30s pinger | `stop()`、`cleanupConn` 清 interval/close WS；upstream registerCleanup | CONNECT 不完整超 8192→400；WS error 未 established→502；close/已 established→end；无显式 relay handshake timeout | 代码有 `closed` guard；无 socket/WS 压测 |
| CA/token 文件 | 读取 token，下载/写 CA bundle | relay listener 确认后 unlink token；cleanup relay | CA/relay 失败保留 token 便于 supervisor retry；`prctl(PR_SET_DUMPABLE,0)` 降低 heap 泄露面 | 仅静态证据；未在 CCR 容器验证 |

**资源结论：** 源码明确覆盖正常完成、业务失败、权限取消、部分网络失败和部分压缩失败；对进程崩溃后的所有临时进程、端口、锁、WS、MCP/LSP、后台任务是否无界残留，当前没有本轮运行证据，必须标记未验证，不得由 cleanup 函数存在推导“已清理”。

## 7. 失败、超时、取消、崩溃矩阵

| 场景 | 源码策略 | 当前结论 |
|---|---|---|
| 参数/规则非法 | Zod/schema、permission parser、工具 checkPermissions；具体工具差异化 | 静态存在；未执行非法输入矩阵 |
| tool deny | 返回 deny 与 `decisionReason`；headless 可自动拒绝 | 已由源码确认，未做各 mode 全矩阵 |
| ask 无交互 | `shouldAvoidPermissionPrompts` → asyncAgent/headless deny；dontAsk 在末端 ask→deny | 已由源码确认 |
| 多路同时批准 | `createResolveOnce` 的 `claim()` 原子先胜；hook/classifier/bridge/channel 清理其他回调 | 已读清理逻辑；竞态测试未验证 |
| Bash 复杂/解析失败 | too-complex/parse-unavailable 默认 ask，精确 deny 不降级；legacy fallback | 已由源码确认，tree-sitter availability 未实测 |
| 命令注入/路径越界 | AST、语义、legacy、redirect、path/sandbox 多层检查 | 有实现证据；不能宣称安全完备 |
| API 连接/429/5xx | `services/api/withRetry.ts`、错误分类、fallback model | 代码入口存在；没有 provider 请求验证 |
| prompt too long | compact 自身 PTL 按 API round 截断重试；超过重试上限报错 | `compact.ts:462-477` 已确认；未实测边界 |
| 自动 compact 连败 | `MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES` 后 circuit breaker | `autoCompact.ts:257-265,334-349` 已确认具体计数；未做连续失败执行 |
| 用户 Stop/SIGINT | abort controller、API user abort rethrow、main SIGINT 与 graceful shutdown | 控制流存在；OS 信号现场未发 |
| transcript 写入慢/失败 | per-file queue、100ms drain、100MB chunk、mkdir 重试；可显式 eager flush | 源码存在；磁盘满/NFS/并发外写未验证 |
| 进程在 API 回复前崩溃 | QueryEngine 先写 user transcript，目标是可 resume | 设计与调用点存在；未 kill/restart 实测 |
| compact boundary 前崩溃 | boundary 前 flush preserved tail；否则 resume 可能加载完整旧历史 | 注释明确风险与补救；未用故障注入验证 |
| relay 未建立/WS error | 400/405/502；`closed` 防双 close；已建立后不写 plaintext 502 | 静态存在；未做 CONNECT 分片/WS 断线压测 |
| CCR proxy 初始化失败 | fail-open，返回 disabled，子进程不注入新代理；成功监听后才删 token | 静态实现清晰；CCR 环境未验证 |
| 宿主/子进程崩溃 | cleanupRegistry、JSONL resume、relay cleanup 等分散补救 | 没有完整崩溃注入与现场残留证明，属于未验证高风险项 |

## 8. 防假绿验证分级（L0-L4）

| 等级 | “通过”所需证据 | 本轮状态 |
|---|---|---|
| L0 源码存在 | 文件、导出符号、源码路径和关键分支可读 | **通过（静态）**：已核对入口、QueryEngine、query、Tool、permissions、Bash、compact、sessionStorage、relay、SDK 类型等 |
| L1 结构闭合 | 入口→门面→注册/路由→provider→结果/事件/释放链能由路径串起来；关键契约不只在 README | **部分通过**：CLI 主链、权限链、transcript/compact/relay 链闭合；代码图不可用，且 feature-gated 分支需逐构建确认 |
| L2 本地可执行验证 | 有依赖/测试材料，实际运行 targeted tests、类型检查或最小 smoke，记录退出码与测试数 | **未通过/未执行**：无根 package/lock/tsconfig 与独立测试套件；未安装依赖、未启动服务、未伪造测试结果 |
| L3 真实集成验证 | 实际 provider、MCP/LSP、Bash sandbox、CCR relay、终端 UI、resume/compact 故障注入 | **未验证**：缺凭据/依赖/完整构建入口，且本任务只允许写架构文档 |
| L4 生产级证明 | 跨版本/跨平台、压力/竞态、超时/取消/崩溃后资源清点，独立证据与可重复命令 | **未验证**：快照非 Git、无构建与运行环境，不能声称生产就绪 |

**反假绿规则：** README 的规模/设计声明、旧细探的“已深入”、源码中的 test-only helper、函数名、日志输出、cleanup 注册和子代理/代码图自报都不能替代 L2-L4。特别是 `agentSdkTypes.ts` 中多处公开函数明确 `throw new Error('not implemented...')`，所以 SDK API 只能列为声明/未实现，不得列为已接通。

## 9. 旧细探吸收裁决

### 9.1 已吸收到本文

- 项目定位、来源、伦理与所有权边界；
- 启动预取、feature DCE、分层目录；
- 权限主顺序、Bash AST/legacy、sandbox、路径/注入/复合命令防护；
- `resolveOnce/claim` 多路权限竞态；
- JSONL transcript、写队列、分块、权限、resume 链、snip/preserved relink；
- auto compact 阈值/递归保护/PTL/附件重建/连续失败熔断；
- system prompt/tool schema 缓存纪律；
- Ink renderer、MCP/bridge/agent/skill/plugin 边界作为目录级架构；
- CCR upstream proxy、CA/token、CONNECT→WebSocket relay、chunk/ping/error/cleanup；
- 可借鉴模式均改写为“源码事实/待核”，没有把研究建议当作当前实现。

### 9.2 暂保留为“线索/待核”，未当作已验证事实

- 旧细探中的精确文件行数、内部事件/实验旗标全量清单、部分 GH/CC 编号与生产指标；
- “约 46K/29K/25K 行”的历史规模说法：当前 `QueryEngine.ts` 1,295 行、`Tool.ts` 792 行、`commands.ts` 754 行，说明旧细探与当前快照的单文件规模描述存在明显漂移；本文以现场当前文件统计为准；
- 具体模型名、内部后门变量、遥测成本/拒绝比例、CCR 后端私有设计文档；
- tree-sitter、Bash sandbox、MCP/LSP、Ink 的真实运行版本与跨平台行为；
- 旧细探提及但本轮未逐文件重新读取的 `permissions.ts` 其他分支、`systemPrompt` 全量动态段、`sessionStorage` 全量 loader 分支、多代理任务实现细节。

### 9.3 不吸收为架构事实

- 任何未能在当前源码或 README 找到对应路径的宣传性结论；
- 旧细探中与当前文件行数/路径不一致的精确规模；
- 将 Anthropic 内部实现直接映射为本平台生产契约的建议；
- 任何绕过权限、沙箱、供应链或所有权边界的操作性内容。

## 10. 本轮验证命令与退出码

以下命令均为只读盘点，不安装依赖、不启动源码服务、不生成构建物：

| 命令 | 结果 |
|---|---|
| `python3` 递归统计目标根文件、扩展名、顶层目录、关键文件行数 | **退出码 0**；1,904 文件，1,902 个 `src` 文件；`.ts/.tsx/.js/.md` 分布如 §1 |
| `git -C '/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/非Git源码/Claude-Code' status --short --branch` | 命令返回 Git fatal；目录确认为非 Git，不能记录 commit/branch |
| `search_files` 查找 `ARCHITECTURE.md` | 写入前不存在；本轮创建本文 |
| `search_files` 查找根 `package*.json`、`bun.lock*`、`tsconfig*.json`、`*.test.tsx`、`*.spec.*`、`__tests__` | 根配置/独立测试证据缺失；不能运行项目测试 |
| `project_context(task=...)` | 工具调用成功，但错绑 `/Users/hekunhua/Documents/Agent/PHP/华世王镞_v3`；不作为本项目代码图证据 |
| `codegraph_explore(projectPath=目标根, ...)` | 返回目标根无 `.codegraph/`；**代码图不可用**，未冒充通过 |

本轮没有声称 TypeScript 编译、单元测试、API、MCP、sandbox、终端 UI、CCR relay 或崩溃恢复通过。

## 11. 后续复核清单与剩余风险

1. 如需继续建档，先修正 `project_context` 的项目绑定，或明确为该非 Git 目录建立独立代码图；不得查询错误项目后引用其结果。
2. 若要 L2，必须获得完整依赖/构建入口或建立隔离的快照验证环境；验证产物和运行缓存不得写入源码快照目录。
3. 优先补充：`query.ts` 状态转换全表、`services/api/withRetry.ts` 重试分类、工具 orchestration、`sessionStorage` loader 全链、MCP/LSP disconnect、后台 Bash/task 进程回收。
4. 设计故障注入：API timeout/429/413、用户 abort、权限五路竞态、JSONL 中断写、compact boundary 中断、Bash 子进程超时、WS half-open/断线、宿主 SIGKILL；每项要读回文件/进程/端口/临时目录状态。
5. 重新核对当前快照与旧细探的漂移，尤其是 feature gate 的构建可达性、SDK stub 与 CLI 实现是否属于同一发布目标。
6. 许可证与供应链风险持续存在：该目录不应被当作可再分发的官方源码或生产依赖。

## 12. 证据索引

- `README.md:1-49`：来源、研究边界、规模；`README.md:53-95`：目录；`README.md:99-203`：工具/命令/服务/bridge/权限/feature summary；`README.md:227-280`：技术栈与免责声明。
- `src/main.tsx:1-21,585-602,120-129,141-160,1747-1749,3134-3146`：启动、预取、权限初始化、REPL。
- `src/QueryEngine.ts:130-207,335-463,529-554,675-751`：会话配置、输入、先写 transcript、查询输出。
- `src/query.ts:181-239,241-280,650-686,893-952`：query generator、stream、fallback/error。
- `src/Tool.ts:15-21,123-138,158-203`；`src/tools.ts:173-250`：工具与上下文契约/注册。
- `src/utils/permissions/permissions.ts:473-548`；`src/tools/BashTool/bashPermissions.ts:1663-1876`：权限/Bash 管线。
- `src/utils/sessionStorage.ts:129-155,202-229,532-686,1408-1412,1583-1585,1839-1982,2306-2314,3468-3470`：JSONL 资源、队列、flush、resume。
- `src/services/compact/autoCompact.ts:160-238,241-265,312-349`；`src/services/compact/compact.ts:387-515,517-599`：压缩、PTL、熔断。
- `src/hooks/toolPermission/handlers/interactiveHandler.ts:46-146,300-429,433-499`：多路权限竞态与清理。
- `src/upstreamproxy/upstreamproxy.ts:79-152,160-204`；`src/upstreamproxy/relay.ts:49-126,295-455`：CCR proxy/relay。
- `src/entrypoints/agentSdkTypes.ts:1-31,73-182`：SDK 类型与当前 stub 边界。
- `细探-Claude-Code.md`：旧细探，已逐章吸收/裁决，**保留不删除**。
