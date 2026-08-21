# Prefect 架构建档

> **项目根目录**：`/Users/hekunhua/Documents/Agent/github 源码参考/12_工作流编排/prefect`
> **项目名称**：Prefect —— Python 工作流编排与观测平台
> **许可证**：Apache-2.0
> **建档范围**：深读当前源码、测试、README、`pyproject.toml` 与已有 `细探-prefect.md`；当前核对只修改本文件，未调用 MCP/Hermes，未启动服务、安装依赖、构建或运行 Prefect 测试。

## 1. 结论摘要

Prefect 的核心是“**Python SDK 执行引擎 + 中央编排 API/数据库 + 部署执行代理 + 事件/自动化横切层**”。用户用 `@flow`/`@task` 描述工作流；Flow/Task 引擎负责本地参数、依赖、重试、超时、缓存和结果处理；Flow 状态迁移通过服务端编排规则裁决，Task 主要在客户端引擎内推进并发出任务事件。服务端以 FastAPI、Pydantic、SQLAlchemy/Alembic 和 SQLite/PostgreSQL 为基础，调度器产生计划运行，Worker 或新 Runner 将计划运行提交到进程、Docker、Kubernetes 等基础设施。旧 Vue UI 与迁移中的 React UI v2 均由服务端提供静态入口。

当前工作区基线（只读命令所得）：提交 `2cc0f474c027cd8e19ecf6b34386908dcb301213`（2026-08-19）；Python 文件约 1,890 个，TypeScript/TSX 文件约 1,627 个。已有未跟踪研究文档 `细探-prefect.md` 保留不动；其中已证实的架构事实已收口到本文件，本文件是唯一根架构建档。

## 2. 文本流程图

```text
┌────────────────────────────────────────────────────────────────────────────┐
│ 用户代码 / SDK                                                            │
│ @flow、@task、Flow.from_source、Flow.serve/deploy、run_deployment          │
└──────────────┬─────────────────────────────────────────────────────────────┘
               │ 装饰器对象 + 参数/依赖/策略
               ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ 本地执行引擎                                                              │
│ FlowRunEngine(Sync/Async) ───────┐                                         │
│ TaskRunEngine(Sync/Async) ────────┼─ TaskRunner → Future/子流程/上下文       │
│ 参数校验 → 依赖等待 → Running → 用户函数 → 成功/失败/超时/取消/崩溃          │
│ 重试、退避、并发租约、事务缓存、结果存储、心跳、hooks                        │
└──────────────┬───────────────────┴─────────────────────────────────────────┘
               │ Flow 状态提议 / Task 事件 / 日志 / API 请求
               ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ Prefect Client 边界                                                       │
│ SyncPrefectClient / PrefectClient；领域化 orchestration clients；HTTP/WebSocket│
│ client schemas 与 server schemas 分离；同步/异步方法成对提供                 │
└──────────────┬─────────────────────────────────────────────────────────────┘
               │ REST + WebSocket
               ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ Prefect Server（FastAPI）                                                  │
│ schemas(Pydantic) → models(SQLAlchemy) → api(routes)                       │
│ orchestration context/rules/policies：ACCEPT / REJECT / WAIT                 │
│ Scheduler、LateRuns、PauseExpirations、CancellationCleanup、Foreman、       │
│ Repossessor、事件持久化/触发器/动作、并发租约/Worker channel                  │
└──────────────┬─────────────────────────────────────────────────────────────┘
               │ SQLAlchemy async ORM + Alembic
               ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ 数据事实源                                                                 │
│ SQLite / PostgreSQL：flows、flow_runs、task_runs、states、deployments、       │
│ work pools/queues、blocks、logs、events、automations、concurrency、配置等     │
└──────────────┬─────────────────────────────────────────────────────────────┘
               │ scheduled flow runs / events / cancellation
               ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ 部署执行层                                                                 │
│ Deployment + Schedule → Scheduler → WorkPool/WorkQueue                       │
│   ├─ Worker：轮询/心跳/本地 CapacityLimiter → Process/Docker/K8s/云基础设施    │
│   └─ Runner：ScheduledRunPoller → LimitManager → ProcessManager → Executor    │
│                    → StateProposer / CancellationManager / Hooks / Events    │
└────────────────────────────────────────────────────────────────────────────┘

横切：运行状态、日志、事件 → EventsWorker/EventsClient → Server 或 Cloud
        Event/Metric/Composite/Sequence/Compound Trigger → Actions
        UI(v1 Vue / v2 React) ← FastAPI API + WebSocket/轮询
```

## 3. 分层与职责

| 层 | 主要目录/文件 | 责任与边界 |
|---|---|---|
| 用户 SDK 表面 | `src/prefect/main.py`、`flows.py`、`tasks.py`、`states.py` | 装饰器、Flow/Task 定义、状态与用户可调用 API；`prefect.__init__` 用懒加载暴露公共符号。 |
| 运行时引擎 | `flow_engine.py`、`task_engine.py`、`task_runners.py`、`futures.py`、`context.py` | 运行生命周期、依赖、重试、超时、取消、结果和上下文；同步/异步实现需保持行为锁步。 |
| 并发/事务/结果 | `concurrency/`、`transactions.py`、`results.py`、`cache_policies.py`、`blocks/` | 租约与槽位、结果缓存幂等事务、序列化与块存储；阻塞线程中的超时不能可靠中断 I/O。 |
| 客户端协议 | `client/`、`client/orchestration/`、`client/schemas/`、`events/`、`logging/` | HTTP/WebSocket 传输、按领域拆分的同步/异步客户端、客户端事件/日志订阅；不得依赖 server-only 模块。 |
| 服务端 API | `server/api/`、`server/schemas/` | FastAPI 路由、请求/响应 Pydantic 契约、认证与中间件；新增端点遵循 schema → model → route。 |
| 服务端模型/数据库 | `server/models/`、`server/database/`、`server/database/_migrations/` | SQLAlchemy ORM、数据库会话、Alembic 迁移；SQLite 与 PostgreSQL 必须保持语义/迁移同步。 |
| 服务端编排 | `server/orchestration/` | `OrchestrationContext` 携带初始/提议/已验证状态，规则链决定 ACCEPT、REJECT 或 WAIT；Flow/Task 有不同策略。 |
| 服务端后台治理 | `server/services/`、`server/events/services/`、`server/concurrency/` | 调度、迟到、暂停过期、取消清理、孤儿回收、事件流、自动化动作和租约管理。 |
| 部署配置 | `deployments/`、`prefect.yaml`、`schemas/` | 初始化项目、build/push/pull steps、模板化步骤输出、部署创建和远程运行触发；不直接负责 Flow 执行。 |
| WorkPool 执行 | `workers/`、`infrastructure/`、`worker_communication/` | 长驻 Worker 从 WorkPool 拉取运行，心跳、归属、限流、基础设施提交和取消；Worker 不管理无 WorkPool 的 Runner 模型。 |
| 新 Runner 执行 | `runner/` | `Runner` 是兼容门面；实际职责拆到 FlowRunExecutor、ProcessManager、StateProposer、CancellationManager、LimitManager、ScheduledRunPoller 等。 |
| UI | `ui/`、`ui-v2/`、`server/api/ui/` | 旧 Vue 与迁移中的 React/TypeScript UI；都通过服务端 API 获取数据，v2 使用 TanStack Router/Query、Vitest、MSW、Pixi.js。 |
| 测试与运维工具 | `tests/`、`integration-tests/`、`compat-tests/`、`benches/`、`load_testing/`、`scripts/` | 单元/服务端/客户端/CLI/集成/兼容/性能和 UI 测试；测试目录镜像 `src/prefect/`。 |

## 4. 关键数据流

### 4.1 Flow 本地调用与状态

1. `@flow` 将函数包装为 `Flow`，记录名称、版本、参数校验、重试、超时、结果存储和 hooks；默认 TaskRunner 为线程池（见 `src/prefect/flows.py:145-229`）。
2. `FlowRunEngine` 解析参数与子流程依赖，必要时把未就绪依赖标为 `Pending/NotReady`；之后通过客户端提出 `Running`，服务端可接受、拒绝或延迟，客户端继续轮询。
3. 用户函数完成后转换为 `Completed`；异常、`BaseException`、超时、取消分别转为 `Failed`、`Crashed`、`Failed(name="TimedOut")`、`Cancelling/Cancelled`，并执行相应 hooks。
4. Flow 运行的状态迁移以服务端为权威；服务端 `OrchestrationContext` 包含 initial/proposed/validated state，`CoreFlowPolicy` 依优先级执行重复迁移、终态、并发槽位、暂停、调度时间、重试和资源释放规则（`server/orchestration/rules.py:71-124`、`core_policy.py:111-151`）。

状态并不是只有九个粗粒度枚举：`src/prefect/client/schemas/objects.py` 定义
`SCHEDULED/PENDING/RUNNING/COMPLETED/FAILED/CANCELLED/CRASHED/PAUSED/CANCELLING`，
而 `src/prefect/states.py` 提供 `AwaitingRetry`、`AwaitingConcurrencySlot`、`Retrying`、
`Late`、`NotReady` 等带业务语义的状态名；`StateDetails` 承载
`scheduled_time`、`pause_timeout`、`cache_key`、`run_input_keyset`、租约 ID 等迁移上下文。
`StateGroup` 对一组状态提供失败、暂停、终态和全完成聚合，适用于批量任务收口，不应被简化为单一布尔值。

引擎还会按配置周期发送 `prefect.flow-run.heartbeat` 事件；跨进程运行通过
`run_flow_in_subprocess()`/`python -m prefect.flow_engine` 入口并注入
`PREFECT__FLOW_RUN_ID`，因此 Worker/Runner 的子进程边界不是普通函数调用边界（证据：
`src/prefect/flow_engine.py`、`src/prefect/workers/`、`src/prefect/AGENTS.md` 中的 SDK 约定）。

### 4.2 Task 依赖、并发与结果

1. `TaskRunner.submit/map` 把任务提交到任务引擎并返回 `PrefectFuture`；`map` 先收集 Future 输入、解析可迭代参数，再逐项提交（`task_runners.py:63-227`）。
2. Task 引擎创建本地/服务端 TaskRun，等待上游输入；执行外圈可取得 tag 并发租约，随后进入 timeout、取消检查与 transaction context。
3. transaction 以 cache key 读已提交结果；命中时跳过用户函数，未命中才调用函数，结束时提交或回滚结果记录。结果可由 ResultStore/块存储持久化。
4. Task 状态更多在客户端引擎内推进，同时发出 `prefect.task_run.*` 事件；服务端仍通过 Task policy 处理服务器侧记录、缓存、并发和终态规则。不要把 Flow 的“服务端提议”模型直接套到 Task。

