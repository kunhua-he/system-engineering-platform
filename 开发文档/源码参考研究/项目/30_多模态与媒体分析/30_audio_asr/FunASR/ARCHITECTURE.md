# FunASR 架构审计档案

> 本文件是当前源码快照的唯一架构事实汇总。审计对象：`/Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/30_audio_asr/FunASR`。
> 本轮只更新本文件；未修改源码、测试、配置、README、旧细探或运行时资产。

## 1. 审计边界与证据状态

- **项目**：FunASR，版本文件为 `funasr/version.txt` 的 `1.3.28`。
- **定位**：以 `AutoModel` 为主入口的语音工具包，覆盖离线 ASR、模型级流式 ASR、VAD、标点、说话人分离，以及 vLLM、WebSocket、HTTP、ONNX、Triton、gRPC、llama.cpp/GGUF 和移动端等部署路径。
- **代码与模型许可**：仓库代码声明 MIT；`MODEL_LICENSE` 对模型权重另行约束。不能用代码许可证替代 checkpoint 许可证审查。
- **构建事实**：`setup.py` 声明 `python_requires >=3.7`，`pyproject.toml` 仅声明 setuptools/wheel 构建后端；README 安装说明写的是 Python `>=3.8`，这是公开文档与包元数据的版本漂移。
- **依赖边界**：核心安装依赖包括 PyTorch 生态、librosa/soundfile、ModelScope/Hugging Face、OmegaConf/Hydra、tokenizer、WebSocket 与音频/说话人相关库；vLLM、FastAPI、uvicorn、python-multipart、ONNX/Triton/客户端运行时按路径额外安装。
- **CodeGraph**：已先尝试在目标根执行 `codegraph explore "FunASR architecture entry points, inference pipeline, resource lifecycle, failures, tests"`；目标目录没有 `.codegraph/`，工具明确返回 CodeGraph 不可用且未初始化索引。以下调用链全部来自目标仓库现场源码、测试、配置和文档，不能把 CodeGraph 证据冒充为本项目证据。
- **本轮执行边界**：未安装依赖、未下载模型、未启动 HTTP/WebSocket/vLLM/ONNX/Triton/GGUF 服务、未执行 GPU/CPU 模型推理、未做压力/取消/崩溃恢复实验。因此本文不宣称运行通过或性能达标。

## 2. 仓库结构与职责

```text
FunASR/
├── funasr/
│   ├── auto/                 AutoModel、AutoFrontend、AutoModelVLLM
│   ├── models/               ASR、VAD、标点、说话人、情感/事件及 LLM-ASR 模型
│   ├── frontends/            波形/特征前端
│   ├── datasets/             训练与数据集适配
│   ├── train_utils/          训练、权重加载、随机种子、设备工具
│   ├── utils/                音频装载、VAD/时间戳、后处理、导出与下载
│   ├── bin/                  CLI、Hydra、HTTP、实时 WebSocket、导出/训练入口
│   ├── register.py           类注册表
│   └── __init__.py           版本、子模块自动导入、延迟导出
├── runtime/                  WebSocket/HTTP/gRPC/Triton/ONNX/llama.cpp/移动端等
├── examples/                 OpenAI API、MCP、实时、模型和部署示例
├── tests/                    单元、契约、文档、服务辅助与轻量管线测试
├── tests_models/             依赖真实 checkpoint/音频/设备的模型测试
├── model_zoo/                模型清单与选择文档
├── docs/                     安装、部署、vLLM、排障、基准与社区文档
├── setup.py / pyproject.toml 包元数据与构建声明
└── README*.md                安装、示例、模型矩阵、部署和性能声明
```

`runtime/` 不是 `AutoModel` 的共享服务对象：各运行时拥有自己的模型格式、采样率约束、chunk/协议、设备后端和释放方式。不能从 Python 路径推断 ONNX、Triton、GGUF 或移动端具有相同语义。

## 3. 真实主链路

### 3.1 离线 Python 链路

```text
路径 / URL / bytes / numpy / batch
  -> prepare_data_iterator / load_audio_text_image_video
  -> AutoModel.generate
       ├─ 无 vad_model: inference
       │    -> batch 切分 -> model.inference -> 结果
       │    -> 可选 punc_model -> 文本标点
       └─ 有 vad_model: inference_with_vad
            -> VAD inference
            -> 可选 merge_vad
            -> 音频读取、按 VAD 区间排序和动态批处理
            -> ASR inference
            -> 恢复原始顺序、偏移 timestamp
            -> 可选 punc_model / spk_model / speaker clustering
  -> postprocess_hotwords
  -> list[dict]
```

