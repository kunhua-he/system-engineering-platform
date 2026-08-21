```text
外部客户端 / 浏览器 / QQ Bot / OpenAI-compatible SDK
                 │
                 ├── HTTP: /v1/chat/completions, /api/chat/completions
                 ├── WebSocket: /ws
                 └── Web UI: /, /monitor
                 │
                 ▼
        api/server.py : FastAPI app + lifespan
        ├── 用户/令牌解析、会话路由、运行状态
        ├── SQL/Neo4j/Chroma 启动自检
        └── OpenAI 请求适配与 SSE 流式响应
                 │
                 ▼
        core/chat_engine.py : ChatEngine.chat_stream
        ├── ChatSession 写入当前 user 消息
        ├── 请求中间件（正向）
        │   ├── IdentityResolverMiddleware
        │   └── MemoryRetrieverMiddleware
        ├── KnowledgeBaseEngine.query
        │   ├── VectorStorer → Chroma chat_memory / knowledge_base
        │   ├── Neo4j Event / Relation / Episode / Saga
        │   ├── SQL 原始消息 / Structured Events / Plan
        │   └── BM25（可开关，缺库时降级）
        ├── HybridScorer：四维评分 + RRF + 意图配额 + MMR 去重
        ├── PersonaManager：用户/助手身份与画像
        └── LLMBridge：OpenAI-compatible LLM，流式生成
                 │
                 ▼
        prompt 组装与 LLM 输出
        [GRAPH_CORE] [SQL_EVIDENCE] [STRUCTURED]
        [PLAN] [VECTOR] [EPISODE] [SAGA] + 双层画像
                 │
                 ▼
        响应中间件（逆序；实际持久化由 GraphWriterMiddleware 完成）
        └── GraphWriterMiddleware.process_response
            ├── EventExtractor（LLM）+ RuleBasedStructuredExtractor
            ├── temporal.resolve + ContentNormalizerAgent
            ├── PersonaManager：观察、Big Five / EFSTB 更新
            ├── AsyncGraphWriter → Neo4j Event/Entity/Relation
            │   ├── 同槽位失效、语义幂等、关系推理
            │   ├── Episode（累计 5 个未归档轮次）
            │   └── Saga（Episode 聚类）
            ├── EventRepository → SQL Structured Events
            ├── ef_event_evidence_links → 原始消息证据链
            └── CDCOutbox → .data/cdc_outbox.db 增量变更

权威持久化边界：
SQL（ef_chat_messages）= 原始对话与审计终点
Neo4j                 = 实体、事件、关系、身份、Episode、Saga 图谱
ChromaDB              = 语义向量索引（辅助检索，不替代 SQL 原件）
SQLite CDC             = outbox / consumer checkpoint / replay 去重
```

# EbbingFlow 架构文档

## 项目定位

EbbingFlow 是一个 Python 长效认知记忆引擎，为 LLM Agent 提供跨会话的事件记忆、知识图谱、向量检索、结构化事件、身份/人格演化和可追溯证据链。项目 README 将其定位为“长效认知记忆引擎”，而源码实现的中心入口是 `api/server.py` 的 FastAPI 应用与 `core/chat_engine.py` 的 `ChatEngine`。

它不是仅保存向量的 RAG 服务：

- `ef_chat_messages` 保存原始对话，是 SQL 证据链的终点；
- Neo4j 保存 `Entity`、`Event`、`Relation`、`Episode`、`Saga` 及身份事实；
- ChromaDB 保存聊天和文档向量，承担模糊语义召回；
- `HybridScorer` 将多种召回源按查询意图统一排序；
- 响应完成后，事件抽取、人格观察、图谱/结构化写入和 Episode/Saga 沉淀在响应阶段执行。

项目声明 Python 3.10+、Apache-2.0、v1.0 Stable；`pyproject.toml` 的包版本为 `1.0.0`。

## 真实目录/分层与职责

以下目录来自当前项目实际目录；职责来自对应源码和配置，而不是只依据 README 的目录示意。

```text
api/                  FastAPI HTTP/WebSocket 接入、启动生命周期、鉴权、监控和维护接口
bridge/               LLMBridge；访问 OpenAI-compatible 异步聊天接口
core/                 ChatEngine、ChatSession、消息历史、中间件链、token 监控
memory/
  event/              事件/关系/人格观察模型、LLM 与规则抽取、时间解析、归一化
  graph/              Neo4j 图谱写入、检索中间件、关系推理
  history/            ChatHistoryRepository、SQL/Chroma 历史仓储适配器
  identity/           Actor、实体消解、身份字段契约、冲突仲裁、画像和人格推理/演化
  integration/        Episode、Saga、CDC outbox、CDC checkpoint
  scoring/            HybridScorer、时间衰减、RRF、来源配额、统一结果模型
  sql/                PostgreSQL/SQLite 访问、聊天/证据/结构化事件仓储及 SQL schema
  vector/             Chroma 持久化、聊天/文档写入、向量查询、长文档摄入
frontend/             `chat_interaction.html` 与 `data_monitor.html` 两个前端页面
integrations/         `qq_bot.py` 等外部平台集成
scripts/              数据库初始化、Neo4j 初始化、验证、备份/恢复、压缩和回填入口
docs/                 OpenAI-compatible API、Docker 部署及开发计划文档
reports/              release closure、质量指标和 benchmark 报告
static/               Logo、聊天页和监控页截图等静态资源
tests/                pytest 风格回归测试、夹具和 M2 数据集
backups/              演示/恢复所需的备份压缩包
demo_data/            演示 JSONL 与回放脚本
.github/              CI、Issue 模板、PR 模板
```

实际顶层目录包括 `.github/`、`api/`、`backups/`、`bridge/`、`core/`、`demo_data/`、`docs/`、`frontend/`、`integrations/`、`memory/`、`reports/`、`scripts/`、`static/`、`tests/`。运行时 `.data/` 由 `memory/vector/storer.py`、`memory/sql/pool.py`、`memory/integration/cdc_outbox.py` 等模块按需创建，当前代码库清单中不作为源码目录出现。

### 接入与会话层

- `api/server.py` 创建 `FastAPI(lifespan=lifespan)`，在 lifespan 中初始化 `ChatEngine`、SQL 历史仓储、Neo4j driver、CDC checkpoint 和 Chroma 向量引擎；SQL、Neo4j 或 Chroma 核心初始化失败时会阻止服务进入正常状态。
- `core/session.py` 的 `ChatSession` 持有 `session_id`、`user_id`、短期消息窗口、`context_canvas` 和身份状态；`ChatMessage` 保存 role、content、timestamp 和可回溯的 SQL `msg_id`。
- `core/middleware.py` 提供请求正向、响应逆向的中间件链。`core/chat_engine.py` 的 `get_standard_engine()` 注册顺序为 `IdentityResolverMiddleware`、`MemoryRetrieverMiddleware`、`GraphWriterMiddleware`。

