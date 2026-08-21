# LightRAG 架构事实与一致性审计

> 本文是本地 checkout 的架构事实入口。源码标识、配置键、接口路径和测试文件名保留原文；结论按“实现已确认 / 有定向测试断言但本轮未执行 / 未验证”区分。本文只修改文档，不代表服务、远程后端或测试已运行。

## 1. 范围、基线与证据

- 项目：LightRAG（仓库 `HKUDS/LightRAG`），本地版本 `lightrag.__version__ = 1.5.5`，API 版本 `0321`。
- 根目录：`~/Documents/Agent/github 源码参考/30_多模态与媒体分析/55_knowledge_graph_rag/LightRAG`。
- 研究范围：`ingest → chunk → extraction → KV/Graph/Vector/DocStatus → query → queue → API → tests → docs`。
- 本轮未使用 MCP/Hermes；目标仓库没有 `.codegraph` 索引，已先行确认 CodeGraph 不可用，未自行初始化索引。
- 本轮未安装依赖、启动服务、构建前端或运行测试。测试文件只证明存在回归意图，不证明通过。

证据等级：

- **E1**：实现、异常路径或源码注释直接确认。
- **E2**：实现与定向测试共同覆盖，但本轮未执行。
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

同一 document/chunk/source identity 重试不能重复累加描述、tracking 或关系权重；相关回归包括 `tests/extraction/test_merge_description_dedup.py`、`test_edge_weight_reprocess.py`、`test_write_ahead_indexes.py`、`test_kg_recovery_primitives.py`。E2（本轮未执行）。

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

本轮仍未验证：真实 Gunicorn/Manager worker SIGKILL 后重启恢复、断电/OOM 下 tmp reaper、远程后端 bulk partial failure/refresh/workspace 隔离、真实 provider timeout 与资源回收、图向量不一致后的完整 rebuild、API 对 embedding 异常空结果的可观测性、完整 pytest/前端测试、性能容量和安全扫描。

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
