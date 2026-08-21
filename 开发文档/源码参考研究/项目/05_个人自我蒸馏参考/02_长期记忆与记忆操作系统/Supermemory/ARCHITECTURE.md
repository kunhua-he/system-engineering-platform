```text
外部 AI 应用 / Agent / 用户
        │
        ├── JavaScript/TypeScript SDK 与工具
        │     ├── supermemory 客户端（仓库外部依赖）
        │     ├── @supermemory/tools
        │     │     ├── AI SDK tools / middleware
        │     │     ├── OpenAI middleware / function tools
        │     │     ├── Mastra processors / wrapper
        │     │     └── VoltAgent hooks / middleware
        │     └── packages/ai-sdk
        │
        ├── Python SDK 适配层
        │     ├── openai-sdk-python（tools + middleware）
        │     ├── agent-framework-python（tools + middleware + context provider）
        │     ├── pipecat-sdk-python（pipeline service）
        │     └── cartesia-sdk-python（voice agent wrapper）
        │
        └── 本仓库应用入口
              ├── apps/web：Next.js 控制台 / onboarding / 配置界面
              ├── apps/browser-extension：浏览器端采集与检索入口
              ├── apps/raycast-extension：Raycast 搜索/添加入口
              └── apps/mcp：Cloudflare Worker MCP 边缘入口
                                      │
                                      ▼
                        OAuth/JWT 校验 + 组织/用户空间解析
                                      │
                                      ▼
                McpServer（每个 HTTP 请求新建，stateless protocol）
                                      │
                 ┌────────────────────┼─────────────────────┐
                 ▼                    ▼                     ▼
          tools/注册器          resources/prompts       MCP App widgets
   search/add/list/get/...       profile/spaces/context  picker/save/upload/graph
                 │                    │                     │
                 └────────────────────┴─────────────────────┘
                                      │
                                      ▼
                  SupermemoryClient（本仓库的 API 适配边界）
                     ├── supermemory SDK：add/search/profile/documents
                     └── fetch：/v3 与 /v4 的特定接口
                                      │
                                      ▼
                外部 Supermemory API（默认 https://api.supermemory.ai）
                                      │
          ┌───────────────────────────┴───────────────────────────┐
          ▼                                                       ▼
   文档/分块/向量/记忆/画像/空间                        连接器/文件处理/分析等
   （本仓库仅有契约与客户端，不含服务端实现）

图谱展示数据流：
外部 API → web/graph playground 或 MCP fetch-graph-data
         → DocumentWithMemories / GraphApiDocument
         → useGraphData → D3 force simulation + Canvas renderer
         → VersionChainIndex / 交互式记忆图谱

MCP 持久化的边缘状态流：
认证用户(orgId,userId) → SpaceState Durable Object
  ├── activeContainerTag（当前空间）
  └── upload:<uuid>（短期上传会话，token 只存 SHA-256）
```

# Supermemory 架构文档

> 本文只描述当前 checkout 中由源码、依赖清单、测试和仓库文档能够确认的结构。仓库根目录没有 `AGENTS.md`，但 `packages/pipecat-sdk-python/AGENTS.md` 提供该 Python 适配包的局部规则。未安装依赖、未启动服务、未运行测试、未修改已有源码。

## 1. 项目定位

Supermemory 是一个围绕 AI 记忆、用户画像、语义检索和上下文注入组织的 Turbo/Bun monorepo。根 `README.md` 将其定位为 memory and context layer，并将能力概括为记忆、用户画像、混合检索、连接器和多模态文件处理。

从本地源码边界看，本 checkout 主要包含：

- Web 控制台及其 API 客户端：`apps/web/`、`packages/lib/`、`packages/validation/`。
- MCP Worker：`apps/mcp/`，负责 OAuth 保护、MCP 工具/资源/prompt 和 MCP App widget。
- 面向 AI 框架的 TypeScript 工具包：`packages/tools/`、`packages/ai-sdk/`。
- 面向 OpenAI、Microsoft Agent Framework、Pipecat、Cartesia 的 Python 适配包。
- 记忆图谱的 React/Canvas 可视化包：`packages/memory-graph/`。

关键边界是：本地没有发现 Supermemory 主 API 的服务端路由、数据库迁移、ORM schema、内容摄取 workflow 或向量索引实现。`packages/lib/api.ts`、MCP client 和多个 SDK 默认都把请求发往 `https://api.supermemory.ai`；因此本地仓库应判断为“控制台 + 边缘入口 + SDK/工具 + 图谱组件”的多包客户端/集成仓库，而不是完整的 API 后端源码镜像。

## 2. 真实分层与职责

### 2.1 根级编排与工程约束

- `package.json:2-21`：仓库为私有 monorepo，workspaces 覆盖 `apps/*` 与 `packages/*`，排除 Raycast 和测试 chatapp；根脚本通过 Turbo 执行 build/dev/check-types，Biome 负责 format-lint；运行时要求 Node `>=20`、包管理器为 `bun@1.3.6`。
- `turbo.json:4-23`：build 依赖上游包 build，check-types 依赖上游类型检查；dev/dev:app 禁用缓存并保持常驻。
- `CLAUDE.md:5-11,26-45`：把仓库描述为 Turbo monorepo，列出 web 与 mcp，并记录 `/v3`、`/api/auth` 等外部 API 能力；这些路由在当前 checkout 中没有对应的完整后端实现，需与源码事实区分。
- `CONTRIBUTING.md:49-73,102-109`：给出 apps/packages 目录意图、Turbo/Bun/TypeScript/Next.js/Cloudflare/OpenNext 技术栈，但目录说明包含部分当前未核实或未在根 workspace 中启用的条目，因此本文以实际文件为准。

### 2.2 契约与数据模型层

- `packages/validation/schemas.ts:3-59`：定义 `Metadata`、可见性、文档类型和处理状态；处理状态明确包含 `queued → extracting → chunking → embedding → indexing → done/failed` 这些外部数据状态。
- `packages/validation/schemas.ts:61-124`：`DocumentSchema` 表示文档/记忆载体，包含 `orgId`、`userId`、`connectionId`、内容/摘要/URL、类型、状态、处理元数据、token/word/chunk 统计和 summary embedding 字段；`ChunkSchema` 关联 `documentId`，有 position、文本/图片类型、embedding 与创建时间。
- `packages/validation/schemas.ts:126-167`：`ConnectionStateSchema` 和 `ConnectionSchema` 建模 OAuth/连接器状态、所属组织用户、provider、token 生命周期、文档上限、container tags 和 provider metadata。
- `packages/validation/schemas.ts:218-237`：`SpaceSchema` 表示空间，包含组织、owner、`containerTag`、可见性、实验标记、内容索引统计及时间戳。
- `packages/validation/schemas.ts:239-294`：`MemoryEntrySchema` 是核心记忆条目模型，包含记忆正文、空间/组织/用户归属、`version`、`isLatest`、父/根记忆 ID、`updates|extends|derives` 关系、来源计数、inference/forgotten/static 标记、遗忘时间/原因、embedding 和时间戳；`MemoryDocumentSourceSchema` 建模记忆到文档的来源关联。
- `packages/validation/api.ts:50-139`、`:194-305`、`:560-791`、`:1048-1134`：将记忆、文档、分块、profile、分页和搜索结果暴露为 Zod/OpenAPI 契约。`SearchRequestSchema` 支持 container tags、过滤器、阈值、结果数量、全文/摘要、rerank/query rewrite；`MemorySearchResult` 支持相似度、版本、父子上下文和关联文档。
- `packages/memory-graph/src/api-types.ts:1-50`、`src/types.ts:5-42`：图谱输入继续保留 `updates|extends|derives`、版本、父/根 ID、latest/forgotten、遗忘原因和文档-记忆关系；这说明图谱组件消费的是带版本/关系的后端响应，而非自己生成记忆事实。
- `apps/mcp/src/shared/types.ts:6-117`、`:119-204`：MCP server 与 widget 共享另一组边界契约，包含 session scope、读写权限、空间摘要、文档-记忆嵌套结构、分页以及 picker/save/upload/graph 的 discriminated union 视图消息。

### 2.3 Web 控制台与 API 客户端层

- `apps/web/package.json:9-21,23-131`：Web 是 Next.js 16/React 19 应用，使用 OpenNext Cloudflare 部署、TanStack Query、Tiptap、React PDF、Radix UI、Sentry 等；脚本只有 dev/build/check-types/start/preview/deploy/upload 等。
- `apps/web/app/(app)/page.tsx:1-5`：主应用页渲染 `AppExperience`；`apps/web/app/(app)/...` 下有 brain、brain-home、configure、connect、integrations、onboarding、settings 等页面入口。
- `packages/lib/api.ts:54-444`：`apiSchema` 集中声明 console 使用的 endpoints，包括 connections、settings、documents/batch/list/processing、search、container-tags/profile、projects、analytics、digests 和 MCP migration；`:446-460` 创建 `$fetch`，base URL 为 `NEXT_PUBLIC_BACKEND_URL` 或 `https://api.supermemory.ai`，自动挂 `/v3`、带 `X-App-Source: nova`、cookie credentials 和三次线性重试。
- `packages/lib/auth.ts` 与 `auth.middleware.ts`：认证客户端配置也以 `NEXT_PUBLIC_BACKEND_URL` 或公共 API 为默认值；本地源码显示的是对外部认证/API 的客户端接入，而不是 Better Auth 服务端实现。
- `apps/web/app/api/` 实际搜索只发现 onboarding 的 `account-status`、`extract-content`、`research` 和 `og` route；因此 `CLAUDE.md` 所称的 `/v3/documents` 等主 API 应作为外部服务契约，不应误写成当前 Web app 内部 route。

