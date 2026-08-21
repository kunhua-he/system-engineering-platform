# FunASR 架构审计档案

> 本文件是当前源码快照的唯一架构事实汇总。审计对象：`~/Documents/Agent/github 源码参考/30_多模态与媒体分析/30_audio_asr/FunASR`。
> 当前核对只更新本文件；未修改源码、测试、配置、README、旧细探或运行时资产。

## 1. 审计边界与证据状态

- **项目**：FunASR，版本文件为 `funasr/version.txt` 的 `1.3.28`。
- **定位**：以 `AutoModel` 为主入口的语音工具包，覆盖离线 ASR、模型级流式 ASR、VAD、标点、说话人分离，以及 vLLM、WebSocket、HTTP、ONNX、Triton、gRPC、llama.cpp/GGUF 和移动端等部署路径。
- **代码与模型许可**：仓库代码声明 MIT；`MODEL_LICENSE` 对模型权重另行约束。不能用代码许可证替代 checkpoint 许可证审查。
- **构建事实**：`setup.py` 声明 `python_requires >=3.7`，`pyproject.toml` 仅声明 setuptools/wheel 构建后端；README 安装说明写的是 Python `>=3.8`，这是公开文档与包元数据的版本漂移。
- **依赖边界**：核心安装依赖包括 PyTorch 生态、librosa/soundfile、ModelScope/Hugging Face、OmegaConf/Hydra、tokenizer、WebSocket 与音频/说话人相关库；vLLM、FastAPI、uvicorn、python-multipart、ONNX/Triton/客户端运行时按路径额外安装。
- **CodeGraph**：目标目录含 `.codegraph/`；本轮已执行两次目标仓库 `codegraph explore`，定位 `AutoModel`、VLLM、实时 WebSocket 和 C++ runtime 入口。CodeGraph 仅用于定位，以下判断仍以现场源码、测试、配置和文档为准。
- **当前核对执行边界**：未安装依赖、未下载模型、未启动 HTTP/WebSocket/vLLM/ONNX/Triton/GGUF 服务、未执行 GPU/CPU 模型推理、未做压力/取消/崩溃恢复实验。因此本文不宣称运行通过或性能达标。

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
5. 当前目标 checkout 未发现独立 `细探-FunASR.md`；本文件不创建或维护平行细探事实源。

## 9. 验证等级与审计结论

| 等级 | 当前核对可证明内容 | 不可证明内容 |
|---|---|---|
| L0 | 目录、源码、测试、配置、文档和入口存在 | 不能证明可导入或可部署 |
| L1 | 通过分段源码读取核对注册、AutoModel、VLLM、HTTP、WebSocket、资源和失败分支 | 不能证明外部依赖版本兼容 |
| L2 | README、安装/部署/vLLM/排障文档和测试意图可相互比对 | 文档声明不等于本地通过 |
| L3 | 当前核对完成目标文件审计写入；未执行模型测试 | 不能声称 pytest、服务 smoke、GPU 或性能通过 |
| L4 | 未执行真实 checkpoint、网络、GPU、vLLM、WebSocket 压测、崩溃恢复 | 全部留待部署环境专项验证 |

## 10. 当前源码深审：AutoModel 入口与输入归一化

### 10.1 `AutoModel.__init__` 的装载顺序

`funasr/auto/auto_model.py:418-521` 的构造函数接收主模型、`vad_model`、`punc_model`、`spk_model`、`merge_vad`、`device`、`ncpu`、`batch_size_s`、`hub`、`trust_remote_code` 等配置。它先保存原始 kwargs，再为主模型及可选模型分别调用 `build_model`；这意味着 VAD、标点和说话人不是同一个模型对象上的可选开关，而是多个独立推理资源。

构造时的真实状态包括：

1. `self.model` 是主 ASR 或 LLM-ASR 模型；
2. `self.vad_model`、`self.punc_model`、`self.spk_model` 可能为 `None`；
3. `self.kwargs` 保存默认配置，`self.vad_kwargs`、`self.punc_kwargs`、`self.spk_kwargs` 保存子模型配置；
4. `self.vad_model` 存在时，`generate` 自动转到 `inference_with_vad`；不存在时走单段 `inference`；
5. `self.cache` 不是全局缓存，流式调用由调用方在 `generate(..., cache=...)` 传入。

