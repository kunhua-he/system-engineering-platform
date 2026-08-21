# Elephant-Agent 架构取证

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│                    产品 / 运行时入口层（apps/）                              │
│  elephant CLI      API/WSGI      Gateway/IM      Daemon/Cron      Dashboard  │
│  apps.launcher     apps.api      apps.gateway    learning worker   Site/macOS│
└───────────────┬──────────────┬──────────────┬──────────────┬─────────────────┘
                │              │              │              │
                └──────────────┴──────┬───────┴──────────────┘
                                      ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                         Kernel / Capability 编排                              │
│  KernelService.run → 身份/PersonalModel/State 解析 → Episode → Loop → Step   │
│       │                 │                         │                           │
│       │                 ├──────── ContextRuntime / Prompt projection          │
│       │                 ├──────── RecallRuntime / UnifiedRecall              │
│       │                 ├──────── ModelProvider / ToolRuntime                │
│       │                 └──────── Telemetry / Security / Skills              │
│       ▼                                                                      │
│  execute_kernel_turn：模型生成或工具循环 → ExecutionResult → 状态刷新         │
└───────────────┬───────────────────────┬───────────────────────┬──────────────┘
                │                       │                       │
                ▼                       ▼                       ▼
┌──────────────────────┐   ┌────────────────────────┐   ┌──────────────────────┐
│ packages/contracts   │   │ packages/storage       │   │ packages/evidence   │
│ PM/State/Episode/    │──▶│ SQLite schema +        │◀──│ Step/Episode/Fact    │
│ Loop/Step/Fact/Path  │   │ RuntimeStorageRepository│   │ indexing + recall    │
└──────────┬───────────┘   └────────────┬───────────┘   └──────────┬───────────┘
           │                            │                          │
           │                            ▼                          ▼
           │                  ┌──────────────────┐       ┌────────────────────┐
           │                  │ durable records  │       │ sqlite-vec +       │
           │                  │ PM/State/trace/  │──────▶│ lexical/hybrid     │
           │                  │ jobs/Paths       │       │ semantic search     │
           │                  └────────┬─────────┘       └─────────┬──────────┘
           │                           │                           │
           └───────────────────────────┴──────────────┬────────────┘
                                                      ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                  Background Learning / Reflect（packages/reflect）             │
