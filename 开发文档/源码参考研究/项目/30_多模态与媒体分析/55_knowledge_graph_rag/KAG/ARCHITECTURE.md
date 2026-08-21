# KAG 架构档案

> 本文件是本地源码参考库中 KAG 副本的首轮架构事实档案。只记录当前源码、配置、测试和远程版本事实；不承担生产设计、不替代上游文档，也不修改源码实现。

## 1. 项目身份与版本锚点

| 项目 | 事实 |
|---|---|
| 项目 | KAG（Knowledge Augmented Generation） |
| 上游 | OpenSPG/KAG，OpenSPG 团队 |
| 本地根目录 | `/Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/55_knowledge_graph_rag/KAG` |
| Python 包名 | `openspg-kag`（见 `setup.py`） |
| Python 入口 | `kag = kag.bin.kag_cmds:main`；`knext=knext.command.knext_cli:_main` |
| 当前版本 | `0.8.0`（`KAG_VERSION`） |
| 许可证 | Apache-2.0（`LICENSE`、`README.md`） |
| 远程仓库 | `https://github.com/OpenSPG/KAG.git` |
| 本地 Git HEAD | `fdab15b3929d2ee40dfcdd388f90233096a6afc9`，提交信息为 `Fix McpExecutor kag_project_config initialization for MCP HTTP store_path (#736)` |
| 远程 `master` | `fdab15b3929d2ee40dfcdd388f90233096a6afc9`；本地 HEAD 与远程 `master` 一致 |
| 本地仓库状态 | shallow clone；本轮新增本文件，并人工吸收此前细粒度研究稿；未修改源码、依赖、测试或配置 |
| 代码规模快照 | 736 个 `*.py`、47 个 `*.yaml`、5 个 `*.yml`、32 个 `*.json`、252 个 `*.md`；`kag/` 914 个文件，`knext/` 187 个文件，`tests/` 60 个文件（排除 `.git`、缓存） |

### 一句话定位

KAG 是建立在 OpenSPG 引擎和大语言模型之上的专业领域知识增强生成框架：构建侧把非结构化/结构化数据、领域 schema 与知识抽取结果写入 SPG 图，并保留知识到原文 chunk 的互索引；推理侧把自然语言问题转成逻辑形式或任务 DAG，混合执行图检索、文本检索、数学计算、LLM 语义推理和 MCP 工具调用。

## 2. 总体边界与分层

```text
┌────────────────────────────────────────────────────────────┐
│ kag.bin / kag.solver.server / kag.mcp.server                │ 运行入口
├────────────────────────────────────────────────────────────┤
│ kag.solver                                                │ 规划、管道、执行器、生成、报告
│   Planner → Task/DAG → Executor → Generator → Reporter    │
├────────────────────────────────────────────────────────────┤
│ kag.builder                                               │ 知识库构建流水线
│   Scanner → Reader → Splitter → Extractor → Vectorizer    │
│   → PostProcessor/Aligner → Writer                        │
├────────────────────────────────────────────────────────────┤
│ kag.interface / kag.common                                │ ABC、注册表、配置、缓存、上下文、LLM/向量模型
├────────────────────────────────────────────────────────────┤
│ kag.indexer / kag.common.tools                            │ 索引管理与检索算法工具
├────────────────────────────────────────────────────────────┤
│ knext                                                     │ OpenSPG SDK：schema/project/graph/search/reasoner/
│                                                           │ thinker/builder 的 REST 客户端与模型
└────────────────────────────────────────────────────────────┘
                 HTTP REST → OpenSPG 服务端（默认 8887）
                 Reasoner → Java 符号推理服务 / 图存储
```

### 2.1 `kag/` 与 `knext/` 的职责边界

- `kag/` 是 KAG 业务编排层，负责知识构建、检索、推理、MCP、评测与公共抽象。
- `knext/` 是 OpenSPG 客户端 SDK，负责 REST API、请求/响应模型、schema DSL/模型、项目与图服务访问；不承担 KAG 的问答编排。
- KAG 不包含 OpenSPG Java 推理引擎源码；`ReasonerClient` 只通过 REST 提交 DSL，Java runner 和图存储属于外部运行时。

## 3. 构建侧：KAGBuilder 数据流

主要入口：`kag/builder/main_builder.py::BuilderMain`；运行器：`kag.builder.runner.BuilderChainStreamRunner`。

```text
数据源
  ↓
Scanner（目录、文件、CSV、JSON、ODPS、SLS、语雀）
  ↓
Reader（txt、md、pdf、docx、表格等）
  ↓
Splitter（长度、大纲、模式、语义、表格）
  ↓
Extractor
  ├─ schema_free_extractor              无 schema 抽取
  ├─ schema_constraint_extractor        schema 约束的实体/关系/事件抽取
  ├─ knowledge_unit_extractor           知识单元与互索引抽取
  ├─ chunk_extractor / table_extractor  chunk / 表格
  ├─ summary_extractor / naive_rag_extractor
  └─ outline_extractor                  先抽大纲，再按语义切片
  ↓
Vectorizer（文本/多模态批量向量化）
  ↓
PostProcessor / SPGAligner / KAGAligner（对齐、归并、去重）
  ↓
Writer
  ├─ KgWriter        写 OpenSPG 图存储
  └─ MemoryGraphWriter
```

### 3.1 构建产物与互索引

- SPG 节点主要包含 Entity、Event、Concept、Standard、Index 五类；基础属性类型包含 Text、Integer、Float 等。
- `kag/builder/component/extractor/knowledge_unit_extractor.py` 先做 NER、实体/知识单元/三元组抽取，再将节点和 chunk 装配到子图。
- `assemble_sub_graph_with_chunk` 给实体和知识单元添加指向 chunk 的 `source` 边；chunk 的 `content` 保存标题与全文。
- 互索引形态为“知识/实体 → 原文 chunk”，同一图结构支持由知识命中原文引用，也支持由文本反查知识。
- `SPGAligner` 依据 `spg_type_name#name` 合并记录，处理多值与非基础类型属性；`KAGAligner` 以 Node/Edge 相等性去重。
- `append_official_name` 用标准化提示词生成 `official_name`，并用 `OfficialName` 边表达别名到正式名的关系。

## 4. Schema 与领域知识模型

主要位置：

- DSL 解析：`knext/schema/marklang/schema_ml.py`
- Schema REST 模型：`knext/schema/rest/models/`
- 约束抽取：`kag/builder/component/extractor/schema_constraint_extractor.py`
- SDK 会话：`knext/schema/client.py`

### 4.1 MarkLang

MarkLang 是缩进敏感的领域 schema DSL。解析层支持 `namespace`、类型定义/继承、属性、关系、约束、索引和逻辑规则。代码中按 `IndentLevel(0..5)` 处理 Type → TypeMeta → Predicate → PredicateMeta → SubProperty → SubPropertyMeta。

- 约束类型：`NOT_NULL`、`MULTI_VALUE`、`ENUM`、`REGULAR`。
- 索引类型：`Text`、`Vector`、`SparseVector`、`TextAndVector`、`TextAndSparseVector`。
- 关系包含普通关系和语义关系：`SYNANT`、`CAU`、`SEQ`、`IND`、`INC`、`USE`；源码用如 `CAU#leadTo` 的前缀表达语义类别。
- `check_semantic_relation` 对语义关系的主客体类型进行约束，例如 SYNANT 仅允许 Concept↔Concept，CAU 约束 Concept/Event，SEQ 要求同型。
- `diff_and_sync` 将 schema 变更归纳为 create/delete/update；继承类型的属性变更和父类型/枚举变更有保护性处理，必要时先删后建。
- `SchemaConstraintExtractor` 的输出索引为 `spo_graph_index` 与 `chunk_index`，把 schema 约束直接传递到抽取和检索阶段。

## 5. 推理侧：Solver 主链路

入口：`kag/solver/main_solver.py::SolverMain`、异步函数 `qa`；服务包装：`kag/solver/server/main_server.py::KAGSolverServer`。

```text
SolverMain.invoke / SolverMain.ainvoke
  ↓ asyncio.run / qa
读取主配置与 task/kb 配置
  ↓
按 kb_project_ids 建立 {task_id}_{kb_project_id} 的任务级 KAGConfigMgr
  ↓
KAGIndexManager.from_config → 构造 retriever 配置
  ↓
SelfCognitionPipeline（自认知/身份类问题直接回答）
  ↓（未拦截时）
SolverPipelineABC.from_config
  ↓
Planner → Task/DAG → 同层 asyncio.gather
  ↓
Executor（混合检索 / 数学 / Deduce / Output / MCP）
  ↓
Generator（带历史任务结果和引用）
  ↓
Reporter（trace、图证据、引用、最终答案）
```

`qa` 会设置 `KAG_PROJECT_CONF.host_addr` 与语言，按 `kb` 配置初始化项目、namespace、LLM、vectorizer 和 index_list；每个知识库配置放入 `KAG_QA_TASK_CONFIG`（`LinkCache(maxsize=100, ttl=300)`），避免不同任务配置互相污染。异常在顶层转为中英文安全提示并写入 reporter；最后始终 `reporter.stop()`。

