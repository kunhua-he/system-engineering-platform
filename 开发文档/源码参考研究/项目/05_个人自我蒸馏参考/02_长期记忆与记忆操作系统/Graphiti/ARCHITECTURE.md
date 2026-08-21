# Graphiti 架构与源码审计

> 分析对象：本地 Graphiti 源码快照
> 源码版本：`graphiti-core` `0.29.3`（根 `pyproject.toml`）
> 源码提交：`993e081a6d7948a0d8851c12a5fbdbeb49fed862`（`fix(attributes): preserve prior node attributes when no entity type applies`，2026-08-13）
> 许可证：Apache-2.0
> 证据等级：本文是本地源码、测试源码、配置和文档审计，不是服务运行报告。

## 1. 研究边界与证据

当前核对只研究本地目录，未启动 Neo4j、FalkorDB、REST 或 MCP，未执行 LLM、embedding 或 cross-encoder。平台 MCP 仅用于本任务开工上下文和代码地图，不作为 Graphiti 的运行证据。

目标仓库当前存在未跟踪的 `.codegraph/` 目录，但它不是该源码提交中的受版本控制证据；本次结论仍以受版本控制的源码、测试和配置为准，不把该临时索引当作版本事实。

当前核对实际读取范围包括：

- 根 `README.md`、`AGENTS.md`、`pyproject.toml`、`pytest.ini`、`Makefile`、`docker-compose*.yml`、`.env.example`。
- `graphiti_core/graphiti.py`、`nodes.py`、`edges.py`、`graphiti_types.py`、`search/`、`utils/maintenance/`、`utils/content_chunking.py`、`llm_client/`、`driver/`、`namespaces/`。
- `server/graph_service/`、`server/README.md`、`server/pyproject.toml`。
- `mcp_server/src/`、`mcp_server/README.md`、配置文件、Docker 文件和 `mcp_server/tests/`。
- 核心 `tests/`、REST live 测试、MCP 集成/异步/压力/transport/parity 测试，以及既有 `细探-Graphiti.md`。

测试源码的存在不等于测试通过。此前文档记录的 pytest 尝试因环境中无法生成 `pytest` 命令退出码 2；当前核对没有重跑测试，只执行了最终 `git diff --check`。

## 2. 分层与入口

```text
Python SDK: graphiti_core.Graphiti
REST: server/graph_service/main.py -> routers -> ZepGraphiti(Graphiti)
MCP: mcp_server/main.py -> src/graphiti_mcp_server.py -> FastMCP tools
                         |
                         v
Graphiti 编排：add_episode / add_episode_bulk / add_triplet / search / search_
                         |
抽取、解析、去重、时间失效、embedding、社区和 Saga
                         |
领域模型：Episodic / Entity / Community / Saga nodes
          Entity / Episodic / Community / Saga edges
                         |
GraphDriver：Neo4j / FalkorDB / Neptune / Kuzu provider
```

`graphiti_core/__init__.py` 的公开核心入口是 `Graphiti`。`Graphiti` 组合 driver、LLM、embedder、cross-encoder 和 tracer，并创建节点/边 namespace。模型类目前仍同时承担 Pydantic 数据结构和兼容期数据库操作；operations/namespace 新接口与旧 `GraphOperationsInterface`、`SearchInterface` fallback 并存，`spec/driver-operations-redesign.md` 仍是 Draft，不能当作完成态架构。

REST 和 MCP 都是适配层，不是第二个记忆内核。REST 负责 DTO、HTTP 路由和异步 worker；MCP 负责配置、provider factory、FastMCP 工具和按 group 排队；主要记忆语义仍由 `Graphiti` 执行。

### 2.1 一次写入的真实调用链（源码边界）

```text
SDK Graphiti.add_episode / MCP QueueService.add_episode / REST POST /messages
  -> Graphiti.add_episode（group_id 可能触发 driver.with_database/clone）
  -> retrieve_episodes + extract_nodes（LLM）
  -> resolve_extracted_nodes（名称/候选/LLM 去重，生成 UUID map）
  -> extract_edges + resolve_extracted_edges（时间字段、重复/矛盾失效）
  -> _process_episode_data
       -> EpisodicNode、EntityNode、EntityEdge、MENTIONS/episode provenance
       -> 可选 Saga 关系与 update_communities
  -> AddEpisodeResults（SDK）；REST/MCP 入队入口只报告接收/队列位置
```

这条链来自 `graphiti_core/graphiti.py:add_episode`、`mcp_server/src/services/queue_service.py:24-80,101-184` 和 `server/graph_service/routers/ingest.py:13-70`。REST/MCP 的 `202/queued` 不是写入提交确认，也没有可查询的 job 状态。

## 3. `add_episode` 与写入语义

### 3.1 单 episode 流程

`Graphiti.add_episode`（`graphiti_core/graphiti.py:980`）的源码顺序是：

1. 校验 entity types、excluded types 和 `group_id`。
2. `group_id` 与当前 driver database 不同则调用 `clone(database=group_id)`，并替换实例上的 `self.driver` 与 `self.clients.driver`。
3. 按 `reference_time` 读取最多 `RELEVANT_SCHEMA_LIMIT` 个上下文 episode；显式 `previous_episode_uuids` 会替代自动窗口。
4. 创建或按 UUID 读取 `EpisodicNode`，其 `created_at` 使用当前 `utc_now()`，`valid_at` 使用调用方 `reference_time`。
5. `extract_nodes` 调 LLM 结构化抽取实体；`resolve_extracted_nodes` 用确定性名称/候选和必要的 LLM 去重解析 canonical node 与 UUID map。
6. `extract_edges` 按已抽取节点白名单抽取事实和时间字段，拒绝未知端点和自环；`resolve_extracted_edges` 做同端点候选、全文/向量候选、duplicate/contradiction 判断。
7. 对矛盾事实保留旧边，并按事件时间更新 `invalid_at`，必要时记录 `expired_at`；重复事实不重复写入。
8. `extract_attributes_from_nodes` 只使用 `new_edges` 更新实体属性和摘要。
9. `_process_episode_data` 生成 `MENTIONS`，批量保存 episode、entity、entity edge 和 embeddings，并可建立 Saga 关系。
10. `update_communities=True` 时在主事实保存后更新社区，最后返回 `AddEpisodeResults`。

