# MemVerse 架构建档

> 本文是本仓库唯一正式架构文档，基于当前磁盘源码静态读取建立。`细探-MemVerse.md` 是已有施工材料，本轮只吸收其中被源码核实的结论，不替代本文。
>
> 范围：只读架构建档；未安装依赖、未启动服务、未运行测试、未修改已有源码/依赖/测试/配置、未生成构建产物、未提交 Git。

## 1. 项目定位

MemVerse 是面向终身学习 Agent 的多模态记忆框架：把文本、图像、视频、音频转成可写入记忆库的文本，再通过三类长期记忆提示词生成 core / episodic / semantic 记忆，使用嵌入、向量检索和 LightRAG 知识图谱支持查询，并可选调用独立的参数化记忆模型。对外提供一个 FastAPI HTTP 入口和一个 FastMCP HTTP 入口；`ClawMemVerse` 另提供 OpenClaw 的本地 Markdown 文件同步/读取适配。

源码事实：顶层 README 将项目描述为跨文本、图像、音频、视频的连续记忆系统，并给出 `app:app`、`/insert`、`/query` 和 Docker 启动方式（`README.md:24-33, 129-176, 178-243`）。实际入口和调用链以本文的源码证据为准。

**不是当前实现的内容：**仓库没有发现 `pyproject.toml`、`setup.py` 或 `package.json`，没有独立发布的 Python SDK；短期记忆类也没有接入顶层编排链。参数化训练/API 是单独的实验/服务分支，而不是默认 FastAPI 服务启动时自动拉起的组件。

## 2. 总体文本流程图

```text
                    ┌──────────────────────────────────────────────┐
                    │ 客户端 / Agent                               │
                    │ curl、FastAPI 表单、FastMCP Client、OpenClaw │
                    └──────────────────────┬───────────────────────┘
                                           │
                         ┌─────────────────┴─────────────────┐
                         │                                   │
                         ▼                                   ▼
              app.py: FastAPI                         mcp_server.py: FastMCP
              POST /insert, /query                    /mcp: insert_memory/query_memory
                         │                                   │
                         └─────────────────┬─────────────────┘
                                           ▼
                              orchestrator.py
                 ┌────────────────────────┼────────────────────────┐
                 │                        │                        │
                 ▼                        ▼                        ▼
        initialize_rag()             handle_insert()           handle_query()
                 │                        │                        │
                 │                        │                        ├─ 可选 PM_BASE_URL
                 │                        │                        │  → 参数化记忆服务
                 │                        │                        │  → GPT 相关性判断
                 │                        │                        │
                 │                        ├─ 保存上传文件          ├─ mem_core.aquery()
                 │                        ├─ 图像 → GPT-4o caption  │  QueryParam(mode)
                 │                        ├─ 视频 → ffmpeg 帧 → caption
                 │                        ├─ 音频 → Whisper 转写    │
                 │                        ├─ conversation.json       ▼
                 │                        └─ update_long_term_memory()
                 │                                   │       最终回答
                 │                                   │       ← OpenAI gpt-4o-mini
                 │                                   ▼
                 │                         build_memory.process_memory()
                 │                         ┌────────┼────────┐
                 │                         │        │        │
                 │                         ▼        ▼        ▼
                 │                  core_memory  episodic  semantic
                 │                  prompt+JSONL prompt+JSONL prompt+JSONL
                 │                         │        │        │
                 │                         └────────┼────────┘
                 │                                  ▼
                 │                       每类一个 LightRAG 实例
                 │                       core / episodic / semantic
                 │                                  │
                 │                    ┌─────────────┼─────────────┐
                 │                    ▼             ▼             ▼
                 │              JsonKVStorage  NanoVectorDB  NetworkX graph
                 │              文档/实体/关系   embedding      graph_*.graphml
                 │                                  │
                 │                                  ▼
                 │                    local/global/hybrid/naive/mix
                 │
                 └─ 启动时 initialize_share_data → initialize_storages

  OpenClaw 旁路：Docker 内 memory_chunks/*.json
             → ClawMemVerse/skill/convert_json_to_md.py
             → OpenClaw workspace/memory/*.md
             → memverse-memory SKILL.md 通过本地文件读取
```

## 3. 真实分层与目录地图

以下按运行职责分层，不把仓库目录名直接当作已实现的独立服务边界。

### 3.1 入口与交付层

| 层 | 真实文件 | 职责 |
|---|---|---|
| HTTP 应用入口 | `app.py` | 创建 `FastAPI`；启动事件初始化 RAG；暴露 `/insert`、`/query`。 |
| MCP 入口 | `mcp_server.py` | 创建 `FastMCP("memverse")`；懒初始化；暴露 `insert_memory`、`query_memory`；主程序监听 5250。 |
| MCP 客户端示例 | `mcp_client.py` | 连接 `http://127.0.0.1:5250/mcp`，调用两个 MCP 工具。 |
| 容器启动编排 | `entrypoint.sh`, `dockerfile` | 后台启动 MCP，再以 `uvicorn app:app` 启动 FastAPI；暴露 8000/5250。 |
| OpenClaw 适配 | `ClawMemVerse/skill/*` | 将容器 JSONL 导出为本地 Markdown，并以 Skill 说明读取方式；不是 MemVerse 服务内的 API SDK。 |

### 3.2 应用编排层

`orchestrator.py` 是当前真正的应用服务/用例编排层（`orchestrator.py:12-22, 116-123, 143-176, 181-299`）：

- 从 `MemoryKB` 导入多模态处理、记忆构建和本地 LightRAG。
- 维护三个 RAG 实例：`mem_core`、`mem_epi`、`mem_sem`。
- `initialize_rag()` 创建 MMKG 的 `core`、`episodic`、`semantic` 工作目录，并初始化共享管线状态。
- `handle_insert()` 生成 ID、保存文件、做 caption/transcript、追加会话记录并触发长期记忆构建。
- `handle_query()` 先按 `use_pm` 选择参数化记忆，再决定是否走长期 RAG，最后用主 OpenAI 客户端生成回答。

### 3.3 多模态摄入层

- `MemoryKB/User_Conversation/process_image.py`：Pillow 读图，转 JPEG Base64，通过 HTTP OpenAI-compatible chat completion 调 GPT-4o 图像描述（`process_image.py:9-47, 50-63`）。
- `process_video.py`：调用外部 `ffmpeg` 按 FPS 抽帧，再逐帧图像描述，最后调用 GPT-4o-mini 汇总（`process_video.py:14-31, 33-59, 61-84`）。
- `process_audio.py`：OpenAI Python SDK 的 `audio.transcriptions.create(model="whisper-1")` 转写（`process_audio.py:5-29`）。
- 文本本身由顶层 `query` 字段直接保留；图像/视频/音频结果写入同一条入口记录的 caption 字段。

