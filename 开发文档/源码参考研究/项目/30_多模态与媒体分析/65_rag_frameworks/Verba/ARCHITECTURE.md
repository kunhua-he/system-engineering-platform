# Verba 架构建档

## 1. 文档定位与证据范围

本文是本地归档仓库 `Verba` 的唯一架构建档，结论来自以下已读取证据：

- `README.md`：产品定位、功能矩阵、部署方式、环境变量和项目已归档声明。
- `TECHNICAL.md`：FastAPI、`ClientManager`、`BatchManager` 和 JSON 数据形状说明；其中部分章节明确标记 `TODO`。
- `FRONTEND.md`：Next.js/TailwindCSS/DaisyUI 构建与静态资源复制约定。
- `setup.py`、`Dockerfile`、`docker-compose.yml`、`frontend/package.json`：依赖、入口、构建和容器拓扑。
- `goldenverba/`：服务、编排、组件、数据模型和持久化实现。
- `goldenverba/tests/`：当前仓库内的 pytest 测试。
- `细探-Verba.md`：既有细探结论；当前核对已逐项核对并吸收，按任务边界保留原文件，不删除或改写。

源码标识、路径、类名、函数名、字段名、路由和命令均保留原文；说明、备注、风险和结论使用中文。

## 2. 项目概览

`Verba`（Python 包名 `goldenverba`）是 Weaviate 的社区版端到端 RAG 应用：通过 Web 前端选择部署与 RAG 组件，导入文件或 URL，执行读取→分块→向量化→Weaviate 存储→混合检索→LLM 流式生成。它是单用户导向的应用型参考实现，不是通用多租户 RAG 服务。

README 顶部明确声明：`Project Discontinued — Repository Archived`。项目不再接受维护、修复、安全补丁或新功能；代码仅作参考或 fork 基础，不能按仍受支持的软件选型。

- 上游仓库：`https://github.com/weaviate/Verba.git`
- 本地根目录：`/Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/65_rag_frameworks/Verba`
- Python 包版本：`goldenverba 2.1.3`（`setup.py`）
- 前端版本：`verba 2.1.0`（`frontend/package.json`）；页面显示版本字符串为 `v2.0.0`
- 许可证：`LICENSE` 为 Weaviate BSD 风格许可证（文件版权年份 `2020-2023`）
- 运行约束：`Python >=3.10.0,<3.13.0`；前端文档要求 Node.js `>=21.3.0`
- 代码规模（当前工作树文件计数）：`goldenverba/**/*.py` 55 个，`frontend/**/*` 68 个（包含前端配置、源码和资源；不含 `node_modules`）

## 3. 总体架构

```text
浏览器（Next.js 静态前端）
  │
  ├─ GET /api/health ────────────────┐
  ├─ POST /api/*（JSON + Origin）     │
  ├─ WS /ws/import_files             │
  └─ WS /ws/generate_stream          │
                                    ▼
                         goldenverba.server.api:app
                                    │
                    ClientManager（连接缓存、锁、清理）
                                    │
                       VerbaManager（应用编排门面）
       ┌────────────────────────────┼────────────────────────────┐
       ▼                            ▼                            ▼
 ReaderManager                 ChunkerManager              EmbeddingManager
 读取文件/URL                   分块/语义分块                 批量向量化 + PCA
       │                            │                            │
       └──────────────► Document ──► Chunk ──────────────────────┘
                                    │
                                    ▼
                          WeaviateManager
             VERBA_DOCUMENTS / VERBA_Embedding_* / VERBA_CONFIGURATION
                         / VERBA_SUGGESTIONS
                                    │
                  RetrieverManager（当前 WindowRetriever）
                    Weaviate hybrid search + chunk window
                                    │
                                    ▼
                    GeneratorManager（LLM 流式生成）
         Ollama / OpenAI / Anthropic / Cohere / Groq / Novita / Upstage / AtlasCloud
```

### 3.1 请求与连接边界

- `goldenverba/server/api.py` 创建全局 `FastAPI` 应用，并在模块导入时实例化全局 `manager = verba_manager.VerbaManager()`、`client_manager = verba_manager.ClientManager()`。
- `ClientManager` 按 `deployment:url:key` 的 SHA-256 哈希缓存 `WeaviateAsyncClient`，按凭证哈希维护 `asyncio.Lock`，连接超过 `max_time = 10` 分钟或 `is_ready()` 失败时清理。
- `/api/*` 除 `/api/health` 外受自定义 `check_same_origin` 中间件约束：要求 `Origin` 等于请求基础 URL，或为 localhost 同源形式。CORS 中间件本身允许 `*`，实际限制由自定义中间件承担。
- `lifespan` 退出时调用 `client_manager.disconnect()`；正常连接和 API 错误主要转换为 JSON 错误，不统一抛出 HTTP 异常。

### 3.2 导入数据流

```text
前端 FileConfig JSON
  → frontend/app/components/Ingestion/IngestionView.tsx
  → 每 2000 字符切批，发送 DataBatchPayload
  → WS /ws/import_files
  → BatchManager.add_batch()
  → 收齐 total 批并按 order 拼接 JSON
  → FileConfig.model_validate_json()
  → VerbaManager.import_document()
  → ReaderManager.load()
  → list[Document]
  → ChunkerManager.chunk()
  → list[Document]（每个 Document 含 list[Chunk]）
  → EmbeddingManager.vectorize()
  → Chunk.vector / Chunk.pca
  → WeaviateManager.import_document()
  → 文档与向量块分别写入 Weaviate
  → LoggerManager.send_report()
  → 前端接收 READY/STARTING/LOADING/CHUNKING/EMBEDDING/INGESTING/DONE/ERROR
```

`VerbaManager.import_document()` 先按文件名检测重复文档；默认拒绝重复，`overwrite` 时先删除旧文档。URL 读取器可能产生多个 `Document`，每个文档都会经 `process_single_document()` 独立分块、向量化和入库。处理任务使用 `asyncio.gather(..., return_exceptions=True)`，成功数不足时发送错误报告。

### 3.3 查询与生成数据流

```text
前端输入 query
  → POST /api/query（QueryPayload）
  → ClientManager.connect()
  → VerbaManager.retrieve_chunks()
  → EmbeddingManager.vectorize_query()
  → RetrieverManager.retrieve()
  → WindowRetriever.retrieve()
  → WeaviateManager.hybrid_chunks()
  → 按 doc_uuid 聚合、分数排序、补 chunk window
  → 返回 documents + context
  → 前端建立/复用 WS /ws/generate_stream
  → GeneratePayload
  → GeneratorManager.generate_stream()
  → 具体 Generator.prepare_messages() + 外部 LLM SSE
  → 每个 chunk {message, finish_reason}
  → 最后一个结果补 full_text
```

`/api/query` 只负责检索，回答生成由 `/ws/generate_stream` 另行完成；前端先拿检索结果和上下文，再通过 WebSocket 发起流式回答。`VerbaManager.retrieve_chunks()` 会把查询写入 `VERBA_SUGGESTIONS`，用于自动补全建议。

## 4. 目录与模块地图

```text
Verba/
├── README.md                         产品说明、功能矩阵、部署和环境变量
├── TECHNICAL.md                      后端技术说明（部分 TODO）
├── FRONTEND.md                       前端构建说明
├── setup.py                          Python 包、依赖和 verba 入口
├── Dockerfile                        Python 3.11 镜像入口
├── docker-compose.yml                verba + Weaviate 拓扑
├── CONTRIBUTING.md                   pytest 和贡献流程
├── LICENSE                           BSD 风格许可证
├── pypi_commands.sh                  PyPI 辅助命令
├── frontend/
│   ├── app/
│   │   ├── page.tsx                  页面状态总编排和页面切换
│   │   ├── api.ts                     前端 HTTP API 封装
│   │   ├── types.ts                   前端类型
│   │   ├── util.ts                    HTTP/WebSocket 地址计算
│   │   └── components/
│   │       ├── Login/                连接、部署和初次使用
│   │       ├── Navigation/            导航、状态和用户弹窗
│   │       ├── Chat/                  查询、检索结果和流式问答
│   │       ├── Ingestion/             文件选择、配置和批量上传
│   │       ├── Document/              文档、块、内容和向量浏览
│   │       └── Settings/              RAG、主题和建议设置
│   ├── package.json                   Next.js/React/Tailwind/Three 依赖
│   ├── package-lock.json              前端锁定依赖
│   └── next.config.js                 Next.js 配置
├── goldenverba/
│   ├── __init__.py
│   ├── .env.example                   环境变量样例
│   ├── verba_manager.py               VerbaManager、ClientManager
│   ├── components/
│   │   ├── interfaces.py              VerbaComponent 五类组件契约
│   │   ├── types.py                   InputConfig
│   │   ├── document.py                 Document 和语言处理
│   │   ├── chunk.py                    Chunk 数据对象
│   │   ├── managers.py                 Weaviate/Reader/Chunker/Embedding/Retriever/Generator Manager
│   │   ├── reader/                     Basic、HTML、Git、Unstructured、AssemblyAI、Firecrawl、Upstage
│   │   ├── chunking/                   Token、Sentence、Recursive、Semantic、HTML、Markdown、Code、JSON
│   │   ├── embedding/                  Ollama、SentenceTransformers、Weaviate、Upstage、VoyageAI、Cohere、OpenAI
│   │   ├── retriever/                  WindowRetriever（Advanced）
│   │   └── generation/                 Ollama、AtlasCloud、OpenAI、Anthropic、Cohere、Groq、Novita、Upstage
│   ├── server/
│   │   ├── api.py                     FastAPI 路由与 WebSocket
│   │   ├── cli.py                     `verba start` / `verba reset`
│   │   ├── types.py                   Pydantic 请求/配置/状态模型
│   │   ├── helpers.py                 LoggerManager、BatchManager
│   │   └── frontend/out/              已构建的静态 Next.js 输出
│   └── tests/
│       ├── document/test_document.py  Document 测试
│       └── chunk/test_chunk.py         Chunk 序列化测试
└── img/                               README 和产品截图/模型资源
```

## 5. 核心组件契约

### 5.1 `goldenverba/components/interfaces.py`

`VerbaComponent` 是所有组件基类，统一暴露：

- `name`：组件显示与选择名。
- `requires_env`：所需环境变量。
- `requires_library`：所需 Python 库。
- `description`、`config`、`type`：前端元数据。
- `get_meta(envs, libs)`：返回 `name/variables/library/description/type/config/available`。
- `check_available(envs, libs)`：依赖环境变量和库均满足才可用。

五类接口：

