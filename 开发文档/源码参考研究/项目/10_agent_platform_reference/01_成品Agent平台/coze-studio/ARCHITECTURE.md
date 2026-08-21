# Coze Studio 架构建档

> 项目根目录：`/Users/hekunhua/Documents/Agent/github 源码参考/10_agent_platform_reference/01_成品Agent平台/coze-studio`
>
> 本文是基于仓库现存文件的首轮静态架构记录，不把设计文档或 README 当作运行时证明。

## 1. 项目定位

Coze Studio 是一站式 AI Agent 开发平台，覆盖 Agent、App、Workflow、插件、知识库、数据库、提示词及对外 API/Chat SDK。仓库是前后端同仓的多项目结构：后端以 Go 微服务和 DDD 分层为主，前端以 React + TypeScript 的 Rush.js monorepo 为主。

README 明确的产品边界包括：模型服务、Agent 构建、App 构建、Workflow 编排、资源管理、聊天与 Workflow API/SDK。公开部署入口默认是 `http://localhost:8888/`；公开网络部署前需要额外评估注册、代码节点执行、SSRF 和越权风险。

## 2. 总体文本流程图

```text
开发者 / 管理员 / 外部业务系统
        │
        ├─ React + TypeScript 前端（Rush.js / Rsbuild）
        │      ├─ Agent IDE、Studio 工作区
        │      ├─ Workflow 可视化画布（FlowGram 相关包）
        │      ├─ 资源/发布/执行历史 UI
        │      └─ Open Platform / Chat SDK 消费端
        │
        └─ HTTP / OpenAPI / Chat SDK 请求
               │
               ▼
        Hertz HTTP Server（backend/main.go）
               │  env → application.Init → middleware → GeneratedRegister
               ▼
        API / Router 层
          ├─ Thrift 生成的 API 模型与服务处理器
          ├─ 请求鉴权、会话、CORS、日志、国际化中间件
          └─ `/api/...` 内部工作台 API 与 `/v1/...` Open API
               │
               ▼
        Application 层
          └─ 用例编排：创建/保存/发布/测试运行/恢复/取消/查询
               │
               ▼
        Domain 层（DDD）
          ├─ workflow / agent / app / plugin / knowledge / prompt / memory
          ├─ Workflow Service + Repository 接口
          ├─ Canvas → Workflow Schema → eino Compose Workflow
          └─ WorkflowAsModelTool：把已配置 Workflow 暴露为模型工具
               │
               ▼
        Infra / Crossdomain / Bizpkg
          ├─ eventbus、SSE、checkpoint、cache、ID 生成
          ├─ MySQL/Redis/ES/Milvus/MinIO/消息队列等适配
          ├─ 模型提供者（OpenAI、Ark、Claude、Gemini、Qwen、DeepSeek、Ollama）
          └─ 跨领域消息、资源、权限、存储、追踪
               │
               ▼
        执行事件 / Span / 持久化
          ├─ workflow/node/tool 事件流
          ├─ 中断事件与 ResumeData
          ├─ 执行历史与 trace 查询
          └─ DB / VCS / External 三种 Workflow PersistenceModel
```

## 3. 真实代码分层与职责

### 3.1 后端入口与横切层

- `backend/main.go`：生成式 Hertz 入口；按固定顺序加载环境、设置日志、调用 `application.Init`，创建 HTTP Server，并注册中间件和路由。
- `backend/api/middleware/`：当前入口明确使用 ContextCache、RequestInspector、Host、LogID、CORS、AccessLog、OpenAPI Auth、Session Auth、I18n；中间件顺序有明确约束。
- `backend/api/router/`：生成路由注册；`backend/api/router/coze/api.go` 将生成服务绑定至实际路径。
- `backend/api/model/`：Thrift/HTTP 生成的请求、响应、枚举和数据模型。
- `backend/pkg/`：错误、日志、序列化、指针/切片等横切工具，不承担领域业务。

### 3.2 API / Application / Domain

- `backend/api/`：API 合约、生成处理器和路由适配；不是工作流核心状态机。
- `backend/application/`：应用服务和跨领域用例编排；`application.Init` 是基础设施与服务装配入口。
- `backend/domain/`：领域实体、领域服务、Repository 接口和具体领域流程。已确认的主要域包括 workflow、agent、app、plugin、knowledge、prompt、search、memory 等。
- `backend/crossdomain/`：跨领域模型/服务，例如 Workflow 执行配置、消息模型。
- `backend/infra/`：基础设施实现，包括事件总线、SSE、checkpoint、缓存、ID 生成、数据库/文档/向量等适配。
- `backend/bizpkg/`：可复用业务包，已从工作流实现中看到 LLM model builder 等依赖。

### 3.3 Workflow 领域的真实子层

`backend/domain/workflow/interface.go` 显示 Workflow Service 组合了 `Executable`、`AsTool`、对话、ChatFlowRole 等接口；Repository 同时承载元数据、版本、草稿、快照、引用、执行历史、InterruptEvent、CancelSignal、Checkpoint、对象存储 URL 与模型等端口。

- **领域接口**：`Service` 提供创建、保存、查询、删除、发布、复制、校验树、查询引用、释放 App Workflow 等操作；`Repository` 提供元数据/版本/草稿/快照/引用/执行历史/中断/取消/检查点等持久化能力。
- **可执行实现**：`backend/domain/workflow/service/executable_impl.go` 的同步执行路径为：按 ID/来源/版本/CommitID 读取 Workflow → 解析 Canvas JSON → `CanvasToWorkflowSchema` → 收集文件字段 → `compose.NewWorkflow` → 转换输入 → `compose.NewWorkflowRunner(...).Prepare` → eino `SyncRun` → 消费最后事件 → 将状态、输出、错误、Token 使用量、中断事件组装为 `WorkflowExecution`。
- **异步执行**：同一实现文件还提供 `AsyncExecute`，返回执行 ID，调用方再通过执行查询接口轮询状态；异步中间结果不直接在调用返回中发出。
- **Workflow 作为模型工具**：`service/as_tool_impl.go` 的 `WorkflowAsModelTool` 遍历策略，经 Repository `WorkflowAsTool` 构造工具；`WithExecuteConfig` 将执行配置注入 eino tools node；`WithResumeToolWorkflow` 将 `toolCallID → ExecuteID` 映射和 `ExecuteID/EventID/ResumeData` 封装为 Resume 选项。
- **执行事件**：`internal/execute/event.go` 定义工作流、节点、函数调用、工具响应四级事件，包括 start/success/failed/cancel/interrupt/resume、node streaming/error、function/tool error，以及 Input/Output、Answer、Token、Duration、Err、InterruptEvents 等上下文。
- **编排引擎**：仓库已有证据显示 Workflow 通过 CloudWeGo eino compose 图执行；`internal/compose/` 负责 Workflow 构造和 Runner，`internal/nodes/` 负责节点输入转换与节点能力接入。

