# LanceDB 架构归档

> 研究对象：`/Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/80_storage_vector_index/lancedb`
>
> 本地基线：`0bc081608ae6c244fe0b72dc5100d59c695e3b2a`（`fix(python): allow selection of _rowid in Permutation (#3133)`，2026-07-22）
>
> 远程复核：`e517ba5205a42d8a311d5521c27cb2c0040fd445`（`refactor: remove unnecessary skill references (#3977)`，2026-08-20）；远程源码通过本机代理 `127.0.0.1:4780` 独立快照 `/tmp/lancedb-remote-e517ba5` 读取。
>
> 本文件是项目根唯一正式架构文档。此前 `细探-lancedb.md` 已人工核对并吸收；后续事实以本文件和当前源码为准，旧细探不再作为独立事实源。

## 1. 项目定位

LanceDB 是建立在 Lance 列式格式之上的多模态 AI 数据平台/向量数据库，提供本地 in-process、对象存储和 LanceDB Cloud 远程后端。它面向向量相似搜索、全文搜索、混合搜索、SQL 过滤与分析，能够存储和检索文本、图片、视频、点云、元数据及向量。项目本身是 Lance 的封装层：列式格式、数据集版本、向量/标量/倒排索引和部分分词算法主要由外部 `lance`、`lance-index`、`lance-linalg` 等 crate 实现，LanceDB 负责数据库/表抽象、查询编排、参数映射、绑定和远程协议。

核心设计结论：Rust 是权威核心；Python、TypeScript/Node.js、Java 是绑定或 SDK 层；`BaseTable` 抽象同时覆盖本地 `NativeTable` 与远程 `RemoteTable`。功能演进遵循 `rust/lancedb` → PyO3/TypeScript/Java 绑定 → 各端测试与文档的顺序。

## 2. 总体流程

```text
┌────────────────────────────────────────────────────────────────────────────┐
│                               LanceDB SDK                                   │
│  Python(sync/async) │ TypeScript/Node(napi-rs) │ Rust │ Java(JNI)          │
└───────────────┬──────────────────────────────┬───────────────┬─────────────┘
                │                                │               │
                ▼                                ▼               ▼
       参数/数据转换、嵌入、重排          Rust Table/Query     Java facade
                │                                │
                └────────────────┬───────────────┘
                                 ▼
                    Connection → Database → Table
                                 │
              ┌──────────────────┴──────────────────┐
              │                                     │
       NativeTable / Lance Dataset          RemoteTable / HTTP REST
              │                                     │
              ▼                                     ▼
   Arrow RecordBatch + DataFusion       ClientConfig + OAuth/API key
              │                                     │
              ▼                                     ▼
  Lance manifest/fragments/indices       LanceDB Cloud / Namespace API
              │
              ▼
   vector ANN │ scalar │ FTS │ hybrid │ SQL │ version/branch/tag
```

## 3. 真实分层与目录地图

```text
Cargo.toml
├── rust/lancedb/                         Rust 核心 crate
│   └── src/
│       ├── lib.rs                         公共模块、connect、DistanceType、ApproxMode
│       ├── connection.rs                  ConnectBuilder、表/命名空间入口
│       ├── connection/create_table.rs     CreateTableBuilder
│       ├── database.rs                    Database trait、请求模型、版本/作业接口
│       ├── database/listing.rs            本地目录/对象存储表发现
│       ├── table.rs                       Table、BaseTable、NativeTable、写入与版本能力
│       ├── table/add_data.rs              流式 add 与写入结果
│       ├── table/merge.rs                 merge_insert builder 与结果
│       ├── table/merge/lsm.rs             Lance MemWAL/LSM 写入路径
│       ├── table/query.rs                 本地查询计划、DataFusion、namespace pushdown
│       ├── table/datafusion/udtf/fts.rs   fts(table_name, query_json) UDTF
│       ├── table/create_index.rs           索引参数映射与创建
│       ├── table/optimize.rs              索引/碎片优化与版本清理
│       ├── table/schema_evolution.rs      加列、改列、删列与元数据更新
│       ├── query.rs                       QueryBase、VectorQuery、FTS、hybrid、投影
│       ├── index/{scalar,vector}.rs       BTree/Bitmap/FM/LabelList/FTS、IVF/HNSW 构建器
│       ├── embeddings.rs                  EmbeddingFunction、EmbeddingRegistry
│       ├── rerankers/rrf.rs               Rust RRF 重排
│       ├── dataloader/permutation/        row_id 轻量视图、split、shuffle、溢写
│       ├── remote/{client,db,table,oauth}.rs 远程 HTTP、重试、认证与表映射
│       ├── data/、io/、ipc/、utils/       Arrow/对象存储/流与资源工具
│       └── error.rs                       统一 Error/Result
├── python/
│   ├── src/                               PyO3/native Rust binding
│   ├── python/lancedb/                    Python sync/async SDK
│   │   ├── db.py、table.py、query.py      连接、表、查询高层 API
│   │   ├── _lancedb.pyi                  原生扩展类型契约
│   │   ├── embeddings/                    多提供者注册与配置
│   │   ├── rerankers/                     多种重排器
│   │   ├── permutation.py、streaming.py  数据装载/流接口
│   │   └── background_loop.py             同步 API 到 asyncio 的桥接
│   └── python/tests/                      Python 单元、集成、文档测试
├── nodejs/
│   ├── src/                               napi-rs Rust binding
│   ├── lancedb/                           TypeScript 高层 API
│   └── __test__/                           Jest 测试
├── java/lancedb-core/                     JNI Java SDK
├── docs/                                  Python/JS/Java API 文档源
├── examples/、rust/lancedb/examples/      Rust 使用示例
└── ci/、.github/、dockerfiles/            CI、mock、发布和容器基建
```

## 4. 连接、数据库与表模型

### 4.1 连接入口

- Rust：`lancedb::connect(uri)` 返回 `ConnectBuilder`，`.execute().await` 得到 `Connection`；支持本地路径、`s3://`、`gs://`、`memory://` 与 `db://`。
- Python：`lancedb.connect()` 位于 `python/python/lancedb/__init__.py`，根据 URI 将请求路由到 `LanceDBConnection` 或 `RemoteDBConnection`；`connect_async()` 提供异步面。
- TypeScript：`nodejs/lancedb/index.ts` 的 `connect()` 归一化 URI、选项、`Session` 和 `HeaderProvider`，再调用 napi 原生 `LanceDbConnection.new`。
- namespace：本地 `dir`、远程 `rest` 或自定义 `LanceNamespace` 可接管表目录、命名空间和可选的 `QueryTable`/`CreateTable` pushdown。

