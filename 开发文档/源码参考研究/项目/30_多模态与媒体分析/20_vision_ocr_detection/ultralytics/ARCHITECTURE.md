# Ultralytics 架构档案

> 首轮全量架构建档。本文是本仓库的单一架构事实源；源码、依赖、测试和配置均以实际文件为准。
>
> **目标项目**：`/Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/20_vision_ocr_detection/Ultralytics`
>
> **本地快照**：`main`，提交 `914074cd1ae3920093022b187f3326e18d845016`，版本 `ultralytics.__version__ = "8.4.104"`。
>
> **远程新鲜度**：通过 `http://127.0.0.1:4780` 读取独立快照，远程 `origin/main` 为 `64e29b080b3893bd9bb5ce095357c6da9662cce4`，提交时间 `2026-08-20T20:59:41+02:00`；本地落后 **299 个提交**。远程快照仅用于比对和补充事实，没有写回本地源码。
>
> **许可证**：AGPL-3.0；商业/生产集成须单独评估 Ultralytics Enterprise License。不得把本仓库代码直接并入受不同许可证约束的业务底座。

## 1. 项目定位

Ultralytics 是以 PyTorch 为核心的 Python 视觉模型平台，向用户提供统一的 `Model`/`YOLO` 外观，覆盖模型构建、权重加载、训练、验证、推理、跟踪、基准测试、导出和若干端侧/业务解决方案。能力对象不止 YOLO 检测，还包括实例分割、语义分割、深度估计、分类、姿态、旋转框、开放词汇检测、promptable segmentation、RT-DETR、YOLO-NAS，以及远程推理后端。

它的主要价值是把 **模型结构 + 数据管线 + 任务运行时 + 结果对象 + 后端适配 + CLI/配置** 组织在一套可复用 API 下，而不是单一模型文件。

### 1.1 核心能力边界

- **任务**：`detect`、`segment`、`semantic`、`depth`、`classify`、`pose`、`obb`。
- **模式**：`train`、`val`、`predict`、`export`、`track`、`benchmark`。
- **模型族**：`YOLO`、`YOLOWorld`、`YOLOE`、`NAS`、`SAM`、`FastSAM`、`RTDETR`。
- **输入**：本地图片/目录/通配符、视频、摄像头、截图、RTSP/RTMP/TCP/HTTP 流、YouTube、PIL、NumPy、Torch Tensor，以及已加载的数据源对象。
- **结果**：`Results` 统一承载 `boxes`、`masks`、`probs`、`keypoints`、`obb`、`semantic_mask`、`depth`、速度、类别名和输入路径。
- **部署**：PyTorch、TorchScript、ONNX、OpenVINO、TensorRT、CoreML、TensorFlow SavedModel/GraphDef/Edge TPU、PaddlePaddle、MNN、NCNN、IMX、RKNN、ExecuTorch、Axelera、DEEPX、Qualcomm QNN、LiteRT、Hailo，以及 Triton 远程推理。
- **非目标**：不是 OCR 专用识别器；仓库的视觉输出主要是检测/分割/分类/姿态/深度等结构化结果。若业务需要文字识别，应把 OCR 识别器作为独立能力接在检测/裁切结果之后。

## 2. 总体架构

```text
用户代码 / yolo CLI / ultralytics CLI
              │
              ▼
   ultralytics.cfg.entrypoint
   TASKS + MODES + default.yaml + get_cfg/check_cfg
              │
              ▼
   ultralytics.Model / YOLO facade
   load *.pt | build *.yaml | Triton URL
              │
              ├──────────── task_map ────────────┐
              ▼                                  ▼
     task-specific Model                  Trainer / Validator / Predictor
     DetectionModel / ...                 detect/segment/.../{train,val,predict}.py
              │                                  │
              ▼                                  ▼
   nn.tasks.parse_model                  data.build + data.dataset + augment
   nn.modules layer zoo                 images/labels/depth/semantic datasets
              │                                  │
              └──────────────┬───────────────────┘
                             ▼
              PyTorch forward / loss / metrics
                             │
             predict → AutoBackend → 统一后端输出
                             │
                             ▼
              task predictor postprocess / NMS
                             │
                             ▼
              Results(boxes/masks/probs/keypoints/obb/semantic/depth)
                             │
              callbacks / save / plot / JSON / TXT / tracking

              export → Exporter → 目标格式模型
              track  → predictor callbacks → Tracker → 带 ID Results
```

### 2.1 依赖方向与所有权

1. `ultralytics.cfg` 拥有命令行语法、任务/模式集合、默认配置合并、类型和值校验及默认数据/模型/指标映射。
2. `ultralytics.engine.model.Model` 拥有跨模型族的用户级生命周期 API；通过 `_smart_load("model"|"trainer"|"validator"|"predictor")` 和各模型的 `task_map` 延迟选择实现。
3. `ultralytics.models` 拥有模型族适配。`models/yolo/model.py` 负责 YOLO、YOLOWorld、YOLOE 和 RT-DETR 识别/切换；SAM/FastSAM/NAS 有各自受限的入口。
4. `ultralytics.nn` 拥有网络图和后端：`nn.tasks` 从 YAML 解析模块，`nn.modules` 提供层/头，`nn.autobackend` 统一加载不同推理格式。
5. `ultralytics.data` 拥有数据源判定、图片/视频/流加载、标签校验、缓存、增强、批处理和任务数据集。
6. `ultralytics.engine` 的四个运行时基类拥有训练、验证、预测和导出的流程骨架；任务目录只实现任务差异。
7. `ultralytics.utils.callbacks` 是横切扩展点，默认事件覆盖训练、验证、预测和导出；集成日志不应侵入核心任务实现。
8. `ultralytics.trackers` 通过预测回调附加跟踪状态；跟踪不是独立的模型前向任务，而是预测后处理上的状态机。

## 3. 关键入口与调用链

### 3.1 Python API

- `ultralytics/__init__.py:3-44`：版本、公开模型名、`__getattr__` 懒加载；本地公开模型为 `YOLO`、`YOLOWorld`、`YOLOE`、`NAS`、`SAM`、`FastSAM`、`RTDETR`。
- `ultralytics/engine/model.py:32-133`：`Model.__init__` 接受 `*.yaml`、`*.pt`、导出文件或 Triton URL，初始化 `overrides`、`task`、`predictor`、`trainer` 和模型状态。
- `ultralytics/engine/model.py:192-223`：`_new` 加载 YAML、推断任务并通过 task map 构建模型。
- `ultralytics/engine/model.py:225-296`：`_load` 解析权重/模型文件，加载 checkpoint 或让任务推断器识别导出格式。
- `ultralytics/engine/model.py:484-543`：`predict` 合并 overrides、方法默认值和调用参数，复用/创建 predictor。
- `ultralytics/engine/model.py:545-586`：`track` 注册 tracker 回调，默认低置信度和 batch=1，再复用预测管线。
- `ultralytics/engine/model.py:588-623`：`val` 创建任务 validator 并将 `validator.metrics` 回写模型。
- `ultralytics/engine/model.py:720` 起：`export` 委托 `Exporter`；`774` 起：`train` 委托任务 trainer；`1121` 起：`_smart_load` 按 task map 解析组件。

典型调用：

```python
from ultralytics import YOLO

model = YOLO("yolo26n.pt")
train_results = model.train(data="coco8.yaml", epochs=100, imgsz=640, device="cpu")
metrics = model.val()
results = model("path/to/image.jpg")
track_results = model.track(source="path/to/video.mp4", persist=True)
exported = model.export(format="onnx")
```

### 3.2 CLI

