# PaddleOCR 架构档案

## 1. 项目身份与证据边界

- **项目**：PaddleOCR
- **本地根目录**：`/Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/20_vision_ocr_detection/PaddleOCR`
- **远程仓库**：`https://github.com/PaddlePaddle/PaddleOCR.git`
- **许可证**：Apache License 2.0；子组件可能另有许可证，详见各自目录。
- **本次基线**：分支 `main`，提交 `2661c7c0ef5c613e8f93c6e93b2e052399f0f854`。
- **证据范围**：直接读取本仓库 `README.md`、`细探-PaddleOCR.md`、`pyproject.toml`、`requirements.txt`、入口/核心实现、MCP 服务、API SDK、测试与发布说明；并检查 Git 远程版本。
- **代码地图**：目标仓库项目本地 `.codegraph/` 已存在且索引最新；`codegraph status` 显示 1,160 files、14,850 nodes、33,164 edges、42.61 MB、node:sqlite WAL（Python 593、YAML 240、C++ 105、TypeScript 90 等）。本次使用项目本地 CodeGraph 做符号辅助，不经过 MCP。
- **细探保留**：`细探-PaddleOCR.md` 是既有细粒度只读探索，本档案只做权威收口，不删除或改写它。

## 2. 项目定位

PaddleOCR 是 PaddlePaddle 生态的多语言 OCR 与 Document AI 工具集，负责把图像/PDF/办公文档转换为文本、坐标、版面结构以及 LLM 可消费的 Markdown/JSON。当前仓库同时维护两条实现线：

1. **v3.x SDK 线**：`paddleocr/`，以 PaddleX pipeline 为外部推理内核，本仓库负责公共包装、参数映射、CLI、结果/API 客户端和文档转换。
2. **v2.x/传统训练推理线**：`ppocr/`、`ppstructure/`、`tools/`、`configs/`，包含模型训练、配置驱动推理、版面/表格/KIE 等历史实现。

外围出口包括 `mcp_server/`（FastMCP 服务）、`api_sdk/`（Go/TypeScript/Python API SDK 相关材料）、`paddleocr-js/`（浏览器 SDK）、`langchain-paddleocr/`、`deploy/`、`test_tipc/` 和 `benchmark/`。

## 3. 总体架构

```text
用户/应用
  ├─ Python API / CLI: paddleocr
  ├─ 官方云 API SDK: PaddleOCRClient / AsyncPaddleOCRClient
  ├─ MCP: paddleocr_mcp（stdio 或 streamable HTTP）
  ├─ 浏览器/生态: paddleocr-js、langchain-paddleocr
  └─ 部署出口: deploy/、C++/服务化/容器
          │
          ▼
  v3.x paddleocr 薄封装
  ├─ _models/：模型级 wrapper
  ├─ _pipelines/：声明式 pipeline wrapper
  ├─ _api_client/：官方异步作业 API 客户端
  ├─ _doc2md/：DOCX/PPTX/XLSX 转 Markdown
  └─ _cli.py / __main__.py：命令行入口
          │  load_pipeline_config → 递归 merge → create_pipeline
          ▼
  外部 PaddleX / PaddlePaddle 推理内核

传统线：ppocr/ + ppstructure/ + tools/ + configs/
  训练/评估/旧版推理/版面解析/表格/KIE

MCP 线：选择模型 → InferenceFactory(provider) → Task → MCP tool
  local / aistudio / qianfan / self_hosted
```

### 3.1 v3.x pipeline 运行机制

`paddleocr/_pipelines/base.py:PaddleXPipelineWrapper` 是所有 v3 pipeline 的公共基类：

1. 接收 `paddlex_config` 和公共参数。
2. 通过 `load_pipeline_config()` 读取 PaddleX 内置配置、路径配置或直接使用配置对象。
3. 子类 `_get_paddlex_config_overrides()` 生成点路径对应的嵌套覆盖项。
4. `_merge_dicts()` 递归合并配置。
5. 通过 `create_pipeline(config=..., device=...)` 创建实际推理管线。
6. `DependencyError` 被统一转换为安装指导型 `RuntimeError`；`close()` 释放外部管线。

`paddleocr/__init__.py` 暴露模型级 wrapper（如 `TextDetection`、`TextRecognition`、`LayoutDetection`、`DocVLM`）和 pipeline 级 wrapper（如 `PaddleOCR`、`PPStructureV3`、`PaddleOCRVL`、`PPChatOCRv4Doc`、`PPDocTranslation`、`TableRecognitionPipelineV2`）。

典型 OCR 子管线为：

```text
DocPreprocessor（方向分类/扭曲矫正，可选）
  → TextDetection
  → TextLineOrientationClassification（可选）
  → TextRecognition
```

`PaddleOCR` 的语言、版本和新旧参数兼容逻辑位于其 pipeline 实现中；旧参数通过 `_DEPRECATED_PARAM_NAME_MAPPING` 迁移到 v3 参数。结果通常由 PaddleX 返回，封装层不重新实现模型算法。

### 3.2 传统 ppstructure 文档解析

`ppstructure/predict_system.py:StructureSystem` 是旧版过程式文档解析入口：图像方向 → 版面分析 → 按区域分派。`table` 区域进入 `TableSystem`，公式进入公式识别，其他区域以全图 OCR 后再按 bbox 交集过滤。`recovery_to_markdown.py` 将 `figure/title/table/equation/text` 等区域还原为 Markdown；`recovery_to_doc.py` 使用 `python-docx` 还原 Word，并处理双栏布局。

该线和 v3 pipeline 并存，不能把 `ppstructure/` 的配置、`tools/infer/` 的 CLI 或 `ppocr/` 的模型代码误认为 v3 SDK 的执行内核。

### 3.3 MCP 服务架构

`mcp_server/` 是独立 Python 包 `paddleocr_mcp`，入口为 `paddleocr_mcp.__main__:main`：

1. `_parse_args()` 读取 CLI 参数和 `PADDLEOCR_MCP_*` 环境变量。
2. `_validate_args()` 在启动前校验 provider 所需凭据/地址；参数错误退出码为 `2`。
3. `resolve_model()` 校验模型白名单和 provider 组合。
4. `create_inference()` 通过 `InferenceFactory` 选择 `(tool, provider)` 实现。
5. `inference.start()` 后由 `create_task()` 创建任务并注册 FastMCP 工具。
6. 默认 stdio；`--http` 时使用 `streamable-http`，默认绑定 `127.0.0.1:8000`。
7. `finally` 执行 `inference.stop()`；启动/运行异常退出码为 `1`。

支持的模型与工具映射（`mcp_server/paddleocr_mcp/selection.py`）：

| 模型标识（源码原文） | MCP 工具 | 可用 provider 约束 |
|---|---|---|
| `PP-OCRv5`、`PP-OCRv5-latin`、`PP-OCRv6` | `ocr` | `local`、`aistudio`、`self_hosted` |
| `PP-StructureV3` | `pp_structurev3` | `local`、`aistudio`、`qianfan`、`self_hosted` |
| `PaddleOCR-VL`、`PaddleOCR-VL-1.5`、`PaddleOCR-VL-1.6` | `paddleocr_vl` | `local`、`aistudio`、`qianfan`、`self_hosted` |

`Task._invoke_tool()` 统一处理 `input_data`、`output_mode`、`file_type`、`return_images`、`runtime_params`：输入适配器归一化并校验，推理层合并/校验运行参数，随后按结果类型格式化。`OCRTask` 的 simple 输出为文本并附置信度/行数，detailed 输出 JSON；文档解析任务返回文本与可选 `ImageContent` 混合内容。

provider 的边界：

- `local`：桥接本地 PaddleX/PaddleOCR 同步推理。
- `aistudio`：官方 API，token、单请求超时和轮询超时。
- `qianfan`：千帆 HTTP API，仅文档解析模型白名单。
- `self_hosted`：自建 HTTP 服务。

### 3.4 官方 API SDK

`paddleocr/_api_client/` 是独立的官方云 API 客户端层。`PaddleOCRClient` 和 `AsyncPaddleOCRClient` 都围绕异步作业模型工作：

```text
submit_url / submit_file
  → job_id
  → Poller 轮询状态
  → 获取 JSONL 结果
  → parse_ocr_result / parse_doc_parsing_result
  → OCRResult / DocParsingResult
```

同步客户端的公开能力包括 `ocr()`、`parse_document()`、`submit_ocr()`、`submit_document_parsing()`、`wait_ocr_result()`、`wait_document_parsing_result()`、`get_status()`、`get_batch_status()` 以及结果资源保存方法。认证默认从 `PADDLEOCR_ACCESS_TOKEN` 读取，也可显式传 `token`；服务地址可由 `PADDLEOCR_BASE_URL` 覆盖。

## 4. 数据模型与契约

本项目没有业务数据库、ORM 或迁移层；“数据模型”主要是内存 dataclass、字典 payload、外部 API JSON/JSONL 和 PaddleX 返回结果。

### 4.1 v3 pipeline 结果

PaddleX pipeline 返回以字典为主的结构化结果，常见 OCR 字段包括 `dt_polys`、`rec_texts`、`rec_polys`、`rec_boxes`；PP-StructureV3 还包含 `overall_ocr_res`、版面块、表格、公式和 Markdown/可视化资源。具体字段由外部 PaddleX pipeline 和各 pipeline wrapper 契约共同决定。

### 4.2 MCP 内部契约

`mcp_server/paddleocr_mcp/inference/types.py` 定义：

- `InferenceRequest`：`input_data: str`、可选 `file_type`、`runtime_params`。
- `TextLine`：`text`、`confidence`、`bbox`。
- `OCRResult`：`text`、`confidence`、`text_lines`。
- `DocParsingResult`：`markdown`、`pages`、`images_mapping`。

`Task` 严格检查 `OCRResult`/`DocParsingResult` 类型，类型不匹配抛出 `TypeError`，避免错误结果伪装成另一种工具输出。

### 4.3 官方 API SDK 模型

`paddleocr/_api_client/models.py` 用 `Model` 枚举和 dataclass 选项表达请求：`OCROptions`、`PPStructureV3Options`、`PaddleOCRVLOptions`。`to_payload()` 把 snake_case 字段转换成 camelCase，并把 `extra_options` 合并到 payload；VLM 选项对 `top_p`、`temperature`、`repetition_penalty`、像素范围做显式校验。

`paddleocr/_api_client/results.py` 定义 `Job`、`JobStatus`、`BatchStatus`、`OCRResult`、`DocParsingResult` 及页级对象，保留 `raw` 和 `data_info`，便于上层处理原始扩展字段。

错误契约位于 `paddleocr/_api_client/errors.py`，包括 `AuthError`、`InvalidRequestError`、`APIError`、`RateLimitError`、`ServiceUnavailableError`、`JobFailedError`、`RequestTimeoutError`、`PollTimeoutError`、`ResponseFormatError`、`ResultParseError`、`NetworkError`。

## 5. 对外入口与接口

### 5.1 Python 包与 CLI

- 包入口：`paddleocr/__init__.py`。
- CLI 脚本：`paddleocr = paddleocr.__main__:console_entry`（`pyproject.toml:63-64`）。
- CLI 实现：`paddleocr/__main__.py` → `paddleocr._cli.main`。
- v2 训练/评估/推理入口：`tools/train.py`、`tools/eval.py`、`tools/infer/*.py`、`train.sh`。
- 传统文档解析入口：`ppstructure/predict_system.py`。

### 5.2 Python SDK 主要公开符号

`paddleocr/__init__.py:17-67` 和 `:84-131` 导出模型 wrapper、pipeline wrapper、`PaddleOCRClient`/`AsyncPaddleOCRClient`、选项/结果错误类型、`doc2md_convert`、`doc2md_supported_formats`、`benchmark` 和 `__version__`。

### 5.3 官方云 API

`PaddleOCRClient` 的外部作业接口由 `paddleocr/_api_client/_http.py` 实现，测试证据表明默认主机为 `https://paddleocr.aistudio-app.com`，作业 API 路径为 `/api/v2/ocr/jobs`，状态路径为 `/api/v2/ocr/jobs/{job_id}`，批次状态路径为 `/api/v2/ocr/jobs/batch/{batch_id}`。输入支持远程 `file_url` 或本地 `file_path`，二者互斥且至少提供一个；支持 `page_ranges`、`batch_id` 和模型特定 options。

### 5.4 MCP 工具接口

MCP 工具由 `Task.register_tools()` 动态注册，工具描述从输入适配器、provider 和运行时参数白名单生成，不是静态重复维护。统一参数为：

- `input_data`：图像/PDF 输入，形式由 provider 决定；
- `output_mode`：`simple` 或 `detailed`；
- `file_type`：HTTP provider 无法推断时传 `image` 或 `pdf`；
- `return_images`：文档解析是否返回图片内容；
- `runtime_params`：JSON 对象形式的 pipeline 参数。

## 6. 依赖、配置与资源边界

### 6.1 根包依赖

`pyproject.toml:17` 要求 Python `>=3.8`。核心依赖为 `paddlex[ocr-core]>=3.7.0,<3.8.0`、`PyYAML>=6`、`requests`、`aiohttp>=3.8.0`、`typing-extensions>=4.12`。可选能力分为 `doc-parser`、`ie`、`trans`、`doc2md` 和 `all`。

根目录 `requirements.txt` 保留传统线依赖：`shapely`、`scikit-image`、`pyclipper`、`lmdb`、`numpy`、`opencv-python`、`opencv-contrib-python`、`Pillow`、`albumentations`、`albucore` 等。它不等同于 v3 包的完整依赖清单。

### 6.2 MCP 包依赖

`mcp_server/pyproject.toml` 声明 `paddleocr_mcp==0.8.5`，要求 Python `>=3.10`，依赖 `mcp>=1.5.0`、`fastmcp>=2.0.0`、`httpx`、`numpy`、`paddleocr>=3.7.0`、`pillow`、`puremagic` 等；`local`/`local-cpu` extra 再引入文档解析能力和 `paddlepaddle>=3.2.1`。

### 6.3 凭据、网络与模型资源

- 官方 API token：`PADDLEOCR_ACCESS_TOKEN`；MCP provider 使用 `PADDLEOCR_MCP_AISTUDIO_ACCESS_TOKEN`、`PADDLEOCR_MCP_QIANFAN_API_KEY` 等环境变量。
- MCP 默认 stdio；HTTP 默认只绑定 `127.0.0.1`，需要显式 `--http`。
- 本地模型权重可能自动从 PaddleOCR/PaddlePaddle 对象存储下载；离线环境应预取并通过配置/模型目录提供。
- OCR、合同、身份证、发票等输入可能含敏感信息；生产接入必须补充鉴权、日志脱敏、传输与落盘加密、保留期和访问审计。
- 推理和 VLM 对 CPU/GPU、内存/显存、磁盘和网络带宽有较高要求；资源密集型测试默认被 pytest 配置排除（`pyproject.toml:82-87`）。

## 7. 测试与质量门

测试目录按职责分为：