LLM、候选读取、embedding、属性摘要和最终保存跨越多个阶段。高层 `add_episode` 没有包在一个 `GraphDriver.transaction()` 中，因此不能宣称全流程原子；异常只记录 tracer span 后重新抛出。

### 3.2 bulk 与 triplet

`add_episode_bulk` 不是单 episode 循环：它先预写 episode，再批量上下文读取、抽取、内存去重、UUID 重映射和实体/边保存，Saga 关系在后续阶段建立。中途失败没有源码级 request journal、幂等提交记录或补偿删除，可能留下部分结果。

`add_triplet` 绕过 episode 抽取，直接解析 source/target entity 和 EntityEdge，生成 embeddings，执行事实 duplicate/contradiction resolution 后写入。它不会自动创建 episode provenance；来源依赖调用方传入的 `edge.episodes`。

### 3.3 并发与 group

`SEMAPHORE_LIMIT` 在 `graphiti_core/helpers.py:38` 默认是 20，核心 `Graphiti.__init__` 允许实例级 `max_coroutines` 覆盖；MCP `graphiti_mcp_server.py:94` 和 Docker compose 默认是 10。README 的服务说明也是 10。三者不是同一配置，不能互相外推。

`semaphore_gather` 只是并发上限，不是事务锁、幂等锁或 group 锁。源码要求同 group episode 顺序 await；SDK 核心本身没有通用 group 锁。由于 group 路由会修改共享 Graphiti 实例的 driver 引用，同一实例跨 group 并发存在共享可变状态风险。MCP 的按 group worker 可以降低该风险，但 REST/SDK 复用实例时不能假定安全。

## 4. 时间语义、实体关系与 provenance

### 4.1 时间字段

| 字段 | 源码语义 |
|---|---|
| `EpisodicNode.valid_at` | episode 的事件/参考时间，来自 `reference_time`，用于上下文窗口 `valid_at <= reference_time`。 |
| `EntityEdge.valid_at` | 事实开始有效的事件时间，由事实抽取和解析产生。 |
| `EntityEdge.invalid_at` | 事实停止有效的事件时间；矛盾失效保留旧边并设置此字段。 |
| `EntityEdge.expired_at` | 系统发现或处理旧事实失效的墙钟时间。 |
| `reference_time` | episode 输入参考时间，并保留到 EntityEdge；不是独立知识时间轴。 |
| `created_at` | 对象构造/写入时间；不是事件有效时间。 |
| Saga 水印 | `last_summarized_at` 是摘要处理墙钟水印；`last_summarized_episode_valid_at` 是已纳入摘要的最大 episode 事件时间。 |

源码没有 `known_at` 字段、赋值、索引、查询过滤、返回 DTO 或 as-of knowledge-time API。README/注释中的 “bi-temporal” 不能解释为已实现 `valid_at/known_at` 双时态。跨 provider 的时区、无时区输入、DST、回填和并发时间一致性没有 live 证据。

### 4.2 节点、边和来源

`EpisodicNode` 是原始输入与派生事实的 provenance 锚点；`EntityNode` 保存名称 embedding、摘要、属性和自定义 labels；`CommunityNode` 连接实体簇；`SagaNode` 维护 episode 序列和摘要。

`EntityEdge.episodes` 保存来源 episode UUID 列表；`EpisodicEdge` 是 `MENTIONS`；`CommunityEdge` 是 `HAS_MEMBER`；Saga 使用 `HAS_EPISODE` 与 `NEXT_EPISODE`。节点归一化使用确定性候选和 LLM 兜底；重复 entity 关系还存在持久化去重检查，不能简化成只有内存 UUID map。

## 5. 检索与删除

### 5.1 检索

`Graphiti.search` 选择 edge hybrid recipe，返回 `list[EntityEdge]`；`search_` 才返回含 edge、node、episode、community 的 `SearchResults`。检索编排根据 `SearchConfig` 并发执行 fulltext/BM25、cosine 和 BFS，再做 RRF、MMR、cross-encoder、node-distance 或 episode-mentions 排序。

`SearchFilters` 支持 group、labels、edge types、UUID 及 `created_at`、`valid_at`、`invalid_at`、`expired_at` 日期条件。值使用参数化查询；label 等查询片段经过校验。索引未就绪、provider 查询失败或部分 scope 失败时没有统一的 partial-result 契约。搜索结果保留事件时间和 provenance，但不是知识时间快照。

### 5.2 删除路径不等价

| 入口 | 源码行为 | 边界 |
|---|---|---|
| `Graphiti.remove_episode` | 删除 episode 来源边、仅被该 episode 提及的孤儿实体，最后删除 episode。 | 只选择 `edge.episodes[0] == episode.uuid`；不重写共享 edge 来源列表，不显式修复 Saga、社区、摘要、索引或缓存。 |
| REST `DELETE /episode/{uuid}` | `ZepGraphiti.delete_episodic_node` 直接删除 episode。 | 不执行 `remove_episode` 的来源边和孤儿实体判断；依赖节点删除的 detach 行为。 |
| REST `DELETE /entity-edge/{uuid}` | 直接删除 EntityEdge。 | 不重算 episode 来源、社区或摘要。 |
| REST `DELETE /group/{group_id}` | 分别读取并逐对象删除 edge、node、episode。 | 多次独立请求，不是统一事务；Saga/Community 不在同一明确策略内。 |
| `clear_data` | 按 provider/group 清除图数据；REST `/clear` 随后重建索引。 | provider 查询不同，删除和重建不是一个统一跨 provider 事务。 |

