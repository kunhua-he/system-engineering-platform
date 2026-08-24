# AriadneMem 架构建档

> 首轮全量架构建档（静态源码取证）
>
> 项目：AriadneMem — *Threading the Maze of Lifelong Memory for LLM Agents*
>
> 本文档只描述当前仓库源码可确认的结构、调用路径和接口；README、论文/细探材料中的设计目标不等同于已实现行为。源码参考库规则要求该文件作为本仓唯一架构事实入口。

> 当前核对已完整对照并吸收 `细探-AriadneMem.md` 中仍与当前仓库一致的架构事实；该文件保留作历史细探记录，但后续架构事实只维护本文档。

## 1. 定位与范围

AriadneMem 是面向长时程 LLM Agent 的结构化长期记忆系统。其核心思想是把**记忆构建**和**在线结构化推理**拆成两个阶段：输入对话先被抽取为原子记忆条目并写入 LanceDB；查询时通过混合召回、实体/时间建图、桥接节点发现和 DFS 多跳路径挖掘生成拓扑感知上下文，再调用 LLM 合成答案。

README 将该项目标识为 *Threading the Maze of Lifelong Memory for LLM Agents*，并链接项目页与论文 arXiv:2603.03290；这些是项目溯源信息，不替代下文的源码实现证据。

仓库当前提供三种使用面：

- Python 直接集成：`main.AriadneMemSystem`。
- 演示/评测脚本：`quick_test.py`、`demo_multihop.py`、`test_locomo10.py`。
- MCP 服务：`MCP/server/stdio_server.py`（stdio）和 `MCP/server/http_server.py`（Streamable HTTP + REST 健康/信息接口）。

当前仓库基线：Git 分支 `main`，HEAD 为 `95c7754`（以本地 Git 为准）。目标仓库没有发现 `AGENTS.md` 或 `CLAUDE.md`；上级源码参考库规则要求本仓只读研究，不安装依赖、不启动服务、不构建。

## 2. 总体文本流程图

### 2.1 双阶段主流程

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                         AriadneMemSystem                                    │
└─────────────────────────────────────────────────────────────────────────────┘
             │
             ├── 初始化：LLMClient + EmbeddingModel + VectorStore
             │                    │
             │                    └── LanceDB 表 + enhanced_index.json
             │
             ▼
┌────────────────────────────── PHASE I：记忆构建 ─────────────────────────────┐
│ Dialogue(s)                                                                  │
│   │                                                                          │
│   ├─ serial redundancy gate：VectorStore.semantic_search + cosine similarity │
│   │       └─ 短时高相似/精确重复 → 丢弃；异常默认保留                       │
│   ▼                                                                          │
│ dialogue_buffer（按 WINDOW_SIZE 分窗，默认 40）                              │
│   │                                                                          │
│   ├─ _generate_memory_entries / worker：OpenAI-compatible LLM JSON 抽取       │
│   │       └─ MemoryEntry：主体-动作-客体的 lossless_restatement + 元数据     │
│   ▼                                                                          │
│ conflict-aware coarsening（当前实现是相似条目过滤/去重）                      │
│   │                                                                          │
│   ▼                                                                          │
│ VectorStore.add_entries                                                     │
│   ├─ EmbeddingModel.encode_documents                                        │
│   └─ LanceDB：dense vector + lexical keywords + symbolic metadata            │
│   │                                                                          │
│   └─ finalize：AggregationBuilder → EnhancedMemoryIndex → enhanced_index.json│
└─────────────────────────────────────────────────────────────────────────────┘
             │
             ▼
┌────────────────────────────── PHASE II：在线推理 ────────────────────────────┐
│ question                                                                     │
│   │                                                                          │
│   ├─ enhanced cache fast path：count / list / relation                        │
│   ├─ regex attribute fast path（依赖 VectorStore.query_attribute）            │
│   ├─ hybrid recall：semantic top-k ∪ keyword top-k（并行）                    │
│   ├─ target entity 过滤/排序                                                  │
│   ├─ query-specific graph：实体重叠/时间邻近边                                │
│   ├─ bridge discovery：时间约束的 semantic 搜索（Steiner 近似）               │
│   ├─ DFS multi-hop path mining（默认深度 3，eco=10 / pro=25 条路径）          │
│   └─ node budget：相关性排序，8–25 节点                                      │
│   │                                                                          │
│   ▼                                                                          │
│ GraphPath（nodes + edges + reasoning_paths + target_entity）                 │
│   │                                                                          │
│   ▼                                                                          │
│ AriadneAnswerGenerator                                                       │
│   ├─ 序列化 [Facts] / [Reasoning Paths] / inferred bridge                    │
│   ├─ 单次 LLM topology-aware synthesis（JSON）                               │
│   ├─ extract_json + 最多 3 次答案重试                                         │
│   └─ SemanticNormalizer.normalize（格式/列表/日期/数字/大小写后处理）         │
│   │                                                                          │
│   ▼                                                                          │
│ answer string / MCP JSON-RPC result                                          │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 MCP 外部接入流程

```text
MCP Client / Cursor / Claude / Copilot
        │
        ├── stdio：一行一个 JSON-RPC 2.0 → stdio_server.py → MCPHandler
        │
        └── HTTP：Bearer + /mcp POST/GET/DELETE
                    │
                    ├── session_manager：会话、队列、30 分钟清理
                    └── FastAPI → MCPHandler
                                  │
                                  ▼
                         AriadneMemSystem（共享系统实例）
                                  │
                         tools/call / resources/read
```

## 3. 分层与模块职责

### 3.1 应用编排层

| 路径 | 职责 | 关键符号 |
|---|---|---|
| `main.py` | 组装所有组件，提供写入、收尾、查询和调试入口 | `AriadneMemSystem`、`create_system` |
| `MCP/server/mcp_handler.py` | 把系统包装成 JSON-RPC/MCP 工具与资源 | `MCPHandler`、`JsonRpcRequest`、`JsonRpcResponse` |
| `MCP/server/stdio_server.py` | 静默加载系统，stdin/stdout 单行 JSON-RPC | `main` |
| `MCP/server/http_server.py` | FastAPI 生命周期、鉴权、会话和 HTTP/SSE 路由 | `app`、`SessionManager`、`get_system` |
| `MCP/run.py` | HTTP 服务命令行启动器 | `--host`、`--port`、`--reload` |

### 3.2 核心算法层

| 路径 | 职责 | 关键实现 |
|---|---|---|
| `core/ariadne_memory_builder.py` | Phase I：门控、窗口化抽取、相似去重、批量写入、增强索引构建 | `add_dialogue(s)`、`process_window`、`_process_parallel`、`build_enhanced_index` |
| `core/ariadne_graph_retriever.py` | Phase II：快速路径、混合召回、图构造、桥接节点、DFS 路径、节点预算 | `retrieve`、`_hybrid_recall`、`_build_inference_graph`、`_discover_reasoning_paths` |
| `core/ariadne_answer_generator.py` | 将查询子图序列化为提示词并生成答案 | `generate_answer`、`_build_topology_context` |
| `core/aggregation_builder.py` | 从条目派生实体聚合、关系三元组和时间索引 | `build_aggregations` |
| `core/semantic_normalizer.py` | 答案输出的格式归一化，不是独立的实体/记忆规范化存储层 | `normalize` |
| `core/exmaple.py` | 旧版/示例答案生成器，当前入口不使用 | `AriadneAnswerGeneratorExample` |

`core/__init__.py` 导出 `AriadneMemoryBuilder`、`AriadneGraphRetriever`、`AriadneAnswerGenerator`。`exmaple.py` 的拼写和“older/example”定位表明它不是当前主实现。

### 3.3 数据、存储与基础设施层

| 路径 | 职责 |
|---|---|
| `models/memory_entry.py` | Pydantic 数据契约：`Dialogue`、`MemoryEntry` |
| `models/enhanced_structures.py` | Pydantic 增强索引结构：实体聚合、关系、缓存、时间信息、归一化规则 |
| `database/vector_store.py` | LanceDB 连接、表初始化、写入、dense/keyword/structured 查询、清空、增强索引 JSON 读写 |
| `utils/embedding.py` | SentenceTransformers/Qwen3 embedding、设备选择、模型缓存、查询 embedding 缓存 |
| `utils/llm_client.py` | OpenAI SDK 兼容客户端、Qwen 特殊参数、streaming、JSON 解析、重试 |
| `config.py.example` | 配置模板；实际运行需要复制为未纳入版本控制的 `config.py` |