### 2.4 TypeScript SDK 与框架工具层

- `packages/tools/package.json:1-73`：发布包 `@supermemory/tools`，通过 exports 暴露根入口、`./ai-sdk`、`./openai`、`./mastra`、`./voltagent` 和 `./claude-memory`；依赖 `supermemory` SDK、AI SDK、OpenAI、Zod、LRU cache，测试/构建使用 Vitest、TypeScript、tsdown。
- `packages/tools/src/ai-sdk.ts:14-120,122-372`：提供 `searchMemoriesTool`、`addMemoryTool`、`getProfileTool`、文档 list/delete/add、memory forget，并以 `supermemoryTools()` 聚合。工具内部把 `projectId` 转换为 `sm_project_<id>` 或使用显式 `containerTags`，通过外部 Supermemory SDK 执行请求。
- `packages/tools/src/shared/memory-client.ts:24-64,88-174`：`supermemoryProfileSearch` POST `/v4/profile`；`buildMemoriesText` 获取 profile + query search，按 mode 去重，并把 profile/search 结果格式化为可注入 system prompt 的文本。`:197-240` 从最后一条 user message 提取查询。
- `packages/tools/src/shared/types.ts:4-126`：工具层的主要契约是 profile 的 `static`/`dynamic`、query `searchResults`、`MemoryMode = profile|query|full`、`AddMemoryMode = always|never`、API/base URL/thread/promptTemplate 配置。
- `packages/tools/src/openai/middleware.ts:14-23,90-246,316-387,417-478`：OpenAI middleware 以 container tag 查询 `/v4/profile`，按 mode 把记忆追加到已有 system prompt 或新建 system prompt；`addMemory` 为 always 时保存消息，带 `customId` 的完整消息可走 `/v4/conversations`，否则回退到 `client.add()`。
- `packages/tools/src/mastra/`、`src/vercel/`、`src/voltagent/`：分别提供 Mastra wrapper/processors、Vercel AI SDK middleware 和 VoltAgent middleware/hooks；它们共享 prompt 构建、查询文本抽取、去重和 API client 思路。
- `packages/ai-sdk/src/index.ts:1` 与 `src/tools.ts`：另一个发布包入口重新导出 AI SDK tools；`tools.ts` 的工具集合同样覆盖搜索、添加、profile、文档操作和忘记记忆。

### 2.5 Python SDK 适配层

- `packages/openai-sdk-python/pyproject.toml:5-32` 与 `src/supermemory_openai/__init__.py:1-78`：Python 包 `supermemory-openai-sdk` 依赖 `openai`、`supermemory`、requests，可选 aiohttp；顶层导出 `SupermemoryTools`、工具 schema/执行器、`with_supermemory`、配置与异常。`tools.py:26-171,173-245` 使用 OpenAI function-calling 的 `search_memories`/`add_memory`，按 project/container tags 调用 AsyncSupermemory；`middleware.py:32-41,109-213` 实现 profile/query/full 模式的 system prompt 注入。
- `packages/agent-framework-python/pyproject.toml:5-30` 与 `src/supermemory_agent_framework/__init__.py:1-60`：依赖 `agent-framework-core` 和 `supermemory`，顶层导出 `AgentSupermemory`、tools、chat middleware、context provider。
- `packages/pipecat-sdk-python/pyproject.toml:5-38`、`src/supermemory_pipecat/__init__.py:1-59`、`AGENTS.md:15-72`：依赖 Pipecat、Pydantic、Loguru；核心入口为 `SupermemoryPipecatService`，按仓库局部规则应放在 `context_aggregator.user()` 与 `llm` 之间，支持 profile/query/full、search limit/threshold，并要求 user_id。
- `packages/cartesia-sdk-python/pyproject.toml:5-39` 与 `src/supermemory_cartesia/__init__.py:1-67`：依赖 Cartesia Line、Supermemory、Pydantic、Loguru；顶层入口是 `SupermemoryCartesiaAgent` 和 `MemoryConfig`，用于 voice agent 的记忆增强。

### 2.6 MCP Worker 与 MCP App 层

- `apps/mcp/src/server/index.ts:13-55,161-210,213-270`：Hono Worker 暴露根信息、OAuth protected-resource metadata、OAuth authorization-server metadata、MCP `/`/`/mcp` 路由和短期上传 `/upload/:uploadId`；每次 MCP 请求先读取 Bearer token，经 `validateOAuthToken` 校验后构造 `ActorContext`，调用 `createMcpHandler`，配置 `legacy: "stateless"`、origin allowlist 和错误处理。
- `apps/mcp/src/server/auth/index.ts:30-102`：session 从外部 `${API_URL}/v3/session` 读取；OAuth JWT 通过外部 `${API_URL}/api/auth/jwks` 验签，要求 issuer、audience、`sub` 和 `organization_id`，并提取 scopes、client ID 与过期时间。
- `apps/mcp/src/server/server.ts:49-120`：`createSupermemoryServer()` 对每个请求新建 `McpServer`；以 `actor` 及 API URL 创建 `SupermemoryClient`，接入 `SpaceState`，注册全部 tools、profile/container-tags/widget resources 和 `context` prompt。
- `apps/mcp/src/server/tools/index.ts:18-34`：统一注册 `search_memory`、`listDocuments`、`getDocument`、`listMemories`、`listSpaces`、`whoAmI`、空间切换、graph、add/save/upload 等工具。
- `apps/mcp/src/server/tools/search-memory.ts:11-94`：按有效空间调用 `getProfile(query)` 与 `search()`，返回 profile、相似度结果、total/timing，并输出文本与 structured content。
- `apps/mcp/src/server/tools/add-memory.ts:7-64`：`add_memory` 的 content 上限为 200000，action 为 save/forget；save 调 `SupermemoryClient.createMemory()`，forget 调 `forgetMemory()`。
- `apps/mcp/src/server/client/index.ts:165-205,208-295,297-332,334-455`：`SupermemoryClient` 是 MCP 到外部 API 的适配边界；用外部 `supermemory` SDK 执行 add、forget、`/v4` search/profile/documents，也用 fetch 执行 `/v3/container-tags/list`、`/v3/documents/documents` 和 `/v4/memories/list`，并统一处理超时、401/403/429/5xx。
- `apps/mcp/src/server/space.ts:3-14`：空间状态 DO 名称用 JSON 数组组合 `organizationId,userId`，有效空间优先级为显式 containerTag，其次 Durable Object active tag，最后由 `server.ts` 回退 `sm_project_default`。
- `apps/mcp/src/server/space-state.ts:22-73`：`SpaceState` Durable Object 存 `activeContainerTag`；上传 session 以 `upload:<uuid>` 隔离，存 bearer token 的 SHA-256、过期时间并设置 alarm；`consumeUploadSession()` 在 transaction 中校验/删除，形成一次性消费。
- `apps/mcp/README.md:6-20,45-89,127-145`：确认 MCP 运行模型为每个 HTTP 请求新建 `McpServer`、OAuth 每请求校验、无 protocol Durable Object，空间状态独立保存；列出 model-visible tools、MCP App launchers、app-only tools、resources/prompt 及配置项。

### 2.7 记忆图谱可视化层

- `packages/memory-graph/package.json:1-64`：包 `@supermemory/memory-graph` 是 React 组件，运行时依赖 `d3-force`，peer dependency 为 React/React DOM，使用 Vite/Vitest。
- `packages/memory-graph/src/index.tsx:1-48`：公开 `MemoryGraph`、`GraphCanvas`、`useGraphData`、`ForceSimulation`、`ViewportState`、`SpatialIndex`、`VersionChainIndex` 和图谱类型。
- `packages/memory-graph/src/types.ts:5-104,152-223`：节点分为 document/memory；memory 带 static/latest/forgotten/forgetAfter/version/parent/root/relation；Canvas 属性暴露 hover/click/drag/viewport 等交互。
- `packages/memory-graph/src/canvas/version-chain.ts`（由 `src/index.tsx:13` 导出）：负责用父子 memory ID 组织版本链；测试显示支持跨 document 链、缓存、断裂版本修正、环引用终止和分支按文档顺序选择首个 child。
- `apps/mcp/src/shared/types.ts:179-200`：MCP graph widget 的结构化消息要求文档/记忆统计、截断标记和 `rendered: true`；因此 MCP graph 是 API 数据到 widget 的展示通道，不是存储层。

## 3. 核心数据流

