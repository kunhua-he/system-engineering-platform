# RAGFlow 架构建档

> 首轮全量架构建档 + 后续通用底座映射，中文说明；源码标识、路径、命令和接口名称保留原文。
>
> 分析日期：2026-08-20
>
> 源码根：`~/Documents/Agent/github 源码参考/15_知识库系统/ragflow`
>
> 本文只描述当前本地工作树事实，并单独标注远程 `origin/main` 快照差异；不把设计文档或远程代码当成本地已实现事实。

## 1. 范围、证据与版本边界

### 1.1 已读取的证据

- 项目说明：`README.md`、`README_zh.md`。
- 协作规则：根 `AGENTS.md`、`CLAUDE.md`、`web/CLAUDE.md`。
- 已有细探：`细探-RAGFlow.md`。该文件是当前核对之前的只读细粒度探索，包含 DeepDOC、分块、混合检索、Agent 画布、提示词和行为边界；当前核对未删除、未改写。
- 依赖与构建：`pyproject.toml`、`uv.lock`、`go.mod`、`go.sum`、`web/package.json`、`web/pnpm-lock.yaml`、`build.sh`、`Dockerfile`、`docker/`、`helm/`。
- 运行入口与配置：`api/ragflow_server.py`、`api/apps/__init__.py`、`cmd/ragflow_server.go`、`cmd/ragflow-cli.go`、`internal/router/router.go`、`internal/server/config.go`、`conf/service_conf.yaml`。
- 数据模型与持久化：`api/db/db_models.py`、`api/db/services/`、`internal/entity/`、`internal/dao/database.go`。
- 核心链路：`deepdoc/parser/`、`rag/flow/`、`rag/nlp/search.py`、`rag/svr/task_executor.py`、`agent/canvas.py`、`agent/component/`、`common/doc_store/doc_store_base.py`、`rag/llm/`、`memory/`、`mcp/server/server.py`。
- API：`api/apps/restful_apis/`、`api/apps/backward_compat.py`、`internal/router/router.go`、`sdk/`。
- 测试：`test/`、`rag/flow/tests/`、`agent/test/`、`internal/**/*_test.go`、`web` 测试脚本与配置；仅静态读取，未执行测试。

### 1.2 本地版本与远程版本

- 本地分支：`main`，HEAD：`f796721ff25f0f86e4499c166f0c49228d5f6ad7`，已与当前 `origin/main` 同步（`git rev-list --left-right --count HEAD...origin/main` 为 `0 0`）。
- 当前 `origin/main` 指向 `f796721ff25f0f86e4499c166f0c49228d5f6ad7`；此前远程定点比较记录的是旧远程指针，不能继续作为当前版本差异。
- 本地工作树初始状态有一个未跟踪文件 `细探-RAGFlow.md`，不是当前核对创建。
- 远程快照通过 `127.0.0.1:4780` 代理以独立内存读取方式分析，未 fetch、未 checkout、未覆盖本地工作树。GitHub API 递归 tree 查询受到代理返回的 `403 rate limit exceeded`，因此远程比较以 `raw.githubusercontent.com` 的定点文件快照为准，不宣称已获得完整远程目录。
- 旧远程定点比较曾记录若干文件差异和 `pyproject.toml` 版本变化；由于当前 `origin/main` 已回到与本地相同的固定提交，这些差异仅保留为历史审计记录，不写成当前源码事实。
- 本轮按用户授权未使用 MCP；RAGFlow 的事实证据来自目标工作树本地文件、Git 元数据、CodeGraph 与既有 `细探-RAGFlow.md`。

## 2. 项目定位与总体形态

RAGFlow 是 Apache-2.0 开源的 RAG 引擎，将深度文档理解、可解释分块、混合检索、Agent 工作流、GraphRAG/RAPTOR、模型接入、记忆和 MCP 能力组合为面向知识库问答与自动化工作流的上下文层。

当前代码不是单一运行时，而是 **Python + Go 双后端、React/TypeScript 前端、C/C++ 原生依赖和多种外部基础设施** 的混合架构：

```text
浏览器 / SDK / MCP 客户端
        │
        ├─ web/ React + TypeScript + Vite
        │       └─ python | hybrid | go proxy scheme
        │
        ├─ Python API：api/ragflow_server.py → Quart app
        │       ├─ api/apps/ 动态注册页面和 REST API
        │       ├─ api/db/ Peewee 模型与服务
        │       ├─ rag/ 摄取、检索、LLM、图谱、任务
        │       ├─ deepdoc/ 解析和 OCR
        │       ├─ agent/ 画布、组件、工具、沙箱
        │       └─ memory/ 对话记忆
        │
        └─ Go API/管理/摄取：cmd/ragflow_server.go → Gin Router
                ├─ internal/handler/ HTTP handler
                ├─ internal/service/ 业务服务
                ├─ internal/dao/ GORM 数据访问
                ├─ internal/entity/ 持久化与 API 实体
                ├─ internal/ingestion/ 管线和组件
                ├─ internal/parser/ 解析与分块
                ├─ internal/engine/ ES/Infinity 等索引后端
                ├─ internal/agent/ Agent runtime
                └─ internal/deepdoc/ 原生文档解析接入
```

根目录规模静态统计（排除 `.git` 与 `node_modules`，用于本地快照定位，不是发布指标）：Python 1,054 个、Go 1,530 个、TypeScript 496 个、TSX 820 个、Markdown 174 个、JSON 165 个、YAML/YML 48 个文件。Go 与 Python 的模型、handler、ingestion 和 parser 具有明显并行/迁移关系；阅读时应以实际代理模式和注册路径为准，不把任一目录名直接等同于唯一生产路径。

## 3. 代码分层与职责边界

### 3.1 `api/`：Python Web 应用层

- `api/ragflow_server.py` 是 Python 服务入口：初始化日志、数据库表和种子数据、运行时配置、插件、进度线程、聊天渠道，然后调用 `app.run()`。
- `api/apps/__init__.py` 创建 `Quart` 应用，接入 CORS、`QuartSchema`、JSON 编码、全局异常处理、session/Redis、内容大小和响应超时配置；通过 `search_pages_path()` + `register_page()` 动态加载 `*_app.py`、`restful_apis/*.py`、SDK 页面并注册 Blueprint。
- 认证支持 JWT、API token、Beta token 和 session fallback；`login_required` 是 Python 路由的主要鉴权边界。
- `api/apps/restful_apis/` 按用户、租户、dataset、document、chunk、chat、agent、file、provider、model、task、memory、MCP、OpenAI 兼容等领域拆分端点。
- `api/apps/backward_compat.py` 注册 `/api/v1` 与 `/v1` 的兼容路由；兼容面是现实边界，不能仅依据根 `AGENTS.md` 的“删除兼容层”倾向推断其已经消失。
- `api/db/services/` 是 Python 业务服务层，通常由 API handler 调用并负责权限、查询、任务、模型配置、文档/知识库/会话等领域操作。

### 3.2 `rag/`：摄取、检索、模型和任务域

- `rag/flow/` 提供解析、分块、tokenizer、extractor、compiler 和 `Pipeline` 组合；`rag/flow/pipeline.py` 继承 `agent.canvas.Graph`，以 DSL 的组件 path 执行并将进度写入 Redis/TaskService。
- `rag/svr/task_executor.py` 是长任务调度中心之一，覆盖 `parse`、`dataflow`、`raptor`、`graphrag`、`memory` 等任务，负责优先级队列、进度、取消检查、嵌入批处理和任务收尾。
- `rag/nlp/` 负责 tokenizer、查询构造、全文/稠密检索、重排和引用；`rag/nlp/search.py` 的 `Dealer` 通过 `DocStoreConnection` 抽象访问 ES、Infinity、OpenSearch、OceanBase 等文档索引后端。
- `rag/llm/` 与 `api/db/services/llm_service.py` 形成模型抽象、供应商配置、chat/embedding/rerank/ASR/vision/TTS/OCR 路由和错误重试边界。
- `rag/graphrag/`、`rag/advanced_rag/` 和 `rag/utils/raptor_utils.py` 提供 GraphRAG、Agentic RAG 和 RAPTOR 旁路能力。
- `rag/prompts/` 以 Markdown/Jinja 模板保存提示词；运行时还存在 DB `prompt_config`、DSL 样例和组件内默认值，后续修改必须先确认实际事实源。

### 3.3 `deepdoc/`：文档解析和 OCR

`deepdoc/parser/` 覆盖 PDF、DOCX、PPT、Excel、Markdown、HTML、TXT、JSON、EPUB、MinerU、Docling、OCR 等 parser；`deepdoc/parser/pdf_parser.py` 是当前 Python DeepDOC 复杂度最高的文件之一（本地 2,145 行）。典型 PDF 路径是：字符层抽取与去重 → 图片/OCR → 版面识别 → 表格结构识别 → 文本合并和阅读顺序 → 表格/图片/caption 归并 → bbox 结果。

`deepdoc/server/` 是可独立运行的 LitServe 方向，承载 OCR/TSR/DLA 等解析或视觉推理服务；主服务可通过配置把部分推理转为远程调用。模型资源在 `rag/res/deepdoc`，缺失时部分路径会触发 HuggingFace 资源获取，部署时需明确网络和缓存策略。

### 3.4 `agent/`：画布、组件、工具和沙箱

- `agent/canvas.py` 的 `Graph` 把 JSON DSL 载入组件对象，校验参数，维护 `components`、`path`、`globals`、`history` 和 task context；运行时支持下游扩展、分支、循环、挂起恢复和组件级错误。
- `agent/component/` 是组件实现和参数契约层；LLM、Retrieval、Message、代码执行、MCP 工具等组件均从此组合。
- `agent/tools/` 提供检索、Web/SQL/文件等工具，MCP 通过 `MCPToolCallSession` 接入，子 Agent 也以工具形态参与工具循环。
- `agent/sandbox/` 通过 `SandboxProvider`/manager 管理 Python/Node 执行环境、资源限制、seccomp、超时、stdout/stderr 和 artifacts 契约。`agent/sandbox/executor_manager/models/schemas.py` 固定了 `CodeExecutionRequest`、`CodeExecutionResult`、`ArtifactItem` 等边界模型。

### 3.5 `internal/`：Go 后端主路径

- `cmd/ragflow_server.go` 通过 `--admin`、`--api`、`--ingestor`、`--syncer` 选择进程角色；初始化配置、数据库、模型 provider、服务依赖和 Gin 路由。
- `internal/router/router.go` 维护 handler 依赖注入和路由分组，已覆盖系统、认证、用户/租户、documents、datasets、chunks、chats、searches、files、agents、providers、memory、MCP、pipeline 等领域。
- `internal/handler/` 负责 HTTP 请求边界和流式响应；`internal/service/` 负责编排业务；`internal/dao/` 负责 GORM 查询和持久化；`internal/entity/` 保持实体、枚举、JSON 映射和 API 输出模型。
- `internal/ingestion/` 细分 `component/`、`pipeline/`、`registry/`、`service/`、`task/` 和 wire 装配，是 Go 摄取新路径的核心；`internal/parser/parser/` 和 `internal/parser/chunk/` 提供类型化解析和 chunk operator。
- `internal/engine/` 对接 Elasticsearch、Infinity、Redis 等；`internal/deepdoc/` 与 `internal/binding/cpp/` 对接 `office_oxide`、`pdfium-static`、`pdf_oxide` 等原生库。
- 根 `AGENTS.md` 将 `internal/ingestion`、`internal/parser`、`internal/deepdoc` 定义为主动重构区，倾向收敛重复实现，而不是继续增加 wrapper/legacy API。

