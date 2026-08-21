# llama_index 架构建档

> 首轮全量架构建档；本文是目标项目根目录的唯一正式架构文档。
> 说明、结论、风险和未确认项使用中文；源码路径、类名、函数名、字段名、命令和包名保留原文。

## 1. 项目身份与证据边界

- **项目名**：`llama_index`（GitHub `run-llama/llama_index`）。
- **本地根目录**：`~/Documents/Agent/github 源码参考/30_多模态与媒体分析/65_rag_frameworks/llama_index`。
- **项目形态**：Python monorepo；核心框架、观测包、工具包和大量独立 integration package 同仓维护。
- **项目定位**：面向 LLM 应用的 data framework，主链路是数据读取 → 文档/节点变换 → 索引 → 检索 → 响应合成；在此之上提供 agent、chat、workflow、memory、evaluation、tools 和多模态能力。
- **当前核对允许修改**：仅新增/更新本文；没有修改源码、依赖、测试、配置、Git 历史或运行产物。
- **规则文件检查**：目标目录内未发现 `AGENTS.md`、`CLAUDE.md`。
- **代码地图证据**：目标项目没有 `.codegraph/`，`codegraph_explore` 明确返回未建立索引，因此当前核对不把代码图结果冒充为有效证据。
- **MCP 证据异常**：首轮 `project_context` 返回并绑定了无关项目 `华世王镞_v3`（根目录 `~/Documents/Agent/PHP/华世王镞_v3`），其项目身份、地图和定位结果均不适用于本项目；本文件以下结论改由目标目录的本地读取和 Git 命令建立。
- **旧细探吸收**：已人工读取并对照此前细粒度研究稿；其中关于 core 分层、索引/检索/合成、存储、观测、VectorStore 契约、Settings、CLI 和集成解耦的内容已吸收到本文，后续正式维护只更新本文。

## 2. Git 基线与远程新鲜度

现场 Git 读取结果：

- 当前分支：`main`，跟踪 `origin/main`。
- 本地 `HEAD`：`7359b1acc74563f715d4463ace39fb4dc73d79af`。
- 本地最新提交时间：`2026-07-22T01:15:31+02:00`。
- 本地最新提交：`Add GPT-5.6 models to supported OpenAI models (#22385)`。
- 远程地址：`https://github.com/run-llama/llama_index.git`。
- `git ls-remote origin` 当前返回：
  - `HEAD` / `refs/heads/main`：`d8021225eb7e7b276d5ceb476b0a4650240f27f8`。
  - `refs/remotes/origin/HEAD`：`3fc6b0e0457d58ef8fbed619f4d2e01df228ab69`。
- **新鲜度结论**：远程 `main` 已不同于本地 `HEAD`，本地工作树不是远程最新源码；当前核对未 `fetch`、未 `pull`、未创建快照或 worktree，故没有把远程新提交的实现内容写入本文。
- 工作树状态：当前核对新增正式文档 `ARCHITECTURE.md`；未修改源码、依赖、测试或配置。

## 3. 规模盘点（现场递归统计）

统计口径是目标根目录下递归匹配文件名；计数包含各 integration 的测试、示例和附属文件，不等同于运行时已安装包数量。

| 项目 | 现场数量 | 说明 |
|---|---:|---|
| 顶层目录 | 9 | `.git`、`.github`、`docs`、`llama-dev`、core、instrumentation、integrations、utils、`scripts` |
| 根目录文件 | 17 | 含 README、许可证、Makefile、根 `pyproject.toml`、`uv.lock` 等 |
| `pyproject.toml` | 635 | 根包、core、instrumentation、utils、`llama-dev` 与 integration 包 |
| integration `pyproject.toml` | 621 | `llama-index-integrations` 递归统计 |
| `uv.lock` | 619 | 根锁文件及大量独立 package 锁文件 |
| Python 文件 | 3,832 | 递归统计 |
| 测试相关 Python 文件 | 1,620 | 路径含 `test` 或文件名以 `test_` 开头 |
| Markdown 文件 | 1,809 | 含各包 README、文档和历史资料 |

主要代码量按顶层目录递归统计：`llama-index-core` 734 个 `.py`，`llama-index-instrumentation` 21 个，`llama-index-utils` 16 个，`llama-index-integrations` 3,031 个，`llama-dev` 23 个，`docs` 4 个。

当前 integration 类别目录共 27 类：`agent`、`callbacks`、`embeddings`、`evaluation`、`extractors`、`graph_rag`、`graph_stores`、`indices`、`ingestion`、`llms`、`memory`、`node_parser`、`observability`、`output_parsers`、`postprocessor`、`program`、`protocols`、`question_gen`、`readers`、`response_synthesizers`、`retrievers`、`selectors`、`sparse_embeddings`、`storage`、`tools`、`vector_stores`、`voice_agents`。

## 4. 总体分层与真实主流程

```text
┌──────────────────────────────────────────────────────────────────────┐
│ 使用方 / 业务应用                                                     │
│ from llama_index.core import VectorStoreIndex, SimpleDirectoryReader  │
│ from llama_index.llms.openai import OpenAI                            │
└──────────────────────────────┬───────────────────────────────────────┘
                               │ 配置、读取、建索引、query/chat/agent
┌──────────────────────────────▼───────────────────────────────────────┐
│ llama-index-core                                                    │
│ schema / Settings / readers / ingestion / indices / retrievers       │
│ query_engine / response_synthesizers / storage / vector_stores       │
│ prompts / tools / workflow / memory / evaluation / callbacks         │
└──────────────┬───────────────────────────────┬───────────────────────┘
               │ 契约依赖                         │ 观测事件与 span
┌──────────────▼──────────────────┐   ┌─────────▼─────────────────────┐
│ llama-index-integrations         │   │ llama-index-instrumentation   │
│ llms / embeddings / readers      │   │ Dispatcher / Event / Span    │
│ vector_stores / storage / tools  │   │ handler 链与上下文传播        │
│ 每包独立 pyproject、独立发布      │   └───────────────────────────────┘
└──────────────┬──────────────────┘
               │ 只通过公开 core 契约接入
┌──────────────▼──────────────────┐
│ llama-index-utils                │ azure / huggingface / oracleai / qianfan │
└─────────────────────────────────┘

输入文件/资源
   │
   ▼
SimpleDirectoryReader.load_data()
   │ Document[]
   ▼
Settings.transformations / run_transformations()
   │ BaseNode[]（默认由 Settings.node_parser → SentenceSplitter 提供）
   ▼
BaseIndex.from_documents()
   ├─ docstore.set_document_hash()
   ├─ BaseIndex.__init__() 建立 StorageContext、callback trace
   ├─ docstore.add_documents()
   └─ 子类 _build_index_from_nodes()
        └─ VectorStoreIndex：embed_nodes（默认批次 2048）→ vector_store.add()
                                  → IndexDict / docstore（由 stores_text 决定）
   │
   ▼
index.as_retriever() → VectorIndexRetriever
   │ QueryBundle → VectorStoreQuery → vector_store.query()
   │ stores_text=False 或非 text 节点时回 docstore 补全
   ▼
RetrieverQueryEngine._query()
   ├─ retrieve()
   ├─ node postprocessors
   └─ response_synthesizer.synthesize()
        └─ get_response_synthesizer(response_mode)
             └─ PromptHelper 按 token 预算 repack/truncate
                  → LLM / structured program / streaming response
```

## 5. 目录地图与职责

### 5.1 根目录

