# MemoryOS 架构建档

> 本文是本仓库唯一正式架构文档，依据当前磁盘源码、README、依赖清单、测试/评估脚本和仓库内已有施工材料整理。文档描述“实际存在的代码”，不把论文设计或 README 宣称当作已验证实现。
>
> 目标仓库：`MemoryOS/`  
> 读取基线：工作树为 `main` 分支。  
> 本轮限制：未安装依赖、未启动服务、未生成构建产物、未运行会触发 LLM/向量模型/数据写入的测试、未提交 Git。

## 1. 项目定位

MemoryOS 是一个面向个性化 AI Agent 的 Python 记忆系统参考实现。它把对话记忆组织为短期、中期、长期三层，并用更新器把短期 QA 批量整理为带主题、向量和对话链元信息的中期会话，再在热度达到阈值时用 LLM 提取用户画像、用户私有知识和助手知识，最后由检索器融合多层上下文交给 LLM 生成回答。

仓库不是单一可安装工程，而是多个并行快照/出口：

- `memoryos-pypi/`：主 SDK 形态，JSON 文件 + FAISS，导出 `Memoryos`。
- `memoryos-chromadb/`：替代存储实现，ChromaDB 向量集合 + 一个 JSON 元数据备份文件，仍导出同名 `Memoryos`。
- `memoryos-mcp/`：把一份 MemoryOS 包复制到 `memoryos-mcp/memoryos/`，由 FastMCP 通过 stdio 暴露工具。
- `memoryos-playground/`：基于 Flask 的浏览器演示；`memdemo/` 保存页面、样例数据和启动脚本。
- `eval/`：LoCoMo 评估/旧版动态更新流水线，不是上述 SDK 的稳定 API 层。

README 对项目的论文定位、三层记忆和四类能力（Storage、Updating、Retrieval、Generation）有概括；当前代码中 Storage/Updating/Retrieval/Generation 是职责划分，不是统一的接口或依赖注入协议。

## 2. 总体文本流程图

### 2.1 SDK 主链路（`memoryos-pypi`）

```text
调用方
  │
  ├─ Memoryos(...)
  │    ├─ OpenAIClient ───────────────► OpenAI-compatible chat.completions
  │    ├─ ShortTermMemory ────────────► users/<user_id>/short_term.json
  │    ├─ MidTermMemory ──────────────► users/<user_id>/mid_term.json
  │    ├─ LongTermMemory(user) ───────► users/<user_id>/long_term_user.json
  │    ├─ LongTermMemory(assistant) ──► assistants/<assistant_id>/long_term_assistant.json
  │    ├─ Updater
  │    └─ Retriever
  │
  ├─ add_memory(user_input, agent_response)
  │    │
  │    ├─ 短期已满？──是──► Updater.process_short_term_to_mid_term()
  │    │                     ├─ 弹出旧 QA
  │    │                     ├─ LLM 判断连续性/生成 meta_info
  │    │                     ├─ LLM 生成最多两个主题摘要与 keywords
  │    │                     └─ MidTermMemory 合并或新建 session
  │    └─ 追加当前 QA 到短期 JSON
  │
  │    └─ 热 session 的 H_segment >= 阈值？
  │          ├─ 并行 LLM：完整用户画像更新
  │          ├─ 并行 LLM：用户私有知识/助手知识抽取
  │          ├─ 写入长期 JSON
  │          └─ 标记 pages.analyzed=True、重置访问/交互热度
  │
  └─ get_response(query)
       ├─ Retriever 并行检索中期页面、用户知识、助手知识
       ├─ 拼接短期历史、页面、用户画像、长期知识和 prompt
       ├─ OpenAIClient.chat_completion()
       └─ 把 query/response 作为新 QA 再写入短期层
```

### 2.2 ChromaDB 变体

```text
Memoryos(memoryos-chromadb)
  │
  └─ ChromaStorageProvider(data_storage_path/chroma_storage)
       ├─ PersistentClient
       ├─ mid_term_memory_user_<user_id>
       │    ├─ session_summary 向量
       │    └─ page 向量
       ├─ user_knowledge_<user_id> 向量
       ├─ assistant_knowledge_<assistant_id> 向量
       └─ metadata_<user_id>_<assistant_id>.json
            ├─ short_term_memory
            ├─ mid_term_sessions/pages_backup
            ├─ access_frequency / heap_state
            ├─ user_profiles
            └─ update_times

add_memory/get_response 的上层流程与 PyPI 变体相同，检索改为 ChromaDB query；会话元数据和页面完整备份仍由 JSON metadata 保存。
```

### 2.3 MCP/网页出口

```text
MCP client ─stdio─► memoryos-mcp/server_new.py
                         │ FastMCP tools
                         ├─ add_memory ─► Memoryos.add_memory
                         ├─ retrieve_memory ─► Retriever + short-term/profile 组装 JSON
                         └─ get_user_profile ─► profile/knowledge 组装 JSON

浏览器 ─HTTP─► memoryos-playground/memdemo/app.py
                         ├─ POST /init_memory ─► 创建内存中的 Memoryos 实例
                         ├─ POST /chat ─────────► Memoryos.get_response
                         ├─ GET  /memory_state ─► 读取三层状态
                         ├─ POST /trigger_analysis
                         ├─ POST /personality_analysis
                         ├─ POST /clear_memory
                         └─ POST /import_conversations
```

## 3. 真实分层与目录地图

