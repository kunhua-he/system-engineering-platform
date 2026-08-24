# DeepSeek-Harness 架构建档

> 项目根：`/Users/hekunhua/Documents/Agent/github 源码参考/10_agent_platform_reference/03_专项Agent源码/DeepSeek-Harness`
>
> 项目定位：DeepSeek 官方 agent harness（命令名 `dsh`），基于 vendored Cordis 的插件化运行时。仓库处于开发者预览阶段，当前架构允许破坏性调整。
>
> 本文是唯一的项目架构事实源，依据仓库根 `AGENTS.md`、`docs/architecture.md`、相关包 README、关键 TypeScript/Python 源码和已有 `细探-DeepSeek-Harness.md` 建档。旧细探保留为历史研究证据，不再作为并行架构文档维护；本文不替代各包 README、`docs/subsystems/` 或测试规范。

## 1. 总体定位与设计原则

DeepSeek-Harness 将模型适配器、工具注册表、会话日志、Agent 循环、持久化、沙箱和产品入口都作为 Cordis 插件；不存在必须直接修改的“特权核心”。插件通过 Cordis Context 提供服务、监听类型化事件，并以可逆 effect 管理注册与卸载。

主要原则如下：

- **一切皆插件**：Service Definition 定义能力，Provider 实现能力，Consumer（通常是工具或产品入口）消费能力。
- **会话日志是事实源**：模型可见内容必须可从 `SessionEvent` 日志重建；投影、UI、遥测和持久化都从日志或实时事件派生。
- **可组合启动**：profile 由按顺序叠加的 bundle patch、profile patch、Harness home patch 和命令行 overlay 组成。
- **事件扩展而不是循环分叉**：Agent 循环通过 `agent/*`、`session/*`、`llm/*`、`tools/*` 等扩展点暴露策略与适配位置。
- **资源必须可逆收敛**：Agent、进程、终端、持久化批处理和 Cordis scope 的创建、取消、卸载均有明确 owner 与 teardown。
- **源平面与制品平面分离**：Vitest/tsconfig paths 测源码；发布与 built smoke 测 `lib/` 制品和实际 bin。

## 2. 文本总流程图

```text
用户/自动化调用
  ├─ dsh CLI: dsh --profile web | headless "任务"
  ├─ Web 应用: apps/web
  ├─ TypeScript SDK: dsh-sdk-client
  └─ Python SDK: deepseek_harness
          │
          ▼
入口与配置层
  ├─ apps/cli (args、profile-boot、进程退出、headless/web runner)
  ├─ packages/boot/app-boot (env、profile、bundle、patch、Loader)
  ├─ packages/boot/cmdline (命令行快照)
  └─ $DSH_HOME/profile + cordis.patch.yml + --patch
          │  Loader 将 bundle patch 按序应用到空 entry list
          ▼
Cordis Context / 插件树
  ├─ vendor/ (vendored Cordis 及插件)
  ├─ bundle/base (模型、工具、会话、沙箱、凭证、设置等基础组合)
  ├─ bundle/web-app 或 bundle/headless
  └─ 用户/第三方 out-of-tree plugins
          │
          ├──────────────────────────────────────────────────────────────┐
          ▼                                                              ▼
核心运行服务                                                     能力提供者与组合点
  ├─ dsh-agent / dsh-agent-loop                                  ├─ dsh-llm + DeepSeek/pi-ai adapters
  ├─ dsh-session / system-prompt / tools                         ├─ shell / subprocess / fs / sandbox
  ├─ dsh-scope / settings / credentials                          ├─ subagent / workflow / skill / plan
  └─ dsh-typert registry/loader/protocol                         ├─ session persistence JSONL/SQLite
                                                                  └─ API gateway / remote / SDK server
          │                                                              │
          └──────────────────────────────┬───────────────────────────────┘
                                         ▼
Agent turn/step 驱动
  turn/start → claim inbox → prompt/tool schema assembly
      → agent/pre-step → step/start → request/header + request/context
      → llm prepare/stream → assistant/chunk* → assistant/message
      → tool/call* → tools/pre-execute → tools/execute
      → tools/post-execute → tool/result* → step/end
      → next-step 或 agent/turn-stopping → turn/end → idle
                                         │
                 ┌──────────────────────┼──────────────────────┐
                 ▼                      ▼                      ▼
          session/event           session/flush            wire/UI projections
          append-only log         durability barrier       Web/ACP/SDK notifications
                 │
                 ▼
      JSONL(.jsonl.zstd/.jsonl) 或 SQLite events/sessions
```

## 3. 分层与职责

| 层 | 主要目录/包 | 职责与边界 |
|---|---|---|
| 基础运行时 | `vendor/`、`packages/util/`、`packages/typert/` | Cordis Context/Loader/Group/Include/HMR；品牌类型、路径、超时、原子写、环境和输出等无业务工具；Typert 类型图、加载器、协议和运行时注册表。 |
| 组合与启动 | `packages/boot/`、`packages/bundle/`、`apps/cli/` | 解析 launcher 参数，初始化 profile，读取分层环境，解析 bundle patch，装载 Loader，处理 web/headless 运行与退出。 |
| Agent 核心 | `packages/core/agent/`、`packages/core/agent-loop/`、`packages/core/scope/` | Agent 注册表/工厂/initiator scope、共享 `SessionId`、具体 `ReactLoopAgent`、inbox、turn/step 生命周期和取消收敛。只有 agent-loop 包含具体循环逻辑。 |
| 会话与提示词 | `packages/core/session/`、`packages/core/system-prompt/`、`packages/core/agent-tool-presentation/` | Append-only `SessionEvent`、消息派生、请求头/上下文折叠、提示词 section 和工具 schema 组装、模型展示。 |
| 模型能力 | `packages/llm/llm/`、`llm-deepseek/`、`llm-pi-ai/`、`llm-retry/`、`token-meter/` | 统一消息/stream/call config/错误协议；按 provider 注册 adapter；DeepSeek 官方适配器直接 fetch+SSE；retry 在请求错误扩展点重试。 |
| 工具与执行世界 | `packages/core/tools/`、`packages/shell/`、`packages/subprocess/`、`packages/fs/`、`packages/sandbox/`、`packages/terminal/` | 工具定义、权限/策略、执行前后流水线；shell、文件系统、进程树、终端和 sandbox provider；敏感环境变量默认不传递给子进程。 |
| 高阶 Agent 能力 | `packages/subagent/`、`packages/workflow/`、`packages/skill/`、`packages/plan/`、`packages/goal/`、`packages/feedback/`、`packages/compaction/` | 子代理创建/委派、工作流 worker、技能提供者与加载器、计划/目标/反馈、上下文压缩；通过 `ctx.agents.create()`、`ctx.jobs` 和事件扩展核心。 |
| 持久化与派生 | `packages/session/`、`packages/storage/`、`packages/context/`、`packages/identity/`、`packages/settings/`、`packages/credentials/` | JSONL/Zstandard 和 SQLite 持久化、检查点、投影/缓存、统计/遥测/标题、会话引用、设置和凭证。 |
| API 与产品面 | `packages/api/`、`packages/sdk/`、`apps/web/`、`packages/acp/`、`packages/client/` | Typert Remote `/api` 网关、远程 Agent 查找、JSON-RPC SDK server/client/protocol、Web UI、ACP 自动化入口。 |
| 原生与发布 | `native/landlock-run/`、`scripts/`、`website/`、`docs/` | Landlock self-restrict-then-exec 原生 launcher；构建、类型、lint、文档、包约束、发布与站点验证脚本。 |

### 3.1 旧细探吸收后的包族补充

旧细探把能力概括为 `core`、`guard`、`session`、`sandbox`、`skill`、`workflow`、`subagent`、`plan` 和 `goal` 等包族；源码现状进一步证明这些不是一个扁平的“大核心”，而是通过 Cordis Context、Service Definition/Provider/Consumer 和事件 seam 组合的独立工作区。当前应按以下边界理解旧细探中的概括：

| 旧细探线索 | 当前源码证据与架构裁决 |
|---|---|
| `packages/core` 包含 agent、agent-loop、session、scope、system-prompt、tools | 吸收，但改用真实子包边界：`packages/core/agent` 负责 Agent 接口/registry，`packages/core/agent-loop` 负责具体 driver，`packages/core/session` 负责内存会话日志，`packages/core/scope` 负责 agent scoped registration，`packages/core/system-prompt` 与 `packages/core/tools` 分别负责提示词/工具组装。不能把 `core` 写成不可替换的特权核心。 |
| `guard` 提供 `repeat-tool-reminder` 与 `timeout-policy` | 吸收。`packages/guard/README.md` 证实前者监听工具/Agent 事件并通过 `tools/post-execute` 的 `additionalContexts` 追加已记录的 plugin-sourced `user/message`；后者在 `tools/execute` 上注册逐调用 deadline listener。二者都是 loop-hygiene 消费者，不是通用 capability provider。 |
| `session` 提供 checkpoint、JSONL/SQLite、projection/cache、stats | 吸收并补全。`packages/session/README.md` 证实 `session-persistence` seam、`session-checkpoint-policy`、`session-persistence-jsonl`、`session-persistence-sqlite`、`session-projection`、`session-projection-cache` 与 `session-stats`；持久化后端订阅 `session/event`，不由 `core/session` 直接绑定。 |
| `sandbox` 分为 `sandbox`、`sandbox-local`、`sandbox-policy`、`sandbox-windows-acl` | 吸收并纠正原有笼统表述。`packages/sandbox/README.md` 证实 `ctx.sandbox`、本地平台 provider 和 `ctx.sandboxPolicy`；`sandbox-windows-acl` 是现存平台实现。沙箱策略约束同一执行世界的进程能力，不是把 workflow worker thread 当作安全边界。 |
| `skill` 是技能包，`workflow` 是工作流包，`subagent` 是子代理包 | 吸收。`packages/skill/README.md` 证实 provider-neutral catalog/loader（`ctx.skills` + model-facing `ctx.tools`）；`packages/workflow/README.md` 证实 `ctx.workflowEngine`、worker-thread provider、`workflow`/`ralph` 工具，并明确 worker thread 不是安全边界；`packages/subagent/README.md` 证实多个命名 provider 可共存，覆盖 in-process、ACP、Codex、Claude Code、DSH SDK 等驱动。 |
| `plan`、`goal`、`feedback`、`compaction`、`interaction` 等高阶能力 | 吸收为独立能力边界，而非 Agent loop 内置状态：`plan-mode` 是记录在日志中的 per-agent collaboration state；`goal` 是同会话目标生命周期；`feedback` 分为 Session log 不可变 remark 与 storage-domain sidecar，均不进入模型上下文；`compaction` 是 Service Definition + provider + tool/command Consumer；`interaction` 负责 approval/permission/ask-user。 |
| `dsh-plugin` 可发现性、GitHub topic 等旁路线索 | 不作为当前架构事实吸收。它们是生态/发现线索，不能替代本地 Loader、`package.json` 的 `dsh` 元数据、profile/bundle patch 或实际注册证据。 |

