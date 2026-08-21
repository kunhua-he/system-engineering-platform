```text
┌──────────────────────────────────────────────────────────────────────────────┐
│                               Client / Entry                                 │
│  import cognee  │  cognee-cli  │  FastAPI /api/v1/*  │  cognee-mcp (MCP)   │
│  Python SDK     │  argparse    │  auth + DTO + router │  stdio/SSE/HTTP      │
└───────────────┬──────────────┬───────────────┬───────────────┬──────────────┘
                │              │               │               │
                └──────────────┴───────┬───────┴───────────────┘
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                          Public application operations                        │
│  add()  cognify()  search()  remember()  recall()  improve()  forget()       │
│  serve() / disconnect() select local execution or remote CloudClient         │
└───────────────┬───────────────────────────────┬──────────────────────────────┘
                │                               │
       permanent memory path             session / typed-entry path
                │                               │
                ▼                               ▼
┌──────────────────────────────┐   ┌──────────────────────────────────────────┐
│ Ingestion + dataset boundary │   │ MemoryEntry discriminator + SessionManager│
│ resolve input / loaders      │   │ QAEntry / TraceEntry / FeedbackEntry      │
│ authorize dataset / DataItem │   │ SkillRunEntry                              │
└───────────────┬──────────────┘   └──────────────────┬───────────────────────┘
                ▼                                     ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                         Pipeline orchestration                                │
│  add_pipeline: resolve directories → ingest_data                              │
│  cognify_pipeline: classify → chunk → extract graph/summaries → persist       │
│  optional: provenance / contradiction / temporal resolution / memify           │
│  one logical run per dataset; per-item resolver selects standard/DLT/code      │
│  background executor + pipeline status + rollback/recovery                     │
└───────────────┬───────────────────────────────┬──────────────────────────────┘
                │                               │
                ▼                               ▼
┌──────────────────────────────┐   ┌──────────────────────────────────────────┐
│ Relational system store      │   │ Graph + vector + session stores            │
│ Dataset / Data / ACL / user  │   │ GraphDBInterface: nodes, edges, traversal  │
│ pipeline runs / migrations   │   │ VectorDBInterface: embeddings/search      │
│ provenance ledger (optional) │   │ CacheDBInterface: QA/trace/context/usage   │
└───────────────┬──────────────┘   └──────────────────┬───────────────────────┘
                └──────────────────────┬──────────────┘
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                          Retrieval / response layer                           │
│ recall scope: session / trace / session_context / graph / explicit tools      │
│ graph search: authorize dataset → set ContextVar → retriever registry         │
│ SearchType → concrete retriever → SearchResultPayload → normalized response   │
│ result source is tagged: session | trace | session_context | graph | tools    │
└──────────────────────────────────────────────────────────────────────────────┘
```

# Cognee 架构文档

## 1. 项目定位

Cognee 是一个面向 AI Agent 的 Python 开源长期记忆平台：把文本、文件、结构化输入、代码或会话内容写入数据集，经 ingestion/cognify 管线生成可检索的知识图谱、向量索引、摘要和会话记忆，再通过多种搜索/recall 入口返回带来源类型的结果。README 将其定位为 “The Open-Source AI Memory Platform for Agents”；`pyproject.toml` 的包描述则是为 LLM context 增加 semantic layer。仓库根 `LICENSE` 是 Apache License 2.0；再分发或改作仍须遵守该许可证的保留声明等条件。

它不是单一的向量 RAG 库，而是由以下几条并行能力组成：

- 永久记忆：`add()` 写入数据集，`cognify()` 把数据处理为图和向量，`search()`/`recall()` 查询。
- 会话记忆：`session_id` 使 `remember()` 写入 cache，`recall()` 可以按 session、trace、session context 查询。
- 结构化记忆：`MemoryEntry` 以 Pydantic 判别联合承载 QA、Agent trace、反馈和 skill run。
- 可选的 provenance、contradiction detection、temporal cognify、memify/self-improvement。
- 多租户/多数据集：关系型系统库保存权限和数据集注册；图、向量后端可按数据集隔离。
- 多种交付面：Python SDK、FastAPI、CLI、独立 MCP server、Next.js 前端和部署模板。

本文依据仓库当前源码；README 与已有 `细探-Cognee.md` 只作为导航和对照，live code 的符号名称优先。

## 2. 真实分层与职责

### 2.1 包级公共门面：`cognee/`

`cognee/__init__.py` 在一个包级入口集中导出：

- V1：`add`、`cognify`、`search`、`delete`、`update`、`datasets`、`config`、`memify`、`run_custom_pipeline`、`visualize` 等。
- V2 memory API：`remember`、`recall`、`improve`、`forget`、`serve`、`disconnect`、`push`、`export`。
- 管线类型：`pipelines`、`Drop`。
- 迁移、observability、`agent_memory`、工具连接和 session lifecycle models。

导入时先读取 `.env`、设置 logging，再导入公共 API；这意味着包级 import 不是纯惰性声明，会触发配置和部分模块注册。

### 2.2 接入层：API、CLI、MCP、前端

- FastAPI 应用位于 `cognee/api/client.py`。`app = FastAPI(...)`，lifespan 启动时运行关系库迁移、创建默认用户并恢复过期的 cognify runs；应用注册 `/api/v1/*` 路由、健康检查、CORS、认证异常和 Cognee API 异常处理。
- 路由按功能拆在 `cognee/api/v1/<feature>/routers/`，主要有 auth、add、cognify、memify、search、remember、recall、improve、forget、datasets、users、permissions、ontologies、visualize、sessions、integrations、slack、health、sync、validate、update、responses、skills 等。
- CLI 入口由 `pyproject.toml` 的 `cognee-cli = "cognee.cli._cognee:main"` 指定；`cognee/__main__.py` 也调用同一 `main()`。`cognee/cli/_cognee.py` 动态发现命令类，注册 add/search/cognify/remember/recall/improve/forget/serve/migrate 等命令；`--api-url` 时切换到 `cognee/cli/api_dispatch.py` 做 HTTP 委托，`-ui` 则启动前端、API 和 MCP 相关进程。
- MCP 独立包 `cognee-mcp/src/server.py` 以 FastMCP 建立服务器，支持 stdio、SSE 和 Streamable HTTP；启动时可直连本地 Cognee、API 模式或通过 `cognee.serve()` 连接云端。核心记忆工具是 `remember`、`recall`、`forget`，其余工具（workspace、数据集、图可视化、旧 V1 操作）通过 `ToolRegistry` 注册并可用 BM25 tool search 发现。
- `cognee-mcp/src/cognee_client.py` 是 direct/API 双模式适配器：direct mode 直接调用 `import cognee` 的函数，API mode 调用 `/api/v1/add`、`/cognify`、`/search`、`/remember`、`/recall`、`/improve`、`/forget` 等 HTTP 接口。
- `cognee-frontend/` 是 Next.js + React 前端；`package.json` 表明使用 Next 16、React 19、Mantine、TanStack Query、D3/force graph 等。前端是 UI 交付面，不是核心记忆引擎。

### 2.3 公共应用操作：`cognee/api/v1/`

#### 永久数据路径：`add()` → `cognify()`

`cognee/api/v1/add/add.py` 的 `add()`：

1. 接受字符串、文件路径、文件流、列表、DataItem 或 DLT 输入。
2. 建立 `Task(resolve_data_directories)` 与 `Task(ingest_data, ...)`。
3. `setup()` 初始化系统，解析授权数据集。
4. `resolve_dlt_sources()` 展开 DLT 输入；后台模式先物化 stream。
5. 通过 `get_pipeline_executor()` 执行 `add_pipeline`，并在成功提交后做 orphan cleanup。

`cognee/api/v1/cognify/cognify.py` 的 `cognify()`：

1. 执行迁移阻塞和 ontology resolver 配置。
2. 根据 `temporal_cognify` 选择标准或 temporal task list。
3. 用 `cognify_route_for(data_item)` 将每条数据路由到 `STANDARD`、`DLT_SOURCE`、`CODE`、`CODE_REPO` 之一；路由依据受保护的 `system_metadata`，不是用户的 `external_metadata`。
4. 调用一次 `get_pipeline_executor()`，把任务解析器传给 `run_pipeline`/`run_tasks`，因此同一数据集只有一个逻辑 pipeline run。
5. 失败时调用 `cognify_rollback_handler`；启动时由 `recover_stale_cognify_runs_on_startup()` 处理遗留的 started run。

标准 cognify task（`get_default_tasks()`）的源码顺序是：

`classify_documents` → `extract_chunks_from_documents` → `extract_graph_and_summarize` → `add_data_points` →（可选）`record_provenance` →（可选）`detect_contradictions` →（可选）`resolve_temporal_contradictions`。

DLT 路径是确定性的 manifest/row pipeline，不走 LLM graph extraction；代码文件和代码仓库走 code-graph tasks。

#### `remember()`：两条记忆通道的统一编排

`cognee/api/v1/remember/remember.py` 是较高层的统一入口：

- `MemorySource` 输入走 memory migration import，不允许与 `session_id` 或远端模式混用。
- `MemoryEntry` 输入短路 add+cognify，交给 `_dispatch_session_entry()`；`SkillRunEntry` 进入 graph-backed skill run，QA/Trace/Feedback 进入 SessionManager。
- 普通永久输入先 `add()` 再 `cognify()`，成功后按 `self_improvement` 调 `improve()`。
- 普通输入带 `session_id` 时写入 session cache；默认 `self_improvement=True` 会异步桥接到永久图。
- `run_in_background=True` 用 asyncio task 执行，并通过模块级 `_BACKGROUND_REMEMBER_TASKS` 保持强引用，避免 HTTP 响应序列化后任务被垃圾回收。
- `RememberResult` 统一表示状态、数据集、pipeline run、数据项数量、content hash、entry id 和错误信息；后台结果可 await。

### 2.4 Session / memory 层

`cognee/memory/entries.py` 定义当前源码真实使用的判别联合：

- `QAEntry(type="qa")`：question、answer、context、可选反馈和已使用 graph ids。
- `TraceEntry(type="trace")`：工具/函数名、状态、参数、返回值、memory query/context 和错误。
- `FeedbackEntry(type="feedback")`：通过 `qa_id` 更新既有 QA 的反馈。
- `SkillRunEntry(type="skill_run")`：skill id、任务、结果、success score、feedback、latency、candidate skills、tool trace 等，并验证 score/feedback/毫秒字段范围。

`MEMORY_ENTRY_TYPES` 用于运行时 `isinstance` 路由；`normalize_scope()` 把 `auto/all/graph/session/trace/session_context/tools` 标准化，其中 `tools` 不会被 `auto` 或 `all` 隐式启用。

`cognee/infrastructure/session/session_manager.py` 的 `SessionManager`：

- 接收 `CacheDBInterface` 实现，按 dataset UUID 生成隔离的默认 session id。
- `add_qa()` 生成 qa UUID，写 cache，调用 `index_session_qa()` 写会话向量，并记录 session activity。
- `add_agent_trace_step()` 生成 trace UUID，可用 LLM 生成反馈，失败时使用确定性 fallback；随后可触发 agent-context extraction。
- `get_session()`、`get_agent_trace_session()`、context entry 方法提供读写；修改文本会删除并重建 QA vector，纯反馈更新不重建向量。
- cache 不可用时，SessionManager 按方法语义返回空/False/None；completion 路径退化为无会话历史的普通 completion。

`cognee/infrastructure/databases/cache/cache_db_interface.py` 是 QA、trace、session-context、usage log、KV 和生命周期操作的抽象契约。仓库同时存在 FsCache、Redis、SQL 等 cache adapter 文件。

### 2.5 Pipeline 编排层：`cognee/modules/pipelines/`

- `modules/pipelines/tasks/task.py` 的 `TaskSpec`/`BoundTask` 支持装饰器、函数包装和延迟绑定；`Task` 根据函数类型执行 coroutine/generator/async generator，并处理 batch。
- `modules/pipelines/operations/run_pipeline.py` 把 `BoundTask` 链转换成 `Task`，串联前一步输出，并委托 `run_tasks_base()`，因此简化 API 复用 telemetry、provenance 和异常处理。
- `modules/pipelines/operations/run_tasks.py` 在一个 dataset 上创建一个 pipeline run，解析每条 item 的 task list，使用 semaphore 控制 `data_per_batch` 并发；所有 item 共享 start/complete/error 生命周期。失败时执行 rollback handler，再写 `PipelineRunErrored`。
- `cognee/pipelines/types.py` 定义单例 `Drop`；Task 执行器见到 `Drop` 就过滤该 item。`cognee/pipelines/__init__.py` 对旧的 Task/run_tasks/run_pipeline 导入做惰性兼容导出。
- `cognee/modules/cognify/estimator.py` 提供 `dry_run` 成本/Token 估算：复用真实分类器、分块器、提示词和响应 schema，但不调用 LLM、不 ingest、不写图结果；估算结构化 graph extraction 与 chunk summarization 两个阶段。它在读取前沿用 `cognify_route_for` 将 DLT/code/code-repo 分流（DLT 用 `row_count` 计数，代码管线按确定性路径计数），音频/图片给出跳过警告，远程 URL、目录和不支持的二进制输入拒绝；embedding、self-improvement 和转录成本不包含在估算内，reasoning model 的输出/成本也明确标记为近似值。

### 2.6 领域任务与图构建层

- ingestion：`cognee/tasks/ingestion/` 负责文件、URL、DLT、DataItem、loader 和 storage 输入。
- document/chunk：`cognee/tasks/documents/`、`cognee/modules/chunking/` 将原始 Data 变成 Document 和 DocumentChunk。
- graph extraction：`cognee/tasks/graph/` 与 `cognee/infrastructure/llm/extraction/` 通过结构化 LLM 输出生成节点、边、摘要。
- graph operations：`cognee/modules/graph/`、`cognee/modules/graph/cognee_graph/` 负责图元素、关系、RDF/ontology、时态冲突和 provenance 路由。
- retrieval/search：`cognee/modules/retrieval/` 提供 chunk、summary、RAG、hybrid、triplet、graph completion、temporal、agentic、code、Cypher、BM25 等检索器。
- memify/improve：`cognee/modules/memify/`、`cognee/tasks/memify/` 负责 triplet embedding、反馈权重、global context index、session bridge 等增强操作。
- ontology/truth/observability/tools/integrations 是横向或可选领域模块，分别处理 ontology grounding、truth alignment、OTEL/Langfuse、受控外部数据库工具、Slack 等。

### 2.7 存储和租户边界

关系型层由 `cognee/infrastructure/databases/relational/` 暴露 SQLAlchemy `Base`、异步 session、relational engine 和迁移 engine；Alembic 版本位于 `cognee/alembic/versions/`。它保存 users、datasets、ACL、Data、pipeline status/run、session lifecycle、provenance 和配置等系统元数据。

图和向量层通过两个协议隔离后端差异：

