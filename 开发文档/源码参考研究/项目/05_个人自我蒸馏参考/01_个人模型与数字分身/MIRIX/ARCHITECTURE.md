# MIRIX Architecture: Source Audit

> Status: static source audit, 2026-08-21. This document describes the current
> repository, not a target platform design. A statement that a test or function
> exists is not a statement that it passed at runtime.

## 1. Executive Summary

MIRIX is an async-first, memory-augmented multi-agent service. Its normal path
is:

```text
REST / RemoteClient / LocalClient
  -> authentication, client/user/scope context
  -> AsyncServer
  -> Agent or MetaAgent
  -> LLM response and tool calls
  -> memory manager
  -> SQLAlchemy ORM and authoritative database
  -> optional Redis cache/search projection
```

`/memory/add` is asynchronous from the caller's perspective: it serializes a
protobuf `QueueMessage` and returns queued semantics. The default transport is
an in-process `MemoryQueue`; Kafka is optional. `/memory/add_sync` calls
`AsyncServer.send_messages()` directly and returns processed semantics.

The most important boundary is negative: the source has no durable
`AgentRun` model or complete run state machine. `AgentState` is persistent
agent configuration/reconstruction material, an `Agent` is an in-memory
runtime, `AgentStepResponse` is a step result, and `Step` is a token/usage audit
row. Queue messages and worker tasks are transient processing infrastructure.

The repository contains partial lifecycle handling: bounded LLM retries,
worker cancellation/cleanup, sandbox timeouts, temporary-file cleanup, Redis
fallback, and Langfuse flush. It does not establish durable task state,
attempt/lease/dead-letter records, end-to-end cancellation propagation,
idempotency, or crash reconciliation.

## 2. Runtime Topology

```text
Clients
  - mirix/client/remote_client.py      HTTP async SDK
  - mirix/local_client/local_client.py in-process adapter
  - mirix/sdk.py                       compatibility facade
  - dashboard/                         React/Vite UI
             |
             v
FastAPI app: mirix/server/rest_api.py
  lifespan -> ensure tables -> optional Redis -> defaults -> queue -> Langfuse
             |
             v
AsyncServer: mirix/server/server.py
  managers, agent loading, per-agent coordination, send_messages/_step
             |
       +-----+------------------+
       |                        |
       v                        v
MemoryQueue/KafkaQueue      direct send_messages
QueueWorker asyncio.Task    /memory/add_sync
       |                        |
       +-----------+------------+
                   v
Agent / MetaAgent / specialized Agent subclasses
  -> LLMClient, tools, memory managers, messages, Step audit
                   |
                   v
SQLAlchemy ORM -> PostgreSQL / SQLite / PGlite
                   +-> optional Redis cache/vector projection
```

### 2.1 Repository responsibilities

| Area | Current responsibility |
|---|---|
| `mirix/server/` | FastAPI routes, lifecycle, `AsyncServer`, database startup |
| `mirix/client/`, `mirix/local_client/` | HTTP and in-process client adapters |
| `mirix/agent/` | Agent loop, MetaAgent coordination, message queue, sandbox dispatch |
| `mirix/services/` | Async managers for agents, messages, blocks, users, clients, tools, files, six structured memories, raw memory and Auto-Dream |
| `mirix/schemas/` | Pydantic API/config/message/memory/agent models |
| `mirix/orm/` | SQLAlchemy tables, relationships, access predicates and indexes |
| `mirix/queue/` | Memory/Kafka queue abstractions, protobuf messages, workers and cleanup |
| `mirix/database/` | Async database helpers, Redis client and cache provider registry |
| `mirix/llm_api/` | LLM configuration and client implementations |
| `mirix/functions/` | Built-in tools, MCP client and generated tool wrappers |
| `mirix/jobs/` | Standalone raw-memory cleanup script |
| `tests/` | Unit and integration tests; external services are required for some files |

## 3. Memory Model and Data Ownership

MIRIX product documentation says “six memory components”. The persistence
boundary currently contains six structured types plus independent `RawMemory`:

