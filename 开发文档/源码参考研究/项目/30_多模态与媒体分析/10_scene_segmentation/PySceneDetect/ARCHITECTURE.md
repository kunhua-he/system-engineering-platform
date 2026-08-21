# PySceneDetect 架构建档（唯一权威文档）

> 本文件是项目根唯一长期架构文档。旧细探 `细探-PySceneDetect.md` 已完整读取并吸收，当前核对**保留旧文件，不删除、不再把它当第二事实源**；后续架构事实只维护本文件。
>
> 说明、风险、裁决和验证结论使用中文；源码路径、类名、函数名、字段名、命令和第三方名称保留原文。

## 1. 项目身份、版本与证据边界

- 项目根：`~/Documents/Agent/github 源码参考/30_多模态与媒体分析/10_scene_segmentation/PySceneDetect`
- 上游：`https://github.com/Breakthrough/PySceneDetect.git`
- 许可证：`BSD-3-Clause`，证据为 `LICENSE`、`THIRD-PARTY.md`、`README.md:130-132`。
- 本地基线：`bba97f59ff082875cf1c41b8ce2cb52a34ed2020`，提交时间 `2026-07-22 22:34:54 -0400`；当前 `main` 与 `origin/main` 同名但本地工作树存在两个未跟踪文档：本文件与 `细探-PySceneDetect.md`。
- 版本：`scenedetect.__version__ = "0.7.1"`（`scenedetect/__init__.py:80-82`），`docs/LATEST_VERSION` 同步为 `0.7.1`。
- 远程新鲜度：既有静态建档记录的独立快照显示远程 `main` 已到 `131c5f60c9d40dd8fd281941d9b10a6a44fed4cc`（2026-08-18），本工作树未执行 pull/fetch/覆盖；不能把远程快照的变更当成本地实现。
- 代码图：目标项目没有 `.codegraph/`，目标路径上的 `codegraph_explore` 返回 `no relevant code found`；不能使用平台代码图结果冒充本仓库源码证据。以下结论来自当前工作树源码、测试、配置和文档的逐文件读取。
- 本文只描述当前本地基线，不把 README、旧细探、远程快照、历史测试或日志当作“已运行”证据。

## 2. 项目定位与边界

PySceneDetect 是 Python 视频剪切检测与分析库及 CLI。它不训练模型、不持久化业务数据库，也没有 LLM 提示词链；主链路是：打开视频或图像序列 → 统一帧/PTS 时间轴 → 对连续帧运行一个或多个可插拔 `SceneDetector` → 收集切点 → 生成连续 `SceneList` → 导出 CSV/HTML/图片/编辑交换格式，或调用 `ffmpeg`/`mkvmerge` 切分视频。

核心边界：

- **库内负责**：输入后端抽象、帧读取、PTS/帧号转换、检测算法、切点去重与场景组装、统计 CSV、结构化输出。
- **库外负责**：OpenCV/PyAV/MoviePy 解码，`ffmpeg`/`mkvmerge` 编码或容器切分，外部 ONNX 模型运行时和模型文件。
- **不提供**：任务队列、服务端 API、权限系统、数据库事务、断点恢复、输出制品的原子提交或跨进程作业状态。
- **准确性边界**：CFR 可依赖帧号；VFR、拼接 seam、PyAV 真实 PTS 应优先使用 `FrameTimecode.pts/time_base/seconds/position`，不能把平均帧率计算出的 `frame_num` 当作精确时间。

## 3. 总体流程图

```text
单路径 / 路径列表 / 文件对象 / cv2.VideoCapture / URL / 设备
                              │
                              ▼
                 scenedetect.open_video(...)
                              │
            ┌─────────────────┼──────────────────┐
            ▼                 ▼                  ▼
      VideoStreamCv2     VideoStreamAv     VideoStreamMoviePy
      /CaptureAdapter                         (可选后端)
            └─────────────────┬──────────────────┘
                              ▼
                    VideoStream 统一契约
                read / seek / reset / position / PTS
                              │
                 路径列表 → VideoStreamConcat
                              │
                              ▼
                      SceneManager.detect_scenes
                 ┌────────────┼────────────┐
                 ▼            ▼            ▼
          解码线程+有界队列  主线程编排   StatsManager(可选)
                              │
               对每帧顺序调用 SceneDetector.process_frame
          ┌──────────────┬───────────────┬───────────────┐
          ▼              ▼               ▼               ▼
       Content/       Threshold       Histogram/       Hash/TransNetV2
       Adaptive       fade/亮度        YUV histogram    (额外入口)
          └──────────────┴───────────────┴───────────────┘
                              ▼
                     CutList（去重后的切点）
                              ▼
               get_scenes_from_cuts / get_scene_list
                              ▼
                SceneList（连续 [start, end) 时间区间）
          ┌─────────┬─────────┬─────────┬──────────────────┐
          ▼         ▼         ▼         ▼                  ▼
        CSV       HTML      图片     EDL/FCP/OTIO/QP    ffmpeg/mkvmerge
```

CLI 控制流：

```text
python -m scenedetect / scenedetect
       │ Click chain=True：全局选项、配置、输入、detector、commands
       ▼
    CliContext.handle_options / add_detector / add_command
       ▼
    run_scenedetect(context)
       ├─ _detect：seek → SceneManager.detect_scenes
       ├─ _load_scenes：从 CSV 读 scene start，跳过 detector
       ├─ _postprocess_scene_list：merge-last / drop-short
       ├─ _save_stats：写 StatsManager CSV
       └─ 按 context.commands 顺序执行输出 handler
```

证据：`scenedetect/__init__.py:88-213`、`scenedetect/scene_manager.py:446-616`、`scenedetect/_cli/controller.py:30-78,81-102,105-160,163-223`、`scenedetect/_cli/__init__.py:187-194,1834-1866`。

## 4. 真实分层与目录地图

```text
PySceneDetect/
├── scenedetect/
│   ├── __init__.py              扁平公共 API、open_video、detect、版本
│   ├── __main__.py              python -m scenedetect 入口
│   ├── common.py                FrameTimecode、Timecode、SceneList/CutList、类型
│   ├── detector.py              SceneDetector 协议、FlashFilter
│   ├── scene_manager.py         解码线程、帧队列、检测编排、场景组装
│   ├── stats_manager.py         帧指标内存缓存与 CSV 读写
│   ├── video_stream.py          VideoStream 抽象与输入异常
│   ├── backends/                OpenCV、PyAV、MoviePy、Concat、已有 Capture 适配
│   ├── detectors/               Content、Adaptive、Threshold、Histogram、Hash、TransNetV2
│   ├── output/                  CSV/HTML/图片/视频/EDL/FCP/OTIO/QP
│   ├── _cli/                    Click 命令组、配置、上下文、控制器、handler
│   ├── _fan_out.py              单源多消费者读取适配
│   ├── _thirdparty/             内置 simpletable 和许可证
│   └── platform.py              日志、路径、命令探测/执行、进度条
├── tests/                       默认 pytest 行为/API/后端/输出/CLI 测试
│   ├── conftest.py              资源 fixture、ERROR 日志门禁、线程/对象清理
│   ├── helpers.py               测试清理辅助
│   └── release/                 release marker 测试，默认排除
├── benchmark/                   检测器评估、扫描、报告
├── docs/                        Sphinx 文档和 API/CLI 页面
├── website/                     MkDocs 网站
├── packaging/                   发布变体、Windows 打包、构建脚本
├── scripts/                     发布/资源/Windows 脚本
├── .github/workflows/           CI、发布、文档、Docker 工作流
├── pyproject.toml               构建、依赖、pytest、Ruff、Pyright
├── scenedetect.cfg              CLI 默认配置
├── README.md                    quickstart 和能力声明
├── LICENSE / THIRD-PARTY.md     许可证
├── ARCHITECTURE.md              本唯一权威架构文档
└── 细探-PySceneDetect.md        已吸收但保留的历史细探，不是第二权威源
```

## 5. 核心数据与时间契约

### 5.1 时间和值模型

- `Timecode` 保存 `pts` 与 `time_base`；`FrameTimecode` 在帧号、秒、字符串时间码、`Timecode` 之间转换，并提供 `frame_num`、`frame_rate`、`pts`、`time_base`、`seconds`、比较、算术、哈希。证据：`scenedetect/common.py`，公共导出：`scenedetect/__init__.py:34-43`。
- `CutList = list[FrameTimecode]`：每个元素是“新场景起始帧”的切点。
- `SceneList = list[tuple[FrameTimecode, FrameTimecode]]`：由 `get_scenes_from_cuts()` 从起点、切点和终点生成连续区间；内部语义为 `[start, end)`，`get_scene_list()` 以 `last_pos + 1` 作为末端，证据：`scene_manager.py:171-210,376-401`。
- CLI 读写时对帧号使用 1-based 展示；Python API 的帧索引是 0-based，`_load_scenes()` 读 CSV 时会减一，证据：`_cli/controller.py:194-205`。
- `FrameRate = float | Fraction`；`framerate_to_fraction()` 规范化常见 `N*1000/1001`；精确 VFR 时间仍取 `pts/time_base`。

### 5.2 输入流契约

`VideoStream` 必须提供：`path`、`name`、`is_seekable`、`frame_rate`、`duration`、`frame_size`、`aspect_ratio`、`position`、`position_ms`、`frame_number`、`read(decode=True)`、`reset()`、`seek()`，证据：`scenedetect/video_stream.py:79-223`。

- `read(True)` 返回 BGR `numpy.ndarray`；流尾返回 `False`。
- `read(False)` 只推进并返回布尔值，供 `frame_skip` 减少图像复制/转换。
- `position` 是“最后已读帧”的展示/PTS 位置；第一帧可为时间 0，但 `frame_number` 直到读帧前为 0。
- `duration` 对文件通常存在，对设备/非终止流可为 `None`。
- `seek()` 对设备或管道可能不可用；失败抛 `SeekError`，负值抛 `ValueError`。
- 输入打开失败使用 `VideoOpenFailure`；帧率无法推断使用 `FrameRateUnavailable`。

## 6. 契约表（公开入口、责任与失败语义）

| 入口/能力 | 输入与输出 | 前置/版本边界 | 失败、可重试、释放责任 | 证据 |
|---|---|---|---|---|
| `scenedetect.open_video` | 路径/路径列表；返回 `VideoStream` 或 `VideoStreamConcat` | `backend` 默认 `opencv`；`frame_rate` 优先于兼容别名 `framerate` | backend 不可用或抛 `VideoOpenFailure` 时尝试 OpenCV；`OSError`（例如路径不存在）不被该层捕获，不能假定会 fallback；最终抛指定 backend 的首个 `VideoOpenFailure`；调用方持有并关闭 backend | `scenedetect/__init__.py:88-151` |
| `scenedetect.detect` | `video_path + SceneDetector`；返回 `SceneList`，可写 stats CSV | `start_time/end_time` 可为帧、秒、时间码；库 API 不替调用方关闭 stream | 打开、seek、非法时间、stats 损坏抛异常；无内置 retry；调用方负责 stream 生命周期 | `__init__.py:154-213` |
| `SceneManager.add_detector` | 注册 `SceneDetector`；无返回值 | detector 必须实现 `process_frame`; 注入共享 `StatsManager` | detector 被 manager 持有；注册指标；`event_buffer_length` 决定帧缓存；重复注册不去重 | `scene_manager.py:337-353` |
| `SceneManager.detect_scenes` | `VideoStream`、duration/end_time、skip、callback；返回处理帧数 | `duration` 与 `end_time` 互斥；有 StatsManager 时 `frame_skip` 必须为 0 | detector/callback/解码线程异常在主线程重抛；`finally` stop + drain + join；无断点恢复 | `scene_manager.py:446-616` |
| `SceneDetector.process_frame` | 顺序 `FrameTimecode + BGR ndarray`；返回 0..N 个切点 | API 明确标注 v1.0 前不稳定；事件可晚于当前帧 | 实现方负责内部状态一致；异常由 SceneManager 上收；不得假设回调一定触发 | `detector.py:37-103` |
| `SceneDetector.post_process` | EOF 最后时间码；返回尾部切点 | 默认空列表；`ThresholdDetector` 用于 `add_final_scene` | 在主线程 join 后调用；异常直接上收；无独立重试 | `detector.py:64-73`、`threshold_detector.py:170-191` |
| `StatsManager` | 帧键→指标字典；可 save/load CSV | 指标目前应为 `int/float`；注册键不强制阻止任意写入 | 文件写失败抛 `OSError`；格式/列/数值错误抛 `StatsFileCorrupt`；写者持有文件句柄 | `stats_manager.py:85-115,120-203,221-296` |
| `save_images` | `SceneList + VideoStream`；返回 `{scene_index: [paths]}` | 先 `video.reset()`；场景为空返回 `{}`；`num_images > 0` | seek/read/编码/写入失败可能部分产物已存在；线程异常经 error queue 上收；无回滚/残留清单 | `output/image.py:352-444`、`108-340` |
| `split_video_ffmpeg` | 输入路径、场景、模板；返回最后一次外部命令退出码 | 空场景返回 0 且不调用 ffmpeg；每场景一个命令 | 非零退出返回非 0；但缺工具或 `CommandTooLong` 被捕获后 `ret_val` 保持 0，属于“日志失败但返回假成功”风险；前面场景可能已成功，失败不删除部分输出 | `output/video.py:255-389` |
| `split_video_mkvmerge` | 输入路径、场景、模板；返回命令退出码 | 空场景返回 0；多场景由一个 mkvmerge 命令构造 | 非零退出返回非 0；但缺工具或 `CommandTooLong` 被捕获后同样可能返回 0；不保证原子输出 | `output/video.py:159-252` |
| CLI `run_scenedetect` | `CliContext`；按命令顺序执行，返回无业务结果 | Click chain；全局选项须在命令前；`load-scenes` 与 detector 互斥 | seek 失败记录 critical 并返回；各 handler 异常向 CLI 层传播；外部输出按 handler 自己负责 | `_cli/controller.py:30-78,105-160` |

