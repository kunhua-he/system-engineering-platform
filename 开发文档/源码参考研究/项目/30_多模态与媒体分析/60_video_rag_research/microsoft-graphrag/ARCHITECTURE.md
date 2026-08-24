# Microsoft GraphRAG 架构档案

> 建档范围：`/Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/60_video_rag_research/microsoft-graphrag`
>
> 建档性质：后续内部收口、只读源码研究后的架构事实记录。本文只描述当前源码与仓库文档，不把设计意图当作已实现事实；旧细探保留为历史原始记录。
>
> 建档基线：本地 `main` / `14a00ad88fc33cf2b52f4f113f25807556f8e25e`（`Release v3.1.1 (#2458)`，本地时间 `2026-07-17T19:16:53-06:00`）。
>
> 远程核对：`origin/main` 当前指向 `7bb23cc7f32f47cf618a1ae9cca39a6695f434ae`，本地相对远程落后 9 个提交；远程 `packages/graphrag/pyproject.toml` 仍为 `3.1.1`，核心 `PipelineFactory` 工作流定义与本地一致。通过 `http://127.0.0.1:4780` 独立读取了远程 `CHANGELOG.md` 与关键源码快照，未将远程未合入内容写成本地实现事实。

## 1. 项目定位与边界

GraphRAG 是一个以 Python 为主的图增强检索生成系统：把非结构化文档经过切块、LLM/NLP 图谱抽取、关系归并、层级社区发现、社区报告生成和向量化，形成可查询的知识模型；查询侧复用这些索引产物，通过 Basic、Local、Global、DRIFT 四种策略生成带数据引用约束的答案。

项目官方 README 明确将其定位为 “a data pipeline and transformation suite”，并声明代码是方法演示，不是官方支持的 Microsoft 产品；索引可能昂贵，应先从小数据集开始（`README.md:22-36`）。项目入口不是一个长期运行的 Web 服务，而是 CLI、Python indexing API 和 Python query API。

本仓库是一个 uv workspace monorepo。主包为 `packages/graphrag`，外围能力拆分为七个 workspace 包：

- `graphrag-common`：配置/通用类型和工具。
- `graphrag-cache`：LLM 调用缓存。
- `graphrag-chunking`：文本切块。
- `graphrag-input`：输入文件和文档加载。
- `graphrag-storage`：表格与对象存储抽象。
- `graphrag-llm`：completion、embedding、tokenizer 和模型 provider。
- `graphrag-vectors`：向量存储抽象及 LanceDB、Azure AI Search、CosmosDB 等实现。

另有 `unified-search-app/` 独立示例应用，用于多索引目录聚合检索；它不是主 `graphrag` 包的运行时入口。

## 2. 系统边界与主数据流

### 2.1 索引侧

```text
输入文件或 pandas.DataFrame
  -> load_input_documents
  -> create_base_text_units       文档切块，内容寻址 ID
  -> create_final_documents       文档与 TextUnit 关联
  -> extract_graph                LLM 实体/关系抽取（Standard）
     或 extract_graph_nlp         NLP 图抽取（Fast）
  -> summarize_descriptions       归并实体/关系多条描述
  -> finalize_graph               去重、ID、degree 等最终化
  -> extract_covariates           可选 claims
  -> create_communities           hierarchical Leiden 社区层级
  -> create_final_text_units     补齐最终 TextUnit 关联
  -> create_community_reports    LLM 社区报告
     或 create_community_reports_text
  -> generate_text_embeddings     TextUnit/Entity/Report 向量
  -> parquet/配置的 TableProvider + 配置的 VectorStore
```

实际默认管线由 `graphrag.index.workflows.factory.PipelineFactory` 注册（`packages/graphrag/graphrag/index/workflows/factory.py:17-97`）：

- `Standard`：`load_input_documents` + `_standard_workflows`。
- `Fast`：`load_input_documents` + `_fast_workflows`。
- `StandardUpdate`：`load_update_documents` + 标准工作流 + `_update_workflows`。
- `FastUpdate`：`load_update_documents` + 快速工作流 + `_update_workflows`。

索引 API `graphrag.api.index.build_index` 接收 `GraphRagConfig`、索引方法、callbacks、额外上下文和可选的 `input_documents` DataFrame，创建 pipeline 后逐个异步执行 workflow，返回 `list[PipelineRunResult]`（`packages/graphrag/graphrag/api/index.py:29-93`）。

`graphrag.index.run.run_pipeline.run_pipeline` 负责组装 input/output storage、TableProvider、cache 和 pipeline context；标准运行把 DataFrame 写入输出表并跳过输入加载，增量运行则使用时间戳目录、`delta/`、`previous/` 备份并由 update 工作流合并（`packages/graphrag/graphrag/index/run/run_pipeline.py:30-114`）。每个 workflow 结束后会写 `stats.json` 和 `context.json`；异常被包装为带最后 workflow 名称的 `PipelineRunResult(error=...)`（同文件 `117-179`）。

### 2.2 查询侧

查询侧读取索引输出表为 DataFrame，经 `graphrag.query.indexer_adapters` 转成数据模型，再由 `graphrag.query.factory` 组合模型、embedding、tokenizer、向量存储和上下文构建器，得到搜索引擎。

| 方法 | 核心路径 | 适用问题 | 主要过程 |
|---|---|---|---|
| `basic` | `BasicSearch` | 直接找相关原文块 | TextUnit embedding top-k -> 单次 LLM |
| `local` | `LocalSearch` + `LocalSearchMixedContext` | 围绕实体/局部关系问答 | 实体向量召回 -> 社区报告、TextUnit、实体、关系、claims 混合上下文 -> 单次 LLM |
| `global` | `GlobalSearch` + `GlobalCommunityContext` | 整库主题、宏观问题 | 社区报告分批 map -> 解析 points/score -> 排序和 token 截断 -> reduce |
| `drift` | `DRIFTSearch` + `DRIFTSearchContextBuilder` | 多步探索、追问和图式研究 | primer -> `QueryState`/`DriftAction` -> 多轮 LocalSearch -> reduce |

`graphrag.api.query` 对四类查询均提供异步非流式函数和 streaming 函数。Global API 读取 entities/communities/reports；Local 还读取 text_units、relationships、covariates；DRIFT 读取 entities、communities、reports、text_units、relationships；Basic 只读取 text_units（`packages/graphrag/graphrag/api/query.py:62-187,190-318,321-450,453-546`）。

CLI 在 `graphrag.cli.main:app` 注册 `init`、`index`、`update`、`prompt-tune`、`query` 五个命令；`query` 根据 `SearchMethod` 分派到 basic/local/global/drift（`packages/graphrag/graphrag/cli/main.py:24-25,98-137,138-247,249-362,364-482`）。

## 3. 知识模型与数据契约

### 3.1 输入契约

所有内置输入 reader 最终产出 `documents` DataFrame。文档公共字段为：

- `id`：由文本内容 hash 生成的稳定 ID，若结构化输入有 `id` 则可复用。
- `text`：全文。
- `title`：标题或文件名。
- `creation_date`：ISO8601 文件创建时间。
- `raw_data`：结构化 CSV/JSON/JSONL/Parquet 行对象，可用于切块前置元数据。

支持 Plain Text、CSV、JSON、JSONL、Parquet 和 MarkItDown；也可通过 indexing API 直接传入符合上述 schema 的 pandas DataFrame（`docs/index/inputs.md:5-25,27-59`）。`graphrag-input` 通过 `InputReaderFactory` 支持自定义 reader。

### 3.2 最终输出表

默认最终产物为配置的 TableProvider 中的表，文件存储默认对应 parquet。所有表共享 `id`（全局唯一 UUID/标识）和 `human_readable_id`（本次运行内短 ID）概念。最终列顺序由 `packages/graphrag/graphrag/data_model/schemas.py:69-159` 固定。

| 表 | 关键字段 | 语义 |
|---|---|---|
| `documents` | `title`, `text`, `text_unit_ids`, `creation_date`, `raw_data` | 输入文档及其切块关联 |
| `text_units` | `text`, `n_tokens`, `document_id`, `entity_ids`, `relationship_ids`, `covariate_ids` | 用于分析和引用的文本块 |
| `entities` | `title`, `type`, `description`, `text_unit_ids`, `frequency`, `degree` | 从 TextUnit 抽取并汇总的节点 |
| `relationships` | `source`, `target`, `description`, `weight`, `combined_degree`, `text_unit_ids` | 实体之间的边 |
| `communities` | `community`, `level`, `parent`, `children`, `entity_ids`, `relationship_ids`, `text_unit_ids`, `period`, `size` | hierarchical Leiden 社区层级 |
| `community_reports` | `community`, `level`, `title`, `summary`, `full_content`, `rank`, `findings`, `full_content_json` | 社区的 LLM 摘要与发现 |
| `covariates` | `covariate_type`, `type`, `description`, `subject_id`, `object_id`, `status`, `start_date`, `end_date`, `source_text`, `text_unit_id` | 可选 claims/时间性陈述 |

数据模型层使用 Python dataclass：`Document`、`TextUnit`、`Entity`、`Relationship`、`Community`、`CommunityReport`、`Covariate`；对象间主要通过 ID 列表字段关联，而不是 ORM 外键或关系数据库 join。`Entity` 的 `community_ids`、`text_unit_ids`、`rank` 和可扩展 `attributes` 见 `data_model/entity.py:12-38`；`Relationship` 的 `source`、`target`、`weight`、`text_unit_ids` 见 `relationship.py:12-38`；社区层级和成员列表见 `community.py:12-43`；报告模型见 `community_report.py:12-38`。

### 3.3 规范化与身份

`GraphExtractor._process_result` 使用 `<|>` 元组分隔、`##` 记录分隔和 `<|COMPLETE|>` 完成标记，解析 entity/relationship 后通过 `clean_str(...).upper()` 规范化实体、类型、关系端点（`packages/graphrag/graphrag/index/operations/extract_graph/graph_extractor.py:27-35,124-178`）。这意味着标题键及后续图合并对大小写规范化敏感。

`GraphExtractor._process_document` 首次调用 LLM 后可按 `max_gleanings` 追加 `CONTINUE_PROMPT`，并以 `LOOP_PROMPT` 询问是否继续；解析异常调用 error handler 并返回空 DataFrame，而非直接抛出（同文件 `59-122`）。空实体/关系是否终止整条管线由上层 workflow 的校验策略决定，不能仅以 extractor 的容错返回判定索引成功。

