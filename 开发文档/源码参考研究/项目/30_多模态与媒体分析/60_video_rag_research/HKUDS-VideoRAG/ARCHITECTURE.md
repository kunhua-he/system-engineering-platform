# HKUDS-VideoRAG 架构事实档案

> 本文件是目标仓库唯一的正式架构文档。它记录当前本地源码快照中**已实现、仅声明、未验证**的边界，不是实现计划，也不把 README/论文宣传当成运行事实。
>
> **旧细探吸收声明**：`细探-HKUDS-VideoRAG.md` 已逐条对照源码并吸收到本文件；按任务要求保留旧文件，不删除、不再把它当第二个权威事实源。后续架构维护只更新本文件，旧文件仅作为历史线索。

## 1. 研究边界、证据与快照

### 1.1 目标身份

| 项目 | 事实 |
|---|---|
| 目标根目录 | `/Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/60_video_rag_research/HKUDS-VideoRAG` |
| 研究对象 | `VideoRAG-algorithm/` 研究算法 + `Vimo-desktop/` Electron/React 桌面原型及其 Python 后端 |
| Git 分支 / HEAD | `main` / `c412a093a820ef7a0e0dda31076ed871136198b3` |
| HEAD 提交 | `docs: upload results`（2026-03-18 16:33:03 +08:00） |
| 工作树 | `ARCHITECTURE.md`、`细探-HKUDS-VideoRAG.md` 为未跟踪文档；源码、配置、依赖未修改 |
| 现场文件盘点 | 排除 `.git/` 后 120 个文件：Python 51、TypeScript 19、TSX 22、JSON 5、Markdown 5、PNG 6，以及 CSS/HTML/Notebook/Shell/YAML 等 |
| 代码图 | 目标根及父路径没有 `.codegraph/`；`codegraph_explore` 明确返回未索引，不能冒充有代码图证据 |

### 1.2 当前核对 MCP 记录

- **用户指定专属 MCP**：`system_engineering_toolkit`，HTTP `127.0.0.1:8766/mcp/`。
- **当前核对实际 MCP 实例/工具命名空间**：`project_toolkit`（调用结果中返回的 `MCP实例`；工具名为 `mcp__project_toolkit__...`）。
- **开工 `project_context` 结果**：绑定到 `华世王镞_v3`，根目录为 `/Users/hekunhua/Documents/Agent/PHP/华世王镞_v3`，与本任务目标根不一致；因此该上下文不能作为本仓库身份或源码证据，已如实记录，未绕过伪装成目标项目。
- 随后的目标路径 `codegraph_explore` 结果：`isn't indexed with codegraph (no .codegraph/ directory found walking up from it)`；本档案改用本地只读文件读取与静态检查。

### 1.3 证据等级约定

| 等级 | 含义 | 本项目判定方式 |
|---|---|---|
| L0 | 仅有 README、论文、注释或接口声明 | 只能说明意图，不能说明闭环 |
| L1 | 当前源码中存在实现路径 | 函数/路由/存储调用已定位，但未证明可运行 |
| L2 | 当前核对静态检查通过 | Python AST/`compileall` 通过；不代表依赖、模型或网络可用 |
| L3 | 真实组件执行通过 | 需要隔离环境中的实际服务/文件/模型执行证据；当前核对未做 |
| L4 | 真实端到端通过并核对终态 | 需要前端→IPC→HTTP→worker→外部模型/向量/图→轮询→回答及清理证据；当前核对未做 |

**防假绿规则**：源码存在不是测试通过；HTTP `success: true` 只表示任务启动/请求成功，不表示索引或回答成功；前端轮询日志、历史 benchmark、README 示例和子进程自报均不能单独提升到 L3/L4。

## 2. 项目定位与真实总体架构

HKUDS-VideoRAG 是一个“长视频检索增强生成”研究实现，同时带一个名为 Vimo 的桌面 Beta 原型。它不是单一运行时，而是两个相似但不相同的实现根：

1. **研究算法根**：本地 `MiniCPM-V` caption、`faster-whisper` ASR、进程内 ImageBind、OpenAI/Azure/Ollama LLM/embedding；默认文件型 KV、NanoVectorDB、NetworkX。
2. **桌面适配根**：Electron/React 负责 UI 和 IPC；Flask 主进程负责配置、ImageBind 单例和子进程登记；每个索引/查询任务是独立 `multiprocessing.Process`，worker 通过 HTTP 回调主进程 ImageBind；ASR 改为 DashScope 在线接口，caption 改为 OpenAI 兼容的多图请求。

### 2.1 真实流程图

```text
研究调用方 / Vimo Renderer
        │
        ├─ React Hook → preload contextBridge(window.api)
        │              → ipcRenderer.invoke
        │              → Electron ipcMain handler
        │              → axios http://localhost:<SERVER_PORT>/api
        │
        ▼
Flask create_app()/register_routes()
        │
        ├─ /initialize：写入进程内 global_config，登记 ImageBind 路径（不加载）
        ├─ /imagebind/load：GlobalImageBindManager 懒加载 ImageBind
        ├─ /sessions/<chat_id>/videos/upload：校验路径，写 status.json，spawn index worker
        │       │
        │       └─ index_video_worker_process
        │              → HTTPImageBindClient → Flask /imagebind/encode/video
        │              → split_video（30 秒段、音频、粗帧时刻）
        │              → DashScope Recognition（ASR）
        │              → saving_video_segments + 多图 caption
        │              → merge_segment_information
        │              → ImageBind 视频段向量
        │              → get_chunks → 文本向量 → LLM 实体/关系抽取
        │              → NetworkX/Neo4j 图 + KV/向量落盘
        │              → status.json completed/error
        │
        └─ /sessions/<chat_id>/query：写 query_status，spawn query worker
                │
                └─ query_worker_process
                       → HTTPImageBindClient → /imagebind/encode/query
                       → VideoRAG.aquery(mode="videorag")
                       → chunks_vdb 文本路 → cheap LLM 改写实体/视觉查询
                       → entities_vdb + graph 邻接路 → video segment ids
                       → ImageBind video-segment vector 路
                       → best LLM 过滤候选段
                       → caption model 对原视频重抽细帧并生成详细 caption
                       → CSV 风格视频上下文 + 文本块上下文
                       → best LLM 回答（桌面 worker 设置 wo_reference=True）
                       → query_status completed/error，前端 2 秒轮询
```

### 2.2 目录地图

```text
HKUDS-VideoRAG/
├── README.md / LICENSE
├── ARCHITECTURE.md                         # 本文件，唯一正式架构事实源
├── 细探-HKUDS-VideoRAG.md                   # 保留的历史细探，不再单独维护
├── VideoRAG-algorithm/
│   ├── README.md                           # 研究安装、示例、实验复现
│   ├── videorag/videorag.py                # 研究版 VideoRAG 编排器
│   ├── videorag/_op.py                     # 分块、实体/关系抽取、三路检索、回答
│   ├── videorag/_llm.py                    # OpenAI/Azure/Ollama 配置与重试
│   ├── videorag/_videoutil/                # split/ASR/caption/ImageBind
│   ├── videorag/_storage/                  # JSON KV、NanoVectorDB、HNSW、NetworkX、Neo4j
│   ├── examples/                           # DeepSeek 示例
│   ├── longervideos/                       # 数据准备与处理入口
│   ├── reproduce/                          # win-rate / quantitative 四步复现脚本
│   └── notesbooks/                         # 仓库原样拼写的 notebook 目录
└── Vimo-desktop/
    ├── package.json / pnpm-lock.yaml       # Electron 34 + React 18 + TS 5
    ├── electron.vite.config.ts             # main/preload/renderer 构建入口
    ├── src/main/main.ts                    # 注册 IPC、窗口、模型处理器
    ├── src/main/handlers/
    │   ├── videorag-handlers.ts            # 服务发现、HTTP、IPC、超时
    │   ├── chat-session-handlers.ts        # chat-<id>.json / session-order.json
    │   ├── settings.ts                     # bootstrap + config.json
    │   └── file-handlers.ts                # 文件/视频选择
    ├── src/preload/index.ts                # contextBridge 暴露 window.api
    ├── src/renderer/src/hooks/             # useVideoRAG / useChat 等
    └── python_backend/
        ├── videorag_api.py                 # Flask、ImageBind、worker、清理
        └── videorag/                       # 桌面版 VideoRAG 适配包
```

## 3. 两个实现根的差异与边界

| 维度 | `VideoRAG-algorithm/` 研究版 | `Vimo-desktop/python_backend/` 桌面版 |
|---|---|---|
| 入口 | `VideoRAG.insert_video()` / `query()`；示例在 `examples/` | `videorag_api.py` Flask 路由；Electron 通过 HTTP 调用 |
| caption | `AutoModel.from_pretrained('./MiniCPM-V-2_6-int4')`，由进程内模型处理（`videorag.py:121-129`） | `dashscope_caption_complete`，多图 base64 + transcript，通过 LLM wrapper 并发（`_videoutil/caption.py:31-74`） |
| ASR | 本地 `WhisperModel('./faster-distil-whisper-large-v3')`，逐段转写（`_videoutil/asr.py:8-29`） | DashScope `Recognition.call`，最多 5 个并发，异常在 `as_completed` 中记录后继续，返回已有 transcript（`_videoutil/asr.py:8-100`） |
| ImageBind | `NanoVectorDBVideoSegmentStorage` 内创建 `.cuda()` 模型（`_storage/vdb_nanovectordb.py:93-145`） | 主 Flask 进程 `GlobalImageBindManager` 单例加载；worker 经 `HTTPImageBindClient` 调 `/api/imagebind/encode/*`（`videorag_api.py:98-330`） |
| 跨进程 | 研究版 caption/切片存在独立 `Process` 和 `Manager`（`VideoRAG-algorithm/videorag/videorag.py:231-281`） | worker 自己完整执行任务，状态通过 JSON 文件投影，不使用 Queue/Manager（`videorag_api.py:336-568`） |
| 必填配置 | 主要由 `LLMConfig` 和环境/README 提供 | `VideoRAG.__post_init__` 对 DashScope、OpenAI key/base URL、模型名做 `assert`（`Vimo-desktop/python_backend/videorag/videorag.py:131-145`） |
| 结果引用 | 研究版可按 `wo_reference` 选择 prompt | 桌面 query worker 明确 `param.wo_reference = True`（`videorag_api.py:808-810`） |
| 默认图存储 | NetworkX | NetworkX；Neo4j 仅为可替换实现，需 `addon_params` |

因此，“双通道”在源码中应具体理解为：文本块/实体图路 + ImageBind 视频段视觉路；不是两个都可独立替代的端到端服务，也不是 README 所述所有跨视频/百小时能力已在当前机器得到验证。

