# SAM 2 架构档案

## 1. 项目身份与审计边界

- **项目**：SAM 2: Segment Anything in Images and Videos
- **根目录**：`/Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/20_vision_ocr_detection/sam2`
- **上游**：`https://github.com/facebookresearch/sam2.git`
- **当前分支/提交**：`main` / `2b90b9f5ceec907a1c18123530e92e794ad901a4`
- **提交主题**：`remove .pin_memory() in obj_pos of SAM2Base to resolve and error in MPS (#495)`
- **远程比对**：`git ls-remote origin refs/heads/main` 与本地提交相同；本地相对 `origin/main` 为 `0 ahead / 0 behind`。本轮未创建 4780 独立快照。
- **工作树基线**：架构建档前已有未跟踪文件 `细探-sam2.md`；本轮保留，不删除、不改写。
- **许可证**：主模型、demo、training 为 Apache-2.0；SA-V 数据集为 CC BY 4.0；`sav_dataset` 评估代码另含 BSD-3-Clause、DAVIS 与 VOS-Benchmark 授权文件；demo 字体含 SIL OFL 约束。
- **本轮允许变更**：仅项目根目录 `ARCHITECTURE.md`。

## 2. 项目定位与总体架构

SAM 2 是 Meta FAIR 的提示式视觉分割基础模型，将图像视为单帧视频，统一支持静态图像分割、视频对象分割与跨帧跟踪。核心模型是 Transformer 视觉编码器、SAM 风格 prompt/mask 解码器、时序 memory attention 与 memory encoder 的组合；视频推理以 `inference_state` 保存会话状态，并把当前帧输出编码进后续帧的流式记忆。

```text
图像/视频帧
    │
    ▼
Hiera image backbone + FpnNeck
    │ 视觉特征 / 位置编码
    ├───────────────┐
    ▼               │
MemoryAttention ◄───┘  历史帧 memory / object pointers
    │
    ▼
SAM prompt encoder + TwoWayTransformer + MaskDecoder
    │ 低分辨率/高分辨率 masks、IoU、object pointer、object score
    ├───────────────┐
    ▼               │
MemoryEncoder ──────┘  mask memory，写回视频状态
    │
    ▼
SAM2ImagePredictor / SAM2VideoPredictor / SAM2AutomaticMaskGenerator
    │
    ├─ Python API：numpy/PIL/Tensor
    ├─ VOS 工具：PNG mask 输出
    ├─ training：Hydra + DDP/Submitit
    └─ demo：Flask + Strawberry GraphQL + multipart 流
```

主要职责边界：

1. `sam2/modeling/` 只负责神经网络模块、特征与 mask 推理；`SAM2Base.forward()` 明确拒绝直接调用，要求通过视频 predictor 或 `SAM2Train` 进入。
2. `sam2/build_sam.py` 是模型装配入口，使用 Hydra/OmegaConf 从 YAML 实例化 `cfg.model`，加载 checkpoint 后放置到指定 device。
3. `sam2/sam2_image_predictor.py` 管理单图/批图 embedding 生命周期和 prompt 推理。
4. `sam2/sam2_video_predictor.py` 管理视频会话、多对象映射、交互输入、memory 传播、清理与重置。
5. `training/` 复用 `SAM2Base`，增加 GT 驱动的点/框采样、纠正点击、多帧 conditioning、loss、优化器和分布式训练。
6. `demo/backend/server/` 是面向浏览器的应用层；`InferenceAPI` 将 GraphQL/HTTP 请求转换成 predictor 调用，再将 Tensor mask 编码为 COCO RLE。

## 3. 目录与组件地图

| 目录/文件 | 职责 | 关键入口/标识 |
|---|---|---|
| `sam2/` | 可安装 Python 包与模型实现 | `sam2/__init__.py`、`build_sam.py` |
| `sam2/modeling/backbones/` | Hiera 主干、FPN neck、patch/window 工具 | `Hiera`、`ImageEncoder`、`FpnNeck` |
| `sam2/modeling/sam/` | SAM prompt 编码、mask 解码、TwoWay/RoPE Transformer | `PromptEncoder`、`MaskDecoder`、`TwoWayTransformer`、`RoPEAttention` |
| `sam2/modeling/memory_attention.py` | 当前视觉特征与历史 memory/object pointers 的时序注意力 | `MemoryAttention`、`MemoryAttentionLayer` |
| `sam2/modeling/memory_encoder.py` | mask 到 memory feature 的编码与压缩 | `MemoryEncoder`、`MaskDownSampler`、`Fuser` |
| `sam2/modeling/sam2_base.py` | 四部分模型骨架、SAM heads、memory 读写辅助 | `SAM2Base`、`NO_OBJ_SCORE` |
| `sam2/sam2_image_predictor.py` | 图像 embedding、点/框/掩码 prompt、batch 预测 | `SAM2ImagePredictor.set_image`、`predict`、`predict_batch` |
| `sam2/sam2_video_predictor.py` | 新版独立对象视频推理与交互状态机 | `SAM2VideoPredictor.init_state`、`add_new_points_or_box`、`add_new_mask`、`propagate_in_video`、`reset_state`、`remove_object` |
| `sam2/sam2_video_predictor_legacy.py` | 旧版视频 predictor 回滚/兼容实现 | `SAM2VideoPredictor`（legacy） |
| `sam2/automatic_mask_generator.py` | 图像网格点采样、多 crop、NMS、稳定性过滤和 RLE | `SAM2AutomaticMaskGenerator.generate` |
| `sam2/utils/` | 图像/视频加载、变换、RLE、connected components、mask 后处理 | `load_video_frames`、`MaskData`、`fill_holes_in_mask_scores` |
| `sam2/configs/sam2/` | SAM 2 YAML 模型配置 | `sam2_hiera_{t,s,b+,l}.yaml` |
| `sam2/configs/sam2.1/` | SAM 2.1 YAML 模型配置 | `sam2.1_hiera_{t,s,b+,l}.yaml` |
| `training/` | 训练模型、数据集、loss、optimizer、trainer、分布式启动 | `training/train.py`、`Trainer`、`SAM2Train` |
| `tools/` | VOS 推理与 PNG 预测导出 | `tools/vos_inference.py` |
| `sav_dataset/` | SA-V 数据加载/可视化/评估 | `sav_evaluator.py`、`VideoEvaluator`、`Evaluator` |
| `demo/backend/server/` | Flask/GraphQL 后端、视频预加载、推理会话 | `app.py`、`schema.py`、`InferenceAPI` |
| `demo/frontend/` | React + TypeScript + Vite 前端 | Vite 配置、GraphQL/上传/交互 UI |
| `notebooks/` | 图像、视频、自动 mask、SA-V 示例 | `*_example.ipynb` |
| `checkpoints/` | checkpoint 下载脚本/模型权重落点 | `download_ckpts.sh` |
| `setup.py`、`pyproject.toml` | setuptools 元数据、依赖、CUDA 扩展 | `get_extensions`、`BuildExtensionIgnoreErrors` |

当前树规模（排除 `.git`）：顶层主要源码约 39 个文件，`demo/` 约 265 个文件，`notebooks/` 约 207 个文件，`training/` 约 25 个文件，`sam2/` 约 39 个文件；仓库同时包含样例媒体和 notebook 资源，不能把资源目录误判为生产代码。

## 4. 模型装配与核心调用链

### 4.1 构建入口

`sam2/build_sam.py:71-97` 的 `build_sam2`：

1. 可选追加动态 multimask 稳定性 post-processing overrides。
2. `compose(config_name=config_file, overrides=...)` 读取 Hydra 配置，`OmegaConf.resolve` 展开变量。
3. `instantiate(cfg.model, _recursive_=True)` 构建 `SAM2Base` 或指定 predictor。
4. `_load_checkpoint` 以 `torch.load(..., map_location="cpu", weights_only=True)["model"]` 载入权重，严格检查 `missing_keys` 与 `unexpected_keys`。
5. `.to(device)`，`mode == "eval"` 时切换 eval。

`build_sam2_video_predictor:100-141` 通过 Hydra override 把目标类切为 `sam2.sam2_video_predictor.SAM2VideoPredictor`；`vos_optimized=True` 时切为 `SAM2VideoPredictorVOS` 并启用 `compile_image_encoder=True`。`build_sam2_hf` 与 `build_sam2_video_predictor_hf` 通过 `HF_MODEL_ID_TO_FILENAMES` 映射 config/checkpoint，再调用同一构建链。

### 4.2 图像路径

`SAM2ImagePredictor.set_image` 将 RGB `numpy.ndarray`/PIL Image 记录原始尺寸，经 `SAM2Transforms` 变换后调用 `model.forward_image` 与 `_prepare_backbone_features`，缓存：

```text
_features = {
    "image_embed": lowest-resolution embedding,
    "high_res_feats": optional high-resolution features,
}
```

`predict`/`predict_batch` 将点坐标、点标签、XYXY box、低分辨率 mask input 转为 Tensor，调用 `sam_prompt_encoder` 与 `sam_mask_decoder`，再将 mask 上采样到原图尺寸，返回 `(masks, iou_predictions, low_res_masks)`。默认返回 numpy；`return_logits=True` 保留 logits。

### 4.3 视频路径

`SAM2VideoPredictor.init_state` 调用 `load_video_frames`，创建字典型 `inference_state`。其核心数据模型包括：

- `images`、`num_frames`、原视频 `video_height/video_width`、compute/storage device；
- `point_inputs_per_obj`、`mask_inputs_per_obj`；
- `cached_features`、`constants`；
- `obj_id_to_idx`、`obj_idx_to_id`、`obj_ids`；
- 每对象的 `output_dict_per_obj` 与 `temp_output_dict_per_obj`，均按 `cond_frame_outputs`/`non_cond_frame_outputs` 分层；
- `frames_tracked_per_obj` 记录帧与正/反向追踪方向。

交互与传播顺序：

1. `add_new_points_or_box` 或 `add_new_mask` 注册/查找对象，更新当前帧 prompt。
2. 调用 `_run_single_frame_inference`，从 `cached_features` 取/算 backbone 特征，再进入 `SAM2Base.track_step`。
3. 交互结果先进入临时输出；`_consolidate_temp_output_across_obj` 合并对象并可恢复到原视频分辨率。
4. `propagate_in_video_preflight` 将临时输出合并，必要时重新运行 memory encoder，并检查每个对象至少有 conditioning 输出。
5. `propagate_in_video` 按正向/反向帧序逐帧运行，把输出写入 `non_cond_frame_outputs` 并 yield `(frame_idx, obj_ids, video_res_masks)`。
6. `clear_all_prompts_in_frame`、`reset_state`、`remove_object` 负责局部清理、全状态清空和对象索引重排。

新版设计允许每个对象独立推理，并允许追踪开始后新增对象；旧行为保留在 `sam2_video_predictor_legacy.py`。

### 4.4 自动 mask 路径

`SAM2AutomaticMaskGenerator.generate` 生成多层 crop 的规则点网格；每批点调用 `SAM2ImagePredictor._predict`，按预测 IoU、stability score、边界、box NMS 过滤，转为 RLE/二值 mask/COCO RLE。输出记录字段为 `segmentation`、`area`、`bbox`、`predicted_iou`、`point_coords`、`stability_score`、`crop_box`。`coco_rle` 需要 `pycocotools`，小区域后处理需要 OpenCV/CUDA 扩展能力。

## 5. 训练、数据与配置模型

### 5.1 训练启动

`training/train.py:123-270` 使用 Hydra `compose` 加载训练配置，补齐 `experiment_log_dir`，写出 `config.yaml` 与 `config_resolved.yaml`，再根据 `--use-cluster`：

- 本地：`single_node_runner`，使用 `torch.multiprocessing` 的 `spawn` 启动多 GPU。
- 集群：`SubmititRunner` + `submitit.AutoExecutor`，对接 SLURM 的 partition/account/qos/nodes/GPU 参数。

`Trainer` 在 `training/trainer.py` 中装配 `data/model/loss/optimizer/checkpoint/logging`，初始化 torch distributed、device、随机种子、DDP、dataloader、checkpoint 与训练循环。checkpoint 使用 `.tmp` 写入后替换目标，降低中断造成的损坏风险。

### 5.2 训练模型与数据模型

`SAM2Train` 继承 `SAM2Base`，对 `BatchedVideoDatapoint` 执行：

```text
图像/视频数据 → prompt 输入采样
             → 初始 conditioning frames
             → frame-by-frame tracking
             → 按预测误差采样 correction points
             → 每帧输出 → MultiStepMultiMasksAndIous loss
```

`training.dataset` 的核心结构：

- `VOSFrame(frame_idx, image_path, data, is_conditioning_only)`；
- `VOSVideo(video_name, video_id, frames)`；
- `PNGRawDataset`：DAVIS/MOSE 类 JPEG + PNG；
- `SA1BRawDataset`：SA-1B 图像 + JSON；
- `JSONRawDataset`：SA-V `_manual.json` 标注 + JPEG 帧；
- `VOSDataset`：采样视频与对象、加载 segment、构建 `VideoDatapoint`，失败时训练模式最多重试 100 次；
- `TorchTrainMixedDataset`：多个数据集按 phase/batch size 混合。