事实矛盾失效、按来源撤销、物理删除和清空命名空间是四种不同语义。当前没有统一软删除、删除墓碑、来源引用重写、投影对账或删除幂等协议。

## 6. Neo4j、FalkorDB、资源与失败

`GraphDriver.transaction()` 基类只是 session 即时执行包装；Neo4j override 使用 async session 和 `begin_transaction()`，正常退出 commit，任何 `BaseException` rollback。只有显式调用该 API 的范围具有此保证；高层 `add_episode` 没有统一使用它。

Neo4j `close()` 会取消/消费索引初始化 task 后关闭 client。批量写阶段另行取得 session，并在 finally 关闭。FalkorDB session `close`/`__aexit__` 是 no-op，`execute_write` 直接调用函数，日期转 ISO 字符串后直接向选定 graph 查询；其 clone 复用同一 client，不能套用 Neo4j rollback 语义。基类 `with_database` 也是浅拷贝。clone 没有独立连接、引用计数或所有权协议，关闭共享 client 存在生命周期风险。

`Graphiti.close()` 只关闭 driver，不统一关闭 LLM、embedder、cross-encoder、缓存或 REST/MCP 队列。Neo4j `execute_query` 的错误日志包含 query 和 params，敏感数据治理需由部署另行约束。

局部失败恢复只有：LLM 对指定瞬时错误有限重试，Neo4j 显式事务局部 rollback，`asyncio` cancellation 沿当前 await 链传播。源码没有跨阶段补偿、提交确认、重启扫描半成品或重复请求回读机制。

## 7. REST/MCP 队列与生命周期

### REST

`server/graph_service/routers/ingest.py` 的 `AsyncWorker` 是一个全局无界 `asyncio.Queue` 和一个 worker。`POST /messages` 逐消息入队后立即返回 202，没有 job id、持久化、重试、死信、结果查询、幂等键、容量上限或 `task_done`。普通 job 异常没有在 worker 内隔离，可能使 worker 终止；shutdown 取消 worker 并清空剩余队列。

更重要的是，`get_graphiti` 是 request-scoped dependency，响应后 finally 会关闭 client；`/messages` 把引用该 client 的闭包放入全局 worker。源码没有证明后台执行一定早于 dependency close，需真实 FastAPI lifespan 测试，不能写成安全保证。

### MCP

`QueueService`（`mcp_server/src/services/queue_service.py:12-80`）为每个 group 保存进程内无界 `asyncio.Queue`，一次处理一个 episode，同 group 顺序执行，不同 group 可并行。异常被记录并吞掉，调用方只收到 queued 位置，不会得到实际结果或失败状态；`add_episode_task` 的“检查 worker 后 `create_task`、worker 再置位”窗口允许并发提交创建重复 worker。

QueueService 没有容量背压、超时、重试、持久化、死信、drain、stop 或恢复 API。MCP 初始化全局 Graphiti client 和 QueueService，但 QueueService 本身没有统一 shutdown；重启没有恢复队列或扫描未完成写入。

当前 MCP 注册工具包含 `add_memory`、`search_nodes`、`search_memory_facts`、`delete_episode`、`delete_entity_edge`、`get_entity_edge`、`get_episodes`、`summarize_saga`、`build_communities`、`add_triplet`、`get_episode_entities`、`clear_graph`、`get_status`。多份旧 MCP 测试仍调用 `search_memory_nodes`，构成静态工具名漂移；不能把这些测试当作当前注册表的有效绿门禁。

生产化若需要可靠任务，必须另行设计有界队列、job/request id、幂等键、持久状态、attempt/lease、deadline、取消状态、重试/死信、优雅排空和启动恢复，并区分 `queued`、`running`、`committed`、`failed`、`cancelled`、`unknown/needs-reconcile`。这些是新增运行治理，不是 Graphiti 当前能力。

## 8. 配置、provider 与测试覆盖

根库要求 Python `>=3.10,<4`，核心依赖 Pydantic、Neo4j、OpenAI、Tenacity、NumPy、dotenv、PostHog；FalkorDB、Neptune、Kuzu、其他 LLM/embedder/reranker 和 tracing 由 extras 提供。README 标记 Kuzu deprecated。MCP 自己有独立 `pyproject.toml`、YAML/env/CLI 配置与 provider factory；其 CLI 只暴露 Neo4j/FalkorDB，不能把核心 driver 列表当作 MCP 可选项。

测试覆盖层次如下：

- 安全、查询构造、Pydantic 和部分 driver 路由有 mock/unit 测试。
- `tests/test_graphiti_mock.py` 名称含 mock，但 fixture 可按环境创建真实图 driver；不能仅凭名称判断无外部依赖。
- `*_int.py`、REST live FalkorDB 和 MCP integration/transport/stress 测试需要数据库、API key 或服务进程。
- MCP 异步测试覆盖顺序、跨 group 并发、快速入队、超时和 cancellation 场景源码，但大量依赖 sleep/时间阈值，未证明 durable recovery、容量边界或重启恢复。
- `tests/test_add_triplet.py` 的 mock embedder/`create_batch` 既有不稳定记录；不能宣称 add_triplet 端到端通过。

静态导入、健康端点、HTTP 202、MCP queued、mock LLM、测试文件存在和 driver ABC 都不能证明数据库连接、索引、真实模型返回、事务、资源释放或跨 provider 等价。

## 9. 唯一审计结论与待核项

Graphiti 当前可作为“事件时间 + episode provenance + 增量实体/事实图 + 混合检索”的源码参考。它不能被描述为已经具备 `valid_at/known_at` 双时态、全流程原子写入、统一删除恢复、可靠异步任务、重启恢复或跨 provider 一致事务的生产控制面。

