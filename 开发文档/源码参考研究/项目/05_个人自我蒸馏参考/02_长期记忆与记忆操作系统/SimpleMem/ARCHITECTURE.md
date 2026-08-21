# SimpleMem 架构建档

> 本文是基于当前工作树源码、README、依赖清单、测试与既有 `细探-SimpleMem.md` 的静态架构地图。它记录“代码中已看到的事实”，不把 README 宣称或论文结果当作运行时证明。
>
> 目标仓库：`~/Documents/Agent/github 源码参考/05_个人自我蒸馏参考/02_长期记忆与记忆操作系统/SimpleMem`
>
> 代码版本边界：`db80b6a`（`main`，与 `origin/main` 对齐）。

## 1. 项目定位

SimpleMem 是面向 LLM Agent 的长期记忆栈：把对话或多模态输入压缩成可检索的原子记忆，再通过多路检索、上下文装配和 LLM 生成回答。当前仓库不是单一运行时，而是一个统一 Python 包加多个集成/参考实现：

- **统一包入口**：`simplemem/`，导出文本 SimpleMem、多模态 Omni、模式列表、EvolveMem 优化配置。
- **文本核心**：`simplemem/text/` + `simplemem/core/`，对话窗口抽取 `MemoryEntry`，LanceDB 存储，语义/关键词/结构化混合检索。
- **多模态核心**：`simplemem/multimodal/`，文本、图像、音频、视频统一成 MAU，热元数据与冷原始数据分离，支持事件层级、金字塔检索、知识图谱。
- **自演化检索**：`simplemem/evolver/`，对已有记忆和 QA 开发集运行 Evaluate → Diagnose → Propose/Adjust → Guard/Repeat。
- **HTTP MCP 服务**：`MCP/`，生产化、多租户、JWT/AES、LanceDB、Streamable HTTP MCP 2025-03-26；`simplemem/integrations/server/` 是同构的包内集成副本。
- **跨会话记忆**：`cross/`，通过组合而不是修改 SimpleMem，增加 SQLite 会话时间线、事件/观察/摘要、上下文注入、生命周期和多租户隔离。
- **Omni 独立参考/stdio MCP**：`OmniSimpleMem/`，与统一包内多模态实现平行；提供独立 REST/stdio MCP、命名空间和媒体解析。
- **技能/CLI/参考副本**：`SKILL/`、`simplemem/integrations/simplemem-skill/`、`MCP/reference/` 等用于 Agent 接入或兼容旧入口。

根 README 将核心原则概括为：语义结构化压缩、在线语义综合、意图感知检索规划；多模态则增加选择性摄入、渐进式检索和知识图谱增强；EvolveMem 让检索基础设施进入自演化闭环。

## 2. 总体文本流程图

### 2.1 统一包路由

```text
调用者
  │
  ├─ from simplemem import SimpleMem/create/list_modes/optimize
  │
  ▼
simplemem/__init__.py
  │  SimpleMem 是 router.AutoMemory 的别名
  ▼
simplemem/router.py
  │
  ├─ create(mode="text") ──lazy import──> simplemem.text.system.SimpleMemSystem
  │                                      │
  │                                      └─> simplemem/core/*
  │
  ├─ create(mode="omni") ──lazy import──> simplemem.multimodal.orchestrator.OmniMemoryOrchestrator
  │                                      │
  │                                      └─> simplemem/multimodal/*
  │
  └─ create(mode="auto") ──> AutoMemory（首次调用锁定 text 或 omni，实例生命周期内不可切换）
```

### 2.2 文本写入与问答路径

```text
speaker + content + timestamp
  │
  ▼
SimpleMemSystem.add_dialogue/add_dialogues
  │  Dialogue(Pydantic)
  ▼
MemoryBuilder
  │  buffer → sliding window(WINDOW_SIZE=40, overlap=2)
  │  大批量可 ThreadPoolExecutor 并行
  │  LLM 抽取：无代词、绝对时间、关键词/人名/实体/地点/主题
  ▼
MemoryEntry(Pydantic)
  │  lossless_restatement + 多视图元数据 + UUID
  ▼
EmbeddingModel.encode_documents
  │
  ▼
VectorStore → VectorStoreBackend → LanceDBVectorStoreBackend
  │  LanceDB 表：memory_entries；dense vector + metadata
  └─ 追加 FTS/Tantivy 索引

question
  │
  ▼
HybridRetriever
  │  LLM 分析意图 → 目标查询
  │  semantic dense search
  │  keyword FTS/Tantivy search
  │  structured persons/location/entities/time filter
  │  merge + deduplicate；可 reflection 追加检索
  ▼
AnswerGenerator
  │  contexts 格式化 → LLM JSON answer
  └─ 无上下文时返回 "No relevant information found"
```

### 2.3 多模态写入与渐进检索路径

```text
text / image / audio / video
  │
  ▼
OmniMemoryOrchestrator
  │
  ├─ TextProcessor ──长度/Jaccard 冗余过滤──┐
  ├─ ImageProcessor ──CLIP 视觉熵触发──┤
  ├─ AudioProcessor ──VAD/能量/异常触发──┤
  └─ VideoProcessor ──抽帧 + 音轨处理───┘
                                      │
                                      ▼
                            ProcessingResult → MAU
                              <summary, embedding, metadata,
                               raw_pointer, details, links, status>
                                      │
                ┌─────────────────────┼──────────────────────┐
                ▼                     ▼                      ▼
        MAUStore(JSONL)       HybridVectorStore(FAISS)   EventStore(JSON)
        热元数据/索引           dense + visual vectors     EventNode 层级
                │                     │                      │
                └──────────────┬──────┴──────────────┬───────┘
                               ▼                     ▼
                       KnowledgeGraph          cold storage
                       entity/relation          disk/S3 原始媒体

query
  │
  ▼
QueryProcessor → PyramidRetriever.retrieve_preview
  │  向量召回 + modality/time/tag 过滤；仅返回 summary/metadata
  ├─ 可选 BM25、图检索、路由/自演化增强
  └─ ExpansionRequest → details/evidence → 按需读取 raw_pointer
  │
  ▼
answer(question) → LLM 基于选定上下文生成回答
```

### 2.4 跨会话闭环

```text
Agent framework / Hook / HTTP / MCP
  │
  ▼
CrossMemOrchestrator
  │
  ├─ start_session → SQLite SessionRecord + ContextInjector
  │                 └─ 旧 summaries/observations/vector hits → ContextBundle → prompt
  ├─ record_message / record_tool_use / file-change
  │                 └─ EventCollector → RedactionFilter → SQLite SessionEvent
  ├─ stop_session / finalize
  │                 └─ ObservationExtractor + summary + 可选 SimpleMem 三阶段管线
  │                    → CrossObservation / SessionSummary / CrossMemoryEntry
  │                    → SQLite + CrossSessionVectorStore(LanceDB)
  └─ end_session → completed / 资源收尾
```

## 3. 分层与职责