| Type | Schema/ORM/manager | Data and retrieval boundary |
|---|---|---|
| Core | `schemas/block.py`, `schemas/memory.py` / `orm/block.py` / `BlockManager` | Prompt blocks (`label`, `value`, `limit`, scope tags); no embedding required; `Memory.compile()` renders Jinja prompt text |
| Episodic | `episodic_memory.py` / `orm/episodic_memory.py` / `EpisodicMemoryManager` | Events with `occurred_at`, actor, summary/details and two embeddings |
| Semantic | `semantic_memory.py` / matching ORM / `SemanticMemoryManager` | Names, summaries and details; three embedding fields |
| Procedural | `procedural_memory.py` / matching ORM / `ProceduralMemoryManager` | Procedure summary and JSON steps; summary/steps embeddings |
| Resource | `resource_memory.py` / matching ORM / `ResourceMemoryManager` | Title, summary, type and content; summary is embedded, content is not |
| Knowledge Vault | `knowledge_vault.py` / matching ORM / `KnowledgeVaultManager` | Sensitive value plus caption/source/sensitivity; caption is embedded, secret value is not |
| RawMemory | `raw_memory.py` / `orm/raw_memory.py` / `RawMemoryManager` | Unextracted context with timestamps, tags and optional context embedding; separate TTL/lifecycle |

All memory records carry user/organization ownership; many also carry agent,
client and `filter_tags`. Client `write_scope` is injected on writes and
`read_scopes` are passed into reads. Tests cover several scope and isolation
paths, but test presence does not prove deployment behavior.

The authoritative write path is manager -> ORM -> database transaction. Redis
is an optional acceleration layer. Cache providers are registered globally;
when no provider is active, managers fall back to the database. A cache hit is
not an authorization decision and must not replace scope filtering.

## 4. Agent, AgentRun, Step, and MetaAgent

### 4.1 Actual state layers

| Layer | Evidence | Meaning |
|---|---|---|
| `AgentState` | `mirix/schemas/agent.py`, `orm/agent.py` | Durable agent configuration: type, prompt, model/embedding config, tools, rules, message ids and parent relationship |
| Agent runtime | `AsyncServer.load_agent()`, `mirix/agent/agent.py` | In-memory object holding actor/user/scope, managers, core blocks and chaining state |
| Step result | `AgentStepResponse` | Messages, `continue_chaining`, `function_failed`, warning and usage for one logical step |
| Step audit | `StepManager.log_step()` / `orm/step.py` | Provider/model/context/token usage and tags; not a task state record |
| AgentRun | No matching durable model found | Not currently implemented as a unified persistent run entity |

`Agent.inner_step()` performs at most one LLM call, handles tool calls and
persists messages and a Step row. The outer `Agent.step()` may chain multiple
steps. `MAX_CHAINING_STEPS` defaults to 10. Context pressure uses a 0.75
warning threshold, summarizes toward 0.1 pressure, and keeps the configured
recent messages. LLM empty-response retries default to three attempts with
configured backoff and maximum delay.

The source does not prove a durable run id, parent run, lease, heartbeat,
idempotency key, final-state table, checkpoint replay, or recovery record. Do
not call `AgentState` or `Step` an `AgentRun`.

### 4.2 MetaAgent composition

`MemoryAgentStates` and `MEMORY_AGENT_CONFIGS` currently define ten
memory-related slots:

```text
episodic, procedural, knowledge_vault, meta_memory, semantic,
core, resource, reflexion, background, auto_dream
```

`MetaAgent.initialize()` loads existing agents or creates them, updates tools,
prompts and LLM configuration, then creates ordinary `Agent` runtimes. A
default `MetaAgent.step()` routes to `meta_memory_agent`; a named step routes
to that child. `MetaAgent.send_message_to_agent()` uses the separate
`mirix/agent/message_queue.py`, which must not be confused with
`mirix/queue/`.