## 4. 组件分层与依赖边界

```text
CLI / Python API
  ├─ config (GraphRagConfig, YAML, defaults, Pydantic)
  ├─ index (PipelineFactory, run_pipeline, workflows, operations)
  ├─ query (adapters, context builders, structured search)
  ├─ prompts / prompt_tune
  ├─ data_model
  ├─ logger / callbacks / tokenizer / utils
  └─ workspace packages
       ├─ graphrag-llm       -> LiteLLM, Azure identity, model abstractions
       ├─ graphrag-vectors   -> LanceDB / Azure Search / CosmosDB
       ├─ graphrag-storage   -> file/blob/Cosmos table providers
       ├─ graphrag-cache     -> file/blob/Cosmos-compatible cache providers
       ├─ graphrag-input     -> reader and metadata collection
       ├─ graphrag-chunking   -> token chunker factory
       └─ graphrag-common     -> dotenv/yaml/toml utilities
```

主包 `packages/graphrag/pyproject.toml` 声明 Python `>=3.11,<3.14`，入口脚本为 `graphrag = "graphrag.cli.main:app"`；主依赖包括 Azure client、七个同版本 workspace 包、`graspologic-native>=1.2,<1.3`、`litellm` 的间接能力、`networkx`、`numpy`、`pandas`、`pyarrow`、`pydantic`、`spacy`、`typer` 等（`packages/graphrag/pyproject.toml:24-74`）。根 `pyproject.toml` 用 `uv.workspace.members = ["packages/*"]` 组织 workspace，开发任务包括 ruff、pyright、pytest、notebook、文档和 build（`pyproject.toml:50-107,138-144`）。

项目刻意通过 provider/factory 隔离外部实现：

- `PipelineFactory`：workflow 名到函数、pipeline 名到 workflow 列表。
- `CompletionFactory` / `EmbeddingFactory`：模型 provider。
- `InputReaderFactory`：输入格式。
- `CacheFactory`：缓存后端。
- `TableProviderFactory`：表存储。
- `VectorStoreFactory`：向量库。
- `LoggerFactory`：日志输出。
- `query.factory`：查询引擎装配。

官方架构文档将这些注册点列为扩展边界（`docs/index/architecture.md:30-51`）。注册机制允许自定义名称，也允许覆盖内置实现；因此配置、导入顺序和注册名是运行时行为的一部分。

## 5. 配置与运行时控制面

`GraphRagConfig` 是 Pydantic `BaseModel`，把模型、并发、异步模式、input/output/update storage、chunking、cache、reporting、vector store、workflows、抽取、聚类、embedding、四种 query 配置统一为一棵配置树（`packages/graphrag/graphrag/config/models/graph_rag_config.py:40-251`）。模型验证阶段会：

1. 解析并校验 file storage 的 base directory。
2. 解析 reporting directory。
3. 为 LanceDB 补齐绝对路径。
4. 为核心 embedding 名称补齐 `IndexSchema`。
5. 以 `completion_models` / `embedding_models` 的 ID 查找模型配置。

关键控制点：

- `workflows` 非空时覆盖内置 method 的 workflow 列表。
- `concurrent_requests` 控制模型请求并发；Global/DRIFT 内部另有协程并发控制。
- `chunking.size`、`chunking.overlap`、`prepend_metadata` 控制 TextUnit 构造。
- `extract_claims.enabled` 默认关闭。
- `vector_store.index_schema` 与 embedding 模型维度必须匹配；3.1.1 changelog 明确记录了向量长度不匹配时 fail fast。
- `cache` 用于降低网络错误、重复请求和成本；架构文档说明相同 prompt 与 tuning 参数可命中缓存。
- snapshots、reporting、update_output_storage 影响诊断、审计和增量产物布局。

本地主包固定 `graspologic-native` 在 `1.2.x`：源码注释说明 `1.3.x` 会改变 Leiden 社区数量/层级，从而破坏回归测试和 golden community data，必须在刷新 golden data 时有意升级（`packages/graphrag/pyproject.toml:46-49`）。

## 6. 关键查询语义

### 6.1 Local Search

`query.factory.get_local_search_engine` 组合 chat model、embedding model、tokenizer 和 `LocalSearchMixedContext`。上下文参数包含 `text_unit_prop`、`community_prop`、实体/关系 top-k、对话历史轮数、最大上下文 token 数和向量 key（`packages/graphrag/graphrag/query/factory.py:37-100`）。`LocalSearch.search` 先构建上下文，再将上下文和 response type 填入 system prompt，向 LLM 发起 streaming completion，并在 `SearchResult` 中记录各阶段调用数和 token 统计（`query/structured_search/local_search/search.py:56-144`）。

### 6.2 Global Search

`GlobalSearch` 是 map-reduce：社区报告上下文先按 token 分块，map 阶段并行调用 LLM 并解析 JSON `points`，reduce 阶段过滤 score 为 0 的点、按分数降序排序并截断到 `max_data_tokens`，再生成最终答案。map 解析失败降为 score 0；若所有点均无效且不允许 general knowledge，则返回 `NO_DATA_ANSWER`（`query/structured_search/global_search/search.py:106-214,216-304,306-431`）。

### 6.3 DRIFT Search

`DRIFTSearch` 将查询状态保存在 `QueryState` 中，初次运行先用 `DRIFTPrimer` 生成中间答案和 follow-up queries，再按未完成动作排名逐轮执行 `LocalSearch`，达到 `n_depth` 或无动作后 reduce。动作结果包含 score、answer、follow-ups，并可序列化/恢复；空 query 直接报错（`query/structured_search/drift_search/search.py:37-109,188-311`）。

### 6.4 引用和幻觉控制边界

查询 prompt 统一要求对数据支持的陈述使用 `[Data: ...]` 引用、最多列出 5 个 record id 并用 `+more` 表示其余；同时要求“不知道就说不知道、不要编造”。这是 prompt 层约束，不等同于结构化事实验证或安全过滤器；生产使用仍需对 LLM 输出做业务侧验证。

## 7. 增量索引与持久化语义

增量运行不是数据库事务，而是基于 storage child path 的文件/表产物编排：

1. 根据时间戳创建 update storage 子目录。
2. 将当前输出复制到 `previous/`。
3. 新输入写入 `delta/`。
4. 运行标准或 Fast 的抽取/社区/报告/embedding 工作流。
5. 运行 `update_final_documents`、`update_entities_relationships`、`update_text_units`、`update_covariates`、`update_communities`、`update_community_reports`、`update_text_embeddings`、`update_clean_state`。

该模型保留旧产物快照并通过 update 工作流合并；“增量索引”不是对已有实体的实时事务更新。升级或重跑时必须关注 `period`、community hierarchy、短 ID 和 embedding schema 的兼容性。`CHANGELOG.md` 记录 3.1.0 增加 Native CosmosTableProvider 的 namespace partitioning、transactional batch writes；3.0.0 引入 monorepo restructure；3.0.3 增加多项 streaming 和 TableProvider 能力（`CHANGELOG.md:4-23,46-62,82-97`）。

## 8. 目录地图

```text
microsoft-graphrag/
├── packages/
│   ├── graphrag/                 # 主包：CLI、API、配置、索引、查询、数据模型、prompt
│   │   └── graphrag/
│   │       ├── api/              # build_index、query API
│   │       ├── cli/              # Typer CLI
│   │       ├── config/            # GraphRagConfig、defaults、query/index config
│   │       ├── data_model/        # Document/TextUnit/Entity/... dataclass
│   │       ├── index/             # workflow、operations、run、update、typing
│   │       ├── query/             # adapters、context_builder、structured_search
│   │       ├── prompts/           # index/query prompts
│   │       ├── prompt_tune/       # prompt 自动调优
│   │       ├── graphs/            # graph/community utilities
│   │       ├── logger/ callbacks/ tokenizer/ utils/
│   │       └── schemas.py         # 最终表列契约
│   ├── graphrag-llm/              # completion、embedding、tokenizer、metrics
│   ├── graphrag-storage/          # Storage/Table/TableProvider
│   ├── graphrag-input/            # Text/CSV/JSON/JSONL/Parquet/MarkItDown reader
│   ├── graphrag-chunking/         # chunker 与 token 切块
│   ├── graphrag-vectors/          # VectorStore 与向量后端
│   ├── graphrag-cache/            # Cache 与缓存后端
│   └── graphrag-common/           # 共享配置和基础工具
├── docs/
│   ├── index/                     # architecture、dataflow、inputs、outputs、methods
│   ├── config/                    # 配置说明
│   ├── query/                     # 四种查询说明
│   ├── prompt_tuning/             # prompt tuning
│   └── examples_notebooks/        # API、索引、查询、迁移示例
├── tests/
│   ├── unit/                      # 配置、索引、query、storage、vectors 等单元测试
│   ├── verbs/                     # workflow/operation 级行为测试与 parquet/csv golden 数据
│   ├── integration/               # cache、LLM、logging、storage、vector stores
│   ├── smoke/                     # fixture 级索引 smoke test
│   └── notebook/                  # notebook 执行测试
├── unified-search-app/            # 独立多索引聚合搜索示例
├── scripts/                       # build assets、版本、spellcheck、Azurite 辅助
├── pyproject.toml                 # uv workspace、poe tasks、ruff/pyright/pytest
├── uv.lock                        # 锁定依赖
├── CHANGELOG.md / breaking-changes.md
├── DEVELOPING.md / CONTRIBUTING.md
├── RAI_TRANSPARENCY.md
└── 细探-GraphRAG.md               # 本机既有的详细只读探索记录（本次未改）
```

实盘核对统计：`packages` 485 个文件、`docs` 105 个文件、`tests` 185 个文件、`unified-search-app` 34 个文件；上述计数为本地递归文件计数，不把 `.git` 计入。仓库根当前还有一个既有未跟踪文件 `细探-GraphRAG.md`，本次未删除、未改写。

## 9. 测试与质量门

根 `pyproject.toml` 的主要任务为：

- `test_unit = "pytest ./tests/unit"`
- `test_integration = "pytest ./tests/integration"`
- `test_smoke = "pytest ./tests/smoke"`
- `test_notebook = "pytest -n auto ./tests/notebook"`
- `test_verbs = "pytest ./tests/verbs"`
- `test = coverage run -m pytest ./tests` + coverage report
- `check = ruff format --check` + `ruff check` + `pyright`

