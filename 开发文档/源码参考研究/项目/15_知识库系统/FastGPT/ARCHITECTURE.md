# FastGPT 架构建档

> 文档性质：唯一权威架构文档；基于当前本地源码、仓库规则、设计文档、测试布局与 CodeGraph 复核。旧细探只作为历史线索，不作为当前版本证据。
>
> 本文只描述已观察到的结构与行为；设计文档中的方案不等同于运行时代码已经完全实现。

## 1. 项目定位与证据边界

FastGPT 是一个以可视化 Flow 工作流为核心的 AI Agent 构建平台，提供数据处理、模型调用、知识库检索、工具执行、Agent 循环、插件/MCP、交互式节点和运行观测能力（`README.md:16`、`AGENTS.md:5-9`）。

本次分析目标：

- 项目根目录：`/Users/hekunhua/Documents/Agent/github 源码参考/15_知识库系统/FastGPT`
- 本地 Git 提交：`76687002`（完整提交见本次 Git 核对），已与 `origin/main` 同步，`git rev-list --left-right --count HEAD...origin/main` 为 `0 0`。
- 当前项目版本：根包仍为 `4.0`（仓库历史兼容字段），主应用 `projects/app` 为 `4.16.1`；Node 要求 `>=22.23.2`，pnpm `10.33.4`。
- 当前工作树：仅保留未跟踪 `.codegraph/` 与源码侧 `ARCHITECTURE.md`；本轮不改源码，不删除或覆盖这两个本地文件。
- 本轮先执行 `git fetch` 与 `git pull --ff-only origin main`，结果 `Already up to date`；没有发生源码覆盖。
- 证据优先级：当前源码/配置与当前 Git > 当前 CodeGraph > 仓库规则/设计文档 > 旧细探；远程新增能力只有在本地已同步后才可写入当前架构事实。

### 1.1 工具与证据可信度说明

- 本轮按用户授权未使用 MCP；使用目标仓库自带 `.codegraph/` 的 `codegraph status/explore`，不混用其他项目地图或证据。
- 目标 CodeGraph 当前为 3,960 files / 55,553 nodes / 185,440 edges，索引状态 `up to date`，覆盖 TypeScript、TSX、JavaScript、Rust、Go、YAML 等。
- 本轮仍为源码静态审计：没有安装依赖、启动 MongoDB/Redis/BullMQ/VectorDB、构建 Next、启动 4780 之外的本地服务或运行业务 E2E。
- 旧 `细探-FastGPT.md`（若存在）只作为历史导航；本文关键结论已回到当前源码行号，且不再维护第二份细探文档。

## 2. 总体架构

```text
浏览器 / OpenAI 兼容客户端 / 外链 / MCP 客户端
                    │ HTTP、SSE、文件接口
                    ▼
          projects/app（Next.js 全栈应用）
          ├─ 页面、React 组件、状态与国际化
          ├─ pages/api/*：API 边界、认证、限流、SSE
          └─ service/*：应用侧适配、权限、文件与响应编排
                    │ workspace 依赖
                    ▼
       packages/global（共享类型、常量、Zod/OpenAPI 合约）
       packages/service（领域服务、Mongo、Redis、BullMQ、AI、Flow）
       packages/web（共享前端组件/hooks/主题/i18n）
       packages/next（Next API/CORS/类型基础设施）
                    │
       ┌────────────┼────────────────────┬──────────────────┐
       ▼            ▼                    ▼                  ▼
 MongoDB       Redis/BullMQ          VectorDB             S3/对象存储
 业务文档      队列、缓存、停止标记    PG/Milvus 等           文件/图片/归档
       │
       └─────────────── 工作流节点、聊天、知识库、插件、计费 ───────┐
                                                                      ▼
       独立运行时：code-sandbox（Hono）、mcp_server（MCP）、volume-manager
       外部/商业：agent-sandbox、agent-sandbox-proxy、fastgpt-ide-agent、pro 子模块
```

核心分层不是传统纯后端 API，而是“共享合约 + Next 应用入口 + service 领域执行器 + 外部基础设施”的 monorepo。`packages/global` 负责跨端数据形状，`packages/service` 持有服务端业务与基础设施实现，`projects/app` 把页面/API/服务适配在一个 Next.js 应用中；工作流运行时再把持久化的 Store 节点转换为带状态的 Runtime 节点。

## 3. 仓库与包组织

### 3.1 Workspace

根 `pnpm-workspace.yaml` 声明：

- `packages/*`
- `projects/app`、`projects/code-sandbox`、`projects/marketplace`、`projects/mcp_server`、`projects/volume-manager`
- `pro/llm_benchmark/content_benchmark`、`pro/admin`、`pro/sso`、`pro/browser-sandbox`
- `document/`、`scripts/icon`、`sdk/*`

根 `package.json` 使用 `pnpm@10.33.4`，要求 Node `>=20.19.0`；根 `turbo.json` 把 `dev` 定义为持久任务，把 `build` 依赖上游包构建，把 `test` 的 MongoDB 测试 URI 和 worker 数量透传给任务（`package.json:4-52`、`pnpm-workspace.yaml:1-16`、`turbo.json:4-36`）。

### 3.2 主要包/项目职责

| 路径 | 包名/角色 | 主要职责 |
|---|---|---|
| `packages/global/` | `@fastgpt/global` | 前后端共享类型、常量、Zod schema、工作流/聊天/AI/OpenAPI 合约；依赖 `zod`、`openapi-types`、`zod-openapi`、`openai` 等（`packages/global/package.json:13-32`）。 |
| `packages/service/` | `@fastgpt/service` | Mongo/Mongoose 业务模型、Redis/BullMQ、聊天、工作流、知识库、AI/Agent、插件、权限、计费、文件和第三方适配（`packages/service/package.json:16-78`）。 |
| `packages/web/` | `@fastgpt/web` | Chakra UI、React 组件、Lexical 编辑器、React Query、Zustand、i18n 与前端共享能力（`packages/web/package.json:8-52`）。 |
| `packages/next/` | `@fastgpt/next` | Next API 相关中间件、CORS 与请求/响应类型。 |
| `projects/app/` | `@fastgpt/app` | 主 Next.js 应用；页面、React UI、`projects/app/src/pages/api/` API 路由、应用侧 service、主聊天入口。当前本地声明 `4.16.1`（`projects/app/package.json:1-24`）。 |
| `projects/code-sandbox/` | `@fastgpt/code-sandbox` | Hono HTTP 沙箱，JS 进程池、Python 隔离 runner、队列并发限制与安全边界；脚本为 `tsx watch src/index.ts`/`node dist/index.js`（`projects/code-sandbox/package.json:1-46`）。 |
| `projects/mcp_server/` | `@fastgpt/mcp_server` | 独立 MCP Server，将 FastGPT 应用/工作流暴露给 MCP 客户端；采用 Bun 启动/构建（`projects/mcp_server/package.json:1-33`）。 |
| `projects/marketplace/` | `@fastgpt/marketplace` | 插件/工具市场 Next 应用，独立 API、Mongo/S3 服务和上传下载逻辑（`projects/marketplace/package.json:1-52`）。 |
| `projects/volume-manager/` | `@fastgpt/volume-manager` | Hono 卷管理服务，抽象 Docker Volume/Kubernetes PVC 驱动（`projects/volume-manager/package.json:1-28`）。 |
| `projects/agent-sandbox/` | 外部沙箱运行时目录 | Agent sandbox 相关镜像/编排资源。 |
| `projects/fastgpt-ide-agent/` | Rust 独立服务 | 远程 IDE 文件、预览、终端/工作区协议；当前本地存在该目录，但其实现细节未纳入深度分析。 |
| `sdk/storage/` | `@fastgpt-sdk/storage` | S3 兼容对象存储适配器、访问链接、上传下载和契约测试。 |
| `sdk/sandbox-adapter/` | `@fastgpt-sdk/sandbox-adapter` | `ISandbox` 等沙箱契约、Sealos DevBox/OpenSandbox 适配。 |
| `sdk/otel/` | `@fastgpt-sdk/otel` | 日志、metrics、tracing 的 OTel SDK 封装。 |
| `document/` | 文档站点 | 独立 Next.js 文档应用与大量 MDX 内容。 |
| `pro/` | Git submodule | 商业版代码，`.gitmodules` 指向 `https://github.com/labring/fastgpt-pro.git`；本地当前 submodule 状态为 `-d0cdce9...`，未在本次读取中展开。 |

## 4. 主应用入口与请求路径

### 4.1 Next.js 应用

`projects/app/package.json` 的 `dev`/`build` 先执行 `build:workers` 再运行 `next dev`/`next build`；生产使用 `next start`，构建输出为 standalone（`projects/app/package.json:12-24`、`projects/app/next.config.ts:38-55`）。`next.config.ts` 还配置：

- `basePath` 来自 `NEXT_PUBLIC_BASE_URL`；
- `en/zh-CN/zh-Hant` 三个 locale；
- 生产安全响应头；
- Turbopack 根为仓库根；
- `@modelcontextprotocol/sdk`、`ahooks` 转译；
- `@node-rs/jieba`、`bullmq`、Milvus SDK、OTel、Agent SDK 作为 server external packages；
- worker 输出、CSS chunk、内存 worker 与 tracing 排除规则（`projects/app/next.config.ts:38-107`）。

`src/pages/_app.tsx` 是页面总壳：初始化系统配置、错误日志、国际化、React Query、Chakra、系统 Store 和 `Layout`；`/apidoc/devapi` 与 `/apidoc/systemopenapi` 不套普通 Layout，其余页面默认套用 `Layout`（`projects/app/src/pages/_app.tsx:23-96`）。`src/instrumentation.ts` 在 Node runtime 注册 `instrumentation-node`（`projects/app/src/instrumentation.ts:1-6`）。

### 4.2 API 入口

Next API 路由按文件系统映射到 `projects/app/src/pages/api/`，当前本地统计约 299 个 `.ts` 路由文件。主要分区：

- `api/v1/chat/completions.ts`：旧版聊天/插件调用入口。
- `api/v2/chat/completions.ts`：新版聊天入口。
- `api/v2/chat/stop.ts`：V2 停止标记入口。
- `api/core/workflow/*`：工作流调试与沙箱包。
- `api/core/dataset/*`：知识库、训练数据、搜索测试、文件预览/上传。
- `api/core/plugin/*`：系统工具、团队工具、版本与安装。
- `api/support/user/*`：账户、团队、登录、成员。
- `api/support/openapi/*`：OpenAPI 配置、标签、健康检查。
- `api/support/mcp/*`、`api/mcp/app/[key]/mcp.ts`：MCP 管理与应用 MCP 端点。
- `api/system/file/*`、`api/system/img/*`：对象存储文件和图片访问。
- `api/invoke/*`、`api/plugin/debug-channel/*`、`api/marketplace/*`：外部调用、调试通道和市场代理。

`src/service/middleware/entry.ts` 通过 `createApiEntry` 统一创建 `NextAPI`，前置用 `withNextCors` 按 `serviceEnv.ALLOWED_ORIGINS` 设置 CORS（`projects/app/src/service/middleware/entry.ts:1-15`）。仓库规则要求 API 边界使用 `parseApiInput`，而不是直接对 `req.body/query/params` 调 schema（`AGENTS.md:99-115`）；V1/V2 completions 均已使用该 helper（`projects/app/src/pages/api/v1/chat/completions.ts:69-92`、`projects/app/src/pages/api/v2/chat/completions.ts:66-92`）。

### 4.3 聊天到工作流

V1/V2 completions 的共同主线是：

1. `CompletionsPropsSchema` 解析 `chatId`、`appId`、`messages`、`stream`、`variables`、外链鉴权、API Key proxy 与引用/技能展示选项。
2. `authChatCompletionHeaderRequest` 或分享外链鉴权，解析团队/成员、应用、额度、调用身份。
3. `teamFrequencyLimit` 做聊天频率限制，`getWorkflowFileLimits` 准备文件配额。
4. 标准化消息、读取聊天历史和最新 `AppVersion`，从 Store 节点/边转换 runtime 节点/边。
5. 调用 `dispatchWorkFlow`，在工作流内执行模型、知识库、工具、插件、循环/并行和交互节点。
6. 通过 `workflowSseEvent`/响应 sink 增量输出，保存节点响应、聊天结果、usage、引用和变量；交互节点则挂起并由下一次请求恢复。

`CompletionsPropsSchema` 位于 `packages/global/openapi/core/chat/completion/api.ts`，通过 Zod 定义请求和响应合同，且对外链 `shareId/outLinkUid` 做成对校验（`.../api.ts:72-111`）。

## 5. 工作流执行引擎

### 5.1 Store/Runtime 双层模型

持久化应用中的 `modules`/`edges` 是 Store 形态；执行前转换为 `RuntimeNodeItemType`/`RuntimeEdgeItemType`，运行期增加节点输出、边状态、入口标记、跳过/激活等状态。共享工作流类型位于 `packages/global/core/workflow/type/` 与 `packages/global/core/workflow/runtime/`，使前端编辑器、API、服务执行器共用同一份 Zod/TypeScript 形状。

### 5.2 `dispatchWorkFlow`

`packages/service/core/workflow/dispatch/index.ts` 的 `dispatchWorkFlow` 首先：

1. 检查团队 AI 点数 `checkTeamAIPoints`；
2. 执行 `prepareWorkflowFileContext`，登记文件、限制文件数量/字节数并刷新预览 URL；
3. 创建或复用 chat usage 记录；
4. 以 `WorkflowVariableState.create` 建立变量、历史、文件登记和外部 workflow variables 的运行态；
5. 建立客户端断开追踪或 V2 停止信号检查；
6. 进入工作流队列/节点调度并用 sink 写响应，最终汇总 usage 与运行结果（`packages/service/core/workflow/dispatch/index.ts:122-234`）。

代码明确要求：流式响应必须由调用入口预先初始化，dispatch 不隐式管理 SSE 协议（`.../dispatch/index.ts:140-145`）。

### 5.3 节点调度与图算法

核心调度状态包括 active node queue、skip node queue、运行中 Promise 集合和按 source/target 索引的边集合。`callbackMap` 是 `FlowNodeTypeEnum` 到节点 dispatch 实现的注册表；节点执行结果通过统一响应结构回填 outputs，并按 `skipHandleId` 标记下游边。

当前节点能力覆盖：

- 起始/回答/文本/代码/变量更新/条件分类；
- `datasetSearchNode` 知识库检索；
- `agent` Agent 循环；`toolCall` 工具循环；
- `pluginModule`/`appModule` 子工作流；
- `parallelRun`/`loopRun` 并行与循环；
- `httpRequest468`、MCP、系统工具、文件读取；
- `userSelect`、`formInput`、`ask_user` 等交互暂停节点。

调度器使用 DFS 边分类、Tarjan SCC 检测循环/回边，并以迭代处理替代深递归；默认工作流运行次数和并行/循环上限由 service 环境常量控制。并行/循环子运行通过深拷贝 runtime nodes/edges 隔离状态，并限制输入规模与并发，避免旧输出泄漏和无限循环。上述算法和限制在现有 `细探-FastGPT.md:99-139` 中已有摘要，主入口实际实现见 `packages/service/core/workflow/dispatch/index.ts` 及 `.../dispatch/utils/tarjan.ts`。

### 5.4 并行/循环子运行与异步上下文

旧细探对这部分的细节经当前源码复核后纳入以下边界：

- `parallelRun` 只接受数组，输入长度受 `WORKFLOW_MAX_LOOP_TIMES`（当前默认 100）限制；用户并发度取整后至少为 1，并被 `WORKFLOW_PARALLEL_MAX_CONCURRENCY` 截断（当前默认 10，用户默认值为 5），重试次数默认 3、上限 5（`packages/service/core/workflow/dispatch/parallelRun/runParallelRun.ts:36-74`、`.../parallelRun/service.ts:18-58`）。
- 每个并行任务都会深拷贝 runtime nodes/edges、克隆变量状态后再次调用 `runWorkflow`；每次重试都累计实际 usage，只有成功任务才把容器运行态快照同步回父运行，交互响应不重复重试（`.../parallelRun/runParallelRun.ts:77-145`）。这使“并行隔离”不仅是内存复制，也包含变量和状态回写策略。
- `loopRun` 支持数组和 conditional 两种模式；数组模式按 0 基索引消费输入，conditional 模式必须存在 `loopRunBreak` 子节点，否则在节点响应中返回错误。循环同样受最大迭代数限制，并在交互恢复时从历史中的 children response 重写内层节点输出；自定义输出通过已完成节点快照读取，避免失败迭代沿用旧值（`packages/service/core/workflow/dispatch/loopRun/runLoopRun.ts:41-95`、`:128-194`、`:215-220`）。
- 工作流调用链使用 `AsyncLocalStorage` 保存 `mcpClientMemory`、只读 `fileContext` 和文件登记器；子工作流派生独立文件上下文，按文件 identity 去重并优先保留当前 query/变量输入，再按父上下文的数量上限过滤历史文件。外链读取复用同一上下文的单文件大小限制（`packages/service/core/workflow/utils/context.ts:16-47`、`:85-190`、`:240-251`）。这补充了“不要把运行上下文全部穿透函数参数”的架构边界。

## 6. Agent 循环与模型层

`packages/service/core/ai/llm/agentLoop/provider/registry.ts` 使用 `Map<AgentLoopProviderName, AgentLoopProvider>` 注册 `fastAgent` 与 `piAgent`，未知 provider 显式报错，允许通过 `registerAgentLoopProvider` 扩展（`.../provider/registry.ts:1-27`）。

`fastAgent/loop/base.ts` 的循环职责是：