- `tests/api_client/`：请求路径、认证、HTTP 错误映射、选项 payload、结果解析、CLI 资源保存。
- `tests/pipelines/`：`test_ocr.py`、`test_pp_structurev3.py`、公式、表格、印章、文档预处理、VLM 等 pipeline 行为。
- `tests/models/`：模型 wrapper 级测试。
- `tests/ppocr/`：传统后处理/增强/公式模型测试。
- `tests/unit/`：例如 `_patch_layout_parsing.py` 的大坐标溢出和空 bbox 防护。
- `tests/security/`、`tests/tools/`：安全加载、命名、文档链接等辅助质量检查。
- `test_tipc/`：训练、推理、服务、量化、Paddle2ONNX、Lite/C++ 等 TIPC 矩阵测试。

测试实际覆盖了：

- `Model` 和 OCR/文档模型分类、默认 payload、camelCase 转换；
- 输入来源互斥和 job task 类型校验；
- API 401/400/429/500/503 映射到分层异常；
- 请求路径、认证头、`Client-Platform`、上传 body；
- OCR 与 PP-StructureV3 的参数转发、模型名选择；
- 大坐标 overlap 防 int32 溢出、空 bbox 兜底。

测试边界和风险：

- `pyproject.toml` 的 `addopts = "-m 'not resource_intensive'"` 默认跳过资源密集型测试；
- `tests/pipelines/` 依赖 PaddleX/模型资源，不能仅凭导入或轻量单测证明端到端推理；
- `TEST_REPORT.md` 是历史 `feature/api-sdk (PR #18049)` 的集成记录，不应替代当前提交上的重新验证；
- 本次架构建档未安装依赖、未启动服务、未构建，也未运行目标项目测试。

## 8. 版本与远程新鲜度

本地 `main` 的 HEAD 为 `2661c7c0ef5c613e8f93c6e93b2e052399f0f854`，提交主题为 `Update README (#18272)`；远程 `origin/main` 当前解析到同一提交，`git rev-list --left-right --count HEAD...origin/main` 为 `0 0`，因此本地没有落后远程的差异，不需要创建 `4780` 独立快照，也没有覆盖工作树。

工作树原有未跟踪文件：`细探-PaddleOCR.md`。本次只新增根目录 `ARCHITECTURE.md`，未触碰该细探或其他源码/依赖/测试/配置。

## 9. 可复用架构模式与不应照搬项

### 可复用

1. **薄封装 + 外部内核**：通过配置覆盖和 `create_pipeline` 解耦公共 API 与推理实现。
2. **能力/模型到 provider 的注册表**：`(tool, provider) → factory` 让任务逻辑复用在本地、官方云、第三方云和自建 HTTP 之间。
3. **输入契约归一化**：URL、本地路径、内容/base64 等输入先由 adapter 统一处理，再交给推理层。
4. **动态工具自描述**：根据 provider 和参数白名单生成 MCP 描述，降低手写契约漂移。
5. **同步内核的异步桥接**：`LocalSyncRunner` 复用同步推理，不强迫底层算法全面 async 化。
6. **作业型 API 的提交/轮询/解析分层**：将长任务、超时、状态和结果资源保存拆开。
7. **边界补丁隔离**：`_patch_layout_parsing.py` 用幂等 monkeypatch 隔离第三方 bug，并配套直接单测。

### 不应直接照搬

- `ppstructure/`/`tools/infer/` 中的 `sys.path` 全局拼接和 v2/v3 混合导入方式；
- 把外部 PaddleX 返回字典当作长期稳定数据库模型；
- 把模型权重、云端 token 或敏感 OCR 原文写入日志/仓库；
- 把 `TEST_REPORT.md` 的历史成功当作当前版本的运行证据；
- 在未锁定 `paddleocr`、`paddlex`、`paddlepaddle` 和模型权重版本前承诺跨环境可复现。

## 10. 风险清单

| 级别 | 风险 | 证据与影响 |
|---|---|---|
| 重要 | 外部内核版本耦合 | `pyproject.toml:49-55` 将根包锁在 `paddlex[ocr-core]>=3.7.0,<3.8.0`，核心行为不完全在本仓库内；升级需同步 PaddleX/PaddlePaddle/权重。 |
| 重要 | 两条版本线并存 | `paddleocr/` v3 薄封装与 `ppocr/`、`ppstructure/`、`tools/` v2 过程式实现的配置、入口和结果形态不同，集成时容易选错入口。 |
| 重要 | MCP 独立包的版本解析 | `mcp_server/pyproject.toml:14` 依赖已发布 `paddleocr>=3.7.0`，与本地源码动态版本/外部依赖组合有关，单独安装时必须确认解析到的版本。 |
| 重要 | 模型/文档资源重 | 本地推理和 VLM 依赖 GPU/CPU extra、模型下载和较大存储；默认跳过资源密集型测试可能隐藏部署环境问题。 |
| 重要 | API 结果与资源链路 | 官方 API 是异步作业 + JSONL + 预签名资源 URL；轮询超时、服务端失败、结果格式变化和资源下载鉴权都需要独立回归。 |
| 建议 | 安全与隐私 | MCP 虽默认 stdio/回环、凭据走环境变量并启用 `mask_error_details=True`，但业务接入仍需对敏感文档做授权、脱敏、加密和审计。 |
| 建议 | 许可证与模型权重 | 根代码是 Apache-2.0，但 `deploy/`、`benchmark/`、移动端和模型权重可能另有条款；发布前逐项核对。 |

## 11. 架构结论

PaddleOCR 当前是一个**多入口、多运行时、以 PaddleX 为 v3 推理内核的 OCR/文档解析生态仓库**，不是单一的 OCR Python 库。推荐理解顺序为：

1. 新应用优先从 `paddleocr/` v3 pipeline 或 `PaddleOCRClient` 开始；
2. 需要 Agent/MCP 接入时使用独立 `mcp_server/`，先选择模型/provider，再审查输入、凭据和资源策略；
3. 需要训练、旧版算法、细粒度配置或传统 KIE/表格实现时再进入 `ppocr/`、`ppstructure/`、`configs/`、`tools/`；
4. 需要生产部署时单独评估 `deploy/`、硬件后端、模型权重许可和端到端测试；
5. 任何升级先锁定 PaddleOCR/PaddleX/PaddlePaddle/权重的版本组合，并重新验证 API/MCP 的异步作业、资源下载、错误分层和安全边界。

**结论**：架构分层清晰，v3 pipeline、官方 API SDK 和 MCP provider 工厂具有较强复用价值；主要维护成本来自 v2/v3 并存、外部 PaddleX 内核、模型资源和多种部署/服务出口。当前本地代码与 `origin/main` 同步，档案基于当前工作树完成，未修改源码、依赖、测试、配置或既有细探。

## 12. 旧细探吸收收口（唯一事实源）

### 12.1 收口规则与范围

- 本档案是项目根唯一 `ARCHITECTURE.md`；后续架构事实只维护本文件。
- `细探-PaddleOCR.md` 已完整读取并作为输入逐项对照；**按用户要求保留，不删除、不改写**。它仍是历史细粒度研究记录，不与本档案并列为权威事实源。
- 当前核对只允许修改本文件；没有改源码、配置、依赖、测试、Git 元数据或旧细探。
- 旧细探的事实若与当前源码一致，收口到第 3—11 节；以下表格记录吸收裁决，避免“旧文档存在”被误认成“当前实现已验证”。

### 12.2 旧细探逐项对照与裁决

| 旧细探主题 | 当前源码证据/收口位置 | 裁决 | 需要保留的边界 |
|---|---|---|---|
| v3 `paddleocr/` 是 PaddleX 薄封装 | `paddleocr/_pipelines/base.py:18-21,54-109`；第 3.1 节 | **吸收** | `load_pipeline_config → _merge_dicts → create_pipeline` 的真实实现位于外部 PaddleX；本仓库不是推理内核。 |
| OCR 三段/四段推理顺序 | `paddleocr/_pipelines/ocr.py:179-237,247-300`；第 3.1 节 | **吸收但修正版本表述** | 旧细探以 PP-OCRv4 为重点；当前入口允许 `PP-OCRv3`—`PP-OCRv6`（`ocr.py:58-62`），且 `DocPreprocessor`、检测、行方向、识别均有开关，不应写成所有调用都固定启用。 |
| `ppstructure` 全图 OCR 后按 bbox 过滤 | `ppstructure/predict_system.py:StructureSystem`（旧线）；第 3.2 节 | **吸收** | 这是传统线事实，不能移植为 v3 `PPStructureV3` 的内部实现；v3 通过 PaddleX pipeline。 |
| Markdown/Word/Excel 恢复 | `ppstructure/recovery_to_markdown.py`、`recovery_to_doc.py`、`paddleocr/_doc2md/`；第 3.2/3.4/4 节 | **吸收** | Markdown、DOCX、表格 HTML/Excel 是不同转换链；转换产物和图片目录属于调用方负责的外部文件资源。 |
| MCP 四 provider 与模型选择 | `mcp_server/paddleocr_mcp/selection.py`、`inference/factory.py:32-67,164-200`；第 3.3 节 | **吸收** | provider 组合由注册表决定；未注册组合抛 `ValueError`，不能按模型名推断“任何 provider 都可用”。 |
| MCP 输入统一适配 | `mcp_server/.../inference/shared/input_contract.py:33-153`、`input_adapters.py:45-182`；第 13.1 节 | **吸收并补强** | 支持绝对路径、HTTP(S) URL、Base64、data URL；相对路径拒绝；本地 Base64 图像转 RGB/BGR contiguous array，PDF/AI Studio 输入使用临时文件。 |
| 官方 API 提交/轮询/JSONL | `_api_client/_http.py:34-206`、`_poller.py:44-152`、`_async_poller.py:36-86`；第 3.4/13.2 节 | **吸收** | 轮询默认 3s 起步、1.5 倍退避、15s 上限、600s 总等待；`done` 还必须有 `resultUrl.jsonUrl` 并成功解析 JSONL。 |
| 旧参数兼容 | `paddleocr/_pipelines/ocr.py:44-56,155-168`；第 3.1 节 | **吸收** | 新旧参数同时传入直接 `ValueError`；`lang/ocr_version` 与显式模型目录并用时是 warning+忽略，不是静默混合。 |
| monkeypatch 修复上游布局解析 | `paddleocr/_pipelines/_patch_layout_parsing.py`、`tests/unit/test_patch_layout_parsing.py`；第 9 节 | **吸收** | 仅说明边界补丁模式，不把单测当端到端证明；补丁须随 PaddleX 版本回归。 |
| 权重/许可证/隐私提醒 | 根 `LICENSE`、各组件 LICENSE/THIRD_PARTY、README；第 6/10 节 | **吸收** | README 的精度、速度、Star 和“领先”是声明/营销材料，不作为当前核对运行证据；代码 Apache-2.0 不自动覆盖模型权重和第三方组件条款。 |
| `skills/` agent 技能包 | 仓库 `skills/` 下各 `SKILL.md`；旧细探第 2.4/3 节 | **待核** | 已确认文件形态与触发元数据存在；未在当前核对验证安装器、环境变量注入和实际 agent 触发。 |
| HPD-Parsing/VL/JS/生态旁路线索 | `docs/`、`paddleocr-js/`、`deploy/`、`langchain-paddleocr/` | **待核/隔离** | 作为旁路线索保留，不混入当前 v3 OCR 主调用链；每条需要独立版本、依赖和运行证据。 |

## 13. 深度事实表

### 13.1 契约表：入口、输入、输出、失败与资源责任

| 契约入口 | 输入与前置 | 输出/状态 | 错误、超时、取消、幂等 | 资源责任与证据 |
|---|---|---|---|---|
| `PaddleOCR(...).predict()` / `predict_iter()` | `paddleocr/_pipelines/ocr.py:179-237`；模型名/目录或 `lang+ocr_version`；配置可来自默认、路径或对象 | 外部 PaddleX 迭代结果；MCP 本地适配器再读 `rec_texts/rec_scores/rec_boxes` | 非法版本/语言 `ValueError`；调用方没有统一取消契约；无作业幂等键 | 构造时创建 PaddleX pipeline；调用方应显式 `close()`，但 MCP local stop 当前只关 runner，见 14.1。 |
| `PPStructureV3.predict()` | `pp_structurev3.py:148-220,223-298`；大量 `use_*`、版面、表格、公式、印章参数 | 外部 PaddleX 结构结果；再适配为 `DocParsingResult` | 非法版本/语言 `ValueError`；资源密集；无统一取消/幂等 | 同上；模块级 `_apply_patches()` 在导入时执行，补丁是进程级副作用。 |
| `PaddleOCRClient.submit_*` | `_api_client/_core.py:38-43` 要求 URL/path 二选一；`_http.py:96-157` | `job_id: str` | 401/403→`AuthError`，400→`InvalidRequestError`，429→`RateLimitError`，503/504→`ServiceUnavailableError`；请求超时/断线分层 | `HTTPClient` 持有 `requests.Session`；文件句柄由 `with open` 关闭；需 `client.close()`。`batch_id` 只是提交字段，不等价于客户端幂等保证。 |
| `wait_*` / `Poller.poll_until_done()` | `_poller.py:59-86` 或 async 版本；job 状态必须是 pending/running/done/failed | JSONL → `OCRResult` 或 `DocParsingResult`；页级 raw/data_info 保留 | 未知状态/缺结果 URL/坏 JSONL→`ResponseFormatError/ResultParseError`；failed→`JobFailedError`；600s 默认→`PollTimeoutError`；没有显式 cancel API | 轮询只持有 HTTP client；取消依赖 async task 取消，源码未证明服务端作业被取消。 |
| MCP `Task._invoke_tool()` | `tasks/base.py:60-106`；`input_data/output_mode/file_type/return_images/runtime_params` | `OCRTask` 返回字符串或 JSON；文档任务返回 `TextContent/ImageContent` 列表 | 输入/运行参数校验失败；结果类型错误→`TypeError`；空结果返回 “No text/content detected”；异常由 FastMCP 边界屏蔽细节 | `InputAdapter.prepare()` 的临时文件上下文退出即删；结果图片若要落盘走独立原子写入，不由 Task 自动持久化。 |
| MCP `main()` | `mcp_server/paddleocr_mcp/__main__.py:144-181,222-274`；provider 凭据/HTTP 参数门禁 | stdio 默认；`--http` 为 streamable-http，127.0.0.1:8000 默认 | 参数错误/不支持组合→exit 2；启动/运行异常→exit 1；`mask_error_details=True`；finally stop | 进程退出进入 `finally` 调 `await inference.stop()`；宿主崩溃不由源码保证清理。 |
| `save_resource*()` | `_api_client/_resources.py:27-119`；目标目录/URL/overwrite | 本地文件路径列表 | URL/目标非法、重复文件、下载超时/断线/非 2xx；无跨资源事务回滚 | 使用同目录临时文件+`os.replace`/hard-link，finally 删除临时文件；多文件保存中途失败时前面已写文件不会自动回滚。 |

### 13.2 真实对接调用链表