测试按 unit、integration、verbs、smoke、notebook 分层。`tests/verbs` 覆盖 `create_base_text_units`、`create_final_documents`、`extract_graph`、`extract_graph_nlp`、`finalize_graph`、`create_communities`、`create_community_reports`、`generate_text_embeddings`、pipeline state 和 update embeddings 等关键环节；`tests/integration` 覆盖存储、LLM、缓存、日志和向量后端；`tests/smoke/test_fixtures.py` 以 fixture 执行完整索引路径。

本次任务禁止安装依赖、启动服务、构建产物和修改测试，因此未运行全量测试。架构结论以源码、仓库文档、测试布局和远程版本核对为依据；没有把“测试文件存在”表述为本次运行通过。

## 10. 资源、错误和安全边界

- LLM/embedding 是外部网络与成本边界；索引实体抽取通常是最昂贵阶段，应小数据试跑并启用 cache。
- TableProvider/`Table` 暴露异步逐行接口，但当前 `ParquetTable` 只是“模拟流式”：首次迭代会把整个 Parquet 读入 DataFrame，写入行先积存在内存并在 `close()` 时一次性写回；只有接口形态是流式，不能把默认 Parquet 路径表述为全链路低内存流式。embedding 仍按 `batch_size`/`batch_max_tokens` 分批。
- Global map 使用并发协程，Local 使用单次上下文构建，DRIFT 使用多轮动作并发；所有路径都受 token budget 和配置 top-k/depth 约束。
- 抽取器通过 error callback 记录单块错误；Global JSON 解析错误会丢弃该批；DRIFT 动作错误会沉底；pipeline 异常保留最后 workflow 名称。
- Azure、LiteLLM、LanceDB、CosmosDB 等 provider 是外部边界；主包通过拆分包和 factory 访问，不把云 SDK 直接散落在查询/索引业务流程中。
- 项目没有发现外部代码执行或插件脚本执行面；但输入文本、LLM prompt 和 LLM 输出仍可能受到数据注入和模型幻觉影响，不能把 prompt 中的“不编造”当作安全保证。
- 数据隐私取决于配置的 LLM/vector/storage provider；部署时应单独审查数据出境、日志、缓存和云端保留策略。

## 11. 当前事实、风险与后续关注点

### 已确认事实

1. 这是 GraphRAG v3.1.1 的 uv monorepo，主运行时是 CLI + Python API，不是内置 Web API 服务。
2. 索引和查询明确分离：索引产物是查询侧的事实输入；查询不会重新构图。
3. Standard/Fast 和 StandardUpdate/FastUpdate 是显式管线变体；可通过 `GraphRagConfig.workflows` 进一步自定义。
4. provider/factory 是主要扩展机制，TableProvider 和 VectorStore 是持久化/检索边界。
5. 知识模型是以 parquet/table 为中心、通过 ID 列表关联的分析产物模型；不是关系数据库 ORM 模型。
6. Global 是 map-reduce，Local 是实体中心混合上下文，DRIFT 是可恢复的动作图式多轮检索。

### 重要风险

- **版本漂移**：本地 pinned commit 比 `origin/main` 落后 9 个提交；升级前应重新核对 CHANGELOG、依赖锁、golden community data 和 API 兼容性，不能只改版本号。
- **Leiden 结果漂移**：`graspologic-native` 1.3.x 会改变社区数量/层级，升级需要有意刷新 golden data，并重新评估查询质量。
- **LLM 输出非确定性**：实体、关系、claims、社区报告都依赖模型输出；缓存能提高幂等性和成本控制，但不能替代质量评估。
- **表契约漂移**：下游依赖固定列名、ID 列表、community level 和 embedding schema；任何字段、短 ID、period 或向量维度变化都可能使既有索引不可查询。
- **增量合并复杂度**：`previous/delta` 文件布局和 update workflows 不是通用事务；中断、重复运行、模型/规则变化需单独验证。
- **中文/多语言质量**：当前抽取 prompt、类型归一化和部分 NLP Fast 路径以英文数据示例为主；中文视频转写、说话人、时间戳等多模态字段不属于本仓库默认知识模型，需要在输入/attributes/自定义 workflow 层适配和验证。
- **查询可解释性边界**：引用规范来自 prompt 和上下文记录；没有看到强制的事实级引用校验器，不能将引用文本视为自动证明。
- **资源成本**：Standard 图抽取、社区报告和 Global map 的 LLM 调用数随数据规模增长；应显式设置并发、缓存、token budget，并建立调用计量。

### 后续发展方向（仅建议，未启动实现）

- 待拍板：将视频切片、ASR 转写、时间戳、说话人和视觉摘要映射为 `Document`/`TextUnit` 的 `raw_data` 或 `attributes`，同时保持核心表契约稳定。
- 待拍板：在不改主包源码的前提下，优先通过 `InputReaderFactory`、`PipelineFactory.register`、自定义 prompts 和 VectorStore provider 接入多模态预处理。
- 待拍板：为增量索引补充“输入内容 hash、模型配置版本、prompt 版本、embedding 版本、community 算法版本”的外部制品清单，支持重放和成本审计。
- 待拍板：针对中文和视频数据建立独立 golden fixtures，分别评估实体/关系召回、社区稳定性、引用覆盖率、时间定位准确率和 LLM 成本。
- 待拍板：若要暴露 HTTP 服务，应在仓库外增加服务适配层，不把当前 CLI/API 误认为已提供生产级鉴权、限流、租户隔离和任务队列。

## 12. 证据索引与本次建档限制

主要证据文件：

- `README.md`：项目定位、官方边界、成本警告、CLI/文档入口。
- `pyproject.toml`：workspace、开发任务、测试和质量工具。
- `packages/graphrag/pyproject.toml`：主包版本、依赖和 `graphrag` 入口。
- `packages/graphrag/graphrag/index/workflows/factory.py`：默认 pipeline 和注册机制。
- `packages/graphrag/graphrag/index/run/run_pipeline.py`：storage、cache、标准/增量运行和状态输出。
- `packages/graphrag/graphrag/api/index.py`：索引 API。
- `packages/graphrag/graphrag/api/query.py`：四类查询 API。
- `packages/graphrag/graphrag/query/factory.py`：查询引擎装配。
- `packages/graphrag/graphrag/query/structured_search/*/search.py`：Local/Global/DRIFT/Basic 语义。
- `packages/graphrag/graphrag/data_model/` 和 `data_model/schemas.py`：对象与最终表列契约。
- `docs/index/architecture.md`、`docs/index/default_dataflow.md`、`docs/index/inputs.md`、`docs/index/outputs.md`：官方架构、流程、输入输出契约。
- `CHANGELOG.md`：版本演进、monorepo 拆分、streaming、provider 和 Cosmos 能力变化。
- `细探-GraphRAG.md`：本机已有的详细探索记录；本次仅交叉核对，未删减或改写。

代码图工具核对结果：专属 `codegraph_explore` 已按要求首轮调用，但目标仓库没有 `.codegraph/` 索引，因此返回不可查询；之后未重复调用，改用目标仓库内置的 Read/Search 与只读 git/远程核对。专属 `project_toolkit` 当前 MCP 根绑定到另一仓库 `/Users/hekunhua/Documents/Agent/PHP/华世王镞_v3`，`development_start` 返回 `MCP_TARGET_PROJECT_MISMATCH`，随后 `code_context/file_operation` 又因服务不可达无法使用；因此本文件仅通过单一目标路径写入，未修改任何其他文件。

本次未安装依赖、未启动服务、未构建、未提交、未修改源码/依赖/测试/配置，也未修改已有 `细探-GraphRAG.md`。

## 13. 旧细探吸收收口（本文件为唯一持续维护的架构事实源）

`细探-GraphRAG.md` 已完整读取，并逐项对照当前 `main` 源码、测试布局和仓库文档。本节把旧细探的事实、线索和不确定性收口到本文件；旧文件**有意保留**，作为历史原始勘探记录，不再作为独立的长期事实源。后续架构更新只改本 `ARCHITECTURE.md`，旧文件不删除、不改写。

| 旧细探内容 | 本文吸收位置 | 裁决 |
|---|---|---|
| 索引/查询两条主流水线、Standard/Fast/Update 变体 | §2、§14.2 | 吸收；以 `PipelineFactory` 当前注册表为准 |
| `Document`/`TextUnit`/图/社区/报告/claims 数据模型与 ID 列表关联 | §3、§14.1 | 吸收；补充输入/最终表契约边界 |
| gleaning、分隔符解析、实体大写规范化 | §3.3、§14.3 | 吸收；明确异常会被 error handler 转为空表，不把 prompt 约束当验证器 |
| Global map-reduce、Local 混合上下文、DRIFT 动作图、Basic 向量检索 | §2.2、§6、§14.4 | 吸收；补充真实 API 入口与失败语义 |
| 配置默认值、factory/provider 扩展、向量维度和成本控制 | §4、§5、§14.1 | 吸收；当前源码中的 `GraphRagConfig` 是 Pydantic 配置模型，不沿用旧文档“dataclass 树”的泛化说法 |
| cache key 版本化、流式 Table、并发/预算 | §10、§14.5 | 吸收；补充正常关闭与异常关闭缺口 |
| 中文/视频/多模态适配、远程版本漂移、Leiden 漂移 | §11、§15 | 吸收为风险/待核，不宣称已实现视频语义字段 |
| “空实体/空关系必然 raise”以及“错误路径都已清理”之类强结论 | §14.6、§15 | 不吸收为实现事实；当前可证据化的是 extractor 返回空 DataFrame、pipeline 捕获 `Exception` 后产出错误结果，以及部分线程池/Table 的关闭路径 |
| 底座可借鉴点、旁路线索和提示词原文 | §11、§12、§16 | 吸收为研究结论/参考索引，不改变本项目源码边界 |

## 14. 深度事实表

### 14.1 契约表：公开入口、输入输出、所有权和验证边界

