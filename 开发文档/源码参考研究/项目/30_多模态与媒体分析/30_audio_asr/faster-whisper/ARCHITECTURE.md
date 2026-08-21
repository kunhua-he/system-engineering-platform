# faster-whisper 架构档案

> **唯一权威架构文档**：本文件是当前源码快照的架构事实源；后续架构维护只更新本文件。
> `细探-faster-whisper.md` 按用户要求保留为历史细探/线索，不删除、不再作为权威事实源。

## 1. 文档边界、身份与证据基线

- **项目名**：`faster-whisper`
- **项目根目录**：`/Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/30_audio_asr/faster-whisper`
- **上游**：`https://github.com/SYSTRAN/faster-whisper.git`
- **许可证**：仓库代码 MIT；Whisper/转换后模型权重的许可证需按具体模型另行核对。
- **语言与版本**：Python `>=3.9`；包版本 `1.2.1`，证据：`setup.py:14-19`、`faster_whisper/version.py:1-3`。
- **Git 基线**：本地 `master`/`HEAD` 为 `ed9a06cd89a93e47838f564998a6c09b655d7f43`，提交时间 `2025-11-19T14:40:46Z`，提交说明 `Adds new VAD parameters (#1386)`；本轮现场 `git ls-remote origin HEAD refs/heads/master` 返回相同提交。工作树在本任务开始时已有两个未跟踪文档：`ARCHITECTURE.md` 与 `细探-faster-whisper.md`。
- **研究边界**：只读取当前仓库源码、README、依赖、测试、CI、Docker/benchmark、Git 元数据和旧细探；不改源码、配置、测试、依赖或 Git，不安装依赖、不下载模型、不启动服务。
- **性能口径**：README 的“最高 4 倍、更少内存、8-bit”是项目说明/历史 benchmark 口径，不是本机本轮实测结论。
- **代码图状态**：专属 `project_toolkit` 的 `project_context` 首次绑定到了错误项目 `华世王镞_v3`（根目录 `/Users/hekunhua/Documents/Agent/PHP/华世王镞_v3`）；随后按要求用 `codegraph_explore` 指定目标根，但目标目录及其父级没有 `.codegraph/`，返回“未建立代码图”。本档案以下事实全部以目标仓库现场文件为证据，不能把错误项目代码图冒充本项目证据。

## 2. 定位与边界

`faster-whisper` 是 OpenAI Whisper 的 CTranslate2 重实现，属于 Python ASR **推理库**，不是 HTTP 服务、数据库、任务队列、持久化转写系统或原生实时 streaming 服务。Python 层负责输入解码、log-Mel 特征、VAD 分块、语言/token 协议、窗口调度、质量回退、时间戳和结果对象；CTranslate2 负责 Whisper encoder/decoder/generate/align 数值推理。

它向调用方交付惰性 `Iterable[Segment]` 与 `TranscriptionInfo`。转写函数返回时并不等于推理完成：必须遍历 generator，才会触发大部分编码、生成、对齐和异常。

## 3. 真实总流程

```text
音频路径 / BinaryIO / float32 numpy waveform
        │
        ├─ 非 ndarray：audio.decode_audio → PyAV av.open → s16/16kHz/mono
        │                              （可选 stereo 左右声道拆分）
        ▼
WhisperModel.transcribe 或 BatchedInferencePipeline.transcribe
        │
        ├─ VAD（可选）：SileroVAD ONNX → speech chunks(sample offsets)
        │       └─ collect_chunks → 拼接音频 + offset/duration/segments 元数据
        ├─ clip_timestamps：显式切片，跳过 VAD
        └─ FeatureExtractor → STFT → Mel filter → log10/动态范围压缩
        │
        ├─ 未指定 language：CTranslate2 detect_language（多语言模型）
        └─ Tokenizer：language/task/SOT/no-timestamps/prompt/hotwords
        │
        ├─ 单路：WhisperModel.generate_segments
        │    ├─ 30 秒窗口 seek/clip
        │    ├─ encode → generate_with_fallback（temperature/质量阈值）
        │    ├─ timestamp token → Segment 切分
        │    └─ 可选 align → word timestamps/标点与边界修正
        │
        └─ 批量：BatchedInferencePipeline._batched_segments_generator
             ├─ features 按 batch_size 分组
             ├─ encode + CTranslate2 Whisper.generate（单温度，无单路 fallback）
             └─ Segment 切分 → 可选 align → 恢复 VAD 原始时间
        │
        ▼
Segment(id, seek, start, end, text, tokens, scores, words?)
+ TranscriptionInfo(language, duration, options, VAD metadata)
        │
        └─ 由调用方遍历、序列化、持久化和负责任务状态/重试/取消/恢复
```

## 4. 仓库结构与职责

```text
faster-whisper/
├── faster_whisper/
│   ├── __init__.py              # 顶层公共导出
│   ├── version.py               # __version__
│   ├── transcribe.py            # 结果 dataclass、WhisperModel、批量管线、解码/对齐
│   ├── audio.py                 # PyAV 解码、重采样、帧聚合、pad_or_trim
│   ├── feature_extractor.py     # STFT、Mel filter、log-Mel 特征
│   ├── tokenizer.py             # tokenizers 包装、special tokens、词切分
│   ├── vad.py                   # Silero VAD、speech chunks、时间映射
│   ├── utils.py                 # 模型别名/下载、资源路径、日志、时间格式
│   └── assets/
│       └── silero_vad_v6.onnx   # 包内 VAD 权重
├── tests/
│   ├── conftest.py              # jfk/physicsworks 数据 fixture
│   ├── test_transcribe.py       # 单路/批量/VAD/语言/时间戳等集成测试
│   ├── test_tokenizer.py        # 抑制 token、unicode 词切分
│   ├── test_utils.py            # 模型清单和 Hugging Face 下载测试
│   └── data/                    # 音频样本
├── benchmark/                   # speed/memory/WER/YouTube Commons 脚本
├── docker/                      # CUDA 单文件推理示例
├── setup.py                     # setuptools 元数据、extras、打包
├── requirements*.txt            # 运行/转换/benchmark 依赖入口
├── .github/workflows/ci.yml     # 格式、测试、构建、PyPI 发布
├── README.md                    # 安装、能力、示例和历史 benchmark
├── 细探-faster-whisper.md       # 历史细探，保留但不作为权威事实源
└── ARCHITECTURE.md              # 唯一权威架构档案（本文件）
```

当前 Git 跟踪快照包含源码、配置、测试与音频样本；Whisper CTranslate2 主模型权重不随仓库提交，只有 Silero VAD ONNX 资产随包分发（`MANIFEST.in:1-3`）。

## 5. 技术栈与外部边界

| 边界 | 组件/版本约束 | 真实职责 | 证据 |
|---|---|---|---|
| 推理 | `ctranslate2>=4.0,<5` | `Whisper.encode/generate/align`，设备、线程、量化 | `requirements.txt:1`；`transcribe.py:689-698,1391-1400,1446-1459,1709-1715` |
| 音频 | `av>=11`（PyAV，包内 FFmpeg） | `av.open`、音频帧解码、s16/16kHz 重采样、帧聚合 | `requirements.txt:5`；`audio.py:37-76` |
| 数组/特征 | `numpy` | waveform、STFT、Mel 矩阵、batch 特征 | `audio.py:66-76`；`feature_extractor.py:198-230` |
| tokenizer | `tokenizers>=0.13,<1` | `tokenizer.json` 编解码、special token、unicode/空格词切分 | `requirements.txt:3`；`tokenizer.py:9-211` |
| 模型分发 | `huggingface_hub>=0.23` | 模型别名映射、Hub snapshot/cache、revision、离线查找 | `requirements.txt:2`；`utils.py:49-115` |
| VAD | `onnxruntime>=1.14,<2` + `silero_vad_v6.onnx` | CPU Silero VAD 推理、speech chunk 和原始时间映射 | `requirements.txt:4`；`vad.py:322-385` |
| 进度/日志 | `tqdm`、标准库 `logging` | 进度条、`faster_whisper` logger | `transcribe.py:1151,1385-1389,583-617`；`utils.py:44-46` |
| 模型转换 | `transformers[torch]>=4.23`（conversion extra） | Transformers Whisper → CTranslate2 转换入口 | `requirements.conversion.txt:1`；`README.md:255-273` |
| 质量门禁 | Black 23、isort 5、flake8 6、pytest 7 | CI 格式、导入、风格、测试 | `setup.py:57-63`；`.github/workflows/ci.yml:13-63` |

GPU 不是抽象的跨平台 provider：README 要求 NVIDIA CUDA 12/cuBLAS/cuDNN 9；CUDA 11/cuDNN 8 需按 README 说明降级 CTranslate2（`README.md:63-70`）。仓库无 GPU 探测服务、模型管理 API、HTTP 路由或认证层。

## 6. 公共入口与契约表

顶层 `faster_whisper.__all__` 只导出 `available_models`、`decode_audio`、`WhisperModel`、`BatchedInferencePipeline`、`download_model`、`format_timestamp`、`__version__`（`faster_whisper/__init__.py:1-14`）。

### 6.1 公开契约