- `pyproject.toml:178-180`（本地）将 `yolo` 和 `ultralytics` 命令绑定到 `ultralytics.cfg:entrypoint`。
- `ultralytics/cfg/__init__.py:57-86` 定义任务、模式、默认数据、默认模型和默认指标。
- `ultralytics/cfg/__init__.py:138-176` 定义 `yolo TASK MODE ARGS` 语法及特殊命令；参数经过 `get_cfg`/`check_cfg` 类型和值校验。
- `ultralytics/cfg/default.yaml` 是配置事实源；`overrides` 在 `Model`、Trainer、Validator、Predictor、Exporter 间传播。

示例：

```bash
yolo predict model=yolo26n.pt source='https://ultralytics.com/images/bus.jpg'
yolo train model=yolo26n.pt data=coco8.yaml epochs=10 lr0=0.01
yolo val model=yolo26n.pt data=coco8.yaml batch=1 imgsz=640
yolo export model=yolo26n.pt format=onnx
```

### 3.3 YOLO task map

`ultralytics/models/yolo/model.py:90-136` 是本地 YOLO 任务装配表。每个任务以四元组为边界：

| task | model | trainer | validator | predictor |
|---|---|---|---|---|
| `detect` | `DetectionModel` | `DetectionTrainer` | `DetectionValidator` | `DetectionPredictor` |
| `segment` | `SegmentationModel` | `SegmentationTrainer` | `SegmentationValidator` | `SegmentationPredictor` |
| `semantic` | `SemanticSegmentationModel` | `SemanticSegmentationTrainer` | `SemanticSegmentationValidator` | `SemanticSegmentationPredictor` |
| `depth` | `DepthModel` | `DepthTrainer` | `DepthValidator` | `DepthPredictor` |
| `classify` | `ClassificationModel` | `ClassificationTrainer` | `ClassificationValidator` | `ClassificationPredictor` |
| `pose` | `PoseModel` | `PoseTrainer` | `PoseValidator` | `PosePredictor` |
| `obb` | `OBBModel` | `OBBTrainer` | `OBBValidator` | `OBBPredictor` |

新增任务/模型族的最小完整路径不是新建平行框架，而是：任务差异组件 → `task_map` → `nn.tasks` 模型类/损失 → `cfg/models/*.yaml` → 数据集/测试。

## 4. 运行时数据流

### 4.1 推理链

1. `Model.predict` 接收路径、URL、PIL、NumPy、Tensor 或流，建立/复用 `BasePredictor`。
2. `BasePredictor.setup_source` 调用 `data.build.load_inference_source`；`check_source` 将输入归类为 webcam/stream/screenshot/image/in-memory/tensor。
3. `BasePredictor.preprocess` 做 LetterBox、BGR→RGB、BHWC→BCHW、设备迁移和 FP32/FP16 归一化。
4. `BasePredictor.setup_model` 构造 `AutoBackend`。`AutoBackend._BACKEND_MAP` 根据后缀选择 `PyTorchBackend`、`ONNXBackend`、`TensorRTBackend` 等。
5. `stream_inference` 逐批执行 preprocess → inference → task predictor `postprocess`，统计 preprocess/inference/postprocess 速度，通过 callbacks 触发生命周期事件。
6. 任务 predictor 将原始输出变为统一的 `Results`；可绘制、保存 TXT/JSON/裁切图/视频，也可 `stream=True` 逐项消费，避免长视频结果积压内存。

源码证据：`ultralytics/engine/predictor.py:73-112,155-209,211-229,251-289,297-395,397-435`；`ultralytics/data/build.py:377-474`。

### 4.2 训练链

`BaseTrainer.__init__` 读取配置、选设备、建立保存目录、保存 `args.yaml`、解析数据集并准备断点状态；`train` 在多卡时生成 DDP 子进程命令，否则进入 `_do_train`。`_setup_train` 完成模型/权重、冻结、AMP、编译、dataloader、optimizer、scheduler、validator、EMA 和恢复训练；`_do_train` 负责 epoch/batch、forward、loss、backward、梯度累积、验证和 checkpoint。

源码证据：`ultralytics/engine/trainer.py:69-118,120-199,215-240,268-298,300-397,399-500`。

训练输出的核心持久化边界是运行目录：`args.yaml`、`results.csv`、`weights/last.pt`、`weights/best.pt`、可选 plots 和日志。它不是数据库式状态仓库；如要在业务平台留存实验，应在外围建立明确的实验元数据/模型制品边界。

### 4.3 验证链

`BaseValidator.__call__` 区分训练中验证和独立验证：准备 `AutoBackend`、数据集和 dataloader，逐批执行 preprocess → forward → loss（训练验证）→ postprocess → `update_metrics`，汇总多卡统计、速度和任务指标；可选输出 `predictions.json`。

源码证据：`ultralytics/engine/validator.py:56-105,143-231,233-307`。

### 4.4 导出链

`Exporter` 根据 `export_formats()` 的格式表校验参数、量化能力和环境依赖，再调用各 `ultralytics/utils/export/*.py` 适配器生成目标制品。导出格式和推理后缀是契约的一部分，不能只改 CLI 文案而不更新格式表、后端选择、依赖和测试。

本地 `export_formats()` 位于 `ultralytics/engine/exporter.py:141-254`，当前列出 PyTorch、TorchScript、ONNX、OpenVINO、TensorRT、CoreML、TensorFlow、PaddlePaddle、MNN、NCNN、IMX、RKNN、ExecuTorch、Axelera AI、DEEPX、Qualcomm QNN、LiteRT、Hailo 等格式；具体环境通过 `EXPORT_ENVS` 分组，`tests/test_exports.py` 用 `--export-env` 选择环境。

## 5. 模型结构与数据模型

### 5.1 YAML → PyTorch 图

- `ultralytics/nn/tasks.py:425-442` 的 `_initialize_yolo_model` 读取模型 YAML，保存 `yaml/channels/names/inplace`，调用 `parse_model` 生成 `nn.Sequential` 和保存层列表。
- `ultralytics/nn/tasks.py:118-205` 的 `BaseModel` 统一 forward：输入为字典时走任务 loss，输入为 Tensor 时走预测；`_predict_once` 按层的 `f` 连接关系执行并按 `save` 保存中间层，支持 profile/visualize/embed。
- `DetectionModel` 等任务模型在 `nn/tasks.py` 中实现 head、stride 和 `init_criterion`；损失位于 `ultralytics/utils/loss.py`。
- YAML 模型定义在 `ultralytics/cfg/models/`，按版本/模型族组织（实盘目录包含 `3`、`5`、`6`、`8`、`9`、`10`、`11`、`12`、`26`、`rt-detr` 等）。YAML 是结构和超参数声明，不是可直接替代权重的模型制品。

### 5.2 数据样本

`YOLODataset` 读取图像和伴生 label，验证后将单样本整理为 `cls`、`instances`、图像路径/形状等字段；`collate_fn` 对图像、文本特征、语义 mask、深度进行 stack，对框/掩码/关键点/OBB 做 concat，并生成 `batch_idx`。任务扩展包括：

- `DepthDataset`：图像 `images/...` 映射到平行 `depth/.../*.npy`。
- `SemanticDataset` / `PolygonSemanticDataset`：像素 mask 或多边形语义标签。
- `YOLOMultiModalDataset` / `GroundingDataset`：文本/多模态训练输入。
- `ClassificationDataset`：分类目录/类别数据。

源码证据：`ultralytics/data/dataset.py:54-97,99-161,226-298,300-432,435-495`；`ultralytics/data/build.py:236-282,316-374`。

### 5.3 结果对象

`Results` 是下游 API 的主要数据契约：初始化时从原始图像和原始尺寸建立 `Boxes`、`Masks`、`Probs`、`Keypoints`、`OBB`、`SemanticMask`、`DepthMap`。`cpu()`、`numpy()`、`cuda()`、`to()` 返回转换后的新结果；`plot`、`save`、`save_txt`、`summary`、`to_json`、`to_csv`、`to_df` 为消费层功能。

源码证据：`ultralytics/engine/results.py:23-173,176-190,192-290,292-475`。