| 契约/入口 | 输入与输出 | 所有权、错误、可重试、取消/幂等 | 证据 |
|---|---|---|---|
| `graphrag.api.index.build_index` | 输入 `GraphRagConfig`、`IndexingMethod`、`callbacks`、`additional_context`、可选 `input_documents`；输出 `list[PipelineRunResult]` | 入口创建 pipeline 并消费 `run_pipeline`；workflow 异常作为 `PipelineRunResult.error` 返回而非重新抛出；没有全局事务、任务幂等键或 deadline 契约；`is_update_run` 通过方法名选择 update 版本 | `packages/graphrag/graphrag/api/index.py:29-98` |
| `PipelineFactory`/`WorkflowFunction` | `config` + `PipelineRunContext` → `WorkflowFunctionOutput(result, stop)`；正式表/制品必须由 workflow 写入 context storage | 注册表是进程级 class state；未知 workflow 名在创建时会失败；`stop` 只控制后续 workflow，不是回滚；不声明跨进程版本兼容 | `index/workflows/factory.py:17-48,51-97`; `index/typing/workflow.py:14-28` |
| `Storage`/`TableProvider`/`Table` | Storage 提供 `get/set/has/delete/clear/child/keys`；TableProvider 提供 DataFrame 读写、`list/open/child`；Table 提供异步逐行读写、`length/has/close` | Table 的 async context manager 在退出时 `close()`；Provider 的 `child` 是命名空间边界，但默认实现可返回 self；`run_pipeline` 直接使用 provider/DataFrame，不提供统一事务或 finally 关闭契约 | `graphrag-storage/graphrag_storage/storage.py:13-134`; `tables/table_provider.py:14-121`; `tables/table.py:16-125` |
| 四类 query API | `global/local/drift/basic` 接收配置和已加载 DataFrame；异步 API 返回 `(response, context_data)`，streaming API 返回 async generator | `@validate_call` 做入口参数校验；DRIFT 空 query 明确 `ValueError`；LLM/向量异常通常向调用方传播或由具体搜索阶段降级；无 HTTP 鉴权、租户、限流或持久任务队列契约 | `graphrag/api/query.py:62-546`; `query/structured_search/drift_search/search.py:188-213` |
| `BaseSearch`/`SearchResult` | query + 可选 conversation history → response、context records/text、耗时、LLM calls/tokens 分类统计 | 统计字段是观测结果，不是答案正确性或引用真实性证明；streaming 只保证 chunk 生成接口，不声明客户端断线后的服务端取消 | `query/structured_search/base.py:28-93` |
| `VectorStore` | `VectorStoreDocument(id, vector, data, dates)`；`connect/create_index/load_documents/similarity_search/search_by_id` | `vector_size` 是配置契约，时间字段会展开；相似度结果只给 score/文档，不验证语义引用；具体后端的连接、索引和删除语义由 provider 实现 | `graphrag-vectors/graphrag_vectors/vector_store.py:25-195` |
| `LLMCompletion`/middleware | completion sync/async 或 stream；可带 structured response、cache、metrics、rate limiter、retry | LiteLLM provider 是外部调用边界；structured response 不支持 streaming；retry 只对可捕获异常重试，不等于端到端超时/幂等；cache 命中不等于模型输出已通过事实校验 | `graphrag-llm/graphrag_llm/completion/completion.py:34-161`; `completion/lite_llm_completion.py:45-208` |

### 14.2 真实对接调用链（不是模块概览）

```text
CLI `graphrag index` / Python `build_index`
  -> `_get_method` + `PipelineFactory.create_pipeline`
  -> `run_pipeline`
  -> `create_storage` + `create_table_provider` + `create_cache`
  -> `create_run_context`
  -> 每个 `(name, workflow_function)`：`workflow_start`
  -> workflow 读取/写入 `PipelineRunContext.output_table_provider`
  -> `WorkflowProfiler` + `workflow_end`
  -> `PipelineRunResult` + `stats.json/context.json`
  -> 下一 workflow，或 `stop`，或捕获 `Exception` 后返回 error result
```

| 链路 | 调用方 → 门面 → 路由/编排 → provider → 结果投影 | 真实证据 |
|---|---|---|
| 完整索引 | CLI/API → `build_index` → `_get_method`/`PipelineFactory.create_pipeline` → `run_pipeline` 建立 storage/table/cache/context → workflow 序列 → `PipelineRunResult` | `api/index.py:60-93`; `index/run/run_pipeline.py:39-114,117-179`; `index/workflows/factory.py:40-48` |
| 标准索引 | `load_input_documents` → `create_base_text_units` → `create_final_documents` → `extract_graph` → `finalize_graph` → `extract_covariates` → `create_communities` → `create_final_text_units` → `create_community_reports` → `generate_text_embeddings` | `index/workflows/factory.py:51-61` |
| 快速索引 | 与标准入口相同，但 `extract_graph_nlp` → `prune_graph`，报告走 `create_community_reports_text` | `index/workflows/factory.py:63-72` |
| 增量索引 | `load_update_documents`/直接 DataFrame → timestamp child → `previous` 复制 + `delta` 写入 → 标准/Fast 产物 → update workflows 合并 | `index/run/run_pipeline.py:54-90`; `factory.py:74-97` |
| Local | `api.local_search_streaming` → `read_indexer_*` → `get_embedding_store(entity_description)`/`get_local_search_engine` → `LocalSearchMixedContext` → LLM stream | `api/query.py:258-318` |
| Global | `api.global_search_streaming` → reports/entities adapter → `get_global_search_engine` → context chunks → 并行 map → score 排序/截断 → reduce stream | `api/query.py:126-187`; `query/structured_search/global_search/search.py:106-140,159-214` |
| DRIFT | `api.drift_search_streaming` → 两个 embedding store + reports/entities adapter → `DRIFTSearch` → primer → `QueryState` actions → LocalSearch actions → reduce | `api/query.py:386-450`; `query/structured_search/drift_search/search.py:63-109,188-213` |
| Basic | `api.basic_search_streaming` → text unit adapter + text-unit embedding store → `BasicSearch` → LLM stream | `api/query.py:504-546` |

### 14.3 关键小节点明细

| 节点 | 前置条件 | 状态/读写对象 | 并发 | 失败分支与恢复 | 证据 |
|---|---|---|---|---|---|
| `create_base_text_units` | documents 已可读、chunking/tokenizer 可用 | 写 `text_units`；内容 hash 形成稳定 ID；更新 workflow state | 按 workflow/表流式处理 | 输入/切块失败需看 workflow error；无跨 workflow rollback | workflow 测试 `tests/verbs/test_create_base_text_units.py`；调用序列 `factory.py:52-61` |
| `GraphExtractor.__call__` | LLM completion 可用、prompt/entity types 已注入 | 读文本，写 entities/relationships DataFrame；名称和端点大写规范化 | 单文档异步；gleaning 最多按配置追加 | 任意 `Exception` 调 error handler 并返回空表；不能据此证明整索引安全跳过 | `index/operations/extract_graph/graph_extractor.py:38-83` |
| `PipelineFactory.create_pipeline` | workflow 名已注册或 config 覆盖正确 | 读取 class-level registry，生成有序 `(name, function)` | 进程内顺序执行 | 缺名在列表构造处失败；没有版本/签名校验门 | `factory.py:17-48` |
| `_run_pipeline` | context/storage/cache 已创建 | 写 `stats.json/context.json`；每步 yield result；`context.state` 持久化 | workflow 顺序执行 | 捕获 `Exception`，记录 `last_workflow` 并 yield error；此前已写表不会自动回滚 | `run_pipeline.py:117-179` |
| `GlobalSearch.stream_search` | reports context 可按 token 分块、model 可调用 | map response 列表、callback context、reduce 输出 | `asyncio.gather`，实例 semaphore 在单批调用逻辑中控制；实现仍需 provider 配置 | map JSON 解析失败降为无效点；无有效点且不允许通用知识返回 `NO_DATA_ANSWER`；reduce 异常不等于可恢复任务 | `global_search/search.py:106-140,216-...` |
| `DRIFTSearch.search` | query 非空、primer 返回中间答案和 follow-ups | `QueryState`/`DriftAction` 图、每轮 action 结果、最终 reduce | `tqdm_asyncio.gather` 并行动作 | 空 query/primer shape 错误抛出；单动作降级语义需以 action 实现和运行证据再确认；无持久化 checkpoint 自动提交 | `drift_search/search.py:111-186,188-213` |
| `Table.__aexit__`/线程池 cleanup | 调用方确实使用 context manager 或正常退出 runner | flush/close Table；线程、队列、response handler | 线程池 `concurrency`；队列可无限或 queue_limit | normal path join；runner 对任意异常未统一 `_cleanup`，KeyboardInterrupt 只 set event 后 `sys.exit` | `graphrag-storage/.../tables/table.py:93-125`; `graphrag-llm/.../completion_thread_runner.py:181-243`; `embedding_thread_runner.py:154-216` |

### 14.4 资源生命周期与残留责任

| 资源 | 创建/持有 | 正常释放 | 失败、超时、取消、崩溃 | 当前证据与缺口 |
|---|---|---|---|---|
| 输入/输出 `Storage`、`TableProvider` | `run_pipeline` 的 `create_storage/create_table_provider`，放入 `PipelineRunContext` | provider 本身无统一 context-manager；由实现/进程结束回收 | pipeline 异常没有统一 close；宿主崩溃可留下半写文件或旧 `context.json` | `run_pipeline.py:39-49,82-107`; 需 provider-specific 实测 |
| `Table` reader/writer | `TableProvider.open`，异步迭代/写行 | 使用 `async with` 才保证 `__aexit__ -> close()` | 若调用方未进入 context，异常/取消可能不 flush；文件 provider 的临时文件/原子替换未在当前核对实测 | `tables/table.py:16-125`; 现有接口声明强于 pipeline 的调用约束 |
| DataFrame 与表缓冲 | `read_dataframe/write_dataframe`、各 workflow 中间 DataFrame | Python 引用释放；workflow 自身决定写入时机 | 大表读取和 `_copy_previous_output` 明确会整表读入内存；无总内存预算/取消回滚 | `run_pipeline.py:182-189`; 与 Table 流式抽象并存，不能概括为全链路流式 |
| LLM/embedding HTTP 会话 | LiteLLM middleware/provider；completion/embedding thread runner 可包线程池 | provider 自己关闭/请求结束；线程 runner 正常路径发送 sentinel、join worker、结束 handler | runner 任意异常路径不保证 `_cleanup`；异步取消不在 `except KeyboardInterrupt` 中；进程崩溃只能由 OS/provider 回收 | `completion_thread_runner.py:181-243`; `embedding_thread_runner.py:154-216`; no end-to-end crash probe |
| 线程、队列、信号 | runner 创建 `threading.Event`、worker threads、input/output Queue | normal `_cleanup` 逐线程 sentinel + join，再结束 handler | queue_limit=0 可无界；KeyboardInterrupt 直接 `sys.exit(1)`；阻塞 provider 可能延长 join；无强制 join deadline | 同上；这是资源/取消风险，不宣称已修复 |
| cache | `create_cache(config.cache)`，可绑定 Storage child/LLM middleware | provider-specific set/get；无统一 close | cache 写失败可能影响请求或被 provider 处理；部分写/旧 key 由实现决定；版本键只能避免部分错误命中 | `run_pipeline.py:45`; `graphrag-llm/cache/create_cache_key.py`；需后端实测 |
| 向量库索引 | query factory/get_embedding_store 或 index embedding workflow provider | provider-specific connection/index lifecycle | 维度不匹配会 fail fast；查询断线/崩溃、删除/更新语义和残留索引未统一验证 | `graphrag-vectors/graphrag_vectors/vector_store.py:56-195`; `tests/integration/vector_stores/` |
| `previous/delta` 更新制品 | update storage timestamp、child namespaces、复制 previous、写 delta | 成功后由后续更新策略决定保留/清理；代码未提供原子激活指针 | 中途崩溃可能同时保留 previous/delta 与不完整结果；没有事务提交标记或恢复扫描契约 | `run_pipeline.py:54-90,182-189`; 增量不是事务 |
| `stats.json/context.json` | `_dump_*` 在启动、每 workflow 后、成功结束时写 | 最后成功写入即为可见状态 | `CancelledError`/宿主崩溃可能无最终状态；旧 state 可能与部分表不一致；没有 manifest 校验 | `run_pipeline.py:117-179` |

