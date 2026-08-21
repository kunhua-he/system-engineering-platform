# TransNetV2 架构建档

> 建档范围：本地仓库 `/Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/10_scene_segmentation/TransNetV2`
>
> 证据顺序：README、仓库源码、配置、Dockerfile、LICENSE、Git 远程状态、已有 `细探-TransNetV2.md`。本文件只记录本仓事实；未安装依赖、未启动服务、未构建模型、未修改源码与依赖。
>
> 版本核对：本地 `master` 与 `origin/master` 均为 `85cef72af9a916bdfd7cc94a670c9cdfbf12d1ed`，提交时间 `2021-07-28 18:42:03 +0200`，提交说明 `minor fix`。经 `127.0.0.1:4780` 查询远程 `refs/heads/master`，远程同为该提交，当前核对不需要建立独立远程快照，也没有覆盖工作树。

## 一、文本架构流程图

```text
视频文件 / RGB 帧序列 / 标注场景
            │
            ├─ 推理入口 inference/transnetv2.py
            │    ├─ TransNetV2.__init__ 加载 TensorFlow SavedModel 与权重
            │    ├─ predict_video ── ffmpeg CLI + ffmpeg-python ──> [N,27,48,3] RGB uint8
            │    ├─ predict_frames
            │    │    ├─ 25 帧首尾复制填充
            │    │    ├─ 100 帧窗口、50 帧步长
            │    │    └─ predict_raw ──> single_frame / many_hot 概率
            │    ├─ predictions_to_scenes(threshold=0.5)
            │    └─ visualize_predictions ──> PIL 图像
            │
            ├─ PyTorch 推理分支 inference-pytorch/
            │    ├─ transnetv2_pytorch.TransNetV2
            │    ├─ convert_weights.py：TensorFlow SavedModel 参数名/张量布局映射
            │    └─ transnetv2-pytorch-weights.pth（运行 convert_weights.py 后生成）
            │
            └─ 训练与评估分支 training/
                 ├─ consolidate_datasets.py：多数据集标注统一
                 ├─ create_dataset.py：视频/场景 → GZIP TFRecord 或 NPY
                 ├─ input_processing.py：TFRecord 解析、增强、合成转场
                 ├─ transnet.py：TensorFlow TransNetV2 网络与特征头
                 ├─ training.py：gin 配置、Trainer、损失、训练/评估循环
                 ├─ evaluate.py：加载 epoch 权重、逐视频预测、场景级 P/R/F1
                 └─ metrics_utils.py / visualization_utils.py：指标与可视化
```

## 二、项目定位与边界

TransNetV2 是面向视频镜头边界检测（Shot Boundary Detection，SBD）的深度网络。模型以连续 RGB 帧为输入，逐帧输出镜头转场概率，随后把概率序列转换为场景区间。仓库同时包含：

- TensorFlow SavedModel 推理实现，面向直接使用；
- PyTorch 推理复现，目标是与 TensorFlow 版本产生一致结果，但只发布推理，不发布 PyTorch 训练代码；
- TensorFlow 训练、数据集整理、TFRecord 生成、评估和可视化代码；
- Git LFS 管理的预训练 SavedModel 权重路径。

它不是 Web 服务，也没有 HTTP API、数据库、任务队列或持久化业务数据层。主要交付物是预测数组、场景区间文本、预测文本、可选 PNG，以及训练日志/权重/评估结果。

## 三、真实目录与模块职责

```text
TransNetV2/
├── README.md                         项目说明、推理和复现实验入口
├── ARCHITECTURE.md                   本架构建档
├── LICENSE                           MIT License
├── setup.py                          transnetv2 1.0.0 与 console_scripts
├── configs/
│   ├── transnetv1.gin                旧 TransNet 配置
│   ├── transnetv2.gin                TransNetV2 训练默认配置
│   └── transnetv2-realtrans.gin      在 V2 配置上增加 transition-only 数据的方案
├── inference/
│   ├── __init__.py                   导出 TransNetV2
│   ├── transnetv2.py                 TensorFlow 推理类、场景转换、可视化、CLI
│   ├── transnetv2-weights/           SavedModel 权重目录（saved_model.pb/variables）
│   ├── README.md                     推理安装、API、输出文件说明
│   └── Dockerfile                    TensorFlow GPU 2.1.1 推理镜像
├── inference-pytorch/
│   ├── transnetv2_pytorch.py         PyTorch 网络定义
│   ├── convert_weights.py            TensorFlow → PyTorch 权重转换与对齐测试
│   └── README.md                     PyTorch 推理和转换说明
└── training/
    ├── transnet.py                   TensorFlow TransNetV2 及可选特征模块
    ├── models.py                     OriginalTransNet、ResNet18、C3D 等模型
    ├── training.py                   Trainer、损失、训练/评估主入口
    ├── input_processing.py           Dataset 管线、解析、增强、转场合成
    ├── create_dataset.py              场景/视频/过渡数据集生成
    ├── consolidate_datasets.py        BBC/RAI/ClipShots/IACC.3 标注统一脚本
    ├── evaluate.py                   离线测试集评估入口
    ├── metrics_utils.py               场景转换、容差评估、TensorBoard 指标
    ├── video_utils.py                ffmpeg 抽帧为 RGB Numpy
    ├── visualization_utils.py        场景、预测、错误样本图像
    ├── bi_tempered_loss.py            可选 bi-tempered 损失
    ├── weight_decay_optimizers.py    自定义权重衰减优化器
    ├── Dockerfile                    训练环境与第三方包清单
    └── 其他训练辅助文件
```

仓库没有 `requirements.txt`、`pyproject.toml`，也没有发现 `test*.py` 测试文件。依赖主要散落在 README、`setup.py` 和两个 Dockerfile 中。

## 四、核心推理架构

### 4.1 TensorFlow 推理边界

`inference/transnetv2.py::TransNetV2` 在构造时通过 `tf.saved_model.load(model_dir)` 加载 SavedModel。默认权重目录是相对于 `inference/transnetv2.py` 的 `transnetv2-weights/`；目录缺失抛 `FileNotFoundError`，SavedModel 加载 `OSError` 被包装为权重损坏/缺失的 `IOError`。

输入契约固定为 RGB、尺寸 `27 x 48`：

- `predict_raw(frames)`：要求五维 `[batch, frames, 27, 48, 3]`，源码将输入转为 `tf.float32`，调用 SavedModel，返回 `tf.sigmoid` 后的 `single_frame_pred` 与 `dict_["many_hot"]`；
- `predict_frames(frames)`：要求四维 `[frames, 27, 48, 3]`，dtype/通道约束由后续模型路径实际承担；
- 窗口为 100 帧，步长为 50 帧；视频首尾分别复制 25 帧，最后一段补齐到 50 帧边界；每个窗口只保留中间 `[25:75]` 的 50 帧预测，最后裁剪回原帧数；
- `predict_video(video_fn)`：依赖 `ffmpeg` Python wrapper 与系统 `ffmpeg`，以 `rawvideo/rgb24/48x27` 抽帧，再调用 `predict_frames`。

### 4.2 TensorFlow 训练网络

`training/transnet.py::TransNetV2` 是 gin 可配置的 `tf.keras.Model`。默认结构由配置 `configs/transnetv2.gin` 实例化为：

1. 输入 `[batch, 100, 27, 48, 3]`，默认按 `255` 归一化；
2. `L=3` 个 `StackedDDCNNV2` 阶段，每阶段 `S=2` 个 `DilatedDCNNV2`，空间池化逐级降低分辨率；
3. 每个 `DilatedDCNNV2` 并行使用时间膨胀率 `1/2/4/8` 的 `Conv3DConfigurable`，再沿通道拼接；
4. 默认启用 `FrameSimilarity(lookup_window=101, output_dim=128)` 和 `ColorHistograms(lookup_window=101, output_dim=128)`，把时间邻域相似度/颜色直方图特征拼到主干特征；
5. `Dense(D=1024)`、ReLU、`Dropout(0.5)`；
6. `cls_layer1` 输出 one-hot/single-frame 转场 logits，`cls_layer2` 输出 many-hot 转场 logits；
7. 训练时由 `training.py::Trainer.compute_loss` 组合 one-hot 损失、可选 many-hot 损失、L2 损失和可选 `comb_reg_loss`。