## 4. 数据流与状态流

### 4.1 Workflow 创建/保存/发布

```text
前端画布或 API 请求
  → Thrift 请求模型（name/desc/schema 等）
  → Hertz 处理器/Workflow Service
  → Repository 元数据、草稿、版本、引用
  → WorkflowSchemaCheck / ValidateTree / CheckResult
  → PublishWorkflow
  → 已发布版本供正式运行或 Open API 调用
```

IDL 中可确认 `CreateWorkflow`、`SaveWorkflow`、`UpdateWorkflowMeta`、`DeleteWorkflow`、`CopyWorkflow`、`PublishWorkflow`、`GetReleasedWorkflows`、`GetWorkflowReferences` 等工作流面操作。`PersistenceModel` 枚举为 `DB`、`VCS`、`External`；当前应用层读取 Workflow 时可见 `PersistenceModel_VCS` 的返回赋值，具体各模式的完整持久化选择逻辑仍需进一步细探。

### 4.2 一次 Workflow 执行

```text
ExecuteConfig + input
  → Repository.GetEntity / Get(policy: ID, From, Version, CommitID)
  → Canvas JSON 反序列化
  → CanvasToWorkflowSchema
  → eino compose.NewWorkflow
  → nodes.ConvertInputs（文件字段、FailFast、输入警告）
  → NewWorkflowRunner.Prepare（executeID、cancelCtx、opts、事件通道）
  → SyncRun / AsyncRun
  → workflow/node/tool 事件
  → 最后事件决定 Success / Failed / Cancel / Interrupt
  → WorkflowExecution（output、duration、token、error、interrupt）
  → Repository/执行历史/trace 查询
```

### 4.3 中断与恢复

```text
工具或节点触发 Interrupt
  → 记录 ExecuteID + EventID + InterruptEvents
  → 返回给测试运行/调用方
  → 调用 TestResume 或 StreamResume 携带 ResumeData
  → toolCallID2ExecuteID 解析历史工具调用
  → eino WithResume
  → 从对应执行上下文恢复
```

恢复参数的代码证据为 `entity.ResumeRequest{ExecuteID, EventID, ResumeData}`，并通过 `toolCallID2ExeID` 将所有中断工具调用映射到执行 ID。

### 4.4 执行历史与 Trace

`trace.thrift` 的 `ListRootSpansRequest` 至少包含 `StartAt`、`EndAt`、`WorkflowID`，并支持 `Limit`、`Offset`、按开始时间倒序、输入过滤、`SpanStatus` 和 `ExecuteMode`。`SpanStatus` 为 Unknown/Success/Fail；`ExecuteMode` 注释区分正式运行、演练运行和节点调试。返回的 Span 包含 TraceID、SpanID、ParentID、名称、耗时、开始时间、状态码和标签。

## 5. API、CLI、SDK 与生成契约

### 5.1 Workflow 工作台 API

真实 API 路径来自 `idl/workflow/workflow_svc.thrift` 的 `api.post`/`api.get` 注解，主要包括：

- `POST /api/workflow_api/create`
- `POST /api/workflow_api/canvas`
- `POST /api/workflow_api/history_schema`
- `POST /api/workflow_api/save`
- `POST /api/workflow_api/update_meta`
- `POST /api/workflow_api/delete`、`/batch_delete`
- `POST /api/workflow_api/publish`
- `POST /api/workflow_api/copy`
- `POST /api/workflow_api/test_run`
- `POST /api/workflow_api/test_resume`
- `POST /api/workflow_api/cancel`
- `GET /api/workflow_api/get_process`
- `GET /api/workflow_api/get_node_execute_history`
- `POST /api/workflow_api/list_spans`
- `POST /api/workflow_api/get_trace`
- `POST /api/workflow_api/validate_tree`
- `POST /api/workflow_api/list_publish_workflow`

IDL 同时定义文件上传授权、图片 URL、会话、节点调试和应用发布相关接口；完整工作流服务方法清单以该 Thrift 文件为准。

### 5.2 Open API 与 Chat SDK

IDL 中确认的对外 Workflow API 包括：

- `POST /v1/workflow/run`
- `POST /v1/workflow/stream_run`
- `POST /v1/workflow/stream_resume`
- `GET /v1/workflow/get_run_history`
- `POST /v1/workflows/chat`
- `GET /v1/workflows/:workflow_id`
- `POST /v1/workflow/conversation/create`

README 将对话、聊天、Workflow API 和 Chat SDK 作为公开集成能力；具体 Personal Access Token 校验、Open API handler 到领域服务的逐方法调用链，当前仅确认了 IDL/生成接口和入口中间件，尚未逐项核实。

### 5.3 CLI / 运维入口

仓库没有发现根 `package.json` 或根 `go.mod`；前端由根 `rush.json` 管理，后端模块位于 `backend/go.mod`。已确认的命令入口来自 `Makefile`：

- `make middleware`：启动开发中间件 Docker profile
- `make server` / `make build_server`：构建或启动 Go 后端
- `make fe`：执行前端构建脚本
- `make debug`：环境、中间件、Python、服务组合启动
- `make web`：Docker 完整 Web 环境
- `make sync_db`、`make dump_db`、`make sql_init`、`make atlas-hash`
- `make down`、`make down_web`、`make clean`

本轮只读取命令定义，未执行任何启动、构建、安装或数据库命令。

### 5.4 前端包与 SDK 入口

`frontend/apps/coze-studio/package.json` 确认主应用是 `@coze-studio/app`，使用 React 18、React Router、Zustand；开发/构建由 Rsbuild，测试由 Vitest。应用依赖多个 `workspace:*` 包，包括 `@coze-project-ide/main`、`@coze-studio/api-schema`、Studio workspace 包、Workflow playground adapter 和基础设施包。`frontend/packages/workflow/sdk/README.md` 存在，说明 Workflow SDK 是独立前端包边界；具体导出符号和浏览器调用协议未在本轮展开。

## 6. 技术栈与基础设施