| 链路 | 真实箭头（函数/输入输出） | 异常/状态转换 | 最终 owner |
|---|---|---|---|
| v3 本地 OCR | `PaddleOCR.__init__` → `PaddleXPipelineWrapper._get_merged_paddlex_config` → `_merge_dicts` → `_create_paddlex_pipeline` → `paddlex.create_pipeline` → `paddlex_pipeline.predict` → `PaddleOCR.predict` 返回 list | `DependencyError`→安装指导 `RuntimeError`；参数冲突/版本不合法→`ValueError` | PaddleX 持有模型与 pipeline；wrapper 只持有封装引用。证据：`paddleocr/_pipelines/base.py:54-109`、`ocr.py:97-173,194-237`。 |
| MCP 本地 OCR | `main._create_inference_from_args` → `InferenceFactory.create` → `OCRLocalInference.start` → `PaddleOCR`+`LocalSyncRunner` → `Task._invoke_tool` → `LOCAL_INPUT_ADAPTER.normalize/validate/prepare` → runner worker 调 `predict` → `_parse_result` → `OCRTask._format_result` → FastMCP tool | 未启动→`RuntimeError`；worker 异常回传 Future；参数非法在 predict 前拒绝；当前没有显式 request cancel | `Inference` 管 provider 生命周期；`PaddleOCR`/PaddleX 管模型；MCP Task 管输出形态。证据：`inference/ocr/local.py:53-131`、`tasks/base.py:60-106`。 |
| MCP AI Studio 文档 | `main` → `InferenceFactory` → `PPStructureV3AIStudioInference` → `AsyncPaddleOCRClient.parse_document` → `HTTPClient.submit_*` → `AsyncPoller.poll_until_done` → `fetch_jsonl` → `parse_doc_parsing_result` → `parse_aistudio_doc_parsing_result` → `DocParsingTask` | HTTP 错误映射为认证/资源不可用/执行失败/超时；状态失败和结果坏格式分别保留错误层次 | API client 持有异步 HTTP session；Task 不拥有外部 job。证据：`inference/pp_structurev3/aistudio.py:80-112`、`_async_poller.py:51-78`。 |
| MCP HTTP provider | `HTTPInputAdapter.prepare_http_file_field` → URL 原样或本地文件 Base64 → provider endpoint → `HTTPInferenceBase.predict` → `parse_*_result` → Task | HTTP 错误/JSON 不符由 HTTP base/parser 转换；`file_type` 只作为服务端无法推断时的提示/参数 | 远端服务拥有推理资源；客户端只持有请求响应。 |
| 官方资源落盘 | `DocParsingResult/OCRResult` 页资源 URL → `save_*_resources` → `save_resource` 校验 URL/目标 → `requests.get` → temp file → `os.replace`/link | 单个下载失败抛异常；已成功文件不回滚 | 本地目标目录由调用方持有；函数只保证单文件原子写入。 |

### 13.3 关键小节点明细

| 节点 | 前置/状态 | 读写对象与并发 | 失败分支/恢复 | 证据 |
|---|---|---|---|---|
| 配置合并 | 先取得内置/路径/对象配置；覆盖项由子类生成 | 只读配置对象，递归复制顶层并递归替换冲突键；无锁 | 配置/依赖异常在构造期暴露；恢复是修依赖/配置后重建 wrapper | `paddleocr/_pipelines/base.py:33-40,90-109` |
| 模型选择 | 显式模型优先；否则按 `lang/ocr_version` 选择 | 仅内存参数；显式模型与语言冲突不合并 | 无模型→`ValueError`；显式参数覆盖需人工确认 warning | `ocr.py:97-127`、`pp_structurev3.py:103-134` |
| 输入分类 | 空输入、URL、data URL、Base64、路径分类 | 绝对路径读文件；Base64 解码在内存完成 | 相对路径/不存在/非 image/pdf→`ValueError`；不会生成持久输入副本 | `input_contract.py:66-129` |
| 同步异步桥 | `LocalSyncRunner` 初始化事件循环、Queue、Thread | 单 worker 串行消费；结果通过 `Future` 回主 loop | worker 异常设到 Future；关闭放 sentinel 并 join；取消与 close 并发未形成完整契约 | `local_sync_runner.py:21-59` |
| 作业状态机 | `pending/running/done/failed` 是允许集合 | 每次 GET 读取远端状态；退避睡眠 | unknown state/缺 URL/failed/超时分别报错；无服务端 cancel | `_core.py:119-192`、`_poller.py:59-86` |
| 结果格式化 | 结果必须是预期 dataclass；空文本特殊输出 | OCR 计算平均置信度；doc Markdown 按 `<img src>` 切成 MCP content | 类型错→`TypeError`；图片 payload 无法解析时保留原 img 文本；不是事务 | `tasks/ocr.py:31-55`、`tasks/doc_parsing.py:27-105` |
| 资源落盘 | URL 必须 http(s)，目录/覆盖策略合法 | 每个资源独立临时文件；同一目标通过 link/replace 争抢 | 重复目标/下载失败/写入失败清理临时文件；批量已写项不回滚 | `_resources.py:27-60,63-119,153-175` |

## 14. 资源生命周期与失败语义

### 14.1 生命周期表

| 资源 | 创建 | 正常释放 | 业务失败/超时/取消 | 崩溃/残留核验 |
|---|---|---|---|---|
| PaddleX pipeline/模型上下文 | `PaddleXPipelineWrapper.__init__` 调 `create_pipeline` | wrapper `close()` 调 `paddlex_pipeline.close()`（`base.py:79-80`） | 构造失败由异常传播；源码未展示统一 cancel；调用方须显式 close | 进程崩溃由 OS/运行时接管；当前核对未做显存/句柄现场核验。MCP local `stop()` 未调用 wrapper close，是重要缺口。 |
| `LocalSyncRunner` 线程、Queue、Future | `local_sync_runner.py:21-29` | sentinel + `run_in_executor(thread.join)`（41-45） | worker 异常传 Future；取消中的 Future、排队任务和 close 并发没有专门状态协议 | 正常 stop 可 join；宿主崩溃不保证；未做线程数/队列现场核验。 |
| 输入临时 PDF/AI Studio Base64 文件 | `NamedTemporaryFile(delete=False)` | context manager finally `unlink(missing_ok=True)` | 推理异常/取消离开上下文仍删；进程硬崩溃可能留残留 | 正常代码有 finally；未执行临时目录扫描，不能宣称零残留。 |
| `requests.Session`/异步 API client | API client/HTTP client 初始化 | `client.close()`；MCP AI Studio `stop()` 调用 | request/poll 异常由上层转换；轮询取消未证明服务端 job 停止 | 崩溃可能由连接池/远端作业自行回收；未做服务端/连接现场验证。 |
| 远端 job 与预签名 JSONL/图片 URL | `submit_*` 返回 job；done 返回 URL | 客户端只读取，不拥有远端删除 | `PollTimeoutError` 不等于远端取消；重复 submit 也无客户端幂等承诺；URL 过期/坏 JSONL 会失败 | 远端 job/URL 生命周期不在本仓库控制范围，必须由 provider SLA 证明。 |
| JSONL/结果 dataclass | poller 解析进内存；保留 `raw/data_info` | Python 引用释放 | malformed payload→`ResultParseError`；没有部分结果提交语义 | 宿主崩溃丢失内存结果；未验证大文档内存上限。 |
| 结果输出文件 | `_atomic_write` 创建同目录临时文件 | `os.replace` 或 `link` 后删临时文件 | 单文件失败清理；多文件失败不回滚前面成功文件 | 正常 finally 清理临时文件；未做崩溃注入/残留扫描。 |

### 14.2 失败、超时、取消、崩溃矩阵

| 场景 | 当前实现 | 可重试判断 | 不能假绿的验收要求 |
|---|---|---|---|
| 空输入/相对路径/不存在路径 | `input_contract.py:108-127` 前置拒绝 | 不应重试，先修输入 | 必须断言未调用 provider；当前仅源码/测试存在性，未当前核对执行。 |
| 非法模型/provider 组合 | `selection.py`/`InferenceFactory.create` 抛 `ValueError`；CLI model 解析 exit 2 | 不应重试 | 应覆盖每个白名单外组合和错误码。 |
| provider 凭据缺失 | `__main__.py:153-181` exit 2 | 不应重试 | 参数门禁测试不能替代真实认证。 |
| HTTP 401/403/400/429/503/504 | `_core.py:148-159` 分层异常 | 401/400 通常不可重试；429/503 需退避和配额策略，但本库不自动重试提交 | 需用 mock/真实服务分别证实调用次数、退避和异常映射。 |
| 请求断线/请求超时 | `_http.py:113-123,144-155,159-183` → `NetworkError/RequestTimeoutError` | 读取可按业务重试；提交重试可能重复创建 job，不能默认重试 | 必须证明幂等策略；当前无客户端幂等键。 |
| job failed/未知状态/缺 result URL | `_poller.py:69-79`、`_core.py:119-192` | job failed 通常不可盲重试；格式错误先升级 provider | 需构造 pending→failed、unknown、done-but-no-json URL。 |
| 轮询超时 | 默认 600s→`PollTimeoutError` | 可查询状态后人工决定；不等于取消 | 必须确认远端 job 是否继续消耗资源；源码没有 cancel。 |
| 主动取消/客户端断连 | async task 可取消 sleep/await，但无 provider cancel 调用 | 不可宣称端到端取消 | 需注入取消并检查 thread、HTTP request、远端 job、临时文件。 |
| worker/第三方模型抛异常 | Future 传回异常；Task/FastMCP 统一边界 | 视异常；当前没有统一重试 | 需证明 worker 仍可继续处理后续请求且 stop 可 join。 |
| 进程崩溃/强杀 | 无崩溃钩子；远端 job、临时文件、模型资源依赖宿主/服务行为 | 需重启恢复策略，源码未提供 | 必须外部现场检查线程、临时文件、端口、远端任务，不能以 finally 证明崩溃清理。 |
| 批量资源部分成功 | 每个资源单独原子写，已写文件不回滚 | 可从失败项重试，但需 overwrite/命名策略 | 需验证重复运行不会误覆盖；不能宣称批量事务。 |

## 15. 防假绿验证分级（L0-L4）

本分级把“源码存在、测试存在、mock 通过、真实外部运行、失败清理”分开；任一级不得用更低级证据冒充。

| 等级 | 证明目标 | 合格证据 | 当前状态 |
|---|---|---|---|
| L0 静态事实 | 文件、符号、入口、配置和调用箭头确实存在 | 当前源码路径+行号、Git 基线、无 `.codegraph/` 事实 | **已完成静态取证**；专属 MCP `codeexplore` 返回目标根无 `.codegraph/`，不能声称有代码图。 |
| L1 单元/契约 | 纯函数和边界契约的输入/输出/异常 | 直接运行对应单测并记录测试数/退出码；不是“测试文件存在” | **部分可见，未当前核对运行**；存在 `tests/api_client/`、`tests/unit/`、`tests/security/`，不能计为当前核对通过。 |
| L2 组件集成 | wrapper↔adapter↔task、API client↔mock HTTP、MCP 注册组合 | 隔离 mock/fixture 运行，断言调用次数、异常、资源清理 | **未验证**；旧 `TEST_REPORT.md`/历史报告不计当前核对证据。 |
| L3 真实端到端 | 真实 PaddleX/权重或真实 provider/API 完成 OCR/解析 | 明确环境、模型/服务、输入、输出、退出码、资源清理 | **未验证**；当前核对未安装依赖、未下载权重、未启动 MCP、未调用云 API。 |
| L4 逆向/生产韧性 | 超时、取消、断线、失败、重启、崩溃、并发、资源零残留 | 故障注入+现场读回线程/进程/端口/临时目录/远端状态/输出完整性 | **未验证**；源码只支持部分 finally/atomic write，不能推导崩溃安全。 |

## 16. 未验证项、吸收/不吸收裁决与剩余风险

### 16.1 未验证项

1. 目标仓库没有 `.codegraph/`；不能提供符号图、最近成功验证或影响面图。`project_context` 返回的代码地图属于错绑项目 `/Users/hekunhua/Documents/Agent/PHP/华世王镞_v3`，已排除，不作为 PaddleOCR 证据。
2. 没有在当前核对安装 PaddlePaddle/PaddleX、下载模型、启动 FastMCP、调用本地推理或真实云 provider；因此所有 L2-L4 仍是未验证。
3. 未运行 pytest/TIPC/API mock 测试；测试目录和历史 `TEST_REPORT.md` 只证明测试材料存在/曾有记录。
4. 未验证 `mcp_server` 发行包 `paddleocr>=3.7.0` 与当前源码 checkout 的实际解析组合、provider endpoint schema、token 权限和预签名 URL 有效期。
5. 未验证大 PDF/长文档的内存上限、并发模型、GPU/CPU 设备释放、PaddleX `close()` 是否在 MCP local stop 中确实需要调用。
6. 未验证 `LocalSyncRunner` 在 Future 被取消、worker 正在执行、stop 并发时的行为；该区域应作为高优先级故障注入目标。
7. 未验证远端 job 在轮询超时或客户端断开后是否继续运行；源码没有 cancel/回收 API。
8. 未验证批量资源保存的中途失败恢复和跨文件原子性；源码明确只有单文件原子写入。

### 16.2 吸收裁决

- **吸收**：旧细探中的 v3 薄封装、传统 `ppstructure`、MCP provider 工厂、输入适配、官方异步 API、结果转换、资源保存、错误层次、测试分层和依赖/许可证边界；已映射到本档案第 3—15 节。
- **不吸收为当前事实**：README/旧细探中的性能、精度、模型领先性、外部服务可用性、远端 SLA、技能实际触发、旁路线部署成功；这些只能作为声明或待核线索。
- **隔离保留**：v2 训练/推理线、HPD-Parsing、PaddleOCR-VL、JS、LangChain、C++/Serving/容器作为独立边界，不与 `paddleocr` 主 pipeline 调用链拼成单一实现。
- **待核升级条件**：在隔离环境执行 L1-L4；对本地 pipeline `close()`、取消、远端 job 回收和多资源输出做故障注入；以真实退出码和现场读回替换当前静态结论。项目本地 CodeGraph 已同步，能够辅助 Python/YAML/C++/TypeScript 等索引范围内的符号定位，但不替代运行态证据。

### 16.3 关键剩余风险

| 优先级 | 风险 | 直接证据/影响 |
|---|---|---|
| P0 | MCP local provider 未显式关闭 PaddleOCR/PaddleX pipeline | `mcp_server/.../inference/ocr/local.py:82-85`、`pp_structurev3/local.py:56-59` 只关闭 `LocalSyncRunner`；而 wrapper 的释放入口在 `paddleocr/_pipelines/base.py:79-80`。长驻进程可能保留模型/设备资源。 |
| P0 | 超时/取消不等于远端 job 取消 | `_poller.py:59-86`、`_async_poller.py:51-78` 只有轮询超时，没有 cancel endpoint；重试提交可能重复 job。 |
| P1 | `LocalSyncRunner` 取消与关闭竞态未定义 | `local_sync_runner.py:34-59` 没有检查 Future 状态/取消传播；可能出现排队任务、已取消 Future 或关闭时线程行为未证实。 |
| P1 | 远端 API 与发行包版本耦合 | 根包 `paddlex` 约束、MCP 已发布 `paddleocr>=3.7.0` 和当前 checkout 需一起锁定；否则 wrapper/结果字段可能漂移。 |
| P1 | 资源批量保存非事务 | `_resources.py:89-119` 逐个写入，失败后前面文件保留；调用方需清单/断点/覆盖策略。 |