### 3.4 记忆构建层

`MemoryKB/build_memory.py` 将一条入口记录转换为三份长期记忆 JSONL：

1. 校验 `id`、`query`、`videocaption`、`audiocaption`、`imagecaption` 五个字段（`build_memory.py:54-60`）。
2. 拼成 `Query:/Video:/Audio:/Image:` 文本（`build_memory.py:69-78`）。
3. 调用 `text-embedding-3-small` 获取向量；可选用余弦相似度和 GPT 分类 `add/update/remain`（`build_memory.py:21-31, 80-133`）。
4. 使用三个 system prompt 分别调用默认 `gpt-4o-mini`，写入 `id`、UTC `timestamp`、`input_text`、`output_text`、`embedding`（`build_memory.py:135-163`）。

对应文件是：

```text
MemoryKB/Long_Term_Memory/system/
├── core_memory_agent.txt
├── episodic_memory_agent.txt
└── semantic_memory_agent.txt

MemoryKB/Long_Term_Memory/memory_chunks/
├── core_memory.json
├── episodic_memory.json
└── semantic_memory.json
```

三个 prompt 的语义边界由文件内容定义：核心资料/偏好、时间顺序事件、概念/对象知识；它们要求只记录输入中存在或可靠推断的信息（各 prompt 文件）。

### 3.5 长期记忆检索层：嵌入 + LightRAG

仓库内嵌了一份 LightRAG 实现，入口是 `MemoryKB/Long_Term_Memory/Graph_Construction/lightrag/__init__.py`，版本常量为 1.4.7（`__init__.py:1-5`）。顶层编排使用：

- `LightRAG(working_dir=..., embedding_func=openai_embed, llm_model_func=gpt_4o_mini_complete)`（`orchestrator.py:116-123`）。
- 默认存储声明为 `JsonKVStorage`、`NanoVectorDBStorage`、`NetworkXStorage`、`JsonDocStatusStorage`（`lightrag/lightrag.py:114-130`）。
- 初始化依次打开 full docs、chunks、entities、relations、三类向量库、图、LLM cache、doc status（`lightrag.py:538-557`）。
- 插入通过 `ainsert()` 入队并处理文档管线（`lightrag.py:857-890`）；管线将文本切块、LLM 抽实体/关系、两阶段合并实体和关系并写入图与向量库（`operate.py:1185-1400, 1473-1649`）。
- 查询由 `aquery()` 按 `QueryParam.mode` 分派到知识图谱/向量混合查询、naive 查询或 bypass 直通 LLM（`lightrag.py:1984-2064`）。顶层当前只查询 `mem_core`（`orchestrator.py:218-223`），启动时虽创建三实例，但 `update_long_term_memory()` 的实现将三份输出分别插入三个实例的代码路径需要结合运行时文件状态进一步验证（`orchestrator.py:168-176`）。
- 图存储实现 `NetworkXStorage` 使用 NetworkX，工作目录下加载/写入 `graph_<namespace>.graphml`，并通过异步锁和更新标志做进程间重载（`kg/networkx_impl.py:24-70, 72-95, 131-151`）。

### 3.6 参数化记忆层

这是独立的训练与推理分支：

- 训练数据：`MemoryKB/Paramatric_Memory/paramemory.json`，样例字段为 `id/query/retrieved`。
- `ParametricMemoryDataset` 将 query 生成固定模板，tokenizer 以 `retrieved` 为 target，输出固定长度的 `input_ids/attention_mask/labels`（`parametric_train.py:26-72`）。
- `train(args)` 从 `Qwen/Qwen2.5-7B` 加载模型，训练后保存 `checkpoint_best_<timestamp>`、`model_latest` 链接和最终模型（`parametric_train.py:107-144, 175-270`）。
- `parametric_api.py` 使用 Transformers 的 CausalLM，按 `checkpoint_best_*` 最新修改时间热加载；`POST /generate` 接收 `QueryRequest`，另有 `/health`、`/model_info`、`/refresh_model`（`parametric_api.py:22-27, 32-84, 130-183, 185-237`）。独立运行时监听 8001（`parametric_api.py:240-267`）。
- 顶层查询通过 `PM_BASE_URL`/`PM_API_KEY` 以 OpenAI-compatible chat completion 调用 `model="parametric-memory"`，再用主 LLM 判断相关性；相关时才跳过 RAG（`orchestrator.py:181-216, 270-289`）。

### 3.7 嵌入的 LightRAG Server 子系统

`MemoryKB/.../lightrag/api/` 是随仓库复制的完整 FastAPI/WebUI/兼容接口子系统，不等同于顶层 `app.py`：

- `lightrag_server.py:create_app()` 组装文档、查询、图、Ollama API 路由，并提供 `/docs`、`/redoc`、`/health` 等（`api/lightrag_server.py:97-212, 507-520, 522-595`）。
- 查询路由的请求模型支持 `local/global/hybrid/naive/mix/bypass`、token budget、历史、ID 过滤、rerank 等；提供 `/query` 和 `/query/stream`（`api/routers/query_routes.py:19-128, 137-224`）。
- 图路由提供 `/graph/label/list`、`/graphs`、实体存在检查、实体/关系编辑（`api/routers/graph_routes.py:28-173`）。
- 文档路由以 `/documents` 为前缀，提供文本/文件导入、扫描、状态等模型与路由（`api/routers/document_routes.py:56-59, 137-224`）。
- 该子系统是否由本仓库的顶层 Docker 入口直接启用：**未确认**；顶层 `entrypoint.sh` 明确只启动 `mcp_server.py` 和 `uvicorn app:app`（`entrypoint.sh:4-10`）。

## 4. 核心数据模型与持久化契约

### 4.1 入口记录（应用自定义字典）

`handle_insert()` 构建的核心记录为：

```json
{
  "id": "<UTC时间字符串>_<UUID>",
  "query": "原始文本",
  "videocaption": "视频摘要或 null",
  "audiocaption": "音频转写或 null",
  "imagecaption": "图像描述或 null"
}
```

证据：`orchestrator.py:107-111, 252-268`。该对象不是 Pydantic/ORM 模型，而是普通 Python dict。

### 4.2 会话记录

- `append_to_conversation()` 读取 `MemoryKB/User_Conversation/conversation.json`，解析失败则重置为空列表，追加入口记录后以 UTF-8、缩进 JSON 数组覆盖写回（`orchestrator.py:96-105`）。当前该文件实际为空。
- `build_memory.py` 的脚本入口却按“每行一个 JSON”读取名为 `conversation.json` 的文件（`build_memory.py:166-185`），因此会话数组格式与该脚本入口的 JSONL 读取方式存在未解决的格式漂移。

