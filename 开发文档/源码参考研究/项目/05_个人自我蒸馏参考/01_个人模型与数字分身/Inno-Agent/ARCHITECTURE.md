# Inno-Agent 架构取证

```text
Inno Agent（单进程、单活动 AgentSession；所有提示串行化）
│
├─ 用户入口层
│  ├─ Electron 桌面：electron/main.js + preload.cjs
│  │  └─ 启动本地 HTTP server，轮询 /health，再加载 Web UI
│  ├─ Web UI：apps/inno-agent/web/src/main.tsx → react/App.tsx
│  │  └─ REST / SSE / WebSocket 客户端；会话、工作区、Notebook、设置面板
│  ├─ CLI：apps/inno-agent/src/cli.ts → PI SDK main()
│  └─ 个人渠道：Feishu / WeChat / QQ
│     └─ ChannelRegistry → PersonalChannelDispatcher
│
├─ 接入与应用编排层
│  ├─ apps/inno-agent/src/server.ts
│  │  ├─ /health、静态文件、SPA fallback
│  │  ├─ REST 路由域：chat / sessions / workspaces / learner / wiki / jobs
│  │  │                skills / presets / practice / settings / channels
│  │  └─ /api/terminal/.../ws → WebSocket + PTY
│  ├─ apps/inno-agent/src/agent/pi-runner.ts
│  │  ├─ initSession() 创建 PI AgentSessionRuntime
│  │  ├─ runPrompt*() 通过共享 Promise queue 串行执行
│  │  ├─ 会话/工作区切换、取消、SSE 事件、图片降级/OCR fallback
│  │  └─ Provider registry 刷新与模型切换
│  ├─ chat/stream-registry.ts + agent/question-bridge.ts
│  │  └─ 保存进行中的流、问题卡片、重连/恢复所需事件
│  └─ workspace/workspace-registry.ts
│     └─ WorkspaceMeta 与 session → workspace 绑定
│
├─ PI Agent 运行时适配层（第三方内核不修改）
│  ├─ agent/inno-extension.ts → ExtensionAPI
│  │  ├─ 注册 providers 与 Inno 工具
│  │  ├─ before_agent_start 注入系统提示、L1 Context Pack、L3 召回、工作区上下文
│  │  ├─ tool_call 路径边界与 open/xdg-open 拦截
│  │  ├─ turn_end 增量索引 L3
│  │  └─ 可选 MCP、pi-sandbox、pi-subagents、ask_user_question
│  └─ @earendil-works/pi-ai / pi-coding-agent / pi-web-ui
│
├─ 领域能力层
│  ├─ L1 学习者画像：memory/learner/
│  │  ├─ events.jsonl 证据事件 + profile.json 紧凑画像/派生快照
│  │  ├─ evidence → state-engine → Context Pack / review 判断
│  │  └─ learner tools + /api/learner/*
│  ├─ L2 Wiki：memory/l2/
│  │  ├─ raw source → parser/converter → manifest + Wiki Markdown/frontmatter
│  │  ├─ node:sqlite 索引：BM25 lexical candidates + 一跳图扩展
│  │  └─ l2 tools + /api/wiki/* + Notebook/Graph UI
│  ├─ L3 跨会话召回：memory/l3/
│  │  ├─ sessions/*.jsonl → indexer → SQLite chunks + FTS5
│  │  └─ lexical hits → coverage threshold / 去重 / 排除当前会话 → prompt 注入
│  ├─ scheduler/
│  │  └─ jobs.json → CronScheduler → job-runner → runs.jsonl → 渠道推送/会话消息
│  ├─ channels/
│  │  └─ Feishu 原生、WeChat iLink、WeChat/QQ bridge → dispatcher → PI prompt
│  ├─ terminal/
│  │  └─ workspace PTY → WebSocket output → RunRecordStore → agent practice tools
│  ├─ content-source/ + presets/
│  │  └─ GitHub/bundle content hub → skills/preset cache → PI resources/workspace
│  └─ agent/document-tools.ts + ocr-tools.ts + practice-tools.ts
│
└─ 持久化与运行时状态
   ├─ config.json / settings.json / mcp.json / skills.json
   ├─ data/learner、l2、l3、sessions、jobs、channels、runs、workspaces、log
   ├─ workspace/（工作区文件；agent.md 与 .skills/可作为当前会话上下文）
   └─ storage/file-store.ts：JSON、JSONL、文本的原子写入/尾部读取/轮转

主要数据流：
用户消息/渠道消息
  → server 路由或 PersonalChannelDispatcher
  → pi-runner 的共享串行队列
  → PI AgentSession.prompt()
  → before_agent_start 组装系统提示（L1 + L3 + workspace）
  → LLM provider ↔ PI 工具调用
  → L1/L2/L3/Job/Workspace/Practice 持久化
  → AgentSession 事件
  → Web SSE、渠道回复或 CLI/TUI；文件变更另经 WebSocket/Workspace UI 展示
```

# Inno Agent 架构文档

## 1. 项目定位

Inno Agent 是一个面向单个学习者的个人学习智能体。根 README 将目标描述为：以 PI coding-agent SDK 为 Agent 内核，在不修改 SDK 内核的前提下，叠加三层记忆、主动调度、个人 IM 渠道和 workspace-scoped Practice Lab。

三层记忆的职责不同：

- **L1 learner profile**：保存学习目标、知识状态、误区和偏好，并把紧凑的 Context Pack 注入每轮系统提示。
- **L2 native wiki**：保存可读、可编辑的 Wiki 页面、来源材料与知识图谱，支持索引和检索。
- **L3 session recall**：读取 PI 会话 JSONL，建立 SQLite FTS5 索引，在相关度阈值通过时召回旧会话片段。

项目提供三种产品形态，但共享同一套后端运行时和运行时目录约定：

- Electron 桌面应用：`electron/main.js` 启动本地 Node HTTP server，再打开 `http://localhost:3000`。
- Web UI：Node HTTP server 提供 API/SSE/静态文件，前端使用 React 19，并保留部分 Lit 组件。
- Terminal CLI：`apps/inno-agent/src/cli.ts` 直接调用 PI SDK 的 TUI 入口，不经过 HTTP。

源码还明确写出了非目标：没有认证/租户隔离，不面向多用户并发或水平扩展；单进程内只有一个活动 AgentSession，跨会话操作共享一条串行 Promise queue。队列繁忙时，跨会话操作可以返回 `409 session_busy`，而不是无限等待。

## 2. 真实分层与职责

### 2.1 入口与启动层

- `apps/inno-agent/src/cli.ts`
  - 解析运行时参数，解析 `RuntimePaths`，调用 `applyRuntimeEnvironment`。
  - 加载配置、设置代理绕过、准备目录和 MCP 配置。
  - 创建 `createInnoExtension`，按需加入 MCP、sandbox 扩展，最后调用 PI 的 `main()`。
  - 显式传入 `--no-skills --skill <skillsDir>`，使 CLI 只从项目配置的 skills 目录加载技能。
- `apps/inno-agent/src/server.ts`
  - 是无 Web 框架的 Node `http.createServer` 入口。
  - 端口监听立即启动；`/health` 与静态页面无需完成完整业务 bootstrap。
  - 首个 `/api/*` 请求触发 `ensureBootstrapped()`，依次加载配置、建立 stores、渠道、AgentSession、dispatcher、scheduler 和终端管理器。
  - 通过 `handle<Domain>Routes()` 把路由分到 `server/routes/`，未匹配的 `/api/*` 返回 JSON 404，其他 GET/HEAD 路径才走 SPA fallback。
- `electron/main.js`
  - 首次启动在 `~/.inno-agent/config/config.json` 创建默认配置。
  - 用子进程启动编译后的 `apps/inno-agent/dist/server.js`，设置 `ELECTRON_RUN_AS_NODE=1` 和 `INNO_*` 环境变量。
  - Loading 窗口轮询 `/health`；服务就绪后创建主窗口。
- `apps/inno-agent/web/src/main.tsx` → `web/src/react/App.tsx`
  - 注册样式、国际化和 legacy `<markdown-block>`，以 React `createRoot` 挂载应用。
  - `App` 初始化 sessions/workspaces/settings stores，组合 `SessionSidebar`、`ChatCenter`、`WorkspacePanel` 和 `SettingsOverlay`。

### 2.2 运行时路径、配置和存储基础设施

- `apps/inno-agent/src/runtime.ts`
  - `parseRuntimeArgs()` 支持 `--config`、`--config-dir`、`--data`、`--home`、`--skills`、`--workspace`、`--port`、`--sandbox`。
  - 路径优先级是 CLI 参数 → `INNO_*` 环境变量 → legacy 项目路径或 `~/.inno-agent` 默认值。
  - 派生目录包括 `learner/`、`sessions/`、`jobs/`、`l2/`、`l3/` 和 `preset-cache/`。
  - `applyRuntimeEnvironment()` 将解析结果写回 `process.env`，并设置 `PI_CODING_AGENT_SESSION_DIR`、`PI_CODING_AGENT_DIR` 供 PI SDK 与 sandbox 使用。
