# Graphiti 架构与源码审计

> 分析对象：本地 Graphiti 源码快照
> 源码版本：`graphiti-core` `0.29.3`（根 `pyproject.toml`）
> 许可证：Apache-2.0
> 证据等级：本文是本地源码、测试源码、配置和文档审计，不是服务运行报告。

## 1. 研究边界与证据

本轮只研究本地目录，未调用 MCP/Hermes，未启动 Neo4j、FalkorDB、REST 或 MCP，未执行 LLM、embedding 或 cross-encoder。

目标仓库没有 `.codegraph/` 目录。已执行本机 `codegraph explore` 检查，工具明确返回“无索引”；依照其提示未自行运行 `codegraph init`。源码定位因此使用目录清单、全文符号检索和分段文件读取，不能声称已完成 CodeGraph 地图构建。

本轮实际读取范围包括：

- 根 `README.md`、`AGENTS.md`、`pyproject.toml`、`pytest.ini`、`Makefile`、`docker-compose*.yml`、`.env.example`。
- `graphiti_core/graphiti.py`、`nodes.py`、`edges.py`、`graphiti_types.py`、`search/`、`utils/maintenance/`、`utils/content_chunking.py`、`llm_client/`、`driver/`、`namespaces/`。
- `server/graph_service/`、`server/README.md`、`server/pyproject.toml`。
- `mcp_server/src/`、`mcp_server/README.md`、配置文件、Docker 文件和 `mcp_server/tests/`。
- 核心 `tests/`、REST live 测试、MCP 集成/异步/压力/transport/parity 测试，以及既有 `细探-Graphiti.md`。

测试源码的存在不等于测试通过。此前文档记录的 pytest 尝试因环境中无法生成 `pytest` 命令退出码 2；本轮没有重跑测试，只执行了最终 `git diff --check`。

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

`SEMAPHORE_LIMIT` 在 `graphiti_core/helpers.py` 当前默认是 20，README 的服务说明仍写 10；MCP `GraphitiService` 又有自己的默认 semaphore limit 10。三者不是同一配置，不能互相外推。

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

`QueueService` 为每个 group 保存进程内无界队列，一次处理一个 episode，同 group 顺序执行，不同 group 可并行。异常被记录并吞掉，调用方只收到 queued 位置，不会得到实际结果或失败状态。

QueueService 没有容量背压、超时、重试、持久化、死信、drain、stop 或恢复 API。`add_episode_task` 先 `create_task`，worker 后设置 `_queue_workers[group_id]`，并发提交窗口存在重复 worker 竞态。MCP 初始化全局 Graphiti client 和 QueueService，但 QueueService 本身没有统一 shutdown；重启没有恢复队列或扫描未完成写入。

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

本文件是本地研究的唯一架构收口入口；`细探-Graphiti.md` 保留为历史细探，不作为第二个权威架构文档。本轮只修改根 `ARCHITECTURE.md`。

## 10. 施工材料吸收记录

已人工回读并吸收 `细探-Graphiti.md` 中的增量事实：episode 增量摄取与实体/边去重、`valid_at/invalid_at/expired_at` 的实际字段边界、四类检索 scope 的 RRF/MMR/cross-encoder 组合、Saga/Community 关系、Neo4j 与 FalkorDB 事务差异、REST/MCP 队列生命周期以及删除路径不等价。旧材料未提供可替代的运行验证；相关结论仍按本文的 L0/L1 静态证据和待核项处理。