1. 根据模型与消息 token 数决定是否 `compressRequestMessages`；
2. 调用 `createLLMResponse`，接收流式文本、reasoning 和 tool calls；
3. 按 `canBatchTool` 区分可并发工具与 plan/ask 等必须串行的有状态工具；
4. 对工具响应执行 `compressToolResponse`，把结果再放回消息；
5. 通过 `onLLMRequest*`、`onTool*`、`onStreaming` 等 callback 将运行态交给 workflow adapter/UI；
6. 受 `maxRunAgentTimes`、abort/stop、交互子工具暂停和完成原因约束（`.../fastAgent/loop/base.ts:125-215`）。

模型层通过 `getLLMModel`、embedding/rerank/VLM 统一解析供应商、模型、计费和请求参数；`packages/service` 依赖 `@mariozechner/pi-agent-core`、`@mariozechner/pi-ai`、`@modelcontextprotocol/sdk`、`openai` 生态和多种解析/向量库 SDK。

### 6.1 Agent 控制面与提示词契约

- `fastAgent` 的循环参数由调用方显式传入 `maxRunAgentTimes` 与 `batchToolSize`；循环内部先按需执行 `compressRequestMessages`，再请求 LLM、执行工具、压缩工具响应并决定是否继续。工具执行可通过 `canBatchTool` 选择并发或串行；子交互会保存 `toolCallId` 和恢复上下文，恢复时把用户结果作为同一个 tool call 的 Tool message 接回原消息链（`packages/service/core/ai/llm/agentLoop/provider/fastAgent/loop/base.ts:182-215`、`:323-369`、`:371-380`）。
- 主 Agent prompt 不是散落在调用方的常量：`domain/mainPrompt.ts` 按是否存在 runtime tools 动态生成 `<role>`、plan、ask、tool 和 completion 规则；fastAgent 还会剔除外部 system message 后统一注入该 prompt，`raw` 模式则保留调用方 messages（`packages/service/core/ai/llm/agentLoop/domain/mainPrompt.ts:5-63`、`packages/service/core/ai/llm/agentLoop/provider/fastAgent/loop/index.ts:90-123`）。因此提示词属于 Agent 控制面的版本化输入适配，而不是独立的业务节点。
- 知识库回答模板在 `packages/global/core/ai/prompt/AIChat.ts` 以 `4.9.7` 键保存 standard/QA/strict/hard-strict 变体；其中引用协议要求输出已召回 `<Cites>`/`<QA>` 中存在的 id，并区分“可参考”与“只能使用召回内容”的 strict 语义（`.../AIChat.ts:6-40`、`:43-66`、`:69-106`）。本文吸收其“版本化 prompt + 引用协议”架构事实，不复制整段提示词。

## 7. 知识库与检索

### 7.1 Mongo 数据与向量索引

知识库业务主数据在 MongoDB，向量/全文检索在 VectorDB 抽象层。当前实现支持 PG/pgvector、Milvus、Zilliz、OceanBase、SeekDB、OpenGauss 等部署/适配方向；部署模板位于 `deploy/templates/vector/` 和 `document/public/deploy/docker/`。

关键 Mongo 模型：

| 集合 | 主要模型/字段 | 作用 |
|---|---|---|
| `datasets` | `teamId`、`tmbId`、`type`、`vectorModel`、`agentModel`、`vlmModel`、`chunkSettings`、`deleteTime` | 知识库及分段、索引、模型配置（`packages/service/core/dataset/schema.ts:18-158`）。 |
| `dataset_datas` | `teamId`、`datasetId`、`collectionId`、`q`、`a`、`imageId`、`indexes[]`、`chunkIndex`、`rebuilding` | 文档 chunk 与其索引元数据；`indexes[].dataId/text/type` 关联向量/全文索引（`.../dataset/data/schema.ts:12-116`）。 |
| `dataset_collections` | 由 `core/dataset/collection/schema.ts` 定义 | 文件/集合级训练状态与来源。 |
| `apps` | `teamId`、`tmbId`、`type`、`modules`、`edges`、`chatConfig`、`pluginData`、`resourceRefs`、`deleteTime` | 应用及其当前工作流 Store 图（`packages/service/core/app/schema.ts:9-159`）。 |
| `app_versions` | `appId`、`tmbId`、`nodes`、`edges`、`chatConfig`、`isPublish`、`isAutoSave`、`versionName` | 应用版本/发布快照；按 `appId,time` 倒序索引读取最新版本（`.../app/version/schema.ts:7-56`）。 |
| `chats` | `chatId`、`teamId`、`tmbId`、`sourceType`、历史物理字段 `appId`、`appVersionId`、变量、外链、反馈统计、生成状态 | 会话元数据、运行变量、分享与生成状态（`packages/service/core/chat/chatSchema.ts:16-220`）。 |
| `chat_items` 等 | 位于 `packages/service/core/chat/` | 消息、节点响应、引用、交互恢复与反馈记录。 |
| `mcp_keys` | `name`、唯一 `key`、`teamId`、`tmbId`、`apps[]` | 对外 MCP key 与暴露的 app/tool 关联（`packages/service/support/mcp/schema.ts:10-60`）。 |
| 用户/团队/权限/钱包/日志 | `support/user`、`support/permission`、`support/wallet`、`common/system` | 多租户、成员权限、套餐配额、余额与运行观测。 |

Mongo 公共基础设施在 `packages/service/common/mongo/index.ts`：使用 Mongoose 连接复用、通用查询耗时 middleware、ObjectId 转换、模型缓存和 `MongoIndexManager`；Schema 索引通过 `defineIndex` 集中登记，生产环境按 `SYNC_INDEX`/Mongo URL 条件同步（`.../common/mongo/index.ts:26-176`）。仓库 `AGENTS.md` 进一步要求废弃索引显式以 `deprecated: true` 登记，并同步 index manager 测试（`AGENTS.md:92-97`）。

### 7.2 默认检索链路

`defaultSearchDatasetData` 是知识库搜索统一入口：先清理文本 query，按配置调用 query extension，再把扩写结果送入 `searchDatasetData`（`packages/service/core/dataset/search/index.ts:12-75`）。默认召回实现的实际步骤为：

1. 图片 query 先尝试 VLM caption；
2. 按 `searchMode` 分配 embedding/full-text 配额并多 query 召回；
3. 文本 embedding/full-text 按 `embeddingWeight` 融合，图片 caption 同理；
4. 只对文本召回做 rerank；
5. 图片 caption 与图片向量按约定权重融合，再与文本结果合并；
6. 固定执行去重、相似度过滤、token 上限裁剪；
7. 最终返回前才把内部 image key 转成预览 URL；
8. 返回 embedding/rerank token 和图片 caption 使用量（`.../search/defaultRecall/index.ts:19-198`）。

该顺序是重要的可维护契约：动态预览 URL 不参与中间去重，视觉结果不会被文本 rerank 误杀，最终输出才暴露可访问 URL。

## 8. 数据访问、队列与外部存储

### 8.1 Redis 与 BullMQ（本地当前实现）

`packages/service/common/redis/index.ts` 负责解析 Redis URL、Unix socket、TLS、连接重试、全局 `fastgpt:` key prefix，并区分 queue/worker/global connection（`.../redis/index.ts:8-135`）。

`packages/service/common/bullmq/index.ts` 定义 `QueueNames`：dataset sync/evaluation/S3 delete/collection update/skill create、资源删除、微信轮询/回复等；`getQueue`/`getWorker` 使用全局 Map 懒创建，并配置 worker 锁、stalled 检查、错误记录和关闭后重启策略（`.../bullmq/index.ts:25-151`）。

### 8.2 对象存储与文件

S3/MinIO/OSS/COS/S3-compatible 适配集中在 `sdk/storage`，服务层用 access link、upload/download alias、文件解析 worker 和图片预览串起文件生命周期。工作流文件上下文在 dispatch 前登记输入文件，避免任意文件穿透节点变量；`projects/app` 的文件 API 提供上传、下载、预签名和代理访问。

### 8.3 远程运行时

- `projects/code-sandbox/src/index.ts` 启动 Hono，限制请求 body 字节数，Zod 校验 `code/variables/queueId`，维护 JS `ProcessPool`、Python `PythonIsolatedRunner`、`QueueIdLimiter`，提供 `/health`、`/sandbox/js`、`/sandbox/python` 等接口；若未配置 `SANDBOX_TOKEN` 会明确记录未认证警告（`.../code-sandbox/src/index.ts:13-18`、`34-110`、`112-180`）。
- `projects/volume-manager` 把卷业务与驱动解耦，驱动包括 Docker Volume/Kubernetes PVC。
- `projects/mcp_server` 是对外 MCP 协议服务；主应用同时实现 MCP client，用于工作流节点/工具调用。
- `sdk/sandbox-adapter` 以 `ISandbox` 契约适配 Sealos DevBox/OpenSandbox 等 provider；`packages/service/core/ai/sandbox` 负责权限、生命周期、归档、资源和运行态。
- `sdk/otel` 与 service/app instrumentation 提供 logger、metrics、tracing；工作流 dispatch 中存在 `observeWorkflowRun`、`observeWorkflowStep` 和 active span。

### 8.4 沙箱生命周期与 CPU 隔离

- 沙箱 provider 当前由 `sealosdevbox`、`opensandbox`、`e2b` 三项组成；应用会话的 `sandboxId` 为 `hash(appId-userId-chatId)` 截取前 16 位，`skillEdit` 使用独立的 debug id 规则，不能把两者混为同一生成算法（`packages/global/core/ai/sandbox/constants.ts:14-40`、`packages/service/core/ai/sandbox/utils/id.ts:10-35`）。
- 沙箱业务状态分为运行/停止，归档元数据另有 `archiving`、`deleting`、`archived`、`restoring`、`failed` 状态；归档链路同时协调 provider 资源、Mongo 状态、S3 workspace archive 和卷清理，而不是单独压缩一个文件（`packages/service/core/ai/sandbox/type.ts:44-101`、`packages/service/core/ai/sandbox/application/archive.ts:1-55`、`packages/service/core/ai/sandbox/application/resource.ts:1-5`）。
- 定时任务每 10 分钟暂停闲置超过 10 分钟的运行实例，每 12 小时在 timer lock 下归档闲置资源；归档阈值为 7 天，归档批次为 5，命令/流程超时为 10 分钟，恢复等待上限为 180 秒（`packages/service/core/ai/sandbox/application/cron.ts:18-60`、`.../application/archive.ts:49-55`）。这些是当前实现的生命周期参数，不等同于已经验证过的实际部署 SLA。
- `packages/service/worker/` 将读文件、HTML 转 Markdown、token 统计、系统插件和文本切块放入 Node `worker_threads`；worker 通过 `{ type: 'success' | 'error', data }` 返回结果，错误或 messageerror 会终止 worker（`packages/service/worker/utils.ts:7-64`）。因此 token 统计和部分 CPU 密集转换属于显式进程内隔离边界。

## 9. 插件、MCP 与安全边界

插件来源按现有实现分为系统工具、团队工作流插件、商业工具、MCP tool set/单工具和 OpenAPI/HTTP tool set。插件输入在边界完成类型化注入、password 解密和文件登记，团队插件需经过 `authWorkflowToolByTmbId` 等权限校验。

MCP client 的现有设计重点：

- Streamable HTTP 优先，兼容 SSE 回退；
- 连接前检查内网地址，手动跟随重定向并逐跳 SSRF 校验；
- 跨 host/protocol 重定向丢弃 authorization/cookie/proxy-authorization 等敏感 header；
- 外部 `$ref` 解析关闭 file/http 解析，避免 schema SSRF；
- tool call 有超时，连接复用并在 workflow `finally` 清理。

HTTP 节点、MCP、文件、外链、团队权限、API Key、对象存储访问均是安全审查重点。`AGENTS.md` 的 API 规则、Mongo 索引规则以及 `.agents/design/api/` 的请求校验/对象 key 授权文档是后续修改的权威约束。

### 9.1 插件节点的版本与输入适配

`dispatchRunPlugin` 当前仍保留三类插件路径：旧 `systemTool-` id 兼容转发到 `dispatchRunTool`；`personal` 先按团队成员读取权限加载指定 `AppVersion`；`commercial` 通过 `SystemToolRepo` 解析系统级工作流和关联插件版本。随后统一把插件图转为 child runtime，`pluginInput` 在边界完成 password 解密、fileSelect 文件登记/转换，`pluginOutput` 的 `isToolOutput` 决定哪些字段暴露给调用方（`packages/service/core/workflow/dispatch/plugin/run.ts:56-99`、`:102-155`、`:166-219`）。这将旧细探中“插件=子工作流”的摘要细化为“来源鉴权/版本选择/输入适配/输出过滤”四个边界。

## 10. 测试与质量门禁

本地测试基于 Vitest：

- 根脚本 `pnpm test` 调 `test:workspace`，通过 `scripts/test/withMongo.mjs` 包装 Mongo 内存测试，再由 Turbo 运行 app/admin/global/service（`package.json:17-27`）。
- `projects/app/vitest.config.ts` 使用共享 `test/setup.ts`、`test/globalSetup.ts`，覆盖 `test/**/*.test.ts`，线程池并发、最大并发 10，覆盖率排除类型/schema 文件（`.../projects/app/vitest.config.ts:18-75`）。
- `packages/service/vitest.config.ts` 同样使用共享 Mongo setup，默认排除 integration 目录；另有 `vitest.integration.config.ts` 做集成测试（`.../packages/service/vitest.config.ts:19-62`）。
- 测试按 API、service、web、workflow、dataset、sandbox、permission、MCP、文件解析、S3、向量数据库等分层。当前本地静态统计约 598 个 `.test.ts/.test.tsx` 文件；其中 `projects/app/test` 和 `packages/service/test` 是主要行为测试位置。
- `test/globalSetup.ts`、`test/setup.ts`、mocks 和 `scripts/test/withMongo.mjs` 是测试隔离基础设施；向量 DB 和对象存储集成测试应视为外部依赖测试，不等同于默认单测。

本次没有运行测试，原因是用户明确禁止启动、构建和测试相关运行；验证仅限 Git 元数据与文档写入后的静态检查门禁。

## 11. 历史版本漂移记录（已由第 29 节当前事实取代）

本节保留早期审计时的版本差异，仅作为历史记录；它不能覆盖第 29 节已重新执行的 `git fetch`、`git pull --ff-only` 和当前 `origin/main` 证据。

- 远程根 `package.json` 仍为根版本 `4.0`，但 Node 要求已提升到 `>=22.23.2`；本地为 `>=20.19.0`。
- 远程 `projects/app/package.json` 为 `4.16.0`，本地为 `4.15.2`；远程增加 `@fastgpt/dal` workspace 依赖。
- 远程新增 `packages/dal/`，其职责是 Redis Runtime、Cache、BullMQ 的独立数据访问层；远程设计文档明确 MongoDB/Vector DB 暂不迁入 DAL。
- 远程工作区包数量和源码规模增加；远程 `pnpm-workspace.yaml` 增加/调整 `ajv`、Hono、Next、Turbo、TypeScript 等目录级依赖版本，并增加 `postcss`、`marked`、`mermaid` 等 catalog 项。
- 远程新增/增强 `projects/fastgpt-ide-agent`、code-sandbox 测试/隔离能力和大量 4.16 设计/发布文档。

历史结论“本地 4.15.x、远程 4.16.x”已失效；当前本地已同步 4.16.1，`packages/dal`、Node 22、Next 16 和 Redis/BullMQ runtime 均已由第 29 节源码证据确认。

## 12. 关键运行流程

### 12.1 普通聊天

```text
HTTP POST /api/v1/chat/completions 或 /api/v2/chat/completions
  → parseApiInput(CompletionsPropsSchema)
  → authChatCompletionHeaderRequest / 外链鉴权
  → teamFrequencyLimit + workflow file limits
  → 标准化 messages + 读取 MongoChat/AppVersion
  → Store nodes/edges 转 Runtime nodes/edges
  → dispatchWorkFlow
  → WorkflowVariableState + callbackMap 节点调度
  → LLM / dataset search / tool / plugin / interaction
  → nodeResponseSink + workflowSseEvent
  → finalizeChatRound / usage / 引用 / 新变量
```

### 12.2 知识库问答

```text
datasetSearchNode 或 Agent dataset_search
  → defaultSearchDatasetData
  → query extension（可选 LLM）
  → image caption（可选 VLM）
  → embedding + full-text 多路召回
  → 加权融合
  → 文本 rerank
  → 去重 → similarity → token 裁剪
  → image key 转 preview URL
  → quoteQA / 引用提示词
  → 最终 LLM 回答
```

### 12.3 Agent 工具循环

```text
agent/toolCall node
  → provider registry（fastAgent/piAgent）
  → createLLMResponse
  → tool calls
  → canBatchTool 决定串并行
  → workflow/plugin/sandbox/dataset/internal tools
  → compressToolResponse / context compression
  → callback 输出流式状态、usage、交互暂停
  → 无 tool call、stop、abort 或达到上限后结束
```

## 13. 风险、边界与维护规则

### 13.1 重要风险

