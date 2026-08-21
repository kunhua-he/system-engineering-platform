# Decord 架构审计

> 本文是当前源码的根架构文档。它记录“代码实现了什么”“调用方如何穿过边界”以及“哪些结论尚未经过运行验证”。不把 README、测试名称或历史 CI 声明当作运行证据。

## 1. 审计范围与证据

审计对象是当前工作树：

```text
~/Documents/Agent/github 源码参考/30_多模态与媒体分析/05_video_decode_sampling/decord
```

覆盖范围：

- Python FFI：Cython/ctypes 选择、参数打包、全局函数发现、异常转换、NDArray/DLPack、bridge。
- C ABI 与 Registry：`c_runtime_api.h/.cc`、`registry.h/.cc`、视频/音频注册入口。
- Reader/Loader：`VideoReader`、`AudioReader`、`AVReader`、`VideoLoader` 与 sampler。
- 解码后端：FFmpeg demux/codec/filter/线程队列，NVDEC parser/decoder、CUDA context/stream/texture、GPU DeviceAPI。
- 数据与生命周期：NDArray Container/view、DLPack deleter、BytesIO、队列、opaque handle、析构路径。
- 测试、构建与文档：`tests/`、`CMakeLists.txt`、CI、`README.md`、`docs/`。

本目录没有 `.codegraph/`，已尝试 CodeGraph 探索但索引不存在；以下定位均来自逐文件源码阅读。当前未安装依赖、未构建、未加载 `libdecord`、未运行 FFmpeg/CUDA/bridge 测试，因此“通过”只表示静态事实闭环。

证据等级：

| 等级 | 含义 | 本仓库状态 |
|---|---|---|
| L0 | 入口、实现和所有权路径在源码中存在 | 通过静态阅读 |
| L1 | 测试源码、夹具和断言可对应当前树 | 部分通过，存在路径/API 漂移 |
| L2 | CMake/CI/README 声明过能力 | 存在，非当前核对执行结果 |
| L3 | 文档与源码交叉核对 | 本文通过 |
| L4 | 当前环境真实构建、导入、执行和释放回读 | 未执行 |

## 2. 项目定位与边界

Decord 是面向机器学习数据准备的视频/音频解码库：Python 提供随机访问、批量采样、音视频切片和框架 bridge；C++ 负责 FFmpeg/NVDEC 解码、采样和数组转换。它不是录制器、分析模型、任务调度器或服务级资源隔离器。

实际依赖边界：

- CPU：FFmpeg/LibAV、`swresample`、DMLC runtime。
- GPU：编译时可选 CUDA/NVDEC/NVML；GPU 路径与 Python 进程同进程运行。
- 数据交换：DLPack ABI、引用计数 NDArray、可选 Torch/MXNet/TensorFlow/TVM bridge。
- 构建：CMake 汇总源码；Python 包通过 `python/decord/_ffi/libinfo.py` 查找动态库。

README 中的 GPU “Done”、shuffle=3、smart shuffle、prefetch 和多 context 均匀分配，不能直接作为当前实现承诺，详见第 8 节。

## 3. 端到端交互链

### 3.1 Python 到 C++

```text
import decord
  → _ffi.base._load_lib()
  → ctypes.CDLL(libdecord, RTLD_GLOBAL)
  → 优先 Cython FFI，失败后退到 ctypes
  → _init_api("decord.video_reader/audio_reader/video_loader")
  → DECORDFuncListGlobalNames()
  → DECORDFuncGetGlobal() 复制 PackedFunc 句柄
  → Function.__call__ 打包 DECORDValue + type_codes
  → DECORDFuncCall()
  → C++ Registry 中的 PackedFunc lambda
  → opaque Reader/Loader、scalar 或 NDArray
```

`DECORDFuncCall` 成功返回 `0`，失败返回 `-1` 并写入线程局部 `DECORDGetLastError()`。字符串、bytes 和全局函数名数组也存在线程局部存储，前端必须在下一次相关 C API 调用前复制。`API_BEGIN/API_END` 主要捕获 `std::runtime_error`；`CHECK`、`LOG(FATAL)` 和部分设备/解码错误仍可能直接终止进程。

### 3.2 Registry 与接口注册

动态库静态初始化时，`DECORD_REGISTER_GLOBAL` 将以下命名空间放入同一张全局表：

```text
video_reader.*     → VideoReader 的创建、seek、next、batch、free
video_loader.*     → VideoLoader 的创建、采样、双结果消费、free
audio_reader.*     → AudioReader 的创建、元数据、NDArray、free
device_api.cpu/gpu → DeviceAPI 延迟解析
```

`Registry::Manager` 使用互斥锁保护 `unordered_map<string, Registry*>`，Manager 和 Registry 节点故意存活到进程退出，以避免 Python callback 的静态析构顺序问题。重复注册默认 `CHECK` 失败；`Remove` 只擦除 map，不撤销已经复制出去的 `PackedFunc`。Registry 是进程内命名装配表，不是权限边界、版本协商或 provider 隔离器。

视频和音频注册入口都先 `new` Reader，再检查帧数/样本数；失败时只返回 null handle，没有删除刚创建的对象。对应 `*_Free` 只是空指针判断后 `delete`，没有 double-free 或 lease 防护。