`sam2.1_training/sam2.1_hiera_b+_MOSE_finetune.yaml` 用 Hydra `_target_` 字段声明 `Trainer`、`SAM2Train`、数据集、transforms、`AdamW`、`MultiStepMultiMasksAndIous`、checkpoint loader 与 TensorBoard logger；路径、数据集、实验输出目录均由配置/命令行决定。

## 6. Demo 应用、API 与数据模型

### 6.1 后端运行时

`demo/backend/server/app.py:29-35` 模块导入时创建 Flask app，执行 `preload_data()`/`set_videos()` 并立即构造全局 `InferenceAPI`。因此启动即要求模型 checkpoint、视频数据目录和推理依赖可用，并会产生文件系统目录/预加载开销。

路由：

- `GET /healthy`：返回纯文本 `OK`。
- `GET /gallery/<path>`：读取 gallery 视频。
- `GET /posters/<path>`：读取 poster。
- `GET /uploads/<path>`：读取上传视频。
- `POST /propagate_in_video`：接收 `session_id` 与可选 `start_frame_index`，返回 `multipart/x-savi-stream` 流。
- `POST /graphql`：由 Strawberry `schema` 提供 GraphQL query/mutation，禁止 GET query，开启 multipart upload。

`docker-compose.yaml` 将前端映射到 `7262`、后端容器 `5000` 映射到 `7263`，后端把 `./demo/data` 挂载到 `/data`，预留 NVIDIA GPU；README 明确 macOS Docker 仅 CPU，MPS 需本地后端运行。

### 6.2 `InferenceAPI` 会话与设备

`demo/backend/server/inference/predictor.py:43-92`：

- 根据 `MODEL_SIZE` 选择 SAM 2.1 tiny/small/base_plus/large checkpoint 与配置。
- 自动选择 CUDA → MPS → CPU；`SAM2_DEMO_FORCE_CPU_DEVICE=1` 可强制 CPU。
- 为 MPS 默认 `offload_video_to_cpu=True`，降低内存碎片风险。
- 全局 `session_states: Dict[str, Any]` 保存 `{canceled, state}`；`inference_lock` 串行保护核心推理。
- 会话操作：`start_session`、`close_session`、`add_points`、`add_mask`、`clear_points_in_frame`、`clear_points_in_video`、`remove_object`、`propagate_in_video`、`cancel_propagate_in_video`。
- mask 输出使用 `pycocotools.mask.encode/decode`，对外 `counts` 转 UTF-8 字符串。

### 6.3 GraphQL 数据模型

`demo/backend/server/data/data_types.py` 定义 Strawberry 类型：

- `Video`：`code/path/poster_path/width/height`，并暴露 `url`、`poster_url`。
- `RLEMask(size/counts/order)`、`RLEMaskForObject(object_id/rle_mask)`、`RLEMaskListOnFrame(frame_index/rle_mask_list)`。
- 输入：`StartSessionInput`、`CloseSessionInput`、`AddPointsInput`、`ClearPointsInFrameInput`、`ClearPointsInVideoInput`、`RemoveObjectInput`、`CancelPropagateInVideoInput`。
- 输出：`StartSession`、`CloseSession`、`ClearPointsInVideo`、`CancelPropagateInVideo`。

`data/schema.py` 提供 query `default_video`、connection `videos`；mutation `upload_video`、`start_session`、`close_session`、`add_points`、`remove_object`、`clear_points_in_frame`、`clear_points_in_video`、`cancel_propagate_in_video`。视频元数据来自 PyAV，上传视频先临时保存、校验、转码，再以 SHA-256 文件名移动到 uploads。

`data/store.py` 是进程内全局字典 `ALL_VIDEOS`，没有数据库持久化；`app_conf.py` 通过环境变量确定 `APP_ROOT`、`API_URL`、`MODEL_SIZE`、`DATA_PATH`、最大上传时长和默认视频，并在导入时创建 gallery/uploads/posters 目录。

## 7. 依赖、构建与部署

### 7.1 必选依赖

`setup.py:23-32`：`torch>=2.5.1`、`torchvision>=0.20.1`、`numpy>=1.24.4`、`tqdm>=4.66.1`、`hydra-core>=1.3.2`、`iopath>=0.1.10`、`pillow>=9.4.0`；Python 要求 `>=3.10.0`。`pyproject.toml` 的 build-system 额外要求 `setuptools>=61.0`、`torch>=2.5.1`。

### 7.2 可选依赖组

- `[notebooks]`：`matplotlib`、`jupyter`、`opencv-python`、`eva-decord`。
- `[interactive-demo]`：`Flask`、`Flask-Cors`、`av`、`dataclasses-json`、`eva-decord`、`gunicorn`、`imagesize`、`pycocotools`、`strawberry-graphql`。
- `[dev]`：`black`、`usort`、`ufmt`、`fvcore`、`pandas`、`scikit-image`、`tensorboard`、`pycocotools`、`tensordict`、`opencv-python`、`submitit`。
- `sav_dataset/requirements.txt`：SA-V 评估专用依赖，独立于主包。

### 7.3 CUDA 扩展

`setup.py:67-153` 默认通过 `SAM2_BUILD_CUDA=1` 编译 `sam2/csrc/connected_components.cu` 为 `sam2._C`。`SAM2_BUILD_ALLOW_ERRORS=1` 默认允许编译失败并继续安装；设置为 `0` 才会把构建失败升级为异常。CUDA 扩展失败后仍可进行主要图像/视频推理，但小洞/小散点后处理能力受限。要求 CUDA toolkit/NVCC 与 PyTorch CUDA 版本匹配；项目原始安装文档以 Linux/CUDA 为主，macOS demo 走 CPU/MPS 分支。

### 7.4 运行入口

```text
pip install -e .                         # 基础包
pip install -e ".[notebooks]"            # notebook
python tools/vos_inference.py ...        # VOS 推理
python training/train.py -c ...          # 本地/SLURM 训练
python sav_dataset/sav_evaluator.py ...  # SA-V 评估
# demo：docker compose up --build，或 gunicorn demo/backend/server/app.py 对应配置
```

本轮未执行安装、启动、构建或模型推理；以上为源码/README 中记录的入口。

## 8. 测试、质量门与可验证性

- 仓库树扫描未发现 `tests/` 目录，也未发现 `test*.py`/`*_test.py` 测试文件；因此当前仓库没有可确认的项目级自动化测试套件入口。
- `CONTRIBUTING.md` 要求：改代码补测试、API 变更更新文档、运行测试套件、使用 `ufmt format` lint。
- 现有可执行质量信号主要是：`setup.py` 构建/导入链、notebook 示例、`tools/vos_inference.py`、`sav_evaluator.py`、demo `/healthy` 与 GraphQL 运行路径；它们都依赖重型运行环境、模型权重或外部数据，不能等同于单元测试。
- 训练与 demo 文档提供了操作型验收口径：MOSE fine-tune 的预期 Base-plus J&F 为 79.4；SA-V evaluator 输出 J/F；demo 健康端点为 `OK`。
- 依赖/权重/CUDA/ffmpeg/PyAV/pycocotools 均可能使“导入成功”与“完整功能可运行”出现差异；后续若补测试，应优先覆盖纯数据模型、状态清理、prompt 输入校验、RLE round-trip、GraphQL schema 生成和无权重的装配检查。

## 9. 关键风险与已发现的实现注意项

### 9.1 环境与资源风险

1. **重型运行时**：主模型依赖 PyTorch、checkpoint 和 GPU/MPS/CPU 设备差异；README/INSTALL 以 Python 3.10+、PyTorch 2.5.1+ 和 CUDA 为主，当前 macOS 环境不应直接假设 CUDA 可用。
2. **安装副作用**：默认安装会尝试编译 CUDA 扩展；宽松模式可能隐藏编译失败，导致运行时后处理能力降级。
3. **权重缺失**：`build_sam2` 可在 `ckpt_path=None` 下构建随机模型，但 demo `InferenceAPI` 固定按 `MODEL_SIZE` 查找 checkpoint；demo 启动无法仅靠源码完成。
4. **导入副作用**：`app_conf.py` 创建目录，`app.py` 预加载视频并构建模型；健康检查不是轻量进程探针，启动失败可能发生在路由注册之前。
5. **内存/并发**：视频 `inference_state` 持有帧、feature、memory 和对象输出；`InferenceAPI.inference_lock` 保护推理但会降低并发吞吐。session 全在内存中，进程重启即丢失。

### 9.2 API 与实现一致性风险

1. `InferenceAPI.add_mask`（`inference/predictor.py:155-193`）调用 `self.model.add_new_mask`，而构造器保存的属性名是 `self.predictor`；按当前源码这是明显的属性名不一致风险，应在未来修复任务中确认并补回归测试。
2. `schema.py:285-290` 的 `process_video` 返回注解声明为四元组 `Tuple[Optional[str], str, str, VideoMetadata]`，实现实际返回 `(filepath, file_key, out_video_metadata)` 三项，契约与实现不一致。
3. `data/store.py:10` 将 `ALL_VIDEOS` 标注为 `Dict[str, Video]`，却初始化为 `[]`；导入后由 `set_videos` 覆盖，仍属于类型/初始状态不一致。
4. `schema.py` 存在重复导入 `CancelPropagateInVideoRequest`；不改变运行语义，但说明 demo API 层缺少静态检查约束。
5. `data/loader.py` 使用 `shutil.which("ffmpeg")` 后直接把结果交给 `subprocess.call`；ffmpeg 缺失时会形成低层调用失败，错误没有转成明确的应用错误。
6. demo 的 GraphQL 上传说明写“configured S3 bucket”，当前实现实际写入本地 `UPLOADS_PATH`；文档/实现语义需要统一。
7. `Video.poster_url` 对 `poster_path=None` 没有显式兜底；无 poster 的上传视频调用该字段可能产生错误 URL。

### 9.3 配置与安全边界风险

1. demo 静态资源路由和上传/传播接口没有认证；`app.py:76` 已明确 TODO：需要 ToS permission check。
2. `send_from_directory` 依赖 Flask 的路径处理，但上传文件名、默认路径和环境变量仍应在部署边界做白名单/权限审计。
3. `process_video` 以临时文件和 SHA-256 文件名去重/落盘，但同名目标、磁盘容量、异常清理和并发上传没有项目级测试证据。
4. GraphQL mutation 直接调用 `InferenceAPI`，输入模型约束主要由 Strawberry 类型承担；对 frame/object/session 关系的业务校验在 predictor 内部，错误以异常为主，缺少统一错误契约。

### 9.4 训练与数据风险

1. 训练默认假设 A100 80GB；配置中的 MOSE、SA-V、SA-1B 路径为空或需用户填写，不能把配置文件存在视为数据可用。
2. 多 GPU/SLURM 依赖正确的 `MASTER_*`、Submitit、CUDA 和数据共享路径；本地 CPU/MPS 不是 README 的默认训练验收环境。
3. 数据加载训练模式失败会随机换样本重试，可能掩盖坏样本比例；验证模式直接抛出异常，需由上层收集数据质量。
4. `Trainer` 的 checkpoint/日志会写入 `sam2_logs` 或配置目录；运行训练前必须明确输出目录，避免污染源码树。

## 10. 可复用设计与边界结论

- **可复用**：`SAM2Base` 的“backbone → memory attention → SAM heads → memory encoder”分层；`SAM2VideoPredictor` 的每对象状态隔离与共享 backbone feature；`SAM2ImagePredictor` 的 embedding 缓存；`SAM2AutomaticMaskGenerator` 的 crop/point batch/NMS 后处理；训练侧 `BatchedVideoDatapoint` 与 Hydra `_target_` 配置化装配。
- **适配建议**：若接入其他平台，应把 PyTorch/模型权重/ffmpeg/PyAV/pycocotools 作为独立重型提供者或独立进程边界，不把 CUDA 扩展和 GPU 状态加载进轻量主进程。
- **数据模型结论**：模型推理状态是运行时内存字典，不是持久化数据库；demo 视频目录是文件系统资源，视频索引是进程内 `ALL_VIDEOS`；checkpoint 是外部不可变权重输入；训练日志/checkpoint 是文件输出。
- **API 结论**：公共 Python 入口是 `build_sam2*`、`SAM2ImagePredictor`、`SAM2VideoPredictor`、`SAM2AutomaticMaskGenerator`；demo 公共入口是 `/healthy`、`/graphql` 与 `/propagate_in_video`。预测输出核心形状为 masks + IoU + low-res logits；demo 再转为 COCO RLE。
- **版本结论**：当前工作树已与远程 `main` 对齐，属于 2024-12-15 的 SAM 2.1 developer suite 后续提交状态；没有“落后远程”的证据，不需要 4780 独立快照。

## 11. 本轮结论

**架构建档完成：** SAM 2 是以 `sam2/build_sam.py` 为装配根、以 `SAM2Base` 为模型骨架、以 `SAM2ImagePredictor`/`SAM2VideoPredictor` 为推理门面、以 `training/` 和 `demo/` 为两条应用扩展面的 PyTorch 视觉分割仓库。核心时序能力由 `inference_state`、`MemoryAttention`、`MemoryEncoder` 和 per-object output dictionaries 共同实现；demo 通过 `InferenceAPI` 将会话式 predictor 封装为 Flask + GraphQL + multipart 流。

