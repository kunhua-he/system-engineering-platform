# Memoria 架构建档

> 本文是本仓库根目录唯一正式架构文档。内容以当前工作树实际源码、依赖清单、测试与根 README 为依据；根目录的 `细探-Memoria.md` 仅作为施工材料读取，不作为事实源机械复制。
>
> 建档边界：本轮只读源码与文档并新增本文件；未修改已有源码、依赖、测试、配置；未安装依赖、启动服务、生成构建产物或提交 Git。

## 1. 项目定位

Memoria 是 MatrixOrigin 的持久化 AI Agent 记忆引擎，产品主张是 **Git for AI Agent Memory**：把记忆的存储、检索、纠错、治理与审计，与 MatrixOne 的数据库原生快照/分支能力结合，提供对记忆而不是代码的 snapshot、branch、merge、rollback、diff 与 selective apply。

真实实现不是单一服务，而是一个 Rust Cargo workspace，外加 Python REST SDK、OpenClaw TypeScript 插件、部署/规则/技能文档。核心后端以 MatrixOne 的 MySQL 兼容协议访问数据库；embedding 可以走 OpenAI-compatible HTTP、多后端轮询、mock，或编译 feature 后使用 fastembed 本地模型；LLM 用于 observe、episodic summary、reflection、entity extraction 等可选能力。

产品出口有三条：

- **REST API**：Axum 路由，默认由 `memoria serve` 提供。
- **MCP**：Rust MCP server，支持 stdio、SSE，以及通过 REST API 的 remote/HTTP 桥接。
- **SDK/插件**：`sdk/python` 提供同步/异步 Python SDK；`plugins/openclaw` 将 Memoria 接成 OpenClaw `memory` 插件，支持 embedded 与 API 两种后端。

## 2. 总体文本流程图

```text
AI Agent / OpenClaw / Python SDK / HTTP Client
                 │
                 ├──────── REST/HTTP ────────┐
                 │                            │
                 └──────── MCP stdio/SSE ─────┤
                                              ▼
                                  memoria-cli (serve/mcp)
                                              │
                    ┌─────────────────────────┴─────────────────────────┐
                    │                                                   │
                    ▼                                                   ▼
          memoria-api::build_router()                         memoria-mcp::server
          Auth / rate limit / routes                            JSON-RPC tools/list/call
                    │                                                   │
                    └─────────────────────────┬─────────────────────────┘
                                              ▼
                                  memoria-service::MemoryService
                    ┌─────────────────────────┼─────────────────────────┐
                    │                         │                         │
                    ▼                         ▼                         ▼
             retrieve/search            governance/graph          pipeline/LLM
             score + explain            scheduler + plugins       sensitivity → sandbox → persist
                    │                         │                         │
                    └─────────────────────────┬─────────────────────────┘
                                              ▼
                         memoria-core contracts/types/errors
                                              │
              ┌──────────────────────────────┴──────────────────────────────┐
              ▼                                                             ▼
 memoria-storage::SqlMemoryStore / DbRouter                         memoria-git::GitForDataService
 CRUD / hybrid search / schema / graph / pools                      snapshot / branch / diff / merge / rollback
              │                                                             │
              └──────────────────────────────┬──────────────────────────────┘
                                             ▼
                  MatrixOne (MySQL/SQLx; vecf32, fulltext, MVCC/COW data branches)
                                             │
        user memory DBs + shared durable/runtime/auth/plugin/metrics tables
```

### Remote 与 embedded 运行形态

```text
Remote:
Agent ──MCP stdio──> memoria mcp --api-url ... ──HTTP/Bearer──> Memoria REST API ──SQL──> MatrixOne

Embedded:
Agent ──MCP stdio/SSE──> memoria mcp ──MemoryService/SqlMemoryStore──> MatrixOne

OpenClaw:
backend=api      Plugin ──MemoriaHttpTransport/fetch──> REST API
backend=embedded Plugin ──MemoriaMcpSession/spawn──> memoria mcp ──> local MatrixOne
```

## 3. 真实分层与目录地图

仓库根目录还包含 `assets/`、`config/`、`docker-compose*.yml`、`scripts/`、`skills/`、Python SDK 与 OpenClaw 插件；Rust 主工程位于 `memoria/`。

| 层 | 真实目录/文件 | 职责与边界 |
|---|---|---|
| 核心契约层 | `memoria/crates/memoria-core/src/` | `Memory`、`MemoryType`、`TrustTier`、反馈信号、错误枚举、`MemoryStore`/`EmbeddingProvider` trait、敏感度检查。无数据库实现。 |
| 存储与数据库层 | `memoria/crates/memoria-storage/src/store.rs` | SQL CRUD、分页、全文/向量/混合检索、反馈、治理写操作、schema bootstrap/compat migration、pool health、缓存与 edit log。 |
| 多租户路由层 | `memoria/crates/memoria-storage/src/router.rs` | `DbRouter` 管理 shared pool、global user pool、schema init pool、user/group → database 映射和 routed store；multi-db 不是抽象文档而是实际调用路径。 |
| 图/实体存储层 | `memoria/crates/memoria-storage/src/graph/` | `GraphStore`、节点/边类型、实体抽取后的节点与 memory/entity link、激活/回填/整理/检索。 |
| 版本数据操作层 | `memoria/crates/memoria-git/src/service.rs` | 调用 MatrixOne `SHOW SNAPSHOTS`、`CREATE/DROP/RESTORE SNAPSHOT`、`data branch` 相关能力；实现 `GitForDataService` 和 diff/apply 分类结构。 |
| 向量/LLM 提供者层 | `memoria/crates/memoria-embedding/src/` | `EmbeddingProvider` 的 HTTP、round-robin、mock、本地 fastembed实现，以及 `LlmClient`。本地 provider 由 `local-embedding` feature 控制。 |
| 业务服务层 | `memoria/crates/memoria-service/src/service.rs` | `MemoryService` 统一 store/retrieve/search/correct/purge/profile/observe/feedback/branch-aware 操作；组合存储、embedding、LLM 与可选 router。 |
| 治理与策略层 | `governance.rs`、`strategy.rs`、`strategy_domain.rs`、`graph_domains.rs`、`scoring.rs` | 定时治理、冷却/熔断、低置信度隔离、陈旧清理、冗余压缩、图整理、信任生命周期、可插拔 scoring 与自适应参数。 |
| 异步/分布式层 | `distributed.rs`、`scheduler.rs`、`stats_reporter.rs`、`rebuild_worker.rs` | DB-backed lock/task、leader/heartbeat、跨实例治理、操作统计与后台刷写。 |
| 插件治理层 | `memoria-service/src/plugin/`、`plugin_registry.rs` | 插件 manifest、签名与发布仓库、review/score/binding/audit、Rhai sandbox 与 gRPC runtime；gRPC proto 在 `memoria/proto/.../strategy.proto`。 |
| 数据安全流水线层 | `pipeline.rs` | 候选记忆经过 sensitivity block/redact，可选 Git sandbox，再 embedding 与持久化；这是独立 pipeline，不是所有 REST 写入的唯一入口。 |
| REST 出口层 | `memoria/crates/memoria-api/src/` | `build_router` 注册 health、memory、snapshot/branch、governance、sessions、groups、auth、admin、plugin、metrics、MCP HTTP 等路由；middleware 负责认证、scope、rate-limit、日志、metrics、panic catch。 |
| MCP 出口层 | `memoria/crates/memoria-mcp/src/` | JSON-RPC initialize/tools/list/tools/call，核心 tools 与 git tools 分发，stdio/SSE/remote transport。 |
| CLI/启动装配层 | `memoria/crates/memoria-cli/src/main.rs` | `serve`/`mcp` 创建 Config、拓扑探测/迁移、store/router/git/embedder/LLM/service/scheduler/AppState，并启动服务器；另含 init/status/rules/update/benchmark/plugin/migrate。 |
| SDK/宿主适配层 | `sdk/python/`、`plugins/openclaw/` | Python SDK 是 REST typed client；OpenClaw plugin 是 TypeScript tool/hook/config 适配，embedded 模式通过 MCP，API 模式通过 fetch。 |

### workspace 成员