1. **版本漂移**：本地与远程 main 已不一致；升级时需要把 `packages/dal`、Node 版本、锁文件和 service Redis import 迁移拆开评估。
2. **商业代码边界**：`pro` 是未展开的 submodule；任何完整产品能力结论不能仅凭开源树推断商业实现。
3. **多基础设施一致性**：一次工作流可能同时触发 Mongo、Redis/BullMQ、VectorDB、S3、模型供应商和外部沙箱，失败补偿/幂等/资源释放是跨系统风险面。
4. **动态工作流复杂度**：循环、并行、嵌套、交互暂停和旧版本兼容同时存在；任何 runtime 字段、输出保留和恢复协议变化都可能影响历史会话。
5. **全局状态与生命周期**：Mongo/Redis/queue、全局 handler 和连接复用需要遵守 Next.js 热重载、worker 关闭、请求 drain 与 `finally` 清理边界。
6. **安全输入面**：MCP/HTTP URL、重定向、schema `$ref`、文件对象 key、沙箱代码、插件 headers 和外链 token 都必须保持现有 SSRF/权限/密钥边界。
7. **测试环境依赖**：默认测试使用内存 Mongo，但向量库、MinIO、Redis、沙箱集成测试有外部服务前置；“单元测试通过”不能代替基础设施集成证明。

### 13.2 修改规则

- 先读 `AGENTS.md` 和对应 `.agents/design/`；API 入参使用 `parseApiInput`。
- Mongo Schema 字段/索引变化必须核对旧索引、`defineIndex`、废弃索引声明和 `indexManager.test.ts`。
- 工作流 Store schema、Runtime type、dispatch callback、SSE/交互恢复必须成组评估。
- 不把 `细探-FastGPT.md` 的摘要数字或旧版本判断直接当作当前事实；先回到源码和 package/lock 文件。
- 不把远程快照新增目录或设计写成本地已实现能力。
- 任何涉及源码、依赖、配置或测试的任务，应保持本架构文档与实际边界同步；本文件不是变更日志，不应记录未验证的完成声明。

## 14. 未确认项

以下内容当前核对没有宣称已实现，需后续以目标版本源码、运行时或针对性测试继续确认：

- `pro/` submodule 未展开，商业版 admin、sso、browser-sandbox 的完整依赖关系、路由和数据模型未确认。
- `projects/agent-sandbox/`、`projects/agent-sandbox-proxy/`、`projects/fastgpt-ide-agent/` 未完成逐文件运行时审计；本文只记录其目录角色，不把内部协议、部署状态或安全性质写成已验证事实。
- 本地未安装/解析依赖，也未运行 `pnpm test`、单测、集成测试、类型检查、lint、构建或服务探针，因此当前文档不代表本地运行时健康或测试通过。
- MongoDB、Redis、VectorDB、S3、模型供应商、MCP server、code-sandbox 的真实部署连接、数据一致性、性能和故障恢复未验证。
- 远程快照的 `packages/dal`、Node 22 与 4.16.x 变化只完成静态对比，未做升级兼容性判断，也未覆盖本地工作树。
- 现有 `细探-FastGPT.md` 中的历史计数、默认参数和部分旧路径未全部逐项复核；本文仅采用已回读源码支撑的结论。

## 15. 结论

FastGPT 当前本地形态是一个较大型的 pnpm/Turbo TypeScript monorepo：`projects/app` 以 Next.js 承载 UI 和 API，`packages/global` 提供共享合约，`packages/service` 承担领域执行和基础设施，Flow 工作流调度器是业务核心，知识库检索和 Agent loop 是两条主要智能链路；MongoDB、Redis/BullMQ、VectorDB、S3 和外部沙箱共同构成运行底座。`projects/code-sandbox`、`projects/mcp_server`、`projects/volume-manager` 与 SDK 包把高风险/高复用能力拆成独立边界。

架构的主要优点是共享 Zod/OpenAPI 合约、Store/Runtime 分离、节点 callback 注册表、工作流图算法、知识库固定过滤管线、Agent provider registry、基础设施适配层和较完整的 Vitest 分层。主要维护难点是多租户权限、计费、交互恢复、跨存储一致性、动态插件/MCP 安全、全局连接生命周期和本地落后远程的版本分叉。

后续开发或二次研究应以本文件的路径分层为入口，优先从 `projects/app` API → `packages/service` 领域执行器 → `packages/global` 合约 → Schema/队列/外部 SDK → 对应测试和设计文档建立闭环证据。

## 16. 本次变更与验证

- 新增：`ARCHITECTURE.md`。
- 未修改：源码、依赖、锁文件、配置、测试、`AGENTS.md`、`细探-FastGPT.md`、submodule。
- 未执行：安装、启动、构建、业务测试、提交。
- 已执行：目标仓库 Git 状态/提交/远程信息读取；远程独立快照获取与版本对比；`git diff --check` 静态门禁。
- 代码图证据：目标仓库本地 `.codegraph/` 已建立并索引最新（3,960 files、55,553 nodes、185,440 edges）；没有使用其他仓库代码地图、记忆或验证证据。

## 17. 旧细探吸收与未吸收裁决

`细探-FastGPT.md` 已完整读取并与本地当前源码、现有本架构文档逐项对照。旧文件保留为历史细探证据，不删除；后续 FastGPT 架构事实只维护本文件。

### 17.1 已吸收

| 旧细探主题 | 吸收结果 | 当前证据/落点 |
|---|---|---|
| 工作流 Store/Runtime 双层、`callbackMap` 节点注册、DFS/Tarjan 与迭代调度 | 已吸收并以当前 `dispatchWorkFlow`/runtime 结构重写 | 第 5 节；`packages/service/core/workflow/dispatch/index.ts`、`packages/global/core/workflow/runtime/` |
| 并行/循环的输入上限、并发/重试、深拷贝、交互恢复与自定义输出快照 | 已吸收，并补充“成功才同步父状态”和 conditional 必须 `loopRunBreak` | 第 5.4 节；`.../parallelRun/runParallelRun.ts`、`.../loopRun/runLoopRun.ts` |
| `AsyncLocalStorage` 的 MCP/file context 与 child 文件隔离 | 已吸收 | 第 5.4 节；`packages/service/core/workflow/utils/context.ts` |
| 双 Agent provider、上下文压缩、工具批处理、ask/plan 暂停恢复、usage 计费 | 已吸收；旧细探中的流程描述按当前 provider 路径校正 | 第 6、6.1 节；`.../agentLoop/provider/` |
| 知识库多路召回、固定过滤顺序、图片 key 最终转 URL、引用模板 | 已吸收；完整 prompt 原文不重复抄录 | 第 7.2、6.1 节；`.../dataset/search/`、`packages/global/core/ai/prompt/AIChat.ts` |
| 插件 system/personal/commercial 来源与 child workflow 输入/输出边界 | 已吸收并补充权限、版本、解密和输出过滤 | 第 9.1 节；`packages/service/core/workflow/dispatch/plugin/run.ts` |
| MCP Streamable HTTP→SSE fallback、逐跳 SSRF、跨域丢敏感头、`$ref` 禁外部解析、300 秒 tool timeout | 已吸收 | 第 9 节；`packages/service/core/app/mcp.ts` |
| Agent sandbox provider、sandbox id、停止/归档/恢复生命周期、S3 与 volume | 已吸收；“部署镜像实际预装软件”不作为实现事实 | 第 8.4 节；`packages/service/core/ai/sandbox/`、`packages/global/core/ai/sandbox/constants.ts` |
| worker_threads 的 token/文件/文本切块隔离 | 已吸收为 CPU 隔离边界 | 第 8.4 节；`packages/service/worker/` |

### 17.2 未吸收或降级为历史线索

| 旧细探内容 | 裁决原因 |
|---|---|
| “版本基线为 package.json 4.0”、`dispatch/index.ts` 1671 行、`mcp.ts` 454 行等行数/版本表述 | 当前本地工作树已有独立版本证据，行数会随提交变化；不作为架构事实，已以路径和当前行为取代。 |
| 旧细探中完整复制的主 Agent、知识库、结构化提取和沙箱 system prompt 文本 | prompt 是源码中的可变版本化输入，不把长文本复制成第二事实源；只吸收 prompt 生成边界、版本键和引用协议，详见第 6.1 节。 |
| “Ubuntu 22.04、bash/python3/node/bun/git/curl 预装”等沙箱提示词中的运行环境承诺 | 这是 `SANDBOX_SYSTEM_PROMPT` 对模型的能力说明，不等于每个 provider/image 的部署验证；保留为提示词线索，不升级为部署事实。 |
| 旧测试数量（如 service 281 个测试文件）、未执行测试的历史运行说明、旧默认值快照 | 当前文档第 10 节已按本地现状记录静态统计和“未运行”边界；旧数字不再引用。 |
| `projects/agent-sandbox`、`fastgpt-ide-agent` 的内部协议、安全和部署结论，以及 pro 商业实现细节 | 当前核对未完成逐文件或运行时审计；继续保留第 3、14 节的未确认状态，不从旧摘要推断实现。 |
| 旧细探“可直接映射到底座”的建议表 | 只保留其中已能由源码证明的机制性观察，且作为研究启发而非 FastGPT 已有底座接口；不把建议当实现或依赖契约。 |

本次收口没有修改源码、配置、依赖、锁文件、测试或 `细探-FastGPT.md`；唯一修改目标是本文件。

## 18. 后续：底座映射与复用裁决（增量）

本节不是 FastGPT 的新实现说明，而是把本地源码中已经存在的运行机制映射成“可复用的通用模块/运行核心能力”。裁决只针对机制边界，不把 FastGPT 的工作流节点、插件目录、聊天业务、计费规则或沙箱业务链复制到平台。

### 18.1 取证边界与总流程

```text
Store nodes/edges
  → storeNodes2RuntimeNodes / storeEdges2RuntimeEdges
  → WorkflowQueue（active/skip queue、边状态、SCC/回边、并发上限）
  → callbackMap 节点执行
  ├─ 普通节点：输出/错误/skip edge → 父队列
  ├─ child workflow：clone runtime + clone variable/file context → runWorkflow
  ├─ parallel/loop：隔离子运行 → attempt/iteration summary → 增量回写父状态
  ├─ interactive：memoryEdges + nodeOutputs + queue/checkpoint → chat history/SSE
  ├─ plugin/MCP/sandbox：鉴权/版本/资源租约 → 外部 provider
  └─ response sink：Redis stream resume + Mongo node-response rows + usage summary
```

当前核对证据的主要路径是：

- 调度：`packages/service/core/workflow/dispatch/index.ts`、`.../parallelRun/runParallelRun.ts`、`.../loopRun/runLoopRun.ts`、`.../dispatch/utils/containerRunState.ts`。
- 交互/流恢复：`packages/global/core/workflow/template/system/interactive/type.ts`、`packages/service/core/workflow/dispatch/index.ts`、`packages/service/core/chat/resume.ts`、`.../utils/streamResponseContext.ts`。
- 插件/子工作流/上下文：`packages/service/core/workflow/dispatch/plugin/run.ts`、`.../child/runApp.ts`、`packages/service/core/workflow/utils/context.ts`。
- 沙箱/归档/租约：`packages/service/core/ai/sandbox/type.ts`、`application/archive.ts`、`application/cron.ts`、`application/runtime/entrypoint.ts`、`packages/service/common/redis/lock.ts`。
- 工作线程/进程边界：`packages/service/worker/utils.ts`、`projects/code-sandbox/src/pool/worker.ts`、`projects/code-sandbox/src/isolated/python-isolated-runner.ts`。

### 18.2 现有能力命中表

| FastGPT 机制 | 可抽取的通用模块/运行核心能力 | 复用裁决 | 不应复制的业务链路 | 关键证据 |
|---|---|---|---|---|
| `WorkflowQueue` 的 active/skip queue、边索引、并发槽、非递归处理、DFS 边分类和 Tarjan SCC | 有界图执行器：节点状态、依赖满足、分支/回边、并发调度、停止检查、运行次数预算 | **吸收**为运行核心“图调度/节点生命周期”能力；契约应只收节点、边、状态和执行回调 | 不复制 `datasetSearchNode`、`agent`、`pluginModule` 等 FastGPT 节点集合，也不复制其业务参数 | `.../dispatch/index.ts:343-355, 359-436, 709-777` |
| `runWorkflow` 的 child depth、root/child span、`workflowDispatchDeep > 20` 保护、统一 resolve/finally | 子运行边界、递归深度预算、父子 trace/usage 关联、崩溃/异常后的上下文复位 | **吸收**为运行核心“子运行监督器” | 不把 app/plugin/agent 的 child 业务语义变成平台工作流模板 | `.../dispatch/index.ts:1507-1530, 1533-1669` |
| `parallelRun` 每项 clone runtime/variable state，单项最多 5 次重试，默认 3；交互结果不重试；成功才同步父状态 | 可配置、可观测、按任务粒度的重试策略；attempt id、最终结果与尝试详情分离；成功提交门 | **升级现有运行核心**的 retry/attempt 契约，而不是新增一套并行引擎 | 不复制 `parallelSuccessResults`、输入数组业务规则和具体积分口径 | `.../parallelRun/runParallelRun.ts:46-169`、`.../parallelRun/service.ts:43-58, 127-179` |
| `WorkflowNodeResponseWriter` 正常写入重试 3 次，随后 slim rows fallback，仍失败只丢详情但保留 summary | 结果持久化的降级级别、详情/摘要分离、失败可观测、最终 flush/close | **吸收**为运行核心“结果投影/失败降级”策略；必须显式声明可丢字段 | 不复制 `chat_items` 的 Mongo 字段和聊天展示树 | `packages/service/core/chat/nodeResponseStorage.ts:612-721` |
| `createContainerRunStateSnapshot` 与 `syncContainerRunState` 按快照比较 output/variable，成功子运行才增量提交；并发写按完成顺序覆盖 | 子运行 delta、提交前快照、显式副作用提交、冲突策略/写入顺序 | **吸收**为公共状态同步契约；后续平台必须补 CAS/版本冲突语义，不能默认 last-writer-wins | 不复制节点 output key、变量业务类型和“后完成者覆盖”作为普遍一致性保证 | `.../utils/containerRunState.ts:49-149` |
| interactive response 保存 `entryNodeIds`、`memoryEdges`、`nodeOutputs`、`skipNodeQueue`、`usageId`；旧 tool message 快照仅兼容读取 | 可持久化 checkpoint、恢复入口、一次性 resume token/attempt identity、历史重建 | **吸收**为运行核心“交互检查点/恢复器” | 不复制 `userSelect`、`paymentPause`、`agentPlanAskQuery` 的产品 UI 和问答语义 | `.../interactive/type.ts:9-20, 44-91, 98-188` |
| `handleInteractiveResult` 把入口边激活、保留跳过队列和节点输出；`runLoopRun` 恢复时重写 child output、合并 pending summary、复用 iteration response id | 可重入恢复、checkpoint 合并、恢复增量投影、重复提交去重 | **升级**恢复核心，重点定义“完整快照/增量快照/重复恢复”的幂等键 | 不复制 loopRun 的 iteration history/custom output 业务结构 | `.../dispatch/index.ts:1437-1488`、`.../loopRun/runLoopRun.ts:85-125, 254-295` |
| Redis Stream resume：按 team/source/chat 组成 key，首轮清空旧镜像，XADD 串行写，TTL touch；断线按 XRANGE 全量追赶后用独立连接 XREAD tail | 流式状态镜像、游标隔离、断线续传、连接生命周期、内存压力降级 | **吸收**为网关/运行核心的“可选流恢复”能力；其 Redis memory pressure、短 TTL 和 stale 检查必须进入资源预算 | 不复制 SSE event 名、聊天响应格式和 FastGPT `chatId` 业务主键 | `packages/service/core/chat/resume.ts:47-60, 131-178, 273-344, 396-535`、`.../streamResponseContext.ts:45-110, 127-185` |
| `AsyncLocalStorage` 保存 `mcpClientMemory`、只读 file context、registrar；child 复制 query/history/file 引用并按 identity/配额筛选 | 请求/运行作用域上下文、父子隔离、受控能力注入、资源额度传播 | **吸收**为公共“运行上下文”模块；registrar 必须是显式权限边界，不做隐式全局可写上下文 | 不复制文件 URL 解析、聊天 history 规则和 MCP client 具体实现 | `packages/service/core/workflow/utils/context.ts:16-47, 49-87, 89-238` |
| personal 插件按 `tmbId` 做 Read 权限校验并取指定 `AppVersion`；commercial 系统工具经 `SystemToolRepo`；password 解密、file 登记、pluginOutput 过滤 | 能力授权、版本解析、输入适配、敏感参数处理、输出最小暴露 | **吸收**为“能力调用授权 + 版本锁定 + 输入/输出边界” | 不复制 personal/commercial/systemTool 分类、插件市场和 `computedAppToolUsage` 计费链路 | `packages/service/core/workflow/dispatch/plugin/run.ts:73-165, 166-225, 267-341` |
| 沙箱 provider adapter 统一 stop/delete/connect，资源表带 sourceType/sourceId/team/user/chat，provider/volume/archive 分离 | 外部运行资源适配器、归属隔离、生命周期状态机、资源释放与补偿 | **吸收**为运行核心“受管外部资源”能力；provider 只做适配，不把 provider API 穿透到上层 | 不复制 Agent sandbox/Skill Edit 的 id 规则、镜像、工作目录和产品配额 | `packages/service/core/ai/sandbox/type.ts:44-103`、`application/resource.ts:50-100, 102-145` |
| `withRedisLease` 用 SET NX PX、随机 token、续期脚本、token 校验释放；sandbox init lease TTL 3 分钟、约 30 秒续租 | 可续租租约、租约丢失检测、拒绝无锁执行、所有权释放 | **吸收**为公共 lease/ownership 模块；租约失效必须使临界区失败，不可静默继续 | 不复制 `agent-sandbox:init:<sandboxId>` key、具体 entrypoint 初始化语义 | `packages/service/common/redis/lock.ts:51-137`、`.../sandbox/application/runtime/entrypoint.ts:23-53` |
| 归档状态 `archiving → deleting → archived`，恢复 `restoring`，失败/回滚/陈旧清理；Mongo CAS 后才删远端，S3 archive 与 volume/provider 协同 | 持久资源归档/恢复状态机、CAS 占用、二阶段清理、失败补偿、stale state 收敛 | **吸收**为运行核心“资源归档恢复编排器”；必须把远端删除与权威状态更新的顺序写入契约 | 不复制 zip/unzip 命令、S3 bucket、sandbox workDirectory 和 Skill runtime 升级链 | `.../sandbox/type.ts:44-78`、`application/archive.ts:422-581, 589-645, 744-943, 969-985` |
| cron 只筛选闲置资源，timer lock 避免多实例重复归档/清理，归档按 Mongo cursor、每批 5 个并发 | 定时扫描、分布式 timer lock、有界批处理、进度与失败汇总 | **吸收**为运维/资源治理模块 | 不复制“10 分钟暂停、12 小时归档、7 天阈值”作为平台默认业务策略；这些是 FastGPT 参数 | `.../sandbox/application/cron.ts:19-60`、`application/archive.ts:648-731` |
| `WorkerPool` 单 worker 单任务、等待队列、任务超时销毁、每 worker 最大任务数后回收、error/messageerror 删除 | 工作线程监督器、槽位/等待队列、超时终止、有限复用、内存泄漏隔离 | **吸收**为运行核心 worker supervisor；必须有终止、队列排空和进程退出验证 | 不复制 `readFile/htmlStr2Md/text2Chunks` 等业务 worker 名和上传文件 handler | `packages/service/worker/utils.ts:81-183, 206-320` |
| code-sandbox 进程池对 JS/Python worker 做崩溃/超时/内存 RSS 终止后 respawn，测试覆盖池满排队和 shutdown | 更强隔离的进程 supervisor、资源限额、崩溃复活、运行后清理 | **吸收**为沙箱/高风险 provider 的独立进程边界；主运行核心只持有协议客户端 | 不复制 FastGPT 的 JS/Python 代码执行协议、允许模块表和业务输入变量 | `projects/code-sandbox/src/pool/worker.ts:1-10`、`test/unit/process-pool.test.ts:61-140`、`test/unit/resource-limits.test.ts:35-148` |