| 入口/对象 | 输入 | 输出/状态 | 失败、重试、超时、取消、幂等与资源责任 | 证据 |
|---|---|---|---|---|
| `WhisperModel(...)` | 模型别名、本地目录或 Hub repo；device/index/compute_type/线程；可选 `files` | 持有 CTranslate2 Whisper、tokenizer、FeatureExtractor | 别名不合法 `ValueError`；下载/文件/CT2/依赖异常向上抛出；无 `close()`、无显式取消/超时/幂等键；创建者持有模型对象至进程/GC | `transcribe.py:620-722`；`utils.py:81-115` |
| `WhisperModel.transcribe(audio, ...)` | 路径、BinaryIO 或 `np.ndarray`；语言/task、窗口、VAD、clip、prompt、温度、时间戳等 | `(Iterable[Segment], TranscriptionInfo)`；generator 遍历时执行 | 音频解码、语言/token、CT2 推理异常传播；单路 temperature 列表可按质量阈值 fallback；无 API timeout/cancel；generator 关闭只停止后续 Python 迭代，不提供底层中断；调用方负责消费/保存 | `transcribe.py:747-1022,1103-1530`；`README.md:142-155` |
| `BatchedInferencePipeline(model)` | 已构造的 `WhisperModel` | 批处理 facade；`transcribe` 返回同类结果 | `batch_size` 控制 Python 分批；当前实现仅取 `temperature[:1]`，不执行单路质量 fallback，且源码将若干参数标为 unused；无 timeout/cancel/恢复；实例的 `last_speech_timestamp` 是可变状态，复用需隔离 | `transcribe.py:111-118,193-252,254-299,518-617` |
| `decode_audio(input_file, sampling_rate=16000, split_stereo=False)` | 路径或文件对象 | float32 waveform；立体声时 `(left,right)` | PyAV/格式错误上抛；`with av.open` 正常关闭 container；文件对象由调用者提供/所有；内部 raw buffer/resampler 由函数持有；无重试/超时/取消 | `audio.py:19-76` |
| `download_model(size_or_id, ...)` | 别名或含 `/` 的 Hub repo；output/cache、revision、token、local-only | Hub 返回本地模型目录 | 无 `/` 且不在 `_MODELS` → `ValueError`；网络/鉴权/缓存异常上抛；Hub 自身负责缓存/文件落盘，库不做事务回滚或下载超时；相同 repo/revision 依赖 Hub cache 语义 | `utils.py:49-115` |
| `available_models()` | 无 | `_MODELS` key 列表 | 只读内存，无失败/资源；不是远端模型可用性探针 | `utils.py:11-36` |
| `Segment`/`Word`/`TranscriptionInfo` | 内部推理结果 | dataclass；可 `dataclasses.asdict` | `_asdict()` 仅兼容且发弃用警告；对象不自动持久化；用户应在遍历时复制/序列化 | `transcribe.py:31-109` |
| `get_speech_timestamps`/`collect_chunks` | waveform、`VadOptions`/dict、采样率、chunk 上限 | speech sample 区间；音频块与 offset/duration 元数据 | 缺 `onnxruntime` → `RuntimeError`；VAD 结果可为空；无重试/超时/取消；VAD 模型由 LRU cache 持有至进程结束 | `vad.py:51-277,322-385` |

### 6.2 结果数据模型

- `Word`：`start`、`end`、`word`、`probability`。
- `Segment`：`id`、`seek`、`start`、`end`、`text`、`tokens`、`avg_logprob`、`compression_ratio`、`no_speech_prob`、可选 `words`、`temperature`。
- `TranscriptionOptions`：beam/sampling、prompt、时间戳、VAD/clip、hotwords 等请求选项。
- `TranscriptionInfo`：检测语言及概率、原始/过滤后时长、全部语言概率、转写选项、VAD 选项。
- `VadOptions`：threshold、正/负 silence、speech 最小/最大时长、padding 等，定义于 `vad.py:15-49`。

### 6.3 重要语义差异

README 把 `BatchedInferencePipeline.transcribe` 称为 `WhisperModel.transcribe` 的 drop-in replacement（`README.md:157-169`），但当前源码存在不能忽略的差异：

1. 单路默认 `vad_filter=False`、`clip_timestamps="0"`，批量默认 `vad_filter=True`、`clip_timestamps=None`。
2. 单路支持逗号字符串 clip；批量签名是 `Optional[List[dict]]`，并把每个 clip 的 `start/end` 当秒数转换。
3. 单路保留完整 `temperatures`、质量阈值 fallback、`condition_on_previous_text`；批量仅使用首个 temperature，并在构造 `TranscriptionOptions` 时固定 `condition_on_previous_text=False`、`prompt_reset_on_temperature=0.5`、`max_initial_timestamp=0.0`、`hallucination_silence_threshold=None`，其 docstring 也标记多个参数为 unused（`transcribe.py:351-369,518-553`）。
4. 批量接收 dict `vad_parameters` 时会原地 `pop("max_speech_duration_s")`，调用方不能假设输入 dict 未被修改（`transcribe.py:399-409`）。
5. 当前 benchmark `benchmark/evaluate_yt_commons.py:52-54` 仍调用 `BatchedInferencePipeline(model, device="cuda")`，但当前构造器只接收 `model`（`transcribe.py:111-116`），直接执行该 benchmark 预期会因参数漂移失败；本任务只记录，不改 benchmark。

## 7. 真实对接调用链

### 7.1 单路 `WhisperModel.transcribe`

| 顺序 | 真实节点 | 输入/输出与状态 | 异常/边界 | 证据 |
|---:|---|---|---|---|
| 1 | `WhisperModel.__init__` | 解析 `files`/本地目录/Hub 别名，构造 CT2 Whisper；加载 tokenizer 与 `FeatureExtractor`，计算 frame/token/time 常量 | 下载、模型目录、tokenizer fallback、CT2 兼容失败即初始化失败；`files` dict 被 pop 消费 | `transcribe.py:671-722` |
| 2 | `decode_audio` | 非 ndarray 输入 → PyAV 解码为 float32 16 kHz；ndarray 原样进入 | 非法媒体/文件对象异常；内部忽略 `av.error.InvalidDataError` 帧，但不是所有解码错误都吞掉 | `audio.py:37-76,79-109`；`transcribe.py:875-878` |
| 3 | VAD/clip 分支 | `vad_filter` 且 clip 为 `"0"` 时 VAD；否则不做 VAD；VAD 后拼接 chunks，记录 `duration_after_vad` | VAD 空结果仍会得到空拼接；显式 clip 优先于 VAD；长音频无 clip 且未开 VAD 直接 `RuntimeError` | `transcribe.py:885-915` |
| 4 | `FeatureExtractor.__call__` | waveform → Hann/STFT → Mel filter → log10、动态范围压缩，返回 `(n_mels,n_frames)` | `chunk_length` 会修改 extractor 的 `n_samples/nb_max_frames` 实例状态；输入形状/dtype错误在 numpy/STFT 处失败 | `feature_extractor.py:198-230` |
| 5 | `detect_language`（可选） | 多语言模型按指定段数 encode，取语言 token 概率；阈值内未命中则多数投票 | 空音频通过 dummy feature；`audio` 与 `features` 都空由 assert 失败；语言结果不是外部持久状态 | `transcribe.py:921-952,1768-1841` |
| 6 | `Tokenizer` + `get_prompt` | 校验 language/task，组装 SOT/语言/task/no-timestamps、历史 token、hotwords、prefix | 非法 task/语言 `ValueError`；prompt+`max_new_tokens` 超过 448 `ValueError`；tokenizer 缺失会尝试 Hub `from_pretrained` | `tokenizer.py:12-40`；`transcribe.py:1532-1565` |
| 7 | `generate_segments` | 生成 seek clips，逐 30 秒窗口 `encode`；按窗口生成结果、跳过 no-speech、切 timestamp token、维护历史 prompt | CT2 异常传播；无显式取消/超时；异常中断时没有 checkpoint；无文本 segment 被跳过 | `transcribe.py:1103-1389` |
| 8 | `generate_with_fallback` | 首温度 0 用 beam，非零用 sampling；按 compression/logprob/no-speech 判断是否重试，全部失败取候选 | fallback 只发生在遍历 generator 时；silence 条件可阻止 fallback；所有温度失败也会选一个候选而非抛质量错误 | `transcribe.py:1402-1530` |
| 9 | `add_word_timestamps`/`find_alignment`（可选） | CT2 `align` → token 跳变时间 → 词边界/概率，再合并标点与修正长词 | 对齐异常传播；空 token 有专门空结果分支；无独立校准或质量门禁 | `transcribe.py:1567-1766` |
| 10 | `restore_speech_timestamps`（VAD 时） | `SpeechTimestampsMap` 把拼接音频时间映射回原始时间；结果逐个 yield | mapping 依赖 chunk 顺序与边界；词按中点固定到 chunk，segment 按词或 end 映射 | `vad.py:280-319`；`transcribe.py:1844-1870` |
| 11 | generator 交付 | yield `Segment`；`TranscriptionInfo` 在函数前半段已创建并返回 | 只调用 `transcribe` 不会完成推理；遍历期异常由调用方接收；库不写库、不发事件、不保存断点 | `transcribe.py:1005-1022,1344-1370`；`README.md:150-155` |

### 7.2 批量 `BatchedInferencePipeline`

```text
transcribe
  → decode_audio / VAD 或显式 clips / collect_chunks
  → 每块 FeatureExtractor；必要时 detect_language
  → np.stack(pad_or_trim(features))
  → _batched_segments_generator
      → 每 batch forward
          → get_prompt（只基于初始 prompt/hotwords）
          → encode(features)
          → 可选 CT2 detect_language
          → CT2 Whisper.generate（batch）
          → _split_segments_by_timestamps
          → 可选 add_word_timestamps（维护 last_speech_timestamp）
          → Segment dataclass
  → 非显式 clip 时 restore_speech_timestamps
```

批量 `forward` 的 `generate_segment_batched` 将 encoder output 和 prompts 一起传给 CT2，首个温度生成一次（`transcribe.py:174-252`）；没有单路 `generate_with_fallback` 的逐温度质量重试。`_batched_segments_generator` 正常结束才把 `last_speech_timestamp` 重置为 `0.0`（`transcribe.py:580-617`），因此异常中断后的同一 pipeline 实例可能留下可变状态。

## 8. 关键小节点明细

