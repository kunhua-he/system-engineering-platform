# Decord 架构审计

> 本文是当前源码的根架构文档。它记录“代码实现了什么”“调用方如何穿过边界”以及“哪些结论尚未经过运行验证”。不把 README、测试名称或历史 CI 声明当作运行证据。

## 1. 审计范围与证据

审计对象是当前工作树：

```text
/Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/05_video_decode_sampling/decord
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
| L2 | CMake/CI/README 声明过能力 | 存在，非本轮执行结果 |
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

## 11. 施工材料吸收记录

已人工回读并吸收 `细探-decord.md` 的增量事实：FFI/Registry 与 C ABI 入口、VideoReader/VideoLoader/AudioReader/AVReader 调用链、FFmpeg/NVDEC 与 CUDA surface、NDArray/DLPack/NumPy 所有权、线程队列与 Stop/join、fatal/忙等错误边界、AudioReader 单位风险及测试样本和绝对路径债务。旧材料不再作为第二份架构事实源。