### 记忆检索层

- `memory/knowledge_engine.py` 的 `KnowledgeBaseEngine.query()` 并行组织 vector、graph、BM25、SQL 原始消息、Episode、Saga、structured events 和 plan 等候选，按内容规范化键全局去重，写入图谱交叉验证分数，再交给 `HybridScorer`。
- `infer_query_intent()` 将问题分为 `fact`、`summary`、`long_term`、`semantic`。事实问题保留 SQL/structured 证据预算；summary/long_term 才提高 Episode/Saga 的权重。
- `memory/scoring/hybrid_scorer.py` 对候选计算语义、图跳数、时间衰减和影响力四维分数，随后用 RRF 融合、按来源配额筛选并做 MMR 风格去重，返回 `UnifiedMemoryResult`。
- `memory/vector/storer.py` 使用 Chroma PersistentClient，建立 `chat_memory` 和 `knowledge_base` 两个 collection；嵌入可选本地 SentenceTransformers 或 OpenAI-compatible/Ollama 接口。
- `memory/graph/retriever.py` 的 `MemoryRetrieverMiddleware` 在请求阶段预取身份、最近事件、关键词相关事件和计划事件；更完整的多轨检索由 `KnowledgeBaseEngine` 承担。

### 事件、结构化记忆与图谱写入层

- `memory/event/extractor.py` 的 `EventExtractor` 使用 `memory_llm_config` 请求严格 JSON，输出事件、关系、`PersonaObservation` 和 `EventEnvelope`；置信度低于 `MemoryConfig.event_confidence_threshold` 的 legacy `MemoryEvent` 进入候选列表而不直接作为有效事件。
- `memory/event/rule_extractor.py` 提供确定性结构化抽取；`memory/event/normalizer.py` 负责数量、货币等 envelope 归一化；`memory/event/temporal.py` 将相对日期、星期、时段和精确时间解析为带时区的事件锚点。
- `memory/graph/writer.py` 的 `GraphWriterMiddleware.process_response()` 在一轮回复后执行抽取、人格观察、身份演化、归一化、Neo4j 写入和 SQL 结构化事件写入，并记录 extraction audit。
- `AsyncGraphWriter.write_events()` 通过 `(owner_id, entity_id)` 策略约束 Entity，使用 semantic key 做幂等；同一 temporal slot 的旧 active Event 会被标记 `invalidated`，新事件保留 `event_time`、`record_time`、`source_msg_id` 等审计属性。
- `AsyncGraphWriter.write_relations()` 写入 `RELATION`，对高风险关系在未确认时加 `POSSIBLY_` 前缀并降低置信度；`RelationReasoner` 可对非推理关系执行二次关系推断。
- `write_episode()` 持久化 Episode 并以 `CONTAINS_EVENT` 连接事件；`write_saga()` 持久化 Saga 并以 `CONTAINS_EPISODE` 连接 Episode。

### 身份与人格层

- `memory/identity/resolver.py` 的 `Actor` 固定当前说话人和倾听者的 ID/name；`IdentityResolverMiddleware` 将其放入 `ChatSession`，为下游抽取消除“我/你”等代词歧义。
- `memory/identity/manager.py` 的 `PersonaManager` 负责用户/助手根 Entity、画像读取和写回、PersonaObservation 应用、人格证据生成、Big Five 动量更新以及画像重新推理的支撑操作。
- `memory/identity/schema.py` 定义 `UserProfile`、`BigFiveVector`、`LongTermPersona`、`EfstbBehavioralTags` 和 `DualLayerProfile`；双层画像由慢变量 Big Five/MBTI/核心价值与短变量 EFSTB 组成。
- `memory/identity/conflict_resolver.py` 依据来源权重、置信度、记录时间和字典序稳定排序候选；`state_reducer.py` 将身份状态优先级约束为 explicit/fast_track > history > default，并保留 conflict trace。
- `memory/identity/evolution.py` 对改名/身份状态变更提供正则极速路径、直接路径和 LLM 深路径，写入别名关系、`IDENTITY_EVOLVED` Event，并追加 CDC outbox。
- `memory/identity/field_contract.py` 将部分画像字段白名单化；实际 `ALLOWED_PROFILE_FIELDS` 只列出 `name`、`age`、`gender`，其他字段进入 dropped/fact 路径。源码顶部注释所说的 MBTI/Big Five 五类字段与该白名单并不完全一致，见“架构判断与未确认项”。

### SQL、证据链和变更同步层

- `memory/sql/schema/ef_history.sql` 定义 `ef_chat_sessions`、`ef_chat_messages`、`ef_event_evidence_links`、`ef_memory_events` 和 `ef_structured_extraction_audit`。
- `memory/sql/pool.py` 优先使用已配置的 PostgreSQL asyncpg pool；未配置或 pool 不可用时走 SQLite（优先 aiosqlite，缺失时使用 sqlite3 兼容包装）。
- `memory/history/repository.py` 提供 `ChatHistoryRepository` 抽象；正常 SQL 后端由 `SqlHistoryRepository` 返回自增消息 ID，Chroma 后端 `ChromaHistoryRepository` 是兼容/legacy 适配器，不能按物理消息 ID 查询。
- `memory/sql/event_repository.py` 的 `EventRepository` 写入结构化 envelope，使用 owner、source message、类型、主客体和谓词等字段做幂等检查，并提供列表、财务汇总、数量汇总、证据链接和抽取审计。
- `memory/graph/writer.py` 将 Neo4j Event UUID 映射到 SQL message ID；`KnowledgeBaseEngine` 再依据该映射构造 SQL evidence window，把 `[SQL_EVIDENCE]` 注入 prompt。
- `memory/integration/cdc_outbox.py` 以 `.data/cdc_outbox.db` 保存 owner 隔离的单调版本变更；`cdc_checkpoint.py` 以 `.data/cdc_checkpoint.db` 保存消费者位点和 replay 去重键。

## 核心数据流

### 1. 对话请求到回答