**下游契约建议**：业务系统应把 `Results` 转换为自己的版本化 DTO，至少保留 `path`、原图尺寸、task、模型/权重标识、类别映射、置信度、坐标系、推理时间和原始制品地址；不要把 PyTorch Tensor 或内部 `Results` 对象直接跨进程/跨服务暴露。

## 6. 跟踪、解决方案与横切集成

### 6.1 Tracking

`Model.track` 复用预测流程，`ultralytics/trackers/track.py` 在 `on_predict_start` 读取 tracker YAML、按 batch 建立 tracker，并在 `on_predict_postprocess_end` 将 `Boxes`/`OBB` 交给 `BYTETracker`、`BOTSORT`、`TRACKTRACK`、`FASTTracker`、`OCSORT` 或 `DeepOCSORT`，再把 track ID 写回结果。跟踪状态与视频路径/persist 参数相关，不能在无明确生命周期的全局单例中复用。

源码证据：`ultralytics/engine/model.py:545-586`；`ultralytics/trackers/track.py:18-26,29-88,90-129,131-144`。

### 6.2 Solutions

`ultralytics/solutions/` 提供对象计数、区域计数、热力图、模糊、裁切、停车管理、队列、速度估计、健身动作、视觉指向和 Streamlit 推理等终端应用。CLI 的 `SOLUTION_MAP` 在 `ultralytics/cfg/__init__.py:37-55` 中登记。Solutions 是面向演示/业务场景的组合层，不应与核心 `engine`/`nn` 互相倒置依赖。

### 6.3 Callbacks 与集成

`ultralytics/utils/callbacks/base.py:121-167` 定义训练、验证、预测、导出的默认事件；`add_integration_callbacks` 再按实例加载 Platform、HUB、ClearML、Comet、DVC、MLflow、Neptune、Ray Tune、TensorBoard、Weights & Biases 等集成。集成通过事件观察生命周期，核心训练/预测不应直接绑定某个商业平台。

`ultralytics/utils/events.py` 还有匿名使用分析：由设置、rank、测试状态、在线状态和安装来源共同控制，队列上限 25、30 秒限流、后台发送。若将其用于受监管或离线环境，应显式审查 `SETTINGS["sync"]`、网络出口和数据最小化策略。

## 7. 依赖、打包与运行环境

`pyproject.toml`：

- Python `>=3.8`；核心依赖包括 `numpy`、`matplotlib`、`opencv-python`、`pillow`、`pyyaml`、`requests`、`torch>=1.8.0`、`torchvision`、`psutil`、`polars`、`nvidia-ml-py`、`ultralytics-thop`。
- `dev`：pytest、coverage、pytest-xdist、文档工具等。
- `export-base`：ONNX、ONNX Runtime、ONNX Slim、NNCF、OpenVINO 等。
- `export-tensorflow`、`export-coreml`、`export-executorch`、`export-litert`、`export-deepx`：按格式拆分重型依赖和版本约束。
- `solutions`：Shapely、lap、Streamlit、Flask；`logging`：W&B、TensorBoard、MLflow；`extra`：Albumentations、faster-coco-eval；`typing`：类型包。
- CLI 入口：`yolo = ultralytics.cfg:entrypoint`、`ultralytics = ultralytics.cfg:entrypoint`。
- setuptools 只打包 `ultralytics` 和子包，附带 YAML、Shell、测试 Python、图片和 solution 模板。

**运行时重点**：模型权重、数据集和视频常由下载器按需取得；测试也会访问网络并缓存资产。生产环境应固定权重 SHA/来源、禁止未授权自动下载，并为每种导出格式使用隔离环境。PyTorch/GPU、TensorRT、CoreML、OpenVINO、TensorFlow、端侧 SDK 不应混入同一个最小运行镜像。

## 8. 目录地图

当前本地仓库根目录包含：

```text
ultralytics/
├── AGENTS.md                 # 仓库规则、架构摘要、命令和许可证约束
├── README.md                 # 英文用户入口
├── README.zh-CN.md           # 中文用户入口
├── pyproject.toml            # 打包、依赖、CLI、pytest、格式规则
├── LICENSE                   # AGPL-3.0
├── ultralytics/              # Python 主包（约 367 个文件）
│   ├── __init__.py           # 版本和公开模型懒加载
│   ├── cfg/                  # default.yaml、任务/模式、模型/数据/跟踪 YAML、CLI
│   ├── data/                 # loader、dataset、augment、converter、data utils
│   ├── engine/               # Model、Trainer、Validator、Predictor、Exporter、Results
│   ├── hub/                  # 本地快照仍存在的 HUB 兼容目录；远程新版本已删除
│   ├── models/                # yolo、rtdetr、sam、fastsam、nas、utils
│   │   └── yolo/              # classify/depth/detect/obb/pose/segment/semantic/world/yoloe
│   ├── nn/                    # tasks、modules、autobackend、backends、distill_model
│   ├── optim/                 # MuSGD 等优化器
│   ├── solutions/             # 终端视觉解决方案和模板
│   ├── trackers/              # BoT-SORT、ByteTrack、OCSORT 等
│   └── utils/                 # ops、loss、metrics、torch_utils、downloads、callbacks、export
├── tests/                    # 11 个测试 Python 文件
├── docs/                     # 文档、宏、API reference 和构建脚本（约 534 个文件）
├── examples/                 # Notebook、Python/C++/Rust 示例（约 79 个文件）
├── docker/                   # CPU/GPU/ARM/Jetson 等镜像定义
└── .github/                  # CI、格式、文档、Docker、发布、fuzz、链接检查工作流
```

本地统计由目录扫描得到：`ultralytics` 367、`tests` 11、`docs` 534、`examples` 79、`.github` 19 个文件；不把这些数量当作稳定 API，后续版本应重新扫描。

## 9. 测试与质量门

### 9.1 测试布局

- `tests/test_python.py`：配置校验、设备选择、模型 forward、dataloader、各输入类型推理、类别过滤、可视化、灰度/多通道、跟踪边界等。
- `tests/test_engine.py`：导出、各任务 Trainer/Validator/Predictor 组合、训练恢复、蒸馏恢复、NaN/非有限 checkpoint、预训练模型复用等。
- `tests/test_exports.py`：按 `--export-env` 划分导出格式；不传会覆盖所有环境。
- `tests/test_cli.py`：CLI 入口和参数行为。
- `tests/test_solutions.py`：solutions 组合功能。
- `tests/test_integrations.py`：集成回调/外部适配。
- `tests/test_ndjson_converter.py`：NDJSON 数据转换。
- `tests/test_cuda.py`：CUDA 环境相关测试，无 CUDA 时跳过。
- `tests/conftest.py`：`--slow`、`--export-env`、随机种子、模型隔离、测试资产清理；默认跳过 slow 测试。
- `pyproject.toml:191-196`：pytest 默认 `--doctest-modules --durations=30`。CI 只传 `tests/`，因此包内 doctest 与 CI 测试面不完全相同。

### 9.2 CI 事实

`.github/workflows/ci.yml` 的 Tests job 覆盖 `ubuntu-latest`、`macos-26`、`windows-latest`、`ubuntu-24.04-arm` 的 Python 3.13，并加入 Python 3.8 + PyTorch 1.8.0 floor；测试安装 `.[export-base,solutions]`，预缓存权重/数据资产，运行 `pytest ... --cov=ultralytics/ tests/ --export-env base`。Benchmark 和 SlowTests 另外覆盖导出、平台和旧 PyTorch 组合。

仓库规则要求的常用命令（本次未安装依赖、未启动服务、未跑全量训练/导出）：

```bash
uv pip install -e ".[dev,export-base,solutions]"
pytest -n auto --dist=loadfile --cov=ultralytics/ --cov-report=xml tests/ --export-env base
pytest tests/test_python.py
pytest tests/test_python.py::test_predict_img -v
pytest --slow tests/
ruff format . && ruff check --fix .
python docs/build_reference.py
```

