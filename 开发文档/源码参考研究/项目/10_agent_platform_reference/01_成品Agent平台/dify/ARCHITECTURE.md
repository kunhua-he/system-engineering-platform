# Dify 架构档案

> 本文是基于本地源码的首轮全量架构建档，不是产品设计推测。
> 基线：`main`，提交 `a9b8c84e9be41376c04901e81ce690f35c1ffe86`（`refactor(dify-ui): simplify popover content API (#41069)`）。
> 版本核对：2026-08-22 本地 `HEAD` 与 `origin/main` 均为上述提交（`git rev-list --left-right --count HEAD...origin/main` 为 `0 0`）；未覆盖源码。
> 目标目录：`~/Documents/Agent/github 源码参考/10_agent_platform_reference/01_成品Agent平台/dify`
> 读取范围：根 README、根及主要子目录 `AGENTS.md`/`CLAUDE.md`、依赖清单、入口、控制器、服务、核心运行时、ORM 模型、迁移、SDK/CLI 和测试。
> 本文只维护这一份权威架构文档；源码树另有未跟踪的本地 `.codegraph/` 和源码侧 `ARCHITECTURE.md`，本轮不改、不纳入正式源码证据。
> 本轮继续只读源码与文档；未安装依赖、启动服务、构建、运行测试或提交 Git。

## 1. 项目定位

Dify 是一个开源 LLM 应用开发平台，主产品面向：

- Chat/Completion 应用；
- Agent 应用（Agent Chat、Agent App/Agent Roster）；
- 可视化 Workflow/Advanced Chat；
- RAG/知识库数据摄取、索引、检索；
- 模型、工具、插件、MCP、数据源与触发器管理；
- 运行记录、费用/Token、追踪与运营观测；
- 面向 Web、服务调用方、OpenAPI 客户端和 `difyctl` 的 API。

README 将它概括为“从原型到生产”的 LLM 应用开发平台；根 `AGENTS.md` 明确的代码分区是 `api`、`web`、`docker`、`dify-agent`。当前仓库实际上还是一个多包 monorepo，另含 `packages`、`sdks`、`cli`、`e2e`、`scripts` 和大量可选 provider。

## 2. 总体文本流程图

### 2.1 部署与进程拓扑

```text
浏览器 / 外部业务 / SDK / difyctl
              │
              ▼
        nginx (可选反向代理)
              │
       ┌──────┴─────────┐
       ▼                ▼
  web: Next.js       api: Flask + Socket.IO
                         │
       ┌─────────────────┼──────────────────┬─────────────────┐
       ▼                 ▼                  ▼                 ▼
 PostgreSQL/MySQL     Redis             文件存储          外部模型/provider
       │                 │                  │
       ├────────────┐    │                  └─ S3/OSS/Azure/GCS/OpenDAL 等
       ▼            ▼    ▼
  worker       worker_beat  API/队列/缓存
  (Celery)     (Celery Beat)
       │
       ├── 文档/RAG 索引、异步工作流、邮件、人机输入、追踪任务
       ├── plugin_daemon (独立插件宿主，HTTP)
       ├── sandbox (远程代码执行，HTTP)
       ├── ssrf_proxy (出站 HTTP 安全边界)
       └── agent_backend: dify-agent FastAPI 运行服务
                                │
                                ├── Redis 状态/事件流
                                ├── plugin_daemon
                                ├── Dify API inner API
                                └── local_sandbox / shellctl

可选中间件/向量服务：Weaviate、Qdrant、pgvector、Chroma、Milvus、OpenSearch、
Elasticsearch、OceanBase/SeekDB、Couchbase、Oracle、TiDB 等。
```

证据：`docker/docker-compose.yaml` 的 `api`、`api_websocket`、`worker`、`worker_beat`、`web`、`redis`、`db_postgres`、`sandbox`、`local_sandbox`、`plugin_daemon`、`agent_backend`、`ssrf_proxy`、`nginx` 及大量 profile 服务；其中 API 的 `AGENT_BACKEND_BASE_URL` 默认指向 `agent_backend:5050`。

### 2.2 统一请求进入 API 的路径

```text
HTTP / WebSocket / SSE 请求
          │
          ▼
Flask app_factory.create_app()
  ├─ DifyApp + dify_config
  ├─ before_request: request context、enterprise license gate
  ├─ initialize_extensions(): DB / Redis / storage / Celery / login /
  │  fastopenapi / OTEL / blueprints / session / OAuth bearer 等
  ├─ after_request: OTEL X-Trace-Id / X-Span-Id
  └─ Socket.IO WSGI wrapper
          │
          ▼
ext_blueprints.init_app()
  ├─ /console/api       Console 管理面
  ├─ /api               Web/App 公开面
  ├─ /v1                Service API
  ├─ /openapi/v1        用户级 OpenAPI
  ├─ /files             文件面
  ├─ /mcp               MCP 面
  ├─ /trigger           webhook / plugin trigger
  └─ inner_api          内部服务/插件调用
          │
          ▼
Controller/Resource
  ├─ Pydantic 请求 DTO / Flask-RESTX schema / fastopenapi contract
  ├─ login、tenant、RBAC、scope、CSRF、license 等门禁
  ├─ 调用 services（业务协调）
  └─ 翻译 domain/service exception 为 HTTP 响应或 SSE
          │
          ▼
Service → core/domain → repositories/SQLAlchemy/models/providers/tasks
```

### 2.3 Chat/Completion/Agent 请求数据流

```text
POST /api/chat-messages 或 /api/completion-messages
POST /v1/chat-messages 或 /v1/completion-messages
POST /openapi/v1/apps/{app_id}:run
          │
          ▼
AppGenerateService.generate(..., InvokeFrom.*)
          │
          ├─ App / ModelConfig / Tenant / EndUser / Conversation / Message
          ├─ ModelManager → graphon.model_runtime ModelInstance
          ├─ prompt、memory、文件访问、moderation、quota
          └─ AppQueueManager / 事件生成器
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
   Chat/Completion       Agent Chat
   LLM stream             BaseAgentRunner
                           ├─ FunctionCallAgentRunner
                           └─ CotAgentRunner (ReAct)
                                  │
                                  ▼
                         ToolManager → ToolEngine.agent_invoke
                                  │
                         tool runtime / ToolInvokeMeta
                                  │
                         plugin / built-in / workflow / MCP / API / dataset
                                  │
                                  ▼
                         observation 回喂模型 + MessageAgentThought
                                  │
                                  ▼
                         Queue events → SSE/HTTP response + trace queue
```

`ToolEngine.agent_invoke` 的真实契约是 `(plain_text, message_file_ids, ToolInvokeMeta)`；工具错误通常被转成 observation 文本返回 Agent 循环，而不是直接打断 Agent。工作流调用使用 `generic_invoke`，异常交给节点/引擎事件处理。

### 2.4 Workflow 执行路径

```text
Console draft sync / Service API run / OpenAPI :run / Web workflow run
          │
          ▼
Workflow ORM row
  ├─ graph: JSON 文本（nodes + edges + node data）
  ├─ features: JSON 文本
  ├─ environment/conversation/RAG variables
  └─ version: draft 或发布版本
          │
          ▼
WorkflowBasedAppRunner / WorkflowEntry
  ├─ build_dify_run_context(tenant/app/user/invoke_from/trace)
  ├─ VariablePool + system/environment/user inputs
  ├─ DifyNodeFactory → graphon Graph
  ├─ GraphEngine layers:
  │    DebugLoggingLayer(仅 DEBUG)
  │    → ExecutionLimitsLayer(步数/时间)
  │    → LLMQuotaLayer(tenant)
  │    → ObservabilityLayer(OTel 开启时)
  ├─ child engine for workflow-as-tool，带 call_depth 上限
  └─ ResponseStreamFilter 将 graphon 变量流恢复为 Dify 响应顺序
          │
          ▼
Graphon events
  GraphRun* / NodeRun* / Loop* / Iteration* / Retry / Pause / StreamChunk
          │
          ▼
WorkflowBasedAppRunner._handle_event
  → QueueWorkflow* / QueueNode* / QueueTextChunk / QueueRetrieverResources
          │
          ├─ 持久化 workflow_runs / workflow_node_executions / logs
          ├─ AppQueueManager → SSE/前端
          ├─ Human Input pause → form/repository/邮件任务 → resume
          └─ trace/OTel
```

工作流引擎主体不是本仓库实现：`api/pyproject.toml` 固定 `graphon==0.6.0`，本仓库的 `api/core/workflow/` 是 Dify 适配与运行时支撑层。

### 2.5 Agent Backend 独立运行路径

```text
api/core/workflow/nodes/agent_v2 或 Agent App
          │ HTTP + SSE
          ▼
agent_backend (dify-agent FastAPI)
  POST /runs             → RedisRunStore.create_run + asyncio.Task
  GET  /runs/{run_id}    → 状态
  POST /runs/{run_id}/cancel
  GET  /runs/{run_id}/events
  GET  /runs/{run_id}/events/sse (Last-Event-ID / after cursor)
          │
          ▼
CreateRunRequest
  composition.layers[] + per-layer config
  session_snapshot + deferred_tool_results + on_exit
          │
          ▼
normalize_composition
  → Agenton CompositorConfig + name-keyed configs
          │
          ▼
Compositor.enter()
  → fresh layer instances / dependency binding / snapshot hydration
          │
          ▼
AgentRunRunner
  ├─ model path: pydantic-ai + LLM layer + history/output/ask-human layers
  ├─ lifecycle-only path: snapshot enter/exit without model
  ├─ plugin/core/knowledge tools via Dify API or daemon clients
  └─ event sink: run_started → pydantic_ai_event* → run_succeeded/failed
          │
          ▼
Redis string run record + Redis Stream event log（同一 retention）
          │
          ▼
轮询 / SSE replay / Dify API 适配器 / Agent App UI
```

关键事实：Redis 在该服务中是状态和事件持久层，不是 job queue；调度器是进程内 `asyncio.Task` 注册表，进程崩溃时活动 run 不会被跨进程接管。

### 2.6 异步索引与追踪路径

```text
文件/URL/在线数据源
      │
      ▼
Console/Service API → Dataset / Document / Segment
      │
      ▼
Celery task（api/tasks）
  文档解析 → 清洗/分段 → embedding → vector backend → indexing status
      │
      ▼
PostgreSQL/MySQL metadata + vector store collection + object storage

应用/Agent/Workflow 运行事件
      │
      ├─ DB: messages / agent thoughts / workflow runs / node executions
      ├─ AppQueueManager: 面向调用方的流式事件
      └─ TraceQueueManager: 定时批量 → Celery process_trace_tasks → JSON storage → trace provider
```

## 3. 真实分层与边界

### 3.1 外层与部署层

| 层 | 真实目录/进程 | 责任 |
|---|---|---|
| 入口/部署 | `docker/`、`docker/docker-compose.yaml`、`api/Dockerfile`、`web/Dockerfile` | 镜像、环境、依赖服务、网络、卷、healthcheck、nginx |
| Web 边缘 | `web/` | Next.js/React 页面、SSR、浏览器状态、国际化、Console UI |
| API 边缘 | `api/app.py`、`api/app_factory.py` | Flask app、Socket.IO WSGI、扩展初始化、请求 hooks |
| Agent 边缘 | `dify-agent/src/dify_agent/server/` | FastAPI run server、SSE、sandbox file/API stub 路由 |
| CLI 边缘 | `cli/bin/dev.js`、`cli/src/framework/` | `difyctl` 参数解析、命令树、输出、错误退出码 |
| SDK 边缘 | `sdks/nodejs-client/`、`sdks/php-client/` | 外部程序调用 Dify API |

### 3.2 API 内部层

```text
controllers/                 # HTTP/REST/OpenAPI/namespace、DTO、认证/错误转换
        ↓
services/                    # 用例编排、事务/仓储/任务/provider 协调
        ↓
core/                        # Agent、Workflow、RAG、Tool、模型、插件、MCP、观测等领域运行时
        ↓
models/ + repositories/      # SQLAlchemy ORM、查询/持久化边界
        ↓
extensions/ + libs/ + providers/ + tasks/
                              # DB/Redis/storage/Celery、通用安全、向量/trace provider、异步执行
```

这是仓库指导中“controller → service → core/domain”的实际主线；并非所有旧模块严格服从该顺序，部分 controller 仍直接依赖模型或 core，属于需要继续细探的边界事实。

**Controllers** 由 Blueprint + Flask-RESTX `Namespace` 和少量 raw Flask route 组成。`extensions/ext_blueprints.py` 注册八类主要 Blueprint。Controller 负责 DTO 校验、认证、租户/RBAC、调用 Service 和 HTTP/SSE 序列化；`api/controllers/API_SCHEMA_GUIDE.md` 规定 Pydantic DTO、`query_params_from_model`、`dump_response` 和 response schema 注册方式。

**Services** 是较大的业务协调面，包含 app/conversation/message/workflow/dataset/document/provider/plugin/auth/workspace/billing/human-input/agent 等用例；长期运行/重任务下沉到 `api/tasks/` 的 Celery task。

**Core** 是运行时核心，重点包括：

- `core/app/apps/`：Chat/Completion/Agent/Workflow 应用生成、队列、运行上下文；
- `core/agent/`：CoT 与 Function Calling 两套 Agent runner、prompt/history、策略；
- `core/tools/`：Tool 实体、参数 schema、ToolManager、ToolEngine、workflow-as-tool、MCP、dataset retriever；
- `core/workflow/`：Graphon 适配、Dify node factory/runtime、变量池、入口、暂停/恢复；
- `core/rag/`、`core/datasource/`、`core/indexing_runner.py`：知识库 ingestion/retrieval；
- `core/plugin/`：plugin daemon HTTP client、声明、安装、模型/工具/Agent 代理；
- `core/mcp/`：MCP client/server/session/auth；
- `core/ops/`、`extensions/otel/`：trace queue、OTel、父子 trace 上下文；
- `core/helper/`：加密、凭证、SSRF、远程文件、代码沙箱客户端、缓存。

### 3.3 外部运行时边界

| 边界 | 本仓库职责 | 本仓库外职责 |
|---|---|---|
| `graphon==0.6.0` | Graph 初始化上下文、Dify node factory/runtime、入口 layers、事件适配 | `Graph`、`GraphEngine`、`VariablePool`、多数节点与模型运行时实现 |
| `dify-agent` | API 通过 editable path 依赖引用；Workflow Agent v2 通过 HTTP/SSE client 调用 | Agenton compositor/layers、FastAPI run server、pydantic-ai 运行、Redis run store |
| plugin daemon | `core/plugin/impl/*` HTTP client、声明/权限/凭证适配 | 插件安装、插件代码执行、插件环境与生命周期 |
| sandbox | `CodeExecutor`/代码节点 client、SSRF/凭证传递 | 用户 Python/JS 代码真实执行 |
| vector/trace providers | provider workspace 包与统一接口 | 各厂商协议、向量索引、外部 trace 平台 |