## 4. 数据模型、索引与持久化契约

### 4.1 核心记录

| 对象 | 关键字段/键 | 产生位置 | 消费位置 |
|---|---|---|---|
| 视频路径 | `video_name -> video_path` | `VideoRAG.insert_video:318-320` | retrieved caption 通过 `video_path_db._data` 找原视频 |
| 视频段 | `video_name -> index -> {content,time,transcript,frame_times}` | `merge_segment_information:88-97` 后 `video_segments.upsert` | rough/filter/caption、图关系来源 |
| 视频段向量 | `__id__ = <video_name>_<index>`，`__video_name__`、`__index__`、`__vector__` | `NanoVectorDBVideoSegmentStorage.upsert:96-125` | `query:127-139`，返回 `id`/`distance` |
| 文本 chunk | MD5 `chunk-<hash(content)>`；`tokens/content/chunk_order_index/video_segment_id` | `_op.get_chunks:159-179` | `chunks_vdb`、`text_chunks`、图实体来源 |
| 实体节点 | 大写 `entity_name`；`entity_type/description/source_id` | `_op._handle_single_entity_extraction:209-227`、merge/upsert | `entities_vdb`、图邻接检索 |
| 关系边 | `(src_id,tgt_id)`；`weight/description/source_id/order` | `_op._handle_single_relationship_extraction:230-250`、`_merge_edges_then_upsert` | 图邻接和关系度统计 |
| 查询状态 | `indexing_status` 或 `query_status`，含 `status/message/current_step/query/answer` | `update_session_status` / worker | Flask status API、React polling |

### 4.2 默认文件与外部存储

| Namespace/资源 | 默认实现 | 文件/位置 | 提交时机 |
|---|---|---|---|
| `video_path`、`video_segments`、`text_chunks`、`llm_response_cache` | `JsonKVStorage` | `kv_store_<namespace>.json` | `index_done_callback` 调 `write_json`；普通写入只改内存 |
| `entities`、`chunks` | `NanoVectorDBStorage` | `vdb_entities.json`、`vdb_chunks.json` | `self._client.save()` |
| `video_segment_feature` | `NanoVectorDBVideoSegmentStorage` | `vdb_video_segment_feature.json` | `self._client.save()` |
| `chunk_entity_relation` | `NetworkXStorage` | `graph_chunk_entity_relation.graphml` | `nx.write_graphml` |
| 可选文本/实体向量 | `HNSWVectorStorage` | `<namespace>_hnsw.index` + `<namespace>_hnsw_metadata.pkl` | `save_index` + `pickle.dump` |
| 可选图 | `Neo4jStorage` | 外部 Neo4j，namespace 派生 label | `index_done_callback` 关闭 async driver；图数据实时写外部库 |
| 桌面会话 | Electron `chat-session-handlers.ts` | `<storeDirectory>/chat-<chatId>.json` | `writeFile` 全量 JSON；无版本/锁 |
| 会话排序 | 同上 | `<storeDirectory>/session-order.json` | `writeFile` 全量 JSON |
| Python 任务 | `videorag_api.py` | `<base_storage_path>/chat-<chatId>/status.json` | `*.tmp` 写完 `os.rename` |
| 临时媒体 | `split_video` / `saving_video_segments` | `<working_dir>/_cache/<video_name>/`，mp3/mp4 | 单视频完成后 `shutil.rmtree`；异常路径未统一清理 |
| ImageBind 权重 | Electron model handler | `<storeDirectory>/imagebind_huge/imagebind_huge.pth` | 下载完成后保留；失败/超时删除目录 |

`JsonKVStorage.write_json`、NanoVectorDB save 和 GraphML save 都是整个文件/索引提交，没有事务、版本号、校验和或迁移协议。`update_session_status` 虽使用临时文件 + rename，但先读后改再写且没有锁，多个 worker/请求可丢字段。

## 5. 契约表

### 5.1 Python `VideoRAG` 公共门面

| 入口 | 输入/前置 | 成功输出/状态 | 失败、可重试、资源责任 | 证据与等级 |
|---|---|---|---|---|
| `VideoRAG(...)` | 必须提供桌面版 6 个 key/base/model 字段；创建 `working_dir`，加载各 namespace | 内存对象、已加载文件索引、safe config | `assert`/依赖导入/损坏 JSON 可失败；没有统一错误码；创建者持有 storage/logger | `videorag.py:56-296`，L1/L2 |
| `insert_video(video_path_list, progress_callback)` | 路径存在、可读、ffmpeg/MoviePy、ASR/caption/embedding/LLM 可用；同名 `video_name` 会跳过 | 按阶段写段、向量、图；callback 最终 `Completed` | 任一阶段异常向上冒泡；桌面 worker 捕获并写 `error`；无事务回滚，可能留下部分文件；缓存目录仅成功路径删除 | `videorag.py:298-410`，L1/L2 |
| `query(query, QueryParam(mode="videorag"))` | 已有 session index；`chunks_vdb/entities_vdb/video_segment_feature_vdb` 可用；外部 LLM/ImageBind 可用 | `str` 回答；结束写 LLM cache | 空文本路在 naive query 结果为空时返回 `fail_response`；其他异常由 worker 写 error；无 query timeout/取消 | `videorag.py:412-447`、`_op.py:574-732`，L1/L2 |
| `aquery(mode="videorag_multiple_choice")` | 同上 | 期望 JSON `Answer` + `Explanation` | `while True` 无限重试非 JSON，无上限/超时/取消；该模式在桌面 API 未专门暴露 | `videorag.py:416-447`、`_op.py:734-906`，L1 |

### 5.2 Flask HTTP 契约

所有路由都在 `create_app()` → `register_routes()` 注册（`videorag_api.py:833-846`），大多数 JSON 含 `success`；耗时索引/查询是“接受任务即返回”，最终结果必须读 status API。

| 方法/路径 | 请求关键字段 | 立即响应语义 | 失败/超时/取消语义 |
|---|---|---|---|
| `GET /api/health` | 无 | `{"status":"ok"}` | 仅表示 Flask 可响应，不表示 ImageBind/worker/外部 provider 健康 |
| `POST /api/initialize` | `base_storage_path`、`image_bind_model_path`、key、model/base URL | 设置 `process_manager.global_config`，ImageBind 只登记路径，不加载 | 配置异常 500；未校验路径/密钥真实性 |
| `GET /api/imagebind/status` | 无 | `success + status`（注意文件后部还重复注册同一路径） | manager 异常 500；重复 route 的覆盖行为未单独实测 |
| `POST /api/imagebind/load` / `release` | 无 | 加载/释放模型并返回状态 | 缺初始化、权重、torch/device 异常 500；无加载超时 |
| `POST /api/imagebind/encode/video` | `video_batch: string[]`，路径必须存在 | base64(pickle(numpy)) + shape/dtype/batch_size | 空批次/不存在路径 400；推理异常 500；主进程 HTTP 无请求超时配置 |
| `POST /api/imagebind/encode/query` | 非空 `query` | base64(pickle(numpy)) + shape/dtype | 空 query 400；推理异常 500 |
| `POST /api/video/duration` | `video_path` | `VideoFileClip` 上下文内返回 duration/fps/size | MoviePy/路径异常 500；虽有 `with`，无认证/路径沙箱 |
| `POST /api/sessions/<chat_id>/videos/upload` | `video_path_list[]`，每个路径存在 | 初始化 status + spawn index worker，返回 `status:"started"` | 空/无效路径 400；spawn 失败 500；启动成功不等于完成；无幂等键/并发任务限制 |
| `GET /api/sessions/<chat_id>/status[?type=query]` | `type=query` 才查 query 状态 | 返回 status 投影；默认查 indexing | 无 status 404；读坏 JSON 返回空并可能 404；没有超时状态判定 |
| `GET /api/sessions/<chat_id>/videos/indexed` | 无 | `indexed_videos[]` | 读失败 500/空列表；列表 append 无去重 |
| `POST /api/sessions/<chat_id>/query` | JSON `query`（空字符串当前未拒绝） | 写 query processing + spawn query worker，返回 started | 未初始化/session 目录不存在会在 worker 内失败；无任务 ID、超时、取消 token |
| `POST /api/sessions/<chat_id>/terminate` | 无 | `terminate_process(chat_id)` 返回 terminated keys | 只直接查 `chat_id`，不对称命中 `chat_id_query`；索引状态标 terminated，query 状态可能仍 processing |
| `DELETE /api/sessions/<chat_id>/delete` | 无 | 调 `delete_session` 后无论其返回值仍返回 success | 仅终止，不删除 `<base_storage_path>/chat-<id>` 文件；查询 worker 可能残留 |
| `GET /api/system/status` / `/api/system/processes` | 无 | 进程、会话、ImageBind 状态投影 | `active_sessions` 只来自当前登记的 live/done process dict；重启后历史索引不自动计入 |

**重复路由事实**：`/api/imagebind/status` 在 `videorag_api.py:905-918` 和 `:1300-1320` 各注册一次，返回字段形状不同（`status` vs `data`）；未通过 Flask 实测确认最终匹配者，故不能把任一形状当稳定契约。

### 5.3 Electron IPC / 前端契约

| 层 | 真实入口 | 关键行为 |
|---|---|---|
| preload | `src/preload/index.ts:184-205` | contextBridge 暴露 `window.api.videorag.*` 与 `chatSessions.*`；隔离开启时不暴露 Node 直连 |
| IPC handler | `src/main/handlers/videorag-handlers.ts:442-723` | `callVideoRAGAPI` 使用 axios；默认 30s，upload 60s，initialize 120s，status 10s，ImageBind load/release 180s |
| 服务发现 | `videorag-handlers.ts:22-44,138-177,725-753` | 开发模式不启动 Python，只扫描 64451–64470；生产模式 spawn 打包 executable；发现服务后初始化配置 |
| 索引 UI | `useVideoRAG.ts:119-143` + `useChat.ts:487-...` | upload 只代表启动成功；状态靠 `/status` 轮询 |
| 分析轮询 | `useChat.ts:202-293` | 2 秒一次；`completed` 停止，`error` 停止；网络异常继续无限轮询 |
| 查询 UI | preload/handler 已有 `query` 与 `queryVideo` 两套 IPC，均 POST 同一路由；调用方需另行读取 `type=query` 状态，契约未统一 |
| 会话状态 | `chat-session-handlers.ts:123-297` | Electron JSON 与 Python status.json 并行，文件全量写；删除 Electron 会话不等于删除 Python 工作目录 |

## 6. 真实对接调用链（函数级）

### 6.1 初始化与模型生命周期