### 14.5 失败、超时、取消、崩溃矩阵

| 场景 | 当前实现可确认的行为 | 能否安全重试/恢复 | 证据等级 |
|---|---|---|---|
| 非法配置/未知 method/workflow | Pydantic/config 与 factory/CLI 处抛出校验或查找错误 | 启动前修正后重试；无统一错误码契约 | L1 静态源码 |
| 单文档 LLM 抽取异常 | `GraphExtractor.__call__` 回调记录后返回空 entities/relationships | 可能继续；是否导致空图终止要看上层 workflow 数据校验，不能默认安全 | L1；无当前核对运行 |
| provider 网络/模型异常 | middleware 可配置 retry、rate limit、cache；线程 worker 将 `Exception` 放入 response queue | 依赖异常类型和 provider；retry 不是幂等/事务，可能产生重复外部请求 | L1 |
| Global map JSON 解析失败 | map 结果转为空/低分点，后续排序过滤；全无效且禁用通用知识时返回 `NO_DATA_ANSWER` | 查询可重新执行，但可能重新消耗 LLM；无请求 id 幂等 | L1 |
| DRIFT primer/动作 shape 错误 | primer 结果缺字段会 `ValueError/RuntimeError`；空 query `ValueError` | 调用方修正输入或重试；没有已提交 QueryState 的持久恢复链 | L1 |
| workflow 普通异常 | `_run_pipeline` 捕获 `Exception`，yield 带 `last_workflow/error` 的 `PipelineRunResult`；之前表写入保留 | **不安全地宣称可重试**：无事务、manifest、幂等 run id；需人工清理/隔离后重跑 | L1 |
| 超时 | Retry 配置只定义次数/退避；Global/DRIFT 有并发与 token/depth 上限；未发现 pipeline-wide deadline 或统一 cancel token | 不能证明超时会中断所有 HTTP、线程、写入和下游 action；需 provider-specific timeout 实测 | L1/未验证 |
| 主动取消/客户端断流 | `_run_pipeline` 只捕获 `Exception`；Python 3.11 的 `CancelledError` 属于 `BaseException`，因此不会转成 error result；线程 runner 只显式处理 `KeyboardInterrupt` | 取消后的状态、线程、缓存、部分文件未形成统一恢复契约 | L1 静态推导；未做运行探针 |
| 进程崩溃/强杀 | 无 finally/启动租约/提交标记可证明完整收口；外部 OS 负责进程资源回收，文件/远程表可能已部分写入 | 只能依赖 previous/delta 和人工目录审计；没有内置崩溃恢复扫描器 | L1 |
| 重复运行/重复事件 | TextUnit 有内容寻址倾向，cache 有版本键；全 pipeline 无统一 idempotency key，update timestamp 以秒生成 | 局部可重用不等于全局幂等；同秒 update、模型/提示词变更和部分写需专门验证 | L1 |

### 14.6 防假绿验证分级（L0–L4）

| 等级 | 证明什么 | 本仓库对应证据 | 当前核对状态/不能宣称 |
|---|---|---|---|
| L0 | 路径、源码、文档、注册表存在 | `read_file/search_files` 读取旧细探、本文、README、pyproject、关键 Python 源码；codegraph 明确返回“无 `.codegraph/`” | 已完成静态取证；不是行为通过 |
| L1 | 纯单元/契约行为可执行 | `tests/unit`、`tests/verbs` 覆盖配置、factory、抽取、社区、存储、向量等；如 `tests/verbs/test_pipeline_state.py` 只证明 state passthrough | 当前核对未安装依赖、未运行；测试文件存在不等于 pass |
| L2 | 本地真实 provider/文件产物可运行 | `tests/integration/vector_stores/test_lancedb.py` 创建临时 LanceDB、插入/检索/清理；smoke fixtures 检查 output/stats/artifacts/NaN | 当前核对未运行；不能宣称 LanceDB/Parquet 全链路绿 |
| L3 | CLI 子进程端到端索引/查询与制品断言 | `tests/smoke/test_fixtures.py` 用 `uv run poe index/query`、检查退出码、`stats.json` workflow 集合、行数范围、NaN，并清理 output/cache | 代码存在但未执行；没有当前核对退出码 |
| L4 | 真实外部 LLM、Azure/Cosmos/Azurite、网络、限流/断线/取消/崩溃恢复 | `tests/integration` 和 smoke 配置提供部分入口，但需外部服务/密钥/运行环境 | 未验证；这是最大证据缺口 |

## 15. 未验证项、吸收/不吸收裁决与剩余风险

### 未验证项

1. 未运行 `uv sync`、pytest、ruff、pyright、CLI index/query；依赖和本机 Python 环境是否满足未验证。
2. 未对真实 LLM provider、embedding provider、cache backend、LanceDB/Azure Search/Cosmos/Azurite 做端到端调用；网络错误、限流、重试上限和响应格式只做静态追踪。
3. 未注入 timeout、`asyncio.CancelledError`、KeyboardInterrupt、进程 SIGKILL、worker hang、磁盘满、部分 Parquet 写入或远程存储断线；资源表中的异常路径是源码推导，不是运行证明。
4. 未验证 update 在重复 timestamp、重复输入、不同模型/prompt/vector schema、previous/delta 部分残留下的重启恢复和一致性。
5. 未建立内容 hash、model/prompt/embedding/Leiden 版本的统一制品 manifest，也未验证 query 引用是否逐条存在于事实表。
6. codegraph 结果为**无代码图**：目标仓库从目标根向上没有 `.codegraph/`，因此无法读取其证据可信度/最近成功验证；没有冒充代码图结果。首轮 `project_context` 返回的项目根是错误绑定的 `/Users/hekunhua/Documents/Agent/PHP/华世王镞_v3`，与目标仓库不一致；其结果不作为本项目证据。

### 吸收/不吸收裁决

- **吸收**：旧细探中能由当前源码路径、测试路径和仓库文档交叉支撑的索引/查询流程、数据模型、provider 边界、提示词约束、成本和版本风险，已写入 §2–§14。
- **不吸收为实现事实**：旧细探中的宣传性/推断性质量结论、未运行的“通过”、把抽取空表直接等同于整条管线必然终止、把 prompt 引用约束等同事实校验、把流式接口等同取消安全、把 previous/delta 等同事务恢复。
- **待核**：多模态视频字段映射、外部 provider 真实语义、全链路清理、增量崩溃恢复、引用校验、中文语料质量和远程 9 提交差异；这些只能在后续针对性运行/版本复核后升级结论。

### 剩余风险排序

- **P0 / 阻断性运行风险**：没有全局事务/提交标记/幂等 run id，普通异常或强杀可能留下部分表与 `context.json/stats.json`；当前不适合把一次失败后的自动重跑宣称为安全。
- **P0 / 资源风险**：线程 runner 对任意异常/异步取消没有统一 cleanup；无界 queue、provider 阻塞和强杀场景可能造成等待或部分请求不可观测。
- **重要**：LLM 输出、社区划分和报告是概率性产物；cache 只保证部分重复请求复用，不证明语义正确性、引用真实性或跨版本兼容。
- **重要**：表列、ID 列表、embedding 维度、community hierarchy 和 `graspologic-native` 版本构成隐式数据契约；远程领先 9 提交，升级需重做 golden/fixture/兼容复核。
- **重要**：本仓库不是 HTTP 服务，缺少认证、租户隔离、审计、队列、限流和服务级超时；视频/ASR/说话人/时间戳需要仓库外适配与独立评测。

## 16. 验证记录与后续最小验收命令

当前核对实际执行的只读验证：

| 命令/动作 | 退出码/结果 | 用途 |
|---|---:|---|
| `git status --short --untracked-files=all` | 0 | 确认 `ARCHITECTURE.md` 与 `细探-GraphRAG.md` 均为既有未跟踪文档，未触及源码 |
| `git rev-parse HEAD`、`git branch --show-current`、`git log -1` | 0 | 记录 `main` / `14a00ad...` / `Release v3.1.1` 基线 |
| `wc -l ARCHITECTURE.md 细探-GraphRAG.md` | 0 | 记录收口前文档规模 |
| `search_files/read_file` | 成功 | 完整读取旧细探，并读取本文、README、根/主包 `pyproject.toml`、索引/查询/storage/cache/vector/LLM 关键源码与测试 |
| `codegraph_explore` | 无代码图（工具明确返回） | 目标仓库无 `.codegraph/`；未绕过、未冒充 |

建议后续在具备依赖和外部服务的隔离 fixture 根目录运行，并把每次退出码、测试数和残留清理回写本文：

```text
PYTHONDONTWRITEBYTECODE=1 uv run pytest tests/unit tests/verbs
PYTHONDONTWRITEBYTECODE=1 uv run pytest tests/integration/vector_stores/test_lancedb.py
PYTHONDONTWRITEBYTECODE=1 uv run pytest tests/smoke/test_fixtures.py
uv run poe check
```

这些是后续验收命令，不是当前核对已通过的命令；在未实际运行前不得写成绿色结论。

## 17. 单一文档规则

