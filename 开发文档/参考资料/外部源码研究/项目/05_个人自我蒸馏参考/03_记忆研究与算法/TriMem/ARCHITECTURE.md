# TriMem 架构建档

> 本文是本项目唯一持续维护的架构事实源，基于当前工作树源码、`README.md`、`LICENSE`、`细探-TriMem.md`、依赖清单、核心入口、数据模型、测试与辅助脚本的静态架构记录。
> 分析基线：Git 提交 `600a3ef`（`Update LICENSE`）。本文记录“代码实际做了什么”，不把论文/README 中的设计意图当作运行时实现证明。
> `细探-TriMem.md` 是本次归并所依据的旧细探，按用户要求保留、不删除、不改写；后续架构维护只更新本文。

## 1. 项目定位与边界

TriMem 是一个面向终身运行 LLM Agent 的 Python 记忆系统。它把对话压缩为可检索的原子事实，同时保留原始对话回链，并可选地按人物构建渐进式实体画像，从而支持事实问答与基于画像的开放域推断。

代码以本地 Python 模块组合为主，不是一个已封装的 Web 服务或可安装 SDK：

- 主要入口是 `main.py` 中的 `TriMemSystem`。
- 外部模型调用通过 OpenAI-compatible Chat Completions API 完成。
- 语义向量默认由本地 SentenceTransformers 模型生成。
- 原子事实存入 LanceDB；实体画像存入 SQLite；原始对话只保存在进程内存。
- 仓库没有 `pyproject.toml`、`setup.py`、明确的 console entry point、FastAPI 路由或 HTTP API 实现；`requirements.txt` 中的 FastAPI/Uvicorn 目前没有在核心源码中形成服务入口。

## 2. 真实目录与职责分层

```text
TriMem/
├── ARCHITECTURE.md                 # 本文；架构建档
├── README.md                       # 项目介绍、安装、Quick Start、参数与评估命令
├── 细探-TriMem.md                  # 既有细探文件；本次不删除、不改写
├── config.py                       # 全局配置默认值与 LLM/评估参数
├── main.py                         # TriMemSystem 装配根、Python 公开调用入口
├── core/                           # 应用编排与记忆算法层
│   ├── memory_builder.py           # 滑动窗口、LLM 原子事实抽取、写入、画像更新
│   ├── hybrid_retriever.py         # 规划、语义/词汇/结构化检索、合并、反思补查
│   ├── answer_generator.py         # 源对话回链、事实/推断路由、答案合成
│   └── profile_manager.py          # 按实体增量更新画像、按检索结果读取画像
├── models/                         # 领域数据模型
│   └── memory_entry.py             # Pydantic MemoryEntry 与 Dialogue
├── database/                       # 存储适配层
│   ├── vector_store.py             # LanceDB 表、向量、FTS、元数据过滤
│   ├── profile_store.py            # SQLite profiles KV 表
│   └── dialogue_store.py           # 进程内 Dict 原始对话存储
├── utils/                          # 外部能力封装层
│   ├── llm_client.py               # OpenAI 客户端、流式响应、JSON 容错解析、重试
│   └── embedding.py                # SentenceTransformer/Qwen3 向量编码与回退
├── tests/
│   └── test_vector_store.py        # LanceDB 本地/GCS 检索与优化手工测试
├── test_locomo10.py                # LoCoMo10 评估运行器、指标、可选 LLM Judge
├── test_ref/                       # 参考/旧评估实现与随仓库数据集
│   ├── locomo10.json               # LoCoMo10 数据集
│   ├── load_dataset.py             # 数据集 dataclass 与加载器
│   ├── test_advanced.py            # 另一套 AgenticMemory 评估路径（依赖外部 memory_layer）
│   └── utils.py                    # 另一套指标实现
├── scripts/
│   ├── analyze_coverage.py         # 从分析 JSON 对照问题证据与记忆覆盖率
│   └── docker-entrypoint.sh        # 容器数据目录初始化脚本（与当前 Python 主路径未接线）
├── polish_prompts.md               # 用评估结果驱动 P_ext/P_prof 的 TextGrad 风格流程
└── requirements.txt                # 134 行版本钉死依赖（末尾含 API/FTS 依赖）
```

### 分层关系

```text
调用者 / 评估 CLI
        │
        ▼
main.TriMemSystem（装配、生命周期、add/finalize/ask）
        │
        ├── core.MemoryBuilder ────────┐
        ├── core.HybridRetriever       │  应用算法/流程层
        ├── core.AnswerGenerator       │
        └── core.ProfileManager ───────┘
        │
        ├── models.MemoryEntry / Dialogue（跨层数据契约）
        ├── database.VectorStore / ProfileStore / DialogueStore（存储层）
        └── utils.LLMClient / EmbeddingModel（外部能力与模型适配层）
```

`core` 直接依赖 `database`、`utils`、`models` 与 `config`，目前没有独立的 repository interface、service container、事务边界或持久化事件层；`main.py` 是集中式装配根。

## 3. 总体流程图（text）

```text
┌──────────────────────────── 写路径：对话 → 记忆 ────────────────────────────┐
│                                                                            │
│ add_dialogue(speaker, content, timestamp)                                │
│        │                                                                   │
│        ├── 创建 Dialogue(dialogue_id, speaker, content, timestamp)         │
│        ├── DialogueStore._store[int] = Dialogue                            │
│        └── MemoryBuilder.dialogue_buffer.append(dialogue)                  │
│                    │                                                       │
│                    ├── 达到 WINDOW_SIZE(默认 40) → process_window()       │
│                    └── finalize() → process_remaining()                    │
│                                                                            │
│ [窗口切分：window=40，overlap=2，step=38]                                   │
│        │                                                                   │
│        ▼                                                                   │
│ LLMClient.chat_completion(P_ext，JSON)                                    │
│        │  有界重试；LLMClient.extract_json 容错解析                         │
│        ▼                                                                   │
│ _parse_llm_response → List[MemoryEntry]                                   │
│        │  原子事实、WHO 消歧、绝对时间、关键词/实体、源 dialogue IDs        │
│        ├── EmbeddingModel.encode_documents(lossless_restatement)           │
│        │       └── VectorStore.add_entries → LanceDB vector + metadata      │
│        └── ProfileManager.update_profiles（可选）                          │
│                └── 按 persons 分组 → 每实体一次 LLM → ProfileStore.upsert  │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────── 读路径：问题 → 答案 ────────────────────────────┐
│                                                                            │
│ ask(question)                                                             │
│        ▼                                                                   │
│ HybridRetriever.retrieve                                                  │
│        ├── 规划 LLM：问题类型/实体/所需信息 → targeted queries（最多 4 条）  │
│        ├── 语义检索：EmbeddingModel.encode_single(is_query=True)            │
│        │       └── LanceDB dense search（默认 top-k=25）                    │
│        ├── 词汇检索：LLM 解析 keywords → LanceDB search/FTS（默认 top-k=5）   │
│        ├── 符号检索：persons/entities/location/time → LanceDB where（top-k=5）│
│        ├── 按 entry_id 合并去重                                              │
│        └── 可选智能反思（默认最多 2 轮）→ 缺失信息查询 → 语义补查            │
│        ▼                                                                   │
│ ProfileManager.get_profiles_for_query（可选，纯 SQLite 读取，无 LLM）       │
│        ▼                                                                   │
│ AnswerGenerator.generate_answer                                            │
│        ├── MemoryEntry 格式化                                               │
│        ├── source_dialogue_ids → DialogueStore.get_with_context(±2 turns)   │
│        ├── INFERENCE_PATTERNS 正则 → inference prompt                       │
│        └── 否则 → factual prompt                                            │
│        ▼                                                                   │
│ LLMClient.chat_completion → extract_json → 返回 result["answer"]           │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘

┌────────────────────── 评估与提示词演进（独立闭环） ─────────────────────────┐
│ test_locomo10.py + test_ref/locomo10.json                                  │
│        → LoCoMo 对话灌入 TriMem → 逐题 retrieve + answer                    │
│        → exact/F1/ROUGE/BLEU/BERTScore/METEOR/SBERT + 可选 LLM Judge         │
│        → result JSON(detailed_results)                                     │
│        → polish_prompts.md 指导 Claude Code 小步修改 P_ext/P_prof            │
│        → 重新评估，平台期/回归/过拟合时停止                                  │
└────────────────────────────────────────────────────────────────────────────┘
```

## 4. 核心数据模型与持久化映射

### 4.1 `Dialogue`

位置：`models/memory_entry.py:76-88`。

| 字段 | 类型 | 作用 |
|---|---|---|
| `dialogue_id` | `int` | 原始对话在当前系统中的索引；`TriMemSystem.add_dialogue` 按 `processed_count + buffer 长度 + 1` 推导 |
| `speaker` | `str` | 发言者 |
| `content` | `str` | 原文内容 |
| `timestamp` | `Optional[str]` | 原始对话时间，约定 ISO 8601 但模型本身没有格式校验 |

`__str__` 将其格式化为 `[ID:n] [timestamp] speaker: content`，作为事实抽取提示的输入。

### 4.2 `MemoryEntry`

位置：`models/memory_entry.py:13-73`。这是原子记忆的跨层契约，字段分为三类索引信息与源回链：

| 字段 | 类型 | 作用与实际用法 |
|---|---|---|
| `entry_id` | `str`，UUID 默认生成 | 合并/去重键；不是数据库自增 ID |
| `lossless_restatement` | `str`，必填 | 自包含事实；用于向量化、FTS 和最终提示 |
| `keywords` | `List[str]` | 写入 LanceDB；词汇查询由 LLM 从问题中抽取关键词 |
| `timestamp` | `Optional[str]` | 事件时间元数据；结构化过滤使用字符串比较 |
| `location` | `Optional[str]` | 位置元数据；结构化过滤使用 `LIKE` |
| `persons` | `List[str]` | 实体过滤，以及画像分组/读取 |
| `entities` | `List[str]` | 公司、产品、作品等实体过滤 |
| `topic` | `Optional[str]` | 主题摘要，主要用于答案提示展示 |
| `source_dialogue_ids` | `List[int]` | 原子事实到原始对话的回链；答案阶段读取上下文 |

Pydantic 模型没有配置 `extra="forbid"`、字段级时间格式验证或自定义跨字段约束；架构上的事实质量主要由 P_ext 提示词约束，`_parse_llm_response` 只对部分 source ID 做 `int` 转换，缺失 source ID 时回退到整个窗口 ID。

### 4.3 存储模型

- **LanceDB / VectorStore**：`database/vector_store.py:53-73` 创建或打开 `memory_entries` 表。物理字段包括上述 MemoryEntry 字段加 `vector: list<float32>[dimension]`。写入前批量调用 `EmbeddingModel.encode_documents`（`121-149`）。
  - 语义视图：`table.search(query_vector).limit(top_k)`。
  - 词汇视图：`table.search(" ".join(keywords)).limit(top_k)`；首次插入后尝试创建 FTS。代码注释称 BM25，但实际依赖 LanceDB search/FTS，`rank-bm25` 未在核心源码使用。
  - 符号视图：动态拼接 `where` 条件（persons/entities `array_has_any`、location `LIKE`、timestamp 范围），见 `185-233`。