| 接口 | 关键方法 | 当前实现 |
|---|---|---|
| `Reader` | `load(config, fileConfig) -> list[Document]` | `BasicReader`、`HTMLReader`、`GitReader`、`UnstructuredReader`、`AssemblyAIReader`、`FirecrawlReader`、`UpstageDocumentParseReader` |
| `Chunker` | `chunk(config, documents, embedder, embedder_config) -> list[Document]` | 8 种 chunker |
| `Embedding` | `vectorize(config, content) -> list[float]`；`max_batch_size=128` | 7 种 embedder |
| `Retriever` | `retrieve(client, query, vector, config, weaviate_manager, embedder, labels, document_uuids)` | `WindowRetriever` |
| `Generator` | `generate_stream(...)`、`prepare_messages(...)`；默认 `context_window=5000` | 8 种 generator |

`Generator` 的默认系统提示词要求只能依据提供的上下文回答、指出使用的文档、信息不足时承认不足，并支持代码块；可由环境变量 `SYSYEM_MESSAGE_PROMPT` 覆盖（源码字段拼写保持为 `SYSYEM_MESSAGE_PROMPT`）。

### 5.2 组件注册与配置

`goldenverba/components/managers.py` 在模块级构造 `readers`、`chunkers`、`embedders`、`retrievers`、`generators` 列表，再由各 Manager 以组件 `name` 建立字典。`VerbaManager.create_config()` 将五类组件统一序列化为：

```text
{
  "Reader":   {"components": {name: RAGComponentConfig}, "selected": name},
  "Chunker":  {"components": {name: RAGComponentConfig}, "selected": name},
  "Embedder": {"components": {name: RAGComponentConfig}, "selected": name},
  "Retriever":{"components": {name: RAGComponentConfig}, "selected": name},
  "Generator":{ "components": {name: RAGComponentConfig}, "selected": name}
}
```

`VerbaManager.verify_installed_libraries()` 和 `verify_variables()` 启动时探测组件所需库和环境变量，最终写入组件的 `available` 元数据。组件列表会根据 `VERBA_PRODUCTION == "Production"` 排除部分本地组件，但 Reader 和 Chunker 基本保持一致。

### 5.3 `WindowRetriever`

`goldenverba/components/retriever/WindowRetriever.py` 当前唯一 Retriever，名称为 `Advanced`，仅实现 `Hybrid Search`。默认配置：`Limit Mode=Autocut`、`Limit/Sensitivity=1`、`Chunk Window=1`、`Threshold=80`，窗口被限制在 `0..10`，阈值被限制在 `0..100` 后转为比例。

实现步骤：

1. 调用 `WeaviateManager.hybrid_chunks()`，`alpha=0.5`，支持 labels 和 document UUID 过滤。
2. 按 `doc_uuid` 聚合结果并累加 chunk score。
3. 归一化分数，达到阈值的结果补取相邻 chunk。
4. 按 `chunk_id` 排序，形成前端 `documents` 和拼接文本 `context`。
5. 无命中返回 `([], "We couldn't find any chunks to the query")`。

备注：`normalize_value()` 在最大分数等于最小分数时存在除零风险；这是源码级风险，不在当前核对修复。

## 6. 数据模型与持久化

### 6.1 Python 对象

`goldenverba/components/document.py` 的 `Document` 字段：

| 字段 | 含义 |
|---|---|
| `title` | 文档标题/文件名 |
| `content` | 原始内容 |
| `extension` | 扩展名 |
| `fileSize` | 字节数 |
| `labels` | 标签列表 |
| `source` | 来源 URL 或来源标识 |
| `meta` | 内部组件配置元数据，最终 JSON 字符串化存储 |
| `metadata` | 用户/文档元数据文本，参与 embedding 上下文 |
| `chunks` | `list[Chunk]`，运行时字段，不直接由 `Document.to_json()` 写入 |
| `spacy_doc` | 语言检测和分句后的 spaCy 对象，运行时字段 |

内容超过 `MAX_BATCH_SIZE = 500000` 时按批创建 spaCy `Doc` 并用 `Doc.from_docs()` 合并；支持 `en/zh/zh-hant/fr/de/nl`，其他语言回退到 `en`。

`Document.to_json()` 生成 Weaviate 文档属性；`Document.from_json()` 要求 `title/content/extension/fileSize/labels/source/meta/metadata` 全部存在，否则返回 `None`。

`goldenverba/components/chunk.py` 的 `Chunk` 字段包括 `content`、`content_without_overlap`、`chunk_id`、`start_i`、`end_i`、`title`、`vector`、`doc_uuid`、`pca`、`labels`。`Chunk.to_json()` 不写 `vector`，向量作为 Weaviate `DataObject(..., vector=chunk.vector)` 的向量字段独立写入。

### 6.2 Pydantic API 模型

`goldenverba/server/types.py` 的关键模型：

- 连接：`Credentials`（`deployment` 仅允许 `Weaviate|Docker|Local|Custom`、`url`、`key`）、`ConnectPayload`。
- 导入：`DataBatchPayload`、`FileConfig`、`ImportStreamPayload`、`FileStatus`、`StatusReport`、`CreateNewDocument`。
- RAG：`ConfigSetting`、`RAGComponentConfig`、`RAGComponentClass`、`RAGConfig`。
- 查询：`QueryPayload`、`DocumentFilter`、`ChunkScore`、`GeneratePayload`、`SearchQueryPayload`。
- 文档浏览：`GetDocumentPayload`、`DatacountPayload`、`GetContentPayload`、`GetVectorPayload`、`ChunksPayload`、`GetChunkPayload`。
- 配置与管理：`SetRAGConfigPayload`、`SetUserConfigPayload`、`SetThemeConfigPayload`、`ResetPayload`。

### 6.3 Weaviate 集合与关键属性

`WeaviateManager` 固定集合名：

| 集合 | 用途 |
|---|---|
| `VERBA_DOCUMENTS` | 文档属性：`title`、`content`、`extension`、`fileSize`、`labels`、`source`、`meta`、`metadata` |
| `VERBA_Embedding_<模型名清洗值>` | 按 embedding 模型隔离 chunk；chunk 属性含 `content`、`content_without_overlap`、`chunk_id`、`doc_uuid`、`title`、`labels`、`pca`，向量写入 default 向量空间 |
| `VERBA_CONFIGURATION` | 以固定 UUID 存储 RAG、theme、user JSON 配置 |
| `VERBA_SUGGESTIONS` | 查询建议：`query`、`timestamp` |

embedding 集合名通过 `re.sub(r"[^a-zA-Z0-9]", "_", embedder)` 生成，并保存在 `embedding_table`。导入文档时先写文档对象，再批量写 chunk；chunk 数量校验失败会删除文档和已写入 chunk，尽量回滚本次导入。

三个配置 UUID：

- `rag_config_uuid = e0adcc12-9bad-4588-8a1e-bab0af6ed485`
- `theme_config_uuid = baab38a7-cb51-4108-acd8-6edeca222820`
- `user_config_uuid = f53f7738-08be-4d5a-b003-13eb4bf03ac7`

## 7. HTTP API 与 WebSocket 契约

### 7.1 静态和健康检查

| 方法 | 路由 | 处理函数 | 结果 |
|---|---|---|---|
| `GET/HEAD` | `/` | `serve_frontend` | 返回 `goldenverba/server/frontend/out/index.html` |
| `GET` | `/api/health` | `health_check` | `{message, production, gtag, deployments, default_deployment}` |

静态目录：`/static/_next` → `goldenverba/server/frontend/out/_next`；`/static` → `goldenverba/server/frontend/out`。

### 7.2 连接、配置和 RAG

| 方法 | 路由 | 处理函数 | 输入/输出摘要 |
|---|---|---|---|
| `POST` | `/api/connect` | `connect_to_verba` | `ConnectPayload`；返回 `connected/error/rag_config/user_config/theme/themes` |
| `POST` | `/api/get_rag_config` | `retrieve_rag_config` | `Credentials`；返回 `rag_config/error` |
| `POST` | `/api/set_rag_config` | `update_rag_config` | `SetRAGConfigPayload`；返回状态 |
| `POST` | `/api/get_user_config` | `retrieve_user_config` | `Credentials`；返回 `user_config/error` |
| `POST` | `/api/set_user_config` | `update_user_config` | `SetUserConfigPayload`；返回状态 |
| `POST` | `/api/get_theme_config` | `retrieve_theme_config` | `Credentials`；返回 `theme/themes/error` |
| `POST` | `/api/set_theme_config` | `update_theme_config` | `SetThemeConfigPayload`；返回状态 |
| `POST` | `/api/query` | `query` | `QueryPayload`；返回 `error/documents/context` |

### 7.3 文档、块、向量和建议

| 方法 | 路由 | 处理函数 | 结果摘要 |
|---|---|---|---|
| `POST` | `/api/get_document` | `get_document` | 单文档元信息 |
| `POST` | `/api/get_datacount` | `get_document_count` | `datacount` |
| `POST` | `/api/get_labels` | `get_labels` | `labels` |
| `POST` | `/api/get_content` | `get_content` | `content/maxPage/error`，支持检索命中上下文窗口 |
| `POST` | `/api/get_vectors` | `get_vectors` | `vector_groups`，可对所有 embedding 做 PCA |
| `POST` | `/api/get_chunks` | `get_chunks` | 分页 `chunks` |
| `POST` | `/api/get_chunk` | `get_chunk` | 单 chunk |
| `POST` | `/api/get_all_documents` | `get_all_documents` | 分页、BM25/标题排序文档和标签 |
| `POST` | `/api/delete_document` | `delete_document` | 删除文档及对应 embedding chunks |
| `POST` | `/api/get_suggestions` | `get_suggestions` | BM25 建议列表 |
| `POST` | `/api/get_all_suggestions` | `get_all_suggestions` | 分页建议和总数 |
| `POST` | `/api/delete_suggestion` | `delete_suggestion` | 删除单条建议 |

### 7.4 管理与双 WebSocket

| 类型 | 路由 | 契约 |
|---|---|---|
| WebSocket | `/ws/import_files` | 接收 `DataBatchPayload`；服务端返回 `StatusReport` 或 `CreateNewDocument`；按 `FileStatus` 推送进度 |
| WebSocket | `/ws/generate_stream` | 接收 `GeneratePayload`；逐条发送 `{message, finish_reason}`，停止时附加 `full_text` |
| `POST` | `/api/reset` | `ResetPayload.resetMode`：`ALL`、`DOCUMENTS`、`CONFIG`、`SUGGESTIONS`；`Demo` 模式不执行删除 |
| `POST` | `/api/get_meta` | 返回 Weaviate 节点与集合统计 |

## 8. 技术栈、依赖和运行入口

### 8.1 后端