源码还保留可选能力：`ResNetFeatures`、`use_resnet_like_top`、`OctConv3D`、`ConvexCombinationRegularization`、`C3DNet`、`OriginalTransNet`。这些由 gin 选项决定，不是默认推理链路。

### 4.3 PyTorch 推理复现

`inference-pytorch/transnetv2_pytorch.py::TransNetV2` 保持 `[B,T,27,48,3]` 的 `torch.uint8` 输入契约，内部转为 `[B,3,T,H,W]`、浮点并除以 `255`。主要模块为：

- `StackedDDCNNV2` → `DilatedDCNNV2` → 四路 `Conv3DConfigurable`；
- `FrameSimilarity`：投影、L2 归一化、时间相似度矩阵与局部窗口；
- `ColorHistograms`：每帧 512-bin 颜色直方图、归一化与局部相似度；
- `fc1`、`cls_layer1`、可选 `cls_layer2`。

PyTorch 版本明确拒绝若干 TensorFlow 选项：`use_resnet_features`、`use_resnet_like_top`、`use_convex_comb_reg`、`frame_similarity_on_last_layer`、`use_octave_conv`、部分 `kernel_initializer` 和 `stop_gradient`。因此“结果一致”依赖于转换时采用双方都支持的模型配置。

`convert_weights.py::convert_weights` 从 TensorFlow SavedModel 读取变量，通过 `remap_name` 映射层名、`remap_tensor` 调整卷积/全连接张量布局，再使用 `check_and_fix_dicts` 对比形状并加载到 PyTorch；`--test` 用 10 组随机 `[2,100,27,48,3]` 输入比较两套模型输出的逐元素接近比例。

## 五、数据模型与数据流

### 5.1 推理数据

| 数据 | 形状/格式 | 生产者 | 消费者 |
|---|---|---|---|
| 视频帧 | `np.ndarray`，`[N,27,48,3]`，RGB，`uint8` | `predict_video` / `video_utils.get_frames` | `predict_frames`、可视化 |
| 单帧预测 | 一维浮点数组 `[N]` | `predict_raw`/`predict_frames` | `predictions_to_scenes`、`*.predictions.txt` |
| many-hot 预测 | 一维浮点数组 `[N]` | `predict_raw`/`predict_frames` | `*.predictions.txt`、可视化 |
| 场景区间 | `np.ndarray`，`[K,2]`，`int32`，起止帧均为闭区间 | `predictions_to_scenes` | `*.scenes.txt`、下游场景切分 |
| 可视化 | PIL `Image` | `visualize_predictions` | `*.vis.png` |

`main()` 对每个视频生成：

- `<video>.predictions.txt`：每帧两列，第一列 single-frame head，第二列 all-frames/many-hot head；
- `<video>.scenes.txt`：场景起始帧、结束帧；
- `--visualize` 时生成 `<video>.vis.png`。

若预测或场景文件已存在，CLI 跳过该视频；可视化文件已存在时只跳过可视化步骤。

### 5.2 场景标签与训练 TFRecord

`training/create_dataset.py::scenes2zero_one_representation` 把闭区间场景标注转换为：

- `one_hot`：每个转场区间取一个代表帧；
- `many_hot`：标记转场区间内的帧。

训练样本是 GZIP 压缩的 `tf.train.Example`：

| 类型 | 字段 |
|---|---|
| 普通训练 TFRecord | `scene: bytes`、`length: int64`、`width: int64`、`height: int64` |
| 过渡专用训练 TFRecord | `scene`、`one_hot`、`many_hot`、`length`、`width`、`height` |
| 测试 TFRecord | `frame: bytes`、`is_one_hot_transition: int64`、`is_many_hot_transition: int64`、`width`、`height` |

`input_processing.py` 按这些字段解码，随机截取 `shot_len=100` 的序列，执行翻转、颜色、裁剪、cutout、dissolve/hard cut 等增强，并以 `tf.data.Dataset` 完成 shuffle、batch、repeat、prefetch。普通训练通过 `concat_shots` 合成两个相邻片段和转场标签；`train_transition_pipeline` 直接读取过渡样本。

### 5.3 训练产物与评估结果

`training.py::get_options_dict` 展开 gin 中的文件 glob，创建 `logs/<log_name>_<时间戳>/`，保存 `config.gin` 与 TensorBoard summary。训练循环每 epoch 写 `weights-<epoch>.h5`，并通过 `Trainer.test_epoch` 记录场景级指标与可视化。`evaluate.py` 读取 `weights-<epoch>.h5` 和 NPY 帧，输出预测、错误图像、pickle 结果及 Precision/Recall/F1。

## 六、公开 API、CLI 与调用契约

### Python API

```python
from transnetv2 import TransNetV2

model = TransNetV2(model_dir=None)
video_frames, single_frame_predictions, all_frame_predictions = \
    model.predict_video("/path/to/video.mp4")
# 或：video_frames = np.ndarray([N, 27, 48, 3], dtype=np.uint8)
single_frame_predictions, all_frame_predictions = model.predict_frames(video_frames)
scenes = model.predictions_to_scenes(single_frame_predictions, threshold=0.5)
image = model.visualize_predictions(
    video_frames,
    predictions=(single_frame_predictions, all_frame_predictions),
)
```

### CLI

| 目标 | 命令/入口 | 说明 |
|---|---|---|
| 单视频/多视频推理 | `python inference/transnetv2.py <video> [--visualize]` | 读取 SavedModel，写预测/场景文本 |
| 已安装包推理 | `transnetv2_predict <video> [--visualize]` | `setup.py` 的 console script |
| 训练 | `python training/training.py configs/transnetv2.gin` | README 约定从 `training/` 目录运行 `training.py ../configs/...`，源码采用本地绝对导入风格 |
| 数据集 | `python create_dataset.py {train,test,train-transitions,test-npy} --mapping_fn ... --target_dir ...` | 可选 `--target_fn`、`--w`、`--h`、`--six_channels` |
| 评估 | `python evaluate.py <log_dir> <epoch> <directory> [--thr 0.5]` | 目录内读取 `*.npy` 与同名 `*.txt` |
| 权重转换 | `python convert_weights.py [--tf_weights ...] [--test]` | 生成 `transnetv2-pytorch-weights.pth` |
| Docker 推理 | `docker build -t transnet -f inference/Dockerfile .` | 镜像基于 `tensorflow/tensorflow:2.1.1-gpu` |

仓库没有 REST、gRPC、GraphQL 或消息协议 API；“API”边界是 Python 类/函数、文件格式和 CLI 参数。

## 七、依赖与运行环境

### 推理

- Python；`numpy`；TensorFlow（README 指定 `tensorflow==2.1`）；
- 直接视频推理需要系统 `ffmpeg` 与 `ffmpeg-python`；
- 可视化需要 `Pillow`；
- `setup.py` 声明包名 `transnetv2`、版本 `1.0.0`，但把 `inference/` 映射为包目录，并没有自动安装 TensorFlow 等依赖。

### PyTorch 推理与转换

- PyTorch README 给出 `pytorch=1.7.1`、`cudatoolkit=10.1`；
- TensorFlow 2.1 仍用于读取 SavedModel 和转换权重；
- `convert_weights.py` 同时导入 TensorFlow、PyTorch、NumPy。

### 训练

训练 Dockerfile 额外列出 `Pillow`、`h5py`、`keras_applications`、`keras_preprocessing`、`matplotlib`、`mock`、`numpy`、`scipy`、`sklearn`、`tensorflow-gpu`、`tqdm`、`ffmpeg-python`、`pyyaml`、`opencv-python`、`opencv-contrib-python`、`shapely`，并从 GitHub 安装 `gin-config`。部分源码还直接依赖 `pandas`、`gin`、`gin.tf.external_configurables`。