- **SQLite / ProfileStore**：`database/profile_store.py:17-29` 建立 `profiles(entity_name TEXT PRIMARY KEY, profile_text TEXT NOT NULL)`。同一实体只有一份当前文本画像；`upsert` 是可变更新，不保存画像版本、来源、时间或冲突记录。
- **进程内 / DialogueStore**：`database/dialogue_store.py:18-62` 使用 `Dict[int, Dialogue]`。支持按 ID、批量、±上下文窗口读取；重启后原始对话丢失，代码没有容量上限或持久化机制。

## 5. 分层组件详解

### 5.1 装配与生命周期：`main.py`

`TriMemSystem.__init__`（`main.py:26-111`）创建 `LLMClient`、`EmbeddingModel`、`VectorStore`、`DialogueStore`，按 `config.ENABLE_PROFILES` 动态创建 `ProfileStore` 与 `ProfileManager`，再把共享依赖注入 `MemoryBuilder`、`HybridRetriever`、`AnswerGenerator`。

生命周期：

1. 初始化即创建/打开 LanceDB 表，并初始化嵌入模型；启用画像时创建 SQLite 表。
2. `clear_db=True` 会删除并重建 LanceDB 表，同时清空内存对话和 SQLite 画像。
3. `add_dialogue` 先写原始对话，再放入构建缓冲区；达到窗口阈值会同步处理窗口。
4. `add_dialogues` 先批量写入 DialogueStore，再由 MemoryBuilder 顺序或并行处理。
5. `finalize` 只冲刷 `MemoryBuilder` 剩余缓冲。
6. `ask` 依次检索、可选读画像、生成答案，并把结果作为字符串返回。

注意：`finalize` 没有显式刷新/关闭数据库连接；也没有跨 VectorStore、ProfileStore、DialogueStore 的事务协调。

### 5.2 写算法：`MemoryBuilder`

位置：`core/memory_builder.py`。

- 默认 `WINDOW_SIZE=40`、`OVERLAP_SIZE=2`，步长为 `window_size - overlap_size`（`32-58`）。窗口达到大小时 `process_window` 消费前 `step_size` 条，形成滑动窗口。
- 小批量走顺序路径；大于 `window_size * 2` 且开启并行时，预切窗口并由 `ThreadPoolExecutor` 并行调用 LLM，再集中批量写入 VectorStore、更新画像（`69-113`、`385-418`）。并行结果按完成顺序聚合，不保证窗口顺序；单个 worker 异常只打印并跳过该窗口，只有并行编排本身抛出异常时才回退到顺序处理，不存在每个失败窗口的独立重试队列。
- `_generate_memory_entries` 构造 P_ext，要求跳过寒暄、拆原子事实、消除代词、将相对时间转绝对时间、保留具体细节，并用世界知识为描述但未命名事物补名（`155-338`）。
- LLM 响应经 `</think>` 尾部清理、`LLMClient.extract_json` 解析，再映射成 Pydantic `MemoryEntry`（`340-383`）。解析/模型错误最多重试 3 次，最终以空列表静默降级。
- 事实写入成功后，同步调用 `ProfileManager.update_profiles`（若启用）。因此画像更新不是独立队列，也不是原子事务；若画像更新失败，ProfileManager 保留旧画像，但向量写入已完成。

### 5.3 画像写/读：`ProfileManager`

位置：`core/profile_manager.py`。

- 写时按 `MemoryEntry.persons` 用 `defaultdict` 分组；每个实体读取旧文本，调用一次 P_prof，再 `ProfileStore.upsert`（`28-49`）。
- P_prof 固定十类 section：Identity、Personality、How Others Describe Them、Interests、Career、Values、Beliefs/Spirituality、Relationships、Life Events、Preferences（`62-93`）。画像是 LLM 合成文本，不是结构化事实表。
- 读时只从已检索记忆的 `persons` 收集实体并批量查 SQLite（`119-148`）；`query` 参数本身没有独立实体抽取逻辑，未被直接使用。没有画像则返回空字符串。

### 5.4 检索：`HybridRetriever`

位置：`core/hybrid_retriever.py`。

默认开启规划、反思与并行检索（以 `config.py` 为准）。`retrieve` 的实际顺序是：

1. `_analyze_information_requirements`：LLM 输出问题类型、关键实体、必需信息、关系、最小查询数；失败使用默认计划。
2. `_generate_targeted_queries`：LLM 生成定向查询，强制包含原问题，最多截取 4 条；失败只用原问题。
3. 每条查询做语义检索；多查询时可使用 `ThreadPoolExecutor`。
4. 对原问题额外做 `_analyze_query`，抽取 keywords/persons/time/location/entities；再执行词汇检索与结构化过滤。
5. 所有结果按 `entry_id` 去重合并。
6. 智能反思最多 `MAX_REFLECTION_ROUNDS`（默认 2）轮，由 LLM 判断 `complete/incomplete`，不完整时生成缺口查询并继续语义检索。失败按不完整处理，最终受轮数约束。

时间解析使用 `dateparser`，默认 `PREFER_DATES_FROM=past`；“week/周”会扩大到前后 7 天。VectorStore 的结构化条件实际是字符串 SQL-like 表达式，location 单引号进行了转义，但 persons/entities 值直接插入条件字符串，过滤安全性与跨语言时间语义仍需谨慎对待。

### 5.5 答案合成：`AnswerGenerator`

位置：`core/answer_generator.py`。

- 无检索上下文时直接返回 `No relevant information found`，不会调用 LLM。
- 有上下文时格式化 MemoryEntry；若 DialogueStore 有数据，则根据所有 `source_dialogue_ids` 取 ±`SOURCE_CONTEXT_WINDOW`（默认 2）轮，源轮用 `*` 标记。
- 用约 50 条英文正则 `INFERENCE_PATTERNS` 路由：推断/假设题走强制承诺答案的推断 prompt；其他问题走“仅依据上下文”的事实 prompt。
- 答案调用 LLM，解析 JSON 并返回 `answer` 字段；解析失败则返回原始响应字符串，最终失败返回 `Failed to generate answer`。`reasoning` 字段被提示词要求生成，但公开方法只返回 `answer`，`TriMemSystem.ask` 也只暴露这个字符串。

### 5.6 外部能力：`LLMClient` 与 `EmbeddingModel`

- `LLMClient`（`utils/llm_client.py:10-132`）包装 `openai.OpenAI` 的 `chat.completions.create`；支持自定义 base URL、模型、temperature、可选 JSON response format、流式收集、Qwen DashScope 的 `extra_body.enable_thinking`。每次调用默认最多 3 次尝试（含首次），退避为 1/2 秒。
- `LLMClient.extract_json`（`134-297`）依次尝试纯 JSON、前缀剥离、代码块、平衡括号扫描、尾逗号/注释清理。
- `EmbeddingModel`（`utils/embedding.py:11-157`）使用 SentenceTransformers。源码默认配置值是完整路径 `Qwen/Qwen3-Embedding-0.6B`，因此走标准初始化分支；只有名称以小写 `qwen3` 开头时才走 Qwen3 优化分支。Qwen3 分支支持 `trust_remote_code=True`、`flash_attention_2`、`device_map=auto` 与 query prompt；加载失败回退 `all-MiniLM-L6-v2`。文档化的 Qwen3 路径与实际分支条件存在待确认/潜在不一致。

## 6. 关键数据流与调用路径

### 6.1 单条写入

```text
TriMemSystem.add_dialogue
  → Dialogue(dialogue_id=processed_count + buffer_len + 1, ...)
  → DialogueStore.add
  → MemoryBuilder.add_dialogue
  → (buffer >= 40 ? process_window : wait)
  → _generate_memory_entries
  → LLMClient.chat_completion(P_ext)
  → LLMClient.extract_json
  → MemoryEntry[]
  → EmbeddingModel.encode_documents
  → VectorStore.add_entries
  → LanceDB table.add
  → optional ProfileManager.update_profiles
  → ProfileStore.upsert(entity_name, profile_text)
```

### 6.2 提问

```text
TriMemSystem.ask
  → HybridRetriever.retrieve
      → information-plan LLM
      → targeted-query LLM
      → semantic: embed query → LanceDB vector search
      → keyword: query-analysis LLM → LanceDB text search
      → symbolic: query-analysis metadata → LanceDB where
      → entry_id merge/dedup
      → optional completeness LLM + supplementary semantic search (≤2 rounds)
  → optional ProfileManager.get_profiles_for_query
      → persons from retrieved entries → SQLite IN query
  → AnswerGenerator.generate_answer
      → source_dialogue_ids → DialogueStore ±2 context
      → factual/inference prompt selection
      → answer LLM → JSON parser
  → answer string
```

### 6.3 外部调用量（代码路径推导）

- 每个完整窗口：至少 1 次 P_ext LLM；启用画像时，每个出现的人物至少 1 次 P_prof LLM。
- 每次普通 `ask`：规划 1 次、定向查询 1 次、原问题分析 1 次、答案合成 1 次；启用反思时可能增加完整性判断、缺口查询和补充检索调用。不同失败/配置分支会改变实际次数。
- Embedding 模型在初始化时加载；写入批次和每次语义检索都会本地编码。模型下载、API 限流与缓存不由本仓库统一治理。

## 7. API / CLI / SDK 表面

### 7.1 Python 调用 API（事实上的 SDK）

`main.py:17-224` 提供以下主要接口：

```python
from main import TriMemSystem, create_system
from models.memory_entry import Dialogue

system = TriMemSystem(clear_db=True)
system.add_dialogue(speaker, content, timestamp=None)
system.add_dialogues([Dialogue(...)])
system.finalize()
answer = system.ask(question)
memories = system.get_all_memories()
system.print_memories()
```

构造器可覆盖 API key、model、base URL、LanceDB 路径/表名、thinking/streaming、规划/反思、窗口处理并行度和检索并行度（`main.py:26-42`）。画像开关及 SQLite 路径目前主要从 `config.py` 读取，不在构造器参数中直接暴露。

这不是稳定发布版 SDK：没有版本化包元数据、类型化 HTTP contract、异步 API、连接关闭协议或向后兼容承诺；模块导入依赖从项目根运行，`models`/`core`/`database`/`utils` 也不是独立可发布包。

### 7.2 CLI / 脚本

| 命令入口 | 作用 | 关键参数 |
|---|---|---|
| `python main.py` | 初始化模型、写入示例对话、打印记忆并问答的 quick test | 源码内固定示例；依赖真实 API key 与本地嵌入模型 |
| `python test_locomo10.py` | LoCoMo10 评估 | `--dataset`、`--num-samples`、`--no-save`、`--result-file`、`--parallel-questions`、`--llm-judge`、`--test-workers`、`--skip-categories` |
| `python tests/test_vector_store.py` | 本地 VectorStore 手工测试 | `--gcs`、`--sa`；本地路径默认 `./tests/test_lancedb` |
| `python scripts/analyze_coverage.py` | 分析记忆对 LoCoMo 问题证据的覆盖 | `--analysis`、`--dataset`、`--sample` |
| `python test_ref/test_advanced.py` | 旧/参考评估路径 | `--dataset`、`--model`、`--output`、`--ratio`、`--backend`、`--temperature_c5`、`--retrieve_k`、SGLang host/port |