### 4.3 长期记忆 JSONL 记录

`process_memory()` 实际生成的单行记录字段为：

```json
{
  "id": "入口记录 id",
  "timestamp": "UTC ISO 时间",
  "input_text": "Query/Video/Audio/Image 拼接文本",
  "output_text": "对应 system prompt 的 LLM 结果",
  "embedding": [0.0, 0.0]
}
```

文件扩展名是 `.json`，但写入路径使用逐行 `json.dumps(...)+"\\n"`（`build_memory.py:150-161`）；当前三个 `memory_chunks/*.json` 实际均为空，不能从样本数据确认完整运行后内容。

### 4.4 LightRAG 内部模型

| 模型/契约 | 字段/作用 | 路径 |
|---|---|---|
| `QueryParam` | `mode`、上下文/提示开关、`top_k`、token 上限、关键词、历史、ID 过滤、rerank 等 | `MemoryKB/Long_Term_Memory/Graph_Construction/lightrag/base.py:82-167` |
| `TextChunkSchema` | `tokens`、`content`、`full_doc_id`、`chunk_order_index` | `.../lightrag/base.py:72-77` |
| `KnowledgeGraphNode` | `id`、`labels`、`properties` | `.../lightrag/types.py:12-16` |
| `KnowledgeGraphEdge` | `id`、`type`、`source`、`target`、`properties` | `.../lightrag/types.py:18-23` |
| `KnowledgeGraph` | `nodes`、`edges`、`is_truncated` | `.../lightrag/types.py:26-29` |
| `StorageNameSpace`/`BaseVectorStorage`/`BaseGraphStorage` | 存储初始化、查询、upsert、图节点/边操作抽象接口 | `.../lightrag/base.py:169-260` 及后续定义 |
| `ParametricMemoryDataset` | `raw_data`、tokenized query/target 样本 | `MemoryKB/Paramatric_Memory/parametric_train.py:26-72` |
| `QueryRequest`（参数化服务） | `query`、`max_new_tokens`、`temperature`、`top_p` | `MemoryKB/Paramatric_Memory/parametric_api.py:130-134` |
| `QueryRequest`（LightRAG API） | query、检索模式、token budgets、history、ids、rerank 等 | `.../lightrag/api/routers/query_routes.py:19-128` |

## 5. 核心数据流

### 5.1 插入流

1. 客户端向 `POST /insert` 提交必填 `query` 和可选 multipart 文件；`app.py:17-23` 直接转给 `handle_insert()`。
2. `handle_insert()` 生成时间+UUID ID；分别把文件写入 `MemoryKB/User_Conversation/{video,audio,image}/`。
3. 多模态处理器生成 caption/transcript；结果和原 query 组成入口 dict。
4. 记录追加到 `conversation.json`。
5. `bm.process_memory([entry])` 对每个 memory prompt 调 embedding 和 LLM，写入三份 JSONL。
6. `insert_chunks_from_json()` 读取每条 JSON 的 `output_text` 并调用三个 LightRAG 实例的 `ainsert()`，将文本切块、抽取实体/关系、写入 KV、向量与图存储。
7. 后续 `/query` 使用长期图/向量检索结果和可选参数化结果，交给主 LLM 生成回答。

### 5.2 查询流

```text
query + mode + use_pm
          │
          ├─ use_pm=false ───────────────────────────────┐
          │                                               │
          └─ use_pm=true → PM /generate → relevant? ─yes─┤
                                      │ no                │
                                      ▼                   ▼
                           mem_core.aquery(QueryParam) → memory_text
                                                              │
                                                              ▼
                                                     OpenAI gpt-4o-mini
                                                              │
                                                              ▼
                             {query, mode, pm_*, rag_memory, final_answer}
```

`handle_query()` 的返回结构和分支见 `orchestrator.py:270-299`。顶层代码只调用 `mem_core.aquery()`，并没有对 episodic/semantic 实例分别执行查询。

## 6. API、CLI、MCP、SDK 表面

### 6.1 顶层 FastAPI HTTP API

| 方法/地址 | 入参 | 出参/行为 | 证据 |
|---|---|---|---|
| `POST /insert` | multipart `query` 必填；`video`/`audio`/`image` 可选 | 成功 `{status:"ok", entry:...}`；捕获异常返回 `{status:"error", message:...}` | `app.py:17-23` |
| `POST /query` | form `query` 必填；`mode` 默认 `hybrid`；`use_pm` 默认 `false` | `{status:"ok", query, mode, pm_*, rag_memory, final_answer}` | `app.py:25-28`, `orchestrator.py:270-299` |

README 的本地命令是 `uvicorn app:app --host 0.0.0.0 --port 8000 --reload`（`README.md:154-177`）。

### 6.2 顶层 MCP

- 服务：`python mcp_server.py`，FastMCP HTTP 监听 `0.0.0.0:5250`，地址路径由客户端写为 `/mcp`（`mcp_server.py:4-7, 22-43`）。
- 工具：`insert_memory(query, image=None, audio=None, video=None)`、`query_memory(query, mode="hybrid", use_pm=True)`（`mcp_server.py:22-40`）。
- 客户端示例：`python mcp_client.py`，调用两个工具（`mcp_client.py:4-19`）。
- 这是 MCP 协议入口，不是独立 Python SDK；仓库未找到 SDK 打包元数据。

### 6.3 嵌入式 LightRAG API

LightRAG 自带的 `api/lightrag_server.py` 是另一套 API 工厂，包含 `/documents/*`、`/query`、`/query/stream`、`/graphs`、`/graph/*`、`/api` 下的 Ollama 兼容接口、`/docs`、`/redoc`、`/health`。它的存在已由源码确认，但顶层 Docker 是否启动它未确认；不要把这些路由误记为顶层 `app.py` 路由。

### 6.4 CLI/脚本

| 命令/脚本 | 实际职责 |
|---|---|
| `uvicorn app:app ...` | 顶层 FastAPI 服务 |
| `python mcp_server.py` | 顶层 MCP HTTP 服务 |
| `python mcp_client.py` | MCP 调用演示 |
| `python MemoryKB/Long_Term_Memory/Graph_Construction/lightrag_openai_demo.py` | 独立 LightRAG 三库初始化、插入、四模式查询演示 |
| `python MemoryKB/Paramatric_Memory/parametric_train.py ...` | Qwen 参数化记忆训练/定时训练，默认无限循环 |
| `python MemoryKB/Paramatric_Memory/parametric_api.py` | 参数化模型服务，默认 8001 |
| `python ClawMemVerse/skill/convert_json_to_md.py` | 从 Docker 拷贝三类 memory JSONL 并导出 MD；脚本含硬编码本地路径，需按部署环境调整 |
| `entrypoint.sh` | 容器内并行 MCP + FastAPI 启动 |

