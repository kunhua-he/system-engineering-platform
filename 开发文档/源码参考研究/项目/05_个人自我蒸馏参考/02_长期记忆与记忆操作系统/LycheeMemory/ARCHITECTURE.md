# LycheeMemory 架构建档

> **文档性质**：首轮全量、基于当前磁盘源码的架构档案。源码事实优先于 README、安装说明和已有“细探”材料；“细探-LycheeMemory.md”只作为施工材料使用，没有机械复制。
>
> **审计边界**：本轮只读源码、依赖、测试和说明文件，并新增本文件；没有安装依赖、启动服务、运行构建、生成业务数据或提交 Git。
>
> **项目根目录**：`/Users/hekunhua/Documents/Agent/github 源码参考/05_个人自我蒸馏参考/02_长期记忆与记忆操作系统/LycheeMemory`

## 1. 文本总流程图

```text
外部 Agent / OpenAI SDK / Claude Code / Hermes / OpenClaw / Web Demo
                         │
          ┌──────────────┼─────────────────┐
          │              │                 │
     FastAPI HTTP       MCP HTTP       宿主插件适配层
  /chat, /memory/*      /mcp         openclaw / hermes / claude
          └──────────────┼─────────────────┘
                         ▼
                 src.api.server:create_app
                         │  app.state.pipeline
                         ▼
                 src.core.factory:create_pipeline
       ┌─────────────────┼──────────────────┐
       │                 │                  │
  LLM/Embedder       Session/Skill       Semantic/Visual
  provider adapters   stores              engines
       └─────────────────┼──────────────────┘
                         ▼
                 src.core.graph:LycheePipeline
                         │ LangGraph StateGraph
                         ▼
  START → wm_manager → visual_memory → search → reason → END
             │              │              │        │
             │              │              │        ├─ assistant turn 回写
             │              │              │        └─ 后台 consolidate
             │              │              │
             │              │              └─ SearchCoordinator
             │              │                   ├─ recent context
             │              │                   ├─ ActionState
             │              │                   ├─ LLM SearchPlan
             │              │                   ├─ CompactSemanticEngine.search
             │              │                   └─ skill store / HyDE
             │              │
             │              └─ VLM 提取 → 图片文件 + VisualMemoryRecord
             │                                  → caption/visual embedding
             │                                  → VisualStore / VisualRetriever
             │
             └─ session append → token budget → async/sync summary

后台固化（ConsolidatorAgent）
  session turns + watermark
       → OnlineSemanticChunker（embedding 驱动、无 LLM）
       → CompactSemanticEncoder（一次 LLM：类型化抽取/消歧/标签）
       → MemoryRecord（SHA256 semantic_text）
       → SQLiteSemanticStore + LanceVectorIndex
       → FieldedEvidenceOrganizer（entity/tag/temporal/event_frame）
       → evidence_nodes SQLite + LanceDB
       → 技能抽取 LLM → SQLiteSkillStore + LanceDB skills
```

## 2. 项目定位与边界

LycheeMemory 是面向 LLM Agent 的轻量长期记忆基础设施，当前代码将会话工作记忆、结构化语义记忆、程序性技能记忆和视觉记忆组合成一个可通过 HTTP/MCP/宿主插件接入的服务。它不是单一向量库：核心路径同时维护会话日志、摘要、结构化 `MemoryRecord`、字段化证据索引、原始对话 turn 向量索引、技能库和视觉记录。

主要目标：

- 通过工作记忆压缩控制活动上下文的 token 预算；
- 将对话增量固化为可检索的类型化长期记录；
- 用 FTS5、LanceDB、字段化证据路由和可选 reranker 组合检索；
- 以 `background_context` 和 provenance 形式为最终推理提供记忆背景；
- 为支持 MCP 或插件生命周期的宿主提供自动召回、轮次镜像与固化桥接。

当前真实实现边界：

- 语义记忆的生产组装路径是 `CompactSemanticEngine`，不是 README 中旧式 Neo4j/Graphiti 路径；
- 当前引擎源码的主索引模型是 `MemoryRecord + evidence_nodes + episode_turns`，没有在 `src/memory/semantic` 中发现 `CompositeRecord` 类定义；API 仍保留旧 `composites` 字段和兼容分支；
- 视觉模块在 `src/memory/visual/`，根目录 `vision/` 还保留一套相似文件/README，是否仍为独立公共入口需后续确认；
- 本项目包含服务端、Web Demo、三个宿主适配目录和示例，但不是一个已经验证过的生产部署包。

## 3. 真实分层与目录地图

### 3.1 入口与接入层

| 层 | 关键路径 | 真实职责 |
|---|---|---|
| 进程入口 | `main.py` | 解析 `--reload`、`--port`；创建 `data/`；按配置创建 LLM/Embedder、Pipeline、FastAPI，并调用 Uvicorn。 |
| HTTP API | `src/api/server.py` | 创建 FastAPI、CORS、trace ID、`/health`，挂载 chat/session/memory/pipeline/visual 路由和 MCP 路由。 |
| HTTP 请求模型 | `src/api/models.py` | Pydantic 请求/响应契约：Chat、OpenAI Chat Completions、memory search/reason/consolidate、session、visual。 |
| MCP 出口 | `src/mcp/server.py`, `src/mcp/handler.py`, `src/mcp/tools_schema.py` | `/mcp` 的 POST JSON-RPC、GET SSE keepalive、MCP session header、`tools/list`/`tools/call` 分发。 |
| OpenClaw | `openclaw-plugin/index.ts`, `openclaw-plugin/src/client.py` | MCP/HTTP 双传输、工具注册、宿主生命周期 hook、自动追加 user/assistant turn、边界/主动固化。 |
| Hermes | `hermes-plugin/lycheemem/plugin.yaml`, `runtime.py`, `client.py`, `tools.py` | Hermes hook 与工具注册；前置 smart search、后置 turn mirror、session end/finalize consolidate。 |
| Claude Code | `claude-plugin/lycheemem/.mcp.json`, `README.md`, `bin/lycheemem_hook.py`, `hooks/hooks.json` | HTTP MCP 配置、memory skill、用户提示前置召回和 Stop/SessionEnd 生命周期桥接。 |
| Web Demo | `web-demo/src/App.tsx`, `api.ts`, `state.ts`, `types.ts`, `vite.config.ts` | React/Vite 对话界面和语义记忆、技能、工作记忆、视觉记忆视图；开发代理指向后端。 |

### 3.2 编排层

