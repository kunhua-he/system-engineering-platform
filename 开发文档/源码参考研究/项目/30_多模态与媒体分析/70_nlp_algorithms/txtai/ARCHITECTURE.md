# txtai 架构研究归档

> 本文件是 `txtai` 项目的唯一架构事实文档。中文说明、结论和风险使用中文；源码路径、类名、函数名、配置键、路由、命令和第三方名称保留原文。此前 `细探-txtai.md` 的有效结论已人工核对并吸收，后续只维护本文件，旧细探不再作为独立事实源。

## 1. 项目定位与版本基线

`txtai` 是 NeuML 维护的 Apache 2.0 开源 all-in-one AI framework，定位为语义搜索、LLM orchestration 和 language model workflows 的统一框架。核心不是单一向量索引，而是一个 `Embeddings` database：将 dense/sparse vector indexes、graph network、relational/content database、ids 和可选 subindexes 组合为一个可保存、加载、增量更新和查询的对象；其上提供 `Pipeline`、`Workflow`、`Agent`，并通过 FastAPI Web API、OpenAI 兼容路由和 MCP 暴露能力。

本地参考库工作树基线：

- 根目录：`~/Documents/Agent/github 源码参考/30_多模态与媒体分析/70_nlp_algorithms/txtai`
- 本地分支：`master`
- 本地提交：`7b49504dca77d850628950760ccb3c4fa08e20e5`，提交时间 `2026-07-23 11:54:09 -0400`，提交说明 `Update test`
- 远程：`https://github.com/neuml/txtai.git`
- 通过本机代理 `127.0.0.1:4780` 获取的远程 `origin/master`：`20f818f72cacbdc7ea01912788a4b988db029c5e`，提交时间 `2026-08-19 06:37:51 -0400`，合并提交 `#1194 ... fix/1190-lemur-collection-centering`
- 远程较本地更新；远程源码以独立快照 `/tmp/txtai-remote-architecture` 取证，未向本地仓库执行 `pull`、`merge` 或覆盖未跟踪细探文件。
- 本地 `setup.py` 版本为 `9.12.0`；远程快照 `setup.py` 与 `src/python/txtai/version.py` 为 `9.13.0`。远程还新增/调整了 `tqdm`、agent 的 `mcp<2.0`/`beautifulsoup4` 等依赖，以及 `pipeline/data/safeopen.py`、`models/pooling/lemur.py`、`models/pooling/max.py` 等实现，故本文件的远程新版本结论以快照为准、本地路径以当前工作树为实现证据。
- 现场统计：本地 `src/python/txtai` 有 268 个 Python 文件、39 个包入口 `__init__.py`；测试目录有 80 个 `test*.py`；`docs/` 有 76 个 Markdown 文件。远程快照分别为 272、39、80、77。

## 2. 总体流程图

```text
┌──────────────────────────── 配置与调用入口 ────────────────────────────┐
│ Python API: txtai.Embeddings / Application / Workflow / Agent          │
│ YAML: Application.read(CONFIG 或 app.yml)                              │
│ CLI: txtai console；Web: uvicorn "txtai.api:app"；MCP: mcp=True      │
└──────────────────────────────┬─────────────────────────────────────────┘
                               ▼
┌────────────────────── Application / API 装配层 ─────────────────────────┐
│ createpipelines → createworkflows → createagents → indexes(loaddata)   │
│ RLock 保护 embeddings 写操作；ThreadPool 承载 schedule                 │
└───────────────┬─────────────────┬─────────────────┬─────────────────────┘
                ▼                 ▼                 ▼
        Pipeline 单能力      Workflow 编排       Agent 自主循环
        __call__              Task/Execute       smolagents + tools
                │                 │                 │
                └─────────────────┴─────────────────┘
                                  ▼
┌──────────────────────────── Embeddings 核心 ────────────────────────────┐
│ Stream 标准化文档 → Transform 批处理/向量化/memmap →                  │
│ ANN dense + scoring sparse + database content + graph + subindexes      │
│                          ↓                                             │
│ Search：graph → SQL/database → subindex/dense/sparse/hybrid → results   │
└──────────────────────────────┬─────────────────────────────────────────┘
                               ▼
┌──────────────────────────── 服务出口 ──────────────────────────────────┐
│ FastAPI routers + EncodingAPIRoute(JSON/MessagePack) + TOKEN 鉴权       │
│ FastApiMCP 挂载 /mcp；已启用 API route 自动成为 MCP 工具                │
└─────────────────────────────────────────────────────────────────────────┘
```