## 7. 技术栈与依赖事实

### 7.1 主栈

- Python：README 宣称 3.10+；Docker 基础镜像是 Python 3.11-slim（`README.md:8, 132-150`；`dockerfile:1-15`）。
- Web：FastAPI + Uvicorn；表单上传依赖 `python-multipart`。
- Agent 互操作：FastMCP（代码导入，但顶层 `requirements.txt` 未声明该包）。
- LLM/多模态：OpenAI Python SDK、OpenAI-compatible HTTP、GPT-4o/GPT-4o-mini、Whisper API。
- 检索/图：本地 LightRAG 1.4.7、NetworkX、NanoVectorDB、tiktoken、Pydantic。
- 参数化记忆：PyTorch + Transformers + Qwen/Qwen2.5-7B（代码使用；顶层依赖清单未声明 torch/transformers）。
- 文件/媒体：Pillow、外部 `ffmpeg`；Dockerfile 没有安装 ffmpeg，视频链路是否可用未确认。
- 部署：Docker；环境文件还提供一个较重且包含 Linux/conda 构建锁定信息的 `environment.yml`。

### 7.2 顶层显式 requirements.txt

`requirements.txt` 只列出：`fastapi`、`uvicorn`、`python-multipart`、`openai`、`numpy`、`Pillow`、`requests`、`json_repair`、`pipmaster`、`nano_vectordb`、`tiktoken`、`networkx`、`dotenv`、`tenacity`（`requirements.txt:1-14`）。

`environment.yml` 实际锁定的是 Python 3.13/Linux conda 环境并通过 pip 段补充 `openai`、`nano-vectordb`、`networkx`、`python-dotenv` 等（`environment.yml:1-180`）。它与 README 的 Python 3.10+ 和 Docker Python 3.11 不是同一套可复现环境，需后续裁决。

## 8. 测试与验证现状

### 8.1 已发现的测试表面

- 仓库没有发现 `tests/`、测试文件名或 `pytest` 测试套件。
- 根目录 `test.sh` 只有一条 `curl` 查询命令，目标是已运行的 `http://127.0.0.1:8000/query`，不是自动化测试（`test.sh:1`）。
- `README.md` 仅给出 curl 手工插入/查询示例；`mcp_client.py` 是 MCP 手工演示。
- 本轮没有运行这些命令，因为用户明确禁止启动服务/生成运行产物，且没有进行依赖安装。

### 8.2 当前可确认的验证边界

已做静态证据核对：真实顶层目录、README、规则文件搜索、依赖清单、Docker/入口脚本、顶层 API/MCP、编排、多模态、三类记忆构建、参数化训练/API、嵌入 LightRAG 核心/数据类型/API、OpenClaw 适配和测试脚本。未做 import、类型检查、HTTP、MCP、外部 API、ffmpeg、模型加载或持久化读写验证。

## 9. 未确认项与风险清单

以下是源码阅读后保留的风险，不把静态推断写成已验证故障：

1. **依赖不闭合（重要）**：`mcp_server.py` 导入 `fastmcp`，视频需要 `ffmpeg`，参数化分支需要 `torch`/`transformers`；这些没有出现在顶层 `requirements.txt`，Dockerfile 也没有安装 ffmpeg。LightRAG API 还导入 `ascii_colors`、`aiofiles` 等额外包。未安装/未 import 验证。
2. **多模态调用签名漂移（重要）**：`orchestrator.handle_insert()` 按 `(query, video, audio, image)` 调用处理器；MCP `insert_memory()` 按 `(query, image, audio, video)` 传给同一函数（`mcp_server.py:23-31`）。同时顶层把 `process_video(video_path, MAIN_BASE_URL, MAIN_API_KEY)`、`process_audio(audio_path, MAIN_BASE_URL, MAIN_API_KEY)` 当作多参数调用，而当前处理器签名分别是 `(video_path, fps=1, prompt=None)` 和 `(file_path)`。没有运行时测试，具体暴露位置和影响需后续隔离验证。
3. **图像错误分支疑似未定义变量**：`process_image.py:37-47` 的失败分支引用 `image_path.name`，该函数参数名是 `image`；未通过故障响应验证。
4. **长期记忆格式漂移**：`.json` 文件按 JSONL 写入，但 `conversation.json` 的追加函数按 JSON 数组读写；`build_memory.py` 脚本入口又逐行解析 `conversation.json`。这几个路径是否在当前默认入口共同使用，需验证。
5. **长期查询覆盖面有限**：三个 LightRAG 实例会被创建，但顶层 `rag_retrieve()` 只查 `mem_core`；episodic/semantic 是否有独立查询或仅用于写入，当前代码显示没有顶层查询合并。
6. **参数化服务接线未闭环**：`parametric_api.py` 定义 JSON `POST /generate`，顶层 `orchestrator.py` 却以 OpenAI chat completions 形态请求 `PM_BASE_URL`，且默认模型名为 `parametric-memory`；是否有兼容代理或实际部署端点未确认。
7. **MCP 参数语义未对齐**：MCP `insert_memory` 的参数类型是可选字符串，而顶层 `handle_insert()` 期待 FastAPI `UploadFile` 并调用 `.read()`；MCP 传本地路径/URL 如何转成上传对象未实现于已读代码中。
8. **启动生命周期/并发未验证**：FastAPI startup 和 MCP `ensure_init()` 都会调用 `initialize_rag()`；容器同时启动两进程，是否会共享/竞争同一 MMKG 工作目录由 LightRAG 的共享锁部分处理，但跨进程一致性和重复初始化未测试。
9. **默认配置与密钥行为未验证**：OpenAI 客户端在模块导入时创建；`OPENAI_API_BASE`/`OPENAI_API_KEY`、参数化 `PM_*`、LightRAG `.env` 的组合优先级未在运行环境验证。不要把 README 中的公网 API 地址当作安全或稳定配置。
10. **环境可复现性不一致**：README 说 Python 3.10+，Docker 使用 3.11，`environment.yml` 固定 Linux conda Python 3.13；没有 lockfile、构建或 CI 证据，无法确认三者均可安装运行。
11. **许可证未在本轮确证**：已有细探文档提示需核对，但本轮只确认 README/源码目录，未将许可证结论写成已确认事实；后续复用 LightRAG 或 OpenClaw 适配前应单独核查 LICENSE 与上游来源。
12. **数据为空限制样本判断**：当前 `conversation.json` 与三份 `memory_chunks/*.json` 实际为空；持久化字段和运行后数据规模只能依据写入代码推断。
13. **安全边界未审计**：顶层 `/insert` 没有文件大小/类型/文件名安全策略，错误以 JSON 返回而未用 HTTP 状态码；嵌入式 LightRAG API 另有认证/CORS 逻辑，但它是否是顶层生产入口未确认。