没有 `pytest` 配置或标准测试命令文档；`tests/test_vector_store.py` 自身实现了 `main()`，更接近可执行集成/手工测试而非 pytest fixture 测试（文件中若干测试函数带 `store` 参数，但没有本地 fixture 定义）。

### 7.3 HTTP / 容器表面

`requirements.txt` 末尾列出 `fastapi` 与 `uvicorn[standard]`，但在当前 Python 源码中未发现 FastAPI app、路由、依赖注入或 Uvicorn 启动代码。`scripts/docker-entrypoint.sh` 只负责创建/授权 `$DATA_DIR` 与 LanceDB 目录，然后以 `appuser` 执行传入命令；脚本默认路径 `/app/MCP/data` 与当前 `config.py` 的 `./lancedb_data`/`./profile_store.db` 并未在仓库中统一配置。因此当前可确认的是本地 Python API 与若干 CLI，不是可直接访问的 HTTP/容器产品。

## 8. 技术栈与依赖分组

### 8.1 运行时实际使用的主要组件

| 层次 | 技术/库 | 代码证据 | 用途 |
|---|---|---|---|
| 语言 | Python 3.10+ | `README.md:32-40` | 模块、脚本和数据处理 |
| 领域模型 | Pydantic 2.x | `models/memory_entry.py:8-13` | `MemoryEntry`/`Dialogue` 校验与序列化 |
| LLM | OpenAI Python client 2.x | `utils/llm_client.py:6,38-88` | OpenAI-compatible Chat Completions |
| 向量化 | SentenceTransformers 5.x、Transformers | `utils/embedding.py:29-95` | 本地文档/查询向量 |
| 向量库 | LanceDB 0.25.3 + PyArrow | `database/vector_store.py:10-14,53-73` | 表、向量检索与 Arrow schema |
| 词汇检索 | LanceDB FTS；本地尝试 Tantivy | `database/vector_store.py:75-98,168-183` | 关键词/全文检索 |
| 结构化时间解析 | dateparser | `core/hybrid_retriever.py:16,281-306` | 自然语言时间到范围 |
| 持久化 | stdlib `sqlite3` | `database/profile_store.py:8,17-29` | 实体画像 KV |
| 并行 | `concurrent.futures.ThreadPoolExecutor` | `core/memory_builder.py`、`core/hybrid_retriever.py` | 窗口、查询、评估问题并行 |
| 评估 | NLTK、ROUGE、BLEU、BERTScore、METEOR、Sentence-BERT | `test_locomo10.py:13-20,260-561` | LoCoMo 质量度量 |

### 8.2 清单中存在但未在核心路径证实的依赖

`requirements.txt` 共 134 行，包含大量 LangChain/LangGraph/LangMem、Anthropic、LiteLLM、Qdrant、SQLAlchemy、FastAPI/Uvicorn、`rank-bm25` 等包，但当前核心导入与运行路径未全部使用。现有细探还指出 `dydantic==0.0.8`、`dataparser==0.0.2` 疑似拼写/冗余依赖；本文不安装或验证这些依赖，仅保留为依赖卫生风险。

## 9. 测试、评估与验证边界

### 9.1 已读测试/评估资产

- `tests/test_vector_store.py`：构造 3 条 `MemoryEntry`，覆盖语义搜索、关键词搜索、persons/location/timestamp 结构化搜索、`optimize`、全量读取；另有 GCS 连接与原生 FTS 分支。测试函数直接使用外部传入 `store`，脚本 `main()` 自行建库、清库、写入测试数据、执行并打印结果。
- `test_locomo10.py`：加载 `test_ref/locomo10.json`，把会话转为 `Dialogue`，通过 `TriMemSystem` 构建记忆，逐题检索与回答；默认 CLI `--num-samples=1`、`--skip-categories=5`，可并行问题处理；生成 timing、聚合指标和 `detailed_results` JSON，可选独立 Judge LLM。
- `test_ref/load_dataset.py`：LoCoMo dataclass（QA/Turn/Session/Conversation/LoCoMoSample）与包含图像 caption 合并逻辑的数据加载。
- `test_ref/test_advanced.py` + `test_ref/utils.py`：另一套旧评估实现，依赖未随当前仓库提供的 `memory_layer`，不能当作当前 TriMem 主路径的可直接回归测试。
- `scripts/analyze_coverage.py`：读取外部的 memory construction analysis JSON，建立数据集 `dia_id` 到全局 dialogue ID 映射，按答案词汇与提取记忆的重叠率分类 COVERED/PARTIAL/MISSING。

### 9.2 本次验证状态

本次任务只进行静态读取和架构建档，未安装依赖、未启动服务、未构建项目、未运行评估或测试，因此没有可宣称的运行通过率。运行前仍需确认：OpenAI-compatible API key/base URL/model、SentenceTransformers 模型可加载、LanceDB/Tantivy 本地环境、写入目录权限以及评估指标所需 NLTK/模型缓存。

## 10. 关键路径与控制点

### 写入关键路径

1. `TriMemSystem.add_dialogue` 生成 ID 并同时保存原始对话、更新抽取缓冲。
2. `MemoryBuilder` 按滑动窗口切片；达到窗口或 `finalize` 时调用 P_ext。
3. LLM JSON 解析结果映射为 `MemoryEntry`；source ID 缺失会回退整个窗口，可能扩大证据范围。
4. `VectorStore.add_entries` 先向量化，再一次性写 LanceDB，并按首批数据初始化 FTS。
5. 画像开关打开时，ProfileManager 在向量写入后同步更新实体画像。

### 查询关键路径

1. 规划/查询分析依赖多个 LLM JSON 输出，失败时静默使用默认值或原问题。
2. 语义、词汇、结构化检索的结果集合合并后仅按 UUID 去重，没有跨视图排序/统一分数融合。
3. 反思阶段受 `MAX_REFLECTION_ROUNDS` 限制，但完整性判定与缺口查询仍依赖 LLM。
4. 源对话只来自本次进程的 DialogueStore；LanceDB 重启后仍有 source ID，但没有可用的原文存储来回链。
5. 最终 factual/inference 路由由英文正则控制；系统提示词、FTS tokenizer 与时间解析也偏英文场景。

### 失败与降级路径

- LLM 调用：`LLMClient` 有指数退避与最大重试次数，最终向上抛出；各上层模块再把异常转为空列表、默认计划、空补查、旧画像或原始响应。
- 嵌入加载：Qwen3 优化加载失败可回退标准加载；Qwen3 整体失败回退 `all-MiniLM-L6-v2`，普通模型初始化失败则抛出。
- FTS 初始化：异常只打印并保持 `_fts_initialized=False`，后续每次首写可能再次尝试；词汇查询异常返回空列表。
- 并行：并行窗口/查询失败时尽量回退顺序执行或跳过失败 future；没有任务持久化、重试队列或失败记录。

## 11. 已确认的架构风险与未确认项

### 已确认的边界/风险

- **原始证据非持久化**：DialogueStore 是无上限进程内字典，进程重启即失；这使 `source_dialogue_ids` 不能独立完成跨进程证据回链。
- **画像是单版本可变文本**：SQLite 只有实体名主键和 profile_text，没有画像历史、事实来源、时间、冲突或并发版本控制；并发读-改-写可能丢更新。
- **无统一事务**：LanceDB 写入成功后画像更新独立执行；跨三种存储没有提交/回滚协调。
- **排序/融合简单**：语义、词汇、结构化结果只做 ID 去重，没有统一相关性分数或稳定的跨视图排序。
- **结构化过滤字符串拼接**：location 有单引号转义，persons/entities 直接插值；输入边界和 LanceDB SQL-like 表达式安全性需要进一步验证。
- **提示词承担主要算法约束**：事实粒度、共指、时间解析、世界知识识别、画像 section 与事实/推断行为主要依赖英文提示词，代码契约较薄。
- **默认配置有运行风险**：`OPENAI_API_KEY` 为空、`JUDGE_API_KEY` 是占位字符串；`ENABLE_THINKING=True`、`USE_STREAMING=True` 需与 provider 能力匹配。
- **依赖与实现漂移**：依赖清单很宽，包含大量未在主路径引用的库；部分依赖名称/版本可疑，但本次未安装验证。
- **清理操作具有破坏性**：`TriMemSystem(clear_db=True)` 会 drop LanceDB 表并清空画像、内存对话；LoCoMo 评估每个 sample 也会清空 VectorStore，但没有同步清空 DialogueStore/ProfileStore 的 sample 隔离逻辑。
- **主 API 会打印内部上下文**：`TriMemSystem.ask` 打印检索上下文、画像与答案；没有日志分级、脱敏或错误码契约。

### 未确认项（需要单独的运行/环境验证）

1. 当前 `requirements.txt` 在目标 Python 版本和 macOS 环境能否完整解析安装；尤其 `dydantic`/`dataparser` 疑似异常条目。
2. `Qwen/Qwen3-Embedding-0.6B` 这个默认完整模型名是否按预期进入 Qwen3 专用分支；优化参数、`trust_remote_code` 和 fallback 在实际运行中是否可用。
3. 当前 LanceDB 版本对 `table.search(query)` 的字符串词汇查询、首次 FTS 创建与 `where(..., prefilter=True)` 的具体行为；本地与云存储分支是否一致。
4. `tests/test_vector_store.py` 在真实依赖/模型缓存下是否能完成全套本地测试，以及其 `optimize()` 调用是否与当前 LanceDB API 匹配。
5. LanceDB 表的并发写/读安全性，尤其 `_process_windows_parallel` 后的集中写入与并行评估问题访问是否会产生竞争。
6. `ProfileStore(check_same_thread=False)` 在多线程评估/并行画像更新下是否安全；当前实现没有锁和连接池。
7. `TriMemSystem.add_dialogue` 的 ID 推导在混合单条/批量、窗口消费失败、并行处理或多次 finalize 时是否始终唯一、连续。
8. `test_locomo10.py` 默认参数和 README 描述是否完全一致；例如 CLI 默认样本数、结果文件名、类别 5 跳过策略。
9. `test_ref/test_advanced.py` 所依赖的 `memory_layer` 是否来自仓库外部历史代码；它是否仍属于项目支持范围。
10. `scripts/docker-entrypoint.sh` 面向的 `/app/MCP/data`、`appuser` 与 `gosu` 是否对应某个未提交的 Dockerfile/部署工程；当前仓库未提供服务启动链。
11. 中文输入、中文时间、中文实体、非英文问句下的抽取、FTS、推断路由和日期解析质量。
12. `polish_prompts.md` 描述的“Claude Code 原位修改提示词”流程没有自动化脚本、版本快照或回滚门禁；实际操作如何保存/回退提示词尚未在代码中实现。