| 节点 | 前置条件 | 具体职责与状态变化 | 读写对象/调用者/被调用者 | 并发与失败恢复 | 证据 |
|---|---|---|---|---|---|
| `WhisperModel.__init__` | CT2、tokenizers、模型文件可用 | 解析模型来源，构造 CT2 模型，加载 tokenizer/config，建立 extractor 与时间常量 | 读 Hub/cache/目录；被调用方创建并持有 `self.model`、`hf_tokenizer`、`feature_extractor` | `num_workers`/device_index 交给 CT2；没有 rollback/close；失败由构造调用方处理 | `transcribe.py:671-722` |
| `decode_audio` | 可读媒体或 file-like | 建 resampler，聚合帧，flush，转 float32；显式 `gc.collect()` 释放 PyAV resampler 关联对象 | `av.open`/AudioFifo/BytesIO/numpy；被两个 transcribe 和公共导出调用 | 帧级 `InvalidDataError` 被跳过；容器用 `with`；无重试/超时 | `audio.py:37-76,79-109` |
| `get_speech_timestamps` | 1-D float waveform、VAD asset、onnxruntime | 每 512 sample 窗口运行 Silero，按阈值/静音/最大时长产生 sample ranges | 调用缓存的 `SileroVADModel`；返回普通 dict，不写盘 | 依赖缺失 RuntimeError；模型/session 异常传播；无取消；空结果合法 | `vad.py:51-217` |
| `collect_chunks` | speech chunk 顺序正确 | 拼接 speech audio，按 `max_duration` 分块，维护 offset/duration/原 chunk | 读 numpy、分配多个 concatenate 数组；被单路/批量 VAD调用 | 空 chunks 返回一个空数组和零时长 metadata；无资源回滚 | `vad.py:220-277` |
| `SpeechTimestampsMap` | chunk 有 start/end 且顺序正确 | 预计算删去静音量和等价 chunk end，把内部时间转回源时间 | 只读内存列表；被 restore wrapper 调用 | 越界/空 chunk 语义未提供强保护；映射异常传播 | `vad.py:280-319` |
| `generate_segments` | 特征、tokenizer、options、CT2 encoder 可用 | seek 循环、prompt 历史、fallback、no-speech、timestamp split、可选对齐，yield 结果 | 读 numpy/StorageView，写局部 token/状态；调用 encode/generate/align | Python generator 可关闭；无显式 cancel/timeout/checkpoint；异常后 pbar/状态清理不由 finally 保证 | `transcribe.py:1103-1389` |
| `generate_with_fallback` | encoder output、合法 prompt、温度列表 | 质量阈值选择候选，保存所有结果，最终返回一个结果 | 调用 `self.model.generate`；不写外部状态 | 每温度串行重试；CT2异常直接中止，不进入下一温度；全部失败仍选最高 logprob | `transcribe.py:1402-1530` |
| `find_alignment` | text token、encoder output、帧数 | CT2 align，按 token jumps 计算词时间和平均概率 | 调用 CT2 `align`、Tokenizer 词切分；返回 dict 列表 | 空文本返回空 list；其余异常传播；无质量阈值 | `transcribe.py:1698-1766` |
| `_batched_segments_generator` | features 已批处理 | 每 batch 调 forward，创建并 yield Segment，更新进度；正常末尾重置共享状态 | 读 `BatchedInferencePipeline.last_speech_timestamp`；调用 forward | pipeline 状态非线程安全证据不足；异常中止可能不 reset/pbar close | `transcribe.py:580-617` |

## 9. 资源生命周期与所有权

| 资源 | 创建/载入 | 正常释放 | 业务失败/取消/超时 | 宿主崩溃/残留与验证 |
|---|---|---|---|---|
| 输入文件、BinaryIO | 调用方传入；`decode_audio` 用 `av.open` 打开 | `av.open` context 关闭 container；传入 file-like 不由库关闭的契约未显式承诺，接入方应自行持有 | 解码异常时 context 负责 container 清理；没有 decode timeout 或 kill | 进程崩溃由 OS 关闭 fd；调用方应验证自有句柄/临时文件 | `audio.py:46-64` |
| PyAV resampler/FIFO/raw buffer | `AudioResampler`、`AudioFifo`、`BytesIO` | 函数末尾 `del resampler; gc.collect()`；局部对象随函数结束 | 发生未捕获异常时不保证走到显式 `gc.collect`；没有 finally | 不产生持久文件；内存由进程回收，无法靠库 API查询 | `audio.py:37-69,91-108` |
| waveform/features/StorageView | numpy decode、FeatureExtractor、`get_ctranslate2_storage` | 局部引用释放/GC；generator 期间保持所需窗口与 encoder output | 取消 generator 后由引用关系回收；无显式内存预算或清理钩子 | 崩溃由 OS 回收；GPU/CPU缓存由 CT2/进程管理，未提供现场清理接口 | `feature_extractor.py:198-230`；`transcribe.py:1391-1400` |
| Whisper CTranslate2 模型/模型文件 | Hub snapshot、本地目录或 `files`；构造 `ctranslate2.models.Whisper` | 无 `close()`；对象/进程生命周期结束时由 Python/CT2/OS 回收；Hub cache 保留 | 无模型卸载、热切换、请求级超时/取消；模型异常由上层决定是否重建实例 | 崩溃不会损坏已完成 cache 的事务语义由 Hub 提供，未在本库验证；需人工检查缓存 | `transcribe.py:674-698`；`utils.py:99-115` |
| tokenizer/config | 模型目录文件、内存 bytes 或 fallback Hub `from_pretrained` | 跟随 model 对象/GC；无 close | 缺文件可能触发外部网络 fallback；JSON 错误仅 warning 后返回原 config | 崩溃无库级恢复；离线接入应预置 tokenizer 并 `local_files_only` | `transcribe.py:700-745` |
| Silero VAD ONNX session | `get_vad_model()` 首次调用，`@lru_cache` 单进程缓存；CPU provider | 没有项目级释放协议；函数包装器暴露 `cache_clear()`，缓存通常保持到进程结束或外部清 cache | ONNX 异常传播；取消只能在 Python 调用边界处理 | 宿主崩溃由 OS 回收；长驻进程会长期保留 session，需进程级重启/现场观察 | `vad.py:322-385` |
| tqdm/progress 与 logger | transcribe generator 创建 pbar；logger 为标准 logging | 正常批量/单路末尾 `pbar.close()`；无 finally | generator 异常/外部关闭时 close 语义未由代码显式保证；不应把进度打印当完成证据 | 无持久状态；日志可能只反映已进入节点，不反映真实结果落盘 | `transcribe.py:1151,1385-1389,583-617` |
| Segment/Word/Info | generator 局部创建，调用方接收 | 调用方消费后释放或序列化 | 部分 yield 后异常时只能得到部分结果；库无 checkpoint/回滚 | 崩溃丢失尚未由调用方保存的结果；需上层逐 segment 持久化 | `transcribe.py:1344-1370` |

**统一结论**：库内没有数据库、队列、HTTP session、事务、子进程管理或端口。不存在库级“回滚任务/恢复断点/杀掉当前请求”的机制；要做生产接入，必须把模型/音频/临时文件/结果和任务状态的所有权放在外层适配器，并为正常完成、业务失败、主动取消/超时、宿主崩溃分别建立现场清理与恢复证据。

## 10. 失败、超时、取消、崩溃矩阵

| 场景 | 当前源码行为 | 是否自动恢复/重试 | 接入方必须补的语义 | 证据/状态 |
|---|---|---|---|---|
| 模型别名非法/Hub repo 格式不合法 | `download_model` 抛 `ValueError` | 否 | 配置预校验；不可盲目重试 | 已静态核对：`utils.py:81-89` |
| Hub 网络、鉴权、缺文件、revision 不可用 | Hugging Face 异常向上抛 | 否（Hub cache 语义除外） | 本地预热、revision 锁定、退避/超时、失败状态和 cache 校验 | 未实测外部 Hub |
| tokenizer/config 缺失或 JSON 坏 | tokenizer 可能从 Hub fallback；preprocessor JSON 坏时 warning 后使用当前 config | 仅隐式 fallback | 离线模式必须预置文件并验证 hash/版本；不要把 warning 当成功 | 已静态核对：`transcribe.py:700-745` |
| PyAV 媒体错误/空输入 | 个别 `InvalidDataError` 帧跳过；其他异常传播；空 waveform 可返回空结果 | 否 | 输入格式/时长校验、错误分类、上层超时 | 空音频有测试源码，未本轮执行 |
| 缺 `onnxruntime` 或 ONNX session 失败 | 开启 VAD 时 `RuntimeError`/session 异常 | 否 | provider 预检，按能力降级或明确失败 | 已静态核对：`vad.py:329-348` |
| VAD 无 speech chunks | `collect_chunks` 返回空数组/零 duration；批量可能产生空结果；单路拼接空 waveform | 否 | 业务上区分“无语音”与“失败”，保留 info/状态 | 测试覆盖意图存在，未本轮实测 |
| 长音频无 VAD、无 clip | 单路抛 `RuntimeError`，要求 VAD 或 clip | 否 | 明确切片策略，不把异常当空结果 | 已静态核对：`transcribe.py:913-919` |
| 非法 task/language | `Tokenizer` 抛 `ValueError` | 否 | 参数契约预校验 | 已静态核对：`tokenizer.py:21-32` |
| prompt + max_new_tokens 超过 `max_length=448` | 单路/批量抛 `ValueError` | 否 | 限制 prompt、记录拒绝原因 | 已静态核对：`transcribe.py:198-207,1421-1430` |
| 低质量/重复/疑似静音 | 单路按 compression/logprob/no-speech 选择下一温度；全部失败仍选最佳候选；批量只首温度 | 单路有限 fallback；批量无同等 fallback | 把“返回 Segment”与“质量通过”分开，建立质量门禁/重跑策略 | 已静态核对，未用模型实测阈值 |
| CT2 encode/generate/align、CUDA OOM/驱动错误 | 异常传播，中断当前 generator | 否；CT2 异常不触发 temperature fallback | 捕获分类、隔离 worker、模型重建、GPU 资源回收与重试上限 | 未实测硬件路径 |
| generator 未遍历/主动 close | 推理可能尚未发生，或停止后续 Python 迭代 | 否；无底层 cancel API | 调度器必须消费或明确取消，记录 partial/aborted | README 明示 lazy，未实测 close 语义 |
| Python 线程/宿主超时 | 库没有 timeout 参数、取消 token、信号处理或 checkpoint | 否 | worker 进程隔离，超时 kill/reap，重启后从输入重做或从外层 checkpoint 续作 | 源码未发现进程治理 |
| 进程崩溃/机器掉电 | 未保存的 generator 结果丢失；模型/VAD 内存由 OS 回收；cache 是否完整由 Hub | 否 | 原子结果写入、输入/模型 revision 记录、重启恢复、残留/锁验证 | 未做崩溃注入实验 |
| 部分结果后异常 | 调用方可能已收到前若干 `Segment`，库不回滚、不标记完成 | 否 | 每段持久化时写 offset/id 与任务状态，完成标记只能由消费结束产生 | 当前库无持久化 |
| benchmark API 漂移 | `evaluate_yt_commons.py` 的 `device` 参数与当前批量构造器不符，预期 TypeError | 否 | benchmark 执行前做签名一致性检查；本任务不修 benchmark | 已静态核对：`benchmark/evaluate_yt_commons.py:52-54` |