## 10. 后续细探建议

1. 在隔离临时环境中先做无外部写入的 import/签名探针，分别验证顶层 FastAPI、MCP、视频/音频/图像处理器和参数化 API 的实际导入错误。
2. 明确统一的数据契约：入口记录、会话 JSON/JSONL、三类长期记忆 JSONL、PM 请求协议；再决定是否将 episodic/semantic 纳入查询合并。
3. 确认顶层服务与嵌入式 LightRAG Server 的关系，避免同时维护两套 API 生命周期和配置。
4. 补充不依赖真实模型/网络的契约测试：参数校验、MCP/FastAPI 参数映射、JSONL round-trip、LightRAG 工作目录隔离、错误分支。
5. 在许可证和依赖闭合后，才评估把任何模式移植到其他记忆系统；本仓库当前应视为源码参考/研究归档，而非已验证生产组件。

## 11. 本轮实际读取材料

### 根目录与规则/交付

- `README.md`

- `requirements.txt`
- `environment.yml`
- `test.sh`
- `entrypoint.sh`
- `dockerfile`
- `app.py`
- `orchestrator.py`
- `mcp_server.py`
- `mcp_client.py`

未发现仓库内 `AGENTS.md`、`CLAUDE.md`、`ARCHITECTURE.md`、`pyproject.toml`、`setup.py`、`package.json`。

### MemoryKB 核心源码与数据

- `MemoryKB/build_memory.py`
- `MemoryKB/User_Conversation/process_image.py`
- `MemoryKB/User_Conversation/process_video.py`
- `MemoryKB/User_Conversation/process_audio.py`
- `MemoryKB/Short_Term_Memory/K_likst.py`
- `MemoryKB/Paramatric_Memory/parametric_train.py`
- `MemoryKB/Paramatric_Memory/parametric_api.py`
- `MemoryKB/Paramatric_Memory/paramemory.json`
- `MemoryKB/Long_Term_Memory/system/core_memory_agent.txt`
- `MemoryKB/Long_Term_Memory/system/episodic_memory_agent.txt`
- `MemoryKB/Long_Term_Memory/system/semantic_memory_agent.txt`
- `MemoryKB/Long_Term_Memory/memory_chunks/core_memory.json`
- `MemoryKB/Long_Term_Memory/memory_chunks/episodic_memory.json`
- `MemoryKB/Long_Term_Memory/memory_chunks/semantic_memory.json`
- `MemoryKB/User_Conversation/conversation.json`

### LightRAG 核心、API 与适配

- `MemoryKB/Long_Term_Memory/Graph_Construction/lightrag_openai_demo.py`
- `MemoryKB/Long_Term_Memory/Graph_Construction/lightrag/__init__.py`
- `MemoryKB/Long_Term_Memory/Graph_Construction/lightrag/lightrag.py`
- `MemoryKB/Long_Term_Memory/Graph_Construction/lightrag/base.py`
- `MemoryKB/Long_Term_Memory/Graph_Construction/lightrag/types.py`
- `MemoryKB/Long_Term_Memory/Graph_Construction/lightrag/operate.py`
- `MemoryKB/Long_Term_Memory/Graph_Construction/lightrag/kg/networkx_impl.py`
- `MemoryKB/Long_Term_Memory/Graph_Construction/lightrag/api/lightrag_server.py`
- `MemoryKB/Long_Term_Memory/Graph_Construction/lightrag/api/routers/document_routes.py`
- `MemoryKB/Long_Term_Memory/Graph_Construction/lightrag/api/routers/query_routes.py`
- `MemoryKB/Long_Term_Memory/Graph_Construction/lightrag/api/routers/graph_routes.py`
- `ClawMemVerse/README.md`
- `ClawMemVerse/skill/SKILL.md`
- `ClawMemVerse/skill/README.md`
- `ClawMemVerse/skill/convert_json_to_md.py`

本文件已吸收此前 `细探-MemVerse.md` 的源码分析结论；后续只维护本文件，旧细探笔记不再作为独立事实源。

本清单是“实际读取”的证据范围；其余目录文件只做了路径/类型清点，没有将未读文件的行为写成已确认结论。

## 12. 第三轮：通用底座映射与裁决

### 12.1 轮次边界与证据状态

本节不是把 MemVerse 直接改造成系统工程平台，而是把当前源码中可复用的底层机制与产品语义分开，作为支持库、记忆模块、运行核心和统一网关的候选输入。当前目标根未找到独立的 `细探-MemVerse.md` 文件；第 1 行已经声明此前细探结论已吸收到本文件，本轮以现有正式文档和再次读取的源码为证据，不把缺失的旧文件当作可引用事实。

代码图前置核对结果：目标根没有 `.codegraph/`，`codegraph_explore` 返回“未建立代码图”，因此本轮使用源码路径、函数、类和行号静态取证回退流程。`project_context`/`development_start` 被错误绑定到 `~/Documents/Agent/PHP/华世王镞_v3`，并以 `MCP_TARGET_PROJECT_MISMATCH` 拒绝 MemVerse work package；本节不把 MCP 或代码图结果伪装成目标项目验证。

本节中的“现状”是源码事实；“映射/建议”是平台侧设计裁决，不表示 MemVerse 已经拥有这些平台组件，也不表示本轮修改了生产底座。

### 12.2 四层归属总表

```text
FastAPI / MCP / OpenClaw 请求
        │ 统一请求、身份、截止时间、取消信号、错误形状
        ▼
网关：唯一记忆公开入口（insert/query/status/cancel）
        │ 只做协议适配，不直接访问文件、模型或 LightRAG 存储
        ▼
记忆模块：空间、记忆类型、摄入/巩固/检索/回答编排
        │ 只表达 core/episodic/semantic/parametric 等产品语义
        ▼
运行核心：操作句柄、空间租约、任务监督、事件账本、取消/超时、崩溃恢复
        │ 只治理生命周期、并发、资源所有权和可观测性
        ▼
支持库：文件/JSON/向量/图/HTTP/模型/媒体/进程等原子能力
        │ provider 负责第三方差异，支持库公开稳定契约
        ▼
受管 provider / 独立进程 / 外部 API / 本地模型 / 文件系统
```

