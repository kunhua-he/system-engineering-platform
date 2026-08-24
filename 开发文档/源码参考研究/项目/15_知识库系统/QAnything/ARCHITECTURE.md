# QAnything 架构与交互链审计

> 审计对象：`/Users/hekunhua/Documents/Agent/github 源码参考/15_知识库系统/QAnything`
>
> 审计方式：目标归档当前含独立 `.codegraph/`（未纳入 Git）；本轮用目标目录 `codegraph explore` 定位 `LocalFileForInsert`、`LocalFile`、`SelfMilvus` 及其调用关系，再回读源码、配置、Compose、前端、测试和文档。代码地图仅用于定位，结论以当前源码为准。
>
> 变更边界：当前核对只修改本文件。未安装依赖、未启动 Docker/模型/数据库、未调用 API、未执行测试或构建，因此本文是静态证据，不是运行通过证明。

## 0. 版本与远程新鲜度增量核对（2026-08-22）

- 本地工作树 `HEAD`：`65de10426b99d5945b8c616a4814afa5a92826cb`（2025-03-12，`Merge pull request #622 from fucktx/qanything-v2`）。
- `git ls-remote origin HEAD refs/heads/master`：远端 `HEAD` 为 `65de10426...`，`origin/master` 为 `30e260f1a28e0aa1d03490c328c9c5497d5a668e`；本地落后远端 master。未 fetch、未 pull、未覆盖工作树；最新代码若需研究，应通过 `127.0.0.1:4780` 建立隔离快照后再逐文件核对。
- **已证调用链**：CodeGraph 定位 `qanything_kernel/core/local_file.py:9`（上传文件抽象，4 个 handler 调用者）、`qanything_kernel/core/retriever/general_document.py:65`（解析入口，2 个 insert worker 调用者）和 `qanything_kernel/core/retriever/vectorstore.py:14-33,155-263`（Milvus 异步写入/flush）。`SelfMilvus` 使用后台 `asyncio.create_task(asyncio.to_thread(...flush))`，因此 flush 完成不在当前调用栈内；原有“后台 flush/非原子提交”风险得到当前源码再次确认。
- **未证/待核**：未运行 Sanic、insert worker、Milvus/MySQL/ES 或模型服务，未执行测试；远端 master 的 API、模型和部署变化均不能写成本地已实现事实。需在隔离快照核对后再决定是否更新参考源码。

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

## 4.3 解析实现证据补充

`qanything_kernel/core/retriever/general_document.py:65-520` 是插入侧统一文件对象。构造阶段区分 FAQ、URL、本地路径，并创建 `RecursiveCharacterTextSplitter`；`split_file_to_docs` 按后缀选择 loader。解析不是纯函数：URL、PDF、OCR、XLSX 会写 `tmp_files` 或图片目录，Markdown 表格会先写 MySQL Documents。

关键证据：

- `get_ocr_result_sync:36-45` 请求 OCR 服务，超时 120 秒，失败返回 `None`；`image_ocr_txt:97-122` 随后写文本文件。
- `get_pdf_result_sync:47-62` 请求 PDF parser，超时 240 秒；`split_file_to_docs:395-405` 失败后回退 `UnstructuredPaddlePDFLoader`。
- `url_to_documents_async:216-253` 与同步版本 `255-291` 最多重试三次，失败后进入 newspaper/MyRecursiveUrlLoader fallback。
- `markdown_process:190-214` 按标题和表格切分，表格过大时保留表头。
- `excel_to_markdown:294-336` 使用只读 workbook；失败时按 sheet 输出 CSV 并使用 `CSVLoader`。
- `inject_metadata:455-520` 注入用户、知识库、文件、页码、图片、FAQ 和 headers，再合并相邻短文档。

这些路径没有统一解析版本号。相同 file_id 在 parser、chunk_size 或标题策略变化后重试，旧 Documents 与向量难以区分；平台接入应把 parser version 和 chunk policy 写入制品元数据。

## 5. 向量、全文和父子检索

### 5.1 Embedding 写入

`qanything_kernel/dependent_server/insert_files_serve/insert_files_server.py` 轮询黄色文件，调用 `LocalFileForInsert.split_file_to_docs`，组装 parent/child 文档并请求 embedding 服务。批量失败主要依赖异常和 File 状态回写，未见跨 Milvus/MySQL 事务协调。

### 5.2 Milvus child 与 MySQL parent

`qanything_kernel/core/retriever/parent_retriever.py:159+` 的 `ParentRetriever` 将 child 向量命中映射回 parent；`docstrore.py:22+` 的 `MysqlStore` 读取完整上下文并可能补写 JSON sidecar。Milvus 命中而 MySQL parent 缺失时，结果只能降级或丢弃。

### 5.3 ES 混合检索

