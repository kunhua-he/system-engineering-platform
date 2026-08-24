# unstructured 架构建档

## 1. 项目定位与审计边界

`unstructured` 是 Unstructured-IO 的 Apache-2.0 开源 Python 库，定位是非结构化文档的摄取与预处理：把 PDF、Office、HTML、Markdown、邮件、图片、音频及表格等输入解析为统一的 `Element` 流，再按需做清洗、元数据增强、chunking、embedding 或序列化。它是处理内核，不是本地 API 服务、连接器平台或数据库；批量连接器主要在独立的 `unstructured-ingest` 项目中，托管能力通过 `partition_via_api()` 接入。

本文件描述本地归档源码的架构事实。源码参考库规则是只读研究：当前核对没有安装依赖、启动服务、构建制品或运行测试；仅新增本文件。既有 `细探-unstructured.md` 保留为研究材料，本文件是本仓唯一架构事实源。

### 审计版本

| 项目 | 事实 |
|---|---|
| 本地版本 | `0.25.1`，来自 `unstructured/__version__.py` |
| 本地基线 | `d309caf8ee20b735eb105d4e16ac3f04e5a48172`，分支 `main`，2026-07-15 |
| 远程 | `https://github.com/Unstructured-IO/unstructured.git`，`origin/main` |
| 远程最新 | `104b585d4e84ad987b121e86aecf80315e8a12a6`，版本 `0.26.3`，2026-08-18 |
| 新鲜度 | 本地落后远程 7 个提交；共同祖先就是本地基线 |
| 远程独立快照 | `/tmp/unstructured-remote-104b585d`，经 `http://127.0.0.1:4780` 获取；未覆盖目标工作树 |
| 远程关键增量 | `441b9d68` HTML 父节点查找优化；`4c61d871` 懒 chunking；`8c4592a` telemetry 默认行为恢复；`44f9d747` PDF 内容流上限；`6d383401` HTML 合并线性化；`104b585d` file-like 字符集回退 |

远程增量只用于新鲜度与风险对照，不改写本地基线的源码事实。若后续要裁决最新行为，应在该独立快照上继续核对，再把确认后的结论合并回本文件。

## 2. 总体架构流程图

```text
输入边界
  filename(path) / file(IO[bytes]) / text(str) / url(HTTP)
  └─ exactly_one()：每个 partitioner 校验输入源互斥
       │
       ├─ url → safe_get()：协议、主机/IP、DNS rebinding、代理、跳转、超时校验
       │             → BytesIO + Content-Type/encoding
       │
       ▼
  detect_filetype()
  ├─ 二进制确定性识别：OLE / ZIP 内部结构
  ├─ 调用方 Content-Type（低可信信号）
  ├─ libmagic；不可用或 octet-stream 时回退 filetype
  ├─ 文本差分：扩展名、CSV、EML、JSON/NDJSON
  └─ 扩展名兜底 → FileType.UNK
       │
       ├─ JSON → 1 MiB 内 JSON/NDJSON 消歧 → partition_json()
       ├─ NDJSON → partition_ndjson()
       ├─ PDF → partition_pdf()（fast / hi_res / ocr_only / auto）
       ├─ 图片 → partition_image()
       └─ 其他格式 → _PartitionerLoader.get(FileType)
                         ├─ is_partitionable
                         ├─ optional dependency_exists()
                         └─ importlib 懒加载 partition_xxx()
       │
       ▼
  格式 partitioner
  ├─ text / markdown / XML / HTML / email / MSG
  ├─ doc / docx / ppt / pptx / xls / xlsx / epub / odt / rst / rtf
  ├─ image / PDF / audio（OCR、布局模型、STT 为可选增强）
  └─ 装饰器：register_partitioner / process_metadata /
             add_metadata_with_filetype / add_chunking_strategy
       │
       ▼
  Element 流
  ├─ Element / Text 家族 / Table / TableChunk / CheckBox
  ├─ ElementMetadata：来源、文件、页码、层次、坐标、表格、模型溯源
  ├─ 确定性 hash ID（默认后处理）或 unique UUID
  └─ 可选：cleaners → chunking → embed → staging 序列化/导出
       │
       ├─ chunk_elements() / chunk_by_title()
       │    PreChunker → PreChunk → 文本 _Chunker / 表格 _TableChunker
       │    TableChunk → reconstruct_table_from_chunks()
       ├─ elements_to_json()/elements_to_ndjson()/elements_to_html()/elements_to_md()
       └─ partition_via_api()/partition_multiple_via_api() → API 响应 → elements_from_dicts()
```

## 3. 分层与目录地图

本地 Git 基线共 1317 个受跟踪文件；其中 `unstructured/` 141 个、`test_unstructured/` 140 个、`test_unstructured_ingest/` 603 个、`example-docs/` 254 个。目录职责如下：

| 目录/文件 | 职责 | 关键入口或标识 |
|---|---|---|
| `unstructured/partition/` | 各格式解析器与统一自动路由 | `partition/auto.py:partition` |
| `unstructured/file_utils/` | 文件类型、编码、依赖、转换等基础设施 | `FileType`、`detect_filetype()` |
| `unstructured/documents/` | `Element` 数据模型、本体中间表示、HTML 净化 | `elements.py`、`ontology.py` |
| `unstructured/chunking/` | 文本/表格分块与策略注册 | `chunk_elements()`、`chunk_by_title()` |
| `unstructured/staging/` | JSON、NDJSON、CSV、HTML、Markdown、标注格式等落地 | `elements_from_dicts()`、`elements_to_*()` |
| `unstructured/embed/` | 外部 embedding provider 的适配接口族 | `openai`、`huggingface`、`voyageai` 等模块 |
| `unstructured/metrics/` | 文本、表格、元素类型、目标检测评估 | `evaluate.py` 及 `metrics/table/` |
| `unstructured/nlp/` | 语言检测、句子/模式与 spaCy 相关能力 | `tokenize.py`、`patterns.py` |
| `unstructured/cleaners/` | 文本清洗 brick | `cleaners/core.py` |
| `unstructured/safe_http.py` | 用户 URL 的统一安全外联边界 | `safe_get()` |
| `unstructured/partition/api.py` | Unstructured REST API 客户端 | `partition_via_api()` |
| `unstructured/cli.py`、`doctor.py` | 环境与文件类型能力诊断 CLI | `unstructured doctor` |
| `test_unstructured/` | 核心单元/集成行为契约 | 分区、模型、chunking、staging、安全测试 |
| `test_unstructured_ingest/` | 连接器与结构化输出快照/指标测试 | expected structured output |
| `example-docs/` | 各格式输入、JSON/NDJSON 示例与 fixture | `arbitrary-records.json`、`arbitrary-records.ndjson` |
| `Dockerfile`、`Makefile`、`.github/workflows/` | 依赖、容器和 CI 约定 | `make test`、`make check`、benchmark workflow |

`unstructured/partition/__init__.py` 与 `unstructured/staging/__init__.py` 为空；公开导出主要通过具体模块和 `unstructured.chunking.__init__` 完成。导入 `unstructured` 时会初始化 `env_config` 并调用 `init_telemetry()`，因此包导入本身是一个明确的启动边界。

