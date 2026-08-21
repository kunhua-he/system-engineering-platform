# PyAV 架构建档

> 本文是 `~/Documents/Agent/github 源码参考/30_多模态与媒体分析/05_video_decode_sampling/PyAV` 的首轮全量架构档案。项目源码、依赖、API、测试与远程版本均按当前磁盘事实记录；源码路径、类名、函数名、字段名和命令保留原文。

## 0. 建档范围与证据边界

- **项目**：PyAV，Python 包名 `av`。
- **定位**：FFmpeg 的 Pythonic binding；对容器、流、包、编解码器、帧和滤镜提供接近底层的控制，同时提供 Python 对象、缓冲区、NumPy/Pillow 等互操作层。
- **许可证**：项目 `BSD-3-Clause`；运行时绑定的 FFmpeg 组件及其编译配置仍需单独核对 LGPL/GPL 边界。
- **当前本地提交**：`32e9f7de15c3ecdddd78cc17b5ed4cdafdd15149`，提交信息 `Refresh installation documentation`，时间 `2026-07-22T22:05:21-04:00`。
- **当前本地版本**：`av.about.__version__ = "18.0.0"`，证据：`av/about.py:1`。
- **工作树事实**：源码工作树未见已跟踪改动；存在未跟踪 `细探-PyAV.md`。本轮只新增/修改本文件，不删除细探，不修改源码、依赖、测试、配置，不安装、不启动、不构建、不提交。
- **远程核对**：`origin/main` 的远程头为 `040da79f2ef323988c56e5e72072b768570c470b`（2026-08-18），本地落后 **48** 个提交。远程快照通过 `127.0.0.1:4780` 独立克隆至 `/tmp/PyAV-remote-4780`，未覆盖本地工作树。
- **远程版本事实**：独立快照 `av/about.py:1` 为 `19.0.0pre1`；远程 `pyproject.toml:13` 要求 Python `>=3.12`，本地为 `>=3.11`。远程快照仅用于版本差异核对，不是本地实现证据。
- **细探吸收**：已有 `细探-PyAV.md` 已完整读取，并在第 13 节逐条记录吸收、部分吸收和未吸收裁决；按任务约束保留原文件。后续架构事实只维护本文件，旧细探不作为第二事实源。

## 1. 一句话架构结论

PyAV 是一个以 `av.container.core.open` 为入口、以 Cython 编译的 `av.*` 模块为 Python API 面、以 `include/*.pxd` 和 `av/**/*.pxd` 为 FFmpeg C ABI 声明面、以 FFmpeg 的 `libavformat/libavcodec/libavfilter/libswscale/libswresample/libavutil/libavdevice` 为执行底座的多媒体绑定库；其核心数据流是 **Container → Stream → Packet → CodecContext → Frame**，滤镜图 `Graph` 和硬件加速 `HWAccel` 作为旁路能力接入，帧再进入 NumPy/Pillow/DLPack 或输出容器。

## 2. 总体流程图

```text
媒体文件 / URL / Python file-like object / 自定义 io_open
                         │
                         ▼
              av.open(file, mode, options, timeout, hwaccel)
                         │
          ┌──────────────┴──────────────┐
          │                             │
          ▼                             ▼
 InputContainer                    OutputContainer
 avformat_open_input               avformat_alloc_output_context2
 avformat_find_stream_info         add_stream / add_mux_stream / template
          │                             │
          ▼                             ▼
 StreamContainer                  Stream + CodecContext
 video/audio/subtitle/data        encode(Frame) → Packet
          │                             │
          ▼                             ▼
 demux() → Packet                 mux(Packet) → av_interleaved_write_frame
          │                             │
          ▼                             ▼
 Packet.decode()                  close() → av_write_trailer
          │
          ▼
 CodecContext.decode(Packet)
 avcodec_send_packet → receive_frame
          │
          ▼
 AudioFrame / VideoFrame / SubtitleSet
          │
   ┌──────┼───────────────┬───────────────┐
   ▼      ▼               ▼               ▼
reformat to_ndarray    to_image        DLPack / side_data
Graph   NumPy           Pillow          motion vectors / HDR / enc params
   │
   ▼
FilterContext.push/pull → Frame
```

## 3. 分层与真实目录

```text
PyAV/
├── av/                         # Python/Cython 绑定主包
│   ├── _core.py/.pxd/.pyi      # FFmpeg 初始化、版本与库元数据
│   ├── container/               # Container、InputContainer、OutputContainer、Python IO
│   ├── codec/                  # Codec、CodecContext、HWAccel
│   ├── audio/                  # AudioFrame、AudioFormat、AudioLayout、AudioFifo、重采样
│   ├── video/                  # VideoFrame、VideoFormat、VideoStream、重格式化
│   ├── filter/                 # Filter、FilterContext、FilterLink、Graph
│   ├── subtitles/              # SubtitleSet、ASS/文本与位图字幕
│   ├── sidedata/               # 帧侧数据、MotionVectors、VideoEncParams
│   ├── frame.py / plane.py     # Frame 与通用/视频缓冲平面
│   ├── packet.py               # Packet 与 PacketSideData
│   ├── stream.py               # Stream、DataStream、AttachmentStream
│   ├── format.py / rational.py # 格式与时间基
│   ├── buffer.py / dictionary.py / utils.py
│   ├── error.py / logging.py   # 错误映射与 FFmpeg 日志
│   ├── datasets.py             # 测试媒体缓存下载
│   ├── device.py               # 输入/输出设备枚举
│   ├── __init__.py             # 核心初始化与常用对象再导出
│   └── __main__.py             # pyav CLI
├── include/                    # FFmpeg 头文件的 Cython 声明
├── tests/                      # pytest 行为测试与测试辅助
├── docs/                       # Sphinx 文档、API、cookbook
├── examples/                   # 音视频、滤镜、硬件、字幕、NumPy 示例
├── scripts/                    # FFmpeg vendor、构建、测试、虚拟环境脚本
├── setup.py                    # Cython/Extension 构建编排
├── pyproject.toml              # 包元数据、构建依赖和入口
├── Makefile                    # build/test/lint/fate-suite
├── AGENTS.md                   # 开发规则
└── 细探-PyAV.md                # 既有研究笔记（本轮保留）
```

按当前工作树可复现的文件清单统计，`av/` 有 60 个 `.py`、56 个 `.pxd`、51 个 `.pyi`，`tests/` 有 34 个 `test_*.py` 模块，`docs/` 有 35 个文件，`include/` 有 6 个 `.pxd`。这里不再把不同扩展名相加后称为“源码文件数”，也不把测试模块数称为测试目录总文件数。核心实现大量采用同名 `.py` + `.pxd` + `.pyi` 三件组合：`.py` 描述 Cython mode 源码，`.pxd` 提供跨模块 cimport/类型声明，`.pyi` 提供静态类型和公开接口提示。

## 4. 启动入口、构建入口与初始化顺序

### 4.1 Python 包入口

`av/__init__.py:1-4` 明确要求先导入 `av._core`，以初始化被包装的底层库；随后导入 `av.logging`，再集中再导出 `AudioFrame`、`VideoFrame`、`Packet`、`Codec`、`CodecContext`、`open`、`ContainerFormat`、设备枚举等常用对象。该顺序是 ABI/FFmpeg 初始化约束，不是普通的便捷导入。

`av/__main__.py:6-51` 提供 `pyav` 命令：

- `--version`：打印 PyAV 版本、FFmpeg 库配置、许可证与各库版本；
- `--codecs`：调用 `av.codec.codec.dump_codecs()`；
- `--hwdevices`：调用 `av.codec.hwaccel.hwdevices_available()`；
- `--hwconfigs`：调用 `av.codec.codec.dump_hwconfigs()`。

`pyproject.toml:49-50` 将命令 `pyav` 映射到 `av.__main__:main`。

### 4.2 构建入口

`pyproject.toml:1-2` 的构建系统依赖 `setuptools>=77.0`、`cython>=3.1.0,<4`；动态版本来自 `av.about.__version__`（`pyproject.toml:32,41-42`）。

`setup.py` 的关键职责：

1. 定义 FFmpeg 库集合 `FFMPEG_LIBRARIES`：`avformat`、`avcodec`、`avdevice`、`avutil`、`avfilter`、`swscale`、`swresample`（`setup.py:14-22`）。
2. 根据 CPython 版本决定 `Py_LIMITED_API`/abi3 策略（`setup.py:24-31`）。
3. 通过 `--ffmpeg-dir` 或 `pkg-config` 获取 include/library 参数（`setup.py:56-120`、`setup.py:123-140`）。
4. 以 `cythonize` 编译 `av/filter/loudnorm.py` + `loudnorm_impl.c`，并遍历 `av/` 下 `.py/.pyx` 生成扩展（`setup.py:144-205`）。
5. 将 `.pxd/.pyi/.typed` 作为 package data（`setup.py:208-218`）。

`Makefile` 的行为边界：

- `make`/`build` 会升级 Cython/setuptools 并执行 `setup.py build_ext --inplace --debug`；
- `make test` 会升级 Cython/NumPy/Pillow/pytest 后运行 pytest；
- `make lint` 会升级 ruff/isort/Pillow/NumPy/mypy 并运行格式、导入排序和类型检查；
- `make fate-suite` 下载完整 FFmpeg FATE 样本。

本轮没有执行上述命令，避免改变依赖或生成构建产物。

## 5. 核心对象模型与所有权

### 5.1 容器层

- `Container`（`av/container/core.py:228-491`）是不可直接构造的基类，保存 `AVFormatContext`、文件名/文件对象、格式、选项、元数据、超时回调、打开文件表。
- `InputContainer`（`av/container/input.py:23-317`）负责 `avformat_find_stream_info`、创建 `Stream` 与对应解码 `CodecContext`、`demux`、`decode`、`seek`、刷新 codec buffers。它通过 `__dealloc__`/`close_input` 释放 `AVFormatContext`。
- `OutputContainer`（`av/container/output.py:68-718`）负责创建输出流、编码启动、写 header、`mux_one`、extradata 缓冲、写 trailer 和释放 `AVPacket`。`add_stream` 产出带 `CodecContext` 的编码流；`add_mux_stream` 产出不创建 codec context、适合外部已编码包的流。
- `StreamContainer` 负责按媒体类型组织和筛选 `Stream`；`Stream` 通过 `codec_context` 暴露编码/解码状态，并保存 `index_entries`、元数据、时间基、帧数、disposition、discard 和类型。

资源所有权的核心规则是：FFmpeg 指针由 Cython class 的 `__dealloc__`/显式 `close` 管理；Python 包装对象保持必要的上层引用，例如 `Stream` 持有 `Container`，`FilterContext` 通过弱引用回到 `Graph`，`Packet` 的 Python 输入可通过 `AVBufferRef` 保持源对象生命周期。

### 5.2 编解码层

- `Codec`（`av/codec/codec.py:78-344`）根据 `name` 与 `mode` 查找 encoder/decoder，暴露 `type`、`id`、能力位、profiles、支持的 frame rate/audio rate/video/audio format、硬件配置。
- `CodecContext`（`av/codec/context.py:230` 起）管理 `AVCodecContext`；`open` 调 `avcodec_open2`，`encode` 走 `avcodec_send_frame`/`avcodec_receive_packet`，`decode` 走 `avcodec_send_packet`/`avcodec_receive_frame`，`None` 表示 flush。
- `ThreadType`、`Flags`、`Flags2`、`OptionType`、`OptionFlags` 将 FFmpeg C 枚举映射为 Python 枚举；`CodecOption*` dataclass 描述通用/私有选项。
- `av/error.py` 将 FFmpeg 返回码和错误标签映射为 Python 异常；`err_check` 是底层调用的统一错误闸门。

### 5.3 帧、包、缓冲与时间

- `Packet`（`av/packet.py:216-517`）包装 `AVPacket`，包含 `pts`、`dts`、`duration`、`pos`、`size`、`time_base`、keyframe/corrupt 等属性；`decode` 转交其所属 `Stream`。
- `Frame`（`av/frame.py:13-210`）是音视频帧基类，统一 `pts`、`dts`、`duration`、`time`、`time_base`、`opaque`、`side_data` 与 `make_writable`。
- `VideoFrame`（`av/video/frame.py:497` 起）管理 `AVFrame` 的像素格式、宽高、planes、旋转/色彩属性、`reformat`、`to_rgb`、`save`、`to_image`、`to_ndarray`、DLPack/CUDA 互操作。
- `AudioFrame`（`av/audio/frame.py:30` 起）管理采样格式、声道布局、采样数、采样率、音频 planes、`from_ndarray`/`to_ndarray`。
- `Plane`、`VideoPlane`、`AudioPlane` 提供 buffer protocol；`Buffer`/`ByteSource` 处理 Python bytes、数组和 FFmpeg 缓冲区之间的生命周期。
- `AVRational`、`av.rational` 与 `av.utils.to_avrational` 维持 Python 分数/FFmpeg `AVRational` 的时间基转换，避免直接暴露 C 结构。

### 5.4 侧数据与字幕

`av/sidedata/sidedata.py:13-135` 以 `Type` 枚举映射 FFmpeg frame side data；`SideDataContainer` 同时支持按索引、按字符串类型和按枚举访问。特殊类型被包装为 `MotionVectors` 与 `VideoEncParams`，并可从 `VideoFrame.side_data` 读取。

`av/subtitles/subtitle.py:18-336` 以 `SubtitleSet` 表示一个 `AVSubtitle` 集合，并按 rect 类型构造 `BitmapSubtitle` 或 `AssSubtitle`；`SubtitleSet.create` 能分配用于编码的 ASS 字幕结构，字幕时间值按所在 stream 的 time base 解释。

## 6. 关键运行链路

### 6.1 输入：打开、探测、解复用、解码

1. `av.open(file, mode="r", ...)`（`av/container/core.py:494-612`）规范化 `Path`/字符串/file-like object，拆分 `timeout` 为 open/read 两个超时。
2. `Container.__cinit__` 分配 `AVFormatContext`，设置 `interrupt_cb`，调用 `avformat_open_input`；随后 `InputContainer.__cinit__` 调 `avformat_find_stream_info`。
3. 每个 `AVStream` 查找 decoder，创建 `AVCodecContext`，用 `wrap_codec_context` 映射为 `VideoCodecContext`/`AudioCodecContext`/`SubtitleCodecContext`，再由 `wrap_stream` 构造具体 `VideoStream`/`AudioStream`/`SubtitleStream`。
4. `InputContainer.demux` 调 `av_read_frame`，把所有权从复用的读取包移动到新 `Packet`；目标 stream 的时间基写入 packet。
5. `InputContainer.decode` 逐包调用 `Packet.decode`；`CodecContext._decode` 向 FFmpeg 发送 packet，再循环接收 frame，并将 packet 的 time base 传给 frame。
6. `seek` 调 `av_seek_frame` 后对各 stream 的 codec context 调 `flush_buffers`，因此 seek 后需要从 keyframe 附近重新解码。

### 6.2 输出：编码、封装、flush、关闭

1. `av.open(file, "w", format=...)` 分配 `AVFormatContext`；`OutputContainer.add_stream` 先验证格式是否支持 codec，再创建 stream/context 并设置视频/音频默认值。
2. 首次 `stream.encode(frame)` 或 `output.mux(packet)` 会使 codec context `open`，写 header；流的结构属性应在写 header 前全部设置。
3. `CodecContext.encode` 将帧时间基重标到 codec time base，使用 send/receive API 产生 `Packet`，并把 packet time base 设回 codec time base。
4. `OutputContainer.mux` 接受一个 `Packet` 或 packet 序列；写入前把 packet 重标到目标 stream time base。对需要 in-band extradata 的流，先用 `extract_extradata` bitstream filter 缓冲并处理首包。
5. 传入 `None` 给 `encode` 执行编码 flush；`close_output` 负责剩余缓冲、`av_write_trailer`、必要时关闭 `AVIOContext`，并保证 trailer 不重复写。

### 6.3 滤镜图

`Graph`（`av/filter/graph.py:16-306`）分配 `AVFilterGraph`，通过 `add` 分配/初始化 `FilterContext`，`link_nodes`/`FilterContext.link_to` 建立边，`configure` 调 `avfilter_graph_config`，并登记 FFmpeg 自动插入的 filters。

- `add_buffer`/`add_abuffer` 将视频/音频帧参数转成 `buffer`/`abuffer` 初始化参数；
- `push`/`vpush` 将 `VideoFrame`、`AudioFrame` 或 `None` 推入源；
- `pull`/`vpull` 从单 sink 取出帧，并自动配置图；
- `threads` 只能在添加 filter 前修改；
- `FilterContext` 对 source/sink 做 push/pull 委托，对普通 filter 通过唯一 input/output 委托。

### 6.4 硬件加速与 GPU 路径