- `graph_db_interface.py`：节点/边增删查、邻居、子图、过滤、feedback/frequency/truth 权重以及 graph provenance source-ref 操作。
- `vector_db_interface.py`：collection、DataPoint、embedding、向量/文本 search、batch search、删除、prune 和按数据集创建/删除。
- `unified/unified_store_engine.py`：以能力位包裹 graph/vector engine；分离后端持有两个 adapter，共享后端可让两个属性指向同一 adapter，并统一 provenance delete/rollback。
- `unified/get_unified_engine.py`：读取 graph/vector ContextVar，判断 hybrid provider；普通路径组合 `get_graph_engine()` 与 `get_vector_engine_async()`，混合路径返回同一 adapter。

`dataset_database_handler/supported_dataset_database_handlers.py` 当前注册的主要 handler 是：Ladybug/Kuzu、Neo4j 多种模式、LanceDB、PGVector、Turso，以及 Postgres graph。AGENTS/README 说明默认本地组合是 Ladybug/Kuzu + LanceDB；启用 `ENABLE_BACKEND_ACCESS_CONTROL` 时图和向量都必须支持 dataset isolation，关系库仍为共享系统库。

Provenance 的细粒度实现位于 `cognee/modules/provenance/`：`ProvenanceManager` 是无状态异步门面，`track_entity`、`track_relationship`、`track_chunk` 通过 `storage.py` 写入共享关系库；普通跟踪写失败时记录日志并让宿主操作继续，用户主动执行的 `invalidate` 对未跟踪实体报错。`storage.append_chained_many()` 将批量写入放在单事务中，并组合事件循环级锁、Postgres advisory transaction lock、`sequence_id` 唯一约束和有界重试，避免并发追加造成链分叉。`integrity.py` 对字段做排序 JSON 规范化，以 `\x1f` 分隔后计算 SHA-256；除 checksum 外覆盖账本字段，实体 ID 使用可识别归档后缀剥离的规范形式，`verify_checksum()` 可检查字段篡改和链完整性。管理器本身不做用户/数据集隔离，cognify provenance task 必须使用带 dataset 前缀的 ID，读写双方保持同一命名空间。

## 3. 核心数据流

### 3.1 永久记忆写入

```text
输入(str/bytes/file/list/DataItem/DLT)
  → add(): resolve_data_directories + ingest_data
  → Data / Dataset / pipeline status 写入关系库
  → cognify(): 按 system_metadata 路由 task list
  → 分类与分块
  → LLM 结构化提取 Node/Edge/summary（标准路径）
  → add_data_points(): graph nodes/edges + vector embeddings
  → 可选 provenance ledger / contradiction / temporal resolution
  → remember() 可选 improve()，返回 RememberResult
```

`Data` (`cognee/modules/data/models/Data.py`) 是关系型数据记录，含 dataset_id、owner/tenant、content_hash、raw location、loader、pipeline_status、token_count、data_size、importance_weight 等；`Dataset` (`cognee/modules/data/models/Dataset.py`) 是用户可授权的数据集容器。

### 3.2 会话写入与图桥接

```text
remember(data, session_id)
  → _add_to_session() 或 typed MemoryEntry dispatcher
  → SessionManager
  → CacheDB: QA/trace/context
  → index_session_qa(): session vector
  → self_improvement=True 时后台 improve(session_ids=[...])
  → 永久图增强/会话同步
```

Typed QA/trace/feedback 需要 `session_id`；SkillRunEntry 可无 session_id 直接 graph-backed 持久化。`CACHING=false` 会让 session memory 不可用；AGENTS 明确说明该开关不是“只关闭缓存加速”，而是移除 session memory 能力。

### 3.3 Recall / Search 查询

```text
recall(query, scope, session_id, datasets/dataset_ids)
  → normalize_scope()
  → auto: 有 session 时 session/graph；无 session 时 graph
  → session/trace/session_context: cache 读取 + token-overlap/context builder
  → graph: 授权 dataset → ContextVar 设置 → query router（可选）
  → SearchType → retriever registry → graph/vector/LLM
  → SearchResultPayload
  → normalize_search_payload()
  → source-discriminated RecallResponse
```

`cognee/api/v1/recall/recall.py` 会把 session、trace、session context、graph 和显式 tools 结果合并，并给每个结果标记 `_source`/`source`。graph 查询由 `modules/search/methods/search.py` 授权后按 dataset context 执行，`get_search_type_retriever_instance.py` 将 `SearchType` 映射到具体 retriever；`FEELING_LUCKY` 另行选择策略。

`SearchResultPayload` 保留 `result_object`、`context`、`completion`、search type 和 dataset 身份；`RecallResponse` 是以 `source` 为 discriminator 的联合：`ResponseQAEntry`、`ResponseAgentTraceEntry`、`ResponseSessionContextEntry`、`ResponseGraphEntry`、`ResponseToolEntry`。

### 3.4 远端/API 数据流

```text
await cognee.serve(url, api_key)
  → CloudClient + health check + remote state
  → cognee.add/remember/recall/search/... 被 CloudClient 拦截
  → multipart/JSON POST 到 FastAPI
  → server router/auth → 本地应用操作和存储
  → JSON 结果返回 SDK/MCP/CLI
```

`cognee/api/v1/serve/serve.py` 支持 direct URL 和云端 Auth0 device flow；`cloud_client.py` 用 aiohttp、X-Api-Key 发送 HTTP。MCP 的 `CogneeClient` 则以 httpx 实现 direct/API 双模式，API 模式下会将文件转成安全 multipart 上传，session 文本使用 typed QA endpoint。

### 3.5 失败、恢复与删除

pipeline 运行记录由 `PipelineRunInfo`（status、pipeline_run_id、dataset_id、dataset_name、payload/data_ingestion_info）承载；`run_tasks.py` 在异常时写 error event 并调用 rollback handler。`cognify/rollback.py` 根据 graph provenance 能力选择 graph/vector source-ref 删除，或删除旧 relational ledger 记录；`cognify/recovery.py` 在启动时定位过期的 started run 并回滚、重置 pipeline status。

## 4. 关键类、函数、数据模型（相对路径）

| 角色 | 符号 | 相对路径 | 真实职责 |
|---|---|---|---|
| 包门面 | `__version__`, `add`, `cognify`, `search`, `remember`, `recall` | `cognee/__init__.py` | 汇聚 V1/V2、pipeline、migration、observability 导出 |
| 永久写入 | `add()` | `cognee/api/v1/add/add.py` | 解析输入、授权 dataset、执行 add_pipeline |
| 图构建 | `cognify()`, `get_default_tasks()` | `cognee/api/v1/cognify/cognify.py` | task 构建、路由和 cognify_pipeline 执行 |
| 统一写入 | `remember()`, `RememberResult` | `cognee/api/v1/remember/remember.py` | 普通/会话/typed/migration/remote 分发 |
| 统一读取 | `recall()` | `cognee/api/v1/recall/recall.py` | scope 解析、session+graph+tools 合并 |
| V1 搜索 | `search()` | `cognee/api/v1/search/search.py` | 参数校验、dataset 解析、调用 search module |
| memory 联合 | `QAEntry`, `TraceEntry`, `FeedbackEntry`, `SkillRunEntry`, `normalize_scope` | `cognee/memory/entries.py` | typed payload 与 recall scope 契约 |
| session 门面 | `SessionManager` | `cognee/infrastructure/session/session_manager.py` | cache QA/trace/context、session vector、反馈和会话 completion |
| cache 契约 | `CacheDBInterface` | `cognee/infrastructure/databases/cache/cache_db_interface.py` | session/cache/usage/KV 抽象 |
| 输入记录 | `Data` | `cognee/modules/data/models/Data.py` | 关系型数据项、content hash、dataset 和 pipeline metadata |
| dataset | `Dataset` | `cognee/modules/data/models/Dataset.py` | owner/tenant、ACL、configuration 和 dataset-scoped Data 视图 |
| 图抽象 | `DataPoint`, `Entity`, `Edge` | `cognee/infrastructure/engine/models/DataPoint.py`; `cognee/modules/engine/models/Entity.py`; `cognee/infrastructure/engine/models/Edge.py` | 图节点基础字段、确定性 Entity id、边权重/关系属性 |
| LLM 图结果 | `Node`, `Edge`, `KnowledgeGraph` | `cognee/shared/data_models.py` | 结构化 LLM 输出的节点/边/知识图谱模型 |
| chunk | `DocumentChunk` | `cognee/modules/chunking/models/DocumentChunk.py` | 文本、chunk index、所属 Document、entities/events、embedding 字段 |
| pipeline result | `PipelineRunInfo` 及 Started/Completed/Errored | `cognee/modules/pipelines/models/PipelineRunInfo.py` | 运行状态、run id、dataset、payload/ingestion info |
| pipeline task | `TaskSpec`, `BoundTask`, `Task` | `cognee/modules/pipelines/tasks/task.py` | 延迟绑定、批处理、Drop/enriches、函数类型执行 |
| pipeline run | `run_pipeline`, `run_tasks` | `cognee/modules/pipelines/operations/run_pipeline.py`; `run_tasks.py` | 简化链式运行与一个逻辑 run 的并发/状态/rollback |
| provenance API | `ProvenanceEntry` | `cognee/modules/provenance/models/ProvenanceEntry.py` | W3C PROV-O 风格 source/temporal/lineage/governance/hash 字段 |
| provenance integrity | `compute_checksum`, `verify_checksum` | `cognee/modules/provenance/integrity.py` | 排序 JSON + 分隔符 SHA-256，检查字段篡改和链完整性 |
| graph 协议 | `GraphDBInterface` | `cognee/infrastructure/databases/graph/graph_db_interface.py` | graph CRUD、traversal、权重、provenance 操作 |
| vector 协议 | `VectorDBInterface` | `cognee/infrastructure/databases/vector/vector_db_interface.py` | collection、embedding、search、delete、dataset backend |
| 统一存储 | `UnifiedStoreEngine` | `cognee/infrastructure/databases/unified/unified_store_engine.py` | graph/vector 能力门面和 provenance delete/rollback |
| 检索注册 | `get_search_type_retriever_instance` | `cognee/modules/search/methods/get_search_type_retriever_instance.py` | SearchType → retriever class/config |
| 结果模型 | `SearchResultPayload`, `RecallResponse` | `cognee/modules/search/models/SearchResultPayload.py`; `cognee/modules/recall/types/RecallResponse.py` | 统一 graph 结果与 source-discriminated recall 响应 |
| FastAPI app | `app`, `lifespan`, `start_api_server` | `cognee/api/client.py` | HTTP 应用、迁移/恢复生命周期、路由注册 |
| 远端 SDK | `serve`, `CloudClient` | `cognee/api/v1/serve/serve.py`; `cloud_client.py` | direct/cloud 连接和 HTTP API 代理 |
| MCP server | `main`, `remember`, `recall`, `forget` | `cognee-mcp/src/server.py` | MCP transport、tool registry、direct/API/cloud 入口 |

## 5. API / CLI / SDK 入口

### Python SDK

```python
import cognee
await cognee.add(data, dataset_name="main_dataset")
await cognee.cognify(datasets=["main_dataset"])
results = await cognee.search("query")
result = await cognee.remember("persistent memory")
results = await cognee.recall("query", session_id="s1")
await cognee.forget(dataset="main_dataset")
await cognee.serve(url="http://localhost:8000", api_key="...")
```

直接 `import cognee` 走本地存储；`await cognee.serve(...)` 后同一组 SDK 调用被路由到远端。

### FastAPI

- 启动模块：`python -m cognee.api.client`。
- 应用对象：`cognee.api.client:app`。
- 重点 REST：`POST /api/v1/add`、`POST /api/v1/cognify`、`POST /api/v1/search`、`POST /api/v1/remember`、`POST /api/v1/remember/entry`、`POST /api/v1/recall`、`POST /api/v1/improve`、`POST /api/v1/forget`。
- 其他 REST 覆盖 auth、datasets、permissions、users、sessions、visualize、ontology、settings、sync、health 和 integrations。

### CLI

- 安装脚本：`cognee-cli = "cognee.cli._cognee:main"`。
- `cognee/__main__.py` 允许 `python -m cognee`。
- 命令类集中在 `cognee/cli/commands/`，由 `_discover_commands()` 动态导入。
- `--api-url`/`--api-key`/`--api-token` 将命令转发到已运行的 API；`-ui` 启动 UI、backend 和 MCP 组合。

### MCP

- 目录：`cognee-mcp/`，脚本：`cognee = "src:main"`、`cognee-mcp = "src:main_mcp"`。
- 源码入口：`cognee-mcp/src/server.py` 的 `main()`。
- transport：stdio（默认）、SSE、HTTP；HTTP 默认路径 `/mcp`，另有 `/health`。
- memory tool：`remember`、`recall`、`forget`；可选 workspace tools 和可搜索的内部工具。

## 6. 技术栈与依赖

### 核心 Python

- Python `>=3.10,<3.15`；构建 backend 为 Hatchling；主包版本由 `pyproject.toml` 声明为 `1.5.0`。
- Pydantic 2 + pydantic-settings：API DTO、MemoryEntry、graph output、pipeline result、配置和 response model。
- FastAPI + Starlette + Uvicorn/Gunicorn：HTTP API 和 server lifecycle。
- SQLAlchemy 2 + aiosqlite + Alembic：关系型异步访问和迁移；Postgres 可选 psycopg2/asyncpg/pgvector。
- LLM：OpenAI SDK、LiteLLM、Instructor；`LLMConfig` 默认 provider 为 `openai`、model 为 `openai/gpt-5-mini`，可按 extraction/summarization/query stage 覆盖；支持 openai、ollama、anthropic、custom、gemini、mistral、azure、bedrock、llama_cpp、mcp-sampling 等 provider 名。
- 文本/数据：numpy、tiktoken、filetype、aiofiles/aiohttp、pypdf、Jinja2、rdflib、networkx、datamodel-code-generator。
- 图：Ladybug/Kuzu、Neo4j、Postgres graph（README 明确标注 Postgres graph 为 demo）、Turso、Neptune/社区能力通过 extras 或 adapter 路径扩展。
- 向量：LanceDB 默认路径、PGVector、Turso；社区适配器可通过额外依赖接入。
- cache/session：Redis 适配、文件 cache、SQL cache 等；`fakeredis`、`diskcache`、`aiolimiter` 等出现在主依赖。
- 可观测性：`structlog`；可选 OpenTelemetry OTLP 和 Langfuse（配置由 `base_config.py` 处理）。

### Optional extras（来自 `pyproject.toml`）

`scraping`、`fastembed`、`neo4j`、`neptune`、`postgres`、`postgres-binary`、`turso`、`notebook`、`langchain`、`llama-index`、`huggingface`、`ollama`、`mistral`、`anthropic`、`azure`、`deepeval`、`groq`、`llama-cpp`、`docs`、`codegraph`、`evals`、`graphiti`、`aws`、`dlt`、`gmail`、`baml`、`tracing`、`docling`、`rapidocr` 等。