## 4. 核心数据流与路由

### 4.1 统一入口 `partition()`

`unstructured.partition.auto.partition()` 接收 `filename`、`file`、`url` 三种来源之一，并接受 `content_type`、`encoding`、`strategy`、语言、表格抽取、图片载荷和 `metadata_filename` 等跨格式参数。处理顺序是：

1. `exactly_one(file=file, filename=filename, url=url)` 拒绝输入源缺失或重复。
2. `url` 通过 `file_and_type_from_url()` 调用 `safe_get()`，生成 `BytesIO` 并依据响应头/编码探测类型；非 URL 输入调用 `detect_filetype()`。
3. 计算 `infer_table_structure`；`pdf_infer_table_structure` 仍保留兼容逻辑并发出弃用警告。
4. PDF 和图片走特化参数分支；JSON/NDJSON 只透传其自身需要的参数；`EMPTY` 直接返回 `[]`。
5. 其他类型复制并补齐语言、编码、策略、表格和起始页参数后调用 partitioner。
6. `augment_metadata()` 为每个元素补 `url`、`data_source` 与规范化 `filetype`。

`_PartitionerLoader` 以 `FileType` 为键维护模块级 `_partitioners` 缓存。首次加载先检查 `is_partitionable`，再按 `importable_package_dependencies` 检查可导入包，缺失时统一抛出包含 `pip install "unstructured[extra]"` 的 `ImportError`，最后按 `partitioner_module_qname` 懒加载函数。这是“检测 → 能力表 → 依赖门禁 → 动态调用”的闭合路由。

### 4.2 `FileType` 声明式能力表

`unstructured/file_utils/model.py:FileType` 不是只有名称的枚举；每个成员携带：

- `partitioner_shortname`：如 `docx`、`image`；由模板派生 `partitioner_function_name` 与 `partitioner_module_qname`。
- `importable_package_dependencies`：运行时 `import` 名称，例如 `DOCX` 使用 `docx`，而发行包是 `python-docx`。
- `extra_name`：对应安装 extra，如 `pdf`、`image`、`xlsx`。
- `extensions`、`canonical_mime_type`、`alias_mime_types`。
- 可由 `create_file_type()` 动态增加成员，并由 `register_partitioner()` 回填实现模块路径。

基线支持 BMP、CSV、DOC、DOCX、EML、EPUB、FLAC、HEIC、HTML、JPG、JSON、M4A、MD、MP3、MSG、NDJSON、ODT、OGG、OPUS、ORG、PDF、PNG、PPT、PPTX、RST、RTF、TIFF、TSV、TXT、WAV、WEBM、XLS、XLSX、XML、ZIP、UNK、EMPTY 等类型。`ZIP`、`UNK`、`EMPTY` 是可识别但不可直接 partition 的类型。

### 4.3 `detect_filetype()` 多信号识别

`unstructured/file_utils/filetype.py:detect_filetype()` 的优先级是：

1. OLE 魔数及流名识别 DOC/PPT/XLS/MSG；ZIP 内部文件名识别 DOCX/XLSX/PPTX，`mimetype` 识别 EPUB/ODT。
2. 调用者提供的 `content_type`，但代码明确把它视为不可靠断言。
3. `libmagic` MIME；不可用或返回 `application/octet-stream` 时回退 `filetype`。
4. 文本差分：CSV 列数、邮件头、JSON 前缀及扩展名。
5. 文件扩展名作为弱信号，最终失败返回 `FileType.UNK`。

JSON 结果会再执行 `_disambiguate_json_file_type`：最多读取 1 MiB；`.ndjson` 扩展名优先；完整严格 JSON 成功时判 JSON；多行逐行严格解析时判 NDJSON。文件游标会被恢复到 0，以支持“先检测、再用同一 file-like 对象 partition”。`loads_strict_json()` 与 partitioner 共用并拒绝 `NaN`、`Infinity`、`-Infinity`。

## 5. 统一 IR：`Element` 与元数据

### 5.1 `Element` 家族

`unstructured/documents/elements.py` 中的 `Element` 是抽象基类，语义是文档中可独立处理的组件。`Text` 提供字符串正文，常用类别包括 `Title`、`NarrativeText`、`ListItem`、`Header`、`Footer`、`FigureCaption`、`Image`、`Table`、`PageBreak`、`CodeSnippet`、`Formula`、`FormKeysValues`、`DocumentData`；`CompositeElement` 由 chunking 产生。`CheckBox` 是带 `checked` 的非 `Text` 元素，`TableChunk` 继承 `Table`。

元素 ID 默认惰性生成 UUID；`Element.id_to_hash(sequence_number)` 以 `metadata.filename + text + page_number + sequence_number` 做 SHA-256 并截取前 32 位，用于默认可复现 ID。它是确定性去重指纹，不是匿名化手段：输入可枚举时不能当作隐私保护。

基础 `to_dict()` 形状为：

```json
{
  "type": "NarrativeText",
  "element_id": "…",
  "text": "…",
  "metadata": {}
}
```

### 5.2 `ElementMetadata`

`ElementMetadata` 是“已知字段 + 可扩展字段”的稀疏模型：类上声明约 60 个常用字段，同时允许格式/集成增加 ad-hoc 字段；赋值为 `None` 会删除字段，序列化会省略 `None` 与空集合。重要字段包括：

- 文件与来源：`filename`、`file_directory`、`filetype`、`url`、`data_source`、`last_modified`。
- 页面与层次：`page_number`、`parent_id`、`category_depth`、`coordinates`、`detection_origin`。
- 表格：`text_as_html`、`table_extraction_method`、`table_id`、`chunk_index`、`is_continuation`、`num_carried_over_header_rows`。
- 邮件/音频/图像：`subject`、`sent_from`、`sent_to`、`segment_start_seconds`、`segment_end_seconds`、`image_base64`、`image_mime_type`、`image_url`。
- 模型溯源：`enrichment_origins` 记录属性由哪类 provider/model 产生。
- 分块溯源：`orig_elements` 以 JSON → 压缩 → base64 保存原始元素，并由 `MAX_DECOMPRESSED_SIZE` 约 200 MB 上限防止解压炸弹。

`process_metadata()` 等装饰器在 partitioner 外统一执行文件名、目录、层级与 hash ID 等横切处理，使格式解析器主要关注格式本身。

`ElementMetadata` 还承载几类容易在概览中遗漏的领域信息：`DataSourceMetadata` 保存
`url`、版本、`record_locator` 与权限数据；`CoordinatesMetadata` 要求坐标点与坐标系成对出现；
`parent_id`/`category_depth` 表达文档层次；`routing`/`routing_score` 表达页面级路由；邮件字段
保存收发件人、抄送、主题等信息；音频元素保存 `segment_start_seconds`/
`segment_end_seconds`。`enrichment_origins` 按属性保存 `{type, provider, model}` 来源链，
因此模型增强并不是无来源地覆写 IR，而是可以留下逐属性溯源。

## 6. JSON/NDJSON 统一化

