```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ 用户入口                                                                     │
│ Electron 桌面端 / LAN·Mobile PWA / Bridge 外部平台 / server-first CLI       │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │ HTTP REST / WebSocket / CLI client
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ server/                                                                     │
│ Hono HTTP + @hono/node-ws；CORS、transport context、Bearer/loopback/device │
│ auth、route-security、WS ticket；open-root + full-root 组合路由              │
└───────────────┬───────────────────────────────┬──────────────────────────────┘
                │ REST/WS handler               │ event / message
                ▼                               ▼
┌─────────────────────────────┐       ┌────────────────────────────────────────┐
│ hub/                        │       │ shared contracts                       │
│ EventBus、ChannelRouter、   │◄─────►│ session refs、model refs、errors、     │
│ DmRouter、Scheduler、       │       │ workspace scope、tool/resource types   │
│ GuestHandler                │       └────────────────────────────────────────┘
└──────────────┬──────────────┘
               │ 调度、频道/DM、Heartbeat/Cron、事件广播
               ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ core/ HanaEngine（Thin Facade）                                              │
│ AgentManager · SessionCoordinator · ModelManager · Config/PreferencesManager │
│ SkillManager · PluginManager · ChannelManager · BridgeSessionManager · MCP  │
│ Resource/SessionFile/Media/Computer-use/Speech/Task/Workflow 等服务          │
└───────┬──────────────────────┬────────────────────────┬───────────────────────┘
        │                      │                        │
        ▼                      ▼                        ▼
┌───────────────┐      ┌──────────────────┐     ┌──────────────────────────────┐
│ Agent runtime │      │ Session runtime  │     │ 能力与执行安全                │
│ personality、 │      │ Pi SDK session、 │     │ capability-policy → principal │
│ tools、memory │      │ turn/compaction、│     │ / grants → execution boundary│
│、desk、cron   │      │ branch、stream   │     │ → remote write lease / audit │
└──────┬────────┘      └────────┬─────────┘     └──────────────┬───────────────┘
       │                        │                              │
       ▼                        ▼                              ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ 持久化与资源边界                                                             │
│ HANA_HOME：agents/*/config.yaml、memory/facts.db、sessions/*.jsonl、          │
│ session-manifest.db、*.jsonl.files.json、preferences.json、auth.json、       │
│ models.json、providers/、security/*、plugin-data/*、ephemeral/*              │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │ model/provider request + structured events
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ Pi SDK / provider compatibility / media adapters                              │
│ @earendil-works/pi-*、ProviderRegistry、ExecutionRouter、LLM client、媒体层   │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │ stream events / content blocks / resources
                                   └──────────────► server WS/REST ◄── UI/CLI/Bridge
```

# HanaAgent 架构文档

## 项目定位

HanaAgent 是一个以 Electron 桌面应用为主、同时提供独立 Node.js Server、LAN/Mobile PWA、外部平台 Bridge 和 server-first CLI 的个人 AI Agent。项目 README 将其定位为“有记忆、有灵魂的私人 AI 助理”，目标用户不局限于 coder；能力覆盖多 Agent、人格与记忆、文件/网页/终端/电脑操作、技能、插件、频道协作、定时任务和受控资源访问（依据 `README.md` 第 20–62 行）。

仓库包名为 `hanako`，版本 `0.447.4`，许可证 Apache-2.0；`package.json` 将运行时约束为 Node `>=24.12.0 <25`，包类型为 ESM，工作区为 `packages/*`。当前架构不是单一库，而是“Electron 壳 + Hono 服务进程 + core 引擎 + hub 调度 + Pi SDK + React 前端 + 插件/SDK”的组合式应用。

## 真实目录/分层与职责

以下目录来自项目根的实际磁盘结构；README 的架构摘要（`README.md:89-111`）与源码中的组合根相互印证。不存在项目级 `AGENTS.md`；项目根也未发现既有 `ARCHITECTURE.md`。

- `core/`：领域核心与组合内的服务。`engine.ts` 是持有各 Manager 的薄 facade；`agent.ts`/`agent-manager.ts` 负责 Agent 实例与生命周期；`session-coordinator.ts` 负责会话生命周期；`model-manager.ts`、`provider-registry.ts` 负责模型和 Provider；`preferences-manager.ts`、`config-coordinator.ts` 管理全局与运行配置；`skill-manager.ts`、`plugin-manager.ts` 管理技能和插件；另含 MCP、媒体、视觉、语音识别、computer-use、频道、Bridge session、工作流、任务、资源、安全、迁移等子域。
- `core/session-manifest/`：会话稳定身份层。`store.ts` 以 SQLite 保存 manifest、locator history、能力快照、executor metadata 等；`resolver.ts` 支持按 `sessionId` 或旧 locator 解析；`ref.ts` 建立 JSONL 路径到稳定 session identity 的引用。
- `lib/`：可复用基础能力库。重点子目录包括 `memory/`（FactStore、摘要、ticker）、`pi-sdk/`（Pi SDK 适配）、`tools/`（内置工具）、`desk/`（书桌与 Cron）、`browser/`、`terminal/`、`sandbox/`、`resource-io/`、`session-files/`、`resources/`、`skills/`、`workflow/`、`bridge/`、`llm/`、`providers/` 和 `file-history/`。
- `hub/`：同进程调度中枢。`index.ts` 创建 `EventBus`、`ChannelRouter`、`GuestHandler`、`Scheduler`、`DmRouter`，并将 Hub 回调和事件总线注入 Engine；负责频道/DM、Heartbeat/Cron、Agent activity 等后台协作。
- `server/`：Node.js 进程的 Hono HTTP + WebSocket 边界。`index.ts` 导出 `startServer()`，创建 Engine/Hub/Hono、执行鉴权和绑定、注册组合路由；`composition/open-root.ts` 挂载开放路由，`composition/full-root.ts` 挂载闭集产品路由，`main-full.ts` 是当前完整产品入口；`routes/` 是 REST/WS 路由工厂，`http/` 是请求上下文、鉴权和边界策略。
- `desktop/`：Electron 主进程、预加载、渲染器和 native helper。`bootstrap.cjs` 解析 `HANA_HOME`、写启动诊断并加载主进程；`main.cjs` 创建窗口、启动/管理 Server、处理 IPC 和桌面能力；`src/main.tsx` 等是 React 入口，`src/react/` 是 UI；`native/` 含 macOS computer-use 与 Windows sandbox helper。
- `cli/`：server-first CLI。`entry.ts` 解析命令并选择本地/远程连接；`client.ts` 以 HTTP/WS 访问 Server；`chat.ts` 负责终端流式交互；`server-runner.ts`、`local-server.ts` 负责发现/启动本地 Server；`bundle.ts` 和 `data.ts` 是 Web 前端发行包及数据 epoch 维护面。
- `shared/`：跨 core/server/desktop/CLI 的契约和无状态工具，包括 `model-ref.ts`、`errors.ts`、`error-bus.ts`、`hana-runtime-paths.*`、`session-projects.ts`、`workspace-scope.ts`、`tool-categories.ts`、资源/权限/网络/配置/安全相关类型与规范。
- `packages/`：插件生态的独立包：`plugin-protocol` 定义协议类型，`plugin-runtime` 为插件运行时，`plugin-sdk` 为 WebView/iframe 浏览器端 SDK，`plugin-components` 为 React UI 组件。
- `plugins/`：内置系统插件（实际存在 `beautify/`、`jimeng-cli/`、`media/`、`office/`）。用户/开发插件运行时目录由 `core/engine.ts:initPlugins()` 指向 `${HANA_HOME}/plugins`、`${HANA_HOME}/plugins-dev`。
- `skills2set/`：内置技能与技能创建工具，包括 `hana-plugin-creator/`、`skill-creator/`、`user-guide/` 等。
- `scripts/`：构建、打包、Server/CLI bundle、运行时依赖追踪、安装器、签名、公证、迁移和验证脚本；`scripts/launch.js` 是开发态 Electron/CLI/Server 的统一子进程启动器。
- `tests/`：Vitest 测试，实际统计到 762 个 `*.test.ts`/`*.test.tsx`/`*.test.js` 文件（含子目录）；`tests/README.md` 定义 contract、regression、unit、route、build、platform 六类测试策略。
- `tools/alpha-gate-worker/`：独立 Cloudflare Worker 相关辅助工具（`worker.mjs`、`core.mjs`、`wrangler.toml`），不属于主 Engine/Server 运行时主链。
- `build/`：构建边界、持久化 schema/启动收据、安装器和 open-boundary 等构建期清单。
- `examples/`：示例插件；`.github/`：CI、Issue 模板和项目资源。

## 核心数据流

### 1. 启动与组合

1. `scripts/launch.js` 根据模式启动 Electron、CLI 或 `server/main-full.ts`；根 `index.js` 只调用 `cli/entry.ts`，不直接创建 `HanaEngine`。
2. Electron 路径先由 `desktop/bootstrap.cjs` 解析并设置 `HANA_HOME`，再加载 `desktop/main.cjs`；主进程启动 Server、等待其就绪，并承载窗口/预加载/渲染器。
3. `server/main-full.ts` 将 `server/index.ts:startServer` 与 `server/composition/full-root.ts` 组合。`server/index.ts` 先绑定监听端口、执行 `ensureFirstRun()` 和本地身份注册，再创建 `HanaEngine` 并 `await engine.init()`。
4. Engine 初始化迁移、凭证文件权限、运行时上下文、资源服务、Pi SDK/ModelRegistry、所有 Agent、Skill/ResourceLoader；Server 随后创建 Hub，注册框架扩展、初始化插件、启动 Scheduler，再建立 Hono 与 WebSocket 组合。
5. `server/composition/open-root.ts` 挂载 chat、sessions、models、providers、agents、skills、channels、DM、files、preferences、Bridge、MCP、plugins、resources、resource-io、usage、speech 等开放路由；`full-root.ts` 额外挂载 avatar、character-cards、cards、desk、diary，并注入内置媒体适配器。`mobile-workbench` 在 `server/index.ts` 中单独挂载，源码标为 evidence-needed，不被 open-root 自动归类。

### 2. 聊天请求与会话持久化

1. 桌面端、Mobile/远程前端、Bridge 或 CLI 通过 REST/WS 进入 `server/routes/chat.ts`；WS 输入协议在 `server/ws-protocol.ts` 中定义，包含 `prompt`、`interject`、`abort`、`resume_stream`、`compact` 等消息。
2. 路由边界先由 `server/http/route-security.ts` 分类为 public、authenticated、local-only、scope、studio-owner 或 plugin-route，再由请求上下文解析 principal、studio/session 范围。WS 通过 `/api/ws-ticket` 或 Bearer/loopback 身份建立受限连接。
3. Chat route 将输入交给 `Hub.send()` 或桌面提交路径；Hub 将 sessionKey、sessionId、sessionPath、agentId、权限模式、工作目录、媒体附件等上下文交给 Engine/SessionCoordinator。
4. `SessionCoordinator` 选择/创建 Pi SDK session，组装 Agent system prompt、记忆、workspace instruction、Skills、tool catalog、model/provider execution config；Agent 的工具来自 `core/agent.ts` 与 `lib/tools/`。
5. Pi SDK 产生流式文本、思考、工具、媒体、activity 等事件；Hub/EventBus 和 Server WS 以 `sessionId`/`sessionPath`/`streamId`/`seq` 标识并广播，`resume_stream` 可从事件序号恢复。
6. 会话正文采用 Pi SDK JSONL（`core/session-jsonl-file.ts` 负责解析、超长行投影和修复），同时由 `core/session-manifest/store.ts` 保存稳定 `sessionId` 与 locator、生命周期、权限/记忆/工作区快照等元数据；`SessionFileRegistry` 另存 `*.jsonl.files.json` sidecar。

