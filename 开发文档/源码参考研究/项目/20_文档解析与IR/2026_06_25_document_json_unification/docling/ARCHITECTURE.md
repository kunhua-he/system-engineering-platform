# Docling 架构建档

> 本文是目标仓库本地快照的架构事实基线。说明、备注、风险、结论使用中文；源码标识、类名、函数名、枚举值、路径和接口路径保留原文。

## 1. 建档范围与证据边界

### 1.1 目标

- 项目根目录：`/Users/hekunhua/Documents/Agent/github 源码参考/20_文档解析与IR/2026_06_25_document_json_unification/docling`
- 项目：`docling-project/docling`
- 用途：把 PDF、Office、HTML、Markdown、图片、XML、音频、视频等输入转换为统一的 `DoclingDocument`，再供 Markdown、HTML、DocTags、DocLang、JSON 或下游分块/RAG 使用。
- 许可证：MIT；模型及外部依赖仍须分别遵守其原始许可证。

### 1.2 已读取的权威材料

本次按“说明 → 架构文档 → 核心入口 → 数据模型 → API/服务客户端 → 测试”的顺序读取：

- `README.md`：项目定位、格式范围、Quickstart、CLI/Python 用法、MCP 和服务入口。
- `AGENTS.md`、`CLAUDE.md`：代码边界、目录约定、测试与检查命令；`CLAUDE.md` 通过 `@AGENTS.md` 复用规则。
- `pyproject.toml`、`packages/docling/pyproject.toml`、`packages/docling/README.md`、`packages/docling-slim/README.md`、`Makefile`、`uv.lock`：打包、依赖、extras、工作区、入口脚本和验证命令。
- `docs/concepts/architecture.md`、`docling_document.md`、`serialization.md`、`chunking.md`：公开架构、IR 结构、序列化和分块语义。
- `docling/document_converter.py`、`docling/backend/abstract_backend.py`、`docling/pipeline/base_pipeline.py`：转换入口、后端契约、流水线编排。
- `docling/datamodel/base_models.py`、`document.py`、`pipeline_options.py`、`datamodel/service/*.py`：输入、状态、错误、结果、选项和服务 wire model。
- `docling/service_client/client.py`、`_async_client.py`、`job.py`、`watchers.py`：同步/异步远程服务客户端、任务句柄、轮询和 WebSocket。
- 代表测试：`test_backend_docling_json.py`、`test_conversion_result_json.py`、`test_service_datamodels.py`、`test_service_client_sdk_unit.py` 及后端、管线、CLI、E2E 测试。
- 本文件已吸收此前 `细探-docling.md` 的源码分析结论；后续只维护本文件，旧细探笔记不再作为独立事实源。

### 1.3 证据限制

- 首次 `project_context` 返回的是另一项目 `华世王镞_v3` 及其根目录，不能作为本仓库身份、代码地图或验证证据；随后已用绝对路径重新核对本仓库。
- `codegraph_explore` 明确返回本目录及其上级没有 `.codegraph/`，因此本仓库没有可用代码图；没有把其他仓库的代码地图、记忆或验证记录混入本建档。
- 本次未安装依赖、未启动服务、未构建、未运行全量测试，也未修改源码/依赖/测试/配置。

## 2. 版本与快照基线

### 2.1 本地工作树

- 当前分支：`main`。
- 本地 `HEAD`：`9b51f4f857176cdd95cef53e2ec7f5f32ffbc6a5`。
- 本地 `HEAD` 提交主题：`fix: guard scipy import in to avoid crash in docling-slim[service-client] (#3860)`。
- `origin`：`https://github.com/docling-project/docling.git`。
- 建档前工作树存在一个未跟踪文件：`细探-docling.md`；本文件已读取并吸收其结论，随后完成单一文档收口。

### 2.2 远程版本信息与独立快照

`git ls-remote origin` 返回远程 `HEAD/main`：`06faa09deef1c195f2004224fa970f3caff23e0f`，与本地 `HEAD` 不同。因此本文的“已实现”结论以本地 `9b51f4f...` 为准；远程最新差异单独记录，不覆盖工作树。

按要求通过 `127.0.0.1:4780` 代理读取远程 SHA `06faa09deef1c195f2004224fa970f3caff23e0f` 的独立 raw 快照并做文本差异，确认远程已出现而本地尚未纳入的方向包括：

- `docling-slim` 版本从 `2.115.0` 变为 `2.121.0`，`docling-core` 下限从 `2.86.0` 变为 `2.91.0`。
- 新增 `format-iwork`、Apple Pages `IWORK_PAGES` 和 `EBCDIC` 输入格式及对应 backend/选项。
- `format-email` 增加 `python-oxmsg`，支持 `.msg`；音频依赖的 `whisper-s2t-reborn` 下限更新。
- uv 工作区新增 `packages/docling-client`。
- 远程 `document_converter.py` 已新增 `IWorkPagesDocumentBackend`、`EbcdicDocumentBackend` 路由。

上述远程差异只作为升级风险和未来复核线索，不是本地已实现能力。

## 3. 项目分层总览

```text
输入 Path / URL / DocumentStream / HttpSource
                 │
                 ▼
      _DocumentConversionInput.docs()
  下载/限流/格式识别/构造 InputDocument
                 │
                 ▼
       DocumentConverter.format_to_options
  InputFormat → FormatOption(backend + pipeline + options)
                 │
        ┌────────┴────────┐
        ▼                 ▼
Declarative backend    Paginated backend
直接产出 DoclingDocument 逐页产出 Page/预测
        │                 │
        │                 ▼
        │       BasePipeline.execute()
        │       _build → _assemble → _enrich
        │                 │
        └────────┬────────┘
                 ▼
       ConversionResult
  document / pages / status / errors / timings / confidence
                 │
       ┌─────────┼─────────┬─────────────┐
       ▼         ▼         ▼             ▼
   export     save/load   chunking   service client
 Markdown/   Conversion  Hierarchical/  docling-serve
 HTML/JSON   Assets ZIP   Hybrid
```

公开架构文档也明确了同一边界：`document converter` 为每种格式选择 backend、pipeline、options；结果持有 `DoclingDocument`，之后可 export、serialize 或 chunk（`docs/concepts/architecture.md:3-14`）。

## 4. 目录与模块边界

### 4.1 根目录

```text
 docling/
 ├── docling/                 # 主 Python 包，运行时转换核心
 ├── packages/docling/        # `docling` 全功能 meta-package
 ├── packages/docling-slim/   # slim 包 README；实际模块由根包构建
 ├── tests/                   # pytest、groundtruth 和输入样本
 ├── docs/                    # Zensical/MkDocs 文档、示例、集成说明
 ├── scripts/                 # 文档渲染、Tach 覆盖率、行数等维护脚本
 ├── pyproject.toml           # 根项目实际构建配置，项目名 `docling-slim`
 ├── uv.lock                  # uv 锁定依赖
 ├── Makefile                 # setup/check/validate/test/docs 命令
 ├── .github/                 # CI、格式、发布与辅助脚本配置
 ├── Dockerfile               # 容器构建入口
 ├── AGENTS.md / CLAUDE.md    # 代码代理和贡献约束
```

### 4.2 主包目录

当前本地快照的静态盘点：`docling/` 约 245 个文件；`backend/` 56 个 Python 文件；`pipeline/` 12 个 Python 文件；`datamodel/` 32 个文件；`service_client/` 7 个文件；`models/stages/` 含 12 个阶段子目录。

| 模块 | 边界与职责 |
|---|---|
| `docling/document_converter.py` | 唯一高层转换入口；格式白名单、选项归一化、输入迭代、pipeline cache、同步/批量转换。 |
| `docling/backend/` | 格式特定解析器；每个 backend 负责输入合法性、格式支持、分页能力、资源释放以及（声明式 backend）直接构造 `DoclingDocument`。 |
| `docling/pipeline/` | 结构化转换和模型富化流水线；包含普通、PDF、VLM、ASR、video、extraction 和 threaded 变体。 |
| `docling/models/` | 推理引擎、阶段模型、富化模型、插件工厂；模型是流水线能力，不是文档 IR 所有者。 |
| `docling/datamodel/` | 本地运行时数据模型和 Pydantic options；`DoclingDocument` 主体由外部 `docling-core` 定义。 |
| `docling/chunking/` | 从 `docling-core` re-export `BaseChunker`、`HierarchicalChunker`、`HybridChunker` 等。 |
| `docling/cli/` | `docling` 和 `docling-tools` CLI 的 Typer 应用、导出和远程转换命令。 |
| `docling/service_client/` | 对外部 `docling-serve` 的同步/异步 SDK，不是服务端实现。 |
| `docling/utils/` | 文件、模型、OCR、VLM、profiling、锁、视频帧等横切能力。 |
| `docling/experimental/` | 实验性 pipeline/model，不应视为稳定公共契约。 |

## 5. 核心转换入口与路由

### 5.1 `DocumentConverter`

文件：`docling/document_converter.py`。

- `FormatOption`（95-109 行）把 `pipeline_cls`、`backend`、`backend_options` 和 `pipeline_options` 组合成格式路由项；缺省 pipeline options 由 pipeline 类生成。
- `_get_default_option()`（259-300 行）将 `InputFormat` 映射为格式选项。当前本地格式覆盖 PDF、DOC/DOCX、PPT/PPTX、XLS/XLSX、ODF、HTML、Markdown、AsciiDoc、CSV、XML（USPTO/JATS/DocLang/XBRL）、DCLX、METS/GBS、JSON_DOCLING、图片、音频、视频、VTT、LaTeX、Email、EPUB、BoxNote 等。
- `DocumentConverter.__init__()`（323-397 行）默认允许所有 `InputFormat`，也允许调用方用 `allowed_formats` 和 `format_options` 缩小或替换边界；图片 backend 有兼容性归一化逻辑。
- `convert()`（431-494 行）是单文档便捷入口，内部委托 `convert_all()`。
- `convert_all()`（496-581 行）构造 `DocumentLimits` 和 `_DocumentConversionInput`，迭代产生 `ConversionResult`；`raises_on_error=True` 时非 `SUCCESS/PARTIAL_SUCCESS` 会抛 `ConversionError`。
- `convert_string()`（583-656 行）只接受 `MD`、`HTML`、`XML_DOCLANG`，把字符串包装为 `DocumentStream` 后走同一主链路。
- `_get_pipeline()`（696-723 行）以 `(pipeline_class, md5(model_dump(options)))` 为 key 缓存 pipeline，并通过 `_PIPELINE_CACHE_LOCK` 保护初始化。
- `_convert()`（658-694 行）按 `settings.perf.doc_batch_size` 分批；当 batch size 与 concurrency 条件满足时使用 `ThreadPoolExecutor`。

### 5.2 输入解析与安全边界

`docling/datamodel/document.py` 中 `_DocumentConversionInput.docs()`（616 行起）负责：

1. 处理本地 `Path`、URL 字符串、`DocumentStream`、`HttpSource`。
2. URL 通过 `docling_core.utils.file.resolve_source_to_stream` 下载，支持批量 headers、每个 `HttpSource` 的 headers 覆盖、`max_file_size` 限制。
3. 网络/来源错误转成带 `FailureCategory.SOURCE_UNAVAILABLE` 或 `POLICY` 的 invalid `InputDocument`，避免无条件中止整个输入迭代。
4. `_guess_format()`（763 行起）结合扩展名、MIME、文件内容探测、Office ZIP 内部文件、XML 根/DOCTYPE、CSV sniffing 和 METS tar 内容识别格式。
5. 构造 `InputDocument`，计算输入 hash、检查文件大小/页数/页范围，并初始化对应 backend。

`InputDocument`（125-375 行）把输入文件、`document_hash`、format、limits、page_count、backend 和拒绝原因收敛到一个对象；后端解析错误区分 `DocumentLoadError`（分类为 `BACKEND_FAILURE`）与其他内部异常（不伪装成输入错误）。

## 6. Backend 层

### 6.1 抽象契约

`docling/backend/abstract_backend.py`：

- `AbstractDocumentBackend`（19-52 行）要求构造函数、`is_valid()`、`supports_pagination()`、`supported_formats()`；默认 `unload()` 关闭 `BytesIO` 并清空引用。
- `PaginatedDocumentBackend`（54-64 行）增加 `page_count()`，供 PDF/图片等逐页处理。
- `DeclarativeDocumentBackend`（66-86 行）增加 `convert() -> DoclingDocument`，适合 DOCX、HTML、Markdown、XML、JSON 等直接构造统一 IR 的格式。

### 6.2 当前本地 backend 分类

- PDF：`pdf_backend.py`、`pypdfium2_backend.py`、`managed_pdfium_backend.py`、`docling_parse_backend.py`、`docling_parse_v2_backend.py`、`docling_parse_v4_backend.py`。
- Office：`msword_backend.py`、`msexcel_backend.py`、`mspowerpoint_backend.py`、`opendocument_backend.py`、`legacy_msoffice` 相关路径。
- Web/文本：`html_backend.py`、`md_backend.py`、`asciidoc_backend.py`、`latex_backend.py`、`csv_backend.py`、`webvtt_backend.py`。
- 结构化 XML：`xml/jats_backend.py`、`uspto_backend.py`、`xbrl_backend.py`、`doclang_backend.py`、`doclang_archive_backend.py`、`mets_gbs_backend.py`。
- 媒体/其他：`image_backend.py`、`email_backend.py`、`epub_backend.py`、`boxnote_backend.py`、`noop_backend.py`。
- 统一 JSON 输入：`json/docling_json_backend.py`。