### 18.3 单链路落点与装配计划

后续不新建平行业务链路，建议按以下唯一落点装配：

```text
项目适配层
  → 工作流/应用适配器（只把 FastGPT Store、插件、聊天字段映射为公共请求）
  → 运行核心/图调度器
  → 运行核心/子运行与状态同步
  → 运行核心/检查点与流恢复（可选能力）
  → 运行核心/租约与资源监督
  → 支持库/外部资源 provider（Redis、Mongo、S3、sandbox、worker）
  → 统一结果、事件、资源释放和验证证据
```

装配顺序：

1. **复用现有公共契约**：先冻结 `运行请求/运行结果/节点状态/attempt/checkpoint/资源句柄/租约/错误码`，不要从 FastGPT 业务 schema 反向生成平台契约。
2. **升级运行核心**：补“有界图调度、子运行 fork/join、delta state、retry policy、checkpoint resume、worker supervisor”六类原子机制；每类只有一个 owner 和入口。
3. **补资源治理**：把 Redis stream、Mongo response、S3 archive、sandbox、worker/process 都挂到统一资源监督/租约/超时/取消模型，明确谁创建、谁持有、谁转移、谁释放。
4. **做项目适配层**：FastGPT 只绑定 node/edge、interactive response、plugin version、sandbox source identity；业务输出和历史数据留在 FastGPT 适配层。
5. **分层验证**：先跑纯契约/状态机/失败注入，再跑真实 Redis/Mongo/S3/provider/worker；缺外部依赖必须返回不可用或显式未验证，不能用模拟成功替代。

不应把 `WorkflowQueue`、`dispatchRunPlugin`、`archiveSandboxResource` 直接搬进平台：它们分别混合了 FastGPT 图语义、插件市场/计费、sandbox 归属与 S3/volume 业务。底座只吸收其中的机制契约和资源边界。

## 19. 资源、失败、租约与验证契约

### 19.1 资源生命周期表

| 资源 | 创建/持有者 | 正常释放 | 业务失败 | 超时/取消 | 宿主崩溃/残留验证 |
|---|---|---|---|---|---|
| runtime nodes/edges、变量 clone | parallel/loop/child 运行；子运行持有 clone | 出作用域后 GC；成功才 delta 回写父状态 | 丢弃未提交 clone，保留 attempt/error summary | `checkIsStopping` 阻止下一步；未见统一强制杀已运行 node 的证据，列待核 | 查无跨任务共享可变引用；并行/循环测试应核对父输出不被失败 attempt 污染 |
| Mongo node-response rows/buffer | writer 持有 buffer 与写队列 | flush/close 后清空 buffer；summary 独立保留 | 3 次失败后 slim rows；再失败丢详情不丢 summary | close 前尽力 flush；未见数据库写取消的独立契约 | 检查无 pending rows、Mongo 连接/事务无残留；真实 Mongo 故障注入待核 |
| Redis stop sign | workflow status 写入；key TTL 60 秒 | workflow 完成 `del`；TTL 兜底 | `del` 失败只记日志，读失败按“不停止”处理，存在安全语义风险 | stop 入口轮询；`waitForWorkflowComplete` 超时只返回，不自动清理 | 检查 `sourceType:sourceId:chatId` 不串号、TTL 到期、Redis 连接释放；它是停止标记，不是所有权租约 |
| Redis stream resume 镜像/active key | 可选 resume mirror 持有；独立 blocking connection 只供当前恢复请求 | flush 后缩短完成 TTL；连接 finally quit/disconnect | Redis 写失败记录日志；内存压力阻止新镜像并记录 unavailable reason | XREAD 30 秒轮询，HTTP 关闭即退出 | 检查旧 stream 在新一轮开始前被清空、无 cursor 共享污染、blocking 连接不会泄漏 |
| sandbox provider、volume、S3 archive、临时 zip | archive/restore flow 持有 provider client 与临时文件 | `disconnectSandbox` finally；临时 archive 文件删除；状态/远端/volume/S3 分步清理 | archiving 前失败→failed；deleting 后失败→deleting error/保持 deleting，避免绕过恢复 | flow 10 分钟超时；restore 等待 180 秒；失败 stop 临时 sandbox 并 rollback restoring | 查询 Mongo 状态与 provider/S3/volume 对账；清 stale archiving/deleting；验证归档对象和临时文件无孤儿 |
| Redis lease/timer lock | `withRedisLease` token；cron timer lock | token 校验释放；续租 timer 清理 | acquire/renew/lost 显式抛错，不能无锁执行；timer 未抢到直接 return | TTL/renew interval 控制临界区；租约丢失在 fn 返回前转失败 | 查 key 已释放、旧 token 不能删新 lease、timer 无残留；高并发抢占待真实 Redis 验证 |
| worker thread/process slot | WorkerPool/ProcessPool 持有；每槽单任务 | idle 或达到 maxTasks 回收；shutdown 清池 | error/messageerror 删除 worker；任务 reject，等待队列继续 | timeout 删除/kill worker，避免占住槽位 | 查 worker/子进程 PID、队列、IPC 管道、临时目录归零；现有测试已覆盖 respawn/shutdown，真实压力仍待核 |

### 19.2 失败矩阵与缺口

| 场景 | 当前源码证据 | 可抽取的公共语义 | 尚未证明的部分 |
|---|---|---|---|
| 非法输入/超限 | parallel/loop 对数组、最大迭代、conditional break 做前置检查；archive 对 entry/大小做限制；sandbox code 对内存/输出/临时目录有限制 | 参数校验、预算拒绝、稳定错误码 | 不同 provider 的错误码统一映射、跨服务预算汇总 |
| 节点业务失败 | `runWorkflow` 以 node response/error/`catchError`/skip edge 传播；parallel 通过 nestedEnd 判定失败 | 失败是结果状态，不强制 reject；错误路由与普通失败分开 | 每种节点错误是否幂等、部分外部写入如何补偿 |
| 可重试瞬态失败 | parallel attempt、writer retry/slim、Redis/Mongo/Vector/Sandbox provider 各自有 retry | retry policy 必须绑定错误分类、次数、退避、幂等键和资源费用 | 全局退避/熔断/重试预算尚未统一；不能把所有异常都重试 |
| 交互暂停 | interactive checkpoint、loop/child 恢复和 agent ask history 重建 | 暂停是可持久化状态，不是普通失败；恢复必须带入口/版本/上下文 | 多次并发提交同一交互、旧版本 checkpoint 兼容和跨实例竞争待核 |
| 客户端断线 | SSE cleanup、Redis mirror、XRANGE + XREAD tail | 传输恢复与业务运行解耦；每个恢复请求独立游标 | 运行仍在生成但 Redis 镜像被内存压力禁用时的用户体验/重试契约 |
| 主动停止/取消 | Redis stop sign、`checkIsStopping`、worker timeout/terminate | 取消检查点、停止传播和资源终止是三件事，不能只删状态 key | 已运行的外部 HTTP/LLM/provider 是否被强制 abort、取消后的费用/写入一致性 |
| provider/宿主崩溃 | worker/process respawn；archive finally/rollback；Redis lease lost | 进程监督器、资源恢复、租约失效保护 | Mongo/S3/Redis 多写之间的跨服务崩溃一致性仍未被真实故障注入证明 |

### 19.3 验收契约（不制造假绿）

1. **源码存在**：本节列出的文件、符号和状态字段均来自当前本地工作树；远程 4.16.x 快照不作为本地实现证据。
2. **测试存在**：可针对性回读的测试包括 `packages/service/test/core/workflow/workflowStatus.test.ts`、`.../utils/streamResponseContext.test.ts`、`.../core/ai/sandbox/application/archive.test.ts`、`projects/code-sandbox/test/unit/process-pool.test.ts` 和 `resource-limits.test.ts`。测试源码存在不等于当前核对已通过。
3. **推荐定向执行**：在具备目标 Node/pnpm、Mongo、Redis 和沙箱依赖后，按包执行 `pnpm exec vitest run packages/service/test/core/workflow/workflowStatus.test.ts packages/service/test/core/workflow/utils/streamResponseContext.test.ts packages/service/test/core/ai/sandbox/application/archive.test.ts`，以及 `pnpm exec vitest run projects/code-sandbox/test/unit/process-pool.test.ts projects/code-sandbox/test/unit/resource-limits.test.ts`；记录退出码、测试数、跳过数和外部服务。
4. **真实资源验证**：Redis 要验证 TTL/lease token/XREAD blocking connection；Mongo 要验证 response writer 故障降级与无 pending rows；S3/provider 要验证归档→删除→恢复→失败回滚；worker 要验证 PID、IPC、临时目录和 shutdown 后无残留。
5. **反向验证**：注入错误 provider、非法数组、无 break、重复交互提交、Redis memory pressure、lease renew 失败、archive CAS 失配、S3 上传失败、unzip 路径逃逸、worker crash/timeout；成功路径通过而失败路径无证据只能标为“待核”。
6. **当前核对实际边界**：未安装依赖、未启动服务、未运行 Vitest；仅完成静态源码/测试取证和文档静态门禁。本轮按用户授权未使用 MCP；本地 CodeGraph 已建立且索引最新，不能把静态证据升级为运行时或生产验证。

## 20. 后续裁决：吸收、废弃、待核

### 20.1 吸收

- **吸收图调度机制**：active/skip queue、边状态、并发槽、非递归推进、深度/运行次数预算；平台只定义通用节点执行契约。
- **吸收子运行机制**：clone/fork、child trace、attempt/iteration summary、显式 delta commit、父子资源额度传播。
- **吸收恢复机制**：checkpoint、入口节点、边状态、节点输出快照、历史重建、流恢复镜像、恢复游标与幂等投影。
- **吸收资源治理机制**：Redis lease、CAS 状态迁移、timer lock、provider adapter、worker supervisor、归档/恢复/清理四终态。
- **吸收验证机制**：错误分类、预算拒绝、重试上限、失败降级、反向破坏、残留资源审计和真实外部依赖分栏。

### 20.2 废弃

- **废弃复制 FastGPT 业务节点表**：节点名称、输入输出字段、提示词、知识库召回和 Agent prompt 不属于通用运行核心。
- **废弃复制插件业务链路**：personal/commercial/systemTool、市场版本和 `computedAppToolUsage` 是项目适配/商业域，不建第二套平台插件市场。
- **废弃复制聊天持久化链路**：`chat_items`、assistant value、引用、usage/积分字段不能成为平台通用状态表；平台只提供结果投影契约。
- **废弃复制沙箱产品链路**：Agent/Skill/IDE 的 sandbox id、镜像、工作目录、归档阈值、S3 source 和 volume 命名只在 FastGPT adapter 内保留。
- **废弃把停止标记当租约**：`agent_runtime_stopping` 是带 TTL 的取消信号；所有权/互斥必须走 token lease/CAS，不可用 `GET`/`DEL` 代替。
- **废弃无条件全局重试**：LLM、插件、交互、外部写入和不可幂等操作不能套同一个 retry loop；必须由能力契约声明错误分类、幂等键、资源费用和补偿。

### 20.3 待核

- runWorkflow 的停止检查能否中断已在运行的单个 provider/HTTP/LLM 请求，以及取消后的 usage/持久化一致性。
- 并行子运行多个任务写同一变量/output 时，当前“按完成顺序覆盖”是否满足目标平台所需一致性；如不满足，需 CAS/版本冲突而不是静默升级。
- stream resume 在 Redis 内存压力、请求长期阻塞、多个 tab 同时恢复和 Redis 重启下的完整性/容量上界。
- archive flow 在 S3 上传成功、远端删除成功、Mongo CAS 失败以及宿主强杀窗口中的最终对账和幂等恢复。
- worker/process supervisor 在主进程退出、SIGTERM、子进程树逃逸、IPC 半关闭和临时目录残留下的全量清理。
- 插件/MCP 的跨租户、跨版本、重定向和 secret 生命周期是否能被统一能力授权契约完整表达；本地代码有边界检查，但尚未做跨模块安全模型证明。

## 21. 后续交付记录

- **修改文件**：仅 `/Users/hekunhua/Documents/Agent/github 源码参考/15_知识库系统/FastGPT/ARCHITECTURE.md`，追加第 18—21 节；未修改源码、配置、依赖、测试、README、Git 或旧 `细探-FastGPT.md`。
- **工具边界**：本轮按用户授权未使用 MCP；证据来自 FastGPT 目标工作树的 Git、源码/测试静态读取与本地 CodeGraph。不得引用其他项目 MCP、代码图或验证记录。
- **验证命令**：当前核对只应执行文档静态检查 `git diff --check` 与目标文件/修改范围审计；Vitest、构建、服务探针和真实 Redis/Mongo/S3/provider/worker 验证未执行，不能报告为通过。
- **剩余风险**：见第 19.2、20.3；尤其是取消传播、跨存储崩溃一致性、并发状态写入、租约高并发和 worker/进程残留尚未得到真实运行证据。

## 22. 后续内部深挖：知识库摄取、解析、切分与制品生命周期

本节是对首轮和旧 `细探-FastGPT.md` 的后续收口。证据回到当前本地工作树；只记录源码能证明的调用链，并把静态发现但未运行验证的缺口单独标出。

### 22.1 摄取入口与来源分流

```text
临时 S3 文件 / 文本 / 图片 / 网页链接 / API Dataset 文件
  → API 鉴权、团队额度、请求 schema
  → Mongo dataset / dataset_collection / training usage
  → 直接切块，或写入 mode=parse 的 dataset_trainings
  → Mongo change stream + 启动补偿 + 每分钟 cron
  → 解析 → 切分/QA/图片阶段 → mode=chunk 训练记录
  → embedding/VLM → dataset_datas + dataset_data_texts + VectorDB
```

- `projects/app/src/pages/api/core/dataset/createWithFiles.ts:45-150` 创建知识库时先在 Mongo session 内写 `datasets` 和权限记录，再把 `temp/` S3 key 移到 `dataset/{datasetId}/...`，为每个文件调用 `createCollectionAndInsertData`。S3 `move` 不属于 Mongo 事务；Mongo 回滚不能自动回滚已完成的对象存储移动，这是摄取失败时必须对账的跨系统边界。
- `packages/service/core/dataset/collection/controller.ts:41-257` 把输入分为三类：有 `rawText`/`imageIds` 时立即切块并写训练记录；只有文件/链接/API 文件来源时创建一条 `TrainingModeEnum.parse` 记录，延迟到解析队列读取源文件。`auto` 在兼容层归一为 `chunk + autoIndexes=true`；QA、backup、template 会删除不适用的切分/图片/索引参数。
- `packages/service/core/dataset/read.ts:164-288` 的来源读取分流如下：本地文件必须是当前 dataset 授权的 S3 key；链接通过 `urlsFetch` 和可选 selector；external file 先 HEAD/流式 GET 并限制大小；API file 交给 `getApiDatasetRequest`。S3 key 不是只要格式正确就能读，`isAuthorizedDatasetFileS3Key` 还绑定 datasetId。
- `readFileRawTextByUrl` 对响应流累计字节并在超限时销毁 stream；完成后把 buffer 交给文件读取 worker。源码同时存在 HEAD 失败后跳过预检、GET 超时/close 清理和解析失败清理，因此 HEAD 成功不是最终大小保证，流式累计检查仍是权威限制（`packages/service/core/dataset/read.ts:26-156`）。
- `projects/app/src/pages/api/core/dataset/data/insertImages.ts:67-111` 把图片先上传到 private dataset S3，并设置 7 天 TTL，再插入训练记录；文本/文件中的解析图片则由 worker 的 `uploadFile` 回调按受控 prefix 写入，worker 不能直接传入任意路径片段（`packages/service/worker/function.ts:62-81`）。