## 12. 结论

TriMem 的当前实现是一条清晰但集中式的“对话窗口 → LLM 原子事实 → 多视图 LanceDB 检索 → LLM 答案”流水线，并在其旁边增加一个“按人物写时合并、查询时读取”的 SQLite 文本画像层。其最有辨识度的工程机制是：

1. 以 `MemoryEntry` 为中心的语义/词汇/符号三视图索引；
2. `source_dialogue_ids` 将压缩事实回链到原始对话上下文；
3. 规划 + 反思的有界多查询检索；
4. 事实题与推断题的低成本正则路由；
5. 以评估 JSON 驱动 P_ext/P_prof 小步演进的提示词闭环。

同时，它更接近研究代码/可复现实验基线，而不是具备生产级边界的记忆服务：持久化、事务、一致性、并发安全、权限、HTTP 封装、错误契约和跨语言支持都未形成完整层。后续复用时应优先抽取上述可验证边界（数据模型、证据回链、多视图检索、反思轮数、提示词 schema），而不是直接把当前存储和静默降级策略视作生产实现。

## 13. 旧细探归并与逐项裁决

本节记录对 `细探-TriMem.md` 全文的吸收结果。裁决标准是：源码路径优先；README、论文说明和旧细探只能在源码能够对应时写入“已吸收”；仅属迁移建议、宣传性描述或当前源码无法证明的内容不升级为架构事实。旧细探文件本身保留，不能作为后续唯一事实源。

### 13.1 已吸收且补入正式架构的事实

- **提示词是主要算法契约**：`core/memory_builder.py::_build_extraction_prompt` 的 P_ext 明确跳过社交寒暄、要求 `source_dialogue_ids`、禁止代词、把相对时间换成事件时间、拆分原子事实、保留具体细节，并对描述但未命名的事物使用世界知识补名；输出字段与 JSON 数组格式由提示词规定，调用温度为 `0.1`，窗口解析最多重试 3 次。
- **画像提示词与失败回退**：`core/profile_manager.py::_update_single_profile` 的 P_prof 按实体每次一次 LLM 调用，使用十个固定 section（Identity、Personality、How Others Describe Them、Interests、Career、Values、Beliefs/Spirituality、Relationships、Life Events、Preferences），要求保留未矛盾信息、从行为综合画像；响应为空时不写入，异常时返回旧画像。
- **行为边界与资源上限**：当前没有鉴权、角色、白名单或 HTTP 权限层；`LLMClient` 直接调用 OpenAI-compatible API，Qwen3 优化分支使用 `trust_remote_code=True`，LanceDB 支持 `gs://`/`s3://`/`az://` 云路径和 `storage_options`。默认窗口处理并行度为 16、检索并行度为 8，LoCoMo 问题并行测试最多 20 worker；原始对话字典无上限，画像与 LanceDB 没有跨存储事务。
- **鲁棒解析和静默降级的真实范围**：`utils/llm_client.py::extract_json` 依次尝试直接 JSON、常见前缀、JSON/通用代码块、平衡括号扫描和尾逗号/注释清理；调用层在失败后分别回退为空列表、默认计划、空补查、旧画像或原始响应。`LLMClient.chat_completion` 自身在 1/2 秒退避后仍会抛出最后异常，不能概括为“底层吞掉所有错误”。
- **评估闭环细节**：`test_locomo10.py` 实际计算 exact/F1/ROUGE/BLEU/BERTScore/METEOR/SBERT，并可选独立 `JUDGE_*` 客户端；Judge 提示词接受时间/数值近似、粒度差异、信息子集和同义表达，最终按 1.0/0.0 记录。category 5 会随机打乱“Not mentioned in the conversation”和对抗答案的顺序、关闭 reflection，并把参考答案固定为前者；CLI 默认跳过 category 5。`polish_prompts.md` 只是要求人工运行 Claude Code、读取评估 JSON 后小步改写 P_ext/P_prof，没有自动化版本、回滚或门禁实现。
- **README/LICENSE 与仓库基线**：README 的 Quick Start、三层记忆说明、配置旋钮和 LoCoMo 命令与当前入口大体一致，但实际 CLI 默认 `--num-samples=1`，不是无条件全量运行；`LICENSE` 明确为 MIT License，版权行是 `Copyright (c) 2025 TMLR Group`。基线提交 `600a3ef` 的当前仓库只有一次提交，不能据此推断完整演进历史。

### 13.2 旧细探各主题的吸收位置

| 旧细探主题 | 裁决 | 正式文档位置与当前证据 |
|---|---|---|
| 文本流程图、三层记忆和三阶段流水线 | 吸收 | 第 2、3、6 节；`main.py`、`core/*`、`database/*` |
| `MemoryEntry`/`Dialogue` 字段、三类索引、源对话回链 | 吸收 | 第 4 节；`models/memory_entry.py`、`database/vector_store.py`、`database/dialogue_store.py` |
| 窗口 40、重叠 2、步长 38、批量并行阈值、画像写时合并 | 吸收并纠偏 | 第 5.2、6.1 节；`config.py`、`core/memory_builder.py`；单 worker 失败只跳过，不承诺独立顺序回退 |
| 规划、定向查询最多 4 条、语义/词汇/结构化检索及最多 2 轮反思 | 吸收 | 第 5.4、6.2、6.3 节；`core/hybrid_retriever.py`、`config.py` |
| 事实/推断正则路由、画像读取零 LLM、±2 轮源上下文 | 吸收 | 第 5.3、5.5、6.2 节；`core/answer_generator.py`、`core/profile_manager.py` |
| JSON 容错、重试、并行和 FTS/结构化过滤风险 | 吸收 | 第 5.6、10、11 节；`utils/llm_client.py`、`database/vector_store.py` |
| LoCoMo10、category 5、Judge、参考评估实现和覆盖率脚本 | 吸收 | 第 7、9、13.1 节；`test_locomo10.py`、`test_ref/*`、`scripts/analyze_coverage.py` |
| 依赖过宽、`keyword_search` 名称与实际 FTS 不完全一致、云存储分支、Embedding fallback | 吸收 | 第 4.3、5.6、8.2、11 节；`requirements.txt`、`database/vector_store.py`、`utils/embedding.py` |
| 对底座的八条借鉴建议 | 不作为 TriMem 运行事实吸收 | 这是旧细探的跨项目解释和迁移建议，不是本仓库的接口、实现或测试证据；仅在第 12 节保留“复用边界”这一总体结论 |

### 13.3 明确未吸收、已被源码纠正或仍待验证的内容

1. 旧细探曾写成用 `response.split(' response')` 剥除思考尾部；当前源码实际使用 `response.split('</think>')`（`core/memory_builder.py`、`core/profile_manager.py`），因此旧写法不纳入本文。
2. 旧细探把并行处理概括为失败后整体顺序回退；源码只对并行编排级异常回退，单个 future 异常在 `_process_windows_parallel` 中打印后跳过，本文已按源码改写。
3. 旧细探把 `previous_entries` 概括为固定保留最近 10 条；源码顺序路径保存上一窗口全部 entries，只有并行路径截取最后 10 条，且提示词实际只使用前 3 条，本文不重复旧的笼统表述。
4. 旧细探流程图把画像读取描述为“从检索结果收集 persons”；这与代码一致，但 `ProfileManager.get_profiles_for_query` 的 `query` 参数未被独立解析，本文按第 5.3 节记录为仅从 retrieved entries 收集实体。
5. README 项目布局引用 `polish_prompts_with_claude_code.md`，当前工作树实际文件为 `polish_prompts.md`；这是文档路径漂移，不能创建同名补充文档，也不改源码或 README。
6. 旧细探提出的中文适配、生产级错误码/事务/版本化画像、统一结果排序、持久化原始对话等均属于风险或后续设计方向；当前没有源码证据，保留在第 11 节风险/未确认项，不伪装成已实现能力。
7. 本次没有安装依赖、启动服务、调用外部 API、下载模型或运行评估；因此旧细探中任何性能、指标、并发安全和云端可用性描述都只能作为静态代码推导，不能升级为运行通过结论。

## 14. 后续深挖收口：记忆分层、抽取/更新/检索、模型/向量/数据库、资源与失败路径

本节是后续对旧细探和首轮架构事实的逐条源码复核，重点回答“分层到底落在哪些对象、谁触发抽取和更新、检索实际走哪些分支、模型/向量/数据库如何持有资源、失败后真实留下什么”。除特别注明外，证据均为当前工作树静态源码证据；当前核对没有安装依赖、调用外部模型、创建临时数据库或执行测试。

### 14.1 证据等级与当前核对口径

为避免把论文符号、README 宣称、测试文件存在和真实运行混为一谈，本文使用以下等级：

| 等级 | 含义 | 本文允许的表述 |
|---|---|---|
| **E0** | README、论文、源码注释、配置注释或旧细探的声明，尚未由实现路径独立证明 | “声明/设计意图/线索”，不能写成已实现 |
| **E1** | 当前源码可直接定位到类、函数、字段、分支或持久化语句（带 `path:line`） | “源码实现/静态确认”；不等于运行成功 |
| **E2** | 测试、评估器、脚本或 fixture 源码存在，能说明预期验证面，但当前核对未执行 | “测试资产存在/可验证入口”，不能写“通过” |
| **E3** | 当前核对在隔离环境真实执行，具有命令、退出码、实际返回值和可回读产物 | “当前核对执行确认” |
| **E4** | 真实外部 provider、云存储、模型或崩溃/取消/资源清理路径已执行并读回现场 | “集成/资源闭环确认” |

**当前核对最高等级是 E2，核心架构事实为 E1。** `README.md`/论文中的“三层记忆”“BM25”“Qwen3 优化”“反思覆盖率”等只有在对应实现路径上才升级为 E1；本仓库不存在 E3/E4 证据，不能把打印日志、测试函数名、历史指标 JSON 或 `import` 成功写成运行通过。

### 14.2 三层记忆与三种索引视图的边界

“三层记忆”与“多视图索引”是两个正交概念，不能把六个名词混成六层：

