# WhisperX 架构事实与深度取证

> 本文是仓库根唯一的长期架构事实源。说明、结论、风险和表格解释使用中文；源码路径、类名、函数名、字段名、命令、协议和第三方名称保留原文。
>
> 研究范围：只读检查当前源码、README、依赖、测试、CI 与 Git 元数据；当前核对只允许修改本文，未删除 `细探-whisperX.md`，未修改源码、测试、配置、依赖或 Git，也未安装依赖、启动服务、下载模型或生成构建物。
>
> **旧细探收口声明：** `细探-whisperX.md` 的四能力定位、VAD→ASR→forced alignment→diarization 管线、单词级时间戳、说话人分轨、PyTorch/多模型权重边界和可复用方向已逐条核对并吸收至本文；旧文件按要求保留作历史线索，不再与本文并行维护事实。后续只维护本文。

## 1. 项目身份、版本与证据边界

| 项 | 当前事实 |
|---|---|
| 项目 | WhisperX |
| 本地根目录 | `/Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/30_audio_asr/whisperX` |
| Python 包 | `whisperx` |
| 上游 | `https://github.com/m-bain/whisperX` |
| 许可证 | BSD 2-Clause；证据：`LICENSE:1-24`、`pyproject.toml:9`。旧细探中的“BSD-3/MIT”已裁决为过时/不吸收 |
| 包版本 | `3.8.7rc1`；证据：`pyproject.toml:4-5` |
| Python 约束 | `>=3.10, <3.14`；证据：`pyproject.toml:8` |
| 当前分支 | `main` |
| 当前提交 | `2cfd7b7c5c7bba144954364db747319b50e8232b` |
| 当前提交摘要 | `fix: raise actionable error when punkt_tab download fails` |
| 当前提交时间 | `2026-07-13T02:30:07-06:00` |
| `origin/main` | 与当前 `HEAD` 同为 `2cfd7b7c5c7bba144954364db747319b50e8232b` |
| 本地标签 | `3.8.7rc1` 指向 `8dcdec18039f6f6b10b967c45273f54dd2a1f699` |
| 工作树 | Git 跟踪源码未改；本地有未跟踪 `ARCHITECTURE.md` 与 `细探-whisperX.md` |
| 服务边界 | 仓库没有 HTTP/RPC 服务、数据库、任务队列、鉴权、持久任务状态或部署编排 |
| 证据强度 | 本文实现结论以当前源码为主；README/论文/旧细探只作线索；模型下载、GPU 推理、ffmpeg 与 gated Hugging Face 模型当前核对未实测 |

**版本裁决：** 本地 `main` 与 `origin/main` 一致，没有执行 fetch/pull。当前文档以 `2cfd7b7c5c7bba144954364db747319b50e8232b` 源码为准，不能把历史标签等同于当前主分支。

## 2. 项目定位与总体流程

WhisperX 是一个 Python 包、CLI 和 Python 函数 API 的组合，用 `faster-whisper`/CTranslate2 做批量 ASR，用 VAD 控制语音片段，用语言特定的 CTC forced alignment 产生词/字符时间，用 `pyannote` 做说话人分离与标签归属，最后输出文本、字幕或 JSON。它不是现成的在线转写服务。

旧细探提炼的“四能力组合”准确，但源码显示它不是四个完全独立的远程服务，而是同一进程中由 `transcribe_task` 分阶段装载的本地模型管线：

```text
CLI: whisperx/__main__.py:cli
  └─ transcribe.py:transcribe_task(args, parser)
       ├─ 解析/归一化参数、建立 output_dir、选择 writer
       ├─ Part 1：load_model
       │    ├─ faster_whisper.WhisperModel / CTranslate2
       │    └─ VAD：Pyannote 或 Silero
       │         └─ load_audio -> VAD -> merge_chunks -> Mel -> batched generation
       ├─ 删除 ASR/VAD 模型、gc.collect、torch.cuda.empty_cache
       ├─ Part 2：load_align_model -> align
       │    └─ torchaudio bundle 或 Hugging Face Wav2Vec2
       │         -> CTC emission -> trellis/backtrack -> words/chars/sentences
       ├─ 删除 alignment model、gc.collect、torch.cuda.empty_cache
       ├─ 可选：DiarizationPipeline -> pyannote -> IntervalTree
       │    └─ assign_word_speakers：按交集时长写入 segment/word speaker
       └─ writer(result, audio_path, writer_args)
            └─ .txt/.vtt/.srt/.tsv/.json/.aud
```

Python API 的最小真实链是：

```text
whisperx.load_model
  -> FasterWhisperPipeline.transcribe
whisperx.load_align_model
  -> whisperx.align
DiarizationPipeline
  -> whisperx.assign_word_speakers
```

顶层 API 由 `whisperx/__init__.py` 的 `_lazy_import` 延迟加载重依赖；调用者负责模型对象、设备、缓存、token、释放和异常处理。

## 3. 真实目录与分层

```text
whisperX/
├── .github/workflows/
│   ├── tests.yml                 # uv sync + pytest
│   ├── python-compatibility.yml  # lock 检查 + import
│   ├── build-and-release.yml     # uv build + GitHub/PyPI 发布
│   └── zizmor.yml                # Actions 安全分析
├── figures/pipeline.png
├── tests/test_word_timestamp_interpolation.py
├── whisperx/
│   ├── __init__.py               # 延迟 Python API 门面
│   ├── __main__.py               # argparse CLI
│   ├── transcribe.py             # CLI 阶段编排
│   ├── asr.py                    # FasterWhisperPipeline、批量生成、load_model
│   ├── audio.py                  # ffmpeg、waveform、Mel 特征
│   ├── alignment.py              # CTC forced alignment
│   ├── diarize.py                # diarization、IntervalTree、speaker 回填
│   ├── schema.py                 # TypedDict 和 ProgressCallback
│   ├── utils.py                  # 语言、时间、writer、插值
│   ├── log_utils.py              # logging
│   ├── conjunctions.py            # 字幕切分词表
│   ├── SubtitlesProcessor.py     # 独立字幕后处理器
│   ├── assets/
│   │   ├── mel_filters.npz
│   │   └── pytorch_model.bin
│   └── vads/
│       ├── vad.py                # Vad 抽象、merge_chunks
│       ├── pyannote.py           # 内置 Pyannote VAD 和 Binarize
│       └── silero.py             # Silero VAD
├── CUDNN_TROUBLESHOOTING.md
├── EXAMPLES.md
├── LICENSE
├── MANIFEST.in
├── README.md
├── pyproject.toml
└── uv.lock
```

### 分层职责

| 层 | 真实 owner | 输入/输出 | 不负责什么 |
|---|---|---|---|
| CLI/编排 | `__main__.py:cli`、`transcribe.py:transcribe_task` | argv → 阶段结果和文件 | 不保存任务状态，不提供服务接口 |
| Python 门面 | `__init__.py` | 延迟导入并转发函数 | 不管理模型生命周期 |
| 音频 | `audio.py` | 路径/数组 → 16 kHz `float32` | 不做音频持久化、重试或超时 |
| VAD | `vads/vad.py`、`pyannote.py`、`silero.py` | waveform → speech intervals/chunks | 不产生文本 |
| ASR | `asr.py` | chunks → segment transcript | 不提供最终词级时间戳 |
| 对齐 | `alignment.py` | transcript + waveform → words/chars | 不验证跨进程 schema |
| diarization | `diarize.py` | waveform → speaker intervals，再回填结果 | 不修正文本 |
| 输出 | `utils.py`、`SubtitlesProcessor.py` | dict → 文件 | 不原子提交、不登记制品 |

## 4. 契约表

下表把公开入口、参数所有权、错误、重试、超时/取消和资源责任分开记录。源码没有统一契约版本、错误码或取消 token；“无”是实现事实，不是建议。

| 入口/能力 | 输入与所有权 | 输出契约 | 失败/重试 | 超时/取消/幂等 | 资源责任与证据 |
|---|---|---|---|---|---|
| `whisperx.__main__:cli` | argv；`argparse` 拥有解析结果 | 无返回，副作用为日志/输出文件 | argparse 参数错误退出；下游异常向上冒泡；无统一重试 | 无超时参数、取消 token、信号处理或幂等键；证据：`__main__.py:12-102` | 编排层触发模型和写文件，清理不在 `finally`；`transcribe.py:124-238` |
| `transcribe_task` | `args` dict 会被大量 `pop`，调用方不得复用；`parser` 用于错误 | 无显式返回；写 `output_dir` | 非法 language、参数联动和模型异常直接失败；已有结果不持久化 | 多输入按阶段聚合；没有 per-file timeout、resume、cancel；输出 basename 冲突会覆盖 | `os.makedirs(..., exist_ok=True)`；ASR/align 正常阶段边界才释放；`transcribe.py:20-238` |
| `audio.load_audio` | 文件路径由函数读取；外部 `ffmpeg` 借用输入路径 | 一维 `np.float32`、mono、目标采样率默认 16 kHz | `CalledProcessError` 转 `RuntimeError`；无重试和 stderr 结构化码 | `subprocess.run` 未传 `timeout`；无取消/进程组回收；`audio.py:25-65` | ffmpeg 子进程及其 stdout 由 `subprocess.run` 管理；异常只转换，不保留独立诊断对象 |
| `asr.load_model` | `whisper_arch`、设备、缓存、token、VAD 选项；返回对象由调用方持有 | `FasterWhisperPipeline` | 非法 `vad_method` 为 `ValueError`；模型/下载/ABI 异常下游抛出；无重试策略 | 无超时/取消；下载和初始化幂等性依赖第三方缓存；`asr.py:315-442` | 创建 CTranslate2/Whisper 与 VAD 模型；调用方负责 `del`/GC；CLI 只在成功阶段执行释放 |
| `FasterWhisperPipeline.transcribe` | 路径或 16 kHz `np.ndarray`；输入数组由调用方保留，内部创建 tokenizer/批次 | `{"segments": [{start,end,text,avg_logprob?}], "language": str}` | 空 speech 时 Silero 返回空列表；模型/语言检测错误冒泡；无 per-chunk retry | 只有进度 callback，没有 timeout/cancel；`DataLoader` 随调用创建；`asr.py:197-298` | VAD chunks、Mel tensor、批量 iterator 生命周期随调用；tokenizer 在未预设语言时调用结束重置 |
| `Vad.merge_chunks` | `SegmentX` 列表由实现提供；不复制输入对象 | `{start,end,segments}` 列表；可能为空 | 基类直接访问 `segments[0]`，空列表由具体实现防护；断言 `chunk_size>0` | 无超时/取消/幂等；纯内存函数 | 不持有模型；`vads/vad.py:20-53`，Silero/Pyannote 各自适配 |
| `load_align_model` | 语言、设备、模型名/缓存；返回模型和 metadata 所有权转调用方 | `(model, {language,dictionary,type})` | 无默认语言模型为 `ValueError`；HF/torchaudio 装载失败统一为 `ValueError`（原异常打印）；可触发网络 | 无超时/取消；本地缓存可由 `model_cache_only` 限制 HF 读取 | 模型移入 device；CLI 在 alignment 阶段成功后删除；`alignment.py:80-114` |
| `alignment.align` | transcript 可迭代对象、模型、metadata、路径/NumPy/Torch 音频；不声明是否复制 | `{"segments": [...], "word_segments": [...]}`；可含 `chars` | 无可对齐字符、越过音频时长、backtrack 失败时保留原 segment；punkt 下载失败为 `RuntimeError`；无重试 | callback 仅报百分比；无 timeout/cancel；CTC trellis 会按帧×token 分配内存；`alignment.py:117-424` | 音频转 Torch，emission/trellis/DataFrame 为临时对象；模型/显存由调用方释放 |
| `DiarizationPipeline.__call__` | 路径或数组；构造 `{'waveform','sample_rate'}` | `DataFrame(segment,label,speaker,start,end)`，可选 `(df, embeddings)` | gated 模型/token/第三方异常冒泡；无重试/错误码 | callback 通过 pyannote hook 报进度；无 timeout/cancel；`diarize.py:105-182` | pyannote 模型和 GPU 设备由实例持有；音频 Tensor/embedding 随调用产生；无显式 close |
| `assign_word_speakers` | `diarize_df` 与 transcript 原地可变对象；会直接写 speaker | 原 transcript 对象本身（就地增强），可加 `speaker_embeddings` | 空 transcript/空 diarization 直接原样返回；无 overlap 且 `fill_nearest=False` 不写标签 | 纯内存，无 timeout/cancel/idempotency；重复调用可能覆盖同字段 | `IntervalTree` 临时构造，结果所有权仍归调用方；`diarize.py:185-263` |
| `utils.get_writer`/writer | `result`、音频路径、options；writer 读取并写文件 | 无返回；文本/字幕文件 | 不支持格式会 `KeyError`；文件 I/O 异常冒泡；无原子替换、重试、回滚 | 无超时/取消；同 basename 可覆盖；`utils.py:215-468` | `with open` 负责单文件句柄关闭；`all` 逐个写，可能部分成功 |
| `SubtitlesProcessor.save` | segments 由调用方提供；会补估计时间到 word dict | 返回字幕条数并写单个文件 | 时间缺失用启发式估算；空/异常结构可能 `KeyError`；无原子写 | 无 timeout/cancel/idempotency；`with open` 关闭文件；`SubtitlesProcessor.py:205-226` |