## 4. 关键业务数据与持久化

### 4.1 Python Peewee 模型

`api/db/db_models.py` 定义 `BaseModel`、`DataBaseModel` 和大量业务模型。共同特征包括 `create_time/create_date/update_time/update_date`，统一 `to_dict()`/`to_human_model_dict()`，查询辅助、索引元数据和数据库连接重试。

重要表/模型：

- 身份与租户：`User`、`Tenant`、`UserTenant`、`InvitationCode`、`APIToken`。
- 模型配置：`LLMFactories`、`LLM`、`TenantLLM`、`TenantModelProvider`、`TenantModelInstance`、`TenantModel`、`TenantModelGroup`、`TenantModelGroupMapping`。
- 知识库主数据：`Knowledgebase`。保存租户、embedding、parser/pipeline、权限、统计计数、相似度/向量权重、GraphRAG/RAPTOR/mindmap/artifact/skill 等 task id 和完成时间。
- 文档与内容：`Document` 以及文档元数据、文件、chunk 相关表；文档状态、parser config、来源、大小、进度、token/chunk 计数和 content hash 是摄取状态的主要字段。
- 会话和 Agent：`Dialog`、`Conversation`、`UserCanvas`、`UserCanvasVersion`、`Task`、`PipelineOperationLog`、`Memory`。
- 外部连接与扩展：connector、MCP server、system settings、evaluation、skill/search 等模型。

`init_database_tables()` 会按反射收集 `DataBaseModel` 子类并创建缺失表，之后执行 Peewee migration/索引补齐；这意味着模型声明、初始化顺序和迁移函数共同构成 schema 契约，不应只看字段定义。

### 4.2 Go GORM 模型

`internal/entity/` 为 Go 侧实体；`internal/dao/database.go` 使用 MySQL DSN、GORM 连接池，并在 `migrateDB` 模式下对一批实体执行 `autoMigrateSafely`，随后运行手工 migration。注册的实体包括 `User`、`Tenant`、`UserTenant`、`File`、`Document`、`Knowledgebase`、`Chat`、`ChatSession`、`Task`、`APIToken`、`LLM`、`TenantModel*`、`IngestionTask`、`FileCommit*` 等。

Go 的 `internal/entity/dataset.go` 与 `document.go` 体现了和 Python 表结构相同的核心字段契约：`Knowledgebase`/`Document`、parser/pipeline、统计计数、状态、时间字段和 JSON 配置。Go 侧还保留 `ToMap()` 等 API 输出映射，避免 GORM 实体直接等于公开响应。

### 4.3 数据边界与风险

两套后端都以 MySQL 业务数据和独立文档索引/对象存储为核心，且存在共用表/兼容 API 的事实；不能在不确认 `API_PROXY_SCHEME`、部署模式和 migration 状态的情况下同时运行两套写路径。Go 的 GORM `AutoMigrate`、Python 的 Peewee 建表/迁移与手工 migration 需要按部署版本协调，尤其关注字段、索引、默认值和删除/状态语义漂移。

文档正文和 chunk 不是全部放在关系库：文档文件/图片走 MinIO/S3/Azure/GCS/OSS/OpenDAL 等 storage provider；chunk、向量、全文字段和图谱字段走配置的 document engine；Redis 保存队列、进度、session/secret、trace/cache 等运行态数据。

## 5. 文档摄取、检索与问答主链路

```text
上传/同步文件
  → Document / Knowledgebase / Task 关系库状态
  → parser（deepdoc 或 Go parser）
  → bbox / parser result
  → chunker / title chunker / pipeline DSL
  → tokenizer + embedding
  → DocStoreConnection：全文字段、dense/sparse vector、metadata、graph fields
  → Dealer.search：MatchText + MatchDense + FusionExpr
  → term/vector/rank feature 重排
  → Dialog/LLMBundle 组织上下文
  → citation 标注、SSE/JSON 响应、usage/trace
```

### 5.1 解析与分块

`RAGFlowPdfParser.__call__` 典型顺序是 outline、images、layout、table transform、text merge、vertical concat、page filter、table/figure extraction；`parse_into_bboxes` 按页批处理以限制峰值内存。乱码检测、OCR 回退、版面垃圾过滤、跨页表格合并和图片上下文是 DeepDOC 的关键质量门。

`rag/flow`/`rag/nlp` 的 chunk 路径支持 `token_size`、`delimiter`、`one` 等模式，支持 `children_delimiters` 父子块、`mom_id`、table/image context，以及 `content_with_weight`、`content_ltks`、`content_sm_ltks` 等检索/嵌入字段。

### 5.2 混合检索和重排

`rag/nlp/search.py::Dealer.search` 先构造全文查询和可选 embedding 查询，按 document engine 组合 `MatchText`、`MatchDense`、`FusionExpr`；空结果时按过滤条件和较低 `min_match`/similarity 降级重试。`retrieval()` 再选择外部 rerank、KNN/term 混合或本地向量重排，并对外部 logits 做归一化。候选窗口必须和 page size 对齐，否则深分页的 offset/window 关系会破坏结果稳定性。

删除安全网 `_prune_deleted_chunks` 会回查关系库 document id，过滤文档已删除但索引残留的 chunk；它是补偿机制，不应替代主删除路径。

### 5.3 Agent 与 LLM

`Graph` 解析 DSL 后构造组件对象并执行 path；`Pipeline` 把该机制用于文档处理。组件执行支持并发、分支、循环、异常 `goto/default_value/终止`、用户输入挂起恢复、MCP 工具和多轮 tool call。LLM 访问由 provider/model 配置解析，统一处理超时、重试、错误分类、thinking/streaming、usage 和上下文隔离。

OpenAI 兼容 API 在 `api/apps/restful_apis/openai_api.py`，通过 SSE 转换内部 answer event，增量输出 `delta.content`，尾事件承载 `final_content/reference`，避免把完整答案重复输出；Go 侧在 `internal/router/router.go` 注册 `/api/v1/openai/:chat_id/chat/completions`。

## 6. API 与外部能力面

### 6.1 Python API

- 动态 Blueprint 默认将 `restful_apis/*.py` 挂到 `/api/v1`，普通 `*_app.py` 按页面名形成版本前缀。
- 代表性领域：`/datasets`、`/documents`、`/chunks`、`/chats`、`/chat/completions`、`/agents`、`/files`、`/tasks`、`/models`、`/providers`、`/memory`、`/mcp`、`/openai/.../chat/completions`。
- `api/apps/backward_compat.py` 提供旧 `/v1` 和旧 `/api/v1` 绑定；实际 route 细节以各 API 文件的 decorator 和注册过程为准。
- 统一返回多使用 `get_json_result`/`get_error_data_result`；错误和鉴权由 Quart handler、`login_required` 和 `RetCode` 处理。

### 6.2 Go API

`internal/router/router.go::Router.Setup` 使用 Gin 分组和 middleware：

- 公共健康/系统：`/health`、`/api/v1/system/ping`、`/system/config`、`/system/version`、`/system/healthz`、`/language`、pipeline catalog、login/OAuth callback。
- Beta token：searchbots、chatbots、agentbots、document preview/image/thumbnail、`POST /api/v1/mcp`。
- 授权后：users/tenants、documents、chats/sessions、OpenAI compatible chat、datasets/documents/chunks/index/ingestion、searches、files、agents、providers、memory、skills、plugins、tasks 等。
- 全部 Go 响应增加 `X-API-Source: go`，可用于 hybrid 路由排查。

### 6.3 MCP 与 SDK

`mcp/server/server.py` 是独立 Starlette/MCP server 方向，支持 SSE 与 `streamable-http` transport，通过 `RAGFlowConnector` 以 API key 调用 dataset/chat/document 等 REST API，并带有有界分页和 metadata cache。Go router 也暴露 `/api/v1/mcp`，Agent 组件还可作为 MCP client 调工具。`sdk/` 和 `api/apps/restful_apis/openai_api.py` 共同形成外部集成面。

## 7. 前端、配置和部署

### 7.1 前端

`web/` 是 React + TypeScript + Vite 应用；状态主要是 Zustand，数据请求使用 TanStack Query，网络层按 `web/CLAUDE.md` 分为 `hooks → services → utils/next-request`，接口类型分置 `interfaces/database` 与 `interfaces/request`。`web/package.json` 的脚本包含 `dev`、`build`、`lint`、`test`、`type-check`，前端代理支持 `python`、`hybrid`、`go` 语义（Go 开发指南和 `web/vite.config.ts` 是共同证据）。

### 7.2 配置

- Python：`common/settings.py` 集中初始化 DB、DOC_ENGINE、Redis、storage、LLM、parser、并发和资源限制；重要环境变量包括 `DB_TYPE`、`DOC_ENGINE`、`RAGFLOW_SECRET_KEY`、`MAX_CONTENT_LENGTH`、`EMBEDDING_BATCH_SIZE`、`PARALLEL_DEVICES`、`LLM_*`、`COMPONENT_EXEC_TIMEOUT` 等。
- Go：`conf/service_conf.yaml`/`internal/server/config.go` 定义 server/admin、MySQL、Redis、NATS、ES/OpenSearch/Infinity/OceanBase、MinIO、OTel、模型、同步器等配置；Go 默认 API/admin 端口在开发文档中为 9384/9383，配置模板中的旧/独立端口值需按运行模式核对。
- 模型：`conf/llm_factories.json`、`conf/models/*.json`、租户模型 provider/instance/group 表和 `models.ProviderManager` 共同决定模型路由。

### 7.3 基础设施与部署

`docker/docker-compose-base.yml` 编排 MySQL、MinIO、Valkey/Redis，并通过 profile 选择 Elasticsearch、OpenSearch、Infinity、OceanBase、SeekDB、sandbox 等；`Dockerfile` 使用 Ubuntu 24.04、多阶段构建、Python 3.13/uv、Node 20、模型资源、Tika、Chrome、ODBC 和 Go/native 运行依赖。`helm/` 提供 Kubernetes chart。

运行时外部依赖主要是：MySQL、Redis/Valkey、MinIO/S3 兼容对象存储、Elasticsearch/OpenSearch/Infinity/OceanBase、NATS（Go ingestor）、LLM/embedding/rerank/vision API、可选 gVisor/沙箱和原生 C/C++ 文档库。

## 8. 测试与验证地图