### 3.4 数据集与评测层

- `dataset/locomo10.json`：LoCoMo 评测数据，源码按 conversation、QA、event summary、observation、session summary 解析。
- `test_locomo10.py`：包含数据类、数据加载、记忆构建、查询、并行问答、指标计算、LLM-as-judge 和结果落盘。
- `quick_test.py`：手写测试套件，不是 pytest/unittest 发现式测试。
- `demo_multihop.py`：四组多跳/因果/统计/对比演示，直接使用真实 LLM、embedding 和 LanceDB。

## 4. 核心数据模型

### 4.1 输入与原子记忆

`models/memory_entry.py`：

- `Dialogue`：`dialogue_id: int = 0`、`speaker: str`、`content: str`、可选 `timestamp`。通过 `AriadneMemSystem.add_dialogue(s)` 写入 builder buffer；ID 可由系统或 MCP handler 自动分配。
- `MemoryEntry`：以 UUID 字符串为默认 ID 的原子事实。必填 `lossless_restatement`；其余字段为 `keywords`、`timestamp`、`location`、`persons`、`entities`、`topic`。
- Pydantic v2 是声明式校验边界，但模型未配置 `extra="forbid"`，也未见跨字段事实完整性校验。

### 4.2 增强派生索引

`models/enhanced_structures.py` 定义：

- `EntityAggregation`：实体名/类型、事件计数、属性集合、按动作的首末时间与计数、证据条目 ID。
- `RelationTriple`：`subject/predicate/object`，可带时间、地点、来源 entry ID 和 confidence。
- `QueryCache`：缓存键、任意缓存值、类型、命中计数和来源条目；当前 `AggregationBuilder` 只构建实体/关系/时间索引，未见实际填充 query cache。
- `EnhancedMemoryIndex`：`entities`、`relations`、`query_cache`、`temporal_index`、`normalization_rules`，可序列化到 JSON 并恢复；`TemporalInfo`、`SemanticNormalizationRule` 是可用模型，但首轮主路径未见完整生产填充。

### 4.3 LanceDB 持久化模型

`database/vector_store.py::_init_table` 建立名为 `ariadnemem_entries`（可由配置覆盖）的 LanceDB 表，字段为：

```text
entry_id: string
lossless_restatement: string
keywords: list<string>
timestamp: string
location: string
persons: list<string>
entities: list<string>
topic: string
vector: fixed-size list<float32>[embedding dimension]
```

数据库目录默认为 `./ariadnemem_lancedb_data`。增强索引另存为该目录下的 `enhanced_index.json`。原始 `Dialogue` 本身没有单独的持久化表；持久化边界是 LLM 抽取后的 `MemoryEntry` 和派生索引。

## 5. 关键数据流与调用路径

### 5.1 写入路径（Python）

```text
AriadneMemSystem.add_dialogue(speaker, content, timestamp)
  → 创建 Dialogue
  → AriadneMemoryBuilder.add_dialogue
  → _check_is_redundant（可配置）
  → dialogue_buffer
  → buffer 达到 WINDOW_SIZE 时 process_window
  → _generate_memory_entries
      → _build_extraction_prompt
      → LLMClient.chat_completion
      → LLMClient.extract_json
      → MemoryEntry 列表
  → _perform_graph_coarsening
  → EmbeddingModel.encode + VectorStore.add_entries
  → LanceDB table.add

AriadneMemSystem.finalize()
  → memory_builder.process_remaining
  → memory_builder.build_enhanced_index
      → VectorStore.get_all_entries
      → AggregationBuilder.build_aggregations
      → VectorStore.save_enhanced_index
  → VectorStore.load_enhanced_index
  → graph_retriever.set_enhanced_index
```

注意：`add_dialogue` 的 ID 计算使用 `processed_count + len(dialogue_buffer) + 1`；MCP 单条写入随后立即 `finalize`，批量写入可通过 `finalize=false` 延迟构建。窗口未满时对话只在内存 buffer 中，调用 `finalize` 才会处理剩余内容。

### 5.2 查询路径（Python）

```text
AriadneMemSystem.ask(question)
  → AriadneGraphRetriever.retrieve(question)
      → enhanced cache fast path（若已加载）
      → regex attribute fast path
      → _extract_target_entity
      → _hybrid_recall
          ├─ VectorStore.semantic_search
          │    └─ EmbeddingModel.encode_single(is_query=True) → LanceDB vector search
          └─ VectorStore.keyword_search
               └─ LanceDB WHERE / pandas fallback + keyword/text scoring
      → _filter_by_entity
      → _build_inference_graph
          ├─ chronological sort
          ├─ adjacent entity overlap / <6h temporal edge
          ├─ _find_bridge_node → semantic search top 5 + timestamp filtering
          └─ _discover_reasoning_paths → directed DFS
      → _rank_and_limit_nodes（目标 8–25 节点）
      → GraphPath
  → AriadneAnswerGenerator.generate_answer
      → _build_topology_context（facts / paths / bridge count）
      → prompt template + JSON response_format
      → LLMClient.chat_completion（最多 3 次）
      → extract_json → answer
      → SemanticNormalizer.normalize
  → string answer
```

`GraphPath.edges` 中的 `source`/`target` 是 `MemoryEntry` 对象而非 ID；边类型包括 `entity_link`、`temporal_flow`、`bridge_in`、`bridge_out`，`info` 用 `direct` 或 `inferred` 区分。当前建图主要连接按时间排序后的相邻节点，桥接节点是从向量库再次搜索出来的既有条目。

### 5.3 增强索引路径

```text
MemoryEntry[]
  → 按 persons/entities 分组
  → _aggregate_entity
      ├─ action_verbs + 文本模式 → event_counts / temporal_sequences
      ├─ keywords/topic/location/possessive/has/likes → attribute_sets
      └─ evidence_entries
  → _extract_relations → RelationTriple[]
  → _build_temporal_index → YYYY-MM-DD → entry_id[]
  → EnhancedMemoryIndex
  → JSON 文件
```

## 6. API、CLI、SDK 与协议面

### 6.1 Python API / SDK 入口

仓库没有 `pyproject.toml`、`setup.py` 或已发现的安装型 SDK 包；“SDK”实际是直接 import 的 Python 类：

```python
from main import AriadneMemSystem
from models.memory_entry import Dialogue

system = AriadneMemSystem(
    api_key=None, model=None, base_url=None,
    db_path=None, table_name=None, clear_db=False,
    enable_thinking=None, use_streaming=None,
    redundancy_threshold=None, coarsening_threshold=None,
    builder_model=None, answer_model=None, reasoning_mode=None,
)
system.add_dialogue(speaker, content, timestamp=None)
system.add_dialogues(dialogues)
system.finalize()
answer = system.ask(question, top_k=5)
memories = system.get_all_memories()
system.print_memories()
```

`ask` 的 `top_k` 当前在 `main.py` 中接收但没有传递给 retriever；检索上限实际来自 `config.py` 的 `SEMANTIC_TOP_K`、`KEYWORD_TOP_K` 和 `STRUCTURED_TOP_K`。

### 6.2 脚本 CLI

| 命令 | 入口 | 作用 |
|---|---|---|
| `python main.py` | `main.py` 的 `__main__` | 清库、加入示例对话、构建、打印记忆并问答 |
| `python quick_test.py` | `quick_test.py` | 导入、配置、数据集、初始化和基础功能检查 |
| `python demo_multihop.py` | `demo_multihop.py` | 基础多跳、因果链、路径统计和对比演示 |
| `python test_locomo10.py` | `test_locomo10.py` | LoCoMo 评测 |
| `python test_locomo10.py --num-samples N --parallel-questions --llm-judge` | 同上 | 限定样本、并发问题、LLM judge |
| `python test_locomo10.py --skip-build --build-only --no-save --result-file PATH --test-workers N --debug-context` | 同上 | 控制构建/评测/结果落盘/调试 |
| `cd MCP && python run.py --host HOST --port PORT --reload` | `MCP/run.py` | 启动 HTTP MCP 服务 |
| `python MCP/server/stdio_server.py` | stdio server | 运行 stdin/stdout MCP 服务，适合客户端拉起 |