### 3.2 旧细探未重复展开但已核对的边界

旧细探中的 `system-prompt` + `agent-tool-presentation` 提示词设计已由 `packages/core/system-prompt`、`packages/core/agent-tool-presentation` 和 `SessionEvent` 可重建约束覆盖；模型可见内容必须可从会话日志重建，不能把提示词拼装写成独立于日志的旁路状态。

旧细探提出的 `python/`、`native/`、`vendor/` 旁路线索已与当前目录和 README 对照：`python/` 是 Python SDK/ bundled runtime，`native/landlock-run/` 是原生受限执行 launcher，`vendor/` 是 vendored Cordis 源码及同步清单；三者属于技术栈/发布边界，不是额外的 Agent 核心层。

### 3.3 包组清单裁决

旧细探中的“packages 极丰富”是方向正确但不宜作为固定数量或旧目录树使用的判断；按当前 `packages/README.md` 和实际工作区核对，包组包括 `acp`、`api`、`attachment`、`boot`、`bundle`、`client`、`code-runtime`、`compaction`、`context`、`core`、`credentials`、`e2b`、`extensions`、`feedback`、`fs`、`goal`、`guard`、`hooks`、`host`、`identity`、`interaction`、`jobs`、`llm`、`lsp`、`mcp`、`plan`、`preset`、`runtime-diagnostics`、`sandbox`、`schedule`、`sdk`、`session`、`session-query`、`settings`、`shell`、`skill`、`spill`、`storage`、`subagent`、`subprocess`、`terminal`、`test-support`、`todo`、`typert`、`util`、`web`、`workflow` 和 `workspace`；因此旧清单吸收为能力地图，不吸收为版本锁定的目录/数量声明。新增包应以 `packages/README.md`、对应组 README 与实际源码为准。

## 4. 关键模块地图

### 4.1 启动、profile 与 patch

`apps/cli/src/bin.ts` 负责加载入口；`packages/boot/app-boot/src/index.ts` 负责 `.env` 分层、config path、Loader guards、可选用户 patch、启动快照和 Cordis 树；`profile.ts` 负责 `$DSH_HOME/profiles/<name>`、profile manifest、bundle 解析和 patch 组合。

启动组合顺序是：空 entry list → `dsh.profile.bundles` 中每个 bundle 的 patch（按声明顺序）→ profile 的 `cordis.patch.yml` → `$DSH_HOME/cordis.patch.yml` → `--patch` overlay。`web` 与 `headless` 有内置 bundle 模板；其他 profile 通过 `dsh plugin` 初始化。

### 4.2 Agent 工厂与具体循环

`packages/core/agent/src/index.ts` 提供 live registry、AgentFactory 委托和 initiator scope；具体创建与驱动不在该包。`packages/core/agent-loop/src/index.ts` 注册 `ctx.agentLoop`，创建/恢复 Agent，并把 agent/session 进入 registry、announce、发出 `agent/session-start`，最后启动具体 driver。

`ReactLoopAgent`（`packages/core/agent-loop/src/agent.ts`）维护 `idle`、`maintenance`、`running` 三类 phase，拥有 Inbox、Agent scope、取消控制器和运行时上下文投影。创建/恢复是回滚覆盖的事务：session、scope、setup、publication 和 teardown 由 owner 共同管理；卸载会 cancel、等待 idle、dispose scope、从 registry detach。

### 4.3 LLM 请求与工具调度

每一步由 session 派生消息，调用 `systemPrompt.assemble()`，经过 `agent/pre-step`，再经 `agent/request` waterfall 形成 `LlmCallConfig`。loop 调用 `ctx.llm.prepareCall()` 获得 adapter 绑定、默认 reasoning/maxTokens 与 context window，然后记录 `request/header` 和 `request/context`，构造带 session id/signal 的冻结请求。

流式响应逐 chunk 记录 `assistant/chunk`，由 `BlockAssembler` 聚合为 `assistant/message`；若发生错误，进入 `agent/request-error`，监听器可以返回 retry。若 assistant message 含 tool calls，则 `executeToolCalls()` 进行调度：exclusive 调用形成 barrier，parallel 调用使用受 `maxParallelToolCalls` 限制的滚动池；执行体可并行，但 policy、结果和上下文仍按模型顺序提交。取消会排空未启动调用并记录 `ABORTED_BEFORE_DISPATCH` 合成结果。

### 4.4 会话日志与持久化

`packages/core/session/src/index.ts` 持有内存 session store、append-only event log、消息派生和 `session/event`、`session/flush` 事件。`SessionEventMap` 可由插件声明合并。`assistant/chunk` 是可重放的原始事件，`assistant/message`、tool call/result、turn/step 边界是模型历史与生命周期事实。

- JSONL provider：每 session 一个逻辑日志，默认 `.jsonl.zstd`，可选 raw `.jsonl`；首行是冻结 `SessionHeader`，后续是事件或可逆 packed chunk row；追加采用批处理、fsync、尾部恢复和连续 seq 校验。
- SQLite provider：`sessions` + `events` 表，每事件一行，append 是事务；默认 WAL；`node:sqlite` `DatabaseSync` 使单次写入同步阻塞事件循环；当前未发布格式拒绝迁移和非当前 schema。
- 两种 provider 都支持 lazy materialization、resume、断裂 turn 修复、非变异 inspect 和 session flush；持久化插件订阅 `session/event`，而非由核心 session 直接绑定后端。

### 4.5 能力 seam、Typert 与远程 API

能力通常有 Service Definition、Provider、Consumer 三个角色。Typert 为 service/remote 方法生成或读取 invocation descriptor，registry/loader 维护运行时绑定。

`packages/api/gateway/src/index.ts` 的 `TypertGatewayService` 将连接的 `/api/<namespace>/<method>` endpoint 映射到当前 Context 中的严格 Typert definition 或受限 SRC marker；它校验 endpoint、参数、receiver、绑定、取消 signal 和返回值，随后返回 JSON-RPC connection envelope。`packages/api/remotes/` 负责 Host BFF 侧的远程 Agent 查找和允许转发的事件集合。

## 5. 数据流与持久化语义

### 5.1 一次普通对话

1. CLI/Web/SDK 将文本或 content blocks 送到某个 `SessionId`。
2. Agent `send` 将消息写入 `next-turn` 或 `next-step` Inbox，并由 wakeup 决定是否唤醒 driver。
3. driver 先追加 `turn/start`，claim inbox，组装 prompt sections 与 tool schemas。
4. `agent/pre-step` 可拒绝或改写进入 step 的消息；接受后追加 `step/start`、`user/message`。
5. `session.deriveMessages()` + prompt + tools 形成请求；`ctx.llm` 适配器发送流并产生 `StreamChunk`。
6. 每个 chunk 追加 `assistant/chunk`；完成后追加 `assistant/message`，记录使用量及 chunk seq。
7. 有工具调用时执行 `tools/pre-execute → execute → post-execute → result`，结果 context 进入下一 step Inbox；没有工具调用则 step 完成。
8. 追加 `step/end`、`turn/end`，发布 Agent status；持久化 provider 异步批量写入，`session/flush` 提供显式耐久化屏障。
9. Web、ACP、SDK server 和 session projection 从事件流/状态变化中形成用户可见结果。

### 5.2 恢复与崩溃修复

Persistence `load/prepare` 读取并校验 header、seq 和事件；若尾部停在合法但未结束的 turn，按照共享 repair 约定补 `TOOL_NOT_STARTED` 或 `TOOL_OUTCOME_UNKNOWN` 等关闭事实，之后恢复的 agent 从已平衡历史继续。严重损坏、校验和失败、已提交边界前的缺陷会拒绝加载，而不是静默丢历史。

### 5.3 子进程执行

工具或 provider 将完整 `SubprocessSpawnSpec` 交给 `ctx.subprocess`。本地 provider 负责可执行文件解析、脱敏父环境、进程树句柄、非消费型 offset reader、SIGTERM→grace→SIGKILL 终止和全树退出观察；terminal provider 另外管理 PTY、前台进程组和终端字节流。SDK 自己管理 runtime 子进程，是 subprocess seam 的已记录例外。

## 6. 关键路径索引