- `apps/inno-agent/src/config.ts`
  - `InnoConfig` 聚合 providers、channels、memory、simpleMode、mcp、scheduler、contentHub、OCR、Tavily 等配置。
  - `normalizeConfig()` 确保至少有一个 provider/model，并兼容旧的 `openai` 配置；`normalizeMemoryConfig()` 默认开启 L1/L2/L3；Simple Mode 和 MCP 默认关闭。
  - `saveConfig()` 通过 `writeJson()` 原子写入，并以 `0600` 保护包含 API key/bridge token 的配置。
- `apps/inno-agent/src/storage/file-store.ts`
  - 提供 JSON/文本原子写入、JSONL 追加、JSONL 尾部读取和超过阈值后的 archive 轮转。
  - `events.jsonl`、scheduler runs 等追加式日志可设置 10 MB 轮转；读取尾部时会丢弃窗口中可能被截断的首行。

### 2.3 PI SDK 适配与 Agent 编排

- `apps/inno-agent/src/agent/pi-runner.ts`
  - `initSession()` 创建 `SessionManager`、PI services 和 `AgentSessionRuntime`，注册当前配置的 provider/model，并绑定扩展。
  - `_queue` 与 `enqueue()` 是进程级共享串行队列；`runPromptSerialized()`、`runPromptInSession()`、`runPromptStreamingInSession()` 都从这里进入。
  - `switchSessionFile()`、`createNewSession()`、`applyWorkspaceCwd()` 负责活动会话和工作区切换；`abortPromptForTurnToken()` 支持精确取消。
  - 流式运行把 PI `AgentSessionEvent` 转发给 server/channel，并支持 provider 自动重试、会话事件最终化和断线重连。
  - 图片请求按模型能力发送；文本模型或 provider 拒绝图片时，会移除原生图片并转向 workspace OCR 提示/重试路径。
- `apps/inno-agent/src/agent/inno-extension.ts`
  - `createInnoExtension()` 是主要的应用扩展装配点，使用 PI `ExtensionAPI` 注册 providers、L1/scheduler/channel/L2/L3/document/OCR/Tavily/practice tools。
  - `before_agent_start` 依次注入 `INNO_SYSTEM_PROMPT`、新用户 onboarding、L1 Context Pack、工作区 `agent.md`/`.skills/`、阈值门控的 L3 recall、最近一次 Practice Lab run 以及原始系统提示。
  - `tool_call` 对 `write`/`edit` 强制当前 workspace 路径边界，对 bash 拦截 `open`/`xdg-open`；`tool_result` 统一记录工具错误。
  - `turn_end` 对活动会话做 L3 增量索引。L2/L3 的索引 backfill 在后台执行，不阻塞启动。

### 2.4 L1 学习者状态层

目录：`apps/inno-agent/src/memory/learner/`。

- `types.ts`
  - `LearnerProfile`：`learner_id`、版本、目标、`knowledge_states`、`misconceptions`、偏好和摘要。
  - `LearningEvent`：事件 ID、学习者、时间、事件类型、上下文、payload、可选 `dedupe_key`、evidence 和 derived signals。
  - `LearningEvidence`：概念、证据种类/结果、提示级别、延迟、迁移距离、评分者和评分置信度等。
  - `DerivedKnowledgeState`：由事件投影出的 mastery、estimate confidence、stability、retrievability、计数、误区、证据 ID、状态标签和教学动作。
- `evidence.ts`
  - 将结构化学习证据转换为 `learning_evidence` 事件，并兼容旧的 `concept_explained`、`exercise_attempt`、`self_assessed`、`milestone_reached`。
  - 权重由证据 kind、hint level、evaluator confidence 和 spacing weight 决定。
- `state-engine.ts`
  - `projectKnowledgeState()` / `projectLearnerKnowledge()` 对证据做确定性投影；按 `asOf` 过滤未来证据。
  - 使用收敛式 mastery 更新、成功/失败对 stability 的调整，并在读取时用 `0.9^(elapsed_days/stability_days)` 计算 retrievability。
  - `stable` 需要较高 mastery/置信度、至少 7 天 stability 和迁移成功；单次讲解不会直接成为稳定掌握。
  - `applyDerivedKnowledgeState()` 把派生状态折回紧凑 profile；`applyEvidenceToLinkedMisconception()` 只处理显式关联的误区。
  - 源码注释明确这些分数是启发式、未校准概率，适合相对排序而非绝对断言。
- `profile-store.ts`
  - `profile.json` 保存紧凑画像；`events.jsonl` 保存追加事件。
  - `recordEvent()` 支持 `dedupe_key` 去重；`recordEventAndUpdateProfile()` 记录后折叠旧式增量规则；`loadRecentEvents()` 只读尾部供 Context Pack 使用。
- `context-pack.ts`、`learner-tools.ts`、`prerequisite-resolver.ts`、`teaching-entry-gate.ts`
  - 分别负责将画像转成提示上下文、暴露 Agent 工具、读取 L2 前置关系并选择 `use/diagnose/teach/repair`。
  - `docs/learner-state-engine-design.md` 标注为 Draft；文档说明完整历史投影、前端状态面板和前置关系编辑仍不是全部完成的范围，不能把设计文档中的目标当作已全部实现。

### 2.5 L2 Wiki 知识库层

目录：`apps/inno-agent/src/memory/l2/`。

- `types.ts`
  - `ManifestEntry` 描述原始来源、抽取文件、Wiki 页面、tags、contentHash、状态和来源归属；manifest 以 `data/l2/manifest.jsonl` 保存。
  - `WikiPageFrontmatter` 描述标题、类型、tags、sources、状态、confidence、concept_id 和显式 prerequisites。
- `manifest-store.ts`、`raw-store.ts`、`wiki-maintainer.ts`、`source-converter.ts`、`document-parser.ts`
  - 负责 raw source、manifest、Markdown/frontmatter、来源转换和 PDF/Office/图片文档解析。
- `l2-index-store.ts`、`l2-indexer.ts`、`l2-memory.ts`
  - Wiki 页面进入 SQLite 索引；`L2Memory` 按数据目录提供进程内 singleton，并负责 backfill、单页重建和删除。
  - SQLite 不可用时，`L2Memory` 返回 null，调用方回退到 substring 搜索。
- `l2-search.ts`
  - 先用 BM25 lexical candidates，再做一跳的 resolved wikilink、source overlap、Adamic-Adar 和 page-type affinity 扩展。
  - 代码注释明确组合分数是手工权重、只用于排序，跨查询不可比；当前不是已接入 embedding 的语义检索。
- `l2-tools.ts`、`server/routes/wiki.ts`
  - 分别提供 Agent 的 archive/query 能力和 `/api/wiki/*`、`/api/l2/raw/upload` API；Web Notebook、Graph、统计面板消费这些 API。

### 2.6 L3 跨会话检索层

目录：`apps/inno-agent/src/memory/l3/`。

- `indexer.ts`
  - 只读取 PI session JSONL 中 user/assistant 的文本 block，跳过 thinking、toolCall、toolResult。
  - 按文件 mtime 增量判断；chunk ID 为 `${sessionId}:${ordinal}`，对变更会话先删后重建，保证重索引幂等。
- `sqlite-store.ts`
  - `L3Store` 使用 `node:sqlite`，建立 `chunks`、FTS5 `chunks_fts`、预留的 `embeddings`、`index_state` 表。
  - CJK 文本用重叠 bigram，ASCII/数字词转小写完整 token；查询与建索引使用同一分词函数。
  - Node <22.5 或 `node:sqlite` 不可用时返回 null，调用方将 L3 视为禁用；`embeddings` 目前只是预留 schema，没有真实 embedding provider 路径。
- `recall.ts`
  - `recall()` 先按 BM25 过采样，再按 query-token coverage 阈值过滤；排除当前 session、去重，并限制结果数。
  - `formatRecallForPrompt()` 将片段格式化为“仅供参考”的系统提示段，不把旧对话当作当前事实。

### 2.7 调度、渠道、工作区和 Practice Lab

- Scheduler：`scheduler/types.ts`、`job-store.ts`、`cron-scheduler.ts`、`job-runner.ts`
  - `ScheduledJob` 持久化到 `jobs.json`，`JobRunRecord` 追加到 `runs.jsonl`。
  - `CronScheduler` 启动后 5 秒首次检查、之后每 60 秒检查；同一 job 用 `running` 集合避免重叠执行。
  - `JobStore.mutate()` 对同一 job 串行化读改写，避免 cron、手动 API、Agent 工具并发更新丢失计数。
  - 任务可从 cron、`/api/jobs/:id/run` 或 `run_scheduled_job` 工具触发，并可由 `PersonalChannelDispatcher` 推送。