There is intentional entry-point drift: `CreateMetaAgent` defaults to nine
agents and omits Auto-Dream, while `MEMORY_AGENT_CONFIGS` has ten slots and
`AutoDreamManager` lazily creates an Auto-Dream child. Documentation must name
the entry point before stating a child-agent count.

## 5. Tools, MCP, Providers, and Model Boundaries

### 5.1 Tool execution

The five actual tool branches are `MIRIX_CORE`, `MIRIX_MEMORY_CORE`,
`MIRIX_EXTRA`, `USER_DEFINED`, and `MIRIX_MCP`.

- Built-in branches resolve callables from fixed MIRIX modules and apply
  argument filtering/validation before execution.
- `USER_DEFINED` uses `ToolExecutionSandbox`; the local path creates a
  temporary Python script, executes asynchronously, enforces a 60-second
  timeout and deletes the script in `finally`. E2B is an optional remote path.
- `MIRIX_MCP` discovers tools, stores generated Python wrapper source and JSON
  schema, then `Agent._execute_mcp_tool()` executes stored source with `exec`
  in the agent process. This is a current security risk, not an isolation
  guarantee.
- Gmail confirmation is a tool-specific callback, not a global side-effect
  policy.

### 5.2 Provider facts

`LLMConfig` declares a wider endpoint vocabulary than the current
`LLMClient.create()` factory. The factory directly handles only `openai`,
`azure_openai`, `anthropic`, and `google_ai`; unsupported values return
`None`. Legacy `llm_api_tools.create()` has a different set of branches.
Declared provider names, model lists and dependency entries therefore do not
prove executable support.

Embedding selection has separate branches in `mirix/embeddings.py` for OpenAI,
Google AI, Azure, Hugging Face and Ollama, with chunking and bounded retry
helpers. It does not prove that every configured model, dimension or vision
capability is reachable. Vision/file message normalization exists, but vision
provider negotiation is not a universal contract.

## 6. Database, Index, Cache, and Lifecycle

`ensure_tables_created()` runs `Base.metadata.create_all` at startup except on
the PGlite path. Database selection is configuration-driven: explicit
PostgreSQL settings use async PostgreSQL, otherwise SQLite/aiosqlite is used;
PGlite is a separate connector path. `init.sql` enables extensions and does
not create all business tables. There is no confirmed migration history or
rollback protocol in this repository.

PostgreSQL can use pgvector, full-text/trigram, JSONB and scope/time indexes.
SQLite retains ordinary indexes and fallback search paths. Search method is a
request/manager choice (`embedding`, `bm25`, or legacy `string_match`), not a
fixed three-way fusion. `memory_type=all` aggregates multiple manager calls.

Redis startup is best effort: disabled, missing, ping failure or index failure
logs a warning and the service continues. Blocks/messages use hash-shaped
cache data; structured memory uses JSON/vector projections. Cache invalidation,
scope-key completeness and concurrent consistency are not globally proven.

Shutdown flushes Langfuse and stops queue workers. Queue cleanup is idempotent
at the manager level, but startup `create_all` and optional providers are not
equivalent to a migration or recovery system.

## 7. Queue, Status, Failure, Cancellation, and Recovery

### 7.1 Queue behavior

`mirix/queue/config.py` defaults to `QUEUE_TYPE=memory`, one worker, and
auto-start enabled. With more memory workers, `PartitionedMemoryQueue` uses
hash or round-robin partitioning. Kafka is selected explicitly and uses
`aiokafka`; it is not the default proven production path.

`QueueWorker._process_message_async()` restores trace context, resolves the
actor and user, converts protobuf messages, and calls
`server.send_messages()`. Its broad exception handler logs the error and ends
that processing attempt. The source does not create a durable failed-task row,
retry record or dead-letter entry there. `CancelledError` stops the worker
loop, and `QueueManager.cleanup()` stops workers and closes the queue, but that
only describes process lifecycle.

### 7.2 State matrix: implemented versus absent