- 当前唯一需要持续维护的架构文档：`ARCHITECTURE.md`。
- `细探-GraphRAG.md` 保留为历史原始细探，本次未删除、未改写；它不再承载后续增量事实。
- 源码、测试、配置、依赖、Git 均未修改；本次只补充本文件的深度架构事实、证据边界和验证裁决。

## 18. 后续通用底座映射：GraphRAG → 支持库、知识图谱模块、运行核心

> 本节是后续“底座映射与裁决”，不是把 GraphRAG 源码复制进生产平台，也没有启动任何底座实现。所有“应映射/建议建立”均是装配输入；当前项目事实仍以 §2–§17 和源码证据为准。

### 18.1 三层职责裁决

| GraphRAG 能力 | 支持库（可复用的原子能力） | 知识图谱模块（领域流程 owner） | 运行核心（统一生命周期 owner） | 后续裁决 |
|---|---|---|---|---|
| `PipelineFactory`、Standard/Fast/Update workflow | 有序工作流接口、能力注册表、运行状态/事件类型 | 声明 `load/chunk/extract/merge/community/report/embed/update` 的领域步骤 | 根据方法、版本和配置装配并顺序驱动；统一停止、错误、指标和证据 | **吸收为“注册表 + 装配计划”模式**；不让每个业务复制一套 pipeline |
| `Storage` / `TableProvider` / `Table` | `artifact-storage`、命名空间、表/行流式读写、schema/manifest 校验 | 只通过表契约读写 `documents/text_units/entities/relationships/...` | 创建 provider、绑定 run namespace、控制提交/激活、记录状态 | **升级支持库边界**；当前接口没有事务，不能直接当事实账本 |
| 实体、关系、claims、社区、报告 | 内容 hash、稳定 ID、ID 映射、版本化数据契约 | 唯一 owner：抽取、规范化、去重、关系合并、社区层级、报告和图内引用 | 只负责调用、超时/取消、计量和结果投影，不解释图语义 | **吸收为知识图谱模块**；图语义不下沉到通用存储 |
| `VectorStore`、entity/text/report embeddings | 向量索引适配器、embedding schema/维度检查、候选标准化 | 决定哪些图对象建立向量、如何映射候选到实体/文本/报告 | 注入 embedding provider、预算、超时、连接和资源关闭 | **吸收现有向量能力**；维度/模型版本必须进入制品 manifest |
| 全文/词法检索 | 新的 `fulltext-search` 原子能力（BM25/倒排/字段过滤、证据 ID） | 负责把全文候选纳入局部上下文和证据排序 | 负责 provider 路由、限流、取消、计量 | **待新建能力**：本仓库 `VectorStore` 只有向量相似度/按 ID/过滤接口，未发现 BM25、倒排或 `full_text` 查询入口；不能伪称已支持全文 |
| Basic/Local/Global/DRIFT | 统一检索结果、token/成本预算、证据引用结构 | 持有查询策略：Basic 原文块，Local 图邻域混合上下文，Global 社区报告 map-reduce，DRIFT 动作图多轮探索 | 装配 query engine、模型/embedding/tokenizer，暴露统一请求、取消和观测契约 | **吸收为一个 `knowledge.retrieve` 门面下的策略**；禁止四条旁路各自读库/翻译错误 |
| completion/embedding thread runner | 有界并发、请求队列、取消 token、join deadline、worker 状态 | 只提交图抽取/报告/embedding 任务，不管理线程 | 统一 worker 生命周期、失败分类、泄漏检测和运行证据 | **升级支持库**：当前 `Queue(0)` 默认无界，cleanup 仅覆盖正常退出/`KeyboardInterrupt`，任意异常和异步取消没有统一收口 |
| cache / `_CACHE_VERSION = 4` | 可插拔 cache、命名空间、版本化 key、命中/未命中指标 | 为抽取、摘要、报告、embedding 声明领域输入摘要和语义 scope | 注入 cache、权限/TTL/容量/失败策略；cache 不是事实写 owner | **吸收为成本/幂等辅助能力**；不能以命中缓存证明图事实正确或索引已提交 |
| `previous/delta` update workflows | run ledger、staging namespace、manifest、原子激活指针、恢复/清理 | 计算 entity/relationship/community/text-unit 映射并生成新图产物 | 负责 run lease、提交、失败隔离、重试和崩溃恢复 | **只吸收 merge 算法，不吸收其非事务落盘语义**；当前 `previous/delta` 是备份+合并布局，不是 commit protocol |

### 18.2 唯一知识链路（唯一 owner、唯一入口、唯一证据方向）

底座落点必须收敛为一条链；`fulltext` 在未实现前不能另开隐式侧链：

```text
输入制品/视频适配层
  → knowledge.ingest（文档、切片、ASR、时间戳、说话人统一输入契约）
  → knowledge.index（运行核心创建 run；知识图谱模块按 workflow 编排）
      → chunk / text-unit identity（支持库：内容 hash + schema）
      → graph.extract（知识图谱模块：Entity/Relationship/Covariate）
      → graph.normalize-merge（规范化、去重、ID mapping）
      → graph.community-report（Leiden 层级 + 社区报告）
      → knowledge.artifact.commit（支持库：manifest/校验/提交指针）
  → knowledge.retrieve（唯一查询门面）
      → candidate fan-out：vector（现有） + fulltext（待建） + graph-neighbor（图模块）
      → candidate normalize/dedupe/evidence-link（支持库 + 图模块）
      → basic/local/global/drift strategy（知识图谱模块）
      → model completion（运行核心 provider/预算/取消）
      → answer + evidence + metrics + run_id（运行核心统一结果）
```

固定规则：

1. `knowledge.index` 是唯一建图入口；CLI、SDK、后续视频模块只能适配输入和配置，不能直写实体表、向量库或社区报告。
2. `knowledge.retrieve` 是唯一检索入口；Basic/Local/Global/DRIFT 是策略参数，不是四套公开网关。向量、全文和图邻域都必须归一为同一 `Candidate`/`EvidenceRef` 契约。
3. 图模块是实体、关系、社区、报告和 ID 映射的唯一写 owner；支持库只保存、校验和索引，不自行合并图语义。
4. 运行核心是 run、workflow、provider、取消、错误、指标和证据的唯一 owner；业务模块不得自建线程池、缓存、重试和状态文件。
5. 每个回答只能沿“候选 → 证据 ID → 上下文 → 模型输出”回溯；prompt 中的 `[Data: ...]` 仍需由底座逐条校验，不能把提示词当事实证明。

### 18.3 现有实现如何归图：索引、存储、图和查询的真实边界

| 阶段 | 当前源码行为 | 归图后的支持库/模块边界 | 不能越界的结论 |
|---|---|---|---|
| workflow 装配 | `PipelineFactory.create_pipeline` 从 `config.workflows` 或 class-level pipeline registry 生成有序函数列表；默认四种方法见 `index/workflows/factory.py:17-97` | 运行核心的 `WorkflowRegistry` + 图模块的 workflow descriptor | registry 没有版本/签名/能力契约校验；注册成功不等于可运行 |
| run context | `run_pipeline` 创建 input/output storage、table provider、cache，读取 `context.json`，每步写 `stats.json/context.json`；见 `index/run/run_pipeline.py:30-179` | 运行核心的 `RunContext`、状态机和证据事件 | `Exception` 才被包装成 `PipelineRunResult.error`；不等于事务回滚或取消安全 |
| 表和行 | `Storage` 提供 key 操作和 `child()`；`TableProvider` 提供 DataFrame 与 `open()`；`Table` 提供 async row iteration、`write`、`close` 和 `__aexit__`；见 `graphrag-storage/.../storage.py:13-141`、`tables/table_provider.py:14-121`、`tables/table.py:16-125` | 支持库分离 key/blob、table snapshot、streaming row、manifest | `Table.__aexit__` 能保证调用 `close()`，但主 pipeline 的 DataFrame 写入路径没有统一事务边界 |
| 图合并 | update 读取 previous/delta，按 title 合并实体并输出 `entity_id_mapping`；关系按 source/target 聚合，重算 degree；见 `index/workflows/update_entities_relationships.py:61-119`、`index/update/entities.py:14-74`、`relationships.py:14-86` | 图模块的 `GraphMergePlan`：输入快照 + delta → 显式映射 → 新图制品 | 当前实体同名合并、关系端点合并依赖字段；不能推导成通用数据库 upsert/事务 |
| 增量 text units | delta 的 `entity_ids` 按 mapping 替换，再从旧 `human_readable_id` 续号并 concat；见 `index/workflows/update_text_units.py:45-95` | 图模块负责引用重写；支持库负责 immutable artifact 和校验 | 续号/concat 不是全局幂等；空旧表、重复运行、模型变更需单独契约 |
| 向量检索 | `VectorStore` 提供 `similarity_search_by_vector/text`、过滤、`search_by_id`、`count/remove/update`；见 `graphrag-vectors/.../vector_store.py:25-216` | 支持库 `VectorIndexProvider`；图模块绑定 entity/text/report 的 evidence key | 向量结果只有相似度候选，不证明引用关系、答案正确或全文命中 |
| Local/Global/DRIFT | `query.factory` 注入模型、embedding、tokenizer、表数据和 vector store；Local 混合图/文本/社区，Global 使用社区报告和并发 map/reduce，DRIFT 使用动作状态；见 `query/factory.py:37-227` 及各 `structured_search/*` | 图模块 `RetrievalStrategy`；运行核心统一 model/timeout/callback/metrics | Global 的 map JSON 降级、DRIFT 动作沉底是局部容错，不是任务级恢复 |

### 18.4 事务、幂等、部分写入：底座必须补的提交协议

当前源码明确是“先写产物、最后写状态”，`previous/delta` 也只是命名空间和复制备份：`run_pipeline.py:54-90,182-189` 没有 run lease、manifest 校验、原子激活指针或跨表 commit。后续映射因此采用以下**待实现的公共契约**，不是对 GraphRAG 当前能力的夸大：

```text
RunCreated(run_id, input_digest, schema/model/prompt/embedding/graph versions)
  → Staging(run_id): tables/indices/cache evidence written only under staging namespace
  → Validate: required tables, schema, row counts, ID uniqueness, references, vector dimension,
              manifest checksums, graph/community mappings, evidence index consistency
  → Prepared(manifest_digest)
  → Commit: conditional write of one activation pointer for the complete manifest
  → Active(run_id, manifest_digest)
  → Cleanup: old staging/previous according to retention policy
```

