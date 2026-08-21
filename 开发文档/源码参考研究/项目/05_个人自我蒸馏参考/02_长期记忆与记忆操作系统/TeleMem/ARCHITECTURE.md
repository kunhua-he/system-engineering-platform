# TeleMem 架构建档

> 本文是对本地仓库的首轮静态架构建档，不是实现计划，也不替代源码。分析边界：仓库 `main` 分支提交 `a8e537c7064e00e3f3d4593f8408f32bb528d10d`（2026-08-17，`Update star-history chart`）。
>
> 已实际读取：`README.md`、`README-ZH.md`、`pyproject.toml`、`requirements.txt`、`uv.lock`、核心 `telemem/`、配置、MCP/API/Provider/Video 文档、示例、测试、CI/发布/Docker 文件以及 LongMemEval 评测入口。仓库内未发现 `AGENTS.md` 或 `CLAUDE.md`；未安装依赖、未启动服务、未构建、未运行测试、未提交 Git。

## 1. 项目定位

TeleMem 是 Python 记忆层：以 `telemem.Memory`/`TeleMemory` 作为 Mem0-compatible drop-in API，面向长时对话、角色隔离、语义检索和视频记忆。文本主链路复用 `mem0.Memory` 的 LLM、embedder、vector store、history 能力；TeleMem 在其上增加角色/共享事件作用域、摘要与批量语义融合，并提供独立 MCP server。

核心取舍：

- **契约优先**：`import telemem as mem0`，顶层重新导出 mem0 API；`Memory` 是 `TeleMemory` 别名（`telemem/__init__.py:11-24`）。
- **本地优先但 provider 可替换**：默认可走 OpenAI-compatible endpoint，配置示例覆盖本地 Ollama、DeepSeek、Moonshot、MiniMax；向量存储默认 FAISS。
- **文本与视频两条存储域**：文本由继承的 mem0 存储栈管理；视频由 JPEG 帧、`captions.json` 和 NanoVectorDB JSON 组成。
- **MCP 是适配层，不是第二套记忆内核**：MCP 工具最终调用同一个进程内的 `Memory` singleton（`telemem/mcp/server.py:71-121`）。

## 2. 总体 text 流程图

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ 接入层                                                                       │
│ Python: telemem.Memory / TeleMemory   │   MCP: stdio / streamable-http / SSE │
│ examples / LangChain / LlamaIndex      │   Claude / Cursor / DeepSeek Harness│
└──────────────────────────────┬───────────────────────────────┬───────────────┘
                               │                               │
                               ▼                               ▼
                    ┌──────────────────┐             ┌────────────────────┐
                    │ TeleMemory API   │             │ MCP tool adapter   │
                    │ add/add_batch    │             │ scope/default/error│
                    │ search + inherited│             │ structured output  │
                    │ get/update/delete│             └─────────┬──────────┘
                    └────────┬─────────┘                       │
                             └──────────────┬──────────────────┘
                                            ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ 文本记忆处理层                                                               │
│ normalize messages → character/global prompt → LLM extraction                │
│ → extract_events_from_text → embedding → similar-memory search               │
│ → cosine cluster / LLM fusion → buffer flush                                 │
└────────────────────────────────────┬─────────────────────────────────────────┘
                                     ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ mem0 扩展/持久化层                                                           │
│ inherited _create_memory / _search_vector_store / history / CRUD             │
│ FAISS vector store + JSON metadata + history DB                              │
│ scope: user profile(s) + pseudo-user "events"                                │
└────────────────────────────────────┬─────────────────────────────────────────┘
                                     │
                                     │ search: profile scope(s) + events
                                     ▼
                              {"results": [...]}

多模态旁路：
video/local-or-YouTube → OpenCV JPEG frames → VLM captions.json
→ embeddings → NanoVectorDB *_vdb.json → MMCoreAgent ReAct tools
(global_browse / clip_search / frame_inspect / finish) → answer messages
```

## 3. 分层架构

| 层 | 责任 | 主要文件/边界 |
|---|---|---|
| 接入与兼容层 | 暴露 Mem0-compatible Python API、MCP、示例框架适配 | `telemem/__init__.py`、`telemem/mem0.py`、`telemem/mcp/server.py`、`examples/` |
| 应用编排层 | 将消息转成摘要、跨角色展开 batch、合并 scope、批量 flush、检索合并与 rerank | `telemem/mem0.py:60-688` |
| 提示词与解析层 | 角色/全局摘要 prompt、融合 prompt、LLM 输出的格式/JSON/条目回退解析 | `telemem/utils.py:62-331` |
| provider/config 层 | Pydantic 配置、YAML/JSON 读取、环境变量占位符展开、LLM/embedder endpoint | `telemem/configs.py`、`telemem/utils.py:13-59`、`config/` |
| 向量与历史存储层 | 由 mem0 提供的 vector store、embedding、history、CRUD；TeleMem 调用其私有 helper | `telemem/mem0.py:163-216,522-587,659-688`；具体 schema 属于依赖 |
| 多模态处理层 | 下载/复制视频、抽帧、并行 VLM caption、主题 registry 合并、向量库与 ReAct QA | `telemem/mm_utils/`；通过 `_import_mm()` 懒加载 |
| 评测与发布层 | 基线、LongMemEval、统计、CI、PyPI/MCP registry/Docker 发布 | `baselines/`、`docs/evaluation.md`、`.github/workflows/`、`Dockerfile` |

### 3.1 真实目录地图

```text
TeleMem/
├── telemem/
│   ├── __init__.py              顶层导出、版本、关闭 mem0 telemetry 默认值
│   ├── mem0.py                  TeleMemory 主实现：add/batch/search/MM
│   ├── configs.py               TeleMemoryConfig
│   ├── utils.py                 配置加载、提示词、摘要解析、向量相似度
│   ├── mm_utils/                视频处理与 MMCoreAgent；PEP 562 懒导出
│   └── mcp/                     MCPServer、module/CLI 入口
├── config/                      默认和 provider 示例配置
├── examples/                    Python、MCP、multi-NPC、框架与 DeepSeek Harness 示例
├── tests/                       离线契约、MCP、provider、统计和 API 测试
├── baselines/                   RAG、Mem0、MemoBase、A-mem、旧 TeleMem、LongMemEval
├── data/                        ZH-4O 数据与视频样例
├── docs/                        MkDocs 文档、API/MCP/Provider/Video/评测说明、技术报告
├── assets/                      文档图片
├── server.json                  MCP registry manifest
├── pyproject.toml / uv.lock    包、依赖、entry points、可复现环境
├── Dockerfile                   MCP server 镜像
└── .github/workflows/           CI、文档、发布、star-history
```

`README` 中的目录树是面向用户的摘要；上图按当前 Git 文件清单补充了 `baselines/longmemeval`、`.github`、Docker、发布清单等实际组成。

## 4. 核心模块与入口

### 4.1 Python 包入口

`telemem/__init__.py` 先 `setdefault("MEM0_TELEMETRY", "False")`，再 `from mem0 import *`，最后覆盖/增加 `TeleMemory`、`Memory` 和 `TeleMemoryConfig`。因此顶层 API 的事实来源是 **mem0 公共面 + TeleMem 自己的覆盖面**，不是独立重写的全部 Mem0 API。

`TeleMemory.__init__` 调用 `mem0.Memory.__init__`，保存 `buffer_size`、`similarity_threshold`，并初始化：

```text
memory_buffer: Dict[buffer_key, List[memory_candidate]]
buffer_locks: Dict[buffer_key, threading.Lock]
```

buffer key 为 `"{run_id}_{events|person_{user_id}}"`（`telemem/mem0.py:68-76`）。

### 4.2 文本 add 路径

```text
add(messages, scope, infer, memory_type, prompt, batch)
  ├─ batch=True                         → add_batch(...)
  ├─ normalize str/dict/list
  ├─ 校验至少一个 user_id/agent_id/run_id
  ├─ memory_type=procedural_memory       → mem0 私有 procedural pipeline
  ├─ infer=False                         → 每条非 system 原文 _create_memory
  └─ infer=True
       → user_id 有值：角色视角 prompt；无值：全局事件 prompt
       → 最新 turn 与上下文分开编码
       → LLM generate_response
       → extract_events_from_text
       → 每个摘要 _search_vector_store(limit=5, threshold)
       → prompt 融合相似旧记忆
       → JSON stored_memories
       → inherited _create_memory
       → {"results": [{id,memory,event:"ADD"}, ...]}