### 5.1 Pipeline 配置

配置目录：`kag/solver/pipelineconf/`。`main_solver.py::load_yaml_files_from_conf_dir` 按 `pipeline_name` 加载 YAML，`get_pipeline_conf` 扫描 `{chat_llm}`、`{vectorize_model}`、`{retrievers}` 等占位符并从运行配置替换；缺失占位符 fail-fast。

| `pipeline_name` | 主要用途 | Planner/Executor/Generator |
|---|---|---|
| `think_pipeline` | 深度逻辑推理 | `kag_static_pipeline` + `lf_kag_static_planner` + 混合检索/数学/Deduce/Output + `llm_index_generator` |
| `mcp_pipeline` | 外部 MCP 工具协同 | `kag_static_pipeline` + `mcp_planner` + 动态 `mcp_executor` + `llm_generator` |
| `default_pipeline` | 轻量 RAG | `naive_rag_pipeline` + 混合检索 + `llm_index_generator` |
| `index_pipeline` | 索引/引用导向 | `index_pipeline` + 混合检索 + `llm_index_generator` |
| `self_cognition_pipeline` | 自认知拦截 | 在主 Solver 中先执行，不作为普通问答管道的最终阶段 |
| `kag_thinker_pipeline` | Thinker 适配 | 通过配置选择，Reporter 映射到 `kag_open_spg_reporter` |

### 5.2 静态规划与任务 DAG

`kag/solver/pipeline/kag_static_pipeline.py::KAGStaticPipeline` 是主要编排器：

1. `planning` 调用 `PlannerABC.ainvoke`，最多由 tenacity 重试 3 次。
2. 规划结果加入 `Context`，`Context.gen_task(group=True)` 按依赖关系分组。
3. 每组用 `asyncio.gather` 并行执行；`execute_task` 可先做 query rewrite，再按 `executor.schema()["name"]` 选择执行器。
4. `GeneratorABC.ainvoke` 汇总答案。
5. `max_iteration > 1` 时，答案包含 `unknown` 或 `finish_judger` 判定未完成会重试整轮。

### 5.3 逻辑形式（LF）

主要文件：`kag/solver/planner/lf_kag_static_planner.py`、`kag/solver/prompt/logic_form_plan.py`、`kag/common/parser/logic_node_parser.py`。

支持的核心算子：

- `Retrieval(s=s1:类型[实体], p=p1:边, o=o1:类型, s.prop=值)`：图/属性检索。
- `Math(content=[...], target=...)->alias`：数学计算。
- `Deduce(op=judgement|entailment|extract|choice|multiChoice, content=[...], target=...)->alias`：LLM 语义推断。
- `Output(alias)`：输出变量。

解析器把 LLM 的 Step/Action 文本转为 `LogicNode` 子类（`GetSPONode`、`MathNode`、`DeduceNode`、`GetNode`、`SearchNode`），变量首次引用包含类型和名称，后续引用使用别名；`std_logic_form` 结合 schema 中英映射将类型和索引标准化。

## 6. 检索与混合执行

主要位置：`kag/solver/executor/retriever/`、`kag/indexer/`、`kag/common/tools/algorithm_tool/`。

默认 `KAGFlow` 以 networkx DAG 编排：

```text
kg_cs（实体链接 + 约束一跳，阈值约 0.9）
  ↓ 命中时可 break 短路
kg_fr（模糊一跳 + PPR chunk，阈值约 0.8）
  ↓
rc（向量 chunk，top_k 约 20）
  ↓
kag_merger（归一化、加权融合、可选 LLM summary）
```

- `kag_hybrid_retrieval_executor` 按 retriever priority 分组；组内使用线程池并发。
- `kag_merger` 对多路结果做 min-max 归一化和 alpha 加权，并可从 SPO/chunk 生成 summary。
- `chunk_retrieved` 与 SPO 检索共享互索引图，`ppr_chunk_retriever` 负责从知识节点回溯文本。
- `index_list` 由知识库构建阶段声明，`KAGIndexManager.from_config` 按索引类型构造 retriever；`default_pipeline` 会强制只用 `chunk_index`。

## 7. MCP 内外双向集成

### 7.1 KAG 作为 MCP Server

文件：`kag/mcp/server/kag_mcp_server.py::KagMcpServer`。

- 依赖 `mcp` 惰性检查，未使用 MCP 管道时不要求导入成功。
- transport 支持 `sse`（默认端口 3000）和 `stdio`。
- 支持工具：`qa-pipeline`、`kb-retrieve`；`--enabled-tools all` 可全部启用，默认 `qa-pipeline`。
- `qa-pipeline` 调 `EvalQa` 的 solver pipeline；`kb-retrieve` 构造 `kag_hybrid_executor`，返回 summary 与 references JSON。

### 7.2 KAG 作为 MCP Client

文件：`kag/solver/executor/mcp/mcp_executor.py::McpExecutor`、`mcp_client.py`、`kag/solver/pipeline/mcp_pipeline.py`。

- `mcp_pipeline` 读取 `kb[0]["mcp_servers"]`，为每个 server 生成 `mcp_executor`。
- `McpExecutor.download_data` 对 `http(s)` `store_path` 下载到 `ckpt_dir/mcp_service`，本地路径原样使用。
- `MCPClient.connect_to_server` 用 `StdioServerParameters` 和 `AsyncExitStack` 管理会话；只支持 `.py`（`sys.executable`）或 `.js`（`node`）外部服务。
- `process_query` 先 `list_tools`，把工具 schema 转为 OpenAI function calling，LLM 选择工具后循环 `call_tool`，再把结果回填消息生成最终回答；每个查询会话负责连接和清理子进程。

## 8. `knext/` SDK 与外部服务契约

### 8.1 REST 客户端

`knext/common/rest/api_client.py::ApiClient` 为 OpenAPI Generator 生成的通用客户端，负责：路径/query/header/body 序列化、同步/线程池异步请求、响应反序列化、文件处理、连接池关闭。各域的 `rest/*_api.py` 通过它访问服务端。

主要 API 域：

| 域 | 入口/客户端 | 作用 |
|---|---|---|
| Project | `knext/project/client.py`、`project/rest/project_api.py` | 项目、namespace 与配置 |
| Schema | `knext/schema/client.py`、`schema/rest/schema_api.py`、`concept_api.py` | SPG 类型、属性、关系、约束、schema 同步 |
| Graph | `knext/graph/client.py`、`graph/rest/graph_api.py` | 图节点/边/写入查询 |
| Search | `knext/search/client.py`、`search/rest/search_api.py` | 文本、向量、自定义检索 |
| Reasoner | `knext/reasoner/client.py`、`reasoner/rest/reasoner_api.py` | DSL/规则推理、任务与结果表 |
| Thinker | `knext/thinker/client.py`、`thinker/rest/thinker_api.py` | Thinker 任务提交与响应 |
| Builder | `knext/builder/client.py`、`builder/rest/builder_api.py` | 构建任务 API |

### 8.2 Reasoner 边界

`knext/reasoner/client.py::ReasonerClient`：

- 初始化时从 `SchemaSession` 缓存中加载 Concept、Entity、Event、Index 类型。
- `generate_graph_connect_config` 读取 `KAG_GRAPH_STORE_URI`、`KAG_GRAPH_STORE_USER`、`KAG_GRAPH_STORE_PASSWORD`、`KAG_GRAPH_STORE_DATABASE`、namespace；未配置时回退本地图存储常量。
- `syn_execute` 将 DSL 包入 `ReasonTask`，调用 `reason_run_post`；`execute` 可将完成任务的结果表写为 CSV。
- Java 符号引擎和图数据库不在本仓库中，故只能确认 REST/DSL 边界，不能从本仓库确认引擎内部执行细节。

## 9. 配置、依赖与运行入口

### 9.1 配置来源

`kag/common/conf.py` 的 `KAGConfigMgr`/`KAGConfigAccessor` 是配置中心：

- 本地配置：向父目录查找 `kag_config.yaml`，先用 Jinja2 渲染环境变量，再 `yaml.safe_load`。
- 生产配置：若有 `KAG_PROJECT_ID` 与 `KAG_PROJECT_HOST_ADDR` 且未指定本地文件，通过 `ProjectClient` 从 OpenSPG 服务端读取项目配置。
- 全局字段：project id、host addr、biz scene、language、namespace、checkpoint_path、user_token。
- 任务级配置：`KAG_QA_TASK_CONFIG`，key 通常为 `{task_id}_{kb_project_id}`，TTL 300 秒。
- 支持 `!ENV` YAML 标签和 `KAG_DEBUG_DUMP_CONFIG` 调试输出。

关键环境变量还包括：`KAG_GRAPH_STORE_URI`、`KAG_GRAPH_STORE_USER`、`KAG_GRAPH_STORE_PASSWORD`、`KAG_GRAPH_STORE_DATABASE`、`KAG_PROJECT_NAMESPACE`。

### 9.2 依赖分组

`requirements.txt` 为运行时依赖声明，核心类别如下：

