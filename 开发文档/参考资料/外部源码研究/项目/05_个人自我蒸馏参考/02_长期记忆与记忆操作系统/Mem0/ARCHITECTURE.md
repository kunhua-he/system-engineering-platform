# Mem0 架构与可靠性审计

> 审计对象：目标 checkout `~/Documents/Agent/github 源码参考/05_个人自我蒸馏参考/02_长期记忆与记忆操作系统/Mem0`。
> 证据等级：**S** = 本地源码/配置事实，**T** = 已读取但未执行的测试源码，**D** = README、AGENTS 或其他声明，**U** = 未验证。
> 本次只修改本文件；未安装依赖、未启动服务、未调用外部模型或向量库。目标仓库存在 `.codegraph/`，已执行 shell `codegraph explore`，未调用 MCP；CodeGraph 仅用于当前源码定位，不代替运行验证。

```text
Memory / AsyncMemory 调用方
        │  mem0/memory/main.py:760, 1379, 1815, 1869, 1946
        ▼
作用域与输入校验
        │  user_id / agent_id / run_id -> filters；拒绝顶层 entity 参数
        ▼
Memory.add
        │  LLM ADD-only 提取 -> embedding -> VectorStoreBase.insert
        │  SQLite history/messages -> entity_store 派生索引
        ▼
Memory.search
        │  semantic search -> 可选 keyword/BM25/entity boost
        │  过期过滤 -> threshold/top-k -> 可选 reranker
        ▼
Memory.update/delete/history
        │  主向量与 entity 链接变更，SQLite 记录审计
        ▼
Provider / Server / Client 适配层
        │  mem0/vector_stores、mem0/memory/storage.py、server/
        ▼
外部 LLM、embedding、向量库、SQLite、HTTP 与进程资源
```

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

这些是 **T 级测试设计证据**，不是执行证据。没有安装依赖或运行 pytest/Jest/Vitest；不能宣称真实 provider、异步取消、跨资源一致性、Docker 或外部 API 通过。

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

当前只做静态审计。若要验证运行行为，应分层执行，不以 mock 测试替代真实链路：

1. L0：确认 `ARCHITECTURE.md` 非空、工作树只包含本文件、所有引用路径存在或明确标注不存在。
2. L1：运行 `hatch run pytest tests/test_memory.py tests/memory/test_main.py tests/memory/test_storage.py tests/utils/test_scoring.py`，核对 add/search/update/delete/history、scope、rollback、reset 和 async 参数。
3. L2：使用真实 SQLite、可控 embedding/LLM 和本地 vector provider，注入 batch 半成功，读回 vector/history/messages/entity 四面状态。
4. L3：启动 server/Docker，验证认证、配置替换、超时、重连、provider close 和 hosted client 映射。
5. L4：注入取消、SIGKILL、删除中断、DB/vector/LLM 故障；重启后对账，检查无幽灵 history、残留 entity、线程、连接和临时目录。

**最终裁决：** Mem0 当前实现提供了可用的记忆领域流程和 provider 生态，但可靠性仍是“局部事务 + 局部 fallback + 日志降级”。在没有跨资源状态机、可重放恢复和完整资源释放证据前，不应把它描述为强一致、可取消或崩溃恢复的长期记忆操作系统。

## 11. 当前提交、源码树与 CodeGraph 证据

### 11.1 快照身份

- 当前 HEAD：`feb12852c0789a1f1182b05ee0dbc386037b012f`；已通过 `127.0.0.1:4780` 拉取远端 HEAD 并快进同步。
- Python 包版本声明来自当前 `pyproject.toml`；TypeScript OSS、hosted client、server 和 integrations 是同一仓库中的独立运行面，不能混写为一个实现。
- 源码树统计：371 个 Python 文件、129 个匹配 `test*.py` 的测试文件；另有 `mem0-ts`、CLI、skills、server、integrations 和多 provider 目录。
- 只修改根 `ARCHITECTURE.md`；`.codegraph/` 是当前索引生成物，源码、测试、配置、锁文件和 Git 历史未修改。

### 11.2 CodeGraph 查询

```text
codegraph explore "Memory add search update delete reinforce MemoryManager provider vector store"
codegraph explore "mem0 Memory.add search update delete async concurrent transaction"
```

查询返回并经函数体核对的主要锚点：