### 6.3 JSON IR 往返

`DoclingJSONBackend`（`docling/backend/json/docling_json_backend.py:13-58`）是声明式 backend：

- 从 `Path` 或 `BytesIO` 读取 JSON。
- 通过 `DoclingDocument.model_validate_json()` 校验。
- 合法时 `convert()` 原样返回 `DoclingDocument`；非法时 `is_valid()` 为 false，`convert()` 抛保存的原始异常。
- 对应测试 `tests/test_backend_docling_json.py:17-59` 覆盖合法 JSON 的 `export_to_dict()` 等价性和非法输入拒绝。

## 7. Pipeline 层与状态语义

### 7.1 `BasePipeline.execute()` 生命周期

`docling/pipeline/base_pipeline.py:46-148` 定义稳定编排边界：

```text
_build_document(conv_res)
        ↓
_assemble_document(conv_res)
        ↓
_enrich_document(conv_res)
        ↓
_determine_status(conv_res)
        ↓
_unload(conv_res)
```

- `_build_document` 由子类实现，负责从 backend/页资源得到基础结构。
- `_assemble_document` 默认透传；分页 PDF pipeline 用它把页面预测装配成文档树。
- `_enrich_document` 遍历 `DoclingDocument.iterate_items()`，以模型声明的 batch size 分批调用 `enrichment_pipe`。
- 异常统一把结果置为 `FAILURE`；`raises_on_error=False` 时追加 `ErrorItem`，否则抛出以 pipeline 类名包装的 `RuntimeError`。
- 任何 pipeline 都在 `finally` 中释放资源。
- 若 `_determine_status` 返回 `SUCCESS` 但 `errors` 非空，统一降为 `PARTIAL_SUCCESS`（82-83 行），避免“有错误但报告纯成功”。

### 7.2 Pipeline 族

| Pipeline | 主要用途 |
|---|---|
| `SimplePipeline` | 声明式/非分页格式，调用 backend 直接得到 `DoclingDocument`。 |
| `StandardPdfPipeline` | PDF/图片的标准分页识别、布局、OCR、表格、阅读顺序、装配和富化。 |
| `LegacyStandardPdfPipeline` | 兼容旧 PDF 路径。 |
| `ThreadedStandardPdfPipeline` | 多阶段线程队列和有界批处理，适合吞吐型 PDF。 |
| `VlmPipeline` | 页面级视觉语言模型转换。 |
| `ExtractionVlmPipeline` | 面向结构化抽取的 VLM 路径。 |
| `AsrPipeline` / `AsrTranscriber` | 音频识别并生成时间化文本/字幕结构。 |
| `VideoPipeline` | 视频帧采样、代表帧与 ASR 组合。 |
| `BaseExtractionPipeline` | 抽取型 pipeline 公共骨架。 |

### 7.3 分页与错误

`PaginatedPipeline`（`base_pipeline.py:238-386`）按 `page_range` 建立 `Page`，以 `page_batch_size` 调用 `build_pipe` 阶段；支持 document timeout，并将超时、页 backend 无效等转为带页号和分类的 `ErrorItem`。`FailureCategory` 当前包括 `POLICY`、`CAPACITY`、`SOURCE_UNAVAILABLE`、`TARGET_UNAVAILABLE`、`TIMEOUT`、`INTERNAL`、`BACKEND_FAILURE`、`INFERENCE_FAILURE`、`UNKNOWN`。

状态枚举 `ConversionStatus`（`base_models.py:85-91`）：`PENDING`、`STARTED`、`FAILURE`、`SUCCESS`、`PARTIAL_SUCCESS`、`SKIPPED`。它不是严格持久化状态机；是一次转换生命周期及结果协议。

## 8. 数据模型与统一 IR

### 8.1 外部核心模型：`docling-core`

主包明确 re-export `docling_core.types.doc` 中的 `DoclingDocument`、`DocItem`、`TextItem`、`TableItem`、`PictureItem` 等；本仓库不包含其完整 schema。公开文档（`docs/concepts/docling_document.md:1-12`）说明 `DoclingDocument` 是 Pydantic 类型，支持：

- 文本、表格、图片等内容 item；
- `body`、`furniture`、`groups` 组成的层级树；
- 父子 JSON Pointer 与阅读顺序；
- 坐标、bbox、页面和 provenance；
- 对外导出和从头构造 API。

因此：`docling` 负责“把多格式内容转换成 IR”，`docling-core` 负责“定义 IR 与核心 serializer/chunker 基础类型”。

### 8.2 本地结果模型

`docling/datamodel/document.py`：

- `ConversionAssets`（394-584 行）保存版本、timestamp、status、errors、pages、timings、confidence、document；`save()` 将这些组件和 `document.export_to_dict()` 写入 ZIP，`load()` 逐项恢复。
- `ConversionResult`（587-595 行）在 `ConversionAssets` 上增加 `input: InputDocument` 和 assembled 信息。
- `Page`、`PagePredictions`、`AssembledUnit`、`ErrorItem` 等属于中间处理/诊断模型，不等同于最终 IR。
- `DoclingVersion` 记录 `docling`、`docling-slim`、`docling-core`、模型包、解析包、平台和 Python 版本，用于资产可追溯。

### 8.3 诊断模型

`ErrorItem`（`base_models.py:308-325`）至少记录 `component_type`、`module_name`、`error_message`、`category`、可选 `page_no`。`ConfidenceReport` 记录 parse/layout/table/OCR 分数，并计算 `mean_score`、`low_score` 和等级；服务层通过 `ConfidenceScores` 将 NaN 转为 JSON-safe 的 null。

### 8.4 序列化语义

- JSON/DocLang/DocTags/HTML 尽量保留表格 span；Markdown 和 LaTeX 当前会扁平化 rowspan/colspan（`docs/concepts/serialization.md:43-65`）。
- 需要准确表格结构时使用 `export_to_html()` 或 `export_to_dict()`，不能把 Markdown 视为完全无损 IR。
- 本地 `JSON_DOCLING` backend 支持“JSON 结果再次作为输入”，形成可再处理闭环；它不把 `docling-core` schema 复制到主仓库。

## 9. 模型、富化与资源边界

### 9.1 阶段模型

`docling/models/stages/` 当前包含：`layout`、`reading_order`、`page_preprocessing`、`page_assemble`、`ocr`、`table_structure`、`heading_hierarchy`、`code_formula`、`picture_classifier`、`picture_description`、`chart_extraction`、`vlm_convert`。

`ConvertPipeline`（`base_pipeline.py:149-235`）按 `PipelineOptions` 装配图片分类、图片描述、可选图表提取等 enrichment；重型模型通过延迟导入和可选 extras 避免 slim 基础导入时强制加载。

### 9.2 资源和配置

- `artifacts_path` 来自 pipeline options 或全局 settings，必须是目录；该目录承载本地模型文件。
- `DocumentLimits` 提供 `max_num_pages`、`max_file_size`、`page_range`；远程输入还支持 headers。
- `PipelineOptions`/`ConvertDocumentsOptions` 用 Pydantic 约束 OCR、PDF backend、table mode、pipeline、超时、图片输出、VLM、富化和自定义 preset/config。
- 本地 PyTorch、OCR、VLM、ASR、远程 Triton、ONNX、HTML rendering 等均由 extras 按需安装；模型权重不是源码仓库的一部分。

## 10. 分块与下游 RAG

`docling/chunking/__init__.py` 仅从 `docling-core` re-export `BaseChunk`、`BaseChunker`、`HierarchicalChunker`、`HybridChunker` 等。

- `HierarchicalChunker` 直接利用 IR 层级和 headers/captions 生成结构感知块。
- `HybridChunker` 在层级分块上加入 tokenizer-aware 拆分和同 heading/caption 的合并，支持表头重复和 overflow 策略。
- `BaseChunker` 契约为 `chunk(DoclingDocument) -> Iterator[BaseChunk]` 与 `contextualize(BaseChunk) -> str`（`docs/concepts/chunking.md:16-36`）。
- 分块可以作为本地库调用，也可通过服务层 `/v1/chunk/{chunker}/...` 远程执行。

## 11. CLI、服务客户端与 API 边界

### 11.1 CLI

`pyproject.toml` 的 `[project.scripts]` 定义：

- `docling = "docling.cli.main:app"`
- `docling-tools = "docling.cli.tools:app"`

`docling/cli/main.py` 是 Typer 应用；CLI 依赖在 `docling-slim[cli]` 中，不属于最小基础依赖。README 的最小用法是 `docling <url-or-path>`，也可选择 VLM pipeline。

### 11.2 外部 `docling-serve` HTTP API

本仓库没有服务端路由；`docs/usage/api_server/rest_api.md` 明确标注内容同步自 `docling-serve v1.21.0`。服务端边界包括：

| 路径 | 方法/协议 | 语义 |
|---|---|---|
| `/health`、`/version` | GET | 健康和版本。 |
| `/v1/convert/source` | POST | URL/base64 source 同步转换。 |
| `/v1/convert/file` | POST multipart | 文件上传同步转换。 |
| `/v1/convert/source/async` | POST | URL source 异步任务。 |
| `/v1/convert/file/async` | POST multipart | 文件异步任务。 |
| `/v1/convert/source/batch` | POST | 批量 source 任务。 |
| `/v1/status/poll/{task_id}` | GET | 带 server wait 的状态轮询。 |
| `/v1/status/ws/{task_id}` | WebSocket | 状态推送。 |
| `/v1/result/{task_id}` | GET | 完成结果。 |
| `/v1/chunk/{chunker}/source/async`、`/file/async` | POST | 远程分块任务。 |

服务客户端 wire model：

- 请求：`ConvertDocumentsOptions`、`ConvertSourcesRequest`、`BatchConvertSourcesRequest`，source 支持 HTTP、S3、Azure Blob、Google Cloud Storage、Google Drive；target 支持 in-body、zip、presigned URL、S3/Azure/GCS/Drive/PUT。
- 结果：`ConvertDocumentResponse`、`DoclingTaskResult`、`PresignedArtifactResult`、`ZipArchiveResult`、`RemoteTargetResult`、`ChunkDocumentResponse`、`TaskFailureResult`。
- 任务：`TaskStatusResponse` 记录 `task_id`、`task_type`、`task_status`、position、进度元数据和结构化 failure。

### 11.3 同步/异步 SDK

`DoclingServiceClient` 与 `AsyncDoclingServiceClient` 均使用 `httpx`：

- `submit()` 返回 `ConversionJob`/`AsyncConversionJob`，任务句柄支持 `poll()`、`watch()`、`result()`。
- 默认优先 WebSocket 状态流，`WebSocketWatcher` 断线重连；服务不可用且开启 fallback 时切到 `PollingWatcher`。
- `convert_all()` 通过 bounded async scheduler 支持并发、顺序保持和增量 yield；客户端有 `max_concurrency`、重试、连接/读取超时。
- 结果目标不同，客户端分别处理 in-body JSON、zip 原始结果、presigned artifact 和远程存储计数结果；对过期/未就绪/服务失败/任务失败进行专门异常分类。
- 服务 API key 通过 `X-Api-Key`；WebSocket URL 根据 HTTP scheme 派生 `ws/wss`。

## 12. 插件与扩展点

### 12.1 新增输入格式

建议遵循以下闭环，不能只新增一个文件：

1. 在 `docling/datamodel/base_models.py` 新增 `InputFormat`、扩展名与 MIME 映射。
2. 实现 `AbstractDocumentBackend` 或 `DeclarativeDocumentBackend`；分页输入实现 `PaginatedDocumentBackend`。
3. 在 `document_converter.py` 增加 `FormatOption` 和 `_get_default_option()` 路由。
4. 在 `pyproject.toml` 增加独立 optional extra，避免基础安装强制引入重依赖。
5. 必要时在 `document.py` 增加内容 sniffing/ZIP/XML 路由。
6. 增加 backend、格式探测、错误边界、序列化/groundtruth 和跨平台测试。
7. 同步 `docs/usage/supported_formats.md`、CLI/API schema 和 slim/full package 说明。

### 12.2 新增 pipeline/stage

- 继承 `BasePipeline` 并实现 `_build_document`、`_determine_status`、`get_default_options`、`is_backend_supported`。
- 通过 `PipelineOptions` 暴露可序列化配置。
- 模型阶段置于 `docling/models/stages/`，通过 factory/plugin 方式装配；不要把模型依赖写进统一 IR。
- 在单页、部分失败、超时、资源释放和 `raises_on_error` 两种模式下补行为测试。

### 12.3 插件入口

根 `pyproject.toml` 注册 `[project.entry-points.docling]` 的 `docling_defaults = "docling.models.plugins.defaults"`。模型和默认配置插件属于扩展层；`allow_external_plugins` 等选项决定是否允许外部插件参与实例化。