`AutoModel.__init__` 先构建主模型，再按配置独立构建 VAD、标点和说话人模型。`build_model` 下载或定位模型，读取 `config.yaml`，从注册表创建 tokenizer/frontend/model，加载 `init_param`，设置 dtype/device，最后 `eval()`。

输入可为本地路径、HTTP URL、numpy、bytes 或批量列表。URL 会进入下载路径；file list (`.scp/.txt/.json/.jsonl/.text`) 会被展开。未显式提供 key 时，部分输入使用文件名，其他输入生成随机 key，因此跨重试的结果幂等性不能由库保证。

### 3.2 流式 Python 模型链路

Paraformer streaming 的调用方维护 `cache`，按约 600 ms chunk 调 `generate(input=chunk, cache=cache, is_final=...)`。`cache` 是调用方拥有的会话状态，不是全局队列，也不是可恢复的持久 checkpoint。FSMN-VAD streaming 同样依赖 cache 和 chunk 边界。

### 3.3 vLLM 链路

`AutoModelVLLM` 解析本地目录或 ModelScope/Hugging Face snapshot，读取 `config.yaml`，只允许 LLM-ASR 架构进入 vLLM；Paraformer、SenseVoice、CT-Transformer、Conformer 和 Qwen3-ASR 明确不适用。Fun-ASR-Nano/GLM-ASR/LLMASR 等路径把音频 encoder/adaptor 留在 PyTorch，把连续 embedding prompt 交给 vLLM 解码，并可配置 dtype、tensor parallel、GPU 显存比例和最大序列长度。

`prepare_vllm_weights` 会创建输出目录、复制配置/分词器并从 `model.pt` 提取 `llm.*` 权重到 safetensors 或 `model.bin`。它有“已存在权重则复用”的路径，但没有跨文件事务、临时目录回滚或并发锁；中断时可能留下部分转换目录。

### 3.4 实时 WebSocket 链路

`realtime_ws.py` 的会话对象接收 PCM16 字节，转 float32 后追加到会话音频缓冲区；服务端 VAD 模式由 VAD 形成已确认段，客户端模式由 `COMMIT` 形成段。每个 chunk 可能触发 partial decode，确认段再次完整 decode，随后可做说话人聚类并返回 `sentences`、`partial`、时间和 `is_final`。

partial 窗口和 lookback 有界，音频压缩时复制保留区，避免 numpy 切片持有已丢弃的大 backing array。解码异常被记录并返回当前响应；完成段失败时会在满足覆盖范围/稳定性条件下采用最新 partial，否则交付空或已解码文本。这个补偿是会话内启发式，不等于持久化恢复。

### 3.5 HTTP 链路

仓库存在两套相似但不等价的 HTTP 实现：

1. `funasr-server` -> `funasr/bin/server.py` -> `_server_app.py`：默认设备参数为 `cuda`，`preload_model=auto` 时 GPU 选择 Fun-ASR-Nano、非 GPU 选择 SenseVoice；Fun-ASR-Nano 先尝试 vLLM，失败后缓存 `AutoModel` fallback。提供 `/v1/audio/transcriptions`、`/asr`、`/v1/models`、`/health`。
2. `examples/openai_api/server.py`：示例级 FastAPI，默认预加载 SenseVoice，`MODEL_REGISTRY` 按名称缓存 `AutoModel`；OpenAI 路径、`/v1/models` 和 `/health` 的响应字段与 `_server_app.py` 不完全相同。

两套实现都把上传内容先读入内存。`_server_app.py` 的 fallback 和示例服务器把内容写入 `NamedTemporaryFile(delete=False)`，通过 `finally` 删除；但没有请求体大小上限、磁盘配额、请求超时、取消 token、排队上限或鉴权。HTTP `async` handler 内直接执行推理，重模型调用可能阻塞事件循环。

## 4. 注册与动态装载