### 6.1 幂等、超时、取消和版本

- **幂等键**：源码没有作业 ID、幂等键或输出制品登记；重复调用会重新读取、覆盖同名 CSV/图片，`ffmpeg` 默认带 `-y` 会覆盖目标。不能宣称幂等。
- **超时**：没有统一 timeout 参数或 watchdog。可用 `duration/end_time` 限制处理范围，不等价于墙钟超时。
- **取消**：`SceneManager.stop()` 只设置线程安全 `Event`；输出图片/外部 ffmpeg 路径没有统一取消接口。CLI Ctrl-C 的完整外部子进程行为依赖 `platform.invoke_command`，当前核对未运行验证。
- **版本兼容**：`SceneDetector` 文档声明 v1.0 前可能改变；`frame_timecode`、`scene_detector`、`video_splitter`、`get_cut_list()`、`framerate` 等兼容入口正在退场。当前本地是 0.7.1，不应以未来远程 API 替换当前契约。

## 7. 关键节点明细与真实对接链

### 7.1 高层 Python API：`detect`

| 顺序 | 真实节点 | 输入/状态 | 输出/副作用 | 失败分支 |
|---|---|---|---|---|
| 1 | `scenedetect.detect` | 路径、backend、可选时间范围 | 调 `open_video` 创建 backend | `VideoOpenFailure`；依赖导入失败在包导入阶段发生 |
| 2 | `video.seek(FrameTimecode(...))` | `start_time` | 修改流读指针 | 不可 seek 或 target 非法抛 `SeekError/ValueError` |
| 3 | `SceneManager(StatsManager() if stats_file_path else None)` | 是否需要指标 | 创建编排器/可选内存 stats | 无数据库/无持久事务 |
| 4 | `add_detector(detector)` | detector 对象 | 注入 stats、注册 metric、扩大 frame buffer | detector 契约不符在调用阶段失败 |
| 5 | `detect_scenes(video, end_time)` | 视频、检测器、范围 | 后台解码、主线程逐帧处理、切点写入内存 | detector/callback/解码异常在 join 后重抛 |
| 6 | `stats_manager.save_to_csv` | 内存指标 | 覆盖/创建 CSV | OSError；只写已落内存的指标 |
| 7 | `get_scene_list` | cutting list、起止位置 | 排序去重后返回连续 `SceneList` | 尚未读取帧或无切点且 `start_in_scene=False` 返回空 |

证据：`scenedetect/__init__.py:198-213`、`scene_manager.py:391-435,446-616`。

### 7.2 CLI：解析 → 控制器 → handler

1. `scenedetect._cli.scenedetect` 是 `click.group(chain=True, invoke_without_command=True)`；注册全局选项，调用 `CliContext.handle_options`。
2. detector command 只把配置解析为 detector 类及参数，交给 `ctx.add_detector`；当前注册名为 `detect-adaptive`、`detect-content`、`detect-hash`、`detect-hist`、`detect-threshold`。
3. `time` 设置 `start_time/duration/end_time`，代码拒绝 duration 与 end 同时存在并检查 start/end 顺序。
4. `run_scenedetect` 若为 `load-scenes` 走 `_load_scenes`，否则 `_detect` 走 `seek → detect_scenes → get_cut_list/get_scene_list`；随后执行 `_postprocess_scene_list`、`_save_stats` 与 `context.commands`。
5. 输出 command handler 再调用 `write_scene_list`、`save_images`、`split_video_*` 或编辑交换格式写入函数；命令顺序保存在 `CliContext.commands`，不是隐式按文件名排序。

### 7.3 逐帧检测：解码线程 → 有界队列 → detector

- `_decode_thread` 调 `video.read()`，检查首帧/连续帧尺寸，按 crop 和 downscale 处理，使用容量 `MAX_FRAME_QUEUE_LENGTH=4` 的队列发送 `(frame, position)`。
- 主线程从队列取帧，用 `_process_frame` 将当前帧放入 `frame_buffer`，依次调用全部 detector，把返回切点追加到同一 `_cutting_list`。
- `event_buffer_length` 是 detector 声明“事件最多落后当前帧多少帧”的缓冲预算；`AdaptiveDetector` 返回 `window_width`，`ContentDetector` 取 `FlashFilter.max_behind`。
- detector 之间没有优先级、短路或事务；同一帧可以由多个 detector 返回切点，最终 `get_scene_list` 用集合去重并排序。
- callback 只对命中的 cut 查找缓冲帧后调用；callback 异常会进入 `finally`，停止并 join decode thread，然后重新抛给调用方。

证据：`scene_manager.py:410-435,565-616,618-703`、`detector.py:75-103`、`content_detector.py:192-243`、`adaptive_detector.py:93-143`。

### 7.4 检测器实现契约

- `ContentDetector`：相邻帧 BGR→HSV，比较 hue/saturation/luma，按权重计算 `content_val`；可选 Canny+dilate edges；达到 threshold 后交给 `FlashFilter`，并将 `content_val`、四个 delta 写入 `StatsManager`。证据：`content_detector.py:49-89,147-211`。
- `AdaptiveDetector`：继承 ContentDetector，先复用 frame score，再保留 `1+2*window_width` 帧窗口，以中心帧与窗口平均分计算 `adaptive_ratio`，同时要求 ratio 和 `min_content_val`，输出中心时间码，因此事件有滞后。证据：`adaptive_detector.py:29-35,93-143`。
- `ThresholdDetector`：计算平均像素强度，记录 `average_rgb`；按 `FLOOR/CEILING` 跟踪 fade in/out，仅在下一次 fade-in 时生成切点，可选 `post_process` 在尾部 fade-out 添加最终切点。证据：`threshold_detector.py:31-55,97-191`。
- `HistogramDetector`、`HashDetector`：分别以 YUV histogram 差异和感知 hash 距离检测快速 cut，指标名与 CLI 以各自源码为准。
- `TransNetV2Detector`：额外文件 `detectors/transnet_v2.py`，使用 `onnxruntime` 与 100 帧窗口/模型资产；当前不是 `detectors/__init__.py` 的核心重导出，不能把它写成默认轻量链路或已验证能力。

## 8. 后端与输入资源生命周期

| 资源 | 创建/持有 | 正常释放 | 失败/取消/崩溃路径 | 当前证据与风险 |
|---|---|---|---|---|
| OpenCV `cv2.VideoCapture` | `VideoStreamCv2._open_capture` 创建并由对象持有；`VideoCaptureAdapter` 借用调用方已有 capture | `reset()` release 后重开；本地源码未见统一 `close()` 公共协议，调用方/GC 负责 | SceneManager 只保证 decode thread join，不等于 capture release；设备不可 seek；崩溃由 OS 回收但 Python 进程可能延迟释放 | `backends/opencv.py:70-137,241-306,312-363,365-538` |
| PyAV `InputContainer`/文件句柄/decoder generator | `VideoStreamAv.__init__` 打开 `_io` 与 `av.open`；`read` 长持有 generator；可 seek/reset 重开 | `__del__` 先 close generator 再 close container；`reset()` close/reopen | 构造中途异常有部分初始化；`__del__` 吞异常；解释器退出期间原生句柄风险 | `backends/pyav.py:87-171,267-357` |
| MoviePy/第三方 decoder | 可选 backend 创建 | 依实现和 GC；当前核对未完整读取该文件，不能承诺显式 close | CLI 对 MoviePy EOF warning 做过滤；实际清理未在当前核对运行 | `backends/__init__.py:100-127`、controller.py:43-47 |
| Concat 子流 | 构造阶段预探测全部输入，但只保持当前 `_cap` 解码；seam 切换重开下一 child | EOF 时 `_finish_current_source` 后打开下一源；reset 重开第一个 | 中途源打开失败、分辨率不一致抛 `VideoOpenFailure`；declared duration 不准时 offset 动态修正；非原子 | `backends/concat.py:137-172,178-239,241-265` |
| 解码线程/队列 | `SceneManager.detect_scenes` 创建 daemon thread 和有界 Queue(4) | `finally` 设置 stop、清空队列、循环 join；decode thread finally 放入 `(None,None)` | detector/callback 异常、decode exception 也进入收口；队列 put/异常边界仍需真实媒体验证；无强制墙钟 timeout | `scene_manager.py:565-616,618-703` |
| detector 内存状态/帧 buffer | `add_detector` 注入 stats；每帧在 `_process_frame` 和 detector 内部缓存 | `clear` 清 cuts/位置并清 detector list；StatsManager 可继续持有指标 | 重复检测不自动 reset detector；重用同一 manager 前应显式 `clear`/重新构造；异常后对象状态不承诺可继续 | `scene_manager.py:358-375` |
| StatsManager 指标字典 | 每个 frame key → metric dict，保存于进程内 | `save_to_csv` 写文件；无 close 资源 | 磁盘失败无事务/临时文件回滚；损坏 CSV 抛异常；部分内存可能已变更 | `stats_manager.py:106-115,164-203,267-296` |
| 图片 encode/save worker | `_ImageExtractor.run` 建 encode/save 两个 daemon worker、有界队列和 error queue | sentinel `(None,None)`，join 两线程；异常回主线程 | 编码 false 可能跳过图像；磁盘失败可能已有部分文件；没有取消 token 或残留文件回收 | `output/image.py:213-296,298-340` |
| 外部 ffmpeg/mkvmerge 进程 | `invoke_command` 从 output.video 调用；每场景 ffmpeg 或单次 mkvmerge | 依赖 subprocess 返回；源码调用使用 ffmpeg `-nostdin` | 缺工具/命令过长/非零码只返回或记日志；中途失败无 rollback；SIGKILL/崩溃清理未证实 | `output/video.py:215-252,326-389` |
| 输出文件/目录 | `get_and_create_path`/`Path.mkdir` 创建父目录和目标 | 成功后留在用户指定目录 | 同名覆盖；半写文件可能残留；无 manifest、校验和或原子 rename | `output/image.py:268-296`、`output/video.py:332-362` |

## 9. 失败、超时、取消、断线与崩溃矩阵