任务重试的边界是客户端与服务端协作：`task_engine.py` 根据 `retries`、
`retry_condition_fn`、`retry_delay_seconds`（数值、列表或 callable）和 jitter 生成
`Retrying/AwaitingRetry`，`scheduled_time` 到期后再进入运行；服务端 `RetryFailedTasks`
等规则仍可拒绝不合法迁移。等待 Pending/Paused 使用
`clamped_poisson_interval` 退避，避免大量客户端固定时间惊群。线程执行中的超时不能
中断阻塞 I/O，异步任务必须在可取消的 await 边界才能可靠响应超时（证据：
`src/prefect/task_engine.py`、`src/prefect/utilities/math.py`、`server/orchestration/core_policy.py`）。

当前任务执行器以 `ThreadPoolTaskRunner`、`ProcessPoolTaskRunner` 和
`PrefectTaskRunner` 为源码实现，`ConcurrentTaskRunner` 是指向线程池的兼容别名
（`src/prefect/task_runners.py:242`、`:749`、`:1337`、`:551-552`）；
旧细探中“SequentialTaskRunner 为 v3 默认、另有内置 DaskTaskRunner”的表述不作为当前
架构事实，Dask 是外部集成示例，默认值以 `flows.py` 当前实现为准。

任务标签并发采用服务端租约：引擎执行外圈的 `lease_duration=60`，续约线程立即续约，
之后每 `lease_duration × 0.75` 执行一次，单次续约最多重试 3 次并指数退避；默认续约失败
只告警，显式 `raise_on_lease_renewal_failure=True` 才取消执行以防超分配，退出时停止并
最多 join 2 秒（证据：`src/prefect/task_engine.py:953`、`:1584`、
`src/prefect/concurrency/_leases.py`）。

### 4.3 调度、部署与执行

1. `Deployment` 保存 entrypoint、storage/pull steps、schedule、parameters、work pool/queue、job variables、并发限制等元数据。
2. `SchedulerService` 周期扫描部署，计算未来运行并写入数据库；LateRuns、PauseExpirations、CancellationCleanup 等服务补偿异常或悬挂状态。
3. WorkPool/WorkQueue 路径由 Worker 心跳并拉取计划运行，再用本地 `anyio.CapacityLimiter` 控制提交，转换 job template/steps 后启动 Process、Docker、Kubernetes 或其他基础设施。
4. Runner 路径没有 WorkPool：`ScheduledRunPoller` 发现运行，`LimitManager` 限流，`FlowRunExecutor` 管理单次生命周期，`ProcessManager` 管理 PID/终止，`StateProposer` 提议状态，`CancellationManager` 协调控制通道、kill、hooks、状态和事件。

调度器的扫描是可恢复且幂等的：`src/prefect/server/services/scheduler.py` 按部署 ID
游标分页，按每个 active schedule 的“未来运行数量/最远计划时间”判断是否需要补排，
再按 `insert_batch_size` 分批写入；新建或刚更新部署另有快速扫描循环。Worker 的
`sync_with_backend()` 把心跳、WorkPool 同步交给 `WorkPoolWorkerChannel`，计划运行查询
仍走 REST；提交使用本地 `CapacityLimiter`，取消观察由 WebSocket 加轮询兜底，并且只对
尚未启动基础设施的运行执行直接取消（证据：`src/prefect/server/services/scheduler.py`、
`src/prefect/workers/base.py`、`src/prefect/workers/AGENTS.md`）。

### 4.4 事件与自动化

客户端事件由 `emit_event`/`PrefectEventsClient` 发送，经 EventsWorker 队列和 WebSocket/HTTP 到 Server 或 Cloud；服务端持久化、匹配资源/related 关系并评估触发器。`EventTrigger` 分为 Reactive（事件出现）和 Proactive（事件缺失），支持 `after`/`expect` 通配符、`threshold`、`within`、`for_each` 和 related 资源匹配；另有 Metric（Cloud-only）、Composite、Sequence、Compound。动作可以运行/暂停/取消部署或 FlowRun、改变状态、发送 Webhook/通知等。客户端和服务端各维护独立事件 schema，不能跨层直接复用；低流量时客户端仍靠时间 checkpoint，不能只依赖事件数量阈值（证据：`src/prefect/events/`、`src/prefect/server/events/`）。

### 4.5 UI 数据流

FastAPI `create_app` 同时组装 API 与 UI 应用，并在 lifespan 中执行数据库迁移、块自动注册、Docket 和后台服务启动（`server/api/server.py:859-988`）。V1 Vue 与 V2 React bundle 并存；UI 通过 API/轮询/WebSocket 展示 Flow、Task、Deployment、WorkPool、Events、Logs 和设置。v2 的路线、查询、组件和测试位于 `ui-v2/src/{routes,api,components,graphs}` 与 `ui-v2/tests`。

## 5. 关键路径索引

| 场景 | 入口 | 主链路 | 重要边界 |
|---|---|---|---|
| Python 工作流 | `from prefect import flow, task` | `flows.py`/`tasks.py` → `flow_engine.py`/`task_engine.py` → client → server | Flow 状态必须走服务端编排；Task 引擎与 Flow 引擎不可混写。 |
| 本地服务部署 | `Flow.serve()`、`prefect serve` | `deployments/runner.py`/`runner/runner.py` → `Runner` → poller/executor | Runner 新行为放抽取类，不放兼容门面。 |
| WorkPool 部署 | `prefect worker start` | `workers/base.py` → WorkerChannel/REST → WorkPool → infrastructure | 心跳/WorkPool 同步由 WorkerChannel 持有；计划运行查询仍走 REST。 |
| YAML 部署 | `prefect deploy`、`initialize_project()` | `deployments/base.py` → `prefect.yaml` → `steps/core.py` → build/push/pull | step 输出以模板传递；动态 step import 与 `requires` 有运行时副作用。 |
| 远程部署触发 | `run_deployment()` / `arun_deployment()` | `deployments/flow_runs.py` → orchestration client → REST | 只触发已有 Deployment，不执行用户 Flow 代码。 |
| 结果缓存 | `@task(cache_policy=...)` | task engine → `transaction(s)` → ResultStore/serializer/block | `PENDING → STAGED → COMMITTED/ROLLED_BACK` 事务语义。 |
| 状态 API | `PrefectClient` 或引擎 `set_state` | client schema → FastAPI route → ORM → orchestration policy | Server/client schemas 分离；参数大小、鉴权、状态规则均在边界校验。 |
| 事件订阅 | `emit_event()`、FlowRunSubscriber | event schema → EventsClient/Worker → server stream/storage/triggers | 事件是横切观测与自动化入口，连接失败不应破坏 Runner 主执行。 |
| CLI | `prefect <group> <command>` | `cli/_app.py` + 命令组 → async/sync client 或本地服务 | `pyproject.toml` 将 `prefect` 映射到 `prefect.cli:app`；JSON 输出不能混入人类文本。 |
| Client-only 包 | `prefect-client` | `client/build_client.sh` 选择 `src/prefect` 子集 | 去除 CLI、server、testing 等；client 代码不能导入 server-only 模块。 |

## 6. API / CLI / SDK 契约面

### 6.1 REST / WebSocket API

- FastAPI 应用入口：`src/prefect/server/api/server.py:create_app`。
- 新 API 的推荐顺序：`server/schemas/` 定义请求/响应 → `server/models/` 实现 ORM → `server/api/` 注册路由。
- 典型资源包括 flows、flow-runs、task-runs、deployments、work-pools/queues、blocks、variables、artifacts、logs、events、automations、concurrency limits 和 settings。
- 状态写入端点为 `POST /flow_runs/{id}/set_state`、`POST /task_runs/{id}/set_state`（另有 FlowRun bulk set-state）；客户端的 `set_flow_run_state`/`set_task_run_state` 只提交提议，服务端规则链返回 ACCEPT/REJECT/WAIT/ABORT 及已验证状态。
- 状态迁移不是普通 CRUD：必须经过 orchestration policy；`force=True` 仍经过 `MinimalFlowPolicy` 的必要保护，不是真正绕过。
- Worker channel 是版本化 WebSocket 协议；事件和日志另有 WebSocket subscriber。协议字段新增应升级协议版本而非静默追加。

### 6.2 CLI

`pyproject.toml:133-134` 声明 `prefect = "prefect.cli:app"`。CLI 使用 cyclopts，根应用和会话选项在 `cli/_app.py`，命令组覆盖 `flow`、`task`、`server`、`worker`、`deployment`、`block`、`work_pool`、`variable`、`cloud`、`deploy`、`transfer` 等。CLI 输出使用 Rich，尽可能提供 `--json`，错误通过统一错误退出路径；整个 `cli/` 不进入 `prefect-client`。

### 6.3 Python SDK

- 公共入口：`prefect.__init__` 的懒加载表暴露 `flow`、`task`、`Flow`、`Task`、`State`、`serve`、`deploy`、`get_client` 等（`src/prefect/__init__.py:153-216`）。
- Flow/Task：装饰器得到可配置对象，配置包含 retries、retry delay/jitter、timeout、cache、result storage、hooks、tags、task runner 等。
- Client：`PrefectClient` 与 `SyncPrefectClient` 组合领域客户端；每个领域同时提供 sync/async 版本，返回客户端 Pydantic 模型。
- Deployment：`Flow.deploy()`/`prefect.deployments.deploy()` 创建 Deployment；`run_deployment()` 触发已有部署；`Flow.from_source()` 支持文件 entrypoint `path.py:flow` 与模块 entrypoint `package.module.flow`。
- Events：`emit_event`、`PrefectEventsClient`、subscriber 和 automation schema 构成事件 SDK。

## 7. 技术栈

| 分类 | 现状证据 |
|---|---|
| 语言 | Python `>=3.10,<3.15`；现代类型标注；前端 TypeScript/TSX。 |
| Python 构建 | Hatchling + versioningit；`uv.lock` 锁定依赖；`prefect` 默认版本回退值在 `pyproject.toml:229-237`。 |
| API | FastAPI、Uvicorn、Starlette、Pydantic v2。 |
| ORM/迁移 | SQLAlchemy 2 async、Alembic、aiosqlite、asyncpg；SQLite/PostgreSQL 双数据库。 |
| HTTP/异步 | httpx、httpcore、anyio、websockets、Docket；事件/日志/Worker channel 使用 WebSocket 或 HTTP。 |
| 结果/运行辅助 | cloudpickle、fsspec、jsonschema、orjson、Jinja2、cryptography、Docker SDK、Graphviz。 |
| 调度/CLI | schedule/cron/rrule 相关模型与工具；cyclopts CLI；Rich 输出。 |
| UI v1 | `ui/`：Vue 体系（现存旧界面）。 |
| UI v2 | React 19 + TypeScript、Vite、Tailwind、shadcn/Radix、TanStack Query/Router/Table、react-hook-form、zod、Recharts、Pixi.js、Vitest、Storybook、MSW；`ui-v2/package.json` 与 `ui-v2/AGENTS.md`。 |
| 扩展生态 | `src/integrations/` 为独立集成包（AWS、Azure、GCP、Docker、Kubernetes、Dask、Ray、DBT、Slack、Email 等），通过 extras/独立 pyproject 管理。 |
| 数据与观测 | ORM 数据库、结果块存储、结构化日志、事件流、OpenTelemetry/Prometheus 相关依赖。 |