`Database` trait 管理表名、创建/打开/删除/重命名、namespace、clone、作业和读一致性；`OpenTableRequest` 携带 `namespace_path`、`ReadParams`、位置、namespace client 与 managed versioning。`Table` 通过 `BaseTable` 统一表能力，`NativeTable` 操作 Lance Dataset，远程实现将同一能力映射为 HTTP 请求。

### 4.2 数据模型与持久化

- 一张表对应 Lance Dataset；数据以 Arrow `RecordBatch`/流为输入输出。
- Schema 使用 Arrow 类型；向量通常是 `FixedSizeList<Float16/Float32>`，二进制向量使用相应数值类型。计算列和 embedding 列通过 Schema metadata 中的 `lancedb::column_definitions` 持久化。
- Lance 采用 manifest/fragments 和不可变数据版本。写入完成后原子切换版本指针；`list_versions`、`restore`、`checkout`、branch/tag 支持回溯和并行演进。`read_consistency_interval` 控制跨进程读刷新，默认偏向性能而不每次检查。
- `merge_insert` 支持匹配更新、源数据删除和新行插入；安装 `LsmWriteSpec` 后可走 Lance MemWAL/`ShardWriter` 的 LSM 路径。bucket、identity、unsharded 三种分片要求单次写入路由到单一 shard，写入器由 `ShardWriterCache` 管理并在关闭时 drain。
- Blob/二进制数据有独立处理路径；Python 查询可按 `BlobMode` 延迟读取、读取字节或自动处理 blob 列。

## 5. 查询与索引调用链

### 5.1 普通、向量和 SQL 查询

典型 Rust 调用链：

```text
Table::query()
  → QueryBuilder / VectorQueryBuilder
  → QueryBase(limit/offset/only_if/select/fast_search/prefilter)
  → NativeTable::query / RemoteTable::query
  → BaseTable::create_plan 或 HTTP 请求
  → Lance Scanner / DataFusion ExecutionPlan
  → DatasetRecordBatchStream
```

`rust/lancedb/src/table/query.rs` 的 `execute_query` 先判断 namespace `QueryTable` pushdown 是否安全；有 branch、`use_lsm`、`approx_mode` 或 MemWAL 未压实数据时回退本地执行，避免远程请求缺少这些语义而返回过时结果。本地 `create_plan` 配置向量列、距离度量、nprobes/ef/refine、过滤、投影、FTS、排序、row id 和批大小，再由 DataFusion 执行；`MaxBatchLengthStream` 与 `TimeoutStream` 提供边界控制。

Python `query.py` 保留 sync/async 查询面，将 `Expr` 转 SQL 或原生表达式，提供 `to_arrow`、`to_pandas`、`to_polars`、`to_batches` 等转换。TypeScript `Query`/`VectorQuery` 以 async iterator 返回 Arrow 批次，并支持 `where`、`select`、`limit`、`nearestTo`、`fullTextSearch` 等 API。

### 5.2 向量索引

`Index::Auto` 按列类型自动选择：向量列默认 IVF-PQ，标量列默认 BTree。显式 builder 包括 `IvfFlat`、`IvfPq`、`IvfSq`、`IvfRq`、`IvfHnswFlat`、`IvfHnswPq`、`IvfHnswSq`。参数在 `table/create_index.rs` 转换为外部 `lance-index` 参数；距离类型包括 `L2`、`Cosine`、`Dot`、`Hamming`，`ApproxMode` 提供 RQ 查询速度/召回权衡。

建索引、列类型校验、训练、等待和统计由 Rust 统一实现；Python/TypeScript 只负责公开 builder 和调用。真实 ANN 算法实现不在本仓库，属于 `lance-index`/`lance-linalg` 外部边界。

### 5.3 标量与全文索引

标量索引包括 `BTree`、`Bitmap`、`LabelList` 和 `FM`（字符串/二进制子串）；`FTS` 使用 BM25 倒排索引。FTS 查询通过 `FtsQuery` JSON 协议表达 `Match`、`Phrase`、`Boost`、`MultiMatch`、`Boolean` 及 `Occur::Must/Should/MustNot`，结果附 `_score`。

`rust/lancedb/src/table/datafusion/udtf/fts.rs` 注册 `fts(table_name, query_json)` DataFusion UDTF，通过 `TableResolver` 得到 `TableProvider`，所以可继续组合 SQL 的 `WHERE`、`GROUP BY`、`ORDER BY _score` 和 `LIMIT`。`lancedb::tokenize` 与 Python/TypeScript `tokenize` 可在不打开表的情况下按 tokenizer 配置生成 token；模型型 tokenizer 仍要求客户端本地存在语言模型。

### 5.4 混合搜索与重排

混合查询并行执行 vector 与 FTS 两条路径，按 `rank` 或归一化分数进入 `RRFReranker` 等重排器，再按 `_rowid` 合并、去重、恢复原始 `_distance`/`_score`、截断 limit。Rust 提供 RRF；Python 还提供 `MRRReranker`、`LinearCombinationReranker`、`CrossEncoderReranker`、Cohere/OpenAI/Jina/ColBERT/VoyageAI/Watsonx 等实现。

## 6. Embedding 与多模态机制

`EmbeddingFunction` 约定 `source_type`、`dest_type`、`compute_source_embeddings`、`compute_query_embeddings`；`EmbeddingDefinition` 记录源列、目标列和函数名，`EmbeddingRegistry` 负责注册/获取。`MemoryRegistry` 使用 `Arc<RwLock<HashMap<...>>>`，读写共享注册表。

Rust 的 `WithEmbeddings` 包装 `RecordBatchReader`，单个 embedding inline，多个 embedding 使用 scoped threads 并行计算；找不到注册函数时返回 `Error::EmbeddingFunctionNotFound`。Python 层通过 registry 和 Arrow metadata 让 embedding 配置随表保存，提供 OpenAI、sentence-transformers、Cohere、Gemini、Ollama、OpenCLIP、SigLIP、ColPali、Watsonx、Bedrock 等适配器。阻塞/长耗时模型调用使用专用 `lancedb-embedding` executor，不占用 asyncio 默认线程池；后台 loop 和 fork hook 在 `background_loop.py` 中负责同步/异步桥接及子进程重置。