### 4.1 结果数据契约

```text
音频文件 / 16 kHz waveform
  -> VAD SegmentX(start, end, speaker?)
  -> merged chunk {start, end, segments:[(start,end)]}
  -> TranscriptionResult
       {segments:[{start,end,text,avg_logprob?}], language}
  -> AlignedTranscriptionResult
       {segments:[{start,end,text,avg_logprob?,words,chars?}],
        word_segments:[{word,start?,end?,score?}]}
  -> diarization augmentation
       segment.speaker, word.speaker, optional speaker_embeddings
  -> writer-specific file
```

`schema.py` 的 `TypedDict` 只提供静态提示，不做运行时校验；`SingleWordSegment` 的 `start/end/score` 在声明中必有，但真实 alignment 对无法对齐词可以不写这些键。`interpolate_method="nearest"` 会估算缺失时间，`"ignore"` 保留缺失；文档消费者必须区分模型对齐和插值结果。当前结果没有 `schema_version`、model provenance、alignment provenance、任务 ID 或错误字段。

## 5. 真实对接链与关键节点

### 5.1 CLI 参数到输出文件

| 顺序 | 调用方 → 被调方 | 实际输入/状态 | 实际输出/异常 |
|---|---|---|---|
| 1 | `cli` → `argparse.parse_args` | audio、model、设备、VAD、alignment、diarize、writer 参数 | `args` dict；类型/choices 错误由 argparse 结束 |
| 2 | `cli` → `setup_logging` | `--log-level` 或 `--verbose` | 配置 `whisperx` logger；导入 `transcribe_task` |
| 3 | `transcribe_task` → `get_writer` | `output_format`, `output_dir` | writer 闭包/实例；创建目录在此前完成 |
| 4 | `transcribe_task` → `load_model` | model/device/cache/token/VAD/asr options | `FasterWhisperPipeline`，可能下载模型 |
| 5 | `transcribe_task` → `load_audio` → `model.transcribe` | 每个 audio path → waveform | VAD chunks、batched ASR segments；结果暂存内存 `results` |
| 6 | 编排 → `del model; gc.collect; torch.cuda.empty_cache` | Part 1 全部输入完成 | 仅正常路径释放 ASR/VAD |
| 7 | 编排 → `load_align_model` → `align` | 初始语言、每条 transcript、原音频 | CTC 对齐结果；语言改变时重复装载模型 |
| 8 | 编排 → 删除 alignment model | Part 2 成功 | 仅正常路径释放 alignment |
| 9 | 编排 → `DiarizationPipeline` → `assign_word_speakers` | path、speaker 限制、token、结果 | speaker interval、就地写回 speaker |
| 10 | 编排 → writer | result、原始 audio path、writer args | 以音频 basename 写出文件；可能覆盖或部分生成 |

### 5.2 ASR 关键小节点

1. `load_model` 先将 `compute_type="default"` 解析为 GPU `float16` 或 CPU `float32`，`.en` 架构强制语言 `en`，构造 `TranscriptionOptions`，再创建 VAD。手工传入 `vad_model` 优先于 `vad_method`；非法 method 才在此处明确报错。
2. `FasterWhisperPipeline.transcribe` 将路径转为 `load_audio` 的 16 kHz 数组；Pyannote 使用 `preprocess_audio` 形成 `[1, samples]` Tensor，Silero 直接使用 waveform dict。
3. VAD 输出按 `chunk_size` 合并；没有活动语音时 Silero/Pyannote 返回空列表，随后 `segments` 为空，不会自动补一条“静音”结果。
4. 无 tokenizer 时仅用首 30 秒 `detect_language`；短于 30 秒只 warning，仍返回检测结果。批量输入共享一个模型但每次调用可能重新构造 tokenizer。
5. `generate_segment_batched` 统一 prompt 给 batch，encoder 一次处理 batch，固定 `without_timestamps=True`，将文本和平均 log probability 返回；这解释了“ASR segment 时间不是最终词时间”。
6. `batch_size` 为 0/1/None 时从 batch 输出取第一个元素；其他值保留批量返回对象。进度 callback 以 VAD segment 数计算百分比。

### 5.3 Alignment 关键小节点

1. `load_align_model` 用 `DEFAULT_ALIGN_MODELS_TORCH` 选择 torchaudio bundle，否则按 `DEFAULT_ALIGN_MODELS_HF` 或显式模型走 Hugging Face；metadata 的 `type` 决定推理分支。
2. `align` 首先把路径/数组规整为二维 Torch waveform，取音频总时长，按语言选择 Punkt tokenizer；缺失 `punkt_tab` 会尝试 `nltk.download`，下载失败抛出可操作 `RuntimeError`。
3. 文本按空格切词，`ja`/`zh` 按字符处理；字典外字符被映射到 emission 的 wildcard 列，故数字/标点也可能获得“估计可用”的时间，但这不是字典字符的原始 CTC 证据。
4. 每个 segment 取 `f1/f2` 音频切片，短于 400 samples 时补齐；模型 emission 经 `log_softmax` 后由 `get_trellis`、`backtrack`、`merge_repeats` 变为字符区间，再聚合 sentence/word。
5. 句子/词时间出现 NaN 时按 `nearest`/`linear`/`ignore` 处理；最后返回 segment 列表和扁平 `word_segments`。

### 5.4 Diarization 与 speaker 回填

1. `DiarizationPipeline` 默认装载 `pyannote/speaker-diarization-community-1`，将模型移动到 device；token 由调用者提供。
2. 调用时路径会再次 `load_audio`，数组包装为 `[1, samples]` Tensor 与 `SAMPLE_RATE`。pyannote hook 把 segmentation/embeddings 两步映射为单调进度。
3. `itertracks(yield_label=True)` 变成 pandas DataFrame，包含原始 `segment`、`label`、`speaker` 和派生 `start/end`。
4. `assign_word_speakers` 为 diarization 区间建排序数组+二分候选的 `IntervalTree`，按实际交集时长聚合并选择单一 dominant speaker；词没有 start 时跳过，`fill_nearest=True` 才用最近区间。
5. `speaker_embeddings` 不是默认结果；CLI 只有同时 `--diarize --speaker_embeddings` 才把 embedding 字典放入结果。

## 6. 资源生命周期与终态

| 资源 | 创建/持有 | 正常释放 | 业务失败、超时/取消、崩溃路径 | 残留与验证 |
|---|---|---|---|---|
| ffmpeg 子进程 | `audio.load_audio` 的 `subprocess.run` | `run` 返回后回收，stdout 变 NumPy | 无 Python timeout、信号处理或独立进程组；宿主被杀时只能依赖 OS | 未有仓库级子进程残留检查；应外部检查进程表 |
| 输入音频/NumPy | `load_audio` 返回，编排暂存 `audio`/`results` | 函数引用离开后由 GC | 异常时局部引用释放依赖栈展开；多文件结果全阶段聚合造成峰值 | 无显式内存预算或大文件流式策略 |
| ASR/VAD 模型与 GPU | `load_model` 创建并 Pipeline 持有 | CLI Part 1 成功后 `del model` + `gc.collect` + CUDA cache flush | Part 1/后续阶段异常没有 `finally` flush；CLI 进程退出通常由 OS 回收，嵌入式调用者可能继续持有 | 只有日志/用户检查显存；无代码级 leak sentinel |
| tokenizer/批量 iterator | `transcribe` 内部创建 tokenizer、DataLoader、PipelineIterator | 调用返回；预设语言为空时 tokenizer 置 None | exception/取消不保证 tokenizer 重置或 iterator 及时销毁 | 无任务级句柄、队列深度或取消观测 |
| alignment model、emission、trellis | `load_align_model` 和每段 `align` 创建 | CLI Part 2 成功后删除 model，临时 Tensor/DataFrame 由引用计数/GC | `align` 失败或中断不保证 GPU flush；trellis 按输入规模增长，可能 OOM | 无输入长度上限、显存预算或 OOM 恢复 |
| pyannote diarization model | `DiarizationPipeline.__init__` 持有 | 无 `close`；进程退出或对象被 GC | 模型异常/取消无显式 release；嵌入式多任务调用者需自行销毁实例 | 无模型句柄/显存读回 |
| DataFrame/IntervalTree/embedding | `DiarizationPipeline.__call__`/回填临时或写入结果 | 函数结束后无引用即回收；embedding 可永久留在结果 | 中断时结果可能是部分原地修改；重复调用会覆盖 speaker | 无事务/快照/回滚 |
| 输出文件 | writer `with open(output_path,"w")` | context manager 关闭句柄 | 进程在写入中崩溃可留下截断文件；`all` 格式可只写出前几种；同 basename 覆盖 | 无临时文件、fsync、原子 rename、manifest 或完整性标记 |
| NLTK/模型缓存 | `nltk.download`、HF/torch/torchaudio/faster-whisper cache | 由第三方缓存策略管理 | 下载中断可能留下缓存临时状态；没有仓库清理器 | 需外部检查缓存目录、磁盘和离线可用性 |

### 6.1 四种终态结论

- **正常完成：** CLI 有阶段级模型释放，单文件 writer 有句柄关闭；这是已实现的最佳路径。
- **业务失败：** 异常通常向上冒泡；没有统一错误码、部分结果清单或回滚。前面阶段的内存/模型释放依赖是否走到显式释放点。
- **主动取消/超时：** 源码没有取消 token、timeout 参数、signal handler 或 `finally` 清理契约；只能由宿主终止整个进程并自行清理。
- **宿主/子进程崩溃：** OS 可回收进程资源，但已写文件、缓存临时物和外部显存状态没有应用级恢复/校验；不能声称可恢复任务。