| 场景 | 入口 → 关键路径 | 主要事实/落点 |
|---|---|---|
| CLI 启动 profile | `apps/cli/src/bin.ts` → `profile-boot.ts` → `app-boot` → Cordis Loader | bundle/profile/用户 patch 组合后创建完整 Context。 |
| headless 一次任务 | `dsh --profile headless "task"` → headless bundle → AgentLoop → LLM/tool → idle | 输出最终 assistant 文本后退出；需要 provider/model 与凭证。 |
| Web 对话 | `apps/web` → Web bundle/Client API → session event 与状态通知 | 浏览器快照测试覆盖 assembled UI 与事件驱动界面。 |
| 新 Agent | `ctx.agents.create({sessionId, setup, agentOptions})` → `AgentLoop.prepare` → publish → driver | setup 完成且 commit 后才 announce；失败回滚。 |
| 恢复 Agent | `ctx.agents.resume({resumeSessionId})` → `ctx.sessionPersistence.prepare` → setup → publish | 需要 mounted persistence；按已有日志恢复 turn/history。 |
| 模型请求 | `agent/request` → `ctx.llm.prepareCall` → `llm.stream` → adapter | DeepSeek route 为 `deepseek-official`；官方 adapter 使用 fetch+SSE。 |
| 工具调用 | assistant tool-call blocks → `executeToolCalls` → tools policy/executor/finalizer | exclusive barrier 与 bounded parallel pool；结果按模型顺序提交。 |
| 远程调用 | connection `/api/ns/method` → `TypertGatewayService` → service method → encoded result | 严格 descriptor 优先；撤回的严格定义不允许 SRC fallback。 |
| TypeScript SDK | `DeepSeekHarness` → `HarnessClient` → child runtime stdio JSON-RPC | `initialize`、`session/prompt`、`shutdown`；收集 event/status/subagent notifications。 |
| Python SDK | `DeepSeekHarness` → `HarnessClient` → bundled runtime subprocess | `deepseek_harness` 使用 Pydantic 模型，等待 enqueue receipt 后收集到 root session idle。 |
| 会话落盘 | `session/event` → JSONL batching/fsync 或 SQLite transaction | session 负责事实；persistence 是可替换 plugin。 |

## 7. API、CLI、SDK 与协议

### 7.1 CLI

- `dsh --profile <name>`：启动命名 profile。
- `dsh --profile headless "job"`：执行一次 headless 任务并打印最终回答。
- `dsh web`：`--profile web` 的别名。
- `dsh plugin --profile <name> <pnpm args>`：在 profile 目录管理 out-of-tree plugins。
- `--dump-default-config` / `--dump-config`：仅查看组合后的配置，不启动应用。

Launcher 只解析自己的 flags；第一个未知 token 起交由被选中的 app/profile 解析，因此 Web/headless 专属参数不会和 launcher grammar 混淆。

### 7.2 Cordis/TypeScript API

核心 Context key 包括 `ctx.agents`、`ctx.sessions`、`ctx.agentLoop`、`ctx.llm`、`ctx.tools`、`ctx.systemPrompt`、`ctx.subprocess` 和可选 `ctx.sessionPersistence`。主要 factory API：

- `ctx.agents.create({ sessionId, meta?, seed?, agentOptions?, setup?, signal? })`
- `ctx.agents.resume({ resumeSessionId, agentOptions?, setup?, signal? })`
- `ctx.agentLoop.create(id, options?, meta?)`
- Agent：`followup()`、`steer()`、`inject()`、`cancel()`、`whenIdle()`
- Remote：`/api/<namespace>/<method>`，由 Typert descriptor 校验参数、receiver、返回值与取消。

### 7.3 SDK stdio JSON-RPC

`@deepseek-ai/dsh-sdk-protocol` 使用以换行分隔的 JSON-RPC 2.0：

| 方向 | method | 语义 |
|---|---|---|
| client → runtime | `initialize` | cwd、provider、model、可选 maxTokens；返回初始化结果。 |
| client → runtime | `session/prompt` | 向 session Inbox 入队 content blocks；返回 `messageId` receipt，不是最终答案。 |
| client → runtime | `shutdown` | 请求运行时关闭。 |
| runtime → client | `session.event` | 未过滤的 session 事件通知。 |
| runtime → client | `session.status` | Agent 整体 `running`/`idle`。 |
| runtime → client | `subagent.started` / `subagent.finished` | 子代理生命周期通知。 |

TS SDK要求显式 `command/args` 启动 runtime；Python SDK负责 bundled runtime resolution。两者都通过事件通知收集结果，当前协议没有 prompt cancel/session close，也未实现 server→client approval request。

## 8. 技术栈与构建形态

- TypeScript/ESM，严格类型检查；根 package `type: module`，Node `^22.19.0 || >=24.0.0`。
- pnpm workspace，声明 `pnpm@11.7.0`；workspace 包统一为 `@deepseek-ai/dsh-*`。
- vendored Cordis、Cordis Loader/Include/Group/HMR；`@deepseek-ai/schemastery` 用于配置校验；Typert 用于 RPC 类型描述与运行时 registry。
- LLM：DeepSeek 官方 chat-completions + SSE（`fetch`、`eventsource-parser`），并有 pi-ai adapter 与 retry/token-meter 插件。
- 持久化：Node 内置文件 API/Zstandard 能力与 `node:sqlite` `DatabaseSync`；JSONL 和 SQLite 遵守同一 `SessionPersistence` seam。
- Web：Vite/VitePress 相关构建与浏览器测试；仓库同时维护文档站 `website/`。
- Python：`python/sdk` 与 `sdk-runtime`，`deepseek_harness` 使用 Python subprocess、newline JSON-RPC、Pydantic；Python 包用 `pyproject.toml`/uv lock 管理。
- Native：`native/landlock-run` 维护 Rust/平台 npm 包族，为受限执行提供 self-restrict-then-exec launcher。
- 质量工具：Vitest、TypeScript `tsc`、tsdown、oxlint、jscpd、knip、publint、VitePress/文档 gates、平台与浏览器 e2e。

## 9. 测试与验证体系

仓库测试随包放在 `tests/`，另有 `scripts/**/*.spec.ts`、`apps/cli/tests` 和 `apps/web/tests`：

1. `pnpm run test`：Vitest 单元/包级组合测试，覆盖边界、事件顺序、错误、取消、并发与 HMR disposal。
2. `pnpm run test:coverage`：CI 覆盖门禁，`packages/*/*/src` 按文件要求 100% line coverage。
3. `pnpm run test:e2e`：带 key 的真实 DeepSeek/外部 provider API 测试；无凭证时相关套件 self-skip。
4. `pnpm run test:snapshot`：无 key 的 ACP/headless JSON-RPC、持久化日志和用户可见输出回放。
5. `pnpm run test:web`：先构建再用 Chromium 做 Web UI snapshot/replay。
6. `pnpm run typecheck`、`lint`、`hygiene`、`build`：分别检查编译、静态规则、包/依赖/发布健康和 host/client 制品。
7. `pnpm run doc-sync`、`website:build` 及 `verify-*` scripts：检查文档、生成目录、链接、配置、事件/模块/包不变量和发布契约。

测试设计要求产品可见插件必须有真实 Loader/Cordis 组合测试；只构造 `ctx.plugin()` 的单元测试不能替代真实入口测试。源码测试解析 `src`，built smoke/子进程测试明确加载 `lib`，避免旧制品污染源码单例。

## 10. 变更与排查入口

- 改 `packages/` 前先读 `docs/architecture.md`、本包 `README.md`、`packages/AGENTS.md` 和相关 `docs/subsystems/`。
- 新能力先确定 Service Definition / Provider / Consumer 三角色，再决定使用哪个 Context/event seam。
- 模型可见输入、事件或 durable 状态变化必须同步更新 SessionEvent、投影/协议、README/JSDoc 和相应 snapshot/real-composition 测试。
- 涉及 agent-loop、session、subprocess、native 或 teardown 时优先检查 cancellation、owner、quiescence、持久化恢复与真实子进程路径。
- 涉及配置时检查 bundle/profile patch 层顺序、`!!js` 约束、环境变量分层和 built/source 两种启动路径。

## 11. 未确认项与首轮风险

以下项目在当前核对未通过构建、启动或完整测试确认，后续工作应以源码和实际验证为准：

- **代码地图边界**：目标 checkout 已有独立 `.codegraph/`（本轮 `codegraph status`：4,066 files / 43,235 nodes / 243,611 edges）；本轮只使用目标仓库本地 CLI 作为导航，不使用跨项目 MCP。架构结论仍以目标源码/文档逐段读取为准。
- **当前 profile 的真实 bundle 树**：profile 解析与内置模板已确认，未启动 `dsh --dump-config`，因此某一台机器当前实际挂载的第三方/用户 patch 集合未确认。
- **API 完整 endpoint 清单**：Typert gateway 的 `/api/<namespace>/<method>` 机制已确认，但具体 endpoint 由运行时服务和 generated definitions 动态决定，本文未宣称固定业务路由表。
- **Web/ACP 运行组合细节**：包和 snapshot 位置已确认，未启动浏览器、ACP server 或 Web server，具体运行时端口、环境变量和当前界面组合未确认。
- **真实 LLM 行为**：DeepSeek adapter 的请求/错误/SSE 语义来自源码与 README，未使用 API key 执行真实请求；配额、网络、代理和 provider 端状态未确认。
- **依赖安装与制品状态**：未执行 `pnpm install`、构建、启动或完整测试；因此不能在本文宣称当前 `node_modules`、`lib`、native 二进制或全量门禁状态正常。
- **跨平台 native/Windows 细节**：Landlock 与 Windows ACL 的职责已定位，但本机 macOS 之外的编译和行为未确认。
- **持久化并发边界**：JSONL provider 的单 live writer 与 SQLite `DatabaseSync`/锁错误语义来自包文档；多进程共用同一数据库/日志的部署约束仍需单独验证。

## 12. 当前核对证据与范围

已读取并用于建档：根 `AGENTS.md`、`细探-DeepSeek-Harness.md`、`docs/architecture.md`、`docs/AGENTS.md`、`docs/testing.md`、根 `package.json`、Python SDK README、native README、CLI/agent-loop/session-persistence/DeepSeek adapter/SDK README，以及 agent-loop、session、app-boot/profile、API gateway/remotes、SDK client/API、subprocess 等关键源码。