## 13. 测试与工程门禁

当前本地盘点约有 104 个 `test_*.py` 文件（另含大量输入样本和 groundtruth 数据）。主要测试层次：

- backend：每种格式的解析、结构、错误、恶意压缩包/路径、可选依赖和跨平台行为。
- pipeline/model：OCR、layout、table、VLM、ASR、video、富化和超时/失败页。
- API/model：`test_service_datamodels.py` 验证 discriminated union、source/target 契约、结构化 failure、结果 round-trip。
- SDK：`test_service_client_sdk_unit.py` 覆盖 URL 归一化、WebSocket URL、轮询 cadence、重连、任务结果异常、并发和顺序。
- JSON/资产：`test_backend_docling_json.py` 覆盖 JSON 输入；`test_conversion_result_json.py` 覆盖 `ConversionAssets.save/load` 往返。
- CLI/E2E：`test_cli.py`、`test_cli_remote.py`、`test_e2e_conversion.py` 等覆盖用户入口和参考输出。

项目约定的命令来自 `Makefile`：

- `make setup`：`uv sync --frozen --group dev --all-extras --no-group docs --no-group examples`。
- `make check`：ruff、ty、Tach、覆盖率/行数脚本、dprint、锁文件检查，只读检查。
- `make validate`：只对当前 changed files 运行 `prek`，可能改写文件。
- `make test`：`uv run pytest -v tests`。

本次按任务约束没有执行上述安装、构建、启动或测试命令；`ARCHITECTURE.md` 写入后的唯一后置验证使用专属门禁执行 `git diff --check`，结果以工具返回为准。

## 14. 关键风险、漂移与后续复核点

### 14.1 事实风险

1. **`docling-core` 是外部 schema 所有者**：本仓库不能单独证明 `DoclingDocument` 的完整字段、schema version 兼容性和所有 serializer 行为；升级时必须同时核对 `docling-core` 版本。
2. **本地与远程已漂移**：远程快照新增 Apple Pages、EBCDIC、`.msg` 和 `docling-client` 工作区等能力；不能把远程文档或最新 README 反推成本地已有实现。
3. **服务端不在本仓库**：`docling-serve` 的 `/v1/*` 路由和真实 OpenAPI 由外部项目维护；本仓库 wire model 与服务端版本必须成对升级。
4. **依赖组合复杂**：`standard/all` extras 会引入 torch、OCR、VLM、ASR、Playwright、Triton 等大依赖；slim 的正确边界是“基础导入可用、特性按 extra 加载”，不能用全量环境假定所有用户都具备模型能力。
5. **部分成功是正式语义**：消费方必须处理 `PARTIAL_SUCCESS`、逐页 `ErrorItem` 和 task-level failure；只判断 `status == SUCCESS` 会丢失诊断信息。
6. **格式探测有歧义**：XML、TXT、ZIP/Office、CSV、METS 等依赖内容 sniffing；新增格式必须避免扩展名/MIME 映射把合法旧格式误路由。
7. **输出格式不等价**：Markdown 对表格 span 有损；需要 lossless 交换或下游结构化处理时应使用 JSON/HTML/DocLang/DocTags。
8. **服务结果有生命周期**：presigned URL 会过期，task/result 可先后达到不同状态；客户端已有 `ResultExpiredError`、`ResultNotReadyError` 等分类，调用方仍需处理重试和持久化策略。
9. **转换资源具有状态性**：pipeline cache、模型权重、线程池、页 backend、image cache 均需在失败/超时路径释放；新增阶段必须遵守 `BasePipeline.execute()` 的 finally 释放边界。

### 14.2 本次工具链异常

- 专属 `project_context` 的返回项目与目标目录不一致；该结果已降级为“工具配置异常”记录，未用于目标仓库事实判断。
- `codegraph_explore` 因目标仓库未初始化 `.codegraph/` 无法提供代码图；本次改用目标绝对路径下的文件读取、静态搜索和 git 只读信息。
- `127.0.0.1:4780` 由 ClashX 监听，作为远程独立快照代理使用；没有把远程文件写回工作树。

## 15. 架构结论

Docling 的稳定核心不是某一个 PDF 模型，而是“格式 backend + 可配置 pipeline + 外部统一 `DoclingDocument` IR + 可组合 serializer/chunker”的边界组合：

- `DocumentConverter` 负责输入统一、格式路由、pipeline 复用和错误策略。
- backend 负责格式语义解析和输入合法性；分页 backend 与声明式 backend 通过抽象契约隔离。
- pipeline 负责页面处理、装配、模型富化、超时、部分成功和资源生命周期。
- `docling-core` 负责统一文档 schema、序列化/分块基础能力；本仓库不应复制其模型定义。
- `service_client` 是远程 `docling-serve` 的协议适配层，支持同步/异步任务、WebSocket/轮询、并发和多种结果目标；它不是本地服务端。
- `docling-slim` 通过 extras 把最小基础依赖与格式/OCR/模型/服务能力拆开，`docling` meta-package 再提供标准全功能安装入口。

- 对后续二次开发最重要的边界是：新增能力应沿“输入格式映射 → backend → pipeline/stage → options/extras → API/CLI → 测试/文档”完整接入；统一 IR 继续由 `docling-core` 作为单一事实源；本地版本与 `docling-serve`、`docling-core`、模型包版本必须显式对齐。

## 16. 后续通用底座映射：Docling 的唯一归属与单文档链路

### 16.1 当前核对目标、边界与证据口径

本节是后续“基于底座的映射与裁决”，不是把 Docling 目录直接复制进系统工程平台，也不是宣称平台已经实现 Docling 能力。它回答四个问题：

1. 文档输入、PDF/Office backend、版面/表格/图片/OCR、统一 `DoclingDocument`、模型和导出分别归哪个唯一 owner；
2. 大文件、模型权重、显存/设备、临时目录、HTTP 会话和输出制品由谁创建、持有、释放和验收；
3. 失败、超时、主动取消、线程/进程崩溃和远端任务未确认时，哪一层写入事实，哪些结果不能伪装成成功；
4. 以 L0-L4 验证等级冻结唯一文档链路，区分源码存在、组件集成和真实韧性证据。

当前核对事实证据只来自目标仓库当前本地快照：`docling/document_converter.py:95-220,431-723`、`docling/datamodel/document.py:616-779`、`docling/backend/abstract_backend.py:19-86`、`docling/backend/docling_parse_backend.py:48-220`、`docling/pipeline/base_pipeline.py:46-148`、`docling/pipeline/standard_pdf_pipeline.py:157-403`、`docling/models/base_model.py:38-218`、`docling/models/factories/ocr_factory.py:9-11`、`docling/utils/model_downloader.py:41-249`、`docling/datamodel/pipeline_options.py:95-260,1203-1269`、`docling/datamodel/document.py:400-550`。远程快照、README 声明、测试文件存在和外部平台能力均不能替代本地实现证据。

`project_context` 实际返回了错误项目 `华世王镞_v3`，其代码图元信息也携带错误项目根；随后目标目录的 `codegraph_explore` 明确报告没有 `.codegraph/`。因此当前核对代码图状态是**不可用**，未把错误项目上下文用于 Docling 事实，以下映射是目标目录直接读取后的静态架构输入。

### 16.2 唯一文档链路：适配差异，不复制执行核心

```text
项目调用方 / HTTP 能力网关 / 可选 MCP 适配器
  → Docling 项目适配层（版本、格式别名、模型 preset、provider 配置、凭据引用）
  → 文档解析模块唯一公开入口
  → 能力注册表与唯一调用器
  → 文档解析支持库（输入/格式 backend/结果转换/导出/模型制品元数据）
  → 运行核心（任务、租约、预算、超时、取消、进程/线程、崩溃恢复）
  → 受管模型 provider（PDF parser / OCR / layout / table / picture / VLM / remote API）
  → `DoclingDocument` 统一文档结构 + `ConversionResult` 状态/错误/诊断
  → 文档投影与制品支持库（JSON/DocTags/DocLang/HTML/Markdown/ZIP/下游 chunk）
  → 权威结果、资源清单、证据和可读制品
```

单链路铁律：一个文档解析原子能力只能有一个能力 id、一个契约 owner、一个公开模块入口和一条注册/调用路径；历史 `InputFormat`、provider 名、模型别名和旧 API 只能在适配层或唯一调用器入口归一化。`DoclingDocument` 是统一结构，不因 PDF、DOCX、XLSX、PPTX、OCR 或 VLM provider 不同而复制多份 IR；Markdown、HTML、JSON、DocTags、DocLang 是投影/序列化结果，不反向成为解析事实 owner。

### 16.3 四类 owner 的明确边界

| Docling 事实/能力 | 文档解析支持库 | 文档解析模块 | 模型 provider | 运行核心 |
|---|---|---|---|---|
| `Path`、URL、`DocumentStream`、`HttpSource`、MIME/扩展名/内容 sniffing、大小/页数限制 | 吸收输入流、来源解析、安全路径、摘要和通用输入结果转换；不拥有任务状态 | 只声明输入需要和格式策略，调用统一输入能力 | 不得自行下载任意 URL 或读取未授权路径 | 网络/文件句柄、下载 deadline、并发和临时输入租约 |
| PDF、DOC/DOCX、PPT/PPTX、XLS/XLSX、ODF、HTML、Markdown、XML backend | 维护格式适配器、`AbstractDocumentBackend` 契约、版本兼容和错误归一化 | 决定何时选 paginated/declarative backend，编排页面到文档 | `docling_parse`、PDFium、Office 解析库等第三方实现放 provider 边界 | provider 进程/环境隔离、超时、崩溃回收和大文件预算 |
| 版面、阅读顺序、页面、区域、表格、图片、公式 | 只提供块/资源/来源位置的数据转换器和结构校验 | 拥有文档语义编排、块顺序、页装配和一次统一出口 | layout/table/VLM/图片模型只返回预测，不定义公共块 schema | batch、队列、设备/显存租约、worker 排空和执行事实 |
| OCR | 提供 OCR 输入裁剪、语言/坐标/置信度转换和 provider-neutral 结果结构 | 决定 OCR 是否参与、区域模式、与版面/页装配如何组合 | `easyocr`、`tesseract`、`ocrmac`、`rapidocr`、远端 KServe 等是策略 | 外部命令、HTTP、GPU/CPU、模型缓存、取消和异常回收 |
| 统一 `DoclingDocument` | 适配/校验/序列化，不复制 schema | 负责将 backend/模型预测装配为统一文档结果 | 不得返回 provider 专属“成功文档”作为跨模块契约 | 负责结果生命周期、状态事实、持久化和恢复，不改变文档语义 |
| `ConversionResult`、`ErrorItem`、`ConversionStatus`、`FailureCategory` | 提供稳定错误/结果转换、诊断和版本元数据格式 | 产生领域阶段结果并决定 partial/complete 语义 | 把第三方异常翻译为 provider 错误，不吞掉页号/模型名 | 唯一写任务状态、deadline、取消裁决、重试/证据和终态 |
| JSON/DocTags/DocLang/HTML/Markdown/ZIP/export | 提供投影和原子制品写入；导出失败不回写解析正文 | 选择下游需要的投影，不维护第二文档结构 | 只能提供必要渲染/模型结果，不拥有导出状态 | 制品租约、磁盘配额、原子替换、崩溃恢复和残留清理 |

这张表是职责拆分，不是当前平台已有实现清单。没有目标平台能力搜索、契约冻结、占用租约和真实验收前，所有“底座落点”均为**待核装配计划**。

### 16.4 Docling 事实到四层底座的映射

#### 16.4.1 文档输入与格式 backend：进入文档解析支持库，模块只编排

`_DocumentConversionInput.docs()` 已把 `Path`、URL、`DocumentStream`、`HttpSource` 归一化，远端输入使用 `resolve_source_to_stream(..., max_file_size=...)`，来源失败产生带 `POLICY` 或 `SOURCE_UNAVAILABLE` 的 invalid `InputDocument`，而不是无条件中止整个批次（`document.py:616-727`）。`_guess_format()` 再组合扩展名、MIME、内容、Office ZIP、XML/CSV 等探测（`document.py:763` 起）。

底座映射如下：

- **文档解析支持库**吸收 `DocumentStream`/HTTP source/本地路径的安全输入契约、流式下载、文件摘要、内容探测、格式别名一次归一化和输入拒绝结果；禁止把 URL 下载、路径拼接和大小限制复制到每个格式模块。
- **文档解析模块**只提交“解析此文档、允许格式、页范围、解析 preset、输出投影”的领域命令；它不直接 `open()` 任意路径、不直接调用 HTTP client，也不根据扩展名各自维护一张 format map。
- **模型 provider**只接收已授权的页面/图像/受管文件句柄；不能把 `HttpSource` 当成模型 provider 的下载命令。
- **运行核心**拥有输入流的 deadline、并发配额、取消信号、文件句柄和临时 materialization 的租约；输入超限必须在 provider 启动前拒绝并留证。