### 3.3 VideoReader：路径/BytesIO 到帧

```text
Python VideoReader(uri, ctx, ...)
  → 路径 io_type=0，file-like 读成 bytearray、io_type=2
  → C++ 打开 AVFormatContext / raw AVIO
  → 选最佳视频流和 CPU/GPU decoder
  → 建 codec/filter，扫描 packet 形成 PTS/keyframe 索引
  → Seek(0) 回到起点
  → seek/next 或 get_batch
  → packet queue → worker → frame queue
  → FFmpeg filter：旋转/缩放/RGB
  → 紧凑 AVFrame 的 DLPack view，或逐行复制 NDArray
  → Python bridge_out
```

`get_batch` 在 C++ 侧按请求顺序输出，重复索引只解码一次，后续使用 offset view/copy。准确 seek 会清空队列、刷新 codec、定位最近 keyframe，并丢弃目标前的 PTS。损坏帧可能 rewind 并返回 `cached_frame_` 的副本；`fault_tol` 超限时依赖错误文本触发 `DECORDLimitReachedError`。返回值没有“替代帧/缺失帧”标记，不能把成功返回解释为数据质量通过。

### 3.4 VideoLoader：采样到双结果

```text
Python URI 列表/ctx/shape
  → URI 逗号拼接 + 11 参数 PackedFunc
  → 每个 URI 创建 VideoReader（当前实际使用 ctxs[0]）
  → sampler 生成 (reader_idx, frame_idx)
  → 一个 Reader.GetBatch()
  → next_data_ + next_indices_
  → NextData() 与 NextIndices() 各消费一次 ready bit
  → Python bridge_out(data), bridge_out(indices)
```

Loader 没有后台预取线程；`prefetch` 只保存参数。`Next`、`NextData`、`NextIndices` 是同步双结果槽，上一批未完整消费只打印 warning；没有并发锁。源码实际支持 shuffle 0、1、2，3/4 只出现在枚举或注释中。构造器创建所有 Reader，但只用第一 context。

### 3.5 AudioReader 与 AVReader

`AudioReader` 构造时同步完成：找音频流 → codec → `SwrContext` → 逐 packet/frame 解码 → 重采样/mono → `outputVector` 全量累积 → `C×S` NDArray。Python 立刻调用 `.asnumpy()`，后续索引只访问 NumPy 数组。因此它不是流式读取，也没有分块、取消或输出预算。

`AVReader` 先创建 AudioReader 并 padding，再对 file-like 执行 `seek(0)` 创建 VideoReader。视频帧 PTS 的秒区间用 `ceil(timestamp * sample_rate)` 转 sample；连续批次复用上一个音频 end，非连续或边界仍受浮点到整数离散化影响。音频和视频任一 Reader 创建失败，整个 AVReader 构造失败，没有事务回滚语义。

## 4. 后端线程与设备链

### 4.1 CPU FFmpeg

`FFMPEGThreadedDecoder` 有 packet、buffer、frame 三条 `ConcurrentBlockingQueue` 和单 worker：

```text
Push(packet, output_buffer)
  → packet/buffer queue
  → WorkerThread
  → avcodec_send_packet/receive_frame
  → FFMPEGFilterGraph
  → ProcessFrame
  → frame queue
  → Pop()（阻塞）
```

EOS 使用 null packet 和 128 个 int64 sentinel。`Stop` 对队列 `SignalForKill`、置 `run_=false`、join；`Clear` 随后 flush codec、清 discard PTS 和错误状态。worker 只把 `dmlc::Error` 记录为内部错误并杀死 frame queue；`CHECK`/`LOG(FATAL)` 可直接退出进程。`CheckErrorStatus` 再次 `LOG(FATAL)`，没有 worker 重启、请求级错误对象或 deadline。

`FFMPEGFilterGraph::Push` 递增 `count_`，`Pop` 成功取 frame 后没有递减。析构函数中的显式 `avfilter_free/avfilter_graph_free` 被注释；底层 graph 是否完全由智能指针释放，需要真实 FFmpeg 版本验证。

### 4.2 NVDEC/CUDA

```text
GPU VideoReader
  → cuInit/cuDeviceGet + NVML 驱动查询
  → primary CUDA context + stream
  → CUVideoParser callbacks
  → CUVideoDecoder surfaces
  → packet/frame/reorder queues
  → cuvidMapVideoFrame
  → texture registry + CUDA conversion kernel
  → cudaStreamSynchronize
  → GPU NDArray
```

display callback 从 frame queue 取预分配数组，映射 surface 后写入 reorder queue。packet queue 超过 `kMaxOutputSurfaces` 时纳秒 sleep 忙等；`Pop` 只检查一次 reorder queue 大小。Stop 依赖 kill 队列并 join launcher，没有外部取消或时间上限。CUDA/NVML、codec、surface、texture、stream/context 错误多为 fatal；未编译 CUDA 或设备不可用时不会自动退回 CPU。

已发现的静态生命周期风险：`CUContext` 构造使用 primary context retain，析构使用 primary release，但 move assignment 使用 `cuCtxDestroy`；texture registry 的 key 不含 pitch/几何尺寸且只在 registry 析构时整体销毁；跨 GPU `cudaMemcpyPeerAsync` 分支没有同等的 `CUDA_CALL` 检查。