**就绪判断：** 源码、README、规则/贡献说明、依赖、配置、入口、模型/会话/API 数据模型、远程版本和已有细探已完成读取并写入本档案；项目级测试文件未发现，完整运行能力仍需真实依赖、权重、媒体数据和设备环境验证。当前最优先的后续工程事项是先修正并测试 demo 层已识别的接口/属性契约风险，再建立不依赖 checkpoint 的最小单测与带小样本权重的冒烟路径。

**本轮未做：** 未安装依赖、未启动服务、未构建 CUDA、未运行训练/推理、未修改源码/依赖/测试/配置、未删除或修改 `细探-sam2.md`、未提交 Git。

## 12. 旧细探逐条吸收裁决（本文件为唯一正式架构档案）

旧细探文件 `细探-sam2.md` 已被完整读取，并逐条与当前源码核对。它仍作为历史工作底稿保留；后续架构事实只维护本文件，不把旧细探当作第二个权威入口。

| 旧细探主张 | 当前源码证据 | 吸收裁决 |
|---|---|---|
| 图像/视频提示式分割，点/框/掩码 prompt | `sam2/sam2_image_predictor.py:237-303`；`sam2/sam2_video_predictor.py:161-381` | 吸收；补充了输入形状、坐标归一化、输出分辨率和状态条件 |
| 图像视为单帧视频、视频跨帧流式记忆 | `sam2/modeling/sam2_base.py:497-676`；`sam2/modeling/memory_attention.py:102-169` | 吸收；实现名是 `MemoryAttention` + `MemoryEncoder` + `output_dict`，不是泛化的“实时保证” |
| model-in-the-loop 数据引擎/SA-V | `README.md:11-13,184-190`；`sav_dataset/` | 部分吸收；仓库提供数据/评估与训练代码，但“数据引擎闭环”是项目定位声明，不等于本仓库内存在完整在线采集服务 |
| `sam2/`、`demo/`、`tools/` 为旁路线索 | 当前真实树中的 `sam2/`、`demo/`、`tools/` | 吸收并扩展为目录与调用链；未把样例媒体/notebook误列为生产模块 |
| Apache-2.0，可借鉴；权重许可另计 | `README.md:196-210`、根 `LICENSE`、`LICENSE_cctorch`、`sav_dataset/LICENSE*` | 吸收；正式结论保留第三方字体、CUDA connected-components 与 SA-V/VOS/DAVIS 文件的单独授权核查要求 |
| 重型 PyTorch + GPU，平台接入应独立进程 | `setup.py:23-32,67-153`；`demo/backend/server/inference/predictor.py:64-92` | 吸收为适配边界建议，不宣称 SAM2 自身实现了进程隔离；demo 实际是单 Flask 进程内模型和会话 |

**不吸收为事实的宣传性表述：** “实时”“最大视频分割数据集”“数据与模型共同进化”只保留为 README/旧细探的项目定位；当前源码能证明的是流式 generator、memory bank 和数据/评估代码，不能证明特定 FPS、在线数据闭环或生产级实时 SLA。

## 13. 精确契约表（源码事实，不以 README 代替实现）

| 入口/契约 owner | 输入与前置条件 | 输出/状态变化 | 错误、重试、超时、取消、幂等 | 资源责任/证据 |
|---|---|---|---|---|
| `build_sam2` | `config_file` 必须能被 Hydra `compose` 找到；`ckpt_path` 可选；`device` 默认 `cuda` | `instantiate(cfg.model)` 后加载 `checkpoint["model"]`，`.to(device)`，可 `eval()`，返回模型 | 配置/依赖异常直接抛出；checkpoint `missing_keys`/`unexpected_keys` 在 `build_sam.py:164-173` 转为 `RuntimeError`；无内建重试/超时/取消/幂等 | 权重由调用方/Hub 管理；模型对象由调用方持有并释放；`build_sam.py:71-97` |
| `build_sam2_video_predictor` | 同上；`vos_optimized=True` 将 target 换成 `SAM2VideoPredictorVOS` 并启用 compile | 返回视频 predictor；默认附加动态 multimask、点交互 memory 二值化、洞填补 override | Hydra/torch.compile/权重异常直接失败；compile 只在构造阶段发生，无取消 | GPU/MPS/CPU 模型由调用方持有；`build_sam.py:100-141` |
| `SAM2ImagePredictor.set_image` → `predict` | RGB `numpy HWC` 或 PIL；先 `set_image`；prompt 可点/框/低分辨率 mask；点标签必须随坐标提供 | `_features={image_embed,high_res_feats}`；返回原图分辨率 masks、IoU、`C×256×256` low-res logits；默认二值化，`return_logits=True` 保留 logits | 未 set image、格式不支持、形状断言失败抛 `RuntimeError`/`NotImplementedError`/`AssertionError`；无重试/超时/取消；`reset_predictor` 清缓存 | predictor 持有特征/原始尺寸；`sam2_image_predictor.py:85-129,237-303,459-466` |
| `SAM2VideoPredictor.init_state` | MP4 bytes/path 或 JPEG 目录；输入由 `load_video_frames` 支持；可选择帧/状态 CPU offload、异步 JPEG 加载 | 返回可变 `inference_state`，包含帧、尺寸、设备、对象映射、prompt、cache、per-object cond/non-cond outputs | 非 MP4/JPEG 目录 `NotImplementedError`；异步加载异常在取帧时重新抛；无 API 超时；未提供持久化或跨进程恢复 | 视频帧/feature/memory/state 由会话持有；`sam2_video_predictor.py:41-99`、`utils/misc.py:104-239` |
| `add_new_points_or_box` / `add_new_mask` | video frame/object；点与 label 必须成对；至少 point 或 box；mask 必须二维；box 要求清旧点 | 更新 prompt 输入与临时输出，调用 `track_step(run_mem_encoder=False)`，返回当前帧原视频分辨率 masks | 参数/顺序/空输入 `ValueError`/`AssertionError`；同一会话重复调用是覆盖/追加语义，不是幂等；取消不适用于单次调用 | 临时输出留在 `temp_output_dict_per_obj`，传播 preflight 时才写 memory；视频文件/状态仍由调用方负责；`sam2_video_predictor.py:161-381` |
| `propagate_in_video` | 每对象必须已有 conditioning 输出；可指定起帧、最大帧数、正/反向 | 先 `propagate_in_video_preflight`，再逐帧 `yield(frame_idx,obj_ids,video_res_masks)`；写 `non_cond_frame_outputs` 和 `frames_tracked_per_obj` | 无对象/对象无 prompt `RuntimeError`；帧范围由 `range` 裁剪；生成器关闭/异常由上层决定，模型无 deadline；反向只是顺序/时序符号反转 | 每帧 mask memory、pos enc、obj ptr 写入状态；`sam2_video_predictor.py:479-630` |
| `SAM2AutomaticMaskGenerator.generate` | HWC `uint8` image；`points_per_side` 与 `point_grids` 必须二选一；输出模式受限 | 多 crop/网格点批推理，经 IoU、稳定性、边缘、NMS、小区域后处理后返回 records | 参数断言；`coco_rle` 缺 `pycocotools` 直接 ImportError；无取消/超时/幂等 | 内部复用 `SAM2ImagePredictor`；mask records 仅内存返回；`automatic_mask_generator.py:36-170` |
| demo `InferenceAPI` 会话 | `start_session.path` 可读；模型 checkpoint/config 可用；设备 CUDA→MPS→CPU；会话 id UUID | `session_states[session_id]={canceled,state}`；点/掩码/清理/删对象/传播转为 RLE | 会话不存在 `RuntimeError`；传播通过共享 `canceled` 标记合作取消；`inference_lock` 串行推理；无超时、TTL、跨进程幂等；`close_session` 才从字典移除 | 全局模型、全局会话字典、锁和 RLE 编解码；`demo/backend/server/inference/predictor.py:43-118,270-427` |
| demo `process_video` / GraphQL `upload_video` | multipart Upload；PyAV 可读；视频流、尺寸、时长有效；时长按 `MAX_UPLOAD_VIDEO_DURATION` 截断 | TemporaryDirectory 写入 `in.mp4/out.mp4`，transcode 后以 SHA-256 文件名移动至 `UPLOADS_PATH`，返回 `Video`；`get_video` 只构造返回对象，不自动调用 `set_videos` 更新启动时的 `ALL_VIDEOS` | 无效容器/缺 stream/缺尺寸/缺 duration/空转码结果抛通用 `Exception`；同 hash 目标、磁盘/ffmpeg/并发异常无项目级回滚/重试契约；源码注解仍错误声明四元组，实际 `schema.py:351` 返回三元组 | 临时目录退出清理；`in_path` 主动删除；`shutil.move` 后文件成为持久上传；`schema.py:285-351`、`app_conf.py:22-55` |

## 14. 真实对接链与关键节点

### 14.1 Python 图像/自动 mask 链

```text
调用方
  → build_sam2(config_file, ckpt_path, device)
  → Hydra compose/OmegaConf.resolve/instantiate(cfg.model)
  → _load_checkpoint(torch.load(...)["model"])
  → SAM2Base.forward_image
  → ImageEncoder(Hiera + FpnNeck)
  → _prepare_backbone_features
  → SAM2ImagePredictor._predict
  → PromptEncoder(points/box/mask)
  → MaskDecoder(TwoWayTransformer)
  → interpolate + threshold/logits
  → numpy masks + IoU + low-res logits
```

`SAM2AutomaticMaskGenerator.generate` 在这个链条前面加入 crop/point-grid，在后面加入 `pred_iou_thresh`、stability score、`batched_nms`、RLE/小区域后处理；它没有独立模型内核。

### 14.2 视频交互/传播链

```text
MP4/JPEG目录
  → load_video_frames / AsyncVideoFrameLoader
  → SAM2VideoPredictor.init_state
  → _obj_id_to_idx 注册 client obj_id
  → add_new_points_or_box 或 add_new_mask
  → _get_image_feature（单帧 backbone cache）
  → track_step
      → _prepare_memory_conditioned_features
          → 选择 cond_frame_outputs + temporal-stride non-cond memory
          → 拼接 object pointers + temporal PE
          → MemoryAttention
      → _forward_sam_heads
          → PromptEncoder → MaskDecoder
      → _encode_new_memory → MemoryEncoder
  → temp_output_dict_per_obj
  → propagate_in_video_preflight（合并对象/非重叠约束/补 memory）
  → propagate_in_video（逐帧写 non_cond outputs）
  → video_res_masks
```

交互帧刻意 `run_mem_encoder=False`，待用户完成点击后由 preflight 统一编码；这不是遗漏，而是为多对象非重叠约束留出重新编码点。`SAM2Base.track_step` 的事实证据为 `sam2/modeling/sam2_base.py:814-879`。

### 14.3 Demo HTTP/GraphQL 链

```text
Flask import
  → app.py:32 preload_data/set_videos
  → app.py:35 InferenceAPI()
      → build_sam2_video_predictor
  → /graphql Strawberry Mutation
      → data/schema.py 输入转换
      → inference.data_types request
      → InferenceAPI
      → SAM2VideoPredictor
      → masks → pycocotools.encode(F-order) → GraphQL RLE

POST /propagate_in_video
  → request.json(session_id,start_frame_index)
  → gen_track_with_mask_stream
  → InferenceAPI.propagate_in_video generator
  → MultipartResponseBuilder
  → multipart/x-savi-stream
```

HTTP 层目前是单进程内存架构：`app.py:29-35` 导入即预加载和构造模型；`app.py:76` 仍留有 ToS 权限检查 TODO；静态视频路由、上传、GraphQL 和 propagation 没有认证契约。`InferenceAPI.add_mask` 在 `predictor.py:178` 调用 `self.model.add_new_mask`，但构造器实际属性是 `self.predictor`（`predictor.py:89-92`），按当前源码这是未修复的明显运行时断链，不能把 GraphQL/HTTP 路径视为已通过。

## 15. 关键节点明细