| Concern | Current evidence | Audit conclusion |
|---|---|---|
| Queued/running/final task state | Queue message plus worker task only | No durable task state machine confirmed |
| Failure | Agent returns tool failure details; worker logs exceptions | Local error reporting exists; durable failure/retry semantics absent |
| Retry | LLM/embedding/HTTP helpers retry bounded classes of errors | No general queue-task retry or attempt ledger |
| Cancellation | Worker/task cleanup can cancel asyncio tasks; sandbox waits with timeout | No proof API cancellation propagates through Agent, LLM, MCP, E2B, subprocess and DB transaction |
| Timeout | LLM settings, queue polling timeout, sandbox 60s timeout, HTTP retry/timeouts | Component-local limits exist; no one deadline contract |
| Recovery | Agent state and messages can be reloaded | No checkpoint replay, lease expiry reconciliation or crash recovery protocol |
| Idempotency | Queue manager initialization is idempotent | No request/task idempotency key for memory writes confirmed |
| Resource release | `finally` cleanup, worker stop, Langfuse flush, session contexts | Partial local cleanup; no global owner/registry/orphan audit |

The correct architectural interpretation is “transient message processing with
partial cleanup”, not “durable task execution”.

## 8. Auto-Dream

`POST /memory/auto_dream` calls `AutoDreamManager.run()` after resolving the
user and a parent meta agent.

1. The request accepts `core`, `episodic`, `semantic`, `resource`,
   `procedural`, `knowledge`, or `experience`; `experience` means episodic,
   semantic and knowledge together.
2. The default start is the latest episodic
   `auto_dream_checkpoint`, or approximately 30 days ago; end defaults to now.
3. Current fetchers use a limit of 500 and `use_cache=False`. Crucially,
   `_fetch_episodic()` passes `start_date=None` and `end_date=None`, and the
   other fetchers also do not apply the resolved dates. The window is recorded
   in logs/input metadata, but current implementation fetches all current
   records returned by each manager.
4. `dry_run=true` returns fetched counts without invoking the agent or writing
   a checkpoint. It is not a mutation preview with per-item diff statistics.
5. A non-dry run formats memory records, removes embedding fields, loads or
   creates `AutoDreamAgent`, runs one ordinary Agent step, and writes a
   checkpoint after that step.
6. The response reports fetched totals as `MemoryTypeStats`; these are not
   actual removed, merged or conflict-resolved counts. Actual consolidation,
   transactionality and partial-failure recovery are not proven.

This corrects the older `docs/ARCHITECTURE.md` and README wording that presents
time-window processing and successful merge/consolidation as established
behavior.

## 9. API, Configuration, and Documentation Conflicts

The following conflicts are resolved here by preferring current executable
source over historical prose:

| Topic | Older wording | Current source decision |
|---|---|---|
| Search | Fixed BM25 + vector + fuzzy “three-way” flow | Independent `embedding`, `bm25` and legacy `string_match` choices; `all` aggregates managers |
| Queue | Architecture prose emphasizes Kafka | Default is in-process memory; Kafka requires configuration |
| MCP | Arguments passed as-is/isolated tool | Stored wrapper source is executed with `exec` in the Agent process |
| Auto-Dream | Reviews a date window and returns consolidation statistics | Current fetches ignore dates, dry-run counts fetched items, response totals are approximate |
| Agent count | Six sub-agents or the `CreateMetaAgent` default | Ten `MEMORY_AGENT_CONFIGS` slots; nine-item create default; Auto-Dream may be lazy-created |
| Run state | Step/agent descriptions imply an execution record | No unified durable `AgentRun`; Step is usage audit |
| Ports | 8531, 8000 and test 8899 all appear | 8531 is Compose/README, 8000 is direct app path, 8899 is test instruction; runtime was not started here |
| Python metadata | Async-native/current package declarations | `pyproject.toml` and legacy `setup.py` still disagree on minimum Python version |
| Cleanup | Nightly scheduler/Celery-style wording | Repository has a standalone async cleanup script and REST path; no unified scheduler confirmed |