### 3. Agent、记忆与人格

- `Agent` 的唯一身份是 `id`，`agentDir = agentsDir/<id>`；`config.yaml`、`memory/`、`sessions/`、`desk/` 都从该目录派生（`core/agent.ts:167-199`）。
- `AgentManager` 扫描 Agent 目录，先加载配置，再懒初始化焦点 Agent runtime；`Agent.init()` 创建 `FactStore`、`SessionSummaryManager`、memory ticker，组装 system prompt 和工具。
- `lib/memory/fact-store.ts` 的 v2 记忆是 SQLite `facts` 表 + FTS5：字段包括 `fact`、`search_text`、`tags`、`time`、`session_id`、`created_at`；CJK 查询会构造 2/3-gram，源码明确不使用 embedding/vector/decay/hit_count。
- 人格/系统提示词由 `core/persona-source.ts`、`core/platform-prompt.ts`、`core/workspace-instruction-files.ts` 等共同提供；README 说明人格文件使用 Agent 私有文件/模板并可随角色卡、Skills 迁移。

### 4. 模型、Provider 与 LLM 调用

`ModelManager.init()` 在 `${HANA_HOME}/auth.json` 初始化 Pi SDK `AuthStorage`，加载 `ProviderRegistry`，同步 provider 配置到 `${HANA_HOME}/models.json`，创建 Pi `ModelRegistry` 和 `ExecutionRouter`；`refreshAvailable()` 以 Provider Catalog 的模型选择为准，形成 `_availableModels` 唯一模型真理源。`core/llm-client.ts` 是文本调用边界，`core/provider-compat.ts` 和 `core/provider-compat/` 负责不同 Provider payload/messages 兼容化。Provider 插件贡献在 `engine.initPlugins()` 后注册回 ProviderRegistry，再触发模型重新同步。

### 5. 文件、资源与媒体

- 工具/插件将本地生成物通过 `SessionFileRegistry.registerFile()` 或推荐的 `stageFile()` 登记为 SessionFile；登记记录包含 `sf_...` file id、session identity、路径、mime/kind、存储类型、origin、操作和生命周期，并写入 session sidecar。
- `lib/resources/resource-envelope.ts` 把稳定 SessionFile ID 映射为 `res_sf_...` Resource envelope，带 `studioId`、生命周期、storage、self/content links；对象深度冻结。
- `ResourceService` 通过 agents 目录扫描 sidecar、解析资源实体和文件内容；`ResourceAccessService` 在 metadata/content 读取前执行 capability authorization，远程请求会移除 `filePath`/`realPath`，并写 security audit。
- REST `/api/resources/:resourceId` 提供 metadata，`POST .../ticket` 签发 HMAC-SHA256、默认 5 分钟 TTL 的资源票据，`GET/HEAD .../content` 支持 ETag、Range 和流式文件响应；资源写读/搜索/监听由 `/api/resource-io/*` 接口转交 ResourceIO。

### 6. 后台协作、Bridge、插件与计划任务

Hub 的 `EventBus` 将 Engine、频道、DM、Bridge、插件和 UI 事件接在一起；`Scheduler` 运行 Heartbeat/Cron，`ChannelRouter` 和 `DmRouter` 负责 Agent 间/外部消息路由。`BridgeSessionManager` 与 `lib/bridge/` 保存平台会话和媒体投递上下文。

`PluginManager` 扫描内置和用户插件，收集 tools/routes/skills/agents/commands/providers/extensions/pages/widgets/settings tabs；`PluginContext` 按 `restricted`/`full-access` 生成带权限的 bus、network、resources、config、session-file/stage-file 能力。插件 HTTP route 通过 `server/http/route-security.ts` 只允许匹配的 plugin surface principal 或 studio owner；iframe 侧 `@hana/plugin-sdk` 只做 host-mediated UI 请求，不直接暴露宿主文件系统。

## 关键类/函数/数据模型及相对路径

| 组件 | 关键类/函数/模型 | 作用 |
|---|---|---|
| 引擎 | `HanaEngine`、`HanaEngine.init()`、`HanaEngine.initPlugins()` | 统一持有 Manager，串起迁移、资源、模型、Agent、Skills、插件和 session runtime；`core/engine.ts` |
| Agent | `Agent`、`Agent.loadConfigOnly()`、`Agent.init()`；`AgentManager.initAllAgents()`、`ensureAgentRuntime()` | Agent 身份、人格、记忆、工具和 desk；`core/agent.ts`、`core/agent-manager.ts` |
| 会话 | `SessionCoordinator`、`SessionManifestStore`、`SessionManifestResolver`、`ensureSessionRefForPath()` | Pi SDK session 生命周期、稳定 ID、locator 历史、权限/记忆/能力快照；`core/session-coordinator.ts`、`core/session-manifest/store.ts`、`core/session-manifest/resolver.ts`、`core/session-manifest/ref.ts` |
| 会话正文 | `parseSessionEntries()`、`repairOversizedSessionEntriesInFile()`、`serializeSessionEntries()` | JSONL 校验、超长行投影、修复备份和重写；`core/session-jsonl-file.ts` |
| 会话文件 | `SessionFileRegistry.registerFile()`、`get()`、`forkSessionFiles()` | SessionFile 登记、sidecar、稳定 file id、fork 复制；`lib/session-files/session-file-registry.ts` |
| 资源 | `createSessionFileResourceEnvelope()`、`ResourceService.getResource()`/`resolveContent()`、`ResourceAccessService.getMetadata()`/`resolveContent()` | Resource 身份、内容解析、远程路径脱敏与审计；`lib/resources/resource-envelope.ts`、`core/resource-service.ts`、`core/resource-access-service.ts` |
| 资源票据 | `issueResourceTicket()`、`verifyResourceTicket()` | `${HANA_HOME}/security/resource-ticket-key` HMAC 签名和 TTL 内容访问票据；`core/resource-ticket-service.ts` |
| 模型 | `ModelManager.init()`、`refreshAvailable()`；`ProviderRegistry`、`ExecutionRouter` | AuthStorage、Provider Catalog、models.json、可用模型投影、凭证和执行路由；`core/model-manager.ts`、`core/provider-registry.ts`、`core/execution-router.ts` |
| 记忆 | `FactStore`、`buildFactSearchText()`；`SessionSummaryManager`、`createMemoryTicker()` | facts.db 元事实/标签/FTS5、摘要和主动记忆维护；`lib/memory/fact-store.ts`、`lib/memory/session-summary.ts`、`lib/memory/memory-ticker.ts` |
| 授权 | `authorizeCapability()`、`principalOwnsLocalConnection()`、`ResourceAccessService._authorize()` | missing capability/principal、local owner、grant/transport/scope 决策；`core/capability-policy.ts`、`core/security-principal.ts` |
| 执行边界 | `createRuntimeExecutionBoundary()`、`createLocalExecutionBoundary()` | 生成不可变 `execb_<serverNodeId>_<studioId>` boundary；`core/execution-boundary.ts` |
| 执行租约 | `issueRemoteWriteLease()`、`consumeRemoteWriteLease()`、`revokeRemoteWriteLease()`；`issueExecutionLease()` | 远程写的 workspace_write lease，默认 TTL 5 分钟，状态 issued/consumed/expired/revoked；`core/execution-lease-service.ts`、`core/execution-lease-registry.ts` |
| Hub | `Hub`、`Hub.send()`、`EventBus`、`Scheduler` | 统一消息入口、事件总线、频道/DM/后台调度；`hub/index.ts`、`hub/event-bus.ts`、`hub/scheduler.ts` |
| Server | `startServer()`、`registerOpenRoutes()`、`registerClosedRoutes()` | Hono 进程初始化、组合路由和 WebSocket 接线；`server/index.ts`、`server/composition/open-root.ts`、`server/composition/full-root.ts` |
| WS 协议 | `wsSend()`、`wsParse()`、`createSessionStreamEventWsMessage()`、`createStreamResumeWsMessage()` | 统一流式事件、身份、seq 和 replay 校验；`server/ws-protocol.ts` |
| 插件 | `PluginManager`、`createPluginContext()`、`HanaPluginSdk` | 插件发现/生命周期/贡献注册；服务端资源和权限运行时；iframe UI SDK；`core/plugin-manager.ts`、`core/plugin-context.ts`、`packages/plugin-runtime/src/index.ts`、`packages/plugin-sdk/src/index.ts` |
| CLI | `main()`、`parseCliArgs()`、`HanaCliClient`、`startCLI()` | 命令分派、连接发现、HTTP/WS 终端客户端；`cli/entry.ts`、`cli/args.ts`、`cli/client.ts`、`server/cli.ts` |

### 主要持久化模型

- Agent 数据目录：`<HANA_HOME>/agents/<agentId>/config.yaml`、`memory/facts.db`、`memory/*.md`、`memory/summaries/`、`sessions/*.jsonl`、`desk/`。
- 全局配置：`<HANA_HOME>/user/preferences.json`；`core/preferences-manager.ts` 采用缓存 + 原子写入，并维护 sandbox、网络代理、UI、通知、模型/权限等全局偏好。
- Provider/模型：`<HANA_HOME>/providers/`（Provider Catalog 相关文件）、`auth.json`、`models.json`；精确文件布局由 `core/provider-registry.ts` 与运行期配置决定。
- Session manifest SQLite：`session_manifests` 的列包含 `session_id`、`owner_agent_id`、`domain`、`kind`、`lifecycle`、`health`、当前 locator、memory policy、permission snapshot、thinking level、workspace scope、plugin、provenance、migration 和时间字段；关联表包括 locator history、capability snapshots、executor metadata、branch head 等（`core/session-manifest/store.ts`）。
- Session JSONL：首条记录必须 `type: "session"` 且带 `id`；消息/工具/压缩等条目按行存储。超大行在 `core/session-jsonl-file.ts` 中先去 inline media，再按字段/长度投影，并保留 `.repair.json` 备份。
- SessionFile sidecar：`<sessionPath>.files.json`，版本为 1，登记 `files` 与 `refs`；资源 envelope 的稳定 ID 形式为 `res_sf_...`。
- 安全状态：`<HANA_HOME>/security/execution-leases.json`、资源票据 key 和安全审计记录；执行租约 registry schemaVersion 为 1。