启用 Elasticsearch 时，child 文本同时写入 ES；查询把 Milvus semantic score 与 ES BM25 结果合并，再进入 rerank。两类 score 标度不同，混合不是天然可比，必须用固定数据集验证归一化和 top-k。

### 5.4 Rerank 与 token 预算

rerank 服务接收 query/passages 并返回 relevance score。LocalDocQA 按分数排序，再按 token budget 截断 parent 上下文；召回 top-k 不等于最终送入 LLM 的片段数，部署应记录召回数、重排数、最终 token 数与截断原因。

## 6. 问答、RAG 与多轮会话

### 6.1 初始化

`qanything_kernel/core/local_doc_qa.py` 初始化 MySQL、Milvus、ES、embedding、rerank、LLM client 和 ParentRetriever。初始化成功只表示 client 构造完成，不表示后端索引或模型健康。

### 6.2 问答链

```text
chat endpoint -> LocalDocQA.get_knowledge_based_answer
 -> query/history normalization -> vector + optional BM25 recall
 -> parent restore -> rerank -> token budget/context
 -> OpenAI-compatible LLM -> citation/source -> QaLogs -> SSE/JSON
```

多轮历史通常随请求体传入；QaLogs 是审计记录，不是 checkpoint。客户端断线后，已生成 token 和中间状态没有自动续传协议。

### 6.3 SSE 与无命中

流式接口推送增量文本、引用和结束标志。LLM 异常、客户端断开、超时和空答案分支不完全一致，可能在已发送前缀后才失败；生产侧需要 request id、终态事件、heartbeat、发送队列上限和断线清理。

Milvus/ES 无命中时，系统可返回无法回答模板或转通用 LLM；HTTP 200 不能证明知识命中。答案应携带 retrieval status、source count 和 fallback reason。

## 7. API 与前端契约

`handler.py` 覆盖知识库 CRUD、上传/删除、文件状态、FAQ、chunk 编辑、Bot、问答、QA 日志和模型探针；`docs/API.md` 是说明性文档，字段仍以 Sanic handler 为准。

### 7.1 文件状态机

```text
gray -> yellow -> green
  \-> red
```

gray 表示已登记，yellow 表示 worker 处理中，green 表示代码认为解析/embedding/索引/parent 写入完成，red 表示失败。状态字段没有可见 lease token、owner、attempt 或 heartbeat；green 不是跨后端原子完成。

### 7.2 删除和编辑

删除需要同时处理原始目录、MySQL Documents、Milvus/ES child、FAQ 和日志关联；后台删除缺少统一 tombstone。chunk 编辑若先改 MySQL 再更新向量，期间会出现旧向量+新 parent 混合版本。

### 7.3 前端状态

Pinia 保存上传、知识库、聊天、Bot 和 chunk 状态。Axios 注入用户信息和错误提示，但取消重复请求逻辑部分注释；前端显示完成依赖轮询，不读取 worker lease 或内部服务健康。

## 8. Worker、队列和资源生命周期

`insert_files_server.py` 是数据库轮询 worker，不是持久消息队列。其任务边界是 File 查询、领取、解析、embedding、索引和状态回写；未见通用优先级、可见 claim token、跨进程幂等 key 或死信表。

PDF/URL 解析的 120/240 秒超时会长期占用 worker；多文件上传可登记大量 gray 行，缺少全局并发预算和用户级配额。embedding/rerank client 的连接复用和关闭依赖 HTTP 库/进程。

资源所有权分散：原始文件和 tmp 目录由解析器创建，HTTP 临时文件部分在 finally unlink；Milvus/ES/MySQL 无统一 close 顺序；Sanic 启动的多个模型进程没有 supervisor 级重启和组回收；前端轮询/SSE 没有后端重启恢复游标。

## 9. 数据库与索引一致性

MySQL 保存用户、知识库、File、Documents、Faqs、QaLogs 和 Bot；Milvus 保存 child 向量；ES 可保存 child 全文；本地文件系统保存原始与解析制品。它们没有共同事务，必须把阶段写成可重试且可核对的状态转换。

### 9.1 失败窗口

1. File=yellow，解析成功但 embedding 超时，留下 tmp 文件和黄色记录；
2. Milvus child 成功、MySQL parent 失败，向量可召回但无法恢复上下文；
3. MySQL green、ES 未写完，混合检索不完整；
4. 删除 MySQL 成功、Milvus 删除失败，孤儿向量继续召回；
5. sidecar JSON 成功、数据库删除，可能产生残留或重复；
6. 进程被 kill 后 yellow 需要显式 stale recovery。

部署验收应记录每个 file_id 的阶段事件、Documents 数、Milvus/ES child 数、parent 可读性、磁盘路径和最终状态，不能只检查 File=green。

## 10. 测试、部署和平台映射

