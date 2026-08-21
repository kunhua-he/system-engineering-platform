# Memory Palace 架构建档

> 本文档是基于当前工作树静态阅读形成的架构地图，不把 README/设计说明当作运行验证证据。
> 目标仓库：`Memory-Palace`
> 许可证：MIT
> 建档范围：README、AGENTS、依赖、后端/前端入口、数据模型、迁移、API、MCP、CLI/集成脚本、测试、`细探-Memory-Palace.md`。

## 1. 项目定位与边界

Memory Palace 是一个面向 AI Agent 的持久化记忆服务：以 SQLite 保存跨会话记忆，以 URI 作为逻辑地址，通过 MCP 向多个 Agent 客户端提供统一的读写、检索和治理工具，同时提供 React Dashboard 做浏览、审查、维护和可观测性。

核心设计边界：

- **MCP 工具层**负责确定性执行；仓库内 Skill 负责调用策略、时机和安全顺序。
- **记忆内容与路径分离**：`memories` 保存内容/版本，`paths` 保存 `domain://path` 地址及优先级、disclosure；多个路径可以指向同一记忆。
- **写入先过 Write Guard**：主要动作是 `ADD`、`UPDATE`、`NOOP`、`DELETE`；更新形成版本链，旧版本默认标记 deprecated，必要时再人工永久删除或归档。
- **读取与检索支持降级**：keyword、semantic、hybrid 可按配置和运行能力自动退化，并在结果中报告 `degrade_reasons`。
- **维护默认保守**：遗忘、分层、压缩和流程提取分别保留预览/草稿/人工 review 边界，避免静默删除或未经审核地把派生内容当成权威记忆。
- **HTTP/SSE 默认 fail-closed**：`MCP_API_KEY` 保护受限端点；stdio 是本地进程通道，不经过 HTTP/SSE 鉴权中间件。

## 2. 文档与代码证据入口

| 主题 | 权威/主要文件 | 关键事实 |
|---|---|---|
| 项目定位、部署、工具总览 | `README.md`、`README_CN.md` | 9 个 MCP 工具、A/B/C/D profile、Dashboard、SQLite、FastAPI、React/Vite |
| Agent 工作规则 | `AGENTS.md` | 先读 README/Getting Started；MCP 绑定；推荐验证命令 |
| 模块职责与数据流 | `docs/TECHNICAL_OVERVIEW.md` | 后端目录、API、前端、写入/检索流、安全默认值 |
| 操作与参数契约 | `docs/TOOLS.md` | URI、9 工具参数、返回字段、降级语义、推荐工作流 |
| 安装接入 | `docs/skills/memory-palace/SKILL.md`、`docs/skills/GETTING_STARTED.md` | `system://boot`、读前写后、Skill + MCP 双路径 |
| 本次细探工作台 | `细探-Memory-Palace.md` | 四引擎、三检索模式、MCP 边界、借鉴点；该文件未删除、未修改 |
| 运行入口 | `backend/main.py`、`backend/mcp_server.py`、`backend/run_sse.py` | FastAPI、FastMCP stdio、SSE/HTTP |
| 持久化 | `backend/db/models.py`、`backend/db/sqlite_client.py`、`backend/db/migrations/` | ORM、SQLiteClient、迁移和索引 |

## 3. 文本架构流程图

### 3.1 总体请求/数据流

```text
┌─────────────────────────────────────────────────────────────────────┐
│ Agent / 用户                                                        │
│ Claude Code · Codex · Gemini CLI · OpenCode · Cursor/Windsurf/...  │
└───────────────┬───────────────────────────────┬─────────────────────┘
                │ Skill + repo-local MCP        │ Browser Dashboard
                ▼                               ▼
     ┌──────────────────────┐          ┌─────────────────────────────┐
     │ stdio wrapper         │          │ React 18 + Vite              │
     │ .sh / mcp_wrapper.py  │          │ /memory /review /maintenance │
     └──────────┬───────────┘          │ /observability               │
                │                      └──────────────┬──────────────┘
                ▼                                     │ Axios / SSE
     ┌──────────────────────┐                         │
     │ FastMCP               │                         │
     │ backend/mcp_server.py │                         │
     │ 9 tools + system://   │                         │
     └──────────┬───────────┘                         │
                └──────────────────┬──────────────────┘
                                   ▼
                     ┌──────────────────────────────┐
                     │ FastAPI application           │
                     │ main.py lifespan + routers   │
                     │ auth / CORS / health / SSE   │
                     └──────────┬───────────────────┘
                                ▼
              ┌──────────────────────────────────────────┐
              │ 应用编排层                               │
              │ Write Lane · Snapshot · Review token     │
              │ runtime_state · Index Worker · cache     │
              └─────────────┬────────────────────────────┘
                            ▼
       ┌──────────────────────────────────────────────────────────────┐
       │ SQLiteClient / repositories / search channels                │
       │ Write Guard · CRUD · FTS5/BM25 · vector · RRF · reranker      │
       └──────────────┬─────────────────────────┬─────────────────────┘
                      │                         │
                      ▼                         ▼
          ┌───────────────────┐       ┌─────────────────────────────┐
          │ SQLite 数据库       │       │ 外部/本地检索能力             │
          │ memories/paths     │       │ hash / sqlite-vec / API      │
          │ chunks/gists/tags  │       │ embedding / reranker / LLM  │
          │ L0/L2/archive      │       └─────────────────────────────┘
          └───────────────────┘
```

### 3.2 写入路径

```text
create/update/delete/add_alias/compact
        │
        ▼
规范化 URI、域、payload、版本目标
        │
        ▼
Write Lane（按 session/全局串行；队列满 => write_lane_timeout / 503）
        │
        ▼
Write Guard：语义匹配 → 关键词匹配 → 可选 LLM 决策
        │
        ├── NOOP/UPDATE/DELETE：停止或按 guard target 提示处理
        └── ADD/允许更新
                │
                ▼
SQLite transaction：memory/path/version/alias 变更
        │
        ├── SnapshotManager：session 隔离、文件锁、manifest + 原子替换
        ├── flush/access/observability 记录
        └── IndexTaskWorker：异步重建；队列满则显式报告丢弃/失败
```

### 3.3 检索路径

```text
query + mode + filters/scope_hint + include_session
        │
        ▼
preprocess_query（空白、全角、URI/过滤器规范化）
        │
        ▼
classify_intent（factual / exploratory / temporal / causal / unknown）
        │
        ▼
strategy template
        │
        ├── keyword  => FTS5/BM25；不安全表达式回退转义 LIKE
        ├── semantic => embedding + vector channel
        └── hybrid   => keyword + vector + 可选 RRF/MMR/entity boost
                              │
                              ▼
                     可选 reranker/API
                              │
                              ▼
              path revalidation / scope filtering / session-first cache
                              │
                              ▼
                  results + intent + mode_applied + degrade_reasons
```

### 3.4 维护/派生路径

```text
Dashboard / maintenance API
        │
        ├── Forgetting：simulate → candidates → review token → archive
        │                              └─ deprecated + archived_memories（不硬删）
        ├── Layering：L1 ids → provenance summary draft → 显式 persist → drill-down
        ├── Compression：budget usage → mild/aggressive/emergency preview（只读）
        └── Procedural：L1 memories → trigger + ordered steps draft
                                      → approve/reject → human_reviewed 才推荐
```

## 4. 分层与模块地图

### 4.1 接入层

- `backend/mcp_server.py`：FastMCP 服务、URI 解析/校验、系统 URI、9 个 `@mcp.tool()` 函数、写入 Guard/快照/索引编排和兼容入口。
- `backend/run_sse.py`：Starlette/ASGI SSE 传输，`/sse`、`/messages` 会话，心跳、消息体大小限制、按 principal 限流、关闭排空、8000→8010 loopback 回退。
- `backend/mcp_wrapper.py`：跨平台 Python wrapper，读取 `.env`、拒绝 `/app`/`/data` 容器路径和相对数据库路径，启动 venv 中的 `mcp_server.py`，转发 stdio 并处理 CRLF。
- `scripts/run_memory_palace_mcp_stdio.sh`：macOS/Linux/Git Bash/WSL 的 repo-local stdio 启动器。

### 4.2 FastAPI 应用层

`backend/main.py` 创建 `FastAPI(title="Memory Palace API")`，关闭默认 OpenAPI/Redoc，注册 CORS 和 7 个 router；lifespan 中初始化 backend runtime、挂载嵌入式 SSE、关闭时排空摘要/关闭 runtime/db。

| Router | Prefix | 主要职责 |
|---|---|---|
| `api/browse.py` | `/browse` | 记忆树浏览、创建、更新、删除；写入走 Write Lane 和 Snapshot |
| `api/review.py` | `/review` | session/snapshot、diff、rollback、integrate、deprecated/永久删除 |
| `api/maintenance.py` | `/maintenance` | import/learn/reflection、orphans、vitality、index job、sleep consolidation、observability |
| `api/setup.py` | `/setup` | 首启状态和受限本地 `.env` 配置写入 |
| `api/layering.py` | `/api/layering` | L2 摘要列表/详情/生成 draft |
| `api/forgetting.py` | `/api/forgetting` | 衰减模拟、候选、archive prepare/confirm |
| `api/search_quality.py` | `/search` | `/quality-metrics`；当前明确返回质量样本未持久化 |

