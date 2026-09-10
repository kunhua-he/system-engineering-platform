# AnythingLLM 架构建档

> 本文是对本地源码归档的首轮全量架构记录。说明、备注、风险、结论使用中文；源码标识、路径、命令和环境变量保留原文。

## 1. 建档范围与基线

- 项目：AnythingLLM（`Mintplex-Labs/anything-llm`）
- 本地根目录：`~/Documents/Agent/github 源码参考/15_知识库系统/anything-llm`
- 本地分支：`master`，跟踪 `origin/master`
- 本地源码基线提交：`c8bd6442e6b6eee8d08a761452960f7f77e334a9`
- 本地提交时间：`2026-07-17T16:27:55-07:00`
- 本地包版本：根、`server`、`collector` 均为 `1.15.0`
- 许可证：仓库代码标注 MIT；自托管相关条款另见 `TERMS_SELF_HOSTED.md`；`open-computer` 文档标注 AGPL-3.0，使用时应分别核对许可边界。
- 工作树状态：存在一个未跟踪文件 `细探-anything-llm.md`；本次未修改、删除或覆盖它。
- 仓库规则：未发现 `AGENTS.md`、`CLAUDE.md` 或同名指导文件。

### 证据与可信度说明

本建档以本地源码、README、依赖清单、Prisma schema、迁移、测试、部署文件和已有细探文档为主；没有启动、安装、构建或接入运行时，因此“实现存在”只表示静态源码证据，不表示运行时已验证。

本轮未调用任何 MCP；目标目录现有独立 `.codegraph/`，当前 `codegraph status` 报告索引 `up to date`。代码地图只用于目标仓库导航，不把其他项目上下文或代码图作为本项目证据。

## 2. 项目定位与总体拓扑

AnythingLLM 是一个自托管的一体化 AI 应用：用户在工作区上传/导入文档，经 `collector` 解析和切分后进入文档存储、嵌入和向量数据库；`server` 负责工作区、权限、聊天、RAG、Agent、模型路由及 API；`frontend` 提供 React 管理和聊天界面。

```text
用户 / OpenAI-compatible 客户端 / Embed Widget / Browser Extension
                              │
                              ▼
                 server（Node.js + Express，默认 3001）
                 ├─ 认证、权限、工作区、线程、聊天和管理 API
                 ├─ SSE 聊天流；WebSocket Agent 会话
                 ├─ Prisma → SQLite（可切换 PostgreSQL 配置）
                 ├─ Document / Workspace / Chat 模型服务
                 ├─ LLM Provider 适配层 + AnythingLLM Model Router
                 ├─ Embedding Engine 适配层
                 ├─ Vector DB 适配层
                 └─ Agent / MCP / Agent Flow / Scheduled Job / Memory
                              │
                ┌─────────────┴─────────────┐
                ▼                           ▼
 collector（默认独立端口）             外部模型与向量服务
 ├─ 文件、链接、纯文本解析              LLM / Embedding / Vector DB
 ├─ OCR、Whisper、Office/PDF/EPUB       │
 ├─ Repository/Confluence 等扩展        ▼
 ├─ hotdir 暂存区与处理结果              文件 JSON + LanceDB/外部索引
 └─ payload integrity / data signer 中间件

frontend（Vite + React） ──HTTP/SSE──► server
open-computer（QEMU + Debian + XFCE）作为 Agent 的隔离电脑环境
```

README 将仓库主结构概括为 `frontend`、`server`、`collector`、`docker`、`embed`、`browser-extension`；其中 `embed` 和 `browser-extension` 是 Git submodule，当前分别指向 `anythingllm-embed` 和 `anythingllm-extension`。

## 3. 真实目录与模块职责

```text
anything-llm/
├── frontend/                 React/Vite UI、页面、模型请求封装、国际化
├── server/                   Express 主服务、模型、API、Agent、向量/嵌入适配
│   ├── endpoints/             内部 Web UI、Embed、扩展、移动端等路由
│   ├── endpoints/api/         Developer API、认证、OpenAI-compatible API
│   ├── models/                Prisma 薄封装与领域操作
│   ├── prisma/                schema、migrations、seed
│   ├── utils/                 聊天、Agent、Provider、向量、文件、任务等
│   ├── storage/               documents、vector-cache、lancedb、SQLite
│   ├── swagger/               Swagger 生成与文档
│   └── __tests__/             server 单元/模块测试
├── collector/                 文档处理服务
│   ├── processSingleFile/      按扩展名选择解析器
│   ├── processLink/            链接抓取和转文本
│   ├── processRawText/         纯文本处理
│   ├── extensions/             Confluence、GitHub/GitLab、Obsidian 等扩展
│   ├── utils/                  OCR、Whisper、文件、下载、签名
│   └── __tests__/              collector 测试
├── open-computer/              QEMU Agent 电脑环境及独立服务/CLI
├── docker/                     Dockerfile、Compose、入口和健康检查
├── cloud-deployments/          AWS/GCP/Helm/K8s/OpenShift 等部署模板
├── embed/                      Git submodule：Web Embed
├── browser-extension/          Git submodule：浏览器扩展
├── extras/                     翻译等辅助工具
├── locales/                    README 多语言说明
├── images/                     文档和界面资源
├── package.json                根级编排脚本
└── ARCHITECTURE.md             本架构建档
```

静态规模（不含 `node_modules`）：`server` 约 536 文件、`collector` 约 71 文件、`frontend/src` 约 690 文件；`open-computer` 含大量镜像/QEMU/服务资源，约 4163 个文件。目录统计来自当前工作树，属于规模快照而非固定契约。

## 4. 启动入口与请求边界

### 4.1 根级编排

`package.json` 定义了三个主要运行单元：

- `yarn dev:server` → `server/index.js`
- `yarn dev:collector` → `collector/index.js`
- `yarn dev:frontend` → `frontend` 中的 Vite
- `yarn dev` 用 `concurrently` 并行启动三者
- `yarn setup` 安装三处依赖、复制 `.env`、生成 Prisma Client、迁移并 seed
- `yarn prisma:generate|migrate|seed|setup` 管理数据库

本次未执行上述启动、安装和构建命令。

### 4.2 `server/index.js`

`server/index.js:1-48` 加载环境、日志、SDK timeout patch 和 Express 依赖；`server/index.js:64-80` 配置 CORS、3GB body limit、HTTP/HTTPS 入口和 `/api` router；`server/index.js:81-111` 注册 system、workspace、thread、chat、admin、document、Agent、MCP、mobile、scheduled job、memory、embed、browser extension 等路由；生产模式 `server/index.js:113-141` 托管 `server/public` 并由 `MetaGenerator` 动态返回页面；非 HTTPS 模式最终在 `server/index.js:179` 监听 `SERVER_PORT`，默认 3001。

`server` 是 CommonJS 边界（`server/package.json` 未声明 `type: module`），虽然根 `package.json` 声明了 ESM。维护时应以各 package 边界为准，不要仅依据仓库根配置判断模块格式。

### 4.3 `collector/index.js`

`collector/index.js:45-204` 提供文档处理接口：

- `POST /process`：处理热目录中的文件并返回解析文档
- `POST /parse`：解析但不落为服务端文档
- `POST /process-link`：抓取 URL 并保存为文档
- `POST /util/get-link`：抓取 URL 内容但不保存
- `POST /util/convert-audio-to-wav`：音频转换
- `POST /process-raw-text`：处理纯文本
- `extensions(app)`：注册扩展路由
- `GET /accepts`：返回可接受 MIME 类型

所有处理接口先经过 `verifyPayloadIntegrity`。`collector/index.js:216-228` 在 `COLLECTOR_PORT` 监听，并在启动回调中清理 collector 临时存储。collector 的错误响应多数仍使用 HTTP 200，并通过 `success/reason/documents` 表达结果；server 的 `CollectorApi` 负责检查 `success`。

`collector/utils/constants.js:1-2` 将 `hotdir` 定义为 `WATCH_DIRECTORY`，它是文件处理的暂存路径；当前源码没有 `fs.watch`、`chokidar` 或其他热目录监听器。collector 启动时由 `wipeCollectorStorage` 清理 hotdir（保留 `__HOTDIR__.md`）和临时目录，开发脚本还显式忽略 `hotdir`/`storage` 的变更。因此旧细探所称“热目录监听”不作为架构事实，准确表述是“hotdir 暂存/交换目录”。

`collector/middleware/verifyIntegrity.js:5-28` 在生产环境校验 `X-Integrity` 与请求体签名，开发环境跳过校验但仍解析运行时选项；`collector/middleware/setDataSigner.js:28-39` 解密 `X-Payload-Signer`，将 `EncryptionWorker` 放入 `response.locals`，供扩展路由加解密敏感数据。扩展路由由 `collector/extensions/index.js:12-239` 注册，覆盖 repository loader、resync、YouTube、website depth、Confluence、DrupalWiki、Obsidian 和 Paperless-ngx，并按路由组合完整性校验和 data signer。

### 4.4 `frontend/src/main.jsx` 与 Vite

`frontend/src/main.jsx:18-434` 使用 `createBrowserRouter`，页面通过 `lazy` 动态加载；公开入口包括 `/login`、`/sso/simple`、`/accept-invite/:code`、`/onboarding`，核心私有页面包括 `/workspace/:slug`、线程、工作区设置和大量 `/settings/*` 管理页，并用 `PrivateRoute`、`AdminRoute`、`ManagerRoute`、`SingleUserRoute` 做访问控制。

`frontend/vite.config.js:20-23` 默认开发端口为 3000；`frontend/vite.config.js:58-67` 强制产物主入口为 `index.js`、主 CSS 为 `index.css`，这是 server 端 `MetaGenerator` 动态托管静态页面的契约。`frontend/.env.example` 的本地 API 地址为 `http://localhost:3001/api`，Docker/非 localhost 部署使用 `/api`。

## 5. 核心业务链路

### 5.1 文档导入、解析和入库