## 4. 核心数据模型与持久化

### 4.1 ORM 基础

`api/models/base.py` 提供 `Base` 和 `TypeBase` 两套 SQLAlchemy Declarative Base，metadata 来自 `models.engine`；`DefaultFieldsMixin`/`DefaultFieldsDCMixin` 提供 UUID、created_at、updated_at。新旧模型并存，`TypeBase` 使用 `MappedAsDataclass`，并非单一统一模型基类。

`api/migrations/versions/` 当前静态可见约 203 个 Python migration 文件，覆盖 2024–2026 的业务演进；数据库迁移由 Flask-Migrate/Alembic 入口负责。本次没有连接数据库或执行迁移。

### 4.2 身份与租户

- `accounts`：账号、登录状态、密码/个人设置；
- `tenants`：工作区；
- `tenant_account_joins`：账号—工作区成员关系和 `owner/admin/editor/normal/dataset_operator` 角色；
- `account_integrates`、`invitation_codes`、插件安装/调试权限策略。

绝大多数共享资源以 `tenant_id` 贯穿 controller → service → core → query；API 指导明确要求查询和写入都带完整租户约束。

### 4.3 应用、会话、消息与审计

`api/models/model.py` 集中承载历史模型：

- `apps`、`app_model_configs`、`sites`、`api_tokens`：应用/发布面/配置/API token；
- `conversations`、`messages`、`message_feedbacks`、`message_files`、`message_annotations`：终端用户会话与消息；
- `message_agent_thoughts`：Agent 每轮 thought、tool、tool_input、observation、tool meta、token、价格、位置；
- `api_requests`、`operation_logs`、`message_chains`、`dataset_retriever_resources`、`trace_app_config`：请求、操作、检索与观测辅助记录。

Agent history 会从 `Message` 和 `MessageAgentThought` 重建成 assistant tool-call + tool observation 消息；Function Calling/CoT 共享消息审计模型，但运行策略不同。

### 4.4 Workflow 与运行记录

`api/models/workflow.py` 的主要表：

- `workflows`：租户/app/version 作用域的 graph、features、环境变量、会话变量、RAG pipeline 变量；`version=draft` 表示草稿，发布版用版本字符串；
- `workflow_runs`：触发来源、版本、输入输出、status、error、elapsed time、token、step、创建者角色；
- `workflow_node_executions`：节点序号、前驱、node id/type、inputs/process_data/outputs/status/error、metadata、时间；
- `workflow_node_execution_offload`：大输入输出/过程数据转 object storage 的 offload 指针；
- `workflow_app_logs`、`workflow_archive_logs`、`workflow_run_archive_bundles`：日志与归档；
- `workflow_conversation_variables`、`workflow_draft_variables`、`workflow_draft_variable_files`、`workflow_pauses`、`workflow_pause_reasons`：变量和暂停/人机输入。

Workflow graph 是持久化 JSON，不是本仓库内的强关系节点表；Graphon 在运行时将它变成 Graph/Node/VariablePool。

### 4.5 RAG/知识库

`api/models/dataset.py` 代表性表：

- `datasets`、`dataset_process_rules`；
- `documents`、`document_segments`、`child_chunks`、`segment_attachment_bindings`、`document_segment_summaries`；
- `embeddings`、`dataset_collection_bindings`、`dataset_queries`、`dataset_keyword_tables`；
- `app_dataset_joins`、`dataset_permissions`、`dataset_metadatas`、`dataset_metadata_bindings`；
- external knowledge、pipeline template/customized pipeline、indexing execution log、rate-limit/auto-disable log。

元数据和文档状态在关系库，向量内容由可选 vector backend provider 负责。Dataset retriever 在 Agent 中被包装为标准工具，并通过 callback 发检索追踪事件。

### 4.6 Agent 领域模型

`api/models/agent.py` 是较新的独立域：

- `agents`：workspace-scoped Agent identity，区分 `roster` 与 `workflow_only`、`active/archived`；
- `agent_debug_conversations`：按 workspace/agent/account/draft type 隔离 Console debug 会话；
- `agent_config_drafts`：可编辑 Soul 草稿；
- `agent_config_snapshots`：按 Agent/version 唯一的不可变配置快照；
- `agent_config_revisions`：保存操作的审计边；
- `workflow_agent_node_bindings`：workflow version + node 到 Agent/snapshot 的绑定；
- `agent_runtime_sessions`：统一 workflow-run/conversation owner 的 Agent backend session snapshot；
- `agent_drive_files`：path-like key 到既有 UploadFile/ToolFile 的指针，不保存字节。

该模型层将 Agent Soul、workflow node job config、运行时 session 和文件 drive 分离，避免在 workflow binding 中复制完整 Soul 配置。

### 4.7 Provider、Tool、Plugin、MCP

- `providers.py`：model/provider/order/credential/load-balancing 相关表；
- `tools.py`：builtin/API/workflow/MCP tool provider、OAuth client、label binding、tool invoke、tool files；
- `core/tools/tool_manager.py` 的 provider 路由：`BUILT_IN`、`PLUGIN`、`WORKFLOW`、`API`、`MCP`、名义存在但未实现的 `APP`，以及 Agent 直接构造的 `DATASET_RETRIEVAL`；
- 内置工具由 provider 目录扫描 + YAML 声明加载；插件通过 daemon HTTP 获取声明和执行；workflow app 可包装成 tool；MCP 通过 MCP server 调用；API provider 根据 OpenAPI/Swagger 声明工具；
- 凭证在 DB 加密存储，运行时按调用域解密，API 返回默认掩码；MCP 的 URL、headers、credentials 也以加密字段/JSON 形式保存。

## 5. API、事件与外部契约

### 5.1 API surface

| 前缀/面 | 真实入口 | 主要用途 |
|---|---|---|
| `/console/api` | `api/controllers/console/` | 登录后 Console：应用/工作流编辑、发布、Agent、知识库、模型/provider、插件、workspace、RBAC、统计/运行记录 |
| `/api` | `api/controllers/web/` | Web App：login、parameters/meta/site、chat/completion、conversation、message、file、audio、human input、workflow |
| `/v1` | `api/controllers/service_api/` | 服务/API token 面：app、chat/completion、workflow、conversation、message、dataset/document/segment、end-user、models |
| `/openapi/v1` | `api/controllers/openapi/` | 用户级 bearer OpenAPI：`apps`、`:run`、DSL import/export、workspace、account/session、files、human input、workflow events、device OAuth |
| `/files` | `api/controllers/files/` | 上传、预览、tool/agent drive 文件相关面 |
| `/mcp` | `api/controllers/mcp/` + `api/core/mcp/` | MCP server endpoint |
| `/trigger` | `api/controllers/trigger/` | webhook 与 plugin trigger |
| inner API | `api/controllers/inner_api/` | plugin daemon / Agent backend 反向调用 Dify 能力 |

源码静态扫描到约 798 个 route decorator 命中；该数字包含多个 Blueprint 面、同一路径的多方法、重复兼容路径及多行 decorator，不能当作去重后的 API endpoint 数量。

### 5.2 代表 API

**Web/App：**

- `POST /api/chat-messages`、`POST /api/completion-messages`；
- `POST /api/workflows/run`，以及对应 task stop；
- `GET /api/messages`、`POST /api/messages/{message_id}/feedbacks`；
- `GET/POST /api/conversations`、rename/pin/delete；
- `POST /api/files/upload`、`GET /api/files/{id}/preview`；
- `POST /api/audio-to-text`、`POST /api/text-to-audio`。

**Service API：** 同类 `/v1` 资源面，加 dataset/document/segment/metadata/hit-testing 和 workflow log/events。

**OpenAPI：**

- `POST /openapi/v1/apps/{app_id}:run`：根据 AppMode dispatch 到 chat/completion/workflow，返回 SSE；
- `POST /openapi/v1/apps/{app_id}/tasks/{task_id}:stop`；
- `GET /openapi/v1/apps/{app_id}`、`GET /openapi/v1/apps`、DSL、files、workspaces/members、account/sessions；
- `GET/POST /openapi/v1/apps/{app_id}/human-input-forms/{form_token}`；
- `GET /openapi/v1/apps/{app_id}/tasks/{task_id}/events`。

OpenAPI controller 使用 Pydantic request/response DTO、`auth_router.guard` 的 scope/RBAC 门禁，并在 `api/openapi`/`packages/contracts` 侧进入生成契约。

**Agent backend：**

- `POST /runs` → `202 {run_id,status}`；
- `GET /runs/{run_id}`；
- `POST /runs/{run_id}/cancel`；
- `GET /runs/{run_id}/events?after=&limit=`；
- `GET /runs/{run_id}/events/sse?after=`，支持 `Last-Event-ID`。

事件 union 为 `run_started`、`pydantic_ai_event`、`run_succeeded`、`run_failed`、`run_cancelled`。成功事件携带 session snapshot，且在 `output` 与 `deferred_tool_call` 之间二选一。

### 5.3 前端契约与请求层

`packages/contracts`：

- `generated/api`：由 API Swagger/fastopenapi 生成的 OpenAPI TypeScript/orpc contract；
- `generated/enterprise`、`generated/knowledge-fs`：对应 enterprise/knowledge-fs contract；
- `console.ts` 合并 generated Console router 与 knowledge-fs router；
- `gen-api-contract` 先调用 `api/dev/generate_swagger_specs.py`、`generate_fastopenapi_specs.py`，再执行 openapi-ts；
- `web/service/client.ts` 用 `@orpc/openapi-client` + `@tanstack/react-query` 暴露 `consoleClient`/`consoleQuery`，不是新代码的手写 REST helper。

前端根 `web/app/layout.tsx` 是 SSR/RSC 入口：服务端预取 system features，dehydrate TanStack Query，再以 Jotai、Theme、Nuqs、TanStack Query、i18n、UI providers 包住页面树。

## 6. CLI 与 SDK

### 6.1 `difyctl`

`cli/` 是 TypeScript/ESM CLI，Node `^22.22.1`，Bun 用于开发/发布脚本，`ky`/自有 HTTP 层、Zod contract、Vitest、Vite+。

入口与分层：

```text
cli/bin/dev.js
  → 解析 build info
  → import cli/src/commands/tree.ts
  → cli/src/framework/run.ts
  → resolveCommand(commandTree, argv)
  → DifyCommand leaf
  → domain modules (run/get/etc.)
  → api resource client
  → http/client + middleware
  → printers / structured output / exit code
```

`cli/src/commands/tree.generated.ts` 当前登记的命令族包括：

- `auth devices/list|revoke`、`auth list|login|logout|whoami`；
- `config get|path|set|unset|view`；
- `create/delete/get/set member`、`get app/workspace`、`describe app`；
- `env list`、`export/import studio-app`；
- `run app`、`resume app`、`skills install`、`use account|host|workspace`；
- `version`。

CLI 的真实边界由 `cli/AGENTS.md` 给出：commands 仅做 framework shell；domain 不可导入 framework；`src/api` 是资源 client；`src/http` 是 ky/middleware 唯一运行时边界；`types` 是纯数据/zod leaf；`io` 隔离 stdout/stderr/progress；printers 支持 text/name/wide/json/yaml 等输出。命令还有 `read/write/destructive` effect 元数据和错误/exit-code 映射。

### 6.2 Node.js SDK

`sdks/nodejs-client`：版本 `3.1.0`，Node `>=18`，发布 `dist/index.js`/`.d.ts`。核心是 `DifyClient` + `HttpClient`，支持：

- parameters/meta/info/site；
- chat/completion message 与 stop；
- conversation/message/feedback；
- file upload/preview；
- audio-to-text/text-to-audio；
- workflow run/stop；
- knowledge-base/workspace 扩展 client；
- JSON、bytes、binary stream、SSE、retry、错误映射与输入校验。

### 6.3 PHP SDK

`sdks/php-client/dify-client.php` 是轻量 PHP 客户端，README 声明 PHP 7.2+、Guzzle；示例覆盖 `CompletionClient`、`ChatClient`、file upload、parameters、feedback、conversation。该目录有 `composer.json`/`composer.lock`，不是 pnpm workspace 包。

## 7. 技术栈与依赖

| 领域 | 实际技术/版本证据 |
|---|---|
| API | Python 3.12；Flask 3.1；Flask-RESTX；fastopenapi；Flask-CORS；Gunicorn/gevent/WebSocket；Pydantic v2；SQLAlchemy；Flask-Migrate |
| API async | Celery 5.6 + Redis 7；worker/beat；Socket.IO；SSE |
| Workflow | `graphon==0.6.0` 外部包；Graph/GraphEngine/VariablePool/event/layers 适配 |
| Agent backend | Python 3.12；FastAPI 0.136（server extra）；uvicorn；Agenton compositor/layers；pydantic-ai；Redis asyncio；httpx；可选 gRPC |
| Web | Next.js 16.2、React 19.2、TypeScript；可选 vinext；RSC/SSR；MDX；Tailwind CSS 4；React Flow；Lexical；ECharts |
| Web state/data | TanStack Query 5、Jotai、Zustand、nuqs；`@orpc/*`；Zod |
| Contracts | OpenAPI/Swagger + fastopenapi + `@hey-api/openapi-ts` 生成 TS；orpc router |
| CLI | TypeScript/ESM、Node 22、Bun 脚本、ky、Zod、Vitest、Vite+；5 个发布目标（Linux/Darwin x64/arm64、Windows x64） |
| DB | PostgreSQL 15 默认 compose profile；MySQL 8 可选；SQLAlchemy ORM/Alembic migrations |
| Cache/stream | Redis 6 compose image；API queue/cache；Agent backend Redis strings + Streams |
| Vector/RAG | Weaviate 默认 profile 以及 Qdrant/pgvector/Chroma/Milvus/OpenSearch/ES 等 workspace providers |
| Storage | Dify storage abstraction、OpenDAL、S3/OSS/Azure Blob/GCS/COS/TOS/OBS 等可选 provider |
| Security | 加密凭证、CSRF、RBAC/tenant、SSRF proxy、远程 sandbox、plugin daemon 进程隔离、license gate |
| Observability | OpenTelemetry、B3、Sentry、Logfire（Agent backend）、trace providers：Langfuse/Opik/Arize Phoenix/MLflow/Weave 等 |
| E2E | Cucumber 13 + Playwright；backend source + production frontend artifact + Docker middleware |

`api/pyproject.toml` 的 `dify-agent` 是 `../dify-agent` editable path 依赖；同时把大量 `providers/vdb/*` 和 `providers/trace/*` 作为 uv workspace members。根 `pnpm-workspace.yaml` 管理 `web`、`e2e`、`sdks/nodejs-client`、`packages/*`、`cli`，统一 lockfile 为 `pnpm-lock.yaml`。