`build_model` (`auto_model.py:522-676`) 的顺序为下载/定位模型、读取 `config.yaml`、解析 `model`/`frontend`/`tokenizer` 名称、从 `funasr.register.tables` 取类、实例化组件、加载 `init_param`、设置 dtype/device、调用 `eval()`。任何组件未注册都会抛出带注册表摘要和导入错误的异常；这不是自动降级到另一个模型。

### 10.2 输入归一化

`prepare_data_iterator` (`auto_model.py:347-416`) 接受：

| 输入 | 处理 | 证据边界 |
|---|---|---|
| 本地音频路径 | 保留为单项，key 默认取文件名 | 不校验采样率/格式，后续 loader 负责 |
| HTTP/HTTPS URL | 先 `download_from_url`，再按本地路径处理 | 下载失败直接抛出；无统一重试/大小上限 |
| `.scp/.txt/.json/.jsonl/.text` | 逐行展开，jsonl 读取 `source` 与可选 `key` | 缺字段或坏 JSON 直接异常 |
| `list/tuple` | 批量输入；多数据类型时递归展开并 zip | 长度不匹配可能由 zip 静默截短 |
| bytes | `load_bytes` 转音频对象 | 先完整读入内存 |
| numpy/tensor/原始文本 | 包装成单项 | 类型解释由下游模型/前端决定 |

文件列表没有稳定 key 时生成 `rand_key_` 加随机字符串；普通路径默认取 stem；因此相同输入重试可能得到不同 key，库本身不提供幂等键。

### 10.3 `generate` 路由

`AutoModel.generate` (`auto_model.py:689-748`) 先 `_reset_runtime_configs()`，再依据 `self.vad_model` 分支：

```text
generate(input, cfg)
  -> reset runtime config
  -> no vad_model ? inference : inference_with_vad
  -> optional punc_model on each result
  -> postprocess_hotwords_to_results
  -> list[dict]
```

无 VAD 路径对每个结果的 `text` 再调用标点模型；若 `return_raw_text` 开启，会先保存 `raw_text`。有 VAD 路径在组合管线内部做标点、时间戳、说话人关联。两条路径返回字段不是严格统一 schema，调用方必须按模型和配置读取。

`generate` 的关键运行参数包括 `cache`、`is_final`、`batch_size_s`、`hotword`、`language`、`sentence_timestamp`、`return_spk_res`、`use_itn`、`progress_callback`。未知配置会进入不同模型的 kwargs，不能假设所有模型都接受同一字段。

## 11. ASR/VAD/标点/说话人组合链

### 11.1 无 VAD 推理

`inference` (`auto_model.py:750-851`) 创建数据迭代器，按 `batch_size_s` 或固定 batch 切分，调用 `model.inference`，将模型输出转成 list 字典并附加 key。它负责进度回调和异常传播，不负责持久化中间结果。长音频是否切片取决于模型/前端配置；没有统一跨模型的覆盖率检查。

### 11.2 VAD 推理

`inference_with_vad` (`auto_model.py:852-1255`) 的真实步骤为：

1. 对输入批次执行 VAD，得到 `[start, end]` 区间；
2. `merge_vad` 开启时合并相邻区间；
3. 读取音频并按区间切段；
4. 根据 `batch_size_s` 动态排序/分批；
5. 调用主 ASR 模型；
6. 恢复原始输入顺序和时间偏移；
7. 可选调用标点模型；
8. 可选调用说话人 embedding/聚类；
9. 通过 `_vad_segment_sentences`、`_merge_timestamp_units` 形成 `sentence_info` 和 timestamp。

VAD 空结果和 ASR 异常语义不同：空区间可以返回空文本，异常则向调用方抛出；服务适配层不得把两者都转成 HTTP 500。

### 11.3 标点与时间戳

`_punctuate_surface_text` (`auto_model.py:134-188`) 将标点模型输出映射回原始文本；`_merge_timestamp_units` (`189-246`) 将字/词级时间戳和标点数组合并。无空格语言与英文混合文本需要依赖模型提供的 words/timestamp，否则句级时间可能只是粗粒度估算。