当前核对允许的唯一工作区变更是新增根文件 `ARCHITECTURE.md`；未修改源码、依赖、测试、配置、已有细探文档，未安装、启动、构建、提交 Git 或删除证据。

## 13. 后续底座映射：抽取边界与裁决

当前核对不是把 DeepSeek-Harness 的包目录照搬为平台目录，而是把包族映射到“运行核心原子能力、可复用模块、仅供参考”三类。凡是依赖 Agent/Session/模型提示词/工具语义的实现，不能因为抽象名称相似就下沉到通用运行核心；凡是涉及资源、取消、所有权、持久化、投影、缓存和故障收敛的机制，才有资格进入运行核心候选。

| 包族 | 真实职责 | 底座裁决 | 可吸收的最小边界 | 不应吸收的部分 |
|---|---|---|---|---|
| `packages/core/` | Agent 接口/注册表、默认 Agent loop、Session 日志、提示词和工具编排 | **部分吸收** | `SessionEvent` append-only 事实流、inbox/FIFO、取消信号、quiescence、owner 生命周期、可插拔 Service Definition seam | `ReactLoopAgent` 的 LLM turn/step 语义、prompt assembly、tool-call 语义不能成为特权“大核心”；`core` 不是不可替换单体 |
| `packages/guard/` | 重复工具调用提醒、逐工具 timeout policy | **抽成策略模块，不进运行核心** | `tools/execute` middleware、声明式预算、信号融合、结果错误码、按 Agent 隔离的 guard state | 重复检测阈值、提醒文案、模型行为纠偏是产品策略；timeout 是 cooperative signal，不是强制杀进程 |
| `packages/session/` | 持久化 seam、JSONL/SQLite、checkpoint、projection、projection-cache、stats/title/telemetry | **吸收为数据平面模块** | `SessionPersistence` 抽象、seq/revision、冷恢复、纯 projection fold、watermark、cache read ladder、durability barrier | JSONL/SQLite 物理格式、title/telemetry/stats 和客户端载体是 provider/领域模块；不能让 cache 成为事实源 |
| `packages/sandbox/` | 按会话和调用解析文件效果策略，包装 argv，报告 enforcement | **吸收安全能力契约，不吸收具体后端实现** | 每调用 policy、workspace root、`full/partial` enforcement、runner/denial 双分类、fail-closed 错误 | bwrap/Landlock/Seatbelt/Windows ACL 具体实现；网络和进程可见性不在该契约；worker thread 不是安全沙箱 |
| `packages/skill/` | 多来源技能发现、分层 registry、catalog snapshot、按需加载和失效 | **复用为目录/发现模块** | provider registry、scope layer、rank 冲突裁决、complete/incomplete、取消、generation、last-good catalog、按需 get | SKILL.md/frontmatter、目录优先级、模型可见文案和资源路径属于 skill provider/Consumer；技能不是 Session 事件，也不是运行核心 |
| `packages/workflow/` | 模型编写脚本、worker-thread 执行、并发子代理、pipeline/parallel、阶段和日志 | **保留为编排模块** | 一次运行一个 lifecycle owner、typed host/worker protocol、structured-clone 边界、并发/总量/item/time/dispose 预算、first-wins 终态、子任务 quiescence | workflow script、`phase`/`log`、Ralph 固定策略、worker 内 `vm` 语义和模型体验；worker thread 只能隔离事件循环，不能宣称安全边界 |
| `packages/subagent/` | 多命名 provider 的 child-agent 启动、continuable Activation、授权、枚举和报告 | **吸收子任务生命周期模块，不复制 provider** | capability negotiation、发布前回滚、发布后 run handle、单一 signal、owner/parent authority、child-first disposal、continuation FIFO | ACP/Codex/Claude/DSH SDK/in-process transport 的协议和启动细节；provider 只能是同一 seam 下的策略 |
| `packages/plan/` | 每 Agent 的 logged collaboration state、pending selection、prompt section、退出审阅 | **仅作参考/领域模块** | “状态以事件 fold 为准、pending 只在明确 commit point 落账、事件失败不伪装切换成功”的状态机模式 | plan mode 本身、`plan:policy` 文案、`exit_plan_mode` 和 `/plan` 交互；它不授权、不加固 sandbox，也不应成为通用 mode registry |

### 13.1 可进入通用运行核心的原子能力

1. **生命周期与所有权**：每个异步操作只有一个 owner 和一个 settlement point；发布前失败回滚未发布资源，发布后由 holder 持有 run/handle；`dispose()` 幂等并等待可证明的 quiescence。`WorkflowRun`、`SubagentRun`、`SessionPreparation` 和 `JobRegistry` 都提供了同一类可抽象证据。
2. **单取消通道与终态优先级**：调用方 signal 负责 admission/start 前后的一致取消语义；宿主在取消、结果、worker death、grace expiry 间用 first-wins 终态锁定边界，禁止清理回调反写已选结果。
3. **权威事实流与只读派生**：模型可见或需要恢复的事实写入 append-only `SessionEvent`；projection 只从已提交事件折叠，wire/UI/cache 不得反向写事实。`SessionHeader` 的 lineage、cwd、seedLength、delegationDepth 等存储元数据不混入模型 transcript。
4. **可插拔能力 seam**：统一采用 Service Definition → Provider → Consumer；Provider 替换不复制 Consumer 流程。单 provider 能力使用单一 `ctx` seam；明确允许多 provider 的能力（`ctx.subagents`）才使用命名 registry。
5. **有界资源监督**：预算要在真正拥有完整结果或完整运行生命周期的层执行；至少覆盖 deadline、并发槽、总任务数、单批 item 数、输出字节、写回间隔、dispose grace、子进程树回收。预算超限是结构化失败，不得当成空结果成功。
6. **证据化恢复**：恢复必须读取 authoritative state 或 durable log，明确区分 committed prefix、torn tail、unknown side effect、cache stale 和 provider unavailable；不能用“进程退出/打印成功/对象存在”代替恢复证据。

### 13.2 只应进入模块库的组合能力

- **Agent loop 模块**：继续由 `agent-loop` 维护 turn/step、LLM stream、tool call 顺序、retry 和模型上下文；运行核心只提供生命周期、事件、取消和持久化接口。
- **checkpoint policy 模块**：在 LLM 请求、顶层工具副作用和 `agent/pre-step` 处建立 durability barrier；该策略可替换，不能把“每个请求都先 flush”硬编码进通用事件库。
- **projection/cache 模块**：projection 的纯 fold、版本号和 watermark 是通用模块；每个领域的 key/state/view/schema 仍由领域包注册。cache 只能加速，不能改变事实或恢复语义。
- **workflow 编排模块**：worker host 管理 child ledger、typed protocol、并发槽和清理；workflow 语言、阶段、日志和脚本错误分类只在 workflow 模块。
- **subagent continuation 模块**：Activation、parent-child ownership、cold resume、followup FIFO 和 report 是可复用组合；具体 ACP/Codex/Claude Code/SDK transport 是 provider 适配。
- **skill discovery 模块**：scope/rank/generation/complete snapshot/last-good fallback 可复用；本地文件系统 watcher 和模型 skill tool 不能下沉为通用运行时。
- **guard policy 模块**：timeout、repeat reminder、输出上限等作为 middleware 装配；必须保留注册顺序的语义，不另造第二套调度器。

### 13.3 仅作参考或明确隔离

- `workflow-worker-thread` 的 `node:vm`、`Worker` 和空环境只解决宿主事件循环阻塞、可终止和凭证不透传；它不能满足恶意脚本隔离。需要真正不信任执行时，应以独立进程、Landlock/Seatbelt、容器或远程沙箱实现同一能力 seam。
- `danger-full-access` 不是 sandbox provider 的一个“弱实现”，而是 Consumer 经过批准后绕过 `ctx.sandbox` 的明确分支；禁止隐式 fallback。
- `plan` 的 prompt guidance 和 approval flow 不是资源权限；不能把 plan active 当作 sandbox mode、授权角色或执行预算。
- `repeat-tool-reminder` 的内存链只针对同一 Agent 的连续完全相同调用，恢复后重置且不写日志；它是启发式提醒，不是防循环不变量。
- `session-title`、`session-stats`、telemetry、Ralph 和具体 tool Consumer 只可作为领域实现参考；其文案、统计口径和外部载体不能成为底座公共契约。

## 14. 沙箱、线程与跨边界运行模型

### 14.1 沙箱不是线程的别名

`ctx.sandbox` 约束同一执行世界中的文件效果；`SandboxExecutionPolicy` 按调用携带 `mode`、绝对 `workspaceRoot` 和可选 `sessionId`，由 `sandbox-policy` 统一解析 session cwd、显式批准 override 和 agentless fallback。`SandboxProvider.confine()` 必须返回 wrapped argv 与 enforcement fact，或者以 `SANDBOX_UNAVAILABLE` fail closed；不允许在 provider 缺失时原 argv 直通。

`workflow-worker-thread` 每次 run 一个 worker，host 通过 typed structured-clone 协议转发子代理请求，worker 环境清空凭证并以 ready/go handshake 防止启动取消竞态；但 `node:vm` 代码可以恢复 Node 能力，故 worker/VM 仅是调度隔离。真正的安全边界应由 `ctx.sandbox` 或独立进程/容器/远程 provider 提供，并且沙箱结果要将“runner 自身失败”和“命令被成功拒绝”分为两种证据。

### 14.2 线程/子进程的资源与回收责任

