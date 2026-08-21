# Hindsight Architecture: Source-Fact Deep Study

> 研究对象：`/Users/hekunhua/Documents/Agent/github 源码参考/05_个人自我蒸馏参考/02_长期记忆与记忆操作系统/Hindsight`
>
> 研究方法：只读源码、迁移、配置和测试阅读；没有调用 MCP 或 Hermes，没有安装依赖，没有启动 API/worker/database，没有运行 pytest，也没有做进程或网络故障注入。
>
> 证据规则：本文把“源码直接可见”“测试源码声明”“未执行验证”严格分开。架构目标、注释中的意图、测试名称和本机真实行为不是同一等级的证据。

## 1. 结论摘要

Hindsight 是一个以 Python `MemoryEngine` 为中心的长期记忆数据面。REST、MCP、SDK、Control Plane、embedded daemon 和 coding-agents 集成最终围绕 API/engine 契约工作；默认存储是 PostgreSQL，记忆事实和关系由 `PostgresMemories` 管理，向量、文本、图和时间检索在一个 recall 编排中融合。

其可靠性边界不能概括成“有队列租约、可取消、崩溃自动恢复”。真实情况更窄：

- API 异步提交把 operation 行和 JSON task payload 放进 `async_operations`，当前提交路径将两者放在同一数据库事务中。
- worker 通过 `FOR UPDATE SKIP LOCKED` 领取 `pending` 且有 payload 的行，并在同一领取事务内写入 `processing`、`worker_id`、`claimed_at`。这是一次性 claim 标记，不是带心跳续租的 lease；源码中未见运行期间续租。
- worker 运行中的 task 若正常、显式 retry/defer、wall timeout 或异常退出，poller 会分别写 terminal/pending/failed；若进程被杀，后续依赖启动恢复、优雅退出释放、管理命令或维护路径，不能据此声称存在独立的全局过期租约扫描。
- 主动 `cancel_operation` 只接受 `pending`，不会把 `processing` 任务改成 cancelled。HTTP 客户端断开协作取消目前明确接到 recall/reflect；已经进入线程的 graph/rerank 计算不能被强杀。
- retain 的数据库写阶段可把 document、chunks、facts、entities、links 等放在同一数据库事务内，但昂贵的抽取、embedding、实体解析和 ANN 预读发生在写事务之外。外部 memory store、对象存储、LLM provider 与 PostgreSQL 之间没有天然的跨系统 ACID 事务；相关一致性依赖扩展自己的 transaction/witness 实现，不能由默认 Postgres 路径推导出来。
- batch parent 是 payload 为空的状态聚合器，children 的 parent linkage 位于 JSON metadata 而非外键。源码专门处理 worker/API 崩溃造成的 parent orphan，但这属于恢复扫描，不是提交时的跨行原子事实。

因此，Hindsight 可以作为“记忆领域契约 + PostgreSQL broker 任务实现”的参考，但不能把当前实现描述成一个已经通过生产级 crash consistency、跨库一致性或统一取消验收的任务平台。

## 2. 仓库范围与证据等级

### 2.1 实际研究范围

本轮以 `hindsight-api-slim/` 为主要运行时源码，辅以根目录入口、客户端、控制面、embedded、coding-agents、配置、Alembic migrations 和定向测试源码。重点实际读取了：

- `hindsight-api-slim/hindsight_api/api/http.py`
- `hindsight-api-slim/hindsight_api/api/__init__.py`
- `hindsight-api-slim/hindsight_api/engine/memory_engine.py`
- `hindsight-api-slim/hindsight_api/engine/retain/orchestrator.py`
- `hindsight-api-slim/hindsight_api/engine/retain/fact_storage.py`
- `hindsight-api-slim/hindsight_api/engine/retain/embedding_processing.py`
- `hindsight-api-slim/hindsight_api/engine/embeddings.py`
- `hindsight-api-slim/hindsight_api/engine/search/retrieval.py`
- `hindsight-api-slim/hindsight_api/engine/search/graph_retrieval.py`
- `hindsight-api-slim/hindsight_api/engine/search/fusion.py`
- `hindsight-api-slim/hindsight_api/engine/memories/base.py`
- `hindsight-api-slim/hindsight_api/engine/memories/postgres.py`
- `hindsight-api-slim/hindsight_api/engine/memories/pg/reads.py`
- `hindsight-api-slim/hindsight_api/engine/memories/pg/writes.py`
- `hindsight-api-slim/hindsight_api/engine/db/base.py`
- `hindsight-api-slim/hindsight_api/engine/db/ops.py`
- `hindsight-api-slim/hindsight_api/engine/db/ops_postgresql.py`
- `hindsight-api-slim/hindsight_api/engine/task_backend.py`
- `hindsight-api-slim/hindsight_api/worker/poller.py`
- `hindsight-api-slim/hindsight_api/worker/main.py`
- `hindsight-api-slim/hindsight_api/cancellation.py`
- `hindsight-api-slim/hindsight_api/liveness.py`
- `hindsight-api-slim/hindsight_api/config.py`
- `hindsight-api-slim/hindsight_api/migrations.py`
- `hindsight-api-slim/hindsight_api/models.py`
- 定向 Alembic migrations，尤其是 worker columns、cancelled status、retry、webhook、serialization、operation retention 和维护 routines
- 定向测试：`test_worker.py`、`test_worker_wall_timeout.py`、`test_worker_claim_connection_reuse.py`、`test_health_probes.py`、`test_recall_cancellation.py`、`test_retain_pipeline_cancellation.py`、`test_operation_status.py`、`test_operation_completion.py`、`test_operation_progress.py`、`test_async_retain_operation_id.py`、`test_retain_same_document_concurrency.py`、`test_graph_maintenance_queue_race.py`、`test_graph_maintenance_claim_serialization.py`、`test_schema_isolation.py`、`test_migrations_parallel_schemas.py`、BM25/embedding/graph/reflect/retain 相关定向测试