## API/CLI/SDK入口

### Server 启动入口

- `npm run server` → `scripts/launch.js server` → `server/main-full.ts` → `server/index.ts:startServer()`。
- Electron 内嵌路径由 `desktop/main.cjs` 启动 Server；开发/打包入口还由 `scripts/build-server*.mjs`、`server/bootstrap.ts` 等接入。
- `npm start`、`npm run start:dev`、`npm run start:vite` 负责构建 preload/renderer/splash/theme 后启动 Electron。

### HTTP/WS

开放路由集中在 `server/composition/open-root.ts`，主要入口包括：

- `/api/health`、`/api/server/identity`、`/api/access`、`/api/auth/*`、`/api/web-auth/*`、`/api/ws-ticket`；
- `/api/chat/*` 和 `/ws`；WS 输入/输出与流恢复契约见 `server/ws-protocol.ts`；
- `/api/sessions/*`、`/api/session-collab/*`、`/api/session-projects/*`、`/api/models/*`、`/api/providers/*`、`/api/agents/*`、`/api/skills/*`；
- `/api/channels/*`、`/api/dm/*`、`/api/bridge/*`、`/api/mcp/*`、`/api/plugins/*`；
- `/api/fs/*`、`/api/studio-workspaces/*`、`/api/upload-blob`、`/api/file-history/*`、`/api/resources/*`、`/api/resource-io/*`、`/api/usage/*`；
- `/api/preferences/*`、`/api/settings-snapshot/*`、`/api/commands/*`、`/api/checkpoints/*`、`/api/speech-recognition/*`、`/api/memory-dream/*`。

资源的具体内容入口是 `server/routes/resources.ts`：`GET /api/resources/:resourceId`、`POST /api/resources/:resourceId/ticket`、`GET/HEAD /api/resources/:resourceId/content`；资源操作入口是 `server/routes/resource-io.ts` 的 stat/read/list/search/write/write-expected-version/rename/move/trash/watch/subscribe 路由。完整产品额外由 `server/composition/full-root.ts` 挂载 `/api` 下的 avatar、character-cards、cards、desk、diary。

### CLI

`package.json` 的 bin 为 `hana: cli/entry.ts`。`cli/entry.ts` 支持：

- `hana serve [-- server args]`
- `hana status`
- `hana sessions`
- `hana continue [index|path]`
- `hana chat [--plain]`
- `hana bundle pull|status`
- `hana data diagnose|checkpoints|restore <transitionId>`
- `hana help`

连接参数为 `--url`、`--token`、`--session`；`HanaCliClient` 对 HTTP 使用 Bearer Authorization，对 WS 使用 Authorization header 或显式允许时的 query token。`server/cli.ts:startCLI()` 是附着 Server 后的交互式 WS/HTTP 客户端实现。

### 插件 SDK

- 浏览器 iframe/WebView：`@hana/plugin-sdk` 的 `hana.ready()`、`hana.assets.url()`、`hana.api.fetch()`、`hana.ui.resize()`、`hana.theme.*`、`hana.host.request()`、`hana.toast.show()`、`hana.external.open()`、`hana.clipboard.writeText()`、`hana.resources.open/pick/requestAccess()`。
- 服务端插件运行时：`@hana/plugin-runtime` 导出 `HanaSessionRef`、`HanaSessionFile`、`HanaResourceEnvelope`、`HanaPluginResources`，通过 `ctx.resources` 提供 stat/read/list/search/materialize/write/edit/mkdir/delete/copy/rename/move/trash/watch/subscribe，通过 `ctx.stageFile()` 进入 SessionFile 交付链路。
- 协议和类型：`@hana/plugin-protocol`；React 侧 UI 组件：`@hana/plugin-components`。

## 技术栈和依赖

### 运行和构建

- Node.js `>=24.12.0 <25`、ESM、TypeScript；`tsconfig*.json` 覆盖源码、Node 和测试类型检查。
- Electron `42.3.0`；React `^19.2.4`、React DOM、Zustand `^5.0.11`、CSS Modules；Vite `^7.3.1`。
- Server：Hono `^4.12.9`、`@hono/node-server`、`@hono/node-ws`、`ws`；构建用 `@vercel/nft`、esbuild、electron-builder。
- Agent runtime：`@earendil-works/pi-agent-core`、`@earendil-works/pi-ai`、`@earendil-works/pi-coding-agent`，版本均为 `0.80.3`；README 称其为 Pi SDK。
- 持久化：`better-sqlite3 ^12.6.2`，源码对事实记忆和 session manifest 均设置 WAL；JSON/YAML/文件使用原子写入或 sidecar。
- 测试/质量：Vitest `^4.0.18`、Testing Library、ESLint 9、TypeScript ESLint；`npm test` 脚本排除缓存和构建输出，`npm run typecheck` 执行三套 tsc 检查，`npm run lint` 执行 ESLint。

### 主要运行时依赖分组

- UI/编辑器：CodeMirror、Tiptap、Markdown-it、KaTeX、Mermaid、Motion、jsdom。
- 文件与媒体：`@firecrawl/anydoc`、Mammoth、UnPDF、ExcelJS、Photon、extract-zip、qrcode。
- 网络/平台：Undici、proxy-agent、node-telegram-bot-api、`@larksuiteoapi/node-sdk`、chokidar、node-pty。
- 文本/协议/校验：`@node-rs/jieba`、TypeBox、js-yaml、diff。
- 内置插件/扩展：插件包工作区，以及配置中包含的 Provider/MCP/媒体/Bridge 适配层。

锁文件为根 `package-lock.json`，lockfileVersion 3；本次只读取清单，没有执行安装，因而本文不对本机 `node_modules` 可用性作结论。

## 架构判断与未确认项

### 架构判断

1. **组合边界清晰**：`HanaEngine` 是薄 facade，具体职责落在 Manager/Service；`server/index.ts` 通过 `CompositionContext` 注入依赖，`open-root` 与 `full-root` 将路由组合从核心启动逻辑中分离。
2. **Server-first 是真实边界**：根 CLI 不直接依赖 Engine，而是通过 HTTP/WS Client；Electron 主进程也通过 spawn 的独立 Server 与前端交互。这样桌面、CLI、Mobile 和 Bridge 能复用同一套会话和资源协议。
3. **会话身份已从路径升级为稳定 ID**：manifest store 以 `sessionId` 为主键，并保留 locator history；源码同时保留 `sessionPath` 以兼容旧客户端/旧插件。这是跨移动、Bridge、fork、归档和文件移动场景的关键设计。
4. **资源不是裸路径**：SessionFile → Resource envelope → ResourceAccess/ResourceIO；远程 metadata 默认移除本地路径，内容访问可用短期 HMAC ticket，权限决策和安全审计处于资源服务前面。
5. **安全模型是分层门禁而非单一沙盒**：HTTP route scope、principal/grant capability、local owner 信任、执行边界、远程写 lease、操作系统 sandbox/PathGuard（README）共同构成边界。`restricted`/`full-access` 插件控制扩展面，但 `PLUGINS.md` 明确指出 restricted 插件代码本身仍在主进程运行，不是代码级沙盒。
6. **持久化偏向可恢复与迁移**：facts.db、session manifest、JSONL sidecar、preferences、lease registry 都有版本/迁移/备份/原子写入策略；启动流程将迁移和凭证权限修复作为 best-effort，并记录下次重试。
7. **测试以契约和风险为中心**：`tests/README.md` 明确优先保护权限、凭证、资源、SessionFile、跨 Agent/session 所有权、构建/原生依赖、Provider/Bridge/插件协议和跨平台行为；实际测试命名与此一致，例如 `session-manifest-store.test.ts` 覆盖持久身份/locator/lifecycle/policy，`resource-access-service.test.ts` 覆盖远程路径脱敏与授权，`startup-contract.test.ts` 覆盖启动器、Pi 路径边界、打包外部依赖和单实例锁。

### 未确认项与边界

- 本项目没有 `AGENTS.md`，也未找到既有 `ARCHITECTURE.md`；开发规则主要来自 `README.md`、`PLUGINS.md`、`packages/*/README.md`、源码注释和 `tests/README.md`。
- 本次按任务要求未安装依赖、未启动 Server/Electron、未执行 Vitest/typecheck/lint，因此不能把源码契约等同于当前环境的运行通过结果。
- `README.md` 的平台支持、签名/公证和发布能力是项目声明；本次没有进行安装包或平台实机验证。
- `server/main-full.ts` 是 `npm run server` 使用的完整产品入口；仓库同时存在 `server/main-open.ts`、`server/composition/open-root.ts` 和 open-boundary 构建脚本。当前实际 release/启动选择与开放导出边界的完整部署矩阵仍应以对应构建脚本和发行产物核验，不能仅凭目录名推断。
- `server/routes/mobile-workbench.ts` 在组合代码中明确标为 evidence-needed；本文只记录其被单独挂载，不把它归入已确认 open 或 closed。
- Provider 的真实模型、凭证、媒体能力取决于 `${HANA_HOME}` 的 Provider Catalog、`auth.json` 和运行时插件；`package.json` 只能确认依赖声明，不能确认用户当前配置或每个 Provider 的可用性。
- Pi SDK 被 `lib/pi-sdk/` 适配并由 `@earendil-works/pi-*` 提供，但其上游内部实现不在本项目核心源码中；本文只描述本仓库已读到的适配边界。
- 许多 core 文件采用 JavaScript 风格的 TypeScript（大量 `any`/声明字段），类型检查配置和测试契约承担了部分架构约束；是否达到完整运行时类型安全，未在本次静态分析外验证。

## 分析依据（实际读取）

本次实际读取的主要文件（全部为项目内相对路径）包括：

- `README.md`、`细探-HanaAgent.md`、`tests/README.md`、`package.json`、`package-lock.json`；未发现 `AGENTS.md`。
- 启动/入口：`index.js`、`scripts/launch.js`、`cli/entry.ts`、`cli/args.ts`、`cli/client.ts`、`server/index.ts`、`server/main-full.ts`、`server/composition/contract.ts`、`server/composition/open-root.ts`、`server/composition/full-root.ts`、`desktop/bootstrap.cjs`、`desktop/main.cjs`。
- 核心引擎/模型/Agent/session：`core/engine.ts`、`core/agent.ts`、`core/agent-manager.ts`、`core/model-manager.ts`、`core/provider-registry.ts`、`core/preferences-manager.ts`、`core/session-coordinator.ts`、`core/session-jsonl-file.ts`、`core/session-manifest/store.ts`、`core/session-manifest/resolver.ts`、`core/session-manifest/ref.ts`、`lib/memory/fact-store.ts`、`lib/memory/config-loader.ts`。
- 资源/安全/插件/调度：`core/resource-service.ts`、`core/resource-access-service.ts`、`core/resource-ticket-service.ts`、`lib/resources/resource-envelope.ts`、`lib/session-files/session-file-registry.ts`、`core/capability-policy.ts`、`core/execution-boundary.ts`、`core/execution-lease-service.ts`、`core/execution-lease-registry.ts`、`core/plugin-manager.ts`、`core/plugin-context.ts`、`hub/index.ts`、`PLUGINS.md`、`packages/plugin-sdk/README.md`、`packages/plugin-sdk/src/index.ts`、`packages/plugin-runtime/src/index.ts` 及四个 `packages/*/package.json`。
- API/协议/测试样例：`server/routes/chat.ts`、`server/ws-protocol.ts`、`server/routes/sessions.ts`、`server/routes/resources.ts`、`server/routes/resource-io.ts`、`server/http/route-security.ts`、`tests/session-manifest-store.test.ts`、`tests/resource-access-service.test.ts`、`tests/startup-contract.test.ts`。