```text
frontend 上传/链接
  → server /workspace/:slug/upload 或 /upload-link
  → CollectorApi
  → collector /process 或 /process-link
  → processSingleFile / processLink
  → Document[]（解析结果及 metadata/location）
  → server Document.addDocuments
  → 文档文件写入 storage/documents
  → EmbeddingEngine 分块和向量化
  → VectorDatabase.addDocumentToNamespace
  → workspace_documents + document_vectors + 向量命名空间
```

`server/endpoints/workspaces.js:116-207` 体现 server 到 collector 的上传/链接边界；`server/endpoints/workspaces.js:209-273` 负责删除/新增嵌入；`collector/processSingleFile/index.js:24-90` 做路径归一化、目录越界防护、保留文件保护、扩展名选择，并把任务分派给 `SUPPORTED_FILETYPE_CONVERTERS`；`collector/processLink/index.js:13-41` 校验 URL 后调用 `scrapeGenericUrl`。

解析能力由 `collector/processSingleFile/convert`、`processLink/convert`、OCR/Whisper/Office/PDF/EPUB 及 `extensions` 组合提供。解析产物落到文件存储，数据库只保存文档索引、工作区关系和 metadata；这是“文件内容/数据库元数据/向量索引”三套状态，需要分别维护一致性。

### 5.2 RAG 聊天

```text
POST /workspace/:slug/stream-chat（或 thread 版本）
  → validatedRequest + multiUserProtected + validWorkspace
  → streamChatWithWorkspace
  → workspace/thread/user 上下文和 chat history
  → chatPrompt + memories + system prompt variables
  → EmbeddingEngine.embedTextInput
  → VectorDatabase.performSimilaritySearch
  → 可选 rerank、pinned documents、parsed files、引用
  → LLM Provider / Model Router
  → SSE chunks（文本、引用、usage、路由提示）
  → WorkspaceChats 持久化 + EventLogs/Telemetry
```

`server/endpoints/chat.js:23-103` 和 `105-209` 是工作区/线程 SSE 入口，限制空消息、配置 `text/event-stream`，并在完成后写 telemetry 和 event log。`server/utils/chats/index.js:61-109` 负责历史和系统提示词；提示词会展开 `SystemPromptVariables`，再接入 memories。`server/utils/DocumentManager/index.js:20-68` 从 `workspace_documents` 找 pinned 文档，再读取 `storage/documents` 中的 JSON 内容。

### 5.3 Agent、工具和 MCP

`server/endpoints/agentWebsocket.js:26-64` 提供 `/agent-invocation/:uuid` WebSocket，会创建 `AgentHandler`、接收反馈/审批/澄清/工具切换消息，并在关闭时关闭 invocation。

`server/utils/agents/index.js` 的 `AgentHandler` 负责：

1. 读取 `workspace_agent_invocations` 并解析工作区、用户、线程。
2. 根据 workspace 的 `agentProvider/agentModel` 或聊天配置选择 provider。
3. 组装 `USER_AGENT`、`WORKSPACE_AGENT` 和所需函数。
4. 通过 `AIbitat` 创建 Agent 图；标准插件包括 websocket、chat history。
5. 动态装载普通插件、子插件、`@@flow_<uuid>`、`@@mcp_<server>` 和 Community Hub 导入插件。
6. 每轮重新读取 parsed files/pinned documents，登记 citations。
7. 通过 provider 的 streaming/non-streaming tool call 递归执行，受 `AGENT_MAX_TOOL_CALLS`/默认 10 次限制。

`server/utils/agents/aibitat/index.js` 的核心状态包括 agents、channels、functions、chat history、citations、tool attachments 和 clarifying-question surveys；`handleAsyncExecution`/`handleExecution` 完成 LLM → tool → tool result → 继续 LLM 的循环。MCP 由 `server/utils/MCP` 和 `MCPCompatibilityLayer` 转成 Aibitat plugins；Agent Flow 通过 `@@flow_` 装载；scheduled jobs 复用 Agent 执行链并把结果写入 `scheduled_job_runs`。

### 5.4 模型路由

当工作区 provider 为 `anythingllm-router` 时，`server/utils/helpers/index.js:634-694` 改为调用 `ModelRouterService` 收集 prompt、历史、系统提示词、pinned/parsed 文件和 token/message 数，再由 `AnythingLLMModelRouter` 选择真实 provider。

`server/utils/router/index.js:25-39` 使用单例缓存 router、sticky route、LLM classification 和通知去重；`server/utils/router/index.js:426-650` 支持 calculated 规则（`AND`/`OR`、字符串/数字比较、正则输入上限）和 LLM 规则。路由数据存放在 `model_routers`、`model_router_rules`，工作区通过 `router_id` 关联（schema 注释说明 SQLite 下有意不建立关系）。

## 6. Provider 适配层

### 6.1 LLM

`server/utils/helpers/index.js:136-264` 的 `getLLMProvider` 按 `LLM_PROVIDER` 或 workspace provider 选择 provider；当前源码包含 OpenAI、Azure、Anthropic、Gemini、LM Studio、LocalAI、Ollama、Together AI、Fireworks、Perplexity、OpenRouter、Mistral、Groq、Cohere、LiteLLM、Bedrock、DeepSeek、xAI、NVIDIA NIM、PPIO、Moonshot、CometAPI、Foundry、Z.AI、Gitee AI、Docker Model Runner、Privatemode、SambaNova、Lemonade、OMLX、Minimax、Cerebras 等适配器。`anythingllm-router` 不直接实例化普通 provider，而由 Model Router 解析。

### 6.2 Embedding

`server/utils/helpers/index.js:271-322` 的 `getEmbeddingEngineSelection` 支持 native、OpenAI、Azure、LocalAI、Ollama、LM Studio、Cohere、VoyageAI、LiteLLM、Mistral、Generic OpenAI、Gemini、OpenRouter、Lemonade；未识别时回退到 `NativeEmbedder`。native 文档说明使用 ONNX `all-MiniLM-L6-v2`，生成 384 维向量；音视频本地转写默认使用 `whisper-small`。

### 6.3 Vector DB

`server/utils/helpers/index.js:87-126` 的 `getVectorDbClass` 按 `VECTOR_DB` 选择 `lancedb`（默认）、Pinecone、Chroma、ChromaCloud、Weaviate、Qdrant、Milvus、Zilliz、AstraDB、PGVector；未知值打印错误并回退 LanceDB。`server/utils/vectorDbProviders/base.js:6-202` 定义连接、命名空间、向量增删、相似度搜索、统计、重置和来源整理等统一接口。

## 7. 持久化与数据模型

### 7.1 数据库边界

`server/prisma/schema.prisma:13-16` 默认使用 SQLite 文件 `server/storage/anythingllm.db`；文件内保留 PostgreSQL datasource 的切换模板。`server/utils/prisma/index.js:1-13` 使用单例 `PrismaClient`。迁移目录有从 `202309...` 到 `202605...` 的连续历史，修改 schema 应新增 migration，不应改旧 migration。

当前 schema 有 **33 个 Prisma model**、约 31 个 `@relation`、20 个 `@@index`/复合索引声明及多处唯一约束。主要模型分组如下：

| 分组 | 主要 model | 责任 |
|---|---|---|
| 身份与权限 | `users`、`recovery_codes`、`password_reset_tokens`、`temporary_auth_tokens`、`invites`、`api_keys`、`browser_extension_api_keys` | 登录、恢复、邀请、API/扩展密钥、角色和限额 |
| 工作区与成员 | `workspaces`、`workspace_users`、`workspace_threads`、`workspace_suggested_messages` | 工作区设置、成员、线程、建议消息 |
| 文档与上下文 | `workspace_documents`、`workspace_parsed_files`、`document_vectors`、`document_sync_queues`、`document_sync_executions` | 文档索引、线程/用户附件、向量映射、同步队列 |
| 对话与嵌入 | `workspace_chats`、`embed_configs`、`embed_chats` | UI/API 对话历史、公开 Embed 会话 |
| Agent 与扩展 | `workspace_agent_invocations`、`scheduled_jobs`、`scheduled_job_runs`、`external_communication_connectors` | Agent invocation、计划任务、运行轨迹、外部连接 |
| 提示词、记忆与治理 | `system_settings`、`system_prompt_variables`、`prompt_history`、`memories`、`slash_command_presets`、`event_logs` | 系统配置、变量、提示词历史、用户/工作区记忆、审计日志 |
| Model Router | `model_routers`、`model_router_rules` | fallback、规则、优先级和路由策略 |
| 客户端连接 | `desktop_mobile_devices` | Desktop/Mobile 配对设备 |

关键领域关系：`workspaces` 是主聚合对象；文档通过 `workspace_documents.workspaceId` 归属工作区；聊天通过 `workspaceId`、可选 `thread_id`、可选 `user_id` 和 `api_session_id` 分区；Agent invocation 同时指向 workspace/user/thread；`memories` 可按 user/workspace/scope 组织；Embed 通过 `embed_configs` 归属 workspace。

### 7.2 文件与向量状态

`server/storage/README.md` 明确要求 `documents`、`lancedb`、`vector-cache` 和 `anythingllm.db`。文档 JSON 内容不直接存入 Prisma；`DocumentManager` 根据数据库的 `docpath` 读取文件。LanceDB/其他向量服务保存向量和相似度索引，Prisma `document_vectors` 保存映射信息。删除工作区时 `server/endpoints/workspaces.js:275-320` 先清理聊天、向量映射、文档、工作区，再尝试删除 vector namespace；外部向量库失败会被记录但不阻断删除响应，这是需要关注的跨存储一致性边界。

### 7.3 关键数据契约

- workspace 的可写字段和校验集中在 `server/models/workspace.js:35-141`；`chatMode` 允许 `chat`、`query`、`automatic`，`vectorSearchMode` 允许 `default`、`rerank`。
- `Workspace.new` 在 `server/models/workspace.js:194-233` 生成 slug、应用默认系统提示词并创建 workspace/member 关系。
- `WorkspaceChats.new` 在 `server/models/workspaceChats.js:4-31` 将 response JSON 化并按 user/thread/API session 记录。
- seed 只在 `server/prisma/seed.js:4-21` 初始化 `multi_user_mode` 和 `logo_filename`（存在则不覆盖）。

