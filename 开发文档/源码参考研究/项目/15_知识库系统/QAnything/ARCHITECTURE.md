# QAnything 架构与交互链审计

> 审计对象：`~/Documents/Agent/github 源码参考/15_知识库系统/QAnything`
>
> 审计方式：CodeGraph 首次尝试后发现目标仓库没有 `.codegraph/` 索引；未初始化索引，改用源码、配置、Compose、前端、测试和文档的分段静态读取。
>
> 变更边界：本轮只修改本文件。未安装依赖、未启动 Docker/模型/数据库、未调用 API、未执行测试或构建，因此本文是静态证据，不是运行通过证明。

## 1. 一句话结论

QAnything 是一个由 Vue 3 前端、Sanic HTTP API、MySQL 状态/元数据、Milvus 向量索引、可选 Elasticsearch BM25 索引以及同一容器内多个模型/解析进程组成的本地知识库 RAG 系统。

当前可由源码确认的主链是：

```text
前端/API
  -> Sanic handler
  -> LocalFile 写原始文件并登记 MySQL File(gray)
  -> insert_files worker 轮询并领取 File(yellow)
  -> LocalFileForInsert 解析为 Document
  -> metadata 注入、标题/表格处理、短片段合并
  -> parent/child 分块
  -> embedding HTTP 服务
  -> Milvus child 写入
  -> 可选 Elasticsearch child 写入
  -> MySQL Documents parent 写入
  -> File(green)
  -> Milvus child 召回、MySQL parent 恢复、可选 ES 混合召回
  -> rerank、token 预算、OpenAI-compatible LLM
  -> SSE/JSON、溯源和 QaLogs
```

这条链路的主要架构风险不是组件缺失，而是提交和生命周期边界没有闭合：`green` 不是跨后端原子完成；`yellow` 没有租约和重启恢复；超时取消不能停止同步线程或后台 flush；删除和清理是未追踪的后台任务；LLM 异常会伪装成正常答案。

## 2. 组件与运行拓扑

### 2.1 请求面

- `qanything_kernel/qanything_server/sanic_api.py` 创建 Sanic 应用，默认监听 `8777`，映射静态前端到 `/qanything/`，在启动钩子中创建 `LocalDocQA`。
- `handler.py` 实现知识库、上传、文件状态、删除、chunk 编辑、Bot、QA 日志、重排和问答接口。
- `GET /api/health_check` 只返回 `{"code": 200, "msg": "success"}`，不检查 MySQL、Milvus、ES、模型服务或 worker。
- 请求体上限为 128 MB；用户标识会拼接为 `user_id__user_info`。

### 2.2 前端

`front_end/` 是 Vue 3 + TypeScript + Vite 应用，使用 Pinia、Vue Router、Ant Design Vue 和 Axios。`src/services/urlConfig.ts` 将前端动作映射到 `/local_doc_qa/*` API，store 管理用户、知识库、上传、聊天、Bot 和 chunk 状态。

前端取消语义需要特别区分：

- Axios interceptor 具备取消重复请求的代码，但真正注册取消回调的部分被注释，不能视为可靠的重复请求取消机制。
- `browerQuene.ts` 的排队实现未接入默认导出，且 `watings` 初始化为对象却调用 `push`/`length`，不能视为有效的浏览器请求队列。
- `urlConfig.clearUpload` 名称描述为取消知识库所有文件上传，实际调用 `/local_doc_qa/clean_files_by_status`；后端只按 `gray/red/yellow` 清理数据库记录，不取消当前解析、embedding、索引或模型调用。

### 2.3 后端与依赖服务

`LocalDocQA.init_cfg` 同时创建 embedding client、rerank client、MySQL manager、Milvus client、ES client 和 `ParentRetriever`。重型能力位于 `dependent_server/`：

| 进程 | 默认端口 | 调用 | 主要职责 |
|---|---:|---|---|
| embedding server | 9001 | `POST /embedding` | 文本批量向量化 |
| rerank server | 8001 | `POST /rerank` | query/passages 重排 |
| PDF parser | 9009 | `POST /pdfparser` | PDF 转 Markdown |
| OCR server | 7001 | `POST /ocr` | 图片转文字 |
| insert files | 8110 | 无业务任务 API | 轮询 MySQL 并执行解析/入库 |
| Sanic API | 8777 | `/api/*` | 控制面、QA 和静态前端 |

`scripts/entrypoint.sh` 使用 `nohup` 启动上述六个进程，保存 PID 到临时生成的 `close.sh`，只通过主日志出现 `Starting worker` 判定启动完成。没有 supervisor、逐服务健康检查、进程组回收或运行中自动重启证据。