## 7. 失败、边界、并发与质量风险

### 7.1 已有失败分支

| 场景 | 源码行为 | 结论 |
|---|---|---|
| ffmpeg 不存在/解码失败 | `FileNotFoundError` 未转换；`CalledProcessError` 转 `RuntimeError` | 有异常，但无可重试分类和 timeout |
| 非法 VAD method/onset/chunk | `ValueError` 或 `assert` | 参数边界部分明确，assert 不宜作为稳定外部契约 |
| 无语音 | 具体 VAD warning 并返回空；ASR 结果可为空 | 不生成显式空结果状态 |
| 缺 alignment model | `ValueError` | 语言/模型需调用者预检 |
| 缺 `punkt_tab` | 尝试下载；失败抛 `RuntimeError` 并给安装命令 | 网络副作用发生在推理阶段 |
| 字典无字符/segment 超时长/backtrack 失败 | 保留原 segment，缺少词时间 | 应向消费者暴露对齐状态，但当前没有字段 |
| translate | `transcribe_task` 强制 `no_align=True` | 翻译结果不会进入 alignment |
| no_align + word 选项 | `parser.error` | 有互斥校验 |
| 无 HF token 的 diarization | warning，第三方可能随后失败 | warning 不是成功证据 |
| 空 diarization/无 transcript | `assign_word_speakers` 原样返回 | 不代表 speaker 已完成 |
| 词无 start | 词级 speaker assignment 跳过 | 结果允许缺字段 |
| 跨 speaker overlap | 选择交集时长最大单一 speaker | 不表达多人重叠 |
| 输出格式/文件错误 | `KeyError`/OSError 冒泡；`all` 可能部分写入 | 无事务性 |

### 7.2 超时、取消、并发与幂等

- CLI 支持多个音频参数，但 `transcribe_task` 先完成所有文件的 VAD+ASR，再统一 alignment，再统一 diarization，`results` 和路径在阶段间保留；原始 waveform 不会全部留在 `results` 中，只有单文件分支继续借用 Part 1 循环结束时的局部 `audio`，多文件 alignment 会按路径再次解码；整体仍不是按文件流式提交。
- `num_workers` 传给 `DataLoader`，默认 `transcribe` 为 0，Pipeline 内部 `_num_workers=1`；没有任务级并发控制、队列、限流或进程池协议。
- `torch.set_num_threads` 是全局进程设置；`threads` 会影响后续 CPU 推理，不是每个任务隔离的资源租约。
- 没有超时、取消、暂停、断点续跑、重试、幂等键或输出 manifest；同名输入 basename 在同一 output_dir 可能互相覆盖。
- progress callback 只是回调，不具有取消语义；callback 抛错也没有专门转换。

### 7.3 质量边界

- ASR 关闭原生 timestamps，词级时间依赖 alignment 模型和语言匹配。
- wildcard、`nearest`/`linear` interpolation 是回退/估算，不等于模型直接对齐证据。
- `ja`/`zh` 不按空格切词，其他语言的空格和标点策略可能造成词边界偏差。
- overlap speech、diarization 误分和语言专用 wav2vec2 缺失是 README 明示限制。
- `TypedDict` 不运行时校验，真实结果可缺少 word 的 `start/end/score`；消费者不能只按类型提示读取。
- `SubtitlesProcessor` 是独立字幕后处理路径，使用启发式词时长（`k=0.25`）补时间，不属于 `transcribe_task` 默认 writer 链；不能把两套字幕规则混为同一契约。

## 8. 模型、网络、缓存、打包与发布

### 8.1 依赖边界

`pyproject.toml:11-25` 的直接依赖包括 `ctranslate2`、`faster-whisper`、`nltk`、`numpy`、`omegaconf`、`pandas`、`pyannote-audio`、`huggingface-hub`、`torch`、`torchaudio`、`torchvision`、条件依赖 `torchcodec`、`transformers` 和 Linux x86_64 的 `triton`。macOS 使用 `pytorch-cpu` index，非 macOS x86_64 使用 CUDA 12.8 index；实际 wheel/ABI 可用性不由本文推断。

### 8.2 外部边界

| 边界 | 触发点 | 离线/认证事实 |
|---|---|---|
| `ffmpeg` | `audio.load_audio` | 系统命令硬依赖；无本地 Python 解码 fallback |
| faster-whisper/CTranslate2 模型 | `asr.load_model` | 可通过 `download_root`/`local_files_only` 控制缓存读取，但模型本体外部管理 |
| Silero | `torch.hub.load('snakers4/silero-vad',...)` | 首次可能访问网络；`trust_repo=True` |
| Pyannote VAD | 包内 `assets/pytorch_model.bin` + `Model.from_pretrained` | 本地资源存在性检查；Torch cache 目录会创建 |
| Alignment | torchaudio bundle 或 Hugging Face `from_pretrained` | `model_cache_only` 只传给 HF 分支；缺语言需显式模型 |
| Punkt | `nltk_load`，缺失时 `nltk.download` | 网络下载发生在运行时，失败给出命令提示 |
| Diarization | `pyannote/speaker-diarization-community-1` | gated 模型需 HF token 和协议确认 |

`MANIFEST.in` 纳入 `whisperx/assets/*` 和 `LICENSE`，`pyproject.toml` 使用 setuptools `find` 包含 `whisperx*`。当前 CI 使用 `uv`，Python 3.10/3.11/3.12/3.13；发布 workflow 执行 `uv lock --check`、`uv build`、GitHub release upload 与 `uv publish`。

## 9. 测试与防假绿 L0-L4

### 9.1 仓库测试事实

当前仓库只有 `tests/test_word_timestamp_interpolation.py`，共 12 个 `test_` 方法，集中覆盖 alignment wildcard、数字/符号词、相邻词不污染、时间单调性和 `interpolate_nans`。

已存在的测试源码证据：

- known/mixed/all-unknown 字符可产生词级时间；
- `4,9` 回归场景有时间；
- unknown word 不破坏相邻 known word；
- `ignore` 保留缺失词时间，segment 的 start/end 仍为非 NaN float；
- `nearest` 能补齐缺失词时间。

未被仓库测试直接覆盖：

- ffmpeg、音频格式、重采样和音频超时；
- Silero/Pyannote 模型下载、VAD 边界、空语音和 `merge_chunks`；
- FasterWhisper batched generation、语言检测、batch size、模型释放；
- torchaudio/HF 两种 alignment 装载和 punkt 下载；
- `DiarizationPipeline`、hook、IntervalTree、speaker assignment、embeddings；
- CLI 全参数联动、所有 writer 的实际内容、Unicode、重复 basename；
- 多文件阶段聚合、缓存只读、OOM、异常清理、取消/崩溃恢复。

### 9.2 L0-L4 证据等级（防止把声明当通过）

| 等级 | 允许的表述 | 本仓库当前证据 |
|---|---|---|
| L0 源码/声明 | “源码存在/README 声明能力” | 四能力、入口、分层和失败分支已由源码核对；不能叫运行通过 |
| L1 测试存在 | “有测试源码覆盖某分支” | `test_word_timestamp_interpolation.py` 的 12 个测试方法；不能推导端到端可用 |
| L2 本地真实执行 | “在当前环境命令退出 0，测试数/跳过数可读回” | 需以当前核对实际命令结果为准；未执行部分不能写通过 |
| L3 外部边界实测 | “ffmpeg/缓存/模型/token/设备等真实对接通过” | 当前核对未下载模型、未启动 GPU/外部服务；全部未验证 |
| L4 端到端与终态 | “真实音频完成 VAD→ASR→align→diarize→writer，且失败/取消/崩溃清理已验收” | 仓库没有端到端夹具、取消协议或资源验收；未达成 |

**防假绿规则：** CI 配置、历史提交、打印日志、测试文件存在、子代理回报和“模型能加载”的声明均不能替代对应等级的真实命令、退出码、测试数、外部依赖和资源读回。当前最多可把窄 alignment 单测记为 L2（前提是当前核对命令实际退出 0），完整产品链必须标为 L0/L1 或未验证。

### 9.3 CI 事实

```text
push/PR main
  -> .github/workflows/tests.yml
  -> uv sync --all-extras
  -> uv run pytest tests/ -v

push/PR main
  -> .github/workflows/python-compatibility.yml
  -> uv lock --check
  -> uv sync --all-extras
  -> uv run python -c "import whisperx..."

published release
  -> .github/workflows/build-and-release.yml
  -> uv lock --check -> uv build -> gh release upload -> uv publish
```

CI 覆盖的是安装、窄测试、import、锁文件和构建发布，不等于 GPU、模型、音频、diarization 或故障恢复验收。

## 10. 未验证项与剩余风险

1. 未在当前核对实测 `ffmpeg` 路径、坏文件、超长文件、采样率和子进程超时行为。
2. 未下载或运行 `faster-whisper`、Silero、Pyannote、alignment、diarization 权重；没有 L3/L4 结果。
3. 未验证 macOS CPU wheel 与 Linux CUDA 12.8 wheel 的实际安装兼容性。
4. 未验证 Hugging Face gated token/协议、`local_files_only` 全链路和缓存中断恢复。
5. 未验证 `nltk punkt_tab` 缺失、下载失败和离线预置场景。
6. 未验证 OOM、网络断线、第三方异常、callback 异常、主动取消、SIGTERM/SIGKILL、模型二次释放和输出部分写入。
7. 当前 `transcribe_task` 的显式清理没有 `try/finally`；异常可能使嵌入式调用者保留 GPU 模型。
8. `FasterWhisperPipeline._sanitize_parameters` 只处理窄 tokenizer 分支，却读取 `kwargs["maybe_arg"]`；扩展 Hugging Face Pipeline 参数前必须补契约测试。
9. `Vad.preprocess_audio` 基类为 `pass`；只能依赖具体 VAD，不应直接实例化基类。
10. `MANIFEST.in` 仍引用仓库中未见的 `requirements.txt`；依赖权威来源应以 `pyproject.toml`/`uv.lock` 为准。
11. `SubtitlesProcessor` 与 `utils` 有两套字幕时间/切分规则；没有统一 writer owner。
12. 输出文件按 basename 写入且无原子替换/manifest；多文件同名、崩溃或 `all` 中途失败可能留下不可判定制品。
13. `assign_word_speakers` 选择单一 dominant speaker，不能表示 overlap speech；embedding 直接放入结果会显著增大内存/JSON。
14. `schema.py` 没有运行时验证和 provenance；外部系统若直接消费，可能把缺时间或插值时间误认成模型证据。

## 11. 旧细探逐条吸收与不吸收裁决

| 旧细探内容 | 裁决 | 本文落点/修正 |
|---|---|---|
| Whisper + VAD + 对齐 + 分离四能力组合 | 吸收 | §2、§3、§5 |
| VAD→Whisper→forced alignment→diarization 顺序 | 吸收但细化 | 实际 CLI 先收集所有 ASR，再统一 alignment/diarization；§2、§5.1 |
| silero、wav2vec2、pyannote 分别承担 VAD/对齐/分离 | 吸收 | §3、§8 |
| 单词级时间戳、说话人分轨 | 吸收但补充缺字段/overlap 约束 | §4.1、§7.3 |
| “无 LLM 提示词” | 吸收为边界事实 | 本项目是模型推理管线，没有 LLM prompt 层；§2 |
| “PyTorch + 多模型权重” | 吸收但改为源码证据 | `pyproject.toml`、`asr.py`、`alignment.py`、`diarize.py`；§8 |
| 多模型权重重、适合独立进程+适配层 | 吸收为接入建议，不冒充当前实现 | §6、§12 |
| “BSD-3/MIT” | 不吸收 | 由 `LICENSE`/`pyproject.toml` 裁决为 BSD 2-Clause |
| “各能力独立可复用” | 部分吸收 | 有 Python 函数入口和 VAD 抽象，但当前仍是同进程模型对象，不是独立服务；§3、§12 |
| “与 faster-whisper/FunASR 多提供者并存” | 不作为当前实现事实 | WhisperX 当前只实现 faster-whisper/CTranslate2 主链；其他 provider 只能是外部平台规划 |