## 10. 远程版本比对与迁移提示

本地 `914074cd...` 到远程 `64e29b0...` 不是单一小修订，而是 299 个提交、485 个文件的较大漂移；主要已观测变化：

- `ultralytics.__version__` 从 `8.4.104` 变为 `8.4.124`。
- 远程公开模型增加 `LLM`；新增 `ultralytics/models/llm.py`，以 OpenAI-compatible Responses/Chat Completions API 提供同步/异步文本和图像输入。
- 远程增加/调整 `ultralytics-platform` 依赖与平台导出；本地不应假定这些公开符号存在。
- 远程删除 `ultralytics/hub/*` 及对应 reference 文档/回调，新增或重排 Platform 相关能力；本地 HUB 代码仍是事实，升级时需专项验证外部调用方。
- 远程增加 `ultralytics/nn/backends/ascend.py`、`ultralytics/utils/export/ascend.py` 等后端/导出能力，并扩展若干集成和文档。
- 远程 `pyproject.toml` 调整 setuptools 上限、macOS NumPy 排除版本、OpenCV/THOP 版本和多个 optional extra；不能把远程依赖表直接反写本地。
- 远程 README 将部分权重链接切换为 Platform 页面；本地 README 的权重/文档链接仍以本地快照为准。

**迁移规则**：如要吸收远程版本，应先在独立工作树逐模块比较 `engine`、`cfg`、`models`、`nn`、`data`、`utils`、`tests` 和 `pyproject.toml`，按 API/权重/后端/许可证影响分批验证；禁止仅凭版本号或 README 合并。

## 11. 风险、备注与未确认项

### 11.1 已确认风险

1. **许可证风险**：AGPL-3.0 对网络交互/分发和衍生作品有合规影响；本项目代码不可直接复制进其他闭源底座。优先采用独立进程、独立服务或取得企业许可，并保留许可证台账。
2. **重型依赖风险**：PyTorch、CUDA、TensorRT、OpenVINO、TensorFlow、CoreML 和端侧 SDK 版本矩阵复杂；按格式隔离环境，不在业务 API 进程里自动安装。
3. **自动下载风险**：权重、数据集、YouTube/URL 输入和测试资产可能访问网络；生产需固定来源、哈希和缓存目录，关闭非必要自动下载/遥测。
4. **长流内存风险**：非 `stream=True` 的视频/流推理会将结果收集成列表；服务接口应显式使用生成器、背压和生命周期清理。
5. **跟踪状态风险**：`persist=True` 会跨调用复用 tracker；多租户/多视频服务必须按会话隔离 tracker 和 `vid_path`。
6. **导出制品风险**：导出模型携带格式、量化、输入布局、batch、类别名等元数据；部署前必须验证原模型与导出模型的结果一致性。
7. **事件上报风险**：`utils/events.py` 存在匿名分析发送逻辑；受限网络、隐私/合规场景须审计并显式配置。
8. **版本漂移风险**：当前本地快照比远程 main 落后 299 个提交，远程已有 LLM/Platform/HUB 删除等架构变更；本档案不能作为远程最新代码的替代证据。

### 11.2 备注

- 已读取本地 `AGENTS.md`、英文/中文 README、`pyproject.toml`、核心 engine、model/task、data、backend、tracker、callback、events、CI、tests，并人工吸收此前 `细探-ultralytics.md` 的有效源码结论。后续只维护本文件，旧细探不再作为独立事实源。
- 代码图工具已按要求在项目上下文核对后调用；该项目没有 `.codegraph/` 索引，因此无法返回符号图，后续证据以实际文件读取和定位为准。
- 第一次 `project_context` 返回的是 `华世王镞_v3` 根目录而不是目标仓库身份；这属于专属 MCP 上下文绑定异常，不能把该返回当作本项目证据。
- `development_start` 尝试建立目标工作包时，专属 `project_toolkit` MCP 连续不可达；因此本档案写入和最终验证仍须以 MCP 恢复后的门禁结果为准。

### 11.3 未确认项

- 未在本地安装依赖，也未运行模型下载、训练、完整 pytest、GPU、导出 SDK 或服务启动；本文是静态架构建档，不是运行时兼容性认证。
- 未确认当前本地权重缓存的内容、来源和哈希；仅确认测试常量/代码会按需下载权重和资产。
- 未确认每一个导出格式在当前 macOS 环境是否可用；应按 `EXPORT_ENVS` 分环境执行定向 smoke test。
- 未确认远程 299 个提交中所有 API 变化；远程差异只用于记录新鲜度和识别重点迁移面。
- 未对 YOLO 检测结果接入 OCR、版面分析或业务证据模型做实现裁决；如需 OCR，应另行建立独立适配契约。

## 12. 底座吸收裁决

| 结论 | 可吸收内容 | 边界 |
|---|---|---|
| 吸收 | `Model`/`task_map` 的统一任务装配；配置集中校验；`BasePredictor` 的流式处理；`Results` 的结构化输出；`AutoBackend` 的后端隔离；callback 生命周期；tracker 通过回调挂载 | 只能提取边界和契约，不能复制 AGPL 源码 |
| 吸收 | 数据集扫描/校验/缓存、任务化 Trainer/Validator/Prediction 三件套、导出格式环境分组 | 需按业务数据治理、模型制品治理和资源限制重新实现/封装 |
| 废弃 | 将 Ultralytics Python 包直接嵌入闭源业务底座、让核心 API 自动联网下载权重、把 `Results` 直接当跨服务协议、全局复用 tracker | 许可证、供应链、并发和生命周期风险不可接受 |
| 待核 | 作为独立进程或内部服务提供检测/分割能力；与 OCR/版面分析串联；采用远程 Triton/导出制品部署 | 需补许可证审查、权重固定、输入输出 DTO、性能和安全验证 |

## 13. 后续：通用底座映射与裁决

当前核对不把 Ultralytics 源码搬入平台，而是把已确认的 `Model`/`task_map`、四类 engine 骨架、`AutoBackend`、数据源加载器、tracker 回调和导出格式表映射为四层公共边界。以下内容是**底座装配输入**；“建议能力”不是已经存在的平台实现，不能当作已落地能力。

### 13.1 四层拆分

| 底座层 | 应承接的职责 | Ultralytics 事实映射 | 明确不承接 |
|---|---|---|---|
| **视觉原子支持库 L0-L1** | 纯视觉变换、几何/NMS、样本/标签校验、数据源分类、帧解码、结果结构转换、制品摘要与临时文件安全 | `utils.ops`/`utils.nms`/`utils.metrics`，`data.check_source`/`load_inference_source`，`data.dataset`，`engine.results.Results` | 不选择模型、不持有训练会话、不直接决定业务状态 |
| **视觉模块 L2-L3** | 面向领域的训练、验证、预测、跟踪、导出编排；把任务差异组合成统一 DTO/事件 | `engine.model.Model` 的统一门面；`models/yolo/model.py` 的任务四元组；`BaseTrainer`、`BaseValidator`、`BasePredictor`、`Exporter`；`trackers/track.py` | 不直连第三方 SDK，不复制 provider 生命周期，不让消费者各自翻译错误 |
| **模型提供者 L2** | 真实模型/权重/推理后端/导出工具链的适配和隔离；报告宿主能力、版本、格式、精度和错误 | `nn.autobackend.AutoBackend` 的 `_BACKEND_MAP`（PyTorch、ONNX、TensorRT、OpenVINO、CoreML、Triton 等），`engine/exporter.py` 的格式和 `EXPORT_ENVS` | 不拥有平台任务状态、配额、租约、公共配置注册，也不向上泄露 provider 对象 |
| **运行核心 L4** | 请求准入、能力注册、配置快照、设备/权重/数据资源租约、预算、进程组监督、取消/超时/崩溃恢复、统一事件/证据/制品 | 当前仓库没有等价的统一控制面；需复用平台已有运行核心/资源监督/任务系统 | 不实现视觉算法，不新增第二套模型注册表、任务系统或结果类型 |