| 层 | 已确认技术 |
|---|---|
| 后端语言 | Go；`backend/go.mod` 声明 Go 1.24.0 |
| HTTP | CloudWeGo Hertz 0.10.2 |
| API 契约 | Apache Thrift IDL；注解生成 API 路由、Go 模型与服务代码 |
| Agent/Workflow 执行 | CloudWeGo eino 0.4.8 与 compose |
| 前端 | React 18、TypeScript 5.8、React Router、Zustand |
| 前端工程 | Rush 5.147.1、pnpm 8.15.8、Node >=21、Rsbuild/Rspack |
| UI/CSS | Semi Design、Tailwind CSS（仓库指导文档确认） |
| 数据库 | MySQL；GORM、Atlas 迁移工具相关脚本；OceanBase compose 变体 |
| 缓存 | Redis |
| 搜索 | Elasticsearch（含 SmartCN 配置说明） |
| 向量检索 | Milvus |
| 对象存储 | MinIO、AWS S3 SDK、Volcengine TOS SDK |
| 消息 | NSQ、RocketMQ、Pulsar、NATS 相关 Go 依赖/配置 |
| 配置/部署 | dotenv、Docker Compose、Helm |
| 流式/事件 | SSE、事件总线、checkpoint；具体实现分布在 `backend/infra/` |
| 测试 | Go `testing`/Testify/Gomock/Mockey；前端 Vitest |

README/CLAUDE 与实际 `backend/go.mod` 存在版本口径差异：指导文档写 Go >=1.23.4，而模块声明为 Go 1.24.0；以当前代码模块文件为本仓库构建约束。

## 7. 测试与验证结构

- 后端测试使用 Go 原生测试生态；当前可见 `backend/domain/workflow/service/executable_impl_test.go`，采用 `testing`、Testify、Gomock、生成 Mock 和跨领域消息 Mock，覆盖执行实现内部逻辑和错误/历史场景。
- `backend/api/handler/coze/workflow_service_test.go` 存在工作流服务 API 测试，已检索到 `TestListWorkflowAsToolData` 等用例。
- 前端主应用脚本为 `vitest --run --passWithNoTests` 与 coverage 变体；Rush 指导命令是 `rush test`、`rush lint`。
- CLAUDE.md 给出按 Rush level 的覆盖率目标：Level 1 80%（增量 90%）、Level 2 30%（增量 60%）、Level 3/4 灵活；该覆盖率策略未在本轮执行工具核实。
- IDL 生成代码位于 `backend/api/model/` 等目录；代码生成链和生成命令未在本轮执行确认。
- 本轮未安装依赖、启动服务、构建、运行测试或访问数据库；因此本文不宣称当前分支测试通过，也不宣称部署可用。

## 8. 关键路径索引

| 关注点 | 证据路径 |
|---|---|
| 项目定位/部署 | `README.md` |
| 仓库工作规约/分层概述 | `CLAUDE.md` |
| 架构证据 | 本文件；源码路径以本文件各章节为准 |
| Rush monorepo 根配置 | `rush.json` |
| 后端依赖与模块版本 | `backend/go.mod` |
| 构建、启动、Docker、数据库命令 | `Makefile` |
| Go HTTP 入口与中间件顺序 | `backend/main.go` |
| Workflow API/生成服务 | `idl/workflow/workflow_svc.thrift`、`backend/api/model/workflow/workflow_svc.go` |
| Workflow 数据模型与 PersistenceModel | `idl/workflow/workflow.thrift`、`backend/api/model/workflow/workflow.go` |
| Workflow 服务/Repository 端口 | `backend/domain/workflow/interface.go` |
| 同步/异步执行 | `backend/domain/workflow/service/executable_impl.go` |
| WorkflowAsModelTool/恢复选项 | `backend/domain/workflow/service/as_tool_impl.go` |
| 事件枚举与事件负载 | `backend/domain/workflow/internal/execute/event.go` |
| Trace 请求/Span 模型 | `idl/workflow/trace.thrift` |
| 前端主应用与脚本 | `frontend/apps/coze-studio/package.json` |

## 9. 未确认项与后续细探边界

1. `application.Init` 的完整服务装配图、配置加载和 Repository 实例绑定尚未逐层展开。
2. `CanvasToWorkflowSchema`、`compose.NewWorkflow`、`NewWorkflowRunner` 与各节点实现的完整调用图尚未展开；本文只记录已读取的执行入口事实。
3. Workflow Repository 的 DB/VCS/External 三模式如何选择、版本/草稿/快照的实际表结构和事务边界尚未确认。
4. MySQL、Redis、Elasticsearch、Milvus、MinIO、NSQ/RocketMQ 等组件的生产必需性、连接参数和启动依赖未通过运行环境核实。
5. Trace/Span 的具体落库实现、SSE 事件订阅端和执行历史写入时机未完全确认。
6. Open API/Chat SDK 的认证、限流、错误码、请求体和 handler→domain 逐方法链路需要继续读取 IDL 及对应 handler。
7. 根目录没有 `package.json`/`go.mod`；前端/后端是独立子项目，其他语言脚本和 Python setup 的职责尚未详查。
8. `rush.json` 声明的完整前端包数、层级依赖和各 package 的实际依赖图本轮未重新统计；CLAUDE.md 的“135+”是指导文档口径。
9. 公开部署的安全风险是 README 的警告，不等于已完成安全审计；尤其 Python 代码节点、SSRF、注册和横向越权仍需单独验证。
10. 本轮专属 MCP 绑定存在环境问题：`project_context` 返回的是非目标 `华世王镞_v3`/`project_toolkit`，`codegraph_explore` 报告目标缺少 `.codegraph/` 索引；因此本文件的目标仓库证据来自直接静态读取，而不是代码地图结果。

## 10. 本轮范围与变更纪律

本文件已吸收此前 `细探-coze-studio.md` 的源码分析结论；后续只维护本文件，旧细探笔记不再作为独立事实源。
仅新增/更新本项目根目录 `ARCHITECTURE.md`。未改源码、依赖清单、测试、配置或 README；未安装依赖；未启动服务；未构建；未提交 Git。

---

# 第三轮：通用底座映射、组件契约与执行生命周期

> 本章是基于当前磁盘源码的第三轮增量，不把 Coze Studio 直接复制为系统工程平台。映射目标是提取可复用的公共契约、模块编排、运行核心和统一网关边界；没有运行时验证的内容明确标为“静态已见/待实测”。

## 11. 第三轮结论与唯一链路

### 11.1 总体归属