- Channels：`channels/channel.ts`、`personal-dispatcher.ts`、`feishu/`、`wechat/`、`bridge/`
  - `ChatChannel` 定义 verify/parse/reply/push/sendFile；`ChannelRegistry` 管理已注册渠道和默认 PushTarget。
  - Feishu 使用 `@larksuiteoapi/node-sdk`；WeChat 支持 iLink 或 sidecar bridge；QQ 使用 bridge。
  - dispatcher 按 `channel:chatId` 持久化会话绑定，去重消息，按需要创建 channel workspace/session，并把消息以带来源标记的 prompt 送入 PI runner；支持渐进式 streaming card 和非流式 fallback。
- Workspace：`workspace/workspace-registry.ts`
  - `WorkspaceMeta` 保存 id/name/相对路径/时间/temp 标记；registry JSON 与 session-workspace map 位于 data 目录。
  - 支持普通工作区、共享 tmp、channel workspace、preset workspace，并确保解析路径不逃出 workspace 根。
- Practice Lab：`terminal/terminal-session-manager.ts`、`local-pty-backend.ts`、`run-record-store.ts`
  - Terminal session 绑定 Inno session 和 workspace，PTY 默认使用本地 shell；WebSocket 协议见 `terminal-types.ts`。
  - `startRun()` 用 sentinel 包装命令，`processOutput()` 从 PTY 输出捕获退出码，`RunRecord` 保存命令、cwd、时间、退出码、日志路径和输出字节数；Agent 可通过 practice tools 读取。

### 2.8 Content Hub、Skills 与可选扩展

- `apps/inno-agent/src/content-source/`
  - `github` source 从仓库目录读取 skills/presets；`bundle` source 从自托管 HTTP bundle 服务读取索引和 tarball。
  - 远程内容通过 `contentHub` 配置并缓存到 `preset-cache`；内置 `apps/inno-agent/presets/` 作为离线 fallback。
- server 的 skills routes 支持列表、上传 zip/Markdown、启停、编辑、删除、reload，以及从远程 skill library import。
- `pi-mcp-adapter`、`pi-sandbox`、`pi-subagents` 通过配置/flag 启用；这些不是主路径的强制依赖。`ocr-tools.ts` 对接配置的 PaddleOCR-VL API；`tavily-tools.ts` 对接可选 Tavily 搜索。

## 3. 核心数据流

### 3.1 Web/CLI 对话流

1. Web `web/src/api/chat.ts` 以 POST `/api/chat` 或 `/api/chat/stream` 提交 prompt、sessionId 和可选图片；CLI 则直接进入 PI TUI。
2. `server.ts` 的 chat route 校验请求，创建/查找 session stream，并调用 `runPromptInSession()` 或 `runPromptStreamingInSession()`。
3. `pi-runner.ts` 把会话切换与 prompt 放在同一个 queue slot，防止其他操作在切换和推理之间抢占活动 session。
4. `inno-extension.ts` 的 `before_agent_start` 组合 L1、L3、工作区 agent.md/skills 和系统规则。
5. PI SDK 向当前 provider 发送请求；工具调用可能更新 L1/L2、调度任务、工作区文件或 Practice Lab。
6. PI 事件被转为 `StreamEventEnvelope`，通过 SSE 发送到 `ChatStore`；文件工具事件同时更新 workspace preview，完成后 Web UI 重新读取 canonical session history。
7. 对话结束后 session JSONL 持久化；`turn_end` 触发 L3 session re-index，后续其他会话才可能召回这段文本。

### 3.2 学习证据到 L1 Context Pack

`record_learning_evidence`/旧学习工具 → `LearningEvent` 写入 `events.jsonl` → `evidenceFromEvent()` 规范化 → `projectLearnerKnowledge()` 按 `asOf` 产生 `DerivedKnowledgeState` → `applyDerivedKnowledgeState()` 更新 `profile.json` 的紧凑快照 → 下一轮 `before_agent_start` 读取 profile + 最近事件 → `buildContextPack()`/`formatContextPackForPrompt()` 注入教学策略。

事件是事实记录，profile 是可重建/可继续使用的紧凑派生状态；L2 页面或 L3 对话召回不会直接等同于掌握证据。

### 3.3 来源材料到 L2

上传/Agent archive → `raw-store` 保存原始材料 → `document-parser`/`source-converter` 抽取 → `manifest.jsonl` 记录来源和处理状态 → Wiki Markdown + YAML frontmatter → `l2-indexer` 写入 SQLite → `l2-search` 结合 BM25 和一跳图信号返回结果 → Agent tool 或 `/api/wiki/*`/Notebook 展示。

### 3.4 调度与渠道流

API/Agent 创建 `ScheduledJob` → `JobStore` 写 `jobs.json` → `CronScheduler.tick()` 检查 cron/timezone → `job-runner.executeJob()` 调用当前 Agent session/提示 → `JobRunRecord` 追加 `runs.jsonl` → dispatcher/ChannelRegistry 向 Feishu、WeChat 或 QQ target 推送，并记录运行结果。

### 3.5 Practice Lab 流

Web 创建 `/api/terminal/sessions` → `TerminalSessionManager.create()` 根据 workspace registry 解析 cwd 并创建 PTY → WebSocket 传输 input/resize/run → `startRun()` 包装命令并建立 `RunRecord` → PTY output 经过 sentinel 扫描、写入日志和回传 → exit 事件完成 run；`practice-tools.ts` 让 Agent 可以读取对应 run 的输出。

## 4. 关键类、函数、数据模型与相对路径

| 类别 | 关键符号 | 相对路径 | 作用 |
|---|---|---|---|
| 运行时 | `RuntimePaths`, `parseRuntimeArgs`, `resolveRuntimePaths`, `applyRuntimeEnvironment` | `apps/inno-agent/src/runtime.ts` | 统一解析目录、环境变量和 CLI 覆盖项 |
| 配置 | `InnoConfig`, `normalizeConfig`, `saveConfig` | `apps/inno-agent/src/config.ts` | provider/model、memory、channel 等配置规范化和持久化 |
| PI 适配 | `initSession`, `runPromptSerialized`, `runPromptInSession`, `runPromptStreamingInSession` | `apps/inno-agent/src/agent/pi-runner.ts` | 建立 PI runtime、共享队列、会话切换和流式 prompt |
| 扩展装配 | `createInnoExtension` | `apps/inno-agent/src/agent/inno-extension.ts` | 注册 providers/tools/hooks，注入 L1/L3/workspace 上下文 |
| L1 模型 | `LearnerProfile`, `LearningEvent`, `LearningEvidence`, `DerivedKnowledgeState` | `apps/inno-agent/src/memory/learner/types.ts` | 学习者画像、追加事件、证据和派生状态契约 |
| L1 投影 | `createLearningEvidenceEvent`, `evidenceFromEvent`, `projectLearnerKnowledge`, `applyDerivedKnowledgeState` | `memory/learner/evidence.ts`, `state-engine.ts` | 证据标准化、确定性投影、profile 快照回写 |
| L1 持久化 | `loadProfile`, `recordEvent`, `recordEventAndUpdateProfile`, `loadRecentEvents` | `memory/learner/profile-store.ts` | profile.json/events.jsonl 的读写和尾部事件读取 |
| L2 契约 | `ManifestEntry`, `WikiPageFrontmatter`, `WikiPrerequisite` | `memory/l2/types.ts` | 来源清单、Wiki 元数据和显式前置关系 |
| L2 服务 | `L2Memory`, `searchL2` | `memory/l2/l2-memory.ts`, `l2-search.ts` | SQLite 索引生命周期、BM25+图扩展检索 |
| L3 存储 | `L3Store`, `L3Chunk`, `L3SearchHit`, `segmentForFts` | `memory/l3/sqlite-store.ts` | chunks/FTS5/index state、CJK bigram 和词法检索 |
| L3 索引/召回 | `indexSession`, `indexAllSessions`, `recall`, `formatRecallForPrompt` | `memory/l3/indexer.ts`, `recall.ts` | session JSONL → chunk，阈值门控召回 |
| 调度 | `ScheduledJob`, `JobRunRecord`, `JobStore`, `CronScheduler` | `scheduler/types.ts`, `job-store.ts`, `cron-scheduler.ts` | cron 任务、并发保护、runs 记录和执行触发 |
| 渠道 | `ChatChannel`, `ChannelRegistry`, `PersonalChannelDispatcher` | `channels/channel.ts`, `personal-dispatcher.ts` | 渠道契约、注册、去重、会话映射与回复 |
| 工作区 | `WorkspaceMeta`, `WorkspaceRegistry` | `workspace/workspace-registry.ts` | 工作区生命周期、session 绑定和路径解析 |
| 终端 | `ClientTerminalEvent`, `ServerTerminalEvent`, `RunRecord`, `TerminalSessionManager` | `terminal/terminal-types.ts`, `terminal-session-manager.ts` | PTY/WebSocket 协议、命令运行和日志记录 |
| HTTP | `ensureBootstrapped`, `handle*Routes`, `bindTerminalWs` | `apps/inno-agent/src/server.ts`, `src/server/routes/` | lazy bootstrap、REST 域路由、SSE/WS 连接 |
| 前端 API | `apiFetch`, `streamSSE`, `streamChat`, `submitChatQuestion` | `apps/inno-agent/web/src/api/client.ts`, `api/chat.ts` | REST 和 SSE 的浏览器侧传输封装 |
| 前端状态 | `ChatStoreImpl`, `App`, `sessionsStore`, `workspaceStore` | `web/src/stores/chat-store.ts`, `web/src/react/App.tsx` | SSE 事件状态、会话/工作区初始化和 UI 编排 |