### 权重与 Git LFS

`.gitattributes` 把 `*.pb`、`*.index`、`*.data-*`、`*.h5` 标记为 Git LFS。当前工作树对应权重文件仅为约 129–133 字节的 LFS 指针文件，不是可直接加载的完整 SavedModel；README 也明确要求安装 git-lfs 后执行 `git lfs pull` 或手工下载权重。由于当前核对禁止安装与下载，不能把推理可运行性表述为已验证。

## 八、训练、评估与数据集流程

1. 下载 BBC Planet Earth、RAI、ClipShots，按需准备 IACC.3；
2. 修改并执行 `training/consolidate_datasets.py`，把不同数据集标注统一为场景区间与 mapping 文本；
3. 从 ClipShotsTrain 划出验证数据；
4. 用 `create_dataset.py` 生成普通训练、测试、过渡训练或 NPY 数据；
5. 用 `configs/transnetv2.gin` 或 `configs/transnetv2-realtrans.gin` 驱动 `training.py`；
6. `Trainer` 训练并写 TensorBoard、epoch 权重、验证可视化；
7. `evaluate.py` 对 NPY 测试集加载指定 epoch，按 `metrics_utils.evaluate_scenes` 的容差匹配统计 TP/FP/FN，输出 Precision、Recall、F1。

`transnetv2-realtrans.gin` 在 V2 配置上启用 `ClipShotsTrainTransitions` 和 `ClipShotsGradual-transitions`，把 `transition_only_data_fraction` 调为 `0.15`，并将 `concat_shots.hard_cut_prob` 调为 `0.412`。

## 九、测试、验证与当前证据边界

- 本仓没有独立 `tests/` 或 `test*.py` 文件；不能声称存在自动化单元测试/集成测试覆盖。
- `inference-pytorch/convert_weights.py --test` 是权重转换后的跨框架前向数值对齐检查，不是常规测试套件；且需要实际 TensorFlow 权重、PyTorch、TensorFlow 环境。
- README 的训练/评估命令是操作说明，不等于当前核对已执行；当前核对按约束没有安装、启动、构建或下载。
- 目标仓没有 `.codegraph/` 索引，专属平台代码地图不能提供该仓的源码符号覆盖；因此本文件的源码事实来自本地逐文件读取，而不是把其他仓库代码地图当作本仓证据。
- 已有 `细探-TransNetV2.md` 已读取并吸收，当前核对不删除；其“平台引入须独立进程”等建议属于跨项目裁决参考，不是本仓已有实现。

## 十、风险、备注与后续核验

### 已确认风险

1. **权重不可直接运行**：当前 LFS 权重是指针文件，未拉取真实内容；推理构造会在权重加载阶段失败，除非另行准备权重。
2. **依赖版本陈旧且未锁全**：README 以 TensorFlow 2.1、PyTorch 1.7.1/CUDA 10.1 为例，训练 Docker 又使用 `tensorflow/tensorflow:devel-gpu-py3` 与未完全固定的包版本；与现代 Python、macOS、Apple Silicon 的兼容性没有仓库内证据。
3. **数据/训练规模大**：README 明确训练数据数十 GB、导出可达数百 GB；训练依赖 GPU、ffmpeg、TFRecord 和外部数据集。
4. **脚本工作目录敏感**：训练模块使用 `from models import ...`、`import transnet` 等同目录导入，README 也要求从特定目录运行；作为已安装包或从仓库根目录直接调用训练脚本可能需要调整 `PYTHONPATH`/工作目录。
5. **`consolidate_datasets.py` 导入即执行**：模块顶层创建目录并立即遍历 BBC/RAI/ClipShots/IACC.3 数据集；不适合作为无副作用库导入，路径也包含硬编码数据集位置。
6. **输入边界主要用 `assert`**：推理形状、配置组合和数据约束大量依赖 `assert`；Python 使用 `-O` 时这些校验会被移除。
7. **边界样本未见测试保护**：例如 `predictions_to_scenes` 对空预测序列的行为没有测试证据；短视频、空数据、损坏视频、帧数与标注不一致的完整错误契约也未被测试套件固定。
8. **训练和推理权重契约分散**：TensorFlow SavedModel、`.h5` 训练权重、PyTorch `.pth` 三种权重形态分别由不同脚本处理，配置不兼容时转换脚本只能在运行期报不匹配。
9. **旧 TensorFlow API 兼容风险**：训练代码使用 `reset_states()`、`tf.contrib` 风格生态替代包和旧版 gin/TF 约定；不能凭源码静态阅读推断现代 TensorFlow 可运行。

### 备注

- `TransNetV2` 的默认公开推理路径是 TensorFlow SavedModel；PyTorch 分支是独立的 inference-only reimplementation，不应与训练路径混写。
- `single_frame_predictions` 适合转为场景边界；`many_hot` 主要用于渐变转场覆盖与训练辅助，二者同时保存在预测文件中。
- README 的 F1 数值是论文/项目说明中的结果声明，不是当前核对复测结果。
- MIT License 允许使用、修改、分发，但须保留版权与许可声明。

## 十一、结论与可借鉴边界

### 本仓已经证实的架构价值

- 用固定低分辨率帧序列和 100/50 滑窗把视频级推理转成可批处理的帧级分类问题；
- 同时保留 single-frame 与 many-hot 两个输出头，把硬切与渐变转场的监督拆开；
- 用 `FrameSimilarity` 与 `ColorHistograms` 补充局部时间上下文，主干仍是多尺度时间膨胀卷积；
- 训练、数据构造、评估和可视化在同一仓库闭环，数据格式（GZIP TFRecord/NPY/场景区间）清晰；
- TensorFlow 与 PyTorch 之间提供显式权重映射及前向对齐检查，而不是假设两边结构天然一致。

### 对平台的吸收建议

1. **吸收**：抽取“视频帧 → 模型推理 → 帧级概率 → 场景区间”的边界契约，作为视频处理能力的一个可替换 provider；固定输入尺寸、RGB 顺序、帧索引闭区间、阈值和容差都应写入契约。
2. **吸收**：把 `single_frame_predictions`、`many_hot`、场景区间和模型/权重版本作为可追溯结果字段，避免只输出一个不可解释的场景列表。
3. **吸收**：借鉴 100 帧窗口/50 帧步长和首尾 padding 的流式批处理策略，但必须补空视频、短视频、损坏权重、ffmpeg 失败和超时测试。
4. **待核**：任何生产接入前需在独立进程或独立 provider 环境隔离 TensorFlow/PyTorch/GPU/ffmpeg，先做真实环境指纹、资源上限、进程回收和模型加载失败验证。
5. **不直接照搬**：不把仓库的训练脚本、顶层副作用数据整理脚本、硬编码数据集路径和未锁定的旧深度学习依赖直接放入平台核心；不把论文 F1 宣传值当作本地验收证据。

**最终判断：** TransNetV2 是一个以 TensorFlow SavedModel 推理为主、训练闭环完整、PyTorch 推理复现为辅的镜头边界检测参考实现。当前本地仓库与远程 `master` 同步，但真实 LFS 权重未展开、无独立测试套件、依赖年代较旧，因此当前核对完成的是源码级架构建档，不是可运行性验收或生产接入裁决。

本文件已吸收此前 `细探-TransNetV2.md` 的源码分析结论；后续只维护本文件，旧细探笔记不再作为独立事实源。

## 十二、后续：通用底座映射与运行治理

本节不是把 TransNetV2 直接改造成平台组件，而是依据本仓已经读取的真实源码，裁决其视频读取、帧采样、模型推理、批处理、设备、权重和接口分别应该落在哪一层。以下“底座归属”是平台装配规划，不代表本仓已经存在这些平台能力；本任务只修改本架构文档，没有修改源码、依赖、配置或生产底座。

### 12.1 后续证据边界