1. 客户端通过 `/ws` 或 OpenAI-compatible POST 发送请求。
2. `api/server.py` 解析 user ID/token；OpenAI 请求取最后一个非空 `user` message 作为本轮输入，把 system/developer message 合并到外部提示区，不把外部 assistant/历史 user 消息直接当作内部会话历史。
3. `_get_user_session()` 返回对应用户的 `ChatSession`；本轮 user 消息先经 `ChatSession.async_add_user_message()` 写入 SQL，并取得 `msg_id`。
4. `ChatEngine.chat_stream()` 清理本轮临时 canvas，处理显式用户/助手画像重写，执行请求中间件，刷新图谱身份上下文。
5. `KnowledgeBaseEngine.query()` 从 Chroma、Neo4j、BM25、SQL、Episode、Saga、结构化事件和计划轨召回候选，统一去重并评分；事实问题会尝试提升带 `source_msg_id` 的 SQL 证据。
6. `ChatEngine` 将候选拆为 graph/vector/structured/plan/narrative 区域，连同用户/助手身份与双层画像拼入 `SYSTEM_PROMPT_TEMPLATE`。
7. `LLMBridge.chat_stream()` 通过 `openai.AsyncOpenAI` 使用配置的 OpenAI-compatible endpoint 流式生成，`ChatEngine` 将 chunk 原样向上游 yield。

### 2. 回答到记忆沉淀

1. 完成流式生成后，assistant 消息写入 `ChatSession` 和 SQL 主存。
2. 响应中间件逆序执行；`GraphWriterMiddleware` 从本轮 user 消息和 `source_msg_id` 开始。
3. LLM `EventExtractor` 与规则抽取器分别产生事件 envelope；时间解析器补齐事件锚点，normalizer 归一化金额、数量和单位，规则结果优先去重。
4. PersonaObservation 写入人格证据并更新用户/助手画像；IdentityEvolutionManager 处理改名或身份演化。
5. legacy Event/Relation 写入 Neo4j；结构化 `EventEnvelope` 写入 SQL `ef_memory_events`，再写 `ef_event_evidence_links` 与抽取审计。
6. 连续累计 5 个未 Episode 化的轮次后，`EpisodeManager` 用 LLM 生成片段摘要、证据消息 ID、EFSTB 和人格提示；Episode 写入 Neo4j 并连接相关 Event。
7. `SagaManager` 决定 Episode 归入已有 Saga 或新建 Saga；最新 EFSTB/Big Five/核心价值同步回 session canvas 和 PersonaManager。
8. 图谱事件、关系和身份变更向 `CDCOutbox` 追加 owner-scoped change，供 `/cdc/changes` 增量读取。

### 3. 文档/知识库摄入

`/kb/upload` 在 `api/server.py` 中读取 UTF-8/GBK 文本，构造 `DocumentDevourer`，按滑动窗口切块后写入 Chroma `knowledge_base`；该 API 当前以 `extract_graph=False` 调用，因此上传接口默认只做向量知识库写入。若直接调用 `DocumentDevourer.devour(..., extract_graph=True)`，则会逐块调用 `EventExtractor`，并将事件/关系双写到向量与 Neo4j。

## 关键类/函数/数据模型及相对路径

### 入口和编排

- `api/server.py`：`app`、`lifespan()`、`health()`、`openai_chat_completions()`、`api_chat_completions()`、`websocket_endpoint()`、`_chat_completion_chunks()`。
- `core/chat_engine.py`：`ChatEngine.chat_stream()`、`_get_kb_engine()`、`get_standard_engine()`、`reset_standard_engine()`。
- `core/session.py`：`ChatMessage`、`ChatSession.async_add_user_message()`、`async_add_assistant_message()`、`get_recent_history()`。
- `core/middleware.py`：`BaseMiddleware`、`MiddlewareChain.execute_request_phase()`、`execute_response_phase()`。
- `bridge/llm.py`：`LLMBridge.chat_completion()`、`LLMBridge.chat_stream()`。

### 检索与评分

- `memory/knowledge_engine.py`：`KnowledgeBaseEngine.query()`、`infer_query_intent()`、`_retrieve_graph_events()`、`_retrieve_vector_context()`、`_retrieve_bm25_context()`、`_retrieve_sql_keyword_context()`、`_retrieve_structured_events()`、`_retrieve_plan_items()`、`format_for_prompt()`。
- `memory/scoring/hybrid_scorer.py`：`ScoredCandidate`、`UnifiedMemoryResult`、`TimeDecayCalculator.calculate()`、`HybridScorer.score()`、`_rrf_fusion()`、`_mmr_deduplicate()`。
- `memory/vector/storer.py`：`VectorStorer.store_chat_turn()`、`store_document_chunks()`、`query()`。
- `memory/vector/devourer.py`：`DocumentDevourer._sliding_chunk()`、`devour()`。
- `memory/graph/retriever.py`：`MemoryRetrieverMiddleware.process_request()`、`_query_root_identities()`、`_query_recent_events()`、`_query_related_events()`、`_query_plan_events()`。

### 事件、图谱和身份

- `memory/event/slots.py`：`ActionType`、`MainEventType`、`TypedPayload`、`NormalizationMeta`、`EventEnvelope`、`MemoryEvent`、`EntityRelation`、`MemoryEpisode`、`MemorySaga`、`PersonaObservation`、`FullExtractionResult`。
- `memory/event/extractor.py`：`EventExtractor.extract_events_from_text()`。
- `memory/event/temporal.py`：`resolve()`。
- `memory/graph/writer.py`：`AsyncGraphWriter.write_events()`、`write_relations()`、`write_episode()`、`write_saga()`；`GraphWriterMiddleware.process_response()`。
- `memory/integration/episode_manager.py`：`EpisodeManager.extract_episode()`。
- `memory/integration/saga_manager.py`：`SagaManager.cluster_episodes_into_saga()`。
- `memory/identity/resolver.py`：`Actor`、`IdentityResolverMiddleware.process_request()`。
- `memory/identity/schema.py`：`UserProfile`、`DualLayerProfile.generate_prompt_injection()` 及双层画像模型。
- `memory/identity/manager.py`：`PersonaManager.apply_observations()`、`get_user_profile()`、`apply_user_profile_rewrite()`、`apply_assistant_role_rewrite()`。
- `memory/identity/conflict_resolver.py`：`ConflictCandidate`、`ConflictResolver.resolve_conflict()`。
- `memory/identity/state_reducer.py`：`reduce_identity_state()`。
- `memory/identity/evolution.py`：`IdentityEvolutionManager.detect_and_evolve()`。

### SQL、证据和 CDC