待核项保持明确：真实 provider 的中途失败残留、同 UUID 重试、跨 group 并发串库、FalkorDB 同连接并发与 clone close、删除后 provenance/Saga/Community/索引对账、REST dependency 与 worker 生命周期、MCP 重复 worker/关闭/取消/重启，以及 Neptune/Kuzu/FalkorDB 的 live 查询和时间行为。

本文件是本地研究的唯一架构收口入口；`细探-Graphiti.md` 保留为历史细探，不作为第二个权威架构文档。当前核对只修改根 `ARCHITECTURE.md`。

## 10. 研究材料吸收记录

已人工回读并吸收 `细探-Graphiti.md` 中的增量事实：episode 增量摄取与实体/边去重、`valid_at/invalid_at/expired_at` 的实际字段边界、四类检索 scope 的 RRF/MMR/cross-encoder 组合、Saga/Community 关系、Neo4j 与 FalkorDB 事务差异、REST/MCP 队列生命周期以及删除路径不等价。旧材料未提供可替代的运行验证；相关结论仍按本文的 L0/L1 静态证据和待核项处理。

## 11. 全量目录与源码文件导航

本节把当前 checkout 的可审计源码边界固定下来。目录清单来自源码仓库提交 `993e081a6d7948a0d8851c12a5fbdbeb49fed862`；源码仓库中的未跟踪 `.codegraph/` 与根 `ARCHITECTURE.md` 不计入发布包事实。

### 11.1 核心包

| 路径 | 职责 | 关键入口 |
|---|---|---|
| `graphiti_core/graphiti.py` | 编排、写入、检索、删除、Saga、社区 | `Graphiti` |
| `graphiti_core/nodes.py` | Episode/Entity/Community/Saga 节点模型和持久化 | `Node`、`EpisodicNode`、`EntityNode`、`CommunityNode`、`SagaNode` |
| `graphiti_core/edges.py` | MENTIONS、事实、社区、Saga 边模型 | `EpisodicEdge`、`EntityEdge`、`CommunityEdge`、`HasEpisodeEdge`、`NextEpisodeEdge` |
| `graphiti_core/graphiti_types.py` | 抽取结果、搜索返回、运行类型 | `EntityType`、结果模型 |
| `graphiti_core/driver/` | provider 抽象、session、查询和新 operations 接口 | `GraphDriver`、`GraphProvider` |
| `graphiti_core/search/` | 混合检索、过滤、排序和配置 recipe | `search`、`SearchConfig`、`SearchFilters` |
| `graphiti_core/llm_client/` | LLM provider、结构化输出、缓存、token 追踪 | `LLMClient` 家族 |
| `graphiti_core/embedder/` | embedding provider | `EmbedderClient` 家族 |
| `graphiti_core/cross_encoder/` | reranker provider | `CrossEncoderClient` 家族 |
| `graphiti_core/prompts/` | 节点、边、去重、摘要提示词 | `extract_*`、`dedupe_*` |
| `graphiti_core/namespaces/` | 节点/边操作门面 | `NodeNamespace`、`EdgeNamespace` |
| `graphiti_core/utils/` | 批处理、文本、时间和维护脚本 | `semaphore_gather`、`clear_data` |
| `graphiti_core/tracer.py`、`telemetry/` | span、token 和匿名初始化遥测 | `Tracer`、telemetry helpers |

### 11.2 服务与部署目录

| 路径 | 事实 |
|---|---|
| `server/graph_service/main.py` | FastAPI lifespan、健康端点和 router 挂载 |
| `server/graph_service/routers/ingest.py` | 消息入队、实体写入、删除、清空 |
| `server/graph_service/routers/retrieve.py` | search、entity edge、episodes、memory |
| `server/graph_service/zep_graphiti.py` | REST DTO 到 `Graphiti` 的适配和依赖注入 |
| `mcp_server/src/graphiti_mcp_server.py` | FastMCP 工具注册、配置、服务初始化和 health |
| `mcp_server/src/services/queue_service.py` | group 级进程内 episode 队列 |
| `mcp_server/src/services/factories.py` | driver、LLM、embedder、reranker 工厂 |
| `mcp_server/config/` | YAML、stdio、Docker 配置 |
| `docker-compose*.yml`、`mcp_server/docker/` | provider 和 MCP 部署编排 |

### 11.3 测试和契约目录

| 路径 | 内容 | 证据等级 |
|---|---|---|
| `tests/test_graphiti_mock.py` | 核心 Graphiti mock/fixture 场景 | 测试源码，非本次执行证据 |
| `tests/test_node_int.py`、`test_edge_int.py` | 节点/边 provider 集成 | 需要外部数据库或 fixture |
| `tests/test_add_triplet.py` | triplet 写入、embedding 和去重 | 含 mock，不能替代端到端 |
| `tests/test_edge_db_queries.py` | 查询构造和边数据库行为 | 静态/单元为主 |
| `mcp_server/tests/test_async_operations.py` | 顺序、并发、timeout、取消源码场景 | 时间阈值敏感 |
| `mcp_server/tests/test_mcp_transports.py` | stdio/HTTP transport | 需要服务依赖 |
| `mcp_server/tests/test_stress_load.py` | MCP 压力场景 | 未执行 |
| `server/tests/`、REST live tests | REST API 和 provider 行为 | 环境依赖 |

## 12. 公开 API、REST 与 MCP 工具表

### 12.1 Python SDK API