- 编排/配置：`PyYAML`、`ruamel.yaml`、`Jinja2`、`networkx`、`tenacity`、`cachetools`、`portalocker`。
- LLM/模型：`openai`、`dashscope`、`ollama`、`numpy`、`pandas`。
- 文档/文本：`python-docx`、`pypdf`、`PyPDF2`、`pdfminer.six`、`markdown`、`jieba`、`nltk`。
- 服务/数据：`requests`、`httpx`、`aiofiles`、`neo4j`、`pyodps`、`aliyun-log-python-sdk`、`zodb`。
- MCP/工具：`mcp==1.6.0`、`pyvis`、`gitpython`、`json_repair`。
- 版本约束同时包含 Python 3.8+（`setup.py`）和 README 推荐 Python 3.10 环境；实际部署还依赖 OpenSPG 服务与其图/推理运行时。

### 9.3 入口

- `python setup.py`：安装包与 console scripts。
- `kag`：`kag.bin.kag_cmds:main`，统一命令入口。
- `knext`：`knext.command.knext_cli:_main`，SDK CLI。
- `kag/builder/main_builder.py`：直接构造 `BuilderMain` 并调用构建 runner。
- `kag/solver/main_solver.py`：`SolverMain.invoke/ainvoke`。
- `kag/solver/server/main_server.py`：FastAPI `/process`，用 `AsyncTaskManager` 提交/查询任务。
- `kag/mcp/server/kag_mcp_server.py`：KAG MCP Server。
- `upload_dev.sh`：构建 sdist/wheel 后 `twine upload dist/*`；`build.sh` 仅执行 `python setup.py sdist bdist_wheel`。

## 10. 测试与验证覆盖

测试配置：`pytest.ini`。

- 测试根目录：`tests`；匹配 `test_*.py` 与 `*_test.py`；测试函数 `test_*`。
- 默认 pytest 参数开启 verbose、short traceback、coverage（`--cov=kag`），并忽略 `tests/unit/solver` 的递归收集。
- 当前仓库盘点到 19 个 `test_*.py` 单元测试文件，覆盖 common、registry、LLM、vectorize model、配置、checkpointer、builder runner、scanner/reader/splitter/extractor/mapping/post_processor/writer、planner 与 logic form executor。
- 测试数据包含 txt/md/json/csv/docx/pdf、节点/边 JSON 和多套 `kag_config.yaml`，说明构建侧文件处理和 planner 逻辑形式是主要回归面。
- 未将真实 OpenSPG 服务、Neo4j、Java reasoner 或外部 LLM 当作本地单元测试前提；涉及这些组件的路径需要外部服务/凭据/运行配置。
- 本轮按只读建档边界未安装依赖、未启动服务、未运行测试、未构建 wheel；因此本文件不宣称当前环境端到端可运行。

## 11. 目录地图（真实顶层）

```text
KAG/
├── kag/                       # KAG 业务框架（914 文件）
│   ├── bin/                   # kag CLI 与命令
│   ├── builder/               # 知识构建流水线
│   ├── common/                # 配置、缓存、LLM、向量、注册表、工具
│   ├── indexer/               # 索引管理与 retriever 配置
│   ├── interface/             # Builder/Solver/Executor/Planner/Prompt 等 ABC
│   ├── mcp/                   # MCP Server
│   ├── open_benchmark/        # 2wiki、musique、hotpotqa、prqa、AffairQA 等评测
│   ├── solver/                # pipeline、planner、executor、generator、reporter、server
│   └── ...                    # 示例共用模块与辅助能力
├── knext/                     # OpenSPG SDK（187 文件）
│   ├── builder/               # builder REST 客户端
│   ├── common/                # OpenAPI REST、cache、base client
│   ├── graph/                 # 图 API
│   ├── project/               # 项目 API
│   ├── reasoner/              # reasoner API/client/model
│   ├── schema/                # schema REST、MarkLang、模型
│   ├── search/                # 搜索 API/client/model
│   └── thinker/               # Thinker API/client/model
├── tests/                     # 单元测试与夹具（60 文件）
├── docs/                      # quickstart/release_notes 等少量文档
├── kag/solver/pipelineconf/   # 深度、MCP、naive RAG、retriever 等 YAML
├── README.md                  # 上游定位、快速开始、技术架构、版本说明
├── README_cn.md / README_ja.md
├── ARCHITECTURE.md            # 本项目唯一架构事实源
├── setup.py / requirements.txt / setup.cfg / pytest.ini
├── KAG_VERSION / LICENSE / CITATION.cff / LEGAL.md
└── build.sh / upload_dev.sh
```

## 12. 关键调用链索引

### 构建

`BuilderMain.invoke` → `BuilderChainStreamRunner.from_config` → `BuilderChainStreamRunner.invoke` → scanner/reader/splitter/extractor/vectorizer/post-processor/writer。

### 普通问答

`SolverMain.invoke` → `qa` → `KAGConfigMgr`/`ProjectClient`/`KAGIndexManager` → `SelfCognitionPipeline` → `SolverPipelineABC.from_config` → `KAGStaticPipeline.ainvoke` → `PlannerABC.ainvoke` → `Context.gen_task` → `ExecutorABC.ainvoke` → `GeneratorABC.ainvoke` → `ReporterABC`。

### LF 图检索

`lf_kag_static_planner` → `ParseLogicForm.parse_logic_form_set` → `GetSPONode` → `kag_hybrid_retrieval_executor` → `KAGFlow`（kg_cs/kg_fr/rc/kag_merger）→ `ReasonerClient.syn_execute` / Search API → `llm_index_generator`。

### MCP

`mcp_pipeline` → `mcp_planner` → `McpExecutor` → `download_data` → `MCPClient.connect_to_server` → `list_tools` → LLM tool calling → `session.call_tool` → 结果回填 → generator。

### HTTP 服务

`KAGSolverServer._setup_routes` `/process` → `sync_task` → `AsyncTaskManager.submit_task` → `run_main_solver` → `SolverMain.invoke`；后续以 `query` 命令读取任务结果。

## 13. 已知风险、边界与未验证项

1. `py_code_based_math_executor` 执行 LLM 生成 Python；当前源码观察未发现完整的沙箱、命令白名单、网络隔离与强制超时闭环。
2. MCP `store_path` 支持 HTTP(S) 下载脚本后执行，当前链路未见内容签名、摘要校验或来源白名单；属于供应链风险。
3. MCP stdio 外部服务使用子进程，但当前源码边界未显示统一 sandbox、网络出口限制或资源配额。
4. 顶层 QA 异常提示会拼接异常文本；日志和返回面是否满足生产脱敏要求，需要结合部署层复核。
5. chunk 全文写入图节点并建立互索引，可能带来图存储、索引和复制放大；具体规模未在本地验证。
6. `knext` REST API 依赖 OpenSPG 服务端契约；本地没有服务端/Java reasoner，因此 schema diff、图写入、reasoner DSL、搜索 API 仅完成源码边界建档。
7. `mcp` 为惰性导入是优点，但 MCP Server/Client 的具体协议行为仍依赖运行时 `mcp` 版本；仓库声明 `mcp==1.6.0`。
8. `kag/interface/solver/` 还存在 `kag_memory_abc`、`kag_reflector_abc`、`kag_reasoner_abc` 等接口预留；本轮没有把它们解释成已落地能力。
9. 本地仓库为 shallow clone；版本比较已通过 4780 独立网络出口读取远程 `master`，未拉取或修改远程历史。

## 14. 可借鉴的架构模式（仅作参考，不直接搬运）

- **互索引证据链**：知识节点/实体通过显式 `source` 边连接原文 chunk，使推理结果可回溯原始上下文。
- **ABC + 注册表 + 配置装配**：`Registrable`、`@XXXABC.register`、`from_config` 形成组件发现与配置驱动装配闭环。
- **逻辑形式作为可审计中间表示**：Retrieval/Math/Deduce/Output 让规划、执行、重放与测试拥有稳定边界。
- **DAG 分层并行**：依赖层之间串行、同层 `asyncio.gather` 并行；检索器内部按优先级并发并在精确命中时短路。
- **任务级配置隔离**：`{task_id}_{kb_id}` 配置键避免多知识库问答共享全局可变状态。
- **可选依赖惰性导入**：MCP 仅在启用 MCP 能力时加载，非 MCP 管道不被额外依赖阻塞。
- **评测与工具复用**：`open_benchmark` 与 `qa-pipeline` 共用求解链，评测入口可以成为可复现工具入口。

## 15. 本轮结论

KAG 0.8.0 的稳定主干是“构建侧 SPG/互索引 + 推理侧逻辑形式混合求解”，`kag/` 负责业务编排，`knext/` 负责 OpenSPG REST/模型 SDK，YAML pipeline 和 ABC 注册表把组件装配连接起来。0.8.0 新增/强化的 MCP 是双向扩展面：KAG 可作为 MCP Server 被 Agent 调用，也可在推理过程中拉起外部 MCP 工具。真正运行依赖 OpenSPG 8887 服务、图存储/符号推理运行时和 LLM/向量模型；本地源码副本本身不包含这些外部系统。

本文件只允许作为后续源码参考、边界裁决和版本漂移对照入口；任何生产化复用都必须重新核对上游版本、依赖、服务端契约、安全边界和真实测试结果。