| 层 | 统一包实现 | 主要职责 | 关键产物/依赖 |
|---|---|---|---|
| 入口/适配层 | `simplemem/__init__.py`、`router.py`、`simplemem_router.py`、`cross/api_*`、`MCP/server/http_server.py`、`OmniSimpleMem/omni_mcp/*` | 稳定 Python、REST、MCP、CLI、Hook 接口；延迟加载后端 | `SimpleMem`、`create`、JSON-RPC、FastAPI |
| 编排层 | `simplemem/text/system.py`、`multimodal/orchestrator.py`、`evolver/manager.py`、`cross/orchestrator.py` | 组装组件、维护会话/资源、暴露领域操作 | `SimpleMemSystem`、`OmniMemoryOrchestrator`、`CrossMemOrchestrator` |
| 处理/压缩层 | `core/memory_builder.py`；`multimodal/processors/*`；`evolver/extractor.py` | 窗口化、去冗余、熵触发、LLM 抽取、摘要、实体提取 | `MemoryEntry`、`ProcessingResult`、`MAU`、`MemoryUnit` |
| 查询/检索层 | `core/hybrid_retriever.py`；`multimodal/retrieval/*`、`knowledge/*`；`evolver/multi_retriever.py`、`retriever.py`；`cross/context_injector.py` | dense/sparse/metadata 检索、规划、反思、金字塔展开、KG 多跳、token budget | `MemoryEntry` 列表、`RetrievalResult`、`ContextBundle` |
| 生成/演化层 | `core/answer_generator.py`；Omni orchestrator.answer；`evolver/evolution.py`、`diagnosis.py`、`policy*` | 基于上下文回答；离线评估、诊断、配置候选、回退/收敛 | answer JSON、`Config`、`EvolutionResult` |
| 契约/模型层 | Pydantic、dataclass、Enum | 定义输入、记忆、检索、事件、用户/认证数据 | `Dialogue`、`MemoryEntry`、`MAU`、`EventNode`、`MemoryUnit` |
| 存储层 | LanceDB/Tantivy；MAU JSONL/FAISS；Event/Knowledge JSON；Cross SQLite + LanceDB；MCP users SQLite + per-user LanceDB | 持久化、索引、租户/命名空间隔离、冷热分层、血缘指针 | vector table、JSONL、SQLite tables、raw files |
| 外部模型层 | `LLMClient`/OpenAI-compatible；SentenceTransformer/Qwen embedding；CLIP；VAD/音频库 | 抽取、规划、回答、摘要/字幕、dense embedding、视觉/音频触发 | 远程 LLM 响应、向量、caption/transcript |

**边界事实：** `simplemem/integrations/simplemem-skill/src/`、`MCP/reference/` 与根核心存在大量同构代码；它们不是自动共享同一实例或同一数据目录，实际选用入口需由调用命令和配置决定。

## 4. 核心数据模型

### 4.1 文本 `MemoryEntry`

定义：`simplemem/core/models/memory_entry.py:13-68`。

- `entry_id`：UUID 字符串。
- `lossless_restatement`：自包含事实，设计要求解决指代、使用绝对时间。
- `keywords`：词法检索字段。
- `timestamp`、`location`、`persons`、`entities`、`topic`：结构化筛选字段。
- `Dialogue`（同文件 `:70-81`）：`dialogue_id`、`speaker`、`content`、可选 ISO 时间，是写入侧原始输入。
- 该模型是 Pydantic，但当前配置使用旧式 `class Config`；未看到面向所有字段的严格 schema/业务校验。

LanceDB 默认表 schema：`simplemem/core/database/vector_store_backend.py:124-139`。每条记录包含上述元数据和固定维度 `vector`；dense 距离升序、关键词分数降序（同文件 `:96-97`、`:188-221`）。`VectorStore` 在模型与后端之间负责 embedding 和反序列化（`vector_store.py:55-178`）。

### 4.2 多模态 `MAU` 与 `EventNode`

定义：`simplemem/multimodal/core/mau.py:17-180`、`event.py:16-245`。

- `ModalityType`：text / visual / audio / video / multimodal。
- `MAU`：ID、时间、模态、摘要、向量、`raw_pointer`、可延迟加载的 `details`、`MAUMetadata`、`MAULinks`、生命周期状态 `ACTIVE/ARCHIVED/PINNED` 和 `HOT/COLD` 存储层。
- `MAUMetadata`：session/source/tags/quality/duration/frame/speaker，以及 persons/entities/keywords/location/topic。
- `MAULinks`：event、前后 MAU、相关 MAU。
- `EventNode`：时间边界、SUMMARY/DETAILS/EVIDENCE 层级、摘要/描述、MAU 子节点、父子事件、session/tags/模态统计；`EventHierarchy` 管理根、子节点和祖先。
- `MAUStore` 按日期 JSONL 存轻量对象并维护 ID/时间/模态/事件索引；原始媒体由 `ColdStorageManager` 另存，支持 disk/S3 路径。
- `KnowledgeGraph` 的 `Entity` / `Relation` 带 `source_mau_ids` provenance；当前图实现主要是内存索引并可序列化到本地路径。

### 4.3 EvolveMem `MemoryUnit`

定义：`simplemem/evolver/models.py:12-69`。

`MemoryUnit` 携带 `memory_id`、`scope_id`、`MemoryType`（episodic/semantic/preference/project_state/working_summary/procedural_observation）、内容/摘要、来源 session/turn 范围、entities/topics、importance/confidence/access/reinforcement、ACTIVE/SUPERSEDED/ARCHIVED、替代关系、embedding、时间、TTL、tags。它由 `MemoryStore`（SQLite + FTS5，`evolver/store.py`）管理，和文本 `MemoryEntry` 是两套模型。

### 4.4 跨会话模型

定义：`cross/types.py:28-226`。

- `SessionRecord`：tenant、外部 content session、内部 memory session、project、prompt、生命周期时间和状态。
- `SessionEvent`：message/tool_use/file_change/note/system、时间、payload、redaction level。
- `CrossObservation`：从事件提取的 decision/bugfix/feature/refactor/discovery/change。
- `SessionSummary`：request/investigated/learned/completed/next_steps。
- `CrossMemoryEntry`：继承文本 `MemoryEntry`，增加 tenant、session、source、source_id、importance、validity、supersession。
- `ContextBundle`：summaries + timeline observations + memory entries，通过 token 估算渲染为注入文本。

### 4.5 MCP 服务数据模型

`MCP/server/auth/models.py:11-137` 定义 `User`、`TokenPayload`、服务侧 `MemoryEntry`、`Dialogue`；`UserStore` 将用户元数据写入 SQLite users 表（`MCP/server/database/user_store.py:23-39`），每个用户生成独立 `mem_<uuid>` LanceDB 表。服务 schema 另见 `MCP/server/database/vector_store.py:16-29`，默认 embedding dimension 为 2560，但根 Docker/env/配置可覆盖。

## 5. 关键路径

### 5.1 文本写入

1. `SimpleMem()` 创建 `AutoMemory`，不立即导入重依赖；首次 `add_dialogue` 锁定 text。
2. `SimpleMemSystem.__init__` 创建 LLM client、embedding、vector store、builder、retriever、answer generator（`simplemem/text/system.py:17-109`）。
3. `add_dialogue` 创建 `Dialogue` 并进入 `MemoryBuilder` buffer（`:112-128`）。达到窗口或 `finalize()` 时调用 LLM 抽取（`memory_builder.py:132-227`）。
4. 解析 JSON 为 `MemoryEntry`（`:308-336`），批量生成 embedding，封装 `VectorStoreRecord` 写入 LanceDB（`vector_store.py:55-80`）。
5. 大批量写入可将窗口交给线程池；源码中的 worker 仍共享前一窗口上下文，失败时有顺序回退路径（`memory_builder.py:85-130`、`:338-433`）。