### 3.1 添加文档/记忆

1. SDK/AI tool 或 MCP `add_memory` 接收内容和 container tag。`packages/tools/src/ai-sdk.ts:82-119`、`apps/mcp/src/server/tools/add-memory.ts:45-54` 分别调用外部 SDK 的 add。
2. API 契约把新增输入建模为 `MemoryAddSchema`/`MemoryUpdateSchema`（`packages/validation/api.ts:141-173`），主 API client 默认向 `${BACKEND_URL}/v3/documents` 发请求（`packages/lib/api.ts:213-216,446-460`）。
3. MCP client 的创建路径返回外部响应 ID，并在 MCP 结构化输出中标记为 `queued`（`apps/mcp/src/server/client/index.ts:189-202`）；状态枚举和处理步骤来自契约，不代表本地实现了处理队列。
4. 文档经过提取、切分、embedding、indexing 的状态定义可由 `DocumentStatusEnum` 和 `ProcessingMetadataSchema` 确认；实际 workflow、模型调用、数据库写入和索引实现不在本 checkout 中，不能从本地源码继续展开。

### 3.2 Profile / hybrid search / 上下文注入

1. SDK 或 MCP 接收 query、containerTag 和可选阈值/过滤配置；API search 契约支持 legacy `/v3/search` 与 memory search 的 `/v4` 结构（`packages/validation/api.ts:339-558,560-791`）。
2. 工具层通过 `/v4/profile` 得到 `profile.static` 与 `profile.dynamic`，带 query 时同时拿 `searchResults`（`packages/tools/src/shared/memory-client.ts:24-64`）。
3. 根据 `profile`、`query`、`full` mode 去重和组装文本；存在 system prompt 时追加，否则新建 system message（`packages/tools/src/openai/middleware.ts:158-246`）。
4. MCP `search_memory` 输出 profile、相似度、total、timing（`apps/mcp/src/server/tools/search-memory.ts:35-87`）；`supermemory://profile` resource 和 `context` prompt 则将静态/近期画像限制后格式化（`apps/mcp/src/server/resources/profile.ts:12-82`、`apps/mcp/src/server/prompts/context.ts:15-115`）。

### 3.3 MCP 请求与空间隔离

1. Worker 从 Authorization header 读取 token，调用外部 API 的 JWKS 验证 issuer/audience，并从 JWT 构造 `userId`、`organizationId`、scopes（`apps/mcp/src/server/index.ts:161-187`、`auth/index.ts:55-101`）。
2. `createSupermemoryServer()` 为请求创建 client 和工具依赖，DO 名称由组织+用户组成（`server.ts:49-73`、`space.ts:3-14`）。
3. 工具用显式 `containerTag` 或 active tag；缺省回退 `sm_project_default`（`server.ts:70-73`、`tools/search-memory.ts:32-34`）。
4. 外部 API 返回数据先由 MCP client 的 Zod schema 解析，再转成 text + structured content；错误按请求超时、鉴权、权限、限流和服务端错误分类（`client/index.ts:461-519`）。

### 3.4 文件上传

1. MCP `prepare-file-upload` 通过 `createUploadSession()` 生成 upload UUID、随机 token 和 2 分钟过期时间，DO 中只保留 token hash（`apps/mcp/src/server/server.ts:74-89`、`space-state.ts:36-45`）。
2. widget 把 multipart 请求发到 `/upload/:uploadId`；Worker 原子消费 session，取得 bearer token 后把流转发到外部 `${API_URL}/v3/documents/file`，并透传响应 content type/retry-after（`apps/mcp/src/server/index.ts:213-260`）。
3. 过期 session 由 transaction/alarm 删除；本地没有文件持久化实现。

### 3.5 图谱数据流

外部 API 的 `documents` + `memoryEntries` 响应先由 MCP/web playground 或 web hook 获取，映射为 `GraphApiDocument`/`GraphApiMemory`，再由 `useGraphData` 构造 nodes/edges，交给 `ForceSimulation`、Canvas renderer、hit-test、viewport 和 `VersionChainIndex`。类型、导出和测试能够确认展示逻辑；不能据此推导后端图数据库或索引实现。

## 4. 关键类、函数、数据模型与相对路径

| 领域 | 关键符号 | 相对路径 | 源码职责 |
|---|---|---|---|
| API 契约 | `MemoryEntrySchema`, `DocumentSchema`, `ChunkSchema`, `SpaceSchema` | `packages/validation/schemas.ts` | 记忆、文档、分块、空间及版本/遗忘/embedding 字段的 Zod 模型 |
| API 契约 | `SearchRequestSchema`, `MemorySearchResult`, `apiSchema`, `$fetch` | `packages/validation/api.ts`, `packages/lib/api.ts` | 请求/响应/OpenAPI 结构和 `/v3` fetch 客户端 |
| Web 类型 | `Project`, `ContainerTagListType` | `packages/lib/types.ts` | console 内部的项目/container tag 类型 |
| MCP client | `SupermemoryClient` | `apps/mcp/src/server/client/index.ts` | 外部 SDK + fetch 的统一 API 适配、空间过滤、错误映射 |
| MCP server | `createSupermemoryServer` | `apps/mcp/src/server/server.ts` | 组装 McpServer、工具、资源、prompt、DO 和 actor |
| MCP HTTP | `app`, `handleMcpRequest`, `validateOAuthToken` | `apps/mcp/src/server/index.ts`, `auth/index.ts` | Hono 路由、OAuth 元数据、JWT 校验和 MCP handler |
| MCP state | `SpaceState`, `spaceStateName`, `resolveContainerTag` | `apps/mcp/src/server/space-state.ts`, `space.ts` | active space 与一次性 upload session |
| MCP tools | `registerAllTools`, `search_memory`, `add_memory` | `apps/mcp/src/server/tools/index.ts`, `search-memory.ts`, `add-memory.ts` | 工具 schema、空间解析、外部 API 调用和结构化结果 |
| SDK prompt | `buildMemoriesText`, `supermemoryProfileSearch`, `extractQueryText` | `packages/tools/src/shared/memory-client.ts` | profile/search 拉取、去重、prompt 文本组装 |
| AI SDK tools | `supermemoryTools`, `searchMemoriesTool`, `addMemoryTool` | `packages/tools/src/ai-sdk.ts` | AI SDK tool 对象和文档/记忆操作 |
| OpenAI middleware | `createOpenAIMiddleware`, `addSystemPrompt`, `addMemoryTool` | `packages/tools/src/openai/middleware.ts` | profile/search 注入及 conversation/memory 保存 |
| Python OpenAI | `SupermemoryTools`, `with_supermemory` | `packages/openai-sdk-python/src/supermemory_openai/` | function-calling tools、同步/异步 OpenAI 包装 |
| Python Agent Framework | `AgentSupermemory`, `SupermemoryChatMiddleware`, `SupermemoryContextProvider` | `packages/agent-framework-python/src/supermemory_agent_framework/` | Agent Framework 的 memory tools/middleware/context |
| Python voice | `SupermemoryPipecatService`, `SupermemoryCartesiaAgent` | `packages/pipecat-sdk-python/src/supermemory_pipecat/`, `packages/cartesia-sdk-python/src/supermemory_cartesia/` | 语音 pipeline/agent 的记忆集成 |
| 图谱 | `MemoryGraph`, `ForceSimulation`, `VersionChainIndex` | `packages/memory-graph/src/index.tsx`, `canvas/` | React/Canvas 图谱展示、布局、命中测试和版本链 |

## 5. API / CLI / SDK 入口

### API（外部服务契约）

- 默认 API base：`https://api.supermemory.ai`。
- Web console：`packages/lib/api.ts:446-460` 默认走 `${base}/v3`，契约包含 `documents`、`search`、`connections`、`settings`、`container-tags`、`projects`、`analytics`、`digests` 等。
- Profile/memory API：`packages/tools/src/shared/memory-client.ts:41-48`、`apps/mcp/src/server/client/index.ts:269-325` 使用 `/v4/profile`；MCP 还使用 `/v4/memories/list` 和 `/v3/documents/documents`。
- MCP 文件上传：`apps/mcp/src/server/index.ts:237-246` 转发到 `/v3/documents/file`。
- MCP 公网入口：`https://mcp.supermemory.ai/mcp`，由 `apps/mcp/README.md:24-39` 和 `src/server/index.ts:263-265` 确认。

### CLI / 工程命令

- 根 `package.json:4-11`：`bun run build`、`bun run dev`、`bun run dev:local`、`bun run check-types`、`bun run format-lint`。
- MCP `apps/mcp/package.json:9-20`：`build:widget`、`build`、`dev:app`、`deploy`、`check-types`、`test:unit`、`test:e2e`、`cf-typegen`。
- 本地源码没有发现独立的“记忆数据库 CLI”或完整后端启动入口；README 中提到的 `supermemory local`/`supermemory-server` 属于仓库外发布物或未在当前文件集合中实现的入口，暂不能列为本地源码入口。

### SDK / 框架入口