```text
MemoryOS/
├── README.md                         # 英文定位、安装、入口、变体和复现命令
├── readme_cn.md                      # 中文 README
├── ARCHITECTURE.md                   # 本正式文档
├── Dockerfile                        # 仅基于 memoryos-pypi 的 Python 3.10 镜像步骤
├── LICENSE                           # 仓库许可证文件；README 标示 Apache-2.0
├── Paper-MemoryOS.pdf                # 论文材料（本轮未把论文当实现证据）
├── docs/                             # 静态 HTML 文档和图片
│   └── docs.html
├── memoryos-pypi/                    # JSON + FAISS SDK 变体
│   ├── __init__.py                   # 导出 Memoryos
│   ├── memoryos.py                   # 聚合根/门面 Memoryos
│   ├── short_term.py                # 短期 deque + JSON
│   ├── mid_term.py                  # session/page、热度、FAISS 检索、LFU
│   ├── long_term.py                 # profile、user/assistant knowledge + FAISS
│   ├── updater.py                   # 短期晋升、连续性、摘要、长期更新
│   ├── retriever.py                 # 三路并行检索与 top-k 页面队列
│   ├── prompts.py                   # 摘要、画像、知识、回复等提示词
│   ├── utils.py                     # OpenAI、embedding、时间衰减、LLM 辅助函数
│   ├── test.py                      # 手工 demo/集成式脚本
│   └── requirements.txt
├── memoryos-chromadb/                # ChromaDB 存储变体
│   ├── __init__.py
│   ├── memoryos.py                  # 同名门面，注入共享 ChromaStorageProvider
│   ├── storage_provider.py           # 向量集合 + JSON metadata 适配层
│   ├── short_term.py / mid_term.py / long_term.py
│   ├── updater.py / retriever.py / utils.py
│   ├── comprehensive_test.py         # 旅行对话测试脚本
│   └── requirements.txt
├── memoryos-mcp/                     # FastMCP stdio 服务器出口
│   ├── server_new.py                # 配置加载、三个 MCP tool、main
│   ├── config.json                  # 示例运行配置（含空 API key）
│   ├── mcp.json                     # 客户端接入示例，含 /root 绝对路径
│   ├── memoryos/                    # 独立复制的一份 MemoryOS Python 包
│   ├── test_simple.py               # MCP client stdio 集成脚本
│   └── requirements.txt
├── memoryos-playground/              # Flask 演示变体
│   ├── memoryos.py / short_term.py / mid_term.py / long_term.py ...
│   ├── memdemo/app.py               # Web 路由和全局实例表
│   ├── memdemo/templates/index.html
│   ├── memdemo/sample_conversations.json
│   ├── memdemo/start_demo.sh
│   └── requirements.txt
└── eval/                             # LoCoMo 旧式评估链
    ├── main_loco_parse.py            # 读 locomo10.json、写 all_loco_results.json
    ├── evalution_loco.py             # 按 category 计算 token-set F1
    ├── dynamic_update.py             # 旧版短期→中期动态更新
    ├── short_term_memory.py / mid_term_memory.py / long_term_memory.py
    ├── retrieval_and_answer.py / utils.py
    └── locomo10.json
```

仓库内未发现 `AGENTS.md` 或 `CLAUDE.md`。也未发现 `pyproject.toml`、`setup.py`、统一测试配置或迁移文件；各变体以目录内脚本和 `requirements.txt` 自管理。

## 4. 核心组件与职责

### 4.1 聚合入口：`Memoryos`

**路径：** `memoryos-pypi/memoryos.py:29-124`；Chroma 变体为 `memoryos-chromadb/memoryos.py:32-130`；MCP 内有独立复制版本 `memoryos-mcp/memoryos/memoryos.py`。

`Memoryos.__init__` 接收 `user_id`、`assistant_id`、OpenAI key/base URL、数据路径、三层容量、热度/相似度阈值、LLM 模型名和 embedding 模型配置，创建存储对象、LLM 客户端、三层记忆、`Updater` 和 `Retriever`。

关键公开方法（PyPI 版本）：

- `add_memory()`：`memoryos-pypi/memoryos.py:226-250`，短期满时先晋升再追加 QA。
- `get_response()`：`memoryos-pypi/memoryos.py:252-348`，检索、组 prompt、调用 LLM，并把本轮交互再写回记忆。
- `get_user_profile_summary()`、`get_assistant_knowledge_summary()`：读取长期层。
- `force_mid_term_analysis()`：临时把热度阈值降为 0，触发热点分析。
- `get_memory_stats()`：读取当前短期数量、中期 session 数和长期概要。

Chroma 版本额外在 `memoryos-chromadb/memoryos.py:132-136` 注册 `atexit`，退出时调用 `ChromaStorageProvider.save_all_metadata()`；其 profile 返回对象而非 PyPI 版本的原始字符串（`memoryos-chromadb/memoryos.py:375-379`）。这说明两个变体不是完全可替换的二进制/行为兼容实现。

### 4.2 短期层：QA deque

**路径：** `memoryos-pypi/short_term.py:9-66`；Chroma 版本 `memoryos-chromadb/short_term.py:9-50`。

数据是按容量限制的 `collections.deque`。最小 QA 结构为：

```text
{
  "user_input": string,
  "agent_response": string,
  "timestamp": "YYYY-MM-DD HH:MM:SS"
}
```

Chroma 变体会额外写入 `user_id`（`memoryos-chromadb/memoryos.py:244-249`），本地 deque 与共享 provider metadata 同步，但 provider 的 metadata 在进程退出/显式保存时才持久化。

### 4.3 中期层：session、page、热度与语义检索

**路径：** `memoryos-pypi/mid_term.py`；核心函数 `compute_segment_heat()` 在 `:26-36`，`MidTermMemory.add_session()` 在 `:103-179`，合并在 `:190-279`，检索在 `:281-362`。

**Session 结构：**

```text
{
  "id": "session_<随机8位hex>",
  "summary": string,
  "summary_keywords": [string],
  "summary_embedding": [float],
  "details": [Page],
  "L_interaction": integer,
  "R_recency": float,
  "N_visit": integer,
  "H_segment": float,
  "timestamp": string,
  "last_visit_time": string,
  "access_count_lfu": integer
}
```

**Page 结构：**

```text
{
  "page_id": "page_<随机8位hex>",
  "user_input": string,
  "agent_response": string,
  "timestamp": string,
  "preloaded": boolean,
  "analyzed": boolean,
  "pre_page": string|null,
  "next_page": string|null,
  "meta_info": string|null,
  "page_embedding": [float],
  "page_keywords": [string]
}
```

热度实际计算为：

```text
H_segment = 1.0 * N_visit + 1.0 * L_interaction + 1.0 * R_recency
R_recency = exp(-(now - last_visit_time) / 24小时)
```

中期层使用 `heap` 保存 `(-H_segment, session_id)`，以便快速取热点；容量超限时按 `access_frequency` 的最小值实施 LFU 淘汰。摘要和 page/session embedding 归一化后使用 FAISS `IndexFlatIP`（内积）检索。页面先按 page 相似度过滤，再由 `Retriever` 用小根堆保留最多 `queue_capacity` 项。

Chroma 变体的行为位于 `memoryos-chromadb/mid_term.py:39-360`：session/page 向量写入 provider，session 元数据和 `pages_backup` 保存在 provider metadata；检索通过 provider 的 Chroma query。该变体会对页关键词调用 LLM 提取，PyPI 版本主要依赖多主题摘要返回的 keywords。

### 4.4 长期层：画像与两类知识

**路径：** PyPI `memoryos-pypi/long_term.py:11-172`；Chroma `memoryos-chromadb/long_term.py:12-104`。

PyPI 版本的长期 JSON 逻辑结构：

```text
{
  "user_profiles": {
    "<user_id>": {
      "data": string,
      "last_updated": string
    }
  },
  "knowledge_base": [
    {"knowledge": string, "timestamp": string, "knowledge_embedding": [float]}
  ],
  "assistant_knowledge": [
    {"knowledge": string, "timestamp": string, "knowledge_embedding": [float]}
  ]
}
```