### 5.2 文本查询

1. `ask()` 调 `HybridRetriever.retrieve()`，规划打开时先由 LLM 分析信息需求并生成目标查询（`hybrid_retriever.py:58-127`）。
2. 对每个查询走 semantic dense；再按 LLM 解析出的 keywords/persons/time/location/entities 走 keyword 与 structured 三路（`:176-290`）。
3. 合并按 `entry_id` 去重；可执行完整性检查、缺口查询和最多 `max_reflection_rounds` 轮反思。
4. `AnswerGenerator` 将上下文和问题交给 LLM，解析 `answer` 字段；无上下文返回固定无结果文本（`answer_generator.py:22-83`）。

### 5.3 多模态摄入/查询

1. `OmniMemoryOrchestrator.__init__` 创建存储、四类 processor、检索/查询/展开、事件、KG、参数化记忆和可选 evolution/router（`multimodal/orchestrator.py:74-202`）。
2. processor 负责触发过滤、摘要/caption/transcript、embedding、raw 冷存储和 MAU 创建；成功 MAU 由 orchestrator `_store_mau` 写入 MAU、向量、事件/KG 等关联路径。
3. `query` 默认 preview；`PyramidRetriever.retrieve_preview` 先向量召回、应用 modality/time/tag 过滤、只返回摘要/元数据。`expand` 再按请求等级加载 details/evidence/raw。
4. `answer`、事件 API、KG/图检索和 self-evolution 是上层可选增强，不是 text backend 的同一数据模型。

### 5.4 自演化优化

- 简化公共 API：`simplemem.optimize(mem, dev_questions)` → `evolver.optimize.run_optimization`；它要求 text backend 已初始化且能暴露 `llm_client`、`embedding_model`、`get_all_memories`（`optimize.py:44-67`、`:97-110`）。它把 `MemoryEntry` 映射为 EvolveMem 字典，使用 `adapter=None` 的 degraded/global 配置路径。
- 完整 EvolveMem：`EvolutionEngine.evolve` 反复执行 Extract → Index → Retrieve → Answer → Evaluate → Diagnose → Adjust，`EvolutionResult` 记录每轮 F1、配置、诊断、最佳轮次（`evolution.py:1-17`、`:188-256`）。候选字段包括各视图 top-k、fusion、权重、上下文预算、query decomposition、entity swap、reflection、answer verification 和 per-category override。
- 保护语义：README 描述回退/探索/收敛；代码中的 `EvolutionConfig` 有 elitist、acceptance threshold、max changes/no-accept 等参数（`evolution.py:188-214`）。实际策略效果未在本次运行验证。

### 5.5 跨会话生命周期

`cross/orchestrator.py` 把同步 SQLite/LanceDB/SessionManager 调用包进 `asyncio.to_thread`：`start_session` 创建记录并构建旧上下文，message/tool 记录事件，`stop_session` 提取观察、生成摘要并可调用 SimpleMem，`end_session` 完成清理（`:80-126`、`:132-340`）。`cross/tests/test_e2e.py` 通过真实临时 SQLite、mock 向量库和 stub extractor 验证完整生命周期、上下文累计、租户隔离、脱敏与持久化。

## 6. API / CLI / SDK 面

### 6.1 Python SDK（稳定公共面）

`simplemem/__init__.py:21-54` 的 `__all__`：

```python
from simplemem import SimpleMem, create, list_modes, optimize, Config, load_config
```

| 入口 | 主要调用 | 备注 |
|---|---|---|
| `SimpleMem()` / `create(mode="auto")` | `add_dialogue`、`add_dialogues`、`finalize`、`ask`、`get_all_memories`、`close` | 首次 text/omni 调用锁定模式 |
| `create(mode="text")` | 同上 | `SimpleMemSystem`，LanceDB 文本路径 |
| `create(mode="omni")` | `add_text`、`add_image`、`add_audio`、`add_video`、`query`、`close` | `OmniMemoryOrchestrator` |
| `simplemem.optimize` | `optimize(mem, [(question, answer)], max_rounds=7)` | 只支持已初始化 text backend 的简化演化路径 |
| `Config` / `load_config` | `Config.save(path)`、JSON 读回 | `Config` 是优化结果的部署配置，不等于 Omni 配置 |

text 构造器参数包括 `api_key/model/base_url/db_path/table_name/clear_db`、thinking/streaming、planning/reflection、并行构建/检索与 worker 数；配置解析优先级是 constructor → 可导入顶层 `config.py` → 同名环境变量 → 内置默认（`core/settings.py:1-80`）。

### 6.2 根目录/文本 CLI 与 benchmark

- `SKILL/simplemem-skill/scripts/cli_persistent_memory.py` 提供 `add`、`import`、`query`、`retrieve`、`stats`、`clear --yes`；CLI reference 同时出现 `add_batch` 的旧命令名，需以脚本当前 argparse 为准，未在本次执行验证。
- `test_locomo10.py` 是 LoCoMo 评测脚本，加载对话、QA、事件摘要、观察并计算 ROUGE/BLEU/BERTScore/METEOR/SentenceTransformer 相似度及可选 LLM judge；运行会触及数据/模型/网络，不在本次范围。
- EvolveMem：`EvolveMem/run_evolution.py`、`run_benchmark.py`；Omni：`OmniSimpleMem/benchmarks/locomo/run_locomo.py`。

### 6.3 HTTP API

**独立多租户文本 MCP HTTP 服务**（`MCP/server/http_server.py`）：

- 注册/认证：`POST /api/auth/register`、`GET /api/auth/verify`、`POST /api/auth/refresh`。
- 运行信息：`GET /api/health`、`GET /api/server/info`。
- MCP Streamable HTTP：`POST/GET/DELETE /mcp`；旧兼容：`GET /mcp/sse`、`POST /mcp/message`；Bearer token + `Mcp-Session-Id`。
- JSON-RPC 方法：`initialize`、`initialized`、`ping`、`tools/list`、`tools/call`、`resources/list`、`resources/read`。
- MCP tools：`memory_add`、`memory_add_batch`、`memory_query`、`memory_retrieve`、`memory_clear`、`memory_stats`。

**Omni REST**（`simplemem/multimodal/app.py`）：`GET /health`、`GET /stats`、`POST /session/start`、`POST /session/end`、`POST /memory/text|image|audio|video`、`POST /query`、`POST /expand`、`POST /answer`、`GET /events`、`GET /events/{event_id}`、`GET /mau/{mau_id}`。

**Cross REST**（`cross/api_http.py`，通常挂在 `/cross` 前缀）：`POST /sessions/start`、`POST /sessions/{id}/message`、`POST /sessions/{id}/tool-use`、`POST /sessions/{id}/stop`、`POST /sessions/{id}/end`、`POST /search`、`GET /stats`、`GET /health`。

### 6.4 MCP / Agent SDK 面

