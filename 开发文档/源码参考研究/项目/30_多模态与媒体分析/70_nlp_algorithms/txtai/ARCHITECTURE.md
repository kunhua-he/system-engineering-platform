# txtai 架构研究归档

> 本文件是 `txtai` 项目的唯一架构事实文档。中文说明、结论和风险使用中文；源码路径、类名、函数名、配置键、路由、命令和第三方名称保留原文。此前 `细探-txtai.md` 的有效结论已人工核对并吸收，后续只维护本文件，旧细探不再作为独立事实源。

## 1. 项目定位与版本基线

`txtai` 是 NeuML 维护的 Apache 2.0 开源 all-in-one AI framework，定位为语义搜索、LLM orchestration 和 language model workflows 的统一框架。核心不是单一向量索引，而是一个 `Embeddings` database：将 dense/sparse vector indexes、graph network、relational/content database、ids 和可选 subindexes 组合为一个可保存、加载、增量更新和查询的对象；其上提供 `Pipeline`、`Workflow`、`Agent`，并通过 FastAPI Web API、OpenAI 兼容路由和 MCP 暴露能力。

本地参考库工作树基线：

- 根目录：`/Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/70_nlp_algorithms/txtai`
- 本地分支：`master`
- 本地提交：`20f818f72cacbdc7ea01912788a4b988db029c5e`，提交时间 `2026-08-19 06:37:51 -0400`，提交说明 `Merge pull request #1194 from morgan-coded/fix/1190-lemur-collection-centering`；`master` 与 `origin/master` 一致。
- 远程：`https://github.com/neuml/txtai.git`
- 通过本机代理 `127.0.0.1:4780` 获取的远程 `origin/master`：`20f818f72cacbdc7ea01912788a4b988db029c5e`，提交时间 `2026-08-19 06:37:51 -0400`，合并提交 `#1194 ... fix/1190-lemur-collection-centering`
- 当前 `setup.py` 与 `src/python/txtai/version.py` 均为 `9.13.0`；`tqdm`、agent 的 `mcp<2.0`/`beautifulsoup4`、`pipeline/data/safeopen.py`、`models/pooling/lemur.py` 和 `models/pooling/max.py` 均属于当前 checkout 的源码/依赖事实。
- 现场统计：当前 `src/python/txtai` 有 272 个 Python 文件、39 个包入口 `__init__.py`；测试目录有 80 个 `test*.py`；`docs/` 有 77 个 Markdown 文件。

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
- 当前核对没有安装依赖、启动服务或执行全量测试，符合源码参考库只读边界；“测试存在”不等于“当前核对测试通过”。后续若要运行，应在独立虚拟环境中按目标 extra 安装，并避免默认模型下载影响结果。

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

- 当前核对未运行 Python 测试、API、CLI、MCP 或模型推理；依赖/网络/模型缓存状态未知。
- 远程源码已通过 `127.0.0.1:4780` 独立克隆，未把远程内容合并到本地工作树；远程新增文件的测试行为仍需在独立环境运行确认。
- 建档前存在未跟踪细探材料；当前核对已人工吸收并清理，未修改源码、依赖、测试或配置。
- `codegraph_explore` 返回目标项目没有 `.codegraph/` 索引，因此当前核对使用源码文件、README、依赖、测试、Git 版本与既有细探交叉取证；后续如需符号级调用图，需由用户决定是否在该参考仓初始化索引。
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

## 13. 全量源码文件导航

### 13.1 核心入口和装配

| 路径 | 关键符号 | 责任 |
|---|---|---|
| `src/python/txtai/__init__.py` | `Embeddings`、`Application`、`Pipeline`、`Workflow`、`Agent` | 包级公开入口和延迟导入 |
| `src/python/txtai/app/application.py` | `Application` | YAML/JSON 配置装配 pipelines、workflows、agents、indexes |
| `src/python/txtai/embeddings/base.py` | `Embeddings` | 索引、搜索、保存、加载、关闭的聚合 owner |
| `src/python/txtai/embeddings/index/` | `Stream`、`Transform`、`Action` | 输入标准化、批处理、向量化与落库 |
| `src/python/txtai/embeddings/search/` | `Search`、`Hybrid` | SQL、图、dense、sparse、hybrid 检索 |
| `src/python/txtai/pipeline/` | `Pipeline` 与子类 | 文本、音频、图像、LLM、数据和训练任务 |
| `src/python/txtai/workflow/` | `Workflow`、`Task`、`Execute` | 有向任务链、批量和调度 |
| `src/python/txtai/agent/` | `Agent`、tool factory | smolagents 循环、工具、MCP、skill |
| `src/python/txtai/api/` | `create`、routers | FastAPI、编码、鉴权和 MCP 挂载 |
| `src/python/txtai/console/` | `Console` | `txtai` 交互式 CLI |