- TypeScript：`@supermemory/tools` 的 exports（`packages/tools/package.json:49-56`），以及 `@supermemory/ai-sdk` 的根入口（`packages/ai-sdk/package.json:25-30`）。
- Python：四个 `src/<package>/__init__.py` 顶层 re-export，分别对应 OpenAI、Agent Framework、Pipecat、Cartesia。
- MCP：`apps/mcp/src/server/index.ts` 默认导出 Hono app；`apps/mcp/src/server/server.ts` 导出 `createSupermemoryServer`。
- Web：Next app route tree，主入口 `apps/web/app/(app)/page.tsx` 渲染 `AppExperience`。

## 6. 技术栈与依赖

| 层 | 源码确认的技术栈/依赖 |
|---|---|
| Monorepo | Bun `1.3.6`、Node `>=20`、Turbo、TypeScript、Biome（根 `package.json`） |
| Web | Next.js `^16.0.11`、React `^19.2.4`、OpenNext Cloudflare、Wrangler、TanStack Query、Tiptap、Radix UI、Sentry（`apps/web/package.json`） |
| API client/validation | `@better-fetch/fetch`、Zod、zod-openapi、better-auth client helpers；根依赖还列出 Drizzle ORM/Drizzle Kit，但本地未发现其 schema/migration 实现 |
| MCP edge | Cloudflare Workers、Hono、`@modelcontextprotocol/server`/client、OAuth provider、`jose`、Durable Objects、React/Vite widget、PostHog（`apps/mcp/package.json`） |
| TypeScript integrations | `ai`、`@ai-sdk/*`、OpenAI SDK、Mastra/VoltAgent peer/dev deps、Supermemory SDK、Zod、LRU cache、tsdown/Vitest（`packages/tools`, `packages/ai-sdk`） |
| Memory graph | React peer、`d3-force`，Vite/Vitest、Canvas rendering（`packages/memory-graph/package.json`, `src/`） |
| Python integrations | Python `>=3.8.1`（OpenAI 包）或 `>=3.10`（Agent Framework/Pipecat/Cartesia）；OpenAI/Agent Framework/Pipecat/Cartesia、Supermemory SDK、requests/aiohttp、Pydantic、Loguru、pytest/mypy/black 等（各 `pyproject.toml`） |
| Apps/extensions | Browser extension 使用 WXT/React 相关依赖；Raycast extension 和 docs/graph playground 在 `apps/` 中作为独立应用存在，具体构建依赖以各自 manifest 为准 |

## 7. 测试覆盖与验证边界

本次实际读取了以下测试源码，未执行测试命令：

- 契约：`packages/validation/api.test.ts`（阈值、分页、类型拒绝/默认值）。
- TypeScript tools：`packages/tools/src/tools-shared.test.ts`、`tool-operations.test.ts`、`shared/memory-client.test.ts`（container tag、mode 去重、SDK mock、DELETE `/v4/memories`、prompt 注入）。
- AI SDK：`packages/ai-sdk/src/tools.test.ts`（需要 `SUPERMEMORY_API_KEY` 和 `OPENAI_API_KEY`，包含远程 generateText 集成）。
- MCP unit：`apps/mcp/src/server/space.test.ts`、`auth/rbac.test.ts`（DO key/空间优先级和权限矩阵）。
- MCP e2e：`apps/mcp/e2e/memory.test.ts`（OAuth 可用时才运行，覆盖 save→recall、profile、forget、container isolation 和错误参数）。
- 图谱：`packages/memory-graph/src/__tests__/version-chain.test.ts`（版本链、跨文档、缓存、断裂版本、环引用、分支）。

从测试源码可确认测试策略包含纯函数/契约测试、mock 外部 SDK、需要凭据的远程集成测试和可选 OAuth e2e；但本次没有安装依赖或运行任何测试，因此没有声称测试通过。

## 8. 架构判断与未确认项

### 已由源码支持的判断

1. **这是“外部记忆 API + 多客户端/集成层”的 monorepo。** Web `$fetch`、MCP `SupermemoryClient` 和 SDK middleware 都显式以外部 API 为边界。
2. **container tag/space 是全链路隔离主键。** 契约、SDK 配置、MCP active space、OAuth session scope、DO key 和测试 isolation 都围绕它组织。
3. **记忆模型具有版本与关系语义。** `MemoryEntrySchema`、MCP output schema、graph types/tests 均支持 parent/root/version/latest/forgotten 和三类 relation；展示层会构造 version chain，但没有本地事实生成器。
4. **MCP 采用请求级 stateless protocol + 用户/组织级 Durable Object 状态。** README、`index.ts`、`server.ts`、`space-state.ts` 一致支持这一点；DO 只承担 active tag 和短期 upload session，不承担 token 之外的协议消息或记忆数据。
5. **SDK 集成采用“读取 profile/search → 格式化 prompt → 可选保存对话”的适配模式。** `packages/tools` 和 Python OpenAI middleware 均有 profile/query/full 与 add always/never 语义。

### 未确认或不能从本地源码推出的事项

- `api.supermemory.ai` 的数据库表、Drizzle schema、迁移、事务边界、主 API route 实现、内容摄取 workflow、LLM 抽取/冲突解决/遗忘算法、向量索引实现及真实部署拓扑。
- `CLAUDE.md:69-75` 提到的 `IngestContentWorkflow`、Cloudflare AI/Hyperdrive/KV/Workflows 绑定：当前仓库只找到描述，没有找到对应 workflow 源码，不能把它们写成已确认的本地实现。
- `skills/supermemory/references/architecture.md` 中关于 HNSW、具体吞吐/延迟、AES/TLS、合规、规模和“自动关系发现”的陈述没有在本次本地源码中找到可验证实现，本文不把它们当作架构事实。
- README 的“one binary/fully offline/local embeddings”入口，以及 `supermemory` SDK 包本身的实现不在当前仓库源码范围内；本地仅能确认文档和调用边界。
- 根依赖列出 Drizzle ORM/Drizzle Kit，但本 checkout 未发现 `schema.ts`、migration SQL 或数据库配置，无法确认其实际使用位置。

## 9. 本次源码读取清单（代表性与权威入口）

- `README.md`、`README.zh-CN.md`、`CLAUDE.md`、`CONTRIBUTING.md`、`package.json`、`turbo.json`。
- 已有架构参考：`skills/supermemory/references/architecture.md`；MCP 说明：`apps/mcp/README.md`；集成说明：`packages/tools/README.md`。
- 契约：`packages/validation/schemas.ts`、`packages/validation/api.ts`、`packages/lib/api.ts`、`packages/lib/types.ts`。
- MCP：`apps/mcp/src/server/index.ts`、`server.ts`、`auth/index.ts`、`client/index.ts`、`space.ts`、`space-state.ts`、`tools/index.ts`、`tools/search-memory.ts`、`tools/add-memory.ts`、`tools/list-documents.ts`、`tools/list-memories.ts`、`resources/profile.ts`、`prompts/context.ts`、`src/shared/types.ts`、`tools/output-schemas.ts`。
- 集成：`packages/tools/src/shared/memory-client.ts`、`shared/types.ts`、`ai-sdk.ts`、`openai/middleware.ts`；四个 Python 包的 `pyproject.toml` 与 `__init__.py`/核心 tools/middleware/service 入口。
- 图谱：`packages/memory-graph/package.json`、`src/index.tsx`、`src/types.ts`、`src/api-types.ts`、`src/__tests__/version-chain.test.ts`。
- 测试：`packages/validation/api.test.ts`、`packages/tools/src/tools-shared.test.ts`、`tool-operations.test.ts`、`shared/memory-client.test.ts`、`packages/ai-sdk/src/tools.test.ts`、`apps/mcp/src/server/space.test.ts`、`auth/rbac.test.ts`、`apps/mcp/e2e/memory.test.ts`。

本文件已吸收此前 `细探-Supermemory.md` 的源码分析结论；后续只维护本文件，旧细探笔记不再作为独立事实源。

## 10. 后续：通用底座映射与边界裁决

### 10.1 当前核对范围、证据等级与现场限制

当前核对不是把 Supermemory 的产品宣传图复写成平台实现，而是把当前 checkout 中可见的内容入口、外部 API 客户端、MCP Worker、SDK middleware、任务/缓存/外部资源处理方式，映射到“支持库—记忆/检索模块—运行核心—统一网关”四层。必须先保留一个事实边界：本仓库没有 Supermemory 主 API 的路由、数据库、队列、提取器、embedding provider 或索引实现；以下“服务端处理链”只有契约或状态枚举证据时，不能升级为本地实现事实。

当前核对采用以下证据等级：