敏感配置不应硬编码。Python embedding 配置要求 API key 等敏感字段使用 `$var:name` 或 `$var:name:default` 变量引用；认证失败等不可重试错误不进入指数退避。该机制是项目安全边界，不是完整沙箱。

## 7. 远程后端、认证与错误

`rust/lancedb/src/remote/client.rs` 基于 `reqwest`，负责 URL 解析、请求构造、额外 header、`x-request-id` 透传、TLS/mTLS、用户标识和流式 multipart 上传。`ClientConfig` 还限制单次插入请求字节数和持续时间，默认 `8 GiB`，用字节/时间任一阈值切分大写入。`remote/retry.rs` 按 request/connect/read 分别计数，使用指数退避和 jitter；`Error::Retry` 保留 request id、各类失败计数和 HTTP 状态。

`remote/oauth.rs` 处理 OIDC discovery、OAuth client credentials、token 过期与刷新；API key、OAuth、`HeaderProvider` 是不同认证边界。`RemoteTable` 与 `NativeTable` 共享 `BaseTable` 形状，但远端能力受服务端协议和 namespace pushdown 支持范围约束。不要把本地 DataFusion 表达式、branch、LSM、模型 tokenizer 语义未经检查地假定为远端可用。

统一错误类型在 `rust/lancedb/src/error.rs`：`InvalidInput`、`Schema`、`TableNotFound`、`TableCorrupted`、`TableAlreadyExists`、`IndexNotFound`、`EmbeddingFunctionNotFound`、`Runtime`、`Timeout`、`JobFailed`、`Http`、`Retry`、`NotSupported` 等；Python 层补充上下文和修复提示。

## 8. 数据装载与资源边界

`dataloader/permutation` 只保存底表 `_rowid`、split id 和顺序，不复制业务数据。`PermutationBuilder` 支持过滤、`Random`/`Hash`/顺序 split、随机 shuffle、clump 以降低对象存储 IOPS，以及临时/永久 permutation 表。排序使用 DataFusion，默认 `DEFAULT_MEMORY_LIMIT = 100MB`，可由 `LANCEDB_PERM_BUILDER_MEMORY_LIMIT` 覆盖，并通过 `DiskManagerBuilder` 溢写临时目录。

其他边界：查询输出可设置 `max_batch_length` 和 timeout；索引 cache 会影响 RAM；HNSW/量化训练有峰值内存；对象存储由 Lance/Lance IO 负责；本地模式直接读写文件系统，不提供应用级沙箱。多版本/原子指针提供版本一致性，但项目不宣称传统数据库 ACID 事务语义。

## 9. API、SDK、CLI 与协议边界

- **公开库 API**：Rust crate、Python `lancedb`、Node 包 `@lancedb/lancedb`、Java `lancedb-core`；入口分别为 `rust/lancedb/src/lib.rs`、`python/python/lancedb/__init__.py`、`nodejs/lancedb/index.ts` 和 `java/lancedb-core`。
- **协议**：Arrow `RecordBatch`/IPC、DataFusion SQL/Expr、FTS JSON、Lance manifest/version、namespace API、远程 REST/HTTP、OAuth/OIDC。
- **CLI**：仓库没有独立业务 CLI；`cargo`、`uv`、`pnpm`、`mvnw` 和 CI 脚本是开发/验证命令，不是运行时产品入口。
- **插件/代理资料**：仓库包含 `.agents`、`plugins/lancedb` 等开发辅助资料，但不改变核心运行时边界。

## 10. 依赖与版本基线

本地 `Cargo.toml` workspace 使用 Rust edition 2024、rust-version `1.91.0`，Lance 生态依赖锁定 `9.1.0-beta.8`，Arrow `58.0.0`，DataFusion `54.0.0`。Python `pyproject.toml` 要求 Python `>=3.10`，依赖 `pyarrow>=16`、`numpy`、`pydantic`、`lance-namespace`，原生扩展由 `maturin` 生成 `lancedb._lancedb`。本地 Node 包版本为 `0.32.0-beta.2`，使用 pnpm、napi-rs、TypeScript 5.5、Node `>=18`，发布 7 个平台二进制目标；Java POM 对齐 Arrow `15.0.0` 和 `lance-core` `9.1.0-beta.8`。

远程独立快照显示版本已明显前进：workspace Lance 依赖为 `11.0.0-beta.15`，Node 为 `0.38.0-beta.2`，Python tests 的 `polars` 上限由本地 `<=1.3.0` 变为 `<=1.32.3`，并新增 Python `type_tests/connect.py` 到 pyright include；远程 `AGENTS.md` 增加 Python API reference 维护规则。远程还增加了 `ClientConfig` 的 TLS/header provider/user id/大请求切分字段，以及 namespace managed-versioning、clone、LSM 路径和 query pushdown 的更完整实现。远程快照仅用于研究，没有回写本地源码或依赖。

## 11. 测试、验证与未执行事项

测试结构已现场确认：

- Rust：`rust/lancedb/src/**` 单元测试，`rust/lancedb/tests/` 集成测试覆盖 object store、embedding registry/并行、blob；`rust/lancedb/examples/` 提供 smoke 示例。
- Python：`python/python/tests/` 覆盖 db/table/query/index/FTS/hybrid/embeddings/permutation/LSM/namespace/blob/remote/OAuth/S3/OTel，以及 `tests/docs/` 文档示例测试；`python/pyproject.toml` 配置 strict markers、`slow`、`s3_test`。
- Node：`nodejs/__test__/` 覆盖 table、remote、Arrow、sanitize、OTel；`package.json` 的 `jest --verbose` 是测试入口。
- Java：`java/lancedb-core` 使用 Maven/JUnit，父 POM 配置 compiler、Surefire、Spotless 和 JNI header。

本次仅做只读源码、README、依赖、入口、数据模型、API、测试、旧细探和远程版本研究，未安装依赖、未启动服务、未构建、未运行测试、未修改源码/配置/依赖/测试、未提交 Git。测试“存在”与测试“通过”必须严格区分；后续验证应使用各目录 `AGENTS.md` 指定的 uv/cargo/pnpm/mvn 命令，并根据当前版本重新建立证据。

## 12. 可借鉴点、风险与后续复核

### 可借鉴点