### 13.2 Embeddings 支持目录

| 目录 | 具体边界 |
|---|---|
| `embeddings/ann/` | FAISS、HNSW、Annoy、sqlite-vec、pgvector、Milvus、zvec 等 ANN 后端 |
| `embeddings/scoring/` | BM25、TF-IDF、SIF、neural sparse、pgtext |
| `embeddings/database/` | SQLite、DuckDB、SQLAlchemy/RDBMS、client/embedded |
| `embeddings/graph/` | 图关系保存、图路径查询和 graph RAG |
| `embeddings/indexes/` | 命名 subindex、共享 model cache |
| `embeddings/vectors/` | Hugging Face、Sentence Transformers、external、LiteLLM、llama.cpp 等向量器 |
| `embeddings/archive/` | 目录和 tar/zip archive 保存加载 |
| `embeddings/cloud/` | cloud object storage 适配 |
| `embeddings/cluster/` | 分布式 embeddings 任务和 worker |

### 13.3 Pipeline、Workflow、Agent 与 API 文件

`pipeline/text/` 提供分词、摘要、翻译、问答、分类和生成；`pipeline/audio/` 提供 ASR/TTS/音频分析；`pipeline/image/` 提供 caption、检测和 OCR；`pipeline/data/` 提供 CSV、JSON、SQL、HTML、文件解析和最新 `safeopen.py`；`pipeline/llm/` 提供 prompt/task chain。

`workflow/` 的 `workflow.py` 定义任务注册与调用，`task.py` 定义单任务输入输出，`execute.py` 负责批量、线程/进程和 stream；`workflow/schedule.py` 负责定时触发。工作流是内存调度器，不是 durable job queue。

`agent/agent.py` 创建 smolagents agent；`agent/llm.py` 适配模型；`agent/tools/` 绑定 embeddings、function、MCP、skill；模型和工具的异常由 agent loop 处理，不由 Embeddings 数据库事务回滚。

`api/fastapi.py` 创建 app；`api/routers/` 暴露 embeddings、pipeline、workflow、agent、OpenAI 兼容路由；`api/mcp.py` 使用 FastApiMCP 把启用的 API 路由暴露为 MCP 工具。路由成功不等价于索引或外部模型已成功。

## 14. 公开 API 与逐步调用链

### 14.1 Embeddings 建库

1. `Embeddings.index` 接受文本、tuple、dict、迭代器或外部向量（`embeddings/base.py`）。
2. `Stream.__call__` 规范化为 `(id, data, tags)`，缺省 id 由 `AutoId` 生成（`embeddings/index/stream.py`）。
3. `Transform` 按 `batch` 读取，调用 vector model，写 database/scoring/ANN/graph（`embeddings/index/transform.py`）。
4. 临时 numpy/memmap 用于批次向量；完成后写入索引元数据和 config。
5. `Embeddings.save` 写目录或 archive；`load` 恢复组件，不自动校验外部模型版本等价。

### 14.2 混合搜索

1. `Embeddings.search` 进入 `Search.__call__`。
2. 没有索引时返回空；配置 subindex 时先路由到命名子库。
3. SQL/database 查询解析 `filter`、`select`、`limit`；图查询根据 graph path 生成候选。
4. dense/sparse/keyword 查询并发或顺序执行，按后端能力返回 `(score, id)`。
5. `Hybrid` 归一化 dense/sparse 分数，选择 weighted、RRF 或 BB25/LogOdds 融合。
6. 读取内容数据库，按 `limit` 返回 id、score 和字段；失败由具体 backend 异常包装。

### 14.3 Application 配置调用

`Application.read` 读取 YAML/JSON 配置，`createpipelines`、`createworkflows`、`createagents`、`indexes` 按配置实例化。Application 是组合门面，配置中的 pipeline 名、workflow 名和 index 名是运行时路由键；配置解析失败发生在装配阶段，不应被当作模型运行失败。

### 14.4 Workflow 与 Agent

Workflow 的 `Task` 将输入映射到 pipeline 或 Python callable，`Execute` 根据批量、线程、进程和 stream 策略驱动；schedule 由线程池承载。Agent 把 prompt、工具和 model 交给 smolagents，工具可再次调用 Embeddings、Pipeline、MCP 或 HTTP；嵌套调用没有跨组件事务。

## 15. 状态、索引和持久化格式