`LongTermMemory.add_knowledge_entry()`（`long_term.py:50-69`）为知识生成 embedding、归一化并放入有容量上限的 deque；`search_*_knowledge()`（`:83-139`）临时建立 FAISS 内积索引完成 top-k 检索。画像更新可选择拼接旧文本（`merge=True`）或整体替换。

Chroma 版本将用户画像放到 provider metadata 的 `user_profiles`，知识放到独立的用户/助手 Chroma collections，metadata 中的知识字段名为 `text`；由 `enforce_knowledge_capacity()`（`storage_provider.py:336-348`）按时间删除超容量旧条目。它的 `update_user_profile()` 经 LLM 生成结构化/原始画像对象后写 provider（`long_term.py:27-43`）。

### 4.5 更新器：短期晋升与长期抽取

**路径：** `memoryos-pypi/updater.py:22-238`；Chroma 版本 `memoryos-chromadb/updater.py:22-230`。

`Updater.process_short_term_to_mid_term()` 的实际步骤：

1. 在短期满时连续 `pop_oldest()`，收集有 user/assistant 文本的 QA。
2. 为每条 QA 创建 Page，初始化 `page_id`、链指针、`analyzed=False`。
3. 通过 `check_conversation_continuity()` 调 LLM 判断是否与上一页连续；连续则设置 `pre_page`，并用 `generate_page_meta_info()` 更新链摘要。
4. 将批次文本交给 `gpt_generate_multi_summary()`，按返回的最多两个 theme/keywords/content 调用 `MidTermMemory.insert_pages_into_session()`；相似则合并，否则建新 session。
5. 修补前后页连接并保存。

长期更新由 `Memoryos._trigger_profile_and_knowledge_update_if_needed()`（`memoryos-pypi/memoryos.py:126-224`）触发：取热度最高且有未分析页的 session，并行调用 `gpt_user_profile_analysis()` 与 `gpt_knowledge_extraction()`；随后写用户画像、用户知识、助手知识，将页标记为已分析，把访问次数和交互长度重置并重建 heap。

### 4.6 检索器与生成

**路径：** PyPI `memoryos-pypi/retriever.py:18-130`；Chroma `memoryos-chromadb/retriever.py:18-140`。

`Retriever.retrieve_context()` 同时启动三路任务：

- `MidTermMemory.search_sessions()` → session 内匹配页面 → top-k 页面堆。
- 用户长期知识语义检索。
- 助手长期知识语义检索。

返回契约为：

```text
{
  "retrieved_pages": [Page],
  "retrieved_user_knowledge": [KnowledgeEntry],
  "retrieved_assistant_knowledge": [KnowledgeEntry],
  "retrieved_at": timestamp
}
```

`Memoryos.get_response()` 将返回值与短期历史、用户画像、关系/元数据、assistant knowledge 拼入 `prompts.py` 定义的 system/user prompt，调用 `OpenAIClient.chat_completion()`。回复完成后，查询和回答会作为新 QA 写入短期层，因此“生成”也是写入入口。

### 4.7 LLM、embedding 和通用工具

**路径：** `memoryos-pypi/utils.py`；Chroma 版本为 `memoryos-chromadb/utils.py`。

- `OpenAIClient`：包装 `openai.OpenAI`，调用 `client.chat.completions.create()`；支持线程池异步/批量调用；失败时返回固定错误字符串而不是抛出原异常（PyPI `utils.py:37-98`）。
- `get_embedding()`：默认使用 `SentenceTransformer`；模型名含 `bge-m3` 时切换 `FlagEmbedding.BGEM3FlagModel`；支持内存模型/向量缓存；归一化由 `normalize_vector()` 完成。
- `compute_time_decay()`：按 `%Y-%m-%d %H:%M:%S` 解析时间并使用指数衰减，解析失败返回 `0.1`。
- LLM 辅助函数：主题摘要、多主题摘要、用户画像分析、知识抽取、连续性判断、页面 meta 信息生成。
- `prompts.py` 中固化回复、摘要、画像、知识抽取等文本协议；输出解析主要是 JSON 或标记区段文本解析，并非 Pydantic/JSON Schema 契约。

## 5. 存储模型与持久化边界

### 5.1 PyPI/Playground 文件布局

`memoryos-pypi/memoryos.py:70-84` 为每个用户/助手拼接以下路径：

```text
<data_storage_path>/
├── users/<user_id>/
│   ├── short_term.json
│   ├── mid_term.json
│   └── long_term_user.json
└── assistants/<assistant_id>/
    └── long_term_assistant.json
```

每个层对象自己 `load()`/`save()`，使用 JSON 覆盖写入；锁是进程内 `threading.Lock`，不是跨进程文件锁。短期 deque 的 maxlen、中期 session 数、长期知识 deque 的 maxlen均由构造参数控制。

### 5.2 ChromaDB 文件/集合布局

`memoryos-chromadb/storage_provider.py:17-36` 创建：

```text
<data_storage_path>/chroma_storage/
├── Chroma PersistentClient 文件（由 ChromaDB 管理）
└── metadata_<user_id>_<assistant_id>.json
```

向量集合为 `mid_term_memory_user_<user_id>`、`user_knowledge_<user_id>`、`assistant_knowledge_<assistant_id>`。session summary 与 page 使用 `type` metadata 区分；Chroma 只存查询所需的向量/metadata，`pages_backup`、短期内容、访问频率、heap、画像、更新时间仍在 JSON metadata 中。

## 6. API、CLI 与 SDK 接口

### 6.1 Python SDK

README 给出的入口为：

```python
from memoryos import Memoryos
memo = Memoryos(
    user_id="demo_user",
    openai_api_key="...",
    openai_base_url="...",
    data_storage_path="./simple_demo_data",
    assistant_id="demo_assistant",
    llm_model="gpt-4o-mini",
    embedding_model_name="BAAI/bge-m3",
)
memo.add_memory(user_input="...", agent_response="...")
answer = memo.get_response(query="...")
```

PyPI 包导出由 `memoryos-pypi/__init__.py:1-2` 完成。README 宣称可 `pip install memoryos-pro`；仓库本身只提供目录级 `requirements.txt`，未发现打包元数据文件，仓内安装路径是 `cd memoryos-pypi && pip install -r requirements.txt`。

### 6.2 MCP stdio

**入口：** `memoryos-mcp/server_new.py`。

- 启动：`python server_new.py --config config.json`；`main()` 用 `argparse` 读取配置，初始化全局 `memoryos_instance`，然后 `mcp.run(transport="stdio")`（`:260-291`）。
- 配置必需字段：`user_id`、`openai_api_key`、`data_storage_path`（`:28-54`）；其余字段取默认值。
- 工具：
  - `add_memory(user_input, agent_response, timestamp?, meta_data?)`（`:59-112`）。
  - `retrieve_memory(query, relationship_with_user="friend", style_hint="", max_results=10)`（`:114-197`），返回短期历史、页面、用户/助手知识、画像和计数。
  - `get_user_profile(include_knowledge=True, include_assistant_knowledge=False)`（`:198-258`）。