| 等级 | 含义 | 本项目当前核对证据 |
|---|---|---|
| **L0** | 只有 README、`skills/supermemory/references/*`、注释或声明，没有可定位的本地实现 | `skills/supermemory/references/architecture.md` 中的 HNSW、吞吐、延迟、加密/合规和完整后端图；`CLAUDE.md` 中未在本 checkout 找到的 `IngestContentWorkflow`/绑定 |
| **L1** | 本地源码存在明确调用/状态/资源路径，但未据此证明外部服务内部实现 | `packages/lib/api.ts` 的 `$fetch`、`apps/mcp/src/server/client/index.ts` 的 `SupermemoryClient`、`apps/mcp/src/server/index.ts` 的 Worker/MCP/上传转发、`packages/tools/src/shared/memory-client.ts` 的 profile/search/prompt 链 |
| **L2** | 有测试源码、mock 或测试断言覆盖，尚未在当前核对真实执行 | `packages/tools/src/*test.ts`、`apps/mcp/src/server/space.test.ts`、`auth/rbac.test.ts`、`apps/mcp/e2e/memory.test.ts`、Python middleware tests |
| **L3** | 当前核对对本地目标执行了命令并得到退出码 0；只能证明该命令覆盖的本地事实 | 当前核对以 `git diff --check` 和目标文档检查为准；未把未安装依赖的项目测试包装成通过 |
| **L4** | 真实外部 API/Provider/部署环境的端到端运行证据，且有退出码、测试/请求结果和资源收尾 | 当前核对无 L4；`api.supermemory.ai` 未作为当前核对可用外部依赖验证 |

本轮按用户授权未使用任何 MCP。目标 checkout 自带 `.codegraph/`，现场 `codegraph status`/`sync` 均成功，代码图统计为 674 files、8,531 nodes、21,098 edges（TypeScript 308、TSX 307、Python 42、YAML 12、JavaScript 5）。因此不引用其他项目的上下文、验证或代码图；源码证据只来自目标 checkout 当前文件和 Git 提交。项目根和修改边界仍以本文路径为准，且只修改本文。

### 10.2 真实可见链路与建议的单链路

当前 checkout 的真实链路是“本地集成层 → 外部 Supermemory API”，不是完整的本地记忆系统：

```text
Web / TypeScript SDK tools / Python SDK / MCP client
  → 各自的 fetch、supermemory SDK 或 $fetch
  → https://api.supermemory.ai（或 API_URL/NEXT_PUBLIC_BACKEND_URL）
  → 服务端文档/记忆/检索/连接器处理（本地未提供源码）
```

后续要收敛成底座的目标单链路应是：

```text
调用方 / Web / SDK / MCP
  → 统一网关（HTTP/MCP：鉴权、请求 id、能力路由、参数/结果协议）
  → 运行核心（任务准入、deadline、取消、重试、租约、背压、崩溃回收）
  → 唯一能力注册表
  → 记忆/检索模块（产品流程与语义）
  → 支持库公开能力（HTTP、文件、编码、embedding、索引、连接器等原子能力）
  → 受管 Provider / 外部服务
  → 统一结果、事件、证据与资源释放结论
```

四层不能互相越权：

- **支持库**只拥有可复用、输入输出明确、资源可回收的原子能力和 Provider 契约。HTTP、JSON/Zod、哈希、流式文件、外部连接、向量/数据库驱动、错误映射等落在这里；不拥有“用户画像”“忘记某条记忆”这类产品决策。
- **记忆/检索模块**拥有文档摄取语义、分块/embedding/index 组合、memory entry 版本和关系、profile、检索排序/过滤、container/space 隔离、forget 和连接导入语义；只能通过支持库公开入口取得底层能力。
- **运行核心**拥有任务状态机、队列/背压、并发预算、deadline/cancel、重试政策、Provider 启停/健康/租约、缓存淘汰、异常与崩溃回收、资源对账；不解释产品记忆关系。
- **统一网关**是通信面，不是业务进程和 Provider 管理器。它只解析 HTTP/MCP、校验认证上下文、路由能力、透传/流式返回结构化结果；不持有数据库连接、浏览器/GPU/Provider 对象，不在每个 MCP/SDK 中另起任务队列。

### 10.3 能力命中表：现有实现如何归层

| 能力/资源 | 当前 checkout 的事实入口 | 支持库落点 | 记忆/检索模块落点 | 运行核心落点 | 网关落点 | 当前核对裁决 |
|---|---|---|---|---|---|---|
| 内容摄取（文本/URL/文件） | `packages/lib/api.ts:213-220` 的 `@post/documents` 契约；`apps/mcp/src/server/index.ts:213-260` 将 multipart 流转到 `/v3/documents/file`；`SupermemoryClient.createMemory()` `:189-205` 调 SDK `add` | 内容类型识别、编码/流、大小限制、摘要/制品引用、HTTP 客户端 | 文档/来源/container 归属、摄取策略、处理阶段、文档→chunk→memory 的产品语义 | 入队、并发、deadline、取消、重试、状态事件、失败重放 | `POST /documents`、`POST /upload/:uploadId`、MCP tool 参数与结果 | **吸收边界；后端提取实现待核**。`queued → extracting → chunking → embedding → indexing → done/failed` 只由 `DocumentStatusEnum`/processing schema 证明（L1），不是本地 workflow（L0/L1） |
| 索引与检索 | `SupermemoryClient.search()` `apps/mcp/src/server/client/index.ts:269-295` 使用 `searchMode: "hybrid"`；`supermemoryProfileSearch()` `packages/tools/src/shared/memory-client.ts:24-64` 调 `/v4/profile`；`SearchRequestSchema` `packages/validation/api.ts:339-389` 约束阈值/空间 | embedding/向量库/全文驱动、过滤 DSL、结果解码、分页、相似度数值 | profile static/dynamic、query/full mode、去重、版本/关系展开、排序和 prompt 投影 | 查询 deadline、并发/限流、重试、缓存一致性、降级 | `/v4/search`、`/v4/profile`、MCP `search_memory` | **模块语义吸收；索引 provider 待选型**。HNSW、p95 和关系扩展的后端实现不在本地（L0） |
| 记忆写入与忘记 | `createMemory()` 返回 SDK id 并本地标记 `queued` `:189-202`；`forgetMemory()` 先 exact forget，404 后以相似度 `0.85` 搜索再 forget `:208-265`；AI/OpenAI tools 通过 `client.add()`/`memories.forget()` | HTTP/SDK、幂等键/请求签名、错误与结果解析 | `MemoryEntrySchema` 的 static/dynamic、version、parent/root、`updates|extends|derives`、inference/forgotten；exact/similar forget 产品规则 | 写任务提交、幂等去重、重试和部分失败补偿；不能把后台 fire-and-forget 当成功 | `add_memory`、SDK tools、`POST /documents`/`/v4/memories` 等协议入口 | **产品语义归模块；唯一写 owner 必须是记忆模块服务端**。当前本地只是调用方，不能宣称写库/版本冲突解决已实现 |
| API/SDK 与 prompt 注入 | `$fetch` `packages/lib/api.ts:446-460`；`@supermemory/tools`、`@supermemory/ai-sdk` exports；四个 Python 包；`buildMemoriesText()` `:88-174` 和 OpenAI middleware | 统一 transport、schema、错误、超时/AbortSignal、SDK 版本兼容 | mode/profile/query/full、消息抽取、去重、system prompt 组装、add always/never | 共享 request budget、任务上下文、统一 retry/cancel、日志/trace | Web API facade、MCP JSON-RPC/structured content、OAuth resource metadata | **升级为薄适配层**。SDK 不应各自维护一套 HTTP/错误/任务实现；prompt 语义仍属于模块适配器 |
| 连接器/内容导入任务 | `packages/lib/api.ts:98-189` 有 provider、import 与 sync-runs 契约，状态为 running/completed/failed、trigger 为 event/cron/manual；schema 有 OAuth token/expiry 字段 | provider OAuth、token refresh、分页、限流、文件/网络连接原子能力 | provider→document、container tags、重复/冲突、删除策略和 import 语义 | sync run 的唯一状态 owner、调度、续租、checkpoint、重试、取消、崩溃恢复 | 连接创建/删除/import/status 的 HTTP/MCP 命令 | **任务与 provider 拆开**。当前只有契约和客户端，导入执行器/凭据持久化待核 |
| 任务/后台写入 | Python OpenAI wrapper `middleware.py:352-394` 建 `asyncio.create_task`，`:529-567` wait/cancel，退出时 `:580-615` 最多等 5 秒；MCP 用 `executionCtx.waitUntil` `apps/mcp/src/server/index.ts:191-206` | `AbortSignal`/取消令牌、任务结果/错误信封、序列化和事件 | 何时把对话变成 memory、customId conversation 聚合、写入失败是否影响主对话 | 有界队列、任务状态、lease、心跳、排空、进程/Provider 崩溃回收 | 提交任务、查询状态、取消；请求结束后只提交任务，不持有任务对象 | **新建运行核心原子能力**。禁止每个 SDK/MCP 自己创建无界/不可追踪后台任务 |
| 缓存 | `packages/tools/src/shared/cache.ts:8-73` 的 `MemoryCache` 为进程内 `LRUCache(max:100)`，key 含 container/thread/mode/归一化 message；VoltAgent 在 turn 内复用 | 可复用 LRU/序列化/哈希原子能力 | 只有检索结果/turn prompt 这类产品可缓存对象，定义数据新鲜度与失效条件 | cache owner、容量/TTL/租户隔离、压力淘汰、命中/失效指标、崩溃丢失语义 | 只传 cache policy/lease，不直接读缓存对象 | **升级而非照搬**。现实现没有 TTL、版本/模型/权限摘要、跨进程一致性，不能当持久记忆缓存；外部 profile/embedding cache 只有文档声明（L0） |
| 外部服务/制品/短期上传 | `SpaceState` `:36-73` 用 DO transaction 一次性消费 upload session，alarm 删除；Worker 将 body stream 转发并透传 `Retry-After` `index.ts:229-257`；当前 upload token 只 hash 存储，但 session payload 同时包含 bearerToken | secret 引用、HTTP/TLS、文件流、hash、临时制品、Provider adapter | 文件作为 document source、来源计数、空间归属 | upload/session lease、过期、崩溃后回收、外部连接预算与审计 | OAuth/MCP upload handshake、流式代理、no-store 响应 | **吸收资源治理；安全项待升级**。网关不能长期保存 bearer token；应改为短期不可复用 credential reference |