`HWAccel`（`av/codec/hwaccel.py:111-220`）描述 device type、device、软件回退、options、flags、`is_hw_owned`，按 `Codec.hardware_configs` 选择 FFmpeg 支持的 device/frame context 方法并创建 `AVBufferRef`。输入路径在 `Container`/`CodecContext` 初始化期间接入；编码路径在 `CodecContext._setup_encode_hwframes` 延迟到最终宽高/像素格式确定后创建 frames context。

`CudaContext`（`av/video/frame.py:22-138`）缓存 CUDA device/frame context；`VideoFrame` 支持从 DLPack capsule 或 `__dlpack__` 对象接入，并在硬件帧与软件帧之间通过 `av_hwframe_transfer_data` 转换。硬件帧不能直接 `to_ndarray`，需先指定软件格式进行 reformat/download。

### 6.5 NumPy、Pillow 与 DLPack

- `VideoFrame.to_ndarray` 按像素格式选择无拷贝 view 或多平面拼接，处理 stride、端序、`yuv420p`/`nv12`/`pal8` 等特殊布局，并在必要时重排通道。
- `VideoFrame.from_ndarray`、`AudioFrame.from_ndarray` 校验 dtype、维度、通道/平面布局后拷贝到 FFmpeg buffer。
- `VideoFrame.to_image` 依赖 Pillow，将 RGB plane 逐行复制为 `PIL.Image`；`save` 通过临时输出容器编码 PNG/JPG。
- DLPack 使用 capsule ownership 改名 `dltensor` → `used_dltensor`，由 FFmpeg `AVBufferRef` 回调释放源 tensor；这是跨框架 GPU/CPU buffer 共享的 ABI 边界。

## 7. API 面（主要公开契约）

| API/对象 | 位置 | 职责与返回 |
|---|---|---|
| `av.open` | `av/container/core.py:494` | 打开输入/输出容器；返回 `InputContainer` 或 `OutputContainer` |
| `InputContainer.demux` | `av/container/input.py:136` | 迭代 `Packet` |
| `InputContainer.decode` | `av/container/input.py:227` | 迭代解码后的 `Frame` |
| `InputContainer.seek` | `av/container/input.py:243` | 按时间基 seek 并刷新 codec buffers |
| `OutputContainer.add_stream` | `av/container/output.py:83` | 创建编码 stream/context |
| `OutputContainer.add_mux_stream` | `av/container/output.py:197` | 创建无 codec context 的预编码复用 stream |
| `OutputContainer.add_stream_from_template` | `av/container/output.py:274` | 从输入 stream 复制编码参数 |
| `OutputContainer.mux`/`mux_one` | `av/container/output.py:600/609` | 写入 packet 或 packet 序列 |
| `Codec` | `av/codec/codec.py:78` | 查询 codec、能力、profiles、硬件配置 |
| `CodecContext.encode`/`decode` | `av/codec/context.py:681/708` | FFmpeg send/receive 编解码 |
| `VideoFrame.reformat` | `av/video/frame.py:683` | 通过 `VideoReformatter` 缩放/改像素格式/色彩元数据 |
| `VideoFrame.to_ndarray`/`from_ndarray` | `av/video/frame.py:774` 及类中静态方法 | NumPy 转换 |
| `AudioFrame.to_ndarray`/`from_ndarray` | `av/audio/frame.py:100,184` | 音频数组转换 |
| `Graph.add`/`configure`/`push`/`pull` | `av/filter/graph.py:64-306` | 构造并驱动 FFmpeg 滤镜图 |
| `HWAccel`/`hwdevices_available` | `av/codec/hwaccel.py:95-220` | 硬件设备与 codec context 配置 |
| `SubtitleSet.create` | `av/subtitles/subtitle.py:41` | 创建可编码字幕集合 |
| `pyav --version/--codecs/--hwdevices/--hwconfigs` | `av/__main__.py:6-51` | 诊断与能力枚举 CLI |

`docs/api/` 共有 17 个 API 文档入口，覆盖 `audio`、`bitstream`、`buffer`、`codec`、`container`、`error`、`filter`、`frame`、`packet`、`plane`、`sidedata`、`stream`、`subtitles`、`time`、`utils`、`video` 和全局项；`docs/cookbook/` 提供 audio、basics、numpy、subtitles 四类用法。

## 8. 依赖、FFmpeg ABI 与配置

### 8.1 Python/构建依赖

本地 `pyproject.toml` 声明 Python `>=3.11`，构建依赖为 `setuptools>=77.0`、`cython>=3.1.0,<4`。测试/开发流程还使用 `pytest`、`numpy`、`Pillow`、`mypy`、`ruff`、`isort`；这些主要由 `Makefile` 的命令安装或运行，未在 `[project] dependencies` 中声明为运行时强制依赖。

NumPy、Pillow 采用按需导入：`VideoFrame.to_ndarray`、`AudioFrame.to_ndarray`、`from_ndarray` 需要 NumPy；`VideoFrame.to_image` 和保存图像需要 Pillow。`tests/common.py:15-20` 对 Pillow 缺失有探测，但部分测试以 `pytest.skip` 表达可选环境能力。

### 8.2 FFmpeg 组件

必须链接：`libavformat`、`libavcodec`、`libavdevice`、`libavutil`、`libavfilter`、`libswscale`、`libswresample`。`docs/overview/installation.rst:24-47` 同时要求 `pkg-config` 与 Python development headers；macOS 源码构建文档要求 Homebrew 的 `ffmpeg` 与 `pkg-config`。Windows 通过 `scripts/fetch-vendor.py` 和 `scripts/ffmpeg-latest.json` 获取 PyAV 维护的开发文件。

FFmpeg 头文件声明位于 `include/avcodec.pxd`、`avformat.pxd`、`avfilter.pxd`、`avdevice.pxd`、`avutil.pxd`、`libav.pxd`；具体模块再以 `cython.cimports.libav` 访问。这种设计将 ABI 声明、Cython 类型和 Python 公开对象绑定在一个编译期边界上。

### 8.3 配置/许可证风险

- FFmpeg 版本与编译选项会改变 codec、filter、硬件设备和许可证信息；`pyav --version` 会把底层库的 configuration/license/version 打印出来。
- `setup.py` 只接受它能解析的 `pkg-config` flags；未知 flags 会拒绝构建，静态 FFmpeg 库场景明确不支持。
- 本地文档写“本 release 支持 FFmpeg 8.x”；远程分支已经增加 FFmpeg 9 测试与同步，版本差异不应直接回填本地源码。
- 硬件加速是宿主能力，不是跨平台固定保证；测试根据 `hwdevices_available()` 和 `HWACCEL_DEVICE_TYPE` 决定是否执行。

## 9. 测试体系与数据模型验证

### 9.1 测试组织

本地 `tests/` 有 34 个 `test_*.py` 测试模块和 `tests/common.py`/`tests/__init__.py`，按 AST 静态统计共有 **428 个 `test*` 函数/方法**（不是本轮运行结果）。主要分布：

- `test_videoframe.py`：110，像素格式、平面、重格式化、NumPy/Pillow、DLPack/硬件帧相关；
- `test_dlpack.py`：37，跨框架 buffer/capsule；
- `test_codec_context.py`：28，编解码 context、options、send/receive、flush；
- `test_decode.py`：18，解复用、解码、时间基、侧数据、硬件解码；
- `test_encode.py`：17，音视频编码、mux、profile、B-frame、硬件编码；
- `test_audioframe.py`：16，音频帧与 ndarray；
- `test_packet.py`：15，包时间戳、side data、buffer；
- `test_filters.py`：14，图构造、连接、音视频 source/sink、线程与 EOF；
- 其余覆盖 `audiofifo`、`audioformat`、`audiolayout`、`audioresampler`、`bitstream`、`chapters`、`codec`、`containerformat`、`device`、`dictionary`、`display_matrix`、`errors`、`file_probing`、`indexentries`、`logging`、`open`、`python_io`、`rational`、`remux`、`seek`、`streams`、`subtitles`、`timeout`、`videoformat`。

### 9.2 测试数据与隔离

`tests/common.py:46-83` 将输出放在项目 `sandbox/`；`PYAV_TESTDATA_DIR` 指向 `tests/assets`，并通过 `av.datasets.fate`/`cached_download` 缓存 FFmpeg FATE 或 PyAV curated 样本。测试既包含纯内存 `io.BytesIO`，也包含实际媒体文件、临时输出、FFmpeg filter source 和外部编码器能力。

`av.datasets.cached_download` 使用规范化文件名、可写数据目录、`.tmp` 临时文件和 `os.rename` 原子落盘；这属于测试数据缓存，不是应用持久化数据库。当前工作树未见 `tests/assets` 全量样本清单，不能把测试源码存在等同于所有 FATE 样本已具备。

### 9.3 测试规则与未执行项

`AGENTS.md` 要求：

```text
source ./scripts/activate.sh
make
make test
python -m pytest tests/some_file.py
python -m pytest -k "substring"
make lint
```

并特别提醒 Cython 可能产生未定义行为（UB）。本轮遵守只读研究约束，没有执行 `make`、`make test`、pytest、lint、FATE 下载、依赖安装或服务启动，因此本文不宣称当前环境测试通过。

## 10. 当前本地与远程差异

远程独立快照相对本地提交领先 48 个提交，`git diff --stat` 显示 117 个文件变化、约 1520 行新增、968 行删除。已核实的架构相关差异如下：

| 维度 | 本地 `32e9f7d` | 远程 `040da79` | 影响 |
|---|---|---|---|
| 版本 | `18.0.0` | `19.0.0pre1` | 本地档案以 18.0.0 为现状，19.x 仅列为远程待跟进 |
| Python | `>=3.11` | `>=3.12` | Python 3.11 支持在远程开发线被移除；不能据远程改本地元数据 |
| FFmpeg | 文档主张 8.x | 新增 FFmpeg 9 测试/同步 | 枚举、ABI、行为和构建兼容性存在升级面 |
| ABI/构建 | 本地支持 CPython 3.11-3.14 的条件分支 | 远程提交 `99a0aca` 表明移除 Python 3.11、面向 3.12+ abi3 | `setup.py`、wheel matrix 与 Cython 声明需同步审查 |
| 硬件 | 已有 `HWAccel`/CUDA/DLPack | 新增/调整 CUDA 声明与显式 CUDA stream 路径 | GPU 所有权、context、frames context 和平台可用性需继续实测 |
| 内存/生命周期 | 已有输入/输出释放、flush、超时和 buffer 管理 | 多个提交集中修复 codec/container/filter 生命周期与潜在崩溃 | 远程修复应按提交拆分阅读，不能把远程源码直接覆盖本地 |
| API | `OutputContainer.add_stream`、`add_mux_stream`、`VideoFrame` 等 | 大量 `.py/.pxd/.pyi` 一致性修订 | 公开 API 与 Cython ABI 可能同时漂移 |

远程快照中的具体近期提交包括：`040da79 Free the codec ctx when building a stream fails`、`e537231 Check container output's allocations`、`105afd4 Close an output container properly`、`1674029 Check add_stream's args before creating the stream`、`2ec99ed Share one SwsContext per thread`、`99a0aca Drop Python 3.11, build abi3 wheels for 3.12+`、`7e3d950 Release 18.1.0`、`1a755a9 Test with ffmpeg 9.0.1`。这些是后续版本跟踪线索，不属于本地实现。

## 11. 设计优点、可复用边界与风险

### 11.1 已证实的优点

1. **边界清晰**：FFmpeg C ABI 声明集中在 `include/` 与 `.pxd`，Python API 集中在 `av/`，构建/测试/文档分目录管理。
2. **对象模型贴近媒体语义**：Container/Stream/Packet/CodecContext/Frame 五层关系能够表达解码、编码、复用与时间基，不强行把媒体语义压成单一高级抽象。
3. **生命周期意识强**：`close`、`__dealloc__`、buffer 引用、filter graph 引用、超时 interrupt callback、flush 和 trailer 都有明确代码路径；远程近期提交仍以释放和崩溃修复为主，说明这是长期高风险边界。
4. **可组合**：滤镜图、硬件加速、NumPy/Pillow/DLPack、字幕侧数据均作为独立能力接入，而非侵入 Container 主流程。
5. **行为测试密度高**：428 个测试函数覆盖资源生命周期、数据转换、错误、编码器/解码器、硬件、side data 和真实媒体样本。

### 11.2 对系统工程平台的可借鉴边界

- **吸收**：Container/Stream/Packet/Frame 的分层对象模型可作为媒体能力模块的领域边界参考；时间基、side data、格式和 codec context 应保持显式，不把 FFmpeg 状态隐藏在无类型字典中。
- **吸收**：`setup.py` 的“第三方原生依赖集中声明 + `pkg-config`/vendor 两种宿主路径”可作为第三方提供者的依赖边界参考。
- **吸收**：输入/输出、滤镜、硬件和数组互操作均通过明确对象/方法契约连接，适合提炼为独立的媒体处理能力接口。
- **待核**：若平台正式接入 PyAV/FFmpeg，需验证独立进程隔离、崩溃回收、超时、输出大小、临时文件和许可证报告；本仓库本身是原生扩展库，不等于平台安全隔离方案。
- **废弃直接照搬**：不要把 PyAV 的 Cython 对象和 FFmpeg 指针直接嵌入平台主进程；不要把可选的硬件设备、编码器和 FATE 样本当作所有宿主的必备条件；不要把 `pytest.skip` 后的测试数量当作能力已验证。

### 11.3 风险清单

- **阻断级（接入前）**：FFmpeg/原生扩展在主进程内崩溃可能导致宿主整体退出；需要独立进程与可验证的协议/回收方案。
- **重要**：本地与远程已发生 Python 最低版本、FFmpeg 主版本、公开 API、Cython 声明和生命周期修复的系统性漂移；任何升级都必须从独立快照逐提交审计。
- **重要**：`OutputContainer`/`CodecContext`/`FilterContext` 的指针所有权和关闭顺序是 segfault 高发区；新增 wrapper 必须同时维护 `.py/.pxd/.pyi` 和释放路径。
- **重要**：硬件帧、CUDA context、DLPack capsule 和 NumPy view 涉及跨库所有权；错误的生命周期或线程使用可能造成悬挂指针或进程崩溃。
- **重要**：FFmpeg codec/filter/device 可用性取决于编译配置；相同 Python 代码在不同 FFmpeg 构建上可能返回不同能力集。
- **重要**：输入文件、网络 URL、容器 metadata、字幕和 side data 都来自复杂/不可信媒体；调用层必须限制超时、资源、格式和异常传播。
- **备注**：`av.datasets` 能下载测试数据，测试代码也会写 `sandbox/`；正式服务接入不能沿用默认数据目录和隐式全局缓存。

## 12. 结论与后续建议

1. **当前结论**：本地 PyAV 18.0.0 是结构完整、测试覆盖广的 FFmpeg Cython 绑定，核心事实已完成首轮全量建档；本轮没有对源码行为做运行验证。
2. **版本结论**：本地落后 `origin/main` 48 个提交；远程为 `19.0.0pre1` 开发线。独立快照已保留在 `/tmp/PyAV-remote-4780`，本地工作树没有被覆盖。
3. **后续阅读顺序**：若继续研究，先按远程提交顺序阅读 `setup.py`、`av/container/*`、`av/codec/*`、`av/filter/*`、`av/video/*` 及对应 `.pxd/.pyi`，再运行最小输入/输出、编码/解码、滤镜和硬件探针；不要先做全量构建。
4. **接入裁决**：平台若吸收该项目，应优先提炼“媒体对象模型 + 独立 FFmpeg 提供者 + 明确帧/包/时间基契约”，而不是复制整个 `av` 包；原生扩展隔离、许可证、FFmpeg 版本矩阵和宿主能力报告必须先冻结。
5. **待核事项**：远程 `19.0.0pre1` 对本地公开 API 的完整变更表、FFmpeg 9 ABI 兼容性、CUDA/DLPack 在 macOS/不同 GPU 上的真实行为、所有测试样本的可获得性，均未在本轮运行或完全展开，不能写成已完成结论。

## 13. 旧细探逐条吸收裁决

`细探-PyAV.md` 是本项目的旧研究笔记，本轮不删除它；以下裁决把其中有证据的架构事实收口到本文件。后续若旧笔记与源码或本文冲突，以当前源码和本文的证据路径为准。