## 8. API 与外部契约

所有 server 路由先由 `server/index.js` 挂载到 `/api`。内置 Web UI/API 的 endpoint 文件包括：

- 认证、管理、系统：`server/endpoints/system.js`、`admin.js`、`invite.js`
- 工作区、线程、聊天、文档：`workspaces.js`、`workspaceThreads.js`、`chat.js`、`document.js`
- Embed、浏览器扩展、移动端、Web Push、Telegram：对应 `embed/`、`browserExtension.js`、`mobile/`、`webPush.js`、`telegram.js`
- Agent、MCP、Flow、memory、scheduled jobs：`agentWebsocket.js`、`mcpServers.js`、`agentFlows.js`、`memory.js`、`scheduledJobs.js`
- Developer API：`server/endpoints/api/index.js` 汇总认证、管理、system、workspace、document、thread、user management、OpenAI-compatible、embed endpoint，并通过 Swagger 生成文档。

静态扫描当前 endpoint 文件得到约 295 个 `app/router` 声明（包含 `use`/WebSocket 等注册表达式，不应直接当作最终 HTTP 路由数）。其中 `server/endpoints/api` 有 9 个路由文件、约 62 个注册表达式。

OpenAI-compatible 契约位于 `server/endpoints/api/openai/index.js`：

- `GET /v1/openai/models`：把 workspace 暴露为可聊天 model
- `POST /v1/openai/chat/completions`：按 workspace slug 聊天，支持同步和 SSE streaming
- `POST /v1/openai/embeddings`：调用当前 embedding engine
- `GET /v1/openai/vector_stores`：把 workspace/文档数量暴露为 vector store

这些接口使用 `validApiKey`，聊天请求通过 `OpenAICompatibleChat` 进入同一聊天/RAG链路。

## 9. Agent 隔离电脑：`open-computer`

`open-computer` 是与主 RAG 服务并列的 Agent 运行环境，README 定位为“给 Agent 自己的机器”。其核心边界：

- QEMU 虚拟化，Debian 13.5.0 + XFCE + Chromium
- `master/base_image/base.qcow2` 作为 golden image
- 每个 Agent 使用独立 `.qcow2` overlay，按端口分配运行
- `service/server.js` 提供 HTTP/WebSocket 接口、浏览器 CDP 桥和 UI
- `services/memory-manager` 管理 Agent memory
- Agent harness 使用 Pi，并通过 OpenAI API-compatible 接口访问主机或外部模型
- `open-computer/cli` 管理 create/up/down/restart/destroy 等生命周期

该目录仍处于 work in progress；它与 server 内部的 Agent/MCP 插件体系不是同一个进程边界，后续接入应明确 API、权限、网络和文件交换契约。

## 10. 部署与运行形态

### Docker

`docker/docker-compose.yml:7-31` 以单容器 `anythingllm` 暴露 3001，挂载 `server/storage`、collector hotdir/outputs，并用 bridge network 和 `host.docker.internal`。`docker/Dockerfile:137-169` 分别构建 frontend、安装 server/collector production dependencies，再把 frontend `dist` 复制到 `server/public`；`docker/Dockerfile:171-182` 设置 production 环境、健康检查和入口脚本。

### 其他部署

`cloud-deployments` 提供 AWS CloudFormation、GCP、DigitalOcean、Helm、K8s、OpenShift、Hugging Face Spaces 等模板；`BARE_METAL.md` 描述不使用 Docker 的部署。部署差异主要落在 STORAGE_DIR、环境变量、端口、持久卷和外部数据库/向量服务配置，核心 server/collector 代码仍保持同一边界。

## 11. 测试与验证面

根 `jest.config.cjs` 仅忽略 `node_modules` 和 `open-computer`。当前可见测试规模：server 约 22 个测试文件、collector 4 个、open-computer 2 个（后者被根 Jest 忽略）。覆盖重点是：

- Agent defaults/imported、Aibitat emitter/provider helper
- Agent Flow executor、MCP compatibility/hypervisor
- OpenAI-compatible chat/helper、TextSplitter、TTS、向量 provider
- Prisma model 行为：user、document sync queue、system prompt variables
- 路径安全、workspace deletion protection、JSON stringify
- collector URL、下载、Confluence、FFmpeg Whisper

测试是模块级单元测试为主，没有在本次建档中启动测试。原因是用户明确禁止启动、构建和验证运行；本次只对文档执行静态格式检查。不要把测试文件存在等同于完整端到端覆盖。

## 12. 远程版本与漂移

当前 checkout 的 `HEAD` 与 `origin/master` 均为 `c8bd6442e6b6eee8d08a761452960f7f77e334a9`（`git rev-list --left-right --count HEAD...origin/master` 为 `0 0`）；本档的当前源码事实以该提交为准。此前基于旧提交的远程快照记录仅作为历史审计痕迹，不覆盖当前本地事实。

按照要求，使用 `http://127.0.0.1:4780` 仅对远程 commit 做了独立快照读取，没有 fetch、覆盖工作树或写入项目目录。读取到的远程关键事实：

- 根、`server`、`collector` 的版本均已为 `1.16.0`。
- `frontend` 的 `@mintplex-labs/piper-tts-web` 已为 `^1.0.5`，并新增 `file-selector`；本地仍为 piper `^1.0.4` 且无 `file-selector`。
- 远程 `server/prisma/schema.prisma` 仍为 33 个 model、约 488 行，当前末尾仍包含 `model_router_rules`，未见模型数量级变化。
- 远程 README 的主拓扑仍是 frontend/server/collector/docker/embed/browser-extension，并新增 Sealos 部署表项。
- GitHub Compare API 经代理返回 403 rate limit，因此未获得可靠的完整 changed-file 列表；不能据此推断远程所有变更。

## 13. 风险、边界与可借鉴点

### 风险

1. **远程漂移**：当前 checkout 已与 `origin/master` 对齐；后续若远程指针变化，仍须在隔离快照中逐文件核对后再更新本档。
2. **跨存储一致性**：Prisma、文件 JSON、vector namespace/cache、collector 临时目录各自持久化，删除/重嵌入不是单一数据库事务；失败恢复要逐层核对。
3. **Provider 组合复杂度**：LLM、Embedding、Vector DB 均是可配置适配器，workspace 配置、系统环境变量和 `anythingllm-router` 有 waterfall；新增 provider 需同步 provider factory、Agent provider、模型选择和 UI/API。
4. **Agent 工具权限**：普通插件、MCP、导入插件、文件系统工具和 Open Computer 都能产生外部副作用；`AGENT_AUTO_APPROVED_SKILLS`、MCP cooldown、工具调用上限和 WebSocket 审批是安全边界，不能只依赖提示词。
5. **API 错误语义不统一**：collector 的处理错误常用 HTTP 200 + `success:false`，OpenAI-compatible 和内部 API 又有 HTTP 状态码/SSE abort 两套语义，客户端应以各接口契约处理。
6. **SQLite 约束与迁移**：schema 对部分关联故意不建 relation 以避免 SQLite 全表迁移；改为 PostgreSQL 或增加 relation 时必须审查 migration 和历史数据。
7. **测试覆盖边界**：当前测试主要是模块级，未证明三进程协作、外部向量服务、真实 LLM、WebSocket Agent、Docker 持久化和升级迁移的端到端行为。
8. **许可边界**：主项目 MIT、自托管条款、submodule 和 `open-computer` 许可并不等价，二次分发前应按目录逐项确认。

### 可借鉴模式

- `collector/processSingleFile` 的扩展名分派和路径越界保护适合文档流水线设计。
- `VectorDatabase` base contract + provider factory 适合把向量供应商隔离在统一接口后。
- `Workspace` 的 writable 字段白名单和字段校验适合配置更新接口。
- `AIbitat` 的 plugin 注册、事件流、工具递归执行和 citation buffer 适合 Agent 编排参考，但必须补齐本地权限与审计要求。
- `open-computer` 的 base image + per-agent overlay 适合隔离运行环境的架构参考；它不是对主机直接授予权限的替代品，仍需网络、密钥和文件访问治理。

## 14. 建档结论

AnythingLLM 的主架构是“React UI + Express 主服务 + 独立文档 collector + Prisma 元数据 + 文件/向量双层检索 + 可插拔 LLM/Embedding/Vector DB + WebSocket Agent/MCP”的模块化单体/伴生服务组合。其核心聚合对象是 workspace，核心数据流是“文档解析 → 文件/元数据 → embedding → vector namespace → workspace chat/Agent → SSE/WebSocket/API”。

本次已完成首轮静态全量建档，唯一写入文件为项目根目录的 `ARCHITECTURE.md`。没有修改源码、依赖、测试、配置、细探文档、submodule，没有安装、启动、构建或提交。后续升级审计仍应以目标根目录的明确 commit 快照和独立 CodeGraph 为证据。

## 15. 旧细探吸收与裁决记录

本节是对旧文档 `细探-anything-llm.md` 的逐项收口记录。旧文档已完整读取，但按本次范围要求保留原文件；它只作为历史线索和溯源材料，后续架构事实只维护本 `ARCHITECTURE.md`。