### 10.4 唯一 owner、资源边界与产品语义分界

#### 唯一 owner 裁决

| 事实/资源 | 唯一写 owner | 其他层允许做什么 | 当前源码状态 |
|---|---|---|---|
| `Document`、处理阶段、处理证据 | 记忆/检索模块的摄取服务 | 网关/SDK 提交命令、读取状态 | 当前只看到 `DocumentSchema`/API 状态；真正写 owner 不在 checkout |
| `Chunk`、embedding、向量/全文索引 | 记忆/检索模块的索引编排器及受管 index provider | 支持库执行原子 upsert/query；调用方只收结果 | schema 有字段，index 实现缺失 |
| `MemoryEntry`、版本链、关系、forget | 记忆/检索模块的 memory writer | 网关/SDK 提交 add/forget，不能直写 DB | schema 与 client 语义存在；服务端写入缺失 |
| container/space 租户与权限 | 记忆/检索模块的空间策略服务 | 网关解析 OAuth actor 和显式 tag；MCP DO 只保存 active tag | `SpaceState` 仅是短期交互状态，不是记忆事实 owner |
| task/run 状态、lease、checkpoint | 运行核心 | 模块提交领域任务，网关读/发取消 | 现有 sync-runs 只是外部 API 契约；Python/MCP 有分散后台任务 |
| HTTP/SDK transport 与错误信封 | 支持库的统一 client/contract owner | SDK/MCP 只做参数适配、结果投影 | 目前 `$fetch`、Supermemory SDK、裸 `fetch` 并存，需收敛 |
| cache entry、容量、TTL、淘汰 | 运行核心缓存服务 | 模块声明 key/新鲜度，不直接拥有全局 cache | 当前 `MemoryCache` 是工具进程内局部 owner，属于待迁移实现 |
| OAuth/外部连接 credential 与 upload artifact | 支持库的 secret/artifact adapter；租约由运行核心持有 | 模块只持有 reference；网关不保存长效秘密 | `ConnectionSchema` 仅字段契约；`SpaceState` 的 upload session 仍暂存 bearerToken |
| analytics/trace/audit 事件 | 运行核心 telemetry owner | 网关/模块发结构化事件 | `waitUntil` PostHog 采集存在，但不是任务/事实 owner |

#### 通用链路与产品语义分界

通用底座只规定：能力 id、参数/返回结构、`request_id`、`contract_version`、`deadline`、`idempotency_key`、`cancel_token`、`resource_budget`、错误码/可重试性和释放证据。它不规定“哪些内容算用户画像”“何时覆盖旧记忆”“updates/extends/derives 如何生成”。

Supermemory 产品模块才规定：

- `containerTag`/space 的隔离和 default project 语义；
- `DocumentStatusEnum` 的处理阶段、文档与 chunk 的关系；
- `MemoryEntrySchema` 的 static/dynamic、version/latest、parent/root、`updates|extends|derives`、inference、forgotten/forgetAfter；
- `/v4/profile` 的 static/dynamic profile 与 query search 的组合；
- `profile`/`query`/`full` prompt 注入、消息是否落 memory、`customId` conversation 聚合；
- exact forget 失败后相似检索再删除的产品策略，以及连接器导入到空间的语义。

二者交界处只允许传不透明的 document/memory/task/lease/artifact id；禁止跨边界传裸数据库连接、游标、Provider 对象、浏览器/GPU 句柄或可变 SDK 内部对象。`containerTag` 可以作为产品过滤字段传给模块，但不能被支持库解释成“自动创建空间”；`MemoryCache` 可以作为支持库原子实现，但 cache key 的业务组成、失效和可接受陈旧度必须由模块声明。

### 10.5 资源生命周期与四种终态

| 资源 | 创建/持有 | 正常完成 | 业务失败 | 超时/主动取消 | 宿主/Provider 崩溃与残留核对 |
|---|---|---|---|---|---|
| HTTP/MCP request、`AbortSignal` | 网关接收请求；MCP 每请求创建 `McpServer`，`legacy: "stateless"` | 返回结构化结果/流；请求对象结束 | 统一错误信封，关闭 response/body | signal 传播至 `getDocuments`、上传 body 或受支持的 SDK 请求；必须让远端任务有明确取消/未知状态 | Worker 请求退出由平台托管；当前没有跨服务 task lease/恢复证据，不能声称写入已完成 |
| 文件上传流/外部 HTTP response | `/upload/:uploadId` consume 一次性 session，直接把 body 转发 `/v3/documents/file` | 返回外部 response body，`Cache-Control: no-store` | 外部非 2xx 原样透传；网络异常返回 502；不得在网关本地落盘 | `c.req.raw.signal` 中止转发；session 已在转发前消费，取消后不能复用，需模块重试/补偿 | DO session 的 alarm/transaction 可清短期状态；外部 multipart 是否已写入由远端状态查询确认，当前无本地证据 |
| `SpaceState` Durable Object 状态 | `activeContainerTag`、upload session 写入 DO；upload token SHA-256 校验 | active tag 保留；upload session 消费后删除 | 无效/过期 token 删除并返回 401 | alarm 到期删除 upload session | DO 存储可持久化，但 bearerToken 随 session payload 保存；必须限制 TTL、权限和 crash 后清理 |
| SDK/API client 与连接 | `SupermemoryClient` 构造 `supermemory` client；外部连接字段由 schema 描述 | 请求返回后对象可继续复用；无本地 close 协议 | `handleError` 将 400/401/402/403/404/429/5xx 和网络错误归类 | MCP 多数请求默认 `AbortSignal.timeout(30_000)`；profile helper 只接受调用方 signal，OpenAI middleware 的裸 profile fetch 无默认 signal | SDK/HTTP 连接池由第三方管理；本仓库无 Provider 进程/连接池残留核对，不能升为 L3/L4 |
| turn `MemoryCache` | 工具进程创建 `LRUCache(max:100)`；键包含空间/线程/mode/消息 | 命中后复用当前核对 prompt，显式 `clear()` 或淘汰 | 缓存错误不应成为记忆事实写入 | 无 per-entry cancel；请求失败不应把半成品写入 cache | 进程崩溃缓存丢失，无磁盘/跨进程残留；没有 TTL、版本和租户权限摘要，必须按易失优化处理 |
| Python background memory task | async OpenAI wrapper `create_task`，集合追踪并注册 done callback | wait/context exit 等待（默认 10 秒；退出 5 秒） | 记录异常且不使主 chat 失败，形成“主请求成功、memory 写失败”的部分成功 | timeout 后 cancel 未完成 task；取消只在协作式 async 边界生效 | 进程崩溃任务直接丢失，无 durable outbox/重放证据；运行核心必须接管并对账 |
| 连接器 OAuth/token、sync run | schema 暴露 token/expiry 和 `running/completed/failed`；执行器缺失 | 由 provider adapter 关闭 response、归还分页/连接资源，checkpoint 后结束 | item 级失败、总任务失败、错误证据与可重试性必须区分 | 取消后保存 checkpoint、撤销/归还 token lease、禁止重复导入 | provider 崩溃由运行核心隔离/重启；当前 checkout 没有进程监督或恢复源码 |
| 文档/记忆/索引/embedding | 只有 schema/API 返回的远端资源 | 由记忆模块确认可检索、版本与来源已提交 | 处理阶段写 `failed` 和 processing error；不把 `queued` 当 done | 任务状态进入 timed_out/cancelled，并由模块决定是否重试或补偿 | DB/向量索引/模型上下文均不在本地；必须以远端状态、幂等查询和索引对账验收 |

### 10.6 失败、超时、取消、崩溃与重复调用矩阵