The root `ARCHITECTURE.md` is the current audit index. `docs/ARCHITECTURE.md`
remains historical reference material and is not treated as a second current
source of truth. README product claims are retained as product intent only
when executable code does not establish them.

## 10. Tests and Evidence Boundary

`pytest.ini` targets `tests/` and excludes integration tests by default.
The repository includes tests for queue behavior, memory managers, raw memory,
scope isolation, cache providers, client/agent isolation, temporal queries and
tool argument filtering. Redis and real-embedding/integration tests require
external services or credentials according to their README files.

This audit did not install dependencies, start PostgreSQL/SQLite services,
Redis, Kafka, an LLM, embedding provider, E2B, API server or dashboard, and did
not run pytest. Therefore no runtime pass, performance number, cache hit rate,
provider availability or recovery guarantee is claimed here.

Static evidence used for this revision:

- Target checkout CodeGraph is available and currently indexes 362 files,
  7,774 nodes and 21,387 edges (node:sqlite, WAL). This map was refreshed with
  `codegraph status`, `codegraph sync`, and targeted `codegraph explore` calls;
  final claims remain grounded in current source files and tests.
- Direct source review covered memory schemas/ORM/managers, Agent and
  MetaAgent, tools/MCP/sandbox, provider factories, database/cache, queue and
  worker lifecycle, Auto-Dream, tests and all repository architecture notes.
- The only intended source-document change is this root `ARCHITECTURE.md`.

## 11. Future Verification Checklist

These are verification requirements, not claims about current MIRIX behavior:

1. Add a durable task/run contract with id, state, attempt, lease, deadline,
   cancellation, idempotency and final error/result.
2. Verify duplicate submission, worker crash, broker restart, cancellation,
   timeout, partial database write and restart reconciliation.
3. Verify scope-aware cache keys, post-commit invalidation, index readiness and
   fallback behavior against real PostgreSQL/Redis configurations.
4. Replace or isolate MCP source execution and verify process-group cleanup for
   local and remote sandboxes.
5. Make Auto-Dream date filtering, mutation statistics and checkpoint
   transaction semantics explicit, then test dry-run and partial failure.
6. Reconcile `LLMConfig` endpoint declarations with executable factories and
   document the selected deployment port and migration strategy.

## 12. 当前版本与目录导航

- 当前源码提交：`8cb06a62bbb7c478beb33dd4f2815696a72df482`；`main` 与 `origin/main` 已同步。
- 源码仓库存在未跟踪 `.codegraph/`、根 `ARCHITECTURE.md`，并有已删除的 `docs/ARCHITECTURE.md` 工作树状态；本次不修改这些源码仓库状态。

| 目录 | 主要职责 |
|---|---|
| `mirix/server/` | FastAPI、AsyncServer、DB/session、SSE |
| `mirix/client/`、`local_client/` | HTTP 与进程内 SDK |
| `mirix/agent/` | Agent、MetaAgent、记忆 Agent、工具和 sandbox |
| `mirix/services/` | 各 memory manager、用户/agent/tool/file 管理 |
| `mirix/orm/`、`schemas/` | SQLAlchemy 持久化和 Pydantic 合约 |
| `mirix/database/` | PGlite/PostgreSQL、Redis cache |
| `mirix/queue/` | Memory/Kafka queue、worker、protobuf |
| `mirix/llm_api/` | OpenAI、Anthropic、Azure、Bedrock、Cohere、Google、Mistral |
| `mirix/jobs/`、`observability/` | cleanup、Auto-Dream、Langfuse/trace |
| `dashboard/`、`evals/` | 管理界面、评估和 token 实验 |

## 13. API 与调用链证据