| 旧细探内容 | 裁决 | 吸收位置与当前源码证据 |
|---|---|---|
| 自托管 AI 应用，包含 RAG、Agent、Open Computer；Node `server`/`collector`、React `frontend`、`embed`、`browser-extension`、Docker/云/裸金属 | 吸收 | 第 2、3、9、10 节；根 `package.json`、`README.md:173-203`、`open-computer/README.md:65-95`、`docker/docker-compose.yml`、`BARE_METAL.md` |
| 文档经 collector 处理后进入 server 知识库、向量化和检索，再由 frontend/embed 使用 | 吸收并细化 | 第 2、5、7 节；`collector/index.js:45-206`、`server/endpoints/workspaces.js`、`server/utils/DocumentManager`、向量 provider 契约 |
| `collector/extensions/` 提供扩展处理 | 吸收并补证据 | 第 3、4.3 节；`collector/extensions/index.js:12-239` 注册 repository、resync、YouTube、website depth、Confluence、DrupalWiki、Obsidian、Paperless-ngx 路由 |
| `processLink`、`convertAudioToWav`、`middleware` 是 collector 的边界组件 | 吸收并细化 | 第 4.3 节；`collector/index.js:109-176`、`collector/convertAudioToWav/index.js:7-54`、`collector/middleware/verifyIntegrity.js`、`setDataSigner.js` |
| `hotdir` 是“热目录监听”，可作为文件进入自动处理机制 | 部分吸收，纠正表述 | 当前源码确认 `hotdir` 是 `WATCH_DIRECTORY` 暂存/交换目录，并在启动时清理；未发现 `fs.watch`、`chokidar` 或监听器，因此不记录“热目录监听”这一未证实事实。证据：`collector/utils/constants.js:1`、`collector/utils/files/index.js:154-191`、`collector/package.json:13` |
| server 负责知识库、向量化、检索、Agent、API；提示词位于 server | 吸收并细化 | 第 4、5、6、8 节；`server/utils/chats`、`server/utils/agents`、`server/models/systemPromptVariables`、`server/endpoints/api` |
| Open Computer 是给 Agent 的独立电脑环境 | 吸收并加边界 | 第 2、9、13 节；`open-computer/README.md:8-27,65-95` 明确 QEMU、隔离 VM、human-in-the-loop、interface service、memory manager、base image 与 overlay；并保留其 WIP/独立进程边界风险 |
| 可借鉴：collector 扩展化、hotdir 自动处理、Open Computer 能力下沉、自托管多形态部署 | 吸收其中有证据部分；hotdir 自动监听不吸收 | 第 10、13 节；扩展化、暂存目录、隔离电脑和 Docker/云/裸金属均有源码或部署文档证据；“自动监听”被上行裁决为未证实 |
| 许可证需核对 MIT、`TERMS_SELF_HOSTED.md` 与 Open Computer 许可；平台只应借鉴架构 | 吸收 | 第 1、9、13 节；未将不同目录许可合并为单一许可证，也未把参考架构当作可直接复制的生产组件 |
|| 旧细探列出的旁路线索和注意事项 | 已覆盖，无需重复建文档 | 已映射到第 3、4、9、10、13 节；没有新增平行摘要或修改旧细探 |

## 16. 后续底座映射：收集器扩展、完整性、暂存资源与部署边界

当前核对不是把 AnythingLLM 的目录直接复制成平台目录，而是把可复用的原子能力、领域编排、运行时治理和项目部署适配分开。以下判断只基于本地源码基线 `c8bd6442e6b6eee8d08a761452960f7f77e334a9`；本节中的“吸收”表示作为平台设计输入，不表示已迁移或已接入平台。

### 16.1 单一权威链路与归属裁决

```text
项目入口/API
  → 项目适配层：认证、工作区权限、部署配置、旧键/旧路由兼容
  → 模块库：文档导入/扩展同步/音频预处理领域编排
  → 唯一能力调用器/注册表
  → 支持库：路径安全、内容摘要/签名、暂存目录、文件原子操作、音频转换契约
  → 受管 provider：FFMPEG、OCR、Whisper、抓取器、Office/PDF 解析器
  → 运行核心：子进程/超时/取消/进程组、临时资源登记与失败清理、证据与可观测性
  → 统一结果/事件/持久化投影
```

| 源码事实 | 平台归属 | 裁决 | 不能下沉的内容 |
|---|---|---|---|
| `collector/extensions/index.js:12-239` 注册 repository、resync、YouTube、website-depth、Confluence、DrupalWiki、Obsidian、Paperless-ngx 路由 | 模块库的“外部内容导入/同步”模块；各平台 loader 是 provider/适配器 | **吸收**扩展注册与路由表思想；每个能力只保留一个规范能力 id，由模块编排 | 不把第三方凭据、平台 URL 参数和具体 loader 直接放进通用支持库 |
| `collector/middleware/verifyIntegrity.js:5-28` 校验 `X-Integrity`；`setDataSigner.js:28-39` 解密 `X-Payload-Signer` 并注入 `response.locals.encryptionWorker` | 支持库负责签名正文/验证结果；运行核心负责密钥句柄、失败证据和密钥生命周期；项目适配层负责 server↔collector 的密钥装配 | **吸收**为“数据完整性签名能力”，但拆开完整性与机密载荷签名两种语义 | 不把 `CommunicationKey`、`EncryptionManager` 或 HTTP header 名称当成平台公共业务契约 |
| `collector/hotdir`、`wipeCollectorStorage()`（`collector/utils/files/index.js:154-192`） | 支持库提供受限暂存目录/安全路径/递归清理原子能力；运行核心负责租约、崩溃清理、残留审计 | **吸收**“暂存/交换目录”模式；明确不是监听器 | 不将 hotdir 当持久知识库，也不把启动时粗粒度 wipe 当作完整恢复机制 |
| `collector/convertAudioToWav/index.js:13-54` + `collector/utils/WhisperProviders/ffmpeg/index.js:13-114` | 模块编排音频预处理；支持库公开音频转换契约；FFMPEG 属受管 provider；运行核心监督外部进程与超时/资源 | **吸收**输入校验、16kHz 单声道 WAV 目标和源文件清理语义 | 不让模块直接 `spawnSync`/定位二进制；不把 ffmpeg 版本/路径写入领域模块 |
| `docker/Dockerfile:13-38,149-182`、`docker/docker-compose.yml:18-31`、`cloud-deployments/*` | 运行核心提供运行环境/健康检查/进程边界；项目适配层提供 env、挂载、端口、云平台模板 | **吸收**“server+collector+静态前端”的部署边界；部署模板是项目适配，不是支持库 | 不把 Docker、K8s、QEMU、云厂商参数写进平台核心或领域模块 |

### 16.2 收集器扩展路由与完整契约

**路由链。** server 的 `server/endpoints/extensions/index.js:12-197` 先做 `validatedRequest`、角色校验（repository 还经过 `isSupportedRepoProvider`），再调用 `CollectorApi.forwardExtensionRequest()`；`server/utils/collectorApi/index.js:257-285` 将 body JSON 化，以 `CommunicationKey.sign(data)` 生成 `X-Integrity`、以 `CommunicationKey.encrypt(new EncryptionManager().xPayload)` 生成 `X-Payload-Signer`，通过内部 collector HTTP endpoint 转发，扩展请求超时为 15 分钟。collector 的 `collector/extensions/index.js:12-239` 再按具体路由选择 loader，并在部分路由挂 `setDataSigner`，最后返回 `{success, reason, data}` 或按扩展定义的结果形状。

**路由映射。** repository 的 server 路由 `/ext/:repo_platform/repo`、`/ext/:repo_platform/branches` 对应 collector `/ext/:repo_platform-repo`、`/ext/:repo_platform-repo/branches`；其余 server 路由 `/ext/youtube/transcript`、`/ext/confluence`、`/ext/website-depth`、`/ext/drupalwiki`、`/ext/obsidian/vault`、`/ext/paperless-ngx` 分别映射 collector 的同名扩展端点。该映射必须集中在一个模块/适配层，不能让 frontend、server endpoint 和 collector 各自维护别名表。

| 能力边界 | 输入契约（源码事实） | 输出/错误契约（源码事实） | 平台后续落点 |
|---|---|---|---|
| repository loader | `repo_platform` 路由参数 + loader 所需 `request.body`；branches 复用同一 body | 成功 `{success:true, reason:null, data:{branches:[]/…}}`；loader 异常通常由 collector 以 HTTP 200 返回 `{success:false, reason, data:{}}`；branches 异常为 HTTP 400 且 branches 空数组 | 模块只编排“选择 provider→调用→结果归一”；provider 声明参数和可用平台 |
| resync | body `{type, options}`；`type` 必须是 `RESYNC_METHODS` 的键 | 未知 type 变成失败 `{success:false, content:null, reason}`；成功/失败均可能通过 HTTP 200 | 支持库/模块契约固定稳定错误码，保留项目适配层对旧 reason 的转换 |
| website depth | `{url, depth=1, maxLinks=20}`；先 `validateURL`，再 `validURL` | 成功 `{success:true,data:scrapedData}`；非法 URL/抓取异常 HTTP 400 `{success:false,reason}` | URL 校验是支持库原子能力；抓取深度编排归模块；浏览器/HTTP 是 provider |
| YouTube/Confluence/DrupalWiki/Obsidian/Paperless | 各 loader 的 body；部分需 `response.locals.encryptionWorker` | 扩展自行返回 `success/reason/data`；顶层异常多为 HTTP 400，server transport 异常则转 HTTP 500 | 用领域输入/输出 DTO 统一，不让 `response` 对象穿透支持库；敏感数据只通过显式 signer 能力 |

**契约缺口。** collector 多处用 HTTP 200 携带 `success:false`，而部分扩展异常用 HTTP 400、server transport 异常用 HTTP 500；因此模块不能只看 HTTP 状态，也不能只看 `success`。平台接入时应在唯一调用器将 `(HTTP status, JSON success, reason/data)` 归一为统一结果：网络/超时、认证/签名失败、参数非法、provider 不可用、外部内容失败、部分结果分别有稳定错误码和 `可重试` 标志；原始 HTTP 状态与 reason 进入诊断，不作为跨模块契约。

### 16.3 数据完整性签名与数据签名的分层

当前 `CollectorApi` 对 `/process`、`/process-link`、`/process-raw-text`、`/util/convert-audio-to-wav` 以及扩展转发都对**同一序列化后的 body**签名；collector 的 `verifyPayloadIntegrity` 在生产环境要求 `X-Integrity` 存在且 `CommunicationKey.verify(signature, request.body)` 为真，开发环境则跳过校验并解析 runtime options。`X-Payload-Signer` 不是完整性签名：它是加密后的持久 `EncryptionManager.xPayload`，由 collector 解密后构造 `EncryptionWorker`，供扩展路由加解密敏感字段。

平台应固定以下契约：