- Python 单元入口：`run_tests.py` 默认执行 `test/unit_test`，支持 pytest、marker、coverage、parallel；根 `AGENTS.md` 还规定了 `uv run pytest` 与 ruff 工作流。
- Python 集成/HTTP/SDK：`test/testcases/`，`test/README.md` 要求先用 `uv sync --python 3.13 --only-group test --no-default-groups --frozen`、安装 SDK、准备 Docker 服务，再按 `HTTP_API_TEST_LEVEL` 和 `HOST_ADDRESS` 执行。
- Go：`internal/**/*_test.go`、handler/dao/service/parser/ingestion 测试；必须优先使用 `build.sh --test`，因为 CGO 静态库和 native flags 不能由裸 `go test` 可靠替代。远程 `AGENTS.md` 新增了 unit/integration/e2e/manual build-tag 分层，但该规则不属于本地版本事实。
- Frontend：`npm run test` 使用 Jest，另有 `lint`、`type-check`、`build`；前端规则要求查询 key factory、service 分层和 UI 共享组件边界。
- 当前核对没有运行 pytest、Go test、npm、lint、build、Docker、Helm 或服务启动；原因是任务明确禁止安装、启动、构建，且当前核对仅要求架构建档。

## 9. 可复用架构模式

1. **阶段化摄取管线**：parser → chunker → tokenizer → extractor → embedding/index，每阶段有参数、进度、取消和任务状态边界。
2. **文档质量门**：字符层乱码检测 + OCR 回退 + layout/TSR + 表格/图片结构化，避免盲目全量 OCR。
3. **统一文档存储接口**：`DocStoreConnection` 将查询表达式、过滤、排序、索引和 CRUD 与 ES/Infinity/OpenSearch/OceanBase 实现解耦。
4. **混合检索数学约束**：全文与 dense 融合、rerank 归一化、rank feature、候选窗口和分页对齐可作为检索契约。
5. **Agent DSL + 事件流**：Graph/Canvas 的 path、组件 output、分支/循环/异常和流式事件适合抽取为工作流执行协议。
6. **LLM 错误分类矩阵**：只对限流/服务端等可恢复错误重试，限制轮次、退避和 token 使用，避免无边界重试。
7. **沙箱提供者接口**：执行、资源限制、超时、错误分类、结构化结果和 artifacts 统一成可替换 provider contract。
8. **MCP 适配层**：把外部 MCP 工具映射到受鉴权 REST 能力面，并在分页、缓存、错误文本和 transport 层保持边界。
9. **双后端迁移可观测性**：Go 响应的 `X-API-Source`、前端 proxy scheme、共享业务实体和 Python 兼容路由共同构成迁移期间的定位手段。

## 10. 风险、注意事项与结论

### 10.1 风险

- **版本漂移**：当前本地已同步 `origin/main`；后续远程指针变化仍需隔离快照逐文件复核，版本对齐不等于运行通过。
- **双后端事实源**：Python Peewee 与 Go GORM/AutoMigrate 共同触及关系模型，Python/Go 路由又存在 hybrid/兼容面；变更 schema、删除语义或 API 时必须双向核对。
- **文档与索引双存储一致性**：MySQL 状态、对象存储文件、document engine chunk/vector、Redis task progress 之间不是单事务；删除残留和任务重试需要重点验证。
- **native/第三方负担**：DeepDOC、OCR、Tika、模型资源、C/C++ 静态库、Chrome、ODBC 和沙箱造成构建/运行环境高度敏感；不能将 Python import 通过等同于可部署。
- **安全边界**：API token/JWT/session、MCP API key、LLM keys、对象存储凭证、代码沙箱、SSRF/外部 URL 和日志脱敏必须沿实际路由和 provider 路径审查。
- **细探时效性**：`细探-RAGFlow.md` 明确是某个本地快照的只读分析；它适合作为导航，不应覆盖当前源代码或远程新版本。

### 10.2 阅读/修改建议

1. 修改 API 前先确定当前 proxy scheme（`python`/`hybrid`/`go`），再同时看 Python decorator、Go Gin route、frontend service/hook 和 SDK。
2. 修改 dataset/document/chunk/task/model schema 前，至少同步核对 `api/db/db_models.py`、`internal/entity/`、`api/db/services/`、`internal/dao/`、migration 和相应测试。
3. 修改摄取或检索时按 `deepdoc → rag/flow → task_executor → DocStoreConnection → Dealer → chat/API` 追链，保留取消、进度、分页、索引残留安全网和引用契约。
4. 修改 Agent 组件、MCP 或沙箱时先看 DSL schema、组件参数校验、事件/streaming、资源上限、子进程生命周期和错误返回形状。
5. 远程版本合并后需重新生成代码地图、重新读 `AGENTS.md`/依赖/入口，并重新核对本文件列出的路径和行数；本地不可直接把远程新增能力当作已存在。

### 10.3 结论

RAGFlow 当前是一个正在从 Python 主路径向 Go ingestion/parser/agent/server 路径扩展并逐步切换的混合 RAG 平台。最稳定的领域边界是：`deepdoc`/`rag` 负责内容理解与检索，`agent` 负责 DSL 工作流和工具执行，`api`/`internal` 分别承载 Python/Go Web 与业务实现，`web` 负责统一 UI，`api/db` 与 `internal/dao/entity` 共同维护关系模型，document engine/object storage/Redis 承载检索、文件和运行态。后续架构演进的主要问题不是再增加平行层，而是明确每个领域在 `python`、`hybrid`、`go` 三种代理模式下的唯一权威路径，收敛 schema/API/任务语义，并用分层测试和可观测标识证明迁移完成。

## 11. 旧细探吸收与裁决

> `细探-RAGFlow.md` 已完整读取并与当前本地源码、`AGENTS.md`、现有本档案逐项对照。本次只把有当前源码路径支撑的架构事实收口到本文件；旧细探保留为历史探索证据，后续只维护本文件，不再在两个文档之间平行更新。

### 11.1 已吸收的细粒度事实

1. **DeepDOC 的质量门和分页策略**：`RAGFlowPdfParser.__call__` 的实际顺序是 outline → images/OCR → layout → table transform（`TABLE_AUTO_ROTATE` 默认开启）→ text merge → downward concat → page filter → table/figure extraction。`parse_into_bboxes` 默认按 `PDF_PARSER_PAGE_BATCH_SIZE=50` 页分窗；空结果时 `zoomin=3` 递归放大到 `<9` 的下一档。字符层来自 `pdfplumber.dedupe_chars()`，页面图像分辨率为 `72*zoomin`；页面级 PUA/CID 乱码门限为 `0.3`，框级乱码比例达到 `0.5` 会清层重 OCR，字体子集把 CJK 映射成 ASCII 时走 `_is_garbled_by_font_encoding`，但 OCR 字符集覆盖不足的干净文本会保留原字符层。证据：`deepdoc/parser/pdf_parser.py::RAGFlowPdfParser.__images__`、`::__ocr`、`::parse_into_bboxes`、`deepdoc/vision/layout_recognizer.py::LayoutRecognizer`。
2. **版面和表格不是黑盒 OCR**：版面标签包含 `Text`、`Title`、`Figure`、`Figure caption`、`Table`、`Table caption`、`Header`、`Footer`、`Reference`、`Equation`；`footer/header/reference` 是垃圾布局候选，布局重叠阈值为 `0.4`，页脚/页眉还按页面上下 `90%/10%` 位置保留或丢弃，`equation` 对外归为 `figure`。TSR 将行列网格构造成 HTML/描述文本，并支持跨页表格、caption、旋转表格坐标还原。证据：`deepdoc/vision/layout_recognizer.py`、`deepdoc/parser/pdf_parser.py` 的 `_table_transformer_job`、`_extract_table_figure`。
3. **分块参数是可校验契约**：`TokenChunkerParam` 的默认 `delimiter_mode=token_size`、`chunk_token_size=512`、`overlapped_percent=0`，模式仅允许 `token_size`/`delimiter`/`one`；`children_delimiters` 形成父子块关联，`table_context_size`/`image_context_size` 为媒体块拼接相邻文本上下文。摄取旧路径还记录 `chunk_token_num` 默认 `128`、默认 delimiter `\n!?。；！？`，因此不能把两套默认值混写成一个事实。证据：`rag/flow/chunker/token_chunker.py::TokenChunkerParam`、`rag/svr/task_executor.py` 的 `chunk_config`。
4. **混合检索的硬不变量**：`FulltextQueryer` 对 `title_tks^10`、`important_kwd^30`、`question_tks^20`、`content_ltks^2` 等字段加权；`Dealer.search` 组合 `MatchText`、`MatchDense` 与 `FusionExpr("weighted_sum", ..., {"weights": "0.001,1"})`，空结果时无文档过滤则把 `min_match` 降至 `0.1` 并将 dense similarity 设为 `0.17` 重试。`Dealer._rerank_window` 以约 `64` 个候选为目标并向上取整到 `page_size` 的整数倍，外部 reranker 开启时再受 `top` 约束；否则块分页和页内切片会漂移。重排 token 特征为 `content + title*2 + important*5 + question*6`，再叠加 `rank_feature`。证据：`rag/nlp/query.py::FulltextQueryer`、`rag/nlp/search.py::Dealer.search`、`::_rerank_window`、`::rerank_with_knn`、`::rerank_by_model`。
5. **嵌入、RAPTOR 和长任务治理**：嵌入批次受 `settings.EMBEDDING_BATCH_SIZE`（当前默认配置为 `16`）和 `embed_limiter` 控制，文本先截断到 `embedding_model.max_length-10`，标题与正文按 `filename_embd_weight`（默认 `0.1`）线性融合。任务执行器覆盖 `parse`、`dataflow`、`raptor`、`graphrag`、`memory`，通过 Redis 优先级队列、进度回调和取消检查推进；RAPTOR 配置默认 `max_token=256`、`threshold=0.1`、`max_cluster=64`，并按 `should_skip_raptor` 跳过不适用文件。证据：`rag/flow/tokenizer/tokenizer.py`、`rag/svr/task_executor.py`、`rag/flow/compiler/compiler.py`、`rag/utils/raptor_utils.py`。
6. **Canvas 的执行协议**：DSL 的 `path` 是运行计划，`Graph` 批执行节点，节点任务可经 `asyncio.gather` 并行；变量引用正则覆盖 `{cpn_id@var}`、`{sys.*}`、`{env.*}`；工具调用多轮默认 `max_rounds=5`，所有 tool calls 可并行执行后按 OpenAI assistant/tool 消息形状追加 history；组件错误支持 `goto`、`default_value` 或终止三态，引用场景再走 `citation_plus` 二次生成。证据：`agent/canvas.py`、`agent/component/base.py`、`agent/component/agent_with_tools.py`、`rag/prompts/generator.py`。
7. **LLM、提示词与上下文预算**：LLM 访问统一经过 `rag/llm/` 和模型 provider 配置，重试必须按错误类型分类而非全量重试；`RerankModel.Base.similarity` 负责把 provider 分数归一到 `[0,1]`。提示词以 `rag/prompts/*.md`、Jinja2 sandbox、DB `prompt_config`、DSL/测试样例共同组成事实源，旧细探中列出的 citation/keyword/question/full-question/RAPTOR/vision/任务分析提示词族均属于这一模板边界，不能把单个默认 prompt 误写成所有租户的运行时配置。`message_fit_in` 负责按上下文预算裁剪历史。证据：`rag/llm/chat_model.py`、`rag/llm/rerank_model.py`、`rag/prompts/`、`rag/prompts/generator.py`、`agent/component/agent_with_tools.py`。
8. **沙箱和行为边界**：`SandboxProvider` 是可替换执行边界，`CodeExecutionRequest`/`CodeExecutionResult`/`ArtifactItem` 明确编码、语言、stdout/stderr、exit code、资源用量、错误类型、结构化结果和 artifacts 契约；执行服务在 finally 阶段清理 workspace/container 并释放容器。资源上限、超时、ContextVar 隔离、密钥/日志脱敏、Jinja2 sandbox 和 provider URL 主机校验属于实现安全边界，不能只依据 API 文档推断。证据：`agent/sandbox/providers/base.py`、`agent/sandbox/executor_manager/models/schemas.py`、`agent/sandbox/executor_manager/services/execution.py`、`common/settings.py`、`common/connection_utils.py`。