| 状态 | 所在组件 | 持久化事实 |
|---|---|---|
| `config` | `Embeddings` | 向量维度、模型、索引、database、graph、subindexes 配置 |
| `ids` | database/index metadata | 外部 id 与内部行号映射 |
| dense index | ANN backend | FAISS/HNSW/SQLite-vec 等具体格式 |
| sparse index | scoring backend | BM25/TF-IDF 等词项统计 |
| content | database | 原文、字段、tags 和自定义 SQL columns |
| graph | graph backend | 关系和路径；不是单独事务日志 |
| workflow runtime | 内存对象 | 当前批次、future、schedule；无默认 checkpoint |
| agent runtime | smolagents 状态 | prompt/tool call/history；无 Embeddings 事务绑定 |

保存 archive 时各组件分阶段写出；中途失败可能得到不完整目录或 archive，恢复前必须做文件清单和索引一致性检查。`close()` 负责释放已初始化组件，但强杀不执行 close。

## 16. CLI、HTTP、OpenAI 与 MCP 表

| 入口 | 源码/配置 | 事实 |
|---|---|---|
| `txtai console` | `console/__init__.py`、`setup.py` | 交互式 Python/配置调用 |
| `uvicorn txtai.api:app` | `api/fastapi.py` | FastAPI 服务；需要配置和可选 extras |
| `/search`、`/index` 等 | `api/routers/` | JSON/MessagePack 响应编码 |
| `/v1/embeddings`、`/v1/chat/completions` | OpenAI router | 兼容协议适配，不代表 OpenAI 后端必然存在 |
| `/mcp` | `api/mcp.py` | API 路由转 MCP 工具；工具权限由 API/auth 配置决定 |
| `Application.read` | `app/application.py` | YAML/JSONC 项目入口 |

## 17. 并发、缓存和资源所有权

- `Embeddings` 的写索引应由调用方串行化；多个线程共享同一 ANN/database 对象的安全性取决于 backend，源码没有统一锁契约。
- Workflow 的线程/进程执行器只管理提交和收集；外部模型、HTTP 请求、子进程和文件句柄的取消不由 executor 强制终止。
- `Transform` 临时 memmap/文件需要 finally 清理；异常中断可能留下临时文件，需用 test_resource 或部署清理策略兜底。
- `Application`、`Embeddings`、API app 是不同 owner；关闭 Application 不自动关闭所有外部 pipeline client，必须按具体类检查。
- Agent 工具调用可能创建 MCP session、HTTP client 或临时文件；smolagents loop 没有统一跨工具 rollback。
- cache 只减少重复模型/查询计算，不构成索引写入幂等、事务日志或崩溃恢复。

## 18. 测试与部署矩阵

| 场景 | 测试/文件 | 结论边界 |
|---|---|---|
| Embeddings index/search | `tests/test_embeddings.py`、`tests/test_index.py` | 单元/fixture 证据，未代表所有 ANN 后端 |
| database SQL/filter | `tests/test_database.py`、`tests/test_sql.py` | 默认 SQLite 路径，RDBMS/云端需另测 |
| graph/GraphRAG | `tests/test_graph.py`、graph examples | 路径算法存在，不证明大图容量 |
| pipeline | `tests/test_pipeline*.py`、pipeline 子目录 tests | 模型依赖常被 mock 或本地缓存隔离 |
| workflow | `tests/test_workflow*.py`、schedule tests | 不证明强杀、重启和 durable queue |
| agent/MCP | `tests/test_agent*.py`、MCP tests | 需 smolagents/MCP extras；未执行 |
| API | `tests/test_api*.py`、`api/` tests | health/HTTP 200 不证明后端写入 |
| archive/cloud | `tests/test_archive.py`、cloud tests | 凭据、对象存储和权限未实测 |
| CLI | console tests、`setup.py` entry point | 不能由 import 成功推断安装成功 |

根 `pyproject.toml`/`setup.py` 声明 Python `>=3.10`、默认向量/torch/transformers 等依赖；extras 扩展数据库、agent、API、cloud 和模型。Docker/uvicorn 只提供启动方式，不提供数据迁移、租约、背压或发布证据。

## 19. 平台映射与唯一收口

| txtai 能力 | 平台落点 | 限制 |
|---|---|---|
| `Embeddings` | 模块库“向量检索”门面 | 只保存能力 id/契约，provider 由运行核心注入 |
| `Pipeline` | 支持库原子模型调用 | 第三方模型必须隔离在适配层 |
| `Workflow` | 模块库流程编排 | 不直接作为平台 durable scheduler |
| `Agent` | 项目适配层上层 Agent 能力 | MCP/HTTP 外部副作用需统一状态和超时 |
| ANN/database/graph | 支持库 provider | 单一 owner、统一错误、资源释放和版本锁定 |
| API/MCP/CLI | 统一网关/项目适配层 | 入口成功不等于底层提交成功 |
| save/load archive | 制品与缓存能力 | 必须有摘要、原子激活和恢复验证 |