## 8. 安全、资源与可靠性边界

- **租户/RBAC**：controller 认证与 workspace/app/dataset scope 门禁；`tenant_id` 应端到端流动；
- **凭证**：DB 加密、输出掩码、按 Agent/Workflow 调用域加密运行时参数；OAuth 过期 refresh；
- **插件**：主进程只持有 HTTP client，不导入插件代码；daemon 负责安装/执行/权限声明；
- **代码执行**：代码节点调用远程 sandbox，不在 API 进程执行用户代码；Agent shell 通过 local sandbox/shellctl；
- **SSRF**：远程 fetch 和工具出站 HTTP 经过 SSRF proxy/校验；
- **文件**：`DatabaseFileAccessController` 和签名 URL/tenant 作用域；大 workflow node 内容可 offload 到 storage；
- **Agent 限制**：默认最大迭代 10，运行时硬顶 100；工具错误转 observation；
- **Workflow 限制**：ExecutionLimitsLayer 的步数/时间上限；子 workflow `WORKFLOW_CALL_MAX_DEPTH`；
- **Agent backend**：每次 run 的 session snapshot 显式传递；SSE 事件有 cursor 和 heartbeat；run record/stream 有 retention；调度器 shutdown 会等待并标记未完成 run；
- **观测**：Agent thought、workflow node execution、trace task 和 OTEL span 多路记录，但外部 trace provider 是可选边界。

## 9. 测试与质量门

### 9.1 已存在的测试面

本次静态计数（包含 fixture、配置和非测试辅助文件，不能等同于测试用例数）：

| 区域 | 文件规模/形态 |
|---|---|
| `api/tests` | 约 1,467 文件；`unit_tests` 约 1,161，`integration_tests` 约 69，另有 `test_containers_integration_tests`；workflow、service、model、repository、task、trigger 覆盖广 |
| `web` | 约 7,690 文件；约 2,056 个名称含 spec/test 的文件；Vitest + React Testing Library，默认 happy-dom； |
| `packages/contracts` | contract/schema/OpenAPI smoke tests，生成契约和非 JSON response 约束 |
| `dify-agent/tests` | 约 88 文件；local import boundary、packaging、client、shellctl、examples/docs 测试；server runtime 还依赖 server extras |
| `cli/src`/`cli/test` | 约 269/54 文件；framework、HTTP、API resource、commands、printer、config、auth、version 等单测/行为测试 |
| `sdks/nodejs-client` | source unit tests + HTTP integration test，覆盖 client、SSE、retry、validation、errors |
| `e2e` | Cucumber feature 约 93 文件，Playwright glue/support；另有 Vitest unit tests |

### 9.2 官方命令（仅记录，未执行）

- API：`uv run pytest`、`uv run pytest tests/unit_tests/`、`uv run pytest tests/integration_tests/`、`uv run pyrefly check`、`make lint/type-check/test`；
- Web：`vp test run`、`pnpm -C web type-check`、根 `pnpm check`；
- Agent：`make test`、`make typecheck`；
- CLI：`pnpm test`、`pnpm test:e2e`、`pnpm tree:check`、`pnpm type-check`；
- Contracts：`pnpm test`、`pnpm type-check`、生成 contract 命令；
- E2E：`pnpm -C e2e test:unit`、`pnpm -C e2e e2e`、`pnpm -C e2e e2e:full`、`pnpm -C e2e type-check`。

### 9.3 测试隔离事实

- API unit fixture 使用 MagicMock Redis、SQLite in-memory engine 和 `/tmp/dify-storage` OpenDAL root；集成/容器测试涉及真实 PostgreSQL/Redis/vector/container，根 `AGENTS.md` 说 integration tests 主要在 CI；
- Web policy 要求按可观察行为和最小边界测试，不以覆盖率为目标；默认不做真实网络请求；
- E2E 使用 Cucumber + Playwright：backend 从源码、frontend production artifact、middleware Docker；每个 scenario 使用独立 BrowserContext，失败产出 screenshot/HTML/console artifacts；
- Agent local tests 明确验证 import boundary，例如导入 client/protocol 时不能提前加载 FastAPI、Redis、server-only adapter；
- CLI 行为测试使用真实 Hono mock，而非 nock/msw/fetchMock（以 `cli/AGENTS.md` 为准）。

本次没有执行任何测试，因此没有“通过”结论，也没有运行时覆盖率或实际 API 响应证据。

## 10. 关键路径索引

| 场景 | 从哪里开始读 | 下一跳 |
|---|---|---|
| API 启动 | `api/app.py` | `app_factory.create_app` → `initialize_extensions` → `ext_blueprints` |
| API migration | `api/app.py` 的 `is_db_command` | `create_migrations_app` → `ext_database`/`ext_migrate`/`ext_commands` |
| Flask route 注册 | `api/extensions/ext_blueprints.py` | 各 Blueprint `__init__.py` → Namespace controller imports |
| Chat/Completion | `api/controllers/web/completion.py`、`service_api/app/completion.py`、`openapi/app_run.py` | `services/app_generate_service.py` → `core/app/apps/*` |
| Agent | `api/core/agent/base_agent_runner.py`、`fc_agent_runner.py`、`cot_agent_runner.py` | `ToolManager` → `ToolEngine` → model/queue/message thought |
| Tool | `api/core/tools/tool_manager.py`、`tool_engine.py` | builtin/plugin/workflow/API/MCP/dataset providers |
| Workflow | `api/core/workflow/workflow_entry.py`、`api/core/app/apps/workflow_app_runner.py` | graphon Graph/GraphEngine + event → Queue events |
| Agent v2 | `api/core/workflow/nodes/agent_v2/`、`api/clients/agent_backend/` | HTTP/SSE → `dify-agent/src/dify_agent/server/routes/runs.py` |
| Agent backend | `dify-agent/src/dify_agent/server/app.py` | lifespan Redis/http clients → scheduler → runner |
| Agent runtime | `dify-agent/src/dify_agent/runtime/runner.py` | Agenton compositor → pydantic-ai → event sink |
| RAG | `api/core/rag/`、`api/core/indexing_runner.py`、`api/tasks/*document*` | embedding/vector provider + storage |
| Console frontend | `web/app/layout.tsx`、`web/app/(commonLayout)/`、`web/service/client.ts` | generated contracts → ORPC/TanStack Query → `/console/api` |
| API contract | `api/dev/generate_swagger_specs.py`、`packages/contracts/package.json` | OpenAPI/fastopenapi → `packages/contracts/generated` |
| CLI | `cli/bin/dev.js`、`cli/src/framework/run.ts`、`cli/src/commands/tree.generated.ts` | command → domain → api/http → printers |
| Node SDK | `sdks/nodejs-client/src/index.ts`、`src/client/base.ts` | HttpClient → public `/v1` app API |
| E2E | `e2e/scripts/run-cucumber.ts`、`e2e/scripts/setup.ts`、`e2e/features/support/hooks.ts` | browser + API setup + Docker middleware |

## 11. 目录地图

```text
dify/
├── api/                         Flask backend
│   ├── controllers/             HTTP surfaces and schemas
│   ├── services/                application/domain coordination
│   ├── core/                    runtime engines and domain logic
│   ├── models/                  SQLAlchemy ORM/domain persistence models
│   ├── repositories/             selected repository abstractions
│   ├── tasks/                   Celery async tasks
│   ├── providers/               vector/trace workspace providers
│   ├── extensions/              DB/Redis/storage/Celery/OTel/etc.
│   ├── migrations/              Alembic/Flask-Migrate history
│   ├── openapi/                 generated/source API specs
│   └── tests/                   unit/integration/container tests
├── dify-agent/                  Agenton + standalone Agent backend package
│   ├── src/agenton/             stateless compositor/layer graph
│   ├── src/dify_agent/          protocol, runtime, FastAPI server, Redis store
│   ├── src/shellctl/            sandbox shell client/protocol
│   └── tests/                   local/import/examples tests
├── web/                         Next.js/React/Vinext frontend
├── packages/
│   ├── contracts/               generated OpenAPI/orpc/Zod contracts
│   ├── dify-ui/                 shared UI primitives
│   ├── iconify-collections/     custom icon source/generator
│   └── ...                      workspace packages
├── cli/                         TypeScript difyctl
├── sdks/                        Node.js and PHP clients
├── e2e/                         Cucumber + Playwright + Docker lifecycle
├── docker/                      compose, env themes, middleware, volumes
├── scripts/                     repo maintenance/codegen/support
├── docs/                        product/development docs
├── README.md                    product/self-hosting overview
└── AGENTS.md / CLAUDE.md        repository working rules
```

## 12. 未确认项与边界声明

1. **Graphon 内部实现未在本仓库展开。** 只确认 `api/pyproject.toml` 锁 `graphon==0.6.0`、Dify 适配调用点和导入类型；Graph/GraphEngine/大部分节点算法需单独读取安装包或其上游仓库。
2. **Plugin daemon 不在目标仓库源码中。** 已确认主进程 client 协议、compose 服务和配置，不代表插件 daemon 的真实实现/版本行为已核验。
3. **运行时未验证。** 没有安装依赖、导入应用、启动 Docker、执行迁移、调用 API、跑单测/E2E；文中“路径”是源码静态路径，不是本机运行成功证明。
4. **数据库实际 schema 未连接核对。** ORM 与 migration 文件已读/计数，但没有对 PostgreSQL/MySQL catalog 做 drift 检查，也未证明所有约束/索引在运行库存在。
5. **API 总数未去重。** 约 798 为 decorator 命中数，含兼容路径、多方法、多 Blueprint 和多行装饰器；权威 wire contract 应以生成的 OpenAPI/fastopenapi 文件为准。
6. **Enterprise 代码边界不完整。** `api/enterprise`、`web` enterprise contract 和 license gate 可见，但企业服务/部署端的完整独立实现不在当前核对目标范围内。
7. **dify-agent 的文档/可选 extras 有分层。** 默认 package 依赖和 `server`/`grpc` optional dependencies 不同；`dify-agent` 根 import 被设计为 client-safe，不能用根包 import 证明 server runtime 可启动。
8. **当前源码树未见独立 Rust 入口。** 已有细探文件将语言概括为“Python(api) + TypeScript(web) + Rust/Python(dify-agent)”，但当前核对对 `dify-agent/src` 的实际扫描为 Python 包（约 127 个 `.py`）；Rust 相关来源/构建链未确认。
9. **已有工作树变化。** 2026-08-22 现场 `git status --short` 为源码侧未跟踪 `.codegraph/` 与 `ARCHITECTURE.md`；两者均不属于 Git 版本源，本轮不修改、不删除。目标树及研究库父目录未发现可回读的 `细探-dify.md`，因此旧细探的历史性表述不作为当前证据。
10. **迁移/CLI/契约生成属于有副作用操作。** 当前核对只记录入口和命令，没有执行 `uv sync`、`pnpm install`、`generate`、`tree:gen`、migration、build 或任何服务命令。

## 13. 主要证据索引

- 产品定位/自托管：`README.md`；
- 总体分区/规则：`AGENTS.md`、`CLAUDE.md`；
- API 分层/后端边界：`api/AGENTS.md`；
- Agent runtime 边界：`dify-agent/AGENTS.md`、`dify-agent/README.md`；
- 前端契约/状态/测试：`web/AGENTS.md`、`web/docs/test.md`；
- CLI 分层/命令：`cli/AGENTS.md`、`cli/src/commands/AGENTS.md`、`cli/ARD.md`；
- E2E 生命周期：`e2e/AGENTS.md`；
- API 依赖：`api/pyproject.toml`；
- JS workspace/依赖：`package.json`、`pnpm-workspace.yaml`、`pnpm-lock.yaml`、各包 `package.json`；
- API 入口：`api/app.py`、`api/app_factory.py`、`api/extensions/ext_blueprints.py`；
- 运行核心：`api/core/app/apps/workflow_app_runner.py`、`api/core/workflow/workflow_entry.py`、`api/core/tools/tool_engine.py`、`api/core/agent/base_agent_runner.py`；
- Agent backend：`dify-agent/src/dify_agent/server/app.py`、`server/routes/runs.py`、`protocol/schemas.py`、`runtime/runner.py`、`runtime/run_scheduler.py`、`storage/redis_run_store.py`、`src/agenton/compositor/core.py`；
- ORM：`api/models/base.py`、`account.py`、`model.py`、`workflow.py`、`dataset.py`、`agent.py`、`tools.py`；
- `api/controllers/openapi/__init__.py`、`api/controllers/openapi/app_run.py`、`packages/contracts/package.json`、`packages/contracts/console.ts`、`web/service/client.ts`；
- CLI/SDK：`cli/bin/dev.js`、`cli/src/framework/run.ts`、`cli/src/commands/tree.generated.ts`、`sdks/nodejs-client/src/index.ts`、`sdks/nodejs-client/src/client/base.ts`、`sdks/php-client/README.md`；
- 既有文档声称本文曾吸收 `细探-dify.md`；当前核对现场未找到该独立文件，因此只能把现有正文作为历史线索，并以当前源码、当前测试和当前核对新增证据为准；后续只维护本文件。

## 14. 后续：通用底座映射（源码事实与裁决分开）

### 14.1 当前核对边界、误绑定记录与证据等级

当前核对的目标是把 Dify 的真实实现映射到“支持库—模块库—运行核心—统一网关”四个底座边界，不是把 Dify 的目录名直接改名，也不是声称 Dify 已经实现了目标平台的通用底座。

早期核对曾把 `project_context` 错绑到 `~/Documents/Agent/PHP/华世王镞_v3`，返回的代码图、提交和工作区指纹属于另一项目；该返回值已废弃，不使用它作 Dify 证据，也没有切换或修改那个项目。本轮已重新以系统工程平台根目录建立独立开工上下文（`work_id=86e3a3ec08354a91`），并在 Dify 根目录使用其自身 CodeGraph shell 取证。因此，下面的 Dify 结论是**目标目录源码/测试证据**；没有运行依赖、服务、数据库或插件 daemon，运行态部分一律标为未验证。

证据分级：

| 等级 | 当前核对含义 | 可支持的结论 |
|---|---|---|
| S0 | 目标源码存在，且能读到实现分支/数据结构 | “源码实现了某路径/契约的一部分” |
| S1 | 目标测试源码覆盖该边界，但当前核对未执行 | “有测试意图/静态回归面”，不能写“通过” |
| S2 | 当前核对实际执行的静态检查（文件回读、Markdown 结构、`git diff --check`） | “当前核对文档和工作树结构通过” |
| S3 | 真实依赖、数据库、Redis、Celery、插件 daemon 或端到端执行 | 当前核对未取得，不得宣称运行成功 |