`sentence_timestamp=True` 会触发 `_vad_segment_sentences` (`71-133`) 和句边界重建；这不是模型统一能力。对于 VAD 多段，代码需要把局部 timestamp 加上原始音频偏移，排序后再输出。

### 11.4 说话人识别

`spk_model` 只在显式装载并开启 `return_spk_res`/相关配置时参与。典型 CAMPPlus 路径将 VAD 段转成 speaker chunks，调用 embedding 模型，再交给 `ClusterBackend` 聚类，最后用 `distribute_spk` 把 label 分配回 sentence。聚类阈值、oracle speaker 数量和 embedding 维度是模型/示例配置，不是统一公共契约。

## 12. 流式状态与实时协议

### 12.1 Python `cache` 语义

Paraformer/FSMN-VAD 流式调用的状态由调用方保存：

```text
new session -> cache={}
chunk_i -> model.generate(chunk_i, cache=cache, is_final=False)
last chunk -> model.generate(..., is_final=True)
reset/disconnect -> caller drops cache
```

`cache` 可以包含 encoder、decoder、VAD 和时间窗口状态；其结构依模型而异，不能序列化为跨版本稳定协议。进程重启、乱序 chunk 或连接迁移不会自动恢复。

### 12.2 `funasr/bin/realtime_ws.py`

实时 WebSocket 入口接收 PCM16 bytes 与文本命令。典型命令包括 `START`、`STOP`、`LANGUAGE:`、`HOTWORDS:`、`SPK:`；二进制消息被转成 float32 后送入 VAD。服务维护 `audio_buffer`、`locked_sentences`、语言/热词/说话人开关和活动状态。

每次 bytes 消息：

1. 追加 `audio_buffer`；
2. `vad.feed` 生成确认段；
3. 对超过最小长度的确认段调用 `_engine.generate`；
4. 追加句子并发送 `is_final=False` 的 partial JSON。

`STOP` 会 finalize VAD、处理未结束语音、可选执行全量 speaker clustering，再发送 `is_final=True`。异常被记录并返回当前连接级错误；代码没有跨连接队列、重放游标或断线续传。

### 12.3 原生 C++ WebSocket runtime

`runtime/websocket/bin/websocket-server-2pass.h:49-71` 的 `FUNASR_MESSAGE` 为每连接保存 samples、punctuation cache、hotword embedding、decoder handle、online result、strand 和时间索引。`WebSocketServer` (`76-165`) 注册 open/message/close handler，使用 `asio::io_context` 解码线程池和每连接 mutex/strand 保证顺序。`on_close`/`check_and_clean_connection` 是资源释放关键点；断连后的解码任务与 map 清理必须结合实现文件验证，不能只看头文件声明。

### 12.4 流式失败边界

- partial 已发送后，后续失败不会回滚客户端已见前缀；
- `is_final` 只表示当前服务端认为本次 STOP 已收束，不是持久化提交证明；
- 长连接没有库级 idle TTL 或最大音频时长；
- WebSocket 发送阻塞、慢客户端和多客户端背压由宿主框架处理，Python 示例没有有界发送队列；
- VAD/ASR 使用同一连接的 numpy buffer，连接关闭时是否及时释放取决于外围 finally。

## 13. vLLM、ONNX、Triton 与部署适配

### 13.1 `AutoModelVLLM`

`funasr/auto/auto_model_vllm.py` 只接受 LLM-ASR 架构，先解析模型目录/config，再把 encoder/adaptor 保留在 PyTorch，LLM 解码交给 vLLM。`check_vllm_applicable` 明确拒绝 Paraformer、SenseVoice、CT-Transformer、Conformer 等非 LLM 模型。`generate` 将音频特征封装为 vLLM prompt，并受 `max_new_tokens`、dtype、tensor parallel、GPU memory utilization 限制。

`prepare_vllm_weights` 会复制配置、tokenizer 和模型权重，转换到 safetensors/model.bin。当前代码使用目录创建和复制操作，没有事务 marker、文件 hash manifest 或跨进程锁；并发转换同一目标目录可能产生半成品。

### 13.2 HTTP 服务