## 11. 真假验证分级（防假绿 L0-L4）

| 等级 | 可证明内容 | 本项目证据 | 不能冒充的结论 |
|---|---|---|---|
| **L0 存在性** | 文档、源码路径、测试/CI/资产文件存在 | 本轮读取 `ARCHITECTURE.md`、旧细探、源码、测试、CI；目标目录未建立 codegraph | 不证明代码可导入、测试通过或模型可用 |
| **L1 静态实现** | 符号、调用关系、分支和数据结构在当前文件中存在 | `transcribe.py` 1941 行、`audio.py`/`vad.py`/`utils.py`/测试等源码逐段核对 | 不证明外部依赖版本兼容、实际 CT2 输出或资源释放现场 |
| **L2 历史/声明验证** | CI 命令、README 示例、测试意图和远程基线被记录 | `.github/workflows/ci.yml:13-90`；README 使用示例；Git 本地/远程同 commit | 不证明 CI 在本轮或本机通过；README benchmark 不等于本机 benchmark |
| **L3 本轮真实执行** | 本轮命令实际退出码为 0，并给出可复现输出 | 见第 12 节；仅列现场 Git/静态文档检查，未安装依赖、未运行推理 | 不把静态 AST/Markdown 检查当端到端转写 |
| **L4 外部依赖/硬件端到端** | 真实模型、PyAV、HF、ONNX、CT2、CUDA 或完整 pytest 实测 | **未执行**：没有下载模型、安装依赖、运行全量 pytest、GPU/CUDA、Hub 或 ONNX 推理 | 不得声称“模型能跑”“VAD 通过”“GPU 可用”“性能达到 README” |

## 12. 测试、CI 与本轮验证

### 12.1 仓库已有测试与 CI（存在不等于通过）

CI `.github/workflows/ci.yml:13-90` 在 Python 3.9 上执行：

1. `pip install wheel`、`pip install -e .[dev]`；
2. `black --check .`；
3. `isort --check-only .`；
4. `flake8 .`；
5. `pytest -v tests/`；
6. 依赖通过后 `python3 setup.py sdist bdist_wheel`，tag 时发布 PyPI。

测试源码覆盖真实模型和音频样本的集成路径：

- `tests/test_transcribe.py:9-315`：语言、单路/批量、空音频、prefix、VAD、立体声、多语言、hotwords、签名、单调时间戳、clips；
- `tests/test_tokenizer.py:6-121`：抑制 token、unicode 词切分；
- `tests/test_utils.py:6-29`：模型清单和 HF 下载/cache；
- `tests/conftest.py:6-18`：音频 fixture。

这些测试中的 `WhisperModel("tiny")` 会加载或下载模型（例如 `test_transcribe.py:10-16`），所以本任务不在未准备依赖和网络/模型条件下擅自运行。

### 12.2 本轮实际验证

| 检查 | 命令/证据 | 退出码 | 结论 |
|---|---|---:|---|
| 项目身份、Git、远程基线 | `git status --short && git rev-parse HEAD && git ls-remote origin HEAD refs/heads/master` | 0 | 目标根、HEAD 与远程 master 同为 `ed9a06cd...`；原有旧细探保留 |
| 源码结构取证 | 读取 `faster_whisper/*.py`、测试、README、setup、CI、benchmark | 0（工具读取成功） | L0/L1 静态证据，非运行通过 |
| 目标架构文档写入 | 仅写 `/faster-whisper/ARCHITECTURE.md` | 0（写入工具确认 hash） | 本任务唯一修改目标；未改旧细探/源码 |
| 端到端推理、全量 pytest、格式 CI、GPU/HF/VAD | 未执行 | — | L4 未验证，不得宣称通过 |

## 13. 吸收与不吸收裁决

### 已吸收进本文件

旧 `细探-faster-whisper.md` 中关于以下事实均已吸收并以当前源码路径补强：

- MIT/Python/CTranslate2 定位、Whisper 重实现、量化与多语言边界；
- `WhisperModel.transcribe`、可选 VAD、Segment/时间戳主流程；
- CTranslate2 作为核心 provider/推理引擎；
- ASR 适配器、独立进程、模型权重与 CUDA/资源边界的接入提醒；
- 旧细探原有文本流程图和“不是 LLM prompt”的事实（这里以 tokenizer/prompt 说明澄清：存在 Whisper token prompt，但不是对话式 LLM 提示词系统）。

### 不直接采信/改为待核

- “同精度快 4 倍”“更省内存”只保留为 README/历史 benchmark 声明，不写成本轮实测；
- “8-bit CPU/GPU”保留为 CT2/README 能力边界，不推断本机设备可用；
- “tests/（基准）”更正为测试与 benchmark 分离：`tests/` 是集成测试，`benchmark/` 才是速度、内存、WER 和 YouTube Commons 评估；
- “多提供者”不作为本库已实现事实：当前代码只有 CTranslate2 主推理，Silero/ONNX 是 VAD provider，不存在 FunASR/WhisperX 路由或统一 provider 注册表；
- “应独立进程”保留为平台接入建议，不冒充库内已有进程隔离。

### 保留旧细探的处理

`细探-faster-whisper.md` **按用户要求没有删除**。它是历史摘要与线索，若与本文件或当前源码冲突，以当前源码与本文件的证据路径为准；后续不要在两个文件并行维护架构事实。

## 14. 剩余风险与后续复核点

1. 未验证 Python 依赖、CT2、PyAV、tokenizers、ONNX Runtime 与当前 macOS/硬件环境的可导入和兼容性。
2. 未下载或锁定任何实际模型 revision，无法确认 Hub cache、tokenizer fallback、离线 `local_files_only` 和模型文件完整性。
3. 未执行单路/批量真实推理，因此 VAD 时间恢复、word alignment、空音频、批量并发和阈值行为仍只有源码/测试意图证据。
4. 未实测取消 generator、线程复用、`num_workers`/多 GPU、OOM、驱动错误、进程 kill/reap、崩溃恢复或 cache 残留。
5. 批量 pipeline 的 `last_speech_timestamp`、FeatureExtractor 的可变 `chunk_length` 状态和原地修改 `vad_parameters` 需要上层实例隔离/复制并配套并发测试。
6. benchmark 构造器漂移尚未修复；README 的历史性能表与当前包版本也存在口径差异。
7. 需要上层适配器定义可序列化契约：模型 id/revision、设备/量化、语言/task、VAD、输入引用、Segment 顺序、部分结果、完成/失败/取消状态和错误分类。

## 15. 最终架构结论

`faster-whisper` 的可验证核心链是：

```text
输入音频
 → PyAV decode_audio
 →（可选）Silero VAD + collect_chunks
 → FeatureExtractor
 → Tokenizer/语言检测/prompt
 → CTranslate2 encode + generate/align
 → timestamp/fallback/word 修正
 → Segment/Word + TranscriptionInfo generator
```

它适合作为离线/批量 ASR 推理能力或独立适配器的底层实现，不应被误当成业务 API、任务编排器、持久化系统或原生 streaming 引擎。真正接入前的 P0 是：锁定模型与依赖版本、隔离模型/请求资源、消费 generator、补齐错误/超时/取消/崩溃恢复和逐段持久化，并用 L3/L4 真实证据验证，而不是把源码存在、CI 声明或 README benchmark 当作假绿。

## 16. 第三轮通用底座映射（仅形成接入裁决，不改生产底座）

本节把当前源码能力映射到“支持库—媒体转写模块—模型提供者—运行核心”四个职责边界。它是平台后续需求登记、能力复用搜索和装配计划的输入，不表示本仓库已有这些平台组件，也不授权在本仓库内新增第二套任务系统。所有“应”字样都是接入约束；当前项目事实仍以第 1—15 节的源码证据为准。

### 16.1 能力事实到四层 owner