根目录当前未发现独立的旧“细探”文件。本文没有把不存在的旧笔记当作证据；如果外部归档有同名文件，必须重新逐条对照当前源码。

### 2.2 证据等级

| 等级 | 含义 | 本轮实例 |
|---|---|---|
| S0 | 文件/符号/SQL 直接阅读 | API 路由、task backend、poller claim、cancel 条件、迁移字段 |
| S1 | 测试源码存在，描述了预期或局部行为 | worker retry、disconnect token、schema isolation、graph race |
| S2 | 本轮实际执行成功 | 无；只要求并执行文档变更后的 `git diff --check` |
| S3 | 真实依赖/进程/数据库/故障注入 | 无；不能声称通过 |

## 3. 实际组件图

```text
HTTP REST / MCP / SDK / Control Plane proxy / embedded daemon / coding-agents
                              |
                              v
FastAPI routes + RequestContext + auth/precheck/audit/error mapping
                              |
                              v
MemoryEngine
  |-- retain_batch_async / submit_async_retain
  |-- recall_async
  |-- reflect_async
  |-- execute_task / operation status / cancel / retry
  |
  +--> retain orchestrator
  |      chunk -> LLM extraction -> normalize -> embedding
  |      -> entity/ANN pre-resolution -> DB write transaction
  |
  +--> recall retrieval
  |      query embedding + BM25/text + graph/link + temporal
  |      -> fusion/RRF -> rerank/score/MMR/token budget
  |
  +--> reflect agent
         mental models -> observations -> recall -> expand -> done/evidence

MemoriesExtension
  |-- PostgresMemories -> memory_units / memory_links / unit_entities
  |-- optional external memory store for memory/link ownership

DatabaseBackend -> PostgreSQL/Oracle dialect, tenant schema, pool, transaction
BrokerTaskBackend -> async_operations <- WorkerPoller/WorkerTaskBackend
```

这张图是当前源码关系，不是建议的拆分目标。`MemoryEngine` 仍然是大型应用编排器；`MemoriesExtension` 是 memory/link 存储 seam，但不替代 banks、documents、chunks、operations 等 PostgreSQL 对象。

## 4. API 到 engine 的真实调用链

### 4.1 retain

同步请求的主链：

```text
POST .../memories
  -> Pydantic RetainRequest
  -> precheck/auth/operation validator
  -> MemoryEngine.retain_batch_async()
  -> 按 strategy、document_id、update_mode 分组
  -> chunk/split
  -> retain.orchestrator.retain_batch()
  -> LLM fact extraction
  -> ProcessedFact 过滤、时间/context/metadata/tags 规范化
  -> embedding_processing.generate_embeddings_batch()
  -> Phase 1 entity resolution + semantic ANN（写事务外）
  -> 实际 UUID 生成和 entity/link remap
  -> document/chunk/fact/entity/link 写入
  -> transaction commit
  -> 返回 RetainResponse；可另提交 consolidation/graph maintenance operation
```

异步请求的主链：

```text
POST .../memories?async=true 或 files/retain
  -> _submit_async_operation()
  -> 事务内检查 bank、dedupe、INSERT async_operations(status=pending, task_payload=jsonb)
  -> 事务提交
  -> BrokerTaskBackend.submit_task() 对已存在 payload 的 row 实际为 no-op/update-null-only
  -> API 返回 operation_id
  -> WorkerPoller.claim_batch()
  -> MemoryEngine.execute_task(task_payload)
  -> retain_batch_async() / file conversion / batch child submission
```

`_submit_async_operation()` 已修复“先插 operation、后补 payload”的 crash window：当前完整 payload 在 INSERT 中写入。`BrokerTaskBackend` 仍保留对旧 caller 的 NULL payload 补写逻辑，但不是当前主路径的第二个提交事务。

### 4.2 retain 的事务边界

源码直接支持以下判断：

1. Phase 1 的实体解析和 semantic ANN 使用独立连接，发生在写事务之外，避免慢读持有写锁。
2. 写阶段把 document replace/delete、document upsert、memory facts、entity postings、links 以及相关 cleanup 放在调用方提供的数据库事务上下文中；`fact_storage` 明确要求 stale observation cleanup 在 active transaction 内、删除源 facts 之前执行。
3. 同一 document 的并发写由 `lock_document_for_write`/serialization key/数据库行锁共同限制；队列 claim 只允许同一 serialization key 的最旧、没有 processing peer 的任务进入。
4. 这保证的是同一数据库 backend 内的事务原子性，不是 LLM、embedding、外部 memory store、S3/GCS/Azure 和 PostgreSQL 的分布式事务。
5. 如果启用外部 `MemoriesExtension`，它可以拥有 facts/links，而 PostgreSQL 仍可能拥有 documents/chunks/entities。只有该扩展实现并完成 `begin_txn`、decision/witness 等协议时，才有跨 store 一致性证据；默认路径不能替代该证据。

### 4.3 recall