根 Rust workspace `memoria/Cargo.toml`（version `0.4.0`、Rust `1.85`）声明：`memoria-core`、`memoria-storage`、`memoria-embedding`、`memoria-service`、`memoria-git`、`memoria-api`、`memoria-mcp`、`memoria-cli`、`memoria-test-utils`。`memoria/vendor/sqlx-mysql` 是 `[patch.crates-io]` 的本地补丁，用于兼容 MatrixOne 非标准 JSON type code（根 `Cargo.toml` 第 52–57 行）。

## 4. 核心数据流

### 4.1 写入、纠错、删除

```text
请求/工具参数
  → API/MCP 参数校验与 AuthUser scope
  → MemoryService.store_memory* / correct* / purge*
  → embedding（若 provider 可用）
  → 选择 active branch table（main 或物理 branch table）
  → SqlMemoryStore insert/update/soft-delete + mem_edit_log
  → MatrixOne
```

`MemoryService` 负责业务语义。`correct` 不是就地覆盖的单纯 update：测试与 MCP 路径验证为旧 memory 失活、新 memory 建立并通过 `superseded_by` 形成版本链；API 另有 `GET /v1/memories/:id/history` 沿链查询。普通 REST `store_memory` 直接调用 service；`MemoryPipeline` 则显式做 sensitivity 与可选 sandbox 后再写入，故不能把 pipeline 误认为所有入口共用的写入门。

### 4.2 检索

```text
query + scope/session/subject/type/tier/branch/metadata filters
  → API models / SDK 本地校验
  → MemoryService retrieve/search/query
  → embedding query（retrieve/search 的语义路径）
  → SqlMemoryStore vector + fulltext / hybrid SQL
  → feedback/confidence/temporal 参数调整排序
  → retrieval_score + optional explain
  → REST JSON / MCP text(JSON) / SDK dataclasses
```

存在三种有意不同的查询：

- `retrieve/search`：服务层语义检索，支持 embedding、session scope、解释信息。
- `query`：结构化精确过滤，不做 vector/keyword retrieval；要求至少一个 selector。
- `fulltext-search`：纯 MatrixOne full-text + 精确 SQL 预过滤，不生成 embedding、不跑 vector/graph/hybrid/temporal/confidence scoring；storage 与 SDK 共同固定字段限制：metadata 最多 16 项，key 最多 64 bytes，value 最多 1024 bytes，query 最多 4096 UTF-8 bytes，limit 1–100。

### 4.3 Git-for-Data 数据流

```text
snapshot/branch/checkout/diff/pick/apply/merge/rollback
  → memoria-mcp::git_tools 或 memoria-api::routes::snapshots
  → user_sql_store + GitForDataService
  → MatrixOne native snapshot / data branch DDL/DML
  → branch registry / active_branch / snapshot registration / edit log/cache invalidation
```

快照有用户显示名与内部 MatrixOne 名称两套标识，`git_tools.rs` 负责转换、可见性过滤、创建锁、计数与注册；snapshot detail/diff 由 API 对 MatrixOne snapshot time-travel 查询做 JSON 整形。分支是物理表加 `mem_branches` 注册，当前分支写入 `active_table` 指向的表；merge 有 `append` 与 `replace/accept` 路径，`pick` 支持 key list、snapshot range、retrieve selector 及 dry-run。

### 4.4 治理、图与 LLM

```text
scheduler/API/MCP governance trigger
  → cooldown/breaker
  → GovernanceStrategy plan → execute
  → quarantine / stale cleanup / redundancy / graph cleanup / index rebuild / tuning
  → safety snapshot + mem_edit_log + summary

observe/session summary/reflect/entity extraction
  → LlmClient（可选）或 candidates/no-LLM fallback
  → service store / GraphStore entity upsert + memory links
```

治理 trait 在 `governance.rs` 中将 plan 与 execute 分开，并通过 `GovernanceStore` 抽象 SQL 操作。`scoring.rs` 的默认插件用 useful/irrelevant/outdated/wrong 反馈调节排序，累计至少 10 条反馈后才自动调参。

## 5. 关键类、函数、trait、数据模型与路径

以下均为源码中实际存在的公开或架构关键符号；路径均相对仓库根。

| 符号 | 相对路径 | 作用 |
|---|---|---|
| `MemoryType` / `TrustTier` / `Memory` | `memoria/crates/memoria-core/src/types.rs` | 6 种 memory type；T1–T4 信任级别及默认半衰期/初始置信度；记忆主记录（身份、scope、content、embedding、source events、active、session、metadata、subject、score）。 |
| `MemoriaError` | `memoria/crates/memoria-core/src/error.rs` | Invalid/NotFound/Database/Embedding/Validation/Blocked 等跨层错误。 |
| `MemoryStore` / `EmbeddingProvider` | `memoria/crates/memoria-core/src/interfaces.rs` | 核心存储与 embedding 边界；允许 service 在 mock/in-memory/SQL 实现间测试。 |
| `SqlMemoryStore` | `memoria/crates/memoria-storage/src/store.rs` | MySQL/MatrixOne 主存储实现；pool、embedding dimension、db routing、缓存、schema、CRUD、检索、治理和日志。 |
| `DbRouter` / `UserDatabaseRecord` | `memoria/crates/memoria-storage/src/router.rs` | shared registry 与 user/group database 路由；`scope_store` 对 `grp_` group 与 user scope 分流。 |
| `GraphStore` / `GraphNode` / `GraphEdge` | `memoria/crates/memoria-storage/src/graph/` | 图节点/边、实体、记忆链接、图检索与整理。 |
| `plan_legacy_single_db_to_multi_db` / `execute_legacy_single_db_to_multi_db` | `memoria/crates/memoria-storage/src/migration.rs` | legacy single DB 到 shared + per-user DB 的 dry-run/execute 迁移；执行前创建 account snapshot，并输出结构化 report。 |
| `MemoryService` | `memoria/crates/memoria-service/src/service.rs` | 业务主入口；维护 store/embedder/LLM/sql/router，提供 store/retrieve/search/correct/purge/observe/feedback/branch-aware API。 |
| `MemoryPipeline` / `PipelineResult` | `memoria/crates/memoria-service/src/pipeline.rs` | sensitivity → optional sandbox → embedding/persist 三阶段流水线。 |
| `DefaultGovernanceStrategy` / `GovernanceStore` | `memoria/crates/memoria-service/src/governance.rs` | 治理计划、执行、清理、隔离、快照、审计与多 DB fan-out。 |
| `DefaultScoringPlugin` / `ScoringPlugin` | `memoria/crates/memoria-service/src/scoring.rs` | 反馈修正基础分及自动调节用户 retrieval 参数。 |
| `GovernanceScheduler` / `DistributedLock` / `AsyncTaskStore` | `memoria/crates/memoria-service/src/scheduler.rs`, `distributed.rs` | 周期任务、leader election、心跳、跨实例任务可见性。 |
| `PluginManifest` / `PluginRepository` 相关函数 / `RhaiGovernanceStrategy` / `GrpcGovernanceStrategy` | `memoria/crates/memoria-service/src/plugin/` | 插件签名、发布、审查、评分、绑定、运行时与审计。 |
| `GitForDataService` / `Snapshot` / `ClassifiedDiff` | `memoria/crates/memoria-git/src/service.rs` | MatrixOne snapshot/branch 操作及 diff 分类/apply 数据结构。 |
| `build_router` / `AppState` | `memoria/crates/memoria-api/src/lib.rs`, `state.rs` | REST 路由总装配；服务、git、auth pool、缓存、rate limiter、batcher、metrics、task store 的共享状态。 |
| `AuthUser` / actor scope middleware | `memoria/crates/memoria-api/src/auth.rs` | Bearer/API key/master/group scope 与 group main-write/merge guard。 |
| route handlers | `memoria/crates/memoria-api/src/routes/{memory,snapshots,governance,sessions,groups,plugins,admin}.rs` | HTTP 参数契约、状态码、scope 处理、service/git 调用及响应映射。 |
| `dispatch_http` / `run_stdio` / `run_sse` / `run_stdio_remote` | `memoria/crates/memoria-mcp/src/server.rs` | MCP JSON-RPC、embedded/remote、stdio/SSE transport。 |
| `tools::list/call` / `git_tools::list/call` | `memoria/crates/memoria-mcp/src/tools.rs`, `git_tools.rs` | MCP 工具 schema 与工具分发；核心 memory/governance/graph 与 Git-for-Data 工具分开。 |
| `Config::from_env` | `memoria/crates/memoria-service/src/config.rs` | DB、multi-db、embedding、LLM、用户、plugin、instance、lock、ops metrics 环境配置。 |
| `main` / `cmd_serve` / `cmd_mcp` | `memoria/crates/memoria-cli/src/main.rs` | CLI 解析与运行时装配；`serve` 默认 8100，MCP stdio 默认或 SSE 默认 8200。 |