| 场景 | 当前本地行为/证据 | 底座统一要求 | 风险等级 |
|---|---|---|---|
| 参数非法/空输入/超限 | Zod schemas；MCP `add_memory` 内容上限 `200000`；错误映射 400/422 | 网关在能力入口拒绝；错误包含 field/path、request id；不得进入任务队列 | L1 |
| 401/403/404 | `SupermemoryClient.handleError()` `:480-498` 分类；forget exact 404 会转相似搜索 | 认证/授权失败不可重试；404 只有模块声明可补偿时才允许 fallback | L1 |
| 429/5xx/网络错误 | MCP 归类为限流/服务端错误；Web `$fetch` 3 次、100ms linear retry；裸 SDK/fetch 路径不完全一致 | 由运行核心唯一决定退避、预算和是否重试；写操作必须绑定 idempotency key，不能各 SDK 隐藏重试 | L1 |
| 请求超时 | MCP 默认 `FETCH_TIMEOUT_MS=30_000`；`AbortSignal.timeout` 转为 “timed out”；工具 profile 可传 signal | deadline 必须从网关传到模块/provider；超时后任务必须进入明确终态，不能只抛异常 | L1 |
| 主动取消 | `getDocuments`、profile helper、上传支持 `AbortSignal`；Python background task 有 `cancel()` | 统一 cancel token；协作式取消有检查点，阻塞/原生 Provider 由运行核心杀受管进程组并验零残留 | L1 |
| 后台写入失败/部分成功 | OpenAI async 写入作为 background task，异常只记录 warning/error，不影响主 chat；没有 outbox | 主请求结果必须带 `memory_write_status` 或 task id；失败可查询、重试、去重，不能静默丢 memory | L1 |
| 外部文件转发失败 | Worker catch 返回 502；session 已消费，重复上传需重新握手 | artifact/session 必须有 lease、状态查询和幂等 key；远端已接收但响应丢失要可对账 | L1 |
| Worker/SDK/Provider 崩溃 | DO 短期状态有持久化/过期；LRU 与 asyncio task 为易失；无 Provider supervisor | 运行核心记录 signal/exit、隔离实例、回收进程组/端口/临时目录/句柄，再决定重试 | L1（部分） |
| 重复写入/重复事件 | API 文档建议 `customId`；当前本地 client add 路径未证明 server 端唯一约束；连接 sync 有 event/cron/manual 契约 | `idempotency_key` 必须进入唯一写 owner，事件消费至少一次时用 checkpoint/dedupe | L0/L1 |
| 忘记误删/相似命中 | exact forget 404 后以 0.85 similarity 搜索，且只删除带 `memory` 的结果 | 产品模块必须明确人工确认/审计、候选与实际删除分离；底座只提供 search/delete 原子能力 | L1 |
| 资源二次释放 | `SpaceState.consumeUploadSession()` transaction 删除后单次返回；Python task done/cancel 有分支 | 所有 release/kill/close 幂等；重复 release 返回已释放而非二次释放异常 | L1（局部） |

### 10.7 复用/升级/新建/隔离裁决

| 裁决 | 对 Supermemory 的结论 | 不能做的事 |
|---|---|---|
| **吸收** | `Document`/`Chunk`/`MemoryEntry`/`Space`/processing status 的契约字段可作为记忆模块候选领域模型；profile/search/prompt 注入可作为上层适配流程；MCP upload 的一次性 session、hash 校验、transaction consume、alarm 过期可作为资源治理样例 | 不把 schema 当数据库实现，不把 MCP DO 当记忆存储，不把图谱组件当关系生成器 |
| **升级现有支持库** | 把 `$fetch`、Supermemory SDK、MCP 裸 `fetch`、Python requests/aiohttp 的重复 transport/错误/timeout 收敛到一个公开 client；把 `MemoryCache` 变成有 owner/TTL/版本/租户隔离的有界缓存原子能力 | 不允许每个 SDK、MCP、连接器各自改错误码和 retry |
| **升级现有记忆/检索模块** | 把 container/space、memory version/relations、profile、forget、document→memory 处理阶段保留在模块；统一写 owner 和 search result contract | 不把通用支持库写成“自动推理/自动忘记/用户画像”业务层 |
| **新建运行核心原子能力** | `memory.document.ingest`、`memory.search`、`memory.profile.read`、`memory.entry.write`、`memory.entry.forget`、`connection.sync.run`、`artifact.upload` 的任务提交/租约/deadline/cancel/回收能力 | 不在主进程中无限创建线程/async task，不把 `waitUntil` 当可靠队列 |
| **统一网关装配** | Web、SDK、MCP 都只调用同一能力注册表；MCP 继续保留 OAuth/JSON-RPC 适配，但不得直连第三方或持有 Provider 对象 | 不再新增 `/v3`/`/v4` 各自独立的业务侧 fallback 链，旧 endpoint 只能在网关唯一入口归一化 |
| **隔离/待核** | 外部 API 服务端的 extraction、HNSW、LLM relation discovery、真实 DB/向量存储、连接器执行器和部署拓扑继续作为外部 Provider/待核参考 | 不把 `skills` 文档的性能、安全、规模数字写入底座验收指标 |

### 10.8 装配计划与验收契约

当前核对只产出映射，不修改生产底座。若进入实现阶段，应按以下顺序装配：

1. **先定能力契约**：为 ingest/search/profile/write/forget/sync/upload 分配唯一 `capability_id`、契约版本、输入输出、错误码、幂等、deadline、cancel、资源预算和证据字段；`/v3`、`/v4`、MCP tool 名称只做网关别名。
2. **再定 owner 与状态**：记忆模块拥有文档/记忆/索引事实；运行核心拥有 task/lease/cache/resource 状态；网关拥有 request/auth 上下文；支持库拥有原子 provider adapter。禁止旁路写库。
3. **建立运行核心**：统一队列、背压、重试预算、任务状态 `created → admitted → queued → running → succeeded/failed/cancelled/timed_out/crashed → cleaned`；Provider 任务另有 `draining/released/cleanup_failed`，释放结论必须可读。
4. **迁移客户端**：先让 `SupermemoryClient`、`$fetch` 和 Python client 适配统一支持库，再将 `buildMemoriesText`、OpenAI/AI SDK/Pipecat/Cartesia 的产品适配留在记忆模块适配层；迁移期记录旧入口到能力 id 的唯一映射。
5. **接入资源治理**：大文件用 artifact id/流，不用无界 Base64；外部 token 只以短期 credential reference 流转；cache key 至少含 provider/version/contract/model/config/space/permission 摘要；所有终态做进程、端口、临时文件、连接和句柄对账。
6. **最后做四终态验收**：正常完成、业务失败、超时/取消、Provider/宿主崩溃各至少一条真实测试；写入要验证幂等与部分成功对账，检索要验证空间隔离与陈旧缓存，upload 要验证 session 一次性消费和过期清理。

最小验收返回契约：

```text
success + value
+ request_id + capability_id + contract_version
+ task_id/lease_id（异步时）
+ error_code + retryable + deadline_state
+ evidence（状态/外部响应/重试/清理）
+ resource_release（released / cached / cleanup_failed）
```

当前核对的最终判断是：**Supermemory 的可复用价值主要在记忆/检索产品契约、profile/search/memory middleware 适配和一次性 MCP 资源会话模式；它不是当前可直接吸收为支持库或运行核心的完整后端。** 生产底座应吸收契约与边界，升级 transport/cache/task/resource 原子能力，保留产品语义在记忆/检索模块，并把外部 API 内核、未证实性能指标和分散后台任务隔离为待核项。

## 11. 后续后续风险与验证缺口

- 目标仓库 `.codegraph/` 已存在；本轮 `codegraph status`/`sync` 成功，统计为 674 files、8,531 nodes、21,098 edges，仅用于定位源码，不替代源码证据。
- 本轮严格未使用 MCP，因此没有 MCP work_id、反馈或验证入账；验证以 shell、git、CodeGraph 和源码静态检查为准。
- 当前核对未安装 Bun/Python 依赖、未启动 Worker、未访问 `api.supermemory.ai`、未执行 OAuth/MCP e2e；因此 L4、后端任务恢复、索引一致性、真实 token refresh、Provider 崩溃回收均未验证。
- `MemoryCache` 没有 TTL/版本/权限摘要；OpenAI middleware 的 profile `fetch` 路径没有统一 timeout/signal；后台写入失败不会影响主 chat，可能造成无提示的数据缺口。
- upload session 在 DO 中 hash upload token，但 session payload 还包含 bearerToken；需要在生产底座改为短期 credential reference，并审计日志/权限/过期/崩溃路径。
- 现有正式文档声称已吸收 `细探-Supermemory.md`；在目标项目根及其所属 `02_长期记忆与记忆操作系统` 目录现场未找到该旧细探文件，当前核对未删除任何旧细探，也未把缺失文件包装成已复核证据。
- 远端 `/v3`/`/v4` 服务端的真实事务、队列、模型、索引、webhook/status callback 和删除语义仍需 L4 复核；不能因为返回 `queued` 或 schema 有 `done` 就声称已完成摄取。

## 12. 本轮源码证据补充（2026-08-22）

### 12.1 Git、目录与代码图身份