## 3. 真实分层与目录地图

### 3.1 顶层入口

- `src/python/txtai/__init__.py`：导出 `Agent`、`Application`、`Embeddings`、`LLM`、`RAG`、`Textractor`、`Workflow`，并安装 `logging.NullHandler`。
- `src/python/txtai/app/`：`Application` 是 YAML 配置驱动的单一装配器，解析配置、实例化管道/工作流/代理/向量库并提供统一调用方法。
- `src/python/txtai/embeddings/`：向量数据库核心，分为 `index/`、`search/`；通过 `ann/`、`database/`、`scoring/`、`graph/`、`vectors/`、`archive/`、`cloud/` 等工厂接入实现。
- `src/python/txtai/pipeline/`：`audio/`、`data/`、`image/`、`llm/`、`text/`、`train/` 和 `hfpipeline.py`，统一以 `Pipeline.__call__` 为能力边界。
- `src/python/txtai/workflow/`：`Workflow`、`Task`、`Execute` 与内置任务，支持批处理、任务链、stream、初始化/收尾和线程/进程并发。
- `src/python/txtai/agent/`：基于 `smolagents` 的 `Agent`、模型适配和工具工厂；包含 embeddings、function、skill、MCP 等工具适配。
- `src/python/txtai/api/`：FastAPI 创建、API 模板、路由、响应编码、集群、鉴权、扩展和 MCP。
- `src/python/txtai/console/`：基于标准库 `cmd.Cmd` 与可选 `rich` 的交互式控制台。
- `src/python/txtai/util/`、`serialize/`、`models/`、`data/`：可选依赖延迟加载、动态解析、序列化、模型基础组件和数据辅助。

### 3.2 Embeddings 子系统

| 层 | 真实职责与主要路径 |
|---|---|
| 输入规范化 | `embeddings/index/stream.py::Stream.__call__` 将裸数据、二元/三元 tuple、dict 统一成 `(id, data, tags)`；需要时由 `AutoId` 生成 id，并把当前序列写回 `config["autoid"]`。 |
| 批处理与落库 | `embeddings/index/transform.py::Transform` 以 `batch` 分批，向 `database`、`scoring`、`indexes`、`graph` 写入，同时把可向量化内容交给模型；使用临时 `.npy` 文件作为 memmap 缓冲。`Action.INDEX`、`UPSERT`、`REINDEX` 控制行为。 |
| 向量模型 | `vectors/` 工厂按配置选择 Hugging Face/Sentence Transformers、word vectors、external、llama.cpp、LiteLLM、LiteRT、model2vec 等后端。外部向量可通过 `transform` callable 或预计算数组输入。 |
| dense ANN | `ann/dense/` 提供 faiss、hnsw、annoy、sqlite-vec、torch、pgvector、milvus、turbovec、zvec、ggml 等可选后端；`ann/sparse/` 提供稀疏后端。具体实现通过 `ANNFactory` 创建。 |
| sparse scoring | `scoring/` 提供 BM25、TF-IDF、SIF、神经稀疏和 pgtext 等；`ScoringFactory` 按 `scoring`/`keyword`/`sparse`/`hybrid` 配置创建。 |
| 内容数据库 | `database/` 提供 SQLite 默认实现、DuckDB、RDBMS/SQLAlchemy、client/embedded 等；`Database` 维护列映射、对象编码、SQL 解析、自定义 functions/expressions 和统一 `SQLError` 包装。 |
| 图与子索引 | `graph/` 保存关系与图查询；`indexes/` 将多个命名 `Embeddings` 作为 subindexes，共享 `models` 缓存。 |
| 查询 | `embeddings/search/base.py::Search.__call__` 决策顺序为无索引返回空、默认 subindex、graph 查询、database/SQL 查询，最后进入 dense/sparse/hybrid index search。 |
| 混合融合 | `embeddings/search/hybrid.py::Hybrid` 根据 sparse 分数状态选择归一化加权、RRF 或 BB25/LogOdds 融合；dense+sparse 查询候选默认扩大到 `limit * 10` 后融合。 |
| 生命周期 | `Embeddings.__enter__/__exit__`、`close()` 关闭 ANN、database、scoring、graph、subindexes、vector model、query/reducer 并清空引用；`save/load` 支持目录与 tar.gz/tar.bz2/tar.xz/zip archive，亦支持 cloud。 |