```text
POST .../memories/recall
  -> RecallRequest 校验 query/token/fact types/options
  -> RequestContext 注入 cancellation token（如有客户端断开）
  -> MemoryEngine.recall_async()
  -> query analyzer / temporal constraint
  -> query embedding
  -> retrieve_all_fact_types_parallel()
  -> MemoriesExtension.recall_unified()
       semantic: pgvector dense search
       BM25: PostgreSQL text-search/native extension 或配置 fallback
       graph: memory_links/entity expansion/link retriever
       temporal: occurred/mentioned time neighbor/window query
  -> fusion.py RRF/interleave
  -> combined score / optional cross-encoder reranker
  -> MMR/diversity + token budget
  -> optional entity/chunk/source-facts enrichment
  -> RecallResult
```

四条 retrieval arm 的候选在 store seam 返回，融合和预算在 engine/search 后段完成。`created_after/created_before` 在相关图扩展和检索路径中绑定 `updated_at`，是变更窗口，不是 `event_date`。`event_date`、`occurred_start/end`、`mentioned_at`、`updated_at` 和 query timestamp 是不同语义，不能合并为一个“时间字段”。

### 4.4 reflect

```text
POST .../reflect
  -> ReflectRequest/auth/precheck
  -> MemoryEngine.reflect_async()
  -> run_reflect_agent()
  -> LLM tool loop:
       search_mental_models
       search_observations (freshness/stale)
       recall (raw facts)
       expand (chunk/document context)
       done(answer, evidence ids)
  -> structured response/retry/trace
  -> ReflectResult
```

普通 reflect 是只读综合，不写 memory。`run_consolidation_job()` 才是 observation 的写投影；mental model refresh 是另一个 operation，可能是 full/delta/dry-run。directive 是显式规则，不能当 observation 来源事实。

## 5. 记忆数据模型与检索实现

### 5.1 memory bank

bank 是业务路由和配置边界，不是 tenant 隔离本身。`Bank` 保存 bank_id、name、disposition、mission 等；tenant/schema 由 `RequestContext`、`TenantExtension`、contextvar 和 `fq_table()` 共同决定。相同 bank_id 在不同 tenant schema 中不是同一行。

核心 PostgreSQL 对象包括：

- `banks`
- `documents`：原文/可选原文、content hash、retain params、tags
- `chunks`
- `memory_units`：text、embedding、fact type、context、metadata、事件/提及/变更时间
- `entities`、`unit_entities`、`entity_cooccurrences`
- `memory_links`：temporal、semantic、entity、causal 等 link
- `async_operations`
- mental model、knowledge base、directives、audit、LLM request、webhook 相关表

当前 schema 不能由 `models.py` 或初始迁移单独推导。`models.py` 只集中声明部分 ORM 模型；后续 Alembic 链继续增加 worker、cancelled、retry、webhook、serialization、retention、维护 routine 等字段和索引。

### 5.2 embedding

`Embeddings` 抽象要求 provider 提供 `initialize()`、`dimension`、`encode()`，并可区分 `encode_query()` 与 `encode_documents()`。源码包含 local SentenceTransformers、ONNX、远程/HTTP provider 等路径；可选 provider 的依赖和运行状态没有在本轮启动验证。

retain 对事实文本做日期和实体增强后生成向量，但数据库保存原始事实文本。query embedding 走 query 入口。embedding dimension 在 provider 初始化后检测，数据库列/索引必须与模型维度相容；“默认维度”只是初始迁移/配置值，不能当成所有部署的运行事实。

资源风险：本地模型初始化可能加载 CPU/GPU/MPS/ONNX 资源；源码有局部 allocator release 和初始化 timeout 配置，但本轮没有真实模型、GPU、远程 provider 或下载失败验证。

### 5.3 BM25/text

BM25/keyword arm 不是 Python 内存中的独立全文数据库，而是由 PostgreSQL text-search/native extension 路径执行，查询词可能经过选择性词项裁剪。Oracle 有不同 SQL/Text 适配；semantic-only fallback 是特定配置/后端行为，不能写成全局保证。BM25、tsvector、扩展索引和长 query timeout 的定向测试只构成 S1 证据。

### 5.4 graph

graph recall 从 semantic seeds 进入 `memory_links`、entity postings 和 causal/semantic/temporal link expansion。图扩展有 fanout/window/budget 限制；`graph_maintenance` 是异步任务，用于维护队列和 relink/prune。源码明确指出同一 bank 的 graph maintenance 要串行化，因为底层队列 claim 使用不带 `SKIP LOCKED` 的 `FOR UPDATE` 片段；这不是整个 worker claim 都没有 `SKIP LOCKED`，而是该内部维护队列的特殊锁语义。

## 6. async_operations 状态机

### 6.1 状态和字段

迁移链可确认的状态为：`pending`、`processing`、`completed`、`failed`、`cancelled`。关键字段为：

- `operation_id`、`bank_id`、`operation_type`
- `task_payload`：可序列化 JSON task；parent aggregator 可为 NULL
- `status`、`error_message`、`created_at`、`updated_at`、`completed_at`
- `worker_id`、`claimed_at`、`retry_count`、`next_retry_at`
- `result_metadata`：parent_operation_id、batch_id、progress、trace/结果等
- `serialization_key`：同 document retain 排序/串行化

### 6.2 真实转换

```text
提交
  -> pending(payload)

worker claim transaction
  -> processing(worker_id, claimed_at)

processing
  -> completed       executor 返回正常
  -> pending         RetryTaskAt；retry_count + 1；next_retry_at
  -> pending         DeferOperation；不增加 retry_count
  -> failed          wall timeout
  -> failed          未处理异常或恢复次数耗尽

pending
  -> cancelled       cancel_operation 仅在 status=pending 的条件下
  -> pending          retry_operation 从 failed/cancelled 重置

batch_retain parent
  -> payload=NULL 的聚合行
  -> children 全部 terminal 后 completed/failed
  -> startup reconcile 时无 children 则 failed(orphaned parent)
```