| 节点 | 前置条件 | 状态/读写 | 并发与失败分支 | 证据 |
|---|---|---|---|---|
| Hydra 模型装配 | 配置、权重、torch/device | 读取 YAML/权重，创建 `nn.Module`；无数据库 | 同一调用内同步；权重键不全立即失败；动态 compile 可能在首次 forward 慢/失败 | `build_sam.py:71-97,100-141,164-174` |
| backbone/cache | 输入 tensor 形状和 image size | 读图像；视频将最近一帧 `(image,backbone_out)` 放到 `cached_features`，image predictor 放 `_features` | cache 是会话局部、无 TTL；异常不做统一回滚 | `sam2_video_predictor.py:704-735`；`sam2_image_predictor.py:99-129` |
| memory 选择 | 非初始 conditioning frame 且已有 cond 输出 | 读取 cond/non-cond 输出，按 temporal stride 选最近 memory；可附加 object pointers | 缺 memory 跳过；缺全部 cond 断言失败；显存压力靠 CPU offload/限制 cond 数缓解 | `sam2_base.py:497-676` |
| mask heads | backbone 特征 `[B,C,H,W]`、prompt 互斥/形状正确 | 产生 low/high-res logits、IoU、object pointer、object score；无外部写 | 形状断言；无 prompt 时填充 label `-1`；对象不存在由上游占位/score处理 | `sam2_base.py:257-413` |
| memory encoder | high-res mask、对象 score、当前视觉特征 | sigmoid/可选二值化→`MaskDownSampler`→pix feature fuse→position encoding；写回 compact output | memory encoder 可被交互跳过；非重叠约束可在 eval 应用；异常终止当前推理 | `sam2_base.py:678-726`；`memory_encoder.py:138-181` |
| preflight consolidation | 每个对象至少一个 cond frame | 清空 temp，补 maskmem，删除冲突 non-cond 输出；可清理周边旧 memory | 零对象/缺对象输入直接失败；不执行补偿事务，部分对象写入后异常可能留下部分状态 | `sam2_video_predictor.py:479-544` |
| object removal | object id 映射存在或 `strict=False` | 删除输入/输出字典并重排 object index；返回受影响帧 mask | 单对象走 `reset_state`；不存在默认静默成功；重排失败无回滚 | `sam2_video_predictor.py:866-954` |
| demo cancellation | session 已存在、传播 generator 正在消费 | 写 `session["canceled"]`；传播每次 yield 前检查并 `return None` | 协作取消，不打断当前 kernel；无 deadline/强制终止/状态回收；GeneratorExit 仅进入 finally 日志 | `predictor.py:270-362` |
| upload persistence | PyAV/ffmpeg 可用、输出非空 | 临时文件→转码→hash→移动到 uploads；`get_video` 构造返回对象但不自动更新启动时 `ALL_VIDEOS` | 临时目录保证普通异常清理；移动后失败没有数据库事务/删除补偿；同 hash 行为未定义 | `schema.py:285-351`；`data/loader.py:39-92`；`data/store.py:1-25` |

## 16. 资源生命周期与四种终态

| 资源 | 创建/持有 | 正常完成 | 业务失败 | 主动取消/超时 | 宿主/子进程崩溃与残留验证 |
|---|---|---|---|---|---|
| 模型/显存 | `build_sam2*` 创建，predictor/API 持有 | 进程存活至调用方释放；无显式 `close()` | 异常由 Python 栈传播；部分 GPU tensor 仍由引用持有 | 取消只停止后续 generator yield，不释放模型/会话 | 进程崩溃由 OS 回收显存；源码无 watchdog/残留探针 |
| 视频帧 | `load_video_frames`/异步线程加载；state `images` 持有 | state 继续持有，直到 demo `close_session`/调用方丢弃 | 加载线程异常保存到 `exception`，下次访问转 `RuntimeError`；无整体回滚 | 无内建 deadline；取消不清帧 | daemon 线程随进程结束；文件目录不由 predictor 删除；需外部检查线程/FD |
| `inference_state` | `init_state` 建 dict，demo 放入 `session_states` | `propagate` 追加 outputs；可 `reset_state` 清内容 | preflight 中途失败可能留下已写对象/临时输出；无事务快照 | cancel 保留 state 及已产出结果，便于继续/重置 | 进程重启全部丢失；无持久化/恢复/TTL |
| cache/memory/output tensors | predictor per-state dict；可 CPU offload/bfloat16 | 作为后续帧 memory 被读取 | 部分 frame 写入可能保留；无 finally 清理 | 取消后仍在 state 中；只有 reset/close 释放引用 | Python/torch 引用随进程回收；需读 `session_states`、GPU allocator 和进程状态验证 |
| 上传临时文件 | `TemporaryDirectory` 中 `in.mp4/out.mp4` | move 到 `UPLOADS_PATH` 后临时目录退出 | 普通异常退出上下文清理；`in_path` 在 move 前显式删除 | 无上传取消 API；客户端断连依赖 WSGI/异常路径 | 崩溃可能留下系统临时文件；应检查 temp 目录与 uploads，源码未提供清扫任务 |
| demo 全局锁/线程 | `InferenceAPI.inference_lock`；可选 AsyncVideoFrameLoader daemon thread | 锁自动释放（`with`）；线程完成或持续至加载结束 | 异常仍释放锁；线程错误延迟抛出 | 取消不杀线程，不释放锁外资源 | daemon 线程不保证业务收尾；需要运行时读取线程/进程，没有本轮实测 |
| 训练进程/日志/checkpoint | `single_node_runner` spawn 或 Submitit；`makedir` 创建 experiment dir | logger/checkpoint 由 Trainer 训练循环写入 | 子进程异常向上抛；Submitit 记录 job；checkpoint 采用临时文件替换（源码/文档约定） | SLURM timeout/preemption 依赖 Submitit checkpointable，非模型状态机保证 | 需外部检查 rank 进程、NCCL/端口、临时 checkpoint；本轮未启动训练 |

**资源结论：** 源码对正常 Python 上下文有局部清理（锁、TemporaryDirectory、reset/close），但没有统一的超时、强取消、崩溃恢复、会话 TTL、显存泄漏探针或跨进程状态持久化。任何“资源已释放”只能按路径分别验证，不能用生成器结束或健康端点代替。

## 17. 失败、超时、取消、崩溃矩阵

| 场景 | 当前实现行为 | 证据等级 | 真实风险/尚缺 |
|---|---|---|---|
| 非法 prompt/点标签缺失/box 与旧点冲突 | `ValueError`/`AssertionError`，通常不改正式输出但输入字典可能已先注册对象 | L1 静态源码 | 需要边界测试确认异常前状态是否干净 |
| 空对象传播/某对象无 conditioning | preflight `RuntimeError`；对象映射可能已创建 | L1 静态源码 | 无事务 rollback；可残留部分对象结构 |
| checkpoint 缺键/多键/配置错误 | 构建直接失败 | L1 静态源码 | 未执行真实权重加载 |
| MP4/JPEG 缺失、异步加载失败、坏视频 | `NotImplementedError` 或延迟 `RuntimeError`；PyAV/ffmpeg 错误多为通用异常 | L1 静态源码 | 错误码不统一；未实测依赖环境 |
| 单次推理超时 | 无 API timeout/deadline；调用线程持续占用 `inference_lock` | L1 静态源码 | WSGI/客户端断开时的 generator/锁/显存行为未验证 |
| 传播主动取消 | session 标记 `canceled`，下一次循环检查后 return；当前帧 kernel 不可抢占 | L1 静态源码 | 结果与状态保留策略未契约化；无强取消/清理 |
| GeneratorExit/客户端断连 | `finally` 只写日志 | L1 静态源码 | 需实测是否锁释放、后续状态可否重用 |
| 进程崩溃/OOM/MPS crash | OS/PyTorch 负责进程级回收，无应用恢复 | L1 静态源码 + README 环境说明 | session/上传索引丢失；无 checkpoint/state journal |
| 部分上传/同 hash/磁盘满 | TemporaryDirectory 覆盖普通异常；移动后无事务 | L1 静态源码 | 需注入文件系统故障验证残留和索引一致性 |
| 训练 preemption/分布式 rank 失败 | Submitit/异常日志/周期 checkpoint 路径 | L1 静态源码 | 未运行 SLURM；不能宣称可恢复闭环 |

## 18. 防假绿验证等级 L0-L4

| 等级 | 何时可标记 | 本项目证据/本轮状态 | 不允许冒充 |
|---|---|---|---|
| **L0 存在性** | 文件、符号、配置、依赖声明存在 | 本轮读取源码；找到 63 个 Python 文件，根 `tests/` 与测试文件未发现 | 不能说功能可运行 |
| **L1 静态可解释** | 入口、调用链、分支、错误路径能由源码逐行解释 | 已核对 `build_sam*`、image/video predictor、memory、demo、训练入口；Python AST 解析 63/63 成功，退出码 0 | 不能说权重、设备、外部依赖已验证 |
| **L2 隔离执行** | 在无生产写入、明确 fixture/无权重环境执行最小契约探针 | 本轮仅运行 AST 与 Git/远程只读检查；未执行模型推理/HTTP/GraphQL/训练 | 不能把 import、打印日志或文档示例算 L2 |
| **L3 真实链路** | 真实依赖+权重+小图片/小视频跑通并读回输出、状态与资源 | 未执行；缺少本轮安装/权重/设备/媒体准备证据 | 不能把 README 指标、历史二进制或子代理回执算通过 |
| **L4 受压/故障验收** | 真实链路上验证超时、取消、断连、OOM/重启、残留清理、并发和回滚 | 未执行；源码没有完整统一治理实现 | 不能宣称生产就绪、实时 SLA 或崩溃恢复 |

本轮可验证结论是 **L0-L1：静态建档完成；L2-L4 未验证**。`git ls-remote origin refs/heads/main` 返回 `2b90b9f5ceec907a1c18123530e92e794ad901a4`，与本地 `HEAD` 相同，退出码 0；工作树只有未跟踪的 `ARCHITECTURE.md` 与 `细探-sam2.md`，没有源码/配置/依赖/测试改动。

## 19. 未验证项、吸收/不吸收与剩余风险

### 19.1 未验证项

- 未安装或锁定 PyTorch、TorchVision、Hydra、PyAV、ffmpeg、`pycocotools`、CUDA/MPS 运行环境；未下载 checkpoint。
- 未执行 `pip install -e .`、CUDA extension build、图像/视频推理、自动 mask、VOS PNG 导出、SA-V evaluator、demo `/healthy`、GraphQL 或 multipart 流。
- 未验证 `torch.compile`、CUDA/MPS 数值差异、CPU 路径性能、异步帧加载竞态、GPU/CPU offload 后的状态一致性。
- 未验证非法输入后的状态回滚、重复 prompt 语义、传播 generator 关闭/客户端断连、取消后的会话复用、进程崩溃重启、OOM/磁盘满/同 hash 上传和训练 preemption。
- 未发现项目级自动化测试目录/文件；notebook、README 指标和历史 checkpoint 不能替代测试。

### 19.2 吸收裁决

- **吸收**：SAM2 的四段模型分层、图像/视频统一入口、per-object session state、streaming memory、自动 mask 的批处理/NMS、Hydra 配置化训练与 demo 的 RLE/流式边界。
- **适配后吸收**：将模型/权重/设备/ffmpeg/PyAV/CUDA 扩展包在独立 provider 或进程边界；把 session 生命周期、取消、超时、资源清扫和错误码补为平台契约。这是平台建议，不是当前仓库已实现事实。
- **待核**：demo 的 `add_mask` 属性断链、`process_video` 返回注解漂移、上传并发/同 hash、权限 TODO、GraphQL 输入业务校验、训练 checkpoint/SLURM 恢复和 MPS 稳定性；必须先有针对性测试/运行证据。
- **不吸收**：把 README 的实时/最大数据集/数据闭环宣传语、A100 benchmark、历史指标或“CUDA 编译失败可忽略”直接升级为生产 SLA/质量结论；也不吸收 Flask demo 的无认证和全局内存 session 作为平台底座模式。

### 19.3 剩余风险排序

1. **阻断**：`InferenceAPI.add_mask` 当前调用 `self.model` 而非已构造的 `self.predictor`，该 HTTP/GraphQL 能力按静态证据不可用；模型权重/依赖/设备未验证。
2. **重要**：取消、超时、断连、崩溃、OOM 和部分写入没有统一资源治理；进程重启会丢失全部 session 与进程内视频索引。
3. **重要**：上传路径无认证，权限 TODO 未闭环；ffmpeg/PyAV/磁盘和同 hash 并发缺少统一错误/回滚契约。
4. **建议**：补充无权重纯契约测试、最小图像/视频 fixture、RLE round-trip、session reset/remove/cancel、故障注入和真实设备矩阵，再把 L2→L4 证据写回本文件。

## 20. 维护规则与证据索引

- `ARCHITECTURE.md` 是本项目唯一正式架构事实源；`细探-sam2.md` 本轮不删除，定位为历史细探底稿，后续不并行维护。
- 任何后续更新必须附当前提交/工作树、源码路径（必要时行号）、验证命令和退出码；声明、历史 benchmark、子代理回执不得单独升级为通过。
- 当前关键证据索引：`sam2/build_sam.py`；`sam2/modeling/sam2_base.py`；`sam2/modeling/memory_attention.py`；`sam2/modeling/memory_encoder.py`；`sam2/sam2_image_predictor.py`；`sam2/sam2_video_predictor.py`；`sam2/automatic_mask_generator.py`；`demo/backend/server/app.py`；`demo/backend/server/inference/predictor.py`；`demo/backend/server/data/schema.py`；`training/train.py`；`training/trainer.py`；`setup.py`；`README.md`。
- 当前基线：本地 `HEAD=2b90b9f5ceec907a1c18123530e92e794ad901a4`，远程 `origin/main` 同值；本轮只允许并只修改本文件，旧细探保留。

## 20A. 第二轮收口补充：模型、predictor、状态、显存、批处理与崩溃边界

本节只补充第二轮项目内部事实，优先记录前文尚未展开、容易被“能导入/能打印日志”掩盖的边界；不是第三轮底座方案。所有结论均来自当前提交源码静态核对，仍属于 L1，未因写入本节而升级为真实设备或权重验证。

### 20A.1 模型装配的真实阶段与失败点