| 能力/事实 | 支持库（公共契约与原子能力） | 媒体转写模块（领域编排） | 模型提供者（faster-whisper/CTranslate2 边界） | 运行核心（通用治理） |
|---|---|---|---|---|
| 模型装载 | 定义 `模型引用`（model id/path、revision、来源、摘要、文件清单、离线策略）和统一错误/结果形状；不 import CTranslate2 | 只提交模型需求，不解析 Hub 别名、不持有下载会话 | `WhisperModel.__init__` 的本地目录/内存文件/别名解析、tokenizer/preprocessor 加载、CTranslate2 `Whisper` 构造；证据 `transcribe.py:620-722` | 给装载任务分配进程/CPU/GPU/内存租约、截止时间和健康记录；失败后回收，不在核心内实现 Whisper |
| 外部模型下载 | 提供模型制品、缓存、revision 锁定、摘要校验和原子落盘契约；可复用统一制品/缓存能力 | 只声明“需要哪个模型”，禁止直连 `huggingface_hub` | 通过模型制品提供者调用 Hub；`utils.download_model` 只允许在这一边作为兼容适配，不向业务暴露 Hub 对象；证据 `utils.py:49-115` | 下载超时、并发去重、凭证脱敏、缓存租约、下载进程/连接清理和残留核验；不维护第二份 `_MODELS` 或 Hub 客户端 |
| 音频解码 | 若平台已有媒体输入/安全解码原子能力，复用其输入引用、格式限制和临时文件契约 | 编排“输入媒体→可转写音频”并保留输入与输出关联 | 当前 `audio.decode_audio` 的 PyAV、16 kHz/mono/float32 转换；证据 `audio.py:37-76` | 对大文件、临时目录、文件句柄、解码子进程设资源上限和回收；不把音频字节写入任务状态库 |
| 单路转写 | 统一请求、Segment/Word/TranscriptionInfo、错误码和版本契约 | 暴露唯一领域入口，装配参数、消费 generator、规范化结果、逐段提交状态 | `WhisperModel.transcribe`：语言检测、FeatureExtractor、Tokenizer、30 秒窗口、fallback、时间戳；证据 `transcribe.py:747-1022,1103-1530` | 调度、租约、总/阶段超时、取消、进程隔离、结果幂等和异常现场；不复制 `generate_segments` |
| 批量转写 | 定义 batch 请求与逐项结果的关联键、顺序/部分成功/重试契约 | 负责输入项编排、`batch_size` 策略、结果聚合和批次状态投影 | `BatchedInferencePipeline` 仅把一个请求的 features 分批，执行 CT2 batch generate、切段和可选对齐；证据 `transcribe.py:111-617` | 将批次拆成可监督的任务/工作单元，限制并发、GPU 显存、队列长度并汇总状态；不能把 provider 的 `batch_size` 当平台队列 |
| VAD | 定义 `VadOptions`、speech chunk、原始时间映射和“无语音”结果语义 | 决定是否启用 VAD、显式 clip 与 VAD 的优先级、把 VAD 元数据纳入转写结果 | 当前 Silero ONNX CPU 实现、`get_speech_timestamps`、`collect_chunks`、`SpeechTimestampsMap`；证据 `vad.py:51-319,322-385` | 为 ONNX session 的 CPU/内存/进程生命周期做租约和清理；不在运行核心重新实现 VAD 算法 |
| 词级时间戳 | 统一 `Word(start,end,word,probability)` 数据结构、精度和缺失语义 | 接收 `word_timestamps` 选项、校验段/词时间单调性并输出统一结构 | `align` + dynamic time warping、`find_alignment`、`add_word_timestamps`、标点合并；证据 `transcribe.py:1567-1766` | 为对齐计算提供与转写相同的 deadline/cancel/资源监督；不另接 WhisperX/第二套 forced alignment 链路 |
| CPU/GPU/CTranslate2 | 约束设备/量化/线程参数的可序列化表示，不假设某宿主一定有 CUDA | 只声明资源需求和可接受降级策略，不直接探测/切换设备 | 将 `device`、`device_index`、`compute_type`、`cpu_threads`、`num_workers` 传入 CT2；`encode/generate/align` 是 provider 实现；证据 `transcribe.py:689-698,1391-1400,1446-1459,1709-1715` | GPU/CPU/显存/线程配额、并发租约、OOM 后隔离重建、设备健康与释放；不把 CT2 API 变成运行核心公共 API |
| 任务状态、取消、超时、崩溃 | 定义稳定状态、错误和幂等键 | 维护领域进度（输入项、片段、已输出文本）与业务结果 | 只报告 provider 执行进度/异常，不拥有任务数据库、取消令牌或重试策略 | 复用唯一任务系统、监督器、进程组回收、租约、证据账本和重启恢复；这是平台补齐缺口的唯一 owner |

**边界结论**：模型装载、VAD 执行、word alignment 和 CT2 推理属于同一个模型提供者的实现闭包；媒体转写模块只做一次领域编排和结果归一化；任务/资源/恢复属于运行核心。不要把 `WhisperModel.transcribe` 再包一层做成另一个“ASR 内核”，也不要让运行核心知道 `temperature`、timestamp token 或 Silero 阈值的算法细节。

### 16.2 唯一接入调用链

建议以现有能力目录检索结果为准确定最终能力 id；下列名称是本项目的**候选语义**，不是已经登记的生产 id，未完成唯一性搜索前不得注册：

```text
调用方/项目适配层
  → 媒体转写模块：提交转写（输入引用、模型引用、单路/批量、VAD、词级时间戳）
  → 唯一能力调用器/注册表：媒体转写.转写
  → 运行核心：创建任务、获取租约、排队、截止时间、监督 worker
  → 模型提供者注册表：faster-whisper provider
  → 模型制品支持库：解析别名/revision、命中或原子准备缓存
  → 外部模型下载提供者（需要时）：Hugging Face snapshot_download
  → provider worker：WhisperModel / BatchedInferencePipeline
  → PyAV →（可选）Silero/ONNX VAD → FeatureExtractor/Tokenizer
  → CTranslate2 encode/generate/align
  → provider 结果 → 媒体模块统一 Segment/Word/Info
  → 运行核心写状态/证据、释放租约 → 调用方读取结果
```

固定规则：

1. 业务代码、媒体模块和任务调度器均不得直接 `import faster_whisper`；只有模型提供者适配层可以绑定本仓库版本。
2. 媒体模块不得直接访问 `huggingface_hub`、CT2、CUDA、ONNX Runtime 或模型 cache；它只依赖公开能力契约。
3. 模型下载、模型装载、单路/批量推理、VAD 和词级对齐是同一 provider 的内部能力组合；对外只暴露一个版本化转写契约，避免五条并行注册路径。
4. `BatchedInferencePipeline` 的 `batch_size` 只是一次转写请求内的特征批大小，不等于任务队列批次；批次状态由运行核心/媒体模块产生，不能从 generator 是否返回推断。
5. provider 不能把 Hub cache、GPU 对象、CT2 `StorageView`、ONNX session 或 Python generator 穿透到公共契约；跨边界只传可序列化的引用、参数、结果和诊断。
6. 如已存在通用模型制品、异步任务、资源监督或进程提供者能力，优先升级其契约/注册表；没有完成需求登记、能力搜索、占用租约和验收契约前，不新建同名支持库或第二个任务中心。

### 16.3 单路、批量、VAD、词级时间戳的契约落点

| 契约项 | 统一外部语义 | provider 内部事实/差异 | 上层必须显式处理 |
|---|---|---|---|
| 单路 | 一个输入引用对应一个可遍历结果流和一份 `TranscriptionInfo` | generator 是惰性的；调用 `transcribe` 只拿到 generator，不代表推理完成 | 消费结束才写“成功”；提前关闭、部分 yield、异常分别写 `取消/部分失败/失败`，不得把返回 tuple 当完成 |
| 批量 | 一个 batch id 下有总数、项 id、顺序、每项结果和汇总状态 | features 按 `batch_size` 分组；批量只取首个 temperature，未实现单路同等 fallback；异常后 `last_speech_timestamp` 可能不 reset | 不跨请求复用带可变状态的 pipeline；复制 `vad_parameters`；按 item/offset 幂等落盘；批量聚合不可覆盖单项失败 |
| VAD | 选项、chunk 原始 sample 区间、拼接后 offset、原始时间恢复、无语音 | 单路默认关闭，批量默认开启；显式 clip 优先并跳过 VAD；`collect_chunks` 空 chunks 仍产生空音频元数据 | 固定默认值与版本；区分“无语音”和 provider 失败；校验恢复后的段/词时间落在输入范围 |
| 词级时间戳 | 每个词有 start/end/text/probability，缺失时 `words=null` | 依赖 CT2 `align` 和 tokenizer 词切分；标点会合并，VAD 后还要经过 chunk 映射 | 统一精度、单调性、段词包含关系；对齐失败不能静默退化成“可信词时间”，要写诊断/降级标识 |
| 质量 fallback | 质量策略是单路 provider 的可选内部行为 | 单路按 temperature 列表重试；批量仅首温度 | 质量未通过与系统失败分开；任何自动降级/重试都记录 attempt、最终 temperature 和原因 |

### 16.4 批量状态、取消、超时、OOM 与崩溃回收

当前仓库没有任务状态存储、取消 token、API timeout、checkpoint、子进程组或 OOM recovery（见第 9—10 节）。以下是接入底座必须补在运行核心/媒体模块的契约，不能伪装成 faster-whisper 已实现：

#### 状态与幂等

```text
创建 → 排队 → 准备模型 → 转写中 → 输出中 → 成功
  │        │          │          │       ├→ 业务失败
  │        │          │          │       ├→ 超时
  │        │          │          │       ├→ OOM
  │        │          │          │       ├→ provider 崩溃
  │        │          │          │       └→ 取消请求 → 已取消
  └→ 参数拒绝/模型不可用（终态）
```

- 批次记录至少包含 `batch_id`、`item_id`、输入引用/摘要、模型 id+revision、provider 版本、attempt、状态、已发段序号/offset、错误码、开始/结束时间和资源租约 id；不要把完整音频或模型对象写进状态库。
- 汇总状态由 item 状态计算：`pending/running/succeeded/failed/cancelled/timed_out/oom/crashed` 必须可区分；部分成功不是成功，也不是把失败项吞掉。
- 结果写入必须以 `(batch_id,item_id,segment_id,offset)` 或等价幂等键去重，且“完成”标记晚于 generator 完整消费和结果落盘。重试只能创建新 attempt，不覆盖旧诊断。
- `last_speech_timestamp`、FeatureExtractor 的可变 chunk 参数和输入 `vad_parameters` 都属于 request-local 状态；不得在并发任务间共享或原地改调用方对象。

#### 取消与超时

- 排队任务：从队列移除并原子标记 `已取消`，不能启动模型下载。
- 已运行任务：取消请求先写入持久状态，再由 worker 在安全边界检查；由于当前 CT2 没有可靠的请求级 cancel，生产接入必须在独立进程组中执行，无法靠 `generator.close()` 宣称底层已停止。
- 至少拆分下载、模型装载、单项推理和整批四类 deadline；超时路径是“标记超时 → SIGTERM/宽限 → `killpg`/SIGKILL → `wait` 回收 → 读回进程、句柄、临时目录、租约现场”，不可只调用线程 `Future.cancel()`。
- 取消/超时与自然完成竞态时，以先落账的终态为准，所有写入幂等；已发出的 segment 只能标为 partial，不得删除后假装从未产生。

#### OOM 与 provider 崩溃