## 6. 数据模型与数据库边界

### 6.1 用户记忆数据库

`SqlMemoryStore::bootstrap_user_schema`（`memoria/crates/memoria-storage/src/store.rs`）实际创建/维护的核心表包括：

- `mem_memories`：memory 主表，`memory_id` 主键；`user_id`、`author_id`、`subject_id`、`memory_type`、`content`、`vecf32(embedding_dim)`、`session_id`、`source_event_ids`、`extra_metadata`、`is_active`、`superseded_by`、`trust_tier`、`initial_confidence`、`observed_at/created_at/updated_at`，并有 active/session/observed/author/subject 索引与 fulltext index。
- `mem_user_state`：每个用户 active branch。
- `mem_branches`：branch 名与物理表名、状态、创建时间。
- `mem_snapshots`：显示名/内部 snapshot 名、extra memory count、状态。
- `mem_memories_stats`：访问次数与四类 feedback 计数。
- `mem_edit_log`：操作、payload、reason、snapshot_before、actor/created time。
- `mem_retrieval_feedback`、`mem_user_retrieval_params`、`mem_governance_cooldown`、`mem_tool_usage`、`mem_api_call_log`：反馈、自适应排序、治理冷却、工具使用及 API 调用统计。
- 图相关：`memory_graph_nodes`、`memory_graph_edges`、`mem_entities`、`mem_memory_entity_links`、`mem_entity_links`（实际表名/字段由 `graph/` 与 bootstrap/compat migration 共同维护）。

### 6.2 shared database 与 multi-db

`DbRouter` 实际维护 shared pool、global user pool、user schema init pool；shared 侧包含 user/group registry、auth key、plugin repository/signers/bindings/reviews/audit、distributed locks/tasks 与服务统计表。用户 memory 通过 user ID 哈希成 `mem_u_<sha256前8字节hex>` 数据库名；group ID 通过 `mem_groups` 指向 group DB。

配置通过 `MEMORIA_MULTI_DB`、`MEMORIA_SHARED_DATABASE_URL` 等变量选择拓扑。CLI 在 `cmd_serve`/`cmd_mcp` 启动时先调用 `detect_runtime_topology`；检测到 pending legacy migration 时自动执行迁移再进入 multi-db。迁移工具自身也支持 dry-run 与 `--execute`，并对 legacy active snapshots 设有执行前置约束。

### 6.3 版本与一致性语义

- 记忆纠错保留旧记录并用 `superseded_by` 链表示替代关系。
- delete/purge 多数路径是 soft delete (`is_active`)，治理还会物理清理陈旧/隔离数据；应区分“用户可见删除”与“数据库物理删除”。
- snapshot/branch 使用 MatrixOne 原生 COW/MVCC 能力，branch 主要体现为物理数据表与注册表，rollback 是恢复 snapshot，而不是覆盖历史版本文件。
- `mem_edit_log`、snapshot_before、stats/metrics batcher 是审计/运营辅助路径，不能等同于完整事件溯源日志。

## 7. API、CLI、SDK 与插件接口

### 7.1 REST API

`memoria-api/src/lib.rs::build_router` 实际注册的接口族：

| 接口族 | 主要路径 | 说明 |
|---|---|---|
| 健康/指标 | `/health`、`/health/instance`、`/metrics` | liveness、DB readiness/instance、Prometheus。 |
| 记忆 | `/v1/memories`、`/query`、`/fulltext-search`、`/retrieve`、`/search`、`/:id`、`/:id/history` | CRUD、三类检索、纠错、分页、反馈、pipeline。 |
| 会话/任务 | `/v1/observe`、`/v1/sessions/:session_id/summary`、`/v1/tasks/:task_id` | observe 与同步/异步 episodic summary。 |
| Git-for-Data | `/v1/snapshots*`、`/v1/branches*` | snapshot、diff、rollback、branch、checkout、merge、pick/apply、删除。 |
| 治理/图 | `/v1/governance`、`/v1/consolidate`、`/v1/reflect`、`/v1/extract-entities*`、`/v1/entities` | cooldown、LLM/candidates、entity graph。 |
| auth/group | `/auth/keys*`、`/v1/groups*` | API key 生命周期与 group/members。 |
| admin/plugin | `/admin/*`、`/admin/plugins/*` | 管理统计、用户、触发治理、插件仓库与绑定。 |
| HTTP MCP | `POST /mcp` | Streamable HTTP MCP JSON-RPC。 |

默认认证边界为 Bearer/API key；`MASTER_KEY` 为空时 `AppState::new` 明确记录 open mode 风险，admin endpoints 可能无认证。group 模式对 main 写入与 native merge 有 middleware guard。

### 7.2 CLI

`memoria-cli/src/main.rs` 的 `Commands` 实际包含：

- `serve`：启动 REST API；`--port` 默认 8100。
- `mcp`：embedded 或 `--api-url` remote；`--transport stdio|sse`，SSE 默认 `MCP_PORT=8200`。
- `init`、`status`、`rules`：为 Kiro/Cursor/Claude/Codex/Gemini 等写配置与 steering rules。
- `update`、`benchmark`、`plugin ...`：更新、基准、插件 init/dev-keygen/publish/list/activate/review/score/matrix/events/rules。
- `migrate legacy-to-multi-db`：legacy 单库迁移 dry-run/execute，支持用户筛选、并发与 JSON report。

根 `Makefile` 的真实开发入口为 `make up`（Docker MatrixOne+API）、`make dev`、`make build`/`build-local`、`make check`、`make test*`、`make python-sdk-test*`；本轮未执行这些命令。

### 7.3 Python SDK

`sdk/python/src/memoria/client.py` 提供 `MemoriaClient` 与 `AsyncMemoriaClient`，底层 `httpx`，以资源对象暴露：`memories`、`snapshots`、`branches`、`profile`、`governance`，并提供 `ping`/`observe`。`models.py` 使用无 Pydantic 的 dataclasses（`Memory`、`MemoryPage`、`RetrieveResult`、`PurgeResult`、`Snapshot`、`Branch`、`ApplyResult`、`Profile`、`GovernanceResult`、`ObserveResult`），`_http.py` 负责 HTTP 错误映射/重试/连接。

SDK 的 pyproject 实际要求 Python >=3.10、运行依赖 `httpx>=0.27`；dev 依赖 pytest、pytest-httpx、pytest-asyncio、anyio、ruff、mypy、build、twine。SDK 本地会复制/校验部分 server 契约常量，尤其是 memory types、fulltext 与 structured metadata 限制。

### 7.4 OpenClaw 插件

`plugins/openclaw/openclaw/index.ts` 注册 OpenClaw memory plugin、prompt guidance、tool surface 与命令 aliases；`client.ts` 以 userId 为 session key，统一解析 Rust MCP 文本/JSON，并缓存最近 memory。配置在 `config.ts`，API transport 在 `http-client.ts`，embedded transport 通过 `memoria` binary/MCP session（README 说明）。插件工具覆盖 search/get/store/retrieve/list/stats/profile/correct/purge/forget/health/observe/governance/consolidate/reflect/entities/snapshot/branch 等。

`plugins/openclaw/package.json` 表明 Node >=22、TypeScript、Vitest、OpenClaw peer >=2026.3.0；npm 包为 `@matrixorigin/thememoria`。插件自身对 Rust MCP 结果存在明确适配限制，例如 `memory_get` 通过最近结果与 bounded scan 兜底，stats 对 inactive/entity totals 可能是 partial。

## 8. 技术栈与构建链