### MCP / Frontend

- MCP：FastMCP `>=3.4,<4`、MCP SDK `>=1.24,<2`、httpx、uv；MCP 包依赖 `cognee[postgres-binary,docs,neo4j]`。
- Frontend：Next.js 16、React 19、Mantine 8、TanStack Query 5、react-force-graph、D3 force、Valibot、TypeScript 5、ESLint/Jest。

### 锁文件观察

`uv.lock` 与 `poetry.lock` 都存在；`uv.lock` 顶部同样声明 Python `>=3.10,<3.15`，并含 `exclude-newer`/平台 resolution markers。两套锁文件的部分解析版本并不完全相同，因此依赖版本以当前 `pyproject.toml` 约束和实际所选锁/平台为准，不能仅凭其中一个锁文件推断运行环境。

## 7. 测试覆盖与源码证据

仓库测试按 `cognee/tests/unit/`、`cognee/tests/integration/`、`cognee/tests/cli_tests/`、`cognee/tests/e2e/` 分层；本地 tracked 文件清点显示 `cognee/tests/` 下有 634 个 Python 文件，其中 564 个为 test-named 文件。MCP 另有 `cognee-mcp/tests/`。

本次实际读取的代表性测试证明了以下架构契约：

- `cognee/tests/unit/modules/cognify/test_cognify_single_logical_run.py`：DLT/code/code-repo/standard 路由、同一 dataset 一个逻辑 run、未映射路由抛错、task resolver 与 pipeline cache 组合。
- `cognee/tests/unit/modules/cognify/test_estimator.py`：dry-run 不调用 LLM；按 chunk 估算输入/输出 token 和费用；DLT/code 项目不读取原文；非法远程 URL、目录、非文本输入被拒绝。
- `cognee/tests/unit/modules/cognify/test_recovery.py`、`test_rollback.py`：stale run 启动恢复、图删除先于关系删除、graph provenance 和 relational rollback 分支。
- `cognee/tests/unit/api/v1/remember/test_remember_background_task_anchoring.py`：永久 remember 和 session→graph bridge 的后台 task 必须被强引用直到完成。
- `cognee/tests/unit/infrastructure/session/test_session_manager.py`：session 默认 id、QA/trace 写入、会话向量重建、cache 不可用时退化、自动反馈和 context 提取。
- `cognee/tests/unit/api/v1/recall/test_recall_api.py`：dataset_ids 优先于 dataset names、scope 解析、session_context profile、远端 forwarding。
- `cognee/tests/unit/modules/recall/test_normalize_search_payload.py`：completion/chunk/code/structured 结果归一化，chunk 的 data/chunk provenance metadata 保留。
- `cognee/tests/unit/modules/provenance/test_integrity.py`、`test_verify_chain.py`：checksum 的字段边界、防篡改、缺行链断、并发 append 的链完整性。
- `cognee/tests/unit/infrastructure/databases/graph/test_ladybug_temporal.py`：Ladybug temporal query 参数列表化和 legacy quoted ids 兼容。
- `cognee-mcp/tests/test_tool_search.py`、`test_tool_search_benchmark.py`、`test_mcp_server_hardening.py`：MCP tool search、可见工具层和 server hardening。

本次未安装依赖、未启动服务、未执行测试；测试结论来自实际读取的测试源码，而不是运行结果。

## 8. 架构判断

1. **分层边界清晰但仓库规模很大。** 公共 API/路由只负责编排和协议转换，任务模块负责认知处理，infrastructure 通过 graph/vector/cache/relational 接口隔离后端。`cognee/__init__.py` 的集中导出提高了 SDK 易用性，但也使包级导入触发配置、logging 和模型注册。
2. **永久图记忆与 session memory 是明确的双通道。** `remember()` 根据输入和 `session_id` 选择 graph pipeline 或 cache；session 结果可以异步 bridge 到永久 graph，不是把 cache 当作永久事实库。
3. **dataset 是权限和存储上下文的核心边界。** Dataset/ACL 在关系库，graph/vector engine 通过 ContextVar 和 handler 为每个 dataset 选择连接；recall/search 在授权后进入 dataset context。
4. **管线采用“一个逻辑 run + 每项路由”。** 这比按数据类型拆成多个独立 run 更适合 status、rollback 和 observability；对应测试明确把多种 item 绑定到同一 run id。
5. **provenance 是可插拔的审计增强，而非默认必经步骤。** `CognifyConfig.provenance_tracking` 默认 false；开启后 task list 加入 `record_provenance`，graph adapter 具备 source-ref 和 pipeline-run rollback 能力时可避免误删共享节点。
6. **检索策略是 registry/factory 架构。** `SearchType` 是公开策略枚举，factory 显式映射到 retriever；新增检索器主要扩展 registry，而不是改动所有 API。
7. **远端支持是 SDK/MCP 的薄代理。** 本地和 HTTP/cloud 模式共享高层语义，但 API 模式的能力边界不同（例如某些直接图访问/自定义 graph model/本地 prune 不可用），源码通过显式 `NotImplementedError` 或文档说明暴露这一点。
8. **可靠性设计集中在生命周期和回滚。** lifespan migrations、stale-run recovery、rollback handler、后台 task strong reference、source-ref provenance deletion 和测试中的顺序断言共同构成失败安全路径。
9. **已有 `细探-Cognee.md` 不是当前符号清单。** 它把当前源码中的 `TraceEntry`/`SkillRunEntry` 记作旧式的 AgentTraceEntry/SkillRunScoreEntry，且对整体分层进行了较窄的抽样；本架构文档以 `cognee/memory/entries.py` 和当前入口源码为准。

## 9. 未确认项与边界

- 本文没有读取运行时 `.env` 的有效配置，也没有启动服务，因此不能确认当前机器实际选择的 graph/vector/cache backend、实际 LLM key 是否可用、数据库是否已迁移或已有数据。
- `README.md`、`AGENTS.md`、`细探-Cognee.md`、`pyproject.toml`、`uv.lock`、`poetry.lock`、核心入口/模型/接口/管线源码、FastAPI/MCP/前端依赖和上述代表性测试已实际读取；未对每一个 retriever、loader、部署模板和前端页面逐文件审计。
- 没有执行 pytest、ruff、ty、npm build、MCP handshake 或 API smoke test，所以本文不声称当前 checkout 可运行或所有测试通过。
- `pyproject.toml` 中同时存在主依赖和大量 optional extras；某个后端/loader/LLM provider 是否可用还取决于安装的 extra、环境变量和外部服务。
- `cognee-mcp/src/server.py` 当前保留较多 V1/legacy/workspace 工具，而 README 将 memory API 描述为三项核心工具；工具可见性还受 `COGNEE_MCP_TOOL_MODE` 和 tool-search transform 影响。
- README 关于性能、云端和部署的描述没有在本次只读源码审计中复测；本文只采用其作为定位/入口说明，不把宣传性 benchmark 当作架构事实。

## 10. 旧细探收口记录

已完整读取 `细探-Cognee.md`，并逐项与当前源码和本文对照。本次吸收后，Cognee 架构事实后续只维护本文件；`细探-Cognee.md` 保留为历史细探，不删除，但不再作为第二个权威架构事实源。

### 已吸收并按当前源码校正

- **cognify 管线职责**：吸收旧细探提出的 routing、estimator、recovery、rollback、config 五类关注点；其中 estimator 的 dry-run 边界和 DLT/code 分流已按 `cognee/modules/cognify/estimator.py` 的实际实现补全。
- **provenance 证据链**：吸收 manager/integrity/storage 的分层和“来源记录 + 完整性校验”价值判断，并补成当前源码可验证的关系库账本、异步批量 hash-chain、并发锁、归档版本、失效 tombstone 和 dataset 命名空间约束。
- **判别式记忆条目**：吸收 QA/trace/feedback/skill 的类型路由、原始输入与结构化输入双路径；名称以当前 `cognee/memory/entries.py` 为准，保留 `Drop` 哨兵的单例、假值和过滤语义。
- **检索与平台边界**：吸收 recall 的语义/图谱/混合检索族、API/MCP/tools/ontology/graph/truth-subspace、评估/测试、前端和文档等旁路线索；本文已将它们放入真实目录、入口和检索 registry 的说明中，而不是把旁路线索写成核心执行链。
- **工程借鉴判断**：保留类型化记忆条目、provenance、Drop、recovery/rollback、estimator、原始数据与结构化知识双轨这六类可借鉴点；它们在本文的数据流、接口、失败恢复和架构判断章节中以源码事实为依据表达。
- **许可证和依赖边界**：补录根 `LICENSE` 的 Apache-2.0 事实；图、向量、LLM 依赖较重以及 Pydantic v2 契约已在技术栈和未确认项中保留，但不把旧细探的外部平台改造建议冒充 Cognee 当前实现。

### 未吸收或不按原文保留

- `AgentTraceEntry`、`SkillRunScoreEntry` 与当前源码冲突；当前事实是 `TraceEntry`、`SkillRunEntry`，因此仅吸收语义，不吸收旧类名。
- “原始数据统一走永久 `add+cognify`”过于绝对；当前 `remember()` 对带 `session_id` 的普通输入还会写 session cache 并可异步 bridge 到 graph，结构化 `MemoryEntry` 也有独立分发路径，故以本文两条记忆通道描述为准。
- 旧细探把 provenance 概括为“防篡改”但未说明默认关闭、关系库账本、并发链和租户命名空间；这些缺失已用源码实现补正，不保留其简化表述作为完整结论。
- “全英文命名”“平台应以独立进程适配重依赖”等属于编码规范或外部设计建议，不是当前 Cognee 架构事实，未写入事实章节。
- 旧细探对提示词原文、检索方法族和外围目录只给出导航级概括；没有足够证据支撑更具体的调用顺序或性能结论，因此未扩写为未经验证的实现承诺。

## 11. 第三轮：底座映射与唯一归属裁决

本节是**跨项目映射建议，不是 Cognee 的项目事实**。前文带有源码路径、函数名、测试路径的内容属于 `[项目事实]`；本节“建议进入支持库/模块库/运行核心/网关”属于 `[平台建议]`。平台建议不能反向证明 Cognee 已经接入目标平台，也不能作为平台现有能力、契约或已验收实现的证明。除本文件外，本轮没有修改 Cognee 源码、依赖、配置、测试或 README，也没有把建议写入平台生产目录。

### 11.1 第三轮裁决总表

| Cognee 能力/模式 | 当前源码证据 | 唯一建议归属 | 裁决 | 边界 |
|---|---|---|---|---|
| `MemoryEntry` 判别联合、`QAEntry`/`TraceEntry`/`FeedbackEntry`/`SkillRunEntry`、scope 规范化 | `cognee/memory/entries.py`；`cognee/api/v1/remember/remember.py:237-407` | 支持库（公共记忆契约） | 吸收为契约样本 | 只吸收类型判别、版本化和错误形状；不复制 Cognee 的 SessionManager 实现 |
| provenance 规范化、checksum、链式追加和完整性校验 | `cognee/modules/provenance/{manager,storage,integrity}.py`；本文 §2.7、§3.5 | 支持库（证据完整性原子能力） | 吸收 | 证据账本的权威写 owner 仍需由平台另行确认；Cognee 的 dataset 前缀不能直接当平台租户契约 |
| Graph/Vector/Cache/Relational 接口和后端适配边界 | `cognee/infrastructure/databases/*/*_interface.py`、`unified_store_engine.py` | 支持库（provider/适配层） | 吸收边界，不搬实现 | 第三方驱动、LLM、数据库连接只能作为受管 provider；不允许模块直接持有 provider 对象穿透契约 |
| `add()`/`cognify()`/`remember()`/`recall()`/`search()` 的记忆领域编排 | `cognee/api/v1/{add,cognify,remember,recall,search}` | 模块库（记忆领域模块） | 吸收模式 | 只吸收“入口→路由→任务→结果”的领域编排；不把 FastAPI、MCP、云端代理或具体数据库并入模块 |
| cognify 的标准/DLT/code/code-repo 路由及 task 顺序 | `cognee/api/v1/cognify/cognify.py:274-336,351-522`；`modules/cognify/routing.py` | 模块库（认知处理模块） | 吸收为可选模块设计 | 路由依赖 Cognee 的 `system_metadata`，不是通用平台事实；不能把其 LLM 提示词和 route 枚举当作平台契约 |
| pipeline run 的 Started/Completed/Errored 状态、并发、超时/取消/崩溃治理 | `modules/pipelines/operations/run_tasks.py`；`pipeline_execution_mode.py`；`cognify/recovery.py` | 运行核心（通用运行治理） | 只吸收缺口与验收要求 | Cognee 当前实现不是平台运行核心；运行核心应重新定义统一状态、取消、截止时间、进程组清理和证据契约 |
| FastAPI REST、CLI、CloudClient、MCP stdio/SSE/HTTP | `cognee/api/client.py`；`cognee/cli/`；`cognee-mcp/src/{server.py,cognee_client.py}` | 网关（协议适配层） | 吸收薄适配思想 | 网关只做认证、协议转换、限流、流式和错误映射；不得把 `remember`/`cognify` 的业务流程复制到各入口 |
| 外部 LLM、Ladybug/Kuzu、LanceDB、Neo4j、PGVector、Redis、enola | `pyproject.toml`；`cognee/infrastructure/`；`tasks/code_graph/enola.py` | 支持库（provider 隔离） | 仅作为 provider 样本 | 版本、可用性、崩溃、超时和许可证必须单独验收；不能把 optional extra 的存在写成宿主可用 |
| ontology、truth_subspace、memify/self-improvement、skills、Slack、前端、部署模板 | `cognee/modules/{ontology,truth_subspace,memify}`、`cognee-frontend/`、`distributed/deploy/` | 仅研究参考 | 暂不进入底座 | 需要独立需求、契约和真实外部依赖验收；本轮没有足够证据证明它们是平台公共原子能力 |
| Cognee 整体产品/图+向量+LLM 组合 | 当前仓库整体 | 仅研究参考 | 明确不整体迁移 | 保留架构模式和失败证据，不复制第二套记忆内核、存储层或网关 |

**唯一归属规则：** 领域编排只归模块库；跨领域资源状态、取消、超时、崩溃恢复只归运行核心；传输协议只归网关；可复用的纯契约、规范化、完整性、provider 边界才归支持库；无法满足单一 owner 或尚未具备验收证据的能力留在研究参考。一个能力不能同时在模块库和运行核心各保留一套实现。

### 11.2 底座映射流程图（建议，不是项目运行流）