## 5. API、CLI、SDK 入口

### HTTP/API

服务入口是 `apps/inno-agent/src/server.ts`，默认端口 3000；前端开发 Vite 默认端口 5173，并将 `/api` 代理到后端。已从源码和后端 README 确认的入口组如下：

- `GET /health`、`GET /api/health`：健康检查。
- `POST /api/chat`：完整响应；`POST /api/chat/stream`：SSE 流式响应。
- `GET /api/chat/events/:id`、`GET /api/chat/status/:sessionId`、`POST /api/chat/:sessionId/:turnId/abort`、`POST /api/chat/question-response`：流恢复、状态、取消和问题卡片回答。
- `/api/sessions[/:id]`：会话列表、详情、归档、激活和主题等。
- `/api/workspaces[/:id]`、`/api/workspace/*`：工作区 CRUD、会话绑定、文件树/文件读写/上传。
- `/api/learner/*`：画像、目标、知识状态和学习者相关操作。
- `/api/wiki/*`、`POST /api/l2/raw/upload`：Wiki 页面、图谱、统计、原始材料上传。
- `/api/jobs[/:id]`、`/api/jobs/:id/run`、`/api/jobs/status`、`/api/jobs/runs`：定时任务及运行记录。
- `/api/skills/*`、`/api/skill-library/*`：技能列表、上传、内容编辑、启停、删除、重载和远程导入。
- `/api/presets`、`/api/presets/:id/open`、`/api/preset-library`：内置/远程 preset 工作区。
- `/api/channels/*`、`/api/bridge/*`：渠道配置、目标、bridge 回调和 WeChat iLink 操作。
- `/api/settings/*`、`/api/mcp`：配置、provider/model、memory、Simple Mode、theme、content hub 和 MCP。
- `/api/terminal/sessions*`、`/api/runs*`：Practice Lab HTTP 管理；`/api/terminal/sessions/:id/ws` 是 WebSocket 升级入口。

所有 API 路由都由 server 侧在实际 dispatch 前触发一次 lazy bootstrap；健康检查、静态页面和 SPA fallback 除外。

### CLI

- root `package.json`：`npm run start` 委托 `apps/inno-agent` workspace 的 `start`。
- `apps/inno-agent/package.json`：`"bin": { "inno": "dist/cli.js" }`；`npm run start` 执行 `node dist/cli.js`。
- `npm run server` 执行 `node dist/server.js`；`npm run sandbox`/`server:sandbox` 仅额外传入 `--sandbox`。
- `cli.ts` 支持的 Inno 运行时 flag：`--home`、`--config`、`--config-dir`、`--data`、`--skills`、`--workspace`、`--port`、`--sandbox`/`--no-sandbox`；其他参数转交 PI SDK。

### SDK/扩展入口

- 第三方 Agent 内核：`@earendil-works/pi-coding-agent` 的 `main()`、`ExtensionAPI`、`AgentSession`/`AgentSessionRuntime`。
- Provider/消息类型：`@earendil-works/pi-ai`。
- Web UI 相关 PI 组件：`@earendil-works/pi-web-ui`（通过前端依赖/legacy 组件使用）。
- Inno 给 PI 的主要扩展工厂：`createInnoExtension(configHolder, paths, channelRegistry?, deps?)`。
- Inno 自身没有单独暴露一个对外 HTTP SDK 包；浏览器 API 模块在 `apps/inno-agent/web/src/api/`，服务端复用 `pi-runner.ts` 的函数入口。

## 6. 技术栈和依赖

### 语言、运行时与构建

- Node.js ESM，工程要求 Node `>=20.6.0`；TypeScript 5.x，后端 target ES2022/Node16 resolution，前端 ESNext/bundler resolution。
- npm workspaces monorepo，root workspace 包括 backend、web 和 showcase。
- 后端 `tsc` 输出 `apps/inno-agent/dist/`；前端 `tsc` 类型检查后由 Vite 构建；Electron Builder 负责桌面包。
- 测试使用 Vitest；`vitest.config.ts` 覆盖后端 `src/**/*.test.ts` 与前端 `web/src/**/*.test.ts(x)`，TSX 组件测试使用 jsdom。

### 直接依赖（按源码 package.json）

- PI：`@earendil-works/pi-ai`、`@earendil-works/pi-coding-agent`、前端 `@earendil-works/pi-web-ui`。
- 服务与系统：Node `http`、`ws`、`undici`、`node-pty`、`source-map-support`、`pino`/`pino-caller`。
- 领域能力：`cron-parser`、`graphology`、`graphology-communities-louvain`、`@llamaindex/liteparse`、`yaml`、`typebox`。
- 渠道与外部能力：`@larksuiteoapi/node-sdk`、`@tavily/core`、`@juicesharp/rpiv-ask-user-question`。
- 可选扩展：`pi-mcp-adapter`、`pi-sandbox`、`pi-subagents`、`jiti`。
- Web：React 19/React DOM、Vite、Tailwind 4、Lit、CodeMirror、xterm、Cytoscape、React Markdown/Office 预览、i18next、lucide-react、qrcode.react、react-arborist、xlsx。
- Electron：`electron`、`electron-builder`。

### 系统/版本条件

- L3 的 `node:sqlite` 需要 Node 22.5+；低版本允许项目运行，但 L3 召回会降级关闭。
- PTY 使用 `node-pty` 原生模块；无预编译平台时构建需要 Python、make、g++。Electron 打包脚本 `scripts/after-pack.cjs` 负责修复 `spawn-helper` 权限。
- 技能 zip 上传/校验需要 `unzip`，workspace 下载打包需要 `zip`，PTY 默认 shell 需要 bash。
- Linux sandbox 需要 bubblewrap、socat、ripgrep；macOS 使用系统的 `sandbox-exec`。文档解析的 Office 路径依赖 headless LibreOffice。
- 这些依赖均为源码/项目文档中声明的条件；本次架构分析没有安装依赖，也没有运行服务。

## 7. 测试与可验证边界

- 测试配置位于 `vitest.config.ts`；后端至少包含 server smoke、chat/queue、L1、L2、L3、scheduler、channels、terminal、storage 等测试文件，前端包含 store/util/component 测试文件。
- `apps/inno-agent/src/server.smoke.test.ts` 通过临时 `--home`/workspace 子进程启动真实 server，覆盖 `/health`、设置脱敏、会话、jobs、channels、presets、learner、skills、wiki、workspaces、chat、terminal 和 JSON/413 错误路径；测试注释明确“不进行 LLM 调用”。
- `memory/learner/state-engine.test.ts` 实际验证讲解仅产生 exposure、证据权重差异、失败降低 mastery/stability、时间降低 retrievability、future event 过滤、紧凑快照和误区修复状态。
- L2 测试覆盖 Wiki 路径、维护/链接/图谱、结构化切分、BM25+图搜索、工具和 lint；L3 测试按 Node 版本条件覆盖 FTS bigram、coverage threshold、排除会话、去重、删除和 mtime 增量。
- 本次任务按要求仅做静态读取与文档落盘，没有安装依赖、启动服务或执行测试；因此本文不声称本次运行得到通过/失败的测试结果。

## 8. 架构判断