`funasr/bin/server.py` 与 `_server_app.py` 提供生产倾向的 FastAPI 包装，`examples/openai_api/server.py` 是示例实现。它们在以下方面不完全一致：默认模型、设备、`response_format`、verbose segments、health schema、模型缓存、vLLM fallback 和异常转换。部署时必须选定一个入口并为其单独编写契约测试。

上传处理普遍先 `await file.read()` 或读取临时文件；虽然临时文件通常在 `finally` unlink，仍缺少请求体上限、磁盘配额、超时和取消令牌。async handler 直接调用同步/重模型推理会阻塞事件循环，应由外层 worker 或进程池隔离。

### 13.3 ONNX/C++ runtime

`runtime/onnxruntime/src/funasrruntime.cpp:6-18` 暴露 `FunASRInit`/`FunASROnlineInit`，`85-117` 的 `FunASRInfer` 读取 wav/pcm/ffmpeg 音频并调用 `Forward`，`119-` 继续提供 VAD buffer 接口，`763-` 提供 reset。C ABI handle 的创建/销毁和异常传播必须由调用方管理；Python `AutoModel` 的 list[dict] 结果不能直接假设等于 C++ `FUNASR_RESULT`。

`runtime/http/bin/server.hpp:26-66` 的 C++ HTTP server 使用 acceptor、io_context_pool、signal_set 和 `ModelDecoder`；`run()`/`do_accept()`/`do_await_stop()` 构成异步生命周期，但本轮未启动验证端口、信号停止和 decoder 线程回收。

## 14. CLI、模型下载与配置边界

`funasr/cli.py` 与 `funasr/bin/inference.py` 提供命令行入口，主要负责解析 model/input/output/device/batch 等参数，然后实例化 `AutoModel` 并写文本/JSON/SRT。CLI 不是额外的推理核心，参数默认值可能与 HTTP/示例不同。

ModelScope/Hugging Face 下载由 `download_model`、snapshot API 和 `download_from_url` 处理。revision、缓存目录、鉴权、远程代码和模型许可证是部署输入；下载中断、磁盘满和进程崩溃时不保证自动回滚半成品缓存。

配置优先级通常是 CLI kwargs → AutoModel 默认 → 模型 `config.yaml` → frontend/tokenizer/model 注册表。`FUNASR_STRICT_IMPORT=1` 将可选组件导入错误升级为启动错误；默认模式记录 `_IMPORT_ERRORS` 并延迟到组件构造失败。生产启动应把注册表快照、实际 device、模型 revision、dtype 和导入错误写入健康证据。

## 15. 测试证据与可执行边界

### 15.1 已存在的测试类别

| 路径 | 覆盖意图 | 当前状态 |
|---|---|---|
| `tests/test_auto_model.py` | 注册失败、strict import、progress callback、构造边界 | 代码存在，未本轮执行 |
| `tests/test_asr_inference_pipeline.py` | 真实 ASR pipeline/公开音频 | 依赖模型/网络，未执行 |
| `tests/test_asr_vad_punc_inference_pipeline.py` | ASR+VAD+标点组合 | 依赖 checkpoint/设备，未执行 |
| `tests/test_fsmn_vad_streaming_buffers.py` | 流式 VAD buffer 边界 | 代码存在，未执行 |
| `tests/test_dynamic_streaming_vad.py` | 动态静音/段落状态 | 代码存在，未执行 |
| `tests/test_cli.py` | CLI 参数与错误 | 代码存在，未执行 |
| `tests/test_realtime_ws_benchmark.py` | 统计 mock/benchmark | 不等于真实 WS 压测 |
| `tests_models/` | 真实 SenseVoice/Paraformer/CAMPPlus 等模型 | 重依赖，未执行 |

### 15.2 测试不变量

源码测试关注局部行为，不提供统一发布门禁：

1. 模型测试需要 checkpoint、音频、GPU/CPU 和网络；
2. 文档/CLI 测试可能只验证参数解析，不验证模型输出；
3. realtime benchmark 的 mock 时间和消息不证明慢客户端背压；
4. Python 测试不能证明 ONNX/C++/Triton/vLLM runtime ABI；
5. 没有看到覆盖所有 HTTP 上传上限、取消、临时文件泄漏、显存回收和跨进程崩溃的统一测试。