```

实现文件：`telemem/mem0.py:218-360`、`telemem/utils.py:73-152,154-331`。静态代码显示融合结果被作为新摘要写入；旧记忆的实际 update/delete 仍来自继承的 Mem0 CRUD，而非 TeleMem 的 add 融合函数直接发出 UPDATE/DELETE 事件。

### 4.3 add_batch 与角色隔离

`add_batch` 将 `user_id` 规范化成角色列表，并始终追加 `None` 代表共享 `events` scope；单个角色因此产生「角色私有档案 + 共享世界事件」两套抽取任务（`telemem/mem0.py:362-477`）。

```text
message-list[] × [user_A, user_B, ..., None]
       │
       ├─ ThreadPoolExecutor(max_workers=16)
       │    └─ 每个 (message-list, scope) 做摘要 + 相似检索
       │
       ├─ 写入 memory_buffer[run_id_scope]
       ├─ 达到 buffer_size → lock → _flush_buffer
       └─ 函数结束 → flush 所有尚未达到阈值的 scope
```

`_flush_buffer` 收集新摘要和检索到的旧摘要，先按 embedding 做贪心 cosine clustering，再对包含新摘要的 cluster 调用 LLM 融合；单项 cluster 直接写入。锁只保护单个 buffer 的 flush，线程池异常被记录后继续处理。

### 4.4 search 路径

```text
search(query, user_id, agent_id, run_id, filters, limit, threshold, rerank)
  → user_id=None: [events]
    user_id=<id>: [<id>, events]
  → 每个 scope 调 inherited _search_vector_store
  → 给 hit 加 source=<scope>
  → 可选 reranker.rerank(query, all_memories, limit)
  → 丢弃空 memory
  → 无 reranker 时按 score 降序截断合并结果到 limit
  → {"results": hits}
```

证据：`telemem/mem0.py:591-688`、`docs/api.md:49-65`。这解释了角色记忆与共享事件的可见性：指定角色查询并非只查角色，而是角色 + `events`。

## 5. 数据模型与持久化

### 5.1 配置模型

`TeleMemoryConfig` 继承 `mem0.configs.base.MemoryConfig`（`telemem/configs.py:1-7`），新增：

| 字段 | 默认/语义 |
|---|---|
| `buffer_size` | `64`；达到该数量后触发 buffer flush |
| `similarity_threshold` | `0.95`，Pydantic 约束 `0.0 ≤ x ≤ 1.0` |
| `vlm` | 视频 endpoint、模型、FPS、clip length、embedding dim、ReAct 参数等字典 |
| 继承字段 | `llm`、`embedder`、`vector_store`、`history_db_path` 等由 mem0 `MemoryConfig` 定义 |

配置文件的稳定结构是：

```yaml
llm:        {provider: openai, config: {model, openai_base_url, api_key, ...}}
embedder:   {provider: openai, config: {model, openai_base_url, api_key, embedding_dims?}}
vector_store: {provider: faiss, config: {collection_name, path, embedding_model_dims?}}
history_db_path: db/history.db
buffer_size: 64
similarity_threshold: 0.95
vlm: {...}                    # 可选的视频域配置
```

`load_config()` 只支持 YAML/YML/JSON；先解析文档，再在值层递归替换 `${NAME}`，缺失变量报出变量名，不允许环境值注入 YAML 结构（`telemem/utils.py:13-59`）。

### 5.2 文本记忆的逻辑数据模型

TeleMem 自己没有 ORM、migration 或第一方 `MemoryRecord` 数据类；持久化记录由 mem0 后端实现。TeleMem 负责写入的逻辑字段/作用域如下：

| 逻辑对象 | 字段/来源 | 用途 |
|---|---|---|
| Memory result | `id`, `memory`, `event`, search 时增加 `score`, `source` | Mem0-compatible 返回契约 |
| Scope | `user_id`、`agent_id`、`run_id` | 隔离检索与过滤；无 `user_id` 的文本落到 pseudo-user `events` |
| Metadata | 用户传入 metadata + `user_id`/`agent_id`/`run_id`；raw 路径增加 message `role` | 审计、过滤、角色归属 |
| Candidate | `new_memory`、`similar_memories[{id,text}]`、`metadata` | LLM 融合前的内存态候选 |
| History | inherited Mem0 `history(memory_id)` 的 ADD/UPDATE/DELETE 事件 | 变更历史，具体表结构由 mem0 管理 |

配置与 README 宣称的落盘形态是 **FAISS 索引 + JSON metadata + history DB**（`config/config.yaml:16-24`、`README.md:652-680`）。仓库当前没有这些运行产物，说明它们是运行时生成物，不是源码模型文件。精确的 mem0 表/列、FAISS metadata schema、CRUD 原子性和 history DB DDL 未在本仓库确认。

### 5.3 多模态数据模型

视频域是文件/JSON 模型，不与文本 `Memory` 索引自动合并：

```text
output_dir/
├── frames/<video_name>/frames/frame_n000000.jpg ...
├── captions/<video_name>/
│   ├── ckpt/<start>_<end>.json       # 单 clip 断点
│   └── captions.json
└── vdb/<video_name>/<video_name>_vdb.json
```

`captions.json` 的确认结构：

```json
{
  "0_10": {"caption": "..."},
  "10_20": {"caption": "..."},
  "subject_registry": {
    "subject": {"name": "...", "appearance": [], "identity": [], "first_seen": "..."}
  }
}
```

`init_single_video_db()` 将每个 clip caption 转成 `{__vector__, time_start_secs, time_end_secs, caption}`，写入 NanoVectorDB；另存 `subject_registry`、`video_length`、`video_file_root`、`fps` 作为 additional data（`telemem/mm_utils/build_database.py:263-305`）。

### 5.4 评测数据模型

已解析 `data/zh4o/data.json`：顶层是 28 项 list；首项字段为 `sample_id`、`conversation`、`session_summary`、`event_summary`、`observation`、`qa`。conversation 至少含 `speaker_a`、`speaker_b`、`session_1_date_time` 和 `session_1`；会话条目使用 `speaker`、`dia_id`、`text`。LongMemEval 入口则以 `question_id`、`question_type`、`question`、`answer`、`haystack_sessions` 等字段驱动检索/回答/评测（`baselines/longmemeval/run_telemem.py:116-145,226-329`）。

## 6. 多模态处理链

### 6.1 add_mm

入口：`TeleMemory.add_mm(video_path, output_dir, clip_secs=None, emb_dim=None, subtitle_path=None)`（`telemem/mem0.py:691-796`）。

```text
video_path
  → decode_video_to_frames (OpenCV, cfg VIDEO_FPS)
  → frame_n*.jpg
  → process_video
       → 固定 CLIP_SECS 切 clip + 可选 SRT
       → 每 clip VLM JSON caption + subject_registry
       → 16 进程并行 + ckpt 缓存
       → 分层 LLM merge subject registries
       → captions.json
  → init_single_video_db
       → batch embeddings（NanoVectorDB）
       → *_vdb.json + additional_data