#### 16.4.2 PDF/Office/图像：backend 是解析适配，不是公共文档模块

`FormatOption` 把 `pipeline_cls`、`backend`、`backend_options`、`pipeline_options` 绑定在一起（`document_converter.py:95-109`）；DOC/DOCX、PPT/PPTX、XLS/XLSX、ODF 等声明式 backend 默认走 `SimplePipeline`，图片和 PDF 默认走 `StandardPdfPipeline`（`document_converter.py:122-219`）。`AbstractDocumentBackend` 区分普通、分页和声明式 backend，`unload()` 负责释放 backend 持有的流（`abstract_backend.py:19-86`）。

因此：

- PDFium、`docling_parse`、Office 解析库和各格式 ZIP/XML 细节归**文档解析支持库 + provider 适配层**；不把第三方对象穿过模块边界。
- `DocumentConverter` 的格式路由和 `SimplePipeline`/`StandardPdfPipeline` 的领域编排归**文档解析模块**，但平台实现时应收敛为一个公开的文档解析模块入口，而不是每种格式暴露一套网关能力。
- PDF 页、Office 段落/表格/幻灯片、图像页最终必须转换为同一个 `DoclingDocument`；格式差异只留在来源定位、诊断和 provider 元信息。
- “Office 文件直接可读”不等于“大文件、恶意 ZIP、宏、外部引用和临时目录安全”已验证；这些属于支持库输入安全与运行核心资源门禁。

#### 16.4.3 版面/表格/图片/OCR：模块拥有语义，provider 只提供预测

`StandardPdfPipeline` 将预处理、layout、OCR、table、assemble、reading order 等阶段通过有界队列/worker 编排；`GenericEnrichmentModel` 以 `prepare_element()` 和批量 `__call__()` 对 `DoclingDocument` 元素做富化（`base_pipeline.py:107-129`、`base_model.py:146-218`）。`OcrFactory` 以 `ocr_engines` 注册表选择 OCR 实现（`ocr_factory.py:9-11`），`OcrOptions` 明确 `FULL_PAGE`、`LAYOUT_REGIONS`、`PDF_AWARE_LAYOUT_REGIONS` 和语言参数（`pipeline_options.py:95-260`）。

映射规则：

- **文档解析模块**拥有页面顺序、版面块类型、表格行列/合并、图片资源引用、OCR 区域模式、阅读顺序和统一结构装配；它是“做什么、结果表示什么”的 owner。
- **模型 provider**拥有 layout/table/OCR/picture/VLM 的模型加载、预处理、推理和预测字段映射；它是“用哪个模型、怎样调用”的 owner。预测框、文本、分数、模型版本和原始字段定位必须经同一个转换器进入文档结构。
- **文档解析支持库**提供 provider-neutral 的 `页面/文档块/表格数据/文档资源/诊断` 转换和序列化；不得让 `ocr_engines`、模型 SDK 或远端返回字典成为公共 IR。
- **运行核心**负责 stage batch、bounded queue、线程/进程和设备资源；模块不能因某个模型 provider 自己启动第二个 scheduler 或无限线程池。

`StandardPdfPipeline` 的失败页会生成含组件、模块、错误类别和页号的 `ErrorItem`（`standard_pdf_pipeline.py:376-392`）；因此“部分页成功”应统一映射为 `PARTIAL_SUCCESS`，不能被模型 provider 直接改写为全局成功。

#### 16.4.4 模型、模型制品和导出：模型 provider 与支持库分开

模型目录不是文档解析模块的事实数据：`PipelineOptions.artifacts_path` 指向预下载权重/配置目录，`enable_remote_services` 与 `allow_external_plugins` 是能力开关（`pipeline_options.py:1203-1269`）；`download_models()` 将 layout、TableFormer、picture classifier、code/formula、VLM、RapidOCR、EasyOCR、Nemotron 等制品写入 `settings.cache_dir / "models"` 或用户指定目录（`model_downloader.py:41-249`）。

- **模型 provider**：绑定 `model_id/revision/repo_id`、推理框架（Transformers/MLX/vLLM/API/KServe 等）、设备输入和第三方 SDK；对外只暴露统一“模型能力 + 预测/富化结果”契约。provider 不拥有任务状态、文档 schema 或跨调用的隐式缓存事实。
- **文档解析支持库**：负责模型制品清单、下载/校验/内容摘要、缓存命中、版本和环境元数据；权重不得进入源码、任务结果或普通日志。模型下载失败必须可区分 `provider_unavailable`、`artifact_corrupt`、`network_timeout` 和 `policy_denied`。
- **运行核心**：负责模型环境/解释器、CPU/GPU/显存 lease、并发预算、加载/卸载、provider 进程及崩溃回收。一个 `artifacts_path` 或模型对象存在，只证明配置/缓存命中，不证明模型真正加载、推理完成或显存已经释放。
- **导出支持库**：`ConversionAssets.save()` 在内存 ZIP 中写入 `version/status/errors/pages/timings/confidence/document.json` 后原子写文件（`document.py:431-501`）；这属于结果制品/序列化支持库。解析模块只选择投影，不能让 Markdown 的有损表格表示反向覆盖 `DoclingDocument`。

### 16.5 统一文档结构与结果契约

平台映射时，`docling-core` 的 `DoclingDocument` 仍是外部 schema owner；不能在平台再复制一套“Docling IR”或让不同 provider 直接返回不同字典。公共契约/文档解析模块应固定 provider-neutral 结构：

| 对象 | 最小语义 | 写入 owner |
|---|---|---|
| `schema_version` | 统一文档结构版本和兼容范围 | 公共契约/模块发布流程 |
| `source` | 来源类型、媒体类型、摘要、页范围、来源 provider | 输入支持库/运行核心审核 |
| `pages` | 有序页码、尺寸、方向、页面资源引用 | 文档解析模块 |
| `blocks` | 标题、段落、表格、图片、公式、页眉/页脚、区域；含顺序、bbox、来源位置、置信度 | 文档解析模块统一转换器 |
| `table_data` | 行列、单元格、合并、表头、文本和结构诊断 | 文档解析模块/表格转换支持库 |
| `resources` | 图像、页预览、原始结果、导出制品的摘要/受管引用 | 资源支持库 |
| `diagnostics` | backend/provider/model、耗时、降级、警告、原始字段定位和错误分类 | 运行核心与结果转换支持库 |
| `status/errors` | `PENDING/STARTED/SUCCESS/PARTIAL_SUCCESS/FAILURE/SKIPPED` 与 `FailureCategory` | 运行核心唯一写状态；模块提交领域结果 |

`ConversionAssets.save/load` 的 ZIP 往返能证明本地资产结构的一部分，但不能证明跨版本 schema、恶意 ZIP 防护、磁盘原子替换、并发写和崩溃恢复。JSON/HTML/DocTags/DocLang/Markdown 等必须有一个投影注册/调用入口；每个导出器只消费统一文档，不回调 provider 读取私有对象。

### 16.6 大文件、模型、临时目录与制品资源生命周期

| 资源 | 创建/持有者 | 正常完成 | 业务失败/超时/取消 | 宿主/子进程崩溃 | 必须读回的证据 |
|---|---|---|---|---|---|
| 本地大文件/URL 下载流 | 输入支持库创建；运行核心持有 deadline/配额 | 流式读取、摘要、格式识别后转受管输入句柄 | 超过 `max_file_size`/页数/内存预算立即拒绝；关闭响应和文件句柄 | 回收下载 worker、临时源文件和锁；不得留下完整半成品 | 文件大小、摘要、句柄数、残留路径、拒绝错误码 |
| PDF/Office 解压与页资源 | backend/provider | 逐页消费并 `unload()` | 损坏 ZIP、宏/路径逃逸、页失败只产生结构化页错误；停止后释放 mmap/流 | 进程组 kill/reap；清理解压目录和 native handles | 解压总量/文件数、页状态、进程、临时目录 |
| 页图像、裁剪图、嵌入图片 | pipeline/model provider 借用；模块拥有文档资源引用 | batch 后释放中间图，仅保留受管资源摘要/引用 | 下游失败或取消清空队列与 crop buffer，不把未完成图片标可读 | worker 退出后确认无引用、无增长缓存、无临时图片 | 内存峰值、队列长度、资源引用、文件摘要 |
| 模型权重/配置/缓存 | 模型制品支持库持久化；运行核心加载/卸载 | 摘要校验、按版本复用、正常卸载 | 下载超时/校验失败废弃临时目录；取消不可留下半模型 | provider 崩溃后释放显存/进程，坏缓存隔离重建 | model id/revision、锁哈希、摘要、设备、显存峰值、租约 |
| CPU/GPU/显存与线程 | 运行核心租约；provider 仅借用 | 达到归还条件后释放并记录峰值 | deadline/取消先停止新 batch，再排空 worker；释放失败进入残留告警 | 强杀后按进程组/设备 owner 对账，不以 Python 对象析构代替 | lease id、owner、开始/结束、峰值、释放结果 |
| 临时目录、ZIP bundle、JSONL/远端结果 | 支持库创建；运行核心登记 | 原子写入、摘要后转正式制品 | 单项失败进入补偿清理；不得把部分 ZIP 当完整结果 | 父进程 finally 与启动监督器双重扫描并清理 | 临时目录前后清单、制品摘要、半成品状态 |
| HTTP/WebSocket/远端 job/session | provider 创建；运行核心监督 | 关闭 session，保存 remote id 与结果引用 | 连接超时/断线可重试需幂等证据；取消仅在远端确认后标 canceled | 本地 session 关闭；远端 job 未确认则 `cancellation_unconfirmed`，不伪装取消 | request id、remote id、状态轨迹、重试/取消确认 |
| 输出 `ConversionAssets`/导出文件 | 导出支持库写入；运行核心拥有制品状态 | 写摘要、原子替换、可读性读回 | 目标冲突/磁盘满/序列化失败保留失败证据并清理临时文件 | 崩溃后扫描临时文件，恢复或标记未完成，不覆盖已确认制品 | 路径、大小、摘要、可读性、原子提交记录 |

当前代码中 `ThreadedPipelineStage.stop()` 最多等待 15 秒，仍存活时只记录“resources may leak”并放弃线程（`standard_pdf_pipeline.py:265-278`）；这正是运行核心必须补上的 P0 资源治理缺口，不能把 daemon/非 daemon 线程、`Future.cancel()` 或 `runner.close()` 当作释放证明。

### 16.7 失败、超时、取消、崩溃矩阵

| 场景 | 当前 Docling 证据 | 统一底座裁决 | 当前状态 |
|---|---|---|---|
| URL 不可达、HTTP 错误、非法本地路径 | `_DocumentConversionInput.docs()` 捕获 `OSError/ValueError`，生成 `SOURCE_UNAVAILABLE`/`POLICY` invalid input | 输入支持库返回稳定错误；运行核心只创建失败任务/继续批次，不重复下载 | 源码存在；统一平台错误码待核 |
| 大文件/页数/页范围超限 | `max_file_size` 在 source resolve 阶段检查；`DocumentLimits` 约束页数/范围 | 在 provider 启动前拒绝；写入大小、策略版本和调用者证据 | 源码部分存在；大文件内存/解压总量未证 |
| backend 损坏或格式不支持 | backend `is_valid()`/`DocumentLoadError`，输入路由可构造 invalid document | `BACKEND_FAILURE` 与输入 `POLICY` 分开；不把解析异常当正文或空文档 | 源码存在；跨 provider 一致性待核 |
| layout/table/OCR/model 推理失败 | pipeline 捕获异常，页级生成 `ErrorItem`，完整失败为 `FAILURE`，有错误的 SUCCESS 降为 `PARTIAL_SUCCESS` | provider 错误经统一转换；模块保留成功页与失败页；重试受幂等/预算控制 | 源码部分存在；运行核心账本待核 |
| 文档级超时 | `document_timeout`、`TIMEOUT` 和 threaded pipeline 的 timed-out run id 已有实现 | 核心拥有 deadline；超时先停止新工作、排空队列、释放资源，终态不得伪装 `SUCCESS`/`CANCELED` | 源码部分存在；跨线程终止和残留未证 |
| 主动取消/客户端断连 | 本地 SDK scheduler 有 `task.cancel()`，但不等价于 provider/线程停止；目标仓库未证明统一取消令牌 | 核心写 `cancel_requested`，调用 provider cancel/stop，排空并回收；未确认时 `cancellation_unconfirmed` | **待核/P0** |
| stage 线程卡死或异常退出 | `_run()` 顶层 guard 记录异常并关闭输出队列；`stop()` 超时后可遗留线程 | 运行核心使用受管进程组或可证明排空的 worker，记录每阶段状态；禁止只靠日志判断完成 | **待核/P0** |
| 子进程/native 扩展崩溃 | PDFium、OCR、torch/ONNX 等 native/第三方边界存在潜在崩溃面；当前仓库未提供统一 crash supervisor | 重型 provider 优先独立进程；SIGKILL 后回收 PID/临时目录/设备租约，任务标 `provider_crashed` 可重试 | **待核/P0** |
| 导出/资产部分写入 | `ConversionAssets.save()` 先构造内存 ZIP，再写目标文件；缺少平台级批次清单与崩溃恢复证据 | 临时文件→摘要→原子替换；部分成功必须可读回、可补偿或明确未完成 | **待核** |
| 远端服务任务超时/结果过期 | service client 有 poll/watch、重连和 `ResultExpiredError/ResultNotReadyError` 等分类；服务端不在本仓库 | provider 只报告远端状态；核心决定重试/取消/补偿，未确认取消不得标已取消 | 源码客户端存在；远端语义待核 |