- `inference/transnetv2.py:8-22` 是 TensorFlow SavedModel 的加载入口；`predict_video:74-88` 通过 `ffmpeg-python` 调系统 `ffmpeg`，将整个 stdout 解码为 `[N,27,48,3]` 的 RGB `uint8` 数组；`predict_frames:35-72` 实现首尾复制填充、100 帧窗口、50 帧步长和中间 50 帧裁剪。
- `inference/transnetv2.py:24-33` 的 `predict_raw` 调模型并输出 `single_frame_pred` 与 `many_hot`；`predictions_to_scenes:90-109` 把阈值后的帧序列转成闭区间场景；`main:153-189` 写相邻的 `.predictions.txt`、`.scenes.txt` 和可选 `.vis.png`。
- `training/video_utils.py:5-13` 与 `training/create_dataset.py:63-112,165-185` 重复使用 `ffmpeg` 抽帧；`training/evaluate.py:25-34,58-84` 再实现一套 100/50 批处理；这证明“解码”和“模型特定窗口策略”当前在项目脚本中有重复实现，不能原样复制成多个平台能力。
- `inference-pytorch/transnetv2_pytorch.py:51-87` 只定义推理模型，输入必须是 `torch.uint8` 的 `[B,T,27,48,3]`；`inference-pytorch/README.md:25-40` 明确由调用方 `load_state_dict`、`eval()` 和 `.cuda()`，没有项目级统一设备参数或 CPU/GPU 回退契约。
- `inference-pytorch/convert_weights.py:82-125` 读取 TensorFlow SavedModel、重映射变量/张量布局、保存 `transnetv2-pytorch-weights.pth`，`--test` 只做 10 组随机输入的前向数值对齐；它不是服务接口或常规测试套件。
- `training/input_processing.py:5-56,560-596` 使用 GZIP TFRecord、`batch_size=16`、`prefetch(2)`；`training/training.py:316-376` 由 gin 配置选择模型、恢复 `.h5` 权重、训练每 epoch 保存权重并评估。训练链与直接视频推理链必须分开治理。
- `setup.py:4-22` 只注册 `transnetv2_predict` console script；`inference/README.md:22-49` 只定义 Docker/CLI/文件输出，没有 REST、gRPC、GraphQL 或消息协议。当前仓库不存在服务接口实现。
- `inference/transnetv2-weights/*` 三个权重文件均为 Git LFS 指针，指向约 5.6 MB、5.5 KB、30.5 MB 的真实对象；本地未展开，故不能把模型加载或端到端推理写成已验证。
- 当前核对 `project_context` 错误绑定 `/Users/hekunhua/Documents/Agent/PHP/华世王镞_v3`，其代码地图/历史证据全部丢弃，不作为 TransNetV2 证据；当前核对改用目标仓库逐文件静态读取。目标仓库没有 `细探-*.md` 文件可供再次核对。

### 12.2 现有能力命中表与唯一归属

| 现有项目能力 | 真实实现/证据 | 通用底座唯一归属 | 裁决 |
|---|---|---|---|
| 视频文件读取、RGB 解码、缩放 | `inference/transnetv2.py:74-88`；`training/video_utils.py:5-13` 通过 `ffmpeg.input().output("pipe:", format="rawvideo", pix_fmt="rgb24", s="48x27").run(...)` | **视频解码支持库**：`视频读取/解码` 原子能力；Provider 可为受管 `ffmpeg` 执行单元 | 吸收接口，不吸收项目脚本；两处实现合并为一个能力 id，禁止模块直连 `ffmpeg-python` |
| 通用帧迭代/尺寸采样 | 当前每次把 `stdout` 全量转数组；训练数据也重复抽帧 | **视频解码支持库**：解码结果游标、帧数、尺寸、RGB/BGR、采样策略基础能力 | 升级；必须增加流式/分段读取和边界错误契约，不能沿用无界全量 stdout |
| TransNetV2 的 25 帧首尾 padding、100 帧窗、50 帧步长 | `inference/transnetv2.py:39-72`；评估侧另有 `training/evaluate.py:25-34` | **视觉模型支持库的 TransNetV2 适配器**：模型输入策略与 `27x48x3` 契约；通用采样器仍归视频解码支持库 | 吸收策略，消除 `predict_frames`/`get_batches` 双实现；窗口策略必须带模型版本/契约版本 |
| 模型前向、single/many-hot 输出 | TensorFlow `predict_raw:24-33`；PyTorch `forward:51-87` | **视觉模型支持库**：模型 Provider、前向、输出归一化、权重绑定 | 吸收边界；TensorFlow/PyTorch 是同一能力契约的可替换 Provider，不建两套媒体流程 |
| 批处理与批量内存预算 | TensorFlow 推理按 100 帧窗逐窗调用；训练 `batch_size=16`、`prefetch(2)`；PyTorch 输入含 B 维 | **运行核心负责预算/并发/排队；视觉模型支持库负责模型允许的 batch 形状** | 升级；`batch_size`、最大帧数、CPU/GPU 内存上限必须显式进请求/Provider 契约，不能由调用方任意放大 |
| GPU/CPU 设备 | Docker 推理基于 `tensorflow/tensorflow:2.1.1-gpu`；PyTorch README 由调用方 `.cuda()`；源码无统一 `device` 参数 | **运行核心**分配设备租约/预算；**视觉模型支持库**实际绑定 TensorFlow/PyTorch device | 待核后吸收；先固定 CPU 可运行路径、GPU 可用性探测、设备不匹配和 OOM 错误码，不能假设 GPU 永远存在 |
| SavedModel、`.h5`、`.pth` 权重 | `tf.saved_model.load`；`training.py:356-367`；`convert_weights.py:82-125` | **视觉模型支持库**拥有权重清单、格式/摘要/兼容性、加载和卸载；**运行核心**拥有环境指纹/缓存/资源租约 | 吸收权重契约；转换工具保持离线构建工具，不进入在线请求链；LFS 指针未展开前只能标“不可用/未验证” |
| 场景转换、预测结果组织、可视化 | `predictions_to_scenes:90-109`、`visualize_predictions:111-150`、CLI `:172-189` | **媒体模块**：镜头边界领域编排、阈值/闭区间语义、结果制品 | 吸收领域语义；可视化是可选后处理，不得阻塞主预测结果，也不能由网关重复实现阈值算法 |
| CLI/文件输出 | `setup.py:12-22`、`inference/transnetv2.py:153-189` | **媒体模块公开入口**由网关适配；**网关**只收参/回结果，**运行核心**提供受管制品引用 | 改为规划接口；当前 CLI 不是服务接口，输出路径旁写和存在即跳过不能直接成为生产幂等语义 |
| HTTP/MCP/服务路由 | 仓库全文未发现服务框架/路由；`ARCHITECTURE.md:203` 已确认无协议 API | **统一网关**（HTTP 为主，MCP 仅薄适配） | 不吸收现有实现；新建薄适配入口，禁止把 TensorFlow、PyTorch、ffmpeg 或 GPU 加载到网关进程 |

### 12.3 唯一推理链路

生产候选链路只允许有一个权威 `request_id` 和一个能力 id；TensorFlow 与 PyTorch 只是视觉模型 Provider，不是两条业务链：

```text
网关请求
  → 媒体模块：镜头边界检测(request_id, 输入制品引用, 模型/阈值/输出选项)
  → 运行核心：校验输入、发放 CPU/GPU/内存/时间/临时目录预算
  → 视频解码支持库：唯一视频读取/解码 Provider
  → 视频解码支持库：按模型契约输出 RGB uint8 帧游标/受限帧批
  → 视觉模型支持库：TransNetV2 输入适配器
      → 100 帧窗口 + 50 帧步长 + 25 帧首尾 padding
      → TensorFlow SavedModel 或 PyTorch Provider（二选一，由能力注册表选择）
      → single-frame/many-hot 概率
  → 媒体模块：阈值、场景闭区间转换、结果元数据/可选可视化
  → 运行核心：提交受管制品、写释放/资源/错误证据
  → 网关：统一结果/事件/制品引用
```

链路不允许出现以下侧路：