| 入口 | 源码位置 | 语义 |
|---|---|---|
| `GET /health` | `mirix/server/rest_api.py:715-736` | 进程健康，不证明 memory 提交 |
| `POST /memory/add` | `rest_api.py:253-267` | QueueMessage 入队，返回 queued |
| `POST /memory/add_sync` | memory handlers | 直接等待 `send_messages` |
| `POST /agents/{agent_id}/messages` | `rest_api.py:1074-1177` | Agent 对话和 SSE/usage |
| `/memory/search_*` | `rest_api.py:3300-4300` | 六类 memory + core 检索 |
| `/memory/raw*` | `rest_api.py:5100-5663` | raw 增删改查/cleanup |
| `/memory/auto_dream` | `rest_api.py:5708-5790` | 后台记忆整理 |
| `/agents`、`/tools`、`/blocks` | `rest_api.py:741-1300` | 资源 CRUD |
| `/clients`、`/users`、`/organizations` | `rest_api.py:1334-1805` | 多租户资源 |
| `/admin/auth/*` | `rest_api.py:6025-6219` | dashboard JWT 注册/登录 |

真实写入链：client scope/auth -> FastAPI context -> `QueueMessage` -> MemoryQueue/Kafka -> worker -> `AsyncServer.send_messages` -> `_step` -> Agent/LLM/tools -> memory manager -> SQL ORM -> optional embedding/Redis projection -> queued/processed/SSE。队列消息和 worker task 是瞬态，没有统一 durable job 状态。

## 14. 记忆、数据库与检索边界

| 类型 | ORM/manager | 注意事项 |
|---|---|---|
| Episodic | `orm/episodic_memory.py` | 事件/时间/来源/embedding |
| Semantic | `orm/semantic_memory.py` | 稳定事实和向量 |
| Procedural | `orm/procedural_memory.py` | 行为、技能、策略 |
| Resource | `orm/resource_memory.py` | 文件和外部资源 metadata |
| Knowledge vault | `orm/knowledge_vault.py` | 私有知识和 scope |
| Raw | `orm/raw_memory.py` | 原始内容，cleanup 可删除 |
| Block/Core | `orm/block.py` | Agent 可编辑核心上下文 |

SQL 是主要权威事实源；Redis cache/向量是投影。写 SQL、生成 embedding、刷新 Redis 和删除 raw 并非同一事务。scope/client/user/agent 过滤必须同时进入 SQL 与 cache key，否则可能跨租户泄漏旧结果。

## 15. Agent、工具和资源所有权

`Agent` 是内存运行时，`AgentState` 是可重建配置；`MetaAgent` 通过工具协调专业 Agent。`tool_validators.py` 检查参数/权限，`tool_execution_sandbox.py` 管理超时、子进程和临时文件；超时只请求停止，不保证外部进程、HTTP 或 LLM 立即终止。LLM provider 由 `llm_api/llm_client.py` 及各 provider client 调用，重试不会回滚 Step、memory 或外部副作用。

| 资源 | owner | 风险 |
|---|---|---|
| SQLAlchemy session | request/manager | 跨 memory/cache 非原子 |
| Redis pool | lifespan/cache provider | stale、断连和关闭顺序 |
| Memory/Kafka consumer | queue worker | offset、重复消费、重启恢复 |
| per-agent lock | lock manager | 只在进程内互斥 |
| LLM HTTP client | provider factory | timeout、retry、取消 |
| sandbox process/temp dir | tool sandbox | 子进程组和强杀清理 |
| Langfuse client | observability | flush 失败可能丢 trace |

## 16. 测试、部署和验证矩阵

| 目标 | 位置 | 当前结论 |
|---|---|---|
| API/Agent | `tests/`、`mirix/server` | 未本轮执行，依赖 DB/LLM |
| memory managers | `services/*_memory_manager.py`、`evals/` | eval 分数不等于生产门禁 |
| queue | `mirix/queue` | Kafka/崩溃/重复消费需实测 |
| Redis/vector | database/config/docker compose | 断连、TTL、索引一致性未实测 |
| LLM | `llm_api/*` | key、网络、模型未实测 |
| dashboard | `dashboard/` | 前端构建/登录未执行 |
| deployment | Dockerfile、compose、startup.sh | 仅部署路径声明 |