- worker 由 `WorkerRun` 持有；取消时同时 abort 子任务、启动 bounded grace、合成未配对的 `workflow/agent-end`，最终 `worker.terminate()`；`dispose()` 必须在已 settle 和未 settle 路径都覆盖。
- subprocess provider 以 detached process group（POSIX）或 `taskkill /T`（Windows）为树根；SIGTERM 后在 grace 到期 SIGKILL，并持续探测进程组，不能只等待直接子进程退出就宣称树已收敛。
- 每个长任务都要有可观察终态（completed/failed/killed/stopping 等）、owner 授权和输出上限；后台 jobs 的 `running + stopping` 计入 per-owner 并发预算，不能只数 running。
- 跨 worker/process/remote 边界只传 plain JSON 或显式 wire envelope；live Agent、handle、取消器和可变结果不得穿边界，结果要先 snapshot/materialize 再传递。

## 15. 会话、投影与缓存：事实、加速器和载体的唯一关系

```text
Agent/工具/子任务产生事实
  → core/session append-only SessionEvent（唯一事实源）
  → session/event 已提交事件
      ├─ session-persistence：JSONL 或 SQLite durable append/flush/revision
      ├─ session-projection：同步纯 fold，按 key 生成同一 asOfSeq 的完整值
      ├─ session-projection-cache：{ver, seq, val}+生命周期 identity 的可丢失 checkpoint
      └─ API/Web/SDK/查询/telemetry：读取投影或事件，不回写事实
```

Projection unit 必须提供 `init/apply/view/schema/stateVersion`；`apply` 对不相关事件返回同一 state reference，`view` 同步且结果为 plain JSON。`ProjectionSnapshot.asOfSeq` 是所有值共同的 watermark，载体用 higher-seq-wins，禁止把某个旧值宣称为更高版本。

Projection cache 的正确性规则是：日志先于 cache，live checkpoint 先 flush 被其覆盖的事件；cache 记录绑定 `createdAt/cwd` 生命周期 identity，重建同一 session id 或更换 storage 时拒绝旧记录；`stateVersion` 不一致直接丢弃并从日志重折叠，不做猜测迁移；写失败只留下 stale cache，下一次写或 cold read 自愈。cold ladder 为 cached rows → `readFrom` tail → restore → fail-soft write-back，发现 crash repair 导致日志缩短时回到 seq 0 全量重读。

因此，cache 的“命中”只能减少读取和 fold 成本，不能证明最新、不能证明写入成功、不能绕过 `SessionPersistence`，也不能作为发布或验收的唯一证据。任何客户端显示状态都必须能回到 `SessionEvent`/durable log 的 seq 和 lifecycle identity。

## 16. 资源预算与失败恢复矩阵

| 资源/边界 | 现有实现证据 | 可抽取的通用契约 | 失败/恢复要求 |
|---|---|---|---|
| Tool 调用时间 | `guard/timeout-policy` 读取 `ToolDefinition.timeoutMs`，融合 `exec.signal` | 声明式 per-call deadline + stable error code | cooperative only；忽略 signal 的工具不能宣称 timeout 已终止；不能给未声明工具隐式 blanket budget |
| Workflow | `maxConcurrentAgents`、`maxTotalAgents`、`maxItemsPerCall`、`syncTimeoutMs`、`disposeGraceMs` | admission、槽位、总量、批量、同步切片、清理 grace 五类预算 | cap/fatal error 在执行前或对应 hook 处 fail loud；取消清理 pending starts 和 published children；worker death 补齐 lifecycle end |
| Background jobs | `maxConcurrentJobsPerOwner`、`outputLimitBytes`、`wait` timeout | exact owner bucket + output presentation bound + terminal first-wins | cancel 先于状态变更；cancel 抛错时 force-fail 并披露 possible orphan；owner/service dispose cancel、等待、移除 |
| Subprocess | `graceMs`、bounded in-memory tail、optional spill cap、process-group liveness | 全树信号、输出保留上限、spill 生命周期、终止梯度 | direct child exit 不等于 tree exit；spill close/unlink 失败要停止宣称完整 spill；最终做 survivor sweep |
| Session persistence | bounded batch wait、`session/flush` quiescence barrier、revision | durability wait 与 backend latency 分离；显式 flush 是观察失败点 | background write 失败保留事件并暂停自动重试；显式 flush 报错；冷恢复只修复 cold session，live open turn 不静默合成 |
| Projection cache | `writeEveryEvents`、`writeIntervalMs`、`turn/end`/detach mandatory points | count/interval throttle + mandatory durability points + stale-safe checkpoint | cache write fail-soft；版本/identity/watermark 不符 refold；日志先写、cache 后写 |
| Sandbox | `full/partial` enforcement、runner/denial signatures | policy per call + enforcement evidence + fail closed | provider 不可用、runner 自身失败和成功拒绝分别归因；禁止无证据 passthrough |

通用恢复终态必须至少覆盖：正常完成、业务失败、主动取消/超时、宿主/worker/子进程崩溃。恢复动作按所有权执行：先关闭 admission，再固定终态，再取消/回收子资源，最后发布事件或 UI 状态；不得让 cleanup 回调改写已发布结果。对有外部副作用的工具，日志只能证明 intent，不能证明 exactly-once；恢复遇到无结果的 durable call 必须生成 `TOOL_OUTCOME_UNKNOWN`，要求重试前验证状态或取得确认。

## 17. 防假绿：验证证据等级与最低门禁

本项目的测试政策可直接作为底座验收参考，但不能把“有测试文件”当成“已验证”：

1. **源码级**：类型/单元测试覆盖边界、错误、取消、并发和 HMR disposal；只证明局部函数和注册销毁关系。
2. **真实组合级**：产品可见插件必须通过 Loader + test-only `cordis.yml` + app/process 真实装配；手工 `ctx.plugin()` 不足以证明入口可用。
3. **制品级**：built bin、worker `lib/worker.cjs`、非 index runtime entry 和协议子进程必须用 plain Node 真实启动；source plane 解析 `src`，artifact plane 只能由显式 built smoke 证明，禁止混用 stale `lib` 形成假绿。
4. **外部世界级**：e2e 必须重新执行命令或从外部重读文件/数据库/进程状态，不能只检查 Agent 自报文本；应断言未触碰文件仍逐字节相同，并在失败、重试、超时路径清理资源。
5. **快照级**：模型可见、协议、持久化和人类可见行为变更需要 keyless snapshot；真实 API e2e 缺 key 时 self-skip 只代表外部条件缺失，不得写成 provider 已通过。
6. **负向级**：每个能力至少验证 provider 缺失、非法参数、空输入、重复调用、超时、取消、断线/崩溃、部分写入、版本漂移、资源二次释放和超限输入；`skip`、日志、缓存命中、子代理自报和历史构建物均不能单独算 pass。

底座验收输出应同时记录：源码存在、测试存在、真实组合执行、built/外部执行、命令、退出码、测试数/skip 数、环境、资源清理和未验证项。任何“绿色”结论都必须能回到真实命令和外部状态；不能以模型回答、日志末尾的 OK、缓存命中或单一静态 grep 冒充完整通过。

## 18. 唯一链路与平台落点

DeepSeek-Harness 的能力只能沿下列单链路映射，不允许每个包族各自复制一套运行核心、缓存、错误转换或 provider fallback：

```text
项目适配层/入口与配置
  → 领域模块（agent-loop / workflow / subagent / skill tool / plan）
  → 唯一 Service Definition 或能力注册表（一个 capability id 一个 owner）
  → 受管 Provider（本地实现 / worker / subprocess / remote）
  → 统一 sandbox、timeout、取消、输出与资源监督
  → SessionEvent 事实流 + SessionPersistence durability barrier
  → Projection / cache / API-Web-SDK 只读载体
  → 统一终态、证据、清理与验收
```

对应约束如下：

- `core/session` 只能是 SessionEvent owner；JSONL/SQLite 是同一 persistence seam 的 provider，不能由 Agent loop 旁路写文件或数据库。
- `workflow` 只能经 `ctx.subagents` 启动 child；worker host 管理协议和清理，不能让脚本直接拿到 Agent/handle，也不能绕过 sandbox 宣称线程隔离。
- `subagent` 只在 `ctx.subagents` 注册命名 provider；能力声明先于 start 校验，失败 loud；continuable child 的 Activation、FIFO、授权和恢复由唯一 continuation manager 持有。
- `skill` 的 catalog/loader 是唯一模型入口；provider 的 scope/rank/generation 在 registry 统一裁决，Consumer 不自行读取目录或维护第二份别名表。
- `guard`、checkpoint policy、projection/cache 都是事件/能力 seam 上的单一 middleware/模块；注册顺序、预算边界和 fail-soft/fail-closed 语义必须有一处 owner。
- `plan` 的 `plan/mode` 事件只进入 SessionEvent fold；UI、prompt、resume 和 compaction 都读同一 fold，不创建 live mirror。
- 任何 provider 失败必须返回统一可分类结果（如 unavailable/timeout/cancelled/unknown），不得隐藏 fallback；任何 cache 或 projection 异常都不能覆盖权威事件。

### 18.1 后续结论分级

- **吸收**：`SessionEvent`/persistence/projection 的事实—派生链、生命周期/取消/quiescence、per-call sandbox policy、资源预算和 worker/process 清理模式；这些能映射到平台运行核心或公共模块边界。
- **升级现有模块**：checkpoint policy、projection cache、jobs/资源监督、subagent continuation、workflow host protocol、skill discovery registry；先复用平台已有唯一 owner，不新建平行中心。
- **仅作参考**：具体 Agent loop、重复提醒文案、Ralph、plan mode、skill 文件系统排序、JSONL/SQLite 物理细节、ACP/Codex/Claude/SDK provider、worker `vm` 沙箱化表述。
- **待核**：跨进程 writer 的部署约束、不同平台 sandbox enforcement 的完整性、cache 并发 cold-read 去重、真实外部 provider 在断网/崩溃后的实测残留，以及平台现有底座对上述能力的准确代码图落点。当前核对不因文档映射直接改平台生产代码。