1. **薄适配层边界清楚。** Agent loop、SessionManager、工具生命周期和 provider 协议由 PI SDK 提供；Inno 的主要扩展点集中在 `createInnoExtension()` 与 `pi-runner.ts`，没有修改第三方内核。
2. **单用户架构是有意选择而非横向扩展架构。** 一个进程只有一个活动 AgentSession；session/channel/workspace 通过共享串行队列复用它。该设计简化状态一致性，但天然不提供多租户、认证、水平扩展或独立会话池。
3. **记忆层按生命周期分离，并且落到不同事实源。** L1 以学习事件和画像投影为主，L2 以 Wiki/source/index 为主，L3 以 session JSONL 的可检索副本为主；只有 L1 的结构化证据投影会判断学习状态，L2/L3 是知识和上下文来源。
4. **检索目前是词法/图结构方案，不是真 embedding 语义检索。** L2 使用 BM25 + 一跳图信号，L3 使用 FTS5 + coverage threshold；源码只为 embeddings 预留 schema，没有实际向量生成/查询 provider。
5. **后端是无框架的模块化 Node HTTP server。** `server.ts` 仍负责 bootstrap、静态服务、队列/终端接线，但业务路由已按域抽出并通过显式 ctx 注入依赖，避免引入 DI 框架。
6. **前端是渐进迁移的混合架构。** 新组件约定是 React，状态放在 framework-agnostic EventEmitter stores，API 集中在 `web/src/api/`；`web/src/components/` 仍保留 legacy Lit Web Components。
7. **持久化偏本地文件，数据库只服务检索索引。** 配置、画像、事件、任务、session、工作区 registry、渠道映射和 run log 主要是 JSON/JSONL/Markdown；SQLite 用于 L2/L3 索引，不是业务主数据库。
8. **安全边界围绕本地单用户工作区。** Agent 内置文件 mutation guard、server 文件路径安全检查、zip entry 校验和可选 OS sandbox；这不是面向恶意多租户的完整安全隔离，尤其 bridge 侧的部分用户过滤责任由 sidecar 承担。
9. **可观测性和容错是 best-effort。** fetch logger、pino 日志、PI event observer、自动 retry、SSE replay、问题持久化和 process fallback 能提升本地运维性，但 L2/L3 backfill、索引、OCR、主题生成等多处明确设计为失败不阻塞主对话。

## 9. 未确认项与阅读边界

以下事项没有在当前源码中得到完整运行时闭环证据，不能当成已实现能力：

- 未发现项目内 `AGENTS.md`；本次遵循的是实际存在的 `CLAUDE.md`、根 `README.md`、后端 README、`docs/SYSTEM_DEPENDENCIES.md`、`docs/learner-state-engine-design.md` 和测试/源码。
- `docs/learner-state-engine-design.md` 自身标注 Draft，并明确前端状态面板、完整历史投影迁移、前置关系编辑和真实数据校准仍未全部实现；设计中的新增 API 不自动代表当前存在。
- L2/L3 都依赖 `node:sqlite` 的可用性，但 L2 的 substring fallback、L3 的禁用行为和 Node 版本差异需要在目标运行环境单独验证；本次未运行服务。
- `embeddings` 表在 L3 schema 中只是未来扩展位，未确认有 embedding 模型、向量写入或 cosine 查询实现。
- provider 的真实地址、key、可用模型和最终调用协议来自运行时 `config.json`，源码仅规定 `openai-completions`/`anthropic-messages` 等兼容字段，不能从仓库静态确定某次部署的真实 provider。
- Electron 当前硬编码本地端口 3000，并将默认 `INNO_WORKSPACE_DIR` 设为用户 `Documents`；与命令行可传的运行时路径之间的最终部署策略需按平台再验证。
- 根 README/CLAUDE 中的测试数量、server 行数等统计可能随源码变动；本文只引用当前可读到的测试类型和行为，不把历史统计当作本次执行结果。

## 10. 本次静态取证文件清单

已实际读取并据此编写本文的主要文件：

- `README.md`
- `CLAUDE.md`（未发现 `AGENTS.md`）
- `package.json`、`apps/inno-agent/package.json`、`apps/inno-agent/web/package.json`、`vitest.config.ts`
- `docs/SYSTEM_DEPENDENCIES.md`、`docs/learner-state-engine-design.md`、`docs/quality-remediation-plan.md`
- `apps/inno-agent/src/cli.ts`、`runtime.ts`、`config.ts`、`server.ts`
- `apps/inno-agent/src/agent/inno-extension.ts`、`agent/pi-runner.ts`
- `apps/inno-agent/src/memory/learner/{types,evidence,state-engine,profile-store}.ts`
- `apps/inno-agent/src/memory/l2/{types,l2-memory,l2-search}.ts`
- `apps/inno-agent/src/memory/l3/{sqlite-store,indexer,recall}.ts`
- `apps/inno-agent/src/scheduler/{types,job-store,cron-scheduler}.ts`
- `apps/inno-agent/src/channels/{channel,personal-dispatcher}.ts`
- `apps/inno-agent/src/workspace/workspace-registry.ts`
- `apps/inno-agent/src/terminal/{terminal-types,terminal-session-manager}.ts`
- `apps/inno-agent/src/storage/file-store.ts`
- `apps/inno-agent/src/server.smoke.test.ts`、`memory/learner/state-engine.test.ts`
- `apps/inno-agent/web/src/main.tsx`、`web/src/react/App.tsx`、`web/src/api/{client,chat}.ts`、`web/src/types/chat.ts`、`web/src/stores/chat-store.ts`
- `electron/main.js`

本文件已吸收此前 `细探-Inno-Agent.md` 的源码分析结论；后续只维护本文件，旧细探笔记不再作为独立事实源。

---

## 11. 后续：通用底座映射与裁决（源码事实 → 支持库/模块库/运行核心/网关）

### 11.1 当前核对边界、证据等级与旧细探收口

当前核对只把当前源码中已经存在的能力映射为通用底座候选，不把 Inno 的产品策略改写成平台事实，也不声称 Inno 已经接入系统工程平台。源码证据主要来自 `apps/inno-agent/src/agent/pi-runner.ts`、`agent/inno-extension.ts`、`server.ts`、`chat/stream-registry.ts`、`scheduler/*`、`workspace/*`、`terminal/*`、`storage/file-store.ts`、`channels/*`、`config.ts`、`runtime.ts` 和 `electron/main.js`。

目标项目第一次 `project_context` 返回的项目是 `~/Documents/Agent/PHP/华世王镞_v3`，不是本项目；随后 `development_start` 以本项目路径开工被 MCP 以 `MCP_TARGET_PROJECT_MISMATCH` 拒绝。`codegraph_explore` 已按本项目绝对路径调用，但明确返回“未建立 `.codegraph/`，不可查询”；因此当前核对没有把错误项目代码图或不存在的代码图当证据，以下定位均来自目标目录现场源码读取。目标目录及其已搜索的父级范围内没有找到独立的 `细探-*.md` 文件；现有文档末尾关于 `细探-Inno-Agent.md` 的吸收声明保留，但独立旧笔记不能再次核验。

### 11.2 四层归属原则

| 底座层 | 应承载的通用能力 | Inno 当前实现/候选落点 | 当前核对裁决 |
|---|---|---|---|
| **支持库** | 文件/JSON/JSONL 原子写入、尾读与轮转；路径安全；HTTP 请求超时；SQLite/FTS 索引；PTY/子进程封装；模型/工具/渠道的稳定数据类型 | `storage/file-store.ts`、`utils/path-safety.ts`、`memory/l2/l2-index-store.ts`、`memory/l3/sqlite-store.ts`、`terminal/local-pty-backend.ts` | **吸收为原子能力候选**。这些能力不应知道 learner、Wiki、scheduler 或 Inno prompt 策略；当前代码仍是项目内支持代码，未迁移。 |
| **模块库** | 领域流程编排和结果转换：会话流、L1/L2/L3 记忆、定时作业、渠道消息、Practice Lab、内容 hub | `agent/inno-extension.ts`、`memory/*`、`scheduler/job-runner.ts`、`channels/personal-dispatcher.ts`、`terminal/terminal-session-manager.ts` | **吸收为模块候选**。模块可组合支持库，但不应各自直连第三方或复制队列、任务、存储、重试内核。 |
| **运行核心** | 进程级运行上下文、能力/模型注册表生命周期、任务队列与取消、会话/句柄、资源预算、超时、崩溃清理、统一结果/证据 | `pi-runner.ts` 的进程级 `_runtime`/`_queue`、`stream-registry.ts`、`process-fallback.ts`、PTY 生命周期散落在 manager/backend | **优先升级运行核心候选**。当前串行队列和流状态是 Inno 局部实现，不能被多个模块各复制一份；但尚无平台统一运行核心接入证据。 |
| **网关** | 外部调用唯一入口、路由/鉴权/限流、协议转换、SSE/WS、渠道 webhook/sidecar、统一错误与观测 | `server.ts` 的 Node HTTP 路由、SSE/WS；`ChannelRegistry`/`PersonalChannelDispatcher`；`BridgeChannel` | **映射为网关适配候选**。Inno 的 `server.ts` 是本地应用网关，不等于系统工程平台统一网关；Feishu/WeChat/QQ、浏览器、CLI 必须最终汇入同一能力调用链。 |