| API | 源码位置 | 语义 |
|---|---|---|
| `Graphiti.__init__` | `graphiti_core/graphiti.py:138-248` | 注入 driver、LLM、embedder、cross-encoder、并发上限和 tracer |
| `Graphiti.close` | `graphiti_core/graphiti.py:314-344` | 关闭 driver；不负责所有 provider/队列 |
| `build_indices_and_constraints` | `graphiti_core/graphiti.py:570-602` | 委托当前 driver 建索引/约束 |
| `add_episode` | `graphiti_core/graphiti.py:980-1228` | 抽取并保存 episode、节点、事实和 provenance |
| `add_episode_bulk` | `graphiti_core/graphiti.py:1230-1488` | 批量抽取、去重、保存和可选社区更新 |
| `add_triplet` | `graphiti_core/graphiti.py:1645-1763` | 直接写 source/target/entity edge，绕过 episode 抽取 |
| `search` | `graphiti_core/graphiti.py:1527-1586` | 返回 `list[EntityEdge]` 的基础混合检索 |
| `search_` | `graphiti_core/graphiti.py:1603-1629` | 返回完整 `SearchResults` 的高级检索 |
| `retrieve_episodes` | `graphiti_core/graphiti.py:927-978` | 按 group 和时间窗口读取上下文 episode |
| `build_communities` | `graphiti_core/graphiti.py:1490-1525` | 分批更新社区节点和成员关系 |
| `summarize_saga` | `graphiti_core/graphiti.py:438-568` | 读取 Saga episode 并生成摘要 |
| `remove_episode` | `graphiti_core/graphiti.py:1765-1794` | 按来源边和孤儿实体策略删除 episode |

### 12.2 REST 路由

| 方法和路径 | 源码位置 | 行为 |
|---|---|---|
| `GET /healthcheck` | `server/graph_service/main.py:27-30` | 进程健康，不验证 provider 写入 |
| `POST /messages` | `server/graph_service/routers/ingest.py:51-70` | 将消息闭包放入全局 worker，返回 202 |
| `POST /entity-node` | `ingest.py:73-84` | 同步保存实体节点 |
| `DELETE /entity-edge/{uuid}` | `ingest.py:87-90` | 直接删除事实边 |
| `DELETE /group/{group_id}` | `ingest.py:93-96` | 委托 group 删除 |
| `DELETE /episode/{uuid}` | `ingest.py:99-102` | 直接删除 episodic node |
| `POST /clear` | `ingest.py:105-111` | 清图后重建索引 |
| `POST /search` | `retrieve.py:17-27` | 调用 `graphiti.search` |
| `GET /entity-edge/{uuid}` | `retrieve.py:30-34` | 读取事实边 |
| `GET /episodes/{group_id}` | `retrieve.py:36-42` | 读取最近 episode |
| `POST /get-memory` | `retrieve.py:44-55` | 组合节点和边返回 memory |

### 12.3 MCP 工具

工具注册位置均为 `mcp_server/src/graphiti_mcp_server.py`：

| 工具 | 行号 | 结果边界 |
|---|---:|---|
| `add_memory` | 354-489 | 进入 QueueService，返回队列位置 |
| `search_nodes` | 491-566 | 节点检索 |
| `search_memory_facts` | 568-646 | 事实检索 |
| `delete_entity_edge` | 648-672 | 删除 EntityEdge |
| `delete_episode` | 674-701 | 删除 Episode |
| `get_entity_edge` | 703-729 | 读取 EntityEdge |
| `get_episodes` | 730-799 | 按 group 读取 episodes |
| `summarize_saga` | 800-852 | Saga 摘要 |
| `build_communities` | 853-906 | 社区构建 |
| `add_triplet` | 907-979 | 直接写三元组 |
| `get_episode_entities` | 981-1016 | episode 的实体关系 |
| `clear_graph` | 1017-1058 | 清图和索引 |
| `get_status` | 1060-1091 | 配置/服务状态 |

旧测试中的 `search_memory_nodes` 与当前注册名 `search_nodes` 不一致，属于工具名漂移，不能把旧测试通过解释为当前 MCP 合约通过。

## 13. 核心类型、字段和关系

### 13.1 节点字段

| 类型 | 位置 | 关键字段 | 生命周期 |
|---|---|---|---|
| `Node` | `nodes.py:93-317` | `uuid`、`name`、`group_id`、`labels`、`created_at` | 抽象基类，提供校验、删除、按 UUID/group 查询 |
| `EpisodicNode` | `nodes.py:318-498` | `content`、`source`、`source_description`、`valid_at`、`entity_edges` | 由 episode 写入，作为 provenance 锚点 |
| `EntityNode` | `nodes.py:499-686` | `name`、`summary`、`name_embedding`、`attributes` | 候选解析、embedding、事实聚合 |
| `CommunityNode` | `nodes.py:687-866` | `name`、`summary`、`name_embedding` | 社区构建/更新，可被检索 |
| `SagaNode` | `nodes.py:867-1007` | `name`、`summary`、`last_summarized_at`、`last_summarized_episode_valid_at` | 顺序 episode 的摘要水印 |

### 13.2 边字段和关系

| 类型 | 位置 | 关系/字段 |
|---|---|---|
| `EpisodicEdge` | `edges.py:143-262` | `EpisodicNode -[MENTIONS]-> EntityNode` |
| `EntityEdge` | `edges.py:263-574` | source/target entity、`fact`、`episodes`、embedding、`valid_at`、`invalid_at`、`expired_at` |
| `CommunityEdge` | `edges.py:575-688` | `CommunityNode -[HAS_MEMBER]-> EntityNode` |
| `HasEpisodeEdge` | `edges.py:689-821` | `SagaNode -[HAS_EPISODE]-> EpisodicNode` |
| `NextEpisodeEdge` | `edges.py:822-934` | Saga 内 episode 顺序关系 |

`EntityEdge.episodes` 是来源 UUID 列表，而不是独立审计日志。删除共享来源时当前实现不自动重写所有引用；因此 provenance 完整性需要额外对账。

## 14. 逐步调用链与边界证据

### 14.1 `add_episode` 单写