## 8. 测试与验证面

测试目录镜像 `src/prefect/`，关键分层如下：

- `tests/`：SDK、引擎、状态、结果、并发、客户端、server、orchestration、CLI、部署、Worker、Runner、设置和集成单元测试。
- `integration-tests/`：需要真实运行服务或外部系统的端到端验证。
- `compat-tests/`：与 Prefect Cloud/API 兼容性验证。
- `ui-v2/tests/`、`ui-v2/e2e/`：Vitest/Testing Library/MSW 和 Playwright UI/E2E。
- `benches/`、`load_testing/`：基准与压力测试。

项目文档给出的常用命令（当前核对未执行）：

```bash
uv run pytest tests/
uv run pytest tests/path.py -k test_name
uv run pytest tests/path.py -x -n4
uv run pytest integration-tests/
cd ui-v2 && npm test
cd ui-v2 && npm run validate:types
```

测试约束：server 与 client fixture 不混用；数据库测试覆盖 SQLite 和 PostgreSQL；数据库依赖空库的测试显式使用 `clear_db`；Flow timeout 测试使用 thread timeout，避免与 Prefect 的 SIGALRM 机制冲突；优先真实 Flow/Deployment/FlowRun，mock 只用于外部服务和时间敏感场景。

## 9. 必须保持的架构不变量

1. **Flow 与 Task 引擎职责不同**：Flow 状态转换经服务端提议/裁决；Task 状态主要由 Task engine 本地推进并发出事件。
2. **Sync/Async 锁步**：Flow 与 Task 的同步、异步引擎都必须同步实现关键行为，尤其是 retries、timeout、cache、result、suspension 和 hooks。
3. **Server 是状态事实源**：不得在客户端、Worker 或测试中绕过 orchestration layer 直接伪造状态迁移。
4. **数据库双 dialect**：每个迁移、查询和持久化语义都要同时支持 SQLite/PostgreSQL。
5. **Client/Server 边界干净**：客户端 schema 不引用 server schema 或 server database/models；否则会破坏 `prefect-client` 裁剪构建。
6. **Runner 只作门面**：新执行行为应落在抽取的单职责类中；保留的旧方法仅为兼容迁移。
7. **取消权单一归属**：Engine、Runner/Worker 之间要明确谁负责取消、kill、状态和 hooks，避免重复状态历史；`PrefectFuture.cancel()` 本身不等价于杀死已运行的用户代码。
8. **资源与重试有界**：并发租约需续约/释放，事件队列与执行队列需明确容量和丢弃策略，子进程需可回收，事件低流量时仍需时间 checkpoint。
9. **事件 schema 双维护**：客户端 `events/` 与服务端 `server/events/` 是平行契约，结构相似但不能假定同一实现。
10. **UI 双版本共存**：V1/V2 bundle、路由和偏好重定向需保持兼容，服务端打包前必须具备所需 UI bundle。

## 10. 后续底座映射：运行核心与工作流模块

本节不是把 Prefect 的实现宣称为平台现成代码，而是把当前源码已经证实的机制裁决为底座输入：**工作流模块只描述工作流、部署和策略；运行核心统一拥有运行状态、尝试、截止时间、租约、事务、取消和资源收口；调度器/工作器/运行器只负责把可运行意图装配到执行环境**。所有映射均以本目录源码为证据，平台落点属于“吸收/升级/新建/隔离”的设计裁决，不能反向当作 Prefect 已实现的平台契约。

### 10.1 唯一权威链路

Prefect 当前可以压缩成一条可审计的执行链；Flow 与 Task 在状态所有权上有意不同，但不能各自复制一套底座：

```text
@flow/@task/Deployment/Schedule
  → FlowRunEngine 或 TaskRunEngine（参数、依赖、尝试、结果、hooks）
  → PrefectClient/SyncPrefectClient（唯一客户端协议边界）
  → Server orchestration（唯一状态迁移裁决：ACCEPT/REJECT/WAIT/ABORT）
  → State + FlowRun/TaskRun/Result/Lease 事实记录
  → Scheduler 生成可运行计划
  → WorkPool Worker 或本地 Runner 领取/限流/启动
  → FlowRunExecutor → ProcessStarter/ProcessManager → 用户代码
  → StateProposer/Engine set_state + 事件/日志/结果提交
  → 终态收口、租约释放、事务提交或回滚、取消/崩溃补偿
```

映射到平台时只保留一个规范能力入口和一个写 owner：

| 平台边界 | Prefect 事实落点 | 后续底座裁决 |
|---|---|---|
| 工作流模块 | `flows.py`、`tasks.py`、`deployments/`、`schedules.py` | 只生成 `WorkflowSpec/RunIntent` 等声明和策略；不直接写状态表、租约表或结果缓存，不直连 provider。 |
| 运行核心 | `flow_engine.py`、`task_engine.py`、`states.py`、`transactions.py`、`results.py` | 升级为唯一的运行生命周期 owner：状态、尝试、重试、截止时间、结果、事务、取消检查和资源清理均在此编排。 |
| 状态裁决 | `server/orchestration/`、`client/orchestration/` | 吸收为唯一状态写入口；Flow 必须服务端裁决，Task 的本地推进也必须通过其规定的事件/记录边界，不允许旁路 CRUD。 |
| 调度器 | `server/services/scheduler.py` | 只把 schedule/deployment 计算成可运行计划并幂等落库；不执行用户函数、不持有执行资源。 |
| 工作器 | `workers/base.py`、`workers/_worker_channel/` | 只同步 WorkPool、心跳、领取计划、提交基础设施和观察取消；不承担 Runner 的本地部署模型。 |
| 运行器 | `runner/` 抽取类 | 只装配本地执行：`ScheduledRunPoller`、`LimitManager`、`FlowRunExecutor`、`ProcessManager`、`StateProposer`、`CancellationManager`；`Runner` 仅作兼容门面。 |
| 事件/时间 | `events/`、`server/events/`、`PrefectEventsClient` | 事件是观测和自动化输入，不是第二状态写入口；客户端 count/time checkpoint 必须同时存在，低流量不得因无事件而失去确认。 |

因此，平台的“工作流模块”不得复制 `retry/cache/timeout/lease/cancel` 五套实现；它只提交策略，运行核心依据同一份策略和同一条状态链执行。Prefect 客户端与服务端 schema、客户端事件与服务端事件虽然平行维护，也都只能在适配边界做一次转换，不能让业务消费者各自翻译。

### 10.2 状态模型、终态和状态归属

源码的状态类型集合和终态必须拆开记录：`StateType` 是 `SCHEDULED/PENDING/RUNNING/COMPLETED/FAILED/CANCELLED/CRASHED/PAUSED/CANCELLING`（`src/prefect/client/schemas/objects.py:89-108`）；终态只有 `COMPLETED`、`CANCELLED`、`FAILED`、`CRASHED`。`AwaitingRetry`、`Retrying`、`AwaitingConcurrencySlot`、`NotReady`、`Late`、`TimedOut` 等主要是状态名称或业务语义，不应另造一套互不相容的终态枚举。

运行核心应执行如下闭包，而非只判断一个 `success` 布尔值：

| 输入/中间态 | 运行核心处理 | 允许的最终收口 |
|---|---|---|
| `SCHEDULED/PENDING` | 等待调度、依赖或并发资源；按时间/退避再次尝试，不执行用户代码 | `RUNNING` 或由策略拒绝/标记失败 |
| `RUNNING` | 记录本次 attempt、开始时间、心跳、租约和结果上下文 | `COMPLETED`、`FAILED`、`CRASHED`、`CANCELLING` |
| `PAUSED` | 保存恢复上下文和暂停截止时间；未到期不得伪造 Running | `RUNNING`、`FAILED` 或外部取消 |
| `CANCELLING` | 只能由唯一取消 owner 推进；等待子进程/基础设施/状态确认 | `CANCELLED`；无法确认取消时按 Runner 规则落 `CRASHED`，并保留原因 |
| `FAILED` 且有余量 | 由 retry policy 产生 `AwaitingRetry(scheduled_time=...)`/`Retrying` | 新 attempt 的 `RUNNING`，或耗尽后的 `FAILED` |
| `BaseException`/宿主崩溃 | 不把未知退出伪装成业务失败；由 engine/runner/服务端补偿识别 | `CRASHED`，随后由恢复策略决定是否重新排队 |
| `COMPLETED/CANCELLED/FAILED/CRASHED` | 禁止普通路径再次执行；只允许有明确幂等/修复契约的补偿命令 | 保持终态，并释放所有持有资源 |

`StateGroup` 以 `final_count`、`not_final_count`、`fail_count`、`paused_count` 提供批量收口（`src/prefect/states.py:679-729`），可直接映射为波次/工作流聚合器；`all_final()` 不能被 `all_completed()` 替代，否则取消、失败和崩溃会被错误地当成未收口。`state_details.scheduled_time`、暂停超时、缓存键、输入 keyset、租约 ID 等是迁移上下文，必须随状态边界传播，不能仅存于内存日志。

**裁决：吸收并升级。** 吸收 Prefect 的“类型终态 + 业务名称 + 状态详情 + StateGroup 聚合”四层模型；升级平台状态契约，明确终态不可自动回退、终态资源释放、重试使用新 attempt、`CANCELLING` 必须有超时补偿。工作流模块只声明允许的状态策略，运行核心和权威状态服务负责实际迁移。

### 10.3 重试、退避、缓存事务、超时和租约的进入点

这些机制都进入运行核心的“attempt 外圈”，工作流模块只提供参数/策略：

```text
创建 attempt
  → 依赖与暂停检查
  → 获取并发租约
  → 向状态 owner 提议 Running
  → deadline/取消检查
  → transaction(cache key) 读取或调用用户函数
  → 成功提交结果 / 失败回滚结果
  → 按 retry policy 产生新 attempt 或终态
  → 释放租约、发送事件、更新终态
```