```

如果目标帧目录、`captions.json` 或 VDB JSON 已存在，`add_mm` 跳过对应阶段。`telemem/mm_utils/__init__.py` 与 `TeleMemory._import_mm()` 使用懒导入，核心文本安装不必在 `import telemem` 时加载 OpenCV/yt-dlp/NanoVectorDB。

### 6.2 search_mm

`search_mm` 要求 `captions/*/captions.json` 与 `vdb/*/*_vdb.json` 各恰好一个，构造 `MMCoreAgent` 后运行 `THINK → ACTION → OBSERVATION`。工具集合默认含 `global_browse_tool`、`clip_search_tool`、`frame_inspect_tool`、`finish`；`LITE_MODE=True` 时移除 `frame_inspect_tool`（`telemem/mm_utils/core.py:37-49,133-173`）。最终返回 message 列表，由 `extract_choice_from_msg` 从 assistant 消息中解析 A/B/C/D。

## 7. API、CLI、SDK 与集成面

### 7.1 Python API

| API | 作用 | 返回/备注 |
|---|---|---|
| `Memory` / `TeleMemory` | 主类，`Memory` 是别名 | 继承 `mem0.Memory` |
| `add(messages, *, user_id=None, agent_id=None, run_id=None, metadata=None, infer=True, memory_type=None, prompt=None, batch=False)` | 单次抽取/原文写入/程序性记忆委派 | `{"results": [...]}` |
| `add_batch(messages, *, user_id=None/list, agent_id=None, run_id=None, metadata=None, infer=True, memory_type=None, prompt=None)` | 并发多轮、多角色 + events 写入 | 同上；不支持 procedural `memory_type` |
| `search(query, *, user_id=None, agent_id=None, run_id=None, limit=100, filters=None, threshold=None, rerank=True)` | scope 合并语义检索 | `{"results": [{id,memory,score,source,...}]}` |
| `add_mm(video_path, output_dir, clip_secs=None, emb_dim=None, subtitle_path=None)` | 视频入库 | `{"output_dir": abs_path}` |
| `search_mm(question, output_dir, max_iterations=15)` | 视频 ReAct QA | message list |
| inherited `get`, `get_all`, `update`, `delete`, `delete_all`, `history`, `reset` | Mem0 CRUD/历史 | 以 mem0 版本为准 |

约束：`add` 至少需要 `user_id`、`agent_id`、`run_id` 之一；`infer=False` 不调用 LLM；只有 `memory_type="procedural_memory"` 走 Mem0 procedural pipeline（`docs/api.md:7-34`）。

### 7.2 MCP 工具面

`create_server()` 注册且测试固定的 8 个工具（`telemem/mcp/server.py:156-383`）：

```text
add_memory          search_memories       get_memories       get_memory
update_memory       delete_memory         delete_all_memories
memory_history
```

- 未给 scope 的读写默认 `TELEMEM_DEFAULT_USER_ID`，默认值 `telemem-mcp`。
- `search_memories` 将 Mem0 结果融合成一个文本 passage；`get_memories` 映射到 `memory.get_all(filters=..., top_k=...)`。
- `delete_all_memories` 必须显式给出至少一个 scope，不能误用默认用户执行全量删除。
- 工具携带 title、read-only/destructive/idempotent/open-world hints 和 structured output；异常被转换为 `{"error": ..., "detail": ...}`。

### 7.3 CLI、传输与 SDK

| 入口 | 用法 |
|---|---|
| `telemem-mcp` | 默认 stdio；`--transport streamable-http --host 127.0.0.1 --port 8421`；也支持 deprecated `sse` |
| `telemem` | 与 `telemem-mcp` 相同，便于 `uvx telemem` |
| `python -m telemem.mcp` | 等价 module 入口 |
| MCP Python SDK v2 | `examples/mcp_client.py` 通过 stdio `Client` 做 list/call；测试 modern/legacy 两种协议路径 |
| 嵌入式 server | `from telemem.mcp import create_server; server.run(...)` |
| DeepSeek Harness | `examples/deepseek-harness.cordis.yml` 以 `uvx telemem==1.10.0` 注册 `mcp__telemem__*` |
| Claude/Cursor/Claude Code | `examples/mcp_config.json`、`docs/MCP.md` 配置 MCP server |
| 框架示例 | `examples/langchain_memory.py`、`examples/llamaindex_memory.py`；接入模式是回答前 `search`、对话后 `add` |

## 8. 技术栈与依赖

### 8.1 直接技术栈

| 类别 | 已确认技术 |
|---|---|
| 语言/运行时 | Python `>=3.10`；CI 矩阵 3.10/3.11/3.12 |
| 包构建 | Hatchling；`uv.lock`；PyPI package `telemem` |
| 记忆基座 | `mem0ai>=2.0,<2.1`，TeleMem 调用其私有 helper，因此受 minor series 约束 |
| LLM/Embedder | OpenAI SDK 与任意 OpenAI-compatible HTTP endpoint；Azure CLI credential 仅多模态 fallback |
| 向量/数值 | FAISS CPU、NumPy、NanoVectorDB（video extra） |
| 配置/校验 | Pydantic、PyYAML；递归环境变量值展开 |
| 并发/媒体 | `ThreadPoolExecutor`、`multiprocessing`、OpenCV、yt-dlp、tqdm |
| 协议/服务 | MCP Python SDK v2；stdio、Streamable HTTP、兼容旧 SSE |
| 文档/发布 | MkDocs Material、Docker、GitHub Actions、PyPI trusted publishing、MCP registry |

### 8.2 pyproject 声明的依赖分组

- Core：`mem0ai`、`openai`、`pydantic`、`faiss-cpu`、`numpy`、`pyyaml`、`tqdm`、`mcp>=2,<3`。
- `video` extra：`opencv-python-headless`、`nano-vectordb`、`yt_dlp`、`azure-identity`、`requests`。
- `mcp` extra：当前只是 core MCP SDK 的兼容别名。
- `all` extra：组合 MCP + video。
- `dev` group：pytest。

已读取的锁定快照包括 `mem0ai==2.0.5`、`mcp==2.0.0`、`faiss-cpu==1.14.2`、`openai==2.41.1`、`pydantic==2.13.4`、`numpy==2.4.6`、`pytest==9.0.3` 等；以 `uv.lock` 当前内容为准，未执行安装或解析。

### 8.3 Provider 配置矩阵

| 配置 | LLM | Embedder | 存储 |
|---|---|---|---|
| `config.yaml` | 本地 OpenAI-compatible `qwen3-8b` | 本地 `qwen3-8b-embedding` | FAISS `db/faiss_db` + `db/history.db` |
| `config.ollama.yaml` | Ollama `qwen3:8b` | Ollama `nomic-embed-text`，768 维 | FAISS，明确维度一致 |
| `config.deepseek.yaml` | DeepSeek | OpenAI `text-embedding-3-small` | FAISS |
| `config.moonshot.yaml` | Moonshot/Kimi | OpenAI `text-embedding-3-small` | FAISS |
| `config.minimax.yaml` | MiniMax M3/M2.7 | OpenAI `text-embedding-3-small` | FAISS |

向量维度必须同时匹配 embedder 输出与 FAISS `embedding_model_dims`；`docs/providers.md:54-65` 将其列为显式运维约束。

## 9. 测试与质量门

### 9.1 测试文件职责

| 文件 | 静态覆盖面 | 网络/API 条件 |
|---|---|---|
| `tests/test_contract.py` | Fake LLM/embedder 契约：scope、角色 prompt、infer false、prompt override、procedural、batch、events、search limit、telemetry | 离线 |
| `tests/test_mcp.py` | 8 工具注册/Schema/annotations、参数映射、默认 scope、删除保护、结构化错误、stdout 隔离、modern/legacy protocol round-trip | 离线，使用 FakeMemory |
| `tests/test_providers.py` | Ollama/DeepSeek/Moonshot 配置结构、维度、环境变量展开与缺失变量错误 | 单元离线；provider integration 由环境变量门控 |
| `tests/test_minimax.py` | MiniMax 配置、端点、模型与温度契约 | API 类测试由 `MINIMAX_API_KEY` 门控 |
| `tests/test_eval_stats.py` | Wilson CI、mean/std、区间重叠 | 离线 |
| `tests/test_basic.py` | import、类、配置、实例化、mm_utils 导出、Mem0 兼容、包结构 | 文档标为无需 key，但 `mm_utils` 导入仍要求 video extras 可用 |
| `tests/test_telemem.py` | 旧式手写集成：真实 add/search、返回 shape、边界场景 | `tests/conftest.py` 默认忽略，需 `TELEMEM_RUN_API_TESTS=1` |
| `tests/conftest.py` | 默认将 live test 排除；为离线实例化提供占位 `OPENAI_API_KEY` | 控制 pytest collection |

仓库文档和测试代码都要求默认 CI 使用离线套件；CI 实际命令是 `uv run pytest tests/ -q`，矩阵 Python 3.10–3.12。由于本次范围是只读建档，未运行命令，不能在本文宣称当前测试通过。

### 9.2 评测架构

`baselines/longmemeval/run_telemem.py` 将检索策略抽象成：

```text
same answer model + same answer prompt
  ├─ telemem: ingest → semantic search
  ├─ full-context: entire history (budgeted)
  └─ grep: keyword-overlap retrieval (simplified)
       ↓