| 概念 | 实际对象 | 生命周期/写入 | 读取 | 证据等级 |
|---|---|---|---|---|
| 原始对话层（证据回链） | `DialogueStore._store: Dict[int, Dialogue]` | `TriMemSystem.add_dialogue/add_dialogues` 先写内存；`clear_db=True` 时清空 | `AnswerGenerator._fetch_source_dialogues` 按 `source_dialogue_ids` 取 ±2 个 ID | E1：`database/dialogue_store.py:18-62`、`main.py:114-139`、`core/answer_generator.py:153-179` |
| 原子事实层（主要记忆） | `MemoryEntry` 写入 LanceDB `memory_entries` 表 | 窗口抽取成功后向量化并 `table.add`；没有更新/删除接口 | `VectorStore` 三类搜索，结果重建为 `MemoryEntry` | E1：`models/memory_entry.py:13-59`、`database/vector_store.py:53-73,121-149` |
| 实体画像层（派生投影） | SQLite `profiles(entity_name PRIMARY KEY, profile_text)` | 每个窗口事实写入后按 `persons` 分组，LLM 合成文本后 `upsert` 覆盖 | 只从已召回事实中的 `persons` 做一次 `get_multiple`，不独立从问题抽实体 | E1：`core/profile_manager.py:28-49,119-148`、`database/profile_store.py:22-48` |
| 语义视图 | `vector` 固定维度 float32 列 | `EmbeddingModel.encode_documents` 生成；写入时一次性随事实加入 LanceDB | `semantic_search` 编码 query 后 dense search，默认 25 | E1：`database/vector_store.py:55-65,126-162` |
| 词汇视图 | `lossless_restatement` 上的 LanceDB FTS | 首次插入后尝试创建索引；本地 Tantivy `en_stem`，云路径 native FTS | `table.search(" ".join(keywords))`，默认 5 | E1：`database/vector_store.py:75-98,168-183`；“BM25”仅是注释/命名，实际未调用 `rank_bm25` |
| 符号视图 | `timestamp/location/persons/entities` 元数据过滤 | 与事实同批写入，无独立索引版本 | `where(..., prefilter=True)`，默认 5 | E1：`database/vector_store.py:185-233` |

因此，`source_dialogue_ids` 是**内存对象 ID 指针**，不是持久化外键；LanceDB 中的事实可在进程重启后保留，但原文不在同一持久化边界内。画像也不是事实表或版本链，而是由事实派生的单行当前文本。上述三层的“解耦”是代码对象/存储位置的解耦，不是事务一致性或恢复能力的解耦。

### 14.3 抽取、窗口消费和写时画像更新：真实状态机

```text
add_dialogue(speaker, content, timestamp)
  → 生成 dialogue_id = processed_count + len(buffer) + 1
  → DialogueStore.add（先写进程内原文）
  → MemoryBuilder.dialogue_buffer.append
  → buffer >= 40 时 process_window
      → 取前 40 条，立即从 buffer 删除前 step=38 条
      → P_ext LLM（temperature=0.1；MemoryBuilder 外层最多 3 次，每次 `chat_completion` 默认再最多 3 次）
      → extract_json + MemoryEntry 映射
      → EmbeddingModel.encode_documents
      → LanceDB table.add
      → 同步 ProfileManager.update_profiles（可选）
      → 成功才更新 previous_entries / processed_count
finalize()
  → process_remaining：抽取剩余 buffer，写 LanceDB/画像，最后清空 buffer
```

| 节点 | 输入/输出与实际动作 | 正常路径 | 失败/边界路径 | 证据等级 |
|---|---|---|---|---|
| ID 与原文接收 | `add_dialogue` 构造 `Dialogue`，ID 依赖 `processed_count + buffer_len + 1`；批量入口直接接受外部 `dialogue_id` | 同时进入内存原文和抽取 buffer | 无重复 ID 检查；失败重试、混合单条/批量、并发下唯一性未证明；批量可覆盖同 ID 原文 | E1：`main.py:114-133`、`database/dialogue_store.py:21-28` |
| 窗口切分 | `window_size=40`、`overlap=2`、`step=38`；顺序路径按阈值消费，`finalize` 处理尾窗 | 40 条窗口 + 2 条重叠上下文，继续处理 buffer | `process_window` 在调用 LLM **前**删除 buffer；若抽取返回空，`processed_count` 不增但窗口已丢；`process_remaining` 无论成功与否最后清空 buffer | E1：`core/memory_builder.py:60-153` |
| P_ext 抽取 | 拼接 `[ID:n]` 对话，最多带 `previous_entries[:3]`，要求原子事实、显式 WHO、相对时间转事件时间、世界知识命名、来源 ID | `LLMClient.chat_completion` → `_parse_llm_response` → `List[MemoryEntry]` | JSON/字段/模型异常时 MemoryBuilder 外层最多 3 次；每次 `chat_completion` 默认再最多 3 次；最终返回 `[]`；缺失或不可转整数的 source ID 不是拒绝，而是回退为整个当前窗口 ID；提示词要求不等于校验器保证 | E1：`core/memory_builder.py:155-205,207-338,340-383` |
| 向量写入 | 对每个 `lossless_restatement` 编码，组成 Arrow/LanceDB 行后一次 `table.add` | 同批写入 UUID、字段、source IDs 和向量 | 向量编码或 `table.add` 异常向上抛；没有写入任务、幂等键、回滚或部分批次记录；写成功后才进入画像更新 | E1：`database/vector_store.py:121-149` |
| 写时画像 | 按 `entry.persons` 分组，每实体一次 P_prof；读取旧文本后生成完整文本并 `upsert` | 画像更新成功覆盖同名（小写化）单行 | P_prof 异常返回旧画像；若存储 upsert 异常则向上抛；向量已写而画像可能未写，跨存储无事务；空/无 persons 的事实不触发画像 | E1：`core/profile_manager.py:28-117` |
| 并行构建 | 输入数 `> window_size*2` 才进入 `add_dialogues_parallel`；ThreadPoolExecutor 默认配置 16 | 各窗口并行抽取，完成顺序聚合，最后批量写一次 | 每个 future 异常只打印并跳过；仅外层编排异常才顺序回退；buffer 在 worker 完成前已清空，全部失败时无恢复队列；并行批次按完成顺序，不保证窗口顺序；画像更新仍在主线程批量同步执行 | E1：`core/memory_builder.py:69-113,385-472`；配置 E1：`config.py:97-103` |

**关键收口：** `processed_count` 不是“已接收/已持久化对话数”，而是只有在至少生成一个 entry 后才增加的窗口计数累加；抽取返回空时它与真实已消费窗口脱节，随后 ID 可能复用或与批量 ID 冲突。代码没有把失败窗口封装成可重试任务，也没有把原文、抽取结果、画像和索引放进一个事务。

### 14.4 检索与答案：真实调用顺序、死分支和结果语义

```text
ask(question)
  → HybridRetriever.retrieve
      ├─ planning=True：P_requirements LLM
      ├─ P_targeted_queries LLM，强制原问题在前，最多截取 4 条
      ├─ 每条 targeted query 只走 semantic_search（可并行）
      ├─ 原问题 → P_query_analysis LLM
      ├─ keyword_search（FTS） + structured_search（metadata where）
      ├─ 按 entry_id 首次出现顺序去重（不融合分数、不排序）
      └─ intelligent reflection（最多 MAX_REFLECTION_ROUNDS=2）
          → completeness LLM
          → missing-info query LLM
          → 只补 semantic_search → 再按 entry_id 去重
  → ProfileManager.get_profiles_for_query（召回 entries 的 persons → SQLite，一次，无 LLM）
  → AnswerGenerator.generate_answer
      ├─ 无 contexts：直接返回 No relevant information found
      ├─ 有 contexts：source IDs → DialogueStore ±2
      ├─ 英文正则判定 inference/factual
      └─ answer LLM → JSON answer；解析失败返回原始响应文本
```

| 检索节点 | 已确认实现 | 失败/语义缺口 | 证据等级 |
|---|---|---|---|
| 规划 | `_analyze_information_requirements` 失败返回默认 general 计划；`_generate_targeted_queries` 失败返回 `[original_query]`，成功结果插入原问题并截断为 4 | LLM 可任意返回结构；`minimal_queries_needed` 不作为硬预算；每条定向查询只做语义检索，不把定向词/实体重新送入词汇和结构化检索 | E1：`core/hybrid_retriever.py:74-127,615-750` |
| 三路召回 | semantic 默认 25，keyword 默认 5，structured 默认 5；结构化仅在 LLM 提供 persons/location/entities/time 至少一个时执行 | 各路异常在 `VectorStore` 内打印并返回空列表；主流程无法区分“没有命中”和“某路失败”；没有统一分数、RRF、稳定排序或索引版本标记 | E1：`core/hybrid_retriever.py:96-119,234-279`、`database/vector_store.py:151-233` |
| 合并去重 | `_merge_and_deduplicate_entries` 按输入首次出现顺序，以 `entry_id` 去重 | 并行 future 完成顺序会改变结果顺序；重复事实 UUID 默认随机，重试不能幂等去重；没有跨视图贡献来源或分数 | E1：`core/hybrid_retriever.py:387-399,532-565`、`models/memory_entry.py:19` |
| 反思 | 实际入口是 `_retrieve_with_intelligent_reflection`，最多 2 轮；完整性失败按 `incomplete`，补查结果只追加 semantic | `coverage_percentage` 只打印不参与停止决策；返回的 `assessment` 未枚举校验；补查数量只靠 prompt 约束；“检索失败”与“信息不全”都可能继续/终止为普通结果 | E1：`core/hybrid_retriever.py:121-127,753-922` |
| 旧反思分支 | `_retrieve_with_reflection`、`_check_answer_adequacy`、`_generate_additional_queries` 仍在源码中 | `retrieve` 当前不调用这套旧分支，不能把其逻辑当作运行路径；它是保留代码/待清理分支 | E1：`core/hybrid_retriever.py:129-170,401-517` |
| 画像读取 | 只收集召回 `MemoryEntry.persons`，SQLite `get_multiple` 一次读取；查询字符串 `query` 未参与实体抽取 | 初始召回没有人物时，即使问题点名实体也不会加载该实体画像；画像缺失直接空字符串，无命中/失败区分 | E1：`core/profile_manager.py:119-148` |
| 答案路由 | 空上下文不调用 LLM；有上下文按约 50 条英文正则路由 inference/factual，最多 3 次答案调用 | inference 提示要求“必须承诺”，可能把间接证据升级为确定回答；factual 仅靠 prompt 约束；最终公开接口只返回 `answer`，不返回 reasoning、检索分数、来源状态或错误码 | E1：`core/answer_generator.py:29-151` |
| 源文回链 | 所有召回 entry 的 source IDs 合并，按 ID 取 ±2 并去重排序；精确源轮标 `*` | 原文只在当前进程；缺失 ID 被静默跳过；跨重启 LanceDB 中仍有 entry 但答案上下文为空 | E1：`core/answer_generator.py:153-179`、`database/dialogue_store.py:38-52` |

### 14.5 模型、向量、数据库和配置边界