| 机制 | Prefect 证据和语义 | 底座唯一落点与边界 |
|---|---|---|
| 重试 | `task_engine.py:660-711` 检查 `retries` 和 `retry_condition_fn`；支持数值/序列延迟，序列尾值可复用，延迟进入 `AwaitingRetry`，无延迟进入 `Retrying`，耗尽进入 `Failed`；Flow 也持有 retry policy。 | 运行核心统一计算 `attempt_no`、原因、下次时间和幂等键；工作流模块仅配置策略。服务端/状态 owner 复核“是否允许重试”，不能让客户端单方面制造重试终态。 |
| 退避 | `clamped_poisson_interval` 用于 Pending/Paused 轮询（`task_engine.py:540-550`、`utilities/math.py:43`），重试延迟另可叠加 jitter。 | 统一退避算法和上限，区分“业务重试延迟”和“等待状态轮询退避”；禁止各模块固定 sleep 造成惊群。 |
| 缓存/事务 | `transaction.py:59-64` 的 `TransactionState`：`PENDING→ACTIVE→STAGED→COMMITTED/ROLLED_BACK`；`task_engine.py:963-989` 以 `compute_transaction_key()`、ResultStore、overwrite、isolation level 进入事务；命中已提交结果时跳过用户函数。 | 运行核心拥有缓存事务和结果引用的读写 owner；工作流模块只能选择 cache policy/expiration/refresh，不得把任意业务对象当缓存已提交事实。提交、回滚、锁释放和二次执行必须幂等。 |
| 超时 | Task `handle_timeout()` 将耗尽重试的超时置为 `Failed(name="TimedOut")`（`task_engine.py:730-743`）；Flow engine 同样区分 timeout；线程阻塞 I/O 无法可靠中断，async 需在可取消 await 边界响应。 | 运行核心持有 deadline、超时原因和终态转换；工作流模块只声明 timeout。超时不是自动 `Crashed`，也不能因线程无法中断而声称用户代码已停止，必须记录“执行可能仍存活”的资源风险。 |
| 租约续约 | Task 外圈使用 `ConcurrencyLeaseHolder`、`lease_duration=60`（`task_engine.py:949-955`）；`concurrency/_leases.py` 提前续约，失败重试/退避，严格模式可取消执行；客户端 API 有 `/v2/concurrency_limits/leases/{lease_id}/renew`。 | 运行核心通过统一 `LeaseHandle` 获得/续约/释放；并发服务是唯一 slot owner。续约失败要么告警并标记可能超分配，要么按显式策略取消，不能静默继续。终态、超时、取消、崩溃都必须释放或由服务端过期回收。 |

**缓存与状态的顺序约束：** 先决定事务是否命中，再进入用户函数；成功先 `stage` 结果，再把终态与结果引用关联；提交失败必须保留失败/回滚证据并释放锁；取消/超时发生在提交边界时不能同时生成“已提交”和“已回滚”两条相互矛盾的事实。`ResultRecord` 只作为持久化引用进入状态，结果内容不应穿透 State/Server schema。

**裁决：吸收 + 升级。** Prefect 的可复用原子能力是 retry decision、backoff、transaction/cache、deadline、lease renewal；需要升级为平台统一的 `AttemptCoordinator`（名称为平台设计，不是 Prefect 现有类），由它串接这些能力并向工作流模块提供单一调用入口。不同 provider/执行器只能替换 `ProcessStarter` 或存储适配器，不能复制 attempt 外圈。

### 10.4 调度器、工作器、运行器如何进入工作流模块

三者是不同生命周期，不得合成一个“执行器大模块”：

1. **Scheduler → Workflow module**：`Deployment` 的 schedule/parameters 经过 `server/services/scheduler.py` 计算成计划运行并写入事实源。它只负责未来运行的幂等补排、游标分页和批量插入，不能执行 Flow，也不能直接占用并发租约。
2. **Worker → Runtime adapter**：`BaseWorker.sync_with_backend()` 将 WorkPool 同步与心跳委托给 `WorkPoolWorkerChannel`；计划运行查询仍为 REST。Worker 使用本地 `CapacityLimiter`，把 job template/pull steps 转成基础设施命令，提交 Process/Docker/Kubernetes 等环境，并观察取消。它不是本地 Runner 的替代品。
3. **Runner → Runtime core**：无 WorkPool 的本地 `Runner` 由 `ScheduledRunPoller` 发现计划、`LimitManager` 限流、`FlowRunExecutor` 管单次生命周期；`ProcessManager` 管 PID/kill，`StateProposer` 管 API 状态提议，`CancellationManager` 管取消意图、kill、hooks、状态和事件。新行为必须进入这些抽取类，不得回填兼容门面 `Runner`。
4. **统一回到运行核心**：无论计划来自 Scheduler→Worker，还是 Runner 本地轮询，启动后都必须进入同一个 `FlowRunExecutor`/Flow engine 状态和资源协议；只能在“如何启动基础设施”处有策略差异。

```text
WorkflowSpec/Deployment
  → Scheduler（何时可运行）
  → ScheduledRun（事实记录）
  → Worker 或 Runner（在哪里启动、领取和限流）
  → FlowRunExecutor/TaskRunEngine（如何执行、重试、超时、取消）
  → State/Result/Event/Lease owner（如何落账和收口）
```

**裁决：吸收职责分离，升级为一个装配协议。** 工作流模块提供声明，调度器只产出计划，工作器/运行器只产出执行上下文，运行核心只产出状态与证据。禁止工作流模块绕过调度/运行核心直接调用 `Process`、Docker SDK、数据库或第三方调度 API。

### 10.5 事件触发与时间检查点

客户端事件 `PrefectEventsClient` 同时使用两种确认机制：事件数量达到 `checkpoint_every` 时检查，以及独立的 `checkpoint_interval` 后台任务按时间检查；`events/AGENTS.md` 明确低流量场景不能只靠数量阈值。事件 schema 与 server schema 平行维护，服务端才负责持久化、触发器评估和动作执行。

映射规则如下：

- 运行核心在状态变化、心跳、取消、重试和终态时发出语义事件；事件发送失败不应回滚已经完成的主执行，Runner 的 `EventEmitter` 在 WebSocket 失败时降级为 `NullEventsClient`。
- 事件模块只负责构造、排队、发送、订阅和 checkpoint；不得把“事件已发送”当作“状态已提交”，也不得从事件消费者旁路更新状态。
- `Reactive` 表示事件出现，`Proactive` 表示事件在时间窗内缺失；`threshold`、`within`、`after/expect`、`for_each` 是触发器条件，不是状态机终态。`MetricTrigger` 在 OSS 中不能当作可用能力，需标记 Cloud-only 或改用 Proactive EventTrigger。
- 时间检查点既是事件确认机制，也是运行核心的可靠性边界：低流量时按时间 flush/确认，服务重启后可从事实源和事件持久化恢复；调度器扫描、租约续约、取消超时、暂停过期和孤儿回收同样必须以时间为驱动，不能依赖“下一条事件恰好到达”。
- `for_each` 的资源分组和 related 关系只用于触发器匹配；同一资源的事件幂等键、因果链 `follows` 和时间窗口必须保留，避免重复动作。

**裁决：吸收时间 checkpoint，隔离事件动作。** 事件进入运行核心的出口是统一 `EventSink`/adapter（平台设计名），状态事实仍由状态 owner 写入；事件触发器属于工作流自动化模块，触发动作只能提交公开命令回到运行核心，不得直接更新底层状态。

### 10.6 状态终态、资源、取消与恢复矩阵

| 资源/事实 | 创建与持有者 | 正常完成 | 业务失败/重试 | 取消/超时 | 崩溃/宿主退出的恢复证据 |
|---|---|---|---|---|---|
| State/Run 记录 | Engine 提议，Server orchestration 写入 | `COMPLETED` 并固定终态 | `FAILED` 或生成下一 attempt | `CANCELLING→CANCELLED`，超时由 `CancellationCleanup` 补齐 | `CRASHED` 或由服务端回收/重排，不能凭客户端日志判定成功 |
| ResultStore/缓存事务 | Task engine + `Transaction` | `STAGED→COMMITTED`，结果引用写入 State | `ROLLBACK`，执行重试不得复用未提交值 | 事务边界回滚，释放 SERIALIZABLE 锁 | 通过锁/缓存读回确认无半提交记录；`refresh_cache` 只能显式覆盖 |
| 并发 slot/lease | 运行核心取得，服务端 limit owner | release；服务端读回 active slots | 重试前释放旧 attempt 或明确转移 | 续约停止，释放/过期回收 | `Repossessor`/lease expiry 清理孤儿，严格续约失败可取消 |
| 线程/TaskRunner | `TaskRunner` 创建与持有 | `cancel_all`/上下文退出，线程池收口 | 清理 Future 和回调 | 线程中阻塞 I/O 可能无法杀死，必须标记风险并避免重复执行 | 进程边界或宿主重启确认无遗留 worker；禁止无界建线程 |
| 子进程/基础设施 | Worker/Runner 的 `ProcessManager`/starter | 等待退出码并映射状态 | 记录退出码、stderr、attempt | ControlChannel 先发取消意图，再按平台 kill；`CancelFinalizer` 固化 Cancelled，无法确认时 Crashed | PID/容器/临时目录读回；SIGTERM→SIGKILL 结果要有证据 |
| Worker/Runner channel | WorkerChannel/ControlChannel | flush 事件、关闭连接 | 可重连、回退 REST/轮询 | 停止接新运行，等待在途收口 | 断线后由服务端事实、心跳和 cleanup 服务恢复，而非依赖内存 map |
| Event queue/WebSocket | EventsWorker/`EventEmitter` | checkpoint/flush 后关闭 | 允许丢弃非关键 telemetry，但主状态不丢 | 取消发送任务并关闭客户端 | checkpoint、服务端事件表和重连去重证明已处理范围 |
| workspace/临时文件 | pull step、bundle builder、基础设施 starter | 上下文退出删除或归档 | 失败路径清理 | 超时/取消仍执行 finally 清理 | 重启扫描临时前缀、PID、锁和端口，保留清理结果 |

取消权必须单一归属：Runner 的 `CancellationManager` 负责控制通道、kill、hooks、状态和事件；Worker 只在基础设施尚未启动时直接取消并写回结果；Flow/Task engine 只在自己持有取消权时推进对应状态。服务端 `CancellationCleanup`、`PauseExpirations`、`LateRuns`、`Foreman`、`Repossessor` 是恢复闭环，不是可选监控。任何“Cancelled 已写入但子进程仍活着”或“子进程已 kill 但状态仍 CANCELLING”都必须进入补偿扫描。

### 10.7 真实验证与验证等级

当前核对只允许修改根 `ARCHITECTURE.md`，未启动 Prefect server、Worker、Runner、UI 或外部数据库；因此不能把源码存在、测试文件存在或文档中的命令写成“运行通过”。验证应按以下等级入账：