- Python `3.10-3.12`、FastAPI `0.111.1`、Uvicorn `0.29.0`、Gunicorn `22.0.0`、Click `8.1.7`。
- Weaviate：`weaviate-client==4.9.6`；支持 Embedded、Docker、Cloud、Custom 四种部署。
- 文档解析：`pypdf`、`python-docx`、`openpyxl`、`xlrd`、`spacy`、`beautifulsoup4`、`markdownify`、`assemblyai`、Unstructured、Firecrawl、Upstage。
- RAG/文本：`langchain-text-splitters`、`tiktoken`、`langdetect`、`scikit-learn`、`wasabi`。
- HTTP/并发：`aiohttp`、`requests`、`httpx`、`aiofiles`、`asyncio`。

### 8.2 前端

Next.js `^14.2.25`、React `^18.3.1`、TypeScript `5.1.6`、TailwindCSS `3.3.3`、DaisyUI `^4.10.1`、Three.js `^0.166.1`、React Three Fiber、MDX、`react-markdown`、`react-window`、`react-virtuoso`、`framer-motion`。

`frontend/package.json` 的关键脚本：

- `npm run dev`：Next 开发服务。
- `npm run build`：`next build` 后把 `out/*` 复制到 `../goldenverba/server/frontend/out/`，再删除 `out`。
- `npm run start`：Next 生产服务，`0.0.0.0:8080`。
- `npm run lint`：`next lint`。

### 8.3 启动和容器

- CLI 入口：`verba=goldenverba.server.cli:cli`。
- `verba start --port 8000 --host localhost --workers 4 --prod/--no-prod` 调用 `uvicorn.run("goldenverba.server.api:app", ...)`。
- `verba reset` 可重置三类配置，或 `--full_reset` 删除所有 `VERBA` 集合。
- `Dockerfile` 基于 `python:3.11`，执行 `pip install '.'`，暴露 `8000`，运行 `verba start --port 8000 --host 0.0.0.0`。
- `docker-compose.yml`：`verba:8000` + `weaviate:8080`，Weaviate 镜像 `semitechnologies/weaviate:1.25.10`，卷 `weaviate_data`，健康检查后启动 Verba；Ollama 服务默认注释。

## 9. 环境变量与外部系统

主要配置：

- Weaviate：`WEAVIATE_URL_VERBA`、`WEAVIATE_API_KEY_VERBA`、`DEFAULT_DEPLOYMENT`。
- OpenAI：`OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL`、`OPENAI_EMBED_API_KEY`、`OPENAI_EMBED_BASE_URL`、`OPENAI_EMBED_MODEL`、`OPENAI_CUSTOM_EMBED`。
- 本地模型：`OLLAMA_URL`、`OLLAMA_MODEL`、`OLLAMA_EMBED_MODEL`。
- 其他模型：`ANTHROPIC_API_KEY`、`COHERE_API_KEY`、`GROQ_API_KEY`、`NOVITA_API_KEY`、`UPSTAGE_API_KEY`、`UPSTAGE_BASE_URL`、`VOYAGE_API_KEY`、`EMBEDDING_SERVICE_URL`、`EMBEDDING_SERVICE_KEY`。
- 数据读取：`UNSTRUCTURED_API_KEY`、`UNSTRUCTURED_API_URL`、`ASSEMBLYAI_API_KEY`、`GITHUB_TOKEN`、`GITLAB_TOKEN`、`FIRECRAWL_API_KEY`。
- 运行行为：`VERBA_PRODUCTION`、`VERBA_GOOGLE_TAG`、`SYSYEM_MESSAGE_PROMPT`。

风险边界：多个组件构造函数会在 `VerbaManager` 初始化期间请求模型列表（如 `OpenAIGenerator.get_models()`、部分 embedder/generator），因此无 API key 或网络不可用时虽然多数实现回退默认模型，但初始化仍可能输出告警或依赖本地库探测。架构建档未安装依赖、未启动服务、未访问外部模型服务。

## 10. 测试与验证现状

仓库贡献文档指定：

```bash
pytest goldenverba/tests
```

当前测试文件：

- `goldenverba/tests/document/test_document.py`：初始化、JSON 往返、`FileConfig` 创建占位、超大内容、非法 JSON、特殊字符、阿拉伯语。
- `goldenverba/tests/chunk/test_chunk.py`：`Chunk.to_json()` / `Chunk.from_json()` 往返及字段保留。

测试成熟度限制：`TECHNICAL.md` 的 Automated Testing 仍为 `TODO`；`test_create_document_from_file_config()` 只有 `assert True`；没有看到覆盖 FastAPI 路由、WebSocket、Weaviate CRUD、导入编排、连接缓存、组件 Manager、检索质量、LLM 流式错误和容器部署的测试。因此测试只能证明少量数据对象行为，不能证明端到端可用性。

当前核对按任务约束未安装依赖、未启动服务、未构建前端或 Docker；仅读取测试源码、依赖和入口。不得将未执行的集成测试描述为通过。

## 11. 版本新鲜度

已读取本地 Git 状态并通过独立代理出口 `http://127.0.0.1:4780` 查询远程引用：

- 本地分支：`main`
- 本地提交：`70b6cfb8ef59c9f178ffccfaf3aadcf737757a18`
- 远程 `origin/main`：`70b6cfb8ef59c9f178ffccfaf3aadcf737757a18`
- 本地与远程：同一提交，无落后提交，无需建立独立最新源码快照
- 本地原有未跟踪文件：`细探-Verba.md`
- 当前核对新增文件：`ARCHITECTURE.md`

由于远程与本地提交一致，未执行 fetch、pull 或 worktree 操作；没有改动源码、依赖、测试、配置或既有细探文件。

## 12. 风险、限制与未确认项

1. **项目生命周期风险（高）**：README 已声明 archived/discontinued，无安全修复和兼容性承诺；不得作为生产底座直接引入。
2. **单用户边界**：README 明确设计为 single-user；没有多用户或 RBAC，`ClientManager` 的缓存键也只围绕连接凭证，不是租户隔离。
3. **安全边界**：`docker-compose.yml` 开启 Weaviate anonymous access；API 的 CORS 配置宽松，主要依赖 Origin 中间件；生产部署必须重新审计认证、授权、网络和密钥暴露。
4. **集成测试缺口**：API、WebSocket、Weaviate、外部 LLM/Reader 和前端构建没有有效自动化覆盖。
5. **数据一致性边界**：文档和 chunks 分属不同集合，导入中途异常主要依赖手工补偿；虽然存在 chunk 数量校验和删除补偿，但没有事务跨集合保证。
6. **模型维度风险**：README 警告不要用不同 Ollama embedding model 混合导入，否则向量维度可能不一致；embedding 集合按模型名分隔，但旧数据迁移/模型配置变更仍需人工审查。
7. **配置校验脆弱**：`VerbaManager.verify_config()` 按字典迭代顺序和配置键顺序比较结构，组件元数据变化可能触发重建；配置数据依赖固定 UUID 和 JSON 字符串。
8. **外部依赖风险**：Reader 和 Generator 直接依赖多家外部 API；网络、token、库缺失和第三方协议变化可能在启动或请求期间失败。
9. **异常处理不统一**：部分 API 返回空列表/空对象并隐藏异常，部分 WebSocket 异常直接把异常对象放入 JSON；调用方不能只凭 HTTP 200 判断业务成功。
10. **前后端版本漂移**：`setup.py`、`frontend/package.json`、页面显示版本和 README 图片/链接版本不完全一致，不能把单一版本字符串视作可靠发布标识。
11. **文档不完整**：`TECHNICAL.md` 明确存在 `ClientManager`、`BatchManager`、WebSocket、测试等 TODO；本架构文档以源码为准补全，但没有替代缺失的正式开发维护文档。
12. **当前未确认项**：未执行依赖安装、pytest、前端 `npm run build`、Docker Compose、Weaviate 实例连接和任何外部 LLM/Reader API；这些行为需要独立环境和明确凭证，不能由当前核对静态建档推断。

## 13. 架构结论与参考价值

### 13.1 结论

Verba 的核心价值是一个结构清晰、可视化完整的 RAG 应用样例：以 `VerbaManager` 编排五类可插拔组件，以 `WeaviateManager` 把文档、embedding chunks、配置和建议分集合持久化，以 `WindowRetriever` 实现基于 Weaviate hybrid search 的窗口检索，并用 FastAPI HTTP/WebSocket 将导入、查询、流式生成和可视化能力连接到 Next.js 前端。

它不是可直接继承的生产框架：项目已归档；认证、多租户、事务、错误契约、测试、依赖新鲜度和安全维护均不足。对支持库/平台的可吸收范围仅限于：

- `Reader`/`Chunker`/`Embedding`/`Retriever`/`Generator` 的边界契约和元数据驱动选择模型。
- `Document`/`Chunk` 的文档—块—向量三层数据形状。
- 导入状态事件 `FileStatus` 与 WebSocket 进度报告的交互模式。
- Weaviate 文档集合与按 embedding 模型分集合的隔离思路。
- `WindowRetriever` 的混合检索、过滤、分数聚合和上下文窗口模式。

### 13.2 选型裁决

- **底座裁决：废弃直接选型。** 原因是上游 archived/discontinued，无安全补丁、无维护、无多用户边界，且端到端测试和技术文档不完整。
- **参考裁决：可作历史参考。** 仅提取组件边界、数据契约、RAG 数据流和 Weaviate 集合组织方式；不复制其旧依赖、认证模型、直接外部 I/O、异常处理或生产部署配置。
- **后续状态：待进一步核验，未启动任何实现。** 若需复用，应先独立验证当前 Weaviate client、FastAPI、模型提供者 API 和前端构建链的兼容性，并重新设计认证、租户隔离、事务补偿、测试和供应链安全。

## 14. 旧细探逐条吸收与裁决

旧细探 `细探-Verba.md` 已完整读取；它不是新的事实源，以下是逐条对照当前源码后的收口结果。旧文件按要求保留、不删除、不改写；后续若事实变化，只维护本 `ARCHITECTURE.md`。