```text
InitializationWizard / settings
  → window.api.videorag.startService()
  → ipcMain videorag:start-service
  → startVideoRAGService()
  → attemptHealthCheck(port)
  → initializeVideoRAGConfig()
  → loadSettingsFromFile()
  → /api/initialize
  → VideoRAGProcessManager.set_global_config()
  → GlobalImageBindManager.initialize()       # 只登记路径
  → window.api.videorag.loadImageBind()
  → /api/imagebind/load
  → GlobalImageBindManager.ensure_imagebind_loaded()
  → ImageBindModel.load_state_dict().to(device).eval()
```

`get_imagebind_device()` 的真实策略是 CUDA 优先，否则强制 CPU；即便 macOS MPS 可用，ImageBind 因 Conv3D 仍走 CPU（`_utils.py:223-233`）。

### 6.2 视频索引链

```text
renderer upload
  → preload `videorag.uploadVideo`
  → IPC `videorag:upload-video`
  → axios POST `/sessions/<chat_id>/videos/upload`
  → path exists 检查
  → `start_video_indexing()` 写初始 status.json 并 spawn
  → `index_video_worker_process()`
  → `HTTPImageBindClient.get_status()`
  → `VideoRAG(..., imagebind_client=client)`
  → `insert_video()`:
       video_path_db.upsert
       split_video() → `_cache/<video_name>/` mp3 + segment timestamps/frame_times
       speech_to_text() → DashScope Recognition.call（最多 5 并发）
       saving_video_segments() → mp4
       segment_caption() → VideoFileClip + base64 frames + caption_model_func
       merge_segment_information() → video_segments.upsert
       video_segment_feature_vdb.upsert() → HTTP /imagebind/encode/video → NanoVectorDB
       `_cache/<video_name>` 删除
       `_save_video_segments()` → KV/vector save
  → `ainsert(video_segments._data)`:
       get_chunks() → chunks_vdb.upsert()
       extract_entities() → LLM → NetworkX/Neo4j + entities_vdb
       text_chunks.upsert()
       `_insert_done()` → 全部 `index_done_callback`
  → final indexing_status.completed
```

关键非原子点：`video_segments` 在图/文本抽取前已写入；向量、图、文本 chunk 可能只完成其中部分；worker 异常只写 error，不删除或回滚已有产物。

### 6.3 查询链

```text
renderer chat submit
  → preload `videorag.queryVideo` 或 `videorag.query`
  → IPC POST `/sessions/<chat_id>/query`
  → `start_query_processing()` 写 query_status.processing + spawn
  → `query_worker_process()`
  → client.get_status() + VideoRAG(...)
  → `VideoRAG.query()` → `aquery()` → `videorag_query()`:
       chunks_vdb.query(query, top_k)
       text_chunks_db.get_by_ids() → naive chunk context
       cheap LLM `_refine_entity_retrieval_query`
       entities_vdb.query + graph.get_node/get_node_edges → segment ids
       cheap LLM `_refine_visual_retrieval_query`
       video_segment_feature_vdb.query() → ImageBind query HTTP
       best LLM `_filter_single_segment` 并发过滤
       cheap LLM `_extract_keywords_query`
       retrieved_segment_caption_async() → 原视频重开 + 细帧 + caption model
       list_of_list_to_csv() → 视频时间/内容上下文
       best LLM with `videorag_response_wo_reference`
  → query_status.completed.answer
  → `/status?type=query`
  → 前端显示/写入 chat session JSON
```

研究版 `videorag_query()` 还支持 `wo_reference=False` 的引用 prompt；桌面 worker 固定关闭引用。`videorag_query_multiple_choice()` 的 JSON 重试是无限 `while True`，不能作为有界生产契约。

## 7. 关键节点明细

| 节点 | 前置条件 | 状态/读写 | 并发模型 | 失败分支与恢复 | 证据 |
|---|---|---|---|---|---|
| `split_video` | 视频可被 MoviePy/ffmpeg 打开；working dir 可写 | 创建 cache；每 30 秒切片；计算 frame_times；写 mp3 | 单 worker 内逐段 | `VideoFileClip` 有上下文；`subvideo`/audio 对象未显式关闭；异常不保证删除 cache | `Vimo.../_videoutil/split.py:10-65` |
| `speech_to_text_online` | DashScope key/model、每个 mp3 存在 | 每段返回 transcript；失败段被 `as_completed` 捕获并跳过 | semaphore=5；同步 SDK 放 executor | 单段异常记录后继续，可能形成空/缺 transcript，却仍进入 caption/index；没有重试/超时参数 | `.../asr.py:44-100` |
| `segment_caption_async` | 原视频可读、transcript key 完整、caption provider 可用 | 先一次性把所有段帧转成 base64，再并发 caption；段异常返回空字符串 | `asyncio.gather`，并发由 wrapper 限制（桌面 max 3） | 单段失败返回空 caption；整段抽帧异常抛出；无取消传播契约 | `.../caption.py:31-74` |
| `NanoVectorDBVideoSegmentStorage.upsert` | cache mp4 存在；ImageBind HTTP 服务 loaded | 生成 1024 维向量并 upsert 内存 DB，最后 save | batch=2，顺序 HTTP 调用 | 任一批失败，整个 upsert 异常；已经计算的内存向量未回滚 | `.../vdb_nanovectordb.py:96-125` |
| `get_chunks` | 每段 content 可 tokenize | 按 1200 token 合并 segment ids，MD5 content 作为 key | tiktoken `encode_batch(num_threads=16)` | 超长段截断；同内容跨视频会发生 key 冲突/去重；无 schema 校验 | `_op.py:69-179` |
| `extract_entities` | chunks、best/cheap LLM、图和 entity vector 可用 | 并发对每 chunk 抽实体关系，再 merge 节点边、写图和 entity vector | `asyncio.gather`，LLM wrapper max_async=16 | LLM 格式不符被忽略；零实体返回 None；并发图 merge 没有显式事务/锁 | `_op.py:357-478` |
| `videorag_query` | 三路索引与原视频路径完整 | 读 chunk/entity/graph/segment vector，写 LLM cache，返回 answer | 多个 `gather`；provider 上限 wrapper | 空文本结果返回 fail response；缺 segment key、`eval` 时间字符串、provider 异常会失败；无总超时 | `_op.py:574-732` |
| `update_session_status` | base storage 可写 | 读 JSON→merge status_type→tmp rename | 多进程/线程共享，**无锁** | 坏 JSON 返回 `{}`；并发写最后写者覆盖字段；tmp 异常删除 | `videorag_api.py:49-96` |
| `terminate_process` | `running_processes` 仍保有 Process 对象 | terminate→join 5 秒→kill；只更新 indexing_status | 主 Flask 进程同步调用 | 只接收 `chat_id`，query key 是 `<chat_id>_query`；不更新 query status；重启后无法杀旧 worker | `videorag_api.py:431-462` |

## 8. 资源生命周期与所有权

| 资源 | 创建/持有者 | 正常释放 | 业务失败 | 超时/主动取消 | 宿主/子进程崩溃与残留验证 |
|---|---|---|---|---|---|
| ImageBind 模型/GPU 或 CPU 内存 | Flask `GlobalImageBindManager` 单例 | `/imagebind/release` 或 `cleanup_on_exit`：to CPU、del、`torch.cuda.empty_cache` | load 异常 re-raise；部分对象由 GC 接管，未证明显存完全回收 | HTTP 请求无后端 cancel；Electron axios 超时只断前端请求，推理仍可能继续 | SIGINT/SIGTERM/atexit 调 cleanup；硬崩溃无保证；当前核对未读 GPU/进程现场 |
| HTTP `requests.Session` | 每个 worker `HTTPImageBindClient` | 依赖进程退出/requests GC；未显式 `close()` | 异常 re-raise | 1800s client timeout；无主动取消钩子 | worker kill 由 OS 关闭 socket；未做残留连接验证 |
| Flask 子进程 | `VideoRAGProcessManager.running_processes` | terminate/join 或 cleanup | worker catch 异常后自行退出，但 manager 不自动移除已退出条目 | terminate 5s 后 kill；查询键不对称 | `cleanup()` 再用 psutil 扫 `videorag-index-`/`videorag-query-`；重启遗留进程清理未实测 |
| Python event loop | worker/`always_get_an_event_loop` | 正常返回时进程退出；无统一 `close()` | 异常路径未显式关闭 | 无 cancellation token；`asyncio.gather` 取消语义未封装 | 进程 kill 后由 OS 回收；当前核对未做 loop 泄漏测试 |
| 原视频 `VideoFileClip` | `split_video`、`saving_video_segments`、caption helper 的局部上下文 | 这些位置使用 `with VideoFileClip` | 大部分异常由 context manager 释放；`subvideo`/audio 临时对象关闭责任不清 | 无取消回调 | 进程硬杀可能留 ffmpeg 子进程/句柄；未做 psutil/文件句柄验证 |
| `_cache` mp3/mp4/帧 base64 | index worker 与 caption coroutine | 成功索引后 `shutil.rmtree(_cache/<video>)`；base64 仅内存 | caption/embedding/graph 失败前不统一删除 | terminate/kill 不执行 worker finally 清理 | 崩溃可能留下大缓存；未做残留扫描 |
| JSON KV / NanoVectorDB / GraphML | `VideoRAG` 对象内存结构 | `_save_video_segments`/`_insert_done` save | save 部分成功可留下不一致文件；无 rollback | 无写入取消协议 | 进程硬杀时文件可能截断；无 checksum/恢复验证 |
| status.json | worker 写入，Flask/renderer 读取 | tmp + `os.rename` | 异常 handler 再写 error；handler 本身失败只记录 | terminate 写 indexing terminated，query 不对称 | 崩溃前最后状态可能永久 processing；需现场检查 PID、状态和 tmp，当前未执行 |
| Electron `chat-<id>.json` / order | Electron main handlers | `writeFile` 全量写；renderer 通过 contextBridge 使用 | catch 返回 false；并发调用可互相覆盖 | 无 abort/锁/版本 | Electron crash 可能留下截断 JSON；未做恢复/备份验证 |
| OpenAI/DashScope/Neo4j client | provider helper / `Neo4jStorage.async_driver` | Neo4j 仅 `index_done_callback` close；OpenAI async global client 无显式 close | SDK/tenacity 仅对部分 OpenAI RateLimit/APIConnection 重试 | HTTP client 有 1800s timeout；DashScope `Recognition.call` 无显式 timeout | 外部服务断线/进程崩溃的远端任务状态不回收；未实测 |
| ImageBind 下载流 | Electron `download-imagebind` | finish close file；成功保留权重 | response/file/request error 删除整个目录 | 300s `request.setTimeout`，destroy + 删除目录 | Electron 硬崩溃可能留半文件；无 SHA-256/断点校验 |