| 组件 | 路径 | 关键职责 |
|---|---|---|
| 配置 | `src/core/config.py` | `Settings(BaseSettings)` 从 `.env`/环境变量加载 LLM、embedding、工作记忆、SQLite/LanceDB、reranker、VLM、视觉路径。 |
| 工厂 | `src/core/factory.py:create_pipeline` | 解析 embedding 真实维度，组装 session store、skill store、compressor、semantic engine、四个 Agent、视觉组件。 |
| 状态 | `src/core/state.py:PipelineState` | LangGraph 节点之间传递 query/session、工作记忆、检索计划/状态、上下文、答案、视觉结果、token 统计和固化状态。 |
| Pipeline | `src/core/graph.py:LycheePipeline` | 构建 LangGraph；提供 `run`、`arun`、`astream_steps`、`consolidate`、后台固化状态查询。 |
| 工作记忆 Agent | `src/agents/wm_manager.py:WMManager` | 追加 user turn、token 计数、70% 异步预压缩/90% 同步压缩、渲染摘要+最近原始轮次。 |
| 检索协调 Agent | `src/agents/search_coordinator.py:SearchCoordinator` | 生成 ActionState、查询分析/HyDE、SearchPlan，调用语义引擎和技能库，返回检索 provenance。 |
| 最终推理 Agent | `src/agents/reasoning_agent.py:ReasoningAgent` | 将压缩历史、`background_context`、技能文档组织成 LLM messages，生成同步或流式最终回答。 |
| 固化 Agent | `src/agents/consolidator_agent.py:ConsolidatorAgent` | 先执行语义固化，再可选执行技能抽取；返回步骤日志和计数。 |
| Agent 基类 | `src/agents/base_agent.py` | 统一 prompt、LLM 调用和 JSON 解析辅助。 |

### 3.3 四类记忆层

1. **Working Memory**：`src/memory/working/session_store.py` 的 `SessionLog`、`InMemorySessionStore`，以及 `sqlite_session_store.py:SQLiteSessionStore`。`SessionLog` 保存 turns、summaries、topic/tags 和单调固化水位线 `last_consolidated_turn_index`。
2. **Semantic Memory**：`src/memory/semantic/engine.py:CompactSemanticEngine` 是总装入口；`base.py` 定义抽象契约；`chunker.py` 做在线分块；`encoder.py` 将 chunk 编码为 `MemoryRecord`；`ingestion.py` 执行完整摄入；`evidence_graph.py` 构造字段化证据节点；`retrieval/` 下的 mixin 组合召回、路由、融合、展开、选择和策略。
3. **Procedural Memory**：`src/memory/procedural/sqlite_skill_store.py:SQLiteSkillStore`，SQLite 保存 skill 元数据和 FTS5，LanceDB 保存 intent 向量；`SearchCoordinator` 依据 `answer/action/mixed` 模式按需检索，`ReasoningAgent` 最多注入两个技能文档。
4. **Visual Memory**：`src/memory/visual/models.py:VisualMemoryRecord`、`visual_store.py:VisualStore`、`visual_extractor.py:VisualExtractor`、`visual_retriever.py:VisualRetriever`、`visual_forgetter.py:VisualForgetter`、`multimodal_embedder.py`。实际三层存储为 SQLite 元数据、LanceDB 向量、本地图片文件。

### 3.4 外部模型与基础设施适配层

- LLM 抽象：`src/llm/base.py:BaseLLM`；主实现 `src/llm/litellm_llm.py:LiteLLMLLM`，支持 LiteLLM provider/model 格式、同步/异步/流式调用、重试和 token 统计。
- Embedding 抽象：`src/embedder/base.py:BaseEmbedder`；实现 `litellm_embedder.py:LiteLLMEmbedder`、`st_embedder.py:SentenceTransformerEmbedder`、`http_embedder.py:HTTPEmbeddingServerEmbedder`。
- 向量索引：`src/memory/semantic/vector_index.py:LanceVectorIndex`，维护 `memory_records`、`evidence_nodes`、`episode_turns` 三类表并检查向量维度。
- 共享工具：`src/utils/time_utils.py` 处理时间键/日期归一化；LLM/Embedding base 中分别维护进程级统计 JSON。

## 4. 核心数据流

### 4.1 普通聊天请求

1. `main.py` 通过 `create_pipeline()` 注入 `LiteLLMLLM` 和某个 `BaseEmbedder`，`create_app()` 将 Pipeline 放入 `app.state.pipeline`。
2. `POST /chat/complete` 或 `POST /chat` 经 `get_pipeline()` 取得实例。普通 Chat 请求由 `ChatRequest` 校验，OpenAI 兼容请求由 `OpenAIChatCompletionRequest` 转换为 session/message。
3. `LycheePipeline` 执行 `wm_manager → visual_memory → search → reason`。`WMManager` 先写 user turn；token 超过 warn/block 阈值时分别启动后台预压缩或同步压缩。
4. 视觉节点/路由使用 VLM 生成 caption、实体、场景和重要性；`VisualStore` 保存图片与记录，可生成 caption/visual embedding。
5. `SearchCoordinator` 从摘要和最近 turn 生成 `recent_context`，构造 `ActionState`，通过 LLM 得到检索计划，再调用 `CompactSemanticEngine.search()`；语义检索可组合 evidence-node、MemoryRecord、原始 episode-turn 召回，技能检索可使用 HyDE 向量。
6. `ReasoningAgent` 将最终背景上下文和可复用技能放入 prompt，生成答案；Pipeline 将 assistant turn 写回 session，并在开启 `auto_consolidate` 时启动后台固化。
7. 非流式返回 JSON；流式路径 `astream_steps()` 逐节点/逐 token 产生 SSE，最终返回 answer、trace、token usage。

### 4.2 长期语义固化

1. `LycheePipeline.consolidate()` 或 `run_memory_consolidate()` 读取 session 的固化水位线，只取新增、未删除 turns；`force_ingest` 可将有效水位线置零。
2. `CompactSemanticEngine.ingest_conversation()` 先将原始 turns 写入 `episode_turns` 向量索引，再交给 `OnlineSemanticChunker.add_turns()`。chunker 为每个 session 保留 pending chunk，以 embedding 分布变化和 token 上限决定边界；`flush_session` 强制收尾。
3. `CompactSemanticEncoder.encode_conversation_with_disambiguation()` 调用一次 LLM，抽取 `semantic_text`、`memory_type`、实体、标签、时间和证据 turn；Python 侧生成 `normalized_text`、校正类型、归一化 turn、`record_id=SHA256(semantic_text)`。
4. `SemanticIngestionMixin` 对同一批 record 按 ID 精确去重，批量生成 semantic/normalized embedding，写入 `SQLiteSemanticStore.memory_records`、FTS5 和 `LanceVectorIndex.memory_records`。
5. `FieldedEvidenceOrganizer.organize_on_ingest()` 不使用句向量相似度构造关系，而根据 encoder 已提供的 entity/tag/temporal/session-turn 字段构造 `entity`、`tag`、`entity_tag`、`temporal`、`event_frame` 节点，分别写入 SQLite `evidence_nodes`、FTS5 和 LanceDB。
6. 若未跳过技能抽取，`ConsolidatorAgent` 再调用 LLM 提取 `intent/doc_markdown`，通过 intent embedding 相似度阈值 0.85 做技能 upsert/去重，写入 `SQLiteSkillStore` 和 LanceDB skills 表。
7. 固化成功后更新 session 水位线；后台模式只返回 `started`，错误记录日志而不阻塞主回复。

### 4.3 视觉记忆流