| 范畴 | 实际技术 |
|---|---|
| 后端语言/构建 | Rust 2021，Cargo workspace，最低 Rust `1.85`；CLI binary `memoria`。 |
| 异步/HTTP | Tokio 1.40、Axum 0.7、Tower/Tower-HTTP、Reqwest 0.12。 |
| 数据访问 | SQLx 0.8 MySQL runtime-tokio + rustls；本地 `vendor/sqlx-mysql` patch 适配 MatrixOne。 |
| 数据库 | MatrixOne，使用 MySQL 协议、`vecf32`、fulltext、snapshot、data branch、MVCC/COW；Docker compose 负责本地部署。 |
| 序列化/错误/观测 | Serde/serde_json、thiserror/anyhow、tracing、OpenTelemetry OTLP 可选 feature。 |
| 向量/LLM | OpenAI-compatible embedding/LLM HTTP；fastembed 可选本地 embedding；round-robin 多 endpoint。 |
| 插件运行时 | Rhai sandbox；Tonic/Prost gRPC；Ed25519 签名；semver。proto 编译由 `memoria-service/build.rs` 使用 vendored protoc。 |
| Python | Python >=3.10、httpx、Hatchling 打包；pytest/ruff/mypy 等开发工具。 |
| OpenClaw | TypeScript/Node >=22、Vitest，OpenClaw plugin SDK peer dependency。 |
| 运维 | Docker Compose、Prometheus/Grafana 配置、shell 安装脚本；Kubernetes/deployment 文档存在但本轮未逐文件审查。 |

## 9. 测试布局与验证方式

本轮只读取测试，未执行测试、未启动数据库或服务。测试命令与测试文件中明确依赖 MatrixOne 的行为如下：

- **core/service 单元**：`memoria-core` 内置 tests；`memoria-service/tests/service_unit.rs` 使用 `MockStore`、`MockEmbedder` 验证 store/retrieve/correct/purge、六类 memory type、四类 trust tier、无 embedder 与 edit-log buffer。
- **storage 集成**：`memoria-storage/tests/store_crud.rs` 连接真实 MatrixOne，验证 CRUD、soft delete、全文/向量/混合检索、字段 round-trip、metadata、entity link；`branch_ops.rs` 验证 active branch table、branch 写入隔离、merge、回退与显式列名规避 MatrixOne `vecf32`/`INSERT IGNORE SELECT *` 问题。
- **service/plugin/governance 集成**：`memoria-service/tests/` 含 `plugin_repository.rs`、`plugin_contract.rs`、`subject_id_filter.rs`、`governance_pool_budget_e2e.rs` 等。
- **MCP**：`memoria-mcp/tests/tools_unit.rs` 及 `core_tools_e2e.rs`、`mcp_e2e.rs`、`snapshot_e2e.rs`、`branch_e2e.rs`、`graph_e2e.rs`、`feedback_e2e.rs`、`edit_log_e2e.rs`、`integration_full.rs`、`perf_optimizations_e2e.rs`；snapshot/branch 相关测试要求串行运行，测试验证 MCP text 输出与 DB 状态。
- **REST API**：`memoria-api/tests/api_e2e.rs`、`api_db_verify.rs`、`api_multi_db_routing.rs`、`api_multi_db_purge.rs`、`group_collab_api.rs`、`subject_isolation_e2e.rs`、pool isolation/budget tests；通过随机端口启动真实 Axum server，使用 reqwest 验证 HTTP 状态码、auth header/scope、metadata、structured/fulltext filters、cursor、branch、session/subject isolation。
- **Python SDK**：`sdk/python/tests/unit/` 覆盖 memories、async memories、snapshots、branches、governance、errors；`pytest-httpx` mock HTTP；`tests/integration/test_e2e.py` 需要真实 API，集成 README 与根 Makefile 要求先 `make up`。
- **OpenClaw**：`plugins/openclaw/openclaw/__tests__/` 的 config/client/format/http-client/parser 测试用 Vitest；已读取的 client 测试验证 API transport、按 userId session reuse、health 与 close，config 测试验证默认 embedded、API 配置、环境变量与范围校验。

官方脚本口径：根 `Makefile` 的 `make check` 是 `cargo check` + `cargo clippy -- -D warnings`；`make test-unit` 不需 DB；storage/API/MCP E2E 需要 MatrixOne 与 `DATABASE_URL`，snapshot/branch 需串行；Python SDK unit 无 API，integration 需要服务；OpenClaw 使用 `npm test`/Vitest。测试设计存在真实外部能力依赖，不能仅以编译通过替代 E2E 证明。

## 10. 已确认与未确认项/风险

### 已确认

1. 当前 commit 为 `efd3d65`（`feat: restore filtered fulltext memory search (#232)`）；当前工作树已有未跟踪的 `细探-Memoria.md`，本轮未改动它。
2. Rust workspace、Python SDK、OpenClaw plugin 的入口与依赖均已实际读取；仓库内未发现 `AGENTS.md` 或 `CLAUDE.md`，因此没有项目级代理规则可补充。
3. `README.md` 的总体定位、运行模式、工具名与 CLI 名称，已用真实 route、MCP dispatch、CLI `Commands` 与 plugin source 交叉核对；本文件对“真实分层”优先按源码模块边界描述。
4. 根目录没有既有 `ARCHITECTURE.md`；本轮新建本文件作为唯一正式架构文档。

### 未确认/需要后续审查

- 本轮没有运行 `cargo check/test`、clippy、Python pytest、Vitest，也没有连接 MatrixOne；因此没有对当前依赖锁、SQLx offline metadata、MatrixOne 版本兼容或 E2E 绿状态做结论。
- `memoria-storage/src/store.rs` 体量很大，包含 schema bootstrap、compat migration、CRUD、检索、治理与大量缓存/运维逻辑；本轮建立边界但没有逐函数审计所有 SQL、事务边界、DDL 并发与回滚语义。
- 多 DB 自动迁移会在 serve/mcp 启动路径执行真实数据库探测与可能的 legacy migration；生产启动是否应自动迁移、备份/恢复窗口与权限边界需要部署级复核。
- MatrixOne 原生 snapshot/data branch/`vecf32`/fulltext 语义依赖具体 MatrixOne 版本；源码和测试包含版本差异/workaround，但本轮未实测目标版本。
- API 认证既支持 master/Bearer/API key，也允许 `MASTER_KEY` 为空进入 open mode；部署是否始终显式设置密钥、admin 与 group policy 是否满足目标安全要求，需安全审计。
- `MemoryPipeline` 是可选 REST pipeline，普通写入/observe/reflect 等入口各自存在；敏感度过滤、审计、快照保护是否覆盖每一种 destructive path，需进一步做入口矩阵审计。
- REST、MCP、Python SDK、OpenClaw 对返回形状有多处文本/JSON/partial 兼容层；尤其 OpenClaw embedded 模式依赖 Rust MCP 文本解析，接口漂移风险需用跨出口契约测试持续验证。
- 插件系统含签名、review、score、binding、Rhai 与 gRPC 多运行时；本轮只确认模块与 proto 边界，未核查信任根、沙箱权限、远程 endpoint、升级/回滚的完整安全模型。
- `skills/`、deployment/Kubernetes 文档、Docker/Grafana/Prometheus 配置、安装脚本未全部逐文件审查；本文仅记录已读取 README、架构/API skill、Makefile、核心源码与代表性测试所得结论。

## 11. 本轮实际读取清单（摘要）

- 根文档：`README.md`；未发现 `AGENTS.md`/`CLAUDE.md`。
- 依赖/构建：`memoria/Cargo.toml`、9 个 crate `Cargo.toml`、根 `Makefile`、`memoria/Makefile`、`memoria-service/build.rs`、`proto/.../strategy.proto`、`sdk/python/pyproject.toml`、`plugins/openclaw/package.json`。
- 入口/核心实现：`memoria-core` types/interfaces/error/lib；`memoria-storage` lib/store/router/migration/graph 入口；`memoria-service` lib/config/service/governance/scoring/pipeline；`memoria-git` lib/service；`memoria-api` lib/state/routes；`memoria-mcp` lib/server/tools/git_tools；`memoria-cli/src/main.rs`；embedding lib/http/local。
- SDK/插件：Python `client.py`、`models.py`、`resources/memories.py`、README；OpenClaw `README.md`、`openclaw/client.ts`、`index.ts`、package manifest、代表性 Vitest tests。
- 测试：storage CRUD/branch，service unit，MCP core tools E2E，API E2E，Python SDK memories unit，OpenClaw client/config unit，以及测试目录清单。

---

**文档状态：首轮全量架构建档。本文已吸收此前 `细探-Memoria.md` 的源码分析结论；后续只维护本文件，旧细探笔记不再作为独立事实源。未宣称运行验证通过。**

---

## 12. 第三轮：通用底座映射与裁决

### 12.1 本轮边界、证据等级与命名