- `memory/sql/pool.py`：`get_pool()`、`get_db()`、`close_pool()`。
- `memory/sql/event_repository.py`：`EventRepository.insert_event()`、`list_events()`、`aggregate_events()`、`aggregate_quantities()`、`link_evidence()`、`record_extraction_audit()`。
- `memory/history/repository.py`：`ChatHistoryRepository`、`SqlHistoryRepository`、`ChromaHistoryRepository`。
- `memory/sql/schema/ef_history.sql`：原始消息、证据链接、结构化事件和抽取审计表定义。
- `memory/integration/cdc_outbox.py`：`CDCOutbox.append_change()`、`list_changes_since()`、`get_latest_version()`。
- `memory/integration/cdc_checkpoint.py`：`CDCCheckpointManager.get_checkpoint()`、`ack_checkpoint()`、`is_replayed()`、`mark_replayed()`。

## API/CLI/SDK入口

### HTTP/WebSocket API

已在 `api/server.py` 实际看到的主要入口：

- `GET /health`：返回服务、Neo4j driver、历史仓储状态。
- `GET /`、`GET /monitor`：返回两个前端 HTML 页面。
- `POST /api/users/demo`：创建 demo user、签发 user token、返回会话和页面 URL。
- `POST /v1/chat/completions`、`POST /api/chat/completions`：OpenAI-compatible 非流式或 SSE 流式聊天。
- `WebSocket /ws`：带 token/用户隔离的交互与全量同步通道。
- `GET /cdc/changes`、`POST /cdc/ack`：CDC 增量变更读取与消费位点确认。
- `POST /identity/reinfer`：触发人格重新推理。
- `POST /evolution/rollback/{event_id}`：回滚身份演化事件。
- `POST /maintenance/wipe-memory`、`POST /maintenance/restore-demo-data`、`GET /maintenance/compaction-report`：维护、清理、恢复和压缩报告接口。
- `GET /kb/list`、`POST /kb/upload`、`POST /kb/delete`、`POST /kb/clear`：知识库向量文件管理。
- `GET /monitor/stats`：读取身份演化冲突/回滚统计。

`docs/api-openai-compatible.md` 与 `tests/test_openai_compat_api.py` 进一步确认：默认 model 为 `ebbingflow`；外部 system/developer 只作为适配提示注入；stream 模式以 `data: [DONE]` 结束。

### 直接运行和维护 CLI

- `python api/server.py`：`api/server.py` 的 `__main__` 调用 `uvicorn.run("api.server:app", ...)`；Windows 快捷入口是 `run.bat`。
- `python scripts/setup_db.py`：执行 `memory/sql/schema/ef_history.sql`，按 PostgreSQL/SQLite 方言初始化 SQL 表。
- `python scripts/initialize_neo4j.py`：验证 Neo4j 并建立 Entity/Event/Episode/Saga 约束与索引。
- `python scripts/release_closure_check.py [--full]`：用子进程调用指定 pytest 回归/质量/Neo4j 链路测试并写 `reports/release_closure_report.*`。
- `python scripts/backup_system.py [--output PATH]`：导出 Neo4j 节点/关系快照并复制 `.data`，生成 zip。
- `python scripts/restore_system.py [--path PATH] [--yes]`：校验压缩包路径、恢复 `.data` 和 Neo4j 图谱。
- `python scripts/graph_compactor.py [--owner ID] [--dry-run|--apply]`：重复事件压缩、候选归档和推理关系抑制。
- `python scripts/backfill_structured_events.py [--owner-id ID] [--since-msg N] [--limit N] [--dry-run]`：从历史 SQL 对话规则化回填结构化事件。
- `python scripts/backfill_narrative_day.py [--owner-id ID] [--dry-run]`：把聊天中的“第 N 天/day N”传播到 SQL 事件和可匹配的 Neo4j Event。
- `scripts/verify.py` 也是 `__main__` 级别的旧验证入口，但其引用的 `get_persona` 和 `MemoryGraphMiddleware` 未在当前源码中找到，不能视为当前可靠启动验证。

### SDK

当前 `pyproject.toml` 没有 `[project.scripts]`，源码中也没有独立的 Python/TypeScript SDK 包。可确认的 SDK 接入方式是使用任意 OpenAI-compatible 客户端指向 `/v1`；服务内部的“SDK/模型桥接”是 `bridge/llm.py` 的 `LLMBridge`，它使用 `openai.AsyncOpenAI` 调用上游 LLM。

## 技术栈和依赖

### 运行时技术栈

- Python `>=3.10`，打包后端为 `setuptools.build_meta`；测试配置在 `pyproject.toml`，pytest 路径为 `tests/`。
- FastAPI + Uvicorn：HTTP/WebSocket API 和服务生命周期。
- Pydantic v2：请求模型、事件 envelope、身份画像和结构化校验。
- Neo4j Python driver `>=5.20.0`：实体/事件/关系/身份/Episode/Saga 图谱。
- ChromaDB `>=0.5.0`：持久化向量 collection；SentenceTransformers 或 OpenAI-compatible embedding。
- PostgreSQL/asyncpg：可选的 SQL 主存；SQLite/aiosqlite 为默认托底路径。
- OpenAI Python client：聊天 LLM、记忆抽取、Episode/Saga 摘要和人格推理。
- `rank-bm25`：关键词召回；`memory/knowledge_engine.py` 对导入失败提供内置字符重合 fallback。
- `dateparser`：部分 legacy Event 时间参考解析；`memory/event/temporal.py` 提供结构化时间解析。
- NumPy、PyYAML、python-dotenv、APScheduler、httpx、python-multipart、qq-botpy 等由 `requirements.txt` 声明；当前核心读取范围未显示全部模块的运行时调用关系。

### 配置边界

`config.py` 在导入时读取 `.env`：

- `LLMConfig`/`llm_config`：主聊天模型；`memory_llm_config`：事件、Episode/Saga、人格等记忆模型；均是 OpenAI-compatible URL。
- `EmbedConfig`：`local`、`openai` 或 `ollama` embedding。
- `Neo4jConfig`：URI、用户名、密码、数据库。
- `MemoryConfig`：窗口、事件置信度阈值、时间衰减半衰期、Top-K、BM25、人格注入和来源预算。
- `PostgresConfig`/`SqliteConfig`：SQL 后端选择和 `.data/ef_history.db` 默认路径。
- `ServerConfig`：host、port、reload、WebSocket 鉴权及维护 token。

## 架构判断与未确认项

### 架构判断

