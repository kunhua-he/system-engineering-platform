# LightRAG 架构事实与一致性审计

> 本文是本地 checkout 的架构事实入口。源码标识、配置键、接口路径和测试文件名保留原文；结论按“实现已确认 / 有定向测试断言但当前核对未执行 / 未验证”区分。本文只修改文档，不代表服务、远程后端或测试已运行。

## 1. 范围、基线与证据

- 项目：LightRAG（仓库 `HKUDS/LightRAG`），本地版本 `lightrag.__version__ = 1.5.5`，API 版本 `0321`。
- 根目录：`/Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/55_knowledge_graph_rag/LightRAG`。
- 研究范围：`ingest → chunk → extraction → KV/Graph/Vector/DocStatus → query → queue → API → tests → docs`。
- 当前核对未使用 MCP/Hermes；目标仓库没有 `.codegraph` 索引，已先行确认 CodeGraph 不可用，未自行初始化索引。
- 当前核对未安装依赖、启动服务、构建前端或运行测试。测试文件只证明存在回归意图，不证明通过。

证据等级：

- **E1**：实现、异常路径或源码注释直接确认。
- **E2**：实现与定向测试共同覆盖，但当前核对未执行。
- **E3**：仓库文档、配置或测试配置确认。
- **U**：需要真实服务、远程后端、强杀、性能或故障注入才能确认。

## 2. 系统边界与入口

```text
客户端 / SDK / WebUI / Ollama-compatible client
                    │
             FastAPI + auth
                    │
              LightRAG 门面
          ┌─────────┼─────────┐
       pipeline    operate   role LLM
   ingest/状态/分块  抽取/检索  EXTRACT/KEYWORD/QUERY/VLM
          │          │
       KV / Vector / Graph / DocStatus
          │
     legacy/native/MinerU/Docling + LLM/Embedding/Rerank
```

`LightRAG` 通过 `_RoleLLMMixin`、`_StorageMigrationMixin`、`_PipelineMixin` 组合公共门面。异步入口包括 `ainsert`、`aquery`、`aquery_data`、`aquery_llm`、`ainsert_custom_kg`、`initialize_storages` 和 `finalize_storages`；同步入口由 `_run_sync` 驱动异步实现，并要求使用初始化 storage 的 owning event loop。E1：`lightrag/lightrag.py`。

两个入口不能混写：SDK `ainsert` 固定使用 F（fixed-token）分块；REST 文档入口使用 `apipeline_enqueue_documents` + `apipeline_process_enqueue_documents`，因此支持每文档 parser/chunk 选项和 F/R/V/P。E1：`lightrag/lightrag.py`、`lightrag/pipeline.py`。

初始化必须先 `await rag.initialize_storages()`。默认组合是 `JsonKVStorage`、`NanoVectorDBStorage`、`NetworkXStorage`、`JsonDocStatusStorage`。`finalize_storages()` 会逐个 finalize，单个 finalize 异常被记录后继续，最后仍可能把总体状态设为 `FINALIZED`；因此 `FINALIZED` 不是所有后端都已成功提交的证明。E1：`lightrag/lightrag.py`。

## 3. Ingest：事实写入、去重与状态

普通文档入队的事实顺序是：

```text
workspace enqueue_serialize 锁
  → basename/content_hash 去重
  → full_docs upsert + flush
  → doc_status=PENDING
  → 发布仅含 doc_id 的 document notification
```

通知不是任务事实，也不携带 status 快照。通知可以丢失、重复、过期或在容量满时被合并；下一轮严格读取 `doc_status` 才能恢复遗漏。入队时会冻结 `parse_engine`、`process_options` 和策略相关 `chunk_options`，后续运行时配置不会悄悄改变已入队文档的处理语义。E1：`lightrag/pipeline.py`、`lightrag/utils_pipeline.py`。

去重边界：basename 是强重复条件，content hash 允许跨文件名识别重复；重复尝试会产生 FAILED 记录供 track 查询，不进入正常处理链。该幂等性不是无限期 exactly-once：manual retry 的 terminal request id 只有有限 FIFO 窗口。E1/E2：`pipeline.py`、`tests/pipeline/test_pipeline_failed_retry_semantics.py`。

### 3.1 状态机

```text
PENDING → PARSING → ANALYZING（可选 VLM）→ PROCESSING → PROCESSED
                                      └──────────────→ FAILED
```

`PREPROCESSED` 仅为历史兼容状态。状态记录包含内容摘要/长度、规范化 `file_path`、状态和时间戳、`track_id`、chunk 信息、错误、metadata、content hash 以及多模态处理标记。

- 自动恢复：`PENDING`、`PROCESSING`、`PARSING`、`ANALYZING`。后 3 个表示进程可能在中途死亡。
- 显式恢复：`FAILED` 只能由 `/documents/scan` 或 `/documents/reprocess_failed` 发布的 manual retry 拉回 `PENDING`；同一次请求对失败文档最多给一次尝试。
- 状态真相：`doc_status`，不是 mailbox，也不是 `pipeline_status`。严格状态读取失败时应整体失败，不能静默跳过坏记录。

`doc_status` JSON 后端的单条 upsert 会立即提交，而普通 Json KV 往往等批次 `_insert_done()`；因此 status 存在只证明恢复锚点出现，不证明 full docs、chunks、graph、vectors 同批 durable。E1；远程后端的逐项 partial commit 为 U。

## 4. Chunk：解析、分块与溯源

Parser routing 支持 `legacy`、`native`、`mineru`、`docling`。环境规则按顺序匹配，文件名 hint 可覆盖单文件规则，例如 `paper.[mineru-iteP].pdf`、`memo.[native-R!].docx`、`notes.[-R].md`。`parse_engine` 与 chunk 选项会持久化到文档数据和 status metadata。E1/E3：`lightrag/parser/routing.py`、`docs/FileProcessingPipeline.md`。