| 旧细探内容 | 裁决 | 本文收口位置与证据 |
|---|---|---|
| “FFmpeg 的 Pythonic 绑定”，直接访问容器、流、包、编解码器、帧 | **吸收** | 第 0、1 节；`README.md:4,10-14`，`pyproject.toml:5-7`，`av/__init__.py:1-29` |
| `Container / Stream / Packet / Codec / Frame` 五层对象模型 | **吸收并精化** | 第 1、5、6 节；当前源码中 `Container`、`Stream`、`Packet`、`CodecContext`、`Frame` 分别位于 `av/container/core.py:229`、`av/stream.py:88`、`av/packet.py:216`、`av/codec/context.py:231`、`av/frame.py:14`。本文将执行链明确为 `Container → Stream → Packet → CodecContext → Frame`，避免把 `Codec` 查询对象与实际状态持有者 `CodecContext` 混同。 |
| 视频/音频解码、转码、封装 | **吸收** | 第 2、6.1、6.2、7 节；`InputContainer.demux/decode`、`OutputContainer.add_stream/mux` 和 `CodecContext.encode/decode` 的源码调用链已列明。 |
| 帧与 NumPy/Pillow 互操作 | **吸收** | 第 1、5.3、6.5、7、8.1 节；`VideoFrame`/`AudioFrame` 的 `to_ndarray`、`from_ndarray`、`to_image` 及其可选依赖边界已列明。 |
| 硬件加速解码 | **部分吸收** | `HWAccel`、`CudaContext`、硬件帧下载和宿主能力约束已收口到第 6.4、8.3、11.3 节；只记录源码确有的配置/生命周期路径，不把硬件能力写成所有平台必然可用。 |
| “硬件加速 vs decord 场景选择”及性能暗示 | **未吸收** | 旧细探没有 benchmark、`decord` 源码或当前 PyAV 性能运行证据；第 11.2/12 仅保留“需隔离并实测”的接入边界，不把两者写成性能结论。 |
| FFmpeg 依赖及 LGPL/GPL 受编译配置影响 | **吸收并收紧表述** | 第 8.2、8.3、11.3 节；`setup.py:14-22,78-102,123-140` 证明链接库和 `pkg-config`/`--ffmpeg-dir` 配置路径，许可证结论仍以实际 FFmpeg 构建为准，不把 PyAV 的 BSD-3-Clause 扩展到 FFmpeg。 |
| “第三方发行版归属一个支持库实例” | **作为平台建议吸收，不作为 PyAV 内部事实** | 第 11.2 节；本文将其表达为依赖提供者/隔离边界建议，而不是声称 PyAV 自身实现了平台级发行版管理。 |
| `av/` 核心包、`tests/` 测试、`docs` API 路线 | **吸收并按真实目录补全** | 第 3、7、9 节；当前目录地图和测试/文档入口均保留源码路径，未将旧笔记的简略路线当作完整模块清单。 |
| BSD-3-Clause 可借鉴 | **吸收许可证事实，未吸收法律结论** | 第 0、8.3、11.2 节；仅记录项目许可证和需单独核对 FFmpeg 组件边界，不据此替使用者作法律意见或直接复制许可结论。 |
| “无 LLM 提示词（纯媒体处理库）” | **未吸收** | 这是旧笔记的范围备注，不属于 PyAV 架构契约；本文以实际 Python/Cython/FFmpeg API 为研究边界。 |

因此，旧细探中有源码支持的定位、对象模型、媒体处理能力、互操作、依赖和目录线索均已并入本文；没有运行或对比证据的 `decord` 性能判断、平台级发行版管理推断和 LLM 提示词备注不作为架构事实。旧文件继续保留，供历史追溯，不再单独维护。

## 14. 本轮操作收口

- **允许修改范围**：仅项目根 `ARCHITECTURE.md`。
- **实际修改**：仅新增/写入本文件。
- **明确未做**：未删除 `细探-PyAV.md`；未修改 `av/`、`include/`、`tests/`、`docs/`、`examples/`、`scripts/`、`setup.py`、`pyproject.toml`、`Makefile` 或配置；未安装、启动、构建、运行测试、提交或推送。

## 15. 第三轮：通用底座映射与唯一归属裁决

本节是本项目的第三轮研究结果。第一轮回答“PyAV 本身是什么”，第二轮已经把对象、调用链、资源和风险展开；本轮只回答“哪些事实可以进入系统工程平台、应由哪一层唯一持有、哪些事实必须隔离”。以下是平台接入裁决，不把候选落点写成当前平台已经存在的实现；没有需求登记、能力搜索、复用裁决、验收契约和装配计划，不据此直接修改平台生产代码。

### 15.1 总裁决：媒体模块负责语义，支持库负责原子能力，独立提供者负责原生执行

```text
业务/项目适配层
        │  只绑定格式、路径、权限、版本和业务参数
        ▼
媒体模块（唯一领域编排入口）
        │  统一 Container/Stream/Packet/Frame 语义、时间基、错误和结果
        ▼
支持库公开能力（一个能力 id 一个契约 owner）
        │  能力调用、资源监督、超时/取消、结果大小和版本边界
        ▼
独立 FFmpeg/PyAV 提供者（独立进程）
        │  子进程内 import av、Cython 扩展、NumPy、Pillow、FFmpeg
        ▼
FFmpeg 动态库、编解码器、滤镜、硬件设备和宿主驱动
```

**唯一归属表**：

| 能力/对象 | 唯一归属 | 允许暴露给上一层的形状 | 明确禁止 |
|---|---|---|---|
| `Container`、`InputContainer`、`OutputContainer` | 独立提供者内部的容器会话；模块只拥有媒体会话句柄/请求 id | `打开`、`读取包`、`写入包`、`关闭`的协议结果和诊断 | 把 PyAV `Container` 对象、`AVFormatContext*` 或 `AVIOContext*` 穿过进程边界；模块自行 `av.open` |
| `Stream`、`VideoStream`、`AudioStream` | 独立提供者内部的流绑定；媒体模块拥有稳定的流描述 | `stream_id`、媒体类型、codec、time base、尺寸/采样率、元数据的不可变描述 | 业务保存 `Stream` Python 对象；多个模块各自维护一套 stream index/时间基映射 |
| `Packet` | 支持库的“编码包传输/时间基”原子能力，由提供者实际创建和释放 | 有界的二进制包、`pts/dts/duration/pos/time_base/keyframe` 和 stream id | 以裸 `bytes` 丢掉时间基；把同一个 `AVPacket*` 借给多个 owner；模块改写 provider 内部 packet |
| `Codec` 查询对象 | 支持库的 codec 能力发现能力，实际查询在提供者内执行 | codec 名称、媒体类型、能力位、可用 profile/格式/hardware config | 把一次宿主探测结果当作永久能力；业务自己扫描 FFmpeg codec |
| `CodecContext` | 独立提供者的有状态编解码会话 | `创建解码器/创建编码器`、`decode`、`encode`、`flush` 的协议结果 | 在媒体模块复制 send/receive 循环；让一个 context 被多个并发请求共享；把 context 生命周期交给 Python GC 的偶然时机 |
| `Frame`、`VideoFrame`、`AudioFrame` | 媒体模块的领域结果模型 + 提供者内的原生帧实体；二者必须分开 | 有界的帧描述、像素/采样格式、时间基、平面或临时文件引用、side data | 将 `AVFrame*`、NumPy view、Pillow `Image` 或 DLPack capsule 直接返回主进程 |
| 解码/编码封装 | 支持库原子能力（解码、编码、flush），媒体模块编排顺序 | 稳定错误码、帧/包批次、可重试和资源状态 | 每个业务实现自己的 `send_packet/receive_frame` 或 `send_frame/receive_packet` 循环 |
| mux/demux、header/trailer | 媒体模块的输入/输出流程契约；FFmpeg 调用归独立提供者 | `open → configure → write_header → mux → flush → trailer → close` 状态 | 将 `close` 当作普通析构；重复 `av_write_trailer`；header 写出后再改变结构字段 |
| NumPy/Pillow 互操作 | 独立提供者的可选适配能力；媒体模块只约定数组/图像交换格式 | dtype、shape、stride、色彩空间、媒体类型、图像字节或临时文件引用 | 主进程按需 import 这些 C 扩展；默认假定 NumPy/Pillow 一定安装；无视 view 的底层 frame 生命周期 |
| FFmpeg 原生扩展、Cython `.py/.pxd/.pyi` | 独立提供者的实现和构建边界 | provider 版本、FFmpeg 版本/许可证、宿主能力报告 | 把 `.pxd` 当平台公共契约；平台源码 `cimport` PyAV；跨模块复制 C 指针释放逻辑 |
| 硬件加速、CUDA/DLPack、device/frame context | 独立硬件提供者（仍受媒体支持库契约监督） | 设备类型、能力探测、是否软件回退、上传/下载结果、设备错误 | 主进程持有 CUDA/FFmpeg context；把宿主有 GPU 写成全局可用；跨进程传未拥有的 capsule |
| `Graph`/`FilterContext` | 媒体模块的滤镜流程能力，图和 filter context 实体仍在提供者内 | 有限拓扑声明、输入/输出帧批次、EOF/flush | 业务直接拼 C filter graph；每个业务维护不同的滤镜 EOF/排空语义 |

这里的“媒体模块拥有领域结果”不等于模块拥有 FFmpeg 指针：模块可以拥有规范化后的 `MediaStream`/`MediaFrame` 数据和流程状态，但原生句柄、底层 buffer、codec context、滤镜图、硬件 context 的 owner 永远是一次独立 provider 会话。这样既保留 PyAV 五层媒体语义，又不把 Cython/FFmpeg 的崩溃半径带入平台主进程。

### 15.2 PyAV 五层对象如何映射为平台契约

1. **`Container` 是会话根，不是业务数据**。`av/container/core.py:228-491` 保存 `AVFormatContext`、文件/IO、选项、超时和打开文件表；它应映射为支持库的“媒体会话”能力。模块只能拿到不可伪造的 `session_id` 和容器描述，所有后续操作必须带会话租约/请求上下文。
2. **`Stream` 是容器内的稳定引用**。`InputContainer.__cinit__`（`av/container/input.py:25-106`）为每个 `AVStream` 创建 decoder context 并调用 `wrap_stream`；它应映射为模块层 `MediaStream` 描述，固定 `stream_id/index/type/time_base/codec`。`stream index` 只能在提供者会话内解释，不能让业务跨容器复用。
3. **`Packet` 是有时间基的传输单元**。`InputContainer.demux`（`av/container/input.py:136-225`）复用一个读取包，然后用 `av_packet_move_ref` 把所有权移动到新 `Packet`，末尾还产生用于 flush 的 dummy packet。平台契约必须保留“移动/转移”语义：输出包要么被 mux 消费，要么由调用方显式释放；不能把 borrowed packet 当 owned packet。
4. **`CodecContext` 是有状态状态机**。`av/codec/context.py` 的 `wrap_codec_context` 将 `AVCodecContext*` 包成按音频/视频/字幕分派的 Python 对象；`encode/decode` 使用 FFmpeg send/receive API，`None` 是 flush 信号。平台必须把 `created → configured → opened → processing → flushing → closed/failed` 固定为能力状态，不允许请求之间共享未声明的状态。
5. **`Frame` 是领域结果但不是可任意转移的指针**。`VideoFrame`/`AudioFrame` 同时含时间戳、格式、plane、side data 和底层 buffer；转 NumPy/Pillow/DLPack 后仍可能借用原 frame。媒体模块可把它规范化为 `MediaFrame`，但应在 provider 内完成 copy/download/编码，或以受控临时制品引用交回，避免悬挂 view。

因此，`Container → Stream → Packet → CodecContext → Frame` 保留为**媒体模块的可观测语义链**，不保留为**平台主进程的对象图**。平台契约可记录每一层的 id、状态、时间基和诊断，但不传递 PyAV 对象本身。

### 15.3 解码、编码、封装的唯一调用链

**解码单链路**：

```text
媒体模块.解码
  → 支持库.媒体解码（创建/租约/监督 session）
  → FFmpeg 提供者.打开输入
  → demux: AVFormatContext → owned Packet
  → CodecContext.decode: send_packet → receive_frame（循环至 EAGAIN/EOF）
  → provider 内完成 frame copy/reformat/download
  → 媒体模块统一 MediaFrame + time_base + side_data
```

`Packet.decode()`（`av/packet.py:216-517`）只能作为 provider 内部实现参考；业务和模块禁止将它复制成自己的循环。`InputContainer.decode()` 只是 `demux()` 后逐包调用 `Packet.decode()`（`av/container/input.py:227-241`），因此平台能力应只有一个解码 owner，而不是“按业务/格式各一套”。

**编码/封装单链路**：

```text
媒体模块.编码/输出
  → 支持库.媒体编码与封装
  → provider 创建 OutputContainer + Stream/CodecContext
  → configure 全部结构属性
  → write_header（结构冻结）
  → encode(frame) → Packet
  → time_base 重标 → mux(packet)
  → encode(None) / CodecContext.flush
  → 排空 delayed packets
  → av_write_trailer（只允许一次）
  → 关闭 AVIO/文件/子进程，返回制品摘要
```

`OutputContainer.add_stream` 会创建带 codec context 的流；`add_mux_stream` 则明确“不创建 codec context”，只适用于外部已编码包（`av/container/output.py:83-195,197-258`）。这两个语义必须成为同一支持库契约中的显式模式，不能让调用方通过“是否传 codec”自行猜测。`close_output`（`av/container/output.py:40-64`）先处理 buffered packets，再在 started 且未 done 时调用 `av_write_trailer`，并明确无论成功失败都设置 done；这不是可选实现细节，而是防重复 trailer/segmentation fault 的资源协议。

### 15.4 flush、close、trailer 与所有权状态机

| 阶段 | Container owner | Codec owner | Packet/Frame owner | 失败/重复语义 |
|---|---|---|---|---|
| `open` | provider 会话持有 `AVFormatContext`、IO、打开文件表 | 每个流持有自己的 `AVCodecContext`（若存在） | provider 分配临时 packet/frame | 打开失败必须释放已分配的 context、IO 和文件，不返回半会话 |
| `configure` | module 提交格式/流结构 | provider 设置 codec options/hw frames | 输入 frame 仍归请求方，未被 encode 前不能被异步借用 | header 前可改结构；非法 codec/格式在分配后仍必须回收 |
| `write_header` | 输出 container 进入 started | codec context 进入 opened/可编码 | extradata/header 归 container | header 后结构属性冻结；后续修改拒绝而非静默改变 |
| `process` | 会话租约有效 | send/receive 循环可交替执行 | send 后 packet/frame 的所有权按协议转移或复制 | `EAGAIN` 是继续驱动状态，不是业务失败；异常进入 failed 并触发清理 |
| `flush` | 输入 EOF 或输出结束信号 | `decode(None)`/`encode(None)`，持续 receive 直到 EOF/无更多输出 | delayed frames/packets 只能由当前 codec owner 排空 | flush 幂等；不能把一次 flush 当作 close；取消时也要记录是否已排空 |
| `trailer` | 仅 output container 写一次 `av_write_trailer` | 所有 codec 已 flush | mux 缓冲包先消费，不能 trailer 后再写包 | trailer 即使返回错误也标记 done；严禁重复调用 |
| `close` | 关闭 IO、管道、文件、会话租约 | 释放 codec/graph/hw context | 未消费的 packet/frame/side data 全部释放或转为诊断 | 显式 close 优先；析构只做最后防线，不能依赖 GC 顺序 |

特别需要把 PyAV 的两种“关闭”分开：输入 `close_input` 先清空 `streams`，再调用 `avformat_close_input` 使 `ptr=NULL`（`av/container/input.py:13-21`）；输出 `close_output` 处理 mux 缓冲和 trailer，`OutputContainer.__dealloc__` 另行释放复用的 `packet_ptr`（`av/container/output.py:40-81`）。平台支持库的 `关闭会话` 必须同时表达“输入关闭/输出完成/失败回收”三种结果，不能只返回一个布尔值。

**资源所有权铁律**：

- provider 子进程拥有所有 `AV*` 指针、Cython wrapper、第三方 buffer、FFmpeg IO、filter graph、硬件 context；
- 媒体模块拥有会话 id、请求状态、规范化元数据和返回制品引用；
- 请求调用方拥有其提交但尚未被 provider 接受的输入字节/临时文件；一旦协议声明 move/copy，转移关系写入诊断；
- NumPy/Pillow/DLPack 的 view/capsule 不能越过 provider 边界；如需共享，必须先 copy 或由 provider 生成带大小、摘要、格式和 owner 的制品；
- 任何 `close`/取消/崩溃后的再次使用都返回稳定的“会话已关闭/提供者已崩溃”，不得复活半释放对象。

### 15.5 NumPy/Pillow、FFmpeg 原生扩展与硬件加速的归属

**NumPy/Pillow**：它们是互操作适配器，不是媒体领域模型。`VideoFrame.to_ndarray/from_ndarray`、`AudioFrame.to_ndarray/from_ndarray`、`VideoFrame.to_image` 的契约应在支持库登记为可选能力，并由媒体模块决定“需要数组/图像还是原始帧”。NumPy 的 dtype、shape、stride、planar layout 和 Pillow 的 RGB/RGBA/alpha 语义必须一次性规范化；不同业务不得各自修复 `yuv420p`、`nv12`、stride 或通道排列。缺依赖时返回 `PROVIDER_UNAVAILABLE`/稳定“可选提供者不可用”，不能用空数组冒充成功，也不能让缺依赖变成测试 `skip` 后的假绿。