这是本归档目录名 `document_json_unification` 对应的核心演进。`partition/common/json_partitioning.py` 以 `is_element_shaped_dict()` 作为模式判别器：

- **rehydrate 模式**：JSON 顶层为非空数组且每项都具备已知 `type` 及其必需字段，或为 `CheckBox`/`TableChunk` 特殊形状；通过 `elements_from_dicts()` 还原元素。
- **arbitrary 模式**：任意其他合法 JSON 转为 `Text`；对象/标量一个元素；全对象数组每个对象一个元素；混合数组或标量数组整体一个元素；空对象为 `Text("{}")`，空数组不产生元素。
- 形状像元素但 `metadata` 损坏时包装为 `ValueError("…could not be reconstructed…")`，不泄漏底层 `zlib.error`/`binascii.Error`。
- `sort_keys=True, indent=2` 使任意 JSON 输出确定、可 diff；这会改变客户字段原始顺序。

`partition_ndjson()` 保持一行一个 JSON 值：空行跳过；所有行都符合元素形状才批量 rehydrate，否则每行一个 `Text`。数组值在 NDJSON 中也保持单行一个元素，不按 JSON 模式拆开。混合元素/任意记录整体走 arbitrary，避免静默丢记录。

已读测试覆盖：JSON/NDJSON 从路径、file-like、文本输入；空值、非法 JSON、深层嵌套、非标准常量；任意对象/数组/标量；元素数组回环；`TableChunk` 回环及表格重建；文件类型检测后复用同一 file handle；元数据文件名和修改时间优先级。

## 7. Chunking 与表格协议

`unstructured/chunking/` 使用两阶段模型：

```text
Element iterable
  → PreChunker.iter_pre_chunks：按语义边界与软窗口装箱
  → PreChunk.iter_chunks：文本 _Chunker / 表格 _TableChunker
  → CompositeElement 或 TableChunk
```

`ChunkingOptions` 约束 `max_characters` 与 `max_tokens` 互斥；token 模式必须有 `tokenizer`；`new_after_n_chars/tokens` 是软上限，`max_*` 是硬上限；`overlap` 不能达到硬上限；`skip_table_chunking=True` 必须与默认 `isolate_table=True` 配合。`text_splitting_separators` 默认优先按换行、空格切分，最后才逐字符切分。`overlap_all` 才把重叠扩展到普通元素边界。

`dispatch.py` 的 `_chunker_registry` 默认注册 `basic` 与 `by_title`，`register_chunking_strategy()` 可增加策略；`add_chunking_strategy` 装饰器从 partitioner 参数中取出策略名，并只透传目标 chunker 支持的参数。`by_title` 按 `Title` 形成语义段，并可用 `multipage_sections` 控制换页边界。

表格默认隔离在自己的 pre-chunk。超窗表格按 HTML 行/单元格/文本递归拆为 `TableChunk`，并携带：同一 `table_id`、递增 `chunk_index`、续块 `is_continuation`、重复表头计数 `num_carried_over_header_rows`。`reconstruct_table_from_chunks()` 按 `table_id` 分组和 `chunk_index` 排序，去除重复表头后合并文本和 `text_as_html`。这是可序列化、可重建的跨块契约。

分块器的尺寸语义是“双阈值”而非单一最大长度：`hard_max` 是不可越过的硬上限，
`soft_max`（`new_after_n_chars` 或 token）是达到后优先闭合的软窗口；`overlap` 默认只用于
文本切分产生的续块，`overlap_all` 才扩展到普通元素边界。文本按换行、空格依次切分，
最后才退化到逐字符；token 模式尽量在 token 边界收敛。字段合并由
`ConsolidationStrategy` 和字段级策略表决定（例如来源取首个、语言去重列表、强调文本拼接），
不是对所有 metadata 做无差别覆盖。表格切分失败时保留可诊断告警并回退纯文本切分，避免把
单个坏表格变成整份文档失败。

远程 0.26.3 新增 `iter_chunk_elements()` 等懒入口，并在 token 配置验证阶段解析 tokenizer；本地 0.25.1 只有列表入口，不能把远程懒 API 当成本地已存在能力。

## 8. HTML、Ontology 与安全输出

HTML 解析支持 v1 与 v2：

- v1 在 `partition/html/partition.py` 直接依据 DOM、标签、层级与文本特征生成 `Element`。
- v2 通过 `documents/ontology.py:OntologyElement` 及其 `Document`、`Page`、`Column`、`Paragraph` 等模型建立中间树，再由 `mappings.py`/`transformations.py` 做 Ontology ↔ `Element` 双向转换。
- 标题 `h1`–`h6` 映射为 `Title`，`category_depth` 来自标题级别；`parent_id` 保留层级；多列布局依靠容器栈重建。
- 空输入返回空 `Document`；没有 `text_as_html` 的元素跳过而不使整棵树失败；未知父 ID 留在当前容器，避免错误回退到文档根。

`documents/html_sanitization.py` 与 `OntologyElement.to_html()` 是输出端防线：标签、属性、URL scheme、CSS 属性白名单；删除 `on*` 事件属性、危险 `javascript:`/`vbscript:`/非图像 `data:`；HTML 文本和属性值最终转义；`target="_blank"` 增加 `noopener noreferrer`。该修复对应 GHSA-v5mq-3xhg-98m9，不能把“输入已解析”误认为“输出可安全渲染”。

## 9. PDF/Image/OCR/STT 与可选能力

`PartitionStrategy` 有 `auto`、`fast`、`hi_res`、`ocr_only`。PDF/Image 会依据文本可提取性、`unstructured_inference`、Tesseract 和表格/图像需求做依赖感知回退；`hi_res` 可产生坐标、表格 HTML、图像载荷，`ocr_only` 依赖 OCR，音频由 speech-to-text agent 产生带时间段元数据的 `NarrativeText`。

回退不是静默替换：`auto` 会根据 PDF 文本可提取性及表格/图像需求选择 fast 或 hi-res；
hi-res 缺少布局依赖时优先回退 OCR（存在 Tesseract 时），否则回退 fast；OCR 不可用时，
文本可提取则回退 fast，否则尝试 hi-res；三条路径均不满足时抛出 `ValueError`。因此上层
可以把“采用了哪条解析能力链”作为可解释的运行结果，而不能假定 `auto` 永远等价于某一种
解析器。`table_extraction_method`（`grid`/`tatr`/`vlm`）记录表格结果的来源。

核心 partition 管线本身没有提示词编排：格式解析主要是确定性解析库与规则；模型只在
布局检测、OCR、STT、可选语言检测和表格增强等提供者边界出现。`unstructured/embed/`
提供 OpenAI、Vertex AI、Hugging Face 等外部 embedding provider 的适配接口，但不内置模型。
这一区分是架构边界，不应将“存在模型适配器”写成核心解析依赖。

核心依赖尽量保持轻量；格式能力走 extras：