## 17. 当前版本与 CodeGraph 复核

本次复核确认本地 `HEAD=2661c7c0ef5c613e8f93c6e93b2e052399f0f854`，`origin/main` 的 `ls-remote` 同为该提交，未发现本地与远程分叉。项目本地 CodeGraph `status`：1,160 files、14,850 nodes、33,164 edges、42.61 MB、`node:sqlite` WAL；语言统计 Python 593、YAML 240、C++ 105、TypeScript 90、Kotlin 43、Swift 33、Go 14 等，索引 up to date。

`codegraph sync` 返回 Already up to date；`codegraph explore PaddleOCRPipelineWrapper PaddleOCR predict LocalSyncRunner --max-files 8` 返回 13 symbols，识别出 `PaddleOCR.predict` 等 10 个 `PaddleXPipelineWrapper` 运行时实现，以及 `LocalSyncRunner` 被三个 MCP local provider 使用。该 CodeGraph 是目标源码目录本地索引，不经过 MCP；不能代替真实模型、GPU、远端 job 或线程回收验证。

## 18. 版本化入口导航

| 入口 | 当前源码证据 | 备注 |
|---|---|---|
| v3 OCR | `paddleocr/_pipelines/ocr.py:44-237` | 支持 PP-OCRv3/v4/v5/v6，旧参数映射到新参数 |
| v3 基类 | `paddleocr/_pipelines/base.py:18-109` | 配置合并、PaddleX create/close |
| 版面 | `paddleocr/_pipelines/pp_structurev3.py` | 外部 PaddleX pipeline |
| 传统检测 | `tools/infer/predict_det.py:42-244` | PP-OCRv5/v6 detector、batch 参数 |
| 传统识别 | `tools/infer/predict_rec.py:45-195` | 多语言模型与识别 batch |
| 传统总链 | `tools/infer/predict_system.py` | det→cls→rec 组合 |
| MCP local | `mcp_server/paddleocr_mcp/inference/shared/local_sync_runner.py:21-59` | 线程/队列/未来对象 |
| Python API SDK | `api_sdk/python/` | HTTP API、异步 client、结果转换 |
| JS SDK | `paddleocr-js/packages/core/` | Worker-backed 浏览器 OCR |
| Android SDK | `deploy/ppocr-android/ppocr-sdk/` | DetectionEngine/RecognitionEngine |
| 文档转换 | `paddleocr/_doc2md/` | PDF/Office/HTML 等转 Markdown |

## 19. 当前核对未验证项

- 未安装 PaddlePaddle/PaddleX 或 MCP extras，未下载 PP-OCR 权重。
- 未执行 CPU/GPU 单图、多页 PDF、表格、版面、公式和印章样本。
- 未启动 MCP stdio/HTTP、官方 API、JS Worker、Android 或 C++ 服务。
- 未实测 batch 并发、线程 join、GPU 显存回收、PaddleX `close()` 和取消竞态。
- 未实测远端 job 超时后的服务端资源、预签名 URL 过期和重复提交幂等性。
- 未运行全量 pytest、TIPC、benchmark、移动端 benchmark 或部署脚本。

本轮仅修改平台唯一 `ARCHITECTURE.md`；源码仓库未改，`.codegraph/` 与源码侧文档保留。全程未调用 MCP，只使用 shell/git/项目本地 CodeGraph。
| P1 | 默认跳过 resource-intensive 测试 | 根 `pyproject.toml` 的 pytest `addopts` 排除资源密集型测试；轻量绿色不证明模型/设备/内存可用。 |
| P2 | 敏感文档与结果资源 | 输入可能是身份证、发票、合同；默认 stdio/127.0.0.1 不是完整鉴权、审计、加密和保留期方案。 |

## 17. 当前核对验证记录

| 项目 | 结果 |
|---|---|
| 专属 MCP 实例 | `project_toolkit`（HTTP `127.0.0.1:8766/mcp/`，按任务上下文指定） |
| `project_context` | **退出/返回成功但错绑**：返回项目 `华世王镞_v3`、根 `/Users/hekunhua/Documents/Agent/PHP/华世王镞_v3`；不能当目标项目身份证据。 |
| `codeexplore`（用户称 `codegraph_explore`） | **失败/不可用**：目标根无 `.codegraph/`；MCP 明确 `可重试=false`，未绕过冒充。 |
| 目标项目根 | `/Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/20_vision_ocr_detection/PaddleOCR` |
| Git 基线 | `main`，HEAD `2661c7c0ef5c613e8f93c6e93b2e052399f0f854`；既有档案记录 `HEAD...origin/main = 0 0`，当前核对未重新 fetch。 |
| 文件变更范围 | 仅本文件；`细探-PaddleOCR.md` 保留。最终需用 `git status --short` 和 diff 复核。 |
| 真实执行 | 当前核对未安装依赖、未启动服务、未跑模型/云 API、未运行测试；L0 静态取证完成，L1-L4 未通过。 |

**收口结论**：旧细探的有效源码事实已吸收到本唯一 `ARCHITECTURE.md`；旧细探不删除。对于无法从当前源码证明的成功、性能、取消、崩溃清理和真实 provider 行为，明确标为未验证或待核，不以历史报告、测试文件存在或 MCP 错绑项目的成功结果冒充绿色。

## 18. 后续：通用底座映射与唯一归属裁决

### 18.1 当前核对目标、边界和证据口径

当前核对不把 PaddleOCR 复制进系统工程平台，也不把 `mcp_server` 的工具名当作平台能力边界，而是回答：**PaddleOCR 的能力分别应由通用 OCR/文档模块、支持库、运行核心和项目适配层中的哪一个唯一 owner 承担**。本节是目标平台的映射输入，不表示平台已经完成对应实现。

当前核对直接对照的目标仓库源码证据包括：

- v3 模型包装与 PaddleX 接线：`paddleocr/_pipelines/base.py:54-109`、`ocr.py:66-237`、`pp_structurev3.py:31-298`；
- 传统版面/表格/文档恢复：`ppstructure/predict_system.py:44-271`、`ppstructure/table/predict_table.py:58-153`、`ppstructure/recovery/recovery_to_markdown.py:129-187`、`recovery_to_doc.py:32-84`；
- MCP 模型选择、provider 注册和 Task：`mcp_server/paddleocr_mcp/selection.py:20-77`、`inference/factory.py:32-200`、`tasks/base.py:29-106`；
- 四 provider 和统一输入：`providers.py:21-88`、`inference/shared/input_contract.py:66-153`、`input_adapters.py:45-182`；
- 官方异步作业：`paddleocr/_api_client/_core.py:119-211`、`_poller.py:44-152`、`_async_poller.py:36-86`、`async_client.py:45-253`。

因此，以下“吸收”表示源码事实可以作为底座契约输入；“隔离”表示保留为版本适配或历史参考，不能成为第二套公共内核；“待核”表示需要真实环境或平台现有能力检索后才能装配。

### 18.2 唯一归属总图

```text
项目调用方 / HTTP 能力网关
  → PaddleOCR 项目适配层（模型别名、参数版本、provider 配置、凭据引用）
  → 通用 OCR 模块 / 通用文档解析模块（领域编排、一次结果归一化）
  → 能力注册表与唯一调用器
  → 支持库（输入、文档结构、结果转换、模型制品、文件和 HTTP 薄适配）
  → 运行核心（任务状态、监督、超时取消、进程/线程、显存/文件/句柄租约）
  → PaddleOCR provider 运行环境或远端 API（local / aistudio / qianfan / self_hosted）
  → 统一文档结果、统一任务状态、统一资源证据
```

唯一边界裁决：

1. **领域模块拥有“做什么”和“结果语义”**：OCR、版面、表格、公式、文档阅读顺序和文档结构拼装属于通用 OCR/文档模块；模块不直接 import `paddlex`、`paddleocr`、`httpx` 或云 SDK。
2. **支持库拥有“如何转换和适配”**：输入类型、Base64/URL/绝对路径、文档块/资源结构、provider payload、结果字段转换、模型制品描述和文件原子写入属于支持库公开能力；支持库不拥有任务状态机和业务流程。
3. **运行核心拥有“如何运行、何时停止和谁释放”**：异步作业、执行监督、超时/取消、子进程隔离、线程排空、模型/显存/临时文件租约和崩溃恢复属于运行核心；provider 不得私自维护第二套任务系统。
4. **项目适配层只绑定差异**：PaddleOCR 版本、模型名、provider endpoint、参数别名、凭据引用和外部返回字段在此绑定；不能把 `PP-OCRv6`、`paddleocr_vl`、`parse` 等项目字符串散落到多个公共消费者。
5. **MCP/API 是适配面，不是平台边界**：`mcp_server` 的 FastMCP tool、`Task._invoke_tool()`、`PaddleOCRClient`/`AsyncPaddleOCRClient` 都必须被视为调用协议适配器。平台边界是 HTTP 能力网关的搜索/契约/执行和通用能力契约；MCP 只能可选地把该边界翻译为工具。

### 18.3 现有能力命中表与唯一 owner

| PaddleOCR 能力/证据 | 通用底座落点 | 唯一 owner 裁决 | 当前核对状态 |
|---|---|---|---|
| `PaddleOCR` 的方向分类、去畸变、文本检测、文本行方向、文本识别 | 通用 OCR 模块编排；模型名、配置覆盖和推理句柄下沉 provider/运行核心 | OCR 模块只负责 OCR 流程和参数契约；PaddleX wrapper 不是模块 owner | **吸收/拆分** |
| `PPStructureV3` 的版面、区域、表格、公式、图表、印章和 GeneralOCR 组合 | 通用文档解析模块；版面/表格/公式/印章是文档块生产能力 | 文档解析模块拥有统一文档结果；各模型实现只作为 provider 策略 | **吸收** |
| 传统 `StructureSystem` 的版面分区、全图 OCR 后 bbox 相交过滤 | 文档模块的兼容策略或旧 provider 适配 | 不迁移 `sys.path` 和过程式全局状态；不得与 v3 另建公共入口 | **隔离/待核** |
| `TableSystem` 的结构预测、OCR、`TableMatch`/`TableMasterMatcher`、HTML | 文档模块的表格块编排；匹配算法可进入表格支持库 | 只能有一个表格结果转换 owner，不能由 MCP Task 或调用方再次拼表 | **吸收算法语义，待平台落点** |
| `recovery_to_markdown.py`、`recovery_to_doc.py`、`_doc2md/` | 通用文档结果投影/文档转换支持库 | OCR/文档解析输出统一为文档结构；Markdown/DOCX/XLSX 是投影或转换产物，不反向定义解析契约 | **吸收/拆分** |
| `_models`、`_pipelines/base.py`、PaddleX `create_pipeline` | PaddleOCR provider 适配 + 运行核心模型句柄 | 不把 `PaddleXPipelineWrapper` 误放成通用模块；其 owner 是版本化 provider 适配 | **吸收模式，待实现** |
| `_api_client` 的 submit/status/poll/JSONL | 远端异步 provider 适配；任务状态由运行核心统一投影 | API client 不拥有平台任务状态，不自行决定取消完成 | **吸收协议，隔离状态实现** |
| `InferenceFactory` 的 `(tool, provider) → factory` | 现有能力注册表/提供者选择器的项目适配层输入 | 注册表可借鉴；不能在 MCP 包内复制平台第二套注册表 | **吸收思想，禁止照搬边界** |
| `local` / `aistudio` / `qianfan` / `self_hosted` | 同一通用 OCR/文档模块契约下的四个 provider 策略 | provider 只实现输入/调用/结果转换/释放，不复制 OCR 或文档流程 | **吸收** |
| `Task.register_tools()`、`OCRTask`、`DocParsingTask` | MCP 可选适配器；`simple/detailed` 是展示投影 | 不作为公共契约，不把 `TextContent/ImageContent` 写入领域核心 | **隔离** |

### 18.4 通用 OCR 与通用文档模块的装配边界

#### 18.4.1 通用 OCR 模块

通用 OCR 模块的公开能力应是一个稳定的领域入口，例如“识别图像/页面”，输入为通用文件引用、页范围、语言/模型策略和 OCR 参数，输出先落为统一文档结构中的 `页面`、`文本块`、`文档资源` 和诊断信息。调用方若只需要纯文本，读取该结构的文本投影；不得把 `mcp_server` 的 `OCRResult(text, confidence, text_lines)` 另立为平台事实模型。

PaddleOCR 映射关系如下：

- `PaddleOCR.predict()` 的检测框、识别文本和分数 → `文本块`；`rec_boxes`/`rec_polys` 只能进入来源定位字段，不能成为平台公共字段的两份别名。
- `DocPreprocessor`、文本行方向和去畸变 → OCR 模块的可选阶段；阶段开关进入模块请求的能力参数，模型目录和 PaddleX 点路径留在 provider 参数映射。
- `OCRTask` 的 simple/detailed → 文档结果的“纯文本投影/结构化投影”，由适配层生成；`Confidence: xx%` 这种展示字符串不能写回结果事实。
- `local` 的 `LocalSyncRunner` → 运行核心的同步 provider 执行桥；不能让线程 Future 成为平台任务 id，也不能以 `Future` 状态代替已持久化任务状态。

#### 18.4.2 通用文档解析模块

通用文档模块负责页面顺序、版面块、表格结构、公式、图像、阅读顺序、Markdown/HTML 等可解释投影。`PPStructureV3` 的 `use_table_recognition`、`use_formula_recognition`、`use_seal_recognition`、`use_chart_recognition` 和 `use_region_detection` 映射为模块能力组合；具体模型和阈值由 provider 适配器翻译。

文档模块的唯一出口建议冻结为 `通用文档`（兼容平台既有 `公共契约/基础类型/文档结构.py` 的命名），最小字段为：

| 字段 | 语义与 owner |
|---|---|
| `schema_version` | 统一文档契约版本，由公共契约/模块发布，不由 provider 自定义 |
| `source` | 输入文件引用、媒体类型、摘要、页范围和来源 provider；凭据、临时绝对路径不进入结果 |
| `pages` | 有序页面集合；每页含页码、尺寸、方向和块引用 |
| `blocks` | `标题`、`段落`、`表格`、`公式`、`图像`、`页眉`、`页脚`、`区域` 等文档块，含 bbox/置信度/顺序/来源定位 |
| `table_data` | 表格的行列、合并、单元格文本和结构；HTML/Excel 是投影，不是唯一事实 |
| `resources` | 图像、预览、原始结果和生成文件的内容摘要/文件引用；不内嵌不受控的大型二进制 |
| `diagnostics` | 模型、provider、耗时、降级、警告和原始字段定位；不把异常字符串伪装成正文 |