## 5. NDArray、DLPack 与所有权

`NDArray::Container` 首字段兼容 `DLTensor`，包含 `manager_ctx`、deleter、shape 和原子引用计数。复制 NDArray 只增引用，不复制数据；引用归零才调用 deleter。view 将父 Container 放进 `manager_ctx`，所以 offset view 不能脱离父数组独立拥有内存。

```text
NDArray::Empty → DeviceAPI::AllocDataSpace → Container
CreateView/CreateOffsetView → 借用 parent + 增加 parent 引用
ToDLPack → 新建 DLManagedTensor + 增加 Container 引用
FromDLPack → 接管外部 tensor，最终调用外部 deleter
Python capsule → 改名 used_dltensor，一次消费
```

FFmpeg 输出只有在 linesize 紧凑时才可能包装为 AVFrame DLPack view，否则逐行复制。GPU copy 使用显式 stream 时可能异步，必须由调用方同步；返回 NDArray 不等于 GPU 数据已经完成。`zerocopy_from_numpy` 只保存 NumPy 裸指针，不持有原始 NumPy 对象，调用方提前释放源数组会留下悬空 view 风险。Python Reader、Loader、Function、NDArray 主要依赖 `__del__`/`__dealloc__`，没有显式 `close()` 或 context manager。

## 6. 生命周期与失败恢复审计

| 阶段 | 正常路径 | 当前失败/恢复行为 | 结论 |
|---|---|---|---|
| 动态库加载 | `_load_lib` 找到库并加载 | 缺库/ABI 问题在 import 阶段失败 | 无延迟 fallback，也非隔离 provider |
| Reader 构造 | 建 format/codec/decoder/index | 空流可能 null；大量 CHECK/FATAL；null 分支泄漏刚分配对象 | 失败不是稳定错误码 |
| 单帧/批量 | seek、队列解码、返回 NDArray | seek 有有限次数 fallback；损坏帧可回退旧帧 | 无超时/取消；替代帧无标记 |
| worker/callback | queue 生产消费，Stop 后 join | 内部错误 kill 部分队列；fatal 直接结束进程 | 无请求级失败、重启或残留回读 |
| 音频 | 全量解码、物化、Python copy | 无音频/codec/resample 常为 fatal | 长音频内存峰值线性增长 |
| GPU | surface map、kernel、stream sync、输出 | CUDA/NVML/格式错误多为 fatal | 无 CPU fallback；忙等可能无界 |
| Python 释放 | `__del__` 调 `*_Free` | GC、循环引用、解释器退出顺序未验证 | 不能作为服务级释放协议 |
| 宿主崩溃 | OS/驱动回收地址空间 | 无 checkpoint、lease、重启或残留扫描 | “OS 会回收”不是验收证据 |

公开 API 没有 wall-clock deadline、cancel token、请求幂等键、句柄租约或统一输出上限。内部 `Stop/Clear` 只服务 seek、重建和析构，不能被调用方当作取消协议。

## 7. 测试、构建与文档可读性

当前测试资产：

- Python Reader/AV/bridge 测试是 nose 风格顶层函数，不是标准 unittest；可选 bridge 缺失时 `print("Skip")`，不是测试框架 skip。
- Audio 测试调用 `ar.shape()`，但实现是 `shape` property；还引用当前树中不存在的 `tests/cpp/audio/*` 音频文件。
- AV 测试包含 `/Users/weisy/...` 绝对路径；bridge 线程测试包含 `~/Dev/decord/...`，均不能在当前树独立复现。
- C++ 测试依赖 GTest 且目标 `EXCLUDE_FROM_ALL`；视频主测试包含 `while (0)`，音频测试使用外部绝对路径。
- `tests/test_data/` 只提供视频样本；存在旋转、乱序、损坏视频，不等于音频/失败释放覆盖。

README 与源码存在可读性漂移：AudioReader 示例把 property 写成方法；VideoLoader 宣称 shuffle=3、多 context 均匀分配和预取；构建说明包含旧发行版/路径写法；API 文档入口只有薄 Sphinx toctree，没有生命周期、错误、GPU 硬失败和 DLPack 同步说明。本文不修改源码、测试或 `README.md`，因此这些问题保留为文档/测试债务。

## 8. 风险清单与优先级

**P0：调用进程可能被终止或资源不可回收**

- Registry Reader/AudioReader null-return 分支泄漏刚 `new` 的对象。
- FFmpeg/NVDEC/DeviceAPI 大量 `CHECK`/`LOG(FATAL)` 越过 C ABI 错误出口。
- 队列 Pop、GPU Push 忙等没有 deadline/cancel；损坏流和设备错误不能安全恢复。

**P1：结果或状态可能被误读**

- 损坏帧用 cached frame 替代但没有结果标记。
- `DECORDLimitReachedError` 由错误字符串匹配，不是稳定错误码。
- VideoLoader 的文档能力超出实际实现；`next_ready_` 双消费槽不是 prefetch。
- AudioReader/AVReader 的 shape 调用漂移；`add_padding` 把 padding 样本乘以 sample rate 加到 duration，单位明显不一致。

**P1：生命周期/并发需要真实回归**