- 基础：`beautifulsoup4`、`charset-normalizer`、`filetype`、`html5lib`、`langdetect`、`lxml`、`nh3`、`spacy`、`numpy`、`python-magic`、`requests`、`unstructured-client` 等。
- 文档 extras：`docx`、`pptx`、`pypandoc-binary`、`markdown`。
- `pdf/image`：`pdf2image`、`pdfminer.six`、`pypdf`、`pikepdf`、`Pillow`、`unstructured-inference`、`unstructured-pytesseract`。
- `csv/xlsx`：`pandas`、`openpyxl`、`xlrd`、`msoffcrypto-tool`。
- `audio`：`openai-whisper`；`huggingface`、`chunking-tokens`、`ingest` 是独立功能 extras。

`pyproject.toml` 要求 Python `>=3.11, <3.14`，`.python-version` 固定 `3.12`，使用 `uv` + `hatchling`；脚本入口是 `unstructured = "unstructured.cli:main"`。`uv.lock` 负责多平台解析；CI 还需要 `libmagic-dev`、`poppler-utils`、`tesseract`、`libreoffice` 等系统工具。依赖未安装时，应期待 `_PartitionerLoader` 给出统一 extra 提示，而不是把深层导入错误当成业务错误。

## 10. API、CLI 与输出边界

### Python API

| API | 输入/用途 | 输出/错误边界 |
|---|---|---|
| `unstructured.partition.auto.partition()` | 自动检测并路由单文档 | `list[Element]`；输入互斥、未知/不可分区类型、缺依赖会报错 |
| `partition_json()` | JSON 文档或序列化元素数组 | `list[Element]`；任意 JSON 转 `Text`，非法载荷 `ValueError` |
| `partition_ndjson()` | 每行一个 JSON 值 | 每行一个 `Element`；空行跳过，坏行 `ValueError` |
| `partition_html()` / `partition_pdf()` 等 | 格式专用参数 | 直接返回格式元素；URL 走 `safe_get` |
| `partition_via_api()` | 文件 + `api_url` + `api_key` | HTTP 200 的 JSON 还原为元素；非 200 `ValueError`；支持 retry config |
| `partition_multiple_via_api()` | 多文件批量上传 | `list[list[Element]]`；长度与文件名/类型不匹配时报错 |
| `chunk_elements()` / `chunk_by_title()` | 元素流 + 字符/token窗口 | `CompositeElement`/`TableChunk` 列表；参数契约严格校验 |
| `reconstruct_table_from_chunks()` | 混合元素中的表格块 | 按表格顺序返回 `Table`；没有有效块返回 `[]` |
| `elements_from_dicts()` | 序列化元素字典 | rehydrate `Element`；未知 type 静默跳过是当前底层行为，JSON 路径先用 shape predicate 防误判 |
| `elements_to_json()` / `elements_to_ndjson()` / `elements_to_md()` / `elements_to_html()` | 元素落地/转换 | 字符串或写文件；`orig_elements` 使用压缩 base64 |

### CLI

`pyproject.toml` 暴露 `unstructured` 命令，`unstructured.cli:main` 目前只提供 `doctor` 子命令：

- `unstructured doctor`：打印环境、依赖和系统能力报告。
- `unstructured doctor --for TYPE`：检查某文件类型/族是否可用，未就绪退出码 1，参数错误退出码 2。
- `unstructured doctor --file PATH`：先探测路径类型再检查能力。

CLI 不是文档解析 HTTP 服务；HTTP 服务由外部部署或 `partition_via_api()` 对接。

## 11. 安全、资源与错误处理

- `safe_get()` 只允许 `http`/`https`；拒绝 localhost、云 metadata、Kubernetes 默认域名、loopback/private/link-local/reserved/multicast/CGNAT；DNS 解析与真实 socket 建连均校验，防 DNS rebinding。
- 主机名按 IDNA 规范化；IPv6 中的 IPv4-mapped、6to4、NAT64 与兼容地址会解开后重新检查，
  且连接前会检查 `getaddrinfo()` 返回的全部地址，而不是只检查第一个解析结果。
- 禁止安全模式代理，因为代理会使连接级 IP 校验只看到代理地址；`session.trust_env=False` 同时关闭环境代理、netrc 和 CA 环境覆盖。
- 手动处理最多 10 跳重定向，每跳重新验证；跨源跳转剥离 `authorization`、`cookie`、`proxy-authorization`、`auth` 和 `cookies`。
- `UNSTRUCTURED_ALLOW_PRIVATE_URL=1` 或 `allow_private=True` 是显式逃生门，只适合受控内网场景，不能默认开启。
- JSON/NDJSON 检测上限 1 MiB；`orig_elements` 解压上限约 200 MB；PDF hi-res 有页数/像素上限；环境配置集中在 `partition/utils/config.py`。
- 可预期错误使用 `UnsupportedFileFormatError`、`UnprocessableEntityError`、`ValueError`、`ImportError`、`DecompressedSizeExceededError`、`PageCountExceededError` 等；邮件附件只吞窄白名单 `EXPECTED_ATTACHMENT_ERRORS`，不把 `RuntimeError`（可能是 OOM 或坏管道）静默成成功。
- telemetry 在本地基线 README 中写明默认关闭、通过 `UNSTRUCTURED_TELEMETRY_ENABLED=true/1` opt-in，并受 `DO_NOT_TRACK`/`SCARF_NO_ANALYTICS` 影响；远程 `8c4592a` 已恢复默认行为，使用最新源码时必须重新核对隐私边界。
- PDF、OCR、hi-res、STT 和 embedding 可能把文档内容送入模型/外部服务；涉密输入需显式选择纯规则/本地路径，不能从“可选依赖”推导“无数据出境”。

## 12. 测试、质量门禁与可观察范围

当前核对未执行测试（遵守只读归档与禁止启动/构建约束），以下是从源码和测试文件读取到的验证面：

- `pyproject.toml` 的 `pytest` testpaths 是 `test_unstructured` 与 `test_unstructured_ingest`；测试函数前缀包含 `test_`、`it_`、`they_`、`but_`、`and_`。
- `Makefile:test` 使用 `uv run --no-sync pytest -n auto test_unstructured --cov=unstructured`；覆盖率门槛 `fail_under = 90`。
- `Makefile:test-no-extras` 验证文本、邮件、HTML、XML 的最小安装边界；多个 `test-extra-*` 目标分别覆盖 csv、docx、epub、markdown、odt、PDF/image、pptx、pandoc、xlsx。
- `Makefile:check` 组合 `ruff check`、`ruff format --check` 与版本同步检查；`.pre-commit-config.yaml` 还执行 TOML/YAML/JSON/XML、尾空格和 Ruff 检查。
- `test_unstructured/partition/test_json.py`、`test_ndjson.py` 锁定 JSON 统一化、任意载荷、严格解析、回环、表格块与文件游标契约。
- `test_unstructured/partition/test_auto.py` 锁定自动类型路由、metadata 增强、策略透传、JSON/NDJSON 分流、缺损元素错误传播及多格式入口。
- `test_unstructured/test_safe_http.py` 锁定 IP/域名、重定向、凭证剥离、代理、环境变量与连接时校验。
- `test_unstructured/file_utils/test_model.py` 锁定 `FileType` 能力表、动态注册和 partitioner 命名派生。
- HTML/ontology 测试覆盖 DOM 到元素、元素到 ontology、空/坏父节点、表格、图片和 GHSA XSS 输出净化。
- `test_unstructured_ingest/` 以各连接器和 expected-structured-output 快照覆盖外部数据源；这部分不等于核心包的单机 API。
- `.github/workflows/partition-benchmark.yaml` 对 `partition()` 做 rolling median 基线比较：20 样本窗口、5 样本 warm-up、30% 回归阈值；主分支记录 S3 历史，PR 主要做只读比较。