处理选项：

| 选项 | 语义 |
|---|---|
| `i/t/e` | drawing/table/equation 的 sidecar/VLM 分析 |
| `!` | 跳过 entity/relation 抽取和图写入，但仍保存 chunk 向量 |
| `F` | fixed-token，SDK `ainsert` 的固定策略 |
| `R` | recursive-character，分隔符级联与 token 感知合并 |
| `V` | semantic-vector，embedding 断点；失败或过长时回退 |
| `P` | paragraph-semantic，依赖结构化 block/sidecar，缺失时回退 R |

Native parser 生成 LightRAG Document 和 sidecar，保留 heading、paragraph、table、drawing、equation 与 source span；`MinerU`、`Docling` 是外部服务边界。外部图片下载还涉及 SSRF、大小、重定向和缓存策略，不能只在架构图中写成普通本地解析。E1/E3：`lightrag/parser/`、`lightrag/sidecar/`、`docs/FileProcessingPipeline.md`。

## 5. Extraction：候选、恢复锚点与幂等归并

`extract_entities` 受角色 LLM 并发限制，支持文本和 JSON 输出、gleaning、JSON repair、记录上限和多模态 block 增强。LLM 输出是候选语义，不是权威事实。

`merge_nodes_and_edges` 的顺序是：

1. 将本次文档的 entity/relation 候选超集写入 `full_entities`/`full_relations` recovery anchors。
2. flush 两个 anchor；anchor upsert/flush 失败时停止，不继续改变图。
3. 按实体 key 和无向关系端点 key 使用 keyed lock 并发归并。
4. 合并描述、source tracking、关系权重，再写 Graph、Vector 和关联 KV。
5. 由 `wait_tasks_with_drain` 在任一子任务失败或等待器取消时 cancel 并等待兄弟任务终态。

同一 document/chunk/source identity 重试不能重复累加描述、tracking 或关系权重；相关回归包括 `tests/extraction/test_merge_description_dedup.py`、`test_edge_weight_reprocess.py`、`test_write_ahead_indexes.py`、`test_kg_recovery_primitives.py`。E2（当前核对未执行）。

图与向量不是跨后端事务。图先提交而向量 flush 失败时，代码抛 `VectorStorageConsistencyError`，恢复策略是以图为权威、停止服务并运行 `lightrag-rebuild-vdb`，不是假装完成 rollback。E1/E2：`lightrag/utils_graph.py`、`lightrag/tools/rebuild_vdb.py`。

## 6. KV、Graph、Vector、DocStatus

四类抽象都继承 `StorageNameSpace`，共同拥有 `initialize`、`finalize`、`drop`、`index_done_callback` 和 `drop_pending_index_ops` 生命周期/提交契约：

- `BaseKVStorage`：按 id 读取、过滤、upsert、delete。
- `BaseVectorStorage`：embedding、query、upsert、批量读取及实体/关系删除。
- `BaseGraphStorage`：节点/边读写、邻接、标签搜索、子图和批量接口。
- `DocStatusStorage`：状态过滤/统计、track 查询、分页和 basename/content hash 查询。

固定 namespace 包括 `full_docs`、`text_chunks`、`llm_response_cache`、`full_entities`、`full_relations`、`entity_chunks`、`relation_chunks`、`entities`、`relationships`、`chunks`、`chunk_entity_relation` 和 `doc_status`。workspace 通过文件目录、collection/index 前缀、数据库字段、payload 或图 label 隔离。E1：`lightrag/namespace.py`、`lightrag/base.py`。

`lightrag/kg/__init__.py` 的注册表声明合法实现和最小方法；`factory.py` 对四个默认后端直接导入，其余后端懒加载。注册表存在不等于 provider 已安装、连接可用或事务语义一致。可选后端包括 Redis、PostgreSQL/PGVector、MongoDB、Milvus、Qdrant、FAISS、Neo4j、Memgraph、OpenSearch 等，但每个后端的 flush、refresh、bulk partial failure 和 workspace 隔离均需单独验证。E1/U。

### 6.1 延迟向量提交与本地快照

以 `NanoVectorDBStorage` 为例：`upsert` 先进入 pending buffer；embedding 与 materialized index 更新发生在 `index_done_callback`。`get_by_id`/`get_vectors_by_ids` 可 read-your-writes，但 `query` 看不到未 flush 向量；embedding、数量或保存失败时 pending 应保留供重试。

文件型后端使用带 pid/tid 的兄弟 tmp 和 `os.replace`，读进程通过 update flag 触发全量 reload。Python 异常可保留旧快照；SIGKILL/OOM/断电可能留下 tmp，启动 reaper 延迟回收。真实强杀、断电、多进程写入和远程后端语义均为 U。

## 7. Query：唯一检索编排

查询公共编排点是 `kg_query` / `naive_query`，不是 API、SDK、WebUI 各自实现一条链：

```text
QueryParam
  → high/low keywords（已有关键词可跳过 KEYWORD LLM）
  → query/document embedding
  → 按 mode 查询 entity/relation/chunk
  → round-robin 去重、可选 rerank
  → entity/relation/chunk token 截断
  → source/reference/context
  → 可选 QUERY LLM 或结构化返回
```

模式：`local` 查实体及一跳关系，`global` 查关系及端点，`hybrid` 合并两者，`mix` 再加入 chunk vector，`naive` 只查 chunk vector，`bypass` 明确绕过检索直接调用 QUERY LLM。`aquery_data` 返回结构化 data/metadata/references；`aquery` 保持文本/流兼容；`aquery_llm` 返回检索数据和 LLM 结果。

查询 embedding 预计算异常可能只 warning 后继续，chunk vector 异常可能转为空候选；因此 API 的 `no_results` 不能自动解释为“索引正常”。诊断必须区分无结果、embedding/provider failure 和 graph/vector inconsistency。E1；真实 HTTP 可观测性为 U。