1. `BaseTable` 把本地和远程能力收敛到同一异步契约，再由后端实现差异化。
2. Embedding registry 将能力名、类型契约和表 metadata 关联，适合能力配置随制品/数据载体保存。
3. FTS JSON、`QueryBase` builder 和 DataFusion Expr 形成可演进的查询参数契约。
4. 独立 embedding executor、`MaxBatchLengthStream`、timeout、临时目录和磁盘溢写体现资源隔离与有界原则。
5. 不可变版本 + 原子指针 + branch/tag/restore 提供低破坏回滚模型。
6. 远程 request id、分类型重试计数、TLS/header provider 和敏感变量约束可作为外部能力调用器参考。

### 风险与未确认项

- 关键索引、分词、Lance manifest 和数据格式实现位于远程 workspace crate，本文件只记录 LanceDB 的适配边界，不能替代 Lance 源码研究。
- `NativeTable`、`RemoteTable`、Python `table.py`/`query.py` 体量大，跨端 API 的细微差异应以对应版本源码和测试为准。
- 本地基线落后远程；远程快照未合并，远程新字段/协议不能直接假定在本地发行物可用。
- namespace pushdown、LSM 未压实数据、branch/version、FTS tokenizer 本地模型和云端 REST 的兼容性需按服务端版本复核。
- 大规模训练/索引/对象存储场景的内存、IO、成本与一致性结论尚未通过运行基准验证。

## 13. 证据路径

- 项目约定：`AGENTS.md`、`python/AGENTS.md`、`nodejs/AGENTS.md`
- 定位与入口：`rust/lancedb/src/lib.rs`、`connection.rs`、`database.rs`、`table.rs`
- 查询与索引：`rust/lancedb/src/query.rs`、`table/query.rs`、`table/create_index.rs`、`index.rs`、`table/datafusion/udtf/fts.rs`
- 数据和扩展：`embeddings.rs`、`table/merge/lsm.rs`、`dataloader/permutation/builder.rs`、`python/python/lancedb/db.py`、`query.py`、`nodejs/lancedb/index.ts`、`table.ts`
- 依赖：`Cargo.toml`、`rust/lancedb/Cargo.toml`、`python/pyproject.toml`、`nodejs/package.json`、`java/pom.xml`
- 测试：`rust/lancedb/tests/`、`python/python/tests/`、`nodejs/__test__/`、`java/lancedb-core/src/test/`
- 此前历史细探（已人工吸收并清理）
- 远程复核快照：`/tmp/lancedb-remote-e517ba5`，提交 `e517ba5205a42d8a311d5521c27cb2c0040fd445`

## 14. 后续：通用底座映射与唯一存储链路

本节是基于当前源码的后续裁决输入，不是把 LanceDB 目录直接搬进系统工程平台，也不是 LanceDB 自身的官方 L0-L4 分层。L0-L4 表示平台验收和职责边界：L0 公共契约，L1 原子支持库/受管 provider，L2 领域检索模块，L3 运行核心，L4 项目适配层/网关/SDK 与控制面。

### 14.1 唯一存储链路

```text
L4 项目适配层 / HTTP-MCP 网关 / Python、TypeScript、Java SDK
  → L3 运行核心：能力注册、版本锁、租约、deadline、取消、重试预算、幂等、崩溃恢复、证据
  → L2 向量/全文检索模块：查询意图、过滤、召回配方、混合合并、重排、引用与结果契约
  → L1 向量存储支持库：表/Schema/Arrow、读写、事务提交、版本/分支、索引、对象存储、远程客户端
  → 受管 LanceDB provider（Rust 核心；Python/PyO3/远程 HTTP 适配）
  → Lance Dataset / manifest / fragment / index / Arrow IPC
  → 本地文件系统、S3/GCS/Azure 或 LanceDB Cloud 对象存储
```

固定不变量：

1. **唯一存储 owner**：表、Schema、Arrow 批次、写入、删除、更新、版本、索引和对象存储访问只能从“向量存储支持库”公开能力进入；模块不持有 `Dataset`、`reqwest::Client`、PyO3 原生对象或云端 SDK client。
2. **唯一检索 owner**：向量、FTS、标量过滤和 hybrid 只是同一检索模块的召回策略；上层不能分别调用“向量搜索”和“全文搜索”再自行拼结果。RRF/线性组合、去重、过滤、limit、引用和降级由检索模块一次裁决。
3. **唯一运行 owner**：并发、队列、连接/进程生命周期、wall-clock deadline、取消传播、重试上限、租约、崩溃回收和恢复证据只能由运行核心治理。LanceDB 的 async future、HTTP retry 或 Python `LOOP.run()` 不能替代运行核心。
4. **唯一版本坐标**：结果必须带表身份、namespace、branch、版本/读水位、Schema/索引摘要和检索链版本。缓存不能跨这些坐标复用；远程 `x-lancedb-version` 水位不能被模块忽略。
5. **禁止侧链**：不允许模块直连 Lance/Python client、不允许 L4 直接写对象存储、不允许 provider 内偷偷完成业务去重/重排、不允许为本地与远程各复制一套检索流程。历史英文键或兼容路由只在 L4 单入口归一化。

### 14.2 LanceDB 能力到平台落点