| 场景 | 当前源码行为 | 结论/未验证边界 |
|---|---|---|
| 路径不存在/权限不足 | OpenCV 明确 `OSError`；PyAV 由 open 抛 OSError 或包成 `VideoOpenFailure` | 可区分打开失败；未做统一错误码/重试 |
| backend 不可用 | `AVAILABLE_BACKENDS` 只收集成功导入的 OpenCV/PyAV/MoviePy；`open_video` 警告并回退 OpenCV | “回退成功”不能证明指定 backend 可用或结果等价 |
| 指定 backend 打开失败 | 非 OpenCV backend 仅在收到 `VideoOpenFailure` 后尝试 OpenCV；`OSError` 不在 fallback 捕获范围内；最终优先抛指定 backend 的首个 `VideoOpenFailure` | 回退可能改变 PTS/准确性；需记录实际 backend，当前无结构化诊断；路径不存在等 `OSError` 会直接终止 |
| 帧率缺失/无效 | `< MAX_FPS_DELTA` 抛 `FrameRateUnavailable`，显式无效值抛 `ValueError` | 可手工提供 fps；VFR 仍需 PTS 证据 |
| 单帧解码失败 | OpenCV 最多继续 `max_decode_attempts`；PyAV 跳过 FFmpegError，连续 8 次后停止；累计 `decode_failures` | 继续处理会降低准确率；当前 CLI 没把失败计数写到结果契约 |
| 帧尺寸变化/损坏 | SceneManager 跳过错误尺寸帧，错误日志达到 16 条后抑制后续日志 | 可能“有输出但少帧”，不能以退出 0 视为准确 |
| 空/短输入 | 未解码帧时 scene list 为空；无 cut 时默认 `get_scene_list()` 为空，`start_in_scene=True` 才返回整个范围 | 空结果是正常语义，不等于失败；CLI 使用 `start_in_scene=True` |
| `duration` 与 `end_time` 同时给出 | 直接 `ValueError` | 合约清晰、无副作用回滚要求 |
| `StatsManager` 与 `frame_skip` 同时使用 | 直接 `ValueError` | 防止统计帧稀疏与缓存语义冲突 |
| seek 失败/不可 seek | CLI `_detect` 捕获 `SeekError`，记录 critical 并返回 None；Python API 直接抛 | CLI 可能以“无结果”路径结束，需查看日志；无统一退出码证据 |
| detector 抛异常 | `finally` stop、清队列、join；之后若 decode thread 有异常再重抛 | 有线程收口设计；未验证原生库异常和 callback 竞争 |
| 主动停止 | `SceneManager.stop()` 设置 Event；主循环退出，finally 收口 | 不是墙钟 timeout；如果 decode thread 阻塞在外部 read，退出延迟未测 |
| Ctrl-C/宿主崩溃 | decode thread 捕获 KeyboardInterrupt；宿主 kill 由 OS 回收 | 外部子进程、临时文件、Python 原生句柄在强杀后无清单/恢复协议 |
| 图片写入部分失败 | worker error queue 回传第一个异常；已写文件不回滚 | 业务失败和资源清理不等价；需调用方扫描输出目录 |
| ffmpeg/mkvmerge 返回非 0 | ffmpeg 停止后续场景并返回非 0；mkvmerge 返回命令码；前面产物保留 | 退出码可检查，但没有完整输出 manifest/原子提交；缺工具/命令过长异常被吞后可能仍返回 0，调用方不能只看返回码 |
| 进程重启恢复 | 无 job、checkpoint、stats lock 或 manifest 恢复机制 | 明确不支持，不能包装成可恢复服务 |

## 10. 检测与输出的资源/数据流细节

### 10.1 StatsManager 两遍用途

`ContentDetector` 首次计算时把 `content_val`、`delta_hue`、`delta_sat`、`delta_lum`、`delta_edges` 写入内存；`AdaptiveDetector` 追加带窗口宽度的 `adaptive_ratio`；`ThresholdDetector` 写 `average_rgb`。`save_to_csv()` 按指标名排序，写 `Frame Number`、`Timecode` 和指标列。`load_from_csv()` 是 deprecated，遇到空文件、缺指标、列数不匹配、非数字抛 `StatsFileCorrupt`。

重要边界：当前 StatsManager 是进程内字典，不是缓存服务；CSV 覆盖写且无 schema/version/checksum；加载旧 CSV 后无法完整恢复无 base framerate 的裸整数帧键。证据：`stats_manager.py:106-115,164-203,221-296`。

### 10.2 图片输出

`save_images` 先 reset video，再按每个场景用 PTS 秒数生成采样时间码；每个采样点 seek/read，进入 bounded encode queue → `cv2.imencode` → bounded save queue → `encoded.tofile`。默认 3 张/scene，可输出 jpg/png/webp，可按 width/height/scale 重采样。返回字典记录“计划/生成的文件名”，不提供内容哈希，不提供全量成功证明；`completed=False` 只记 error 日志并仍返回部分字典。

### 10.3 视频切分与交换格式

- `write_scene_list` 写 CSV，默认可先写 cut list；`write_scene_list_html` 将 scene rows 和可选图片嵌入 HTML。
- `write_scene_list_edl`、`write_scene_list_fcp7`、`write_scene_list_fcpx`、`write_scene_list_otio`、`write_scene_list_qp` 通过 `FrameTimecode`/PTS 转换外部编辑格式；可选依赖或 schema 需以对应实现/测试为准。
- `split_video_ffmpeg` 每个 scene 组装一条 `ffmpeg -nostdin -y -ss ... -i ... -t ...` 命令，默认 re-encode；第一条失败后 break，返回非零码。`arg_override.split(" ")` 不是 shell 解析器，含空格/引号的自定义参数会被拆错；缺工具或 `CommandTooLong` 在函数内只记日志，默认 `ret_val=0`。
- `split_video_mkvmerge` 将所有 scene parts 组合到一次命令；单场景强制补 `-001`，模板只替换 `$VIDEO_NAME`，`mkvmerge` 自己追加场景编号；命令过长/缺工具异常同样可能保留 0 返回码。两者都不提供事务、回滚、产物校验或 resume。

## 11. 技术栈与依赖边界

`pyproject.toml` 当前声明：Python `>=3.10`、构建 `setuptools>=77`、核心仅声明 `numpy`；OpenCV 是运行时必需但故意不放进根依赖以兼容 `opencv-python`/`opencv-python-headless`。可选 `opencv`、`opencv-headless`、`av>=9.2`、`moviepy`；`dev` 包含 Click（排除 `8.3.0`）、OpenCV、PyAV、MoviePy、pytest、tqdm 等；docs/website 依赖 Sphinx/MkDocs。

外部边界：

- `cv2`：导入 `scenedetect` 时即检查，缺失在 `__init__.py:20-29` 直接给出安装提示。
- PyAV：导入失败时 backend 值为 `None`，不进入 `AVAILABLE_BACKENDS`。
- MoviePy：同上，且 CLI 只对其 warning 做过滤。
- `ffmpeg`/`mkvmerge`：由 PATH/平台探测；`output/video.py:62-92` 中 ffmpeg 路径在模块导入时探测，存在导入触发外部命令探测的副作用。
- `onnxruntime` 与 TransNetV2 ONNX：额外可选边界，不在核心依赖中。

## 12. 测试结构与防假绿 L0-L4

### 12.1 已发现的测试结构

现场静态统计：`tests/test_*.py` 15 个文件、201 个 `test_*` 函数；`tests/release/test_*.py` 7 个文件、22 个测试函数。`pyproject.toml:93-100` 设置默认 `addopts = "-m 'not release'"`，release marker 默认不跑。

`tests/conftest.py:12-24,104-161` 明确依赖远程 `resources` 分支的 `tests/resources/`；当前工作树不存在 `tests/resources`。它还提供：

- `no_logs_gte_error`：把测试期间 ERROR 级日志视为失败（`conftest.py:91-101`）；
- `auto_close`：测试结束关闭注册的 stream（`conftest.py:164-184`）；
- `pytest_unconfigure`：收集 GC 并报告残留非主线程（`conftest.py:186-211`）。

### 12.2 真假验证等级

| 等级 | 可以证明什么 | 当前核对状态 | 不能冒充什么 |
|---|---|---|---|
| L0 声明 | README/旧细探/文档宣称有某能力 | 已读取 README、旧细探、API/CLI 文档 | 不能证明源码路径、运行成功或版本一致 |
| L1 静态实现 | 源码有入口、调用链、异常/资源处理；测试文件存在 | **已达到**：读取当前关键源码、配置、测试与工作树 | 不能证明依赖可导入、媒体可解码、外部工具可用 |
| L2 无外部资源验证 | 可运行的纯内存/合同/时间码/算法单元测试 | **未正式执行本项目 pytest**；缺 `tests/resources`，不能用 skip 当通过 | 不能证明真实视频、VFR、坏帧、线程、编码输出 |
| L3 真实链路 | 真实视频 + 指定 backend + detector + 输出，记录退出码/产物 | **未验证**：无资源、无当前核对安装/工具探测 | 不能证明发布矩阵、强杀清理、跨平台行为 |
| L4 发布/灾难闭环 | release/golden、backend 矩阵、外部工具失败、取消/崩溃后无残留、结果内容校验 | **未验证**：release 测试默认排除且资源缺失 | 不能宣称“生产可用”“无泄漏”“可恢复” |

规则：`pytest` 收集通过、打印“完成”、历史二进制、子代理回信、缓存复用、`skip` 都不是 L3/L4 证据；必须记录命令、退出码、测试数/跳过数、输入资源、backend、外部程序、输出产物与清理结果。

## 13. 当前核对验证记录

当前核对真实执行过的静态盘点命令及结果：

| 命令 | 退出码 | 结果 |
|---|---:|---|
| `git status --short --branch && git rev-parse HEAD && git log -1 --format=... && git remote -v` | 0 | 本地基线为 `bba97f5...`；仅两个未跟踪文档 |
| Python 静态统计 `tests/test_*.py` / `tests/release/test_*.py` / resources / 文档存在性 | 0 | 15/201、7/22；`tests/resources` 不存在；旧细探存在 |
| 目标项目 `codegraph_explore` | 0 | 返回未建立 `.codegraph`、无法查询；未将平台图冒充目标图 |
| `system_engineering_toolkit.project_context` | 成功 | 正确识别的平台 MCP 实例为 `system_engineering_toolkit`，开工 id `546fa0f49d6c4a65`；其代码图是系统工程平台而非本项目，可信度 50、匹配成功记录 0 |
| `system_engineering_toolkit.codegraph_explore` | 0 | 查询范围为平台代码图，`No relevant code found`；不是 PySceneDetect 证据 |

当前核对没有安装依赖、下载视频/模型资源、启动服务、运行 CLI、运行 pytest、调用 ffmpeg/mkvmerge、生成测试输出，也没有修改源码/配置/测试/依赖/Git。验证登记必须以后续 `mcp_feedback` 通过后再调用 `system_engineering_toolkit.verify_and_record`；若验证命令退出码非 0，不得宣称成功。

## 14. 失败/取消/崩溃验收清单（后续 L3/L4）

- [ ] 缺 OpenCV、缺 PyAV、缺 MoviePy 时分别确认导入错误和 fallback 日志。
- [ ] 不存在文件、无帧文件、帧率缺失、非法 crop、负 duration、duration/end 冲突。
- [ ] CFR、VFR、非零 stream start time、图像序列和多文件 seam 的 PTS 与 frame number 对照。
- [ ] 单个坏帧、连续坏帧超过 OpenCV/PyAV 上限，确认 `decode_failures`、退出状态和是否漏帧。
- [ ] detector、callback、decode thread 分别抛异常，确认 decode thread 已结束、capture/container 无残留。
- [ ] `stop()` 主动取消、有限 duration、非终止设备流；测量阻塞 read 的退出边界。
- [ ] save-images 编码失败、磁盘写失败、worker 异常，确认主线程收到异常且部分文件有清单。
- [ ] ffmpeg/mkvmerge 缺失、命令过长、场景中途失败、外部进程强杀，确认退出码、子进程和部分产物。
- [ ] 重复调用/同名输出覆盖行为；明确调用方是否需要独立输出目录和 manifest。
- [ ] 进程 SIGTERM/SIGKILL 后扫描线程、句柄、子进程、临时文件、半写输出；当前源码没有恢复协议，验收只能确认残留风险。

## 15. 兼容性与剩余风险