### 3.3 Pipeline、Workflow 与 Agent

- `pipeline/base.py::Pipeline` 只有 `batch()` 辅助方法；子类只需实现 `__call__`。`pipeline/factory.py::PipelineFactory.list` 通过反射扫描当前 `txtai.pipeline` 模块中继承 `Pipeline` 且定义 `__call__` 的类，短名取小写类名；`create` 对 `package.Class` 使用 `Resolver` 动态解析，也允许 callable 直接作为管道。
- `app/base.py::Application.createpipelines` 先列出内建 pipeline，再把配置中的点路径键加入候选，并把 `similarity`、`extractor`、`rag`、`reranker` 等依赖型管道排序到后面；`createworkflows` 将 YAML task/action/stream 字符串解析成 callable；`createagents` 将 `llm` 与工具 target 解析后创建 `Agent`；`indexes` 最后加载现有索引或创建新 `Embeddings`，并回填 `extractor/rag/reranker` 的引用。
- `workflow/base.py::Workflow`：默认 `batch=100`，未指定 `workers` 时取所有 task 的最大 action 数；`__call__` 用 `Execute` 建立本次执行上下文，依次运行 `initialize`、stream、chunk、process、`finalize`。`chunk` 同时兼容有长度的序列和生成器。`schedule` 依赖可选 `croniter`，缺依赖时显式 `ImportError`。
- `workflow/task/base.py::Task`：action 可为 callable 列表；`select` 过滤、`unpack/pack` 管理 `(id,data,tag)`、`column` 选择 tuple 列、`merge` 支持 `hstack`/`vstack`/`concat`/None、`OneToMany` 表示 1→N、`concurrency` 交给 `Execute` 线程/进程执行。`filteredrun` 为元素编号，未选中元素原样透传，避免异构数据在同一 workflow 中丢失。
- `agent/` 以 `smolagents` 的 `CodeAgent`/`ToolCallingAgent` 为执行底座，`PipelineModel` 将 txtai LLM pipeline 接为模型；工具工厂覆盖 bash/edit/glob/grep/python/question/read/todowrite/websearch/write，并提供 `EmbeddingsTool`、`FunctionTool`、`SkillTool`、`TodoWriteTool` 和 MCP 适配。Agent 记忆使用按 session 的 `deque(maxlen=window)`，提示模板使用 Jinja2 `SandboxedEnvironment`。

## 4. 核心数据模型、状态与持久化

### 4.1 输入与索引内部模型

- 外部文档允许 `str`、`dict`、`(id, data)`、`(id, data, tags)`；`Stream` 统一为 `(id, data, tags)`。dict 的 `id`、`tags` 是控制字段，`columns.text`/`columns.object` 决定向量化字段。
- `Embeddings` 的核心状态字段为 `config`、`model`、`reducer`、`ann`、`ids`、`database`、`functions`、`graph`、`scoring`、`query`、`archive`、`indexes`、`models`；这些是运行时组件引用，不是独立持久化对象。
- 当 `content` 未启用时，`IndexIds` 保存内部 indexid 到用户 id 的映射；启用内容数据库时，database 保存文档与 indexid 关联。删除会先将用户 id 映射为内部 indexid，再同步 ANN/scoring/subindexes/graph。
- `Transform` 的 `offset`、`batch`、`quantize/qbits`、`columns` 控制增量和批处理；`upsert` 先删除同 id 的旧记录，再追加向量与各数据仓库。删除造成的 indexid 空洞由 `reindex` 重新编号。