| LanceDB 实体/能力 | 当前源码事实 | 平台唯一落点 | 明确不吸收 |
|---|---|---|---|
| `Table`/`BaseTable`/`NativeTable`/`RemoteTable` | `BaseTable` 同时抽象 schema、读写、索引、查询、版本和优化；Native 作用于 Lance Dataset，Remote 作用于 HTTP Cloud | L1 向量存储支持库提供统一表能力；L2 只提交统一查询/写入契约 | 不把 `Table` 对象穿透到模块或正式业务 |
| Arrow `Schema`/`RecordBatch`/IPC | Rust 以 Arrow `SchemaRef`、`RecordBatchReader`/stream 为核心；Python 通过 PyArrow 转换，Remote 以 JSON schema + Arrow body 传输 | L0 固化字段、向量维度、nullable、metadata、批次与流式结果契约；L1 做 Arrow 转换/校验/边界限制 | 不把 pandas/Polars/NumPy 作为公共存储真相；只在 L4/L1 适配 |
| 表 Schema/metadata/主键 | Lance Schema 支持嵌套字段、字段路径、metadata；`set_unenforced_primary_key` 只登记主键、不保证写入唯一性；embedding 定义随 metadata 保存 | L1 Schema 支持库负责兼容校验、字段路径、向量维度、metadata 读写；L2 负责业务主键语义和幂等策略 | 不把“unenforced”主键宣称为数据库唯一约束 |
| vector ANN index | `Index::Auto` 对向量默认 IVF-PQ；显式 IVF/HNSW/SQ/RQ；参数最终交给 `lance-index`/`lance-linalg` | L1 原子索引能力；L2 选择召回参数、过滤/重排策略；L3 监督构建、等待、预算和失败恢复 | 不把 ANN 算法实现复制进平台公共核心 |
| scalar/FTS index | BTree、Bitmap、LabelList、FM 和 BM25 FTS；FTS 通过 DataFusion UDTF 与 SQL 组合 | L1 标量/全文索引 provider；L2 统一 keyword/vector/hybrid 召回和引用 | 不建立独立全文库与独立向量库两条写链 |
| `QueryBase`/`VectorQuery`/FTS/hybrid | builder 生成 DataFusion 计划或远程 JSON；hybrid 召回后由 RRF 等重排 | L0 查询/错误/读版本契约；L2 检索模块持有 query recipe、去重、重排、引用 | 不让 SDK 自己拼 query JSON 或重排结果成为事实 |
| 写入/`merge_insert`/LSM | Native 分区先生成未提交 `Transaction`，最后一个分区合并后由 `CommitBuilder` 一次提交；MemWAL LSM 只支持约束后的 upsert 形态，单表缓存一个 shard writer | L1 原子写、merge、LSM 原子能力；L3 负责幂等键、并发上限、deadline、恢复对账 | 不把 Lance 的 commit 直接等同平台跨资源事务 |
| 版本/branch/tag/restore | `BaseTable` 暴露 version、checkout、checkout_latest、restore、branch/tag；time-travel handle 禁止修改 | L1 版本/引用支持库；L3 用不可变版本、激活指针、CAS/恢复治理运行态 | 不让模块直接改版本指针或删除仍被引用版本 |
| 远程 `ClientConfig`/`RemoteTable` | reqwest 负责 TLS/mTLS、header provider、user id、request id、分片上传、重试；RemoteTable 有 schema cache、branch、read watermark | L1 HTTP/namespace provider；L3 注入 deadline、取消、重试预算、请求证据；L4 仅做认证/配置适配 | 不把 HTTP 连接池和 OAuth 状态放进检索模块 |
| 对象存储/namespace | Lance/Lance IO 负责本地/S3/GCS 等 object store；namespace 可提供 location、storage options、credential refresh、managed versioning | L1 对象存储支持库和凭证适配；L3 监督句柄、临时文件、上传分片和清理 | 不让 L4 绕过支持库拼对象路径或保存长期临时凭证 |
| Python/Rust 边界 | Rust `rust/lancedb` 是权威实现；PyO3 `python/src` 暴露原生类型，Python `lancedb/` 是 sync/async 门面，`LOOP.run()` 桥接同步 API | L1 以受管 provider 封装原生/第三方边界；L4 Python SDK 只做参数和结果映射；L2 不导入 `_lancedb` | 不把 Python 包的便利 API 当平台契约，不在主运行进程任意加载原生扩展 |

### 14.3 一致性、索引与事务语义

#### 14.3.1 数据一致性

`DatasetConsistencyWrapper` 明确区分三种读取模式：`None` 是 Lazy（复用当前 Dataset），`Duration::ZERO` 是 Strong（每次读检查最新版本），正间隔是 Eventual（TTL 缓存，临近过期后台刷新，过期后同步刷新）。同一 Table 实例的写入会立即更新自身 dataset；其他实例是否看见新版本取决于模式或 `checkout_latest()`。time-travel wrapper 固定版本，branch handle 追踪自己的 HEAD，且固定版本时拒绝修改。

RemoteTable 还会把响应头 `x-lancedb-version` 折叠到单调递增的 `min_read_version`，查询体携带当前 version/branch，减少负载均衡读节点造成的回退读。schema cache 有 TTL 和错误状态失效；这证明了“远程读一致性”是 provider/运行边界，不应被 L2 重新实现。

平台映射：

- L0：每个读/写结果必须声明 `table_id、namespace、branch、requested_version、observed_version、consistency_mode、schema_fingerprint`；读水位不是业务事件时间。
- L1：支持 Lazy/Strong/Eventual、time travel、branch、schema cache 和 read watermark；写入成功后返回提交版本和行统计。
- L2：检索模块只能在一次查询中固定读坐标；hybrid 的 vector/FTS 子查询必须使用同一坐标，不能一支读新版本、一支读旧缓存。
- L3：跨请求缓存、重试和故障恢复必须校验版本水位与 Schema/索引摘要；读到旧版本时按契约重读或返回一致性错误，不静默拼接。

这不是传统数据库的完整 ACID 证明：当前源码显示 Lance manifest/fragment 的不可变版本和单次 commit 语义，但没有证明跨多表/多对象的分布式事务、exactly-once 或任意业务副作用回滚。平台契约应明确 `提交成功`、`提交未知`、`部分物化待对账` 三种状态。

#### 14.3.2 索引一致性

索引创建前必须解析字段路径并校验 Arrow 类型；向量维度从 `FixedSizeList` 或 Lance 类型推断，FTS/标量索引也有类型白名单。索引构建是与数据版本绑定的派生制品，不是 canonical rows：

1. 建索引提交成功后，L1 返回 `index_name/index_uuid、base_version、schema_fingerprint、state`；未完成只能是 `building`，不能返回可用。
2. `wait_for_index` 有 timeout；超时只表示等待失败，不能删除底表，也不能把“任务已提交”包装为“索引已就绪”。
3. 新写入、schema 变更、drop/optimize 可能改变索引适用性；L3 必须记录索引基线版本，查询发现过期/缺失时按策略回退扫描、排队重建或明确降级，并记录召回质量风险。
4. FTS tokenizer metadata 随索引保存，但 model-backed tokenizer 仍需客户端存在模型；“能 tokenize”不等于服务端 FTS 索引可用。
5. index cache、HNSW/量化训练和 FTS 构建都有内存/IO 峰值；资源预算、临时文件和取消清理由 L3 监督。

#### 14.3.3 写事务与并发

Native `InsertExec` 的真实顺序是“各 DataFusion partition 用 `execute_uncommitted_stream` 产生 Lance `Transaction` → 共享锁收集 → 最后分区合并 fragments → `CommitBuilder::execute` 一次提交 → `DatasetConsistencyWrapper.update`”。因此单次 insert 的分区提交具备原子合并形状，但它不是跨表事务。`merge_insert` 标准路径有 Lance 的 retry/timeout；LSM 路径要求 unenforced primary key、upsert-only 和输入单 shard，writer 关闭走 `drain_and_close`。