归属硬规则：一个能力 id 只有一个契约 owner、一个注册入口和一条调用链；一个模块只编排一个领域流程；provider、渠道和模型差异留在适配层/提供者；状态、事件、索引、制品和证据分别指定唯一写 owner。当前 Inno 尚未显式形成平台能力 id 注册表，PI 的 `registerTool` 和 `modelRegistry.registerProvider` 只能作为源码事实，不能直接宣称为平台注册体系。

### 11.3 能力注册、任务/会话、工具、模型、存储、线程/进程和外部服务映射

| 对象 | 当前源码事实 | 通用底座归属 | Agent 业务策略与基础能力边界 |
|---|---|---|---|
| **能力注册** | `createInnoExtension()` 批量调用 `pi.registerTool()`；工具来自 learner/scheduler/channel/L2/L3/document/OCR/Tavily/practice；可选 MCP、subagents、ask_user_question 在启动时装配。 | 注册描述、参数 schema、版本/能力 id、重复检查 → **支持库/能力契约 + 运行核心注册表**；按配置装配 → **模块库**；对外调用 → **网关**。 | “有哪些工具、何时启用 L1/L2/L3、Simple Mode 是否关闭记忆、是否注入 onboarding”是 Inno 策略；schema 校验、注册幂等、缺实现、错误形状和生命周期是通用底座。 |
| **任务** | scheduler 的 `ScheduledJob` 存 `jobs.json`，`CronScheduler` 每 60 秒 tick，`running` Set 防同 job 重叠；`executeJob()` 通过 `runPromptSerialized()` 执行并写 `runs.jsonl`。Practice Lab 另有 terminal run。 | 任务状态机、任务 id/幂等、排队、取消/超时、重试、租约、运行记录 → **运行核心**；cron/提醒/学习任务编排 → **模块库**；REST/工具触发 → **网关**。 | “提醒学习者”、prompt 内容、推送哪个渠道是业务策略；任务身份、状态迁移、资源释放、重复触发和失败证据是通用能力。当前 scheduler 无独立取消/硬超时契约，只有 prompt/provider 内部能力，标 **待核**。 |
| **会话** | PI `SessionManager` 管理 JSONL；Inno 进程只有一个活动 `AgentSession`，所有 prompt、切换、新建共用 `_queue`；channel chatId→sessionId 写 `chat-sessions.json`，session→workspace 写 `workspaces.json`。 | 会话句柄、所有者、活动 turn、事件回放、并发租约、取消、恢复、版本和清理 → **运行核心**；channel/workspace 绑定策略 → **模块库**；HTTP/SSE/CLI/IM 接入 → **网关**。 | “个人学习者、每渠道独立会话、消息来源标签、自动 topic”是业务策略；会话一致性、turn 唯一性、断线重连和快照是基础能力。当前 session 文件主要由 PI SDK持久化，Inno 的 `StreamRegistry` 只在进程内保存流状态。 |
| **工具** | PI 内置 bash/read/edit/write 与 Inno 自定义工具共用 `ExtensionAPI`；`tool_call` 拦截 workspace 越界和 `open/xdg-open`，`tool_result` 集中记录错误。 | 工具契约/schema、调用监督、超时/取消、输出上限、权限、审计、统一结果 → **支持库 + 运行核心**；工具组合和领域语义 → **模块库**；工具暴露 → **网关**。 | `record_learning_evidence`、`l2_archive`、`run_scheduled_job`、`ocr_image`、`web_search` 的语义是 Agent 业务；路径边界、凭证脱敏、错误捕获和进程隔离是通用基础。 |
| **模型/provider** | `config.ts` 规范化 provider/model；`initSession()` 和 `refreshConfiguredProviders()` 把 provider/model 注册进 PI `modelRegistry`；`switchModel()` 设置活动模型并由 `model_select` 持久化默认值；默认 provider 超时 10 分钟，Undici body timeout 15 分钟。 | provider/model 元数据、能力声明、凭证引用、路由、超时、重试、熔断、健康和资源预算 → **支持库/运行核心**；模型选择/图片降级/OCR fallback → **模块库**；外部 HTTP 出口 → **网关/外部提供者适配层**。 | “默认模型、是否支持图片、文本模型转 OCR、provider 选择”是 Agent 策略；连接、认证、超时、重试、错误码和密钥不落日志是通用能力。当前真实 provider 由 `config.json` 决定，仓库不能证明某次部署实际可用。 |
| **存储** | 配置/画像/事件/任务/session/workspace/channel/run 主要 JSON/JSONL/Markdown；`writeJson`/`writeJsonl` 用 tmp+rename；JSONL 支持尾读、坏行跳过和部分轮转；L2/L3 SQLite 仅索引。 | 原子文件、追加日志、锁/并发、备份恢复、损坏检测、SQLite 连接/事务/迁移/索引 → **支持库 + 运行核心**；L1/L2/L3 的事实模型和投影 → **模块库**。 | “L1 事件如何投影掌握度、L2 Wiki frontmatter、L3 召回阈值”是业务/领域策略；原子提交、主键/幂等、恢复与残留审计是通用基础。当前没有统一权威数据库；部分 JSON 读改写仍由各模块自行组织。 |
| **线程/进程** | Node 主进程内 Promise 串行队列、cron `setInterval`、后台 `void backfill()`；PTY 通过 `node-pty` 启动 shell；Electron `spawn()` 独立 server 子进程；process fallback 对 uncaught exception/unhandled rejection 记录后最多等待 3 秒退出。 | 线程/进程组、句柄、健康、kill/回收、超时、崩溃重启/恢复、资源预算 → **运行核心**；具体 PTY 交互和终端业务 → **模块库**；Electron/HTTP 控制入口 → **网关/宿主适配**。 | “Practice Lab 命令、workspace cwd、sentinel 解析退出码”是业务模块；进程组隔离、API key 环境清洗、SIGTERM/SIGKILL、孤儿进程检查是通用基础。当前 PTY 是真实子进程，但未发现独立进程组 killpg、统一硬超时或崩溃恢复闭环。 |
| **外部服务** | PI provider API；Feishu SDK；WeChat iLink `https://ilinkai.weixin.qq.com`；QQ/bridge WeChat sidecar `/reply`/`/push`/`/health`；Tavily；Baidu PaddleOCR-VL 的 submit→poll→result；GitHub/bundle content hub；可选 MCP。 | URL/凭证/HTTP 超时/重试/限流/熔断/协议解析/脱敏和健康检查 → **支持库/提供者适配层**；多服务业务流程 → **模块库**；统一出站路由和 webhook → **网关**。 | “消息来源标签、默认 push target、OCR 作为视觉失败 fallback、联网搜索结果 Markdown”是业务策略；外部连接池/超时/取消/响应限制和失败分类是通用基础。当前只有部分调用设置了 `AbortSignal.timeout`，不能推断全局统一出站治理。 |

### 11.4 唯一链路：现状调用链与平台化目标链

#### 现状一：Web/CLI 对话与模型工具链

```text
Web REST / SSE 或 CLI
  → server.ts route / PI main()
  → runPromptInSession() / runPromptSerialized()
  → pi-runner.enqueue()（单进程共享 Promise queue）
  → switchToSession()
  → PI AgentSession.prompt()
  → before_agent_start（INNO_SYSTEM_PROMPT + L1 + workspace + L3 + 最近 run）
  → PI model/provider
  → PI tool loop + inno-extension 的 tool_call/tool_result
  → L1/L2/L3/Job/Workspace/RunRecord 写入
  → AgentSession event → StreamRegistry/SSE 或 CLI/TUI
```

这是当前唯一的 Inno 对话主链；`completePromptOnce()` 是明确绕过该队列的 metadata side-channel，故不能被误并入会改变阻塞语义。目标平台链应收敛为：

```text
入口适配层（Web/CLI/渠道）
  → 统一网关请求/鉴权/限流/协议转换
  → 模块库会话/任务流程
  → 运行核心唯一会话与任务调用器
  → 能力注册表按能力 id 选择实现
  → 支持库原子能力 / provider 受管进程
  → 外部 API、系统 API 或存储
  → 统一结果、事件、证据、资源释放
```

#### 现状二：个人渠道链

```text
Feishu/WeChat 原生或 QQ/WeChat Bridge
  → ChannelRegistry（按 name 注册）
  → PersonalChannelDispatcher（dedupe、chatId→sessionId、默认 target）
  → createNewSession()/runPromptInSession()
  → pi-runner 唯一队列 → PI AgentSession
  → StreamingReplyHandle 或 channel.reply()
  → ChannelRunLog / chat-sessions.json
```

`BridgeChannel` 对 sidecar 的 `reply/push` 设 30 秒超时，健康检查设 5 秒；WeChat iLink 长轮询 30 秒、发送/普通 POST 15 秒，令牌和 `updates_buf` 写 0600 文件。渠道的重试只在 dispatcher 回复失败时最多再试一次；这不是统一重试器。

#### 现状三：scheduler 链