| 资源/组件 | 真实配置与持有方式 | 代码已证行为 | 未证/风险 | 证据等级 |
|---|---|---|---|---|
| LLM provider | `LLMClient` 直接构造 `openai.OpenAI(base_url=config.OPENAI_BASE_URL, api_key=...)`；默认 `openrouter.ai/api/v1`、`openai/gpt-4.1-mini` | Chat Completions 支持可选 JSON format、streaming；只有 base URL 含 `dashscope.aliyuncs.com` 才写 Qwen `extra_body.enable_thinking` | 无 timeout、deadline、取消、token 上限、请求幂等或 provider 错误码；默认 key 为空，配置注释与实际提交文件边界不一致 | E1：`utils/llm_client.py:10-106`；配置 E1：`config.py:14-26,38-49` |
| LLM 重试/流 | `chat_completion(max_retries=3)`；退避实际为 1/2 秒（第三次失败后抛出），不是无限重试 | streaming 由 `_handle_streaming_response` 收集全文后返回；单次失败重试同一请求 | 没有显式关闭/取消流的代码；上层各自再把异常变成空列表、默认计划、旧画像或原始回答，造成错误语义分裂 | E1：`utils/llm_client.py:79-132` |
| Embedding | 默认 `EMBEDDING_MODEL="Qwen/Qwen3-Embedding-0.6B"`，但分支只匹配 `self.model_name.startswith("qwen3")` | 默认值实际走 standard `SentenceTransformer(self.model_name)`；只有传入 `qwen3-0.6b/4b/8b` 等短名才走 `trust_remote_code=True`、可选 flash attention/device_map | README/配置的“Qwen3 优化”不是默认运行分支；标准分支失败直接抛出；fallback `all-MiniLM-L6-v2` 只存在于 Qwen 专用分支；配置 `EMBEDDING_DIMENSION=1024` 未用于建表，实际取模型 dimension | E1：`utils/embedding.py:15-95`、`config.py:28-31` |
| 向量表 | 本地默认 `./lancedb_data`，表 `memory_entries`；云路径识别 `gs://`/`s3://`/`az://` 并传 `storage_options` | Arrow schema 固定字段及 `vector` 维度；首次建表，已有表直接 open；写入后尝试 FTS | 未检查既有表 schema/维度兼容；没有版本/快照/事务标记；`clear()` drop 整表重建，破坏性强；连接关闭协议缺失 | E1：`database/vector_store.py:28-73,235-250` |
| FTS | 本地 `create_fts_index(... use_tantivy=True, tokenizer_name="en_stem")`；云端 `use_tantivy=False` | 初始化异常只打印，`_fts_initialized` 保持 False；后续 add 仍会重复尝试；keyword search 依赖 LanceDB `table.search(str)` | 非英文 tokenizer、LanceDB 版本行为、本地/云一致性未执行验证；代码注释“BM25”不是独立 BM25 实现 | E1：`database/vector_store.py:75-98,168-183`；E2：`tests/test_vector_store.py:53-62,152-161` |
| Profile SQLite | `./profile_store.db`，单连接 `check_same_thread=False`；表仅两列，`entity_name` 主键 | 参数化读取；`upsert` 每次 `commit`；画像名统一小写 | 无 close/context manager、无锁、无版本/CAS、无来源/时间/冲突记录；`check_same_thread=False` 不是并发安全证明 | E1：`database/profile_store.py:17-73` |
| Dialogue 原文 | `DialogueStore` 是每个 `TriMemSystem` 实例内的 Python dict，无文件/数据库路径 | 支持按 ID、批量、上下文邻居和 clear | 无容量上限、TTL、持久化、跨进程恢复或缺失源告警；邻居按整数 ID 推导，ID 不连续时只是过滤不存在项 | E1：`database/dialogue_store.py:18-62` |

**模型/存储收口结论：** 该项目的“模型层”不是可替换 provider 注册表，而是进程内直接持有 OpenAI client、SentenceTransformer 和 LanceDB handle；其“数据库层”是 LanceDB、SQLite、内存 Dict 三套独立写入。当前能确认的是研究代码的组合方式，不能确认默认配置可运行、云分支可用、模型降级后维度兼容或跨存储一致性。

### 14.6 资源生命周期与四类终态

| 资源 | 创建/持有者 | 正常完成 | 业务失败 | 超时/主动取消 | 崩溃/重启 | 证据等级 |
|---|---|---|---|---|---|---|
| `OpenAI` client / HTTP 流 | `LLMClient` 实例 | 返回文本；无显式 close | 重试后抛出，由上层各自降级 | 没有 deadline/cancel 参数；无法从公开 API 证明真实取消 | 进程退出由宿主处理，未见恢复/lease | E1：`utils/llm_client.py:22-41,79-132` |
| SentenceTransformer / GPU/内存 | `EmbeddingModel` 实例 | 常驻进程，批量编码 | Qwen 专用初始化可 fallback；standard 初始化失败抛出 | 无取消/卸载接口；编码异常由调用方承担 | 模型和缓存重启重建，未记录模型版本/摘要 | E1：`utils/embedding.py:15-157` |
| LanceDB 连接/表/索引 | `VectorStore` 实例 | `table.add` 后可查询；FTS 初始化标志在内存 | 批量写无事务/补偿；FTS 异常仅打印 | 检索线程无显式取消；线程池只由上下文管理器退出 | 持久表可能保留，但无写入意图/快照恢复记录 | E1：`database/vector_store.py:35-49,75-149`；并行 E1：`core/hybrid_retriever.py:532-565` |
| SQLite connection/游标 | `ProfileStore` 实例 | 单条 upsert commit | commit 异常向上抛；旧画像在 LLM 失败时保留 | 无 cancel/rollback 协议（依赖 sqlite 异常状态） | 无连接重连/版本恢复；句柄没有 close | E1：`database/profile_store.py:17-48` |
| 原文 Dict / buffer | `TriMemSystem` 与 `MemoryBuilder` | 成功 entry 后 buffer 消费，原文继续驻留内存 | 抽取空结果后窗口已从 buffer 删除；尾窗最终清空 | 无取消令牌，处理中途停止策略未实现 | 原文全部丢失，LanceDB source IDs 变悬空 | E1：`core/memory_builder.py:115-153`、`database/dialogue_store.py:18-23` |
| ThreadPoolExecutor / futures | `MemoryBuilder`、`HybridRetriever`、评估器 | `with` 块退出等待 worker 完成 | 单 future 异常只打印跳过；无失败任务持久化 | 无 `Future.cancel`、deadline 或后台 worker 反查 | 进程崩溃后无任务状态/重放 | E1：`core/memory_builder.py:391-418`、`core/hybrid_retriever.py:540-565,580-606` |
| 配置/云凭证/临时数据 | 调用方和 LanceDB SDK | 从配置读取；云路径把 `storage_options` 传入 | 无统一 secret provider、日志脱敏或权限层 | 无凭证撤销/超时治理 | 无残留审计 | E1：`database/vector_store.py:28-49`、`main.py:26-61`；安全结论未做 E3 验证 |

当前核对没有发现显式 `close()`、`finally` 资源清理、任务 lease、取消 token、事务协调器、崩溃恢复日志或残留审计。ThreadPoolExecutor 的 `with` 只能证明上下文会等待/退出，不能证明 provider 请求、future、模型内存、数据库连接和原文缓冲在四类终态都被治理。

### 14.7 失败路径矩阵：当前行为与可宣称边界

| 场景 | 当前源码行为 | 可宣称等级/结论 |
|---|---|---|
| 空窗口/空检索库 | `process_window` 空 buffer 直接返回；向量三路搜索先 `count_rows()==0` 返回 `[]`；答案返回 `No relevant information found` | E1；这是确定的空值行为，不是“正确处理所有空输入” |
| P_ext 非法 JSON/缺字段 | `extract_json` 多级尝试；MemoryBuilder 最多 3 次，最终 `[]`；缺 `lossless_restatement` 会抛异常并触发重试 | E1；无稳定错误码、无失败记录，且空列表会被上层当成可继续流程 |
| source IDs 缺失/非法 | 每项尝试 `int`；全为空时回填当前窗口所有 ID | E1；属于扩大证据范围的静默修复，不是来源校验通过 |
| LLM 限流/网络/第三方异常 | LLMClient 1/2 秒退避后抛最后异常；抽取→空列表，规划→默认计划，查询分析→默认字段，反思→`incomplete`，画像→旧画像，答案→原始响应或失败文本 | E1；错误语义不统一，不能宣称“失败不影响正确性” |
| Embedding 加载失败 | 默认完整模型名走 standard，失败直接抛；短名 Qwen 分支失败才 fallback MiniLM | E1；fallback 不是全局降级且维度/质量未运行验证 |
| 向量写成功、画像写失败 | `table.add` 后调用画像；画像异常不会撤销向量 | E1；明确存在跨存储部分提交 |
| FTS 建索引失败 | 只打印，`_fts_initialized=False`；后续批次重复尝试；keyword 查询异常返回 `[]` | E1；不能把空词汇结果解释为“没有关键词命中” |
| 单个并行窗口/future 失败 | worker 返回 `[]` 或 future 异常被打印跳过；其他窗口仍可能批量写入 | E1；无窗口级状态/重试/失败计数，批次可出现部分成功 |
| 检索一路失败 | VectorStore 捕获异常返回空路由；其余路由结果继续合并并生成答案 | E1；没有 `partial_results`/缺失路由标记，存在“降级后照常回答”风险 |
| 反思评估返回非法 assessment | `_analyze_information_completeness` 原样返回；主循环既非 complete/incomplete 就进入 else 并停止反思 | E1；coverage 数值不作为硬条件，prompt schema 无运行时约束 |
| 重复写入/重试 | `MemoryEntry.entry_id` 每次默认 UUID；无 source digest/operation idempotency | E1；同一语义重试可产生重复事实，entry_id 去重不能跨重试识别 |
| `clear_db=True` / `VectorStore.clear` | drop LanceDB 表后重建；TriMemSystem 另清 DialogueStore，画像 store 建好后再 clear | E1；破坏性清空，无确认、快照或回滚 |
| 进程崩溃/重启 | 原文 Dict 丢失；LanceDB/SQLite 可能保留已提交部分；无恢复协议 | E1；只能说“部分持久化”，不能说可恢复 |
| 超时/主动取消 | 未提供 timeout、cancel token 或公开 cancel 方法；sleep 重试不是端到端超时 | E1；E3/E4 未验证，不能宣称取消安全或无残留 |

### 14.8 后续裁决与未验证清单

**已吸收（E1，源码直接确认）：**

1. 三个记忆存储对象确实存在，但只有原子事实层落在 LanceDB；原始对话是进程内证据回链，实体画像是 SQLite 单行文本投影。
2. `MemoryEntry` 同时承载 dense/lexical/symbolic 所需字段，但三种视图只是同一事实的索引路径，不是三份独立记忆。
3. 抽取由 40/2 滑窗和 P_ext 提示词驱动；`source_dialogue_ids`、WHO 消歧、事件时间、原子事实和描述命名都属于提示词要求，运行时只做很薄的字段映射。
4. 画像是写时同步、按人物分组、每人物一次 P_prof 的读-改-写；读取画像零 LLM，但只依赖召回事实中的人物。
5. 真实检索入口是 planning → semantic targeted queries → 原问题 keyword/structured → UUID 去重 → intelligent reflection；旧 reflection 方法保留但不在当前入口接线。
6. 模型、LanceDB、SQLite 和原文 Dict 由一个集中式 `TriMemSystem` 装配，却没有统一 provider 注册、事务、close、恢复或错误契约。
7. 失败策略的共同特点是“尽量让主流程继续”，但具体降级值不同：空列表、默认计划、旧画像、空路由、原始响应；这些不是可观测的稳定失败结果。