1. 媒体模块或网关直接 `import tensorflow`、`torch`、`ffmpeg`，或直接创建 GPU 上下文；
2. TensorFlow 与 PyTorch 各自实现一套 `predict_video`、场景转换、错误码和输出写入；
3. 训练脚本 `training/create_dataset.py` 或 `evaluate.py` 旁路在线服务链；训练和离线转换只产生版本化模型制品；
4. 网关把整段视频、整段帧数组或模型对象作为无界 JSON/Base64 穿透；大对象只传受管制品引用；
5. 通过“已有 `.predictions.txt` 就跳过”代替统一幂等键。幂等由 `request_id + idempotency_key + 输入摘要 + 模型/权重摘要 + 契约版本` 决定。

### 12.4 资源生命周期与所有权

| 资源 | 创建/持有 | 正常完成 | 业务失败 | 超时/取消 | Provider/宿主崩溃 | 当前源码缺口 |
|---|---|---|---|---|---|---|
| 输入视频路径/制品 | 调用方借用，运行核心校验只读权限；视频解码支持库读取 | 关闭读取句柄，保留输入引用 | 不删除调用方输入，记录摘要和失败原因 | 停止读取，输入引用不回收为输出 | 进程重启后输入仍由制品层管理 | 当前直接接收字符串路径，无制品权限/摘要/所有权契约 |
| `ffmpeg` 子进程、stdin/stdout/stderr | 视频解码 Provider 创建；运行核心拥有进程组 | 关闭管道，`wait` 回收，核对 PID/临时目录 | 读取受限 stderr，返回解码错误 | 真实终止进程组而非仅放弃 Python 调用，排空并回收 | 记录退出码/信号，清理孤儿进程 | 当前 `.run(capture_stdout=True, capture_stderr=True)` 同步执行，无显式 deadline/cancel/进程组回收代码；`err` 未进入统一错误结果 |
| 解码帧 `np.ndarray`/帧游标 | 解码 Provider 创建；采样/模型适配器借用或接管批 | 每批消费后释放引用，最终帧缓存清零 | 释放已创建批，禁止返回半截成功数组 | 取消点丢弃当前批，不能继续写结果 | Provider 重启后不得复用旧内存引用 | 当前把完整 stdout 一次性 `frombuffer`，长视频内存峰值随视频长度增长 |
| TF/PyTorch Tensor 与 GPU 上下文 | 视觉 Provider 创建；运行核心发设备/显存预算 | 释放批 tensor；模型缓存按租约/上限保留 | 清理当前 batch 和异常上下文 | 先协作停止，不能强杀主线程；不可协作时杀受管 Provider | 隔离 Provider，销毁/重建上下文，记录 OOM/信号 | 当前没有统一 device、显存上限、清理或重启实现；PyTorch `.cuda()` 由示例调用方决定 |
| 模型权重与模型对象 | 视觉 Provider 按权重摘要加载；Provider 私有持有 | 模型可进入有界缓存，记录版本/设备/环境指纹 | 加载失败不得留下“健康”模型实例 | 取消加载时删除临时下载/转换物，回收上下文 | 旧实例标失败并隔离，重启后重新健康检查 | LFS 仅指针；TF 构造器加载异常有限，未形成统一模型租约 |
| 预测数组/场景数组 | 视觉 Provider 产出；媒体模块转换 | 交给制品写入器，带模型/权重/输入摘要 | 失败不可发布半截制品 | 取消结果不应冒充完整结果；临时结果清理 | 崩溃后只保留可验证的临时证据 | 当前预测先全量拼接，CLI 后置写文件，没有统一提交事务 |
| 临时目录与中间制品 | 运行核心按 `request_id` 创建并持有 | 原子提交后按策略保留摘要/制品，删除中间物 | `finally` 清理，清理失败显式暴露 | 超时/取消后强制清理并验证不存在 | 重启扫描孤儿目录并按 owner/TTL 回收 | 当前推理没有临时目录；训练/评估直接写 `logs/`、`results/`，无请求级隔离 |
| 输出 `.txt`/`.png`/模型 `.pth` | 当前 CLI 直接在输入旁写；转换工具写当前目录 | 只允许临时文件→原子 rename；结果引用回传 | 失败不覆盖旧制品，保留失败证据 | 取消不产生“完成”文件 | 崩溃恢复只认完整摘要/提交标记 | 当前 `np.savetxt`/`PIL.Image.save` 无原子提交、摘要或清理协议；存在文件即跳过是弱幂等 |

资源责任必须跟随调用链传递：创建者声明 owner，转移必须显式，借用不得跨进程；成功、业务失败、超时/取消、崩溃四种终态都必须有释放结论。模型缓存若采用常驻模式，也必须有最大实例数、最大空闲时间、显存/内存预算和排空状态，不能把“进程没退出”当作资源治理完成。

### 12.5 超时、取消、OOM、崩溃与错误契约

| 场景 | 本仓真实行为 | 底座统一语义 | 验收要求 |
|---|---|---|---|
| 输入非法/空视频/短视频 | 形状检查主要依赖 `assert`；`predict_frames` 直接访问 `frames[0]`/`frames[-1]`；空序列和极短序列没有测试保护 | `INPUT_INVALID` 或 `EMPTY_VIDEO`，不可进入模型 Provider；短视频应由窗口适配器明确 padding 语义 | 空、1 帧、99/100/101 帧、非 RGB、错误尺寸、损坏路径各有固定结果 |
| 解码失败/缺 `ffmpeg` | `predict_video` 捕获缺 Python wrapper；`ffmpeg.run` 失败由库异常上抛，stderr 只被捕获未转统一结果 | `DECODER_UNAVAILABLE`、`DECODE_FAILED`，分别标可重试性和 stderr 摘要 | 缺二进制、缺 wrapper、非视频、截断视频、退出非零；进程组无残留 |
| 模型/权重缺失或损坏 | 权重目录缺失抛 `FileNotFoundError`；SavedModel `OSError` 包装为 `IOError`；LFS 指针无法当模型加载 | `WEIGHTS_NOT_FOUND`、`WEIGHTS_CORRUPT`、`MODEL_PROVIDER_UNAVAILABLE` | 指针文件、错误摘要、版本不兼容、Provider 重启后健康状态均可区分 |
| 超时 | 当前 ffmpeg 与窗口推理为同步循环，无 deadline 参数 | 运行核心注入硬截止；阻塞解码/原生推理由独立进程终止；返回 `TIMEOUT` 且 `retryable` 明确 | 真正超过截止后进程/队列/临时目录消失；不能只是 Python 返回超时而后台继续跑 |
| 取消 | 仓库没有取消令牌、取消 API 或取消检查点 | `CANCEL_REQUESTED → CANCELLED`；可协作任务检查点退出，不可协作任务由运行核心杀受管进程组 | 取消前/解码中/批间/写出前四个位置都不发布成功制品，释放幂等 |
| CPU/GPU OOM | 没有显式捕获或预算；全量帧数组、100 帧窗口和 PyTorch 直方图可能放大内存；TensorFlow GPU 镜像不等于已获得 GPU | `RESOURCE_EXHAUSTED`/`GPU_OOM`，记录峰值和设备；隔离 Provider，必要时降级 CPU/拒绝重试，禁止盲目无限重启 | CPU 内存上限、GPU 显存上限、超大视频、并发 batch 压力；OOM 后进程/显存/临时目录可复用或已清理 |
| Python/原生 Provider 崩溃 | 本仓无守护、重启、信号证据；TensorFlow/PyTorch/ffmpeg 仍可能带原生崩溃风险 | `PROVIDER_CRASHED`，记录退出码/信号/最后阶段；运行核心隔离并有界重启 | 真实 SIGTERM/SIGKILL/非零退出；PID、端口、句柄、GPU、临时目录归零；不得把重启次数无限放大 |
| 输出写入失败/重复请求 | CLI 直接写输入旁文件；已有预测/场景文件即跳过，未验证内容摘要和模型版本 | `OUTPUT_COMMIT_FAILED`；幂等键决定复用，制品提交原子化 | 磁盘满、权限拒绝、目标已存在、重复请求、旧版本制品均返回可解释结果 |