| 项目 | 现场证据 | 结论 |
|---|---|---|
| 源码根 | `~/Documents/Agent/github 源码参考/05_个人自我蒸馏参考/02_长期记忆与记忆操作系统/Supermemory` | 目标 checkout 与平台研究文档分离 |
| 远程同步 | `git fetch origin --prune`、`git pull --ff-only` | 返回 `Already up to date` |
| 提交 | `git rev-parse HEAD` | `34876664810a43a55954a0a83571662a3bd333b8` |
| 代码图 | `codegraph status`、`codegraph sync` | 674 files / 8,531 nodes / 21,098 edges，索引最新 |
| 文档唯一性 | `find .../Supermemory -maxdepth 1 -type f` | 平台文档目录仅保留 `ARCHITECTURE.md` |
| 修改边界 | 平台仓库定向 `git diff -- .../Supermemory/ARCHITECTURE.md` | 不修改源码 checkout |

### 12.2 Web 控制台请求边界

`packages/lib/api.ts:54-444` 的 `apiSchema` 是控制台请求契约，声明 connections、settings、documents、batch、search、profile、container-tags、projects、analytics、digests 与 MCP migration 等 endpoint。`packages/lib/api.ts:446-460` 的 `$fetch` 用 `NEXT_PUBLIC_BACKEND_URL` 或 `https://api.supermemory.ai` 作为 base，追加 `/v3`，携带 `X-App-Source: nova`、cookie credentials，并对请求做 3 次线性重试。它是浏览器客户端，不是后端路由或数据库写入器。

`apps/web/app/(app)/page.tsx:1-5` 将根应用交给 `AppExperience`；页面目录包含 brain、connect、configure、integrations、onboarding 和 settings。对 `apps/web/app/api/` 的现场文件盘点只发现 account-status、extract-content、research、og 等局部 Next routes；因此 `/v3/documents`、`/v4/profile` 等仍应标记为外部 API，而不能写成 Web 内部实现。

### 12.3 MCP Worker 请求生命周期

`apps/mcp/src/server/index.ts:161-210` 先读取 Bearer token、调用 `validateOAuthToken`、构造 actor，再为每次请求创建 MCP handler；`legacy: "stateless"` 表明协议层不把 McpServer 当长期会话对象。`apps/mcp/src/server/server.ts:49-120` 每请求创建 `McpServer`、`SupermemoryClient` 和工具注册器，注册 tools、resources、prompts 与 widget。

`apps/mcp/src/server/auth/index.ts:55-101` 从外部 `${API_URL}/api/auth/jwks` 验证 JWT 的 issuer、audience、`sub`、`organization_id`、scope 和过期时间；`auth/index.ts:30-52` 还从 `${API_URL}/v3/session` 查询会话。认证密钥与用户会话均由外部服务提供，本地 Worker 不拥有用户数据库。

### 12.4 MCP 工具与外部 API 适配

`apps/mcp/src/server/tools/index.ts:18-34` 注册 search_memory、list/get documents、list memories、list spaces、whoAmI、space switch、graph、add/save/upload 工具。`search-memory.ts:11-94` 先解析有效 container tag，再组合 profile 与 hybrid search，输出 text 和 structured content；`add-memory.ts:7-64` 将 save/forget 分派到 `createMemory`/`forgetMemory`，内容上限为 200000 字符。

`apps/mcp/src/server/client/index.ts:165-205` 的 `createMemory` 通过外部 SDK add 并把响应映射为 queued；`:208-295` 的 forget/search 通过 SDK 与 `/v4` fetch 实现；`:297-455` 处理 documents、container tags 和 memories list。`:461-519` 将 400/401/403/404/429/5xx、网络异常和超时映射为统一 MCP 错误文本。这里没有本地 SQL、队列、embedding 或索引调用。

### 12.5 空间状态与上传资源

`apps/mcp/src/server/space.ts:3-14` 用 `organizationId,userId` 生成 Durable Object 名称，显式 containerTag 优先于 DO active tag，缺省回退 `sm_project_default`。这是请求路由状态，不是记忆事实存储。

`apps/mcp/src/server/space-state.ts:22-73` 将 activeContainerTag 与 `upload:<uuid>` 会话存入 DO；upload token 仅以 SHA-256 保存，过期时间为 2 分钟，alarm 清除过期状态，`consumeUploadSession()` 在 transaction 内校验并删除，形成一次性消费。注意 payload 仍带 bearerToken，平台迁移时应改为短期 credential reference。

`apps/mcp/src/server/index.ts:213-260` 将 multipart body 直接流式转发到外部 `/v3/documents/file`，透传 content type 与 retry-after，响应设置 `Cache-Control: no-store`。Worker 不落盘文件；外部是否已入库必须通过远端状态或幂等查询确认。

### 12.6 TypeScript 工具调用链

`packages/tools/src/ai-sdk.ts:14-120` 暴露 searchMemoriesTool、addMemoryTool、getProfileTool、documents list/delete/add 与 memory forget；`:122-372` 聚合为 `supermemoryTools()`。工具把 projectId 转换为 `sm_project_<id>`，或接受显式 containerTags，再调用外部 `supermemory` SDK。

`packages/tools/src/shared/memory-client.ts:24-64` 的 `supermemoryProfileSearch` 请求 `/v4/profile`；`:88-174` 的 `buildMemoriesText` 合并 static/dynamic profile 与 query search、去重并按 mode 生成 prompt 文本；`:197-240` 从最后一条 user message 提取 query。`packages/tools/src/openai/middleware.ts:158-246` 把结果追加到既有 system message 或新建 system message，`:316-387` 在 addMemory=always 时保存消息。

`packages/tools/src/shared/cache.ts:8-73` 使用进程内 `LRUCache(max:100)`，key 包含 container、thread、mode 与归一化消息。该缓存没有持久化、TTL、模型/权限摘要，进程结束即丢失，只能作为易失检索优化。

### 12.7 Python 适配器与后台任务

`packages/openai-sdk-python/src/supermemory_openai/tools.py:26-245` 将 search_memories/add_memory 映射为 OpenAI function tools；`middleware.py:109-213` 注入 profile/query/full context。`:352-394` 使用 `asyncio.create_task` 异步保存，`:529-567` 等待/取消，`:580-615` 退出时有限等待。进程崩溃会丢失未完成任务，当前没有 durable outbox 或恢复扫描。

`packages/agent-framework-python/src/supermemory_agent_framework/` 提供 tools、chat middleware、context provider；`packages/pipecat-sdk-python/src/supermemory_pipecat/` 将检索接入 user context 与 LLM 之间；`packages/cartesia-sdk-python/src/supermemory_cartesia/` 包装 voice agent。四个适配器均调用外部 Supermemory SDK，不拥有记忆数据库。

### 12.8 契约字段与后端缺口

`packages/validation/schemas.ts:3-59` 的 Metadata/DocumentStatus 定义 queued、extracting、chunking、embedding、indexing、done、failed；`:61-124` 的 Document/Chunk 字段描述内容、token、chunk、embedding 与 processing metadata；`:239-294` 的 MemoryEntry 描述 version、isLatest、parent/root、updates/extends/derives、inference、forgotten、forgetAfter 与 embedding。它们是前后端共享 schema，不是本地 ORM schema。

本 checkout 当前未发现主 API 的数据库迁移、ORM 表定义、embedding provider、全文/向量索引、内容抽取 worker、连接器执行器或 webhook 状态消费者。根依赖中的 Drizzle 不能单独证明数据库实现存在；`queued` 只能表示外部服务已接受或客户端映射，不等于处理完成。

### 12.9 测试与部署证据

仓库测试入口分布在 `packages/validation/api.test.ts`、`packages/tools/src/*test.ts`、`packages/ai-sdk/src/tools.test.ts`、`apps/mcp/src/server/space.test.ts`、`apps/mcp/src/server/auth/rbac.test.ts`、`apps/mcp/e2e/memory.test.ts` 与 `packages/memory-graph/src/__tests__/version-chain.test.ts`。测试源码覆盖 schema、工具参数、RBAC、空间状态、图谱版本链和 MCP e2e 定义；本轮未安装 Bun/Node 依赖，未执行测试命令，不能宣称通过。

根 `package.json:4-11` 通过 Turbo/Bun 编排 build、dev、check-types、format-lint；`apps/mcp/package.json:9-20` 提供 widget build、Worker build、Cloudflare deploy、unit/e2e test。部署目标和 OpenNext/Cloudflare 配置属于边缘/控制台运行时，不能推断外部 API 后端的部署拓扑。

### 12.10 本轮验证与剩余风险

本轮执行：`git fetch origin --prune`、`git pull --ff-only`、`codegraph status`、`codegraph sync`、平台文档 `wc -l` 与 `git diff --check`。源码 checkout 未改动；平台唯一文档达到 500 行以上。未执行 Bun 安装、TypeScript 构建、Vitest、Python 测试、Cloudflare Worker、OAuth/JWKS、MCP 客户端、真实 API、上传中断、429/5xx 重试、缓存并发、连接器同步、崩溃恢复和远端删除对账。

本轮严格未使用 MCP；CodeGraph 仅作为目标源码定位工具。所有关于 API 内部队列、数据库、embedding、索引、连接器 worker、服务端鉴权持久化和性能的结论均保留为外部边界或待验证项，不升级为本地实现事实。