- `README.md`：对外定位、安装方式、core/integration 命名空间、入门样例、`StorageContext.persist()` 与加载示例。
- `pyproject.toml`：发行包 `llama-index`，版本 `0.14.23`，Hatch 构建；依赖 `llama-index-core`、OpenAI embedding/LLM、`nltk`。
- `uv.lock`：根项目锁定依赖。
- `Makefile`：`format`、`lint`、`test`、`test-core`、`test-integrations` 及文档 watch 命令。
- `.github/workflows/`：单元测试、包构建、lint、core typecheck、发布、子包发布、文档同步等工作流。
- `docs/`：文档站点配置与内容；`docs.config.mjs` 提供站点配置。
- `scripts/`：仓库级脚本。
- `llama-dev/`：仓库专用开发/测试/发布自动化 CLI，不是业务运行时的一部分。

### 5.2 `llama-index-core`

核心包 `llama-index-core` 版本 `0.14.23`，源码在 `llama-index-core/llama_index/core/`，包 README 明确其职责是 LLM 应用和 RAG 的基础抽象：LLM、Vector Store、Embedding、Storage、Callable 等。核心包不绑定某一个具体 LLM 或向量数据库。

主要子目录：

- `schema.py`：`BaseComponent`、`TransformComponent`、`BaseNode`、`Document`、`TextNode`、`ImageNode`、`IndexNode`、`NodeWithScore`、`QueryBundle`、节点关系、元数据模式和多模态类型。
- `settings.py`：`_Settings` 与单例 `Settings`，统一管理 LLM、embedding、tokenizer、node parser、prompt helper、callback manager、transformations。
- `readers/`：`BaseReader`、`SimpleDirectoryReader` 以及文件/字符串/JSON 等读取器。
- `ingestion/`：`IngestionPipeline`、`run_transformations`、缓存和 docstore 策略。
- `indices/`：`BaseIndex` 和具体索引族；包括 `VectorStoreIndex`、`TreeIndex`、`SummaryIndex`、`KeywordTableIndex`、`KnowledgeGraphIndex`、`PropertyGraphIndex`、`SQLStructStoreIndex`、`PandasIndex`、`DocumentSummaryIndex`、`MultiModalVectorStoreIndex` 等。
- `indices/registry.py`：`INDEX_STRUCT_TYPE_TO_INDEX_CLASS`，把 `IndexStructType` 映射到索引类，加载持久化索引时使用。
- `retrievers/` 与 `indices/*/retrievers/`：检索器及递归对象检索、向量检索、自动检索等。
- `query_engine/`：`BaseQueryEngine`、`RetrieverQueryEngine`、router、sub-question、citation、SQL 等查询引擎。
- `response_synthesizers/`：`Refine`、`CompactAndRefine`、`TreeSummarize`、`Accumulate`、`Generation`、`NoText`、`ContextOnly` 等响应合成器。
- `prompts/` 与 `indices/prompt_helper.py`：模板选择、chat/text 双提示词、token 预算、重打包和截断。
- `storage/`：docstore、index store、KV store、chat store、`StorageContext`。
- `vector_stores/`：`VectorStore` Protocol、`BasePydanticVectorStore`、查询/过滤器模型、`SimpleVectorStore`。
- `graph_stores/`：简单图存储、属性图存储和抽象接口。
- `callbacks/`、`instrumentation/`：旧式 callback 与 core 侧观测接入。
- `tools/`、`agent/`、`chat_engine/`、`memory/`、`workflow/`、`evaluation/`：从 RAG 基础设施向 agentic application 的上层能力。
- `command_line/`：当前文件明确标注 deprecated；CLI 已拆到独立 `llama-index-cli` 包，本文目标仓库内没有单独的该包目录。
- `core/_static/`：发行包携带的 NLTK、tiktoken cache；发布流程还对这些构建资产生成 provenance attestation。

### 5.3 `llama-index-instrumentation`

- 版本：`0.5.0`。
- 源码布局：`src/llama_index_instrumentation/`，与 core 独立发布。
- 主要组件：`Dispatcher`、`BaseEvent`、`BaseEventHandler`、`BaseSpanHandler`、span 树、传播上下文和 `instrument_tags`。
- `[project.scripts]` 暴露 `llama-index-instrumentation = "llama_index_instrumentation:main"`。
- core 通过 `llama_index.core.instrumentation` 适配层取得 dispatcher；例如 `RetrieverQueryEngine` 和 `VectorIndexRetriever` 使用 `@dispatcher.span`，查询事件仍通过 `CallbackManager` 发出。

### 5.4 `llama-index-utils`

面向多个集成包的轻量复用工具，当前可见子包包括 `llama-index-utils-azure`、`llama-index-utils-huggingface`、`llama-index-utils-oracleai`、`llama-index-utils-qianfan`；每个子包有自己的 `pyproject.toml`，不应与 core 业务层混同。

### 5.5 `llama-index-integrations`

现场有 621 个独立 `pyproject.toml`。每个 integration 通常有自己的 `llama_index/<category>/<name>/` 包、README、测试、锁文件和构建元数据，可独立构建/发布。以 `llama-index-vector-stores-chroma` 为样例：

- 包名/版本：`llama-index-vector-stores-chroma` `0.5.5`。
- 依赖：`chromadb>=0.5.17` 与 `llama-index-core>=0.13.0,<0.15`。
- `[tool.llamahub] import_path = "llama_index.vector_stores.chroma"`。
- `class_authors` 声明 `ChromaVectorStore` 的归属。

这里的关键解耦不是动态扫描后自动装配一个全局插件容器，而是 core 定义稳定契约，集成包实现具体 provider，并使用 Python namespace/import path 和版本区间连接两侧。core 源码不反向 import 全量 integrations。

## 6. 核心模型与序列化

### 6.1 `BaseComponent` 与节点模型

`llama-index-core/llama_index/core/schema.py` 中：

- `BaseComponent` 基于 Pydantic，`class_name()` 是稳定序列化标识；`custom_model_dump()`、`to_dict()`、`to_json()` 会写入 `class_name`，`from_dict()` 会移除该字段后重建对象。
- `__getstate__()` 尝试移除不可 pickle 的字段并记录 warning；`__setstate__()` 优先用 `__init__` 重建，失败后才回退默认状态恢复。这是序列化兼容/资源清理措施，不是完整的反序列化安全沙箱。
- `TransformComponent` 同时承载 Pydantic 组件和 dispatcher span，公开 `__call__()`，异步默认回落到同步实现。
- `BaseNode` 家族承载 `id_`、embedding、metadata、hash、关系和内容；`Document` 是输入文档，`TextNode`/`ImageNode` 是节点，`IndexNode` 可引用另一索引/检索对象。
- `MetadataMode` 区分 `ALL`、`EMBED`、`LLM`、`NONE`；元数据可分别排除出 embedding 或 LLM 内容，避免同一原文在不同阶段使用同一份上下文。
- `NodeRelationship` 包括 `SOURCE`、`PREVIOUS`、`NEXT`、`PARENT`、`CHILD`；`RelatedNodeInfo` 保存关系节点信息。
- `ObjectType`/`Modality` 覆盖 text、image、index、document、multimodal 及 audio/video 等模态边界。

### 6.2 索引结构注册

`indices/registry.py` 的 `INDEX_STRUCT_TYPE_TO_INDEX_CLASS` 当前登记 11 类：`TREE`、`LIST`、`KEYWORD_TABLE`、`VECTOR_STORE`、`SQL`、`PANDAS`、`KG`、`SIMPLE_LPG`、`EMPTY`、`DOCUMENT_SUMMARY`、`MULTIMODAL_VECTOR_STORE`。`indices/loading.py` 读取 `IndexStruct.get_type()` 后按该表恢复具体索引类；未知类型不会静默落到默认实现。

### 6.3 VectorStore 契约

`vector_stores/types.py` 同时保留两条接口：