```text
上层业务/Agent
  → 网关：REST / MCP / CLI 协议适配、认证、限流、流式
  → 模块库：记忆领域入口、scope 路由、认知任务编排、结果归一化
  → 支持库：MemoryEntry/结果/证据完整性/Graph-Vector-Cache provider 契约
  → 运行核心：run 状态、租约、截止时间、取消、进程组、崩溃恢复、残留审计
  → 受管 provider：数据库、向量库、图库、LLM、外部 CLI
```

这张图是目标平台的候选落点，不是 Cognee 当前调用链；Cognee 当前调用链仍以本文 §3 的 `remember → add/cognify → storage → recall` 为事实。

### 11.3 契约补全与未决语义

| 契约对象 | 当前源码可确认的输入/输出 | 失败、超时、取消、幂等与兼容语义 | 当前证据级别 |
|---|---|---|---|
| `remember()` | 输入可以是文本、文件流、`DataItem`、`MemorySource` 或 `MemoryEntry`；普通永久路径进入 add+cognify；typed entry 进入独立 dispatcher；返回 `RememberResult` 或 dry-run estimate | `MemorySource` 禁止 remote、`dataset_id` 和 `session_id` 组合；typed QA/trace/feedback 缺 `session_id` 抛 `ValueError`，cache 不可用抛 `RuntimeError`；后台结果 `await` 后不重新抛出任务异常，而写入 `status/error`；源码未给出统一取消 API、幂等键或重试契约 | 源码事实；未运行 |
| `RememberResult` | `status` 可为 `running`、`completed`、`errored`、`session_stored`；有 dataset、pipeline run、entry、items、elapsed、error 等字段；`done` 表示任务结束 | `_resolve()` 把 PipelineRun 状态映射为 completed/errored；`__await__` 使用 `shield` 等待且不重新抛出；不应把 `bool(result)` 当作“后台已执行”，它只对 completed/session_stored 为真 | 源码 + 定向测试源码；未运行 |
| typed `MemoryEntry` | `QAEntry`、`TraceEntry`、`FeedbackEntry` 需要 session；`SkillRunEntry` 可 graph-backed 且可无 session；反馈以 `qa_id` 更新既有 QA | 不支持类型抛 `TypeError`；SessionManager 返回 `None`/`False`/空集合的地方与 dispatcher 的硬失败并存，不能抽象为一个统一“cache 缺失”结果码；版本兼容和跨服务序列化版本未在本仓库中形成独立契约 | 源码事实；契约未完全固化 |
| `cognify()` / `run_tasks()` | 一个 dataset 形成一个逻辑 pipeline run；每个 item 可由 resolver 选 task list；`data_per_batch` 由 semaphore 限制；完成前先 flush graph/relational push，再写 Completed | 普通异常进入 rollback handler，再写 Errored；rollback 失败只日志记录；源码没有 `run_tasks()` 级全局 deadline 或公开 cancel；`asyncio.gather()` 未设置 `return_exceptions=True`，不能把后续 BaseException 汇总分支误读为所有子任务都可收集 | 源码事实；定向测试源码；未运行 |
| pipeline run 状态 | `PipelineRunStarted` 在后台/阻塞执行器首先产生；终态是 `PipelineRunCompleted` 或 `PipelineRunErrored`；启动恢复只关注最新的 `DATASET_PROCESSING_STARTED` | stale 判定是 `created_at` 超过 `COGNEE_STALE_RUN_RECOVERY_MIN_AGE_SECONDS`（默认 3600 秒）的年龄启发式，不是 heartbeat/lease；没有证据表明近期运行可被安全强杀后立即精确恢复 | 源码 + recovery 测试源码；未运行 |
| `search()` / `recall()` | `recall` 规范化 scope，合并 session/trace/session_context/graph/tools，并用 source discriminator；graph 路径先授权 dataset 再设 ContextVar 和 retriever | scope、授权、provider 不可用、LLM 失败的最终统一错误形状需按各入口分别验证；本轮没有 API smoke、真实 graph/vector、MCP handshake，因此不宣称端到端返回稳定 | 源码事实；未执行 |
| `serve()` / API / MCP | SDK 可切换 direct/cloud；FastAPI 注册 `/api/v1/*`；MCP 支持 stdio/SSE/HTTP，direct/API 双模式 | remote 下部分本地能力显式不支持；网络断开、连接超时、客户端断开后的请求/流式清理没有由本轮统一测试证明；各入口错误映射不能直接当平台网关错误码 | 源码事实；未执行 |

**契约缺口裁决：** 取消、全局超时、幂等键、重试预算、租约心跳、跨进程恢复证据、统一错误码和版本迁移不应从 Cognee 当前实现“推定存在”。它们是进入运行核心前必须补写的目标契约，不是本项目已经具备的事实。

### 11.4 关键节点与证据链

| 节点 | 前置条件 | 实际动作与状态变化 | 失败/恢复 | 证据路径 |
|---|---|---|---|---|
| `remember` 分发 | 远端状态、输入类型和 `dry_run` 组合合法 | 先按 `MemorySource`、typed entry、普通输入分流；普通输入进入本地或远端路径 | 非法组合 `ValueError`；typed cache 不可用可 `RuntimeError`；后台普通路径通过 result 记录错误 | `cognee/api/v1/remember/remember.py:744-884`、`:925-985` |
| `add` 入口 | 可解析输入、授权 dataset、系统 setup | 建 `resolve_data_directories` 与 `ingest_data` 任务，执行 add pipeline | 失败由 pipeline 状态/异常路径承担；本轮未执行真实 loader | 本文 §2.3；`cognee/api/v1/add/add.py` |
| `cognify` 配置/路由 | migrations 完成、ontology resolver 可构造、dataset 可访问 | 生成标准/temporal/DLT/code/code-repo task 列表，按 `system_metadata` 解析 item | 未映射 route 抛 `KeyError`；dry-run 禁止 temporal/remote，并不写图 | `cognee/api/v1/cognify/cognify.py:253-336`、`:351-522` |
| `run_tasks` 启动 | dataset 可读、user 可解析 | 关系库记录 Started，产生 pipeline id；设置 dataset/owner/LLM/embedding ContextVar | 连接/状态写入失败进入外层异常；取消没有专门终态落账 | `cognee/modules/pipelines/operations/run_tasks.py:60-87` |
| item task 执行 | task 列表通过校验、batch semaphore 可用 | 每 item 建 `PipelineContext`，按 `data_per_batch` 并发执行 | 子项异常可触发 run 失败；异常聚合代码存在但 `gather` 默认行为限制其适用范围 | `run_tasks.py:94-168` |
| 提交终态 | item 全部成功、graph/relational push 成功 | 先 flush 外部持久化，再写 Completed 并产出 Completed 事件 | push 或 task 失败先 rollback，再写 Errored；rollback 自身失败只记录日志 | `run_tasks.py:169-225` |
| rollback | run id、dataset id 可得 | graph provenance 分支删除 source refs；旧 relational 分支先删除 graph/vector，再删关系行并清 pipeline status | graph/vector 删除失败时关系元数据保留，便于重试；这不是“所有资源已回滚”的证明 | `cognee/modules/cognify/rollback.py:107-136,214-265`；`test_rollback.py` |
| startup recovery | API lifespan 启动、latest run 可查询 | 只恢复最新且足够老的 Started run，调用 rollback 后 reset status | dataset 不存在则跳过；恢复失败记日志；年龄阈值可能误留长任务或误判已死任务 | `cognee/modules/cognify/recovery.py:43-135`；`test_recovery.py` |
| API shutdown | FastAPI lifespan 正常退出 | cache-clear graph/vector engine，意图是让存储 WAL 在退出前完成收尾 | SIGKILL 等非正常退出不经过 lifespan；本轮没有强杀后 WAL/残留实测 | `cognee/api/client.py:66-107` |

### 11.5 资源生命周期与残留边界

| 资源 | 创建/持有 | 正常释放 | 失败/超时/取消/崩溃现状 | 不能假定的结论 |
|---|---|---|---|---|
| 关系库 async session/事务 | `get_async_session()` 上下文；pipeline 状态、Data、ACL、provenance | `async with` 退出；rollback 路径显式 commit 状态重置 | SQL/进程崩溃时由数据库和启动恢复共同承担；取消分支未在 `run_tasks` 明确实现 | 不能假定每次取消都写 Errored 或完成 rollback |
| graph/vector engine | dataset ContextVar 选择；统一 engine 持有 graph/vector adapter | API lifespan 对缓存工厂 `cache_clear()`；正常 run 在 Completed 前调用 push | graph 删除失败保留关系回滚元数据；非正常进程退出的 WAL/adapter 清理未由本轮执行证明 | 不能把 adapter 接口存在写成后端已安装/可用 |
| cache/session QA 向量 | `SessionManager.add_qa()` 写 cache 后 `index_session_qa()`；更新时删旧向量再重建 | `delete_qa` 删除向量；`delete_session` 清 graph snapshot/context/session | cache 不可用时部分方法空返回，typed dispatcher 硬失败；自动 context extraction 失败 fail-open | 不能把 fail-open 误写成数据已持久化 |
| pipeline background task | `asyncio.create_task()`；模块集合 `_BACKGROUND_PIPELINE_TASKS` 强引用 | done callback 从集合移除；remember 另有 `_BACKGROUND_REMEMBER_TASKS` | result 被丢弃仍不被 GC；没有公开取消、超时后任务排空或任务组强制终止契约 | 强引用只证明任务不被 GC，不证明任务最终成功或可回滚 |
| enola 外部进程 | `create_subprocess_exec`，stdout/stderr pipe，cwd 为仓库 | `communicate()` 完成后进程自然退出 | `wait_for` 超时执行 `process.kill()` 再 `wait()`；非零码/缺 `facts.jsonl` 抛错误；输出 `.enola` 的清理不在该函数 | 不能把单个 CLI 的 timeout 处理扩展成全 Cognee pipeline 的取消治理 |
| 临时/生成文件 | loader、技能 materialize、enola snapshot、数据库后端各自创建 | 由各子模块决定；本轮只确认技能目录按 dataset hash 稳定命名、enola 产物目录存在 | 没有全仓统一“异常后残留扫描”证据；崩溃可能留下 snapshot、锁或 WAL | 不声称零临时文件、零锁、零进程残留 |

### 11.6 失败、超时、取消、崩溃与“防假绿”矩阵

| 场景 | 源码行为 | 证据状态 | 防假绿要求 |
|---|---|---|---|
| 参数非法/不支持组合 | 多处 `ValueError`，如 remote dry-run、MemorySource 与 session/dataset_id 冲突、typed entry 缺 session | 有测试/源码分散证明，未统一运行 | 必须断言异常类型、关键消息和没有写入；不能只看 HTTP 400 |
| provider 缺失/后端不可用 | optional extras 和 adapter 在运行时决定；部分入口会抛配置/系统错误 | 未在本轮安装或探测真实 provider | 需要缺库、空 key、断网和 backend unsupported 的非 skip 测试；“导入成功”不是 provider 可用 |
| 单 item 失败 | `run_tasks` 构造 Errored 信息并触发 rollback；`gather` 默认取消/传播行为须单独验证 | `test_rollback.py` 为 mock 单元证据，未执行 | 必须读回 pipeline 状态、graph/vector、关系行和 rollback 顺序；不能以日志“rollback completed”作证据 |
| rollback 失败 | rollback 异常被记录，随后仍写 PipelineRunErrored；关系元数据按删除顺序尽量保留 | 有定向测试源码，未执行 | 需注入 graph 删除失败，确认关系回滚元数据仍在且重试可识别，不能把 Errored 当清理完成 |
| timeout | enola、部分 LLM/embedding/session 子路径使用 `wait_for`；pipeline 顶层没有统一 deadline | 有源码，未执行 timeout 回归 | 必须检查被杀进程、pipe、锁、临时目录和最终 run 状态；仅捕获 `TimeoutError` 不足以证明清理 |
| 主动取消 | 若干 LLM/retrieval 代码显式让 `CancelledError` 不重试；`run_tasks` 外层仅 `except Exception`，未见专门 cancel 分支 | 未见 pipeline 取消契约测试 | 必须单独注入 `Task.cancel()`，断言取消是否写状态、是否 rollback、是否排空子任务；禁止把普通异常测试当取消测试 |
| worker/API 崩溃 | API 启动时只对最新、足够老的 Started cognify run 做 rollback + reset；阈值默认 3600 秒 | `test_recovery.py` 只读测试源码，未执行；无强杀端到端证据 | 独立进程 SIGKILL 后重启，读回数据库、graph/vector、WAL、锁和 pipeline 状态；年龄阈值不能替代 heartbeat |
| background result 丢失 | 模块集合强引用 task，完成后移除；测试覆盖 GC 期间仍在运行 | 测试源码存在，未执行 | 要等待任务完成并确认集合移除、错误落在 result/状态；不能只断言 task 在集合中 |
| 流/客户端断开 | MCP/API 有多种 transport；本轮没有统一客户端断开/半关闭测试 | 仅源码证据 | 需真实连接断开后确认服务端 task、socket、队列和临时资源收敛 |

#### L0-L4 验证等级

| 等级 | 含义 | 本轮可给 Cognee 的判定 |
|---|---|---|
| L0 | 只有目录、符号或声明存在 | 所有映射候选至少有 L0；optional extra 只能停在此级 |
| L1 | 已读源码并能指出输入、状态、异常和资源路径 | 核心入口、pipeline、rollback、recovery、API lifespan、enola timeout 达到 L1 |
| L2 | 定向测试源码存在，且测试断言对应真实生产接口 | remember background anchoring、recovery、rollback、cognify routing 等达到“有 L2 测试源码”；本轮未执行，不能写“L2 已通过” |
| L3 | 本轮真实执行，含真实数据库/图/向量/HTTP/MCP/外部进程，并读回状态 | 本轮未执行；所有项目能力均不得标 L3 |
| L4 | 独立进程强杀/取消/超时/重启，读回无半成品、无进程/锁/临时残留，并有可重复验收命令 | 本轮未执行；崩溃恢复、取消和残留治理全部未达 L4 |

本轮严格结论是：**源码和测试源码证明了若干设计意图，不等于当前 checkout 已通过真实运行验证**。旧细探和本文件中的“测试覆盖”章节只能说明测试源码存在；本次没有安装依赖、启动 API/MCP、连接真实 graph/vector/LLM、执行 pytest、模拟超时/取消、强杀恢复或做残留扫描。

### 11.7 平台接入前置验收契约（建议）

以下是平台建议的“进入底座前”门槛，不是 Cognee 已有能力：