### 2.4 基础设施

三份 Compose 文件编排 MySQL 8.4、Elasticsearch 8.13.2、Milvus 2.4.8、etcd、MinIO 和 `qanything_local` 镜像。Mac/Windows 暴露 API `8777`、Milvus `19540`、MySQL `3316`、ES `9210`；Linux 使用 host network。Compose 的 healthcheck 只覆盖部分基础设施，不覆盖 QAnything 内部模型服务和 insert worker。

## 3. 上传到制品的完整链路

### 3.1 三种入口

| 入口 | handler 行为 | 初始状态 |
|---|---|---|
| `upload_files` | multipart 文件名清理、同名策略、文件数/字符数检查；`LocalFile` 写二进制 | `File=gray` |
| `upload_weblink` | 校验 `http` 前缀、URL 最大 2048 字符，登记 URL 和标题 | `File=gray` |
| `upload_faqs` | JSON 或 Excel FAQ 转 question/answer/nos_keys，写 `Faqs` 和虚拟 `.faq` 文件 | `File=gray` |

HTTP 返回 `code=200` 只代表登记成功。响应没有独立 `task_id`，客户端主要依靠 `file_id` 和文件列表中的状态跟踪后台处理。

### 3.2 原始与中间制品

- 二进制原始文件：`QANY_DB/content/<user_id>/<kb_id>/<file_id>/<file_name>`。
- URL：登记 `file_url`，worker 后续在文件目录的 `tmp_files` 下写 Markdown。
- FAQ：问题/答案主要存在 MySQL `Faqs`，`LocalFile` 不保存二进制。
- PDF：PDF parser 返回 Markdown 路径，随后复制解析目录中的 JPG 到 `dist/qanything/assets/file_images/<file_id>`。
- 图片：OCR 返回的行拼接后写入 `tmp_files/<filename>.txt`。
- XLSX：首选写 Markdown 表格；fallback 会为 sheet 写 CSV。
- 表格：`markdown_process` 可能把完整表格先以随机 `table_doc_id` 写入 `Documents`，再切成多个片段。
- parent sidecar：`MysqlStore.mget` 在缺少本地 JSON 时补写 `<file_name>_<doc_index>.json`。

这些制品没有统一 manifest、版本、owner、保留策略或 run 级清理器。失败、取消、重复重试或宿主崩溃可能留下中间文件、图片、sidecar 或数据库辅助文档。

## 4. 解析、规范化与分块

### 4.1 解析分派

`LocalFileForInsert.split_file_to_docs` 按来源和后缀分派：

| 输入 | 首选路径 | fallback/失败 |
|---|---|---|
| URL | `r.jina.ai` 转 Markdown，最多 3 次、单次约 30 秒 | `newspaper` 120 秒，再 `MyRecursiveUrlLoader` |
| Markdown | Markdown 标题树 parser | `UnstructuredFileLoader` |
| TXT | UTF-8、ISO-8859-1、Windows-1252 | 全部失败返回空列表 |
| PDF | PDF parser HTTP，返回 Markdown | `UnstructuredPaddlePDFLoader` |
| JPG/PNG/JPEG | OCR HTTP，再 `TextLoader` | 异常由外层标红 |
| DOCX | `UnstructuredWordDocumentLoader` | `docx2txt` |
| XLSX | 每个 sheet 转 Markdown 表格 | Pandas 转 CSV 后 `CSVLoader` |
| PPTX/EML/JSON/CSV | 对应 loader | 没有同等粒度 fallback |
| FAQ | MySQL 读取 question/answer | 不经过普通文件 loader |

README 中提到的 `.doc` 未在当前分派器中看到独立分支，不能把文档宣传口径直接当作实现事实。

### 4.2 metadata 与短片段合并

`inject_metadata` 将 loader 输出重新包装为 LangChain `Document`，注入 `user_id`、`kb_id`、`file_id`、`file_name`、`nos_key`、`file_url`、标题、表格、图片、页码、FAQ 和 headers。随后按 `min(400, chunk_size / 2)` 的 child 上限合并相邻短文档，并删除重复标题。

### 4.3 parent/child

- 默认 parent 为 800 tokens，child 为 400 tokens，child overlap 为约 100 tokens。
- 含表格或不超过 parent 大小的文档可以直接成为 parent，否则使用零 overlap 的 parent splitter。
- parent ID 为 `<file_id>_<parent_index>`。
- child metadata 保存 parent ID；`[headers](...)` 被前置到 child 和 parent 文本。
- 发往 embedding 的副本会删除标题列表、表格标志、图片、文件名、NOS key、FAQ 和页码等字段。
- `parent_chunk_size` 改变时，运行时重建 splitter，child 大小为 `min(400, parent/2)`。