- 根 README 的云/自托管文本 MCP 是 `MCP/` HTTP 服务；支持 Claude Desktop、Cursor 等 MCP 客户端。
- `OmniSimpleMem/omni_mcp` 是独立 stdio JSON-RPC 2.0 服务，命令：`python -m omni_mcp --data-dir ...`。工具包括 `omni_add_text/image/audio/video/document`、`omni_query`、`omni_answer`、`omni_stats`、`omni_list_events`、`omni_consolidate`、`omni_list_namespaces`、`omni_delete_namespace`；每个 namespace 有独立目录、MAU、向量和事件存储，名称做路径穿越校验。
- `cross/api_mcp.py` 的 `MCPToolRegistry` 暴露 8 个工具：`cross_session_start/message/tool_use/stop/end/search/context/stats`，生成 JSON Schema 并异步分发。
- `SKILL/SimpleMem.skill`、`simplemem/integrations/simplemem-skill/SKILL.md` 和 CLI 脚本是 Agent/Claude Skill 接入层，不是独立数据库协议。

## 7. 技术栈与依赖

| 分类 | 实际代码/清单 |
|---|---|
| 语言/运行时 | Python；根 `setup.py` 要求 `>=3.10`；Omni 独立包 `>=3.9`；MCP Docker 使用 Python 3.11 slim |
| LLM/协议 | `openai` OpenAI-compatible API；`anthropic`、`litellm`、LangChain/LangGraph 等出现在根锁定依赖；MCP SDK、JSON-RPC 2.0、Streamable HTTP |
| Embedding/视觉/音频 | `sentence-transformers`、Transformers、Torch、Qwen embedding、CLIP/OpenVision、Pillow、soundfile、librosa、VAD |
| 向量/全文检索 | LanceDB + PyArrow；Tantivy/LanceDB FTS；FAISS（Omni）；rank_bm25（Omni/Evolve）；结构化元数据索引 |
| 持久化 | 文本 LanceDB；Omni JSONL + FAISS + disk/S3 cold storage + JSON event/KG；Evolve SQLite + FTS5；Cross SQLite + LanceDB；MCP users SQLite + per-user LanceDB |
| Web/服务 | FastAPI、Uvicorn、python-multipart、CORS；Docker Compose；MCP HTTP/stdio |
| 数据/评测 | datasets、pandas、numpy、scikit-learn、NLTK、ROUGE、BERTScore、tqdm、SentenceTransformer |
| 测试 | pytest、pytest-asyncio；大量 mock/tmp_path/offline 测试；部分根脚本是手工测试/benchmark 而非标准 pytest 套件 |
| 打包 | setuptools `setup.py`；根统一包名 `simplemem` 版本 `0.3.0`；Omni 独立包名 `omnimem` 版本 `0.1.0` |

根 `requirements.txt` 是较大的锁定环境清单，并另外列 API 依赖；根 `setup.py` 的可选 extras 是 `server`、`benchmark`、`dev`、聚合 `all`。`requirements-gpu.txt` 单独固定 Torch/CUDA/Triton。MCP、Omni、EvolveMem 各有独立 requirements，不能仅凭根 requirements 推断所有子项目依赖已安装。

许可证事实：根 `LICENSE` 是 MIT；OmniSimpleMem 自带 LICENSE/README 标为 Apache 2.0。`setup.py` 的 classifier 仍写 Apache 2.0，与根许可证存在漂移，属于发布前需确认项。

## 8. 测试与验证面（仅静态盘点）

本次遵守“禁止安装依赖、启动服务、构建、运行测试”的范围，**没有执行 pytest、benchmark、CLI、FastAPI、MCP 或模型调用**。以下是对测试文件的 AST 静态盘点，不是通过数：

| 区域 | 测试文件 | 静态 `test_*` 函数 | 静态 `Test*` 类 | 主要覆盖 |
|---|---:|---:|---:|---|
| 根 `tests/` | 2 | 16 | 0 | LanceDB/自定义 backend、dense/keyword/structured 三路、过滤字段安全、生命周期、HybridRetriever |
| `cross/tests/` | 8 | 127 | 26 | 类型、SQLite、收集/脱敏、上下文、会话生命周期、整链集成、租户隔离 |
| `OmniSimpleMem/tests/` | 8 | 163 | 25 | MAU/配置/处理器/触发器/向量/BM25/KG/编排/Omni MCP；测试说明外部 LLM/embedding/file I/O 多数 mock |
| `MCP/` 顶层测试文件 | 3 | 2 | 0 | Ollama/参考评测入口；MCP 主 HTTP 逻辑测试不在该目录的独立标准套件中 |

已实际读取的代表性测试：

- `tests/test_vector_store_backend.py`：确定性 embedder/LLM、内存 backend、LanceDB backend、三路检索、注入过滤、转义、生命周期和 hybrid 调用路径。
- `tests/test_vector_store.py`：本地手工检查 semantic/FTS/structured/timestamp/optimize/get-all，并提供可选 GCS 路径。
- `cross/tests/conftest.py`、`test_e2e.py`：临时 SQLite、mock vector store、stub collector/extractor；验证 session → events → finalize → context、租户隔离和 redaction。
- `OmniSimpleMem/tests/test_orchestrator.py`：mock 重型 processor/retriever/LLM，验证初始化、session、add_text、query、token budget。
- `OmniSimpleMem/tests/test_omni_mcp.py`：离线 JSON-RPC、工具 schema、namespace 隔离/穿越拒绝、文档/媒体校验、重启持久化和 API key 错误。

## 9. 配置、运行与持久化边界

### 文本核心

- `config.py.example`：`OPENAI_API_KEY`、`OPENAI_BASE_URL`、`LLM_MODEL`、`EMBEDDING_MODEL`、`EMBEDDING_DIMENSION`、窗口/并行/规划/反思、`LANCEDB_PATH`、表名。
- 默认文本路径：`./lancedb_data` / `memory_entries`；embedding 默认 Qwen3-Embedding-0.6B、1024 维。
- 运行前需有 OpenAI-compatible key；embedding 默认走本地 SentenceTransformer/Qwen 路径，模型下载和缓存位置未在本次执行确认。

### MCP HTTP

- `MCP/config/settings.py` 读取 `.env`/环境变量，默认数据目录 `./data`、users DB `./data/users.db`、LanceDB `./data/lancedb`、端口 8000。
- provider：`openrouter` / `requesty` / `ollama`；JWT 与 API key 加密有内置默认值，代码会发出不安全默认密钥警告。
- Docker Compose 用命名卷 `simplemem_data`，通过 `/app/MCP/data` 持久化，容器启动入口不在本次运行。

### Omni

`OmniMemoryConfig` 控制 storage/index/cold、embedding 维度、LLM、retrieval、entropy trigger、event/evolution/router；`data_dir` 会派生 cold/index/向量等子目录。独立 stdio MCP 再按 namespace 派生完全隔离的数据目录，LRU 只缓存打开的 orchestrator。

### EvolveMem / Cross

EvolveMem 的 `MemoryStore` 默认 SQLite/FTS5，并把演化缓存、结果、policy、telemetry 等分散到配置目录；Cross 默认 `~/.simplemem-cross/cross_memory.db` 与 `~/.simplemem-cross/lancedb_cross`，context 默认预算 2000 token。确切运行路径取决于构造器和环境覆盖。