测试文件数量和契约已核对，但未运行结果不可写成“通过”。

## 13. 风险、备注与未确认项

1. **版本漂移**：工作树是 0.25.1，远程已到 0.26.3；最新的 file-like 字符集回退、懒 chunking、PDF 内容流防护、HTML 性能修复和 telemetry 语义不能直接用于本地基线裁决。
2. **外部依赖面大**：`all-docs`/`ingest` 会引入重量级 Python 与系统依赖；部署时应按格式裁剪 extras，并把 `libmagic`、`poppler`、`tesseract`、`libreoffice`、`pandoc` 的可用性纳入诊断。
3. **JSON 形状歧义不可完全消除**：客户数据若恰好形如 `{"type":"Title","text":"x"}` 的元素数组，会被识别为 Unstructured 元素并 rehydrate；这是当前契约明确保留的限制。
4. **任意 JSON 输出是平面 `Text`**：当前没有 JSONPath、字段级 metadata 或结构感知 walker；`elements_from_arbitrary_value()` 是未来可替换的 swap point。
5. **`FileType` 动态注册改写 Enum 内部成员**：扩展能力强，但全局注册状态、模块导入顺序和测试隔离需要谨慎治理。
6. **metadata 可扩展但类型边界较软**：ad-hoc 字段利于演进，却增加 schema 漂移与下游消费不一致风险；跨系统传输应以 `to_dict()` 实际形状为准。
7. **deterministic ID 不是脱敏**：hash 输入包含文件名和正文，跨系统共享时可能被枚举。
8. **URL 安全逃生门与模型增强**：`allow_private`、`UNSTRUCTURED_ALLOW_PRIVATE_URL`、hi-res/OCR/STT 都是高权限/高数据流量选项，应在上层调用边界显式审计。
9. **API 客户端异常与重试需单独治理**：`partition_via_api()` 依赖 `unstructured-client` 的 retry 配置，批量函数使用 `requests.post`；两条远程路径的超时、凭证和错误模型并不完全统一。
10. **当前没有代码地图索引**：专属 `system_engineering_toolkit` 的 `codegraph_explore` 已按要求调用，但目标仓库没有 `.codegraph/`，因此不能把其他仓库的代码地图结果当作本仓证据；本档案结论来自目标仓库实际文件、测试、Git 和独立远程快照。

## 14. 旧细探吸收/未吸收裁决

当前核对已完整读取 `细探-unstructured.md`，并以本地 Git 基线源码、测试和现有架构文档逐项对照。
`细探-unstructured.md` **保留不删除**，仅作为历史研究材料；后续维护只更新本文件，避免形成
第二个架构事实源。

### 已吸收

| 旧细探主题 | 裁决 | 本文件落点 |
|---|---|---|
| 输入边界、四级文件类型识别、JSON/NDJSON 消歧 | 吸收；保留信号优先级、1 MiB 限制、严格解析和 file-like 游标复用 | 第 2、4 节 |
| `FileType` 能力表与 `_PartitionerLoader` | 吸收；保留依赖门禁、extra 提示、懒加载和动态注册边界 | 第 4 节 |
| `Element`/`ElementMetadata`、确定性 ID、`orig_elements` | 吸收；补充数据源、坐标、层次、邮件/音频和逐属性模型溯源 | 第 5 节 |
| 两阶段 chunking 与 `TableChunk` 重建协议 | 吸收；补充硬/软阈值、overlap、字段合并和失败回退语义 | 第 7 节 |
| arbitrary JSON、rehydrate、NDJSON 一行一元素 | 吸收；保留形状判别、确定性 pretty-print 和错误包装 | 第 6 节 |
| HTML v1/v2、Ontology 映射与 GHSA XSS 净化 | 吸收；明确这是输出端安全边界 | 第 8 节 |
| PDF/Image 依赖感知策略、OCR/STT/embedding 提供者 | 吸收；补充回退链和“核心无提示词、模型是可选提供者”边界 | 第 9 节 |
| `safe_http`、凭证剥离、代理禁用、尺寸限制、窄异常白名单 | 吸收；补充 IDNA、IPv4 派生地址和全解析结果校验 | 第 11 节 |
| 测试目录、Make/Ruff/覆盖率和 benchmark 观察面 | 吸收为“已读未执行”；没有把测试存在写成测试通过 | 第 12 节 |
| 版本漂移、可选依赖膨胀、deterministic ID 非脱敏、远程快照边界 | 吸收为风险/复核项 | 第 1、13 节 |

### 未吸收或降级为旁线材料

| 旧细探内容 | 裁决与原因 |
|---|---|
| “100% 可确定”、格式数量、目录文件行数等绝对化或易漂移表述 | 不按原文绝对化；只保留源码可验证的识别规则、职责和当前盘点结果。行数/数量不是稳定架构契约。 |
| 对底座的十条“可借鉴点” | 不作为 `unstructured` 已实现能力；仅在第 19 节结论中提炼为边界设计，避免把外部底座建议反写成项目事实。 |
| README 商业推广、商业化入口描述 | 不属于本地 Python 内核架构，未写入事实结论。 |
| 历史提交标题、目录命名寓意及未在当前源码/测试中闭合的推测 | 仅保留能解释版本/风险边界的部分；其余不进入权威架构。 |
| 旧细探中关于后续底座直接套用、复制完整 extras 或模型能力的建议 | 不吸收为实施承诺；第 9、13、19 节明确“只借鉴边界，不照搬实现”。 |

## 15. 后续：真实调用链与失败契约

本节只记录当前核对沿源码继续下钻后确认的实现事实；`S0`/`S1`/`S2`/`S3` 验证等级定义见第 18 节。没有把“有测试”或“能导入”写成“运行通过”。

### 15.1 解析调用链：同步、一次性结果，没有任务句柄

```text
partition.auto.partition()
  → exactly_one(file/filename/url)
  → url: file_and_type_from_url() → safe_get() → BytesIO；本地输入：detect_filetype()
  → JSON/NDJSON/PDF/Image/EMPTY 特判
  → _PartitionerLoader.get(FileType)
       → is_partitionable → dependency_exists() → importlib.import_module()
  → partitioner（装饰器链：metadata → chunking → partitioner body）
  → list[Element]
  → augment_metadata()
```