### 6.3 MCP 工具与资源

`MCPHandler._handle_tools_list` 声明 7 个工具：

- `memory_add`：单条对话写入并 finalize。
- `memory_add_batch`：批量对话，可 `finalize`。
- `memory_query`：图检索 + 拓扑感知答案生成。
- `memory_retrieve`：返回检索到的原始记忆字段。
- `memory_graph_inspect`：返回节点、边、DFS 路径和摘要。
- `memory_stats`：返回条目数、对话计数、配置和模型信息。
- `memory_clear`：要求 `confirm=true` 后清空并重建系统。

资源 URI：

- `memory://ariadnemem/stats`
- `memory://ariadnemem/all`

协议方法：`initialize`、`initialized`、`ping`、`tools/list`、`tools/call`、`resources/list`、`resources/read`。

### 6.4 HTTP API

`MCP/server/http_server.py` 暴露：

| 路由 | 方法 | 语义 |
|---|---|---|
| `/api/health` | GET | 健康检查 |
| `/api/server/info` | GET | 服务、协议、模型和功能信息 |
| `/mcp` | POST | 初始化/JSON-RPC 请求/通知；初始化返回 `Mcp-Session-Id` |
| `/mcp` | GET | 以 SSE 持续输出服务端消息 |
| `/mcp` | DELETE | 删除 MCP 会话 |

HTTP 使用 `ARIADNEMEM_API_TOKEN` 的 Bearer token；默认值是开发用 token。会话由 `SessionManager` 管理，后台任务每 60 秒清理超过 30 分钟未活动的会话。CORS 当前允许任意 origin、方法和 header，生产安全边界需另行确认。

## 7. 配置、技术栈与运行时依赖

### 7.1 技术栈

| 层 | 技术/实现 |
|---|---|
| 语言 | Python（脚本式仓库，无打包入口） |
| 数据模型 | Pydantic `>=2.0.0` |
| LLM | OpenAI Python SDK `openai>=1.0.0`，兼容 OpenAI/Qwen/自定义 base URL |
| 向量/存储 | LanceDB `>=0.1.0` + PyArrow `>=12.0.0` |
| 数值 | NumPy `>=1.24.0` |
| Embedding | SentenceTransformers `>=2.2.0` + PyTorch `>=2.0.0`；支持 Qwen3 embedding |
| HTTP/MCP | FastAPI `>=0.109.0`、Uvicorn `>=0.27.0`；JSON-RPC 2.0，Streamable HTTP 2025-03-26 |
| 评测 | NLTK、ROUGE、BERTScore；另使用 SentenceTransformers 相似度 |
| 数据格式 | JSON、JSONL 风格 stdin/stdout 消息、LanceDB 表、enhanced index JSON |
| 许可证 | `LICENSE` 明确为 CC BY-NC 4.0：须署名且不得商业使用；商业许可需联系作者。依赖/上游许可证兼容性仍需另行核对 |

### 7.2 主要配置

`config.py.example` 是运行配置模板，包含：

- LLM：`OPENAI_API_KEY`、`OPENAI_BASE_URL`、`LLM_MODEL`、`BUILDER_LLM_MODEL`、`ANSWER_LLM_MODEL`。
- embedding：`EMBEDDING_MODEL`、`EMBEDDING_DIMENSION`、`EMBEDDING_CONTEXT_LENGTH`。
- 调用行为：`ENABLE_THINKING`、`USE_STREAMING`、`USE_JSON_FORMAT`、`DEBUG_LLM_CONTEXT`。
- Phase I：`WINDOW_SIZE=40`、`OVERLAP_SIZE=2`、冗余/粗化阈值和并发 worker 数。
- Phase II：semantic/keyword/structured top-k、`REASONING_MODE`，以及最大路径深度/路径数量。
- 存储：`LANCEDB_PATH=./ariadnemem_lancedb_data`、`MEMORY_TABLE_NAME=ariadnemem_entries`。
- 评测：独立 judge key/base URL/model、temperature。
- answer prompt：system、eco/pro/custom 模板。

`MCP/mcp_config/settings.py` 以 dataclass 读取环境变量中的服务配置，再尝试导入根部 `config.py` 覆盖模型、embedding、窗口、阈值和检索参数。根部没有 `config.py` 时，按源码注释需要从 `config.py.example` 复制生成；本次未生成该文件。

### 7.3 LLM 与 embedding 边界

- `LLMClient` 统一封装 chat completion；支持可选 streaming、JSON response format、Qwen DashScope 的 `enable_thinking`、最多 3 次重试和指数等待（1/2/4 秒）。`extract_json` 支持纯 JSON、代码块、嵌入式平衡对象及常见清理。
- `EmbeddingModel` 通过 SentenceTransformers 加载本地模型；Qwen3 选择 CUDA/MPS/CPU，CUDA 尝试 flash attention + FP16，失败回退标准加载；非 Qwen 模型加载默认模型。进程级模型缓存避免重复加载，实例级查询缓存上限 1000。
- LLM 负责抽取和最终语言生成；检索图的连接、桥接和 DFS 是本地算法路径。README 的“每次查询 1 次 LLM”是目标/当前 answer path 的描述，缓存命中或空图时可能为 0 次，构建阶段还会调用 LLM。

## 8. 测试、评测与验证面

### 8.1 `quick_test.py`

这是一个顺序执行的手写测试套件：

1. `test_imports`：导入主系统、模型、core、存储、LLM、embedding 和 LoCoMo 测试符号。
2. `test_config`：检查 `OPENAI_API_KEY`、`LLM_MODEL`、`EMBEDDING_MODEL`。
3. `test_dataset`：检查 `dataset/locomo10.json` 存在。
4. `test_system_init`：初始化系统并检查 6 个组件属性。
5. 前四项全绿后，`test_basic_functionality`：清理数据库、添加一条对话、finalize、检索和生成答案。

该脚本会加载 embedding/LLM 客户端，基础功能测试会清空 LanceDB；因此本次遵照只读约束未运行。

### 8.2 `test_locomo10.py`

该文件同时承担 benchmark runner 和评测库：

- 解析 LoCoMo sample、session、turn、QA、event summary、observation。
- 处理带图片 caption 的 turn。
- 指标：exact match、token F1、ROUGE-1/2/L、BLEU-1/2/3/4、BERTScore、METEOR、SentenceTransformer cosine similarity，可选 LLM judge。
- 可串行或 `ThreadPoolExecutor` 并发处理问题；支持 `skip_build`、`build_only`、限定样本数和 worker 数。
- 默认结果写入 `ariadnemem_locomo10_test_results.json`；运行时还会下载 NLTK 数据、加载评测模型、调用 LLM 和写入 LanceDB。

### 8.3 演示与测试覆盖边界

`demo_multihop.py` 覆盖的是可运行示例，不是断言式回归测试。仓库顶层未见 `tests/` 目录，也未见 pytest/unittest 配置、CI workflow 或 schema/migration 测试。当前测试主要证明“脚本能否走通”和“benchmark 指标如何计算”，未形成对门控、抽取 JSON 契约、去重、图边、桥接、DFS 上限、MCP 协议和数据清空安全性的独立单元测试矩阵。

## 9. 当前实现事实与设计宣传的差异

以下项目不能仅凭 README/论文描述判定为完整实现，应作为后续细探重点：