成功/失败的多数 poller 写入带 `WHERE status='processing'` 或先读取并加锁，因此迟到的 terminal 写不会正常覆盖已经完成的行。但 `cancel_operation` 的实现是“先 SELECT pending，再 UPDATE cancelled”，不是一个把 `status=pending` 放进 UPDATE 条件的完整 CAS；两个请求/worker 之间仍需以数据库并发时序和后续状态检查为准，不能把它描述成所有竞态都已无条件解决。

### 6.3 folded retain 和 parent

同一 `serialization_key` 的 retain peers 可以在 claim transaction 内被 fold：主行和 peers 一起标记 processing，合并 contents，产生 `fold_members`。terminal/retry/defer 要对 `all_operation_ids` 扇出，否则 peer 会永远 stuck。batch parent 的 child linkage 在 JSON `result_metadata` 中，parent 聚合会锁 parent 行并检查所有 siblings。

源码专门处理多个 crash window：

- child 已 terminal 但 parent promotion 失败；
- parent 已建但 children 尚未持久化；
- worker/API 在 batch child 提交中断。

启动恢复会把没有 child 的 payload-less parent 标成 failed，而不是伪造 completed。这证明源码承认 parent 提交并非一个不可分割的跨行事实。

## 7. worker、claim 与“租约”边界

### 7.1 `FOR UPDATE SKIP LOCKED`

PostgreSQL `claim_tasks()` 按 reserved pool 和 shared pool 分阶段查询：

```sql
SELECT ...
FROM async_operations o
WHERE o.status = 'pending'
  AND o.task_payload IS NOT NULL
  AND (o.next_retry_at IS NULL OR o.next_retry_at <= NOW())
  ...serialization predicates...
ORDER BY o.created_at
LIMIT $n
FOR UPDATE SKIP LOCKED
```

随后在同一 transaction 内把候选更新为 processing，并返回 payload/retry_count。多个 worker 不会等待同一行；被锁行由本轮跳过，下一轮再尝试。poller 在 schema 间 round-robin，先做每 schema 的公平 pass，再从有工作的 schema 回填容量。

claim transaction 是每个 schema 一次 transaction；整个 poll cycle 复用一个 connection，但不会把所有 schema claim 锁在同一个长事务中。`worker_claim_connection_reuse` 测试源码专门覆盖该连接复用形状。

### 7.2 它不是完整 lease

当前源码有 `claimed_at` 和 `worker_id`，但本轮未发现：

- worker 运行期间定时更新 `claimed_at` 的 heartbeat；
- 任意 worker 按 `claimed_at` 过期时间自动接管另一个活 worker 的 processing 行；
- 一个独立的、全局、连续运行的 lease reaper。

因此更准确的名称是“带 owner/time 标记的数据库 claim”。恢复路径是：

1. worker 启动 `recover_own_tasks()`，按本 worker_id 重置 processing rows；
2. shutdown drain 超时后取消本地 asyncio tasks，再 `release_own_tasks()` 重置本 worker_id rows；
3. retry/reclaim 达到 `max_retries` 后标 failed，避免 kill-loop 无限重领；
4. batch parent 通过 startup reconcile 处理 payload-less orphan；
5. admin CLI 可以按 worker 或全局释放 processing rows。

如果 worker 使用不稳定的 hostname-derived id、进程被 SIGKILL 且新实例 id 不同，旧 processing 行不会因为 `claimed_at` 自动在当前 claim 查询中变回 pending；必须依靠明确的管理/恢复路径。源码存在对此风险的注释和测试线索，但本轮没有实际 kill/restart 验证。

### 7.3 slots 和资源释放

`max_slots` 结合 per-operation reserved floor 与 shared pool 控制本 worker 的 in-flight 数。`execute_task()` 创建 fire-and-forget asyncio task，active map 和 slot 计数通过 done callback 清理。wall timeout 当前明确覆盖 retain、batch retain、file retain 变体；不是所有 operation type 的统一外层 wall timeout。consolidation、reflect 等有各自 engine/provider 层限制或没有同一 poller ceiling，不能画成全局一致。

## 8. 取消、超时、断开与崩溃

### 8.1 HTTP 客户端断开

`ClientDisconnectCancellationMiddleware` 被最后加入，位于 `BaseHTTPMiddleware` 外侧，读取原始 ASGI receive channel，在 `http.disconnect` 时触发 `CancellationToken`。`run_cancellable_on_disconnect()` 将 token 塞入 `RequestContext`，`OperationCancelledError` 映射为 HTTP 499。

这条包装明确用于 recall/reflect。token 是 cooperative：recall 在 stage boundary 检查；graph expansion 和 cross-encoder reranking 若已经通过 `run_in_executor` 进入线程，取消 await 不会强杀该线程，只能阻止下一昂贵阶段。`Request.is_disconnected()` 被明确放弃，因为在 BaseHTTPMiddleware 后可能不触发。

本轮没有把 retain HTTP handler、后台 worker task 或 MCP 断开都写成同样语义。后台 operation 已经入队后，API 客户端断开不等于 operation cancelled；调用者需要显式 operation cancel/retry API。

### 8.2 主动取消

`MemoryEngine.cancel_operation()`：

1. 认证 tenant/bank；
2. 查询 operation 是否属于 bank；
3. 只有 `status == 'pending'` 才允许；
4. 更新为 `cancelled`。