| 符号 | 文件/行 | 真实边界 |
|---|---|---|
| `Memory.__init__` | `mem0/memory/main.py:487-552` | 工厂创建 embedder/vector/LLM/reranker/SQLite |
| `Memory.add` | `mem0/memory/main.py:760` | scope、ADD-only 提取、vector/history/entity |
| `_add_to_vector_store` | `mem0/memory/main.py:879` | LLM 提取与主向量写入阶段 |
| `Memory.search` | `mem0/memory/main.py:1379` | semantic/keyword/entity/过期/重排 |
| `Memory.update/delete` | `main.py:1815/1869` | CRUD 与 history/entity 清理 |
| `AsyncMemory.add/search` | `main.py:2434/3037` | `to_thread`/异步 provider 包装 |
| `VectorStoreBase` | `mem0/vector_stores/base.py:16` | provider 最小 CRUD/search 契约 |
| `SQLiteManager` | `mem0/memory/storage.py:1-250` | history/messages 事务和锁 |

CodeGraph 还显示 `VectorStoreBase.update` 分派到 27 个 provider 实现；这证明接口多态存在，不证明每个 provider 的 filter、原子 update、close 或错误语义相同。

### 11.3 目录与命名解释

| 目录 | 实际职责 | 命名陷阱 |
|---|---|---|
| `mem0/memory/` | Python OSS 领域编排、基类、SQLite history | `Memory` 不是 vector store；`MemoryManager` 并非独立队列 |
| `mem0/vector_stores/` | 27+ 外部向量/混合索引适配 | `VectorStoreBase` 方法名相同但 provider 事务/过滤不同 |
| `mem0/llms/`、`embeddings/` | LLM/embedding factory/provider | 动态导入将依赖和错误推迟到运行时 |
| `mem0/reranker/` | 可选重排 | 失败一般保留原序，没有统一降级字段 |
| `mem0/client/` | hosted API 同步/异步 client | 不是本地 OSS 事实源 |
| `server/`、`mem0/proxy/` | FastAPI server/proxy | 配置替换、认证和单例生命周期另有边界 |
| `mem0-ts/` | TypeScript OSS 复刻 | 与 Python 版本独立，异步/初始化语义不同 |
| `integrations/` | OpenClaw、LangChain 等适配 | 集成工具可能直接映射 CRUD，不能推导核心一致性 |
| `skills/`、`cli/` | 文档、平台/CLI 工作流 | 平台能力和 OSS 能力混合，需按版本裁决 |

## 12. 五条真实函数体调用链

### 12.1 `add` → ADD-only → vector/history/entity

```text
Memory.add (main.py:760)
  -> normalize expiration + build scope filters
  -> normalize messages/roles
  -> infer=True: read recent messages + old vectors
  -> LLM ADD-only extraction / JSON parse
  -> embed_batch (逐条 fallback)
  -> vector_store.insert (批量失败逐条 fallback)
  -> SQLite history ADD
  -> entity extraction + entity_store upsert (best effort)
  -> SQLite messages recent-window write
  -> return results
```

主 vector、history、entity 和 messages 不共享一个事务。返回 results 是逻辑提取结果，不能证明每条向量都已成功插入；批量 fallback 失败记录主要停留在日志。

### 12.2 `search` → semantic/keyword/entity → rerank

```text
Memory.search (main.py:1379)
  -> validate query/top_k/threshold/filters
  -> query embedding
  -> vector_store.search(top_k*4 or 60)
  -> optional keyword_search/BM25
  -> extract query entities + entity_store search (最多约8)
  -> filter expiration/show_expired
  -> score_and_rank (semantic + keyword + entity boost)
  -> optional reranker
  -> top_k MemoryItem/explain
```

provider 不支持 `keyword_search` 时返回 `None` 并退化 semantic-only；reranker 异常保留原排序。结果没有 `degraded_sources`，调用方无法从同一返回结构区分能力缺失与零命中。

### 12.3 `update` → vector → history → entity rebuild

```text
Memory.update (main.py:1815)
  -> get(memory_id)
  -> validate text/metadata/expiration and identity immutability
  -> embed new text
  -> vector_store.update
  -> SQLite history UPDATE
  -> remove old memory_id from entity linked_memory_ids
  -> re-extract/re-upsert entities
  -> return MemoryItem
```

更新没有 version/CAS；并发更新可覆盖新值。vector update 成功而 history 或 entity rebuild 失败时，事实和审计/辅助索引分叉。