1. **粗化不是完整的 Merge/Link/Add 状态图。** `AriadneMemoryBuilder._perform_graph_coarsening` 当前源码实际按相似度和关键词重叠丢弃条目，未见持久化“合并结果”或显式状态更新/时间边记录；查询图的边是在读取时推导。
2. **语义归一化位置较窄。** `SemanticNormalizer` 当前由答案生成器调用，主要做输出格式归一；未见对输入实体或 `MemoryEntry` 做持久化规范名/实体消解。
3. **增强 cache 结构未完全闭环。** `QueryCache` 和 normalization rule 有模型定义，但构建器未见填充；retriever 的增强 fast path依赖实体聚合、关系和时间索引。
4. **属性 fast path 依赖缺失方法。** `AriadneGraphRetriever._try_attribute_lookup` 检查并调用 `VectorStore.query_attribute`，当前已读 `vector_store.py` 未见该方法；该路径通常会跳过并回到混合召回。
5. **MCP 文档与 handler 的字段需核对。** `memory_query` 接收 `top_k` 但 handler 未将它传入 retriever；`memory_graph_inspect` 的边源/目标在 handler 中直接取对象，而源码图边存的是 `MemoryEntry` 对象，是否能稳定 JSON 序列化尚未执行验证。
6. **并发与状态所有权未被测试证明。** builder 的 LLM 抽取可以并行，但 LanceDB 写入、增强索引保存、MCP 全局 system 和 session handler 的并发访问没有专门锁/事务测试。
7. **时间语义是字符串/启发式比较。** 时间字段通常按字符串或 `datetime.fromisoformat` 比较；相对时间在 prompt 中要求保留，但没有独立的时间类型、时区策略或有效期/版本历史模型。
8. **数据安全边界偏开发态。** 配置模板包含明文 API key 占位符；HTTP 默认 dev token，CORS 全开；`memory_clear` 是不可逆清空操作，虽有 confirm 参数，但没有审计/回滚层。
9. **README 的平台兼容性和性能数字未在本仓验证。** 本文只记录源码入口与静态调用关系，不把“Fully Tested”、性能提升、LLM 调用/延迟比较当作本地已验证事实。

## 10. 未确认项

首轮只做静态读取，以下事项明确保持未确认：

- 当前工作树中是否已有可用的 `config.py`、API key、LanceDB 数据目录或增强索引数据；本次没有创建、读取或修改运行数据。
- 实际依赖版本、Python 版本、OpenAI/Qwen 端点连通性、embedding 模型是否已下载，以及 CPU/MPS/CUDA 的真实选择。
- `http_server.py` 在当前本地依赖和 Python 版本下能否导入、FastAPI 路由是否完整启动、Bearer 鉴权和 SSE 会话是否端到端工作。
- MCP `memory_graph_inspect` 的边 JSON 序列化、`memory_query.top_k` 行为、`query_attribute` 缺失路径和异常恢复行为。
- LanceDB 空表、已有表 schema 漂移、重复 `entry_id`、并发 add/clear、进程崩溃恢复和 enhanced index 与主表一致性。
- LLM 抽取输出不完整/畸形、重复 facts、时间冲突、跨窗口关系、相对时间及多时区的真实准确率。
- `OVERLAP_SIZE` 是否应参与窗口构建；当前主 builder 读取 `WINDOW_SIZE`，未见实际窗口 overlap 逻辑。
- `AggregationBuilder` 的英文动作词和正则模式对中文、多语、否定句、被动句、复杂关系及实体同名的覆盖能力。
- benchmark 全量样本的真实指标、资源消耗、结果文件内容和论文数字复现情况。
- `LICENSE` 全文的商业/衍生使用解释及依赖/上游许可证兼容性。

## 11. 首轮代码地图（按阅读优先级）

```text
入口/编排
├── main.py
├── MCP/run.py
├── MCP/server/stdio_server.py
├── MCP/server/http_server.py
└── MCP/server/mcp_handler.py

Phase I 写入
├── core/ariadne_memory_builder.py
├── utils/llm_client.py
├── utils/embedding.py
├── models/memory_entry.py
└── database/vector_store.py

Phase II 读取
├── core/ariadne_graph_retriever.py
├── core/ariadne_answer_generator.py
├── core/semantic_normalizer.py
└── database/vector_store.py

派生索引/数据模型
├── core/aggregation_builder.py
├── models/enhanced_structures.py
└── ariadnemem_lancedb_data/enhanced_index.json（运行时生成，当前未生成）

评测/样例
├── quick_test.py
├── test_locomo10.py
├── demo_multihop.py
└── dataset/locomo10.json

配置/依赖
├── config.py.example
├── requirements.txt
└── MCP/requirements.txt
```

## 12. 当前核对边界声明

本架构建档只新增本文件；未修改源码、依赖、测试、配置或细探文件，未安装依赖，未启动服务，未执行构建/benchmark，未提交 Git，也未删除已有 `细探-AriadneMem.md`。

## 13. 旧细探吸收对照

本节记录旧细探的收口结果，避免保留两份平行架构事实源。

### 13.1 已吸收

| 旧细探内容 | 本文档落点 | 吸收方式 |
|---|---|---|
| 面向长时程 Agent 的结构化终身记忆；解决证据断裂与状态更新；写入与读取/推理解耦 | 第 1 节、第 2.1 节 | 保留为项目定位与双阶段主流程，并以当前源码的 `MemoryEntry`、LanceDB、检索图和答案生成调用链具体化 |
| `core/` 的五个核心职责：记忆构建、语义归一化、图检索、聚合、答案生成 | 第 3.2 节 | 逐一映射到真实文件和关键符号；其中 `semantic_normalizer` 的真实职责按源码收窄为答案输出归一化 |
| 图检索、多跳路径和跨记忆证据聚合 | 第 2.1 节、第 5.2～5.3 节 | 补充为混合召回、实体/时间边、桥接节点、DFS、节点预算及 `AggregationBuilder` 的派生索引路径 |
| `quick_test.py`、`demo_multihop.py`、`test_locomo10.py` 评测/演示入口 | 第 3.4 节、第 6.2 节、第 8 节 | 保留入口事实，并明确脚本测试、benchmark 与独立回归测试的边界 |
| `database/`、`dataset/`、`models/`、`utils/`、`MCP/` 作为数据、模型、工具和接入边界 | 第 3.1～3.4 节、第 6 节、第 11 节 | 按应用编排、核心算法、持久化/基础设施、评测和 MCP 协议重新分层 |
| Python、MCP 接入、论文/项目溯源和许可证需关注 | 第 1 节、第 6 节、第 7.1 节 | Python 直接集成与 stdio/HTTP MCP 已由源码展开；项目页、arXiv 和 `LICENSE` 已补入可核验信息 |

### 13.2 未直接吸收或按源码事实修正

| 旧细探表述 | 处理 | 原因 |
|---|---|---|
| `semantic_normalizer` 是“实体/语义标准形式”，承担输入实体消解/记忆规范化 | 未按原表述吸收；改以第 3.2 节、第 4.2 节和第 9.2 节的窄职责描述 | 当前源码调用点是答案生成后的格式、列表、日期、数字和大小写归一；未见输入实体或 `MemoryEntry` 的持久化规范名层 |
| “conflict-aware coarsening”可概括为完整冲突/合并状态机制 | 未按设计性表述吸收；保留第 2.1 节和第 9.1 节的相似条目过滤/去重事实 | 当前 `_perform_graph_coarsening` 未形成持久化 Merge/Link/Add 状态图，不能把宣传性机制当作已实现架构 |
| 将多跳流程直接概括为“图检索 → 聚合 → 答案生成” | 未单独重复旧流程图 | 第 2.1 节已给出源码级顺序；聚合主要在 `finalize()` 阶段构建增强索引，在线检索并非每次先调用 `AggregationBuilder` |
| “许可证未确认” | 不保留为最终事实；改为第 7.1 节的 `LICENSE` 原文结论，并保留依赖/上游兼容性待核对 | 已读取当前仓库 `LICENSE`，其中明确 CC BY-NC 4.0、署名、非商业和商业许可联系作者 |

旧细探文件未删除，仍位于仓库根目录；它不再作为本文档之外的架构事实入口。

## 14. 后续：通用底座映射边界

本节不是把 AriadneMem 的实现直接搬进平台，而是把源码中已经可复核的能力映射到平台的公共契约、记忆存储支持库、记忆推理模块和运行核心。映射依据是本仓库当前源码与第 13 节旧细探收口结果；论文、README 中的 `Merge/Link/Add`、完整状态更新和“fully tested”不能越过源码证据成为生产能力。

### 14.1 映射总图与四个归属面