```text
可视化节点/插件/工作流定义
  → 前端 WorkflowNodeRegistry + FlowGram WorkflowJSON + 表单契约
  → Hertz/Thrift handler（参数校验、鉴权、OpenAPI/SSE边界）
  → Application Service（创建/保存/发布/测试运行/恢复/取消用例）
  → Domain Service + Repository（元数据、草稿、版本、引用、执行历史）
  → CanvasToWorkflowSchema + NodeAdaptor/NodeBuilder
  → eino compose Workflow/Runner（依赖图、输入转换、checkpoint、事件、状态）
  → 模型/插件/知识/数据库节点的公开领域接口
  → GORM/MySQL、Redis、TOS、向量/搜索、事件总线或外部 HTTP
  → JSON/执行记录/中断事件/SSE/Trace
```

四层底座裁决：

| 当前能力 | 通用支持库 | 模块库 | 运行核心 | 统一网关 |
|---|---|---|---|---|
| 节点 ID、类型、字段、结果、错误码、输入输出类型 | 类型/序列化/错误/ID/上下文/观测契约 | 工作流节点目录、表单与节点适配模块 | schema 编译、依赖解析、节点监督、事件状态 | 节点元数据、校验、调试 API |
| 插件、Tool、OpenAPI 参数 | OpenAPI/HTTP/鉴权/Token/重试契约 | 插件注册、版本、OAuth、Tool 执行模块 | Tool 调用、超时、Interrupt/Resume、错误归一化 | 插件开发/发布/执行路由 |
| Workflow Canvas/草稿/版本/发布 | JSON schema、版本与引用契约 | 工作流编辑、保存、发布、复制、依赖资源模块 | Compose 图、Runner、checkpoint、执行历史 | CRUD、TestRun、OpenAPI Run、SSE |
| 模型、知识、数据库、文件 | Provider 接口、资源/文件/Token 契约 | Model builder、知识检索、数据库节点、文件节点 | 调用预算、fallback、重试、取消和运行事件 | 模型配置、节点参数和执行查询 |
| 任务、取消、进度 | TaskID、状态机、截止时间、幂等键 | 复制/索引/发布/后台任务编排 | `context`、`errgroup`、队列消费、恢复、回收 | task status/cancel/retry/progress API |
| DB、Redis、对象存储、消息队列 | 驱动抽象、连接/事务/消息契约 | 各领域 Repository 与 eventbus 适配 | checkpoint、状态 CAS、事件投影和资源治理 | 不得直连基础设施，只暴露安全结果 |
| 前端画布、编辑器、部署 | fetch/SSE/Disposable/客户端错误契约 | FlowGram、节点表单、自动保存、IDE 插件 | 不承载服务端执行状态，只消费事件/结果 | 静态文件、HTTP、TLS、认证、部署入口 |

### 11.2 单能力单入口原则在本仓库的落点

1. **节点注册的唯一公开入口**：前端以 `WorkflowNodeRegistry` 提供类型、元数据、表单、输入输出和生命周期钩子；后端以 `RegisterNodeAdaptor`/`GetNodeAdaptor` 将画布节点转换为 `NodeSchema`，运行时再由 `NodeBuilder.Build` 生成可调用节点。业务代码不能绕过这些入口直接从 Canvas 拼 Eino 图。
2. **插件 Tool 的唯一执行入口**：工作流插件节点最终调用 `crossplugin.DefaultSVC().ExecuteTool`；`pluginServiceImpl.ExecuteTool` 统一做 executor、OAuth、真实执行、响应裁剪和可选响应 schema 生成。不同执行场景在 `buildToolExecutor` 内选择，不应由每个节点复制 HTTP/OAuth 流程。
3. **Workflow 的唯一执行入口**：`SyncExecute`、`AsyncExecute`、`StreamExecute` 和 `AsyncExecuteNode` 共享“读取版本 → 反序列化 Canvas → 转 Schema → 构图 → 输入转换 → Runner.Prepare”的链路；同步、异步、流式只是终态交付方式，不是三套执行内核。
4. **状态与证据的权威 owner**：工作流执行写 `WorkflowExecution`/`NodeExecution`，中断和取消分别由 `InterruptEventStore`/`CancelSignalStore` 维护；其他层只能调用 Repository/Domain Service，不能旁路改表或直接改 Redis key。
5. **统一网关不承担领域编排**：`backend/api/router/coze/api.go` 只把生成路由绑定到 handler；handler 只做 BindAndValidate、调用 Application Service、转换 JSON/SSE。公共网关层不应承载节点注册、模型选择或数据库事务。

### 11.3 第三轮裁决

| 模式 | 裁决 | 证据与边界 |
|---|---|---|
| `WorkflowNodeRegistry` 的元数据/表单/生命周期契约 | **吸收** | `frontend/packages/workflow/base/src/types/registry.ts:55-184` 已形成可迁移的九要素雏形；需去除 FlowGram 类型耦合后进入通用组件契约。 |
| 前端 `createNodeRegistry` 的字段必填、变量标签和提交前归一化 | **吸收** | `frontend/packages/workflow/playground/src/nodes-v2/chat/create-node-registry.ts:56-131`；`beforeNodeSubmit` 是参数契约的最后归一化点。 |
| 后端 `NodeAdaptor` 注册表 | **升级后吸收** | `backend/domain/workflow/internal/nodes/node.go:151-188` 有注册/获取，但 map 覆盖注册、未注册时 panic，缺版本、冲突、卸载和诊断契约。 |
| `plugin_meta.yaml` + OpenAPI 文档静态装载 | **吸收为插件提供者校验层** | `backend/domain/plugin/conf/load_plugin.go:133-256` 已有版本、弃用、Manifest/OpenAPI、Tool ID/API 唯一性检查；不能直接当生产动态注册中心。 |
| Eino `compose` 图和 `WorkflowRunner` | **吸收为运行核心模式** | `backend/domain/workflow/internal/compose/workflow.go:83-175`、`workflow_run.go:85-313`；需补统一任务状态、资源租约、崩溃恢复证据。 |
| 多种 MQ 实现 | **隔离为 provider** | `backend/infra/eventbus/` 对 NSQ/RMQ/Pulsar/NATS/Kafka 有接口和实现；领域只依赖 `eventbus.Producer/ConsumerService`，禁止把某一种 MQ 写进模块契约。 |
| 现有前端包名和 FlowGram API | **待核/不直接迁移** | 可提取 registry、form、autosave、dispose 语义；React/FlowGram 组件与系统工程平台 UI 运行时保持适配层隔离。 |