| 旧细探结论 | 当前源码对照 | 吸收/修正裁决 |
|---|---|---|
| Verba 是 Weaviate RAG 文档问答框架 | `README.md:50-52`、`goldenverba/server/api.py:423-441`、`goldenverba/verba_manager.py:705-747` | **吸收**；精确定义为应用型端到端 RAG，不是通用多租户框架。 |
| 入库→分块→向量化→Weaviate→混合检索→生成 | `verba_manager.py:125-171,183-271,705-747`、`managers.py:397-449,764-814`、`WindowRetriever.py:65-204` | **吸收并补全**：入库还包含 Reader、状态事件、文档/块双集合补偿；查询和生成是两个 HTTP/WebSocket 阶段，不是单个同步请求。 |
| “Weaviate 向量化” | `managers.py:104-158,1061-1175` | **修正**：Weaviate 是持久化/查询后端；向量可由 `Ollama`、`SentenceTransformers`、`OpenAI`、`Cohere`、`VoyageAI`、`Upstage` 或 `Weaviate` embedder 生成。 |
| RAG 问答提示词 | `interfaces.py:148-199`、`OpenAIGenerator.py:52-125` | **吸收并补全**：system prompt 约束上下文回答，conversation 追加到 messages；`SYSYEM_MESSAGE_PROMPT` 拼写错误是实际环境变量契约。 |
| 已归档、无安全补丁、不建议生产选型 | `README.md:3-10,19` | **吸收**；这是生命周期和供应链裁决，不等于当前代码每条路径都不可运行。 |
| 旁路线索为 Weaviate | `managers.py:164-270`、`docker-compose.yml:35-65` | **吸收并补全**：还存在 FastAPI、Next.js、spaCy、scikit-learn、外部 Reader/Embedding/Generator API；Docker Compose 的 Weaviate 开启匿名访问。 |

## 15. 契约表：入口、边界、失败与资源责任

下表只记录源码实际暴露的契约。代码没有统一 request id、幂等键、取消 token 或重试策略时，明确写“未实现”，不以 HTTP 200、日志或状态事件冒充成功。

| 入口/能力 | 输入与输出契约 | 错误/超时/取消 | 幂等与资源责任 | 证据 |
|---|---|---|---|---|
| `POST /api/connect` | `ConnectPayload(credentials, port)`；返回 `connected`、配置和主题；异常返回 HTTP 400 与 `connected=false` | Weaviate 初始化 `Timeout(init=60, query=300, insert=300)`；连接异常被转成字符串；无应用层重试/取消 | 凭证哈希缓存复用；连接由 `ClientManager` 持有，应用 lifespan 退出时关闭 | `server/api.py:161-197`；`components/managers.py:173-270`；`verba_manager.py:750-827` |
| `GET /api/health` | 返回存活标记、部署信息和默认部署；Local 模式会读取部署环境变量 | 会先 `clean_up()`，其中 `is_ready()` 异常可使健康检查失败；无超时/重试契约 | 健康检查可能关闭过期/不 ready client；不是纯只读探针 | `server/api.py:139-157`；`verba_manager.py:808-827` |
| `POST /api/query` | `QueryPayload(query, RAG, labels, documentFilter, credentials)`；返回 `error/documents/context` | 异常返回 HTTP 200 形状的错误 JSON；向量/Weaviate timeout 继承客户端 300 秒；无取消/重试 | 每次查询先写 `VERBA_SUGGESTIONS`；没有请求幂等键，重复查询的建议去重是查询后读再写，存在竞态 | `server/api.py:423-441`；`verba_manager.py:705-732`；`managers.py:836-854` |
| `WS /ws/import_files` | 多条 `DataBatchPayload`；收齐后 `FileConfig.model_validate_json()`；服务端发送 `StatusReport`/`CreateNewDocument` | Pydantic/业务异常记录后断开；客户端断开只跳出；无恢复游标、取消传播、超时控制 | `BatchManager` 按 `fileID` 聚合并在完成或 `isLastChunk` 时删除；导入任务在当前 WebSocket 协程内等待 | `server/api.py:238-265`；`server/helpers.py:44-79`；`server/types.py:41-48,138-152` |
| `WS /ws/generate_stream` | `GeneratePayload`；逐条 `{message, finish_reason}`，收到 `stop` 时补 `full_text` | `WebSocketDisconnect` 退出；其他异常尝试把异常对象直接放进 JSON；OpenAI `httpx` 使用 `timeout=None`；无服务端 cancel/上限 | async generator 和 `httpx.AsyncClient` 的上下文负责正常释放；断线后的上游生成没有显式 `aclose`/取消保证 | `server/api.py:203-235`；`components/generation/OpenAIGenerator.py:52-103` |
| `POST /api/delete_document` | `GetDocumentPayload(uuid, credentials)`；成功/不存在均可能 HTTP 200 空对象 | 失败 HTTP 400 空对象；无重试/幂等声明 | 删除文档后按 `meta` 找 embedder，再删除其块；跨集合非事务 | `server/api.py:663-679`；`managers.py:469-489` |
| `POST /api/reset` | `ResetPayload.resetMode`：`ALL/DOCUMENTS/CONFIG/SUGGESTIONS`；成功 HTTP 200 空对象 | 未识别 mode 也不报参数错误；异常 HTTP 500 空对象；无确认/取消 | 破坏性操作可重复调用但没有幂等回执；`ALL` 按名称删除所有含 `VERBA` 集合 | `server/api.py:684-706`；`managers.py:491-507` |
| `POST /api/set_*_config` | RAG/User/Theme 配置分别写固定 UUID；成功 JSON status | Demo 模式伪成功返回字符串 `"200"`；普通异常多为 HTTP 200 + status 400；无版本/并发控制 | `set_config` 采用“存在则删后插入”，中断可能造成配置缺失；没有事务/版本号 | `server/api.py:291-417`；`managers.py:367-393` |

## 16. 真实对接调用链（函数级）

### 16.1 连接与配置链

```text
HTTP ConnectPayload
  → server.api.connect_to_verba()
  → ClientManager.connect()
  → credentials SHA-256 + per-credential asyncio.Lock
  → VerbaManager.connect()
  → WeaviateManager.connect()
  → use_async_with_*() / client.connect() / client.is_ready()
  → verify_collection(VERBA_CONFIGURATION)
  → load_rag_config/load_user_config/load_theme_config()
  → WeaviateManager.get_config()/set_config()
  → JSON response
```

关键事实：模块导入时 `server/api.py:55-57` 创建全局 `VerbaManager` 与 `ClientManager`；而 `ClientManager.__init__` 又创建第二个 `VerbaManager`（`verba_manager.py:750-755`）。这会重复初始化组件并重复执行库/环境探测，也使“全局 manager”和“ClientManager.manager”不是同一实例；不能把它描述成单例。

### 16.2 文件导入链

```text
frontend/app/components/Ingestion/*
  → DataBatchPayload（分片 JSON）
  → websocket_import_files()
  → BatchManager.add_batch()/check_batch()
  → FileConfig.model_validate_json()
  → ClientManager.connect()
  → VerbaManager.import_document()
  → exist_document_name()/delete_document()（重复/覆盖策略）
  → ReaderManager.load() → Reader.load() → list[Document]
  → asyncio.gather(process_single_document(...), return_exceptions=True)
  → ChunkerManager.chunk() → Chunker.chunk()
  → EmbeddingManager.vectorize() → batch_vectorize() → Embedding.vectorize()
  → WeaviateManager.import_document()
  → insert VERBA_DOCUMENTS → insert_many VERBA_Embedding_<model>
  → aggregate count 校验 → 失败补偿 delete_document()
  → LoggerManager.send_report() → DONE/ERROR
```

`asyncio.gather(..., return_exceptions=True)` 允许多文档 URL 部分成功；但 `import_document()` 在一个或多个成功时仍会发送整体 `DONE`，所以“有 DONE”不等于所有子文档成功。单文档失败时，内部发送 `ERROR` 后外层仍可能再次发送 `ERROR`，状态协议没有唯一终态保证。

### 16.3 查询—回答链

```text
POST /api/query
  → ClientManager.connect()
  → VerbaManager.retrieve_chunks()
  → add_suggestion()
  → EmbeddingManager.vectorize_query()
  → RetrieverManager.retrieve()
  → WindowRetriever.retrieve()
  → WeaviateManager.hybrid_chunks(alpha=.5, filters)
  → get_document() / get_chunk_by_ids()
  → score 归一化、窗口补块、按文档分数排序
  → documents + combine_context()
  → 前端 WS /ws/generate_stream
  → GeneratorManager.generate_stream()
  → ProviderGenerator.generate_stream()
  → SSE `data:` lines → message chunks → `[DONE]`
  → websocket handler 拼接 `full_text`
```

查询链的实际持久化副作用是 `add_suggestion()`；检索不是纯读操作。生成链只接收前端再次提交的 `rag_config/query/context/conversation`，后端没有把 `/api/query` 的结果绑定到后续 WebSocket，也没有服务端会话或上下文完整性校验。

## 17. 关键节点明细

| 节点 | 前置条件 | 状态/读写 | 并发模型 | 失败分支与恢复 | 证据 |
|---|---|---|---|---|---|
| `BatchManager.add_batch` | `fileID`、`total`、`order` 合法且分片 JSON 可拼接 | 内存 `batches[fileID].chunks[order]` 覆盖同序号；收齐后删除 | 每个 WebSocket 一个实例；无全局锁，单连接内串行 | `isLastChunk` 会无论是否收齐都删除；异常只日志且隐式返回 `None`，无重传协议 | `server/helpers.py:44-79` |
| `ClientManager.connect` | 凭证 deployment 合法；Weaviate 可连接且 ready | 读写 `clients`、`locks`；首次创建连接，记录 `datetime` | 同一凭证串行，凭证之间可并行；缓存时间戳不会在复用时刷新 | 连接失败向上抛；没有清理失败 client 的统一 finally | `verba_manager.py:771-801` |
| `WeaviateManager.verify_collection` | client 可用 | 查询集合存在性，缺失时创建 | 调用方自行并发，创建无分布式幂等门 | 创建失败向上抛；并发创建竞态未处理 | `components/managers.py:307-320` |
| `VerbaManager.import_document` | FileConfig/RAG 选择存在，client ready | 读文档名；驱动 `Document/Chunk` 内存流水线和报告；写 Weaviate | URL 文档用 `gather` 并行；单文档 chunk/embed/ingest 串行 | 重复拒绝或先删；子任务异常收集；全失败抛出后发送 ERROR；部分成功仍可 DONE | `verba_manager.py:97-181` |
| `WeaviateManager.import_document` | Document 已有 chunks/vector/meta，embedder 集合可建 | 先写文档，再写 chunks/vector，再计数校验 | 同一 client 无事务锁 | chunk 批量部分失败或计数不符时删除文档及按记录到的 chunk UUID；跨集合补偿非原子 | `components/managers.py:397-449` |
| `WindowRetriever.retrieve` | query vector、embedder、RAG config 合法 | 读 embedding/document 集合；构造 documents/context | 单请求顺序读取；多个请求由 ASGI 并发 | 无命中返回空文档；缺文档跳过；分数最大最小相等时 `normalize_value` 除零；未知 search mode 可能导致 `chunks` 未赋值 | `WindowRetriever.py:46-204` |
| `websocket_generate_stream` | WebSocket 已 accept，payload JSON 可验证 | 读取消息、消费 async generator、发送每个片段 | 单 socket 循环；上游 provider 无请求级超时 | 客户端断开退出；其他异常尝试发送异常对象，发送失败会覆盖原异常 | `server/api.py:203-235` |