### 12.4 `delete/delete_all` → tombstone/entity cleanup

```text
Memory.delete (main.py:1869)
  -> vector_store.get old row
  -> vector_store.delete
  -> SQLite DELETE history tombstone
  -> _remove_memory_from_entity_store (best effort)

Memory.delete_all (main.py:1890)
  -> list scoped IDs in batches <=1000
  -> seen_batches avoid repeated provider pages
  -> delete each item (async gather with return_exceptions)
  -> return aggregate message
```

delete 不是数据库 tombstone 与 vector delete 的原子操作；delete_all 异步异常可被收集后仍返回整体成功，调用方拿不到每项失败清单。

### 12.5 Async wrapper → `to_thread` → uncancellable provider

```text
AsyncMemory.add/search/update/delete
  -> asyncio.to_thread(sync Memory method) 或 provider async adapter
  -> caller awaits coroutine
  -> caller cancellation stops await, not necessarily worker thread/HTTP request
  -> underlying vector/SQLite/LLM may continue and commit
```

这条链是异步 API 的关键可靠性边界：协程取消不等于写操作取消，不能把 CancelledError 返回给调用方写成“未落库”。

## 13. 关键数据模型与 provider 状态

### 13.1 MemoryItem 与作用域

`MemoryItem` 至少包含 id、memory/text、hash、metadata、score、created_at、expiration_date 等；`user_id/agent_id/run_id` 作用域由 filters 建立。`add()` 接受顶层身份参数，`search/get_all` 要求 `filters` 形式；混用会抛 ValueError。metadata 中同名身份字段不能覆盖显式作用域。

### 13.2 SQLite history/messages

`history` 是事件审计表，记录 ADD/UPDATE/DELETE；`messages` 是每个 session scope 的最近上下文窗口，默认保留约 10 条。SQLite 单连接 `check_same_thread=False` + `threading.Lock` 保护本进程访问；BEGIN/COMMIT/ROLLBACK 只保护 SQLite，不保护向量、LLM 或 entity collection。

### 13.3 Entity collection

`Memory.entity_store` 懒创建独立 collection；实体 payload 存 `data/entity_type/linked_memory_ids` 和 scope。`_upsert_entity` 先 normalized text 查找，再 semantic >=0.95 认定匹配，否则插入新 UUID。删除/更新逐实体重嵌入或删除，单条异常被吞掉；entity 是辅助索引，不是主事实权威。

### 13.4 Provider 选择与初始化

`Memory.__init__` 调 EmbedderFactory、VectorStoreFactory、LlmFactory、SQLiteManager，并按配置创建 reranker/telemetry store。`from_config` 只负责 Pydantic 配置解析后实例化；动态 import 的 provider 依赖直到选择时才失败。`entity_store` 和 telemetry store 可能复制主 vector config，某些嵌入式 provider 还共享 client 以规避锁冲突。

## 14. 并发、事务、取消与资源

### 14.1 并发与容量

- `embed_batch`、vector batch 和 `delete_all` 批次大小/并发由 provider 或主流程决定，没有统一 operation budget。
- entity linking 对 query/entity 使用有限线程或 gather，但不建立跨进程租约。
- SQLite lock 只保护当前进程内单连接，多进程/多 worker 需要外部锁或独立 DB 设计。
- vector provider 的 client 是否线程安全、是否支持并发 update/delete 取决于实现；抽象未声明。
- `AsyncMemory` 使用 `to_thread` 会消耗默认线程池，任务无界时可能堆积；没有全局 queue、backpressure 或 shutdown drain。

### 14.2 事务边界

`SQLiteManager` 的 rollback 只覆盖自身 SQL。主 vector insert/update/delete、entity upsert/cleanup、messages/history 依次发生；不存在跨资源 commit marker、outbox 或 saga。批量失败后逐条 fallback 可能造成顺序差异和部分成功，且没有 item-level durable status。

### 14.3 取消、超时、崩溃

源码未为所有 LLM、embedding、vector、reranker 调用建立统一 deadline；部分 HTTP provider 自带 timeout，不能外推到全部。调用方取消 async wrapper 时，已运行线程和外部请求可能继续。进程崩溃后 SQLite 未提交事务可回滚，但外部 vector/entity 已提交状态没有启动扫描、重放或回滚协议。

### 14.4 关闭资源