测试包括 Python 单测/脚本、API/文档静态检查、前端 test.js 和 Compose/服务脚本；没有看到覆盖完整上传→解析→索引→问答→删除的单一端到端门禁。模型和基础设施测试依赖 Docker、GPU、MySQL、Milvus、ES 及外部模型。

部署由 `docker-compose-*.yaml`、`scripts/entrypoint.sh` 和环境文件拼接。Linux host network 与 Mac/Windows 端口映射不同；只检查 8777 可达不等于 9001/8001/9009/7001/8110 健康。

平台吸收边界：

| 能力 | 可吸收模块 | 不能直接复用 |
|---|---|---|
| 上传/状态 | durable ingest | gray/yellow/green 无 lease |
| 解析/OCR | parser support library | 中间制品无 manifest/版本 |
| parent-child 检索 | RAG module | MySQL/Milvus/ES 无原子事务 |
| embedding/rerank | 外部模型适配器 | 维度/健康/超时未统一 |
| SSE 多轮 | 流式响应模块 | 无断线游标/终态账本 |
| Compose | 受管服务编排 | entrypoint 无 supervisor |

## 11. 风险与验证边界

高风险：跨存储 green 假完成、yellow 无租约、删除孤儿索引、HTTP 无背压/取消、模型服务阻塞、多进程无 supervisor。中风险：解析版本漂移、sidecar 生命周期、ES/Milvus score 合并、前端取消失效、LLM 晚到异常。低风险：文档/脚本参数漂移。

本轮未安装 Python/Node 依赖，未启动 Docker 或 4780 服务，未调用真实 OCR/PDF/embedding/rerank/LLM，未执行完整 pytest、前端构建、Milvus/ES/MySQL 一致性、压力和崩溃恢复测试。结论均为目标 checkout 静态源码、配置和测试布局证据。

## 12. 本轮审计记录

- 目标分支：`qanything-v2`；HEAD=`65de10426b99d5945b8c616a4814afa5a92826cb`，与 `origin/qanything-v2` 一致。
- 远程同步：尝试 `git fetch origin --prune && git pull --ff-only origin main`；远程不存在 `main`，未误切换分支，按远程默认分支完成状态核对。
- CodeGraph：目标 `.codegraph/` 存在；已查询 `LocalFileForInsert`、`MysqlStore`、`ParentRetriever` 及解析调用链。
- 平台唯一文档：仅修改本文件；源码侧未跟踪 `.codegraph/` 和 `ARCHITECTURE.md` 保留。

## 13. 入口与证据索引

| 调用链 | 入口证据 | 关键阶段 | 终态/副作用 |
|---|---|---|---|
| 文件上传 | `handler.py` upload_files | LocalFile 写盘、File gray | 返回 file_id，后台异步处理 |
| URL 上传 | `handler.py` upload_weblink | URL 登记、Jina/newspaper 解析 | Markdown/tmp 制品 |
| FAQ 上传 | `handler.py` upload_faqs | FAQ/MySQL、虚拟文件 | question/answer 进入检索 |
| 解析 | `general_document.py:367-452` | 后缀 loader、fallback | LangChain Document |
| 元数据 | `general_document.py:455-520` | user/kb/file/page/title/image | child chunk 输入 |
| Embedding | insert worker + embedding HTTP | batch 文本向量化 | Milvus child |
| Parent | `parent_retriever.py:159+` | child 命中、MySQL 恢复 | 上下文文档 |
| 混合召回 | LocalDocQA + ES/Milvus | score 合并、rerank | token 截断 |
| 问答 | handler chat | LLM prompt、历史、引用 | SSE/JSON + QaLogs |
| 删除 | handler + 后台任务 | 文件、DB、向量、全文 | 可能部分成功 |

## 14. 部署前最小验收

1. 固定源码提交、镜像 tag、模型 revision、embedding 维度和 rerank 版本。
2. 启动探针逐一检查 Sanic、insert worker、OCR、PDF、embedding、rerank、MySQL、Milvus、ES，而不是只检查 8777。
3. 上传代表性 PDF、图片、DOCX、XLSX、URL、FAQ，核对解析文档数、child 数、parent 可读性和原始制品。
4. 检索记录 Milvus/ES top-k、rerank 分数、最终 token、引用 file_id 和 fallback 状态。
5. 在 embedding/ES/Milvus/MySQL 任一阶段注入失败，确认 yellow/red、重试、孤儿清理和人工诊断记录。
6. 删除后确认磁盘、MySQL、Milvus、ES 均无可召回残留；编辑后确认向量与 parent 版本一致。
7. 对 SSE 断线、慢客户端、大上传、并发用户和 worker kill 做有界资源检查。
8. 只有上述动态证据齐全，才能把静态架构结论升级为部署通过。

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