```text
L4 项目适配层 / MCP / Python 门面
  → L3 记忆推理模块：写入编排、图检索、多跳、证据聚合、答案合成
  → L2 记忆存储支持库：原子记忆、向量/词法/符号索引、快照、embedding/LLM provider
  → L1 运行核心：任务、截止时间、取消、租约、句柄、崩溃恢复、事件与证据账本
  → L0 外部资源：LanceDB/文件系统、模型进程、OpenAI-compatible HTTP、MCP连接

          ┌────────────── 公共契约（跨 L0-L4 的唯一边界） ──────────────┐
          │ 请求/结果/错误码/证据引用/版本/幂等键/预算/资源释放/状态机 │
          └───────────────────────────────────────────────────────────┘
```

| 归属面 | AriadneMem 真实证据 | 后续裁决 | 不应承载的职责 |
|---|---|---|---|
| 公共契约 | `models/memory_entry.py:13-83` 的 `MemoryEntry`/`Dialogue`；`core/ariadne_graph_retriever.py:24-34` 的 `GraphPath`；`models/enhanced_structures.py:14-171` 的聚合、关系、时间和索引模型 | 吸收“结构化事实、图节点/边、证据条目、聚合视图”的概念；升级为版本化请求/结果/错误/证据引用契约 | 不把 Pydantic 模型直接当跨进程事务协议；不让 provider 对象、LLM 原始响应或 `MemoryEntry` 内部对象穿过网关 |
| 记忆存储支持库 | `database/vector_store.py:59-402` 负责 LanceDB 表、三视图索引、读写、清空和 `enhanced_index.json`；`utils/embedding.py:17-213` 管理本地模型与缓存；`utils/llm_client.py:10-283` 管理 OpenAI-compatible 调用 | 复用“dense + lexical + symbolic”检索思想；把 LanceDB、JSON 快照、embedding、LLM 变成受管 provider，统一返回结果和资源状态 | 不在支持库里编排多跳流程、答案提示词、会话、任务恢复或直接决定业务状态 |
| 记忆推理模块 | `core/ariadne_memory_builder.py:62-665`；`core/ariadne_graph_retriever.py:56-827`；`core/aggregation_builder.py:39-322`；`core/ariadne_answer_generator.py:31-318` | 以模块公开入口承载写入窗口、混合召回、桥接、DFS、聚合和拓扑合成；只通过支持库公开能力组合 | 不直接 `lancedb.connect`、不直接拥有线程池/HTTP会话、不自行定义第二套重试/错误码/取消系统 |
| 运行核心 | 当前源码只有局部线程池、FastAPI session、全局 `_system` 和普通 Python/文件状态（`MCP/server/http_server.py:38-108,146-171`），没有统一任务/资源监督 | 生产化必须由运行核心提供任务 id、预算、截止时间、取消、租约、句柄、进程组、崩溃恢复、事件和证据账本；推理模块只提交受监督的工作 | 不把 `print`、ThreadPoolExecutor、`asyncio.Queue` 或 `session_manager` 当平台级运行核心 |

### 14.2 结构化终身记忆如何归公共契约

`MemoryEntry` 是研究基线中的最小“可检索事实”：必填 `lossless_restatement`，并带 `keywords`、`timestamp`、`location`、`persons`、`entities`、`topic`（`models/memory_entry.py:21-55`）。它适合成为公共契约的**事实内容部分**，但还缺生产所需的来源、版本和治理字段。平台公共契约应拆成以下稳定对象，而不是把当前类原样外露：

| 公共对象 | 必须表达的字段/语义 | 当前实现 | 底座落点 |
|---|---|---|---|
| `MemoryWriteRequest` | `operation_id`、租户/项目/所有者、输入对话引用、幂等键、预算、截止时间、取消令牌 | `Dialogue` 只有 `dialogue_id/speaker/content/timestamp`，没有所有权、请求和幂等语义 | 公共契约；由运行核心校验后交记忆推理模块 |
| `StructuredMemory` | 稳定 `memory_id`、lossless 事实、实体/关键词/时间/地点、schema/version、来源引用、抽取器版本、置信度、状态 | `MemoryEntry` 有 UUID 和内容字段，但没有 `source_dialogue_ids`、schema 版本、confidence、状态、创建/更新时间 | 公共契约；存储支持库负责持久化和版本读写 |
| `EvidenceRef` | `memory_id`、来源制品/对话、原文区间或摘要、证据类型、生成链路、时间、置信度、可追溯版本 | `EntityAggregation.evidence_entries` 只保存 entry ID；`RelationTriple.source_entry_id` 只有单一来源 | 公共契约；证据账本/存储支持库负责权威写入 |
| `GraphEvidence` | 节点、边、边类型、direct/inferred、推理步号、路径、时间约束、来源证据集合 | `GraphPath` 的边直接保存 `MemoryEntry` 对象，`info` 只有 `direct/inferred`；无法稳定跨进程序列化 | 公共契约；推理模块只生成，网关只投影 |
| `MemoryQueryResult` | 查询、候选事实、路径、证据聚合、置信度/冲突、是否截断、预算消耗、诊断和可重试错误 | `ask()` 返回字符串；MCP query 返回答案和计数，未返回稳定证据引用/截断原因 | 公共契约；答案生成器返回统一结果，不隐去证据 |
| `MemoryTaskResult` | 任务状态（accepted/running/succeeded/failed/timed_out/cancelled/crashed）、结果引用、错误码、重试性、资源释放证据 | 当前入口无任务 id 和状态机，LLM 失败多处返回空列表或原始文本 | 公共契约 + 运行核心；不得让调用方猜异常含义 |

**裁决：**“结构化”本身吸收；`MemoryEntry` 的字段集合只能作为研究版 v0，不作为平台最终契约。尤其不能把“LLM 已抽取”当作事实可信证明：抽取结果必须带来源和证据状态，失败时必须能区分“没有事实”“抽取失败”“存储未提交”和“查询超时”。

### 14.3 图检索、多跳推理和证据聚合的归属

| 能力 | 当前实现证据 | 记忆推理模块可复用部分 | 生产缺口/公共契约要求 |
|---|---|---|---|
| 混合召回 | `_hybrid_recall` 并行调用 `semantic_search` 和 `keyword_search`，按 `entry_id` 去重（`core/ariadne_graph_retriever.py:477-523`） | dense/sparse 联合候选集和去重策略 | 需要明确召回来源、分数、排序、top-k 实际值、超时降级和部分结果标记；当前 `ask(top_k)` 未传入 retriever（`main.py:207-224`） |
| 查询图 | `_build_inference_graph` 按时间排序，相邻节点使用实体重叠或 6 小时邻近建立边（`core/ariadne_graph_retriever.py:525-609`） | 查询特定子图而非全库图、实体/时间边、节点预算 | 当前不是持久化知识图谱；边是读取时启发式推导，缺唯一 edge id、证据集合、冲突与置信度、图版本和可复现输入 |
| 桥接发现 | `_find_bridge_node` 组合实体/关键词/内容，`semantic_search(top_k=5)` 后按时间过滤（`core/ariadne_graph_retriever.py:611-705`） | 作为候选桥接策略，保留 `direct/inferred` 区分 | “Steiner tree”是近似命名，不是可证明最优解；桥接边必须标注推断而非事实，且要有候选、过滤原因、超时和成本预算 |
| 多跳推理 | `_discover_reasoning_paths` 构造有向邻接表，DFS 最大深度来自配置、路径上限来自配置（`core/ariadne_graph_retriever.py:727-806`） | DFS 路径枚举、深度/路径数量预算、路径去重 | 没有循环/爆炸保护之外的任务级截止时间、取消点、路径证据闭包、路径置信度和冲突处理；需要返回 `truncated/reason`，不能只返回列表 |
| 证据聚合 | `AggregationBuilder` 按实体生成 event counts/attributes/time sequences，关系三元组来自文本启发式，时间索引按字符串前 10 位（`core/aggregation_builder.py:39-72,74-118,243-322`） | 实体视图、关系视图、时间索引作为派生读模型 | 动作词集合以英文为主，关系可能误判，`confidence` 默认 1.0；必须保留来源集合、算法版本、重建时间、输入快照和失效状态 |
| 快速路径 | `EnhancedMemoryIndex` 有 `query_cache`/`normalization_rules`，但构建器只填实体、关系、时间索引（`models/enhanced_structures.py:121-171`） | 把聚合读模型作为可选加速器 | 不得把空实现的数据结构当能力。cache 命中必须带证据和索引版本；缓存失效、重建失败、主表与快照不一致时必须回退并报诊断 |
| 答案合成 | `_build_topology_context` 生成 `[F1]`、路径和桥接摘要，调用 LLM，失败三次后返回原始响应/固定错误（`core/ariadne_answer_generator.py:54-210`） | 拓扑上下文序列化、答案后处理、上下文 token 统计 | 应返回答案、推理/证据引用、模型版本、上下文快照、重试次数；不能用原始 LLM 文本代替结构化失败结果 |