- `mcp.json` 是客户端配置样例，但当前文件内命令和脚本都是 `/root/...` 绝对路径（`memoryos-mcp/mcp.json:2-11`），不能直接视为本机可运行配置。

### 6.3 Flask Playground HTTP API

**入口：** `memoryos-playground/memdemo/app.py`，默认 `0.0.0.0:5019`（`:426`）。

| 方法 | 路径 | 实际职责 |
|---|---|---|
| GET | `/` | 返回 `templates/index.html` |
| POST | `/init_memory` | 用 JSON 中 user/API/base/model 创建本进程 `Memoryos`，写 Flask session |
| POST | `/chat` | 调用 `Memoryos.get_response()`，返回 response/timestamp |
| GET | `/memory_state` | 返回短期、中期 session 概况、长期画像/知识 |
| POST | `/trigger_analysis` | 检查未分析页后调用 `force_mid_term_analysis()` |
| POST | `/personality_analysis` | 解析画像文本中的维度/等级 |
| POST | `/clear_memory` | 删除用户/助手目录并重建实例 |
| POST | `/import_conversations` | 批量把 `{user_input, agent_response, timestamp?}` 写入记忆 |

该演示使用全局字典 `memory_systems` 按随机 session id 保存实例，不是多进程/生产级会话存储。

### 6.4 评估 CLI/脚本

- `python eval/main_loco_parse.py`：读取 `eval/locomo10.json`，构建旧式记忆模块，写 `all_loco_results.json`；代码会创建 `mem_tmp_loco_final/`。
- `python eval/evalution_loco.py`：读取上一步结果，按 category 计算 token 集合 F1。
- `python memoryos-chromadb/comprehensive_test.py`：旅行规划集成测试脚本。
- `python memoryos-mcp/test_simple.py`：启动 MCP 子进程，调用 `add_memory` 15 次，再调用 `retrieve_memory` 验证返回内容。

## 7. 技术栈与依赖

| 领域 | 实际使用 |
|---|---|
| 语言/运行时 | Python；README 要求 Python >= 3.10；Dockerfile 使用 `python:3.10-slim` |
| LLM 客户端 | `openai` Python SDK；通过 OpenAI-compatible `base_url` 支持其他服务 |
| embedding | `sentence-transformers`；BGE-M3 通过 `FlagEmbedding`；README 提到 Qwen embedding |
| 向量检索 | PyPI/Playground 使用 `faiss.IndexFlatIP`；Chroma 变体使用 ChromaDB，默认 cosine |
| 数值/数据 | `numpy`、JSON 文件、`deque`、`heapq`、`threading`、`concurrent.futures` |
| 服务出口 | FastMCP (`mcp`) stdio；Flask 2.x web demo |
| 评估 | 自定义 Python LoCoMo 处理与 token-set F1；`locomo10.json` |
| 容器 | Dockerfile 仅复制 `memoryos-pypi`、安装依赖并安装 vim，无 CMD/ENTRYPOINT |
| 版本管理/许可 | Git；README badge 和 `LICENSE` 指向/标示 Apache-2.0 |

依赖来源：`memoryos-pypi/requirements.txt`、`memoryos-chromadb/requirements.txt`、`memoryos-mcp/requirements.txt`、`memoryos-playground/requirements.txt`、`memoryos-playground/memdemo/requirements.txt`。不同变体的版本约束不一致：例如 PyPI 固定 `sentence-transformers==5.0.0`，Playground 约束 `<3.0.0`，Chroma 变体使用无版本约束；均声明 `faiss-gpu`，对 macOS/CPU 可用性没有仓库内适配说明。

## 8. 测试与验证现状（仅静态读取）

本轮没有执行测试，因为各测试会加载 embedding 模型、调用外部 LLM、创建/修改数据目录或启动 MCP/Flask，不符合“禁止启动服务、生成构建产物”的范围。

已读取的测试/评估材料及其性质：

- `memoryos-pypi/test.py`：10 条 demo QA 后调用 `get_response()`；配置中有空 API/base/data/model 值，属于手工 demo，不是无外部依赖单元测试。
- `memoryos-playground/test.py`：单轮初始化、添加 QA、查询；配置含本地 `/root/...` embedding 路径的演示副本；不是 pytest 测试。
- `memoryos-chromadb/comprehensive_test.py`：30 轮旅行规划对话，触发分析，再以关键词匹配评估三个查询；依赖外部 LLM/embedding 和 Chroma 持久化目录。
- `memoryos-mcp/test_simple.py`：MCP stdio 客户端集成测试，插入 15 轮并执行两条查询；依赖 `mcp`、配置和服务器子进程。
- `eval/main_loco_parse.py` + `eval/evalution_loco.py`：全量 LoCoMo 生成结果和 category F1；会写评估临时目录/结果文件并调用 LLM。
- `eval/dynamic_update.py`：旧版短期批量驱逐、连续性判断、meta 信息和主题分组实现，供评估链使用，不是当前 `Memoryos` 的统一实现。

未发现标准 `tests/` 目录、pytest 配置、CI 工作流或无网络的单元测试契约。README 中提到的 `test_comprehensive.py` 与当前仓库可见文件名不完全一致；当前实际可见的是 `memoryos-chromadb/comprehensive_test.py` 和 `memoryos-mcp/test_simple.py`。

## 9. 关键未确认项与风险

以下事项来自静态代码/文件对照，未通过安装或运行确认：