这不是版本化的 `DocumentEnvelope`/`ChunkEnvelope` 契约，而是共享 metadata 字段的隐式约定。

## 5. Embedding、索引和可见性

### 5.1 embedding

`YouDaoEmbeddings` 调用 `POST http://localhost:9001/embedding`，输入 `{texts: [...]}`，输出向量列表，模型版本写入 metadata。异步客户端按批创建 `aiohttp.ClientSession` 并 `gather`，没有显式请求 timeout；任一批次异常可能使整个批次失败。

### 5.2 实际写入顺序

```text
child 文本 embedding
  -> Milvus Collection.insert，每批最多 1000
  -> create_task(to_thread(collection.flush))，不等待
  -> 可选 ES BM25 child 写入，异常只记录
  -> MySQL Documents 逐 parent 写入
  -> worker 将 File 写为 green
```

| 数据面 | 保存内容 | ID/过滤 | 当前一致性 |
|---|---|---|---|
| MySQL | File、KnowledgeBase、Documents、Faqs、QaLogs、Bot | parent `doc_id` 为业务 ID | parent 逐条提交，无批次事务 |
| Milvus | child 向量和 metadata | `kb_id` partition；Milvus `auto_id=True` | flush 未 await、未绑定 run |
| Elasticsearch | child 文本 BM25 | ES child ID 为 `file_id_<child_index>` | 写入异常被吞掉 |

`green` 只说明 `insert_documents` 返回，没有 commit marker、generation、index version 或跨后端可见性检查。Milvus 成功、ES 或 MySQL 失败时不会回滚已写向量，也没有向 API 投影 partial 状态。

另有一个字段风险：`update_chunks_number()` 实际更新了 `File.chunk_size`，而 `process_data` 随后又更新 `chunks_number`。删除 ES 时读取 `chunk_size` 作为 child 数量，导致配置大小和实际数量可能混淆。

## 6. 检索与问答

### 6.1 检索

问答只纳入 `File.status == green` 的文件，最多 20 个知识库，`top_k` 最大 100。检索顺序：

1. Milvus 召回 child。
2. 按 child metadata 中的 parent ID 去重。
3. `MysqlStore.amget` 恢复 parent，score 写回 parent。
4. `hybrid_search=true` 时追加 ES BM25，只补充 Milvus 未命中的 parent。
5. 删除文件在 QA 侧用 MySQL 状态过滤。
6. Milvus 空结果时重建 client 并重试一次。

ES 异常会退化为 Milvus 结果，但响应没有统一 `degraded_sources` 或证据等级字段。索引删除完成也不是检索过滤完成的同义词。

### 6.2 问题改写、重排和上下文

- 有历史时调用 `RewriteQuestionChain`；token 超过 `4096-256` 时从最早历史开始裁剪，改写失败回退原问题。
- rerank 只在候选多于 1 且问题 token 不超过 300 时调用，低于 `0.28` 的结果过滤；主 QA 链 rerank 异常只记录并继续。
- FAQ 评分至少 0.9 时优先保留 FAQ；问题清洗后完全相等时直接返回 FAQ answer，不经过常规 LLM 生成。
- token 可用量为 context window 减去输出、余量、问题、历史、模板和引用字段；文档按来源文件顺序装入，超限即停止。
- `prepare_source_documents` 第一行直接返回，下面的 aggregate/fallback 代码不可达，不能宣称按文件聚合已生效。

### 6.3 模型与响应

`OpenAILLM` 使用 OpenAI-compatible Chat Completions，配置来自请求或 Bot：`api_base`、`api_key`、model、context length、max token、top_p、temperature。响应支持 JSON 和 SSE delta，正常结束发送 `[DONE]`，随后写 `QaLogs`。

当前失败语义不可靠：`_call` 捕获任意异常后把异常文本作为 `answer`，`finally` 仍发送 `[DONE]`；handler 按正常完成路径返回 `code=200` 并写日志。未发现显式 LLM timeout、provider cancel、客户端断线终态或 `failed/partial/cancelled/timed_out` 字段。初始化日志还直接打印 API key。

## 7. 队列、失败、取消、恢复

### 7.1 队列事实

后端没有独立消息队列。所谓队列是 MySQL `File` 表加 `insert_files_server.check_and_process` 轮询：按 `id % workers` 分片，按 timestamp 取最早 `gray`，先提交 `yellow` 再处理，成功 `green`，业务失败 `red`。