后续没有启动任何底座实现、迁移、依赖安装或发布动作；下一步若要生产化，必须先在系统工程平台登记需求、搜索能力、确认复用/升级裁决、取得能力占用和验收契约，再按唯一链路装配，并用真实组合、制品和外部状态验证。

## 19. 后续深挖收口：运行时、工具、沙箱、模型、事件与进程

本节是对旧 `细探-DeepSeek-Harness.md` 的逐条源码复核结果。旧细探仍保留为历史证据，但其中的“everything is a plugin”、guard、双后端持久化、sandbox 分层和子代理等概括，均以本节和前文的真实包边界为准；后续只维护本文，不在旧细探上继续增加架构事实。

### 19.1 契约表

| 契约 | 公开入口与参数 | 成功结果/事实 | 失败、取消、超时与资源责任 | 源码证据 |
|---|---|---|---|---|
| Agent 创建/恢复 | `ctx.agents.create({ sessionId, meta?, seed?, agentOptions?, setup?, signal? })`；`resume({ resumeSessionId, agentOptions?, setup?, signal? })` | `AgentHandle` 只在 setup、commit、session/agent publication 和 loop start 完成后返回；Agent 与 Session 共用同一 `SessionId`。 | setup/commit/publication 失败在未发布事务内回滚；`dispose()` cancel → `whenIdle()` → detach registry → remove session → unwind scoped world；同一 live id 的发布碰撞是权威拒绝点。 | `packages/core/agent/src/index.ts:65-132,159-213,397-482`；`packages/core/agent-loop/src/agent.ts:134-223` |
| Agent turn/step | `Agent.followup()`、`steer()`、`inject()` 进入单一 Inbox；`ReactLoopAgent.turn()`/`step()` 驱动。 | `turn/start` 先于首个 claim；每个模型请求是一个 step；`assistant/chunk*` 聚合成 `assistant/message`；工具结果按模型顺序回到下一 step。 | `agent/pre-step` 可 reject 或改写；首个空输入仍关闭 durable turn 但不发模型请求；取消在 turn 边界记录 `aborted`；非取消错误转成 `LlmError`/`UNKNOWN` 并由 driver containment 收口。 | `docs/architecture.md:63-90`；`packages/core/agent-loop/src/agent.ts:225-399` |
| Tool registry/executor | `ctx.tools.register(ToolDefinition)`、`schemas(scope?)`、`executionMode()`、`execute(ToolExecutionInput)`；输入参数先做 lossless JSON snapshot。 | 输出必须满足 `output.schema`，经 `output.render` 投影为 model content，顶层调用可生成 `meta`；最终结果 deep-freeze 后才通知 `tools/result`。 | `UNKNOWN_TOOL`、`INVALID_TOOL_OUTPUT`、approval deny、guard deny、`ABORTED_BEFORE_DISPATCH`/`ABORTED` 均结构化为错误结果；已启动的同进程 tool 只能 cooperative cancel，registry 不会遗弃其 promise；disposer 由 Cordis fiber 管理。 | `packages/core/tools/src/index.ts:221-287,1329-1450,1527-1667` |
| Tool scheduling | `executeToolCalls(ctx, turn, step, toolCalls, signal, acceptContext)`；工具以 `isConcurrencySafe(args) === true` 才可并行。 | exclusive 调用形成 barrier；parallel 调用进入 `maxParallelToolCalls` bounded rolling pool；dispatch 可重叠，但 `tools/pre-execute`、post、result 和 context 以模型顺序提交。 | abort 停止补充、排空已启动调用，并为未启动调用补 `ABORTED_BEFORE_DISPATCH` 的 call/result；内部 scheduler failure 排空后抛出首错，不伪造 recovery result。 | `packages/core/agent-loop/src/tool-calls.ts:41-101,112-245` |
| Sandbox policy/provider | `ctx.sandboxPolicy.resolve({ session?, mode? })` → `ctx.sandbox.confine(argv, SandboxPolicy)`；`danger-full-access` 不调用 provider。 | policy 按调用携带 `mode`、canonical `workspaceRoot`、可选 `sessionId`；provider 返回 wrapped `argv`、`full/partial`、denial dialect 和 runner-failure rules。 | 没有可用 backend 或 runner probe 失败抛 `SANDBOX_UNAVAILABLE`，禁止原 argv 直通；runner 自身失败与被限制命令的 denial 分开归因；Windows ACL 固定 `partial`。 | `packages/sandbox/sandbox-policy/src/index.ts:126-151`；`packages/sandbox/sandbox/src/index.ts:90-175`；`packages/sandbox/sandbox-local/src/index.ts:242-333,485-539` |
| LLM adapter/model | `ctx.llm.registerAdapter(providers, adapter)`；loop 先 `prepareCall(config, signal)`，再用一次性 `PreparedLlmCall.stream(request)` 或 `ctx.llm.stream(request)`。 | adapter registration 固定 provider route 和 retry policy；`resolveModelInfo` 校验精确模型能力；`DeepSeekAdapter` 每次 stream 快照 endpoint/credential/options，fetch `/chat/completions`，解析 SSE 为 `StreamChunk`。 | 无 provider/model 在 `buildRequest` 直接拒绝；无 adapter 形成 `NO_ADAPTER` finish；HTTP 401/403、429、400、5xx 映射稳定错误码；caller abort 为 `ABORTED`，idle watchdog 为 `TIMEOUT`；iterator 未耗尽时 `return()` 收口。 | `packages/core/agent-loop/src/agent.ts:407-494`；`packages/llm/llm/src/index.ts:154-232,771-927`；`packages/llm/llm-deepseek/src/adapter.ts:214-345` |
| Session/event | `Session.append(type, data, surface metadata?)`；`session/event` 是 post-commit observe-only feed，`session/flush` 是 awaited durability barrier。 | append 对 data 和 surface metadata 做一次 lossless snapshot，分配连续 `seq`、冻结事件、先入 log 后通知；model history 从 surface/log 派生。 | 非 JSON、非法 surface、重入 append 在 log 变化前拒绝；observe listener throw/reject 被记录并隔离，不回滚已提交 append；`session/flush` listener 聚合失败由调用方看到。 | `packages/core/session/src/index.ts:570-655`；`packages/core/session/src/known-event-types.ts:9-64` |
| Subprocess | `ctx.subprocess.spawn(SubprocessSpawnSpec)` 或 `spawnTerminal()`；spec 显式给 argv/cwd/stdio/grace/signal/env。 | 普通 spawn 立即返回 live handle；collect reader 按 byte offset 非消费读取；`done` 报 exit code/signal；terminal handle 负责 PTY/foreground group。 | abort 只触发 provider 的 terminate；POSIX detached process group 走 SIGTERM→grace→SIGKILL，Windows 走 `taskkill /T`；`done` 仅在 spawn-level failure reject，cause classification 由 caller 负责。 | `docs/subsystems/subprocess.md:89-172,221-249`；`packages/subprocess/subprocess-local/src/spawn.ts:318-369,417-542` |
| Cordis event bus | `ctx.emit/parallel/serial/bail/waterfall`；listener 由 `ctx.on()` 注册到当前 fiber。 | `emit` 同步触发不等待；`parallel` 等待全部；`serial` 顺序等待并可 bail；`waterfall` 由 listener 调 `next()` 委托；listener 随 fiber dispose。 | waterfall 不调用 `next()` 即 veto；parallel 汇总 rejection；emit 不等待异步 rejection，领域 owner 必须自行 containment；filter 按 context/agent carrier 应用，`global` 可绕过过滤。 | `vendor/cordis/src/events.ts:24-32,43-107,158-243,245-301` |

### 19.2 真实对接调用链

| 链路 | 源码级调用顺序 | 中间状态与边界 |
|---|---|---|
| 一次 Agent turn | `ReactLoopAgent.wakeDriver()` → `kick()` → `turn()` → `preStep()` → `systemPrompt.assemble()` → `agent/pre-step` → `step()` → `buildRequest()` → `llm.prepareCall()`/`llm.stream()` → append assistant events → `executeToolCalls()` → append tool results → `step/end` → `agent/turn-stopping` → `turn/end` | `phase` 只有 `idle/maintenance/running`；Inbox 是输入唯一入口；`session.append` 是 durable commit，status 只在 phase commit 后发布。 |
| 工具调用 | `executeToolCalls()` → `ctx.tools.executionMode()` → scheduler `prepare()` → `ToolRuntime.createExecution()` → `tools/pre-execute` → approval/monotonic guards → scheduler `dispatch()` → `tools/execute` → `ToolDefinition.execute()` → output schema/render/meta → `tools/post-execute` → materialize/freeze → `tools/result` → `tool/result` | policy 只能在自己的阶段改变结果；caller signal 与 wrapper signal fuse；call/result 由 scheduler 用 call event seq 建立 source reference。 |
| DeepSeek 模型 | `buildRequest()` → `LlmRuntime.prepareCall()` → adapter `resolveModelInfo()`/defaults → one-shot `PreparedLlmCall.stream()` → `streamWithRegistration()` → `adapterStream()` → `DeepSeekAdapter.stream()` → `request()` → `fetch()` → `parseSse()` → `translate()` → `BlockAssembler` → `assistant/message` | route registration 与准备结果绑定，避免 HMR 在 capability lookup 与实际 stream 之间换 adapter；stream 内 endpoint、key、user id 同一 generation，in-flight 不读新配置。 |
| 沙箱执行 | `SandboxPolicyService.resolve()` → bash/fs/terminal consumer 选择 mode → `LocalSandboxProvider.confine()` → `selectRunner()`/一次性 functional probe → runner argv + evidence dialect → `ctx.subprocess.spawn()` → consumer 按 stderr/exit facts 区分 runner failure/denial/task failure | provider 只包装 exact argv，不接 shell 字符串；policy owner 统一 cwd/mode precedence；`danger-full-access` 是显式 bypass 分支，不是 provider fallback。 |
| 子进程与输出 | `spawnSubprocess()` → `childEnv(scrubbedParentEnv + explicit env)` → detached `child_process.spawn()` → `OutputCollector.push()`/pipe reader → child close 或 drain grace → `done`；`terminate()` 启动 `observeTreeExit()` 与 signal escalation → `waitForExit()` 确认树消失 | collect 结果是 tail 保留；spill 超 cap 时删除并停止宣称完整；direct child close 不等价于 process tree quiescence。 |
| 会话持久化 | `Session.append()` → `session/event` snapshot callbacks → persistence coordinator batch → JSONL `appendLines()`/SQLite transaction → `session/flush` 等待各 listener；冷恢复走 header/seq/event/surface validation → repair closers → `Session.fromRestore()` | persistence 不在 core/session 直接绑定；JSONL append/sync 失败尝试 rollback 到旧 byte size；torn tail 只能恢复 committed prefix，不能静默丢历史。 |
| CLI 进程退出 | `createProcessShutdown(dispose, forceExit, complete, timeoutMs)` → `shutdown(code)` coalesce disposal 或 `interrupt(code)`；第二次 interrupt 立即 force exit；disposal reject/超时也 force exit | 5 秒是 CLI controller 默认 grace；自然完成只设置 exit code，信号/重复中断升级为强退；应用 disposer 必须自行达到 quiescence。 |