## 9. 失败、超时、取消、崩溃矩阵

| 场景 | 当前代码行为 | 是否有界/可恢复 | 结论 |
|---|---|---|---|
| 空上传列表/不存在路径 | upload 400；路径仅 `os.path.exists` | 有界 HTTP 拒绝；没有白名单 | 已实现输入拒绝，安全边界不足 |
| 空 query | 路由只检查 `data`，不拒绝空字符串；worker 继续启动 | 无业务校验；可能 provider 失败或返回无意义答案 | 未形成稳定契约 |
| 缺 key/model/ImageBind | `initialize` 可返回 success 但仅保存配置；真正失败常在 load/worker | 错误延迟到后续阶段 | `success` 不能视为 ready |
| 单段 ASR/Caption provider 失败 | ASR 段失败后继续；caption 段失败变空字符串 | 任务可“完成”但内容不完整 | 存在部分成功假绿风险 |
| LLM rate limit/连接错误 | 研究 `_llm.py` 对 OpenAI 部分调用 tenacity 重试；DashScope caption/ASR无统一重试 | 重试次数有时 5/3 次，等待 4–10 秒；无全任务 deadline | 需按 provider 分开验证 |
| ImageBind HTTP 断线 | worker client 1800 秒请求超时后抛错；worker 写 error | 单调用有界；任务无总 deadline/重试 | 失败可见但恢复需人工重跑 |
| Electron axios 超时 | 10–180 秒区间后前端报错；后端任务可能仍运行 | 前端请求可终止，服务端没有取消 | 不能把前端超时当作任务取消 |
| 用户主动 terminate | index `terminate`→join 5s→kill；只更新 indexing | query key `<chat_id>_query` 不会被同一接口直接命中；无 worker finally | 取消不完整 |
| API/worker 进程崩溃 | `atexit`/SIGINT/SIGTERM 仅覆盖可捕获退出；主进程重启无任务恢复 | status 可能永久 processing；缓存/索引/ffmpeg 残留 | 没有 crash recovery 协议 |
| 多请求/多 worker 同时更新 status | 读-改-写无锁，临时 rename 只保证单次替换 | 最后写者覆盖，字段丢失可能 | 不是并发安全状态存储 |
| 图/向量/KV 部分写入 | 不同 namespace 先后 save，无跨文件事务 | 重启会加载部分状态；没有 manifest/校验/回滚 | 索引一致性未保证 |
| 多选题 LLM 非 JSON | 无限 `while True` 重试 | 无最大次数/超时/取消 | 明确的无界失败路径 |
| 删除 session | API 只调用 `delete_session`/terminate，不删除工作目录；路由忽略返回值仍返回 success | 资源/数据可能残留，前端文件与 Python 状态脱节 | 删除语义是假完成高风险点 |
| 路径/权限/恶意请求 | CORS 全开放；本地路径直接传入；无认证、白名单、大小限制 | 无安全恢复 | 仅适合本机 Beta/研究使用 |

## 10. 防假绿验证账本（当前核对真实执行）

| 验证项 | 命令/证据 | 结果 | 等级 |
|---|---|---|---|
| 目标文件与旧细探存在 | `search_files(target="files", pattern="*")` + `read_file(细探-HKUDS-VideoRAG.md)` | 旧细探完整读取 69 行；`ARCHITECTURE.md` 存在 | L1 |
| 目标 Git 基线/边界 | `git status --short --branch`、`git log -1 --format=...` | `main`，HEAD `c412a09...`；仅两份未跟踪文档 | L1 |
| Python 语法/编译 | `python3 -m compileall -q VideoRAG-algorithm/videorag Vimo-desktop/python_backend/videorag Vimo-desktop/python_backend/videorag_api.py` | 退出码 `0`；随后已删除本命令生成的 `__pycache__`，未留构建物 | L2 |
| 代码图 | `mcp__codegraph__codegraph_explore(projectPath=<目标根>, ...)` | 明确“no `.codegraph/` directory found”，未伪造 | L0（工具不可用） |
| Flask/IPC 真实启动 | 未启动 | 未验证依赖、端口、路由注册最终行为 | L0/L1 |
| ImageBind/ASR/caption/LLM provider | 未加载权重、未调用外部服务 | 未验证 GPU/CPU、key、模型、网络、重试 | L0/L1 |
| 视频索引 | 未准备/处理视频 | 未验证分段、ffmpeg、文件产物、图/向量一致性 | L0 |
| 查询/前端轮询 | 未启动 Electron/Flask，未进行 HTTP/IPC E2E | 未验证回答、状态终态或取消 | L0 |
| 端口/进程/句柄/缓存终态 | 未执行任务，不应声称“无残留” | 需后续隔离运行后读回验证 | L0 |

### 10.1 后续可执行但当前核对未执行的验收命令

以下只是复核方案，不能写成已通过：

```bash
# 在隔离 Python 3.11 + 依赖 + 模型 + 密钥环境中
python -m compileall -q VideoRAG-algorithm/videorag Vimo-desktop/python_backend/videorag Vimo-desktop/python_backend/videorag_api.py
python Vimo-desktop/python_backend/videorag_api.py

# 另一个终端：逐项确认健康、初始化、load/status/release，再用短测试视频做 upload/status/query
curl -fsS http://127.0.0.1:<port>/api/health
curl -fsS -X POST http://127.0.0.1:<port>/api/initialize -H 'Content-Type: application/json' --data @config.json
curl -fsS -X POST http://127.0.0.1:<port>/api/imagebind/load

# 任务结束后必须核对：status.json 终态、worker PID、ffmpeg 子进程、_cache、*.tmp、JSON/GraphML/向量文件可读性
ps -axo pid,ppid,command | grep -E 'videorag-(api|index|query)|ffmpeg'   # 仅示意，执行时不得把 grep 自身当残留
```

## 11. 旧细探逐条吸收与裁决

| 旧细探内容 | 当前源码对照 | 裁决 |
|---|---|---|
| “抽帧 → 多模态嵌入 → 图/向量索引 → 检索 → 生成” | `split_video`、caption、ImageBind vector、`ainsert`、`videorag_query` 均有真实调用 | **吸收**，已落入第 2、6 节；标为 L1/L2，不宣称 E2E |
| “图驱动知识索引 + 分层上下文编码双通道” | 当前实现可证实的是实体/关系图路 + 视频段 ImageBind 路；“分层上下文编码”更多来自 README/论文表述，源码未见独立层级编码模块 | **部分吸收/降级**：只保留可证实的图路 + 视觉段路 |
| 视频采样、视觉+文本、多模态 embedding | `split.py` frame_times、caption base64、ImageBind vision/text 编码、DashScope transcript | **吸收**，加入真实参数/文件路径 |
| 单 GPU 超长视频 | README 宣称 RTX 3090/百小时；桌面 ImageBind 在 CUDA 或 CPU，研究版 `.cuda()`；当前核对未跑 | **仅保留为声明**，不吸收成能力保证 |
| 视频问答与 Vimo Desktop | 根 README、桌面 README、Electron/Flask 源码均对应 | **吸收**，明确 Vimo 为 Beta 原型、服务发现和状态轮询事实 |
| “慢速重型能力，需要独立进程 + 资源协调” | 桌面确实 spawn index/query worker，ImageBind 主进程单例；但没有统一队列/租约/总 deadline | **吸收为架构观察**，不升级为已完成治理 |
| “平台视频检索候选/媒体能力组合” | 这是跨项目平台建议，不是本仓库事实 | **不吸收为项目实现**，仅保留在第 12 节候选裁决 |
| Vimo 多视频、跨视频、百小时、无长度限制 | README 宣称；源码接受列表且图/向量可处理多视频，但无当前核对运行证据，也有同名 key 冲突风险 | **待核**，不得写成验收能力 |
| “许可证通常 MIT” | 旧文档未给许可证原文；当前只确认 `LICENSE` 文件存在，当前核对未按许可证文本裁决 | **不吸收“通常 MIT”**，避免猜测 |
| HKUDS/LightRAG 旁路线索 | README acknowledgement 可作来源线索，不是当前调用链 | **保留为来源备注**，不当作运行依赖事实 |

## 12. 面向平台的吸收/不吸收裁决

### 12.1 可吸收（研究模式，不等于直接复制）

- **吸收**：视频任务可拆为“分段/时间坐标 → 音频转写 → 视觉描述 → 统一段记录 → 多路索引 → 候选过滤 → 细粒度重 caption → 回答”的可审计阶段模型。
- **吸收**：图路与视觉向量路应拥有统一的 `segment_id`、时间范围、来源文件和可追溯引用契约。
- **吸收**：重型 ImageBind/ASR/caption 必须隔离到可管理进程/服务，并显式记录模型、设备、批次、外部请求和资源终态。
- **吸收**：索引/查询必须分离“accepted/running/succeeded/failed/cancelled/timeout/crashed”，不能用启动成功代替任务成功。

### 12.2 不吸收/废弃为底座契约

- **不吸收**：每个 session 一组无锁 JSON 文件作为跨进程事实源；它无法提供事务、版本、恢复和并发合并。
- **不吸收**：worker 直接用 `status.json` 读改写、以 `chat_id`/`chat_id_query` 两套键管理任务。
- **不吸收**：无界多选题重试、前端 axios 超时后继续后台任务、删除 API 忽略内部失败、全开放 CORS/本地路径直传。
- **不吸收**：把 MD5 内容键当完整性证明；这里仅能作为当前代码的去重/缓存键。
- **不吸收**：让桌面端、研究版、模块消费者各自维护同名 VideoRAG 核心的第二套实现；应由唯一能力契约/适配层收敛。

### 12.3 待核

- 图驱动索引与论文中的“层级上下文编码”是否有未在当前快照的独立实现。
- 多视频同名 basename、相同 chunk 内容、增量索引和跨 session 隔离的实际正确性。
- Neo4j/HNSW 替换实现是否在当前版本可用，尤其是 driver 关闭、label/constraint 和元数据恢复。
- Apple Silicon/MPS 下完整链路的可用性；代码明确 ImageBind 强制 CPU，但其余 PyTorch/依赖兼容性未测。
- 状态文件损坏、进程崩溃、ffmpeg 残留、部分索引恢复和删除后的数据清理。

## 13. 剩余风险与下一轮复核优先级