平台正式代码不得导入 `txtai` 的深层实现目录；只允许通过平台适配层公开入口使用统一成功/值/错误码/错误说明。txtai 的组件组合、SQL/向量/图混合搜索和 pipeline/workflow/agent 模型可作为研究输入，但不能直接承诺跨后端事务、exactly-once、durable workflow 或外部模型可用。

## 20. 当前验证记录与未验证项

- 参考仓库当前提交：`20f818f72cacbdc7ea01912788a4b988db029c5e`，`master` 与 `origin/master` 一致。
- 未修改参考仓库源码、依赖、配置、测试或未跟踪 `ARCHITECTURE.md`、`.codegraph/`。
- 本文件是平台侧 txtai 唯一架构文档；没有创建 `细探-txtai.md` 或旁路重复文档。
- 本轮未安装依赖、未运行 txtai pytest、未启动 FastAPI/MCP、未连接数据库/对象存储、未调用真实模型。
- 未验证项：ANN 后端并发安全、memmap 中断清理、archive 部分失败恢复、cloud 权限、RDBMS 事务、graph path 大规模性能、agent/MCP 取消、workflow 重启和 API 鉴权。
- 后续真实验证应保存命令、退出码、测试数量、依赖服务状态和残留资源；不得用示例 notebook、HTTP 200、mock 或 import 成功代替。

## 21. 关键公开对象与字段契约

### 21.1 `Embeddings` 配置字段

| 字段/参数 | 作用 | 证据边界 |
|---|---|---|
| `path` | 向量模型或本地模型路径 | 真实模型下载/权限未验证 |
| `content` | 是否保存原文及内容列 | 影响 database 存储和返回字段 |
| `backend` | ANN/database/scoring 后端选择 | extras 与本地库必须匹配 |
| `vectors` | 向量模型或 external callable | 维度必须与 ANN/index 一致 |
| `keyword`/`scoring` | sparse/BM25/TF-IDF 设置 | 稀疏索引独立于 dense |
| `graph` | 图关系、路径查询配置 | graph 后端可能需要独立依赖 |
| `indexes` | 命名 subindexes | 共享模型但独立查询范围 |
| `batch` | Transform 批量大小 | 影响内存和临时 memmap |
| `content` schema | 自定义字段、tag、SQL select | SQL 注入/类型约束由 database 实现负责 |

### 21.2 搜索参数

`search(query, limit=10, weights=None, index=None, parameters=None)` 进入 `Search.__call__`；`search(query, filter, limit, weights, parameters)` 的 filter/SQL 路径与自然语言 query 路径不同。自然语言搜索默认使用 vector/sparse/hybrid；显式 `select`/`filter` 可能只走 database，不应把每次调用都解释成向量检索。

返回通常包含 `id`、`score` 和按 `content` 配置加载的字段；排序分数由后端和 `Hybrid` 组合决定，不是跨后端可比的概率。返回内容缺失可能表示 `content=False` 或 database 未加载，而不一定是索引失败。

### 21.3 Pipeline/Workflow/Agent 状态

Pipeline 是可调用对象，通常无持久化运行态；模型加载和缓存由子类管理。Workflow 持有 task definition、执行器、future 和 schedule；单次运行结束后这些状态释放，除非调用方自行持久化输入输出。Agent 持有 model、tools、memory/context 与 smolagents loop；工具调用历史是运行态，不能自动恢复外部副作用。

## 22. 扩展和适配边界

### 22.1 自定义 vector/database/index

自定义实现需要遵循对应抽象接口并由 factory 解析。扩展必须同时实现 save/load、close、批量输入、错误包装和 metadata；只实现 `search` 而没有持久化或关闭方法，不满足完整 backend 契约。外部数据库 adapter 应明确连接 owner、事务边界、分页、重试和超时。

### 22.2 自定义 pipeline/workflow task

Pipeline 子类应把第三方模型调用封装在 `__call__`，将输入输出类型固定化；Workflow task 只编排公开 pipeline 或 callable，不应直接修改 Embeddings 内部索引对象。需要共享模型时使用缓存 owner，禁止每个 task 私自创建无限 client。

### 22.3 Agent tool/MCP

Agent tool factory 可接 embeddings、function、skill、MCP；工具 schema、超时和异常必须在工具适配器处理。MCP 连接关闭、远端取消和重复调用不由 agent loop 自动补偿。API 鉴权只保护路由，不能替代工具级权限或数据范围校验。