- `VideoReader` 共享对象并发不安全；Reader/Loader/Audio 没有显式关闭协议。
- filter graph `count_` 不递减；CUDA primary context move assignment、texture registry 几何 key、跨 GPU copy 检查存在静态风险。
- DLPack 一次消费、异步 GPU copy、NumPy zero-copy owner 依赖调用方自律。

## 9. 适配边界与最低验收

若把 Decord 接入更高层系统，只能吸收以下模式：PTS/keyframe 随机访问、批量重复索引去重、CPU/GPU 共享 reader 形态、NDArray/DLPack 数据所有权表达。不得直接吸收：进程内 fatal、日志字符串错误分类、Python GC 唯一释放、全量音频物化、GPU 忙等和未兑现的 prefetch/multi-context 语义。

外部适配层至少需要：

1. 独立 provider 进程或等价隔离边界，不把 FFmpeg/CUDA native handle 暴露给主进程。
2. 稳定错误码、请求 id、预算、deadline、取消、句柄租约和显式 close。
3. 失败帧带失败索引/替代标记；GPU fallback 必须显式声明，不能伪装成功。
4. 对正常、失败、超时、取消、provider 崩溃分别验证队列、线程、句柄、临时文件、GPU surface/stream 和 DLPack deleter 的释放。

本仓库下一轮真实验收最低应覆盖：CPU 视频顺序/随机/重复 batch/损坏流、AudioReader shape/重采样/padding、AV 时间对齐、FFmpeg worker Stop/join、CUDA surface/texture/context、DLPack 一次消费和异步同步。当前这些均为 L4 未执行项。

## 10. 参考路径

- Python API：`python/decord/video_reader.py`、`video_loader.py`、`audio_reader.py`、`av_reader.py`、`ndarray.py`、`bridge/`。
- FFI/C ABI：`python/decord/_ffi/`、`include/decord/runtime/c_runtime_api.h`、`src/runtime/c_runtime_api.cc`。
- Registry/接口：`include/decord/runtime/registry.h`、`src/runtime/registry.cc`、`src/video/video_interface.cc`、`src/audio/audio_interface.cc`。
- 视频/音频：`src/video/video_reader.cc`、`src/video/video_loader.cc`、`src/audio/audio_reader.cc`、`include/decord/video_interface.h`、`audio_interface.h`。
- CPU/GPU：`src/video/ffmpeg/`、`src/video/nvcodec/`、`src/runtime/cuda/`、`src/video/storage_pool.*`。
- 数据所有权：`include/decord/runtime/ndarray.h`、`src/runtime/ndarray.cc`、`python/decord/_ffi/ndarray.py`。
- 测试/构建/文档：`tests/`、`CMakeLists.txt`、`.github/workflows/`、`README.md`、`docs/`。
- 历史线索：`细探-decord.md`，仅作历史材料，不与本文并列为事实源。

## 11. 研究材料吸收记录

已人工回读并吸收 `细探-decord.md` 的增量事实：FFI/Registry 与 C ABI 入口、VideoReader/VideoLoader/AudioReader/AVReader 调用链、FFmpeg/NVDEC 与 CUDA surface、NDArray/DLPack/NumPy 所有权、线程队列与 Stop/join、fatal/忙等错误边界、AudioReader 单位风险及测试样本和绝对路径债务。旧材料不再作为第二份架构事实源。

## 12. 当前版本、目录和文件导航

### 12.1 Git 与构建基线

- 参考仓库：`~/Documents/Agent/github 源码参考/30_多模态与媒体分析/05_video_decode_sampling/decord`。
- `master` 与 `origin/master` 当前提交：`d2e56190286ae394032a8141885f76d5372bd44b`，提交说明 `update readme (#211)`，2022-07-19。
- 仓库包含未跟踪 `.codegraph/` 和根 `ARCHITECTURE.md`；两者不属于 Git 提交，不删除、不覆盖。
- `CMakeLists.txt` 汇总 C++ runtime、FFmpeg、CUDA/NVDEC、Python binding；`python/setup.py` 负责 Python 包安装和动态库查找。
- `cmake/modules/FindFFmpeg.cmake`、`FindCUDA.cmake` 和 `CUDA.cmake` 是发现外部依赖的边界；配置成功不等于编译或加载成功。

### 12.2 目录职责表

| 目录 | 关键文件 | 责任 |
|---|---|---|
| `include/decord/` | `video_interface.h`、`audio_interface.h`、`av_interface.h` | C++ reader 公共接口、opaque 类型和输出契约 |
| `src/video/` | `video_reader.cc`、`video_loader.cc`、`storage_pool.cc` | FFmpeg/NVDEC 视频读取、批量和缓存 |
| `src/audio/` | `audio_reader.cc`、`audio_interface.cc` | 音频解码、重采样、padding 和 NDArray |
| `src/runtime/` | `c_runtime_api.cc`、`ndarray.cc`、`registry.cc`、`thread_pool.cc` | C ABI、PackedFunc、NDArray、全局注册、线程池 |
| `src/sampler/` | sequential/random/smart/random-file sampler | 帧索引生成和 shuffle 策略 |
| `src/segmenter/` | cutter、scene cutter | 区间切分和场景边界辅助 |
| `src/improc/` | `improc.cu` | CUDA 图像转换和 device kernel |
| `python/decord/` | `video_reader.py`、`audio_reader.py`、`av_reader.py`、`video_loader.py` | Python API、FFI 调用和对象包装 |
| `python/decord/_ffi/` | `base.py`、`function.py`、`runtime_ctypes.py` | Cython/ctypes 绑定、PackedFunc 打包 |
| `tests/` | test data、benchmark、脚本 | 夹具和性能对比；当前没有完整 Python 单测目录 |
| `docs/`、`examples/` | rst、notebook、媒体文件 | 使用说明和示例，不是运行验证 |