缓存 key 绑定 mode、query、预算、prompt、response format 和 role/binding/model/host identity；非法 keyword cache 回退 LLM，流式、空内容和截断响应不缓存。cache 是性能层，不能证明索引提交或知识事实。

## 8. Queue、取消、恢复与资源释放

`pipeline_ingress` 是 workspace 级三通道唤醒面，不是持久任务队列：

| 通道 | 语义 | 边界 |
|---|---|---|
| document | 仅 `doc_id`，允许丢失/重复/过期，依赖严格 status scan | 每 workspace 4096；溢出合并为 auto-rescan |
| auto-rescan | 单 bit 脏标记，由 supervisor 消费；查询失败必须重新 arm | 不是 document feeder 的 work predicate |
| manual retry | sticky FIFO，FAILED→PENDING 持久化后 ACK | terminal request id 4096 FIFO，有限窗口幂等 |

多进程由一个预 fork 的 Manager-side `PipelineIngressHub` 持有 workspace mailbox；worker 只持有 proxy。等待 RPC 单次最多 30 秒，客户端需循环。mailbox 随 Manager 生命周期保留，workspace clear 只清空不删除；大量短生命周期 workspace 会留下空 mailbox，属于已知生命周期风险。E1：`lightrag/kg/pipeline_ingress.py`。

取消 API `POST /documents/cancel_pipeline` 只是设置 `cancellation_requested`，不是同步终止。运行循环在锁内优先处理取消，停止接管新文档；parse/analyze/process worker 在边界检查并把队列项标为 FAILED，native parser bridge 收到取消事件，batch finally 取消并 drain worker。已完成文档保持 `PROCESSED`。未消费信号保留；已消费但未被 batch 接管的窗口会重新 arm auto-rescan。取消请求本身返回 `cancellation_requested` 或 `not_busy`，不能作为处理已完成证明。E1/E2：`document_routes.py`、`tests/pipeline/test_pipeline_cancellation.py`。

内部 storage-error abort 与用户取消不同：内部错误会清理仍在 buffer 的 index ops，留下需要修复存储后再运行的 halt/recovery 语义；普通 `FAILED` 不自动无限重试。`wait_tasks_with_drain` 只保证已交给它的 asyncio writer 收敛，不能替代 provider timeout 或进程级终止。

恢复也分三类：

1. 自动恢复：PENDING 和死进程中间状态。
2. manual retry：`/documents/scan` 还发现新文件并分类；`/documents/reprocess_failed` 只读 storage，不扫描输入目录。失败重试仍回 FAILED，等待下一次显式请求。
3. `POST /documents/recovery/force_reset`：要求 `confirm=true`，只清 `recovery_required`、reservation/busy/scanning 标志，不修复 custom chunks、delete、clear 的部分提交；它是 unsafe override，不是数据恢复。

角色化 `EXTRACT`、`KEYWORD`、`QUERY`、`VLM` 各自有 priority queue、`max_async`、timeout 和状态。异步热更新会 drain 旧队列，超时取消 pending future/worker；无 running loop 的同步更新只能告警并跳过确定性清理，不能宣称旧 provider 已释放。E1：`lightrag/llm_roles.py`。

## 9. API 契约与一致性风险

服务组装位于 `lightrag/api/lightrag_server.py`，默认文档端口为 `9621`、working dir 为 `./rag_storage`、input dir 为 `./inputs`；认证包括 API key/JWT，`/health` 保持最小存活信息。

- Query：`POST /query`、`POST /query/stream`、`POST /query/data`，支持上述 mode、token budget、rerank、历史和 references。
- Document：`/documents/scan`、`upload`、`text`、`texts`、`track_status/{track_id}`、`pipeline_status`、分页/状态统计、`reprocess_failed`、`cancel_pipeline`、`recovery/force_reset`、删除、清空和 cache 清理。
- Graph：标签列举/热门/搜索、子图、实体/关系创建编辑、实体合并和删除。图编辑受 pipeline reservation 约束，并需同步图、向量和索引路径。
- Ollama-compatible：`/api/*` 协议适配，不是第二套检索内核。

上传、文本插入返回 track id；文件 basename/content hash 冲突不会等价于成功。clear/delete 使用 destructive reservation；普通 `busy` 不单独阻止 enqueue，但 `destructive_busy`、`scanning_exclusive` 和 pending enqueue 会阻止冲突写入。reservation 释放必须 owner-checked、cancellation-resistant、幂等；managed background task 需要 start barrier/backstop 防止响应取消留下 busy 槽位。E1：`document_routes.py`、`shared_storage.py`。

核心一致性结论：四类 storage 没有跨后端两阶段提交。以下状态各自只能证明局部动作，不能证明全链路完成：`doc_status` 存在、mailbox ACK、`busy=False`、`FINALIZED`、单 storage flush、cache hit、空查询结果、`force_reset`。

## 10. 测试与文档一致性审计

定向回归面包括：

- ingest/status：`tests/pipeline/test_pipeline_failed_retry_semantics.py`、`test_pipeline_ingress_exit.py`、`test_pipeline_ingress_feed.py`、`test_doc_status_chunk_preservation.py`。
- cancellation/recovery：`tests/pipeline/test_pipeline_cancellation.py`、`test_pipeline_internal_abort.py`、`test_pipeline_release_closure.py`、`tests/kg/test_reservation_dead_process_recovery.py`。
- extraction/merge：`tests/extraction/test_write_ahead_indexes.py`、`test_kg_recovery_primitives.py`、`test_edge_weight_reprocess.py`、`test_merge_description_dedup.py`。
- chunk：`tests/chunker/` 下 F/R/V/P、overlap、长块、标题、sidecar backfill 和参数持久化测试。
- storage：`tests/kg/` 下 JSON、NetworkX、NanoVector、PostgreSQL、Redis、Memgraph 等后端和 deferred flush 测试。
- API/query：`tests/api/routes/`、`tests/api/config/` 下 query、stream、document chunk validation、graph busy、认证和路由配置测试。