**FFmpeg 原生扩展与 Cython**：`include/*.pxd`、`av/**/*.pxd`、`.py` Cython 源、生成扩展以及 `setup.py` 的 `FFMPEG_LIBRARIES`/`pkg-config`/`--ffmpeg-dir` 全部属于 provider 构建和运行边界。平台支持库只登记能力、版本、宿主依赖、许可证摘要和错误映射；不复制 C ABI 声明，不在公共契约中暴露指针，也不要求业务持有 `.pxd`。同一宿主只允许一个受管 FFmpeg provider 版本进入一个 provider 环境，升级走版本兼容与回滚，不允许业务静态链接第二套 FFmpeg。

**硬件加速**：`HWAccel`、`CudaContext`、`AVBufferRef`、hardware frames、`av_hwframe_transfer_data` 和 DLPack 是 provider 内部资源。支持库只负责声明 `hardware_required`、软件回退策略、设备能力、显存/帧数预算和失败码；媒体模块只选择“硬件优先/软件允许/硬件必须”策略。硬件帧在交付数组或图像前必须在 provider 内完成 download/reformat，设备不可用时必须明确返回 host-unavailable 或 capability-unavailable。不能让主进程保留 device context，也不能让一个业务直接把 CUDA stream/capsule 交给另一个业务。

### 15.6 主进程隔离、超时取消与崩溃回收

PyAV 的 Cython/FFmpeg/NumPy/Pillow/硬件组合属于“宿主崩溃半径不可接受”的边界。即使正常路径有 `__dealloc__`、`close`、interrupt callback 和异常闸门，也不能把这些等同于进程级安全隔离；C 扩展的未定义行为、第三方 codec、驱动和解释器退出清理仍可能直接终止主进程。因此本项目到平台的唯一接入方式裁决为：**主进程零加载 PyAV/FFmpeg 原生扩展；所有媒体 provider 在独立子进程运行**。

推荐协议和回收顺序：

1. 支持库管理器用 `subprocess.Popen` 启动固定 provider 入口，`start_new_session=True` 建立独立进程组；主进程只打开受控 stdin/stdout/stderr，不 import `av`、`numpy`、`PIL`。
2. 请求使用有界 JSON 行控制协议；大帧/大包通过受控临时文件或带摘要/大小的二进制制品引用传输，不把无限二进制写进单行 JSON。响应固定包含 `request_id`、成功/错误码、结果摘要、资源状态和可重试性。
3. `timeout` 必须覆盖打开、读取、解码、编码、flush、trailer 和关闭，不只覆盖 socket/read；FFmpeg interrupt callback 是 provider 内的第一层中断，父进程 deadline 是第二层硬边界。
4. 超时/取消先发送协议取消并关闭输入，等待很短的宽限期让 provider 执行 flush/close；仍未退出则对整个进程组发送 `SIGTERM`，再次等待后发送 `SIGKILL`，随后 `wait()` 回收并排干/关闭三条管道。
5. 崩溃、非零退出、无效 JSON、EOF 或管道断裂统一映射为 `PROVIDER_CRASHED`；禁止复用旧 pid、旧 session 或旧句柄。下一次调用新建 provider 会话，并附带上一次退出码/信号、deadline、已清理文件和重启次数。
6. 回收后的验证不是“kill 返回成功”：必须确认进程组不存在、子进程已 `wait`、管道关闭、临时目录为空或已删除、端口/文件锁不存在、共享制品引用已标记失败；必要时从独立观察进程读取 `ps`/句柄/目录现场。
7. 任何后台线程、Future、队列和资源监督器都必须在 provider 退出后收口；超时不依赖 `Future.cancelled()` 判断，而由治理层记录“调用方视角取消已发生”。

该原则也解释了为什么不能用“主进程 try/except + `__del__`”替代隔离：Python 异常只能覆盖可回到 Python 的错误，不能拦住 C 层 segfault、驱动 abort、解释器关闭期析构和进程组中遗留的 codec/IO 线程。

### 15.7 为什么不能让各业务复制一套 FFmpeg 链

复制的表面成本只是多几段 `av.open`/`demux`/`decode`，实际会复制至少九类不可见状态：

1. FFmpeg 版本、编译 flags、codec/filter/device 能力和许可证扫描；
2. Cython `.py/.pxd/.pyi` 与生成扩展的 ABI 配套；
3. Container/Stream/Packet/CodecContext/Frame 所有权和 Python 引用保持；
4. time base、PTS/DTS、seek 后 `flush_buffers` 和 B-frame 延迟语义；
5. encoder `send/receive`、decoder `send/receive`、EAGAIN/EOF 和 flush 排空；
6. header、extradata、mux、trailer 单次调用与文件/IO 关闭顺序；
7. NumPy/Pillow/DLPack 的 stride、copy/view、色彩空间和底层 buffer 生命周期；
8. hardware frames、GPU context、软件回退和宿主驱动故障；
9. timeout、取消、SIGKILL、崩溃重启、临时制品、输出大小和诊断证据。

这些状态一旦按业务复制，就会出现“同一个 mp4 在不同业务得到不同 time base/颜色/尾帧”“某业务忘记 flush 导致尾帧丢失”“某业务重复 trailer 导致崩溃”“一个业务升级 FFmpeg 使另一个业务 ABI 失效”“主进程被某个 codec 拖死”等无法由普通接口测试发现的问题。唯一支持库 owner 可以集中完成错误映射、资源预算、版本矩阵、隔离、回收和验证；媒体模块只组合业务需要的“抽帧/转码/封装/图像导出”等流程。业务若需要新 codec/filter，只提交能力缺口和 provider 版本变更，不复制内核。

### 15.8 第三轮的复用、升级、新建、隔离裁决

| 裁决 | 本项目证据 | 平台落点 | 条件/边界 |
|---|---|---|---|
| **吸收** | 五层对象模型、time base、demux/decode、encode/mux、filter graph、side data 已有源码路径（第 5、6、7 节） | 升级媒体模块的领域契约和支持库能力目录 | 只吸收语义和契约，不吸收 PyAV 对象指针 |
| **升级现有支持库** | `CodecContext.encode/decode`、flush、timeout、buffer 和错误映射已有集中实现 | 在现有能力调用/资源监督/独立进程框架下增加媒体原子能力 | 先查能力 id/契约/占用租约，禁止并列第二套解码器 |
| **新建独立 provider** | `setup.py` 链接七个 FFmpeg 库；Cython、NumPy/Pillow、HWAccel/DLPack 都是宿主相关原生边界 | `PyAV/FFmpeg` 受管 provider + 独立环境/独立进程 | 一 provider 一版本/一环境/一健康检查；主进程零加载 |
| **升级媒体模块** | 输入、输出、滤镜、硬件和数组转换是可组合媒体流程，不应落到业务 | 媒体模块统一 `抽帧/解码/编码/封装/重格式化/滤镜` 入口 | 模块只编排公开能力，统一结果、时间基、错误和取消 |
| **隔离** | Cython 未定义行为提醒、远程生命周期/崩溃修复、硬件和 DLPack 所有权风险（第 10、11 节） | 进程组、超时、取消、崩溃重启和残留检查 | 进程隔离是接入前置条件，不是失败后的可选优化 |
| **废弃直接照搬** | PyAV 公开对象和底层指针与平台契约不同；`pytest.skip`/宿主硬件也不能证明通用可用 | 不把 `av` 包嵌入平台公共包，不让业务直连 FFmpeg | 旧业务链保留为迁移对照，不成为第二事实源 |
| **待核** | 本地未运行 build/test；硬件、FFmpeg 版本矩阵和远程 19.x 未完全实测 | 版本兼容、许可证报告、性能/吞吐、GPU provider 具体实现 | 只能进入需求登记和验证工作包，不能标“已接入” |

### 15.9 L0-L4 验证阶梯与验收契约

第三轮不把源码存在、历史测试数量或 provider 自报当作完成。媒体能力进入底座必须按以下等级逐级通过；任一级失败都保留证据并停止向上宣称。

| 等级 | 目标 | 必须验证的真实内容 | 通过证据 |
|---|---|---|---|
| **L0 结构/来源** | 证明映射不是臆测 | 源码路径、`.py/.pxd/.pyi` 对齐、`setup.py` FFmpeg 库、公开 API、`AGENTS.md`、测试文件和许可证/版本基线 | 静态路径表、对象/调用链/资源表、未确认项清单；不计为行为通过 |
| **L1 契约/纯边界** | 固定唯一归属与错误形状 | 能力 id 唯一；Container/Stream/Packet/CodecContext/Frame 描述；time base；输入输出模式；缺 NumPy/Pillow/硬件；非法参数；重复 flush/close/trailer；结果大小/超时字段 | 独立契约测试；失败必须是稳定错误码/状态，不以异常文本猜测 |
| **L2 真实最小链路** | 证明 provider 真执行 | 独立子进程打开小型输入、demux、decode、输出帧；编码、mux、flush、trailer、close；NumPy/Pillow 可选链；输入/输出 file-like 与临时文件 | `Popen` 真实退出码 0；输出可再次打开并核对流/帧/尾帧/时间基；无未关闭管道/临时文件 |
| **L3 故障与资源治理** | 证明不把原生故障带入主进程 | provider 缺失、FFmpeg 错误、读取/编码超时、主动取消、阻塞 flush、非零退出、SIGKILL、无效 JSON、重复关闭、硬件不可用/回退、超大输出 | 父进程仍存活；killpg 后子进程组消失；`wait` 完成；管道/锁/临时目录/端口清零；重启次数有界且有诊断 |
| **L4 宿主矩阵与发布门禁** | 证明可在目标宿主持续受管 | Python/FFmpeg/Cython/NumPy/Pillow 版本矩阵、CPU 与硬件路径、真实 codec/filter、并发和长时运行、许可证/依赖清单、回滚 provider 版本 | 每宿主能力报告、环境指纹、可复现命令、退出码、资源现场、性能基线和回滚证据；缺宿主能力明确标 unavailable |

本地当前只能把 L0 的源码档案视为已完成输入；L1-L4 均未在本轮运行，尤其没有把 `make`、`make test`、FATE、硬件探针或独立 provider 回收测试写成已通过。第三轮接入任务的验收契约至少应固定：

- **输入**：路径/URL/file-like 只在 provider 边界读取；大小、格式、协议、超时和取消令牌显式；
- **输出**：`MediaFrame`/`MediaPacket` 或制品引用必须携带 stream id、time base、PTS/DTS、格式、大小、摘要和所有权状态；
- **状态**：`opened/configured/started/flushing/trailered/closed/failed/cancelled` 可观察且不可逆复活；
- **错误**：区分参数非法、格式不支持、provider 不可用、宿主能力缺失、超时、取消、崩溃和输出超限，并标可重试性；
- **释放**：成功、业务失败、取消/超时、provider 崩溃四条路径都可读回资源现场；
- **版本**：FFmpeg/PyAV/Cython/NumPy/Pillow/驱动版本进入环境指纹，变更需要重新跑至少 L2-L4 相关等级；
- **装配**：先登记需求→搜索现有能力→唯一归属裁决→申请占用租约→冻结契约→生成装配计划→执行分级验证；没有这条记录不得新增第二个媒体入口。

### 15.10 第三轮结论与剩余风险

1. **唯一归属已裁决**：媒体语义和流程归媒体模块；解码、编码、封装、时间基、帧包转换等原子能力归支持库；PyAV/Cython/FFmpeg/NumPy/Pillow/硬件归独立 provider；主进程只保留契约数据和受控会话状态。
2. **主进程隔离是硬门槛**：PyAV 当前实现虽有 `close`、`__dealloc__`、interrupt callback、flush 和 trailer 防护，但这些是库内生命周期治理，不是跨第三方原生边界的崩溃隔离。
3. **不能复制 FFmpeg 链**：复制会复制 ABI、时间基、flush/trailer、buffer、GPU、超时和回收状态，最终形成无法审计的多套媒体内核；后续业务只能调用唯一媒体模块/支持库入口。
4. **真实验证尚缺**：本轮没有构建或运行 PyAV，未验证本机 FFmpeg 动态库、NumPy/Pillow、硬件、DLPack 和 Cython 退出清理；L1-L4 属于后续接入工作包，不得提前宣称通过。
5. **MCP 证据缺口**：本轮 `project_context` 调用因 `project_toolkit` 服务连续不可达失败；随后 `codegraph_explore` 明确返回目标项目不存在 `.codegraph/`，代码图不可用。因此本轮以目标文件和源码静态读取为事实来源，未把 MCP 缺失伪装成成功；反馈/验证结果见第 16 节。

## 16. 第三轮操作收口与验证记录

- **开工 id**：`PyAV 第三轮通用底座映射与唯一归属裁决`（MCP `project_context` 未返回实例 id）。
- **MCP 实例**：`system_engineering_toolkit` 请求链路不可达；实际工具端报告为 `project_toolkit`，存在专属 MCP 名称与运行时工具名不一致/不可达风险。
- **项目根**：`~/Documents/Agent/github 源码参考/30_多模态与媒体分析/05_video_decode_sampling/PyAV`。
- **代码图**：不可用；`codegraph_explore` 返回未发现 `.codegraph/`，按工具要求不重复调用。
- **反馈**：本轮待调用五字段 `mcp_feedback`；反馈内容必须如实包含“project_context 不可达、代码图缺失、静态取证完成、L1-L4 未执行、未修改源码”。
- **修改文件**：仅 `ARCHITECTURE.md`；未删除 `细探-PyAV.md`，未修改源码、配置、依赖、测试、README 或 Git。
- **文档验证命令**：`python3 - <<'PY'` 读取本文，检查第三轮标题、`L0`-`L4`、`Container`、`CodecContext`、`flush`、`trailer`、`NumPy`、`Pillow`、`Cython`、`killpg` 和“不能复制”裁决均存在，并输出文件大小/行数；退出码 0 才算文档结构验证通过。
- **源码/项目测试**：未执行 `make`、`make test`、pytest、lint、FATE、构建或硬件探针；因此不存在可报告的项目测试通过退出码。
- **剩余风险**：MCP 服务/项目上下文未绑定、代码图未建立；L1-L4 未执行；本地 FFmpeg/硬件/可选依赖/许可证矩阵和 Cython 退出清理仍待真实验证。

## 17. 第二轮深挖：FFmpeg binding、对象状态、解码、线程、缓冲与释放

本节是第二轮的源码级收口，专门补足第一轮/第三轮中被压缩成概览的 FFmpeg binding、`Container`/`Stream`/`Packet`/`Frame` 对象关系、send/receive 解码状态机、线程边界、缓冲转移、Cython 释放和异常路径。以下结论以本地提交 `32e9f7de15c3ecdddd78cc17b5ed4cdafdd15149` 的当前源码为准；远程 19.x 的修复提交只能作为风险线索，不倒灌成本地事实。

### 17.1 FFmpeg binding 的真实边界：Cython 编译面，不是 Python fallback

| 边界 | 源码事实 | 对调用者的含义 |
|---|---|---|
| 包初始化 | `av/__init__.py:1-29` 先导入 `av._core`，随后导入日志和公开对象 | `import av` 依赖扩展初始化顺序；不能把 `av.*` 当作可脱离 FFmpeg 的纯 Python 包 |
| C ABI 声明 | `include/avcodec.pxd`、`avformat.pxd`、`avfilter.pxd`、`avutil.pxd` 等与 `av/**/*.pxd` 共同声明 FFmpeg 类型/函数；具体实现通过 `cython.cimports` 访问 | `.pxd` 是编译期 ABI 边界，不是平台公共 API；FFmpeg 头文件、动态库和 Cython 版本必须配套 |
| Python API | `av/**/*.py` 是 Cython mode 源码，类由 `@cython.cclass` 生成扩展类型；`.pyi` 只描述静态类型 | 运行时对象带 C 指针和扩展类型状态；不能依赖普通 Python `__dict__`、拷贝或猴子补丁来表达所有权 |
| GIL 边界 | `CodecContext._decode`、`_recv_frame`、`_recv_packet`、`InputContainer.demux` 的 FFmpeg 调用在 `with cython.nogil` 中执行（`av/codec/context.py:538-545,621-649,734-739`；`av/container/input.py:179-225`）；Python IO、日志和超时回调再取得 GIL | FFmpeg 内部计算可释放 GIL，但 Python 调用方仍须遵守对象级并发约束；释放 GIL 不等于同一对象可并发调用 |
| 统一错误闸门 | `err_check`（`av/error.py:293-356`）先处理 callback 中 stash 的 Python 异常，再把负返回码映射为异常；错误还可携带文件名和最后一条 FFmpeg error log | 不能只检查 `res < 0` 或解析异常文本；provider/上层应保留 `errno`、异常类、`filename`、`log` 和是否可重试 |

FFmpeg 的返回值并不都经过同一种语义：主处理调用通常经 `err_check`，析构和清理路径则经常直接调用 `av_*_free/unref/close`，因为释放函数没有可恢复的业务结果；需要特别区分“错误已映射”与“清理尽力完成”。Cython callback 不能直接把 Python 异常穿过 C ABI：`pyio_read_gil`、`pyio_write_gil`、`pyio_seek_gil`、`pyav_io_open_gil` 捕获异常并调用 `stash_exception()`（`av/container/pyio.py:100-114,127-141,157-179`；`av/container/core.py:73-115`），返回 `PyAV` 私有错误码，下一次 `err_check` 再恢复原异常和 traceback。