1. `VectorStore(Protocol, runtime_checkable)`：鸭子类型接口，公开 `add`、`async_add`、`delete`、`adelete`、`query`、`aquery`、`persist`。
2. `BasePydanticVectorStore(BaseComponent, ABC)`：真正适合 Pydantic 序列化/配置的抽象基类，公开同组操作并增加 `get_nodes`、`delete_nodes`、`clear` 等扩展。

两条接口明确不能直接混合（源码注释为 `Temp copy of VectorStore for pydantic, can't mix with runtime_checkable`）。实现必须声明：

- `stores_text: bool`：向量库是否自行保存文本；
- `is_embedding_query: bool`：查询是否需要 embedding；
- `add(nodes) -> List[str]`；
- `delete(ref_doc_id)`、`query(VectorStoreQuery) -> VectorStoreQueryResult`；
- 异步方法在未专门实现时默认同步回落。

`VectorStoreQuery` 支持 `query_embedding`、`similarity_top_k`、`doc_ids`、`node_ids`、`query_str`、`mode`、`alpha`、`filters`、MMR 以及 hybrid 检索参数。`MetadataFilter` 使用 `StrictInt`、`StrictFloat`、`StrictStr` 等严格类型；`FilterOperator` 覆盖等值、比较、集合、文本匹配和空值判断；不支持高级过滤器的后端通过 `legacy_filters()` 显式拒绝非 EQ 条件。

## 7. 真实调用链

### 7.1 读取与 ingestion

`SimpleDirectoryReader` 在 `readers/file/base.py`：

- 构造时要求 `input_dir` 或 `input_files`；支持 `exclude_hidden`、`exclude_empty`、`recursive`、`required_exts`、`file_extractor`、`num_files_limit`、metadata 回调和 `fsspec` 文件系统。
- `_add_files()` 通过 `fs.walk` 收集文件，按隐藏文件、空文件、后缀、排除目录和数量上限过滤；没有文件时抛 `ValueError`。
- `load_data()` 逐文件或使用 multiprocessing `spawn` 读取，默认文件读取器按后缀选择，最后统一排除 metadata；`aload_data()` 使用异步任务，`iter_data()` 按文件产生文档批次。
- 文件/远程文件系统边界由 `fsspec` 和调用方的 `file_extractor` 决定，不是内置的内容安全隔离层。

`BaseIndex.from_documents()` 的当前实现：

1. 创建/复用 `StorageContext`、`CallbackManager` 和 `Settings.transformations`。
2. 对每个 `Document` 执行 `docstore.set_document_hash(doc.id_, doc.hash)`。
3. 执行 `run_transformations(documents, transformations)`，产生 `BaseNode[]`。
4. 调用 `cls(nodes=nodes, storage_context=..., callback_manager=...)`。
5. `BaseIndex.__init__()` 建立 docstore/index store/vector store/graph store 引用，登记 object map，进入 `index_construction` trace。
6. 通过 `build_index_from_nodes()` 先写 docstore，再调用子类 `_build_index_from_nodes()`，最后把 `IndexStruct` 写入 index store。

`Settings.transformations` 没有显式设置时惰性创建为 `[Settings.node_parser]`；`Settings.node_parser` 默认是 `SentenceSplitter()`。embedding 可作为独立变换或由 `VectorStoreIndex` 建索引时执行，不能把“切分”和“向量化”误认为同一个 core 阶段。

### 7.2 `VectorStoreIndex` 建索引

`indices/vector_store/base.py` 的主路径：

- 构造时用 `resolve_embed_model(embed_model or Settings.embed_model)` 解析 embedding，默认 `insert_batch_size=2048`。
- `build_index_from_nodes()` 先过滤 `node.get_content(metadata_mode=MetadataMode.EMBED) == ""` 的空节点并打印提示，再进入 `_build_index_from_nodes()`。
- 同步路径 `_add_nodes_to_index()`：按 2048 分批 → `_get_node_with_embedding()` → `vector_store.add()` → 根据 `stores_text`/`store_nodes_override` 分支写 `IndexDict` 和 docstore。
- 当向量库不保存文本，或显式 `store_nodes_override=True`，每个节点去掉 embedding 后写入 index struct 与 docstore；当向量库保存文本，只额外保留 `ImageNode`、`IndexNode` 等非普通文本节点。
- `use_async=True` 时走 `_async_add_nodes_to_index()`、`async_embed_nodes()`、`async_add()`；未实现异步的后端会按契约回落同步。
- `from_vector_store()` 要求 `vector_store.stores_text=True`，否则显式抛 `ValueError`。
- 当前 `_delete_node()` 在 `VectorStoreIndex` 中是空实现；真正的 `delete_nodes()`/`delete_ref_doc()` 直接调用 vector store，再按存储文本策略维护 index struct/docstore。该语义必须在特定 integration 后端复核，不能默认所有向量库删除能力一致。

### 7.3 检索与查询

`indices/vector_store/retrievers/retriever.py` 中 `VectorIndexRetriever`：

1. 根据 `vector_store.is_embedding_query` 和 query mode 判断 `_needs_embedding()`；`TEXT_SEARCH`、`SPARSE` 模式不强制 embedding。
2. 需要时由 `_embed_model.get_agg_embedding_from_queries()` 或异步版本填充 `QueryBundle.embedding`。
3. 组装 `VectorStoreQuery`，把 top-k、node/doc ids、filters、hybrid 参数和 `vector_store_kwargs` 传给后端 `query()`。
4. 根据返回的 `nodes`/`ids` 和向量库是否保存文本，决定从 docstore 补哪些节点；缺失节点时显式报错，结果不满足至少有 `nodes` 或 `ids` 时抛 `ValueError`。
5. 把 `VectorStoreQueryResult` 转成 `NodeWithScore[]`，保留相似度并记录查询日志。

`RetrieverQueryEngine._query()` 的当前调用顺序：

```text
BaseQueryEngine.query()
  -> RetrieverQueryEngine._query()
       -> retrieve(query_bundle)
            -> VectorIndexRetriever.retrieve()
                 -> vector_store.query()
                 -> docstore.get_nodes()（必要时）
                 -> NodeWithScore[]
       -> node_postprocessors 顺序执行
       -> BaseSynthesizer.synthesize(query, nodes)
       -> CallbackManager QUERY event.on_end(response)
       -> 返回 RESPONSE_TYPE
```

同步/异步路径分别是 `_query()`/`_aquery()`、`retrieve()`/`aretrieve()`、`synthesize()`/`asynthesize()`；`@dispatcher.span` 覆盖 query 和 vector retrieval 关键边界。

### 7.4 响应合成与 token 预算

`response_synthesizers/factory.py::get_response_synthesizer()` 根据 `ResponseMode` 工厂化选择实现：`REFINE`、`COMPACT`、`TREE_SUMMARIZE`、`SIMPLE_SUMMARIZE`、`GENERATION`、`ACCUMULATE`、`COMPACT_ACCUMULATE`、`NO_TEXT`、`CONTEXT_ONLY`；未知 mode 显式抛 `ValueError`。

`PromptHelper` 的核心边界：

- `available_context = context_window - num_prompt_tokens - num_output`；小于 0 时抛 `ValueError`。
- 可用 chunk 大小约为 `available_context // num_chunks - padding`，再受 `chunk_size_limit` 限制。
- token 估算会考虑 text/chat 模板、LLM system prompt、StructuredLLM 工具定义。
- `repack()` 使用 `TokenTextSplitter` 合并小块以尽量填满上下文；`truncate()` 则把每个输入块裁剪到预算内。
- `SelectorPromptTemplate` 会根据 `is_chat_model(llm)` 选择 text/chat 模板；`RetrieverQueryEngine.from_args()` 可注入 prompt、response mode、output model、streaming、async、multimodal 和 structured filtering 参数。

## 8. Settings、回调和观测

### 8.1 全局惰性配置

`settings.py` 定义 dataclass `_Settings` 并创建单例 `Settings = _Settings()`：