文档冲突与修正：

1. 旧版根文档把第 19、20、21 节写成多轮补充，重复描述相同的 ingress、cancel/drain、延迟 embedding 和 graph-authoritative rebuild；本版合并为单一章节，避免“补充结论”与主结论漂移。
2. `pipeline_ingress` 不能称为普通持久队列；它是有界三通道唤醒面，真正事实在 `doc_status`。
3. `cancel_pipeline` 是异步请求，不是同步终止；返回成功不代表所有 worker 已退出。
4. `finalize_storages()` 的总体 `FINALIZED` 可能掩盖单 storage finalize 失败，不能写成全链路提交。
5. `STORAGES` 注册表和 provider 列表不能写成“全部默认可用”；实际连接、依赖、refresh 和事务语义必须按 provider 验证。
6. `BaseGraphStorage.search_labels` 是标签模糊搜索，不等于独立全文/BM25；当前 query 链没有被源码证明的独立全文 provider。OpenSearch 后端存在也不能改写成全文能力已通过。
7. 取消、恢复、重试、force reset 和 rebuild 不是同义词；尤其 force reset 不修复部分提交。

当前核对仍未验证：真实 Gunicorn/Manager worker SIGKILL 后重启恢复、断电/OOM 下 tmp reaper、远程后端 bulk partial failure/refresh/workspace 隔离、真实 provider timeout 与资源回收、图向量不一致后的完整 rebuild、API 对 embedding 异常空结果的可观测性、完整 pytest/前端测试、性能容量和安全扫描。

## 11. 结论

LightRAG 的可恢复骨架由以下事实组成：

1. ingest 先写事实，再发可丢唤醒；`doc_status` 是状态真相。
2. parser/chunk 选项按文档冻结，sidecar 保留多模态溯源。
3. extraction 先写 recovery anchors，再以 keyed lock 和 cancel/drain 归并。
4. KV、Graph、Vector、DocStatus 是可插拔存储边界，但不是跨后端原子事务。
5. query 由 `kg_query`/`naive_query` 统一编排，API/SDK/WebUI/Ollama 只是入口适配。
6. cancel 是可观察的异步终止请求；manual retry 是持久意图；force reset 只是危险围栏清除。
7. 延迟 embedding、graph-authoritative rebuild、有限 ingress 和有限 request-id 窗口必须在调用方文档中明确。

最重要的生产边界不是某个 provider，而是：认证与路径安全、workspace 单写者/reservation、flush/read-after-write 屏障、embedding fingerprint、失败与恢复证据，以及不把局部成功误报为全链路成功。

## 12. 主要证据索引

- 入口与生命周期：`lightrag/lightrag.py`、`lightrag/pipeline.py`。
- 存储契约与 namespace：`lightrag/base.py`、`lightrag/namespace.py`、`lightrag/kg/__init__.py`、`lightrag/kg/factory.py`。
- ingest/queue：`lightrag/kg/pipeline_ingress.py`、`lightrag/kg/shared_storage.py`、`lightrag/utils_pipeline.py`。
- extraction/query：`lightrag/operate.py`、`lightrag/utils.py`、`lightrag/utils_graph.py`。
- API：`lightrag/api/lightrag_server.py`、`lightrag/api/routers/document_routes.py`、`query_routes.py`、`graph_routes.py`。
- 处理说明：`docs/FileProcessingPipeline.md`、`docs/LightRAG-API-Server.md`、`docs/ParagraphSemanticChunking.md`。
- 定向测试：`tests/pipeline/`、`tests/extraction/`、`tests/chunker/`、`tests/kg/`、`tests/api/`。

## 13. 目录与交付物盘点（当前 checkout）

以下盘点来自 `rg --files`，用于防止把示例、部署脚本或 WebUI 误认成核心运行时：

| 区域 | 代表文件/目录 | 架构职责 | 证据 |
|---|---|---|---|
| 核心门面 | `lightrag/lightrag.py` | dataclass 配置、生命周期、同步兼容门面 | E1 |
| 编排 | `lightrag/operate.py` | 抽取、图查询、朴素查询、上下文构造 | E1 |
| 流水线 | `lightrag/pipeline.py`、`lightrag/utils_pipeline.py` | 入队、扫描、解析、分析、处理和状态更新 | E1 |
| 入口 API | `lightrag/api/lightrag_server.py` | FastAPI 应用组装、认证、静态 WebUI 和健康检查 | E1 |
| 文档路由 | `lightrag/api/routers/document_routes.py` | 上传、文本、扫描、追踪、删除、取消、恢复 | E1 |
| 查询路由 | `lightrag/api/routers/query_routes.py` | 普通、流式、结构化 query | E1 |
| 图路由 | `lightrag/api/routers/graph_routes.py` | 标签、子图、节点边编辑、合并删除 | E1 |
| 存储抽象 | `lightrag/base.py` | KV、Vector、Graph、状态和 embedding 接口 | E1 |
| 存储工厂 | `lightrag/kg/factory.py`、`lightrag/kg/__init__.py` | 默认实现和懒加载 provider 注册 | E1 |
| 并发协调 | `lightrag/kg/shared_storage.py`、`pipeline_ingress.py` | workspace 锁、reservation、mailbox | E1 |
| 解析器 | `lightrag/parser/`、`lightrag/sidecar/` | legacy/native/MinerU/Docling 和旁车数据 | E1/E3 |
| 角色 LLM | `lightrag/llm.py`、`lightrag/llm_roles.py` | EXTRACT/KEYWORD/QUERY/VLM 队列和 provider | E1 |
| 迁移与工具 | `lightrag/tools/` | storage 迁移、rebuild-vdb、诊断 CLI | E1 |
| WebUI | `lightrag_webui/src/` | API 类型、上传、状态和图可视化 | E1 |
| 测试 | `tests/` | 按 pipeline/extraction/chunker/kg/api 等分域回归 | E2 |
| 文档 | `docs/`、`README*.md` | 部署、API、解析和分块说明 | E3 |
| 部署 | `Dockerfile*`、`docker-compose*`、`k8s-deploy/` | 镜像、外部数据库和 Kubernetes | E3 |