1. **P0 任务终态与取消**：引入持久 task id、幂等键、owner、deadline、cancel token、统一状态机、worker exit code 和 crash recovery；终止后读回 PID/进程组/状态/临时目录。
2. **P0 数据一致性**：为 KV/向量/图建立 manifest、版本、原子提交或 SQLite/事务边界；启动时校验并能从中间状态恢复/回滚。
3. **P0 输入与安全**：路径沙箱、session 所有权、认证、请求大小/格式限制、CORS 白名单、日志脱敏；禁止把任意本地路径当上传接口。
4. **P1 外部依赖**：锁定 Python/Node/CUDA/模型 commit 与 SHA-256；为 DashScope/OpenAI/ImageBind/Neo4j 建立可观测 timeout、重试和错误码。
5. **P1 测试真假**：补无模型单测（分段边界、时间字段、chunk key、状态合并、IPC payload、进程键）和 mock provider 契约测试，再做短视频 L3 与完整 L4。
6. **P1 双实现漂移**：明确研究版是实验基线，桌面版是适配层；不要继续手工复制 `videorag.py`、`_op.py`、storage 的修复。

## 14. 结论

当前源码确实落地了一个“研究算法 + 桌面原型”的视频 RAG 管线：视频按约 30 秒分段，产生音频与时间帧；桌面版用 DashScope 做 ASR、兼容视觉模型做 caption、主进程 ImageBind 做视频/文本编码；随后以文件 KV、NanoVectorDB 和 NetworkX/可选 Neo4j 构建索引；查询同时使用文本/实体图路和视觉段向量路，经过候选过滤和细 caption 后调用 LLM 回答。

但当前证据最高只到 **L2 静态语法检查**。没有 L3 依赖/服务/模型实测，也没有 L4 前端到端、失败恢复、取消、崩溃清理或终态核对。故本项目应定位为可供研究复现和平台设计借鉴的 Beta 原型，而不是已经通过生产可靠性验收的视频分析服务。

**当前核对修改边界**：仅更新目标根 `ARCHITECTURE.md`；保留 `细探-HKUDS-VideoRAG.md`；未修改源码、配置、测试、依赖、模型、数据库、Git 历史或远程仓库。

---

## 15. 后续：通用底座映射与单链路裁决

本节不是把平台能力反投影成“项目已经具备”，而是根据当前源码的真实 owner、输入输出和资源边界，给出迁移到“支持库 → 知识模块 → 运行核心 → 网关”的候选落点。凡源码没有实现、没有测试或没有当前核对真实运行证据的内容，均保留为“待核/不吸收”，不能作为生产能力声明。

### 15.1 目标分层与唯一 owner

| 领域对象 | 当前项目真实 owner | 支持库落点（底层原子能力） | 知识模块落点（领域编排） | 运行核心落点（治理/资源） | 网关落点（统一边界） | 后续裁决 |
|---|---|---|---|---|---|---|
| 媒体摄取 | `upload_video` 只接收本机路径；`VideoRAG.insert_video` 写入 `video_path_db` | 媒体文件探测、可读性/格式、受控路径、元数据读取、唯一内容/来源标识、临时目录和原子文件写 | `视频摄取模块`：把一个媒体来源编排成可重放的摄取任务 | 输入配额、路径沙箱、任务幂等、租约和清理 | `POST /sessions/<chat_id>/videos/upload` 只接受命令并返回 task id；不直接传模型对象 | **吸收为候选；拒绝“任意本机路径即上传”**。源码无上传字节流、认证或沙箱。 |
| 时间片段/采样 | `split_video` 以 30 秒为默认段，`np.linspace` 生成粗帧；检索时再按 `[start,end)` 细采样 | `ffprobe/MoviePy` 元数据、时间坐标校验、段/帧采样器、音频抽取、视频段制品写入 | `视频片段模块`：维护 `media_id/segment_id/start/end/frame_times` 与 ASR/caption 关联 | 采样预算、单段大小/时长上限、取消检查点、ffmpeg 子进程组回收 | 只暴露规范化的 `segment`/进度投影，不暴露 MoviePy 对象 | **吸收数据契约，不复制当前字符串时间格式**。当前 `time` 被拼成字符串并用 `eval` 解析，不能成为底座契约。 |
| ASR | 研究版 `faster_whisper.WhisperModel` 逐段同步转写；桌面版 `DashScope Recognition.call`，Semaphore=5 | ASR provider 适配、音频格式/采样率、分段转写、provider 错误归一化 | `视频摄取模块` 调用 ASR 并将 transcript 绑定 segment | 外部请求 deadline、重试预算、并发配额、取消传播、失败段策略 | 网关只返回任务状态/错误码，不直连 DashScope | **吸收 provider 适配边界；不吸收“单段失败仍算完成”**。 |
| OCR | 目标源码中未检出 `OCR/Tesseract/PaddleOCR/EasyOCR/文字识别` 实现入口；caption 不是 OCR | 预留 `媒体文字识别` 原子能力，先不实现、不注册假能力 | 片段模块未来可把 OCR 块并入统一 segment evidence | GPU/CPU 预算、页/帧数量和文本置信度治理 | 未来由统一媒体解析路由承载 | **待核/不吸收**。不能把视觉 caption 或 README 的多模态宣传写成 OCR 已实现。 |
| caption/视觉描述 | 研究版 `MiniCPM-V` 本地模型；桌面版 `dashscope_caption_complete` 多图请求；检索后再细 caption | 多图/文本 prompt provider、图片编码、模型调用、结果清洗、provider 超时 | `视频片段描述模块`：粗描述、细描述、转录合并 | GPU/外部 API 配额、并发、OOM、取消、重试和响应大小 | 通过任务执行，不在 Flask 路由内拼 prompt | **吸收“粗→过滤→细”的阶段模型；provider 实现隔离**。 |
| 跨模态 embedding | 研究版 `NanoVectorDBVideoSegmentStorage` 内部每次 `.cuda()` 加载 ImageBind；桌面版 Flask `GlobalImageBindManager` 单例，worker 走 HTTP `/imagebind/encode/*` | 文本/视觉 embedding provider、批量、维度/模型指纹、序列化反序列化、向量写入 | `跨模态索引模块`：segment vector + text/entity vector 的统一索引记录 | GPU 模型池/独占租约、显存预算、模型生命周期、OOM 隔离和重启 | `/imagebind/encode/video`、`/imagebind/encode/query` 应降为统一 embedding 能力网关适配，不保留项目专属协议 | **吸收能力边界；废弃研究版每次查询/写入重新加载模型的模式**。 |
| 文本 chunk/实体图 | `_op.get_chunks` 按 segment content、1200 token 拼 chunk；`extract_entities` 调 LLM 后写 NetworkX/Neo4j + entity VDB | tokenizer、chunk、实体/关系记录校验、向量/图存储驱动 | `知识索引模块`：chunk→实体/关系→segment_id 投影 | 索引事务、manifest、版本、重建/回滚、并发写协调 | 网关只提交 `build_index` / `query` 命令并读统一结果 | **吸收图路作为知识模块，不把 NetworkX 文件直接当权威状态库**。 |
| 检索/RAG | `videorag_query` 先 chunks，再实体改写+图邻接，再视觉向量，LLM 过滤，细 caption，最终 LLM | 向量 top-k、图邻接读取、候选融合、证据排序和上下文序列化 | `视频检索问答模块`：唯一融合编排和回答引用 | query deadline、候选/上下文预算、取消、部分 provider 降级、答案证据完整性 | 统一 `submit_query`/`get_task`/`cancel_task`；禁止 renderer 自己拼第二条查询链 | **吸收唯一融合顺序和 segment evidence；不吸收 `wo_reference=True` 的无引用生产默认**。 |
| 模型/外部 provider | `_llm.py` 的 OpenAI/Azure/Ollama（研究版）和 OpenAI-compatible/DashScope（桌面版）；ImageBind、Whisper、MiniCPM-V | 每个 provider 独立适配、凭据引用、模型元数据、重试/错误码 | 各领域模块只依赖统一模型能力契约 | 独立环境/进程、资源预算、健康检查、熔断、版本指纹 | 网关不暴露 key，不把第三方异常直接透传 | **吸收“provider 可替换”；废弃模块各自直连第三方**。 |
| 任务队列/状态 | 桌面版 `multiprocessing.Process` 直接 spawn；状态写 `status.json`；没有持久队列；研究版 `Manager.Queue` 只传 caption/切片错误 | 不建立第二套队列；支持库只提供子进程/进程组/JSON 协议原子能力 | `视频摄取模块`、`视频查询模块` 作为任务 handler | 唯一任务状态机、持久任务表、队列/worker、deadline、cancel token、租约、崩溃恢复 | Flask/Electron 仅是网关/适配，不拥有运行队列 | **建立运行核心唯一任务 owner**；当前 `running_processes` + JSON 状态只作研究证据，不能生产化复用。 |
| 文件制品 | `_cache` mp3/mp4、KV JSON、NanoVectorDB JSON、GraphML、`status.json`、Electron 会话 JSON、模型权重 | 受控目录、原子写、摘要/manifest、版本化制品、读回校验、删除/回收 | 模块定义 segment/chunk/index/answer evidence 制品关系 | 制品生命周期、引用计数、崩溃恢复、垃圾回收、空间配额 | 只返回制品 id/下载或预览引用，不直接返回内部路径 | **吸收制品分类；不吸收无 manifest 的多文件“提交完成”**。 |
| GPU/CPU 资源 | 研究 ImageBind `.cuda()`；桌面主进程锁保护单例；`get_imagebind_device` CUDA 优先否则 CPU | 设备探测、模型加载/释放、tensor 转 CPU、显存采样 | 模块声明每阶段的 GPU 需求 | GPU 租约、显存预算、OOM 处置、进程隔离、强杀后回收 | 网关显示资源/任务状态，不在请求线程持有 GPU | **吸收资源声明与独立 provider 进程；当前无显存预算/OOM恢复，不能算生产治理**。 |

**单一 owner 规则**：支持库只实现可替换原子能力；知识模块只编排媒体领域流程；运行核心只负责任务、租约、资源、制品和终态；网关只负责认证/输入校验/命令接受/状态查询/取消和统一错误。任何“worker 直接写多个 JSON、renderer 自己轮询并解释状态、模块各自调用 OpenAI/ImageBind”的做法均属于侧链，不作为底座接入方案。

### 15.2 唯一摄取链路（目标装配，不冒充当前已实现）

当前代码能证明的桌面链路是 `upload → multiprocessing.Process → VideoRAG.insert_video`；后续将它收敛为以下**唯一规范链路**。箭头左侧是调用者，括号内是应由对应层承担的契约；没有括号内能力的部分是当前缺口。