1. **签名正文**：先固定 canonical JSON（字段顺序/编码/空值规则），再计算摘要或签名；验证端只验证收到的原始正文，禁止先反序列化再重新序列化后验签。
2. **签名范围**：签名覆盖能力 id、版本、请求 id/幂等键、时间窗、正文摘要和必要的路由上下文；HTTP header 只是传输载体，不能成为业务事实。
3. **结果**：验证成功返回统一结果并携带签名版本/摘要；缺签名、签名格式错误、正文篡改、时间窗过期、密钥不可用分别返回稳定错误码；不得用开发模式跳过作为生产降级。
4. **机密载荷**：数据加密/解密是另一能力，输入为密文与密钥句柄，输出为明文或明确失败；密钥不落日志、不进入普通模块参数、不由 provider 对象穿透。
5. **重放与幂等**：签名本身不能阻止重放；应由运行核心检查时间窗、nonce/request id 和能力级幂等键。重复请求返回既有结果或 `DUPLICATE_REQUEST`，不得重复写文档/索引。

**证据等级：** 当前源码证明“server→collector 的请求完整性校验存在”，但没有证明 canonicalization、nonce/时间窗、签名版当前核对换、重放防护或跨存储写入后的数据摘要链。因此“完整性签名能力”可**吸收为设计输入，待运行/契约验证**；不能把当前 `X-Integrity` 直接宣布为平台级数据完整性账本。

### 16.4 hotdir 暂存、音频转换与失败清理

`WATCH_DIRECTORY` 是 `collector/hotdir`（`collector/utils/constants.js:1`）。`processSingleFile` 默认从该目录解析；`convertAudioToWav` 先用 `normalizePath` 和 `isWithin` 防目录越界，检查源文件存在，再调用 FFMPEG 输出同目录 `<原名>.wav`。成功和失败的 `finally` 都调用 `trashFile(inputPath)`；函数注释要求调用者随后读取并删除 wav，但该删除责任不是函数内部强制完成。collector 启动监听回调执行 `wipeCollectorStorage()`，清理 hotdir 中除 `__HOTDIR__.md` 外的条目，以及 `storage/tmp` 中除 `.placeholder` 外的条目；`trashFile` 只删除文件，不删除目录。

| 终态 | 当前源码行为 | 平台契约/治理要求 |
|---|---|---|
| 正常转换 | ffmpeg 生成 WAV，返回 `{success:true, reason:null, wavFilename}`；源文件 finally 删除 | 输出文件由调用者显式取得所有权；读取完成后删除或转为正式制品，记录资源释放证据 |
| 参数/路径/源文件失败 | 返回 `success:false`、reason、`wavFilename:null`；未进入转换时没有源文件可清理 | 错误码区分空输入、路径越界、源不存在；路径校验在任何 I/O 前完成 |
| ffmpeg 失败 | catch 返回失败；finally 删除源文件；失败时可能留下部分/损坏的 outputPath，源码未显式清理输出 | 运行核心必须登记输出临时资源；失败、超时、取消、provider 崩溃统一删除临时输出并做残留扫描 |
| 进程崩溃/重启 | 下次 collector 启动粗粒度 wipe hotdir/tmp；不按任务租约恢复，也不区分其他并发任务 | 用 operation id/租约目录隔离；只清理已过期或本进程所有的临时资源，避免并发任务互删；启动清理只作兜底 |
| 直接上传/parseOnly | `writeToServerDocuments` 将 `parseOnly` 写入 `direct-uploads`，普通文档写 `documents/custom-documents` | 支持库明确“暂存→正式制品”的原子转移与 owner；模块决定是否进入知识库，不旁路写正式目录 |

**关键安全边界。** `isWithin` 明确不检测 symlink；因此平台若要把 hotdir 作为通用能力，必须增加 realpath/symlink 策略或把目录放入受控沙箱。当前 `wipeCollectorStorage` 使用目录枚举加 `rmSync`，并发下没有租约/操作 id，属于项目级启动兜底而非可复用的安全清理器。

### 16.5 音频转换的支持库/模块/运行核心边界

音频能力的规范输入应为 `{source: 临时资源句柄或受限相对路径, targetFormat: "wav", sampleRate: 16000, channels: 1, sampleEncoding: "pcm_f32le", operationId, timeout}`；不应把绝对路径直接作为公共模块参数。规范输出为 `{artifact: 临时/正式制品句柄, format:"wav", sampleRate:16000, channels:1, encoding:"pcm_f32le", size, digest, cleanupOwner}`，失败输出为统一错误码（`PATH_INVALID`、`SOURCE_NOT_FOUND`、`PROVIDER_UNAVAILABLE`、`CONVERSION_FAILED`、`TIMEOUT`、`CANCELLED`），并标明可重试性。

- **支持库**：文件句柄/路径安全、音频格式契约、临时制品登记、摘要和原子转移；不得直接承载业务“转写/入库”流程。
- **模块库**：选择“音频转 WAV→Whisper/解析→文档块”的领域顺序，决定成功后谁取得输出所有权、失败时如何回滚；不得直接调用 shell 或持有 ffmpeg 路径。
- **运行核心**：通过受管 provider 启动 ffmpeg，使用结构化参数列表、独立进程组、超时、输出上限、SIGTERM→SIGKILL 和 wait/reap；对临时文件执行 finally 清理和残留审计。
- **项目适配层**：把 AnythingLLM 的 hotdir 文件名、collector endpoint、Whisper 配置和旧 `{success,reason,wavFilename}` 结果映射到平台契约。

现有 `FFMPEGWrapper` 使用 `execSync("which ffmpeg")`、`execSync("<path> -version")` 和 `spawnSync(ffmpeg, args)`；这能证明外部转换边界，但不能直接吸收为平台运行核心实现，因为命令字符串拼接、同步等待、无显式超时/进程组回收和失败输出清理均未形成底座契约。验证测试存在于 `collector/__tests__/utils/WhisperProviders/ffmpeg/index.test.js`，但当前核对未执行。

### 16.6 部署边界与运行时归属

Dockerfile 安装 Node、FFMPEG、Chromium 依赖和 uvx，构建 frontend 静态物料、server production dependencies 与 collector production dependencies，最终以 `docker-entrypoint.sh` 启动；compose 将 `server/storage`、`collector/hotdir`、`collector/outputs` 映射到宿主并暴露 3001。云部署模板把同一应用映射到 AWS/GCP/DigitalOcean/Helm/K8s/OpenShift/Hugging Face 等平台。由此应裁决：

- server、collector、frontend 的进程拓扑属于**项目运行方案**；平台运行核心只提供进程监督、健康检查、端口/目录/环境契约，不复制 AnythingLLM 的业务入口。
- `STORAGE_DIR`、`COLLECTOR_PORT`、Whisper/OCR 配置、向量库/LLM endpoint、Docker volume、Ingress 和云 provider 配置属于**项目适配层/部署包**；平台只校验声明、密钥引用、路径和资源预算。
- FFMPEG、Chromium、OCR、Whisper、Office/PDF 库属于**受管 provider**。缺失应返回 `PROVIDER_UNAVAILABLE` 或宿主不可用，不在支持库中伪造降级成功。
- `open-computer` 是 QEMU + overlay 的独立 Agent 电脑环境，仍应保持独立运行边界；其镜像、overlay、CDP、网络和密钥不能被默认并入 server/collector 的同一权限域。
- 部署健康检查只能证明进程/端口可达；不能代替 collector 真实解析、签名验证、hotdir 清理、FFMPEG 转换、文件/向量/Prisma 一致性验证。

### 16.7 后续验收契约、验证等级与剩余风险

| 验证等级 | 必须证明的事实 | 本地证据/建议命令 | 当前判定 |
|---|---|---|---|
| L0 静态 | 路由映射、签名 middleware、hotdir 清理、FFMPEG 参数、部署挂载存在且路径对应 | `grep -R "X-Integrity\|X-Payload-Signer\|wipeCollectorStorage\|convert-audio-to-wav" collector server`；审阅 `collector/index.js`、`collector/extensions/index.js`、`server/utils/collectorApi/index.js`、`docker/*` | **已完成源码取证**；未使用目标专属 codegraph（服务器绑定其他仓库） |
| L1 契约 | 缺签名/篡改正文/越界路径/空输入/未知扩展类型的结果形状和稳定错误码；路由 alias 只在唯一入口转换 | collector/server Jest 定向测试；当前已有 `collector/__tests__`，但当前核对未执行 | **待核**；源码存在行为，统一错误码与 canonical JSON 尚未证明 |
| L2 真实 provider | 真实 FFMPEG 16kHz/mono/`pcm_f32le` 输出；缺 binary、非音频、超时、失败输出清理 | `yarn test collector/__tests__/utils/WhisperProviders/ffmpeg/index.test.js`（以项目实际脚本为准）+ 独立检查输出文件/残留 | **待核**；不能以测试文件存在代替执行 |
| L3 进程协作 | server→collector 签名请求、扩展长请求 15 分钟超时、collector 重启后临时资源清理、并发任务不互删 | 启动 server/collector 的隔离环境，执行签名/扩展/音频链路，读回 HTTP、文件、进程和临时目录 | **未验证**；当前核对遵守只改文档边界未启动服务 |
| L4 部署 | Docker build/entrypoint/healthcheck、volume 持久化、FFMPEG/Chromium/provider 可用性、多架构行为 | 在隔离 Docker 项目运行 compose healthcheck，并检查挂载目录及退出后残留 | **未验证**；未构建/启动镜像 |

**单一链路验收标准。** 未来平台化实现必须能够从一次 `operationId` 追踪：请求签名 → 路由/能力 id → 模块调用 → provider 进程 → 临时资源创建 → 输出摘要 → 正式制品/文档写入 → 向量/元数据投影 → 清理证据。任何直接写 hotdir、直接调用 ffmpeg、绕过唯一签名验证或扩展自行维护第二套路由/错误码的路径，都判为侧链。

**剩余风险。** (1) collector 的 HTTP 200 + `success:false` 与 HTTP 400/500 混用；(2) 当前签名没有从源码中确认 canonicalization、时间窗、nonce、轮换和重放保护；(3) `isWithin` 不防 symlink；(4) FFMPEG 同步执行且缺少显式超时/进程组治理，失败 output 清理不完整；(5) hotdir 启动 wipe 没有租约，存在并发互删/崩溃后误删边界；(6) 文件、Prisma、向量库和 collector 暂存区不是单事务；(7) 当前核对没有运行测试、服务或容器，所有 L1-L4 均不能宣称通过。