统一状态建议冻结为：

```text
created → queued → running → succeeded
                       ├→ partial_success
                       ├→ failed
                       ├→ timed_out
                       └→ cancel_requested → canceled | cancellation_unconfirmed
```

`ConversionStatus` 是文档转换结果语义；它不能单独代替平台任务状态。一个文档只有在统一结构、错误/诊断、制品摘要和资源释放均完成读回后才可进入 `succeeded`；“pipeline 返回对象”“日志出现 completed”“线程 join 超时后返回”“HTTP 200”都不能单独证明成功。

### 16.8 现有能力命中、缺口与复用/升级/新建/隔离裁决

| 能力 | 源码命中 | 底座落点 | 后续裁决 |
|---|---|---|---|
| 输入路径/URL/stream、格式探测、限制 | `_DocumentConversionInput`、`InputDocument`、`DocumentLimits` | 文档解析支持库 + 运行核心资源监督 | **吸收语义，升级统一输入/安全/大文件契约** |
| PDF/Office/image backend | `AbstractDocumentBackend`、`FormatOption`、各 backend | 文档解析支持库/provider 适配 | **吸收适配模式，禁止每格式复制公共入口** |
| 页面、版面、表格、图片、OCR 编排 | `StandardPdfPipeline`、`GenericEnrichmentModel`、`OcrFactory` | 文档解析模块 | **吸收并升级为统一文档出口** |
| `DoclingDocument`、`DocItem`、provenance | `docling-core` 外部类型与本地调用 | 公共文档结构/文档解析模块 | **吸收契约边界；不复制 schema** |
| OCR/layout/table/VLM/ASR 模型 | `models/stages/`、factory、model specs | 模型 provider 支持库 | **按第三方/框架拆 provider，统一模型注册和结果转换** |
| 模型下载与 `artifacts_path` | `model_downloader.py`、`PipelineOptions` | 模型制品支持库 + 运行核心 | **升级摘要/环境/显存/缓存租约；不把权重当源码** |
| `ConversionAssets.save/load`、JSON/HTML/Markdown/DocTags | `document.py`、外部 serializer | 导出/制品支持库 | **吸收投影能力；统一原子写入和完整性验收** |
| 同步/批量线程、threaded PDF pipeline | `ThreadPoolExecutor`、bounded queue、stage thread | 运行核心监督器 | **吸收调度语义；禁止直接复制为平台任务系统** |
| `service_client` 的 poll/watch/WebSocket/async scheduler | `service_client/` | 远端 provider 适配 + 运行核心任务监督 | **吸收协议形状，隔离任务状态 owner** |
| CLI/MCP/远程服务端路由 | CLI 和 client 有适配代码，服务端不在本仓库 | HTTP 能力网关/可选协议适配 | **隔离；不得形成第二能力注册表或第二任务链** |
| 15 秒线程放弃、native/第三方崩溃、取消未确认 | `ThreadedPipelineStage.stop()` 暴露泄漏风险，未见统一 supervisor | 运行核心 | **新增/升级 P0 运行治理；当前不能宣称已具备** |
| 统一错误、幂等、重试、资源证据 | 有 `ErrorItem`/categories，但无平台任务账本证据 | 公共契约 + 运行核心 + 证据支持库 | **升级；禁止由 provider/模块各自翻译** |

“废弃/隔离”不是删除当前 Docling 代码：旧 backend、旧 pipeline、CLI 和 service client 继续作为项目版本事实保留；平台只禁止它们绕过唯一模块入口、直接写任务/状态/制品或复制第二套运行核心。

### 16.9 装配计划、验收契约与唯一 owner 门禁

未来若将 Docling 接入平台，必须按以下顺序执行，不能边研究边修改公共入口：

1. **契约冻结**：冻结 `通用文档`、`页面`、`文档块`、`表格数据`、`文档资源`、`解析结果/导出结果`、错误分类、模型/provider 描述、资源清单和任务状态；保留 `schema_version`、来源摘要和原始字段定位。
2. **能力搜索与占用租约**：检索已有文档、PDF、Office、OCR、模型制品、文件、HTTP、任务、资源监督能力；每个能力只选择一个 owner。没有搜索、复用裁决、租约和验收契约不得新建。
3. **结果转换先行**：先建立 provider-neutral 的 backend/模型/远端 JSONL → 统一文档结构转换器，覆盖字段缺失、页号、bbox、置信度、资源引用和诊断；不在四种 provider 内各写一份。
4. **文档解析模块接线**：唯一模块入口负责输入命令、格式策略、页面/版面/OCR/表格组合、结果转换和投影选择；模块不导入第三方 SDK，不直写任务状态。
5. **模型 provider 装配**：按 PDF parser、OCR、layout、table、picture/VLM、Office parser 等维度声明 provider id、版本、模型制品、能力参数、环境和资源预算；本地模型优先独立环境/进程，远端 API 只保留 remote id 和结果引用。
6. **运行核心接线**：加入任务 id/幂等键、deadline、取消令牌、进程组、线程排空、模型/设备租约、临时目录、制品原子替换、崩溃恢复和证据读回。取消未确认时不能写 `canceled`。
7. **协议与下游最后接入**：HTTP 能力网关调用模块唯一入口；CLI/MCP/service client 仅做协议/展示/远端适配。Markdown/HTML/JSON/DocTags/DocLang/ZIP 和 chunking 均从统一文档读取。
8. **反向破坏验收**：故意移除格式注册、结果转换、provider 声明、超时排空、取消确认、模型释放和临时清理，验证相应 L1-L4 门禁确实失败；不能以 mock、日志、子代理回执或“对象返回”替代。

唯一 owner 门禁至少检查：

- 正式代码没有直连第三方文档/OCR/模型 SDK 的旁路调用；
- 模块没有第二套 format map、model registry、poller、task state 或临时目录清理器；
- provider 不返回未转换的私有对象、不写公共任务状态、不偷偷 fallback 到另一模型；
- 导出器不重新解析源文件、不修改统一文档事实；
- 运行核心是唯一任务/租约/超时/取消/崩溃事实写 owner；
- 同一输入、同一能力版本和同一幂等键可读回同一任务/制品，不因 CLI、HTTP、MCP 或 SDK 入口不同而重复执行。

### 16.10 L0-L4 防假绿验证阶梯

| 等级 | 当前核对必须验证的内容 | 证据要求 | 当前状态 |
|---|---|---|---|
| **L0 静态事实** | 本地项目身份、版本、输入/backend/pipeline/model/export 路径；四类 owner；资源创建/释放箭头；失败分类；唯一链路 | `ARCHITECTURE.md` 源码路径/行号、错误 MCP 上下文、`.codegraph/` 状态、修改范围 | **当前核对完成**：已直接读取目标文件；代码图不可用 |
| **L1 契约** | 输入互斥/大小/页限、格式路由、统一文档字段、错误映射、状态枚举、模型/provider 声明、导出结果形状 | 定向测试总数/跳过数/退出码；不能把测试存在、mock 或 import 成功算通过 | **未执行**：未安装依赖、未运行 pytest |
| **L2 组件集成** | input→backend→pipeline→model provider→统一文档；PDF/Office/OCR/table/image 结果转换；资产 save/load；临时目录清理 | 真实/受控 provider 调用次数、结果 schema、文件摘要、session/模型/队列释放 | **未执行** |
| **L3 真实端到端** | 真实 PDF/Office/图片，至少一条 OCR/layout/table，真实模型制品或明确的 `HOST_UNAVAILABLE`，真实导出并读回 | 环境/依赖/模型摘要、输入/输出摘要、任务状态、退出码、进程/线程/临时目录/显存现场 | **未执行**：未下载权重、未启动 provider/服务 |
| **L4 逆向韧性** | 超大/损坏/恶意输入、provider 缺失、模型下载失败、断线、超时、主动取消、线程卡死、SIGKILL/native crash、部分导出、重启恢复、重复幂等 | 四终态状态轨迹、重试/取消确认、PID/线程/端口/租约/临时目录/制品残留读回；退出码必须真实 | **未执行**：当前仓库不能推出端到端取消或崩溃安全 |

L0-L4 通过口径是“当前核对真实命令 + 退出码 + 现场读回”。历史测试报告、README、模型目录存在、`ConversionResult` 对象返回、warning、HTTP 200、线程停止日志或 MCP tool 可注册都不能越级算通过。外部 provider 不可用时必须记为 `HOST_UNAVAILABLE`/`UNVERIFIED` 并写明阻塞原因，不能改成 skip 后绿色。

### 16.11 后续最终裁决与剩余风险

- **吸收**：Docling 的输入归一化、backend/pipeline 分离、分页/声明式解析契约、版面/表格/图片/OCR 富化、`DoclingDocument` 外部 IR 边界、`ConversionResult` 错误/部分成功语义和多种导出投影，作为文档解析支持库与文档解析模块的契约输入。
- **升级**：模型制品下载/校验、provider 注册、统一结果转换、文件/HTTP/临时目录支持库，以及运行核心的任务账本、资源租约、超时、取消、进程隔离、崩溃恢复和残留审计必须进入平台已有 owner；不得由 Docling 模块复制一套。
- **隔离**：Docling 的第三方 backend/model 对象、CLI、MCP、service client wire model、pipeline 内存队列和 `ConversionStatus` 的项目内部细节留在项目适配层/provider/协议适配层；平台只接收统一文档、统一任务和统一制品契约。
- **待核**：目标平台现有文档/OCR/模型/HTTP/任务/资源能力的实际注册表、能力 id、占用租约、契约版本和运行验证均因 MCP 错绑/代码图不可用而未核；不能直接开生产底座工作包。
- **P0 风险**：线程停止超时可遗留资源；native/第三方模型崩溃隔离与恢复未证；取消/远端 job 未确认不能安全标记 canceled；大文件解压总量、模型显存峰值、批量导出原子性和临时目录崩溃清理未形成统一可读回证据。
- **当前核对边界**：仅修改本项目根目录 `ARCHITECTURE.md`；未修改源码、配置、依赖、测试、README、Git，未删除旧细探或其他文件。

## 17. 后续 MCP、修改与验证记录

| 项目 | 结果 |
|---|---|
| 开工 id | **未取得**：`project_context` 返回的 `开工id` 为空，且项目错误绑定为 `/Users/hekunhua/Documents/Agent/PHP/华世王镞_v3`；不能伪造目标项目开工 id。 |
| MCP 实例 | 工具实际返回 `project_toolkit`；任务指定的 `system_engineering_toolkit`/目标 HTTP `127.0.0.1:8766/mcp/` 未能为本目标项目提供正确身份绑定。 |
| `project_context` | **错误绑定**：返回项目名 `华世王镞_v3`，根目录与目标 Docling 不一致；结果未用于目标项目事实。 |
| `codegraph_explore` | **不可用/错误上下文**：目标目录无 `.codegraph/`；工具返回 `codegraph` 不可用，元信息项目根仍是错误的 V3 根。 |
| MCP 五字段反馈 | 当前核对完成文档映射后调用；若后端仍拒绝，将以工具原始结果为准，不宣称已入账。 |
| `verify_and_record` | 当前核对仅允许执行 `git diff --check` 作为文档工作包验证；退出码必须为 0 才能记录成功。由于 MCP 上下文错绑，即使命令退出 0 也只证明目标文件差异格式，不证明平台装配完成。 |
| 项目根 | `/Users/hekunhua/Documents/Agent/github 源码参考/20_文档解析与IR/2026_06_25_document_json_unification/docling` |
| 修改文件 | 仅 `ARCHITECTURE.md`；未修改源码、配置、依赖、测试、README、Git，旧细探未删除。 |
| 代码图 | 不可用：目标目录没有 `.codegraph/`。 |
| 真实验证 | L0 静态映射完成；L1-L4 未执行。 |

## 18. 后续底座映射收口：从统一入口到可验收制品

本节是后续映射的收口版，按“调用入口 → 统一文档 → 解析器与转换 → 分块/结果 → 外部依赖 → 制品 → 异常终态 → 验证等级”给出一条不可分叉的实现边界。它描述的是对 Docling 的架构归纳，不表示目标平台已经拥有这些组件。

### 18.1 唯一入口和请求生命周期

```text
Path / URL / DocumentStream / HttpSource
  → DocumentConverter.convert() / convert_all() / convert_string()
  → _DocumentConversionInput.docs()
  → InputDocument(document_hash, format, limits, backend)
  → FormatOption(pipeline_cls, backend, backend_options, pipeline_options)
  → BasePipeline.execute()
  → ConversionResult(input, document, pages, errors, timings, confidence, status)
  → export / ConversionAssets.save() / chunker
```