## 10. 未确认项与结构性风险

以下内容本次只做静态发现，没有用安装、启动、构建或测试来确认：

1. **没有 AGENTS.md/CLAUDE.md**：在项目树中未发现仓库级 `AGENTS.md` 或 `CLAUDE.md`；贡献/运行规则以 README、子目录文档和源码为准。
2. **依赖可用性未确认**：未安装依赖、未导入全栈；不能宣称当前 Python 环境可运行 text/omni/MCP/benchmark。
3. **模型/API 未确认**：未验证 key、endpoint、model name、embedding 维度、CLIP/VAD/音频工具和 OpenRouter/Requesty/Ollama 的实际兼容性。
4. **重复实现与入口漂移**：`simplemem/multimodal`、`OmniSimpleMem/omni_memory`、`MCP/`、`simplemem/integrations/server`、`MCP/reference` 和 `SKILL` 存在平行实现；根 `router.py` 路由统一包内实现，顶层 `simplemem_router.py` 路由旧/外置实现，选择规则需按调用入口确认。
5. **依赖/打包漂移**：根 README 示例提到 `pip install -e .[server]` 和 `gpu`，但根 `setup.py` 明确 extras 中未见 `gpu`，GPU 依赖另列 `requirements-gpu.txt`；需发布前核对。
6. **许可证元数据漂移**：根 LICENSE 为 MIT，根 `setup.py` classifier 写 Apache；Omni 子包自带 Apache 2.0 标识，不能把整个仓库简单视为单一许可证。
7. **数据目录/维度漂移**：文本默认 embedding 1024 维；MCP 默认 2560 维；Omni 可配置 384/768/3072 等；同一 LanceDB 表不能混用维度，跨实现复用数据的迁移边界未确认。
8. **服务安全配置仍需部署审计**：MCP settings 允许默认 JWT/AES 密钥并仅警告；实际部署是否通过强 secret、CORS allow-list、反代 TLS 和持久卷保护未确认。
9. **测试可信度边界**：Cross E2E 明确需要 patch/stub 以适配 collector API；Omni 测试大量 mock；根 LoCoMo benchmark 会初始化模型/尝试 NLTK 数据；静态存在不等于端到端外部服务可用。
10. **并发/一致性未压测**：源码包含线程池、RLock、异步 `to_thread` 和多 namespace LRU，但写入顺序、并发重复、跨进程锁、异常恢复和索引重建未执行验证。
11. **压缩与检索语义未做质量复核**：LLM 输出解析失败会重试并最终返回空列表；回答 JSON 失败有原始文本回退；时间解析、结构化过滤和反思的边界行为需要针对真实数据验证。
12. **生产闭环未确认**：尚未验证 Docker build/compose、MCP Streamable HTTP 会话恢复/过期清理、注册后用户表与向量表的一致性、Omni stdio stdout/stderr 约束，以及 Cross HTTP/MCP 与异步 orchestrator 的实际挂载方式。
13. **官方性能数字未复现**：README/子项目文档中的 LoCoMo、MemBench、Mem-Gallery 数字是项目声明；本次没有数据集、模型或 benchmark 运行证据。

## 11. 建档范围与变更边界

- 已读取：根 README、根/子项目依赖、setup/config/Docker 文件、统一入口、text 核心、vector/data models、multimodal orchestrator/processors/storage/retrieval/KG、EvolveMem、Cross、MCP/HTTP/stdio 文档与代表性测试。
- 未做：安装依赖、修改源码/依赖/测试/配置、生成数据库/模型缓存、启动服务、构建镜像、执行测试、提交 Git。
- 本次新增文件：`ARCHITECTURE.md`（仅项目根这一份）。

本文件已吸收此前 `细探-SimpleMem.md` 的源码分析结论；后续只维护本文件，旧细探笔记不再作为独立事实源。

## 12. 第三轮：通用底座映射与裁决（仅基于源码证据）

### 12.1 本轮范围、证据边界与总裁决

本轮在既有建档和内部细探之上，专门回答：记忆压缩、分层存储、召回、上下文、embedding/重排、批任务和资源，若接入系统工程平台，分别应归入**记忆支持库、记忆模块、运行核心、统一网关**的哪一层；同时固定唯一写入/检索链路、幂等语义、失败/超时/取消/崩溃处置和 L0-L4 验证门槛。

本轮代码图事实：第一次 `project_context` 返回的是错误项目 `华世王镞_v3`（根目录 `~/Documents/Agent/PHP/华世王镞_v3`，开工 id 为空），不能作为 SimpleMem 证据；随后按目标绝对路径调用 `codegraph_explore`，服务明确返回“SimpleMem 未建立 `.codegraph/`，不可查询”。因此本节的源码证据全部来自目标工作树的文件读取和静态交叉核对，**不把错误项目代码图或不可用代码图冒充 SimpleMem 证据**。仓库内未找到独立的 `细探-SimpleMem.md`；既有文档已声明其结论已吸收到本文件，本轮继续以当前源码为准。

**总裁决：吸收边界契约，隔离平行实现；不把 SimpleMem 任何一套实现直接升级为平台生产底座。** 当前仓库不是一条链，而是文本核心、MCP 服务副本、Omni 多模态链、Cross 跨会话链、`OmniSimpleMem/` 和 Skill/参考副本并存。第三轮要做的是把能力语义收敛到平台四层的唯一 owner，而不是把这些目录互相串接。

### 12.2 四层归属表：能力、源码落点与裁决