```text
import sam2
  → sam2.__init__.initialize_config_module("sam2")（只初始化一次 Hydra 全局状态）
  → build_sam2* 的 Hydra compose + OmegaConf.resolve
  → instantiate(cfg.model, _recursive_=True)（模型参数先在 CPU）
  → torch.load(ckpt_path, map_location="cpu", weights_only=True)["model"]
  → model.load_state_dict（默认 strict=True；源码还写显式 missing/unexpected 检查）
  → model.to(device)
  → mode == "eval" 时 model.eval()
```

| 阶段 | 当前源码事实 | 崩溃/资源边界 |
|---|---|---|
| 包导入 | `sam2/__init__.py:7-11` 调用 `initialize_config_module("sam2", version_base="1.2")`，且用 `GlobalHydra` 防止重复初始化 | Hydra 全局状态属于进程级；在错误工作目录/重复初始化场景下不是 predictor 自己可恢复的错误 |
| 工作目录保护 | `build_sam.py:17-31` 检测 `sam2.__path__[0]/sam2`，怀疑从仓库父目录导入时主动抛 `RuntimeError`，避免仓库名遮蔽 Python 包 | 这是导入阶段硬失败，尚未分配模型/显存；不能把“源码文件存在”当作可导入 |
| 配置实例化 | `compose`、`OmegaConf.resolve`、`instantiate` 都是同步调用；配置路径、Hydra target、依赖构造异常直接向上抛 | 没有统一错误码、重试、超时或半构造模型回收钩子；`instantiate` 成功不代表 checkpoint 兼容 |
| checkpoint | `torch.load(..., map_location="cpu", weights_only=True)["model"]` 先在 CPU 读出 state dict；`model.load_state_dict(sd)` 使用 PyTorch 默认 `strict=True`，源码随后还对返回的 `missing_keys`、`unexpected_keys` 做显式检查 | 没有 SHA-256、文件大小、模型版本、来源或 config/checkpoint 绑定校验；缺键/多键通常已由 strict load 直接抛 `RuntimeError`，损坏文件/缺少 `model` 键/反序列化错误也直接失败 |
| 设备迁移 | `model.to(device)` 在 checkpoint 校验后执行；`ckpt_path=None` 时允许随机初始化模型 | `.to(device)` 可能在 CPU 模型仍存活时产生 CPU+设备侧峰值；函数没有显式 `del`、`empty_cache` 或失败回滚 |
| eval 模式 | 仅当 `mode == "eval"` 才调用 `model.eval()`；其他字符串不会自动切到 train/eval | 推理入口依赖调用方传入正确 mode；源码没有把 `inference_mode` 或 autocast 固化在 `build_sam2*` 内 |
| HF 装配 | `_hf_download` 只按白名单 `HF_MODEL_ID_TO_FILENAMES` 下载 checkpoint；config 名称仍走已安装包的 Hydra config module；随后复用同一 build 链 | 网络、HF 缓存、未知 model id 或本地 config 不可见时在模型完成前失败；不存在隐式 fallback 到其他模型 |

`build_sam2_video_predictor` 的默认 override 不是纯别名：它额外开启 dynamic multimask、交互帧 memory 二值化和 `fill_hole_area=8`（`build_sam.py:119-131`）。`vos_optimized=True` 把 target 改为 `SAM2VideoPredictorVOS` 并开启 image encoder compile；`SAM2VideoPredictorVOS.__init__` 随后还会对 memory encoder、memory attention、prompt encoder、mask decoder 逐一 `torch.compile`（`sam2/sam2_video_predictor.py:976-1011`）。因此优化模式的失败面不只是权重加载，还包括 compile 的 fullgraph/dynamic 约束；首次 forward/compile 可能很慢，README 的 A100 FPS 不能外推到其他设备。

### 20A.2 图像 predictor：缓存是单图状态，批处理不是全链路批推理

`SAM2ImagePredictor` 的状态只有 `_is_image_set`、`_features`、`_orig_hw`、`_is_batch`（`sam2/sam2_image_predictor.py:51-66`）。`set_image` 一开始就调用 `reset_predictor()`，因此新图像类型、转换或 backbone 失败时，旧 embedding 已经被丢弃；它不会保留“上一个可用图像”作为回退。

```text
set_image / set_image_batch
  → reset_predictor
  → SAM2Transforms(ToTensor → Resize(image_size) → Normalize)
  → model.forward_image
  → _prepare_backbone_features（扁平化视觉特征）
  → _features.image_embed + high_res_feats
  → predict / predict_batch
  → prompt encoder + mask decoder
  → 插值回原图尺寸 → logits clamp(-32, 32) → 可选 threshold
  → CPU numpy
```

| 入口/状态 | 精确语义 | 边界 |
|---|---|---|
| `set_image` | 接受 RGB `numpy` 或 PIL；numpy 原始尺寸取 `shape[:2]`，PIL 取 `(h,w)`；预处理后只以 batch=1 调 backbone | 不支持的类型在 reset 后抛 `NotImplementedError`；只做形状/通道断言，不校验 RGB 数值范围或 dtype 的所有异常组合 |
| `set_image_batch` | 只接受 `list[np.ndarray]`；一次 batched backbone 得到 B 份 embedding；设置 `_is_batch=True` | 没有空列表、列表长度、原始尺寸一致性或 prompt 列表长度的显式契约；B 越大，backbone 激活和 `_features` 同时驻留越多 |
| `predict` | 单图入口，默认 `img_idx=-1`；prompt 在 `device` 上转换，点可按原图尺寸归一化，box 转为两个特殊点 label 2/3 | 未 set image 直接 `RuntimeError`；点有而 labels 无是 `AssertionError`；无统一错误码/取消/超时 |
| `predict_batch` | 先断言 `_is_batch`，然后对每个 image index 逐个调用 `_predict`，每次结果立即转 CPU numpy 并 append | 它批量化了 image backbone，不是多个 image 的 mask decoder 全向量化；公共入口没有并行 worker/显存预算。`set_image_batch` 后误调用 `predict` 没有专门拒绝，默认索引为最后一张图，属于调用方必须避免的状态错配 |
| `_predict` | 内部可对单图传入 B 组 point prompt，触发 decoder 的 `repeat_image`；mask decoder 内部还产出 object token/score，但 image predictor 只取 low-res logits 与 IoU；mask 上采样后 logits 限幅到 `[-32,32]` | `return_logits=False` 才阈值化；输出转换为 numpy 会把结果从设备侧拷回 CPU，流式/大图调用方需承担峰值和拷贝时间 |
| `reset_predictor` | 只把四个 predictor 字段置空/false | 没有显式释放 CUDA cache；实际释放依赖 Python/Torch 引用计数和调用方不再持有旧 tensor |

`SAM2Transforms.postprocess_masks` 和视频 `fill_holes_in_mask_scores` 捕获 connected-components 异常后告警并跳过后处理（`sam2/utils/transforms.py:76-118`、`sam2/utils/misc.py:312-338`）。这是一条“主推理可继续、后处理降级”的源码路径，不能写成 CUDA 扩展失败等价于整条推理失败；但也不能写成后处理结果一致，因为小洞/小散点清理已被跳过。

### 20A.3 视频输入、`inference_state` 与对象状态机

`init_state` 在 `@torch.inference_mode()` 内建立一次会话并主动预热 frame 0（`sam2/sam2_video_predictor.py:41-99`）。输入分派由 `load_video_frames` 决定（`sam2/utils/misc.py:172-210`）：`bytes` 或 `.mp4/.MP4` 进入 `decord`，目录只接受扩展名为 jpg/jpeg 的文件并按文件名整数排序；其他格式直接 `NotImplementedError`。MP4 路径不启用 `async_loading_frames`，异步加载只属于 JPEG 目录。

| 状态区域 | 创建/更新 | 关键边界 |
|---|---|---|
| `images` | MP4 由 `decord.VideoReader` 遍历全部帧后 `torch.stack`；JPEG 同步路径先分配完整 `[num_frames,3,image_size,image_size]`，异步路径是定长 list + daemon thread | 不是按需视频解码；长视频首先消耗与帧数成正比的 CPU/GPU 图像存储。MP4 空流、坏帧、JPEG 目录坏文件可能在初始化或首次访问时失败 |
| `cached_features` | `_get_image_feature` 命中则复用，否则把当前 image 搬到 compute device，运行 backbone，并把 cache **替换为仅一个 frame_idx**（`sam2/sam2_video_predictor.py:704-735`） | 不是多帧 LRU；跨帧传播会反复算 backbone，重复点击同帧才受益；没有 TTL、大小上限或失败回滚 |
| `constants` | 首次得到 `maskmem_pos_enc` 时缓存一份并按对象数 expand（`841-864`） | `reset_state` 不清 `constants`、`cached_features`、`images` 或视频 loader；它只清 tracking 输入、对象映射和输出字典（`676-702`）。会话真正释放依赖丢弃整个 state 引用 |
| 对象映射 | `_obj_id_to_idx` 首次看到 client `obj_id` 就分配连续 model index，并创建该对象的输入/临时/正式输出字典；允许传播开始后新增对象 | `add_new_points_or_box`/`add_new_mask` 在参数完整性检查前就注册对象；非法 prompt 可能留下空对象映射，后续 preflight 再失败 |
| 临时输出 | 交互调用 `track_step(run_mem_encoder=False)`，结果写入 `temp_output_dict_per_obj`；返回当前帧原视频分辨率 mask | 每次点击可覆盖同一 frame 的临时 slot；memory 不在点击时编码，必须等 preflight |
| preflight | 逐对象把 temp output 编码为 memory、写入正式 `cond/non-cond` 输出并清空 temp；随后检查每个对象至少有 conditioning output | 检查是在循环中进行；前面对象已写入、后面对象缺 prompt 时抛错，没有事务快照或整体 rollback |
| 正式输出 | 每帧 compact output 保留 `maskmem_features`、共享/缓存的 `maskmem_pos_enc`、`pred_masks`、GPU 上的 `obj_ptr`、`object_score_logits` | `reset_state` 清字典但不主动移除 tensor；多次传播可覆盖同一 frame 的 `non_cond_frame_outputs`，没有 request id/幂等表 |
| 删除对象 | 多对象时先清输入/可能降级 conditioning，再重建 id/index 映射并重排五类 per-object dict；单对象直接 `reset_state` | 重排不是事务；未知 id 在 `strict=False` 下静默返回；单对象删除会清空全部对象 tracking 结果但仍保留视频/feature 区域 |

交互坐标有两套调用约定：predictor 默认 `normalize_coords=True`，会按原视频宽高归一化再乘 `image_size`；demo 的 `InferenceAPI.add_points` 显式传 `normalize_coords=False`，因此 demo 发送的是模型内部坐标而不是通用 API 的原视频像素坐标（`demo/backend/server/inference/predictor.py:120-142`）。这不是可跨入口互换的参数语义。

`propagate_in_video` 的范围是 Python `range(start, end+1)`（`sam2/sam2_video_predictor.py:560-581`），所以 `max_frame_num_to_track` 表示参与边界计算的跨度，不严格等于产出帧数：正常方向通常包含起始帧并可能得到 `max_frame_num_to_track + 1` 个索引，边界帧会再裁剪。反向同样包含起始帧。调用方若需要“最多 N 帧”必须在外层按事件序号/帧数再限额，不能只依赖参数名。

### 20A.4 GPU、MPS、offload 与显存峰值的真实归属

| 资源/策略 | 实际位置与行为 | 不能误读为 |
|---|---|---|
| 模型参数 | `SAM2Base.device` 取第一个 parameter 的 device；`build_sam2*` 最后统一 `.to(device)` | 不是每个 session 一个模型；demo 是一个进程级 predictor，所有 session 共享模型参数和设备上下文 |
| autocast | README 示例由调用方包住 `torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16)`；demo 仅 CUDA 返回 bfloat16 autocast，MPS/CPU 为 `nullcontext`（`predictor.py:94-98`） | build/predictor 自身对所有平台都自动启用混合精度；MPS 不能据此推断与 CUDA 数值一致 |
| `offload_video_to_cpu` | false：整段已预处理视频在 compute device；true：图像留 CPU，每帧 `_get_image_feature` 时搬到 compute device | 不是流式解码，也不减少模型参数/当前帧 activation；它主要减少帧常驻设备侧显存，增加 PCIe/设备拷贝成本 |
| `offload_state_to_cpu` | `storage_device=cpu` 时，`maskmem_features` 转 bfloat16 后存 CPU，`pred_masks` 也存 storage device；读取 memory 时再搬回 compute device | 不是所有 state 都在 CPU：`cached_features`、`obj_ptr`、`object_score_logits` 仍在 compute device；`maskmem_pos_enc` 由 `constants` 缓存且代码只 clone/expand，不能简单宣称整体 offload |
| memory 上限 | 默认 `num_maskmem=7`，代表 1 个 conditioning + 6 个历史 memory；eval 以 `memory_temporal_stride_for_eval` 取历史，`max_cond_frames_in_attn=-1` 表示不限制 conditioning frame 数（`sam2/modeling/sam2_base.py:28-39,58-61`） | “streaming memory” 自动等价于固定显存上限；conditioning frames、对象指针、输出字典仍可能随交互增长 |
| 多对象 | 每帧按对象循环调用 `_run_single_frame_inference(batch_size=1)`，最后 `torch.cat` 当前帧对象 mask；`_get_image_feature` 只把同一 backbone feature expand 到对象维 | 不是多对象全链路并行；对象数提高 decoder/memory/output 和当前帧拼接峰值 |
| demo 观测 | `__get_session_stats` 记录 `torch.cuda.memory_allocated/reserved/max_*`，且 max 是进程级累计值（`predictor.py:399-415`） | 不是每 session 的峰值、不是 MPS/CPU 指标、不是预算/泄漏探针；没有在 session close 时 reset peak stats |