### 11.2 未吸收为当前确定事实的内容

- 旧细探中的整段英文 prompt 原文、示例数量和“测试/DSL 样例是事实标准”等表述没有作为固定运行时值复制；当前文档只保留模板路径、渲染边界和 `prompt_config` 的事实源裁决，因为租户配置和代码会变化。
- 旧细探把某些经验阈值、默认值和“当前路径”写成跨后端普遍规则的部分（例如 `rag/nlp/__init__.py::naive_merge` 与 `rag/flow/chunker` 的默认 token 数、不同 document engine 是否返回向量）不合并为单一默认；已按实际调用路径拆开，并以当前源码为准。
- 旧细探的“架构演进方向”“可借鉴点”“旁路线索”不是当前运行事实；它们只在第 9 节以可复用模式、风险或后续复核点保存，不作为已经完成的迁移结论。远程 `origin/main` 的新增内容同样不覆盖本地事实。
- 旧细探未提供可替代静态证据的运行结果；当前核对没有把 OCR、检索、Agent、沙箱或服务启动成功写成已验证事实。

### 11.3 收口结论

- **吸收**：能由当前源码路径和现有架构证据共同支撑的解析、分块、检索、任务、Agent、LLM、提示词边界和沙箱契约，已并入第 2—10 节及本节。
- **待核**：不同部署模式下 Python/Go 唯一路由、租户 `prompt_config` 的最终覆盖顺序、各 document engine 的向量返回语义、远程 DLA/LitServe 的生产部署方式，需运行配置或集成测试才能裁决。
- **不吸收**：仅来自旧快照、宣传/推断、未在当前源码定位到调用关系，或把可配置值绝对化的表述。
- 旧文件 `细探-RAGFlow.md` **不删除、不改写**；其角色固定为历史细探证据，后续架构维护入口只有根目录 `ARCHITECTURE.md`。

## 12. 首轮变更与验证记录

- 唯一写入：根目录 `ARCHITECTURE.md`（本文件）。
- 未修改源码、依赖、测试、配置、README、`AGENTS.md`、`CLAUDE.md` 或既有细探文件。
- 未删除任何文件，未安装依赖，未启动服务，未构建镜像/二进制，未提交 Git。
- 静态核对使用 Git 状态/版本、文件读取、路径/规模统计、远程代理定点快照比较，并补读 `deepdoc/parser/pdf_parser.py`、`deepdoc/vision/layout_recognizer.py`、`rag/flow/chunker/token_chunker.py`、`rag/nlp/query.py`、`rag/nlp/search.py`、`rag/svr/task_executor.py`、`agent/canvas.py`、`agent/component/agent_with_tools.py`、`agent/sandbox/executor_manager/models/schemas.py` 等当前源码；未执行运行时验证。

## 13. 后续：通用底座映射范围与裁决

当前核对不把 RAGFlow 的目录直接复制为平台目录，而是把每个能力按“原子能力、领域编排、运行治理、外部协议”四个问题重新归位。结论只针对本地工作树 `f796721f`；Go 摄取/解析路径属于正在收敛的新路径，Python 路径仍是可见实现，不能把两条实现写成两个稳定公共契约。

### 13.1 唯一逻辑链路

```text
L4 网关/前端/SDK/MCP/OpenAI 兼容入口
  → L2 知识模块：文档摄取、检索、问答、RAPTOR/GraphRAG、工作流
  → L3 运行核心：命令信封、任务状态、租约/心跳、预算、取消、检查点、幂等、证据
  → L1 支持库公开能力：解析、切分、tokenize、Embedding、rerank、索引、对象存储、模型客户端、沙箱
  → L0 受管提供者/宿主：DeepDOC/OCR/原生 C/C++、LLM/Embedding API、MySQL、Redis/NATS、对象存储、ES/Infinity/OpenSearch
  → 统一结果/事件/状态投影/资源释放
```

文档摄取的规范链应是：`上传/同步 → 文档事实与内容寻址 → 解析结构 → 切分结构 → tokenize/Embedding → 索引写入 → 文档与任务状态完成`。查询的规范链应是：`查询入口 → 查询规范化/权限 → 全文+dense 召回 → 融合/重排 → 删除残留过滤 → 上下文预算裁剪 → LLM/引用 → 事件流或 JSON`。工作流只在 L2 组合这两条链，不能把 `agent/canvas.py` 或 Go `internal/agent` 直接当作网关，也不能让组件绕过 L1 直接访问第三方。

当前 Python `rag/svr/task_executor.py` 与 Go `internal/ingestion/service/ingestion_service.go` 是两套实现路径；它们可以作为迁移期适配器，但对平台只能暴露一个 `文档摄取.执行` 契约、一个 `任务.提交/查询/取消` 契约和一个 `检索.查询` 契约。Python/Go 的路由选择由网关或项目适配层决定，不能由每个消费者各自选择并翻译错误。

### 13.2 领域映射表

| RAGFlow 能力 | 当前源码事实 | 支持库（L1） | 知识模块（L2） | 运行核心（L3） | 网关（L4） | 后续裁决 |
|---|---|---|---|---|---|---|
| 文档摄取/解析 | `deepdoc/parser/`、`rag/app/`；Go `internal/parser/parser/` + `internal/ingestion/component/parser_dispatch.go`，按 file type/`parse_method`/`output_format` 选择 parser | `文档解析`、`OCR/版面/表格识别`、`ParseResult`/通用文档结构、文件读取 | `文档摄取`：文件类型策略、parser config、解析结果到 chunk 输入的编排 | 任务上下文、超时/取消、解析阶段进度、checkpoint、失败证据 | 上传、文件同步、文档预览、解析任务 API | 吸收解析结果和 dispatch；升级为单一结构化输出，provider 差异不得穿透模块 |
| 切分/tokenize | Python `TokenChunkerParam`/`naive_merge`；Go `internal/ingestion/component/chunker/`（token/delimiter/one、父子块、媒体上下文） | `tokenize`、`TokenChunker`、父子块/位置/媒体上下文原子能力 | `文档摄取`选择 chunk 模式、模板、字段映射和质量规则 | chunk 阶段预算、并发、取消、批次重试和中间结果生命周期 | chunk 配置/预览/人工调整 API | 吸收参数校验和父子关联；统一 `Chunk` 结构，禁止 Python/Go 各自定义对外字段 |
| Embedding | Python `rag/llm/embedding_model.py` 多 provider；`task_executor.embedding` 批量、标题权重、截断；Go `task/embedder.go` 从 KB `embd_id` 解析 `ModelDriver.Embed` | `Embedding`、维度/模型元数据、批处理、token usage、重试分类 | `文档摄取`生成向量，`检索`生成 query vector，模型选择由知识库/租户策略决定 | 并发闸、60s 批次超时、预算、取消、provider 熔断/租约 | 模型配置、provider 管理、query/chat API | 吸收 provider 适配；升级模型/维度/版本绑定与索引 schema 的一致性检查 |
| 检索/重排/索引 | `Dealer.search/retrieval` 组合 `MatchText`/`MatchDense`/`FusionExpr`；`DocStoreConnection` 抽象 ES/Infinity/OpenSearch/OceanBase；Go `internal/engine/` | `全文查询`、`dense query`、`融合`、`rerank`、`索引 bulk`、分页窗口 | `检索`、TOC/children/GraphRAG/RAPTOR 召回与上下文整理 | 候选窗口、分页一致性、超时、删除残留过滤、索引写入幂等/补偿 | `/search`、chat/OpenAI compatible、MCP/SDK | 吸收 `Dealer` 数学约束和 store 接口；升级索引写入为可对账制品，不能把 `_prune_deleted_chunks` 当主一致性方案 |
| 工作流/Agent | Python `agent/canvas.py` Graph/Canvas；Go `internal/agent` + ingestion `pipeline.Pipeline`，DSL、path、分支、循环、工具调用、事件 | `DSL 编译`、组件注册、变量解析、工具调用、事件编码、沙箱 client | `工作流`、数据流摄取、Agentic RAG、工具/MCP 编排 | run id、状态、检查点、恢复、取消、最大轮次/并发、artifact 清理 | canvas/agent/pipeline API、SSE、MCP | 吸收 DSL/事件协议；工作流不得持有 DB/消息租约，不得让组件自行实现第二任务系统 |
| 任务队列/执行 | Python Redis Stream consumer group、unacked iterator、`te.{0,1}.common`；Go `tasks.RAGFLOW` MQ、`GetMessages(4)`、bounded `taskChan`、worker pool | Redis/NATS/MQ client、Ack/Nack、消息编解码 | `任务`提交具体领域命令并解释业务结果 | claim、状态 CAS、lease heartbeat、重投、panic recovery、停止排空 | 任务提交/查询/取消/重试/进度 API | 升级为 L3 唯一任务运行核心；Python/Go 队列只作 provider，禁止双写状态 |
| 存储 | Go `internal/storage.Storage` 统一 `Put/Get/Remove/List/PresignedURL/Copy/Move`，factory 支持 MinIO/S3/OSS/GCS；关系库由 Peewee/GORM；索引另存 | 对象存储、关系库、文档索引、Redis checkpoint/cache、连接池 | 文档/数据集/会话/记忆/索引事实编排 | 事务边界、幂等键、原子状态投影、恢复/对账、残留清理 | 文件上传下载、预览、artifact、dataset/document API | 吸收 `Storage` 接口；升级跨 MySQL+对象+索引+Redis 的非原子提交为 outbox/对账契约 |
| 模型 | `rag/llm/` 的 chat/embedding/rerank/vision/OCR/ASR/TTS provider；Go `ModelDriver`/`ModelProviderService` | provider client、错误分类、token usage、流式解码、模型能力描述 | 模型路由、提示词、上下文、RAG/Agent 调用策略 | 超时/重试/限流/成本/凭证隔离/熔断/审计 | provider/model 配置、OpenAI 兼容、流式 chat | 吸收错误分类与 usage；升级为统一模型能力契约，禁止知识模块依赖具体 SDK 对象 |
| 前后端服务 | Python Quart 动态 Blueprint、Go Gin router/handler/service、`web/` hooks→services→utils；proxy scheme `python/hybrid/go` | HTTP/SSE/JSON/MCP/OpenAI 协议编码、鉴权 token、分页 | 领域服务只编排公共能力并形成领域返回 | tracing、request budget、请求取消、跨服务 correlation id、审计 | 唯一外部网关和兼容路由；前端只调网关 | 网关吸收协议兼容；Python/Go handler 不得成为第二个领域 owner |