公开基础端点：`GET /`、`GET /health`。`/health` 未鉴权远端返回浅健康；loopback 或有效 key 可读 runtime/index 详情；降级时 HTTP 503。

### 4.3 应用运行态层

`backend/runtime_state.py` 的 `RuntimeState` 聚合多个进程内协调器：

- `WriteLaneCoordinator`：写操作按 lane/session 串行，超时显式失败。
- Session-first 检索缓存、最近读取缓存、flush tracker、promotion tracker：服务于会话召回、compact 和观测。
- `IndexTaskWorker`：后台 rebuild/reindex/sleep-consolidation 队列，提供 job 状态、取消、重试、队列容量和统计。
- reflection lanes：对可选 LLM 反思工作做超时/异常降级。

这些对象是进程内状态，不是跨进程共享队列；SQLite 和文件锁承担跨进程持久化协调的主要边界。

### 4.4 核心业务引擎层

- `core/facade.py`：`MemoryCore` 兼容外观，主要是委托，不是独立存储实现。
- `core/layering_engine.py`：L2 summary。读取 L1，构造带 source ids/hashes、derivation method、confidence、review state、storage budget 的 draft；`persist_draft` 才落库；drill-down 对 live/archive/purged 来源保留状态。
- `core/forgetting_engine.py`：指数 vitality 衰减和候选计算是只读；`approve_archive` 要求 review token，将内容复制到 `archived_memories` 并把原记忆置 `deprecated`，不使用 SQL DELETE。
- `core/compression_engine.py`：按预算使用率计算 mild/aggressive/emergency 级联预览；核心域/固定记忆可豁免；v1 只读，不写 gist/summary/archive、不入队。
- `core/procedural_engine.py`：从 L1 提取 trigger 和有序步骤；新记录默认为 `draft`，审核后变为 `human_reviewed`，拒绝记录仍可审计，只有 human_reviewed 会被推荐。

### 4.5 持久化与检索层

- `db/sqlite_client.py`：当前 canonical storage facade，异步 SQLAlchemy/aiosqlite，包含 CRUD、版本迁移链、路径/别名、Write Guard、gist、vitality、索引、keyword/semantic/hybrid 搜索等。它向后兼容地重新导出 `db.models` 中的 ORM 类。
- `db/repositories/`：`MemoryRepository`、`PathRepository`、`SearchRepository`、`IndexRepository`、`VitalityRepository`、`GistRepository`、`MaintenanceRepository` 是薄 facade；当前主要委托回 SQLiteClient，尚未完全承载方法实现。
- `db/search/`：`fts5_channel.py`、`vector_channel.py`、`rrf_fusion.py`、`entity_channel.py`、`base_channel.py`；RRF 是配置开关，entity 是 fusion 后 boost，不是第三条 RRF channel。
- `db/embeddings/drift_detector.py`：比较 embedding backend/model/dimension/API base 元数据，漂移时排队 reindex。
- `db/snapshot.py`：按 session/database scope 维护 path/memory snapshots；manifest 和单文件原子替换，保守 retention/GC，回滚前检查是否被更新版本覆盖。
- `db/migration_runner.py`：发现 `000N_*.sql`，按 normalized UTF-8/BOM/换行计算 checksum，锁住 migration 文件，创建/更新 `schema_migrations`，重试 SQLite locked。
- `db/migration_gate.py`：operator/CI 侧安全门，执行 backup、dry-run、rollback 文件存在检查、风险表 JSONL export，再委托 MigrationRunner。

## 5. 数据模型与持久化演进

### 5.1 ORM 核心模型

`backend/db/models.py` 定义 SQLAlchemy `Base` 和以下模型：

| 表 | 作用 | 关键字段/关系 |
|---|---|---|
| `memories` | L1 内容、版本、活力 | `id`、`content`、`deprecated`、`migrated_to`、`vitality_score`、`last_accessed_at`、`access_count` |
| `paths` | URI 路径/别名 | 复合主键 `(domain, path)`；`memory_id` 外键；`priority`、`disclosure` |
| `memory_chunks` | 分块检索文本 | `memory_id`、`chunk_index`、字符范围 |
| `memory_chunks_vec` | 传统 SQLite 向量存储 | `chunk_id`、`memory_id`、JSON/text vector、model、dim |
| `embedding_cache` | embedding 缓存 | `cache_key`、`text_hash`、model、embedding |
| `index_meta` | 索引能力/运行元数据 | key/value |
| `schema_migrations` | 已应用迁移 | version/checksum/applied_at |
| `memory_gists` | 单记忆摘要 | source hash/method/quality，0007 后带派生 provenance |
| `memory_tags` | 结构化标签 | type/value/confidence |
| `access_log` | L0 访问/写入/命中日志 schema（迁移/模型已定义，runtime writer 未证实） | operation、timestamp、context、metadata_json |
| `memory_summaries` | L2 topic/scope 摘要 | summary、scope、layer、source ids/hashes、review state |
| `archived_memories` | 遗忘后的可恢复副本 | original id、content、paths snapshot、review state |
| `procedural_memories` | 可审核的步骤式记忆 | trigger、steps_json、provenance、review state、success_count |

### 5.2 启动和迁移顺序

```text
DATABASE_URL
   │
   ▼
SQLiteClient.__init__：校验路径、配置 WAL/embedding/vector/reranker
   │
   ▼
_process/init lock_
   │
   ▼
Base.metadata.create_all
   │
   ├── legacy migrated_to 兼容迁移
   └── MigrationRunner.apply_pending()
          │
          ├── 0001 vitality/gist/tag 基础表
          ├── 0002 gist (memory_id, source_content_hash) 唯一索引
          ├── 0003 vitality/path 清理查询索引
          ├── 0004 access_log（L0）
          ├── 0005 memory_summaries（L2）
          ├── 0006 archived_memories
          ├── 0007 memory_gists 派生 provenance + backfill
          └── 0008 procedural_memories
   │
   ▼
embedding drift 检测 → FTS/vector/sqlite-vec 能力探测
   │
   ▼
index metadata / WAL metadata 同步 → bootstrap indexes
```

### 5.3 版本与安全语义

- 更新不是覆盖旧内容：旧 `Memory` 通过 `migrated_to` 指向 successor，review 页面可 diff/rollback；永久删除时会修复版本链。
- 路径和 memory snapshot 分开记录，允许只回滚路径或只回滚内容。
- 遗忘 archive 保存原始内容和路径快照；原记录保留为 deprecated tombstone。
- L2/gist/procedural 派生数据保留来源 memory id、来源 hash、方法、置信度、审核态等 provenance；来源丢失时 layering drill-down 返回 purged tombstone，不静默丢来源。
- migration runner 负责运行时幂等和 checksum；migration gate 负责人工/CI 级 backup、dry-run、rollback/export 护栏。

## 6. API、MCP、CLI 与 SDK 边界

### 6.1 MCP 工具契约

代码和 `backend/tests/contract/mcp_contract_golden.json` 将工具集合冻结为 9 个：

| 工具 | 输入/作用 | 关键输出或边界 |
|---|---|---|
| `read_memory` | URI；可选 chunk/range/max_chars/ancestors | 支持 `system://boot/index/index-lite/audit/recent/N` |
| `create_memory` | parent URI、content、priority、可选 title/disclosure | 先 Guard；超长/只读域/Guard 拒绝时不写 |
| `update_memory` | URI；Patch `old_string/new_string` 或 Append；可改元数据 | Patch/Append 互斥；版本冲突返回可重试错误 |
| `delete_memory` | URI path | 删除逻辑路径；具体持久化删除受 review/维护边界约束 |
| `add_alias` | new URI、target URI、priority/disclosure | 支持跨域；snapshot 失败时回滚 |
| `search_memory` | query、mode、候选数、session、filters、scope_hint | `results`、intent、mode_applied、`degrade_reasons` |
| `compact_context` | reason、force、max_lines | Gist + Trace；LLM → extractive → sentence fallback |
| `rebuild_index` | memory_id/reason/wait/timeout/sleep_consolidation | 异步 job 或等待结果；队列满显式 `queue_full` |
| `index_status` | 无参数 | index availability、degraded、worker、write lanes、sleep 状态 |

URI 是 `domain://path`，默认域 `core`；`system` 是只读域。控制字符、surrogate、畸形 URI、路径式 Windows 输入和超长 payload 在边界层拒绝。

### 6.2 HTTP API 重点清单

- `/browse/node`：GET 浏览节点/子节点/breadcrumb/gist/alias；POST/PUT/DELETE 走写 lane、Guard、snapshot 和版本语义。
- `/review/*`：sessions、snapshots、diff、rollback、integrate、deprecated、永久删除、通用 diff。
- `/maintenance/*`：外部导入 prepare/execute/rollback、显式 learn/reflection、orphans、vitality cleanup、index worker/job/cancel/retry/rebuild/reindex/sleep consolidation、observability。
- `/api/layering/*`：摘要查询、来源 drill-down、生成 draft；生成接口 v1 不自动持久化。
- `/api/forgetting/*`：simulate/candidates 只读；archive prepare/confirm 或单条 archive 需要 review token。
- `/search/quality-metrics`：当前为真实鉴权端点，但返回 `is_mock=true`、`status=unavailable`，因为 labelled quality samples 尚未持久化。
- `/setup/status`、`/setup/config`：首启 Dashboard 配置；本地 `.env` 写入受项目路径、loopback、key 和 provider base 校验约束。