同步 `Memory.close()` 主要关闭 SQLite；异步 reset 额外尝试关闭 `vector_store.client`。LLM、embedding、reranker、telemetry vector store、线程池和 HTTP session 没有统一 close registry。server 单例替换和 proxy shutdown 需要逐实例验证，不能仅凭 FastAPI lifespan 推导资源归零。

## 15. 正常/失败/超时/取消/崩溃矩阵

| 场景 | 当前源码行为 | 可依赖结论 | 未闭合风险 |
|---|---|---|---|
| 正常 add infer=True | ADD-only facts→embed→vector/history/entity/messages | 领域流程可导航 | 跨资源非原子 |
| JSON/LLM 失败 | malformed JSON 可能视为空事实；LLM error 抛出 | 可区分部分 provider 错误 | no_facts 与 provider_error 不同状态未统一 |
| embedding batch 失败 | 逐条 fallback，失败 item 跳过 | 其他 item 可能继续 | 无 item-level 失败记录 |
| vector batch 失败 | 逐条 insert fallback | 部分向量可落库 | history 可能记录失败 item |
| history 失败 | SQLite rollback/重试 | SQLite 内局部一致 | vector 无法回滚 |
| entity 失败 | warning/debug 后主流程继续 | 主记忆可返回 | entity 过期/删除残留 |
| search provider 不支持 BM25 | keyword `None`，semantic-only | 查询仍可返回 | 质量降级未结构化 |
| reranker 失败 | 原顺序保留 | 不阻断返回 | 调用方不知降级 |
| update 并发 | 无 CAS/version，后写覆盖 | 单次调用可工作 | 重试/并发历史错序 |
| delete_all 部分异常 | async gather 收集异常仍可整体成功 | 可能删除多数 | 无公开失败项清单 |
| async cancel | await 被取消，to_thread 可能继续 | 仅停止等待 | 实际可能继续写入 |
| process crash | SQLite 未提交回滚 | 局部可恢复 | vector/entity/history 分叉 |
| close/reset | SQLite 明确关闭，provider 不对称 | 部分资源释放 | HTTP/client/thread 残留 |

## 16. 测试映射、未读范围与平台映射

### 16.1 测试文件映射

- `tests/memory/test_main.py`、`tests/test_memory.py`：CRUD、scope、infer、LLM error、malformed JSON、reset 与异步参数。
- `tests/memory/test_storage.py`：SQLite migration、history/messages、排序、rollback、close。
- `tests/utils/test_scoring.py`、`test_entity_extraction.py`：阈值、BM25/entity、抽取规则。
- `tests/vector_stores/`、`tests/embeddings/`、`tests/llms/`、`tests/rerankers/`：provider adapter 局部契约；不证明全链路一致。
- `tests/test_server_auth.py`、`test_client.py`、`test_project.py`：hosted/server 适配，不等于 OSS vector 事实。
- `mem0-ts/src/oss/tests/`、`cli/*/tests/`、integrations tests：独立实现与工具测试，不能混并到 Python 证据。

### 16.2 未读或未执行范围

1. 真实 Qdrant/pgvector/Milvus/Redis/ES 等 provider 的 filter、batch、分页、update/delete 原子性。
2. LLM/embedding/reranker 网络超时、限流、取消、重试和 token/cost 预算。
3. 多进程 SQLite、server 配置热替换、proxy shutdown、线程池耗尽。
4. 同一 memory 并发 update/delete、重复 add、vector/history/entity 对账。
5. SIGKILL、DB 断连、provider 部分成功后的启动恢复和可重放。
6. 多语言实现与 Python 版本的语义差异、托管 API 的认证/项目成员边界。

### 16.3 L0-L4

| 等级 | 定义 | 当前 |
|---|---|---|
| L0 | 源码/配置/CodeGraph 直接阅读 | add/search/update/delete/provider/SQLite 事实 |
| L1 | 测试源码存在且有断言，未执行 | CRUD、storage、provider、server/client 映射 |
| L2 | 当前命令成功 | CodeGraph、文档结构、git diff 检查 |
| L3 | 真实模型/向量库/server 链 | 0 |
| L4 | 故障注入/压力/崩溃恢复/资源归零 | 0 |

### 16.4 系统工程平台映射

