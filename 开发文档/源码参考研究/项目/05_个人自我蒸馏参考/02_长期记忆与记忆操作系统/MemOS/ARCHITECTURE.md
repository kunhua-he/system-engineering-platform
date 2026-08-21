# MemOS 架构文档

> 本文是仓库根目录唯一正式架构文档。内容依据当前工作树 `7f80d13` 的实际源码、配置、测试与项目说明整理；`细探-MemOS.md` 仅作为施工材料，不是本文件的事实源。
>
> 本轮只新增本文件；未修改源码、依赖、测试、配置，未安装依赖、启动服务、生成构建产物或提交 Git。

## 1. 项目定位

**MemOS / MemoryOS** 是面向 LLM 与 AI Agent 的记忆操作系统：对外提供记忆的添加、检索、对话、反馈修正、用户/知识库管理和异步调度；对内把记忆容器、文本/激活/参数化记忆、模型与存储适配器编排成可配置系统。

当前仓库实际包含两条实现线，不能合并描述为一个共享运行时：

1. **Python MemOS 2.0 Stardust**：`src/memos/`，发行包名 `MemoryOS`、导入包名 `memos`。它是主 Python 库与 FastAPI 服务，采用 MemCube 聚合多种记忆，使用向量库/图数据库/用户数据库，并可通过 MemScheduler 异步执行记忆任务。
2. **TypeScript `memos-local-plugin` V7**：`apps/memos-local-plugin/`，面向 OpenClaw、Hermes Agent、DeepSeek Harness 的本地优先插件。它以 SQLite 文件保存 L1 trace、L2 policy、L3 world model、Skill、Episode 与反馈，提供三层检索、奖励反向传播、决策修复和 Skill 演化。OpenClaw 与 DeepSeek Harness 进程内调用 TypeScript 核心；Hermes 通过 Python → stdio JSON-RPC → Node bridge 调用同一核心。

仓库还保留 `packages/adapter-base/`、`packages/memos-schema/`、`packages/memos-core/` 等早期/兼容性包，以及多个 `apps/` 独立应用。它们不是 Python MOS 的内部层，也不能在没有进一步运行验证的情况下视为当前本地插件的唯一入口。

许可证与发布元数据：Apache-2.0、Python 发行版本 `2.0.30`（`pyproject.toml`）；本地插件 `package.json` 当前版本为 `2.0.16-beta.1` 且许可证字段为 MIT。两条实现线的许可证字段存在差异，复用代码时应分别遵守。

## 2. 总体文本流程图

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│                       Agent / 应用 / 用户                                     │
│ OpenClaw · Hermes · DeepSeek Harness · Python SDK · REST 客户端               │
└───────────────┬───────────────────────────────┬──────────────────────────────┘
                │                               │
                │ Python REST / SDK             │ 本地插件生命周期 / 工具 / Hook
                ▼                               ▼