本文件已吸收此前 `细探-HanaAgent.md` 的源码分析结论；后续只维护本文件，旧细探笔记不再作为独立事实源。

本文件只新增/更新了项目根的 `ARCHITECTURE.md`；未修改已有源码、未安装依赖、未运行服务或测试、未提交 Git。

---

## 第三轮：通用底座映射（基于当前源码的真实边界）

### 3.1 证据边界与方法

本轮不是把 HanaAgent 的 Agent 工作流当成平台底座，而是把当前源码中已经存在的**契约、注册表、持久化 owner、运行时句柄和外部进程边界**映射到四类平台职责：支持库、模块库、运行核心、网关。映射中的“应落点”是平台复用裁决，不等于 HanaAgent 已经实现了目标平台；凡源码没有证据的内容标为“待核”，不向上推断。

- **当前源码证据**：`core/engine.ts:349-729,2373-2668,2696-2812`、`hub/event-bus.ts:31-218`、`hub/event-bus-capabilities.ts:664-738`、`core/session-manifest/store.ts:237-360`、`lib/task-registry.ts:73-511`、`lib/session-execution-registry.ts:21-125`、`core/plugin-manager.ts:220-245,386-445,491-612,614-800`、`core/provider-registry.ts:489-741`、`server/index.ts:435-547,1285-1369`、`core/mcp/clients/stdio-client.ts:20-180`、`server/bootstrap.ts:32-73`、`lib/terminal/terminal-session-manager.ts:51-180`、`lib/resource-io/providers/url-provider.ts:28-220`。
- **旧细探状态**：当前工作树没有 `细探-HanaAgent.md`，Git 索引也没有该文件；正式文档第 249、255 行曾引用并声明吸收它。因此本轮只能以当前源码和现有 `ARCHITECTURE.md` 为证据，不能伪称已读取一个当前不存在的旧笔记；旧笔记若在其他归档位置，应由主协调者另行提供后再复核。
- **代码图状态**：目标目录没有 `.codegraph/`，`codegraph_explore` 返回“未建立代码图”；本轮未使用错误绑定到 `~/Documents/Agent/PHP/华世王镞_v3` 的项目上下文结果，也未把任何其他仓库证据写入本文件。
- **当前文档事实与本轮映射分离**：已有章节描述“项目是什么”；本章只新增“哪些真实能力可以抽象为底座契约、哪些仍是项目编排”。未因存在 `Agent`、`workflow`、`prompt`、`memory` 等词就认定存在通用运行核心。

### 3.2 四层边界总图（映射目标，不是现状宣称）

```text
外部客户端 / Electron / CLI / Bridge / Mobile / 插件 UI
                 │  HTTP REST、WebSocket、CLI client、插件 host API
                 ▼
统一网关：认证、scope、请求/流协议、错误/超时、只读查询与命令入口
                 │  只调用公开模块入口，不直写存储、不持有第三方对象
                 ▼
运行核心：请求上下文、能力分发、会话/任务生命周期、取消传播、资源监督、审计
                 │
                 ├── 模块库：会话编排、模型选择、工具装配、插件贡献、资源服务、计划任务
                 │
                 └── 支持库：稳定 ID/契约/错误、原子文件、SQLite/JSONL/sidecar、provider 适配
                                      │
                                      ▼
                         Pi SDK、better-sqlite3、node-pty、MCP stdio、CLI、HTTP、native helper
```

现状中 `HanaEngine` 是组合 facade（`core/engine.ts:260` 附近），`Hub` 是同进程调度中枢，`server/index.ts` 是 HTTP/WS 组合根；它们**不是天然的三层 owner**。平台化时必须拆出下表的唯一 owner，保留 HanaAgent 适配层只做路径、配置、权限和版本绑定。

### 3.3 能力域到四层的映射表

| 能力域 | 当前源码事实 | 支持库 | 模块库 | 运行核心唯一 owner | 网关边界 | 裁决 |
|---|---|---|---|---|---|---|
| 能力注册/发现 | `EventBusCapabilityDirectory` 按 `type` 保存契约；`EventBus.handle()` 可绑定 handler；`ProviderRegistry` 另有 provider/media 注册表；插件还贡献 tools/routes/providers | 能力 ID、输入/输出 schema、权限、错误集合、稳定性、owner 字段的规范化；`shared/errors.ts` 等稳定错误 | EventBus 能力目录、ProviderRegistry、PluginManager 的领域注册适配 | 运行期“已注册能力 → handler/provider → 可用状态”的分发账本；禁止多个注册表各自成为规范 owner | 只提供 list/get/request；不让客户端直接注入函数或 provider 对象 | **吸收契约形状；升级为单一公共能力注册/调用器**。当前存在 EventBus/Provider/Plugin 多注册面，不能直接视为一个平台注册表 |
| 会话身份/正文 | `SessionManifestStore` 用 SQLite WAL 维护 `session_manifests`、locator history、能力快照、executor metadata、branch heads；正文仍是 Pi JSONL | session ref、稳定 ID、JSONL entry、快照、分支和 locator 错误契约；SQLite/JSONL 原子读写 | `SessionCoordinator` 负责创建、切换、fork、compact、prompt 和 runtime 恢复；manifest resolver/ref 负责路径兼容 | 会话生命周期、owner_agent_id、当前 runtime 句柄、状态迁移和关闭；路径只是 locator，不是 owner | `/api/sessions/*`、`/api/chat/*`、WS resume/seq；只提交命令，不直接改 JSONL/SQLite | **吸收稳定身份/manifest；升级正文与 manifest 的单写 owner、崩溃恢复契约** |
| 任务/调度 | `TaskRegistry` 的 handler 在内存，任务/计划元数据可写 `.ephemeral/plugin-tasks.json`；恢复 active 状态为 `recovering`，handler 需提供 `abort` | Task/lease 状态、幂等键、进度、错误、重试和时间契约；原子 JSON 持久化 | `TaskRegistry`、Hub task bus handlers、Scheduler、媒体/子代理/workflow runner | 任务状态机、取消入口、handler ownership、调度 timer、恢复和最终态；业务 runner 不可旁路改 owner 状态 | `task:list/get/cancel/schedule` 等 bus/REST/WS 映射；超时和取消返回统一结果 | **吸收任务状态与恢复；升级持久化写失败不再仅 log warning，补 owner/幂等/租约** |
| 工具/能力执行 | 内置工具来自 `lib/tools`；插件工具由 `PluginManager` 包装；MCP 工具进入 `McpManager`；`buildTools()` 组合并可延迟 catalog；能力声明由工具权限 wrapper 校验 | Tool descriptor、参数 schema、capability、permission、result/error、调用句柄 | Tool catalog、工具装配、MCP bridge、session permission/checkpoint wrapper | 当前会话的 tool snapshot、可执行句柄、取消注册和实际调用监督；同一 tool 只能由一个注册 owner 发布 | Chat/WS 工具事件、插件 bus request、MCP route；网关不接收任意函数 | **吸收 descriptor/policy；升级工具注册与执行为一个可审计入口，禁止 builtin/plugin/MCP 各自解释错误** |
| 模型/provider | `ModelManager._availableModels` 被声明为唯一模型真理源；`ProviderRegistry` 合并 catalog/local plugin/runtime media；`ExecutionRouter` 只做 role/ref→执行参数，Pi `ModelRegistry` 负责 SDK 侧 | model-ref、provider credential、payload compatibility、usage/error、流式事件契约 | ModelManager、ProviderRegistry、ExecutionRouter、Pi SDK 适配、媒体 provider 选择 | provider/model 解析、凭证句柄、每个 session 的 model binding、调用取消/预算/审计；不得由 Agent config 直接发请求 | `/api/models/*`、`/api/providers/*`、chat stream；凭证只在受控服务端边界 | **吸收“availableModels 单真理源”原则；升级凭证/模型调用为单 provider gateway，保留 SDK 作为 provider adapter** |
| 插件/技能 | `PluginManager` 扫描 builtin/user，按 source+id 形成 `pluginKey`；贡献 tools/routes/skills/agents/commands/providers；load 有 15s timeout，cleanup 调 `onunload` 和 disposables；`createPluginContext` 生成权限化 bus/network/resources/config | plugin protocol、manifest、capability/permission、生命周期/cleanup、版本兼容、host-mediated SDK | PluginManager、SkillManager、PluginContext、ResourceLoader、Provider contribution | plugin instance、contribution registrations、disposable 栈、active source/shadowing、load/activation 状态；插件不是代码级沙盒 | `/api/plugins/*`、iframe/WebView host API、plugin route；restricted/full-access 只是一层权限，不取代进程隔离 | **吸收 manifest/context/cleanup；升级 full-access 插件的崩溃隔离和租约** |
| 上下文/快照 | SessionCoordinator 组装 system prompt、memory、workspace instruction、skills、tool catalog、model/provider config；manifest 有 capability/prompt snapshot；`buildTools()` 对 runtime session ref 做冻结 | session ref、workspace scope、prompt/tool/model snapshot、cache prefix、request context 的不可变结构 | Session turn/context builder、skill snapshot、provider compatibility、memory prompt builder | 当前 turn 的上下文版本、可取消 signal、执行边界、snapshot fingerprint；模型只能消费快照，不能改 owner 事实 | chat/WS 只传 prompt/interject/abort/resume 等命令；不得让客户端提交可信权限/模型凭证 | **吸收快照/漂移检测；升级 snapshot version+hash+恢复语义** |
| 存储/资源 | `HANA_HOME` 下 facts.db、manifest.db、JSONL、sidecar、lease JSON、task JSON、usage ledger、plugin-data；`FactStore`/manifest store 各自持有 better-sqlite3 句柄；SessionFileRegistry 写 sidecar | SQLite/JSONL/sidecar/atomicWrite、schema migration、file/resource ref、checksum、close contract | FactStore、SessionManifestStore、SessionFileRegistry、ResourceService/Access/IO、FileHistoryService | 每类事实一个单写 owner：manifest、session body、session files、facts、leases、tasks 分开；运行核心负责打开/关闭顺序与恢复 | resources/file/resource-io routes 只通过 ResourceAccess/IO；远程去除 realPath/filePath | **吸收资源 envelope 和 sidecar；升级多 store 统一生命周期与读写证据，禁止 route 直写盘** |
| 线程/进程 | Node 主线程承载 Server/Engine；`server/bootstrap.ts` 仅用 Worker 做不受主线程阻塞影响的 keepalive；Electron spawn 独立 Server；MCP stdio、node-pty、CLI/native helper 使用 child process；SessionExecutionRegistry 是内存 AbortController 表，不是线程 | process/worker/PTY handle、signal、exit/kill、stdio JSON-RPC、资源回收契约 | TerminalSessionManager、McpStdioClient、CLI/media/native adapters、computer-use provider | 子进程/Worker/PTY 的监督、进程组回收、超时升级、崩溃判定、残留扫描；明确“keepalive worker ≠ 业务 worker” | Server 只暴露 start/read/write/stop/health；不把 PID/PTY 对象当 API 合同 | **吸收独立边界；升级统一 process supervisor** |
| 外部服务 | Pi/LLM HTTP、URL ResourceIO（SSRF/DNS/redirect/size/timeout）、MCP stdio JSON-RPC、Bridge 平台 HTTP、CLI 工具、native computer-use | URL/HTTP、MCP、CLI、native protocol adapter；外部错误、超时、重试和凭证脱敏 | Provider/Bridge/MCP/ResourceIO/media 模块 | 外部调用预算、取消、句柄/连接释放、重试上限、审计和 provider health；第三方 SDK 不能穿透到网关 | REST/WS/CLI 是产品协议；第三方 token、真实 URL、路径、PID 不外泄 | **吸收安全检查；升级所有外部调用统一纳入监督和错误归一化** |