## 16. 第三轮通用底座映射：KAG 知识链路的唯一拆分

本节是基于 KAG 当前源码的第三轮底座输入，不是把 KAG 目录复制到系统工程平台，也不是宣称平台已经实现下述能力。事实证据来自本仓库源码路径和函数；所有“目标落点”“升级”“新建”“待核”均是后续需求登记、能力搜索、复用裁决、占用租约和验收契约的输入。

本轮必须先把 KAG 的一条知识增强链拆成三个职责面：**图存储/检索支持库**只提供原子 I/O 和检索 provider；**知识推理模块**只编排 schema、图知识、逻辑形式、检索、推理和工具语义；**运行核心**只负责任务、并发、超时、取消、崩溃恢复、资源和证据。L0 公共契约与 L4 项目适配/网关是上下边界，不能被三个职责面吞并。

### 16.1 单一知识链路总图

```text
L4 项目适配层 / CLI / HTTP / MCP Server / SDK
  → 唯一知识能力入口（请求、别名、权限、版本、结果归一化）
  → L3 运行核心（运行实例、任务 DAG、队列、租约、并发、截止时间、取消、恢复、证据）
  → L2 知识推理模块（schema 绑定、图知识构建命令、逻辑形式、规划、混合检索配方、推理/工具语义）
  → L1 图存储/检索支持库（图 CRUD、schema REST、文本/向量/自定义检索、PPR、事务/连接/索引 provider）
  → L0 公共契约（GraphNode/Edge/Chunk/SPO/Schema/LogicNode/Plan/Task/Result/Error/Resource/Evidence）
  → OpenSPG REST（默认 8887）/图存储/Java Reasoner/搜索索引/模型与 MCP provider
```

**当前源码对照：** `kag/builder/component/writer/kg_writer.py:31-165` 把 `SubGraph` 标准化后交给 `knext.graph.client.GraphClient.write_graph`；`knext/graph/client.py:27-95` 只封装图写入、顶点查询、一跳扩展和 PageRank；`knext/search/client.py:28-58` 只封装 text/vector/custom search；`knext/reasoner/client.py:28-137` 负责 schema session、DSL `ReasonTask` 提交和结果导出。它们适合 L1 边界，但不应直接成为 L2 业务流程或 L3 任务系统。

### 16.2 KAG 能力到三类职责的逐项裁决

| KAG 能力/事实 | 当前源码证据 | 图存储/检索支持库（L1） | 知识推理模块（L2） | 运行核心（L3） | 第三轮裁决 |
|---|---|---|---|---|---|
| 知识图谱节点/边/SubGraph | `kag/builder/model/sub_graph.py`；`kg_writer.py:82-135`；`GraphClient.write_graph:66-74` | `写入子图`、UPSERT/DELETE、namespace/项目参数化、事务结果 | “数据源→抽取→对齐→互索引→写入”知识构建流程 | 写入任务、批次、重试、幂等键、失败账本和恢复 | 吸收边界；L1 只做原子写，L2 保留知识语义，L3 统一任务治理 |
| 图节点查询/一跳/PPR | `GraphClient.query_vertex/expend_one_hop/calculate_pagerank_scores:36-95` | 参数化查询、PageRank、一跳、连接/超时/重连和结果模型 | 选择起点、约束、路径和证据解释 | 并发预算、取消、外部请求截止时间、资源回收 | 吸收并升级；不能让每个 retriever 直连 REST |
| Schema/MarkLang/约束/索引 | `knext/schema/marklang/schema_ml.py`；`SchemaSession:37-135`；`SchemaClient:138-217` | Schema REST 读写、版本/差异提交、缓存和服务错误 | 领域类型映射、抽取约束、逻辑形式标准化、schema 与检索索引选择 | schema 版本锁、发布/回滚、迁移任务和并发冲突 | L1/L2 分责；不能把 SchemaSession 当全局事实写 owner |
| 逻辑形式与中间表示 | `kag/common/parser/logic_node_parser.py:71-164,200-309,318-320`；`base_model.py:49-277` | 只提供序列化/校验原子能力（如适用） | `GetSPONode`、`MathNode`、`DeduceNode`、`GetNode`、`SearchNode` 与 alias/类型/依赖 | 逻辑节点实例化为受监督 task，状态、重试、取消和证据 | 吸收为 L0+L2；逻辑形式不是第二任务系统 |
| 规划与任务 DAG | `kag/solver/planner/lf_kag_static_planner.py:21-170`；`kag/solver/pipeline/kag_static_pipeline.py:29-177` | 不承载拓扑和调度 | LLM 生成计划、query rewrite、finish judge、执行器能力声明 | 依赖分组、同层并行、任务队列、最大迭代、截止时间和恢复 | 规划语义进 L2，唯一调度进 L3；禁止模块自建线程池 |
| 混合检索 | `kag/solver/executor/retriever/kag_hybrid_retrieval_executor.py:54-242`；`kag_hybrid_executor.py:196-220` | 图/文本/向量/custom/PPR 原子检索和 merger 算子 | `kg_cs→kg_fr→rc→kag_merger` 配方、优先级、短路、上下文选择、summary | retriever 并发、超时、失败隔离、结果上限和取消 | 吸收检索配方，升级 L1 provider 生命周期；不得复制多条对外检索链 |
| 语义推理/Deduce/Math | `kag_deduce_executor.py:14-167`；`py_based_math_executor.py:29-210` | 模型调用、代码隔离执行 provider、输出限制 | Deduce 操作语义、数学输入绑定、答案/alias 语义 | 子进程/进程组、硬截止、资源上限、异常与崩溃回收 | L2 吸收语义，L3 统一监督；当前 Python 代码执行安全不足，待核/不直接吸收 |
| OpenSPG Reasoner DSL | `ReasonerClient.syn_execute:105-137` | REST/HTTP、请求超时、响应解码、连接释放 | DSL 生成、schema 绑定、结果转 SPO/证据 | reason task 状态、轮询/超时/取消、服务崩溃重试和证据 | 吸收 API 边界；Java reasoner 内部实现仍是外部未验证 provider |
| MCP 工具执行 | `kag/solver/executor/mcp/mcp_executor.py:23-88`；`mcp_client.py` | HTTP/stdio transport、进程/会话句柄、协议编解码 | 工具 schema 选择、参数绑定、结果回填到推理上下文 | 外部服务下载校验、子进程组、超时/取消/崩溃清理、供应链证据 | L2 只保留工具语义；MCP transport 和进程治理进入 L1/L3，不能直连外部脚本 |

**核心拆分原则：** “图”是事实和证据的存储/检索介质，不是任务调度器；“逻辑形式”是可审计中间表示，不是持久化状态库；“Planner/Executor”是领域编排，不是通用运行核心；`knext` 是 SDK/provider 边界，不是知识模块的第二入口。

### 16.3 一条真实调用链的边界

```text
SolverMain.invoke/ainvoke
  → qa / KAGConfigMgr / KAGIndexManager
  → SelfCognitionPipeline 或 SolverPipelineABC
  → KAGStaticPipeline.planning
  → PlannerABC.ainvoke（例如 KAGLFStaticPlanner）
  → Context.gen_task(group=True)
  → L3 运行核心提交受监督 task（当前源码由 asyncio.gather 直接实现，尚未形成平台任务账本）
  → execute_task / query_rewrite
  → L2 Executor（Retrieval / Math / Deduce / Output / MCP）
  → L1 GraphClient/SearchClient/ReasonerClient/模型或工具 provider
  → RetrieverOutput / LogicNode alias / Task.result
  → Generator → Reporter（引用、trace、图证据）
  → L4 响应/流式投影
```

当前 `KAGStaticPipeline.ainvoke:127-177` 每轮新建内存 `Context`，按 `context.gen_task(group=True)` 将同组 task 交给 `asyncio.gather`，规划与单任务执行均最多 tenacity 重试三次；这证明了 DAG 与重试语义，但不证明持久任务、硬截止、取消或崩溃恢复。`KAGHybridRetrievalExecutor.do_retrieval:127-242` 组内使用 `ThreadPoolExecutor`，按优先级收集结果，异常只记录日志并继续，命中图/chunk/doc 后短路；因此“有输出”不等于所有 retriever 成功，失败必须进入统一结果和证据契约。

## 17. 数据、模型、缓存与任务资源契约

### 17.1 数据与事实 owner