| 通用能力 | 记忆支持库（原子能力/提供者） | 记忆模块（领域流程） | 运行核心（执行与资源治理） | 统一网关（协议与边界） | 本轮裁决 |
|---|---|---|---|---|---|
| 语义结构化压缩 | LLM 调用、JSON 解析、`MemoryEntry`/`MAU` 序列化契约 | 窗口切分、指代消解、绝对时间、事实抽取、冗余/熵门控 | 批窗口调度、重试预算、任务状态、取消和恢复 | `memory_add`/`memory_add_batch` 请求校验与结果投影 | **模块吸收流程，支持库只提供调用与模型契约；不复制 `MemoryBuilder`** |
| 分层存储 | LanceDB/FAISS/BM25/SQLite/JSONL/文件/S3 适配器，原子读写、摘要、索引重建 | 记忆实体、事件、来源、状态、归档与血缘关系 | 连接/句柄/文件/临时目录/锁、原子提交、残留清理 | 租户、namespace/table 映射，禁止外部直连存储 | **吸收提供者接口；MAUStore、Cross SQLite、MCP per-user table 只保留项目适配语义** |
| 召回与 embedding | `EmbeddingModel`、多模态 `EmbeddingService`、向量库、FTS/BM25、结构化过滤 | 意图规划、多查询、混合召回、反思、图召回、preview/expand、parametric fallback | 并发查询、token/API 预算、超时、部分结果和可观测证据 | `memory_query`/`memory_retrieve`、HTTP/MCP 会话与错误码 | **模块持有召回编排；支持库不持有“问答流程”** |
| 重排 | 当前仅有向量距离、BM25 分数和插入顺序，无 cross-encoder/学习重排证据 | 统一分数、去重、候选截断、可插拔 rerank 策略 | 重排耗时/模型资源预算、取消、版本和结果证据 | top-k、token budget、来源字段 | **新建“重排原子能力”候选，当前标为待核；禁止宣称已有重排** |
| 上下文装配 | token 估算、文本渲染、上下文结构序列化 | `AnswerGenerator`、Omni `format_for_llm`、Cross `ContextInjector` 的优先级与预算 | token 预算、截断、敏感信息脱敏、失败降级 | system prompt 注入、MCP/HTTP 返回、调用方版本适配 | **模块统一 ContextBundle；Cross 的模板渲染只作为适配器** |
| 记忆压缩/巩固/蒸馏 | JSONL 样本、模型/训练提供者、归档和快照读写 | `MemoryConsolidator`、`MemoryDistiller`、parametric recall、生命周期状态 | 长任务、GPU/进程/文件资源、检查点、失败回滚、恢复 | `consolidate`/`distill` 管理操作应异步化、权限化 | **模块保留策略；训练和大任务进入运行核心监督，不进入网关同步请求** |
| 批任务 | 批量向量编码、批量插入、批量索引、批量读取原子能力 | `add_dialogues`、多查询、批量 expand、Cross finalize | job id、队列、并发度、重试、取消、断点、幂等提交 | 只提交/查询/取消 job，不持有 worker | **新建统一记忆任务适配器，不能沿用各目录私有线程池作为第二任务系统** |
| 资源生命周期 | 连接、向量索引、文件/S3、模型句柄的 acquire/release | 领域流程声明资源依赖和所有权 | 统一租约、预算、超时、取消、崩溃回收、诊断 | 请求级 deadline、认证、限流、审计 | **运行核心唯一 owner；模块不能自行杀进程、清理跨任务资源或绕网关** |

### 12.3 当前源码的真实写入链：四条并行链，不存在唯一 owner

```text
现状（不是目标架构）

文本 SDK：
  SimpleMem/AutoMemory
    → simplemem.text.system.SimpleMemSystem
    → simplemem.core.memory_builder.MemoryBuilder
    → simplemem.core.database.vector_store.VectorStore
    → EmbeddingModel.encode_documents
    → LanceDBVectorStoreBackend.insert

MCP 服务副本：
  MCPHandler.tools/call
    → integrations/server/core/MemoryBuilder
    → client.create_embedding
    → integrations/server/database/MultiTenantVectorStore.add_entries
    → 每用户 LanceDB table.add

Omni：
  OmniMemoryOrchestrator.add_text/image/audio/video
    → modality Processor（摘要/embedding/raw pointer）
    → _store_mau
      ├→ MAUStore.add（JSONL）
      ├→ VectorStore.add/add_text/add_visual（FAISS/NumPy）
      ├→ EventManager.add_mau_to_event
      ├→ EntityExtractor → KnowledgeGraph
      └→ consolidator.record_memory_access

Cross：
  CrossMemOrchestrator.record/finalize
    → SessionManager + SQLiteStorage（events/observations/summary）
    → 可选 SimpleMem.add_dialogues/finalize
    → CrossSessionVectorStore.add_entries（另一个 LanceDB 表）
```

这四条链使用不同模型、表结构、embedding 维度、错误形状和资源目录，且 `simplemem/integrations/server/`、`OmniSimpleMem/`、`MCP/reference/`、Skill 副本与统一包并非同一实例或同一数据目录。故平台的**唯一写入链**应冻结为：

```text
统一网关（HTTP/MCP/SDK 适配）
  → 记忆模块.写入/批写入（校验、规范化、生成 operation_id/idempotency_key）
  → 运行核心.提交记忆任务（状态、预算、租约、取消、恢复）
  → 记忆支持库.压缩/embedding/索引/持久化提供者
  → 唯一权威记忆存储（事实/状态先提交）
  → 派生索引、事件、图谱、冷数据、证据（由同一任务编排，失败可重放）
  → 统一结果/事件/资源释放
```

**写入 owner 规则：**事实和状态只能由记忆模块通过支持库公开入口提交；embedding、向量/FTS、冷对象、图谱是派生物，不得被网关或消费者旁路写库。当前 `_store_mau()` 同时写五类存储、Cross finalize 还会再次把 SimpleMem 结果写入 Cross 表，均只能作为待迁移的历史实现，不能被认定为平台唯一事务。

### 12.4 当前源码的真实检索链与平台唯一检索链

文本 `HybridRetriever.retrieve()` 的真实顺序是：规划 LLM → 目标查询 → semantic（可并发）→ keyword → structured → 按 `entry_id` 首次出现去重 → 可选反思补查；`_merge_and_deduplicate_entries()` 只按 ID 去重，不计算统一分数。`VectorStore` 的 semantic 是 embedding 后调用 LanceDB 距离升序，keyword 是 FTS 分数降序，structured 是 metadata 条件。没有看到 cross-encoder、学习排序或统一 score calibration。

Omni `query()` 先 `QueryProcessor` 决定策略，再 `PyramidRetriever.retrieve_preview()` 做向量预览；可附加 BM25（明确追加到 FAISS 结果尾部，不重排）、知识图谱 source MAU、parametric recall（置信度大于 0.8 才挂答案），需要时才 `expand()` 读取 details/raw。Cross 上下文则是 summaries → observations → semantic entries 的贪心 token 打包。平台唯一检索链应为：

```text
统一网关.检索请求
  → 记忆模块.解析意图/确定范围/建立 query_plan
  → 记忆支持库.embedding（query 向量）
  → 记忆支持库.多视图召回（dense + lexical + structured + graph/parametric 可选）
  → 记忆模块.统一分数、去重、版本/租户/有效期过滤
  → 待核的 rerank 原子能力（没有提供者则明确 NOT_AVAILABLE，不静默伪造）
  → 记忆模块.ContextBundle（token budget、preview→expand、来源）
  → 运行核心.监督 LLM 生成/流式任务
  → 统一网关.答案/来源/诊断/事件
```

**唯一检索 owner：**候选召回和过滤由支持库提供者实现，query plan、去重、重排、context 和 answer orchestration 由记忆模块实现；运行核心只监督耗时/资源/取消，不重新实现检索；网关只转发并投影结果。所有历史入口（`memory_query`、`memory_retrieve`、Omni `query/expand/answer`、Cross `search/context`）必须最终落到这一条模块入口，不能各自维护一套分数和 fallback。

### 12.5 幂等、失败、超时、取消、崩溃：源码事实与底座要求