### 4.2 磁盘格式与数据库边界

- `Embeddings.save(path)` 写入 `config.json`，并按存在的组件写入 `embeddings`、`lsa`、`ids`、`documents`、`scoring`、`indexes`、`graph` 子路径；archive 实现再把目录压缩为归档文件。
- `Embeddings.load(path)` 先读取配置并应用 override，再依次创建/加载 ANN、reducer、ids、database、scoring、subindexes、graph，最后加载向量模型和 query 模型。
- `Database.search` 支持普通相似度查询、带 `SIMILAR()` 的 SQL、纯 SQL；`database/sql/` 负责 SQL token、表达式、aggregate 与错误处理。`parameters` 用于命名参数绑定，数据库底层异常统一转为 `SQLError`。
- SQLite `database/sqlite.py::SQLite` 使用 `sqlite3.connect(..., check_same_thread=False)`；配置 `wal` 时开启 `PRAGMA journal_mode=WAL`。`copy` 在有未提交事务时使用 `iterdump`，否则使用 SQLite backup API。
- 序列化由 `serialize/` 工厂按 msgpack、safetensors、pickle 等实现选择；pickle 兼容读取受 `ALLOW_PICKLE` 环境变量/显式配置约束，旧格式兼容属于安全敏感边界。

## 5. 真实调用链

### 5.1 Python 建索引与检索

```text
Embeddings(config)
  → configure()
    → createscoring()/loadvectors()/loadquery()
  → index(documents)
    → initindex()
    → Stream(self)(documents)
    → Transform(...)(stream, tempfile.NamedTemporaryFile(.npy))
      → model.vectors()
      → database.insert()/scoring.insert()/indexes.insert()/graph.insert()
    → createann() → ann.index()
    → scoring.index()/indexes.index()/graph.index()
  → search(query)
    → Search(self)([query], ...)
      → graphsearch() 或 dbsearch() 或 search()
      → dense()/sparse()/Hybrid()
      → database.search()（启用 content 时）
```

`Application` 路径在索引写入上再包一层：`Application.add/index/upsert/delete/reindex` 先检查 `config["writable"]`；写操作进入 `self.lock` 的 `RLock`，`reindex` 还要求 `config["reindex"]`。因此直接使用 `Embeddings` 时，源码只承诺读线程安全，写操作由调用方自行同步；YAML 应用层才提供统一写锁。

### 5.2 API 请求链

```text
uvicorn "txtai.api:app"
  → api/application.py::create() 创建 FastAPI
  → lifespan() 读取 CONFIG → Application.read()
  → APIFactory.create(config, API_CLASS) 创建 API/Application
  → apirouters() 反射发现 routers/*.py 的 APIRouter
  → 按配置 include_router()
  → EncodingAPIRoute 按 Accept 选择 JSON/MessagePack
  → router handler → application.get() → API/Application 方法
  → Embeddings/Workflow/Pipeline → ResponseFactory 编码
```

API 路由由配置键控制启用；`embeddings` 存在而没有显式 `similarity` 时自动补 similarity 路由，`cluster` 存在而没有 embeddings 时补 embeddings 路由。`api/routers/embeddings.py` 已核实提供 `/search`、`/batchsearch`、`/add`、`/addobject`、`/addimage`、`/index`、`/upsert`、`/delete`、`/reindex`、`/count`、`/explain`、`/batchexplain`、`/transform`、`/batchtransform` 等端点；其余 router 覆盖 pipeline、workflow、agent、RAG、LLM、音频、图像、文件上传、OpenAI 兼容接口等。

鉴权由 `api/application.py::create` 读取 `TOKEN`，通过 `Authorization` 依赖校验 Bearer token；`api/authorization.py::Authorization.digest` 对 token 做 SHA-256，使用 `hmac.compare_digest` 恒定时间比较，失败返回 HTTP 401。`API.limit` 将 limit 限制到 1–250，默认 10；`API.weights` 将权重转为 float。

### 5.3 MCP 请求链