1. `Graphiti.add_episode` 校验 `group_id`、entity/edge 类型和输入时间（`graphiti.py:980-1030`）。
2. group 与 driver database 不同时调用 `clone/with_database` 并替换实例 driver（`graphiti.py:1031-1055`）。
3. `retrieve_episodes` 读取上下文；显式 `previous_episode_uuids` 覆盖自动窗口（`graphiti.py:927-978,1057-1084`）。
4. 构造 `EpisodicNode`，`created_at` 为当前时间，`valid_at` 为 `reference_time`（`graphiti.py:1086-1117`）。
5. `_extract_and_resolve_nodes` 调 LLM，生成 canonical nodes 与 UUID map（`graphiti.py:604-629`）。
6. `_extract_and_resolve_edges` 约束端点、抽取时间并处理 duplicate/contradiction（`graphiti.py:631-678`）。
7. `_process_episode_data` 批量保存 episode、entity、facts、MENTIONS 和 Saga 边（`graphiti.py:680-781`）。
8. `update_communities` 为真时追加社区更新（`graphiti.py:1180-1207`）。
9. 返回 `AddEpisodeResults`（`graphiti.py:1210-1228`）；中途异常向上抛出，不提供跨阶段补偿。

### 14.2 `add_episode_bulk`

`add_episode_bulk` 先预写 episode，再通过 `semaphore_gather` 读取上下文和执行抽取，内存中去重并重映射 UUID，随后批量写入实体、边和 Saga（`graphiti.py:1230-1488`）。它不是简单循环调用 `add_episode`；预写与后续事实保存之间存在部分失败残留窗口。

### 14.3 检索

`search` 选择 edge hybrid recipe 并调用 `search` 模块（`graphiti.py:1527-1586`）；`search_` 接受 `SearchConfig`、group、中心节点、BFS 起点和 `SearchFilters`，委托 `graphiti_core/search/search.py`（`graphiti.py:1603-1629`）。search 模块并发执行 fulltext、向量、BFS scope，再做 RRF、MMR、cross-encoder 或 node-distance 排序；任何 provider 查询失败是否形成 partial result 由具体实现决定，当前没有统一 partial-result DTO。

### 14.4 删除和清空

`remove_episode` 先读取 episode 来源边，再筛选只被该 episode 提及的实体，删除 edges/nodes，最后删除 episode（`graphiti.py:1765-1794`）。REST `DELETE /episode` 调 `ZepGraphiti.delete_episodic_node`，不等价于 `remove_episode`；`clear` 先 `clear_data` 再建索引（`ingest.py:99-111`）。

## 15. Provider、配置和部署矩阵

### 15.1 核心 provider

| Provider | 实现 | 事务/连接事实 |
|---|---|---|
| Neo4j | `graphiti_core/driver/neo4j_driver.py` | async session，原生 transaction commit/rollback，close 取消索引 task 后关闭 client |
| FalkorDB | `graphiti_core/driver/falkordb_driver.py` | graph/client 复用，session close/no-op，`execute_write` 非原生回滚 |
| Kuzu | `graphiti_core/driver/kuzu_driver.py` | 本地驱动，事务能力与并发边界需按实现验证；README 标记 deprecated |
| Neptune | `graphiti_core/driver/neptune_driver.py` | provider-specific 查询/连接，未做 live 证据 |

`GraphProvider` 枚举和 `GraphDriver` 抽象在 `driver/driver.py:59-166`；`with_database` 是浅拷贝并复用连接（`driver.py:117-125`），基类 `transaction` 只是 session wrapper，真实 rollback 需 provider override。

### 15.2 LLM、embedding、reranker

| 边界 | 目录 | 失败与资源事实 |
|---|---|---|
| LLM | `llm_client/` | 结构化抽取/去重/摘要；部分指定错误 tenacity 重试；调用方需提供 key/provider |
| embedding | `embedder/` | 节点名、事实和社区名向量；维度/模型一致性由 provider 配置决定 |
| cross-encoder | `cross_encoder/` | 检索重排；不是事实写入事务的一部分 |
| cache/token | `llm_client/cache.py`、`token_tracker.py` | 本地缓存和统计不等于结果持久化或 exactly-once |

### 15.3 配置与部署文件

| 文件 | 作用 |
|---|---|
| 根 `.env.example` | 核心 Neo4j/LLM/embedder 环境变量模板 |
| `mcp_server/config/config.yaml` | MCP provider、模型、日志与服务配置 |
| `mcp_server/.env.example` | MCP 环境变量模板 |
| `mcp_server/docker/docker-compose-neo4j.yml` | Neo4j + MCP 组合部署，默认 `SEMAPHORE_LIMIT=10` |
| `mcp_server/docker/docker-compose-falkordb.yml` | FalkorDB + MCP 组合部署，默认 `SEMAPHORE_LIMIT=10` |
| `server/pyproject.toml` | REST 独立包及 FastAPI 依赖 |
| `Dockerfile`、根 compose | 核心库/数据库开发环境，不等同生产发布门禁 |

## 16. 测试、验证与部署证据矩阵

| 目标 | 源码/测试证据 | 当前执行状态 | 可声明范围 |
|---|---|---|---|
| 节点/边模型 | `tests/test_node_int.py`、`test_edge_int.py` | 未执行 | 测试设计存在 |
| mock 写入 | `tests/test_graphiti_mock.py` | 未执行 | 不能证明真实 provider |
| triplet | `tests/test_add_triplet.py` | 未执行 | 不能证明 embedding/DB 端到端 |
| 查询安全 | `tests/test_edge_db_queries.py`、node label tests | 未执行 | 可审计查询构造源码 |
| REST | `server` live/integration tests | 未执行 | 不能证明 dependency/worker 生命周期 |
| MCP async | `mcp_server/tests/test_async_operations.py` | 未执行 | 有顺序/并发源码场景，不能证明重启恢复 |
| MCP transport | `test_mcp_transports.py`、`test_http_integration.py` | 未执行 | 不能声明服务可用 |
| stress | `test_stress_load.py` | 未执行 | 不能声明容量、背压或公平性 |
| 部署 | Docker compose、README | 未启动 | 只能说明配置路径 |