1. **主链路是“SQL 原件 + Neo4j 认知图 + Chroma 辅助索引”的多存储架构。** `ef_chat_messages` 与 `source_msg_id`/`ef_event_evidence_links` 组成审计链；Episode、Saga 和向量是派生层，不应替代原始消息。
2. **编排采用同步生成、响应后沉淀的中间件模型。** `ChatEngine` 先完成上下文检索和 LLM 回复，再由响应中间件抽取/写入；因此记忆写入失败可以通过 response audit 暴露，但不会改变已经生成的回答。
3. **检索采用意图路由而非简单 Top-K。** `KnowledgeBaseEngine.infer_query_intent()` 与 `HybridScorer._source_policy()` 对 fact/summary/long_term/semantic 分配不同来源预算，符合“证据优先、叙事辅助”的实现意图。
4. **身份演化有明确的防漂移边界。** Actor 强绑定、实体 owner 隔离、来源加权仲裁、旧状态 invalidation、别名关系和 CDC 记录共同构成身份连续性机制。
5. **结构化事件具备规则优先的可回填路径。** 规则抽取、LLM 抽取、归一化、SQL 幂等写入、证据链接和 backfill 脚本形成相对独立的结构化记忆子链路。
6. **部署依赖较重。** API 启动默认要求 SQL、Neo4j 和 Chroma/embedding 可初始化；SQLite 只能替代 PostgreSQL，不能替代 Neo4j 和 Chroma 的核心启动检查。

### 未确认项和源码漂移

- 本次未安装依赖、未启动服务、未连接 Neo4j/PostgreSQL/LLM、未运行 pytest；因此当前文档只确认静态源码结构和测试意图，不宣称运行链路已通过。
- `scripts/verify.py` 使用的 `get_persona`、`MemoryGraphMiddleware` 在当前源码搜索中不存在，说明该脚本与当前 `ChatEngine`/`GraphWriterMiddleware` 版本存在漂移。
- `scripts/release_closure_check.py` 的 `QUALITY_TESTS` 引用 `tests/test_confidence_tuning.py`，当前 `tests/` 文件清单中未发现该文件；脚本的完整 release closure 结果未在本次执行。
- `tests/test_quality_guards.py` 要求 `requirements.txt` 的运行时依赖使用 `==` 固定版本，但当前 `requirements.txt` 使用 `>=`；静态策略与依赖清单不一致。
- `memory/identity/field_contract.py` 顶部说明把 MBTI/Big Five 纳入画像字段，但 `ALLOWED_PROFILE_FIELDS` 实际只有 `name`、`age`、`gender`；MBTI/Big Five 在 `PersonaManager`、`schema.py` 和 `ProfileProperties` 中另有写入/模型路径，统一字段契约边界尚未完全收敛。
- `memory/scoring/hybrid_scorer.py` 的模块说明写有 7 天默认半衰期，但实现从 `MemoryConfig.time_decay_half_life_days` 读取，`config.py` 默认值为 45 天；应以运行配置为准，报告/注释不能直接当作实际参数。
- `tests/test_temporal_goldens.py` 会写入 `.data/temporal_hit_rate.json`，`tests/test_cdc_outbox.py` 会创建并删除 `.data/cdc_test.db`；因此不能在“只读源码审计”范围内把全套测试当作无副作用验证。
- 当前没有独立 SDK 包、`[project.scripts]` 或 OpenAPI/类型客户端生成入口；外部 SDK 兼容性主要依赖 OpenAI-compatible HTTP 协议和手写请求模型。
- Neo4j 线上约束/索引、SQLite 旧库迁移、Chroma embedding function 冲突和多用户隔离需要真实服务/数据验证；本次仅确认了初始化脚本、Cypher 和测试中的静态意图。

## 第三轮：通用底座映射与裁决

> 本章是第三轮研究输入，不是 EbbingFlow 已接入系统工程平台的声明。标记为“源码事实”的内容只来自当前源码、测试和脚本；标记为“平台建议”的内容是面向支持库、模块库、运行核心和统一网关的设计裁决，不能反写成项目已有实现。当前项目没有 `.codegraph/`，本轮没有可用的 EbbingFlow CodeGraph 证据；使用本地源码路径和行号取证。项目根现有独立 `细探-EbbingFlow.md` 未找到；正式文档已声明旧细探结论已吸收，故不虚构未找到的旧笔记内容。

### 3.1 真实唯一链路：对话、记忆、证据和响应

**源码事实。** 当前运行链路只有一个以 `api/server.py` 和 `core/chat_engine.py` 为中心的请求编排：

```text
HTTP / WebSocket / OpenAI-compatible SDK
  → api/server.py 鉴权、用户路由、SSE/WS 输出
  → ChatSession 写入 ef_chat_messages，取得 source_msg_id
  → ChatEngine.chat_stream()
  → MiddlewareChain 请求阶段：身份预取、轻量图谱预取
  → KnowledgeBaseEngine.query()
       → Chroma 向量 / Neo4j 图谱 / SQL 原始消息与结构化事件
       → Episode / Saga / Plan / BM25（按开关和意图召回）
       → HybridScorer 评分、RRF、来源配额、MMR 去重
  → LLMBridge.chat_stream()（OpenAI-compatible 上游）
  → assistant 消息写入 SQL
  → MiddlewareChain 响应逆序：GraphWriterMiddleware
       → LLM EventExtractor + RuleBasedStructuredExtractor
       → temporal.resolve + ContentNormalizerAgent
       → PersonaManager / IdentityEvolutionManager
       → Neo4j Event/Relation/Entity
       → SQL ef_memory_events + ef_event_evidence_links + extraction_audit
       → 5 轮聚合 Episode，再由 SagaManager 聚类
       → CDCOutbox 追加 owner-scoped 变更
  → SSE / WebSocket / 非流式响应
```

证据路径分别由 `core/chat_engine.py:545-724`、`core/middleware.py:48-90`、`core/session.py:118-206`、`memory/graph/writer.py:783-1089` 和 `api/server.py:941-1031` 实现。`source_msg_id` 的权威来源是 SQL 消息自增 ID；Neo4j 事件 UUID 通过 `memory/graph/writer.py:223-246` 写入 `ef_event_evidence_links`。因此“回答已生成”与“记忆沉淀成功”不是同一事务：响应已流出后，响应阶段可以部分失败，审计状态只能记录 `empty`、`partial` 或 `failed`。

**平台建议。** 这条链路可收敛为平台唯一公共入口，但不得复制 EbbingFlow 的多存储业务编排：

```text
统一网关
  → 项目适配层（user/session/token/配置/格式绑定）
  → 模块库：对话编排、记忆检索、记忆沉淀、知识摄入
  → 支持库公开能力：SQL、图、向量、模型、证据、文件
  → 运行核心：请求上下文、租约、超时、取消、资源和证据生命周期
  → 受管 provider / 独立进程 / 外部服务
```