本轮未安装依赖、未运行 pytest、未启动 FastAPI/PostgreSQL/Redis/Kafka、未调用真实 LLM、未构建 dashboard。不能以 health/HTTP 200、mock 或 eval 结果声明成功。

## 17. 平台映射与最终裁决

| MIRIX 能力 | 平台落点 | 限制 |
|---|---|---|
| 六类 memory + raw | 模块库记忆编排 | SQL/向量/cache owner 统一 |
| Agent/MetaAgent | 项目适配层 Agent | 外部副作用不可回滚 |
| Memory/Kafka queue | 运行核心任务调度适配 | 需 job id、lease、attempt、死信、恢复 |
| ORM/schema | 支持库数据库适配 | 正式代码不得直导入实现 |
| Redis cache | 支持库缓存 provider | stale/fallback/失效契约 |
| REST/Remote/Local client | 统一网关适配 | queued 与 committed 分离 |
| tools/sandbox | 受管进程能力 | 权限、超时、进程组和临时资源有界 |

MIRIX 适合作为多租户 Agent 与分层记忆系统参考；源码没有完整 durable AgentRun 状态机、统一幂等、跨存储事务、全链路取消或崩溃对账。平台只能吸收 memory 分类、scope、manager、queue 和 API 适配经验，正式落地前必须补租约、任务状态、provenance、缓存失效、资源释放和真实验收。本文是平台侧唯一 MIRIX 架构文档。

## 18. 失败与恢复矩阵

| 场景 | 可能状态 | 需核对 |
|---|---|---|
| LLM timeout | Step 部分写入或无结果 | retry 是否重复 tool/memory 副作用 |
| worker crash | QueueMessage 已取出未提交 | broker offset、重启补偿、死信 |
| DB commit fail | SQL 未提交，cache 可能更新 | cache invalidation、重试幂等 |
| embedding fail | memory 行存在但向量缺失 | index readiness、重建任务 |
| Redis down | 回源 SQL 或错误 | stale 数据和连接池释放 |
| SSE disconnect | server task 仍运行 | request cancellation 是否传播 |
| sandbox timeout | 子进程仍存活 | process group kill、临时文件 |
| Auto-Dream crash | 部分记忆已变更 | dry-run、统计、checkpoint |
| delete memory | SQL/raw/cache/projection 分裂 | provenance 和跨表清理 |
| process kill | finally 不执行 | queue、session、LLM、trace 残留 |

## 19. 多租户与安全边界

- `get_client_from_jwt_or_api_key` 在 `rest_api.py:4830` 解析身份；client、organization、user、agent scope 进入 manager 查询。
- API key 记录在 ORM client_api_key，token 只在授权流程返回；日志和错误不得回显原始 key。
- LocalClient 绕过 HTTP middleware，调用方必须自行提供同等 user/client scope；不能把本地调用当作天然隔离。
- Memory search 的 all-users 管理接口应只对管理员开放；普通 memory endpoint 必须校验所属 client/user/agent。
- Redis key 必须含 scope 维度；若仅使用 memory id，跨租户 cache collision 会成为数据泄漏风险。
- 工具/sandbox 需要 allowlist、文件根目录、网络权限和超时；MCP/远程工具结果不能直接成为可信指令。

## 20. 队列和并发验收场景

1. 同 agent 并发提交两条消息，确认 `PerAgentLockManager` 保序且不同 agent 可并行。
2. worker 在 DB commit 前崩溃，确认 Kafka/MemoryQueue 的消息重投、重复写和最终状态。
3. queue 满载，确认是否有容量上限、背压、拒绝或仅内存增长。
4. API 客户端断开 SSE，确认 `_step`、LLM 请求、工具子进程和 DB session 是否释放。
5. Redis 断连后恢复，确认 cache miss 回源、写后失效和关闭不阻塞。
6. Auto-Dream 与用户消息同时执行，确认记忆锁、事务和排序。
7. 多进程部署，确认本地 per-agent lock 不被误当作跨进程互斥。