### 17.2 Container/Stream/Packet/CodecContext/Frame 的引用图与对象契约

```text
Container
 ├─ AVFormatContext* + AVIOContext* / Python IO + open_files
 └─ StreamContainer(list)
     └─ Stream
         ├─ strong ref → Container
         ├─ AVStream*（由 AVFormatContext 所有）
         └─ CodecContext（可能为 None）
             └─ AVCodecContext* + 可选 parser/hw_frames_ctx

InputContainer.demux
 ├─ 一个复用的 read_packet: AVPacket*
 └─ 对命中流的每个输出 Packet：av_packet_move_ref → 新 Packet
     └─ _stream → Stream；time_base ← AVStream.time_base

CodecContext.decode
 └─ Packet → avcodec_send_packet → 多次 receive_frame
     └─ 新的 AudioFrame/VideoFrame/SubtitleSet → AVFrame*
         └─ Plane/SideData/DLPack view 反向持有 Frame 或 AVFrame ref
```

| 对象 | 创建/持有 | 状态与所有权 | 关键异常边界 |
|---|---|---|---|
| `Container` | `Container.__cinit__`（`av/container/core.py:228-345`）分配 `AVFormatContext`，设置 `opaque`、超时回调、Python IO；输入调用 `avformat_open_input`，输出调用 `avformat_alloc_output_context2` | 输入由 `close_input`（`av/container/input.py:13-20`）把 `streams` 清空并调用 `avformat_close_input`，使 `ptr=NULL`；输出由 `close_output`（`av/container/output.py:40-64`）处理缓冲、trailer、IO | 关闭后属性普遍由 `_assert_open` 抛 `AssertionError`（`core.py:388-391`）；`InputContainer` 与 `OutputContainer` 的关闭语义不是同一条 C 路径 |
| `Stream` | `wrap_stream`（`av/stream.py:50-84`）要求 `AVStream` 已完整构造；`Stream._init` 保存 container、`AVStream*`、codec context 和 metadata | `Stream` 强引用 `Container`，`Container.streams` 又强引用 `Stream`，形成 GC cycle；`Stream` 不拥有 `AVStream*`，它随容器释放 | 无 decoder/encoder 时 `codec_context=None`；`_assert_has_codec_context` 先转为稳定 FFmpeg 异常，避免空指针 segfault（`av/stream.py:131-137`） |
| `Packet` | `Packet.__init__`（`av/packet.py:223-261`）可分配 FFmpeg buffer，或用 `AVBufferRef` 直接引用 Python `bytes`/buffer | `Packet.__dealloc__` 调 `av_packet_free`（`packet.py:227-229`）；`_stream` 是 Python 引用；时间戳和 `time_base` 随包保存 | `decode()` 依赖 `_stream`；`rescale_ts` 要求 `AVRational` 且拒绝零 time base；`stream_index` 越界在 mux 时转 `ValueError` |
| `CodecContext` | `CodecContext.create` 分配 `AVCodecContext*`；容器为每个可找到的 decoder 分配并包装；`wrap_codec_context` 按媒体类型选择具体子类 | `is_open` 只表示 `avcodec_open2` 成功；析构先释放 extradata，再 `avcodec_free_context`，另关 parser（`context.py:425-430`） | decoder 的 `time_base` 访问被拒绝；重复 `open(strict=True)` 是 `ValueError`；打开失败不把 `is_open` 置真 |
| `Frame` | `_alloc_next_frame` 为解码分配具体音视频帧；`Frame.__cinit__` 调 `av_frame_alloc` | `Frame.__dealloc__` 调 `av_frame_free`；`Plane` 保存 `frame` 引用；side data 容器延迟创建；`make_writable` 可能触发 FFmpeg copy-on-write | `pts/dts` 可为 `None`；flush 产生的 frame 不由 dummy packet 设置 time base；硬件 frame 不支持 Python buffer protocol |

`Stream` 的属性透传只存在于视频/音频/字幕子类的 Python/Cython 方法中：`VideoStream.encode/decode`（`av/video/stream.py:23-61`）、`AudioStream.encode/decode`（`av/audio/stream.py:19-54`）先检查 codec context，再把编码包回填 `_stream` 和 `stream_index`。因此 `add_mux_stream` 明确得到“只有 mux、没有 codec context”的流；对它调用 `encode` 应为 `EncoderNotFoundError`，输入端无 decoder 则为 `DecoderNotFoundError`，测试证据在 `tests/test_decode.py:56-82`。

### 17.3 解码 send/receive 状态机、flush、seek 与部分输出

真实解码链不是“一包对应一帧”，而是一个有内部缓冲和延迟的状态机：

```text
CodecContext.decode(packet | None)
  → open(strict=False)（首次调用懒打开）
  → avcodec_send_packet(packet.ptr 或 NULL)
  → receive_frame 循环
       ├─ 成功：_transfer_hwframe → _setup_decoded_frame → append
       ├─ EAGAIN：本次输入暂时没有更多帧，返回当前列表
       ├─ AVERROR_EOF：flush 后已无更多帧，返回当前列表
       └─ 其他负值：err_check；若此前已有帧且是 InvalidDataError，则保留已产出帧
```

源码证据：`CodecContext._decode`（`av/codec/context.py:708-753`）发送一次 packet/NULL 后循环 `_recv_frame`；`_recv_frame`（`context.py:613-632`）将 EAGAIN/EOF 视为本轮停止而非异常；`_decode` 只对“已有输出 + 后续 `InvalidDataError`”做保留输出处理（`context.py:741-750`）。这解释了 `tests/test_codec_context.py:237-308` 的断言：同一个 packet 里“有效 FLAC frame + 坏字节”仍返回有效 frame；只有全坏输入才抛 `InvalidDataError`。

| 操作 | 状态变化 | 不应误读为 |
|---|---|---|
| `decode(packet)` | 将 packet 送入当前 context，并尽可能排空可立即得到的 frame | 不是一包一帧；返回空列表不等于输入无效 |
| `decode(None)` | 发送 NULL，驱动 codec 排空 delayed/B-frame 缓冲；可重复尝试到 EOF/空列表 | 不是释放 context，也不是 `close` |
| `flush_buffers()` | 直接调用 `avcodec_flush_buffers` 丢弃内部 codec 缓冲（`context.py:755-765`） | 不是把 delayed frame 排出；seek 后是丢弃旧位置状态 |
| `Container.seek` | `av_seek_frame` 成功后调用所有 stream codec context 的 `flush_buffers`（`input.py:280-317`） | 不保证精确落到目标帧；默认向前找 keyframe，随后仍需 demux/decode 到目标 |
| parser `parse(None/empty)` | `av_parser_parse2` 以空输入 flush parser；输出 packet 数据立即复制 | 不是 decoder flush；parser 未完成的 packet 不应借用 FFmpeg 临时 buffer |

`CodecContext.pxd:51-58` 明确写出“不能只 send 不 receive”：某些 `_prepare_frames_for_encode` 可能把一个输入扩成多个 frame，FFmpeg send/receive buffer 也可能有限，因此每次 send 后必须尽量 receive。编码侧对称地走 `_send_frame_and_recv`（`context.py:538-550`），`encode(None)` 是 encoder flush；`encode_lazy` 才把 packet 逐个 yield，而默认 `encode`/`decode` 返回 list，会把本次可用结果先聚集到 Python 容器。

时间基不是附带元数据，而是状态的一部分：输入 demux 把 `AVStream.time_base` 写入 `Packet`（`input.py:197-210,213-219`）；正常 decode 把触发 packet 的 time base 写入 frame（`context.py:768-775`）；flush 的 NULL 没有真实 packet，因此源码 TODO 明确承认不能从 dummy packet 取 time base，测试 `tests/test_decode.py:235-263` 也断言 flush frame 的 `time_base is None`。编码时 `_prepare_and_time_rebase_frames_for_encode` 会把 frame 时间重标到 codec time base（`context.py:654-679`），输出 packet 再标记 codec time base（`context.py:697-706`）；mux 前还会按目标 stream time base 重标（`output.py:616-635`）。

### 17.4 线程模型：FFmpeg 内部线程 ≠ CodecContext 并发安全

| 层次 | 默认/约束 | 证据与结论 |
|---|---|---|
| codec 内部线程 | `_init` 设置 `thread_count=0`（按 CPU 自动）与 `thread_type=0x02`（frame threading；`context.py:273-289`）；两项只能在 open 前改（`context.py:916-948`） | 这是单个 FFmpeg codec context 的内部解码/编码并行参数，不是 PyAV 帮你建立的 Python worker pool |
| 同一 context 的外部并发 | `CodecContext.decode` 文档明确“not thread-safe”；并发调用同一个 context 会破坏 FFmpeg 状态并可能 segfault；需要每线程一个 context（`context.py:708-723`） | `with cython.nogil` 只允许其他 Python 线程运行，不能消除 context 的状态竞争；平台应按 session/context 串行化或每 worker 独立 context |
| filter graph 线程 | `Graph.threads` 默认为 FFmpeg 自动值；必须在添加 filter 前设置，否则 `RuntimeError`（`av/filter/graph.py:33-48`）；现有测试 `tests/test_filters.py:262-265` 只验证 `threads=4` 的正常图路径 | graph thread count 与 codec thread count 独立；未发现同一 Graph 并发 push/pull 的安全声明 |
| Python IO 回调 | `pyio_read/write/seek` 在 `nogil` C callback 中重新取得 GIL 调 Python file-like（`av/container/pyio.py:90-179`） | 自定义 IO 仍受 Python 对象线程安全、阻塞和回调异常影响；FFmpeg 计算释放 GIL 不代表 file-like 可并发访问 |
| FFmpeg 日志 | `logging` 文档警告 Python 日志在多线程流程中可能不理想（`av/logging.py:19-34`）；实现用 `skip_lock` 保护全局重复日志/错误状态，`Capture(local=True)` 按线程 id 收集，`local=False` 收集所有线程（`logging.py:172-205,266-315`） | 日志捕获有线程范围语义；错误 `log` 是“最后一条”竞争下的诊断线索，不应当作严格请求级事件序列 |

源码没有为 `CodecContext.encode/decode`、`Container.demux/seek` 或 `Graph.push/pull` 建立通用 Python 锁。第二轮的可执行边界因此是：**同一个 `CodecContext`、`Container` 或 `Graph` 的操作由一个拥有者串行驱动；需要多线程时复制会话/上下文，而不是共享 C 指针**。测试源码仅覆盖 filter 内部线程参数和日志 capture 线程范围，没有覆盖“同一个 context 并发 decode”的负向压力或 sanitizer 证据。

### 17.5 缓冲、借用、复制与跨框架 view

1. **demux 读缓冲**：`InputContainer.demux` 预分配一个 `read_packet`，每轮先 `av_packet_unref`，调用 `av_read_frame` 后把命中流的内容用 `av_packet_move_ref` 移到新的 `Packet`（`input.py:179-210`）。因此调用者拿到的是 owned packet；循环末尾为每个选中 stream 额外 yield 一个无数据 dummy packet 用于 decoder flush（`input.py:213-219`）。
2. **mux 写缓冲**：`OutputContainer._mux_one` 先把调用方 packet `av_packet_ref` 到容器复用的 `packet_ptr`，再把该引用交给 `av_interleaved_write_frame`（`output.py:616-635`）。调用方 packet 的 Python 对象仍可继续存在，但 mux 过程会按 FFmpeg 规则消费/清空容器侧引用；不能把 packet 当不可变值对象随意跨线程复用。
3. **Python bytes → Packet**：`Packet(input)` 把 `ByteSource` 的指针装进 `AVBufferRef`，先 `Py_INCREF(source)`，释放回调 `_python_free` 再 `Py_DECREF`（`packet.py:203-211,223-261`）。这是“借用源 buffer 但用 FFmpeg ref 维持 Python 生命周期”，不是立即复制；若调用者需要独立可变包，应显式构造/复制。
4. **ByteSource**：`ByteSource` 对 bytes/bytearray 直接取指针，对 memoryview 使用 `PyObject_GetBuffer`，析构时 `PyBuffer_Release`（`buffer.py:14-40`）。`Buffer.update` 只在长度完全相等且可写时 memcpy；长度不等或硬件 plane 写入会抛 `ValueError`/`TypeError`。
5. **Frame/Plane**：`Plane.__cinit__` 保存父 `Frame` 引用（`plane.py:12-14`），所以 Python buffer/memoryview 仍在时父 frame 不会因单纯引用计数消失。`VideoPlane` 对负 linesize 调整 buffer 起点；硬件 frame 在 `__getbuffer__` 明确拒绝 Python buffer protocol，要求 DLPack 或下载到软件 frame（`video/plane.py:49-88`）。
6. **DLPack**：导出时先 `av_frame_ref` 新建 frame ref，并把 shape/strides/`DLManagedTensor` 一起交给 capsule deleter；deleter 释放 AVFrame、shape、strides 和 managed tensor（`video/plane.py:260-373`）。CUDA path 不支持 `stream` 同步，要求 `stream=None` 且调用方先同步（`video/plane.py:111-130`）；这不是零成本、任意线程安全的共享。
7. **opaque/side data**：`Frame.opaque`/`Packet.opaque` 用 `AVBufferRef` 绑定 Python 对象（`frame.py:198-210`；`packet.py:460-472`）；`PacketSideData.to_packet(move=False)` 复制，`move=True` 把所有权置空（`packet.py:104-131`）。

PyAV API 本身没有对 decoded frame list、packet list、filter queue 或单次输出大小设置统一上限；FFmpeg 内部 codec/filter 缓冲取决于 codec、B-frame、filter 和输入。平台接入若要做背压/预算，必须在 PyAV 外层按 packet/frame 数、字节数、临时制品大小和 deadline 设界，不能从“每次 API 返回 list”推断已有资源上限。

### 17.6 释放路径与异常中断：正常、失败、取消/超时、宿主崩溃

| 资源/路径 | 正常完成 | 业务失败/异常 | 取消或超时 | 宿主/解释器崩溃 |
|---|---|---|---|---|
| 输入 `AVFormatContext`/streams | `InputContainer.close` → 清空 Python streams → `avformat_close_input`，ptr 置 NULL | `__dealloc__` 调 `close_input`；构造期失败还依赖对象析构/FFmpeg 自身状态 | 本库 timeout interrupt 让 FFmpeg 返回 `AVERROR_EXIT`，回到 Python 映射 `ExitError`；不覆盖任意后续 codec 操作 | 进程级由 OS 回收；没有库内 finally 能修复 segfault |
| 输出 format/IO/trailer | `close_output` 先 mux `_buffered_packets`，再单次 `av_write_trailer`，必要时 `avio_closep`；无论 trailer 成败设置 done（`output.py:40-64`） | `_mux_one`/buffered flush 本身失败时会在进入 trailer/done 前抛出；这是需测试的异常窗口 | `av.open` 的 timeout 不给编码/flush/trailer 设 watchdog；外层必须终止调用线程/进程或使用独立 provider | `__del__`/`__dealloc__` 不可作为崩溃恢复机制 |
| `AVCodecContext`/parser | `CodecContext.__dealloc__` free extradata/context/parser；显式 API 没有单独 `close` | `open` 失败保持 `is_open=False`；未包装的中途分配异常可能依赖容器/对象回收 | `decode(None)`/`encode(None)` 是 FFmpeg flush，不是超时取消；外层需中止 | 原生崩溃绕过 Python exception |
| Packet/Frame/plane/view | `av_packet_free`/`av_frame_free`；plane 因强引用延后 frame 释放 | Python 异常离开作用域后引用计数/GC 负责，C buffer 由 FFmpeg ref 释放 | 取消时仍需丢弃/关闭未消费的 packet/frame/list；PyAV 不提供统一 cancel API | 只能依靠进程回收和外层制品清理 |
| Python IO/自定义 `io_open` | `pyio_close_custom_gil` flush AVIO buffer 并调用原 file.close；`open_files` 删除 entry（`core.py:117-151`；`pyio.py:190-204`） | callback 异常经 `stash_exception` 返回，下一层 `err_check` 恢复；关闭期异常只记录并返回 FFmpeg unknown | 中断回调不会自动让任意 Python `read()` 停止；阻塞 Python callback 仍是宿主线程风险 | 原始文件/外部 socket 的一致性不由 PyAV 保证 |
| GC/cycle | context manager/显式 `close` 是确定路径 | 文档承认 Container/Stream cycle 可能使自动 close 延迟到数千个容器（`docs/overview/caveats.rst:25-35`） | 不应把 `gc.collect()` 当 deadline 清理协议 | 进程退出时析构顺序不确定；输出 close 会检测 underlying file 已 closed 并跳过 trailer（`output.py:49-54`） |