配置存在 `mcp: True` 或 mcp 字典时，`api/application.py::createmcp` 创建 `httpx.AsyncClient` + `ASGITransport`，再创建 `FastApiMCP(application, http_client=client, **mcpargs)` 并 `mount()`。默认挂载 `/mcp`；启用的 FastAPI 路由自动变成 MCP 工具，不需要为每个端点增加第二份声明。`clientargs` 可覆盖默认 `base_url=http://apiserver`、`timeout=100`，`mcpargs` 传给 `FastApiMCP`。

### 5.4 CLI 调用链

```text
Console(path)
  → preloop() 打印 txtai console 并可加载 path
  → .load YAML → Application(path)
  → .load index → Embeddings().load(path)
  → 普通输入 → search() 或 explain()
  → .config / .highlight / .limit / .workflow
  → rich Table 输出结果
```

`console/base.py::Console` 依赖 `rich`；缺少 `console` extra 时构造器直接抛出安装提示。默认输入被视为搜索词；`.workflow name args...` 只在当前 app 是 `Application` 时执行 workflow。

## 6. API、CLI、SDK 与协议边界

- Python SDK 边界：`txtai.Embeddings`、`txtai.Application`、`txtai.Workflow`、`txtai.Agent` 及顶层导出的 LLM/RAG/Textractor。
- YAML 边界：`Application.read` 接受文件路径、YAML 字符串或 dict；配置键包括 `embeddings`、`pipeline`/内建 pipeline 名、`workflow`、`agent`、`path`、`cloud`、`mcp`、`cluster` 等；配置中的 `package.Class` 和 callable 名称是动态依赖注入点。
- HTTP 边界：FastAPI `app`，由 `CONFIG` 指向 YAML；典型启动命令为 `CONFIG=app.yml uvicorn "txtai.api:app"`。Accept 头决定 JSON/MessagePack，`TOKEN` 决定是否启用 Bearer 鉴权。
- MCP 边界：`/mcp`，由 `mcp` 配置启用；服务端使用 `fastapi-mcp`，Agent 侧可通过 `mcpadapt` 接入外部 MCP。
- CLI 边界：console 命令与 `.config`、`.highlight`、`.limit`、`.load`、`.workflow` 子命令；它不是独立的索引格式或第二套业务逻辑，而是 `Application/Embeddings` 的交互式壳。
- 其他协议/适配：cloud 支持对象存储；`ServiceTask` 通过 requests+xmltodict 调远程服务；RDBMS 通过 SQLAlchemy；OpenAI router 提供兼容接口。各项通过 extras 延迟进入，不应视为核心必然依赖。

## 7. 技术栈与依赖边界

### 7.1 默认安装

当前本地 `setup.py` 默认依赖 `faiss-cpu`、`huggingface-hub`、`msgpack`、`numpy`、`regex`、`pyyaml`、`safetensors`、`torch`、`transformers`；Python 要求 `>=3.10`。远程 `9.13.0` 另加入 `tqdm>=4.66.3`。

### 7.2 Optional extras

- `agent`：`jinja2`、`mcpadapt`、`smolagents`；远程还声明 `beautifulsoup4`、`mcp<2.0`。
- `api`：FastAPI、fastapi-mcp、httpx、uvicorn、aiohttp、Pillow、python-multipart。
- `ann`/`vectors`/`similarity`：faiss 之外的 annoy、hnswlib、milvus-lite、pgvector、scipy、scikit-learn、sqlalchemy、sqlite-vec、turbovec、zvec、sentence-transformers、llama-cpp-python、LiteLLM 等。
- `database`/`graph`/`cloud`/`workflow`/`console`/`model`：DuckDB、SQLAlchemy、networkx、grand-*、libcloud、croniter、requests、openpyxl、xmltodict、rich、onnx/onnxruntime 等。
- `pipeline-*`：按 audio/data/image/llm/text/train 分域安装；`pipeline` 汇总这些 extra，`all` 汇总全部能力。
- `MINIMAL`：`setup.py` 在环境变量存在时将包名改为 `txtai_minimal`，默认重型依赖转入 `default` extra，体现“核心可最小安装、能力按需加装”的发行策略。