## 13. Python 公开 API 与调用表

| API | 文件 | 真实行为 |
|---|---|---|
| `decord.VideoReader` | `python/decord/video_reader.py` | 打开视频、元数据、随机/顺序帧、batch、seek、时间定位 |
| `VideoReader.__getitem__` | `video_reader.py` | 单索引/切片转 `next` 或 `get_batch`；负索引按长度解析 |
| `VideoReader.get_batch` | `video_reader.py` | 将索引列表交给 C++ batch，返回 NDArray |
| `VideoReader.seek`/`seek_accurate` | `video_reader.py` | 快速关键帧 seek 或精确 seek；精度依赖 codec/keyframe |
| `VideoReader.get_avg_fps` | `video_reader.py` | 从 C++ 元数据计算 FPS |
| `decord.AudioReader` | `python/decord/audio_reader.py` | 音频采样、shape、duration、sample rate、batch |
| `AudioReader.__getitem__`/`get_batch` | `audio_reader.py` | 以样本索引取数据并返回 NDArray |
| `decord.AVReader` | `python/decord/av_reader.py` | 以时间范围对齐视频帧与音频样本 |
| `decord.VideoLoader` | `python/decord/video_loader.py` | 多文件采样、batch、shuffle、prefetch、双结果迭代 |
| `decord.bridge.set_bridge` | `python/decord/bridge.py` | 输出转换到 numpy/torch/mxnet/tvm 等桥接格式 |
| `decord.cpu`/`decord.gpu` | `python/decord/base.py` | 设备上下文对象，传入 Reader/Loader/NDArray |

Python 层多数对象通过 `__del__` 调用 C ABI free；这属于最佳努力，不是确定性 `close()` 协议。异常消息来自线程局部 `DECORDGetLastError`，调用方必须在下一次 C API 调用前复制。

## 14. VideoReader/AudioReader/Loader 详细链路

### 14.1 VideoReader 初始化

1. `VideoReader(uri, ctx, width, height, num_threads, fault_tol)` 解析 URI 或 BytesIO。
2. Python FFI 查找 `video_reader._VideoReader`，将 device、尺寸、线程数和 fault tolerance 打包。
3. C++ `VideoReader` 创建 FFmpeg demuxer、codec context、线程池/缓存和可选 CUDA decoder。
4. C++ 返回 opaque handle；Python 保存 `_handle`、`_num_frame`、`_frame_pts` 等元数据。
5. 帧数或 codec 初始化失败时返回空句柄/异常；构造失败对象的析构路径需要真实验证。

### 14.2 随机访问与 batch

`__getitem__` 负责边界和 slice 展开；`seek` 先寻找关键帧，`seek_accurate` 继续解码至目标 PTS；`get_batch` 对重复索引做缓存/复用并一次性返回 NDArray。随机访问不是 O(1) 硬保证，成本受关键帧间隔、codec、缓存和 device transfer 影响。

### 14.3 AudioReader

AudioReader 将 FFmpeg 音频 stream 解码为目标 sample rate/channel/layout；`get_batch` 返回样本和通道维度。重采样、尾部 padding、非整帧和损坏音频的行为由 `audio_reader.cc`/`swresample` 决定，不能只按 notebook 示例推断。

### 14.4 VideoLoader

VideoLoader 创建多文件 reader 列表和 sampler；迭代器一次返回 `(frames, indices)` 双结果。`shuffle=0/1/2/3` 选择 sequential、random、smart 或 random-file sampler；`prefetch` 由 worker/thread pool 提前填充。文件打开失败、单文件 frame count 变化和 worker 异常的聚合语义需要实测。

## 15. C ABI、Registry 与 Python FFI 细节

`src/runtime/c_runtime_api.cc` 提供 `DECORDFuncCall`、`DECORDFuncGetGlobal`、`DECORDFuncListGlobalNames`、`DECORDGetLastError`、NDArray 与 DLPack 函数。`src/runtime/registry.cc` 的全局 map 以 mutex 保护注册和查找；复制出的 `PackedFunc` 可能继续引用静态注册节点。

Python `_ffi/function.py` 把 Python 参数编码为 `DECORDValue`、type codes 和 handle 数组；返回值按 scalar/string/NDArray/opaque 解包。ctypes fallback 与 Cython 路径必须保持 ABI 一致；指针长度、字符串生命周期和异常线程局部存储是高风险边界。

## 16. FFmpeg、线程池和设备资源