## 18. 资源生命周期与终态矩阵

| 资源 | 创建/持有 | 正常释放 | 业务失败 | 超时/主动取消 | 宿主/进程崩溃与残留风险 |
|---|---|---|---|---|---|
| `WeaviateAsyncClient` | `WeaviateManager.connect()` 创建，`ClientManager.clients` 持有 | lifespan `client_manager.disconnect()`；健康检查也会淘汰过期/not-ready | `connect()` 前失败无 client；已写数据依赖导入补偿 | Weaviate SDK timeout 有 60/300 秒；未见取消回调或 shield/finally | 进程崩溃不会执行 `close()`；Embedded/HTTP 会话由 SDK/宿主回收，无法从源码证明即时清理 |
| `asyncio.Lock` 与缓存字典 | `get_or_create_lock()` 按凭证创建；锁字典永久保留 | 无删除 lock 的路径；client 删除不删除 lock | 锁上下文退出会释放锁 | Task cancellation 通常由 async context 释放锁，但源码没有专门测试 | 进程退出由宿主处理；凭证哈希而非明文进入日志，但缓存 client 生命周期可能跨业务请求 |
| WebSocket | endpoint accept；`LoggerManager` 持有 socket | `WebSocketDisconnect` 分支 break；框架负责连接 | import 异常 break；generate 异常尝试发错误帧 | 无 `asyncio.timeout`、取消消息或上游主动关闭逻辑 | 客户端/进程崩溃时没有应用层清理、未完成批次/上游流可能残留 |
| 导入内存（Batch/Document/Chunk/tasks） | BatchManager 收分片；`gather/create_task` 建任务 | `batches[fileID]` 完成或 `isLastChunk` 删除；任务正常返回 | `gather` 收集异常；未见 finally 清空大对象或取消兄弟任务 | 取消传播未显式设计；`isLastChunk` 过早可丢批次 | 进程崩溃丢失内存批次，磁盘已写文档/块可能留下孤儿或半成品 |
| `httpx.AsyncClient`/SSE response | provider `async with` 创建/持有 | `async with` 正常退出关闭 | JSON/SSE 解析或 HTTP 异常离开上下文 | OpenAI 生成 `timeout=None`；socket 断开未见显式 `aclose`/cancel | 宿主回收连接；无应用层 provider 流追踪、重放或残留检查 |
| Weaviate 文档/块/配置 | 集合由 `verify_collection` 懒创建；对象按 API 写入 | 删除 API 或 reset；配置“删后插入” | 导入失败执行跨集合补偿；配置插入失败可能已删除旧配置 | SDK 超时可能发生在文档写入与块写入之间；无事务 | 崩溃可能留下文档—块不一致、配置空洞、孤儿块；源码没有启动恢复扫描 |
| PCA/向量内存 | EmbeddingManager 为每个文档构造 embeddings/PCA 列表 | 函数返回后由 Python GC | 向量数量不匹配时抛错；没有持久化前的 schema/维度门 | 无大小/耗时上限；取消只依赖 asyncio 默认语义 | 大文档和大批量可能造成内存压力；无峰值监控或恢复证明 |

## 19. 失败、超时、取消、崩溃与一致性矩阵

| 场景 | 源码行为 | 可证明结论 | 未证明/风险 |
|---|---|---|---|
| 非法 deployment/payload | Pydantic 对 `Credentials.deployment` 限定四值；路由层未统一处理验证错误 | 类型边界部分存在 | FastAPI validation error、错误格式和前端兼容性未测；部分数值/字符串没有范围约束 |
| 空 query/空文档 | `add_suggestion` 仍可写空 query；hybrid 结果为空返回固定英文句 | 有显式空命中结果 | 空字符串、超长 query、空 chunks 的端到端行为未测 |
| 缺 provider API key/库 | `VerbaComponent.check_available` 标记 metadata；多个 generator 构造函数初始化时取模型列表并回退默认 | 可用性信息可展示，部分初始化有 fallback | 选中 unavailable 组件的请求错误契约未统一；某些库导入异常在模块导入阶段发生 |
| Weaviate 连接断线/not-ready | `ClientManager.clean_up` 在健康检查中调用 `is_ready` 并关闭 client | 过期/not-ready client 有清理路径 | `is_ready` 自身异常、并发请求使用被淘汰 client、重连退避未测 |
| 导入中第三方/Reader失败 | `process_single_document` 发 ERROR 并抛；外层 `gather(return_exceptions=True)` 汇总 | 单文档异常不会直接中止其他 URL 文档 | 部分成功整体 DONE、重复 ERROR、未完成兄弟任务取消和孤儿数据未验证 |
| chunk 批量写入部分失败 | 检查 `has_errors`；记录 UUID 后调用 `delete_document` | 有最佳努力补偿 | delete_many/删除文档失败时的二次补偿、跨集合原子性和重启修复未实现 |
| query/LLM provider 超时 | Weaviate query 300 秒；OpenAI stream `timeout=None` | SDK 级 Weaviate timeout 存在 | provider 可能无限等待；HTTP 错误码、非 SSE 行、`[DONE]` 前断流和重试未统一 |
| 主动取消/客户端断线 | WebSocketDisconnect 仅 break；无取消 token/任务表 | 断线可退出 WebSocket 循环 | 上游生成/导入任务是否取消、连接/批次/临时数据是否清除均未证明 |
| 进程崩溃/重启 | 没有持久化 job 状态、启动恢复扫描或 orphan reconciliation | 仅能依赖 Weaviate 持久化数据和宿主重启 | 未完成状态可能停留在 STARTING/INGESTING；文档与块不一致需要人工处理 |
| 重复提交/重复事件 | `fileID` 分片同 order 覆盖；同名文档按 overwrite 决策；建议写入做先查后写 | 有局部去重 | 没有幂等键、版本号或唯一约束保证竞态下只执行一次 |

## 20. 防假绿验证分级（L0-L4）

| 等级 | 证明目标 | 本仓库证据 | 当前结论 |
|---|---|---|---|
| L0 源码存在 | 路由、管理器、组件、模型和测试文件真实存在 | 本文引用的 `server/`、`components/`、`tests/` 文件已读取 | **通过（静态存在）**；不等于可运行 |
| L1 静态契约 | Python 可解析、导入边界/路由/模型形状能对齐 | 当前核对只做源码阅读和 Markdown 校验；未安装依赖，未把 import 成功当作证明 | **部分**；尚未执行完整静态检查，不能声称包导入通过 |
| L2 单元测试 | 数据对象行为在隔离测试中通过 | 测试文件只有 Document/Chunk；其中 `test_create_document_from_file_config` 是 `assert True` | **存在但未执行**；即使执行也只覆盖窄面 |
| L3 集成测试 | FastAPI、WebSocket、Weaviate CRUD、导入/检索/生成链连通 | 仓库没有对应覆盖；当前核对未启动 Weaviate、未跑服务 | **未验证** |
| L4 外部真实链路 | 真实 provider、模型、网络、容器部署、断线/恢复和资源清理 | 当前核对未使用凭证、未调用外部 API、未启动 Docker/Weaviate | **未验证** |

严格口径：源码中有 `return`、日志显示 `DONE`、历史构建物存在、README 标记 implemented、子模块单测通过，都不能升级为 L3/L4。当前唯一可写入的验证事实是静态源码证据与后文新鲜的文档检查；任何运行级结论必须另行执行并记录退出码、测试数、依赖和清理结果。

## 21. 未验证项、吸收与不吸收裁决

### 21.1 吸收（仅作为边界模式，不复制实现）

- **吸收**：五类 `VerbaComponent` 的元数据驱动选择和 `available` 展示；可映射为统一能力注册/能力契约，但必须补版本、权限、错误、超时和取消字段。
- **吸收**：`Document`—`Chunk`—`vector` 数据分层，以及 embedding 模型隔离集合的思路；复用前必须增加维度、模型版本和迁移约束。
- **吸收**：导入状态阶段和检索上下文窗口模式；复用前必须定义状态机、单一终态、job id、幂等键和断线恢复。
- **吸收**：Weaviate hybrid search 的 `alpha=.5`、标签/文档过滤、分数聚合和窗口补块作为检索策略样例；不吸收当前归一化算法的除零风险。

### 21.2 不吸收/废弃

- **废弃**：把 archived Verba 直接作为生产底座、依赖其无维护的版本和安全边界。
- **不吸收**：`allow_origins=["*"]` 加自定义 Origin 检查的安全模型；生产认证、授权、租户隔离和密钥治理必须另建契约。
- **不吸收**：`set_config` 的删后插入、文档/块跨集合最佳努力回滚、无 job 状态的导入编排；它们不能作为事务或一致性模板。
- **不吸收**：OpenAI `timeout=None`、异常对象直接 `send_json`、HTTP 200 携带业务失败、Demo 模式伪成功、未识别 reset mode 静默成功。
- **不吸收**：直接在组件构造期间访问外部 provider `/models`；应改为显式、可超时、可观测的 provider 探测阶段。

### 21.3 待核

- Weaviate client `4.9.6` 与当前 Weaviate 服务/集合 API 的兼容性。
- 各 Reader、Embedder、Generator 的真实外部协议、错误码、速率限制、流式终止和取消语义。
- 前端当前分片顺序、断线重传、`DONE/ERROR` 状态消费和生成 WebSocket 的重连行为。
- Docker Compose 在真实环境中的匿名访问、健康检查、卷恢复和跨容器 Ollama 网络。
- 高并发、多请求共享 `ClientManager`、锁/缓存淘汰以及跨集合补偿失败后的数据修复。
- 全部测试、前端构建、Docker/Weaviate 集成、外部模型调用和崩溃恢复；这些均未由当前核对静态研究证明。

## 22. 当前核对证据与专属 MCP 状态

- **目标项目根**：`/Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/65_rag_frameworks/Verba`
- **专属 MCP 实例**：`project_toolkit`（用户指定名称为 `system_engineering_toolkit`；当前工具返回的 MCP 实例字段为 `project_toolkit`，按返回值如实记录）。
- **`project_context`**：已作为开工第一调用执行，但错误绑定到 `/Users/hekunhua/Documents/Agent/PHP/华世王镞_v3`，项目名为 `华世王镞_v3`，不是本任务的 Verba；其代码地图摘要为 2,055 files/36,605 nodes/93,082 edges，提交 `682fd41...`，不能作为 Verba 证据。
- **`codegraph_explore`**：随后按要求调用并明确传入 Verba 根目录；返回 `no .codegraph/ index exists`，且 MCP 元信息仍显示错误项目根 `/Users/hekunhua/Documents/Agent/PHP/华世王镞_v3`。结果为**不可用/错绑**，未绕过、未冒充代码图；本文全部代码事实改由当前源码逐文件读取取得。
- **Git 基线**：本地 `main`，`70b6cfb8ef59c9f178ffccfaf3aadcf737757a18`；工作树原有未跟踪 `细探-Verba.md`，当前核对只允许修改 `ARCHITECTURE.md`。