```text
Base64 image
  → VisualExtractor.extract_from_base64
  → SHA256 image_hash + VLM JSON(caption/entities/scene/importance)
  → VisualStore.save_image_file(session directory)
  → VisualMemoryRecord
  → caption embedding + optional CLIP visual embedding
  → SQLite visual_memories + LanceDB visual_records
  → VisualRetriever(text/image/session) → API / pipeline visual_context
  → VisualForgetter(decay/TTL) → expired=1 soft expiration
```

## 5. 关键类、函数与数据模型索引

### 5.1 Pipeline 与 Agent

- `main.py:main`, `_create_llm`, `_create_embedder`：进程 CLI 入口和 provider 选择。
- `src/core/factory.py:create_pipeline`, `_resolve_embedding_dim`, `_create_session_store`：依赖组装、embedding 维度探测/缓存、SQLite session 选择。
- `src/core/graph.py:LycheePipeline._build_graph`, `run`, `arun`, `astream_steps`, `consolidate`：同步/异步/流式主流程与水位线固化。
- `src/agents/wm_manager.py:WMManager.run`, `append_assistant_turn`：会话回写和压缩调度。
- `src/memory/working/compressor.py:WorkingMemoryCompressor.should_compress`, `find_compression_boundary`, `compress`, `render_context`：双阈值和摘要锚点。
- `src/agents/search_coordinator.py:SearchCoordinator.run`, `_build_action_state`, `_build_retrieval_plan`, `_search_skills`：状态化检索和技能模式切换。
- `src/agents/reasoning_agent.py:ReasoningAgent.run`, `astream`, `_build_messages`：最终答案和流式输出。
- `src/agents/consolidator_agent.py:ConsolidatorAgent.run`, `_run_compact`：语义固化、技能提取和步骤结果。

### 5.2 语义模型与存储

- `src/memory/semantic/models.py:MemoryRecord`：原子长期记忆记录；核心字段为 `record_id`、`memory_type`、`semantic_text`、`normalized_text`、entities/tags/temporal、confidence、evidence_turn_range、source_session、过期字段。
- `src/memory/semantic/models.py:ActionState`：当前子目标、拟执行动作、工具结果、约束、失败信号、token budget、recent context。
- `src/memory/semantic/models.py:SearchPlan`、`EvidenceRoute`：语义/pragmatic 查询、模式、时间过滤、深度、问题类型、证据目标/约束和独立 evidence route。
- `src/memory/semantic/base.py:SemanticSearchResult`、`ConsolidationResult`、`BaseSemanticMemoryEngine`：搜索/固化公共契约。
- `src/memory/semantic/engine.py:CompactSemanticEngine.search`, `delete_all`, `export_debug`：语义引擎总装入口。
- `src/memory/semantic/ingestion.py:SemanticIngestionMixin.ingest_conversation`, `_ingest_semantic_chunk`：turn→chunk→record→索引/证据组织。
- `src/memory/semantic/encoder.py:CompactSemanticEncoder.encode_conversation_with_disambiguation`：LLM 输出到 Python-owned `MemoryRecord` 的边界。
- `src/memory/semantic/evidence_graph.py:FieldedEvidenceOrganizer.organize_on_ingest`：字段化 evidence node 构造。
- `src/memory/semantic/sqlite_store.py:SQLiteSemanticStore`：`memory_records`/`evidence_nodes` 表、FTS5、upsert/search/export。
- `src/memory/semantic/vector_index.py:LanceVectorIndex`：三类 LanceDB 表、ANN upsert/search、向量维度校验。
- `src/memory/semantic/chunker.py:OnlineSemanticChunker.add_turns`：每 session pending chunk 和边界决策。

### 5.3 技能、视觉和宿主桥接模型

- `src/memory/procedural/sqlite_skill_store.py:SQLiteSkillStore.add/search/fulltext_search/record_usage`：技能持久化、FTS5、cosine ANN、使用统计。
- `src/memory/visual/models.py:VisualMemoryRecord`：图片引用、VLM 结果、caption/visual embedding、重要性、检索统计和过期字段。
- `src/memory/visual/visual_store.py:VisualStore.store/search_by_text/search_by_visual_embedding/mark_expired`：三层视觉存储和软删除。
- `src/memory/visual/visual_extractor.py:VisualExtractor.extract_from_base64`：图像 hash、压缩、VLM JSON、LRU 风格缓存。
- `src/memory/visual/visual_retriever.py:VisualRetriever.retrieve_by_text/retrieve_by_image/retrieve_by_session`：三类视觉召回。
- `src/memory/visual/visual_forgetter.py:VisualForgetter.compute_decay_score/cleanup_expired/schedule_ttl`：重要性和检索次数影响的遗忘策略。
- `src/api/models.py`：`ChatRequest`、`OpenAIChatCompletionRequest`、`MemorySearchRequest`、`MemorySmartSearchRequest`、`MemoryReasonRequest`、`MemoryAppendTurnRequest`、`MemoryConsolidateRequest` 及响应模型。
- `src/mcp/handler.py:LycheeMCPHandler.handle/_dispatch_tool`：JSON-RPC 到共享 API helper 的分发。

## 6. API、CLI、SDK 与插件接口

### 6.1 HTTP API

路由真实注册位置为 `src/api/server.py` 和各 router：

- `GET /health`：健康状态和版本。
- `POST /chat/complete`：Lychee 原生非流式对话；`POST /chat`：SSE 流式对话。
- `POST /v1/chat/completions`：OpenAI Chat Completions 兼容接口；`POST /v1/chat/complete`、`POST /v1/chat` 为兼容别名，支持 `stream`。
- `POST /memory/search`：语义记忆和技能库统一原始检索。
- `POST /memory/smart-search`：检索并生成 `background_context`，按 `mode`/`response_level` 裁剪输出。
- `POST /memory/reason`：给定背景上下文执行 `ReasoningAgent`，可选择回写会话。
- `POST /memory/append-turn`：外部宿主镜像单条自然语言 turn。
- `POST /memory/consolidate`：按水位线固化，支持后台/同步、force/skip-skills/flush；兼容旧路径 `POST /memory/consolidate/{session_id}`。
- `GET /memory/session/{session_id}`、`GET /sessions`、`DELETE /memory/session/{session_id}`、`PATCH /memory/session/{session_id}/meta`：会话查看与管理。
- `GET /memory/graph`、`GET /memory/graph/search`、`DELETE /memory/graph/clear`：调试/前端树视图、FTS 搜索和清空语义记忆。
- `GET /memory/skills`、`DELETE /memory/skills/clear`、`DELETE /memory/skills/{skill_id}`：技能查看/清理。
- `/visual/memories`、`/visual/memories/{record_id}`、`/visual/memories/{record_id}/image`、`POST /visual/search`、`GET /visual/stats`、`DELETE /visual/memories/{record_id}`：视觉记忆管理。
- `GET /pipeline/status`、`GET /pipeline/last-consolidation`：运行统计和固化轮询。
- 全局 HTTP middleware 注入/回传 `X-Trace-ID`；当前 CORS 是 `allow_origins=["*"]`，源码未看到认证依赖。