根目录同时包含 `pyproject.toml`、`setup.py`、`uv.lock`、多套 offline requirements、`Makefile`、`scripts/test.sh` 和 Docker/K8s 制品。依赖锁和 compose 文件是版本事实；不能仅依据 README 的安装命令推断 provider 已可运行。

## 14. 真实调用链 file:line 索引

### 14.1 SDK 插入链

1. `LightRAG.insert` 在 `lightrag/lightrag.py:1736-1772` 做同步包装，实际转向 `ainsert`。
2. `LightRAG.ainsert` 在 `lightrag/lightrag.py:1774-1842` 校验输入、生成 `doc_id`/tracking 并调用内部插入管线。
3. 自定义 chunk 入口为 `insert_custom_chunks`/`ainsert_custom_chunks`（`lightrag/lightrag.py:1844-1935`），绕过 parser 但仍需要向量和文档状态语义。
4. 自定义知识图谱入口为 `insert_custom_kg`/`ainsert_custom_kg`（`lightrag/lightrag.py:3454-3578`），直接接收 entities/relationships，仍要经过 workspace 和存储生命周期。
5. 初始化和关闭在 `lightrag/lightrag.py:1568-1668`；任何 SDK 示例缺失 `initialize_storages` 都是不完整运行契约。

### 14.2 文档流水线链

1. `lightrag/api/routers/document_routes.py:约 5526` 的 `insert_text` 接收单文本并返回 tracking。
2. 同文件 `约 5658` 的 `insert_texts` 批量创建 tracking，容量和重复判断在入队层执行。
3. `/documents/scan` 和 `/documents/reprocess_failed` 的处理入口在同路由的 scan/retry handlers；前者访问 input 目录，后者仅依据状态 storage。
4. `lightrag/pipeline.py` 将解析器、chunker、sidecar、抽取器和写入器串联；`utils_pipeline.py` 保存状态转换和失败原因。
5. `lightrag/kg/pipeline_ingress.py:503` 的 `PipelineIngressHub` 只唤醒 supervisor；它不保存全文、不承诺 exactly-once。
6. worker 每个阶段都检查 cancellation event；取消后的 document item 在边界处变为 FAILED，并由状态扫描决定是否再次接管。

### 14.3 查询链

1. `query_routes.py:447-733` 的 `query_text` 负责认证、参数限制、调用 `rag.aquery` 并转换 HTTP 响应。
2. `query_routes.py:736-1307` 的 `query_text_stream` 使用异步迭代器，客户端取消只取消响应消费，不等同 provider 已释放。
3. `query_routes.py:1309-` 的 `query_data` 走结构化结果，不复用文本拼接作为内部真相。
4. `lightrag/lightrag.py:3896-3951` 的 `query/aquery` 是兼容包装，真正完整结果在 `aquery_llm`。
5. `lightrag/lightrag.py:3978-4182` 的 `aquery_data` 负责 retrieval data、metadata、references。
6. `lightrag/lightrag.py:4184-4330` 的 `aquery_llm` 负责 role LLM 调用、bypass、流式和 response format。
7. `lightrag/operate.py:4504-6456` 的 `kg_query` 负责 local/global/hybrid/mix 检索、去重、rerank 和 token 截断。
8. `lightrag/operate.py:6458-` 的 `naive_query` 只查 chunk vector，不应被描述成知识图谱查询。

### 14.4 API 与 WebUI 链

1. `lightrag/api/lightrag_server.py:2468` 注册根路由，`2525` 注册 login，`2601` 开始健康/配置相关路由。
2. 应用将 `document_routes`、`query_routes`、`graph_routes` 和 Ollama-compatible router 组合；协议适配层调用同一 `LightRAG` 门面。
3. WebUI `lightrag_webui/src/api/lightrag.ts:362-368` 创建 axios 基址和 JSON headers，`370-` 管理 token 刷新；它不持有检索状态。
4. WebUI `lightrag_webui/src/api/lightrag.ts:534-570` 调用图标签和 `/health`，`572-` 调用 documents；API 类型明确暴露 queue、pipeline、workspace 和 keyed lock 状态。
5. `StatusCard.tsx:16-` 按 `extract/keyword/query/vlm` 展示角色队列；展示数据来自 `/health`，不是本地猜测。

## 15. 组件边界与扩展约束

### 15.1 Parser 与 chunker

- `lightrag/parser/routing.py` 将环境、文件名 hint 和显式 API 选项归一化；同一文档的 parser 选择在入队时冻结。
- `lightrag/chunker/` 维护 F/R/V/P 四种策略；semantic-vector 依赖 embedding 断点，失败回退必须保留策略元数据，避免重试改变 chunk identity。
- `lightrag/parser/external/mineru/` 和 `docling/` 使用 HTTP 外部边界；客户端应限制 endpoint、重定向、响应大小和轮询次数。
- `lightrag/sidecar/` 的 sidecar 是溯源输入，不是可无条件信任的最终实体；VLM 失败时必须能回退纯文本处理。

### 15.2 Storage provider

| 类型 | 默认实现 | 可选实现举例 | 需要独立验证的语义 |
|---|---|---|---|
| KV | `json_kv_impl.py` | Redis、Postgres、Mongo | flush、批量失败、workspace 前缀 |
| Vector | `nano_vector_db_impl.py` | Qdrant、Milvus、FAISS、PGVector | 维度、refresh、read-your-writes |
| Graph | `networkx_impl.py` | Neo4j、Memgraph、OpenSearch | 节点边原子性、标签隔离 |
| DocStatus | `json_doc_status_impl.py` | Redis、Postgres 等 | 单条 upsert durability、分页一致性 |