| 数据对象 | 当前事实 | 唯一写/读边界 | 资源与一致性要求 |
|---|---|---|---|
| 原始文件、文档、表格、chunk | Builder Scanner/Reader/Splitter/Extractor；chunk 作为图节点属性并由 `source` 边互索引（现有 §3.1） | L2 构建模块提交；L1 文件/图 provider 执行 | 原文、chunk、摘要、向量、图节点要区分；大文本应支持引用/上限，不能静默复制 |
| SPG Node/Edge/SubGraph | `KGWriter.standarlize_graph:82-102` 给 label 加 namespace、非字符串属性 JSON 化；`write_graph:104-135` 提交 | L1 图支持库是原子写 owner，L2 负责语义和幂等键 | UPSERT/DELETE、事务边界、部分批次、冲突、重试和回读必须可证明 |
| Schema/类型/谓词/约束/索引 | `SchemaSession` 在内存中持有 `_alter_spg_types`，`commit:100-135` 一次提交 draft；`SchemaCache` TTL 300 | Schema 支持库负责 REST；L2 只提出变更/绑定；发布与版本由 L3/控制面治理 | Schema 版本、namespace、迁移兼容和缓存失效必须显式；缓存不是真实 schema owner |
| 检索结果/SPO/chunk/reference | `RetrieverOutput`、`KgGraph`、`KAGRetrievedResponse`；`to_reference_list:36-86` 生成图/文档引用 | L1 返回候选；L2 merger/summary/证据转换；L4 只投影 | 结果必须含来源、索引、分数/路径、schema 版本和截断标记；空结果与失败不同 |
| 逻辑形式/Task/alias | `LogicNode` 及其子类；`Task.update_memory/update_result`（`kag/interface/solver/base_model.py` 后段） | L2 维护语义；L3 维护 task 状态、尝试次数、租约和终态 | alias 只在一次 run/plan 命名空间内有效；恢复不能依赖进程内对象仍存在 |

### 17.2 模型与工具资源

| 资源 | 当前实现 | 第三轮契约/落点 |
|---|---|---|
| Chat LLM / planner / generator / deduce | `LLMClient.from_config` 在多个 executor/planner 内按配置创建；`KAGLFStaticPlanner` 直接 `llm.ainvoke` | L1 模型 provider 统一能力、模型版本、token/并发、超时、错误码和用量；L2 只传 prompt/结构化输入；L3 监督调用和取消 |
| 向量化/重排模型 | `kag/common/vectorize_model/`、`interface/common/vectorize_model.py` 等注册/配置路径 | L1 模型支持库；批量、维度、模型摘要、缓存键和 provider 隔离必须统一；不能由 `rc` 自己创建另一套模型 registry |
| Python 数学代码 | `run_py_code:29-61` 写临时 `.py`，`subprocess.run` 默认 timeout 5 秒，捕获 stdout/stderr 后删除文件 | 只能作为隔离 provider 候选；必须进独立进程组、资源/输出限制、无网络/文件边界和 SIGTERM→SIGKILL 回收；当前源码不足以生产吸收 |
| MCP server 文件/HTTP 下载 | `McpExecutor.download_data:48-77` 下载到 `ckpt_dir/mcp_service` 后交 `MCPClient`；当前未见签名/摘要/来源白名单 | L1 transport + L3 子进程/进程组治理；L4 只传已登记工具引用；下载必须内容摘要、来源策略、缓存隔离和清理，否则标供应链阻断 |
| HTTP REST/连接池 | `knext.common.rest.ApiClient` 及生成 API 支持 `_request_timeout`；Graph/Search/Reasoner 客户端持有 `_rest_client` | L1 transport 统一连接、超时、响应上限、重试/不可重试错误、close；L2 不持有裸连接对象穿透契约 |

### 17.3 缓存与任务资源的分责

`knext/common/cache.py:15-42` 的 `LinkCache` 与 `SchemaCache` 都是 TTLCache；`kag/common/conf.py:202-239` 的 `KAG_QA_TASK_CONFIG` 是 `LinkCache(maxsize=100, ttl=300)`，按 `{task_id}_{kb_project_id}` 隔离任务配置。`kag/common/checkpointer/base.py:19-190` 另有文件 checkpoint 和进程内 `CheckpointerManager`，按配置哈希复用对象；二者都不能直接当平台任务账本或图事实库。

| 资源类别 | 当前 owner/位置 | 目标唯一 owner | 必须验证 |
|---|---|---|---|
| 配置缓存 | `KAG_QA_TASK_CONFIG`、`KAGConfigAccessor` | L3 运行实例/配置快照；L2 只读不可变快照 | TTL、任务隔离、配置变更失效、敏感字段不落日志 |
| Schema 缓存 | `reason_cache`/`SchemaCache`（按 project id） | L1 schema provider + L3 版本锁 | 并发刷新、旧版本拒绝、服务断线、关闭释放 |
| Builder checkpoint | `CheckpointerManager` + txt/bin checkpointer | L1 checkpoint provider；L3 决定提交/恢复时机 | key 幂等、部分写、关闭、损坏、跨进程并发、恢复读回 |
| LLM/vector/rerank 缓存 | 配置/模型实现分散，未见统一 owner | L1 模型支持库 | 模型版本/输入摘要/namespace/TTL/容量/失效，不能缓存错误为成功 |
| task/context/alias | `Context`、`Task`、`asyncio.gather` 内存态 | L3 任务账本、运行快照、租约和证据 | 重启恢复不依赖内存；同层并发、重复提交和任务终态可读回 |
| HTTP/MCP/子进程 | `ApiClient`、`MCPClient`、数学 `subprocess` | L1 transport + L3 资源监督 | 正常/失败/超时/取消/崩溃四终态均无连接、线程、进程、临时文件残留 |

## 18. 失败、超时、取消与崩溃矩阵

| 节点/场景 | 当前源码语义 | 真实缺口/风险 | 底座验收与目标落点 |
|---|---|---|---|
| LLM 规划失败 | `KAGStaticPipeline.planning:68-86` 和 planner `invoke:128-146` 最多重试 3 次，最后抛出 | 无统一错误码、预算、退避证据；异步规划路径与同步重试语义不完全对称 | L2 返回可重试分类；L3 记录 attempt、deadline、prompt/model 摘要，耗尽后终态为 failed |
| 单 retriever 异常 | `do_retrieval:183-216` 捕获并日志记录，继续收集其他结果 | 失败可能被空结果掩盖；无法区分“无命中”和“provider 失败” | L1 返回 provider error；L2 按策略 partial/failed；L3 记录子任务终态和是否短路 |
| 全部检索为空 | hybrid executor 以空 `RetrieverOutput` 继续到 generator/summary | empty 可能被生成器伪装成“未知/无资料” | 统一 `NO_RESULT` 与 `RETRIEVAL_FAILED`；引用为空、模型失败、业务未知分开验收 |
| Reasoner/图服务断线 | REST 客户端调用直接抛异常（`GraphClient`、`ReasonerClient`） | 本地无 OpenSPG/Java reasoner，断线、重试、幂等和服务端任务终态未实测 | L1 连接/读超时/重试契约；L3 取消外部任务或标记 orphan 并对账；不得只重试写操作 |
| Math 代码超时 | `run_py_code:42-61` `subprocess.run(timeout=5)` 捕获 `TimeoutExpired`，finally 删除临时文件 | 未显式进程组 kill；子进程树、网络、资源上限和取消传播未证明 | L1/L3 独立进程组、硬截止、SIGTERM→SIGKILL、stdout/stderr 上限、残留检查；当前标待核/阻断 |
| Math 代码异常 | stderr 返回到上层，`PyBasedMathExecutor` 重试生成代码 | LLM 生成代码是高风险执行面，当前无完整沙箱/白名单/网络隔离 | 只能在受管隔离 provider 通过；失败不可回写为成功 alias |
| MCP 连接失败 | `McpExecutor.ainvoke:79-88` 连接异常后 cleanup 并记录 error，但随后仍调用 `process_query` | 连接失败可能进入二次异常；外部脚本下载与执行缺签名/资源边界 | L2 工具失败终止当前 task 或按显式 fallback；L3 取消/回收 session/process；L4 不允许绕过唯一工具入口 |
| MCP 客户端断线/取消 | `MCPClient` 使用 `AsyncExitStack` 管理会话（现有 §7.2） | 未见统一 run deadline、取消 token、子进程组回收证据 | 取消须关闭 stream/session/process；崩溃后读回无残留、无 orphan 工具进程 |
| generator/finish judge 失败 | hybrid summary 和 planner finish judge 有 tenacity/异常兜底，部分路径打印后继续 | “兜底答案”可能掩盖模型失败；无统一 partial result 语义 | L2 固定 `success/partial/unknown/failed`；L3 记录生成与检索各自终态，禁止以最终字符串判成功 |
| 任务进程/线程崩溃 | `AsyncTaskManager.worker:33-80` 捕获普通异常写 failed；线程/进程崩溃恢复未闭合 | `future.result()` 无任务级 timeout/cancel；任务仅 TTLCache，重启丢失；全局 manager 导入即启动 | L3 持久任务账本、租约、心跳、超时/取消/重启恢复；强杀后必须新进程恢复并清理租约/连接 |
| HTTP `/process` 断开 | `main_server.py:36-63` submit/query；submit 返回 task id，query 读缓存 | HTTP 200/已入队不等于业务成功；没有取消命令和断线策略 | L4 只投影 L3 状态；必须区分 accepted/running/success/failed/timeout/cancelled/crashed/expired |

**四种终态验收铁律：** 正常完成要读回结果和引用；业务失败要有稳定错误码和释放证据；主动取消/超时要证明子任务停止或被隔离并记录终态；宿主/子进程崩溃要在全新进程中恢复或明确不可恢复，且清理任务租约、连接、锁、临时文件和外部进程。日志、warning、HTTP 200、队列接收、SSE/流结束、TTLCache 中有记录都不是成功证据。

## 19. L0-L4 映射与防假绿验证契约