1. **契约门**：为记忆条目、领域操作、pipeline run、错误码、取消、deadline、幂等和版本兼容各给稳定 schema；明确 cache unavailable 是空结果还是硬失败，禁止同一能力按入口漂移。
2. **唯一 owner 门**：每个能力只能有一个能力 id、一个注册入口、一个模块 owner；Graph/Vector/Cache provider 不能被多个模块各自包装成第二套调用器。
3. **资源门**：对关系连接、graph/vector adapter、cache vector、background task、外部进程、stdout/stderr pipe、临时目录和锁逐项证明正常、业务失败、超时/取消、崩溃四条释放路径。
4. **失败门**：真实注入 provider 缺失、非法输入、部分写入、graph 删除失败、LLM 超时、客户端断开、worker SIGKILL；每个场景读回权威状态和残留，而不是看日志或返回 200。
5. **反向门**：删除/禁用关键 provider、移除 rollback、吞掉错误、跳过等待或伪造 Completed 时，验证必须转为失败；测试不得用 mock 返回“看起来成功”的值代替真实执行。
6. **门禁门**：L0-L2 只能算研究输入；至少 L3 才能成为底座候选；涉及取消、超时、崩溃、跨进程资源的能力必须有 L4，未达标只能标“待核/仅研究参考”。

### 11.8 最终唯一归属清单

| 归属 | 只允许接收的 Cognee 研究产物 | 本轮是否进入目标平台 |
|---|---|---|
| 支持库 | 记忆条目/结果 schema、证据 checksum/规范化、provider 接口和隔离边界 | 否；形成候选清单，等待需求登记与 L3/L4 验收 |
| 模块库 | remember/cognify/recall 的领域编排、scope 和结果归一化模式 | 否；仅形成模块边界，不复制 Cognee 业务代码 |
| 运行核心 | pipeline run 状态、deadline、取消、租约、进程组、崩溃恢复和残留审计需求 | 否；当前 Cognee 的年龄式 recovery 不能直接作为通用运行核心 |
| 网关 | FastAPI/MCP/CLI 的协议适配、认证、流式和错误转换模式 | 否；不能把 `cognee-mcp` 当作平台唯一网关实现 |
| 仅研究参考 | 全体产品组合、前端、部署、ontology/truth/memify/skills/评估和未验证 provider | 是；保留为研究参考，不进入生产底座 |

这份唯一归属清单完成第三轮裁决，但不构成平台改造授权。若后续要落地，必须另行登记能力需求、复用裁决、消费者契约、资源/验收契约和装配计划；在此之前，Cognee 只能作为研究输入。

## 12. 第二轮架构收口：真实契约、调用链与生命周期

本节是本轮对真实源码的收口补充。它不把函数注释、README 或测试名称当成已运行证据；路径后的行号是本轮读取的源码定位，验证等级仍按 §11.6 的 L0-L4 解释。凡标注“未运行”的内容，都只能说明静态行为已定位，不能说明当前环境可用。

### 12.1 公开契约的实际边界

| 入口/对象 | 输入和输出的真实形状 | 已确认的前置条件、状态和错误 | 未提供的契约 |
|---|---|---|---|
| `add()` | `str`、文件路径/URL、`BinaryIO`、`DataItem`、列表或 DLT 对象；先解析并写入关系库 `Data`，返回单个 `PipelineRunInfo`（后台时为 Started 信息） | `resolve_authorized_user_dataset()` 先解析写权限；`resolve_dlt_sources()` 先展开 DLT；`reset_dataset_pipeline_run_status()` 清理旧运行状态；后台输入会先物化 stream | 没有公开幂等键；content hash/data id 只提供数据集内去重线索，不等于请求级幂等。未运行真实 loader/provider |
| `cognify()` | 数据集名或 UUID 列表；返回 blocking 的 dataset→run 信息或 background 的 Started 信息；`dry_run` 返回估算对象 | 先阻塞迁移，再构造 task；`dry_run` 拒绝 `temporal_cognify` 和远端模式，且不调用 LLM/不写图；未映射 `CognifyRoute` 直接 `KeyError` | 没有顶层 deadline、公开取消 API、重试预算或“估算等于实际成本”保证 |
| `remember()` | 原始数据、`MemorySource` 或判别式 `MemoryEntry`；普通路径返回 promise-like `RememberResult`，估算返回 `DryRunEstimate` | `MemorySource` 禁止 `dry_run`、`dataset_id`、`session_id`、remote；typed entry 禁止 `dry_run`/`dataset_id`，QA/Trace/Feedback 需要 session；不支持 entry 抛 `TypeError` | `await result` 只等待任务并返回 result，不把任务业务异常重新抛出；但调用者自身被取消时 `shield` 不会吞掉外层 `CancelledError`。没有取消后状态契约 |
| `recall()` | 查询文本 + `scope`/session/dataset/search type 等；返回 `list[RecallResponse]`，`source` 区分 session、trace、session_context、graph、tools | `dataset_ids` 优先于 names；graph 先授权再设置 dataset ContextVar；显式 tools 且未启用时硬失败 `ToolCallsDisabledError`；多 dataset 的 CODE seed miss 被包装为单 dataset 结果 | 各 retriever/provider 的错误没有统一错误码；scope 内多源是顺序执行，不是一个事务，也没有跨源一致性/截止时间 |
| `search()` / `authorized_search()` | `query_type` 为 `SearchType`；可跨授权 dataset；底层返回 `SearchResultPayload`，V1 再做兼容性降级 | `top_k<=0` 在 retriever factory 抛 `QueryValidationError`；`FEELING_LUCKY` 二次选择实际 retriever；禁止 Cypher 时抛 `UnsupportedSearchTypeError`；空图只记录 warning，不自动 cognify | 结果数量/排序由具体 retriever 决定；没有统一“空图/空结果/LLM 失败”的响应协议 |
| `run_tasks()` | 固定 task 列表或 `data_item -> task list` resolver；一 dataset 一个 `pipeline_run_id`；按 `data_per_batch` semaphore 并发 | 先 Started，再设置数据库/LLM/embedding context；单 item 结果汇总后 flush，再 Complete；普通异常走 rollback + Errored | `asyncio.gather()` 未设置 `return_exceptions=True`，所以后置的 BaseException 汇总分支不能当作“所有子任务都被收集”；`CancelledError` 不进入 `except Exception` 回滚分支 |

### 12.2 摄取、图谱写入和检索的逐节点调用链

#### A. 标准永久记忆写入链

```text
remember(raw)
  → add()
    → resolve_authorized_user_dataset()
    → resolve_dlt_sources()
    → Task(resolve_data_directories)
    → Task(ingest_data)
      → save_data_item_to_storage()
      → open_data_file() + ingestion.classify()/identify()
      → dataset 内 content hash/data id 解析或 uuid4()
      → data_item_to_text_file() + Data 关系记录
    → run_pipeline(add_pipeline)
  → cognify()
    → get_default_tasks()
      → classify_documents
      → extract_chunks_from_documents
      → extract_graph_and_summarize
        → asyncio.gather(extract_graph_from_data, summarize_text)
      → add_data_points
        → get_graph_from_model + deduplicate
        → graph/vector 写入与 embedding
      → [record_provenance]
      → [detect_contradictions]
      → [resolve_temporal_contradictions]
    → run_tasks()：Started → 每 item task → durable flush → Completed
```

证据：`cognee/api/v1/add/add.py:251-325`、`cognee/tasks/ingestion/ingest_data.py:35-160`、`cognee/api/v1/cognify/cognify.py:274-430`、`cognee/tasks/graph/extract_graph_and_summarize.py:12-37`、`cognee/tasks/storage/add_data_points.py:39-212`、`cognee/modules/pipelines/operations/run_tasks.py:63-225`。`add_data_points()` 的非 hybrid 路径先在关系库事务内写 legacy rollback ledger，再并行写 graph nodes/vector points 与 graph edges/vector edges；graph provenance 非 hybrid 路径可将 source ref 折叠进 graph 写入，hybrid 路径仍有第二次 attach 窗口。故“图、向量、关系库一次原子提交”不是当前真实契约。

#### B. DLT、代码和 temporal 分支

| 分支 | 真实 task 链 | 关键差异 |
|---|---|---|
| `STANDARD` | 标准五步 + 可选 provenance/contradiction/functional relationship | 结构化 LLM 抽取 + 摘要；默认 `provenance_tracking`、`contradiction_detection` 由配置控制 |
| `DLT_SOURCE` | `classify_documents` → `purge_stale_dlt_source_artifacts` → chunk → `add_data_points` → `extract_dlt_source_edges` | 不做 LLM graph extraction；稳定 manifest id 先清理旧派生物，再写确定性 row/chunk/schema/FK edge |
| `CODE` / `CODE_REPO` | `get_code_file_tasks()` / `get_code_repo_tasks()` | 代码图任务调用 enola；不是标准文本 LLM graph 路径 |
| `TEMPORAL` | classify → chunk → `extract_events_and_timestamps` → `extract_knowledge_graph_from_events` → add points | 由 `temporal_cognify=True` 整体选择，不与 dry-run 组合 |

`cognify()` 在同一个 pipeline run 中使用 `tasks_by_route` resolver；不同 item 可以走不同 task list，但共享 run、context、终态和 rollback。证据：`cognee/api/v1/cognify/cognify.py:294-336,433-522`、`cognee/modules/cognify/routing.py:39-66`。

#### C. graph/vector 检索链

```text
recall(query)
  → normalize_scope()
  → session/trace/context（如请求）
  → graph：get_default_user / resolve authorized datasets
  → query_router（query_type 缺省且 auto_route）
  → authorized_search()
    → get_authorized_existing_datasets(..., "read")
    → 每 dataset：set_database_global_context_variables()
    → get_graph_engine().is_empty()（只告警）
    → get_retriever_output()
      → FEELING_LUCKY 二次 select_search_type()
      → get_search_type_retriever_instance()
      → `SearchType` registry/community retriever
      → run_session_aware_completion()
      → SearchResultPayload(dataset identity + result/context/completion)
  → normalize_search_payload()
  → ResponseGraphEntry(source="graph")
```

access-control 打开时多个 dataset 的 `_search_in_dataset_context()` coroutine 用 `asyncio.gather()` 并发；单个 CODE seed miss 在多 dataset 情形被转成 `seed_not_found` payload，其他 dataset 不被连带失败。普通 retriever 初始化只在 factory 验证 `top_k`；具体 LLM、向量和图访问错误向上冒泡。证据：`cognee/api/v1/recall/recall.py:575-667`、`cognee/modules/search/methods/search.py:155-212,215-409`、`cognee/modules/search/methods/get_retriever_output.py:31-61`、`cognee/modules/search/methods/get_search_type_retriever_instance.py:41-403`。

### 12.3 关键节点的状态、失败和恢复责任

| 节点 | 持有/写入对象 | 成功终态 | 失败分支 | 责任边界 |
|---|---|---|---|---|
| `ingest_data` 预解析 | 原始文件、loader、Data id、关系库 `Data` | 输入落到 Cognee storage，Data 元数据提交 | loader/classify/identify/SQL 异常向 pipeline 传播；同批 hash 共享首次 mint 的 id | 只负责摄取和关系元数据，不生成图 |
| `extract_graph_and_summarize` | chunk、LLM response、summary | 返回 `TextSummary`；graph extraction 的副作用/结果由任务链继续消费 | 任一 `gather` 分支异常会使组合任务失败；没有局部补偿 | graph extraction 与 summary 并行，但不是独立可重试事务 |
| `add_data_points` | graph nodes/edges、vector points、legacy provenance ledger 或 graph source refs | 节点/边和检索索引可读 | graph/vector 任一并行写失败使 task 失败；ledger 可能已先 commit，等待 rollback | 事务边界随 backend/capability 改变，不能概括成全局原子 |
| `run_tasks_data_item` | 每 item pipeline status、`PipelineRunYield` | 写 `DATA_ITEM_PROCESSING_COMPLETED` | incremental 分支先产出 Errored；`RAISE_INCREMENTAL_LOADING_ERRORS=true` 默认再抛给 run 层 | 单 item 错误先被记录，是否终止全 run 受环境变量和 gather 行为影响 |
| `run_tasks` | `PipelineRunStarted/Completed/Errored`、数据库 context、后台 task | flush 后写 Completed | `Exception` 才触发 rollback + Errored；rollback 异常仅日志，仍写 Errored；取消/`BaseException` 无专门终态 | 是 run 状态 owner，但不是取消/崩溃的完整治理器 |
| `cognify_rollback_handler` | graph/vector artifact、legacy node/edge/provenance、Data.pipeline_status | source-ref 或 pipeline-run 归属的产物删除，状态可重跑 | 删除失败时上层记录 rollback error；不能证明所有外部 WAL/临时文件已清理 | 只回滚可定位的图/向量/关系对象 |
| `recover_stale_cognify_runs_on_startup` | 关系库最新 run、dataset pipeline status | 仅足够老的 latest Started run 回滚并 reset | 查询/回滚失败只日志；年轻 run 跳过；无 dataset 跳过 | age heuristic，不是 heartbeat/lease；只在 API lifespan 调用 |
| `SessionManager.add_qa` | cache QA row、session vector、session activity | cache row + vector best effort + activity | cache 不可用直接 `None`；vector indexing fail-open；cache 写异常本身可传播 | session 快速记忆不是永久 graph 事务 |

### 12.4 资源生命周期：四种终态逐项收口

| 资源 | 创建/持有 | 正常完成 | 业务失败 | 主动取消/超时 | 宿主崩溃 |
|---|---|---|---|---|---|
| SQLAlchemy async session/事务 | `async with get_async_session()`；ledger/Data/status 写入 | context 退出，显式 `commit` 的事务完成 | context 回收连接；run rollback 另开事务清 status/删除对象 | 顶层没有统一 cancel handler；不能保证写 Errored 或完成 rollback | 数据库自身恢复 + API 重启 stale recovery；未证明半提交跨库一致 |
| graph/vector adapter | dataset ContextVar 选择；`UnifiedStoreEngine` 持有 adapter | API lifespan 正常 shutdown `cache_clear()`；任务完成前 push | pipeline rollback 尝试 source-ref/pipeline-run 删除；并行写可能部分完成 | 仅局部 provider 可能有 timeout；顶层无 deadline/排空协议 | SIGKILL 不走 lifespan；WAL、锁、embedded engine 残留未做本轮扫描 |
| 原始输入/临时文件 | `save_data_item_to_storage`、loader、`.enola`、stream materialize | 各模块自行关闭 file context；前台 DLT orphan cleanup 在提交后执行，后台在启动前执行 | orphan cleanup 顺序可避免前台中途丢数据；异常临时产物无统一 sweep | enola timeout 会 kill + wait；普通 pipeline 不会递归清理全部临时目录 | 可能留下 storage 文件、`.enola`、WAL/锁；没有仓库级残留审计 |
| background pipeline task | `create_task(handle_rest_of_the_run)` + `_BACKGROUND_PIPELINE_TASKS` 强引用 | 完成回调移除集合；队列收到 run updates | task 内异常若未由 pipeline 转换，后台宿主只保留 task 状态；调用者不自动收到异常 | `RememberResult` 用 `shield` 等待自身 task；无公开 cancel/timeout drain | 进程死后 task 消失，靠下一次 API 启动 age recovery，且仅覆盖 latest Started cognify |
| session QA vector | `SessionQAVector` 以 QA UUID 写入 vector collection | `delete_qa`/`delete_session` 路径清理；检索失败 fail-open | cache row 可存在而 vector 缺失；recall 退回 cache/关键词路径 | 未见 session vector 顶层 cancel 事务 | 无跨库恢复账本；vector orphan 需另行扫描 |
| enola 子进程/pipe | `create_subprocess_exec`，stdout/stderr PIPE | `communicate()` 收完，自然退出 | 非零码或缺 `facts.jsonl` 抛 `EnolaSnapshotError` | `wait_for` 超时后 `kill()` + `wait()`；只覆盖该子流程 | 父进程崩溃时本轮没有证据证明子进程一定被回收 |