**边界原则**：`Results` 可以作为模块内部事实，但跨进程/跨服务必须由视觉原子支持库转换为版本化 DTO；Tensor、`AutoBackend`、Tracker 实例、DataLoader 和 `cv2.VideoCapture` 均不得穿透模块/provider边界。

### 13.2 能力注册、配置、任务模型与唯一 owner

源码中的注册目前是静态分散表：`cfg/__init__.py:38-95` 的 `SOLUTION_MAP`、`MODES`、`TASKS`、`TASK2DATA`、`TASK2MODEL`、`TASK2METRIC`，`models/yolo/model.py:90-136` 的 `task_map`，`trackers/track.py:18-26` 的 `TRACKER_MAP`，以及 `engine/exporter.py:141-254` 的格式表。它们都应映射为**运行核心唯一配置/能力注册入口**，而不是在每个模块再维护别名表。

建议冻结的规范能力 id（当前核对只登记，不声称已实现）：

| 规范能力 id | 契约 owner | 当前事实入口 | 输入/输出边界 |
|---|---|---|---|
| `视觉模型.加载权重` | 视觉模块 + 模型提供者契约 | `Model.__init__`/`_load`；`AutoBackend` | 受信权重引用+哈希/格式 → 模型句柄元数据；不返回裸 provider |
| `视觉模型.训练` | 视觉训练模块 | `Model.train` → 任务 Trainer → `BaseTrainer.train` | 数据集引用、设备、批量、轮数、截止时间 → 运行记录/检查点/指标 |
| `视觉模型.验证` | 视觉验证模块 | `Model.val` → 任务 Validator → `BaseValidator.__call__` | 权重+数据集 → 版本化指标和证据 |
| `视觉模型.预测` | 视觉预测模块 | `Model.predict` → `BasePredictor.stream_inference` | 图片/视频/流资源 → 流式视觉结果 DTO |
| `视觉模型.跟踪` | 视觉跟踪模块 | `Model.track` → `register_tracker` → 两个预测回调 | 带会话的视频结果 → 带 track id 的结果；tracker 按视频/租约隔离 |
| `视觉模型.导出` | 视觉导出模块 | `Model.export` → `Exporter` → 格式适配器 | 权重+目标格式+量化参数 → 可验证模型制品引用 |
| `视觉数据.解析数据集` | 视觉原子支持库 | `check_cls_dataset`/`check_det_dataset`、`data.dataset` | 数据集引用 → 校验后的数据集描述/样本索引 |
| `视觉数据.打开流` | 视觉原子支持库 | `check_source` → `load_inference_source` → `LoadStreams` | 图片/视频/摄像头/RTSP 等 → 有界帧迭代器和关闭句柄 |
| `视觉结果.转换DTO` | 视觉原子支持库 | `Results` 及 `to_json`/`summary` 等 | 内部结果 → 不含 Tensor/provider 的版本化结构 |

唯一链路的归一化顺序应为：**别名/旧键 → 运行核心注册表 → 模块契约 → provider 选择器 → 原子支持库和 provider 实现**。历史 `TASK2*`、tracker 名称、export format 名称只能在注册入口归一化；禁止 CLI、HTTP、任务模块和项目适配层各自再做一份映射。一个能力 id 只能有一个契约 owner、一个公开入口和一条调用/错误归一化路径。

### 13.3 训练、验证、预测、跟踪、导出如何装配

```text
外部 API/CLI
  → 运行核心：校验身份、能力版本、配置快照、权重/数据引用、预算和租约
  → 视觉模块公开入口
     ├─ 训练：任务 task_map → Trainer → data/dataloader → model/loss → checkpoint/metrics
     ├─ 验证：任务 task_map → Validator → AutoBackend → dataset → metrics/证据
     ├─ 预测：task_map → Predictor → source loader → preprocess → provider.forward
     │          → task postprocess/NMS → 结果 DTO → 流/制品输出
     ├─ 跟踪：预测链 → on_predict_start 初始化 tracker → postprocess_end 更新状态
     │          → 带 ID 结果；tracker 不成为第二条模型前向链
     └─ 导出：Exporter → 格式/量化/宿主能力校验 → 隔离导出 provider → 制品校验
  → 运行核心：统一结果、事件、指标、制品指针、释放和审计证据
```

源码证据约束了拆分方式：

- `Model.predict` 会合并 `overrides`、方法默认值和调用参数，并按 device 复用或重建 Predictor（`engine/model.py:484-543`）；因此配置快照和 predictor 生命周期应由模块/运行核心拥有，不能让 provider 修改调用方配置。
- `Model.val` 直接创建 task validator、执行并回写 `metrics`（`engine/model.py:588-623`）；验证模块应把指标和数据/权重指纹一起输出，不能只返回一个不可追溯的 dict。
- `Model.track` 先注册两个预测回调，再复用预测（`engine/model.py:545-586`）；因此跟踪模块是预测模块的有状态后处理扩展，不是独立模型服务。
- `Model.export` 把 device 重置为 `None`，由 `Exporter` 校验格式和参数；`try_export` 会检查输出文件/目录大小并在异常时重新抛出（`engine/model.py:720-772`、`engine/exporter.py:424-479`）。平台仍需补原子制品写入和失败目录清理，不能把日志“export success”当作制品已入库。
- `BaseTrainer` 已有配置保存、设备选择、数据集检查、DDP 子进程、AMP、checkpoint、早停和清理（`engine/trainer.py:120-200,215-240,399-631`）；平台复用其语义，但把训练作业放入受监督任务进程，不把 Trainer 对象放入长寿命 API 进程。

### 13.4 设备、权重、数据集和视频流的资源归属

| 资源 | 创建/选择 owner | 持有与转移 | 正常释放 | 失败/超时/崩溃治理要求 |
|---|---|---|---|---|
| 设备/GPU/MPS/CPU | 运行核心准入 + provider 能力探测；实际选择对应 `select_device` | 一个作业租约绑定 device、精度、显存预算；禁止跨作业共享可变模型状态 | 作业结束同步、清缓存、销毁 worker/provider | OOM 触发受限重试；provider 崩溃由进程监督器回收；租约超时强制终止进程组并读回无残留 |
| `.pt`/导出权重 | 运行核心制品引用校验；provider 负责加载 | 只读映射/模型句柄归单次作业；记录格式、版本、哈希、类别和输入约束 | provider/作业结束卸载；临时下载目录原子提交或删除 | 缺失、哈希不符、格式不支持均在副作用前失败；禁止隐式联网下载；加载崩溃不能污染权威制品指针 |
| 数据集/YAML/缓存 | 视觉原子支持库解析，运行核心批准路径/URL/缓存 | 数据集描述只读；DataLoader worker 是作业子资源 | `InfiniteDataLoader.close/reset` 关闭 worker；训练末尾显式 close（`data/build.py:44-105`、`trainer.py:627-630`） | 数据集校验失败归一化为任务失败；worker 超时/崩溃由作业进程组回收；缓存写入用临时路径和摘要 |
| 图片/视频文件 | source support 根据 `check_source` 分类 | 迭代器只在作业内持有；输出 VideoWriter 属作业句柄 | `stream_inference` 末尾 release writer、关闭窗口；异常路径必须 finally 化 | 大量文件/视频必须 `stream=True`；输出上限、帧数上限和背压由运行核心执行 |
| RTSP/RTMP/HTTP/摄像头流 | `LoadStreams` 创建 `VideoCapture`、daemon reader thread 和帧缓冲 | 每个流对应独立 source lease；buffer 默认受控，代码将缓冲限制为不超过约 30 帧（`data/loaders.py:95-155,159-180`） | `close` 置 `running=False`、join 每线程最多 5 秒并 release capture（`data/loaders.py:182-194`） | 首帧/连接失败要返回明确错误；读帧失败可重开但必须有次数/时间上限；取消、线程卡住、宿主崩溃由进程组和句柄清扫兜底 |
| Tracker/ReID 状态 | 跟踪模块在 `on_predict_start` 按 batch/stream 创建 | 绑定视频路径、source session 和 tracker 配置；`persist` 才允许跨调用保留 | 会话关闭/视频切换 reset 并解除 hook | 禁止全局 singleton；任务取消/流断开/崩溃必须丢弃 lease 关联状态，重启不得误接旧视频 |
| 临时导出目录/结果 | 运行核心创建唯一 job 目录，模块/provider 只写工作区 | 生成中不进入权威制品目录；完成后摘要校验+原子移动 | 成功提交后保留制品，失败/取消/超时删除临时目录 | 强杀后扫描 job 前缀、进程、GPU/文件句柄；发现半成品只能隔离/删除，不自动标为可用 |

