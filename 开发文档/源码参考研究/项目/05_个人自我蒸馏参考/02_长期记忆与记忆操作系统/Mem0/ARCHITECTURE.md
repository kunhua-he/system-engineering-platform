# Mem0 架构与可靠性审计

> 审计对象：目标 checkout `~/Documents/Agent/github 源码参考/05_个人自我蒸馏参考/02_长期记忆与记忆操作系统/Mem0`。
> 证据等级：**S** = 本地源码/配置事实，**T** = 已读取但未执行的测试源码，**D** = README、AGENTS 或其他声明，**U** = 未验证。
> 本次只修改本文件；未安装依赖、未启动服务、未调用外部模型或向量库。目标仓库没有 `.codegraph/` 索引，已尝试 `codegraph explore`，返回不可用，因此没有伪造 CodeGraph 调用关系证据。

## 1. 结论摘要

Mem0 是一个多语言 monorepo，核心 Python OSS 路径是一个 `Memory` 编排器，连接 LLM、embedding、vector store、可选 reranker、SQLite history/messages 和基于同一 vector provider 的 entity collection。TypeScript OSS 复刻相同的领域形状，但不是同一实现；托管 client、FastAPI server、CLI 和 integrations 是另外的适配边界。

核心优点：

- `add`、`search`、`get`、`get_all`、`update`、`delete`、`delete_all`、`history` 的公开入口清楚。
- 作用域（`user_id`、`agent_id`、`run_id`）是一等过滤条件；metadata 中的身份字段不能覆盖既定作用域。
- v3 Python 写入是 ADD-only 提取；显式 `update/delete` 承担事实修订，避免 LLM 直接覆盖或删除长期记忆。
- 检索组合语义、可选 BM25 和 entity boost，并支持过期过滤、threshold、top-k 和 explain。
- SQLite 自身有锁、显式事务和 rollback；批量 embedding/vector/history 有逐条 fallback。

最高风险：

- vector store、SQLite history、entity collection 是跨资源顺序写入，没有 operation manifest、幂等键、CAS/version、outbox 或启动恢复对账。
- fallback 可能造成主向量已写而 history 未写，或接口返回成功但只完成部分 item；entity 失败通常只记录日志。
- `AsyncMemory` 大量使用 `asyncio.to_thread`；取消协程不等于取消底层线程或外部请求，写操作可能在调用方收到取消后继续落库。
- 同步 `Memory.close()` 只关闭 SQLite；LLM、embedding、vector、reranker、telemetry 资源没有统一 close 契约。server 配置替换也没有在源码中看到旧实例排空关闭。
- 文档存在明确漂移：根 `AGENTS.md`/`mem0/AGENTS.md` 声称 Python 有 `mem0/graphs/` 和四种 graph provider，但当前 checkout 没有该目录；当前 v3 Python 主流程是 entity collection，不应写成默认 graph memory。

**吸收判断：** Mem0 适合作为记忆领域编排样板，不适合作为跨资源可靠性底座原样移植。应保留作用域、ADD-only、混合检索、审计与消息窗口分工；应隔离其动态导入、日志式部分成功、线程包装异步和不完整 close 语义。

## 2. 代码地图与调用关系

```text
用户 / Agent / 应用
  ├─ Python OSS: mem0.Memory / mem0.AsyncMemory
  ├─ TypeScript OSS: mem0ai/oss Memory
  ├─ Hosted client: MemoryClient / AsyncMemoryClient
  ├─ FastAPI server: server/main.py -> server_state -> Memory
  └─ CLI / integrations / examples

Memory.add
  -> scope/metadata/message 校验
  -> embedding + vector search（infer=True 的上下文）
  -> LLM ADD-only JSON 提取
  -> embedding / vector insert
  -> SQLite history
  -> entity collection upsert（可降级）
  -> SQLite messages 最近窗口

Memory.search
  -> query 校验与 scope filters
  -> query embedding
  -> vector semantic search
  -> optional keyword_search/BM25
  -> entity collection search / boost
  -> 过期过滤 -> threshold -> score_and_rank -> optional reranker

Memory.update/delete
  -> 读取主 vector
  -> 主 vector update/delete
  -> SQLite UPDATE/DELETE history
  -> entity linked_memory_ids 清理或重建
```