answer call → audited LLM judge → per-seed results
       ↓
mean ± sample std + per-type Wilson 95% + ingest/search latency + tokens
```

`docs/evaluation.md` 要求 baseline-first、固定模型、审计 judge、多 seed、噪声区间、成本/延迟与可复现配置；LongMemEval README 明确当前 harness 状态为 experimental，发布数字 pending。`baselines/` 还保留 RAG、Mem0、MemoBase、A-mem 和 legacy TeleMem 用于比较，不应误认为生产运行时依赖。

## 10. 部署、发布与运行边界

- **直接库使用**：`pip install telemem`，配置默认 OpenAI 或显式 `TELEMEM_CONFIG`。
- **本地全链路**：Ollama + FAISS + JSON metadata；核心代码不自动启动外部模型服务。
- **MCP stdio**：最适合桌面 Agent/CLI；stdout 由协议占用，server 将后端噪声重定向到 stderr。
- **HTTP MCP**：`streamable-http` 默认端口 8421，监听地址由 CLI 指定；Docker 示例要求容器内 `0.0.0.0`。
- **Docker**：`python:3.12-slim`，只 COPY `pyproject.toml`、`README.md`、`telemem/`，安装本地 package，entrypoint 为 `telemem-mcp`；Docker 镜像没有在 Dockerfile 中安装 video extra。
- **发布**：tag `v*` 触发，先检查 tag 与 `telemem.__version__`，构建 sdist/wheel，PyPI OIDC 发布，再同步 `server.json` 版本并发布 MCP registry。
- **文档**：MkDocs Material，由 `.github/workflows/docs.yml` 发布 GitHub Pages（具体 workflow 未作为本次重点展开）。

## 11. 未确认项与静态风险

以下项目没有通过运行时、依赖源码或真实后端验证，不能当成已实现保证：

1. **Mem0 持久化真实 schema 未确认**：本仓库没有自己的 ORM/migration/model registry；FAISS 元数据格式、history DB 表结构、CRUD 是否原子、并发/崩溃恢复边界均由 mem0 2.0.x 决定。
2. **私有 API 兼容性边界**：`telemem/mem0.py` 明确调用 `_create_memory`、`_search_vector_store`、`_create_procedural_memory` 等私有成员；`mem0ai>=2.0,<2.1` 是保护措施，但仍需在目标平台实际验证。
3. **融合语义与 CRUD 语义需区分**：add 的 LLM fusion 代码最终调用 `_create_memory`；文档中的“增删/融合”不能直接等价为对旧记忆发出 UPDATE/DELETE。继承 API 的 history 具体事件链未在仓库内确认。
4. **相对路径行为需实跑确认**：`add_mm` 对 `output_dir` 使用 `os.path.join(BASE_DIR, output_dir)`（`telemem/mem0.py:727-731`），而 examples/docs 以仓库相对路径描述；绝对路径与当前工作目录组合是否完全符合预期需验证。
5. **`clip_secs` 参数现状**：`add_mm` 接收该参数，但实现中实际使用 `self.config.vlm` 的 `CLIP_SECS`，相关覆盖逻辑是注释；参数是否应生效需产品/实现裁决。
6. **多模态配置双轨**：文本使用 `TeleMemoryConfig` 的 `vlm`，MM 工具又有独立的 `memory_utils.load_config`/dict 约定（如 `vlm_client`、`emb_client`、`emb_model`）；完整字段映射只在运行时路径中体现，未有统一 schema。
7. **MM 工具待运行验证**：静态代码中的 endpoint/key 字段映射、`global_browse_tool` embedding 参数、NanoVectorDB 已存在文件的 additional data、并行 caption 失败恢复均未通过真实视频/VLM/embedding 验证。
8. **核心安装与基础测试的边界**：`telemem.mm_utils` 虽然懒导出，但 `test_basic.py` 直接导入多模态符号；未安装 `[video]` 时该测试是否符合“无需 API key”的文档表述需在受控环境确认。
9. **MCP backend 行为未实测**：离线测试覆盖 FakeMemory 与协议结构，但真实 Mem0 的 `get_all/update/delete/delete_all/history` 返回 shape、scope 过滤和 streamable HTTP 传输尚未验证。
10. **评测数字不是本次验证结果**：README 的 ZH-4O 86.33% 等数字是项目声明；LongMemEval 当前文档明确发布数字 pending，不能由本架构文档背书。

## 12. 可复用的关键模式

- 用继承/别名保持既有 Mem0 调用契约不变，再通过 `TeleMemory` 增加角色与视频能力。
- 以 pseudo-user `events` 表示共享世界状态，以真实 `user_id` 表示角色私有视角，并在 `search` 时可控合并。
- `infer=False` 提供不调用 LLM 的原文写入路径，适合离线契约测试与确定性导入。
- 视频流水线每阶段有文件级缓存/ckpt，支持抽帧、caption、向量库分阶段复用。
- MCP 层做 scope 默认值、破坏性操作显式 scope、防 stdout 污染、结构化错误和协议兼容，不复制记忆逻辑。
- 评测把 full-context、grep 与 TeleMem 放在同一 answer model/prompt 下，并报告区间、成本和延迟，而不是只报单点准确率。

## 13. 首轮结论

TeleMem 的生产/使用主干可以概括为：

```text
Mem0-compatible Python/MCP contract
        ↓
TeleMemory orchestration (character + events + buffer + fusion)
        ↓
Mem0-managed FAISS/metadata/history persistence
        ↓
semantic search / CRUD / MCP structured tools

video input
        ↓
frames → captions + subject registry → NanoVectorDB JSON
        ↓