| 场景 | 当前源码事实 | 当前风险/证据等级 | 平台归属与硬要求 |
|---|---|---|---|
| 重复写入 | 文本 `MemoryEntry` 默认 UUID；`VectorStore.add_entries()` 每次 encode 后直接 `backend.insert()`；Omni `MAUStore.add()` 追加 JSONL，未检查已有 ID；Omni vector store 追加 mapping；MCP `table.add()` 无唯一键 | **非幂等**；重试可能产生重复事实、重复向量和孤儿 raw | 记忆模块生成稳定 `memory_id = hash(tenant, source, source_event, canonical_content, schema_version)`；支持库以唯一键/CAS/幂等表拒绝重复；相同 key+payload 返回原结果，不同 payload 明确冲突 |
| 批写入 | 文本大批量用 `ThreadPoolExecutor`，`as_completed` 收集成功窗口，失败窗口打印后丢弃；Cross finalize 每次可重复插 event/observation/summary 和 SimpleMem entries | **部分成功无任务账本**；重跑不能可靠续接 | 运行核心 job 状态 `accepted/running/partial/succeeded/failed/cancelled`，每个窗口有 checkpoint、attempt 和 operation_id；成功项不可重复，失败项可重放 |
| LLM/JSON 失败 | 文本抽取、query analysis、answer generation 各自最多 3 次；失败后抽取返回空、分析回退原 query、回答回退原文/固定错误 | 有重试，但没有统一 deadline、错误码和成本上限 | 支持库只报告稳定错误；模块决定可重试；运行核心统一指数退避、总 deadline、预算和证据；不能把空列表当成功写入 |
| embedding 失败/维度错 | 文本写入在 embedding 异常时直接失败；Omni processor 返回 `No embedding data received`；Omni query embedding 失败返回空 preview；多模态 averaged embedding 检查维度 | 事实、raw、索引可能处于不同阶段；跨存储无事务 | 先校验 embedding provider、维度和模型指纹；事实提交与派生索引有可恢复状态；索引失败不能伪造“已可检索” |
| 存储失败/部分提交 | LanceDB `insert/add`、JSONL append、FAISS add、event/KG 更新彼此没有统一事务；`_store_mau` 后续实体失败只 warning | **半写入窗口明确存在** | 运行核心持有提交事务/补偿任务；权威事实先落账，派生物按状态重建；对账读取权威事实与索引差异 |
| 超时 | `LLMClient` 只做 1/2/4 秒重试等待，OpenAI client 没有本项目级 timeout；FAISS/SQLite/文件读取无统一 deadline；`asyncio.to_thread` 不传取消 token | **未实现统一超时**，不能宣称可取消 | 网关传 deadline；运行核心用硬截止监督真实 provider/子进程；超时返回可重试错误并回收线程/进程/连接/临时文件 |
| 主动取消 | 线程池/`asyncio.to_thread`/processor/存储接口未暴露 cancel token；Future 只等待结果，没有取消路径 | **未发现取消契约** | 运行核心拥有 cancel(job_id)，设置 cooperative token；不可协作 provider 必须隔离进程并 killpg；取消后状态幂等、结果不可再提交 |
| 崩溃/重启 | 部分索引和 JSONL 初始化时重载；Omni `close()` 保存 vector/KG/parametric；没有统一 WAL/事务恢复或进程 supervisor；Cross SQLite 有 migration/rollback，但 finalize 无恢复账本 | **有局部重载，无端到端崩溃恢复证据** | 运行核心记录意图、checkpoint、租约和恢复证据；重启扫描未完成 job，按幂等 key 重放/回滚；杀进程后验证无孤儿 worker、锁、临时目录 |
| 资源释放 | ThreadPool `with` 会等待 worker；Cross `close()` 关 SQLite；Omni `close()` 保存各索引；`retrieve_to_file()` 创建临时文件但由调用者负责生命周期；OpenAI/httpx/model 句柄无统一 close owner | **释放责任分散** | 创建者声明 owner，转移显式；成功/失败/超时/取消/崩溃均有 finally/监督回收和现场读回 |
| 访问隔离 | MCP 以 user table 隔离；Cross 以 tenant 字段和查询过滤；Omni namespace/目录隔离；统一 SDK 文本默认单表 | 层间隔离字段不统一，旁路入口容易绕过 | 网关认证得到 tenant/scope，模块所有读写都强制携带 scope；支持库拒绝缺 scope；隔离测试作为 L3/L4 门禁 |

### 12.6 记忆压缩、分层存储、召回、上下文与重排的落点细化

1. **压缩：记忆模块。** 文本源码的 `MemoryBuilder` 用 `WINDOW_SIZE`（默认 40）和 overlap 切窗，LLM 生成无代词、绝对时间、自包含 `MemoryEntry`；Omni `TextProcessor` 做长度/重复门控，图像/音频/视频 processor 做熵、VAD 或抽帧触发，再产出 `MAU(summary, embedding, raw_pointer, details, metadata)`。支持库只承载 prompt/JSON/模型调用、输入规范化和结果契约；不把 LLM prompt 写进网关。
2. **分层存储：支持库提供者 + 记忆模块状态。** `MAUStore` 的 JSONL 是热元数据/索引，`ColdStorageManager` 是本地或 S3 原始数据，FAISS/NumPy 是向量索引，EventStore/KG 是关联派生物；`PyramidRetriever` 的 `SUMMARY → METADATA → DETAILS → EVIDENCE` 是检索层级而非统一持久化事务。平台应把事实、派生索引、冷制品、缓存明确分层并保存血缘/摘要，不允许把 preview 当权威事实。
3. **召回：记忆模块编排，支持库执行。** text 是 dense + lexical + structured；Omni 是 vector + BM25 + graph + parametric，Cross 是 summaries/observations/vector。统一模块要固定候选来源、score 方向、去重键、有效期和 top-k；当前 Omni BM25 以 `bm25_score * 0.01` 追加且不重排，只能作为历史兼容策略，不能当作标准融合。
4. **上下文：记忆模块。** Cross `ContextInjector` 先摘要、后观察、再语义记忆，按 `len(text.split())` 贪心预算；Omni `format_for_llm` 先 summary/details 再 raw image；文本 `AnswerGenerator` 格式化所有上下文。平台应产出统一 `ContextBundle`，携带 token estimate、来源 ID、截断原因、敏感信息策略和可展开句柄。
5. **embedding/重排：支持库是 provider owner，模块是策略 owner。** 文本 `EmbeddingModel` 使用 SentenceTransformer/Qwen query prompt；Omni `EmbeddingService` 可能使用 CLIP/Tongyi/Doubao/OpenAI；Cross 复用文本 embedding。模型、维度和版本必须进入契约指纹。源码没有独立 reranker；“结构化优先/FAISS 保序/BM25 追加/首次 ID 去重”不是重排实现。重排能力列为**待核的新原子能力**，没有 provider 时必须可观测地禁用。
6. **批任务与资源：运行核心。** 文本写入/查询、Omni 多查询/批展开、Cross `asyncio.to_thread` 都是局部并发实现，不提供统一 job、租约、取消、deadline 或恢复。平台应将这些改为运行核心监督的任务，记忆模块只提交领域步骤和 checkpoint schema；网关仅同步等待短任务或返回 job 查询句柄。

### 12.7 复用、升级、新建、隔离裁决表