1. **版本漂移**：本地 0.7.1 落后远程快照；远程 API/PTS/CLI 变化不能混入当前文档或实现。
2. **代码图缺失**：目标项目无 `.codegraph`，本次调用平台图只用于记录错绑/无相关结果，不是源码定位证据；后续若建立代码图，需重新核对摘要和指纹。
3. **依赖声明不对称**：根包只声明 numpy，但导入强依赖 cv2；使用者须显式选择 OpenCV 变体。
4. **PTS 与 frame number 双语义**：VFR、Concat、OpenCV seek 会使平均帧率帧号近似；输出格式中同时使用两者时需要按场景选择。
5. **资源释放不统一**：`VideoStream` 没有统一公共 `close()`；PyAV依赖析构器，OpenCV capture 释放责任容易落到调用方/GC。
6. **输出非事务**：CSV、图片、视频输出可能部分成功/覆盖旧文件，不提供 manifest、hash、rename、回滚或恢复。
7. **并发收口待实测**：SceneManager 和 image workers 有 join/error queue 设计，但真实 decoder/native exception、阻塞 read、强杀路径尚未 L3/L4 验证。
8. **Stats CSV 非稳定存储协议**：无 schema version、校验和、锁；`load_from_csv` 已 deprecated，不能作为长期缓存服务。
9. **TransNetV2 边界不清**：需单独确认当前 CLI 是否有用户入口、模型资产、onnxruntime 版本与测试资源，不能从文件存在推断可用。
10. **测试资源缺失**：真实视频、VFR、损坏帧、golden 和模型都不在当前树；任何“测试通过”都必须补充资源来源和实际执行输出。

## 16. 旧细探逐条吸收与裁决

| 旧细探内容 | 吸收位置 | 裁决 |
|---|---|---|
| 项目定位、纯视觉算法、无 LLM 提示词 | §2 | 吸收；补充库/外部工具边界 |
| `SceneManager`、detector、stats、video manager 概览 | §3、§5、§7 | 吸收并改为当前真实类名：`VideoStream`，不把不存在的 `VideoManager` 当当前入口 |
| Content/Threshold 检测器 | §7.4 | 吸收；补充 HSV、FlashFilter、fade 状态和 post-process |
| “Detector 可插拔” | §6、§7 | 吸收；补充注入、指标、事件缓冲、重复 cut 去重语义 |
| 场景切点到切分/时间轴 | §3、§7.1、§10 | 吸收；补充 SceneList `[start,end)`、输出非事务风险 |
| OpenCV/numpy 依赖 | §11 | 修正为根声明 numpy、运行导入强依赖 cv2，并分出 PyAV/MoviePy/外部工具 |
| “轻量、CPU 友好” | §2、§7.4、§11 | 部分吸收；只描述实现，不把性能宣传当测量结果 |
| 可借鉴：多 provider、时间轴、标准库适配 | §17 | 仅作为架构映射候选，不当成本项目已实现的平台集成 |
| 许可证“通常 BSD-3-Clause” | §1 | 修正为源码许可证证据明确的 BSD-3-Clause |

## 17. 对平台底座的吸收/不吸收裁决

### 吸收（有源码证据，但仍需平台化验收）

- `VideoStream` 的输入能力契约：统一 `read/seek/reset/position/PTS`，适合作为视频输入 provider 的参考边界。
- `SceneDetector` 的逐帧处理扩展点与 `event_buffer_length`：适合作为“检测算法 provider”与延迟事件缓存的设计参考。
- `FrameTimecode` 的 CFR/VFR 双表示与 `VideoStreamConcat` 的全局 PTS + `SourceSpan` 映射：适合作为场景时间轴数据模型参考。
- detector → `StatsManager` 指标 → CSV 的可解释中间结果：适合作为调参/审计产物参考，但不能直接当长期持久化协议。
- 输出格式适配层：CSV/EDL/FCP/OTIO/QP 应视为边界适配器，而非核心场景检测流程。

### 不吸收/隔离

- 不把 OpenCV/PyAV/MoviePy/onnxruntime 直接嵌入平台主进程；应由独立 provider/进程和明确能力错误承载。
- 不复制当前 CLI 的兼容别名、导入时 ffmpeg 探测、根依赖与运行依赖不一致、无原子输出等风险模式。
- 不把 `StatsManager` 内存字典/CSV 直接当平台任务状态、数据库或可靠缓存。
- 不把 `ffmpeg`/`mkvmerge` 返回码视为制品提交成功；平台若复用需增加 manifest、校验、部分失败状态和清理策略。
- 不宣称 PySceneDetect 自带 LLM、服务 API、队列、重试、幂等、超时或崩溃恢复；这些均未在当前源码实现。

### 待核

- TransNetV2 的正式 CLI 注册、模型分发和 runtime 版本闭环。
- MoviePy backend 的完整关闭/异常语义。
- `platform.invoke_command` 的 subprocess 信号、超时和 stdout/stderr 收集行为。
- FCP/OTIO/QP 依赖缺失与格式校验在当前环境的行为。
- 远程 `main` 对当前 API、VFR、Concat 和输出行为的逐文件差异。

## 18. 后续唯一维护规则

1. 任何新架构事实只写本 `ARCHITECTURE.md`，旧 `细探-PySceneDetect.md` 只保留为历史线索，不再追加平行结论。
2. 远程升级先建立独立快照并记录提交，再逐文件对照本地基线；不在未裁决版本时混写 API。
3. 真实验证必须分别记录 L1/L2/L3/L4，不得以资源缺失时的 skip、缓存或历史证据替代真实媒体执行。
4. 若平台要复用能力，先区分“源码模式可借鉴”与“已满足平台契约”；先建适配契约和资源清理验收，再做实现。
5. 当前核对仅允许修改本文件；`细探-PySceneDetect.md`、源码、配置、测试、依赖和 Git 均不得删除或改动。

## 19. 当前核对收口证据

- 目标项目专属 MCP 实例：`system_engineering_toolkit`（HTTP `127.0.0.1:8766/mcp/`）。
- 正确 `project_context`：项目根被 MCP 绑定为 `~/Documents/Agent/PHP/系统工程平台`，任务开工 id `546fa0f49d6c4a65`；这是系统工程平台控制面的身份，不是 PySceneDetect 根，故已如实标记错绑/跨仓库边界。
- `codegraph_explore`：平台代码图可用但查询 `PySceneDetect architecture scene detection pipeline` 返回 `No relevant code found`；目标 PySceneDetect 无 `.codegraph/`，未冒充代码图证据。
- 允许修改文件：仅 `~/Documents/Agent/github 源码参考/30_多模态与媒体分析/10_scene_segmentation/PySceneDetect/ARCHITECTURE.md`。
- 旧细探：`~/Documents/Agent/github 源码参考/30_多模态与媒体分析/10_scene_segmentation/PySceneDetect/细探-PySceneDetect.md` 已读取且保留。
- 本文修改范围：仅吸收旧细探、当前源码和测试事实，补充契约表、真实调用链、节点表、生命周期、失败矩阵、L0-L4 防假绿、未验证项和吸收/不吸收裁决；未改源码、配置、测试、依赖、Git。

## 20. 后续通用底座映射与单链路裁决

### 20.1 映射前提与边界

本节是基于当前本地 `bba97f59ff082875cf1c41b8ce2cb52a34ed2020` 的后续映射输入，不是对平台生产代码的改造承诺。PySceneDetect 当前只提供项目内的 `VideoStream`、`SceneManager`、`SceneDetector`、`StatsManager`、CLI handler 和输出函数；平台尚未在本项目工作树内登记“媒体.场景检测”能力，也没有目标仓库自己的 `.codegraph/`。因此以下“吸收/升级/待核”均是边界裁决，不能写成“已接入平台”。

平台侧的 `system_engineering_toolkit` 只能作为平台公共契约、运行核心和提供者治理的参考证据；其 `project_context` 绑定的是 `~/Documents/Agent/PHP/系统工程平台`，不是本项目根，代码图查询也没有返回目标仓库符号。本节不把平台代码图结果冒充 PySceneDetect 源码证据；PySceneDetect 的事实仍以本文件前述源码路径为准。

后续唯一目标是把同类责任收敛为一个能力 owner 和一条可审计调用链：

```text
CLI/API 或项目适配层
  → 运行核心统一能力调用器（授权、契约、预算、任务状态）
  → 媒体模块「场景检测」编排（时间范围、采样计划、算法策略、场景组装）
  → 支持库公共媒体契约（PTS/时间码、帧信封、采样计划、场景区间、统一结果）
  → 唯一视频/模型/外部命令提供者（OpenCV、PyAV、MoviePy、onnxruntime、ffmpeg、mkvmerge）
  → 运行核心资源监督与证据收口
  → 统一场景结果、资源摘要和失败证据
```

固定禁令：CLI/API 不得直连 `cv2`、`av`、`moviepy`、`onnxruntime`、`ffmpeg` 或 `mkvmerge`；媒体模块不得各自维护第二套时间码、取消器、任务状态或 provider 注册表；提供者不得反向编排场景业务；`StatsManager` CSV 不得冒充平台任务状态、可靠缓存或制品提交。

### 20.2 能力归属映射表

| 当前能力/责任 | 当前源码事实 | 后续归属与唯一 owner | 中文契约边界 | 不允许的落点 |
|---|---|---|---|---|
| 场景检测 | `SceneManager.detect_scenes` 顺序消费帧并调用一个或多个 `SceneDetector`，再由 `get_scene_list` 组装连续区间（`scene_manager.py:446-616`、`common.py`） | **媒体模块**：唯一编排 `媒体.场景检测`；负责输入范围、采样计划、detector 策略选择、切点去重、`SceneList` 组装和统一结果 | 输入为媒体引用、时间范围、采样策略、算法策略、输出选项；输出为 `[start,end)` 场景区间、切点、指标引用、诊断和证据 id；时间语义优先 PTS | 不为每个 detector、CLI command 或 provider 复制一套场景流程 |
| 视频读取 | `VideoStream` 统一 `read/seek/reset/position/PTS`；实际后端为 OpenCV、PyAV、MoviePy、Concat（`video_stream.py`、`backends/`） | **提供者**：每种解码器一个受管实现；媒体模块只依赖统一 `媒体输入` 契约 | `打开(媒体引用,配置)`、`读取帧(解码/跳过)`、`定位(时间码)`、`重置`、`关闭`、`能力探测`；返回标准帧信封或明确错误码 | CLI/模块直接持有第三方 decoder 对象；多个模块各自 open/read |
| 帧采样 | `save_images` 按场景 PTS 生成采样时间码并 `seek/read`；`SceneManager` 有 `frame_skip`、crop、downscale、容量为 4 的队列（`output/image.py`、`scene_manager.py`） | **支持库 + 媒体模块分工**：支持库拥有 PTS 优先的采样计划/时间码算法；媒体模块拥有按场景执行和结果组装；不得再建视频读取链 | `采样计划(场景区间,数量/间隔,策略) → 时间码序列`；VFR 不得用平均帧率帧号替代 PTS；执行结果逐项标记命中、跳过或失败 | 输出 handler 自己实现时间轴和采样；以文件名数量冒充实际帧成功数 |
| 算法策略 | `ContentDetector`、`AdaptiveDetector`、`ThresholdDetector`、`HistogramDetector`、`HashDetector` 和可选 `TransNetV2Detector` 各自实现 `process_frame`（`detector.py`、`detectors/`） | **提供者**：算法策略 provider 只接受标准帧信封和策略参数，返回切点事件/指标；媒体模块决定何时、以何策略调用 | 输入帧、帧时间码、只读配置和可选状态；输出 0..N 个切点事件、指标、延迟/窗口信息；异常转统一错误，不直接写业务库 | provider 自行读视频、写 CSV、启动另一条检测循环或隐藏 fallback |
| CLI/API | Click chain、`CliContext`、`run_scenedetect` 和 handler 目前把解析、检测、后处理、输出串起来（`_cli/controller.py`、`_cli/__init__.py`） | **运行核心**统一授权、能力调用、预算、任务/取消、错误和证据；CLI/API 只是项目适配门面，调用一个能力 id | 请求必须是版本化 JSON/参数对象；返回统一 `成功/值/错误码/消息/可重试/证据id/资源摘要`；CLI 退出码由统一错误映射产生 | CLI 直接 import provider 或自己解释 timeout、重启、角色、状态 |
| 媒体资源 | capture/container/generator、帧队列、detector buffer、图片 worker、外部 ffmpeg/mkvmerge 和输出文件分别由当前对象/线程/函数持有，缺统一 close/manifest | **提供者创建实际媒体资源；运行核心拥有租约、监督、回收和证据；媒体模块只传递逻辑所有权** | 资源必须声明创建者、持有者、转移者、释放函数、截止时间、残留检查；`关闭` 幂等，释放失败必须可观察 | 用 Python GC、`__del__`、进程退出或“返回码 0”替代释放证明 |
| 取消、超时、崩溃回收 | 当前只有 `SceneManager.stop()` Event；无统一墙钟 timeout、job、checkpoint、外部子进程回收协议（§6.1、§9） | **运行核心**唯一拥有取消 token、单调截止时间、进程组强杀、join/reap、临时根扫描和证据；提供者必须可被监督 | 取消幂等；超时是墙钟截止，不把 `duration/end_time` 混称 timeout；崩溃统一为可重试/不可重试错误，并记录清理结果 | 媒体模块再建 `VideoTimeoutManager`、CLI 自己 kill、provider 无限重试或静默重启 |