`mcp_server/inference/types.py` 的 `DocParsingResult(markdown, pages, images_mapping)` 与 `_api_client/results.py` 的页级 `DocParsingResult` 都只能在适配层转换为上述结构。`markdown` 是一个投影，`images_mapping` 是资源引用集合；二者不得成为跨 provider 的唯一事实。所有 provider 的 `layoutParsingResults`、PaddleX `res.markdown` 和旧 `region` 字典都必须经过同一文档结果转换器；转换器负责字段缺失、页码、bbox、资源引用和诊断降级，模块出口不允许出现 provider 专属成功形状。

### 18.5 provider、模型包装与资源的唯一归属

#### 18.5.1 四 provider 映射

| provider | 当前源码行为 | 通用底座映射 | 必须保留的差异/限制 |
|---|---|---|---|
| `local` | `PaddleOCR`/`PPStructureV3` 在进程内创建，`LocalSyncRunner` 用线程把同步 `predict` 接入 asyncio；见 `inference/ocr/local.py:53-131`、`pp_structurev3/local.py:32-81` | provider 适配器 + 运行核心的本地隔离执行器；模型环境、设备和显存由运行核心登记 | 不能把 Paddle/PaddleX 对象穿透模块；优先独立 provider 进程/环境，主进程只收统一结果 |
| `aistudio` | `AsyncPaddleOCRClient` 提交官方异步 job、轮询并解析 JSONL；见 `ocr/aistudio.py:43-132`、`pp_structurev3/aistudio.py:44-112` | 远端异步 provider；运行核心创建平台任务并把远端状态投影到统一状态 | `token` 只作凭据引用；远端 job 由 provider 记录，轮询超时不能宣称远端取消 |
| `qianfan` | `HTTPInferenceBase` + `Authorization: Bearer`，调用 `paddleocr` endpoint；选择层只允许 `PP-StructureV3`/`PaddleOCR-VL`；见 `selection.py:22-27,67-75` | HTTP provider 适配器；文档模块统一消费结果 | 模型白名单和 endpoint 契约必须进入 provider 能力声明，不能让任意模型名透传 |
| `self_hosted` | `HTTPInferenceBase` 调 `ocr` 或 `layout-parsing` endpoint；见各 `self_hosted.py` | 自建 HTTP provider；运行核心管理请求、超时、连接池和释放 | 服务端模型/显存归远端宿主；客户端只持有连接与响应，不把远端状态伪装为本地资源 |

四种 provider 共用 `InputAdapter` 的输入归一化，但 transport 不等于领域能力：`ProviderTransport.LOCAL`、`AISTUDIO_API`、`HTTP` 只描述调用方式，不能产生三个不同的 OCR/文档契约。`InferenceFactory` 的注册表可以作为项目适配层的静态组合表，但最终能力 id、版本、参数契约、权限、资源预算和 provider 选择必须由平台唯一能力注册表裁决。

#### 18.5.2 模型包装与模型制品

`PaddleXPipelineWrapper` 负责读取 pipeline 配置、递归合并 overrides、调用 `create_pipeline` 并暴露 `close()`；`PaddleOCR` 和 `PPStructureV3` 负责将模型名、模型目录和开关映射到 `SubModules`/`SubPipelines` 点路径。这部分的唯一归属是 **PaddleOCR provider 适配器**，不是通用文档模块，也不是平台公共契约。

平台侧只登记稳定的模型描述：`model_id`、版本、provider、权重制品摘要、支持输入/输出、显存预算、设备类型、依赖环境摘要和能力兼容范围。实际 PaddleX 配置、`text_detection_model_name`、`table_*_model_dir`、`formula_recognition_model_name` 等字符串由 provider 适配器转换。模型权重不得写入 Git、任务状态或日志；下载、缓存、校验和淘汰归模型制品支持库，装载/卸载、显存 lease 和进程生命周期归运行核心。

#### 18.5.3 CPU/GPU/显存与文件资源

- **模型/显存**：运行核心在启动 provider 前申请模型环境和设备/显存租约，记录模型摘要、设备、预算、实际峰值和 owner；正常完成、失败、超时、取消、崩溃都必须释放或留下可恢复的租约证据。`device` 只是请求字段，不是释放证明。
- **输入文件**：`resolve_absolute_path()` 只接受绝对路径；Base64 image 转 contiguous RGB/BGR array，PDF/AI Studio 输入用 `NamedTemporaryFile(delete=False)` materialize。输入临时文件属于文件资源支持库，context 退出即删；运行核心负责在异常、取消和 provider 崩溃后扫描残留。
- **HTTP/session**：`requests.Session`、`aiohttp.ClientSession`、MCP 的 `httpx.AsyncClient` 属于 provider 适配资源；创建者持有，`close()`/`stop()` 是明确释放动作，不得由 Task 或调用方重复 close。
- **结果资源**：JSONL、预签名图片 URL、Markdown 中图片和本地导出文件先登记资源引用/摘要，再由资源支持库做单文件原子写入。批量保存失败不自动回滚前面成功文件，平台必须显式使用批次清单和补偿清理。

### 18.6 MCP/API 异步作业如何接入运行核心

#### 18.6.1 官方 API job

官方 `_api_client` 真实流程是：

```text
validate_input_source(file_url/file_path 二选一)
  → submit_url / submit_file
  → job_id + Job(task/model)
  → get_job_status / get_batch_status
  → pending|running|done|failed
  → resultUrl.jsonUrl
  → fetch_jsonl
  → parse_ocr_result / parse_doc_parsing_result
```

`Poller`/`AsyncPoller` 使用 3 秒初始间隔、1.5 倍退避、15 秒上限和默认 600 秒总等待；`done` 没有 `resultUrl.jsonUrl` 或 JSONL 坏格式仍是失败。`batch_id` 只是提交字段，源码没有证明客户端幂等。映射到运行核心时：

1. 网关接收一次能力执行请求，运行核心生成平台 `task_id`、请求摘要和幂等键；provider 适配器提交后记录 `remote_job_id`。
2. `pending/running` 映射为统一任务状态并保存进度；`done` 只有结果下载、摘要校验、统一文档转换成功后才允许平台任务进入 `succeeded`。
3. `failed` 映射为可解释的 `provider_failed`，保留远端错误和可重试性；`PollTimeoutError` 映射为 `timed_out`，不伪装成 `failed` 或 `canceled`。
4. 轮询器只能由运行核心监督；provider 适配器提供 `查询状态/取得结果/尝试取消` 原子能力，不另起平台任务线程或数据库。
5. 相同幂等键再次执行应读回原任务；没有幂等证据时不得对提交超时自动重试，否则可能创建重复远端 job。

#### 18.6.2 MCP tool

当前 `Task._invoke_tool()` 顺序是 normalize → validate → 合并/校验 runtime params → `InferenceRequest` → `Inference.predict()` → `OCRTask`/`DocParsingTask` 格式化。它没有平台任务 id、状态查询、取消接口和结果制品登记；FastMCP 的 `TextContent`/`ImageContent` 只是响应展示类型。因此：

- MCP 适配器必须调用平台通用模块/HTTP 能力网关，不能直接把 `Task` 注册为平台能力 owner。
- 若 MCP 需要长任务，工具响应返回平台 `task_id`/查询引用，而不是把长轮询永久包在一次 tool call 中；状态、结果和取消走同一任务系统。
- 若必须兼容当前同步工具，保留一个“提交并等待”的适配函数，但它内部仍调用统一任务执行器，并把等待、超时、取消和资源清理证据交给运行核心。
- `simple/detailed`、`return_images` 和动态 tool description 只属于 MCP presentation adapter；它们不能改变通用文档 schema 或任务状态。

#### 18.6.3 状态模型冻结

平台统一任务状态建议至少包含：

```text
created → queued → running → succeeded
                         ├→ failed
                         ├→ timed_out
                         └→ cancel_requested → canceled | cancellation_unconfirmed
```

provider 的 `pending/running/done/failed` 只能作为外部状态映射。`canceled` 只有 provider 已确认取消、进程已终止且资源已释放时才能使用；仅仅取消 asyncio task、Future 或 HTTP await 只能进入 `cancel_requested`/`cancellation_unconfirmed`。状态记录必须包含 `task_id`、`attempt`、`remote_job_id`、`state`、时间戳、deadline、进度、错误码、可重试、取消确认、结果引用和资源清单，并由运行核心唯一写入。

### 18.7 轮询、超时、取消、释放和崩溃裁决

| 场景 | 当前项目证据 | 底座唯一处理 | 验收要求 |
|---|---|---|---|
| provider 请求超时 | AI Studio 有 request/poll timeout；HTTP provider 有 read timeout | 运行核心记录 `provider_timeout`，停止当前 attempt，按幂等策略决定是否重试 | 证明调用次数、deadline、异常映射和 session 关闭 |
| 轮询超过 deadline | `_poller.py`/`_async_poller.py` 抛 `PollTimeoutError`，没有 cancel endpoint | 状态为 `timed_out`；若远端仍可查，后台 reconcile；禁止写 `canceled` | 读回远端 job 状态或如实标 `cancellation_unconfirmed` |
| 主动取消/客户端断连 | async sleep/await 可取消；源码未调用远端 cancel | 运行核心先原子写 `cancel_requested`，调用 provider cancel（若支持），排空本地 worker，最后决定 `canceled` | 检查线程、进程、请求、临时文件、显存 lease 和远端任务 |
| local stop | `local.py:82-85`、`pp_structurev3/local.py:56-59` 只 close `LocalSyncRunner`，未显式调用 wrapper `close()` | provider adapter 必须补偿释放 PaddleOCR/PaddleX wrapper，再由运行核心释放设备租约 | 不能以 `runner.close()` 代替模型/显存释放证明；这是当前 P0 缺口 |
| AI Studio stop | provider `stop()` 调 `AsyncPaddleOCRClient.close()` | 由 provider adapter 关闭 HTTP session；平台任务状态仍由运行核心收口 | 测试重复 stop、失败 stop 和取消中 stop 的幂等性 |
| HTTP provider stop | `HTTPInferenceBase.stop()` 调 `AsyncHTTPClient.stop()` | 关闭连接池、排空请求；远端推理资源由远端 SLA/状态接口负责 | 客户端关闭不等于远端任务取消，必须分别记录 |
| worker/进程崩溃 | 当前 local runner 无崩溃恢复状态机；MCP finally 只覆盖正常控制流 | 运行核心独立进程组、有限重启、死亡租约回收和残留扫描 | 强杀后检查 PID/线程/端口/临时目录/显存/任务状态 |
| 结果批量落盘部分成功 | `_resources.py` 单文件原子写，批量失败不回滚已写文件 | 资源清单状态化，失败进入补偿/清理，不宣称事务 | 重复运行、目标冲突、半成品和摘要一致性必须可读回 |

### 18.8 缺口表与复用/升级/新建/废弃裁决

| 缺口或模式 | 裁决 | 原因与下一步 |
|---|---|---|
| OCR 文本、框、置信度和文档块有多套结果形状 | **升级现有通用文档模块** | 统一 `通用文档` 出口；MCP/API/旧版字典只做输入适配，不保留平行事实模型 |
| 版面/表格/公式/图像/阅读顺序组合 | **升级现有通用文档模块** | PP-StructureV3 是编排证据，表格和公式是块生产策略，不应各自创建公共文档结果 |
| PaddleX/PaddlePaddle/python-docx 等重依赖 | **新建或复用 provider 支持库 + 运行核心隔离** | 第三方依赖不得进入核心公共部分；local 进程内加载和 close 缺口需先做隔离/释放验证 |
| 输入路径、URL、Base64、data URL 与临时文件 | **复用/升级文件与输入支持库** | `InputAdapter` 契约可吸收；绝对路径安全、内容摘要、临时目录、清理证据必须统一 |
| 官方 API `submit/poll/fetch JSONL` | **复用异步任务运行核心，新增 PaddleOCR provider 适配** | 不复制 Poller 任务状态；保留 provider 轮询算法作为适配实现，统一平台状态/超时/取消 |
| MCP `Task`、动态 tool description、`TextContent/ImageContent` | **隔离为可选协议适配器** | 智能代理接口不应决定平台能力、权限、结果 schema 或资源 owner |
| `ppstructure` 的 `sys.path`、全局环境变量和过程式写文件 | **废弃为生产底座模式，保留只读兼容参考** | 与单网关、统一资源和可审计调用链冲突；若兼容，必须包在项目 provider 隔离层 |
| `_doc2md` Office→Markdown | **复用文档转换支持库，不并入 OCR 解析内核** | 它消费办公文件结构并生成 Markdown/图片资源，不是 OCR/版面识别事实源 |
| `batch_id` 作为幂等保证 | **废弃该推断，待核真实服务语义** | 源码仅把它作为请求字段；平台必须自有幂等键和提交证据 |
| 远端取消能力 | **待核** | 当前源码无 cancel API；未取得服务端确认前只能报告取消未确认，不能承诺端到端取消 |

### 18.9 装配计划与依赖顺序

当前核对不修改生产底座；未来落地必须按以下工作包冻结租约，禁止边查边在公共入口加旁路：

1. **契约冻结**：在公共契约中冻结 `通用文档`、`文本块`、`表格数据`、`文档资源`、`生成/解析结果`、任务状态和错误码；用 `schema_version`、模型/provider 元信息和原始字段定位承接 PaddleOCR 差异。
2. **能力搜索与复用裁决**：检索现有 OCR、文档解析、文件、模型制品、HTTP、异步任务、资源监督能力；每个能力只保留一个能力 id、契约 owner 和注册路径。没有搜索/租约/验收契约不得新建。
3. **结果转换支持库**：先实现 provider-neutral 的 PaddleX/官方 API/HTTP/旧结构结果转换，写入统一文档结构；不把转换逻辑复制到四 provider。
4. **PaddleOCR provider 适配**：分别绑定 local/aistudio/qianfan/self_hosted 的模型白名单、参数映射、payload、状态查询、结果下载和错误映射；provider 只通过模块/能力调用器暴露。
5. **运行核心接线**：接入任务状态、幂等键、deadline、轮询、取消确认、进程组、显存 lease、临时文件和 session 释放；建立正常/失败/超时/取消/崩溃四终态证据。
6. **协议适配**：最后把 HTTP 能力网关接到模块；MCP 仅做网关到 tool 的可选翻译。任何 MCP-only 能力必须标记为适配器，不得成为平台契约。
7. **逆向验收**：故意移除统一结果转换、provider 声明、取消排空、模型释放和资源清单，验证 L1-L4 门禁确实失败；不得用打印日志或子代理回执代替。

### 18.10 L0-L4 验证工作包