| 层 | 主要路径 | 责任和边界 |
|---|---|---|
| Python 入口 | `mem0/__init__.py` | 导出 `Memory`、`AsyncMemory`、hosted clients；版本通过 `importlib.metadata` 获取。 |
| 领域编排 | `mem0/memory/main.py` | CRUD、提取、混合检索、entity linking、过期处理、telemetry。 |
| 抽象与配置 | `mem0/memory/base.py`、`mem0/configs/` | Memory API、Pydantic 配置和 `MemoryItem`。 |
| 提供者 | `mem0/llms/`、`mem0/embeddings/`、`mem0/vector_stores/`、`mem0/reranker/` | 外部模型、向量、重排适配。 |
| 工厂 | `mem0/utils/factory.py` | provider 名到字符串类路径的懒加载；LLM 支持运行时注册。 |
| 本地审计存储 | `mem0/memory/storage.py` | SQLite `history` 和 `messages`，迁移、事务、锁和关闭。 |
| HTTP 适配 | `server/`、`mem0/client/` | 认证、配置、REST/hosted API 错误映射；不应被视为 OSS 核心行为证据。 |
| TypeScript | `mem0-ts/src/oss/src/` | 独立异步实现；支持自动探测 embedding dimension 和可替换 history store。 |

## 3. Provider 与数据边界

### 3.1 LLM、embedding、vector、reranker

`mem0/utils/factory.py` 使用 `importlib.import_module` 和字符串类路径。当前映射覆盖多种 LLM、embedding、vector store 和 reranker；未选 provider 不会全部导入，缺失可选依赖通常在选中 provider 时暴露。工厂错误主要是 `ValueError`、`ImportError` 或 provider 原始异常，不是全入口统一 error envelope。

| 抽象 | 源码契约 | 审计边界 |
|---|---|---|
| `LLMBase` | `generate_response` 和模型参数过滤；配置可由 provider 专属 config 构造。 | 没有统一 deadline、取消、重试预算或 token/cost 结果契约。 |
| `EmbeddingBase` | `embed(text, memory_action)`；默认 `embed_batch` 顺序调用单条。 | 没有统一维度、模型版本、批次上限和结果指纹；批次短返回由调用方自行处理。 |
| `VectorStoreBase` | `create_col/insert/search/delete/update/get/list/reset`；高分表示高相似度。 | 距离到相似度由 provider 自己转换；filter 语义、分页、原子性和 close 行为不统一。 |
| `keyword_search` | 默认返回 `None`，表示不支持。 | `None` 会退化 semantic-only；能力缺失是质量降级，不是公开错误。 |
| `search_batch` | 默认逐条调用 `search`。 | provider 可优化，但没有统一部分结果、item 状态或批次取消契约。 |
| reranker | 可选 Cohere、HuggingFace、Sentence Transformer、LLM、Zero Entropy。 | 失败被捕获并保留原结果，通常只留下 warning；没有 degradation 字段。 |

### 3.2 Entity 与 graph 文档冲突

当前 Python checkout 没有 `mem0/graphs/` 目录；`mem0/vector_stores/neptune_analytics.py` 是 vector-store provider，不能证明独立 graph memory 已进入 Python OSS 默认路径。`Memory.entity_store` 首次访问时复制主 vector 配置创建独立 collection，payload 通过 `linked_memory_ids` 回指主记忆，并参与 entity boost。

冲突来源：

- `mem0/AGENTS.md` 声称有 `graphs/`、四种 graph provider。
- `LLM.md`、server/README、CLI 文档和 `docs/openapi.json` 仍描述 graph memory 能力。
- `skills/mem0/references/features.md` 与插件技能说明 v3 用 built-in entity linking 替代 graph memory。

裁决：本文件以当前 `mem0/memory/main.py`、`mem0/vector_stores/` 和目录实际存在性为实现证据；graph memory 只能标记为“平台/历史文档能力，Python OSS 默认主路径待核”，entity collection 才是本 checkout 可复核的关系辅助索引。

## 4. CRUD 审计

### 4.1 `add`

源码位置：`mem0/memory/main.py:760-1206`，异步对应 `2428-2858`。