| 资源 | owner | 释放路径 | 未保证 |
|---|---|---|---|
| `AVFormatContext`/`AVCodecContext` | Video/AudioReader | reader destructor/close | 构造失败和强杀路径 |
| FFmpeg packet/frame/filter | decoder/filter | RAII 或显式 free | filter graph 版本差异 |
| reader worker/thread pool | VideoLoader/decoder | Stop/join/destructor | worker 异常是否唤醒所有等待者 |
| CUDA context/stream | NVDEC/GPU DeviceAPI | decoder/device destructor | Python GC 顺序、跨线程 context |
| CUDA surface/texture | NVDEC parser/decoder | frame release/deleter | 异步 kernel 完成前释放 |
| NDArray refcount | runtime/bridge | `DECORDArrayFree`/deleter | 跨框架异步消费 |
| DLPack capsule | bridge | one-shot deleter | 重复消费和 consumer 延迟 |
| PackedFunc handle | Registry/FFI | 静态节点/引用释放 | 动态库卸载时序 |

线程池和 decoder queue 需要明确 bounded capacity；当前源码不能证明所有 backpressure、fairness、timeout 或 cancellation 都具备。

## 17. 测试、构建和部署矩阵

| 目标 | 位置 | 证据边界 |
|---|---|---|
| 视频随机/顺序 | `tests/test_data`、examples | 样例媒体，不等于当前执行通过 |
| 音频 shape/重采样 | `examples/audio_reader.ipynb` | notebook 说明，非门禁 |
| loader shuffle/benchmark | `tests/benchmark/bench_decord.py` | 性能脚本，无失败恢复断言 |
| C++ runtime | CMake/CI | 构建配置，未在当前环境运行 |
| FFmpeg discovery | `cmake/modules/FindFFmpeg.cmake` | 依赖探测，未验证本机版本 |
| CUDA/NVDEC | `cmake/modules/CUDA.cmake`、`gpu.Dockerfile` | 需要 GPU/driver，未执行 |
| Python package | `python/setup.py` | 安装入口，未构建 wheel |
| bridge | Python bridge modules | 需要对应框架，未测试 DLPack 生命周期 |

构建命令应在独立目录执行 CMake configure/build、Python import 和媒体 smoke test；不能在无 FFmpeg/CUDA 时把 skip 当作通过。部署时要固定 `libdecord`、FFmpeg、CUDA driver ABI 和 Python wheel 版本。

## 18. 平台映射与最终结论

| Decord 能力 | 平台落点 | 限制 |
|---|---|---|
| VideoReader/AudioReader | 支持库媒体解码原子能力 | 外部 FFmpeg/CUDA 必须隔离适配层 |
| VideoLoader/sampler | 模块库视频采样流程 | 需要有界队列、取消、资源租约和批次证据 |
| C ABI/NDArray/DLPack | 公共契约跨框架数据边界 | 必须统一错误和一次性所有权 |
| FFmpeg/NVDEC | 受管 provider | 版本、GPU context、进程隔离和回收 |
| Python bridge | 项目适配层 | 不让正式代码直接依赖框架私有 ABI |
| CMake/CI/Docker | 构建/发布工具 | 配置声明不等于实际发布验证 |

Decord 可作为“音视频解码、随机访问、批量采样和跨框架数组交换”的源码参考；不能直接承诺全链路事务、强取消、GPU 资源自动恢复、跨版本 ABI 稳定或服务级隔离。本文是平台侧唯一 Decord 架构文档，后续增量只修改本文件。

## 19. 细粒度错误与边界矩阵

| 阶段 | 典型错误 | 当前代码处理 | 仍需验证 |
|---|---|---|---|
| 动态库查找 | `libdecord` 不存在 | `libinfo.py` 搜索候选路径并抛 OSError | 多平台路径、RTLD_GLOBAL 冲突 |
| FFI 参数打包 | unsupported Python type | type code 校验/异常 | 64 位指针、bytes 生命周期 |
| URI 打开 | 文件不存在/权限 | FFmpeg open 失败转 last error | 句柄是否完全释放 |
| codec 初始化 | codec 不支持/损坏 header | Reader 构造失败 | 部分创建对象的析构 |
| seek | 非单调 PTS/无关键帧 | 快速或精确 seek 返回错误/近似帧 | 时间精度与重复 seek |
| batch | 越界/重复/空列表 | Python 边界检查、C++ batch | 大 batch 内存峰值 |
| 音频重采样 | layout/rate 不兼容 | swresample 错误 | 尾部 padding 和通道顺序 |
| FFmpeg worker | decode thread 异常 | Stop/join 或队列错误 | 等待者是否全部唤醒 |
| CUDA init | 无 driver/context | GPU API 错误 | fallback 是否显式而非静默 |
| CUDA async | stream 未完成 | deleter/同步依赖 | surface 释放竞态 |
| NDArray bridge | consumer 延迟/重复消费 | refcount/DLPack deleter | torch/mxnet/tvm 异步语义 |
| registry | 重复注册 | `CHECK` 失败 | 动态库重复加载行为 |
| Python GC | 循环引用/解释器退出 | `__del__` 最佳努力 | 进程退出 leak |

## 20. 资源所有权核对表

### 20.1 Reader 所有权

`VideoReader` Python 对象持有 opaque `_handle`；实际 `VideoReader` C++ 对象持有 demuxer、codec、frame cache、storage pool 和可选 device decoder。Python `__del__` 调用 `video_reader.Free`，但用户主动删除 `_handle`、重复析构或跨线程共享不受 lease 保护。`AudioReader` 相同，只是额外持有 resampler、audio frame buffer 和 sample metadata。