### 16.8 后续修改与证据边界

- 当前核对唯一修改文件：项目根 `ARCHITECTURE.md`；未修改源码、配置、依赖、测试、README、Git 或旧细探文件。
- 目标项目本地源码证据：`collector/index.js`、`collector/extensions/index.js`、`collector/middleware/verifyIntegrity.js`、`collector/middleware/setDataSigner.js`、`collector/convertAudioToWav/index.js`、`collector/utils/files/index.js`、`collector/utils/WhisperProviders/ffmpeg/index.js`、`server/utils/collectorApi/index.js`、`server/endpoints/extensions/index.js`、`docker/Dockerfile`、`docker/docker-compose.yml`。
- 本轮未调用 `system_engineering_toolkit` 或其他 MCP；目标仓库独立 `.codegraph/` 的 `up to date` 状态仅作导航证据，最终结论仍以目标源码逐段读取为准。
- 当前核对未执行测试、安装、启动、构建、容器或部署命令；后续执行必须在目标根目录、隔离资源和明确验证等级下进行，并将退出码、测试数、跳过数、provider 状态及临时资源清理结果入账。

## 17. 后续深挖收口：workspace、文档摄取、向量库、Provider、插件、任务与 API

本节是后续内部事实审计，仍以本地源码基线 `c8bd6442e6b6eee8d08a761452960f7f77e334a9` 为准；只补充 AnythingLLM 已有实现，不把后续平台设想写成当前实现。旧细探 `细探-anything-llm.md` 已逐条对照：其“hotdir 热目录监听”仍裁决为错误线索，其他概览内容已在前文吸收；旧文件按用户要求保留，不是新的权威事实源。

### 17.1 Workspace 聚合对象与配置契约

`workspaces` 是配置、权限、文档关联、聊天和 Agent 的聚合根，但不是单一事务边界。`server/models/workspace.js:35-141` 只允许 `writable` 白名单字段写入：`name`、温度/历史、提示词、相似度阈值、chat/agent provider 与 model、`topN`、`chatMode`、`vectorSearchMode`、`router_id`；`slug`、`vectorTag` 和头像路径不能通过通用更新写入。验证器将非法值归一（例如 `chatMode` → `automatic`、阈值夹到 `0..1`、`topN` 最小为 1、`vectorSearchMode` 仅 `default/rerank`）。

创建链是 `POST /workspace/new` → `Workspace.new` → `slugify`/冲突时随机八位后缀 → 读取系统默认 prompt → Prisma 创建 → 可选 `WorkspaceUser.create` → telemetry/event log。更新链是 `POST /workspace/:slug/update` → 当前用户/角色和 workspace 权限检查 → `Workspace.trackChange` → `Workspace.update`；切到 `anythingllm-router` 会清空 `chatModel`，切离 router 会清空 `router_id`，把 `chatProvider` 设为 `default` 会同时清空 provider/model。读取时 `Workspace.get/getWithUser` 还计算 provider/model 的 `contextWindow` 与 `workspace_parsed_files` token 总量，因此读取不是纯 Prisma 行返回。

权限边界由路由 middleware 先于领域模型执行：创建/设置/上传/嵌入/删除要求 admin/manager；普通聊天、列表和读取允许 all，但多用户读取会通过 `workspace_users` 过滤，admin/manager 走全局可见路径。`workspace_deletion_protection` 只保护删除入口，不能把后续跨存储清理变成事务。

| Workspace 节点 | 前置/输入 | 状态写入 | 成功/失败语义 | 证据 |
|---|---|---|---|---|
| 创建 | 名称非空、管理员角色 | `workspaces`、可选 `workspace_users`、telemetry/event log | 统一 HTTP 200 携带 `{workspace,message}`；异常 HTTP 500 | `server/endpoints/workspaces.js:50-83`、`server/models/workspace.js:194-233` |
| 更新 | 已授权 slug、白名单字段 | `workspaces`、prompt history/change tracking | 无有效字段返回业务 message；Prisma 异常转 message/500 | `server/endpoints/workspaces.js:86-114`、`workspace.js:242-289` |
| 删除 | 已授权、删除保护通过 | 先删 chats、`document_vectors`、workspace docs、workspace，再删 vector namespace | 外部 namespace 删除异常只记录，不阻断 HTTP 200 | `server/endpoints/workspaces.js:275-319` |
| 查询 | 已授权 slug | 读取 Prisma + 文件 token 统计 | 不存在仍可返回 `{workspace:null}` | `server/endpoints/workspaces.js:381-398`、`workspace.js:364-385` |

**收口结论：** workspace 配置契约清晰，但删除顺序是“元数据先删、向量 namespace 后删”，且没有删除 `storage/documents` 源文件和 `vector-cache`；namespace 删除失败会形成孤儿向量。平台若复用该模式必须显式记录删除 operation、补偿队列和残留扫描，不能把 `HTTP 200` 当作全链路删除成功。

### 17.2 文档摄取的两条入口与状态机

文档摄取有“上传/链接先由 collector 解析”与“已解析文件再嵌入 workspace”两个阶段，不能合并成一个原子 API：

```text
multipart/API 文件或 URL
  → multer 写入 collector/hotdir
  → server CollectorApi.online/processDocument/processLink
  → server→collector body JSON + X-Integrity（生产）+ 可选 X-Payload-Signer
  → collector 选择 converter/extension，生成 Document[]
  → storage/documents/<folder>/<json>（pageContent + metadata）
  → Document.addDocuments / native embedding-worker
  → TextSplitter → Embedder.embedChunks
  → VectorDB namespace（workspace.slug）
  → document_vectors(docId, vectorId)
  → workspace_documents(docId, docpath, metadata)
```

**阶段 A：解析/制品写入。** `POST /v1/document/upload` 和 `/v1/document/upload/:folderName` 先由 `handleAPIFileUpload` 接收文件；`CollectorApi.processDocument` 负责 collector 可用性检查和签名转发。文件入口默认写入/交换 `collector/hotdir`，collector 返回解析后的 `location`。带 folder 的 API 先做 `normalizePath` + `isWithin`，解析后把 JSON 制品从当前目录 `renameSync` 到目标 folder，再以新 location 做后续 workspace upsert。`POST /v1/document/upload-link` 走 `processLink`；纯文本、parse-only、扩展同步则复用 collector 的不同端点。

**阶段 B：workspace upsert。** `Document.addDocuments` 对每个 `docpath` 读取 `storage/documents` JSON，生成新的 UUID `docId` 和 Prisma 行，但先调用 `VectorDb.addDocumentToNamespace`，向量化成功后才创建 `workspace_documents`。`Document.removeDocuments` 则先删 namespace 中该 doc 的 vector ids，再删 workspace row 和 `document_vectors` 映射。文档文件本体仍由 `purgeDocument`/`purgeFolder` 或清理任务负责，不由 `removeDocuments` 自动删除。

| 摄取节点 | 真实行为 | 失败/恢复事实 | 证据 |
|---|---|---|---|
| 文件上传 | multer→collector；默认单请求 body/文件边界；collector offline 时 server 返回 500 + `success:false` | 已写入 hotdir 的中间文件依赖 collector 启动清理；未见 operation lease | `server/endpoints/api/document/index.js:49-172`、`server/endpoints/workspaces.js:116-164` |
| 解析 | converter/extension 返回 `Document[]`，错误可能 HTTP 200 + `success:false` 或 HTTP 400 | server 既检查 online 又检查返回 `success`；跨阶段不是事务 | `collector/index.js:45-228`、`server/utils/collectorApi/index.js:257-285` |
| 文件制品 | JSON 保留 `pageContent`，元数据写入同一 JSON；`DocumentManager` 按 `docpath` 再读 | `fileData` 做路径归一和 within 检查，但不防 symlink；JSON 损坏则读失败 | `server/utils/files/index.js:23-33`、`DocumentManager/index.js:20-68` |
| workspace upsert | sequential loop；每文档独立生成 docId、向量、映射、workspace row | 向量已写入而 Prisma create 失败时没有回滚；重复调用会生成新 docId/向量，未见幂等键 | `server/models/documents.js:83-201` |
| native worker | `embedFiles` 按 workspace slug 复用一个 Bree child process，可中途 `add_files` 或移除队列文件 | worker 异常发 `all_complete` 错误事件；处理中取消只影响尚未开始的文件 | `server/utils/EmbeddingWorkerManager.js:17-193`、`server/jobs/embedding-worker.js:29-199` |

`/workspace/:slug/update-embeddings` 对 native embedder 将新增文件放进 worker，非 native 则在请求内同步执行；删除始终先执行 `Document.removeDocuments`。进度通过 `/workspace/:slug/embed-progress` SSE 推送，按 slug 保存连接和最多 10 秒事件历史，连接关闭只移除 response，不会取消 embedding worker。

**重要摄取风险：** `storage/vector-cache` 的 key 是 `uuidv5(filename, uuidv5.URL)`，只由文件路径决定；没有把 embedding engine、model、维度或 splitter 参数纳入 key。切换 embedder/model 后源码只提供“用户应清理 cache”的提示性能力，不能证明自动失效；缓存复用也不会重新验证当前 vector dimension。平台借鉴时必须使用内容摘要 + embedder/model/splitter 版本指纹，并为 cache hit 声明校验结果。

### 17.3 向量库契约、映射和检索上下文

`VectorDatabase` base contract（`server/utils/vectorDbProviders/base.js:17-200`）要求 provider 实现连接/heartbeat、namespace 探测与统计、文档增删、相似度搜索、namespace 删除/reset、source curate。factory（`server/utils/helpers/index.js:87-126`）按 `VECTOR_DB` 选择 LanceDB、Pinecone、Chroma/ChromaCloud、Weaviate、Qdrant、Milvus、Zilliz、AstraDB、PGVector，未知值回退 LanceDB；因此“配置值未知”不是硬失败，而是日志 + 本地 provider fallback。