### 12.5 失败、超时、取消、崩溃的真实矩阵

| 场景 | 当前源码事实 | 本轮验证等级 | 收口结论 |
|---|---|---:|---|
| 非法组合/非法参数 | `remember` 的 remote/dry-run/session/dataset 组合和 typed entry 前置条件有显式 `ValueError`；retriever `top_k<=0` 有 `QueryValidationError` | L1；定向测试源码 L2 | 错误类型可定位，但未运行并未读回“零写入” |
| 空图/未 cognify | search 检查 `graph_engine.is_empty()` 后 warning；仍继续 retriever，不自动失败/不自动处理 | L1 | 空图不是硬前置错误，调用方必须自行区分“空结果”和“查询失败” |
| provider/optional extra 缺失 | adapter/extra 在导入或运行时决定；backend access control 下图和向量不支持会硬失败而非回退 | L1 | 未安装 extra、未连外部服务；不能称 provider 可用 |
| graph/vector 部分写 | `add_data_points` ledger/graph/vector 边界随 capability 改变；失败进入 run rollback，但 rollback 自身失败只日志 | L1；rollback 测试源码 L2 | `Errored` 只代表运行失败，不代表所有外部 artifact 已删除 |
| LLM/embedding timeout | `infrastructure/llm` 和部分 embedding 使用局部 `wait_for`；pipeline 顶层无 deadline | L1 | 局部 timeout 处理不能外推为全链路超时治理 |
| enola timeout | `communicate()` timeout 后 `kill()`、`wait()` 并抛 `EnolaSnapshotError` | L1；enola 测试源码 L2 | 已有单子进程清理样本；未做进程树/临时目录残留扫描 |
| 主动取消 | pipeline 外层是 `except Exception`；Python `CancelledError` 不会走此分支；`gather` 未 `return_exceptions=True` | L1 | 不能声称取消会写 Errored、rollback 或排空 sibling tasks |
| background task 结果未 await | module set 强引用，done callback 移除；`RememberResult` 自己吞业务异常并写 status/error | L2 测试源码；未运行 | 强引用只防 GC，不是成功证明；后台错误需读 result/DB，而不是看 HTTP 已返回 |
| API/worker SIGKILL | lifespan shutdown 的 cache clear 不执行；重启只找每 dataset 最新且年龄超过阈值的 Started cognify run | L1；recovery 测试源码 L2 | 这是有限恢复，不是跨进程租约/心跳；未达到 L4 |
| 客户端断开/MCP 连接断开 | transport 支持 stdio/SSE/HTTP，但本轮没有断连后 server task/socket/pipe 清理实测 | L0-L1 | 必须独立测试，不能由 transport 枚举推定安全 |

### 12.6 本轮验证等级和禁止误读

| 证据项 | 现场事实 | 等级 |
|---|---|---:|
| 生产源码路径、函数签名、异常/资源分支 | 本轮直接读取入口、pipeline、retriever、session、rollback、recovery、enola 源码 | L1 |
| 定向测试源码存在 | 已定位 cognify routing/estimator、rollback/recovery、remember background anchoring、session/retriever/provenance 等测试 | L2（仅“测试源码存在”） |
| 本轮真实执行 | 未安装依赖，未启动 API/MCP，未连接真实 LLM/graph/vector/cache，未运行 pytest/ruff | 未达 L3 |
| 独立进程故障验证 | 未执行 SIGKILL、Task.cancel、provider timeout、客户端断连、重启后数据库/WAL/锁/临时目录扫描 | 未达 L4 |

因此本轮收口后的最高诚实表述是：**Cognee 的入口契约、标准/DLT/code/temporal 摄取分支、graph/vector 写入边界、scope→授权→retriever→结果链和有限的 rollback/startup recovery 已达到源码级 L1；若对应测试文件的断言确实覆盖该路径，可标“存在 L2 测试源码”，但整个 checkout 仍未获得 L3/L4 运行验证。** 特别不能把 `PipelineRunErrored`、日志中的 rollback、`RememberResult.done` 或 API 已返回 Started 解读为“已清理、已成功或可取消”。

### 12.7 第二轮最终裁决

1. **吸收为研究事实**：`add → cognify` 双阶段写入、单 dataset 单 logical run、每 item route resolver、graph/vector/cache/relational 分层、`SearchType` registry、typed memory entries、provenance source-ref、后台 task 强引用和 age-based startup recovery。
2. **明确为实现缺口**：统一 deadline、主动取消终态、取消传播/子任务排空、幂等键、retry budget、heartbeat/lease、跨 graph/vector/relational 的原子提交、崩溃后全资源扫描、统一错误码和版本迁移契约。
3. **明确不得外推**：enola 的 `wait_for + kill + wait` 不能外推为全 Cognee pipeline 的进程治理；session vector fail-open 不能外推为 cache/vector 一致；rollback 完成日志不能外推为零残留；L2 测试源码不能外推为通过。
4. **文档权威归属**：本节吸收二轮细探事实；`细探-Cognee.md` 保留历史，不再新增平行事实。后续若继续研究，只更新本 `ARCHITECTURE.md`，并为每一项从 L1/L2 推进到 L3/L4 提供真实命令和读回证据。

## 13. 第二轮源码复核增补：入口分支、任务持有和外部进程

本节是对上一节已记录事实的再次逐符号核对，不删除或改写 `细探-Cognee.md`。新增内容仍按“源码事实”和“未运行”分开：本轮只读了本机 checkout，没有安装依赖、启动服务或执行测试。

### 13.1 `remember()` 的实际分流比“原始数据/typed entry”更细

```text
MemorySource
  → import_memory_source()
  → 仅本地、永久图；禁止 dry_run / dataset_id / session_id / remote

MemoryEntry
  → _remember_entry()
  → QA / Trace / Feedback：SessionManager
  → SkillRun：graph-backed skill 记录

content_type="code"
  → resolve_repo_source()
  → 每个仓库 run_custom_pipeline(code_graph_pipeline)
  → enola/code graph；可选 index_vectors

content_type="skills"
  → 稳定的 dataset 临时根物化 SKILL.md
  → add_skills() 的技能图路径

其他普通输入
  → add() → cognify()
  → session_id 存 session；无 session_id 走永久路径
```

源码直接确认的补充约束：`MemorySource` 不能连接 remote 客户端，否则导入会写本地图而非远端；`content_type="code"` 只接受目录/远程 Git URL（或列表），明确拒绝 session；普通 `dry_run` 只支持本地标准 add+cognify，且不调用 LLM、不写图。技能物化根由 dataset UUID 的 SHA-256 前 16 位命名，避免随机临时目录导致同一技能重复生成图节点。证据：`cognee/api/v1/remember/remember.py:744-841,887-1051`、`cognee/memory/entries.py:25-135`。

### 13.2 代码图分支的缓存、网络和残留语义

`resolve_repo_source()` 对本地目录只做存在性校验；远程仓库默认复用 `~/.cognee/repos/<稳定 slug>`，已有 clone 不保证 freshness：`git pull --ff-only` 失败时仍继续使用旧 clone。新 clone 使用 `--depth 1`，Git 子进程通信有 600 秒超时，超时路径是 `kill()` 后 `wait()`；`ALLOW_HTTP_REQUESTS=false` 时远程 clone 在启动子进程前拒绝。该 timeout 只覆盖 Git 子进程，不覆盖后续 enola、图写入或整个 `remember()`。

`run_enola_generate()` 默认 600 秒；它可能自动下载并安装 enola，随后在仓库目录运行 `enola --generate`，要求 `.enola/facts.jsonl` 存在。超时同样 `kill()` + `wait()`；非零返回码、缺少 facts 文件会报 `EnolaSnapshotError`。解析时坏 JSON 行和缺失/损坏 `receipt.json` 是 warning/fail-open，而缺少 `facts.jsonl` 是硬失败；`insights.json` 可选并会被合成为 `kind="insight"` 的事实。源码未在该函数清理 `.enola`，因此成功快照和失败残留均不能假定自动删除。证据：`cognee/tasks/code_graph/resolve_repo.py:55-123`、`cognee/tasks/code_graph/enola.py:77-196`。

### 13.3 后台执行的真实持有关系

- `run_pipeline_as_background_process()` 先为每个 dataset 消费到 `PipelineRunStarted`，再创建**一个** `handle_rest_of_the_run` task；该 task 按 pipeline 列表逐个推进，而不是并发推进多个 dataset，以避免数据库写冲突。
- `_BACKGROUND_PIPELINE_TASKS` 和 `_BACKGROUND_REMEMBER_TASKS` 都是模块级强引用集合，完成回调移除 task；这只防止事件循环弱引用导致任务被 GC，不是 durable queue，也不是崩溃恢复账本。
- `RememberResult.__await__()` 使用 `asyncio.shield(self._task)`，调用者等待超时或被取消时，外层等待被取消，但不会因此自动取消被 shield 的业务 task；该业务 task 仍可能继续写库。调用者不能把“await 被取消”解释为“pipeline 已停止”。
- `RememberResult` 的后台协程自行把业务异常写入 `status="errored"`/`error`；`await result` 返回 result 对象而不是重新抛业务异常。`done` 仅表示 task 结束或非 running 状态，`bool(result)` 仅对 `completed`/`session_stored` 为真。

证据：`cognee/modules/pipelines/layers/pipeline_execution_mode.py:17-127`、`cognee/api/v1/remember/remember.py:410-561,1240-1311`。未发现公开的 task cancel、deadline、drain 或跨进程持久队列契约。

### 13.4 任务级异常传播的精确边界

`run_tasks()` 使用 semaphore 限制同时执行的 item 数量，但先为全部 item 创建 task；`asyncio.gather()` 没有 `return_exceptions=True`。因此后续“遍历 gathered 并收集 `BaseException`”代码不能保证收集所有 sibling 异常：首个传播异常可能使 gather 提前结束，且 `CancelledError` 不进入 `except Exception` 的 rollback 分支。普通 `Exception` 才会调用 rollback handler、写 `DATASET_PROCESSING_ERRORED` 并 yield `PipelineRunErrored`；rollback 自身异常只记录日志。

完成事件前会先尝试 graph/vector 与 relational 的 `push_to_s3()`，push 失败仍归入失败路径；这强化了“Completed 不是在内存 task 完成时写入”的事实，但不改变跨存储非原子性。证据：`cognee/modules/pipelines/operations/run_tasks.py:63-225`。这部分已有测试源码线索，但本轮仍未运行，最高只能记为 L1，或“存在 L2 测试源码”，不能记为 L2 通过。

### 13.5 统一底座映射的再次裁决

| 观察到的 Cognee 事实 | 可借鉴的通用底座语义 | 不应直接复制的部分 |
|---|---|---|
| `MemoryEntry` literal discriminator + Pydantic 校验 | 支持库中的版本化记忆/结果 schema、显式类型路由 | Cognee 的字段名、SessionManager 和 cache 语义不是平台公共契约 |
| 一个 logical run、Started/Completed/Errored、item semaphore | 运行核心的 run 状态、并发预算和终态证据 | Cognee 没有统一 deadline、cancel、lease 或跨库事务，不能当运行核心实现 |
| `source-ref` provenance、checksum、rollback | 支持库的证据完整性原子能力 | Cognee dataset 前缀和 ledger owner 不能直接充当平台租户/权威账本 |
| REST/CLI/MCP direct/API 双模式 | 网关的协议适配、认证和错误映射 | 不能把每个入口的业务分流复制成多套记忆实现 |
| Git/enola `wait_for` 后 kill/wait | 受管 provider 的局部子进程超时样本 | 不能外推为 pipeline 取消、进程组清理或崩溃恢复 |

唯一归属仍为：纯 schema/规范化/完整性/provider 边界进入支持库候选；`remember`/`cognify`/`recall` 领域流程进入模块库候选；run 状态、资源、deadline、取消、崩溃和残留治理进入运行核心候选；REST/MCP/CLI 进入网关候选。以上均是研究映射，不表示 Cognee 已接入任何通用底座。

### 13.6 本轮验证结论

- **L1（源码事实）**：`remember()` 的 MemorySource/typed/code/skills/普通分支，后台 task 强引用与 shield，run_tasks 的 gather/rollback/flush 边界，startup recovery 的 age heuristic，Git/enola 局部 timeout 和快照解析容错。
- **L2（仅测试源码存在）**：后台任务 anchoring、cognify routing、rollback/recovery、session 和 provenance 相关定向测试仍可定位；本轮没有执行，因此不写“通过”。
- **L3 未达成**：没有真实数据库、图/向量、LLM、API、MCP、Git/enola provider 运行与读回。
- **L4 未达成**：没有 `Task.cancel()`、外层 deadline、客户端断连、SIGKILL/重启、进程树、WAL、锁、`.enola` 或临时目录残留验证。

本轮未验证项仍包括：依赖安装与版本解析、真实 provider 可用性、网络/密钥、跨 graph/vector/relational 一致性、取消后的终态和 sibling 排空、跨进程 lease、重复请求幂等、MCP/API 断连清理，以及完整测试套件结果。

## 14. 本轮深度源码研究收口（2026-08-21）

本节是本轮实际读取后的增补。它只修改本文件；`细探-Cognee.md` 保留不动。研究目标是从 `add/remember` 进入，经 `cognify`、pipeline、graph/vector/relational/cache，再到 `recall/authorized_search`，逐节点核对真实参数、返回、状态、并发、取消、超时、异常和资源 owner。所有等级均按 §11.6 定义；本轮未安装依赖、未启动服务、未运行测试，所以没有 L3/L4。

### 14.1 实际读取范围