受保护路径由 `maintenance.require_maintenance_api_key`/SSE middleware 控制，支持 `X-MCP-API-Key` 或 `Authorization: Bearer`。允许本地免 key 也必须显式设置 `MCP_API_KEY_ALLOW_INSECURE_LOCAL=true`，且限 direct loopback。

### 6.3 CLI/脚本入口

仓库没有独立发布的 Python/TypeScript SDK 包；可编程公共边界主要是 HTTP API、MCP 和脚本。

| 命令/脚本 | 用途 |
|---|---|
| `bash scripts/apply_profile.sh [--dry-run] [platform] [profile] [target]` | 从 `.env.example` + `deploy/profiles/{macos,linux,windows,docker}/profile-{a,b,c,d}.env` 生成配置 |
| `scripts/docker_one_click.sh/.ps1` | 生成 Docker env、避端口冲突、启动/健康检查、挂载/WAL 防护 |
| `scripts/run_memory_palace_mcp_stdio.sh` | POSIX shell stdio MCP launcher |
| `python backend/mcp_wrapper.py` | Windows/跨平台 Python stdio wrapper |
| `python scripts/install_skill.py` | `--targets`、`--scope workspace/user`、`--mode copy/symlink`、`--with-mcp`、`--dry-run`、`--check` |
| `python scripts/render_ide_host_config.py --host ...` | 为 cursor/windsurf/vscode-host/antigravity 输出 repo-local MCP JSON 片段 |
| `python scripts/sync_memory_palace_skill.py [--check]` | 同步/检查 canonical Skill 到 workspace mirrors |
| `python scripts/evaluate_memory_palace_skill.py` | Skill 触发和安装契约评估 |
| `python scripts/evaluate_memory_palace_mcp_e2e.py` | live MCP e2e（需要已运行后端/环境） |
| `bash scripts/pre_publish_check.sh` | 发布前工件、endpoint/key 模式检查 |
| `bash scripts/backup_memory.sh` / `.ps1` | 数据库备份与保留策略 |

### 6.4 客户端接入双路径

- CLI 客户端建议 `Skill + MCP`：Skill 读取仓库可见的 `docs/skills/memory-palace/`；MCP 通过 stdio wrapper 绑定本仓库数据库。
- IDE 宿主走 repo-local `AGENTS.md` + `render_ide_host_config.py` 输出的 stdio 配置，不依赖隐藏 Skill mirror。
- SSE 适合不支持 stdio 的客户端；连接 `/sse`，POST `/messages`，需要 API key；Codex/OpenCode 的远程 SSE 直连在 Getting Started 中标注为尚未验证。

## 7. 技术栈与部署

| 层 | 技术/版本要求 | 用途 |
|---|---|---|
| 语言 | Python 3.10+；Node.js 20.19+ 或 22.12+ | 后端/前端 |
| Web | FastAPI ≥0.109、Uvicorn ≥0.27、Starlette/SSE-Starlette | REST、内嵌/独立 SSE |
| MCP | `mcp` / FastMCP ≥0.1 | 9 工具、stdio/SSE |
| ORM/DB | SQLAlchemy ≥2.0、aiosqlite ≥0.19、SQLite | 异步 CRUD、索引和持久化 |
| 校验/配置 | Pydantic ≥2.5、pydantic-settings、python-dotenv | payload、环境配置 |
| 检索 | FTS5/BM25、hash/API embedding、sqlite-vec ≥0.1.9、RRF、可选 MMR/reranker | keyword/semantic/hybrid |
| HTTP/文本 | httpx、requests、diff_match_patch、difflib fallback | 外部 provider、diff |
| 并发/锁 | asyncio、filelock、SQLite WAL/busy timeout | write lane、snapshot/migration/index |
| 前端 | React 18、React Router 6、Axios 1、i18next/react-i18next | Dashboard 和 API 客户端 |
| 前端构建 | Vite 7、Tailwind 3、Framer Motion 12、Vitest 3、TypeScript 5 | 构建、样式、测试/typecheck |
| 容器 | Docker Compose；backend `python:3.11-slim`；frontend Node 22 build + nginx-unprivileged | 本地/镜像部署，默认非 root |

部署 profile：A=keyword、B=hybrid+本地 hash（默认起步）、C=本地/Router embedding + reranker、D=远程 API embedding + reranker。切换 embedding backend/model/dimension 后必须检查 drift/index 状态，必要时 rebuild；C/D 依赖真实 endpoint/key/model/dimension，模板占位值会 fail-closed。

Docker 默认 backend 容器端口 8000、宿主 18000；frontend 容器 8080、宿主 3000；数据和 snapshots 使用 named volumes，默认 loopback 绑定。仓库对 NFS/CIFS/SMB + WAL 组合有显式拒绝/覆盖规则。

## 8. 测试与验证地图（只读盘点，未执行）

本次未安装依赖、未启动服务、未构建、未运行测试；以下是从测试文件实际盘点出的验证面。

仓库当前 tracked 统计：约 **112 个 backend 测试 Python 文件**、约 **187 个核心 backend Python 文件**、约 **81 个 frontend/src 文件**。主要测试类别：

- **MCP 合同**：`backend/tests/contract/test_mcp_contract_golden.py` 用 AST 固定 9 工具的名称、参数顺序、默认值、返回注解、域/URI 常量、golden transcript 和 `db.sqlite_client` 模型 re-export。
- **写入/并发**：`test_browse_write_lane.py` 验证 create/update/delete 进入 lane、Guard 在 lane 内执行、队列满映射 503、版本冲突映射 409、snapshot resource type/operation。
- **检索**：`test_search_memory_scope_hint_compat.py` 验证 URI scope hint、filters 优先冲突、domain/path_prefix 传递；`test_rrf_integration.py`、`test_embedding_provider_chain.py`、`test_sqlite_vec_rollout.py` 覆盖融合、provider chain、sqlite-vec gate。
- **审查/回滚**：`test_review_rollback.py` 覆盖 path/memory snapshot、树级联删除、alias root、晚到 descendant、旧版本永久删除和 stale target 409。
- **四引擎**：`test_layering_engine.py` 验证 provenance、默认只读、persist、live/archive/purged drill-down、hash stale；`test_forgetting_engine.py` 验证 decay/candidate 只读、review token、archive 不硬删；另有 compression/procedural 对应测试。
- **安全/传输**：`test_mcp_transport_security.py` 验证 DNS rebinding、host/origin allowlist、loopback 默认、8000→8010、非法 host 无 traceback；`test_mcp_uri_contracts.py`、`test_mcp_error_contracts.py`、`test_sensitive_api_auth.py` 覆盖 URI/错误/HTTP 鉴权。
- **迁移/启动**：`test_migration_runner.py`、`test_migrations_0004_0007.py`、`test_init_db_process_lock.py`、`test_backend_healthcheck.py` 覆盖 checksum、rollback/安全门、初始化锁和容器 healthcheck。
- **维护/运行态**：week2/week3/week4/week6/week7 系列覆盖 Write Guard、intent、Gist、SSE/maintenance auth、vitality cleanup、index job cancel/retry、sleep consolidation、reflection、observability。
- **前端**：`App.test.jsx`、`MemoryBrowser.test.jsx`、`ReviewPage.test.jsx`、`MaintenancePage.test.jsx`、`ObservabilityPage.test.jsx`、`RootErrorBoundary.test.jsx`、i18n/API/SSE/browser profile 测试；`package.json` 还提供 `test:bundle-budget` 和 `typecheck`。
- **Benchmark/fixture**：`backend/tests/benchmark/` 含 profile A/B/C/D、延迟、质量、降级注入和 dataset integrity runner；`fixtures/` 含 memory/intent/write guard/Gist golden 数据。

AGENTS 声明的验证命令为：

```text
cd backend && .venv/bin/pytest tests -q
cd frontend && npm test && npm run build
python scripts/evaluate_memory_palace_skill.py
cd backend && python ../scripts/evaluate_memory_palace_mcp_e2e.py
```

这些命令当前核对均未执行，不能据此宣称当前工作树测试通过。

## 9. 关键路径索引

| 路径 | 作用 |
|---|---|
| `backend/main.py:113-166` | FastAPI lifespan、SSE mount、router 注册 |
| `backend/main.py:181-276` | `/health` 浅/详细健康和 degraded 503 |
| `backend/mcp_server.py:155-181` | FastMCP、域白名单、只读 system 域、默认 core |
| `backend/mcp_server.py:4293-6262` | 9 个 MCP tool 定义区间 |
| `backend/run_sse.py:434-735` | SSE transport、限流、body limit、session、关闭清理 |
| `backend/run_sse.py:735-917` | API key middleware、SSE app、uvicorn/端口入口 |
| `backend/runtime_state.py:121-358` | Write Lane |
| `backend/runtime_state.py:1622-2100` | IndexTaskWorker |
| `backend/db/sqlite_client.py:349-614` | SQLiteClient 初始化配置、embedding/vector/reranker |
| `backend/db/sqlite_client.py:1215-1235` | `create_all` → migration → drift/index bootstrap |
| `backend/db/models.py:67-438` | ORM 表、关系和派生模型 |
| `backend/db/migration_runner.py:70-405` | migration discovery/checksum/lock/apply |
| `backend/db/migration_gate.py:284-457` | backup/dry-run/export/rollback safety gate |
| `backend/core/layering_engine.py:226-441` | L2 draft/persist/query/drill-down |
| `backend/core/forgetting_engine.py:137-411` | vitality/candidate/review archive |
| `backend/core/compression_engine.py:171-440` | preview-only cascade |
| `backend/core/procedural_engine.py:219-499` | procedural draft/approve/reject/recommend |
| `frontend/src/main.jsx:34-54` | React root、StrictMode、全局 rejection handler |
| `frontend/src/App.jsx:24-320` | lazy pages、Dashboard routes/layout |
| `frontend/src/lib/api.js:11-353` | Axios、运行时/会话鉴权注入和 protected path 判定 |
| `frontend/src/lib/api.js:556-763` | Dashboard API 调用面 |
| `frontend/vite.config.js:18-46` | `/api`、layering/forgetting、SSE dev proxy |