## 12. 类易语言组件模型：注册、参数契约、保存与执行单元

### 12.1 组件注册四元组

把一个“组件/节点/插件 Tool”视为以下四元组，而不是一个 UI 卡片：

```text
组件身份 = {稳定类型/能力 id, 版本, 元数据, 注册入口}
参数契约 = {输入字段, 类型, 必填性, 来源/变量, 默认值, 输出字段, 错误}
执行实现 = {Adaptor/Builder, Invoke/Stream/Collect/Transform, provider 依赖}
生命周期 = {初始化, 校验, 装配, 执行, 中断/恢复, 成功/失败, 取消/超时, 释放/卸载}
```

对应源码证据：

- 前端 `WorkflowNodeRegistry` 的 `type`、`meta.nodeDTOType`、`formMeta`、`variablesMeta`、`getNodeInputParameters`、`getNodeOutputs`、`beforeNodeSubmit`、`onInit`、`checkError`、`onDispose` 位于 `frontend/packages/workflow/base/src/types/registry.ts:125-184`。
- 前端 `WorkflowNode` 优先从 registry 读取输入输出，否则按 `inputParametersPath` 或 `/inputParameters` 从表单模型读取，见 `frontend/packages/workflow/base/src/entities/workflow-node.ts:35-69`。这就是“组件属性表/参数表”的运行时读取规则。
- `createNodeRegistry` 将 `fieldConfig` 的 `name/description/required/type` 变成变量标签校验，并在提交前把固定参数类型写回 `input.type`，见 `frontend/packages/workflow/playground/src/nodes-v2/chat/create-node-registry.ts:56-131`。
- 后端 `NodeAdaptor` 是“画布数据 → 可执行 Schema”的适配契约，`NodeBuilder` 是“Schema → 执行对象”的构造契约；`InvokableNode`、`InvokableNodeWOpt`、`StreamableNodeWOpt`、`TransformableNode` 等执行形状位于 `backend/domain/workflow/internal/nodes/node.go:31-111`，构造接口位于 `backend/domain/workflow/internal/schema/node_builder.go`。
- 插件以 `plugin_id/version/plugin_type/manifest/tools` 为组件身份，以 OpenAPI operation 为参数和响应契约；`loadPluginProductMeta` 还拒绝弃用项、非法版本、重复 ID、未声明 API 和不通过 Validate 的 operation，见 `backend/domain/plugin/conf/load_plugin.go:40-55,151-249,259-283`。

### 12.2 参数契约的跨层传递

```text
前端 fieldConfig + formMeta + ValueExpression
  → WorkflowNodeJSON.data.inputs.inputParameters
  → Thrift BindAndValidate / workflow.SaveWorkflowRequest.Schema
  → vo.Canvas / Node.Inputs / FieldInfo
  → CanvasToWorkflowSchema / NodeAdaptor.Adapt
  → NodeSchema.InputSources + TypeInfo
  → nodes.ConvertInputs（文件、FailFast、警告）
  → NodeBuilder.Build + Invoke/Stream
```

关键约束：

- 保存的 Canvas JSON 不是最终执行参数；它还必须通过后端 `CanvasToWorkflowSchema`、节点依赖解析和 `ConvertInputs`。因此“前端表单校验通过”不能代替后端 Schema 校验。
- 输入来源必须保留变量路径和依赖关系；`compose.Workflow.addNodeInternal` 会先 `resolveDependencies`，再给 Eino 节点添加直接/非直接输入映射，见 `backend/domain/workflow/internal/compose/workflow.go:216-279`。
- `NodeTypeMeta` 记录 `DefaultTimeoutMS`、`InputSourceAware`、`PersistInputOnInterrupt`、`IncrementalOutput`、`UseDatabase`、`UseKnowledge`、`UsePlugin` 等执行和资源属性，见 `backend/domain/workflow/entity/node_meta.go:48-126`。这些字段应下沉为通用能力契约的行为列，而不是仅作 UI 展示。
- 插件执行时将 `map[string]any` 序列化成 `ArgumentsInJson`，并在工作流场景带上 `PluginID/ToolID/PluginVersion/UserID`，见 `backend/domain/workflow/internal/nodes/plugin/plugin.go:38-69`；响应再反序列化为工作流输出。参数错误、响应非 JSON、OAuth 中断都必须在这条入口归一化。

### 12.3 流程保存、发布和版本

```text
WorkflowEditService.addNode / 表单变更
  → WorkflowJSON(nodes, edges, blocks, data, version)
  → 前端 autosave/SaveWorkflow
  → handler.BindAndValidate
  → ApplicationService.SaveWorkflow
  → DomainService.Save
  → JSON 反序列化 + 测试运行标记 + 输入/输出参数 + CommitID
  → Repository.CreateOrUpdateDraft
  → ValidateTree / WorkflowSchemaCheck
  → PublishWorkflow
  → WorkflowVersion / Snapshot / Reference
  → Release execution only reads selected version/commit
```

源码证据：`frontend/packages/workflow/base/src/types/node.ts:25-38` 定义 nodes/edges/blocks/version；`frontend/packages/workflow/playground/src/services/workflow-edit-service.ts:78-167` 负责创建、初始化和放置节点；`backend/api/handler/coze/workflow_service.go:82-119` 负责保存 handler；`backend/application/workflow/workflow.go:303-327` 调用领域保存；`backend/domain/workflow/service/service_impl.go:128-163` 将 schema 解析为草稿并写入 `CreateOrUpdateDraft`；`backend/domain/workflow/interface.go:69-116` 明确元数据、版本、草稿、快照、引用和执行历史端口。

保存与发布的通用底座要求：

1. 草稿、已发布版本、快照、执行输入必须有不同的稳定身份，不能以“当前 Canvas”覆盖已执行版本。
2. 发布前必须同时校验节点类型、端口、必填参数、插件/数据库/知识依赖和子工作流版本；源码已有 `ValidateTree`、`WorkflowSchemaCheck` 和引用端口，但本轮未确认每一种发布事务的原子提交范围。
3. 资源复制/移动必须沿 `UseDatabase/UseKnowledge/UsePlugin` 元数据收集依赖并建立引用；不能只复制 Canvas JSON。
4. 恢复必须携带 `ExecuteID + EventID + ResumeData`；`WorkflowRunner.Prepare` 会核对中断事件存在性、ID 匹配和数据库条件锁，见 `backend/domain/workflow/internal/compose/workflow_run.go:126-158,177-258`。