`processing`、`completed`、`failed` 不能通过该入口取消。worker 已领取且正在执行的 operation 不会因这个 API 调用自动被终止。engine 内部另有 `_check_op_alive()`/cancellation checkpoint 的局部逻辑，但不能将其等同为数据库 operation 状态的统一 cancelled transition。

### 8.3 超时和失败

- provider/DB 各有配置的 command/acquire/statement/model/operation timeout，但配置存在不代表所有调用路径都使用相同 ceiling。
- retain worker outer timeout 触发 `asyncio.timeout()`，取消 executor，写 failed，并保留 stage breadcrumb。
- `RetryTaskAt` 是可重试异常；`DeferOperation` 是有意 backpressure，不增加 retry count。
- unhandled exception 通常标 failed；如果失败写入本身因 DB/pool/statement timeout 失败，poller 尝试 reclaim 自己的 processing rows，否则 row 可能暂时保持 processing。
- `CancelledError` 继承 `BaseException`，在 shutdown timeout 的 task cancel 路径不会被普通 `except Exception` 捕获；poller 等待短暂 cancel drain 后再 release 自己的 rows。

### 8.4 worker/API 崩溃

可确认的 recovery 是“基于 DB 行和 worker_id 的启动/退出扫描”，不是对已提交 memory 的通用二阶段判定。若 retain 在 DB commit 前崩溃，事务回滚，operation 可重领；若 memory commit 已完成但 operation terminal 更新前崩溃，重试是否重复事实取决于 retain 的 operation/document/idempotency/replace/append 语义，源码有大量针对性保护，但本轮没有 L4 注入验证。

API 进程崩溃在 `_submit_async_operation()` INSERT transaction 之前不会留下 operation；事务提交后 payload 一起存在，worker 可领取。文件 retain 还涉及上传 bytes、转换产物、operation metadata 和数据库 document，不能用 operation 行删除推导对象存储已清理。

## 9. 数据库迁移、配置和跨库一致性

### 9.1 migration

`migrations.py` 通过 Alembic、数据库 advisory lock/进程协调启动迁移；不同 dialect 由 `run_for_dialect()` 分发。迁移链包括：

- 初始 `async_operations` 和状态约束；
- `worker_id`、`claimed_at`、`retry_count`、`task_payload`；
- `cancelled` 状态；
- `next_retry_at`、webhook delivery；
- `serialization_key`；
- parent metadata GIN、terminal retention index；
- 多 schema maintenance routines、skip-locked schema discovery；
- bank delete cascade 和历史 orphan 清理。

初始迁移中没有 `cancelled`/worker 字段，不代表当前 schema。生产形状必须按完整 migration head 与目标 dialect 验证。本轮没有运行 Alembic，也没有比对 live database。

### 9.2 配置

关键运行配置包括 DB pool min/max、command/acquire/statement timeout、parallel gather、session setup、migration startup/concurrency、worker enabled/id/poll interval/max retries/retry backoff/max slots、operation retention/cleanup batch、各 operation 的 reserved slots、model init timeout、embedding provider/model/dimension、LLM provider/model/key/base URL 和 provider-specific timeout/retry。

默认 reserved floor 中 consolidation 为 2，retain/file/refresh/graph 等为 0；reservation 是最低保证，不是该 type 的最大上限，剩余 shared pool 仍可被其使用。配置测试源码证明了类型解析和覆盖行为，但没有本机启动验证。

### 9.3 跨库/跨系统一致性

默认 PostgreSQL 单库内：

- operation INSERT 是数据库事务；
- retain 写入事务可原子提交 facts/links/document 相关表；
- tenant schema 由 schema-qualified SQL 隔离。

跨系统时：

- LLM/embedding/reranker 是外部副作用或本地资源，不在 PostgreSQL transaction 内；
- 外部 memory store 可能拥有 memory/link，而 documents/chunks/entities 仍在 PostgreSQL；
- file/object storage bytes 不与 operation 行共享 ACID；
- webhook delivery 作为另一个 `async_operations` task，发送成功与业务事务不是同一个提交；
- audit/LLM trace/metrics 也可能是 best-effort 或独立写入。

因此“retain 成功”必须明确是模型处理成功、PostgreSQL memory transaction committed、外部 store committed、文件已持久化还是 operation 已 terminal；这些不是一个天然的跨库原子状态。

## 10. 测试证据与未验证项

### 10.1 测试源码能支持的局部结论（S1）

- `test_worker.py`、`test_worker_wall_timeout.py`：worker backend、claim、完成/失败/retry/defer、wall timeout 的局部行为。
- `test_recall_cancellation.py`：token、ASGI disconnect wiring、499 映射和 cooperative checkpoint。
- `test_retain_pipeline_cancellation.py`、`test_recall_error_propagation.py`：pipeline 局部取消/错误传播。
- `test_worker_claim_connection_reuse.py`：claim cycle 连接复用形状。
- `test_schema_isolation.py`、`test_migrations_parallel_schemas.py`：schema/context/migration 并发隔离意图。
- `test_retain_same_document_concurrency.py`、`test_graph_maintenance_queue_race.py`、`test_graph_maintenance_claim_serialization.py`：同 document、graph queue race/serialization 的回归场景。
- `test_async_retain_operation_id.py`、`test_operation_status.py`、`test_operation_completion.py`、`test_operation_progress.py`：operation idempotency、状态读取、父子/进度局部行为。
- BM25、embedding、graph、reflect、retain 测试：各自算法和管线局部契约。

测试文件存在不等于测试通过；本轮没有运行它们。