最低字段与规则：

- **幂等键**：`run_id` 不能只用当前秒时间戳；至少由 `dataset/input_digest + workflow_name + config_digest + schema_version + model/prompt/embedding/graph_algorithm_versions` 组成。相同键重试只能复用同一 manifest 或返回冲突，不能静默追加第二份事实。
- **部分写入**：任何 table/vector/cache 写入都只能进入 staging；单表 `close()` 或 DataFrame 写成功不代表 run 可见。只有所有必需表和索引通过 manifest 校验后才切换 activation pointer。
- **事务边界**：若 provider 没有跨表事务，使用“不可变 staging + 单指针条件提交”模拟可审计原子可见性；不能声称底层 Parquet、Blob、Cosmos 等天然具备跨表事务。
- **previous/delta**：`previous` 只读快照，`delta` 只读本次输入/中间结果；合并产物写新 staging，不能原地覆盖 active。保留 `entity_id_mapping`、`community_id_mapping` 和输入/版本摘要，支持回放。
- **重复事件**：workflow 事件和 provider 回调都带 `run_id/workflow/request_id`；状态更新使用版本或条件写，重复回调不得使计数、human-readable id 或结果重复增长。
- **重试**：可重试只针对同一幂等键和未 Active 的 run；Active 后重试应读回 manifest，不能再次调用昂贵 LLM。cache 命中只减少调用，不替代 manifest/提交检查。

### 18.5 取消、超时、线程池与崩溃恢复矩阵

| 终态 | 当前 GraphRAG 可确认行为 | 底座必补契约 | 验收证据 |
|---|---|---|---|
| 正常完成 | thread runner 发送 sentinel、逐线程 `join`，pipeline 最后写 stats/context；`completion_thread_runner.py:219-243` | `Active` 指针提交后才对查询可见；记录全部 worker/request 终态 | 读回 manifest、指针、表计数、向量计数、线程/队列为零 |
| 业务失败 | `_run_pipeline` 捕获 `Exception` 并返回 error result；此前写入不会自动回滚；`run_pipeline.py:126-157` | 错误 run 标记 `Failed`，active 指针不变，staging 隔离，可按幂等键安全重试 | 注入 provider error，验证旧 active 可查询、失败 staging 不被查询读取 |
| 主动取消/超时 | runner 只在 `KeyboardInterrupt` 分支 set event + `sys.exit(1)`；`asyncio.CancelledError` 不属于 `Exception`，pipeline 没有统一 cancel token/finally；见 `completion_thread_runner.py:232-243`、`run_pipeline.py:153-157` | 取消信号贯穿 workflow、LLM、embedding、Table、Vector；有 deadline、非阻塞 join、`Cancelled` 状态和 staging 清理/保留策略 | 取消抽取、embedding、Global map、DRIFT action，确认请求停止、指针不变、无 worker 残留 |
| 宿主崩溃/SIGKILL | OS 回收进程/线程，但已写文件或远端表可能半成品；没有启动租约、提交标记、恢复扫描器 | lease + heartbeat + `Prepared/Active` manifest；启动时扫描 stale run，只认 Active 指针，孤儿 staging 可清理或隔离 | 强杀后重启，读回 active 仍完整；stale staging 不进入查询；清理无锁/临时文件/端口 |
| 队列背压 | completion/embedding runner 的 `Queue(queue_limit)`，默认 `0` 表示无限；见对应 runner `:115-187`、`:88-160` | 默认有界队列、拒绝/等待策略、队列深度指标、每请求 deadline，禁止无界内存增长 | 超限输入时 producer 有界阻塞/拒绝，内存和队列回落 |

当前线程实现的资源责任必须归入支持库：`request_id` 是关联标识但不是幂等提交键；`_cleanup()` 对 worker 使用无 deadline 的循环 join，阻塞 provider 可能无限等待；因此不能把现有线程池直接作为运行核心的“取消已完成”证据。

### 18.6 L0–L4 验收映射（后续不制造假绿）

| 等级 | 对底座映射的最低证明 | 本项目已有证据 | 当前核对结论 |
|---|---|---|---|
| **L0 结构/静态** | 源码路径、注册表、输入输出表、唯一链路和缺口可定位 | 已读取 workflow/storage/table/vector/query/thread/cache/update 源码；`codegraph_explore` 明确返回目标仓库无 `.codegraph/` | **完成**；是事实建档，不是运行通过 |
| **L1 契约/单元** | workflow 顺序、ID mapping、表 schema、cache key、向量维度、取消/错误类型有可执行断言 | `tests/unit`、`tests/verbs` 覆盖相关模块，但当前核对未运行 | **未验证**；测试文件存在不等于通过 |
| **L2 本地真实 provider** | 临时文件/Parquet/Table、Memory/Json cache、LanceDB 或 mock vector、失败后旧快照仍可读 | 仓库有 storage/vector/cache/integration fixture；当前核对未安装依赖、未执行 | **未验证**；尤其缺 partial write/cancel probe |
| **L3 本地端到端** | CLI/API 完整 index → commit → vector/fulltext/graph retrieve；断言 manifest、证据 ID、stats、退出码和残留 | `tests/smoke/test_fixtures.py` 提供历史测试入口；当前无当前核对退出码，且全文能力没有内置实现 | **未验证/全文缺口**；不能宣称完整链路绿 |
| **L4 外部与故障** | Azure/Cosmos/真实 LLM、限流/断网、重复 run、SIGKILL 重启、stale lease、取消清理和跨 provider 一致性 | 集成目录提供部分 provider 入口；无当前核对外部服务和故障注入证据 | **未验证，P0 风险保留** |

### 18.7 后续落点、装配计划与最终裁决

| 工作包 | owner | 交付契约 | 当前状态 |
|---|---|---|---|
| `artifact-storage` + manifest/activation | 支持库 | `Storage/Table` streaming、schema/ID/checksum、staging、conditional commit、恢复扫描 | **待建**；GraphRAG 现有 Storage/Table 只能作为接口线索 |
| `bounded-worker-runtime` | 支持库 + 运行核心 | completion/embedding 统一 worker、bounded queue、request/deadline/cancel、join deadline、泄漏证据 | **升级**；现有 runner 不能直接收口取消/崩溃 |
| `versioned-cache` | 支持库 | scope/key/version/TTL、命中计量、失败策略、不可冒充事实 | **吸收并升级**；现有 `_CACHE_VERSION=4` 是局部实现 |
| `knowledge-graph-index` | 知识图谱模块 | 唯一建图入口、实体/关系/claims/社区/报告、增量 mapping、证据链接 | **吸收流程，重做提交边界** |
| `knowledge-retrieval` | 知识图谱模块 | 统一 `Candidate/EvidenceRef`，Basic/Local/Global/DRIFT 策略，vector + graph；fulltext 插件契约 | **吸收现有四策略；全文待建** |
| `knowledge-run-core` | 运行核心 | run/workflow/provider/callback/metrics/lease/commit/cancel/recovery 的唯一入口 | **待装配**；不能由项目 CLI 直接充当生产核心 |

**结论归类：**

- **吸收**：GraphRAG 的 workflow registry、索引/查询分离、Table 流式接口、内容/ID mapping、Global/Local/DRIFT 策略、版本化 cache key、调用计量和 Standard/Fast 成本档位。
- **升级**：Storage/Table 为 staging+manifest+activation 提供者；thread runner 为 bounded/cancel/join 提供者；previous/delta 为可回放 merge 输入，而不是事务实现。
- **新建/待核**：统一全文检索能力、候选/证据归一化、run 幂等键、跨表提交协议、stale-run 恢复和取消/崩溃故障测试。
- **不吸收**：GraphRAG 直接写生产库、模块各自建立向量/全文旁路、以 timestamp 作为唯一幂等键、以 cache 命中或 prompt 引用代替事实校验、以 `PipelineRunResult.error` 代替回滚。

本节不改变仓库源码、配置、依赖和测试；它把后续研究结果限定为“底座升级输入”，后续只有在目标平台能力搜索、契约评审、占用租约和 L0–L4 验收完成后，才可进入实现。

## 19. 后续源码收口补充：从索引到检索的可执行事实

> 本节是后续源码收口的补充，不是新实现说明。以下结论来自目标仓库当前文件的直接阅读；当前核对没有调用 MCP、Hermes、远程服务或测试服务，也没有修改除本文件之外的文件。

### 19.1 索引、实体图与社区摘要的实际边界

GraphRAG 的索引不是一个“读文档后直接写图”的单步函数，而是由 `PipelineFactory` 生成的有序 workflow 生成器。默认 Standard 顺序为：

```text
load_input_documents
  → create_base_text_units
  → create_final_documents
  → extract_graph
  → finalize_graph
  → extract_covariates
  → create_communities
  → create_final_text_units
  → create_community_reports
  → generate_text_embeddings
```

Fast 将 LLM 图抽取换成 `extract_graph_nlp`，随后执行 `prune_graph`，并使用文本社区报告；Update 在对应 Standard/Fast 链路后追加一组 update workflows。`config.workflows` 非空时直接替换默认列表，因此配置拥有改变顺序、跳过步骤或引用自定义 workflow 的能力；`PipelineFactory` 本身只按名称查表，没有对输入输出 schema、依赖顺序或版本签名做静态验证。

实体图形成过程可拆为四个事实阶段：

1. `GraphExtractor` 按 TextUnit 调用 completion，使用记录/字段分隔符解析实体和关系；gleaning 通过追加 completion 请求补充抽取结果。
2. 实体和关系描述在后续 operation 中归并；实体按规范化标题聚合，关系按规范化 source/target 聚合，并重新计算 frequency、degree、weight 等派生字段。
3. `finalize_graph` 为最终实体/关系生成稳定标识和引用列表；TextUnit、Entity、Relationship 之间仍是 ID 列表关联，不是 ORM 外键级联。
4. `extract_covariates` 是可选的 claims 路径，默认关闭；claims 不是关系边的替代物，而是带 subject/object、状态和时间字段的独立事实表。

社区阶段先把关系表转成无向、去重的 edge list，可选保留 stable largest connected component，然后调用 `hierarchical_leiden`。输出包含 level、cluster、parent 和节点列表；社区层级不是 LLM 生成的，而是图算法产物。社区报告阶段按层级构造上下文：先按 level 组织父子社区和本地上下文，再在每个 level 内通过 `derive_from_rows` 并发生成报告；一个社区报告缺失或抽取异常会记录日志并返回 `None`，不会自动回滚已生成的其他层级报告。报告字段包括 title、summary、findings、rating/rank、原始全文及结构化 JSON，既是 Global 检索的主要输入，也是 Local/DRIFT 的摘要上下文。