provider 工厂的懒加载避免未安装依赖在 import 阶段崩溃，但会把错误推迟到初始化；部署检查必须显式 import、连接、写入、读取、删除和 finalize。对于远程 provider，bulk 成功响应不代表每一条记录成功，必须读取 partial failure 明细。

### 15.3 LLM、embedding、rerank

- `lightrag/llm.py` 暴露 provider 适配函数；`llm_roles.py` 以角色分离 queue、timeout、priority 和运行状态。
- `MAX_ASYNC_LLM`、`MAX_ASYNC_EMBEDDING`、`MAX_ASYNC_RERANK` 是并发上限，不是总吞吐保证；provider 自身连接池可能形成第二层限制。
- role 热更新需要 drain 旧 queue；配置写成功而旧 worker 仍运行时，健康状态必须报告迁移中。
- embedding 维度、模型名、前缀和归一化方式构成 index identity；变化后应阻断增量写入并要求 rebuild/migration。
- rerank 只在检索候选之后改变排序；rerank timeout 不能回滚已写入的 graph/vector。

## 16. 并发、锁与资源释放检查表

| 资源 | 获取点 | 释放点 | 当前判断 |
|---|---|---|---|
| workspace reservation | `shared_storage.py` reservation helpers | owner-checked finally | E1；需进程杀验证 |
| keyed entity/edge lock | `utils_graph.py` merge path | context manager finally | E1 |
| pipeline mailbox | `pipeline_ingress.py` hub | manager 生命周期/clear | E1；空 mailbox 会累积 |
| LLM queue slot | `llm_roles.py` submit/worker | completion/cancel drain | E1 |
| vector pending buffer | NanoVector `upsert` | `index_done_callback` | E1；失败保留待重试 |
| temp snapshot | JSON storage save | `os.replace`/reaper | E1；SIGKILL 仍 U |
| HTTP response stream | query stream route | client disconnect/finally | E1；真实断连 U |
| external parser task | MinerU/Docling poll | cancel/timeout/finally | E1；供应商语义 U |

资源风险不是“有 finally 就已解决”：finally 可能在进程强杀、解释器终止、provider 卡死或 event loop 销毁时不执行。生产部署必须配合 watchdog、超时、幂等重扫和外部连接池回收。

## 17. 权限、路径和安全边界

- API key/JWT 校验位于 API 依赖层；健康路由仍需确认是否暴露工作目录、provider 名称和 queue 计数。
- input/working directory 必须做 canonical path 校验；basename/content hash 去重不能代替路径穿越防护。
- 外部 parser URL 允许配置时应拒绝 loopback、link-local 和内部 DNS 解析结果，除非部署策略显式允许。
- graph label、entity id、document id 来自请求时必须限制长度和字符集，避免日志、SQL、图查询和文件名注入。
- 错误响应应返回稳定 error code 和可操作说明，不能把 provider 原始 token、URL、SQL、绝对路径或密钥回显到客户端。
- WebUI token 刷新要限制并发、重试次数和失效窗口；axios 拦截器的刷新锁只解决客户端竞态，不解决服务端撤销。

## 18. 部署与运维证据

- `Dockerfile`、`Dockerfile.lite`、`Dockerfile.postgres` 区分完整、轻量和 PostgreSQL 组合；镜像并不自动证明外部 embedding/LLM 可达。
- `docker-compose.yml` 和 `docker-compose-full.yml` 声明 Redis/Postgres/Qdrant/Neo4j 等组合；生产必须固定版本和持久卷，避免 `latest` 漂移。
- `k8s-deploy/lightrag/templates/deployment.yaml`、`service.yaml`、`pvc.yaml` 描述服务、卷和探针；应核对 readiness 是否等待 storage 初始化完成。
- `k8s-deploy/databases/` 的脚本负责数据库安装与卸载，属于运维层，不是 LightRAG 事务保证。
- `lightrag.service.example` 和 `docker-entrypoint.sh` 是启动样板；真实部署还需核对 worker 数、Manager/fork 关系和 graceful shutdown 超时。
- 端口默认 `9621`，本次审计未启动服务；任何运行态验证应使用独立端口 4780，避免碰撞平台 MCP 端口。

## 19. 测试覆盖矩阵与证据边界

| 风险主题 | 代表测试 | 本次状态 |
|---|---|---|
| failed retry 一次性语义 | `tests/pipeline/test_pipeline_failed_retry_semantics.py` | 文件存在，未执行 |
| mailbox 溢出和退出 | `tests/pipeline/test_pipeline_ingress_exit.py`、`feed.py` | 文件存在，未执行 |
| cancel/drain | `tests/pipeline/test_pipeline_cancellation.py` | 文件存在，未执行 |
| graph/vector recovery | `tests/extraction/test_write_ahead_indexes.py`、`tests/kg/test_kg_recovery_primitives.py` | 文件存在，未执行 |
| chunk F/R/V/P | `tests/chunker/` | 目录存在，未执行 |
| provider dimension | `tests/llm/test_dimension_mismatch.py` | 文件存在，未执行 |
| API stream | `tests/api/routes/test_query_stream_routes.py` | 文件存在，未执行 |
| auth/path | `tests/api/auth/test_whitelist_path_prefix.py` | 文件存在，未执行 |
| error sanitization | `tests/api/test_error_message_sanitization.py` | 文件存在，未执行 |
| workspace isolation | `tests/workspace/test_workspace_migration_isolation.py` | 文件存在，未执行 |

“文件存在”仅是 E2 的测试意图证据，不是通过证据。未安装依赖和未配置 provider 时，不能把 import、收集或静态 grep 当运行成功。

## 20. 剩余风险清单（按优先级）