当前核对读过的旧正式文档为本文件第 1–13 节；目标目录和研究库父目录未找到可回读的旧 `细探-*.md`。读过的代表性测试包括：`api/tests/unit_tests/core/workflow/test_node_mapping_bootstrap.py`、`api/tests/unit_tests/core/app/apps/test_workflow_app_runner_core.py`、`api/tests/unit_tests/tasks/test_async_workflow_tasks.py`、`api/tests/unit_tests/services/test_async_workflow_service.py`、`dify-agent/tests/local/dify_agent/runtime/test_run_scheduler.py` 和 `dify-agent/tests/local/dify_agent/storage/test_redis_run_store.py`。这些是测试源码证据，不是当前核对执行结果。

### 14.2 四层底座的判定规则

| 底座层 | 在通用平台中的唯一职责 | Dify 中的主要落点 | 后续裁决 |
|---|---|---|---|
| **支持库** | 稳定的协议、连接、序列化、加密、存储、锁、HTTP、数据库会话、通用观测；不拥有业务流程 | `api/extensions/`、`api/libs/`、`api/core/helper/`、`core/db/session_factory.py`、`extensions.ext_storage`、`BasePluginClient`、`dify-agent` storage/protocol 边界 | 吸收为可复用原子能力；禁止把 provider 选择和业务状态塞进支持库 |
| **模块库** | 一个领域流程的公开编排；组合支持库和运行核心，拥有领域契约，不复制 provider 内核 | `api/services/`、`core/tools/`、`core/rag/`、`core/trigger/`、`core/app/task_pipeline/`、provider/plugin controller | 吸收其流程编排和契约；将 Dify 特有 DTO/数据库模型留作适配，不照搬旁路入口 |
| **运行核心** | 执行一个已解析的组件/节点/任务，发出统一事件，维护运行上下文与终态 | `core/app/apps/*`、`core/agent/`、`core/workflow/`、`ToolEngine`、`DifyNodeFactory`、`graphon` 以及 `dify-agent/runtime/` | 吸收执行单元、事件适配、取消/暂停语义；外部 `graphon`/Agenton 只能通过明确 adapter 进入 |
| **统一网关** | 认证、租户/RBAC、版本、命令/查询、SSE/WebSocket/HTTP、错误和契约出口；不执行领域逻辑 | `api/controllers/`、`inner_api`、`/openapi`、`/trigger`、`dify-agent/server/routes/`、`packages/contracts`、`web/service/client.ts` | 吸收单一入口和生成契约；前端、插件、Agent backend 不得绕过网关直接写数据库 |

判定铁律：一个原子能力只能有一个规范能力 id、一个契约 owner、一个注册表/调用路径和一个状态写 owner。provider、插件、节点版本和队列只是策略或适配，不得生成第二套业务流程。当前 Dify 仍有历史 `/api`、`/v1`、`/openapi/v1`、`/console/api`、inner API 和 Agent backend 多面出口；这说明“统一网关”是映射目标，不能把当前多面事实误写成已经完全收敛。

### 14.3 领域映射表：插件/工具/节点/工作流、模型、队列、事件、数据库、文件、前后端

| 能力域 | 支持库（L0） | 模块库（L1/L2） | 运行核心（L2/L3） | 统一网关（L3） | 当前事实/裁决 |
|---|---|---|---|---|---|
| 插件 | `BasePluginClient` 的 HTTP 连接池、timeout、API key、traceparent、路径遍历防护（`api/core/plugin/impl/base.py:44-169`） | `PluginToolManager`、`PluginModelAssembly`、`PluginService`，负责 tenant/plugin/provider 解析和声明转换 | `ToolEngine`/`ModelInstance` 通过 plugin client 执行；插件代码不进 API 进程 | plugin management/dispatch inner API、Console plugin routes | 吸收“主进程 client + 独立宿主”边界；daemon 安装/执行生命周期仍是仓库外未核验 |
| 工具 | 加密 credential、HTTP/SSRF、文件转换、trace callback | `ToolManager` 将 `BUILT_IN`/`PLUGIN`/`WORKFLOW`/`API`/`MCP` 路由到 provider controller（`tool_manager.py:94-188`）；工具 provider 是模块契约 | `ToolEngine.agent_invoke/generic_invoke` 是实际执行单元；Agent 错误多转成 observation，workflow 错误向上抛给节点事件（`tool_engine.py:49-203`） | tools management、workflow tool config、MCP/API tool endpoints | 吸收工具统一 provider/engine；不能让每种 provider 拥有一套错误和文件输出协议 |
| 节点 | Code executor、HTTP client、file manager、limits、serializer | `core/workflow/nodes/*` 的节点实现和 `DifyNodeFactory` 的构造参数表 | `graphon Graph/GraphEngine` 驱动单节点；factory 对配置做 shared schema → concrete node schema 二次校验（`node_factory.py:376-480`） | workflow draft/publish/run routes | 吸收“注册表 + 版本解析 + 二次校验 + context 注入”；`graphon` 节点算法本体标外部依赖 |
| 工作流 | DB session、pause snapshot、storage offload、timeout/limit layer | `WorkflowService`、`WorkflowAppGenerator`、async dispatcher、pause/resume service | `WorkflowEntry`/`WorkflowBasedAppRunner` 驱动 graph；`_handle_event` 将 Graph 事件转 Queue 事件（`workflow_app_runner.py:408-619`） | `/api/workflows/run`、`/v1`、`/openapi/v1/apps/{app_id}:run`、Console | 吸收“版本化图 + 运行上下文 + 节点事件 + 暂停恢复”；graph JSON 不是强关系节点注册库 |
| 模型供应商 | graphon model protocol、HTTP client、加密/缓存、Redis cache | `ProviderManager` 读取 tenant-scoped provider/model/credential/settings；`PluginModelAssembly` 共享 request-scoped runtime | `ModelInstance` 绑定 provider/model/credentials，负责 LLM/embedding/rerank/TTS 等实际调用并可接 load balancing（`model_manager.py:35-116`） | provider/model credential/config routes | 吸收“配置 owner → provider factory → model instance”唯一链；不能把 provider credential 对象穿透到节点/前端 |
| 队列/任务 | Redis、Celery broker/worker、TTL cache、锁 | `AsyncWorkflowService` 写 trigger log、按 tier 选队列、reserve/commit quota；Celery task 是任务模块（`async_workflow_service.py:39-194`） | `async_workflow_tasks._execute_workflow_common`、`resume_workflow_execution`；同步请求则由 `AppQueueManager` 进程内 queue 驱动 | trigger API、task stop API、workflow events/SSE | 吸收“提交—任务记录—执行—投影”；Celery 重投/worker 崩溃恢复未由当前核对源码证明，不能把 `retry_count` 当 lease |
| 事件 | Pydantic event schema、Redis Streams、cursor/TTL、序列化 | queue event entity、event adapter、持久化 repository/trace queue | Graph `GraphRun*`/`NodeRun*` → `QueueWorkflow*`/`QueueNode*`；Agent sink → typed run event | SSE/HTTP event page、Agent `/runs/{id}/events` | 吸收“事件先统一类型再投影”；Dify AppQueue 是实时消费队列，Agent Redis Stream 才是可 cursor replay 的事件日志，两者不可混称 |
| 数据库 | SQLAlchemy/Alembic、session factory、事务/row lock | `models/`、repositories、service transaction；`workflow_trigger_logs` 是异步触发事实表 | workflow run/node execution、message/thought、provider/tool/file 状态投影 | REST/OpenAPI DTO 和 query routes | 吸收“DB 作为事实/状态 owner”；当前模型新旧 Base 并存、部分状态写在服务层，append-only/event-sourcing 未被证明 |
| 文件/制品 | `extensions.ext_storage.storage`、OpenDAL/S3 等、签名 URL、hash/size limit | `FileService`、`ToolFileManager`、`DatabaseFileAccessController`、offload/archive services | node/tool/LLM file saver 把字节变成 `UploadFile`/`ToolFile` 引用；大 node data 通过 `workflow_node_execution_offload` 转制品指针 | `/files`、upload/preview、Agent output adapter | 吸收“制品引用 + owner scope + storage abstraction”；数据库和对象存储双写的补偿/孤儿清理需继续验证 |
| 前后端边界 | React Query/Jotai/ORPC client、Zod/OpenAPI TS codegen | `web/features/*` 按 feature 持有 UI/query state；`packages/contracts` 维护生成与手工拼装 contract | 浏览器不进入运行核心，只消费 command/query/event projection | `web/service/client.ts` 的 `OpenAPILink` + `consoleClient/consoleQuery` → API prefix | 吸收“生成契约为唯一前端调用面”；旧 handwritten helper 只能在 legacy 兼容层，不能成为新 owner |

### 14.4 组件注册与唯一装配链

#### 节点注册

`DifyNodeFactory` 的注册不是硬编码一张永远静态的字典，而是 `NODE_TYPE_CLASSES_MAPPING` 对 `get_node_type_classes_mapping()` 的 lazy snapshot；`Node.get_registry_version()` 变化时重建，另允许测试/兼容层 override/delete（`api/core/workflow/node_factory.py:180-231`）。`create_node()` 先用通用 `NodeConfigDictAdapter` 校验，再按 `node_type + node_version` 调 `resolve_workflow_node_class()`，随后调用节点类的 `validate_node_data` 做具体二次校验，最后注入 code limits、HTTP/文件、模型、HITL、tool runtime 等依赖（`node_factory.py:376-466`）。

测试 `api/tests/unit_tests/core/workflow/test_node_mapping_bootstrap.py:8-60` 用隔离 subprocess 验证生产入口导入后 `KNOWLEDGE_RETRIEVAL`、knowledge index、datasource 和 Agent v2 能从 registry 解析；这证明注册/导入边界有回归测试，不证明所有版本节点都能在本机运行。

#### 工具与插件注册

`ToolManager` 使用进程级 builtin cache/lock；未知 builtin provider 转到按 `tenant_id` 的 plugin provider，plugin provider 再以 `contexts.plugin_tool_providers` 做请求上下文缓存（`tool_manager.py:94-175`）。`PluginToolManager.fetch_tool_providers()` 从 daemon 拉声明，给 provider/tool 强制加 `plugin_id/provider` 命名空间并解引用 output schema；`invoke()` 以 tenant/user/provider/tool/credentials/parameters 调 daemon stream，合并 blob chunks 并限制最大文件大小（`api/core/plugin/impl/tool.py:17-127`）。

因此通用底座应把“声明注册”和“执行调用”拆成两个可审计动作：

```text
插件/内置声明
  → 唯一 provider/tool identity 归一化
  → ToolManager provider registry
  → ToolEngine runtime handle
  → ToolEngine.agent_invoke 或 generic_invoke
  → 统一 ToolInvokeMessage/ToolInvokeMeta/error
  → observation、node event、message/file/trace projection
```

当前实现仍有 builtin YAML 扫描、plugin daemon、workflow-as-tool、API/MCP 等多策略；后续裁决为“统一 `ToolManager`/`ToolEngine` owner，provider 只提供声明和策略”，不把每个 provider 的实现复制进底座。

#### 模型供应商注册

`PluginModelAssembly` 把一个 tenant/user 请求绑定到一个 `PluginModelRuntime`，再由同一 runtime 构造 `ModelProviderFactory`、`ProviderManager` 和 `ModelManager`（`model_runtime_factory.py:48-110`）。`ModelInstance` 再从 `ProviderModelBundle` 得到 provider/model/credentials，并按自定义 provider 的 load-balancing configuration 选择凭证（`model_manager.py:35-116`）。这是一条比“节点自己找 provider”更接近通用底座的装配链；节点只能获得 `ModelInstance` 或受限 wrapper，不应获得 DB credential rows。

### 14.5 任务执行单元、租约、状态投影与失败恢复

| 执行单元 | 创建入口 | 持有/租约事实 | 状态投影 | 成功/失败/取消/崩溃恢复 |
|---|---|---|---|---|
| 同步 App/Workflow run | Controller → generator/runner | `AppQueueManager` 将 `generate_task_belong:{task_id}` 写 Redis TTL 1800；stop flag TTL 600；这是请求归属和停止标记，不是 worker lease（`base_app_queue_manager.py:35-57,178-239`） | Queue event → SSE/response；runner 同时写 workflow/message/node execution | listener 超时或客户端断流会 `send_stop_command` 并发 `QueueStopEvent`；进程崩溃后的接管未证明 |
| Celery 异步 workflow | `AsyncWorkflowService.trigger_workflow_async` 先写 `WorkflowTriggerLog(PENDING)`，reserve quota，再按 tier `.delay()`，回写 `QUEUED + celery_task_id`（`async_workflow_service.py:85-194`） | trigger refresh 有 Redis `SET NX EX` in-flight lock；普通 workflow trigger log 有 `retry_count`，未见通用 task lease/heartbeat | trigger log → task → workflow run/node execution → events | 执行异常写 trigger log `FAILED`；pause 用 serialized graph runtime state + `resume_workflow_execution`；Celery worker crash/re-delivery/租约接管未在当前代码闭环确认 |
| 文档索引任务 | `sync_website_document_indexing_task`/其他 `@shared_task(queue="dataset")` | 用 Redis `document_{id}_is_sync` 标识；函数先清理旧向量/segments，再写 `PARSING`，释放事务后运行 `IndexingRunner` | `Document.indexing_status/error/stopped_at` + vector index | 异常 rollback 后写 `ERROR` 并删除 sync key；数据库/向量双写中断后的补偿未证明 |
| Agent backend run | `POST /runs` → `RunScheduler.create_run` → `asyncio.create_task(AgentRunRunner.run)` | `active_tasks` 仅进程内；Redis run record/stream 是状态和事件持久化，不是 job queue；没有跨进程 lease（`run_scheduler.py:1-13,63-120`） | `run_started`、typed stream events、single terminal event；Redis JSON record 的 status 与 Redis Stream 的 cursor 共享 retention | cancel 写 `run_cancelled` + `cancelled`，shutdown grace 后 pending 以 `run_failed(reason=shutdown)` 收口；进程突然崩溃时活动 run 不会自动接管，源码 docstring 明确要求外部 operator 标记/重试 |
| Trigger subscription refresh | scheduler 扫 due rows，批量 `SET key NX EX` 后 group enqueue | 这是当前最明确的短租约：TTL 至少 300 秒，任务 finally 删除 key；TTL 到期可避免永久卡死，但没有 owner token 校验（`trigger_provider_refresh_task.py:36-45,48-105`） | subscription credential/expires_at 由 provider service 更新 | 找不到订阅/刷新异常记录日志；finally best-effort delete；重复执行和 crash 后再执行依赖 TTL |