本轮不是把 Memoria 的目录直接改造成平台目录，而是回答“哪些机制可以进入公共底座、哪些仍属于记忆领域、哪些只能进入制品/证据治理，以及迁移前必须保留的失败语义是什么”。本节只增量维护本文件；没有修改 Memoria 源码、依赖、配置、测试或 Git。

本轮证据优先级如下：

1. 当前工作树源码与 SQL schema；
2. 当前工作树测试源码、RFC、README/API 文档；
3. 本轮现场命令结果；
4. 旧细探材料（仅作线索，不能覆盖源码）。

现场事实：目标根目录为 `~/Documents/Agent/github 源码参考/05_个人自我蒸馏参考/02_长期记忆与记忆操作系统/Memoria`；首次 `project_context` 错绑到 `华世王镞_v3`（返回根目录 `~/Documents/Agent/PHP/华世王镞_v3`），不能作为 Memoria 的项目身份或代码图证据。随后对明确 Memoria 路径调用 `codegraph_explore`，结果为“未发现 `.codegraph/`，无法查询”；因此本轮所有源码事实均来自直接读取，不能声称有代码图佐证。根目录当前只有 `ARCHITECTURE.md` 被 Git 标记为未跟踪；预期的根目录 `细探-Memoria.md` 当前现场未找到，不能宣称对旧细探做了本轮逐文件复核或删除。

为避免把“源码存在”写成“平台已接入”，本轮使用以下判断：

- **源码事实**：实现、字段、调用链或测试源码中可直接定位；
- **可吸收模式**：抽象边界和失败/资源语义有足够证据，可作为平台候选，但不表示已经迁入；
- **项目特有语义**：必须保留在记忆模块或项目适配层，公共底座不能理解其业务含义；
- **待核**：只有声明、RFC、局部测试或未运行的外部依赖证据，不能升级为生产契约；
- **废弃/隔离**：与公共底座的单一 owner、原子性、可取消或证据完整性铁律冲突，先隔离而不是复制实现。

### 12.2 通用目标分层：公共契约、记忆模块、运行核心、制品/证据治理

```text
上层 Agent / SDK / 插件 / 管理 UI
              │ 只提交带版本、范围、幂等键的公开命令
              ▼
公共契约层：EventEnvelope / MemoryRevision / Query / Snapshot / Release
              │ 统一结果、错误、取消、超时、证据引用与资源责任
              ▼
记忆模块：记忆写入/纠错/软删除、图整理、信任层、检索、治理策略
              │ 只表达记忆领域语义；不自建第二套任务、发布或审计中心
              ▼
运行核心：监督执行、超时/取消/崩溃回收、租约/锁、连接池、事务与原子切换
              │ 对外部数据库、embedding/LLM、插件 runtime 和后台任务设预算
              ▼
制品/证据治理：不可变包、签名/审核、快照索引、事件/审计账本、回滚证据
              │ 记录“谁在何时以哪个版本对哪个范围做了什么、结果如何”
              ▼
MatrixOne / 外部提供者 / Rhai 或 gRPC 插件 / HTTP embedding 与 LLM
```

这四层不是 Memoria 现有四个目录的机械对应。Memoria 的 `memoria-core` 适合贡献一部分公共类型，但 `Memory`、`TrustTier`、`superseded_by`、`MemoryStore` 仍是记忆域；`memoria-service` 同时混合了领域编排、后台任务和治理策略；`memoria-storage` 同时承担数据库适配、索引、审计写入与缓存；`memoria-git` 是数据库特有的版本操作提供者。平台吸收时应按“契约 owner + 运行责任 + 证据责任”重新归位，不能按 crate 名称搬运。

### 12.3 事件与记忆版本：可复用外壳，保留记忆特有血缘

#### 12.3.1 当前源码事实

| 主题 | 当前实现证据 | 第三轮判断 |
|---|---|---|
| 记忆主记录 | `memoria/crates/memoria-core/src/types.rs::Memory`；字段含 `memory_id`、scope/user/author/subject、content、embedding、`source_event_ids`、`superseded_by`、`is_active`、trust、时间戳 | `Memory` 是记忆域实体，不应成为公共事件类型 |
| 记忆类型 | `MemoryType` 固定六种：semantic、working、episodic、profile、tool_result、procedural | 类型枚举属于记忆模块；公共契约只应承载可扩展的领域类型标识 |
| 事实可信度 | `TrustTier` T1–T4，并由 tier 给出初始置信度/半衰期 | 可信度/衰减是记忆策略，不是通用发布状态 |
| 新版本 | `MemoryService::correct_on_branch` 用 UUID v7 生成新 `memory_id`，新记录 `source_event_ids = ["correct:<old_id>"]`，旧记录通过 `supersede_memory` 失活并指向新记录 | 可吸收“不可变新 revision + 显式 predecessor/supersedes”模式；`correct:<id>` 字符串约定不能直接当公共事件协议 |
| 普通写入/去重 | `store_memory_with_metadata_on_branch` 生成 UUID v7；近重复内容会插入新记录并 supersede 旧记录；同内容近重复则返回实际幸存记录；源码明确标注 dedup check/insert 竞态 TODO | 记忆模块保留去重与矛盾区分；运行核心必须补幂等/CAS 或将竞态标为待核 |
| 删除 | `soft_delete`/`is_active` 是用户可见删除；治理另有物理清理 | 公共契约必须区分 deactivate、purge、physical cleanup，禁止统一叫 delete |
| 事件/审计 | `source_event_ids` 是 `JSON NOT NULL` 字段；`mem_edit_log` 是单独审计表，字段含操作、payload、reason、snapshot_before、actor/time | 当前没有完整、不可丢失、可重放的事件溯源实现，不能声称“事件源系统” |

#### 12.3.2 建议吸收的公共契约

平台可新增/复用以下概念，但必须由一个公共契约 owner 定义：

```text
EventEnvelope {
  event_id, event_type, schema_version,
  occurred_at, actor, scope, subject,
  correlation_id, causation_id, idempotency_key,
  payload, payload_digest, outcome, evidence_refs
}

MemoryRevision {
  memory_id, lineage_id, revision_no,
  predecessor_ids, supersedes_ids,
  state(active|inactive|quarantined|purged),
  domain_type, scope, content_ref, source_event_refs,
  created_at, observed_at, actor, schema_version
}
```

必须固定的行为是：事件 id/幂等键可重试；revision 不原地覆盖历史；所有跨边界写入返回 operation id；结果带稳定错误码和可重试性；事件、revision、审计证据的关联能通过 `correlation_id/causation_id` 或显式引用读回。事件 payload 不能把 embedding、敏感原文和大制品无界塞进公共账本，应使用内容摘要/受控制品引用。

#### 12.3.3 记忆模块特有语义

以下不能上提为通用底座语义：六种 `MemoryType`、T1–T4 trust tier、置信度指数衰减、`source_event_ids` 的业务解释、`correct:<old_id>` 命名、subject/session 过滤、近重复阈值 0.3162、实体图链接以及“新记忆替代旧记忆”的产品语义。平台只提供版本/事件容器、状态与证据关联；记忆模块负责把这些容器解释为“记忆纠错”“观察事件”“图实体更新”。

当前仍需补强：纠错源码在 `service.rs` 明确写有“同一 memory_id 并发 correct 可能生成重复新记忆”的 TODO；因此该链路最多是“版本链模式可吸收、并发一致性待核”，不是可直接升级的原子 revision 契约。

### 12.4 Git 式快照、分支、diff、merge、rollback 的底座落点

#### 12.4.1 真实实现拆解

```text
REST / MCP snapshot 或 branch 命令
  → memoria-api routes/snapshots.rs 或 memoria-mcp/git_tools.rs
  → user_sql_store(scope) + GitForDataService
  → MatrixOne CREATE/DROP/RESTORE SNAPSHOT 或 data branch DDL
  → mem_snapshots / mem_branches / mem_user_state 注册与 active table
  → diff 分类 / selective_apply / edit log / cache invalidation
```