1. 校验 `timestamp`、expiration、memory type、消息形状，并要求至少一个作用域身份。
2. `infer=False`：逐条跳过 system/非法消息，逐条 embedding，生成 UUID，写主 vector 和 ADD history；不会自动建立 entity link。
3. `infer=True`：读取 scope 最近 10 条 messages 和 top 10 旧记忆；用数字 ID 映射旧 UUID；一次 LLM 调用执行 ADD-only JSON 提取。
4. 提取为空或 JSON 解析失败时保存 messages 并返回空结果；LLM 调用异常包装为 `LLMError` 并上抛。
5. `embed_batch` 失败逐条 fallback；主 vector 批量 insert 失败逐条 fallback；history 批量写失败逐条 fallback。
6. entity 提取、embedding、search/update/insert 失败通常只 warning/debug，不阻断主记忆返回。
7. 最后保存 messages；该步骤失败会使 add 抛错，但此前主 vector/history 可能已经提交。

关键问题：fallback 只恢复“调用动作”，没有记录每个 item 的成功/失败状态；返回 `records` 不是实际成功写入集合。vector 写失败后仍可能为同 item 写 history，形成幽灵审计。

### 4.2 `search` 与 `get_all`

源码位置：同步 `1379-1731`、异步 `3031` 起。

- query 非空，`top_k` 为非负整数，threshold 在 `[0,1]`；`filters` 至少有 `user_id`、`agent_id`、`run_id` 之一。
- 语义检索超采样 `max(top_k * 4, 60)`；可选 `keyword_search` 返回 BM25；最多 8 个 query entities，实体搜索使用最多 4 个线程或异步并发。
- 语义候选先做过期过滤，再由 `score_and_rank` 做 threshold 门控、BM25/entity 融合、top-k 截断；rerank 失败保留原结果。
- `get_all` 通过 vector store `list`，为隐藏过期项扩大 fetch limit，再格式化 `MemoryItem`。
- `get(memory_id)` 只按 ID 读取，不接受 scope 参数；权限边界依赖 provider/server，不能把它等同为租户授权校验。

搜索不是事务问题，但存在 provider 语义不统一风险：filter operators、分页返回形状、分数范围和 keyword 支持依赖具体 provider；源码对多种返回形状做兼容，却没有统一运行时类型校验。

### 4.3 `update`

源码位置：同步 `1815-1867`、`2032-2092`；异步 `3464` 起。

- 至少提供 text、metadata 或 expiration_date；`data` 是 deprecated 的 text 别名。
- 先读取旧 vector；正文变化时先 embedding，再 vector update，再写 UPDATE history，最后清除旧 entity link 并重建。
- `user_id`、`agent_id`、`run_id`、`actor_id` 等身份字段不可通过 metadata 改写。
- 无版本号/CAS；并发更新或重试可覆盖较新的写入并重复生成 history。
- vector 已更新但 SQLite history 失败时，跨资源不能 rollback；entity 重建也可能失败而只留日志。

### 4.4 `delete`、`delete_all`、`history`

- `delete`：读取旧 vector -> 删除主 vector -> 写 DELETE tombstone history -> best-effort 清理 entity。主删除成功而 history 失败时存在审计缺口。
- `delete_all`：必须有 scope；每批最多 1000 条，使用 `seen_batches` 防止 provider 重复返回导致死循环。同步逐项删除；异步使用 `asyncio.gather(..., return_exceptions=True)`，异常后仍可能返回整体成功消息，没有公开部分失败明细。
- `history`：SQLite 按 memory id 读取 ADD/UPDATE/DELETE，按时间排序；它是审计记录，不是主事实表。
- 已删除后再次 `delete` 通常得到 not found，而不是幂等 tombstone；这使调用方重试需要额外判断。

## 5. SQLite、事务、线程与异步

`SQLiteManager`（`mem0/memory/storage.py`）的静态事实：

- 单个 SQLite connection 使用 `check_same_thread=False`，所有方法用一个 `threading.Lock` 串行化访问。
- 初始化迁移旧 history schema，再创建 `history` 和 `messages` 表。
- migration、建表、history、batch history、messages、reset 都显式 `BEGIN/COMMIT`，异常 `ROLLBACK`。
- `history` 保存变更审计；`messages` 按 `session_scope` 只保留最近 10 条，并按时间顺序返回。
- `close()` 关闭 connection 并置空；析构函数再次调用 close。

SQLite 事务只覆盖 SQLite，无法撤销已经提交的外部 vector store 或 entity collection。单 connection 加大锁能保护本进程，但不是多进程协调，也没有 busy timeout、统一重连或跨资源事务。