**租约裁决：** Dify 有“归属 TTL”“停止 TTL”“refresh in-flight lock”“数据库/Redis transaction”等局部占用语义，但没有覆盖所有任务执行单元的统一 `lease_id/owner/fencing_token/heartbeat/expires_at` 契约。通用底座不能把这些局部 key 直接升格为租约；需要新建统一 lease contract，至少绑定 `{resource_id, execution_id, owner_id, lease_id, issued_at, expires_at, heartbeat_at, fencing_token}`，并把失效后的 recovery policy 交给运行核心。当前 status 字段、Celery task id、Redis key 和 cursor 都不是 lease owner。

**状态投影裁决：** workflow trigger log、workflow run/node execution、message thought、AppQueue event、Agent Redis run record/stream 是不同投影。当前源码可以证明“事件/状态被写入多个投影”，不能证明它们共享全局 event id、严格顺序、幂等去重或可从事件完整重放；因此只吸收 projection adapter，不宣称 Dify 已实现事件溯源。

### 14.6 后续唯一链路与契约冻结

#### 14.6.1 目标唯一链路

跨入口的通用底座应收敛为下列一条能力链；入口差异只出现在 gateway adapter，不得在 controller、worker、Agent backend 各复制一份核心。

```text
Web / SDK / CLI / webhook / plugin / Agent backend
  → gateway: auth + tenant + version + request DTO + idempotency
  → module command: resolve owner/config/version + create execution record
  → execution registry: component/node/provider/task identity
  → runtime core: execute one unit with deadline/cancel/lease context
  → support provider: DB/Redis/storage/model/plugin/sandbox/HTTP
  → typed event sink: started/progress/retry/paused/succeeded/failed/cancelled
  → authoritative projection writer: run/node/task/status/artifact/trace
  → gateway query/event stream: SSE/polling/replay + typed error
```

Dify 当前对应的最长真实链是：

```text
/openapi/v1/apps/{app_id}:run
  → AppGenerateService / WorkflowAppGenerator
  → WorkflowEntry + DifyNodeFactory
  → graphon GraphEngine
  → WorkflowBasedAppRunner._handle_event
  → QueueWorkflow*/QueueNode*
  → AppQueueManager / workflow run-node execution repositories
  → SSE、workflow event API、数据库投影
```

异步触发链是：

```text
trigger API
  → AsyncWorkflowService.trigger_workflow_async
  → WorkflowTriggerLog(PENDING/QUEUED)
  → tier dispatcher + Celery task id
  → async_workflow_tasks._execute_workflow_common
  → WorkflowAppGenerator + TriggerPostLayer
  → trigger log/workflow run/node events
```

Agent backend 是另一条运行进程链：

```text
agent_v2 node
  → HTTP/SSE client
  → RunScheduler + RunStore
  → AgentRunRunner
  → event sink
  → Redis run record + Redis Stream
  → API adapter / SSE / UI
```

后续裁决不是把这三条链都保留为三个底座，而是：共用 `ExecutionContext`、`ExecutionEvent`、`Lease`、`ArtifactRef`、`StatusProjection` 契约；Dify 的 Graph/Celery/Agent backend 分别作为 runtime adapter，逐步把状态写 owner 和取消/恢复策略收敛到同一执行服务。

#### 14.6.2 最小契约表

| 契约 | 唯一 owner | 必填字段/不变量 | 超时/取消/重试 | 资源责任 |
|---|---|---|---|---|
| ComponentRef | component registry | `namespace/id/version/kind`；节点解析失败必须是 typed error | 不重试解析错误；provider 缺失由模块决定 fallback/终止 | registry 只读快照，运行实例由 execution owner 释放 |
| ExecutionCommand | gateway/module command | `tenant_id/subject_id/execution_id/component_ref/input_hash/idempotency_key/deadline`；调用方不能提交最终状态 | deadline 传入 runtime；取消只能由 owner/授权 gateway 发出 | 创建 execution record 的模块负责提交/回滚 |
| Lease | execution/lease service | `lease_id/owner/fencing_token/expires_at/heartbeat_at`；续租须校验 token | 过期不得继续写 authoritative projection；抢占/恢复需 fencing | holder 负责 heartbeat/final release，crash 由 reaper/recovery 接管 |
| ExecutionEvent | event sink | `event_id/execution_id/sequence/type/created_at/payload_schema_version`；终态互斥 | retry/progress 可重复但需幂等；terminal 只能一次 | event sink 负责 append/cursor/retention |
| StatusProjection | execution projection owner | status 必须由 event/command 推导，不能由 UI 任意写；记录 `error_code/retryable/finished_at` | projection 重放幂等；缺事件标 degraded | owner 负责 DB/Redis/stream 一致性和 repair |
| ArtifactRef | artifact/file owner | 只传 `artifact_id/storage_key/mime/size/hash/tenant/owner/expires_at`，不传任意 path/credential | 取消/失败按 policy 删除或保留证据；清理可异步但可观测 | 创建者或显式 transfer owner 负责 release/retention |
| ProviderInvocation | provider module | provider/model/credential ref/timeout/trace；credential 只在支持库边界解密 | connection/rate limit 可按 policy retry；参数/授权错误不重试 | HTTP/plugin/model client 关闭 stream/session |

当前 Dify 的对应关系是“部分契约”：`ToolInvokeMeta`、Queue event Pydantic models、Agent run schemas 和 generated OpenAPI 是可吸收的契约素材；统一 `idempotency_key`、`sequence`、`lease_id/fencing_token`、全链 status projection 仍是缺口，不能由现有字段臆造。

### 14.7 资源生命周期（成功、业务失败、超时/取消、崩溃四态）

| 资源 | 创建/持有 | 正常释放 | 业务失败 | 超时/取消 | 宿主崩溃后的现状与底座要求 |
|---|---|---|---|---|---|
| DB session/transaction | service/task 进入 `session_factory`/`Session`；查询/状态写入 | context manager/commit 后关闭；长 LLM I/O 前显式 `commit` 释放 transaction（`async_workflow_tasks.py:165-169`） | rollback 后写错误投影 | stop/timeout 应 rollback 并关闭；部分任务需补偿 | DB 会回收连接/锁，但业务状态可能停在 RUNNING/PARSING；需要 recovery scan |
| Redis task ownership/stop key | `AppQueueManager.__init__` 写 task belong TTL；stop 写 stop TTL | `stop_listen` 删除 belong；TTL 自然到期 | error path 不保证所有外部 key 已删除 | listener finally abort、删除 belong；stop key 仍可能留至 TTL | 无 fencing；需要 owner token 和 orphan sweeper |
| AppQueueManager in-memory queue | 每次 run 建 `queue.Queue`、threading/lifecycle events | `stop_listen` 放 sentinel，释放 graph runtime reference | `publish_error`/terminal stop，listener finally abort | listener max execution time/客户端断流触发 abort | 进程死 queue 丢失；DB/Redis 投影可能不完整，不能 replay |
| Celery task | `.delay()` 创建 broker message，trigger log 保存 task id | task 完成，trigger log finished/failed | `_execute_workflow_common` 写 FAILED/error/elapsed | pause 改走 resume task；取消边界需任务/Graph stop 协同 | 当前核对未证明 ack/requeue/worker crash 恢复；需要 broker/worker 运行验证 |
| Agent asyncio Task | `RunScheduler.create_run` 注册 `active_tasks[run_id]` | done callback 删除 active entry | runner 发 `run_failed` + store status | `task.cancel`，先持久化 `run_cancelled/cancelled`，再最多二次注入 cancellation | 进程崩溃 active registry 丢失；Redis record 可能永久 running 直到 retention，需 recovery worker |
| Redis run record/stream | create/status `SET`；event `XADD` | TTL 由 status/event 刷新，过期删除 | `run_failed` event + error status | `run_cancelled` event + cancelled status | stream/record 可 replay 但并非任务接管机制；清理/保留策略必须 owner 化 |
| model/plugin HTTP stream | pooled HTTP client/stream；plugin client 统一 timeout | generator/response 完成后应关闭；具体 daemon 端生命周期仓库外 | typed provider/plugin error，工具可转 observation | deadline/HTTP timeout 应终止 stream；ToolEngine 只返回 error meta | 连接由进程/HTTP client 回收，第三方副作用未知；需 provider idempotency |
| UploadFile/ToolFile/对象制品 | `FileService` 先 storage.save，再 DB `UploadFile`；node/tool 通过 file ref | 业务 retention/deletion/cleanup；签名 URL 非所有权转移 | DB insert 失败可能留下 storage orphan（当前代码无同事务补偿证据） | 取消/失败需按 artifact policy 删除或保留 | crash 双写窗口可能产生 orphan；需 outbox/compensating cleanup/hash reconciliation |
| graph runtime state/pause snapshot | `GraphRuntimeState`、VariablePool、pause repository 序列化 | run 完成后 runner/queue 清理引用；pause 由 resume 消费 | failed event 记录错误，快照是否保留取决于 pause | abort 应释放内存且保留必要审计 | 进程死内存态丢失；只有已持久化 pause/DB state 可恢复 |

文件边界的源码证据是 `DatabaseFileAccessController`：有 scope 时同时约束 tenant，并在 end-user 场景约束 `created_by` 或显式 granted upload；`FileService.upload_file` 以 UUID/tenant 生成 storage key，先写对象存储再写 `UploadFile` row。它证明了访问控制和制品引用方向，未证明跨存储事务、孤儿回收和崩溃补偿已经闭环。

### 14.8 失败、超时、取消、崩溃矩阵

| 场景 | 当前源码处理 | 状态/事件投影 | 是否可重试/恢复 | 证据与风险 |
|---|---|---|---|---|
| provider/model 不存在 | `ToolProviderNotFoundError`、`ProviderTokenNotInitError` 等在 manager/engine 层抛出 | 工具 Agent 路径转 observation/error meta；workflow 节点由 Graph 产生 failed/exception | 参数/配置错误不应盲重试；需修配置后新 execution | `tool_engine.py:130-157`、`model_manager.py:66-80`；跨入口错误码仍需统一 |
| 工具参数非法 | `ToolParameterValidationError` 转可读 error response，并 callback `on_tool_error` | Agent 继续消费 observation；workflow generic path re-raises | 不重试同一 payload；可由模型修正后新调用 | `tool_engine.py:67-80,138-157`；两种 invoke 语义必须保留在契约中 |
| plugin daemon HTTP/权限/超时 | `BasePluginClient` 配置 timeout，RequestError 映射 `PluginDaemonInnerError`；工具 stream 经 blob merger | ToolEngine callback/error meta 或 node failure | 连接/503 可策略重试，参数/授权不重试；当前统一 retry policy 未见 | `base.py:44-101`；daemon 实现仓外，S0 |
| node retry | Graph `NodeRunRetryEvent` 映射 `QueueNodeRetryEvent`，带 retry_index、inputs/process/outputs/error | Queue retry event，最终 node succeeded/failed/exception | 由 Graph/node policy 决定；投影必须用 execution id + retry index 去重 | `workflow_app_runner.py:472-500`、`queue_entities.py:387-399` |
| workflow business failure | `GraphRunFailedEvent` → `QueueWorkflowFailedEvent`；async task catch 写 trigger log FAILED | workflow event + DB error/elapsed | `reinvoke_trigger` 为新尝试；pause 不同于 failure | `workflow_app_runner.py:423-426`、`async_workflow_tasks.py:188-200`；当前 trigger log 不等同 event ledger |
| execution time limit | `AppQueueManager.listen` 按 `APP_MAX_EXECUTION_TIME` 触发 `_abort_execution`；Graph layer 另有限制 | `QueueStopEvent`，下游应停止 Graph | 同一 execution 不应重入；需新 idempotency key | `base_app_queue_manager.py:64-99`；停止信号可能与 runner race |
| client disconnect | `listen` finally 以 “response stream closed” abort，清理 runtime reference | stop/abort event 视 runner 响应而定 | 不自动续跑；应以 execution status 查询收口 | `base_app_queue_manager.py:96-120`；客户端断流后的 DB 终态需运行验证 |
| user cancel Agent run | scheduler 先写 `run_cancelled`，再 status cancelled，并最多二次 cancel task | Redis terminal event + status | cancel 幂等；已 finished/不在本进程则 conflict | `run_scheduler.py:122-154`，测试 `test_run_scheduler.py:189-251` |
| Agent graceful shutdown | 等 grace；pending task cancel 后写 `run_failed(reason=shutdown)` | failed event + failed status | 可由外部重新提交；不是原 run 自动 resume | `run_scheduler.py:156-211`，测试 `:163-186` |
| Agent process crash | `active_tasks` 丢失，Redis record/stream 保留到 TTL | 可能停在 running，无 terminal event | 当前没有跨进程 claim/recovery；需要外部 operator/recovery worker | `run_scheduler.py:1-13` 明文说明；这是 P0 可靠性缺口 |
| Celery worker crash/requeue | 当前核对只看到 `@shared_task`、task id、retry_count 和 failure write | 可能停在 QUEUED/RUNNING，取决于 broker/ack 运行态 | broker redelivery 及幂等未在源码/当前核对运行证明 | `async_workflow_service.py:161-187`、`models/trigger.py:278-292`；S3 |
| DB exception/transaction rollback | tasks 使用 rollback/context；异步 workflow finally/except 写 failure | error/status 投影可能成功，也可能因第二次 DB 故障失败 | 需要安全重试和 duplicate guard | `sync_website_document_indexing_task.py:92-109`；未做真实 DB 注入 |
| storage/DB 双写失败 | FileService storage.save 后独立 DB commit | 可能无 DB 引用的对象制品 | 需 orphan scan/hash reconciliation；不能简单重试导致重复对象 | `file_service.py:85-118`；当前无跨存储事务证据 |
| Redis unavailable | queue stop/status/cursor/TTL 读写可能异常；部分路径记录日志 | 事件实时流/取消/归属投影不可靠 | 需要降级/重连/最终一致性策略 | 多处 `RedisError` best effort；当前核对未启动 Redis |

### 14.9 L0–L4 通用底座分级与当前落点