证据是 `partition/auto.py:151-183, 287-294`、`partition/api.py:79-137` 和 `file_utils/model.py`。入口同步返回 `list[Element]`，源码没有 `task_id`、队列、持久化状态、进度事件或取消令牌；`requires_dependencies()` 中的 `async` wrapper 只是给被装饰函数做依赖检查，不是异步解析调度。因此“任务生命周期”在核心库内等同于一次 Python 调用栈：调用开始 → 读取/转换/模型推理 → 返回或抛异常。宿主若需要排队、超时、重试、取消、租约或崩溃恢复，必须在库外包裹 worker/进程边界。

### 15.2 分块调用链：惰性输入，列表输出，存在明确的信息丢失点

`chunk_elements()`/`chunk_by_title()` 先构造并校验 `ChunkingOptions`，再执行 `PreChunker.iter_pre_chunks()`；`by_title` 额外经过 `PreChunkCombiner`，最终由 `PreChunk.iter_chunks()` 分派文本 `_Chunker` 或表格 `_TableChunker`（`chunking/basic.py:94-120`、`title.py:101-127`、`base.py:702-720`）。输入可以是任意 iterable，但公共入口立即返回列表，不提供核心级取消或背压。

- `ChunkingOptions._validate()` 在执行前拒绝互斥窗口、缺 tokenizer、非正硬上限、非法 overlap 和 `skip_table_chunking/isolate_table` 冲突；token 模式首次计数时才懒加载 `tiktoken`，导入/模型名错误会在迭代中失败。
- `PreChunker` 的设计文档明确写着 “CheckBox elements are dropped”（`base.py:428-447`）；实际循环把它带入 pre-chunk，但 `Element.text` 默认空字符串（`documents/elements.py:727,753-755`），最终 `_Chunker` 不会为它发出独立 chunk，只可能随 `orig_elements` 保留。这是 chunking 后的 IR 语义损失，不能把“返回成功”当作无损转换。
- `Table`/`TableChunk` 默认独占 pre-chunk；`text_as_html` 解析遇到 `ParserError`/`ValueError` 时只告警并回退纯文本表格切分（`base.py:1028-1040`）。因此表格局部降级可成功，但 HTML 结构可能丢失；中途异常仍没有部分结果回传契约。
- `include_orig_elements=True` 默认把原始元素引用放入 chunk metadata，序列化时才压缩成 base64；超大/递归元数据会放大内存与载荷，解压端受 200 MB 上限保护，但生成端没有同等总大小门禁。

### 15.3 Provider 边界：统一接口，非统一运行时语义

`embed/__init__.py:11-19` 只维护 provider 名称到 encoder 类的映射；核心 partition 不自动调用 embedding。`BaseEmbeddingEncoder`（`embed/interfaces.py:14-39`）要求 `initialize()`、维度、单位向量、文档和查询五个接口，但各实现的生命周期并不一致：

| provider/入口 | 实际外部边界与批量行为 | 超时/重试/资源事实 | 失败/验证结论 |
|---|---|---|---|
| `langchain-openai` | 每次 `embed_query`/`embed_documents` 都 `get_client()`；一次批量文档调用 | 本地没有显式 timeout/retry/close | 外部 SDK 异常原样上抛；S0 |
| `langchain-huggingface` | 本地 `HuggingFaceEmbeddings`，默认 `device=cpu`、不归一化 | 每次操作构造 client，模型缓存/释放交给 SDK；无取消接口 | 源码类未实现抽象 `initialize()`，按 ABC 规则实例化可失败；需运行确认，S0 |
| `langchain-aws-bedrock` | 每次操作新建 `boto3.client`，凭证来自 `SecretStr` | 无显式 timeout/retry/close；连接由 boto3 管理 | 同样未实现 `initialize()`，且 `__post_init__` 调用它；provider 可用性未运行验证，S0 |
| `langchain-vertexai` | 每次操作新建 Vertex client；先写 `/tmp/google-vertex-app-credentials.json` 并设置全局 `GOOGLE_APPLICATION_CREDENTIALS` | 临时凭证文件没有 finally 删除；环境变量是进程全局突变 | 崩溃/异常可能留下凭证文件，S0 |
| `voyageai` | 先调用 `tokenize()`，按模型 token 上限和最多 1000 条分批；`list(_build_batches(...))` 会先物化全部批次 | 没有本地 timeout/retry；任一批失败则整个调用失败 | 前面批次的 embedding 在最终全部成功前不会写回元素，S0 |
| `mixedbread-ai` | 每批 128 条，`MAX_RETRIES=3`、`TIMEOUT=60` 秒，逐批同步调用 | 只有该 SDK 请求选项显式给出重试/超时；无 cancel/close | 远端失败原样传播；S0 |
| `octoai` | 通过 OpenAI SDK，但 `embed_documents()` 对每个元素逐一 query，非批量 | 无本地 timeout/retry；失败位置不可从返回值获知 | 吞吐和失败放大风险，S0 |

所有 encoder 都把 `element.embeddings` 写回原对象；这是原地突变而非新 IR。Embedding 维度和单位向量属性通过额外的示例 embedding 调用推断（可能是本地模型或远端 provider，如 `get_exemplary_embedding()`），不是静态配置验证。未配置 key、缺 optional extra、模型拒绝、网络断开和配额耗尽均没有统一错误码或统一重试语义。

### 15.4 STT provider：白名单 + 进程缓存 + 单实例串行锁

`SpeechToTextAgent.get_instance()`（`partition/utils/speech_to_text/speech_to_text_interface.py:41-88`）只允许白名单模块，按完整类名使用 `lru_cache(maxsize=STT_AGENT_CACHE_SIZE)`；构造失败包装为 `RuntimeError`。Whisper（`whisper_stt.py:14-85`）在构造时加载模型，按实例锁串行化 `transcribe()`，配置在首次构造时冻结；模型没有 unload/shutdown。`partition_audio()` 对 file-like 输入先复制到 `NamedTemporaryFile(delete=False)`，在 STT 返回、抛错或构造失败时 `finally` 删除临时文件（`audio.py:74-90`），但模型下载、GPU 内存和第三方 ffmpeg 进程不在核心生命周期控制内。chunking 后音频段起止时间按 `DROP` 丢弃，时间轴必须在未分块元素上消费。

## 16. 任务、超时、取消与崩溃的资源生命周期