## 10. 未确认项与维护提示

以下项目通过静态代码/文档无法在当前核对确认，后续若要运行或改造应单独验证：

1. **未做运行验证**：没有安装依赖、没有启动 FastAPI/SSE/Dashboard、没有执行 pytest/npm/build/e2e，因此依赖安装状态、实际 import、数据库初始化和端到端连通性均未确认。
2. **当前数据库状态未确认**：仓库未提供当前核对使用的 `DATABASE_URL`/运行数据库；无法确认实际 migration head、已写入表数据、索引能力或 embedding drift 状态。
3. **外部 provider 未确认**：C/D 的 embedding、reranker、可选 Write Guard/Gist/intent LLM endpoint、key、模型和维度都依赖部署环境；源码只实现配置读取、校验、降级和报告。
4. **sqlite-vec 实效未确认**：代码有 native vec0 探测、extension path 和 legacy fallback，但当前环境没有进行 extension load/KNN 实测。
5. **质量面板不是生产质量证明**：`/search/quality-metrics` 源码明确返回 `is_mock=true` / labelled samples 未持久化；README 中 benchmark 数字是发布摘要，不等于本地当前运行结果。
6. **SDK边界**：没有发现独立可安装 Python/TypeScript SDK；稳定公共契约是 MCP/HTTP/脚本。客户端各自对 SSE header、IDE local stdio 的支持仍需按目标宿主复核。
7. **文档与代码可能漂移**：README/TECHNICAL_OVERVIEW 是导航和设计说明，实际路由/返回字段应以 `backend/api`、`backend/mcp_server.py` 和合同测试为准；特别是 `/api/layering`、`/api/forgetting` 与 Dashboard `/api` proxy 的组合需在运行环境复核。
8. **迁移回滚数据风险**：0006/0007/0008 配对 rollback 文件存在，migration gate 规定对风险表先 backup/export；真实环境执行 rollback 前仍需确认 backup/export 产物和数据保全策略。
9. **进程内状态边界**：session cache、write lane、index worker 主要是单进程 runtime state；多进程/多容器扩展时不能默认把它们当作共享协调服务，应实测 SQLite WAL、锁和 job 语义。

## 11. 当前核对变更边界

- 新增：项目根 `ARCHITECTURE.md`（本文件）。
- 未修改：源码、依赖清单、测试、配置、迁移、Docker 文件、README、Skill、既有 `细探-Memory-Palace.md`。
- 未执行：依赖安装、服务启动、构建、测试、数据库写入、Git 提交。
- 现有工作树中原先的未跟踪 `细探-Memory-Palace.md` 保持原样；当前核对不将其删除或改写。

## 12. 旧细探逐项吸收裁决

本节是对 `细探-Memory-Palace.md` 的收口记录。旧细探保留为历史取证材料，但不再作为当前架构事实的第二权威来源；后续维护以本 `ARCHITECTURE.md` 为准。本节只裁决项目自身事实，不把“对底座可借鉴点”冒充为 Memory Palace 的实现事实。

### 12.1 已吸收（源码/正式文档仍有证据）

| 旧细探内容 | 吸收位置 | 当前证据 |
|---|---|---|
| 项目定位：持久、可搜索、可审计、跨会话的 AI Agent 记忆服务；MIT、Python 3.10+、FastAPI、React 18/Vite、MCP | §1、§7 | `README.md:32-38`、`README.md:121-157`、`LICENSE:1-21` |
| MCP 客户端经统一服务接入，CLI 采用 Skill + MCP，IDE 采用 `AGENTS.md` + 渲染片段 | §3.1、§6.4 | `README.md:34-38`、`README.md:309-355`、`AGENTS.md:25-28`、`scripts/render_ide_host_config.py` |
| backend 四引擎：layering、compression、forgetting、procedural | §3.4、§4.4、§5.1、§8 | `backend/core/layering_engine.py`、`compression_engine.py`、`forgetting_engine.py`、`procedural_engine.py`；对应四组测试 |
| 三种检索模式及自动降级、`degrade_reasons`、按 scope 检查向量维度、陈旧路径结果丢弃 | §1、§3.3、§4.5、§6.1 | `README.md:80-86`；`backend/db/sqlite_client.py`、`backend/db/search/`；`test_search_memory_scope_hint_compat.py`、`test_embedding_provider_chain.py` |
| MCP 边界：畸形 URI、超大 payload、percent-encoded URI、`system://` 写保护、`add_alias` 失败回滚 | §6.1、§6.2、§8、§9 | `backend/mcp_server.py`；`test_mcp_uri_contracts.py`、`test_mcp_error_contracts.py`、`test_review_rollback.py` |
| SQLite 持久化及 `sqlite_client`、embedding/search、snapshot、migration runner/gate、repositories 的分层关系 | §3.1、§4.5、§5 | `backend/db/`、`backend/db/migrations/`、`backend/tests/test_migration_runner.py` |
| review 人工审查边界，以及维护操作的预览/草稿/显式批准语义 | §3.4、§4.4、§5.3、§6.2 | `backend/api/review.py`、`backend/api/forgetting.py`、`backend/core/*_engine.py`；对应引擎测试 |
| embedding 维度/后端变化需要检查索引并可能 `rebuild_index(wait=true)`；sqlite-vec 与 legacy fallback 并存 | §1、§4.5、§7、§10 | `README.md:97-100`、`README.md:214-222`；`backend/db/search/vector_channel.py`、`test_sqlite_vec_rollout.py` |
| 四引擎的安全细节：Layering 保留 provenance、Compression v1 只读、Forgetting 需 review token 且归档不硬删、Procedural 草稿只向 human-reviewed 推荐 | §4.4、§5.3、§8 | 各 `backend/core/*_engine.py` 模块说明与 `test_layering_engine.py`、`test_compression_engine.py`、`test_forgetting_engine.py`、`test_procedural_engine.py` |

### 12.2 不吸收为当前架构事实（保留裁决原因）

| 旧细探内容 | 裁决 | 原因 |
|---|---|---|
| “压缩语义无损” | 不吸收 | 源码只证明 v1 是只读级联预览和候选排序，不证明实际压缩后的语义等价或无损；§4.4、§10 已按可验证边界表述。 |
| “不同生命周期分层” | 不吸收原表述 | 源码能证明 L0/L1/L2、provenance 和 review state，不能仅凭该短语推出完整生命周期状态机；已用 §3.4、§4.4、§5.1 的具体模型替代。 |
| “提示词设计：四引擎使用提示词、MCP 工具描述统一接口” | 不吸收 | 这是未指向具体 prompt、调用方、输入输出契约的概括，不能作为架构边界；可选 LLM/fallback 已在 §4.4、§6.1、§10 记录。 |
| “backend/api 包含 `_write_lane` API 面” | 不吸收为 HTTP router | `backend/api/_write_lane.py` 是写通道内部协调模块；`backend/main.py:159-166` 实际注册的是 7 个 HTTP router。其职责已按内部 `WriteLaneCoordinator` 收录于 §4.3，而不把文件名误写成公开 API。 |
| “四引擎全套可借鉴”“平台 MCP 网关安全清单”“平台证据账本人工复核”等底座建议 | 不吸收至本项目文档 | 这些是跨项目迁移建议，不是 Memory Palace 自身事实；按单项目文档边界，不在本项目架构文档制造底座结论。 |
| “MIT 可自由借鉴” | 不吸收为工程结论 | `MIT` 许可证事实已吸收；“可自由借鉴”属于法律/跨项目使用判断，不由架构文档替代法律意见。 |
| “依赖嵌入服务”作为必选依赖 | 不吸收原表述 | A/B profile 可在无外部 embedding 服务时工作，C/D 才需要真实 endpoint/key/model/dimension；§7、§10 已按 profile 条件记录。 |
| `backend/core/*_engine.py`、`backend/db/snapshot.py`、`docs/skills/`、`frontend/`、`AGENTS.md` 旁路线索列表 | 不单独复制 | 这些路径已分别进入 §2、§4、§5、§6、§9 的证据索引；重复保留会形成第二套导航。 |

### 12.3 收口状态

- 已吸收：旧细探的项目定位、接入边界、四引擎、检索降级、MCP 安全、SQLite/快照/迁移、review 语义和向量索引演进，均已落入本文件对应章节并绑定源码或正式文档证据。
- 未吸收：无证据的宣传性措辞、跨项目借鉴建议、未形成契约的 prompt 概括，以及会误导公开 API 边界的 `_write_lane` 表述；均保留了不吸收原因。
- `细探-Memory-Palace.md` 不删除、不修改；它只作为旧细探原文留存，本文件是唯一当前架构事实源。

## 13. 后续：面向系统底座的映射与裁决