统一执行请求至少传递：

```text
request_id + capability_id + contract_version
input_artifact + model_id + weight_digest
deadline + cancel_token + idempotency_key + resource_budget
```

统一结果至少包含：

```text
success + value/artifact_ref + error_code + error_message
retryable + request_id + model/weight/input_digest
device + resource_usage + release_status + evidence_ref
```

### 12.6 临时文件、缓存和制品边界

本仓当前没有“请求级临时文件”实现，但已有三类写盘行为必须在底座中分开：

1. **在线推理结果**：`<video>.predictions.txt`、`<video>.scenes.txt`、可选 `<video>.vis.png`（`inference/transnetv2.py:167-189`）。未来应写入 `request_id` 临时目录，校验完整内容/摘要后原子提交到制品仓库，网关只返回 `artifact_ref`；不得由网关进程任意拼接用户路径。
2. **离线训练/评估**：`training/training.py:54-64,365-376` 的 `logs/<log_name>_<timestamp>/`、`weights-<epoch>.h5`、TensorBoard 与可视化；`training/evaluate.py:73-106` 的 `results/`、错误 PNG、pickle。它们是离线工作区制品，不应混入在线媒体模块或共享在线缓存。
3. **离线权重转换**：`convert_weights.py:119-125` 在当前目录生成 `transnetv2-pytorch-weights.pth`。它只能进入模型制品构建/登记流程，必须记录 TensorFlow 源权重摘要、映射版本、PyTorch 模型版本和对齐结果；不能在每次服务请求中转换。

建议的临时目录命名为 `临时根/<request_id>/<attempt_id>/`，目录内至少区分 `decode/`、`batches/`、`result/`；路径必须拒绝绝对路径和 `..` 逃逸，文件大小/总量/压缩比有上限。正常完成只保留受管制品和摘要，失败/取消/崩溃按 TTL 回收；回收器必须在启动时扫描孤儿目录并记录未清理项。当前源码没有这些保证，不能标记为已实现。

### 12.7 L0-L4 分层落点

| 层级 | 责任 | TransNetV2 对应事实 | 不应承载 |
|---|---|---|---|
| **L0 设备/第三方 Provider** | `ffmpeg`、TensorFlow、PyTorch、CPU/GPU 驱动、SavedModel/`.h5`/`.pth` 文件的实际调用 | Dockerfile 指定 TensorFlow GPU/ffmpeg；推理源码导入 TensorFlow、ffmpeg；PyTorch 示例调用 CUDA | 网关路由、场景业务规则、持久化任务状态 |
| **L1 视频解码与视觉模型支持库** | 原子能力契约、Provider 隔离、输入/输出形状、错误转换、权重格式与设备适配 | `video_utils.get_frames`/`predict_video`、`predict_raw`、PyTorch `forward` 和 `convert_weights` 是候选实现 | 训练数据集业务编排、HTTP 会话、无界全量内存 |
| **L2 媒体模块** | 镜头边界检测领域流程：调用解码、窗口推理、概率阈值、场景闭区间、可选可视化和制品组织 | `TransNetV2.predict_frames`、`predictions_to_scenes`、CLI 输出共同表达该领域流程，但当前仍混在类/脚本内 | 直接加载 GPU/第三方库、启动 ffmpeg、维护线程池/取消/重启 |
| **L3 运行核心** | 请求状态、能力注册、队列/背压、租约、deadline/cancel、CPU/GPU/内存预算、进程组、缓存、临时目录、崩溃恢复和证据 | 本仓没有对应实现；这是接入平台时的必需治理边界 | 场景阈值算法、模型层权重映射、HTTP 参数解析 |
| **L4 统一网关** | HTTP/JSON（MCP 仅薄适配）的认证/授权、请求 id、能力路由、参数转发、结果/事件/制品引用透传 | 本仓只有 Python API/CLI，没有服务接口 | 导入 TensorFlow/PyTorch/ffmpeg、持有模型/帧数组/GPU 上下文、实现第二套错误/取消 |

### 12.8 复用、升级、新建、废弃裁决

| 裁决 | 对 TransNetV2 的结论 |
|---|---|
| **吸收/复用** | RGB `uint8`、`27x48` 输入、single/many-hot 双输出、场景闭区间和模型/权重摘要字段；100/50 滑窗与首尾 padding 作为 TransNetV2 模型适配策略；TensorFlow/PyTorch Provider 可共享同一模型能力契约 |
| **升级现有支持库** | 视频解码能力：统一 `ffmpeg` 调用、流式帧输出、尺寸/颜色空间、stderr、退出码、deadline/cancel、进程组清理；运行核心：GPU/CPU/内存预算、Provider 健康与崩溃回收、受管临时目录 |
| **新建原子能力** | 若现有底座无对应能力，登记“视频解码.读取RGB帧”“视觉模型.加载权重”“视觉模型.批量推理”“视觉模型.释放执行单元”四类原子能力；先做能力搜索和契约复用裁决，不能以本项目目录名直接建一套 TransNetV2 平台内核 |
| **模块升级** | 建立唯一“镜头边界检测”媒体模块，组合解码、TransNetV2 适配、场景转换和制品提交；训练/评估另作为离线工作流，不进入在线模块 |
| **网关适配** | 新增统一网关薄适配，仅暴露 `镜头边界检测` 能力；输入输出用制品引用/摘要，错误/超时/取消透传统一结果；本仓 CLI 仅保留兼容适配，不成为第二入口 |
| **废弃/隔离** | 废弃在线链路中的整段 `capture_stdout`、输入旁直接写文件、已有文件即跳过、网关直连第三方、训练脚本在线复用；隔离 `consolidate_datasets.py` 的导入即执行副作用与硬编码数据集路径 |
| **待核** | TensorFlow/PyTorch 在目标宿主上的实际版本、GPU 可用性、CPU 性能、真实权重完整性、模型 Provider 是否必须独立进程、转换后数值误差阈值；这些没有本仓运行证据 |

### 12.9 装配计划与验收契约

当前核对只形成文档级装配计划，未启动任何生产实现：

1. **契约冻结**：冻结 `视频解码.读取RGB帧`、`视觉模型.批量推理`、`镜头边界检测` 的输入/输出/错误/资源字段；明确 `request_id`、模型/权重摘要、设备、帧索引闭区间和阈值。
2. **能力搜索与租约**：在现有能力目录中先搜索解码、图像缩放、进程组、GPU/资源监督和制品写入能力；命中则复用并升级，不命中才登记上述新能力。任何实现前都要有 provider 占用租约，避免并行建立第二套能力。
3. **视频 Provider 工作包**：封装唯一 `ffmpeg` 解码入口，支持受限流式读取、RGB/尺寸契约、stderr 摘要、超时/取消/崩溃回收和零残留验证；禁止返回无界整段 stdout。
4. **视觉 Provider 工作包**：分别适配 TensorFlow SavedModel 与 PyTorch `.pth`，共用输入/输出契约；模型加载、设备选择、batch 上限、OOM、权重摘要和释放均由 Provider/运行核心承担。
5. **媒体模块工作包**：只组合公开能力，保留 TransNetV2 的 100/50/25 窗口策略、`single_frame`/`many_hot` 和 `predictions_to_scenes` 语义；统一场景结果和可选可视化制品，禁止重复实现解码或设备治理。
6. **运行核心工作包**：接入 deadline、取消令牌、资源预算、Provider 状态机、独立进程/进程组、临时目录、缓存上限、崩溃回收、证据与幂等；四种终态都必须真实读回资源现场。
7. **网关工作包**：最后接入 HTTP 能力入口；网关只解析参数、授权、路由、透传统一结果和制品引用，不导入 TensorFlow/PyTorch/ffmpeg，不持有 Provider 对象。

验收契约最低覆盖：