| 主题 | 当前 MemVerse 的真实落点 | 平台归属 | 可复用基础能力 | 不应下沉的产品语义 |
|---|---|---|---|---|
| 记忆版本 | 入口 `id=UTC时间+UUID`；长期记录只有 `timestamp`，参数模型从 `checkpoint_best_*` 目录名取版本 | 运行核心维护提交版本、激活指针、快照和兼容范围；记忆模块解释版本语义 | 内容摘要、单调版本、不可变快照、CAS 指针 | core/episodic/semantic 的分类及“更新/保留/新增”判断 |
| 记忆空间 | `LightRAG.workspace` 加 `working_dir` 组成 namespace；顶层固定 `core/episodic/semantic` 三个目录 | 运行核心维护 `space_id`、所有者、配额、租约、隔离和回收 | namespace、路径安全、目录隔离、空间生命周期 | “这是某用户的核心记忆/事件记忆/语义知识” |
| 入口与会话存储 | `conversation.json` 是普通 JSON 数组，`append_to_conversation` 整体读改写 | 支持库提供原子 JSON/事务 KV；运行核心负责写入提交和恢复 | 原子写、fsync、幂等键、版本校验、损坏备份 | 入口记录字段、会话归属和用户可见语义 |
| 长期记忆存储 | `memory_chunks/*.json` 以 JSONL 追加；`process_memory` 生成三类 `input_text/output_text/embedding` | 记忆模块选择记忆类型；支持库负责记录/索引写入 | JSONL 流、记录校验、内容寻址、索引重建 | prompt 产出的记忆内容及 core/episodic/semantic 规则 |
| KV/文档 | `JsonKVStorage` 保存 full docs/chunks/entities/relations/cache；`JsonDocStatusStorage` 保存状态 | 支持库；运行核心托管句柄、提交和清理 | KV、文档状态、分页、drop/finalize、迁移 | “文档已巩固”“记忆已可检索”的业务判定 |
| 向量检索 | `NanoVectorDBStorage` 写 `vdb_*.json`，批量 embedding、top-k、阈值、距离 | 支持库提供向量存储与 embedding provider；记忆模块提供检索策略 | embedding 批处理、top-k、阈值、压缩/反压 | query 的相关性、记忆优先级、回答用途 |
| 图检索 | `NetworkXStorage` 读写 `graph_*.graphml`，实体/关系由 LightRAG 抽取和合并 | 支持库提供图存储/图查询；记忆模块定义知识图谱用途 | 图节点/边 CRUD、子图、持久化、并发重载 | 实体关系是否代表个人事实、事件或概念 |
| 检索编排 | `QueryParam` 支持 `local/global/hybrid/naive/mix/bypass`、top-k、token budget、历史、ID 过滤 | 记忆模块公开检索用例；运行核心监督预算和取消 | 查询参数校验、预算、优先级、结果归一化 | 当前只查 `mem_core`、PM 相关性决定是否跳过 RAG |
| 事件/状态 | `DocStatus` 为 `pending/processing/processed/failed`；`track_id`、pipeline namespace、update flags、日志 | 运行核心事件账本、状态投影、订阅和审计 | 状态机、事件 ID、outbox、重放、幂等消费 | “摄入/巩固/回答”三个记忆业务阶段 |
| 服务边界 | `app.py` FastAPI、`mcp_server.py` FastMCP、可独立运行参数化 API、嵌入式 LightRAG API | 网关统一公开入口；记忆模块为唯一用例门面 | HTTP/MCP 适配、健康检查、错误映射、限流 | `insert_memory/query_memory` 及回答拼接规则 |
| 模型资源 | OpenAI embedding/chat/Whisper、GPT-4o 图像/视频描述、`ffmpeg`、Qwen CausalLM | 支持库 provider + 运行核心资源监督/隔离 | 模型客户端、进程组、超时、重试、版本加载、GPU/CPU 预算 | 使用哪个 prompt、何时 PM 优先、何谓“相关” |

### 12.3 记忆版本与空间：应补的通用契约

源码已有三种互不等价的“版本/空间”概念，不能直接合并：

1. **入口事件版本**：`orchestrator.generate_unique_id()` 产生时间串加 UUID；它适合做请求/记忆记录的唯一 id，不是可比较的提交版本，也没有父版本、幂等键或激活指针。
2. **LightRAG 数据空间**：`working_dir`、`workspace` 和 `namespace` 决定文件与共享字典的隔离；三实例分别使用 `MMKG/core`、`MMKG/episodic`、`MMKG/semantic`。这属于存储隔离，不等于用户/项目权限空间。
3. **参数模型版本**：`parametric_api.py` 扫描 `checkpoint_best_*`，按修改时间选最新目录，并用全局 `current_model_version/current_model_path` 标记；这不是事务化发布，目录修改时间也不是可审计版本指针。

建议在平台侧统一成以下最小对象，而不是沿用这些字符串的隐式语义：

```text
记忆空间 = {space_id, owner_id, project_id, memory_kind, quota, state}
记忆版本 = {space_id, version, parent_version, content_digest, snapshot_uri, state}
激活指针 = {space_id, active_version, changed_at, operation_id}
记忆操作 = {operation_id, idempotency_key, space_id, input_digest, deadline, cancel_token}
```

规则：版本提交必须在入口意图、索引写入、快照发布和激活指针之间形成可恢复状态机；`memory_kind` 只由记忆模块解释，不能让支持库凭目录名猜测业务类型；同一空间同一幂等键只能得到一个逻辑结果；旧读取必须持有对应版本的只读句柄，不能在热切换后悄悄读到另一版本。

### 12.4 存储、检索和事件的唯一链路

当前源码链路是 `app/MCP → orchestrator → build_memory → LightRAG → 多种存储/provider`，但存在两套入口、三次初始化、多个直接外部调用和数据格式漂移。平台化后的唯一规范链路应为：

```text
FastAPI / MCP / OpenClaw
  → 网关统一入口
  → 记忆模块.摄入 / 记忆模块.检索 / 记忆模块.回答
  → 运行核心.提交操作(operation_id, space_id, deadline, cancel_token)
  → 支持库.记录存储 / 支持库.embedding / 支持库.向量检索 / 支持库.图存储
  → 受管 provider 或独立进程
  → 运行核心.提交版本 + 事件 outbox + 证据
  → 网关统一结果与状态查询
```

固定裁决：