本节只回答“如何把已证实的 Memory-Palace 机制映射到支持库、模块库和运行核心”，不表示目标平台已经实现这些能力，也不修改目标平台。映射依据是当前源码：`backend/runtime_state.py`、`backend/db/sqlite_client.py`、`backend/db/snapshot.py`、`backend/db/migration_gate.py`、`backend/core/layering_engine.py`、`backend/core/forgetting_engine.py`、`backend/core/procedural_engine.py` 和对应测试；没有源码明确出现的 L3/L4 语义标为“待核”。

### 13.1 现有能力命中表与落点裁决

| Memory-Palace 能力 | 当前真实 owner/证据 | 支持库映射 | 模块库映射 | 运行核心映射 | 裁决 |
|---|---|---|---|---|---|
| 写入串行化 | `runtime_state.py:121-356`：session lane + global semaphore；SQLite 锁冲突有限重试，超时为 `write_lane_timeout`；`api/_write_lane.py:8-36` 映射 HTTP 503 | 原子事务、短锁、SQLite 连接/重试适配 | 记忆写入编排：规范化 URI → Guard → 版本写入 → 快照 → 索引任务 | 统一资源协调、并发预算、取消/超时和租约；不能把进程内 `asyncio` 锁冒充跨进程锁 | 吸收并升级：跨进程协调必须由 SQLite/file lock/运行核心补足 |
| 快照与回滚 | `db/snapshot.py:219-230,427-457,926-1050`：按 session/数据库 scope 隔离，FileLock，先写资源再原子写 manifest；manifest 失败恢复旧字节或清理新文件 | 不可变快照、内容摘要、临时文件、`fsync` + 原子替换、路径安全、资源锁 | review/rollback 流程只操作公开快照接口，检查新版本覆盖后再回滚 | 崩溃窗口、锁租约、恢复扫描、残留清理；数据库事务回滚不能被文件快照替代 | 吸收；快照与权威 DB 必须双阶段对账 |
| 审核令牌 | `runtime_state.py:1400-1480`：令牌/确认短语/TTL/一次性消费仅在进程内；`forgetting_engine.py:274-411` 与 `procedural_engine.py:369-538` 验证 token，并保存 SHA-256 指纹 | 只提供安全比较、摘要、令牌格式校验，不持有授权事实 | 归档、L2/流程草稿批准/拒绝；模块负责状态机，不自造第二套 token | 持久化授权/会话/租约、过期与重启失效、审计证据、并发一次性消费 | 升级：目标平台的审核令牌 owner 应是运行核心授权/证据链，模块只消费公开验证结果 |
| 归档 | `forgetting_engine.py:274-411`：候选/模拟只读；批准后写 `archived_memories`、保留 paths snapshot、原记忆 `deprecated=1`、不 DELETE；重复归档复用已有 archive | 原子复制/恢复、摘要与压缩存储、归档介质适配 | 记忆生命周期模块：candidate → review → archive → restore/purge；保留 tombstone/provenance | 事务提交、失败回滚、恢复编排、清理和生命周期租约 | 吸收；“归档≠删除”是公共契约，不应由 provider 私自改变 |
| 索引重建 | `runtime_state.py:1630-1760` 起：队列、有界容量、job 状态/取消/重试；`sqlite_client.py:1237-1279` 检测 embedding drift 后排队 rebuild；`db/repositories/index_repo.py` 只是薄委托 | FTS/vector/sqlite-vec provider、维度/模型检查、批量索引与摘要 | 检索模块决定 rebuild/reindex/sleep-consolidation 的业务编排和结果契约 | 后台任务生命周期、队列背压、取消、重启恢复、资源预算和幂等 job key | 吸收并拆责：索引数据能力下沉支持库，任务治理留运行核心，领域触发留模块库 |
| 降级原因映射 | `sqlite_client.py:2267-2316,6710-7120` 与 `mcp_server.py:2452-2540`：原因去重、带 backend/timeout/异常类型；semantic/hybrid 可退 keyword，gist 可退 extractive/sentence | provider 能力探测、统一错误/能力状态、超时和健康信号 | 检索/摘要/Guard 模块将 provider 失败翻译成稳定 `degraded + degrade_reasons`，不得静默吞错 | 资源/超时/熔断/重试与观测事件；不决定领域 fallback 内容 | 吸收：原因是结果契约的一部分；统一入口归一化，禁止各消费者各维护映射 |

**单一 owner 规则**：写入状态、版本链、归档事实、审核结果、索引元数据、快照文件和降级事件分别只能有一个权威写入口。支持库不写业务状态，模块不直连第三方或旁路写 SQLite，运行核心不替模块决定“什么内容值得记忆”。

### 13.2 SQLite 与进程内边界

```text
外部 MCP/HTTP/控制台
  → 模块库公开入口（记忆写入/检索/维护）
  → 运行核心资源协调（写车道、任务、授权、超时、恢复）
  → 支持库公开能力（SQLite/快照/索引/provider）
  → SQLite 文件 + snapshots 文件树 + 可选外部 embedding/reranker
```

| 边界 | SQLite/文件持久层 | 进程内运行态 | 迁移到平台的硬规则 |
|---|---|---|---|
| 权威性 | `memories/paths/versions`、`archived_memories`、`memory_summaries`、`procedural_memories`、`index_meta` 是可跨会话事实；`access_log` 只有 schema/迁移意图，runtime writer 尚未证实；事务 `commit/rollback` 决定写入可见性 | session-first cache、`asyncio` 写车道、reflection lane、cleanup review records、IndexTaskWorker 的 queue/job/event 和统计只存在当前进程 | 进程内对象只能优化/协调，不能作为跨进程事实；重启后必须从 DB、快照和 index_meta 重建状态 |
| 并发 | `SQLiteClient.init_db()` 以 `.init.lock` 串行启动；连接 hook 设置 busy timeout；WAL 受网络文件系统风险保护，失败回退 DELETE | 同 session lock + global semaphore；默认 global concurrency 可为 1；事件循环切换会把未完成 job 标为 `event_loop_reset` | 多进程/多容器用 DB 条件、文件锁或运行核心租约；禁止把 Python lock/queue 当分布式协调器 |
| 快照 | `snapshots/.scoped/<database_fingerprint>/<session>/` 与 manifest/resource 文件隔离数据库 scope；文件锁跨进程 | SnapshotManager 单例只是进程内入口，真正快照事实在文件树 | snapshot 与 DB 提交要有可恢复关联；只恢复文件或只恢复 DB 都必须进入对账/降级态 |
| 审核 | 归档/派生行的 `review_state`、token fingerprint、archive reason 可持久化 | `CleanupReviewRecord` 的原 token、确认短语、TTL 和一次性消费记录不持久化；进程重启即失效 | 高风险操作必须使用运行核心持久授权/证据能力，短 token 只能作一次性操作凭证 |
| 外部客户端 | embedding/reranker 是 SQLite 之外的 provider，结果与错误只经统一检索入口返回 | HTTP client、reflection task、临时响应在进程内拥有 | provider 不可用时必须返回可识别原因并按契约降级，不得伪造向量/质量分 |

### 13.3 资源生命周期、失败恢复与证据要求

| 资源/节点 | 正常完成 | 业务失败/超时/取消 | 崩溃或重启后的恢复 |
|---|---|---|---|
| 写车道/SQLite session | 任务返回后释放 session lane/global semaphore；成功记录 metrics | `write_lane_timeout` 返回结构化 503；SQLite transient lock 按界限重试；异常/取消记录失败指标并在 finally 释放计数与 semaphore | 不能恢复进程内排队任务；从 DB 事务结果、snapshot manifest、index_meta 对账，未完成索引重新排队 |
| DB 连接/事务/外部 HTTP client | `async with session` 结束，`commit` 后关闭；服务 lifespan 关闭 runtime/db | 异常路径 `rollback`，禁止把半提交状态当成功；外部调用超时转原因并释放 client/响应 | 启动 quick/integrity check、迁移 checksum；损坏/迁移风险先走 backup/export/dry-run/rollback gate |
| 快照临时文件/manifest | 临时文件 flush + `fsync`，`os.replace`；FileLock 上下文退出释放锁 | manifest 保存失败恢复旧 resource bytes，或删除新 resource；锁超时产生明确错误；不可读 manifest 从资源文件重建 | 以 scope fingerprint 隔离数据库；manifest 损坏可重建，资源损坏跳过并告警；恢复后再次原子落 manifest |
| 归档/审核记录 | token 通过、候选重检通过后，在同一 DB session 中写 archive、deprecated、gist，再 commit | token 缺失/无效→拒绝；候选状态变化→409；事务异常→不宣称已归档；确认记录先消费，故障后需重新 prepare | archive 表、deprecated tombstone、paths snapshot 和 review_state 是恢复依据；重复执行应复用 existing archive，不能重复删除 |
| 索引 job | queue→running→succeeded，记录结果和 finished_at | queue 满→`dropped/queue_full`；取消→`cancelled`；异常→`failed`；事件循环切换→`failed/event_loop_reset` | job 表并非持久队列；依据 embedding drift/index_meta 和 `index_status` 重新生成幂等任务，不能认为内存 job 仍在 |
| 派生记忆 | L2/procedural 先 draft，明确 persist/approve 后才成为可推荐结果；保留 source ids/hashes | LLM 失败使用确定性 fallback，并记录方法/原因；来源缺失拒绝生成；reject 保留审计行 | live/archive/purged drill-down 均返回状态，不能静默删除 provenance；purged 只保留 tombstone/hash |