- `funasr.register.tables` 维护 model/frontend/tokenizer/encoder/decoder/predictor/dataset 等表，并记录类名、文件和行号元数据。
- `@tables.register` 对重复 key 是覆盖式重注册，只记 debug 日志，不拒绝冲突；导入顺序可影响最终实现。
- `funasr.__init__` 通过 `pkgutil.walk_packages` 自动导入子模块以触发装饰器。默认模式捕获异常、记录到 `_IMPORT_ERRORS` 后继续；`FUNASR_STRICT_IMPORT=1` 才在导入失败时抛出。
- `AutoModel.build_model` 在组件缺失时才失败，并把注册表摘要和导入错误拼入异常。因而默认导入成功不等于所有模型已注册。
- `AutoModel`/`AutoFrontend` 是延迟导出；没有 PyTorch 时顶层 `import funasr` 可成功，但访问 `AutoModel` 才给安装提示。这是有意的轻量导入语义，不能当作模型可用性探针。
- `trust_remote_code` 与 `remote_code` 允许 checkpoint 提供额外代码；模型来源、revision、代码内容和许可证必须在部署边界锁定。

## 5. 公开接口和契约风险

| 入口 | 正常结果 | 关键失败/资源语义 |
|---|---|---|
| `AutoModel(**kwargs)` | 持有主模型及可选子模型 | 下载、配置、注册、权重或设备失败直接抛出；不可用设备会回退 CPU 并把 batch 设为 1；没有统一 `close()` |
| `AutoModel.generate` | `list[dict]`，常见 `key/text/timestamp/sentence_info` | 无 VAD 是单段推理；有 VAD 是组合管线；部分结果/异常没有外部事务或 checkpoint |
| `AutoModelVLLM.generate` | LLM-ASR 结果列表 | 只适用声明的 LLM 架构；长输入只告警或受 `max_new_tokens` 截断；vLLM 异常不自动提供通用重试 |
| HTTP `/v1/audio/transcriptions` | JSON/text/verbose JSON，取决于实现和 `response_format` | 未知模型 400；解码/推理异常可能 500；两套 server 的默认模型、语言、segments 和 health 字段不同 |
| HTTP `/asr` | 文本、segments、duration、processing_time、rtf | 依赖 backend；`spk` 参数在部分路径未形成完整说话人结果；没有请求取消/队列 |
| WebSocket realtime | partial/final sentences 和会话统计 | 解码错误返回 partial 响应并继续；连接生命周期、并发和会话回收由服务宿主负责 |
| CLI `funasr` / `funasr-server` | 文件转写、JSON/SRT 或服务 | CLI 只是调用入口；端口、模型下载、设备和依赖错误在启动/请求期暴露 |
| `download_model` / snapshot | 本地模型目录 | hub 网络、revision、鉴权和部分下载失败没有统一事务回滚；缓存由外部 hub 语义决定 |

结果字典不是跨模型严格 schema：有的模型给 `timestamp`，LLM-ASR 可能先给 `timestamps`，标点/说话人/语言/情感字段也随模型变化。HTTP 适配层会清理特殊标签、补粗粒度 segments 或转换时间单位，因此不能把 HTTP 响应反推为 Python 原始结果。

## 6. 资源、并发和所有权审计

| 资源/状态 | 所有者与正常释放 | 失败/取消/崩溃风险 |
|---|---|---|
| 模型、VAD、标点、说话人实例 | `AutoModel`、服务 `app.state`、模块全局或 registry 长期持有 | 无统一卸载、优雅 shutdown 或显存释放协议；依赖进程退出/GC，模型缓存数量没有库级上限 |
| Hub/model cache | ModelScope/Hugging Face 和调用方 | revision/cache 完整性和清理不是 FunASR 事务；下载中断或远程代码漂移需宿主审计 |
| HTTP 上传 bytes | 请求函数内存 | 没有上传大小上限；大文件先完整读入内存。临时文件正常/异常路径有 `finally` 删除，但 unlink 失败没有专门处理 |
| WebSocket audio buffer | 单会话 `RealtimeSession` | lookback/partial 窗口有限且有显式释放；异常断连是否调用 reset/release 取决于外围连接处理，不能由会话类本身保证 |
| streaming cache | 调用方按会话持有 | 不是持久 checkpoint；丢连接、进程重启或乱序 chunk 后不能自动恢复 |
| vLLM KV/cache 与 PyTorch tensors | vLLM/torch 引擎 | 请求级超时和取消由服务层补齐；GPU OOM、驱动异常或 worker 崩溃没有统一重建协议 |
| progress/logging | `tqdm`、标准 logging | 部分循环路径有进度更新，但异常时不能把日志或 progress 当作完成证据 |
| vLLM 权重转换目录 | `prepare_vllm_weights` | `os.makedirs`、复制和写权重不是原子事务；并发调用可能互相看到半成品 |