### 13.5 资源预算与 L0-L4 验收等级

预算必须随能力契约显式传入并在运行核心执行，而不是只写在 YAML：

| 预算维度 | 最低要求 |
|---|---|
| 墙钟/截止时间 | `queue_deadline`、`start_deadline`、`hard_deadline` 分开；训练另受 `time`/epoch 上限约束；超过硬截止必须终止整个进程组 |
| 并发/租约 | 每个设备、模型制品、流 source、tracker session 有并发 token；同一 tracker session 禁止并发写；租约心跳/空闲超时/硬截止可读回 |
| CPU/线程/进程 | 限制 DataLoader workers、DDP world size、provider 子进程数；单批小数据不创建持久 worker（`data/build.py:344-374`） |
| GPU/内存 | `device`、精度、batch、imgsz、最大帧缓冲、最大输出对象数；训练 OOM 只能按现有首 epoch 单卡最多 3 次减半 batch 语义受控重试（`trainer.py:493-522`） |
| 输入/输出 | 文件/URL 白名单、最大文件/解压/样本/帧数、最大结果 DTO/JSON/视频输出字节数；默认长流不聚集结果 |
| 磁盘/网络 | 权重/数据下载字节上限、缓存空间、导出临时空间、请求超时和重试预算；默认禁止 provider 自行下载 |

等级定义与验收门槛：

- **L0 原子纯计算**：格式归一化、LetterBox 前后形状、坐标/NMS、结果 DTO 映射；无网络/设备/持久化，给定输入可重放。
- **L1 受限资源支持**：本地图片、YAML、标签、视频解码和临时文件；有路径/大小/格式校验，正常/失败都可关闭，不能产生后台线程残留。
- **L2 模型 provider**：加载权重、设备/精度、PyTorch/导出后端 forward、格式探测；必须有宿主不可用、权重损坏、超时、进程非零退出和输出形状错误的契约测试。
- **L3 视觉模块工作流**：训练/验证/预测/跟踪/导出和统一 DTO；必须有任务注册、配置快照、指标/制品证据、流式背压、取消和恢复语义。Ultralytics 本地代码只能证明部分实现，不能直接满足平台 L3。
- **L4 运行核心治理**：准入、配额、租约、进程组、取消/超时/崩溃恢复、幂等、审计、制品提交和残留扫描；没有 L4 证据，不得把 L2/L3 能力宣称为生产可用。

### 13.6 失败恢复、超时、取消和崩溃矩阵

| 场景 | 本地源码事实 | 底座裁决/缺口 |
|---|---|---|
| 配置/任务/格式非法 | `get_cfg/check_cfg` 校验；`task_map`、`TRACKER_MAP`、`export_formats` 有显式集合 | 吸收为 L0/L3 前置校验；失败必须在加载权重/打开流前返回稳定错误码，禁止模块各自拼错误 |
| 权重缺失/损坏/下载失败 | `Model._load`/`load_checkpoint` 与 provider 后缀探测会抛错；训练/测试路径可能按需下载 | 运行核心先校验来源、哈希、许可、缓存额度；下载是独立 provider 预算；缺失不可 fallback 到随机模型 |
| provider/设备不可用 | `AutoBackend` 按格式选择 backend；不支持格式抛 `TypeError`；设备/FP16能力有条件降级 | provider 必须返回 `HOST_UNAVAILABLE`/`FORMAT_UNSUPPORTED` 等稳定错误和可重试标记；降级只允许配置明确的 CPU/格式策略，不得静默换模型 |
| 训练 OOM | 单卡首 epoch 最多 3 次减半 batch，清缓存并重建 dataloader/optimizer/scheduler；其他 epoch、DDP 或超过次数直接抛错 | 吸收“有界资源恢复”；每次重试写证据并消耗预算，失败后恢复最近有效 checkpoint 或终止，不无限重试 |
| NaN/Inf/fitness collapse | 非首 epoch 从 `last.pt` 恢复，最多 3 次；缺 checkpoint/坏 checkpoint 直接失败（`trainer.py:998-1037`） | 吸收为训练恢复策略；把 checkpoint 摘要、epoch、恢复次数写入作业证据，禁止把继续运行当作成功 |
| 主动取消/超时 | 训练有 `time` 预算和批间 `stop`，DDP 广播停止；预测生成器可由消费端停止，正常尾部释放 writer/window；没有统一外部 cancel token/硬 kill | **待补 L4**：运行核心发 cancel token，先优雅排空/关闭，再按宽限期 `TERM`，最后强杀进程组；读回 worker、GPU、capture、临时目录和 tracker 残留 |
| 视频/流断线 | `LoadStreams.update` 读帧失败时告警并尝试 `cap.open(stream)`；`close` 有线程 join 5 秒 | **部分实现**：重开没有平台级次数/总时限/退避/熔断；由 stream provider 实现 bounded retry、断线事件和最终 `STREAM_UNAVAILABLE` |
| 预测结果内存失控 | 非 stream 调用把 `stream_inference` 全部转成 list；源码明确警告长流会 OOM；CLI 路径消费 generator 不存结果 | 吸收为硬契约：长流默认 streaming + 背压/最大未确认帧数；超限取消并清理，不允许调用方误用 list 形成无限积压 |
| 导出失败/半成品 | `try_export` 检查输出大小，异常记录并重新抛出；Exporter有格式/量化/环境分组 | **待补制品事务**：输出写 job 临时目录，成功后重读摘要/元数据/最小加载 smoke，再原子提交；失败、取消、崩溃清除或隔离半成品 |
| tracker 切视频/流断开 | `on_predict_postprocess_end` 按 `vid_path` reset；`persist` 控制复用；ReID hook 会注册/移除 | 吸收 tracker 状态绑定；L4 负责 session lease、断开回收和跨租户隔离，不能把 `persist=True` 当无限期全局状态 |
| DDP/worker/provider 崩溃 | DDP 使用 `subprocess.run`，finally 调 `ddp_cleanup`；DataLoader 有 `close`/析构；stream reader 是 daemon thread | **部分实现**：这些是局部清理而非崩溃一致性。模型 provider、DDP、DataLoader 应放独立进程组，由运行核心监督、回收、限次重启和从 checkpoint/制品指针恢复 |

### 13.7 现有能力命中、缺口与裁决