模型内存还存在两类容易漏记的常驻引用：`cached_features` 保存 image/backbone 输出；每个正式 frame output 保存 mask memory、mask、object pointer/score。`reset_state` 只清 dict，不调用 `torch.cuda.empty_cache()`；demo `close_session` 只是从 `session_states` pop（`predictor.py:417-427`），没有 `reset_state`、同步活动 generator、释放模型或确认 allocator 下降。故“字典删除”只证明索引删除，不证明显存已经归还系统。

### 20A.5 批处理、自动 mask 与临时资源

自动 mask 的批处理边界是明确的两级循环：每个 crop 重新 `set_image` 计算 embedding；每个 crop 内按 `points_per_batch` 分组调用 `_process_batch`（`automatic_mask_generator.py:224-292`）。`points_per_batch` 越大，点 prompt/mask decoder 并行度和设备峰值越高；它不改变 crop 数。`crop_n_layers>0` 会追加多层 crop，所有 crop 的 `MaskData` 先 `cat` 到总集合，最后才跨 crop NMS 和 `to_numpy`。因此：

- `binary_mask` 会把每个保留 mask 解码为完整二维数组，高清图/大量候选会放大 CPU 内存；`coco_rle` 只改变最终编码格式，不能避免前面的候选、RLE、NMS 中间数据；
- `_process_crop` 对每个 batch `del batch_data`、对模型输出 `del masks`，这是局部引用释放，不是 allocator flush；
- `use_m2m=True` 会对保留下来的 low-res mask 再按同一 `points_per_batch` 分批 refinement，额外执行 decoder 和中间 list 拼接；
- `min_mask_region_area>0` 依赖 OpenCV，`coco_rle` 依赖 `pycocotools`；依赖缺失在构造/后处理边界失败，而不是统一降级。

视频帧加载与 demo 上传是两套临时资源模型：

| 资源 | 源码生命周期 | 失败/崩溃边界 |
|---|---|---|
| JPEG 异步线程 | `AsyncVideoFrameLoader` 先同步读取 frame 0，再创建 daemon `Thread` 遍历所有 frame；异常存入 `self.exception`，下次 `__getitem__` 才转成 `RuntimeError`（`misc.py:104-169`） | 没有 stop/join；会话关闭或 generator 取消不会主动停止线程。daemon 只保证解释器退出时不阻止进程结束，不保证业务清理或已读文件引用核对 |
| MP4/decord | `load_video_frames_from_video_file` 把 `VideoReader` 全部 frame 读入 list，stack 后按 offload 策略搬设备（`misc.py:280-309`） | 无 decode timeout、帧数上限或逐帧 backpressure；坏视频/内存不足可在 state 返回前直接失败 |
| demo upload | `schema.py:296-351` 在 `TemporaryDirectory` 写 `in.mp4/out.mp4`，PyAV 元数据校验→ffmpeg transcode→删除 `in.mp4`→SHA-256→`shutil.move` 到 `UPLOADS_PATH` | `subprocess.call` 返回码未检查（`transcoder.py:153-186`）；ffmpeg 缺失可能在组装命令时低层失败，输出损坏则后续元数据/空帧检查才发现；没有 ffmpeg timeout、取消或原子写入协议 |
| upload hash/索引 | 目标名是内容 hash，但没有锁、目标存在策略或数据库事务；返回三元组 `(filepath,file_key,out_video_metadata)`，函数注解仍写四元组 | 同 hash 并发、磁盘满、进程 SIGKILL、move 后索引更新失败都没有补偿/清扫任务；临时目录只覆盖正常 Python 异常退出 |
| poster/preload | `data/loader.py:54-84` 调 ffmpeg 生成 poster 后用 `imagesize.get` 读尺寸；`app.py` 导入时 preload gallery 并构造全局 API | ffmpeg 返回码不检查，poster 缺失会在后续读尺寸处失败；启动阶段失败可能早于 `/healthy` 路由可用 |

### 20A.6 取消、并发、OOM 与进程崩溃边界

1. **锁覆盖 generator 生命周期**：`InferenceAPI.propagate_in_video` 在 `with self.autocast_context(), self.inference_lock:` 内 `yield`（`predictor.py:282-355`）。消费者暂停读取时锁也保持；其他 add/clear/remove/start 调用被阻塞。`cancel_propagate_in_video` 不拿该锁，只把 session 的 bool 设为 true；传播要等 generator 恢复到下一次检查点才返回，不能抢占当前 kernel 或解码。
2. **关闭不是停止**：`close_session` 直接 pop 字典，不调用取消、不等待 active generator、不调用 predictor reset；活动 generator 若仍持有局部 `session`/`inference_state`，仍可能继续计算，只是后续 `__get_session_stats` 不再能通过 session id 查到它。此路径没有“关闭后无任务/线程/tensor”的验证。
3. **取消后状态保留**：取消分支只 `return None`，已写入的 `non_cond_frame_outputs`、cache、memory 和帧不会回滚；下一次传播开始时又把 `session["canceled"]` 设回 false。能否从取消后的部分结果继续，不是源码保证的事务语义。
4. **传播重复调用**：没有请求幂等键；再次调用会重复执行 preflight/传播并覆盖同帧的非 conditioning 输出，输出事件也没有序号/去重字段。错误、取消和客户端断连均没有统一终态对象。
5. **CUDA OOM/MPS crash**：源码没有 catch `torch.cuda.OutOfMemoryError`、MPS 崩溃恢复或子进程隔离。demo 只在 MPS 选择 `offload_video_to_cpu=True` 并警告 MPS preliminary；发生设备级异常时，应用没有重建 predictor、session journal 或显存健康闸门。
6. **进程级崩溃**：OS 会回收进程内存、文件描述符和 GPU context，但不会替应用删除已经写入的临时/上传文件，也不会恢复 `session_states`、`ALL_VIDEOS`、`inference_state` 或 generator 进度；daemon 线程和锁没有应用级崩溃回调。

| 场景 | 当前源码能证明的行为 | 不能声称 |
|---|---|---|
| 非法图像/点/box/mask | 多数在断言/`ValueError`/`NotImplementedError` 处失败；但对象注册或输入字典写入可能发生在前 | 不能声称失败后 state 自动回滚/旧 embedding 保持 |
| 缺权重/错 key/错 config | 构造链同步失败，严格 key 差异抛异常 | 不能声称有校验摘要、重试、备用模型或优雅降级 |
| 缺 CUDA 扩展 | connected-components 后处理捕获异常并告警跳过；核心 mask 推理路径可继续 | 不能声称所有后处理结果不受影响 |
| 视频解码失败 | 同步路径初始化失败；异步路径可能延迟到访问帧时失败 | 不能声称异步线程可取消、坏帧可跳过或状态可恢复 |
| timeout/客户端断连 | 没有内部 deadline；generator `finally` 只日志；取消是合作式 bool | 不能声称 kernel 被中断、锁立即释放、未引用 tensor/临时文件自动清扫 |
| OOM/MPS 进程崩溃 | 依赖 PyTorch/OS 的进程级处置；无应用恢复 | 不能声称 session 连续性、自动重试或 GPU context 健康 |
| 上传 ffmpeg/磁盘失败 | 临时目录覆盖常规异常；ffmpeg 返回码、超时、并发目标和崩溃残留无统一治理 | 不能声称 content hash 已提交即具备原子索引/回滚 |

### 20A.7 第二轮收口结论与验证边界

- **已确认的关键硬边界**：模型是“CPU checkpoint 读取 → strict key 检查 → `.to(device)`”的同步装配；图像 predictor 缓存 embedding；视频 predictor 全量持有/加载帧并用可变 `inference_state` 管理 per-object memory；自动 mask 只对 points/crops 做分批，不是无界流式；demo 的 CUDA autocast、MPS CPU frame offload、全局锁和全局 session map 都是应用层行为。
- **最容易被误判的事实**：`offload_state_to_cpu` 只移动部分输出 tensor；`reset_state` 不清 frame/cache/constants；`close_session` 不等于 predictor close；取消不等于回滚；`max_frame_num_to_track` 不严格等于产出帧数；`points_per_batch` 不限制总候选数；`TemporaryDirectory` 不覆盖 SIGKILL/ffmpeg timeout/同 hash 并发。
- **阻断级崩溃边界**：compile 失败、checkpoint/配置失败、坏视频/全量帧内存峰值、CUDA/MPS OOM 或设备崩溃、活动 generator 断连、上传 ffmpeg 非零退出和进程 SIGKILL 都没有项目级恢复/资源审计闭环。
- **本轮未执行**：没有安装依赖、下载权重、启动服务、创建 fixture、运行图像/视频推理、测量 CUDA/MPS/CPU 显存、注入 OOM/断连/磁盘故障或检查临时目录；上述内容保持 L1 静态证据，不冒充 L2-L4。

## 21. 第三轮：通用底座映射范围与证据边界

本节是第三轮“项目能力 → 通用底座”的裁决，不是对 SAM2 源码的再次建档，也不是对平台生产代码的改造方案。前两轮已经证明：SAM2 的图像/视频分割、视频会话、mask memory 传播、权重装配和 demo 入口都存在于同一仓库，但当前实现把模型、会话和 HTTP 应用放在一个 Python 进程内。本轮只把这些能力放入平台既有的**视觉支持库、视觉模块、运行核心、提供者**四个边界，并明确哪些行为必须被平台契约补齐。

证据等级仍按本档案的 L0-L4 执行：下文带 `源码事实` 的内容来自本项目真实路径；带 `底座裁决` 的内容是平台接入边界；二者不能混写。当前没有安装依赖、下载权重、启动 demo 或运行推理，因此本轮第三轮映射仍只能把项目证据推进到 L1，不能把映射方案写成 L2-L4 已通过。

### 21.1 现有能力命中表

| SAM2 能力/入口 | 项目当前实现证据 | 视觉支持库归属 | 视觉模块归属 | 运行核心归属 | 提供者归属 |
|---|---|---|---|---|---|
| 图像提示式分割 | `sam2/sam2_image_predictor.py:85-129,237-303,337-438`；embedding 缓存后接受点/框/低分辨率 mask | 定义 `视觉分割.图像分割` 契约、输入图像/提示/掩码/评分结构、统一错误 | 编排“上传或图像引用 → 校验 → 一次 embedding → 多次 prompt → 输出” | 请求超时、并发预算、句柄和结果制品释放 | 在隔离进程中加载 `torch`、SAM2 模型、权重和 device，执行 backbone/prompt/mask decoder |
| 自动 mask | `sam2/automatic_mask_generator.py:36-170`；crop、网格点、NMS、稳定性过滤 | 定义 `视觉分割.自动掩码` 与统一 mask record | 选择是否调用自动掩码、归一化结果，不复制网格/NMS 流程 | 作业监督、预算、取消、输出上限 | 复用同一 SAM2 图像 provider；不得另建自动 mask 模型链 |
| 视频会话创建 | `sam2/sam2_video_predictor.py:41-99` 的 `init_state`；会话状态是内存字典 | 定义 `视觉分割.会话创建/关闭/重置`、不透明会话句柄和状态摘要 | 把业务会话命令转换为能力调用；不持有 torch Tensor | 会话租约、所有者、TTL、硬截止、状态机、重启/崩溃标记 | 创建 provider-side state，持有视频帧、feature cache、memory 和 per-object outputs |
| 点/框/掩码交互 | `sam2/sam2_video_predictor.py:161-381`；`add_new_points_or_box`、`add_new_mask` | 定义提示输入的形状、坐标系、object id、覆盖/追加语义和错误码 | 处理业务层 object/frame 请求，调用同一视频会话能力 | 校验幂等键、取消令牌、会话锁/句柄合法性 | 在 provider 内把输入转成 Tensor，执行 `track_step` 和临时输出 |
| mask 传播 | `sam2/sam2_video_predictor.py:479-630`；preflight 后 generator 按帧 yield | 定义 `视觉分割.掩码传播`、帧事件、对象映射、RLE/制品引用、序号和结束事件 | 编排 forward/reverse 范围、流式结果、模块级结果转换 | 流任务监督、背压、deadline、客户端断连、取消升级和子进程回收 | 执行 `MemoryAttention`、`MemoryEncoder`、`track_step`，只返回跨进程可序列化结果 |
| 模型配置与权重 | `sam2/build_sam.py:71-174`；Hydra instantiate + `torch.load(..., weights_only=True)` + strict key 检查 | 定义模型族、配置/权重指纹、兼容性和 provider 能力声明 | 选择已登记的模型 profile，不接收任意 Python 类/路径 | 权重制品锁、校验、缓存引用计数、加载超时和释放 | 只在隔离 provider 进程读取 config/checkpoint，构造并 `.to(device)` |
| GPU/MPS/CPU 设备 | `demo/backend/server/inference/predictor.py:64-92`；CUDA→MPS→CPU，MPS 默认 offload | 定义设备能力、显存预算、精度/降级结果字段 | 选择业务允许的设备策略，不直接读 allocator | 资源预算、租约配额、峰值记录、OOM 后收口和进程级回收 | 真实查询 `torch.cuda`/MPS、设置 autocast/offload，报告实际 device |
| 上传与转码 | `demo/backend/server/data/schema.py:285-351`、`data/loader.py:39-92`；临时目录、PyAV、ffmpeg、SHA-256 后移动 | 复用通用媒体输入/文件制品契约；不把 Flask multipart 当视觉能力 | 把上传文件引用接入图像/视频任务；负责业务格式选择 | 临时目录、原子落盘、磁盘/大小/时长预算、失败清扫 | 在隔离 provider 中使用 PyAV/ffmpeg/pycocotools；ffmpeg 不得从主进程直连 |
| GraphQL、Flask、multipart demo | `demo/backend/server/app.py:29-140`、`data/schema.py`；`/graphql`、`/propagate_in_video` | 不归视觉支持库；仅消费公开能力契约 | 归 demo/项目适配入口，解析请求并调用唯一视觉模块 | 统一网关/任务监督/认证和连接断开治理 | 不接受 GraphQL 直接导入 SAM2；provider 只接收内部协议 |