1. **高**：跨 KV/Graph/Vector/DocStatus 没有统一事务；需在业务层暴露 partial commit 和 rebuild 状态。
2. **高**：外部 parser 和 LLM provider 的 timeout、断连、重试和计费边界需真实注入验证。
3. **高**：workspace reservation、Manager mailbox 和多 worker graceful shutdown 需 SIGTERM/SIGKILL 双路径验证。
4. **高**：embedding identity 变化若未阻断，可能产生静默的向量维度或语义混库。
5. **中**：健康接口包含较多运行配置，生产需确认脱敏和最小暴露。
6. **中**：有限 terminal request-id 窗口不能提供无限 exactly-once；客户端必须保存 tracking 和状态结果。
7. **中**：空查询结果与 embedding failure 的响应区分不足，需增加 provider error telemetry。
8. **中**：图编辑、删除、clear 与流水线并发时的 reservation 竞争需要长时间压力测试。
9. **低**：WebUI 类型与后端新增字段可能短暂漂移，应在 CI 运行生成/契约检查。
10. **低**：文档中仍有英文 provider 名称和协议字段，这是外部契约保留，不应翻译成业务别名。

## 21. 审计交付元数据

- 源码仓库：`/Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/55_knowledge_graph_rag/LightRAG`。
- 审计 HEAD：`ddecea9e`（`git log -1 --oneline`，2026-08-22 本地核对）。
- 源码文件规模：`rg --files` 可见核心 Python、TypeScript、部署、文档和测试文件；完整清单留在 checkout，本文只保留架构相关索引。
- 文档唯一写入：`/Users/hekunhua/Documents/Agent/PHP/系统工程平台/开发文档/源码参考研究/项目/30_多模态与媒体分析/55_knowledge_graph_rag/LightRAG/ARCHITECTURE.md`。
- 代码仓库中的未跟踪 `.codegraph/` 和 `ARCHITECTURE.md` 未纳入平台文档修改；本审计未在源码仓库写入任何文件。
- MCP 证据：`project_context` 返回项目根为华世王镞_v3，`codeexplore` 返回同一错绑根目录并以错误码 `TOOL_EXECUTION_ERROR` 结束；两者不用于 LightRAG 事实。
- 验证命令：本次只执行 `git status`、`git log`、`wc -l`、`rg --files`、`rg -n` 和文档静态检查；未运行 pytest、服务、Docker、K8s 或 provider。
- 结论状态：源码静态事实已整理；运行态、性能、强杀、远程后端和安全扫描仍为 U。

## 22. 关键配置与默认值索引

配置字段由 `LightRAG` dataclass 和环境变量共同决定，以下只列会改变架构语义的字段：

| 配置 | 作用 | 失败/漂移后果 | 证据 |
|---|---|---|---|
| `WORKING_DIR` | KV、vector、graph、status 文件根目录 | 误指向旧 workspace 造成数据混用 | `lightrag/lightrag.py:392-500` |
| `INPUT_DIR` | scan 和上传默认目录 | 路径越界或扫描遗漏 | `document_routes.py` |
| `KV_STORAGE` | KV provider 名称 | provider 懒加载失败 | `kg/factory.py` |
| `VECTOR_STORAGE` | vector provider | 维度/刷新语义改变 | `kg/factory.py` |
| `GRAPH_STORAGE` | graph provider | 图事务、标签能力改变 | `kg/factory.py` |
| `DOC_STATUS_STORAGE` | 状态 provider | 恢复锚点丢失或分页不一致 | `kg/factory.py` |
| `MAX_ASYNC_LLM` | 默认 LLM 并发 | provider 限流、内存放大 | `lightrag.py:688-770` |
| `MAX_ASYNC_EMBEDDING` | embedding 并发 | 请求堆积、batch 超时 | `lightrag.py:659-684` |
| `EMBEDDING_BATCH_NUM` | embedding batch | 单批过大导致 OOM | `lightrag.py:659-662` |
| `LLM_TIMEOUT` | role LLM 超时 | 取消和重试边界改变 | `llm_roles.py` |
| `EMBEDDING_TIMEOUT` | embedding 超时 | pending index ops 保留 | `lightrag.py:684-686` |
| `RERANK_TIMEOUT` | rerank 超时 | 候选不排序但不回滚检索 | `lightrag.py:771-781` |
| `COSINE_THRESHOLD` | 向量候选阈值 | 结果数量与 no_results 变化 | `operate.py` |
| `MIN_RERANK_SCORE` | rerank 过滤阈值 | 过高造成空上下文 | `lightrag.py:778-781` |
| `MAX_PENDING_DOCUMENTS` | ingress/status 待处理上限 | 溢出转 rescan 或拒绝 | `lightrag.py:876-880` |
| `PIPELINE_REQUIRE_STRICT_STORAGE_READS` | 严格 status 读取 | false 可能静默跳过坏记录 | `lightrag.py:857-863` |
| `VLM_PROCESS_ENABLE` | sidecar VLM 总开关 | 多模态块回退纯文本 | `lightrag.py:795-799` |
| `PARSER_ROUTING` | parser 路由规则 | 文档语义与 chunk identity 改变 | `parser/routing.py` |

环境变量加载通常在 import/dataclass 默认值阶段发生；改变 `.env` 后必须重启所有 worker，不能只刷新 WebUI。多 worker 环境下配置热更新还需核对旧 queue 是否 drain。

## 23. 失败语义与客户端动作