下表是平台映射等级，不是 KAG 官方分层。KAG 当前源码/测试存在只能证明“可研究”；没有外部 OpenSPG、图存储、Java Reasoner、LLM、向量模型和 MCP 服务的真实读回，不得越级为 L3/L4 通过。

| 层级 | 允许承载 | KAG 映射 | 本项目本轮状态 | 禁止伪装 |
|---|---|---|---|---|
| **L0 公共契约** | Schema、Graph、SPO、Chunk、LogicNode、Plan、Task、Result、Error、Run、Resource、Evidence 的字段/版本/错误/可重试/幂等/取消语义 | `knext` REST model、`base_model.py`、`RetrieverOutput`、`Task/Context` 的事实输入 | **部分可吸收/待冻结**；源码形状已取证，平台契约未登记 | 不放 HTTP、线程、数据库、LLM SDK、隐式 fallback |
| **L1 支持库/provider** | 图 CRUD、schema REST、text/vector/custom search、PPR、一跳、HTTP、checkpoint、模型、MCP transport、隔离执行 | `GraphClient`、`SearchClient`、`ReasonerClient`、`KGWriter`、checkpointer、模型与 MCP 客户端 | **候选能力命中；真实 provider 未验证** | 不做知识去重/规划/答案生成，不拥有平台任务状态 |
| **L2 知识推理模块** | 构建流程、schema 约束、逻辑形式、Planner、检索配方、Deduce/Math/Tool 语义、引用与答案转换 | `kag/builder`、`kag/solver/planner`、`executor`、`generator/reporter` | **源码事实充分，可吸收语义** | 不直连第三方、不自建注册表/任务系统/重试账本、不旁路写图/状态 |
| **L3 运行核心** | 运行实例、DAG 调度、任务账本、队列、并发预算、超时、取消、租约、崩溃恢复、资源/证据 | 当前仅有 `asyncio.gather`、线程池、TTLCache、AsyncTaskManager 的局部实现 | **主要缺口/待平台登记** | 不解释图事实、schema 业务语义、Deduce 内容或工具选择 |
| **L4 接入与适配** | 项目配置、别名、权限、HTTP/MCP/CLI/SDK、请求/结果投影、部署 | `SolverMain`、`KAGSolverServer /process`、`KagMcpServer`、CLI | **边界可吸收；真实服务未验证** | 不复制 L2 编排、不直接改 L3 状态/图库、不拥有第二知识入口 |

### 19.1 分层验收工作包

1. **L0：** 静态检查每个输入/输出/错误/版本/幂等/超时/取消/资源字段；验证逻辑形式解析失败不会变成空成功，Schema/namespace 版本不可混用。
2. **L1：** 每个图、schema、search、reasoner、checkpoint、模型和 transport provider 至少有真实成功、空结果、非法参数、断线、超时、取消、重复写、资源释放和 provider 缺失证据；缺少外部服务记为 `HOST_UNAVAILABLE/UNVERIFIED`，不能用 skip 伪绿。
3. **L2：** 以固定 fixture 验证构建→图写入→图/文本/向量检索→SPO/chunk 引用→逻辑形式→Deduce/Math/Output→Generator 的结果对称性；验证 schema 约束、alias 依赖、优先级短路、partial failure、重复任务和 provenance。
4. **L3：** 同组并发、跨优先级并发、超时、取消、队列满、重复提交、任务 TTL、模型/图服务断线、进程强杀、重启恢复和零残留；恢复必须新进程读权威账本，不能复用父进程 `Context`。
5. **L4：** 冷启动配置装配、`/process submit/query`、KAG MCP Server/Client、CLI/SDK 结果形状、权限/项目/namespace 隔离和发布门禁；HTTP 200、task id、MCP tool list 或流结束只能算中间证据。

本轮实际验证仅为源码读取、文档落盘和文档结构检查；未安装依赖、未启动 OpenSPG/图数据库/Reasoner/LLM/MCP、未运行 KAG 测试或端到端服务。因此 L1-L4 不能写“通过”。

## 20. 不复制第二知识链路：唯一 owner 与禁止事项

KAG 同时存在 `kag/` 业务编排、`knext/` SDK、OpenSPG 服务端、图检索/文本检索/向量检索、Reasoner、MCP 和 checkpoint。第三轮不能把这些横向复制成平台的多套知识系统，必须收敛为以下一条链：

```text
项目适配/HTTP/MCP/CLI/SDK
  → 唯一知识能力入口
  → L3 运行核心（唯一任务/租约/重试/超时/取消/恢复/证据 owner）
  → L2 知识推理模块（唯一图知识/检索/推理/工具领域编排 owner）
  → L1 图存储/检索支持库（唯一 graph/search/schema/reasoner/provider 能力 owner）
  → 外部图存储、索引、模型、Reasoner、工具服务
```

1. **单一图事实写 owner：** `SubGraph→KGWriter→GraphClient.write_graph` 是候选写链；任何 HTTP/MCP/任务入口只能调用 L2 命令，不得直接写 Graph API 或旁路数据库。
2. **单一检索编排 owner：** 图精确、图模糊/PPR、chunk/vector/text/custom 仍是同一 L2 混合检索模块的策略；不能另建“向量知识库”“全文知识库”“Reasoner 知识库”三套对外能力。L1 可有多 provider，但能力 id、结果契约和调用器唯一。
3. **单一 Schema owner：** Schema REST/session/cache 属 L1；schema 约束、中文/英文类型映射和逻辑形式绑定属 L2；发布、版本、迁移和回滚属 L3/控制面。不能由 extractor、retriever、Reasoner client 各自维护 schema 真相。
4. **单一逻辑/任务 owner：** LogicNode 是 L0/L2 的中间表示；Task、attempt、run、deadline、cancel、lease、recovery 是 L3。不得把 alias、SPO 或图节点当任务状态，也不得把 `Context` 内存对象当恢复账本。
5. **单一模型入口：** planner、generator、Deduce、summary、vectorizer、reranker 只能经统一模型能力入口；不能每个 executor 自己建立 provider registry、错误翻译、重试和缓存。
6. **单一工具入口：** MCP 是工具 transport/provider；工具选择和参数绑定在 L2，进程/session/下载/超时/取消在 L1/L3，任何项目适配不能直接拉脚本或绕过工具审计。
7. **单一缓存职责：** 配置缓存、schema 缓存、模型结果缓存、checkpoint、运行状态彼此分责；不能用 TTLCache 代替权威状态，不能用 checkpoint 代替图事实或任务账本。
8. **禁止隐式 fallback：** provider 缺失、图服务断线、模型失败、索引未就绪、MCP 下载失败只能按契约失败/降级/重试；不得悄悄切到未登记内存图、第二向量库、第二模型或空结果成功。
9. **禁止目录机械迁移：** `kag/` 与 `knext/` 的文件不直接复制为平台平级目录；按上述职责拆分，保留原项目适配和回滚证据。
10. **历史兼容只在唯一入口归一化：** `qa-pipeline`、`kb-retrieve`、旧 executor 名、英文能力键如需兼容，只在 L4/唯一能力调用器映射到一个能力 id，不让每个消费者维护别名表。

## 21. 能力命中、缺口与装配计划

| 工作包 | 当前命中 | 目标落点 | 动作 | 进入条件与最小验收 |
|---|---|---|---|---|
| A 图存储与图查询 | `GraphClient`、`KGWriter`、`ReasonerClient`、`SearchClient` | L1 图存储/检索支持库 + provider | 新建/升级候选能力，不复制 KAG 编排 | 冻结图 CRUD、schema、PPR、一跳、参数化查询、事务、断线、超时、命名空间、关闭 |
| B Schema/逻辑形式 | MarkLang、`SchemaSession`、`LogicNode`、`ParseLogicForm` | L0 契约 + L2 知识推理模块 | 吸收数据结构和解析语义，升级版本/错误/可审计字段 | 非法 schema/LF、类型映射、alias 依赖、版本冲突、序列化往返 |
| C 混合检索 | `KAGFlow`、`kg_cs/kg_fr/rc/kag_merger` | L1 原子检索 + L2 唯一检索模块 | 升级已有检索支持能力；不建第二知识链 | 图/文/向量结果、短路、融合、空结果、部分失败、引用读回和并发 |
| D 规划与推理 | `KAGStaticPipeline`、LF planner、Math/Deduce/Output | L2 知识推理模块 + L3 受监督任务 | 吸收规划/逻辑/推理语义；调度从模块剥离 | 固定 plan fixture、依赖分组、重写、重试、终止、partial/unknown/failed 语义 |
| E 模型能力 | `LLMClient`、vectorizer/reranker 注册路径 | L1 模型支持库/provider | 复用唯一模型调用器；补版本/额度/超时/取消/缓存 | provider 缺失、限流、流断、超时、模型版本和资源释放 |
| F 工具执行 | `McpExecutor`、`MCPClient`、KAG MCP Server | L1 transport + L2 tool semantics + L3 process governance | 隔离兼容适配；不把 MCP 变成第二执行核心 | 来源/摘要/权限、stdio/http、工具 schema、取消、强杀、零残留 |
| G 运行治理 | `AsyncTaskManager`、`CheckpointerManager`、TTLCache | L3 运行核心 + L1 checkpoint/缓存 provider | 新建/升级治理能力，不能把现有线程池直接复用为平台任务系统 | 持久账本、租约、CAS/幂等、超时/取消/崩溃恢复、读回和证据 |