本轮仅对平台文档做静态修改，未安装依赖、未启动数据库/服务、未调用真实 LLM/embedding。文档验收命令为平台侧 `git diff --check` 和受控缓存读写工作包；这不能替代 Graphiti provider 集成验证。

## 17. 面向系统工程平台的映射

| Graphiti 能力 | 平台映射 | 吸收边界 |
|---|---|---|
| Episode/Entity/Edge Pydantic 模型 | 公共契约中的事件、实体、关系 DTO | 可吸收字段/版本/错误结构；不能直接吸收 provider persistence |
| `Graphiti.add_episode` 编排 | 模块库“事件摄取与事实抽取”模块 | LLM、embedding 必须是支持库能力，由运行核心注入 |
| `SearchConfig` + hybrid search | 模块库“图检索”模块 | 只保留能力 id/契约版本，不静态导入 Graphiti 实现 |
| Neo4j/FalkorDB/Kuzu/Neptune | 支持库适配层 provider | 每个发行包单一 owner，统一结果/错误/资源释放 |
| REST/MCP adapter | 项目适配层或统一网关适配器 | 不复制记忆内核，不把 queued 当 committed |
| QueueService | 运行核心任务调度输入 | 必须补容量、job id、幂等、超时、重试、死信、drain、恢复 |
| Saga/Community | 模块级摘要/社区能力 | 需定义失效、删除、重建和 provenance 对账契约 |
| `Graphiti.close` | 资源协调器 shutdown hook | 明确 driver、模型客户端、队列、线程和 session owner |
| `valid_at/invalid_at/expired_at` | 公共时间语义契约 | 不得扩写为 `known_at` 双时态，除非另有实现与索引证据 |

平台落地不得直接引用 `graphiti_core.nodes`、`graphiti_core.edges` 或 provider 实现目录；只能通过适配层包级公开入口返回统一成功/值/错误码/错误说明。

## 18. 当前提交与文档验证记录

- 参考源码 checkout：`993e081a6d7948a0d8851c12a5fbdbeb49fed862`。
- 远程默认分支：本地 fetch 后与 `origin/main` 一致；未修改参考仓库未跟踪 `ARCHITECTURE.md`、`.codegraph/`。
- 平台唯一文档：本文件；未创建新的 `细探-Graphiti.md` 或其他平行架构文档。
- 本轮新增内容：全量目录/文件导航、SDK/REST/MCP API 表、核心类型字段、调用链 file:line、provider/配置/部署矩阵、测试证据矩阵、平台映射。
- 文档静态检查：本轮执行 `git diff --check` 并以退出码 0 为准；按用户授权未使用 MCP，不生成 `verify_and_record` 记录。
- 未验证项：真实 Neo4j/FalkorDB/Neptune/Kuzu 查询、索引、事务回滚、LLM/embedding 返回、REST lifespan、MCP transport、压力、崩溃恢复、删除后 provenance 对账。

## 19. 源码索引与错误边界补充

### 19.1 查询、写入和维护文件索引

| 文件 | 关键符号/查询 | 维护责任 |
|---|---|---|
| `graphiti_core/graph_queries.py` | 节点、边、episode、社区 Cypher 模板 | 参数绑定和 provider 语法边界 |
| `graphiti_core/search/search.py` | `search`、scope 并发、RRF/MMR | 检索组合，不负责写入事务 |
| `graphiti_core/search/search_config.py` | `SearchConfig`、limit、reranker 参数 | 请求级检索策略 |
| `graphiti_core/search/search_filters.py` | `SearchFilters` 日期、group、label、UUID | 过滤条件校验 |
| `graphiti_core/search/search_config_recipes.py` | edge/node/episode/community recipe | 默认策略，不是 provider 配置 |
| `graphiti_core/utils/maintenance/graph_data_operations.py` | `clear_data`、索引维护 | 清空和重建，非跨 provider 事务 |
| `graphiti_core/utils/bulk_utils.py` | bulk 去重、UUID 映射、批处理 | 内存批次辅助，不提供 durable journal |
| `graphiti_core/utils/datetime_utils.py` | UTC、ISO 转换 | 时间规范化，不创建 known-time |
| `graphiti_core/helpers.py` | `semaphore_gather`、`SEMAPHORE_LIMIT` | 进程内并发限制 |

### 19.2 错误、取消和资源矩阵

| 阶段 | 可能错误 | 当前处理 | 未保证 |
|---|---|---|---|
| LLM 抽取 | provider timeout、结构化输出错误 | 指定错误有限重试，最终抛出 | 之前写入阶段不自动补偿 |
| embedding | API 错误、维度不符 | 当前调用链抛错 | 已保存节点/边的回滚 |
| Neo4j query | session/transaction error | provider transaction rollback（仅显式 transaction） | 高层 add_episode 全链路原子 |
| FalkorDB query | client/graph error | 记录并抛出 | 原生 rollback、clone 隔离 |
| REST worker | job 异常 | worker 路径可能结束/异常传播 | job 状态、重试、死信 |
| MCP queue | process_func 异常 | 日志记录并吞掉，task_done | 调用方失败回执、持久化 |
| asyncio cancellation | await 链取消 | 当前 task 收到 CancelledError | 外部 HTTP/LLM/线程一定停止 |
| close/shutdown | 进程被杀 | finally 可能不执行 | 强杀时资源和未提交写入 |

### 19.3 可复核命令和输出边界

以下命令是源码仓库可复核入口，不代表本轮已执行成功：