没有 `task_id`、ack、lease owner、heartbeat、attempt、priority、deadline、cancel token 或启动恢复扫描。worker 在提交 `yellow` 后崩溃，文件可能永久停留在 `yellow`。

### 7.2 失败矩阵

| 场景 | 当前行为 | 未闭合点 |
|---|---|---|
| URL 失败 | Jina 重试后 fallback newspaper/递归 loader | deadline 由多层常量拼接，无统一错误码 |
| PDF/OCR 不可用 | HTTP 异常后 PDF fallback；OCR 异常返回空/抛错 | 中间制品和模型资源无 run 清理 |
| 解析超时 | `wait_for(to_thread(...), 300)`，设置 Event，标红 | 不能强制终止同步线程，Event 未证明被消费 |
| Milvus 插入超时 | 尝试按 file_id 删除 Milvus，标红 | ES、Documents、未等待 flush 可能残留 |
| ES 写入/检索失败 | 记录日志并继续 | 没有降级字段，可能仍标绿 |
| rerank 失败 | 主链继续；专用接口可 embedding cosine fallback | 失败策略未进入统一结果契约 |
| LLM 异常 | 异常文本作为答案并 `[DONE]` | 错误伪装成功，无法区分失败/部分输出 |
| 删除文件/知识库 | MySQL/本地目录同步，Milvus/ES `create_task` 后立即返回 | 不 await、不重试、不对账 |
| 清理 gray/red/yellow | 主要软删除 MySQL 记录 | 索引、parent、图片可能残留 |
| SSE 断开 | 未发现客户端断开到 provider 的取消传播 | 模型、连接、日志终态未闭合 |
| 进程退出 | `close.sh` 普通 kill 已知 PID | 无进程组、reaper、孤儿任务恢复 |

## 8. 资源生命周期审计

| 资源 | 创建者 | 释放现状 | 风险 |
|---|---|---|---|
| 原始文件目录 | `LocalFile` | 删除接口尝试 `rmtree` | 失败和孤儿制品无统一扫描 |
| Markdown/OCR/CSV/图片/temp | parser/loader | 部分长期保留 | 无 manifest 和保留策略 |
| MySQL pool | insert worker | `after_server_stop` 关闭 | 强杀、连接断开、yellow 恢复未处理 |
| embedding/rerank session | connector | 局部创建，依赖上下文退出 | 无统一 timeout/取消 owner |
| Milvus insert/flush | vectorstore | flush 异步 task | task 未追踪，可能跨请求继续运行 |
| ES client/index documents | ES connector | 异常多为日志 | 删除完成不可确认 |
| LLM client/stream | `OpenAILLM`/Sanic ResponseStream | 正常路径结束 SSE | close、断线取消和异常终态未证明 |
| 线程/进程/GPU | `to_thread`、Sanic、nohup | `close.sh` kill PID | 无 process group、残留检查、自动重启 |

## 9. HTTP 交互面与文档漂移

### 9.1 Sanic 实际注册路由

`sanic_api.py` 注册：

```text
GET  /api/docs
GET  /api/health_check
POST /api/local_doc_qa/new_knowledge_base
POST /api/local_doc_qa/upload_files
POST /api/local_doc_qa/upload_weblink
POST /api/local_doc_qa/upload_faqs
POST /api/local_doc_qa/local_doc_chat
POST /api/local_doc_qa/list_knowledge_base
POST /api/local_doc_qa/list_files
POST /api/local_doc_qa/get_total_status
POST /api/local_doc_qa/clean_files_by_status
POST /api/local_doc_qa/delete_files
POST /api/local_doc_qa/delete_knowledge_base
POST /api/local_doc_qa/rename_knowledge_base
POST /api/local_doc_qa/get_doc_completed
POST /api/local_doc_qa/get_qa_info
POST /api/local_doc_qa/get_user_id
POST /api/local_doc_qa/get_doc
POST /api/local_doc_qa/get_rerank_results
POST /api/local_doc_qa/get_user_status
POST /api/local_doc_qa/get_random_qa
POST /api/local_doc_qa/get_related_qa
POST /api/local_doc_qa/new_bot
POST /api/local_doc_qa/delete_bot
POST /api/local_doc_qa/update_bot
POST /api/local_doc_qa/get_bot_info
POST /api/local_doc_qa/update_chunks
POST /api/local_doc_qa/get_file_base64
```

### 9.2 文档可读性与漂移