本文件是唯一正式架构事实源；`细探-Verba.md` 是保留的历史细探，不删除、不继续扩写。

## 23. 后续：通用底座映射与服务边界裁决

本节不是把 Verba 直接改造成平台组件，而是把当前源码中可验证的能力，映射到“组件支持库—检索模块—运行核心—统一网关”四个职责边界，明确哪些只是 Verba 产品层。所有“应归入”均为底座设计输入，不代表当前核对已经修改或实现系统工程平台。

### 23.1 映射原则与源码事实

源码的公共抽象在 `goldenverba/components/interfaces.py`：`VerbaComponent` 只提供 `name`、`requires_env`、`requires_library`、`description`、`config`、`type`、`get_meta()` 和 `check_available()`；`Reader`、`Chunker`、`Embedding`、`Retriever`、`Generator` 五个子类只规定异步方法签名，没有统一错误码、超时、取消、幂等、版本、权限或资源所有权字段。可用性判断是“环境变量 + Python 库是否存在”，不是运行时健康检查。

`goldenverba/components/managers.py:81-158` 在模块导入时建立全局组件实例列表，`ReaderManager`、`ChunkerManager`、`EmbeddingManager`、`RetrieverManager`、`GeneratorManager` 只按组件 `name` 建字典并转发调用；`VerbaManager` 又把这些 Manager 和 `WeaviateManager` 组合成产品流程。因而源码中的“Manager”不是一个单一通用层：它同时混有注册/选择、流程编排、状态上报、外部 I/O 和产品数据模型，必须拆开映射。

当前实现的六类能力边界如下：

| 源码能力 | 真实入口/职责 | 输入输出事实 | 后续归属判断 |
|---|---|---|---|
| `Reader` | `interfaces.py:57-72`；具体实现位于 `components/reader/` | `load(config, FileConfig) -> list[Document]`；`BasicReader` 从 base64 文件解码并支持文本/PDF/DOCX/CSV/Excel，`FirecrawlReader` 调外部 URL 服务并可能返回多个 `Document` | **组件支持库**的 Reader 契约 + Reader provider；文件格式解析和远端抓取是非 Agent 通用能力，业务导入编排不放进 Reader |
| `Chunker` | `interfaces.py:93-116`；`components/chunking/` | `chunk(config, documents, embedder, embedder_config) -> list[Document]`；部分语义分块可借用 `Embedding` | **组件支持库**的分块原子能力；按文档类型选择策略可由检索/导入模块编排，不能让 Chunker 直接管理任务状态 |
| `Embedding` | `interfaces.py:75-90`；`components/embedding/` | `vectorize(config, list[str]) -> list[list[float]]`，默认 `max_batch_size=128`；另有查询单文本向量化 | **组件支持库**的模型 provider；批量切分、维度/模型版本校验、重试和资源监督由运行核心/模型资源管理负责 |
| `Retriever` | `interfaces.py:119-145`；当前只有 `WindowRetriever` | 接受 client、query、vector、RAG config、`WeaviateManager`、labels、document UUID；返回 `documents, context`；实现 hybrid search、分数聚合、窗口补块 | **检索模块**；检索策略、过滤、排序、上下文窗口是领域流程，不应成为 Weaviate provider 的职责 |
| `Generator` | `interfaces.py:148-200`；`components/generation/` | `generate_stream(...)` 产生 `{message, finish_reason}`；`prepare_messages()` 组装 system/conversation/query/context | Provider 调用和统一流式结果属于**组件支持库**；RAG prompt、上下文长度和回答产品策略属于产品/应用模块，流任务监督属于运行核心 |
| `Manager` | `managers.py` 全文件；`verba_manager.py:37-827` | 五类 Manager 做注册转发；`WeaviateManager` 负责连接、集合、CRUD、hybrid 查询；`VerbaManager` 负责导入/检索/生成；`ClientManager` 缓存连接、锁和健康清理 | **拆分而非整体吸收**：注册表/能力选择归支持库目录；导入、任务、补偿、进度归运行核心；检索编排归检索模块；Weaviate 客户端归支持库；HTTP/WS 会话缓存归网关/运行核心资源服务；`VerbaManager` 本身是产品层编排门面 |

### 23.2 四层落点：支持库、检索模块、运行核心、网关

| 底座边界 | 可以吸收的 Verba 模式 | 必须留在边界外或重写的部分 | 证据 |
|---|---|---|---|
| **组件支持库** | `Document`/`Chunk` 的稳定数据形状；Reader/Chunker/Embedding/Generator provider 契约；能力元数据（环境变量、库、配置、available）；Weaviate 连接/集合/对象读写适配器；模型列表探测适配器 | 不吸收 `components/managers.py` 的全局实例列表、构造器联网、产品集合名、固定 UUID、直接向 WebSocket 发消息；provider 必须返回统一结果/错误，配置和凭证由调用方显式传入 | `interfaces.py:15-54`；`document.py:46-144`；`chunk.py:4-52`；`managers.py:164-449` |
| **检索模块** | 查询向量化→hybrid 查询→labels/document UUID 过滤→按 `doc_uuid` 聚合→分数排序→窗口补块→context 的策略链；`WindowRetriever` 可作为策略样例 | 不让策略直接持有裸 `WeaviateAsyncClient` 或任意 manager；不把建议写入、前端 DTO、模型凭证混入检索算法；修复分数全相等除零和未知 search mode 未赋值问题后才能作为候选实现 | `WindowRetriever.py:46-221`；`verba_manager.py:705-732` |
| **运行核心** | 导入 job、步骤状态、并发/批量 fan-out、超时/取消、跨集合补偿、重启恢复、资源预算和证据；模型/Weaviate client 的持有与回收；把六类能力串成一条可审计流水线 | 当前 `asyncio.create_task()` 后立即 `await` 不是可恢复任务系统；`gather(return_exceptions=True)` 不是可靠部分成功协议；源码没有 job 持久化、恢复扫描、取消 token 或唯一终态 | `verba_manager.py:97-271`；`managers.py:1128-1162`；`server/types.py:80-93` |
| **统一网关** | HTTP DTO 校验、Origin/认证边界、WS 接受/发送、将内部进度/生成事件编码为稳定 wire protocol；健康、连接、查询和配置路由作为产品 API 适配 | 网关不应直接编排 provider、持有业务事务或把 `WebSocket` 对象塞入领域 logger；`api.py` 当前直接使用全局 `manager`/`client_manager`，属于待拆分的产品实现，不是可复制的网关底座 | `server/api.py:55-133,203-265,423-441`；`server/helpers.py:12-41` |

### 23.3 `Manager` 的进一步拆解

1. **能力注册/选择器**：把 `managers.py:81-158` 的实例列表和 `VerbaManager.create_config():275-342` 的元数据序列化，改识别为“能力目录/组件支持库装配输入”。唯一键应为稳定能力 id + provider 版本，而不是只用显示名 `name`；`available` 只能是探测结果，不能代替调用时健康检查。
2. **导入编排器**：把 `VerbaManager.import_document()` 与 `process_single_document()` 的顺序保留为领域流程候选：重复检查→Reader→Chunker→Embedding→Weaviate ingest→补偿→终态；实际应由运行核心创建 job、分配 step id、保存进度和持久化失败证据。
3. **查询编排器**：`VerbaManager.retrieve_chunks()` 只保留“查询 embedding + 调检索策略”的模块门面；`add_suggestion()` 是产品副作用，不能隐藏在通用检索调用中。
4. **生成编排器**：`GeneratorManager.generate_stream()` 只做 provider 选择和结果转发；运行核心负责流任务取消/超时/背压，网关负责事件序列化，产品层决定 prompt 和 conversation 字段。
5. **数据服务适配器**：`WeaviateManager` 需要拆为通用 `VectorStore`/`DocumentStore` 适配器与 Verba schema service。前者只表达集合、对象、向量、过滤、聚合、删除、健康和事务能力；后者才知道 `VERBA_DOCUMENTS`、`VERBA_Embedding_<模型>`、`VERBA_CONFIGURATION`、`VERBA_SUGGESTIONS`。
6. **连接资源管理器**：`ClientManager` 的凭证哈希、按凭证锁、10 分钟淘汰和 `is_ready()` 清理可作为资源管理模式，但必须补 owner/job 关联、更新时间、关闭幂等、取消/崩溃回收和连接泄漏观测。当前复用 client 不刷新 `timestamp`，且 `disconnect()` 不删除缓存，不能原样吸收。

### 23.4 导入进度与 WebSocket 的通用化边界

源码的导入状态枚举在 `server/types.py:80-93`：`READY`、`CREATE_NEW`、`STARTING`、`LOADING`、`CHUNKING`、`EMBEDDING`、`INGESTING`、`DONE`、`ERROR`，另预留 `NER`、`EXTRACTION`、`SUMMARIZING`。`LoggerManager.send_report()` 在 `server/helpers.py:12-28` 把 `{fileID,status,message,took}` 直接发送到 socket；`BatchManager` 在 `helpers.py:44-79` 按 `fileID`、`total`、`order` 在内存拼接 JSON。

后续将其拆成三层契约：

```text
运行核心 Job/Step 状态
  → 统一事件账本（job_id、step_id、sequence、status、progress、message、took、error、terminal）
  → 网关 WS/SSE 适配器
  → 前端 Ingestion/Chat 消费
```

- **通用事件**：`job_id`、`file_id`、`step_id`、单调 `sequence`、阶段、已完成/总量（可未知）、耗时、错误码、可重试、终态标志。`READY…DONE/ERROR` 可作为兼容映射，但不能让字符串消息成为状态机。
- **当前缺口**：Reader、Chunker、Embedding、单文档和外层导入都会重复发送同一阶段；`process_single_document()` 发送 `DONE` 后外层 `import_document()` 还会发送 `INGESTING`/`DONE`；部分 URL 成功时整体仍可能 `DONE`。因此当前事件没有唯一终态、序号或父子任务汇总。
- **批量导入**：`BatchManager` 是 socket 进程内存态，没有持久化、重传窗口、checksum、过期清理或断线恢复；`isLastChunk` 即使未收齐也删除缓存。通用底座应让网关只接收分片，运行核心保存可恢复 upload session，按 `file_id + upload_id + order` 幂等接收并在完整校验后提交 job。
- **`/ws/import_files`**：网关只负责收包、校验、发送事件；不得在网关内 `create_task(manager.import_document())` 并等待产品 manager。导入 job 应可脱离 socket 继续运行，断线后由 `GET/WS events?after=sequence` 追赶。
- **`/ws/generate_stream`**：当前 `GeneratePayload` 由前端重新提交 `query/context/conversation/rag_config`，服务端没有把 `/api/query` 的结果绑定到生成会话；上游 `httpx.AsyncClient.stream()` 由 generator 自行打开。通用网关应使用 `generation_job_id`/上下文引用，逐事件发送 delta、finish、error、cancelled，并保证只出现一个终态。