## 21. 运行核心映射要求

| MIRIX 现有事实 | 平台必须补齐 |
|---|---|
| QueueMessage/worker | job id、attempt、lease、deadline、cancel state |
| AgentState/Step | AgentRun durable state machine、parent/child lineage |
| memory manager | write contract、provenance、version、rebuild |
| Redis projection | authoritative commit point、stale/read barrier |
| LLM/tool | provider timeout、budget、idempotency、side-effect ledger |
| sandbox | bounded process group、temp root、force kill、evidence |
| Auto-Dream | scheduled lease、dry-run、checkpoint、partial failure |

不得从 MIRIX 的 manager 类名直接生成平台正式模块；必须先做能力搜索、复用决策、提供者登记、租约和受控验证。

## 22. 证据与维护规则

- 当前 `.codegraph/` 存在并已被目标仓库生成；本轮使用目标仓库 CodeGraph 定位 Agent、Memory、RawMemory、cache、queue 和 test 调用链，仍不以代码图替代源码逐文件证据。
- 远程同步以 `git fetch` 后 `main/origin/main` commit 为准；未跟踪源码文档和 `.codegraph/` 不得被破坏。
- 新增 memory 类型要同时更新 ORM、schema、manager、API、search、cache、delete 和 provenance 表。
- 新增 provider 要记录连接 owner、超时、重试、关闭、凭据、迁移和测试矩阵。
- 新增队列入口要记录 accepted/queued/running/committed/failed/cancelled 语义和查询方式。
- 任何“持久化”“恢复”“事务”“实时”“幂等”结论都必须有源码和运行证据双重支持。
- 运行验证必须保存命令、退出码、环境/数据库/Redis/Kafka 状态、测试数量和未验证项。
- 旧 `docs/ARCHITECTURE.md` 删除状态与根文档并存时，以当前 Git/worktree 事实为准，不主动恢复历史文件。

## 23. 本轮最终验证边界

本轮只完成源码、Git、代码地图和平台唯一文档的静态收口；没有启动服务、没有使用端口4780以外的辅助服务、没有安装依赖、没有执行外部 LLM/DB/Redis/Kafka。静态文档验证必须与后续真实运行验证分开记录，不能将平台测试或 CodeGraph 规模宣称为 MIRIX runtime 通过。

### 23.1 收口检查

- [x] 当前提交与远程分支已核对。
- [x] 目录、入口、记忆、Agent、任务、API、队列、资源和平台映射已写入本文件。
- [x] `.codegraph/` 与源码工作树未跟踪状态已保留。
- [x] 未创建旁路细探或第二份平台架构文档。
- [ ] 真实 DB、Redis、Kafka、LLM、sandbox、SSE 和并发恢复仍待执行。
- 文档行数达到500行以上，内容来自源码路径、接口、状态和验证边界。

## 24. 当前 checkout 收口记录

- 目标仓库：`~/Documents/Agent/github 源码参考/05_个人自我蒸馏参考/01_个人模型与数字分身/MIRIX`。
- 远程：`origin=https://github.com/Mirix-AI/MIRIX.git`，分支 `main`，`git pull --ff-only` 返回 Already up to date。
- 当前提交：`8cb06a6`（`Merge pull request #139 from Mirix-AI/feat/adaptive-session-tag-routing`）。
- 工作树边界：源码侧 `docs/ARCHITECTURE.md` 为既有删除状态；未跟踪 `.codegraph/` 与源码根 `ARCHITECTURE.md` 均保留，未恢复或删除。
- 本平台侧唯一修改对象：本 `ARCHITECTURE.md`；没有创建旁路细探文档。
- 本轮明确未使用任何 MCP，仅使用 shell、git、CodeGraph CLI 与静态源码/测试证据。
- 未验证：依赖安装、pytest、PostgreSQL/SQLite、Redis、Kafka、LLM、embedding、E2B、FastAPI、dashboard、SSE、并发、崩溃恢复和真实工具副作用。