| 验收面 | 必须证明 |
|---|---|
| 正常链路 | 真实视频 → 解码 → 窗口批 → 模型 → 两个概率头 → 场景闭区间 → 受管制品；结果含输入/模型/权重摘要 |
| 边界 | 空/短/非 RGB/错误尺寸/帧数边界/损坏视频/损坏权重/缺 ffmpeg/缺 GPU |
| 资源 | 正常、业务失败、超时/取消、Provider 崩溃四终态；PID、管道、GPU/CPU 内存、句柄、临时目录无无界残留 |
| 可靠性 | 重复请求按幂等键复用或明确冲突；输出原子提交；旧制品不被错误覆盖；失败证据可读 |
| Provider | TensorFlow 与 PyTorch 共用契约；权重转换只走离线链；设备/版本/环境指纹可追溯；缺 Provider 返回明确不可用而非假成功 |
| 服务 | 网关真实 HTTP 请求/响应、deadline/cancel、统一错误码和制品引用；没有第三方库穿透网关 |
| 证据等级 | 代码存在、测试存在、静态检查、真实运行、外部依赖实测分栏记录；本仓当前仅有源码/配置/文档/LFS 指针和 AST 静态证据，无端到端运行证据 |

### 12.10 后续最终判断

**吸收**的是 TransNetV2 的模型输入/窗口/双输出/场景闭区间等可验证领域契约；**升级**的是唯一视频解码能力与运行核心资源治理；**隔离**的是 TensorFlow、PyTorch、ffmpeg、GPU 和 LFS 权重；**新增**的是必要的模型 Provider/媒体模块/网关适配边界；**不吸收**的是项目脚本的重复解码、全量 stdout、旁路文件写入、无界缓存、在线复用训练脚本和“已有文件即跳过”语义。

当前结论等级为 **L1/L2 候选边界已能从源码确认，L3/L4 仅完成架构映射，未完成运行验证**。真实生产接入必须在权重展开、依赖与设备环境可用后，按上述验收契约执行；在此之前不得声称 TransNetV2 已经作为平台视频能力上线。

### 12.11 后续通用底座映射卡片

为避免把“视频模型接入”误解为只搬运 `predict_video`，当前核对将每个横切面收敛为一个可替换的底座边界。下表是面向后续实现的最小责任矩阵；“已证实”表示能从本仓源码直接确认，“规划”表示平台接入时必须补齐，均不表示本仓已经实现。

| 横切面 | L0 | L1 | L2 | L3 | L4 | 本仓状态 |
|---|---|---|---|---|---|---|
| 视频输入 | 系统 `ffmpeg`、文件系统 | 解码、RGB、尺寸、帧游标 | 镜头检测输入适配 | 输入制品权限、摘要、大小/时长限制 | 认证后传入 `input_artifact` | 已证实文件路径 + `ffmpeg`；其余规划 |
| 帧采样 | 解码器实际抽帧 | 流式/分段读取、采样率、颜色空间 | 100 帧窗、50 帧步长、25 帧边界 padding | 帧数预算、背压、取消点 | 只传制品引用和采样参数 | 100/50/25 与 `27x48` 已证实 |
| 模型推理 | TensorFlow/PyTorch、CPU/GPU 驱动 | 输入适配、前向、sigmoid、输出形状 | 双概率头与场景语义 | Provider 租约、隔离、健康、重启 | 能力路由与统一结果透传 | TF 默认链路、PyTorch 复现已证实 |
| 批处理 | Tensor/TensorFlow 运行时 | 模型允许的 batch 形状 | 窗口结果拼接与原帧裁剪 | 并发、队列、背压、内存上限 | 请求级超时与排队状态 | 推理逐窗；训练 `batch_size=16` |
| CPU/GPU | 设备驱动与运行时 | device 绑定和可用性探测 | 设备无关的模型流程 | CPU/GPU/显存租约、OOM、降级策略 | 不暴露设备对象 | GPU 仅由镜像/示例暗示，未验证 |
| 权重 | LFS/文件存储 | SavedModel、`.h5`、`.pth` 加载 | 模型版本与输出契约 | 摘要、缓存、兼容性、卸载 | 只接受 `model_id`/摘要 | 当前为 LFS 指针，未可运行验证 |
| 服务接口 | 外部进程/第三方运行时 | Provider 进程边界 | `镜头边界检测` 公开能力 | 请求状态、事件、制品提交 | HTTP/JSON 薄路由，MCP 仅适配 | 本仓只有 Python API/CLI，无服务 |
| 资源释放 | OS 进程、管道、句柄 | Tensor、帧批、模型上下文 | 结果临时对象 | finally、进程组、临时目录、缓存回收 | 释放状态透传 | 本仓缺少显式释放协议 |
| 失败治理 | 信号、退出码、驱动错误 | 错误转换、stderr 摘要 | 领域失败语义 | deadline/cancel/OOM/崩溃状态机 | 错误码、retryable、request_id | 本仓主要是异常上抛 |

#### 请求与终态状态机

通用底座不应把同步函数返回当作完整生命周期。每次请求至少按以下状态推进，状态转换必须幂等，并在终态写入 `release_status`：

```text
ACCEPTED
  → VALIDATED
  → DECODING
  → BATCHING
  → INFERENCING
  → COMMITTING
  → SUCCEEDED

VALIDATED/DECODING/BATCHING/INFERENCING/COMMITTING
  ├─ 业务错误 → FAILED
  ├─ deadline 到期 → TIMED_OUT
  ├─ cancel_token 生效 → CANCELLED
  └─ Provider 非零退出/信号/OOM → CRASHED 或 RESOURCE_EXHAUSTED
```

其中：

1. `TIMED_OUT`、`CANCELLED` 和 `CRASHED` 都必须先停止或杀死受管解码/推理进程组，再回收管道、帧批、临时目录和设备租约；不能仅中断等待线程。
2. `FAILED` 不得提交半截预测或场景制品；已有旧制品不能因为本次失败被覆盖。成功提交必须使用临时文件、内容摘要和原子改名。
3. `RESOURCE_EXHAUSTED` 要区分 CPU 内存、GPU 显存、磁盘和队列容量，并记录设备、峰值和是否可重试；禁止无条件重启或无限重试。
4. Provider 崩溃后，运行核心只能在有界次数内重建实例；未重新通过权重/设备健康检查的实例不得接收请求。

#### 最小统一契约

```text
输入：
  request_id, capability_id, contract_version,
  input_artifact, sampling, model_id, weight_digest,
  deadline, cancel_token, idempotency_key, resource_budget

输出成功：
  scenes, single_frame_predictions, many_hot_predictions,
  input_digest, model_id, weight_digest, device,
  resource_usage, release_status, evidence_ref

输出失败：
  success=false, error_code, error_message, retryable,
  request_id, phase, provider_exit, release_status, evidence_ref
```

`sampling` 必须记录原始帧率/采样率（若可得）、目标尺寸、颜色顺序、窗口长度、步长、padding 和帧索引语义；不能只记录最终场景数组。`device` 必须记录 `cpu` 或具体 GPU/运行时标识，不得由网关猜测。`evidence_ref` 指向运行证据而不是论文指标。

## 十三、分段审计补遗：实现边界、失败路径与文档裁决

本节按输入/采样/窗口/模型/设备/权重/API/测试/文档分段补齐审计结论。它只描述本仓源码和文档现状；没有把平台规划写成已有实现。

### 13.1 输入与采样

- `predict_video` 和 `training/video_utils.get_frames` 都使用 `ffmpeg-python` 的同步 `.run(capture_stdout=True, capture_stderr=True)`，把全部 stdout 复制到 Python/Numpy 内存；`err` 被接收但丢弃，未按退出码、stderr、字节数或帧数建立错误契约。
- `np.frombuffer(...).reshape([-1, 27, 48, 3])` 依赖输出字节数恰好是完整 RGB 帧的整数倍；截断或异常 ffmpeg 输出会在 reshape 处失败，不能被当作空视频或成功结果。
- 参考实现只固定目标尺寸 `48x27`、`rgb24` 和 RGB 顺序，没有固定原始视频帧率、时长、解码帧数上限或背压策略。平台适配必须把这些作为输入预算和采样元数据，而不是隐含在命令行参数中。
- 训练输入是另一条离线路径：GZIP TFRecord/NPY、随机片段、增强、shuffle、repeat、prefetch；不得把训练的 `batch_size=16` 或 `prefetch(2)` 解释为在线请求默认值。