**唯一证据链要求：**所有推理路径必须引用 `memory_id`，所有聚合字段必须可反查 `EvidenceRef`，所有答案必须绑定查询快照和推理模块版本。合成器可以隐藏内部提示词，但不能隐藏“哪些事实是 direct、哪些边是 inferred、哪些步骤被预算截断”。

## 15. 研究基线与平台生产缺口

### 15.1 研究基线（当前核对确认）

| 项目 | 基线事实 | 证据/状态 |
|---|---|---|
| 版本 | 分支 `main`，HEAD `95c77548ac37fc551babec256a9230fd03066ed3`，提交时间 `2026-03-05T10:47:03-08:00` | 本地 `git rev-parse HEAD`/`git log`；源码工作树中 `ARCHITECTURE.md` 与 `细探-AriadneMem.md` 为未跟踪研究文档，源码未改 |
| 写入 | 门控 → 窗口抽取 → 相似度去重 → LanceDB 写入；批量大于窗口条件时只并行 LLM 抽取，coarsening 和写入仍在主线程 | `core/ariadne_memory_builder.py:62-109,166-197,517-579` |
| 读取 | 增强索引快路径/属性快路径 → dense+lexical 召回 → 实体排序 → 实体/时间边 → 桥接 → DFS → 节点预算 → LLM 合成 | `core/ariadne_graph_retriever.py:56-106,477-591`、`core/ariadne_answer_generator.py:54-210` |
| 持久化 | LanceDB `ariadnemem_entries` 表 + 同目录 `enhanced_index.json`；原始 `Dialogue` 没有独立持久化表 | `database/vector_store.py:69-108,110-138,375-401`；与第 4.3 节一致 |
| 外部依赖 | OpenAI SDK、SentenceTransformers/PyTorch、LanceDB/PyArrow、FastAPI/Uvicorn 等；配置是复制 `config.py.example` 后运行 | `requirements.txt`、`config.py.example:6-10`、`MCP/server/http_server.py:22-33` |
| 验证 | 顶层只有手写 `quick_test.py`、LoCoMo benchmark 和 demo；没有发现式单元测试、CI、迁移/协议/故障矩阵 | `ARCHITECTURE.md:376-402`；当前核对未安装依赖、未启动服务、未运行 benchmark |
| 代码图 | 目标 AriadneMem 根目录存在独立 `.codegraph/`；本轮用目标目录内 CLI 状态核对 | 图谱仅作定位辅助；以下源码事实仍以直接读取为准，未调用 MCP，也不把索引状态当运行验证 |

### 15.2 生产缺口分级

| 缺口 | 当前源码现象 | 平台生产要求 | 裁决 |
|---|---|---|---|
| 契约/错误 | 大量 `except Exception` 转为空列表、`False` 或打印；MCP 未知/内部错误统一成 -32603；没有稳定业务错误码 | 公共契约固定结果形状、错误码、可重试、来源和诊断；网关/模块/provider 各只做一次转换 | 升级公共契约，禁止复制当前异常语义 |
| 来源/事实血缘 | `MemoryEntry` 无 dialogue 来源；聚合仅保 entry ID；合成节点和 synthetic fact 可能没有原始证据闭包 | 每个事实、关系、路径、答案都可追溯到不可变输入快照和证据账本 | 新增公共证据契约，存储支持库承载索引，旧结果只能作为无血缘候选 |
| 事务/一致性 | `table.add` 与 `enhanced_index.json` 分开写；clear 先 drop table 后删 JSON；无 schema 迁移、版本、原子快照或重启对账 | 事实表、派生索引、激活指针和证据记录有提交边界；失败可回滚/重建，崩溃可对账 | 升级记忆存储支持库并接运行核心事务/恢复，不直接复用 `clear` |
| 并发/所有权 | builder buffer、`previous_entries`、embedding cache 无锁；HTTP 多 session 共享全局 `_system`；`MCPHandler` 可并行调用同一系统 | 项目/所有者隔离、读写租约、单写 owner、CAS/版本校验、并发冲突错误 | 归运行核心资源协调 + 存储支持库提交协议 |
| 超时/取消 | LLM retry 使用 `sleep(1/2/4)`，无 deadline；线程池 `future.result()` 无超时；SSE queue 等待可持续；没有用户取消传播 | 每个任务有截止时间、取消令牌、级联取消、有限重试和最终状态；后台工作必须被排空/终止 | 新建运行核心监督路径，推理模块插入取消点 |
| 崩溃/重启 | 没有独立 worker、进程组、崩溃状态、恢复扫描；全局系统/会话为内存态 | 子进程隔离第三方、SIGTERM→SIGKILL、进程组回收、任务/快照/锁恢复和证据 | 归运行核心；provider 不自行发明恢复机制 |
| 资源释放 | `VectorStore` 没有 `close()`；文件用 `with` 仅覆盖增强索引；模型/线程池生命周期由 GC/上下文隐式管理；session 删除只删 dict | 成功、业务失败、超时/取消、宿主崩溃四终态均有释放和现场验证 | 建立资源契约和句柄/租约治理 |
| 图正确性 | 只连接排序后的相邻节点；边对象保存对象本身；时间用字符串/启发式；桥接 top 5；DFS 只保路径列表 | 图快照版本、稳定 edge/evidence id、可复现排序、循环/预算/冲突诊断 | 保留研究算法，升级为受契约约束的模块算法 |
| 聚合完整性 | 英文动作词和 regex 规则；`confidence=1.0` 默认；时间索引取字符串前十位；cache/rule 结构未填充 | 多语言/时区/否定/冲突/证据集合、算法版本、失效和重建状态 | 待核，先做基准数据和反例评测，不直接生产化 |
| MCP/安全 | 默认开发 token、CORS 全开、`memory_clear` 不可逆；`top_k` 只读未使用；graph inspect 直接返回对象 | 认证授权、限流、审计、幂等、危险操作二次授权、稳定 JSON schema | MCP 仅作为 L4 适配层重做，不作为平台核心入口 |
| 测试/验收 | 没有针对空输入、畸形 JSON、重复写、schema 漂移、并发、网络断开、超时、取消、SIGKILL、资源残留的独立测试 | 契约测试 + 反向破坏 + 真实 provider/子进程 + 资源残留审计 + L0-L4 验收 | 生产化前置门禁；研究指标不能替代运行验收 |

## 16. 失败、超时、取消、崩溃与资源生命周期

### 16.1 失败矩阵（源码事实与目标语义分开）