| 失败位置 | 可观察信号 | 客户端动作 | 不应做的假设 |
|---|---|---|---|
| parser HTTP | track FAILED、error 字段 | 修 parser/重试 | 认为文档已入图 |
| chunk semantic embedding | fallback metadata 或 FAILED | 检查 embedding provider | 认为语义 chunk 一定生效 |
| entity extraction | extraction error/partial anchors | inspect recovery anchors | 认为 LLM 输出是事实 |
| graph write | reservation/graph error | rebuild 或人工核对 | 认为 vector 同步完成 |
| vector flush | pending ops/consistency error | graph-authoritative rebuild | 直接重新 query |
| doc status upsert | status storage error | 停止恢复扫描并修 provider | 依据 mailbox 推断状态 |
| queue overflow | auto-rescan bit | 等待 supervisor scan | 认为每个 doc 通知都存在 |
| cancellation | `cancellation_requested` | 轮询 track/status | 把 HTTP 200 当作 worker 已停 |
| stream disconnect | client close | 等待 server finally/timeout | 认为 provider 已取消 |
| auth failure | 401/403 稳定错误码 | refresh token 或重新登录 | 重试无限次 |
| force reset | `recovery_required` 清除 | 先备份再 rebuild | 当作数据修复完成 |

错误处理应该保留 `track_id`、`doc_id`、`workspace`、provider role 和可重试标志；只返回自然语言错误会让运维无法区分 provider failure 与业务 no-result。

## 24. 版本与兼容性边界

- Python 包版本以 `lightrag/__init__.py`/发布脚本和当前 checkout 为准；本文记录的 `1.5.5` 不代表远端最新版本。
- API `0321` 与核心版本独立；前端 `LightragStatus` 同时暴露两者，客户端应按 capability 判断 `/docs`、stream 和 graph API。
- `aquery` 保留旧文本/流式返回，`aquery_data`、`aquery_llm` 是新结构化入口；调用方迁移时不能把字典直接当字符串。
- parser hint 格式（例如 `[mineru-iteP]`）属于文档处理协议；未知 flag 应拒绝或显式回退并写入 metadata。
- storage namespace、workspace 前缀和 embedding fingerprint 属于持久数据协议；升级 provider 前需要迁移脚本和回滚指针。
- `force_reset`、rebuild-vdb 和 migration 是运维命令，不属于普通 query/insert API；权限应比读写接口更严格。

## 25. 复核命令清单（未执行项）

以下命令是后续运行态复核入口，本次不执行以避免未安装依赖或外部 provider 造成误判：

```text
cd /Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/55_knowledge_graph_rag/LightRAG
python -m pytest tests/pipeline/test_pipeline_cancellation.py -q
python -m pytest tests/extraction/test_write_ahead_indexes.py -q
python -m pytest tests/api/routes/test_query_stream_routes.py -q
python -m pytest tests/api/auth/test_whitelist_path_prefix.py -q
python -m pytest tests/workspace/test_workspace_migration_isolation.py -q
python -m lightrag.api.lightrag_server --port 4780
curl -fsS http://127.0.0.1:4780/health
```

运行前应固定 Python、依赖锁、工作目录、临时数据库和 provider endpoint 指纹；测试产生的 storage、日志和外部数据库必须使用独立临时目录。真实 server 验证要在测试完成后清理进程和端口，不能把开发实例当平台 MCP。

## 26. 最终审计判定

本次交付满足“单一 ARCHITECTURE.md、顶部流程图、全量模块盘点、真实调用链、并发/资源/失败/恢复、测试部署和剩余风险”的静态源码审计范围。源码未改动，所有结论均绑定当前 checkout 的文件和行号或明确标注 E3/U。

MCP 项目错绑是本次工具链缺陷而非 LightRAG 事实：project_context 返回 `/Users/hekunhua/Documents/Agent/PHP/华世王镞_v3`，代码地图摘要也显示该项目 2,055 个文件；因此没有将其文件、索引或验证证据混入本文。LightRAG 仓库此前存在未跟踪 `.codegraph/` 与 `ARCHITECTURE.md`，本次没有修改或删除，平台文档是唯一写入目标。

在依赖、服务和外部 provider 未就绪前，本文不声称“测试通过”“接口可用”“断电可恢复”“性能达标”或“安全已通过”。下一阶段只需按第 25 节命令在隔离环境执行定向验证，再将成功退出码和环境指纹追加到平台项目证据，而无需创建第二份架构文档。

## 27. 快速导航：事实到源码

| 事实 | 主要源码锚点 |
|---|---|
| 门面类与配置 | `lightrag/lightrag.py:389-950` |
| storage 初始化 | `lightrag/lightrag.py:1568-1668` |
| SDK insert | `lightrag/lightrag.py:1736-1842` |
| custom chunks | `lightrag/lightrag.py:1844-1935` |
| custom KG | `lightrag/lightrag.py:3454-3578` |
| sync query | `lightrag/lightrag.py:3896-3918` |
| async query | `lightrag/lightrag.py:3920-3951` |
| structured query | `lightrag/lightrag.py:3978-4182` |
| query + LLM | `lightrag/lightrag.py:4184-4330` |
| KG query | `lightrag/operate.py:4504-6456` |
| naive query | `lightrag/operate.py:6458-` |
| ingress hub | `lightrag/kg/pipeline_ingress.py:503-` |
| document text API | `lightrag/api/routers/document_routes.py:5526-5750` |
| query API | `lightrag/api/routers/query_routes.py:447-1400` |
| app assembly | `lightrag/api/lightrag_server.py:2400-3000` |
| role queue | `lightrag/llm_roles.py` |
| graph merge | `lightrag/utils_graph.py` |
| parser routing | `lightrag/parser/routing.py` |
| Docling constants | `lightrag/parser/external/docling/client.py:74-90` |
| WebUI status type | `lightrag_webui/src/api/lightrag.ts:56-157` |
| WebUI graph calls | `lightrag_webui/src/api/lightrag.ts:534-570` |
| pipeline retry tests | `tests/pipeline/` |
| extraction recovery tests | `tests/extraction/` |
| provider tests | `tests/kg/` |
| API security tests | `tests/api/auth/`、`tests/api/test_error_message_sanitization.py` |

这张表是导航索引，不替代源码；行号随未来远程更新可能变化，更新 checkout 后应重新核对并在文档元数据中记录新的 commit。