## 12. 可复用边界与不可照搬项

### 可吸收

1. 阶段化 VAD+ASR、alignment、diarization 模型生命周期，适合显存受限的执行器。
2. `Vad`/`merge_chunks` 的语音区间边界和 provider 可替换方向。
3. transcript → word/char alignment → speaker augmentation 的逐层结果增强。
4. writer 边界、惰性导入和 `IntervalTree` 区间查询优化。
5. wildcard 与 interpolation 的“可用性回退”思想，但必须在统一契约中标明证据来源。

### 不可直接照搬

- 不把模型下载、GPU、ffmpeg 和文件写入直接嵌入业务 API；外部适配层必须增加 timeout、cancel、错误分类、缓存策略和清理确认。
- 不把 `TypedDict` 当跨进程契约；需运行时 schema、版本、provenance 和缺失字段策略。
- 不把 `nearest`/wildcard 结果说成真实 CTC 对齐。
- 不默认依赖 gated Hugging Face；应有本地模型、token 注入、离线预检和诊断输出。
- 不把仓库当生产服务；缺少队列、状态、限流、鉴权、重试、恢复和制品登记。
- 不让 `utils` 与 `SubtitlesProcessor` 长期形成两个字幕事实 owner；接入平台时必须裁决唯一 writer/字幕契约。

## 13. 后续复核清单（仅建议，未启动实现）

- [ ] 建立短音频/mock 模型夹具，覆盖 `load_audio -> VAD -> ASR -> alignment -> diarization -> writer` 阶段边界。
- [ ] 为每阶段补 error class、timeout、cancel、资源 owner 和 `finally` 清理契约。
- [ ] 为结果增加 `schema_version`、模型/语言/设备 provenance、`alignment_source` 和缺失字段状态。
- [ ] 为输出引入临时文件、原子 rename、manifest、输入唯一 ID 与重复 basename 防护。
- [ ] 独立实测 ffmpeg、离线缓存、punkt、HF token、CPU/CUDA、OOM 和第三方断线。
- [ ] 裁决 `utils` writer 与 `SubtitlesProcessor` 的唯一字幕边界。
- [ ] 核对 `MANIFEST.in` 的 `requirements.txt` 引用、README 示例/TODO 与当前 CLI 同步。

## 14. 架构结论

WhisperX 的真实核心是一个**阶段化、以本地模型为主但可触发外部下载的音频推理库**：`faster-whisper` 批量 ASR 负责文本，VAD 负责可批处理语音区间，语言特定 CTC 模型负责词/字符时间，`pyannote` 负责说话人区间和标签回填，writer 负责文件导出。它验证了“多个小能力组合成一条可解释管线”的参考价值，但没有把队列、任务状态、取消、超时、错误恢复、原子制品和资源验收纳入实现。

因此，底座吸收裁决为：**吸收**阶段边界、结果逐层增强、VAD 抽象、对齐/说话人能力和资源分阶段释放模式；**不吸收**当前的隐式生命周期、无运行时 schema、无取消/超时/恢复、非原子输出和双字幕路径；**待核**所有真实模型/ffmpeg/HF/设备对接及失败终态。本文和源码路径是后续复核入口，`细探-whisperX.md` 保留但不再作为第二事实源。

## 15. 后续：通用底座映射与单链路裁决

### 15.1 当前核对范围、事实与边界

当前核对不是把 WhisperX 当作已经接入平台的实现，而是把当前源码中可复用的音频能力，映射到“音频支持库 → ASR 模块 → 运行核心 → 统一网关”的既有底座分工。凡标为“目标落点/应升级/待建”的内容都是接入裁决，不是当前仓库已有代码。当前仓库仍只有 Python API、CLI 和同进程模型管线，没有平台任务句柄、统一错误码、HTTP 能力网关、持久任务状态或资源租约。

当前核对 `project_context` 返回的项目根错误绑定为 `/Users/hekunhua/Documents/Agent/PHP/华世王镞_v3`，不是本项目；该结果作为环境问题记录，不采用其代码图、记忆、验证或项目结论。本节全部事实来自目标目录本地静态源码与测试；当前核对没有下载模型、调用 GPU、访问 Hugging Face、运行 ffmpeg 音频解码、启动外部服务或执行真实端到端转写。

### 15.2 能力到四层底座映射

| 能力/资源 | 当前 WhisperX owner 与证据 | 音频支持库落点 | ASR 模块落点 | 运行核心落点 | 统一网关边界 | 裁决 |
|---|---|---|---|---|---|---|
| 音频读取、单声道化、16 kHz 重采样 | `whisperx/audio.py:25-65` 的 `load_audio` 直接 `subprocess.run(["ffmpeg", ...])`，返回 `np.float32` | `音频读取` 原子能力；ffmpeg 仅作为受管 provider，不把 CLI 命令泄漏给消费者 | 只提交音频输入句柄，不自行解码 | 创建受限子进程、超时、进程组回收、输出上限、失败证据 | 接收路径/对象引用/输入契约，不直接执行 ffmpeg | 升级现有音频支持库；当前实现不能直接照搬 |
| 补齐/裁切、Mel 特征 | `audio.py:68-159` 的 `pad_or_trim`、`mel_filters`、`log_mel_spectrogram` | 统一 waveform、采样率、dtype、设备搬运和特征契约 | Whisper 推理前的特征参数由 ASR 模块声明 | GPU/CPU 预算、显存峰值、句柄释放 | 只暴露参数契约，不暴露 Torch tensor | 吸收算法边界，升级为运行时可验证契约 |
| VAD 与语音切分 | `vads/vad.py:20-53`、`silero.py:18-69`、`pyannote.py:21-264`；输出 `SegmentX` 后由 `merge_chunks` 合并 | `vad.detect`、`vad.merge_chunks` 两个原子能力；Silero/Pyannote 是同契约 provider | 选择 VAD、阈值、`chunk_size`，把区间送入唯一转写链 | 为 VAD 模型、网络下载、设备和长音频分配预算 | 暴露可校验的切分参数和进度事件 | 吸收“VAD 先切分、再批处理”，不吸收空列表/`assert` 作为稳定外部契约 |
| Whisper 推理 | `asr.py:31-104` 的 `WhisperModel`，`106-298` 的 `FasterWhisperPipeline`，`315-442` 的 `load_model` | `whisper.infer` provider：CTranslate2/faster-whisper、tokenizer、compute type 适配 | `asr.transcribe` 负责语言、任务、prompt、温度回退和 segment 结果语义 | 模型句柄、GPU lease、CPU 线程、OOM/超时/崩溃隔离 | 只调用 ASR 能力，不持有模型对象 | 新建/升级音频 ASR 支持能力；业务不得直连 `faster_whisper` |
| 批处理 | `asr.py:176-195` 建 `PipelineIterator`、`DataLoader`；`197-298` 按 VAD segment 生成 batch | batch tensor 组装和 provider-specific forward | batch size、VAD chunk 与转写结果的对应关系、进度语义 | 队列深度、并发槽位、GPU 显存预算、取消排空 | 请求只声明 batch hint/预算，网关不能自行调 DataLoader | 吸收批处理策略；把调度和资源治理移出当前 Pipeline |
| 语言检测与 tokenizer | `asr.py:236-255`、`300-312`；没有语言时取首 30 秒并修改实例 tokenizer | tokenizer/model adapter 能力 | 语言选择、`.en` 强制 `en`、翻译禁对齐规则 | 模型句柄与临时 tokenizer 生命周期 | 参数校验和结果中的 language 字段 | ASR 模块持有语义，支持库持有第三方对象 |
| CTC forced alignment | `alignment.py:80-114` 装载 torchaudio/HF 模型，`117-424` 做切片、emission、trellis、backtrack、词/字符聚合 | `alignment.infer` provider；语言模型、dictionary、`punkt_tab` 归外部适配边界 | 将 ASR segments 转为对齐结果，明确真实/回退/插值状态 | trellis 内存与 GPU 预算、超时/OOM/取消清理 | 返回可版本化的 words/chars/provenance，不直传 pandas/Torch | 吸收算法和逐层增强；升级为可观测能力 |
| 说话人分离 | `diarize.py:91-182` 的 `DiarizationPipeline`；`185-263` 的 `assign_word_speakers` | `diarization.infer` provider，pyannote 与 token/cache 适配 | 把 diarization intervals 与 aligned transcript 合并，定义 overlap 策略 | 模型/GPU/embedding 内存、gated 模型失败、进程隔离 | 只传 speaker 约束和 token 引用，禁止网关持有 HF SDK 对象 | 吸收区间交集回填；升级为 speaker 证据和失败状态 |
| 结果归一化、句子/词/字符结构 | `schema.py:11-78` 为 `TypedDict`，运行时不校验；alignment 可能缺 `start/end/score` | 统一序列化/结构校验/时间单位和 provenance 原子能力 | 唯一 ASR 结果模型：`segments → words/chars → speaker` | 结果大小上限、取消时部分结果策略、制品句柄 | 契约/执行接口返回 JSON-safe 结果和错误，不返回内部对象 | 新建运行时 schema；不能把当前 TypedDict 直接当跨进程协议 |
| 字幕/JSON/TSV/Audacity 输出 | `utils.py:215-468` 的 writer；`SubtitlesProcessor.py:33-226` 另有一套切分和估时 | 统一 writer/序列化/原子制品能力 | 选择格式、传递结果和 writer 参数 | 临时文件、fsync、原子 rename、manifest、重复名检测 | 只返回制品句柄/下载引用和状态 | 裁决唯一 writer owner；隔离 `SubtitlesProcessor` 的旁路事实源 |
| 模型文件与缓存 | faster-whisper、torchaudio、HF、Pyannote、Silero、NLTK 下载由 `asr.py`/`alignment.py`/`diarize.py`/`vads/*` 触发 | 模型 provider、版本/校验/离线预检和缓存适配 | 选择模型族、语言模型映射和能力版本 | 模型句柄租约、GPU/CPU 资源、缓存并发、下载超时与清理 | token 只接受受控引用；不在网关下载模型 | 模型适配归音频支持库；所有权和预算归运行核心 |
| GPU/CPU/线程 | `load_model` 传 `device/device_index/compute_type/threads`；CLI `torch.set_num_threads`、阶段后 `empty_cache` | 仅执行 provider 的 device adapter | 声明推理所需设备/精度和 batch hint | GPU lease、显存预算、峰值观测、OOM 降级/重试策略、进程隔离 | 暴露可拒绝的资源请求，不暴露 CUDA 对象 | 运行核心 owner；当前全局线程和手动 cache flush 只作线索 |
| 临时文件/中间结果 | 当前没有统一临时工作区；writer 直接写最终路径，HF/torch/NLTK 由第三方管理缓存 | 只使用由运行核心传入的 workspace/artifact handle | 只写阶段结果，不自行创建不可追踪临时目录 | 创建唯一运行目录、生命周期、崩溃回收、原子提交和残留扫描 | 返回 artifact 状态，不暴露本地临时路径 | 运行核心唯一 owner；当前直接写出必须隔离 |
| 外部服务与第三方边界 | ffmpeg 进程、`torch.hub.load`、HF `from_pretrained`、`nltk.download`、gated Pyannote | provider adapter 负责协议、认证引用、错误映射和离线检测 | 只依赖声明好的 provider capability | 网络超时、断线、重试上限、子进程/进程组和证据 | 统一网关是平台外部入口，不是 HF/ffmpeg 代理的业务旁路 | 禁止 ASR 模块/网关直连外部服务；由支持库+运行核心受管 |