| 故障 | provider 当前事实 | 运行核心接入动作 | 是否允许重试 |
|---|---|---|---|
| GPU/CTranslate2 OOM | 异常向上传播；没有自动降 batch、换量化或重建 | 将 worker 归为 `OOM`，停止复用该进程，释放 GPU/CPU 租约，读回子进程/共享内存/临时文件；必要时按预声明策略用更小 batch 新 attempt | 仅在输入可重放、结果幂等、重试上限内；降级设备/量化必须显式记录，不得隐藏 |
| Python/CPU 内存不足 | 当前库不提供预算或分类保证 | 隔离并回收 worker，记录峰值/估计资源与输入大小；不能把 `MemoryError` 当普通空结果 | 有界；连续 OOM 应熔断该模型/设备组合 |
| CT2/ONNX/驱动错误 | `encode/generate/align` 或 VAD session 异常直接传播 | 标记 provider 健康失败，按错误可重试性决定重启；不在同一疑似损坏 session 上继续请求 | 仅对明确瞬态故障；参数/模型损坏不重试 |
| worker 崩溃/信号退出 | 当前仓库无子进程，宿主崩溃会丢未保存 generator 结果 | 独立进程组 `wait`、记录退出码/信号、清理句柄和租约；新进程重新装载同一 model revision | 只从最后一个已提交 offset 重放；无 checkpoint 则从 item 起点重做并靠幂等去重 |
| Hub 下载中断/缓存半成品 | `snapshot_download` 异常向上传播，库不提供事务回滚证明 | 下载到临时制品目录，校验文件清单/摘要后原子发布；失败清理临时目录，保留诊断 | 网络瞬态可有界退避；鉴权、revision、摘要失败不可盲重试 |

### 16.5 CPU/GPU、CTranslate2、VAD 与模型制品的资源责任

| 资源 | 当前源码所有权 | 平台归属与验收 |
|---|---|---|
| CT2 model / tokenizer / FeatureExtractor | `WhisperModel` 实例持有；无 `close()`、卸载或热切换 API | provider worker 持有；运行核心按模型 revision 建实例池/租约，终态销毁进程或显式证明可复用；禁止跨任务泄漏 provider 对象 |
| CPU 线程与 batch 内存 | `cpu_threads`、`num_workers` 传给 CT2；numpy features/StorageView 为局部内存 | 运行核心登记线程/内存预算，provider 报实际/估计峰值；batch size 只在预算内调度，OOM 后不继续复用原 worker |
| GPU device/显存 | CT2 接收 `device`/`device_index`/`compute_type`；多 GPU 时 encoder 可回 CPU | 运行核心分配 GPU lease、设备互斥/并发上限、健康状态；provider 只实现设备参数，不实现全局 GPU 调度 |
| Silero ONNX session | `get_vad_model` `lru_cache` 单进程缓存，固定 `CPUExecutionProvider`，线程=1；无 clear/close | provider worker 内缓存；运行核心以进程生命周期回收，长驻模式必须有重启/清缓存策略和现场验证 |
| PyAV container/resampler/FIFO | `decode_audio` 用 context 关闭 container，部分 resampler 清理依赖函数尾部 | 模块/worker 负责输入句柄与临时文件；异常、超时、强杀后必须检查 fd/临时目录，不能只看 Python 返回值 |
| HF cache / model artifact | Hub 管缓存，当前库未做摘要事务或完整性核验 | 模型制品支持库维护 revision、文件清单、摘要、临时目录与原子发布；运行核心只管租约、并发和故障恢复 |
| Segment/Word 结果 | generator 局部 yield，库不持久化 | 媒体模块逐段转公共 DTO；运行核心/权威状态记录提交 offset 和终态，崩溃后只重放未提交部分 |

### 16.6 第三轮复用/升级/新建/废弃裁决

| 裁决 | 结论 | 理由与边界 |
|---|---|---|
| 吸收 | faster-whisper 的模型装载参数、单路/批量、VAD chunk 映射、词级对齐和 CT2 资源事实 | 源码证据充分，作为模型 provider 的实现输入；不把 README 性能或测试声明提升为平台能力 |
| 升级 | 现有媒体转写模块的统一结果/参数契约；现有运行核心的任务、租约、进程组、超时、OOM、崩溃恢复和证据链 | 这几个缺口是接入所必需的通用治理，不应由每个 ASR provider 各写一套；升级前先查能力目录与占用租约 |
| 升级 | 现有模型制品/缓存支持库，增加 model id+revision+文件摘要+离线/下载状态契约 | `download_model` 的 alias/Hub 调用只能成为 provider 适配实现；下载原子发布和缓存完整性不能留在媒体模块 |
| 复用 | 唯一 provider 注册表/能力调用器、统一结果/错误、资源监督和诊断中心 | `faster-whisper` 只登记一个 provider 版本；provider 对象不穿透公共契约 |
| 隔离 | 当前 `BatchedInferencePipeline`、Silero ONNX、CT2 模型实例放在 provider worker | 当前项目无取消/超时/崩溃治理；进程隔离是接入安全边界，不是本仓库已经实现的事实 |
| 废弃/禁止 | 业务项目直调 `WhisperModel`、各模块直连 Hugging Face、各 provider 自建 batch queue/状态库/下载器、另接 VAD 或 forced-alignment 链 | 会形成多条不可审计链、重复缓存/资源调度和结果漂移；历史入口如需兼容，只在唯一模块入口归一化 |
| 待核 | 最终能力 id、现有平台是否已有模型制品/媒体转写/异步任务/进程提供者、真实 CUDA/ONNX 宿主矩阵 | 本项目代码图不可用且第一次 `project_context` 错绑到 `华世王镞_v3`；需平台 owner 现场搜索后再定注册名，不以本档案猜测补底座 |

**单链路验收条件**：同一模型、同一输入、同一 revision 的单路与批量可以有明确的 provider 内部差异，但必须通过同一个媒体转写模块契约、同一个任务/资源治理链和同一个结果/证据 owner；不能因为批量、VAD 或词级时间戳分别再造入口、状态表、缓存或错误翻译。

### 16.7 第三轮 L0-L4 验收矩阵

| 能力 | 当前最高证据 | L3 必须真实执行 | L4 必须真实执行 | 当前结论 |
|---|---|---|---|---|
| 模型 alias/本地目录/Hub revision 装载 | L1：`transcribe.py:671-710`、`utils.py:81-115`；L2：`tests/test_utils.py:12-29`、CI | 预置本地模型目录，CPU 构造并读 tokenizer/preprocessor；验证 invalid alias/离线缺件失败 | 锁定 HF revision，真实下载/缓存命中、摘要/断点/半成品清理，必要时真实 CUDA | 当前未到 L3；不能声称模型装载通过 |
| 单路转写 | L1：`transcribe.py:747-1022,1103-1530`；L2：`tests/test_transcribe.py:14-59` | 本地模型+样本音频，完整消费 generator，检查 info、segment 顺序、部分异常 | 真实外部模型/CPU 与 GPU 对比、质量/资源/长音频 | 当前仅静态/测试意图 |
| 批量转写 | L1：`transcribe.py:111-617`；L2：`tests/test_transcribe.py:62-88` | `batch_size` 多值、空输入、clips/VAD、词时间戳，验证异常后 pipeline 状态不污染 | 真实多任务并发、GPU 显存峰值、OOM 后重建和批次汇总 | 当前未验证；provider batch 不等于任务 batch |
| VAD 与时间恢复 | L1：`vad.py:51-319,322-385`；L2：`tests/test_transcribe.py:118-139` | 本地 ONNX Runtime+包内 asset，检查无语音、chunk 边界、原始时间单调 | 真实长音频、缺 provider、worker 重启后 session/cache 残留 | 当前未验证，VAD 为 CPU provider |
| 词级时间戳/align | L1：`transcribe.py:1567-1766`；L2：`tests/test_transcribe.py:14-42,76-88,247-271` | 完整消费单路/批量并检查词边界、标点合并、VAD 后映射 | 真实设备/长音频、align 异常降级与重试证据 | 当前未验证；无独立校准门禁 |
| 状态/取消/超时/故障回收 | L0/L1 仅能证明源码没有这些接口；第 10 节反向矩阵 | 先以真实 worker/任务监督器做取消、分阶段 deadline、SIGTERM/killpg/wait、残留核验 | GPU OOM、SIGKILL、Hub 中断、解释器重启后幂等恢复和证据对账 | 属平台接入缺口，不得归功于 faster-whisper |
| CPU/GPU/CT2 资源 | L1：`transcribe.py:620-698,1391-1400`；L2：README/requirements | CPU CT2 真实推理、线程/内存峰值与 provider 错误分类 | CUDA/cuBLAS/cuDNN、量化、显存并发/OOM 和设备恢复 | 当前无本机硬件证据 |

L0/L1/L2 的源码、测试、CI 和 README 证据只能证明“存在/实现分支/声明或测试意图”；L3 才能证明本轮命令真实执行，L4 才能证明外部模型、硬件和故障回收。当前本文件没有新增模型下载、推理或 GPU 执行，因此本轮映射结论最高仍是静态/历史证据，不能写成“转写链路已接入平台”。

### 16.8 装配工作包与退出条件

后续若平台 owner 确认需求，按以下顺序装配，且每一步都只能复用现有 owner：

1. **能力盘点**：检索现有媒体转写、模型制品、异步任务、资源监督、独立进程、诊断/证据能力；冻结唯一能力 id、版本、错误、超时、取消和资源契约。命中现有能力则升级，不命中才登记缺口。
2. **公共契约**：冻结模型引用、转写请求、批次/项状态、Segment/Word/Info、错误与幂等键；明确 provider 与媒体模块不得泄漏 CT2/ONNX/HF 类型。
3. **provider 适配**：在独立 provider 环境/worker 中绑定 faster-whisper 版本；模型下载与装载先落临时制品目录，revision/文件摘要验证通过后原子发布；失败必须清临时资源。
4. **媒体模块接线**：只经唯一能力入口编排单路/批量、VAD、word timestamps 和结果序列化；复制入参、逐段提交、对齐失败显式降级，不复刻底层算法。
5. **运行治理**：接入任务状态、租约、阶段 deadline、取消、OOM/崩溃 kill/reap、重试上限和证据；用 item/offset 幂等恢复，不把 provider generator 当 checkpoint。
6. **分层验证**：先 L0/L1 静态契约，再 L2 既有测试/CI 对照，随后 L3 本地模型 CPU 实跑，最后 L4 外部 Hub/CUDA/OOM/崩溃真实验证；任一级未完成都不得向上宣称通过。

**退出条件**：能力目录只有一个转写 owner；模型下载只有一个制品/cache owner；VAD/align 没有旁路实现；任务状态/取消/超时/回收只由运行核心和媒体模块按职责负责；所有外部结果可读回、残留可验证、L3/L4 证据与本档案路径/命令/退出码一致。