| 场景 | 当前源码路径 | 当前实际结果 | 生产目标结果 |
|---|---|---|---|
| 空输入/空图 | `process_window` 空 buffer 直接返回；`retrieve` 无候选返回空 `GraphPath`；答案生成空图返回固定字符串 | 不区分“无事实”和“前置失败” | `NO_EVIDENCE`、`INVALID_INPUT`、`INDEX_UNAVAILABLE` 分离，带 query/task/evidence snapshot |
| LLM 抽取异常/畸形 JSON | builder `_generate_memory_entries` 最多两次，失败返回 `[]`；解析失败也返回 `[]`（`core/ariadne_memory_builder.py:327-361,434-515`） | 可能静默丢窗口，调用方只看到流程继续 | `EXTRACTION_FAILED`，标明窗口、重试次数、是否写入；只允许明确的空事实结果完成 |
| 存储/embedding 异常 | `VectorStore` 搜索多处捕获后返回 `[]`；`add_entries` 不包事务 | 读失败像无召回，写失败可能在上层中断 | `STORAGE_UNAVAILABLE`/`EMBEDDING_FAILED`，写入原子性可判定，禁止把失败当空结果 |
| 桥接/图算法异常 | bridge 搜索异常直接 `None`；时间解析异常返回 `None`；路径为空也可合成 | 部分图静默降级，无降级证据 | 标记 `partial=true`、降级原因、算法预算和候选缺口；是否允许答案由契约决定 |
| 答案 JSON 失败 | 生成器最多 3 次，最终返回原始响应或 `Failed to generate answer` | 可能输出未验证 LLM 文本 | `ANSWER_SYNTHESIS_FAILED`，如允许 raw fallback 必须显式 `unstructured_fallback=true` 并保留原响应证据 |
| 参数非法/危险清空 | MCP handler 直接索引 `args["speaker"]`/`args["question"]`；clear 只检查 `confirm` | KeyError 变内部错误；clear 无回滚/审计 | 入口先做 schema/权限/范围/幂等校验；clear 走受保护命令、事务、备份/证据和恢复策略 |
| 超时 | LLM SDK 调用未设置 timeout；retry 等待固定指数；图搜索/DFS无截止时间 | 可能长时间占用请求/线程 | 运行核心 deadline 贯穿 provider、模块、网关；超时返回 `TIMED_OUT`，资源释放证据先于任务终态 |
| 主动取消 | 没有 cancel token；async handler 调同步推理；SSE generator 只捕获 `TimeoutError` | 客户端断开不会可靠停止 LLM/embedding/DFS | `CANCEL_REQUESTED`→排空/终止 provider→`CANCELLED`；不可取消的外部调用记录 `cancel_pending` 并由监督器回收 |
| 线程/宿主崩溃 | ThreadPoolExecutor 上下文退出会等待任务；全局系统和文件没有恢复状态 | 进程被杀后无任务/锁/快照对账 | 独立进程组、SIGTERM→宽限→SIGKILL、回收管道/临时目录；重启扫描未完成任务并按事务证据恢复/重试/失败 |
| HTTP/MCP 会话过期 | cleanup 只从 `_sessions` 删除；队列/handler 引用无释放钩子 | 逻辑会话消失但后台/共享系统状态不变 | session 关闭向运行核心发释放命令，排空队列、取消关联任务、记录关闭原因 |

### 16.2 四终态资源生命周期表

| 资源 | 创建/持有者（当前） | 正常完成 | 业务失败 | 超时/取消 | 宿主崩溃 | 生产验证 |
|---|---|---|---|---|---|---|
| LanceDB 连接/表 | `VectorStore.__init__` 创建并持有 `db/table`（`database/vector_store.py:69-108`） | 关闭连接/提交快照 | 回滚或标记未提交写 | 终止请求，确认连接可复用或重建 | 重启后 integrity/schema/快照对账 | 进程外读回条目、锁/临时文件为零残留 |
| 增强索引文件 | `save_enhanced_index` 的 `open(...,'w')` 写 JSON（`database/vector_store.py:375-383`） | 原子替换并记录 index version | 保留旧快照，删除不完整临时文件 | 取消时不发布半文件 | 发现临时文件/主表版本不一致则重建 | 摘要、版本、条目数、证据引用一致 |
| embedding 模型/缓存 | 全局 `_model_cache` +实例 `_cache`（`utils/embedding.py:12-39,153-176`） | 复用或显式卸载 | 不污染共享缓存 | 取消批量编码，释放批次输入 | 子进程隔离 C/GPU provider，父进程确认退出 | 进程树、GPU/文件句柄、内存趋势无界增长 |
| LLM HTTP/stream | `OpenAI` client 与 streaming iterator（`utils/llm_client.py:29-37,104-118`） | 消费完 iterator，关闭 session/provider | 有界重试，保留最后错误 | abort/close 或 provider 进程回收 | 独立进程组回收连接/管道 | socket/进程/线程不存在，错误含 retryable |
| LLM 抽取线程 | `ThreadPoolExecutor`（`core/ariadne_memory_builder.py:547-562`） | `with` 退出并收集 future | 单窗口失败需有窗口状态 | 每个 future 有 deadline/cancel/排空 | 强杀 worker 后窗口状态可恢复 | 无 `Exception in thread`、无活跃任务、窗口可重放 |
| 请求/会话队列 | `SessionManager` 为每个 session 创建 `asyncio.Queue`（`MCP/server/http_server.py:45-55`） | 正常 delete + drain | 失败 delete + 关联任务结束 | 断开触发 cancel/drain | 重启丢弃内存队列但保留持久任务证据 | 队列引用、handler、任务和 session 数回到基线 |
| 证据/快照/临时目录 | 当前没有统一 owner；JSON 直接落盘 | 事务证据与激活指针一起提交 | 失败证据不可覆盖成功证据 | 取消证据先落盘再释放 | 启动恢复扫描 orphan/未完成事务 | 逐项检查残留、大小上限和可重放性 |

**资源责任铁律：**创建者必须声明 owner；跨层转移必须显式；模块不得私自关闭共享 provider；所有释放操作必须幂等。四种终态都要有结构化证据，不以“函数返回”或 Python GC 作为释放证明。

## 17. L0-L4 分层、公共契约和唯一链路

### 17.1 L0-L4 定义

| 层级 | 平台职责 | AriadneMem 对应 | 允许依赖 | 禁止事项 |
|---|---|---|---|---|
| L0 资源/宿主 | 文件系统、LanceDB、HTTP/LLM、embedding/GPU、进程和 OS 信号 | `lancedb.connect`、OpenAI SDK、SentenceTransformer、FastAPI/Uvicorn 的实际外部边界 | 只能由受管 provider/适配器接触 | 业务模块直连外部、无超时/无释放/无资源预算 |
| L1 运行核心 | 任务状态、调度、deadline/cancel、句柄、租约、进程组、恢复、事件、证据 | 当前缺口：`ThreadPoolExecutor`、session cleanup、全局系统不能替代它 | 调用 L2 provider 和 L3 模块的公开入口 | 再建一套 provider 重试/任务状态/日志；吞掉崩溃和取消 |
| L2 记忆存储支持库 | 事实/索引/快照/版本/事务、embedding/LLM provider、统一错误 | `database/vector_store.py`、`utils/embedding.py`、`utils/llm_client.py` | 公共契约、L1 监督；可接 L0 | 编排多跳、生成最终答案、拥有网关 session |
| L3 记忆推理模块 | 结构化抽取编排、图检索、桥接、DFS、聚合、答案合成 | `core/ariadne_memory_builder.py`、`ariadne_graph_retriever.py`、`aggregation_builder.py`、`ariadne_answer_generator.py` | 只调 L2 能力，经 L1 获得任务上下文 | 直接写 LanceDB/文件、另造错误/取消/重试/证据账本 |
| L4 项目适配/接入 | Python 门面、MCP tools/resources、认证/授权/输入输出投影 | `main.py`、`MCP/server/*` | 只调 L3 公共入口和 L1 查询状态 | 以 `MCPHandler` 作为第二业务核心；绕过公共契约；危险操作无授权 |

公共契约不是第六套实现层，而是横切每个层级的唯一边界：L0 返回 provider result，L1 包成任务/资源结果，L2/L3 产生领域结果，L4 只投影稳定 JSON。任意一层新增别名必须在唯一入口归一化，不得在 MCP、Python、评测脚本分别维护一套映射。

### 17.2 AriadneMem 的唯一生产链路