### 15.3 唯一转写链路

平台接入时只允许以下一条规范链路；CLI 与 Python API 都必须被视为该链路的项目适配入口，而不是第二套执行引擎：

```text
统一网关: execute(asr.transcribe, request)
  → 请求校验/授权/能力契约解析
  → ASR 模块: 创建唯一转写执行单元
  → 运行核心: 分配 execution_id、截止时间、取消令牌、workspace、资源/模型句柄
  → 音频支持库: audio.read(path|input_ref) → 16 kHz mono waveform handle
  → 音频支持库: vad.detect + vad.merge_chunks → speech chunks
  → ASR 模块: 绑定 language/task/options，提交唯一 batch plan
  → 音频支持库: whisper.infer(batch plan) → transcript segments
  → 运行核心: 记录阶段进度、显存/CPU/子进程与错误证据
  → 音频支持库: alignment.infer(transcript, waveform, language model)
  → ASR 模块: 统一 segments/words/chars 与真实/插值 provenance
  → [可选] 音频支持库: diarization.infer(audio, speaker constraints)
  → ASR 模块: assign speakers，明确 overlap 与 dominant speaker 规则
  → 音频支持库: result.serialize/write 临时制品
  → 运行核心: 校验、fsync、原子提交 artifact handle，释放全部句柄/租约
  → 统一网关: 返回统一结果/事件/制品引用/错误码
```

禁止的侧链包括：网关直接调用 `load_model` 或 `ffmpeg`、业务代码直接实例化 `DiarizationPipeline`、每个 provider 自己实现一遍转写编排、`utils` 与 `SubtitlesProcessor` 并行作为两个字幕 owner、任何隐藏的“模型下载失败就换 provider”分支。`whisperx.__init__` 的延迟 API（`__init__.py:4-31`）和 `whisperx.__main__:cli`（`__main__.py:12-102`）接入时只能归一到同一 `asr.transcribe` 能力契约。

当前 CLI 的真实差异必须保留为缺口：`transcribe_task`（`transcribe.py:20-238`）先把所有文件完成 VAD+ASR，再统一 alignment、diarization，阶段间保留 `results` 和路径；单文件可复用上一轮局部 `audio`，多文件会重新从路径解码，它没有 execution id、持久状态、逐文件提交、回滚、取消或恢复。因此“唯一链路”是目标平台链路，不是声称当前源码已有统一网关。

### 15.4 执行单元、句柄与资源所有权

当前源码没有这些对象；以下是接入平台时必须补齐的最小契约，不能把 Python 模型实例本身当作跨层句柄：

| 对象 | 创建者/持有者 | 最小内容 | 转移与释放 |
|---|---|---|---|
| `transcription_execution` | ASR 模块向运行核心申请 | `execution_id`、输入引用、能力版本、owner/project、状态、deadline、cancel token、错误/进度证据 | 运行核心唯一推进终态；终态后禁止复用/复活 |
| `audio_handle` | 音频支持库经运行核心创建 | 原始输入引用、解码格式、采样率、时长、workspace 路径、摘要 | provider 借用 waveform；执行单元终止或失败时由运行核心释放/清理 |
| `model_handle` | 模型支持 provider 创建 | provider、模型名/版本、缓存摘要、device、compute type、显存估计 | 调用方只能借用；运行核心在阶段结束/失败/OOM/取消时释放，禁止模块直接 `del` 成为唯一清理 |
| `provider_process_handle` | 运行核心监督器创建 | pid、进程组、命令摘要、输入/输出上限、启动时间 | 正常关闭、超时 killpg、崩溃回收均写证据并确认进程不存在 |
| `gpu_lease`/`cpu_lease` | 运行核心资源监督器 | 设备、显存/线程预算、租约截止、占用者 | 超时/取消先停止工作再释放；OOM 不得把租约留给下一个任务 |
| `workspace_handle` | 运行核心创建 | 唯一临时目录、允许写入范围、清理策略、残留扫描结果 | provider 不得越界写；成功原子提交后删中间物，失败/崩溃按策略保留诊断或清理 |
| `artifact_handle` | 运行核心在 writer 成功后登记 | 输入摘要、结果摘要、格式、路径/对象键、完整性、提交状态 | 只允许临时文件→fsync→原子 rename/登记；半写文件不能标成功 |
| `external_session_handle` | 音频支持 provider | 外部模型/下载/认证引用、重试预算、脱敏诊断 | 不把 token 或 SDK session 放入结果；断线/超时由 provider 关闭并归还预算 |

### 15.5 资源生命周期裁决

| 阶段 | 运行核心状态 | 必须存在的资源动作 | 当前 WhisperX 行为 | 平台验收要求 |
|---|---|---|---|---|
| 创建 | `created` | 校验输入、生成执行单元、workspace、deadline/cancel | CLI 只有 argv 和局部变量 | 句柄可读回，非法输入不占 GPU/模型 |
| 准备 | `preparing` | 解析模型/设备/缓存，建立 provider 会话 | `load_model`/`load_align_model` 可能触发下载；无超时 | provider 可用性、版本、缓存和 token 预检 |
| 读取/VAD | `reading`/`segmenting` | 借用 audio handle，启动受管 ffmpeg/VAD，记录时长和 chunks | ffmpeg 无 timeout；VAD 对空语音返回空列表 | 子进程/网络/模型句柄均有 owner，空输入是明确结果 |
| Whisper | `transcribing` | 申请 GPU/CPU lease，批处理，阶段进度，回收 batch 临时对象 | `DataLoader`/PipelineIterator 随调用创建；无取消 | batch 队列可排空，OOM/超时可释放 lease，结果不与错误混合 |
| 对齐 | `aligning` | 按语言取得 alignment model，限制 trellis 内存 | CLI 成功后才 `del align_model`；异常没有 `finally` | 每种终态都释放模型/trellis/GPU；缺模型/缺 punkt 有稳定错误 |
| 分离 | `diarizing` | 创建/借用 diarization model，限制 embedding 大小 | `DiarizationPipeline` 无 `close`；结果原地回填 | speaker 结果与 transcript 版本关联，embedding 可选且限额 |
| 序列化 | `serializing` | 仅写 workspace 临时制品，校验结果 schema | writer 直接 `open(output_path,"w")`；`all` 可能部分成功 | 无最终路径截断写；每个制品有 manifest/摘要/状态 |
| 提交 | `committing` | fsync、原子替换、登记 artifact、释放借用句柄 | 无原子替换/制品登记 | 读回提交状态和文件摘要，重复执行不覆盖不相关输入 |
| 终止 | `succeeded`/`failed`/`cancelled`/`timed_out`/`oom`/`crashed` | 关闭进程、释放模型/GPU、清 workspace、写证据 | 主要依赖正常路径 `del`/GC/进程退出 | 六种终态逐一有测试和残留检查，终态不可复活 |

### 15.6 失败、超时、取消、OOM、崩溃矩阵

| 场景 | 当前源码行为与证据 | 目标归属/动作 | 当前证据等级 |
|---|---|---|---|
| 输入路径不存在、ffmpeg 不存在 | `audio.py:41-65` 仅捕获 `CalledProcessError`；`FileNotFoundError` 可直接冒泡 | 音频支持库映射为 `AUDIO_PROVIDER_UNAVAILABLE`/`AUDIO_DECODE_FAILED`；运行核心回收子进程 | L0 |
| 格式损坏、解码失败、采样率异常 | ffmpeg stderr 转 `RuntimeError`；无结构化错误码 | 音频支持库区分输入错误/提供者错误，保留脱敏 stderr；不可重试输入错误 | L0 |
| 空音频或无活动语音 | Silero/Pyannote 返回空列表并 warning，后续可得到空 `segments` | ASR 模块输出明确 `NO_SPEECH` 结果；不伪装成功转写 | L0，L1 未覆盖 |
| VAD 参数非法/切分边界错误 | `Vad.__init__`、Silero/Pyannote `merge_chunks` 使用 `ValueError`/`assert` | 网关/模块先做契约校验；provider 不以 `assert` 作为外部错误协议 | L0 |
| Whisper 模型缺失、下载失败、token/缓存错误 | `load_model` 下游异常冒泡；`local_files_only` 只控制部分缓存读取 | 音频支持库映射 `MODEL_UNAVAILABLE`；运行核心按下载/认证/输入区分可重试 | L0 |
| Whisper 推理超时或 callback 抛错 | 无 timeout/cancel 专用路径；异常向上冒泡，模型释放依赖调用者 | 运行核心设置硬 deadline，取消 token 传播至 provider，超时后 kill/排空并释放 lease | L0 |
| GPU OOM/CPU 内存超限 | 当前无 OOM 捕获、降 batch、重试或预算；可能由 Torch/CTranslate2 直接抛出 | 运行核心记录资源峰值，停止当前执行，释放显存；是否降 batch 必须是显式策略，不能隐藏 fallback | L0 |
| alignment 无默认模型/`punkt_tab` 缺失 | `load_align_model` 抛 `ValueError`；`alignment.py:149-157` 可能运行时 `nltk.download`，失败 `RuntimeError` | 音频支持库离线预检/下载 provider；ASR 模块返回对齐失败或明确跳过，不把原 segment 当完整对齐 | L0；L1 仅有 mock align 主路径 |
| trellis/backtrack 失败、字符无法对齐 | `alignment.py:235-245`、`294-297` 保留原 segment；插值可补缺失词 | 结果中记录 `alignment_status`、`alignment_source=estimated/original`，消费者不得误认模型证据 | L0/L1 |
| diarization gated 模型、token 无效、第三方异常 | `DiarizationPipeline` 直接调用 `Pipeline.from_pretrained`；CLI 只 warning 无 token | 音频支持库映射认证/提供者故障；ASR 模块可按请求策略“失败即终止”或“明确无 speaker”，不可静默成功 | L0 |
| diarization 超时/取消/崩溃 | 无 `close`、无 timeout/cancel；pyannote 对象由 GC/进程退出回收 | 运行核心隔离 provider 进程/会话，取消后关闭进程组，确认 embeddings 和 GPU 释放 | L0 |
| 输出 I/O 失败、重复 basename、写到一半崩溃 | `ResultWriter` 直接覆盖 basename；`get_writer("all")` 逐 writer 写，可能部分成功 | 运行核心 workspace+原子提交+唯一输入 id+manifest；部分制品统一标记失败并可清理 | L0 |
| 宿主 SIGTERM/SIGKILL 或 Python 崩溃 | 无信号处理、恢复状态、崩溃清单；OS 只回收进程级资源 | 运行核心以独立进程组和持久执行状态恢复/清理；重启后不得把旧句柄当活跃 | L0 |
| 取消、超时后的重复释放/重试 | 当前没有取消协议，重复调用可能覆盖模型 tokenizer/结果 | 句柄释放幂等，重试只允许在能力契约声明可重试且新 execution_id 下进行 | L0 |