## 18. 第二轮深挖收口：CTranslate2、装载、解码、beam/batch、设备与生命周期

本节是第二轮针对底层执行边界的收口。它只描述当前快照的真实实现，不把 CTranslate2、FFmpeg/PyAV、ONNX Runtime 或 GPU 驱动的外部能力扩写成 `faster-whisper` 自己的能力。行号以本轮源码现场为准；若后续上游变化，应重新核对源码而不是沿用本节结论。

### 18.1 CTranslate2 调用边界：一个模型对象、三类执行调用

`WhisperModel.__init__` 只创建一个 `ctranslate2.models.Whisper` 实例，参数是模型目录/内存文件、`device`、`device_index`、`compute_type`、`intra_threads=cpu_threads`、`inter_threads=num_workers` 和额外 `model_kwargs`（`transcribe.py:689-698`）。Python 层没有第二套推理后端、没有 provider 注册表，也没有把 CT2 对象包装为可序列化公共结果。

| CT2 调用 | Python 输入形状/批次 | 传入的关键参数 | 输出消费方式 | 失败与所有权 |
|---|---|---|---|---|
| `Whisper.encode` | 单路特征先扩为 batch 维；批量特征由 `np.stack` 形成 batch | `StorageView`；多 GPU 时 `to_cpu=True` | `StorageView` 继续交给 `generate` 或 `align` | CT2 异常直接上抛；encoder output 只由当前 generator/批次引用，不落盘；`encode` 无独立 close |
| `Whisper.generate`（单路） | `[encoder_output]` 与 `[prompt]`，实际 batch=1 | 公共长度/惩罚/抑制参数；温度 0 用 `beam_size`+`patience`，非零温度用 `beam_size=1`、`num_hypotheses=best_of`、`sampling_topk=0`、`sampling_temperature` | 取返回列表第一个结果的 `sequences_ids[0]`、`scores[0]`、`no_speech_prob` | 每个温度是一次串行 CT2 调用；CT2 异常不会触发下一温度 fallback；返回对象只在本轮候选计算中持有 |
| `Whisper.generate`（批量） | 一次传入一个 Python batch 的多条 `StorageView`/prompt | `beam_size`、`patience`、`length_penalty`、`max_length`、抑制参数、`sampling_temperature=temperatures[0]`；不传 `num_hypotheses` | 逐结果读取 `sequences_ids[0]`、`scores[0]`、`no_speech_prob`，再按 chunk metadata 切段 | `batch_size` 只控制调用前后的 Python 切片；整批 CT2 异常使当前批次 generator 中断，已 yield 的前批次不会回滚 |
| `Whisper.align` | 一次对一组文本 token 与 encoder output 对齐 | `sot_sequence`、文本 token、`num_frames`、`median_filter_width=7` | `alignments`、token 概率经 Python DTW/词切分变成 `Word` | 对齐异常直接上抛；空文本在 Python 侧短路为空列表 |

`get_ctranslate2_storage()` 先执行 `np.ascontiguousarray`，再调用 `StorageView.from_array`（`transcribe.py:1873-1876`）；因此 CT2 边界前至少有一次连续内存保证，但源码没有声明 StorageView 的跨请求所有权或长期缓存契约。模型对象、encoder output、generate result、StorageView 都不能穿过平台公共契约。

单路的质量逻辑位于 Python，不是 CT2 的质量门禁：`generate_with_fallback()` 对每个温度重新调用 CT2，按压缩比、平均 log probability 和 no-speech 条件决定是否继续；全部候选都不合格时仍选择一个候选返回（`transcribe.py:1402-1530`）。因此“CT2 返回成功”与“业务质量通过”必须分开记录。

### 18.2 模型装载与文件来源：先构造 CT2，再补齐 tokenizer/特征配置

装载顺序是一个重要的失败边界：

```text
files/local directory/model alias
  → model_path（内存文件模式、本地目录，或 snapshot_download 返回目录）
  → ctranslate2.models.Whisper(...)
  → tokenizer.json：内存 bytes > 本地文件 > Tokenizer.from_pretrained fallback
  → preprocessor_config.json：内存 bytes > 本地 JSON > FeatureExtractor 默认值
  → FeatureExtractor 与 frame/token/time 常量
```

具体约束如下：

1. `files` 模式会原地 `pop("tokenizer.json")` 和 `pop("preprocessor_config.json")`，同一个 dict 的调用方会观察到这两个键被移除；剩余键继续传给 CT2（`transcribe.py:673-698`）。这不是只读输入契约。
2. 字符串别名/Hub repo 先经 `download_model()`；`utils.py:91-97` 的 `allow_patterns` 只请求 `config.json`、`preprocessor_config.json`、`model.bin`、`tokenizer.json`、`vocabulary.*`。下载由 `huggingface_hub.snapshot_download` 管理，当前库没有文件清单摘要、签名、下载事务回滚或半成品清理证明（`utils.py:49-115`）。
3. `local_files_only` 只传给 `snapshot_download`。如果本地模型目录没有 `tokenizer.json`，代码仍会调用 `tokenizers.Tokenizer.from_pretrained("openai/whisper-tiny[.en]")`（`transcribe.py:700-708`），没有在此调用点传 `local_files_only`；因此“本地模型模式”不等于所有 tokenizer 路径都离线。
4. CT2 模型构造发生在 tokenizer 和 preprocessor 读取之前。后续 tokenizer 文件损坏、fallback 失败或特征配置构造失败时，构造函数不会执行显式 rollback/close；未完成的 Python 对象只能依赖异常栈退出和 GC/进程回收。
5. `_get_feature_kwargs()` 只把合法的 `FeatureExtractor.__init__` 参数从 JSON 中筛出；JSON 解码错误仅记录 warning 并回到初始空配置（`transcribe.py:729-745`）。这不是 schema 校验，也没有对采样率、Mel 维度、模型文件版本做一致性证明。
6. `model_kwargs` 是无白名单的透传入口，未知参数/不兼容 CT2 版本由 CT2 构造阶段报错；`faster-whisper` 不翻译成稳定错误码。模型目录存在性、模型转换格式与 CT2 版本兼容也由 CT2/文件系统共同决定。

### 18.3 音频解码与特征内存：PyAV 负责媒体，Python 负责一次性物化

`decode_audio()` 的真实帧链为：

```text
av.open(input_file, metadata_errors="ignore")
  → container.decode(audio=0)（只取第一个音频流）
  → _ignore_invalid_frames（仅跳过 av.error.InvalidDataError）
  → _group_frames（AudioFifo 聚合至 500000 samples；清空 frame.pts）
  → AudioResampler(format="s16", layout=mono/stereo, rate=16000)
  → resampler.resample(...); 最后以 None flush
  → BytesIO 写入帧 ndarray
  → np.frombuffer → float32 / 32768.0
```

取证结论（`audio.py:37-109`）：

- PyAV 自带 FFmpeg，项目没有要求系统另装 ffmpeg；`metadata_errors="ignore"` 只影响元数据错误，不是媒体错误的全局容错。
- `frame.pts = None` 明确放弃帧时间戳检查，输入时间轴由解码后的连续采样数重建；损坏帧只在迭代到该帧时跳过，容器打开、流选择、重采样或其它解码异常仍会传播。
- 通过 `AudioFifo` 与 `500000` 样本分组降低逐帧处理开销，但最后一组可能不足该阈值；重采样器的 `None` flush 是必要的尾帧语义。
- 输出为 `s16` 后再转回 float32，至少产生 raw buffer、`frombuffer` 视图和最终 float32 数组几个阶段的内存占用；函数不提供流式 chunk 输出，转写前先完整物化输入 waveform。
- `split_stereo=True` 返回交错 stereo buffer 的偶数/奇数采样切片；`WhisperModel.transcribe` 只接受单个 ndarray，因此声道拆分必须由调用方分别提交。
- 传入 ndarray 时 `transcribe()` 完全绕过 PyAV，不检查 dtype、维度、采样率或数值范围；`FeatureExtractor.__call__` 会把非 float32 转成 float32，但采样率只能由调用方按模型的 `sampling_rate` 自行保证。
- `resampler` 的显式 `del` 和 `gc.collect()` 只在正常走完 `av.open` 块后执行（`audio.py:57-64`），不是 `finally` 清理；中途异常没有库级“解码已清空”证据。`av.open` 本身由 context manager 负责关闭 container。

特征侧 `FeatureExtractor.__call__` 会在传入 `chunk_length` 时原地改写实例的 `n_samples` 与 `nb_max_frames`（`feature_extractor.py:198-206`），再执行 padding、STFT、Mel 矩阵、log10、动态范围压缩（`feature_extractor.py:210-230`）。这是 model 级可变状态，不是纯函数；同一 `WhisperModel` 并发调用不同 `chunk_length` 时，必须由上层串行化或实例隔离。

### 18.4 beam、sampling、fallback 与 batch：参数同名不代表语义相同

| 维度 | `WhisperModel.transcribe` 单路 | `BatchedInferencePipeline.transcribe` 批量 | 收口判断 |
|---|---|---|---|
| `beam_size`/`patience` | 仅在温度 `0` 的 CT2 generate 使用 | 每批 generate 都传入 | 都是 CT2 解码参数，但批量没有单路的逐温度质量循环 |
| `best_of` | 非零温度时映射为 `num_hypotheses`，并把 beam 置 1 | 签名保留但 `generate_segment_batched()` 不传 `num_hypotheses` | 批量调用方不能把 `best_of` 当成生效保证 |
| `temperature` 列表 | 按顺序逐个 CT2 generate，阈值失败时 fallback | `temperature[:1]`，只保留首项，并传 `sampling_temperature` | batch 是单温度执行，不等价于单路质量策略 |
| `compression_ratio_threshold`、`log_prob_threshold`、`no_speech_threshold` | 参与候选质量/静音分支 | 在批量 docstring 中标为 unused；`no_speech_prob` 仍回传但不执行同等 fallback | 不能用相同字段名推断相同质量门禁 |
| `condition_on_previous_text` | 维护跨 30 秒窗口 prompt，可按温度阈值 reset | 固定 `False`；初始 prompt/hotwords 复制到每个 batch item | 批量窗口之间不复用单路历史 token |
| `max_initial_timestamp`、`hallucination_silence_threshold` | 按调用选项参与 | 固定为 `0.0`、`None` | batch 的异常/幻觉行为不可从单路推断 |
| `batch_size` | 无此概念；每窗口一次 batch=1 | 仅把已经完成的特征数组按 Python 切片分批；默认 8 | 是一次请求内的 CT2 输入批大小，不是任务队列或并发 worker 数 |