| 层级 | 进入条件 | Dify 可复用材料 | 当前缺口/裁决 | 验收门槛 |
|---|---|---|---|---|
| **L0 支持库** | 无业务状态 owner；可独立测试、资源边界清晰、协议稳定 | SQLAlchemy session factory、Redis/Celery adapter、storage、HTTP/SSRF、credential encryption、typed schema/cursor、plugin client transport | 吸收；Redis key/lock 先去业务化，不把 Dify key 当通用契约 | 单测覆盖成功/异常/timeout/cancel；连接、session、stream、temp file 无残留 |
| **L1 原子能力** | 一个 capability id + 一个 provider contract + 一个错误/资源协议 | `ToolManager` provider resolve、`ToolEngine` invoke、`ModelInstance`、file access、artifact ref、node class resolve | 吸收并做 façade；provider-specific credential/ORM 只能在 adapter 内 | 缺 provider、坏参数、重复 idempotency、权限、超时、取消均有 contract test |
| **L2 领域模块** | 一个模块编排一个业务流程，拥有状态变更和重试策略 | workflow run, async trigger, indexing, plugin management, provider config, pause/resume | 吸收流程，但要去除多入口旁路写和隐含 fallback | command→execution→event→projection 一条链，事务和恢复测试闭环 |
| **L3 运行核心/统一网关** | runtime 执行单元与 gateway 契约分离；所有入口复用同一 execution/event/lease | `WorkflowBasedAppRunner`/Graph adapter、AgentRunRunner/Scheduler、API controllers、OpenAPI TS contracts、SSE cursor | 这是当前最大的合并目标；Dify 现在是多入口、多投影，不能标已完成 | Web/SDK/CLI/trigger/plugin/Agent 入口都走同一 capability owner；错误、取消、事件顺序一致 |
| **L4 运行治理** | 可观测、租约/抢占/恢复、容量/配额、审计、制品 retention、回放/repair | quota reserve/commit/refund、trace queues、retention/archive services、partial shutdown | 吸收治理素材；统一 lease/fencing、crash recovery、projection repair 未完成 | 注入 worker/Redis/DB/plugin/storage crash，验证最终状态、幂等、租约接管、资源清理和审计证据 |

### 14.10 复用/升级/新建/隔离裁决

| 对象 | 裁决 | 不能直接照搬的部分 |
|---|---|---|
| `BasePluginClient` + plugin declaration/invoke | **吸收**为插件支持库/模块 adapter | daemon 安装、插件进程生命周期和权限执行在仓外，必须补运行证据 |
| `ToolManager` + `ToolEngine` | **升级现有能力**为唯一工具入口 | 当前 builtin/plugin/workflow/API/MCP 兼容分支需统一 capability id/error/resource contract |
| `DifyNodeFactory` + node registry | **吸收**注册和版本解析模式 | registry snapshot/legacy imports 的全局刷新、动态卸载和版本兼容需补契约 |
| `WorkflowBasedAppRunner` + Graph event adapter | **吸收**为 workflow runtime adapter | `graphon` 外部实现、DB projection 全量重放和 lease 未证明 |
| `PluginModelAssembly` + `ModelManager/ModelInstance` | **吸收并升级**为 provider/model 唯一装配链 | credentials 不能穿透节点；负载均衡和 provider failover 需统一 retry/health contract |
| `AsyncWorkflowService` + Celery tasks | **吸收编排模式**，新建通用 ExecutionCommand/TaskRecord | Celery task id/retry_count 不能代替 idempotency/lease/fencing；worker crash 需补偿 |
| AppQueue/Queue entities | **吸收事件类型和 stop semantics** | 进程内 queue 不作为长期事件日志；需统一 event id/sequence/cursor |
| Agent `RunScheduler` + RedisRunStore | **隔离为进程运行 adapter，升级 recovery** | 当前无跨进程 lease，Redis 不是 job queue；不得直接宣称可恢复执行 |
| `DatabaseFileAccessController` + FileService/artifact offload | **吸收访问控制与制品引用** | storage/DB 双写补偿、retention、orphan scan 必须由制品 owner 负责 |
| `packages/contracts` + `web/service/client.ts` | **吸收为网关/前端契约边界** | generated artifact 必须由源 OpenAPI 生成；marketplace/manual contract 单独标注，不混入 Dify API owner |

### 14.11 测试映射与当前核对验证边界

| 关注点 | 已读测试源码 | 证明什么 | 当前核对状态 |
|---|---|---|---|
| 节点组件注册 | `api/tests/unit_tests/core/workflow/test_node_mapping_bootstrap.py:8-60` | 生产入口导入后 registry 能解析若干节点和 Agent v2 | S1，未执行 |
| Graph→Queue 状态投影 | `api/tests/unit_tests/core/app/apps/test_workflow_app_runner_core.py:368-580` | started/succeeded/paused/aborted、node retry/fail/exception 等映射存在 | S1，未执行 |
| Async Celery 路由与 trigger log | `api/tests/unit_tests/services/test_async_workflow_service.py:146-226` | tier → queue task、trigger log、quota commit 的测试意图 | S1，未执行 |
| Async task 参数/异常文本 | `api/tests/unit_tests/tasks/test_async_workflow_tasks.py:10-105` | resume task 的输入和异常消息边界 | S1，未执行 |
| Agent cancel/shutdown/failure | `dify-agent/tests/local/dify_agent/runtime/test_run_scheduler.py:137-354` | background task、cancel 幂等、shutdown failure、异步失败 projection | S1，未执行 |
| Agent Redis record/stream retention | `dify-agent/tests/local/dify_agent/storage/test_redis_run_store.py:103-186` | record TTL、XADD+双 expire transaction、cursor round-trip | S1，未执行 |
| 文件权限 | 目标测试树中未按 `*file_access*` 找到对应文件名；源码有 controller 使用点 | 只能证明源码边界，不能证明所有 tenant/end-user 组合 | S0，待补测试定位 |

当前核对实际验证只允许做文档/工作树静态检查：目标文件现场回读、Markdown fence/标题检查、`git diff --check`、`git status`。未执行 `uv run pytest`、`make test`、`pnpm test`、Docker、Celery、Redis、数据库迁移、插件 daemon、Agent backend 或 E2E，所以不能将上表 S1 升级为通过。

### 14.12 未决风险与下一轮装配前置条件

1. **错误项目上下文**：必须重新以 Dify 根目录建立可用项目上下文后，才能把 MCP/code graph 结果纳入证据；当前核对已明确排除错绑结果。
2. **统一执行租约缺失**：先冻结 `Lease`/fencing/reaper/recovery contract，再改 worker、Agent backend 或 Celery wiring；没有 lease 不能声称 crash-safe。
3. **状态投影不统一**：先决定 `ExecutionEvent` 的唯一 append owner、sequence、idempotency 和 projection repair，再把 AppQueue、workflow DB、Agent Redis Stream 对齐；不能从多个现有表拼出“事件溯源已完成”。
4. **插件 daemon/Graphon 外部边界**：需要读取 pinned package/daemon protocol 或做隔离运行测试，验证 timeout、断流、版本、权限、重试、文件 blob 和资源关闭。
5. **制品双写**：需要 storage failure/DB failure/crash 注入和 orphan scan，明确失败/取消后的保留期、删除 owner、签名 URL 失效和 hash reconciliation。
6. **Celery 运行事实**：需要明确 ack、visibility timeout、requeue、worker crash、重复投递和任务幂等；`celery_task_id` 与 `retry_count` 只能做观测字段。
7. **旧细探缺失**：若后续找到历史 `细探-dify.md`，必须逐条对照当前源码并只吸收进本文件；不得恢复成第二事实源。

后续结论：Dify 最值得进入通用底座的不是产品目录，而是四个可验证模式——**组件注册与版本解析、provider/工具统一装配、事件到状态投影、资源与失败边界显式化**。其中前两项已有较强 S0/S1 素材，后两项在单进程/单存储路径成立，但统一租约、跨进程崩溃恢复、跨投影幂等和制品补偿仍是 L3/L4 缺口；在这些缺口闭合前，裁决只能是“吸收模式、升级契约、隔离运行时”，不能宣称通用底座已落地。

## 15. 后续源码深挖：插件、工具、节点、工作流与运行治理

> 本节是对前 1–14 节的后续定向深挖，专门补齐“声明如何进入运行时、运行结果如何落库/出流、失败后谁负责收口”的证据。只读目标目录源码；未安装依赖、启动 Redis/Celery/数据库/插件 daemon、运行测试或调用外部 provider。结论仍以 S0（源码）/S1（测试源码）为限，不能将静态路径写成运行成功。

### 15.1 插件、工具、节点、工作流的真实装配链

#### 插件不是 Python import，而是声明与 HTTP 执行边界

API 进程中的 `BasePluginClient`（`api/core/plugin/impl/base.py`）维护共享 HTTPX client，统一注入 `X-Api-Key`、可选 `traceparent` 和超时；请求路径限制为 4096 字符，最多解码 8 层，并拒绝解码后的 `..` 路径段。普通请求把网络异常归一为 `PluginDaemonInnerError`，流式请求按行消费 daemon 返回的 `data:` 片段。由此可确认：

```text
tenant/provider/tool/model 配置
  → API 侧 plugin client
  → plugin daemon inner API
  → daemon 内部安装/权限/运行插件
  → JSON/流式文本/blob 返回
```

API 侧没有插件实现代码；`dify-agent` 也只通过 `DifyPluginDaemonToolClient`、`DifyPluginDaemonProvider` 调 daemon。插件安装、沙箱、子进程生命周期、daemon 的版本兼容和真实权限判定不在本仓库源码内，不能把 client 的错误映射当作 daemon 的完整契约。

#### 工具声明和工具执行是两次不同的动作

`ToolManager` 的 provider 路由具有进程级 builtin cache 和请求上下文 plugin cache：

```text
ToolProviderType
  → BUILT_IN: provider 目录/YAML/硬编码 controller
  → PLUGIN: tenant + provider → PluginToolManager.fetch_tool_provider()
  → WORKFLOW: workflow app 包装为 WorkflowTool
  → API: OpenAPI/Swagger 声明为 ApiTool
  → MCP: MCP server/session 包装为 MCPTool
  → DATASET_RETRIEVAL: Agent 场景直接构造的检索工具
  → ToolRuntime(tenant/user/credentials/invoke_from)
```

插件 provider 的声明会补上 plugin 命名空间，再生成 `PluginToolProviderController`；同一请求中按 provider 缓存，避免每次调用重新请求 daemon。未知 builtin provider 才回退到 plugin provider，故“内置/插件”不是两个并列执行引擎，而是 provider resolve 阶段的策略分支。

`ToolEngine` 将执行分为两种不可混淆的契约：

| 入口 | 调用方 | 结果/错误语义 |
|---|---|---|
| `agent_invoke` | Function Calling / CoT Agent | 把字符串参数转 dict；将文本、JSON、链接、图片和二进制统一转为模型可读 observation；多数工具异常转 `ToolInvokeMeta.error_instance` 后继续 Agent 循环 |
| `generic_invoke` | Workflow 节点/Workflow-as-tool | 合并 runtime 参数，执行 callback，异常重新抛给 Graph/节点事件；不把错误伪装成 Agent observation |

执行期间 `ToolInvokeMessage` 可产生文件；`ToolFileMessageTransformer` 负责转换，`_create_message_files` 把二进制结果投影为 `MessageFile`。因此工具结果不是单纯字符串，必须同时拥有文本 observation、文件引用、耗时/错误 meta 和 trace callback 四种输出通道。

#### 节点注册是 lazy snapshot + 双重校验

`DifyNodeFactory` 通过 `get_node_type_classes_mapping()` 延迟取得节点映射，并按 registry version 重建 snapshot；测试/兼容路径还允许 override/delete。`create_node()` 的顺序是：

1. 用通用 `NodeConfigDictAdapter` 校验节点公共字段；
2. 用 `node_type + node_version` 解析具体 class；
3. 调用节点 class 的 `validate_node_data` 做二次专用校验；
4. 注入代码执行限制、HTTP/文件访问、模型、HITL、工具运行时等依赖。

这不是“读取 graph JSON 后反射执行”。真正可执行的是 registry 解析出的版本化 class；graph JSON 只提供配置和拓扑。节点算法主要由 `graphon` 外部包承载，Dify 的 node factory 是适配、版本选择、校验和依赖注入边界。

#### 工作流是版本化图配置 + 运行时状态，不是节点关系表

`workflows.graph` 持久化 nodes/edges/data JSON，`version=draft` 与发布版本并存。运行时由 `WorkflowAppGenerator` 创建 `WorkflowEntry`/`WorkflowBasedAppRunner`，构造 tenant/app/user/invoke/trace 上下文和 `VariablePool`，再交给 Graphon `GraphEngine`。Graph engine layers 至少承担执行步数/时间限制、租户 LLM quota、OTel、暂停状态和 trigger post 状态投影。

节点/图事件在 `_handle_event` 中转换为 Dify `QueueWorkflow*`、`QueueNode*`、文本块、检索资源等事件，同时由 repository 写 `workflow_runs`、`workflow_node_executions` 和日志。HITL pause 会序列化 graph runtime state、response filter 和生成参数，之后由 Celery `resume_workflow_execution` 恢复；这条恢复路径依赖已持久化 pause snapshot，不等同于任意运行中工作流的崩溃接管。

### 15.2 模型供应商：配置装配、凭证边界与调用实例

`ProviderManager` 以 `tenant_id` 为主键装配 workspace provider graph，读取 provider、model、preferred provider、model settings、load-balancing 和 credential 记录，再调用注入的 `ModelProviderFactory` 生成 provider entities。实例级配置缓存在 manager 内，支持按 tenant 清理和跨进程 source cache invalidation。

`ModelInstance` 只在模型运行时边界拿到当前 provider/model credentials：

```text
PluginModelAssembly / model runtime
  → ProviderManager.get_configurations(tenant_id)
  → ProviderConfiguration / ProviderModelBundle
  → ModelInstance(provider, model, credentials)
  → LLM / embedding / rerank / moderation / STT / TTS adapter
```

如果当前模型凭证不存在，抛出 `ProviderTokenNotInitError`；自定义 provider 的 load balancing 由 `LBModelManager` 按配置选择 credential。节点和工具不应读取 provider ORM 行，也不应持有未掩码凭证；通用底座应将 `ProviderInvocation` 作为唯一受控调用对象，支持库负责解密、HTTP/流关闭和底层错误归一。

provider 错误至少分为授权/参数、连接、限流、服务不可用、凭证未初始化五类。当前源码能够看到异常类型和部分调用分支，但没有全 provider 统一的 retry budget、熔断、幂等键和健康状态 owner；因此“load balancing”不是“故障自动恢复”的证明。

### 15.3 队列、事件和任务状态：三套机制不能混称

#### Celery 是跨进程任务投递，不是全部运行状态

`@shared_task(queue=...)` 显示出明确的队列分域：`dataset`/`priority_dataset`、`pipeline`/`priority_pipeline`、workflow execution、`mail`、`plugin`、`conversation`、`schedule_executor`、`trigger`、`workflow_storage`、`enterprise_telemetry` 等。异步工作流按 professional/team/sandbox tier 选择队列；文档索引、RAG pipeline、邮件、归档和 provider refresh 也各有队列。

异步 workflow 的源码顺序为：