矩阵结论：当前源码能证明若干异常会抛出或回退，但不能证明超时、主动取消、OOM、宿主崩溃、第三方断线后的资源终态。平台接入验收必须至少读回进程表、GPU/lease、临时目录、制品状态和错误证据，不能只看调用返回值。

### 15.7 后续复用/升级/新建/隔离裁决

| 裁决 | 内容 | 原因 |
|---|---|---|
| 吸收 | VAD 区间、`merge_chunks`、ASR segment→alignment words/chars→speaker augmentation、批处理降低推理开销、进度 callback 的阶段边界 | 这些是源码已证实的领域模式，可转为公共契约 |
| 升级现有音频支持库 | `audio.read`、`vad.detect/merge`、`whisper.infer`、`alignment.infer`、`diarization.infer`、唯一 writer/序列化 | 原子能力边界清楚，但当前实现缺 schema、错误、超时、取消、资源 owner |
| 升级 ASR 模块 | 统一 `asr.transcribe` 编排、语言/任务/对齐/分离策略、结果 provenance、空语音和部分阶段策略 | 领域流程应集中在一个模块，不能让每个 provider 编排一条链 |
| 升级运行核心 | 执行单元、句柄、GPU/CPU lease、模型缓存租约、workspace、外部进程组、deadline/cancel、OOM/crash 清理、artifact 原子提交 | 当前最主要缺口不属于 Whisper 算法，而属于运行治理 |
| 接入统一网关 | `search → contract → execute` 暴露 ASR 模块能力，统一授权、错误、进度、结果和制品引用 | 当前仓库没有 HTTP/RPC；网关必须成为唯一外部入口，不直连第三方 |
| 新建原子能力 | 音频格式探测、受限 ffmpeg 解码、模型可用性预检、alignment 证据标注、speaker overlap 策略、结果 schema 校验 | 当前没有可复用的跨进程稳定契约，不能仅把函数名搬过去 |
| 隔离/废弃 | 直接 `subprocess.run(ffmpeg)`、第三方 SDK 穿透模块、直接 HF/NLTK 下载、`del model` 作为唯一释放、双 writer、原地修改作为跨层契约 | 与单网关、单 owner、资源可审计原则冲突 |
| 待核 | 实际 GPU/CUDA/CPU wheel、模型版本和显存、ffmpeg 支持格式、HF gated 协议、pyannote embedding 成本、长音频批处理吞吐 | 当前核对没有真实外部依赖和端到端运行证据 |

### 15.8 后续 L0-L4 验证分层

| 等级 | 当前核对可声称的内容 | 不能声称的内容 | 证据 |
|---|---|---|---|
| L0 源码静态事实 | 已定位入口、音频读取、VAD、ASR batch、alignment、diarization、writer、模型/缓存/外部边界和失败分支 | 不能称为运行通过或平台已接入 | 目标仓库源码路径及本文件 §2-§15 |
| L1 测试源码存在 | 现有单测覆盖 mock emission、wildcard、数字/符号词、插值和相邻词不污染 | 不能推导 ffmpeg、模型、GPU、分离、CLI 端到端 | `tests/test_word_timestamp_interpolation.py:54-231` |
| L2 本地真实执行 | 仅在实际执行命令退出 0、读回测试数/失败数后，才可把该命令对应的窄路径记为 L2 | 不把 CI 配置、文件存在、历史输出算 L2 | 当前核对实际命令与退出码见 §15.9；pytest 缺失时保持未验证 |
| L3 外部边界实测 | 只有真实 ffmpeg、模型缓存、GPU/CPU provider、HF/NLTK、token/网络等运行且读回资源结果才可记 L3 | 当前核对未运行真实 ffmpeg 解码、模型下载、GPU、HF、gated Pyannote 或外部服务 | 明确未执行；因此这些边界均未达 L3 |
| L4 端到端与终态 | 只有真实音频完成唯一链路，并验证成功/失败/超时/取消/OOM/崩溃和残留清理才可记 L4 | 当前仓库没有任务句柄、取消协议、恢复/制品验收；当前核对未达成 | 当前最多 L0/L1；窄单测实跑后可局部 L2 |

### 15.9 当前核对验证记录与剩余风险

- **静态验证：** 已现场读取 `ARCHITECTURE.md`、旧细探、`pyproject.toml`、`whisperx/__main__.py`、`__init__.py`、`transcribe.py`、`audio.py`、`vads/*`、`asr.py`、`alignment.py`、`diarize.py`、`schema.py`、`utils.py`、`SubtitlesProcessor.py` 和现有测试；路径与行号以当前工作树为准。
- **真实外部依赖：** 当前核对明确未运行 `ffmpeg` 解码，未下载/加载 faster-whisper、CTranslate2、Silero、Pyannote、torchaudio/Hugging Face alignment、NLTK `punkt_tab` 或 gated 模型，未使用 HF token，未启动 HTTP/RPC/数据库/队列服务，未验证 GPU/CUDA/显存/OOM，也未做真实多文件 CLI 转写。
- **验证命令与退出码：** `python3 -m py_compile whisperx/__init__.py whisperx/__main__.py whisperx/alignment.py whisperx/asr.py whisperx/audio.py whisperx/diarize.py whisperx/schema.py whisperx/transcribe.py whisperx/utils.py whisperx/vads/vad.py whisperx/vads/silero.py whisperx/vads/pyannote.py whisperx/SubtitlesProcessor.py` 退出码 **0**，仅证明 Python 源码可编译；`python3 -m pytest tests/test_word_timestamp_interpolation.py -q` 退出码 **1**，原因是当前解释器 `No module named pytest`，未安装依赖、未重跑、未将其记为通过。
- **工作区边界：** 只对目标根 `ARCHITECTURE.md` 执行了文档 patch；`细探-whisperX.md`、源码、测试、`pyproject.toml`、依赖和 Git 未修改，旧细探仍保留。
- **验证边界：** 现有测试源码使用 `MagicMock` emission/model 和合成 `torch` waveform，属于窄对齐行为测试；当前未因 pytest 缺失而执行它，即使后续命令通过，也不等于外部模型、音频读取、GPU、说话人分离或输出链通过。
- **剩余风险：** 仍需后续在隔离环境补齐真实音频夹具、ffmpeg 超时/坏输入、模型缓存/认证/断线、GPU OOM、取消、SIGKILL、进程残留、workspace 清理、原子制品和唯一网关回归；未有证据前不得把后续映射写成已落地能力。

## 16. 后续结论

WhisperX 对通用底座的核心贡献不是“再造一个 ASR 服务”，而是提供一组可收敛到单链路的音频原子能力：`音频读取/归一化 → VAD 切分 → batched Whisper → CTC 对齐 → 可选说话人分离 → 统一结果/制品`。其中，**音频支持库**拥有第三方音频/模型 provider 的薄适配和结果基础结构，**ASR 模块**拥有唯一领域编排与结果语义，**运行核心**拥有执行单元、句柄、GPU/模型/临时目录/进程生命周期及故障终态，**统一网关**拥有唯一外部入口、授权、契约、事件和制品引用。

最终后续裁决：**吸收** VAD+批处理+对齐+speaker augmentation 的领域边界；**升级**音频支持库和 ASR 模块以补运行时 schema、错误、超时、取消和 provenance；**补齐**运行核心的资源/执行治理与统一网关接入；**隔离**当前直接 ffmpeg/HF/模型 SDK、隐式释放、双 writer 和非原子输出。当前仅完成源码研究与文档映射，未修改生产底座，也未运行真实外部依赖。

## 17. 后续收口：转写、对齐、分离、资源与故障终态补证

本节是对前述建档/后续映射的后续源码收口，专门补上容易被“管线概览”掩盖的参数失效、状态污染、设备不一致、批处理边界、外部下载和释放缺口。以下均是当前提交 `2cfd7b7c5c7bba144954364db747319b50e8232b` 的静态源码事实；不是对生产底座的实现承诺。

### 17.1 CLI/编排的实际语义与隐藏状态

| 位置 | 深挖事实 | 对外影响 |
|---|---|---|
| `__main__.py:12-98` → `transcribe_task` | `cli` 只做 argparse、日志配置和一次函数调用；没有 `try/except`、退出码映射、信号处理或任务句柄。`transcribe_task` 通过 `args.pop(...)` 消费传入字典，调用者若复用原字典会看到参数被删除。 | CLI 异常通常以未分类 traceback 结束；Python 嵌入调用者必须自己拥有异常、超时和生命周期。 |
| `transcribe.py:47-50,84-86` | `task="translate"` 强制 `no_align=True`；未指定语言时预先把 `align_language` 设为 `"en"`，只是为了先加载英文 alignment 模型。 | 翻译没有对齐是硬编码规则，不是可配置 provider 选择；未指定语言时不能把初始 alignment 语言当成真实音频语言。 |
| `transcribe.py:88-112` 与 `__main__.py:51-73` | CLI 声明了 `--best_of`、`--condition_on_previous_text`、`--fp16`、`--segment_resolution`，但编排没有取出/传递这些值；`asr_options` 又硬编码 `condition_on_previous_text=False`。`best_of` 留在 `default_asr_options` 的默认值而非 CLI 值。 | 这些参数目前是“可见但不生效”或被覆盖的配置漂移，不能写入外部能力契约；应以源码实际生效字段为准。 |
| `transcribe.py:147-158,165-201` | Part 1 对每个文件解码并转写，只保存 `(result, audio_path)`；单文件 alignment 复用循环末的 `audio`，多文件 alignment 从路径再次调用 `load_audio`。因此不是所有原始 waveform 常驻内存，但所有转写结果会跨阶段聚合。 | 多文件的磁盘 I/O 会在 alignment 再次发生；长批次仍有结果聚合峰值，不是逐文件完成/提交。 |
| `transcribe.py:181-187,236-238` | 检测到与当前 alignment metadata 不同的语言时直接重新赋值 `align_model`/metadata，没有先 `del`、`gc.collect`、`empty_cache`；最终写文件前又无条件执行 `result["language"] = align_language`。 | 多语言/未指定语言输入的输出 language 可能被错误写成初始 `en`；旧语言 alignment 模型的 GPU 释放延迟且无显式证据。 |
| `transcribe.py:160-163,203-206,218-238` | ASR/VAD 与 alignment 只有正常走到阶段末才 `del`；没有 `finally`。diarization 实例在函数返回前也没有对等释放。 | `load_model`、单文件转写、alignment、diarization 或 writer 任一异常时，嵌入式进程可能继续持有模型/显存；进程退出掩盖了 CLI 的释放问题。 |

另一个状态污染点在 `asr.py:256-296`：`suppress_numerals` 会临时替换 `self.options.suppress_tokens`，未预设语言时会临时创建 tokenizer；只有正常走到函数尾才恢复。模型生成异常或 progress callback 抛错时，pipeline 对象可留下修改后的 options/tokenizer，随后复用同一对象的结果不再等价于第一次调用。

### 17.2 VAD、ASR 与批处理边界