- `llm` 首次读取时 `resolve_llm("default")`；
- `embed_model` 首次读取时 `resolve_embed_model("default")`；
- `callback_manager` 默认创建 `CallbackManager()`；
- `node_parser` 默认创建 `SentenceSplitter()`；
- tokenizer 使用 core global tokenizer 或 `get_tokenizer()`；
- `prompt_helper`/`chat_prompt_helper` 可从 LLM metadata 惰性生成；
- `transformations` 默认 `[self.node_parser]`；
- `chunk_size`、`chunk_overlap` 是对 node parser 属性的代理，不支持相应属性时抛 `ValueError`。

这是便捷的全局可变状态：测试之间和多租户应用之间若共享进程，必须显式设置/恢复 `Settings`，否则可能产生配置串扰。

### 8.2 `Dispatcher` 观测模型

独立包 `Dispatcher` 维护 event handlers、span handlers、parent/root dispatcher 和 `propagate` 链：

- `event()` 沿当前 dispatcher 到父链同步派发；`aevent()` 创建异步任务并 `gather(..., return_exceptions=True)`。
- handler 异常被捕获并忽略，观测故障不阻断业务调用。
- span 有 enter/drop/exit 生命周期；span handler 能沿父链建立树形 trace。
- `ContextVar active_instrument_tags` 保存当前标签；`capture_propagation_context()`/`restore_propagation_context()` 可跨线程/进程传播 handler 上下文和标签。
- `shutdown()` 负责丢弃未关闭 span 并关闭 handler。

core 侧的 `DispatcherSpanMixin`、`instrument.get_dispatcher(__name__)` 和 `CallbackManager` 是两套互补通道：前者用于 span/观测树，后者用于业务事件和 trace 名称。

## 9. 存储、持久化与恢复

`storage/storage_context.py` 的 `StorageContext` 是存储容器，不是数据库服务。字段为：

- `docstore: BaseDocumentStore`：节点原文和文档 hash；默认 `SimpleDocumentStore`。
- `index_store: BaseIndexStore`：`IndexStruct`；默认 `SimpleIndexStore`。
- `vector_stores: Dict[str, BasePydanticVectorStore]`：按 namespace 保存向量库；默认 `DEFAULT_VECTOR_STORE`，可增加 `image` namespace。
- `graph_store: GraphStore`：默认 `SimpleGraphStore`。
- `property_graph_store`：`SimplePropertyGraphStore`，按需从持久化目录加载。

`StorageContext.from_defaults()`：

- 无 `persist_dir` 时创建内存对象；
- 有 `persist_dir` 时从 `docstore.json`、`index_store.json`、`graph_store.json`、命名空间向量文件等恢复；属性图文件缺失时把 property graph store 设为 `None`；
- 可通过 `vector_store`/`image_store`/`vector_stores` 注入外部实现。

`StorageContext.persist()` 依次持久化 docstore、index store、graph store、property graph store，并为每个 vector store 生成 `<namespace>__<vector_store_fname>` 文件；默认目录是 `./storage`。`load_index_from_storage()` 通过 index store 取得 `IndexStruct`，按 `INDEX_STRUCT_TYPE_TO_INDEX_CLASS` 重建索引；没有索引或索引数多于一个时显式报错，多个索引应使用 `index_id`。

core 自带 `SimpleVectorStore`，所以最小 RAG 可以不依赖第三方向量数据库；外部 vector store 的 durable 语义、过滤语义和删除语义由各 integration 自行实现并通过 core 契约接入。

## 10. API、SDK、CLI 与协议边界

### 10.1 Python 公共 API

README 展示的主要入口：

```python
from llama_index.core import Settings, StorageContext, SimpleDirectoryReader
from llama_index.core import VectorStoreIndex, load_index_from_storage
from llama_index.llms.openai import OpenAI
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
```

命名空间规则是：带 `core` 的导入指向 core 包；不带 `core` 的具体 provider 路径通常来自 integration，例如 `llama_index.llms.openai`、`llama_index.vector_stores.chroma`。根 `llama-index` 是 starter 包，把 core 与少量 OpenAI 相关 integration 组合发布；用户也可以只安装 `llama-index-core` 再选择所需 integration。

### 10.2 `llama-dev` 仓库开发 CLI

`llama-dev/pyproject.toml` 暴露：

```text
llama-dev = llama_dev.cli:cli
```

`llama_dev.cli:cli` 用 Click 注册三个命令组：`pkg`、`test`、`release`，全局参数为 `--repo-root`、`--debug`。README 说明的使用面包括：

- `llama-dev pkg info`：查询一个或全部 package 元数据；
- `llama-dev pkg exec`：在一个或全部 package 目录执行命令；
- `llama-dev test --base-ref main --workers N [--cov]`：按变更包及依赖包运行测试，支持并行和覆盖率；
- `llama-dev release ...`：发布前检查、变更日志和发布自动化。

根 `Makefile` 仍提供 `pants` 目标（如 `test-core`、`test-integrations`），但当前 GitHub CI 主单元测试工作流在 `llama-dev` 工作目录调用 `uv run -- llama-dev test`。

### 10.3 CLI 边界

core 的 `command_line/__init__.py` 仅写明“Deprecated. CLI is now its own package llama-index-cli”；因此不要把 `llama_index.core.command_line` 当作当前主 CLI。本文未把仓库外部的 `llama-index-cli` 实现当作本地源码证据。

## 11. 依赖、构建、测试与部署

### 11.1 依赖边界

- Python：各主要包声明 `>=3.10,<4.0`；`llama-dev` 要求 `>=3.9.17`。
- 构建：统一使用 Hatchling；开发/锁定工具使用 `uv`。
- core 运行时依赖包括 Pydantic、SQLAlchemy、fsspec、httpx/requests/aiohttp、numpy、tiktoken、nltk、networkx、Pillow、PyYAML、aiosqlite 等；具体列表以 `llama-index-core/pyproject.toml` 为准。
- integration 额外依赖第三方 provider，并通常以 `llama-index-core>=0.13.0,<0.15` 这样的契约版本区间绑定 core。
- `pyproject.toml` 中的 `tool.uv.sources` 可把本地 integration 作为开发源；不同子包有独立 `uv.lock`。

### 11.2 测试结构

- 测试框架是 `pytest`，core 测试位于 `llama-index-core/tests/`，按 schema、storage、vector stores、indices、query engine、ingestion、tools、rate limiter 等领域分目录。
- integration 通常在自己的包目录中维护测试；本仓库递归现场统计到 1,620 个测试相关 `.py` 文件。
- `CONTRIBUTING.md` 要求修改包后在该包目录运行 `uv run -- pytest`，远程系统应以 mock 避免外部变化导致测试不稳定，并说明 CI 有覆盖率门槛（默认低于 50% 会失败）。
- 当前核对**未运行测试、未运行 lint、未运行 typecheck、未运行构建或安装**，因此本文不声称当前源码测试通过。

### 11.3 CI 验证与发布

根据当前 `.github/workflows/`：

- `unit_test.yml`：Python `3.10`、`3.11`、`3.12` 矩阵；每个 job `NUM_WORKERS=8`；另有 Python `3.14` 的 core 测试和 coverage；CI 先安装 `portaudio19-dev`，再通过 `llama-dev test` 执行。
- `build_package.yml`：Ubuntu/Windows 构建矩阵，`uv build`，创建 venv 安装 wheel，并在临时目录执行 `import llama_index`。
- `lint.yml`：Python 3.12，`uv run -- pre-commit run -a`。
- `core-typecheck.yml`：在 `llama-index-core` 中执行 `uv run -- mypy llama_index`。
- `release.yml`：发布 core 前 `uv sync`、填充 NLTK/tiktoken cache、生成 GitHub build provenance attestation、运行 `uv run pytest tests`、`uv build`、`uv publish`；随后发布根 starter 包并创建 GitHub Release。
- `publish_sub_package.yml`：比较 push 前后变更的 `pyproject.toml`，对变更的非 core integration 逐包执行 `uv sync && uv build && uv publish`。