### 15.3 本轮验证

本轮仅执行了仓库同步、目录/源码/CodeGraph 静态审计和平台缓存读写基线记录；没有执行 FunASR pytest、模型下载或服务启动。验证记录应标为平台文档工作包成功，不得标为 FunASR 运行通过。

## 16. 平台映射与吸收边界

### 16.1 可吸收能力

| FunASR 事实 | 平台支持库/模块映射 | 必须保留的边界 |
|---|---|---|
| `prepare_data_iterator` | 音频输入规范化模块 | URL/bytes 大小、稳定 id、格式与采样率校验 |
| `AutoModel.generate` | ASR 能力门面 | 统一结果 schema、模型能力声明、错误码 |
| VAD+ASR+Punc+SPK | 语音流水线模块 | 段落覆盖率、时间单位、可选组件 owner |
| streaming cache | 流式会话模块 | session/epoch、chunk 顺序、TTL、取消 |
| ModelScope/HF 下载 | 模型制品支持库 | revision/hash/许可证/原子缓存 |
| HTTP/WS | 传输适配层 | body/queue/backpressure/auth/timeout |
| C++/ONNX/Triton | 受管外部进程/动态库适配层 | handle 生命周期、ABI、崩溃隔离 |

### 16.2 不应直接吸收

- 不能把 `AutoModel` 的动态注册表作为平台唯一能力注册表；重复 key 覆盖行为必须先改为冲突失败。
- 不能把模型 `cache` 当成平台 durable session；必须包装 owner、版本、过期和恢复策略。
- 不能把 `InMemory`/模块全局模型缓存当成跨请求事实；需要资源预算和明确释放。
- 不能把两个 HTTP 服务实现合并为无条件兼容 API；先冻结一个版本化响应契约。
- 不能把 vLLM 权重转换目录当作原子制品；应增加 staging、manifest/hash 和发布指针。

## 17. 当前风险清单（按优先级）

1. **高**：HTTP 上传无统一大小/并发/超时/取消门禁，重模型调用可能阻塞事件循环并耗尽内存。
2. **高**：模型下载和 vLLM 权重转换缺少统一原子事务，崩溃可能留下半成品并被后续复用。
3. **高**：流式 cache 只在调用方内存中，断线/重启丢失；服务没有跨连接恢复协议。
4. **中**：注册表重复 key 覆盖、默认导入吞错、remote code 供应链边界需要部署门禁。
5. **中**：多模型结果字段不统一，HTTP 适配层转换规则容易造成 timestamp/segment 语义漂移。
6. **中**：说话人聚类和标点是可选异步/同步组件，失败时部分路径保留文本但缺少统一能力状态。
7. **中**：设备不可用时静默 CPU fallback + batch=1，可能造成容量雪崩而非显式失败。
8. **低**：文档、README、示例和 setup.py 的 Python/服务/API 版本存在漂移，应由契约测试锁定。

## 18. 最终证据边界

- 源码快照：`3c58cb5`（`main`，本轮 fetch/pull 后确认最新）。
- CodeGraph：目标仓库 `.codegraph/` 可用；本轮已用 CodeGraph 定位关键 Python/C++ 入口，最终结论以源码和测试文件为准。
- 文档唯一性：平台侧仅维护本文件；源码侧未跟踪 `ARCHITECTURE.md` 与 `.codegraph/` 均未删除。
- 未验证：FunASR 依赖安装、pytest、真实模型、GPU、网络下载、HTTP/WS/vLLM/ONNX/Triton、取消、背压、崩溃恢复、显存和临时文件现场。
- 因此本文是源码级 L0/L1 审计，不是部署验收或性能报告。

## 19. 细粒度调用链证据索引

本节把前述结论压缩为可以复核的 file:line 路径，避免仅凭目录名称推断能力。