### 12.4 执行单元生命周期

| 阶段 | 真实动作 | 单元状态/释放责任 |
|---|---|---|
| 创建 | `Prepare` 生成 ExecuteID；非恢复路径写 `WorkflowExecution(Status=Running)` | ID、输入、版本、日志 ID、节点数落账；生成失败不得启动图 |
| 装配 | `NewWorkflow` 初始化 Schema、复合节点、普通节点，编译 Eino Runner | NodeBuilder panic 被转为 `ErrCreateNodeFail`；未注册 adaptor 当前仍会 panic，需统一错误码 |
| 启动 | `context.WithCancel`，按 Background/Foreground 配置 `WithTimeout`；启动事件处理 goroutine | cancelFn/timeoutFn 由事件处理器持有；事件通道和可选 StreamContainer 由 Runner 管理 |
| 执行 | `SyncRun` 直接返回；`AsyncRun` 用 `safego.Go` 调 `Runner.Invoke/Stream`；流式写入 `StreamWriter` | 节点事件包括 start/end/error/stream/function/tool；节点可依赖 checkpoint |
| 中断 | Eino interrupt 转成 InterruptEvent，Redis list 保存，执行状态为 interrupted | 输入可按 `PersistInputOnInterrupt` 写 checkpoint；恢复前必须抢条件锁 |
| 恢复 | 复用 ExecuteID，读取首个中断事件，写 ResumeData，配置 state modifier，状态从 interrupted CAS 到 running | 恢复成功后事件/队列/锁必须可再次消费；重复恢复应被条件锁拒绝 |
| 成功/失败 | 最后事件决定 Success/Failed/Cancel/Interrupt，写 output/duration/error/token/status | `UpdateWorkflowExecution` 按允许旧状态条件更新，失败时再读取当前状态 |
| 取消/超时 | cancel API 写 Redis cancel flag；Runner 的事件处理器调用 cancelFn；context deadline 触发 timeout | 取消与超时不得伪装为普通失败，保留稳定错误码和执行证据 |
| 宿主崩溃 | 当前源码有 goroutine panic recover 和 `safego`，但未见完整进程级恢复编排 | 必须补启动时扫描 running 执行、租约/心跳、孤儿事件和 stream 关闭的验证 |
| 结束 | SSE handler `defer w.Close(); sr.Close()`；Runner 的 event goroutine `container.Done()` | 所有 reader/writer/channel/Redis TTL/DB 连接都要有终态核对 |

## 13. 领域能力到通用底座的详细映射

### 13.1 可视化节点、插件与 Workflow

- **支持库**：稳定 NodeType/能力 ID、Schema/ValueExpression/FieldInfo、统一成功/失败/错误码、JSON 编解码、版本和引用、输入输出/流式/中断数据类型。
- **模块库**：节点目录、分类、节点模板、前端 registry、后端 adaptor/builders、插件/Tool registry、Workflow 草稿/版本/发布/复制/依赖收集。
- **运行核心**：画布 Schema 编译、依赖拓扑、复合节点/子工作流、节点监督、输入转换、checkpoint、执行事件、取消/超时/重试、状态与执行历史。
- **网关**：`/api/workflow_api/*` 工作台 API、`/v1/workflow/*` Open API、插件开发/发布路由、鉴权、限流、错误映射和 SSE。

### 13.2 模型、工具、知识和数据库节点

- `backend/bizpkg/llm/modelbuilder` 是 provider 构建边界；`ModelForLLM` 将主模型、fallback 模型、模型信息、callback 和 ToolCallingChatModel 封装，见 `backend/domain/workflow/internal/nodes/llm/model_with_info.go:33-187`。应映射为“模型提供者支持库 + 模型调用模块”，不可让节点直接各自持有 SDK。
- 模型 fallback 由 `CurrentRetryCount > 0` 决策，说明重试属于运行核心语义，provider 只实现 Generate/Stream/WithTools；真实供应商/密钥/连接参数应留在 provider 适配层。
- Plugin Tool 的 OpenAPI schema、OAuth token、response trimming、debug status 属于插件模块；HTTP client、TLS、重试、body 关闭和敏感信息脱敏属于通用支持库；执行时由运行核心记录 `FunctionCall/ToolResponse/ToolError` 事件。
- `NodeTypeMeta.UseKnowledge/UseDatabase/UsePlugin` 是资源依赖声明；知识库/数据库的复制和发布关联属于 Workflow 模块，具体 GORM/Redis/向量库/对象存储驱动属于支持库 provider，不应从前端或网关直连。

### 13.3 API、任务、数据库和队列

| 边界 | 当前源码事实 | 底座落点与不能越界的事项 |
|---|---|---|
| API | Thrift 注解生成路由，handler 先 BindAndValidate，再调 Application Service；OpenAPI 运行失败可转 `WorkflowError.OpenAPICode()`，见 `workflow_service.go:862-898` | 网关拥有认证、错误/协议/SSE；模块拥有用例；不得在 handler 拼执行图或写 DB |
| 同步任务 | `SyncExecute` 等待 `SyncRun`，返回执行结果和终止计划 | 运行核心提供 deadline、状态和资源监督；同步请求不能承载无限中断，源码错误码明确提示中断应改异步 |
| 异步任务 | `AsyncExecute` 先 Prepare/落执行记录，再 `AsyncRun`，调用方用 ExecuteID 轮询 `GetExecution` | TaskID 与 ExecuteID 需统一或有可验证映射；当前执行状态/节点历史由 Repository 持久化 |
| 节点调试/测试 | `AsyncExecuteNode`、`TestRun`、`GetProcess`、`GetNodeExecution` | 调试是同一运行核心的 ExecuteMode，不另造一套 runner；前端仅维护 form/result view |
| 数据库 | Workflow Repository 以 GORM query 读写 `workflow_meta/draft/version/snapshot/reference/execution/node_execution` 等 DAL；`NewRepository` 注入 DB、Redis、TOS、checkpoint | 支持库负责驱动、事务、连接、超时；模块负责 repository/领域事务；当前未确认所有发布/复制操作的事务边界 |
| Redis | cancel flag、interrupt list、previous resumed event 使用 Redis，TTL 为 24h；见 `cancel_signal_store.go:33-61`、`interrupt_event_store.go:38-140` | 支持库只封装 KV/list/pipeline；运行核心负责幂等、过期和恢复；禁止把 Redis key 当公共跨域协议 |
| 队列 | `eventbus.Producer`/`ConsumerService`/`ConsumerHandler` 是统一抽象；实际有 NSQ/RMQ/Pulsar/NATS/Kafka provider；NSQ consumer 连接失败返回错误，退出信号触发 Stop | 队列 provider 只负责传输；领域 handler 负责幂等和错误；消费失败、重复投递、重试/死信仍需按具体 provider 实测 |
| 任务组 | `pkg/taskgroup` 用 errgroup 和并发上限；可选“首错取消剩余”或“全部继续”，panic 只记录 | 可吸收为通用并发原语，但必须补 panic 后错误可观察、Wait 语义、取消和资源清单；不能把日志等同于任务失败证据 |