### 6.2 MCP

`POST /mcp` 使用 JSON-RPC，`GET /mcp` 提供 SSE keepalive；`initialize` 返回 `Mcp-Session-Id`，后续请求需复用。`tools/list` 暴露：

- `lychee_memory_smart_search`
- `lychee_memory_search`
- `lychee_memory_append_turn`
- `lychee_memory_consolidate`

工具处理最终复用 `src/api/routers/memory.py` 的 `run_memory_*` helper，而不是复制一套记忆业务实现。

### 6.3 CLI 与 Python/HTTP SDK

- 源码 CLI：`python main.py [--reload] [--port PORT]`。
- 示例 CLI：`python examples/api_pipeline_demo.py`，支持 `--base-url`、`--session-id`、`--multi-turn`、`--no-consolidate`、`--sync-consolidate` 等；示例运行时依赖 `requests`。
- README 宣称存在 `lycheemem-cli`，但当前 `pyproject.toml` 未看到 `[project.scripts]` 声明；该命令本轮标为未确认，不把它当作已验证入口。
- OpenAI SDK：README 给出的 `OpenAI(base_url="http://localhost:8000/v1", api_key="lycheemem")` 通过 `/v1/chat/completions` 接入。
- 项目没有看到独立发布的 Python SDK 包；`openclaw-plugin/src/client.py`、`hermes-plugin/lycheemem/client.py` 是宿主 HTTP/MCP 客户端适配器，非核心 SDK。

## 7. 技术栈与依赖

### 后端

- Python `>=3.9`；打包后端 Hatchling；源码包配置为 `src`。
- FastAPI `>=0.115`、Uvicorn（代码运行时导入）、Pydantic Settings。
- LangGraph `StateGraph` 编排，LangChain Core 基础依赖。
- LiteLLM 统一 LLM/embedding provider；OpenAI、Google GenAI 依赖可作为 provider 支持。
- SQLite + FTS5：会话、语义记录、证据节点、技能和视觉元数据；WAL/线程专属连接用于部分存储。
- LanceDB + PyArrow：语义 MemoryRecord、evidence node、episode turn、skill 和 visual 向量表。
- NumPy、tiktoken、Pillow、NetworkX、PyYAML、HTTPX、JWT/bcrypt 等；`local-embed`/`rerank` extra 额外引入 sentence-transformers、PyTorch、Transformers、HuggingFace Hub、safetensors。

### 前端与宿主

- `web-demo/`：React 18、React DOM、TypeScript 5.6、Vite 6、Zustand、D3 hierarchy/force、Ant Design Icons、React Markdown/GFM。
- `openclaw-plugin/`：TypeScript ESM/OpenClaw extension；配置声明在 `openclaw.plugin.json`，无独立构建脚本。
- Hermes/Claude 插件：Python/JSON/YAML/Markdown，以 HTTP/MCP 连接后端；Claude hook 明确以标准库为目标。

### 配置与数据目录

`src/core/config.py` 的默认路径包括：`data/sessions.db`、`data/compact_memory.db`、`data/compact_vector`、`data/skill_store.db`、`data/skill_vector`、`data/visual_memory.db`、`data/visual_vector`、`data/visual_memory`。`.env.example` 同时给出 LLM、embedding、reranker、VLM 和工作记忆变量。

## 8. 测试与验证现状

### 已实际读取

- `tests/test_embedding_dimensions.py`：当前发现的唯一测试文件；包含 5 个 pytest 测试函数，覆盖：LiteLLM embedding dimensions 传递、工厂实际维度探测与缓存、空 LanceDB 表按真实维度重建、写入前维度错误保护、非空索引维度变更拒绝。
- `pyproject.toml`：pytest 配置为 `testpaths=["tests"]`、`asyncio_mode="auto"`，ruff 行宽 100、目标 Python 3.11。

### 本轮验证方式

本轮没有安装依赖、启动服务、运行构建或执行测试；结论来自静态读取和路径/符号核对。没有把 README 示例或已有细探内容当作运行通过证据。

## 9. 未确认项与架构风险

1. **测试覆盖很窄**：当前可见测试只验证 embedding/LanceDB 维度边界；没有发现覆盖 FastAPI 路由、MCP JSON-RPC、完整 LangGraph pipeline、语义摄入/检索、固化水位线、视觉 API、宿主插件生命周期的测试。
2. **文档与实现存在漂移**：README/已有细探描述了 `CompositeRecord`、层级融合等旧模型，但当前 `src/memory/semantic` 主路径未发现 `CompositeRecord` 定义，当前证据组织实现是 `FieldedEvidenceOrganizer + evidence_nodes`。`/memory/graph` 保留 composite 兼容分支，最终前端语义树的长期契约需裁决。
3. **CLI 发布契约未闭合**：README 的 `lycheemem-cli` 在当前 `pyproject.toml` 中没有看到 `[project.scripts]`；`main.py` 仍是明确的源码启动入口。
4. **直接导入依赖未完全声明**：源码直接导入 `dotenv`、`pyarrow`，示例直接导入 `requests`；`pyproject.toml` 未逐项声明 `python-dotenv`、`pyarrow`、`requests`，当前是否由传递依赖/运行环境提供未验证。
5. **视觉代码存在双目录**：根目录 `vision/` 与 `src/memory/visual/` 有相似模型/存储/提取器文件，且根 `vision/README.md` 的描述与 `src` 组装路径并不完全一致；应确认哪个是正式入口，避免后续双轨维护。
6. **配置耦合**：`create_pipeline()` 接收 `settings`，但视觉组件部分又读取 `src.core.config` 的全局 `settings`；测试替换配置或多实例运行时可能出现注入对象与全局对象不一致。
7. **视觉请求可能重复处理**：`chat.py` 的普通图片流程先调用 `_process_images_with_mime()`，随后又把原始图片交给 Pipeline 的视觉节点；存储层有同 session/image hash 去重，但是否会造成重复 VLM 调用、日志或时延，需要运行时验证。
8. **安全默认值需上线前复核**：FastAPI CORS 全开放，源码未见认证中间件；MCP/API 默认无 token 保护，宿主配置中的 token 只是可选传输字段。
9. **后台一致性边界未验证**：固化在 daemon thread/`asyncio.create_task`/线程池中运行；水位线只在固化完成后更新，异常恢复、进程退出、并发同 session 固化和 LanceDB/SQLite 双写一致性没有对应测试证据。
10. **依赖与版本事实未统一**：`pyproject.toml` 项目版本为 `0.1.4`，FastAPI/MCP/plugin/API 文本中多处显示 `0.1.0`；README 新闻和部分示例包含未来/历史混合描述，不能直接作为当前版本契约。
11. **服务生命周期未验证**：`src/mcp.handler` 初始化日志器时可能创建 `appdata/`，`main.py` 启动时会创建 `data/`；本轮未导入模块，因此未验证实际文件副作用和优雅关闭/flush pending visual vectors 行为。
12. **根目录治理文件缺失**：在项目内未发现根级 `AGENTS.md` 或 `CLAUDE.md`；发现的 `claude-plugin/lycheemem/INSTALL_CLAUDE.md` 是安装说明，不视为仓库治理规则。