| 等级 | 本项目映射验证 | 必须记录的证据 | 当前状态 |
|---|---|---|---|
| **L0 静态** | 源码路径、能力/模型/provider 矩阵、结果字段、资源创建/释放箭头、依赖边界 | 文件/行号、版本基线、目标根、`.codegraph/` 状态、错绑上下文 | **当前核对完成**；目标根无代码图 |
| **L1 契约** | 纯函数验证模型白名单、provider 组合、输入互斥、状态枚举、结果转换、错误映射 | 定向单测测试数/跳过数/退出码；禁止把测试存在当通过 | **未执行** |
| **L2 组件集成** | wrapper↔provider adapter↔module、HTTP mock、异步 poller、JSONL→通用文档、临时文件清理 | mock 调用次数、状态轨迹、统一结果字段、session/文件释放 | **未执行** |
| **L3 真实端到端** | 隔离环境运行 local OCR/PP-StructureV3，或真实 AI Studio/Qianfan/self-hosted；输入真实图片/PDF | Python/依赖/模型/设备、job id、输出摘要、退出码、模型/显存/文件清理 | **未执行**；未装依赖、未下载权重、未启动服务、未调用云端 |
| **L4 逆向与韧性** | 注入提交断线、轮询超时、unknown state、job failed、主动取消、worker 异常、SIGKILL、结果下载失败、重复幂等 | 任务状态最终值、重试次数、取消确认、PID/线程/端口/临时目录/显存 lease/远端 job 读回 | **未执行**；当前源码不能推出崩溃安全或远端取消 |

L0-L4 的通过口径是“当前核对真实命令+退出码+现场读回”，不是历史 `TEST_REPORT.md`、README 声明、mock 通过或 MCP tool 能注册。L3/L4 若外部 provider 不可用，记录 `HOST_UNAVAILABLE`/`UNVERIFIED` 及阻塞原因，不得改写为 skip 后绿色。

### 18.11 后续裁决结论与剩余风险

- **吸收**：v3 PaddleX 薄封装的“参数映射→配置合并→外部 pipeline”、MCP provider 选择矩阵、统一输入适配、官方异步 job/JSONL 协议、版面/表格/文档投影的事实，作为通用 OCR/文档模块和 provider 适配的输入。
- **唯一归属**：OCR/版面/表格/公式/文档块编排归通用文档模块；输入/结果/模型制品/文件/HTTP 薄转换归支持库；任务状态/监督/超时/取消/模型显存/句柄和崩溃清理归运行核心；provider 只绑定外部差异；MCP/API 只做协议适配。
- **隔离**：`mcp_server` 的智能代理工具面、`TextContent/ImageContent`、`simple/detailed`、`LocalSyncRunner` Future、旧 `ppstructure` 全局路径和过程式落盘不进入平台公共边界。
- **P0 剩余风险**：local provider `stop()` 没有显式调用 PaddleOCR/PaddleX wrapper `close()`；官方轮询 timeout/async cancel 没有服务端 cancel；当前无统一平台 task id、幂等状态和资源租约证据。这三项在底座装配前必须先冻结验收契约。
- **P1 剩余风险**：provider 返回结构差异、批量资源非事务、模型/显存峰值和大文档内存上限、MCP 发行包与 checkout 版本组合尚未在真实环境验证。
- **不得越界**：当前核对没有修改系统工程平台、PaddleOCR 源码、配置、依赖、测试、README 或旧细探；本节只作为后续底座映射文档输入。

## 19. 后续 MCP/验证记录补充

| 项目 | 结果 |
|---|---|
| 开工 id | **未取得**：`project_context` 返回连续 4 次失败（server unreachable），`codeexplore` 元信息的开工 id 为空；不能伪造有效 id。 |
| MCP 实例 | 按任务指定 `system_engineering_toolkit` / `project_toolkit`，Streamable HTTP `http://127.0.0.1:8766/mcp/`；实际工具回报服务不可达。 |
| `project_context` | **失败/不可用**：无法核对返回项目名和根目录；后续 codegraph 响应携带的项目根是 `/Users/hekunhua/Documents/Agent/PHP/华世王镞_v3`，与目标 PaddleOCR 根不匹配，已排除。 |
| `codegraph_explore` | **失败/不可用**：对应工具实际名称为 `codeexplore`；返回目标 PaddleOCR 无 `.codegraph/` 索引，`可重试=false`，代码图状态/最近 1—3 次成功验证均不可得。 |
| MCP 五字段反馈 | **调用失败**：`mcp_feedback` 首次调用因 server unreachable 未入账；已准备并提交摘要、不满意、多余、缺失、升级建议，不能声称反馈成功。 |
| `verify_and_record` | **命令退出码 0，但上下文不匹配**：执行 `git diff --check`，返回“弱验证/工作包”，临时开工 id=`临时-2300a80e2cdd`、源码指纹=`a21170ed0797606b`、证据 id 列表为空；同时返回 `MCP_WORK_ID_REQUIRED`，元信息项目根仍是 `/Users/hekunhua/Documents/Agent/PHP/华世王镞_v3`。因此仅记录命令退出 0，不记为 PaddleOCR 目标项目的有效强验证。 |
| 项目根 | `/Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/20_vision_ocr_detection/PaddleOCR` |
| 修改文件 | 仅 `ARCHITECTURE.md`；`细探-PaddleOCR.md` 保留，源码/配置/依赖/测试/README 未修改。 |
| 真实验证 | 后续为静态源码映射；未安装依赖、未运行模型、未启动 provider/MCP、未调用真实 API；L0 完成，L1-L4 未通过。 |

## 20. 后续深挖收口：模型注册、预处理、设备、批处理与释放

本节是后续指定主题的补充收口，优先记录“源码实际做了什么”，并把 v3 `paddleocr/`、v2 `tools/infer`/`ppocr/`、MCP 服务三条边界分开。除文末验证记录外，本节仍是 L0 静态取证；没有把 PaddleX 外部实现、README 性能声明或测试文件存在当成运行证据。

### 20.1 模型注册与模型身份：三种机制，不能混写

| 层 | 实际注册/选择机制 | 关键行为 | 证据与边界 |
|---|---|---|---|
| v3 pipeline | `PaddleOCR._get_ocr_model_names(lang, ocr_version)` 静态映射语言和 PP-OCR 版本；默认是 `PP-OCRv6_medium_det` + `PP-OCRv6_medium_rec` | `PP-OCRv6` 按 `_PPOCRV6_LANGS` 放行；`PP-OCRv5` 再按 `latin/eslav/arabic/cyrillic/devanagari/korean/th/el/te/ta` 选择识别模型；v4 只有 `ch/en`；v3 使用语言前缀拼接识别模型名。显式 `*_model_name`/`*_model_dir` 存在时不再自动选模型，`lang`/`ocr_version` 仅 warning 后忽略 | `paddleocr/_pipelines/ocr.py:44-62,97-127,318-422`。模型真实下载、权重校验、网络缓存和 PaddleX predictor 创建不在本仓库；`PaddleXPipelineWrapper` 最终交给外部 `create_pipeline`。 |
| v3 单模型 wrapper | `paddleocr/__init__.py` 静态导出类；每个 wrapper 给出 `default_model_name`，基类调用 PaddleX `create_predictor(model_name, model_dir, ...)` | `TextDetection` 默认 `PP-OCRv6_medium_det`，`TextRecognition` 默认 `PP-OCRv6_medium_rec`，行方向分类默认 `PP-LCNet_x0_25_textline_ori`；没有本仓库级动态模型注册表 | `paddleocr/_models/base.py:30-82`、`_models/text_detection.py:24-31`、`text_recognition.py:23-37`、`textline_orientation_classification.py:21-29`。`close()` 仅调用外部 predictor 的 `close()`。 |
| MCP 模型/工具选择 | `SUPPORTED_MODELS` + `_MODEL_TOOLS` 把用户模型映射到 `ocr`、`pp_structurev3`、`paddleocr_vl`；`resolve_model()` 再校验 provider，`InferenceFactory._registry` 用 `(tool, normalized_provider)` 选 factory | Qianfan 只放行 `PP-StructureV3`/`PaddleOCR-VL`；注册表在 `factory.py` 导入时填充，未注册组合直接 `ValueError`；local OCR 再通过 `_LOCAL_OCR_INIT_BY_MODEL` 把 `PP-OCRv5/PP-OCRv6/PP-OCRv5-latin` 映射成 PaddleOCR 初始化参数 | `mcp_server/paddleocr_mcp/selection.py:20-77`、`inference/factory.py:32-67,164-200`、`inference/ocr/local.py:25-50`。模型白名单、工具名和 provider 组合不能凭字符串推断。 |
| v2 配置驱动模型 | 训练/旧版推理由 `Architecture`、`PostProcess` 等 YAML 的 `name` 驱动 builder；`build_model()` 动态取 `ppocr.modeling.architectures.<name>`，`BaseModel` 再按 `Transform → Backbone → Neck → Head` 逐层构造 | backbone 和 postprocess 都是“导入类 + `support_dict` + `eval(name)`”的显式白名单；`build_model` 自身没有 decorator/插件注册机制。训练/推理在 build 前会根据字符字典长度补写 recognition head 的 `out_channels` | `ppocr/modeling/architectures/__init__.py:27-35`、`base_model.py:27-76`、`ppocr/modeling/backbones/__init__.py:18-156`、`ppocr/postprocess/__init__.py:66-121`、`tools/train.py:75-144`。这是 v2 配置注册，不是 v3 PaddleX 模型目录注册。 |
| v2 发布模型目录 | `tools/infer/predict_det.py`、`predict_rec.py`、`predict_cls.py` 读取 `inference.yml` 的 `Global.model_name` 并与内置允许列表比对 | 不支持的模型名抛 `ValueError`；识别器在默认字典路径下会从 `inference.yml:PostProcess.character_dict` 生成 `<rec_model_dir>/ppocr_keys.txt` 并改写 `args.rec_char_dict_path`，这是模型目录内的运行时写入副作用 | `tools/infer/predict_det.py:36-50`、`predict_rec.py:40-69`、`predict_cls.py:40-49`。不存在 `model_dir` 时旧 `create_predictor()` 反而 `sys.exit(0)`，属于错误码假成功风险。 |

**模型注册结论**：v3 的公共层只做别名/参数到 PaddleX 配置的映射，v2 才在本仓库内按 YAML 类名构造网络；MCP 是协议层的模型/provider 白名单。三者分别拥有模型身份、网络构造和服务组合，不能把一个注册表当成全仓库统一注册中心。

### 20.2 图像预处理与检测—方向—识别的真实链路

#### v3：本仓库只配置阶段，不实现算子

`PaddleOCR.__init__` 把模型名、目录、开关、阈值、输入形状和 batch size 收入 `_params`；`_get_paddlex_config_overrides()` 生成点路径配置，例如 `SubPipelines.DocPreprocessor.SubModules.DocUnwarping.*`、`SubModules.TextDetection.*`、`SubModules.TextLineOrientation.*` 和 `SubModules.TextRecognition.*`。`use_doc_preprocessor` 由“整页方向分类或去畸变任一显式启用”推导，调用时还可用同名运行参数覆盖。随后基类加载默认/路径/对象配置，递归 `_merge_dicts()`，调用 `paddlex.create_pipeline(config=..., device=...)`。

```text
输入 image/PDF/路径/URL
  → PaddleX DocPreprocessor（可选整页方向分类、去畸变）
  → PaddleX TextDetection（限边、阈值、DB 等外部后处理）
  → 检测框裁剪（外部 pipeline）
  → PaddleX TextLineOrientation（可选，batch_size 独立）
  → PaddleX TextRecognition（batch_size 独立、score_thresh/word box）
  → PaddleX 结果字典（本仓库只迭代/列表化返回）
```

证据：`paddleocr/_pipelines/ocr.py:129-173,179-237,247-316`、`_pipelines/base.py:54-109`。因此不能从当前 checkout 断言 v3 的 resize、颜色通道、归一化、检测后处理具体实现；这些属于锁定的 PaddleX 版本和模型配置，必须在外部依赖源码/真实运行中复核。

#### v2：预处理算子和坐标回映射在本仓库

1. **检测输入**：`TextDetector` 组合 `DetResizeForTest → NormalizeImage → ToCHWImage → KeepKeys(image, shape)`；DB 默认均值 `[0.485,0.456,0.406]`、标准差 `[0.229,0.224,0.225]`、`1/255`、HWC 归一化，DB++ 使用另一组均值/标准差。`DetResizeForTest` 对极小图先补到至少 `32×32`，按 `limit_type=max/min/resize_long` 缩放，默认将尺寸对齐到 32 的倍数并记录 `[src_h,src_w,ratio_h,ratio_w]`；固定 `image_shape`、SAST/FCE/CT 走不同 resize 分支。
2. **检测推理与后处理**：预处理结果扩成 batch 1；Paddle Inference 从 CPU 拷贝输入、运行、逐输出拷回 CPU（ONNX 则通过 session）；按 DB/EAST/SAST/PSE/FCE/CT 组装 `preds`，交给对应 `build_post_process`，再把框按源图尺寸 clip；四边形过滤宽高≤3的框，polygon 只 clip 并补齐点数。
3. **框裁剪**：`TextSystem` 对框按 `(y,x)` 排序，再对相邻首点 y 差小于 10 的框按 x 做局部冒泡调整；quad 用透视旋转裁剪，其他类型用 `minAreaRect` 后再裁剪。`get_rotate_crop_image()` 使用 `warpPerspective`，边界复制；裁剪结果高宽比过窄时旋转 90°。
4. **行方向**：若 `use_angle_cls`，按宽高比排序、以 `cls_batch_num` 分批 resize 到 `cls_image_shape`，按 `[-1,1]` 归一化并零填充；`ClsPostProcess` 产生 label/score，只有 label 含 `180` 且分数超过 `cls_thresh` 才执行 `cv2.rotate(..., 1)`。源码没有在这里证明标签“180”与 OpenCV 旋转码的语义一致，应作为兼容性验收点。
5. **识别输入/输出**：按宽高比排序后以 `rec_batch_num` 分批；标准分支等比缩放到 `rec_image_shape` 高度、按宽度上限截断、CHW、`/255` 后 `-0.5/0.5`，右侧零填充；NRTR/ViTSTR/RFL/LaTeX 等算法另走灰度、固定尺寸、mask/额外输入或专用归一化。推理后按 CTC/Attn/SRN/SAR/NRTR 等 `postprocess` 解码，再用原始索引恢复顺序；CTC 可附带 `return_word_box`。
6. **总链路**：识别结果与框 zip，按 `drop_score` 过滤，输出只保留通过阈值的框/文字/分数；`TextSystem` 保留整张图的所有 crop，因此识别框超过 1000 时只打印内存/耗时警告，没有硬限流。

证据：`tools/infer/predict_det.py:57-163,244-308`、`ppocr/data/imaug/operators.py:72-134,208-347`、`tools/infer/predict_system.py:76-157,160-182`、`tools/infer/predict_cls.py:67-137`、`tools/infer/predict_rec.py:208-261,583-861`、`tools/infer/utility.py:880-932`。

### 20.3 GPU/CPU、推理引擎和批处理边界