**命中结论：** 图像与视频不是两个独立视觉内核；它们共享 SAM2 backbone、prompt/mask head 和同一 provider 能力族，视频只额外拥有 session/memory/传播状态。`SAM2AutomaticMaskGenerator` 只能是图像能力的策略，不得升级成第二套模型链。上传、GraphQL、Flask 和 demo 也不是视觉算法层，不得把入口代码复制到视觉支持库。

### 21.2 缺口表与裁决

| 缺口 | SAM2 当前状态 | 第三轮裁决 | 归属/优先级 |
|---|---|---|---|
| 主进程隔离 | `app.py` 导入时构造全局 `InferenceAPI`；`InferenceAPI` 在同进程 import `torch` 并加载 SAM2 | 拒绝把此结构作为平台底座；主进程只运行入口、契约、租约和监督，不加载 `torch`、SAM2、PyAV、CUDA 扩展或大 Tensor | 运行核心 + SAM2 provider，阻断级 |
| 会话状态权威性 | `session_states: Dict[str, Any]` 为进程内全局字典；重启即丢失 | 会话元数据由运行核心持有并带租约；provider state 是从属资源；无 checkpoint 时崩溃后必须返回 `SESSION_LOST`，不得静默重跑 | 运行核心，阻断级 |
| mask 传播治理 | provider generator 逐帧 yield；无 deadline、背压和强取消 | 统一流任务协议：序号、帧范围、结束/取消/失败事件、背压、硬截止；取消先合作、超时后杀 provider 进程组 | 运行核心 + 视觉支持库，阻断级 |
| 模型权重可信装配 | checkpoint 路径由 `MODEL_SIZE` 拼接，严格 key 检查；无平台制品锁/摘要契约 | 权重和 config 必须是不可变、可寻址、带 SHA-256/模型版本/设备兼容声明的制品；provider 只读已登记制品 | 运行核心制品治理 + provider，重要 |
| GPU 显存边界 | 只记录 CUDA allocator 统计；MPS 通过 CPU offload 缓解；无预算/租约回收 | 请求前预留显存/内存预算，provider 报实际峰值；OOM 显式失败并回收 provider，禁止隐藏 CPU fallback | 运行核心监督 + provider，重要 |
| 上传原子性 | TemporaryDirectory 负责常规退出清理，`shutil.move` 后无事务/并发/磁盘满补偿 | 上传必须先写唯一临时目录、校验容器/时长/大小、fsync 后原子落盘；失败/取消/崩溃清理临时和未完成制品 | 视觉模块调用通用文件能力 + 运行核心资源治理 |
| GraphQL/demo 业务校验 | 入口认证 TODO；错误主要由异常表达；`add_mask` 仍调用不存在的 `self.model` | 只保留为项目适配入口；所有输入、权限、会话校验和错误转换在入口/模块完成后走唯一能力调用器；不修成第二入口 | 项目适配层/统一网关，重要 |
| 错误/取消/崩溃契约 | 没有统一稳定错误码；取消只写 bool，`GeneratorExit` 只日志 | 固定错误码、可重试语义、状态终态和证据；provider 崩溃必须由运行核心观察并回收，不能由 GraphQL 自行重启一套模型 | 公共契约 + 运行核心，阻断级 |

**吸收/升级/新建/废弃裁决：**

- **吸收**：SAM2 的四段模型结构、图像 embedding 复用、视频 per-object state、`cond_frame_outputs`/`non_cond_frame_outputs`、preflight 后 memory encoding、forward/reverse propagation、mask 评分和 RLE 输出形状。
- **升级现有底座**：复用平台已有的唯一能力注册/调用器、独立进程监督、进程组回收、租约管理、资源预算、统一结果/事件和证据账本；视觉域只补契约和 provider 声明，不新建一套加载器、任务系统、日志或网关。
- **新建原子能力**：仅在能力目录没有等价 owner 时登记 `视觉分割.图像分割`、`视觉分割.自动掩码`、`视觉分割.视频会话`、`视觉分割.提示`、`视觉分割.掩码传播`、`视觉分割.关闭会话` 等能力；它们共享一个视觉支持库契约族和一个 SAM2 provider 适配面。
- **废弃/隔离**：废弃 demo 的全局 `InferenceAPI`、全局 `session_states`、GraphQL 直调 predictor、主进程加载模型、隐藏 CUDA→CPU fallback 作为平台模式；历史源码保留作参考，不把它们接入正式调用链。
- **待核**：权重制品仓库现有能力是否能表达模型/config 双文件绑定、GPU 显存预算是否支持 MPS/CPU 统一指标、流式任务的背压接口和大 mask 制品格式，必须在平台能力搜索与契约登记后再定，不凭本项目源码假设已有。

## 22. 目标单链路与四层职责

第三轮的唯一正式链路如下；入口可以有 HTTP、GraphQL、CLI 或 Python SDK，但它们只能在最左侧做协议适配，不能各自拥有模型调用逻辑：

```text
Flask/GraphQL/demo/CLI/SDK 入口
  → 统一网关/项目适配层
  → 模块库.视觉分割（校验、编排、结果投影）
  → 唯一能力调用器/能力注册表
  → 支持库.视觉分割（图像/视频/掩码/会话契约）
  → 运行核心（会话租约、任务监督、资源句柄、取消、进程组、证据）
  → SAM2 隔离提供者（独立解释器/进程组/内部 JSONL 或等价协议）
  → torch + SAM2 + config/checkpoint + PyAV/ffmpeg/pycocotools/CUDA/MPS
  → 序列化 mask/事件/制品引用
  → 运行核心收口资源
  → 模块统一结果
  → 原入口响应/流
```

### 22.1 视觉支持库

视觉支持库是**契约 owner**，不是模型包，也不是 HTTP 包。它只定义并注册：

1. `图像输入`、`视频输入`、`提示`、`对象`、`掩码`、`传播事件`、`模型 profile`、`设备报告`和`视觉结果`的稳定结构；
2. `视觉分割.图像分割`、`视觉分割.自动掩码`、`视觉分割.视频会话`、`视觉分割.提示`、`视觉分割.掩码传播`、`视觉分割.会话关闭`等能力的参数、返回、错误码、超时、取消、幂等键和资源释放责任；
3. 坐标系、frame/object/session 关联、mask 尺寸、RLE 或大结果制品引用的边界校验；
4. provider 无关的 `结果/事件` 结构。Tensor、`torch.device`、`inference_state` Python 字典、Flask Request 和 Strawberry 类型均不得穿过此层。

掩码小结果可使用受限 RLE 内联；超过大小阈值必须转为内容寻址制品或分块事件。无论采用哪种编码，能力 id 和结果 schema 只有一个 owner，不能由 GraphQL、demo、provider 各写一套 mask 转换。

### 22.2 视觉模块

视觉模块是**领域流程 owner**，但不是能力 owner。它负责：上传/文件引用与视觉请求的绑定、单图多 prompt 的生命周期、视频会话命令编排、传播方向/范围参数、结果分页/流式投影和业务错误转换。它只能调用视觉支持库公开能力或统一能力调用器，不能：

- `import sam2`、`import torch` 或直连 `build_sam2*`；
- 读取/修改 provider 内的 `inference_state`；
- 自己维护 `session_states`、模型缓存、GPU 锁、重试器或进程池；
- 为 GraphQL、REST、CLI 各复制一份传播循环；
- 把 provider 对象、Tensor 或异常文本泄漏给上层。

图像和视频模块可以有不同的工作流函数，但它们必须共享视觉支持库的 mask、结果、错误和会话契约。自动掩码是图像工作流的策略能力，不建立第二个 backbone 或第二个 provider registry。

### 22.3 运行核心

运行核心是**通用运行治理 owner**，不认识 SAM2 的层名和算法细节，只治理以下通用对象：请求、任务、会话租约、资源句柄、独立进程组、预算、取消令牌、截止时间、事件序号、终态证据和残留检查。它必须：

- 为每个会话分配不可猜测的 `session_handle`、`lease_id`、owner/project scope、创建时间、空闲截止和硬截止；
- 在 provider 启动前预留 CPU/GPU/内存/文件/进程预算，结束时按句柄统一释放；
- 监督 provider 的 stdin/stdout/stderr、PID/进程组、退出码、协议超时、输出上限和心跳；
- 把主动取消、客户端断连、超时、provider 非零退出和 OOM 统一投影为稳定终态；
- 清理 provider 进程组、管道、临时目录、未完成上传、session 引用和任务队列，并读回确认无残留；
- 记录“创建/持有/转移/释放/失败释放/崩溃回收”的证据，但不把算法结果写成运行核心的业务状态。

运行核心可以保存会话元数据和恢复日志；不能伪造 SAM2 的中间 Tensor 可恢复性。若 provider 没有可验证的 checkpoint，崩溃后只能把会话标记为 `SESSION_LOST`，由上层决定重新上传/重新提示，而不是偷偷重跑并声称会话连续。

### 22.4 SAM2 提供者

提供者是唯一可以接触 SAM2 重型依赖的边界，推荐使用独立解释器和独立进程组：

```text
运行核心
  → Popen([隔离解释器, SAM2提供者入口], stdin=PIPE, stdout=PIPE,
          stderr=PIPE, start_new_session=True)
  → 一请求一响应/事件协议（JSONL 或受控二进制帧）
  → provider 内 import torch/sam2/PyAV/pycocotools
  → 权重校验、模型装配、GPU/MPS/CPU 执行
  → 只输出结果/事件/设备报告/错误码
```

provider 必须实现：权重/config 只读装配、实际设备探测、模型/会话状态隔离、图像 embedding、视频 prompt、memory 传播、mask 编码、依赖缺失和 provider 崩溃的明确返回。主进程不得通过 Python import、共享 Tensor、共享 CUDA context 或 provider 全局对象“优化”这条边界。若未来使用长期驻留 provider 进程，必须由运行核心按模型指纹+设备+租约管理引用计数和逐会话隔离；这仍是同一 provider 链，不得另设视觉服务链。

## 23. 会话、mask 传播与资源契约

### 23.1 会话租约状态机

SAM2 当前的 `inference_state` 是 provider 内的可变运行态，不是平台会话契约。平台会话至少包含如下元数据：

```text
创建中 → 活跃 → 传播中 → (活跃 | 取消中 | 失败 | 已完成)
                 │
                 ├→ 超时/租约过期 → 回收中 → 已过期
                 ├→ provider 崩溃 → 回收中 → 崩溃/SESSION_LOST
                 └→ 显式关闭 → 回收中 → 已关闭
```

- **创建**：验证输入制品和模型 profile，申请 lease/预算，启动或复用受监督 provider，成功后才把 session 置为 `活跃`；任何初始化失败都释放预算和 provider 引用。
- **续租**：只有 owner 持有有效 lease token 才能心跳/续租；续租不能绕过硬截止，传播中的 lease 也不能无限延长。
- **使用**：每次 prompt、clear、remove、propagate 都携带 session handle + lease token + request id；重复 request id 必须按能力契约决定幂等或拒绝，不能靠字典覆盖猜语义。
- **关闭**：先阻止新命令，再取消活动任务，排空/关闭 provider-side state，释放视频帧、feature、memory、Tensor、管道和预算，最后从运行核心索引移除；关闭操作本身幂等。
- **过期/崩溃**：标记终态并追加证据，杀死/回收子进程组，删除临时资源；无法恢复的 provider state 不得重新挂回旧 lease。

租约只保护运行资源，不把 session id 当认证凭证；真实网关还需要身份、项目范围和权限。GraphQL 的 context 只能携带已授权的调用者和能力请求，不能直接暴露 provider session 对象。

### 23.2 mask 传播统一事件

建议固定为一条能力 `视觉分割.掩码传播`，而不是 forward、backward、multipart、GraphQL 各有一条算法链。事件至少包含：

```text
{请求id, 会话句柄, lease版本, sequence, frame_index,
 object_ids, masks或制品引用, device, provider版本,
 is_conditioning, 完成/取消/失败标记}
```