并发边界裁决：

- 同一表的多任务提交必须以 Lance commit/版本冲突结果为准；L2 不用 Python 锁模拟成功。
- `DatasetConsistencyWrapper` 的 `Arc<Mutex<DatasetState>>` 只保护本地句柄状态；它不是跨进程/跨对象存储锁。
- `ShardWriterCache` 同时只持有一个 shard writer；换 shard 前必须 drain/close，关闭结果要读回。
- Remote 写重试只有在输入 `rescannable` 且错误可重试时执行；multipart 需要可重扫输入，否则拒绝开启重试，避免部分写重复。
- 业务 upsert 幂等键、跨表事务、租约和恢复状态不属于 LanceDB 自动提供，统一由 L3 + L2 领域契约补足。

### 14.4 超时、取消、崩溃恢复与资源释放

| 场景 | L1 向量存储支持库/provider | L2 检索模块 | L3 运行核心/证据 |
|---|---|---|---|
| 查询超时 | Native query 使用 `QueryExecutionOptions.timeout`/`TimeoutStream`；Remote 将毫秒 deadline 发 `x-request-timeout-ms`，并用 `tokio::select!` 终止等待 | 取消 vector/FTS 子查询，不能拼接半套结果；输出明确 timeout/partial 语义 | 传递硬 deadline、记录 attempt/request id、取消并排空 stream/future，归还租约 |
| `merge_insert`/索引等待超时 | `tokio::time::timeout`/`wait_timeout` 返回失败；超时不等于底层已强杀 | 不把“写任务提交”当业务成功 | 对不可取消写入标记 `commit_unknown`，重启后用版本/幂等键读回对账 |
| HTTP 连接/读/请求失败 | reqwest 分开 connect/read/request retry counter，指数退避+jitter；错误保留 request id/status/计数 | 只对无副作用或契约允许的节点重试；hybrid 不重复一侧已确认结果 | 预算化重试、熔断、deadline 传播；不可重试错误立即终止 |
| 主动取消/客户端断开 | Rust async future drop 可停止等待；同步 Python `LOOP.run()` 只表示调用方停止等待，不证明原生写线程已停 | 停止排队、关闭 Arrow reader、撤销未提交召回 | L3 记录取消原因和任务终态；硬截止需独立进程组，不用线程假杀 |
| 写入部分成功/响应丢失 | Lance manifest commit 后版本可读；对象存储可能已有孤儿 fragment，当前项目未证明自动清理 | 不重放未知提交；先读 version/幂等记录 | `commit_unknown` → 读回表版本、行数/主键/请求 id → 完成、补偿或人工介入；清理 orphan 由资源治理任务负责 |
| 进程崩溃/SIGKILL/重启 | 不可变 manifest/fragment 提供恢复读基础；LSM writer 需 `close_lsm_writers`/drain；自动崩溃恢复范围未由本仓库完整证明 | 不恢复半成品引用/答案；按固定读坐标重新召回 | 持久化意图、版本、索引任务、幂等键和资源句柄；重启扫描连接、进程、临时目录、锁和未完成事务 |
| schema/index 不兼容 | 返回 `Schema`/`InvalidInput`/`IndexNotFound` 等错误；不隐式 cast 破坏数据 | 选择明确降级或失败，记录召回模式 | 装配前做契约/Schema/索引摘要校验，拒绝跨版本旁路读取 |
| 资源释放 | Arrow stream、HTTP response/body、schema cache、index cache、LSM shard writer、临时上传 part 各有 owner | 只持有结果/引用，不持有底层连接 | 成功、失败、超时、取消、崩溃四终态验证无线程/进程/连接/文件/临时对象残留 |

### 14.5 Python/Rust、远程客户端和对象存储边界

```text
Python sync/async API 或其他 SDK
  → 参数/Arrow/错误映射（L4 薄适配）
  → PyO3/napi/JNI binding（L1 受管语言边界）
  → rust/lancedb BaseTable / Query / Database（L1 provider 核心）
  → lance/lance-index/lance-linalg/DataFusion（受管第三方实现）
  → object_store / namespace / REST Cloud（L1 外部协议 provider）
```

- Python `LanceTable` 的同步方法通过 `LOOP.run()` 调用 async 原生对象；它是 API 便利层，不是独立执行引擎。`RemoteTable.to_arrow()`/`to_pandas()` 当前明确不支持 Cloud，不能在平台契约里宣称本地/远程完全对称。
- Rust `BaseTable` 是最接近统一能力 owner 的源码事实；`NativeTable` 与 `RemoteTable` 共享方法形状但能力、错误和一致性不同，映射时必须保留 `NotSupported` 与服务端能力差异。
- namespace client 可提供 location、storage options 和 managed versioning；凭证刷新/对象存储 session 属于 provider 资源，不传给模块。`WrappingObjectStore`/IO tracking/mirroring 是 L1 观察或存储策略，不能成为业务写 owner。
- Python embedding/reranker/provider 配置只通过受控变量引用和 L1 provider；API key、OAuth token、mTLS key 不进入 Schema metadata、日志或检索结果。

### 14.6 L0-L4 验收契约

| 等级 | LanceDB 证据范围 | 平台最低验收 | 当前状态 |
|---|---|---|---|
| **L0 公共契约** | `BaseTable`、Arrow Schema/RecordBatch、query/index/version/error 类型和本地/远程能力差异已核对 | 固定能力 id、Schema/查询/版本/错误/资源字段；冻结唯一存储链与唯一检索 owner；不生成平台实现 | 已完成静态映射 |
| **L1 支持库/provider** | Native/Remote、object store、Arrow、索引、FTS、事务、版本和 retry/timeout 源码路径已核对 | 每个 provider 真实返回、Schema 拒绝、索引等待、事务回滚/未知提交、断线、超时、取消和释放测试；缺依赖不得 skip 伪绿 | 未执行，待工作包 |
| **L2 检索模块** | vector/FTS/hybrid builder、RRF 和 DataFusion/HTTP 查询边界已核对 | 真实写入→建索引→向量/全文/hybrid 检索→过滤/重排/引用；固定版本坐标，部分召回和过期索引有明确策略 | 未执行，待模块工作包 |
| **L3 运行核心** | retry counter、read watermark、cache、LSM drain 和 query/write timeout 机制已核对 | 真实能力调用器、并发/租约/预算、deadline/取消排空、幂等、`commit_unknown` 对账、强杀重启和零残留；不把 future drop 当崩溃恢复 | 未执行，待运行核心联调 |
| **L4 接入/控制面** | Python/TypeScript/Java API、Remote REST、namespace/OAuth 入口已核对 | 冷启动装配、权限/namespace 隔离、本地/远程结果对称性、版本锁、签名制品、回滚和发布门禁；SDK 不能绕过 L2/L3 | 未执行，待接入验收 |