归属要点：算法“策略”属于提供者，算法“编排”属于媒体模块；采样“数学与时间码”属于支持库，采样“按场景执行”属于媒体模块；资源“实际句柄”属于提供者，资源“生命周期治理”属于运行核心。这种拆分避免把同一责任同时复制到三层。

### 20.3 中文公共契约

#### 20.3.1 `媒体.场景检测` 聚合能力

- **请求**：`媒体引用`（路径、受控文件句柄引用或输入资源 id，禁止第三方对象）、`后端约束`（可选）、`时间范围`、`采样策略`、`算法策略`、`统计选项`、`输出选项`、`取消令牌`、`截止时间`、`幂等/输出目录约束`。
- **前置条件**：媒体引用已授权且可读；时间范围满足 `duration` 与 `end_time` 互斥；采样计划通过 PTS/帧率一致性检查；算法策略已登记并满足输入格式；资源预算已获运行核心批准。
- **成功返回**：统一结果中的 `值` 含 `场景列表`（`[start,end)`）、`切点`、时间轴基线、实际后端、算法策略、统计引用和输出制品引用；另含 `证据id`、资源摘要和是否完整。
- **失败返回**：至少区分 `MEDIA_NOT_FOUND`、`MEDIA_OPEN_FAILED`、`BACKEND_UNAVAILABLE`、`INVALID_TIME_RANGE`、`FRAME_RATE_UNAVAILABLE`、`DECODE_FAILED`、`DETECTOR_FAILED`、`OUTPUT_PARTIAL`、`CALL_TIMEOUT`、`CALL_CANCELLED`、`PROVIDER_CRASHED`、`RESOURCE_CLEANUP_FAILED`；错误必须有 `可重试` 和清理状态，不能只返回日志文本。
- **副作用**：读取输入、可能创建临时目录/子进程/统计文件/输出制品；所有副作用必须挂到资源摘要和证据 id；成功不代表输出已原子提交，除非 manifest/hash/rename 验收全部通过。

#### 20.3.2 媒体输入 provider 契约

`打开 → 能力探测 → 读取/跳过 → 定位 → 重置 → 关闭` 是唯一生命周期顺序。`读取帧` 返回标准帧信封：`帧序号`、`pts`、`time_base`、`秒`、`宽`、`高`、`像素格式`、`数据引用`、`来源跨度`；EOF 是结构化终态，不把 `False`、空数组和解码失败混为一谈。不可 seek 的设备/管道必须在能力探测中声明，`定位` 返回稳定错误码而不是隐式从头读。

第三方对象（`cv2.VideoCapture`、PyAV `InputContainer`、MoviePy reader、ONNX session）只在 provider 边界内存在；若使用独立进程，跨边界只传 JSON 契约、受控帧/文件引用或受控共享资源 id，禁止把 Python/C 扩展对象穿透到媒体模块或运行核心。

#### 20.3.3 采样与算法策略契约

- 支持库的采样计划输入场景区间和数量/间隔，输出单调、去重、带 PTS 的时间码序列；VFR、Concat seam、非零 stream start time 必须保留 `pts/time_base/source span`，`frame_num` 仅作展示或 CFR 快速路径。
- 算法 provider 每次调用只消费标准帧信封和显式状态；返回切点事件、指标、事件延迟和策略版本。指标是中间证据，不自动成为长期缓存；状态转移必须可清空、可重复构造，不能依赖上一次检测的隐式内存。
- 媒体模块负责把多个策略结果合并、去重、排序和组装 `SceneList`；同一帧多个策略命中不触发第二次读取，也不允许 provider 重新打开视频。

#### 20.3.4 CLI/API 与统一运行契约

CLI 的兼容别名、Click 参数和 API 字段只能在项目适配层归一化一次；归一化后调用运行核心的唯一能力调用器。运行核心负责授权、能力契约、资源预算、超时、取消、错误码、事件和证据；CLI 负责将统一结果映射为人类输出和退出码，API 负责版本化 JSON，不得各自维护 fallback 和重试。

### 20.4 资源生命周期与四种终态

| 资源 | 创建/持有 | 正常完成 | 业务失败 | 主动取消/超时 | 宿主/提供者崩溃 | 必须留下的证据 |
|---|---|---|---|---|---|---|
| 输入路径、文件引用、临时目录 | 运行核心分配资源 id；provider 借用 | 关闭借用句柄；临时目录按保留策略提交或删除 | 关闭并记录部分读取；删除未提交临时物 | 先停止读取，再关闭；截止后由运行核心强制回收 | 以资源租约和进程身份重扫；不能依赖析构 | 资源 id、拥有者、路径摘要、终态、残留扫描 |
| OpenCV/PyAV/MoviePy 解码器 | provider 创建并独占真实对象 | `close/release`，确认 provider 报告已关闭 | finally 关闭；构造中途失败清理已创建部分 | 取消读取；阻塞时由独立进程/线程治理 | killpg/等待/reap；旧句柄不得复用 | 实际后端、退出码/信号、关闭结果、可重试性 |
| 帧缓冲、队列、detector 状态 | 媒体模块/worker 创建；运行核心给预算 | sentinel、排空、join，清空 detector 状态 | error queue 上收后排空并 join | 发取消 sentinel，设置 deadline，超时后强制终止 | 进程结束后重建，不复用半状态 | 队列深度、线程列表、join 结果、状态摘要 |
| 算法模型/ONNX session | 算法 provider 创建；不向上层泄漏对象 | provider 关闭/进程退出 | 释放并记录模型版本 | 取消调用；超时 kill provider 进程 | 崩溃记 `PROVIDER_CRASHED`，下次调用新建 | 模型/策略版本、环境指纹、退出原因 |
| Stats、图片、CSV、视频输出 | 媒体模块申请；输出 provider 写入 | manifest/hash 校验后原子 rename 或明确“非事务输出” | 保留部分产物但写 partial manifest，不伪装完整 | 关闭 worker，标记取消，扫描半写文件 | 以 manifest/临时前缀扫描，禁止自动当成功 | 每个产物路径、字节数/hash、完整性、清理结果 |
| 取消 token、租约、证据 | 运行核心创建；调用链显式转移 | 任务终态后关闭租约并写证据 | 记录失败终态，释放剩余预算 | 取消幂等，记录发起者和时间；回收失败升级 | 由重启扫描死亡拥有者并补写崩溃证据 | 任务 id、token 状态、截止时间、回收动作、残留数 |

四种终态都必须走同一个 `finally → 排空/停止 → join/reap → 关闭 provider → 扫描临时资源 → 写证据` 收口；“宿主被 SIGKILL 后 OS 会回收”只能说明部分内核句柄，不等于输出、临时目录、子进程、队列和平台租约已收口。

### 20.5 L0-L4 验证契约

| 等级 | 当前核对可证明内容 | 必须执行的验证 | 通过门槛 | 当前状态 |
|---|---|---|---|---|
| L0 声明/映射 | 当前源码已有 `VideoStream`、detector、SceneManager、CLI、输出和失败边界；后续归属表与单链路原则 | 逐条回读本文件 §§5-11、§20 与源码路径；检查旧细探只作线索 | 每一项映射均有源码证据、owner、禁止项和未验证边界 | **已完成静态归档**；不等于实现平台能力 |
| L1 静态实现/契约 | 入口、调用链、异常、资源 owner、四终态契约是否可审计 | `git diff --check`；检查 Markdown 表格/标题；静态核对禁止直连、第三方对象穿透和第二链路文字 | 仅修改目标 `ARCHITECTURE.md`；无源码/配置/测试/Git 改动；无“已运行”措辞冒充 | **已完成**：当前核对文档校验通过，未升级 L2-L4 |
| L2 纯内存/无外部媒体 | FrameTimecode/PTS 采样计划、CFR/VFR 边界、切点去重、错误形状和取消幂等 | 使用内存帧/伪 provider 的合同测试；不得 `skip` 掩盖缺失；记录测试数、跳过数、退出码 | 合同测试真实执行且失败分支可观察；无 OpenCV/PyAV/ffmpeg 依赖假绿 | **未验证** |
| L3 真实媒体链路 | 真实视频/图像序列 → 指定 provider → 采样 → 算法策略 → SceneList → manifest/输出 | 真实 CFR、VFR、Concat seam、坏帧、至少一个算法策略；记录 provider 版本、输入摘要、产物 hash、退出码 | 全链路真实运行；缺资源不能算通过；输出内容和时间轴均读回校验 | **未验证**：当前 `tests/resources` 缺失，当前核对未下载/生成媒体 |
| L4 发布/灾难闭环 | CLI/API、provider 缺失、外部命令失败、取消/墙钟超时、SIGTERM/SIGKILL、崩溃后回收与部分输出 | 独立进程组真实强杀；重启后扫描线程/进程/句柄/临时目录/租约/manifest；跑 backend 矩阵和 release/golden | 取消/超时/崩溃均有稳定错误和完整清理证据；无残留或残留被明确标记并阻断发布 | **未验证**：当前源码没有统一恢复协议，映射不能替代实现 |

L1 的文档校验只能证明当前核对写入没有破坏 Markdown 和边界；L2-L4 的命令必须在对应环境真实运行。`pytest` 收集成功、历史验证、缓存命中、打印“完成”、`skip` 或子代理回信均不得升级为 L3/L4。

### 20.6 后续收口：读取、时间码、编排、检测器与输出的实现级结论

本节是对前述概览的后续收口，优先级高于前文同一主题的概括性描述。结论来自当前工作树逐文件读取；没有安装依赖、下载媒体或运行外部工具，因此“源码存在”和“真实链路已运行”仍严格分开。

#### 20.6.1 视频读取后端：统一接口之下的真实差异

`VideoStream` 只规定属性、`read(decode=True/False)`、`reset()` 和 `seek()`，没有 `close()` 抽象，也没有上下文管理器。所有实现都把 `frame_number` 定义为读到的帧数（首帧为 1），把 `position` 定义为最后已读帧的 presentation time；首帧读完后位置仍为 0。`read(False)` 不是“只移动指针而不解码”的绝对保证，而是后端尽量只 `grab`/推进并避免返回图像，资源和解码器状态仍会前进。证据：`scenedetect/video_stream.py:79-223`、`tests/test_video_stream.py:158-200`。