### 23.5 Weaviate、模型资源与服务边界

#### 23.5.1 Weaviate 资源

`WeaviateManager.connect()` 根据 `Weaviate`、`Docker`、`Local`、`Custom` 选择 SDK 工厂，设置 `Timeout(init=60, query=300, insert=300)`，连接后 `is_ready()`；`ClientManager` 按 deployment/url/key 哈希缓存客户端。`docker-compose.yml:35-64` 又把 Weaviate 作为独立服务、持久卷 `weaviate_data`，并开启 `AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED: 'true'`。

底座映射：

- `weaviate-client`、连接工厂、健康探测、集合/对象/向量 API 是**支持库的受管 provider**；必须隐藏 SDK 类型，暴露统一 VectorStore/DocumentStore 契约。
- collection schema、`VERBA_*` 命名、固定配置 UUID、`meta` 中嵌套 RAG 配置、建议表和“按模型名清洗后拼集合名”是 **Verba 产品层**。通用底座只提供 namespace、schema 版本、tenant/index、模型指纹和迁移契约。
- 文档写入 `VERBA_DOCUMENTS`，chunk/vector 写入 `VERBA_Embedding_*`，源码在数量不一致时执行删除补偿；这不是跨集合事务。生产运行核心必须把“意图、写入对象、补偿状态、对账结果”落账，崩溃后扫描孤儿文档/chunk，而不是只依赖 `delete_document()`。
- anonymous access、直连 URL/API key、默认公网服务和产品 collection 名不应进入通用支持库；凭证应由网关/项目适配层注入，日志只出现脱敏引用。

#### 23.5.2 模型与 provider 资源

模型资源不是只有一个“模型名”字符串：它包含 provider、模型 id、embedding/generation 类型、维度/上下文窗口、端点、凭证引用、版本/环境指纹、并发预算和释放动作。

源码事实与边界：

- `OpenAIEmbedder.__init__()`、`OpenAIGenerator.__init__()` 会通过 `requests.get(<base_url>/models)` 获取模型列表；无 key 或异常时回退默认列表，但构造器仍可能联网。`OllamaEmbedder.__init__()` 调 `GET /api/tags`；`WeaviateEmbedder` 使用 `EMBEDDING_SERVICE_URL` 的 `/v1/embeddings/embed`。
- OpenAI embedding 的 `aiohttp` 请求显式 `timeout=30`，OpenAI generator 的 `httpx.AsyncClient.stream()` 使用 `timeout=None`；Weaviate embedding 的 `aiohttp` POST 未显式超时。模型探测、embedding、generation 的超时语义因此不一致。
- `EmbeddingManager.vectorize()` 按 `max_batch_size` 切批并用 `asyncio.gather(return_exceptions=True)`，随后核对向量数；PCA 只保存三维展示值，真实向量作为 Weaviate vector 写入。PCA 展示数据不能被当成检索向量或模型资源版本。

底座应分三条边界：

1. **模型目录/能力支持库**：登记 provider、模型、维度、上下文、协议和依赖；模型探测是显式可超时能力，不在 import/构造阶段隐式联网。
2. **模型运行资源管理**：持有 HTTP session、连接、批次、并发令牌、超时预算和 cancel handle；成功、失败、超时、取消、崩溃均释放；必要时 provider 隔离进程。
3. **产品配置与持久化**：选择哪个模型、保存哪个 `meta`、哪个 collection namespace、如何展示 PCA/模型列表，属于项目适配层/产品层；不得让模型 provider 直接写 Verba 配置集合。

### 23.6 非 Agent 通用部分与 Verba 产品层

| 分类 | 可作为非 Agent 通用底座输入 | 明确属于 Verba 产品层/不应泛化 |
|---|---|---|
| 数据 | `Document`、`Chunk`、来源、标签、chunk offset、vector、embedding model reference | `VERBA_DOCUMENTS`、`VERBA_Embedding_*`、固定三个 config UUID、Verba 专用 `meta` JSON |
| 能力 | Reader、Chunker、Embedding、Retriever、Generator 的 provider contract；文档→块→向量→检索→生成流水线 | `VerbaComponent.name` 显示名、当前默认组件列表、`VERBA_PRODUCTION` 分支和页面配置形状 |
| 检索 | hybrid search、过滤、分数聚合、窗口补块、上下文拼接 | `Advanced` 名称、`Suggestion` 自动补全写库、当前英文无命中文案、前端 documents 形状 |
| 运行 | job/step、事件、批量、超时、取消、补偿、资源生命周期和证据 | 单用户假设、按文件名重复判断、URL 子文档 fileID 拼接、Demo 模式伪成功 |
| 网关 | DTO 校验、HTTP/WS 事件、健康/连接/查询/生成 transport adapter | Next.js 页面、`Origin` 同源策略的具体产品实现、静态 `frontend/out`、端口和 CLI 名 `verba` |
| 模型/存储 | provider 适配、模型资源引用、向量库抽象、schema/namespace/维度契约 | OpenAI/Ollama/Firecrawl 等默认 URL 与环境变量名、Docker Compose 的 Weaviate anonymous access |
| Agent 边界 | **本项目没有 Agent 通用内核**；可吸收的只是 RAG pipeline 和流式生成能力 | 没有规划器、工具调用循环、长期记忆、任务委派、策略/权限决策或 Agent 状态机；不要把 `Generator` 误命名为 Agent |

### 23.7 唯一链路与禁止侧链

未来通用底座的唯一规范链路应为：

```text
项目产品层/前端
  → 统一网关（HTTP/WS DTO、认证、事件编码）
  → 运行核心（job、step、资源预算、状态账本、取消/超时/恢复）
  → 领域模块（导入模块 / 检索模块 / 生成模块）
  → 能力注册表（唯一能力 id、版本、契约 owner）
  → 组件支持库公开入口（Reader/Chunker/Embedding/VectorStore/Generator provider）
  → 受管外部资源（文件/URL、模型 API、Weaviate、Ollama、进程）
  → 统一结果/事件/证据/释放
```

检索的唯一子链为：

```text
网关查询请求
  → 运行核心创建 query job
  → 检索模块校验 query/filter/context policy
  → Embedding 支持能力（查询向量）
  → Retriever 策略
  → VectorStore 支持能力（Weaviate hybrid/过滤/取块）
  → 检索结果统一化（documents、scores、context、证据）
  → 网关返回
```

导入的唯一子链为：

```text
网关分片/文件引用
  → 运行核心 upload session + import job
  → Reader 支持能力
  → Chunker 支持能力
  → Embedding 支持能力
  → VectorStore/DocumentStore 提交
  → 一致性核对与补偿/恢复
  → 事件账本终态
  → 网关事件流
```

生成的唯一子链为：

```text
网关 generation job
  → 运行核心绑定 query/context 引用
  → 生成模块组装产品 prompt
  → Generator 支持能力
  → 受管模型流
  → 运行核心背压/取消/终态
  → 网关 delta/finish/error/cancelled
```

禁止从正式代码形成以下侧链：网关直接调用 `OpenAIEmbedder`/`WeaviateAsyncClient`；各 Manager 各自维护模型别名和错误翻译；Retriever 直接写 `VERBA_SUGGESTIONS`；Generator 直接持有 WebSocket；组件构造器隐式访问 `/models`；产品层绕过能力注册表调用 provider；为兼容旧 `name` 复制第二套 Manager。历史英文键或产品显示名若需兼容，只能在唯一能力入口归一化。

### 23.8 资源生命周期：正常、失败、超时/取消、崩溃

| 资源/所有权 | 创建与持有 | 正常完成 | 业务失败 | 超时/主动取消 | 宿主崩溃/恢复要求 |
|---|---|---|---|---|---|
| 上传分片/`BatchManager.batches` | 网关收到 `fileID/order`；当前只在内存 `dict` | 收齐、JSON 校验成功后转 job 并删除 session | JSON/Pydantic 错误应保留可诊断失败并清理过期分片；当前异常只日志 | 取消/TTL 到期释放分片和临时空间；当前没有 TTL/cancel | 进程死会丢分片；通用实现需持久 upload manifest 和启动恢复/清理 |
| 导入 job 与 `Document`/`Chunk` 内存 | 运行核心创建 job；Reader/Chunker/Embedding 返回对象 | 持久写入后释放大对象、关闭临时流 | 记录失败 step；取消未提交对象；避免兄弟任务悬挂 | 传播 cancel token，停止后续 step，排空已启动 provider；当前 `gather` 无显式兄弟取消 | 重启读取 job/写入意图，对文档—chunk 孤儿做对账；当前无 job 状态 |
| `WeaviateAsyncClient`/HTTP session | ClientManager 缓存；provider 内 `async with` 或 SDK 工厂持有 | job/session 引用归零后 `close()`；lifespan 最终关闭 | 创建失败立即释放部分 client；操作失败不复用已坏连接 | SDK/HTTP 超时后 cancel/close 或健康复检；当前仅部分 SDK timeout，provider 语义不一致 | 崩溃由宿主被动回收，不能证明及时 close；恢复时健康探测和孤儿连接清理 |
| 模型 provider 请求/批次 | Embedding/Generator provider 创建 session、流和并发令牌 | 读完 SSE/JSON，关闭 response/session，释放 token | HTTP/协议/维度/数量错误统一成 provider error，记录可重试 | embedding 30s、generation `timeout=None` 等现状不合格；需硬 deadline、取消上游、排空流 | provider 崩溃/解释器异常需隔离或重启、次数有界、写证据；禁止把模型资源留在全局对象 |
| Weaviate 文档与 chunks | DocumentStore 先写文档，VectorStore 批写 chunks | 核对对象数、记录 commit/索引引用 | 失败补偿删除并记录补偿结果；删除失败进入恢复队列 | 事务 deadline 到期进入 `PENDING_RECONCILE`，不能伪造 DONE | 依据持久意图扫描“仅文档/仅 chunk/重复 chunk”，幂等修复或人工隔离；当前仅最佳努力删除 |
| 连接锁/租约 | 当前按凭证 hash 创建 `asyncio.Lock`，字典永久保留 | 临界区退出释放锁、client 引用计数归零 | 获取/连接失败不得遗留锁或半初始化对象 | Task cancellation 必须 finally 释放租约；当前无专门测试 | 进程死按 lease owner/expiry 回收；内存锁本身不可恢复，不能当持久互斥 |
| WebSocket/事件订阅 | 网关 accept；当前 `LoggerManager` 持 socket | 发送唯一终态后关闭或保持订阅 | 发送失败转事件账本，不把异常对象直接 JSON 化 | 断开触发 job cancel 或明确“后台继续”；上游生成要 cancel/close | socket 崩溃不应丢 job；订阅重连按 sequence 补发；当前无重放 |