这表明部署/交付形态主要是 PyPI 多包发布，而不是常驻 HTTP 服务；运行时服务由使用方自行承载。

## 12. 安全边界与资源行为

`SECURITY.md` 的威胁模型把 LlamaIndex 定位为可信执行环境内的 Python 库：当它被嵌入 FastAPI/Flask/Django 等网络服务时，输入校验、认证、授权、Web 限流和应用层安全由宿主负责。源码与文档反映的边界包括：

- `SimpleDirectoryReader` 接收本地/`fsspec` 路径和可自定义 reader；调用方必须限制路径、大小、格式和来源。
- tools 允许用户提供函数；不能把工具执行当成内置沙箱。
- Text-to-SQL prompt 会约束“只使用列出的表”“不要查询所有列”，但 prompt 约束不替代数据库权限、SQL parser 或执行沙箱。
- `BaseComponent` 对不可 pickle 属性做清理和重建，但这不是对不可信 pickle 输入的完整防护。
- 观测 handler 异常被吞掉，优点是观测不阻断业务，代价是 handler 故障可能只留日志而不向调用方传播。
- `TokenBucketRateLimiter` 和 `SlidingWindowRateLimiter` 同时提供同步/异步 `acquire`；限流器可被多个 LLM/embedding 实例共享，但实现状态是进程内状态，不自动提供跨进程/分布式一致额度。
- 读取、embedding、向量库、LLM、外部 reader/provider 的超时、重试、TLS、凭证和资源释放语义必须在具体 integration 和宿主应用中继续核验。

## 13. 失败语义与重要行为边界

- 参数冲突（例如 `nodes` 与 `index_struct` 同时提供、VectorStore 的 filters 与后端专有 where 双路冲突）倾向于显式 `ValueError`。
- 未实现能力使用 `NotImplementedError`，例如部分 vector store `get_nodes`、某些索引删除逻辑；不静默宣称完成。
- 查询结果必须至少提供 `nodes` 或 `ids`；检索器无法从 index struct/docstore 补回节点时抛错。
- `stores_text` 是 vector store 与 docstore/index struct 协同的关键契约标志；错误声明会造成重复存储或查询结果缺节点。
- `Settings` 是进程级可变 singleton；长期运行服务和测试需要主动管理生命周期。
- `ResponseMode` 工厂未知值显式拒绝；LLM 输出解析失败在部分响应合成路径中 warning 后继续，需结合具体 synthesizer 判断是否会产生空回答。
- `SimpleVectorStore` 和 JSON storage 适合默认/本地场景；生产持久化、并发、故障恢复和一致性不能由本文推断为数据库级保证。

## 14. 对系统底座可借鉴的架构观察

以下是基于当前源码的抽象观察，不是对本项目的改造要求：

1. **契约与 provider 分离**：core 以 Protocol/ABC/Pydantic 模型定义能力，integration 通过独立包实现具体 provider，并以 core 版本区间绑定契约。
2. **窄接口 + 契约标志**：`VectorStore` 的少量核心方法配合 `stores_text`、`is_embedding_query`，让上层统一处理不同后端。
3. **模板方法生命周期**：`BaseIndex.from_documents → run_transformations → build_index_from_nodes → _build_index_from_nodes` 固定骨架，子类只实现索引差异点。
4. **注册表是恢复路由**：`INDEX_STRUCT_TYPE_TO_INDEX_CLASS` 同时承担类型到实现的反序列化路由，注册表变更会影响持久化兼容。
5. **默认实现与可插拔实现并存**：`SimpleVectorStore`/Simple stores 让最小链路可运行，外部 integration 只替换契约实现。
6. **全局惰性配置降低接入成本但引入状态管理责任**：`Settings` 统一解析默认模型与变换链，适合快速构建，不适合无边界地跨租户共享。
7. **预算先于执行**：`PromptHelper` 把模板、system prompt、工具和输出预留纳入 token 预算，再 repack/truncate，避免把上下文限制留给 provider 猜测。
8. **业务事件与观测 span 分离**：`CallbackManager` 面向业务事件，`Dispatcher` 面向 span 树和传播；handler 异常不阻断业务。
9. **持久化容器组合化**：`StorageContext` 把 docstore、index store、vector namespaces、graph stores 组合起来，索引算法不直接绑定某个文件格式或数据库。
10. **开发自动化独立成包**：`llama-dev` 把变更检测、并行测试、包信息和发布流程从运行时 core 中剥离。

## 15. 未确认项、风险与后续复核点

### 已确认但需持续关注

- **远程漂移**：远程 `main` 已是 `d8021225...`，本地仍是 `7359b1a...`；后续深挖应先建立最新源码快照或在允许时 fetch，再复核关键 API 是否漂移。
- **代码地图缺失**：本项目没有 `.codegraph/`；需要符号级影响分析时应由项目负责人决定是否初始化代码图，当前核对不擅自生成。
- **历史研究已收口**：此前细粒度研究稿已经人工吸收到本文并清理；后续不再创建第二份并行正式架构文档。
- **集成规模复杂**：621 个独立 integration 未逐包阅读；本文只抽查了 `llama-index-vector-stores-chroma` 作为 provider 结构样例，不能把 Chroma 的过滤/持久化语义外推到所有向量库。
- **外部 provider 语义**：LLM、embedding、reader、vector store、storage、tool 和 graph integration 的凭证、重试、超时、事务、TLS、并发和删除语义均需按具体包继续复核。

### 尚未在当前核对验证

- 没有安装依赖、创建虚拟环境或运行 Python 导入。
- 没有运行 `pytest`、`llama-dev test`、`make test`、`pants`、`pre-commit`、`mypy`。
- 没有运行 `uv build`、wheel 安装、PyPI 发布或 GitHub attestation。
- 没有读取远程新提交的源码内容，没有声称远程版本与本地实现兼容。
- 没有对所有 621 个 integration 的 `stores_text`、filters、async、persist、delete、错误码和外部依赖做契约矩阵。
- 没有验证 `llama-index-cli`（仓库外/独立包）的当前版本，也没有把它的源码纳入本项目架构范围。

### 风险重点

1. `Settings`/global tokenizer/callback 的进程级可变状态可能导致测试污染或多租户串配置。
2. `stores_text`、`is_embedding_query` 和 provider 返回 `nodes`/`ids` 的契约不一致，会产生静默缺文档、重复存储或检索结果错误。
3. 集成包数量大、版本区间宽，core 的数据模型/序列化/IndexStruct 注册变更可能造成跨包或持久化兼容风险。
4. prompt 约束、Pydantic 校验和 pickle 清理不能替代宿主侧权限、SQL 执行隔离、路径验证和网络安全控制。
5. `Simple*Store` 的 JSON 持久化不应默认视为生产级并发存储；生产环境要单独验证原子性、锁、损坏恢复和备份策略。
6. 观测 handler 异常被吞掉会提高业务可用性，但可能降低诊断完整性；应通过独立监控确认 handler 自身健康。

## 16. 证据路径索引