`util/library.py::Library` 对 numpy、torch、yaml、regex、transformers、huggingface-hub、safetensors 等做条件导入并提供桩对象；各能力在实际使用时才抛出缺少 extra 的 `ImportError`。这让主包导入链相对延迟，但 `Embeddings` 默认模型仍需从 Hugging Face 加载，完整 dense/agent/API 能力不能在纯标准库环境中直接工作。

## 8. 测试与验证结构

- 测试根：`test/python/`，现场统计 80 个 `test*.py`。
- 核心覆盖：`testembeddings.py`（默认 dense、sparse、hybrid、external、subindex、save/load、upsert/delete、terms、quantize、reducer）、`testapp.py`（YAML 装配、自定义 pipeline、workflow stream）、`testworkflow.py`、`testgraph.py`、`testserialize.py`。
- 数据库覆盖：`testdatabase/testdatabase.py`、`testsqlite.py`、`testduckdb.py`、`testrdbms.py`、`testclient.py`、`testcustom.py`、`testencoder.py`、`testsql.py`。
- ANN/vector/scoring 覆盖：`testann/`、`testvectors/`、`testscoring/`，包括外部向量、Hugging Face/SBERT、词向量、稀疏模型和后端适配。
- Pipeline 覆盖：`testpipeline/testaudio/`、`testdata/`、`testimage/`、`testllm/`、`testtext/`、`testtrain/`；可选依赖测试必须结合实际环境。
- API/协议覆盖：`testapi/testapiembeddings.py`、`testapiworkflow.py`、`testapiagent.py`、`testapi/testmcp.py`、`testauthorization.py`、`testencoding.py`、`testextension.py`、`testopenai.py`、`testcluster.py`、`testdependency.py`；`testmcp.py` 真实检查 `mcp: True` 时 app routes 中存在 `/mcp`。
- CLI 覆盖：`testconsole.py` 真实建立 embeddings 索引与压缩/非压缩保存物，验证 `.load`、`.limit`、搜索、`.config`、`.highlight`、`.workflow`、空结果和无数据库索引。
- 本轮没有安装依赖、启动服务或执行全量测试，符合源码参考库只读边界；“测试存在”不等于“本轮测试通过”。后续若要运行，应在独立虚拟环境中按目标 extra 安装，并避免默认模型下载影响结果。

## 9. 安全、并发、资源与行为边界

1. `Application` 对 index 写操作使用 `RLock`，但裸 `Embeddings` 只保证读线程安全；多线程写必须由上层同步。
2. `writable` 是写入口门禁；`reindex` 额外要求 `reindex=True`。API 将这些异常映射为 HTTP 403。
3. API token 使用 Bearer + SHA-256 + `hmac.compare_digest`；未配置 `TOKEN` 时不自动增加该依赖，生产部署需显式设置。
4. Agent 工具涉及 shell、文件、网络和 Python 执行，虽然提示模板使用 Jinja2 sandbox，工具本身仍是高权限边界，应由宿主部署策略限制。
5. SQL 由自研 `database/sql` 解析并以命名参数绑定；不得把“支持 SQL 查询”误读为允许未经解析的任意字符串拼接。
6. `Execute`、workflow、Application thread pool、Embeddings 组件均提供 close/context-manager 路径；定时任务应通过 `Application.wait()` 或对象回收收口。
7. dense 索引可能加载原生库（faiss、torch、各种 ANN）；源码在 Darwin/Windows 对 faiss 设置 `OMP_NUM_THREADS=1` 等兼容措施，但不同 optional backend 仍有平台风险。
8. archive、cloud、RDBMS、pickle、外部向量和模型下载均是边界扩展；其可用性、数据落盘位置和凭据行为不能从核心 `Embeddings` 语义推断。

## 10. 对系统工程底座的可借鉴与不可直接照搬

### 可吸收