### 13.3 现有能力命中、缺口与复用裁决

| 分类 | 已定位能力 | 底座处理结论 |
|---|---|---|
| 吸收 | DeepDOC 的乱码门控/OCR/版面/表格；`TokenChunker` 的参数校验、父子块和媒体上下文；`Embedding` 批处理与 provider 适配；`Dealer` 的全文+dense+rerank；`Canvas` DSL/path/事件；Go `Storage` 接口；Go pipeline checkpoint/RunTracker | 作为 L1/L2 设计证据吸收，不复制 RAGFlow 目录和第三方对象 |
| 升级 | Python/Go 两条 parser、ingestion、agent、task 路径；MySQL 状态、对象存储、索引、Redis/MQ 分散写入；任务状态和消息 ack 的耦合；模型错误/usage 形状 | 先建立统一公共契约和适配器；生产迁移前需能力需求登记、复用决策、占用租约与回归验收 |
| 新增候选 | 跨后端统一命令信封（`operation_id/task_id/correlation_id`）、任务租约 epoch、跨存储 outbox/对账、统一预算声明、资源释放证据、索引幂等写入 | 归 L3 运行核心；当前 RAGFlow 有局部实现但没有证据表明已形成平台级唯一 owner |
| 隔离/废弃候选 | 业务模块直连 Redis/ES/LLM SDK、API 层各自翻译任务状态、`_prune_deleted_chunks` 代替删除事务、Python/Go 双公共入口 | 不能继续扩散；由唯一网关/L2/L1 适配层收口，旧路径仅在迁移回滚窗口保留 |
| 待核 | Go 与 Python 在真实部署中的最终 route owner、同一 schema 的写入仲裁、各 document engine 对 vector/分页/删除的精确语义、远程 DeepDOC/DLA 的生产租约 | 必须通过配置、集成测试和运行证据裁决，当前核对不宣称已收敛 |

## 14. 资源预算、状态与租约

### 14.1 资源预算表

以下是源码可定位的默认值或硬边界，不是已经注册到系统工程平台的统一预算。平台迁移时应把每项变成能力契约的 `预算声明`，并由 L3 在提交前拒绝超预算，而不是由 provider 自己决定是否继续。

| 资源/阶段 | RAGFlow 当前预算或行为 | 证据路径 | 平台契约建议 |
|---|---|---|---|
| 单文档输入 | `MAX_CONTENT_LENGTH` 默认 128MB；用户文件数由 `MAX_FILE_NUM_PER_USER` 控制 | `common/settings.py`、旧细探 §四 | 网关先拒绝；解析器再按格式/解压后大小设二级上限 |
| PDF 解析 | `PDF_PARSER_PAGE_BATCH_SIZE` 默认 50 页；空结果可提高 `zoomin` 重试 | `deepdoc/parser/pdf_parser.py::parse_into_bboxes` | 页窗、图像像素、OCR 时长、临时文件分别计费/限额，禁止只限原始字节 |
| Chunker | Go 文本 payload 按主分隔片段 fan-out 4 goroutines；token size、overlap、媒体上下文由 `TokenChunkerParam` 校验 | `internal/ingestion/component/chunker/token.go` | 并发、最大块数、单块 token、父子展开倍数需显式预算；取消只能在 ctx 检查点生效 |
| Embedding | Python `EMBEDDING_BATCH_SIZE=16`；每批 `@timeout(60)`；文本截断 `mdl.max_length-10`；标题权重默认 0.1 | `rag/svr/task_executor.py::embedding` | 绑定模型版本/维度；批超时可重试但不得重复计费，记录 token/批次/向量数 |
| LLM/chat | `LLM_TIMEOUT_SECONDS=600`、`LLM_MAX_RETRIES=5`、`max_rounds=5`；仅 rate-limit/server 错误重试，带抖动退避 | `rag/llm/chat_model.py::Base` | 按请求/工作流/租户设 token、美元、轮次、并发总预算；超预算返回稳定错误而非继续重试 |
| Retrieval/rerank | 旧细探记录 Retrieval 工具 12s、Jina rerank 30s；候选窗约 64 且向上对齐 `page_size` | `rag/nlp/search.py::Dealer._rerank_window`、旧细探 §四 | 召回 topK、rerank pool、页深、外部调用数和总时限绑定，保持窗口整除不变量 |
| Canvas/沙箱 | 组件执行默认 10min，Agent 组件可到 20min；沙箱为独立 provider，有 stdout/stderr、exit code、artifact 和 workspace | `common/settings.py`、`agent/sandbox/.../schemas.py` | 子进程/容器/文件/网络/输出/CPU 内存配额统一挂到 operation id，finally 清理 workspace |
| Python 任务 | Redis 优先级队列、worker heartbeat timeout 120s；进度写 DB 并检查 `has_canceled` | `rag/svr/task_executor.py` | 队列租约、可见性超时、最大重投、死信和任务级 deadline 必须显式记录 |
| Go ingestion | 默认并发为 `runtime.NumCPU()`；`taskChan` 容量为 `maxConcurrency*2`；每次 MQ `GetMessages(4)`；heartbeat 默认 10s、cancel poll 3s | `internal/ingestion/service/ingestion_service.go` | worker 数、缓冲、消息批量、AckWait、heartbeat、cancel 检查间隔纳入资源预算；队列满必须可解释地 Nack/backpressure |
| Go pipeline/checkpoint | checkpoint/RunTracker TTL 24h；可恢复循环最多 1000 轮；无 store 时可降级不可恢复，但生产 `WithRequireResume()` 会拒绝启动 | `internal/ingestion/pipeline/pipeline.go` | 生产任务禁止静默降级；TTL 到期、checkpoint 删除失败和恢复次数超限写证据并进死信/人工处理 |
| 索引/存储 | Go `chunkIndexWriter` 按 bulk size 写；`bulkSize<=0` 一次写全量；对象存储接口未统一声明大小/超时/事务 | `internal/ingestion/task/chunk_index_writer.go`、`internal/storage/types.go` | bulk、单请求字节、并行连接、重试和部分成功位置必须在写入回执中可对账 |

### 14.2 状态与租约分层

| 对象 | 当前状态 owner | 租约/可见性 | 失败后的事实 | 迁移风险 |
|---|---|---|---|---|
| Python task | `TaskService`/Peewee task 行；`set_progress` 写 progress/progress_msg | Redis Stream consumer group 的 pending/unacked 消息；`get_unacked_iterator` 支持再领取 | 已取消任务 ack 并丢弃；执行异常写错误进度；进程退出依赖 pending 再投 | 没有跨 Python/Go 共用 epoch/lease owner，重复执行与状态覆盖需裁决 |
| Go ingestion task | `IngestionTaskService`/GORM，状态 `CREATED→RUNNING→STOPPING→STOPPED` 或 `COMPLETED/FAILED`；转换带冲突错误 | MQ handle `InProgress()` 默认 10s；进程内 `currentTasks` claim 防重投 | DB terminal 状态为 Ack 权威；非 terminal Nack；panic recover 后 MarkFailed/Nack | `currentTasks` 只在进程内，重启后的唯一性依赖 DB/MQ，需 durable lease/epoch |
| Pipeline run | Canvas `RunTracker` + Redis checkpoint，`taskID`/checkpoint id | interrupt id、TTL 24h；成功清 checkpoint；取消清 checkpoint | crash 可从 interrupt id 继续；恢复失败记录错误；超 1000 轮失败 | checkpoint 与文档/索引写入不是同一事务，可能出现已索引未投影或反之 |
| Document state | Python `Document`/Go `Document` 的 run/progress/chunk/token 字段 | 非独立 lease；由任务执行器/`docState.apply` 投影 | 删除路径回查 task 与 document engine；跨存储失败可能残留 | MySQL/Peewee 与 GORM 双 owner 事实，禁止同时无仲裁写 |
| Object/index/cache | storage factory、`DocStoreConnection`、Redis 各自 owner | SDK/连接/锁由 provider 管；当前未见统一租约字段 | bulk/对象写失败通常返回 error；前面已成功的批次不会自动回滚 | 需要 operation id、批次序号、幂等键、outbox/对账和残留扫描 |

租约裁决：L3 的任务租约必须至少包含 `operation_id、task_id、owner_id、attempt、lease_epoch、acquired_at、expires_at、heartbeat_at、cancel_requested`。消息 Ack/Nack 是传输确认，不等于业务完成；`InProgress` 是 broker 可见性租约，不等于数据库状态锁；进程内 `currentTasks` 只能作快速去重，不能作为崩溃恢复后的权威 owner。

## 15. 失败、超时、取消与崩溃矩阵

| 环节 | 业务失败 | 超时 | 主动取消 | 进程/宿主崩溃 | 底座收口要求 |
|---|---|---|---|---|---|
| 读取/解析/OCR | Python 多处降级为空列表或重 OCR；Go parser dispatch 返回带 stage 的 error，禁止输出半结果 | 页批/外部 OCR/DLA 需受 ctx 或阶段 deadline 约束；原生调用是否完全响应取消仍待核 | Python `has_canceled` 在 progress 点抛 `TaskCanceledException`；Go parser 传 ctx | Python pending 消息可再领取但中间临时物不一定有清单；Go Stop 注释明确 native CGO 可能阻塞 | 解析结果必须带 `source_hash/parser_version`；临时目录 finally + 崩溃清扫；失败不发布索引指针 |
| 切分/tokenize | 参数校验失败或输入形状错误返回 `_ERROR`/error；Go 结构化输入统一转换 | Go chunker 只承诺 ctx cancellation，没有独立 timeout | ctx 下一检查点停止；已生成内存块丢弃 | 纯内存中间块丢失，可从任务重跑 | 块批次序号/幂等键；限制 fan-out/单块 token/输出数量 |
| Embedding | provider `ModelException`/`EmbeddingError`；绑定模型或维度不符失败 | Python 单批 60s；LLM/HTTP provider 还受 client timeout；Go 依赖 ctx | embedding 批次之间检查；已提交 provider 请求是否可撤销需 provider 契约 | 重跑可能重复调用、重复计费；已写部分向量需按批次对账 | provider 错误码+可重试标志+usage；重试只对安全错误，按 request hash 幂等 |
| 召回/重排 | 索引后端/外部 reranker error；空结果有降级重试 | 检索工具约 12s、Jina 约 30s；窗口/分页不能因超时改变语义 | 请求取消必须终止 query/HTTP 流并释放连接 | 查询通常是无状态，但流式连接和外部请求可能残留 | 统一 `RETRIEVAL_TIMEOUT`/`MODEL_TIMEOUT`，返回候选快照版本与 partial 标记 |
| 索引写入/删除 | `InsertChunks`/`DocStoreConnection` error；删除残留由 `_prune_deleted_chunks` 补偿 | 当前 Go writer 只检查 ctx，没有统一 bulk deadline | 在批次边界停止；已写批次保留 | 可能出现前 N 批已写、关系库未计数或反向情况 | 写入 manifest、批次 offset、幂等 upsert、重启 reconciliation；禁止把补偿过滤当事务 |
| 工作流/Agent | Graph 组件支持 `goto/default_value/终止`；LLM tool loop 错误归统一 error | 组件 10/20min，LLM 600s，max rounds 5；超限必须结束 | `cancel_task` 写 Redis cancel key，Graph 抛 `TaskCanceledException`/Go ctx canceled | Canvas checkpoint/RunTracker 能恢复非终端节点；无 Redis 时生产拒绝启动可恢复任务 | 每个 node event 带 operation/task/run/node；恢复只允许幂等节点或明确 replay policy |
| 队列/worker | DB transient error Nack；terminal 状态 Ack；任务已删除/已终态 Ack-skip | heartbeat 维持 AckWait；消费错误 1s backoff；业务 deadline 来自 ctx | `STOPPING`+Redis cancel，poll 每 3s，最终 STOPPED | Go panic 被 recover、MarkFailed、Nack；Stop 超时交 broker redelivery；Python signal 只设置 stop_event 后退出 | 重投次数、死信、毒任务、lease epoch、panic 栈脱敏、Ack/Nack 结果都入证据 |
| 存储/状态投影 | DB/对象/索引分别返回 error，跨系统没有单事务 | `FetchBinary` 监听 ctx，但 goroutine 中 provider 调用自身可能继续 | ctx 返回后必须关闭/回收连接；取消不能把已提交事实标成未提交 | 崩溃窗口可能留下对象、索引、Redis checkpoint 或 DB task | L3 outbox/事务日志/对账，成功/失败/取消/超时/崩溃四终态可重建 |