1. `load_model` 的默认 `vad_method` 是 `pyannote`（`asr.py:315-432`），其 `Pyannote` VAD 使用包内 `whisperx/assets/pytorch_model.bin`；只有 `vad_method="silero"` 才在 `Silero.__init__`（`vads/silero.py:18-31`）执行未固定版本的 `torch.hub.load("snakers4/silero-vad", ..., trust_repo=True)`。因此“VAD”不是一个纯内存算法，至少有本地权重和可触发远端仓库代码/缓存两条边界。
2. `Silero.__call__` 只接受 16 kHz，使用 `max_speech_duration_s=chunk_size`；`Pyannote.merge_chunks` 先用 `Binarize(max_duration=chunk_size)` 切断长活动区间，再调用 `Vad.merge_chunks`。`Vad.merge_chunks`（`vads/vad.py:20-53`）直接访问 `segments[0]`，具体子类才对空结果返回 `[]`；其收集的 `speaker_idxs` 从未写入输出。`chunk_size<=0` 依赖 `assert`，不是稳定的外部错误协议。
3. `FasterWhisperPipeline.transcribe` 先 VAD，再按 `(start,end)` 切 waveform；`preprocess` 用 `padding=N_SAMPLES-audio.shape[0]` 补到最多 30 秒 Mel 输入。`WhisperModel.generate_segment_batched` 固定一个 prompt 复制给整个 batch，且 `without_timestamps=True`；segment 时间来自 VAD chunk，不是 Whisper 原生词时间。
4. `get_iterator`（`asr.py:176-195`）按 `torch.stack` 组 batch，`DataLoader(num_workers=num_workers, batch_size=batch_size)` 没有动态降 batch、队列上限或 OOM 回退。`num_workers` 是调用级 DataLoader 参数，不是任务级资源租约；worker/iterator 在异常或取消时没有显式排空和回收协议。首次构造 iterator 还会全局写入 `TOKENIZERS_PARALLELISM=false`，不保存/恢复宿主原值。
5. `batch_size = batch_size or self._batch_size`（`asr.py:264`）把 0 当作“未提供”；随后只有 0/1/None 才取 batch 第一个元素。CLI 的 `--batch_size 0` 因此不是一个可依赖的禁用批处理开关。进度按 VAD segment 数计算，callback 只报告百分比；没有取消返回值/取消 token，callback 异常直接打断调用。
6. 未给语言时 `detect_language` 只取音频前 30 秒（`asr.py:300-312`），短音频只 warning；每个未预设语言文件都可能重新检测、创建 tokenizer。`.en` 架构强制 `en`（`asr.py:354-364`）。

### 17.3 对齐：输入形状、模型装载、CTC 内存与回退

| 主题 | 源码事实 | 需要防止的误读 |
|---|---|---|
| 输入契约 | `align` 标注 `Iterable`，实际先执行 `len(transcript)`，随后又两次 `enumerate(transcript)`（`alignment.py:159-214`）；生成器既不能通过 `len`，一次性迭代器也不能安全复用。 | 对外契约应是可 `len` 且可重复迭代的 segment 序列，不能只按类型注解放行任意 iterable。 |
| 模型选择 | `load_align_model` 对 `en/fr/de/es/it` 优先走 torchaudio bundle；其他默认语言或显式名称走 HF `Wav2Vec2Processor/ForCTC`。`model_cache_only` 只传给 HF 的 `from_pretrained`，torchaudio `bundle.get_model(dl_kwargs={"model_dir": ...})` 没有同等离线开关（`alignment.py:80-114`）。 | “缓存只读”不是所有 alignment provider 的共同保证；torchaudio 分支仍可能触发下载。 |
| 文本清洗 | 空格语言用 `|` 表示空格，`ja/zh` 按字符处理；未知字符不丢弃，而是把 emission 非 blank 各列最大值作为 wildcard 列（`alignment.py:174-199,278-289`）。 | 数字、标点、外文字符得到的时间是 wildcard 估计，不是对应字符的原始 CTC 类别证据。 |
| 计算与内存 | 每个 segment 串行切 waveform、推理；emission 经过 `log_softmax` 后搬回 CPU，`get_trellis` 在 CPU 建立 `(num_frame+1, num_tokens+1)` 张量（`alignment.py:246-292,431-451`）。没有按帧/token 的预算、最大时长、OOM 捕获或批量 alignment；trellis 规模随音频帧×文本 token 增长。 | GPU 释放不等于总内存有界；超长 segment 可能在 CPU trellis 或 DataFrame 阶段耗尽内存。 |
| 缺失与回退 | 无字符、起点超过音频时长、backtrack 失败会保留原 segment；词缺时间时按 `nearest`/`linear`/`ignore` 补或保留（`alignment.py:235-245,294-297,371-383`）。`linear` 最后仍有 `ffill/bfill` 边界填充（`utils.py:470-476`）。 | “返回了 word”不等于完成了可靠对齐；结果没有 `alignment_status`/`alignment_source` 字段。 |
| 外部句切 | 每次 `align` 首先读取 `tokenizers/punkt_tab/<lang>.pickle`；缺失时执行 `nltk.download('punkt_tab', quiet=True)`（`alignment.py:146-157`），下载没有 timeout、取消或下载锁。HF 加载异常被打印后统一包成 `ValueError`。 | 网络、缓存、模型认证失败会在推理中途发生，原始异常类别和可重试性不再完整保留。 |

### 17.4 说话人分离与标签回填

- `DiarizationPipeline.__init__`（`diarize.py:91-103`）把 `Pipeline.from_pretrained(model_config, token=token, cache_dir=cache_dir)` 的 pyannote pipeline 持有在 `self.model`，默认模型是 gated 的 `pyannote/speaker-diarization-community-1`；对象没有 `close`/上下文管理器。CLI 在 `transcribe_task` 只对缺 token 发 warning，随后仍尝试加载。
- `__call__` 对路径再次 `load_audio`，对数组建立 `torch.from_numpy(audio[None, :])`；progress callback 通过 pyannote 的 segmentation/embeddings hook 映射到 0–99，再末尾直接回调 100。hook 没有取消语义，pyannote 内部异常直接冒泡。`return_embeddings=True` 时将每个 embedding `.tolist()` 放进结果，可能显著放大内存和 JSON 制品。
- `assign_word_speakers` 先把 DataFrame 复制成排序数组，再按交集时长累加并选择一个 dominant speaker；segment/word 都是原地写入，词没有 `start` 就跳过。overlap speech 不保留多 speaker 分布；`fill_nearest=True` 才在无交集时用最近区间。
- `IntervalTree.query` 虽然用 `searchsorted` 缩小候选起点范围，但随后对从 0 到 `right_idx` 的前缀做布尔扫描；在大量重叠区间时查询并非严格 O(log n)，`find_nearest` 还每次重算全体 midpoint 并 `argmin`，是 O(n)。源码注释中的“~228x/ O(log n)”只能视为特定基准的宣传/经验，不应当写成最坏复杂度契约。
- 空 transcript 或空 diarization 在 `assign_word_speakers` 开头直接原样返回；此早退发生在追加 `speaker_embeddings` 之前，不能把“调用返回”当作已完成 speaker 结果。重复调用会覆盖既有 `speaker` 字段，没有版本/快照/回滚。

### 17.5 音频、模型、GPU 与外部服务边界

| 资源/边界 | 实际行为 | 后续裁决 |
|---|---|---|
| ffmpeg | `load_audio` 以 `ffmpeg -nostdin -threads 0 -i <file> -f s16le -ac 1 -ar 16000 -` 启动 `subprocess.run(capture_output=True, check=True)`；stdout 全部驻留后再转 NumPy。只捕获 `CalledProcessError`；命令不存在的 `FileNotFoundError`、OS 错误和超时均不统一。 | 受管 provider 必须有 deadline、进程组、stdout/音频时长上限、可读错误分类和残留读回；当前函数不是可取消解码器。 |
| 模型/缓存 | faster-whisper/CTranslate2、Silero torch hub、torchaudio bundle、HF Wav2Vec2、NLTK punkt、gated pyannote 都由库内调用触发；没有统一下载锁、版本 pin、校验摘要、下载 timeout 或断点恢复。 | 不能把 `download_root`/`model_dir` 当成完整离线与缓存一致性协议；认证 token 只在 diarization CLI 路径显式存在，alignment HF 没有 token 参数。 |
| 精度/设备 | `load_model` 只有 `device == "cuda"` 时把 `default` 解析成 `float16`，传入 `"cuda:0"` 会走 `float32` 分支。`device_index` 传给 faster-whisper 和 CUDA VAD，但 alignment/diarization 只接收 `device`，未按 `device_index` 显式绑定同一 GPU。 | 设备、精度、显存预算必须由运行核心统一解析；当前 CLI 的多 GPU 语义不是全链路一致的设备选择。 |
| CPU/GPU 生命周期 | `torch.set_num_threads(threads)` 是进程全局设置；CLI 的 `threads=0` 时仍把 faster-whisper `cpu_threads` 设为 4。阶段结束的 `gc.collect`/`torch.cuda.empty_cache` 只发生在正常路径；`empty_cache` 不能释放仍被引用的模型/张量。 | 线程和 GPU 必须租约化、可读回；不能把一次 `empty_cache()` 日志当作资源释放验收。 |
| Mel cache | `audio.mel_filters` 使用 `@lru_cache(maxsize=None)`，键包含 device；第一次在 CUDA device 上调用会把 filter tensor 留在无界进程缓存中，直到进程退出。 | 长驻进程需限定/显式清理此缓存，否则模型释放后仍可能留有 GPU 缓存对象。 |
| 服务边界 | 仓库没有 HTTP/RPC server、队列、数据库或持久任务；“外部服务”实际是 ffmpeg 子进程、模型仓库/缓存、torch hub、HF、NLTK 和 gated 模型。 | 接入平台时这些都应归 provider/运行核心受管，统一网关不可直接暴露第三方 SDK 或命令。 |

### 17.6 四种终态的资源证据矩阵

| 终态 | 当前能证明的动作 | 当前不能证明的动作 | 必须读回的证据 |
|---|---|---|---|
| 正常完成 | `subprocess.run` 返回后子进程句柄回收；writer 的 `with open` 关闭单文件；CLI 阶段末尝试 `del`/GC/cache flush。 | 全链路模型显存归还、mel cache 清空、唯一制品完整提交；diarization 没有显式 close。 | 子进程/进程组不存在、GPU 显存/租约、缓存、输出摘要与文件大小。 |
| 业务失败 | 多数异常向上冒泡；`CalledProcessError`/缺 punkt/非法参数有部分转换或提示。 | 统一错误码、可重试性、partial result manifest、模型/线程/worker 的 finally 清理。 | 异常类型与脱敏 stderr、阶段状态、模型句柄、临时目录和已生成文件清单。 |
| 主动取消/超时 | 源码没有 timeout、cancel token、signal handler；只能由宿主中止同步调用或进程。 | ffmpeg、DataLoader、CTranslate2、CTC、pyannote 是否停止；GPU/线程/缓存是否归还。 | kill 后进程组、worker、端口/句柄、GPU lease、workspace、半写文件。 |
| 宿主/子进程崩溃 | OS 通常回收进程级资源。 | 输出原子性、缓存临时文件、任务恢复/幂等、模型和第三方状态的应用级清理。 | 重启扫描 orphan workspace/cache、制品校验/manifest、持久任务终态；当前仓库不存在这些对象。 |

### 17.7 当前核对收口结论与未验证项

**已吸收的真实模式：** VAD 区间 → 30 秒级批处理 → CTranslate2/faster-whisper 文本 → 语言特定 CTC alignment → pyannote speaker interval → 原地标签增强 → 多格式 writer；阶段边界、wildcard/插值回退和显式 progress hook 可作为领域参考。