| 等级 | 可证明内容 | 当前核对事实/命令 |
|---|---|---|
| 源码事实 | 类、枚举、调用边界和终态存在 | 已读取 `states.py`、`transactions.py`、`task_engine.py`、`runner/AGENTS.md`、`workers/AGENTS.md`、`events/AGENTS.md` 及对应源码索引 |
| 测试存在 | 有针对性测试入口，但不代表通过 | 已定位 `tests/public/{tasks,flows}/test_*_timeouts.py`、`tests/test_transactions.py`、`tests/concurrency/test_raise_on_lease_renewal_failure.py`、`tests/runner/test__event_emitter.py`、`tests/events/client/test_events_client.py` |
| 静态真实验证 | 文档格式/差异无空白错误 | 修改后应执行 `git diff --check`；退出码以现场命令回执为准 |
| 进程内真实验证 | 需真实执行 timeout/retry/cache/lease/event/runner 测试 | 当前核对未执行 `uv run pytest`，不能标记通过 |
| 服务/数据库验证 | 需启动 API、SQLite/PostgreSQL、Worker/Runner，读回状态、租约、进程和事件 | 当前核对未执行；调度精度、WebSocket、取消时序和双 dialect 仍为待核 |

最小可复核命令（后续工作包，不在当前核对宣称已通过）为：

```bash
uv run pytest tests/public/tasks/test_task_timeouts.py tests/public/flows/test_flow_timeouts.py tests/test_transactions.py
uv run pytest tests/concurrency/test_raise_on_lease_renewal_failure.py tests/runner/test__event_emitter.py tests/events/client/test_events_client.py
git diff --check
```

真实验收不能只看 pytest 绿灯，还必须读回：终态是否属于四个终态集合、重试是否产生新 attempt、缓存提交/回滚和锁是否清理、lease active slots 是否归零、取消后 PID/容器/临时目录是否消失、事件 checkpoint 是否在低流量时间窗口触发。外部服务失败、测试跳过、无数据库配置和仅 mock 的事件都只能记为“未验证/部分验证”。

### 10.8 复用/升级/新建/隔离裁决与装配计划

| 裁决 | 内容 | 证据/原因 |
|---|---|---|
| 吸收 | 状态终态 + StateGroup；retry/backoff；事务缓存；deadline；lease renewal；Scheduler/Worker/Runner 分工；事件 count/time checkpoint；取消补偿服务 | 这些均有当前源码或 `AGENTS.md` 直接证据，且能进入运行核心公共契约 |
| 升级 | 建立统一 `AttemptCoordinator`、`CancellationReconciler`、`ResourceLedger`、`EventSink`（均为平台落点名）并让 Flow/Task 共用；保留 Flow server-authoritative 与 Task local + event-emitted 的明确差异 | Prefect 现状有 sync/async 双实现和 Worker/Runner 新旧并存，直接复制会形成侧链 |
| 新建 | 时间驱动 checkpoint/reconciler 的统一接口，以及四终态资源验收探针；允许 provider 适配器实现存储/执行差异 | 低流量事件、取消超时、孤儿资源需要统一证据，不应靠每个模块自扫 |
| 隔离 | Prefect Cloud-only `MetricTrigger`、WorkPool/Cloud/Kubernetes provider 细节、客户端/服务端平行 schema、旧 `Runner.execute_bundle()` 兼容路径 | 与平台核心契约无关或仍属迁移/外部依赖，不能升格为公共底座 |
| 废弃 | 工作流模块直连第三方、模块自写状态/租约/缓存、Runner 兼容门面新增行为、事件旁路改状态 | 违反唯一 owner、资源责任跟随调用链和单链路原则 |

装配顺序固定为：

1. 工作流模块注册 `WorkflowSpec/Deployment` 和策略，不注册第二份执行器。
2. 运行核心注册状态、attempt、deadline、transaction、lease、cancellation、event sink 的能力契约。
3. Scheduler/Worker/Runner 只注入计划来源、启动策略和资源适配器；所有运行进入同一个 attempt 外圈。
4. Server/state owner 读回状态与租约，reconciler 扫描 `CANCELLING`、过期 lease、Late/Paused 和孤儿基础设施。
5. 先完成进程内真实测试，再做真实 API/数据库/Worker/Runner 联调；每一层必须回传命令、退出码、测试/跳过数、外部依赖和残留资源读回结果。

## 11. 未确认项与风险

- **代码地图风险（已确认）**：按任务要求调用的专属 MCP `system_engineering_toolkit`（`http://127.0.0.1:8766/mcp/`）返回的 `project_context` 和 `codegraph_explore` 均绑定到其当前项目 `/Users/hekunhua/Documents/Agent/PHP/系统工程平台`，未切换到 Prefect；因此本档不采用该错误项目的符号/调用链证据，架构事实来自 Prefect 目录内实际读取的源码、`AGENTS.md`、README、`pyproject.toml` 和 `细探-prefect.md`。后续若需要完整代码地图，应先修复专属 MCP 的项目绑定，再按 Prefect 根目录重建/查询地图。
- 当前核对没有启动 Prefect server、Runner、Worker、UI 或外部数据库，未对运行时调用链、真实 HTTP/WebSocket、迁移、调度精度和取消时序做动态验证。
- 未执行依赖解析、构建、pytest、Vitest、Playwright、lint 或类型检查；测试命令仅记录项目约定，不能视为通过证据。
- 代码存在新旧架构并存面：Worker 与新 Runner 同时存在，旧 `Runner.execute_bundle()` 等路径仍有迁移缺口；UI v1 与 UI v2 并存。
- `prefect-client` 的裁剪构建依赖跨文件依赖闭包和 root/client pyproject 同步，本档未实际运行 `client/build_client.sh`。
- OSS 服务端不提供 Cloud 同等级 RBAC/多租户能力；Cloud-only 的 Metric trigger、RBAC 和租户隔离不能从本地 OSS 实现推断。
- `细探-prefect.md` 是当前核对之前已有的未跟踪细探文档，基线提交/规模描述与当前源码可能随归档更新而漂移；本文件优先引用当前磁盘源码和当前 `git` 基线，旧细探已逐项裁决，后续只维护本文件。

## 12. 当前核对边界记录

仅修改：`ARCHITECTURE.md`。未修改源码、依赖、测试、配置、锁文件或 `细探-prefect.md`；未删除任何文件；未安装、启动、构建或提交 Git。

## 13. 旧细探吸收与裁决记录

`细探-prefect.md` 已完整读取，且针对当前源码逐项核对。它仍保留在项目根目录作为
历史研究证据；长期维护入口只有本 `ARCHITECTURE.md`，不再把旧细探当作并行架构事实源。

| 旧细探主题 | 裁决 | 吸收位置与当前证据 |
|---|---|---|
| SDK → Flow/Task 引擎 → Client → Server → DB → Worker/Runner 的三段式边界 | 吸收 | 第 1、2、3、4 节；`src/prefect/flow_engine.py`、`task_engine.py`、`client/`、`server/`、`workers/`、`runner/`。 |
| `StateType`、业务状态名、`StateDetails` 迁移上下文、`StateGroup` 聚合 | 吸收 | 第 4.1 节；`src/prefect/client/schemas/objects.py`、`src/prefect/states.py:679`。 |
| Flow 状态必须由服务端编排规则 ACCEPT/REJECT/WAIT；规则链含重试、并发、暂停、资源释放 | 吸收 | 第 4.1、6.1、9 节；`src/prefect/server/orchestration/rules.py`、`core_policy.py`。 |
| Task 的依赖等待、泊松抖动退避、重试延迟/jitter、事务缓存与线程超时边界 | 吸收 | 第 4.2、5 节；`src/prefect/task_engine.py`、`transactions.py`、`utilities/math.py`。 |
| 标签租约、续约窗口、失败策略、v1/v2 槽位协作 | 吸收 | 第 4.2、9 节；`src/prefect/concurrency/_leases.py`、`server/orchestration/core_policy.py`。 |
| Scheduler 的按 schedule 补排、游标分页、批量写入、近期部署快速扫描 | 吸收 | 第 4.3 节；`src/prefect/server/services/scheduler.py`。 |
| Worker 的 WorkPoolChannel 边界、本地限流、基础设施启动与取消观察 | 吸收 | 第 4.3、5 节；`src/prefect/workers/base.py`、`workers/AGENTS.md`。 |
| Runner 的拆分式职责、轮询/限流/进程/状态/取消组件与兼容门面约束 | 吸收 | 第 3、4.3、9 节；`src/prefect/runner/runner.py`、`runner/AGENTS.md`。 |
| 事件触发器的 Reactive/Proactive、通配符、时间窗、`for_each`、动作与时间 checkpoint | 吸收 | 第 4.4、9 节；`src/prefect/events/clients.py`、`events/schemas/automations.py`、`events/AGENTS.md`。 |
| 结果状态只携带持久化元数据、块/本地存储解析与读取重试 | 吸收 | 第 5、7、9 节；`src/prefect/results.py`、`states.py`、`_internal/result_records.py`。 |
| 测试分层、可靠性/压测/兼容测试和未执行事项 | 吸收 | 第 8、10 节；`tests/`、`integration-tests/`、`compat-tests/`、`load_testing/`。 |
| 旧细探中的源码行数、目录规模与“124MB”统计 | 不吸收为架构事实 | 属于随提交和工作树变化的快照统计；本文件只保留当前基线的粗粒度计数，并明确来源。 |
| “SequentialTaskRunner 为 v3 默认、内置 DaskTaskRunner” | 不吸收 | 当前 `task_runners.py` 没有 `SequentialTaskRunner`，`ConcurrentTaskRunner` 是线程池兼容别名，Dask 通过外部集成示例接入；见第 4.2 节。 |
| 旧细探中未在当前源码重新核实的固定默认秒数、批次上限和历史 API 版本分支 | 不吸收为无条件事实 | 这些值受当前 settings、API 版本和部署模式影响；仅保留源码中可定位的行为，不把旧快照默认值推广为平台契约。 |
| Cloud/RBAC/多租户、真实 HTTP/WebSocket、调度精度和取消时序的运行时结论 | 待核 | OSS 源码可说明边界，但当前核对未启动服务或外部系统；保留在第 11 节，后续需动态验证。 |

## 14. 后续收口：Flow/Task、调度队列、Worker 与恢复事实表

本节是对旧 `细探-prefect.md` 的后续逐项收口，不新增平行实现说明。以下结论均以当前工作树源码为证据；“源码存在”与“已运行通过”严格分开。源码版本基线仍为 `2cc0f474c027cd8e19ecf6b34386908dcb301213`。

### 14.1 契约与状态所有权表