1. **变体 API 兼容性未确认。** PyPI 版本的长期画像是字符串结构，Chroma 版本返回字典/对象；两者同名 `Memoryos` 不能据此假定结果契约一致。
2. **MCP 复制漂移风险。** `memoryos-mcp/memoryos/` 是独立复制包；修复/升级 `memoryos-pypi` 不会自动同步 MCP 目录。MCP `mcp.json` 的 `/root` 路径也与本仓库所在 macOS 路径不符。
3. **配置/文档漂移。** README MCP 测试命令指向不存在于当前可见清单的 `test_comprehensive.py`；README 与 `memoryos-mcp/config.json` 的默认值/字段也存在版本差异。
4. **持久化一致性边界弱。** PyPI 层采用 JSON 覆盖写入，锁仅为进程内 `threading.Lock`；Chroma 变体的向量写入和 metadata 写入不是一个事务，异常中断时可能产生不一致。
5. **数据模型无正式 schema。** QA、Page、Session、Knowledge、画像均为裸 `dict`/JSON；没有类型化 schema、迁移版本、校验或兼容升级机制。
6. **LLM 输出是非严格协议。** 多主题摘要依赖 `json.loads`，知识抽取依赖中文标记文本解析；LLM 请求异常在 `OpenAIClient` 中被转成固定错误字符串，可能继续进入后续记忆流程。
7. **向量和平台依赖未验证。** 依赖声明 `faiss-gpu`，embedding 模型可能需要网络/本地模型缓存；当前没有 macOS/CPU 降级说明，也没有本地离线测试证据。
8. **并发和生命周期未闭合。** 多处使用线程池，但没有跨实例/跨进程写协调；`OpenAIClient` 的线程池缺少由 `Memoryos` 明确调用的 shutdown 路径，Chroma 只注册 metadata 保存的 `atexit`。
9. **短期晋升语义需要运行确认。** 短期达到容量后 `Updater` 会持续弹出直到不满，再追加新 QA；这意味着一次迁移可能移动多个旧 QA，是否符合预期只能由实际行为测试确认。
10. **时间语义有限。** 时间是本地时区字符串，热度和衰减没有时区/时钟注入；非法时间静默返回低衰减值。
11. **安全边界未建立。** MCP server 使用全局单用户实例；Flask 将 API key 放进 Flask session 配置并维护全局实例表；未看到认证、授权、租户隔离或密钥脱敏策略。
12. **评估链与主链分叉。** `eval/` 使用另一组 `short_term_memory`、`mid_term_memory`、`long_term_memory`、`DynamicUpdate` 和 `RetrievalAndAnswer`，结果不能直接证明当前 PyPI/Chroma/MCP 入口的行为。
13. **构建/发布状态未确认。** README 宣称 PyPI 包名 `memoryos-pro`，但仓库快照中未发现 `pyproject.toml`、`setup.py` 或发布流水线；没有在本轮安装验证。
14. **文档/论文性能声明未复核。** README 中的 LoCoMo 指标和“5 倍加速”等是项目声明，本架构文档没有将其当作当前环境的测试结果。

## 10. 建档结论

当前仓库的真实核心是“LLM 驱动的三层个人对话记忆流水线”，而不是已经抽象出统一存储、更新、检索接口的可插拔平台。`memoryos-pypi` 是最清晰的基线实现；`memoryos-chromadb` 是共享 provider 的向量存储改写；`memoryos-mcp` 和 Playground 是外围适配/演示出口；`eval` 是独立的旧式评估实现。后续若要借鉴到其他系统，应优先抽取三层数据边界、短期晋升触发条件、热度模型、检索结果契约和 LLM 输出校验边界，而不能把不同目录下同名模块直接视为一个可替换组件。

本文件已吸收此前 `细探-MemoryOS.md` 的源码分析结论；后续只维护本文件，旧细探笔记不再作为独立事实源。

## 11. 第三轮：通用底座映射与产品边界

本轮只追加底座映射，不把 MemoryOS 改造成平台实现。证据仍以本仓库当前源码为准：`memoryos-pypi/memoryos.py`、`updater.py`、`retriever.py`、`short_term.py`、`mid_term.py`、`long_term.py`、`utils.py`，以及 `memoryos-chromadb/storage_provider.py`、`memoryos-mcp/server_new.py`。目标树当前没有独立的 `细探-MemoryOS.md` 文件；本轮未删除任何旧细探，沿用本文件已经吸收的旧结论。

### 11.1 映射总图：MemoryOS 能力如何进入平台

```text
Agent/业务调用方
  → HTTP 能力网关（唯一通信入口；MCP 只能作薄适配）
  → 项目适配层（用户/助手/模型/存储策略、权限、版本和别名）
  → 运行核心（请求上下文、任务、截止时间、租约、监督、证据）
  → 记忆/状态模块（L0-L4、事件、状态迁移、记忆策略、检索编排）
  → 唯一能力调用器/注册表
  → 支持库公开能力
       ├─ 结构化存储/原子文件/快照
       ├─ 向量化与向量检索
       ├─ LLM/Embedding 模型提供者
       ├─ 时间、标识、序列化和文本处理
       └─ 线程/进程/外部服务适配
  → 受管提供者或独立执行单元
  → JSON/Chroma/FAISS/模型服务/外部协议
  → 统一结果、事件投影、资源释放证据
```

上图是平台落点，不是当前 MemoryOS 已经实现的调用链。当前源码的真实情况是：`Memoryos` 直接实例化记忆对象、`Updater`、`Retriever` 和 `OpenAIClient`；各对象直接读写 JSON/Chroma、直接建 FAISS 索引和线程池；MCP 工具直接调用 `Memoryos`，Flask 路由直接持有全局实例表。因而本轮裁决是“提取能力并归位”，不是把这些跨层直连当作可复用底座契约。

### 11.2 分层映射表

| 当前源码能力/资源 | 当前证据 | 平台归属 | 第三轮裁决 |
|---|---|---|---|
| QA、时间戳、随机 id、JSON 序列化 | `short_term.py:18-25, 41-66`；`utils.py:119-126` | 支持库原子能力；schema 由公共契约冻结 | 吸收；禁止让每个记忆模块自定义时间/id/错误形状 |
| `short_term` 容量 deque 与逐次保存 | `short_term.py:9-45` | 记忆/状态模块调用存储支持库 | 吸收语义，升级为有版本、原子写、恢复和事件留痕的状态记录 |
| Page/Session、链指针、`H_segment`、LFU、heap | `mid_term.py:26-36, 38-51, 103-179, 281-362` | 记忆/状态模块 | 吸收为 Agent 记忆策略，不下沉为通用文件/向量支持库 |
| 画像、用户私有知识、助手知识 | `long_term.py:16-23, 26-75` | 记忆/状态模块的领域状态；向量写入委托支持库 | 吸收数据边界；“用户/助手”语义是产品策略，不是通用存储字段 owner |
| 短期晋升、连续性、主题摘要、页面链、长期抽取 | `updater.py:100-207`；`memoryos.py:126-224` | 记忆/状态模块的巩固编排；任务生命周期由运行核心托管 | 吸收流程，拆出明确命令、事件和可恢复任务状态 |
| 三路并行检索与 top-k 堆 | `retriever.py:34-130` | 记忆/状态模块负责组合；向量检索、排序、索引为支持库 | 升级；模块不能直接构造 FAISS/Chroma 或吞掉异常 |
| OpenAI-compatible chat、Embedding、模型缓存 | `utils.py:37-98, 142-211` | 支持库适配层/模型提供者；线程池、预算、超时、崩溃由运行核心 | 吸收提供者边界；禁止把具体模型名和模型对象泄露给模块调用方 |
| JSON 文件、FAISS 临时索引 | `short_term.py`、`mid_term.py`、`long_term.py` | 支持库后端；文件一致性和索引生命周期是运行核心治理 | 保留为候选提供者，不把 JSON+FAISS 定为唯一实现 |
| Chroma 集合 + metadata JSON 备份 | `storage_provider.py:17-36, 57-80, 102-172` | 支持库后端提供者；双写一致性由运行核心/状态模块协同 | 吸收为替代提供者；必须补事务、摘要、恢复和残留契约 |
| `add_memory`、`retrieve_memory`、`get_user_profile` | `memoryos-mcp/server_new.py:59-258` | 网关能力的适配层接口；实际执行仍走唯一能力链 | 吸收公开意图，废弃 MCP 自己持有一套执行逻辑 |
| Flask `/chat`、`/memory_state` 等演示路由 | `memoryos-playground/memdemo/app.py:62-424` | 网关/项目适配示例，不是记忆内核 | 隔离为演示适配；不能把全局 `memory_systems` 当平台会话服务 |
| 论文评估和 `eval/` 旧链路 | `eval/*.py`、现有第 8 节 | 研究/评估资产 | 隔离；不注册为第二套记忆内核或生产检索链 |
| skill/技能对象与技能注册表 | 当前源码未发现；MCP 只有三个工具 | 网关上的 Agent 产品层能力，不属于 MemoryOS 通用底座 | 待核/不宣称已实现；技能调用必须以后端能力契约为唯一执行入口 |