- 定位/安装/主流程样例：`README.md`
- 根包元数据：`pyproject.toml`
- core 元数据：`llama-index-core/pyproject.toml`
- instrumentation 元数据和 console script：`llama-index-instrumentation/pyproject.toml`
- 仓库开发 CLI 元数据：`llama-dev/pyproject.toml`
- 仓库 CLI 入口：`llama-dev/llama_dev/cli.py`、`llama-dev/llama_dev/__main__.py`
- core 模型与序列化：`llama-index-core/llama_index/core/schema.py`
- Settings：`llama-index-core/llama_index/core/settings.py`
- 读取器：`llama-index-core/llama_index/core/readers/file/base.py`
- ingestion 出口：`llama-index-core/llama_index/core/ingestion/__init__.py`、`pipeline.py`
- 索引骨架：`llama-index-core/llama_index/core/indices/base.py`
- VectorStoreIndex：`llama-index-core/llama_index/core/indices/vector_store/base.py`
- VectorIndexRetriever：`llama-index-core/llama_index/core/indices/vector_store/retrievers/retriever.py`
- 查询引擎：`llama-index-core/llama_index/core/query_engine/retriever_query_engine.py`
- 合成工厂：`llama-index-core/llama_index/core/response_synthesizers/factory.py`
- token 预算：`llama-index-core/llama_index/core/indices/prompt_helper.py`
- VectorStore 契约：`llama-index-core/llama_index/core/vector_stores/types.py`
- 存储容器：`llama-index-core/llama_index/core/storage/storage_context.py`
- 索引恢复注册表：`llama-index-core/llama_index/core/indices/registry.py`、`loading.py`
- 限流：`llama-index-core/llama_index/core/rate_limiter.py`
- 独立观测：`llama-index-instrumentation/src/llama_index_instrumentation/dispatcher.py`
- integration 样例：`llama-index-integrations/vector_stores/llama-index-vector-stores-chroma/pyproject.toml`
- 测试/构建/发布：`.github/workflows/unit_test.yml`、`build_package.yml`、`lint.yml`、`core-typecheck.yml`、`release.yml`、`publish_sub_package.yml`
- 开发规则：`CONTRIBUTING.md`、`.pre-commit-config.yaml`
- 安全边界：`SECURITY.md`
- 此前历史人工细探：已人工吸收并清理

## 17. 后续通用底座映射：文档/检索支持库、RAG 模块与运行核心

> 本节是后续裁决，不是把 LlamaIndex 直接复制进平台。映射只回答“哪一类能力由哪个底座 owner 持有、哪条链路允许被复用、哪些语义必须升级或隔离”。当前证据仍以本地 `llama-index-core` 源码为准；`project_context` 曾错绑到无关项目，目标目录无 `.codegraph/`，因此不把 MCP/codegraph 失败结果冒充为目标项目证据。

### 17.1 三类底座 owner 的裁决

| LlamaIndex 能力 | 平台归类 | 规范 owner 与边界 | 当前核对裁决 |
|---|---|---|---|
| `Document`、`BaseNode`、`TextNode`、`ImageNode`、`IndexNode`、`NodeWithScore`、`QueryBundle`、关系/元数据/多模态结构 | 文档/检索支持库的 L0 公共契约 | 只定义不可变或可校验的数据形状、来源位置、节点关系、内容/embedding/metadata 语义；不负责读文件、调模型、查库 | **吸收**为通用文档与检索对象契约；不吸收 LlamaIndex 专有序列化标识作为平台业务主键 |
| `BaseReader`、`BasePydanticReader`、`ResourcesReaderMixin`、`Document` 读取和 `TransformComponent`/node parser | 文档支持库（契约）+ Reader/解析 Provider（实现） | Reader 只负责资源发现、权限/资源信息、读取和统一文档输出；解析器只负责文档→节点变换；第三方格式库留在 provider | **吸收契约，升级资源/取消/安全边界**；不让每个 Reader 自建缓存、重试或结果格式 |
| `VectorStore`/`BasePydanticVectorStore`、`VectorStoreQuery`、filters、`VectorStoreQueryResult`、`SimpleVectorStore` | 检索支持库 | 公共查询/过滤/结果契约与 provider 适配；`stores_text`、`is_embedding_query` 是显式能力声明；向量数据库、索引算法、凭证不进入公共契约 | **吸收窄接口与能力标志**；升级过滤能力矩阵、删除/持久化/超时/幂等契约 |
| `StorageContext`、docstore、index store、vector namespace、graph store 组合 | 持久化支持库；原子提交/恢复属于运行核心 | 支持库提供存储后端与读写契约；运行核心负责版本、锁、校验、原子发布、失败回滚和崩溃恢复；不能把 `StorageContext` 当权威状态服务 | **吸收组合容器；升级持久化事务和恢复** |
| `BaseIndex`、`VectorStoreIndex`、`IndexStruct`、`VectorIndexRetriever`、`RetrieverQueryEngine`、response synthesizer | RAG 模块 | 只编排“文档/节点→转换→索引→检索→后处理→合成”的领域流程；通过公开支持库契约组合能力；不持有 provider 注册、租约、数据库事务 owner | **吸收流程骨架为唯一 RAG 模块链路**；不复制第二套索引/检索内核 |
| `LLM`/`BaseLLM`、`BaseEmbedding`、`resolve_llm()`、`resolve_embed_model()` 及 `llama-index-integrations` 中具体包 | 模型/Embedding/LLM Provider 支持库 | Provider 适配外部 SDK、凭证、限流和网络协议；对上只返回统一 LLM/embedding 结果；注册、版本、健康、资源和失败治理由运行核心托管 | **吸收 Provider 解耦与显式解析**；升级隐式默认模型、fallback、客户端关闭和取消语义 |
| `Settings`、`CallbackManager`、`Dispatcher`、`async_utils` | 运行核心的配置/观测/执行适配，不是 RAG 业务 | 运行核心持有请求上下文、资源预算、超时/取消、观测和 provider 生命周期；业务模块不得依赖全局可变 singleton | **只吸收机制，不复制全局状态**；`Settings` 作为兼容适配层隔离 |
| `agent`、`chat_engine`、`workflow`、`memory`、`evaluation`、tools | L4 应用/编排层或独立模块 | 这些不是文档检索支持库，也不是当前核对 RAG 核心；需要接入时只能调用唯一 RAG 模块公开入口 | **隔离**，不把它们并入第二 RAG 链路 |

### 17.2 唯一可复用链路与“第二 RAG 链路”禁令

```text
资源/输入
  → Reader Provider（资源发现、权限、读取）
  → 通用 Document/Node 契约（L0）
  → 文档变换/节点解析 Provider（L1）
  → Ingestion/缓存/docstore（支持库，幂等去重）
  → 唯一 RAG 模块：Index/VectorStoreIndex
  → Embedding Provider（L1）→ VectorStore Provider（L1）+ IndexStruct/docstore
  → 唯一 Retriever：VectorIndexRetriever
  → 唯一 QueryEngine：RetrieverQueryEngine
  → postprocessor → response synthesizer
  → LLM Provider（L1）→ 统一响应、来源节点、事件与资源释放
```

平台落点必须保持“一能力一个契约 owner、一个公开入口、一条注册/调用路径”。Reader、embedding、vector store、LLM 的不同实现是同一模块契约下的 provider，不得各自复制 `Index→Retriever→QueryEngine`。现有 LlamaIndex 的 `BaseIndex.from_documents()`、`VectorStoreIndex.as_retriever()`、`RetrieverQueryEngine._query()` 已经提供一条可审计的参考骨架；平台只复用边界和顺序，不复制其全量包树、全局状态或每个 integration 的业务代码。

禁止以下侧链：业务代码直连第三方模型/向量库、模块自行翻译 `VectorStoreQueryResult`、provider 对象穿透公共结果契约、每个 Reader 自建 RAG index、为 `SimpleVectorStore` 再建一套“本地 RAG”、为外部 vector store 再建一套“生产 RAG”、把 `Settings` fallback 当第二 provider 注册表。旧英文键/别名若存在，只能在唯一调用入口归一化一次。

### 17.3 LlamaIndex core 目录到平台层级的逐项映射