第二轮还发现以下**源码级待复核窗口**，不能写成已修复或已泄漏的运行结论：

- `InputContainer.__cinit__` 在 `av/container/input.py:45-72` 先为 stream options `malloc`/复制字典，随后调用 `avformat_find_stream_info`；`self.err_check(ret)` 位于释放 `c_options` 之前。若该 C 调用返回错误，静态路径显示释放段可能被跳过，需用失败注入/ASAN 或泄漏检查确认。
- `OutputContainer.add_stream`（`av/container/output.py:114-187`）先 `avformat_new_stream`、`avcodec_alloc_context3`，然后才包装成 Python 对象；本地代码没有在两次分配后立即检查所有 NULL，也没有为 `avcodec_parameters_from_context` 异常显式回滚已创建的 stream/context。远程提交 `040da79 Free the codec ctx when building a stream fails`、`1674029 Check add_stream's args before creating the stream` 正好把该区域列为后续版本修复线索，不能反推本地已具备修复。
- `close_output`（`output.py:41-47`）先遍历并 mux `_buffered_packets`，该阶段若异常逸出，尚未清空 streams、写 trailer 或设置 done；下一次显式 close/析构的行为需要故障注入验证。
- `PyIOFile.__cinit__`（`av/container/pyio.py:61-75`）分配 buffer 和 `AVIOContext` 后立即设置字段，未见对 `avio_alloc_context` 返回 NULL 的分支；这是极低层内存耗尽边界，不能靠常规 pytest 覆盖。
- `Container.__cinit__` 的输入 `avformat_alloc_context`、输出 `avformat_alloc_output_context2` 和若干 stream/context 分配依赖 `err_check` 或后续 C API；构造失败时由 Cython 部分初始化对象析构兜底，真实失败注入和 sanitizer 仍缺失。

这些是“静态发现的待核风险”，不是对正常路径的失败断言；正式接入前应以故障注入、ASAN/UBSAN、进程级回收和临时文件现场验证收口。

### 17.7 异常分类与边界矩阵

| 场景 | 本地实现 | 稳定可观察字段/结果 | 第二轮判断 |
|---|---|---|---|
| 未知 codec/demuxer/muxer | `Codec.__cinit__` 抛 `UnknownCodecError`；FFmpeg 错误表把 decoder/encoder/demuxer/muxer not found 映射为 LookupError 系列（`codec.py:101-131`；`error.py:140-168`） | 异常类、`errno`、消息；stream 无 context 时 `DecoderNotFoundError`/`EncoderNotFoundError` | 属于参数/能力缺失，默认不可通过重试同一请求解决 |
| 非法参数/状态 | `av.open` mode/timeout tuple、`seek` 非 int、零 time base、重复 open、已打开后改 thread 参数分别抛 `ValueError`/`TypeError`/`RuntimeError`（`core.py:555-575`、`input.py:280-285`、`packet.py:294-311`、`context.py:396-423,916-948`） | Python 异常类和稳定文本仅作人读；契约应使用场景码 | 不应让调用方通过字符串判断状态 |
| 解码 EAGAIN/EOF | `_recv_frame` 把二者作为“本轮无更多 frame”；滤镜 pull 也让 EAGAIN 作为暂时阻塞（`context.py:621-627`；`filter/context.py:158-168`） | codec decode 返回当前 list；filter 通过 `BlockingIOError`/OSError errno EAGAIN 暴露；flush 后 EOF 可为 `EOFError` | EAGAIN 不是业务失败；需要继续驱动或等待输入 |
| 坏数据 | `err_check` 把 `AVERROR_INVALIDDATA` 映射 `InvalidDataError`/`ValueError`；decode 在已有输出时保留已产出 frame | `errno` + 已返回的 frame；全坏 packet 抛异常 | 部分结果与失败可同时出现，不能事务式假设“抛异常即无输出” |
| Python callback 异常 | callback `stash_exception` → `err_check` 恢复原异常；同一线程已有 stash 时会向 stderr 打印并丢弃旧异常（`error.py:287-325`） | 原始异常 traceback 尽量保留；多次嵌套 callback 不是无限错误队列 | 外层需避免在 callback 中继续调用会触发另一 callback 的 PyAV 操作 |
| 打开/读取超时 | `interrupt_cb` 按 monotonic deadline 返回 1（`core.py:30-54`）；open/find-stream-info 使用 open timeout，demux 的每次 `av_read_frame` 使用 read timeout；测试期待 `ExitError`（`tests/test_timeout.py:55-80`） | `ExitError`/`AVERROR_EXIT`，可带 filename/log | 未覆盖 encode、decode、filter、flush、trailer 和 Python 自定义 read 的统一 deadline |
| 关闭后再用 | input `ptr=NULL`，属性 `_assert_open` 抛 `AssertionError`；output 以 `started/done` flag 防重复 trailer，但部分方法仍应靠状态检查 | 会话已关闭状态，不应复活对象 | 应由上层把 AssertionError/原生异常归一为 session-closed，而不是暴露给业务 |
| 线程错误/原生崩溃 | 同一 CodecContext 并发 decode 明确未定义/可能 segfault；Cython/PyAV 文档也拒绝 own-GIL sub-interpreter | Python 无法可靠捕获 segfault；只能进程退出、信号和外层回收证据 | 这是必须隔离的宿主级故障，不是普通 retryable exception |
| 硬件/跨框架边界 | hardware plane buffer protocol 拒绝；DLPack 仅支持声明的格式，CUDA stream 非 None 拒绝；`CudaContext` 缓存 device/frames refs | `TypeError`/`NotImplementedError`/`ValueError`/FFmpegError；设备 ref 由 `CudaContext.__dealloc__` unref | 能力缺失必须显式 unavailable，不能以空数组或软件成功伪装 |

### 17.8 第二轮事实表：已实现、仅有测试源码、尚未验证

| 主题 | 源码存在 | 测试源码存在 | 本轮真实执行 | 结论等级 |
|---|---|---|---|---|
| FFmpeg/Cython binding 与错误映射 | `av/__init__.py`、`include/*.pxd`、`av/error.py`、`av/codec/context.py` | `tests/test_errors.py:9-78`、`tests/test_codec_context.py` | 未运行 build/pytest | L0 已证，行为待执行 |
| Container/Stream/Packet/Frame 关系 | `av/container/core.py`、`container/input.py`、`stream.py`、`packet.py`、`frame.py` | `tests/test_decode.py:56-94,222-263`、`tests/test_packet.py:67-104` | 未运行 | L0 已证，部分行为有历史测试但本轮不计通过 |
| send/receive、flush、部分坏包输出 | `context.py:538-753` | `tests/test_codec_context.py:237-308`、`tests/test_decode.py:235-263` | 未运行 | L0/L1 结构与预期已核，L2 未执行 |
| codec/filter 线程设置 | `context.py:286-289,916-948`、`filter/graph.py:33-48` | `tests/test_filters.py:262-265` | 未运行；无同 context 并发负测 | 参数路径有源码/测试，线程安全结论来自文档，L3 缺口 |
| Python IO、timeout、callback exception | `container/pyio.py`、`container/core.py:30-54`、`error.py:287-356` | `tests/test_timeout.py:55-80`、`tests/test_open.py:42-55` | 未运行；未注入 callback 失败/阻塞 read | timeout 正常设计已证，取消/泄漏待核 |
| packet/frame/plane/DLPack 生命周期 | `packet.py`、`frame.py`、`buffer.py`、`video/plane.py:260-373` | `tests/test_packet.py:152-223`、`tests/test_dlpack.py`、`tests/test_videoframe.py` | 未运行；未做 sanitizer/泄漏/崩溃回收 | 所有权路径已静态证，跨框架故障未验证 |
| GC cycle、output trailer、失败清理 | `output.py:40-81`、`docs/overview/caveats.rst:25-35` | `tests/test_open.py:42-55` 仅覆盖未显式 close 的 GC smoke | 未运行；未做故障注入 | 正常/GC 设计可追溯，异常释放窗口明确保留 |
| 硬件路径 | `codec/hwaccel.py`、`video/frame.py`、`video/plane.py` | `tests/test_decode.py:275-399`，依环境 skip | 未运行；macOS 当前硬件矩阵未探测 | 仅源码/条件测试存在，不宣称宿主支持 |

### 17.9 第二轮收口结论

1. **FFmpeg binding 的真正 owner 是 Cython 扩展对象**：`Container`、`Stream`、`Packet`、`CodecContext`、`Frame` 都围绕 `AV*` 指针和 FFmpeg buffer 建立，不存在可替代的纯 Python 语义层；`.pxd` 变更必须视作 ABI 变更。
2. **解码是可排空状态机**：`send_packet → receive_frame*`，EAGAIN/EOF 是驱动信号，`None` 是 flush，seek 后必须 flush；一包不等于一帧，坏包可能“先返回部分帧、再报错”。
3. **线程配置和线程安全是两个问题**：`thread_count/thread_type` 只控制 codec 内部线程；同一 `CodecContext` 并发 decode 明确不安全，必须每线程独立 context/容器，filter graph 也没有通用并发承诺。
4. **缓冲所有权可追踪但不自动变成有界**：demux 用 `move_ref` 转移，mux 用 `packet_ref` 建立容器侧引用，Python bytes 用 `AVBufferRef` 保活，plane/DLPack 用父 frame/ref 保活；调用方仍需建立 frame/packet/字节数上限和背压。
5. **显式 close 是契约，不是优化**：Stream↔Container cycle、输出 trailer 单次约束、Python IO/custom IO、GPU/DLPack 和解释器退出顺序都使 GC 不能充当确定性释放；输入、输出、codec、frame、IO 的关闭路径必须分开建模。
6. **异常边界必须区分可恢复信号与宿主级故障**：EAGAIN/EOF、InvalidData、缺 codec、timeout、callback exception 可以在协议层分类；同 context 并发导致的 segfault、Cython UB、GPU driver abort 无法由 Python `try/except` 兜底，应隔离进程。
7. **本地源码仍有失败路径待核**：`find_stream_info` 选项数组异常释放、`add_stream` 分配/回滚、`close_output` 缓冲 mux 异常、`avio_alloc_context` NULL 和长时间自定义 IO 都需要故障注入/ASAN/进程回收验证；不得因远程修复提交或正常 pytest 路径而宣布已解决。

## 18. 第二轮操作收口与验证记录

- **本轮目标**：深挖 FFmpeg binding、`Container`/`Stream`/`Packet`/`Frame`、send/receive 解码、线程、缓冲、释放和异常边界；未改源码实现。
- **静态取证**：已现场读取 `av/container/{core,input,output,pyio}.py`、`av/codec/{codec,context}.py`、`av/{stream,packet,frame,buffer,error}.py`、`av/filter/{graph,context}.py`、`av/video/{frame,plane,stream}.py`、`av/audio/{frame,stream}.py`、相关 `.pxd` 与边界测试源码。
- **本轮新增/修改**：仅项目根 `ARCHITECTURE.md`，新增第 17、18 节；未修改 `av/`、`include/`、`tests/`、`docs/`、`examples/`、`scripts/`、`setup.py`、`pyproject.toml`、`Makefile`、`README` 或配置；未删除 `细探-PyAV.md`。
- **项目执行**：未执行 `make`、`make test`、pytest、lint、构建、依赖安装、FATE 下载、硬件探针或 sanitizer；因此本文只把源码和测试源码记为 L0/待执行，不宣称项目测试通过。
- **文档验证待执行命令**：对本文做纯文本结构检查，至少检查第 17/18 节、`avcodec_send_packet`、`avcodec_receive_frame`、`thread_count`、`EAGAIN`、`DLPack`、`stash_exception`、`close_output`、`find_stream_info`、`ASAN`、`未运行` 和“只能进程隔离”等关键词；不触碰项目构建或运行依赖。
- **剩余风险**：本地 FFmpeg/Cython 运行 ABI、失败注入、释放泄漏、同 context 并发、长阻塞 Python IO、DLPack/CUDA stream、硬件矩阵、sub-interpreter 和 sanitizer 证据均未在本轮执行验证。

## 19. 第三轮底座映射：FFmpeg/PyAV 封装、资源治理与 L0-L4

本节将前两轮的源码事实收敛成可供底座设计使用的映射表。这里的“底座”是接入系统时的受管媒体执行底座，不是把 PyAV 直接变成平台公共 API；所有结论仍以本地 `32e9f7d` 源码静态证据为准，未运行构建、解码、故障注入或 sanitizer。

### 19.1 FFmpeg/PyAV 封装边界

```text
Python 调用 av.open / Container / Stream / Packet / Frame
                 │
                 ▼
        Cython 扩展对象（.py + .pxd + .pyi）
                 │  err_check / stash_exception / nogil
                 ▼
        FFmpeg C ABI（include/*.pxd）
                 │
                 ▼
 libavformat  libavcodec  libavutil  libavfilter
 libavdevice  libswscale  libswresample
```

- `av/__init__.py` 先加载 `_core`，因此 `import av` 就是原生扩展初始化，而非可降级的纯 Python import。
- `include/*.pxd` 是 FFmpeg 头文件的 Cython 声明；`av/**/*.pxd` 是模块间的编译期类型/调用边界；`.pyi` 只描述静态类型。三者与生成扩展、FFmpeg 头文件和动态库必须同版本配套。
- `setup.py` 集中声明七个 FFmpeg 库，并通过 `pkg-config` 或 `--ffmpeg-dir` 取得 include/library 参数。平台底座应把这整组依赖视为一个不可拆分的 provider 制品，记录 FFmpeg 配置、版本和许可证摘要。
- FFmpeg 调用通常在 `cython.nogil` 中执行，但 Python IO、日志和异常回调会重新取得 GIL；释放 GIL 只表示计算期间可运行其他线程，不表示任何 PyAV 对象可以被并发调用。
- C 回调不能把 Python 异常直接穿过 FFmpeg ABI：`pyio_*_gil`/`pyav_io_open_gil` 捕获异常后用 `stash_exception()` 存在线程局部槽，下一次 `err_check()` 恢复原异常和 traceback。底座协议必须保留“原始回调异常”和 FFmpeg 返回码两层信息。

### 19.2 容器、流、包、解码器和帧的底座映射

| PyAV 实体 | FFmpeg 资源 | PyAV 实际职责 | 底座唯一 owner | 跨边界结果 |
|---|---|---|---|---|
| `Container` / `InputContainer` | `AVFormatContext*`、`AVIOContext*`、打开文件表 | open、find stream info、demux、seek、输入关闭 | provider 会话 | `session_id`、容器描述、状态、诊断 |
| `OutputContainer` | 输出 `AVFormatContext*`、复用 packet、AVIO | add stream、header、mux、trailer、输出关闭 | provider 会话 | 制品引用、流描述、写入统计、完成状态 |
| `Stream` | `AVStream*`（由容器拥有） | index、媒体类型、time base、codec 参数 | 容器会话；模块仅持有描述 | `stream_id/index/type/codec/time_base` |
| `Packet` | owned `AVPacket*` / `AVBufferRef` | demux 产出、codec 输入、mux 输出 | provider；传输时明确 move/copy | 有界包数据或制品引用 + `pts/dts/duration/time_base` |
| `CodecContext` | `AVCodecContext*`、parser、hw frames | send/receive、懒 open、编码/解码状态 | 单 provider 会话、单 owner | 批量帧/包、flush 状态、错误码 |
| `Frame` / `VideoFrame` / `AudioFrame` | `AVFrame*`、planes、side data | 时间戳、格式、平面、重格式化、互操作 | provider 内原生帧；模块拥有规范化值 | `MediaFrame` 描述或受控制品引用 |

关键引用关系是 `Stream → Container` 的强引用、`Packet → Stream` 的 Python 引用、`Plane → Frame` 的父对象保活；`AVStream*` 不独立拥有，`AVPacket*`/`AVFrame*` 则由各自 `__dealloc__` 释放。故平台不能跨进程传 PyAV 对象、C 指针、NumPy view、Pillow Image 或 DLPack capsule，只能传复制后的值或带 owner/大小/摘要的制品引用。

### 19.3 解复用、解码、音视频帧与时间基

输入链是：

```text
av.open
  → avformat_open_input
  → avformat_find_stream_info
  → 为每个可解码 AVStream 创建 CodecContext
  → av_read_frame（复用 read_packet）
  → av_packet_move_ref（产生 owned Packet）
  → avcodec_send_packet
  → avcodec_receive_frame*（直到 EAGAIN/EOF）
  → VideoFrame / AudioFrame / SubtitleSet
```