| 现有能力命中 | 裁决 | 落点 |
|---|---|---|
| 统一模型外观、任务四元组、配置合并 | **升级/吸收模式** | 视觉模块复用契约；把静态 task map 作为 provider/module 声明输入，运行核心只保留唯一注册/版本校验 |
| preprocess、LetterBox、source 分类、数据集/标签校验、NMS、指标、Results | **吸收为视觉原子支持库** | L0/L1；输出转平台通用 DTO，不复制 AGPL 实现 |
| Trainer/Validator/Predictor/Exporter 流程骨架 | **吸收为视觉模块模式** | L3；训练/验证/预测/导出各一公开能力，预测与跟踪共用一条前向链 |
| AutoBackend 和 export format/EXPORT_ENVS | **升级为模型提供者注册契约** | L2；每格式独立环境/版本/宿主探测， provider 对象不穿透 |
| `LoadStreams`、`InfiniteDataLoader`、VideoWriter、tracker/ReID hook | **升级资源治理** | L1/L3 + L4 租约、上限、取消和残留验证 |
| checkpoint、OOM 减半 batch、NaN 恢复、DDP cleanup | **吸收局部恢复策略** | 作为 provider/module 的可复用策略，但由运行核心统一预算/证据/终止 |
| 训练时间停止、生成器停止、线程 join 5 秒 | **部分实现，待核 L4** | 需统一 cancel token、硬截止、killpg、子进程重启、状态恢复和残留扫描 |
| 自动下载、HUB、Triton、匿名 events、全局设置 | **隔离/默认关闭** | 置于显式网络 provider；权重/数据供应链、遥测和许可证必须在准入策略中声明 |
| Solutions 终端应用 | **不进入核心视觉模块** | 作为上层组合模块，只调用 `视觉模型.预测/跟踪`，不另建模型链或注册表 |

### 13.8 单一可审计链与装配计划

最终只允许这一条生产调用链：

```text
项目适配层/HTTP/CLI
  → 运行核心.视觉任务提交（鉴权 + 能力版本 + 配置快照 + 资源预算）
  → 视觉模块.训练|验证|预测|跟踪|导出（唯一公开入口）
  → 视觉注册表（task/mode/format/provider 唯一归一化）
  → 视觉原子支持库（数据源、预处理、结果、制品安全）
  → 模型提供者（独立环境/进程，真实设备或远程后端）
  → 统一结果 DTO / 事件 / 指标 / 模型制品
  → 运行核心.提交证据 + 释放租约 + 残留审计
```

装配顺序固定为：

1. **登记需求**：冻结任务、模式、输入/输出 DTO、许可、设备和数据范围；不因“已有 Ultralytics API”跳过需求登记。
2. **能力命中与复用裁决**：优先复用现有通用结果、资源监督、任务系统、进程组、制品和审计能力；视觉域只补缺口。
3. **声明契约**：为每个能力声明参数、返回、错误码、可重试、超时、取消、幂等键、资源 owner 和 L0-L4 级别；provider 仅声明宿主/版本/格式能力。
4. **注册/版本/占用**：能力 id、provider、格式、权重和设备选择由唯一注册表归一化；同一能力不得有侧链或隐藏 fallback。
5. **装配和隔离**：预测/跟踪可共用一次前向；训练/导出等重型任务进入独立作业进程；每个作业有唯一工作目录、资源租约和预算。
6. **验收契约**：至少覆盖正常、非法参数、缺 provider、权重损坏、设备不可用、OOM、断流、超时、取消、强杀、重启恢复、重复提交、二次释放和残留扫描；未覆盖项保持“待核”。

**后续结论**：吸收的是“任务装配、四种运行骨架、流式数据和后端适配的边界模式”；升级的是资源、制品和生命周期治理；新建的是 L4 统一监督/注册/证据契约；废弃的是直嵌闭源业务、隐式下载、跨服务暴露内部对象和全局 tracker。当前项目仍只能作为“视觉模型运行时/检测分割底座候选”，不是平台生产实现。

## 14. 结论

Ultralytics 的架构主线是 **统一用户外观 → task map 装配任务组件 → engine 运行时骨架 → data/nn 提供数据与模型 → AutoBackend 统一部署 → Results 结构化交付**。其可复用价值在边界设计和多后端/多任务组织方式，不在把整个仓库搬进业务平台。

对当前源码参考库的建议：将它登记为“视觉模型运行时/检测分割底座候选”，优先以独立服务或独立进程方式调用；OCR 识别、版面理解和业务证据落库继续保持独立模块。任何正式吸收前，先处理 AGPL/企业许可、权重和数据供应链、导出环境隔离、流式内存和多租户 tracker 生命周期。

## 15. 后续源码映射增补：Model/task_map/Results 到受治理工作流

本节只记录本地源码可直接确认的调用关系，并将其翻译为平台边界。源码事实重点是：`Model` 负责统一外观和生命周期转发，具体任务由 `task_map` 四元组装配，`Results` 是推理后的内部结果容器；训练、推理、设备、权重、数据和释放都在这条链上产生资源副作用。

### 15.1 Model 的状态机与 task_map 装配

`ultralytics/engine/model.py` 的 `Model.__init__` 先初始化 `callbacks`、`predictor`、`model`、`trainer`、`ckpt`、`cfg`、`overrides`、`metrics`、`session` 和 `task` 等状态，再按输入分流：HUB 地址创建 HUB session，Triton 地址保存远程模型引用，YAML 进入 `_new`，其他权重进入 `_load`。YAML 路径经 `yaml_model_load` 和 `guess_model_task` 得到任务，随后 `_smart_load("model")` 从子类的 `task_map` 取出模型类；权重路径经 `load_checkpoint` 恢复模型、checkpoint 和任务。

`ultralytics/models/yolo/model.py:88-134` 的 `YOLO.task_map` 是任务装配事实表：每个 task 映射 `model`、`trainer`、`validator`、`predictor`。当前本地明确包含 `classify`、`detect`、`segment`、`pose`、`obb`、`depth`、`semantic` 七项。`Model._smart_load` 只按当前 `self.task` 和键读取这一表；不存在的任务/键在装配前失败，而不是运行到 provider 内部才失败。

平台应保留两个不同概念：任务契约（版本化 task 名称及输入/输出语义）和实现装配（任务对应的 model/trainer/validator/predictor/provider 组合）。后者只能由唯一注册表解析，不能让 HTTP、CLI、项目适配层各自复制 `task_map`。

`Model.predict` 合并 `self.overrides`、方法默认值和调用参数；设备变化时重建 predictor，否则只更新 predictor 配置。`Model.track` 给 predictor 注册 tracker 回调后把 `mode=track`、低置信度和 batch=1 传回 `predict`。`Model.val` 创建 validator 并回写 `validator.metrics`，`Model.train` 创建 trainer，训练结束从 `best.pt` 或 `last.pt` 重新加载模型。这说明模块拥有工作流，provider 只拥有一次受控的模型执行。

### 15.2 Results 的内部数据契约与跨边界转换

`Results.__init__` 以原图和 `orig_shape` 为基准构造可选的 `Boxes`、`Masks`、`Probs`、`Keypoints`、`OBB`、`SemanticMask` 和 `DepthMap`，同时记录 `speed`、`names`、`path` 和 `save_dir`。这些对象共享 `BaseTensor` 的设备转换语义：`cpu()`、`numpy()`、`cuda()`、`to()` 返回新对象；索引会按相同的原图上下文产生新的 `Results` 子集。

`Results.plot/show/save/save_txt/save_crop/summary/to_json/to_csv/to_df` 是消费和导出操作，不是模型推理本身。`speed` 的 preprocess/inference/postprocess 由 predictor 在批处理后按图像数分摊。结果层不会自动补充平台需要的权重摘要、任务版本、坐标系版本、请求 id 或数据许可证。

平台边界裁决：`Results` 只允许留在视觉模块内部；跨进程、跨服务必须转成版本化 DTO。DTO 至少包含 `schema_version`、`task`、`path/source_id`、原图尺寸、模型/权重指纹、类别映射、置信度/坐标系、推理耗时和制品引用。Tensor、GPU device、`AutoBackend`、tracker、DataLoader、VideoCapture 和 callback 对象不得进入 DTO。`numpy()` 不是安全边界，仍需结果数量、数组大小、JSON/文件输出字节上限。

### 15.3 训练与推理：相同入口，不同资源模型