| 项目模式/能力 | 裁决 | 原因 |
|---|---|---|
| `MemoryEntry`/`MAU` 的自包含事实、来源、模态、raw pointer、状态字段 | **吸收契约，升级为统一记忆模型** | 价值明确，但当前两套模型和多套表结构不兼容；需统一 ID、scope、schema/version、validity、provenance |
| LanceDB/FAISS/SQLite/JSONL/S3/FTS/BM25 薄适配 | **吸收支持库候选** | 是真实存储边界；事务、维度、索引重建、路径和异常需由支持库统一托管 |
| 文本 `MemoryBuilder`、Omni processors、Cross finalize | **吸收领域语义，重写为记忆模块流程** | 三套流程职责重叠且写入副作用分散，不能直接并列成为三个生产入口 |
| `PyramidRetriever` 的 preview→expand、Cross token budget | **吸收模块策略** | 是可复用的上下文/成本模式；raw 加载、token 估算、来源和失败契约需统一 |
| 当前无 reranker | **新建原子能力，待核** | 只有分数拼接/保序/去重，不能把 README 或架构描述当实现证据 |
| ThreadPool/`asyncio.to_thread`/模型训练/批量 consolidation | **迁移到运行核心监督** | 当前无统一任务状态、取消、超时、崩溃恢复；不得再造第二套任务系统 |
| MCP HTTP、Omni REST/stdio、Cross HTTP/MCP、Skill/CLI | **保留适配器，统一网关出口** | 协议可复用，业务逻辑和存储写入必须下沉到同一模块入口；旧入口只做版本/参数/认证映射 |
| `MCP/`、`simplemem/integrations/server/`、`OmniSimpleMem/`、`MCP/reference/` 平行实现 | **隔离/逐步废弃为参考实现** | 重复模型、维度、provider 和数据目录，不满足单 owner；不能直接拼成平台核心 |
| `MemoryDistiller` 的 LoRA/训练与 parametric recall | **模块策略 + 运行核心长任务** | 有明确蒸馏意图，但真实训练可能走 mock；必须把 mock 与真实 provider 分开验收 |

### 12.8 L0-L4 验证分级与本仓库现状

L0-L4 是平台接入验收等级，不是 SimpleMem 当前已经通过的等级。当前文档阶段只做静态研究，没有安装依赖、启动服务、调用外部 LLM/embedding、运行 benchmark 或修改源码；因此不能把测试文件存在、README 描述、日志打印或历史数字记为通过。

| 等级 | 验证内容 | SimpleMem 需要的最小命令/证据 | 本轮判定 |
|---|---|---|---|
| **L0 静态契约** | 目标项目身份、源码路径、公开入口、模型/字段、依赖和四层映射；检查文档结构、路径存在、无旁路写入口 | `git diff --check -- ARCHITECTURE.md`；静态 AST/路径扫描；逐条源码路径回读 | **部分具备**：源码路径和入口已回读；目标 codegraph 不可用，错误 project_context 已明确隔离 |
| **L1 确定性单元** | 不依赖网络/模型的窗口、规范化、ID 幂等、过滤、去重、预算、错误形状、取消状态机 | `python -m pytest tests/test_vector_store_backend.py`、对应 Cross/Omni 单元（需环境满足）；新增平台实现须有确定性 fake provider | **只有历史测试源码证据**；本轮未执行，且现有测试多使用 fake/mock，不能覆盖完整外部链 |
| **L2 真实本地持久化** | 临时 LanceDB/SQLite/JSONL/FAISS 写读、重启加载、索引重建、重复提交、部分失败对账、租户隔离 | `python -m pytest tests/ cross/tests/test_storage.py OmniSimpleMem/tests/test_vector_store.py`（独立临时目录）；读回计数/ID/文件残留 | **未验证**：既有 Cross E2E 使用临时 SQLite 但向量多为 mock；现有存储没有统一跨表事务 |
| **L3 真实 provider/网关** | 真实 embedding/LLM、MCP Streamable HTTP/REST、认证租户、超时、断线、限流、取消和错误码 | 启动隔离服务后用真实 HTTP/MCP 客户端逐条走 add/batch/query/retrieve/clear；记录端口、provider、deadline、退出码 | **未执行**：本轮禁止启动/外部调用；源码也没有统一 timeout/cancel 契约 |
| **L4 崩溃/恢复/生产式验收** | kill/重启 worker 或网关，恢复未完成 job，核对事实/索引/冷文件，验证幂等重放、无半写入、无孤儿资源和性能/成本预算 | 独立临时数据目录；注入窗口/embedding/存储/HTTP/进程故障，`kill` 后全新进程恢复；读回 job ledger、索引、文件、进程和端口 | **未验证且当前实现不满足**：没有统一 job ledger、checkpoint、监督器和崩溃恢复证据 |

**本轮最低验收结论：**可把 L0 的源码事实和映射写入底座需求输入；不能把 SimpleMem 作为已通过 L1-L4 的生产记忆组件。后续任何平台实现必须先补能力需求、契约 owner、幂等键、资源/失败矩阵和 L1-L4 验收工作包，再决定复用或新建。

### 12.9 第三轮装配计划（只作为候选，不代表已修改平台）

1. **先冻结公共契约：**统一 `MemoryId/Scope/Source/Validity/SchemaVersion/EmbeddingFingerprint/OperationId/IdempotencyKey`，定义 `写入结果`、`检索结果`、`ContextBundle`、`JobStatus` 和稳定错误码；明确事实写 owner 与派生索引状态。
2. **再登记支持库能力：**embedding（query/document）、向量索引、lexical/BM25、structured filter、冷对象、JSON/SQLite/Lance/FAISS provider、摘要/原子文件、可选 rerank；每个能力一个 id、一个契约 owner、一个 provider 注册路径。
3. **建立记忆模块唯一入口：**`写入`、`批写入`、`检索`、`展开`、`装配上下文`、`巩固`、`蒸馏`；历史 SDK/MCP/REST/Cross/Omni 均只做适配，禁止直接实例化私有存储或自己翻译错误。
4. **接入运行核心任务：**为批压缩、批 embedding、索引构建、consolidation、distillation 建 job ledger、checkpoint、租约、deadline、cancel token、进程隔离和恢复对账；任务产物写临时目录后原子发布。
5. **最后收敛网关：**认证/租户/namespace、参数校验、限流、同步短任务与异步长任务分流、统一错误/事件/来源和版本兼容；`memory_clear` 等破坏性操作必须显式授权和证据。
6. **以 L0→L4 门禁推进：**L0 先证明唯一入口和无旁路；L1 验证确定性契约；L2 验证本地持久化和幂等；L3 验证真实 provider/网关；L4 验证杀进程、重启、重放、对账和残留清理。任一级失败都只能标为“待核”，不得用下一层的静态通过覆盖。

### 12.10 本轮新增剩余风险

- `project_context` 错绑项目且未产生开工 id；目标项目专属 `system_engineering_toolkit` 上下文未建立，代码图也未索引。上述事实已记录，不能当作平台项目证据。
- 源码存在多套同构实现和多个默认数据目录；未完成迁移前，任何“唯一链路”都只是目标约束，不是当前行为。
- 当前 embedding 维度在文本、MCP、Omni、Cross 间可不同，模型/维度指纹和迁移策略尚未统一；跨表直接复用会失败或产生不可比结果。
- 失败窗口、重复 finalize、重复 MAU、raw/metadata/vector/event/KG 半写入、模型/HTTP 句柄释放、超时取消和崩溃恢复均缺少端到端证据。
- parametric distillation 的真实训练路径和 `MemoryConsolidator` 的重要性注册/归档完整性尚未通过真实 provider 验证；mock training 不能算蒸馏完成。
- 本轮只允许并实际修改项目根 `ARCHITECTURE.md`；未修改源码、依赖、配置、测试、README 或 Git。