MMCoreAgent tool-calling QA
```

它不是独立数据库型记忆操作系统，而是一个以 Mem0 为存储/模型基座、以文件化多模态索引和 MCP 适配扩展能力的 Python package。后续若要把它的模式迁入其他平台，优先抽取的是：**公开契约兼容、scope/角色隔离、buffer/fusion、阶段缓存、MCP 安全边界和可审计评测**；不要把 `baselines/` 当作运行时核心，也不要在未确认 Mem0 schema 前假设 TeleMem 已拥有独立持久化模型。

## 14. 证据索引

- 定位、公开 API、存储声明：`README.md:48-64,114-145,361-449,652-705`；`README-ZH.md:50-65,117-149,341-430,631-705`
- 包导出与版本：`telemem/__init__.py:1-24`
- 主实现：`telemem/mem0.py:41-58,60-216,218-589,591-688,691-841`
- 配置与解析：`telemem/configs.py:1-46`；`telemem/utils.py:13-59,62-394`
- 多模态：`telemem/mm_utils/video_utils.py`；`frame_caption.py`；`build_database.py`；`core.py`；`mm_utils/__init__.py`
- MCP：`telemem/mcp/server.py:75-121,156-425`；`docs/MCP.md:19-169`
- API/provider/video：`docs/api.md`、`docs/providers.md`、`docs/video.md`
- 依赖与 entry points：`pyproject.toml:31-73`；版本锁定：`requirements.txt`、`uv.lock`
- 测试契约：`tests/test_contract.py`、`tests/test_mcp.py`、`tests/test_providers.py`、`tests/test_minimax.py`、`tests/test_eval_stats.py`、`tests/conftest.py`
- 评测与基线：`baselines/longmemeval/run_telemem.py`、`baselines/longmemeval/stats.py`、`docs/evaluation.md`
- 运行与发布：`examples/`、`server.json`、`Dockerfile`、`.github/workflows/ci.yml`、`.github/workflows/release.yml`
- 本文件已吸收此前 `细探-TeleMem.md` 的源码分析结论；后续只维护本文件，旧细探笔记不再作为独立事实源。当前工作树和 Git 索引均未发现该旧细探文件；本轮没有删除任何旧细探。

## 15. 第三轮：通用底座映射与唯一链路裁决

> 本节不是把 TeleMem 宣称成已经具备的系统工程平台，而是把本仓库当前真实实现映射到“支持库—记忆模块—运行核心—网关”的公共底座边界。凡源码没有实现、没有测试或依赖 `mem0ai` 私有 API 的地方，均明确标为“缺口/待核”，不得把目标设计当成当前能力。
>
> **本轮身份与证据边界**：目标根目录为 `/Users/hekunhua/Documents/Agent/github 源码参考/05_个人自我蒸馏参考/02_长期记忆与记忆操作系统/TeleMem`；代码图 MCP 已按该路径探测，返回“没有 `.codegraph/`，不可查询”，因此本节只使用现场源码、现有 `ARCHITECTURE.md`、仓库文件和测试代码，不冒充代码图证据。项目最近源码基线仍为 `a8e537c7064e00e3f3d4593f8408f32bb528d10d`（2026-08-17T07:30:12Z，`Update star-history chart`）。

### 15.1 映射规则：当前归属与平台目标归属分开

| 底座边界 | 当前源码事实 | 第三轮归属裁决 | 证据/状态 |
|---|---|---|---|
| 支持库 | `mem0ai` 的 LLM、embedding、FAISS、history、CRUD 私有 helper；视频侧 OpenCV、`yt_dlp`、`NanoVectorDB`、OpenAI-compatible client | 只把“外部 provider 薄适配、配置解析、向量/文件原子能力、MCP SDK 适配”归支持库；不把 Mem0 内部 schema 猜成 TeleMem 自有支持库 | 复用/升级；Mem0 内部待核 |
| 记忆模块 | `TeleMemory` 负责消息规范化、角色/`events` 作用域、LLM 摘要、相似记忆检索、融合、search 合并；`MMCoreAgent` 负责视频检索编排 | TeleMem 的核心可复用资产归“记忆模块”：作用域语义、抽取/融合策略、统一记忆结果；视频记忆是独立模块或独立 provider 域，不并入文本索引 | 吸收，源码充分 |
| 运行核心 | 没有独立运行核心；buffer、锁、线程池、进程池、重试和 ReAct 循环散落在记忆代码 | 迁移候选只提取执行监督、任务状态、超时/取消、崩溃恢复、资源释放、证据和可观测性；不复制 TeleMem 的第二套任务系统 | 需升级，当前缺口明显 |
| 网关 | Python 类入口、MCP 8 工具、stdio/Streamable HTTP/SSE CLI | MCP/CLI/HTTP 只归统一网关适配层；网关不得直接触碰 FAISS、NanoVectorDB 或 provider 对象，统一调用记忆模块公开契约 | 吸收，MCP 边界清楚；认证/生命周期待核 |
| 评测/示例 | `examples/`、`baselines/longmemeval/run_telemem.py`、Fake 后端测试 | 归任务/评测层（L4），不能成为生产记忆模块、索引或网关；评测工作目录的临时存储由运行核心托管 | 吸收边界，禁止倒灌 |

固定原则：一个记忆能力只能有一个模块 owner；一个 provider 能力只能有一个支持库 owner；所有入口必须经过同一注册/调用路径。TeleMem 当前“Python 入口和 MCP 入口都最终进入同一 `Memory` singleton/实例”的部分符合此原则，但其内部仍直接调用 Mem0 私有 helper，尚未形成平台级 provider 注册、契约版本、超时和证据边界。

### 15.2 跨会话、跨时间的记忆传输链

#### 15.2.1 当前真实链路

```text
调用者消息
  → add()/add_batch() 的 user_id、agent_id、run_id、metadata
  → TeleMemory 将 user_id 缺省映射为 pseudo-user "events"
  → infer=True：LLM 摘要/事件抽取 → _search_vector_store(limit=5)
  → 当前调用内 candidate buffer（仅 add_batch）/立即 _sync_memory_to_vector_store（add）
  → Mem0 _create_memory → FAISS + metadata + history DB（具体 schema 外置）
  → 下一次进程/下一次会话由同一配置重开 Mem0 后端，再以相同 scope search()
  → user scope + "events" scope 合并、reranker 或 score 截断