训练入口为 `Model.train → task_map[task].trainer → BaseTrainer.train`。`BaseTrainer.__init__` 规范化设备、保存 `args.yaml`、创建 `weights/last.pt` 和 `weights/best.pt` 路径、解析数据集，并决定 CPU/MPS worker 数和 DDP world size。单卡进入 `_do_train`；多卡生成 DDP 命令并用 `try/finally` 调用 `ddp_cleanup`。训练循环包含 AMP/autocast、梯度累积、optimizer/scheduler、EMA、验证、早停和 checkpoint。

训练是长作业，模型、optimizer、scaler、EMA、DataLoader worker、DDP 子进程和工作目录均属于同一作业租约。业务 API 进程不应持有 Trainer；应由受监督作业进程执行，输出只通过指标、checkpoint 摘要和状态事件回传。

推理入口为 `Model.predict → BasePredictor.__call__ → stream_inference`。`stream=False` 显式把生成器消费成 list，`stream=True` 返回生成器；CLI 使用 `predict_cli` 消费生成器但不保存结果。`stream_inference` 在锁内完成 source setup、warmup、批次循环和 callback 事件，按 preprocess → inference → postprocess 计时，然后 yield `Results`。因此长视频/实时流的默认平台策略必须是 streaming、背压和最大未确认结果数，而不是无界 list。

### 15.4 设备、权重与后端选择

推理 `setup_model` 用 `select_device` 选择设备，再创建 `AutoBackend`；后者根据模型格式选择 PyTorch、TorchScript、ONNX、TensorRT、OpenVINO、CoreML、Triton 等后端。模型随后 `eval()`，可按 CUDA 原生 PyTorch 条件使用 channels-last，并可尝试 compile。预处理将图像迁移到 device，根据实际 backend 的 FP16 能力选择 half/float。

`load_checkpoint` 对远程权重前缀调用 `check_file`，再由 `torch_safe_load` 加载 checkpoint；优先使用 `ema` 或 `model`，要求结果为支持的 `torch.nn.Module`，补齐 args、pt_path、task、stride，最后设为 eval 并迁移 device。权重加载可能联网，且 checkpoint 不是只含裸参数的简单文件。

平台必须在调用 provider 前完成权重来源许可、内容哈希、格式、类别/输入元数据、下载字节和缓存空间校验。禁止 provider 静默下载、随机初始化替代缺失权重或静默从 GPU 降级为 CPU。设备选择结果、精度、显存预算和后端版本应写入运行证据。

### 15.5 数据、批处理与流生命周期

`load_inference_source` 先由 `check_source` 分类，再选择 `LoadStreams`、`LoadImagesAndVideos`、`LoadPilAndNumpy`、`LoadScreenshots` 或 `LoadTensor`。`BasePredictor.setup_source` 将 source 转为 dataset，按模型 stride 校验 imgsz；相同尺寸、rect 和 backend 条件满足时使用自动 LetterBox。

训练 `build_yolo_dataset` 按 task 选择 `YOLODataset`、`DepthDataset`、`SemanticDataset`/`PolygonSemanticDataset` 或多模态数据集；`build_dataloader` 根据数据量、设备数、batch 和 worker 上限计算实际 worker 数，单批数据不建立持久 worker。`InfiniteDataLoader` 复用 worker，提供 `close`/`reset`，析构时也尝试终止 worker。`collate_fn` 将图像和像素级数据 stack，把框、掩码、关键点、OBB concat，并生成 `batch_idx`。

`LoadStreams` 为每个源创建 `cv2.VideoCapture`、daemon reader thread 和帧缓冲；缓冲上限约 30 帧，非 buffer 模式只保留最新帧。初始化失败会调用 `close` 后重新抛出；`close` 置 `running=False`、每线程最多 join 5 秒，再 release capture。它是局部资源释放，不等于平台级断流重试、硬截止或进程回收；这些必须由 L4 监督器补齐。

### 15.6 资源释放与错误归一化矩阵

| 边界 | 本地源码行为 | 平台必须补齐 |
|---|---|---|
| predictor/视频输出 | 推理尾部 release `vid_writer`，显示窗口调用 `cv2.destroyAllWindows` | `finally` 覆盖取消、异常、生成器提前关闭；核对文件句柄和临时输出 |
| DataLoader | `InfiniteDataLoader.close/reset` 关闭持久 worker，训练末尾显式 close | 作业终止后回收 worker/管道，禁止残留进程；二次 close 幂等 |
| stream loader | stop flag、join 5 秒、release `VideoCapture` | bounded retry、退避、断线事件、硬超时、强杀进程组和残留扫描 |
| DDP | `subprocess.run` + finally `ddp_cleanup` | 进程组 owner、TERM→KILL 宽限期、退出码和 checkpoint 恢复证据 |
| export | 异常重抛，检查输出文件/目录大小 | job 临时目录、摘要/最小加载验证、成功后原子提交，失败清理半成品 |
| 结果列表 | 非 streaming 路径累积 list | 默认长流 streaming、背压、最大结果/字节数，超限取消 |

错误必须在模块边界统一为稳定结构：`错误码`、`错误说明`、`可重试`、`阶段`、`资源`、`原始诊断引用`。至少覆盖 `INVALID_CONFIG`、`TASK_UNSUPPORTED`、`WEIGHT_NOT_FOUND`、`WEIGHT_INTEGRITY_FAILED`、`FORMAT_UNSUPPORTED`、`DEVICE_UNAVAILABLE`、`DATASET_INVALID`、`STREAM_UNAVAILABLE`、`RESOURCE_EXHAUSTED`、`CANCELLED`、`DEADLINE_EXCEEDED`、`PROVIDER_CRASHED` 和 `ARTIFACT_COMMIT_FAILED`。底层 Python/CUDA/OpenCV 异常可进入诊断引用，但不能直接成为跨服务协议。

### 15.7 L0-L4 映射与验收闸门

| 等级 | 当前核对源码映射 | 能证明的范围 | 尚不能证明的范围 |
|---|---|---|---|
| **L0** | LetterBox、张量/坐标转换、NMS、`Results`/DTO 映射 | 同输入可重放、无网络和持久资源 | 模型质量、设备可用性 |
| **L1** | `check_source`、dataset/label 校验、图片/视频读取、DataLoader 和临时文件 | 路径/格式/大小校验，正常/异常关闭 | 崩溃后的全局回收、外部流稳定性 |
| **L2** | `load_checkpoint`、`select_device`、`AutoBackend`、forward、导出格式 | 权重/设备/格式适配和宿主探测 | 统一配额、隔离进程、供应链可信度 |
| **L3** | `task_map`、Trainer/Validator/Predictor/Exporter、tracker 回调、Results | 任务化工作流、指标和结果结构 | 取消、恢复、制品事务、多租户租约 |
| **L4** | 本地没有等价的统一控制面 | 只能提出准入、租约、监督和证据要求 | 不能把本源码仓库宣称为生产治理实现 |

当前核对最终裁决：复用 `Model/task_map` 的装配思想、Trainer/Validator/Predictor 的任务差异分层、`Results` 的内部结果模型、source/batch 的流式边界以及 AutoBackend 的 provider 隔离思想；不复用 AGPL 实现，不把内部对象作为平台协议，不允许隐式下载、无界批处理、全局 tracker 或未监督的训练/导出进程。只有 L0-L3 定向验收和 L4 运行核心证据同时存在时，才能将视觉能力标记为生产可用。

## 代码地图现状复核（2026-08-22）

文中早期“目标仓库无 `.codegraph`”记录对应旧快照，现已过期。当前目标根 `/Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/20_vision_ocr_detection/ultralytics` 存在独立 `.codegraph/`；`codegraph status` 退出码为 0，返回 430 files、6,464 nodes、16,343 edges。该索引仅作为源码导航，AGPL 合规、模型下载、任务取消和生产治理仍按本文未验证边界执行。