```text
L4 memory_add / Python add_dialogues
  → 公共 MemoryWriteRequest（schema/权限/幂等/预算）
  → L1 运行核心创建 task + lease + deadline
  → L3 记忆推理模块.MemoryBuilder 写入编排
  → L2 记忆存储支持库.结构化记忆/Embedding/LLM 能力
  → L0 受管模型/HTTP/向量库/文件系统
  → L2 原子提交事实快照 + 派生索引 + EvidenceRef
  → L1 记录事件/释放资源/关闭 task
  → L4 返回 MemoryTaskResult

L4 memory_query / Python ask
  → 公共 MemoryQueryRequest（snapshot/version/top-k/budget/deadline）
  → L1 创建 query task + read lease
  → L3 GraphRetriever 混合召回 → 图构建 → bridge → DFS → EvidenceAggregator
  → L2 读取同一 snapshot 的 dense/lexical/symbolic/聚合视图
  → L3 AnswerGenerator 只消费 GraphEvidence，输出答案+证据引用
  → L1 记录 token/路径/资源/错误/释放
  → L4 投影 MemoryQueryResult（不直接返回 provider 对象）
```

**唯一 owner 约束：**

- 一个原子能力只有一个能力 id、一个契约 owner、一个注册/调用入口；`memory_query`、`main.ask`、评测脚本不得各自绕过模块复制检索。
- 事实快照、派生索引、证据账本、任务状态分别指定唯一写 owner；其他层只能提交命令或读公开视图。
- provider 的差异（LanceDB/其他向量库、OpenAI/Qwen/本地模型）留在 L2；L3 不按 provider 复制一套推理流程。
- 失败、超时、取消、崩溃统一由 L1 监督，L2 报告可重试与释放需求，L3 只返回领域结果，L4 不猜异常。
- 历史 `MemoryEntry`/`GraphPath` 只作为适配输入输出的兼容结构；生产链路必须先转换为公共版本化契约，不能让对象引用穿过 JSON/MCP 边界。

## 18. 吸收、升级、新建、废弃与待核裁决

| 研究能力/模式 | 裁决 | 目标落点 | 依据与限制 |
|---|---|---|---|
| 写入与在线推理解耦 | 吸收 | L3 两类模块 + L1 两类任务 | `main.py:192-227` 真实分成 `finalize` 和 `ask`；生产需加快照/任务状态 |
| 结构化原子事实 | 升级 | 公共契约 `StructuredMemory` + L2 存储 | `MemoryEntry` 字段有价值，但缺来源/版本/置信度/所有权 |
| dense/lexical/symbolic 三视图 | 吸收 | L2 记忆存储支持库 | `VectorStore` 明确实现三层；不等于已证明检索质量 |
| 实体/时间聚合 | 吸收但标研究级 | L3 聚合模块 + L2 派生索引 | 可反查 evidence 后复用；英文规则、字符串时间和默认 confidence 需升级 |
| 图检索/桥接/DFS | 吸收算法骨架 | L3 记忆推理模块 | 保留 `direct/inferred`；必须加路径证据、版本、预算和超时 |
| 拓扑上下文答案生成 | 吸收接口思想 | L3 答案合成模块 | 输出必须是公共结果，不把 raw response 当成功 |
| QueryCache/normalization rules | 待核 | L2/L3 派生读模型 | 有模型无完整写入闭环（`enhanced_structures.py:121-171`） |
| `LanceDB + enhanced_index.json` 双写 | 废弃现状，保留研究证据 | L2 事务快照/派生索引机制 | 当前没有原子提交、版本、对账；不得直接作为生产存储协议 |
| MCP 7 工具/2 资源 | 适配层复用入口名，契约需升级 | L4 MCP adapter | `mcp_handler.py:172-343,374-635` 有入口，但 `top_k`、边序列化、错误/权限不稳定 |
| README/论文的完整状态更新、Steiner 最优、fully tested | 废弃为实现事实 | 仅研究假设/评测待核 | 与第 9 节源码差异保持一致，不得写入平台能力目录 |
| 现有 retry、ThreadPoolExecutor、global session | 废弃为平台机制 | L1 监督器重写 | 只能作为局部实现线索，不能形成第二套运行核心 |

### 18.1 生产化前置工作包（仅计划，不在当前核对改平台）

1. **需求与能力登记：**登记“结构化记忆写入/快照提交”“混合记忆检索”“图证据路径”“证据聚合”“答案合成”五类需求，先搜索平台已有公共契约、存储、任务和证据能力，形成复用/升级/新建裁决。
2. **公共契约冻结：**冻结 `MemoryWriteRequest/StructuredMemory/EvidenceRef/GraphEvidence/MemoryQueryResult/MemoryTaskResult` 的版本、错误码、幂等键、预算、取消和释放字段；禁止以当前 Pydantic 对象直接替代。
3. **L2 存储支持库：**先实现事实与来源的原子写入、读取快照、派生索引重建、schema/version、CAS/幂等、关闭和损坏恢复；为 LanceDB/JSON 建独立 provider，禁止业务层直连。
4. **L1 任务与资源：**为抽取、索引重建、图检索、答案合成建立任务状态机；插入 deadline/cancel 点，监督线程/进程/HTTP/模型资源，验证四终态回收。
5. **L3 模块迁移：**将 builder/retriever/aggregator/generator 改为只依赖公共契约与 L2 入口；保存旧算法作为可切换 provider/版本，不复制第二套流程。
6. **L4 接入收口：**MCP/Python 只做 schema 校验、认证授权、请求映射和结果投影；危险清空必须受控命令并写证据，移除默认 token/CORS 全开等开发态默认。
7. **验收门禁：**先跑静态契约/导入/序列化，再做真实小数据写读；随后注入 LLM 失败、畸形 JSON、向量库断开、慢请求、客户端断开、SIGKILL 和重启恢复；最后审计任务、线程、进程、socket、临时文件、快照和锁无残留。

没有完成上述登记、能力搜索、复用决策、租约和验收契约前，本项目只能作为研究参考，不能直接改写平台生产底座。

## 19. 后续验证边界与风险

- 当前核对实际修改仅为本文件；未改 AriadneMem 源码、依赖、配置、测试、README、旧细探或 Git。
- 本轮严格未使用 MCP。目标目录已有 `.codegraph/`，已执行 `codegraph status` 与 `codegraph sync`，统计为 25 files、430 nodes、859 edges，索引最新；CodeGraph 仅用于定位，最终结论仍以源码为准。
- 未安装依赖、未创建 `config.py`、未初始化/清空 LanceDB、未调用外部 LLM/embedding、未启动 MCP/HTTP 服务，因此“研究基线”不等同于运行通过。
- 未把 `README` 的宣传性状态更新、Steiner 术语、性能/指标和兼容性声称当成验证事实；平台缺口均标为源码可见缺口或待核，不伪造生产能力。
- `ARCHITECTURE.md` 与 `细探-AriadneMem.md` 在当前 Git 工作树均是未跟踪研究文档；当前核对不提交 Git、不删除旧细探。

## 20. 本轮现场收口记录（2026-08-22）

| 项目 | 现场证据 | 结果 |
|---|---|---|
| 远程同步 | `git fetch origin --prune`、`git pull --ff-only` | `Already up to date` |
| 当前提交 | `git rev-parse HEAD` | `95c77548ac37fc551babec256a9230fd03066ed3` |
| CodeGraph | `codegraph status`、`codegraph sync` | 25 files / 430 nodes / 859 edges；Python 25，索引最新 |
| 文档行数 | `wc -l ARCHITECTURE.md` | 当前 696 行，满足 500 行要求 |
| 差异检查 | `git diff --check -- ARCHITECTURE.md` | 本轮执行退出码 0 |

本轮只修改平台研究文档，源码 checkout 未改。静态审计覆盖 `AriadneMemSystem`、`AriadneMemoryBuilder`、`AriadneGraphRetriever`、`AggregationBuilder`、`VectorStore`、`EmbeddingModel`、`LLMClient`、MemoryEntry/enhanced structures、MCP stdio/HTTP handler、quick/demo/LoCoMo 脚本及配置依赖；已将图记忆、事件/实体/时间边、混合检索、bridge/DFS、答案合成、索引双写、并发和资源缺口写入唯一 ARCHITECTURE.md。

本轮严格未使用 MCP，只使用 shell、git、CodeGraph CLI 与源码静态证据。未安装依赖、未创建配置、未运行 pytest/benchmark、未连接真实 LLM/embedding/LanceDB、未启动 MCP/HTTP、未做并发/超时/客户端断连/SIGKILL 恢复及残留扫描；这些仍是未验证项，不能将静态实现升级为 L2-L4 通过。