### 10.2 本轮明确没有证明的内容

- PostgreSQL/pgvector/text extension 真实安装、迁移 head 和索引可用性；
- 真实 LLM、embedding provider、reranker、Oracle、S3/GCS/Azure；
- REST/MCP/SDK 与独立 worker 的跨进程真实链路；
- SIGKILL worker/API 后 operation、memory、document、link 的恢复和幂等；
- DB 断连、pool exhausted、statement timeout 时的资源归还；
- client disconnect 与已运行线程的实际 CPU/线程排空；
- `processing` 行的全局过期 lease reaping；
- 外部 memory store 的 witness/事务一致性；
- 文件转换产物、reflect cache、webhook delivery 的真实回收；
- full test suite、coverage、性能和压力。

## 11. 真实调用链与状态机的最小验收模型

### 11.1 retain/operation 联合模型

```text
HTTP request
  -> [auth/precheck]
  -> sync retain:
       [LLM/embed/read phase]
       -> [DB write transaction]
       -> commit => memory visible
       -> response

  -> async retain:
       [operation INSERT + payload transaction]
       -> pending
       -> worker claim transaction => processing(owner/time)
       -> [LLM/embed/read phase outside final write transaction]
       -> [DB memory write transaction]
       -> terminal operation write
```

中间任何 crash 都要分别检查两个事实：记忆事务是否 committed、operation row 当前是什么状态。不能用其中一个推断另一个。

### 11.2 可靠性判断

| 问题 | 当前源码可说 | 当前源码不能说 |
|---|---|---|
| 多 worker 不重复 claim | 有 `FOR UPDATE SKIP LOCKED` 的 claim transaction | 所有内部维护队列都无锁等待；graph queue 有特殊 `FOR UPDATE` 语义 |
| 任务有 owner/time | processing 写 `worker_id/claimed_at` | 有运行 heartbeat 或全局过期租约 |
| worker crash 可恢复 | startup/release/admin recovery 路径存在 | 任意新 worker 自动接管所有 stale processing |
| pending 可取消 | `cancel_operation` 只接受 pending | processing 可由 cancel API 立即终止 |
| recall/reflect 可响应断开 | cooperative token + 499 | 已运行 thread 被强制停止 |
| retain DB 写原子 | 单一 DB transaction 可包住写阶段 | LLM/外部 store/object store 与 DB 跨库 ACID |
| parent orphan 可见 | startup reconcile 可标 failed | batch parent/children 提交天然不可分割 |
| retry 有边界 | retry_count/max recovery attempts/backoff | 每类 provider/operation 都共享同一重试语义 |

## 12. 研究收口

Hindsight 的真实核心不是“向量库加一个 agent”，而是：

1. `retain` 将 LLM 抽取、时间、embedding、实体和图关系投影到 memory store；
2. `recall` 将 semantic、BM25、graph、temporal 四臂候选融合，再做 rerank/MMR/budget；
3. `reflect` 通过工具循环读取 mental models、observations、raw facts 和证据，不默认持久化答案；
4. `async_operations` 用 PostgreSQL 行作为跨进程 broker，worker 用 SKIP LOCKED claim 并通过有限 recovery 处理部分失败；
5. 事务一致性主要是单一数据库内的局部一致性，跨 store/provider/object storage 需要额外协议；
6. 取消是分层且不对称的：HTTP recall/reflect 有 cooperative disconnect，operation cancel 只取消 pending，worker processing 的终止主要依赖 timeout/shutdown/recovery；
7. `claimed_at`/`worker_id` 是恢复线索，不应在架构文档中升级成未实现的 lease heartbeat/reaper。

本文件只记录源码事实、测试源码证据和明确的未知项。未运行的测试、未连接的数据库、未注入的故障和未读取的外部归档均不被写成“已验证”。

## 13. 本轮源码深审补充

本节是对前文草稿的第二遍核对，优先记录会改变可靠性判断的细节，而不是重复产品说明。

### 13.1 CodeGraph 状态

按用户要求先执行了目标仓库内的 CodeGraph 探索命令，但仓库没有 `.codegraph/` 索引，命令返回“CodeGraph isn't available here — no .codegraph/ index exists”。因此本文没有伪造 CodeGraph 调用关系；下面的关系图和结论来自源码直接阅读、全文符号检索及测试源码，证据等级仍为 S0/S1，而不是 CodeGraph 证据。

### 13.2 API/engine/broker 的关键边界

`MemoryEngine.execute_task()` 是 worker 的统一路由入口。它先从 payload 取出 `_schema` 并设置 tenant context，再查询 `async_operations`；如果行不存在或状态为 `cancelled`，任务直接跳过。查询失败时源码记录错误但继续执行，这意味着“无法确认取消”采用 fail-open，而不是 fail-closed。之后按 `task_dict["type"]` 分发到 `batch_retain`、`file_convert_retain`、文档导入导出、`consolidation`、`graph_maintenance`、`refresh_mental_model` 和 `webhook_delivery`。未知类型会删除 operation 行并返回，因而不是进入 `failed` 的可观测终态。

异步提交主路径确实把完整 payload 与 operation INSERT 放进同一 transaction；但 `BrokerTaskBackend.submit_task()` 仍支持“仅为 NULL payload 的旧 caller 补写”以及“没有 operation_id 时另建 operation”两种旁路。`WorkerTaskBackend.submit_task()` 则明确 no-op，worker 内部产生的子任务依赖已有 `async_operations` 行在下一轮被领取，而不是递归 inline 执行。`SyncTaskBackend` 会立即 inline 执行，测试/embedded 因此不等价于独立 API + worker 进程。