| 资源/节点 | 创建与持有 | 正常/业务失败清理 | 超时/取消/宿主崩溃边界 | 残留与验证 |
|---|---|---|---|---|
| 输入路径/调用方 file-like | `partition()`、各格式 partitioner 读取；路径通常由 `with open` 持有，调用方传入的 file 不由库关闭 | 路径句柄由上下文关闭；file-like 所有权仍在调用方；部分检测会 seek 回 0 | 没有 signal/cancel handler；调用方必须在 worker 外层关闭 | S0；未做进程级泄漏实测 |
| `safe_get()` HTTP session | 每次调用新建 `requests.Session`，手动跟随最多 10 跳 | `finally: session.close()`（`safe_http.py:389-416`） | 连接/读取默认 `(10,300)`；requests 异常向上传播；无主动取消，线程阻塞只能由宿主终止 | S1 有默认 timeout/重定向测试；无真实网络 S3 |
| URL 下载缓冲 | `BytesIO(response.content)` 一次性载入内存 | 随函数返回释放引用 | 读超时有边界，但响应体大小没有本地总字节上限；进程崩溃由 OS 回收内存 | S0 |
| Office/Pandoc 转换 | `TemporaryDirectory()` + `subprocess.run(soffice)` 或 pypandoc | 临时目录上下文清理；转换结果失败只记录错误（`common.py:256-332`） | `wait_for_soffice_ready_time_out` 只限制“等待 soffice 可用”的重试循环；`subprocess.run` 本身无 timeout、无进程组 kill，不能证明取消/崩溃后子进程无残留 | S0；只有 readiness 单测源码 S1 |
| PDF/OCR/图片渲染 | `TemporaryDirectory()` 保存页图；`PDF_RENDER_MAX_PIXELS_PER_PAGE` 和页数/模型限制在 provider 侧 | 上下文正常退出清临时页图；输出图片目录是调用方指定的持久制品 | 模型/转换器崩溃没有统一回滚；宿主强杀时不保证临时目录和 GPU/子进程清理 | S0；未运行 hi-res/OCR |
| 提取图片输出 | `save_elements()` 创建 `output_dir_path`，按元素写 `figure-*.jpg`/`table-*.jpg` 或写 base64 | 已写文件不会因后续元素失败而回滚；单张 `ValueError/IOError` 只告警跳过 | 取消/崩溃可能留下部分制品；输出目录不由函数删除 | S0；应按文件清单核验残留 |
| `orig_elements` | chunk 内存引用；序列化时 JSON→zlib→base64 | Python 引用释放由 GC；反序列化设 200 MB 解压上限 | 生成端无超大载荷取消；坏压缩数据抛异常，不恢复部分对象 | S0；staging 单测源码 S1 |
| embedding client/model | provider `get_client()` 多数每次调用创建；HF/Whisper 可能持有本地模型 | 没有统一 `close()`/`unload()`；SDK 自行管理连接/缓存 | 除 Mixedbread 外没有库级 timeout/retry；没有 cancel；进程崩溃由宿主回收 | S0；所有外部 provider S3 未验证 |
| 评估任务 executor | `metrics/evaluate.py:148-199` 默认 `ProcessPoolExecutor`，`with executor` 包围 `executor.map` | 正常/单文档异常后 context manager shutdown；异常文档被记录并从结果中省略 | 没有取消接口/每文档 timeout；worker 崩溃可能使 `map`/pool 直接失败；`except Exception` 不覆盖 `KeyboardInterrupt` | S0；没有执行 metrics |

补充：`partition_multiple_via_api()`（`partition/api.py:232-341`）与单文件 SDK 路径不是同一可靠性契约。批量路径直接 `requests.post()`，没有 timeout、retry 或 `Session` finally；`filenames` 与 `files` 都为空时 `response` 未赋值，随后会触发 `UnboundLocalError`。单文件路径的 SDK retry 默认常量为首间隔 3000 秒、最大间隔 720000 秒、最大 elapsed 1800000 秒；这是重试预算，不是用户可感知的总任务 deadline。API 客户端两条路径均没有取消令牌、幂等键或服务端任务状态读取。

## 17. 失败矩阵与降级语义

| 场景 | 代码行为 | 是否保留部分结果 | 上层必须做的事 |
|---|---|---|---|
| 输入缺失/多源、空参数 | `exactly_one()` 抛 `ValueError`；EMPTY 类型返回 `[]` | 否；EMPTY 是合法空结果 | 将参数错误与“空文档”区分 |
| 未知/不可分区类型 | `UNK/ZIP/EMPTY` 能识别但不可 partition，loader 抛 `UnsupportedFileFormatError` 或返回空 | 否/空结果 | 记录 FileType 与调用参数 |
| optional dependency 缺失 | loader/decorator 在调用前抛 `ImportError`，含 extra 安装提示 | 否 | 不把缺能力当输入坏；按格式安装或选降级策略 |
| PDF 文本提取异常 | `partition_pdf()` 捕获 `Exception`，记录并继续走策略判定 | 之前提取的临时元素不返回；后续 fast/hi-res/OCR 可能成功 | 记录最终采用的 strategy；不要仅凭无异常判断高保真 |
| hi-res/OCR 依赖缺失 | `determine_pdf_or_image_strategy()` 警告并回退；三者不可用且文本不可提取时 `ValueError` | 回退路径的元素可返回，模型/坐标能力可能丢失 | 将 fallback 当结果元数据审计 |
| 表格 HTML 坏 | `ParserError/ValueError` 告警，回退纯文本表格切分 | 文本保留，HTML 结构可能丢 | 检查 `text_as_html`/`table_extraction_method` |
| JSON 形状像 Element 但 metadata 损坏 | rehydrate 错误包装为 `ValueError` | 否；不静默转 arbitrary | 记录输入载荷，不重试同一坏载荷 |
| `orig_elements` 压缩数据坏/超限 | 抛 `zlib.error` 或 `DecompressedSizeExceededError`；JSON 分区层可包装 | 否 | 限制输入大小并拒绝递归载荷 |
| URL DNS/SSRF/重定向 | `UnsafeURLError` 快失败；每跳校验，跨源剥离凭证 | 否 | 只在受控场景显式启用 `allow_private`，不要扩大 catch |
| URL 连接/读取超时 | `safe_get()` 默认 `(10,300)`，异常向上 | 否 | 由 worker deadline 终止上层调用；注意 `auto.partition` docstring 的“None=无限”与实际 safe_get 默认不一致 |
| Office/Pandoc/ffmpeg/模型崩溃 | 依格式抛 `FileNotFoundError`/`RuntimeError`/第三方异常；部分路径仅记录转换失败 | 可能有部分输出或临时文件 | 进程隔离、进程组回收、输出目录清单核验 |
| embedding provider 超时/配额/断线 | 各 SDK 原样异常；仅 Mixedbread 显式 60 秒/3 次重试 | 取决于 provider；无统一 checkpoint | 上层按 provider 做 deadline、幂等和重试，禁止假设统一语义 |
| 主动取消/KeyboardInterrupt | 核心无取消协议；无全局 signal handler；`except Exception` 不捕获 `KeyboardInterrupt` | context manager/finally 覆盖的资源通常清理，外部模型/子进程不保证 | 在独立进程中取消并 kill process group，随后检查临时目录、端口、GPU/子进程 |
| 宿主崩溃/强杀 | Python finally 不保证执行；OS 回收内存，文件/子进程/外部制品可能残留 | 不可保证 | 启动前登记工作目录/子进程，重启后扫描并清理或标记 orphan |
| metrics 单文档错误 | `_try_process_document()` 记录错误并返回 None，聚合时静默省略失败文档 | 其他文档保留，但总数减少 | 必须对账输入文件数、成功数、失败数；不能只看聚合表 |

## 18. 验证等级、已证与未证