### 22.2 文件解析与 CPU 隔离

- `packages/service/worker/readFile/index.ts:29-105` 是统一解析入口，当前显式支持 `txt/md/html/pdf/docx/pptx/xlsx/csv`；未知扩展名直接失败。解析任务使用 transfer `ArrayBuffer`，不满足独占条件时复制到 `SharedArrayBuffer`，调用方在 transfer 后不能继续复用原 buffer。
- `packages/service/worker/utils.ts:107-320` 的 `WorkerPool` 保证一个 worker 同时只跑一个任务；任务超时会终止并摘除 worker，`maxTasksPerWorker=100` 后回收，以隔离 `mammoth/xlsx/pdf-parse` 等依赖的潜在模块级内存增长；error/messageerror 会拒绝任务并删除 worker，等待队列继续调度。worker 线程数量来自 `PARSE_FILE_WORKERS`、`TEXT_TO_CHUNKS_WORKERS`。
- `packages/service/common/file/read/utils.ts:48-267` 的 PDF 解析可走内置解析，或在 `customPdfParse` 打开且配置存在时走外部服务、Textin、Doc2x 三选一；外部解析有 600 秒请求上限，并按页记录 PDF 解析 usage。解析结果中的 base64/HTTP Markdown 图片会被读取、上传并替换成 dataset 对象 key；外部服务成功但图片上传/后续 Mongo 写入失败时，仍需要依靠对象存储和数据清理对账。
- 解析不是“读取文件即完成”：`datasetParseQueue` 先原子领取 `mode=parse` 记录，再校验团队 AI 点数，读取 source，按 plus/配置决定是否调用段落 LLM，调用 `rawText2Chunks`，更新 collection 的 `rawTextLength/hashRawText`，在同一 Mongo session 写入后续训练记录并删除 parse 记录（`projects/app/src/service/core/dataset/queues/datasetParse.ts:106-355`）。dataset 超限会把任务锁到 2999 年；普通异常写 `errorMsg` 并把 `lockTime` 回拨 10 分钟等待重试（`:363-400`）。

### 22.3 切分契约与边界

- `packages/service/core/dataset/read.ts:291-372` 在切分前有三种触发策略：`backupParse` 将 CSV 首行作为表头丢弃、后续列映射为 `q/a/indexes`；`maxSize` 只有文本超过模型最大 token 的约 70% 才切；普通 `minSize` 只有超过配置阈值才切；否则保留一个原文 chunk。`forceChunk` 才跳过最小值门槛。
- `packages/service/common/string/textSplitter.ts:905-931` 先按 `CUSTOM_SPLIT_SIGN` 分区，再选择 Markdown table 专用处理或递归通用切分。通用顺序是自定义分隔符、Markdown 标题（最多 8 层）、代码块、HTML/Markdown 表格、段落、换行和中英文标点；自定义/标题阶段禁止 overlap，后续标点阶段按 `overlapRatio` 取尾部上下文。
- 切分同时支持 `char` 与 `token` 长度单位；token 模式按 Unicode code point 二分查找前缀/后缀，避免用字符下标误判 token 或切断代理对。代码块最多以 `min(maxSize, chunkSize*4)` 作为完整块预算，超长代码块再按 chunkSize 无 overlap 拆开；Markdown 表格会重复表头但在 token 模式再次计算表头占用，防止“行内安全、拼回表头超限”。
- `maxChunks` 是硬拒绝而不是静默截断：自定义分隔符、正则命中、递归输出和最终结果均检查上限；非法 chunkSize、overlapRatio、空自定义分隔符会直接抛错。切分后 `simpleText` 归一文本，`chunkIndex` 在入训练队列时按数组序号固定下来。
- 解析链把每个 chunk 转为 `dataset_trainings` 记录；`pushDataListToTrainingQueue` 会过滤纯空 q、过滤超过当前训练模式模型上限的 `q+a`，按 500 条批量 insert，单事务最多 20 批；超过 10,000 条时分段事务并用 `retryFn` 重试（`packages/service/core/dataset/training/controller.ts:73-261`）。

## 23. 后续内部深挖：训练队列、模型与工作流检索

### 23.1 `dataset_trainings` 是 Mongo 领取队列，不是 BullMQ

- 训练记录 schema 在 `packages/service/core/dataset/training/schema.ts:15-143`：每条任务带 team/tmb/dataset/collection/bill、`mode`、`retryCount`、`lockTime`、`expireAt`、q/a/image、indexes、dataId 和 error。`expireAt` 有 7 天 TTL；默认 BullMQ 并不承载知识库训练。
- `projects/app/src/service/core/dataset/training/utils.ts:8-36` 对 `MongoDatasetTraining.watch()` 的 insert 事件按 `parse/qa/chunk` 启动对应处理器；`startTrainingQueue(true)` 在启动时预热多个循环，每分钟 cron 再补一次，`unlockTask` API 可人工补偿。这里是“Mongo change stream 触发 + 进程内并发槽 + cron 扫描”的混合队列，不是持久化 job scheduler。
- 三个处理器通过 `findOneAndUpdate` 领取任务并把 `lockTime` 设为 now、`retryCount` 减一：parse/QA 只重新领取超过 10 分钟的任务，vector 超过 3 分钟（`datasetParse.ts:123-132`、`generateQA.ts:55-64`、`generateVector.ts:98-107`）。进程内 `datasetParseQueueLen/qaQueueLen/vectorQueueLen` 只限制当前 Node 实例；跨实例一致性依赖 Mongo 原子更新和锁时间，而非全局并发计数。
- parse 阶段成功产生 chunk/QA/image 后删除当前阶段记录；QA 先 LLM 生成 `Qn/An`，正则解析失败则退回 `text2Chunks`，再写 `mode=chunk`；vector 阶段成功后在 Mongo session 中删除训练记录。点数不足时 `lockTrainingDataByTeamId` 把团队剩余任务写成 `BLOCKED_LOCK_TIME=2050-01-01` 和错误文本，避免继续消费（`training/controller.ts:19-71`、`queues/utils.ts:9-29`）。
- **静态缺口（待运行/版本复核）**：`getDatasetImageTrainingMode` 能返回 `imageParse` 或 `image`（`packages/service/core/dataset/utils.ts:194-208`），`insertImages.ts:97-110` 和 `rebuildEmbedding.ts:149-184` 也会写这两种 mode；但当前本地 `createDatasetTrainingMongoWatch`、`startTrainingQueue` 和 `generateVector` 的领取条件只显式处理 `parse/qa/chunk`。当前核对未运行 Mongo change stream，不能把它直接定性为线上缺陷；应把 image/imageParse 是否由未展开的商业/外部启动路径消费列为 P0 复核项，不能宣称图片训练链已闭环。

### 23.2 训练模式、模型选择与计费边界

| 阶段 | 领取/处理 | 模型与限制 | 成功制品 |
|---|---|---|---|
| `parse` | `datasetParseQueue` | `agentModel` 可做段落 LLM；文件解析受 worker/外部 PDF 600 秒边界 | 删除 parse 记录，写 chunk/后续 mode 训练记录 |
| `qa` | `generateQA` | dataset `agentModel`；LLM 输出 Q/A，结果解析失败降级普通切分 | 删除 QA 记录，写 `mode=chunk` |
| `chunk` | `generateVector` | dataset `vectorModel`；embedding 批量请求、重试、token 计费 | `dataset_datas`、全文 token、VectorDB 向量 |
| `imageParse/image` | 当前源码可创建 | VLM/多模态 embedding 能力由 `getDatasetImageIndexCapability` 决定；本地消费路径待核 | 不把“已创建任务”当作“已生成图片索引” |

- `packages/service/core/ai/config/utils.ts:27-225` 从 plugin `listModels()` 与 Mongo `MongoSystemModel` 合并模型；只把 active 模型加入 map，同时用 `model` 和 `name` 两个别名登记，读取 DB metadata 覆盖 provider、defaultConfig、fieldMap、maxResponse 和价格层。默认模型缺失时退回 active map 的第一项；这是可用性 fallback，不是调用方指定模型一定存在的证明。
- `packages/service/core/ai/model.ts:8-82` 的 `getLLMModel/getEmbeddingModel/getVlmModel/getRerankModel` 对字符串按 map 查找，查不到时多数路径回退默认模型；因此上层的“模型未配置”分支只有在默认模型本身为空时才会触发。dataset 持久化的是模型标识，运行时解析的是当前全局 map，模型下线/改名会影响历史 dataset 的再训练和检索。
- `packages/service/core/ai/embedding/index.ts:46-193` 是 embedding 最后入口：输入先 Zod 校验和 trim，文本按 token 计数并按 `model.maxToken` 做单条截断（不拆分），按 `batchSize` 分批顺序请求，单批 `retryFn`；没有 usage 时本地补 token 计数。向量维度超过 1536 截断，低于 1536 补零，可按模型配置归一化。知识库完整内容必须在上游切分，不能依赖 embedding 入口补救。
- 工作流的 `datasetSearchNode` 在 `packages/service/core/workflow/dispatch/dataset/search.ts` 读取首个 dataset 的 `vectorModel/vlmModel`，解析 rerank 模型并组装 search data，再调用 `defaultSearchDatasetData`；Agent 的 dataset tool 走同一搜索层。工作流只持有检索契约和引用输出，不直接写 VectorDB。

### 23.3 检索细节：两条召回链共享同一集合过滤

- `defaultSearchDatasetData` 先清理 text query；开启 extension 时调用 `datasetSearchQueryExtension` 生成 search queries 和 rerank query，再进入 `searchDatasetData`（`packages/service/core/dataset/search/index.ts:18-69`）。
- `multiQueryRecall` 先并行求 forbidden collection 与 metadata filter，再把同一约束下发给 embedding 和 Mongo full-text（`.../defaultRecall/multiQueryRecall.ts:31-73`）。这保证权限/禁止集合不会因为切换召回方式而漂移。
- embedding 召回把用户文本、图片 caption 作为 text embedding；只有模型 `vision` 时才把原始图片转 base64 做 image embedding；向量库返回 index dataId 后，再按 `dataset_datas.indexes.dataId` 回查主 data 和 collection，并在每个 query 内去重、多 query 间做 RRF 合并（`.../embeddingRecall.ts:39-126,180-303`）。
- full-text 只查 `dataset_data_texts` 的 Mongo `$text` 索引；query 先 `jiebaSplit`，按 textScore 排序，再批量回查主 data/collection。该表只保存 `teamId/datasetId/collectionId/dataId/fullTextToken`，展示内容不复制到全文表（`.../fullTextRecall.ts:62-155`、`packages/service/core/dataset/data/dataTextSchema.ts:9-50`）。
- rerank 只作用于文本召回；失败降级原文本结果。最终顺序仍是文本/图片加权融合 → 同内容去重 → 相似度阈值 → token 裁剪 → 批量签发图片预览 URL，且只有最终保留的对象 key 才签发 90 天预览链接（`defaultRecall/index.ts:120-183`、`packages/service/core/dataset/data/controller.ts:73-111`）。

## 24. 后续内部深挖：数据库、向量与制品一致性

### 24.1 写入顺序与所有权

```text
训练记录(dataset_trainings)
  → embedding/VLM provider
  → VectorDB.insert 得到 index dataId
  → Mongo dataset_datas 写 q/a/image/indexes[dataId]
  → Mongo dataset_data_texts 写 jieba fullTextToken
  → removeS3TTL(image)
  → collectionUpdate BullMQ debounce
```

- `projects/app/src/service/core/dataset/data/data.ts:96-205` 明确先生成系统/外部索引，再写 VectorDB，拿到向量 id 后写 `dataset_datas`，随后写 `dataset_data_texts`，最后移除图片 TTL。这样 Mongo 中的 index dataId 不会先指向不存在的向量，但如果向量已写入而 Mongo 或全文表写入失败，仍可能出现孤儿向量；现有 cron 只能事后清理，不能提供跨存储事务。
- 更新路径 `data.ts:214-323` 先写新向量，再把新 indexes 写回 Mongo/全文 token，Mongo 指向新向量后才删除旧向量；内容变化保留最多 10 条 history。`forceRebuild` 用于切换 embedding 或强制重建，不能把新旧向量删除顺序倒置。
- `dataIndex.ts:498-676` 把 patch 分为 create/update/delete/unChanged；系统索引 `default/imageEmbedding` 由当前 q/a/image 自动重建，custom/question/summary/image 等外部索引被保留。相同文本和类型复用旧 dataId，避免重复 embedding；更新人工索引时先写新向量、再替换 Mongo、再删旧向量。
- `dataset_datas` 是权威 chunk/索引清单，`dataset_data_texts` 是全文检索派生表，VectorDB 是向量派生制品，S3 是图片/解析图片对象制品；任何“删除/重建完成”声明都必须同时对账这四类对象，不能只看 Mongo 主表。

### 24.2 删除、软删除、TTL 与孤儿清理

- dataset 主 schema 有 `deleteTime` 软删除字段；真正清理由 `datasetDelete` BullMQ，jobId 为 `teamId-datasetId`，延迟 1 秒，默认指数退避、最多 10 次，失败记录保留（`packages/service/core/dataset/delete/index.ts:1-42`）。
- `packages/service/core/dataset/controller.ts:67-128` 的相关清理顺序覆盖 `dataset_trainings`、`dataset_data_texts`、`dataset_datas`、VectorDB、collections 和 dataset S3 files；单个 data 删除还会删图片对象与其 indexes 中的全部向量（`projects/app/src/service/core/dataset/data/data.ts:451-479`）。
- 训练记录 `expireAt` 是 7 天 TTL；临时图片对象通常先带 7 天 TTL，成功成为 dataset data 后 `removeS3TTL`。解析过程生成的图片 key 也有 prefix 约束，但链接解析图片的长期过期/知识库删除联动在源码中留有 TODO，必须列入制品残留风险。
- `projects/app/src/service/common/system/cronTask.ts:18-151` 每小时在 Redis timer lock 下检查过去 6 至 2 小时的异常 dataset data：若 collection 不存在，删 training/data_text/vector/data；另一路扫描 VectorDB 时间范围，对 Mongo `dataset_datas.indexes.dataId` 不再引用的向量做删除。这是补偿性清理，不是事务回滚。
- `packages/service/common/bullmq/index.ts:25-151` 的 BullMQ 只负责显式的 dataset/app/team/S3/collection 等异步运维队列；全局 Map 复用 Queue/Worker，worker 默认 10 分钟 lock、30 秒 stalled 检查，closed 后无限重建。知识库训练仍由 app 进程内 Mongo 领取循环处理，二者不能混为同一队列语义。

## 25. 后续契约、失败矩阵与验证等级

### 25.1 关键契约表

| 边界 | 输入/输出 | 失败与重试 | 资源责任/幂等 |
|---|---|---|---|
| 摄取 API | 认证请求 → dataset/collection/training 记录 | schema/权限/额度失败；Mongo session 回滚，S3 move 需外部对账 | temp key 由上传端持有；move 后 collection/解析链负责 dataset key |
| 文件解析 | buffer+extension → rawText/formatText | worker 超时/解析器异常；PDF 外部服务 600 秒；单文件下载上限 | worker 消费 buffer；uploadFile 只接受 basename+prefix；finally 清理 handler |
| 切分 | rawText+chunk settings → bounded chunks | 参数、空分隔符、单字符超 token、maxChunks 超限直接失败 | text worker 单任务；chunkIndex 由入队方生成 |
| 训练领取 | Mongo training → mode-specific output | 原子 claim，锁超时重试；点数不足永久阻塞到 2050 | retryCount 是数据库剩余尝试，不是 BullMQ attempts |
| embedding/vector | text/image inputs → vectors/index ids | provider retry；空输入/模型错误失败；向量库 retry | VectorDB 先写，Mongo indexes 后写；补偿清理孤儿 vector |
| 检索 | queries+filters → cited chunks | caption/image/rerank 失败尽量降级；主召回仍可返回 | 只为最终候选签发预览 URL；搜索不持有写权限 |
| 删除/重建 | dataset/data → 派生制品收敛 | BullMQ 退避；跨存储部分失败保留失败任务/靠 cron 对账 | 权威 owner 是 Mongo 主数据；VectorDB/S3/full-text 为派生制品 |

### 25.2 反向场景与当前证据

| 场景 | 源码已有机制 | 当前核对等级/缺口 |
|---|---|---|
| 空/超大输入 | API schema、流式大小检查、切分参数/maxChunks、embedding trim+截断 | **源码存在**；未运行超大 PDF、token 极端值和 Unicode 边界 |
| provider 不可用 | embedding/向量库 retry；PDF/图片路径局部失败；rerank/caption 降级 | **部分实现**；统一错误码、退避预算、成本上限未证明 |
| 重复训练/多实例 | Mongo 原子 `findOneAndUpdate`、lockTime、change stream + cron | **源码存在**；未做多实例竞争/进程崩溃注入 |
| 部分写入 | session 覆盖 Mongo 子步骤；向量先写、失败后 cron 查孤儿 | **补偿而非事务**；跨 VectorDB/Mongo/S3 崩溃一致性待核 |
| 取消/超时 | worker 任务超时终止、队列锁和 stalled；训练循环无独立 Abort 协议 | **部分实现**；已在运行的解析/provider 请求取消传播待核 |
| 图片训练 | 能力判断、image/imageParse 记录生成、图片向量与 VLM 分支代码存在 | **静态链路未闭合**；本地 mode 消费者只显式处理 parse/qa/chunk，需优先复核 |
| 删除/重建 | BullMQ 删除、Mongo session、旧向量延后删除、小时级孤儿扫描 | **源码存在**；真实 S3/VectorDB/Mongo 对账未执行 |