```text
Electron renderer / 外部调用方
  → 网关: POST /sessions/{session_id}/videos/upload
      (认证、路径/文件输入校验、幂等键、创建持久 task_id；不能以 success=started 代表完成)
  → 运行核心: 提交“媒体摄取任务”
      (队列、owner、deadline、cancel token、资源预算、状态 accepted→running)
  → 知识模块: 视频摄取编排器
  → 支持库: 媒体探测/安全打开/唯一 media_id
  → 支持库: 时间片段采样器
      (segment_id、start/end、frame_times、audio 制品、采样参数和模型/版本指纹)
  → 支持库: ASR provider + caption provider
      (逐段结果、错误码、重试记录；OCR 未实现，不能隐式加入)
  → 知识模块: 统一 segment record
      (media_id + segment_id + 时间范围 + transcript + caption + frame refs)
  → 支持库: 文本 embedding / ImageBind 视觉 embedding
  → 知识模块: 跨模态索引编排
      (chunk、entity/relation、segment vector、反向 segment evidence)
  → 运行核心: manifest/版本化制品原子提交
      (所有索引文件可读、摘要一致、任务终态 succeeded；失败转 failed/partial，不能伪装完成)
  → 网关: GET /tasks/{task_id} / 事件或轮询
      (只投影统一状态、进度、制品引用和可审计错误)
```

当前源码与这条规范链的偏差：`upload_video` 接受任意存在路径；`start_video_indexing` 先写初始 `status.json` 后直接 `Process.start()`；`insert_video` 先写 `video_path_db`，再分段/ASR/caption/segment vector，随后 `ainsert` 建 text/entity/graph；没有 task id、manifest、跨文件事务或幂等键。以上事实分别见 `videorag_api.py:998-1046`、`videorag_api.py:349-387`、`videorag.py:298-410`、`videorag.py:449-529`。

### 15.3 唯一检索链路（当前源码顺序与底座归属）

```text
网关: POST /sessions/{session_id}/query
  → 运行核心: 创建 query task（当前仅 query_status + Process）
  → 知识模块: 规范化 query
  → 支持库: 文本 embedding → chunks_vdb.query(top_k)
  → 知识模块: 读取 text_chunks，截断 naive context
  → 支持库: cheap LLM 改写实体检索式
  → 支持库: entities_vdb.query
  → 知识模块: NetworkX/Neo4j 邻接 → text chunk source_id → segment_id
  → 支持库: cheap LLM 改写视觉检索式
  → 支持库: ImageBind text embedding → video_segment_feature_vdb.query
  → 知识模块: 图路 segment_id ∪ 视觉路 segment_id，排序、去重、候选过滤
  → 支持库: best LLM 过滤候选段
  → 支持库: cheap LLM 提取细 caption 关键词
  → 支持库: 原视频按 segment 时间范围细采样 + caption
  → 知识模块: 生成带 video_name/start_time/end_time/content 的 evidence context
  → 支持库: best LLM 生成回答
  → 运行核心: 写 answer artifact、证据/模型/版本/耗时、终态
  → 网关: 返回 task 结果及 evidence 引用
```

当前实现证据为 `Vimo-desktop/python_backend/videorag/_op.py:574-732`，桌面 worker 在 `videorag_api.py:715-831` 固定 `QueryParam(mode="videorag")` 且 `wo_reference=True`。因此“图路 + 视觉向量路 + 细 caption”是源码可吸收的**唯一检索编排**；研究版和桌面版不能各自成为第二个生产入口。`videorag_multiple_choice` 的 JSON `while True` 重试（`_op.py` 后段）只能隔离为研究评测脚本，禁止纳入无界生产链。

### 15.4 跨模态索引的规范记录

底座不直接采用当前散落键，而应把每个索引对象统一包在可校验记录中：

| 记录 | 必须字段 | 当前来源 | 生产映射 |
|---|---|---|---|
| `media` | `media_id`、来源引用、媒体格式、时长、fps、摘要、摄取版本 | `video_name -> video_path`（`videorag.py:311-320`） | 支持库探测 + 运行核心制品登记；原始路径不得作为跨层唯一 id |
| `segment` | `segment_id`、`media_id`、整数/浮点 `start/end`、采样参数、音频/视频制品引用 | `segment_index2name`、`segment_times_info`（`_videoutil/split.py:18-65`） | 知识模块领域记录；禁止以 `video_name_index` 猜测时间 |
| `transcript` | `segment_id`、文本、语言、ASR provider/model、状态和错误 | `transcripts[index]`（研究 `asr.py:8-29`；桌面 `asr.py:44-100`） | 支持库 provider 结果 + 模块绑定；缺失段必须显式 `partial` |
| `caption` | `segment_id`、粗/细描述、帧引用、caption model、prompt/version、状态 | `merge_segment_information`（`caption.py:88-97`）、检索后二次 caption | 知识模块制品；空字符串不能等价于成功描述 |
| `embedding` | `segment_id`/`chunk_id`、模态、维度、模型指纹、向量制品、归一化规则 | NanoVectorDB `__id__`/`__vector__`（`vdb_nanovectordb.py:34-74,96-142`） | 支持库索引存储；索引 manifest 锁定维度/模型，禁止静默混库 |
| `evidence` | query task、segment_id、时间范围、命中来源、排序分数、最终引用 | `_op.py:643-715` 仅拼 CSV 文本 | 知识模块输出 + 运行核心审计；网关只返回引用句柄 |

`video_name = basename.split('.')[0]`、`chunk-<md5(content)>`、`eval(time)` 和 `video_name_index` 均是当前实现细节，不是可跨项目复用的公共契约：同名视频、相同文本、下划线名称和恶意时间字符串都会造成碰撞或安全风险。

### 15.5 资源生命周期映射（四种终态）

| 资源 | 创建/持有 | 正常完成 | 业务失败 | 超时/主动取消 | 宿主/worker 崩溃 | 底座 owner |
|---|---|---|---|---|---|---|
| 原始媒体引用 | 网关验证，摄取模块读取 | 只保留受控引用/元数据 | 不删除用户原件，撤销本次引用 | 解除任务引用 | 重启扫描未完成引用 | 支持库+运行核心制品登记 |
| `_cache` mp3/mp4/帧 | `split_video`/`saving_video_segments` 创建，worker 持有 | 索引提交后删除并记录删除结果 | 失败也必须 finally 清理或转隔离区 | cancel handler 触发子进程组终止后清理 | 启动恢复扫描孤儿目录、按 task/lease 判断可删 | 支持库文件能力 + 运行核心清理 |
| VideoFileClip/ffmpeg | MoviePy/ffmpeg 创建，局部函数持有 | context manager/进程组回收 | 捕获异常后关闭所有句柄 | deadline/cancel 强杀整组并 wait | 进程组回收 + ps/句柄检查 | 支持库进程组管理 |
| ASR/caption/LLM HTTP | provider client/async task | 显式关闭/排空，记录 provider 请求 | 统一错误码和重试账本 | request deadline + cancel event；不把网络断开当后台任务完成 | 远端请求不可撤回，记录 orphan/未知结果 | 支持库 provider + 运行核心监督 |
| ImageBind/Whisper/MiniCPM GPU | 模型 owner 加载；当前研究版 storage 内部加载，桌面 Flask 单例 | 引用归零后 unload、释放显存、记录峰值 | load/inference 失败转 provider error 并释放 | 只在安全边界终止推理进程，释放模型 | 独立 provider 进程退出，主进程重建；主进程硬崩溃只能 OS 回收 | 运行核心 GPU lease + 支持库 provider |
| KV/vector/GraphML/Neo4j | VideoRAG storage 持有内存/连接 | manifest 校验后原子发布 | 临时版本隔离，不能把部分写入激活 | 取消时丢弃未提交版本/回滚引用 | 恢复扫描 manifest，重建或标记损坏 | 运行核心制品/事务 |
| `status.json`/task state | 当前 worker 读改写；目标为状态机 owner | `succeeded` 带制品和证据 | `failed` 带错误/重试 | `cancelled` 或 `timeout`，不可继续写 completed | `crashed`/`unknown`，重启恢复判定 | 运行核心任务状态；网关只读投影 |
| Electron session JSON/log | Electron main / Flask 日志写入 | 原子/版本化提交 | 保留错误日志，不能声称删除成功 | cancel 不应覆盖历史证据 | 备份/恢复或标损坏 | 支持库文件原子写 + 运行核心证据 |

当前实现的真实缺口：`write_status_json` 只有单文件临时 rename，没有锁/版本；`JsonKVStorage`、NanoVectorDB、NetworkX 各自保存，没有跨文件事务；`delete_session` 只终止进程，不删除 Python 工作目录；HTTP `requests.Session` 没有显式 close。这些不是待实现细节，而是禁止直接复用为生产底座的原因。

### 15.6 失败、超时、取消、OOM、崩溃矩阵