**资源释放底线**：锁、信号量、SQLAlchemy session、临时文件、HTTP client、后台 task 的释放都必须覆盖成功、异常、取消/超时和宿主退出四条路径；任何“日志显示完成”都不能替代读回 DB、快照目录、进程/锁和 job 状态的现场验证。

### 13.4 L0-L4 映射：事实、派生与未实现边界

仓库当前源码明确的是 L0、L1、L2 以及若干正交派生表；没有证据表明存在完整的 L3/L4 生命周期。为避免把平台目标层级倒灌成项目事实，采用以下分层：

| 层 | 当前源码事实 | 唯一记忆链路中的位置 | 平台映射与边界 |
|---|---|---|---|
| L0 | `AccessLog`（`db/models.py:248-274`）与迁移 `0004_add_access_log.sql` 定义了 read/write/search_hit/compact 日志表和 FIFO 意图；但当前核对静态搜索未发现 `session.add(AccessLog)` 或 `INSERT INTO access_log` 的运行时写入点 | 观测表的 schema/设计意图已存在，但“运行中持续产生日志”尚未被源码证实，不是可直接召回的记忆正文 | 支持库事件/审计记录；运行核心负责留痕与保留策略，模块只读取观测结果 |
| L1 | `memories` + `paths` + `memory_chunks` + version chain；正文更新生成 successor，旧版本 deprecated | 唯一权威记忆正文与 URI 地址 | 模块库记忆写入/读取 owner；支持库提供事务与索引；运行核心保证串行、恢复和资源边界 |
| L2 | `memory_summaries`：scope/topic 摘要，来源 ids/hashes、method、confidence、review_state；`layering_engine` 默认 draft，显式 `persist_draft` 才写 | 可追溯派生摘要，不替代 L1 | 模块库分层/摘要编排；支持库存储派生行；运行核心提供审核、任务和证据 |
| L3 | 当前没有名为 L3 的表/枚举/公开契约；`procedural_memories` 是“跨 L1 抽取的步骤式派生记忆”，但源码没有把它定义为 L3 | 只能作为候选的流程知识，默认 draft；human_reviewed 才可推荐，rejected 保留审计 | **待核/候选映射**：若平台确认 L3=流程/策略知识，由模块库承接，不能在当前核对擅自提升层级 |
| L4 | 当前没有名为 L4 的表、索引或生命周期状态；archive 是生命周期状态/副本，不等于 L4 | `archived_memories` 是可恢复归档与 tombstone 来源，不是新层级 | **待核**：平台若需要 L4（长期稳定规则/跨项目知识），须先定义来源、审核、版本、撤销、范围和召回契约 |

因此，当前唯一可落地的链路是：

```text
L0 访问/操作事件
  → L1 权威正文（memories + paths + version chain）
  → L2 带 provenance 的摘要/gist
  → [L3 流程派生候选：仅在定义和审核契约冻结后启用]
  → [L4 跨域稳定知识：当前待核，不得旁路生成]
  → 检索模块按 scope/版本/审核态过滤
  → 统一结果 + degrade_reasons + 审计事件
```

`archived_memories` 与 `purged tombstone` 横切 L1/L2/L3 的生命周期，不应被误画成 L4；任何派生对象都必须能回指 source ids/source hashes，来源进入 archive 或 purge 后返回 `from_archive`/`purged`，而不是静默丢失。

### 13.5 统一降级原因字典（映射建议，不是新增代码）

当前项目已形成“原因可观测、结果可继续”的语义，但原因字符串分散在 provider、SQLiteClient、MCP/引擎层。迁移到底座时建议只在**唯一检索/派生入口**归一化为以下稳定类别，同时保留原始原因作为 detail：

| 稳定类别 | 当前源码原因示例 | 允许的结果变化 | 不允许的行为 |
|---|---|---|---|
| `CAPABILITY_UNAVAILABLE` | `vector_backend_disabled`、`sqlite_vec_knn_unavailable`、provider 不可用 | semantic/hybrid → keyword 或 legacy scoring；LLM gist → extractive/sentence | 伪造 embedding、伪造质量或静默标成 full mode |
| `INDEX_STALE_OR_MISMATCH` | `vector_dim_mismatch_requires_reindex`、`vector_dim_mixed_requires_reindex`、`vector_hash_fallback_requires_reindex` | 返回 keyword/旧索引结果，并建议/排队 rebuild | 混用不兼容维度，继续声称 semantic 完整可用 |
| `TIMEOUT_OR_SATURATION` | `write_lane_timeout`、`*_reflection_lane_timeout`、队列 `queue_full` | 返回 503/失败 job/可重试标记 | 无限等待、吞掉取消、重复释放资源 |
| `TRANSIENT_STORAGE_FAILURE` | SQLite locked 重试耗尽、snapshot lock timeout | 有界重试后失败，保留现场证据 | 把部分提交或未写 manifest 当成功 |
| `INVALID_INPUT_OR_SCOPE` | `empty_query`、URI/过滤器非法、scope 不匹配 | 空结果/边界错误，保留请求原因 | 通过放宽 scope 偷渡越权结果 |
| `DERIVATION_FALLBACK` | `compact_gist_llm_exception:*`、rule-based/sentence fallback | 返回确定性派生物，降低 method/quality 并携带原因 | 把 fallback 冒充 LLM 产物或权威 L1 |

### 13.6 后续复用/升级/新建/废弃结论与验收契约

- **复用**：SQLite 事务/迁移、内容摘要、原子文件写入、文件锁、FTS/vector provider、统一结果中的降级字段、L0 审计 schema（runtime writer 待核）、L1 版本链和 L2 provenance。
- **升级**：把当前进程内 Write Lane、Cleanup Review、Index Worker 的语义接到运行核心；把审核 token 从“内存短凭证”升级为可审计、可过期、可重启恢复的授权/证据契约；把 archive 与 snapshot/DB 提交做恢复对账。
- **模块化**：建立唯一的记忆写入模块、检索模块、维护/归档模块、分层/流程派生模块；各模块只编排，不复制 provider 或直接写旁路表。
- **新建前置**：L3/L4 若要落地，先登记能力需求、定义层级/来源/审核/撤销/召回契约，再生成装配计划；当前核对不新建平台能力、不修改源码。
- **废弃/隔离**：废弃“进程内队列即可靠任务队列”“archive 即 L4”“LLM fallback 即同质量权威结果”“各模块自定义 review token/降级字典”等模式；保留为项目适配层历史兼容时必须显式标注。

验收契约应至少覆盖：同 session 并发写只有一条串行提交；跨进程快照锁与 manifest 原子性；快照/manifest 失败恢复；SQLite lock/timeout/rollback；审核 token 缺失、错误、过期、重复消费和重启失效；归档幂等且不硬删；队列满/取消/worker 重启后的可观测状态；向量 backend/维度/model 漂移的 rebuild 建议；L0-L2 provenance 完整、L3/L4 未定义时不误报已实现；所有失败返回稳定原因并完成资源释放。

### 13.7 后续验证边界

- 当前核对已完成目标项目源码、`ARCHITECTURE.md` 和旧细探的静态交叉核对；未修改旧细探、源码、配置、依赖或测试。
- 本轮严格未使用 MCP。目标项目已有 `.codegraph`，已执行 `codegraph status` 与 `codegraph sync`，统计为 290 files、7,161 nodes、20,273 edges（Python 198、JSX 56、JavaScript 28、YAML 7、TypeScript 1），索引最新；CodeGraph 仅用于定位，结论仍以源码为准。
- 依照任务硬边界，当前核对没有运行依赖安装、服务启动、数据库写入、pytest、前端构建或 Git 操作；因此本节结论属于静态架构映射，不等价于运行验收。

## 14. 后续内部深挖收口：结构、检索、状态、模型、任务与终态

本节是后续对当前源码的补充收口，优先级高于初始的概览式描述。证据范围为 `backend/db/models.py`、`backend/db/sqlite_client.py`、`backend/runtime_state.py`、`backend/core/*_engine.py`、`backend/main.py`、`backend/run_sse.py` 及迁移/测试源码；未把 README、旧细探或设计 RFC 中的“应当”当成已经运行的事实。

### 14.1 记忆对象的真实结构与状态机

```text
URI(domain://path)
  → Path(domain, path, memory_id, priority, disclosure)
  → Memory(id, content, deprecated, migrated_to, vitality, access counters)
  → MemoryChunk(char range)
  → FTS5 / MemoryChunkVec / optional sqlite-vec
  → optional MemoryGist / L2 MemorySummary / ProceduralMemory
```