```text
AsyncWorkflowService
  → WorkflowTriggerLog(PENDING)
  → quota reserve / rate-limit decision
  → queue dispatch + celery_task_id + QUEUED
  → task 读取 trigger_data
  → RUNNING 并 commit
  → 释放 DB transaction 后进入阻塞 generate()
  → TriggerPostLayer/Graph event
  → SUCCEEDED/PAUSED/FAILED + elapsed/output
```

`WorkflowTriggerLog` 字段同时保存 `queue_name`、`celery_task_id`、`retry_count`、`status`、时间和错误，状态枚举为 `pending/queued/running/succeeded/paused/failed/rate_limited/retrying`。但这些字段没有证明 broker ack、visibility timeout、worker heartbeat、fencing 或重复投递去重；`celery_task_id` 只是追踪字段，`retry_count` 也不是租约。

#### AppQueue 是实时消费队列，Agent Redis Stream 才是可回放日志

同步 App/Workflow 使用 `AppQueueManager` 的进程内 queue，把 Graph event 转为 SSE/HTTP 流；Redis key 只记录 task ownership TTL 和 stop flag。客户端断流、执行超时或 stop 会触发 abort，但进程死后内存 queue 不可 replay。

独立 `dify-agent` 使用 `RunScheduler` 的进程内 `asyncio.Task` 执行，`RedisRunStore` 只持久化：

- JSON run record：`running/succeeded/failed/cancelled` 等状态；
- 每 run Redis Stream：事件 payload 和 stream cursor；
- record/stream 共同 TTL，事件写入通过 Redis transaction 同时刷新两者。

Redis 明确不是 job queue，create-run payload 不落 Redis（因为 layer config 可能含凭证）。SSE 首先 replay `after` cursor，随后 `XREAD BLOCK` 等待新事件；事件 union 以 `run_started`、`pydantic_ai_event`、`run_succeeded`、`run_failed`、`run_cancelled` 为主，终态事件应互斥。run scheduler 仍是单进程 owner，Redis Stream 的可回放性不能推导出跨进程接管能力。

#### Dify `Events` 容器是进程内回调，不是领域事件总线

`api/events/__init__.py` 的 `Events` 是兼容外部包的最小 C# 风格事件容器：动态创建 `_EventSlot`，支持 `+=`/`-=`、同步遍历和调用分发。它没有事件 id、顺序、持久化、重试或跨进程传输语义，不应与 Graph Queue event、AppQueue 或 Redis Stream 归为同一事件系统。

### 15.4 数据库、文件和制品的事实边界

数据库是业务状态和审计投影 owner：trigger log、workflow run/node execution、message/thought、provider/tool config、UploadFile 等均有 SQLAlchemy model/repository。异步任务在阻塞 generate 前显式 `session.commit()`，避免连接长期处于 `idle in transaction`；这体现了数据库连接生命周期约束，但不提供跨 DB、broker、对象存储事务。

文件上传的真实顺序是：

```text
校验文件名/黑名单/类型/大小
  → UUID + tenant 生成 storage key
  → storage.save(key, bytes)
  → 独立 DB session INSERT UploadFile(hash/size/mime/owner/key)
  → signed URL
```

`FileService` 不把原始路径作为 storage key，记录 SHA3-256、租户、创建者角色和来源；`DatabaseFileAccessController` 查询时强制 tenant scope，end-user 还要满足本人拥有或 execution 显式 grant。`ToolFile`、`UploadFile`、Agent drive file 和 workflow node offload 是不同制品引用层：Agent drive 只保存 path-like key 到既有文件的指针，workflow 大输入/输出可转为 object storage offload 指针。

当前代码能证明访问控制、UUID key、对象存储与 DB 引用方向，不能证明 storage.save 成功后 DB commit 失败时自动删除孤儿，也不能证明 DB 成功而对象读取失败时有 repair。通用制品 owner 仍需 hash reconciliation、orphan scan、retention、取消/失败保留策略和签名 URL 失效规则。

### 15.5 服务边界与任务状态机

| 服务/进程 | 可拥有的状态 | 不应拥有的状态 | 主要边界 |
|---|---|---|---|
| Flask API | 请求上下文、同步生成协调、DB/Redis/storage 写入、SSE/Socket.IO | 插件代码、用户代码、跨进程 Agent task | `/console/api`、`/api`、`/v1`、`/openapi/v1`、inner API |
| Celery worker | 异步 task attempt、索引/邮件/工作流执行 | 永久事实的唯一来源、任意 UI 状态 | broker message → DB/domain service → projection |
| plugin daemon | 插件安装、声明、凭证调用、插件进程/环境 | API 的租户业务表和前端状态 | API key HTTP inner API |
| graphon runtime | Graph/Node/VariablePool 执行态、节点事件 | Dify API wire contract、tenant credential rows | Dify node factory/runner adapter |
| dify-agent | 当前 run 的 asyncio task、session/layer snapshot、typed stream | Celery job queue、跨进程 recovery owner | FastAPI `/runs` + Redis record/stream |
| Web/SDK/CLI | 查询缓存、展示态、调用参数和 cursor | workflow/provider/file 事实状态 | generated OpenAPI/orpc/client |

工作流 trigger 的状态图可静态确定为：

```text
PENDING → QUEUED → RUNNING → SUCCEEDED
                    ├──────→ PAUSED → resume task → RUNNING/终态
                    ├──────→ FAILED
                    └──────→ FAILED（abort/异常）
PENDING/QUEUED → RATE_LIMITED
失败重投策略 → RETRYING → QUEUED 或 FAILED
```

Agent run 则是另一套状态图：

```text
create record(running)
  → run_started
  → pydantic_ai_event* / deferred tool call
  → run_succeeded | run_failed | run_cancelled
```

两者都存在暂停/失败/取消，但状态名称、存储 owner、重试语义和事件 cursor 不同；不能通过统一字符串字段强行拼成一套已实现状态机。

### 15.6 后续失败矩阵

| 失败面 | 源码处理 | 当前能否恢复 | 主要缺口/裁决 |
|---|---|---|---|
| plugin daemon 连接/HTTP 失败 | HTTPX RequestError → `PluginDaemonInnerError`；调用方 callback/engine 决定上抛或 observation | 仅能按调用方策略重试 | 缺统一 retry budget、幂等和 daemon 运行证据 |
| plugin 路径越界/权限/凭证 | 路径预解码拒绝 `..`；API key 注入；daemon 错误按类型映射 | 参数/权限错误不应重试 | daemon 侧权限和安装生命周期仓外 |
| 工具参数非法 | `ToolParameterValidationError`；Agent 返回 observation，Workflow 重新抛出 | Agent 可让模型生成新参数；同一 payload 不应盲重试 | 两种错误语义必须保留在统一契约 |
| 工具输出含 blob/大文件 | transformer 转 `ToolFile`/`MessageFile`，并限制文件大小 | 业务层可读取引用 | storage/DB 双写补偿和 retention 未闭环 |
| provider 凭证缺失 | `ProviderTokenNotInitError`/credential validation error | 修配置后新 execution | 无跨 provider 统一健康/熔断状态 |
| provider 限流/连接中断 | graphon error 类型向上暴露，部分 model manager 支持 load balancing | 是否重试由外层策略决定 | load balancing 不等于 failover；缺 invocation idempotency |
| 节点版本/配置非法 | registry resolve 失败或二次 schema validation 失败 | 不应重试原 graph | 版本兼容、卸载和 registry snapshot 的全局一致性待验证 |
| workflow 业务失败 | Graph failed event → Queue failed event；TriggerPostLayer 写 FAILED/error | 新 trigger 可重新提交；pause 另走 resume | trigger log 不是事件账本，缺统一去重 |
| workflow 超时/客户端断流 | AppQueue listener abort、Graph limits/stop event | 原 execution 不自动续跑 | 断流后的 DB 终态需运行验证 |
| Celery worker 崩溃/重复投递 | 源码有 task id/status/retry_count；具体 broker ack 未在当前核对证明 | 依赖 Celery 配置或人工恢复 | 缺 lease/heartbeat/fencing/idempotent task claim |
| Agent 进程优雅关闭 | scheduler cancel pending tasks，写 `run_failed(reason=shutdown)` | 外部重新提交，不自动续跑 | 这是明确终态，不是 resume |
| Agent 进程突然崩溃 | asyncio task registry 丢失；Redis record 可能停在 running | 无跨进程接管 | P0：需要 recovery worker + lease/fencing |
| Redis 不可用 | 状态、stream、cursor、stop/TTL 操作失败或 best-effort 记录 | 没有可靠实时流/取消保证 | 需要降级、重连和 repair 语义 |
| DB transaction rollback | session rollback/context；部分 task 再写 FAILED | 视第二次写入是否成功 | 失败投影本身也可能失败，需 repair scan |
| storage 成功、DB 失败 | 当前顺序会留下无引用对象 | 无自动补偿证据 | P0：outbox/补偿删除/hash 对账 |
| DB 成功、storage 读取失败 | DB 引用仍存在，读取阶段报错 | 需人工/后台修复 | 制品可用性探针和保留策略缺失 |

### 15.7 后续结论与下一步优先级

后续源码事实进一步收敛为五条：

1. **插件边界是 HTTP daemon，不是可热插拔的进程内模块。** API/Agent 只持有声明、client 和受控凭证；daemon 行为必须单独验收。
2. **工具有唯一运行引擎，但有两种故障投影。** Agent observation 与 Workflow exception 都是设计语义，不能用一个“工具失败即终止”规则覆盖。
3. **节点 registry 是版本化装配点，workflow graph 只是持久化配置。** 任何通用底座都应先解析 `ComponentRef`，再创建 runtime instance，不允许节点自行反射 provider。
4. **队列、事件、状态、制品是四种不同对象。** Celery task id、Redis cursor、DB status、storage key 不能互相冒充 lease、event id、terminal owner 或 artifact transaction。
5. **最高风险仍在崩溃恢复和制品补偿。** 在引入新 worker、Agent backend 或文件管线前，应先冻结 `ExecutionEvent`、`Lease/Fencing`、`StatusProjection`、`ArtifactRef` 和 repair/reaper 契约，并用 broker/Redis/DB/storage/plugin crash 注入验证。

当前核对新增源码证据索引：`api/core/plugin/impl/base.py`、`api/core/tools/tool_manager.py`、`api/core/tools/tool_engine.py`、`api/core/model_manager.py`、`api/core/provider_manager.py`、`api/core/workflow/node_factory.py`、`api/tasks/async_workflow_tasks.py`、`api/models/trigger.py`、`api/models/enums.py`、`api/services/file_service.py`、`api/core/app/file_access/controller.py`、`api/events/__init__.py`、`dify-agent/src/dify_agent/storage/redis_run_store.py`、`dify-agent/src/dify_agent/runtime/run_scheduler.py`。

## 16. 交互线、状态机与文档质量审计

### 16.1 交互线审计结论

当前源码存在四条可区分的交互线，不能用“请求进入队列、执行、返回结果”概括：

| 交互线 | 入口到出口 | 实时性/回放 | 状态 owner | 关键边界 |
|---|---|---|---|---|
| 同步 Chat/Completion | HTTP → `AppGenerateService` → Agent/LLM → `AppQueueManager` → SSE/Socket.IO | 实时消费；进程内 queue 不具备崩溃回放 | message/thought 与请求侧运行投影 | 客户端断流、超时和 stop 都可能触发 abort；断流不等于执行已安全终止 |
| 同步 Workflow | HTTP → `WorkflowAppGenerator` → `WorkflowEntry`/Graphon → Queue event → SSE/事件查询 | 实时消费；事件落库和流式投影并行 | workflow run/node execution repository | Graph 事件、Queue 事件、DB 状态不是同一事件账本 |
| 异步 Workflow/Trigger | webhook/service API → trigger log → Celery broker → worker → workflow run → trigger/event API | 跨进程执行；事件查询依赖 DB/事件投影 | `WorkflowTriggerLog`、workflow run/node execution | Celery task id 只用于关联；源码未证明 ack、lease、heartbeat、重复投递去重 |
| Agent backend | Agent v2 node/API → `RunScheduler` → asyncio task → Redis record/Stream → polling/SSE | Redis Stream 支持 cursor replay；执行仍是进程内 | Redis run record/stream | Redis 不是 job queue；进程崩溃后 running run 无自动接管 |

前端交互也不是单一 transport：生成契约经 `packages/contracts` 和 ORPC/TanStack Query 进入 Console，legacy service/helper 仍存在；运行事件另经 SSE、Socket.IO、workflow event API 或 Agent Redis Stream adapter 暴露。文档应明确“命令提交”“状态查询”“事件订阅”“事件回放”四种动作，不能把一个 HTTP 响应描述成完整运行事实。

### 16.2 状态与暂停/恢复审计

工作流 trigger 的状态可由 `WorkflowTriggerLog` 和任务代码静态还原为：

```text
PENDING → QUEUED → RUNNING → SUCCEEDED
                     ├──────→ PAUSED → resume task → RUNNING/终态
                     ├──────→ FAILED
                     └──────→ FAILED（异常或 abort）
PENDING/QUEUED → RATE_LIMITED
```

Agent backend 使用独立状态集合：`running → succeeded|failed|cancelled`。它没有与 workflow trigger log 共享状态 owner、事件 sequence 或终态去重，因此不能从两个状态图推导出一个已实现的全局状态机。

HITL 恢复的真实顺序是：

```text
表单 token/recipient 校验
  → 校验并规范化提交数据
  → repository 原子标记 submitted
  → workflow_run_id → enqueue resume_workflow_execution
  → 读取 pause snapshot/GraphRuntimeState
  → 标记 pause resumed
  → generator.resume
  → 删除 pause entity
```

同一提交入口若携带 `conversation_id`，则转向 Agent App 的 `resume_agent_app_execution`，把人工结果作为 deferred tool result 继续会话。表单过期、全局超时和已提交状态在入队前拦截；这保证了“提交一次”语义，但恢复任务本身仍依赖 Celery 投递和 pause snapshot 可读性。pause snapshot 是可恢复的显式检查点，不是任意运行中进程的崩溃恢复机制。

### 16.3 暂停、取消与失败重试的边界