| 调用链 | 入口 | 中间步骤 | 终点/副作用 |
|---|---|---|---|
| 离线单段 | `AutoModel.generate` `auto_model.py:689-748` | `inference` `750-851`、`prepare_data_iterator` `347-416` | `model.inference` 返回 list 字典 |
| 离线长音频 | `generate` | `inference_with_vad` `852-1255`、VAD 分段/排序/偏移 | ASR + optional punc/spk |
| 标点 | `generate` `733-742` | 对每个结果再次 `inference` | 覆写 `text`，可保留 `raw_text` |
| 热词 | `generate` `742/748` | `apply_postprocess_hotwords_to_results` | 文本替换与可选匹配详情 |
| streaming | `generate(cache,is_final)` | 模型/ VAD cache | partial/final list；状态由调用方持有 |
| 模型装载 | `AutoModel.__init__` `418-521` | `build_model` `522-676` | registry + config + weights + eval |
| 动态注册 | `funasr/__init__.py` | `pkgutil.walk_packages` + `register.tables` | 默认吞导入错，strict 模式失败 |
| Python WS | `funasr/bin/realtime_ws.py` | receive bytes → VAD → engine.generate | JSON partial/final |
| Python HTTP | `funasr/bin/_server_app.py` | upload → temp file → model.generate | OpenAI/ASR JSON |
| C++ WS | `runtime/websocket/bin/websocket-server-2pass.h:76-165` | open/message/close + strand | 每连接 `FUNASR_MESSAGE` |
| C++ HTTP | `runtime/http/bin/server.hpp:26-66` | acceptor + io_context_pool + decoder | 异步 HTTP 服务 |
| ONNX | `runtime/onnxruntime/src/funasrruntime.cpp:6-117` | handle init + audio load + Forward | `FUNASR_RESULT` |
| vLLM | `auto_model_vllm.py` | encoder/adaptor + vLLM LLM | LLM-ASR text/timestamps |

### 19.1 结果与错误边界

FunASR Python 核心没有统一 `成功/值/错误码/可重试` envelope；主要使用异常和 `list[dict]`。服务层可能将异常转换为 HTTP 400/500，实时 WS 可能记录错误后继续连接，C++ runtime 以空句柄/null pointer/结构体指针表达失败。平台适配必须在外层完成错误归一化，不能把不同入口的原始行为直接暴露为同一契约。

### 19.2 资源释放核对表

- `AutoModel`：未见跨模型统一 `close()`；服务进程退出是主要释放边界。
- 临时上传文件：部分 HTTP 路径用 `finally` 删除，但没有删除失败账本。
- numpy audio buffer：实时会话追加/压缩依赖连接处理，不具备跨连接持久化。
- C++ handle：`FunASRInit`/`FunASRReset` 暴露，销毁和异常转译由 ABI 调用方负责。
- vLLM 权重目录：创建/复制/写入非原子，需外部 staging 和锁。
- GPU tensors/KV cache：由 torch/vLLM/进程管理，库未提供统一 request cancel/reap。
- WebSocket connection map：C++ 头文件声明 `check_and_clean_connection`，必须以实现和运行态验证清理完成。

### 19.3 部署前最小验收矩阵

1. 固定模型 revision、权重 hash、代码版本和模型许可证。
2. 启动探针确认实际 backend/device/dtype、可选组件注册和显存占用。
3. HTTP 发送超大 body、慢请求、断开上传，确认有界拒绝和临时文件回收。
4. WS 发送乱序/空 chunk、长时间静音、STOP 中断，确认 session TTL 和最终状态。
5. vLLM/ONNX/Triton 启动失败、模型转换中断和 worker kill，确认无半成品和孤儿进程。
6. VAD 无语音、标点失败、SPK 聚类失败分别验证错误码与部分结果语义。
7. 多客户端并发和 GPU OOM 验证背压、排队、取消和资源释放。
8. 真实测试通过后，才允许把 L0/L1 静态结论升级为运行态证据。

## 20. 本轮交付记录

- 开工 id：`536911525b84474c`。
- MCP 实例：`system_engineering_toolkit`（平台 HTTP 网关）。
- 目标源码 HEAD：`3c58cb5`，远程 `origin/main` 已 fetch/pull 且无更新。
- CodeGraph：目标 `.codegraph/` 存在；已查询 AutoModel 主链与 Python/C++ 服务入口。
- 修改文件：仅平台侧 `开发文档/源码参考研究/项目/30_多模态与媒体分析/30_audio_asr/FunASR/ARCHITECTURE.md`。
- 源码侧状态：未跟踪 `.codegraph/`、`ARCHITECTURE.md` 保留，未修改/删除。
- 验证：平台缓存读写工作包记录为退出码 0；FunASR pytest、服务和模型推理未执行。
- 未验证项：依赖安装、模型下载、GPU、HTTP/WS/vLLM/ONNX/Triton、背压、取消、崩溃恢复、显存/临时文件清理现场。