### 11.3 记忆层级与 L0-L4

MemoryOS 当前明确实现短期、中期、长期三层；为了接入平台，采用五级语义，但不伪称源码已经存在 L0/L4：

| 层级 | 平台统一语义 | MemoryOS 当前映射 | 权威 owner | 典型生命周期 |
|---|---|---|---|---|
| L0 | 当前请求工作集/瞬时上下文 | `get_response()` 的 query、短期历史、检索结果、prompt 文本；不独立持久化 | 运行上下文 + 记忆模块查询结果 | 请求创建 → 组装 → 生成/失败/取消 → 释放 |
| L1 | 原始近期事件 | `ShortTermMemory` 的 QA deque，`short_term.json` 或 Chroma metadata 的 `short_term_memory` | 记忆/状态模块写 owner；存储支持库落盘 | 接收 → 满容量 → 晋升/淘汰；失败不得静默丢失 |
| L2 | 经整理的会话/经历 | `Page`、`Session`、`pre_page/next_page`、摘要、关键词、embedding、热度 | 记忆/状态模块 | 创建/合并 → 访问升温 → 检索 → 巩固/淘汰 |
| L3 | 稳定画像与知识 | `user_profiles`、`knowledge_base`、`assistant_knowledge` | 记忆/状态模块；向量索引为派生读模型 | 抽取候选 → 校验 → 提交 → 检索/版本替换 → 过期或归档 |
| L4 | 跨会话 Agent 经验、技能策略、领域知识产品 | 当前未实现；`prompts.py` 只是提示词，MCP 工具也不是技能状态 | Agent 产品模块/策略中心；底座只提供契约、存储、检索和执行资源 | 候选经验 → 评估/授权 → 发布 → 版本化使用 → 回滚/废弃 |

固定边界：L0/L1/L2/L3 是本项目可直接吸收的记忆数据和流程；L4 只能作为平台预留产品层，不得把“画像/知识抽取”扩大解释为技能学习、自动改写 Agent 策略或跨用户共享。用户记忆、助手知识和跨 Agent 技能必须按 owner、租户、权限和生命周期隔离。

### 11.4 事件与状态：当前事实、目标契约

当前源码没有统一事件总线、事件账本或状态机。可观察状态散落在 `is_full()`、`page["analyzed"]`、`session["H_segment"]`、`N_visit`、`L_interaction`、`access_frequency`、`heap`、画像时间和 Chroma `update_times` 中；并行任务以临时 `Future` 表示，异常多被打印后转空列表/固定错误字符串。因此下表的事件名是平台目标契约，不是源码已存在的类名。

```text
记忆命令
  ├─ 记忆接收
  ├─ 记忆查询
  ├─ 强制巩固
  ├─ 清理/删除
  └─ 状态读取
       │
       ▼
记忆状态模块（唯一状态写 owner）
  ├─ L0/L1/L2/L3 记录与版本
  ├─ 巩固任务状态
  ├─ 检索读模型/索引指针
  └─ 追加不可覆盖事件与证据
```

建议冻结的最小领域事件：`MemoryAccepted`、`ShortTermFull`、`PagePromoted`、`SessionCreated`、`SessionMerged`、`RetrievalCompleted`、`ConsolidationRequested`、`ConsolidationCompleted`、`ConsolidationFailed`、`ProfileUpdated`、`KnowledgeAdded`、`MemoryCleared`。每个事件至少带 `event_id`、`request_id`、`user_id`、`assistant_id`、`memory_level`、`occurred_at`、`state_version`、`idempotency_key`、结果/错误和资源释放证据。

状态必须分两类，不能混成一个 `status` 字符串：

1. **记忆领域状态**：L1 是否接收、L2 session 是否已分析、L3 画像/知识版本、索引是否落后、待巩固页集合；由记忆/状态模块持有。
2. **执行资源状态**：任务 `created → admitted → queued → running → succeeded/failed/cancelled/timed_out/crashed → draining → cleaned`，模型/存储/索引执行单元的健康、租约和释放；由运行核心持有。

事件是追加事实，状态是可重建投影；任何向量索引、heap、access frequency 都应视为可重建派生状态，不能反过来成为唯一事实源。事件写入、权威状态提交和索引发布必须规定顺序，并对崩溃窗口做恢复对账。

### 11.5 存储、检索、技能、模型和服务资源的归位

| 领域 | 通用底座应提供 | Agent 产品策略应提供 | MemoryOS 当前缺口 |
|---|---|---|---|
| 存储 | 记录 schema、版本迁移、原子写/替换、快照、摘要、租户隔离、备份恢复、失败证据 | 哪些字段属于 QA/Page/Session/Profile/Knowledge、容量和淘汰策略 | JSON 覆盖写、进程内锁、无 schema/迁移；Chroma metadata 与向量非事务双写 |
| 检索 | embedding provider 契约、向量索引 CRUD/query、top-k/距离结果形状、索引重建和版本指针 | 中期页/用户知识/助手知识三路融合、阈值、排序、上下文预算 | PyPI 每次建 FAISS；Chroma 与 JSON 备份分离；异常常返回空列表 |
| 更新/巩固 | 有界任务、幂等、重试、截止时间、取消、checkpoint、任务状态和恢复 | “短期满即晋升”“热度达阈值抽取画像/知识”“主题合并” | 过程在同步调用中执行，Future 无 deadline/cancel/checkpoint，LLM 失败可能仍形成 fallback session |
| 模型 | chat/embedding 统一请求响应、模型版本/配置摘要、密钥引用、资源预算和提供者隔离 | 选择 `llm_model`、embedding 模型、提示词、温度/max tokens、抽取格式 | `OpenAIClient` 捕获异常转固定文本；模型缓存为进程全局，未统一释放/版本证据 |
| 技能 | 技能声明、参数契约、权限、版本、调用/撤销、资源预算 | 将“记忆接收/查询/画像/巩固”编排成 Agent 可用技能，并绑定产品权限 | 没有技能实体或注册表；MCP 三工具是网关工具，不等于技能系统 |
| 服务资源 | MCP/HTTP/进程/端口/线程/连接/临时文件的监督和生命周期 | 是否启用 MCP、是否开放记忆查询、每用户会话和产品配额 | MCP 是 stdio 单全局实例；Flask 用全局字典；没有统一认证、租约和服务管理 |