| 后端 | 读取与时间语义 | seek/reset/失败 | 资源收口风险 |
|---|---|---|---|
| `VideoStreamCv2` | `VideoCapture.grab()` 后按需 `retrieve()`；失败时最多追加 `max_decode_attempts` 次 `grab`；`position` 优先取 `CAP_PROP_POS_MSEC`，非正值且已有帧时按帧率合成；OpenCV 的 `CAP_PROP_PTS` 被明确认为不可靠 | 文件/图像序列可 seek；seek 到正时间先退一帧再 `grab`，并用 `CAP_PROP_POS_MSEC` 做最多 100 次 VFR 校正；`reset()` 先 `release()` 再打开 | 没有公共 `close()`；正常生命周期只有 `reset()` 会显式 release。打开后帧率探测失败、异常或调用方结束时没有类内统一 release；`VideoCaptureAdapter` 借用外部 capture，`seek/reset` 都不支持且不拥有关闭责任；`backends/opencv.py:70-137,241-363,365-538` |
| `VideoStreamAv` | 长持有 `av.InputContainer.decode(video=0)` generator；`position` 使用当前 frame 的 `pts/time_base`，并减去 stream `start_time` 归一化；`frame_number` 是 PTS×平均帧率的 CFR 近似，不是 VFR 精确索引 | `seek()` 按 PyAV stream time base 定位后向前读到 target；`reset()` 关闭 container 后重开；`FFmpegError` 单帧跳过，连续 `8` 次停止；`AUTO/FRAME` 线程模式在 EOF 且未解完时可能重开并从上次位置继续 | `__del__` 先关 decoder 再关 container，并吞掉异常；类内没有显式关闭由路径创建的 `_io` 文件对象。测试辅助 `tests/helpers.py:24-50` 因此直接按 `_decoder → _container → _io` 关闭，说明公共接口不足；构造中途异常、解释器退出和原生异常仍需外部验收；`backends/pyav.py:87-171,267-357,413-436` |
| `VideoStreamMoviePy` | 由 MoviePy `FFMPEG_VideoReader` 启动 ffmpeg 子进程并缓存首帧；`read()` 读取下一帧来判断 EOF；源码把读出的 BGR 缓冲转成 **RGB**，与 `SceneDetector`/其他 OpenCV 后端期望的 BGR 契约不一致，不能只按 `VideoStream` 总接口推断颜色空间 | 始终报告可 seek；seek 失败在 `finally` 调 `reset()`；`reset()` 直接用新的 `FFMPEG_VideoReader` 覆盖旧 reader，没有先显式 `close()` 旧 reader；MoviePy 2.x 的 `last_read`/旧版 `lastread` 分支影响 EOF | 类本身没有 `close()`；重复 `reset()` 或 seek 失败可能留下旧 ffmpeg reader/子进程，测试 helper 只关闭当前 `_reader`；首次读取 aspect ratio 时还临时创建 `VideoStreamCv2`，其 capture 没有类内 close；`backends/moviepy.py:42-67,70-129,219-295`、`tests/helpers.py:46-50` |
| `VideoStreamConcat` | 构造时预打开/探测全部输入，实际只把一个 child 放入 `_cap`；全局时间轴以微秒 `Fraction` 偏移拼接，跨 seam 用 child `position`；`map_span()` 把全局区间映射为 `SourceSpan` | 所有源分辨率必须相同；帧率可不同但只警告；声明 duration 作为 offset 估计，读到真实 EOF 时只在实际结束 **晚于**声明结束时向后修正，较早结束不会向前修正；seek 可跨源，reset 重开第一个源 | `_finish_current_source`、跨源 seek 和 reset 都是直接覆盖 `_cap`，没有显式关闭旧 child；构造探测中途失败也没有统一清理已打开 child。尚未读完整个流时 `duration`/`map_span` 仍可能基于声明估计；`backends/concat.py:137-172,201-265,353-387` |

`open_video()` 的 fallback 边界必须特别保留：它只捕获 `VideoOpenFailure`；OpenCV/PyAV 对“路径不存在/权限不足”会抛 `OSError`，该异常不会在 `open_video()` 中转成另一个 backend 尝试。指定 backend 的 fallback 也可能改变 PTS、颜色空间和错误语义，调用方必须记录实际返回的 `BACKEND_NAME`，不能把“返回了 stream”当作指定 backend 已生效。证据：`scenedetect/__init__.py:120-151`。

#### 20.6.2 时间码与场景边界：三套时间来源不能混写

1. `Timecode(pts, time_base)` 是精确的有理 PTS 表示；`FrameTimecode` 可以承载它，同时保留平均 `frame_rate` 供帧号、显示和兼容 API 使用。对 VFR，`time_base/pts/seconds` 是权威时间，`frame_num` 是近似值。`framerate_to_fraction()` 只把常见 NTSC 帧率规范化为 `N*1000/1001`，不会把 CFR 假设变成 VFR 真值；`common.py:126-145,163-210`。
2. `position` 的约定是“最后已读帧的呈现起点”，不是下一个待读帧；因此首帧 `frame_number == 1` 而 `position == 0`。`seek(0)` 是把下一个读帧置于首帧前，`seek(1)` 在部分后端已经把指针置到首帧位置。把 position、frame number 和 CLI 的展示帧号混用会产生一帧偏差；`tests/test_video_stream.py:177-248,264-299`。
3. OpenCV 用 `CAP_PROP_POS_MSEC` 加 VFR 修正，PyAV 用归一化真实 PTS，MoviePy 按 CFR 合成时间，Concat 使用全局微秒偏移。因此同一媒体在不同 backend 上可能出现 seek、duration、最后一帧和 frame number 差异；跨 backend 比对必须比较 PTS 容差，不能只比较 `frame_num`。
4. `SceneManager.get_scene_list()` 把切点按集合去重/排序，并以 `start_pos` 到 `last_pos + 1` 组成连续场景；没有切点时默认返回空，只有 `start_in_scene=True` 才返回整个检测范围。CLI 读 CSV 时把展示用 1-based 帧号减一，输出 formatter 又从场景索引 1 开始显示；`scene_manager.py:376-408`、`_cli/controller.py:194-205`、`output/video.py:127-151`。
5. `VideoStreamConcat` 的 seam 不能简单以“文件声明 duration 相加”作真值：其真实读取只在遇到 EOF 后才可能修正后续 offset。对尚未完整读取的流做 `duration`、`map_span` 或输出切分，必须标注“基于声明 duration 的估计”。

#### 20.6.3 `SceneManager`：队列收口可靠，但状态复用不是安全的

真实逐帧链为：`detect_scenes()` 校验参数与裁剪 → 设置 `base_timecode`/Stats 基线 → 启动 daemon 解码线程 → `Queue(maxsize=4)` 传递 `(frame, position)` → 主线程按 detector 注册顺序调用 `process_frame()` → finally 设置 stop、排空队列并 join → 主线程重抛解码线程异常 → 用最终 position 调所有 detector 的 `post_process()`。`frame_skip` 只减少 detector 消费频率，解码线程仍推进跳过帧；返回值是 source frame number 的差值，不严格等于 detector 实际处理帧数。证据：`scene_manager.py:446-616,618-703`。

必须记录的实现级边界：

- `event_buffer_length` 只决定保存多少历史帧以支持 callback 回找，不是通用事件队列、回滚或事务。`AdaptiveDetector` 以 `window_width` 为缓冲长度并返回中心帧；若 detector 返回的 cut 已超出 buffer，cut 仍进入 cutting list，但 callback 找不到对应图像。
- `_process_frame()` 对每个 detector 直接追加 cuts，不在 callback 前去重；多个 detector 命中同一时间码会触发多次 callback，最终 `get_scene_list()` 才去重。`new_cuts` 在 detector 循环内被最后一个 detector 的结果覆盖，只影响进度条描述，不影响 cutting list。
- `clear()` 清 cuts、位置、frame size 并清 detector 列表，但不清 `_frame_buffer`、`_exception_info` 或已注入 detector 的内部状态；`clear_detectors()` 也只是丢弃对象引用。复用同一 `SceneManager`/detector 前必须重建对象或由调用方保证状态全新，不能宣称 manager 可安全重入。
- `_exception_info` 只在构造器初始化为 `None`，本次 `detect_scenes()` 开始时不重置；一次解码线程异常后再次调用同一 manager 可能重新抛旧异常，这是源码状态契约风险，不是恢复机制。
- finally 的 `stop → drain → join` 能避免正常异常路径遗留 decode thread，但没有墙钟 deadline；若 native `video.read()` 阻塞，join 收口时间没有上界。线程是 daemon 不等于资源已释放，`SceneManager` 也不关闭传入的 `VideoStream`。

#### 20.6.4 Detector：输入顺序、延迟事件和无 reset hook

`SceneDetector.process_frame(timecode, frame_img)` 假定时间码顺序连续，输入图像是 24-bit BGR；接口本身不验证顺序、dtype、shape 或颜色空间。返回值可以是 0 个或多个任意历史时间码，`post_process()` 在主线程 join 后处理 EOF 尾部事件，`event_buffer_length` 由实现声明。该 API 在 v1.0 前仍不稳定，证据：`detector.py:37-103`。

| Detector | 状态/指标 | 事件与边界 |
|---|---|---|
| `ContentDetector` | 相邻帧 HSV hue/saturation/luma 差异；可选 Canny+dilate edges；写 `content_val` 和分量指标 | `FlashFilter` 的 MERGE/SUPPRESS 实现 `min_scene_len`；以秒传入时 `max_behind` 按 240 fps 估算，超过该帧率时 callback 缓冲预算可能不足；`content_detector.py:147-243` |
| `AdaptiveDetector` | 复用 Content score，保留 `1+2*window_width` 帧窗口并写 `adaptive_ratio` | 对中心帧判定、晚 `window_width` 帧发出；`event_buffer_length == window_width`；不是第二次读取视频；`adaptive_detector.py:88-143` |
| `ThresholdDetector` | 写 `average_rgb`，跟踪 `in/out` fade 状态 | 默认只在下一次 fade-in 产生 cut；`add_final_scene=True` 且 EOF 为 fade-out 时由 `post_process()` 补尾 cut；`threshold_detector.py:100-191` |
| `HistogramDetector` / `HashDetector` | 分别写 `hist_diff` / `hash_dist[...]`；均以相邻帧比较 | 首帧只建基线；要求三通道 8-bit（Histogram 明确校验）；没有跨调用 reset；`detectors/histogram_detector.py`、`hash_detector.py` |
| `TransNetV2Detector` | 100 帧窗口和 ONNX Runtime/模型资产 | 文件存在不等于 CLI 注册、模型可用或测试通过；当前仍为待核能力 |

所有 detector 都把算法状态保存在 Python 对象字段中（上一帧、上一 cut、fade 状态、窗口等）；`SceneManager.clear()` 不调用 reset 协议。StatsManager 只提供指标字典，不提供 detector 状态快照，因此 stats CSV 不能让一次检测从中断点恢复。

#### 20.6.5 ffmpeg/mkvmerge：同步外部命令，不是受管作业

- `output/video.py` 模块导入时执行 `_FFMPEG_PATH = get_ffmpeg_path()`；`get_ffmpeg_path()` 会同步尝试 `ffmpeg -v quiet`，必要时再探测 `imageio_ffmpeg`。导入 PySceneDetect 输出模块因此可能产生外部进程探测副作用；路径在导入时缓存，之后 PATH 改变不会自动刷新。`get_mkvmerge_path()` 每次探测 PATH，但只把“可启动”当作可用，不建立版本/能力契约。
- `platform.invoke_command()` 只是 `subprocess.call(args)` 的薄包装：同步等待、继承标准输入/输出/错误，不捕获日志、不设 timeout、不建独立进程组、不提供取消或强杀；Windows 只把特定 206/87 OSError 映射为 `CommandTooLong`。证据：`platform.py:216-245`。
- `split_video_ffmpeg()` 对每个 scene 启动一次命令，固定加入 `-nostdin -y -ss START -i INPUT -t DURATION`，默认 `libx264/veryfast/crf22/aac`，之后加入 `-sn`；每个输出可覆盖旧文件。VFR/Concat 时间码被转换为秒字符串，输入是多文件 list 时旧 API 只允许单元素，不能直接把全局 Concat 场景当多输入切分。
- `split_video_mkvmerge()` 把所有 parts 放到一次命令，单场景补 `-001`，多场景由 mkvmerge 追加编号；输入路径必须是单文件，输出模板只有 `$VIDEO_NAME` 被替换。两者都没有 stdout/stderr 证据、manifest、hash、临时文件、原子 rename、回滚、resume 或墙钟超时。
- 更严重的返回契约：两函数初始化 `ret_val = 0`，捕获 `OSError`/`CommandTooLong` 后只写日志而不改码，缺工具、命令过长可能返回 0；ffmpeg 某一场景非 0 才会 break 并保留之前已经生成的文件。调用方必须同时检查工具探测、日志、输出文件集合和内容完整性，不能把返回 0 当制品成功。