| 场景 | 当前源码行为/证据 | 当前等级 | 生产底座处理与裁决 |
|---|---|---|---|
| 输入路径不存在/空列表 | upload 路由 400；只做 `os.path.exists`，无格式/大小/沙箱 | L1/L2 | 网关 + 媒体支持库拒绝，记录稳定 `INPUT_INVALID`；**不吸收任意路径** |
| 空 query | `/query` 对空字符串未拒绝，仍启动 worker；ImageBind encode 路由自身才拒绝空 query | L1 | 网关统一拒绝或显式 `QUERY_EMPTY`；不得让 worker 才发现 |
| 媒体损坏/ffmpeg失败 | `split_video`/MoviePy 异常向上冒泡；桌面 worker 写 indexing `error`；无回滚 | L1 | 支持库返回 `MEDIA_INVALID`，运行核心隔离临时制品并清理 |
| 单段 ASR失败 | `as_completed` 捕获异常并继续，返回部分 transcripts；后续 caption 仍可能运行 | L1 | 模块显式 `partial`，策略由契约决定“跳段/重试/失败全任务”，不能假完成 |
| caption段失败 | `_process_single_caption` 返回空字符串；检索细 caption失败返回 Error 文本 | L1 | 空结果必须带 provider error；是否可降级需模块契约，不得静默成功 |
| embedding/ImageBind断线 | worker HTTP client 单请求 timeout=1800 秒，异常上抛，worker 写 error；无总 deadline/重试 | L1 | provider timeout + 可重试错误码 + 任务总 deadline；取消传播到子进程 |
| LLM rate limit/连接错误 | OpenAI/桌面兼容实现 `tenacity` 最多 5 次，指数等待 4–10 秒；DashScope ASR/部分 caption 无统一 timeout | L1 | 运行核心按 provider 预算重试，统一截止时间；超出转 `DEPENDENCY_TIMEOUT` |
| 前端 axios 超时 | upload 60s、initialize 120s、load/release 180s；后端任务继续运行 | L1 | 网关请求 timeout 与任务 deadline 分离；返回 task id，不能把 `ECONNABORTED` 当取消 |
| 用户 terminate | `terminate()` → join 5 秒 → kill；只按 `chat_id` 查索引键，`<chat_id>_query` 可能漏杀；状态只写 indexing terminated | L1 | 运行核心按 task id/进程组取消，幂等写 `cancelled`，排空/回收/读回终态 |
| CUDA/CPU OOM | 代码未见显存预算、`torch.cuda.OutOfMemoryError` 专门处理或自动降级；研究版 `.cuda()` 可能直接抛/进程退出；桌面 manager 只记录通用异常 | L0/L1 | GPU lease 预留/峰值监控；OOM → 释放/隔离 provider worker、可重试或降级 CPU（需契约）；禁止主网关被拖垮 |
| worker SIGTERM/SIGKILL/异常退出 | worker try/except 只能覆盖 Python 异常；硬杀不写 error；状态可永久 processing；缓存/部分索引残留 | L1 | 独立进程组、exit code/signal 记录、启动恢复 `crashed`、制品 manifest 对账和孤儿清理 |
| Flask/Electron 宿主崩溃 | `atexit`/SIGINT/SIGTERM 尝试 cleanup；硬崩溃不保证执行；重启不恢复历史 worker | L1 | 运行核心持久任务+租约；宿主重启扫描 active lease，判定恢复/失败，不重复建索引 |
| 多 worker 并发写状态 | `read→merge→rename` 无锁，最后写者可覆盖字段；indexed list append 也无并发合并 | L1 | 唯一状态写 owner/CAS；模块只发事件，禁止直接写 status JSON |
| 部分索引提交 | KV/vector/GraphML 分别 save，无跨文件事务/manifest；`ainsert` finally 会调用保存回调 | L1 | 版本化索引 bundle + manifest 原子激活；失败隔离旧版本，支持重建 |
| 多选题非 JSON | `while True` 无限重试，未见全局 timeout/cancel | L1 | 研究脚本隔离；生产必须最大尝试次数+deadline+结构化解析错误 |
| 删除 session | 路由忽略 `delete_session` 返回值仍返回 success；不删除工作目录 | L1 | 删除命令应返回真实终态，引用归零后 GC，失败可重试并留证据 |
| 外部远端任务断线 | DashScope/LLM 调用未建立远端 job id/撤回协议 | L1 | 记录未知结果；幂等 key + provider request id，不能重复计费/重复写入 |

### 15.7 研究脚本、桌面 Beta 与生产能力的边界

| 能力 | 研究脚本 `VideoRAG-algorithm/` | `Vimo-desktop` Beta | 可否直接叫生产能力 |
|---|---|---|---|
| 摄取入口 | Python `VideoRAG.insert_video()`，示例/notebook/复现实验驱动 | Electron IPC→Flask upload→worker | 否；两者都是研究/原型入口，须经统一网关适配 |
| ASR/caption | 本地 faster-whisper + MiniCPM-V/本地 caption 路径 | DashScope ASR + OpenAI-compatible 多图 caption | 否；provider、密钥、版本、超时未形成统一可验证契约 |
| ImageBind | `vdb_nanovectordb.py` 每次 storage `upsert/query` 内 `.cuda()` 创建模型 | Flask 单例加载，worker HTTP 调用，释放有 `to('cpu')`/`empty_cache` | 否；桌面版更接近可隔离原型，但无 OOM/任务恢复验收 |
| 任务并发 | caption/切段使用 `multiprocessing.Process`、`Manager.Queue`/dict | index/query 各一个 `multiprocessing.Process`，不用 Queue/持久队列 | 否；运行核心需唯一队列/任务状态 |
| 持久索引 | 文件 KV/NanoVectorDB/GraphML，Neo4j/HNSW 是可选替换 | 同一套 storage 写 session 目录 | 否；无 manifest、版本、跨文件事务和恢复 |
| 检索/回答 | 研究函数/Notebook 可直接调用，含 multiple-choice 无限 JSON 重试 | 查询 worker 固定 `wo_reference=True`，前端轮询 | 否；只能作为模块原型和评测脚本 |
| 前端/网关 | 无生产 HTTP 网关 | Electron/Flask 有路由、CORS 全开、本机路径直传 | 否；应改为统一网关适配层，补认证、授权、限流、task id |
| 测试 | 仓库没有匹配 `*test*` 的测试文件/目录；README/notebook 不是测试 | package 只有 `format/lint/dev`，未见后端测试脚本 | 否；当前核对只可声明静态证据，不得把示例运行当回归 |

### 15.8 后续能力裁决表

| 候选 | 结论 | 原因/边界 |
|---|---|---|
| `媒体摄取.安全打开与元数据` | **吸收** | 入口与媒体读取是通用原子能力；必须去掉任意本机路径直传。 |
| `媒体片段.时间轴采样` | **吸收** | 30 秒段、粗帧、细帧和音频是稳定领域原子；公共输出改为结构化时间值。 |
| `媒体转写.ASR` / `媒体描述.Caption` | **吸收/升级现有支持库** | provider 可替换、并发/超时/部分成功要进入统一契约。 |
| `媒体文字识别.OCR` | **待核** | 当前源码无 OCR 入口；先登记缺口，禁止从 caption 推导实现。 |
| `跨模态嵌入.ImageBind` | **吸收为 provider 适配** | 模型/设备/维度/批次可复用；模型必须脱离知识模块并独立治理。 |
| `视频知识索引` | **吸收为知识模块** | chunk、entity/relation、segment vector 三类索引由一个模块编排；不复制存储实现。 |
| `视频检索问答` | **吸收为知识模块** | 唯一融合链为文本→图→视觉→过滤→细 caption→回答；引用必须保留。 |
| `视频任务队列/状态` | **升级运行核心** | 当前 Process + JSON 是原型，不能让支持库或网关各建一套。 |
| `制品/manifest/恢复` | **升级运行核心** | 当前多文件独立写入无原子 bundle、摘要、恢复和 GC。 |
| `GPU lease/OOM/crash` | **新建运行核心原子能力** | 当前仅有锁、to CPU、empty_cache 和粗略 cleanup，无显存预算和崩溃终态。 |
| `Flask/Electron 专属 VideoRAG API` | **隔离为项目适配层/网关适配** | 不把 `/api/imagebind/*`、`status.json`、IPC 名称提升为平台公共契约。 |
| `MiniCPM/Whisper/DashScope/OpenAI` 具体绑定 | **隔离 provider** | 具体模型和密钥随部署变动；公共模块只能依赖能力 id。 |
| 论文“百小时单 GPU/分层上下文编码” | **废弃为实现结论，保留为 L0 声明** | README 有宣传，当前源码和当前核对没有性能、容量、L4 证据。 |

### 15.9 后续验收等级与可接受证据

| 等级 | 对本项目的严格含义 | 当前核对状态 | 不能越级的例子 |
|---|---|---|---|
| L0 | README/论文/注释/接口声明，或“应当如何映射”的设计 | README 的百小时/单 GPU、论文式双通道表述、OCR 缺口与平台候选映射 | 不能证明函数可运行、不能证明 provider 可用 |
| L1 | 当前源码存在且调用关系可定位 | 研究 `insert_video/query`、桌面 Flask/IPC/worker、split/ASR/caption/embedding/storage/RAG 入口 | 不能证明依赖安装、模型权重、外部服务、清理 |
| L2 | 当前核对静态检查通过 | 既有 Python AST/compileall 记录、路径/函数/路由读取、OCR/测试文件搜索；静态检查不加载重依赖 | 不能称“测试通过”或“端到端通过” |
| L3 | 隔离环境真实执行一个组件并读回终态 | 当前核对未做视频、ASR、caption、ImageBind、向量/图、Flask 服务或 Electron 执行，故没有 L3 | 仅 HTTP `success:true`/worker 自报/日志不够 |
| L4 | 从网关/IPC→任务→摄取或查询→模型/provider→索引/回答→状态、制品、进程/GPU清理全部读回 | 当前核对未做，明确为未验证 | 不能把前端启动、README benchmark 或局部函数调用当 L4 |

生产接入的最低验收应按 L0→L1→L2→L3→L4 顺序推进：先固定 `media/segment/transcript/caption/embedding/evidence/task/artifact` 契约，再在隔离目录使用短视频和可替换 provider 做真实组件验证，最后才接 GPU/外部模型和 Electron。每次 L3/L4 都必须记录命令、退出码、任务终态、制品可读性、进程组/PID、ffmpeg、临时目录、GPU/模型释放结果；缺任一项只能保留较低等级。

## 16. 后续证据与修改收口

### 16.1 当前核对新增/复核证据路径

- `VideoRAG-algorithm/videorag/videorag.py:202-432`：研究入口、`Manager`/子进程、`.cuda()` ImageBind、索引保存、查询入口。
- `VideoRAG-algorithm/videorag/_videoutil/asr.py:8-29`：本地 `WhisperModel` 逐段 ASR。
- `VideoRAG-algorithm/videorag/_storage/vdb_nanovectordb.py:75-145`：研究版每次向量写入/查询加载 ImageBind 并 `.cuda()`。
- `Vimo-desktop/python_backend/videorag_api.py:98-330`：ImageBind 单例、锁、HTTP client、1800 秒请求 timeout、cleanup。
- `Vimo-desktop/python_backend/videorag_api.py:336-568`：直接 `multiprocessing.Process`、JSON 状态、terminate/cleanup、无持久 Queue。
- `Vimo-desktop/python_backend/videorag_api.py:587-831`：索引/query worker、模型配置、错误投影、`wo_reference=True`。
- `Vimo-desktop/python_backend/videorag_api.py:847-1320`：Flask 路由、重复 `/api/imagebind/status`、任务接受与状态读取、删除/终止语义。
- `Vimo-desktop/python_backend/videorag/_videoutil/split.py:10-84`、`asr.py:44-142`、`caption.py:31-146`、`feature.py:10-30`：片段、采样、ASR、caption、ImageBind 调用。
- `Vimo-desktop/python_backend/videorag/videorag.py:298-537`、`_op.py:159-179,357-478,574-906`：索引、图/向量、多路检索和回答。
- `Vimo-desktop/src/main/handlers/videorag-handlers.ts:47-225`、`src/renderer/src/hooks/useVideoRAG.ts:119-180`：Electron 启动/发现、axios timeout 和上传/状态投影。
- `VideoRAG-algorithm/README.md:37-49,63-110`：仅作为 L0 宣传/依赖线索，不作为容量或 GPU 验收。

### 16.2 测试/验证边界