- `memoria-git/src/service.rs::GitForDataService` 对 snapshot/branch 使用 MatrixOne 原生 DDL；snapshot 是数据库级/账户级时间点，branch 是表级零拷贝分支；实际用户隔离、内部名与显示名由 `mem_snapshots`、`mem_branches`、`mem_user_state` 配合维护。
- `create_snapshot`/`drop_snapshot`/`create_branch`/`merge_branch`/`pick_*`/`diff_branch_rows`/`selective_apply` 均验证标识符；branch 名应为内部生成值。MatrixOne DDL 遇错误 20631 会在 `exec_ddl` 中最多三次、100/200ms 退避重试；diff 的 `columns (...)` 不兼容时进程内降级到全行查询。
- `classify_diff_rows` 以 `is_active` 与 `superseded_by` 分类 ADDED/UPDATED/REMOVED/CONFLICTS，并区分 `behind_main`、`ghost_removes`；`selective_apply` 对 branch/main 做存在性核验、冲突策略（fail/skip/accept）和事务内 apply，但部分 branch 读故意绕过事务连接以规避 MatrixOne 零拷贝可见性问题。
- `restore_table_from_snapshot` 的真实语义是先 `DELETE` 当前表，再 `INSERT ... SELECT ... {SNAPSHOT=...}`；源码明确写明 DELETE+INSERT 非原子、调用者应先建 safety snapshot，且并发 restore 需串行化以规避 MatrixOne 已知问题。它不是平台意义上的自动原子回滚。
- 治理 `create_safety_snapshot`、purge 路径和周期开启的 snapshot retention 共同形成“破坏前留快照、破坏后可恢复”的模式；但每用户 DB 的 multi-db safety snapshot 需要逐库恢复，不是单个全局回滚点。

#### 12.4.2 公共契约应吸收什么

| 公共能力候选 | 应固定的契约 | Memoria 适配层保留的语义 |
|---|---|---|
| Snapshot | `create/list/get/delete/read_at`；scope、source revision、retention、immutable id、digest、创建 operation/evidence | MatrixOne `SHOW SNAPSHOTS` 列名大小写差异、snapshot 显示名与内部名、数据库级范围 |
| Branch | `create/checkout/list/delete`；parent snapshot/revision、owner、active pointer、生命周期 | 物理 branch table、`active_branch`、user/group routing、内部 UUID hex 名 |
| Diff | 有界窗口、source/target、分类、conflict、ghost/no-op、dry-run、解释 | MatrixOne flag 版本差异、`is_active/superseded_by` 分类、LCA/branch 行来源 |
| Apply/Merge | 幂等 operation、selection、conflict policy、预检、部分结果、重试/回滚证据 | add/update/remove/accept_branch_conflicts 的记忆 id 列表与“替代链”更新 |
| Rollback | 明确 restore scope、前置 safety point、是否 destructive、原子性等级、恢复后校验 | `DELETE+INSERT` 表恢复、MatrixOne snapshot syntax、每用户 DB 分步恢复 |

公共快照句柄不能只存一个字符串名；至少要带 `snapshot_id`、scope/database、parent/created revision、状态、保留策略、创建者和证据引用。公共 rollback 结果必须明确“目标已切换、目标未切换已回滚、恢复部分失败、恢复不可验证”四态，不能把数据库返回成功当作恢复完成。

#### 12.4.3 项目特有语义与隔离项

MatrixOne 的 snapshot/data branch、COW/MVCC、`vecf32`、fulltext index、DDL 20631/23860/23861 workaround 是提供者适配语义；平台只接收标准 snapshot/branch provider，不应在运行核心复制 SQL 方言。`memoria-git` 目前的 rollback、merge 和 diff 依赖具体 MatrixOne 版本，且 RFC 中“已对真实 MatrixOne 验证”与本轮未运行现场不等价；因此 runtime readiness 仍为待核。

### 12.5 审核、审计、证据账本：两条链不可混为一谈

#### 12.5.1 记忆编辑审计链

`mem_edit_log` schema 有 `edit_id/user_id/memory_id/operation/payload/reason/snapshot_before/created_by/created_at`，服务层通过 `send_edit_log` 异步发送；`SqlMemoryStore::log_edit` 在 buffer 满时会记录 warning 并直接丢弃 entry，channel closed 才 fallback 到 direct INSERT。该实现适合“运营审计辅助”，不满足“拒绝也必须留痕、不可丢、可重放”的平台证据账本要求。

可吸收：操作前 safety snapshot 引用、操作/原因/actor/scope、逐 memory 关联、批量 operation、异步刷写与 direct fallback 的性能思路。必须改造成公共治理能力后再使用：写入必须有 operation id；buffer backpressure 不能静默丢证据；失败/拒绝/超时/取消/崩溃均需 durable outcome；证据写入与业务状态至少有明确的一致性级别和补偿扫描。

项目特有：`inject`、`correct`、`purge`、`governance:quarantine`、`governance:cleanup_stale` 等 operation 名，以及 `snapshot_before` 指向记忆安全快照，是记忆审计语义；平台账本只保存类型化 operation 和引用，不解释“quarantine”是否改变 trust tier。

#### 12.5.2 插件发布审核链

`memoria-service/src/plugin/repository.rs` 与 `routes/plugins.rs` 实现另一条明确的制品链：

```text
package directory
  → load_plugin_package：manifest/schema/compatibility/permission/limits/integrity/signature
  → sha256 + trusted signer 校验
  → mem_plugin_packages：不可变 plugin_key+version+payload
  → mem_plugin_reviews：pending/active/rejected + score/notes/reviewer
  → binding rule：exact/semver + rollout_percent + subject/domain
  → runtime load/execute + mem_plugin_audit_events
```

正式 publish 对同一 `plugin_key@version` 的不同摘要/签名/签名人拒绝；相同制品幂等返回；非 dev 模式先进入 pending review；review、score、publish、binding 会写 plugin audit event。Rhai runtime 通过 manifest 宣布 capabilities、权限、timeout、memory/output limits，并在超限或执行失败时返回 `Blocked`，scheduler 可降级到默认策略并打开共享 breaker。

可吸收：内容寻址/不可变版本、签名与信任根、审核状态机、兼容范围、绑定/灰度、运行时预算、审计事件、失败降级。该链可以作为“制品治理”候选，不应直接复用为“记忆发布”——记忆内容不是插件包，记忆快照的回滚/合并具有不同的原子性与 scope。

审核缺口：需要核对生产策略是否始终 `enforce_signatures=true`、签名公钥来源是否独立可信、binding 激活与 runtime cache 是否原子、审核拒绝是否覆盖所有 destructive memory 操作；本轮未启动服务或读取生产数据库，不能升级为已验证安全结论。

### 12.6 检索：公共查询契约 + 记忆域排序模块 + 运行资源监督

#### 12.6.1 当前检索调用链

`MemoryService::retrieve_inner` 的 SQL 路径是分阶段 fallback：

```text
query + scope/session/subject/type filters
  → embed(query)；embedding 失败时不立即抛错而进入无 embedding 路径
  → 无约束主表尝试 Graph ActivationRetriever
  → graph 命中不足时 hybrid vector+keyword
  → vector/hybrid 无结果时 MatrixOne fulltext
  → feedback_weight / temporal / confidence 调整与排序
  → RetrievalExplain(path, attempted/hit/timing/candidate scores)
```

有严格 session/subject/type 过滤时会跳过 graph；graph 失败也 fall through 到 hybrid；embedding/vector 都无结果时走 fulltext。`MemoryStore` 公共 trait 目前只有 `search_fulltext`、`search_vector`，hybrid、graph、explain、feedback、branch 与 scope 细节仍在 service/storage 扩展接口中。

#### 12.6.2 公共契约落点

公共契约可固定：`RetrievalRequest`（query、scope、filters、top_k、deadline、explain level、consistency/revision point）、`RetrievalResult`（items、score、rank、source path、snapshot/revision、partial/degraded flags）、`RetrievalExplain`（候选阶段、耗时、过滤、fallback、score components）和 `RetrievalEvidence`（query digest、provider/model version、data revision）。

记忆模块负责：memory type/trust/confidence、session/subject 语义、graph activation、feedback weight、temporal decay、近重复与实体图。运行核心负责：embedding/LLM deadline、并发额度、连接池隔离、取消传播、结果/候选/解释大小上限。制品/证据治理负责：记录使用了哪个模型、哪个快照/branch、哪些 fallback 与 partial 结果；不能把用户 query 原文无条件写入审计。

#### 12.6.3 不能误吸收的行为

- embedding 失败被 `unwrap_or(None)` 转为 fallback 是项目容错策略，不等于所有检索都应静默降级；公共契约必须让调用者看见 degraded/partial 原因。
- Graph + hybrid 的最终分数融合、feedback 四信号和 `T1–T4` 衰减是记忆领域排序；不能下沉为通用搜索核心。
- MatrixOne fulltext 的 ngram、`vecf32`、结构化 metadata 限制和 branch table 可见性是 provider 语义。