- `docs/API.md` 提供参数、示例和响应，但部分示例注释不是严格 JSON，且示例字段与实现存在历史差异；应以 `sanic_api.py` 和 handler 为运行时事实源。
- `README.md`/`README_zh.md` 适合部署和能力概览，但“支持格式”“双通道”“离线”和“上传成功”等宣传语不能替代状态、fallback 和失败语义。
- `细探-QAnything.md` 是研究笔记，不是第二份权威架构文档；其“独立扩缩”“FAISS/Milvus 同时主用”等表述未被当前主链证明。
- 本文件按“源码事实 / 未验证 / 架构缺口”区分，避免把目标设计、脚本样例或静态存在写成运行能力。

## 10. 测试与证据边界

仓库未发现可识别的后端 `pytest`/`unittest` 回归套件。根 `test/` 只有 `test.json` 样本和 `test_result.txt` 结果文本。`scripts/test_embed.py`、`scripts/test_rerank.py`、`local_chat_qa.py`、`multi_local_chat_qa.py`、`stream_chat.py` 和 `upload_files.py` 是依赖真实模型/服务的脚本，不是已通过的自动化测试。

`front_end/package.json` 的 `test` 命令是 `vite build --mode test`，不是单元测试 runner；根 `front_end/test.js` 也不是端到端测试入口。

本轮未执行任何测试，因此以下均为未验证：

- 格式解析、表格切分和 parent/child 边界。
- embedding 维度、批量并发和模型服务错误处理。
- Milvus/ES/MySQL 写入、删除、重建和一致性。
- 检索质量、rerank 阈值、FAQ 直通和 token 预算。
- SSE、LLM 错误、断线、取消和 QA 日志终态。
- 队列压力、worker 崩溃、重启恢复、制品清理和资源归零。

## 11. 复用裁决与最小补齐清单

### 可复用的领域语义

- 多格式解析后统一为带标题、表格、图片和来源 metadata 的文档。
- parent/child 检索：child 负责召回，parent 负责上下文恢复。
- Milvus、ES、MySQL 的职责分离。
- token window 预算与溯源 metadata。
- PDF/OCR/embedding/rerank 进程隔离的部署形态。

### 不应直接复用为可靠基础设施的行为

- 用 MySQL `File.status` 轮询替代任务队列。
- 用 `green` 表示跨后端提交完成。
- 用 `asyncio.wait_for(to_thread(...))` 代表同步工作已取消。
- 未等待的 Milvus flush 和后台删除 task。
- 把模型异常转换成正常答案。
- 用 PID 脚本而非 supervisor 管理多进程。
- 没有制品 manifest、租约、重试和孤儿清理。

### 最小补齐顺序

1. 为每次上传、解析、索引、删除和问答建立 `task_id/run_id`、阶段记录、owner、attempt、deadline、heartbeat 和明确终态。
2. 将 parser、chunker、embedding、vector index、lexical index、parent store 和 QA 输出定义为版本化制品契约。
3. 为 Milvus/ES/MySQL 建立幂等写入、commit marker、可见性检查、补偿删除、重建和对账。
4. 使用可取消的进程/子进程 worker 管理解析、模型和索引工作；不要把 coroutine cancellation 当成线程终止。
5. 让删除、重试、取消和恢复成为可查询任务；启动时扫描过期 lease 和孤儿制品。
6. 让 SSE 显式区分 `success`、`partial`、`failed`、`cancelled`、`timed_out`，禁止把异常文本当答案。
7. 增加不依赖外部服务的纯逻辑测试，再增加受控 mock provider、三后端集成和故障注入测试。
8. 将 `health_check`、API 文档和前端动作名称与实际依赖、状态和取消语义同步。

## 12. 最终审计结论

QAnything 已实现一条可导航的 RAG 领域链：上传登记、异步解析、多格式归一化、两级分块、embedding、Milvus/可选 ES 索引、MySQL parent 恢复、混合检索、重排、token 预算、OpenAI-compatible QA、SSE/JSON 和溯源日志。

但源码尚不足以证明它具备可靠的任务系统。失败、取消、恢复、删除完成、跨后端一致性、模型超时、SSE 断线、制品回收和服务自动恢复都存在未闭合边界。本文将这些边界明确记录为审计结果，未把任何未执行的运行验证或目标架构写成现状能力。

## 13. 施工材料吸收记录

已人工回读并吸收 `细探-QAnything.md` 的增量事实：URL/Markdown/PDF/OCR/DOCX/XLSX/FAQ 解析分派、父子块与来源 metadata、Milvus/ES/MySQL 的实际写入顺序、embedding/rerank/FAQ 直返与 token 裁剪、SSE/JSON 双出口、MySQL 状态轮询长任务、`to_thread` 超时无法强杀、未等待 flush/background delete、删除残留和启动无 supervisor。以上均保持“源码事实与未验证边界”区分。