当前可确认的恢复语义只有局部：Go pipeline 对 checkpoint 有成功删除、取消清理和 `RunTracker` 恢复；Go ingestion 对 panic/terminal DB truth 有处理；Python Redis pending 提供再次领取线索。不能据此宣称“全链路 exactly-once”或“跨存储原子回滚”。合理的底座语义应是 **at-least-once transport + idempotent business commit + durable reconciliation**。

## 16. L0-L4 目标分层与边界

| 层级 | 目标职责 | RAGFlow 对应 | 允许依赖 | 禁止事项 | 验收等级 |
|---|---|---|---|---|---|
| L0 提供者/宿主 | 第三方 SDK、模型 API、OCR/原生库、DB/MQ/对象/索引、容器/进程 | `deepdoc` native/remote、`rag/llm` provider、MySQL/Redis/NATS/ES/MinIO、Go `ModelDriver`/storage implementations | 只依赖宿主和 provider SDK；通过适配器报告能力/错误/资源 | 不持有知识业务状态，不直接改任务/文档事实，不隐藏重试/无限超时 | 缺 provider、断网、超时、崩溃、资源释放均有可执行探针 |
| L1 支持库 | 一个原子能力一个 owner 和契约：parse/chunk/embed/retrieval/storage/model/queue client/sandbox | `DocStoreConnection`、`Storage`、parser/chunker/embedding/model base、checkpoint client | 依赖 L0，向上只暴露公共类型/错误/事件 | 不编排 dataset/tenant/workflow，不旁路网关，不复制任务系统 | 契约、参数、错误码、超时/取消、资源生命周期测试 |
| L2 知识模块 | 领域流程与策略：摄取、检索、问答、GraphRAG/RAPTOR、工作流、记忆 | `rag/flow`、`rag/nlp`、`rag/graphrag`、`agent`、Go `internal/ingestion`/service | 只调用 L1；通过 L3 提交运行与持久化意图 | 不直接持有 provider SDK/连接池/消息 lease，不各自定义状态机 | 端到端领域回放、输入/输出结构、权限和降级矩阵 |
| L3 运行核心 | 任务、状态、租约、预算、取消、检查点、幂等、重试、恢复、证据、观测 | Go ingestion worker/RunTracker 是局部样本；Python task executor 是局部样本 | 调用 L1，接受 L2 命令，写权威状态/事件 | 不理解 PDF/检索业务，不被某个 provider 反向驱动，不把 Ack 当完成 | 故障注入：kill、断连、超时、取消、重投、恢复、残留对账 |
| L4 网关/交互 | HTTP/JSON/SSE/MCP/OpenAI/SDK、鉴权、版本兼容、前端服务层 | `api/apps`、`internal/router/handler`、`mcp/server`、`sdk`、`web` | 调 L2/L3 唯一公开入口；协议转换在边界完成 | 不直接访问 DB/ES/LLM/对象存储，不创建第二任务入口，不把内部 provider 错误散给用户 | route/权限/限流/流式断开/错误形状/前后端回归 |

L0-L4 不是把当前目录机械搬家：例如 `internal/ingestion/component/parser.go` 作为 L2 的流程组件可以保留，但具体 `parser.GetParser` provider 解析必须落在 L1/L0 边界；`internal/service/document` 是 L2 领域服务，不能因为它调用 DAO 就升级为 L3；`api`/Gin handler 只能是 L4，即使历史代码里包含业务逻辑，也应在迁移裁决中标为边界债务。

## 17. 装配计划、唯一契约与验收等级

### 17.1 唯一契约最小集合

平台接入 RAGFlow 时只允许注册以下能力族（名称为裁决用规范名，非声称当前项目已经提供这些平台 id）：

- `文档解析.解析`：输入 `source_ref/file_type/parser_config/model_refs`，输出通用 `DocumentIR`，含来源位置、媒体资源、parser/provider/version、可重试错误。
- `文档切分.切分`：输入 `DocumentIR/chunk_policy`，输出带稳定 `chunk_id/parent_id/position/content_hash` 的 `ChunkSet`。
- `向量模型.Embedding`：输入 `model_ref/texts/request_id`，输出按 index 对齐的 vectors、维度、token usage、provider trace。
- `知识检索.查询`：输入 `query/filter/embedding_ref/top_k/page/timeout`，输出候选快照、分数解释、partial/has_more。
- `工作流.运行`：输入 DSL/version/input/run budget，输出事件流、状态快照、artifact manifest。
- `任务.提交/查询/取消`：由 L3 唯一 owner 实现，领域模块不能直连 Redis/NATS/MQ。
- `对象存储.读写`、`关系状态.读写`、`文档索引.写入/查询`：分别声明一致性、幂等、超时和释放责任。
- `模型.对话/重排/视觉`：统一 `model_ref`、usage、错误分类、重试和取消语义。

所有历史英文键、Python/Go 函数名和 provider 名只能在 L4/L2→L1 的一个归一化入口处理；不能在 web、SDK、Python API、Go API、MCP 各维护一张别名表。

### 17.2 装配波次

1. **S0 契约冻结**：冻结 `DocumentIR/Chunk/EmbeddingResult/RetrievalResult/TaskEvent/ArtifactManifest`、错误码、预算字段、状态图和租约字段；记录 Python/Go 当前字段映射及冲突。
2. **S1 L1 提供者适配**：先接 parser、chunker、embedding、index、object storage、model client；每个 provider 做缺失/超时/取消/断连/崩溃探针，不在 L2 里复制 SDK 逻辑。
3. **S2 L3 运行闭环**：统一 task command、lease epoch、heartbeat、cancel、checkpoint、ack/nack、重投/死信、outbox/对账；先用 Go ingestion 的状态/心跳/checkpoint 作为证据样本，不能直接当平台实现。
4. **S3 L2 领域收口**：将 Python `task_executor`、Go `PipelineExecutor`、`Dealer`、`Graph` 接到唯一能力入口；验证同一输入在两个实现下的结构化结果和状态投影。
5. **S4 L4 网关切换**：前端、SDK、MCP、OpenAI 兼容接口只接一个网关；`python/hybrid/go` 仅为内部路由策略，记录 `X-API-Source`/correlation id 并可回滚。
6. **S5 反向破坏与清理**：删除/阻断直连 provider、旁路写库、第二队列和第二状态翻译；对索引残留、对象残留、checkpoint 残留、死进程/连接/临时目录做现场扫描。

### 17.3 L0-L4 验收等级

| 等级 | 证明什么 | RAGFlow 当前核对状态 |
|---|---|---|
| L0 | 路径/符号/配置/接口源码存在，能描述输入输出与边界 | 已完成静态读取；本地 CodeGraph 索引最新 |
| L1 | 单个支持能力真实调用，错误/超时/取消/资源释放有结果 | 未执行；不能把源码存在写成通过 |
| L2 | 文档摄取、检索、工作流等领域链真实回放，状态/事件/引用一致 | 未执行；Python/Go 最终 owner 待核 |
| L3 | 队列租约、重投、checkpoint、kill/断连/超时/取消/崩溃恢复和对账真实通过 | 未执行；当前源码只有局部实现证据 |
| L4 | 网关+前端/SDK/MCP 全链路、权限、流式断开、版本兼容和生产资源预算通过 | 未执行；不得宣称部署完成 |

当前核对结论为“后续映射输入”，不是底座生产变更。没有需求登记、能力搜索、复用/新建裁决、文件租约、验收契约和装配计划，不应修改系统工程平台生产代码。

## 18. 后续风险与证据边界

- 本轮未使用 MCP；目标工作树 CodeGraph 已同步，当前索引统计为 4,783 files、99,019 nodes、307,732 edges，状态为 `up to date`。
- 当前核对没有安装依赖、启动 MySQL/Redis/NATS/ES/MinIO、调用模型/OCR、运行 Go/Python/前端测试或构建 native 库；因此 L1-L4 均未通过实测。
- 当前源码允许 checkpoint 不存在时 `Pipeline` 降级为不可恢复运行，但生产 `WithRequireResume()` 会拒绝；该差异必须在平台契约中显式化，不能靠默认值。
- Go `settleMessage` 以数据库 terminal 状态为 Ack 权威，Python 侧依赖 Redis pending/TaskService；两边没有已证实的跨实现统一 lease epoch，重复执行、部分索引写入和双 schema 写入仍是高风险。
- `细探-RAGFlow.md` 保留不删、不改；后续长期维护入口仍只有本 `ARCHITECTURE.md`。

## 19. 后续收口：双路径、解析/切分/Embedding/检索、队列与持久化

> 本节是后续内部深挖的收口，不是后续底座设计。证据均来自本地工作树 `f796721f`；只写已经读到的源码行为，并把“实现存在”和“跨存储恢复已证明”分开。旧 `细探-RAGFlow.md` 不删除，后续只维护本文件。

### 19.1 Python/Go 双路径的真实选择器

两条路径不是简单的“Python 旧、Go 新”目录并列，而是由不同入口、任务载荷和运行开关选择：

```text
Python API/任务创建
  → api/db/services/task_service.py::queue_tasks / queue_dataflow
  → Peewee Task 行 + Redis Stream XADD（te.<priority>.<suffix>）
  → rag/svr/task_executor.py::collect → handle_task
  → TE_RUN_MODE=0: TaskManager.run_refactored_task → TaskHandler/ChunkService
  → TE_RUN_MODE=1: 先 do_handle_task 原路径，再 dry-run refactor 对比
  → 其他值: do_handle_task 原路径

Go HTTP/任务创建
  → internal/service/ingestion_task_service.go::CreateAndEnqueue
  → GORM IngestionTask 状态 CREATED + NATS JetStream tasks.RAGFLOW
  → internal/ingestion/service/ingestion_service.go::Start/processMessage
  → bounded taskChan → workerLoop → PipelineExecutor/DocumentService
```