### 25.3 后续验收结论

- **已吸收**：真实摄取来源分流、S3 key 授权与 TTL、worker 解析边界、token/字符切分算法、Mongo 训练队列的领取/重试/阻塞语义、模型 map/fallback、embedding 批量与维度归一化、full-text 派生表、向量/Mongo 写入顺序、删除与孤儿补偿链路。
- **降级为待核**：`imageParse/image` 任务是否存在当前本地树外的消费者；S3 move 与 Mongo transaction 的跨系统回滚；解析图片长期 TTL 及删除联动；多实例 change stream 与锁竞争；VectorDB 写成功后 Mongo 失败的实际孤儿规模；取消对外部 PDF/LLM/embedding 请求的传播。
- **当前核对没有运行**：未安装依赖、未启动 Mongo/Redis/VectorDB/S3/模型服务、未运行 Vitest、未构建 worker；因此文中的“源码存在/测试存在”不等于“生产链路通过”。
- **后续唯一维护入口**：当前核对事实已写入根 `ARCHITECTURE.md`；`细探-FastGPT.md` 保留为历史细探，不再新增平行细探文件。

## 26. 后续真实源码收口：端到端边界、失败与资源释放

本节把后续取证从“知识库内部链路”收口到可执行的端到端边界。以下结论均回到当前本地源码；前端页面、Next API、app service、共享 service、worker、Mongo/VectorDB/S3 和模型 provider 分开描述。源码存在不等于真实依赖可用，也不把局部 `try/catch` 误判为跨系统事务。

### 26.1 从浏览器到制品的完整路径

```text
dataset detail 页面 / 外部 API 客户端
  → Next pages/api/core/dataset/*
  → parseApiInput 或 multipart multer
  → authDataset + Write/OwnerPermission + team quota
  → collection controller
  → Mongo dataset_collection + dataset_trainings
  → change stream / 启动补偿 / cron
  → parse（来源读取、文件解析、可选段落 LLM、切分）
  → qa（可选 Agent LLM 生成问答）
  → chunk（embedding / image-VLM / VectorDB）
  → Mongo dataset_datas + dataset_data_texts
  → collection update job + 检索可见
```

入口并非单一“上传接口”：`create/localFile.ts` 接收 multipart、限制扩展名和大小、先传 dataset S3，再创建 collection，最后在 `finally` 删除本地临时文件；`create/fileId.ts` 只接受已存在且格式合法的 dataset S3 key；`create/text.ts` 将文本先上传为私有 S3 对象，成功建 collection 后移除 TTL；`create/apiCollection.ts` 通过配置的 API dataset server 获取外部文件详情。这些 API 都在进入 service 前完成 schema 解析或 multipart 解析，并通过 `authDataset` 绑定 dataset、team、成员和写权限。

前端 `projects/app/src/pages/dataset/detail/index.tsx` 只负责页面壳、dataset context、导航和动态加载 Collection/Data/Test/Import 子页面；它不直接访问 Mongo、VectorDB、模型或 S3。数据读写经 React context/request hooks 调 Next API。后端边界由 `pages/api` 负责 HTTP 形状、鉴权和配额，`projects/app/src/service/core/dataset` 负责应用编排，`packages/service/core/dataset` 负责共享领域模型/读取/搜索，`packages/global` 负责类型和 schema。这个边界允许工作流检索复用同一 service 搜索入口，但禁止浏览器绕过 API 直接拿内部对象 key 或模型配置。

### 26.2 摄取来源、文件所有权与解析释放

| 来源 | API/存储动作 | 解析动作 | 主要释放/残留边界 |
|---|---|---|---|
| 浏览器本地文件 | `multer.resolveFormData` → dataset S3 上传 | `mode=parse` 延迟读取 | `finally` 清 disk temp；S3 已上传但 Mongo 创建失败需补偿 |
| 预上传 fileId | 校验 dataset prefix、读取 metadata | collection 记录引用，随后 parse | 不复制文件；错误时不会误读其他 dataset key |
| 文本 | Buffer 上传到 private S3，初始带 TTL | 按文件解析，再进入 parse/chunk | 成功后 `removeS3TTL`；中间失败依赖 TTL/清理 |
| 链接 | collection 保存 URL/selector | `urlsFetch`/selector 读取，随后解析 | HTTP response 流和超时需关闭；外链不是永久文件副本 |
| external/API file | API server 或远端 URL | HEAD/GET 或 API adapter 读取 | 大小由流式累计检查兜底；远端失败不应留下已完成 chunk |
| 图片 | 私有 dataset S3，临时 TTL | image/VLM 或多模态 embedding 分支 | 正式 data 成功后移除 TTL；图片训练消费者仍需单独核验 |

`readDatasetSourceRawText` 把 file/link/apiFile/externalFile 映射为统一来源读取契约。外部 URL 的 HEAD 只是优化，GET 流累计字节才是硬限制；超限时销毁 stream，异常和 close 路径需要释放 response/body。文件解析经 `packages/service/worker/readFile` 和 `WorkerPool` 执行，worker 一次只处理一个任务；超时、error、messageerror 会终止并摘除 worker，达到最大任务数也回收，避免解析器模块长期积累内存。调用方 transfer `ArrayBuffer` 后不得继续使用原 buffer。

解析完成后，`datasetParseQueue` 在 Mongo 原子领取 `mode=parse`，读取 source、可选调用 600 秒段落 LLM、调用 `rawText2Chunks`，然后在 Mongo session 中更新 collection 摘要、批量插入 chunk 训练记录并删除 parse 记录。文件读取、worker、HTTP 和临时 S3 对象分别属于不同资源所有者；Mongo session 只覆盖 Mongo 写入，不能回滚已完成的网络读取、S3 move/upload 或 provider 请求。

### 26.3 三阶段队列不是统一 job queue

训练队列的真实形态是 **Mongo 持久记录 + change stream 触发 + app 进程内并发槽 + 启动/cron 扫描**：

1. `createDatasetTrainingMongoWatch` 只处理 insert，并按 `parse`、`qa`、`chunk` 启动对应循环；`startTrainingQueue` 在启动时主动补偿扫描。
2. 每个处理器用 `findOneAndUpdate` 原子设置 `lockTime` 并减少 `retryCount`；parse/QA 使用约 10 分钟锁超时，vector 使用约 3 分钟锁超时。锁是跨实例去重的事实，`global.*QueueLen` 只限制当前 Node 进程。
3. 余额不足不是普通重试：`checkTeamAiPointsAndLock` 通知团队并把任务锁到未来时间；数据集超限在 parse 阶段也会把任务锁到 2999 年。普通异常写 `errorMsg` 并回拨锁时间，允许后续重试。
4. `qa` 领取任务后解析 LLM Q/A，解析失败时降级普通切分，成功后写入新的 `chunk` 任务；`chunk` 领取后生成向量/系统索引并完成 data 写入。BullMQ 只承载 dataset 删除、collection update 等运维/派生任务，不能当作训练三阶段的实际调度器。

这意味着 change stream 中断时依赖启动/cron 补偿，进程级队列长度不会形成全局吞吐预算；服务重启或多实例扩容时必须验证锁过期、重复领取和最终收敛。当前源码能证明 `parse/qa/chunk` 消费者，不能仅凭 `getDatasetImageTrainingMode` 创建 `image/imageParse` 记录就证明本地存在对应消费闭环。

### 26.4 模型解析、工作流检索与前后端调用边界

模型配置的权威运行时是全局 active model map：配置层合并 provider `listModels()` 与 Mongo `MongoSystemModel`，按 model/name 建别名并覆盖 provider、字段映射、响应上限和价格；`getLLMModel`、`getEmbeddingModel`、`getVlmModel`、`getRerankModel` 负责将 dataset 保存的字符串解析成当前运行时模型。多数 getter 在找不到指定项时回退默认模型，因此历史 dataset 的模型标识不会自动锁定历史 provider；模型下线、改名或默认模型变化会影响再训练和查询。

embedding 入口先校验并 trim 文本，按模型最大 token 截断单条输入，按 batch 顺序请求并对单批重试；缺失 usage 时本地补 token。向量维度会按当前实现补零或截断到约定维度。它不是切分器，超过模型上限的完整内容必须在 parse/chunk 或 index patch 层拆分。VLM 只在图像能力判断通过时参与 imageParse/image embedding；rerank 只处理文本召回。

工作流侧的 `datasetSearchNode` 和 Agent dataset tool 不自行连接 VectorDB，而是读取 dataset 模型配置、构造过滤/引用参数并调用 `defaultSearchDatasetData`。因此前端知识库测试页、聊天工作流和外部 API 共用搜索领域服务；HTTP/API 层只能提交经过 schema 的查询和 dataset 授权，不能把 provider client、Mongo session 或内部向量 id 暴露给 UI。

### 26.5 数据库、向量库、全文表和 S3 的一致性方向

`DatasetDataOperation.create` 的顺序是：规范化系统/外部 indexes → 写 VectorDB 得到 dataId → Mongo `dataset_datas` 写带 dataId 的主记录 → Mongo `dataset_data_texts` 写 Jieba 全文 token → 移除图片临时 TTL → 推送 collection update。这样避免 Mongo 先指向不存在的向量，但不能避免 VectorDB 已成功、Mongo 后续失败而形成孤儿向量。

更新索引时先创建新向量，Mongo 指向新 dataId 后再删除旧向量；主记录保存最多 10 条内容 history，全文 token 与主记录在 Mongo session 内更新。`dataIndex` 通过 create/update/delete/unchanged patch 区分系统索引和 custom/question/summary/image 等外部索引；切换 embedding model 时可强制认为所有索引变化。这个顺序降低悬空引用风险，但 Mongo transaction 仍不覆盖 VectorDB 或 S3。

删除是软删除 dataset 后交给 BullMQ `datasetDelete`，再清理 training、全文表、主 data、VectorDB、collection 和 dataset S3。小时级 cron 扫描 collection 缺失的异常 data，并扫描未被 `dataset_datas.indexes.dataId` 引用的向量；这是补偿性收敛，不是分布式回滚。解析图片、临时图片、向量孤儿和 S3 move 失败必须以 Mongo 主数据、VectorDB、全文表和对象存储四方对账，不能以单个 job 成功作为删除完成。

### 26.6 失败传播与资源释放矩阵

| 失败点 | 当前行为 | 仍需保持的释放/补偿契约 |
|---|---|---|
| API schema/权限/配额 | 在 API 边界拒绝，不进入训练 | multipart 临时文件仍走 `finally`；已上传对象需 TTL/补偿 |
| source 下载/解析 | 记录 error、回拨 lockTime；worker/provider 失败不提交后续训练 | 关闭 response stream、终止超时 worker、清理临时文件 |
| 段落/QA LLM | 阶段失败可重试；QA 结果格式异常降级普通切分 | 不能重复扣费或无幂等地重复写 chunk；usage 与 training id 关联 |
| dataset 超限/余额不足 | 任务长期锁定，通知或错误记录 | 不能继续占用 worker/队列槽；恢复额度后须有显式解锁入口 |
| VectorDB 成功、Mongo 失败 | 可能产生孤儿向量，依赖 cron/清理 | 记录 index/data identity，删除与重建必须可重入 |
| Mongo 成功、全文表/TTL 失败 | 主数据可能可见但派生制品不完整 | 以 collection update/对账任务补齐，不把 session 当跨系统事务 |
| change stream/进程崩溃 | 启动和 cron 重新领取过期锁 | 验证 lockTime、retryCount、队列槽归零和无重复最终制品 |
| 客户端断开 | 不应等同于训练取消；工作流另有 stop/resume 机制 | provider 请求取消传播、usage、写入和临时资源需分别定义 |
| 删除/重建中止 | BullMQ 重试和 cron 补偿 | Mongo 主状态、VectorDB、S3、全文表必须最终可对账 |

### 26.7 后续真实源码裁决

- **已收口**：知识库入口的 API/权限/配额边界；local/fileId/text/link/API/external/image 来源分流；S3 key 授权与 TTL；worker 解析及超时回收；parse→qa→chunk 的 Mongo 领取语义；模型 map/fallback、embedding 批处理；工作流统一检索入口；VectorDB→Mongo→全文表→S3 TTL 的写入顺序；删除、重建和孤儿扫描；前端仅经 Next API 访问后端领域服务。
- **不能宣称已闭环**：`image/imageParse` 的本地消费者；change stream 中断和多实例竞争下的最终吞吐；S3/Mongo/VectorDB 跨系统回滚；外部 PDF/LLM/embedding 请求的取消传播；provider 下线后历史 dataset 模型的稳定性；worker/子进程在宿主强杀下的全量残留清理。
- **当前核对验证等级**：真实源码静态收口；未安装依赖、未启动 Mongo/Redis/VectorDB/S3/模型服务、未运行前端或后端测试。不得把本文的源码链路描述写成生产可用性、性能或故障恢复证明。
- **唯一修改范围**：本次后续收口仍只修改根 `ARCHITECTURE.md`；未改源码、配置、依赖、锁文件、测试、前端组件、旧细探或 Git 历史。

## 27. 知识库系统深度研究补充：从 API 到检索制品

本节按用户要求对本地工作树中的知识库摄取、worker、解析/QA/切块、Mongo/向量/全文/S3、工作流/API、测试和部署配置重新建立索引。它是对第 22—26 节的源码导航和边界补充，不改变前述“静态源码证据不等于运行验证”的结论。

### 27.1 API 面：来源不是一个上传接口

知识库 API 集中在 `projects/app/src/pages/api/core/dataset/`，目录同时包含 dataset/collection/data/training/index/file/folder/apiDataset 等资源面。入口共同经过 `NextAPI`，写操作通常先调用 `authDataset` 绑定 `datasetId`、team、成员和 `WritePermissionVal`，再执行 `checkDatasetIndexLimit`；JSON 请求使用 `parseApiInput` 和 global 的 OpenAPI/Zod schema，multipart 文件则由 `multer.resolveFormData` 解析。

当前摄取来源和初始动作如下：

| 来源 | 入口/持久化动作 | 后续训练模式 |
|---|---|---|
| 本地文件 | `collection/create/localFile.ts` 校验扩展名/大小，上传到 dataset 私有 S3，再创建 file collection；`finally` 删除本地临时路径 | 通常 `parse` |
| 已上传 fileId | `collection/create/fileId.ts` 校验 dataset S3 key 和 metadata，不重新复制对象 | `parse` |
| 原始文本 | `collection/create/text.ts` 将 Buffer 写入私有 S3 临时对象，成功后移除 TTL | `parse` 或直接 `chunk`，取决于 controller 归一化参数 |
| 网页链接 | `collection/create/link.ts` 保存 URL 和可选 selector，不把网页内容预先复制为本地文件 | `parse`，读取阶段执行 `urlsFetch` |
| API dataset / external file | collection 保存外部标识或 URL，由 `readDatasetSourceRawText` 选择 API adapter、HEAD/GET 流或外部文件读取 | `parse` |
| 图片 | `collection/create/images.ts` 或 `data/insertImages.ts` 上传 private dataset S3，临时对象带 TTL | image/imageParse/chunk 的组合由模型能力和 collection 配置决定；本地训练消费者是否完整覆盖 image 两种 mode 仍待运行复核 |
| 结构化备份/模板 | `create/backup.ts`、`create/template.ts` 直接把结构化字段映射为 q/a/indexes | 可跳过普通解析，按 backup/chunk 规则写训练记录 |

API 只负责请求边界和应用编排，不直接持有 VectorDB client、embedding provider 或 Mongo session。前端 dataset detail 页面通过 request hooks 调用这些 API；工作流节点和 Agent dataset tool 复用 service 层搜索入口，而不是绕过 HTTP/领域服务读取内部对象。

`createCollectionAndInsertData` 的关键分流在 `packages/service/core/dataset/collection/controller.ts`：已有 `rawText`/`imageIds` 的数据可以立即进入切块和训练记录；file/link/API/external 等来源先写 `TrainingModeEnum.parse`。兼容参数 `auto` 会归一为 `chunk + autoIndexes=true`，QA、backup、template 会清除不适用的切分或图片索引选项。Mongo session 只包住 Mongo 写入；S3 upload/move 已完成后发生 Mongo 失败，不能由 session 回滚。

### 27.2 解析 worker 与输入释放

`packages/service/worker/readFile/index.ts` 是文件解析 worker 的统一入口，当前本地源码显式覆盖 `txt`、`md`、`html`、`pdf`、`docx`、`pptx`、`xlsx`、`csv` 等类型。调用方将 `ArrayBuffer` 通过 worker transfer 传递；transfer 后不能继续使用原 buffer。解析结果中的图片可能由 worker 的受控 `uploadFile` 回调上传到 dataset 对象存储，回调只接受受控 prefix/basename 组合，避免解析器把任意路径片段写入 S3。

`packages/service/worker/utils.ts` 的 `WorkerPool` 是有界线程池而非无限 Promise 并发：

- 一个 worker 同时只执行一个任务，其他任务进入等待队列；
- 任务超时、`error` 或 `messageerror` 会 reject 当前任务并终止/摘除 worker；
- 达到 `maxTasksPerWorker=100` 后主动回收 worker，隔离 PDF、Office、HTML 等依赖的长期内存增长；
- worker 数量由 `PARSE_FILE_WORKERS`、`TEXT_TO_CHUNKS_WORKERS` 等环境配置影响；
- `preLoadWorker` 在 Node instrumentation 初始化阶段预热，worker 构建由 `projects/app/scripts/build-workers.ts` 和 app package 的 `build:workers` 参与。