**废弃/纠偏（以 E1 源码为准）：**

- 不把 `keyword_search` 写成已实现独立 BM25；实现是 LanceDB `table.search(str)`，FTS 是首次写入后尝试创建的 Tantivy/native 索引。
- 不把默认配置写成已启用 Qwen3 优化；`Qwen/Qwen3-Embedding-0.6B` 不满足 `startswith("qwen3")`，默认进入 standard 分支。
- 不把“并行失败整体顺序回退”写成普遍行为；只有外层编排异常才回退，单个 future 失败被跳过。
- 不把“画像按问题实体读取”写成事实；`get_profiles_for_query` 的 `query` 参数未使用，只从已召回 entries 收集 `persons`。
- 不把反思覆盖率当成算法阈值；代码只打印 `coverage_percentage`，停止依据是字符串 `assessment`。
- 不把重试当幂等、`source_dialogue_ids` 当持久化外键、`clear_db` 当可回滚清理、线程池上下文当取消/崩溃治理。

**仍待验证（没有 E3/E4，不升级为运行事实）：**

1. 目标 Python/依赖版本能否安装；`requirements.txt` 中可疑/未使用条目是否阻断环境创建。
2. 默认 OpenRouter 配置、`ENABLE_THINKING=True`、`USE_STREAMING=True` 与实际 provider 是否能成功完成 P_ext、P_prof、规划、反思和答案全链路。
3. 默认完整 Qwen3 模型名在 SentenceTransformers standard 分支的真实加载、维度、缓存和内存占用；Qwen 短名优化分支与 MiniLM fallback 的真实维度兼容。
4. LanceDB 当前版本对 `table.search(str)`、`create_fts_index`、`where(... prefilter=True)`、已有表 schema 和 `optimize()` 的实际行为；本地与云路径差异。
5. 多线程下 LanceDB 读写、SQLite `check_same_thread=False` 单连接 upsert 的真实安全性。
6. `dialogue_id` 在混合单条/批量、抽取空列表、重复 finalize、并行批次中的实际碰撞情况。
7. 真实失败注入后的残留：流、线程、连接、模型内存、临时目录、部分 LanceDB 行、SQLite 事务状态。
8. 中文输入、中文时间、中文实体、中文问句在 P_ext、FTS、dateparser、英文 inference regex 下的质量与误路由。
9. LoCoMo 评估的实际指标、类别 5 默认跳过行为、Judge provider 和结果文件是否可重现；当前只有 E2 测试/评估源码证据。

**后续结论：** TriMem 的研究价值在于把“事实压缩、源回链、人物画像、三视图召回、有限反思补查”组合成一条易读的实验链；其工程边界则是“内存原文 + LanceDB 事实 + SQLite 文本画像”的三套非事务存储，以及由 prompt/静默降级承担的大量语义。可吸收的是分层概念、字段契约候选和检索编排；不可直接吸收的是当前的内存唯一原文、无幂等写入、无版本画像、无统一错误、无 deadline/cancel、无跨存储一致性和无崩溃恢复。后续维护以本节和本文为唯一事实源，旧 `细探-TriMem.md` 仍仅作为已保留研究材料。

## 15. 后续：底座映射与复用/缺口裁决

本节是后续底座映射，不是对 TriMem 现状的生产化背书。结论只依据本项目源码与系统工程平台当前的支持库/模块总览；系统工程平台没有现成的“记忆”正式支持库或模块，因此下列“新落点”都是候选需求，必须先经过需求登记、能力搜索、复用决策、占用租约、验收契约和装配计划，不能直接开工或把 TriMem 代码复制进平台。

### 15.1 可复用能力与一致性/失败语义缺口

| TriMem 能力/事实 | 可复用部分 | 不能复用或缺失的底座语义 | 唯一归属裁决 |
|---|---|---|---|
| `MemoryEntry` 的 `lossless_restatement`、关键词、实体、时间、人物、主题、`source_dialogue_ids` | 字段/JSON 序列化可借鉴 `支持库/后端/数据交换`，文本归一化可借鉴 `支持库/后端/文本处理`，事件时间规范化可借鉴 `支持库/后端/时间日期` | 当前 Pydantic 模型未 `extra="forbid"`，时间/ID/来源存在性无严格约束，LLM 缺来源时把整个窗口当来源（`models/memory_entry.py:13-73`、`core/memory_builder.py:340-383`）；没有版本、幂等键、内容摘要、租户/所有者、证据状态和冲突语义 | 新建唯一公共契约 owner：`公共契约/记忆契约`（候选），不得由模块或存储库各自定义 `MemoryEntry` |
| 对话→记忆的滑动窗口：`WINDOW_SIZE=40`、重叠 2、步长 38，`finalize` 冲刷尾窗 | 窗口参数校验、列表分片可复用 `支持库/后端/数据集合` 的纯计算能力 | 窗口消费先从缓冲移除，LLM/写库失败后可能丢失窗口；并行窗口按完成顺序聚合，窗口顺序不稳定；`processed_count` 只有有 entries 时才增长，失败窗口没有可恢复任务记录（`core/memory_builder.py:60-153,385-418`） | 唯一流程 owner：新建 `模块库/记忆`；滑窗属于记忆构建流程，不下沉为通用数据集合能力 |
| 语义、词汇、结构化三路检索及按 `entry_id` 去重 | 结果集合、参数校验和统一结果形状可借鉴 `支持库/后端/数据集合`、`支持库/后端/数据交换`；资源目录/摘要/CAS/锁借鉴 `支持库/后端/资源管理` | 当前只有去重，没有统一分数、稳定排序、索引版本、快照一致性或查询可重复性；`VectorStore` 将 `persons/entities` 直接拼入 where 字符串，LanceDB 表与原文回链没有同一提交边界（`core/hybrid_retriever.py:97-127,308-324`、`database/vector_store.py:121-149,185-233`） | `模块库/记忆` 唯一拥有检索编排；候选原子存储能力归 `支持库/后端/记忆存储`，LanceDB 只能是其唯一受管提供者，不另建第二个检索模块 |
| 规划、定向查询、最多 2 轮反思补查 | 有界轮数、查询去重和并行任务的形状可借鉴运行核心任务/资源监督语义；LLM JSON 容错可借鉴统一模型提供者的结果转换 | 规划/完整性判断/缺口查询失败都降级为默认计划、不完整或空补查，没有稳定错误码、预算、deadline、取消令牌、反思证据和“补查没有改变结果”的状态；反思最多轮数不是总请求数/Token/时间预算（`core/hybrid_retriever.py:121-170,401-517`） | 仍由 `模块库/记忆` 编排；模型调用必须经过平台唯一能力调用器和受管 LLM 提供者，禁止模块继续直接持有 `openai.OpenAI` |
| 原始对话回链与 ±2 轮源上下文 | 上下文窗口是可复用的纯选择算法；临时文件/快照/释放可复用 `支持库/后端/资源管理` | `DialogueStore` 是无界进程内 Dict，重启后 `source_dialogue_ids` 变成悬空指针；ID 由计数+缓冲长度推导，混合写入/失败重试/并发下唯一性未证明（`database/dialogue_store.py:12-62`、`main.py:116-133`） | 原始对话与记忆条目的权威写入、来源存在性和窗口读取归 `支持库/后端/记忆存储`；上下文拼装仍归 `模块库/记忆` |
| 人物画像写时合并、查询时读取 | SQLite 参数化查询与基本连接关闭可借鉴平台数据库适配边界 | `ProfileStore.upsert` 是单行可变覆盖，无版本、来源、CAS、冲突、事务关联；向量写入成功后画像更新失败会形成跨存储分裂（`core/memory_builder.py:127-153`、`database/profile_store.py:17-73`） | 画像是否纳入第一版由需求裁决；若纳入，仍由 `支持库/后端/记忆存储` 统一拥有画像快照/版本写入，不准保留独立 `ProfileStore` 写链 |
| LLM/Embedding/流式输出/重试 | 平台已有 `支持库/适配层/本地LLM提供者` 可作为本地模型边界参考；统一请求、截止时间、取消、输出上限和释放证据可复用运行核心约定 | TriMem 直接构造 `openai.OpenAI`，重试为固定 1/2 秒且没有请求 deadline/取消/幂等键/输出上限；Embedding 在主进程加载模型，fallback 可能改变向量维度/语义；流式迭代无取消与连接关闭契约（`utils/llm_client.py:10-132`、`utils/embedding.py:11-157`） | 远端 OpenAI-compatible 与本地模型必须分别登记为受管 provider 策略；`模块库/记忆` 只调用统一能力，不复制客户端；LanceDB/Embedding 若采用第三方，各自一发行包一支持库/提供者 |

**裁决摘要：**“条目契约、滑窗、三路检索、反思补查、源上下文拼装”是可提炼的研究能力；“持久原文、索引与原文的提交一致性、画像版本、幂等、失败可恢复、超时/取消、崩溃清理和证据链”不是当前实现能力，而是底座必须补齐的语义。不能因为算法路径可复用，就把 LanceDB/SQLite/进程内 Dict 的现状判定为可复用存储实现。

### 15.2 唯一落点与单链路装配计划

平台侧只允许形成下面一条候选链路；以下目录目前均未在 TriMem 本项目内创建，也未在当前核对修改平台：

```text
调用方
  → 模块库/记忆（唯一流程 owner）
  → 运行核心唯一能力调用器
  → 支持库/后端/记忆存储（唯一记忆持久化与索引抽象 owner）
  → 支持库/适配层/LanceDB提供者（若最终选用，唯一 LanceDB 技术边界）
  → 受管向量/词法/结构化索引与持久化介质
  → 统一结果、事件、版本、证据和资源释放
```

落点职责冻结如下：

1. `公共契约/记忆契约`（候选）：冻结 `Dialogue`、`MemoryEntry`、`MemorySource`、`ProfileSnapshot`、`RetrievalQuery`、`RetrievalHit`、`ReflectionRound`、操作结果、错误码、版本、幂等键、截止时间和取消令牌。任何模块不得再定义同名数据契约。
2. `支持库/后端/记忆存储`（候选）：只提供追加原始对话、追加记忆条目、来源引用校验、版本化画像快照、读取上下文窗口、三视图查询、索引快照/恢复和幂等提交等原子能力；不负责 LLM 提示词、窗口编排、答案生成或反思策略。
3. `支持库/适配层/LanceDB提供者`（候选且待需求确认）：仅封装 LanceDB 连接、索引、查询、事务/快照能力和第三方异常转换；不得被 `模块库/记忆` 直接导入。若选择其他向量库，替换 provider，不能新增第二个记忆存储 owner。
4. `模块库/记忆`（候选）：唯一编排“滑动窗口→抽取→提交”“规划→三路检索→稳定融合→反思补查”“来源上下文→答案”的公开流程；只通过能力 id 调用 `记忆存储` 与受管模型能力。
5. 既有 `支持库/后端/资源管理`、`数据交换`、`文本处理`、`时间日期` 只作为依赖复用，不承接记忆领域状态；既有 `支持库/适配层/本地LLM提供者` 只可作为本地模型策略候选，不能替代远端 OpenAI-compatible provider。