### 13.4 前端和部署边界

- 前端 `@coze-workflow/base` 是类型/实体/校验基础，`@coze-workflow/nodes` 是节点目录/表单能力，`playground` 是画布编排，`test-run` 是测试运行插件，`studio/autosave` 是自动保存能力，`project-ide/biz-plugin-registry-adapter` 是 IDE 插件 widget 适配。它们对应“前端支持库/模块库”，不拥有后端权威状态。
- `WorkflowPlaygroundContext.loadNodeInfos` 通过 `workflowApi.NodeTemplateList(node_types, x-locale)` 获取服务端模板，并将模板、插件 API、插件分类建成 map，见 `frontend/packages/workflow/playground/src/workflow-playground-context.ts:119-164`。这形成前后端节点注册的对接契约：后端 ID/版本/元数据变更必须同时验证前端 registry 映射。
- `backend/api/router/register.go` 还注册静态文件，后端既是 API 服务也是默认 Web 入口；`backend/main.go:61-105` 的监听、body 上限、TLS、CORS、OpenAPIAuth、SessionAuth、I18n 顺序是部署/网关边界，不是业务模块。
- Docker Compose 把 MySQL 8.4.5、Redis 8.0、Elasticsearch 8.18.0 以及其数据卷/初始化脚本组织成 middleware；Makefile 的 `middleware`、`server`、`web`、`sync_db`、`clean` 分离开发和部署动作，见 `docker/docker-compose.yml:1-150`、`Makefile:23-89`。
- Helm `values.yaml` 当前把 `cozeServer` 以 8888/8889 暴露，配置 `STORAGE_TYPE=minio`、`COZE_MQ_TYPE=rmq`、`ES_VERSION=v8`、`VECTOR_STORE_TYPE=milvus`，并独立部署 MySQL/Redis/RocketMQ/Elasticsearch/MinIO。它证明的是部署边界和可选 provider，不证明所有服务在本地或当前分支都能启动。

## 14. 资源释放、唯一链路与故障矩阵

### 14.1 已见资源释放点

| 资源 | 创建/持有 | 已见释放 | 风险/待补证据 |
|---|---|---|---|
| 执行 context/cancel/timeout | `WorkflowRunner.Prepare` | `HandleExecuteEvent` 接收 cancel/timeout；context 结束后图应停止 | 未见每类节点都尊重 context；需真实慢节点验证 |
| StreamReader/Writer/SSE | `schema.Pipe`、handler `sendStreamRunSSE` | `defer w.Close(); sr.Close()`，见 `workflow_service.go:948-952` | 客户端断开到后台 Run 的传播和 goroutine 无残留需 L2/L3 |
| execute event channel/container | `eventChan`、`NewStreamContainer` | `container.Done()` 在 Prepare 失败和事件 goroutine defer | 非流式 channel、异步 Runner 错误的最终落账需验证 |
| DB 连接/事务/游标 | GORM/DAO/rows | 局部源码见 `rows.Close`；Repository 用 query/transaction | 未做连接池、事务回滚、崩溃中断验证 |
| Redis cancel/interrupt | key/list/pipeline | TTL 24h；取消 flag 无显式主动删除 | 过期残留、重复 resume、Redis 重启恢复需验证 |
| MQ producer/consumer | provider producer/consumer | NSQ 监听 `signal.WaitExit()` 后 Stop；其他 provider 需逐项核对 | 重复投递、断线重连、停机排空、死信未统一证明 |
| 模型/HTTP/对象存储 body | ModelBuilder、Tool executor、TOS/HTTP | 若使用 response body 的代码多处 `defer Body.Close` | Tool executor 全链路的连接关闭/超时/重试需 provider 级证据 |
| 前端注册与节点 | FlowGram document/registry/form | registry 提供 `onDispose`，声明用于回收错误信息/资源 | 各节点是否真正实现 onDispose 未全量扫描；不能把接口存在算实现 |

### 14.2 失败、超时、取消、崩溃矩阵

| 场景 | 当前可见行为 | 真实验收要求 |
|---|---|---|
| 非法参数/空输入 | handler BindAndValidate 返回 400 类错误；节点 `ConvertInputs` 可返回错误/警告 | L1 覆盖 required/type/变量不存在/文件字段/FailFast；L2 证明请求不落半执行记录 |
| Canvas/Schema 非法 | JSON 反序列化、CanvasToWorkflowSchema、NewWorkflow/Compile 返回错误 | L0 错误码映射；L1 每类非法边/未知节点；L2 API 只返回统一错误不启动后台 goroutine |
| 未注册节点/Builder panic | `GetNodeAdaptor` 当前 panic；`compose.New` defer recover 后包装 `ErrCreateNodeFail` | 统一为稳定 `CAPABILITY_NOT_FOUND`/`NODE_BUILD_FAILED`，并验证无执行/锁/stream 残留 |
| 插件/OpenAPI/Tool 失败 | meta/OpenAPI 校验时跳过/记录错误；ExecuteTool 包装 build/auth/execute/schema 错误 | L1 缺 Tool/重复 Tool/非法响应/OAuth；L2 真实 HTTP 超时和断线；不把默认响应当成功 |
| 模型 provider 失败 | `ModelForLLM` 在节点 retry 次数大于 0 时可切 fallback；callback 报错 | L1 验证主/备模型和 token；L2 provider 断线/限流/超时；输出必须标明实际模型和错误 |
| 节点超时/Workflow 超时 | NodeTypeMeta 有 `DefaultTimeoutMS`；Runner 按 foreground/background 设置 context deadline；错误码有 `ErrNodeTimeout/ErrWorkflowTimeout` | L1 deadline 触发；L2 慢节点真实停止并释放；L3 API 轮询最终为 timeout 而非 running |
| 主动取消 | Redis cancel flag + event handler cancelFn + `WorkflowCancel` 事件 | L1 幂等取消；L2 cancel API 与执行竞态；L3 客户端断开/取消后进程、goroutine、锁、Redis key可审计 |
| Interrupt/Resume | Redis 保存事件；ResumeData/state modifier；CAS 锁避免重复恢复 | L1 EventID/ExecuteID mismatch；L2 Redis 持久化恢复；L3 SSE 中断→提交回答→恢复→终态 |
| DB/Redis/MQ 断线 | provider 返回包装错误；部分 consumer 连接失败直接返回 | L2 注入断线并验证重试/失败边界；禁止无界重试或状态假成功 |
| goroutine panic | `taskgroup`/Runner 有 recover 并写日志；`safego.Go` 封装异步调用 | 日志不是完成证据；必须有执行记录 failed/crashed、资源回收和可查询错误 |
| 进程崩溃/强杀 | 当前静态证据未形成完整 running 执行恢复状态机 | L3 强杀 API/worker 后重启；L4 验证无半发布、无孤儿锁、可重试/人工介入 |
| SSE/网络断开 | handler defer 关闭 writer/reader；后台运行与客户端连接解耦的完整语义待核 | 断开后验证 context/stream/后台任务策略，避免双写、阻塞、泄漏 |