`AsyncMemory` 不是原生异步 provider 链：大量调用使用 `asyncio.to_thread`，包括 LLM、embedding、vector、SQLite 和 entity 操作。异步 reset 额外尝试关闭 `vector_store.client`；同步/异步公开 close 没有对所有 provider 做对称释放。取消等待中的 coroutine 不会自动终止已经运行的线程或底层 HTTP 请求，因此写操作可能在调用方收到 `CancelledError` 后继续完成。

## 6. 部分成功、恢复与资源释放矩阵

| 故障点 | 当前行为 | 结果风险 | 必须补的契约 |
|---|---|---|---|
| LLM 调用失败 | 抛 `LLMError`；通常尚未写主记忆。 | 与“无事实”可区分，但没有统一 retry/deadline。 | operation/attempt/provider 错误记录；只对可重试错误退避。 |
| JSON 解析失败 | 视为空事实，仍保存 messages。 | 调用成功但没有新增事实，需让调用方可观察。 | 明确 `no_facts` 与 `provider_error` 结果状态。 |
| embedding batch 失败 | 逐条 fallback；失败文本被跳过。 | 返回结果和输入消息数量可能不一致。 | item-level 状态、批次上限、模型指纹、可重放。 |
| vector batch 失败 | 逐条 insert；失败只日志。 | history 仍可能记录全部 ADD，形成幽灵审计。 | history 只确认实际成功 item；失败进入 outbox。 |
| history 失败 | SQLite rollback；逐条重试。 | vector 已提交时无法回滚，事实与审计分叉。 | 权威写 owner + outbox + 启动对账。 |
| entity 失败 | warning/debug，主结果继续。 | 辅助索引过期、重复边、删除残留。 | 版本化幂等 upsert、补偿删除、可重建和残留扫描。 |
| keyword 不支持 | `None`，semantic-only。 | 质量下降但不是错误。 | 能力状态和 degradation 事件，不伪造空结果。 |
| reranker 失败 | 使用原排序。 | 质量降级通常只在日志中可见。 | 统一 degradation 字段或事件。 |
| async 取消/超时 | `to_thread` 底层工作可能继续。 | 调用方以为未写入，实际可能落库。 | deadline 传播、提交点、独立 worker 或排空后再返回取消。 |
| 进程崩溃 | SQLite 局部事务可恢复；外部状态未知。 | vector/history/entity 不一致。 | operation manifest、启动扫描、可重放/隔离状态机。 |
| close/reset | SQLite close 明确；provider close 不统一。 | 连接、线程、HTTP client、临时目录残留。 | 句柄注册表、幂等 release、成功/失败/取消终态均回收。 |

## 7. TypeScript、Server、CLI 与配置边界

TypeScript `Memory`（`mem0-ts/src/oss/src/memory/index.ts`）构造时创建 embedder、LLM、history manager 和可选 reranker；`_autoInitialize()` 先做 dimension probe，再创建并 await vector store 初始化，失败后 `_ensureInitialized()` 会重试。它支持 `disableHistory` 和多种 history manager；这些能力不能直接推回 Python OSS。TS 仍有 entity store 的独立 collection、逐项错误吞吐和外部 provider 生命周期问题。

Python 根 `pyproject.toml` 声明版本 `2.0.18`、Python `>=3.10,<4.0`，而 `mem0/AGENTS.md` 仍写 Python 3.9-3.12；以构建配置为发布事实。核心依赖包含 qdrant、Pydantic、OpenAI、httpx、PostHog、SQLAlchemy、protobuf，其他 provider 多在 optional extras。

`server/main.py` 是 FastAPI 适配层，`server/server_state.py` 用锁维护配置和 Memory 单例。源码可确认 `/memories`、`/search`、`/configure`、`/reset` 等路由和认证/管理员边界；本文没有启动 Docker、PostgreSQL、pgvector、Neo4j 或 dashboard，因此不把 server 文档的运行描述当作运行证据。配置替换应采用“新实例健康 -> 原子切换 -> 旧实例排空关闭”，当前静态代码未证明已经具备完整流程。

Python/Node CLI 主要调用 hosted platform API；它们的 graph flags、平台 temporal/decay/project 选项不能证明本地 Python OSS 已实现。

## 8. 测试与文档审计

### 8.1 测试证据

已读取测试目录和核心测试源码：