装配前置条件：先完成能力搜索和复用裁决，再冻结契约/错误码/资源预算；然后登记 `记忆存储` 与 `记忆` 的包声明、依赖锁、验证场景和完整性摘要；最后通过冷启动装配和唯一注册表调用。TriMem 当前的 `main.TriMemSystem`、`MemoryBuilder`、`HybridRetriever`、`VectorStore` 不得直接成为平台正式实现或第二条兼容链。

### 15.3 资源生命周期与权威一致性要求

| 资源 | 创建/持有者 | 正常完成 | 业务失败 | 超时/主动取消 | 宿主崩溃/重启后的要求 |
|---|---|---|---|---|---|
| 对话与记忆条目 | `记忆存储` 创建并持有持久记录；模块只持有不可变引用 | 原文、条目、来源引用、索引状态和版本证据可读 | 校验失败不写半条目；已提交原文不得因抽取失败丢失，记录可重试任务 | 取消抽取不撤销已提交原文；未提交任务进入可恢复状态 | 依据幂等键/输入摘要恢复，不重复条目、不留下悬空 `source_dialogue_ids` |
| 向量/词法/结构化索引 | provider 创建；`记忆存储` 持有索引版本/快照引用 | 索引版本与权威条目版本一致或有明确可见滞后状态 | 索引失败不能把“已索引”写成成功；允许重建，查询返回索引不可用/滞后而非伪造命中 | 停止当前索引任务并释放连接/线程；不切换半成品索引 | 从最后一个完整快照恢复，重放未完成索引任务；不得出现条目存在但来源/索引指针无主记录 |
| LLM/Embedding 执行单元 | 运行核心监督器创建；调用器持有 execution/lease，模块不持有第三方对象 | 返回统一值、provider 版本、用量/截止时间和释放证据 | provider 异常转稳定错误码；重试受幂等键和预算约束 | deadline 到达真实取消；线程/进程/网络流排空，取消不可报告为成功 | 进程/连接重启后旧 lease 失效；监督器回收临时目录、端口、句柄和未完成请求 |
| 画像快照 | `记忆存储` 创建不可变版本；模块提交新版本意图 | CAS/版本条件成立后发布新快照，旧版本可查询 | 版本冲突返回冲突并保留旧版本；不得 `upsert` 覆盖并吞掉并发更新 | 取消不发布半快照，临时构建物删除 | 重启按提交记录恢复激活版本，不能以半写文件或最后一次内存对象为准 |
| 临时文件、缓冲、线程与任务 | 资源协调/监督器登记；创建者声明持有者 | finally/回调释放，释放证据写入调用结果 | 异常路径同样释放；二次释放幂等 | 取消先停止生产者再排空消费者，最后释放；超时不可遗留后台 future | 强杀后通过独立进程组、目录、端口、句柄和任务表反查零残留 |

**跨存储提交顺序：** 先持久化原文和不可变输入摘要，再提交抽取任务/记忆版本意图；记忆条目、来源引用、索引版本和画像快照必须由同一权威状态记录关联。任何“VectorStore 已写、ProfileStore 后写”的当前顺序只能算研究代码的部分成功，不能作为平台事务模型。

### 15.4 失败、超时、取消与一致性矩阵

| 场景 | 当前 TriMem 行为 | 底座必须固定的结果语义 |
|---|---|---|
| 空对话/非法条目/缺失 `lossless_restatement` | Pydantic/LLM 解析异常通常转空列表或重试，错误原因不形成稳定记录 | `INVALID_ARGUMENT`，不改变窗口游标；输入拒绝可观测且可安全重试 |
| LLM 返回非法 JSON/缺字段/错误来源 ID | 外层最多 3 次（每次 `chat_completion` 默认最多 3 次）后返回 `[]`；来源缺失扩大为整个窗口 | `PROVIDER_INVALID_RESPONSE` 或 `CONTRACT_VIOLATION`；保留原文和失败证据，禁止无声丢窗/扩大来源 |
| LLM/Embedding 不可用、限流、网络断开 | LLM 重试后向上抛，构建/规划层分别变空列表/默认计划；Embedding 普通初始化失败直接抛 | provider 不可用、限流、网络失败、模型缺失分码；`retryable`、预算和幂等键由调用器统一决定 |
| 单个并行窗口/future 失败 | 打印后跳过；批次仍可能集中写入其他窗口，`processed_count` 可能与实际窗口不一致 | 每个窗口独立 task/状态/输入摘要；成功、失败、取消分别记账，可从失败窗口重试，不能以批次成功掩盖局部失败 |
| LanceDB 写成功、画像写失败 | 已写向量，画像保留旧值，跨存储分裂 | 要么同一提交协调，要么返回 `PARTIAL_COMMIT` 并可对账/补偿；禁止统一返回成功 |
| 重复写入/重复请求 | UUID 默认随机；没有幂等键，重试可能重复事实 | 由 `source_digest + operation_id` 或显式幂等键去重；相同摘要幂等成功，不同摘要冲突 |
| 检索某一路失败 | VectorStore 各路异常打印并返回空列表，最终可能以不完整结果正常回答 | 返回部分结果时必须带缺失路由、索引版本和完整性标记；反思不得把“检索失败”误判为“没有相关事实” |
| 反思判定/缺口查询失败 | 判为 `insufficient` 或返回空补查，最多 2 轮后继续 | 反思轮次、原因、查询、增量命中和停止原因必须入证据；超过 deadline/预算返回 `REFLECTION_BUDGET_EXCEEDED` 或部分成功 |
| 超时 | 当前只有重试 sleep，没有端到端 deadline，也没有真实取消 | 截止时间沿调用链传递；取消模型请求、查询任务和索引任务，回收所有资源；返回 `TIMEOUT`，可重试性明确 |
| 主动取消 | 没有取消参数/令牌；线程池 future 只等待完成 | `CANCELLED` 与业务失败、超时区分；取消后不得发布新版本，已提交事实保持可读，后台任务和 lease 必须结束 |
| 进程崩溃/重启 | 原文内存丢失，画像/向量可能半完成，恢复协议不存在 | 通过状态机/快照/日志恢复到“旧版本或新版本”之一；旧 lease 失效；重放幂等；残留进程/目录/端口为零 |

### 15.5 L0-L4 验证契约

当前核对只完成 L0 的静态映射与证据归档；L1-L4 是候选底座落地后的验收门槛，不得把当前 TriMem 的打印日志、静态可导入或研究评估 JSON 当作通过证据。

| 等级 | 目标与必须证明 | 典型证据/命令 | 当前状态 |
|---|---|---|---|
| L0 静态事实与边界 | 源码路径、条目字段、窗口/检索/反思调用链、现有存储和明确缺口；支持库/模块唯一 owner 不冲突；禁止直接把声明当实现 | `ARCHITECTURE.md` 第 2-15 节；对 `models/`、`core/`、`database/`、`utils/` 的逐路径复核；平台 `项目说明.md` 与 `开发工具/项目编译/正式包索引.py` 的当前能力/边界事实 | **当前核对完成**；TriMem 根目录存在独立 `.codegraph/`，CLI 状态可读；图谱仅作定位辅助，未伪造运行验证 |
| L1 纯契约/算法 | 严格校验 `MemoryEntry`/Dialogue/查询/错误结果；滑窗边界、重叠、尾窗、重复输入、空输入、来源引用、三路去重、反思轮数和稳定排序可重复 | 未来 `测试中心/记忆/测试_记忆契约.py`（标准库 unittest）；纯函数测试不触碰正式存储；非法 JSON/缺来源/非法时间必须失败而非静默扩大范围 | **未实现/未验证**；当前 Pydantic 与算法不满足全部门槛 |
| L2 隔离存储/资源 | 独立临时目录中真实写入原文、记忆、画像和索引；重开可读；幂等重放不重复；版本冲突/CAS、部分写入、索引滞后和回滚可读；finally 后线程/连接/临时目录零残留 | 未来 `python3.14 测试中心/运行测试.py --测试文件 测试中心/记忆/测试_记忆存储.py`；每例独立临时根，结束后目录/句柄反查 | **未实现/未验证**；当前 DialogueStore 进程内，TriMem 三存储无事务 |
| L3 真实 provider/运行治理 | 通过唯一注册表/调用器/模块公开入口，使用真实受管 LanceDB/Embedding/LLM provider；端到端 deadline、取消、provider 断线/崩溃、有限重试、输出上限、进程组和 lease 回收均真实发生 | 未来工作包测试：冷启动制品装配 + 真实 provider 探针 + 故障注入；禁止直接 `from ...实现...`、测试预注册或 mock 返回冒充成功 | **未实现/未验证**；当前直接依赖 `openai`、SentenceTransformers、LanceDB |
| L4 发布/反向破坏/恢复 | 删除契约/注册入口/能力声明/提供者/索引快照任一项，生产调用必须失败；强杀窗口任务/检索/模型/索引后能恢复且无半激活；跨版本回放输出稳定；调用、失败、取消、释放证据完整 | 未来 `python3.14 测试中心/运行测试.py --范围 全部`、`python3.14 开发工具/发布门禁/运行发布门禁.py`；附独立进程强杀、重启对账、残留审计和制品摘要 | **未实现/未验证**；本项目没有平台装配、发布门禁或崩溃恢复链 |

L0 之外的门槛必须以真实退出码和可回读产物为准：`skip`、日志打印、历史 LoCoMo 指标、测试文件存在、仅 `import` 成功或子代理自报均不能替代 L1-L4。若最终只复用算法而不建设一致性层，裁决应为“研究能力吸收、生产存储/失败语义待核”，不能标记为“底座已接入”。

### 15.6 后续结论

- **吸收：** `MemoryEntry` 的字段分组与源回链概念；40/2 滑窗；语义/词汇/结构化三路检索；规划、有限反思补查；源上下文窗口；这些属于 `模块库/记忆` 可复用的流程与契约候选。
- **升级：** 通用 JSON/文本/时间/集合处理复用既有支持库；原子写入、CAS、短锁、快照和安全释放复用 `支持库/后端/资源管理`；模型/第三方库改走唯一受管 provider。
- **待核/缺口：** `支持库/后端/记忆存储`、`支持库/适配层/LanceDB提供者`、`模块库/记忆` 尚未登记、实现或验证；条目严格契约、原文持久化、跨存储一致性、版本画像、索引快照、幂等、失败/超时/取消/崩溃语义、调用证据和 L1-L4 全部待核。
- **废弃/隔离：** 不吸收 TriMem 当前 `DialogueStore` 内存唯一存储、直接 `openai.OpenAI`、无 deadline 的重试、LanceDB/SQLite 分裂写、打印式错误和“失败返回空集合”的生产语义；它们只能作为研究基线/反向测试样本保留。