PDF 路径可使用内置解析，或在配置启用时选择 custom PDF provider、Textin、Doc2x 等外部解析服务；外部请求的源码边界为约 600 秒超时，并会记录按页解析 usage。源文件读取还存在 HEAD 优化、GET 流累计大小限制、超限销毁 body、close/异常清理等多重边界，HEAD 成功不能替代 GET 流的最终大小校验。

### 27.3 三阶段训练 worker 的真实状态机

训练记录 schema 位于 `packages/service/core/dataset/training/schema.ts`，集合名为 `dataset_trainings`。记录包含租户和来源身份（`teamId`、`tmbId`、`datasetId`、`collectionId`）、计费关联 `billId`、阶段 `mode`、`retryCount`、`lockTime`、7 天 TTL 的 `expireAt`、q/a/image/indexes/chunkIndex/dataId 和 `errorMsg`。索引覆盖租户/数据集、collection 状态、`mode + retryCount + lockTime + weight` 排序及 TTL。

训练调度由 `projects/app/src/service/core/dataset/training/utils.ts` 统一接线：

```text
MongoDatasetTraining.insert
  → Mongo change stream（仅 insert 分流）
  → parse / qa / chunk 对应循环

进程启动 startTrainingQueue(true) 或每分钟 cron
  → 主动扫描并补偿未处理/锁过期记录

每个循环
  → findOneAndUpdate(mode, retryCount > 0, lockTime 过期)
  → 原子占锁 + retryCount 减一
  → 阶段处理
  → 成功删除当前记录并写下一阶段，或记录 errorMsg 等待重试
```

三个消费者的差异是架构事实：

| 消费者 | 领取锁窗口 | 核心动作 | 成功产物 |
|---|---:|---|---|
| `datasetParseQueue` | 约 10 分钟 | 读取 file/link/API/external source，解析 raw text，可选段落 LLM，调用 `rawText2Chunks`，校验 dataset limit | 更新 collection 标题/长度/hash；批量写 `chunk` 或训练模式记录；删除 parse 记录 |
| `generateQA` | 约 10 分钟 | 用 dataset `agentModel` 和 collection QA prompt 请求 LLM，按 `Qn:/An:` 正则解析 | 写 `chunk` 记录；格式不符合时退回 `text2Chunks` 普通切分；删除 qa 记录并记 QA usage |
| `generateVector` | 约 3 分钟 | 用 `vectorModel` 生成 embedding，执行新建或重建 data/index；处理 image/VLM 派生索引 | 写 `dataset_datas`、全文派生表和 VectorDB 制品；成功后删除 chunk 记录并记 embedding usage |

余额不足不是普通瞬态错误：`checkTeamAiPointsAndLock` 会把任务延迟锁定，避免 worker 持续消费；dataset 超限在 parse 阶段也会被锁到远未来。普通异常写 `errorMsg` 并把锁拨回可领取时间。`global.*QueueLen` 只限制当前 Node 实例的并发槽，Mongo 原子 claim 才承担跨实例去重，因此它不是全局吞吐预算。

这里必须区分两种队列：BullMQ 的 `QueueNames` 包括 `datasetDelete`、`collectionUpdate`、`s3FileDelete`、`datasetSync`、evaluation 和团队/app 删除等；它负责运维、同步、删除和派生更新。训练 parse/qa/chunk 并不通过 BullMQ job 领取，而是 Mongo 持久任务加 change stream/cron 的混合模型。change stream 中断时，启动补偿、每分钟 cron 和锁过期是恢复依赖。

### 27.4 切分与 QA 的可观察契约

`rawText2Chunks` 在 `packages/service/core/dataset/read.ts` 与 `packages/service/common/string/textSplitter.ts` 之间组合：

- `backupParse` 将 CSV 首行作为表头并映射后续列为 q/a/indexes；
- `maxSize` 只在文本超过模型最大 token 的约 70% 时触发；普通 `minSize` 在超过配置阈值后才触发；`forceChunk` 可跳过最小值门槛；
- 分隔顺序覆盖自定义分隔符、Markdown 标题、代码块、HTML/Markdown 表格、段落、换行和中英文标点；标题/自定义阶段不做 overlap，后续阶段按 `overlapRatio` 带回尾部上下文；
- 支持 `char` 和 `token` 长度单位；token 模式使用 token 计数和前缀/后缀二分，而不是把字符长度当 token 长度；
- Markdown 表格会保留表头，但会重新计入表头 token；代码块有更大的完整块预算，超长代码块再拆分；
- `maxChunks`、非法 chunk size、非法 overlap ratio、空自定义分隔符和最终超限都是显式失败，不是静默截断；入队时固定 `chunkIndex`；
- 训练 controller 按 500 条批量插入，单事务最多 20 批；超过 10,000 条会分段事务并配合 `retryFn`。

QA 阶段不是独立的知识库存储格式。LLM 生成的问答对先正则转换为 q/a；没有可解析结果时，直接将原文普通切块并把 a 置空，然后仍进入 `chunk` 向量阶段。因此 QA prompt 的输出协议失败会降级召回质量，但不会必然阻塞整个摄取链。

### 27.5 Mongo、VectorDB、全文与 S3 的职责分离

知识库的权威关系可以概括为：

```text
Mongo dataset_collections / dataset_trainings
  → Mongo dataset_datas（权威 chunk + index 清单）
  → Mongo dataset_data_texts（全文检索派生 token）
  → VectorDB（向量检索派生 index dataId）
  → S3/MinIO/OSS/COS（源文件、图片、解析图片、预览对象）
```

`packages/service/common/vectorDB/controller.ts` 根据 `SEEKDB_ADDRESS`、OceanBase、PG、Milvus、OpenGauss 等配置选择一个 controller；写入入口负责 embedding、retry、插入和 team vector count cache 失效，查询入口负责带过滤条件的向量召回。向量库内的文本向量和图片向量最终都是 `number[][]`，输入类型只影响 embedding provider 的生成方式。

全文召回由 Mongo `dataset_data_texts` 的 `$text` 索引执行。查询先经 `jiebaSplit`，只回传 `dataId`、`collectionId` 和 text score，再批量回查 `dataset_datas` 与 collection 补 q/a/indexes。全文派生表不复制展示正文，且 filter/forbid collection 条件与向量召回共享同一组约束。

向量召回把文本 query、图片 caption 作为 text embedding；只有当前 embedding model 支持 image 时，原始图片才会转 base64 并走 image embedding。VectorDB 返回 index dataId 后，service 用 `dataset_datas.indexes.dataId` 回查权威 chunk。每个 query 内先按 data 去重，多 query 再做 RRF/列表合并。

S3 SDK 在 `sdk/storage` 抽象 `IStorage`，支持 AWS S3-compatible、MinIO、COS、OSS 的 bucket/object、metadata、stream download、multipart upload、批量/前缀删除、presigned URL 和 abort signal。service 层再划分 public/private bucket，并由 `getS3DatasetSource()` 约束 dataset key 前缀、对象授权、TTL、下载别名和预览链接。开发 compose 默认是 Mongo replica set、Redis 7、pgvector 和 MinIO；生产部署模板可切换 S3-compatible vendor 与向量后端。

创建新 data 的实际顺序是：生成/写 VectorDB → Mongo `dataset_datas` 写入返回的 index dataId → Mongo `dataset_data_texts` 写全文 token → 移除临时图片 TTL → collection update。更新时新向量先写入，Mongo 指向新索引后再删除旧向量。顺序避免 Mongo 先引用不存在的向量，但不能形成跨 VectorDB/Mongo/S3 的事务；VectorDB 成功后 Mongo 失败仍可能产生孤儿向量，小时级 cron 和删除/重建任务承担补偿收敛。

### 27.6 检索、工作流和外部 API 的汇合点

`defaultSearchDatasetData` 是知识库检索统一入口，工作流 `datasetSearchNode` 与 Agent dataset tool 都调用它。链路保持以下顺序：清理 query → 可选 query extension → VLM caption → embedding/full-text 在相同 collection filter 下并行召回 → text/image caption/image vector 分类合并 → 仅文本结果 rerank → 去重、相似度过滤和 token 截断 → 最终为保留的图片 key 签发预览 URL → 返回引用数据给工作流/Agent。

API 的 `searchTest`、数据引用/预览、training detail/error、collection read 和工作流节点共享这个领域层，但权限仍在 API 或 service authorization 层完成。检索结果只提供引用和预览所需字段，不把 Mongo session、provider client 或裸向量 id 作为前端契约。模型标识保存在 dataset，但运行时通过 active provider model map 解析；历史模型下线、改名或默认模型变更可能影响重新训练和检索，这是配置漂移风险而非 dataset 快照锁定。

### 27.7 测试与配置证据地图

测试基于 Vitest，workspace 默认由根 `scripts/test/withMongo.mjs` 包装 Mongo 测试环境后，经 Turbo 运行 app、global、service 等包；root `turbo.json` 透传 `FASTGPT_TEST_MONGODB_URI`、`FASTGPT_TEST_MAX_WORKERS`。app 和 service 的 `vitest.config.ts` 都使用共享 `test/setup.ts`、`test/globalSetup.ts`、线程池和最多 10 的测试并发；service 默认排除 `test/integrations/**`，向量集成单独运行。

知识库直接相关的静态测试入口包括：

- `packages/service/test/core/dataset/read.test.ts`：dataset S3 key 必须位于被授权 dataset 前缀下，未授权 key 不会调用读取器；
- `packages/service/test/core/dataset/textSplitter.test.ts`：max/min/force 分块及 Markdown 结构行为；
- `packages/service/test/worker/readFile/parseOffice.test.ts`、`worker/utils.test.ts`、`worker/htmlStr2Md.test.ts`、`worker/tokenWorkerConfig.test.ts`：解析 worker 和线程池边界；
- `packages/service/test/common/vectorDB/controller.test.ts`：统一 vector controller；
- `packages/service/test/common/s3/*`：key、上传约束、token、access link、delete queue、mime 和 mock storage；
- `packages/service/test/core/workflow/dispatch/dataset/search.test.ts`、`utils.test.ts` 以及 Agent dataset tool 测试：工作流/Agent 到 dataset search 的适配；
- `packages/service/test/integrations/vectorDB/`：通过 `testSuites.ts` 工厂复用 PGVector/OceanBase/Milvus 等 controller 测试，缺少对应环境变量时整体跳过；这类跳过不是默认 workspace 单测的基础设施证明。

配置侧的关键事实来自 `deploy/dev/docker-compose.yml`：Mongo 以 replica set 启动以支持 change stream/事务，Redis 作为队列、锁和缓存，MinIO 提供 public/private object storage，pgvector 是默认向量后端；code-sandbox 另有 body、timeout、memory、output、pool size 和内网检查限制。配置模板支持切换 `STORAGE_VENDOR`、S3 endpoint/bucket、`PG_URL`、`OCEANBASE_URL`、`MILVUS_ADDRESS` 等，但源码选择 controller 和真实服务连通性必须分别验证。

本次深度研究仍未启动服务、安装依赖或运行 Vitest。因而上述测试文件说明“存在的验证面”，配置说明“声明的运行条件”，不说明当前机器上的 Mongo change stream、Redis lock、VectorDB、S3、LLM、VLM 或 worker 已通过真实端到端验证。

### 27.8 深度研究后的未决问题

- `imageParse`/`image` 训练记录在当前开源本地树中的完整消费者闭环仍需在运行时和版本范围内确认；创建记录和重建分支本身不能作为消费证明。
- change stream 重启、多实例竞争、锁过期和进程崩溃后的最终训练吞吐尚未用真实 Mongo replica set 验证。
- VectorDB 写入后 Mongo/S3 失败的孤儿向量、解析图片长期 TTL、dataset 删除联动需要跨制品对账测试。
- 外部 PDF、段落 LLM、QA LLM、embedding/VLM 请求的 Abort/取消传播和 usage 幂等仍未形成统一取消协议。
- 当前根 package 仍要求 Node `>=20.19.0`、pnpm `10.x`；远程 4.16.x 的 Node/DAL 变化不能回写为本地架构事实。

## 28. 后续分段审计：知识库摄取、状态、资源与文档冲突

本节是当前核对按“摄取 → worker → parse/QA/chunk → Mongo/VectorDB/full-text/S3 → workflow/API → tests/config/docs”顺序重读后的收口。目标工作树没有 `.codegraph/`，CodeGraph 明确返回不可用；以下证据来自当前源码、测试、配置和文档静态读取，未启动服务、安装依赖或运行测试。

### 28.1 分段源码导航

| 分段 | 事实入口 | 审计结论 |
|---|---|---|
| 摄取/API | `projects/app/src/pages/api/core/dataset/collection/create/*`、`createWithFiles.ts`、`packages/service/core/dataset/collection/controller.ts` | API 先做 schema、dataset/team/member 权限和额度边界；来源可为本地文件、已上传 fileId、文本、链接、API/external file、图片、backup/template。浏览器不直接写 Mongo/VectorDB。 |
| 文件 worker | `packages/service/worker/readFile`、`text2Chunks`、`worker/utils.ts` | 文件解析和 CPU 切分在 `worker_threads`；WorkerPool 单 worker 单任务，等待队列、任务超时销毁、error/messageerror 摘除、达到任务数回收。没有看到统一宿主退出时排空所有等待任务的公共契约。 |
| parse/QA/chunk | `projects/app/src/service/core/dataset/queues/{datasetParse,generateQA,generateVector}.ts` | `dataset_trainings` 是 Mongo 持久任务；change stream、启动补偿和每分钟 cron 触发进程内循环，不是 BullMQ 训练 job。阶段成功删除当前记录并写下一阶段，普通错误写 `errorMsg`、回拨 `lockTime`；余额不足或 dataset 超限进入长期阻塞。 |
| Mongo 主数据 | `packages/service/core/dataset/{schema,collection/schema,data/schema,data/dataTextSchema,training/schema}.ts` | `dataset_datas` 是 chunk/index 权威清单，`dataset_data_texts` 是全文派生表，`dataset_trainings` 是阶段任务；训练记录 7 天 TTL，主数据和集合另有软删除/清理链。 |
| VectorDB | `packages/service/common/vectorDB/controller.ts`、`core/dataset/data/data.ts` | 根据环境选择一个 PG/Milvus/OceanBase/SeekDB/OpenGauss controller；向量先写、Mongo 再引用返回的 index dataId，降低悬挂引用但不提供跨存储事务。 |
| Full-text | `core/dataset/search/defaultRecall/fullTextRecall.ts` | Mongo `$text` 查询 `dataset_data_texts`，经 jieba 分词后只取 id/score，再回查 Mongo 主 data/collection；全文和 embedding 共享 collection filter/forbid 约束。 |
| S3/对象制品 | `common/s3/sources/dataset/*`、`sdk/storage` | dataset 私有 bucket 负责 presign、key 前缀授权、原文件/解析图片/临时图片、TTL 和异步删除；S3 upload/move 不受 Mongo session 回滚。 |
| workflow/API 汇合 | `core/workflow/dispatch/dataset/search.ts`、`core/dataset/search/index.ts`、dataset API | 工作流节点、Agent dataset tool、搜索测试和外部 API 复用同一 search service；最终才签发图片预览 URL，不把裸 VectorDB id 或 provider client 暴露给前端。 |
| tests/config/docs | `test/*`、`packages/service/test/*`、`turbo.json`、`deploy/dev/docker-compose.yml`、`document/content/*dataset*` | 默认测试隔离 Mongo，VectorDB/S3 集成为外部依赖；compose 声明 Mongo replica set、Redis、MinIO、pgvector，但声明不等于当前环境连通或端到端通过。 |

### 28.2 数据、状态和资源审计

知识库的权威关系应按以下方向理解：

```text
API/上传对象
  → Mongo dataset_collections + dataset_trainings
  → parse → optional QA → chunk/image
  → embedding/VLM
  → VectorDB index ids
  → Mongo dataset_datas.indexes
  → Mongo dataset_data_texts
  → S3 TTL 移除/collection update
```

关键状态不是一个统一枚举：

- 训练任务由 `mode`、`retryCount`、`lockTime`、`errorMsg` 表达阶段、剩余领取次数、租约窗口和最近失败；任务领取时原子减少 `retryCount`，所以重试计数消耗发生在真正处理前。
- parse/QA 约按 10 分钟重新领取，vector 约按 3 分钟重新领取；进程内 `global.*QueueLen` 只限制单实例，Mongo 原子 claim 才承担多实例去重。change stream 中断、进程崩溃和长期锁依赖启动/cron 扫描收敛。
- 余额不足会通知团队并把任务锁到 `BLOCKED_LOCK_TIME`；dataset 超限会把 parse 任务锁到 2999 年。这两类状态不是普通 retry，恢复额度或容量后需要显式解锁/补偿路径。
- `imageParse`/`image` 记录可以由图片能力判断和重建路径创建，但当前开源树中已明确读到的消费者领取条件主要是 `parse`、`qa`、`chunk`；不能把“任务已创建”写成“图片索引已完成”，应作为最高优先级运行复核项。

跨系统资源的正常与异常边界如下：

| 资源 | 正常责任 | 失败/恢复风险 |
|---|---|---|
| worker thread | WorkerPool 持有单任务槽，完成后空闲或按上限回收 | timeout/error 会终止 worker；宿主 SIGTERM、等待队列和子 worker 全量排空未见统一证明 |
| HTTP/PDF/LLM/embedding | 各阶段调用方持有请求和 usage 关联 | 局部 timeout/retry 存在，但没有统一 Abort、取消费用和幂等写入协议 |
| Mongo session | 覆盖 Mongo 内的集合、训练、主 data、全文派生写入 | 不覆盖 S3、VectorDB、外部 provider；不能把 session 当分布式事务 |
| VectorDB index | data 写入流程先创建，Mongo 成功引用后再删除旧索引 | VectorDB 成功而 Mongo 失败会留下孤儿向量，依赖小时级扫描/删除重建补偿 |
| S3 object/TTL | 临时文件和图片由 TTL/异步删除管理，正式 data 成功后移除临时 TTL | S3 move/upload 与 Mongo 回滚脱钩；解析图片长期过期和 dataset 删除联动仍有 TODO/待对账边界 |
| BullMQ queue | dataset delete、collection update、S3 delete、dataset sync 等运维/派生任务 | 默认 worker 有 lock/stalled/restart 和失败保留策略，但不覆盖训练三阶段的任务语义 |