### 12.7 发布、激活、回滚：插件制品与记忆状态必须分开

| 生命周期 | Memoria 当前实现 | 底座映射 |
|---|---|---|
| 插件制品发布 | `publish_plugin_package` 写不可变 package/payload、初始 pending review，并写 audit | 制品治理：包、摘要、签名、审核状态、版本唯一性 |
| 插件审核/评分 | `review_plugin_package`、`score_plugin_package` 更新 review 与 audit | 制品治理；需公共审核结果/证据契约 |
| 插件激活 | `activate_plugin_binding` → exact/semver binding，支持 rollout_percent、domain/subject | 发布控制面：激活指针/绑定规则；需 CAS、旧版保留与恢复 |
| 记忆提交 | `store_memory`/`correct`/`purge` 直接作用于 main 或 branch；部分入口 pipeline 才有 sensitivity/sandbox | 记忆模块命令；运行核心监督；不能伪装为制品发布 |
| 记忆安全点 | purge/governance 创建 safety snapshot；snapshot registry 另存显示/内部名 | 快照能力 + 证据治理；需关联 operation/actor/scope |
| 记忆回滚 | table restore 为 DELETE+INSERT；branch selective apply 有事务与 skipped/applied 结果 | 运行核心必须补恢复状态机、前后校验、崩溃恢复和幂等 |

公共发布契约至少要有 `prepare → review/approve → activate → verify → complete`，失败转 `rejected/rolled_back/unknown`；激活前必须记录意图，激活指针切换必须原子或明确不可原子。发布后保留旧版本直到引用归零/保留期结束。对于 Memoria，插件版本可走此状态机；记忆数据版本应走 `revision/snapshot/branch/apply` 状态机，两者共用证据、资源监督和回滚报告，但不共用业务 payload。

当前源码没有一个覆盖“package registry + binding + runtime cache + memory snapshot + active branch”的统一发布事务；这应判为待核，不应通过增加第二套发布中心解决。先复用平台唯一发布/回滚 owner，再为 Memoria 写适配器。

### 12.8 失败、超时、取消、崩溃与部分成功矩阵

| 场景 | 当前源码行为 | 可吸收/缺口 |
|---|---|---|
| 非法标识符/参数 | Git DDL 标识符拒绝；pick strategy/empty keys 返回 Validation；API 转 400/Conflict | 吸收稳定错误码、参数前置校验、SQL 标识符白名单；统一错误 envelope 待建 |
| embedding/LLM/provider 失败 | 普通 store/retrieve 依赖 embedding 的入口可能返回错误；retrieve query embedding 失败后 fallback；pipeline 收集 error 并继续处理其他候选 | 吸收 partial/degraded 结果；必须显式区分“跳过候选”与“主操作失败” |
| MatrixOne 瞬态冲突 | `exec_ddl` 对 20631 最多 3 次退避；其他 DB error 直接返回 | 吸收可重试分类与有界退避；重试必须带相同 operation/idempotency 语义 |
| 图检索失败 | `retrieve_inner` 记录阶段耗时后 fallback 到 hybrid/vector/fulltext | 吸收阶段降级，但公共返回需带 degraded path，不静默吞错 |
| 插件超时/输出超限 | Rhai `spawn_blocking` + engine progress + outer `timeout` 返回 Blocked；scheduler 使用 fallback/breaker | 吸收 runtime budget/circuit breaker；timeout 后 blocking 任务是否已停止、资源是否完全回收需实测，当前不能视为强取消 |
| 治理失败 | 每个 strategy operation 多数记录 warning；primary 失败可记录 breaker 并运行 fallback；部分 DB 清理路径有 best-effort warning | 吸收计划/执行分离、fallback、breaker、summary；需 operation-level durable outcome |
| 审计写入失败/拥塞 | `mem_edit_log` 异步 buffer 满时静默丢 entry（有 warning）；direct insert 失败也不让调用者失败 | 这是不能吸收的默认语义；平台证据治理必须阻止静默丢失或标注证据缺口 |
| 回滚中途失败 | table rollback DELETE 成功、INSERT 失败时可能留下空/部分表；源码承认非原子 | 必须隔离为 destructive provider；平台恢复状态机/前后 digest/安全点验证待建 |
| 异步任务超时 | session summary `tokio::spawn` 后只写 processing/completed/failed；没有 deadline/cancel endpoint | 当前为明显缺口；不得映射成平台“可取消任务” |
| 主进程崩溃 | DB locks 依靠 TTL/expired cleanup；async task 可能永久 processing，重启恢复/僵尸扫描未在本轮确认；后台 tokio task随宿主退出 | 运行核心必须有 owner/lease/heartbeat、启动扫描 processing、可恢复/unknown 状态与孤儿清理 |
| 取消 | API/MCP 没有统一 cancellation token；客户端断开与后台任务取消的传播未形成契约 | 判为待核/缺失，不能声称支持取消 |
| 部分 batch 成功 | pipeline 返回 stored/rejected/redacted/errors；selective_apply 返回 applied/skipped 分桶并在事务提交 | 吸收结构化 partial result；公共契约要固定重试/补偿与是否已提交 |
| 版本/数据库不兼容 | MatrixOne snapshot 列大小写兼容、diff columns runtime downgrade；storage 有 compat migrations | 吸收 capability negotiation/provider downgrade evidence；不要把 fallback 当版本兼容完成 |

### 12.9 资源生命周期与责任转移

| 资源 | 创建/持有 | 正常释放 | 失败/超时/取消/崩溃要求 | 当前证据与剩余风险 |
|---|---|---|---|---|
| MatrixOne 主连接池 | `SqlMemoryStore`/`DbRouter` 创建；service 持有 Arc；governance 可创建 isolated background pool | store/service shutdown 时由 pool drop | DDL/查询 deadline、连接断开、进程退出需 drain；崩溃由 DB/锁 TTL 接管 | pool、背景 pool、graph pool 有源码；本轮未实测连接泄漏/停机 drain |
| 治理分布式锁 | `mem_distributed_locks` INSERT IGNORE；holder+TTL 持有，heartbeat renew | task 完成 release；过期行清理 | 任务超时/进程死由 TTL 回收；必须防旧 holder 过期后误释放新 holder | 有 `try_acquire/renew/release`，但 owner fencing token/epoch 未见，需补强 |
| 异步任务记录 | `mem_async_tasks` create 为 processing；后台 `tokio::spawn` 持有 state clone | complete/fail 后治理清理 72h | cancel/deadline/crash 要写 cancelled/abandoned/unknown，并重启扫描 | 当前只有 processing/completed/failed；无 cancel handle，存在永久 processing 风险 |
| snapshot/branch DDL | GitForDataService pool + MatrixOne snapshot/branch；注册表保存内部名 | drop snapshot/branch；weekly retention 清理 | restore 非原子；并发 restore 需串行；crash 后需 reconcile registry vs DB | 已有 cleanup/orphan 分支；未建立统一 lease/operation 状态 |
| edit-log buffer | service/store 共享 channel；调用者只 try_send | flush worker 批量 INSERT；channel closed direct INSERT | buffer 满不可丢；关闭需 drain；崩溃需 outbox/replay | 当前满即 drop，是证据治理阻断项 |
| embedding/LLM HTTP | provider 发起 HTTP；service 等待 future | response/body/connection 由 client 回收 | deadline、cancel、响应上限、provider retry budget；崩溃由进程/连接池清理 | provider trait 只表达 `embed`；完整 deadline/cancel 不在 core trait |
| Rhai/gRPC plugin runtime | Rhai `spawn_blocking`；gRPC runtime/外部 endpoint | JoinHandle/runtime/stream 关闭 | timeout 后中止执行、输出/内存限制、进程崩溃、版本卸载 | Rhai 有限制但 outer timeout 未证明停止 blocking；gRPC 生命周期待核 |
| graph/vector index | graph store/isolated pool；vector rebuild 由治理触发 | rebuild 完成或清理 orphan graph data | rebuild timeout/cancel、旧索引与新索引一致性、崩溃重建 | 有 `rebuild_vector_index`/orphan cleanup；缺统一资源租约和版本标记 |
| 临时/制品 payload | plugin publish 捕获 package payload 并持久化 JSON；sandbox branch 由 pipeline 创建/删除 | branch drop；数据库 retention | publish/review/activate 失败不得泄漏临时目录或激活半成品 | 包不可变与签名有实现；完整临时目录/崩溃清理需实测 |