| 契约/节点 | 输入与真实动作 | 输出/失败分支 | 所有权与证据 |
|---|---|---|---|
| `@flow` / Flow run | `Flow` 保存参数校验、`retries`、`retry_delay_seconds`、`timeout_seconds`、结果存储和 hooks；`FlowRunEngine.begin_run()` 先解析依赖，再校验参数，最后提议 `Running` | 上游未完成写 `Pending(name="NotReady")`；服务端拒绝 `Running` 时循环重提；用户异常/超时写 `Failed`，`BaseException` 写 `Crashed` | Flow 状态提议由 `propose_state_sync`/异步等价路径发送到 Server；`src/prefect/flows.py:145-229`、`src/prefect/flow_engine.py:688-771` |
| `@task` / Task run | `TaskRunner.submit/map` 创建 `PrefectFuture`；Task engine 解析参数、等待 `wait_for`、推进本地状态、进入事务和任务函数 | `UpstreamTaskError` → `Pending(NotReady)`；失败按 `retry_condition_fn` 和剩余次数决定 `Retrying/AwaitingRetry`，耗尽为 `Failed`；`BaseException` 为 `Crashed` | Task 的状态对象在本地 engine 更新，并发出 `prefect.task_run.*` 事件；不得把 Flow 的服务端提议模型直接套到 Task；`src/prefect/task_engine.py:516-605` |
| 状态裁决 | Flow/Worker/Client 提交状态提议，Server 按 `CoreFlowPolicy`/`CoreTaskPolicy` 顺序运行规则 | `ACCEPT`、替换/拒绝、`WAIT`、`ABORT`；终态为 `COMPLETED/FAILED/CANCELLED/CRASHED`，不能普通回退 | `src/prefect/server/orchestration/core_policy.py:111-180`；`force=True` 仍经过 `MinimalFlowPolicy` 的保护，非绕过 |
| 结果/事务 | Task engine 以 cache key 进入 `Transaction`，读取已提交结果或调用用户函数；结果先 stage，再按 commit mode 写入 `ResultStore` | `PENDING→ACTIVE→STAGED→COMMITTED/ROLLED_BACK`；读取外部结果允许有限重试，半提交不能作为成功 | `src/prefect/transactions.py:48-87`、`src/prefect/states.py:46-75,96-135`；状态只传 `ResultRecordMetadata`，不传任意业务对象 |

**关键差异：** Flow 的 `FlowRunEngine.handle_timeout()` 直接提议 `Failed(name="TimedOut")`，最终是否接受仍由服务端决定；Flow 的重试参数在初始化时写入 `flow_run.empirical_policy`，由 `RetryFailedFlows` 规则在服务端调度下一次尝试。Task 的 `handle_retry()` 则在客户端 engine 依据任务配置计算延迟和状态（`src/prefect/task_engine.py:660-743`），服务端仍可通过 Task policy 拒绝不合法迁移。不能把“Flow 客户端有完整 `handle_retry`”或“Task 完全绕过服务端”写成当前事实。

### 14.2 调度与队列的真实领取语义

```text
DeploymentSchedule(active)
  → SchedulerService 主循环/最近部署快速循环
  → FlowRun(state=SCHEDULED, next_scheduled_start_time, work_queue_id)
  → Worker POST /work_pools/{name}/get_scheduled_flow_runs
  → WorkPool/WorkQueue 暂停、并发槽位、时间窗、优先级和行锁过滤
  → Worker 本地 CapacityLimiter
  → propose Pending/Submitting
  → 基础设施运行
```

| 环节 | 当前源码行为 | 资源/一致性边界 |
|---|---|---|
| 主调度 | `schedule_deployments()` 只选“任一 active schedule 的未来运行数不足或最远计划时间不足”的 Deployment；按 Deployment ID 游标分页；每个 schedule 计算运行后按 `insert_batch_size` 分批插入 | `created_by.id` 关联 schedule，查询只统计 `auto_scheduled=true` 且 `SCHEDULED` 的未来运行；数据库错误导致连接 invalidated 时回滚并 `TryAgain`；`src/prefect/server/services/scheduler.py:35-127,170-285` |
| 快速调度 | `schedule_recent_deployments()` 只扫描最近更新且有 active schedule 的 Deployment；与主调度重叠是允许的，因为插入逻辑必须幂等 | 新建/更新部署不必等完整主循环；不能将“5 秒”等历史默认值写成无条件平台契约，实际值来自 settings；`scheduler.py:130-167,288-358` |
| 队列领取 | Worker 以 work-pool 名称、队列名列表和 `scheduled_before=now+prefetch` 查询；Server 只取未暂停 pool/queue、`SCHEDULED`、非 `in_process` 重试运行，按最早 `next_scheduled_start_time` 排序 | PostgreSQL 使用 `FOR UPDATE SKIP LOCKED`；队列/Pool 可用槽位限制每队列和整个 Pool 的返回量；`src/prefect/client/orchestration/_work_pools/client.py:278-320`、`server/database/sql/{postgres,sqlite}/get-runs-from-worker-queues.sql.jinja` |
| 队列优先级 | 查询可由 `respect_queue_priorities` 选择按 `work_queue.priority ASC` 再按计划时间排序；Worker 常规 work-pool 拉取路径必须以服务端返回顺序为准，不能假定所有调用都启用优先级 | 优先级不是全局状态，也不替代 Pool/Queue 并发；SQLite 用窗口函数，PostgreSQL 用 lateral join，双 dialect 语义需锁步；`server/database/query_components.py:124-243` |
| Worker 本地限流 | `_submit_scheduled_flow_runs()` 对每个 `flow_run.id` 使用 `CapacityLimiter.acquire_on_behalf_of_nowait`；满额立即停止当前核对提交，重复 ID 由 `_submitting_flow_run_ids` 跳过 | 领取槽位、提交槽位和基础设施槽位必须在异常/未就绪路径释放；`_submit_run_and_capture_errors()` 的 `finally` 释放，重复释放只记录 debug；`src/prefect/workers/base.py:1495-1553,1616-1706` |

因此，“队列”不是内存 FIFO：计划运行先落 Server 数据库，Worker 按服务端过滤/锁定/排序领取；本地 `CapacityLimiter` 只限制正在提交/执行的 Worker 任务。WorkPool/WorkQueue 的并发与 Task tag/deployment concurrency 是不同层次，不能合并成一个 `queue_size` 字段。

### 14.3 重试、超时、取消、恢复失败矩阵

| 场景 | 首次动作 | 可能残留/失败 | 恢复或补偿证据 |
|---|---|---|---|
| Task 业务异常 | `can_retry()` 调 `retry_condition_fn`；有余量则写 `Retrying` 或带 `scheduled_time` 的 `AwaitingRetry`，`retries` 自增；否则写 `Failed` | 条件函数自身异常会记录并视为不重试；延迟列表末值会重复使用；结果事务可能已 stage | 新 attempt 必须从新状态进入，旧 lease/事务需释放；`task_engine.py:442-477,660-743`、`transactions.py` |
| Flow 业务异常/超时 | Engine 提议 `Failed`；`empirical_policy` 让 Server 的 `RetryFailedFlows` 规则判断是否生成 `AwaitingRetry` | 线程或阻塞 I/O 超时不能杀死用户代码；Flow timeout 只代表状态提议/失败原因，不证明进程已停止 | Worker/Runner 以 PID、子进程退出和服务端终态为准；不能用客户端日志代替状态读回 |
| Pending/Paused/槽位不足 | Engine 轮询 `set_state(Running)`；Task 使用 `clamped_poisson_interval`，未来 `scheduled_time` 到点后再尝试 | 固定 sleep 惊群；客户端断线时内存循环无法成为事实源 | Server 状态、lease expiry、`LateRuns`、`PauseExpirations` 扫描；`task_engine.py:540-550`、`server/orchestration/core_policy.py` |
| Worker 提交异常 | `_submit_run_and_capture_errors()` 记录异常并提议 `Crashed`；未真正启动时通知 task group，统一释放本地限流槽 | 基础设施返回无状态/异常退出码时无法证明用户函数运行结果；`infrastructure_pid` 写回失败会使运行不可取消 | 读回 `infrastructure_pid`、退出码和状态；Worker 不应把非零基础设施退出码当业务 `Failed`；`workers/base.py:1616-1693` |
| Runner 取消 | `CancellationManager` 先发送 attempt-scoped `cancel` intent，再 `ProcessManager.kill()`；成功杀停后跑 hooks、提议 `Cancelled`、发取消事件 | control channel 不 ack 时按 crash 风险处理；POSIX 为 SIGTERM 后等待，超时 SIGKILL；kill 非预期异常会中止后续状态收口 | `CancelFinalizer`/StateProposer 读回状态；服务端 `CANCELLING` 超时检查最终标 `Cancelled`，无法确认时按 Runner 规则 `Crashed`；`runner/_cancellation_manager.py:72-215`、`_process_manager.py:182-264` |
| Worker 取消 | `FlowRunCancellingObserver` 事件优先、轮询兜底；仅当 `start_time is None` 时由 Worker 直接处理，按 `infrastructure_pid` 调 `kill_infrastructure` | 已启动的运行交给基础设施/Runner；未实现或暂不可用的 kill 可能保持 `CANCELLING` 或出现“状态已取消但基础设施仍活着”风险 | `CancellationCleanup` 为每个 CANCELLING 状态写入带 key 的超时检查；子任务按非终态批量取消；`workers/base.py:1396-1422,1844-1924`、`server/services/cancellation_cleanup.py:53-118` |
| Worker/Server 崩溃 | Worker 心跳停止；Server 后台服务仍扫描状态和 worker | 内存中的 `_submitting_flow_run_ids`、进程 map、事件队列不可作为恢复依据 | `Foreman` 按 heartbeat 将 Worker 标为 `OFFLINE`，无在线 Worker 的 Pool 标 `NOT_READY`，过期 deployment/queue 标 `NOT_READY`；`Repossessor` 回收过期租约；`server/services/foreman.py:32-69` |

### 14.4 资源生命周期闭包

| 资源 | 创建/持有 | 正常完成 | 失败、取消、崩溃收口 | 未确认风险 |
|---|---|---|---|---|
| Task thread/process pool | `ThreadPoolTaskRunner`/`ProcessPoolTaskRunner` 创建 executor；Future 持有运行引用 | runner 上下文退出，`cancel_all`/executor 收口 | 线程阻塞 I/O 不可强杀；ProcessPool 数据必须可 pickle；嵌套 submit 在有界池可能饥饿 | 仅源码/测试存在，未当前核对运行 fd、线程和进程残留探针 |
| Server concurrency lease / Worker limiter | Task engine 取得 tag lease；Flow/Deployment/WorkPool/Queue 分层占槽；Worker 取得本地 limiter token | 终态或提交异常释放；lease 续约线程停止并有限 join | 续约失败默认告警，严格模式取消；Server lease expiry/Repossessor 兜底；重复 release 必须幂等 | 外部 Server/Redis lease storage 未启动，active slots 未读回 |
| Runner child process | `ProcessManager` map 保存 PID/handle；`ControlChannel` 绑定 attempt token | executor 收到退出、移除 map；Runner 退出逐个 kill 后清空 map | SIGTERM→最多 grace→SIGKILL；control ack 失败可能落 `Crashed`；子进程已死但状态未确认需 finalizer | 当前核对未实际创建 PID，无法宣称 kill 时序通过 |
| Result/transaction | Task engine 创建 cache key、`Transaction`、`ResultStore`；ResultRecord 写入后需 `mark_persisted()` | stage/commit 后 State 只保存 metadata 引用 | exception/timeout/cancel 回滚；外部存储异步写入时读取最多有限重试 | 未接真实块存储，写入/断线/半提交需动态验收 |
| Events/logs/Worker channel | EventsWorker/Emitter、HTTP/WebSocket subscriber、WorkerChannel 队列 | checkpoint/flush 后关闭；EventEmitter 连接失败可降级 `NullEventsClient` | telemetry 丢失不应改变主状态；队列写入失败需重试/丢弃计数；channel 断线回退 REST/轮询 | 未实测低流量时间 checkpoint、重连、协议版本和丢弃边界 |
| Worker attribution/env | `BaseWorker.setup()` 写 `PREFECT__WORKER_NAME`；首次心跳成功后写 ID；子进程由 `prepare_for_flow_run` 注入 | `teardown()` 仅在值仍属于当前 Worker 时清理 | Worker 同进程复用/心跳失败不能提前假定 backend ID；缺注入参数会丢 child attribution | 只读源码确认，未启动两个 Worker 进行环境隔离实测 |