- Python 当前默认 `TE_RUN_MODE` 是 `"0"`，因此 `TaskManager` 重构路径是默认执行路径；`"1"` 不是普通生产模式，而是“原路径执行 + 记录写操作 + 重构路径 dry-run + 比较”的迁移验证模式；只有其他值才显式走 `do_handle_task` 原路径。证据：`rag/svr/task_executor.py::handle_task`、`rag/svr/task_executor_refactor/task_manager.py`。
- Python 的 `queue_tasks` 按 PDF 页范围、表格行范围或整文档生成 `Task`，以 chunking config + `doc_id/from_page/to_page` 计算 `xxhash` digest；可复用已完成任务的 `chunk_ids`，删除旧任务和旧索引后再批量建新任务、`begin2parse`、seed Redis counter、逐条 `queue_product`。`queue_dataflow` 则写 dataflow Task 后将 `dataflow_id` 放入消息。
- Go 入口把一个文档的 `IngestionTask` 作为数据库唯一任务（`Create` 先按 document 查重；失败/停止任务允许转回 CREATED），再调用 `PublishTaskMessage`；发布失败会删除新建任务或把重试任务 CAS 回原终态。状态 CAS 位于 `internal/dao/ingestion.go::UpdateStatusIfCurrent`，不是进程内锁。
- 结论：当前“Python 任务表/Redis Stream”和“Go IngestionTask/NATS”各自拥有任务消息与状态写法；源码没有证明二者共享同一 task id、lease epoch 或跨实现仲裁。因此“Go 可替代 Python”只能标记为迁移期事实，不能写成已经单路径收敛。

### 19.2 DeepDOC：Python 完整质量门与 Go 结构化复刻的边界

**Python DeepDOC** 的 PDF 入口仍是 `deepdoc/parser/pdf_parser.py::RAGFlowPdfParser.__call__` / `parse_into_bboxes`：

1. `extract_pdf_outlines`；
2. `__images__`：字符层 `pdfplumber.dedupe_chars()`、页面图像、PUA/CID 与字体子集乱码门控；乱码框清层后进入 OCR；多设备时用 `PARALLEL_DEVICES` 分片；
3. `_layouts_rec`：版面模型给 `Text/Title/Figure/Figure caption/Table/Table caption/Header/Footer/Reference/Equation` 及 bbox；
4. `_table_transformer_job`：TSR/旋转校正；
5. `_text_merge`、`_concat_downward`、分页过滤；
6. `_extract_table_figure`：表格/图片、caption、位置与媒体结果；再过滤 scraps。

`parse_into_bboxes` 不是只在文档级循环：`PDF_PARSER_PAGE_BATCH_SIZE` 默认 50 页，超过窗口时逐窗调用 `__images__` 与 `_parse_loaded_window_into_bboxes`，通过 `_to_global_boxes` 拼回全局坐标，并给 callback 发送页进度；窗口没有 box 时 `__images__` 可把 zoom 提高到下一档（上限 `<9` 的递归条件）。普通 `__call__` 与分窗路径的后处理并不完全相同：分窗路径额外调用 `_naive_vertical_merge`，不能把两者描述成同一个函数序列。证据：`deepdoc/parser/pdf_parser.py:1744-1829`。

**Go DeepDOC** 不是把 Python OCR/TSR HTTP 化：

- `internal/deepdoc/parser/pdf/parser.go::Parser.processPage` 按页并行处理字符抽取、渲染、OCR/字符融合、DeepDoc layout/TSR、表格；按页保存 `pageResult`，最终按页码排序汇总，避免 worker 完成顺序改变输出。渲染/OCR/DLA/TSR 失败被划为可恢复页级错误，保留字符 fallback 或空表；worker 编排 panic 才是 fatal。默认渲染是 DLA DPI，单页无 box 时才做每页 zoom retry，重试 zoom 上限 9。
- `internal/deepdoc/parser/type/types.go` 的 `ParseResult` 持有 `Sections/Tables/PageHeight/PageWidth/Metrics/Outlines/DLARegions` 以及仍由调用方持有的 `Engine PDFEngine`；`ParseResult.Close()` 幂等释放 native engine。这个 engine 所有权是 Go 路径必须显式收口的资源边界。
- `internal/deepdoc/client.go` 只对配置的 `DEEPDOC_URL` 或旧名 `TENSORRT_DLA_SVR` 提供 DLA HTTP 调用：每次最多 3 次，重试网络、5xx、响应校验失败，不重试 4xx/ctx cancel，单次请求默认 18 秒。`internal/deepdoc/ocr.go` 和 `internal/deepdoc/tsr.go` 明确是无条件返回 `ErrNoRemoteEndpoint` 的 stub：Python OCR/TSR 是本地 ONNX 路径，不存在可假定的远程 OCR/TSR provider。Go parser 的 DeepDOC 质量链由本地 native/CGo 与 DLA 接口拼成，不能写成“Go 调 Python DeepDOC 服务”。
- Go parser 以 `internal/parser/parser/parser_type.go::GetParser` 按 `utility.FileType` 选择 PPT/PPTX/XLS/XLSX/CSV/DOC/DOCX/PDF/HTML/Markdown/TXT/EPUB/JSON/EMAIL/图片/音频 parser；统一 `ParseWithResult(context.Context, filename, data)`，成功输出 `output_format` 与唯一 payload（`json/markdown/text/html`），失败时 payload 清空。`internal/ingestion/component/parser_dispatch.go` 再从 `file_type/name` 推断类型、读取 setup 的 `parse_method`/`output_format`、校验白名单并把 parse_method 写入 `File` 元数据。

### 19.3 解析→切分→Embedding 的阶段契约

Python 重构摄取路径的实际阶段是 `ChunkService.build_chunks` → parser/chunker → 图片对象上传 → keywords/questions/metadata/tags → `Tokenizer`（若 dataflow 先由 `DataflowService` 规范化并在缺向量时补 embedding）→ `ChunkService.insert_chunks`。旧 `do_handle_task` 仍保留同类链，但默认 `TE_RUN_MODE=0` 不走它。

- **切分输入与字段**：Python `rag/flow/tokenizer/tokenizer.py` 接受 `chunks` 或 parser 的 `markdown/text/html/json`；`full_text` 分支写 `title_tks/title_sm_tks/content_ltks/content_sm_ltks`，并把 questions/keywords/summary 转为检索字段；`embedding` 分支只对去掉 HTML table 标签后非空的文本调用模型。`Tokenizer` 从 KB 的 `tenant_embd_id` 或 `embd_id` 解析 `LLMBundle`，标题先单独编码，正文按 `settings.EMBEDDING_BATCH_SIZE`（默认 16）分批，在 `embed_limiter` 下执行 `@timeout(60)`，正文截断到 `max_length-10`，最后写 `q_<dim>_vec = 0.1*title + 0.9*content`（权重可配置）。空 chunk/空文本不是异常，embedding no-op；模型解析失败、返回向量数不一致则失败。
- **Go Tokenizer**：`internal/ingestion/component/tokenizer.go` 将 upstream 解析结果规范到 `schema.ChunkDoc`，full-text 走 `internal/tokenizer`，embedding 通过注入的 `DefaultEmbedderResolver` 按 tenant/kb/model setup 解析；正文仍按 16 分批，单批由 `runtime.WithTimeout` 控制（默认 600 秒，可由 `COMPONENT_EXEC_TIMEOUT_TOKENIZER` 改），而不是 Python 的 60 秒 decorator；每批验证返回向量数，标题与正文做同维度校验和 0.1/0.9 合成。Go 明确不在 component 包直接依赖 service，而由组合根注入 resolver。
- **Python chunk 写入前**：`ChunkService._prepare_docs_and_upload` 用 `xxhash(content_with_weight + doc_id)` 生成 id；带 image 的 chunk 先经 `image2id` 上传对象存储，`img_id` 保存对象引用；`_create_mother_chunks` 从 `mom/mom_with_weight` 生成 `mom_id`、`available_int=0` 的母块。
- **Go chunker**：`internal/ingestion/component/chunker/token.go` 校验 `delimiter_mode`、token size、overlap、父子 delimiters、表/图上下文；`token_size` 是 split→greedy merge，`delimiter` 是 regex 分段不再合并，structured JSON 与文本 payload 统一进入 chunk shape。文本段/structured items 由 goroutine fan-out，但结果按输入 index 合并；仅承诺 ctx cancellation，未提供 Python `@timeout` 等价物。当前注释明确不处理 Python `restore_pdf_text_previews`，PDF/outline 语义仍由上游 parser/其他组件负责。

### 19.4 索引、对象、关系库的写入顺序与非原子窗口

**Python 重构路径的真实顺序**：

```text
storage.Get(bucket, name)
  → parser/chunker 生成 cks
  → image2id: STORAGE_IMPL.put(tenant_id, image object)
  → metadata/keywords/questions/tags
  → docStoreConn.insert(mother chunks, DOC_BULK_SIZE)
  → docStoreConn.insert(main chunks, DOC_BULK_SIZE)
  → 每个批次 TaskService.update_chunk_ids(累计 id 串)
  → DocumentService.increment_chunk_num(doc,kb,token,chunk,duration)
```

- `ChunkService._insert_mother_chunks` 先写母块；`_insert_main_chunks` 分批写主块，批后检查取消，再把从开头到当前批的 chunk id 累积写入 Task。index 返回非空错误时以 `[ERROR]` 更新进度并抛异常；Task 更新失败则删除已写 chunk 与关联图片。取消只对部分 RAPTOR summary 做专门回滚，普通已成功批次依赖重跑/删除路径，不能宣称全链路事务。
- `DocMetadataService.update_document_metadata` 的关系库查询只用于拿 tenant/kb；真正的 metadata index 写在 ES/Infinity：ES 优先 `replace_meta_fields` 完整替换，失败或文档不存在时 delete+insert；Infinity 直接 delete+insert。`DocumentService.increment_chunk_num` 则在同一 Peewee `DB.atomic()` 内递增 Document 与 Knowledgebase 的 token/chunk/process_duration，并在任一行不存在时抛错。这是关系库内部原子，不覆盖对象和索引写入。
- `DocStoreConnection` 的 Python 公开抽象是 `create_idx/delete_idx/index_exist/search/get/insert/update/delete`；`insert` 语义是 bulk upsert。ES 连接有重试与 `get` 的超时错误传播；Infinity 连接按表和向量维度建表/向量索引。`_prune_deleted_chunks` 只在检索后以关系库 Document id 过滤索引残留，是安全网，不是写入事务。

**Go ingestion 路径的真实顺序**：

```text
Pipeline.Run（可恢复 DSL）
  → PipelineExecutor.processOutput
  → NormalizeChunks / ProcessChunksForPipeline（补 id、doc_id、kb_id、字段/位置）
  → chunkIndexWriter.Write（DOC_BULK_SIZE；0=整批）
  → engine.Get().InsertChunks
  → 成功返回 PipelineResult
  → docStateUpdater.apply（metadata merge + Document/KB counter）
```