同类项目只能共享一个 `调用能力`/注册表和一个证据结果契约；项目适配层不能直连 Neo4j、Chroma、OpenAI 或数据库，也不能把 provider 对象穿透到模块之外。

### 3.2 映射表：现有代码归属、可吸收边界与不应照搬项

| EbbingFlow 当前源码事实 | 平台建议落点 | 裁决 |
|---|---|---|
| `core/session.py` 的 `ChatSession`、短期 `history`、`context_canvas`、`identity_state` | 运行核心的请求上下文/会话状态接口；长期状态转模块命令 | 吸收“短期上下文与长期状态分离”；不照搬可变 dict 作为跨模块契约 |
| `memory/sql/pool.py` 的 PostgreSQL pool + SQLite fallback；`memory/sql/schema/ef_history.sql` 的消息、事件、证据表 | 支持库的 SQL 能力；运行核心只管理连接/租约/事务边界 | 吸收异步仓储和 owner 过滤；不照搬隐式“连不上 PG 就 SQLite”作为生产 fallback |
| `memory/graph/writer.py` 的 Neo4j Entity/Event/Relation/Episode/Saga、owner 条件和槽位失效 | 支持库的图 provider + 模块库的记忆图模块 | 吸收 owner 隔离、语义幂等、时间槽失效；不照搬模块直接拼接 Cypher 和直接改 `rel` 对象 |
| `memory/vector/storer.py` 的 Chroma `chat_memory`/`knowledge_base`、本地/兼容 API embedding | 支持库的向量索引能力；模型 provider 由运行核心监督 | 吸收 collection/metadata/查询接口；不照搬 embedding 初始化时在主进程握手且异常吞掉 |
| `memory/knowledge_engine.py` 的多源召回、`HybridScorer`、事实证据优先 | 模块库的检索编排与统一记忆结果契约 | 吸收来源预算、意图路由、证据优先、去重；不照搬固定来源键和超大函数内的 provider 细节 |
| `EventExtractor`、规则抽取、归一化、时间解析 | 模块库的“候选抽取→确定性归一化→写入命令”流程；LLM 只产候选 | 吸收规则优先和低置信候选；不把 LLM 返回当权威状态或直接写库 |
| `EventRepository` 的 owner/source/message 幂等和 extraction audit | 支持库 SQL 仓储 + 运行核心证据/审计能力 | 吸收幂等键和 partial/failed 审计；需升级为原子事务、显式错误码和重试策略 |
| `CDCOutbox`/`CDCCheckpointManager` 的版本位点和 replay 去重 | 运行核心事件/Outbox 能力，模块只提交变更意图 | 吸收单调位点、owner 隔离、重复消费保护；不照搬全局 SQLite 单例和逐表独立提交 |
| `EpisodeManager`/`SagaManager` 的 LLM 摘要与聚类 | 模块库叙事聚合模块，使用统一模型能力 | 吸收“原始证据→派生摘要”的层级；不把摘要当事实、不允许摘要覆盖 SQL/图证据 |
| `api/server.py` 的 FastAPI/SSE/WebSocket、鉴权、维护接口 | 统一网关的协议适配和鉴权入口 | 吸收 OpenAI-compatible/SSE/WS 适配；不将每个项目各自暴露维护写接口 |
| `scripts/backup_system.py`、`restore_system.py` 和 `/maintenance/restore-demo-data` | 运行核心备份/恢复资源事务；网关只调用命令 | 吸收 zip 路径校验、临时目录、句柄关闭、恢复锁；不照搬 demo 数据恢复为通用发布机制 |

### 3.3 记忆、状态、证据和写入所有权

**源码事实。** 权威边界不是一个数据库：`ef_chat_messages` 是原始对话终点；Neo4j 是图事实和派生叙事节点；Chroma 是辅助语义索引；CDC SQLite 是变更投递和消费位点。`ChatSession.context_canvas` 是进程内临时状态，每轮 `clear_context_canvas()` 保留少数 persona/episode 计数后重建（`core/session.py:215-247`），不能作为持久权威。`GraphWriterMiddleware` 在一个响应阶段内依次写 Persona、图、SQL 结构化事件、Episode/Saga 和 CDC；这些写操作没有跨 Neo4j、SQL、Chroma 的统一事务。

**平台建议的写 owner。**

- 原始消息：SQL 消息支持库唯一写 owner；模块库只能提交“追加消息”命令。
- 结构化事实/证据链接：事实模块 + SQL 支持库唯一写 owner；证据链接必须引用已存在的消息 ID。
- 图谱实体/事件/关系：图模块通过图支持库写入；其它模块只能读统一结果。
- 向量：索引模块通过向量支持库写入；删除/重建必须带 owner、索引版本和制品证据。
- 画像、Episode、Saga：都是派生状态，必须保留来源消息/事件引用，不能反向提升为原始事实。
- CDC：运行核心/Outbox 作为唯一投递 owner；消费者只能通过 checkpoint 命令推进位点。

建议所有写入命令带 `operation_id、owner_id、source_msg_id、idempotency_key、schema_version、recorded_at`；成功、业务失败、拒绝、超时和取消都写结构化证据。EbbingFlow 当前只在部分路径具备这些字段，不能宣称已满足该建议。

### 3.4 工作流/任务执行映射

**源码事实。** 当前没有独立持久任务队列、任务状态表、worker 进程、通用 DAG 或取消协议。`ChatEngine.chat_stream()` 是单请求内顺序执行的 01–14 步；`MemoryRetrieverMiddleware` 和 `GraphWriterMiddleware` 仍在同一个服务进程的 async 调用链中。计划/待办只是 `ef_memory_events` 中 `PLAN/TASK/SCHEDULE/GOAL` 的检索视图（`memory/knowledge_engine.py:1102-1199`），不是执行器。`scripts/release_closure_check.py:32-67` 使用 `subprocess.run` 运行测试，属于验证脚本而非生产任务系统。生产代码中能确认的线程只有 `api/server.py:783-791` 的 daemon 浏览器启动线程；未找到生产任务进程/worker。`APScheduler` 仅在依赖声明/搜索线索中出现，当前源码没有对应调度链。

**平台建议。** 若把该模式吸收为通用任务能力，应新建唯一任务执行契约，而不是把 `ChatEngine` 复制成第二套任务系统：

```text
网关命令 → 模块库创建任务（幂等） → 运行核心任务记录/租约
  → 支持库/受管 provider 执行 → 事件/结果/证据写 owner
  → checkpoint → 可重试完成或可解释终态
```