**支持库**只承载可复用的原子能力：安全 JSON/文件、结构化记录、时间/id、向量化、向量检索、模型调用、受管制品和必要的进程/线程动作。支持库不决定“什么算用户画像”、不拼 prompt、不选择热度阈值。

**记忆/状态模块**承载 L0-L4 的领域模型、领域事件、状态投影、晋升/合并/淘汰、巩固策略、检索编排和上下文构建。它只能通过支持库公开能力读写和调用模型，不能直接 `import faiss/chromadb/openai` 或直接持有第三方连接。

**运行核心**承载任务准入、队列、线程/进程、资源预算、deadline、取消、租约、健康、缓存、崩溃回收、状态恢复、证据和零残留；它不决定记忆内容，也不把 `H_segment` 当通用调度优先级。

**网关**只承载搜索/契约/执行/状态查询的统一通信面。平台当前冻结为 HTTP 网关核心（默认 8866），MCP 是可选薄适配层；MemoryOS 的 `server_new.py` 可以作为适配参考，但不得继续拥有一份直达 `Memoryos` 的旁路执行逻辑。

### 11.6 唯一链路与调用闭环

#### 接收/写入链

```text
POST /能力/执行（记忆.接收）
  → 网关请求 id/参数/大小/权限校验
  → 项目适配层绑定 user/assistant/策略版本
  → 运行核心准入、幂等键、deadline、资源预算
  → 记忆/状态模块.接收记忆
  → 支持库.状态记录/原子写入（L1）
  → 若达到容量：提交巩固任务/读取 L1 批次
  → 支持库.模型调用 + 支持库.embedding
  → 记忆/状态模块创建/合并 L2，追加领域事件
  → 若达到热度：提交 L3 巩固任务并以 checkpoint 记录
  → 索引/快照发布、统一结果和释放证据
  → 网关返回 request_id + 状态/事件摘要
```

#### 查询/回答链

```text
POST /能力/执行（记忆.回答）
  → 网关/适配层/运行核心唯一入口
  → 记忆/状态模块读取 L0/L1
  → 记忆模块提交一次检索编排
       → 支持库.embedding(query)
       → 支持库.vector_search(L2)
       → 支持库.vector_search(L3 user)
       → 支持库.vector_search(L3 assistant)
  → 记忆模块按 Agent 策略合并、排序、截断上下文
  → 支持库.chat_completion（受管模型执行单元）
  → 记忆模块将 query/answer 作为 L1 接收事件
  → 运行核心排空/缓存或释放模型、线程、索引和临时资源
  → 网关只返回统一回答结果与证据
```

“检索后自动写回”是当前 `memoryos-pypi/memoryos.py:252-348` 和 Chroma 变体的产品语义，不能在 MCP、Flask、SDK 各复制一遍。`add_memory`、`get_response`、`retrieve_memory`、`get_user_profile` 最终应归一到记忆模块的公开命令/查询；所有出口只能映射到同一能力 id、同一结果和同一事件链。

#### 唯一性不变式

- 一个原子能力只有一个能力 id、一个契约 owner、一个注册/调用入口；JSON+FAISS 与 Chroma 只能是同契约下的提供者，不能各自向上暴露不同返回形状。
- 一个记忆领域流程只有一个模块入口；MCP、HTTP、Flask、Python SDK 只能是适配器，不得另写巩固/检索/回答链。
- 权威事实只有一个写 owner：L1-L3 记录和领域事件归记忆/状态模块；向量索引、heap、缓存是派生读模型；任务/资源状态归运行核心。
- 任何 provider 选择、错误转换、超时、取消、崩溃、释放和证据都不能被模块或网关旁路重写。

### 11.7 资源生命周期、失败、超时、取消与崩溃

| 资源 | 创建/持有 | 正常完成 | 失败/超时/取消 | 宿主崩溃与当前缺口 |
|---|---|---|---|---|
| JSON 文件句柄 | `save/load` 的 `open()` 临时创建；模块持有路径 | `json.dump` 后关闭 | 当前只打印 `IOError`；无原子临时文件、fsync、回滚或写后校验 | 进程中断可能留下空/半写文件；应由支持库原子替换+快照恢复 |
| Chroma client/集合 | `ChromaStorageProvider.__init__` 创建 PersistentClient 和三集合 | `save_all_metadata()` 写 metadata JSON；向量另行写入 | 查询/删除异常多转空结果或打印；metadata 与向量无事务 | `atexit` 只覆盖正常解释器退出；应由运行核心恢复双写、重建索引、清理租约 |
| FAISS 索引 | `search_sessions`/知识检索中按请求创建 IndexFlatIP | 函数返回后成为临时对象 | 无独立取消/预算；embedding 异常向上层传播或被检索器吞掉 | 无需跨进程恢复，但索引版本/维度/模型摘要应可重建校验 |
| Embedding/模型缓存 | `utils._model_cache`、`_embedding_cache` 进程全局建立 | 命中缓存或进程存续 | 没有模型卸载、租约和内存预算；缓存仅按数量粗略清理 | 崩溃由宿主回收；GPU/原生扩展应隔离到受管提供者 |
| OpenAI client/线程池 | `OpenAIClient.__init__` 创建 SDK client 和 `ThreadPoolExecutor` | `chat_completion` 返回；`shutdown()` 存在但 Memoryos 未调用 | `chat_completion` 把异常转固定字符串；`future.result()` 没有 deadline/cancel | PyPI 缺明确 close；Chroma 只保存 metadata；运行核心必须统一排空/join/释放 |
| 巩固/检索 Future | `Updater`/`Retriever` 临时 `ThreadPoolExecutor` 提交 | 上下文管理器等待 Future | Future 异常转 `None`/`[]` 或提前返回；无幂等 checkpoint | 线程不能证明被中断；改为运行核心任务状态+协作取消，阻塞/原生任务转独立进程 |
| L1-L3 状态 | 记忆对象内存结构 + JSON/metadata | 单层 `save()` 或 metadata 保存 | 单层保存成功不代表向量/备份一致；容量淘汰可能是破坏性写入 | 需状态版本、事件账本、恢复对账和索引重建，禁止以空状态覆盖未知损坏 |
| MCP/Flask 服务 | `mcp.run(transport="stdio")`；Flask `app.run`；全局实例表 | 正常返回/退出 | 仅入口级异常 JSON/exit1；无租约、排空、认证和取消 | 崩溃不保证实例/任务/文件清理；网关与运行核心应接管服务状态 |