| 语义 | 当前实现 | 审计判断 |
|---|---|---|
| 暂停 | Graph pause event 持久化 runtime state；HITL 提交后 Celery resume task 恢复 | 是显式 checkpoint/resume，不是 worker 迁移或任意 crash recovery |
| 用户取消 | AppQueue stop/abort；Agent scheduler 先写 cancelled event/status 再取消 task | Agent 取消有较明确的幂等终态；同步 workflow 的 runner race 仍需运行验证 |
| 节点重试 | Graph `NodeRunRetryEvent` → Queue retry event；节点策略决定次数 | 重试是节点/Graph 语义，必须以 node execution + attempt 去重，不能等同 Celery retry |
| Agent v2 输出重试 | `OutputFailureOrchestrator` 按失败输出策略计算 retry/default/fail branch/stop；每次重试生成 distinct idempotency key | 这是业务级整节点重试，不能证明 Agent backend 本身具备跨进程恢复 |
| provider/插件重试 | 连接、5xx、限流可由外层策略选择；授权、参数和凭证缺失不应盲重试 | 当前缺少跨 provider 统一 budget、熔断、幂等和健康 owner |
| 文档/RAG 重试 | 文档 pause/retry flag 使用 Redis TTL，任务异常写 ERROR；部分摘要/连接路径有指数退避 | 属于局部业务重试；数据库与向量存储双写补偿未形成统一协议 |
| Celery 失败重投 | 看到 task id、retry_count 和失败写入；未从源码确认 broker ack/requeue/visibility timeout | 不得把 `retry_count` 或 Celery task id 写成 lease/fencing |

关键风险是“恢复”和“重试”经常共享名词但不是同一动作：恢复使用既有 pause snapshot 继续同一 workflow execution；重试应创建新的 attempt/idempotency key；崩溃接管则需要 lease、fencing、reaper 和 recovery policy。当前只有第一类在 pause 路径中有明确源码闭环。

### 16.4 队列、事件、状态、制品的分离检查

当前核对确认以下对象不能互相替代：

- Celery broker 是跨进程任务投递；不负责成为业务状态事实源。
- `AppQueueManager` 是同步执行的实时消费通道；不是持久化事件日志。
- Agent Redis Stream 是每个 run 的有 TTL 事件日志，可按 cursor replay；不是任务调度队列。
- DB status/trigger log/node execution 是状态和审计投影；没有证据表明它们可由统一 event sequence 完整重放。
- storage key、signed URL、`UploadFile`、`ToolFile` 和 workflow offload pointer 是不同制品引用；都不能充当执行 lease 或事务提交凭证。

这条分离是当前架构最重要的正确性约束。若未来统一运行底座，应先定义唯一 `ExecutionEvent` append owner、`execution_id + attempt` 幂等键、终态互斥规则和 `Lease/Fencing`，再改 Celery、Agent scheduler 或 SSE adapter。

### 16.5 文档质量审计

**优点：** 根 README 对产品定位、自托管入口和主要能力清楚；`AGENTS.md` 对后端、前端、Agent、CLI 的边界和测试规则较具体；`docs/design/human-in-the-loop/hitl-form-file-upload-design.md` 能解释文件 owner 与恢复路径的设计取舍；本文件已将源码事实、外部依赖和未验证项分开，并给出关键路径索引。

**缺口：**

1. 根 README 是产品/部署导览，不是运行时架构说明；没有描述四条交互线、状态 owner、暂停 snapshot、Celery/Redis 的不同语义。
2. `docs/` 以多语言 README、合规说明和少数专题设计文档为主，缺少一份与当前代码版本绑定的后端运行时、队列拓扑、失败恢复和数据生命周期文档。
3. API wire contract、generated contract、legacy service helper 与 Console ORPC client 的关系分散在代码和规则文件中，读者难以判断哪个是新增接口的唯一 owner。
4. Graphon、plugin daemon、vector/trace provider 属于外部边界；仓库文档能说明调用方，却不能单独证明版本兼容、ack/retry、权限执行和资源关闭，必须显式链接 pinned version、协议和运行验证。
5. 测试目录覆盖面很广，但静态存在不等于通过；文档应把“测试源码覆盖”“本地执行通过”“容器/E2E 通过”三种证据分栏记录。

**文档维护建议：** 以后每次改变队列、状态、暂停/恢复、重试或 provider 装配时，必须同步更新本文件的交互线表、状态图、失败矩阵和证据索引；涉及外部服务时追加运行验证结果或明确保留为 S0/S1 未验证，不把配置字段、task id 或 TTL 猜测为可靠性保证。

### 16.6 当前核对最终裁决与优先级

1. **P0：** 为 workflow、Celery task 和 Agent run 冻结统一 execution/lease/fencing/recovery 契约；在此之前不宣称跨进程 crash-safe。
2. **P0：** 为 storage + DB 双写增加 outbox/补偿删除/hash 对账和 orphan scan，并定义失败/取消后的制品 retention。
3. **P1：** 为 Graph event、AppQueue、workflow DB、Agent Redis Stream 建立统一 event id/sequence/attempt/idempotency 规则，补 projection repair。
4. **P1：** 对 plugin daemon、Graphon、Redis/Celery broker 做隔离运行测试，覆盖超时、断流、重复投递、worker crash、恢复和资源关闭。
5. **P2：** 把上述交互线和状态 owner 提炼为版本化架构文档，并在 API/worker/Agent/前端入口增加链接，降低仅靠源码考古的维护成本。

本节仍是源码与文档静态审计。没有安装依赖、启动服务、连接 DB/Redis、运行 Celery、调用 plugin daemon、执行测试或做 E2E；因此所有运行态结论仍不得标记为通过。

## 17. 2026-08-22 源码级整项目复核（当前最新版）

### 17.1 版本、规模与代码地图证据

本轮在 Dify 根目录直接复核，而不是只依赖既有 Markdown：

| 项目 | 当前证据 |
|---|---|
| Git | `HEAD=main=a9b8c84e9be41376c04901e81ce690f35c1ffe86`；`origin/main` 同值；领先/落后 `0/0` |
| 受版本控制文件 | 13,470 个（`git ls-files`） |
| 主要代码规模 | `api` 3,771；`web` 7,631；`dify-agent` 269；`dify-agent-runtime` 72；`packages` 887；`cli` 362；其余目录 478 |
| 主要语言/文件 | TSX 4,344；Python 3,817；TS 2,427；Go 65；JS 117；YAML/YML 122；JSON 1,350 |
| CodeGraph | 10,905 files / 215,860 nodes / 671,426 edges；Python、TypeScript、TSX、Go、YAML 等均已索引；状态 `up to date` |
| 工作树 | 源码侧仅有未跟踪 `.codegraph/` 与 `ARCHITECTURE.md`；本轮不修改源码、不把二者算作发布文件 |

CodeGraph 查询 `create_app AppGenerateService WorkflowBasedAppRunner ToolEngine DifyNodeFactory RunScheduler RedisRunStore` 返回 12 个核心符号及调用者/测试覆盖：API `create_app` 位于 `api/app_factory.py:157`，Agent 服务 `create_app` 位于 `dify-agent/src/dify_agent/server/app.py:42`；`RunScheduler` 位于 `dify-agent/src/dify_agent/runtime/run_scheduler.py:94`；`RedisRunStore` 位于 `dify-agent/src/dify_agent/storage/redis_run_store.py:146`。该查询是本轮的代码地图证据，具体结论仍以当前文件行号复读为准。

### 17.2 当前真实启动链（前端到后端）

```text
浏览器 / 嵌入 WebApp / difyctl / SDK
        │
        ├─ Console React/Next 页面与 TanStack Query
        │    └─ web/service/client.ts
        │         ├─ @orpc/openapi-client OpenAPILink
        │         ├─ @dify/contracts 生成的 TypeScript 类型
        │         └─ web/service/base.ts request / ssePost / sseGet / sseGeneratorPost
        │
        ├─ /console/api、/api、/v1、/openapi/v1、/files、/mcp、/trigger
        │
        ▼
api/app.py:69-73 → app_factory.create_app()
  → create_flask_app_with_configs()
  → initialize_extensions()（数据库、Redis、storage、Celery、login、FastOpenAPI、OTel）
  → ext_blueprints.init_app()（八组 Blueprint）
  → Socket.IO WSGI wrapper / gevent WebSocket server
        │
        ▼
Controller DTO/认证/租户/RBAC/CSRF/license
  → AppGenerateService.generate()
  → WorkflowBasedAppRunner / Agent runner / ModelManager / ToolEngine
  → Graphon event / AppQueue / DB projection / SSE 或 Socket.IO
        │
        ├─ 异步 trigger → WorkflowTriggerLog → Celery broker → worker → DB 状态
        ├─ 插件/模型/MCP → plugin daemon 或 provider HTTP 边界
        └─ Agent v2 → dify-agent FastAPI → RedisRunStore + RunScheduler → Redis Stream/SSE
```

`api/app_factory.py:157-168` 明确先构造 Flask 应用、初始化扩展，再套 `socketio.WSGIApp`；`api/app_factory.py:171-245` 的扩展顺序说明数据库、Redis、storage、key provider、logstore 在 Celery 之前就绪，blueprint 在认证与基础设施之后注册。`api/extensions/ext_blueprints.py:27-120` 当前注册 `service_api`、可选 `openapi`、`web`、`console`、`files`、`inner_api`、`mcp` 和 `trigger`，并为公开/嵌入/控制台路径分别设置 CORS 与认证头，不能将所有 HTTP 面当成同一权限域。

### 17.3 前端契约与流式传输的当前实现

- `web/service/client.ts:19-30,75-95` 使用 `OpenAPILink` 把 `@dify/contracts/console` 路由映射到 `API_PREFIX`，请求统一经 `web/service/base.ts` 的 `request`；这意味着前端接口的类型 owner 是 `packages/contracts` 的生成文件，而不是任意页面内手写 fetch。
- `packages/contracts/package.json` 的 `gen-api-contract` 先运行 `api/dev/generate_swagger_specs.py` 与 `generate_fastopenapi_specs.py`，再由 `openapi-ts` 生成 `packages/contracts/generated/api`；契约变更实际是“后端 schema → 生成 TypeScript → 前端 client”链路。
- `web/service/base.ts:550-810` 的 `ssePost`/`sseGet` 处理 chat、workflow、human-input 等 SSE；`web/service/base.ts:900-941` 的 `sseGeneratorPost` 专门处理 `/workflow-generate/stream`，对跨 chunk JSON frame 进行重组。SSE 断开、错误通知、完成回调是前端消费语义，不能反推后端执行已取消或已提交终态。
- `web/app/layout.tsx` 与 `web/app/(commonLayout)` 是页面宿主；大量 `web/features` 和 `web/app/components/workflow` 只是 UI/状态投影，运行事实仍由 API/DB/事件流提供。
- `cli/package.json` 的 `difyctl` 版本为 `0.2.0-alpha`，兼容 Dify `1.16.0–1.16.1`；其依赖同一 `@dify/contracts`，并用 `eventsource-parser` 消费流式结果。CLI 不是第二套 API 契约。

### 17.4 Agent App 新增事实（不能沿用旧 Agent 结论）

当前 `api/services/app_service.py:503-655` 的 `create_app` 在 `AppMode.AGENT` 下创建独立 `AppModelConfig`，再调用 `AgentRosterService.create_backing_agent_for_app`，并在同一事务中写入 App 与 backing Agent；注释明确该新 Agent App 与旧 function-call/ReAct `agent_mode` 不同。控制台 agent roster 路由位于 `api/controllers/console/agent/roster.py:563-1184`，包含 publish、draft checkout/apply、版本、日志、API access 与 key 管理。

```text
AppMode.AGENT 创建
  → App + 空壳 AppModelConfig
  → backing Agent（同事务、app_id 1:1）
  → Composer 配置 Agent Soul（model/prompt/tools）
  → draft checkout / apply / publish
  → Agent API access / logs / versions
```

这条链说明 Dify 当前同时存在 legacy Agent 与新 Agent App 两种模型；底座映射时必须保留 `AppMode.AGENT`、roster Agent、workflow Agent node 和 dify-agent backend 的不同 owner，不能把它们压平为一个“Agent 模块”。

### 17.5 Agent backend 的当前生命周期与资源边界

`dify-agent/src/dify_agent/server/app.py:42-151` 当前 FastAPI app 在 lifespan 中创建一个 Redis client、一个 `RedisRunStore`、一个 `RunScheduler`、一个 plugin daemon HTTP client 与一个 Dify inner API HTTP client；`finally` 块按 scheduler → HTTP clients → Redis 顺序关闭（同文件 `:119-125`）。`_create_shared_http_client` 在 `:175-185` 设置 outbound timeout、连接池上限、keepalive 和 `trust_env=False`。

`dify-agent/src/dify_agent/server/routes/runs.py:44-109` 的控制面是：

| HTTP | 实际动作 |
|---|---|
| `POST /runs` | 交给本地 `RunScheduler.create_run`，返回 `202` 与 run id/status |
| `GET /runs/{id}` | 从 Redis 读取状态/时间/错误 |
| `POST /runs/{id}/cancel` | scheduler 持久化取消，owner task 观察并停止 |
| `GET /runs/{id}/events` | 按 Redis Stream cursor 分页 |
| `GET /runs/{id}/events/sse` | `after` 或 `Last-Event-ID` 后 replay，再持续流式读取 |

该服务仍然是“单进程调度器 + Redis 状态/事件日志”：HTTP client 的关闭边界已明确，但没有跨进程 scheduler 接管、lease/fencing 或 broker redelivery 证据。Redis Stream 的可回放性不等于执行任务的可恢复性。

### 17.6 版本变化和证据更新裁决

与本文早期基线 `8ef002f6` 相比，本轮确认仓库已前进到 `a9b8c84e`；旧文档中所有“当前提交”表述均以本节和顶部元数据为准。当前源码还显示：

1. 前端已采用 `@orpc/openapi-client` + 生成 contracts 的明确契约链，不能继续只写“legacy helper + fetch”。
2. `AppMode.AGENT` 的 backing roster/Composer/publish/version 体系已是正式路径，应与 legacy Agent、Workflow Agent node、dify-agent backend 分开记录。
3. `dify-agent` lifespan 已显式管理共享 HTTP client、Redis、scheduler 的关闭顺序，文档可以确认资源 owner，但仍不能宣称崩溃恢复。
4. Dify 根目录 CodeGraph 已覆盖全量多语言文件；后续探索应优先复用该索引，只有索引未覆盖或代码指纹变化时才直接逐文件读取。

### 17.7 本轮验证边界

已执行且可复核：

- Dify 根目录 `git fetch origin main`、`git rev-list --left-right --count HEAD...origin/main`：`0 0`；
- Dify 根目录 `codegraph status`：索引 `up to date`；
- Dify 根目录 `codegraph explore 'create_app AppGenerateService WorkflowBasedAppRunner ToolEngine DifyNodeFactory RunScheduler RedisRunStore'`：退出码 `0`；
- 文件统计、入口行号与当前源码回读；
- 本文件 Markdown/结构修改后将执行 `git diff --check`（平台仓库）与章节/流程图检查。

未执行：API/Agent 依赖安装、数据库迁移、Redis/Celery、plugin daemon、模型 provider、Docker、前端构建、单元测试、集成测试和 E2E。故本文所有运行态、性能、故障恢复与外部服务兼容性结论仍标为“源码已见、运行未证”。