worker poller 的 terminal 处理有一个重要不对称：`_mark_completed()` 使用 `WHERE status='processing'`；`_mark_failed()`、`_schedule_retry()`、`_defer_operation()` 的 SQL 没有同样的 processing 条件。正常情况下这些写入来自拥有该 task 的 asyncio task，且未见第二个执行者同时改写同一行；但文档不能把所有 terminal 写都概括成统一 CAS。异常时 terminal 写失败会尝试按当前 worker/operation reclaim；如果 reclaim 也失败，行可能继续保持 `processing`，而活着的 worker 已经从 active map 移除，只有后续显式恢复路径能处理。

### 13.3 取消、状态读取和进度不是同一机制

HTTP disconnect middleware 只监控路径后缀 `/memories/recall` 和 `/reflect`，通过 pump task 转发 ASGI receive，同时把 token 写入 scope。上传、MCP stream 和 retain 请求不经过这层取消。`recall_async()` 与 `reflect_async()` 在入口和阶段/迭代边界检查 cooperative token；进入线程执行的 graph/rerank 不能被强制终止。

operation cancel API 先 SELECT 再无条件 UPDATE `operation_id`，没有在 UPDATE 中重复 `status='pending'` 条件；这仍是竞态窗口，不能称为完整 CAS。worker 执行前的 cancelled 检查失败时会继续执行；长任务的 `_check_op_alive()` 在数据库错误时返回 True，也采用 fail-open。已进入 `processing` 的任务不由 cancel API 终止。

`result_metadata.progress` 只是粗粒度阶段/批次快照，写入失败被吞掉，不是 lease heartbeat；`updated_at` 也不能据此推导 worker 存活。operation retention 只清理 terminal rows，不能把 retention 写成处理中任务的回收机制。

### 13.4 retain/recall/reflect 的实际语义修正

retain 的批处理 API 先认证 tenant、验证 operation、确认 bank，再复制输入；orchestrator 可能清空内部 copy 的逐项 content 以降低内存压力，调用者输入不会被该内部优化直接修改。事实抽取、embedding、实体解析和检索预读与最终写事务分离；最终 DB 阶段才提交 document/chunk/fact/entity/link 等投影。post-insert maintenance、consolidation、graph maintenance 和 webhook 等后续动作通过异步 operation 产生，不能把 retain 返回等同于所有后处理完成。

recall 的实现是“每个 fact type × 四个检索臂”并行，再做 RRF、rerank、MMR 和 token 过滤；chunks 的拉取预算独立于 facts 的 `max_tokens`。`created_after/created_before` 在源码注释中明确约束 `updated_at` 变更窗口，而不是 `created_at`；前文关于时间字段不可合并的结论保持有效。

reflect 首先读取 bank profile、配置、freshness 和 directives，然后按配置决定是否暴露 mental-model、observation、raw recall、expand 工具。agent 从空上下文开始，最后一轮移除工具以迫使最终回答；普通 reflect 只读，不持久化答案。刷新 mental model/consolidation 是另行入队的写路径，不能用 reflect 的只读语义覆盖它们。README 的“Reflect ... generate new observations and insights”是产品层描述，若按字面理解为每次 reflect 都写 observation，会与当前 `reflect_async()` 的只读源码冲突。

### 13.5 数据库、租户和外部存储

`async_operations`、banks、documents/chunks、memory_units、entities、links、mental models、directives、webhook 和审计/LLM trace 相关表共同形成当前 schema；不能只读 `models.py` 或初始 migration 来判断最终字段。默认 PostgreSQL 路径提供单库 transaction 和 schema-qualified tenant 隔离；Oracle 通过另一套 SQL/锁语义适配，不能仅凭 PostgreSQL 的 `SKIP LOCKED` 结论覆盖 Oracle。

文件 retain 还连接文件转换和可选 S3/GCS/Azure/PostgreSQL storage。数据库 operation/document 与对象存储 bytes 没有共享 ACID；operation 删除或 terminal 也不自动证明转换临时产物、对象 key、webhook side effect 已回收。外部 memory store 的 transaction/witness seam 若未由具体扩展实现并验证，不能升级为跨库一致性保证。

### 13.6 测试与文档冲突审计

测试源码覆盖了 worker claim/retry/defer/wall timeout、disconnect wiring、schema/migration 并发、同 document retain、graph queue race、operation progress/status/completion，以及局部 retain/recall/reflect/embedding/BM25 行为；同时存在需要真实 PostgreSQL、pgvector/text extension、SeaweedFS、Oracle、LLM 或外部 provider 的场景。测试文件存在只能证明设计意图和局部断言，不能证明当前环境已通过。

README 适合解释三种产品操作和 Docker/SDK 快速开始，但它把“state-of-the-art”“生产使用”“full feature parity”等外部或版本性声明与源码架构事实混在一起，也把“Reflect ... generate new observations”写得比当前普通 reflect 代码更宽。根 ARCHITECTURE.md 采用源码事实优先：把 Reflect 区分为只读综合，把 observation 写入归到 consolidation/refresh，并把未执行的依赖、故障注入和真实跨进程链路列为未知。当前根目录未发现第二份独立 `ARCHITECTURE*.md`；不存在可合并的旧“细探”文档。

## 14. 最小生产审计清单

部署前至少应逐项确认：