### 3.4 唯一 owner、句柄与租约裁决

| 资源/事实 | 创建者 | 唯一 owner（应固定） | 对外句柄/租约 | 正常释放 | 超时/取消/崩溃释放 | 当前证据与缺口 |
|---|---|---|---|---|---|---|
| 能力 descriptor + handler | EventBus/PluginManager/ProviderRegistry | 运行核心能力注册器；领域模块只能注册，不得重复解释 | `capabilityId + registrationToken` | unregister；plugin cleanup 反向移除 | owner 失活时批量撤销；调用中 handler 由 supervisor 等待/标记失败 | EventBus unregister 有实现；跨 registry 的全局唯一性未证实 |
| session manifest DB | `HanaEngine` 构造 `SessionManifestStore` | 会话 manifest store（事实）+ 运行核心（打开/关闭） | `sessionId`；path/locator 只可解析 | `SessionCoordinator.cleanupSession()` 后 `db.close()` | 启动恢复/隔离损坏 DB；未提交事务由 SQLite 回滚，运行态句柄清空 | 构造失败会 close；Engine dispose 关闭 store；跨进程并发 owner 待核 |
| session runtime / tool call | SessionCoordinator / `SessionExecutionRegistry.begin()` | 运行核心 session execution supervisor | `{sessionId, toolCallId, AbortSignal, release}` | tool promise `finally` 调 release，session abort 按 sessionId | AbortSignal.any 传播；孤儿运行时需启动恢复扫描 | `release` 幂等且运行态删除；未发现持久化 in-flight journal |
| task/schedule | TaskRegistry.register/schedule | TaskRegistry（状态）+ handler（业务执行） | `taskId` / `scheduleId`；handler 只拿 task id | complete/fail/cancel + clear timer | abort handler；恢复 active→recovering；无 handler 时仍可标 aborted，但不能保证实际业务停止 | `abort` 无 handler 会记录状态；持久化异常只 warning，是 P1 缺口 |
| plugin instance/contribution | PluginManager | PluginManager 按 `pluginKey` | pluginKey、dispose 函数、context owner | `onunload` 后逆序 disposables、移除 tools/routes/providers | load timeout 标 cancelled 后 cleanup；进程崩溃时主进程内插件句柄无法隔离 | 15s boundary、cleanup 真实存在；restricted 仍主进程执行，崩溃隔离待升级 |
| external write | capability policy + `issueRemoteWriteLease()` | execution-lease registry（记录）+ 运行核心（消费边界） | `execb_*` execution boundary、`lease_*` lease；lease 默认 5min | consume/revoke，JSON 原子写 | expiry/revoke；宿主崩溃后启动校验过期租约并禁止复用 | lease 状态 issued/consumed/expired/revoked；没有看到自动全量过期清扫 owner |
| MCP stdio child | McpStdioClient | MCP runtime/supervisor | child process + pending request id | stdin EOF→等待 2s→SIGTERM→再 3s→SIGKILL；pending 全 reject | exit/error reject all pending，报告 expected/unexpected；需补 stderr/pipe 关闭审计 | `core/mcp/clients/stdio-client.ts:74-180` 已有链路 |
| PTY terminal | TerminalSessionManager + node-pty backend | TerminalSessionManager（session ownership） | terminalId + `{sessionPath, seq}` + PTY handle | close 调 handle.dispose，记录 exit/transcript | session close 批量 close；进程异常由 onExit 标记；残留 PTY 扫描待核 | `lib/terminal/terminal-session-manager.ts:122-180` 有 owner check/持久 transcript |
| Resource/SessionFile | SessionFileRegistry / ResourceService | SessionFileRegistry 负责 file identity；ResourceAccessService 负责授权读取 | `sf_*` / `res_sf_*` / HMAC ticket | sidecar 写入、fork/discard、ticket 到期 | missing file 标记、远程路径脱敏；缓存 GC 与 watcher 崩溃恢复需独立验证 | sidecar/稳定 ID/TTL ticket 已实现；删除/恢复全矩阵待核 |

**硬规则**：一个原子能力只有一个规范 ID、一个契约 owner、一个公开入口；provider、插件、MCP 只是实现/发现来源。`HanaEngine` 只能是装配 facade；`server/index.ts` 只能是网关组合根；`Hub` 只能是事件/调度模块，不能同时成为持久化 owner。任何新平台接入先提交能力契约、资源责任和租约，再进入装配。

### 3.5 失败/超时/取消/崩溃矩阵

下表记录“当前实现能证明什么”和“平台验收必须补什么”；没有执行证据的格子不得写成已通过。

| 域 | 正常完成 | 业务失败/第三方错误 | 超时 | 主动取消 | 宿主/子进程崩溃 | 验收判据 |
|---|---|---|---|---|---|---|
| 能力/Bus | handler 返回首个非 `SKIP` 结果 | 无 handler=`BusNoHandlerError`；handler 异常传播 | `Promise.race`=`BusTimeoutError`，但底层 handler 可能仍运行 | 当前 request 没有统一 signal 传播 | owner unregister 后新请求不可用，进行中请求清理待核 | 必须证明超时后无重复副作用、handler 可观测终态 |
| 会话/工具 | Pi stream 完成，execution `finally.release` | session/file/model 错误写统一错误并保留 session | model/tool/WS 超时退出调用；不能只断连接 | `abortSession` + `abortBySession` + TaskRegistry 子任务 | 重启按 manifest/JSONL/branch 恢复，不恢复旧 AbortController | sessionId 不变、无孤儿任务/句柄、JSONL 可继续追加 |
| 任务/计划 | complete，schedule 更新 nextRunAt/runCount | fail 写 error；计划仍按 interval 重新 arm | 必须进入 failed/aborted/canceled 的明确语义 | handler.abort 后才允许 canceled | active persisted→recovering；handler 再注册后恢复策略必须可重复 | 状态机闭合、幂等 cancel、重启不重复执行一次性任务 |
| 插件 | load/activation 完成，贡献可查询 | failed/incompatible/restricted，不污染其他 plugin | load/activation 15s 后 cleanup | `_loadCancelled`、onunload、逆序 disposable | 主进程插件异常不能拖垮 Engine；当前缺独立进程隔离 | 贡献数归零、route/tool/provider 不残留、日志含失败阶段 |
| 模型/外部 HTTP | 返回模型/stream，usage 归账 | provider 未配置、HTTP 非 2xx、凭证错误 | request timeout + signal，连接/响应体释放 | AbortSignal 传到 fetch/SDK | provider 进程或网络断开，session 可恢复到 unavailable 状态 | 无 secret 泄露、重试有上限、模型 ref 不漂移 |
| MCP/CLI/PTY | JSON-RPC/CLI/PTY 完成，stdin/stdout/handle 关闭 | exit/error/非 JSON/非零码映射 provider failure | request timer、execFile timeout、PTY wait | stdin EOF/SIGTERM/SIGKILL 或 handle.dispose | child exit signal/exitCode 被记录，pending 全 reject，PID/端口消失 | 真实检查进程树、pipe、临时输出目录和 transcript 残留 |
| 存储/资源 | SQLite transaction commit、JSON 原子替换、sidecar 更新 | rollback/部分写错误留下诊断，不吞成成功 | DB/URL/IO timeout 不持有连接/文件句柄 | cancel 不删除仍被引用的制品，释放 watcher | WAL/JSON/sidecar 损坏隔离或恢复；不能静默重建空库 | 读回内容/版本/owner，`close` 后无锁、无 watcher、无临时残留 |
| Server/网关 | stop accepting → drain → dispose → 删除 server-info | route 错误统一状态码/错误体 | 15s shutdown force exit 是最后护栏 | SIGINT/SIGTERM 进入同一 gracefulShutdown | server-info stale、PID 不存在、重启后可启动；当前 uncaughtException 主要记录 | 端口、PID、server-info、WS client、Bridge、Hub/Engine 全部收口 |

### 3.6 L0-L4 验证契约

L0-L4 是平台化验收等级，不把某个 Agent workflow 的 happy path 当作底座通过；每级都要求真实对象和可回读证据。

| 等级 | 目标 | 必须验证的真实内容 | HanaAgent 本轮状态 |
|---|---|---|---|
| **L0 静态边界** | 证明目录/契约/owner 没有明显越界 | 仅 `ARCHITECTURE.md` 变更；所有证据路径存在；四层映射、唯一 owner、禁止 route 直写和 workflow 非底座声明齐全；代码图不可用必须留痕 | **本轮可执行**，但不等价于源码行为通过 |
| **L1 单元/契约** | 证明纯契约和状态机 | `event-bus-capabilities`、`event-bus-request`、`task-registry`、`session-execution-registry`、`execution-lease-registry`、`tool-invocation-permission`、`plugin-manager`；覆盖重复注册、权限拒绝、超时、幂等 release/cancel | 测试文件存在；依赖未安装，执行结果待命令验证 |
| **L2 组合/持久化** | 证明一个 owner 跨模块可恢复 | manifest SQLite WAL+迁移、JSONL/sidecar、TaskRegistry restart recovery、session ref/locator、plugin contribution cleanup、ResourceAccess 脱敏/审计；重启后读回同一 ID/版本 | 源码有组合链和测试名；未运行，不能宣称通过 |
| **L3 真实外部边界** | 证明网关到真实 provider/process/service | 启动真实 Server；HTTP/WS auth+scope；Pi provider；MCP child；node-pty；URL SSRF/redirect/size/timeout；CLI/native helper；真实取消、SIGTERM/SIGKILL、进程树/端口清理 | 当前仅有源码/测试契约，未安装依赖且未启动服务 |
| **L4 崩溃/发布门禁** | 证明 crash consistency 与可审计发布 | 强杀 Server/MCP/PTY/provider；恢复 manifest/task/lease/resource；无孤儿 PID/port/lock/temp/pipe；运行全量 `npm test`、`npm run typecheck`、`npm run lint`，记录退出码和测试数；门禁拒绝未声明能力/越权依赖 | **未验证**；不能用历史日志、子代理回信或“源码存在”替代 |