## 10. 本轮实际读取与修改清单

### 实际读取的主要文件

- `README.md`、`README_zh.md`、`.env.example`、`pyproject.toml`、`main.py`。
- `src/core/config.py`、`factory.py`、`graph.py`、`state.py`。
- `src/agents/base_agent.py`、`wm_manager.py`、`search_coordinator.py`、`reasoning_agent.py`、`consolidator_agent.py`。
- `src/memory/base.py`；`src/memory/working/{session_store.py,sqlite_session_store.py,compressor.py}`；`src/memory/semantic/{base.py,models.py,engine.py,ingestion.py,encoder.py,chunker.py,evidence_graph.py,sqlite_store.py,vector_index.py}`；semantic retrieval 组合入口；`src/memory/procedural/sqlite_skill_store.py`；`src/memory/visual/{models.py,visual_store.py,visual_extractor.py,visual_retriever.py,visual_forgetter.py}`。
- `src/api/server.py`、`dependencies.py`、`models.py`、`routers/{chat.py,memory.py,session.py,pipeline.py,visual.py}`。
- `src/llm/{base.py,litellm_llm.py}`、`src/embedder/{base.py,litellm_embedder.py}`、`src/mcp/{server.py,handler.py,tools_schema.py}`。
- `tests/test_embedding_dimensions.py`、`examples/api_pipeline_demo.py`、`vision/README.md`、`vision/models.py`。
- `web-demo/package.json`；`openclaw-plugin/{package.json,openclaw.plugin.json,index.ts,src/client.py}`；`hermes-plugin/lycheemem/{plugin.yaml,runtime.py,tools.py,client.py}`；`claude-plugin/lycheemem/{README.md,.mcp.json}`。
- 真实目录结构通过只读目录遍历核对；未发现根级 `AGENTS.md`、`CLAUDE.md`、`requirements*.txt`、`setup.py`、`Makefile`、Dockerfile 或已有 `ARCHITECTURE.md`。

### 本轮修改文件

- 新增：`ARCHITECTURE.md`（本文件）。
- 已吸收此前 `细探-LycheeMemory.md` 的源码分析结论；后续只维护本文件，旧细探笔记不再作为独立事实源。
- 未修改任何已有源码、依赖清单、测试、配置、README 或插件文件。

## 11. 第三轮：通用底座映射与裁决

> 本章是第三轮底座输入，不是对 LycheeMemory 的生产改造方案。当前源码仍以 `src.core`、`src.memory`、`src.api` 和插件目录为事实边界；下表中的“归属”是映射到系统工程平台时的唯一 owner 建议。没有把本章建议写回 LycheeMemory 的其他目录，也没有声称平台已经实现这些能力。

### 11.1 四层归属总表

| 通用能力 | 当前源码证据 | 系统工程平台归属 | 第三轮裁决 |
|---|---|---|---|
| 记忆记录、检索计划、搜索结果、来源和时间字段 | `src/memory/semantic/models.py:MemoryRecord/SearchPlan/EvidenceRoute`；`src/memory/visual/models.py:VisualMemoryRecord` | **支持库：公共契约/基础类型/时间与来源** | 吸收数据形状与不可变来源语义；`MemoryRecord` 不应继续让 LLM 直接决定 `record_id`、归一化文本或证据索引键。 |
| 工作/语义/程序/视觉四类记忆的领域流程 | `src/memory/working/`、`semantic/`、`procedural/`、`visual/` | **记忆模块** | 吸收四类记忆的差异化生命周期；禁止把四类数据压成一个万能向量表。 |
| SQLite、FTS5、LanceDB、图片文件的具体读写 | `sqlite_store.py`、`vector_index.py`、`sqlite_skill_store.py`、`visual_store.py` | **支持库：存储/索引/文件资源提供者** | 升级为有事务证据、统一错误、维度契约和释放语义的 provider；模块只能调用公开能力，不能直连数据库或 LanceDB。 |
| `LycheePipeline`、LangGraph 节点、固化水位线、后台任务状态 | `src/core/graph.py`、`src/core/state.py`、`src/core/factory.py` | **运行核心：编排、任务、资源监督、恢复** | 吸收图拓扑和水位线；升级任务幂等、取消、崩溃恢复、并发同 session 锁和停机排空。 |
| LiteLLM、HTTP embedding、SentenceTransformer、VLM、reranker | `src/llm/*`、`src/embedder/*`、`visual_extractor.py`、`reranker.py` | **支持库：模型/外部 provider 适配层** | 一个模型能力一个契约 owner；模型对象、连接、线程、临时文件的持有权不得穿透模块。 |
| HTTP、MCP、Hermes/OpenClaw/Claude hook | `src/api/routers/memory.py`、`src/mcp/handler.py`、插件 `runtime.py/client.py` | **统一网关/项目适配层** | 吸收“HTTP 与 MCP 共享 `run_memory_*` helper”的单入口做法；废弃网关直接访问 `_sqlite` 等内部对象的旁路。 |
| 统计 JSON、trace、日志 | `src/llm/base.py`、`src/embedder/base.py`、`semantic/debug_trace.py` | **运行核心：事件/诊断/证据** | 吸收按来源的 token/embedding 统计；升级为结构化、脱敏、可关联 job/trace 的事件账本，不以统计文件承担业务一致性。 |

### 11.2 多类记忆如何归底座

| 记忆类别 | 领域事实与权威写 owner | 索引/召回 | 模块层职责 | 支持库边界 |
|---|---|---|---|---|
| **Working Memory** | `SessionLog` 的 `turns`、`summaries`、`last_consolidated_turn_index`；生产可选 `SQLiteSessionStore`，开发默认 `InMemorySessionStore` | 当前主要是会话顺序读取和 token 计数；摘要是压缩产物，不是独立语义索引 | `WMManager` 负责追加、70% 异步预压缩、90% 同步压缩和上下文渲染 | 会话存储、token 计量、摘要写入、软删除和水位线应是支持库契约；LLM 摘要是 provider。 |
| **Semantic Memory** | `MemoryRecord` 是原子记录；`record_id=SHA256(semantic_text)`；`memory_records` 是 SQLite 权威行，`evidence_nodes` 是字段索引 | FTS5、`memory_records` 的 semantic/normalized 向量、`evidence_nodes` 的 entity/tag/entity_tag/temporal/event_frame 向量、`episode_turns` 原始 turn 向量 | `CompactSemanticEngine` 编排 chunk→encode→写入和 route-aware 多通道检索 | SQLite/LanceDB、embedding、reranker、日期解析和向量维度检查只能由公开支持能力提供。 |
| **Procedural Memory** | `skills` SQLite 行（intent、Markdown、conditions、metadata、success_count、last_used） | intent 向量 ANN；补充 `skills_fts`；HyDE 查询向量 | `SearchCoordinator._search_skills` 按 `answer/action/mixed` 决定是否召回；`ConsolidatorAgent` 抽取并按 0.85 相似度 upsert | 技能契约、向量写入、usage 事件和去重应由程序记忆模块调用支持库；不能让 LLM 自行写库。 |
| **Visual Memory** | `VisualMemoryRecord`；SQLite `visual_memories` 记录、LanceDB `visual_records`、`image_storage_path` 原始文件 | caption 文本向量、可选 CLIP `visual_vector`，文本/视觉加权融合；无 provider 时回退 SQLite `LIKE` | `VisualExtractor` 做 hash/压缩/VLM JSON；`VisualStore` 负责文件和元数据；`VisualForgetter` 做衰减、软过期、TTL | 图片字节、临时文件、VLM、多模态 embedding 和向量缓冲必须由支持库声明资源责任；软过期与物理文件删除不能混成一个动作。 |