### 28.3 失败恢复审计结论

已由源码证明的恢复机制：Mongo 原子领取、锁超时重新领取、change stream 之外的启动/cron 补偿、阶段错误记录、dataset/collection 删除队列重试、worker 超时回收、S3/VectorDB 孤儿清理扫描、旧向量延迟删除以及 QA 输出解析失败后的普通切分降级。

仍不能宣称闭环的恢复场景：

1. VectorDB 写成功后 Mongo、全文表或 S3 后续失败时的精确对账、幂等重放和孤儿规模。
2. change stream 断连、多个 app 实例竞争、进程在 claim 或 provider 调用中崩溃时的最终吞吐和 retry 预算。
3. 外部 PDF、段落 LLM、QA LLM、embedding/VLM 请求被主动取消后的 provider abort、usage 结算和后续 Mongo 写入一致性。
4. S3 move/upload 成功后 Mongo transaction 回滚，以及解析图片长期对象在 dataset 删除时的完整联动。
5. `imageParse`/`image` 任务在当前本地开源树中的实际消费者和失败重试路径。

### 28.4 文档重复与冲突裁决

当前文档分为三类，不能混用：

- 根 `ARCHITECTURE.md` 是本地源码审计和证据边界的唯一汇总入口；第 22—28 节保留分段源码导航和风险结论，后续只在此处追加事实，不再扩写平行细探。
- `document/content/guide/dataset/dataset_engine.mdx` 的检索说明仍与当前实现基本一致：多向量映射、embedding/full-text/mixed、RRF、文本 rerank、token 上限和图像 caption/image embedding 均可由当前搜索代码对应。但其中“采用 PostgreSQL PG Vector、HNSW”只代表一种文档/部署叙述；当前 controller 明确支持多种 VectorDB，不能当作唯一运行实现。
- `document/content/self-host/design/dataset.mdx` 是明显历史冲突：它写“文件通过 MongoDB FS、数据通过 PostgreSQL”“浏览器解析”“training 表后插入 PG”，而当前代码使用 S3/MinIO-compatible 私有对象、服务端 worker、Mongo `dataset_trainings`/`dataset_datas`/`dataset_data_texts` 和可切换 VectorDB。该文档应视为过期设计说明，不能作为当前架构事实引用。
- `document/content/openapi/dataset.mdx` 是接口示例和参数说明，不应承担内部队列、存储一致性或恢复语义；它与代码版本漂移时应按 API schema/handler 校正，不能反向定义内部实现。
- 旧根 `细探-FastGPT.md` 继续保留为历史调查材料；它包含早期 Mongo FS/PG 叙述和重复架构摘要，后续维护应引用本文件的已核源码事实，不再复制更新两套文档。

### 28.5 测试与验证等级

- 当前静态存在针对 `read`、text splitter、worker、VectorDB controller、S3、dataset search、workflow dataset adapter 和 API 的单元测试；Mongo 使用 `mongodb-memory-server` 或共享测试 Mongo 数据库隔离，测试 worker 默认 4，可由 `FASTGPT_TEST_MAX_WORKERS` 覆盖。
- VectorDB integration suite 按 PG/OceanBase/Milvus/SeekDB/OpenGauss 分组，依赖外部服务配置；默认 service 测试排除 integrations。测试文件存在、mock 返回成功和 compose 有服务声明，都不能证明生产链路、跨系统回滚或资源无残留。
- 当前核对只完成静态分段取证和文档更新；未执行 `pnpm test`、Vitest、构建、Mongo/Redis/VectorDB/S3/模型连接或压力/故障注入。因此所有“已证实”均限定为源码结构和静态配置事实。

### 28.6 当前核对裁决

## 29. 2026-08-22 当前最新版源码整项目复核

### 29.1 版本、目录规模与代码地图

本轮在源码根目录完成 `git fetch origin main`、`git pull --ff-only origin main`，结果为 `Already up to date`。当前证据如下：

| 项目 | 当前事实 |
|---|---|
| Git | `HEAD=main=origin/main=76687002`；领先/落后 `0/0` |
| 主应用版本 | `projects/app/package.json:1-24` 为 `4.16.1` |
| 运行时 | 根 `package.json:41-45` 要求 Node `>=22.23.2`、pnpm `10.33.4`；Next catalog 为 `16.3.0` |
| 受版本控制文件 | 5,973（`git ls-files`；主要目录计数：`packages` 2,494、`projects` 1,925、`document` 1,185、`sdk` 131） |
| 主要代码文件 | TypeScript 2,856；TSX 855；JavaScript 129；Rust 20；Go 7；MDX 496 |
| CodeGraph | 3,960 files / 55,553 nodes / 185,440 edges；索引 `up to date` |
| 源码工作树 | 未跟踪 `.codegraph/` 与源码侧 `ARCHITECTURE.md`；本轮保留，不修改源码 |

CodeGraph 查询 `dispatchWorkFlow chat completions datasetSearchNode Agent toolCall training queue MongoDB Redis BullMQ` 定位到当前 `packages/service`、`packages/dal`、`projects/app` 和 sandbox/MCP 边界；后续结论以这些源码的当前行号为准。注意：文件总数按 `git ls-files` 重新统计时应以命令原始输出为准，不能把目录计数相加后当成去重总数。

### 29.2 当前真实端到端调用链

```text
浏览器 / SDK / OpenAI 兼容客户端 / MCP 客户端
                 │ HTTP、SSE、文件上传、MCP SSE
                 ▼
projects/app（Next.js 16.3.0）
  pages/_app.tsx + pages/api/*
  NextAPI → createApiEntry → withNextCors
                 │
                 ├─ v1/v2 chat/completions
                 │    → parseApiInput(CompletionsPropsSchema)
                 │    → authChatCompletionHeaderRequest / share auth
                 │    → teamFrequencyLimit
                 │    → AppVersion + Store nodes/edges
                 │    → dispatchWorkFlow
                 │
                 ├─ core/dataset/*
                 │    → dataset/controller + training controller
                 │    → Mongo dataset_trainings / source files
                 │    → parser/chunk/QA/embedding/vector/full-text
                 │
                 └─ core/plugin/* / support/mcp/* / invoke/*
                      → plugin/MCP/API adapters
                 │
                 ▼
packages/service（领域服务与 Workflow Runtime）
  Store graph → Runtime graph
  dispatchWorkFlow → runWorkflow → node callback map
  LLM / Agent / Tool / Dataset Search / Loop / Parallel / Human Input
                 │
                 ├─ packages/dal（RedisRuntime + Cache + BullMQ）
                 ├─ MongoDB/Mongoose（业务状态、训练状态、聊天、运行记录）
                 ├─ VectorDB / full-text / S3 storage
                 └─ 外部模型、插件、MCP、sandbox
                 │
                 ├─ projects/code-sandbox（Hono + JS pool + isolated Python）
                 ├─ projects/mcp_server（MCP SSE sessions → FastGPT API）
                 └─ projects/volume-manager（Hono volume/PVC 控制面）
```

`projects/app/src/service/middleware/entry.ts:1-15` 是所有 Next API 的统一入口包装；`projects/app/src/pages/api/v2/chat/completions.ts:90-172` 先解析 Zod 合约，再分流外链或 API/token 鉴权。`packages/service/core/workflow/dispatch/index.ts:184-231` 在执行前检查 AI 点数、登记文件与大小限制；`packages/service/core/workflow/dispatch/index.ts:1577-1605` 暴露 `runWorkflow`，工作流内部再按 callback map 分发节点。该路径证明 FastGPT 的“API、工作流、知识库、Agent”不是四套独立服务，而是 Next API 进入同一个 service runtime 的不同入口。

### 29.3 DAL 与队列的当前实现（已从旧 4.15 结论升级）

`packages/dal` 已是当前源码中的正式 workspace，而非远程设计草案：

- `packages/dal/redis/runtime/index.ts:1-50` 导出 Redis runtime、配置、健康指标、错误类型、逻辑 keyspace 和 shutdown hook；业务层不应自行创建裸 Redis client。
- `packages/dal/redis/bullmq/context.ts:9-37` 以 `globalThis` symbol 保存进程级 runtime，热重载时复用 Queue/Worker；若绑定到不同 Redis runtime 则主动抛错，避免跨实例串接。
- `packages/dal/redis/bullmq/binding.ts:25-61` 是服务层唯一 BullMQ binding，统一默认 Worker 配置：完成/失败任务立即清理、lock 10 分钟、stalled 检查 30 秒、最大 stalled 3 次；业务只声明 queue name/processor。
- `packages/dal/redis/bullmq/queue-manager.ts:21-50,64-84` 为 Queue 复用、错误 listener、超时关闭和 force disconnect；创建失败会释放连接。
- `packages/dal/redis/bullmq/worker-manager.ts:34-55,82-169` 为 Worker 复用、暂停恢复、关闭后自动重启、业务 listener 快照迁移和有界关闭；重启循环在 runtime 仍为 running 时按延迟重试。
- `packages/dal/redis/bullmq/services/*.ts` 将 dataset sync/delete、collection update、evaluation、S3 delete、team/skill delete 等队列业务绑定到同一 DAL；这不是新的业务状态 owner，Mongo 训练/文档状态仍由 service 模型持有。

当前与旧文档的关键差异是：Redis/BullMQ 的连接和生命周期已经有独立 DAL 边界，但 BullMQ 仍是任务投递/执行协调器，不自动成为工作流、训练或制品的唯一事实账本；重复投递、业务幂等和跨 Mongo/S3/vector 的补偿仍由各 service 负责。

### 29.4 知识库摄取与检索的当前源码链

```text
上传/外部来源/手工数据
  → dataset API/controller
  → MongoDatasetTraining(dataset_trainings)
  → 团队 timer lock（training/controller.ts:19-70）
  → parse / chunk / QA / image / embedding
  → Mongo collection + VectorDB + full-text + S3/file refs
  → training 状态/错误/重试计数
  → defaultSearchDatasetData
       → query extension（可选 LLM）
       → default recall（向量/全文/权重/RRF/rerank）
       → tenant/dataset/collection filter
       → quote list / workflow node response / Agent tool observation
```

`packages/service/core/dataset/training/controller.ts:19-70` 以团队 timer lock 防止多 worker 同时锁训练记录，并在 finally 释放锁；`73-148` 按 chunk/QA/auto/image/imageParse 选择 embedding、LLM 或 VLM 模型与 token 上限；模型缺失直接返回错误，不伪造训练成功。`packages/service/core/dataset/search/index.ts:18-69` 是统一检索入口，先规范化 query，可选生成扩展检索词与 rerank query，再调用 default recall；`74-75` 的 deep RAG 通过全局 handler 作为扩展边界，避免具体 recall 实现反向持有全局适配。

该链的核心数据边界是：Mongo `dataset_trainings` 保存训练任务与错误/重试状态；文件/S3 保存原始与中间制品；VectorDB 保存向量；全文存储与 rerank 负责召回排序；最终引用通过 workflow response/quote list 返回。任何一处成功都不能单独证明整条摄取事务已经完成。

### 29.5 Agent、工具与工作流节点

- `packages/service/core/workflow/dispatch/ai/agent` 将 Agent 节点装配为 workflow runtime；`toolProvider/createWorkflowAgentToolProvider.ts` 生成 readFile、datasetSearch、sandbox 等系统工具；`toolcall/toolProvider/createToolCallToolProvider.ts:59-120` 将 dataset search node ids 包装成可调用工具，并以 `runWorkflow` 作为工作流工具执行器。
- `packages/service/core/workflow/dispatch/index.ts` 的 callback map 将 `datasetSearchNode`、agent、toolCall、pluginModule、appModule、parallelRun、loopRun、MCP 和交互节点绑定到统一调度器；子工作流由 `runWorkflow` 递归进入，但每个子运行复制 runtime nodes/edges 与变量上下文，避免父运行状态直接污染。
- Agent/Tool 的模型层仍由 `packages/service/core/ai/model` provider registry 按模型配置产生 LLM/embedding/VLM 实例；调用后的 usage、引用、节点响应由 workflow response 与 chat usage 记录持久化。
- 交互节点（`userSelect`、`formInput`、`ask_user`）通过历史 response/interactive state 暂停；恢复是既有 workflow execution 的 checkpoint 续跑，不是任意 worker 崩溃接管。

### 29.6 沙箱、MCP 与外部进程边界

- `projects/code-sandbox/src/index.ts:90-126` 创建 Hono app、JS `ProcessPool`、Python `PythonIsolatedRunner` 与 `QueueIdLimiter`；初始化失败退出进程，`/health` 在池未就绪时返回 `503`。`81-88` 限制代码体积为 5 MB；`175-180` 显示 token 配置缺失时 API 可能无认证，生产必须设置 `SANDBOX_TOKEN`。
- `projects/mcp_server/src/index.ts:20-103` 为每个 `/:key/sse` 建立独立 MCP `Server` 与 `SSEServerTransport`，用 `transportMap` 按 session id 保存连接；`onclose/onerror` 删除连接或记录错误，工具调用最终转到 FastGPT API 的 `callTool`。这是 session 级 transport registry，不是持久化任务队列。
- `projects/volume-manager/src/index.ts:1-35` 是独立 Hono 卷管理服务，提供 Docker/Kubernetes 存储驱动适配；其状态不能与 Mongo 业务状态混为一谈。
- `projects/fastgpt-ide-agent` 与 `projects/agent-sandbox*` 是独立运行时/商业边界；本轮只确认目录存在，不把其内部行为写成当前已验证事实。

### 29.7 并发、失败与资源释放矩阵

| 资源/故障 | 当前源码行为 | 仍未证明 |
|---|---|---|
| Next API 断流 | v1 创建 client abort tracker；V2 通过停止标记/stream context 协同 workflow | 断流后所有外部调用、Mongo 写入和向量写入均已终止 |
| Workflow 并发/循环 | parallelRun 深拷贝 runtime 状态、限制并发；loopRun 有最大迭代/停止条件 | 跨进程执行接管、重复提交幂等 |
| BullMQ Worker 关闭 | Worker manager 监听 closed/paused，恢复或重启并迁移业务 listener | 进程崩溃中 job 的业务去重与 Mongo/vector/S3 补偿 |
| Redis 关闭 | DAL runtime 有角色连接、健康指标、shutdown hook、force disconnect | Redis 恢复期间任务状态是否最终一致 |
| 训练并发 | team timer lock + Mongo `retryCount/lockTime` | 多地域时钟漂移、锁抢占者崩溃后的 reaper |
| Sandbox 进程 | JS pool + Python isolated runner；队列按 queueId 限流 | 真实 OS 级隔离、强杀后的制品清理 |
| MCP SSE | session map，close/error 清理 | 多实例共享 session、重连回放、连接泄漏长期运行表现 |
| Mongo/S3/vector 多写 | 各 service 按阶段更新状态并记录错误 | 跨系统事务、孤儿制品扫描、向量与全文对账 |

### 29.8 当前版本裁决与后续验证边界

本轮已把旧第 11 节“本地落后 4.16 远程”的结论降级为历史记录；当前 `main` 已同步到 4.16.1，`packages/dal`、Node 22、Next 16 和 BullMQ runtime 均属于本地源码事实。后续架构映射应选择：

1. **支持库**：Redis runtime、BullMQ Queue/Worker 生命周期、S3/storage、模型 provider、向量检索适配器、sandbox 进程适配器；只提供原子能力和资源释放。
2. **模块库**：知识库摄取、默认检索、Agent 工具 provider、工作流节点组合、训练任务编排；不得直接持有裸 Redis/第三方 SDK。
3. **运行核心**：Workflow `runWorkflow`/调度状态、执行上下文、事件/响应投影、停止/恢复与 usage 归集；必须补统一 execution/attempt/idempotency 契约。
4. **项目适配层**：FastGPT 的 tenant/team/app/version、模型配置、API 路由和外部部署环境；不能被误吸收为通用支持库。

已验证：Git 版本同步、CodeGraph 索引状态、目录/文件统计、关键源码行号、文档结构静态检查。未验证：pnpm 安装、Next build、Mongo/Redis/BullMQ/VectorDB/S3、模型 provider、sandbox、MCP server、真实训练/检索、故障注入和 E2E。任何运行成功、性能数字或崩溃恢复声明都必须等后续在端口 4780 及隔离资源上实测后再升级证据等级。

- **吸收为当前事实**：S3 私有对象 + dataset key 授权、服务端 worker 解析、Mongo 训练状态机、parse/QA/chunk 分阶段、Mongo 主数据与全文派生表、VectorDB 可替换 controller、检索多路融合、BullMQ 运维队列与测试隔离边界。
- **标记为文档过期/冲突**：Mongo GridFS、浏览器解析、PG 为唯一数据存储、训练线程直接插 PG 的旧 self-host dataset 设计；不得继续作为当前架构依据。
- **标记为待核**：image/imageParse 消费闭环、跨 Mongo/VectorDB/S3 事务与恢复、取消传播和 usage 幂等、多实例锁/吞吐、宿主强杀后的 worker 与临时对象清理。