建议每个能力的验收记录至少包含：`能力id、契约owner、版本、输入/输出、可重试、超时、取消信号、句柄/租约、正常/失败/超时/取消/崩溃结果、资源残留检查、命令、退出码`。`skip` 只能记录为未验证，不能写成 pass。

### 3.7 复用/升级/新建/隔离裁决与装配顺序

1. **吸收**：稳定 session ID/locator、Resource envelope、EventBus capability schema、Provider model-ref、Task 状态集合、Plugin context 权限化、MCP stdio 的关闭升级链。这些有直接源码和测试命名证据。
2. **升级**：统一 capability registry/caller；统一 provider/HTTP/MCP/CLI/process supervisor；把 TaskRegistry 的状态 owner 与实际 runner 绑定；为 plugin full-access、worker/PTY、store watcher 增加崩溃租约和残留审计；将所有持久 store 的 close/migrate/recovery 纳入运行核心。
3. **模块化落点**：会话、工具、模型、插件、资源、Bridge、媒体和计划任务保留为模块库流程；模块只能调用支持库公开能力，不能互相读取对方私有 Map、直接调用第三方 SDK 或旁路写 `HANA_HOME`。
4. **支持库新建候选**：`CapabilityContract`、`ResourceHandle`、`ExecutionLease`、`ProcessSupervisor`、`StoreLifecycle`、`ExternalCallResult` 六组原子契约；是否新建须先查平台现有能力目录，当前任务没有目标平台能力目录证据，因此仅登记候选，不落生产代码。
5. **隔离**：`HanaEngine`、Pi SDK session workflow、人格/记忆 prompt、Heartbeat/Cron 业务规则、Bridge 频道语义和 UI 交互不作为通用底座事实；只通过适配层接入底座能力。
6. **装配波次**：先冻结公共契约和 owner → 接入句柄/租约/取消/释放 → 接入 store/process supervisor → 迁移 session/task/tool/model/plugin/resource 模块 → 最后接 REST/WS/CLI/插件网关；任何缺 L2 资源回读或 L3 外部实测的能力不得进入发布。

本第三轮结论是**底座升级输入，不是生产改造批准**：未修改 HanaAgent 源码、依赖、配置、测试或 Git；后续若要把上述候选能力落到系统工程平台，必须另开能力需求、复用检索、租约占用、验收契约和非重叠工作包。

---

## 第四轮：入口、路由、工具、事件与后台执行的源码事实

### 4.1 证据分层

本节是对当前工作树的静态源码研究，不是运行报告。为避免把“文件存在”误写成“行为已通过”，结论分为三类：

- **源码事实**：本轮直接读取的实现文件中可以定位到的控制流、状态、持久化路径或默认值。
- **测试存在**：当前工作树存在相关测试文件或测试策略声明，只能证明测试意图/覆盖入口存在。
- **未运行验证**：本轮没有安装依赖、启动 Server/Electron、调用真实 Provider/MCP/Bridge，也没有运行 Vitest、typecheck 或 lint；因此不对本机运行结果、测试通过率或外部服务可用性作结论。

### 4.2 完整入口链

**源码事实**：

1. `package.json` 的包入口是 `desktop/bootstrap.cjs`，CLI bin 是 `cli/entry.ts`；`npm run server` 通过 `scripts/launch.js server` 进入 Server 模式。
2. `server/main-full.ts` 是当前完整产品的薄入口：正常分支静态导入 `startServer`、闭集路由和内置媒体适配器，然后调用 `startServer({ registerClosedRoutes, builtinMediaAdapters })`。仅当 `HANA_INTERNAL_STANDALONE_RUNTIME_SMOKE=1` 时执行打包独立运行时探针。
3. `server/index.ts:startServer()` 设置并规范化 `HANA_HOME`，执行首次运行和本地身份准备，创建 `HanaEngine`，初始化网络/认证/HTTP/WebSocket 边界，注册开放路由，再创建 `Hub` 并接通任务、延迟结果、Loop 等 bus handler；最终通过 Hono + `@hono/node-server` + `ws` 提供 REST/WS。
4. Electron 的 `desktop/bootstrap.cjs`/`desktop/main.cjs` 负责桌面壳、Server 子进程和 IPC/窗口；桌面与 Server 没有以 IPC 传递业务会话，Server 就绪信息写入 `HANA_HOME/server-info.json`，桌面端轮询该文件。
5. `Hub` 与 `HanaEngine` 在同一 Node 进程内运行。`Hub.send()` 是统一消息入口，按顺序区分桌面 owner、Bridge guest、Bridge owner、ephemeral 后台执行等路径；路由命中后直接调用 Engine 或隔离执行方法。

**测试存在**：`tests/startup-contract.test.ts`、`tests/server-port-ownership.test.ts`、`tests/cli-local-server.test.ts`、`tests/cli-server-runner.test.ts`、`tests/build-server-artifact.test.ts`、`tests/standalone-server-smoke.test.ts`、`tests/desktop-onboarding-completion.test.ts` 等文件存在；`tests/README.md` 将启动、构建和平台行为归入 contract/build/platform 层。

**未运行验证**：上述测试没有在本轮执行；`node_modules`、构建产物、端口占用和 Electron/原生 helper 的当前状态没有据此确认。

### 4.3 模型路由与调用边界

**源码事实**：

- `ModelManager.init()` 从 `${HANA_HOME}/auth.json` 创建 Pi SDK `AuthStorage`，加载 `ProviderRegistry`，把 Provider Catalog 投影同步到 `${HANA_HOME}/models.json`，创建 Pi `ModelRegistry` 和 `ExecutionRouter`。
- `ProviderRegistry` 合并内置/用户/插件 Provider 声明与用户配置，规范化 chat/media 能力、模型、认证来源、headers、thinking level 和模型默认值；配置错误会保留为运行时元数据而不是直接把任意输入当成合法 Provider。
- `ModelManager.refreshAvailable()` 从 Pi ModelRegistry 取得模型，再按 Provider Catalog projection/allow-list 过滤，叠加已知模型 metadata 和持久化 thinking level，最终写入 `_availableModels`。源码明确把 `_availableModels` 作为模型解析的唯一真理源。
- `ExecutionRouter` 只负责角色到执行参数的解析，不负责注册模型。角色包括 `chat`、`utility`、`utility_large`、`embed`；它从 Agent 配置/全局 preferences 解析 `provider/model`，再查 Provider 凭证，返回 model/provider/api/apiKey/baseUrl/headers 等调用参数。utility 可有独立 API 覆盖，但会校验 provider 一致性。
- `Agent`/`SessionCoordinator` 将人格、工作区指令、记忆、Skills、工具 catalog、权限模式以及模型执行配置组装进会话；文本/审批等 utility 调用经过 `callText` 和模型执行配置边界，不由 HTTP 路由直接拼第三方请求。

**测试存在**：`tests/model-sync.test.ts`、`tests/model-sync-routes.test.ts`、`tests/session-switch-model.test.ts`、`tests/provider-compat.test.ts`、`tests/provider-compat-payload-snapshots.test.ts`、`tests/cache-prefix-contract-drift.test.ts`、`tests/provider-media-capabilities.test.ts`、`tests/media-model-catalog.test.ts`、`tests/oauth-force-refresh.test.ts` 等文件存在。

**未运行验证**：没有读取或使用本机 `${HANA_HOME}` 的真实凭证、Provider Catalog、模型清单或网络响应；不能据此断言某个具体模型可用、凭证有效、Provider 请求成功或缓存前缀在运行中保持稳定。

### 4.4 工具装配与延迟 catalog

**源码事实**：

- `core/agent.ts` 持有工具实例并在运行时组装：记忆搜索、网页搜索/抓取、todo、automation、文件与 SessionFile、频道、浏览器、computer-use、pinned memory、experience、Skill 安装、通知、设置、session folders、subagent、deferred result、Loop、任务停止、状态、workflow、卡片和 session 工具等。
- `core/engine.ts` 的 `buildTools()`/Agent 回调将基础工具、插件工具、MCP 工具、自定义工具和权限/checkpoint wrapper 合并到会话执行上下文；实际工具集合随 Agent、workspace、permission mode、插件和 session 状态变化。
- `core/tool-catalog.ts` 是纯内存、无 I/O 的延迟工具目录。每个 entry 保存名称、短描述、参数摘要、server/source、是否可延迟和 `schemaRef` 闭包，不保存完整参数 schema；来源可为 `builtin` 或 `mcp`，按 BM25 风格轻量评分并支持 manifest 分层输出。
- 目录按 source slice 注册/替换/删除，查询只返回 descriptor/hit；模型需要细节时再通过 bridge/工具路径取得 schema。工具目录评分不使用 server label/provenance 作为额外权重。
- 工具调用不是无条件执行：`lib/permission/tool-invocation-permission.ts`、`core/capability-policy.ts`、checkpoint/approval 相关扩展共同决定 capability、session permission、审批和执行边界；MCP stdio/HTTP 连接由 `core/mcp/` 适配。

**测试存在**：`tests/tool-availability.test.ts`、`tests/agent-config-tools-disabled.test.ts`、`tests/resource-io-materialize-tool.test.ts`、`tests/subagent-tool-policy.test.ts`、`tests/exec-command-policy.test.ts`、`tests/loop/loop-control-tool.test.ts`、`tests/workflow-tool.test.ts`、`tests/tool-catalog.test.ts`、`tests/plugin-ui-capabilities.test.ts` 等文件存在。

**未运行验证**：没有执行真实模型工具调用、MCP server discovery、插件加载或 OS computer-use；测试文件存在不等于工具 schema、权限拒绝、取消和资源释放在当前环境全部通过。

### 4.5 事件、Hub 与流式输出

**源码事实**：