#### 20.6.6 输出与 Stats：计划文件名不等于成功制品

- `save_images()` 在任何抽帧前调用 `video.reset()`，因此非 seekable `VideoCaptureAdapter` 不适用；随后按场景秒数生成采样点，逐点 `seek/read`，默认线程路径用两个有界队列（各容量 4）连接 encode/save worker。返回字典的 key 实际是 **0-based** 场景索引，列表保存的是计划写入的相对文件名，与 docstring 的“starting from 1”不完全一致；`output/image.py:163-296,352-444`。
- `cv2.imencode()` 返回 `is_ok=False` 时 worker 直接跳过，不写 error queue；主线程可能拿到“完成”返回但缺少对应文件。磁盘 `tofile()` 异常会经 error queue 回主线程，但已写文件不回滚。主线程在等待队列时发现 worker 异常会抛出，若调用方没有继续收口，daemon worker 可能短暂残留。
- `save_images()` 不负责关闭 `video`，也不保证 reset 后回到原位置；所有输出 handler 都是调用方传入 stream 的借用者，生命周期仍由调用方承担。
- `StatsManager.save_to_csv()` 对路径使用 `with open(..., "w")`，对外部 TextIO 不关闭；直接覆盖目标文件，没有临时文件、fsync、schema version、锁、hash 或回滚。`load_from_csv()` 已 deprecated，且读入裸整数 frame key 后无法在无 base framerate 时完整再写回时间码；`stats_manager.py:164-203,219-296`。
- CLI 的 `_save_stats`、图片 handler、视频 handler 按命令顺序执行；前一个 handler 的部分输出不会被后一个 handler 回滚。命令链成功只表示控制流返回，没有统一“输出制品全部存在且可读”的验收点。

#### 20.6.7 资源生命周期最终表（当前实现 vs 需要的外部治理）

| 资源 | 当前创建/释放事实 | 后续裁决 |
|---|---|---|
| OpenCV capture | `_open_capture()` 创建；`reset()` release；无公共 close；adapter 借用外部对象 | 调用方必须持有 backend-specific close 责任；不能依赖 `SceneManager`/`detect` 自动释放 |
| PyAV generator/container/file | generator/container 在 `__del__` 或 reset 中关闭；路径 `_io` 无类内显式 close | 测试已用直接属性关闭作为补偿；生产接入必须提供显式、幂等 close 或隔离进程 |
| MoviePy reader/ffmpeg 子进程 | reader 创建时启动 ffmpeg；类无 close；reset 覆盖旧 reader | 旧 reader/子进程回收存在静态风险；必须由外部 helper/进程 supervisor 验收，不以 GC 或 daemon 替代 |
| Concat child | 预探测全部，切换/seek/reset 直接覆盖 `_cap` | child 释放不是显式链路；多文件失败、反复 seek、reset 要做句柄/子进程扫描 |
| SceneManager decode thread/queue | Queue(4)、daemon decode thread；finally stop、排空、join | 正常异常路径有 join 设计，但阻塞 read 无 deadline；线程 join 不是 VideoStream close |
| detector/frame buffer/stats | manager 持有 detector、帧窗口和 Stats dict | 没有状态快照/恢复/reset 协议；重用必须新建对象或显式清理并现场验证 |
| image workers | 两 daemon worker、sentinel、error queue、join | encode false 静默缺产物；异常路径需扫描线程、队列和输出目录 |
| ffmpeg/mkvmerge | `subprocess.call` 同步返回码 | 无 timeout、进程组、取消、stdout/stderr、原子提交；必须由外部 supervisor 负责 |
| CSV/图片/视频文件 | 直接覆盖/写入用户目录 | 无 manifest/hash/rename/rollback；“返回 0/返回路径”均不等于完整制品 |

四种终态的真实收口目前只能描述为：正常结束时部分对象/线程有关闭路径；业务失败时可能保留部分输出；主动取消只覆盖 `SceneManager.stop()`，不覆盖外部 ffmpeg；宿主强杀没有 Python finally、子进程组回收、临时文件扫描或恢复协议。故本项目在资源治理上是“静态边界已收口，运行闭环未实现/未验证”。

#### 20.6.8 后续最终裁决

1. **可吸收的项目模式**：`VideoStream` 的读/seek/reset/position 抽象、`Timecode(pts,time_base)` 的精确时间表示、`SceneManager` 的 detector 编排和 `SceneList` 连续区间模型；吸收时必须补充颜色空间、显式 close、VFR、取消和输出制品契约。
2. **只能隔离为 provider**：OpenCV、PyAV、MoviePy、ONNX Runtime 以及 ffmpeg/mkvmerge。第三方对象、native 句柄和子进程不得穿透媒体模块；实际 backend、版本、退出信号和清理证据必须可观察。
3. **明确不吸收的风险模式**：`open_video` 对 OSError 不 fallback、MoviePy reset 不先 close、Concat 覆盖 child 不显式 close、SceneManager 无 reset/deadline、导入时外部探测、外部命令缺失仍可能返回 0、输出无 manifest/原子提交。
4. **后续状态**：契约、失败矩阵、时间轴和资源生命周期已用源码路径补齐，达到 L1 静态收口；未执行真实媒体、backend 矩阵、ffmpeg/mkvmerge、强杀、句柄扫描或输出 hash 校验，L2-L4 继续保持“未验证”，不因本节补文而升级。

### 20.7 不形成第二视频链路的最终裁决

1. **吸收为媒体模块能力**：把 `SceneManager` 的检测编排、多个 `SceneDetector` 的组合、切点去重和 `SceneList` 组装提炼为一个候选 `媒体.场景检测` 模块；模块不复制读取器、时间轴、任务系统或输出事务。
2. **吸收为支持库公共原子能力**：复用/升级 `FrameTimecode` 的 PTS 与 frame number 双表示、统一帧信封、采样计划、场景区间和统一结果/错误码；支持库只做纯契约和可测试转换，不直接 import `cv2`/`av`/`moviepy`，不直接读写媒体。
3. **归提供者并隔离**：OpenCV、PyAV、MoviePy、onnxruntime 以及 `ffmpeg`/`mkvmerge` 属于 provider/外部命令边界。每个 provider 只实现已登记能力，报告实际版本/后端/退出状态；不能把 PySceneDetect 的 CLI 或场景业务复制进 provider。
4. **归运行核心治理**：统一能力调用、授权、预算、任务状态、取消 token、单调 deadline、线程/进程组回收、租约和证据，直接复用运行核心已有治理；不建立 `VideoTaskManager`、`VideoTimeoutManager`、`VideoProviderRegistry` 或第二套崩溃恢复中心。
5. **CLI/API 只做适配**：现有 Click 链和未来 HTTP/API 只能在项目适配层把用户参数转换成一次 `媒体.场景检测` 调用；不让每个 command 直接访问 provider，也不为旧英文别名复制另一条注册路径。
6. **现有模式隔离**：当前 `StatsManager` CSV、`save_images` worker、`split_video_*` 及 `platform.invoke_command` 继续作为项目事实记录；它们不能直接升级为平台状态/制品事务。若未来复用，必须先补 manifest、hash、原子提交、部分失败、取消和崩溃清理契约。
7. **新建条件**：只有在需求登记、能力搜索、复用裁决、占用租约、模块/提供者契约、L2-L4 验收和装配计划齐全后，才允许建立平台接入工作包；当前核对不修改平台生产底座、不生成第二套视频实现。
8. **结论分类**：时间轴/场景区间/检测编排为“吸收候选”；第三方解码和算法运行时为“提供者隔离”；平台任务治理与回收为“复用运行核心”；TransNetV2 正式入口、帧跨进程传输、具体能力 id、provider 可用性和真实媒体回归为“待核”。

最终权威链路只有一条：

```text
项目 CLI/API
  → 运行核心唯一能力调用器
  → 媒体模块唯一场景检测编排
  → 支持库唯一时间轴/帧/采样契约
  → provider 唯一解码或算法执行
  → 运行核心统一监督、取消、超时、崩溃回收
  → 场景结果与证据
```

任何新增设计若无法落入这条链路，或需要第二个视频读取器、第二个帧采样器、第二个 detector 编排器、第二套取消/超时/回收器，裁决为**不吸收/阻断**。

### 20.8 后续修改与验证边界

- 当前核对实际修改文件：仅本 `ARCHITECTURE.md`；未改 `细探-PySceneDetect.md`、源码、配置、依赖、测试和 Git。
- 当前核对 `project_context` 开工 id：`49fd2716f50d4b93`；MCP 反馈登记工作 id：`19f617e7f2584c88`；MCP 实例：`system_engineering_toolkit`（HTTP `127.0.0.1:8766/mcp/`）。`project_context` 的平台根为 `~/Documents/Agent/PHP/系统工程平台`，与目标源码根不同；代码图查询只返回平台治理/能力调用相关边界，未返回 PySceneDetect 符号。该边界已如实保留，不能把平台图当目标仓库证据。
- 当前核对未安装依赖、下载媒体、启动服务或执行 PySceneDetect 的真实 CLI/pytest；L2-L4 仍为未验证。后续执行验证时必须逐级记录命令、退出码、测试/跳过数、输入媒体摘要、provider、产物和清理结果，并在平台 MCP 反馈后再登记成功证据。

## 21. 后续场景检测底座映射（收口版）

本节把后续关注的八类事实收敛为一条从输入到制品的可审计链路。它是对当前仓库源码的底座映射，不是把 PySceneDetect 现有实现误写成平台能力；其中“底座建议”表示未来接入时应采用的责任边界。

### 21.1 单一数据流与责任边界

```text
媒体引用/路径列表/设备
  → open_video() 选择并创建 VideoStream
  → backend 解码、规范化 position/PTS、报告坏帧
  → SceneManager 有界队列顺序取帧
  → SceneDetector.process_frame() 产生切点与指标
  → post_process() 补齐 EOF 尾部事件
  → cutting_list 去重/排序
  → SceneList 连续区间 [start, end)
  → CSV/统计、图片采样、ffmpeg 或 mkvmerge 输出
```

| 链路节点 | 当前实现事实 | 底座责任归属 | 必须保留的证据 |
|---|---|---|---|
| 输入 | `open_video()` 接受单路径、路径列表或已有输入对象；默认 OpenCV，可选 PyAV/MoviePy，路径列表由 Concat backend 组成 | 媒体输入 provider | 原始引用摘要、实际 backend、可 seek 能力、分辨率、帧率、时长 |
| 解码 | `VideoStream.read(True)` 返回帧，`read(False)` 推进而不返回图像；SceneManager 以 `Queue(maxsize=4)` 与解码线程并行 | provider 持有 decoder；运行核心监督线程/进程 | 每帧序号、PTS、尺寸/像素格式、EOF、`decode_failures`、线程收口结果 |
| 检测 | manager 按注册顺序调用全部 detector；一个 detector 可返回多个切点，多个 detector 不短路 | 场景检测模块编排，算法 provider 实现策略 | detector 名称/版本、参数、命中时间、事件延迟、指标引用 |
| 时间码 | `Timecode(pts,time_base)` 表达精确 PTS；`FrameTimecode` 同时承载帧号和秒；`frame_num` 在 VFR 时只是平均帧率近似 | 时间轴支持库唯一维护转换 | 时间基、原始 PTS、归一化秒、展示帧号、转换容差 |
| 场景 | `get_scene_list()` 对切点集合去重排序，生成连续 `[start,end)` 区间；无切点默认可为空 | 场景检测模块唯一组装 | 输入范围、切点来源、场景边界、是否完整、漏帧/坏帧摘要 |
| 切分 | ffmpeg 每个场景启动一次命令；mkvmerge 一次命令携带多个 `parts`；空场景返回 0 且不执行外部命令 | 外部命令 provider；制品治理归运行核心 | 完整命令参数、工具版本、退出码/信号、输出 manifest、hash、部分失败状态 |

### 21.2 输入、解码与坏帧语义