### 20.2 Loader 所有权

`VideoLoader` 同时持有 reader 列表、sampler、prefetch queue、worker 和 batch buffer。停止顺序必须是阻止新任务、关闭输入 reader、唤醒 worker、join、释放 queue 和 batch NDArray；源码路径存在 Stop/join，但没有统一外部 `close()` 协议，必须把析构测试列为高风险。

### 20.3 Bridge 所有权

NDArray 可以从 C++ 返回到 Python，也可导出 DLPack；DLPack capsule 通常只允许一次消费。consumer 若在 producer 释放后异步使用，必须由框架保持引用或同步 stream。不能把 numpy view、torch tensor 或 DLPack capsule 当作独立持久化副本。

## 21. 构建与部署证据分层

| 层级 | 需要的命令/证据 | 当前状态 |
|---|---|---|
| 源码配置 | `cmake -S . -B build` | 未执行 |
| FFmpeg 探测 | CMake configure 输出、库版本 | 未执行 |
| CPU 编译 | `cmake --build build` | 未执行 |
| Python 安装 | `pip install -e python` 或 wheel | 未执行 |
| Python 导入 | `python -c 'import decord'` | 未执行 |
| CPU smoke | 真实 mp4 顺序/随机/get_batch | 未执行 |
| audio smoke | mp3/wav shape、rate、padding | 未执行 |
| GPU 编译 | CUDA/NVDEC configure/build | 未执行 |
| GPU smoke | 真实 driver/context/surface | 未执行 |
| bridge smoke | DLPack 到 torch/mxnet/tvm | 未执行 |
| 长压测 | 多文件 VideoLoader、worker、内存 | 未执行 |

Dockerfile 和 CI workflow 可以说明依赖安装顺序，却不能证明当前机器、当前 FFmpeg ABI 或 GPU driver 达到同样状态。发布包还需固定 C++ ABI、编译器、FFmpeg SONAME、CUDA compute capability 和 Python 版本。

## 22. 随机访问、时间和采样语义

- 帧索引是解码后 frame number，时间戳来自 FFmpeg stream PTS；二者在 variable frame rate 视频上不等价。
- `seek` 常跳到关键帧附近，`seek_accurate` 需要向前解码；耗时与关键帧间隔线性相关，不能承诺常数时间。
- `get_batch` 返回请求顺序通常由 Python 索引列表决定；重复索引的内部缓存优化不改变调用方应验证的顺序。
- `AVReader` 以时间范围对齐音视频，但音频 sample rate、视频 FPS 和 PTS time base 不同，边界需要容差契约。
- `VideoLoader` sampler 的 shuffle 只改变索引选择顺序，不保证跨进程、跨 worker 的全局无重复。
- `fault_tol` 影响损坏帧处理策略；错误帧替代/跳过必须由返回状态或日志可观测，不能静默伪装有效帧。

## 23. 平台验收最小场景

1. CPU 顺序读取：验证首帧、末帧、帧数、FPS、时间戳和 close 后句柄。
2. CPU 随机读取：验证关键帧前后、重复索引、逆序索引、空 batch 和越界。
3. 损坏流：验证 fault tolerance、失败索引、错误码和 reader 是否仍可继续。
4. AudioReader：验证 mono/stereo、多 sample rate、尾部 padding、空范围和重采样。
5. AVReader：验证同一时间窗口的音频样本数与视频帧边界。
6. VideoLoader：验证多文件、四种 shuffle、prefetch、worker 异常、停止和重复 close。
7. FFmpeg worker：注入 decode 错误，确认 queue 不死锁，所有 worker join。
8. GPU：验证 context、stream、surface、texture、异步同步和无 driver 错误路径。
9. Bridge：验证 numpy/torch/mxnet/tvm 转换、DLPack 一次消费、延迟消费和引用释放。
10. 长时间运行：检查线程数、RSS、GPU memory、文件描述符和临时文件无界增长。

## 24. 唯一文档维护规则

- 远程提交变化时先更新提交、依赖和新增目录，再修改调用链行号。
- 新增 reader/loader/provider 必须同步更新 API、资源 owner、错误矩阵和测试矩阵。
- 行号必须以当前 checkout 源码为准；历史 `细探-decord.md` 只用于追溯，不作为第二事实源。
- C ABI、DLPack、FFmpeg 和 CUDA 的版本声明必须分别标注源码证据与运行证据。
- 任何“零拷贝”“实时”“线程安全”“自动恢复”表述都要有明确源码路径和测试，不得从 README 宣传语推断。
- 文档静态收口只能声明结构和证据完整；不能代替编译、导入、真实媒体和 GPU 运行。
- 平台映射只记录研究输入；正式接入必须走能力登记、provider owner、租约、错误和发布门禁。
- 新增平台验证结果必须记录命令、退出码、环境指纹、媒体样本、资源残留和未验证项。

## 25. 最终裁决