- Go `chunkIndexWriter` 在每批前检查 ctx，上一批已经成功写入不会自动回滚。ES `InsertChunks` 以 bulk `index`（同 `_id` 更新/插入）发送，`refresh=wait_for`，并检查顶层 `errors` 及 item reasons；Infinity `InsertChunks` 自动建表（从 `q_<dim>_vec` 推断维度），先按 id 删除旧行再 insert，删除失败只 warning，随后 insert 失败才返回 error。Infinity 这条“删后插”不是事务。
- Go `docStateUpdater` 在索引成功后才更新文档事实；metadata 先读再只填充不存在的 key，读失败会放弃完整覆盖，计数更新失败只记录 warning，不使任务失败。Go `progressSink` 另写 `ingestion_task.component_total`、`ingestion_task_log` 并镜像 Document progress；这些进度/统计写入均是可观测性或 best-effort，不等价于 index commit。
- Go `internal/storage.Storage` 是对象存储 provider 接口（Put/Get/Remove/List/PresignedURL/Bucket/Copy/Move/Close），可选 MinIO/Azure/S3/OSS/OpenDAL/GCS；它没有跨对象、关系库、索引的事务/commit marker。Python `File2DocumentService.get_storage_address` 从 File/File2Document 解析 bucket/key，非 local source 回落 Document 的 kb_id/location；也没有和 Task/Index 同事务的对象写协议。

### 19.5 检索路径的候选窗口、向量归属和删除残留

`rag/nlp/search.py::Dealer.retrieval` 的当前 ES 路径可精确写成：

1. `page/page_size/top` 先计算 `RERANK_LIMIT = ceil(64/page_size)*page_size`，外部 reranker 存在时再按 `top` 向下绑定到 page_size 的整数倍；后端请求的 page 是 `global_offset // RERANK_LIMIT + 1`，size 是窗口，保证排序后切片 `global_offset % RERANK_LIMIT` 对齐。
2. `Dealer.search` 通过 `DocStoreConnection.search` 组合全文/向量表达式；ES 召回后 chunk vector 不随主 `_source` 返回，`_knn_scores` 对候选 id 做第二次 KNN-only 查询取 `_score`，应用层只拿 term fields + ES cosine 分数。OceanBase 仍走携带向量的本地 `rerank`，Infinity 直接采用后端归一化融合分数。
3. `rerank_with_knn` 的 term 特征为 `content + title*2 + important*5 + question*6`，按 `term_weight/vector_weight` 合成，再加 tag feature/PageRank；外部 reranker 由 `RerankModel.Base.similarity` 负责归一化到 `[0,1]`。稳定排序后再做 threshold；当 vector weight=0 时 threshold 对 term-only 结果不生效。
4. 在重排前 `_prune_deleted_chunks` 回查关系库 Document id，剔除父文档已不存在的索引 chunk；结果还返回 `similarity/vector_similarity/term_similarity`、positions、mom_id 等稳定字段。citation 场景需要向量时再用 `fetch_chunk_vectors` 按 chunk id 显式取回。

检索因此是“索引召回 + 关系库存在性补偿 + 应用层重排”的组合，不是关系库事务读，也不是全后端统一 vector semantics；各 engine 分支必须分别验证。

### 19.6 队列确认、取消、重试、崩溃与恢复矩阵

| 维度 | Python Redis Stream | Go NATS JetStream |
|---|---|---|
| 发布 | `queue_product` 把 JSON 包成 `{"message": json.dumps(message)}` 后 `XADD`，失败最多重连重试 3 次 | `PublishTask` 5 秒 context 发布 `tasks.RAGFLOW`；stream `RAGFLOW_TASKS` 为 file storage、WorkQueuePolicy、MaxMsgs 128K、MaxBytes 1MB |
| 消费 | `queue_consumer` 建/复用 group，`XREADGROUP` 每次 1 条、block 5 秒；先 `get_unacked_iterator` 从 pending 消息重取 | `GetMessages(4)` Fetch，consumer explicit ack、MaxDeliver 16、MaxAckPending 128K；每条 handle 由 ingestor 负责结算 |
| 去重/租约 | Python `CURRENT_TASKS` 只做本进程观测；消息处理期间没有 Go 式 DB CAS claim；Redis pending 是传输态，不是业务 lease | `currentTasks` mutex 只防同进程重复；DB `StartRunning`/`UpdateStatusIfCurrent` 做状态 CAS；heartbeat 每 10s `InProgress` 并在 ack/nack 前等待 heartbeat goroutine 退出 |
| 取消 | `has_canceled(task_id)` 查 `<task_id>-cancel`；`set_progress` 每次进度更新都会检查，命中抛 `TaskCanceledException`；取消 flag 由 `cancel_all_task_of`/API 写入 | `RequestStop` CAS RUNNING→STOPPING 并写 Redis `<task>-cancel`；worker 启动及每 3 秒轮询，cancel context 后 `markStopped` 写 Document cancel progress、STOPPING→STOPPED、清 flag |
| 失败/确认 | `handle_task` 成功、取消或异常后都落进度/日志，但 `finally` 最终无条件 `redis_msg.ack()`；因此 Python 当前源码没有把业务异常自动 NACK 交给 Stream 重投，重试主要靠取 Task 时递增 `retry_count` 和后续重新排队/未完成文档同步 | `settleMessage` panic 会 recover、MarkFailed；读取 DB 终态是 Ack/Nack 权威：COMPLETED/STOPPED/FAILED Ack，非终态 Nack；Nack 交给 broker redelivery |
| 崩溃/停止 | Redis pending 提供再次领取入口，`report_status` 维护 executor heartbeat 并清理过期 worker；Task retry 达 3 次时标 Document FAIL、abort chunk counter。当前未证明进程崩溃后对象/index/task 可自动对账 | `Stop(ctx)` 取消根 context 并等待 worker；超时不强杀不响应 ctx 的 native CGO，返回并让 broker redeliver；Go pipeline checkpoint/RunTracker 用 Redis TTL 24h 保存 interrupt id，取消/成功清 checkpoint，恢复轮最多 1000；`WithRequireResume()` 无 Redis 时拒绝生产 pipeline，测试可降级 runPlain |

这张表的关键裁决是：Python 的 Redis pending、Go 的 broker Ack/Nack、Pipeline checkpoint 都只是局部恢复机制，不能互相替代，也没有当前源码证据支持 exactly-once。最诚实的共同语义仍是 `at-least-once transport + idempotent index upsert/任务状态 CAS + 需要补偿的跨存储恢复`。

### 19.7 后续逐项真假验证表

| 事项 | 源码存在 | 测试源码 | 当前核对真实执行 | 当前等级/结论 |
|---|---|---|---|---|
| Python Redis Stream publish/consume/pending/ack | 是：`rag/utils/redis_conn.py`、`rag/svr/task_executor.py` | 是：`test/` 与相关 unit tests 可检索 | 未执行 Redis | L0；未证明断线、pending reclaim 或 ack 后一致性 |
| Python DeepDOC OCR/layout/TSR/分页 | 是：`deepdoc/parser/`、`deepdoc/vision/` | 是：`test/unit_test`、parser tests | 未执行 OCR/模型/真实 PDF | L0；不能宣称解析质量通过 |
| Python tokenizer/embedding/index/计数 | 是：`rag/flow/tokenizer/`、`task_executor_refactor/`、`api/db/services/` | 是：unit/dataflow/chunk tests | 未执行模型、对象存储、ES/Infinity、MySQL | L0；未证明批次失败后的跨存储恢复 |
| Go parser/DeepDOC/chunker/tokenizer | 是：`internal/parser/`、`internal/deepdoc/`、`internal/ingestion/component/` | 是：parser/deepdoc/ingestion tests，含 CGO/native 分层 | 未执行 `build.sh --test` 或 native test | L0；CGO、DLA、OCR/TSR 运行态仍待核 |
| Go NATS/Redis queue + task state | 是：`internal/engine/nats`、`internal/engine/redis`、`internal/ingestion/service` | 是：ingestion lifecycle/heartbeat/transition tests | 未启动 NATS/Redis/MySQL | L0；未证明 redelivery/max delivery/跨进程恢复 |
| Go checkpoint/RunTracker | 是：`internal/ingestion/pipeline/pipeline.go`、`internal/agent/canvas/checkpoint_store.go` | 是：checkpoint/recovery tests | 未执行 Redis-backed recovery | L0；TTL/重启恢复只由静态代码支持 |
| Go ES/Infinity index + document state | 是：`internal/engine/{elasticsearch,infinity}`、`internal/ingestion/task`、`internal/ingestion/service/doc_state.go` | 是：writer、engine、doc state tests | 未启动 document engine | L0；没有部分 bulk/删后插/统计失败的现场证据 |
| 外部对象存储 Storage | 是：`internal/storage/types.go` 与 provider 实现；Python `settings.STORAGE_IMPL` | 是：mock/provider tests 可检索 | 未连接 MinIO/S3 等 | L0；未证明对象与索引/DB 对账 |

### 19.8 后续裁决、剩余风险与后续复核点

- **吸收**：Go `ParseResult`/parser dispatch 的结构化输出契约；DeepDOC 页级质量门与显式 engine 释放；Python/Go tokenizer 的模型解析、批次、标题加权；ES 二次 KNN 分数、候选窗整除不变量；Python 母块/主块写入与 Go bulk writer；Go DB 状态 CAS、heartbeat、DB-truth settlement、Redis checkpoint/RunTracker。
- **升级候选**：跨 Python/Go 的统一 `DocumentIR/Chunk/Embedding/IndexWriteReceipt/TaskEvent`；任务 lease epoch/idempotency key；对象→索引→关系库的 manifest/outbox；索引 bulk 部分成功后的 batch receipt 与 reconciliation；恢复时的 stale object/image、orphan index、已写索引未计数和已计数未写索引扫描。
- **隔离/不吸收**：把 Python `CURRENT_TASKS`、Redis pending 或 `_prune_deleted_chunks` 当成 durable lease/事务；把 Go `currentTasks` 当跨进程 owner；把 DLA client 当远程 OCR/TSR；把 `docStateUpdater`/`progressSink` 的 best-effort 写入当成功提交。
- **待核**：真实部署中 Python 与 Go 是否由同一 proxy scheme/进程角色仲裁写入；Go `internal/parser` 与 Python DeepDOC 在同一 PDF/Office 样本上的结构等价性；ES/Infinity/OceanBase 的向量、分页、delete/upsert 语义差异；NATS/Redis 故障下的 redelivery 与任务状态 CAS；对象存储失败或进程 kill 后的残留回收；`TE_RUN_MODE=1` dry-run comparator 对所有 provider 写结果的覆盖。
- **后续状态**：本节完成源码逐项收口，但没有把未执行的外部服务、模型、native/CGO、队列、恢复和全链路测试标为通过。正式维护入口仍是根 `ARCHITECTURE.md`，旧细探仅保留为历史证据。