### 14.7 命中、缺口与工作包裁决

| 能力 | 现有底座命中 | 缺口 | 裁决 |
|---|---|---|---|
| Arrow/Schema/表 CRUD/对象存储 | 支持库后端原子能力、文件/资源管理、外部 provider 与统一结果模式 | 尚无向量 Schema/批次/版本坐标的统一中文契约 | **新建向量存储支持库候选**；先登记能力与 provider，不复制 LanceDB 整库 |
| ANN/标量/FTS 索引 | 运行核心 provider 监督、资源预算和现有检索研究可复用 | 索引基线版本、构建状态、召回降级、tokenizer 依赖尚未固化 | **升级索引支持库 + L3 任务监督** |
| vector/FTS/hybrid 检索 | 模块库领域编排、唯一能力调用器、结果/证据基础类型可复用 | 没有唯一向量检索模块、引用/过滤/重排契约 | **新建候选“向量与全文检索模块”**；不得把 LanceDB QueryBuilder 直接当模块 API |
| 事务/版本/branch/restore | 运行核心已有版本、CAS、发布恢复和证据模式；Lance 有不可变 manifest | Lance 提供的是表级提交/版本，不是平台跨资源事务 | **升级存储支持库 + 运行核心恢复**；明确 commit_unknown/补偿 |
| 远程 HTTP/namespace/OAuth | 现有 HTTP、进程、认证和资源监督 provider 模式 | 需要 remote/local 能力矩阵、request id、read watermark、远程 cancel 证据 | **复用 HTTP provider，新增向量存储远程适配** |
| Python/Rust/原生扩展 | 受管独立进程/环境/提供者边界可复用 | 原生 `lancedb._lancedb` 的加载、崩溃隔离和 Python sync cancellation 未实测 | **隔离为 L1 provider**；禁止正式代码直接 import 原生扩展 |
| 多模态 blob/大批量流 | 文件/资源管理和临时目录能力可复用；Arrow stream/分片上传有源码事实 | blob 生命周期、对象孤儿、上传重试幂等和大批次预算未完成验证 | **待核**，先做资源/对账工作包，不并入检索模块 |

装配顺序固定为：

```text
需求登记/能力搜索
  → 冻结 Arrow/Schema/统一结果/版本坐标/资源契约
  → 向量存储支持库（本地 Lance + object store + remote provider）
  → 索引与检索原子能力（vector/scalar/FTS）
  → 向量与全文检索模块（唯一召回、hybrid、重排、引用）
  → 运行核心调用器/租约/deadline/取消/幂等/恢复/证据
  → L4 Python/HTTP/MCP/SDK 薄适配
  → L0 静态 → L1 provider → L2 本地检索链 → L3 故障并发恢复 → L4 接入发布
```

当前核对不创建平台文件、不登记能力、不修改 LanceDB 源码；该节只形成候选底座输入。正式开工必须先完成需求确认、能力搜索、复用/升级/新建裁决、占用租约、消费者验收契约和装配计划。

### 14.8 后续结论、未确认项与验证记录

**吸收：** `BaseTable` 的本地/远程统一形状、Arrow RecordBatch 流、Schema metadata、向量/标量/FTS 索引分工、Lance 不可变版本、branch/time travel、远程 request id/read watermark、分类型 retry、multipart 有界上传和 LSM writer drain。

**升级现有底座：** 运行核心的资源监督、能力调用、版本/CAS、租约、证据、HTTP/进程 provider；公共契约的结果、Schema、版本、错误、取消、资源和一致性字段。不得新增第二套网关、注册表、任务系统或事务恢复器。

**建立候选模块：** 向量与全文检索模块，统一 vector/FTS/hybrid、过滤、RRF/重排、引用、查询版本坐标和降级策略；前提是向量存储支持库能力 owner 先冻结。

**建立候选支持库：** 向量存储支持库，封装 Lance/PyO3/Arrow/object store/remote namespace；一个 LanceDB provider 一个能力 owner，Python/Rust 只是实现边界，不成为上层直连入口。

**不吸收：** LanceDB 的 Python convenience API、远程 REST JSON、本地 DataFusion 计划、具体 ANN 算法实现、模块内存锁、隐式缓存刷新和“表级 commit = 全平台事务”。这些只能作为 provider/适配实现或研究证据。

## 15. 后续补充：通用存储能力映射（源码核对版）

本节把后续从“候选分层”收敛为可装配的通用存储能力清单。核对范围覆盖 `rust/lancedb` 核心、PyO3/Python、napi-rs/TypeScript 和 JNI/Java 入口；Java 当前公开面主要是 namespace client 与 JNI 核心，不能按 Python/Node 的完整表 API 对称假定。

### 15.1 能力闭包与唯一 owner

```text
连接/命名空间
  → 表句柄（本地 Dataset 或远程 HTTP）
  → Schema/Arrow 批次与流
  → 写入、merge、delete/update、版本提交
  → 标量/全文/向量索引
  → 普通/向量/全文/hybrid 查询
  → 版本水位、错误、资源终态
```