以 LanceDB 为具体证据：

1. `connect()` 是按进程的静态单例连接，URI 为 `STORAGE_DIR/lancedb`；namespace 是表名。
2. `addDocumentToNamespace` 先读取 cache；cache hit 时把缓存 chunks 重新生成新的 vector ids、写 LanceDB、再 `DocumentVectors.bulkInsert`。cache miss 时用 `TextSplitter` 生成 chunks，调用当前 embedder，向量分批写入 LanceDB，落 vector-cache，再批量写 `document_vectors`。
3. `performSimilaritySearch` 先 namespace 存在检查，再 `LLMConnector.embedTextInput`；普通模式 cosine + `topN` + threshold，rerank 模式先取 `10..50` 个候选再 `NativeEmbeddingReranker`，最后 `curateSources` 将向量元数据转换成 chat sources。
4. 删除文档通过 `document_vectors` 找 vector ids，再在 namespace 执行 `id IN (...)`；删除 namespace 只 drop table，不同步删除 `document_vectors`、`workspace_documents`、source JSON 或 cache。

```text
Document.addDocuments
  → VectorDb.addDocumentToNamespace
  → cache hit ? cache chunks : TextSplitter + Embedder.embedChunks
  → Vector namespace write
  → vector-cache write（miss）
  → DocumentVectors.bulkInsert（Prisma transaction 仅覆盖 mapping rows）
  → workspace_documents.create
```

这里唯一的数据库事务是 `DocumentVectors.bulkInsert` 内部的 Prisma `$transaction(inserts)`；它不覆盖 vector DB、cache 或 workspace row。若 namespace 写成功而 mapping/row 失败，后续按 docId 找不到向量；若 mapping 成功而 namespace 删除失败，反之亦然。`Document.removeDocuments` 对 vector delete 没有外围补偿事务；`purgeFolder` 用 `Promise.all` 并发移除多个 workspace 文档后直接 `rmSync` 文件夹，任何失败不会形成可重试清单。

### 17.4 LLM、Embedding 与 Model Router 的 provider 生命周期

普通聊天调用 `resolveProviderConnector`：若 workspace provider 不是 router，factory 立即实例化 `getLLMProvider({provider,model})`，provider 实例携带 embedder；若是 `anythingllm-router`，先由 `ModelRouterService.gatherRoutingContext` 收集 workspace/user/thread/API session、历史 token/message 数和附件，再 `AnythingLLMModelRouter.resolve` 返回 delegate provider、routing metadata 和 prefetched context。Agent 的 `EphemeralAgentHandler` 有相同 fallback：agent provider/model → workspace chat provider/model → 系统 `LLM_PROVIDER`/默认 model；router 会在每个 Agent turn 重新解析。

| Provider 层 | 创建/持有 | 关键输入输出 | 失败/释放边界 |
|---|---|---|---|
| LLM | 每次 connector/agent 初始化按 provider/model 创建适配器 | `getChatCompletion` 或 `streamGetChatCompletion`；可报告 streaming、prompt window、metrics | 缺 key/base path 多在 `AgentHandler.checkSetup` 抛错；未见统一 provider 错误码或连接池释放契约 |
| Embedding | `getEmbeddingEngineSelection` 每次选择 native/远端 embedder；native 模型缓存目录 `storage/models` | `embedTextInput`/`embedChunks` 返回向量；chunk 并发由 provider 限制 | native pipeline 按 model 静态单例缓存，因为 onnxruntime `dispose()` no-op；没有释放 API，进程生命周期是释放边界 |
| Vector DB | factory 每次取 provider；LanceDB connection 是静态单例 | namespace/table、vector rows、search sources | 外部 provider client/HTTP 会话的关闭由各适配器负责，base contract 未要求 `close()`；未知配置回退 LanceDB |
| Router | 单例/缓存 route、sticky route、规则/LLM classification、通知去重 | delegate connector + `routingMetadata` + 预取上下文 | route 失败由 chat 层返回 abort；router 本身没有独立资源回收契约 |

**上下文装配顺序：** `streamChatWithWorkspace` 先检查 namespace/count，再取 pinned docs（受 `promptWindowLimit` token cap）、thread/user parsed files，再向量检索和可选 rerank，拼历史/系统 prompt/附件，交给 connector 压缩消息；成功响应写 `workspace_chats`，SSE 只写 `close:true` 事件不等于数据库已写成功。Pinned 文件是直接读取 JSON 全文，且其来源会从 vector search 结果中过滤；parsed files 是独立的 `workspace_parsed_files` 临时/附件域。

### 17.5 内置插件、Flow、MCP 与 Community Hub

Agent plugin 不是单一目录扫描：`defaults.js` 组合内置默认技能、system settings 配置技能、可用性检查和 multi-user 排除；`EphemeralAgentHandler.#loadAgents/#attachPlugins` 再把内置单阶段插件、`parent#child` 子技能、`@@flow_<uuid>`、`@@mcp_<server>`、`@@<hubId>` imported plugin 解析为 Aibitat plugin 并调用 `aibitat.use()`。`AIbitat` 以 `agents/channels/functions` Map 持有本次 invocation 状态，默认 `AGENT_MAX_TOOL_CALLS` 为 10（`maxRounds` 默认 100），工具结果、citations、附件和澄清问卷暂存在实例 buffer，chat-history plugin 最终持久化后才清空部分 buffer。

| 插件来源 | 激活/装载 | 权限与资源 | 失败事实 |
|---|---|---|---|
| 内置 plugin | system settings + availability + disabled sub-skills；multi-user 禁用 `create-scheduled-job` | 运行在 server 进程，可读写文件/邮件/SQL/网络，部分工具走审批 | 无效 plugin 名称只日志并跳过；可用性检查不是执行成功证明 |
| Agent Flow | `@@flow_<uuid>` → `AgentFlows.loadFlowPlugin`，替换 agent function 名 | Flow 文件在 storage，运行时注册到当前 Aibitat | Flow 不存在只跳过；未形成版本/锁定快照 |
| MCP | `@@mcp_<server>` → `MCPCompatibilityLayer.convertServerToolsToPlugins`，每个 server tool 成为子 plugin | MCP hypervisor/transport 是外部连接，session 生命周期不由 base plugin 契约统一声明 | server/tool 不存在跳过；需额外核对 close/断线/重连和凭据清理 |
| Community imported | `storage/plugins/agent-skills/<hubId>/{plugin.json,handler.js}`；只加载 `active:true` | `handler.js` 被本地 `require`；导入包强制 `active:false`，插件需要显式启用；每次 load 删除 require cache | path/Zip Slip 有检查，zip 最终删除；下载无统一超时/HTTP 状态校验，解压失败可能留下部分目录，覆盖没有事务回滚 |

Imported plugin 的 handler 从磁盘加载并把配置 JSON schema 转为 Aibitat function，`requestToolApproval` 由宿主闭包注入，防止 handler 覆盖；但当无审批通道（例如 scheduled job）会自动批准。Community Hub 本身还可以直接把 system prompt 写入 workspace、创建 slash command；这些是外部内容到本地状态的写操作，应按 API 权限和审计边界看待，不能只当“插件下载”。

### 17.6 Scheduled Job 任务状态机、并发与取消

任务只允许 single-user mode 路由使用。`BackgroundService` 是 singleton：Bree 管理固定清理/记忆/文档同步 job，`later` 以 UTC 解释 cron；自定义 scheduled job 使用进程内 cron timer → `PQueue`（默认并发 1，可由 `SCHEDULED_JOB_MAX_CONCURRENT` 调整）→ Bree child process `run-scheduled-job.js`。数据库通过 `ScheduledJobRun.start` 的交互事务检查同一 job 是否存在 `queued/running`，实现跨 cron/手动触发的单 job in-flight 去重。

```text
create/update/toggle/trigger API
  → ScheduledJob 校验 cron、JSON tools、active cap
  → BackgroundService timer 或 enqueue
  → ScheduledJobRun.start（事务 claim: queued）
  → PQueue → Bree child process
  → markRunning + update last/next timestamps
  → EphemeralAgentHandler + toolOverrides
  → 自动批准 tool → agent cluster
  → complete/fail/timed_out/killed
  → scheduled_job_runs.result/error → 可选 continueInThread
```

`run-scheduled-job.js` 使用 `Promise.race` 实现 `SCHEDULED_JOB_TIMEOUT_MS`；超时标记 `timed_out`，finally `conclude()` 对 child process 执行 `process.exit(0)`。用户 kill 先尝试 `BackgroundService.killRun`，worker 收到 SIGTERM 后把 run 标为 killed 语义（数据库实际状态是 `failed` + `Job killed by user`）。server 冷启动 `failOrphanedRuns` 将所有 queued/running 标记为 `failed` + `Server restarted during execution`；删除 job 先移除 timer/发送 SIGTERM，再依赖 FK cascade 删除 runs。

**任务资源风险：** scheduled job 运行时强制 `requestToolApproval = approved:true`，所以 tool 白名单（空数组表示无工具、非空表示只加载所选工具）是主要安全边界；超时是子进程退出兜底，不是 provider 请求的结构化取消协议。任务结果 JSON 可能包含 text、thoughts、toolCalls、outputs、metrics，生成文件由 `cleanup-generated-files` 按 chat/run 引用清理；继续到 thread 会创建/复用 `scheduled-jobs` workspace 和新 thread，属于一次额外持久化投影。

### 17.7 API 契约与错误/流资源语义

除内部 `/api` 路由外，Developer API 统一挂 `/api/v1` 并由 `validApiKey` 保护。核心契约如下：