| Mem0 能力 | 平台职责候选 | 必须补齐 |
|---|---|---|
| `Memory.add` ADD-only 与作用域 | 模块库记忆写入 | operation/item 状态、幂等键、provider 锁定 |
| search semantic/BM25/entity | 模块库检索融合 | 统一 score/degraded/error envelope |
| vector store adapters | 支持库外部向量适配 | 能力注册、超时、维度/模型指纹、close |
| SQLite history/messages | 支持库审计与上下文窗口 | outbox、跨资源对账、恢复扫描 |
| AsyncMemory | 运行核心异步调用器 | 不把 to_thread 取消宣称为写入取消 |
| server/client/integrations | 项目适配层/统一网关 | 认证、租约、配置替换和证据账本 |

## 17. 结构验证记录

- 当前 HEAD 已核对为 `feb12852c0789a1f1182b05ee0dbc386037b012f`；上游本次主要更新 TypeScript/集成依赖锁、dashboard 锁文件与文档路由，Python Memory 主链未见改动，但 provider/SDK 版本复核仍以该提交为准。
- 两次 CodeGraph 查询均退出码 0；未调用 MCP。
- 文档结构检查、关键章节存在、行尾空白检查与 `git diff --check` 必须退出码 0。
- 未安装依赖、未启动服务、未连接外部模型/向量库、未运行 pytest/Jest/Vitest；应用证据仍为 L0/L1，L3/L4 为 0。
- 剩余风险：跨资源部分成功、异步线程取消、provider 语义差异、entity 辅助索引残留、server 热替换和真实多进程恢复均需后续受控验证。

## 18. 最小验收场景（未执行）

### 18.1 正常链

使用可控 fake LLM、embedding 和本地 vector store，分别验证 `infer=False` 原文写入、`infer=True` ADD-only 提取、作用域隔离、search top-k、history 与 messages 窗口；逐项读取主 vector、SQLite、entity collection，记录 item-level 成功集合。

### 18.2 失败链

在 LLM JSON malformed、embedding 第 n 项失败、vector batch 第 n 项失败、history transaction rollback、entity update 失败五个位置注入异常；要求结果明确区分 `no_facts`、partial、provider_error，且不得把失败 item 写成已成功 history。

### 18.3 并发和恢复链

并发 add/update/delete 同一 memory，检查无 CAS 时的覆盖顺序；取消 `AsyncMemory.add` 后等待线程池排空，确认是否仍有 vector/history 写入；SIGKILL 后重启扫描并对账 vector、history、messages、entity。当前源码没有这些状态记录，因此测试前需先定义预期。

### 18.4 Provider/资源链

至少选 Qdrant、pgvector、Milvus 各一实现，验证 filter 运算符、score 范围、keyword fallback、update/delete、分页和 close；server 配置切换时确认旧 Memory、SQLite、HTTP client、reranker 和 telemetry store 全部排空，不能只检查新实例健康。

### 18.5 交付判定

只有文档结构检查与 `git diff --check` 退出码为 0，且工作树确认仅有根 `ARCHITECTURE.md` 与索引生成物时，才可记录文档交付；这不等价于 Mem0 应用链通过。真实 provider、取消、崩溃和恢复证据必须单独登记为 L2-L4，不能从本地静态审计升级。

交付回传还必须带上项目根、HEAD、CodeGraph 查询、源码统计、修改文件、验证命令及退出码、未读范围和剩余风险。任何遗漏都只能算研究中间态，不能作为平台合并完成信号。

本文件没有读取凭据、生产数据库或用户数据；示例中的 API keys、provider endpoints 和路径均只作为接口类别说明。所有外部副作用保持未执行状态，便于主会话后续统一安排受控验证。

静态事实与运行事实的分界必须在后续报告中保持：源码存在是 S，测试源码是 T，命令成功是 L2，真实 provider 链与故障注入分别需要 L3/L4。

在平台吸收前，先固定当前快照和文档证据，再按失败矩阵逐项补做运行验证。

# 19. 补充审计：作用域、ADD-only 与辅助索引复核（2026-08-21）

## 20. 当前版本与公开接口复核