**共性裁决**：四类记忆共享 `session_id`、时间、来源、状态、trace/job 关联和统一结果契约，但不共享一张不带类型的写表。`fact/preference/event/constraint/procedure/failure_pattern/tool_affordance` 是语义记忆内部 `memory_type`，不是平台四类记忆的替代物；`raw_turn`、`evidence_node`、技能和视觉记录也必须保留自己的来源类型。

### 11.3 唯一写入链路（当前事实 → 底座单链路）

#### A. 普通对话/宿主镜像的唯一事实写入

```text
HTTP /chat、/memory/reason，或 MCP/plugin append_turn
  → 统一 API helper / 客户端边界校验
  → WMManager 或 run_memory_append_turn
  → session_store.append_turn(session_id, role, content, speaker, created_at)
  → turns 权威日志（SQLiteSessionStore）/内存日志（开发后端）
```

`LycheePipeline._wm_manager_node` 追加用户轮次，`_reason_node` 追加 assistant 轮次；外部宿主只应镜像自然语言 user/assistant turn。MCP handler 明确禁止把原始工具参数、工具输出和编排 trace 当普通对话写入。当前 `run_memory_append_turn` 是 HTTP/MCP 共用的事实写入 helper；插件 `post_llm_call` 还用 `session_id + user + assistant` 的 SHA1 指纹避免重复镜像。

#### B. 语义长期固化的唯一顺序

```text
session_store 水位线
  → ConsolidatorAgent.run
  → CompactSemanticEngine.ingest_conversation
  → LanceVectorIndex.upsert_turns_batch       [episode_turns，失败当前实现返回0]
  → OnlineSemanticChunker.add_turns            [每 session 内存 pending，flush 才收尾]
  → CompactSemanticEncoder                     [一次 LLM；类型/消歧/时间/证据 turn]
  → Python 归一化 MemoryRecord                 [校正类型、normalized_text、绝对 turn、SHA256 id]
  → SQLiteSemanticStore.upsert_record          [memory_records + FTS5]
  → LanceVectorIndex.upsert_batch               [semantic/normalized 向量]
  → FieldedEvidenceOrganizer                   [entity/tag/time/event_frame]
  → SQLiteSemanticStore.upsert_evidence_nodes  [evidence_nodes + FTS5]
  → LanceVectorIndex.upsert_evidence_nodes_batch
  → 成功返回后 session_store.set_last_consolidated_turn_index
```

当前实现按原子 record 精确 ID 去重，不再以相近句向量直接判定事实重复；`upsert_record` 是 SQLite 行和 FTS5 的幂等 owner。**但这不是跨存储原子事务**：原始 turn 向量、SQLite record、record 向量、evidence SQLite、evidence 向量可能在不同步骤部分成功，水位线只在整体函数返回后更新。因此底座映射必须升级为“写意图/事务 id → 权威记录 → 索引 outbox/重放 → 对账”，禁止模块自行补偿第二条写链。

#### C. 技能与视觉的分支写入

```text
语义固化成功
  → ConsolidatorAgent skill_extraction LLM
  → intent embedding
  → SQLiteSkillStore.add (skills + skills_fts)
  → LanceDB skills upsert
```

技能 SQLite 成功而 LanceDB 失败时当前 `_upsert_vector` 静默吞异常，形成双写漂移；平台应返回结构化“主存成功/索引待修复”，由运行核心重放，不能把失败伪装成 `skills_added` 成功。

```text
Base64
  → VisualExtractor.extract_from_base64
  → SHA256(image bytes) + 有界结果/压缩缓存 + VLM(30s wait_for)
  → VisualStore.save_image_file(session/hash.ext)
  → VisualMemoryRecord
  → caption embedding / optional visual embedding
  → SQLite visual_memories
  → LanceDB vector buffer（10 条或退出时 flush_pending_vectors）
```

视觉写入是独立资源事务：图片文件先于 SQLite 行，向量又可能延迟；重复 hash+session 返回空 id；软过期只更新 SQLite `expired=1`，物理删除才由 `delete_record` 删除数据库行和图片文件，当前未见同步删除 LanceDB 行的完整链路。

### 11.4 唯一检索链路

```text
HTTP /memory/search 或 /memory/smart-search
MCP tools/call
Hermes/OpenClaw/Claude smart_search
  → 统一 run_memory_search / run_memory_smart_search
  → SearchCoordinator.run
  → recent_context + ActionState
  → 可选 query_analysis_and_hyde LLM
  → retrieval_planning LLM → SearchPlan/EvidenceRoute
  → CompactSemanticEngine.search
  → route query variants 去重
  → 本次 search 内 query embedding cache（并发同 query 合并）
  → temporal evidence 精确范围召回
  → evidence_nodes ANN → SQLite 批量展开 MemoryRecord
  → MemoryRecord normalized ANN
  → episode_turns 原始 turn ANN
  → source window / assistant answer window
  → 可选 reranker（失败则关闭并回 baseline）
  → route RRF 融合 + coverage/MMR 选择 + episode 预算
  → context + provenance + retrieval_plan
  → SearchCoordinator 按 mode 检索技能（HyDE → skills ANN/SQLite）
  → background_context
  → 可选 ReasoningAgent 生成答案
```

`src/api/routers/memory.py` 的 `run_memory_*` 是当前 API/MCP 共享业务入口，`src/mcp/handler.py` 只做 JSON-RPC、Pydantic 校验和错误包装；这是应吸收的单链路。反例是 `GET /memory/graph/search` 直接调用 `sc.semantic_engine._sqlite.fulltext_search`，它绕过 SearchPlan、统一 provenance 和网关契约；第三轮裁决为**废弃该旁路作为正式能力**，仅保留调试接口或改为调用公开检索能力。

### 11.5 时间、来源和可追溯性