- `InputContainer.demux()` 每轮复用一个 `AVPacket*`，先 `av_packet_unref`，再用 `av_packet_move_ref` 转移到新 `Packet`；迭代结束为选中流产生 dummy packet，驱动 decoder flush。dummy packet 不是媒体数据，不能作为业务包持久化。
- `CodecContext.decode(packet)` 是“一个输入包，循环接收零个或多个帧”的状态机。一包不等于一帧；B-frame、codec 内部缓冲和帧线程都会造成延迟。
- `decode(None)` 向 `avcodec_send_packet` 发送 NULL，排空 delayed frames；`flush_buffers()` 直接丢弃 codec 缓冲，通常用于 seek 后切换位置，不能与 decoder flush 混同。
- `EAGAIN`/`AVERROR_EOF` 是 receive 阶段的驱动信号，不是自动的业务失败；坏包可能先返回已产出帧，再报告 `InvalidDataError`。平台结果应支持“部分结果 + 失败诊断”并存。
- Packet 的 `time_base` 来自 `AVStream.time_base`，正常解码帧继承触发 packet 的 time base；flush 产生的帧没有真实 packet，`time_base` 可能为空。编码时 frame、codec packet、目标 stream 在不同阶段重标时间基，不能只传裸 PTS/DTS。
- 视频帧的像素格式、宽高、stride、plane、色彩/旋转信息必须随帧描述；音频帧的 sample format、channel layout、sample rate、样本数和 plane 也必须随结果返回。`to_ndarray`/`to_image` 前需在 provider 内完成必要的 copy/reformat/download。

输出链是：

```text
configure stream/codec
  → write_header（结构冻结）
  → encode(frame) → receive_packet*
  → packet 重标到目标 stream time base
  → mux
  → encode(None) 排空 delayed packets
  → av_write_trailer（只允许一次）
  → AVIO close / provider close
```

`add_stream` 创建 codec context；`add_mux_stream` 只创建复用流，不能误当作可编码流。输出 close 先处理缓冲包，再写 trailer；即使 trailer 失败也必须置 `done`，避免重复 `av_write_trailer` 导致 segmentation fault。

### 19.4 线程、句柄与确定性释放

**线程边界**：

1. `CodecContext.thread_count=0` 表示由 FFmpeg 按 CPU 选择线程数，默认 `thread_type=0x02` 为 frame threading；这些参数只能在 codec open 前修改。
2. FFmpeg 内部线程不等于 Python 对象并发安全。源码明确警告同一 `CodecContext.decode` 不能并发调用，可能破坏内部状态并 segfault；多线程必须每线程拥有独立 Container/CodecContext，或在外层串行化。
3. `Graph.threads` 只控制滤镜图内部线程，且必须在添加 filter 前设置；没有同一 Graph 并发 push/pull 的通用安全承诺。
4. 自定义 Python IO 回调重新取得 GIL，可能被用户 `read/write/seek/close` 阻塞；底座不能把“FFmpeg 释放 GIL”当作 IO 可取消或线程安全。

**句柄/资源 owner**：

| 资源 | 创建 | 正常释放 | 异常/取消策略 |
|---|---|---|---|
| `AVFormatContext` / streams | `avformat_alloc/open` | input `avformat_close_input`；output trailer 后 close IO | provider 会话统一回收；不向模块泄漏指针 |
| `AVCodecContext` / parser | `avcodec_alloc_context3` | `avcodec_free_context`、释放 extradata/parser | 分配后任一步失败都要记录并回收；禁止 GC 作为唯一路径 |
| `AVPacket` | alloc/ref/move | `av_packet_unref/free` | 明确 borrowed、owned、moved；取消时清空未消费包 |
| `AVFrame` / plane / side data | `av_frame_alloc`、FFmpeg ref | `av_frame_free`；plane 强引用延迟父帧释放 | view/capsule 存在时不得释放底层 frame |
| custom `AVIOContext` | `avio_alloc_context` | flush、调用 file.close、释放 buffer/context | callback 阻塞由父进程 deadline 处理；关闭异常进入诊断 |
| filter/hardware context | graph/filter/device/frame refs | graph/free、`av_buffer_unref` | provider 退出时整体回收，不共享跨请求 context |
| Python 临时制品/管道 | provider 管理器 | close、wait、删除、现场核验 | timeout/crash 后按 manifest 清理并标记失败 |

`__dealloc__`/`__del__` 是最后防线，不是确定性协议；Container/Stream cycle 会延迟自动释放，解释器关闭期析构顺序也不稳定。底座必须提供显式 `close`，并让 `closed/failed/cancelled/crashed` 成为不可逆状态；关闭后的旧 session、packet、frame、句柄一律返回稳定的 session-closed/provider-crashed 错误。

### 19.5 异常、超时、取消与崩溃隔离

**异常分层**：

- 参数/状态：类型错误、零 time base、重复 open、open 后修改 thread 参数、关闭后使用；映射为稳定 `INVALID_ARGUMENT`/`INVALID_STATE`。
- 能力/媒体：未知 codec/demuxer/muxer、无 decoder、格式不支持、坏包；映射为 `CODEC_UNAVAILABLE`、`FORMAT_UNSUPPORTED`、`INVALID_MEDIA`，不要用异常文本作协议判断。
- 驱动信号：EAGAIN、EOF、flush 结束；作为 `need_input`/`drained` 状态，不应统一映射成失败。
- 环境/治理：可选 NumPy/Pillow 缺失、硬件不可用、超时、主动取消、输出超限；分别返回 `CAPABILITY_UNAVAILABLE`、`TIMEOUT`、`CANCELLED`、`OUTPUT_LIMIT`，并标明可重试性。
- 宿主故障：非零退出、SIGSEGV/SIGABRT、EOF、无效协议响应、管道断裂；统一为 `PROVIDER_CRASHED`，保留退出码/信号和资源现场。

PyAV 的 timeout 只在 `av.open`/`find_stream_info` 和 `demux` 的 `av_read_frame` 路径设置 `interrupt_cb`；它不是 encode、decode、filter、flush、trailer 或任意 Python `read()` 的全链路 watchdog。底座必须采用双层 deadline：provider 内 interrupt callback 作为第一层，父进程 monotonic deadline 作为不可绕过的第二层。

推荐取消/回收顺序：

1. 父进程发送带 `request_id` 的取消，provider 停止接收新输入并尝试关闭当前 IO/flush；取消必须可重复，状态从 processing 只进入 cancelled/failed。
2. 在短宽限期内等待 provider 主动 close；超时则向独立进程组发送 `SIGTERM`，再次超时发送 `SIGKILL`，随后 `wait()`。
3. 排干并关闭 stdin/stdout/stderr，确认进程组无残留、临时目录/文件锁/端口已清理、未完成制品标记失败。不能以 `Future.cancelled()` 或 `kill()` 返回成功代替现场核验。
4. provider 崩溃后禁止复用旧 pid、session、C 指针或句柄；新请求新建 provider 会话，并记录退出码/信号、deadline、取消阶段、清理结果和有界重启次数。

主进程不得 import `av`、FFmpeg 原生扩展、NumPy、Pillow 或硬件驱动；PyAV provider 使用 `subprocess.Popen(..., start_new_session=True)` 运行在独立进程组。try/except、`__del__`、FFmpeg interrupt callback 都不能捕获 C 层 segfault、驱动 abort、Cython UB 或解释器崩溃，因此进程隔离是接入前置条件，而不是故障后的补救优化。

### 19.6 L0-L4 底座验收矩阵

| 等级 | 本轮能证明的内容 | 必须执行的底座验证 | 不可宣称 |
|---|---|---|---|
| **L0 结构/来源** | 目录、源码路径、Cython/FFmpeg 七库、对象图、线程/句柄/异常边界、版本与许可证事实 | 静态路径核对、契约字段表、provider 制品与环境指纹清单 | 不等于能打开或解码媒体 |
| **L1 契约/纯边界** | 唯一 owner、session 状态、packet/frame/time base、错误码、超时/取消字段设计 | 纯契约测试：非法参数、缺能力、重复 flush/close/trailer、结果大小和状态不可逆 | 不等于 FFmpeg 真执行 |
| **L2 真实最小链路** | 目标链路和资源顺序已由源码明确 | 独立 provider 真开小媒体：probe/demux/decode 音视频帧；encode/mux/flush/trailer/close；重开输出核对流、尾帧、PTS/DTS/time base | 不等于故障安全 |
| **L3 故障与资源治理** | 已识别 timeout 只覆盖输入读取、同 context 并发风险、callback 阻塞和 trailer 崩溃窗口 | 阻塞 IO、读取/解码/编码/flush/trailer 超时；主动取消；SIGTERM/SIGKILL；坏协议；硬件失败；超大输出；进程组、管道、临时制品清零 | 不等于宿主矩阵稳定 |
| **L4 宿主/发布** | provider 必须携带版本、FFmpeg config/license 和能力报告 | Python/FFmpeg/Cython/NumPy/Pillow/驱动矩阵、codec/filter、并发长跑、ASAN/UBSAN、许可证审计、性能基线、回滚与重复发布 | 缺少任一宿主证据不得标记 production-ready |

当前档案的静态对象/调用链/所有权映射可作为 **L0 输入**；L1-L4 仍是未执行状态。尤其不能把源码中已有 `tests/test_timeout.py`、`tests/test_decode.py` 或远程生命周期修复提交当作本地 provider 已通过 L2/L3 的证据。

### 19.7 第三轮底座裁决

1. **唯一归属**：媒体模块拥有 Container/Stream/Packet/Frame 的规范化语义和流程；支持库拥有解码、编码、封装、时间基转换、重格式化和治理契约；PyAV/FFmpeg/Cython/NumPy/Pillow/硬件句柄只归独立 provider。
2. **唯一执行链**：所有业务统一调用 `open → probe → demux → decode/encode → flush → mux/trailer → close`，不得按业务复制 send/receive、time base、flush 或 trailer 实现。
3. **句柄不跨边界**：跨进程只传 id、描述、受控字节/制品引用和状态；所有 C 指针、Python buffer view、GPU context、线程局部异常和 FFmpeg IO 留在 provider。
4. **失败可观察**：异常、超时、取消和崩溃都必须有稳定错误码、不可逆状态、可重试性、退出现场和清理结果；部分帧与坏包错误可同时返回。
5. **隔离优先**：正常 close 只能证明库内生命周期路径，不证明原生安全；在 L3 进程组回收和 L4 宿主矩阵通过前，禁止进入平台主进程或宣称生产可用。

## 20. 第三轮新增内容与验证边界

- **本轮新增**：第 19 节，补充 FFmpeg/PyAV Cython 封装边界、Container/Stream/Packet/CodecContext/Frame 映射、音视频帧与时间基、线程和句柄所有权、异常/timeout/cancel/crash isolation，以及 L0-L4 验收矩阵和底座裁决。
- **实际修改**：仅项目根 `ARCHITECTURE.md`；未修改 `av/`、`include/`、`tests/`、`docs/`、`examples/`、`scripts/`、`setup.py`、`pyproject.toml`、`README` 或配置。
- **验证边界**：本轮只做源码和已有架构文档静态研究；未安装依赖、构建 PyAV、运行 pytest、启动 FFmpeg、执行硬件探针、故障注入、ASAN/UBSAN 或进程回收测试。因此新增内容最高属于 L0 设计/来源映射，L1-L4 不计通过。
- **剩余风险**：真实 FFmpeg ABI、分配失败清理、阻塞 Python IO、同 context 并发、输出 trailer 异常、DLPack/CUDA 生命周期、跨宿主能力矩阵和崩溃回收仍需后续独立验证工作包。

## 21. 本轮深度研究：准确项目定位与 PyAV 原生执行边界

### 21.1 路径裁决和研究范围

任务给出的 `~/Documents/Agent/github 源码参考/20_文档解析与IR/2026_06_25_document_json_unification/pandoc/pandoc` 不存在，且该目录不是 PyAV。源码参考库中按 `av/__init__.py`、`setup.py`、FFmpeg Cython 声明和 `tests/` 交叉定位后，准确项目根为：

```text
~/Documents/Agent/github 源码参考/30_多模态与媒体分析/05_video_decode_sampling/PyAV
```

本轮实际读取并交叉核对：

- `README.md`、`AGENTS.md`、`ARCHITECTURE.md`、`细探-PyAV.md`；
- `pyproject.toml`、`setup.py`、`Makefile`、`MANIFEST.in`；
- `av/__init__.py`、`av/container/{core,input,output,pyio}.py`；
- `av/codec/{codec,context,hwaccel}.py`、`av/{stream,packet,frame,buffer,error,logging}.py`；
- `av/audio/*`、`av/video/*`、`av/filter/*`、`av/subtitles/*`、`av/sidedata/*`；
- `include/{avformat,avcodec,avutil,avfilter,avdevice,libav}.pxd` 和相关 `av/**/*.pxd/.pyi`；
- `tests/test_{open,python_io,timeout,decode,encode,codec_context,packet,streams,filters,errors,remux}.py` 及其余测试目录入口；
- `docs/overview/{installation,caveats}.rst`、`docs/api/`、`docs/cookbook/`。

没有修改 `pandoc` 项目，也没有修改 PyAV 的源码、测试、配置、README、细探或其他文件。

### 21.2 Python/Cython/FFmpeg 三层封装事实

PyAV 当前快照的绑定源主要是 `av/**/*.py`，不是通过一个独立的 `src/*.pyx` 树提供 Python fallback。`setup.py:174-205` 遍历 `av/` 下 `.pyx` 和 `.py`，当前目录实际以 `.py` Cython mode 源为主；`.pxd` 是跨模块 Cython 声明，`.pyi` 是静态类型接口，构建时由 `cythonize` 生成扩展。因而：

1. `av/__init__.py` 先导入 `av._core`，`import av` 依赖原生扩展及 FFmpeg 初始化，不应描述为可脱离 FFmpeg 的纯 Python 包。
2. `include/*.pxd` 声明 `libavformat`、`libavcodec`、`libavutil`、`libavfilter`、`libavdevice`、`libswscale`、`libswresample` 的 C ABI；`av/**/*.pxd` 声明模块间对象和指针关系；`.pyi` 不负责运行时所有权。
3. `setup.py` 通过 `--ffmpeg-dir` 或 `pkg-config` 解析头文件、库目录和动态库；未知 linker flags 会阻断构建，静态 FFmpeg 场景明确不支持。
4. Cython 源中的 FFmpeg 计算通常位于 `with cython.nogil`，但 Python IO、日志和异常回调重新取得 GIL。释放 GIL 仅表示计算区间允许其他线程运行，不表示同一 `Container`、`CodecContext` 或 `Graph` 可以并发调用。
5. Python 异常不能穿过 FFmpeg C callback 直接返回。`pyio_read_gil`、`pyio_write_gil`、`pyio_seek_gil` 和 `pyav_io_open_gil` 捕获异常后调用 `stash_exception()`；下一次 `err_check()` 再恢复异常。调用层必须同时保留 FFmpeg 返回码与 callback 原始异常。

### 21.3 Container 到 Frame 的生命周期和 owner

```text
Container
  ├─ AVFormatContext* / AVIOContext* / Python IO / open_files
  └─ StreamContainer
       └─ Stream ──强引用──> Container
            └─ CodecContext ──> AVCodecContext* / parser / hw_frames_ctx

demux 的复用 AVPacket*
  └─ av_packet_move_ref → 调用方拥有的 Packet
       └─ _stream / time_base

CodecContext
  └─ avcodec_send_packet / receive_frame
       └─ Frame ──> Plane / side_data / DLPack view
```

- 输入 `Container.__cinit__` 分配 `AVFormatContext`、设置 `AVFMT_FLAG_GENPTS`、可选 `interrupt_callback` 和 Python IO，然后调用 `avformat_open_input`；`InputContainer.__cinit__` 再调用 `avformat_find_stream_info`，为可找到 decoder 的每个 `AVStream` 分配并包装 `AVCodecContext`。
- `Stream` 不拥有 `AVStream*`，其指针随 `AVFormatContext` 生命周期；它以 Python 强引用保持容器存活。这个引用关系形成 GC cycle，文档明确建议显式 `close()` 或 context manager。
- `Packet` 的独立对象由 `av_packet_alloc/free` 管理；demux 用 `av_packet_move_ref` 把读取缓冲转移给新包。`Packet(bytes)` 则用 `AVBufferRef` 保持 Python 源对象存活，不应误写成必然立即复制。
- `Frame` 基类由 `av_frame_alloc/free` 管理；`VideoFrame` 的专用析构先 `av_frame_unref`，继承的 Cython 对象释放仍需结合基类析构语义理解；`AudioFrame` 另行释放其手工分配的音频 buffer。`Plane` 保存父 Frame 引用，避免 buffer view 先于底层帧释放。硬件 plane 不提供 Python buffer protocol，必须下载为软件帧或使用受限 DLPack 路径。
- `CodecContext.__dealloc__` 释放 extradata、`AVCodecContext*` 和 parser；它没有独立的显式 `close()` API，因此调用方不能把 Python GC 当作实时资源协议。
- 输入 `close_input` 先清空 `StreamContainer`，再 `avformat_close_input(&ptr)` 使 `ptr=NULL`。输出关闭是另一条路径，必须处理缓冲 packet、trailer 和 AVIO。

### 21.4 demux/decode、PTS/DTS 和 time base