- `Pipeline.__call__` 的薄能力边界与 `PipelineFactory.list/create` 反射工厂：适合抽象“能力入口 + 工厂发现”，但底座仍应额外固定能力 id、版本和契约。
- `Application` 的 YAML 单容器装配与 `Resolver` 点路径解析：可作为配置依赖注入的参考，不能把任意物理路径直接升级成稳定公开契约。
- `Workflow.Task` 的 `(id,data,tag)` 通道、select 过滤、未选中透传、OneToMany 与 merge 三策略：适合异构模块编排和统一中间数据形态。
- Embeddings 的“索引向量 + 内容库 + 图 + 稀疏评分”联合读模型，以及 graph→SQL→vector 的查询决策链。
- `Library` 的条件导入/桩对象/用到才报错模式，适合第三方提供者隔离；不能隐藏真实不可用状态。
- `close()`、上下文管理器、临时 memmap 和写锁的资源收口组合。
- MCP 由已启用 API route 自动暴露的模式，可参考统一网关能力自动映射，但底座必须明确权限、审计和版本边界。

### 不可直接照搬或待核

- 默认安装依赖 torch、faiss、transformers 等重型原生栈，与系统工程平台“核心公共部分只用标准库”的铁律冲突；只能借鉴适配层边界。
- `PipelineFactory` 反射扫描模块是隐式注册，缺少稳定声明、契约版本和冲突治理，不能直接替代平台能力目录。
- `Application.function` 允许配置字符串解析任意 callable，适合应用内部扩展，不应直接作为跨项目安全调用接口。
- Agent 的 shell/edit/write 工具属于高权限执行面，需在平台中补权限、沙箱、资源预算、审计和失败证据。
- 远程 `9.13.0` 相对本地 `9.12.0` 的 `lemur` pooling、`safeopen`、依赖和 API 细节已变化；凡基于本地源码做复用，必须先重新对照远程快照和对应测试。

## 11. 未确认项、风险与后续复核点

- 本轮未运行 Python 测试、API、CLI、MCP 或模型推理；依赖/网络/模型缓存状态未知。
- 远程源码已通过 `127.0.0.1:4780` 独立克隆，未把远程内容合并到本地工作树；远程新增文件的测试行为仍需在独立环境运行确认。
- 建档前存在未跟踪细探材料；本轮已人工吸收并清理，未修改源码、依赖、测试或配置。
- `codegraph_explore` 返回目标项目没有 `.codegraph/` 索引，因此本轮使用源码文件、README、依赖、测试、Git 版本与既有细探交叉取证；后续如需符号级调用图，需由用户决定是否在该参考仓初始化索引。
- `Application` 的 YAML 配置是强动态边界；配置键与源代码类名/路由之间的自动发现关系，应在升级时以 `PipelineFactory`、`APIFactory`、`apirouters` 和测试共同复核。
- 远程版本 `9.13.0` 的发行文件、PyPI 元数据、文档站内容和 GitHub 默认分支源码可能存在发布时间差异；本文件只将 Git 远程快照作为远程实现基线，不宣称已验证发布包。

## 12. 证据路径

- 项目说明：`README.md`
- 此前细探材料（已人工吸收并清理）
- 依赖与发行入口：`setup.py`、`pyproject.toml`、`src/python/txtai/version.py`
- 顶层导出：`src/python/txtai/__init__.py`
- 装配器：`src/python/txtai/app/base.py`
- 向量库：`src/python/txtai/embeddings/base.py`、`embeddings/index/transform.py`、`embeddings/index/stream.py`、`embeddings/search/base.py`
- 工作流：`src/python/txtai/workflow/base.py`、`workflow/task/base.py`
- API/MCP：`src/python/txtai/api/application.py`、`api/base.py`、`api/route.py`、`api/authorization.py`、`api/routers/embeddings.py`
- CLI：`src/python/txtai/console/base.py`
- 数据库：`src/python/txtai/database/base.py`、`database/sqlite.py`
- 测试：`test/python/testembeddings.py`、`testapp.py`、`testworkflow.py`、`testconsole.py`、`testapi/testmcp.py` 及其余 `test/python/test*.py`
- 远程独立快照：`/tmp/txtai-remote-architecture`，基线提交 `20f818f72cacbdc7ea01912788a4b988db029c5e`