### 19.3 关键小节点与并发语义

1. **`ReactLoopAgent.preStep()` 是模型可见输入的最后编排点。** 它先 claim Inbox，再组装 prompt，随后由 `RuntimeContextProjection` 把动态上下文作为可重建的 plugin-sourced `user/message` 候选交给 `agent/pre-step`；signal 在 waterfall 返回后再次检查。`turn()` 的首个 claim 被 reject 或改写为空时仍写 `turn/start`/`turn/end`，但不写 `step/start`，这一区分不能被 UI 的“没有回复”替代。
2. **`ReactLoopAgent.step()` 只把完整 assistant 事实提交给 tool scheduler。** 每个 chunk 先 append `assistant/chunk`，`BlockAssembler.finish` 发生 error/aborted 时进入 `agent/request-error`；只有成功聚合才 append `assistant/message`。因此中途失败不会凭半截 chunk 派发 tool call，但原始 chunk 仍可供 replay/UI 使用。
3. **`ToolRuntime` 把扩展 policy 与不可逆边界分开。** code-mode collapse 在 `tools/pre-execute` 前拒绝 model-direct 非 `run_code`；approval `ask` 没有 ApprovalService 时降级 deny；guard 只有 deny 权没有 allow 权，不能由后来的 guard 翻转；`finalizeContent` 在执行开始时 snapshot，结果 materialize 和 observer failure 都不能改写已选 outcome。
4. **`runGroup()` 的“并行”只覆盖 dispatch/body。** pre-execute 仍按顺序 await；并行组中途若 registry 重分类为 exclusive，则先 drain 当前 pool，下一次以 barrier 启动；abort 时已启动调用要先 settle 并接收 additional context，再为未启动 call 写合成错误结果；scheduler 内部异常则不补结果，保留“有 call 无 result”作为真实故障证据。
5. **`LlmRuntime.prepareCall()` 是 adapter binding commit。** 它校验模型能力并 materialize adapter default，返回只能 dispatch 一次的 handle；route replacement 先完整校验后一次性替换，避免观察者看到空 route。模型目录是 advisory，未列出的 model 不因此被拒绝，精确 model metadata 仍须合法。
6. **`LocalSandboxProvider.selectRunner()` 的 probe 是缓存的 capability verdict。** Linux 多候选按 `bwrap`→`landlock` 探测；macOS Seatbelt 与 Windows ACL 是当前单候选，运行时拒绝仍走 fail-closed。Windows workspace ACE 是跨 session 的 standing grant，private temp grant 随 provider dispose 撤销；crash 不会执行撤销。
7. **`OutputCollector` 同时维护 retained tail、whole-stream offset 和可选 spill。** 首次超过 memory cap 时把既有 chunks 和后续 chunks 写入 0600 random spill；超过 spill cap 会删除 spill，只保留 bounded tail；`seal()` 失败则停止返回 spill path，不能把不完整文件当完整证据。
8. **事件不是同一种一致性。** `session/event` 是已提交后的 fire-and-forget feed；`session/flush` 才是 awaited durability barrier；`agent/*`/`tools/*` waterfall 可以拦截正在进行的工作；Cordis fiber dispose 只自动解除 listener/effect，不会替调用方等待一个没有 owner 的 detached task。

### 19.4 资源生命周期与四种终态

| 资源 | 正常完成 | 业务失败 | 主动取消/超时 | 宿主/子进程崩溃与残留边界 |
|---|---|---|---|---|
| Agent、scope、Inbox | `turn/end` 后回 idle；owner 保留 handle 或显式 dispose。 | error 被 driver containment 收口，turn 仍写 end；未提交的创建事务回滚。 | abort 当前 phase，清 Inbox（除非 `keepInbox`），等待 idle；dispose 不 latch 新 wake。 | owner unload 关闭 initiator、等待返回 Promise 边界，再 dispose registry/session/scope；同进程任意不合作 callback 仍不是可强杀安全边界。 |
| Tool body、policy listener | body settle，post/finalize，冻结结果并通知。 | thrown value 规范化为 `ToolFailure`；output schema/render 失败不泄漏成功 value。 | pre-body → `ABORTED_BEFORE_DISPATCH`；body started → cooperative drain 后 `ABORTED`；signal listeners 在 fuse dispose 时移除。 | worker/宿主崩溃不能由 ToolRuntime 证明外部副作用结果；恢复只能把未知副作用标作 unknown 并要求外部核验。 |
| LLM fetch/SSE/iterator | `finish` complete，watchdog dispose；正常迭代器自然结束。 | HTTP/provider/parse/translate error 形成 terminal failure chunk；retry 只在 `agent/request-error`/retry policy 允许时发生。 | caller abort 与 idle watchdog 使用同一 upstream signal；finally abort consumer 并尝试 `iterator.return()`。 | 网络断开只证明请求失败，不证明 provider 未产生副作用；没有 API key 的 e2e 是 skip/未验证，不是 provider pass。 |
| 子进程、process group、PTY | `done` 收集 exit facts；`waitForExit()` 确认整个 tree gone。 | 非零 exit 是业务结果，不能自动等同 sandbox runner failure；collect tail/spill sealed。 | abort → `terminate()`，POSIX SIGTERM→grace→SIGKILL，Windows `taskkill /T /F`；grace timer 保持 ref，防止父进程提前退出。 | direct child close 但 descendant 尚存时仍可继续 signal；host-exit 用内部 `terminateForHostExit()`；若宿主自身突然崩溃，OS temp/spill 和子树只能靠外部 survivor sweep 验证。 |
| Sandbox runner/ACL | runner argv 被执行，消费者用 enforcement fact 归因。 | runner refusal 是 `SANDBOX_UNAVAILABLE`/runner failure；受限命令是 denial，不应被包装成基础设施失败。 | 每次调用携带独立 policy；provider selection verdict 缓存但不把调用 policy 写入全局可变状态。 | Windows private temp ACE/目录正常 dispose 清理；workspace standing ACE 按设计保留；crash 跳过 cleanup，随机 temp path/SID 不复用旧 session 授权。 |
| Session log/persistence | append → batch → fsync/SQLite transaction；显式 `session/flush` 后才可宣称 durability barrier。 | append validation 或 backend error 暴露给 owner；JSONL 部分写尝试 truncate+sync rollback。 | flush signal/等待由 persistence coordinator 负责，不能把已 append 事实从内存 log 删除；取消不自动伪造成功。 | JSONL torn frame 只恢复 committed prefix，再以 repair/closer 记录未完成工具的 `TOOL_NOT_STARTED`/`TOOL_OUTCOME_UNKNOWN`；未知 event type 除非 `ignorable`，否则拒绝解释。 |

### 19.5 失败、超时、取消与恢复矩阵