| 对象/状态 | 进入方式 | 可见性与转移 | 失败/恢复语义 |
|---|---|---|---|
| `Memory` 活跃版 | `create_memory` 插入正文，再插入 `Path`；`title` 不落 `memories`，由路径最后一段显示 | `deprecated=0` 才进入普通 read/search；一个 memory 可由多个 domain/path/alias 指向 | 外层 `session()` 正常退出 commit；异常或取消走 rollback；索引失败不会被文档层宣称为成功 |
| 版本 successor | `update_memory(content=...)` 无条件新建 Memory，旧版 `deprecated=1, migrated_to=new_id`，所有指向旧版的 Path 一次性改指 successor | 旧版留在版本链，review/diff/rollback 可见；CAS `expected_memory_id` 防止陈旧更新 | 版本冲突以错误返回；事务失败不应留下半条路径迁移；链损坏/循环由 `_resolve_migration_chain` 返回不可解析 |
| 路径元数据变更 | `priority`/`disclosure` 可不改变 Memory 正文 | 只改 Path；同一正文可保留多个别名及不同 disclosure/priority | 期望值不匹配时报冲突；快照/回滚另有 path-only 与 memory-content 两种范围 |
| orphan/deprecated | 删除路径可能留下 `deprecated=0` 但无 Path 的 orphan；更新/归档留下 deprecated 版本 | 普通检索过滤掉 deprecated；maintenance/sleep consolidation 扫描两类 orphan；永久删除需 review 边界 | archive 与永久删除不是同一动作；purged 来源由 L2 drill-down 返回 tombstone，而非静默消失 |
| gist/L2/procedural 派生 | gist 按 `(memory_id, source_content_hash)` upsert；L2 显式 `persist_draft`；procedural 可 `persist=True` 生成 draft | 派生记录携带 source ids/hashes、method、confidence、review_state、预算；procedural 只有 `human_reviewed` 可推荐 | source hash 可判 stale；来源 live/archive/purged 均保留状态；reject 记录不删除 |

`create_memory` 的 `index_now=True` 会在同一 SQLAlchemy session 内做 chunk/embedding 索引；`index_now=False` 只返回 `index_pending`，由运行态 worker 后续执行。`update_memory` 的 content 版本迁移会先清旧索引、再为 successor 建索引；只有 priority/disclosure 更新时不新建正文版本。这些是状态转移的实际分界，不应把“Path 更新”误写成“Memory 原地覆盖”。

### 14.2 存储、索引和检索的真实调用链

| 阶段 | 真实实现 | 关键副作用/边界 |
|---|---|---|
| 启动 | `SQLiteClient.init_db()` → `create_all` → legacy `migrated_to` 迁移 → `MigrationRunner.apply_pending` → embedding drift → FTS/vector probe → bootstrap indexes | `.init.lock` 跨进程串行启动；迁移 checksum/locked 重试；WAL 在网络文件系统风险下回退 DELETE；启动失败抛出，FastAPI 不进入服务态 |
| 分块 | `_chunk_content` 以 `RETRIEVAL_CHUNK_SIZE`/overlap 切片，保存 `char_start/char_end` | chunk 是检索物化，不是新的记忆层；旧版本索引必须清理，active memory 才参与默认索引 |
| embedding | `_get_embedding` 先查 `embedding_cache`，缓存键含 backend/model/dim/text hash；remote `/embeddings` 或确定性 `_hash_embedding` | 维度/模型不匹配只允许降级或建议 rebuild；不能把 hash fallback 冒充远程模型；provider chain 可按 fail-open/fallback 配置继续或 block |
| keyword | FTS5 `MATCH` + `bm25`；失败/不可用时转安全 LIKE；仍无结果时扫描 `memories.content/paths` 的 legacy LIKE | FTS 表不存在/查询表达式异常被显式标记；LIKE 对 `%/_` 转义；`m.deprecated=0`、domain/path_prefix/priority/updated_after 过滤在查询中执行 |
| semantic | query embedding → sqlite-vec native top-k 或 Python cosine/legacy scoring；先按当前 scope 检查 indexed dims/models | 当前范围内 mixed/mismatch/hash-fallback model 会加 `degrade_reasons`，必要时切 keyword；不扫描无关 scope 的向量以假装全库一致 |
| hybrid/rerank | keyword + semantic 结果按 memory/chunk 归并，按 priority/recency/path-prefix 等加权；可选 RRF、entity boost、HTTP reranker、MMR | reranker 只改排序，失败不阻断基础检索；MMR 失败回退已排序结果；结果带 `mode`/`requested_mode`/`metadata`/降级信息 |
| read/return | `read_memory_segment`/`get_memory_by_path` 只取 active memory，并可批量取 gist；search 返回 top rows 后 `_reinforce_memory_access` | read/search 会更新 `access_count`、`last_accessed_at`、bounded vitality；因此读取并非纯 SELECT；exact-URI recent-read cache 必须用 `created_at/children/priority/disclosure` state token 验证 |

检索入口的失败分叉是确定的：空 query 返回空结果并 `empty_query`；非法 mode 抛 `ValueError`；semantic/hybrid 无 vector backend 转 keyword；远程 embedding/reranker 的 408/429/502/503/504 或网络/超时错误最多三次、带 retry 元数据，耗尽后报告原因；embedding chain 最终可转 hash 或以 `embedding_provider_chain_blocked` 失败。结果中的 `degrade_reasons` 是契约字段，不是日志装饰。

### 14.3 模型调用与确定性 fallback 矩阵

| 调用点 | 真实模型输入/输出 | 限流、超时与失败结果 |
|---|---|---|
| intent | `classify_intent_with_llm` 构造 `temperature=0` 的 `/chat/completions` JSON 请求，期望 `intent/confidence/signals`；输入经 `_safe_prompt_payload` 和“不可信数据”系统提示清洗 | `INTENT_LLM_ENABLED` 关闭、base/model 缺失、lane timeout、HTTP/网络重试耗尽、空/非法 JSON、非法 intent 均回到规则 classifier，并带 `degrade_reasons`；默认规则结果才是可用基线 |
| write guard | `write_guard` 先 semantic + keyword；达到阈值直接 NOOP/UPDATE，未决时可调用 `/chat/completions`，期望 `ADD/UPDATE/NOOP/DELETE` 与 target | provider degraded 且未 fail-open 时直接 NOOP（fail closed）；LLM 关闭/候选为空/模型异常/响应非法不允许伪造决策，最终才按“无强重复信号” ADD；实际写入仍由 MCP/API 继续做 target/review 边界检查 |
| compact gist | `generate_compact_gist` 对 session flush summary 调 `/chat/completions`，期望 `gist_text/quality`，过短 summary 会跳过 | LLM disabled/config missing/短输入/超时/异常/空或非法响应均返回 `None`；调用方使用 extractive/sentence fallback，method/quality/reason 必须能区分 fallback 与 LLM |
| L2 layering | `LayeringEngine` 只接受注入的 `summarizer(bodies)`，不是自身持有 provider；期望 `(summary_text, confidence)` | summarizer 异常被捕获，转最多 600 字符的 rule-based bullet；`MemorySummaryDraft` 强制 source ids/hashes，默认 `draft`，不自动 persist |
| procedural | v1 `_extract_steps` 只扫描 L1 正文中的 bullet/ordered lines，`LLM_PATTERN` 只是枚举候选，不等于当前实现调用 LLM | 缺少 source、无步骤、非法状态直接拒绝；成功默认写 `draft`，只有审核后推荐；不要把 procedural 的“流程提取”写成已启用的 LLM workflow |
| compression/forgetting | compression 是预算/可替代性 SELECT 预览；forgetting 是 vitality 指数模拟 + candidate | compression v1 不写表、不排 worker；forgetting 只有 `approve_archive` 经过 token validator 才写 archive/deprecated；模拟和候选失败不能造成删除 |

所有 HTTP provider 共用 `httpx.AsyncClient`：`RETRIEVAL_REMOTE_TIMEOUT_SEC` 默认 8 秒，`_post_json` 固定最多 3 次尝试，响应 408/429/502/503/504 或连接/读写/PoolTimeout 才可重试，非重试错误立即返回。`SQLiteClient.close()` 负责 `aclose()` remote client，再 `engine.dispose()`；这是服务 shutdown 的资源 owner，不能由各引擎自行关闭共享 client。

### 14.4 运行态、任务状态与资源所有权