| core 路径/符号 | L0 | L1 支持库/Provider | L2 运行核心 | L3 RAG 模块 | 说明 |
|---|---:|---:|---:|---:|---|
| `schema.py`：`Document`/`BaseNode`/`NodeWithScore`/`QueryBundle` | ✓ |  |  |  | 公共数据与来源/关系语义；不得混入 IO 和网络 |
| `readers/base.py`、`readers/file/base.py` |  | ✓ | 资源监督/取消 |  | `BaseReader` 是契约，具体文件/远程 reader 是 provider；`ResourcesReaderMixin` 是资源边界 |
| `ingestion/pipeline.py`：`run_transformations()`、`IngestionPipeline`、`IngestionCache`、`DocstoreStrategy` | 节点契约 | cache/docstore provider | 缓存生命周期、幂等与并发治理 | ✓ 编排 | 作为 RAG 前置 ingestion，不另造文档摄取链 |
| `indices/base.py`、`indices/registry.py`、`indices/loading.py` | `IndexStruct` 形状 | 存储适配 | 恢复路由、版本兼容 | ✓ 索引骨架 | registry 是反序列化路由，不是 provider 业务注册中心 |
| `indices/vector_store/base.py` |  | embedding/vector store 契约实现 | 批次预算、任务监督、资源释放 | ✓ `VectorStoreIndex` | `stores_text` 决定 docstore/index struct 补存策略，不能由调用方猜测 |
| `indices/vector_store/retrievers/retriever.py` | `VectorStoreQuery`/`NodeWithScore` | vector store、embedding provider | 超时、取消、预算和观测 | ✓ `VectorIndexRetriever` | query mode、filters、top-k 在模块契约中固定，后端专有参数只能显式扩展 |
| `query_engine/retriever_query_engine.py`、`response_synthesizers/` | response shape | LLM provider | token/时间/输出预算与取消 | ✓ 唯一 QueryEngine + synthesizer | 不允许业务层绕过 Retriever 直接调用 provider 生成“第二问答链” |
| `storage/storage_context.py`、`storage/*store`、`vector_stores/simple.py` | 持久化数据结构 | 文件/数据库/vector backend provider | 原子持久化、锁、校验、恢复 | 只持有引用 | `StorageContext` 组合 stores，不拥有全局状态和业务事务 |
| `llms/utils.py`、`embeddings/utils.py`、`settings.py` | Provider 标识/统一接口 | ✓ | lazy resolver、健康、凭证、预算、关闭 | 由 RAG 调用 | `resolve_*` 可作为适配线索，不能成为第二注册中心 |
| `instrumentation/`、`callbacks/`、`async_utils.py` | 事件/span 形状 | handler/provider 适配 | 上下文传播、排空、关闭、失败证据 | 被 RAG 使用 | 观测异常不可静默吞掉治理关键证据 |

### 17.4 懒加载、Provider 与单一注册/调用入口

**已确认的懒加载事实**：

1. `settings.py::_Settings` 的 `llm`、`embed_model`、`node_parser`、`callback_manager`、`prompt_helper` 等属性按首次读取初始化；默认 `node_parser` 是 `SentenceSplitter()`。
2. `llms/utils.py::resolve_llm()` 在调用时才尝试导入 `llama_index.llms.openai`、`llama_index.llms.llama_cpp` 或 LangChain 包；`embeddings/utils.py::resolve_embed_model()` 同样按需导入 OpenAI、CLIP、HuggingFace 或 LangChain adapter。
3. `VectorStoreIndex.as_retriever()` 明确使用 lazy import 才导入 `VectorIndexRetriever`；core 因此不会在只构造文档对象时加载完整检索实现。
4. `BaseReader.alazy_load_data()`、`aload_data()`、资源异步方法默认通过 `asyncio.to_thread()` 调同步实现，只有 provider 覆盖它们才是真异步 IO。

平台应把这些行为分成三个阶段：`发现/声明`（不加载重型 SDK）→ `首次调用初始化`（解析 provider、校验能力与凭证、创建资源）→ `调用后释放/归还`（关闭客户端、线程/进程、临时文件、租约和 trace）。Provider 只能由唯一能力注册表/调用器解析；RAG 模块不得 `import` 第三方 SDK 或自行 fallback。默认模型、`local:*`、`clip:*` 等字符串选择器必须在适配层显式记录为 provider 版本和配置摘要；缺包、凭证缺失、宿主不可用应返回稳定错误与可重试属性，不能以 Mock/隐式 fallback 冒充生产成功。

### 17.5 持久化、缓存与恢复边界

`StorageContext.from_defaults()` 在无 `persist_dir` 时构造内存 `SimpleDocumentStore`、`SimpleIndexStore`、`SimpleGraphStore` 和 namespaced `SimpleVectorStore`；有 `persist_dir` 时从 `docstore.json`、`index_store.json`、`graph_store.json`、property graph 文件和 namespace vector 文件恢复。`persist()` 依次调用各 store 的 `persist()`；`load_index_from_storage()` 根据 `IndexStruct.get_type()` 经 `INDEX_STRUCT_TYPE_TO_INDEX_CLASS` 恢复索引。`BaseIndex.from_documents()` 先写文档 hash，再执行 transformations；`IngestionPipeline` 可用 `IngestionCache` 和 docstore hash 做去重/缓存。

这些事实的底座裁决是：

- **文档/检索支持库 owner**：定义 docstore/index store/vector store 的最小读写、异步读写、namespace、序列化版本和错误契约；provider 负责 JSON、数据库或远程 vector backend 的具体存取。
- **运行核心 owner**：为一次索引构建或持久化恢复分配 operation id、租约、超时和取消令牌；把多 store 写入封装为可审计事务，执行临时目录→校验→fsync/原子替换→激活指针→证据；失败、超时、取消和进程崩溃都能回滚或恢复。
- **RAG 模块 owner**：只提交“节点、index struct、查询结果”等公开命令，不直接改权威数据库，不自己决定锁/事务/恢复。

当前源码**没有证据**表明 `StorageContext.persist()` 对多 store 写入提供事务、原子发布、校验和崩溃恢复；也不能把 `Simple*Store` JSON 文件当生产并发数据库。因此这部分是“吸收容器、升级治理”，不是已完成的平台能力。`IndexStruct` 注册表只能恢复类型，不能替代迁移表、版本兼容和数据完整性校验。

### 17.6 资源生命周期、失败、超时与取消

| 资源 | 当前源码事实 | 运行核心必接管的 owner/终态 |
|---|---|---|
| 本地路径、`fsspec` filesystem、远程 reader 会话 | Reader 接收本地/远程资源；`ResourcesReaderMixin` 提供资源枚举、权限信息、按资源读取，但基类没有统一 `close`/租约 | 规范化路径、大小/格式/来源校验；正常、失败、取消、崩溃均释放句柄和网络会话 |
| `asyncio.to_thread()`、`ProcessPoolExecutor`、批次任务 | Reader 默认 async 是线程包装；ingestion 支持进程池；`run_jobs()` 以 semaphore 限制并发 | 任务 id、进程组/线程排空、超时后 kill/回收、取消结果与残留检查；不能把“Future 被取消”当作底层同步函数已停止 |
| LLM/Embedding SDK client、rate limiter、embedding cache | `BaseEmbedding` 支持 batch、cache、rate limiter；具体 client 在 integration；LLM/embedding 可同步或异步流式返回 | 连接池、凭证、预算、重试/退避、流式断开、取消、关闭；Provider 不得泄漏客户端到上层 |
| VectorStore client、index/docstore、namespace 文件 | `VectorStore` 同时有 sync/async add/query/delete/persist；`stores_text` 决定文本是否由后端持有 | 每次调用的连接/事务/租约；写入幂等、删除一致性、查询超时、结果补全和资源释放 |
| cache、临时文件、持久化目录、索引快照 | `IngestionCache` 可读写缓存；`StorageContext.persist()` 顺序写多个文件 | 临时目录隔离、内容摘要、原子替换、旧版本保留、失败回滚、崩溃扫描和残留清理 |
| `CallbackManager`、`Dispatcher` span/context | callback/span 有开始/结束与上下文传播；部分 handler 异常会被捕获忽略；`shutdown()` 清理未关闭 span | 业务失败不能丢失关键审计事件；正常/异常/取消/崩溃都关闭 span，观测失败单独记录而不能吞掉治理证据 |