```text
python -m pytest tests/test_graphiti_mock.py
python -m pytest tests/test_add_triplet.py
python -m pytest mcp_server/tests/test_async_operations.py
python -m pytest mcp_server/tests/test_mcp_transports.py
python -m pytest server/tests/
docker compose -f mcp_server/docker/docker-compose-neo4j.yml up
```

必须区分：

1. `pytest` 收集/fixture 成功，只能证明测试进入执行路径。
2. mock 或 VCR 成功，只能证明隔离逻辑，不证明真实 provider。
3. healthcheck/HTTP 202/queued，只能证明适配器接受请求，不证明事实已提交。
4. provider integration 通过，仍需单独验证资源关闭、取消、重复请求和删除对账。
5. 压力测试通过，仍需检查容量、队列增长、worker 退出和重启恢复。

## 20. 唯一文档收口结论

Graphiti 的可复用核心是：以 episode 为 provenance 输入，以 entity/edge 为增量事实投影，以 `valid_at/invalid_at/expired_at` 表达事件时间和事实失效，以混合检索连接文本、向量和图邻域。其 REST/MCP 只是入口适配器，QueueService 和 REST worker 都是进程内调度集合，不构成可靠任务系统。

## 19. 2026-08-22 复审记录

- 源码根目录：`~/Documents/Agent/github 源码参考/05_个人自我蒸馏参考/02_长期记忆与记忆操作系统/Graphiti`。
- 当前提交：`993e081a6d7948a0d8851c12a5fbdbeb49fed862`，提交说明 `fix(attributes): preserve prior node attributes when no entity type applies`；`origin/main` 同 SHA，未执行覆盖式更新。
- 工作树仅有未跟踪 `.codegraph/` 与根 `ARCHITECTURE.md`；平台唯一文档仍是本文件，未改源码参考仓库。
- shell `codegraph status`：290 files、5,137 nodes、13,214 edges、13.27 MB，index up to date。CodeGraph 仅用于导航，关键结论回读当前源码与行号。
- 本轮按用户授权未使用 MCP；因此没有 MCP 开工、反馈或 `verify_and_record` 证据，不把静态检查冒充运行验证。
- 已复核远程 SHA、CodeGraph 状态、文档行数（501）及 `git diff --check`；未安装依赖、未启动 Neo4j/FalkorDB/Neptune/Kuzu、未运行 REST/MCP transport 或压力/崩溃测试。

### 19.1 L0-L4 证据边界

| 等级 | 本轮状态 | 结论 |
|---|---|---|
| L0 | 已完成 | Git SHA、目录/文件、配置和 CodeGraph 索引可复现 |
| L1 | 已完成 | 入口、episode/entity/edge、检索、队列、REST/MCP 路径有源码行号 |
| L2 | 未执行 | 测试文件存在不等于测试通过 |
| L3 | 未执行 | 未启动真实数据库、模型、HTTP 或 worker |
| L4 | 未执行 | 未做生产 provider、重启、并发压力、资源残留验证 |

因此本平台只能吸收其数据模型、抽取/去重/检索流程和 provider 适配边界；不能把 Graphiti 当前实现直接当作全流程事务、双时态数据库、可恢复队列或跨 provider 一致性方案。任何平台落地必须重新定义租约、幂等、资源所有权、统一错误和验证证据，并在真实 provider 上执行受控验收。

### 20.1 维护规则

- 源码提交变化时，先更新顶部提交、版本和远程分支证据，再检查受影响 file:line。
- 新增 provider 时，必须同时更新 provider 表、配置矩阵、事务/关闭边界和测试证据。
- 新增 REST/MCP 工具时，必须更新入口表、返回状态、错误和队列语义，不能只追加工具名。
- 新增节点或边类型时，必须更新字段表、关系图、删除路径和 provenance 影响。
- 测试文件新增不等于测试通过；只有带退出码的现场运行才能进入验证记录。
- 旧细探材料不得重新成为第二个架构事实源；所有裁决写回本文件。
- 任何平台映射都必须标注“吸收、适配层隔离或待核”，不得把建议写成 Graphiti 已有能力。
- `valid_at`、`invalid_at`、`expired_at` 与 `created_at` 的语义不得合并；没有源码证据时禁止增加 `known_at`。
- queued、accepted、running、committed、failed、cancelled 必须在适配器契约中分别表达。
- 关闭 driver 不等于关闭 LLM、embedding、cross-encoder、queue、tracer 或后台任务；必须列明 owner。
- provider 查询参数必须保持参数化；label、group 和日期过滤不能通过未经校验的字符串拼接进入 Cypher。
- bulk 写入必须记录预写 episode 与后续事实阶段，故障注入时检查孤儿 episode、重复 UUID 和来源边。
- 社区和 Saga 都是派生投影，删除或重建时必须验证摘要水印和成员边，不得只检查主实体数量。
- MCP 初始化、REST lifespan 和 `Graphiti.close` 必须分别记录启动、排空、关闭顺序；不能用健康端点替代关闭证据。
- 文档中出现的代码行号以本地 checkout 为准；远程更新后重新读取源码，避免沿用历史行号。
- 所有运行验证都应保留命令、退出码、测试数量、外部依赖状态和未验证项。
- 跨 group 并发验证必须确认 driver database、client 引用和返回结果没有串库。
- 任何 “bi-temporal” 文案都必须回到字段、索引和查询过滤三处源码共同核实。
- 适配层返回统一结果时，底层异常只进入错误详情，不直接泄漏到正式业务接口。
- 文档收口后，重复 `ARCHITECTURE.md` 只允许在源码参考仓库自身保留，不在平台研究目录复制。
- 本文件是 Graphiti 在平台侧的唯一权威研究入口，目录导航和证据矩阵均服务于该入口。
- 任何后续增量应优先修正已有章节，而不是新增轮次标题或平行说明文件。
- 本轮 500 行以上的篇幅来自具体路径、符号、字段、状态和验证边界，不代表运行验证已完成。