- **唯一公开入口**：FastAPI 和 MCP 只做参数/协议适配，最终都调用一个记忆模块门面；禁止 `mcp_server.py` 直接按位置参数调用 `handle_insert` 形成第二套语义。
- **唯一记忆写 owner**：入口记录、长期记忆记录、LightRAG 索引、事件状态分别声明 owner；其他层只能提交命令或读取公开视图，不能旁路改 `conversation.json`、`memory_chunks` 或 `MMKG`。
- **一次巩固一个 operation_id**：原始入口记录、三类记忆输出、向量/图索引和状态事件都带 `operation_id` 与输入摘要；重试只能恢复同一操作，不得重复追加 JSONL 或重复插入图谱。
- **事件晚于事实、早于对外成功**：事实/索引提交成功后写 outbox 事件，再由运行核心投影状态；网关只有在状态和提交证据可读时返回成功。当前源码的 `print`、日志、update flag 不是事件账本。
- **检索结果统一化**：向量距离、图子图、LightRAG 生成文本和 PM 生成文本先转成统一的 `MemoryHit`/`MemoryContext`，模块再决定优先级；禁止把 provider 原始对象穿透到网关。

### 12.5 可复用基础能力与产品语义边界

| 结论 | 内容 | 裁决 |
|---|---|---|
| 吸收 | `StorageNameSpace`、`BaseKVStorage`、`BaseVectorStorage`、`BaseGraphStorage` 的 initialize/finalize/index_done/drop 形状；namespace/workspace 隔离；`JsonKVStorage` 的 update flag 重载机制 | 升级为支持库契约，补原子提交、版本校验、错误码、所有权和恢复证据后复用 |
| 吸收 | `QueryParam` 的模式、top-k、token budget、ID 过滤、stream、model override 作为检索请求的候选字段 | 由记忆模块重新命名/校验；支持库只实现检索原子能力 |
| 吸收 | `DocStatus`、`DocProcessingStatus` 的 pending→processing→processed/failed、`track_id` 和分页状态读取 | 迁入运行核心通用任务状态；补 operation_id、取消、超时、崩溃恢复、幂等和事件 |
| 吸收 | `priority_limit_async_func_call` 的优先队列、并发上限、队列上限、超时和 shutdown 结构 | 升级为统一资源监督器；不得让每个 provider 自己维护 worker/信号量 |
| 升级 | LightRAG 的 KV+vector+graph 三路索引编排、`index_done_callback` 和跨进程 update flags | 保留为检索 provider 组合，但由运行核心管理事务/租约/快照，避免部分写和隐式 reload |
| 隔离 | `OpenAI` 在模块导入时创建的全局 client、`requests.post` 无统一 deadline、顶层直接调用 `ffmpeg`/模型 | 迁入 provider/独立进程，统一超时、取消、进程组、重试和敏感信息脱敏 |
| 隔离 | `core/episodic/semantic` prompt 文件、`check_duplicate` 的 GPT `add/update/remain`、PM relevance 判断、最终回答 prompt | 保留在记忆模块；它们是产品语义，不应进入通用存储或网关 |
| 隔离 | `ClawMemVerse` 的 JSON→Markdown 导出和 `SKILL.md` 读取 | 作为项目适配器；不能成为平台权威记忆存储或第二写入链 |
| 待核 | 嵌入式 `lightrag/api` 是否作为独立服务启用、三类 RAG 是否应分别查询、参数化 API 是否存在兼容代理 | 继续静态/运行核验；本轮不作生产接线裁决 |

### 12.6 句柄、租约、资源释放与所有权

当前源码有 `track_id`、`asyncio.Lock`/multiprocessing lock、共享 namespace 和全局模型变量，但没有可跨边界传递的句柄/租约。`track_id` 只能追踪文档处理，不能代替资源所有权。平台接入必须补下列句柄，而不是把 Python 对象传过网关：

| 句柄 | 创建者/持有者 | 必须绑定 | 正常释放 | 超时/取消/崩溃回收 |
|---|---|---|---|---|
| `operation_handle` | 网关创建，运行核心持有 | operation_id、space_id、deadline、cancel_token | 完成/失败事件落账后关闭 | 运行核心按租约扫描，标记 abandoned 并回收子任务 |
| `space_lease` | 运行核心签发，记忆模块持有 | owner、project、space_id、版本范围 | 操作结束主动释放 | 心跳过期/进程身份死亡后释放，禁止过期复活 |
| `storage_handle` | 支持库创建，运行核心登记 | namespace、workspace、读写模式、版本 | `finalize`/事务提交后关闭 | 进程组清理锁、临时文件、未提交缓存；恢复日志后再重开 |
| `model_handle` | 模型 provider/监督器创建 | provider、模型摘要、设备、并发预算 | 新版本原子接管后释放旧模型 | 加载失败保留旧句柄；宿主崩溃由独立进程退出回收 |
| `media_handle` | 文件/媒体 provider 创建 | 原始文件摘要、临时目录、操作 id | caption/transcript 后删除临时帧或按策略归档 | deadline/取消/崩溃均 killpg、递归清理、残留扫描 |

所有权规则：创建者默认持有；显式转移才改变持有者；借用不得关闭他人句柄；释放必须幂等并产出证据；句柄状态至少为 `created/active/releasing/released/expired/abandoned`；租约只能续租活跃句柄，不能用旧 `track_id` 或旧版本重新激活已经过期的句柄。

源码对应的已实现释放点只有部分：`StorageNameSpace.finalize`/各 storage 的 `index_done_callback`，`LightRAG.finalize_storages()` 逐个尝试收尾，`drop()` 清空 JSON/向量/图文件，`UnifiedLock.__aexit__` 释放锁，限流器 `shutdown()` 取消 future、等待队列并取消 worker。缺口是顶层 FastAPI/MCP 没有 shutdown 调用 `finalize_storages()`；上传文件无统一删除策略；视频 `frames_temp` 无 finally 清理；模型热替换没有旧模型/显存释放契约。

### 12.7 失败、超时、取消、崩溃矩阵（L0-L4）

下表把 L0-L4 定义为从网关到宿主的治理层级。除代码明确实现处外，其余均为静态风险或平台应补契约，不能标记为已验证。