- `DocumentConverter` 是本地同步 API 的唯一高层入口；批量、字符串、CLI 和服务 SDK 都必须最终归一到同一转换契约，不能分别维护 format map、任务状态或结果 schema。
- 输入层先完成来源解析、大小/页数/page range 检查、hash 和格式探测，再实例化 backend；provider 不得绕过这一层下载 URL 或读取任意路径。
- `FormatOption` 是“格式 → backend + pipeline + options”的唯一路由记录。声明式格式通常由 backend 直接生成文档；分页格式由 pipeline 逐页建立页面、运行阶段并装配文档。
- `BasePipeline.execute()` 的 `build → assemble → enrich → determine_status → unload` 是转换生命周期边界；`finally` 中的 unload 是必要条件，但不是跨进程资源释放的充分证明。

### 18.2 统一文档模型、解析器和转换器

| 层 | 事实 | 平台映射决策 |
|---|---|---|
| 输入模型 | `InputDocument` 保存路径/流的逻辑名称、hash、format、filesize、page_count、limits 和 backend | 输入支持库负责来源与安全；运行核心负责 deadline、配额和临时输入租约 |
| backend | `AbstractDocumentBackend`、`PaginatedDocumentBackend`、`DeclarativeDocumentBackend` 分别表达通用、分页、直接生成 IR 的能力 | 第三方解析对象只停留在 provider 适配层；模块只选择 backend，不暴露 backend 对象 |
| 页面中间模型 | `Page`、`LayoutPrediction`、`Cluster`、表格/图片/OCR预测和 `AssembledUnit` | 只作为转换中间态；必须带页号、来源位置、bbox、置信度和 provider 诊断，不能成为第二套公共 IR |
| 统一 IR | `docling_core.types.doc.DoclingDocument` 及 `DocItem`、`TextItem`、`TableItem`、`PictureItem` | `docling-core` 是 schema owner；平台只做版本声明、校验和适配，不复制字段定义 |
| 语义转换 | backend 产出基础结构，pipeline 负责页面装配、阅读顺序、OCR、表格、图片和公式富化 | 模块拥有文档语义；模型 provider 只返回可转换预测；一个转换器统一处理缺字段、页号、bbox、置信度和错误 |

解析器按能力而非入口拆分：PDF/图像属于分页解析链；DOCX/PPTX/XLSX/ODF/HTML/Markdown/XML/JSON 等多为声明式链；音频、视频走 ASR/帧抽取链。无论链路不同，最终都只能产出一个 `DoclingDocument`，格式差异保留在 provenance、资源引用和诊断中。

### 18.3 分块、结果和投影

- `BaseChunker.chunk(DoclingDocument)` 是唯一分块输入契约；`HierarchicalChunker` 消费 IR 层级、heading 和 caption，`HybridChunker` 再执行 tokenizer-aware 拆分、合并、表头重复和 overflow 策略。分块是统一文档之后的下游投影，不得参与源文件解析或回写 IR。
- `ConversionResult` 是一次本地转换的领域结果，至少包含 `input`、`document`、`pages`、`errors`、`timings`、`confidence` 和 `ConversionStatus`。`ConversionStatus.SUCCESS` 仅表示转换阶段没有记录错误；有错误时由 pipeline 降为 `PARTIAL_SUCCESS`，不能由导出成功覆盖。
- `ConversionAssets.save()` 的当前 bundle 包含 `timestamp.json`、`version.json`、`status.json`、`errors.json`、`pages.json`、`timings.json`、`confidence.json` 和 `document.json`。这是项目资产格式，不等于平台任务记录；平台还必须保存输入/输出摘要、schema 版本、能力版本、幂等键和资源释放证据。
- Markdown、HTML、DocTags、DocLang、JSON、YAML、纯文本、VTT 和 chunks 都是从统一 IR 读取的投影。Markdown 对表格合并单元格存在有损语义，不能作为无损交换格式；无损重放应使用 JSON/`DoclingDocument` 兼容投影。

### 18.4 外部依赖和文件制品边界

| 能力 | 本地依赖/制品示例 | 依赖性质 | 约束 |
|---|---|---|---|
| 基础模型与 IR | `pydantic`、`pydantic-settings`、`docling-core`、`filetype`、`requests` | 基础运行依赖 | `docling-core` 版本必须与 schema/serializer 一起锁定 |
| PDF | `pypdfium2`、`docling-parse` | native/解析器依赖 | 版本、平台 wheel、native crash 和页资源释放单独验收 |
| Office/Web/XML | `python-docx`、`python-pptx`、`openpyxl`、`odfdo`、`beautifulsoup4`、`marko`、`lxml`、`defusedxml`、`arelle-release` | 按格式 extra 加载 | 缺失依赖必须是明确 `TARGET_UNAVAILABLE`/能力缺失，不得静默降级为空文档 |
| OCR/推理 | RapidOCR、ONNX Runtime、EasyOCR、Tesseract、`ocrmac`、PyTorch/Transformers、VLM/ASR | 重型或平台相关依赖 | provider 只声明能力；模型、设备、显存和解释器由运行核心租约管理 |
| 远程服务 | `httpx`、WebSocket、S3/Azure/GCS/Drive target/source | 外部会话和远端任务 | 保存 request/remote id、状态轨迹、重试和取消确认；不把 HTTP 200 当完成 |
| 文件制品 | 模型权重、缓存、临时解压目录、页面图片、JSON/ZIP/导出文件 | 可持久化或临时资源 | 先写临时路径、校验大小/摘要/可读性，再原子替换；权重不进入源码和普通结果日志 |

`docling-slim` 的基础依赖约束与 optional extras 是能力边界的一部分：`format-*` 负责格式，`feat-ocr-*` 负责 OCR，`models-*` 负责模型，`feat-chunking` 负责分块，`service-client` 负责远程客户端。安装 extra 只能证明依赖可解析，不能证明 provider 可加载、模型可推理或资源可释放。

### 18.5 失败、超时、取消和崩溃的统一裁决

文档结果状态与平台任务状态必须分离。文档层沿用 `PENDING/STARTED/SUCCESS/PARTIAL_SUCCESS/FAILURE/SKIPPED`；平台任务至少采用：

```text
created → queued → running → succeeded
                        ├→ partial_success
                        ├→ failed
                        ├→ timed_out
                        └→ cancel_requested → canceled | cancellation_unconfirmed
```

| 事件 | 必须写入的事实 | 禁止的假成功 |
|---|---|---|
| 输入不可达、格式非法、超限 | source/policy 错误、输入 hash（若可得）、限制值和是否启动 provider | 不得生成空 `DoclingDocument` 或继续标 `SUCCESS` |
| backend/页解析失败 | backend/provider、页号、`BACKEND_FAILURE`、已成功页和未处理页 | 不得丢失页级 `ErrorItem`，不得将局部错误变成纯成功 |
| 推理/OCR/表格失败 | 模型能力、版本、批次、`INFERENCE_FAILURE` 或 `TARGET_UNAVAILABLE` | 不得以旧缓存、空预测或 warning 代替失败事实 |
| deadline 超时 | deadline、已完成页、停止请求、排空结果、资源回收结果 | 不得因返回了对象、线程停止日志或 HTTP 200 标记成功 |
| 主动取消/客户端断连 | `cancel_requested`、本地停止结果、远端取消确认和残留资源 | 远端未确认时只能是 `cancellation_unconfirmed`，不能写 `canceled` |
| 线程卡死、native/provider 崩溃 | worker/PID、退出信号、阶段、临时目录、模型/设备租约回收结果 | 不得只靠异常日志或父进程存活推断完成 |
| 导出/保存中断 | 临时制品路径、摘要、原子提交标记和可读回结果 | 半写 ZIP/JSON 不能冒充完整制品，也不能覆盖已确认制品 |

取消必须先停止新工作，再排空有界队列并释放页面、backend、session、线程/进程和设备资源；重型 native provider 优先独立进程并按进程组回收。当前源码中 threaded stage 的停止等待存在“仍存活则可能泄漏”的路径，因此取消确认、崩溃监督、临时清理和设备租约仍是平台 P0 缺口。

### 18.6 验证等级与放行条件

| 等级 | 证明范围 | 必须读回的证据 | 放行含义 |
|---|---|---|---|
| L0 静态 | 入口、路由、模型、依赖、状态和 owner 关系存在 | 源码路径/版本/配置与差异检查 | 只允许进入设计评审 |
| L1 契约 | 输入限制、格式路由、IR 字段、错误映射、结果/制品 schema | 定向契约测试退出码、零测试/跳过解释、序列化 round-trip | 允许组件开发，不允许真实服务宣称可用 |
| L2 集成 | input→backend→pipeline→provider→IR→export/chunk | 真实或受控 provider 调用、schema、文件摘要、队列/session/缓存释放 | 允许受控环境试运行 |
| L3 端到端 | 真实 PDF/Office/图片及 OCR/layout/table，真实导出读回 | 依赖/模型/输入输出摘要、任务轨迹、进程/线程/临时目录/设备现场 | 允许业务验收候选 |
| L4 韧性 | 超大、损坏、恶意、缺依赖、断线、超时、取消、卡死、SIGKILL/native crash、重启、幂等 | 四终态轨迹、取消确认、PID/租约/临时目录/制品残留和恢复结果 | 才可称生产级底座 |

验证不自动升级：README、测试文件存在、import 成功、mock 返回、模型目录存在、日志出现 completed、`ConversionResult` 对象返回或 HTTP 200 均不能替代对应等级的真实证据。外部依赖不可用时必须明确记录 `HOST_UNAVAILABLE`/`UNVERIFIED` 及阻塞原因；不得将未执行改写成绿色通过。

### 18.7 后续最终映射

1. **吸收**：统一输入归一化、`FormatOption` 路由、backend/pipeline 分层、`DoclingDocument` 外部 IR、`ConversionResult`/`ErrorItem`、分块和导出投影。
2. **复用**：`docling-core` 作为 IR 单一事实源，现有 serializer/chunker 作为投影基础，现有 optional extras 作为依赖分层参考。
3. **升级**：模型制品清单与校验、provider 结果转换、文件/HTTP session、任务账本、资源租约、超时、取消确认、崩溃隔离和制品原子提交。
4. **隔离**：第三方 backend/model 对象、CLI/MCP/service-client 协议细节、pipeline 私有队列和本地 `ConversionStatus` 细节不得越过唯一模块入口形成第二套公共能力。
5. **未放行**：当前快照只完成 L0 静态映射；L1-L4 未因未安装依赖、未下载模型、未启动服务和未运行测试而通过。任何平台接入必须先完成能力 owner、契约版本、验证命令和资源现场的登记。

## 19. 深度源码核对补充：从输入到制品的逐节点事实

本节是在前述架构结论基础上的第二次逐节点源码核对。它只记录当前本地快照的实现事实和未被证明的边界，不把平台设计要求倒推成 Docling 已有能力。

### 19.1 输入路由与生命周期的实际顺序

```text
convert()/convert_all()/convert_string()
  → _DocumentConversionInput.docs()
  → resolve_source_to_stream()（URL/HttpSource）
  → _guess_format()
  → InputDocument（hash/limits/backend）
  → _process_document()
  → _get_pipeline() / pipeline.execute()
  → ConversionResult
```

- `convert_string()` 不是独立解析器，只允许 MD、HTML、XML_DOCLANG，并将字符串包装成带扩展名的 `DocumentStream` 后回到 `convert()`。
- URL 和 `HttpSource` 在获得流之前执行来源解析和 `max_file_size` 检查；来源错误会产出 invalid `InputDocument`，因此 `convert_all()` 在 `raises_on_error=False` 时可以继续批次。`raises_on_error=True` 仍会在消费该结果时抛出 `ConversionError`，并通过 `__cause__` 保留输入构造时捕获的原始异常。
- `_guess_format()` 对路径和流使用不同的探测窗口：路径通常读 1024 字节，流读 8192 字节；先处理 `.dclg`/`.dclx` 特殊扩展名，再组合 MIME、扩展名、Office/ODF ZIP 内部成员、METS gzip、XML 根/DOCTYPE、HTML 和 CSV sniffing。XML、纯文本和共享扩展名存在候选歧义，最终格式由内容规则裁决。
- 未识别或不在允许格式表中的输入使用 `_DummyBackend`，随后成为带 `POLICY`/`UNKNOWN` 的失败或 `SKIPPED` 结果；不存在可识别结果且要求抛错时，批次迭代结束后才抛“无可识别格式”的 `ConversionError`。
- `InputDocument` 在 backend 初始化后立即调用 `is_valid()`；分页 backend 还会读取 `page_count()`，在 pipeline 启动前执行最大页数和 page range 起点限制。`DocumentLoadError` 被归类为 `BACKEND_FAILURE`，非该类型的依赖缺失或内部异常继续向上传播，避免伪装成坏输入。

### 19.2 Backend、pipeline 与统一文档的节点核对