Decord 的核心价值是把 FFmpeg/NVDEC 解码、VideoReader/AudioReader/VideoLoader 采样、线程队列和 NDArray/DLPack bridge 封装成 Python 可用 API。其真实性边界由 C ABI、Registry、opaque handle、FFmpeg/CUDA 生命周期和 Python GC 共同决定。

当前源码没有证明跨 provider ABI 永久稳定、reader/loader 强取消、所有 queue 有界、GPU surface 自动恢复、DLPack 异步安全或服务级隔离。平台可吸收接口分层、媒体批处理和资源 owner 设计，但必须在支持库适配层锁定版本，并通过真实 CPU/GPU/bridge 验收后才能进入正式制品。

## 26. 文件级证据索引

| 文件 | 关键证据 |
|---|---|
| `python/decord/video_reader.py` | VideoReader 参数校验、索引、seek、batch、时间戳和 bridge |
| `python/decord/audio_reader.py` | AudioReader sample、shape、duration、rate 和 C ABI 调用 |
| `python/decord/video_loader.py` | 多文件、sampler、batch、prefetch 和迭代器 |
| `python/decord/av_reader.py` | 音视频时间窗口对齐 |
| `python/decord/_ffi/base.py` | 动态库搜索和 Cython/ctypes fallback |
| `python/decord/_ffi/function.py` | PackedFunc 参数编码、调用和异常读取 |
| `python/decord/ndarray.py` | NDArray Python 包装、context、DLPack |
| `src/video/video_reader.cc` | 视频 demux、codec、seek、frame batch、错误和释放 |
| `src/video/video_loader.cc` | loader worker、sampler、queue、Stop/join |
| `src/audio/audio_reader.cc` | 音频解码、重采样、padding、NDArray |
| `src/runtime/c_runtime_api.cc` | C ABI、线程局部错误、PackedFunc、NDArray API |
| `src/runtime/registry.cc` | 全局函数注册、查找、互斥和静态生命周期 |
| `src/runtime/thread_pool.cc` | worker、队列和任务完成等待 |
| `src/video/storage_pool.cc` | frame/storage pool、缓存和回收 |
| `src/sampler/*.cc` | 顺序、随机、smart、文件级 sampler |
| `cmake/modules/FindFFmpeg.cmake` | FFmpeg 头文件、库和版本探测 |
| `cmake/modules/CUDA.cmake` | CUDA/NVDEC 编译开关、架构和库 |
| `python/setup.py` | Python 包、动态库安装和依赖 |
| `tests/benchmark/bench_decord.py` | 与 OpenCV/PyAV 的基准入口 |
| `.github/workflows/ccpp.yml` | CI 编译平台和系统依赖声明 |

## 27. 证据分级收口

静态源码可证明入口、字段、调用和资源 owner；测试源码可证明作者意图和断言存在；CMake/CI/README 可证明预期构建路径；只有当前环境实际编译、导入、读取媒体、触发错误、释放资源并回读残留，才能升级为运行证据。本轮属于前三级静态收口，L4 真实验证仍未执行。

## 28. 版本冻结与兼容性风险

- 当前 checkout 的最后提交为 2022 年，远程 `origin/master` 没有比本地更新的提交；这只是仓库事实，不代表 Decord 依赖链在今天仍兼容。
- FFmpeg、CUDA、Python、NumPy、PyTorch、DLPack 和编译器均可能已发生 ABI/API 漂移；README 中的安装命令不能替代当前版本矩阵。
- CMake 发现旧 FFmpeg header/library 组合时可能配置成功但链接或运行失败；必须记录实际 `avcodec`、`avformat`、`swscale`、CUDA driver 版本。
- Python ctypes fallback 依赖动态库导出符号和结构体布局；Python 3.10+、arm64、Windows/macOS/Linux 的路径和 calling convention 都需单独验证。
- GPU 路径依赖 NVDEC 能力、显卡 compute capability、driver 和 FFmpeg 编译选项；没有 GPU 时不应把 CPU fallback 当作 GPU 等价。
- 测试样本是仓库内有限的 `.mov/.mp4/.mkv/.mp3` 文件，不能覆盖 variable frame rate、B 帧、字幕、多音轨、损坏索引和网络 URI。
- benchmark 只比较吞吐/延迟，不覆盖内存泄漏、句柄泄漏、线程退出、错误恢复或跨框架异步生命周期。
- 版本冻结风险应进入平台 provider 锁定：源码 commit、编译器、FFmpeg/CUDA/NumPy/DLPack ABI、Python wheel 和真实媒体 smoke 结果必须成套记录。

## 29. 本轮完成清单

- [x] 首调用 `project_context`，核对平台根目录和 `system_engineering_toolkit` 实例。
- [x] 随后调用 `codegraph_explore`；平台代码地图可用，但不将平台地图当作 Decord 源码地图事实。
- [x] `git fetch origin master`，确认 `master` 与 `origin/master` 同步且无远程新提交。
- [x] 保留源码仓库未跟踪 `.codegraph/`、`ARCHITECTURE.md`，未修改源码仓库。
- [x] 更新平台唯一 `ARCHITECTURE.md`，覆盖目录、入口、调用链、状态、资源、测试、部署、版本风险和平台映射。
- [x] `git diff --check` 通过。
- [ ] Decord C++/Python 真实构建、导入、媒体读取、GPU、bridge、压力和强杀恢复，未执行。