## 15. L0-L4 验证分层与本轮状态

| 等级 | 目标 | 具体验收 | 本轮状态 |
|---|---|---|---|
| L0 静态契约 | 证明边界、入口和源码存在 | 检查 `ARCHITECTURE.md`、IDL 路由、Service/Repository、NodeAdaptor/Registry、Runner、DAL/provider 文件；检查旧细探未被本轮删除 | **已执行静态读取**；目标 `.codegraph/` 不存在，不能冒充代码图证据 |
| L1 单元/契约 | 证明组件局部行为 | `go test` 定向跑 `domain/workflow/service/executable_impl_test.go`、`api/handler/coze/workflow_service_test.go`；前端 `vitest --run` 跑 registry/form/autosave/节点校验；覆盖坏参数、重复注册、错误码、resume mismatch | **未执行**；依赖/构建成本未启动 |
| L2 集成 | 证明真实基础设施链 | 隔离 Docker Compose 启 MySQL/Redis/ES/Milvus/MinIO/MQ；创建/保存/发布/执行/取消/中断恢复；核对 DB 行、Redis TTL/list、MQ ack/retry、对象存储、checkpoint | **未执行**；不能把配置文件当服务可用 |
| L3 进程/API E2E | 证明网关与运行核心贯通 | `make middleware` + server/static；调用 `/api/workflow_api/test_run`、`get_process`、`cancel`、`test_resume`、`/v1/workflow/run`、`stream_run`；断开客户端、强杀进程、重启后查状态/残留 | **未执行**；本轮禁止启动服务和写数据库 |
| L4 部署/混沌/兼容 | 证明上线边界和恢复 | Helm 部署、滚动升级、DB/MQ/Redis 重启、provider 超时/限流、节点/插件版本兼容、压力/并发/资源上限、崩溃恢复和审计证据 | **未执行**；Helm/Compose 仅作部署静态证据 |

L0 之外的任何“通过”都必须同时记录命令、退出码、测试数量、外部依赖、数据库/Redis/MQ 隔离身份、资源清理结果。源码中存在接口、历史测试存在、打印成功日志和子代理回信均不能替代真实执行。

## 16. 第三轮缺口、装配计划与后续复核

### 16.1 必补缺口

1. 为节点、插件 Tool、模型 provider、任务和队列统一定义 `能力 ID + 版本 + 参数/输出 + 错误码 + timeout/cancel/retry + resource owner`，解决当前前后端/插件/运行时各自持有部分契约的问题。
2. 将后端节点注册表从裸 map 升级为带冲突诊断、版本、启用/弃用、卸载和 provider 健康状态的唯一能力注册表；未知节点不得 panic 穿透网关。
3. 把 `ExecuteID`、任务状态、队列消息、执行历史、中断事件、取消信号串成一个可查询的状态机；建立 idempotency key，明确重复消息和重复取消语义。
4. 为异步 `safego.Go` 增加错误/崩溃落账、运行租约和重启恢复；不能只 recover 后写日志而让 DB 记录长期 `running`。
5. 为 SSE、Redis interrupt list、checkpoint、MQ consumer、HTTP/model provider 建立统一资源 owner 和四终态（完成/失败/取消超时/宿主崩溃）清理验证。
6. 明确 Workflow 发布事务的原子范围：版本、快照、引用、插件/数据库/知识资源、搜索事件和激活指针不能出现半发布。
7. 前端 `onDispose` 需要全量实现检查；节点 registry 与服务端 `NodeTemplateList` 的 node type/version/field schema 需要契约 diff 门禁。

### 16.2 建议装配顺序

```text
S0 契约冻结：能力ID/版本/参数/错误/状态/资源 owner
  → S1 注册与发现：前端 registry + 后端 adaptor + plugin/OpenAPI provider
  → S2 运行核心：统一 Runner/Task/Cancel/Timeout/Interrupt/Resume/Crash recovery
  → S3 持久与消息：Repository/CAS/幂等/队列 ack-retry-dead-letter
  → S4 统一网关：工作台 API/Open API/SSE/认证/限流/静态部署
  → S5 L0-L4 门禁：静态→单元→隔离集成→进程 E2E→部署混沌
```

任何新能力都必须先查现有注册表和支持库，命中则复用；只在契约、资源责任和验证缺口明确后升级/新建，不能按 Coze 的目录名复制第二套“工作流引擎”。

### 16.3 第三轮证据边界

- 目标仓库当前没有可用的 `.codegraph/`；专属 `system_engineering_toolkit` 的 `project_context` 实际返回了非目标项目 `华世王镞_v3`，MCP 实例为 `project_toolkit`，其代码图和最近成功验证也属于该非目标项目；随后对目标路径的 `codegraph_explore` 明确报“目标缺少 `.codegraph/` 索引”。因此本章所有 coze-studio 结论均来自目标路径直接静态读取，不能引用或冒充非目标代码图/验证证据。
- 目标目录搜索未发现独立旧细探文件；本轮没有删除任何文件。旧细探已被既有 `ARCHITECTURE.md:267` 声明为已吸收，本轮只追加本文件。
- 本轮允许修改范围只有目标根 `ARCHITECTURE.md`；本轮不改源码、依赖、配置、测试、README、Git，不安装依赖，不启动服务，不写正式数据库。