运行核心迁移时，每类资源都必须显式记录 `creator → owner → transfer → close/release`，并分别验证正常完成、业务失败、超时、主动取消、宿主崩溃五种终态。仅有 Rust RAII/Arc drop 或 `let _ = release()` 不是崩溃恢复证据；必须能从数据库/进程/文件/连接现场读回无界残留是否存在。

### 12.10 L0–L4 映射：从源码事实到平台采用

本项目采用以下研究/采用等级，而不是把 Memoria 的 T1–T4 trust tier 混用为平台成熟度：

| 等级 | 定义 | 必须具备 | Memoria 本轮对应 |
|---|---|---|---|
| **L0 事实** | 只证明源码/字段/入口存在 | 路径、符号、调用链、未运行声明 | `Memory`/`MemoryStore`、snapshot/branch API、plugin package/review 表、retrieval stages、task/lock 表 |
| **L1 契约候选** | 能提炼输入/输出/错误/资源责任，但未证明跨实现稳定 | 请求/结果/错误、owner、版本、deadline、evidence 草案 | EventEnvelope、MemoryRevision、Snapshot/Branch、RetrievalResult、Release 状态机候选 |
| **L2 模式证据** | 有单元/集成测试或多处实现支持，但仍有外部依赖/缺口 | 正反场景、边界、部分成功、重试/回滚证据 | correction lineage、diff/selective apply、plugin review/signature/limits、graph→hybrid→fulltext fallback；外部 MatrixOne 未本轮运行 |
| **L3 平台候选** | 已映射唯一 owner，跨入口调用、资源和证据契约齐全 | 适配器、版本兼容、取消/崩溃恢复、验收命令、无第二中心 | 目前只有候选：插件制品治理、快照 provider、检索 provider；不能称为已接入平台 |
| **L4 可生产复用** | 真实外部环境与故障矩阵验证，发布/回滚/残留/审计闭环通过 | 真实运行退出码 0、重启恢复、证据完整性、负载/权限/安全验证 | 本轮没有任何 Memoria L4 结论；`cargo`/MatrixOne/API/Python/Vitest 均未执行 |

具体裁决：

- `MemoryRevision` 的不可变新记录、predecessor/supersedes、active/inactive 状态：**L1→L2 候选吸收**；先补并发 CAS、幂等和完整事件关联。
- snapshot/branch/diff/selective apply 的抽象：**L2 候选吸收**；MatrixOne SQL 方言留 provider；DELETE+INSERT rollback 只能标 destructive/non-atomic。
- plugin package immutable publish + review + signer + binding + runtime budget：**L2 候选吸收至制品/证据治理**；生产信任根、激活原子性和 runtime cancel 仍待核。
- retrieval request/result/explain/degraded/fallback：**L1→L2 候选吸收**；排序、trust、graph、feedback 留记忆模块；embedding/HTTP deadline 下沉运行核心。
- `mem_edit_log` 作为可靠公共证据账本：**隔离/暂不吸收**，原因是 buffer 满可丢、失败不阻止业务、非完整事件溯源。
- async session task 作为“可取消、可恢复任务”：**暂不吸收**；当前只有后台 spawn + 三态持久记录，没有 cancel/deadline/crash recovery。
- MatrixOne 原生 snapshot/branch 细节、`correct:<id>`、六 memory types、T1–T4、dedup 阈值、Rhai plugin key：**项目特有语义/适配层**。

### 12.11 第三轮单链路落点与实施前验收契约

如果将来把这些候选接入系统工程平台，单链路应是：

```text
Memoria 项目适配层
  → 记忆模块：MemoryRevision / Retrieval / MemoryGovernance
  → 公共能力注册表：snapshot / event / evidence / task / release
  → 运行核心：deadline / cancellation / lease / CAS / crash recovery
  → 制品与证据治理：package/review/activation/audit/retention
  → MatrixOne provider / embedding provider / plugin runtime
```

不得出现：Memoria 再建一套通用事件总线、任务中心、发布中心、证据账本或资源监督器；不得让 API、MCP、SDK、OpenClaw 各自翻译一套版本/错误/回滚语义；不得让 `memoria-git` 直接把 MatrixOne DDL 穿透到上层。

装配前的最小验收契约：

1. **事件/版本**：同一 operation 重试不重复 revision；并发 correct 只有一个合法 successor；旧 revision 可读且 active 状态与 lineage 一致；事件、revision、审计证据可按 operation/correlation 读回。
2. **快照/回滚**：创建前后读回 immutable snapshot handle；diff 能区分 added/updated/removed/conflict/ghost；dry-run 不写；rollback 前有 safety point，成功/失败/未知三态可恢复；强杀后无空表/半激活。
3. **审核/制品**：同版本不同摘要拒绝；未审核制品不可激活；签名/兼容/权限/预算均有证据；拒绝、超时、取消、运行崩溃同样写审计；旧激活版本可回退。
4. **检索**：固定 query/result/explain/degraded schema；embedding、graph、vector、fulltext 各阶段有 deadline/预算；fallback 不吞原因；snapshot/revision point 可复现同一结果或明确不保证。
5. **资源**：连接池、锁、task、branch、snapshot、buffer、provider runtime 都有 owner/lease/release；超时与取消能停止或标记后台工作；进程崩溃后可扫描、回收、恢复；现场无无界残留。
6. **发布门禁**：只允许唯一契约 owner、唯一注册路径、唯一证据写入路径；源码、测试存在、真实运行、外部依赖实测分栏记录，不能把 skip、历史 RFC 或日志打印算通过。

本轮因此输出的是“可吸收模式 + 项目特有语义 + 明确缺口”的底座输入，不是对生产平台的改造批准。

## 13. 第三轮源码证据索引与验证状态

| 结论 | 主要证据路径 |
|---|---|
| 记忆实体、版本链字段、trust tier | `memoria/crates/memoria-core/src/types.rs`；`memoria/crates/memoria-service/src/service.rs` 的 `store_memory_with_metadata_on_branch`、`correct_on_branch` |
| 核心存储与检索接口 | `memoria/crates/memoria-core/src/interfaces.rs`；`memoria/crates/memoria-storage/src/store.rs` 的 `search_*`；`memoria/crates/memoria-service/src/service.rs` 的 `retrieve_inner` |
| 表结构、edit log 与 best-effort 写入 | `memoria/crates/memoria-storage/src/store.rs` 的 `bootstrap_user_schema`、`log_edit`、`insert_edit_log_direct` |
| snapshot/branch/diff/apply/restore | `memoria/crates/memoria-git/src/service.rs`；`memoria/crates/memoria-api/src/routes/snapshots.rs`；`memoria/docs/git-for-data-rfc.md` |
| 治理安全快照、审计、breaker/fallback | `memoria/crates/memoria-service/src/governance.rs`；`memoria/crates/memoria-service/src/scheduler.rs`；`memoria/crates/memoria-api/src/routes/governance.rs` |
| 分布式锁与异步任务三态 | `memoria/crates/memoria-service/src/distributed.rs`；`memoria/crates/memoria-api/src/routes/sessions.rs` |
| 插件发布/审核/激活/审计 | `memoria/crates/memoria-service/src/plugin/repository.rs`、`manifest.rs`、`rhai_runtime.rs`；`memoria/crates/memoria-api/src/routes/plugins.rs` |
| 测试存在但本轮未运行 | `memoria/crates/memoria-storage/tests/`、`memoria/crates/memoria-git/tests/git_ops.rs`、`memoria/crates/memoria-service/tests/`、`memoria/crates/memoria-api/tests/`、`memoria/crates/memoria-mcp/tests/`、`sdk/python/tests/`、`plugins/openclaw/openclaw/__tests__/` |

**第三轮状态：已完成源码级映射和裁决，未完成真实运行验证。** `project_context` 错绑、Memoria 无代码图、旧细探现场缺失、MatrixOne/外部 provider 未启动，以及异步任务取消/崩溃恢复、snapshot 非原子恢复、审计 buffer 丢失等均保留为剩余风险；没有把它们写成已解决。后续只维护本文件，不删除或改写旧细探材料。