| 通用能力 | Rust 权威实现 | 多语言绑定事实 | 平台映射与边界 |
|---|---|---|---|
| 连接、namespace、表生命周期 | `connection.rs`、`database.rs`、`BaseTable`；Native/Remote 共享表能力形状 | Python 同步/异步 DB 与 Remote DB；Node `Connection`/`LocalTable`；Java 以 namespace/JNI facade 为主 | L1 暴露句柄式存储能力；L4 只映射参数和统一结果；句柄必须由 L3 关闭/回收 |
| Schema、metadata、Arrow | `SchemaRef`、`RecordBatchReader`、DataFusion；metadata 保存 column definitions | Python PyArrow/NumPy/Polars 是转换面；Node async iterator/Arrow；Java 不作为公共 Arrow 真相 | L0 固化字段路径、nullable、向量维度、metadata、批次上限；禁止以 pandas/Polars 类型替代 Schema |
| CRUD 与流式写入 | `add_data`、`delete`、`update`、`merge_insert`；partition 先生成未提交 transaction，再统一 commit | Python/Node 提供 builder 与 sync/async 面；Remote 通过 HTTP 映射，能力受服务端协议约束 | L1 负责写入语义和 commit 结果；L3 负责幂等、并发、deadline、未知提交对账；不宣称跨表事务 |
| 版本、branch、time travel | `DatasetConsistencyWrapper`、manifest/fragments、checkout/restore/branch/tag | Python/Node 暴露部分版本接口；Remote 带 branch 与 read watermark | 版本是结果坐标和缓存键的一部分；模块不得直接切换指针或把表提交当平台事务 |
| ANN、标量、FTS 索引 | `create_index.rs`、`index/{vector,scalar}.rs`；算法实现由 `lance-index`/`lance-linalg` 提供 | Python/Node 暴露 builder；Java 不能假定同等索引 API | L1 只封装索引原子能力；L2 选择召回配方；L3 监督 building/ready/failed、超时、重建和预算 |
| 查询与 hybrid | `QueryBase`、DataFusion plan、FTS UDTF、RRF；Native/Remote 分别执行或 pushdown | Python 具有丰富 sync/async 转换；Node 以 async iterator 输出；远程输出能力不完全对称 | L2 唯一持有过滤、召回、重排、去重、引用；SDK 不拼 JSON、不自行合并 vector/FTS |

### 15.2 并发、持久化与资源语义

1. **并发不是语言绑定的锁。** `DatasetConsistencyWrapper` 的互斥只保护本地句柄状态；同表竞争以 Lance commit/版本冲突为准。LSM 的 `ShardWriterCache` 单表缓存一个 shard writer，换 shard 或关闭必须 drain；L3 才能限制队列、并发、租约和取消。
2. **持久化是版本化列式存储。** canonical rows 位于 Lance Dataset 的 manifest/fragments，索引和 permutation 是派生制品；不可变版本支持读回与恢复，但不证明跨表、跨对象存储的 ACID/exactly-once。对象存储可能遗留孤儿 fragment，清理属于资源治理，不属于查询成功条件。
3. **流和大对象必须有界。** `MaxBatchLengthStream`、`TimeoutStream`、上传字节/时间切分、permutation 的 100MB 默认内存与磁盘溢写，构成 provider 侧边界；索引 cache、HNSW/量化训练、FTS 构建仍需 L3 预算 RAM、临时目录、IO 和并发。
4. **取消要区分等待取消与执行取消。** Rust future drop 可以停止等待；Python `LOOP.run()` 返回只说明调用方停止等待，不证明原生写线程已停止；Remote 的 HTTP timeout 也不等于服务端写入已回滚。写入超时/响应丢失统一进入 `commit_unknown`，重启后按版本、幂等键和行统计对账。
5. **资源终态必须可观测。** Arrow reader、HTTP body、连接池、schema/index cache、LSM writer、multipart 临时 part 和溢写目录均要在成功、失败、超时、取消、崩溃路径验证释放；不能以线程锁或 GC 作为释放证据。

### 15.3 异常与跨语言统一结果

Rust `error.rs` 的 `InvalidInput`、`Schema`、`TableNotFound`、`TableAlreadyExists`、`TableCorrupted`、`IndexNotFound`、`EmbeddingFunctionNotFound`、`Timeout`、`JobFailed`、`Http`、`Retry`、`NotSupported` 等是 provider 错误分类，不应原样泄漏为业务异常。统一平台结果至少包含：

```text
success / value / error_code / error_message / retryable
table_id / namespace / branch / requested_version / observed_version
schema_fingerprint / index_fingerprint / request_id / attempt
consistency_mode / resource_state / commit_state
```

跨语言映射只允许在 L1/L4 完成：Python 的异常上下文、Node 的 Promise rejection、Java/JNI 的异常均归一为上述分类；敏感 token、API key、mTLS 私钥和原始 provider 异常不得进入 metadata、日志或结果。`NotSupported` 必须保留，不能因本地 API 存在就假设 Remote 或 Java 支持。

### 15.4 最小验收矩阵

| 验收面 | 必须证明 | 不能用作证明 |
|---|---|---|
| Rust 核心 | 本地表 CRUD、Schema 拒绝、版本读水位、索引 building/ready、查询 timeout、LSM drain | 仅编译或仅 mock builder |
| Python/PyO3 | sync/async 同一结果、原生扩展异常映射、取消后的资源释放、Remote 能力差异 | `LOOP.run()` 返回即视为取消成功 |
| Node/napi | Arrow 批次迭代、Promise 错误、表/索引/查询参数与 Rust 一致 | TypeScript 类型生成成功即视为运行时可用 |
| Java/JNI | 实际公开 facade、namespace/连接关闭和 JNI 异常边界 | 按 Python/Node API 猜测 Java 覆盖范围 |
| 并发/恢复 | 同表冲突、重试幂等、`commit_unknown` 对账、SIGKILL 后无半成品引用和临时资源 | Python 锁、future drop、GC 或一次成功请求 |

后续最终裁决：**新建一个向量存储支持库作为唯一 L1 owner，复用现有运行核心的调用器/租约/资源/证据与 HTTP provider；再由单一 L2 检索模块组合 vector、scalar、FTS 和 hybrid。** LanceDB 的 Rust 核心、多语言绑定、表/索引/查询、持久化、并发、资源和异常均作为该 provider 的受管实现证据，不直接成为平台公共 API，也不创建第二套网关、注册表、任务系统或事务恢复器。

**待核：** 真实索引构建/删除/重建一致性、跨进程并发 commit、对象存储孤儿清理、远程服务端取消、Python 原生扩展崩溃隔离、commit_unknown 对账、Schema 演进与索引迁移、多表事务和生产负载；当前均不得标成 L2-L4 已通过。

当前核对 MCP/验证边界：任务指定目标是 `/Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/80_storage_vector_index/lancedb`。`project_context` 已调用，但实际绑定 `/Users/hekunhua/Documents/Agent/PHP/华世王镞_v3`，MCP 实例为 `project_toolkit`，开工 id 为空，不能作为 LanceDB 身份或代码图证据；随后按要求调用 `codegraph_explore`，目标根无 `.codegraph/`，返回未索引。故当前核对源码事实来自目标根 `AGENTS.md`、既有 `ARCHITECTURE.md`、目标源码/测试路径的只读核对，未冒充错绑代码图结果。仅修改本文件，未运行 LanceDB 构建/测试、未安装依赖、未启动服务、未修改 Git；文档写入成功不等于 L1-L4 通过。