| 节点 | 当前实现事实 | 不能据此推出的结论 |
|---|---|---|
| PDF | `PdfDocumentBackend` 暴露 `load_page()`/`iter_pages()`、页图像、文本、bitmap、尺寸和 outline；`docling-parse` 同时持有 pypdfium2 与 native parser，并在 unload 时分别释放 native document 和 PDFium document | Python `unload()` 调用成功不等于 native 崩溃隔离、进程回收或显存释放已验证 |
| 图片 | `ImageDocumentBackend` 绕过 PDFium，预先复制多帧图像为独立 RGB frame，以便页面处理；backend unload 关闭全部 frame 并再关闭输入流 | 多页图像的内存峰值和异常中断后的 frame 回收没有端到端现场证据 |
| Office | DOCX/PPTX/XLSX/ODF 多为声明式 backend；DOCX 对 Strict OOXML 做受大小上限约束的内存重写，并校验 ZIP slip/总解压大小；LibreOffice 仅在部分渲染/旧格式转换路径使用 | OOXML 单成员/总量保护不等于所有 Office backend、宏、外部引用和所有压缩路径都有统一资源预算 |
| Web/XML | HTML 使用 BeautifulSoup 和 `ImageResourceLoader` 生成文本、表格、图片、表单等 IR；Markdown、JATS、USPTO、XBRL、DocLang 等声明式 backend 直接构造 `DoclingDocument` 或经 `docling-core` deserializer 恢复 | 声明式 backend 直接生成文档不代表拥有第二套公共 schema；schema owner 仍是 `docling-core` |
| DCLX/EPUB | DCLX 流输入会 materialize 到 `mkdtemp(prefix="docling_dclx_")`，unload 删除目录；EPUB 启用本地图片抓取时创建 `docling_epub_` 临时目录，安全解包失败会主动删除 | 只有这些 backend 的正常/已捕获失败路径明确清理；崩溃、强杀和未执行 unload 仍需宿主扫描 |
| 媒体 | Audio/Video 使用 `NoOpBackend`，ASR/Video pipeline 自行处理文件；BytesIO 音频/视频会写 `NamedTemporaryFile(delete=False)`，Video 还通过 ffmpeg 写 WAV | `delete=False` 路径必须在异常、取消和进程退出后由统一临时资源 owner 回收；当前源码未形成全局登记账本 |
| pipeline | `BasePipeline.execute()` 依次执行 build、assemble、enrich、determine_status，最后在 finally 调 `_unload()`；异常变为 `FAILURE`，不抛错模式追加 pipeline `ErrorItem`；成功但有 errors 强制降为 `PARTIAL_SUCCESS` | finally 只覆盖已进入 pipeline 的对象；pipeline 构造失败、线程卡死和 native crash 需要外部监督 |
| PDF 页 | `PaginatedPipeline` 按 `page_batch_size` 初始化页、运行 build stages、按配置丢弃 image cache/parsed page 并 unload 页 backend；超时后记录 `TIMEOUT`、停止新 batch、过滤未初始化页 | 超时不是强制中断：正在运行的 native/model 调用可能继续，结果只能说明主流程记录了超时 |

`DocumentConverter` 的 pipeline cache key 是 `(pipeline_class, md5(str(pipeline_options.model_dump())))`，初始化由 `_PIPELINE_CACHE_LOCK` 串行保护，但 cache 没有公开的 eviction/close 协议。批量文档并发是批次级 `ThreadPoolExecutor`，只有 `doc_batch_size > 1` 且 `doc_batch_concurrency > 1` 时启用；线程池上下文退出会等待其 future，不能作为取消语义。

### 19.3 `DoclingDocument`、结果、分块与导出的所有权

- `DoclingDocument`、`DocItem`、页面和 serializer/chunker 基础类型来自 `docling-core`。本地 backend 通过 `DoclingDocument` 构造、deserializer 或 `model_validate_json()` 进入同一 IR；`ConversionResult` 不替代 IR，而是在 IR 外包裹输入、页面中间态、错误、计时、置信度和状态。
- `ConversionAssets.save()` 先在内存中构造 ZIP，再一次性写目标路径；包内固定写入 timestamp、version、status、errors、pages、timings、confidence 和 `document.json`。`load()` 对缺失成员采用默认值，对版本/status 等部分字段做容错恢复。源码没有临时目标文件、fsync、目标摘要、并发写锁或崩溃恢复标志，因此不能称平台级原子制品提交。
- `docling/chunking/__init__.py` 只是 re-export。`BaseChunker`、`HierarchicalChunker`、`HybridChunker` 的实际实现和 tokenizer 行为属于 `docling-core`；chunking 消费已完成的 `DoclingDocument`，不应参与输入路由、provider 调度或回写 IR。
- CLI 的 chunks 输出先调用 chunker，再对每个 chunk `contextualize()`；这与 Markdown、HTML、DocTags、DocLang、JSON 等一样是 IR 后投影。表格 span 的保真度依 serializer 而不同，Markdown 仍是有损投影。

### 19.4 OCR、模型权重与缓存核对

- OCR 通过 `OcrFactory`/注册表选择实现，选项区分 full-page、layout regions、PDF-aware layout regions 和语言；可选 RapidOCR、EasyOCR、Tesseract、macOS OCR、Nemotron、远程/KServe 等依赖由 extras 或 provider 提供。模型失败在 pipeline 中进入页/阶段 `ErrorItem`，不是统一自动重试。
- `BasePipeline` 将 `artifacts_path` 解析为 pipeline 或全局 settings 的目录，并在构造时只验证目录存在。没有路径时，各模型可能调用自身 `download_models()`；集中式 `download_models()` 默认写入 `settings.cache_dir / "models"`，再按模型 repo folder 分目录。路径存在只证明目录命中，不证明权重摘要、revision、可加载性或设备初始化成功。
- `settings.cache_dir` 默认是 `~/.cache/docling`；`scoped()` 只保存和恢复 perf/debug/inference 三组设置，不管理模型 cache、pipeline cache、线程、GPU 或临时文件。`PipelineOptions` 的 timeout 是阶段/provider 配置，不能替代整个任务 deadline。
- VLM API 模型内部可以使用自己的 `ThreadPoolExecutor` 和请求 timeout；远端请求、ASR、ffmpeg、LibreOffice、Tectonic、Tesseract 等各自拥有局部超时/进程边界，当前快照没有一个覆盖所有 provider 的取消令牌或 supervisor。

### 19.5 失败、超时、取消、卡死与崩溃的最终裁决

| 事件 | 当前代码能确认的事实 | 仍未确认/必须补的证据 |
|---|---|---|
| 部分成功 | 页级错误带 component/module/category/page_no；pipeline 有 errors 时不会保持 `SUCCESS`；`ConversionStatus.PARTIAL_SUCCESS` 可持久化到资产 | 各 backend/媒体 pipeline 是否都按同一粒度保留成功内容与失败项，需 L2/L3 真实样本核对 |
| 文档超时 | `document_timeout` 在分页 batch 完成后检查；threaded pipeline 用 run id 标记后续项为 `TIMEOUT` | 当前 batch/model 调用中的线程无法被 Python 安全强杀；超时后可能仍占 native handle、设备和临时文件 |
| 主动取消 | 本地 service client/scheduler 有 job/task cancel 入口 | 本地 `DocumentConverter`/pipeline 没有已核实的公共取消令牌；远端未确认取消不能写成 `canceled`，应保留 `cancellation_unconfirmed` |
| 线程卡死 | `ThreadedPipelineStage` 为非 daemon 线程；`stop()` 关闭输入队列并 join 15 秒，超时仅记录 warning，线程可能继续存活 | 必须由进程组/worker supervisor 记录 PID、停止结果、队列和资源租约；`Future.cancel()` 或 warning 都不是释放证明 |
| native 崩溃 | PDFium、docling-parse、Pillow、OCR runtime、torch/ONNX、ffmpeg 等均形成潜在 native/外部边界 | 当前仓库没有统一 crash supervisor、子进程重启、设备租约回收和残留临时目录审计 |
| 临时资源 | 部分 backend 用 `unload()` 清理；LibreOffice/Tectonic 等 `TemporaryDirectory`/显式 finally 路径有局部清理 | `mkdtemp`、`NamedTemporaryFile(delete=False)` 和外部进程异常路径必须由统一登记、超时清理和启动后扫描补强 |

因此，`ConversionStatus` 只能描述文档转换结果，不是可取消、可恢复、资源已释放的任务状态。至少要把“pipeline 返回对象”“部分页被过滤”“线程 join 超时”“HTTP 200”“日志 completed”和“远端 job 未确认”排除在成功/取消证明之外。

### 19.6 测试配置与证据边界

根 `pyproject.toml` 使用 pytest，`testpaths = ["tests"]`，并登记 `ml_ocr`、`ml_pdf_model`、`ml_vlm`、`ml_asr`、`cross_platform`、`external_service` 标记。`.github/scripts/pytest_marker_selection.py` 强制 CI 标记出现在模块级 `pytestmark`，核心 lane 忽略 ML 和 external service 文件，专门 suite 再按 marker 选择它们。

- 这套选择器能证明测试分层和 CI 选择规则，不能证明被忽略的模型、外部服务、取消、native crash 或资源清理路径通过。
- 测试大量使用 `tmp_path`/`tmp_path_factory` 生成样本；这证明测试自身的临时目录隔离策略，不证明生产路径的 `mkdtemp`、delete-false 文件、模型 cache 和服务结果会被统一回收。
- `test_failed_pages.py`、`test_threaded_pipeline.py`、`test_conversion_result_json.py`、各 backend 测试和 marker 选择测试覆盖了若干局部契约；在未安装依赖、未下载权重、未运行 pytest 的当前核对中，不把测试文件存在或静态读取升级为 L1-L4 通过。

### 19.7 当前核对深度研究结论

1. **吸收**：`DocumentConverter → _DocumentConversionInput → InputDocument → FormatOption → backend/pipeline → ConversionResult → DoclingDocument → chunk/export` 是当前源码唯一主链，格式差异应收敛在 backend/provider 和 provenance 中。
2. **明确边界**：声明式 backend、分页 backend、OCR/model stage、chunker 和 serializer 的职责已可分别定位；`docling-core` 继续是统一 IR 与 chunker 基础能力的 owner。
3. **保留事实**：PDF/Office/Web/XML/media 路径并非完全同质，尤其是 Office/EPUB/DCLX/ASR/video 的临时目录和外部进程处理存在不同清理语义，不能用一个“finally 已清理”结论覆盖。
4. **P0 缺口**：threaded stage 15 秒放弃、Python 线程不可强杀、native/provider 崩溃隔离、主动取消确认、delete-false 临时文件登记、模型权重校验/租约、导出原子提交和恢复证据仍不由当前源码统一保证。
5. **验证裁决**：当前核对只做静态深度源码研究，唯一后置命令是 `git diff --check`；未执行安装、模型下载、服务启动、pytest 或真实 provider，因此 L1-L4 继续保持未验证。只修改本文件，旧细探材料不删除。

## 20. 本次指定目录的实际源码映射

本次研究要求覆盖 `converter/input/backend/pipeline/document/chunker/export/OCR/model/cache/tests`。逐项核对目标快照后，发现这些名称并不全部对应根级物理目录；以下映射以源码实际路径为准，不能按概念名臆造目录。

| 指定概念 | 实际源码位置 | 主要事实 |
|---|---|---|
| converter | `docling/document_converter.py` | `DocumentConverter` 统一 `convert()`、`convert_all()`、`convert_string()`；`FormatOption` 将 `InputFormat` 绑定到 backend、pipeline 和 options；pipeline 实例按类和 options hash 缓存。 |
| input | `docling/datamodel/document.py`、`docling/datamodel/base_models.py`、`docling/datamodel/settings.py` | `_DocumentConversionInput` 处理 `Path`、URL、`DocumentStream`、`HttpSource`、来源下载、大小限制、内容 sniffing 和格式选择；`InputDocument` 保存 hash、format、limits、backend、页数和拒绝原因。 |
| backend | `docling/backend/` | `AbstractDocumentBackend` 是共同契约；`PaginatedDocumentBackend` 面向按页读取；`DeclarativeDocumentBackend` 直接返回 `DoclingDocument`。实际覆盖 PDF、图片、Office、ODF、HTML、Markdown、AsciiDoc、LaTeX、CSV、XML、JSON、EPUB、Email、BoxNote、VTT 和 METS/GBS。 |
| pipeline | `docling/pipeline/` | `BasePipeline.execute()` 固定 build → assemble → enrich → determine status → unload；具体族包括 `SimplePipeline`、标准/旧版/线程化 PDF、VLM、抽取、ASR 和 video。 |
| document | `docling/datamodel/document.py` 加外部 `docling_core.types.doc` | 本地定义 `InputDocument`、`ConversionAssets`、`ConversionResult` 和错误/页/计时包装；统一 IR 的 `DoclingDocument`、serializer 和核心 item 由 `docling-core` 所有。 |
| chunker | `docling/chunking/__init__.py` | 该文件仅 re-export `docling-core` 的 `BaseChunker`、`HierarchicalChunker`、`HybridChunker` 和 chunk model；本仓库没有第二套分块实现。 |
| export | 外部 `DoclingDocument` serializer、`docling/cli/main.py`、`docling/cli/export_utils.py`、`ConversionAssets.save()` | 导出是 IR 后投影，CLI 统一解析输出格式为 JSON/YAML/HTML/Markdown/TXT/DocTags/VTT/DocLang/DCLX/chunks；资产 bundle 是独立 ZIP，不是另一份解析 IR。 |
| OCR | `docling/models/base_ocr_model.py`、`docling/models/stages/ocr/`、`docling/models/factories/ocr_factory.py`、`docling/models/plugins/defaults.py` | OCR 是 pipeline stage/plugin；默认注册 Auto、EasyOCR、KServe v2、Nemotron、macOS、RapidOCR、Tesseract Python/CLI 等实现，由 `OcrFactory` 按 options 类型创建。不存在根级 `OCR/` 目录。 |
| model | `docling/models/`、`docling/datamodel/*model*`、`docling/utils/model_downloader.py` | 阶段模型、VLM/对象检测/图像分类推理引擎、factory、preset 和插件均在 `models/`；模型下载统一入口按开关写入 `settings.cache_dir / "models"` 或显式 `output_dir`。不存在根级 `model/` 目录。 |
| cache | `docling/datamodel/settings.py`、`docling/utils/model_downloader.py`、`DocumentConverter.initialized_pipelines` | `settings.cache_dir` 默认是 `~/.cache/docling`，主要承载模型制品；pipeline cache 是 converter 实例内存字典，受 `_PIPELINE_CACHE_LOCK` 保护，当前没有公开 eviction/close API。不存在源码根级 `cache/` 目录。 |
| tests | `tests/` | pytest 测试按 backend、input、pipeline/stage、OCR/VLM/ASR、导出/资产、CLI、服务客户端、E2E 和 marker 分层；测试样本和 groundtruth 与测试代码同属仓库测试树。 |