批量调用前，代码已经把所有 `audio_chunks` 转成特征并 `pad_or_trim` 后 `np.stack`（`transcribe.py:463-516`）；所以 `batch_size` 不能限制完整音频解码、VAD、特征列表的前置内存峰值，只限制 CT2 generate 的一次输入规模。批量 generator 按批次 yield，若在某批次中断，之前批次已经交付的 `Segment` 不会撤回。

### 18.5 CPU/GPU 与线程：配置映射是真实边界，调度器并不存在于本库

1. `device="auto"`、`"cpu"`、`"cuda"`、`device_index` 和 `compute_type` 原样进入 CT2 构造；本项目没有自己的 CUDA 探测、显存计费或量化校验。CUDA 可用性还受 CTranslate2 wheel、CUDA/cuBLAS/cuDNN 组合约束，README 的安装说明不是本机验证。
2. `cpu_threads` 被命名为 CT2 `intra_threads`；默认值 `0` 是传给 CT2 的“由 CT2 决定”语义，不能在 faster-whisper 层断言实际线程数。源码 docstring 说明非零值覆盖 `OMP_NUM_THREADS`，但仓库没有读回实际线程数的诊断接口。
3. `num_workers` 被映射为 CT2 `inter_threads`，不是 Python `ThreadPoolExecutor`，也不是平台任务 worker 数。源码 docstring 的并行承诺是：多个 Python 线程并发调用 `transcribe()` 时，CT2 的并发 generate 可真正并行，但代价是内存增加（`transcribe.py:647-657`）。
4. `device_index` 可以是整数或多 GPU 列表。`encode()` 在 `cuda` 且 GPU 数量大于 1 时把 encoder output `to_cpu=True`（`transcribe.py:1391-1400`），源码注释给出的原因是下一作业可能由不同 GPU 处理；这会增加 CPU 侧中转/驻留成本，不能把它解释为“始终在单卡显存中保持 encoder output”。
5. Silero VAD 完全是另一条 CPU 资源边界：`CPUExecutionProvider`、`inter_op_num_threads=1`、`intra_op_num_threads=1`、关闭 CPU memory arena（`vad.py:329-348`）。Whisper 主模型即使在 CUDA，VAD 仍不会自动迁移到 GPU。
6. VAD 推理内部以 512 samples 窗口、64 samples context，并按 `encoder_batch_size=10000` 分段调用 ONNX session（`vad.py:350-383`）；这不是 CT2 的 `batch_size`，也不受 `BatchedInferencePipeline.batch_size` 控制。

### 18.6 异常、生成器关闭和资源释放：正常路径有清理，失败路径没有统一 finally

| 位置/资源 | 正常路径 | 业务异常/主动关闭/超时 | 收口结论 |
|---|---|---|---|
| 单路 `generate_segments` 的 `tqdm` | 循环结束后 `pbar.close()`（`transcribe.py:1385-1389`） | CT2、tokenizer、align 或调用方 `generator.close()` 提前离开时没有包围整个循环的 `finally` | 进度条关闭不能作为推理完成证据；异常后的局部状态、已消费段和资源需由外层管理 |
| 批量 `_batched_segments_generator` | 正常遍历后 `pbar.close()`，并将 `last_speech_timestamp=0.0`（`transcribe.py:580-617`） | 批次异常或提前关闭可能不执行末尾 reset/close；同一 pipeline 再用可能残留时间状态 | pipeline 不是被源码证明为线程安全/可重入对象；并发请求应实例隔离 |
| 音频 container | `with av.open(...)` 退出时关闭 | 打开/解码/重采样异常仍依赖 context 异常退出；无超时中断接口 | 线程超时不能证明底层解码停止；大媒体应放在可杀的 worker 进程 |
| resampler、FIFO、raw buffer | 正常解码后显式删 resampler 并 GC，局部 buffer 随函数返回 | GC 不在 `finally`；异常时无“已释放”回读 | 不把 Python 引用消失等同于 C/FFmpeg 资源现场核验 |
| CT2 Whisper、tokenizer、FeatureExtractor | 随 model 实例持有；无 `close()`/`unload()` | 没有请求级 cancel、deadline、OOM 清理或模型重建 | 进程/worker 是可验证的资源边界；线程 Future.cancel 不能替代底层中断 |
| ONNX VAD session | `get_vad_model()` 成功结果单进程缓存 | 没有项目级关闭协议；异常创建不会形成成功缓存 | `get_vad_model.cache_clear()` 虽由 `functools.lru_cache` 暴露，但它只是函数包装器能力，不是文档化的 session 生命周期/并发清理协议；长驻进程仍需现场验证 |
| Segment/结果 | 每次 yield 后所有权转给调用方 | 部分 yield 后异常不回滚，未保存段丢失 | 完成必须晚于 generator 完整消费；上层应按 segment/offset 幂等保存并记录 partial |

特别要区分三类“取消”：(1) 不遍历返回的 generator，只是推理尚未开始或尚未继续；(2) Python `generator.close()`，最多停止后续 Python 迭代，源码没有把它传给 CT2 cancel；(3) worker 进程被 SIGTERM/kill，才是外层能验证的硬停止边界。当前项目只实现了第一、第二类的 Python 语义，没有第三类进程治理。

### 18.7 第二轮失败矩阵与接入验收补强

| 反向场景 | 当前源码可确认行为 | 不应宣称 | 外层验收动作 |
|---|---|---|---|
| `files` dict 复用 | 构造器会移除两个元数据键 | 输入 dict 是不可变/幂等的 | 调用前复制 dict；验证原 dict 与 provider 读取边界 |
| 本地目录缺 tokenizer | 可能走 `Tokenizer.from_pretrained` 外部 fallback | `local_files_only=True` 已彻底离线 | 离线 worker 预置 tokenizer，断网/无凭证时验证失败码与残留 |
| 多 GPU encoder | encoder output 可能转 CPU | 所有中间张量始终占用当前 GPU | 记录 CPU/GPU 内存峰值与设备分配，逐 GPU 并发实测 |
| batch 中一个 CT2 调用异常 | 当前 batch 中断，前批次结果可能已交付 | 整个 batch 原子成功或自动回滚 | item/segment 幂等键、attempt、部分失败状态与重放验证 |
| 非零 temperature 单路/批量 | 单路 `best_of` sampling+fallback；批量首温度一次 generate | 两入口质量策略等价 | 对同输入固定模型比较候选次数、最终温度和诊断 |
| `chunk_length` 并发变化 | FeatureExtractor 实例字段被改写 | 一个 model 可无锁并发任意 chunk 参数 | request-local 复制或实例隔离，跑并发交叉参数回归 |
| generator 中途抛错/close | `pbar`、批 pipeline 状态可能不走末尾清理 | 返回 tuple 或首个 segment 即代表完成 | 用异常注入验证状态、句柄、worker、临时目录和部分结果读回 |
| CUDA/CT2/ONNX OOM 或驱动异常 | 异常向上抛，没有自动降 batch/换设备/重建 | “重试”已由库提供 | 独立进程组、kill/reap、租约释放、重建上限和错误分类由运行核心负责 |

第二轮结论：CTranslate2 是单一数值推理边界，但模型下载、音频解码、特征构造、VAD、tokenizer、结果切段都发生在同一 Python 进程；该库没有把其中任一环节变成可取消、可回滚、可恢复的任务。生产接入的最小硬边界仍是“模型/解码/CT2/VAD 放 provider worker，任务状态/超时/取消/进程回收/逐段幂等落盘放外层唯一 owner”。

### 18.8 本轮验证等级与边界

| 检查 | 本轮真实动作 | 结果/等级 |
|---|---|---|
| CTranslate2、装载、解码、特征、VAD、测试源码取证 | 读取 `transcribe.py`、`audio.py`、`feature_extractor.py`、`vad.py`、`utils.py`、`requirements.txt`、`tests/test_transcribe.py` 的相关实现 | L1 静态实现证据；关键调用、参数映射、异常分支和资源路径均有源码路径 |
| 历史细探对照 | 读取 `细探-faster-whisper.md`，保留旧文件并将第二轮有效事实补入本文件 | L0/L1；旧细探仍是历史线索，不是并行事实源 |
| 文档结构与目标范围 | 仅写目标根 `ARCHITECTURE.md`；目标根 `git status --short` 仍只显示既有未跟踪的两份文档；`git diff --check -- ARCHITECTURE.md` 返回 0 | 文档写入成功；未改源码、依赖、配置、测试或 Git；由于架构文档本身未跟踪，Git diff 不作为内容差异证据 |
| 真实模型/CT2/PyAV/ONNX/GPU/线程/崩溃测试 | 未安装依赖、未下载模型、未启动推理或故障 worker | L3/L4 未验证；不能宣称模型可运行、GPU 可用、线程数达到预期或异常释放已现场通过 |

## 19. 第三轮更新后的剩余风险

1. 专属 MCP `project_context` 首次绑定错误项目，`codegraph_explore` 指定 faster-whisper 时确认目标无 `.codegraph/`；本轮没有把错误项目代码图当作目标证据，也没有重复请求不可用代码图。
2. 当前源码没有任务状态、取消、超时、OOM、崩溃回收或持久化结果；第 16.4—16.8 节是平台接入契约和验收要求，不是源码已具备能力。
3. `download_model` 的 Hub cache、tokenizer fallback 和外部模型完整性未在本轮实测；不得把下载成功测试源码当作当前网络/凭证/模型 revision 证据。
4. 单路/批量默认值、quality fallback、VAD 参数原地修改和 `last_speech_timestamp` 差异可能造成结果漂移；统一模块契约必须显式固定而不能只做 drop-in 声明。
5. 本任务严格只修改本文件；没有创建支持库、媒体模块、provider、运行核心、测试、配置或模型制品，也没有删除 `细探-faster-whisper.md`。