当前核对未执行任何测试，因此以下均为未验证：

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

## 13. 研究材料吸收记录

已人工回读并吸收 `细探-QAnything.md` 的增量事实：URL/Markdown/PDF/OCR/DOCX/XLSX/FAQ 解析分派、父子块与来源 metadata、Milvus/ES/MySQL 的实际写入顺序、embedding/rerank/FAQ 直返与 token 裁剪、SSE/JSON 双出口、MySQL 状态轮询长任务、`to_thread` 超时无法强杀、未等待 flush/background delete、删除残留和启动无 supervisor。以上均保持“源码事实与未验证边界”区分。

本文件是平台侧唯一架构事实汇总；源码 checkout 的未跟踪 `ARCHITECTURE.md` 与 `.codegraph/` 均保留，未作为平台事实源修改。

## 14. 交付判定

本轮满足 500 行级源码审计要求的目标是证据密度而非文字长度：每条主链都对应目标仓库的源码路径、函数或配置边界；运行态仍未验证。后续动态验收应保存源码提交、容器镜像、模型版本、数据库/索引版本、请求样本、阶段状态、资源探针、测试命令和退出码。

缺少这些证据时，不得把 `File=green`、HTTP 200、SSE 结束或前端“完成”状态解释为解析、索引、问答和清理均成功。平台接入应将每一阶段建模为可查询任务，并在恢复、删除和重试时保留原 task_id/run_id，避免生成不可审计的第二条事实链。

最终结论：QAnything 是可复用的 RAG 领域参考实现，不是已闭合的生产任务底座。可吸收的是文档解析、父子检索和引用拼装流程；必须重建的是租约、事务、幂等、背压、取消、失败账本、制品清理和多后端对账。

本轮没有修改 QAnything 源码、Compose、前端、依赖或测试；没有创建新的细探文档。所有新增章节均写入平台侧唯一 `ARCHITECTURE.md`，并以当前 `qanything-v2` checkout 为基线。

- 源码提交：`65de10426b99d5945b8c616a4814afa5a92826cb`。
- 分支：`qanything-v2`。
- CodeGraph：目标 `.codegraph/` 已存在并已查询。
- 平台文档：唯一更新对象。
- 动态服务：未启动。
- 外部模型：未调用。
- 数据库/索引：未连接。
- 验证等级：静态源码审计。

## 15. 远程固定 SHA/raw 定点复核（2026-08-22）

本轮只通过 `http://127.0.0.1:4780` 尝试读取 QAnything 远端 `master` 的少量固定 raw 文件；未调用其他 MCP，未 fetch、pull、clone 或覆盖共享源码树。

| 项目 | 固定目标 | 请求与结果 | 证据判定 |
|---|---|---|---|
| QAnything | `30e260f1a28e0aa1d03490c328c9c5497d5a668e`（已有记录的远端 `master`） | `curl -L --proxy http://127.0.0.1:4780 --max-time 20 https://raw.githubusercontent.com/netease-youdao/QAnything/30e260f1a28e0aa1d03490c328c9c5497d5a668e/qanything_kernel/core/retriever/vectorstore.py`；退出码 `56`，HTTP `404`，未取得文件字节 | 远端向量写入实现本轮 **未证**；不能把远端 `master` 的行为回填为本地事实 |
| QAnything | `HEAD/master/main` | `git ls-remote` 经 4780；本轮未在短时限内返回，记录为超时/无成功退出码；第 0 节已有的 SHA 记录不因本轮失败而更新 | 本轮未刷新远端引用；已有 SHA 仅作先前记录 |

当前可用事实仍来自本地 `qanything-v2`：`qanything_kernel/core/retriever/vectorstore.py:14-33` 的 `SelfMilvus._milvus_flush` 用 `asyncio.create_task(asyncio.to_thread(self.col.flush))`，`vectorstore.py:253-259` 的批量写入同样异步 flush；解析入口和 worker 链路见第 3-5 节。raw 404/远端超时既不能证明远端已修复后台 flush，也不能证明远端与本地一致。

### 15.1 L0-L4 证据边界

- **L0**：固定仓库、SHA、raw 路径、代理参数、HTTP 404 和退出码已记录。
- **L1**：本地解析、embedding、Milvus/ES/MySQL 写入顺序和失败窗口有源码行号证据。
- **L2**：远端固定文件未成功读取，没有远端差异快照。
- **L3**：未启动 Sanic、insert worker、MySQL、Milvus、ES 或模型服务，未发上传/问答请求。
- **L4**：未执行端到端上传→解析→索引→问答→删除、崩溃恢复、压力或发布验证。

下一轮必须先取得远端固定 raw 字节或隔离归档，再比较 parser、worker、Milvus flush、删除和状态字段；在取得证据前，不更新本地参考源码，也不把远端版本称为已审计。