```text
CronScheduler.start() → 5 秒首次 tick / 60 秒轮询
  → isCronDue() + running Set
  → executeJob()
  → push_reminder 直接生成通知，其他任务 → runPromptSerialized()
  → JobStore.appendRun()/mutate()
  → 可选 ChannelRegistry.get().push()
```

该链与对话链共享同一 Agent 队列，但 `executeJob()` 自己维护 job 状态和推送失败语义。平台化时只能保留一个通用任务监督器，scheduler 只保留 cron 解释和提醒业务策略。

#### 现状四：Practice Lab 链

```text
HTTP/WS terminal route
  → TerminalSessionManager.create()
  → WorkspaceRegistry.resolveWorkspaceDir()
  → LocalPtyBackend.create() → node-pty shell
  → startRun() 写 sentinel + RunRecordStore.start()
  → processOutput()/recordOutput()
  → sentinel 得到 exitCode
  → RunRecordStore.finish()（JSON + .log）
  → WS 客户端与 before_agent_start 的最近 run 上下文
```

创建同一 Inno session 的新终端会先 `close()` 旧 PTY；PTY 自行退出会从两个内存 Map 清理，但当前源码没有发现统一进程组/孤儿子进程扫描和崩溃后重建 run 的平台闭环。

### 11.5 业务策略与通用基础能力的裁决表

| 只属于 Inno Agent 业务策略，不下沉为公共事实 | 应下沉为通用基础能力，不由业务模块复制 |
|---|---|
| L1 learner profile 的事件类型、证据权重、mastery/stability/retrievability 投影、稳定掌握门槛 | 能力契约、能力 id、注册/注销/版本兼容、缺实现和重复注册错误 |
| L2 Wiki 页面/frontmatter、前置关系、BM25+一跳图手工排序 | 文件原子写入、追加日志、轮转、坏数据隔离、锁与恢复 |
| L3 “仅供参考”召回、coverage threshold、排除当前会话 | 会话句柄、turn 状态、事件序号、重放、断线订阅、TTL 清理 |
| `Simple Mode` 关闭三层记忆、onboarding、workspace `agent.md`/`.skills` 注入 | 任务排队、幂等、取消、超时、重试、租约、结果/证据统一形状 |
| `push_reminder`、学习 prompt、默认频道推送、来源渠道标签、自动 topic | 工具 schema/权限/输出上限、调用监督、调用者取消、错误留痕 |
| 图片失败后的 OCR 选择、Tavily 搜索结果格式、preset workspace 内容 | provider/model 注册、认证引用、能力声明、健康、超时/重试/熔断 |
| Practice Lab 的 sentinel 展示、运行记录面板、workspace 绑定策略 | 线程/进程组、PTY/子进程句柄、SIGTERM→SIGKILL、残留检测、崩溃清理 |
| 个人渠道的消息解析、卡片展示、IM 会话绑定 | HTTP/WebSocket/SSE、出站超时、限流、凭证脱敏、协议错误归一化 |

### 11.6 资源生命周期与 owner 契约

| 资源 | 创建/持有者 | 正常完成 | 业务失败 | 超时/主动取消 | 宿主/子进程崩溃 | 现场验证要求 |
|---|---|---|---|---|---|---|
| Provider/model 注册表 | `initSession()`/`refreshConfiguredProviders()`；PI runtime 持有 | 注册完成并可 `find()`；切换后保存默认模型 | 缺 provider/model 抛错；配置保存失败保留运行态 | 不应因队列等待；请求由 provider/PI timeout 终止 | runtime 重建后重新注册；配置文件原子写避免半文件 | 列出注册 id、默认模型、删除 provider 后旧模型不再可见 |
| AgentSession 与 prompt turn | `SessionManager`/`pi-runner`；queue slot 持有 | Agent event 完成，session JSONL 有可读 assistant 消息 | 事件错误/模型错误，恢复旧 leaf；stream 终态 `error` | `AbortSignal` 进入队列前立即拒绝；运行中 `abortPromptForTurnToken` 调 PI abort；首次未回答 turn 写 aborted 占位 | process fallback 记录 fatal、调用 onFatal 后退出；不在不可信状态继续服务 | active queue/turn 归零；session 文件可重开；无 ghost session switch |
| StreamRegistry 流、订阅和历史 | `createTurn()` 创建；registry 持有 | `finishTurn(done)` 发布 terminal，清 subscribers | `finishTurn(error)`；subscriber 抛错即移除 | `requestCancel()` 只置标记，实际取消仍需 caller/runner 配合；TTL 默认 5 分钟清终态 | 仅内存状态丢失；session 文件可能已持久化，需客户端重连/状态重建 | 终态唯一、eventId 单调、after replay 无 gap、过期流清零 |
| Tool call / tool result | PI agent 持有；extension 监听 | `tool_end` 完成并将结果交回 agent | `tool_result.isError` 记录；路径/命令策略可阻断 | 自定义工具的 signal 是否被下游采用需逐工具验证；OCR 使用总 5 分钟 abort | agent 进程退出，工具未完成状态不可从 StreamRegistry 恢复 | schema 拒绝非法输入；输出上限；取消后无继续写入/外部副作用 |
| JSON/JSONL/Markdown | 各 store 创建；`file-store` 写入 | tmp+rename 或 append；配置 0600 | JSON 解析坏文件回默认；JSONL 坏行跳过并记录 warn | append/rename 不接受取消；轮转失败不丢当前记录 | 原子 rename 避免截断，但 append 中断可能留下尾部坏行 | 重启解析；tmp 无残留；敏感文件 mode=0600；归档可读 |
| L2/L3 SQLite 索引 | L2/L3 singleton/store；索引模块持有 | 建表、索引、FTS 查询 | L2 SQLite 不可用回退 substring；L3 不可用则禁用 | backfill 是 `void` 后台任务，未见统一取消 token | 进程死后索引可从 raw/session JSONL backfill；需要验证 WAL/锁残留 | 删除/重建幂等；进程重启可 backfill；索引与 canonical 文件计数一致 |
| Cron job / run record | `JobStore` 持有 jobs.json/runs.jsonl；scheduler 持有 running Set | `appendRun(success)` + `mutate` 更新计数/nextRun | push 缺 target、channel 未注册或 prompt 异常写 error；one-shot 禁用 | 当前没有统一 job timeout/cancel；停止 scheduler 只清 interval，不主动取消已执行 prompt | jobs 记录最后状态，内存 running Set 丢失；重启可能重新判 due | 并发同 job 不重复；计数无丢失；错误/成功与 runs 一致；无卡住 running |
| Workspace 与 session 映射 | `WorkspaceRegistry`；registry.json/workspaces.json | bind/unbind、路径在根目录内 | 无 workspace 返回 null；删除 workspace 可解除绑定 | 删除不自动删除 session；tmp 共享且不清理 | registry 原子写；进程死后映射可恢复 | `realpath/relative` 无越界；删除/重启映射一致；tmp 残留策略明确 |
| PTY、shell、run log | `LocalPtyBackend`/`TerminalSessionManager`；node-pty 持有 | sentinel 捕获 exit code，`RunRecordStore.finish` 写终态 | 非 0 exit 仍完成并记录 exitCode；写 log 失败 best-effort | 当前没有 run 硬超时；close 调 `pty.kill()`，不保证子孙进程组 | PTY onExit 清两个 Map；宿主 crash 后没有重建/回收证明 | 子进程/端口/句柄无残留；exitCode/signal 与日志一致；强杀后可重启 |
| 外部 HTTP/渠道/MCP/OCR | 各 provider/channel/tool 自持 fetch/SDK 会话 | 响应解析、结果转换、状态推进 | 非 2xx/JSON 缺字段分类为失败；dispatcher safeReply 最多一次重试 | Bridge 30s、health 5s、WeChat 15/60s、OCR 单请求 60s/总 5min、Tavily 60s | 未发现统一断路器/恢复 supervisor；WeChat auth -14 清 token，其他服务多返回错误 | 真实服务/隔离 mock 分层测试；超时后连接/定时器释放；凭证不出日志 |

资源责任原则：创建者必须声明持有者；转移必须显式；正常、失败、取消/超时、崩溃四条终态均要有释放和证据。当前源码中的 `void backfill()`、`running Set`、PTY map、外部 fetch 和 process fallback 仍存在“运行态丢失后由重启恢复”的边界，不能标为完整生命周期实现。

### 11.7 失败、超时、取消、崩溃矩阵