最小任务状态建议为 `created → running → succeeded|failed|timed_out|cancelled|crashed`，另有 `retrying` 和 `blocked`；每次尝试必须有 attempt、开始/结束时间、取消原因、退出码/异常摘要、资源清单和恢复动作。计划记忆只能产生任务候选，不能越过统一命令入口直接执行。

### 3.5 线程、进程、模型、数据库和文件资源生命周期

| 资源 | 当前源码事实 | 平台建议生命周期 |
|---|---|---|
| asyncio 任务/事件循环 | FastAPI lifespan、请求 handler 和 middleware 使用 async；没有统一 task registry；`MemoryRetrieverMiddleware.__del__` 甚至尝试 `loop.create_task(self.close())` | 运行核心登记 operation/task，持有取消令牌；正常、异常、取消、超时都 await 收尾，禁止依赖 `__del__` |
| 线程/锁 | `TokenMonitor`、CDCOutbox 使用 `threading.Lock`；浏览器 opener 是 daemon thread；恢复用 `asyncio.Lock` | 线程只放阻塞 provider/隔离适配层；声明 owner、join/停止动作和超时；daemon 不能承载关键写入 |
| 进程/进程组 | 当前生产源码未启动 worker；release closure 用 `subprocess.run`，无独立进程组治理证据 | 第三方 C 扩展、长任务和不可信命令由运行核心 `Popen(start_new_session=True)` 管理；超时先终止进程组再强杀，回收并核验残留 |
| 主聊天模型 | `LLMBridge.__init__` 每个 category 创建 `AsyncOpenAI`，`LLMConfig` 给 timeout 60s、max_retries 2；`chat_stream` 异常转成文本错误块（`bridge/llm.py:13-101`） | 模型属于 provider 资源；统一超时/重试/错误码/费用/模型版本和流关闭；异常不得伪装为正常 assistant 文本 |
| 记忆模型 | `EventExtractor`、Episode、Saga、人格推理各自通过 `LLMBridge(memory_llm_config)` 调模型 | 模块库声明用途、结构化输出和预算；运行核心隔离模型会话；LLM 只输出候选，确定性 reducer 决定状态 |
| embedding 模型 | `VectorStorer` 选择本地 SentenceTransformers 或 OpenAI/Ollama 兼容函数，构造时做一次 `embed_fn(["h"])` 握手（`memory/vector/storer.py:48-83`） | embedding provider 独立能力；主进程不得加载不稳定 C 扩展；模型缓存、版本、维度和索引绑定，失败返回 `PROVIDER_UNAVAILABLE` |
| SQL 连接/事务 | PostgreSQL pool 懒初始化，`min_size=1,max_size=5,command_timeout=10`；无 PG 时每次 `get_db()` 创建 SQLite/aiosqlite 连接并 finally 关闭兼容连接（`memory/sql/pool.py:19-118`） | 连接池由支持库持有，运行核心负责租约和 shutdown；每个写事务明确边界，禁止跨库“看似成功”的部分提交 |
| Neo4j driver/session | lifespan 创建 global driver 并 verify；GraphWriter/KnowledgeBase/MemoryRetriever 也各自持有 driver；`ChatEngine.close()` 和 lifespan 关闭部分句柄 | driver/session 统一由 provider factory/运行核心登记；模块不重复创建全局 driver；关闭必须可重复并有未关闭会话检查 |
| Chroma client/collection | `VectorStorer` 持有 PersistentClient，写 `.data/chroma`；`ChatEngine` 缓存一个 storer，上传/维护 API 还会新建 storer | 统一向量能力实例和索引版本；临时重建必须隔离目录、原子切换、保留旧索引和恢复指针 |
| 本地文件/临时目录 | `.data/ef_history.db`、`cdc_outbox.db`、`cdc_checkpoint.db`、`.data/chroma` 和 compaction 报告是运行数据；备份/恢复使用 `TemporaryDirectory` 并在 finally 清理（`api/server.py:2177-2236`） | 文件能力统一做路径逃逸、大小/类型/权限校验；创建者持有临时目录，成功/失败/取消/崩溃都清理并读回验证 |
| 备份/恢复句柄 | 恢复先关 WebSocket、运行句柄，再替换本地数据、恢复 Neo4j、重建 runtime；`restore_demo_lock` 串行化 | 作为运行核心恢复事务：先记录意图，再切换指针；失败可回滚，崩溃后新进程按记录恢复，不把 demo 恢复逻辑当发布系统 |

### 3.6 失败、超时、取消、崩溃矩阵

| 场景 | 当前源码事实 | 当前缺口/平台验收建议 |
|---|---|---|
| 参数/输入非法 | API 校验空 user message；KB 只接受 UTF-8/GBK，`chunk_size` 未形成完整统一契约；事件/LLM 解析失败多返回空列表或错误审计 | 统一 `INVALID_ARGUMENT`，写拒绝证据；验证空输入、超长输入、非法编码、超大文件和非法 owner |
| provider 不可用/断线 | lifespan 对 SQL、Neo4j、Chroma 初始化失败直接阻止启动；LLMBridge 捕获异常，流式路径 yield `[AI 响应异常: ...]`；BM25 缺库可 fallback | 统一 `PROVIDER_UNAVAILABLE`/可重试标志；禁止把异常字符串当 assistant 成功结果；每 provider 做隔离探针 |
| 业务失败/部分写入 | 响应后写入按步骤执行；结构化事件逐条写，`record_extraction_audit` 标记 `partial`；图、SQL、CDC 可能已经分别提交 | 需要 operation/outbox 关联和补偿状态；验证图成功、SQL 失败、CDC 失败等交叉故障，不能只看 HTTP 200 |
| 上游超时 | LLM client 配置 timeout；PostgreSQL pool command_timeout；未见统一 `asyncio.wait_for` 或请求 deadline 传播 | 运行核心注入硬截止时间，provider 返回 `TIMED_OUT`；验证超时后流、连接、锁、临时文件和模型响应均释放 |
| 客户端主动取消/断线 | WS 捕获 `WebSocketDisconnect` 并移除连接；HTTP 流生成器没有显式取消清理；`ChatEngine` 没有取消令牌 | 取消必须穿透网关→模块→provider；取消后的 assistant/记忆写入语义要固定为“未提交/已提交可追踪”，并验证后台无残留任务 |
| 进程崩溃/强杀 | 当前生产没有任务 worker；服务崩溃恢复依赖外部进程重启和持久化 SQL/Neo4j/Chroma/CDC；恢复接口仅对 demo 数据提供重建流程 | 任务必须有 attempt/租约/心跳和启动扫描；强杀在写前、写后、指针切换前后验证无半状态；读回进程、端口、锁、文件和数据库事务 |
| 重复调用/重放 | Neo4j event 有 semantic key；SQL event 有复合幂等索引/应用预查；CDC replay_dedup 和 checkpoint 只提供基础能力 | 统一 idempotency key，确保跨 provider 一致；并发重复请求必须只有一个权威写 owner，拒绝/成功都留证据 |
| 关闭/重启 | FastAPI lifespan 关闭 engine、Neo4j driver、checkpoint、SQL pool；多个模块可能各自创建 driver；恢复代码有重新初始化路径 | 统一 shutdown 顺序和幂等关闭；新进程启动做 orphan/resource scan，证明没有遗留连接、线程、临时目录和锁 |