源码没有统一全局任务队列、优先级、背压、请求 id、幂等键、结果持久化或取消令牌。动态 batch 是推理内部的批处理，不是服务级排队。生产封装必须在外层提供有界 worker/进程、上传配额、超时 kill/reap、GPU 隔离、临时目录回收、结果原子写入和重启恢复。

## 7. 失败矩阵

| 场景 | 当前行为 | 自动恢复 | 接入方必须补齐 |
|---|---|---|---|
| 可选依赖导入失败 | 默认记录后继续，后续组件构建时失败；严格模式启动即失败 | 否 | 启动期检查 `get_import_errors()`，生产环境使用 strict import |
| 注册 key 缺失/重复 | 缺失构建时报错；重复覆盖 | 否 | 记录注册表快照，重复键 fail-fast |
| hub 网络/鉴权/revision/模型文件失败 | 异常上抛，缓存语义由 hub 决定 | 否 | 预热、锁 revision/hash、退避和失败状态 |
| `trust_remote_code` 代码或配置不兼容 | 载入/构建异常 | 否 | 代码白名单、供应链扫描、禁止隐式远程漂移 |
| 指定设备不可用 | 回退 CPU，batch 置 1 | 仅设备降级 | 健康检查必须返回实际 device/backend，避免静默降级 |
| 无 VAD 的长音频 | 受模型上下文/显存限制，可能失败或截断 | 否 | 强制 VAD/切片并检查覆盖率 |
| VAD 无语音 | 组合管线可返回空文本/空 timestamp | 否 | 区分“无语音”和“推理失败” |
| vLLM 初始化失败 | `_server_app` 尝试 AutoModel fallback；其他入口直接失败 | 仅统一 server 的特定路径 | 限制 fallback 次数，清理半初始化 engine，记录实际 backend |
| vLLM 超长输入 | 可能受最大 token/`max_new_tokens` 截断，通常只 warning | 否 | 输入时长上限、VAD 分段、输出覆盖率门禁 |
| ASR/align/后处理异常 | Python 入口抛出；实时路径记录并返回当前 partial | 否 | 错误分类、请求状态、重试边界和隔离 worker |
| HTTP 请求过大/并发过高 | 先读入内存，可能阻塞事件循环或耗尽内存 | 否 | body/file 限制、有界队列、超时、取消、鉴权和背压 |
| 实时客户端断开/进程崩溃 | 未持久化 partial 丢失；会话回收依赖外围 finally | 否 | 连接清理、会话 TTL、状态指标、重启后重新送入 |
| 部分结果后失败 | 调用方已看到前缀，库不回滚也不标记 committed | 否 | 每段原子保存，完成只能由消费结束产生 |
| 文档/示例 API 漂移 | 不同入口可启动但参数、默认模型、响应字段不同 | 否 | 选定唯一服务入口并对 README/docs/examples 做契约测试 |

## 8. 测试与文档一致性

### 8.1 测试分层

- `tests/test_auto_model.py` 覆盖注册失败报告、strict import、progress callback 和部分 AutoModel 构造；部分用例会下载模型。
- `tests/test_asr_vad_punc_inference_pipeline.py`、`tests/test_vad_inference_pipeline.py` 通过 ModelScope pipeline 和公开音频 URL 做真实 VAD/ASR 断言，依赖网络、checkpoint、设备和外部服务。
- `tests/test_fsmn_vad_streaming_buffers.py`、`test_dynamic_streaming_vad.py`、`test_fsmn_vad_dynamic_silence.py` 等覆盖流式 buffer、VAD 边界和动态静音。
- `tests/test_cli.py`、`test_generate_subtitle.py`、`test_punc_model_none.py`、`test_postprocess_hotwords.py` 覆盖 CLI/字幕/后处理契约。
- `tests/test_realtime_ws_benchmark.py` 主要用 mock 消息和时间验证 benchmark 统计，不证明真实 WebSocket、vLLM 或多客户端压力通过。
- `tests_models/` 覆盖 SenseVoice、Paraformer、streaming、FSMN-VAD、CAMPPlus、GLM/Qwen 等模型，但属于重依赖真实模型测试。
- CI 文件当前没有传统单一 `ci.yml`；可见 workflow 分散在发布、ONNX、llama.cpp 下载、文档 API 更新等任务，不能据此推断本地完整测试已通过。