### 14.5 当前核对真实验证等级与剩余闭口

| 等级 | 当前核对结果 |
|---|---|
| 源码取证 | 已读取并核对 `flow_engine.py`、`task_engine.py`、`flows.py`、`tasks.py`、`task_runners.py`、`states.py`、`transactions.py`、`server/orchestration/core_policy.py`、`server/services/scheduler.py`、队列 SQL 模板、`workers/base.py`、`runner/_cancellation_manager.py`、`runner/_process_manager.py` 及对应 `AGENTS.md`。 |
| 旧细探吸收 | `细探-prefect.md` 已完整读取；其“SequentialTaskRunner v3 默认”“内置 DaskTaskRunner”“固定默认批次/秒数”等与当前源码或 settings 不一致的说法不升格为事实，旧文件继续保留。 |
| 测试源码 | 已定位引擎 timeout、transaction、lease renewal、runner cancellation/event、scheduler/queue/orchestration 测试入口；测试文件存在不等于通过。 |
| 静态验证 | 已执行 `git diff --no-index --check /dev/null ARCHITECTURE.md`；无 trailing whitespace 输出。因目标文档在基线中是未跟踪文件，比较命令返回 1 属于差异存在，不是检查错误。 |
| 动态验证 | 未启动 Server、SQLite/PostgreSQL、Worker、Runner、WebSocket、外部 lease/result storage；未执行 `pytest`/UI 测试，因此调度时延、真实锁竞争、取消时序、双 dialect 和残留资源仍标“待核”。 |

**后续裁决：** 吸收 Prefect 的 Flow/Task 分层、状态类型与终态闭包、服务端编排、schedule→scheduled run→queue→Worker/Runner、重试/退避、租约/事务、取消权单一归属和时间驱动补偿；升级平台时必须复用一个 `AttemptCoordinator`/取消协调/资源台账边界，隔离 WorkPool provider、Cloud-only 自动化、旧 Runner 兼容路径和客户端/服务端平行 schema。后续只维护本 `ARCHITECTURE.md`，不得把 `细探-prefect.md` 继续作为并行架构事实源。

## 15. 源码复核补充：Flow/Task、队列、心跳与恢复闭环

本节针对旧细探中仍容易误读的执行细节，按当前源码再次核对。它只补充本文件已有结论，不把配置默认值或测试文件存在误写成运行时保证。

### 15.1 Flow 与 Task 的真实执行边界

- `Flow.__init__` 当前默认实例化 `ThreadPoolTaskRunner()`；不能沿用旧细探的“SequentialTaskRunner 为 v3 默认”说法。当前 `task_runners.py` 的内置实现是 `ThreadPoolTaskRunner`、`ProcessPoolTaskRunner` 和分布式 `PrefectTaskRunner`，`ConcurrentTaskRunner` 只是 `ThreadPoolTaskRunner` 的兼容别名；Dask 不属于当前核心内置实现。
- `@flow` 的配置同时携带参数校验、Flow 级 retries/retry delay、timeout、结果持久化、serializer 和五类状态 hooks；Flow 引擎负责把用户函数生命周期转换成状态提议，但最终状态仍须经过服务端编排。
- `TaskRunner.submit()` 是非阻塞提交，返回 `PrefectFuture`；`map()` 会先解析可映射输入，要求至少一个 iterable 且所有 iterable 长度一致，再逐项创建 Future。Task runner 必须作为上下文管理器使用，退出时执行 `cancel_all()` 和 executor 清理。
- Task engine 的本地运行外圈仍包含依赖等待、取消事件检查、结果事务和 tag lease；这说明“Task 状态主要本地推进”不等于“Task 不需要服务端记录或服务端规则”，而是执行粒度和状态提议时机不同。

### 15.2 调度、队列领取与本地容量

调度队列的事实链是：

```text
active DeploymentSchedule
  → SchedulerService 计算并幂等写入 SCHEDULED FlowRun
  → WorkPool/WorkQueue 查询按服务端过滤、排序和数据库锁定返回
  → Worker 预取 scheduled_before 的运行
  → 本地 CapacityLimiter 取得提交令牌
  → Pending/Submitting → 基础设施启动 → FlowRunExecutor
```

- Server 数据库中的 scheduled run 才是队列事实；Worker 内的 `_submitting_flow_run_ids` 只是防止同一进程重复提交，不能作为恢复依据。
- `ScheduledRunPoller` 对计划时间排序后从 `LimitManager` 非阻塞取得令牌；容量耗尽即停止当前核对提交，已取得的令牌由单次 `_submit_run` 在 `finally` 中释放。它还会在启动前提议 `Pending`，使 Pending 事件和状态自动化语义保持一致。
- Runner 的 `query_seconds`、`prefetch_seconds` 和 Worker 的 query/prefetch/heartbeat 都来自 settings 或构造参数；文档可以记录机制，不能把旧细探的 5 秒、10 秒、30 秒等快照当成所有部署的公共契约。
- Worker 的 `sync_with_backend()` 同时负责 WorkPool/Worker 元数据同步和心跳；计划运行查询仍走 API。Worker 的取消观察采用实时事件加轮询兜底，且直接取消只适用于基础设施尚未真正启动的 FlowRun。

### 15.3 存储、代码拉取与结果引用

- Runner storage 的协议职责是设置本地基路径、声明 `pull_interval`、提供目的地、执行 `pull_code()` 和生成 deployment pull step。`ScheduledRunPoller` 对有周期的 storage 启动独立的 critical service loop；单次 storage 只在启动前拉取一次。
- Git storage 同时支持 branch 或 commit SHA（二者互斥）、稀疏目录、子模块和凭据块；凭据格式化属于 provider/block 边界，不能把认证信息写入普通日志或持久化的运行状态。
- 代码存储与结果存储是两条不同链：storage 拉取的是可执行代码，`ResultStore`/block storage 保存结果；State 的 `data` 在持久化场景只应携带 `ResultRecordMetadata` 等引用，不应把大结果或连接凭据塞进状态表。
- 结果写入必须遵守 `Transaction` 的 stage/commit/rollback 顺序。代码拉取失败、结果读取暂时失败、结果半提交和用户函数失败分别记录，不能统一伪装成“Flow failed”而丢失恢复依据。

### 15.4 心跳、队列与资源上限

- Flow heartbeat、Worker heartbeat、lease renewal 和事件 checkpoint 都是独立的时间驱动循环；它们不能互相替代。低流量事件仍须按 `checkpoint_interval` 检查，不能只在累计事件数达到 `checkpoint_every` 时确认。
- `EventsWorker`、日志 worker、进程池消息队列和内部 QueueService 都是异步边界；遥测或日志队列拥塞可以丢弃/降级并记录，但不能阻断已经完成的主状态提交。主执行、状态事实和 telemetry 必须分离。
- ThreadPool/ProcessPool 的 `cancel_all()` 只能可靠取消尚未开始的 Future；运行中的线程阻塞 I/O 不能被 Python 强杀。ProcessPool 还需要处理跨进程日志消息队列的关闭、`close()` 和 `join_thread()`，否则资源泄漏会被误判为业务失败。
- 本地 `CapacityLimiter`、服务端 WorkPool/WorkQueue limit、deployment concurrency、task tag lease 是不同粒度的资源闸门。任一层拒绝都应进入等待/重试语义，而不是把“本地没有令牌”写成用户函数失败。

### 15.5 失败恢复的最小证据闭包

每次失败、取消、重试或宿主退出都至少需要能够读回以下事实：`flow_run/task_run` 的当前状态及 attempt/run count、下一次 scheduled time、基础设施 PID/句柄或容器标识、lease/limiter 是否释放、事务是否 committed/rolled back、结果引用是否可读、临时工作区是否清理、最后一次 heartbeat 和事件 checkpoint。只保留日志文本不足以完成恢复判定。

| 故障 | 不可直接推出的结论 | 必须执行的恢复动作 |
|---|---|---|
| Worker 心跳消失 | 不能推出用户代码已失败或已停止 | Foreman/服务端按过期心跳标记 Worker，不依赖内存提交集合；由 Repossessor/基础设施清理继续处理孤儿运行 |
| Runner/宿主退出 | 不能用客户端最后一条日志代替终态 | 读取服务端状态、PID/容器和 lease；补齐 `CANCELLING`、过期 lease 和孤儿基础设施 |
| 线程超时 | 不能推出线程已经终止 | 标记超时风险，阻止无证据的重复执行；只有进程边界或 provider kill 回执才能确认停止 |
| 取消请求断线 | 不能把已发出的取消意图当成已取消 | 控制通道/事件优先，API 轮询兜底；由 CancellationCleanup 或 finalizer 收口 `CANCELLING` |
| 结果存储失败 | 不能把“函数执行成功”当成“运行结果已提交” | 保留 stage/commit/rollback 证据；状态只能引用已确认可读的结果元数据 |

**最终复核结论：** Prefect 的可复用核心不是某个 Worker 或某个队列实现，而是“声明式 Flow/Task → 服务端计划与状态裁决 → 有界领取/执行 → attempt 外圈 → 时间驱动补偿”的闭环。平台吸收时应共享一套状态、attempt、租约、事务、取消和资源台账；只把代码拉取、进程/容器启动、结果存储和事件传输作为受边界约束的适配器替换点。

## 16. 深度源码研究记录：事实、测试与未验证运行行为

本节是当前核对研究的证据索引。标记为“源码”只表示当前磁盘代码路径已读取；标记为“测试”只表示仓库中存在针对性测试并已阅读断言；标记为“运行”才表示当前核对实际启动了组件并读回结果。当前核对没有 Prefect 动态运行，因此本节不把测试源码或测试命令当作运行绿灯。

### 16.1 Flow/Task/Runner/Future/map/cancel