1. 当前本地 HEAD 与远端默认 HEAD 均为 `feb12852c0789a1f1182b05ee0dbc386037b012f`；同步保护了未跟踪 `ARCHITECTURE.md` 与 `.codegraph/`，未执行强制改写。
2. Python `Memory` 位于 `mem0/memory/main.py`，公开 `add/search/get/update/delete/history` 将 scope、LLM ADD-only 提取、embedding、vector store、SQLite history 和 entity collection 串联。
3. `VectorStoreBase` 只定义 provider CRUD/search；距离、过滤、批量原子性、keyword/BM25、分页和 close 语义由各 provider 决定，不能由接口名称推断一致事务。
4. `Memory.entity_store` 是独立 vector collection 的关系辅助索引，通过 `linked_memory_ids` 回指主记忆；当前 checkout 没有独立 Python graph memory 目录，历史文档中的 graph provider 需隔离标注。
5. `search` 先做 semantic 超采样，再可选 keyword/BM25 与 entity boost，随后过期过滤、阈值、融合排序和 rerank；rerank 失败保留原候选，不应被解释为检索质量等于重排成功。
6. `update` 是显式事实修订：读取旧向量、重新 embedding、更新主 vector、写 UPDATE history、清理并重建 entity；任何中间失败都可能形成 vector/history/entity 不一致。
7. `delete_all` 强制 scope，批量上限 1000；异步 `gather(return_exceptions=True)` 可能吞并单项错误，调用方必须读取逐项证据而不能只看整体返回消息。
8. SQLite 锁和事务只覆盖本地 history/messages；vector、entity、LLM、embedding 和 reranker 是外部资源，没有跨资源事务、outbox 或启动对账。
9. `AsyncMemory` 大量通过 `asyncio.to_thread` 包装同步 provider；取消 coroutine 不会强制终止已运行线程或底层 HTTP，请求方需区分取消已确认与取消等待中。
10. TypeScript `mem0-ts` 的 Memory 构造会初始化 embedder、LLM、history manager、reranker 和 vector store，并执行 dimension probe；其异步初始化、entity collection 和错误吞吐不能直接回写 Python 事实。
11. `server/main.py` 与 `server/server_state.py` 提供 FastAPI 路由、认证、配置替换和 Memory 单例；配置替换的旧实例排空关闭未由静态源码证明，server 文档不等价于实际运行证据。
12. REST/SDK/CLI 是适配面：托管 API 的 graph、temporal、decay、project 等参数不能证明本地 OSS 已提供同等能力；请求应保留 client、user、run 和 scope 绑定。
13. 失败终态至少区分 ADD 提取失败、embedding/provider 失败、vector 部分写入、history rollback、entity 清理失败、过期过滤空结果、rerank 降级、取消未确认和进程崩溃。
14. 测试源码覆盖 memory、server auth、client、provider、scoring、entity、telemetry 和集成场景；未安装依赖、未运行 pytest、未启动真实向量库/LLM/HTTP 服务。

## 19.1 入口和身份边界

源码提交 `feb1285` 的 `mem0/memory/main.py` 在 `add()`、`search()`、`update()`、`delete()` 入口统一校验 `user_id`、`agent_id`、`run_id`，并从这些字段生成 session scope。`input_metadata` 中的身份键会被剥离，不能借 metadata 越权改变作用域；顶层实体参数也被拒绝，实体过滤必须走显式 filters。该约束是 SDK 内部校验，不等价于 server/API 鉴权或跨租户授权。

## 19.2 ADD-only 与两类派生写入

当前主流程同时存在两种语义，不能只按 README 的“ADD-only”概括：

1. 新版提取提示与 agent-confirmed facts 路径倾向只追加候选事实，避免在 LLM 输出中直接产生 UPDATE/DELETE。
2. OSS `Memory.add(..., infer=True)` 仍会进入事实解析、向量写入、history 记录和可选 entity linking；显式 `update()`/`delete()` 仍是受调用方控制的修改入口。

因此 ADD-only 只描述提取算法的候选生成策略，不是全 SDK 的不可变存储保证。`history` 是变更审计记录，SQLite 与 vector/entity store 之间没有统一提交标记；任何“只追加”结论都必须同时说明派生索引和显式 CRUD 边界。

## 19.3 Entity store、history migration 与对账

`entity_store` 首次使用时深拷贝 vector 配置并改写 collection 名称；它是独立的辅助索引，不是主 memory collection 的事务分区。`SQLiteManager` 启动时会检查旧 history 表列并执行 rename/create/copy/drop 迁移，失败重试只覆盖 SQLite 内部，不能回滚已经写入的外部向量。

新增裁决：

- entity linking 失败可被主流程记录 warning 后继续，因而“memory 返回成功”不代表实体索引完整；
- history migration 的成功不能证明 vector schema 或 entity collection 已迁移；
- scope 字段是查询过滤边界，但 provider 若不正确实现 filter，SDK 抽象没有统一的越权检测回退。