| 信息 | 当前写入点 | 当前检索/展示用途 | 底座要求 |
|---|---|---|---|
| `session_id` | turns、MemoryRecord.source_session、EvidenceNode.session_ids、VisualMemoryRecord | 会话上下文、event_frame、视觉按会话检索 | 必须是租户/项目/所有者作用域的一部分，不能只当字符串过滤；插件已有前缀和长度归一化可吸收，但核心服务尚无统一作用域授权。 |
| turn 位置 | `evidence_turn_range`、episode `turn_index`、event frame span | 原始 turn 回溯、source window、图展示 | 由 Python 生成和校验，LLM 只能提出局部证据索引；写入前做范围、删除状态和 session 归属检查。 |
| 对话时间 | turn `created_at`、`reference_timestamp`/`session_date`、MemoryRecord.created_at、Visual.timestamp | temporal 节点 day/month、`since/until` 精确范围、展示 provenance | 业务发生时间与写入时间分开；`time_utils` 只做格式归一化，不应覆盖原始值。 |
| 语义时间 | `MemoryRecord.temporal` 的 `t_ref/t_valid_from/t_valid_to`，EvidenceNode `start/end` | 先结构化 temporal route，再语义召回 | 归一化日期可检索，但必须保留原始 LLM 字段和解析失败原因，避免错误日期静默变事实。 |
| 角色/参与者 | `source_role`、turn `role/speaker`；索引内容加 speaker 前缀 | raw turn 和记录来源解释 | 来源角色必须来自受控集合；speaker 需要脱敏/权限边界，不能仅拼接进向量文本后丢元数据。 |
| provenance/trace | `SemanticSearchResult.provenance`、`_trace_id`、LLM/embedding source 标签 | API background_context、debug trace、成本统计 | 统一 `trace_id/job_id/record_id/source_id`；统计失败不能影响业务，证据账本不能被普通日志替代。 |

### 11.6 索引、缓存和模型资源的底座归属

1. **索引不是权威数据**：SQLite `memory_records`、`skills`、`visual_memories` 和 session turns 是可读回的结构化主数据；FTS5、LanceDB、visual vector、episode turn 是可重建索引。任何索引缺失都应进入 `INDEX_PENDING/INDEX_REBUILD`，不能把检索空结果解释成“没有记忆”。
2. **向量维度是启动契约**：`factory._resolve_embedding_dim` 会探测真实维度；`LanceVectorIndex` 对空表可重建，对非空维度不一致直接拒绝。平台应把“模型身份、版本、维度、归一化方式”写进索引元数据；切换模型必须走新索引/迁移，不允许覆盖旧向量。
3. **查询缓存**：`CompactSemanticEngine` 有最多 4096 项进程内 LRU 查询向量缓存，`_query_embedding_inflight` 用 Event 合并同 key 并发，等待上限 30 秒；这是运行期优化，不是持久事实。超时后当前调用可能拿不到向量并返回部分结果，平台应记录 `CACHE_WAIT_TIMEOUT`，而不是无限等待。
4. **记录预取缓存**：每次 search 使用一次性 `record_cache`，`get_records_by_ids` 批量取回，生命周期仅覆盖一次检索；它归检索模块内部，不应升级为跨请求无效缓存。
5. **视觉/VLM 缓存**：`VisualExtractor` 按 image hash 保存有界结果和压缩 Base64 缓存；VLM 失败的 fallback 结果也会进入结果缓存，后续同 hash 可能继续复用降级描述。底座应区分“成功缓存”和“失败/降级缓存”，并带模型版本、提示版本和 TTL。
6. **模型资源**：`LiteLLMLLM`/`LiteLLMEmbedder` 是远程会话 provider；`HTTPEmbeddingServerEmbedder` 每次调用新建 `httpx.Client`；`SentenceTransformerEmbedder` 懒加载本地模型；多模态 embedder 延迟加载；reranker 可为本地模型或 HTTP。它们属于支持库 provider，模型句柄/HTTP client/GPU/MPS 内存的 owner 是 provider manager，不得由 gateway 或 MemoryRecord 持有。
7. **成本/统计**：`BaseLLM`、`BaseEmbedder` 通过 `ContextVar` 标记 `compact_encoding`、`semantic_search_query`、`skill_ingest` 等来源，并以临时文件 rename 写 JSON 统计。可吸收“调用来源”字段，升级统计写入不阻塞主链且具进程/任务隔离；当前统计文件不是可靠审计账本。

### 11.7 资源生命周期与失败矩阵

| 资源/阶段 | 正常完成 | 业务失败 | 超时/主动取消 | 宿主崩溃/重启 | 当前证据与缺口 |
|---|---|---|---|---|---|
| Session turns/摘要 | append/summary commit；成功固化后水位线单调更新 | LLM/编码失败时异常上抛，水位线不前进，理论上可重试 | HTTP 客户端取消没有统一 job cancel；后台线程继续运行 | 内存 store 全丢；SQLite turns 可恢复，未完成固化靠水位线重跑 | 有 SQLite 持久化与单调水位线；无同 session 并发锁/恢复测试。 |
| WM 压缩 Future/线程池 | Future 完成后摘要写入、旧 turn 软删除；同步阈值可复用已完成 Future | Future 异常回退同步压缩 | 同步阈值对未完成 Future 调 `cancel()`；运行中任务不可保证停止 | `ThreadPoolExecutor` 是对象资源，未见统一 `shutdown`；daemon/线程退出语义未验 | 70/90 双阈值真实代码；缺取消、停机排空和泄漏验证。 |
| LLM/VLM/Embedder HTTP | provider 返回后统计写入；流式结束正常 | LiteLLM 非重试 HTTP 400/401/403/404/422 直接失败；VLM JSON 失败 fallback | LLM/Embedder 默认 600s，VLM `wait_for(30)`；同步 provider 无统一 cancel；stream 首 token 后失败不重试 | 远程调用无持久句柄；本地模型进程崩溃语义未覆盖 | 有重试/超时代码，默认重试次数和指数退避需治理；未实测外部服务。 |
| Semantic SQLite/FTS | 行 upsert、FTS 同事务 commit | SQLite 异常上抛；FTS 建表已存在错误被吞 | 未见查询级 cancel；连接 `busy_timeout=5000` | 线程本地连接可在新线程重建；无统一 close/检查 WAL 残留 | 线程专属连接、写锁和 WAL 有源码证据；无损坏恢复/双写对账。 |
| LanceDB/ANN/cache | upsert/ANN 返回；维度校验通过 | 多数 ANN 异常返回空；维度错误启动抛 RuntimeError | query embedding 等待 30s；ANN 无明确超时/取消 | 索引可重建但未见自动对账；exact cache 进程内消失 | 空结果和故障语义混淆，需结构化 provider 错误。 |
| Skill 双写 | SQLite+FTS 后 Lance vector upsert | Lance `_upsert_vector` 异常静默，主表仍返回成功 | 无单独取消 | SQLite 可恢复，向量漂移需重建；无启动对账 | 这是 P0 双写一致性缺口。 |
| Visual 图片/向量 | 临时图片写入后 SQLite 记录，向量达到10条或显式 flush | VLM 异常可能不写记录；视觉向量异常只记录日志 | VLM 30s fallback；临时文件有 finally 删除 | 图片文件可能先于 DB 残留；vector buffer 未 flush 可能丢索引 | `NamedTemporaryFile` 视觉 embedding 有 finally；退出 flush 仅有公开方法，未接入统一 shutdown。 |
| Background consolidate job | `done` 状态、结果和水位线写回 | `_safe_consolidate` 捕获异常并写 `error`，主回复不阻塞 | 无 job cancel API；HTTP background thread 不返回 job id | 进程被杀时状态只在内存，水位线未更新可重跑，但部分双写需对账 | 当前状态 `pending/done/skipped`，异常仍 status=`done`；应改为可区分 failed/cancelled/retry。 |
| MCP session/SSE | initialize 建 session，后续复用 `Mcp-Session-Id` | 参数错误 -32602，未知工具 -32602，业务异常 -32603 | SSE 客户端断开无显式 session 清理/超时；registry 无 TTL | 进程重启 session registry 全丢，需重新 initialize | 网关协议清晰；无认证、过期和并发 session 治理。 |