| 反向场景 | 当前源码行为 | 验证边界 |
|---|---|---|
| 缺 provider/model | `buildRequest()` 在 provider 或 model 为空时抛错，未进行模型 I/O。 | 源码确定；需真实入口验证 profile 是否确实提供 route，不能只看配置声明。 |
| 缺 LLM adapter | `prepareCall()` 的 `NO_ADAPTER` 可回退为未 prepared config，最终 `LlmRuntime.adapterStream()` 产生 terminal failure chunk。 | 源码确定；未在当前核对启动 profile 验证真实输出和退出码。 |
| 非法/空工具参数 | `executeToolCalls.parseArguments()` 将空字串映射 `{}`，非法 JSON 保留原始文本；registry 再做 lossless snapshot，output schema 对成功 value 校验。 | 源码确定；必须分别测试空、非法 JSON、非 JSON value 和 oversized value，不能把“工具返回 error”算参数校验通过。 |
| 重复 tool call/并发竞态 | `isConcurrencySafe()` 只有 exact `true` 才并行；异常或未知 classifier fail closed 为 exclusive；`repeat-tool-reminder` 只是同 Agent 连续完全相同调用的启发式提示。 | 源码/README 确定；未执行真实多步模型和恢复后行为。 |
| 工具超时/取消 | `timeoutMs` 由 `tools/execute` policy 使用 cooperative signal；registry 根据 body 是否启动选择两个 abort code，已启动 promise 仍须 settle。 | 源码确定；不能宣称能强杀同进程代码；需外部检查未留下子进程/文件/锁。 |
| sandbox provider 缺失/runner 不可用 | `SandboxUnavailableError(SANDBOX_UNAVAILABLE)` fail closed；Local provider 多候选 probe 全失败则 unavailable；runner signature/exit gate 与 denial signature 分离。 | 源码确定；本机 macOS Seatbelt 是否可实际启动未当前核对验证。 |
| stream 断线/HTTP 错误/空 body | DeepSeek 将 fetch transport、HTTP status、无 body、SSE/translate failure 分类；401/403=`AUTH`、429=`RATE_LIMIT`、400 context overflow 或 `INVALID_REQUEST`、5xx=`SERVER`。 | 源码确定；未使用 API key 做真实 provider e2e，网络/配额/代理状态未知。 |
| event listener throw/reject | `session/event`、`tools/result` 等 observe feed 隔离 listener failure；waterfall listener 不调 `next()` 是 veto；`parallel` 汇总 rejection。 | Cordis/owner 源码确定；未用实际插件 unload 组合验证所有 listener 顺序。 |
| persistence 部分写/损坏尾部 | JSONL 写入/`sync()` 失败尝试恢复旧 size；读取识别 torn frame，恢复 committed prefix 并通过 coordinator 写 repair/closer；SQLite 使用事务和当前 schema 约束。 | 源码/包文档确定；未制造真实磁盘故障或跨进程竞争。 |
| 子进程 direct child 退出但 helper 存活 | `done` 受 close/drain grace 约束，`waitForExit()` 继续观察 process group；terminate 的 SIGKILL timer 不因 direct child settle 清掉。 | 源码和 fixture 存在；未在当前核对启动树形 fixture 做 survivor sweep。 |
| runtime closure/发布依赖缺失 | `scripts/verify-runtime-closure.ts` 从 `python/sdk-runtime/package.json` BFS workspace dependencies，要求必需 workspace peer 直接出现在 runtime dependencies；失败退出 1。 | gate 源码确定；当前核对未执行 `pnpm run verify-runtime-closure`，不能写成 gate pass。 |

### 19.6 真假验证表：存在、执行与外部事实分栏

| 验证层级 | 仓库中的证据 | 当前核对状态 | 可宣称范围 |
|---|---|---|---|
| 源码/静态契约 | 直接读取上述源码、README、`docs/architecture.md`、`docs/testing.md`、`docs/subsystems/{sandbox,subprocess}.md`；路径和函数已回链。 | **已完成（静态取证）** | 可确认实现边界、状态机和错误分类；不能证明当前安装制品可启动。 |
| 测试源码存在性 | agent-loop、tools、sandbox-local、subprocess-local、LLM adapter、CLI shutdown、persistence、snapshot/e2e 等 `tests/` 与 fixture 存在。 | **已核对存在；未执行** | 只能说“有覆盖意图/测试代码”，不能说 pass。 |
| 单元/组合执行 | `pnpm run test`、聚焦 Vitest、Loader real-composition tests。 | **未执行** | 不宣称单元、HMR、组合或取消测试通过。 |
| 真实 API | `pnpm run test:e2e`，依赖 `DEEPSEEK_API_KEY` 和外部 provider。 | **未执行** | 不宣称 DeepSeek 真实请求、配额、代理、网络和 provider 状态通过。无 key self-skip 仍是未验证。 |
| keyless snapshot/协议 | `pnpm run test:snapshot`，ACP/headless JSON-RPC、持久化和 model-visible 输出回放。 | **未执行** | 不宣称协议、日志重放或用户可见输出与预期一致。 |
| built/artifact/process | `pnpm run build`、built bin/worker/SDK runtime smoke、plain Node 子进程入口。 | **未执行** | 不宣称 `lib/`、worker、native launcher、Python bundled runtime 或发布包可用。 |
| 文档/生成 gate | `pnpm run doc-sync`、`verify-*`（含 `verify-runtime-closure`、catalog/invariant/links）。 | **未执行** | 本文的源码路径已人工核对；不宣称仓库文档门禁、生成物新鲜度或 runtime dependency closure 通过。 |
| 外部状态/清理 | 重新读取文件、进程树、端口、临时目录、spill/ACL/数据库锁，验证“世界”而不是 Agent 自报。 | **未执行** | 不能宣称工具副作用 exactly-once、进程树无残留、spill/ACL 无残留或崩溃恢复成功。 |

### 19.7 旧细探逐条裁决与后续剩余风险

| 旧细探条目 | 收口结论 |
|---|---|
| `everything is a plugin`/Cordis | **吸收**：本文第 1、3、4、19.1 明确 Service Definition/Provider/Consumer、fiber effect 和 event dispatch；`dsh-plugin` GitHub topic 仅是生态发现线索，不是运行时可发现性证据。 |
| `core`、`guard` | **吸收并拆边界**：Agent registry 与 loop、Session、Tools、guard middleware 分属不同 owner；`guard` 不是特权核心，也不提供强制进程终止。 |
| `session` 双后端、checkpoint、projection/cache/stats | **吸收并加失败语义**：事实是 `SessionEvent`，persistence 是可替换 provider，cache 不是事实源；flush、rollback、torn-tail、unknown side effect 已单列。 |
| `sandbox` local/policy/windows-acl | **吸收并纠偏**：policy 统一 mode/root/session precedence；local runner 只提供 same-world file-effect enforcement；Windows `partial`、runner/denial 两类证据和 crash cleanup 边界不能省略。 |
| `skill`、`workflow`、`subagent`、`plan`、`goal`、`feedback`、`compaction`、`interaction` | **吸收为领域能力地图**：它们通过能力 seam、SessionEvent 或 Agent events 接入，不合并成“大核心”；worker thread 不是安全沙箱，plan 不是授权。 |
| `python/`、`native/`、`vendor/` | **吸收为运行/发布边界**：Python 是 SDK/bundled runtime，native 是 Landlock launcher，vendor 是 Cordis source of record；均不另造 Agent 核心层。 |
| “开发者预览、破坏性变更” | **保留为版本风险**：根 `AGENTS.md` 的 pre-release stance 仍有效，session format/schema 和 public package contract 不应被旧细探的概括性兼容假设覆盖。 |

后续收口后的未确认项仍是实测边界，而不是实现缺陷的推断：本机 profile 的实际 Loader 组合、Seatbelt/Landlock/Windows backend 的运行态 enforcement、真实 DeepSeek API、跨进程 persistence writer、built/Python/native artifact、崩溃后的子进程/临时目录/ACL survivor sweep 均未在当前核对执行。本文因此把“源码存在”“测试存在”“当前核对静态核对”“真实执行”“外部状态复核”严格分栏，不把任何 `skip`、历史制品、日志或模型自报写成通过。

## 19.8 2026-08-22 远程对账与代码图增量

| 项目事实 | 证据 | 结论 |
|---|---|---|
| 本地 checkout | `git rev-parse HEAD` = `528c682e061696f5a160f363f236ecbf53cbd006`，分支 `master`，origin=`https://github.com/deepseek-ai/deepseek-harness.git` | 本文前述静态事实绑定此 checkout |
| 远程 HEAD | 4780 代理 `git ls-remote` 返回 `b150a551b8d465e31e418e1b2eaf5e79bbb7d28e`（`HEAD`/`master`） | 远程领先本地；本轮未能完成隔离 clone/codeload，故没有把远程新源码混入本地证据，也没有覆盖共享 checkout |
| CodeGraph | 目标 `.codegraph` 存在，`codegraph status` = 4,066 files / 43,235 nodes / 243,611 edges；`codegraph explore 'AgentLoop executeToolCalls Session append'` 显示 `append` 运行时分派到 8 个 `SessionPersistence` 实现，`executeToolCalls` 位于 `packages/core/agent-loop/src/tool-calls.ts:59` | **已证静态导航**；持久化 provider 选择必须按运行时实现继续核对 |
| 当前关键锚点 | `packages/core/session/src/index.ts:604-609` 的 `Session.append`；`packages/core/agent-loop/src/tool-calls.ts:59` 的工具调度入口 | 当前文档的事实链仍可定位，但远程领先提交可能改变行号和实现，不能外推到 b150 快照 |

本轮仅使用 shell、Git 和目标仓库 CodeGraph；**未调用其他 MCP**。远程 SHA 已确认但隔离快照下载在 4780 长连接窗口内未完成，因此远程增量源码审计仍是未完成项；源码、依赖、测试和配置均未修改。

### 19.9 2026-08-22 固定 SHA 定点请求复核

本轮按任务边界仅通过 `http://127.0.0.1:4780` 发起 3 个 raw 定点请求，目标均锁定 `b150a551b8d465e31e418e1b2eaf5e79bbb7d28e`。代理 TCP/HTTP CONNECT 成功，但 TLS 握手超时；以下退出码是实际 `curl --connect-timeout 5 --max-time 30 -fsSL` 结果：

| 定点文件 | URL | 退出码/字节数 | 可用结论 |
|---|---|---:|---|
| Session 内存日志 | `https://raw.githubusercontent.com/deepseek-ai/DeepSeek-Harness/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/packages/core/session/src/index.ts` | `28 / 0` | 远程内容未取得；不得把当前 checkout 行号外推到该 SHA。 |
| 工具调度 | `https://raw.githubusercontent.com/deepseek-ai/DeepSeek-Harness/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/packages/core/agent-loop/src/tool-calls.ts` | `28 / 0` | 远程内容未取得；并发/取消结论仍只绑定本地静态证据。 |
| JSONL 持久化 | `https://raw.githubusercontent.com/deepseek-ai/DeepSeek-Harness/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/packages/session/session-persistence-jsonl/src/index.ts` | `28 / 0` | 远程内容未取得；不能宣称固定 SHA 的尾部修复语义未变。 |

本轮未下载 codeload 压缩包、未 clone、未覆盖共享 checkout；因此远程增量仍为“SHA 已确认、源码未核验”。下一次应优先重试同一三个文件或使用代理恢复后的隔离临时目录，并在成功读到内容后再填写差异，而不是凭远程分支名推断实现变化。