- `tests/test_memory.py`、`tests/memory/test_main.py`：CRUD、scope、异步参数、LLM 错误、malformed JSON、reset。
- `tests/memory/test_storage.py`：SQLite schema、migration、ADD/UPDATE、排序、rollback、close。
- `tests/utils/test_scoring.py`、`test_entity_extraction.py`：BM25、threshold、entity、score explain 和抽取规则。
- `tests/test_client.py`、server/auth/params 测试：hosted client 参数、API 认证和请求映射。
- `tests/llms/`、`tests/embeddings/`、`tests/vector_stores/`、`tests/rerankers/`：provider adapter 测试清单。
- `mem0-ts/src/oss/tests/`、`cli/python/tests/`、`cli/node/tests/`：TS OSS、CLI 的各自测试入口。

这些是 **T 级测试设计证据**，不是执行证据。本轮没有安装依赖或运行 pytest/Jest/Vitest；不能宣称真实 provider、异步取消、跨资源一致性、Docker 或外部 API 通过。

### 8.2 重复、冲突、模糊和可读性

原 `ARCHITECTURE.md` 是多轮追加稿，同一事实在第 2、11、12、13 节重复描述，并把旧轮次结论和当前审计边界混在一起，读者难以判断哪段是最终裁决。本次已合并为单一章节结构，重复内容只保留一次。

已发现的文档漂移：

- 根 `AGENTS.md` 的 graph 目录/数量与当前 Python checkout 不符。
- README 的 benchmark、Temporal Reasoning 和 managed platform 能力明确含 proprietary/hosted 成分，不能当作 OSS 运行事实。
- Python `pyproject.toml` 的 Python 下限与 `mem0/AGENTS.md` 不一致。
- Python API docstring 仍写 `infer=True` 会决定 update/delete，但当前 prompt/代码是 ADD-only；以实现和 README v3 说明为准。
- server、CLI、LLM 文档仍使用 graph memory 术语，和 v3 entity linking 说明并存，必须标注适用版本/产品边界。

可读性改进：事实、风险、证据等级、吸收裁决和验证缺口分离；使用单一代码地图、操作分节、风险矩阵和明确的 S/T/D/U 标签，避免把“已读取”写成“已运行”。

## 9. 吸收与隔离裁决

**应吸收：** 作用域校验；ADD-only 提取；显式 CRUD；`MemoryItem`；语义/BM25/entity 三路融合；过期过滤；history 与 messages 分工；可选 provider 的降级形状。

**应升级后吸收：** `VectorStoreBase`、embedding batch、SQLite history/messages、provider 配置和能力探测。平台侧必须增加统一 provider 注册、超时、资源预算、模型/向量维度指纹和错误 envelope。

**必须新建：** operation/item 状态、幂等键、CAS/version、主事实与审计的 outbox、entity 补偿队列、启动恢复扫描、删除对账、句柄注册表和统一 close。

**先隔离：** 当前不存在的独立 Python graph store；cache；hosted temporal/decay/project API；动态 import 作为唯一 provider 选择机制；`to_thread` 作为可取消异步的替代品。

## 10. 验证缺口与建议命令

本轮只做静态审计。后续若要验证运行行为，应分层执行，不以 mock 测试替代真实链路：

1. L0：确认 `ARCHITECTURE.md` 非空、工作树只包含本文件、所有引用路径存在或明确标注不存在。
2. L1：运行 `hatch run pytest tests/test_memory.py tests/memory/test_main.py tests/memory/test_storage.py tests/utils/test_scoring.py`，核对 add/search/update/delete/history、scope、rollback、reset 和 async 参数。
3. L2：使用真实 SQLite、可控 embedding/LLM 和本地 vector provider，注入 batch 半成功，读回 vector/history/messages/entity 四面状态。
4. L3：启动 server/Docker，验证认证、配置替换、超时、重连、provider close 和 hosted client 映射。
5. L4：注入取消、SIGKILL、删除中断、DB/vector/LLM 故障；重启后对账，检查无幽灵 history、残留 entity、线程、连接和临时目录。

**最终裁决：** Mem0 当前实现提供了可用的记忆领域流程和 provider 生态，但可靠性仍是“局部事务 + 局部 fallback + 日志降级”。在没有跨资源状态机、可重放恢复和完整资源释放证据前，不应把它描述为强一致、可取消或崩溃恢复的长期记忆操作系统。