1. migration head、目标 dialect、pgvector/text/vchord 等扩展和索引真实可用；
2. API 与独立 worker 使用同一 tenant/schema 解析、operation payload 和 worker id 策略；
3. kill -9、DB 断连、pool exhausted、statement timeout 后分别检查 operation 行、memory transaction、document/chunk、对象存储和 parent aggregator；
4. 明确 processing 行的接管机制；当前源码不能用 `claimed_at` 代替 heartbeat/reaper；
5. 验证 cancel 与 worker claim 的并发返回、取消后的入口检查和 fail-open DB 错误策略；
6. 验证 retain 后 maintenance/consolidation/refresh/webhook 的最终一致性、重试幂等和资源清理；
7. 将 README 的产品宣传、测试源码预期和真实运行证据分栏记录，不把任一栏替代另外两栏。

## 15. 第二遍数据库与资源审计

### 15.1 数据库抽象不是相同事务语义

`DatabaseBackend` 把 pool、acquire、transaction、fetch/execute 和 `ops` 策略暴露给 engine；`DataAccessOps` 把 PostgreSQL 的 `unnest`、LATERAL、数组和 Oracle 的 `executemany`、逐行/替代 SQL 隔离开。它统一的是调用接口，不是锁、约束、索引和返回值的物理语义。

PostgreSQL 的同文档写入使用单条 `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` 获取行锁；Oracle 不能用相同语句返回，因此拆成幂等 insert 加 `SELECT FOR UPDATE`。PostgreSQL memory link 写入还在同一语句内对引用的 memory unit 取 `FOR KEY SHARE`，以覆盖 deferred FK 与并发删除之间的窗口。上述是具体方言实现的局部并发保护，不应抽象为所有数据库的一致锁协议。

worker 的通用 claim 由 backend ops 生成，PostgreSQL 查询使用 `FOR UPDATE SKIP LOCKED`；graph maintenance 的内部队列则明确使用不带 `SKIP LOCKED` 的 `FOR UPDATE`，所以同一 bank 的 graph job 必须先在 operation claim 层串行化。文档中“worker claim 使用 SKIP LOCKED”必须限定为通用 operation claim，不能覆盖内部维护队列。

### 15.2 迁移和 retention 的事实

worker 字段、payload、cancelled constraint、serialization key、webhook/retry、maintenance routine 和 terminal cleanup index 分散在连续 Alembic revisions。terminal cleanup index 的谓词只包含 `completed/failed/cancelled`；它服务于 retention sweep 和 operation listing，不负责处理 `processing`。迁移同时有 PostgreSQL `CREATE INDEX CONCURRENTLY`、Oracle 独立 DDL 和 per-schema 运行路径，真实发布必须验证目标 dialect 的 migration head，而不是只看 Python 模型。

`operation_retention_days=0` 表示保留 terminal rows/payloads，正数才按更新时间清理；API 文档的“保留窗口后可查询”因此是配置条件，不是永恒保证。batch parent 没有 payload，children 通过 JSON `result_metadata.parent_operation_id` 关联，缺少外键级别的跨行约束；恢复和 retry 代码必须扫描/聚合这些 JSON 关系。

### 15.3 资源释放的真实等级

pool connection 主要通过 async context manager 释放；worker active task、slot 和 per-type counter 通过 done callback 清理。优雅 shutdown 先停 HTTP、等待 poller drain，再取消 poller task、释放当前 worker 所有 processing rows，最后关闭 engine；第二个信号可立即 `sys.exit(1)`，Windows Proactor 没有 asyncio signal handler 时也失去两阶段优雅路径。SIGKILL、强制退出、进程 OOM 不会执行这些 finally/atexit 路径。

retain 的 provider、embedding、cross-encoder 和本地模型资源有初始化/调用级配置，但本轮没有真实下载失败、GPU/MPS、外部 HTTP 或 pool exhausted 验证。reflect 的增量 prompt cache 清理是 detached best-effort task，短 TTL 作为后备；清理异常不会让 reflect 失败。由此可见“资源有释放代码”与“崩溃后所有资源立即释放”是两种不同结论。

PostgreSQL BYTEA file storage 与数据库在同一后端但 `FileStorage.store/delete` 自己获取连接，是否与 document/operation 写入处于同一 transaction 取决于调用者传入的路径；S3/GCS/Azure 更不可能与 operation row 共享 ACID。文件 retain 的失败回收需要单独验证 storage key、转换产物、`file_storage` 行和 operation 状态，不能从 `async_operations` terminal 状态推导。

## 16. 文档冲突判定

当前根文档是本次审计唯一新增/修改的文件，目标仓库未发现另一份根级或子目录级 `ARCHITECTURE*.md` 可互相覆盖。README 的产品流程图与本文的工程审计不是同一文档类型：README 描述用户可见的 retain/recall/reflect 三操作，本文描述源码实际边界、异步状态和未验证项。两者存在以下需要显式保留的语义差异：

- README 将 reflect 概括为“generate new observations and insights”；普通 `reflect_async()` 当前是只读 agent loop，写 observation 的路径是 consolidation/refresh；
- README 说 Oracle “full feature parity”；源码有独立 dialect/ops/迁移/锁实现，完整 parity 必须以 Oracle 集成测试和 live migration 证据证明；
- README 的 Docker/embedded/SDK 示例隐藏了 `SyncTaskBackend`、embedded pg0、外部 PostgreSQL 和独立 worker 的执行拓扑差异；不能用 quick start 推导生产 broker/worker 故障语义；
- README 的 benchmark/production 使用声明属于外部项目声明，不能作为当前 checkout 的运行验证。

因此没有修改 README：用户要求只改根文档，且架构审计应在根 `ARCHITECTURE.md` 中记录冲突，而不是把宣传文案改写成源码文档。