本仓库没有匹配 `*test*` 的测试文件/目录；`package.json` 只声明 `format`、`lint`、`dev`，未声明后端测试入口。当前核对没有安装依赖、下载权重、启动 Flask/Electron、调用外部 API、处理测试视频、跑 GPU/OOM/取消/崩溃场景；因此本文件新增结论最高仍为 **L2（静态取证）**，L3/L4 均明确未验证。OCR 搜索仅命中 `pnpm-lock.yaml` 中与 OCR 无关的字符串片段，未发现 OCR 实现入口。

### 16.3 当前核对修改边界（再次确认）

当前核对只修改目标根 `ARCHITECTURE.md`，没有修改源码、依赖、配置、测试、README、旧细探、Git 或运行数据。误绑定的 `project_context` 返回了华世王镞_v3 环境，已记录为环境问题并完全丢弃其代码地图、任务和证据；本节及全文的源码结论均来自目标目录本地读取。

## 17. 摄取、任务与通用底座的补充映射

本节把源码中容易被“上传成功”“索引完成”或“GPU 可用”等表述掩盖的边界，按一个媒体任务从输入到制品的生命周期重新归档。它仍然是静态源码事实与底座设计映射，不是对当前仓库缺口的实现承诺。

### 17.1 摄取与时间片段的实际数据流

当前两个实现根都把本机文件路径当作输入，而不是接收字节流：研究版由 `VideoRAG.insert_video(video_path_list)` 直接处理，桌面版由 Electron IPC 将 `video_path_list` 传给 Flask，再由 `start_video_indexing` 派生 worker。桌面路由只检查路径存在，未建立认证、所有权、路径沙箱、大小配额或内容摘要，因此“upload”实际语义是“登记并异步处理已有路径”。

单视频的可观察步骤为：

```text
原始路径
  → basename 派生 video_name（当前存在碰撞风险）
  → split_video
      → 约 30 秒一个 segment
      → segment_index2name
      → segment_times_info（时间范围与粗采样 frame_times）
      → _cache/<video_name>/mp3 与 mp4
  → ASR：每段音频得到 transcript
  → caption：粗采样帧 + transcript 得到段描述
  → merge_segment_information
      → content / transcript / frame_times / time 等段记录
  → ImageBind：段视频向量
  → 文本 chunk、实体/关系图、文本/实体向量
```

索引后查询还会从原视频按候选段时间范围重新打开媒体，使用更密的细采样帧生成细 caption，再把时间、视频名和内容序列化为回答上下文。故时间坐标不是展示字段，而是 ASR、caption、视频制品、向量命中和最终 evidence 的连接键。底座应使用数值化且可校验的 `start`/`end`（明确单位、闭开区间和时区无关性），并禁止沿用源码中的字符串时间 + `eval` 解析。

### 17.2 ASR、OCR、caption 与 embedding 的边界

| 能力 | 当前源码证据 | 输出与缺口 | 通用底座映射 |
|---|---|---|---|
| ASR | 研究版 `faster_whisper`；桌面版 DashScope `Recognition.call`，最多 5 个并发 | transcript 按段返回；桌面单段异常被记录后继续，缺段没有统一状态 | `媒体转写.ASR` provider；结果必须带语言、模型、请求、重试、错误和 `partial` 标记 |
| OCR | 未发现 OCR provider、帧文字识别或 OCR 路由 | caption 中出现的视觉描述不能证明文字识别；当前无 OCR 能力 | 预留 `媒体文字识别.OCR`，未实现、未注册、不得由 caption 代替 |
| caption | 研究版 MiniCPM-V；桌面版 OpenAI-compatible/DashScope 多图请求；查询阶段还会细 caption | 产生粗/细描述；单段失败可能退化为空字符串或错误文本 | `媒体描述.Caption` provider；空结果必须携带失败原因和采样帧引用 |
| 文本 embedding | LLM 配置的 OpenAI/Azure/Ollama 兼容 embedding，写入 chunks/entities VDB | 维度由配置决定，当前文件索引无统一模型 manifest | `文本嵌入` provider；必须锁定维度、模型指纹、归一化和批次 |
| 视觉/跨模态 embedding | ImageBind 1024 维；研究版 storage 内 `.cuda()`，桌面版 Flask 单例并经 HTTP 给 worker | 视频段和文本 query 进入同一检索空间；HTTP 返回 pickle/base64 | `跨模态嵌入.ImageBind` provider；公共协议禁止暴露 pickle 和项目私有路由 |

当前链路没有独立 OCR 阶段。底座若启用 OCR，应把 OCR 作为可选的、可重试的片段 evidence 来源，与 transcript/caption 并列，而不是把 OCR 结果塞进 caption 字段后丢失来源和置信度。

### 17.3 索引、检索与 RAG 的单一编排

索引由三类互相关联的对象组成：

1. **时间片段事实**：`video_segments` 保存每个视频的段记录，段记录连接时间、transcript、caption 与帧信息。
2. **文本知识路**：`get_chunks` 将段内容按约 1200 token 合并；文本 chunk 写入 `chunks_vdb`/`text_chunks`，实体与关系抽取后写入 `entities_vdb` 和 NetworkX/Neo4j 图。
3. **视觉段路**：`video_segment_feature_vdb` 保存 ImageBind 段向量，以段 id 回指视频段和原视频。

查询的源码顺序是文本向量初召回 → 文本块上下文 → cheap LLM 改写实体检索 → 实体向量与图邻接得到段 id → cheap LLM 改写视觉查询 → ImageBind query embedding 做视觉召回 → 合并、排序和 best LLM 候选过滤 → 原视频细采样/细 caption → best LLM 生成回答。知识模块的公共输出应始终保留 `segment_id`、`media_id`、`start/end`、召回来源、分数和证据引用；桌面 worker 当前设置 `wo_reference=True`，只能视为 Beta 展示选择，不能成为平台 RAG 默认契约。

### 17.4 任务队列与状态机映射

当前没有持久任务队列：桌面 Flask 直接 `multiprocessing.Process.start()`，研究版仅在保存切段与 caption 时使用 `Manager`/`Queue` 传递错误；任务状态落在 session 目录 `status.json`，索引键为 `chat_id`，查询键为 `chat_id_query`。前端的 2 秒轮询和 axios 超时都只是观察/请求层行为，不是任务调度或取消。

通用底座唯一 owner 应是运行核心，推荐规范状态为：

```text
accepted → queued → running → succeeded
                         ├→ failed
                         ├→ partial
                         ├→ timeout
                         ├→ cancelled
                         └→ crashed / unknown
```

每个任务至少需要持久 `task_id`、任务类型（摄取/索引/查询）、session/media 范围、幂等键、owner、创建/开始/截止时间、attempt、worker PID/进程组、资源租约、取消原因、错误码以及制品 manifest 引用。网关只负责提交、查询和取消；知识模块只发阶段事件；worker 不得直接把 `status.json` 当权威状态库。取消必须按 task id 命中索引和查询两类任务，先传播 cancel token，再终止进程组、等待、回收临时制品并读回终态。

### 17.5 文件制品与提交边界

当前制品分为原始路径引用、`_cache` 下的 mp3/mp4、KV JSON、NanoVectorDB JSON、GraphML/Neo4j 数据、Electron 会话 JSON、`status.json` 和 ImageBind 权重。它们由不同对象分别写入；只有 status 单文件使用 `.tmp` + rename，索引文件之间没有跨文件事务、manifest、摘要或版本激活。worker 异常和硬杀可能留下部分索引、永久 `processing` 状态、ffmpeg 子进程和大体积 cache；删除 session 也不会删除 Python 工作目录。

底座应把一次索引视为不可变制品 bundle：先在 task 临时版本中写入媒体元数据、segment、transcript/caption、embedding、chunk、图和 evidence 索引；生成 manifest（版本、文件清单、大小、摘要、模型/参数指纹、父版本和任务 id）；逐项读回校验后原子激活。失败、取消、超时或崩溃只能留下隔离版本并标为不可用，不能激活为 succeeded。启动恢复要扫描 active lease、`.tmp`、孤儿 cache、未完成 manifest 和 worker PID，按租约与摘要决定恢复、重建、隔离或回收。

### 17.6 GPU、CPU 与外部 provider 治理

ImageBind 是当前最明确的重型资源：研究版在向量存储操作中创建 CUDA 模型，桌面版把模型提升为 Flask 主进程单例，以锁保护并通过 HTTP 为 worker 提供编码；释放时尝试移到 CPU、删除对象并调用 `torch.cuda.empty_cache()`。代码没有显存预算、峰值采样、OOM 专门分支、模型加载 deadline 或 provider 进程健康租约；README 所称单 RTX 3090、百小时处理只是 L0 声明。

通用底座映射为：运行核心分配 GPU lease 和显存预算；provider 进程独占模型并报告设备、模型指纹、批次、峰值显存、退出码；知识模块声明阶段资源需求，不直接持有 GPU；OOM 进入可区分的 `RESOURCE_OOM`，按契约释放并隔离 provider、重试或降级 CPU；网关只投影资源与任务状态，不在请求线程同步持有 GPU。ASR、caption、LLM、Neo4j 等外部 provider 还必须分别记录 request id、deadline、重试次数、限流/断线错误与远端未知结果；断开 HTTP 连接不能伪装成取消远端任务。

### 17.7 通用底座最终落点

| 底座层 | 唯一职责 | 不应承接的当前实现 |
|---|---|---|
| 支持库 | 媒体探测/时间采样、ASR/OCR/caption/embedding provider、受控文件与进程组、向量/图存储原子驱动 | 不直接编排完整 VideoRAG，不暴露第三方异常、pickle 或 provider 密钥 |
| 知识模块 | 摄取阶段编排、统一 segment evidence、chunk/实体/关系/多模态索引、检索融合与回答 | 不创建第二套队列、任务状态、GPU 单例或文件事实源 |
| 运行核心 | 持久任务队列、状态机、deadline/cancel、worker lease、GPU/CPU 资源、制品 manifest、恢复/GC | 不理解 caption prompt、图检索策略或 Electron IPC 细节 |
| 网关/项目适配层 | 认证授权、输入校验、任务提交/查询/取消、统一错误与制品引用 | 不把 `success: started` 当完成，不让 renderer 自行拼检索链，不接受任意本机路径 |

因此，VideoRAG 最值得吸收的是“时间片段作为统一 evidence 主键 + ASR/视觉描述/跨模态向量/文本图路的阶段化融合”；最不应吸收的是“Process + 无锁 JSON + 多文件独立保存 + 前端轮询”作为生产任务底座。当前仓库的事实结论仍为 L2，以上治理项均为通用底座映射或待实现边界。