| 入口 | 设备解析与引擎 | 批处理/并发实际语义 | 释放/风险 |
|---|---|---|---|
| v3 pipeline/wrapper | `parse_common_args()` 默认 `device=None`，实际交给 `paddlex.utils.device.get_default_device()`；`parse_device()` 得到 device type。支持 `paddle/paddle_static/paddle_dynamic/transformers/onnxruntime`，GPU 可组装 TensorRT fp32/fp16；CPU 可启用 MKL-DNN（默认 cache capacity 10、默认线程 10），也可启用 CINN/HPI | OCR pipeline 的显式 batch 配置只映射到行方向和识别子模块；`predict_iter()` 保持外部 pipeline 迭代，`predict()` 立即 `list()` 物化全部结果；单模型 wrapper 同样把 predictor 结果 `list()` 化 | `PaddleXPipelineWrapper.close()`/`PaddleXPredictorWrapper.close()` 只负责调用外部对象。`device` 成功传入不等于设备/显存释放已证实。证据：`_common_args.py:29-124`、`_models/base.py:53-82`。 |
| v2 Python Inference | `create_predictor()` 可走 CUDA GPU、CPU、XPU、NPU、MLU、MetaX、GCU；ONNX 路径按显式 providers、CUDAExecutionProvider 或 CPUExecutionProvider 创建 session。CUDA/HIP 可见卡由 `CUDA_VISIBLE_DEVICES`/`HIP_VISIBLE_DEVICES` 读取，但最终 GPU 配置使用 `args.gpu_id` | detector 单图 batch=1；recognizer 默认 `rec_batch_num=6`，classifier 默认 `cls_batch_num=6`；recognizer/classifier 按宽高比排序后批处理，再通过索引恢复原顺序。多进程是入口级分片，不是同一个 predictor 内部并发 | GPU 路径设置显存、TensorRT workspace、dynamic shape cache；CPU 关闭 GPU、可启用 MKL-DNN、设置线程数并打开 memory optimization。只有 classifier 在每批后调用 `predictor.try_shrink_memory()`；det/rec 没有对应收缩动作。证据：`tools/infer/utility.py:177-438,564-581`、`tools/infer/utility.py:1033-1038`。 |
| MCP local | `--device`/`PADDLEOCR_MCP_DEVICE` 透传 v3 wrapper；`LocalSyncRunner` 建一个 Thread + FIFO Queue，把同步 `predict` 桥到 asyncio | 每个 local inference 只有一个 worker，队列无最大长度、无批量聚合和背压；多个 MCP 请求顺序执行。它不是 GPU 多卡并行服务 | `stop()` 只给 runner 投递 sentinel 并 join，没有调用 `_inference.close()`；这是模型/显存资源释放的 P0 缺口。证据：`inference/shared/local_sync_runner.py:21-59`、`inference/ocr/local.py:70-98`、`pp_structurev3/local.py:43-72`。 |
| 旧 CLI/并行入口 | `tools/infer/predict_system.py` 通过 `process_id :: total_process_num` 做文件分片；可选 slice 对超长图切块并合并框 | slice 每个方向有 `maximum_slices=500` 防止切片数过大；但 `TextSystem` 的 slice 分支在所有切片均无框时直接 `np.concatenate(dt_slice_boxes)`，源码没有空列表兜底 | `warmup` 只执行随机图；无独立退出清理钩子，通常依赖进程退出。证据：`predict_system.py:76-109,185-225`、`tools/infer/utility.py:935-973`。 |

**设备结论**：v3 设备/引擎是 PaddleX 初始化参数，v2 设备/推理器配置在本仓库；MCP 的 async 只是同步模型的调度桥。GPU OOM、模型缓存、MKL-DNN cache、TensorRT cache 和线程退出不能仅由 `device`/`close()` 名称推导为已治理。

### 20.4 服务入口、失败路径和资源释放收口

| 场景/资源 | 源码动作 | 已确认的失败语义 | 未被源码保证的事项 |
|---|---|---|---|
| Python v3 CLI | `pyproject.toml` 注册 `paddleocr = paddleocr.__main__:console_entry`；`perform_simple_inference()` 先构造 wrapper，`try` 中消费 `predict_iter()`，`finally` 调 `wrapper.close()` | 参数/构造/推理异常向上传播；wrapper 构造成功后 CLI 正常和异常都进入 close | 构造函数在完成外部资源创建前失败时没有独立 owner；PaddleX 内部关闭细节不在仓库 |
| v2 `tools/infer/*.py` | `program.preprocess()` 建设备/推理器；各入口加载模型、构造 operators、`model.eval()`/predictor.run；通常写结果文件 | 找不到模型路径在 `create_predictor()` 中 `sys.exit(0)`；未知 detector algorithm 也 `sys.exit(0)`；某些 resize 异常打印后 `sys.exit(0)`，均可能把失败报告为退出码 0 | 这些脚本没有统一 `try/finally` 关闭 predictor；长驻进程不能把“脚本结束”当作可复用服务的显式释放证明 |
| MCP 启动/服务 | `_validate_args()` 先校验 host/port、token、api key、base URL；`resolve_model()` 校验模型；`inference.start()` 后注册 FastMCP tool；`finally` 调 `await inference.stop()`；HTTP 为 streamable-http，默认 `127.0.0.1:8000` | 参数错误 exit 2；启动/运行异常 exit 1；`mask_error_details=True` 隐藏 FastMCP 内部细节；`start()` 失败仍会进入 finally | `create_inference()` 在进入 try 前执行；宿主 SIGKILL/崩溃不经过 finally；HTTP 客户端关闭不等于远端作业取消 |
| MCP local 模型 | `start()` 构造 `PaddleOCR`/`PPStructureV3`，再创建 `LocalSyncRunner`；输入 `with input_adapter.prepare(...)` 后调用 runner | 输入准备和 worker 异常可沿 Future 回传；输入临时文件的 context 结束会清理 | `stop()` 关闭 runner 后将 `_wrapper=None`，但没有清空 `_inference` 或调用 wrapper `close()`；close 与 call 并发、Future 已取消时 worker 仍无状态协调；构造 runner 失败时已创建的 inference 没有补偿 close |
| MCP 外部 provider/API | AI Studio 为 async job submit→poll→fetch JSONL；HTTP provider 持有 async client；Task 只做输入归一化和结果展示 | 401/429/503、网络超时、job failed、未知状态、缺结果 URL、坏 JSONL 分层报错；poll timeout 不自动 cancel | 当前 API client 没有服务端 cancel；提交请求超时重试可能产生重复 job；远端 job/预签名 URL 生命周期不由客户端拥有 |
| v2/ONNX/Paddle Inference predictor | `create_predictor()` 建 session/config/predictor；输入 copy、run、输出 copy 到 CPU；TensorRT 可写 `.cache/trt` 或 dynamic shape 文件 | 文件缺失/配置非法抛 `ValueError` 或提前退出；设备不可用有时只 warning 后继续初始化 | 本仓库推理脚本没有统一 predictor `close()`/显存归还契约；ONNX session 和 TensorRT cache 的释放依赖进程/运行时 |
| 结果/输出文件 | v2 入口创建输出目录并写 `det_results.txt`/识别结果/可视化；v3 API 资源保存使用临时文件再 `os.replace`/link | 单文件临时写失败会清临时文件；批量资源中途失败保留之前已完成文件 | 无批量事务回滚；强杀时临时文件、半成品、显存和线程残留没有现场核验 |

### 20.5 失败矩阵与后续验收重点

| 失败/边界 | 静态结论 | 不能宣称的能力 | 后续应如何验收 |
|---|---|---|---|
| 模型名、语言、版本或 provider 组合非法 | v3 `ValueError`，MCP `resolve_model`/factory 拒绝，v2 `inference.yml` allowlist 拒绝 | 不能宣称任意模型名可自动下载/任意 provider 可用 | 对白名单外模型、显式目录与 `lang` 冲突、Qianfan OCR 组合断言错误类型/exit 2，且确认没有创建 predictor |
| 输入为空、极小、坏图、相对路径 | v2 transform 可返回 `None`；检测极小图补边；MCP 本地输入契约另行拒绝相对路径；旧 slice 全空有 `concatenate` 风险 | 不能宣称所有空输入都会稳定返回空结果 | 构造空文件、损坏图、极小图、所有 slice 无框，检查 provider 调用次数、错误码和临时文件 |
| GPU 不可用/OOM/CPU 降级 | v2 `check_gpu()` 可把 use_gpu 置 false，但 `create_predictor()` 路径也可能只 warning；v3 设备判断在 PaddleX | 不能把“声明 GPU”当作 GPU 实际执行或 OOM 可恢复 | 在无 GPU、显存不足、CPU/MKLDNN、TensorRT fp16/fp32 环境分别读回实际设备、峰值显存、线程和退出码 |
| worker 异常、Future 取消、stop 并发 | worker 把异常 set 到 Future，close 仅 sentinel+join | 不能宣称请求取消会终止推理或后续请求一定可用 | 注入阻塞/异常函数，取消 await，再 stop；检查 Future 状态、线程数、队列、第二次调用和重复 stop |
| 轮询超时/客户端断连 | Poller 抛 `PollTimeoutError`，源码无远端 cancel | 不能把 timeout/cancel 写成远端 job 已停止 | 记录 remote job id，超时后查询远端状态；提交请求重试必须用自有幂等键并核对 job 数 |
| 结果批量落盘失败 | 单文件原子，批量非事务 | 不能宣称全量成功或自动回滚 | 注入第 N 个资源失败，核对已写文件清单、临时文件和重复运行覆盖策略 |
| 正常退出与强杀 | Python CLI/MCP 的 `finally` 覆盖正常异常控制流；SIGKILL 不执行 | 不能以 finally 证明崩溃清理、显存归还、远端任务取消 | 对本地 MCP/v2 服务做 SIGTERM/SIGKILL，现场读回 PID/线程/端口/临时目录/缓存/远端任务 |

### 20.6 后续收口裁决

- **吸收为项目事实**：v3 的语言/版本模型别名选择、点路径配置覆盖、方向—检测—行方向—识别阶段开关；v2 的 YAML builder、检测 resize/归一化/坐标回映射、裁剪、方向旋转、识别按宽高比排序分批和结果复原；MCP 的模型→工具→provider 双层注册；设备/引擎参数的分层与旧 CLI 的失败码风险。
- **明确隔离**：v3 具体预处理算子属于 PaddleX；v2 `ppocr` 训练网络 builder 与 v3 pipeline 不是同一模型注册系统；MCP `InferenceFactory` 只拥有服务组合，不拥有公共 OCR 领域模型；ONNX/TensorRT/CUDA/CPU 的真实可用性必须按运行环境验证。
- **P0 保留**：MCP local `stop()` 没有显式关闭 `PaddleOCR`/`PPStructureV3` wrapper；超时/取消没有远端 cancel；v2 缺模型/未知算法等路径使用 `sys.exit(0)`；这些都不能被正常路径绿色掩盖。
- **P1 保留**：`LocalSyncRunner` 无界队列和取消/关闭竞态；`TextSystem` 全量持有 crop；slice 全空时 `np.concatenate`；recognizer/classifier 有批处理而 detector 默认单图；v2 predictor/session 没有统一服务级 close；批量资源非事务。
- **验证等级**：本节补充完成 L0 静态证据；未安装依赖、未加载权重、未执行 L1 单测、未做 L2 mock、未运行 L3 本地/远端推理，也未执行 L4 OOM/取消/SIGKILL/残留扫描。上述问题只能记为源码风险和验收项，不能记为已修复。

### 20.7 当前核对证据索引

| 主题 | 关键源码路径 |
|---|---|
| v3 模型选择与 OCR 配置 | `paddleocr/_pipelines/ocr.py:44-62,97-173,247-422` |
| v3 pipeline/predictor 资源边界 | `paddleocr/_pipelines/base.py:54-109`、`paddleocr/_models/base.py:30-82` |
| v3 设备/引擎 | `paddleocr/_common_args.py:29-188`、`paddleocr/_constants.py:15-22` |
| v2 网络/后处理 builder | `ppocr/modeling/architectures/__init__.py:27-35`、`base_model.py:27-117`、`ppocr/modeling/backbones/__init__.py:18-156`、`ppocr/postprocess/__init__.py:66-121` |
| v2 检测/方向/识别 | `tools/infer/predict_det.py:36-163,244-411`、`predict_cls.py:38-137`、`predict_rec.py:39-69,208-261,583-861`、`predict_system.py:48-182` |
| v2 预处理/切片/设备 | `ppocr/data/imaug/__init__.py:68-96`、`operators.py:72-134,208-347`、`tools/infer/utility.py:177-438,935-1038` |
| MCP 入口/注册/本地桥 | `mcp_server/paddleocr_mcp/__main__.py:144-274`、`selection.py:20-77`、`inference/factory.py:32-200`、`inference/shared/local_sync_runner.py:21-59`、`inference/ocr/local.py:25-131` |

**后续收口结论**：PaddleOCR 不是“一个模型注册表 + 一条固定预处理链”。v3 是 PaddleX 外部内核的配置/生命周期薄壳，v2 是 YAML 类名驱动的过程式推理线，MCP 是模型/provider 服务组合层；三条线的预处理、批处理、设备和释放责任不同。当前最需要在真实环境补证的是 local wrapper 关闭、取消/超时语义、GPU/CPU 实际设备与内存、空切片/假成功退出码，以及长驻服务的队列和 predictor 资源治理。

## 21. 后续：OCR 通用能力映射总表

本节把前两轮的分散事实压缩为可装配的通用 OCR 能力矩阵。它只描述当前 PaddleOCR 源码能够证明的边界，并明确哪些行为属于外部 PaddleX、运行环境或真实服务，避免把 v2、v3、MCP 三条线拼成一条不存在的实现。映射目标是“一个平台契约、多个 provider”，不是把 PaddleOCR 的内部参数原样暴露为公共 API。

### 21.1 预处理能力映射

| 能力阶段 | v3 `paddleocr/` | v2 `tools/infer/`/`ppocr/` | 通用 OCR owner 与映射 | 证据边界 |
|---|---|---|---|---|
| 输入解码与页面枚举 | wrapper 把 image/PDF/路径等交给 PaddleX；MCP adapter 另做 URL、Base64、data URL 和临时文件归一化 | `check_and_read()` 读取图片/GIF/PDF，PDF 按页展开 | 输入支持库负责来源、媒体类型、页范围和摘要；模块只消费规范化页面 | v3 解码算子不在 checkout；v2 对坏图可跳过，不能推导统一空结果语义 |
| 整页方向与去畸变 | `DocPreprocessor` 可选，`use_doc_preprocessor` 由两个开关推导 | 传统链路不等同于 v3 DocPreprocessor | OCR 模块公开为可选预处理阶段，provider 负责模型参数 | PaddleX 执行具体算子；当前源码只证明点路径和开关映射 |
| 检测 resize/归一化 | 只传 `limit_side_len/type/input_shape` 等配置 | `DetResizeForTest → NormalizeImage → ToCHWImage → KeepKeys`，记录源尺寸与比例 | 预处理支持库统一输入尺寸、颜色、归一化和坐标回映射接口；算法分支留在 provider | v2 具体均值、32 倍数对齐和小图补边可复用；v3 不应假定相同 |
| 裁剪与几何变换 | 由外部 pipeline 生成识别输入 | quad 透视裁剪，其他框走最小外接矩形，窄图可旋转 | OCR 模块只拥有“检测框到文本块”的语义；几何实现属于检测/图像支持库 | crop 列表可能完整保存在内存，暂无统一上限 |
| 方向分类预处理 | 行方向模型可选，batch 独立 | `cls_image_shape`、归一化、零填充，满足条件才旋转 180° | 作为文本行方向可选阶段，输出必须保留变换诊断 | v2 标签语义与 OpenCV 旋转码需回归，不能只看字段名 |
| 识别预处理 | `text_rec_input_shape` 和识别 batch 透传 PaddleX | 按宽高比排序、等比缩放、CHW、归一化、右侧填充；特殊算法有独立分支 | 识别 provider 输出原始顺序索引，统一转换器负责恢复顺序 | v3 的 resize/颜色/归一化属于锁定 PaddleX 版本 |