| API | 输入/边界 | 输出与持久化 | 当前缺口 |
|---|---|---|---|
| `POST /v1/document/upload[/:folderName]` | multipart `file`，可选 `addToWorkspaces`（逗号 slug）、metadata；folder 做 path 安全 | collector 返回 `documents[]`，可选 sequential upsert workspace | collector offline/解析失败通常 HTTP 500；已上传文件残留需另行清理 |
| `POST /v1/document/upload-link` | `link`、可选 scraper headers/metadata/workspaces | collector `processLink` → JSON 制品 → 可选 embedding | URL/抓取错误在不同层有 HTTP 400/500 + reason 混用 |
| `POST /v1/workspace/:slug/update-embeddings` | `adds[]/deletes[]`，`validApiKey` | vector namespace、mapping、workspace docs | 无 operation id/幂等键；native 分支异步，非 native 分支同步，响应时序不同 |
| `POST /v1/workspace/:slug/chat`、`/stream-chat` | prompt/history/attachments，API key；workspace slug | sync JSON 或 SSE；成功最终写 `workspace_chats` | 客户端断开/上游 abort 的资源取消需依赖 provider/handler，未见统一 `AbortController` 契约 |
| `GET /v1/openai/models` | API key | workspace slug 伪装 model list | 全量扫描 workspace，无分页 |
| `POST /v1/openai/chat/completions` | `model` 必须是 workspace slug；最后一条 message 必须 user；`stream` 可选 | `OpenAICompatibleChat` 同步 JSON 或 SSE | 只支持部分 OpenAI 字段；错误多为 401/400/500 或 AnythingLLM abort 形状 |
| `POST /v1/openai/embeddings` | `input` 或兼容旧键 `inputs`；字符串或字符串数组，拒绝空/非字符串 | 当前 embedder 向量 list | provider/embedChunks 失败统一 HTTP 500，无稳定错误码 |
| `GET /v1/openai/vector_stores` | 无 query 时全量；带 query 直接空页 | workspace slug + Prisma document count，不直接查询向量 provider | `file_counts` 是 metadata 行数，不是实际 namespace vector row 数；固定 `has_more:false` |
| `/scheduled-jobs/*` | single-user；cron、tools、prompt | job/run rows、worker、可选 thread | kill/timeout/重启能落终态，但没有通用幂等键和外部 provider cancellation |

SSE/WS 的资源边界必须区分：普通聊天把 `close:true` 写入协议事件；workspace embed-progress 在 request close 时只释放 SSE response 引用；Agent WebSocket close 会 `aibitat.abort()`（仅 bail command）并把 invocation `closed=true`，普通 socket close 处理器只记录关闭并标记数据库。`EphemeralEventListener` 把 Agent 事件缓存在内存数组，等待 `closed` 后打包 thoughts/text/outputs/metrics/citations；若异常路径没有 close 事件，调用方可能一直等待。

### 17.8 资源生命周期与四种终态矩阵

| 资源 | 创建/持有 | 正常完成 | 业务失败 | 取消/超时 | 宿主/子进程崩溃与残留验证 |
|---|---|---|---|---|---|
| `storage/documents/*.json` | collector/文件 API 写入；Document 以 `docpath` 借用 | 长期保留，workspace row 指向它 | parse 失败可能留 hotdir/中间物；清理任务/`purgeDocument` 删除 | 无统一取消回滚 | collector 启动 `wipeCollectorStorage` 只清 hotdir/tmp；需扫描 documents orphan |
| `storage/vector-cache/*.json` | LanceDB cache miss 写入，key=文件名 UUIDv5 | 供后续复用 | vector/provider 或 mapping 失败可能保留 | 无 operation owner | `purgeDocument`/`purgeFolder` 可删；workspace delete 不删；需按 docpath/model 指纹审计 |
| LanceDB/外部 namespace | provider `connect` 静态/外部 client | rows + namespace 保留 | provider 异常可能部分写入；无统一 rollback | 搜索/embedding 无统一取消 | namespace 删除失败被吞并记录；需 count/name 与 mapping 对账 |
| `document_vectors` | 每批 vector id 在 Prisma transaction 写入 | mapping 与向量对应 | transaction 只保证 mapping 批次，不保证外部 rows | 无 cancel hook | orphan vectorId/docId 需对账，不能只查 Prisma |
| `workspace_documents` | 向量化后单行 create | metadata/docpath 指向制品 | create 失败时外部 vector/cache 已存在 | 无回滚 | workspace delete 删除 row 但不删除 source JSON/cache |
| native embedding pipeline/model | `NativeEmbedder` model path + static pipeline map | 进程内复用 | 下载/ONNX 错误返回异常 | 无 dispose；依赖进程终止 | pipeline promise finally 清 map entry，但成功 pipeline 永久缓存；检查 `storage/models` 大小/权限 |
| embedding worker/Bree child | `BackgroundService.spawnWorker` | `all_complete`→exit→remove Bree job | unexpected exit→合成 `all_complete` error，移除 job | remove queue 只影响未处理项；无主动 worker cancel API | 子进程退出由 parent 事件清理 map；需读回进程、Bree registry、SSE history |
| SSE/WS | request/response 或 socket 注册 Map/EventEmitter | close/end 后删除连接或 invocation closed | 写失败会删除 SSE response；WS exception close socket | bail 调 `aibitat.abort`；普通 client disconnect 不等同 cancel | `eventHistory` all_complete 后 10 秒删除；需检查 Map/未结束 listener |
| Agent plugin/MCP | 每次 Aibitat 实例 `use()`；MCP 建立 transport | chat-history/citation/output 持久化，再实例自然释放 | 工具错误进入 AIbitat error/trace；插件本地副作用不自动回滚 | abort/terminate 事件；插件是否响应取决于实现 | MCP transport close 路径分散，需查 hypervisor 状态；不得以 socket close 证明第三方会话已关 |
| scheduled job run | Prisma claim `queued`，worker→`running` | `completed` + JSON result | `failed` + error | `timed_out` 或实际 DB `failed` kill 语义 | cold boot `failOrphanedRuns`；检查 worker PID、queued/running rows、generated files |
| generated output files | Agent tool 写 storage，chat/run 保存引用 | 被引用时保留 | 工具失败可能留文件 | kill/timeout 不保证删除 | `cleanup-generated-files` 以 workspace chat/run 引用集合清理；需文件与引用反查 |
| Prisma client/DB | module singleton `PrismaClient` | server 生命周期持有 | 事务失败回滚其范围内写入 | 无请求级关闭；进程退出释放 | 不要把 `$transaction` 误认跨 provider 事务；检查 SQLite locks/连接错误 |

### 17.9 后续真假验证表与裁决

| 事实项 | 源码存在 | 测试源码 | 当前核对真实执行 | 外部依赖实测 | 判定 |
|---|---|---|---|---|---|
| workspace 白名单/值归一 | `workspace.js:35-141` | 相关 model/endpoint 测试存在 | 未执行 | 无 | **静态已证，运行待核** |
| collector→制品→workspace upsert | `collectorApi`、`documents.js`、document API | collector/server 单测存在 | 未执行 | collector/Prisma/vector 未启动 | **实现链存在，跨存储一致性未证** |
| native worker/SSE 进度 | `EmbeddingWorkerManager.js`、`embedding-worker.js`、endpoint | embedding/worker 相关测试需定向确认 | 未执行 | ONNX/model download 未测 | **实现存在，崩溃/取消未证** |
| vector base/factory/Lance mapping | `base.js`、factory、`lance/index.js`、`vectors.js` | vector provider 测试存在 | 未执行 | LanceDB 未连接 | **静态已证，孤儿/维度漂移未证** |
| LLM/embedding/router 选择 | `helpers/index.js:87-323,634-695` | provider/helper/router 测试存在 | 未执行 | 没有真实 LLM/embedder | **静态已证，缺 key/断线/重试未证** |
| plugin/Flow/MCP/Hub | `defaults.js`、`ephemeral.js`、`imported.js`、`CommunityHub` | defaults/MCP 测试存在 | 未执行 | 无 MCP/Hub/第三方工具 | **静态已证，权限/关闭/污染未证** |
| scheduled job 终态 | `BackgroundService`、`ScheduledJobRun`、worker/API | scheduled job 测试需定向确认 | 未执行 | 未启动 Bree/SQLite worker | **静态已证，真实 kill/timeout/重启未证** |
| OpenAI-compatible API/SSE | `api/openai/index.js`、`openaiCompatible.js` | compatibility script/单测存在 | 未执行 | API key/服务未启动 | **契约静态已证，客户端兼容性未证** |

当前核对后续收口的唯一事实结论是：**AnythingLLM 的模块契约已具备，但资源和一致性契约仍是“分段 best effort”而不是全局事务。** 可吸收的是 workspace 白名单、collector converter 分派、provider base contract、native worker 隔离、scheduled run 的数据库去重和 Agent plugin 装载分层；应隔离/待核的是文件-向量-Prisma 三方原子性、cache 指纹、未知 provider fallback、SSE/WS 取消、MCP close、社区插件安装回滚、任务 timeout 的结构化取消以及 workspace 删除后的外部残留。

### 17.10 当前核对修改与证据边界

- 当前核对仅追加修改目标根 `ARCHITECTURE.md`；未修改源码、依赖、配置、测试、README、旧细探、submodule 或 Git。
- 旧细探逐条核对结果已在第 15 节和本节体现；“hotdir 热目录监听”明确废弃为未证实/错误表述，未删除旧文件以保留溯源。
- 当前核对静态读取的关键证据包括：`server/models/workspace.js`、`server/models/documents.js`、`server/utils/files/index.js`、`server/utils/files/purgeDocument.js`、`server/utils/EmbeddingWorkerManager.js`、`server/jobs/embedding-worker.js`、`server/utils/vectorDbProviders/base.js`、`server/utils/vectorDbProviders/lance/index.js`、`server/utils/helpers/index.js`、`server/utils/chats/stream.js`、`server/utils/agents/{defaults.js,ephemeral.js,imported.js,index.js}`、`server/utils/BackgroundWorkers/index.js`、`server/jobs/run-scheduled-job.js`、`server/models/{scheduledJob,scheduledJobRun,workspaceAgentInvocation,vectors}.js`、`server/endpoints/{workspaces,scheduledJobs,agentWebsocket}.js`、`server/endpoints/api/{document,openai}/index.js`、`server/prisma/schema.prisma`。
- 未执行安装、测试、启动、构建、容器、真实 provider、MCP、Community Hub 或清理验证；所有 L1-L4 和本节“未证”项必须保持未验证，不能用源码存在或历史日志替代运行证据。