| 场景 | 当前可见行为 | 底座要求 | 当前状态 |
|---|---|---|---|
| 配置缺 provider/model、坏 JSON | `normalizeConfig()`/`loadConfig()` 抛错；JSON store 读坏文件回默认 | 启动前契约校验、稳定错误码、敏感配置原子恢复 | **部分实现**：有边界但无统一错误契约 |
| 队列繁忙、请求先取消 | `enqueue()` 的 signal 触发即拒绝，slot 到达前 `guarded()` 不执行 | 任务/turn 取消必须幂等并可观测，不产生 ghost switch/prompt | **已实现局部**：运行中取消另依赖 PI abort |
| LLM/provider 超时或错误 | PI retry；默认 provider 10 分钟，undici body 15 分钟；流错误转 error；图片 413/能力错误分级 fallback | 单一 timeout budget、取消传播、重试预算、错误/证据统一 | **部分实现**：多处独立 timeout，预算未统一 |
| Tool 参数/权限失败 | TypeBox/PI schema；workspace 越界和 open 命令在 `tool_call` 阻断；tool_result 记录错误 | schema、权限、调用者、输出上限和副作用回滚都应统一 | **部分实现**：路径边界有，逐工具取消/幂等未齐 |
| SQLite 不可用/索引失败 | L2 substring fallback；L3 禁用；backfill/turn_end 失败不阻塞主对话 | canonical source 不得丢、后台任务可重试、索引版本/差异可诊断 | **部分实现**：降级有，重试/残留证据待核 |
| Channel/sidecar/外部 API 断线 | 超时或非 2xx 抛错；dispatcher safeReply 再试一次；WeChat -14 清凭证 | 出站统一重试/熔断/限流/健康与死信；业务不重复发送 | **部分实现**：局部超时/重试，未形成单一 owner |
| Cron 重复触发或 prompt 失败 | scheduler `running` 防同实例重叠；JobStore per-job chain 防计数覆盖；异常写 error run | 跨进程幂等、租约、取消、重启恢复和唯一 run id | **待核**：只证明单进程内存防重叠 |
| PTY 非零退出/关闭 | sentinel 记录 exitCode；close kill；onExit 删除 map | 独立进程组、硬超时、SIGTERM→SIGKILL、stdout/stderr 上限和残留审计 | **部分实现**：能记录退出，缺进程组/崩溃治理证据 |
| uncaught exception/unhandled rejection | fatal 日志，onFatal 最多 3 秒后 `process.exit(1)`；Electron 感知 server 非零退出 | 宿主先冻结接收、关闭 HTTP/WS/PTY、持久化意图、回收子孙进程，再退出/重启 | **部分实现**：退出兜底有，完整关闭回调/恢复闭环待核 |
| 进程崩溃后恢复 | PI/session/JSON 文件可在重启后读取，index 可 backfill；内存流、queue、running Set 丢失 | 事务/会话/任务/句柄恢复、僵尸资源清理、重复执行防护 | **待核**：源码有重建路径，未见全链路强杀验证 |

### 11.8 L0-L4 验证分层与本项目验收契约

| 等级 | 目标 | Inno 应验证的内容 | 当前核对证据/命令 | 判定 |
|---|---|---|---|---|
| **L0 静态契约** | 证明目录、公开符号、注册点和依赖边界存在 | `createInnoExtension` 注册工具；`modelRegistry` 注册/注销；`pi-runner` 唯一 queue；四类链路和文件 owner；无第二份任务/队列/网关内核 | 当前核对源码读取；代码图明确不可用；目标 `ARCHITECTURE.md` 追加本章 | **已完成静态整理**，不等于运行通过 |
| **L1 纯单元/性质** | 不启动外部服务，验证状态机和纯逻辑 | queue 取消不执行、StreamRegistry 终态/事件序号/replay/TTL、路径 containment、JSONL 坏行/轮转、cron due、JobStore mutate、sentinel 退出码 | 现有 Vitest 文件存在，但当前核对未运行 | **未验证** |
| **L2 本地组件集成** | 临时目录 + 本地 SQLite/PTY/mock provider | lazy bootstrap、配置热更新、session/workspace 绑定、L1/L2/L3 读写、后台索引、JobStore→runner、terminal run record | 应运行 `npm test -- --run` 或项目等价的 Vitest 入口（当前核对按任务边界不执行） | **未验证** |
| **L3 真实进程/HTTP/WS** | 跨进程与协议边界真实执行 | `npm run build`；server `/health`、chat/SSE abort/replay、session switch、terminal WS/PTY、Electron spawn→health→非零退出清理；隔离 sidecar mock | 应运行 `npm run build`、`server.smoke.test.ts` 及独立 WS/PTY smoke（当前核对未执行） | **未验证** |
| **L4 外部与灾难** | 外部依赖、长耗时和崩溃/超时/取消真实闭环 | 隔离 provider/OCR/Tavily/Feishu/WeChat/bridge；断线/非 2xx/凭证失效；kill server/PTY/索引 backfill；重启恢复、无 orphan process、无临时/锁/订阅残留 | 需要显式外部凭证或隔离服务；当前核对未启动服务、未安装依赖、未调用外部服务 | **未验证；不能假绿** |

验收门槛：L0 只能证明“有代码和唯一链路描述”；L1-L3 至少要有真实命令及退出码；L4 需要外部依赖/强杀证据。任何“源码存在”“测试文件存在”“历史测试统计”“子代理回信”都不能替代真实执行。缺少某层证据时，只能写“待验证/部分实现”。

### 11.9 后续复用/升级/新建/隔离裁决

| 能力族 | 裁决 | 原因与落点 |
|---|---|---|
| 原子文件/JSONL、路径安全、SQLite/FTS、PTY/HTTP 基础包装 | **复用/升级支持库** | 提取稳定契约和生命周期，禁止 L1/L2/L3/terminal 各自复制；provider-specific 依赖留在适配层。 |
| 能力/工具/模型注册与统一调用 | **建立运行核心唯一入口** | 当前 PI 注册点分散于 extension/runtime；先建立能力 id、参数/返回/错误/版本 owner，再由 Inno 适配层绑定。 |
| 会话、turn、事件回放、流订阅、队列取消 | **升级运行核心** | `_queue`、`StreamRegistry` 已是同类公共问题；合并前必须冻结单一 owner，保留 Inno 的 session/channel 策略在模块层。 |
| Cron、push reminder、L1/L2/L3、Practice Lab、渠道 dispatcher | **保留为模块库** | 这些流程包含 Inno 学习产品语义；只调用公共任务、会话、存储、外部服务能力。 |
| Feishu/WeChat/QQ/OCR/Tavily/content hub/MCP | **提供者适配 + 网关接入** | 统一凭证、健康、超时、重试和错误映射；不让每个业务模块直连第三方。 |
| Inno `server.ts` 的本地 REST/SSE/WS、Electron server child process | **隔离为项目网关适配** | 当前是单用户本地应用入口；不能未经契约验证替换系统统一网关，也不能复制第二套平台任务/注册/存储核心。 |
| PI SDK `AgentSession`、`SessionManager`、`ExtensionAPI` | **隔离并适配** | 第三方内核是外部运行时 owner；Inno 只做版本/配置/策略适配，不修改或把 PI 内部对象穿透到底座契约。 |
| 真实崩溃恢复、跨进程任务租约、统一出站治理 | **待核/新建前先登记需求** | 当前源码只给局部 best-effort 和重启重建线索，尚无 L3/L4 证据，禁止据此直接改生产底座。 |

### 11.10 后续工作包与后续验证顺序

1. **契约冻结**：为能力注册、工具调用、模型选择、任务、会话/turn、外部调用分别写请求/返回/错误/超时/取消/幂等/资源 owner；先登记需求并搜索现有能力，不直接创建第二套中心。
2. **单链路试点**：选择 `Web → chat stream → AgentSession → provider → tool → session JSONL/SSE` 一条链，定义唯一能力 id、模块公开入口和网关入口；其余渠道先只做适配，不并行重构。
3. **资源与失败试点**：用临时目录、隔离端口和可控 mock provider 验证正常/业务失败/取消超时/kill 崩溃四终态；重点检查 queue slot、subscriber、timer、PTY、子进程和 `.tmp` 残留。
4. **任务/会话扩展**：在主链验收后再接 scheduler 和 channel dispatcher；验证同一 job 跨 cron/API/工具触发不重复，channel messageId 幂等且 session 映射恢复。
5. **外部服务 L4**：只使用隔离账号/服务和明确凭证，验证 Feishu/WeChat/bridge/OCR/Tavily 的断线、认证失效、超时、重试、死信与脱敏；不得触碰真实业务库或无关账号。
6. **收口规则**：每个复用/升级结论必须回填能力 owner、调用链、资源责任、失败证据和 L0-L4 结果；没有真实退出码的项目事实只能停留在“静态存在/待验证”。

当前核对的底座输入结论为：**吸收**（支持库/模块库边界和四条现状唯一链路）、**升级候选**（能力/模型注册、会话/任务监督、资源生命周期和统一网关适配）、**待核**（跨进程幂等、强杀恢复、统一外部治理）；未将任何未验证设计写成已实现功能。
 # Inno-Agent 架构取证