| 主题 | 当前源码事实 | 测试证据 | 当前核对运行证据 |
|---|---|---|---|
| Flow 默认执行器 | `Flow.__init__` 默认创建 `ThreadPoolTaskRunner`；`ConcurrentTaskRunner` 是兼容别名，不是另一种独立实现；当前核心还有 `ProcessPoolTaskRunner` 和 `PrefectTaskRunner` | `tests/test_task_runners.py` 覆盖线程池、进程池、异步任务、上下文传播和嵌套提交 | 未运行；线程/进程数量和退出时资源未读回 |
| submit/map | `Task.submit()` 依赖当前 `FlowRunContext`，提交后立即返回 Future；`TaskRunner.map()` 先解析 Future 输入、物化 iterable、校验所有可映射长度相同，再逐项 submit；映射提交本身可能阻塞等待上游 Future | `tests/test_task_runners.py` 覆盖 map、Future 解析、长度和上下文；`tests/test_background_tasks.py` 覆盖 deferred map | 未运行；大 iterable 的内存峰值未测 |
| Future wait/result | 线程/进程 Future 读取底层 future；分布式 Future 先读 API，再由 `TaskRunWaiter` 等最终事件，之后重新读状态以抵抗事件竞态；FlowRunFuture 在 waiter 返回后持续读 API，直到读到终态或超时 | `tests/test_futures.py` 覆盖并发 wait、超时、as_completed、事件竞态和暂停检查 | 未运行；真实 WebSocket 丢事件/重连未测 |
| cancel | `PrefectConcurrentFuture.cancel()` 委托 `concurrent.futures.Future.cancel()`，只能取消尚未开始的底层工作；TaskRunner `cancel_all()` 另设置每个 task 的 `threading.Event`，Task engine 只在检查点抛出取消异常；运行中的线程阻塞 I/O 不会被强杀 | `tests/test_task_runners.py`、`tests/test_futures.py` 有 future 和 runner 收口/超时断言 | 未运行；不能声称取消已停止用户线程 |
| Task 状态边界 | Task engine 在本地推进状态、事务和事件，但创建/读取/状态服务端记录仍经过 client；Flow engine 的 Running/终态提议走服务端编排 | `tests/test_task_engine.py`、`tests/test_flow_engine.py`、`tests/server/orchestration/test_core_policy.py` | 未运行；未读回 API 状态历史和 run count |

### 16.2 调度、FlowRun、WorkPool/WorkQueue、Worker/Runner

- **调度器是数据库计划生成器，不是执行器。** `SchedulerService` 对 deployment 做游标分页，按 active schedule 计算未来运行并批量插入；最近变更 deployment 有单独快速扫描。重复扫描是设计允许的，插入路径必须幂等。源码证据：`server/services/scheduler.py`；测试证据：`tests/server/services/test_scheduler.py`。当前核对未启动服务，未测时间精度、并发调度器和 SQLite/PostgreSQL 差异。
- **队列事实在数据库。** WorkPool/WorkQueue 查询过滤 `SCHEDULED`、暂停状态、`scheduled_before`、队列/池容量，并可按队列优先级排序。队列优先级是数值越小越优先，源码模型明确 `1` 为最高优先级；它不是全局 FlowRun 优先级，也不改变 deployment/task/tag 的其他容量闸门。源码证据：`server/models/work_queues.py`、队列 SQL/query components、`client/schemas/objects.py`。
- **领取顺序不是任意 FIFO。** 普通工作池路径由服务端排序和数据库查询决定；新 Runner 再按 `next_scheduled_start_time` 排序，并在本地 `LimitManager` 无令牌时停止当前核对提交。Worker 的 `_submitting_flow_run_ids` 仅是进程内去重集合，进程退出即丢失，不能用于恢复或证明租约。
- **Worker 与 Runner 的断线策略不同但目标一致。** Worker channel 有 `CONNECTING/HEALTHY/FALLBACK_RETRYING/DISABLED` 状态；健康 WebSocket 不可用时 REST fallback 仍启用，快照以 `snapshot_sequence` 拒绝旧序列；Worker 取消观察则是事件订阅失败后切轮询。测试证据：`tests/test_observers.py`、`tests/server/utilities/test_worker_channel.py`、`tests/client/schemas/test_worker_channel.py`。当前核对未模拟真实断线、重复 frame 或服务端重启。
- **Runner 的单次执行闭包明确。** `ScheduledRunPoller` 取得 limiter token 后创建一次 `FlowRunExecutor`；executor 先检查 Cancelling/Cancelled，再提议 Submitting，启动器先通过 `task_status.started(handle)` 暴露句柄，进程退出后读取 attempt conclusion，再移除 ProcessManager 注册，最后按退出码决定是否提议 Crashed。token 在 poller 的 `finally` 释放。源码证据：`runner/_scheduled_run_poller.py`、`runner/_flow_run_executor.py`；测试证据：`tests/runner/test__flow_run_executor.py`、`tests/runner/test_runner.py`。

### 16.3 重试、锁、租约、心跳与结果失败

1. **重试不是一次状态覆盖。** Task 的 `retry_condition_fn` 异常按“不重试”处理；延迟可为数值、列表或 callable，列表最后一个值可复用，最多配置 50 个延迟；每次 retry 从 `Retrying`/`AwaitingRetry` 再进入运行。Flow 的 retry policy 写入 FlowRun policy，服务端规则 `RetryFailedFlows` 决定是否接受下一轮。测试证据：`tests/test_task_engine.py`、`tests/public/tasks/test_task_timeouts.py`、`tests/public/flows/test_flow_timeouts.py`；当前核对未运行，未确认实际 run count 和 scheduled time。
2. **结果写入不是跨对象原子事务。** `ResultStore` 无 metadata storage 时把 ResultRecord 一次写入；配置 metadata storage 时先写 result，再写 metadata，是两个独立 block I/O。`Transaction.commit()` 捕获序列化/存储异常后调用 rollback 并释放 SERIALIZABLE lock，但已经成功写入的外部对象不会由该代码自动做分布式删除。因此“函数成功”不等价于“远端结果可读”，结果引用必须在读回确认后才可作为完成事实。源码证据：`results.py:1067-1129`、`transactions.py:335-391`；测试证据：`tests/results/test_result_store.py`、`tests/test_transactions.py`；当前核对未对半写、远端断线或重试读回做运行实验。
3. **锁是可选能力。** `READ_COMMITTED` 不要求 lock manager；`SERIALIZABLE` 没有 lock manager 会配置失败。事务在 begin 获取锁，在 commit 或 rollback 的 finally 路径释放；commit 失败会回滚，但 hook 或外部存储自身的副作用不具备通用补偿。测试证据：`tests/test_transactions.py`、`tests/test_locking.py`、`tests/results/test_result_store.py`。
4. **租约失效有明确的保守/宽松分叉。** 续约线程在 lease duration 的 0.75 处续约，每次最多 3 次指数退避；`raise_on_lease_renewal_failure=True` 取消执行，默认值只告警并允许继续，此时 active slot 可能暂时被超额使用。服务端 `Repossessor` 扫描过期 lease，按 lease metadata 扣回 active slots 并撤销 lease。测试证据：`tests/concurrency/test_leases.py`、`tests/concurrency/test_raise_on_lease_renewal_failure.py`、`tests/server/concurrency/test_memory_lease_storage.py`；当前核对未运行，未读回 active slots 为零。
5. **心跳是观测，不是租约。** Flow heartbeat 使用 daemon thread，最小间隔由源码钳制为 30 秒；它在检测到终态后停止，发送异常只 debug 记录。Worker heartbeat 更新 worker/backend 健康；Foreman 根据过期 heartbeat 标记 Worker offline，并进一步标记没有在线 Worker 的 Pool、长期未 poll 的 deployment/queue 为 not ready。心跳事件不自动延长 concurrency lease，也不证明用户进程存活。测试证据：`tests/server/services/test_foreman.py`、`tests/test_observers.py`；当前核对未运行。

### 16.4 取消、孤儿 run、恢复和释放

- Runner 取消的真实顺序是 control-channel intent → 平台 kill → cancellation hooks → `Cancelled` 状态提议 → cancelled event。POSIX 收到 ack 后仍会继续实际 kill；Windows 有有限 graceful window。control channel 不可用时不是自动判定“已取消”，而是记录异常并走强制 kill；kill 发生非预期异常时，代码会中止后续 hooks/state 收口，留下由服务端 cleanup/finalizer 处理的风险窗口。
- `CancellationCleanup` 为 `CANCELLING` 安排带 run/state id 的超时任务，并用行锁复核当前状态；超时后把仍未收口的 FlowRun 标为 `Cancelled`，同时向 Worker cleanup queue 投递清理消息。它不是对已消失进程的直接证明，而是状态侧补偿。
- `Foreman` 只改变健康状态，`Repossessor` 只回收过期 concurrency lease；二者都不会凭空知道用户代码是否已停止。孤儿 FlowRun 的安全恢复必须联合读取状态、heartbeat、基础设施句柄/PID、lease 和 cleanup queue，而不能看到 Worker offline 就直接重跑。
- 资源释放依赖多层 `finally`：TaskRunner 关闭 executor，Task engine 退出 concurrency context，Runner poller 释放 limiter token，FlowRunExecutor 移除 ProcessManager handle，Worker 清理 zip/bundle 临时目录，EventsWorker 删除被丢弃事件的 context cache。任一层外部 provider 不响应，都可能留下需要扫描的资源；源码中没有跨 provider 的全局事务。
- 测试源码覆盖取消清理、observer 的 WebSocket→polling fallback、worker cleanup、runner cancellation、repossessor 和 lease storage：`tests/server/services/test_cancellation_cleanup.py`、`tests/test_observers.py`、`tests/workers/test_cleanup.py`、`tests/runner/test__cancellation_manager.py`、`tests/server/services/test_repossessor.py`。当前核对没有真实进程、容器、数据库、WebSocket 或 provider，因此所有“孤儿已回收”“PID 已消失”“lease 已归零”均未验证。

### 16.5 研究结论与边界

静态代码足以确认：状态机有终态闭包和按优先级排列的编排规则；重试由客户端策略与服务端裁决共同完成；队列是数据库事实而非内存 FIFO；取消是有 owner 的多阶段序列；租约和临时资源有过期/`finally` 补偿；事件与 heartbeat 是观测通道而非主状态事实。测试源码足以确认：项目主动覆盖了 map/future 超时、嵌套线程池死锁警告、重试、事务回滚、租约续约失败、取消 observer fallback、scheduler 和 cleanup。

当前核对不能确认：真实部署下的调度延迟和优先级公平性、数据库锁竞争、结果双写断线后的残留对象、Worker channel 重连期间的重复领取、真实 SIGTERM/SIGKILL 时序、容器/PID 清理、孤儿 run 是否被安全重排、以及资源释放最终是否归零。唯一实际执行的验证是文档级 `git diff --check`；未执行 pytest、服务启动或外部系统联调。