**必须隔离的实现缺口：** 参数失效/覆盖、默认语言覆盖真实检测语言、无界 `mel_filters` GPU cache、设备 index 不贯穿 alignment/diarization、直接 ffmpeg/torch hub/HF/NLTK 下载、无 timeout/cancel/signal/finally、无 OOM/worker 回收、pyannote 无 close、dominant speaker 单标签、原地结果与非原子 writer。

**当前核对没有声称的验证：** 未下载/加载任何模型或 HF gated pipeline，未调用 HF token，未执行真实 ffmpeg 解码、GPU/多 GPU、长音频/多文件批处理、OOM、DataLoader worker 异常、网络断线、timeout、主动取消、SIGTERM/SIGKILL、崩溃恢复或显存/进程/缓存残留读回。现有测试仍只覆盖 mock alignment/interpolation 窄路径；`pytest` 依赖在当前解释器缺失，不能记为运行通过。

**后续裁决：** WhisperX 适合作为“本地模型推理算法与阶段结果语义”的源码参考，不适合作为可直接嵌入的任务执行器。平台若吸收，必须把 `audio.read`、VAD、ASR batch、alignment、diarization、serialization 各自包成受管 provider/能力，并由运行核心统一拥有 deadline、cancel、GPU/CPU lease、模型缓存、进程组、workspace、artifact 原子提交和四终态清理证据；不能以当前 CLI 的阶段末 `del`/`empty_cache` 代替这些契约。

## 18. 第四轮核对：从输入到资源终态的逐项事实清单

本节再次对根文档、`细探-whisperX.md` 和当前源码逐项交叉检查。旧细探保留，不作为第二事实源；与源码不一致的旧表述以本节和前文源码证据为准。以下仍是静态研究结论，没有把模型、GPU、ffmpeg 或外部网络调用写成已实测。

### 18.1 音频读取与特征

- `audio.load_audio` 是唯一实际音频解码入口：通过 `ffmpeg -nostdin -threads 0 -i <file> -f s16le -ac 1 -acodec pcm_s16le -ar 16000 -` 把任意受 ffmpeg 支持的输入转成单声道、16 kHz、`float32` NumPy waveform（`whisperx/audio.py:25-65`）。它依赖系统 `ffmpeg`，没有 Python 解码 fallback。
- `subprocess.run` 使用 `capture_output=True, check=True`，因此完整 PCM stdout 先驻留在内存，再经 `np.frombuffer` 转换；没有 `timeout`、输出上限、进程组、取消处理或残留进程确认。`CalledProcessError` 被转成 `RuntimeError`，但 `FileNotFoundError`、其他 OS 错误和超时并没有统一错误分类。
- `pad_or_trim` 将输入补齐/截断到 Whisper 的 30 秒、480000 samples；`log_mel_spectrogram` 使用 400 点 FFT、160 hop 和包内 `mel_filters.npz`。`mel_filters` 使用 `lru_cache(maxsize=None)` 且键含 device，长期驻留进程可能无限积累不同设备的 filter tensor（`audio.py:68-159`）。
- 输入音频通常在 Part 1 每个文件解码一次；多文件 alignment 和 diarization 又按路径重新解码，不能把“阶段间结果聚合”误读成原始 waveform 全部常驻内存，也不能把它误读成流式处理。

### 18.2 VAD 与 Whisper 批量转写

- `load_model` 默认 VAD 是 `pyannote`；该路径读取包内 `whisperx/assets/pytorch_model.bin`，并通过 `Model.from_pretrained` 与 `VoiceActivitySegmentation` 建立 pipeline。`silero` 路径执行 `torch.hub.load('snakers4/silero-vad', ..., trust_repo=True)`，首次运行可触发远端仓库代码/权重和缓存（`asr.py:315-442`、`vads/pyannote.py:21-49`、`vads/silero.py:18-31`）。
- 两种 VAD 都要求 16 kHz；Pyannote 先把 NumPy 音频变为 `[1, samples]` Tensor，Silero 使用 waveform 映射。Pyannote 的 `Binarize(max_duration=chunk_size)` 和 Silero 的 `max_speech_duration_s=chunk_size` 都会限制活动段长度，然后 `merge_chunks` 合并为 `SegmentX` 列表。无活动语音返回空列表并 warning；`chunk_size <= 0` 依赖 `assert`，不是稳定外部错误协议。
- `FasterWhisperPipeline.transcribe` 只对 VAD chunk 做切片和 batch；`preprocess` 将每段补至最多 30 秒 Mel 输入，`generate_segment_batched` 固定 `without_timestamps=True`。因此返回的 segment 时间来自 VAD chunk，词级时间必须由后续 CTC alignment 产生，不能把 ASR segment 当作原生词时间。
- `batch_size` 经 `batch_size or self._batch_size` 归一，0 会被当成未提供；DataLoader 没有动态降 batch、队列上限、OOM 回退或取消排空。进度 callback 只报告百分比，不具有取消语义；callback 抛异常会中断推理。
- 未指定语言时只用音频前 30 秒检测语言；短音频仅 warning。`.en` 架构强制 `en`。`transcribe_task` 的 `condition_on_previous_text` 固定为 `False`，若干 CLI 字段（如 `best_of`、`fp16`、`segment_resolution`）没有完整传入实际编排，不能把 CLI 可见参数全部视为生效契约。

### 18.3 对齐与说话人分离

- `load_align_model` 对英语、法语、德语、西班牙语和意大利语优先使用 torchaudio bundle，其他默认语言或显式名称走 Hugging Face `Wav2Vec2`。`model_cache_only` 只传给 Hugging Face `local_files_only`，torchaudio bundle 没有同等离线开关（`alignment.py:80-114`）。
- `align` 实际要求 transcript 可 `len` 且可重复迭代，虽然注解写作 `Iterable`；生成器不能满足这一隐含契约。它依赖 NLTK `punkt_tab`，缺失时在推理过程中执行 `nltk.download`，没有下载超时、取消或下载锁。未知字符通过 wildcard emission 列估计，`nearest`/`linear` 通过插值补时；这些结果必须标为回退/估计，不能冒充原始 CTC 字符证据。
- 对齐按 segment 串行推理，emission 回 CPU 后建立 `(num_frame + 1) × (num_tokens + 1)` trellis；没有时长/token 上限、内存预算、OOM 捕获或批量 alignment。无可用字符、起点超过音频时长或 backtrack 失败时保留原 segment，词字段可能缺 `start/end/score`。
- `DiarizationPipeline` 默认加载 gated 的 `pyannote/speaker-diarization-community-1`，token、cache_dir 和 device 在构造时传入；调用路径字符串时会再次 `load_audio`，并构造 `[1, samples]` waveform。进度 hook 只映射 segmentation/embeddings 进度，不提供取消。
- `assign_word_speakers` 对 diarization 区间建立排序数组并按交集时长选择单一 dominant speaker；`fill_nearest=True` 才在无交集时填最近 speaker。重叠语音的多 speaker 分布不保留；结果和 words 原地修改，`return_embeddings=True` 时 embedding 被转成 Python list 放入结果，可能显著扩大内存和 JSON。

### 18.4 GPU、模型、缓存与设备一致性

- Whisper 模型由 `faster_whisper.WhisperModel`/CTranslate2 持有；alignment 由 torchaudio 或 Hugging Face 模型持有；VAD 和 diarization 另有 PyTorch/pyannote 对象。它们不是统一模型池，也没有版本摘要、下载锁、缓存校验、租约或显式 `close` 契约。
- `compute_type="default"` 只在 `device == "cuda"` 时解析为 `float16`，否则为 `float32`；例如 `cuda:0` 不走同一分支。Whisper 的 `device_index` 传入 faster-whisper，Pyannote VAD 在 `device == "cuda"` 时手工拼接 `cuda:<index>`，但 alignment 和 diarization 只接收 `device`，多 GPU 设备选择不是全链路一致契约。
- CLI 的 `torch.set_num_threads` 是进程全局设置；`load_model` 默认 CPU threads 为 4。`gc.collect()` 与 `torch.cuda.empty_cache()` 只能在正常阶段末由 CLI 调用，且 `empty_cache()` 不会释放仍被引用的模型/张量。异常、取消、OOM 和嵌入式复用没有 `finally` 清理保证。
- `FasterWhisperPipeline.transcribe` 在正常返回时才恢复临时 tokenizer 和 `suppress_tokens`；模型生成异常或 progress callback 异常可能留下被修改的 pipeline 状态。`_sanitize_parameters` 的 tokenizer 分支读取 `kwargs["maybe_arg"]`，但没有对应的稳健参数契约，扩展 Hugging Face Pipeline 参数前应补测试。

### 18.5 临时文件、外部边界、失败与资源生命周期

| 资源/阶段 | 当前实现 | 失败或中断缺口 | 接入时必须补齐 |
|---|---|---|---|
| ffmpeg 解码 | 同步子进程，stdout 全量捕获 | 无 timeout/cancel/进程组/输出上限；异常分类不完整 | 受管 provider、deadline、killpg、脱敏 stderr、残留读回 |
| VAD/Whisper 模型 | 本地 asset、Torch Hub、faster-whisper/CTranslate2 | 下载、ABI、认证、OOM 异常向上冒泡；无统一释放 | 模型句柄、缓存摘要、设备/精度预算、失败释放和可重试分类 |
| alignment/Punkt | torchaudio/HF 模型与运行时 NLTK 下载 | 下载可能发生在推理中；trellis 可随输入增长 | 离线预检、下载超时/锁、最大时长和内存预算 |
| diarization/embedding | pyannote pipeline 无 `close`；embedding 可进入结果 | gated token、第三方异常、取消后无显式 GPU/对象回收 | provider 进程或会话隔离、embedding 限额、speaker 证据和关闭确认 |
| waveform/tensor/worker | NumPy、Torch tensor、DataLoader iterator 随调用生成 | 多阶段引用、异常和 worker 中断无统一排空；GPU cache 无界 | workspace/句柄 owner、队列上限、finally、GPU/CPU lease 和残留扫描 |
| 输出制品 | writer 直接 `open(output_path, "w")`；`all` 逐格式写 | 崩溃可截断；重复 basename 可覆盖；可部分成功 | 临时文件、fsync、原子 rename、唯一输入 id、manifest 和提交状态 |
| 任务终态 | CLI 只有同步函数和阶段末释放 | 无 execution id、持久状态、timeout、cancel、resume、signal handler | `succeeded/failed/cancelled/timed_out/oom/crashed` 六类终态及逐类资源证据 |

### 18.6 核对结论与证据边界

旧细探的核心判断“Whisper + VAD + forced alignment + diarization”成立，但应修正为：当前实现是同一 Python 进程内的阶段化本地模型管线，不是四个独立服务；Whisper 的批量文本、语言特定 CTC 对齐、pyannote speaker interval 和 writer 才是源码已证实的能力边界。旧细探中的许可证、独立服务化和“可直接并存多 provider”等泛化表述不应覆盖当前源码事实。

当前核对仍未执行 `ffmpeg` 解码、模型下载/加载、HF gated 认证、NLTK 下载、GPU/CUDA 推理、OOM/取消/崩溃场景或真实端到端音频；因此上述 GPU、外部服务、资源回收和失败终态均为源码核对与接入约束，证据等级最多为 L0，不能写成 L2/L3/L4 通过。后续若接入平台，唯一可吸收的是阶段结果语义和 provider 边界；模型、GPU、临时文件、外部服务、错误和生命周期必须由受管运行核心统一拥有。