| 层级 | 故障范围 | 当前源码事实 | 平台必需行为/验收 |
|---|---|---|---|
| L0 网关/请求 | 参数非法、文件缺失/超限、未授权、客户端断开、重复请求 | FastAPI `/insert` 捕获异常返回 `{"status":"error"}`，仍可能是 HTTP 200；`/query` 无统一异常映射；MCP 参数是可选字符串而 `handle_insert` 期待 `UploadFile` | schema/大小/类型/授权前置；统一错误码和 HTTP/MCP 映射；生成幂等键；客户端取消要传入 cancel token；不得把业务失败伪装成成功响应 |
| L1 记忆模块 | 入口记录校验、JSON 损坏、prompt/embedding/LLM 失败、重复巩固、三类记忆部分成功 | `process_memory` 校验五字段；解析坏 `conversation.json` 会重置为空；`update_long_term_memory` 吞掉 `process_memory` 异常后仍继续插入旧文件；JSONL 逐行跳过坏行 | 原始事件不可丢；巩固采用阶段状态和幂等 upsert；禁止失败后继续消费旧索引；三类输出全成或显式部分失败；支持重放/补偿 |
| L2 运行核心 | 队列满、任务超时、取消、锁竞争、部分写、服务重启 | 限流器有 `_queue_timeout`/`_timeout`，超时会 cancel future；worker 会处理 `CancelledError`；`asyncio.gather` 多处默认遇到异常即传播；存储采用 update flag/reload，没有统一事务 | 一个操作一个 deadline；取消要排空/终止子任务并写取消事件；队列满返回可重试错误；存储写入带提交点/回滚或恢复；锁与租约可证明无残留 |
| L3 provider/模型 | OpenAI/HTTP/Whisper、ffmpeg、NanoVectorDB/NetworkX、Qwen 加载或推理失败 | 图像 `requests.post` 未传 timeout；视频 `subprocess.run` 未设 timeout/check；音频 SDK 未设 deadline；PM 服务协议与顶层调用形态疑似不一致；模型更新失败只打印并保留全局旧状态 | 每 provider 接受统一 deadline/cancel；外部调用在独立进程或可杀会话中；有界重试+退避；旧模型原子保留；失败不污染索引；返回 provider unavailable/timeout/cancel/crashed 稳定错误码 |
| L4 进程/宿主 | FastAPI/MCP 双进程、解释器崩溃、SIGKILL、机器重启、磁盘/权限耗尽 | `initialize_rag()` 在 FastAPI startup 与 MCP `ensure_init()` 各自执行；多个 RAG 实例共享目录机制复杂；没有顶层优雅停机收尾；临时媒体和内存状态可能残留 | 运行核心登记进程身份和租约；启动只允许一次空间初始化；SIGTERM→宽限→SIGKILL；重启扫描未完成 operation/锁/租约/临时目录并恢复或隔离；磁盘/权限故障写证据；恢复后读回事实、索引、状态一致性 |

最小验收场景应逐层覆盖：空 query、非法 mode、重复 `id`、重复事件、JSONL 中间坏行、embedding 返回数量不一致、向量/图单路保存失败、请求超时、主动取消、客户端断开、provider 断线、ffmpeg 卡死、模型加载失败、旧模型切换中 SIGKILL、FastAPI/MCP 同时启动、强杀后重启恢复、二次释放和临时目录/锁/子进程残留。当前仓库无自动化测试套件，以上只能列为待验证，不得用 `test.sh` 的单次 curl 代替。

### 12.8 第三轮落点、装配计划与禁止事项

**支持库候选：** `原子文件/JSON事务`、`命名空间KV`、`向量检索`、`图存储`、`embedding/LLM客户端`、`媒体转码`、`模型加载`、`独立进程与进程组`。每项应有一个能力 id、一个契约 owner 和一个 provider 注册入口；第三方库只在 provider 边界出现。

**记忆模块候选：** `空间与记忆类型`、`多模态摄入`、`三类长期记忆巩固`、`参数化记忆相关性策略`、`检索结果统一`、`最终回答上下文`。模块只组合支持库能力，不自行写锁、任务监督、重试、事件账本或外部 HTTP。

**运行核心候选：** `operation_handle`、`space_lease`、`storage/model/media_handle`、截止时间和取消传播、任务状态、事件 outbox、版本/快照/CAS、崩溃恢复、资源残留审计。运行核心不理解 prompt 内容，也不决定 core/episodic/semantic 的业务分类。

**网关候选：** 一个 FastAPI/MCP 统一入口，保留协议适配；公开 `insert/query/status/cancel` 等稳定操作；统一鉴权、请求大小、幂等键、错误码、trace/operation id 和响应形状。嵌入式 LightRAG API、OpenClaw 文件同步和参数化 `/generate` 先作为隔离适配器，不能未经契约编译直接成为第二网关。

**装配顺序：**

1. 先冻结 `space/version/operation/handle/lease/event` 公共契约和错误码；
2. 搜索已有平台能力，优先复用公共存储、资源监督、子进程、版本/快照、事件和网关，不创建第二套同名底座；
3. 将 LightRAG 的 KV/vector/graph 适配成 provider，补原子提交、索引一致性、超时、取消和 `finalize` 证据；
4. 在记忆模块中把 FastAPI/MCP 两条调用收敛到一个门面，显式传 `space_id/operation_id/deadline/cancel_token`；
5. 用故障注入验证 L0-L4，再决定是否生产化任何候选；
6. 验收通过后才能形成装配计划；本轮不修改平台底座、不安装依赖、不启动 MemVerse 服务。

**禁止事项：** 网关直连 `OpenAI`/`ffmpeg`/JSON 文件；FastAPI 与 MCP 各维护一套记忆流程；用 `track_id` 冒充租约；用目录 mtime 冒充模型发布版本；失败后继续读取旧 JSONL；隐藏 provider fallback；在 `core/episodic/semantic` 各复制一套锁/重试/事件；把 `ClawMemVerse` Markdown 当权威写库。

### 12.9 第三轮结论与剩余风险

- **吸收**：LightRAG 的存储抽象、namespace/workspace 隔离、向量/图/KV 的组合检索、文档状态和优先级限流，作为平台能力设计的事实样本。
- **升级**：版本/空间、唯一操作链、事件账本、句柄/租约、资源释放和 L0-L4 故障治理；当前源码只提供局部机制，不能直接宣称满足平台契约。
- **隔离**：MemVerse 的 prompt、三类记忆含义、PM 相关性判断、最终回答和 OpenClaw 适配，保留在产品模块/项目适配层。
- **待核**：真正运行时的依赖闭合、三实例初始化竞争、PM 协议兼容、LightRAG API 是否启用、模型/向量/图写入的一致性、所有失败/超时/取消/崩溃路径。仓库没有测试套件，本轮未安装依赖、未启动服务、未调用外部模型、未进行真实故障注入。

本轮唯一修改文件是目标根 `ARCHITECTURE.md`；没有删除旧细探材料，没有修改 MemVerse 源码、依赖、配置、测试或 Git。后续若要把本节变成平台生产改造，必须另行获得目标平台正确 MCP 绑定、能力搜索、工作包租约和独立验收证据。