### 23.9 失败、超时、取消、崩溃矩阵（后续验收口径）

| 场景 | 当前源码行为 | 底座必须固定的契约 | 当前裁决 |
|---|---|---|---|
| 非法组件/配置/模型 | Manager 查不到名称抛普通 `Exception`；Pydantic 只做部分形状校验 | 稳定 `CAPABILITY_NOT_FOUND`/`CONFIG_INVALID`/`MODEL_UNAVAILABLE`，在唯一入口转换 | 只吸收方法边界，不吸收异常文本 |
| 空 query/空输入 | 查询仍可 `add_suggestion`；无命中返回英文字符串；空内容进入 Document/spaCy | 空输入策略、最大尺寸、拒绝/空结果、是否写副作用必须显式 | 产品策略待核，通用检索不应隐式写建议 |
| provider 缺库/缺 key | `available=False` 或 provider 内抛；构造器可能回退模型列表 | 探测与执行分离；错误码含 provider、可重试、缺少资源；不以 available=True 代替实测 | 吸收元数据，不吸收当前 fallback 静默语义 |
| 网络/Weaviate 断线 | `is_ready()` 在 health cleanup 才检查；连接和读写异常多为字符串 | 每次调用有 deadline、健康状态、有限重试/退避和幂等条件 | Weaviate provider 可升级候选，不是现成可靠实现 |
| 导入部分失败 | URL 子任务 `gather(return_exceptions=True)`；部分成功仍可能外层 `DONE`；内外重复 ERROR | 父 job 必须汇总子 job，`SUCCEEDED/PARTIAL/FAILED/CANCELLED` 单一终态，记录每文档结果 | 当前状态事件只能作为兼容输入，不能直接复用 |
| 写文档成功、写 chunk 失败 | 捕获后调用 `delete_document`，跨集合无事务 | 两阶段意图/补偿/对账；补偿失败进入可恢复状态，不报告 DONE | 最佳努力补偿归历史参考 |
| query/LLM 超时 | Weaviate query 有 300s；OpenAI generator `timeout=None`；部分 aiohttp 有 30s | 端到端 deadline 传递到每层，超时可重试性明确；取消上游流和释放 session | 必须升级，不能把 provider 默认 timeout 当平台契约 |
| 客户端主动断线 | WS handler `WebSocketDisconnect` 只 break；无 job cancel | 明确 disconnect policy：取消或后台继续；两者都必须可查、可恢复、可回放 | 网关当前行为仅 L0/L1 事实 |
| 进程崩溃/重启 | 无持久 job、恢复扫描、孤儿对账；Weaviate 数据可能部分存在 | job/step 意图先落账；重启恢复、幂等提交、孤儿扫描、证据链 | L3/L4 未验证，禁止声称可恢复 |
| 重复提交/重复事件 | 同名文档检查非原子；分片同 order 覆盖；建议先查后写有竞态 | upload/job/step/idempotency key + sequence + store constraint | 只能吸收“需要去重”的事实，不能吸收实现 |
| 错误路径清理自身失败 | 多数异常直接向上抛或只打印；删除补偿失败无二次队列 | 清理动作有独立结果和证据，二次清理/人工隔离；禁止吞异常后 DONE | 待核，需要真实故障注入 |

### 23.10 后续 L0-L4 防假绿分级

| 等级 | 当前核对要证明什么 | Verba 现有证据 | 后续结论/升级条件 |
|---|---|---|---|
| **L0 源码事实** | 文件、符号、路由、集合、状态和调用链确实存在 | 已读取 `interfaces.py`、`managers.py`、`verba_manager.py`、`server/api.py`、`helpers.py`、`types.py`、`WindowRetriever.py`、代表 provider、`docker-compose.yml` 和旧细探 | **通过静态建档**；这是存在性，不是行为通过 |
| **L1 静态契约** | Python/依赖/路由/DTO/导入关系可解析，边界形状无明显矛盾 | 当前历史文档列出依赖与测试，但当前核对未安装依赖、未执行编译；源码可见 `timeout=None`、错误对象入 JSON、重复终态等静态问题 | **部分**；要升级须在隔离环境执行 `python -m py_compile`/导入审计，并记录退出码 |
| **L2 单元/组件** | Document/Chunk、组件契约、配置序列化、状态事件转换和策略边界通过 | 仓库只有 `goldenverba/tests/document/test_document.py`、`chunk/test_chunk.py`；没有 Manager/provider/状态机测试，当前核对未执行 | **存在窄测试但未证明底座契约**；需补无 provider、空输入、维度错、重复事件、取消测试 |
| **L3 集成** | 网关→运行核心→模块→支持库→Weaviate/模型的真实链路、断线、补偿、重启恢复 | 没有覆盖 FastAPI/WS/Weaviate CRUD/导入/检索/生成的有效集成测试，当前核对未启动服务 | **未验证**；需隔离 Weaviate、假 provider/真实 HTTP、上传恢复、跨集合对账和唯一终态实测 |
| **L4 外部真实** | 真实模型/Weaviate/容器/网络、速率限制、超时、取消、进程崩溃和残留均可审计 | 当前核对未使用任何凭证、未访问外部 provider、未启动 Docker/Weaviate/Ollama、未做强杀 | **未验证**；不能以模型列表 fallback、历史镜像或 `DONE` 日志冒充 |

后续的底座验收不能只复跑现有两组窄单测。最低新增验收契约应包括：一个 provider 缺失、一个 HTTP 超时、一个用户取消、一个客户端断线、一个 Weaviate 部分写入、一个进程强杀、一个重启恢复、重复分片/重复 job、事件序号与唯一终态；每个场景记录真实命令、退出码、测试数、外部服务和清理结果。

### 23.11 复用/升级/新建/废弃裁决

| 裁决 | 内容 | 理由 |
|---|---|---|
| **吸收** | `Reader`、`Chunker`、`Embedding`、`Generator` 的最小方法边界；`Document`/`Chunk` 数据分层；模型与向量存储 provider 的适配思路；hybrid+window 检索策略；进度阶段名称作为兼容映射 | 源码证据充分，且属于非 Agent RAG 通用能力；但必须补版本、错误、超时、取消、资源和 schema 契约 |
| **升级** | `available` 元数据、模型目录探测、Weaviate 连接/集合适配、导入事件、ClientManager 连接缓存、跨集合补偿 | 有可用模式但当前实现混合产品/网关职责，且缺健康、租约、持久状态、幂等和崩溃恢复 |
| **新建** | 统一能力注册表；导入/查询/生成 job；事件账本与回放；VectorStore/DocumentStore 抽象；模型资源管理；唯一终态和对账器；取消/超时监督器 | Verba 没有这些通用治理能力，不能把 `Manager` 重命名后假装具备 |
| **废弃/隔离** | archived 项目直接作为生产底座；全局组件实例；构造器联网 `/models`；WS socket 注入 `LoggerManager`；`timeout=None`；HTTP 200/字符串伪成功；匿名 Weaviate；删后插入配置；跨集合最佳努力补偿冒充事务 | 与平台单一 owner、资源生命周期、统一错误和安全边界冲突 |
| **待核** | 各 provider 当前 SDK/API 版本、向量维度迁移、真实 Firecrawl crawl 轮询、Weaviate 4.9.6 与目标服务、断线后后台任务策略、外部限流与重试 | 当前核对严格只读，未凭证实测，不能把源码声明升为运行事实 |

### 23.12 后续唯一事实源与后续装配计划

- 本文件继续是 Verba 唯一正式架构事实源；旧 `细探-Verba.md` 已保留且不删除，后续只更新本文件。
- 当前核对没有修改系统工程平台、Verba 源码、依赖、配置、测试、README 或 Git；“映射”不等于生产底座已经新增能力。
- 若进入实现，顺序必须是：先登记需求与消费者契约 → 搜索已有能力并裁决复用/升级/新建 → 冻结 `Document`/`Chunk`/VectorStore/事件/错误/取消契约 → 以 provider 隔离方式装配 → 用 L0-L4 验收 → 记录资源残留与回滚证据。禁止先复制 `components/managers.py` 再补治理。
- 一个原子能力只能有一个能力 id、一个契约 owner、一个公开入口和一条调用链；provider 差异只能在支持库适配层；产品层差异只能在项目适配层/模块策略；网关不拥有领域状态；运行核心不拥有具体第三方 SDK。

### 23.13 后续证据、MCP 与范围说明

- **目标根目录**：`/Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/65_rag_frameworks/Verba`。
- **首次 `project_context`**：按任务要求先调用，但当前 MCP 返回错误绑定到 `/Users/hekunhua/Documents/Agent/PHP/华世王镞_v3`，项目名为 `华世王镞_v3`、开工 id 为空；该结果不是 Verba 证据，已排除。
- **`codegraph_explore`**：随后显式传入 Verba 根目录；返回该项目不存在 `.codegraph/`，代码图不可用，并要求改用本地 Read/Grep；未再次调用，也未把其他项目代码图冒充 Verba。
- **`development_start`/专属 MCP**：尝试以 Verba 根目录和仅允许修改本文件的路径开工，但 `project_toolkit` MCP 连续失败后不可达；因此没有有效开工 id、没有 MCP 验证入账，也没有伪造反馈或成功证据。用户指定的 `system_engineering_toolkit (http://127.0.0.1:8766/mcp/)` 在当前核对不可用，工具返回的实例名为 `project_toolkit`，两者均如实记录。
- **当前核对真实取证替代**：使用本地只读文件读取核对 `ARCHITECTURE.md`、`细探-Verba.md`、六类接口、Manager、API/WS、进度、Weaviate、代表 Reader/Embedding/Generator、Retriever、Docker Compose 和 setup.py；只追加本节到 `ARCHITECTURE.md`。
- **正式验证状态**：由于专属 MCP 不可达，无法执行其要求的 `mcp_feedback` 与 `verify_and_record`；当前核对不宣称 L1-L4 通过。修改文件仅为目标根 `ARCHITECTURE.md`，旧细探明确未删。