### 3.7 吸收、隔离、待核裁决

- **吸收：** `source_msg_id → event_uuid` 证据链、owner 隔离、规则优先的结构化抽取、时间槽失效、语义幂等、来源预算、事实问题提升 SQL 证据、Episode/Saga 作为派生叙事、CDC 单调位点。
- **升级后吸收：** `ChatSession` 的短期窗口、SQL/Neo4j/Chroma provider 抽象、extraction audit、备份临时目录和恢复锁。必须先套统一结果、租约、超时、取消、原子写和失败证据契约。
- **隔离：** LLM 直接决定 Episode/Saga 文本但不应决定权威事实；Chroma 不能替代 SQL 原件；可变 `context_canvas` 不能跨进程共享；全局单例 outbox/checkpoint、模块各自建 driver、API 内直接维护库、硬编码 `.data` 路径不能成为平台公共模式。
- **废弃/不照搬：** `LLMBridge` 将异常转成文本块、middleware 捕获后继续、SQL/Neo4j/CDC 分别提交、依赖声明却无实现的 APScheduler 线索、无持久状态的“计划执行”语义。
- **待核：** Neo4j 线上约束/索引、真实 PostgreSQL 事务语义、Chroma embedding 版本冲突、多用户并发下同一 session 的写入顺序、服务崩溃后的跨存储一致性；这些不能凭静态源码归为已实现。

### 3.8 L0–L4 验证契约

| 等级 | 必须证明 | 针对本项目的现场命令/证据 | 判定 |
|---|---|---|---|
| L0 静态身份与边界 | 根目录、文档、关键源码路径、无越界改动；CodeGraph 可用性如实记录 | `pwd`；`find`/文件清单；检查仅 `ARCHITECTURE.md` 变更；本轮 CodeGraph 返回“未索引” | 本轮可证明；不能把错绑 V3 代码图算目标证据 |
| L1 静态契约 | Python 编译、导入路径、API/脚本引用和文档链接不破 | `python -m compileall -q api bridge core memory scripts`；源码搜索 `细探-EbbingFlow.md`、旧入口和缺失测试引用 | 只证明语法/静态结构，不证明外部服务 |
| L2 离线行为 | 不连接外部服务的鉴权、时间、字段、评分、幂等、规则抽取和文档门禁 | `python -m pytest -q` 中明确离线测试；优先 `tests/test_ws_auth.py`、`test_temporal_bitemporal.py`、`test_semantic_idempotency.py`、`test_profile_field_contract.py`、`test_quality_guards.py` | 测试不得把 skip 或历史 report 当通过；读退出码和实际测试数 |
| L3 真实集成 | SQL/Neo4j/Chroma/embedding/LLM 的真实启动、读写、证据回链、CDC ack、WS/SSE 流和资源关闭 | `python scripts/release_closure_check.py --full`；按环境提供真实 PostgreSQL/Neo4j/模型，并核对 `reports/release_closure_report.json` | 当前源码只声明了脚本路径；本轮未连接这些外部服务，故不宣称 L3 通过 |
| L4 破坏与恢复 | 超时、取消、断线、provider 故障、重复并发、强杀、恢复、备份回滚和残留清理 | 在隔离测试环境注入断线/超时/SIGKILL，重启新进程后读回 SQL/Neo4j/Chroma/CDC 和 OS 资源；记录退出码、attempt、证据和残留扫描 | 当前项目未提供完整通用 L4 执行器；只能列为平台接入前置门禁 |

本轮源码级结论是：EbbingFlow 提供了可复用的“记忆事实—派生叙事—证据回链—多源检索”领域样本，但没有提供可直接充当平台运行核心的任务、资源、取消、崩溃恢复或统一网关实现。平台吸收应止于契约和模块边界；真正的运行治理必须由平台唯一 owner 实现并用 L3/L4 现场证据证明。

## 本次源码证据范围

本次实际读取了：`README.md`、`requirements.txt`、`requirements-dev.txt`、`docs/api-openai-compatible.md`、`docs/docker-deploy.md`、`CONTRIBUTING.md`、`tests/README.md`、`tests/conftest.py`；旧的 `细探-EbbingFlow.md` 分析结论已吸收进本文，不再作为独立事实源；核心入口 `api/server.py`、`core/chat_engine.py`、`core/session.py`、`core/middleware.py`、`bridge/llm.py`、`config.py`；核心记忆/模型 `memory/knowledge_engine.py`、`memory/scoring/hybrid_scorer.py`、`memory/event/{slots,extractor,temporal}.py`、`memory/graph/{writer,retriever}.py`、`memory/identity/{schema,field_contract,resolver,state_reducer,conflict_resolver,manager,evolution,inference}.py`、`memory/history/repository.py`、`memory/sql/{pool,event_repository}.py`、`memory/sql/schema/ef_history.sql`、`memory/vector/{storer,devourer}.py`、`memory/integration/{episode_manager,saga_manager,cdc_outbox,cdc_checkpoint}.py`；脚本 `scripts/{setup_db,initialize_neo4j,verify,release_closure_check,backup_system,restore_system,graph_compactor,backfill_structured_events,backfill_narrative_day}.py`；以及代表性测试 `tests/test_openai_compat_api.py`、`test_ws_auth.py`、`test_ws_profile_payload.py`、`test_event_evidence_chain.py`、`test_temporal_bitemporal.py`、`test_temporal_goldens.py`、`test_semantic_idempotency.py`、`test_m2_episode.py`、`test_cdc_outbox.py`、`test_profile_field_contract.py`、`test_conflict_arbitration.py`、`test_quality_guards.py`。

本文件已吸收此前 `细探-EbbingFlow.md` 的源码分析结论；后续只维护本文件，旧细探笔记不再作为独立事实源。

本文件仅新增/更新项目根的 `ARCHITECTURE.md`，没有修改已有源码、安装依赖、运行服务或提交 Git。