### 13.2 窗口与结果拼接

- 在线 `predict_frames` 使用首尾各复制 25 帧、100 帧窗口、50 帧步长，每窗只保留 `[25:75]` 的 50 帧，最后裁剪到原始长度；`training/evaluate.py::get_batches` 又独立复制这套规则，存在漂移风险。
- `frames[0]` 和 `frames[-1]` 在空数组上直接失败；99/100/101 帧、单帧和非整数 50 帧边界虽有确定的 padding 算法，但仓库没有测试把它们固定为契约。
- `predictions_to_scenes` 采用 `>` 阈值和闭区间 `[start, end]`。空预测序列并没有显式错误分支，可能落入 `[0, -1]` 的退化场景；这必须在适配器中显式拒绝或定义，不得静默传播。
- 在线预测把每个窗口结果追加到 `predictions`，结束后再完整 `concatenate` 两个数组；评估路径同样累计全部预测和结果，峰值内存随视频/数据集增长。

### 13.3 模型、设备与 OOM 热点

- TensorFlow SavedModel 在构造函数中加载，输入先转 `tf.float32`；PyTorch `forward` 要求 CPU/GPU 上的 `torch.uint8 [B,T,27,48,3]`，内部转为 `[B,3,T,H,W]` 浮点。两个实现都把输入约束主要写成 `assert`，使用 `python -O` 会移除检查。
- PyTorch README 要求调用方自行 `load_state_dict()`、`eval()`、`.cuda()`；源码没有统一 device 选择、显存预算、CPU 回退、OOM 分类或释放确认。`eval()` 只改变模块行为，不是资源租约或健康检查。
- `FrameSimilarity` 为 `[B,T,T]` 相似度矩阵创建重复的 batch/time/lookup 索引；`ColorHistograms` 为每个 batch/time 建立 `512` bin 直方图，并再次计算 `[B,T,T]` 相似度。增大 batch、并发或时间窗会放大 GPU/CPU 峰值，OOM 不能只包成普通 Python 异常。
- 设备不可用、TensorFlow/PyTorch 原生崩溃、驱动 OOM 和 Python 异常必须由受管 Provider 分层区分；当前仓库没有这些分类、隔离进程、重建次数上限或健康检查实现。

### 13.4 权重与制品生命周期

- TensorFlow SavedModel 是默认在线权重；训练产生 `.h5`，转换脚本从 SavedModel 映射并写 `transnetv2-pytorch-weights.pth`。转换脚本的 `--test` 是十组随机输入的跨框架前向对齐检查，不是完整测试，也没有以失败退出码保证阈值通过。
- 当前权重文件受 Git LFS 管理；本地工作树若只有指针文件，`tf.saved_model.load` 不能证明可加载。加载前必须验证 LFS/文件摘要、格式、模型契约版本和来源权重摘要。
- `convert_weights.py` 直接在当前目录写 `.pth`，没有临时文件、原子替换、摘要登记或失败清理；它只能作为离线模型制品构建步骤。在线请求不得触发转换，也不得把未通过对齐检查的制品注册为健康。
- CLI 直接在输入视频旁写 `.predictions.txt`、`.scenes.txt`、`.vis.png`，并以“文件存在”跳过；这不是带输入/模型/权重摘要的幂等语义。失败、取消、超时或崩溃期间不能发布半截文件，也不能覆盖旧版本制品。

### 13.5 API、取消与崩溃语义

- 本仓实际公开边界只有 Python 类/函数、`transnetv2_predict` console script 和文件输出，没有 REST、gRPC、GraphQL、任务状态、持久化取消或消息协议。
- `predict_video`、`predict_frames`、`predict_raw` 和可视化均为同步调用，没有 cancel token、deadline、阶段状态或检查点；取消调用线程不能保证 ffmpeg 子进程和原生推理停止。
- 解码、推理或写盘抛异常时没有统一 `error_code/retryable/release_status`；强杀或原生崩溃后也没有 PID、管道、GPU、临时文件和输出完整性对账。因此“函数返回”不能作为释放证据。
- 平台接入仍应使用已有状态机：`accepted → validated → decoding → batching → inferencing → committing → succeeded`，并将 `failed`、`timed_out`、`cancelled`、`resource_exhausted`、`provider_crashed` 作为互斥终态；终态前先停止受管进程组和未提交写入。

### 13.6 测试与验证证据

- 仓库没有 `tests/`、`test*.py` 或常规单元/集成测试；不能声称输入边界、解码失败、OOM、取消、崩溃、原子制品或资源释放已有覆盖。
- `convert_weights.py --test` 依赖真实 TensorFlow/PyTorch 权重和运行环境，仅验证十组随机 `[2,100,27,48,3]` 前向数值接近；它不验证视频解码、窗口边界、场景闭区间、CLI 幂等或异常清理。
- README、Dockerfile 和 CLI 命令是运行说明，不是当前核对执行证据。当前核对未安装依赖、未拉取 LFS、未启动 ffmpeg/GPU、未运行权重转换或端到端推理。
- 最低新增验证面应包括空/短/99/100/101 帧、错误尺寸/颜色、截断视频、缺 ffmpeg、LFS 指针/损坏权重、CPU/GPU 不可用与 OOM、解码中/批间/写出前取消、超时、SIGTERM/SIGKILL、磁盘写失败、重复请求和旧制品保护。

### 13.7 文档重复与冲突裁决

- `README.md`、`inference/README.md`、`inference-pytorch/README.md` 和 `细探-TransNetV2.md` 主要是使用说明或早期研究笔记；它们可保留为背景/入口，但不再独立定义运行治理事实。
- `细探-TransNetV2.md` 的“GPU 友好”“SOTA F1”等表述是项目/论文定位，不是本地运行证据；本文件以源码确认、LFS 状态和实际验证等级为准，不把宣传指标写成验收结果。
- README 的“直接使用”“自动推断权重”和 Docker 的 `--gpus 1` 只表示预期用法；它们不覆盖当前 LFS 指针、设备可用性、版本兼容性、OOM、取消或资源回收缺口。
- 本文件与旧细探笔记出现重复时，以本文件的分段事实、证据边界和“已实现/规划/未验证”标记为准；不删除旧笔记，以免破坏研究索引，但禁止将其作为第二套架构事实源。

### 13.8 审计结论

当前仓库可确认的是模型形状、RGB 采样目标、100/50/25 窗口、双概率头、闭区间场景转换、TF/PyTorch 结构及离线转换路径；不可确认的是真实权重可加载、设备可用、在线吞吐、OOM 恢复、取消生效、Provider 崩溃回收和制品原子提交。任何生产接入必须先完成受管解码/模型 Provider、有限内存与设备租约、取消/截止传播、原子制品提交和真实资源证据，再提升验证等级。

#### 三类实施边界

- **可直接复用的模型事实**：RGB `uint8`、`27x48x3`、100/50 窗口、25 帧首尾复制、single-frame/many-hot 双头、阈值后闭区间场景；这些是 TransNetV2 适配器的模型契约，不是通用视频解码器的默认值。
- **必须升级的底座能力**：流式解码、受限批处理、CPU/GPU 资源租约、deadline/cancel、进程组回收、权重摘要、原子制品提交、幂等和崩溃恢复。现有 `capture_stdout`、同步 `.run()` 和输入旁直接写文件均不足以承担这些职责。
- **必须隔离的运行单元**：TensorFlow、PyTorch、ffmpeg、GPU 上下文和权重转换。它们可以作为 L0 Provider 被 L1 调用，但不得进入 L2 媒体模块、L3 运行核心或 L4 网关的直接依赖面。

本卡片完成的是后续架构映射和责任冻结；由于真实 LFS 权重、TensorFlow/PyTorch/ffmpeg、GPU 和服务宿主均未在当前核对启动，L0 运行事实、L3 资源回收事实和 L4 服务事实仍为待验收项。