| 运行对象 | 状态/并发 | 取消、超时、崩溃/重启 |
|---|---|---|
| `WriteLaneCoordinator` | session lane 串行 + global semaphore（默认 concurrency=1）；等待、active、成功/失败、p95 和 last_error 仅进程内统计；SQLite lock 有界指数退避 | acquire 超时 30 秒转 `write_lane_timeout`；`CancelledError` 记录 cancelled 并在 finally 减 waiting/active、release semaphore、清理空 session lock；进程崩溃不保留队列，重启只能按 DB/snapshot/index_meta 对账 |
| `ReflectionLaneCoordinator` | optional intent/gist/guard 共用有界 semaphore（默认 2，acquire 默认 20 秒），各 operation 统计 | lane 饱和转 `reflection_lane_timeout`，调用方 fallback；`finally` 释放 active semaphore。取消会释放资源，但当前 `except Exception` 不会像 Write Lane 一样把 `CancelledError` 记为失败指标，这是可观测性缺口，不应宣称“取消已完整计数” |
| `SessionSearchCache` / `SessionRecentReadCache` | 纯进程内 session-first 命中缓存；hits 上限 200/session、128 sessions，recent exact-read 默认 TTL 15 分钟；stale hit 按 half-life*8 清理，超限 LRU-like 淘汰 | 版本 state token 不匹配会删除 exact-read entry；进程退出全部丢失，不是权威存储；查询必须允许 cache miss 回源 DB |
| `SessionFlushTracker` | 每 session 最多 80 条、128 sessions；达到至少 6 events 且约 6000 chars 才建议 flush；仅保留截断后的文本 | `mark_flushed` 才清除；shutdown 调 `drain_pending_flush_summaries(reason=runtime.shutdown)` 是 best-effort，失败只告警，因此未 flush 内容可能丢失，不能称为 durable queue |
| `CleanupReviewCoordinator` | review record/token/confirmation phrase/TTL（默认 900 秒）全在内存，最多 64 pending；consume 在锁内一次性移除，防重复消费 | token/phrase/过期/不存在拒绝；进程重启所有 review 失效；高风险 archive/delete 的事实仍由 DB review_state/token fingerprint 及事务承载 |
| `VitalityDecayCoordinator` | 每进程 single-flight；同一任务由 `create_task` 执行，其他调用 `shield` 等待；默认 600 秒检查间隔，DB `index_meta` 再做每天一次门禁 | 调用方取消不会取消 shield 后的 decay task；task 自身异常写 degraded last_result 并清 inflight；进程崩溃后由 DB day key 和下一次启动重新判断 |
| `IndexTaskWorker` | bounded queue 默认 256；`reindex_memory` 按 memory 去重，rebuild/sleep 各单飞；job 状态 `queued → running → succeeded/failed/dropped/cancelled`，recent jobs 默认 30 | queue full 立即 dropped；queued cancel 会移出队列/置 cancelled；running cancel 置 cancelling 并 cancel execution task；`wait_for_job` 超时只返回当前状态，不取消任务；worker shutdown cancel runner。事件循环更换时 queued 任务尝试重入新队列，running/non-final 标 `failed:event_loop_reset` |
| `SleepTimeConsolidator` | 默认 1800 秒调度；sleep job 去重；orphan scan、dedup preview/apply、cleanup preview、fragment rollup，最后 rebuild index | 子步骤异常转 degraded reason 并继续其他阶段；dedup/rollup apply 默认关闭；queue full 30 秒重试，不无限重排；无持久任务表，崩溃中断的 sleep job 不可恢复为“已完成” |

资源责任边界：`SQLiteClient.session()` 在 `async with` 正常退出 commit，任何 `BaseException` rollback；SQLAlchemy engine 和共享 HTTP client 只由 `SQLiteClient.close()` 释放。`IndexTaskWorker._run_loop` 在执行任务 finally 中清 active task 并 `queue.task_done()`；快照 `FileLock`、manifest 临时文件和 SSE anyio streams 也在 finally/上下文管理器中释放。FastAPI lifespan 关闭顺序是 drain flush → `runtime_state.shutdown()` → `close_sqlite_client()`；SSE transport 另在 response finally 关闭 reader/writer、清 session/rate-limit，并支持 `close_active_streams()`。

### 14.5 失败、超时、取消、崩溃矩阵

| 场景 | 当前实现结果 | 不能过度推断的部分 |
|---|---|---|
| 非法 URI/空正文/超大输入/只读 `system://` | MCP 边界拒绝；create/update 不进入持久化；空检索返回 `empty_query` | 不等于所有内部 SQLiteClient 入口都自行完成同等 URI 校验，公开入口与内部 helper 要分开看 |
| 重复/相似写入 | Write Guard 语义阈值：semantic ≥.92 NOOP、≥.78 UPDATE；keyword ≥.82 NOOP、≥.55 UPDATE；provider degraded 默认 NOOP | 阈值决策不是事实正确性证明；LLM guard 关闭时不能宣称有语义裁决 |
| SQLite lock/事务异常 | Write Lane 最多配置次数重试；session context rollback；最终错误与 metrics 保留 | rollback 只保证当前事务，不自动恢复外部快照或已发出的 provider 请求 |
| provider timeout/HTTP 429/5xx/坏 JSON/坏维度 | 3 次有限重试后 `degrade_reasons`；semantic/hybrid 可 keyword/hash fallback；reranker 只放弃 rerank；LLM 回规则/抽取 | 没有熔断器、持久重试队列或跨进程 provider 状态；调用方必须读取 degraded 字段 |
| 写 lane/reflection lane 饱和 | 分别返回 `write_lane_timeout` / `reflection_lane_timeout`；写入失败，反思走 fallback | `wait_for_job` timeout 不是取消；反思取消指标存在缺口 |
| index queue full / job cancel | job 显式 `dropped` 或 `cancelled`，memory pending/dedup 指针清理；running 取消可能由底层 client 自己响应取消 | job 状态只在内存；没有跨进程 durable queue，重启恢复依赖 drift/bootstrap 重新发现 |
| snapshot lock/manifest/临时文件失败 | lock timeout 抛明确信号；manifest 保存失败尝试恢复旧 bytes 或删除新资源；原子 replace | DB transaction 与文件快照没有一个跨资源的两阶段提交；必须靠恢复扫描/对账，不可宣称全局原子 |
| 宿主取消/事件循环切换 | Write Lane finally 释放锁；Index worker 将非 final job 标 `event_loop_reset`，queued 尝试迁移；SSE response finally 关闭流 | 进程硬杀没有 finally；缓存、review、队列、未提交 flush 会丢失 |
| 进程崩溃/重启 | SQLite 已 commit 数据由 DB 保留；启动 init lock/migration/checksum/quick check；embedding drift 可 enqueue rebuild | 没有通用崩溃恢复日志或 durable job ledger；未提交事务、内存任务和 runtime counters 不可恢复 |
| 部分派生/来源被归档或 purge | provenance 仍返回 live/from_archive/purged；L2 stale hash 可识别；procedural reject 留审计 | L3/L4 没有独立恢复语义；archive 是横切生命周期，不是更高层级 |

### 14.6 L0-L4 最终裁决与证据等级

| 层级 | 最终裁决 | 证据等级 |
|---|---|---|
| L0 | `access_log` 的表、索引、迁移和模型注释已实现；但当前工作树没有发现运行时写入调用点，因此是 **schema/intent 已实现，采集链路未证实** | 部分实现；需运行或补源码 writer 后才可称 live observability |
| L1 | `memories`/`paths`/`memory_chunks`、successor 版本链、active/deprecated 过滤、read/search/rollback 真实存在 | 已实现（当前核对仅静态核对，未运行） |
| L2 | `memory_summaries` + `LayeringEngine` provenance/draft/persist/drill-down；gist 是正交的单记忆派生表，不等同 L2 topic summary | 已实现但 LLM provider 是可选，rule fallback 是有效实现 |
| L3 | 无 `L3` 枚举/表/公开工具；`procedural_memories` 是独立流程派生表，默认 draft，human-reviewed 才推荐 | 候选/待核，禁止写成项目已定义 L3 |
| L4 | 无 L4 表、索引、状态或公开契约；`archived_memories` 是 L1 生命周期副本，`purged` 是来源 tombstone | 未实现/待定义，禁止把 archive 或 stable rule 想象成 L4 |

最终不变式：**L1 是唯一权威正文；L2/gist/procedural 不能脱离 provenance 独立成为真相；L0 只能作为观测输入；archive/purge 横切生命周期而不是 L4。** 任何新接入都必须先读 `deprecated`、`review_state`、source hash、mode/degrade 字段和 job 状态，再决定是否写入或推荐。

### 14.7 后续验收边界

- 已逐条核对旧细探的核心主张：旧细探关于“压缩语义无损”“四引擎全套自动化”“依赖嵌入服务必选”“MIT 可自由借鉴”均不能作为当前实现事实；本文件保留了证据边界。
- 当前核对补足了旧文档没有展开的 memory/path/version/orphan 状态、缓存 TTL/淘汰、provider retry/timeout、LLM 调用与 fallback、worker job/cancel/event-loop reset、session/HTTP/SSE/lock 释放，以及 crash 后的非持久边界。
- 特别更正 L0：迁移和模型定义了日志意图，但当前核对源码搜索未找到 runtime writer；后续若要宣称 L0 live，必须补 `access_log` 写入的源码/运行证据，而不是只依据 `0004` 注释。
- 当前核对仍未安装依赖、启动服务、写入数据库、运行 pytest/npm/build/e2e；所有“已实现”均指源码存在，不是运行通过。
- 仅修改本文件；`细探-Memory-Palace.md` 保留且未改，源码、依赖、配置、测试、README、Git 均未改。

## 15. 本轮现场收口记录（2026-08-22）

| 项目 | 现场证据 | 结果 |
|---|---|---|
| 远程同步 | `git fetch origin --prune`、`git pull --ff-only` | `Already up to date` |
| 当前提交 | `git rev-parse HEAD` | `56c9bed39957f615da0b66b5e1459281d8fd1fef` |
| CodeGraph | `codegraph status`、`codegraph sync` | 290 files / 7,161 nodes / 20,273 edges；索引最新 |
| 文档行数 | `wc -l ARCHITECTURE.md` | 当前超过 500 行 |
| 差异检查 | `git diff --check -- ARCHITECTURE.md` | 本轮执行退出码 0 |

本轮严格未使用 MCP，只使用 shell、git、CodeGraph CLI 和源码静态证据。审计覆盖记忆图/事件和版本链、四引擎检索、SQLite/向量/快照、模型 provider、FastAPI/CLI/MCP/控制台、写审查与回滚、队列/并发、SSE/锁/缓存资源及测试部署边界；只修改平台研究文档，源码 checkout 未改。

未验证：依赖安装、pytest/contract/e2e、真实 SQLite/向量 backend、LLM/embedding/reranker、API/MCP handshake、SSE 断连、重复并发写、超时取消、快照恢复、进程强杀、缓存/锁/临时文件残留和性能 benchmark。静态源码与 CodeGraph 结果不等于运行通过。