## 19.4 补充审计验证边界

当前只做源码定位和文档结构检查（L0/L2），未连接真实 provider、未执行 SQLite 迁移、未运行并发 scope 测试。必须继续验证：不同 provider 的 filter 等价性、同 scope 并发 update 的覆盖顺序、history/vector/entity 三方对账，以及 server auth 与 SDK scope 的组合边界。

## 20. 函数级复审补充

### 20.1 CRUD 与派生索引

- `mem0/memory/main.py:760-1205` 的 `Memory.add` 先校验 scope 和输入，再调用 LLM/事实解析、embedding 与主 vector store；entity linking 通过 `_entity_store` 单独 insert/update。主向量成功而 entity 写失败时没有跨 provider 回滚。
- `Memory.search`（1379 起）按 scope 构造 filters，先 semantic search，再按 provider 能力追加 keyword/BM25、entity boost、过期过滤和 rerank；provider 未实现 `keyword_search` 时由基类能力检测决定是否跳过。
- `Memory.update`（1815-1867）读取旧记录并重新 embedding，更新 vector payload，写 SQLite history，再清理/重建 entity 关联；这些步骤不是一个数据库事务。`delete`/`delete_all`（1869-1944）删除主向量、entity link 和 history，批量删除的逐项错误需由调用方读取。
- `history`（1946 起）只从 SQLite 读取变更记录；它能证明审计行存在，不能证明 vector/entity 已完成同一版本提交。

### 20.2 Provider 与作用域

- `mem0/vector_stores/base.py:4-91` 只规定 add/search/update/delete/get/list 等接口；仓库包含二十余个 provider 实现，过滤语义、距离阈值、批量原子性、close 和错误类型由实现自行决定。
- `Memory.entity_store`（559-580）深拷贝 vector 配置并改 collection 名称，形成独立辅助索引；`linked_memory_ids` 是反向关系字段，不是图数据库事务。
- `main.py` 的 `_reject_top_level_entity_params`（165-172）拒绝从顶层参数注入实体身份，要求通过 filters；这只是 SDK 输入约束，server 的 auth、API key、项目成员角色仍由 `server/auth.py` 与 `server/main.py` 负责。

### 20.3 异步与失败资源

- `AsyncMemory`（2172 起）大量使用 `asyncio.to_thread` 调同步 Memory/provider；取消 await 不会杀掉已进入线程的 HTTP/SDK 调用，必须区分“取消等待”与“底层操作已停止”。
- SQLite manager 的迁移和 history 事务只覆盖本地数据库；LLM、embedding、vector、entity、reranker 没有统一 deadline、outbox 或补偿队列。更新中途崩溃可能留下 history 与向量版本不一致。
- server 单例替换、provider client、连接池和后台任务没有静态可证明的统一 shutdown；配置热切换后旧实例排空、网络请求取消和资源释放仍是运行验证项。

### 20.4 当前版本与验证

- 当前 HEAD 为 `feb12852c0789a1f1182b05ee0dbc386037b012f`，分支 `main`，远端 `https://github.com/mem0ai/mem0.git`；工作树仅有未跟踪 `.codegraph/` 与根 `ARCHITECTURE.md`。
- `codegraph sync` 退出码 0；查询 `Memory.add search update delete history AsyncMemory VectorStoreBase SQLiteManager entity_store` 退出码 0，输出 618 行。文档补充后应执行 `git diff --check`、结构/实现词扫描；未运行真实 provider、SQLite migration、并发 scope、server auth 或崩溃恢复测试。

## 21. 2026-08-22 增量复核

- 本地与 `origin/HEAD` 均为 `feb12852c0789a1f1182b05ee0dbc386037b012f`；经 `http://127.0.0.1:4780` 复核无远程漂移，未覆盖未跟踪 `.codegraph/` 与 `ARCHITECTURE.md`。
- `codegraph status`：1,021 files、13,805 nodes；查询 `Memory add search update delete` 成功，命中 Python `mem0/memory/main.py:760`、异步 `:2434`、TypeScript `index.ts:720` 及 provider dispatch。
- L0/L1 已复核；L2 测试源码存在但本轮未运行；L3/L4 真实 vector provider、SQLite migration、server auth、取消、崩溃恢复和跨资源对账均未验证。
- 仅使用 shell/git/codegraph CLI，未调用任何 MCP；本轮只修改平台侧本文件。