### 21.1 装配波次（仅计划，不表示已启动）

```text
波次 A：冻结 L0 Graph/Schema/SPO/Chunk/Logic/Plan/Task/Result/Resource/Evidence 契约
  → 做能力登记、搜索和复用/升级/新建裁决
波次 B：登记/升级 L1 图存储、检索、schema、reasoner、model、transport、checkpoint provider
  → 每 provider 独立环境、依赖锁、资源预算和 HOST_UNAVAILABLE 语义
波次 C：装配一个 L2 知识推理模块
  → 构建、schema 约束、LF、混合检索、Deduce/Math/Tool、引用统一走一个公开入口
波次 D：接入 L3 运行核心
  → task/run/attempt/lease、DAG、并发、截止、取消、恢复、资源和证据
波次 E：L4 适配与门禁
  → 配置/HTTP/MCP/CLI/SDK 别名只映射唯一入口；冷启动、故障注入、读回和发布门禁
```

任何波次开工前必须有需求登记、能力搜索、复用裁决、占用租约、消费者验收契约和装配计划；本文件不授权直接修改平台生产底座。

## 22. 第三轮验证边界、MCP 状态与结论

| 证据项 | 本轮事实 | 结论 |
|---|---|---|
| 目标项目 | `/Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/55_knowledge_graph_rag/KAG` | 路径已核对 |
| MCP 实例 | 首次 `project_context` 返回 `project_toolkit`，但错误绑定到 `/Users/hekunhua/Documents/Agent/PHP/华世王镞_v3`；未将其内容作为 KAG 证据 | 错绑事实保留，不能宣称正确项目上下文 |
| 代码图 | `codegraph_explore` 返回 KAG 未建立 `.codegraph/`，退出码 0 但不可查询 | 代码图不可用；本轮使用目标仓库直接只读源码 |
| 修改范围 | 仅追加本文件第三轮章节 | 未改 KAG 源码、配置、依赖、测试、README、Git；未删除旧细探 |
| 运行验证 | 未安装依赖、未启动外部服务、未运行测试或端到端链路 | L1-L4 全部未验证/待核，不写成通过 |

本轮第三轮完成定义是：KAG 的图存储/检索、Schema、逻辑形式、规划、检索、推理和工具执行已经明确拆到 L1/L2/L3，数据/模型/缓存/任务资源有 owner，失败/超时/取消/崩溃有矩阵，L0-L4 有验收边界，并明确不复制第二知识链路；这不等同于系统工程平台已经实施或 KAG 外部服务已可运行。

后续只维护本 `ARCHITECTURE.md` 的第三轮映射和证据边界；任何平台实现必须重新读取目标源码、锁定当前版本、登记能力并执行真实 provider/故障/恢复验收。

## 23. 第二轮源码深挖：从组件实现到真实运行语义

本节补充对知识构建、规则/图谱、检索、推理、模型、存储、任务队列、资源释放和验证边界的源码级核对。这里的“通过”只表示源码路径和控制流已经读到；没有启动 OpenSPG、图存储、Reasoner、模型或外部工具服务，因此不把静态可读性写成运行成功。

### 23.1 知识构建不是单线程流水线，而是 DAG + 批内并发 + checkpoint

源码存在两套相近但不完全相同的构建执行形态：

1. `KAGBuilderChain.invoke`（`kag/interface/builder/builder_chain_abc.py:28-98`）先用 `networkx.topological_sort` 遍历组件 DAG；每个节点把所有前驱输出拼成输入，再在节点内部创建 `ThreadPoolExecutor`，对输入逐项调用 `node.invoke`。`max_workers` 参数实际没有传入该内部线程池，当前实现使用 `ThreadPoolExecutor` 默认并发度，故配置名与真实并发上限并不完全一致。
2. `KAGBuilderChain.ainvoke:100-174` 按 `networkx.topological_generations` 逐层运行；同一层节点通过 `asyncio.gather` 并行，每个节点的输入又通过共享 `asyncio.Semaphore(max_concurrency)` 限制。取消或某个 task 抛错时没有统一的子任务终态/补偿协议，`gather` 的异常传播仍由调用方承担。
3. `DefaultUnstructuredBuilderChain.invoke:123-191` 先 Reader、Splitter 串行生成 chunk，再对每个未 checkpoint 的 chunk 执行 Extractor → Vectorizer → PostProcessor → Writer；这一段显式使用 `ThreadPoolExecutor(max_workers=max_workers)`。`processed_chunk_keys` 只跳过已处理 chunk，不能证明远端图写入和 checkpoint 记录是同一事务。
4. `BuilderChainStreamRunner` 还按链路使用线程池、异步 consumer 和 `ProcessPoolExecutor`；收尾处调用 `CheckpointerManager.close()`。因此“builder 返回结果”与“所有线程/进程、checkpoint、远端写入均已一致收口”是两个不同命题。

**构建真实性结论：** checkpoint 提供的是 chunk key 级的重复抑制，不是图写入事务日志；并发完成顺序不等于输入顺序；单 chunk 异常是否影响批次由上层 runner 的 gather/future 收集方式决定，必须在真实故障注入中验证。

### 23.2 抽取、规则与图谱：规则既有 schema 语义，也有 LLM 软规则

- `KnowledgeUnitSchemaFreeExtractor` 先加载 `SchemaClient.load()` 的项目 schema，再进行 NER、知识单元和三元组抽取；可叠加 `ExternalGraphLoaderABC.ner`，并按名称去重、将未知类型归入 `Others`。实体标准化、三元组和知识单元均受 LLM 输出影响，源码没有把抽取结果当作确定性事实。
- `SchemaConstraintExtractor` 走 schema 约束抽取路径，输出 `spo_graph_index` 和 `chunk_index`；MarkLang 中的类型继承、属性/关系约束、枚举/正则/非空/多值以及索引类型，负责约束“允许抽什么”和“如何建索引”，不是运行时自动证明事实正确。
- `KAGPostProcessor` 先过滤无 id/label 节点，把未知 label 归到 `OTHER_TYPE`，再按向量相似度和阈值建立相似边；默认 `similarity_threshold` 是否启用由配置决定。相似边是链接候选，不等同于人工确认的同一实体。
- `SPGAligner` 以 `spg_type_name#name` 聚合并处理属性，`KAGAligner` 以 Node/Edge 相等性去重；`KGWriter.standarlize_graph` 给 label/edge type 加 namespace，并把非字符串属性 JSON 序列化。
- `KGWriter` 最终调用 `GraphClient.write_graph(..., operation=UPSERT|DELETE)`；`lead_to_builder` 可把写图继续交给服务端 builder/推理链，但本仓库没有服务端实现，不能从客户端代码证明规则触发、事务隔离或最终一致性。
- 逻辑形式提示词明确包含 `Deduce(op=rule)`，但执行端仍是 LLM 语义推断路径；它不是 OpenSPG 符号规则引擎的替代品。真正 DSL/规则推理走 `ReasonerClient.syn_execute`，通过 REST 提交 `ReasonTask` 给外部 Java Reasoner。

因此应区分三种“规则”：MarkLang/schema 约束（结构规则）、LF/Deduce 的提示词规则（模型软规则）、Reasoner DSL/服务端规则（外部符号执行）。三者不能用同一“规则命中”字段混淆。

### 23.3 检索实际是可配置 DAG，并带优先级短路和部分失败吞并

`KAGFlow` 解析形如 `kg_cs->kg_fr->rc->kag_merger` 的 flow string 为 `networkx.DiGraph`，显式检查 DAG；节点配置来自 `KAG_CONFIG.all_config`，否则使用内置默认配置。默认组件语义为：

| 阶段 | 源码语义 | 重要边界 |
|---|---|---|
| `kg_cs` | 0.9 entity linking + exact one-hop | 图命中后可 break |
| `kg_fr` | 0.8 entity linking + fuzzy one-hop + PPR 回溯 chunk | 依赖图节点到原文的路径 |
| `rc` | vector chunk retriever，默认 top-k 20 | 向量服务/索引属于外部 provider |
| `kag_merger` | 合并图、chunk 和其他 RetrievedData，可调用 LLM summary | summary 不是检索事实 |

`KAGHybridRetrievalExecutor.do_retrieval:127-242` 再按 retriever 的 `priority` 分组，组内以 `ThreadPoolExecutor(max_workers=len(group))` 并发，按优先级顺序等待并合并；只要 graphs/chunks/docs 有内容就 break。单个 retriever 异常被记录后继续，全部异常时可能得到空 `RetrieverOutput`；外层 `invoke` 会把总异常转成带 `err_msg` 的输出。故当前结果至少要区分：真实空结果、部分 provider 失败、全链路失败、命中后短路。