输入链的真实顺序是：

```text
av.open
  → avformat_open_input
  → avformat_find_stream_info
  → av_read_frame
  → av_packet_move_ref
  → Packet.decode
  → avcodec_send_packet
  → avcodec_receive_frame* 直到 EAGAIN/EOF
```

`InputContainer.demux()` 每轮复用一个 `read_packet`，先 `av_packet_unref`，再调用 `av_read_frame`。命中筛选流后，内容移动到新的 `Packet`，并将 `AVStream.time_base` 写入 packet。迭代结束时，每个被选中的流额外 yield 一个无数据 dummy packet；这是 PyAV 用于驱动 decoder flush 的接口细节，不是可持久化媒体包。

`CodecContext.decode(packet)` 一次 send 后循环 receive，可能返回零个、一个或多个 frame：

- `EAGAIN` 表示本轮没有更多可立即接收的帧，`AVERROR_EOF` 表示 flush 后已经排空；二者不是同一类业务失败；
- `decode(None)` 向 FFmpeg 发送 NULL，排出 B-frame 或 codec 延迟帧；它不是释放 context；
- `flush_buffers()` 直接丢弃内部缓冲，主要用于 seek 后切换解码位置，不等同于排出尾帧；
- 如果已经产出 frame 后遇到 `InvalidDataError`，当前实现保留已产出部分；因此“异常”与“部分结果”可以同时存在；
- flush 产生的 frame 没有真实 Packet，`_setup_decoded_frame` 无法从 packet 复制 time base，当前测试明确断言其 `time_base is None`。

时间字段必须携带其所属 time base，不能跨层只传裸 `PTS/DTS`：demux 使用 stream time base；编码前把 frame 重标到 codec time base；编码 packet 记录 codec time base；mux 前再重标到目标 stream time base。B-frame、重排序、缺失 timestamp 和 flush 尾帧都要求调用层保留 `pts`、`dts`、`duration`、`time_base`、`stream_index` 和 keyframe 状态。

### 21.5 encode/mux、header、extradata、flush 和 trailer

输出链的真实顺序是：

```text
add_stream / add_mux_stream
  → 配置全部 stream/codec 属性
  → start_encoding
       → codec open
       → avio_open（需要时）
       → avformat_write_header
  → encode(frame)
       → avcodec_send_frame
       → avcodec_receive_packet*
       → mux
  → encode(None)
       → 排空 delayed packet
  → close
       → buffered packet mux
       → av_write_trailer（最多一次）
       → AVIO close
```

- `add_stream` 创建 `AVStream` 和 `AVCodecContext`；`add_mux_stream` 故意不创建 codec context，只适合外部已编码 packet 的复用。二者不能由调用方通过“是否传 frame”猜测。
- 首个 `encode()` 或 `mux()` 会触发 `start_encoding()`。header 写出后，format、尺寸、layout、rate、pix_fmt 等结构字段已冻结，测试覆盖 header 后修改第二流会抛 `RuntimeError`，防止状态损坏。
- `CodecContext.encode(frame)` 对每个待编码 frame 调 `avcodec_send_frame`，然后持续 receive packet；`encode(None)` 是 encoder flush，必须在 trailer 前执行并 mux 所有 delayed packet。
- `OutputContainer._mux_one` 先校验 packet stream index，再将 packet 时间重标到目标 `AVStream.time_base`，通过 `av_packet_ref` 建立容器侧引用，最后调用 `av_interleaved_write_frame`。
- global-header muxer 可能需要从首个 in-band packet 提取 extradata。`OutputContainer` 在 extradata 未确定时缓存 packet，使用 `extract_extradata` bitstream filter，确定后写 header 并冲刷缓存。该缓存没有通用大小上限。
- `close_output` 先 mux `_buffered_packets`，再在 started 且未 done 时调用一次 `av_write_trailer`；无论 trailer 成功还是失败都设置 done，因为重复 trailer 在源码注释中明确可能造成 segmentation fault。若底层 Python IO 已在 GC 期间关闭，代码会跳过 trailer。
- 输出失败窗口仍需故障注入验证：缓存 packet mux 失败可能发生在 trailer/done 之前；底层目标文件是直接写入，PyAV 不提供应用级原子替换或回滚。

### 21.6 线程、回调、超时和异常边界

FFmpeg codec 内部线程由 `thread_count=0`（自动选择）和默认 `thread_type=FF_THREAD_FRAME` 等参数控制，这不等于 PyAV 创建了可共享的 Python worker pool。`CodecContext.decode` 文档明确声明同一 context 并发调用不安全，可能破坏 FFmpeg 状态并导致 segfault；需要并发时应使用每线程独立 container/context 或在外层串行化。`Graph.threads` 只控制滤镜图内部线程，不能推导 Graph 的 Python push/pull 并发安全。

自定义 file-like IO 的 `read/write/seek/close` 回调在 C callback 中取得 GIL，并可能任意阻塞。`interrupt_cb` 使用 monotonic deadline 返回中断信号，但当前 `timeout` 只在输入 `avformat_open_input`/`avformat_find_stream_info` 和 `demux` 的 `av_read_frame` 阶段设置；它不覆盖 Python `read()` 已经阻塞的完整治理，也不为 encode、decode、filter、flush、trailer 或 close 提供统一 wall-clock watchdog。

错误层次应分开记录：

- `EAGAIN`、EOF 和 flush-drained 是驱动状态；
- 缺 codec、坏包、格式不支持、零 time base 和关闭后使用是参数/媒体/状态错误；
- callback Python 异常由 `stash_exception` 延迟恢复；
- timeout 主要表现为 FFmpeg `AVERROR_EXIT` 与 `av.ExitError`；
- Cython UB、FFmpeg/driver abort、segfault 和解释器退出期析构不保证能回到 Python 异常路径。

### 21.7 SIGTERM/SIGKILL 与主进程/provider 隔离：源码没有，接入必须补

PyAV 源码没有 `SIGTERM`、`SIGKILL`、`killpg`、父子 provider 协议或崩溃重启实现。`interrupt_cb` 只是 FFmpeg 调用内的中断回调；`close()`、`__dealloc__` 和 Python `try/except` 也不能捕获原生 segfault、驱动 abort 或进程被强杀。因此以下是**上层接入要求，不是 PyAV 已实现事实**：

1. 主进程不得 import `av`、FFmpeg 原生扩展、NumPy、Pillow 或硬件驱动；PyAV 应放入独立 provider 子进程。
2. provider 由固定入口启动，使用独立进程组；请求协议必须有界，结果只传复制后的 metadata、受控 bytes 或制品引用，不传 `AV*` 指针、Python buffer view、Pillow Image、DLPack capsule 或 codec context。
3. deadline 必须覆盖 open、read、demux、decode、encode、flush、mux、trailer 和 close。先发送协议取消并给短暂 graceful close 窗口；仍阻塞时向整个进程组发送 `SIGTERM`，宽限期后发送 `SIGKILL`，随后 `wait()` 并关闭/排干管道。
4. 回收验收必须观察进程组无残留、子进程已 wait、stdin/stdout/stderr 已关闭、临时目录/文件锁/端口已清理、未完成输出已标记失败。不能以 `kill()` 返回成功或 `Future.cancelled()` 代替现场证据。
5. provider 崩溃后禁止复用旧 pid、session、C 指针和句柄；新请求创建新会话，并记录退出码/信号、取消阶段、清理结果和有界重启次数。

### 21.8 测试、构建和验证状态

README 和 `AGENTS.md` 给出的项目流程是 `source ./scripts/activate.sh`、`make`、`make test`、定向 `python -m pytest tests/some_file.py` 和 `make lint`。`Makefile` 实际会安装/升级 Cython、setuptools、pytest、NumPy、Pillow、ruff、isort、mypy，并且 `fate-suite` 会从 FFmpeg 下载完整样本；这些都不是只读研究可以默认完成的动作。

测试源码覆盖 `test_open`、Python IO、timeout、demux/decode、encode/mux、codec context、packet、streams、filters、errors、remux、DLPack、硬件和音视频格式。它们能证明项目作者定义了行为预期，但在没有执行前不能证明当前机器的 FFmpeg ABI、动态库、样本、硬件或可选依赖可用。尤其 `test_timeout.py` 使用慢 HTTP server 验证 open timeout，不能外推为 encode/flush/trailer 超时；硬件测试按环境变量可能 skip，不能把 skip 当作硬件通过。

**本轮明确未运行验证**：

- 未执行 `make`、`setup.py build_ext`、wheel 构建或安装；
- 未执行 `make test`、任何 pytest、定向 encode/decode/remux/timeout 测试或 doctest；
- 未下载 FATE 样本，未启动真实 FFmpeg 输入、输出、网络或自定义 Python IO；
- 未执行 lint、mypy、Cython 编译器诊断、ASAN/UBSAN、泄漏检测或故障注入；
- 未执行 NumPy/Pillow/DLPack/CUDA/硬件矩阵验证；
- 未执行阻塞 callback、并发同一 context、超时取消、SIGTERM/SIGKILL、进程组残留、临时文件清理或崩溃重启验证；
- 未调用 MCP 或 Hermes。

因此本文本轮新增结论最高是**源码静态研究/L0**。任何“可构建”“测试通过”“超时可取消”“SIGKILL 后无残留”“硬件可用”或“生产安全隔离”的说法均未被本轮验证。

### 21.9 本轮收口

- **准确项目根**：`~/Documents/Agent/github 源码参考/30_多模态与媒体分析/05_video_decode_sampling/PyAV`。
- **唯一修改文件**：项目根 `ARCHITECTURE.md`。
- **未修改文件**：`av/`、`include/`、`tests/`、`docs/`、`examples/`、`scripts/`、`setup.py`、`pyproject.toml`、`Makefile`、`README.md`、`AGENTS.md`、`细探-PyAV.md` 及其他路径。
- **研究裁决**：PyAV 是 Cython 编译的 FFmpeg 绑定；Container/Stream/Packet/CodecContext/Frame 的 owner 和 time base 必须显式建模；demux/decode 与 encode/mux 的 flush/trailer 不能混同；Python IO callback、GIL、线程和 GC 都不是进程级隔离；SIGTERM/SIGKILL、取消和 provider 回收必须由上层独立进程治理补齐。

## 22. 本轮资源与文档质量审计

### 22.1 审计口径

本轮按用户指定的 Python/Cython/ABI、Container、Stream、Packet、Codec、Frame、decode、encode、mux、timebase、callback、tests、build 和 docs 分段读取；先尝试 CodeGraph 的 `codegraph explore "Cython FFmpeg avformat avcodec ..."`，目标仓库没有 `.codegraph/`，工具明确返回不可用，因此调用链证据来自源码全文检索和逐文件静态阅读。没有运行构建、导入扩展或媒体样本，以下结论最高为 L0 静态证据。

### 22.2 资源生命周期结论

| 资源 | 所有权/释放证据 | 审计结论 |
|---|---|---|
| `AVFormatContext`、输入 streams | `InputContainer.close_input` 清空 `StreamContainer`，再调用 `avformat_close_input(&ptr)`；`__dealloc__` 作为兜底 | 正常输入关闭路径明确；`Stream` 强引用 `Container` 形成 GC cycle，显式 `close` 或 context manager 仍是必需契约 |
| 输出 context、IO、trailer | `close_output` 先冲刷 `_buffered_packets`，再最多一次 `av_write_trailer`，最后按条件关闭 AVIO 并设置 `done` | trailer 单次约束和正常 close 明确；缓冲 mux 失败可能发生在设置 `done` 之前，需故障注入确认重复 close 的所有路径 |
| `AVCodecContext`、parser、extradata | `CodecContext.__dealloc__` 释放 extradata、context、parser；`open` 只在 `avcodec_open2` 成功后设置 `is_open` | 正常析构可追踪；没有独立显式 codec close，不能以 GC 作为实时释放或取消机制 |
| `AVPacket`、`AVFrame`、side data | Packet/Frame 有各自 `av_*_free`；demux 使用 `av_packet_move_ref`，mux 使用 `av_packet_ref`；side data 支持 copy/move | borrowed/owned/moved 语义可从源码追踪；返回 list、filter queue、mux extradata buffer 没有统一应用级上限 |
| Python file-like 与 `AVIOContext` | `PyIOFile` 将 Python 方法接入 C callback，异常经 `stash_exception` 延迟到 `err_check`；自定义 close 刷新 AVIO 并调用原对象 `close` | GIL/阻塞/回调异常边界明确；`avio_alloc_context` 返回 NULL 的失败分支在静态代码中未见完整保护，需注入验证，不能直接写成已发生泄漏 |
| Video/Audio plane、NumPy、DLPack | plane 保持父 Frame；硬件 plane 拒绝 buffer protocol；DLPack 建立独立 `AVFrame` ref 和 capsule deleter；AudioFrame 另持有 `_buffer` | view/capsule 的保活关系明确；跨框架路径仍需真实 refcount、异常和同步验证，CUDA `stream` 非空明确不支持 |
| timeout/callback | `interrupt_cb` 使用 monotonic deadline；只在 open/find-stream-info/read-frame 路径设置 timeout；Python callback 可能重新取得 GIL | 输入读取中断不是全链路 watchdog；encode/decode/filter/flush/trailer/close 和阻塞 Python callback 仍须由上层治理 |

### 22.3 静态待核风险与优先级

1. **高优先级：输出分配失败回滚**。`OutputContainer.add_stream` 取得 `AVStream*` 和 `AVCodecContext*` 后，包装对象前的 NULL、参数复制异常和部分构造回滚需要 ASAN/故障注入；远程修复提交只能作为线索，不能替代本地验证。
2. **高优先级：输入 stream options 清理**。`InputContainer.__cinit__` 在 `avformat_find_stream_info` 后调用 `err_check`，随后才释放 `c_options`；错误返回时的释放路径需要注入和泄漏检查确认。
3. **中优先级：自定义 IO 分配失败**。`PyIOFile.__cinit__` 分配 buffer 后调用 `avio_alloc_context`，源码未显示 NULL 分支；需要低内存/失败注入，不能由普通媒体样本覆盖。
4. **中优先级：关闭期异常**。输出缓存冲刷失败时，trailer、`done`、stream 清空和后续析构的组合需要验证；底层目标文件也没有应用级原子替换或回滚保证。
5. **中优先级：并发与取消**。同一 `CodecContext.decode` 明确非线程安全；FFmpeg 内部线程不等于对象并发安全，当前测试没有同一 context 的负向并发和进程级回收证据。
6. **中优先级：测试数据与可选能力**。`tests/common.py` 使用 `sandbox/` 和可下载的 FATE 样本；硬件、Pillow、部分 NumPy/DLPack 场景按环境 skip。源码有测试不等于本机能力已验证，也不等于 skip 后的能力通过。

### 22.4 文档质量审计

**优点**：README、`docs/index.rst`、API 文档和 `docs/overview/caveats.rst` 对项目定位、FFmpeg 组件、显式关闭和 sub-interpreter 限制的主线一致；`ARCHITECTURE.md` 已覆盖对象图、send/receive、time base、flush/trailer、C callback、线程、可选依赖和进程隔离边界。

**本轮校正**：原文第 3 节的“约 170 个 av 文件”和“tests 有 36 个文件”混合了扩展名/目录计数口径，已改为可复现的 `60 .py + 56 .pxd + 51 .pyi`、`34 test_*.py`、`35 docs`、`6 include/*.pxd`；同时把 `VideoFrame.__dealloc__` 的 `av_frame_unref` 与基类 `av_frame_free` 语义分开描述。

**仍需维护的缺口**：

- 文档是研究档案，不是 Sphinx toctree 的正式用户手册；源码/API 改动后，路径和行号引用会漂移，应在版本更新时重跑静态链接检查。
- `Makefile` 会安装或升级依赖，`fate-suite` 会下载大量样本；文档应继续明确这些命令会改变环境或工作树，不能把它们当作无副作用审计命令。
- `tests` 使用 pytest，而项目说明同时包含可选依赖和环境 skip；质量报告必须区分“测试源码覆盖”“本轮执行通过”“环境不可用/跳过”。
- 本文已经有多轮研究节，后续维护应优先更新本节和对应事实表，避免继续复制相同架构结论。

### 22.5 本轮审计收口

- **实际修改**：仅 `ARCHITECTURE.md`；未修改 `av/`、`include/`、`tests/`、`docs/`、`setup.py`、`pyproject.toml`、`Makefile`、README、`AGENTS.md` 或 `细探-PyAV.md`。
- **代码图**：未建立；目标仓库不存在 `.codegraph/`，已按工具返回停止重复尝试。
- **执行验证**：未安装、构建、导入、运行 pytest、下载 FATE、启动 FFmpeg、探测硬件或执行 ASAN/UBSAN；本轮不能宣称 L1-L4 通过。
- **剩余风险**：分配失败清理、关闭期异常、阻塞 callback、同 context 并发、DLPack/CUDA refcount、测试样本完整性和宿主 ABI 矩阵仍待真实验证。