失败矩阵必须至少覆盖：空输入/非法 filters/`stores_text` 错配、provider 缺包/缺凭证/宿主不可用、向量库只返回 ids 或返回空 nodes、LLM/embedding 网络断开、超时、主动取消、重复写入、部分持久化、进程崩溃和重启恢复。当前 LlamaIndex 主要以 `ValueError`、`NotImplementedError`、导入错误和 provider 自身异常表达失败；`asyncio.gather()`/`run_jobs()` 提供并发执行但没有平台统一的取消 token、资源所有权转移、失败回滚或跨 provider 取消协议。`BaseReader` 的 `to_thread()` 取消等待方也不会自动停止正在运行的同步读取。因此这些必须归 **L2 运行核心升级项**，不可在 L3 RAG 模块里各写一份超时/重试/清理逻辑。

### 17.7 L0-L4 装配与验收边界

| 层级 | 允许内容 | 本项目映射 | 禁止内容 | 验收重点 |
|---|---|---|---|---|
| **L0 契约/数据** | 通用文档、节点、来源、关系、查询、过滤、向量结果、统一错误/结果形状 | `schema.py`、`vector_stores/types.py` 的数据模型 | IO、SDK、网络、全局 singleton、业务流程 | schema/序列化兼容、字段所有权、错误形状、来源可追溯 |
| **L1 支持库/Provider** | Reader、解析/变换、LLM、Embedding、VectorStore、Storage 后端适配 | `readers/`、`node_parser/`、integrations、`storage/*`、`vector_stores/*`、`resolve_*` | 复制 Index/Retriever/QueryEngine；私自写权威状态 | 缺 provider、版本/能力声明、健康、凭证、超时、重试、关闭、真实结果 |
| **L2 运行核心** | lazy provider resolver、注册/版本、资源租约、并发/预算、超时/取消、观测、持久化事务、恢复 | LlamaIndex 只提供零散线索：`Settings`、`async_utils`、`Dispatcher`、`StorageContext` | 文档切分、检索排序、回答 prompt 等领域逻辑 | 四种终态资源治理；失败证据；崩溃恢复；无残留；单一能力调用器 |
| **L3 RAG 模块** | ingestion→index→retriever→postprocess→query engine→synthesizer 的唯一编排 | `IngestionPipeline`、`BaseIndex`、`VectorStoreIndex`、`VectorIndexRetriever`、`RetrieverQueryEngine`、`response_synthesizers` | 直连第三方、创建第二向量索引/第二查询链、管理 provider 生命周期 | 真实调用链、来源节点、过滤/top-k、同步/异步/流式、取消传播、契约结果 |
| **L4 应用/控制面** | API、任务、租户/权限、业务 workflow、agent/chat/memory、发布和审计 | core 的 `agent`/`workflow`/`memory` 只能作为上层参考 | 把应用策略下沉到 L0/L1，绕过 L2/L3 直连 provider | 权限、幂等、审计、配额、发布回滚和业务验收 |

### 17.8 复用/升级/新建/隔离裁决与装配计划

| 裁决 | 内容 | 依据/动作 |
|---|---|---|
| **吸收** | `Document`/Node/Query/VectorStoreQuery 形状；Reader、VectorStore、LLM、Embedding 的窄契约；`BaseIndex`→Retriever→QueryEngine 顺序；`StorageContext` 的组合思想；lazy import 与 provider 独立包 | 现有源码路径和调用链已确认；落到平台公共契约、文档/检索支持库和唯一 RAG 模块 |
| **升级** | `Settings` 的进程级可变状态、隐式 OpenAI/Mock fallback、`StorageContext.persist()` 多文件顺序写、async `to_thread`/gather、handler 异常吞掉、provider 客户端与资源释放 | L2 统一上下文/Provider 注册表/资源监督/取消/持久化事务/恢复；保留兼容适配，不让新模块复制实现 |
| **新建原子能力** | 文档读取、节点变换、向量写入/查询、LLM/embedding 调用、存储快照/恢复、资源取消/回收的稳定能力 id 与验收契约 | 每个能力只有一个公开入口；provider 只实现策略；先登记需求、检索现有能力、确定 owner，再装配 |
| **隔离/废弃候选** | core 内对第三方的直接默认导入、全局 `Settings` 作为跨租户配置、`Simple*Store` 被误当生产库、L4 agent/workflow 另起 RAG 链、已 deprecated 的 core CLI | 作为兼容边界或历史参考保留，不进入平台权威调用链；不可用宣传文档覆盖未验证实现 |
| **待核** | 621 个 integration 的 filters、async、delete、persist、retry、连接关闭和版本差异；远程 `main` 漂移后的 API 变化 | 先按 provider 分批建立契约/资源/真假验证矩阵，不把 Chroma 样例外推为全体结论 |

建议装配顺序：

1. **L0 冻结**：统一文档/节点/来源位置、查询/过滤/向量结果、错误与取消结果形状；明确 `stores_text`、embedding 维度、namespace 和 provider 版本字段。
2. **L1 支持库**：先接 Reader/解析、Embedding、LLM、VectorStore、Storage 的公开契约与一个可验证 provider；第三方 SDK 只能在 provider 边界出现。
3. **L2 运行核心**：接唯一 provider registry/resolver、请求上下文、资源租约、预算、超时/取消、观测、内容摘要、快照原子发布和恢复；验证正常/失败/取消/崩溃四终态。
4. **L3 唯一 RAG 模块**：只按本节单链路组合 ingestion、index、retriever、query engine、synthesizer；不新建平行 `RAG2`、`VectorRAG`、`LocalRAG` 或 provider 专属 query engine。
5. **L4 接入**：应用/API/agent/workflow 只调用 L3 公开入口并携带租户、权限、operation id、取消 token 和审计关联；不得跨层直连。

### 17.9 后续结论与剩余风险

- **吸收**：LlamaIndex 最有价值的底座不是某个具体模型或数据库，而是可替换的文档/节点/向量/模型契约，以及从 ingestion 到 query 的单一 RAG 编排骨架。
- **升级**：平台必须补足 provider 发现与版本、懒加载失败、资源所有权、超时/取消传播、持久化原子性、损坏恢复和失败证据；不能把当前 `StorageContext`、`asyncio.to_thread()` 或进程级 `Settings` 直接当作生产治理能力。
- **隔离**：LlamaIndex 的 agent/chat/workflow/memory、第三方默认 fallback 和每个 integration 的专有语义不进入第二 RAG 链路；它们只能作为 L4 或 provider 适配参考。
- **未验证**：当前核对只完成静态源码映射，未安装依赖、未执行 core/integration 测试、未对 621 个 provider 做真实外部服务验证；不声称 L0-L4 平台能力已经实现。

---

**首轮结论**：`llama_index` 的稳定底座是 `llama-index-core` 的数据模型/转换/索引/检索/合成/存储契约；具体模型、向量库、读取器和工具通过 621 个独立 integration 包解耦；`llama-index-instrumentation` 与 `llama-dev` 分别承担观测和仓库工程自动化。当前本地源码可完成静态架构建档，但 Git 远程已前进、代码图不可用、全量测试和构建尚未执行，后续复核必须保留这些边界。