`KAGFlow.execute` 对每个逻辑节点逐个创建 `ThreadPoolExecutor` 并按拓扑顺序推进；这与 hybrid executor 的优先级并发是两层并发，不能简单相加为一个全局并发预算。`context_select` 会保留 LLM 选择的 chunk，并额外补足最多前 4 个 chunk；选择失败则退回前 10 个，属于显式降级但会改变证据集合。

### 23.4 推理链：Planner 生成任务，Context 维护 alias，Generator/Reporter 负责投影

`KAGStaticPipeline` 的实际控制流是 Planner → `Context.gen_task(group=True)` → 同组 `asyncio.gather` → Executor → Generator；规划和执行路径使用 tenacity 重试，`max_iteration` 可在 unknown 或 finish judge 未完成时重跑。`LogicNode`/`Task` 保存 alias、父任务和中间结果，`variables_graph` 让 Retrieval 输出可以被后续 Math、Deduce、Output 使用。

- Retrieval 将 SPO/chunk/doc 结果写入 `RetrieverOutput` 与 `KgGraph`，并可能写 answered alias。
- Math 从 alias 解析输入，由 LLM 生成 Python，再调用独立 `python` 子进程；stdout 被包装回 alias 结果。
- Deduce 将父任务结果、图或文本上下文交给 LLM，`rule`/`judgement`/`entailment`/`choice` 等是提示词定义的操作语义。
- Generator 汇总任务依赖、检索上下文和历史结果；Reporter 同时承载 trace、引用、图证据和外部 OpenSPG report。

这条链的可审计单位应是 plan、每个 LogicNode/Task、每次 provider attempt、证据引用和最终投影，而不是最终自然语言字符串。当前 `Context`、alias 和 task result 主要在进程内，不能作为重启恢复依据。

### 23.5 模型调用与向量化：已有节流/重试/计量，但没有统一全局预算

`LLMClient` 通过注册表按配置装配，初始化 rate limiter；同步/异步调用和 JSON 解析均有最多 3 次 tenacity 重试。`TokenMeter` 可按 task id 内存计量，关闭内存模式时落到系统临时目录并用 portalocker 加锁；`TokenMeterFactory.remove_meter` 会尝试删除计量文件，但 `clear_all` 不删除文件。计量因此是使用统计/辅助 checkpoint，不是账务真相。

`BatchVectorizer` 会按文本去重成 placeholder，按 batch size 调 dense/sparse vectorizer 并回填属性；异步路径创建多个 `asyncio` task 后 `gather`，但本地源码未见统一的全局模型额度、输出维度校验、取消传播或 provider close。抽取器、检索 merger、summary、planner、Deduce 都可能独立拿到 LLM 实例，故模型重试、限流和缓存的跨组件预算仍需平台级收敛。

### 23.6 存储与外部服务：客户端释放能力存在，但业务对象未统一闭合

- `ApiClient.close()` 可关闭底层 REST 连接池；Graph/Search/Reasoner client 持有各自 `_rest_client`。源码未显示 KAGBuilder/KAGSolver 在所有正常、异常、取消路径统一调用这些 close。
- `ReasonerClient` 初始化即加载/缓存 schema；`reason_cache` 是按 project id 的 TTL cache。`syn_execute` 仅提交 DSL 并返回 `ReasonTaskResponse`，客户端不能证明远端任务已完成、可取消或结果已经持久化。
- `CheckPointer.close()` 具备幂等关闭语义，`CheckpointerManager.close()` 在全局锁内逐个关闭并清空缓存；它能释放 checkpoint provider，但不负责图写入回滚、模型缓存或任务账本。
- `KGWriter` 的异步写入使用 `asyncio.to_thread` 包装 checkpoint 读写；GraphClient 的 HTTP 生命周期仍由对象 owner 管理，不由每次写入显式关闭。
- Reporter 的抽象实现持有单线程 executor，`stop()` 会 shutdown；`SolverMain.qa` 的 finally 调 reporter.stop 是较明确的释放点，但不能推出所有自定义 Reporter 或外部 client 都完成释放。

### 23.7 任务队列与资源释放：HTTP 异步层不是持久任务系统

`AsyncTaskManager`（`kag/solver/server/asyn_task_manager.py`）维护无界 `queue.Queue`、最多 10 个 worker 线程、一个 `ThreadPoolExecutor(max_workers=10)` 和 `TTLCache(maxsize=1000, ttl=3600)`。worker 从队列取任务，再把函数提交给 executor 并同步等待 `future.result()`；这造成两级线程池：队列 worker 被占住，同时 executor worker 执行实际任务。

`submit_task` 只生成 UUID 并入队，未设置队列上限、幂等键、截止时间、取消句柄或持久账本。查询不到任务、任务过期和真实失败都统一返回 `status=failed` 风格的“not found or expired”结果。`shutdown()` 发送哨兵、等待 queue join、再关闭 executor；但没有任务取消、运行中 future 回收或崩溃恢复。模块导入时还创建全局 `asyn_task = AsyncTaskManager()`，即导入即启动 10 个 daemon worker。

HTTP `/process` 的 `submit` 返回 `success=True,status=init` 只代表入队；`query` 读取 TTLCache。没有 cancel 命令，也没有 accepted/running/completed/failed/timeout/cancelled/crashed/expired 的完整状态机。因而 HTTP 200、task id、TTLCache 有值都不能作为业务成功或资源已释放的证据。

### 23.8 资源释放与危险执行面的真假判定

当前源码能直接证明的释放点包括：上下文退出时重置 LLM contextvars；`CheckpointerManager.close()` 关闭缓存对象；Reporter executor shutdown；MCP `AsyncExitStack.aclose()`；数学执行 finally 删除临时 `.py` 文件；Builder runner 收尾关闭 checkpointer。当前源码不能证明的包括：线程池/进程池在任意异常和取消下均关闭、子进程树被杀净、HTTP 连接池与 schema cache 按 run 隔离、远端 Reasoner 任务被取消、MCP 下载脚本经过签名和摘要校验。

特别是 `run_py_code` 使用 `subprocess.run([sys.executable, temp_file_path], timeout=5)`，没有显式新建进程组、资源限制、网络/文件系统隔离或 SIGTERM→SIGKILL 回收；`MCPClient` 依赖外部 `.py`/`.js` 服务和 `AsyncExitStack`，而 `McpExecutor.download_data` 可下载 HTTP(S) 内容到 checkpoint 目录。两者都只能作为受管隔离 provider 候选，不能以“有 timeout/finally”判定安全。

### 23.9 验证真假矩阵（第二轮源码核对）

| 可观察证据 | 能证明 | 不能证明 |
|---|---|---|
| 本地单元测试通过 | 解析、模型/组件假实现、纯内存流程的回归 | OpenSPG、图数据库、Reasoner、真实模型和 MCP 服务可用 |
| Builder 返回 SubGraph/列表 | 当前输入已走过部分组件 | 所有 chunk 已远端 UPSERT、向量一致、checkpoint 与写图原子一致 |
| RetrieverOutput 有 graphs/chunks | 至少一个检索器产生了候选 | 其他 retriever 成功、证据完整、结果未被短路或 summary 改写 |
| ReasonTaskResponse 返回 | HTTP/API 返回了任务对象 | Java Reasoner 已完成、结果可重放、远端任务可取消 |
| HTTP `/process` 返回 task id | 请求已进入内存队列 | 业务成功、任务持久化、断线后可恢复 |
| `future.result()`/`asyncio.gather` 正常返回 | 当前进程收到返回值 | 子进程树、连接、线程、临时文件和远端任务均已释放 |
| pytest/pytest.ini 收集到测试 | 测试收集与选定断言执行 | 零测试、skip、mock provider 被误报为端到端通过 |

第二轮的最小真实验收应至少覆盖：固定 fixture 的构建和图回读；schema 版本冲突；UPSERT 重复提交；图精确/模糊/PPR/向量检索的空、部分失败和短路；Reasoner DSL 成功/超时/取消；LLM 限流、重试和 token 计量；Math/MCP 强杀后零残留；队列满、TTL、重复提交、进程强杀后新进程读回任务状态。当前均未在本地执行，故统一标记为 `UNVERIFIED`，不能用日志、warning、HTTP 200 或“最终答案非空”替代。

### 23.10 第二轮结论

KAG 的真实核心不是单一“知识图谱问答函数”，而是三类并发控制叠加的长链：Builder DAG 的批内并发、Retriever/KAGFlow 的优先级并发、Solver/HTTP 的任务并发；它们各自有局部线程池、缓存和重试，却没有统一的运行账本、全局截止时间和跨 provider 资源预算。知识事实由 schema 约束、LLM 抽取、相似链接、UPSERT 图写入共同形成；规则又分结构约束、模型提示词和外部符号 Reasoner 三种语义。检索结果、推理 alias、模型输出和任务状态必须分开验真。

因此后续平台化时最优先的不是复制 KAG 目录，而是：冻结结果/错误/证据/资源字段；建立唯一任务与租约 owner；把 Graph/Search/Reasoner/Model/MCP/隔离执行统一成可关闭、可取消、可计量的 provider；把“空结果、部分失败、失败、超时、取消、崩溃、过期”从字符串和 TTLCache 中提升为可读回状态；最后用真实外部服务和故障注入证明，而不是用 mock 或返回对象证明。