```

- `run_id` 在 `add()` 中写入 metadata 和 search filter（`telemem/mem0.py:296-331,514-529,639-664`），但它不是会话注册表、恢复 token 或时间游标；源码没有 `session` 表，也没有“上一会话自动续接”协议。
- `add_batch()` 的 buffer key 是 `f"{run_id}_{person_<user>|events}"`（`telemem/mem0.py:68-76,425-477`）。`run_id=None` 会形成字符串 `None_...`，因此它更像当前实例内的并发隔离键，而不是可靠的跨进程唯一事务键。
- 跨调用持久化依赖 Mem0 外部后端；跨时间传输只在调用者再次传入同一 `user_id`/`agent_id`/`run_id` 或 filters 时成立。没有 first-party `created_at`、`source_time`、`session_started_at`、顺序号、版本号或增量 checkpoint。
- 角色查询会自动加入 `events`（`telemem/mem0.py:646-653`），所以事件可从过去会话传给角色；但这是固定的双 scope 查询，不是按时间、权限或事件订阅传输。
- LongMemEval 明确读取 `haystack_sessions`，但 `retrieve_telemem()` 仅逐 session `memory.add(messages, user_id=scope)`，未把 `haystack_dates` 传入 `metadata`，也没有把 session id 写入 `run_id`（`baselines/longmemeval/run_telemem.py:126-147`）。这意味着评测中的跨时间信息主要靠同一 user scope 的语义累积，日期/会话边界在 TeleMem 记忆记录中不可审计。

#### 15.2.2 归底座的传输契约

| 传输对象 | 支持库负责 | 记忆模块负责 | 运行核心负责 | 网关负责 |
|---|---|---|---|---|
| 会话标识 | ID 校验/序列化，不生成业务语义 | 解释 `user_id`、`agent_id`、`run_id` 作用域 | 生成 request/task/attempt id，维护租约和恢复点 | 从请求提取并显式传递，不能隐式改写 |
| 跨时间记忆 | provider 的持久化读写、索引刷新 | 记忆版本、来源、时间窗口、可见 scope 过滤 | 提交事务、checkpoint、重启恢复、幂等 | 分页/流式返回，不缓存第二份事实 |
| 跨会话导入 | 文件/JSON/数据库/HTTP provider | 消息→记忆的单一抽取入口 | 背压、超时、取消、部分失败账本 | API/MCP 参数和错误映射 |
| 记忆传出 | 结果序列化、向量/记录读取 | 统一 `memory/result/history` 形状 | 读一致性、资源释放、审计 | Python/MCP/HTTP 响应 |

**复用裁决**：保留 TeleMem 的 `run_id` 作为兼容输入，但平台适配层必须补 `session_id`、`source_event_id`、`source_time`、`ingest_time`、`memory_version`、`idempotency_key` 的明确映射；不能把 `run_id` 误升格为完整跨会话协议。

### 15.3 消息、事件与变更记录

1. **输入消息**：`add()` 接受 `str`、`dict` 或 `list`，字符串包装成 `{"role":"user","content":...}`；`parse_messages()` 只识别 `system/user/assistant` 三种 role，并把内容拼成 prompt 文本（`telemem/mem0.py:282-294`；`telemem/utils.py:62-71`）。未知 role 不会被 `parse_messages()` 纳入摘要，源码没有统一拒绝/告警契约。
2. **事件抽取**：`infer=True` 时 LLM 输出经 `extract_events_from_text()`，支持摘要标记、JSON、条目和触发词分句回退（`telemem/utils.py:154-331`）。它返回的是字符串摘要列表，不是带 id、来源、时间和状态的事件对象。
3. **共享事件**：无 `user_id` 或 `add_batch()` 的 `None` 角色写成 metadata `user_id="events"`（`telemem/mem0.py:79-85,315-323,389-395`）。这是作用域命名约定，不是事件总线；没有 publish/subscribe、事件序列、去重键或消费位点。
4. **记忆变更事件**：TeleMem 自己在新增结果里写死 `event="ADD"`（`telemem/mem0.py:157-165,204-209,581-587`）。更新/删除由继承的 `mem0.Memory.update/delete/delete_all` 完成；`history()` 的 ADD/UPDATE/DELETE 记录由 Mem0 管理，当前仓库没有确认其表结构、事务边界或事件投递保证。
5. **视频事件**：caption 输出的时间片以 `"start_end"` 字典键保存，VDB 行包含 `time_start_secs/time_end_secs/caption`；`subject_registry` 是合并后的附加数据（`telemem/mm_utils/build_database.py:263-305`）。它与文本 `events` scope 没有自动桥接。

**底座归属**：消息规范化和事件/记忆语义归记忆模块；持久事件日志、顺序/幂等、投影和发布可靠性归运行核心；provider 只负责存取；网关只传输。当前 TeleMem 只有第一项的一部分，不能把 `event="ADD"` 当成完整事件账本。

### 15.4 存储、向量索引与事实 owner

| 数据/索引 | 当前写入点 | 当前持久化 | 公共底座 owner | 可靠性结论 |
|---|---|---|---|---|
| 文本记忆正文 | `TeleMemory._create_memory()` | Mem0 vector store + metadata | 支持库 provider；记忆模块提交语义 | Mem0 schema/原子性/恢复未知 |
| 文本 embedding/FAISS | Mem0 `_search_vector_store()`、`embedding_model.embed()` | 配置的 FAISS path | 向量索引支持库 | 维度一致性由配置/测试检查；在线一致性未实测 |
| ADD/UPDATE/DELETE history | 继承 Mem0 API | `history_db_path` 对应 history DB | 事件/历史支持库 | 仅接口可见，DDL 和崩溃语义未确认 |
| TeleMem candidate buffer | `memory_buffer` dict | 仅内存 | 运行核心任务状态 | 进程崩溃/强杀会丢未 flush candidate；无 checkpoint |
| 视频 caption/ckpt | `frame_caption._caption_clip()`、`process_video()` | `ckpt/*.json`、`captions.json` | 文件制品/JSON 支持库 | 普通 `open(...,"w")`，无原子替换/摘要/损坏校验 |
| 视频向量库 | `init_single_video_db()` | `*_vdb.json` NanoVectorDB | 视频索引支持库 | 已存在文件直接跳过；维度/内容新旧未做 manifest 校验 |
| VDB 附加元数据 | `store_additional_data()` | `subject_registry`、video length/root/fps | 视频记忆模块读模型 | `video_file_root` 是绝对路径，跨机器/跨时间可移植性差 |

当前唯一可靠的写 owner 只能表述为“Mem0 对文本后端负责、TeleMem 对调用参数和语义编排负责、视频工具对各 JSON/VDB 文件负责”。平台化时应把它收敛为：**一个记忆模块提交入口 → 一个存储支持库事务/索引入口 → 一个历史/事件写 owner**。禁止 MCP、examples 或评测脚本直写 FAISS、history DB、VDB。

### 15.5 服务接口、权限和网关边界

#### 15.5.1 Python 公开面

`telemem/__init__.py` 先导出 Mem0，再覆盖/增加 `Memory`、`TeleMemory` 和 `TeleMemoryConfig`；`TeleMemory` 公开 `add/add_batch/search/add_mm/search_mm`，CRUD/history/reset 仍来自继承层（现有文档第 7 节、`telemem/mem0.py:60-841`）。这是库调用契约，不是远程服务契约。直接构造 `TeleMemory()` 会调用 Mem0 配置和 provider 初始化，源码没有 close/shutdown 方法。

#### 15.5.2 MCP 网关

`telemem/mcp/server.py` 注册固定 8 个工具（`:156-383`）：

```text
add_memory → Memory.add
search_memories → Memory.search → _fuse_search_results
get_memories → Memory.get_all
get_memory → Memory.get
update_memory → Memory.update
delete_memory → Memory.delete
delete_all_memories → Memory.delete_all
memory_history → Memory.history
```

- `_get_memory()` 用进程级 `_memory` singleton 和 `_memory_lock` 延迟初始化；锁只包初始化，不包后续读写（`:71-95`）。同进程共享实例，同一进程内并发写的线程安全性由 Mem0/FAISS/TeleMem 自己承担。
- `_call()` 把 stdout 重定向到 stderr，把异常转换成 `{"error": type, "detail": ...}`，并通过 `_jsonable()` 将 UUID/date 等转成 JSON（`:98-121`）。这保证传输形状，不保证操作事务。
- 未给 scope 的读写回退 `TELEMEM_DEFAULT_USER_ID`（默认 `telemem-mcp`）；`delete_all_memories` 没有明确 `user_id/agent_id/run_id` 时在网关侧拒绝（`:124-153,352-368`）。这是最小误删保护，不是身份认证或授权系统。
- 工具声明 `readOnlyHint/destructiveHint/idempotentHint/openWorldHint` 是 MCP 元数据；它们不会在后端强制权限、幂等或并发锁。
- CLI 支持 stdio、Streamable HTTP、deprecated SSE；HTTP host/port 由参数控制（`:386-425`）。源码未发现 bearer/API key、租户 ACL、TLS、限流、审计主体或跨进程会话认证。默认 `127.0.0.1` 是部署默认，不等于安全边界；若绑定 `0.0.0.0`，必须由外部网关补认证和网络隔离。

**网关裁决**：吸收 MCP 的工具元数据、scope 默认和显式 destructive guard；升级为统一网关公共错误/鉴权/超时/取消/请求 id 契约；网关只能调用记忆模块公开接口，不能继续暴露 Mem0 私有方法和 provider 原始对象。

### 15.6 模型、任务与资源分层

| 资源/任务 | 代码位置与当前策略 | 应归层 | 当前缺口 |
|---|---|---|---|
| 文本抽取 LLM | `self.llm.generate_response()`，角色/事件 prompt；`add()` 直接调用，`add_batch()` 在线程池调用 | 模型 provider 支持库 + 记忆模块策略 | 没有统一预算、deadline、取消和 provider 错误码 |
| 记忆融合 LLM | `get_update_memory_prompt()` + JSON `stored_memories`；融合异常回退新摘要（`:181-209,553-589`） | 记忆模块语义 + LLM 支持库 | 失败时可能静默空写；无融合版本/证据 |
| Embedding | `embedding_model.embed()`；视频 `AzureOpenAIEmbeddingService.get_embeddings()` | embedding 支持库 | 文本/视频配置字段两套，维度/endpoint 契约未统一 |
| 视频 caption VLM | `process_video()` 的 `multiprocessing.Pool(16)`；每 clip 最多 3 次调用 | 视频记忆模块 + VLM 支持库 | 子进程故障、超时和 partial result 无统一任务状态 |
| 视频 merge LLM | 分层每批最多 2 次，失败返回 `{}` | 视频记忆模块 | 空 merge 仍可能生成不完整 registry，未写失败账本 |
| 视频 ReAct | `MMCoreAgent.run()` 最多 `max_iterations`，最后强制 `finish`；`stream_run()` 为生成器 | 任务运行核心 + 视频模块 | 没有外部取消 token、deadline、任务状态持久化；`response=None` 直接返回 |
| add_batch | `ThreadPoolExecutor(max_workers=16)`，future 异常记录后继续，结尾 flush | 运行核心监督 + 记忆模块编排 | 没有任务 id、失败集合返回、背压、超时或取消；异常可能只进日志 |
| caption embedding | `multiprocessing.Pool(os.cpu_count() // 2)`，批量 128，失败最多重试 3 次 | 运行核心任务 + embedding provider | `os.cpu_count() // 2` 在低核/异常环境可能为 0；进程池取消/崩溃恢复未定义 |
| 评测任务 | LongMemEval 每题创建临时工作目录，`finally shutil.rmtree` | L4 评测任务，临时资源由运行核心托管 | 评测 scope 没有时间/会话元数据，模型网络调用没有本项目统一 deadline |

**资源 ownership**：调用者拥有输入消息/视频路径；记忆模块拥有候选对象和抽取结果；provider 拥有 HTTP client、FAISS/DB/VDB 句柄；运行核心应拥有线程/进程/临时目录/取消 token；网关拥有连接/流式响应。当前源码没有显式 ownership transfer，也没有统一 `close()`/`abort()`/`release()` 协议。

### 15.7 失败、超时、取消、崩溃与释放矩阵

| 场景 | 当前实现/证据 | 当前等级 | 底座补法 |
|---|---|---|---|
| 空/非法 add 参数 | `Mem0ValidationError`：无 scope、非法 `memory_type`、消息类型（`mem0.py:282-310`）；MCP 无 text/messages 返回 `invalid_arguments` | 已实现，测试覆盖主要契约 | 网关统一错误码，保留字段级 detail |
| LLM 抽取异常 | `add()` 的 `_extract_summary_from_messages()` 未在 direct path 捕获；batch future 捕获后记录并继续（`:428-477`） | 部分实现 | 任务级失败结果、可重试分类、失败事件和调用者可见的 partial 状态 |
| 摘要解析异常/空响应 | parser 异常变空列表；空列表可导致“成功返回但无记忆” | 部分实现 | `EMPTY_EXTRACTION` 明确结果，不把空写当成功 |
| 融合 LLM 异常/非法 JSON | `_flush_buffer` 异常回退 `new_summaries`；`_sync_memory_to_vector_store` 异常后 `stored_summaries=[]` | 部分实现且语义不一致 | 统一 provider error；回退必须记录策略、原文候选和是否降级 |
| 向量/数据库失败 | 依赖 Mem0 helper，TeleMem 不做事务包装 | 待核 | 支持库返回稳定错误；运行核心负责 rollback/重试/断点 |
| 重复写/重复事件 | 没有 idempotency key；add_batch 每个 scope 都写一次；VDB 仅以文件存在跳过 | 未实现 | 事件 id/幂等键/索引 manifest/提交前后对账 |
| 网络超时 | `telemem` 层没有显式 timeout/deadline；provider client 行为由 OpenAI/Mem0/视频 helper 决定 | 未确认 | 运行核心传 deadline，provider 必须硬超时并归还连接/线程 |
| 主动取消 | 无 API 参数、Future cancel、Pool terminate 或 MCP cancellation handler | 未实现 | request cancellation → task cancel → provider abort → drain/join → 释放证据 |
| 线程/进程崩溃 | batch 线程异常只 log；caption worker 给空结果；视频/embedding pool 由 context manager 回收 | 部分实现 | 子进程独立进程组、退出码、重启上限、未完成状态恢复 |
| 写文件中途崩溃 | ckpt/captions/VDB 采用普通 `open(...,"w")`/库 save；无临时文件+fsync+rename | 未实现 | 原子写、摘要/manifest、损坏隔离、恢复/重建策略 |
| provider 资源关闭 | `VideoCapture.release()` 只在正常循环后；MCP singleton 无 close；Mem0 连接生命周期外置 | 未确认 | 创建者/持有者/转移者显式登记，success/failure/timeout/cancel/crash 全路径 release |
| 客户端断开/流式停止 | `stream_run()` 是普通 generator，没有 finally 清理和客户端断开回调；MCP SDK 处理传输层但不取消后端任务 | 未实现 | 网关断连传播取消，排空事件并释放模型/线程/文件 |
| 评测临时目录 | `retrieve_telemem()` 的 `finally shutil.rmtree(ignore_errors=True)` | 已实现，范围仅评测 | 统一临时资源登记，删除失败要留下残留证据而非忽略 |

这里的“已实现”只表示源码有分支或离线测试有断言，不表示真实外部 provider、崩溃恢复或安全边界已通过验收。

### 15.8 来源、时间、权限和可审计字段

| 维度 | 当前事实 | 风险/迁移要求 |
|---|---|---|
| 来源 | 普通文本 metadata 只自动加入 user/agent/run；raw 路径加入 message `role`；视频 VDB 保存视频文件根和 clip 时间 | 没有强制 `source_type/source_uri/source_message_id/source_session_id`；适配层必须补来源字段并禁止下游覆盖系统字段 |
| 时间 | 视频 clip 有 `time_start_secs/time_end_secs`；LongMemEval 输入有 `haystack_dates` 但未传入；评测只计 `time.time()` 延迟 | 没有统一事件时间、摄取时间、更新时间、时区或单调时钟；跨时间检索不能声明已支持时间排序 |
| 身份/权限 | `user_id/agent_id/run_id` 仅作为 filters/metadata；MCP 默认用户和 delete-all 显式 scope | scope 隔离不等于认证/授权；没有 owner、租户、角色、ACL、撤销、审计主体。外部部署必须由统一网关补齐 |
| 凭证 | LLM/embedder/VLM API key 来自 config 或 `${ENV}` 展开；`load_config()` 只允许值层替换（`utils.py:13-59`） | 不把 key 写入记忆 metadata/事件；支持库应提供脱敏和 secret reference，日志不得打印 prompt 中的密钥 |
| 证据 | logger、MCP error detail、Mem0 history、评测 JSON | 没有统一 request/task/event/evidence id，也没有成功/失败/拒绝都留痕的账本 |

**明确结论**：TeleMem 具备“按 scope 传递”的最小来源边界，不具备“按时间、来源、权限、证据传递”的平台契约。第三轮只能吸收 scope 语义，不能吸收其缺失的安全/审计假设。

### 15.9 L0-L4 归层与当前映射

```text
L4 任务/应用/评测：examples/、LongMemEval、LangChain/LlamaIndex、DeepSeek Harness
    ↓ 只提交标准消息/查询/任务参数，不持有 provider 和索引句柄
L3 网关/服务：Python 公开面、MCP 8 tools、stdio/Streamable HTTP/SSE、CLI
    ↓ 鉴权、限流、请求 id、错误/流式协议、调用记忆模块公开入口
L2 运行核心：任务监督、buffer/queue、deadline/取消、重试、崩溃恢复、资源释放、事件/证据
    ↓ 以一次可审计执行调用记忆模块；当前 TeleMem 没有独立实现
L1 记忆模块：TeleMemory scope、消息/事件抽取、融合、文本 search；视频记忆模块/MMCoreAgent
    ↓ 只通过支持库能力契约读写，不直连未登记外部服务
L0 支持库/提供者：Mem0/FAISS/history、embedding/LLM/VLM client、NanoVectorDB、OpenCV、yt_dlp、文件/JSON、MCP SDK
    ↓ 外部数据库、模型服务、文件系统和第三方 SDK 的生命周期/错误/版本隔离
```

- **L0** 是资源和 provider 边界，不是“把所有第三方 import 复制进支持库”；`mem0ai` 私有 helper 依赖必须在适配层隔离，并以版本契约锁定。
- **L1** 的公共能力 id 应类似 `memory.extract_events`、`memory.store`、`memory.search`、`memory.history`、`video.index`、`video.search`；`TeleMemory` 是模块 owner，不能让 MCP 或 examples 自己实现相似逻辑。
- **L2** 应承接当前散落的 `ThreadPoolExecutor`、`multiprocessing.Pool`、buffer lock、重试和 generator 生命周期；不能再建一个与平台已有任务系统平行的 TeleMem task engine。
- **L3** 复用现有 MCP 工具契约，但把 `_call()` 的异常包装升级为统一网关错误；MCP annotation 不能替代授权、幂等和超时执行。
- **L4** 只负责场景、编排和评测，不得被用作生产数据 owner；`baselines/` 的 RAG/Mem0/MemoBase 等目录是比较基线，不是 TeleMem 运行时底座。

### 15.10 唯一可审计链路

平台化后的唯一链路应收敛为一条，所有 Python/MCP/HTTP/评测入口都走它：

```text
L4 caller/task
  → L3 网关适配（校验请求、认证/授权、request_id、输入大小/截止时间）
  → L2 运行核心提交（task_id、租约、取消 token、预算、资源登记）
  → L1 记忆模块公开入口
       ├─ message normalization + scope/来源/时间补全
       ├─ extraction/fusion/search/history 领域编排
       └─ video memory only through its module contract
  → L0 支持库能力注册表
       ├─ LLM/embedding/VLM provider
       ├─ vector/history store provider
       └─ file/JSON/NanoVectorDB/OpenCV provider
  → 统一结果/事件/证据
  → L2 release + commit/recovery record
  → L3 response/stream
  → L4 caller
```

唯一链路铁律：

1. 一个原子能力一个 owner、一个能力 id、一个公开入口；`_create_memory`、`_search_vector_store` 等 Mem0 私有 helper 只能被 L0 适配层封装，不能泄漏到 L1/L3。
2. 一个记忆事实一个权威写 owner；候选 buffer、事件 history、向量索引和视频制品分别有明确 owner，禁止旁路写库或旁路写 JSON。
3. 资源责任沿链路传递：创建者登记，转移显式，正常完成/业务失败/超时取消/宿主崩溃都必须有释放与残留验证。
4. 任何 fallback 必须返回“降级/部分成功/不可用”状态并写证据；不能像当前 `_sync_memory_to_vector_store()` 那样在 JSON/LLM 失败后只得到空列表而保持成功外观。
5. 网关只做协议、权限和流控；记忆模块只做记忆语义；运行核心只做执行治理；支持库只做外部资源边界。不得在四层之间复制第二套转换、错误码、重试或日志。

### 15.11 第三轮复用/升级/新建/废弃裁决

| 候选模式 | 裁决 | 原因 |
|---|---|---|
| `user_id` + `events` 的角色/共享事件 scope | **吸收** | `add_batch` 双写、`search` 双 scope 有离线契约测试；迁移时补 schema/source/time/ACL 字段 |
| `run_id` 作为跨会话协议 | **升级** | 当前只是 metadata/filter 和 buffer key；保留兼容输入，新增 session/事件/幂等/版本契约 |
| `extract_events_from_text` 的多格式回退解析 | **吸收为模块能力** | 领域价值明确；须统一空结果、解析失败和模型版本证据 |
| buffer + cosine cluster + LLM fusion | **升级后吸收** | 语义策略可复用；buffer 必须纳入 L2 任务状态、deadline、flush 事务和 crash recovery |
| Mem0 私有 `_create_memory`/`_search_vector_store` 直调 | **隔离/升级** | 不能让平台层直接依赖私有 API；只允许 L0 provider adapter 包装，版本漂移要可探测 |
| MCP 8 工具、structured output、stdout 隔离 | **吸收** | 已有离线协议测试；接入统一网关认证、超时、取消、错误和审计 |
| MCP 默认用户与 delete-all 显式 scope | **吸收但不当授权** | 防误操作有价值；不替代身份/租户/角色 ACL |
| 视频 frames→captions→NanoVectorDB | **隔离为视频记忆模块 + provider** | 与文本索引/事件模型分离，资源重、第三方多、故障面不同；通过统一记忆查询契约接入 |
| LongMemEval/`baselines/` | **隔离** | 是任务/评测层，不是公共生产能力；保留作为验收输入 |
| 普通 JSON 写 ckpt/captions/VDB、存在即跳过 | **废弃为生产写法** | 无原子提交、manifest、损坏探测和恢复证据；可在离线实验中保留但不能升级为底座 |
| 依赖 skip 的 provider integration | **待核** | 测试明确由环境变量门控，当前没有真实外部服务证据；不能计为 provider 已通过 |

### 15.12 验证等级与剩余风险

本轮采用以下 L0-L4 之外的证据等级，避免“源码存在”被写成“运行通过”：

| 等级 | 含义 | TeleMem 当前证据 |
|---|---|---|
| S0 | 仅目录/声明/文档线索 | provider 配置、README、发布/部署声明 |
| S1 | 目标源码路径已读并可定位 | `telemem/mem0.py`、`utils.py`、`mcp/server.py`、MM 源码 |
| S2 | 离线测试直接覆盖 | `tests/test_contract.py`、`tests/test_mcp.py`、provider 配置测试 |
| S3 | 真实本地 provider/进程/文件链实跑 | 本轮未执行，不能宣称通过 |
| S4 | 断线、超时、取消、强杀、重启、残留审计 | 本仓库没有充分实现/证据，全部待补 |

第三轮不能正式背书的事项：Mem0 真实 schema/事务/并发/恢复；模型和 embedding endpoint timeout/cancel；MCP Streamable HTTP 真实网络认证；视频 VLM/embedding/多进程崩溃恢复；索引文件原子性；跨时间日期保留；多租户权限；singleton 关闭；客户端断开时 generator/后端任务清理。

后续装配前的验收契约必须至少包含：

```text
输入：消息 + user/agent/session/run scope + source/time + idempotency key + deadline/cancel token
成功：统一 memory/history/result，带 memory_id、source、time、scope、task/evidence id
失败：稳定错误码，区分参数非法、provider 不可用、超时、取消、冲突、部分成功、恢复中
释放：线程、进程、HTTP、DB/向量句柄、临时文件、buffer、流式连接均在四种终态可验证无界残留
恢复：任意提交前/提交后强杀只能得到旧版或新版，不得半条记忆/半个索引/孤儿任务
```

本节的结论是“第三轮底座输入”，不是对系统工程平台的生产改造授权；任何公共底座新增能力仍需先登记需求、检索现有能力、确定唯一 owner、占用租约、编写消费者契约，再进入装配和验证。

## 16. 第三轮证据补充索引

- scope/缓冲/抽取/融合/搜索：`telemem/mem0.py:60-216,218-360,362-550,591-688`
- 配置、环境变量和阈值：`telemem/configs.py:7-46`；`telemem/utils.py:13-59`
- 摘要/事件解析：`telemem/utils.py:62-331`
- MCP singleton、8 工具、错误/默认 scope、传输：`telemem/mcp/server.py:68-153,156-383,386-425`
- 视频帧/字幕/多进程 caption/重试/ckpt：`telemem/mm_utils/video_utils.py:140-184`；`telemem/mm_utils/frame_caption.py:260-322,330-405,411-461`
- 视频 VDB/embedding/附加数据：`telemem/mm_utils/build_database.py:263-367`
- 视频 ReAct、最大迭代、流式和并行任务：`telemem/mm_utils/core.py:37-193,198-251`
- LongMemEval 跨 session ingest/search/临时目录：`baselines/longmemeval/run_telemem.py:116-147`
- 离线契约与 scope/search 测试：`tests/test_contract.py:53-75,99-242`
- MCP 工具/默认 scope/删除保护/错误/协议测试：`tests/test_mcp.py:48-89,136-383`
- provider 结构/环境变量/外部 integration 门控：`tests/test_providers.py:43-223`
- 依赖与 CLI entry points：`pyproject.toml:31-73`
- 当前 Git 基线：`a8e537c7064e00e3f3d4593f8408f32bb528d10d`，2026-08-17；目标代码图探测结果为无 `.codegraph/`。