### 8.2 文档重复与冲突

1. `README.md`、`docs/vllm_guide*.md`、`vllm_guide_zh_v2.md`、博客和模型选择文档重复描述安装、端口、模型和 RTFx；性能数字应统一链接 `docs/benchmark/rtf_reproducibility.md`，保留测试集、硬件、计时范围和 CER 版本。
2. `README.md`/`docs` 把 `funasr-server` 当成单一 OpenAI-compatible 服务，但源码存在 `funasr/bin/_server_app.py` 与 `examples/openai_api/server.py` 两套实现，默认模型（自动选择 Fun-ASR-Nano/SenseVoice 与示例默认 SenseVoice）、`verbose_json`、health 和 fallback 行为不一致。
3. `setup.py` 的 Python `>=3.7` 与 README/FAQ 的 `>=3.8` 冲突；应以实际支持矩阵和 CI 证据为准，不能只改文案。
4. README 的 `340x/17x` 和 vLLM 指南的 `RTFx 340` 是历史/声明性 benchmark，不是当前机器实测；不要将其用于服务容量承诺。
5. 旧 `细探-FunASR.md` 适合作为历史线索，包含相同的 AutoModel/VAD/runtime/许可证结论，但没有本文件的两套 HTTP 实现、导入容错、临时文件和实时 buffer 细节。后续架构事实只维护本文件，旧文档不再并行更新。

## 9. 验证等级与审计结论

| 等级 | 本轮可证明内容 | 不可证明内容 |
|---|---|---|
| L0 | 目录、源码、测试、配置、文档和入口存在 | 不能证明可导入或可部署 |
| L1 | 通过分段源码读取核对注册、AutoModel、VLLM、HTTP、WebSocket、资源和失败分支 | 不能证明外部依赖版本兼容 |
| L2 | README、安装/部署/vLLM/排障文档和测试意图可相互比对 | 文档声明不等于本地通过 |
| L3 | 本轮完成目标文件审计写入；未执行模型测试 | 不能声称 pytest、服务 smoke、GPU 或性能通过 |
| L4 | 未执行真实 checkpoint、网络、GPU、vLLM、WebSocket 压测、崩溃恢复 | 全部留待部署环境专项验证 |

**审计结论**：FunASR 的强项是把主 ASR 与 VAD/标点/说话人能力组合到一个 Python 门面，并为多种部署运行时提供适配；其主要工程风险不在单一识别模型，而在动态注册/导入容错、模型供应链、两套 HTTP 服务契约、无统一服务级队列与取消、长会话和 GPU 资源生命周期，以及文档/benchmark 的重复和版本漂移。接入生产系统时，应选定一个 HTTP/实时入口作为权威契约，在外围补齐认证、限流、队列、超时、进程隔离、结果持久化、健康指标和跨运行时回归样本。

## 10. 事实索引

- 注册与导入：`funasr/register.py`、`funasr/__init__.py`
- 主装配与推理：`funasr/auto/auto_model.py`
- vLLM：`funasr/auto/auto_model_vllm.py`、`funasr/models/fun_asr_nano/inference_vllm.py`
- HTTP：`funasr/bin/_server_app.py`、`funasr/bin/server.py`、`examples/openai_api/server.py`
- 实时 WebSocket：`funasr/bin/realtime_ws.py`
- 模型/版本/依赖：`funasr/version.txt`、`setup.py`、`pyproject.toml`
- 测试：`tests/`、`tests_models/`
- 部署与文档：`README.md`、`docs/vllm_guide.md`、`docs/vllm_guide_zh.md`、`docs/benchmark/rtf_reproducibility.md`、`docs/troubleshooting*.md`
- 历史细探：`细探-FunASR.md`，仅作线索，不作为并行权威架构文档

## 11. 施工材料吸收记录

已人工回读并吸收 `细探-FunASR.md` 的增量事实：AutoModel 与 VAD/标点/说话人子模型装配、离线/流式/2pass/llama.cpp 路由、C++ runtime 的 HTTP/WebSocket/gRPC 出口、热词双层纠错、模型与代码许可证分离、动态注册表覆盖和默认导入容错。旧材料不再作为第二份架构事实源。