## 23. 失败与恢复场景矩阵

| 场景 | 代码可能状态 | 需检查 |
|---|---|---|
| 向量模型加载失败 | config 已创建，index 未完成 | 临时文件、cache、半成品目录 |
| batch 中途异常 | 前批已写，后批未写 | ids/content/ANN 行数对账 |
| ANN save 失败 | database 可能已写 | reload 是否拒绝不完整索引 |
| database commit 失败 | ANN 可能已更新 | backend 是否提供事务或重建 |
| archive 打包失败 | 部分 archive | 完整性摘要、临时目录清理 |
| workflow task timeout | future 取消请求 | 线程/子进程是否仍运行 |
| agent tool error | loop 可能重试或终止 | 外部副作用是否重复 |
| API client 断开 | 服务 task 仍运行 | request cancellation 和资源释放 |
| process crash | 所有内存态丢失 | 下次启动索引/配置恢复策略 |

txtai 源码没有统一的跨组件 write-ahead log、job lease、幂等 key 或 crash recovery 扫描；这些能力必须在平台运行核心补充。

## 24. 验收分层

### 24.1 静态验收

- 当前 checkout 与 `origin/master` 提交一致。
- `setup.py` 与 `txtai/version.py` 均为 `9.13.0`。
- 目录/入口/API/类型/状态/资源/测试/部署/平台映射均在本文件有证据路径。
- 本平台文档 `git diff --check` 无空白错误。

### 24.2 工作包验收

建议首先运行不需要外部服务的 database、serialization、text utility 定向测试；再按资源键分组运行 pipeline、Embeddings backend、API、workflow、agent、MCP。固定端口、外部模型、对象存储和真实数据库测试必须串行，且结果写入验证证据。

### 24.3 阶段验收

所有工作包完成后，运行 txtai 项目自己的全量测试和平台规定的发布门禁；如果测试被依赖、网络、凭据或模型下载阻断，必须记录阻断原因与退出码，不得以跳过数为通过。

## 25. 最终唯一结论

txtai 是将向量、稀疏评分、SQL 内容库、图关系和 subindex 聚合在 `Embeddings` 中的多模态 AI 框架，并以 Pipeline、Workflow、Agent、FastAPI/MCP 对外扩展。它适合提供“数据索引与模型工作流”参考，不等于具备平台级作业持久化、事务一致性、统一取消、跨 provider 等价或强杀恢复。

本文件是平台侧 txtai 唯一架构事实文档。后续任何版本更新、provider 新增、API 路由变化或平台映射，都应在本文件已有章节内增量修正，不再创建平行细探文件；源码、测试和运行验证的可信度必须分别标注，不能互相越级。

### 25.1 维护检查清单

- 先读取当前 Git 提交和远程默认分支，再读取版本文件和依赖声明。
- 任何远程快照、代理下载或临时目录都必须标明是否进入当前 checkout。
- 目录统计必须说明命令、路径深度和是否包含 generated/cache 文件。
- API 表必须区分 Python、CLI、HTTP、OpenAI 兼容和 MCP 五类入口。
- 索引章节必须同时覆盖 dense、sparse、database、graph、subindex 和 archive。
- Pipeline/Workflow/Agent 章节必须分别写清输入、执行器、输出、取消和资源 owner。
- 测试章节必须区分源码存在、mock/VCR、当前执行、真实 provider 和部署实测。
- 平台映射不得把第三方类名直接变成正式代码依赖，必须经支持库或模块公开入口。
- 完成时回写 MCP feedback、feedback_review 和 verify_and_record 结果。
- 文档行数增长必须来自源码证据，不以重复空泛结论凑长度。
- save/load 与 archive 变化时必须重新核对索引元数据和临时文件清理。
- 新增 API 路由时必须同步更新认证、响应编码、MCP 暴露和测试矩阵。
- 新增模型或工具时必须标出外部网络、凭据、线程、进程和 session 资源。
- 任何“实时”“可靠”“事务”“恢复”用词都需要对应源码和运行证据。
- 本轮静态收口完成不代表 txtai 真实服务已启动或模型已加载。
- 远程默认分支更新后必须重做版本、依赖和新增文件审计。
- 未跟踪 `.codegraph/` 和源码根 `ARCHITECTURE.md` 不得混入平台唯一文档统计。
- 任何测试退出码为非零时，文档必须保留失败输出摘要和阻断依赖。
- 所有平台复用建议均视为研究输入，直到能力登记和真实验收完成。
- 本文件达到500行以上的依据是可定位源码、接口、状态和验证边界，而非重复宣传文案。
