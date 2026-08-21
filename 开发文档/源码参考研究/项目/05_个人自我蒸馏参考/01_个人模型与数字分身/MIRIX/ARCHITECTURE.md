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

- Local CodeGraph was initialized in this repository and indexed 327 files,
  6,572 nodes and 17,603 edges.
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