## 21. 目录与组件盘点补充

| 目录/文件 | 当前源码事实 | 研究边界 |
|---|---|---|
| `funasr/auto/` | AutoModel、AutoFrontend、AutoModelVLLM、输入和导出 | 主 Python 调度层，不等于全部模型实现 |
| `funasr/models/` | Paraformer、SenseVoice、FSMN-VAD、CAMPPlus、标点和 LLM-ASR | 各模型有独立 cache/输出字段 |
| `funasr/frontends/` | fbank、wav、音频特征和采样率处理 | 前端参数随模型 config 变化 |
| `funasr/utils/` | audio loader、下载、timestamp、hotword、导出 | 文件/URL 和后处理边界 |
| `funasr/bin/` | CLI、HTTP、WS、训练/导出入口 | 入口之间非完全同构 |
| `runtime/` | C++ HTTP/WS、ONNX、Triton、gRPC、llama.cpp、移动端 | ABI/线程/模型格式独立 |
| `examples/` | OpenAI、实时、批处理、vLLM、MCP 示例 | 示例不是发布契约 |
| `tests/` | 轻量、文档、服务和管线测试 | 外部依赖比例高 |
| `tests_models/` | 真实模型专项测试 | 需要 checkpoint/设备 |
| `model_zoo/` | ModelScope/HF 模型选择和卡片 | 许可证和 revision 需外部锁定 |
| `docs/` | 安装、部署、迁移、vLLM、排障 | 文档数字不等于当前实测 |

设备路径包括 CPU、CUDA、NPU、ONNX CPU/GPU、Triton server、vLLM GPU 和 C++ runtime；`_resolve_ncpu`、`is_npu_available` 与模型/服务参数共同决定实际执行资源。部署健康检查必须记录实际设备而不是仅记录请求参数。模型、VAD、标点、SPK 同时加载时显存是叠加占用，不能以主模型单独大小估算容量。

FunASR 没有统一的跨入口版本化 API schema：Python 结果、HTTP JSON、WS partial、C++ `FUNASR_RESULT`、ONNX handle 和 Triton 输入输出属于不同契约。平台接入应为每条链建立独立能力 id、输入输出 schema、资源预算和验证场景，禁止通过“同为 ASR”合并不同 ABI 和生命周期。

### 21.1 交付判定

本文件达到 500 行级源码审计要求后，仍只代表静态研究完成：目录和入口已盘点，关键调用链有 file:line 证据，风险与未验证项已分离。任何“模型可用”“服务稳定”“实时性达标”“GPU 容量足够”或“崩溃可恢复”的结论，都必须另有受控运行记录、输入/输出样本、资源探针和退出码，不能由本文件自动升级。

验收记录还应保存：源码提交、模型 revision、Python/torch/CUDA 版本、设备、音频输入摘要、模型输出摘要、服务端口、测试命令、退出码、临时目录和进程回收结果。缺少其中任一关键项时，结果只能标注为局部实验，不能写成正式发布证据。

这也是本文与部署报告的分界：本文冻结源码事实和风险，部署报告另行记录真实环境和动态结果。

后续源码更新应先刷新顶部提交与 CodeGraph 状态，再修改调用链和风险矩阵。

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
- 历史细探：当前 checkout 未发现独立 `细探-FunASR.md`；本文件为平台侧唯一架构事实源

## 11. 研究材料吸收记录

本轮直接从当前 checkout 源码核对 AutoModel 与 VAD/标点/说话人子模型装配、离线/流式/2pass/llama.cpp 路由、C++ runtime 的 HTTP/WebSocket/gRPC 出口、热词双层纠错、模型与代码许可证分离、动态注册表覆盖和默认导入容错；未发现独立细探文件。