- 入口与配置：`README.md`（1-483）、`AGENTS.md`、`CLAUDE.md`、`pyproject.toml`、`cognee/__init__.py`、`cognee/base_config.py`、`cognee/context_global_variables.py`、`cognee/infrastructure/databases/cache/config.py`。
- 完整主链实现：`cognee/api/v1/add/add.py`、`cognee/api/v1/remember/remember.py`、`cognee/api/v1/cognify/cognify.py`、`cognee/api/v1/recall/recall.py`、`cognee/api/v1/search/search.py`、`cognee/modules/search/methods/search.py`。
- 编排、状态和资源：`cognee/modules/pipelines/operations/run_tasks.py`、`run_pipeline.py`、`cognee/modules/pipelines/layers/pipeline_execution_mode.py`、`cognee/infrastructure/databases/dataset_queue/queue.py`、`cognee/modules/cognify/rollback.py`、`recovery.py`。
- 存储边界：`cognee/tasks/storage/add_data_points.py`、`cognee/infrastructure/databases/unified/unified_store_engine.py`、`graph/graph_db_interface.py`、`vector/vector_db_interface.py`、`cache/cache_db_interface.py`、`cognee/infrastructure/session/session_manager.py`。
- 代码图与外部资源：`cognee/tasks/code_graph/resolve_repo.py`、`enola.py`、`install_enola.py`、`extract_code_graph.py`，覆盖 Git clone/pull、enola 子进程、快照、自动安装、checksum、`.enola` 产物和增量身份。
- 测试与历史材料：`cognee/tests/unit/modules/cognify/test_cognify_single_logical_run.py`、`test_run_tasks_rollback.py`、`cognee/tests/unit/api/v1/remember/test_remember_background_task_anchoring.py`、`cognee/tests/unit/api/v1/recall/test_recall_api.py`、`cognee/tests/unit/modules/search/test_search.py`、现有 `ARCHITECTURE.md` 全文、旧 `细探-Cognee.md` 全文。测试只读取，未执行。

### 14.2 逐节点事实和纠错项

1. `add()` 的真实入口签名是 `data, dataset_name="main_dataset", user=None, node_set=None, vector_db_config=None, graph_db_config=None, dataset_id=None, preferred_loaders=None, incremental_loading=True, data_per_batch=20, importance_weight=0.5, run_in_background=False, llm_config=None, embedding_config=None, data_cache=True, **kwargs`。它先 `setup()`，解析授权 dataset，展开 DLT；后台模式先执行 orphan cleanup 并物化 stream，随后进入 `add_pipeline`。前台 cleanup 在 pipeline commit 后执行。返回值在单 dataset 时从 executor 的映射中解包为单个 `PipelineRunInfo`。证据：`cognee/api/v1/add/add.py:35-59,251-325`。等级 L1。
2. `remember()` 不是单一 add+cognify 包装器：`MemorySource`、typed `MemoryEntry`、`content_type="code"`、`content_type="skills"` 和普通输入分别走不同分支。普通 `session_id` 输入先写 cache，再以 `asyncio.create_task(improve(...))` 异步桥接；普通永久输入才进入 add→cognify→可选 improve。`RememberResult` 的后台异常被写入 `status="errored"/error`，`await result` 使用 `shield` 等待并不会重新抛出业务异常。证据：`remember.py:744-841,925-1051,1176-1319`。等级 L1；后台强引用有测试源码，等级 L2（未运行）。
3. 纠正 README/AGENTS 的简化表述：`CACHING=false` 时，普通输入的 `_add_to_session()` 看到 `SessionManager.is_available=false` 只记录 warning 并返回，随后 `remember()` 仍构造 `status="session_stored"` 的结果；typed QA/Trace/Feedback 则在 dispatcher 中对 cache 不可用抛 `RuntimeError`。因此不能笼统写成“所有 `remember(session_id=...)` 都抛错”。证据：`remember.py:146-183,301-320,1221-1251`、`session_manager.py:129-156`。等级 L1。
4. `cognify()` 的真实参数包括 dataset 名/UUID、graph model、chunker、chunk size、batch、ontology config、graph/vector config、background、incremental、prompt、temporal、functional relationships、LLM/embedding config、data cache 和 dry-run。标准任务顺序是 classify→chunk→LLM graph/summarize→add_data_points，provenance/contradiction/functional relationship 为配置性追加；DLT、CODE、CODE_REPO 由 `system_metadata` 路由，且所有 route 共用一个 executor 调用和一个 logical run。证据：`cognify.py:54-74,253-336,351-476`；测试源码：`test_cognify_single_logical_run.py`。等级 L1/L2源码存在。
5. `run_tasks()` 先写 Started，再为全部 item 创建 asyncio task，`Semaphore(data_per_batch)` 只限制同时进入 item body 的数量；`asyncio.gather()` 未设置 `return_exceptions=True`。普通 `Exception` 进入 rollback→写 Errored，rollback 异常只日志；`CancelledError`/其他 `BaseException` 不进入这个 `except Exception` 分支。后置的异常汇总循环不能被解释为完整 sibling 收集或取消治理。证据：`run_tasks.py:63-225`。等级 L1。
6. Completed 前会先调用 graph/relational 的 `push_to_s3()`（若 adapter 提供），之后才写 pipeline complete。`add_data_points()` 在非 hybrid 路径可先提交 relational rollback ledger，再并发写 graph/vector；graph provenance 非 hybrid 可折入 graph 写入，hybrid 仍有独立 attach pass。因此“graph/vector/relational 一次原子提交”不成立，Completed 只表示本流程到达完成写入，不是跨存储事务证明。证据：`run_tasks.py:169-190`、`add_data_points.py:116-252`。等级 L1。
7. dataset queue 是进程内 `asyncio.Semaphore`，默认启用；同一 task+dataset 通过 depth 计数重入，不同 task 即使继承 ContextVar 也重新占槽。async-with 退出显式释放，旧 `await context` 依赖 task-end callback 兜底。最后 holder 释放时，subprocess engine 默认按 `SUBPROCESS_IDLE_TTL_SECONDS=600` 保活并由 daemon reaper 清理；TTL=0 才 force-close。禁用 queue 会同时失去并发上限、subprocess teardown 和 active pinning。证据：`dataset_queue/queue.py:1-40,175-239,241-390,392-497`、`context_global_variables.py:277-321`。等级 L1。
8. `recall()` 先 `normalize_scope()`：默认 session-only 命中可短路 graph；显式 scope 按 session/trace/session_context/graph/tools 顺序串行执行。graph 分支解析用户和授权 dataset，`dataset_ids` 优先于 names，随后 `authorized_search()` 为每个 dataset 建 ContextVar scope、检查 graph 空状态、调用 retriever factory，并把 `SearchResultPayload` 归一化为 source-discriminated response。access-control 打开时多个 dataset 的 graph search 用 `asyncio.gather()` 并发；tools 不由 auto/all 隐式启用，禁用时显式请求会硬失败。证据：`recall.py:338-771`、`modules/search/methods/search.py:155-409`；测试源码：`test_recall_api.py`、`test_search.py`。等级 L1/L2源码存在。
9. code graph 的资源 owner 是 Cognee 的 code-graph task：远程 URL 由 `resolve_repo_source()` 复用 `~/.cognee/repos/<slug>`，已有 clone 的 `git pull --ff-only` 失败仍继续使用旧 clone；Git 通信 deadline 为 600 秒，超时 kill+wait。enola 缺失时默认可自动下载固定版本到 `~/.cognee/bin`，下载 120 秒并 SHA-256 校验、临时目录内原子替换；生成阶段默认 600 秒，超时 kill+wait，要求 `.enola/facts.jsonl`。成功或失败均没有由该函数递归删除 `.enola` 快照；父进程崩溃后的子进程/快照残留未验证。证据：`resolve_repo.py:55-124`、`enola.py:77-196`、`install_enola.py:34-189`。等级 L1。
10. graph/vector/cache/relational 的 owner 是各自接口与 adapter，不是 `UnifiedStoreEngine` 统一事务 owner。Unified engine 只按 capability 暴露 graph/vector 并提供 source-ref 删除/rollback；cache interface 的 `close/prune/delete_session` 是 adapter 责任；SessionManager 写 cache 后再写 session vector，vector indexing 失败的 fail-open 语义不能证明 cache/vector 一致。证据：`unified_store_engine.py:14-152`、`graph_db_interface.py:23-109`、`vector_db_interface.py:9-220`、`cache_db_interface.py:51-336`、`session_manager.py:134-198,263-301`。等级 L1。

### 14.3 本轮 L0-L4 证据结论

| 等级 | 本轮结论 |
|---|---|
| L0 | 目录、入口、配置、接口、任务和测试文件存在；optional provider、MCP、前端和部署声明不能据此证明可用。 |
| L1 | `add→remember→cognify→run_tasks→graph/vector/relational/cache→recall→authorized_search` 的参数、返回形状、状态边界、并发、局部 timeout、异常传播和资源 owner 已由源码直接定位。 |
| L2 | cognify 单 logical run、rollback、recall dataset precedence、search 多 dataset、remember 后台 task anchoring 等测试源码存在；本轮未运行，不能写“通过”。 |
| L3 | 未达成：没有安装依赖、真实数据库/图库/向量库/cache/LLM、API/MCP、Git/enola provider 的真实运行和状态读回。 |
| L4 | 未达成：没有 Task.cancel、顶层 deadline、客户端断连、SIGKILL/重启、进程树、WAL、文件锁、`.enola`、临时目录和 sibling task 排空验证。 |

### 14.4 剩余风险

- 无公开的 pipeline 级统一取消、deadline、retry budget、heartbeat/lease 或请求幂等键；`RememberResult` 的 shield 可能使调用者取消等待而业务 task 继续写入。
- `asyncio.gather()` 的默认异常/取消传播与后台 executor 的单 task 持有关系，可能造成未显式终态、未排空 sibling 或只留下 Started 记录；startup recovery 只按 latest run + 年龄阈值处理。
- graph、vector、relational、session cache、session vector 和 S3/文件资源跨 owner 写入，失败后依赖 rollback 或 fail-open，各路径没有统一原子提交和全资源残留扫描。
- Git/enola 自动安装、远程 clone、`.enola` 快照和外部子进程存在网络、版本、进程组、旧 clone freshness、磁盘占用和崩溃残留风险；局部 kill+wait 不能外推为全链路进程治理。
- README、AGENTS 与 `pyproject.toml` 的 Python 上限表述存在漂移：README写 3.10–3.14，AGENTS 写 `<3.14`，而 `pyproject.toml` 和锁文件约束为 `>=3.10,<3.15`。运行环境事实未在本轮安装或解析验证，故以配置文件记录为静态事实，不能宣称支持矩阵已运行确认。

## 15. 本轮深度源码审计补充（2026-08-21）

本节记录本轮在目标仓库本地完成的进一步源码研究。没有调用 MCP/Hermes，没有安装依赖、启动服务、连接外部 provider 或运行测试；因此本节仍然只提供源码级事实和未验证边界，不把测试文件存在写成测试通过。

### 15.1 探索方法、范围和项目地图

- 目标根目录为当前仓库本身；首先检查 `.codegraph`，结果为**不存在**。因此没有 CodeGraph 项目地图、节点或调用链证据，本轮改用本地目录读取、Glob、rg/Grep、分段完整读取和源码行号定位。不能把任何 CodeGraph 等级或缓存索引状态外推到此仓库。
- 根入口：`cognee/__init__.py` 汇聚 V1 API、V2 memory API、pipeline、migration、observability、agent memory、tools 和关系模型注册；`cognee/__main__.py` 转到 CLI；`pyproject.toml` 注册 `cognee-cli`。
- 服务入口：`cognee/api/client.py` 创建 FastAPI app、执行 lifespan 迁移/默认用户/过期 run 恢复、注册 `/api/v1/*` 路由；`cognee-mcp/src/server.py` 建立 FastMCP，支持 stdio、SSE、Streamable HTTP、工具搜索和 direct/API client；`cognee-frontend/` 是独立 Next.js 交付面。
- 领域主链：`api/v1/add` 摄取输入，`api/v1/cognify` 构建按 item 路由的 task resolver，`modules/pipelines/operations/run_tasks.py` 持有一个 logical run，`tasks/storage/add_data_points.py` 跨关系库/图/向量写入，`api/v1/recall/recall.py` 依次合并 session、trace、context、graph、tools。
- 状态/资源边界：`context_global_variables.py` 用 ContextVar 传递 dataset、LLM、embedding 和 file storage 配置；`dataset_queue/queue.py` 用进程内 semaphore、按 task/dataset 深度计数和 task-done callback 管理并发槽位；graph/vector cache、关系库、外部 Git/enola、临时目录由各自 adapter/task 持有，`UnifiedStoreEngine` 不是跨存储事务 owner。
- 研究材料：完整分段读取根 `README.md`、现有根 `ARCHITECTURE.md`、历史 `细探-Cognee.md`、`AGENTS.md`、`CLAUDE.md`、`pyproject.toml`、`.env.example`；主入口、配置、remember/cognify/recall、pipeline、队列、存储、搜索、MCP、代码图外部进程和代表性 recovery/rollback/routing/background 测试按源码段读取。仓库规模静态清点为约 1,989 个 tracked Python 文件，其中 `cognee/tests/` 约 563 个 Python 文件；这不是完整逐文件行为审计的等价证明。

### 15.2 交互面和状态转换审计

```text
Python SDK / CLI / FastAPI / MCP / frontend client
  → 本地 direct、HTTP API 或 CloudClient 选择
  → add / cognify / remember / recall / search / improve / forget
  → user + dataset ACL 解析
  → ContextVar 设置 + dataset queue 槽位
  → task resolver / retriever registry
  → relational metadata + graph/vector/cache provider
  → PipelineRunStarted → item tasks → flush → Completed
                  └→ Exception → rollback best effort → Errored
```

- `import cognee` 不是纯声明式导入：先调用 `dotenv.load_dotenv(override=True)`，再配置 logging，并导入大量 API、模型和关系模型以完成注册。包级导入因此可能受环境文件、第三方依赖和模块注册副作用影响。
- `remember()` 不是一个单一 add+cognify 包装器：`MemorySource` 走迁移；typed `MemoryEntry` 走 SessionManager 或 skill-run；`content_type="code"` 走 Git/enola code graph；`content_type="skills"` 走临时物化和 skill 图；普通永久输入走 add→cognify→可选 improve；普通 `session_id` 输入先写 session cache，再可异步 bridge 到 graph。
- 普通 session 输入在 `CACHING=false` 时 `_add_to_session()` 只记录 warning 并返回，但调用仍构造 `status="session_stored"`；QA/Trace/Feedback typed entry 在 cache 不可用时由 dispatcher 抛 `RuntimeError`。因此“关闭缓存即所有 session remember 失败”是错误的统一描述。
- `RememberResult` 将后台业务异常写到 `status="errored"` 和 `error`，`await result` 使用 `asyncio.shield()` 等待并返回对象，不重新抛出业务异常；外层等待者取消只取消等待，不等于被 shield 的业务 task 被取消。
- `recall()` 的 `auto` 规则会在单独 session 查询时先查 session，命中后短路 graph；带 dataset/query type 时 session 与 graph 都贡献；显式 scope 按 session/trace/session_context/graph/tools 顺序串行。`tools` 不由 `auto` 或 `all` 隐式启用，显式但未打开 `TOOL_CALLS_ENABLED` 时硬失败。
- graph recall 先解析授权 dataset，再进入每 dataset 的 ContextVar/队列上下文；access-control 开启时多 dataset search 使用 `asyncio.gather()` 并发，CODE seed miss 在多 dataset 情况被包装成该 dataset 的结果。不同 source 的 recall 合并不是事务，也没有跨 source deadline。
- FastAPI lifespan 启动迁移失败时先 `create_database()` 再重试迁移，然后创建默认用户和恢复过期 cognify；退出时仅清 graph/vector engine cache。正常 lifespan 之外的 SIGKILL、进程崩溃、客户端断开不经过该关闭路径。