#### 失败矩阵与平台要求

| 场景 | 当前实现事实 | 平台统一要求 |
|---|---|---|
| 缺配置/缺 provider | MCP 初始化缺字段抛异常并退出；模型导入/调用错误路径不统一 | 稳定错误码、可重试性、诊断信息脱敏；不得进入“成功写记忆” |
| 空输入/非法参数 | MCP 工具对空输入返回 `status=error`；SDK 入口没有完整 schema 校验 | 网关/契约先校验，拒绝事件也留证；统一返回 `{成功, 值, 错误码, 错误说明}` |
| 损坏/非法 JSON | 各层 `JSONDecodeError` 后初始化空内存 | 先隔离损坏制品、保留证据、尝试快照恢复；不能静默把历史变成空库 |
| LLM 异常/输出解析失败 | `OpenAIClient` 返回固定错误字符串；多摘要失败降级为 general session；知识解析依赖文本标记 | provider 错误与业务降级分开；schema 校验；部分成功必须有状态和重试语义，错误文本不能当记忆内容 |
| 检索/Chroma 异常 | `Retriever`、Chroma provider 多处把异常转 `[]` | 返回可诊断的 `RETRIEVAL_UNAVAILABLE`/降级标识；不得把“没有结果”和“检索失败”混为一谈 |
| 超时 | 当前没有请求 deadline；`future.result()` 可无限等待 | 运行核心强制 deadline、真实终止阻塞 provider、排空队列、记录 timed_out 和可重试 |
| 主动取消 | 源码未实现取消令牌或取消 API | 协作取消优先；无法安全终止的模型/原生任务独立进程 killpg，并等待/验证残留 |
| 线程/提供者异常 | 局部捕获并打印，调用者可能继续拿到空/固定文本 | 任务状态进入 failed/crashed，资源释放结论必填，不能伪报成功 |
| 进程崩溃/强杀 | Chroma 的 `atexit` 不覆盖 SIGKILL；JSON/metadata 无恢复事务 | 启动时扫描未完成任务/租约/临时目录，恢复权威状态、重建索引、清理进程组和端口 |
| 重复写/重试 | `add_memory` 没有幂等键；随机 page/session id 可能重复生成新记录 | `request_id + idempotency_key` 去重，巩固和事件追加可重放，重复释放/清理幂等 |
| 部分提交 | Chroma 向量与 metadata 分开写；JSON 覆盖写非事务 | 先写意图/事件，再原子提交权威状态，再发布派生索引；恢复按版本对账 |

### 11.8 通用底座与 Agent 产品策略的最终裁决

```text
通用底座（跨软件复用）
  公共契约/记录 schema/错误码/事件外壳
  → 支持库：存储、快照、向量、模型、时间、序列化、受管资源
  → 运行核心：任务、资源、超时、取消、崩溃恢复、证据
  → 网关：搜索、契约、执行、状态；MCP 为薄适配

Agent 产品策略（可替换，不污染底座）
  → L0-L4 语义及租户/用户/助手关系
  → QA→Page→Session→Profile/Knowledge 的晋升策略
  → 热度公式、相似度阈值、容量、top-k、上下文预算
  → 提示词、画像/知识抽取 schema、回答风格
  → 技能声明、授权、发布和 L4 经验策略
```

裁决如下：

1. **吸收**：三层记忆的数据边界、短期容量触发、Page/Session 链、热度驱动巩固、用户/助手知识分离、三路检索结果和 OpenAI-compatible 模型边界，作为记忆/状态模块的候选设计。
2. **升级现有底座**：将 JSON/Chroma/FAISS、Embedding、LLM、线程池和文件保存改为统一支持库/提供者契约；把统一结果、版本、事件、快照、资源预算和故障证据接入运行核心；把 MCP/Flask/SDK 收敛成同一网关能力的适配器。
3. **新建但不在本任务实施**：记忆/状态模块的领域 schema、L0-L4 状态投影、巩固任务状态、记忆事件账本和索引重建协议；这些必须先登记需求、搜索现有能力、形成复用/新建裁决和验收契约。
4. **隔离/废弃为生产入口**：`memoryos-mcp` 内复制的独立包、Playground 全局实例表、`eval/` 旧记忆链和每个变体各自直连 provider 的路径，保留源码参考但不再作为第二套生产内核。这里的“废弃”只指平台接入资格，不删除本仓库源码。
5. **待核**：L4 技能/经验沉淀、跨 Agent 记忆共享、Chroma 事务恢复、模型/Embedding 的真实资源预算、不同变体的返回兼容性；当前没有运行证据，不能宣称完成。

本项目不是“直接接入一个 MemoryOS 包”，而是提供一组 Agent 记忆策略候选。真正进入平台前，至少要冻结：领域事件与状态 schema、唯一能力 id、L1-L3 存储/索引一致性、巩固任务的幂等/恢复、模型与向量 provider 的资源契约、网关请求/响应契约，以及四种终态（正常、业务失败、超时/取消、崩溃）的实测证据。

### 11.9 本轮修改与验证边界

- 允许修改且实际修改：仅目标根 `ARCHITECTURE.md`；未修改 MemoryOS 源码、依赖、配置、测试、README、论文或 Git。
- 本轮没有安装依赖、启动 MCP/Flask、调用外部 LLM/Embedding、写入 MemoryOS 数据目录或执行会改变记忆数据的集成测试。
- 代码图事实：已按任务先调用 `codegraph_explore`，返回目标项目未发现 `.codegraph/`，因此本轮按内置只读文件读取完成；不能把代码图查询当作成功证据。
- 开工上下文事实：首条 `project_context` 错绑到 `~/Documents/Agent/PHP/华世王镞_v3`，返回项目名与目标不一致；随后已显式以 MemoryOS 绝对路径做文件盘点。专属 MCP `system_engineering_toolkit`/`project_toolkit` 本轮在 `development_start` 时不可达，故 MCP 开工 id、反馈入账和正式验证状态必须如实标为未完成，不能伪造成功。
- 旧细探：目标树未发现独立 `细探-MemoryOS.md`，本轮未删除旧细探；现有正式文档的吸收声明保留。