│ learning_jobs(trigger) → resolve_features → evidence packet + prompt         │
│ → run_sub_agent → governed tools (PM update/questions/diary/skill draft)      │
│ → result_json / Personal Model facts & questions / next-turn prompt projection │
└──────────────────────────────────────────────────────────────────────────────┘
```

# Elephant-Agent 架构文档

## 项目定位

Elephant Agent 是一个以 Personal Model（个人模型）为核心、CLI 优先且支持持久化的个人 AI 运行时。产品目标不是把所有历史内容堆成“记忆表”，而是通过可纠正的 Personal Model、Elephant State、Episode/Loop/Step 执行轨迹、可解释召回和后台学习，逐步理解用户并帮助用户推进长期 Path。

README 将产品入口分为两类：推荐的 macOS 桌面应用，以及 Linux/云端的 CLI + Dashboard。源码中的稳定技术主干是 Python `apps/` 入口和 `packages/` 运行时包；前端、网关、守护进程和平台壳负责把同一套包级事实投影到不同表面。

当前设计的权威说明是 `docs/system-design/system-layer-model.md`。该文明确把以下对象作为核心事实：Personal Model、Fact、Question、Elephant State、Episode、Loop、Step、SemanticIndexEntry 和 LearningJob；Steps 是原始证据，Fact 通过 `source_episode_ids` 保留来源，不再以独立 Memory/Evidence/Record 表承载 Personal Model 真相。

## 真实目录/分层与职责

以下目录按当前磁盘实际结构整理，而不是只复述 README 中的示意树。

### 入口与应用层：`apps/`

- `apps/launcher.py`：Python console script `elephant` 的统一 Typer 启动器；初始化默认 state 目录和配置文件，把大多数命令转发给 CLI、网关、Cron、Dashboard、Reflect 等子入口。
- `apps/cli/`：主用户交互面。`cli_main_impl.py` 注册 `init`、`status`、`wake`、`provider`、`herd`、`facts`、`reflect`、`sandbox`、`rtk` 等命令；shell 使用 `prompt_toolkit` 输入和 `rich` 渲染。
- `apps/api/`：程序化 API/本地 WSGI 服务。HTTP 路由、请求响应转换、控制台和 Dashboard 投影在此；核心认知仍委托给 packages。
- `apps/gateway/`：消息入口与投递编排，包含 Discord、Telegram、Feishu、DingDing、Weixin、WeCom、Webhook/Chat Bot 等适配器，以及 gateway runtime factory。
- `apps/daemon.py`、`apps/daemon_command.py`、`apps/daemon_http.py`、`apps/daemon_tasks.py`：统一守护进程、HTTP 服务、网关/Cron/学习 worker 的进程生命周期。
- `apps/learning_worker_runtime.py`、`apps/learning_worker_command.py`、`apps/learning_agents/`：后台学习 worker 的兼容和进程接入层；学习逻辑的主实现位于 `packages/reflect/`。
- `apps/dashboard/`：Vite + React 的本地运行时检查控制台，调用 API，不拥有运行时真相。
- `apps/site/`：Docusaurus 公共站点、产品文档和发布内容；是静态/内容优先表面，不承担运行时认知。
- `apps/macos/`：Swift/AppKit/SwiftUI 桌面壳和打包脚本，负责本地桌面产品表面与 Python/API 运行时的启动连接。
- `apps/reflect/`：对 `packages.reflect` 的兼容导入 facade，不再拥有 Reflect runner 和 feature 的核心实现。
- 其它根级 app 支持文件（`provider_runtime.py`、`runtime_layout.py`、`episode_runtime.py`、`cron_scheduler_command.py`、`dashboard_command.py` 等）负责组装进程、路径、配置和表面生命周期。

### 可复用运行时层：`packages/`

`packages/AGENTS.md` 规定包应可被多个 app 复用、依赖方向显式，并优先通过 `contracts/` 与 `capabilities/` 集成。

- `packages/contracts/`：低依赖、无副作用的共享契约和不可变 dataclass。`layers.py` 定义 `PersonalModel`、`State`、`Episode`、`Loop`、`Step`；`personal_model.py` 定义 `Fact`、`OpenQuestion`、`DiaryEntry`；`paths.py` 定义 Path 及其 Step/Run/Comment/LearningSummary/UnderstandingCheck；`runtime.py` 还定义模型选择、Recall、Context、Execution、checkpoint 和等待/重试记录。
- `packages/kernel/`：规范运行时生命周期。负责事件摄取、默认 PersonalModel/State 解析、Episode/Loop/Step 编排、Context/Recall/Model/Tool 调用、状态持久化、学习触发和 telemetry。入口是 `runtime_impl.py` 的 `KernelService`，对外从 `packages/kernel/__init__.py` 导出。
- `packages/state/`：Personal Model/State 的加载、治理、文件投影和 Prompt contract。`canonical.py` 生成 elephant identity、user profile、relationship 投影；`profile_from_claims.py` 说明渲染 profile 来自 active PM facts，而不是另一个真相源。
- `packages/context/`：热/稳/冷上下文策略、token budget、检索调度、摘要、压缩和 Prompt rendering；保持上下文组装可重复、可检查。
- `packages/evidence/`：Step/Episode/Fact 的证据化、RecallRuntime、统一召回、重排、时间范围、Episode/Fact/Step/Diary/LearningSummary 的索引文本和 resume packet。
- `packages/semantic_index/`：语义索引协议、`SQLiteVecSemanticIndex`、索引服务和 HybridSemanticSearcher。索引 bundle 从运行时 state 目录派生同一物理文件，避免生产端和消费端使用不同索引。
- `packages/storage/`：SQLite 持久化、干净 schema bootstrap 和 repository 方法。`repository_impl.py` 组合 system、curiosity、learning、Path、checkpoint、auth、semantic index 等方法。
- `packages/models/`：provider-neutral 模型契约、provider catalog/discovery、OpenAI/Anthropic/OpenAI-compatible 等适配器和响应解析；provider-specific auth 由 `packages/auth/` 配合。
- `packages/embeddings/`：embedding provider/service 和向量形状；被 evidence/semantic_index 使用。
- `packages/tools/`：工具注册、schema、执行、审批、MCP、浏览器、文件/终端/代码等能力；通过 capability/requester 约束模型可见范围。
- `packages/skills/`：内置和扩展 Skill catalog、加载、启停、搜索和 skill shelf；Skill 进化候选由 Reflect 产生并等待显式批准。
- `packages/capabilities/`：包间能力描述和运行时 capability protocol。
- `packages/auth/`：provider credential/profile、加密 secret store、环境变量和持久化凭据解析。
- `packages/reflect/`：后台反思/学习的 feature registry、证据包、提示片段、轨迹信号、候选聚合和 runner。
- `packages/understanding/`：Personal Model 的搜索、更新、治理和语义索引写回面；foreground PM 工具使用它而非直接操作数据库。
- `packages/curiosity/`、`packages/growth/`、`packages/experience/`、`packages/continuity/`：主动问题、成长指标、体验轨迹、跨 Episode 连续性等领域运行时。
- `packages/gateway_core/`：与具体平台无关的身份映射、会话、入站/出站消息、投递队列和 proactive ask 基础设施。
- `packages/cron/`：计划任务运行时；`packages/operator/`：Typer、shell、daemon、wizard 等 app-neutral 操作支持。
- `packages/security/`、`packages/sandbox/`：安全策略、审批分类和本地/Docker/远端 SDK 等执行隔离后端。
- `packages/observability/`、`packages/telemetry/`：结构化日志、trace、metrics 和 OpenTelemetry 接入。
- `packages/runtime_config.py`、`packages/runtime_layout.py`：全局配置与 state/install 路径布局。

### 持久化与部署层

- `packages/storage/schema.sql`：当前 SQLite 终态 schema，包含 PM/State/episodes/loops/steps、semantic index、learning jobs、Path 体系、facts/questions/diary、growth、identity 等表。
- `deploy/docker/`、`deploy/systemd/`、`deploy/cloud/`：容器、systemd 和云部署配置；`install.sh`、`scripts/install.sh`：安装入口。
- 根 `Makefile` 和 `tools/agent/`：测试、构建、发布和 agent harness 的可执行契约；不是产品 cognition 层。

### 测试层：`tests/`

- `tests/unit/`：包级快速测试，且各热点目录有本地 `AGENTS.md`。
- `tests/integration/`：跨包行为，重点覆盖 kernel 生命周期、storage schema/repository、models/auth、semantic index、tools/skills、security/observability、Reflect。
- `tests/e2e/`：API、CLI、Gateway、deploy、release 的应用级表面测试。
- `tests/scenarios/`：连续性、上下文、companion 等产品论点/纵向场景；`tests/scenarios/continuity/` 明确覆盖时间间隔恢复、中断工作、召回恢复、可解释下一步、State 连续性、纠正感知恢复和 refocus。
- `tests/agent/`：仓库 agent harness 契约测试。

## 核心数据流

1. **入口组装**：`apps.launcher` 或 `apps.api`/`apps.gateway` 读取 state/config，创建 `RuntimeStorageRepository`，加载 profile/identity，组装 Context、Recall、Model、Tool、Skill、Telemetry 和安全 capability。Gateway 的组合根是 `apps/gateway/runtime_factory.py::build_gateway_app`。
2. **身份与作用域解析**：Kernel 根据请求的 profile/surface/route 与 storage 中的 PersonalModel、State、Episode 解析 `personal_model_id`、`state_id`、`episode_id`、`loop_id`；单用户默认 PersonalModel 的 canonical id 由 storage 支持层处理。
3. **Episode/Loop/Step 记录**：`KernelService.run` 打开或复用 Episode/Loop，先用 `KernelStepRecorder` 写 observation 的输入 Step，再写 context assembly、model/tool call、reflect、state persistence 等 reasoning/acting Step。`Step` 同时是执行审计和后续召回证据。
4. **召回与上下文**：`RecallRuntime.retrieve` 通过 `unified_recall` 查询 Steps/Episodes；有可用 embedding 时走 HybridSemanticSearcher 的向量、词法和精确/字符信号融合，否则回退到 token/CJK lexical ranker。召回结果进入 `ContextRuntime.assemble` 生成 `ContextBundle` 和 `PromptEnvelope`。
5. **生成或工具循环**：`execute_kernel_turn` 根据请求走直接工具调用，或调用 model provider，再根据模型返回的 tool calls 继续工具循环；最终统一为 `ExecutionResult`，记录 token usage、tool calls、side effects 和 outcome。
6. **状态投影与收尾**：Kernel 将执行结果投影为新的 State，持久化 State/Loop/Step，并在 Episode 关闭、checkpoint 或失败时按触发器入队 `LearningJob`。`Episode.parent_episode_id` 和 `interruption_state` 支持下一 Episode 及 lineage 恢复。
7. **索引生产/消费闭环**：`SemanticSummaryIndexer` 为关闭 Episode、Step、active Fact、LearningSummary 和 DiaryEntry 生成索引文档；`SemanticIndexService` 先写 `semantic_index_entries` 元数据，再写 SQLite-vec 向量。`build_semantic_index_bundle` 固定使用 `<state_dir>/semantic-index/sqlite-vec.sqlite3`，Recall 读取同一 bundle。
8. **后台学习**：Learning worker 领取 LearningJob；`packages.reflect.features.resolve_features` 按 trigger（如 `episode_close`、`manual`、`dream`、`context_compaction`）确定 feature，`run_reflect_agent` 组装 evidence/system prompt/tool 白名单并调用 `runtime.run_sub_agent`。子 agent 通过受治理工具更新 Fact、Question、Diary 或产生待审批 Skill draft，结果写回 `learning_jobs.result_json`。
9. **对外投影**：API 将 Episode、Loop、Step、Recall、State、identity/user/relationship/continuity、Path 和审批状态序列化；Dashboard 只检查这些 API/package 契约；CLI/Gateway/macOS 复用同一运行时事实。

## 关键类/函数/数据模型及相对路径

### 规范领域模型

- `PersonalModel`、`State`、`Episode`、`Loop`、`Step`：`packages/contracts/layers.py`。关系为 `PersonalModel → State → Episode → Loop → Step`，Episode 可通过 `parent_episode_id` 形成 lineage。
- `Fact`、`OpenQuestion`、`DiaryEntry`：`packages/contracts/personal_model.py`。Fact 具备四 lens（identity/world/pulse/journey）、confidence、source、status 和 `source_episode_ids`；只有 active Fact 进入稳定 Prompt。
- `PathRecord`、`PathStepRecord`、`PathStepRunRecord`、`PathStepCommentRecord`、`LearningSummaryRecord`、`UnderstandingCheckRecord`：`packages/contracts/paths.py`。它们是长期 Path/Step 协作层，位于 Episode/Loop/Step 执行轨迹之上。
- `LearningJob`、`ContextBundle`、`PromptEnvelope`、`ExecutionResult`、`EvidenceRetrievalRequest/Result`、`LoopState`、`WaitCondition`、`PendingToolCall`：`packages/contracts/runtime.py`。
- `SemanticIndexEntry` 及契约清单：`packages/contracts/inventory.py`；索引 metadata 的表结构在 `packages/storage/schema.sql`。

### 核心编排

- `KernelService.run(request)`：`packages/kernel/runtime_impl.py`。主流程为 identity → lifecycle → ingest → resolve → recover → context → execute → persist → learning/close。
- `execute_kernel_turn(...)`：`packages/kernel/execution_support.py`。决定 model/tool 路径，负责模型返回后的工具循环和 Step 记录。
- `open_episode_lifecycle`、`open_loop_lifecycle`、`close_episode_lifecycle`：`packages/kernel/lifecycle_support.py`。
- `close_episode`、`open_next_episode`：`packages/kernel/episode_state_machine.py`。
- `RuntimeStorageRepository`：`packages/storage/repository_impl.py`；bootstrap 在 `packages/storage/repository_bootstrap_methods.py::bootstrap`，system records 在 `repository_system_methods.py`，Fact/Question/Diary 在 `repository_curiosity_methods.py`，LearningJob 在 `repository_learning_methods.py`，checkpoint 在 `repository_loop_checkpoint_methods.py`。

### State、召回、索引与模型

- `build_canonical_profile_state`、`build_elephant_identity_record`、`build_user_profile_projection`、`build_relationship_projection`：`packages/state/canonical.py`。
- `derive_profile_from_claims`、`render_profile_text_from_claims`：`packages/state/profile_from_claims.py`。
- `RecallRuntime.retrieve`、`RecallRuntime.retrieve_evidence`：`packages/evidence/recall_runtime.py`；`StepEvidenceStore` 把 canonical Step 转成只读 RecallEvidence，禁止单独持久化 RecallEvidence。
- `unified_recall`：`packages/evidence/unified_recall.py`；`SemanticSummaryIndexer`：`packages/evidence/episode_summary_indexer.py`。
- `build_semantic_index_bundle`：`packages/evidence/semantic_index_factory.py`；`SemanticIndexService.index_document`：`packages/semantic_index/service.py`；`SQLiteVecSemanticIndex`：`packages/semantic_index/backend.py`。
- `ModelAdapter`、`ModelRequest`、`ModelTextResult`、`PreviewModelProviderCapability`：`packages/models/runtime.py`；真实 provider 适配器选择入口 `build_model_adapter` 在 `packages/models/providers/factory.py`。
- `Feature`、`ALL_FEATURES`、`TRIGGER_FEATURES`、`resolve_features`：`packages/reflect/features/types.py` 与 `packages/reflect/features/__init__.py`；`run_reflect_agent`：`packages/reflect/runner.py`。

## API/CLI/SDK入口

### CLI

- 安装脚本入口由 `pyproject.toml` 声明：`elephant = "apps.launcher:main"`。
- 统一 launcher：`apps/launcher.py::main`、`build_typer_app`。
- CLI 实现：`apps/cli/cli_main_impl.py::main`、`build_typer_app`；`apps/cli/__main__.py` 是兼容转发模块。
- 已从源码注册/转发的主要命令：`init`、`status`、`wake`、`dashboard`、`provider`（含 embeddings 子命令）、`herd`、`facts`、`reflect`、`skills`、`gateway`、`cron`、`sandbox`、`rtk`、`daemon`、`upgrade`。
- Reflect 的显式 CLI 形状在系统设计文档给出：`elephant reflect run --features pm,diary --date YYYY-MM-DD`。

### HTTP API

- Python 模块入口：`python -m apps.api`，由 `apps/api/__main__.py` 使用标准库 `wsgiref.simple_server` 在本地启动；默认 host/port 代码值是 `127.0.0.1:8000`，数据库默认落在 CLI state 目录。
- 程序化 API：`apps/api/__init__.py` 导出 `ElephantAPIApp`、`APIAppConfig`、结果记录类型和 `create_app`。
- 应用构造：`apps/api/api_runtime_impl.py::create_app`；路由分发：`apps/api/api_runtime_http_methods.py::dispatch`。
- 已读到的主要路由族：`/v1/episodes`（创建、检查、interrupt、next、loops、clarifications、approvals、todos、profile、recall）、`/v1/states`、`/v1/herd`、`/v1/paths`、`/v1/providers`、`/v1/internal`、`/v1/operator`，以及健康检查。API e2e 还验证了 identity/user/relationship/continuity 投影和工具审批。

### Gateway、Dashboard、SDK

- Gateway 模块入口：`apps/gateway/__main__.py`、`apps/gateway/gateway_main_impl.py`；运行时组合根为 `apps/gateway/runtime_factory.py::build_gateway_app`。平台适配器在 `apps/gateway/platforms/` 和相邻 service/transport 文件中。
- Dashboard：`apps/dashboard/` 是 React/Vite 检查面，脚本由 `apps/dashboard/package.json` 声明；其 API client/页面不拥有持久化真相。
- Site：`apps/site/` 是 React/Docusaurus 文档与公开站点，脚本由 `apps/site/package.json` 声明。
- 未发现独立的公共 SDK client 包或单独 SDK 发布目录。当前可复用的“SDK 形状”是 Python import API（`from apps.api import create_app`）和 `packages/contracts`/`packages/models` 的 protocol/dataclass；Gateway 的第三方 SDK（Discord、DingTalk、Feishu 等）是外部传输依赖，不等于 Elephant Agent 自有 SDK。

## 技术栈和依赖

### Python 主运行时

- Python `>=3.12`；构建后端为 `setuptools.build_meta`，构建依赖 `setuptools>=69`、`wheel`。锁文件为 `uv.lock`，其顶层项目也声明 `elephant-agent` 为 editable 包。
- CLI/UI：`typer`、`prompt_toolkit`、`rich`。
- HTTP/异步/浏览器：标准库 `wsgiref` API server、`aiohttp`、`playwright`。
- 模型与协议：`mcp`、`tiktoken`；代码中存在 OpenAI、Anthropic、OpenAI-compatible、vLLM semantic router 等 provider 适配/发现模块。
- 持久化与向量：标准库 `sqlite3`、`sqlite-vec==0.1.9`；`packages/storage/schema.sql` 为打包数据文件；`packages/semantic_index/` 负责 sqlite-vec backend 和 lexical/hybrid search。
- 安全与观测：`cryptography` 用于本地 secret 加密；OpenTelemetry API/SDK、OTLP gRPC exporter、semantic conventions 用于 trace/metrics/structured observability。
- 消息/平台：`discord.py`、`dingtalk-stream`、`lark-oapi`，以及源码中的 Telegram/Weixin/WeCom/Webhook 适配路径；`qrcode` 用于相关配对/配置体验。

### Web 与平台

- `apps/site/package.json`：Docusaurus `3.10.0`、React/React DOM 19、MDX、Mermaid/ELK、`react-pdf`、TypeScript；Node `>=20`。
- `apps/dashboard/package.json`：Vite、React/React DOM 19、React Router、React Flow、Dagre、TypeScript；Node `>=20`。
- `apps/macos/`：Swift/macOS SDK 打包脚本；`Makefile` 提供 `macos-build`、`macos-build-all`、发布打包目标。
- `deploy/`：Docker、systemd、cloud 运行形态；构建/测试统一由根 `Makefile` 和 `tools/make/agent.mk` 驱动。

## 架构判断与未确认项

### 判断

1. **分层主线清晰**：`apps → packages` 的依赖方向在 `docs/agent/repo-map.md`、`apps/AGENTS.md`、`packages/AGENTS.md` 中被明确约束；kernel 是唯一主要 turn lifecycle 编排点，表面不应复制 cognition。
2. **数据模型已从“记忆表”收敛到理解系统**：`system-layer-model.md` 与 `schema.sql` 一致地把 Step 作为证据、Fact 作为有来源的持久化 claim、Question 作为主动好奇性、LearningJob 作为后台学习队列；bootstrap 会清理旧 `records`/`memory_entries`/`groundings` 等遗留表。
3. **召回生产者/消费者边界设计较好**：`semantic_index_factory.py` 明确固定同一 state-dir 索引文件，集成测试验证 Episode close 写入后另一个上下文可通过 `unified_recall` 找回；sqlite-vec 不可用时存在 lexical/degraded 路径。
4. **后台学习采用可组合 feature，而非一个不可分的反思 agent**：trigger 只表达为什么运行，feature 表达允许写什么；`run_reflect_agent` 通过 feature 组装 prompt、tool 白名单和 evidence packet，Skill evolution 还保留待审批边界。
5. **主要工程风险是组合根和兼容层复杂度**：API 与 storage 都通过分散模块再动态挂方法到主类（`ElephantAPIApp`、`RuntimeStorageRepository`），有利于拆分热点，但增加静态导航和变更影响分析成本。`apps/gateway/runtime_factory.py` 是高扇出 composition root，`packages/contracts/runtime.py` 是跨域 dataclass 集中点。
6. **测试策略覆盖了架构关键断言**：已读测试覆盖 schema 终态/idempotence、kernel turn lifecycle、API Episode/Loop/Step 和审批、CLI init/wake/continuity、semantic producer→consumer、PM claim lifecycle，以及连续性场景；测试规则要求 unit/integration/e2e/scenario 分层，符合当前边界设计。

### 未确认项

- 本次严格未安装依赖、未启动服务、未调用真实 provider、未运行测试；因此 provider 凭据、实际模型选择、网络网关连接、sqlite-vec 动态扩展可用性和当前机器上的完整运行结果均未确认。
- `pyproject.toml` 规定 Python `>=3.12`，本分析环境的 Python 版本不是项目运行验证的一部分；没有据此宣称项目可在当前解释器运行。
- API 路由族依据 `dispatch` 和已读 API e2e 汇总，未对所有拆分的 provider/operator/path/gateway 路由逐条穷举；完整公开契约仍以 `tools/agent/public-contracts.yaml` 及其生成文档为准。
- Dashboard/Site 的 TypeScript 编译、构建产物和 macOS Swift 打包未执行；这里只依据 `package.json`、目录 AGENTS 和 Makefile 判断其职责。
- `apps/reflect/`、`apps/learning_agents/` 的兼容导入关系已由源码和 AGENTS 确认，但未来是否完全移除兼容别名、以及所有旧调用方是否已迁移，不在本次只读分析中进一步裁决。

## 实际读取证据范围

README/规则/设计：`README.md`、`AGENTS.md`、`apps/README.md`、`apps/AGENTS.md`、`packages/README.md`、`packages/AGENTS.md`、`docs/README.md`、`docs/agent/README.md`、`docs/agent/repo-map.md`、`docs/agent/context-management.md`、`docs/agent/change-surfaces.md`、`docs/agent/testing-strategy.md`、`docs/agent/architecture-guardrails.md`、`docs/system-design/README.md`、`docs/system-design/AGENTS.md`、`docs/system-design/system-layer-model.md`。

依赖/构建：`pyproject.toml`、`uv.lock`、`Makefile`、`apps/site/package.json`、`apps/dashboard/package.json`。

入口/核心源码：`apps/launcher.py`、`apps/cli/cli_main_impl.py`、`apps/cli/__main__.py`、`apps/api/__main__.py`、`apps/api/__init__.py`、`apps/api/api_runtime_impl.py`、`apps/api/api_runtime_http_methods.py`、`apps/gateway/runtime_factory.py`、`packages/contracts/inventory.py`、`packages/contracts/layers.py`、`packages/contracts/personal_model.py`、`packages/contracts/paths.py`、`packages/contracts/runtime.py`、`packages/kernel/__init__.py`、`packages/kernel/runtime_impl.py`、`packages/kernel/execution_support.py`、`packages/state/__init__.py`、`packages/state/canonical.py`、`packages/state/profile_from_claims.py`、`packages/storage/schema.sql`、`packages/storage/repository_impl.py`、`packages/storage/repository_system_methods.py`、`packages/storage/repository_bootstrap_methods.py`、`packages/evidence/__init__.py`、`packages/evidence/recall_runtime.py`、`packages/evidence/unified_recall.py`、`packages/evidence/semantic_index_factory.py`、`packages/semantic_index/backend.py`、`packages/semantic_index/service.py`、`packages/models/runtime.py`、`packages/models/providers/factory.py`、`packages/reflect/features/__init__.py`、`packages/reflect/features/types.py`、`packages/reflect/runner.py`。

测试：`tests/README.md`、`tests/AGENTS.md`、`tests/integration/AGENTS.md`、`tests/integration/kernel/AGENTS.md`、`tests/integration/kernel/test_turn_lifecycle.py`、`tests/integration/storage_system_layers/test_schema.py`、`tests/integration/semantic_index/test_unified_recall_end_to_end.py`、`tests/integration/reflect/test_skill_opt_e2e.py`、`tests/e2e/api/test_api_surface.py`、`tests/e2e/cli/test_cli_surface.py`、`tests/scenarios/continuity/test_continuity_scenarios.py`、`tests/unit/test_personal_model_lifecycle.py`，以及相关测试目录的局部 `AGENTS.md`。

本文件已吸收此前 `细探-Elephant-Agent.md` 的源码分析结论；后续只维护本文件，旧细探笔记不再作为独立事实源。

本文件是本次分析唯一新增/更新的交付文件；没有修改已有源码、依赖文件、测试、部署文件或 Git 历史。

---

## 后续：通用底座映射与运行闭环裁决（现场源码证据）

### 1. 证据边界与裁决口径

当前核对把项目事实映射到“支持库 / 模块库 / 运行核心 / 网关”四类通用底座边界，但不把 Elephant Agent 的产品语义伪装成平台通用能力。证据优先级为：当前源码 > 当前 schema/测试契约 > `docs/system-design/system-layer-model.md` 与 `docs/agent/**` 设计说明 > 旧细探结论。目标仓库内未发现独立 `细探-*.md` 文件；现有文件已经声明此前 `细探-Elephant-Agent.md` 已吸收，当前核对不删除、不另建平行细探。

专属 `system_engineering_toolkit` MCP 的真实开工上下文返回的是项目 `系统工程平台`（根目录 `/Users/hekunhua/Documents/Agent/PHP/系统工程平台`，MCP 实例 `system_engineering_toolkit`，开工 id `e8d1ecb90f4444d6`），其代码图也固定指向该平台，不是本项目；`codegraph_explore` 因此只能提供平台映射基线，不能作为 Elephant-Agent 源码证据。本节涉及 Elephant-Agent 的事实均来自目标根目录现场读取；验证结果也必须按目标仓库本地命令单独判定。

当前核对最重要的真实性裁决：

- `EventEnvelope` 是通用事件契约和运行中输入信封：`packages/contracts/runtime.py:829-835`，由 `packages/kernel/runtime_support.py:258-291` 的 `KernelSourceRequest.to_event()` 生成；当前 kernel 把它放入 `KernelOutcome` 和 Step `payload_refs`，但未在 `KernelService.run()` 中写入独立事件表。
- `ReconciliationPipeline`/`StateReconciler` 形式上接收 `durable_events`，但 `packages/evidence/recall_runtime.py:171-173` 的 `RecallRuntime.append_event()` 当前直接丢弃事件。因此“事件契约存在、事件被构造”是已实现事实；“事件账本可重放/可查询”不是当前实现事实。
- 当前真实可持久化的执行证据是 `Step`：`KernelStepRecorder.record()` 在 `packages/kernel/lifecycle_support.py:57-109` 构造带 `phase/action/status/sequence/payload_refs/metadata` 的 Step 并调用 `storage.upsert_step()`；`StepEvidenceStore` 在 `packages/evidence/recall_runtime.py:21-119` 只读地把 Step 投影为召回证据，并明确拒绝持久化独立 `RecallEvidence`。
- 因而当前核对底座接入不得把 `EventEnvelope` 当作已落盘的事件源；若平台需要事件溯源、事件重放、幂等消费或跨进程审计，必须另行登记“事件持久化能力”缺口，不得由模块层旁路写库补齐。

### 2. 四层底座映射表

| 当前源码事实 | 支持库（可复用原子能力） | 模块库（领域组合流程） | 运行核心（唯一执行编排） | 网关/应用边界 | 不是通用底座的 Agent 业务语义 |
|---|---|---|---|---|---|
| `PersonalModel`、`State`、`Episode`、`Loop`、`Step`、`LearningJob`、`EventEnvelope` dataclass | `packages/contracts/`：稳定 ID、状态枚举、可序列化结构、参数/结果形状 | 不应定义第二套对象 | 读取契约并推进生命周期 | 只做入站/出站转换 | 四 lens、Elephant identity、Episode/Loop 产品层级和“理解系统”语义 |
| SQLite schema、repository 方法、WAL/事务、索引 | `packages/storage/`：`RuntimeStorageRepository`、`schema.sql`、连接与 SQL 持久化 | 不应直接拼 SQL | 通过 `KernelStoragePort` 使用，不拥有 SQLite 细节 | 由 app 选择 state 目录并初始化 | 哪些 Fact/Question 属于用户理解、哪些学习触发器有产品意义 |
| Tool 注册/描述/schema/审批/执行/生命周期事件/清理 | `packages/tools/`：`ToolRuntime`、`ToolDefinition`、executor、approval、context | `packages/understanding/`、`packages/skills/` 等组合具体工具意图 | `execution_support.py` 负责模型工具循环、Step 证据和 checkpoint | gateway/CLI/API 只注入 requester 与 session context | `tool.personal_model.*`、`tool.diary.write`、`tool.skill.draft` 等工具的产品语义与允许写入对象 |
| Provider-neutral model 请求、流式响应、错误/用量/凭据适配 | `packages/models/`、`packages/auth/`：provider adapter、transport、credential resolver | `packages/context/` 组装 Prompt，`packages/reflect/` 组装后台 Agent prompt | `execute_kernel_turn()` 决定模型调用次数、工具循环、预算和结果归一 | app/gateway 选择 profile、凭据和 surface provider | “Elephant 怎么说”、四 lens 如何解释用户、onboarding letter 文风 |
| embedding、semantic index、词法/向量混合召回 | `packages/embeddings/`、`packages/semantic_index/` | `packages/evidence/` 的 `RecallRuntime`、`unified_recall`、indexer | kernel 只请求 recall/context，不持有索引实现 | gateway/CLI/API 只呈现结果 | “相关记忆”如何服务个人理解的排序策略及 recall scope 语义 |
| 资源上下文、审批、临时工作目录、会话清理、取消检查 | `packages/tools/` executor/context、`packages/sandbox/`、`packages/security/` | 领域模块只声明需要的能力/预算 | `KernelSessionResourceManager`、Episode close、loop checkpoint 统一收口 | app 负责进程启动/停止和 surface 生命周期 | 哪些资源属于一次对话、一次学习 Agent、或某个产品动作 |
| LoopState、pending tool、partial assistant、wait condition、heartbeat | `packages/contracts/runtime.py` 数据结构、storage checkpoint 方法 | `resume_support.py` 提供通用恢复判定 | `LoopCheckpointService` + kernel 负责 park/resume/cancel | CLI/API/Gateway 把“继续/恢复”映射为请求 | “继续这段对话”的用户体验措辞和产品默认唤醒策略 |
| `learning_jobs` SQLite 队列、worker claim/retry/result | `packages/storage/` 的队列持久化原子操作 | `packages/reflect/` 的 feature/evidence/prompt 组合 | `apps/learning_worker_runtime.py` 负责 worker 进程状态和调度边界；kernel 只 enqueue | gateway/daemon 只负责拉起/停止 worker | `episode_close`、`dream`、`onboarding_letter`、skill evolution 等触发器和 feature 选择 |
| 跨进程出站消息队列 | `packages/gateway_core/outbound_queue.py`：flock、原子替换、claim/release/backoff | 各 adapter 只消费同一队列并调用自己的发送实现 | 不应让 kernel 直连 IM SDK | `apps/gateway/` 负责 adapter、账号、会话和投递 | 某个 IM 平台的 conversation identity、mention 规则和文案 |
| telemetry、structured logs、trace、failure status | `packages/telemetry/`、`packages/observability/` | `packages/reflect/` 将进度投影到 LearningJob | kernel 发 `kernel.stage`/`kernel.outcome`，统一关联 event/episode/loop/step | gateway 只附加 transport 信息 | “这次学习是否改变了个人模型”的业务判定 |

**复用/升级/新建/隔离裁决：**

1. **吸收**：Step 作为执行证据、Loop checkpoint 作为长运行恢复记录、`learning_jobs` 作为后台队列、`ToolRuntime`/model provider/SQLite repository 作为通用能力候选；它们已有明确 owner 和可验证调用边界。
2. **升级现有支持库**：事件契约需要补“可持久化事件账本/幂等键/重放查询”能力时，应升级 `packages/contracts` + `packages/storage` 的公共契约与唯一 repository owner；不得让 `packages/evidence` 或某个 gateway 私自保存事件。
3. **升级现有模块**：`packages/evidence` 只负责 Step/Fact 的召回和索引；`packages/reflect` 只负责后台 feature 编排；如果需要把事件转成证据，模块只能引用已持久化的事件/Step，不拥有事件写入。
4. **继续待核**：当前 `RuntimeStorageRepository` 使用 `INSERT OR REPLACE` 写 learning job，队列 claim 用 `BEGIN IMMEDIATE`，但 worker 崩溃后的 lease/超时回收、队列死信审计和并发跨进程恢复尚未形成统一契约；当前只能把现有实现映射为“有限重试队列”，不能宣称完整任务系统。
5. **隔离**：Elephant 的 four-lens Personal Model、Fact/Question 规则、Reflect feature 选择、onboarding letter、Paths/continuity 等保留在 Agent 领域模块；它们可消费通用底座，但不应下沉为平台公共语义。

### 3. 唯一可审计调用链

#### 3.1 前台请求到响应（当前真实主链）

```text
Gateway adapter / CLI / API
  → apps/* surface normalizes inbound message and chooses state_dir/profile
  → GatewayCoreService（仅 gateway surface）或 app 直接构造 KernelSourceRequest
  → KernelSourceRequest.to_event() 生成 EventEnvelope（当前为内存输入信封）
  → KernelService.run()
      → resolve_runtime_identity()
      → open_episode_lifecycle() / open_loop_lifecycle()
      → KernelStepRecorder.record(observation.record_input)
      → _retrieve_recall_evidence()
          → RecallRuntime.retrieve()
          → unified_recall()
          → RuntimeStorageRepository.list_steps / semantic index search
      → ContextCapability.assemble() 生成 ContextBundle
      → execute_kernel_turn()
          ├─ 直接工具：ToolCapability.invoke()
          │    → ToolRuntime.invoke()
          │    → registry → visibility/approval → executor → ExecutionResult
          └─ 模型：ModelProviderCapability.generate()
               → provider adapter / HTTP transport
               → ExecutionResult
               → 解析 tool calls、去重、按安全集合并行
               → ToolRuntime.invoke() × N
               → role-preserved tool messages
               → 继续唯一模型循环，直至完成/失败/取消/预算 park
      → 每个节点由 KernelStepRecorder 写 Step（planned/completed/failed/cancelled）
      → loop checkpoint 写 LoopState/LoopStep（长循环、pending tool、heartbeat、wait condition）
      → _refresh_state_projection() → RuntimeStorageRepository.upsert_state()
      → close_loop_lifecycle() → close_episode_lifecycle()
          → exit summary semantic index（best effort）
          → session_resource_manager.cleanup_session()
      → episode closed 时 enqueue_learning_job()
      → KernelOutcome + _emit_telemetry(kernel.outcome)
  → delivery capability / gateway adapter → user-visible response
```

对应源码：`packages/kernel/runtime_impl.py:170-512`、`packages/kernel/execution_support.py:53-168,372-529`、`packages/kernel/lifecycle_support.py:57-109,269-437`、`packages/tools/runtime.py:593-758`、`apps/gateway/runtime_factory.py:403-492`。

#### 3.2 后台学习唯一主链

```text
Kernel close episode
  → RuntimeStorageRepository.enqueue_learning_job()
  → learning_jobs(status=queued, available_at)
  → apps.learning_worker_runtime.run_learning_worker()
      → claim_learning_job()（BEGIN IMMEDIATE + earliest available）
      → run_learning_job()
          → packages.reflect.runner.run_reflect_agent()
              → resolve_features(trigger)
              → build_evidence(runtime, job, features)
              → allowed_tools + system_prompt
              → runtime.run_sub_agent(learning_agent=True)
                  → 同一 ToolRuntime / model provider / Step/child Episode 语义
              → write_learning_job_result(result_json)
          → close_finished_learning_child_episode()
          → complete_learning_job()
      → 异常 → fail_learning_job()（attempt_count < max_attempts 则 queued，否则 failed）
  → worker record/log 写 `learning-worker.runtime.json` / `learning-worker.log`
```

对应源码：`packages/kernel/runtime_impl.py:463-494`、`packages/storage/repository_learning_methods.py:96-195,268-302,368-444`、`apps/learning_worker_runtime.py:327-453`、`packages/reflect/runner.py:479-585`。

#### 3.3 跨进程出站消息链（与 kernel 内部响应链分开）

```text
cron / 非 IM 进程
  → GatewayOutboundQueue.enqueue() 写 gateway-outbound-queue.json
  → flock + 临时文件 + replace
  → gateway adapter claim(adapter_id)
  → 真实 adapter send path（复用同一 adapter 的 credential/session/retry）
  → success: complete(row_id)
  → failure: release(row_id,error) → pending + backoff
  → attempts >= max_attempts: 丢弃并由 telemetry 侧记录
```

对应源码：`packages/gateway_core/outbound_queue.py:1-35,117-243,282-355`。该队列是通用“跨进程投递缓冲”，不是学习任务队列，也不是事件账本；三者不得合并。

### 4. 事件、步骤与 Agent 运行单元的证据语义

| 对象 | 当前真实状态 | 可作为何种证据 | 不可宣称什么 |
|---|---|---|---|
| `EventEnvelope` | `KernelSourceRequest.to_event()` 生成，包含 `event_id/event_type/episode_id/source/payload` | 请求输入的相关性、来源和 payload 引用 | 不是已落盘事件；当前 `RecallRuntime.append_event()` no-op |
| `Step` | 每次 observation/context/model/tool/reflect/state/response/checkpoint 都可能写入 SQLite `steps` | 原子操作证据、失败/取消状态、顺序、payload refs、tool/model metadata、召回来源 | 不是完整 provider 原始响应或不可变事件流；`upsert_step` 仍是 repository 写入口 |
| `Loop` | `loops` 表保存一次 Episode 内的 turn-level 生命周期 | 一次运行单元的触发、状态、outcome、时间边界 | 不等于后台 `LearningJob`，也不自动提供跨进程 lease |
| `LoopState`/`LoopStep` | checkpoint 方法持久化长循环状态和摘要 | crash/park/resume 的恢复输入、pending tool、partial assistant、heartbeat | `resume_support.py` 的“规划”不等于 supervisor 已真实重放所有 async tool |
| `LearningJob` | SQLite 队列行保存 queued/running/completed/failed/cancelled、attempt、worker、result | 后台 Agent 工作单元的排队、领取、重试和结果摘要 | 不等于 Agent 的所有 Step；job result 仍是摘要 JSON |
| `ToolLifecycleEvent` | ToolRuntime 进程内 observer 事件：requested/classified/approval/execution.started/completed/failed | 实时进度、审批和失败观测；Reflect 会压缩到 job progress | 不是 durable event store；进程崩溃后不能凭 observer 事件重建全链 |
| `kernel.stage`/`kernel.outcome` telemetry | `KernelService` 统一发出，含 event/episode/loop/step ids 和计数 | 运行观测、指标、追踪关联 | 不是业务状态 owner，也不是事实/证据写入 owner |

**Agent 运行单元定义（当前可落地的最小通用形状）：**

- 前台一次 `KernelService.run()` = 一个 `Episode` 内的一个 `Loop`，通过 `request_id → event_id → episode_id → loop_id → step_id` 关联；它可以是直接 Tool、一次模型调用，或模型-工具循环。
- 后台一次 `LearningJob` = 一个可排队、可领取、有限重试的 Agent 工作单元；`run_reflect_agent()` 再组合 feature、evidence、system prompt 和 allowed tools。
- 子 Agent 的 `session_id=job.episode_id`，结果可能产生 child Episode；worker 会检查 child Episode 的 parent/job scope 后关闭它，但当前后台执行的每个内部动作是否都完整写入独立 Step，需继续用集成测试核实。
- 因此通用底座可复用“运行单元 id、状态机、checkpoint、预算、工具/模型调用证据、失败分类和队列”，不能复用“reflect feature 名称、四 lens 业务判断、onboarding letter、学习写 Fact 的规则”。

### 5. 资源生命周期与所有权

| 资源 | 创建/持有 | 正常释放 | 失败、超时、取消、崩溃 | 当前缺口/底座落点 |
|---|---|---|---|---|
| 输入事件信封 | request 生成；kernel 暂持 | 随 `KernelOutcome` 返回 | 进程崩溃即丢；无 durable event store | 支持库契约 + storage 事件账本（待核/新建缺口） |
| Step 证据 | `KernelStepRecorder` 创建；storage 持有 | SQLite commit 后由 repository 管理 | model/tool 异常前已写的 planned/failed Step 可保留；中途进程杀死可能留下 planned | 支持库 storage；需补不可变/幂等语义才可作事件证据 |
| Episode/Loop | lifecycle 创建/更新；kernel 持有 | close lifecycle；Episode close 还触发索引、学习入队、session cleanup | model 非 `RuntimeError` 异常可能从 `run()` 逸出，未见统一 `finally` 关闭路径；崩溃恢复依赖 checkpoint/reconciliation | 运行核心 owner；补统一异常收口/残留扫描 |
| Model HTTP/stream session | `packages/models` provider adapter 持有 | provider 返回/异常由 adapter 处理 | provider overflow 触发 context compact retry；取消只由 kernel 的 `cancel_check` 在循环边界感知；SSE partial 有 checkpoint 字段 | 支持库 provider + 运行核心预算；需实测连接关闭/超时/断流 |
| Tool invocation/executor | `ToolRuntime.invoke` 建 invocation，executor 执行；session context 带 cwd/roots/cancel_check | executor 完成；Episode close 调 `cleanup_session` | 未注册/禁用/不可用/不可见/审批拒绝在 invoke 边界返回错误或 blocked/deferred；executor 异常发 failure event 后上抛，kernel `_invoke_tool_call` 转失败 ExecutionResult；崩溃清理依赖 executor 实现 | 支持库 tools/sandbox；运行核心只传 session/owner |
| Loop checkpoint | `LoopCheckpointService` 创建；storage checkpoint 表/方法持有 | complete/fail/cancel/park 状态落盘 | budget exhausted park；cancel 标记 cancelled；crash 用 heartbeat/crash_marker/pending tool 供 resume 规划；async tool `poll` 仍是 Phase 2 预留 | 运行核心 + storage；需 supervisor 现场证明真实重启恢复 |
| SQLite 连接/事务 | `RuntimeStorageRepository.connection()` | context manager/commit | `claim_learning_job` 用 `BEGIN IMMEDIATE` 抢占；锁/损坏/迁移异常的现场恢复未在当前核对执行 | 支持库 storage；禁止模块和网关直连库 |
| Semantic index/vector | index bundle/service 创建；state-dir 物理文件共享 | 索引服务管理；失败为 best effort warning | embedding 不可用时 lexical/degraded；索引失败不应阻断 Step 写入，但召回质量下降 | 支持库 embeddings/index；evidence 模块编排 |
| Learning job | episode close enqueue 到 SQLite；worker claim 持有 | complete/failed/cancelled 更新 | worker 异常按 attempt/backoff 重试；达到 max_attempts 进入 failed；worker kill 会把 active job 标记 terminal failure，但此路径未验证重试策略一致性 | 支持库队列原子操作 + 运行核心 worker supervision |
| Learning worker process | gateway factory `Popen(... start_new_session=True)` 创建，runtime record 记 pid/log | idle/once/stop 后写 stopped record | pid 不活跃时可重新拉起；SIGTERM stop；运行异常由 job fail；SIGKILL/孤儿进程/重复 worker 竞争需真实故障测试 | 网关/daemon 只拉起；通用进程监督应归运行核心 |
| Gateway outbound queue file/lock | enqueue 创建 JSON row；`flock` 保护 | complete 删除；release backoff | corrupt/unreadable 文件按空队列处理，可能丢消息；超过 max_attempts 直接丢弃；临时文件 replace 非 fsync 语义 | 支持库 gateway_core；平台接入需补死信/损坏告警 |
| Gateway identity/session/credentials | runtime factory 建 store、resolver、adapter | app shutdown/adapter lifecycle | auth/transport failure由 adapter/retry处理；跨进程凭据/队列恢复需 e2e | 网关只拥有 transport/identity；不拥有 PM/State 规则 |

### 6. 失败、超时、取消、崩溃矩阵

| 场景 | 当前源码路径与结果 | 证据落点 | 恢复/重试 | 结论 |
|---|---|---|---|---|
| 正常模型完成 | `_generate_with_steps()` 返回 response；model Step completed；kernel 写 State、关闭 Loop/Episode、索引并 enqueue | model/reflect/write_state/emit_response Steps + Loop/Episode + telemetry | 无需重试 | 已实现主链 |
| 直接工具成功 | `_execute_direct_tool_loop()` 执行 Tool、checkpoint record_tool_step、complete；kernel 写 response Step | tool Step + Loop checkpoint | 无 | 已实现，但需 provider/executor 真实验证 |
| 模型返回 tool calls | 去重后按安全集合串/并行调用；每个 call planned/completed/failed；继续模型 | ToolRuntime 生命周期事件 + Step metadata + LoopStep | 达到 turn/wall budget 则 park | 已实现有界循环 |
| 未注册/禁用/不可用/权限或审批拒绝 | ToolRuntime 在 registry/visibility/approval 边界拒绝，返回 blocked/deferred 或抛出结构化异常 | ToolLifecycleEvent；kernel tool Step 可记录 failed/blocked | 不自动重试审批；用户/调用面需后续决定 | 已实现边界，业务重试不统一 |
| 工具 executor 异常 | ToolRuntime 发 `execution.failed` 并抛出；kernel `_invoke_tool_call` 捕获后转 `ExecutionResult(outcome=failed)` | failed tool Step、LoopStep、telemetry | 当前模型循环可继续把失败作为 observation；无统一退避 | 部分实现 |
| provider overflow | `KernelService.run()` 捕获 `RuntimeError`，`retry_context_after_provider_overflow()` compact 后只重试一次 | compact Step + source refs + retry stage | 一次压缩重试；再次失败向上抛 | 已实现但只覆盖此类 RuntimeError |
| provider 普通异常/HTTP 断流 | `_generate_with_steps()` 写 failed model Step 后 re-raise；run 外层没有统一 `finally` 收口 | failed model Step；可能没有最终 Loop/Episode close | 无通用 retry；partial SSE 只有 checkpoint/resume 设计支持 | **重要风险：可能遗留 open Episode/Loop 和 session 资源** |
| 用户取消 | `cancel_check` 在 model/tool 循环边界命中；生成 cancelled ExecutionResult；LoopCheckpoint cancel；kernel close loop/按 policy 更新 Episode | cancelled Step、cancelled Loop、telemetry | 不重放已取消调用 | 已实现边界语义；provider 正在阻塞时不能即时打断未确认 |
| turn/wall budget 超限 | `LoopCheckpointService` park，写 wait_condition=`budget_exhausted`、continuation prompt、checkpoint/pause Step，返回 `outcome=paused` | pending LoopState + checkpoint/pause Step | 用户再次请求继续；resume 规划 pending tool | 已实现 park；真实跨重启 resume 仍待验证 |
| learning job 正常 | claim queued→running，reflect 运行，写 result_json，complete | learning_jobs progress/result + child Episode/Steps（若产生） | 无 | 已实现 |
| learning job 异常 | worker 捕获异常，`fail_learning_job()`；attempt < max → queued/backoff，否则 failed | last_error/progress/status/attempt_count | 有界重试，默认 max_attempts=3；具体 backoff 由 worker `min(60,max(5,attempt*5))` | 已实现有限重试 |
| worker stop/kill | stop 主动把记录中的 active job 标 terminal failure，再 SIGTERM；worker finally 写 stopped | worker runtime record + job failure | gateway 下次发现 pid inactive 可拉起；SIGKILL 现场重启需测试 | 部分实现，存在“终止失败 vs 可重试”语义待核 |
| gateway outbound send failure | claim→in_flight；adapter 失败后 release pending + delay；attempts 达上限删除 | queue row last_error/attempts；telemetry侧记录 | 默认 max_attempts=5、15s backoff | 已实现但没有 durable dead-letter row |
| gateway queue 文件损坏 | `_load_rows()` 把不可读/非 list/坏行当空或跳过 | 仅日志/运维可见，数据行可能丢 | 无自动修复/隔离 | **重要风险：不能当可靠消息队列** |
| SQLite 锁/进程崩溃 | claim 有 `BEGIN IMMEDIATE`；checkpoint/learning job 依赖 SQLite 提交边界 | 已提交行；未提交事务由 SQLite 回滚 | 新进程可读已提交 checkpoint/job；stale running job 专门回收策略不足 | 部分实现 |
| 事件写入/重放 | `append_event` 当前 no-op | 无事件落点；只能查 Step/Fact | 无 | **阻断平台事件溯源映射的缺口，不得假绿** |

### 7. L0-L4 现场验证阶梯

以下是针对本次架构文档和后续底座接入的分级验收，不把“源码存在”当作“运行通过”。当前核对只改文档，L0-L2 为本次可执行范围；L3-L4 记录为后续真实运行/外部依赖门。

| 等级 | 证明目标 | 目标仓库命令/证据 | 当前核对状态 |
|---|---|---|---|
| L0 静态身份与文档完整性 | 根目录、唯一 `ARCHITECTURE.md`、流程图、源码路径、只改允许文件 | `test -s ARCHITECTURE.md` + `git diff --check` + 必需章节/源码路径脚本：退出码 0；`make agent-report CHANGED_FILES="ARCHITECTURE.md"`：退出码 0；现场状态仅出现 `?? ARCHITECTURE.md`（目标文档为既有未跟踪交付文件） | 通过（静态脚本退出码 0）；Git 不提交、不修复未跟踪基线 |
| L1 仓库规则/文档门禁 | manifest、文档、契约引用和上下文映射无明显漂移 | `make agent-validate`：退出码 2，既有 `apps/cli/cli_main_elephant_support.py:1` parse-error；`make agent-context-audit CHANGED_FILES="ARCHITECTURE.md"`：退出码 0，但报告该顶层文件未归属 task surface | 部分通过；阻断与本次文档无关，未修改规则文件 |
| L2 本地回归 | harness 回归与 Python/结构检查不因文档变更破坏 | `make agent-lint`：退出码 2（同一 parse-error + 顶层文档无 task surface）；`make agent-test`：退出码 2，64 tests 中 2 个既有 `AgentGateTests` 失败，均由同一 parse-error 引起 | 未通过既有仓库门禁；不能宣称全绿，也未为修绿而越界修改 |
| L3 运行核心纵向链 | 临时 state dir 中真实完成 gateway/CLI/API → kernel → Step/Loop/Episode → learning_jobs → worker/result；取消、预算 park、重启 resume、队列 claim/retry 都有读回证据 | `make test-integration-scenarios`、相关 `tests/integration/kernel/**`、`tests/integration/storage_system_layers/**`、`tests/integration/reflect/**`、gateway e2e | 当前核对未执行；需 Python 依赖和较长运行环境，不能宣称通过 |
| L4 外部/灾难闭环 | 真实 provider/IM adapter、流式断线、provider overflow、executor 崩溃、worker SIGKILL、SQLite 锁/损坏、gateway queue 损坏与恢复，且资源无残留 | `make e2e`、`make test-live-provider-smoke`（需明确 secrets）、故障注入与进程/文件/DB 读回 | 当前核对未执行；代码图/外部服务也未提供证据 |

L3/L4 的最低验收断言：

- 事件：若声称事件持久化，必须重启进程后按 `event_id` 读回；当前实现应明确失败而不是用 Step 数量替代。
- Step：至少读回 observation、model/tool planned、completed/failed/cancelled、checkpoint/pause 的顺序、payload refs 和 episode/loop 关联。
- Agent 单元：读回 `LearningJob.status/attempt_count/worker_id/result_json`，并验证同一 episode 重复 enqueue 的幂等行为。
- 资源：正常完成、业务失败、主动取消/超时、SIGKILL 四种终态都检查无遗留 worker、锁文件、临时目录、未关闭 session 或无限 running job。
- 队列：learning_jobs 与 gateway outbound queue 分开测试；前者验证 SQLite claim/retry，后者验证 flock/atomic replace/backoff/max attempts/损坏文件告警。

### 8. 后续底座工作包（只作为映射输入，不在本项目落地平台改造）

| 工作包 | 唯一 owner 候选 | 验收契约 | 现状裁决 |
|---|---|---|---|
| 事件账本 | `packages/storage` + `packages/contracts` | append-only event、event_id 幂等、按 episode/sequence 重放、失败事件可读回 | 新建/升级缺口；当前 `append_event` no-op |
| Step 证据治理 | `packages/kernel` 写入 + `packages/storage` 持久化 + `packages/evidence` 只读投影 | Step 顺序唯一、状态闭集、payload refs 可解析、失败/取消不可被覆盖为成功 | 吸收，需验证 upsert 的幂等/覆盖边界 |
| Agent 运行单元 | `packages/contracts.runtime` + kernel checkpoint + worker queue | 统一 run/job id、状态、预算、取消、超时、重启恢复、结果/证据关联 | 吸收现有 Loop/LearningJob，统一契约待核 |
| Tool/Model provider | `packages/tools` / `packages/models` | 公开 capability、权限/审批、错误分类、超时/取消、资源释放、调用 Step | 吸收；普通 provider 异常收口不足 |
| 持久化/队列 | `packages/storage`；`packages/gateway_core` 仅负责出站队列 | 事务边界、claim lease、retry/dead-letter、损坏告警、跨进程一致性 | 两类队列已分离；gateway 文件队列可靠性不足 |
| 资源/失败恢复 | kernel lifecycle + checkpoint + tools/sandbox + worker supervisor | 四终态清理、stale running 回收、SIGKILL 读回、无旁路释放 | 部分实现；需 L3/L4 故障验证 |
| 网关接入 | `apps/gateway` + `packages/gateway_core` | adapter 只做身份/传输/投递；所有认知调用进入 kernel；出站单一发送路径 | 基本符合；不应把 gateway queue 当 kernel queue |

**后续最终结论：** Elephant-Agent 已经具备可映射的通用执行骨架（契约、Step 证据、Loop checkpoint、Tool/Model provider、SQLite learning queue、gateway outbound queue），但“事件”仍是运行信封而非 durable event log，“普通模型异常后的统一收口”和“跨重启资源/队列恢复”仍未闭环。可吸收的是能力边界和调用链，不可吸收的是产品层的 Personal Model/四 lens/Reflect feature 业务规则。任何平台化改造须先登记上述缺口、冻结唯一 owner、补 L3/L4 验收，再决定升级支持库或新建通用原子能力。

---

## 第四轮：全交互链、状态机与流式传输审计

### 1. 当前核对范围与证据规则

当前核对只读取目标仓库当前磁盘源码、SQLite schema、测试和设计文档，不使用 MCP/Hermes，不启动服务、不调用真实 provider、不修改源码和测试。目标仓库没有 `.codegraph/` 索引，因此未把 CodeGraph 结果冒充源码证据；定位依据是现场目录、全文检索和逐段源码读取。唯一落盘文件仍是本根 `ARCHITECTURE.md`。

当前核对纠正前文可能造成的三个误读：

1. 项目**确实存在 SSE**：API 有 WSGI SSE 和 daemon 的 `aiohttp` SSE 两层适配，均调用 `ElephantAPIApp.stream_loop_events()`；它们是 UI/HTTP 事件投影，不是 provider 原始流的持久化日志。
2. 项目**确实存在 WebSocket**：WeCom 使用独立的 `aiohttp.ClientSession` 与 WebSocket Bot 长连接；它与 API SSE、provider SSE、gateway 出站 JSON 队列是四种不同传输/队列，不应合并成一个“事件总线”。
3. `ReconciliationPipeline` 的字段名 `durable_events` 与说明文字不能证明事件已落盘。当前 `RecallRuntime.append_event()` 仍是显式 no-op；事件构造、观测、投影和 durable event store 必须分别描述。

### 2. 真实全交互链

#### 2.1 CLI/API/Gateway 到 Kernel

```text
CLI / API / Gateway adapter / Cron bridge
  → surface 读取配置、state_dir、profile、route/session
  → 规范化 prompt、source payload、delivery payload、cancel_check
  → KernelSourceRequest.to_event()（内存 EventEnvelope）
  → KernelService.run()
      → resolve_runtime_identity()
      → open_episode_lifecycle() / open_loop_lifecycle()
      → KernelStepRecorder 写 observation.record_input
      → RecallRuntime.retrieve_evidence()
          → StepEvidenceStore 读 steps
          → semantic index + lexical/hybrid recall
      → ContextCapability.assemble()
      → execute_kernel_turn()
          ├─ 直接工具：ToolCapability → ToolRuntime
          └─ 模型：ModelProviderCapability.generate()
                    → provider adapter / HTTP JSON 或 provider SSE
                    → 解析 tool calls
                    → ToolRuntime.invoke()（审批/可见性/执行）
                    → role-preserved tool messages
                    → 下一次模型调用，直到完成/失败/取消/park
      → upsert State、Loop、Step、checkpoint
      → delivery hook
      → close Loop；按状态关闭/保持 Episode
      → 关闭 Episode 时索引摘要并 enqueue LearningJob
      → KernelOutcome + telemetry
```

API 的同步 `run_loop()` 在 `KernelService.run()` 外层用 `finally` 清理已注册的 session cancel callback，但 Kernel 本身在进入执行后没有包住整个 Episode/Loop 生命周期的统一 `finally`。模型普通异常、provider 断流或状态持久化异常可能在最终 `close_loop_lifecycle()`/`close_episode_lifecycle()` 前向上抛出；已写入的 failed Step 不等于 Loop/Episode 已关闭。

#### 2.2 API SSE 链

```text
POST /v1/episodes/{episode_id}/loops/stream
  → WSGI __call__ 或 daemon aiohttp route
  → ElephantAPIApp.stream_loop_events()
  → 每次流请求启动 daemon Thread worker
      → 订阅 model stream observer、ToolRuntime observer、telemetry observer
      → 获取全局 _loop_stream_lock
      → run_loop(cancel_check=cancel_event.is_set)
      → 产出 loop.started / assistant.delta / reasoning.delta /
        tool.lifecycle / kernel.stage / loop.completed|cancelled|failed
  → Queue 中的事件包装 stream_sequence
  → WSGI bytes 或 aiohttp StreamResponse 写 SSE frame
```

实现上的重要边界：

- `_loop_stream_lock` 位于单个 `ElephantAPIApp`，会把同一 app 的多个 live loop 串行化；它防止共享 provider observer/clarify delegate 互相覆盖，但不是按 episode 的并发锁。
- `Queue(maxsize=2048)` 有界，worker 的 `put()` 仍可能阻塞。客户端断开时，消费者 finally 只清除 `_loop_cancel_events` 映射，没有主动 `set()` 当前 cancel event；因此 worker 可能继续执行到自然结束，或在队列满时停滞。
- worker finally 会恢复 provider stream observer、clarify delegate，取消 observer 订阅并释放 stream lock；这是正常 worker 退出的清理，不是断开连接时的强制终止保证。
- WSGI 适配器捕获异常后只发送一个 `loop.failed` frame；aiohttp 适配器捕获 `ConnectionResetError`/`CancelledError` 后尝试 `write_eof()`。SSE frame 本身没有 durable offset、重放 token 或 last-event-id 协议。
- `stream_loop_events()` 的 stream sequence 只在本次 generator 内递增，重连不能从某个 sequence 恢复；恢复依赖 Loop checkpoint/CLI 侧状态，而不是 SSE 重放。

#### 2.3 Provider SSE 链

`packages/models/providers/http.py::UrllibJSONHTTPTransport.post_json_stream()` 在首个 chunk 前使用有限 retry；拿到首个 chunk 后，连接异常转换为 `ProviderSSEIncompleteError`，携带累计 `partial_text`。`runtime_capability.py` 用 scoped observer 将 delta 投影到 API/CLI。

这条链与 API SSE 是嵌套关系：provider SSE 是上游模型传输，API SSE 是下游 UI 投影。当前架构只把 partial 文本定义在 `LoopState.partial_assistant` 的 checkpoint 契约中；当前核对读取到的 `resume_support.py` 和 `harness/supervisor.py` 能识别、消费和持久化该字段，但 supervisor 不会再次调用 provider，也不会自动 re-enter kernel。

#### 2.4 WeCom WebSocket 链

```text
gateway daemon
  → WeComGatewayService.start_gateway()
  → aiohttp ClientSession.ws_connect()
  → subscribe handshake（超时/错误即失败）
  → heartbeat task + _read_events()
  → asyncio.create_task(_dispatch_payload_safe(payload))
  → inbound normalization / identity-session mapping / Kernel request
  → adapter reply
```

`start_gateway()` 的 `try/finally` 始终调用 `stop_gateway()`；stop 路径设置 `_running=False`，取消 heartbeat/listen task，关闭 websocket、取消 pending response futures、关闭 aiohttp session 和 HTTP client。监听异常会关闭坏连接并指数退避重连，连续失败达到阈值后增大 backoff。`asyncio.create_task()` 为每个 inbound payload 派发任务，单个任务异常由 `_dispatch_payload_safe()` 吸收并记录；停止时未见统一等待所有 payload dispatch task 的集合，因此“socket 已清理”不等于所有已派发处理已完成。

### 3. 状态机裁决

#### 3.1 Episode / Loop / checkpoint 状态

| 层级 | 当前状态/转移 | 权威写入口 | 关键限制 |
|---|---|---|---|
| Episode | `open` → `closed`；`open_next_episode()` 先关闭 parent 再建立带 `parent_episode_id` 的新 Episode | `episode_state_machine.close_episode()` / `open_next_episode()` | close 是幂等的；index/learning enqueue/cleanup 是 close side effects；异常前未必进入 close |
| Loop | `active` → `completed` / `failed` / `cancelled`，或 `active` → `pending`(`waiting`) | `LoopCheckpointService.complete/fail/cancel/park` + repository | Loop checkpoint 存在于 `loops.metadata_json`，不是独立 SQL 表；每次 upsert 可 round-trip 校验关键字段 |
| WaitCondition | timer/tool_callback/network/approval/external_poll/event/budget_exhausted 等等待原因 | `LoopCheckpointService.park()` | `wake_at` 与 `auto_wake` 只给 supervisor 判定；不代表事件总线或异步 tool 已实现 |
| PendingToolCall | `dispatched` / `running` / `done_unread`；resume 规划为 `skip` / `inject` / `replay` / `poll` | `register_pending_tool()` / `apply_resume_snapshot()` | `poll` 明确是 Phase 2 预留；replay 依赖 tool 支持 idempotency key，不能保证外部副作用 exactly-once |
| Supervisor | stale heartbeat 或 timer ripe → `reclaimed_crashed` / `woken_timer` | `scan_once()` + `upsert_loop_checkpoint()` | 只标记/整理 checkpoint，不重新执行 kernel；重复扫描主要依赖刷新 heartbeat 避免重复处理 |
| LearningJob | `queued` → `running` → `completed`，失败时 `queued` + backoff 或 `failed`，另有 schema 允许 `cancelled` | `claim_learning_job()` / `complete_learning_job()` / `fail_learning_job()` | claim 用 `BEGIN IMMEDIATE`；没有 lease_expires_at/heartbeat 的 learning_jobs 字段，worker 崩溃后的 stale running 回收不等同 Path run 的 lease 机制 |
| Path Step Run | `queued` → `dispatched` → `running` → terminal，带 attempt/claim token/heartbeat/lease | `repository_path_run_methods.py` | 它是长期 Path 执行队列，不能与 Episode Loop checkpoint 或 LearningJob 互称“任务状态机” |

#### 3.2 重复/冲突的架构说法

- `close_episode()` 本身会 enqueue `episode_boundary_learning`，而 `KernelService.run()` 在 Episode closed 后又有 `_enqueue_episode_learning_job()`。两条路径通过 `load_learning_job_for_episode()` 对非 `force_new` 的 queued/running/completed job 做复用，因此当前通常表现为幂等复用，不是两个独立 job；架构文档必须称为“双触发入口 + repository 去重”，不能称为只有一个 enqueue 调用点。
- `system-layer-model.md` 把 Steps 定义为 canonical evidence，`recall_runtime.py` 的 `StepEvidenceStore` 也拒绝写独立 RecallEvidence；因此旧文档中“Evidence/Record/Memory 表”只可作为已移除遗留模型，不能与当前 schema 的 `semantic_index_entries`、`learning_jobs` 或 `steps` 并列为现行实体。
- `reconciliation.py` 的 `repository` 参数在 `reconcile_turn()`/`reconcile_wake()` 中未被使用，实际写操作仅调用 `recall_runtime.append_event()`；而该方法是 no-op。这里的 “durable events” 是待实现契约，不是当前状态机的持久化阶段。
- `LoopState` 的 checkpoint metadata 与 `loops` 表是当前真实持久化实现；不能把 `LoopState` 说成独立 `loop_checkpoints` 表。`list_loop_checkpoints()` 是 repository 对 `loops` 的投影查询。

### 4. SQLite、任务和资源释放审计

#### 4.1 SQLite ownership

`RuntimeStorageRepository` 是唯一主要 SQLite owner；schema 通过外键和级联删除连接 PersonalModel → State → Episode → Loop → Step，并分别连接 semantic index、learning jobs、Paths、Facts、Questions、Diary。连接使用 context manager，普通写入显式 commit，学习 job claim 使用 `BEGIN IMMEDIATE`，checkpoint 写入后可立即重新读回验证。

但 schema 中没有 append-only `events`/`event_log` 表，也没有 LearningJob lease/heartbeat 字段。故以下三者必须分开：

- `steps`：可查询、可召回的执行证据，允许 repository 的 upsert/idempotent replay 语义。
- `learning_jobs`：SQLite 中的后台学习队列，有限重试但没有与 Path run 对等的租约回收。
- `gateway-outbound-queue.json`：带 `flock`、临时文件和 replace 的跨进程出站缓冲；它不是 SQLite 任务队列，也不是事件账本。

#### 4.2 资源 owner 和终态

| 资源 | 正常释放 | 已覆盖的失败路径 | 未闭环风险 |
|---|---|---|---|
| Episode session resources | `close_episode()` 调 `cleanup_session()`；closed 重入也 cleanup | cleanup 异常被吞掉，避免阻断 close | provider 普通异常可能绕过 close；cleanup 成功与资源真的关闭之间没有统一可观测结果 |
| API cancel callback | `run_loop()` finally 清理 ToolRuntime session callback | kernel 内 cancel 只在模型/工具循环边界感知 | provider 阻塞调用不会被同步中断；SSE consumer 断开不自动 set cancel event |
| API stream observers/delegates | worker finally 恢复 previous observer/delegate、unsubscribe、释放 global lock | worker 自然异常也走 finally | queue 满或客户端断开时 worker 生命周期可能脱离 HTTP response 生命周期 |
| Provider HTTP stream | generator 上下文关闭 response；首 chunk 前 retry，首 chunk 后转 incomplete | `ProviderSSEIncompleteError` 带 partial text | 普通 provider 异常从 Kernel.run 逸出时没有统一 Episode/Loop close |
| WeCom WebSocket | `start_gateway()` finally → `stop_gateway()` 关闭 task/socket/session/client | handshake/read error 重连；停止取消 task/futures | 已 `create_task()` 的 inbound dispatch 没有统一 task registry/await drain |
| Loop checkpoint | terminal/park 状态持久化，supervisor 刷 heartbeat | stale heartbeat 标记 detected，resume snapshot 去重 tool | supervisor 不执行真正 resume；`running` async tool 只返回 poll 计划 |
| Learning worker/job | job complete/fail 写状态；worker runtime 写 stopped record | 有限 attempt/backoff | active running job 在进程硬杀后的回收策略未与 Path lease 统一；可能遗留 running job |
| Gateway outbound row | complete 删除；release pending/backoff | attempts 达上限删除 | 无 durable dead-letter；坏 JSON 被当空队列/跳过，可能静默丢消息 |

### 5. 失败恢复结论

| 故障 | 当前可证明行为 | 不能宣称的行为 |
|---|---|---|
| tool 未注册/不可见/审批拒绝 | ToolRuntime 返回结构化 blocked/deferred，记录 lifecycle/执行摘要 | 不自动把拒绝变成重试或用户确认后的同一调用恢复 |
| tool executor 抛异常 | ToolRuntime 记录 failed lifecycle 和失败 ExecutionResult 后重新抛出；kernel tool loop 可把观察结果带回模型的路径需按具体调用验证 | 不是所有外部副作用都有统一 rollback；不是 exactly-once |
| provider HTTP 状态错误 | HTTP adapter 标注 status/headers/retry-after，普通请求按 RetryPolicy 有界重试 | 不代表 Kernel 已把所有异常归一为可恢复 ExecutionResult |
| provider SSE 中途断开 | 转 `ProviderSSEIncompleteError(partial_text)`，契约支持 checkpoint partial assistant | 不能宣称自动恢复；当前 supervisor 只整理 checkpoint，不重新生成 |
| 用户取消 | API Event → `cancel_check`；循环边界返回 cancelled，写 cancelled Step/Loop | 正在阻塞的 provider/tool 调用不保证立即停止；SSE disconnect 不保证取消已传到 worker |
| budget/wall-time 超限 | Loop park，写 WaitCondition/continuation/checkpoint，结果为 paused | 不能宣称 timer/event/tool callback 会自动重新进入 kernel |
| worker 崩溃 | 已提交 job/Step/checkpoint 仍在 SQLite；supervisor 可识别 stale Loop | `learning_jobs.status=running` 的自动租约回收和重派未形成与 Path run 同等的统一证明 |
| WeCom socket 断开 | 关闭坏 socket、取消 heartbeat、指数退避并重连 | 未完成 inbound dispatch 的跨重连 exactly-once、去重和 drain 需额外验证 |
| SQLite 锁/进程崩溃 | SQLite 事务边界保护已提交数据，claim 用立即事务避免多 worker 同领 | 未提交 Step、队列损坏、stale running job 的业务恢复策略不能仅凭事务推断 |

### 6. 测试覆盖与缺口

当前测试已对以下事实提供静态或集成级证据：

- `tests/integration/kernel/test_turn_lifecycle.py`：checkpoint step 重放覆盖、Kernel turn state/telemetry、checkpoint learning trigger。
- `tests/integration/harness/test_crash_recovery.py`：真实 SQLite 中 stale Loop 回收、partial assistant 清除、已完成 tool Step 跳过、未完成 tool replay 保留、第二次扫描幂等。
- `tests/e2e/api/` 与 `tests/e2e/gateway/`：API surface、Gateway identity/session、审批、多个平台适配器和重启后的 mapping/session 复用。
- `tests/integration/models_auth/`：provider adapter、HTTP fallback、响应解析和 reasoning 形状；不等于真实网络断流恢复。
- `tests/scenarios/continuity/`、`tests/scenarios/context/`、`tests/scenarios/recall/`：产品连续性、压缩、召回和恢复论点；部分是场景规范文件，不等于每项都有灾难注入测试。

仍缺少或当前核对未执行的高价值验收：

1. API SSE 客户端在 `assistant.delta` 中途断开后，确认 worker 终止、Queue 不堵塞、observer/delegate/lock/cancel map 无残留。
2. Provider SSE 首 chunk 后断流，确认 partial assistant 写入 SQLite checkpoint，重启后由真正 supervisor/调用面恢复，而不是只生成 `ResumeSnapshot`。
3. 普通 provider 异常、状态写入异常、delivery 异常分别确认 Loop/Episode 是否最终关闭、session resource 是否释放、learning job 是否不会错误入队。
4. 多个并发 API stream 确认全局 stream lock 的串行化是有意上限，而不是共享 observer 导致的隐性吞吐瓶颈。
5. WeCom 在 handshake、heartbeat、read、dispatch task 各阶段断开/取消，确认所有 asyncio task 都可枚举并收敛。
6. learning worker `SIGKILL` 后确认 running job 的回收、重试次数、result_json 幂等和 worker 重启竞争；分别与 Path Step Run 的 lease/heartbeat 语义对照。
7. gateway outbound queue 写坏、半写、进程杀死于 replace 前后，确认不会静默丢行，或至少有可查询 dead-letter/告警。
8. `ReconciliationPipeline` 产生的 event 在进程重启后按 event_id 读回；在当前 schema 下该断言应明确失败，不能用 Step 数量替代事件持久化。

### 7. 第四轮最终裁决

Elephant-Agent 的可复用主干是“surface → Kernel → Context/Recall → Model/Tool → Step/Loop/State → delivery → background LearningJob”，并已具备有限预算、取消边界、checkpoint 序列化、provider 首 chunk 前重试和 WeCom socket 重连。当前最可靠的事实记录是 Step、Loop/State、Fact 及其索引；不是 EventEnvelope，也不是 observer/SSE/WebSocket frame。

架构上必须保留以下分界：

- API SSE、provider SSE、WeCom WebSocket、gateway outbound JSON queue 是四种不同传输/恢复语义。
- Episode close、Loop checkpoint、LearningJob、Path Step Run 是四个不同状态机；不能以“任务”统称。
- `resume_support`/supervisor 目前是恢复判定和 checkpoint 整理层，不是完整的恢复执行器。
- 事件账本仍是缺口；`append_event()` no-op、无 events 表、无 event_id 重放查询，不能在平台映射或产品说明中写成已实现。
- 普通异常统一收口、SSE 断开资源终止、learning running job 租约回收、WebSocket dispatch drain 和出站死信仍是主要可靠性缺口。

当前核对未运行测试和服务，仅完成静态审计；因此不能把上表的源码路径存在性升级为 L3/L4 运行通过。
 # Elephant-Agent 架构取证