### 20.1 入口到输出的精确调用链

```text
DocumentConverter.convert / convert_all / convert_string
  → _DocumentConversionInput.docs
  → resolve_source_to_stream（URL/HttpSource）
  → _guess_format（扩展名、MIME、内容、ZIP/XML/CSV/TAR）
  → InputDocument（hash、limits、backend、validity）
  → FormatOption.pipeline_cls + backend
  → BasePipeline.execute
  → ConversionResult（pages、document、errors、timings、confidence、status）
  → DoclingDocument serializer / ConversionAssets.save / chunker
```

几个边界必须同时保留：

- `convert_string()` 只接收 Markdown、HTML 和 DocLang 字符串；它通过 `DocumentStream` 回到同一输入链，不是旁路解析器。
- URL 解析失败或超出 `max_file_size` 会产生 invalid `InputDocument`，使批量迭代能够保留按文档分类的失败；`raises_on_error=True` 再将该结果包装为 `ConversionError`，并保留原始 cause。
- 未识别格式或不在 `allowed_formats` 中使用 dummy backend/`SKIPPED` 或失败结果，不会构造一个伪造的空成功文档。
- 声明式 backend 直接生成统一 IR；分页 backend 先产生 `Page` 和中间预测，再由 pipeline 装配文档。二者都不能拥有自己的公共文档 schema。

### 20.2 模型与插件注册边界

`BaseFactory` 以 `BaseOptions` 的具体类型为 key，维护 options class 到模型 class 的唯一映射，并记录 `kind`、plugin name 和 module metadata。重复注册同一 options type 会被拒绝；外部 setuptools entry point 只有在 `allow_external_plugins=True` 时才允许加载。根 `pyproject.toml` 通过 `docling_defaults = "docling.models.plugins.defaults"` 注册默认插件。

因此，模型选择分成三层：

1. `PipelineOptions`/stage options 以 Pydantic 字段和 preset 描述“选择什么”。
2. factory/plugin 以 `kind` 将 options 解析为具体 stage/model class。
3. model/inference engine 负责加载本地或远端实现，并把预测转回 page/document enrichment 契约。

OCR、layout、table structure、picture description 等共用此模式；外部 provider 的 SDK、权重格式和原始返回对象不应穿过 pipeline 的统一结果边界。

### 20.3 输出、资产与缓存的区别

- `DoclingDocument.export_to_dict()`、`export_to_json()`、`export_to_html()`、`export_to_markdown()`、DocTags、DocLang 和 CLI 输出是同一 IR 的不同投影；其中 Markdown 对表格合并语义可能有损。
- `ConversionAssets.save()` 先在内存中构造 ZIP，再写入目标文件，包含 `timestamp.json`、`version.json`、`status.json`、`errors.json`、`pages.json`、`timings.json`、`confidence.json` 和 `document.json`。它是项目级保存格式，当前源码未提供临时目标文件、fsync、摘要、并发写锁或崩溃恢复协议。
- 模型 cache 由下载器写入目录，pipeline cache 由 converter 保存在内存，页面 image/parsed-page cache 由 pipeline 在批次结束时按选项清理；三者生命周期不同，不能以“cache 命中”推断模型已加载或资源已释放。

### 20.4 测试树的证据边界

测试文件覆盖的事实类型包括：各格式 backend 和格式探测、JSON/资产 round-trip、失败页和 threaded pipeline、heading/reading order/table/layout、OCR/VLM/ASR/video、CLI、服务 datamodel/SDK、外部服务 scaffolding 和 E2E。`pyproject.toml` 将模型及外部服务测试标记为 `ml_ocr`、`ml_pdf_model`、`ml_vlm`、`ml_asr`、`cross_platform`、`external_service`；`.github/scripts/pytest_marker_selection.py` 要求 CI 标记位于模块级 `pytestmark`，并据此生成核心忽略参数和专项 suite。

本次只进行源码和测试静态读取，没有安装依赖或执行 pytest。因此：测试文件存在只能证明测试意图和覆盖位置，不能证明对应 backend、模型、缓存、导出、取消、native crash 或资源清理路径实际通过；本文件的 L1-L4 结论仍保持“未验证”。

## 21. 当前核对完整分段审计收口

当前核对按实际物理布局分段核对了 `docling/document_converter.py`、`docling/datamodel/document.py`、`docling/backend/`、`docling/pipeline/`、`docling/datamodel/`、`docling/chunking/`、`docling/cli/export_utils.py`、`docling/models/`、`docling/utils/ocr_utils.py`、`docling/utils/model_downloader.py`、`tests/`、`docs/`、根 `pyproject.toml` 及包 README。目标树没有根级 `converter/`、`input/`、`document/`、`export/`、`OCR/`、`model/`、`cache/` 目录；这些名称是概念分区，源码事实以第 20 节映射为准。

### 21.1 端到端事实链

```text
Path / URL / DocumentStream / HttpSource
  → DocumentConverter.convert*()
  → _DocumentConversionInput.docs()
  → resolve_source_to_stream() / _guess_format()
  → InputDocument(hash, limits, backend, valid)
  → FormatOption(backend + pipeline + options)
  → BasePipeline.execute(build → assemble → enrich → status → unload)
  → ConversionResult(document + pages + errors + timings + confidence + status)
  → docling-core serializer / chunker / ConversionAssets.save()
```

这条链是当前源码可直接证明的本地主链。`convert_string()` 只接受 MD、HTML、XML_DOCLANG，并通过 `DocumentStream` 回到同一链路；音频和视频使用 `NoOpBackend`，分别在 ASR/Video pipeline 中生成文档；服务 client 是外部 `docling-serve` 的协议适配器，不是本地服务端。

### 21.2 组件责任与重复冲突裁决

| 主题 | 当前唯一事实 owner | 不应重复维护的内容 |
|---|---|---|
| 格式路由 | `DocumentConverter.FormatOption` 与 `_get_default_option()` | CLI、backend、服务 client 各自复制 format map |
| 输入来源与探测 | `_DocumentConversionInput` / `InputDocument` | 每个 backend 自行下载 URL、解释大小限制或建立第二套 MIME map |
| backend 生命周期 | `AbstractDocumentBackend.unload()` 及具体 backend 覆盖 | pipeline、导出器和 CLI 重复关闭同一底层对象并把关闭日志当作完整释放证据 |
| 页面语义编排 | pipeline 及 `Page`/`AssembledUnit` 中间模型 | OCR、layout、table provider 各自定义公共文档 schema |
| 统一 IR | 外部 `docling_core.types.doc.DoclingDocument` | 本仓库、平台模块、provider 再复制一套 `DoclingDocument` 字段模型 |
| serializer/chunker | `docling-core`；本仓库 `chunking/__init__.py` 仅 re-export | CLI、RAG 示例、服务 client 各自实现分块或序列化规则 |
| 模型/OCR 选择 | options → factory/plugin → model | 每个 stage 自己注册同一 options type、偷偷 fallback 或绕过 factory |
| 项目资产保存 | `ConversionAssets.save/load()` | 把 ZIP bundle、IR JSON、CLI 输出和平台任务记录混称为同一制品 |

公开 `docs/concepts/architecture.md`、`docling_document.md`、`chunking.md`、`serialization.md` 与源码在上述边界上是一致的；根文档此前把“平台应补的原子写入、任务账本、租约和取消确认”与“Docling 当前已提供的能力”混写。本节及第 19 节以后以“当前事实 / 目标平台裁决”明确分栏，前文相同语义只作设计约束，不应解读为当前实现。

### 21.3 资源、缓存和终态审计

- 输入路径或流在 `InputDocument` 初始化时计算 hash、文件大小并创建 backend；分页 backend 还立即读取页数。失败输入会释放已创建 backend；进入 pipeline 后由 `BasePipeline.execute()` 的 `finally` 调 `_unload()`。
- PDF threaded pipeline 使用有界 `ThreadedQueue`、单独 producer 和多个非 daemon stage thread。队列有 back-pressure 和 close 传播，但 `ThreadedPipelineStage.stop()`、producer join 最多等待 15 秒，超时会放弃仍存活的线程；代码明确记录“resources may leak”。这不是可证明的取消或释放。
- pipeline cache 是 converter 实例内存字典，key 为 pipeline class 加 options dump 的 MD5；只有初始化锁，没有公开 eviction/close，也没有跨 converter 的共享缓存一致性协议。
- 模型下载器默认写 `settings.cache_dir / "models"`，`artifacts_path` 只检查目录存在；源码未提供统一 revision/hash 校验、坏缓存隔离、显存租约或 provider 崩溃回收证明。
- `ConversionAssets.save()` 在内存构造 ZIP 后直接以 `filename.open("wb")` 写目标，未实现临时目标文件、fsync、摘要、并发写锁或崩溃恢复标志。此前出现的“原子替换”只能作为平台目标要求，不能作为当前 Docling 事实。
- Video pipeline 对 BytesIO 视频、ffmpeg WAV 使用 `NamedTemporaryFile(delete=False)`；DCLX、EPUB 等 backend 也使用临时目录。正常 finally/unload 路径有局部清理，但没有覆盖强杀、native crash 和宿主重启的全局资源登记账本。

当前源码能表达文档结果 `PENDING/STARTED/SUCCESS/PARTIAL_SUCCESS/FAILURE/SKIPPED` 和页级 `ErrorItem`，不能单独表达平台任务的 `queued`、取消确认、进程崩溃、资源租约终态或恢复事实。`SUCCESS` 也只在 pipeline 没有错误时成立；它不证明模型、线程、临时文件或设备资源已释放。

### 21.4 文档重复与漂移处理

1. 根 `ARCHITECTURE.md` 是本次审计的唯一综合建档；不新增另一份 `细探` 类事实笔记，也不把 `docs/concepts/*` 改造成平台设计文档。
2. `docs/concepts/*` 保持面向 Docling 用户的简洁公共说明：`architecture.md` 说明 converter/backend/pipeline/result，`docling_document.md` 说明 IR，`chunking.md` 和 `serialization.md` 说明下游投影。资源治理、失败矩阵和本地快照版本差异只在根建档维护，避免用户文档重复平台审计内容。
3. 根文档中的“当前源码事实”不得由 README、示例、测试文件存在、模型目录存在、HTTP 200、日志或对象返回升级为运行证据；真实状态仍由 L1-L4 验证命令决定。
4. 当前工作树在审计前已存在未跟踪的 `ARCHITECTURE.md`；当前核对只修改该文件，不吸收、不删除、不重写其他未由当前核对创建的文件。

### 21.5 当前核对结论与验证边界

- 审计结果：静态 L0 完成；输入、路由、backend、pipeline、IR、chunker、export、OCR、model、cache、tests 和 docs 均有实际路径与责任边界记录。
- 资源结论：正常路径存在局部 `unload()`/`finally`/临时清理，但 threaded stop 超时、pipeline cache 无 eviction、模型缓存无统一校验、delete-false 临时文件和直接覆盖资产文件仍是明确风险。
- 文档结论：公开概念文档与源码主链一致；根文档此前的设计性“原子提交/租约/取消/崩溃监督”已在本节标明为平台目标，不再冒充当前实现。
- 验证边界：未安装依赖、未下载模型、未启动外部服务、未运行 pytest；当前核对没有 L1-L4 运行证据。仅可使用 `git diff --check` 验证 Markdown 差异格式。