┌───────────────────────────┐       ┌──────────────────────────────────────────┐
│ Python FastAPI             │       │ TS adapters                              │
│ memos.api.server_api:app  │       │ openclaw / deepseek-harness              │
│ /product/* + /health      │       │ hermes Python provider → bridge.cts      │
└──────────────┬────────────┘       └──────────────────┬───────────────────────┘
               │                                       │
               ▼                                       ▼
┌───────────────────────────┐       ┌──────────────────────────────────────────┐
│ Python MOS 编排            │       │ agent-contract/                           │
│ MOS → MOSCore              │       │ MemoryCore · DTO · events · errors        │
│ 用户/会话/权限/Cube路由    │       │ JSON-RPC method registry                  │
└──────────────┬────────────┘       └──────────────────┬───────────────────────┘
               │                                       │
               ├──────────────┐                        ▼
               │              │       ┌──────────────────────────────────────────┐
               ▼              ▼       │ TS core/pipeline                          │
┌────────────────────┐ ┌────────────┐  │ session/episode → retrieval               │
│ MemCube             │ │ Scheduler  │  │ capture → reward → L2 → L3 → Skill         │
│ GeneralMemCube      │ │ Redis/本地 │  │ feedback/decision repair                  │
└─────────┬──────────┘ └─────┬──────┘  └───────────────┬──────────────────────────┘
          │                  │                         │
          ▼                  ▼                         ▼
┌────────────────────┐ ┌────────────┐       ┌──────────────────────────────────┐
│ MemoryFactory       │ │ label      │       │ SQLite + migrations + repositories │
│ text / activation / │ │ → handler  │       │ FTS5 + float32 BLOB vectors       │
│ preference / LoRA   │ │ → queue    │       └──────────────────┬───────────────┘
└──────┬─────────────┘ └─────┬──────┘                          │
       │                     │                                 ▼
       ▼                     ▼                    ┌──────────────────────────────┐
┌───────────────┐  ┌────────────────┐             │ TS HTTP/SSE server + Viewer   │
│ LLM/embedder  │  │ graph/vector   │             │ /api/v1/* · /api/v1/events    │
│ factories     │  │ DB/user DB     │             └──────────────────────────────┘
└──────┬────────┘  └────────────────┘
       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ Python 记忆数据：TextualMemoryItem / metadata / 来源与版本历史；             │
│ TS 记忆数据：Session → Episode → Trace(L1) → Policy(L2) → World(L3)/Skill     │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 本地插件一轮核心数据流

```text
用户 turn
  → adapter.onTurnStart / bridge turn.start
  → session relation + intent + episode 路由
  → Tier 1 Skill + Tier 2 Trace/Episode + Tier 3 World Model
  → RRF 融合 + MMR 去重 + 时间/相对阈值 + prompt 注入
  → Agent 执行与工具调用
  → adapter.onTurnEnd / bridge turn.end
  → episode.finalized
  → capture: step 提取 → normalize → reflection → α → embedding → traces(V=0)
  → reward: R_human → V_t = α_t·R + (1-α_t)·γ·V_(t+1) → priority
  → reward.updated → L2 policy induction/gain
  → L2 induced → L3 聚类/抽象/合并
  → L2/L3/reward 事件 → Skill eligibility/evidence/crystallize/verify/package
  → SQLite rows + CoreEvent + viewer/SSE
```

### Python 典型数据流

```text
messages / memory_content / doc_path
  → MOSCore.add
  → (可选) MemReader：parser → chunker → LLM 提取
  → TextualMemoryItem
  → text memory add（embedder → vector DB）
  → async 模式：ScheduleMessageItem → Redis Stream / Local Queue
  → label handler：add / mem_read / pref_add / mem_update 等
  → search：cube 权限过滤 → textual/preference 并行查询 → MOSSearchResult
  → chat：search 记忆 → system prompt → chat LLM → answer 任务入队
```

## 3. 真实分层与目录地图

### 3.1 仓库边界

```text
MemOS/
├── src/memos/                 # Python 主库、MOS、记忆实现、服务、SDK
├── tests/                     # Python pytest
├── apps/memos-local-plugin/   # 当前本地插件：TS V7 + Hermes Python adapter
├── packages/                  # TS 早期/兼容性包（需与 V7 区分）
├── apps/                     # OpenWork、OpenClaw Cloud 等独立应用
├── examples/                  # 配置、MemCube、MCP 等示例
├── docs/                      # Python 服务文档目录；当前未发现 docs/openapi.json
├── evaluation/                # 评测脚本/说明
├── deploy/ docker/            # 部署与容器材料
├── scripts/                   # 辅助脚本
├── pyproject.toml / uv.lock / poetry.lock
└── ARCHITECTURE.md            # 本文，根目录唯一正式架构文档
```

### 3.2 Python 主库分层

| 层 | 真实路径 | 职责 |
|---|---|---|
| 公共出口 | `src/memos/__init__.py` | 导出 `MOS`、`GeneralMemCube`、`MOSConfig`、`GeneralMemCubeConfig`、Scheduler 工厂等；版本为 `2.0.30`。 |
| 顶层编排 | `src/memos/mem_os/main.py`、`mem_os/core.py` | `MOS` 负责自动配置与 PRO/CoT 入口；`MOSCore` 管理用户、Cube、聊天历史、记忆增删改查、搜索、聊天和 Scheduler。 |
| 配置契约 | `src/memos/configs/` | Pydantic v2 配置与 `*ConfigFactory`：MOS、MemCube、Memory、LLM、Embedder、Vector DB、Graph DB、Reader、Scheduler 等。 |
| MemCube 容器 | `src/memos/mem_cube/base.py`、`mem_cube/general.py` | `GeneralMemCube` 按配置装配 text/activation/parametric/preference 四个槽位，负责目录加载、转储、schema 校验和远程仓库初始化。 |
| 记忆抽象 | `src/memos/memories/base.py`、`memories/textual/base.py`、`memories/activation/`、`memories/parametric/` | BaseMemory/BaseTextMemory/BaseActMemory/BaseParaMemory 定义 load/dump、extract/add/search/get/update/delete 等契约。 |
| 文本记忆实现 | `src/memos/memories/textual/` | `NaiveTextMemory`、`GeneralTextMemory`、`TreeTextMemory`、`SimpleTreeTextMemory`、Preference 记忆；通用文本实现将文本 embedding 后写入向量库。 |
| 输入摄取 | `src/memos/mem_reader/`、`parsers/`、`chunkers/` | 多模态/消息/文档读取，文件解析、分块、结构化记忆提取；工厂选择具体 reader/parser/chunker。 |
| 检索与排序 | `src/memos/search/`、`memories/textual/tree_text_memory/retrieve/`、`reranker/` | 普通/树状/偏好检索、过滤、重排、网络检索和查询服务。 |
| Provider 适配 | `src/memos/llms/`、`embedders/`、`vec_dbs/`、`graph_dbs/` | 每类基本遵循 `base.py` 抽象类 + `factory.py` 注册表 + `configs/<category>.py` 配置。 |
| 异步调度 | `src/memos/mem_scheduler/` | Scheduler、队列、消费者/分发器、任务 handler、monitor、ORM/Redis/RabbitMQ 支撑。 |
| 用户与租户 | `src/memos/mem_user/` | SQLite/MySQL/Redis 持久用户管理、Cube 所有权、授权与共享。 |
| 反馈/梦境/插件 | `src/memos/mem_feedback/`、`src/memos/dream/`、`src/memos/plugins/` | 反馈修正提示词链、梦境/巩固流水线、插件发现/钩子/组件启动。 |
| HTTP/API | `src/memos/api/` | FastAPI app、路由、handlers、Pydantic 产品模型、请求上下文、中间件、异常、MCP/生命周期。 |
| 观测与通用支撑 | `src/memos/log.py`、`context/`、`memos_tools/`、`types/`、`exceptions.py` | 日志、trace/user 上下文、线程安全容器、通用类型与语义异常。 |

### 3.3 TypeScript 本地插件分层

| 层 | 真实路径 | 职责 |
|---|---|---|
| 宿主适配层 | `apps/memos-local-plugin/adapters/openclaw/`、`adapters/deepseek-harness/`、`adapters/hermes/memos_provider/` | 把宿主 hook、工具、会话、配置和 LLM 回调转换成统一 Core 调用；OpenClaw/DSH 进程内，Hermes 走 Node bridge。 |
| 公共契约 | `apps/memos-local-plugin/agent-contract/` | `MemoryCore`、DTO、事件、错误、日志记录、JSON-RPC 方法名；跨语言边界的稳定协议。 |
| 核心门面/编排 | `core/pipeline/memory-core.ts`、`core/pipeline/orchestrator.ts`、`core/pipeline/index.ts` | `bootstrapMemoryCoreFull` 打开数据库、跑迁移、装配 provider 与 pipeline；`createMemoryCore` 暴露生命周期、turn、反馈、查询、导入导出和观测接口；orchestrator 管事件总线与 session/episode。 |
| 生命周期与演化算法 | `core/session/`、`core/episode/`、`core/capture/`、`core/reward/`、`core/memory/l2/`、`core/memory/l3/`、`core/skill/`、`core/feedback/` | Session/Episode 路由；L1 捕获；奖励评分/反传；L2 policy；L3 world；Skill 结晶；反馈/decision repair。 |
| 检索 | `core/retrieval/` | Tier 1 skill、Tier 2 trace/episode、Tier 3 world model；`ranker.ts` 负责多路分数融合、MMR 和时间/阈值处理；`injector.ts` 形成注入上下文。 |
| 基础设施 | `core/storage/`、`core/embedding/`、`core/llm/`、`core/logger/`、`core/config/`、`core/hub/` | SQLite/迁移/repository；embedding provider/cache；LLM provider/host bridge；结构化日志；YAML 配置/运行目录；可选团队 Hub。 |
| 本地存储 | `core/storage/connection.ts`、`migrator.ts`、`repos/`、`migrations/` | better-sqlite3、WAL、foreign keys、事务、FTS5 trigram、float32 BLOB 向量与按实体拆分的 repository。 |
| 服务与观测 | `server/`、`viewer/`、`bridge.cts`、`bridge/` | Node 标准库 HTTP/SSE API、Viewer 静态资源、JSON-RPC stdio/TCP bridge、事件/日志转发。 |

### 3.4 早期/兼容性 TS 包

`packages/memos-core/src/index.ts` 仍导出早期 `initPlugin`、`SqliteStore`、`IngestWorker`、`RecallEngine` 等设计；但当前 `packages/memos-core/src/` 的实际文件清单与这些 import（如 `storage/sqlite`、`ingest/worker`、`recall/engine`）不完全对应，且 `packages/` 下未发现独立 `package.json`。因此本文件把它列为**历史/兼容性材料**，不把它当作当前 V7 运行入口。`packages/adapter-base` 与 `packages/memos-schema` 仍提供较稳定的早期跨适配器类型意图。

## 4. 核心数据模型

### 4.1 Python 模型

- **`MOSConfig`**：`src/memos/configs/mem_os.py`。核心字段包括 `user_id`、`session_id`、`chat_model`、`mem_reader`、`mem_scheduler`、`user_manager`、`top_k`，以及 textual/activation/parametric/preference/scheduler 开关。
- **`GeneralMemCubeConfig`**：`src/memos/configs/mem_cube.py`。以 `cube_id`、`user_id` 和四个 `MemoryConfigFactory` 槽位描述一个 Cube，并校验各槽位允许的 backend。
- **`MemoryConfigFactory`**：`src/memos/configs/memory.py`。用 `backend` + `config` 将配置映射到 `NaiveTextMemoryConfig`、`GeneralTextMemoryConfig`、`TreeTextMemoryConfig`、`PreferenceTextMemoryConfig`、`KVCacheMemoryConfig`、`LoRAMemoryConfig` 等。
- **`TextualMemoryItem`**：`src/memos/memories/textual/item.py`。顶层为 UUID `id`、`memory` 文本和 metadata。metadata 有基础 `TextualMemoryMetadata`，树记忆扩展 `TreeNodeTextualMemoryMetadata`（memory_type、sources、embedding、usage、background、file_ids），搜索扩展 relativity，偏好扩展 preference/dialog/embedding 等。
- **来源与版本**：`SourceMessage` 保存 chat/doc/file 等来源定位；`ArchivedTextualMemory` 与 metadata 的 `history`、`version`、`status`、`evolve_to` 支持历史/冲突/归档语义。
- **`ScheduleMessageItem`**：`src/memos/mem_scheduler/schemas/message_schemas.py`。任务消息包含 `item_id`、`user_id`、`mem_cube_id`、`trace_id`、`session_id`、`label`、JSON 字符串 `content`、时间、`task_id`、`info`、chat_history/user_context；Redis 序列化时显式转换列表/字典。
- **API 请求/响应**：`src/memos/api/product_models.py`。`BaseResponse[T]` 是 `{code,message,data}` 包络；`APISearchRequest`、`APIADDRequest`、`ChatRequest`、`APIFeedbackRequest`、Cube 请求以及分页/任务状态模型构成 REST 契约，并保留 `mem_cube_id` 等兼容字段的归一化逻辑。

### 4.2 TypeScript V7 模型与 SQLite 表

`agent-contract/dto.ts` 与 `core/types.ts` 是跨模块 DTO/内部 Row 类型；SQLite 初始 schema 的权威实现为 `core/storage/migrations/001-initial.sql`，后续为 `002-...` 至当前实际迁移文件。

| 概念 | 关键字段/表 | 来源与用途 |
|---|---|---|
| Session | `sessions`：id、agent、owner namespace、started/last_seen、meta | `core/session/`；宿主会话容器。 |
| Episode | `episodes`：session_id、trace_ids、r_task、open/closed、meta | 一段任务/主题；关系分类与边界关闭后触发演化链。 |
| L1 Trace | `traces`：user_text、agent_text、tool_calls、reflection、value、alpha、r_human、priority、tags、error signatures、`vec_summary`/`vec_action`、turn_id | 一步行动/观察/反思的持久化记录。 |
| L2 Policy | `policies`：title、trigger、procedure、verification、boundary、support、gain、candidate/active/archived、evidence ids、decision guidance、vec | 跨 Episode 归纳的可复用策略。 `l2_candidate_pool` 保存签名桶与候选证据。 |
| L3 World Model | `world_model`：title、body、`structure_json`（environment/inference/constraints）、domain tags、confidence、policy ids、status、vec | 从 L2 聚类/抽象而来的环境知识。 |
| Skill | `skills`：name、invocation_guide、procedure、eta、support、gain、trial 计数、source policy/world、evidence anchors、version、status、vec | 从合格 L2 结晶的可调用能力。 |
| Feedback | `feedback`：episode/trace、explicit/implicit channel、polarity、magnitude、rationale、raw JSON | 任务级/用户级反馈信号。 |
| Decision repair | `decision_repairs`：context_hash、preference、anti_pattern、高/低价值 trace ids、validated | 把失败模式转成下一轮的决策指导。 |
| 观测 | `audit_events`、`api_logs`、`kv`、FTS5 虚表/触发器 | 审计、Viewer 日志、运行小状态以及 traces/policies/skills/world 的关键词检索。 |

SQLite 约定：TEXT id、毫秒 epoch 时间、JSON TEXT + `json_valid` check、embedding 为 little-endian float32 BLOB；`connection.ts` 默认 WAL、foreign keys、busy timeout 和 `synchronous=NORMAL`。`001-initial.sql` 明确把 schema migrations、sessions/episodes/traces/policies/world/skills/feedback/audit/api_logs/kv/FTS5 等纳入初始 schema。

## 5. 关键类、函数与调用边界

### 5.1 Python

| 符号 | 相对路径 | 作用 |
|---|---|---|
| `MOS` / `MOS.simple()` | `src/memos/mem_os/main.py` | 顶层用户入口；从环境读取 OpenAI 配置与文本记忆类型，调用默认配置并自动注册 Cube。 |
| `MOSCore` | `src/memos/mem_os/core.py` | 初始化 LLM/Reader/UserManager/Scheduler；实现 `chat`、`search`、`add`、`get/get_all`、`update/delete`、Cube/user 管理。 |
| `GeneralMemCube` | `src/memos/mem_cube/general.py` | 依据四槽配置通过 `MemoryFactory.from_config` 装配记忆，提供 `init_from_dir`、`init_from_remote_repo`、`load`、`dump`。 |
| `MemoryFactory.from_config` | `src/memos/memories/factory.py` | backend → 具体记忆类注册表；当前实际注册 naive/general/tree/simple-tree/preference/KV/vLLM-KV/LoRA。 |
| `BaseTextMemory` / `GeneralTextMemory` | `src/memos/memories/textual/base.py`、`textual/general.py` | 文本记忆契约；通用实现负责 LLM 提取、embed、vector DB add/search/get/update/delete/load/dump。 |
| `SchedulerFactory.from_config` / `GeneralScheduler` | `src/memos/mem_scheduler/scheduler_factory.py`、`general_scheduler.py` | scheduler backend 装配；GeneralScheduler 建立 handler services/context/registry。 |
| `ScheduleMessageItem` | `src/memos/mem_scheduler/schemas/message_schemas.py` | Redis/local queue 的统一任务消息和序列化边界。 |
| `MemOSClient` | `src/memos/api/client.py` | Python HTTP SDK；Token 认证、重试、JSON 模型解析、SSE 流、消息/记忆/知识库/反馈/聊天/profile 等远端 API。 |

### 5.2 TypeScript V7

| 符号 | 相对路径 | 作用 |
|---|---|---|
| `bootstrapMemoryCoreFull` | `apps/memos-local-plugin/core/pipeline/memory-core.ts` | 解析运行目录/配置，打开 SQLite、运行迁移、创建 embedder/LLM/repositories/pipeline。 |
| `createMemoryCore` | 同上 | 将 `PipelineHandle` 包装成适配器面对的 `MemoryCore`，提供生命周期、turn、反馈、查询、Skill、配置、导入导出、SSE 观测接口。 |
| `createPipeline` | `apps/memos-local-plugin/core/pipeline/orchestrator.ts` | 建立 event buses、session、capture/reward/L2/L3/skill/feedback subscribers 与 retrieval entry points。 |
| `MemoryCore.onTurnStart/onTurnEnd` | `apps/memos-local-plugin/agent-contract/memory-core.ts` | 统一的回合开始检索/注入与回合结束捕获/持久化契约。 |
| `turnStartRetrieve` / `toolDrivenRetrieve` / `skillInvokeRetrieve` / `subAgentRetrieve` / `repairRetrieve` | `apps/memos-local-plugin/core/retrieval/retrieve.ts`、`retrieval/index.ts` | 按触发场景选择 Tier 组合。 |
| `runL2` / `runL3` / `runSkill` | `core/memory/l2/`、`core/memory/l3/`、`core/skill/` | Policy 归纳、World Model 抽象合并、Skill 资格/证据/结晶/校验/生命周期。 |
| `openDb` / `runMigrations` / `makeRepos` | `core/storage/connection.ts`、`migrator.ts`、`repos/index.ts` | SQLite 连接、迁移和按领域 repository 装配。 |
| `startHttpServer` | `apps/memos-local-plugin/server/http.ts` | Node 标准库 HTTP/SSE 服务；静态 Viewer、`/api/v1/*`、鉴权、body 限制和优雅关闭。 |
| `RPC_METHODS` | `apps/memos-local-plugin/agent-contract/jsonrpc.ts` | `core.*`、`session.*`、`episode.*`、`turn.*`、`memory.*`、`skill.*`、`config.*`、`hub.*`、`logs.*`、`events.*` 方法注册。 |
| `MemosBridgeClient` | `apps/memos-local-plugin/adapters/hermes/memos_provider/bridge_client.py` | 启动/复用 Node bridge，行分隔 JSON-RPC 2.0、响应匹配、通知分发、反向 `host.llm.complete` 回调与进程清理。 |

## 6. API、CLI 与 SDK

### 6.1 Python REST API

ASGI 入口是 `memos.api.server_api:app`，应用在启动时加载 `.env`、发现插件、初始化 `server_router` 组件，挂载 `/download` 静态目录，注册请求上下文与统一异常处理。`server_router.py` 使用 `/product` 前缀与 handler/依赖容器。

已从实际路由读取到的 endpoint 分组：

- `GET /health`：服务健康状态。
- 记忆写入/检索：`POST /product/add`、`POST /product/search`、`POST /product/get_all`、`POST /product/get_memory`、`GET /product/get_memory/{memory_id}`、`POST /product/get_memory_by_ids`、`POST /product/delete_memory`、`POST /product/feedback`。
- Cube：`POST /product/create_cube`、`POST /product/register_cube`。
- Chat：`POST /product/chat/complete`、`POST /product/chat/stream`、`POST /product/chat/stream/playground`、`POST /product/chat/stream/business_user`。
- Scheduler：`GET /product/scheduler/allstatus`、`GET /product/scheduler/status`、`GET /product/scheduler/task_queue_status`、`POST /product/scheduler/wait`、`GET /product/scheduler/wait/stream`（SSE）。
- 辅助/内部：`POST /product/suggestions`、`/get_user_names_by_memory_ids`、`/exist_mem_cube_id`、`/delete_memory_by_record_id`、`/recover_memory_by_record_id`、`/get_memory_dashboard`。
- 管理路由另在 `src/memos/api/routers/admin_router.py`，认证/管理 key 逻辑在 `src/memos/api/middleware/auth.py`。

请求/响应以 `product_models.py` 的 Pydantic 模型为准；`APISearchRequest` 和 `APIADDRequest` 支持 readable/writable cube 列表，并在模型校验阶段把旧的单 Cube 字段映射到新字段。

### 6.2 Python CLI

`pyproject.toml` 的 `[project.scripts]` 把 `memos` 指向 `memos.cli:main`。当前 CLI 真实子命令只有：

- `memos download_examples --dest ./examples`：从 GitHub 下载 examples 压缩包并解包。
- `memos export_openapi --output openapi.json`：导入 FastAPI app 并写出 OpenAPI JSON。

Makefile 还定义 `make serve`（`uvicorn memos.api.server_api:app`）、`make openapi`（调用上述 CLI 写 `docs/openapi.json`）、`make test`、`make format`、`make pre_commit`。本轮没有执行这些会启动服务、写文件或改变工作树的命令。

### 6.3 Python SDK

`src/memos/api/client.py` 的 `MemOSClient` 是远端 OpenMem API 的 Python SDK：

- 初始化参数：`api_key`、`base_url`、`is_global`，也可读 `MEMOS_API_KEY`、`MEMOS_BASE_URL`、`MEMOS_IS_GLOBAL`。
- HTTP：主要使用 `requests.post/get`，默认每个请求最多重试 3 次、超时 30 秒，响应由 `MemOS*Response` Pydantic 模型解析。
- 能力：`get_message`、`add_message`、`search_memory`、`get_memory`、`get_memory_by_id`、知识库创建/删除/文件操作、`get_task_status`、`add_feedback`、`delete_memory`、`update_memory`、`extract_memory`、`rerank`、profile template/instance 操作、`chat`。
- `chat(stream=True)` 与 `_iter_sse_data` 解析 `data:` 行并在迭代结束关闭响应；测试覆盖了流式不误解析 JSON、参数契约与旧任务状态格式归一化。

### 6.4 TypeScript/跨语言 SDK 契约

- `agent-contract/memory-core.ts` 是 TypeScript 适配器 SDK 契约：`init/shutdown/health`、session/episode、`onTurnStart/onTurnEnd`、feedback、`searchMemory/timeline`、traces/policies/world/skills、config、metrics、bundle、embedding maintenance、event/log subscription。
- `agent-contract/jsonrpc.ts` 是 Hermes/Python 等非 TS 客户端的 JSON-RPC 2.0 契约；Node bridge 通过 `bridge/methods.ts`（实际存在）将方法分派给 `MemoryCore`，事件/日志以通知返回。
- `packages/adapter-base` / `packages/memos-schema` 表达了早期的 `BaseMemoryAdapter`、`MemoryQuery`、`MemoryEvent`、`PromptInjection` 等跨宿主类型；需与当前 V7 `agent-contract` 版本对照后使用。

### 6.5 本地插件 HTTP/SSE

`apps/memos-local-plugin/server/http.ts` 使用 Node `http`，默认 loopback，服务 SPA 与 `/api/v1/*`。已实际读取的主要 memory 路由包括：

- `GET/POST /api/v1/memory/search`；
- `GET /api/v1/memory/trace`、`/memory/policy`、`/memory/world`；
- 其他 route registry 注册的 session、feedback、skill、config、logs、metrics、import/export、hub 和 `/api/v1/events` SSE 路由。

端口约定来自本地插件实际文档/代码：OpenClaw `18799`、Hermes `18800`、DeepSeek Harness `18801`；具体运行参数仍由 adapter/server options 决定。

## 7. 技术栈与依赖

| 范畴 | 实际技术 |
|---|---|
| Python | Python `>=3.10`，当前仓库声明支持 3.10–3.13；Pydantic v2、Poetry/poetry-core、pytest、Ruff。 |
| Python Web | FastAPI `0.115.x`、Uvicorn、Starlette StaticFiles、SSE 响应路径；MCP 使用 `fastmcp`。 |
| Python 模型/网络 | OpenAI SDK、Ollama、Transformers、Tenacity、scikit-learn、requests、dateutil、Prometheus client。 |
| Python 可选后端 | Neo4j、Redis、Pika/RabbitMQ、PyMilvus、Qdrant client、sentence-transformers、MarkItDown、Chonkie、LangChain text splitters、Tavily 等，按 extras 分组。 |
| Python 数据存储 | SQLAlchemy + PyMySQL 用于用户/调度相关持久化；图存储实现含 Neo4j/PolarDB/PostgreSQL 等；向量存储含 Qdrant/Milvus。具体运行组合由配置决定。 |
| TypeScript | Node `>=20`、TypeScript 5、ES modules、Vitest、Vite。 |
| 本地插件存储 | `better-sqlite3`、SQLite WAL/FTS5、SQL migrations、float32 BLOB 向量；本地 embedding 使用 `@huggingface/transformers` 路线，亦支持远端 provider。 |
| 本地插件服务 | Node 标准库 `http`，HTTP JSON API、SSE、静态 Viewer；不依赖 Fastify/Express。 |
| 本地插件模型 | OpenAI-compatible、Anthropic、Gemini、Bedrock、host bridge、local-only 等 LLM provider；OpenAI/Gemini/Cohere/Voyage/Mistral/local 等 embedding provider，实际注册以当前源码为准。 |
| 配置与运行目录 | Python 使用 Pydantic 配置/环境变量/示例 JSON；本地插件使用 `config.yaml`、`MEMOS_HOME`/`MEMOS_CONFIG_FILE`/agent-specific home。 |
| 分发 | Python `MemoryOS`；本地插件 npm package `@memtensor/memos-local-plugin`，OpenClaw/Hermes/DSH agent-specific 安装，不是独立全局 CLI。 |

## 8. 测试结构与验证现状

### 8.1 已盘点的实际规模

本轮用只读目录遍历核对到：

- `src/` Python 源文件：381 个；
- 根 `tests/` Python 测试文件：138 个；
- `apps/memos-local-plugin/` TypeScript/CTS/MTS 源文件：467 个；
- 本地插件测试文件（TS + Python）：189 个；
- `packages/` TypeScript 文件：55 个。

这些是文件数量，不是通过测试数量。未执行测试，不能据此宣称通过。

### 8.2 Python 测试分层

`tests/` 按实现目录镜像组织，实际包含：`api/`、`configs/`、`llms/`、`embedders/`、`vec_dbs/`、`graph_dbs/`、`chunkers/`、`parsers/`、`reranker/`、`memories/`、`mem_cube/`、`mem_os/`、`mem_reader/`、`mem_scheduler/`、`mem_user/`、`mem_feedback/`、`mem_chat/`、`mem_agent/`、`dream/`、`plugins/` 等。

本轮实际阅读的代表性测试：

- `tests/mem_os/test_memos_core.py`：mock LLM/Reader/UserManager/Cube，覆盖初始化、用户、注册 Cube、search/add/get_all/chat、系统 prompt、共享 Cube 和错误边界。
- `tests/api/test_client.py`：mock requests，覆盖 SDK payload、用户/agent 互斥、知识库、分页、任务状态兼容、SSE chat 和文件句柄关闭。
- `tests/test_cli.py`：覆盖 OpenAPI 导出、examples 下载及 CLI 子命令分派。
- 同时枚举了根 `tests/` 的全部测试路径，以确认模块镜像关系。

项目规定的命令（本轮未执行）：`poetry run pytest tests`、单文件 `poetry run pytest tests/<path>/test_xxx.py -q`、`make format`、`make pre_commit`。

### 8.3 TypeScript 本地插件测试分层

`apps/memos-local-plugin/tests/` 实际包含：

- `unit/`：pipeline、capture、reward、retrieval、L2/L3/skill、feedback、storage、embedding、LLM、config、logger、server、viewer、各 adapter；
- `python/`：Hermes bridge client、runtime home、shared bridge runtime；
- `integration/`：bridge ESM、诊断模式、OpenClaw full chain；
- `e2e/`：`v7-full-chain.e2e.test.ts`；
- `helpers/`：临时 home、fake LLM、fake embedder、临时 DB。

`apps/memos-local-plugin/package.json` 声明 `npm test`、`test:unit`、`test:integration`、`test:e2e` 与 `lint`（`tsc --noEmit`）。本轮未安装 npm 依赖、未运行这些命令。

## 9. 未确认项与风险

以下项目是本轮静态建档边界内的未确认/需要后续单独验证项，不应被本文当成已通过的运行结论：

1. **FastAPI OpenAPI 产物缺失**：`CLAUDE.md`/`AGENTS.md`把 `docs/openapi.json`称为 API 契约并要求 `make openapi` 生成；当前实际读取路径不存在该文件。本轮禁止生成构建/契约产物，因此没有补生成。
2. **服务端默认端口表述不一致**：README 自托管示例使用 `8000`，`server_api.py` 的 `__main__` 默认 `8001`，Makefile 的 `uvicorn` 未显式端口。实际部署端口需以启动方式和环境为准。
3. **Python API 初始化副作用**：`server_router.py` 在模块导入时执行 `handlers.init_server()` 并构造全局 handler/数据库/调度组件；启动环境依赖、外部 DB 可达性和生命周期关闭行为未在本轮运行验证。
4. **Python 存储组合是配置驱动的**：`GeneralTextMemory` 的通用实现实际依赖 embedder + vector DB；Tree/Preference/Activation/Parametric 路线有额外 provider 和可选依赖。仅从 import/配置不能证明每种组合都可启动。
5. **TS V7 与早期 packages 并存**：`packages/memos-core` 的入口 import 与当前文件清单存在漂移；`packages/` 没有被当作当前运行主链。需要后续确认其发布/构建历史及是否仍有外部消费者。
6. **根 README 的“本地插件”描述范围大于 Python 主库**：README 同时介绍 Cloud Plugin、Local Plugin、Self-Host；应按本文件的两条主实现线阅读，不能把云 API、Python 服务、V7 SQLite 视作同一后端。
7. **本地插件文档入口存在层级重复**：`apps/memos-local-plugin/ARCHITECTURE.md` 是该子项目已有细节文档；本根文档只抽取其与源码交叉核实的边界和关键路径，未删除或机械复制。两份文档后续若变更，需同步核对，根文档仍是本仓库架构总览。
8. **本地插件本轮未运行**：没有执行 Node/TypeScript 编译、Vitest、Python pytest、SQLite migration 或启动 HTTP/bridge，因此无法确认依赖安装状态、构建状态、外部 provider 可用性和运行时端到端行为。
9. **README/代码的版本信息可能随工作树变化**：本文依据 HEAD `7f80d13` 与当前未提交的既有 `细探-MemOS.md` 之外的源码静态状态；未来切换 commit 后应重新核对入口、路由、迁移和 package 版本。
10. **安全边界**：V7 的日志有脱敏/loopback/API key/session 机制，但 SQLite 记忆表仍可能保存原始对话与工具输出；Python API 的生产鉴权、外部图/向量库网络边界和实际 secrets 管理未在本轮验证。

## 10. 本轮实际读取与修改记录

### 实际读取的权威/导航/依赖文件

- `README.md`、`AGENTS.md`、`CLAUDE.md`、`pyproject.toml`、`Makefile`；另核对 `uv.lock`、`poetry.lock` 存在，但未全文展开；
- `src/memos/__init__.py`、`mem_os/main.py`、`mem_os/core.py`、`mem_cube/general.py`；
- `src/memos/configs/mem_os.py`、`configs/mem_cube.py`、`configs/memory.py`；
- `src/memos/memories/base.py`、`textual/base.py`、`textual/item.py`、`textual/general.py`、`memories/factory.py`；
- `src/memos/api/server_api.py`、`api/routers/server_router.py`、`api/product_models.py`、`api/client.py`、`cli.py`；
- `src/memos/mem_scheduler/general_scheduler.py`、`scheduler_factory.py`、`schemas/message_schemas.py`；
- Python 代表测试 `tests/test_cli.py`、`tests/mem_os/test_memos_core.py`、`tests/api/test_client.py`；
- 本地插件 `apps/memos-local-plugin/README.md`、`package.json`、已有 `ARCHITECTURE.md`、`core/index.ts`、`core/pipeline/index.ts`、`core/pipeline/memory-core.ts`、`core/pipeline/orchestrator.ts`、`core/retrieval/index.ts`、`core/storage/index.ts`、`core/storage/connection.ts`、`core/storage/migrations/001-initial.sql`；
- 本地插件 `agent-contract/memory-core.ts`、`agent-contract/jsonrpc.ts`、`adapters/openclaw/index.ts`、`adapters/hermes/README.md`、`adapters/hermes/memos_provider/bridge_client.py`、`server/http.ts`、`server/routes/memory.ts`；
- `packages/memos-core/src/index.ts`、`packages/memos-core/src/types.ts`、`packages/memos-schema/src/index.ts`、`packages/adapter-base/src/index.ts`；
- 通过只读目录清单核对了根目录、`src/`、`tests/`、`apps/memos-local-plugin/`、`packages/` 的实际文件结构与测试规模。

### 修改文件

- 新增：`ARCHITECTURE.md`（仅此文件）。

### 未做的事情

- 已吸收此前 `细探-MemOS.md` 的源码分析结论；后续只维护本文件，旧细探笔记不再作为独立事实源。
- 未修改任何已有源码、依赖清单/锁文件、测试、配置或子项目 `ARCHITECTURE.md`；未安装依赖、未启动服务、未生成 OpenAPI/编译产物/数据库、未提交 Git。

## 11. 第三轮：通用底座映射与裁决（基于当前源码）

### 11.1 证据边界与本轮结论口径

本节是第三轮映射，不把 MemOS 的现有目录直接当成平台已经存在的支持库。证据优先级为：当前源码与测试路径 > 当前配置/迁移 > 文档声明。当前目标仓库内没有可单独读取的 `细探-MemOS.md`；根文档明确说旧细探结论已经吸收，且后续只维护本文件（第 3、338、363-364 行）。因此本节只能以当前工作树实际源码为证据，不能声称完成旧细探逐条复核。

本轮还发现专属 MCP 开工上下文错绑到 `/Users/hekunhua/Documents/Agent/PHP/华世王镞_v3`，目标 MemOS 没有 `.codegraph/`，所以以下映射**不使用错误项目的代码图、记忆或验证结论**，而是以目标仓库的只读源码为证据。没有运行时验证的内容继续标为“待核/未验证”。

```text
Agent/宿主
  → agent adapter（OpenClaw/Hermes/DeepSeek 或 Python REST/SDK）
  → agent-contract / Python MOS API
  → MemoryCore / MOSCore（唯一产品调用门面）
  → pipeline/orchestrator 或 MemCube + scheduler
  → memory/state module（episode/trace/policy/world/skill 或 textual/activation/parametric）
  → support library（LLM/embedder/vector/graph/SQLite/queue/process）
  → provider / SQLite / Redis / 外部模型
  → 统一 DTO、事件、日志、资源释放
  → JSON-RPC bridge、HTTP/SSE 或 FastAPI gateway
```

这张图是**目标底座的单链路映射**，不是说 Python MOS 与 TypeScript V7 已经共享一个运行时。当前源码仍是两条实现线：TypeScript 的 `MemoryCore` 通过 `core/pipeline/memory-core.ts` 暴露 V7 算法核心；Python 的 `MOSCore` 直接编排用户、MemCube、LLM、Reader 和 Scheduler（`src/memos/mem_os/core.py:38-80`）。二者必须先在契约/适配层对齐，不能把两套状态库拼成一个隐式写入链。

### 11.2 记忆层级与状态所有权映射

源码已经明确实现了 L1/L2/L3 语义，但没有统一的 L0-L4 平台术语。下面把“现有事实”和“平台映射”分开：

| 映射层 | 当前 MemOS 事实 | 建议底座归属 | 唯一写 owner / 边界 | 裁决 |
|---|---|---|---|---|
| L0 工作上下文 | 当前 turn 的 `TurnInputDTO`、`InjectionPacket`、`AbortSignal`、namespace、可见上下文；`MemoryCore.onTurnStart/onTurnEnd` 是边界（`agent-contract/memory-core.ts:161-239`） | 运行核心的运行上下文与资源预算 | 运行核心持有，适配层只提供 turn/取消/namespace | **吸收**；不得持久化为长期记忆，除非进入 L1 |
| L1 轨迹/经历 | `sessions`、`episodes`、`traces`；trace 保存 user/agent/tool/reflection/value/alpha/reward/vector 等（根文档 175-185 行，`core/pipeline/orchestrator.ts:311-353`） | 记忆/状态模块 | episode/trace repository 写入；事件总线只广播，不能作为权威状态 | **吸收并升级**为通用事件/轨迹状态模型 |
| L2 策略/经验 | `runL2` 在 reward.updated 后做关联、candidate pool、跨 episode 归纳、gain/support/status 更新（`core/memory/l2/l2.ts:1-18,61-77,120-167,371-454`） | 记忆/状态模块的策略演化子模块 | L2 runner + policy repository；诱导失败不能回滚 reward 写入（`l2/subscriber.ts:1-10`） | **吸收算法边界，隔离 prompt/阈值** |
| L3 世界模型 | 只处理达到 active/gain/support 门槛的 L2，聚类、冷却、LLM 抽象、合并或创建 world model，并保留 source policy/episode（`core/memory/l3/l3.ts:1-20,86-181,183-318`） | 记忆/状态模块的跨任务抽象子模块 | L3 runner + world-model repository；KV 只保存 cooldown 等运行元数据 | **吸收机制，策略参数外置** |
| L3 可调用 Skill | Skill 由合格 policy 取证、LLM crystallize、verifier 校验后以 `candidate` 写入；trial/feedback 才能转 active/archived（`core/skill/skill.ts:1-18,79-124,160-245`；`core/skill/lifecycle.ts:59-160`） | 记忆/状态模块 + Agent 能力视图 | skill repository 写 row；产品/宿主决定何时注入、是否提供工具 | **吸收状态机，隔离产品策略** |
| L4 外部影响/共享与制品 | feedback、Hub shared memories、导入/导出 bundle、viewer/API 观察；不是当前单一“记忆层”，而是跨边界证据/共享制品 | 网关/控制面/共享适配层 | Hub/API 负责边界，核心只读/提交公开命令；共享行须经过 namespace/share 过滤 | **待核**；禁止把 Hub 数据当本地权威记忆 |

L1-L3 之间的状态推进是事件驱动但不是完整事件溯源：`CoreEvent` ring buffer 会从 SQLite 行合成最近事件（`core/pipeline/orchestrator.ts:150-210,219-301`），L2/L3/Skill 又直接通过 repository 更新状态。因此平台化时应保留两类事实：**追加的领域事件/运行证据**和**可重建的当前投影**；不能只把内存 event bus 或 ring buffer 当作崩溃恢复来源。

Python 线的对应关系不同：`TextualMemoryItem`、metadata/history/version 以及 MemCube 槽位是 L1/记忆容器；`MOSCore.chat/search/add` 负责产品级用户/Cube 权限和 prompt 组装（`src/memos/mem_os/core.py:251-352,546-682`），Activation/Parametric 记忆是模型运行资源而非可直接等价的 L2/L3。Python 的异步 `ScheduleMessageItem` 承载 user/cube/session/trace/label/content/task_id 等任务上下文（`src/memos/mem_scheduler/schemas/message_schemas.py:38-62`），应映射到运行核心任务契约，不与 V7 的 trace/event row 混写。

### 11.3 Agent contract、检索、技能/策略的边界

#### 11.3.1 Agent contract 是唯一跨宿主门面

`agent-contract/memory-core.ts` 是当前 V7 的正式跨适配器接口：生命周期 `init/shutdown/health`、session/episode、turn start/end、feedback、查询、Skill、bundle、embedding maintenance、事件/日志订阅都在同一 `MemoryCore`（`memory-core.ts:169-239,241-365,475-617`）。TypeScript 适配器可直接调用实现，非 TS 宿主必须走 JSON-RPC；`jsonrpc.ts:1-7` 明确重命名/删除方法是 breaking，`RPC_METHODS` 在 `jsonrpc.ts:56-125` 统一方法注册，错误码转换在 `jsonrpc.ts:127-140`。

因此通用契约拆分为：

- **公开请求/响应**：`MemoryCore` DTO、`MemosError`/错误码、JSON-RPC 2.0 envelope、事件/日志通知。
- **运行控制**：`AbortSignal`、绝对 deadline、foreground/background 资源优先级；这些控制字段只能在进程内使用，跨 JSON-RPC 时须显式序列化为 deadline/取消请求。
- **产品策略**：agent kind、namespace/profile、检索 scenario/profile、tier 开关、Skill 注入模式、prompt、阈值、是否开启 lightweight/recovery。它们不能渗入通用 DTO 的语义字段，更不能让某个宿主直接写 repository。

#### 11.3.2 检索通用能力与产品策略

当前检索入口有五个：`turn_start`（Tier 1/2/3）、`tool_driven`（Tier 2 可选 Tier 3）、`skill_invoke`（Tier 1 + Tier 2）、`sub_agent`（Tier 2/3）、`decision_repair`（Tier 1/2，含低价值 anti-pattern）；入口函数只读存储并发出 started/done/failed 事件（`core/retrieval/retrieve.ts:1-18,95-210`）。共享执行链是：query builder → embedding（可降级关键词）→ 四路 tier 并行 → rank/RRF/阈值/MMR → 可选 LLM filter → decision guidance → packet（`retrieve.ts:238-371,384-435,537-669`）。`ranker.ts:1-39,132-189,221-369` 是纯函数，无存储副作用。

底座拆法如下：

| 通用能力（支持库/记忆模块） | Agent 产品策略（适配层/配置） |
|---|---|
| query 编译、FTS/pattern/exact identifier 通道 | 哪种 agent 在何种 turn 触发哪一路检索 |
| 向量/关键词候选读取、namespace 可见性 | `turn_start/tool_driven/...` 的 tier 组合与 limit |
| RRF、相对阈值、长标识符硬确认、去重、MMR | `RetrievalProfile`、`personal_fact`、lightweight 行为 |
| LLM relevance filter 的请求/超时/失败语义 | 是否延迟 filter 到调用方、malformed retry 次数 |
| `InjectionPacket` 结构化结果与来源引用 | Skill 注入 `summary`/`full`、prompt 文字和宿主工具名 |
| 检索事件、stats、drop 原因和 traceability | UI 展示、OpenClaw/Hermes 的 prompt 拼装 |

检索必须保持一条能力链：`适配器 → MemoryCore.searchMemory/onTurnStart → orchestrator.retrieve* → Retriever/runAll → rank → repository/provider → InjectionPacket/event`。不得在 OpenClaw、Hermes、Python SDK 各复制一份 query/rank/filter；差异只能通过明确的 `profile/plan/config` 输入表达。

#### 11.3.3 Skill/策略隔离

L2 policy、L3 world model、Skill 是当前 V7 的产品演化策略载体，不是“模型输出即事实”。通用层只提供：证据选择、关联/聚类、草稿解析、结构校验、版本化写入、状态转移、来源链和可重建查询；产品层提供 `L2_INDUCTION_PROMPT`、`L3_ABSTRACTION_PROMPT`、`SKILL_CRYSTALLIZE_PROMPT`、min support/gain/eta、candidate trials、cooldown、何时注入及是否允许自动 promotion。

Skill 当前明确“verifier 通过仍先 candidate，生命周期由 feedback/trial 驱动”（`core/skill/skill.ts:182-211`），而 `lifecycle.ts:76-89,122-160` 定义 candidate/active/archived 的产品语义。底座不得把“active”硬编码成所有 Agent 都可调用；应将它作为策略给出的可见性/资格投影，并保留证据和版本。

### 11.4 异步巩固、模型与存储资源的四层拆分

#### 11.4.1 支持库层

只承载可复用、可替换、可测量的原子能力：

1. **模型支持库**：`LlmClient`/`LlmProvider`、`Embedder`/`EmbeddingProvider`。客户端统一 JSON 解析/校验、超时、deadline、重试、host fallback、circuit breaker、status/error sink；Provider 只负责实际调用，契约见 `core/llm/types.ts:231-269,320-363` 与 `core/embedding/types.ts:102-133,166-194`。
2. **存储支持库**：SQLite 打开/事务/statement cache/close、migration、FTS/keyword/vector 编解码、repository 基元。`openDb` 负责 WAL/foreign_keys/busy_timeout/close/tx（`core/storage/connection.ts:25-145`），`runMigrations` 负责有序、幂等、事务化迁移和 ready 标记（`core/storage/migrator.ts:1-12,90-145`）。
3. **异步与资源支持库**：Abort/deadline、优先级 semaphore、retry lease、bounded queue、coalescing、进程/管道关闭、可重入释放。当前 `createForegroundResources` 已提供 foreground/background gate、embedding admission、AbortSignal 和幂等 release（`core/util/foreground-resources.ts:8-24,47-196`）。
4. **协议与观测支持库**：DTO/错误/事件、JSON-RPC envelope、日志脱敏、metrics、trace/correlation id。它们不决定“什么是好记忆”。

#### 11.4.2 记忆/状态模块层

这一层拥有 domain row 与状态投影：session/episode/trace、feedback、policy/candidate pool、world model、skill/trial、namespace visibility、source links、embedding retry queue。模块内部只能调用支持库公开入口；L2/L3/Skill 的 subscriber 负责事件到模块的编排，不允许适配器直写 `repos`。

当前异步巩固链是：

```text
episode finalized
  → capture/reward
  → reward.updated
  → L2 subscriber（按 episode 串行、合并最新 reward）
  → l2.policy.induced / updated
  → L3 subscriber（single-flight，事件 burst 排队）
  → world model update/create
  → Skill subscriber（microtask debounce，eligibility → crystallize → verify → candidate）
  → trial/feedback → active/archived
```

L2 的 `pendingByEpisode`/`inflightByEpisode` 和 `drain()` 证据见 `core/memory/l2/subscriber.ts:51-155`；L3 的 single-flight/queued replay/drain 见 `core/memory/l3/subscriber.ts:53-141,181-199`；Skill 的 queue/flush/lifecycleTick 见 `core/skill/subscriber.ts:60-107,206-232`。这些是可复用的异步编排模式，但具体事件名、门槛和 prompt 属于产品策略。

#### 11.4.3 运行核心层

运行核心只负责把模块和资源以确定顺序装配起来：`createPipeline` 建立 event buses、session、capture/reward/L2/L3/skill/feedback subscribers 与 retrieval 入口（`core/pipeline/orchestrator.ts:123-150`）；`flush()` 按 capture → reward → L2 → L3 → Skill → feedback → embedding retry 顺序 drain（`orchestrator.ts:1610-1644`）。它还负责 startup recovery、namespace/foreground budget、取消传播、shutdown 状态、故障隔离和恢复。

启动时 `bootstrapMemoryCoreFull` 的实际顺序是 open SQLite → migrations → repos → host bridge → LLM/embedder → pipeline（`core/pipeline/memory-core.ts:203-267,269-405,526-557`）。这应成为唯一装配入口；不要为某个 Agent 再造一套“轻量 MemoryCore”。Python 的 `MOSCore`/`GeneralScheduler` 可通过适配层接入同一公共 contract，但在没有迁移证据前只能隔离为另一产品运行时。

#### 11.4.4 网关层

网关只做协议、鉴权、限流/体积、路由和生命周期，不实现记忆算法：

- HTTP/SSE：`server/http.ts` 默认 loopback，API key/session gating、body limit、route dispatch、SSE tracking 和 graceful close（`server/http.ts:55-157,227-301`）。
- JSON-RPC/bridge：Hermes Python client 通过行分隔 JSON-RPC 调 Node 子进程；请求匹配、通知、reverse `host.llm.complete`、超时、BrokenPipe、reader EOF 和 pending 唤醒见 `bridge_client.py:131-171,309-369,393-463,465-524`。
- Bridge 进程：PID singleton、stdio/daemon 模式、启动顺序、viewer fallback、SIGTERM/SIGKILL 和 20 秒 shutdown ceiling 见 `bridge.cts:35-45,83-195,390-431,503-616`。

网关只调用 `MemoryCore`，不得调用 `runL2`/`repos`/Provider。Python FastAPI 同样只通过 router/handler 调 `MOSCore`，其 lifespan 调 `shutdown_components`（`src/memos/api/server_api.py:33-72`）。

### 11.5 现有能力命中表与第三轮裁决

| 当前能力/证据 | 目标底座落点 | 决策 | 不能带入底座的部分 |
|---|---|---|---|
| `agent-contract` + JSON-RPC registry | 公共契约/网关 | **吸收** | Agent 专属方法别名、宿主 prompt |
| `LlmClient`/`Embedder` provider facade | 模型支持库 | **吸收并升级** | 某 Agent 的 provider 顺序、API key、fallback 偏好 |
| SQLite/migrator/repos/FTS/vector | 存储支持库 + 状态 repository | **吸收并升级** | V7 专有表名、Viewer 查询字段直接成为公共 schema |
| session/episode/trace/policy/world/skill | 记忆/状态模块 | **吸收并升级** | V7 的 reward 公式、阈值、Skill 命名与注入文案 |
| L2/L3/Skill subscribers + drain | 运行核心异步巩固编排 | **吸收模式** | 事件名、cooldown、candidate/active 规则不可硬编码为全 Agent 规则 |
| `rank` 与五入口 retrieval | 检索支持库/模块 | **吸收** | Tier 组合、profile、LLM filter 是否启用由产品策略输入 |
| `createPipeline`/`MemoryCore` | 运行核心唯一装配/门面 | **吸收** | 不允许适配器绕过 facade；不复制第二套 orchestrator |
| HTTP/SSE + stdio JSON-RPC + reverse host LLM | 统一网关适配层 | **吸收** | 固定端口、OpenClaw/Hermes 路径和 viewer 页面是产品部署策略 |
| Python `MOSCore` + MemCube + GeneralScheduler | Python 产品适配/兼容运行时 | **隔离、待核** | user/Cube 产品权限、默认 prompt、Python 专有四槽模型不可直接升格通用底座 |
| `packages/*` 早期 TS 包 | 历史兼容材料 | **废弃/隔离** | 没有当前入口、构建或消费者证据前不得接入唯一链路 |

第三轮的装配计划不是立刻改生产底座，而是：先冻结 `MemoryCore`/JSON-RPC/错误/取消/事件 contract；再抽出模型与存储支持库的最小接口；随后把 L1-L3/Skill repository 与演化 runner 放入记忆/状态模块；最后让 HTTP/SSE、stdio bridge、Python REST 适配器只调用统一门面。每一步都必须有 owner、能力 id、资源预算、回滚和 L0-L4 验收；未完成前不得建立旁路。

### 11.6 资源生命周期矩阵

| 资源 | 创建/持有 | 正常完成 | 业务失败 | 超时/主动取消 | 宿主崩溃/进程崩溃 | 当前证据与缺口 |
|---|---|---|---|---|---|---|
| SQLite DB/WAL/statement cache | `openDb` 创建目录/连接，repo 持有；`MemoryCore` shutdown 回调关闭（`connection.ts:25-43,72-145`） | `db.tx` commit，`close()` 清 cache/handle | 事务抛错由 better-sqlite3 rollback；migration 失败 bootstrap close 后抛 `config_invalid` | 当前 DB API 没有查询级 Abort；上层应在调用 deadline 到期后停止新任务，不能假称已取消 SQL | 下次启动重新 open + migrations；WAL/未完成写恢复依赖 SQLite，未做本轮 crash 注入 | 有 close/idempotent 证据；无本轮真实断电/kill 中间事务验证 |
| Migration/ready 状态 | `runMigrations` 枚举 SQL，逐文件事务写 `schema_migrations` | 全部完成后 `markReady` | 单文件事务失败，bootstrap 关闭 DB | 无独立 migration deadline | 依赖 SQLite 事务重启重放；半迁移修复未单独测试 | `migrator.ts:90-145`；需 L2/L3 真实临时 DB round-trip |
| LLM provider/HTTP/native 会话 | `LlmClient` 统一调用 Provider；provider 可 `close()` | 返回 completion，记录 status/log | 重试耗尽、JSON malformed、terminal error；可 host fallback；circuit breaker 可打开 | provider 收 `AbortSignal/deadlineAt`，调用级 timeout 不续期；超时语义仍需 provider 实测 | 进程消失由 bridge/gateway 上层感知；模型侧服务状态不由 core 恢复 | `llm/types.ts:214-251`、`client.ts:300-415`；未实测每 provider 的取消真实性 |
| Embedder/cache/vector | embedder facade 管 cache/stats，资源仲裁器管理 admission；L2/L3/Skill 缺向量入 retry queue | 返回向量，释放 semaphore | 失败记录 `system_error`，记 `embedding_retry_queue`，检索可退化 FTS/pattern | `foreground-resources` 合并 shutdown/request signal，释放函数幂等 | retry queue/lease 需重启恢复；embedding 过程崩溃无本轮证据 | `foreground-resources.ts:104-145,204-273`、`embedding/types.ts:104-123`；retry lease 需补测 |
| L2/L3/Skill background task | subscriber 创建 Promise/inflight；按 episode 或 single-flight 持有 | `drain/flush` 等待并释放 map；写 row/event | 捕获后发 `l2.failed/l3.failed/skill.failed`，不向上游抛（L2/L3 subscriber） | 当前 shutdown 先 flush 15s，再 abort，最多再等 4s；超限标 `flush_abandoned` | Node 进程死时只剩已提交 SQLite rows，未完成 Promise 丢失；startup recovery 可补部分 episode | `orchestrator.ts:1610-1681`、各 subscriber；需 kill 在每个阶段的恢复探针 |
| AbortSignal/foreground lease | `createForegroundResources` 创建 controller；每次 acquire 返回 release | `finally` release；release 幂等 | provider 异常也走 finally | abort 移除 waiter 并 reject `AbortError`；shutdown abort 全部派生 signal | 进程死由 OS 回收内存，外部 provider/子进程不一定回收 | 代码覆盖正常/取消；需验证队列 waiter 不残留、取消计数和 provider 真停 |
| Event bus/ring buffer/listener | `createPipeline` 创建 buses/listeners/ring；订阅返回 unsubscribe | emit 给 listeners，ring 留最近 160 个 | listener 异常被记录，不阻断 emit | detach/dispose 阻止后续排队；无事件持久事务保证 | 内存事件丢失，重启只按 rows 合成 synthetic events | `orchestrator.ts:150-177,194-301`；必须把关键领域事件持久证据化 |
| JSON-RPC bridge 子进程/stdio | Python `Popen` 持有 stdin/stdout/stderr/reader；Node PID 文件防重复 | stdin EOF/close，等待最多 5s | BrokenPipe/EOF 唤醒 pending 为 `transport_closed` | request waiter 超时移除；close 依次 stdin→wait→SIGTERM→SIGKILL | reader EOF `_abort_pending`；PID guard 清理旧 bridge；残留 PID/进程需现场验证 | `bridge_client.py:228-257,393-463,465-524`、`bridge.cts:83-195`；需真实 ps/lsof 残留检查 |
| HTTP server/socket/SSE | `startHttpServer` bind socket，active SSE set 持有 response | stop accepting，finish in-flight，close idle，按配置销毁 SSE | handler 500 + response end；EADDRINUSE 上抛给 caller | close 时可 destroy active SSE；普通请求允许完成 | supervisor/daemon 重启；端口/PID 残留需要 lsof 验证 | `server/http.ts:55-157`；本轮未启动真实服务 |
| Temp import/export/bundle buffers | gateway body reader/repository bundle 负责；import body 上限 64MB | 返回 imported/skipped，临时数据释放 | validation/row error 应隔离并返回 skipped/error | deadline/cancel 后必须删除临时文件和停止 parser | 崩溃可能留下临时文件；当前未发现统一残留扫描 | 只看到 body limit/route，需专门资源审计 |

### 11.7 失败、超时、取消、崩溃矩阵

| 链路 | 参数/依赖失败 | timeout | cancel | crash/restart | 验收要求 |
|---|---|---|---|---|---|
| turn start → retrieval | 空 query/无可用 channel 返回空 packet；embedder 失败降级关键词；最终失败发 `retrieval.failed` 并返回 emptyResult（`retrieve.ts:260-298,670-687`） | deadline 只压缩 embedding/LLM filter timeout；检索总 deadline 的端到端预算需验证 | `signal` 向 embedder/filter 传递 | 内存 packet 丢失，下一 turn 可重新查询 SQLite | L1：纯 rank/query；L2：临时 SQLite；L3：真实 bridge→Core；确认失败不会伪装命中 |
| episode/session | relation classifier 超时回退 `follow_up`/confidence 0（`orchestrator.ts:92-119`）；DB 读异常需隔离 | classify timeout 有明确上限 | signal 传 session start/classify | open episode 启动恢复；轻量模式静默关闭，普通模式后台 recovery | 验证关系超时不会重复 episode、重启不生成孤儿 |
| reward → L2 | reward 写成功而 L2 可单独失败；candidate/policy 部分 warning | LLM induction timeout 由 LLM facade/deadline 处理；整体 flush 上限 | 当前 L2 input 没有独立 signal，需补通用任务取消契约 | 已提交 reward/candidate 可重放；Promise 中断不应重复 policy | 强制在 L2 induce 前后 kill，核对 duplicate/content key 和 candidate pool |
| L2 → L3 | policy 不足/无 centroid/cooldown 是明确 skip；抽象失败发 `l3.failed` | L3 每 cluster LLM 可能长耗时，只有 pipeline flush 总预算 | subscriber 当前无独立 abort 参数，shutdown abort 只影响资源 provider | single-flight queued replay；进程死后 cooldown/rows决定是否重跑 | 验证同 cluster 不并发、冷却不会吞掉永久失败、恢复有证据 |
| L3 → Skill | evidence empty、LLM 拒绝、verifier fail 都有 warning/event，不写 skill | Skill crystallize/verify 未暴露统一 deadline | 无独立 cancel 参数；需由运行核心传 signal | candidate row 可重建，active 只能由 trial/feedback/lifecycle tick | 验证 verifier fail 不产生 active skill，重启不绕过 trial |
| model fallback/circuit | primary failure → host fallback；两者失败抛统一错误；terminal error 打开 breaker（`client.ts:348-415`） | per-call timeout + absolute deadline，host fallback 额外 `timeout+5s`（`bridge.cts:247-277`） | provider ctx 收 signal，但各 provider 是否真中断待核 | circuit state 是内存态；重启会丢 breaker，需要产品决定是否持久 | L3：模拟 401/429/timeout/host down，检查 error/status/api_logs 与请求次数 |
| Python add/search/scheduler | Cube/user/reader/provider 缺失抛 ValueError/依赖错误；async add 需要 scheduler（`MOSCore:70-139,684-839`） | Python client 默认请求最多 30s；scheduler/backend timeout 需从实现补证 | Python `Future.result`/Redis 消费取消语义未在本轮确认 | FastAPI lifespan 关闭 components；Redis message 可能重复/未 ack 需专项验证 | 不把 Python 产品成功路径当通用底座通过 |
| bridge RPC/gateway | method not found/invalid params/application error 有 JSON-RPC code；HTTP 404/405/500 | Python waiter 默认 30s；Node serverRequest timeout；shutdown 20s | close/EOF 唤醒 pending；SSE 可 destroy | child exit → transport_closed；PID singleton 重启；残留进程/端口必须读回 | L4：真实启动、超时、SIGTERM/SIGKILL、重连和 `ps/lsof` |

### 11.8 唯一链路与防旁路规则

对当前 TypeScript V7，唯一规范链路应冻结为：

```text
OpenClaw/Hermes/DSH adapter
  → MemoryCore（agent-contract/memory-core.ts）
  → createMemoryCore facade
  → PipelineHandle / createPipeline
  → retrieve* 或 session/capture/reward subscriber
  → L2/L3/Skill memory module
  → LlmClient/Embedder/StorageDb/Repos support facade
  → configured provider / SQLite WAL
  → CoreEvent + api_logs + DTO
  → stdio JSON-RPC / HTTP-SSE gateway
```

对 Python 线保持另一条、但同样唯一的产品链：

```text
REST/SDK
  → FastAPI router/handler
  → MOSCore
  → UserManager permission + GeneralMemCube
  → MemoryFactory/TextMemory/Preference/Activation/Parametric
  → LLM/Reader/Embedder/Vector/Graph/User DB factory
  → BaseResponse / ScheduleMessageItem / API lifecycle
```

固定规则：

1. 一个原子能力只能有一个公开 capability id、一个 contract owner 和一个 adapter entry；旧英文键只能在入口归一化，不能在每个宿主复制映射。
2. `MemoryCore`/`MOSCore` 是唯一产品门面；adapter、viewer、Python bridge 不得直接 import `runL2`、`repos` 或 provider。
3. L2/L3/Skill 的状态写只能由对应 memory/state module owner 执行；网关、检索、事件监听只能读或提交命令。
4. provider 不得穿透 DTO 把模型对象、SQLite statement、HTTP response 泄露给产品层；模型/存储资源必须在支持库边界完成关闭/超时/取消转换。
5. 失败、拒绝、超时、取消也必须留下稳定错误/事件/日志；不能以“返回空数组”掩盖是否 provider 失败、无命中或被过滤。
6. `packages/*`、Python 与 V7 只有在 adapter contract + namespace + 数据迁移 + L0-L4 全通过后才能共享能力；在此之前是隔离产品策略，不是第二条隐藏旁路。

### 11.9 L0-L4 验证分级（本轮未宣称通过）

这里的 L0-L4 是平台验收等级，不是仓库现有记忆层级。每一级都必须记录命令、退出码、测试数、外部依赖和资源残留；本轮只做源码读取和文档修改，以下状态均为“待执行”。

| 等级 | 目的 | 最小验证 | MemOS 对应验收 | 通过判据 |
|---|---|---|---|---|
| L0 静态/契约 | 证明路径、类型、唯一入口和文档声明存在 | `git diff --check -- ARCHITECTURE.md`；检查 `MemoryCore`/`RPC_METHODS`/provider facade/唯一 bootstrap 引用；TypeScript `tsc --noEmit`、Python 静态 import/ruff（依赖具备时） | 能从 adapter 找到唯一 facade；错误/取消/deadline 字段有 owner；无 adapter 直达 repo/provider | 命令退出 0，目标路径和公开方法无重复入口 |
| L1 纯模块 | 证明无外部依赖的确定性算法 | `ranker`、query builder、L2 gain/status、L3 cluster/merge、Skill lifecycle/verifier 的现有 unit tests | 空输入、重复、阈值、MMR、candidate→active→archived、失败不写入 | 测试全绿，不能用 skip 代替缺 provider |
| L2 存储/重放 | 证明 SQLite schema、repo、迁移、事件/状态重启语义 | 临时 DB 跑 `runMigrations`；写入 episode/trace/policy/world/skill；关闭重开；embedding retry lease、bundle round-trip；故障注入中间阶段 | rows/索引/外键/namespace 可重建；重复事件幂等；未完成任务可恢复或明确丢弃 | 临时目录清零，数据库不是正式用户库，退出 0 |
| L3 跨层集成 | 证明 Core→pipeline→model/storage→事件链 | 使用 fake LLM/embedder + 临时 SQLite，调用 `bootstrapMemoryCoreFull`、turn start/end、feedback、flush、shutdown；验证 L2/L3/Skill 事件和 API logs | 只经 MemoryCore；模型失败/fallback/timeout/取消有稳定结果；flush 顺序无丢失 | 真实调用链执行，断言 rows/events/error/释放，退出 0 |
| L4 宿主/网关/故障 | 证明真实 Node/Python bridge、HTTP/SSE、进程和资源治理 | 安装依赖后运行 TypeScript unit/integration/e2e、Python bridge tests；启动临时 HTTP/stdio；`curl`/JSON-RPC；SIGTERM/SIGKILL/port collision/timeout/cancel；`ps`、`lsof`、临时目录扫描 | 断线立即 transport_closed；重连不重复 bridge；SSE/child/stdio/PID/port 全清；FastAPI 关闭组件 | 所有专项退出 0，残留进程/端口/文件为 0；若外部 provider 不可用必须明确 `unavailable` 而非 skip/pass |

**当前验证事实**：本轮没有安装依赖、没有运行 Python pytest、Vitest、TypeScript 编译、SQLite migration、HTTP、bridge 或故障注入；因此 L0-L4 均不能写成“通过”。后续执行 L0-L4 时应分别保存 stdout/stderr、退出码、测试计数和资源清理结果，避免把“源码存在”“测试存在”“测试打印 OK”“子代理自报完成”混为真实通过。

### 11.10 第三轮剩余风险与后续复核点

1. MCP 代码图对目标仓库不可用，且开工上下文返回了错误项目根；本节没有使用该错误证据。应由项目 owner 重新绑定专属 `system_engineering_toolkit` 后再做一次代码图/成功验证复核。
2. 当前 V7 的 event bus/ring buffer 是内存态，SQLite rows 是状态投影；尚不能证明所有关键事件都追加持久化、可重放、幂等。应补事件账本或明确哪些事件只是观测事件。
3. L2/L3/Skill subscriber 的 drain/flush 解决了单次进程退出的主要竞态，但 L2/L3/Skill 没有统一的任务 idempotency key、持久 lease 和跨进程取消契约；崩溃窗口仍需 L2/L3/L4 验证。
4. `LlmClient`/`Embedder` 声明了 signal/deadline/close，但 provider 是否真实停止 HTTP/native 调用、超时是否中断底层 socket，不能只凭接口声明认定已实现。
5. Python Scheduler 的 Redis/local queue、handler ack/retry/停止恢复与 V7 subscriber 不是同一任务系统；在没有真实重启和重复消息测试前，Python 只能作为隔离产品适配。
6. HTTP/SSE 和 bridge 的关闭代码有明确上限，但本轮未实际启动进程；端口、PID 文件、子进程组、SSE response、WAL/临时文件的残留仍是 L4 阻断项。
7. 记忆层 L0-L4 的平台术语是本轮映射建议，源码事实仍以 L1 trace/L2 policy/L3 world/skill 和 Python MemCube 为准；跨项目裁决前不能把建议名称写回生产契约。

本节完成的是“第三轮通用底座输入”：命中表、分层落点、通用/策略边界、资源矩阵、失败矩阵、唯一链路和验证契约。它不等价于已经升级任何外部平台支持库，也不授权修改 MemOS 源码、依赖、配置或测试。