**预处理裁决**：公共契约只冻结页面、图像引用、坐标系、阶段开关和诊断，不冻结 PaddleX 点路径或 v2 算子名称。任何 provider 必须返回“输入尺寸→处理尺寸→输出坐标”的可追溯信息；无法提供时标记诊断缺失，而不是猜测坐标已正确回映。

### 21.2 检测—识别能力映射

```text
页面输入
  → 可选整页方向/去畸变
  → 文本检测（quad 或 polygon）
  → 框排序与裁剪
  → 可选文本行方向分类
  → 文本识别与解码
  → 置信度阈值过滤
  → 统一文本块/页面结果
```

| 子能力 | 当前源码行为 | 通用输出 | 失败/降级语义 |
|---|---|---|---|
| 检测 | v3 配置 DB 类阈值和边界参数后交给 PaddleX；v2 按 DB/EAST/SAST/PSE/FCE/CT 选择后处理并 clip 框 | `文本块.geometry`、检测分数、来源阶段 | 无框应是合法“空页面”或明确 `no_detection`，不能由 provider 自行混入错误文本 |
| 排序与框裁剪 | v2 先按 `(y,x)` 排序，同一行近邻再局部交换；quad 透视裁剪 | `文本块.order` 和 `source_bbox` | 排序是阅读顺序启发式，不等于文档阅读顺序；复杂版面交给文档模块 |
| 文本行方向 | v3 可独立开关和 batch；v2 仅特定 label/score 触发旋转 | `文本块.orientation`、变换诊断 | 分类失败应保留原框并记录阶段失败/降级，不能静默篡改原图 |
| 识别与解码 | v3 返回 PaddleX 结果字典；v2 支持 CTC/Attention/SRN/SAR/NRTR 等后处理，按索引恢复 | `文本块.text`、识别分数、可选 word box | 识别结果数量与框不一致必须失败或逐块标记，禁止 zip 截断后假成功 |
| 置信度过滤 | v3 `text_rec_score_thresh` 传给 pipeline；v2 `drop_score` 在检测框与识别结果配对后过滤 | 过滤前后计数和阈值诊断 | 展示层不得把平均置信度拼进事实文本；MCP 的 `Confidence: ...` 仅为投影 |
| 版面与结构 | PP-StructureV3/传统 `StructureSystem` 组合版面、表格、公式等 | 统一 `页面/块/表格/资源` | 结构失败不得退化成“纯 OCR 成功”而丢失失败诊断；需标记局部降级 |

### 21.3 模型、设备与批处理矩阵

| 维度 | v3 pipeline/模型 wrapper | v2 推理线 | 服务/平台映射 |
|---|---|---|---|
| 模型身份 | `lang + ocr_version` 选择 det/rec 别名；显式 model name/dir 优先，冲突时 warning | `inference.yml` 的 `Global.model_name` 与算法/后处理配置驱动 | 项目适配层登记稳定 `model_id/version`；provider 转换为实际目录、点路径和配置 |
| 设备 | `device`、HPI、PaddleX 后端参数；实际设备由外部内核解析 | GPU、CPU、XPU、NPU、MLU、MetaX、GCU、ONNX Runtime；GPU id 受可见设备环境影响 | 运行核心登记设备 lease、峰值显存和实际后端；请求字段本身不是执行证明 |
| 精度/引擎 | PaddleX 可承接 Paddle、静态/动态图、ONNX Runtime、TensorRT、MKL-DNN 等 | Paddle Inference/ONNX；TensorRT 需要 dynamic shape 或缓存配置 | 模型制品支持库管理缓存/校验；运行核心管理加载、卸载和隔离进程 |
| 检测批 | v3 未在 wrapper 层承诺 detector batch | `TextDetector` 默认单图 batch=1 | 公共能力不得承诺端到端 batch；provider 声明真实批语义 |
| 方向批 | `textline_orientation_batch_size` 独立映射 | `cls_batch_num`，按宽高比/resize 分批 | 运行核心限制单任务 batch 和队列等待，记录实际 batch |
| 识别批 | `text_recognition_batch_size` 独立映射 | `rec_batch_num` 默认 6，按宽高比分批并恢复原序 | 批大小是 provider 参数；输出转换器必须保持输入框顺序 |
| 请求并发 | `predict_iter()` 可迭代，`predict()` 物化 list | 多进程入口按文件分片，不是 predictor 内并发 | 运行核心负责并发、背压、队列上限和设备租约；禁止 provider 私建无界任务队列 |
| MCP local | 一个 `LocalSyncRunner` 线程和无界 FIFO，顺序执行 | 不适用 | 只能作为同步桥；平台必须补有界队列、取消、超时和 worker 状态 |

### 21.4 服务入口与输出映射

| 服务/入口 | 当前实现 | 通用底座装配 | 输出裁决 |
|---|---|---|---|
| Python v3 API/CLI | wrapper 构造 PaddleX，`predict_iter()` 迭代，CLI finally close | 项目适配层/同步调用适配器 | 统一文档结果；CLI 文本、JSON、可视化仅是投影 |
| v2 CLI/训练推理 | `tools/infer` 直接创建 predictor，文件分片、逐图/逐页写结果 | 兼容 provider 隔离层，不进入公共核心 | `det_results.txt`、可视化图片和日志不是平台事实模型 |
| MCP local | `InferenceFactory → LocalSyncRunner → Task`；默认 stdio | MCP 只翻译网关契约；local runner 由运行核心托管 | `simple/detailed` 为展示投影；不得把 `TextContent` 当领域输出 |
| MCP HTTP | streamable HTTP 默认回环 `127.0.0.1:8000`，参数/凭据先校验 | 网关负责鉴权、任务 id、状态和取消 | HTTP 响应应返回统一任务/结果引用，不以一次 tool call 隐藏长任务 |
| AI Studio/Qianfan/self-hosted | 远端 HTTP/异步 job、轮询、JSONL 或 provider 特定 JSON | provider 提供 submit/query/fetch/可选 cancel 原子能力 | `done` 只有结果下载、摘要校验和转换成功才是平台 succeeded |
| 输出资源 | API 资源单文件临时写后 `os.replace`/link；批量失败不回滚 | 资源支持库登记 URL、摘要、目标和批次补偿 | 原始 JSONL、图片、Markdown/DOCX 均是资源引用/投影；不能内嵌不受控大二进制 |

统一输出最小契约：`schema_version`、`source`、有序 `pages`、`blocks`、`diagnostics` 和 `resources`。纯文本、MCP simple、Markdown、HTML、可视化图像都从该契约投影，不能反向成为跨 provider 的事实源。

### 21.5 资源生命周期映射

| 资源 | 创建 owner | 正常释放 | 异常/强杀要求 | 当前缺口 |
|---|---|---|---|---|
| 模型/pipeline/predictor | provider 适配器通过运行核心创建 | wrapper/predictor `close()`，随后释放设备 lease | 失败、超时、取消、崩溃都要有 lease 状态和回收扫描 | MCP local stop 只关 runner，未显式关 wrapper |
| worker、线程、队列、Future | 运行核心 | 排空、sentinel、join；队列有界 | 取消中的任务不可再 set 已取消 Future；关闭必须幂等 | `LocalSyncRunner` 队列无界，取消/close 竞态未定义 |
| 输入临时文件 | 输入/文件支持库 | context finally 删除 | 强杀后由监督器扫描并清理 | 正常 finally 有证据，崩溃零残留未验证 |
| HTTP session/连接池 | provider 适配器 | provider `close/stop` | 超时和断连关闭 session；远端任务另行查询 | 客户端 close 不等于远端 job cancel |
| 结果临时文件与资源 | 资源支持库 | 原子替换后清临时文件 | 批次清单记录部分成功，补偿删除或续传 | 批量写入非事务，前置成功项不会自动回滚 |
| 远端 job/预签名 URL | 远端 provider | 客户端只查询/下载 | timeout 必须 reconcile；URL 过期应可解释失败 | 源码没有统一 cancel endpoint 或幂等保证 |

### 21.6 后续失败矩阵

| 失败场景 | 源码可确认语义 | 通用平台状态/可重试 | 验收必须证明 |
|---|---|---|---|
| 模型、语言或 provider 不支持 | v3 `ValueError`；MCP 白名单/组合校验；v2 allowlist | `invalid_request`，不可盲重试 | 不创建 predictor/inference；CLI/MCP 错误码符合契约 |
| 空、坏、极小或相对路径输入 | MCP 相对路径拒绝；v2 小图可补边，坏图可能跳过；slice 全空存在 concatenate 风险 | `invalid_input` 或明确 `no_detection`；不可统一吞错 | provider 调用次数、页级结果、临时文件和错误码 |
| 检测无框/识别空文本 | MCP 返回 “No text detected”；v2 可能返回空框列表 | 成功空结果或局部降级，必须携带诊断 | 不把空结果序列化成异常成功文本，也不丢页面信息 |
| CPU/GPU 不可用或 OOM | v2 部分路径 warning/降 CPU；v3 由 PaddleX 决定 | `device_unavailable`/`resource_exhausted`；仅在幂等时重试 | 实际设备、峰值显存、线程和模型 lease 读回 |
| worker 异常、Future 取消、stop 并发 | 异常传 Future；当前无完整取消协议 | `failed` 或 `cancellation_unconfirmed`，不可写 confirmed canceled | 后续请求、线程、队列、重复 stop 和模型 close |
| HTTP 401/400/429/503/断线 | SDK 分层异常；提交超时可能重复 job | 认证/请求错误不重试；限流/服务不可用按策略退避；提交重试需幂等 | 调用次数、退避、remote_job_id 和 session 释放 |
| 轮询超时/未知状态/缺结果 URL | `PollTimeoutError`、格式/状态错误；无服务端 cancel | `timed_out` 或 `cancellation_unconfirmed`，不得写 canceled | 超时后远端状态、任务是否继续消耗、结果 URL 过期处理 |
| 结果转换字段缺失/JSONL 损坏 | parser 抛 `ResponseFormatError`/`ResultParseError` | `provider_invalid_result`，不可把原文当正文 | 原始 payload 摘要、字段定位、统一 schema 校验 |
| 批量资源第 N 项失败 | 单文件原子；先前文件保留 | `partial_success`，允许从失败清单恢复 | 已写清单、临时文件、覆盖策略、补偿清理 |
| SIGTERM/SIGKILL/宿主崩溃 | finally 只覆盖正常控制流和可传播异常 | `crashed`/`recovery_required`；远端 job 单独 reconcile | PID/线程/端口/临时目录/显存 lease/远端任务现场读回 |

### 21.7 后续唯一归属与落地顺序

1. **通用 OCR 模块**：拥有“页面 OCR”的领域流程、阶段开关、文本块语义、顺序和置信度语义；不导入 PaddleOCR/PaddleX。
2. **通用文档模块**：拥有版面、表格、公式、图像、阅读顺序和统一文档结构；Markdown/HTML/DOCX 是投影或转换。
3. **支持库**：拥有输入归一化、预处理/坐标转换、provider payload、结果转换、模型制品和原子资源写入；不拥有平台任务状态。
4. **PaddleOCR provider 适配**：绑定 v3 点路径、v2 配置、模型白名单、四 provider endpoint、错误字段和外部版本；不复制 OCR 编排。
5. **运行核心**：唯一拥有 task id、幂等键、队列背压、deadline、轮询监督、取消确认、进程/线程、设备/显存和崩溃恢复。
6. **项目适配层**：只绑定项目模型别名、版本、凭据引用、endpoint 和权限；禁止把具体字符串散落到公共模块。
7. **MCP/API 适配器**：只做协议与展示翻译；`simple/detailed`、`TextContent/ImageContent`、CLI 输出和远端 SDK 类型不得进入公共契约。

落地顺序冻结为：统一文档/任务/错误契约 → 结果与输入转换支持库 → PaddleOCR 四 provider 适配 → 运行核心状态与资源租约 → MCP/API 协议适配 → L1-L4 故障注入验收。未完成前，不得以成功注册工具、mock 绿色或 `finally` 存在宣称设备释放、远端取消、崩溃安全或批量事务。

### 21.8 后续映射验收清单

| 验收层 | 当前核对要验证的通用映射 | 当前结论 |
|---|---|---|
| L0 静态 | 预处理阶段、检测/识别箭头、模型设备、batch、服务、输出、资源和失败矩阵 | **已完成**：基于当前 checkout 静态源码；v3 外部算子明确标记边界 |
| L1 契约 | 模型/provider 白名单、输入分类、统一 schema、错误映射、状态枚举 | **未执行**：未运行测试命令 |
| L2 集成 | provider→转换器→通用 OCR/文档模块、mock poller、批资源清单和释放 | **未执行**：不能以测试文件存在替代 |
| L3 真实 | local CPU/GPU、AI Studio/Qianfan/self-hosted、真实图片/PDF 输出 | **未执行**：未安装依赖、未下载权重、未启动服务 |
| L4 韧性 | OOM、取消、断线、重复提交、SIGKILL、残留和远端 job reconcile | **未执行**：仍是待建故障注入工作包 |

**后续结论**：PaddleOCR 可映射为“通用 OCR/文档模块 + PaddleOCR provider + 运行核心资源治理”的组合，但不能直接复用其 v3/v2/MCP 任一层作为平台公共核心。最关键的不可假绿边界是：v3 预处理由外部 PaddleX 执行、v2 设备/算子与 v3 不同、MCP local 是无界单线程同步桥、远端 timeout 没有 cancel 证明、批量资源没有事务、正常 finally 不覆盖强杀。上述事实仅完成 L0 静态映射，后续实现必须以 L1-L4 真实证据推进。

## 代码地图现状复核（2026-08-22）

文中“目标仓库没有 `.codegraph`”属于早期核对记录，现已过期。当前目标根 `/Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/20_vision_ocr_detection/PaddleOCR` 存在独立 `.codegraph/`；`codegraph status` 退出码为 0，返回 1,160 files、14,850 nodes、33,164 edges。此前错绑 MCP 证据仍不采纳，索引可用也不代表 L1-L4 运行验证完成。