### 11.8 L0-L4 证据等级

本项目第三轮统一采用以下证据分级，避免“源码有实现”被误报为“生产已验证”：

| 等级 | 含义 | LycheeMemory 当前可列事实 |
|---|---|---|
| **L0** | 声明/README/兼容字段/注释线索，未证明当前执行路径 | README 的 `CompositeRecord`/层级树旧描述、`lycheemem-cli` 文案、根 `vision/` README。 |
| **L1** | 当前源码静态路径、函数、数据表和错误分支已核对 | 四类记忆、唯一固化顺序、SearchCoordinator 路由、MCP 共享 helper、资源创建/释放代码。 |
| **L2** | 本地确定性测试或静态门禁真实通过 | 当前 `tests/test_embedding_dimensions.py` 的5项测试范围；它只覆盖 embedding 维度/LanceDB，不覆盖完整记忆链。 |
| **L3** | 真实 provider、数据库、HTTP/MCP、模型或跨进程链路已执行并读回 | 本轮没有安装依赖、启动服务、外部 API、真实 VLM/embedding、HTTP/MCP 或完整固化/检索执行，因此本项目这些项均为未证实。 |
| **L4** | 故障注入、超时/取消、崩溃重启、对账、资源残留和并发边界已真实验收 | 当前没有 L4 证据；尤其缺少双写部分失败、后台 job 崩溃、MCP session 重启、视觉文件/向量残留和同 session 并发固化验证。 |

**本轮结论**：架构映射最高只能把源码结论标为 L1，把已有维度测试标为 L2；不得把 README、日志或本轮静态读取升级为 L3/L4。

### 11.9 复用/升级/新建/废弃裁决

| 裁决 | 内容 | 原因与落点 |
|---|---|---|
| **吸收** | 四类记忆分层；`MemoryRecord` 的类型/时间/来源/证据 turn；按水位线增量固化；API/MCP 共用 helper；查询向量并发合并；索引维度启动校验。 | 这些是可复用边界模式，分别进入公共契约、记忆模块、运行核心和网关契约。 |
| **升级** | SQLite/LanceDB/文件三层双写；技能向量静默失败；视觉向量缓冲；LLM/Embedding 重试；后台任务状态；MCP session；统计 JSON。 | 当前存在部分成功、异常吞掉、缺取消、缺恢复或缺对账；升级为统一 provider 结果、事务证据、outbox、job 状态和资源监督。 |
| **新建** | 记忆写入事务/索引重放器、记忆检索公开能力、统一 provenance/source contract、consolidation job supervisor、视觉资源清理/对账能力。 | 当前没有一个 owner 同时治理跨 SQLite/LanceDB/文件的原子意图、取消、崩溃恢复和残留验证；新建前必须走平台能力需求登记和复用裁决。 |
| **废弃/隔离** | 旧 `composites` 作为当前主模型；网关 `GET /memory/graph/search` 直达 `_sqlite`；根 `vision/` 与 `src/memory/visual/` 的双公共入口；各插件自行维护业务 fallback。 | 与当前 `MemoryRecord + evidence_nodes + episode_turns` 主路径或单 owner 原则冲突；旧字段可读回滚，不能再作为新写入路径。 |
| **待核** | `apply_feedback_from_user_turn`/usage outcome、reranker v0、VisualForgetter TTL 真实接入、SQLite backend 的生产默认、插件 token/auth。 | 源码有接口或文案，但缺完整执行和故障证据，暂不映射成生产底座能力。 |

### 11.10 底座装配与验收契约（未启动实现）

若未来把 LycheeMemory 能力接入系统工程平台，装配顺序必须是：

1. **需求/契约冻结**：登记四类记忆的读写能力、作用域、幂等键、时间/来源字段、返回错误、可重试、超时、取消和资源 owner；明确 `record_id`、`episode_id`、`skill_id`、`visual_record_id` 的唯一性。
2. **能力搜索与复用裁决**：先搜索已有支持库的 SQLite、文件、向量、模型、任务、时间、网关能力；不得直接复制 `src/memory/*` 为第二套底座。
3. **写 owner 装配**：session/record/skill/visual 主数据各一个 owner；索引是可重建副本，采用事务证据或 outbox；每个能力只有一个公开 id 和一条注册调用链。
4. **读取 owner 装配**：统一检索能力接收 query、scope、time range、memory types、top-k、budget，返回 records/context/provenance/diagnostics；调试 graph 只能消费公开读能力。
5. **资源监督**：模型句柄、HTTP client、SQLite 连接、LanceDB 句柄、线程池、临时文件、图片文件、后台任务和 MCP session 都登记创建者、持有者、转移、正常释放、失败释放、超时/取消和崩溃清理。
6. **验收分层**：L2 先做确定性契约/幂等/维度测试；L3 做隔离 SQLite/LanceDB、真实 HTTP/MCP 和模型 provider；L4 做部分双写、超时、取消、SIGKILL/重启、同 session 并发、对账和残留检查。缺任一级证据只能保持待核。

本项目当前没有因此启动平台实现；正式改造必须另有需求登记、能力占用租约、验收契约和独立工作包。

## 12. 第三轮证据与未验证边界

- **代码图**：按任务要求先核对上下文后以目标绝对路径调用 `mcp__codegraph__codegraph_explore`；目标项目未发现 `.codegraph/`，返回“未索引”，后续未重复调用，改用本地只读文件核对。
- **旧细探**：在目标根及 `02_长期记忆与记忆操作系统` 分类目录未找到 `细探-LycheeMemory.md`；现有 `ARCHITECTURE.md` 第3、10节已记录此前细探结论已吸收，本轮未删除任何旧材料。
- **源码事实**：第三轮追加内容主要由 `src/memory/{working,semantic,procedural,visual}`、`src/agents/{wm_manager,search_coordinator,consolidator_agent}`、`src/core/{factory,graph}`、`src/{llm,embedder,api,mcp}` 和 Hermes runtime/client 交叉核对。
- **验证等级**：本轮仍是静态研究；未安装依赖、未启动服务、未运行测试、未调用真实模型/数据库/HTTP/MCP，因此没有新增 L2-L4 通过证据。原有唯一测试范围和风险见第8、9节。
- **修改边界**：本轮只追加本文件第11、12节；没有修改 LycheeMemory 源码、依赖、配置、测试、README、插件或 Git，也没有删除旧细探。