### 15.3 文档遗漏、冲突、重复和可读性

| 位置 | 发现 | 影响 | 本文裁决 |
|---|---|---|---|
| `README.md` 性能说明 | 把 `CACHING=false` 概括为 session memory 完全停止，但普通 session remember 会返回 `session_stored`，typed entry 才硬失败 | 使用者无法区分“未写入 cache”“结果状态仍成功样式”和 typed entry 硬失败 | 以源码分支为准，README 该表述属于待修正文档漂移；本轮不改 README |
| `AGENTS.md` / `README.md` / `pyproject.toml` | Python 支持上限分别出现 `<3.14`、3.10–3.14、`>=3.10,<3.15` | 安装与 CI 支持矩阵可能被错误理解 | `pyproject.toml`/锁文件是静态配置事实；运行兼容性仍未验证；本轮不改 AGENTS/README |
| 根 `ARCHITECTURE.md` 与 `细探-Cognee.md` | 历史细探使用过时类名和较窄的分层；根文档已多轮吸收并校正 | 两个文件并存时可能形成第二个权威事实源 | `细探-Cognee.md` 明确保留为历史，不删除、不再追加；根文档作为当前审计收口 |
| `cognify.py` docstring 与实现 | docstring 给出较线性的标准处理描述，实际还有 DLT、CODE、CODE_REPO、temporal、配置性 provenance/contradiction 分支 | 读者可能把示例流程当作所有输入的真实 task 链 | 本文按 route resolver 和 task factory 分支描述，docstring 只作入口说明 |
| MCP README / `server.py` / hardening tests | README 侧重 memory API；server 仍保留大量 V1、workspace、legacy 工具，tools/list 又受 `COGNEE_MCP_TOOL_MODE` 和 BM25 transform 影响 | “只有三个工具”与真实可调用/可发现面不等价 | 本文区分注册、advertised、searchable、direct-call 四个面；本轮不改 MCP 文档 |
| 根 ARCHITECTURE.md | 历史章节、第二/第三轮收口和本轮补充均保留，内容详尽但重复较多 | 便于追踪证据演进，但降低快速阅读和视觉扫描效率 | 不删除旧章节；本节用证据等级和事实/建议边界避免再次复制完整主链 |

**交互面结论：** Cognee 的外部表面不是一个统一同步 API，而是多个协议入口共享部分领域编排、状态记录和 provider 上下文。不同入口对异常、后台结果、远端能力和工具可见性的表达不同；不能从某一入口的 README 示例推断所有入口具有相同的取消、错误码、幂等和资源释放语义。

### 15.4 数据、状态和资源流

#### A. 标准永久写入

```text
remember(raw)
  → setup / resolve user + dataset
  → add(): resolve_data_directories → ingest_data → Data/文件落盘
  → cognify(): route(system_metadata)
  → classify → chunk → graph extraction + summary
  → add_data_points()
       ├─ relational rollback ledger（非 graph-provenance）
       ├─ graph nodes/edges
       └─ vector points/edge vectors
  → optional provenance / contradiction / functional relationships
  → push_to_s3 if adapter exposes it
  → PipelineRunCompleted
  → optional improve/session bridge
```

- `cognify()` 通过一个 executor 调用和一个 `cognify_pipeline` logical run 承载混合 item；resolver 依据受保护的 `system_metadata` 选择 STANDARD、DLT_SOURCE、CODE、CODE_REPO，不能由用户的 `external_metadata` 直接改变 route。
- 标准 task 顺序为 classify、chunk、`extract_graph_and_summarize`、`add_data_points`，之后按配置追加 provenance、contradiction 和 functional relationship；DLT 分支先清理旧派生物，再按 manifest/row 确定性构建，CODE 分支使用 enola，不走标准 LLM graph extraction。
- `add_data_points()` 会先把非 graph-provenance 路径的 relational node/edge rollback ledger 提交，再并行写 graph 和 vector；普通 graph/vector/relational 写入不是一个跨 provider 事务。hybrid graph 还存在写入后第二次 attach source refs 的窗口。
- 完成事件之前会尝试 `push_to_s3()`；只有 flush 后才写 Completed。因而 Completed 表示流程已到达终态记录，不表示所有 provider、WAL、临时文件和后台子任务都已完成全局一致提交。

#### B. Session 与 recall

```text
remember(session_id)
  → CacheDB QA/trace/context
  → session vector（best effort）
  → optional improve() background bridge

recall(query)
  → normalize_scope / auto route
  → session keyword + trace/context
  → authorized graph search per dataset
  → optional external SQL tools
  → source-discriminated response list
```

- `SessionManager.add_qa()` 的 cache 写入和 session vector indexing 是先后两个 owner；vector indexing 失败可以 fail-open，cache row 仍可能存在，不能把 session cache 读到当作 vector 一致性证明。
- recall 的 session/trace/context 路径在 cache 不可用时返回空集合；graph 路径可能继续执行，tools 路径在显式启用但配置关闭时抛硬错误。多源结果是顺序合并，不是同一事务或快照。
- `dataset_ids` 优先于 dataset names；graph 每 dataset 先做 read ACL，再设置 ContextVar 和 queue slot。关闭 backend access control 时 search 仍会设置 LLM/embedding override，但不建立 dataset-specific isolation。

#### C. 资源 owner 和释放

| 资源 | 创建/持有者 | 正常释放 | 业务失败 | 取消/超时/崩溃边界 |
|---|---|---|---|---|
| 关系库 session/事务 | SQLAlchemy adapter、pipeline/status/provenance task | `async with` 退出，显式 commit | rollback 另行读取和删除；跨库仍非原子 | `CancelledError` 不进入 `run_tasks` 的 `except Exception`；崩溃依赖数据库恢复和 startup recovery |
| dataset queue slot | `DatasetQueue`，按 `(task,dataset)` 深度计数 | scoped `async with` 退出；legacy await 依赖 task-done callback | release 使用 `finally`；reaper/evict 失败记录日志 | 进程崩溃不执行 Python callback；禁用 queue 同时失去并发上限、active pinning 和 subprocess teardown |
| graph/vector adapter | engine cache / provider | API lifespan `cache_clear()`；queue 释放时 TTL touch 或 force close | rollback 尝试 source-ref 或 pipeline-run 删除 | SIGKILL 不经 lifespan；WAL、文件锁、跨进程 worker 未在本轮实测 |
| session QA vector | SessionManager + vector adapter | delete QA/session 路径 | indexing 可 fail-open | 无统一取消事务或跨库恢复账本 |
| background task | `create_task()` + 模块级 strong-ref set | done callback 移除引用 | remember 自己写 `RememberResult.error`；session improve 非致命 | `shield` 不取消业务 task；进程死后 task 消失，仅可能由下一次启动 age recovery 处理 cognify |
| Git clone | `resolve_repo_source()` + `~/.cognee/repos/<slug>` | 无自动删除，重复调用复用 | pull 失败仍使用旧 clone；新 clone 失败抛错 | 600 秒只覆盖 Git communicate；父进程崩溃后的子进程/半成品目录未验证 |
| enola binary/install | `install_enola()` + `~/.cognee/bin` | 临时 archive 目录退出；目标用同目录 `os.replace` | checksum/layout/下载失败不安装目标 | 120 秒下载、600 秒 generate 是局部 deadline；生成 `.enola` snapshot 不由该函数递归清理 |
| skill materialization | `remember(content_type="skills")` | `finally` 中 `shutil.rmtree(materialize_root)` | add_skills 失败仍进入清理 | 进程崩溃可能留下稳定 temp root；本轮未做残留扫描 |

### 15.5 并发、失败、取消、超时和崩溃审计

- `run_tasks()` 先为全部 data item 创建 asyncio task，再由 `Semaphore(data_per_batch)` 限制进入 item body 的并发量；这不是有界 task 创建，也不是全局资源预算。`asyncio.gather()` 未设置 `return_exceptions=True`，所以首个传播异常可能使 sibling 的完整异常汇总逻辑失去意义。
- 普通 `Exception` 会尝试 rollback、写 `PipelineRunErrored` 并按 incremental 规则决定是否重新抛出；rollback 失败只记录日志，随后仍可写 Errored。`CancelledError` 属于 `BaseException`，不会进入该回滚分支，因此不能声称主动取消会写 Errored、删 artifact 或排空 sibling。
- `DatasetQueue` 的 task-done callback 是 legacy slot 的安全网；scoped context 会显式释放。其独立 daemon reaper 每 5 至 60 秒扫描 idle subprocess engines；reaper 异常被记录后继续循环，但本轮没有验证 event-loop 关闭、线程退出或进程崩溃下的行为。
- startup recovery 只选择每个 dataset 最新的 `cognify_pipeline` run，且只处理 `DATASET_PROCESSING_STARTED`；年龄小于 `COGNEE_STALE_RUN_RECOVERY_MIN_AGE_SECONDS`（默认 3600 秒）跳过，年龄足够大才 rollback/reset。它没有 heartbeat、lease、owner fencing，长任务可能被误判，早期崩溃也可能在阈值前保持 Started。
- graph-provenance rollback 必须在删除 source refs 前从 graph 读取受影响 data ids；非 graph-provenance rollback 先删 graph/vector，再删 relational rows/status，故删除失败时保留关系元数据便于重试。但 rollback 成功日志不证明 provider 外部 WAL、临时目录和进程已清理。
- Git/enola 只对各自子进程 `communicate()` 设置局部 timeout，并在超时后 `kill()` + `wait()`；没有统一父子进程组、pipeline deadline 或请求级取消传播。远程 clone 的 `git pull --ff-only` 失败仍可继续索引旧内容，形成 freshness 语义而非强一致。
- FastAPI 正常退出只清 graph/vector cache；MCP 强引用后台 task 只防垃圾回收，不提供 durable queue、cancel endpoint 或 crash-safe result journal。客户端断开、worker SIGKILL、半写 WAL、锁、`.enola` 和 temp 目录均需要独立故障测试。

### 15.6 测试证据和“防假绿”边界

- 已读测试源码能证明设计意图：`test_cognify_single_logical_run.py` 覆盖 route resolver、一个 executor call 和一个 logical run；background anchoring 测试覆盖 strong-ref 在 GC 后仍存活并在完成后移除；recovery/rollback 测试覆盖 stale candidate、graph-before-relational 顺序和 graph delete failure 保留关系路径。
- MCP hardening 测试覆盖输入解析、文件名/目录穿越、multipart 字节、direct/API 临时上传清理、工具可见集合和 top-k/delete 参数；它们验证的是 MCP 适配层局部行为，不是主 pipeline 的真实 provider 运行。
- 代表性测试使用 pytest/pytest-asyncio 和大量 mock/fixture；源码读取能确认断言与生产符号对应，但本轮没有安装依赖或执行 pytest。因此证据等级为“测试源码存在”，不是 L2 通过，更不是 L3/L4。
- 本轮没有验证：真实 LLM key/provider、数据库迁移、Ladybug/Kuzu/LanceDB/PGVector/Neo4j/Redis、API/MCP handshake、远端 CloudClient、Git/enola、客户端断连、Task.cancel、顶层 deadline、SIGKILL 重启、进程组、WAL/锁/temp/.enola 残留、跨 graph/vector/relational 一致性、重复请求幂等。

### 15.7 外部依赖、配置和安全边界

- `pyproject.toml` 将 FastAPI、SQLAlchemy/Alembic、LanceDB、Ladybug、LLM SDK、embedding、Redis/文件 cache 和大量 optional extras 放在同一发行项目中；`uv.lock` 与 `poetry.lock` 同时存在，解析结果可能因 Python/platform/选择的锁文件不同。optional extra 存在不等于当前环境安装或 provider 可用。
- 默认 `BaseConfig` 将数据、系统、cache、日志路径映射到本地目录或用户 home；`STORAGE_BACKEND=s3` 时可自动把 cache root 设为 `s3://...`，但本轮未验证对应文件 API 和权限行为。
- 多租户隔离要求 graph/vector handler 都支持 dataset isolation；关系库仍共享保存用户、ACL、registry 等元数据。任何一侧不支持时应硬失败，而不是静默回退 shared backend；本轮未真实探测各 provider。
- enola 自动安装默认开启，下载地址固定到 pinned release 并做 SHA-256、archive layout 和 atomic replace 校验；`ALLOW_HTTP_REQUESTS=false` 可阻止 Git clone 和安装下载。该安全边界只覆盖两个网络/安装动作，不覆盖所有 optional loader、LLM、外部 SQL tool 或集成模块。
- FastAPI CORS 由 `CORS_ALLOWED_ORIGINS`/`UI_APP_URL` 控制；MCP 另有 Host/Origin DNS rebinding protection 和 `MCP_ALLOWED_HOSTS`/`MCP_DISABLE_DNS_REBINDING_PROTECTION`。两个入口配置分离，不能以一个入口的 CORS/Host 结论覆盖另一个。
- 配置和包级导入有运行时副作用：`.env` 使用 `override=True`，Langfuse key 可派生 OTLP endpoint/header 并自动开启 tracing；`get_base_config()` 有 LRU cache，测试或运行时修改环境变量后必须显式清 cache 才能得到新配置。

### 15.8 本轮收口结论

1. **已确认的源码级事实**：入口和协议分层、remember 多分支、cognify route resolver、单 logical run、dataset queue、跨存储写入、recall 多源合并、rollback/recovery、Git/enola 局部 timeout、MCP 工具搜索和配置边界。
2. **已确认的实现缺口**：pipeline 级 deadline、主动取消终态、sibling 排空、heartbeat/lease、请求幂等、统一 retry budget、跨 graph/vector/relational 原子事务、全资源残留扫描、统一错误码和跨入口版本契约。
3. **必须禁止的外推**：strong-ref 不等于 durable queue；`session_stored` 不等于 cache 实际写入；`PipelineRunErrored` 不等于 rollback/清理完成；局部 `kill()+wait()` 不等于全链路进程组治理；测试源码存在不等于测试通过；optional extra 和 README 宣称不等于 provider 可用。
4. **文件边界**：本轮只更新根 `ARCHITECTURE.md`；`细探-Cognee.md`、README、源码、测试、配置均未修改。`.codegraph` 缺失已明确记录；异常、取消、provider 和残留项均以“未运行/待核”保守表达。