provider 内部仍可保持 SAM2 的 `cond_frame_outputs`、`non_cond_frame_outputs`、`cached_features`、`maskmem_features` 和 `obj_ptr`；这些字段不得穿出 provider。模块层只看到规范事件，并根据业务需要投影为 GraphQL payload、multipart chunk 或文件制品。传播 preflight 的“临时输出 → memory encoder → 正式传播”是 provider 内部事务阶段，运行核心只记录任务阶段，不复制一套 memory encoder。

传播取消语义必须分层：

1. 运行核心立即把任务置为 `取消请求`，阻止后续新请求；
2. provider 在安全检查点停止 generator，发送 `取消确认` 或失败事件；
3. 超过取消宽限期时，运行核心对独立进程组执行 TERM→宽限→KILL，回收管道和显存；
4. 若当前帧 kernel 不可抢占，当前帧是否有结果必须由事件序号明确，不得把“客户端断开”伪装成完整传播成功。

## 24. 权重、GPU 显存与上传边界

### 24.1 权重制品

`build_sam2` 当前能严格检查 checkpoint keys，但它不是平台制品治理。正式接入要求：

- `config + checkpoint + 模型族 + provider 版本 + 设备/精度约束`作为一个可寻址模型 profile；
- 下载/导入在能力外部完成，使用 SHA-256、大小、来源、许可证和完整性证据；请求参数只能引用已登记 profile，不能把任意本地路径或 URL 传给 provider；
- provider 启动时重新读取摘要并以只读方式加载，缺键、多键、摘要不符、版本不兼容均返回 `WEIGHT_INVALID`/`MODEL_INCOMPATIBLE`；
- 模型驻留由运行核心按 provider 引用计数治理；最后一个 lease 结束后可回收，回收失败必须有证据；
- Hugging Face/远程下载若作为 provider，仍只能生成/读取同一模型制品，不能在 GraphQL 或模块内暗自下载。

### 24.2 GPU/MPS/CPU 显存

SAM2 源码的 `offload_video_to_cpu`、`offload_state_to_cpu` 和 `torch.cuda.memory_*` 统计可作为 provider 观测字段，但不是资源治理。目标契约如下：

| 阶段 | 必须动作 | 失败语义 |
|---|---|---|
| 预留 | 运行核心按模型 profile、视频尺寸、对象数、传播上限预留预算；provider 报可用 device | 预算不足返回 `RESOURCE_BUDGET_EXCEEDED`，不启动半初始化模型 |
| 装配 | provider 选择明确的 CUDA/MPS/CPU；返回实际 device、精度、offload 策略和模型指纹 | 设备不可用返回 `DEVICE_UNAVAILABLE`；不允许无记录的隐式 fallback |
| 执行 | 采集 allocated/reserved/peak、CPU 内存、帧缓存和输出缓冲；限制对象/帧/输出上限 | OOM 返回 `GPU_OOM` 或 `MEMORY_LIMIT_EXCEEDED`，标记当前任务失败 |
| 收口 | 删除 session state 引用，等待/终止 provider，关闭 pipe，释放预算；必要时由独立进程退出让 OS 回收 CUDA/MPS context | 无法确认释放时隔离并杀 provider，记录 `RESOURCE_CLEANUP_UNCONFIRMED` |

MPS 当前被源码标为 preliminary，不能把 MPS 的“能跑”升级为 CUDA 数值一致性或稳定性保证。CPU fallback 只能是显式策略或重试策略，不能在一次请求中静默换设备而改变成本、延迟和结果证据。

### 24.3 上传/转码/制品

上传不是 GraphQL 自己的文件副作用，也不是 provider 直接接收任意文件名。目标流程：

```text
multipart/GraphQL upload
  → 入口鉴权与请求限额
  → 运行核心分配 upload lease/临时目录
  → provider 或专用媒体 provider 校验容器、stream、尺寸、时长、大小
  → 临时输出 fsync + 摘要
  → 原子移动到内容寻址制品
  → 视觉模块只拿 immutable artifact_ref
  → 会话关闭/租约过期按引用计数清理
```

当前源码的 `TemporaryDirectory` 只能证明普通 Python 异常下的局部清理，不能证明取消、进程崩溃、磁盘满、同 hash 并发和上传索引一致性；这些必须列入 L3/L4，不可用“文件已经 move”代替验收。`GraphQL upload_video` 与 `/propagate_in_video` 必须最终进入同一个视觉模块/能力 id，不得因协议不同再复制一套视频解码、会话或传播逻辑。

## 25. 失败、取消、崩溃和释放矩阵

| 场景 | 统一结果/状态 | 必须释放或保留 | 重试边界 |
|---|---|---|---|
| 非法图像/提示/坐标/对象 | `INVALID_INPUT`，请求失败；会话保持可用或按契约回滚到请求前快照 | 不得留下新 object、临时 prompt 或未绑定 Tensor | 仅修正输入后新 request；不自动重试同一非法请求 |
| 配置/权重缺失、摘要不符 | `MODEL_UNAVAILABLE`/`WEIGHT_INVALID`；会话不进入活跃 | 释放模型加载中 Tensor、文件句柄、预算和 provider | 可在制品修复后重试创建；不能重试已失败传播伪造连续性 |
| provider/torch/PyAV/ffmpeg 依赖不可用 | `PROVIDER_UNAVAILABLE` | 不启动或回收隔离进程；保留错误证据 | 初始化可有界重试；业务传播不得隐藏 fallback |
| 视频坏帧/解码失败 | `MEDIA_DECODE_FAILED`；当前 session 进入失败或可重置 | 清理 frame loader、临时文件和未完成 output；已提交 immutable 制品可保留 | 仅对可证明幂等的读取重试；不得重复写上传制品 |
| 单帧业务异常 | `INFERENCE_FAILED`；是否可继续由 session 状态契约决定 | 清理当前请求临时输出；不得把半写 memory 当正式结果 | 同 request 只在幂等且 provider 状态可证明未变时重试 |
| 传播超时/deadline | `TIMEOUT`，任务终止；session 可标记需要重置 | 取消 generator，关闭/回收 provider，清理流和预算；保留已发序号作为证据 | 不自动从中间帧重放；新传播需要显式 resume/checkpoint 能力 |
| 主动取消/客户端断连 | `CANCELED`；未发出的帧不算成功 | 合作取消，宽限后强杀；释放锁、管道、临时输出和未引用 mask | 取消操作幂等；不可把取消当 provider 成功 |
| GPU OOM/MPS 崩溃 | `GPU_OOM`/`PROVIDER_CRASHED`；session 通常 `SESSION_LOST` | 杀并回收整个 provider 进程组，释放 GPU context/预算；检查无子进程残留 | 可按显式策略新建较小模型/CPU 会话；禁止偷偷续用损坏 state |
| 入口/GraphQL 异常 | 稳定错误响应，不泄漏 traceback/Tensor/路径 | 由运行核心 finally 收口已创建的 task/lease；无任务则无副作用 | 仅安全重试查询/幂等关闭；mutation 必须带 request id |
| 上传取消/磁盘满/进程崩溃 | `UPLOAD_FAILED`；无半成品索引 | 删除临时目录和未完成目标，读回 uploads/制品目录确认 | 只对未提交临时上传重试；已提交内容寻址制品按摘要幂等复用 |
| 会话租约过期/显式关闭 | `LEASE_EXPIRED`/`CLOSED`；拒绝新命令 | 取消任务、释放 state/frame/cache/memory/model 引用，清理 provider | 旧 token 永不复活；必须新建会话 |

当前 SAM2 只对部分正常路径有局部清理：锁的上下文、`TemporaryDirectory`、`reset_state`、`close_session` 字典移除和 generator `finally` 日志。它没有覆盖上述统一矩阵；因此本表是接入验收契约，不是当前源码已通过声明。

## 26. 装配计划与验收契约

### 26.1 装配计划（不改本项目源码）

1. **能力搜索与冻结**：先查询平台能力目录，确认是否已经有通用媒体制品、子进程 provider、任务流、租约、GPU 预算和 RLE/制品能力；记录命中能力 id、契约指纹和占用租约。没有搜索证据不得新建视觉能力。
2. **契约登记**：冻结一组 `视觉分割.*` 能力、统一输入/输出/错误/取消/资源字段，明确图像和视频共享 owner；把 GraphQL、REST、CLI 作为消费者契约，不把它们注册成算法能力。
3. **provider 工作包**：建立一个 SAM2 provider 适配包/独立环境，依赖只放 provider；config/checkpoint 通过模型制品引用；内部协议先支持图像、视频会话、提示、传播、关闭五类动作，不能把 provider Python 类暴露给模块。
4. **视觉模块接线**：模块只做请求编排、格式校验、结果转换和业务事件投影；GraphQL/demo 迁移为项目适配入口，所有入口调用同一模块公开函数。
5. **运行核心接线**：接入 session lease、任务监督、进程组、预算、取消、超时、崩溃回收和证据；逐项验证正常完成、业务失败、主动取消/超时、宿主/子进程崩溃四终态。
6. **分层验收**：先 L2 无权重/fixture 的协议与资源探针，再 L3 小权重图像/短视频真实链路，最后 L4 OOM/超时/断连/killpg/重复请求/同 hash 并发和残留审计；任何一层失败都不能由下一层“看起来跑通”覆盖。

### 26.2 最小消费者契约

| 消费者 | 唯一入口 | 最低验收 |
|---|---|---|
| Python/SDK | `模块库.视觉分割` 的图像/视频函数 | 非法输入稳定失败；成功返回统一 mask/事件；不暴露 Tensor/provider 对象 |
| REST/multipart | 统一网关视觉路由 | 鉴权、request id、背压、断连取消、流结束事件和 session lease 全可观测 |
| GraphQL/demo | 项目适配层 → 同一视觉模块 | upload/start/prompt/propagate/close 都走同一能力 id；GraphQL 只做 schema 映射 |
| 任务/后台作业 | 运行核心任务入口 | 超时/取消/崩溃可回收；重新读取任务状态能得到终态和证据 |

### 26.3 验收命令和当前状态

本轮只允许修改本项目根 `ARCHITECTURE.md`，没有安装依赖、下载权重、启动服务或修改源码；因此当前真实验证仍为：

```text
L0：已完成。目标文件、关键入口、配置、provider 依赖和 demo 路由存在性已核对。
L1：已完成。已根据 build_sam、image/video predictor、demo predictor/app/schema 解释真实调用链与失败边界。
L2：未完成。本轮没有启动隔离 provider，也没有运行无权重协议/资源探针。
L3：未完成。没有真实 checkpoint、短图/短视频、CUDA/MPS/CPU 结果与资源读回。
L4：未完成。没有真实超时、取消、断连、OOM、SIGKILL、重启、同 hash 并发和残留审计。
```

若后续执行本轮映射验收，命令必须逐项记录退出码、测试数、设备、权重摘要和清理读回结果，至少包括：

```bash
# 仅示意；依赖、权重和 provider 隔离环境准备完成后才能执行
python -m unittest <视觉支持库定向契约测试>
python <隔离provider协议探针> --无权重fixture
python <真实图像/短视频冒烟> --model-profile <已登记profile>
python <故障注入> --timeout --cancel --disconnect --provider-crash
```

这些命令在当前仓库没有现成测试入口，不能把 README 示例、历史 benchmark、`/healthy` 文本、静态导入或子代理回执算作通过。

## 27. 不形成第二视觉链路的强制规则

1. **唯一能力 id**：同一原子能力只有一个 `视觉分割.*` id、一个契约 owner、一个注册入口；GraphQL/REST/CLI 的动作名只能在入口归一化，不能各自注册。
2. **唯一模型链**：图像、视频、自动 mask 共享 SAM2 provider 和模型制品；自动 mask 的 crop/NMS 是策略，不得新建第二模型加载器。
3. **唯一会话 owner**：session lease、状态终态和资源释放由运行核心治理；模块和 provider 不得各自维护全局 session map。
4. **唯一重型边界**：torch、SAM2、PyAV、ffmpeg、pycocotools、CUDA/MPS 只在同一受管 provider/其明确依赖环境内出现；主进程和入口不做隐式直连。
5. **唯一流协议**：图像结果、视频传播、multipart 和 GraphQL 都从统一视觉结果/事件转换；不得在每个协议里重新实现 mask threshold、RLE、对象映射或传播循环。
6. **唯一失败治理**：错误码、可重试、取消、超时、崩溃和释放由公共契约+运行核心决定；provider 不能吞异常，入口不能把异常文本当稳定契约。
7. **唯一资源证据**：权重、显存、帧、memory、临时上传、管道、线程和进程的创建/释放必须有同一条可审计链；“删除 Python 引用”不等于显存/子进程已释放。
8. **禁止旁路**：正式模块不得 `from sam2...`；demo 不得直接构造 `InferenceAPI` 作为平台全局单例；任何兼容旧 API 的别名只能在唯一适配入口归一化，不能复制第二套视觉内核。

**第三轮最终裁决：** SAM2 值得作为视觉 provider 的算法实现和模型权重/设备适配参考，图像与视频能力吸收到同一视觉支持库/模块契约族；会话租约、资源释放、失败/取消/崩溃和主进程隔离必须由通用运行核心补齐；Flask/GraphQL/demo 只保留为入口适配，不进入视觉底座。当前项目本身仍停在 L0-L1，第三轮映射是可装配输入而不是生产就绪证明。