- `Hub` 构造 `EventBus`、`ChannelRouter`、`GuestHandler`、`Scheduler`、`DmRouter`，再通过 `engine.setHubCallbacks()` 和 `engine.setEventBus()` 注入 Engine；Hub 是同进程调度/接线中枢，不是独立消息队列。
- `EventBus` 有全局订阅索引和按 `sessionPath` 的订阅索引，订阅还可按 event type 过滤；回调异常只记录日志，不阻断其他订阅者。`unsubscribe` 会同时清理两个索引。
- EventBus 同时提供 request/handle 模式：handler 顺序尝试，第一个非 `EventBus.SKIP` 结果返回；无 handler 抛 `BusNoHandlerError`，默认 30 秒超时抛 `BusTimeoutError`。超时是 `Promise.race`，源码本身没有证明底层 handler 会自动停止，因此取消传播仍由具体 handler/AbortSignal 负责。
- 能力目录由 `EventBusCapabilityDirectory` 维护，handler 可伴随 capability 注册和卸载；`get/listCapabilities` 会把 handler 是否当前可用投影到结果。
- Pi SDK 会话事件由 Engine/SessionCoordinator 发出，Hub/EventBus 接收后由 Server WS 以 session identity、stream id 和 seq 向客户端广播；WS 协议支持 prompt、interject、abort、resume_stream、compact 等输入，流恢复依赖服务端事件/序号状态。

**测试存在**：`tests/event-bus.test.ts`、`tests/event-bus-capabilities.test.ts`、`tests/event-bus-request.test.ts`、`tests/hub-agent-config-handlers.test.ts`、`tests/session-stream-store.test.ts`、`tests/ws-protocol.test.ts`、`tests/ws-auth.test.ts`、`tests/resource-events-ws.test.ts` 等文件存在（以当前目录命中为准）。

**未运行验证**：没有启动 WebSocket 客户端或进行断线/恢复/并发订阅实测，不能把事件序号连续性、重放边界或网络断开后的资源释放写成已通过。

### 4.6 持久化布局与恢复

**源码事实**：

| 领域 | 当前实现与主要位置 | 事实状态 |
|---|---|---|
| Agent/人格/记忆 | `<HANA_HOME>/agents/<id>/config.yaml`、`memory/*.md`、`memory/facts.db`、`memory/summaries/`；`Agent` 由 `id` 派生目录和 session/desk 路径 | 源码事实；`FactStore` 使用 SQLite/FTS5，memory ticker/summary 负责派生状态 |
| 会话正文 | `<agentDir>/sessions/*.jsonl`；`core/session-jsonl-file.ts` 校验首条 session 记录、读取/序列化、超长行修复并保留 repair 备份 | 源码事实；没有运行读写/修复演练 |
| 会话身份 | Session Manifest SQLite 的 `session_manifests`、locator history、capability snapshots、executor metadata、branch heads | 源码事实；WAL、schema migration、locator 解析和关闭路径在 `core/session-manifest/store.ts` |
| 文件与资源 | SessionFile sidecar `*.jsonl.files.json`、`session-files/` cache、Resource envelope、资源票据和 resource-io | 源码事实；远程边界会脱敏 `filePath/realPath`，内容 ticket 使用 HMAC + TTL |
| Provider/偏好/用量 | `auth.json`、`models.json`、`providers/`、`user/preferences.json`、`usage-ledger.json` | 源码事实；真实文件内容取决于运行时 HANA_HOME，当前未读取 |
| Cron/任务/Loop | Studio Cron jobs/runs 文件、`.ephemeral/plugin-tasks.json`、LoopStore JSON；写入使用原子替换或恢复文件 | 源码事实；恢复分支和损坏文件处理存在，但没有本轮重启实测 |

`SessionManifestStore` 显式启用 SQLite WAL、创建 schema 并按 user_version 迁移；构造失败会尝试关闭数据库并重新抛出原始错误。`CronStore` 对主文件缺失/损坏和 `.tmp` 恢复有备份与错误码路径；`LoopStore` 对损坏 JSON 会重命名为 `.corrupt-<timestamp>` 后以空态启动，而不是静默覆盖现场。上述是实现设计，不代表故障恢复已在本机验证。

### 4.7 队列、心跳、Loop 与任务

**源码事实**：

- `Scheduler` 启动每个启用 desk Agent 的独立 Heartbeat、一个 Studio 级 CronScheduler 和 fresh-compact daily scheduler；Heartbeat 不依赖当前焦点 Agent，Cron 也不随 active agent/workspace 切换。
- `lib/desk/heartbeat.ts` 的巡检分为工作区文件差量检测和根目录/一级子目录 `jian.md` 扫描；活动输出目录被排除，巡检通过隔离 Agent session 执行并写 patrol/jian 状态日志。Heartbeat 默认是定时器，不是持久消息队列。
- `lib/desk/cron-scheduler.ts` 每 60 秒检查到期 job。确定性调度层不调用 LLM，只有 `executeJob` 回调才创建 Agent session；单次执行默认 20 分钟超时，超时调用 `abortJob`，成功/失败分别推进 run cursor 并写运行历史，同一检查批次会重新读取 job 以避免使用过期配置。
- `CronStore` 持久化 job、schemaVersion、configRevision、nextRunAt 和 runs；支持 `at`、`every`、`cron` 语义，失败有退避表，启用 Agent automation 时必须有 prompt，执行器当前只接受 `agent_session`。
- `TaskRegistry` 的 handler 函数只在内存中，任务和 schedule 元数据可写 `.ephemeral/plugin-tasks.json`。状态集合包含 `pending/running/paused/blocked/recovering` 和 `completed/failed/canceled/aborted`；注册 handler 必须提供 `abort(taskId)`，启动时加载持久任务并重新 arm 可恢复 schedule。没有 handler 时任务可登记但不能得到 abort 支持，持久化写失败主要记录 warning。
- Loop 不是普通 Cron：`LoopStore` 以 `sessionId` 为唯一键原子持久化，默认最多 50 轮、连续失败 3 次暂停、最小延迟 60 秒、守护/兜底延迟 1200 秒；`LoopController` 通过 turn_start/message_end/turn_end 记账，在没有 alarm 且没有活跃后台工作时补兜底 alarm，启动恢复时为仍运行但没有 alarm 的 Loop 重新布置唤醒。
- 这些机制使用定时器、AbortController、文件状态和事件 bus 组合，不是独立的通用持久化队列服务；进程崩溃时能恢复的是各自落盘状态，内存 handler、正在运行的 Promise、AbortController 和外部进程仍需具体 supervisor/adapter 重新建立。

**测试存在**：`tests/scheduler-heartbeat-default.test.ts`、`tests/loop/alarm-service.test.ts`、`tests/loop/loop-controller.test.ts`、`tests/loop/loop-messages.test.ts`、`tests/loop/loop-store.test.ts`、`tests/loop/loop-bus-handlers.test.ts`、`tests/loop/task-registry-active-query.test.ts`、`tests/task-registry.test.ts`、`tests/cron-store.test.ts`、`tests/cron-scheduler.test.ts`、`tests/workflow-integration.test.ts` 等文件存在。

**未运行验证**：没有等待真实分钟级调度、强杀进程、重启恢复、外部任务取消或检查残留 PID/定时器；不能把“有恢复代码/测试文件”表述成队列至少一次/至多一次语义、任务不重复执行或崩溃一致性已经验证。

### 4.8 测试存在性与本轮验证结论

**源码事实**：`tests/README.md` 定义了 `contract`、`regression`、`unit`、`route`、`build`、`platform` 六类风险驱动测试，并要求清理工作至少运行 `npm test`、`npm run typecheck`、`npm run lint`。`package.json` 的 `test` 使用 Vitest，`typecheck` 执行三套 TypeScript 检查，`lint` 执行 ESLint。

**测试存在**：当前工作树中存在入口、模型/provider、工具权限、EventBus/WS、manifest/JSONL、memory、Cron/Heartbeat/Loop、插件、Bridge、资源和平台边界等大量测试文件；文件名可用于定位测试意图，但不代表每个测试都被本轮运行。

**未运行验证**：本轮严格按任务要求只做源码/测试文件读取和文档编辑；没有调用 MCP/Hermes，没有安装依赖，没有运行任何测试、lint、typecheck、Server、Electron、CLI、Provider、MCP、Bridge 或真实心跳/任务。因而本轮交付状态是“静态事实已整理，动态验证未执行”。

### 4.9 本轮研究范围与文件边界

本轮只修改项目根 `ARCHITECTURE.md`。读取重点包括 `package.json`、`server/main-full.ts`、`server/index.ts`、`hub/index.ts`、`hub/event-bus.ts`、`hub/scheduler.ts`、`core/engine.ts`、`core/agent.ts`、`core/model-manager.ts`、`core/provider-registry.ts`、`core/execution-router.ts`、`core/tool-catalog.ts`、`core/session-manifest/store.ts`、`lib/task-registry.ts`、`lib/desk/heartbeat.ts`、`lib/desk/cron-scheduler.ts`、`lib/desk/cron-store.ts`、`lib/loop/loop-controller.ts`、`lib/loop/loop-store.ts`、`tests/README.md` 以及相关测试文件清单。没有修改源码、配置、依赖锁、测试或构建产物。

---

## 第五轮：全项目状态、资源与恢复审计（2026-08-21）

### 5.1 审计边界与证据等级

本轮按“入口 → 关系 → 运行面 → 持久化 → 调度/任务 → 测试/文档”分段读取当前工作树，目标是补齐前几轮文档中的状态与资源结论，而不是重复描述产品功能。

- **代码图状态**：目标仓库没有 `.codegraph/`；在仓库根执行 `codegraph explore "project entrypoints, Electron CLI server hub engine provider tools events JSONL SQLite cron task tests docs architecture"` 返回索引不存在。因此本轮不能提供 CodeGraph 节点/调用边证据，入口关系改由 `package.json`、入口文件的静态 import、组合根和路由注册源码核对；不能把全文搜索结果冒充代码图关系。
- **工作区状态**：基线分支为 `main`，HEAD 为 `c6d0405 chore(release): prepare v0.447.4 digest`。本轮开始时仅发现根 `ARCHITECTURE.md` 为未跟踪文件；本轮只更新该文件，未修改源码、配置、锁文件、测试或构建产物。
- **源码事实**：来自本轮实际读取的文件和静态关系；可说明实现意图、状态字段、边界和清理路径。
- **测试存在**：仅说明测试文件/测试策略存在，不说明测试通过。
- **未运行验证**：本轮没有安装依赖、启动服务、运行 Electron/CLI、连接 Provider/MCP/Bridge、等待 Cron/Heartbeat，也没有运行 Vitest、typecheck 或 lint；动态状态不能写成通过。

### 5.2 入口与关系核对

```text
package.json main/bin/scripts
    ├─ Electron: desktop/bootstrap.cjs
    │    └─ desktop/main.cjs → spawn Server → server-info.json 轮询 → BrowserWindow/IPC
    ├─ CLI: cli/entry.ts
    │    ├─ hana serve → cli/server-runner.ts → server/main-full.ts
    │    ├─ chat/continue/status/sessions → HanaCliClient → HTTP/WS Server
    │    └─ bundle/data → 本地发行包与 data-epoch 维护面
    └─ server: scripts/launch.js → server/main-full.ts
         └─ startServer({ registerClosedRoutes, builtinMediaAdapters })
              ├─ HanaEngine.init() → Managers/Agent/Provider/Session/Plugin
              ├─ Hub → EventBus/ChannelRouter/DmRouter/Scheduler
              └─ Hono + @hono/node-server + ws → REST/WS routes
```