| 等级 | 含义 | 当前核对证据/当前状态 |
|---|---|---|
| `S0 源码事实` | 直接由本地基线源码、配置或 Git 得到，未运行 | 当前核对解析链、元素/分块、provider、temp/session、无 task/cancel、失败矩阵均属此级 |
| `S1 测试存在` | 测试源码明确断言行为，但当前核对没有执行 | `test_safe_http.py` 的默认 timeout/显式 timeout、`test_auto.py` 的 request_timeout 透传、`test_api.py` 的 retry config、`test_common.py` 的 soffice readiness timeout；测试存在不等于通过 |
| `S2 当前核对真实执行` | 在本地基线执行命令并记录退出码、测试数、资源清理结果 | 当前核对遵守归档只读约束，未安装依赖、未启动服务、未运行测试；无 S2 结论 |
| `S3 外部依赖/服务实测` | 真实调用 OCR、布局模型、STT、embedding provider、远程 API，并核验外部效果 | 全部未验证；API CI 测试有 `skipif`（非 CI/main 跳过），不能算 S3 |

当前核对可确认的“实现级”结论：`safe_get()` 有明确 session finally；音频 file-like 临时文件有 finally 删除；Office/PDF 临时目录依赖上下文；`partition_multiple_via_api()` 缺少 deadline/retry/空输入门禁；核心没有任务状态与取消模型；provider 的超时/重试和资源释放不统一；`HuggingFaceEmbeddingEncoder` 与 `BedrockEmbeddingEncoder` 的抽象 `initialize()` 缺口需要一次隔离环境运行确认。以上没有被包装成已通过的运行结果。

后续若要提升到 S2/S3，验收命令必须至少记录：实际 Python/依赖版本、命令退出码、输入/输出元素数、采用的 strategy/provider、失败异常类型、HTTP 重试耗时、临时目录与子进程清单、输出制品清单及取消/强杀后的残留扫描；不能用日志中的“success”、skip、历史 CI 或子代理回信替代。

## 19. 架构结论

`unstructured` 的核心价值不是某一个格式解析器，而是三条收口边界：

1. **声明式路由边界**：`FileType` 把类型、依赖、extra、MIME、扩展名和实现路径放在一起，`detect_filetype()` 与 `_PartitionerLoader` 共同完成可审计的能力选择和懒加载。
2. **统一 IR 边界**：各格式最终进入 `Element + ElementMetadata`；JSON/NDJSON 既能 rehydrate 已有元素，也能把任意结构安全地降级成确定性 `Text`，chunking 和 staging 围绕同一 IR 工作。
3. **安全与资源边界**：`safe_http`、HTML 输出净化、严格 JSON、解压/页数/像素上限和窄异常白名单把不可信输入限制在明确范围内，并保留可预期错误的可观测性。

对文档解析与 IR 方向可吸收的是“格式识别 → 能力注册 → 可选提供者 → 统一元素契约 → 可重建分块 → 有界序列化”的边界设计；不应直接照搬其完整 extras、外部 API 或模型能力。后续若继续研究，优先沿 `partition()` → `detect_filetype()` → `FileType`/`_PartitionerLoader` → `ElementMetadata` → `chunking` 追后续调用链，并在独立远程快照中复核 0.26.x 的新增安全与流式行为。

## 20. 当前 checkout 快速证据索引

| 事实 | file:line |
|---|---|
| 自动分区入口、参数归一化 | `unstructured/partition/auto.py:26-321` |
| 动态 partitioner loader | `unstructured/partition/auto.py:321-` |
| 文件类型检测四级策略 | `unstructured/file_utils/filetype.py:231-275` |
| PDF/Image 策略判定 | `unstructured/partition/strategies.py` |
| DOCX options、页码、表格 | `unstructured/partition/docx.py:186-370` |
| PPTX options、slide notes、图片 | `unstructured/partition/pptx.py:329-500` |
| 图片 OCR/布局策略 | `unstructured/partition/image.py:16-111` |
| OCR provider interface | `unstructured/partition/utils/ocr_models/ocr_interface.py:24-` |
| 元素元数据字段/合并策略 | `unstructured/documents/elements.py:150-560` |
| Table ontology HTML 清洗 | `unstructured/documents/ontology.py:331-339` |
| Table/TableChunk IR 类型 | `unstructured/documents/elements.py:1001-1010` |
| chunking decorator dispatch | `unstructured/chunking/__init__.py`、`dispatch.py` |
| 基础 chunk consolidation | `unstructured/chunking/base.py:840-970` |
| by_title section boundaries | `unstructured/chunking/title.py:144-260` |
| CLI argparse 入口 | `unstructured/cli.py:1-90` |
| REST API 适配 | `unstructured/partition/api.py` |
| URL 安全请求 | `unstructured/file_utils/safe_http.py` |
| 元素 JSON/NDJSON 序列化 | `unstructured/staging/` |
| 依赖/格式诊断 | `unstructured/doctor.py:224-` |
| strategy 回归 | `test_unstructured/partition/test_strategies.py` |
| safe HTTP 回归 | `test_unstructured/file_utils/test_safe_http.py` |
| metadata 回归 | `test_unstructured/partition/common/test_metadata.py` |
| chunk dispatch 回归 | `test_unstructured/chunking/test_dispatch.py` |
| API retry/config 回归 | `test_unstructured/partition/test_api.py` |

## 21. 交付与未验证声明

- 本轮 MCP `project_context` 返回项目根 `/Users/hekunhua/Documents/Agent/PHP/华世王镞_v3`，不是 unstructured；`codeexplore` 同样使用错误代码地图并返回错绑错误。因此 MCP 结果没有被写入本项目事实。
- 当前 checkout HEAD `104b585d`，分支 `main`，受跟踪文件约 1319；工作树保留未跟踪 `.codegraph/` 和源码侧 `ARCHITECTURE.md`，没有删除或改写它们。
- 平台唯一写入目标是本文件；本次不修改 unstructured 源码、测试、依赖、锁文件或远程仓库。
- 运行态仍未验证：本地依赖安装、所有格式真实样本、OCR/layout/STT 模型、API endpoint、并发吞吐、强杀清理、远程 provider、Windows Office/Pandoc/ffmpeg 和安全扫描。
- 文档可作为静态架构基线，不代表 `partition()`、CLI 或远程 API 当前可直接运行；任何“通过”结论都必须追加实际命令、退出码、环境指纹和输入/输出对账。
- 建议下一步只跑定向测试 `test_safe_http.py`、`test_strategies.py`、`test_dispatch.py` 和一个无外部模型的 DOCX/HTML fixture；模型、网络和 Office 测试必须单独隔离并使用端口 4780。

本文件至此为 unstructured 的唯一架构文档，后续只增量修订本文件并保留版本、证据等级和未验证边界。

## 22. 代码地图现状复核（2026-08-22）

第 13 节的“当前没有代码地图索引”属于早期审计记录，现已过期。当前目标根 `/Users/hekunhua/Documents/Agent/github 源码参考/20_文档解析与IR/2026_06_25_document_json_unification/unstructured` 存在独立 `.codegraph/`；在该根执行 `codegraph status` 退出码为 0，返回 321 files、6,918 nodes、17,842 edges。此前错绑 MCP 的结果仍不采纳；CodeGraph 也只证明索引可用，不证明运行态或外部 provider 已验证。

审计结束。