1. **输入不是解码成功**：路径存在、backend 被导入、容器能打开，只能证明输入阶段部分通过。成功帧必须另有帧计数、EOF 和尺寸记录。
2. **EOF、坏帧和错误必须分开**：`read()` 返回 `False` 表示流结束；OpenCV 可在有限次数内继续 `grab`，PyAV 可跳过 `FFmpegError` 并在连续失败达到阈值后停止；错误尺寸帧由 SceneManager 记录并跳过。这些都可能产生“有 SceneList 但不完整”的结果。
3. **坏帧不应静默降级**：底座结果至少包含 `decode_failures`、尺寸错误数、首个/最后一个坏帧位置和完整性标志。达到 provider 阈值后应返回可区分的 `DECODE_FAILED` 或 `PARTIAL_DECODE`，而不能仅凭进程退出码判定成功。
4. **颜色和尺寸是契约的一部分**：检测器假定 8-bit、三通道 BGR；MoviePy backend 当前存在 RGB/BGR 语义风险；解码尺寸变化会被跳过。底座必须在 provider 边界完成颜色空间和 shape 归一化并记录转换。
5. **路径列表有 seam 风险**：Concat 以子流声明 duration 估算偏移，真正读到 EOF 后才可能修正；未完整消费前的全局时间和切分范围必须标记为估计，不得伪装成精确时间轴。

### 21.3 时间码、CFR/VFR 与场景边界

| 情况 | 权威时间 | 可用的帧号语义 | 底座规则 |
|---|---|---|---|
| CFR | `pts × time_base` 或等价秒 | 可用作快速索引和展示 | 仍保留 PTS，不能只落帧号 |
| VFR | 解码帧携带的 `pts/time_base` | 平均帧率推导值是近似 | seek、采样、场景边界和切分优先使用 PTS |
| 非零 stream start time | 归一化后的 presentation time，并保留原始 PTS | 可能与 0-based 帧号脱钩 | 记录 start time 和归一化规则 |
| Concat seam | 子流实际 PTS 加全局 offset | 跨源帧号不具备单源意义 | 记录 `source_span`；声明 duration 只能作为临时估计 |

切点表示“新场景起始位置”。场景的结束位置是下一个切点，最后一个场景的结束位置来自最后已读位置/检测范围；因此 `[start,end)` 的半开区间是内部组合语义。CLI 的展示帧号、Python 的 0-based seek 指针和 detector 收到的 `position` 不能互换，边界转换必须集中在时间轴支持库。

### 21.4 检测器与切点编排

- `ContentDetector`/`HistogramDetector`/`HashDetector` 主要比较相邻帧；`ThresholdDetector` 维护亮度 fade 状态；`AdaptiveDetector` 以窗口中心帧判定并延迟输出；`TransNetV2Detector` 依赖 100 帧窗口、ONNX Runtime 和模型资产，不能从文件存在推断可用。
- detector 只接收当前帧、时间码和显式配置，不得自行打开视频、启动第二个读取循环或直接写制品。算法状态必须能在一次任务结束时释放，不能依靠 Stats CSV 恢复中断任务。
- `event_buffer_length` 是 callback 找回历史帧的容量提示，不是事务日志。相同切点可能触发多次 callback，最终场景组装阶段才集合去重；底座若需要事件级幂等，应另设事件 id 和来源集合。
- detector、callback 或解码线程抛错时，当前 manager 会 stop、排空队列并 join，再把异常带回主线程；这证明了异常收口意图，但没有墙钟 deadline，也不关闭调用方传入的 VideoStream。

### 21.5 ffmpeg/mkvmerge 与制品边界

`split_video_ffmpeg()` 对每个场景构造 `-nostdin -y -ss ... -i ... -t ...` 命令并同步等待；任一场景失败后停止后续场景，但已生成文件保留。`split_video_mkvmerge()` 将全部场景组装为一次 `--split parts:` 命令；单场景会补 `-001`。两者都直接写目标目录，不生成 manifest、hash、临时前缀或原子 rename。

当前返回码存在重要陷阱：空场景返回 0 是正常的“无命令”；缺少工具或 `CommandTooLong` 被捕获后，函数的默认 `ret_val=0` 可能保持不变；因此返回 0 不能单独证明切分成功。未来 provider 必须同时返回工具探测结果、实际退出状态、stderr 摘要、输出集合和完整性校验，制品由临时目录写完并校验后再提交。

### 21.6 资源生命周期与四种终态

唯一建议的生命周期为：`打开 → 能力探测 → 读取/检测 → 停止或 EOF → 排空队列 → join/reap → close/release → 扫描临时资源 → 写终态证据`。OpenCV capture、PyAV container/generator、MoviePy reader、ONNX session 和 ffmpeg/mkvmerge 子进程均只能存在于受管 provider 边界；`__del__`、daemon 线程、Python 进程退出和“操作系统会回收”都不是释放证明。

| 终态 | 最低收口动作 | 不能宣称 |
|---|---|---|
| 正常完成 | EOF、队列 sentinel、线程 join、关闭 decoder、产物 manifest/hash 校验 | 不能把返回路径或返回 0 当完整制品 |
| 业务失败 | 保存错误码和已完成产物，关闭所有资源，写 partial manifest | 不能自动回滚已写文件，也不能伪装全量成功 |
| 主动取消/超时 | 幂等 token、单调 deadline、停止读取、join/reap；外部进程需进程组治理 | `SceneManager.stop()` 不等于 ffmpeg 已停止，不等于墙钟超时 |
| 宿主/提供者崩溃 | 重启后按租约/进程身份扫描线程、子进程、临时目录和半写输出 | SIGKILL 后没有 finally，不能宣称资源和制品已清理 |

### 21.7 后续 L0-L4 证据门槛

| 等级 | 当前核对映射能证明的内容 | 升级所需真实证据 | 当前结论 |
|---|---|---|---|
| L0 | 文档/README/源码声明存在输入、检测器、时间码、切分入口 | 不要求运行，但必须标注声明来源 | 已完成，不能证明实现正确 |
| L1 | 当前源码的调用链、异常边界、坏帧策略、VFR 风险、资源 owner 和外部命令语义 | 源码逐文件核对、文档一致性、Markdown 差异检查 | 已完成静态映射；不等于媒体可运行 |
| L2 | 纯内存时间码换算、CFR/VFR 边界、切点去重、错误对象和取消幂等 | 不依赖真实媒体/外部工具的合同测试，记录测试数、跳过数和退出码 | 未验证 |
| L3 | 真实 CFR、VFR、Concat seam、坏帧输入经过指定 backend 和 detector，并读回 SceneList/输出 | 记录输入摘要、实际 backend、PTS、坏帧计数、产物 hash、退出码和清理结果 | 未验证；当前没有把静态文档当真实媒体证据 |
| L4 | provider 缺失、命令失败、超时、取消、SIGTERM/SIGKILL、重启扫描和发布/golden 闭环 | 独立进程组强杀、backend 矩阵、外部工具故障注入、残留扫描和 release 验收 | 未验证；当前实现没有统一恢复/原子提交协议 |

后续最终裁决：**吸收** `VideoStream` 的输入抽象、`Timecode/FrameTimecode` 的 PTS 模型、SceneManager 的单链路 detector 编排和 SceneList 区间模型；**隔离** OpenCV、PyAV、MoviePy、ONNX Runtime、ffmpeg、mkvmerge；**补强** 坏帧可观察性、VFR 时间轴、显式 close、超时/取消、manifest/hash/原子提交和崩溃回收。任何需要第二个读取器、第二套时间码、第二个 detector 编排器或第二套取消/回收中心的方案均阻断。

## 22. 分段审计补充（2026-08-21）

### 22.1 范围、目录和定位证据

当前核对先核对实际目录：源码根为
`~/Documents/Agent/github 源码参考/30_多模态与媒体分析/10_scene_segmentation/PySceneDetect`。
源码没有独立的 `open_video/`、`decoder/`、`ffmpeg/` 或 `mkvmerge/` 目录：`open_video()` 在
`scenedetect/__init__.py`，decoder 语义在 `video_stream.py` 与 `backends/`，外部切分在
`output/video.py`，命令探测和 `subprocess` 包装在 `platform.py`。`video_splitter.py` 只是
deprecated 转发模块，不能作为第二套切分实现。

按段读取了 `open_video`/`detect`、`VideoStream`、OpenCV/PyAV backend、`SceneManager`、
`SceneDetector`/主要 detectors、`Timecode`/`FrameTimecode`、`_fan_out.py`、ffmpeg/mkvmerge
输出、CLI context/controller/commands、README、Sphinx API 页面、参考库 `ARCHITECTURE.md`
以及 VFR、坏帧、SceneManager、backend、fan-out、CLI、输出测试。目标项目没有 `.codegraph/`；
尝试 CodeGraph 只能得到当前平台仓库的无关结果，因此没有把平台代码图当作 PySceneDetect 证据。

### 22.2 审计结论

- **VFR**：PyAV 以帧 PTS 和 `time_base` 作为精确位置，并处理非零 `stream.start_time`；OpenCV
  使用 `CAP_PROP_POS_MSEC`，seek 再向前 `grab()` 做最多 100 次补偿。两者的 `frame_num` 仍是
  CFR 等价/平均帧率派生值。EDL、FCP7 等帧率格式对 VFR 只能是近似输出，不能回写成精确时间事实。
- **坏帧**：PyAV 跳过 `FFmpegError`，累计 `decode_failures`，连续 8 次后结束；OpenCV 按
  `max_decode_attempts` 重试；SceneManager 还跳过尺寸漂移帧并最多记录 16 条错误。该策略是
  “可观察地降级”，不是内容修复；CLI 结果没有把漏帧/失败计数提升为结构化成功条件。
- **队列与并发**：SceneManager 使用容量 4 的有界队列，生产者阻塞形成背压，异常路径会 stop、
  排空并 join。FanOut 为每个消费者建有界队列，最慢消费者决定源读取速度，`prefetch=0` 实际
  映射为容量 1；`close()` 最多等待 reader 5 秒，且不拥有/关闭底层 source。若 source.read()
  或原生 decoder 阻塞，stop/join 没有墙钟超时或强制终止保证。
- **外部进程**：`platform.invoke_command()` 最终调用同步 `subprocess.call`；ffmpeg 在模块导入
  时就探测，切分逐场景启动 ffmpeg，mkvmerge 一次拼接全部 parts。没有统一 timeout、取消令牌、
  进程组 kill、stdout/stderr 截断、输出 manifest 或原子提交；多场景中途失败保留已写产物。
- **返回值风险**：`split_video_ffmpeg()` 与 `split_video_mkvmerge()` 对缺工具或 `CommandTooLong`
  捕获后可能保留默认 `ret_val=0`。空场景返回 0 是合法无操作，但缺工具/命令过长的 0 是假成功
  风险；调用方不能只依据退出码判断制品完整。
- **资源清理**：PyAV 主要依赖显式 reset 与 `__del__` 兜底，OpenCV `VideoCapture` 没有统一
  公共 `close()`，adapter 借用调用方 capture；SceneManager 不拥有传入 stream。图片 worker、
  外部命令和输出文件均无统一资源清单、部分产物回滚或崩溃后 orphan 扫描协议。
- **CLI/tests/docs 质量**：CLI 测试文件自身明确写出“主要检查退出码、不检查输出正确性”、
  缺少若干 min-scene/drop-short 场景；输出测试明确将 mkvmerge 标为 TODO；真实 VFR、损坏帧、
  后端和 fan-out 测试覆盖面较好，但依赖 `tests/resources` 和外部工具，跳过不等于通过。Sphinx
  API 页面主要是 `automodule` 薄包装，真正的生命周期和失败语义仍需以源码/本文件为准。

### 22.3 质量等级与平台裁决

静态证据达到 L1：调用链、VFR 模型、坏帧策略、有界队列、外部进程边界和 owner 风险已逐项核对；
当前核对没有安装依赖、运行 pytest/CLI、调用 ffmpeg/mkvmerge 或执行强杀，因此没有 L2/L3/L4 运行证据。
平台复用时必须把 decoder、detector、外部命令置于受管 provider，统一返回 PTS、实际 backend、
decode failures、终态、stderr 摘要、输出清单和清理结果，并由宿主提供墙钟 deadline、进程组回收、
幂等/manifest/hash/原子 rename。不能直接复用当前同步 `subprocess.call`、GC 析构、daemon thread
或“返回 0”作为取消、资源释放或制品提交协议。