静态关系中最重要的边界有三条：

1. `server/main-full.ts` 是当前完整产品的薄组合入口；`server/index.ts` 本身导出 `startServer()`，不自举，也不直接导入闭集路由。
2. Electron 与 Server 通过独立 Node 子进程和 `HANA_HOME/server-info.json` 协作，业务会话走 HTTP/WebSocket，而不是 Electron IPC 直连 Engine。
3. `Hub` 和 `HanaEngine` 在同一 Server 进程内；`Hub.send()` 按桌面 owner、Bridge guest/owner、ephemeral 后台执行进行首个命中路由，后台调度不是独立消息队列。

### 5.3 运行组件与资源责任

| 运行对象 | 创建/拥有者 | 外部句柄 | 正常释放 | 当前恢复事实与缺口 |
|---|---|---|---|---|
| Server HTTP/WS | `server/index.ts:startServer()` | 监听 host/port、WS clients、`server-info.json` | graceful shutdown 中停止接受、dispose Engine/Hub 并清理状态 | 有同宅互斥、端口 fallback、stale server probe；本轮未实测端口、WS、强杀和重启残留 |
| Engine/Agent | `HanaEngine`、`AgentManager` | Agent runtime、FactStore、session runtime、插件贡献 | `Hub.dispose()` → `engine.dispose()`；Agent 并行 dispose | 有明确 dispose 链和初始化并发限制；跨进程并发只靠同宅闸，冷启动写 server-info 前存在源码注释明确承认的秒级竞态 |
| EventBus | `Hub` | subscriber id、handler、capability type | unsubscribe/unhandle/clear | sessionPath/global 索引会清理；request 超时使用 `Promise.race`，不能证明底层 handler 自动停止 |
| Cron/Heartbeat | `hub/Scheduler` | timer、per-job `AbortController`、heartbeat instance | stop heartbeat、stop cron、清理 executing map | job 有 per-job 锁、超时 abort、失败退避；定时器不是持久队列，崩溃时运行中的 Promise 不可恢复 |
| TaskRegistry | `lib/task-registry.ts` | `taskId`、schedule timer、内存 handler | complete/fail/cancel/abort、清 timer | 元数据可持久化，active 状态可进入 `recovering`；handler 仍是内存函数，写失败主要记录 warning，不能保证状态账本与实际 runner 一致 |
| Session JSONL | Pi SDK/`SessionCoordinator` | session file、stream runtime、execution AbortController | flush/rewrite、session teardown | 超长行投影、inline media 清理、`.repair.json` 备份已实现；本轮未做损坏文件、并发写、恢复追加演练 |
| Session manifest SQLite | `SessionManifestStore` | better-sqlite3 DB handle、WAL | 构造失败 close；Engine dispose 关闭 | WAL、schema migration、locator history、capability/executor/branch 快照有源码证据；本轮未实际打开 DB 或验证迁移回滚 |
| Plugin | `PluginManager` | plugin context、route/tool/provider/extension registrations、disposables | unload、逆序 disposable cleanup | 15 秒加载边界和 cleanup 存在；restricted/full-access 不是进程隔离，插件主进程崩溃隔离未解决 |
| MCP/PTY/native child | 对应 client/manager/provider | child process、stdin/stdout、PTY、pending request | EOF → SIGTERM → SIGKILL 或 handle.dispose | stdio client 有升级关闭链和 pending reject；本轮未检查真实进程组、pipe、临时目录和残留 PID |
| Resource/SessionFile | `SessionFileRegistry` + `ResourceAccessService` | `sf_*`、`res_sf_*`、HMAC ticket、watcher | sidecar/managed cache 写入、ticket 到期、watch dispose | 远程路径脱敏、ticket TTL、sidecar 原子替换存在；缓存 GC、watcher 崩溃恢复和删除/恢复全矩阵未动态核验 |

### 5.4 持久化与失败恢复结论

- **JSONL**：会话正文以行记录保存，首条必须是带 `id` 的 `session` 记录；解析时限制行大小、数组/对象规模和工具参数字符串，超限时先剥离 inline media，再投影字段并写入 `hanaRepair` 元数据。文件修复前保留 `${sessionPath}.repair.json`。这是“可读性优先的降级修复”，不是无损恢复，应在产品文档中明确提示用户。
- **SQLite**：`SessionManifestStore` 使用 WAL、`synchronous=NORMAL`、有限 cache/mmap，并在 schema 初始化/迁移失败时关闭句柄后抛出；Agent facts DB 另由 `FactStore` 负责。两个 SQLite owner 分离，当前未见统一 store supervisor 或跨 store 事务，因此不能把 manifest 与 facts 的一致性写成原子事务。
- **Cron JSON**：`CronStore` 对主文件缺失/损坏会读取 `.tmp`，必要时保留 `.corrupt-<timestamp>-<pid>-<attempt>.bak`，再原子 rename；同步 mutator 禁止 reentrant/async 写入。该恢复是文件级恢复，不等价于一次性 Cron 执行的 exactly-once 保证。
- **Activity JSON**：启动时把遗留 `running` 标为 `interrupted`，并可按执行超时标为 `timeout`；最多保留 100 条且会删除对应活动 session 文件。此处属于元数据回收策略，不能恢复已中断的模型调用。
- **Task/Loop**：TaskRegistry、LoopStore、CronStore 分别维护自己的状态和计时器；已有 `recovering`、失败退避、Loop alarm 重建等逻辑，但没有统一的持久 in-flight journal、全局幂等键或跨模块恢复协调器。崩溃恢复语义应记录为“恢复可调度元数据”，而非“恢复原 Promise”。
- **启动失败**：桌面 bootstrap 写 `launch-marker.json`、`launch.log` 和错误诊断；Server bootstrap 用独立 Worker keepalive 避免 native import 阻塞被 Electron 误判启动失败；server 启动前有 HANA_HOME 同宅互斥和 data epoch 闸。上述路径改善诊断与拒绝启动，但本轮未做故障注入。

### 5.5 Provider、工具和事件审计

- `ProviderRegistry` 是声明式 Provider 合并层，负责能力、协议、认证类型、模型和媒体能力规范化；`ModelManager` 的 `_availableModels` 是可用模型投影的唯一真理源；`lib/llm/provider-client.ts` 仅负责测试/健康探测 URL 和认证 header，真实文本调用由 `core/llm-client.ts` 经 Pi SDK 边界完成。
- Provider 配置错误会保留 `_config_error` 等运行时元数据；OAuth HTTP base URL 有 HTTPS/origin allow-list 校验；但真实凭证、模型列表、Provider 网络可达性均属于 `${HANA_HOME}`/外部环境，静态代码不能证明当前可用。
- `core/agent.ts` 组装内置工具，`PluginManager` 和 MCP 提供扩展工具，`core/tool-catalog.ts` 只保存轻量 descriptor 与 `schemaRef`，按 BM25 风格搜索并延迟加载 schema。工具可用性还受 session permission、capability、approval、checkpoint、sandbox 共同约束。
- `EventBus` 既承载广播订阅，又承载 request/handle 和 capability directory。它是进程内总线，不是持久事件日志；WS 的 stream `seq`/resume 由 Server 层维护，断线恢复不能推导为 EventBus 本身具备 durable replay。
- 事件订阅回调异常被记录而不阻断其他订阅者；request 默认 30 秒超时，但 `Promise.race` 不会自动取消已进入 handler 的副作用。所有长调用必须由具体 handler 绑定 AbortSignal 和 finally 清理，平台化时应把这一点升级为统一调用监督契约。

### 5.6 测试和文档质量

- 测试体系设计质量较高：`tests/README.md` 明确区分 contract、regression、unit、route、build、platform，并优先保护权限、凭证、资源、SessionFile、迁移、Provider、Bridge、插件和跨平台边界。当前测试树覆盖入口、Server/WS、Provider、工具权限、manifest/JSONL、Cron/Heartbeat/Loop、插件、资源、媒体和平台 helper 等主题。
- 文档质量的优点是 README 提供了运行面、数据目录、脚本、平台和安全能力摘要；`PLUGINS.md`/`PLUGIN_SDK.md` 提供扩展协议；`tests/README.md` 提供验证政策；本文件补充了源码级 owner、句柄和恢复边界。
- 文档质量的限制是 README 的“支持/已签名/已公证/可用”表述属于项目声明，不是本轮运行证据；`ARCHITECTURE.md` 中所有“源码事实”和“测试存在”都不能替代动态验证。当前仍存在 open/full composition、mobile-workbench、发行产物和具体 Provider 可用性需要构建或实机核对的边界。
- 本轮未发现应把不存在的 CodeGraph 索引、未运行测试或外部运行状态写成事实的依据；文档已显式保留这些限制。后续若仓库启用 `.codegraph/`，应重新生成入口节点/调用边证据并复核本文件，而不是仅追加文字。

### 5.7 当前风险分级与后续建议

| 优先级 | 风险 | 依据 | 建议验收 |
|---|---|---|---|
| P1 | TaskRegistry 状态与实际 handler 执行可能分离 | handler 仅内存；持久化写失败主要 warning；无统一 in-flight journal | 注入写失败、进程强杀、重启并核对 task 状态、实际副作用和幂等键 |
| P1 | full-access 插件在主进程内，异常隔离不足 | PluginManager cleanup 有边界但不是进程隔离 | 插件崩溃/超时/卸载测试，确认 Engine、route、provider、timer、child 全部收口 |
| P1 | EventBus 超时不自动停止 handler | `Promise.race` 只结束等待者 | 使用可观测副作用 handler 验证超时后取消、重复提交和终态记录 |
| P1 | 跨 store 一致性依赖模块级恢复 | facts、manifest、JSONL、cron/task 各自 owner/格式 | 设计统一恢复报告和读回校验，不把多个原子替换宣传为跨 store 事务 |
| P2 | 同一 HANA_HOME 冷启动存在 server-info 写入前竞态 | `server/index.ts` 注释明确承认秒级窗口 | 并发启动压力测试，确认端口、SQLite、server-info 和退出清理结果 |
| P2 | 资源 watcher/cache/外部 child 的残留需真实核验 | 源码有 cleanup，但本轮未启动和强杀 | L3/L4 验证进程树、端口、文件句柄、watcher、tmp、pipe 和 cache |
| P2 | 文档动态状态不可由源码推断 | 本轮未安装/未运行 | 在 CI 或发布流程记录命令、退出码、测试数、跳过项和实机平台矩阵 |

### 5.8 本轮交付边界

本轮只更新根 `ARCHITECTURE.md`，没有调用 MCP/Hermes，没有安装依赖，没有运行测试/lint/typecheck，也没有启动或修改 HanaAgent 运行数据。交付结论为：**入口、静态关系、资源 owner、持久化格式、失败恢复设计、调度/任务边界、测试意图和文档质量已完成静态审计；动态运行状态、故障注入、真实外部 Provider/进程和发布通过状态仍未验证。**