因此，“实体图完成”至少应同时检查实体、关系、社区层级、TextUnit 引用和报告覆盖率；单独存在 `entities.parquet` 或 `community_reports.parquet` 不能证明图索引完整。

### 19.2 检索装配、候选上下文与回答生成

查询入口读取已落盘的 DataFrame，再经 adapter 转换为 `Entity`、`Relationship`、`Community`、`CommunityReport`、`TextUnit` 和 `Covariate` 对象；它不会重新执行索引 workflow。`query.factory` 负责按策略创建 completion、embedding、tokenizer、VectorStore 和 context builder，四种策略的差异如下：

| 策略 | 候选来源与上下文 | LLM 阶段 | 失败/截断语义 |
|---|---|---|---|
| Basic | TextUnit 向量相似度 top-k | 一次 completion | 无命中时由上下文构造器和 prompt 决定；不做图扩展 |
| Local | 查询向量映射实体，再按匹配实体选择社区报告、实体、关系、claims、TextUnit | 一次 completion/stream | `community_prop + text_unit_prop > 1` 直接 ValueError；其余内容按 token 比例截断 |
| Global | 社区报告按 token 分块 | 并行 map，再 reduce | map JSON 解析失败转为 score 0；全部无效时返回 `NO_DATA_ANSWER` |
| DRIFT | primer 产生 QueryState/动作，动作反复调用局部上下文 | 多轮 LocalSearch，再 reduce | 空 query 或 primer shape 错误抛出；没有自动持久 checkpoint |

Local context 的排序不是简单的向量 top-k：实体向量召回后，社区按匹配实体数和 rank 排序；实体、关系、claims 和 TextUnit 分别进入预算分配的上下文段。conversation history 会先占用 token 预算，再按 `community_prop`、`text_unit_prop` 和剩余 local proportion 分配。Global 的 `asyncio.gather` 创建所有 map coroutine，实例 semaphore 在单批模型调用处限制并发；它不是任务队列，也不提供跨批次的持久重试。

所有策略的 `SearchResult` 都可带 context records、context text、completion 时间、LLM 调用数和 prompt/output token 统计。统计是观测数据，不是引用真实性证明。prompt 要求使用 `[Data: ...]` 引用并在缺乏证据时回答不知道，但源码没有看到对最终回答逐条解析、校验 record id 是否存在或阻止幻觉的强制验证器。

### 19.3 LLM、embedding、缓存和 provider 路由

LLM 侧由 completion/embedding factory 创建 provider，再叠加 middleware。当前源码可确认的横切能力包括：

- retry：按异常分类和配置的次数/退避策略重试；不提供索引级事务，也不保证外部请求幂等。
- rate limiting：按配置的滑动窗口限制请求速率；它是进程内调用控制，不是跨实例租户配额。
- cache：通过版本化 cache key 复用相同输入附近的 completion/embedding 结果；命中只减少调用，不证明模型结果正确或当前索引已提交。
- metrics/logging/request count：记录调用耗时、token、请求数和错误，供 callback/metrics store 输出；指标缺失不会自动使 pipeline 失败。
- structured response：社区报告、抽取等路径可以要求结构化结果；源码明确 streaming 与 structured response 不同时使用。

Embedding operation 以 `batch_size` 和 `batch_max_tokens` 切分输入，并按 `batch_size * num_threads` 缓冲后调用 `run_embed_text`；结果写入 VectorStore，必要时同时写 embedding 输出表。`None` 向量会被跳过并记录 warning，但函数返回值仍按输入 buffer 长度累计，因此“处理行数”不能直接等同于“成功写入向量数”。VectorStore 的公共契约提供建索引、批量装载、向量相似度、按 ID 查询、计数、删除和更新；它没有全文倒排/BM25 语义，也没有统一的跨表提交接口。

### 19.4 存储、批处理和任务模型

存储层有两条相关但不同的抽象：`Storage` 负责 blob/key、child namespace、存在性和清理；`TableProvider` 负责 DataFrame 表和 `open()`；`Table` 负责异步逐行迭代、逐行写入、length/has 和 close。File、Blob、Cosmos 等 provider 由 factory 按配置创建，表 provider 的 child 用于增量运行的命名空间隔离。

`Table` 的异步接口看起来是流式的，但默认 `ParquetTable` 在第一次迭代时把整个 parquet 读入 DataFrame，逐行写入也先积存在 `_write_rows`，只有 `close()` 才一次性序列化并写回。因此：

- workflow 若使用 `async with table`，退出时会调用 `close()`；脱离 context manager 的异常路径可能丢失尚未 flush 的写入。
- parquet 默认路径不是低内存全链路流式；`read_dataframe`、复制 previous 以及许多 DataFrame operation 都会整表占用内存。
- embedding 的批处理限制了模型请求批次和单次 token 量，但不限制所有中间 DataFrame、Parquet 读入和向量索引的总内存。

GraphRAG 源码没有独立的 task queue、scheduler、worker lease 或任务数据库。这里的“任务”是 workflow、异步 coroutine、`derive_from_rows` 的并发行处理和 LLM thread runner request，而不是可由外部系统领取/恢复的持久任务。`PipelineRunResult` 只是逐 workflow 的结果投影，字段为 workflow、result、state、error；它没有 run id、attempt、提交状态、重试次数或取消原因。callbacks manager 只广播 pipeline/workflow start/end、progress 和 error，也不承担任务持久化。

### 19.5 资源生命周期与失败收口

资源责任不能只看正常路径：

| 资源/阶段 | 正常路径 | 源码可确认的缺口 |
|---|---|---|
| Storage/TableProvider | 由 `run_pipeline` 创建并放入 context；Table 可由 async context 关闭 | provider 没有统一 context manager；pipeline 没有 finally 统一关闭所有 provider |
| Parquet Table | `close()` flush 缓冲并释放 DataFrame 引用 | 异常、取消或未使用 `async with` 时可能不 flush；写入不是跨表事务 |
| completion/embedding runner | sentinel、worker join、response handler sentinel | `Queue(0)` 表示无界；普通异常和 `CancelledError` 不进入统一 cleanup；join 无 deadline，provider 阻塞可无限等待 |
| LLM/embedding 外部请求 | middleware/provider 负责单次调用、retry、cache 和 metrics | 没有 pipeline-wide deadline/cancel token；retry 可能重复外部调用 |
| update previous/delta | timestamp child 隔离新结果并复制 previous | 没有 manifest、prepared/active 标记或原子激活指针；强杀后不能由源码证明恢复一致 |
| stats/context | 启动、每个 workflow 后和成功结束时写入 | 部分表可能已写而状态未写完；旧状态可能和当前部分产物不一致 |

`run_pipeline._run_pipeline` 只捕获 `Exception`，在捕获后 yield 一个带 error 的 `PipelineRunResult`；此前已经写入的表不会自动删除或回滚。Python 3.11 的 `asyncio.CancelledError` 属于 `BaseException`，因此不能把它等同于普通 workflow error。线程 runner 对 `KeyboardInterrupt` 设置退出事件并 `sys.exit(1)`，但这不是统一的取消协议；其 `_cleanup()` 循环 join 没有最大等待时间。

### 19.6 失败、重试与恢复裁决

| 事件 | 当前源码行为 | 可否仅凭源码宣称安全恢复 |
|---|---|---|
| 配置/未知 workflow 错误 | 启动或创建 pipeline 时抛出 | 修正配置后重新启动；无统一错误码 |
| 单 TextUnit 抽取失败 | error handler 记录，抽取器返回空结果 | 否；需检查上层是否允许空图/空边继续 |
| 社区报告失败 | 单社区返回 `None`，其他社区可继续 | 否；报告覆盖率和下游 Global 质量需额外检查 |
| embedding 返回 None | 跳过该向量并 warning | 否；输入行数与向量行数可能不一致 |
| provider/LLM 异常 | middleware 可能 retry；线程响应可携带 Exception | 否；没有跨 workflow 事务和幂等 run key |
| Global map 解析失败 | 当前批次 score 0；全无效时 canned no-data | 查询可重试，但可能重复消耗模型；不是任务恢复 |
| workflow 普通异常 | 返回 error result，已写产物保留 | 不安全自动重跑；需隔离/清理并重新核验 |
| 取消、超时、SIGKILL | 没有统一 finally、lease、恢复扫描 | 只能依赖 provider/操作系统回收；不可证明产物一致 |

最终裁决：GraphRAG 可以作为“有序索引运算 + 多策略查询”的源码参考，但不能把 `PipelineRunResult.error` 当作回滚，把 cache/retry 当作幂等，把 async interface 当作低内存流式，把 callback 当作任务系统，或把 prompt 引用格式当作事实校验。若底座要复用该模式，必须在其外增加 run identity、staging manifest、schema/reference/vector 校验、单指针提交、bounded queue、取消传播、join deadline、stale-run 扫描和可重放的失败制品。

### 19.7 当前核对收口的证据与限制

当前核对直接核对的关键源码包括：`index/workflows/factory.py`、`index/run/run_pipeline.py`、`index/operations/cluster_graph.py`、`index/operations/summarize_communities/summarize_communities.py`、`index/operations/embed_text/embed_text.py`、`query/factory.py`、Local/Global/DRIFT/Basic structured search、`graphrag_llm` 的 completion/embedding middleware 与 thread runner、`graphrag-storage` 的 Table/ParquetTable、`graphrag-vectors` 的 VectorStore 以及 callbacks/typing 文件。

当前核对未安装依赖、未启动服务、未运行 pytest/CLI、未注入网络故障、取消、超时、磁盘满、SIGKILL 或真实 LLM/provider。因而本文新增结论均为 L0 静态源码事实和由源码直接推导的风险；不存在当前核对 L1–L4 行为通过记录。唯一修改文件仍为根 `ARCHITECTURE.md`。

## 代码地图现状复核（2026-08-22）

文中早期“目标仓库没有 `.codegraph`”记录对应旧快照，现已过期。当前目标根 `/Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/60_video_rag_research/microsoft-graphrag` 存在独立 `.codegraph/`；`codegraph status` 退出码为 0，返回 610 files、5,797 nodes、12,653 edges。索引只用于源码导航，未把索引状态提升为 GraphRAG pipeline、provider 或故障注入运行证据。
