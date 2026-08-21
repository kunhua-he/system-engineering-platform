# OpenCLIP 架构建档

## 0. 顶部流程图

```text
图像/音频/文本输入
  → tokenizer/processor 与 batch
  → image/text/audio encoder
  → projection + normalize
  → 对比 logits / embedding / zero-shot 结果
  → 训练损失、检索或下游 Provider 调用
```

> 本文是对本地源码归档的首轮全量架构记录，不是生产接入指南，也不替代上游 README、模型配置和测试。
>
> 目标项目：`/Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/40_embedding_retrieval/open_clip`
>
> 项目名：`open_clip`；Python 包名：`open_clip_torch`；上游：`https://github.com/mlfoundations/open_clip`
>
> 记录范围：README、`pyproject.toml`、依赖、入口、模型/任务/损失/数据流、API、测试、已有细探、Git 版本。源码只读；本次只修改本文件，未安装依赖、启动服务、构建、生成权重或修改源码/测试/配置。
>
> **旧细探吸收声明**：`细探-open_clip.md` 已完整读取并逐条对照当前源码；其中的定位、CLIP/SigLIP/NaFlex/训练栈、图文嵌入/零样本分类、MIT 与 PyTorch/GPU/权重边界均已吸收到本文相应章节。旧细探按要求保留，不是第二个权威架构源；后续架构维护只更新本文，旧文件仅作历史留痕。

## 1. 项目定位

OpenCLIP 是 OpenAI CLIP 的开源复现及扩展，核心是把图像与文本（以及扩展后的音频与文本）映射到可比较的嵌入空间，用于图文/音文检索、零样本分类、对比学习训练和部分生成式图像/音频描述。

本地 `main` 代码已经不只是传统的 CLIP 推理库：

- **标准 CLIP**：图像塔 + 文本塔，归一化嵌入，点积得到相似度/Logits。
- **SigLIP/SigLIP2**：使用 sigmoid 对比损失，支持分布式邻居交换与 chunked loss。
- **CoCa / MaMMUT**：图文对比 + 自回归 caption；MaMMUT 复用文本解码器进行双向对比和因果 caption 两种路径。
- **CLAP**：音频塔 + 文本塔的对比学习与音频零样本分类。
- **NaFlex**：可变图像分辨率/patch 数、可变音频时长、token budget batching、长度分桶。
- **GenLIP / GenLAP**：把图像/音频前缀和文本拼接成 prefix-LM，使用 MRoPE、门控注意力、SwiGLU 和内存受限的 fused linear cross-entropy 做生成式预训练。
- **现代文本塔**：RoPE、SwiGLU/ReLU²、RMSNorm、可变长度文本、HF/ModernBERT 文本塔等。

README 明确警告：`main` 的训练栈是 post-refactor 版本；若需要旧的 release-stable 训练 API，应使用 `v3` 分支或 3.x PyPI。推理 API 仍以兼容为目标，但训练脚本和下游集成必须按新任务层、dict batch 与新 CLI 复核。

## 2. 版本与归档状态

| 项目 | 本地事实 |
|---|---|
| 当前分支 | `main` |
| 本地 HEAD | `602d4af74f86df6f2ff81ba0f0a847b0b70ad2e5` |
| 本地 HEAD 提交 | `Fix for new tiktoken config fields, robustness to tiktoken configs with vocab gaps (100 & 200).` |
| 本地 HEAD 时间 | `2026-08-10 14:11:02 -0700` |
| 上游远端 | `https://github.com/mlfoundations/open_clip.git` |
| 远端 `origin/main` | `602d4af74f86df6f2ff81ba0f0a847b0b70ad2e5`（本轮 fetch 后与本地 HEAD 相同） |
| 新鲜度判断 | 本轮已核对远程 SHA 与本地一致；当前事实以该 checkout 为准 |
| 工作区 | 已有未跟踪 `细探-open_clip.md`；本次不改、不删除该文件 |

本轮不通过 MCP 或代理读取外部快照；版本差异以 Git fetch/ls-remote 结果为准。

## 3. 技术栈与依赖

### 3.1 包与构建

- Python：`>=3.9`。
- 构建：`pdm-backend`，`pyproject.toml` 使用 `package-dir = "src"`。
- 包含：`src/open_clip`、`src/open_clip_train`。
- 版本来源：`src/open_clip/version.py`，由 PDM 动态读取。
- 许可证：MIT；部分 modeling/tokenizer 代码改编自 OpenAI CLIP。
- 测试配置：`pyproject.toml` 的 `testpaths = ['tests']`，另有 `pytest.ini`。

### 3.2 核心依赖

| 分类 | 依赖/用途 |
|---|---|
| 张量与视觉 | `torch>=2.6`、`torchvision`、`timm>=1.0.17` |
| 文本与清洗 | `regex`、`ftfy`；可选 `transformers[sentencepiece]`、`tiktoken` |
| 权重与发布 | `huggingface-hub`、`safetensors`、`tqdm` |
| 训练数据 | `webdataset>=0.2.5,<=0.2.86`、`pandas`、`fsspec`、`braceexpand` |
| 音频 | `torchaudio`、`torchlibrosa`、`openai-whisper`、`datasets[audio]` |
| 训练记录/加速 | 可选 `wandb`、`trackio`、TensorBoard、FSDP2、`torch.compile`；int8 路径另需 `bitsandbytes`/`triton` |
| 测试 | `pytest>=9.0.3`、`pytest-split`、`requests` |

依赖的最低 PyTorch 版本与 FSDP2、`torch.compile`、`torch.load(weights_only=True)` 约束相关；不能按旧版 `torch>=2.0` 的经验直接替换。

## 4. 目录与职责地图

```text
open_clip/
├── README.md                         # 定位、API、训练/评估/部署示例与 breaking changes
├── pyproject.toml                    # 包、依赖、构建、测试配置
├── requirements*.txt                 # 核心/训练/测试依赖拆分
├── LICENSE / CITATION.cff / HISTORY.md
├── docs/                             # 预训练模型、结果、profile、教程与图表
├── scripts/                          # CLAP/GenLIP/零样本/转换/预训练脚本
├── tutorials/                        # int8 教程 notebook
├── tests/                            # 53 个主要测试文件，覆盖模型/任务/数据/训练/转换
├── src/
│   ├── open_clip/
│   │   ├── __init__.py               # 顶层公共 API 汇总
│   │   ├── factory.py                # 模型/transform/tokenizer/task/loss 工厂
│   │   ├── model.py                  # CLIP、CustomTextCLIP、视觉/文本配置与塔构造
│   │   ├── transformer.py             # Vision/Text/Modern/Multimodal Transformer 组件
│   │   ├── modified_resnet.py         # ResNet 视觉塔
│   │   ├── timm_model.py              # timm 视觉骨干适配
│   │   ├── hf_model.py                # Hugging Face 文本塔适配
│   │   ├── coca_model.py              # CoCa 图像+文本+多模态解码器
│   │   ├── mammut_model.py            # MaMMUT 图文多模态模型
│   │   ├── clap_model.py              # CLAP 音频+文本模型
│   │   ├── naflex_genlip_model.py     # GenLIP prefix-LM 图像生成模型
│   │   ├── naflex_genlap_model.py     # GenLAP prefix-LM 音频生成模型
│   │   ├── audio/                     # 音频配置、HTSAT、Whisper、mel、NaFlex audio tower
│   │   ├── model_configs/*.json       # 模型家族的结构配置，约 190 个 JSON
│   │   ├── pretrained.py              # 预训练 tag、URL/HF Hub、本地权重、校验/下载
│   │   ├── tokenizer.py               # Simple/HF/SigLip/TikToken tokenizer
│   │   ├── transform.py               # 图像预处理、增强、NaFlex transform factory
│   │   ├── naflex_config.py            # NaFlex 数据预算/patch/seq-len 不可变配置
│   │   ├── loss.py                    # CLIP/SigLIP/CoCa/Distill/生成式损失与 fused CE
│   │   ├── task/                      # TrainingTask 及 CLIP/SigLIP/CoCa/CLAP/Gen/Distill 任务
│   │   ├── generation.py              # CoCa/MaMMUT 生成通用逻辑
│   │   ├── zero_shot_classifier.py     # 零样本分类器构建
│   │   ├── convert.py / naflex_convert.py # checkpoint/布局转换
│   │   └── push_to_hf_hub.py           # HF Hub 发布
│   ├── open_clip_train/
│       ├── main.py                    # 新任务训练/评估主入口
│       ├── train.py                   # TrainState、epoch、eval、检索指标与日志
│       ├── data.py                    # 图像 WebDataset/CSV/合成数据与 dict batch
│       ├── audio_data.py               # 音频 WebDataset/合成数据与 NaFlex audio
│       ├── naflex_data.py              # 长度分桶、调度、patchify、可变文本与 batch
│       ├── params.py                  # CLI 参数解析
│       ├── distributed.py              # DDP、FSDP2、rank/device、对象广播
│       ├── optim.py / scheduler.py     # 优化器、weight decay、layer decay、LR 调度
│       ├── metrics.py / zero_shot.py   # 检索指标、ImageNet 零样本
│       ├── audio_zero_shot.py          # Hugging Face 音频零样本
│       ├── checkpoint/file_utils.py    # checkpoint、DCP、S3/fsspec 远程同步
│       └── legacy_*.py                 # 旧训练循环和 decode-first 数据兼容层
└── 细探-open_clip.md                   # 本地已有的中文细探，保留为辅助材料
```

目录核实结果（当前核对现场只读计数）：`src/open_clip/model_configs` 有 190 个 JSON；仓库共有 122 个 Python（其中 `src/` 70 个、`tests/` 47 个、`scripts/` 5 个）；非 `.git` 文件 376 个、共 15,434,694 bytes（含模型配置、图片、数据/教程等归档资源）。

## 5. 核心运行链路

### 5.1 推理与检索

```text
调用方
  → open_clip.create_model_and_transforms(model_name, pretrained, ...)
  → factory.py 读取内置 model_configs / hf-hub:/local-dir: / pretrained.py
  → model.py 或 coca_model.py / mammut_model.py / clap_model.py 构造模型
  → transform.py 生成图像变换；tokenizer.py 生成文本 token
  → model.encode_image / encode_text（CLAP 为 encode_audio）
  → 可选 L2 normalize
  → 点积 × exp(logit_scale) (+ logit_bias)
  → 检索分数、零样本分类或下游嵌入
```

标准 CLIP 的 `CLIP.forward()` 返回图像特征、文本特征和 `logit_scale`；`output_dict=True` 时返回命名字典。`CustomTextCLIP` 将文本塔作为 `self.text` 单独持有，便于现代/HF/可变文本配置。

### 5.2 新训练入口

```text
python -m open_clip_train.main
  → params.parse_args
  → distributed.init_distributed_device
  → factory.create_model_and_transforms
  → factory.create_task
       → 构造并绑定 TrainingTask 子类（模型 + loss）
  → 可选 torch.compile / DDP / FSDP2 / EMA
  → get_tokenizer + get_data / get_wds_audio_dataset
  → create_optimizer + scheduler
  → TrainState
  → train_one_epoch
       → task.prepare_batch
       → task(batch) -> (losses, report)
       → backward / grad accumulation / optimizer.step
       → logit_scale clamp、计数器、日志
  → evaluate
       → paired features + get_clip_metrics
       → ImageNet/audio zero-shot
       → checkpoint / results.jsonl / remote sync
```

训练栈的关键边界是 `TrainingTask`：`TrainingTask.forward()` 统一 dict、关键字和旧位置参数兼容；具体 batch key 与 loss 由子类负责。`TrainingTask.state_dict()` 不等同于普通 `nn.Module.state_dict()`，包含 `state_dict` 和可选 `state_dict_ema`，checkpoint 必须走 task 的保存/加载辅助函数。

### 5.3 数据链路

- 图像：`open_clip_train.data.get_data()` 按 `dataset_type` 选择 `webdataset`、`csv`、`synthetic`；普通输出为 `{"image": ..., "text": ...}`。
- 音频：`audio_data.py` 从 tar 中筛选音频和 caption，使用 `torchaudio` 解码，普通 CLAP 输出 `{"audio": ..., "text": ...}`。
- WebDataset 新链路把 `tokenize → length bucketing → decode → transform` 排列，分桶时保存原始压缩数据，降低 worker 内存；旧的 decode-first 路径固定在 `legacy_data.py`。
- NaFlex：`NaFlexDataConfig` 定义 patch sizes、seq lens、概率、token budget、batch divisor 和 eval 配置；`NaFlexBatchScheduler` 生成确定性 schedule，`LengthBucketer` 以 caption/audio token 长度排序，`NaFlexBatcher` 负责 decode、transform、patchify、padding/collate。
- 可变文本：`collate_variable_text` 返回 `text` 与 `text_valid`；`text_pad_multiple` 限制 `torch.compile` 的文本形状数量，`text_pad_cap` 防止超过 tokenizer context。

## 6. 模型与任务契约

| 模型/任务 | 主要类/入口 | 输入 batch | 目标/输出 |
|---|---|---|---|
| CLIP | `CLIP`, `CLIPTask` | `image`, `text` | `image_features`, `text_features`, 对比损失 |
| Custom/HF/Modern text | `CustomTextCLIP`, `_build_text_tower` | `image`, `text` | 与 CLIP 契约相同，文本塔可变/双向/现代化 |
| SigLIP | `SigLIPTask`, `SigLipLoss` | `image`, `text` | sigmoid loss；支持 `bidir/shift/reduce/gather` 分布式实现 |
| CoCa | `CoCa`, `CoCaTask`, `CoCaLoss` | `image`, `text`, 可选 `text_valid` | 对比 + caption CE；任务层生成右移 labels 并把 padding 设为 `-100` |
| MaMMUT | `MaMMUT`, `CoCaTask` | `image`, `text`, 可选 `text_valid` | 双向对比 pass + 因果 cross-attention caption pass |
| CLAP | `CLAP`, `CLAPTask` | `audio`, `text` | 音频-文本对比与音频零样本 |
| NaFlex CLIP/CLAP | NaFlex towers + `NaFlexDataConfig` | 嵌套 patch dict + text | variable aspect/duration，按 token budget 分 batch |
| GenLIP | `NaFlexGenLip`, `GenLipTask` | `image` patch dict、`text`, `text_valid` | 仅文本 token 自回归 CE；图像 patch/pad 为 ignore |
| GenLAP | `NaFlexGenLap`, `GenLapTask` | `audio` patch dict、`text`, `text_valid` | GenLIP 同一目标，前缀改为 NaFlex 音频 |
| Distill | `DistillCLIPTask`, `DistillClipLoss` | student + teacher feature 路径 | 对比损失 + teacher/student 蒸馏损失 |

### 6.1 文本有效性与 padding

`SimpleTokenizer` 用 0 填充，但 0 也是真实词表 token，因此不能单纯用 `text != 0` 推断有效位置；其 `output_mask=True` 通过长度生成精确 mask。`HFTokenizer` 强制右 padding，并保留底层 tokenizer 的 `pad_token_id`；无保留 pad 的 tokenizer 不可安全用于 variable text。`TikTokenTokenizer` 把 EOS/PAD/BOS 放在基础 vocab 之上，适配 GenLIP/GenLAP。

CoCa/MaMMUT 的 `text_valid` 由 task 传入文本塔，caption labels 在 `CoCaTask._caption_labels()` 中右移并把无效位置设为 `-100`。不要把 CoCa 的 autoregressive label shift 假定在 `coca_model.py` 内完成。

### 6.2 生成式 prefix-LM

`naflex_genlip_model.py` 的核心序列是 `[valid media patches ; valid text ; PAD]`（普通 block layout 或 `pack_prefix=True` 的 compact layout）。媒体 token 之间双向注意力，文本 token 因果注意力，文本可看媒体，媒体不可看文本；`build_prefix_lm_mask`/`build_packed_prefix_lm_mask` 显式构造 `(B, 1, S, S)` bool mask，并强制对角线可见以避免全 masked query。位置编码使用三轴 MRoPE；attention 使用 SDPA，生成损失使用 `fused_linear_cross_entropy` 分块计算，避免物化完整 `[B, L, vocab]` logits。

## 7. 公共 API 与入口

### 7.1 顶层 Python API（`src/open_clip/__init__.py`）

主要导出：

- 模型工厂：`create_model`、`create_model_and_transforms`、`create_model_from_pretrained`。
- 配置/权重：`list_models`、`add_model_config`、`get_model_config`、`load_checkpoint`。
- tokenizer/transform：`get_tokenizer`、`tokenize`、`decode`、`image_transform`。
- 模型类：`CLIP`、`CustomTextCLIP`、`CoCa`、`MaMMUT`、`CLAP`、`NaFlexGenLip`、`NaFlexGenLap`。
- 任务：`TrainingTask`、`CLIPTask`、`SigLIPTask`、`CoCaTask`、`GenLipTask`、`GenLapTask`、`DistillCLIPTask`。
- 损失/零样本：`ClipLoss`、`DistillClipLoss`、`CoCaLoss`、`GenLipLoss`、`build_zero_shot_classifier`。
- 预训练：`list_pretrained`、`get_pretrained_cfg`、`download_pretrained`、`push_to_hf_hub`。

README 标注的 breaking API：顶层不再提供 `trace_model`、`load_openai_model`、`list_openai_models`、`build_model_from_openai_state_dict`；OpenAI 权重改由标准 factory/pretrained 路径通过 HF Hub 加载。调用 CoCa/MaMMUT 的 `encode_text`/`forward` 时，`text_valid` 插入到旧的位置参数之前，旧调用应改用关键字参数。

### 7.2 CLI 入口

- 新训练/评估：`python -m open_clip_train.main`。
- 旧兼容训练：`python -m open_clip_train.legacy_main`；不提供新 task/FSDP2/EMA/CLAP/NaFlex/length bucketing/compile 全套能力。
- 多 GPU：README 使用 `torchrun ... -m open_clip_train.main`。
- HF Hub 发布：`python -m open_clip.push_to_hf_hub ...`。
- 脚本入口：`scripts/` 中有 CLAP、GenLIP、零样本和权重/patch layout 转换脚本。

## 8. 模型配置与预训练权重

`src/open_clip/model_configs` 是结构配置边界，`pretrained.py` 是模型名→tag→URL/HF Hub/预处理参数的注册表。当前配置家族包括标准 `RN*`/`ViT*`、`convnext_*`、`ViTamin-*`、`EVA*`、`PE-Core-*`、`roberta-*`、`nllb-*`、`mt5-*`、`coca*`、`mammut*`、`moderntext-*`、`naflex*`、`CLAP-*` 等。

权重解析支持：

1. 内置模型配置与预训练 tag；
2. `hf-hub:`/本地目录配置；
3. 本地 checkpoint 路径；
4. URL 下载到 cache；
5. HF Hub 下载，优先尝试 safetensors 替代文件；
6. OpenCLIP/OpenAI 预处理 mean/std/interpolation/resize_mode 等元数据。

URL 下载会对部分文件名执行 SHA256 前缀校验；HF Hub 依赖必须存在。预训练权重、数据集和 GPU 是运行时外部资源，不随本仓库源码归档提供。

## 9. 测试与验证覆盖

测试按职责覆盖：

- 推理/工厂：`test_inference*.py`、`test_factory_task.py`、`test_eval_task.py`、`test_download_pretrained.py`。
- 损失/检索：`test_loss.py`、`test_siglip_chunked_loss.py`、`test_fused_caption_loss.py`、`test_retrieval_metrics.py`。
- 任务/训练：`test_task_base_unit.py`、`test_task_specific_unit.py`、`test_task_compile.py`、`test_task_checkpoint.py`、`test_task_fsdp_unit.py`、`test_grad_accum.py`、`test_training_simple.py`。
- 文本/生成：`test_pad_id.py`、`test_context_masking.py`、`test_modern_text.py`、`test_coca2.py`、`test_mammut.py`。
- NaFlex：`test_naflex*.py`、`test_naflex_config.py`、`test_naflex_timm_conversion.py`、`test_wds.py`。
- 音频：`test_audio_*.py`、`test_clap_task.py`、`test_naflexclap.py`。
- 数据：`test_data_csv.py`、`test_legacy_data.py`、`test_num_shards.py`。
- 优化/参数：`test_optim_layer_decay.py`、`test_params.py`。
- 零样本：`test_zero_shot_eval.py`、`test_audio_zero_shot.py`。

测试体现出的重要契约包括：dict batch、嵌套 NaFlex patch dict、pad id 与 `text_valid`、CoCa/Gen fused loss、梯度累积等价性、FSDP scalar reshape/checkpoint、compile train/eval forward、chunked retrieval 与 full matrix 一致性。README 建议用 `python -m pytest -x -s -v tests -k "training"` 做定向运行，并用 `make test` 跑项目测试；本次按只读建档范围未安装依赖、未运行测试。

## 10. 关键架构风险与边界

1. **分支新鲜度风险**：本地 HEAD 落后于远端 `main` 的提交摘要；必须在复用前核对上游变更，尤其是 tiktoken、配置字段、NaFlex 和训练 CLI。
2. **训练 API 迁移风险**：旧代码若直接调用 `train_one_epoch(model, loss, ...)` 或假设 tuple batch，会与新 `TrainingTask`/dict batch 契约冲突；需要明确选择新入口或 legacy shim。
3. **资源风险**：PyTorch、timm、GPU、分布式通信、模型权重和大型 WebDataset 是硬运行条件；CPU 上只适合小型单测/形状探针，不代表训练可用。
4. **NaFlex 依赖风险**：NaFlex 依赖 recent timm 的数据支持和 patchify；未安装或版本不匹配时应由 `require_naflex()` 明确失败，不能静默退化。
5. **padding 语义风险**：不同 tokenizer 的 `pad_id`/`eos_id`/`bos_id` 不能猜；generative 配置必须经过 factory/tokenizer 校验，否则可能把真实 token 当 padding 或错误 pooling。
6. **生成显存风险**：外部 logits loss 会物化完整词表 logits；大词表训练应使用 fused loss 路径。`CoCaTask` 的 fused caption loss 不支持 `--accum-freq > 1`，代码会明确拒绝。
7. **分布式组合风险**：FSDP2、DDP、compile、gradient checkpointing 有严格顺序和互斥边界；`TrainingTask.prepare_fsdp()` 负责 scalar reshape、block sharding、forward method 注册及 checkpoint shape reconciliation。
8. **checkpoint 兼容风险**：task checkpoint 不是普通 flat state dict；FSDP 的 0-D/1-D `logit_scale`/`logit_bias` 形状需要专用 reconcile。自定义 optimizer 若包含未 allowlist 的 pickle 类型，要按 README 注册 safe globals。
9. **外部文件安全边界**：权重、图像、音频、tar、HF Hub/S3 都是外部输入；远程同步和下载路径不能视为纯内存函数，生产封装应另做超时、缓存、校验和权限控制。
10. **远端/本地文档漂移**：`细探-open_clip.md` 是辅助分析，不应覆盖源码事实；README 中的模型列表、CLI 和 breaking changes 需要随上游版本重新核对。

## 11. 可复用架构结论

- 将 **模型构造、权重解析、预处理、tokenizer、训练 task、数据 loader、loss、评估** 分层，边界清楚，适合被下游以“能力/契约”方式复用，不宜整库复制。
- `TrainingTask` 是值得提取的训练编排模式：task 统一模型+目标函数+batch contract+分布式/compile/checkpoint 适配，避免主循环知道每种模型的细节。
- `text_valid` 与 `patch_valid` 是多模态变长输入的关键显式契约；不要用填充值反推有效性，除非 tokenizer 明确保证 pad id 不与真实 token 冲突。
- NaFlex 的 **预算→确定性 schedule→长度分桶→按需 decode/patchify→嵌套 dict collate** 是高吞吐变长数据的可复用模式，但强依赖 timm/PyTorch 版本和 GPU 预算。
- fused cross-entropy 的原则是：模型只提供未加权的 loss components，任务/损失模块负责权重组合；分块和 checkpointing 控制峰值显存。
- 预训练注册表把模型结构、权重来源、预处理参数绑在一起，能降低“模型加载成功但 preprocessing 错误”的风险；下游接入时必须保留这组元数据。
- 这些结论是参考模式，不等于可直接复制到其他生产平台；接入前应做独立依赖隔离、权重许可、显存/吞吐测量和输入安全审计。

## 12. 首轮结论

OpenCLIP 当前本地归档是一个以 PyTorch 为核心、覆盖图文/音文对比、多模型族、生成式多模态和大规模训练的研究型库。其稳定可复用核心是：`factory.py` 的构造与权重边界、`model.py`/各模型族的编码契约、`tokenizer.py`/`transform.py` 的输入契约、`TrainingTask` 的任务编排、`loss.py` 的分布式/内存高效目标函数以及 `open_clip_train` 的数据-训练-评估闭环。

首轮建档不判定本地版本可直接生产，也不把 README 的成功示例当作当前环境已验证。后续如要实际接入，应先在独立环境固定本地/远端提交、PyTorch/timm/transformers 版本和权重来源，再选择单一模型家族做小样本 CPU/GPU 形状测试、检索指标测试和 checkpoint 往返测试；若涉及训练，再独立验证 DDP/FSDP2/compile/NaFlex 组合。

## 13. 契约表：公开入口、输入输出与失败语义

下表只记录当前源码中能定位到实现的契约；README 示例、注释和历史细探不能替代实现证据。

| 契约入口 | 输入与前置条件 | 成功输出 | 失败/重试/超时/取消/幂等语义 | 证据 |
|---|---|---|---|---|
| `open_clip.create_model` | `model_name` 为内置名或 `hf-hub:`/`local-dir:`；可传 `pretrained`、精度、设备及塔覆盖 | 已实例化并迁移到目标设备/精度的模型；可选完整或塔权重 | 配置/路径/未知 tag 抛 `FileNotFoundError`/`ValueError`/`RuntimeError`；HF 配置失败抛错，HF 默认权重下载失败会先警告并允许仅配置建模；无内建调用超时/取消/幂等键 | `src/open_clip/factory.py:322-763` |
| `open_clip.create_model_and_transforms` | 同 `create_model`，另含图像/音频增强配置 | `(model, preprocess_train, preprocess_val)`；NaFlex 验证 transform 是工厂 | 模型成功而预处理工厂构建失败仍抛错；下载/构造无超时/取消控制 | `factory.py:1188-1356` |
| `open_clip.create_model_from_pretrained` | 需要可解析的模型及预训练来源 | 模型或 `(模型, preprocess)`；内部要求 `require_pretrained=True` | 权重未加载抛 `RuntimeError`；没有请求级超时/取消 | `factory.py:1359-1476` |
| `get_tokenizer` | 内置、HF Hub 或本地目录模型标识；生成/变长文本需一致的 special tokens | `SimpleTokenizer`/`SigLipTokenizer`/`HFTokenizer`/`TikTokenTokenizer` | HF tokenizer 配置读取失败、本地配置缺失、`eos_id`/`pad_id` 漂移、变长文本无 reserved pad 均 fail-fast；HF schema 配置失败时 tokenizer 有 fallback，但生成语义仍需复核 | `factory.py:833-983` |
| `TrainingTask.forward`/`training_forward` | dict batch，或按 `data_keys` 传位置参数；训练态须有 loss | 训练返回 `(losses, report)`；评估返回模型/生成输出 | 未知 task/损失或不兼容 batch 抛异常；`torch.compile` 只包装 forward callable，取消依赖调用方/进程；无内建请求超时/幂等键 | `task/base_task.py:37-157,478-503`；`task/clip_task.py:41-50` |
| CLIP/SigLIP task | `{"image", "text"}`；SigLIP 由 loss 处理分布式策略 | `image_features`、`text_features`、`logit_scale`，可带 `logit_bias`；训练 `loss` | `args.siglip` 与模型类型组合由 factory dispatch；损失断言/参数错误抛异常；不是远程服务，取消只能由训练宿主停止 | `task/image_text_task.py:21-101`；`task/clip_task.py:9-50`；`task/siglip_task.py:8-44` |
| CoCa/MaMMUT task | `image,text`，生成训练可选/要求 `text_valid`；caption 目标右移 | 对比特征 + caption logits，或 fused `caption_loss_ce`/`caption_loss_z` | `text_valid` 优先；否则以 `pad_id` 推导，SimpleTokenizer 的 0 语义有历史陷阱；fused caption loss 与 `accum_freq>1` 明确 `NotImplementedError` | `task/coca_task.py:10-152` |
| GenLIP/GenLAP task | `image`/`audio` NaFlex patch dict + `text`/`text_valid` | 仅自回归 caption loss；fused 路径不物化完整词表 logits | z-loss 配置不一致抛 `ValueError`；external loss 路径显式物化 `[B,S,V]` logits，不能假定可扩展；无远程超时/取消 | `task/genlip_task.py:17-164`；`task/genlap_task.py:15-45` |
| `get_data` | `dataset_type` 为 `webdataset`/`webdataset-audio`/`csv`/`synthetic` 等，且路径/样本数/NaFlex config 满足约束 | `dict[str, DataInfo]`，dataloader 附 `num_batches/num_samples` | 未知类型、缺数据长度、NaFlex 缺 timm/工厂、shard 不足、pad cap 超限抛错；WebDataset 解码坏样本可按 handler 跳过并补齐，连续失败超过上限抛错 | `open_clip_train/data.py:746-1009,1012-1121,1192-1262`；`naflex_data.py:743-959` |
| `save_checkpoint`/`load_checkpoint` | task、optimizer；FSDP 下所有 rank 必须集体调用 | 单 `.pt` 或 DCP 分片目录；保存 epoch、optimizer、EMA、scaler、counters | 损坏/不兼容 checkpoint 由 `torch.load`/模型加载抛错；没有校验和/临时文件原子写保障（最新单文件另有 `tmp.pt`→`os.replace`）；取消/崩溃由训练外层决定 | `task/checkpoint.py:56-216`；`open_clip_train/main.py:683-767` |
| 预训练下载 | URL/HF repo、cache dir；URL 可能带 SHA256 前缀 | cache 中权重文件路径 | 已有文件可复用；URL 文件做前缀 SHA256 检查，失败重下/最终抛错；`urllib.request.urlopen` 未设置 timeout；中断下载可能留下部分目标文件，源码无事务临时名/清理 | `pretrained.py:818-861,885-954` |

**资源所有权总原则**：调用方拥有模型、dataloader、optimizer、logger 与 checkpoint 目录；任务只持有模型/EMA/loss；数据管线拥有 worker、共享 epoch、预取线程和队列；远程 sync 子进程由 `main` 创建并在正常结束时 `terminate()`，异常/宿主崩溃清理没有统一 finally 保障。

## 14. 真实对接调用链（函数级）

### 14.1 推理/嵌入/检索

```text
调用方
  → open_clip.create_model_and_transforms()
  → factory.create_model()
  → parse_model_name() / get_model_config() / _get_hf_config() / local open_clip_config.json
  → pretrained.download_pretrained() 或 factory.load_checkpoint()
  → model_class(**final_model_cfg)
  → _set_model_device_and_precision()
  → _build_preprocess() → image_transform_v2 / audio_transform_v2 / NaFlex factory
  → tokenizer = get_tokenizer()
  → preprocess(input) + tokenizer(text)
  → CLIP/CustomTextCLIP.encode_image()/encode_text()
  → F.normalize() → exp(logit_scale) * image @ text.T (+ logit_bias)
  → 下游检索、零样本分类或持久化嵌入
```

实现关键点：`CLIP.forward()`/`CustomTextCLIP.forward()` 在 `output_dict=True` 时输出命名 dict；`CLIP.get_logits()` 重新编码并计算双向 logits（`src/open_clip/model.py:421-455`），不是由 factory 计算。`create_model` 的 full checkpoint 使用转换器、NaFlex state dict 转换、位置 embedding resize 后再 strict load（`factory.py:264-296`）。

### 14.2 新训练/评估

```text
python -m open_clip_train.main
  → params.parse_args()
  → distributed.init_distributed_device()
  → create_model_and_transforms()
  → create_task()：unwrap_model 后按 CLAP → distill → CoCa/MaMMUT → GenLAP → GenLIP → SigLIP → CLIP dispatch
  → optional task.compile / task.prepare_fsdp / task.prepare_distributed
  → create_optimizer() + scaler + scheduler
  → load_checkpoint()/load_sharded_checkpoint()（resume）
  → get_tokenizer() + get_data()
  → TrainState(task, optimizer, scaler, scheduler, counters)
  → train_one_epoch()
       → task.prepare_batch() → task(batch) → backward → optimizer.step → clamp_logit_scale
       → optional all_reduce / EMA/logging
  → evaluate()
       → task(batch) → CPU feature accumulation → get_clip_metrics / zero-shot
       → results.jsonl / TensorBoard / wandb/trackio
  → save_checkpoint()/save_sharded_checkpoint()
  → distributed.barrier() → final remote sync
```

`create_task` 必须基于解包后的真实模型类型而非名称字符串（`factory.py:1097-1185`），否则 `hf-hub:`/`local-dir:` 或改名配置可能错误落到 `CLIPTask`。FSDP2 顺序是 per-block `torch.compile`（如启用）→ composable checkpoint → `fully_shard`；并注册 `encode_text`/`encode_image` 为 FSDP forward method（`task/base_task.py:256-361`）。

### 14.3 数据链与变长/NaFlex

```text
get_data()
  → get_dataset_fn(dataset_type)
  → WebDataset: shard → split_by_node/worker → tar samples → filter/rename/caption → tokenize
       → optional LengthBucketer → decode image/audio → transform → collate
  → CSV: CsvDataset → tokenize/variable text → optional NaFlexMapDatasetWrapper → DataLoader
  → Synthetic: SyntheticDataset → tokenizer → DataLoader
  → batch dict: image/audio patch dict + text + optional text_valid
  → TrainingTask.prepare_batch()（浮点迁移到 device/dtype，整数保持 dtype，递归 dict）
```

NaFlex 训练在 `NaFlexBatcher.run()` 中先从源取样，按 schedule 选择 seq_len/patch，`process_sample()` 只包裹 decode；坏 decode 触发 `SampleDecodeError`，由 handler 决定 skip+replenish 或 re-raise。transform/patchify 错误故意不包裹，直接暴露为管线 bug（`naflex_data.py:743-767,917-959`）。预取模式以 daemon thread + `queue.Queue` 重叠上游分桶与下游解码；消费者提前结束时 `stop.set()` 并排空队列，但源码不 join 线程，仅依赖线程在 poll 周期内退出（`naflex_data.py:321-383`）。

## 15. 关键小节点明细

| 节点 | 前置条件 | 状态变化/读写对象 | 调用者 → 被调用者 | 并发/失败/恢复 | 证据 |
|---|---|---|---|---|---|
| 模型标识解析 | 非空合法 schema | 读内建 config、local JSON 或 HF 配置；不写仓库 | factory → parser/config loader | local 缺失立即失败；HF 默认权重失败可降级为 config-only（但 `require_pretrained` 后续会拒绝） | `factory.py:387-462` |
| checkpoint 归一化 | checkpoint 可读 | 读权重，改内存 state dict：去 `module.`、第三方转换、维度/位置 embedding 修正 | `load_checkpoint` → converters → `model.load_state_dict` | strict=True 捕获结构漂移；无磁盘写回；不负责超时/取消 | `factory.py:230-296` |
| special-token 校验 | tokenizer 已解析 | 只读 config/tokenizer `eos/pad`；阻断不一致组合 | `get_tokenizer` → `_validate_special_tokens` | fail-fast，避免错误 pooling/label masking；生成无 pad 时可能仅 warning/fallback | `factory.py:766-830` |
| task dispatch | model 已实例化；args 标志完整 | 创建 task、loss、rank/world size 参数；可附 NaFlex config | `main` → `create_task` → task/loss 构造 | CLAP distill 明确拒绝；dispatch 失败抛错；无动态注册/热替换 | `factory.py:1097-1185` |
| batch 准备 | batch dict，tensor shape 合法 | 新建递归 dict，浮点转 input dtype，整数只迁设备 | train/eval → `TrainingTask.prepare_batch` | 非 tensor 原样保留；没有 shape/schema 总校验 | `task/base_task.py:135-157` |
| 对比损失 | model out 含 features/scale | 可能 all-gather/neighbor exchange，返回带 `_loss` 键的 dict；task 汇总为 `loss` | `CLIPTask`/`SigLIPTask` → `ClipLoss`/`SigLipLoss` | 分布式 collective 要求各 rank 形状/步调一致；异常无事务回滚 | `task/clip_task.py:41-46`; `loss.py:118-227,359-467` |
| caption label 构造 | text 为 `[B,L]`；可选 `[B,L]` valid | 右移 labels；无效位置变 `-100` | `CoCaTask`/`GenLipTask` | `text_valid` 缺失时 pad fallback；fused CoCa+accum 明确不支持 | `task/coca_task.py:72-103`; `genlip_task.py:114-139` |
| NaFlex schedule | timm NaFlex 可用；预算、patch/seq 配置合法 | 生成每 epoch schedule、patch dict、valid mask；保持 batch size 以满足 all-gather | data → scheduler → batcher → task | 坏 decode 有界跳过；坏 transform 直接失败；连续失败阈值由环境变量 `OPEN_CLIP_MAX_CONSECUTIVE_DECODE_FAILURES` 控制 | `naflex_data.py:490-517,743-767,917-959` |
| train step | optimizer 非空；scheduler 除非显式跳过 | backward、optimizer/scaler step、logit scale clamp、global_step/samples_seen 增长 | `train_one_epoch` → eager/compiled step → task | `accum_freq>1` 重算 forward；compile+累积/scaler 组合 fail-fast；异常不保证 optimizer/梯度回滚 | `train.py:164-317,343-426` |
| eval feature accumulation | rank0 或 FSDP eval 协议 | GPU features 搬到 CPU list；最后算 chunked retrieval metrics | `evaluate` → task → `get_clip_metrics` | FSDP 非 rank0 用 dummy batch，并由 broadcast signal 控制结束；普通非 rank0 直接 return；内存仍随 N×D 增长 | `train.py:542-729` |
| checkpoint latest swap | save 权限/磁盘空间；分布式 rank 协同 | full `.pt` 用 `tmp.pt`→`os.replace`；sharded 用 `_tmp_latest`/`epoch_latest`/`_trash_latest` | main → checkpoint helper → torch.save/DCP | 注释描述“至少一个目录存活”，但 rename/rmtree 非完整事务；进程杀死窗口仍需恢复审计 | `main.py:683-767` |

## 16. 资源生命周期与终态矩阵

| 资源 | 创建/持有 | 正常释放 | 业务失败 | 超时/主动取消 | 宿主/子进程崩溃与残留验证 |
|---|---|---|---|---|---|
| 模型/EMA/optimizer/scaler | factory/task/main 创建；task 持有 | 依赖 Python 引用/进程退出；EMA 由 `ModelEmaV3` 持有 | 构造或 load 异常时局部对象由引用计数/GC 回收，无显式 rollback | 无 API 取消；调用方只能停止训练 | 进程崩溃由 OS 回收 GPU/CPU；未见源码级残留探针 |
| image/audio/full-res sample | DataLoader worker/batcher 临时持有 | `process_sample` 返回后 full-res 不再由 batch accumulator 持有 | transform/patchify 异常传播；坏 decode 可 skip | 预取消费者 finally `stop.set()`、排空 queue；不 join | daemon thread 依赖自然退出；需现场检查线程/worker 是否消失 |
| prefetch thread/queue | `_prefetch` 迭代开始时创建 | done sentinel + finally stop/drain | producer 异常放入 `box["exc"]`，consumer 结束后抛出 | stop event + queue drain；put poll 最长约 1s 一轮 | 无强制 join/残留断言；worker 被杀由 DataLoader/OS 处理 |
| WebDataset/CSV/DataLoader workers | `get_data`/WebLoader/DataLoader 创建 | 迭代结束或 DataLoader 生命周期结束 | handler 对部分 decode/parse 错误 skip；系统性错误可能最终抛 | epoch 边界依赖 iterator 关闭；persistent workers 可能长期存活 | 主流程无 finally 统一关闭 worker；需运行后查进程 |
| URL/HF 下载文件 | cache dir + `open(...,"wb")` 持有 | 文件写完后返回，后续 cache 复用 | SHA256 不匹配抛；坏文件重下；部分文件无隔离临时名 | `urlopen` 没有 timeout；Ctrl-C/kill 可能留下部分文件 | 无崩溃恢复/垃圾扫描；需手动检查 cache 临时/异常文件 |
| checkpoint full/sharded | rank0 或所有 rank 写文件/目录 | 文件/目录保留为恢复制品；latest 可删除 previous | save 抛异常时临时文件/目录可能残留 | 无 save timeout/cancel API；分布式必须所有 rank 协同 | 强杀可能落在 rename/rmtree/barrier 间；需检查 `.metadata`、`_tmp_latest`、`_trash_latest` 和全文件可读性 |
| distributed process group/barrier | `init_distributed_device`/DDP/FSDP | 代码未在 `main` 正常尾部显式 `destroy_process_group` | 任一 rank 异常可能使 collective 阻塞或报通信错误 | 无超时由本项目层统一管理 | 进程组/子进程由 torch/OS 处理；需 `ps`/端口/日志确认无残留 |
| remote sync subprocess | `start_sync_process` 仅 master 创建 | 正常末尾 `terminate()`，再 final sync | 初始或 final sync 返回 false 只记录失败 | `terminate()` 非 wait/kill；无超时封装 | 主进程 crash 时没有 finally；需查同步子进程与远端半成品 |

当前代码**没有**统一的 cancellation token、请求 deadline、进程组 kill、下载临时文件原子提交、checkpoint checksum 或启动后资源审计入口。因此“正常路径能返回”不能推出“超时/取消/崩溃安全”。

## 17. 失败、超时、取消与崩溃矩阵

| 场景 | 当前实现证据 | 结论 | 验证状态 |
|---|---|---|---|
| 非法模型名/本地目录/缺配置 | factory 多处 `FileNotFoundError`/`ValueError`/`RuntimeError` | 明确失败，不静默造随机模型 | 源码已核对；未执行每分支 |
| HF config 成功、默认权重不存在 | `factory.py:455-460` 捕获权重下载异常后继续 | 允许 config-only；只有 `create_model_from_pretrained` 的 require gate 才阻断 | 源码已核对；未做在线 HF 探针 |
| 预训练 URL 超时/断线 | `urllib.request.urlopen(url)` 无 timeout；写入最终 cache 文件 | 无界等待风险；中断可能部分写入，非事务 | 源码已核对，未注入断网/kill |
| checksum 不匹配 | 已有 cache 重新下载；下载后前缀 SHA256 校验 | 可检测内容错，但未覆盖原子下载/并发下载 | 源码已核对，未跑夹具 |
| tokenizer eos/pad 不一致 | `_validate_special_tokens` fail-fast；生成非零 pad 缺配置为 warning | 防止部分 silent corruption；warning 分支仍需专项验证 | 源码已核对，测试文件存在 |
| 空/坏 WebDataset 样本 | filter + `log_and_continue`；NaFlex decode skip/replenish | 坏 decode 有界，transform bug 不隐藏 | 源码已核对；未跑坏 tar/全坏流 |
| 全部样本持续 decode 失败 | consecutive counter > `_MAX_CONSECUTIVE...` re-raise | 有界失败，避免无限补样 | 源码已核对；未执行超阈值探针 |
| 变长文本超过 cap | `collate_variable_text` 抛 `ValueError` | 不静默截断，保护 EOS/绝对位置 | 源码已核对；未执行超限夹具 |
| fused caption + grad accumulation | `CoCaTask.compute_accum_loss` 抛 `NotImplementedError` | 明确互斥，不是假支持 | 测试源码/源码已核对 |
| torch.compile 不兼容组合 | train loop 对 compile-step + accum/scaler fail-fast；main 对 DDP dynamic shape 调整 | 部分互斥有显式保护，图编译运行仍依赖环境 | 未运行 compile |
| DDP/FSDP rank 不一致/collective 中断 | batch 需相同形状；eval 用 signal broadcast；barrier 由 main 调用 | 设计上保持步调，但无应用级 deadline/故障恢复 | 未做多进程故障注入 |
| checkpoint 写入中断 | latest 有临时替换策略；epoch 文件/DCP 目录无统一校验 | 尽量保留旧 latest，不等于可证明完整 | 未做强杀/恢复测试 |
| remote sync 失败/主进程崩溃 | 返回 false 仅日志；正常尾部 terminate，异常无 finally | 失败可见但无重试/回滚/残留治理 | 未运行 AWS/S3 外部链路 |

## 18. 防假绿验证等级（L0-L4）

本项目的“测试存在”“测试被收集”“测试通过”“外部能力可用”必须分开记账。以下是本次文档任务采用的判级规则，不把历史 README 或旧细探算作执行证据。

| 等级 | 必须证明什么 | 当前核对状态 | 不能冒充的结论 |
|---|---|---|---|
| L0 文件/声明 | `ARCHITECTURE.md`、旧细探、源码路径存在；旧细探未删除；文档章节完整 | **已完成**：现场读回两份文档并检查路径 | 不能证明 Python 可导入或模型可运行 |
| L1 静态源码 | 当前源码可被 AST 解析；关键函数/类/测试文件可定位；工作树只改目标文档 | **已完成**：当前核对现场计数 `src/*.py=70`、`tests/*.py=47`、配置 JSON=190，且读到关键实现；验证命令见第 22 节 | 不能证明依赖、CUDA、HF、timm 或运行时环境可用 |
| L2 本地单进程 | 使用实际安装依赖运行无网络、CPU、小模型/夹具的目标单测，记录测试数/skip/退出码 | **未执行**：本任务禁止安装依赖/构建，且不以静态读代替测试 | 不能把测试源码中 `skipif`/`importorskip` 当通过 |
| L3 真实边界 | 真实 checkpoint round-trip、NaFlex/timm、WebDataset/CSV、FSDP/DDP/compile、坏数据与保存中断探针 | **未执行** | 不能声称 GPU/分布式/断点恢复/失败清理已验证 |
| L4 外部系统 | 真实 HF Hub/URL/S3/远端日志同步与权限/断网/超时/崩溃证据 | **未执行** | 不能声称外部下载、remote sync 或线上权重可用 |

测试树中确实有 `pytest.importorskip`、CUDA skip、macOS skip 和 NaFlex/timm 条件 skip（例如 `tests/test_task_compile.py:51-103`、`test_retrieval_metrics.py:164-185`、`test_naflex_mammut.py:19`、`test_training_simple.py:11-100`）；这些是条件覆盖线索，不是当前核对通过数。旧细探提出“重型 PyTorch/GPU 应独立进程”的边界已吸收为第 16、17、19 节的未验证风险，但源码当前并未提供统一外部进程隔离层。

## 19. 当前源码与旧细探的吸收/不吸收裁决

| 旧细探主张 | 当前源码对照 | 裁决 |
|---|---|---|
| CLIP 图文嵌入、对齐空间、零样本分类 | `model.py` 编码/归一化/logits；`zero_shot_classifier.py` 与 train zero-shot 入口存在 | **吸收**：写入第 1、5、13、14 节 |
| SigLIP 是 sigmoid 变体 | `SigLIPTask` 选择 `SigLipLoss`，loss 负责实现 | **吸收**：写入第 6、13、15 节 |
| NaFlex 可变分辨率/patch 与训练栈 | `naflex_config.py`、`naflex_data.py`、NaFlex model/task、timm gate 均存在 | **吸收并加深**：补预算、分桶、解码失败有界与生命周期 |
| CLAP 音频-文本 | `CLAP`/audio data/`CLAPTask` 与 factory dispatch 存在 | **吸收**：不再把项目仅描述为图文库 |
| 训练栈含 TrainingTask/FSDP2/torch.compile | `TrainingTask`、main 的 compile/FSDP/DCP 分支和测试存在 | **吸收但标未验证**：实现存在不等于本机组合可运行 |
| “main 训练 API 变化、v3 稳定” | README/当前版本说明线索；本地源码同时保留 `legacy_*` | **吸收为版本风险**，不把 `v3` 说成当前源码事实或推荐版本 |
| MIT、Python + PyTorch + GPU/权重依赖 | LICENSE/pyproject/README/依赖配置和运行路径支持 | **吸收**；许可证与外部权重许可仍需逐模型复核 |
| `src/open_clip/` 是核心、训练栈为旁路线索 | 真实目录和 import 链确认 | **吸收并扩展**为目录/调用链 |
| “平台多模态嵌入/视觉理解候选”“可借鉴” | 这是跨项目设计建议，不是 open_clip 的实现事实 | **不吸收到实现契约**；仅保留在第 20 节候选裁决，待独立需求与隔离验证 |
| “平台引入须独立进程” | 当前 open_clip 本身未实现统一 subprocess provider；只有 AWS sync subprocess | **不宣称已实现**；作为外部接入建议/剩余风险保留 |

## 20. 对平台的吸收裁决（仅研究结论，不启动实现）

- **吸收**：图文/音文统一嵌入接口的“输入预处理 + tokenizer + encoder + 归一化向量 + 相似度”分层；`text_valid`/`patch_valid` 显式有效性；任务层统一 batch/loss/checkpoint 适配；NaFlex 的预算→schedule→分桶→按需 decode/patchify→collate 模式。
- **待核**：单一模型能力 id、权重 cache 的内容校验/原子落盘、GPU/CPU 资源预算、模型版本与预处理元数据绑定、fused CE 的内存预算。这些需要平台现有能力搜索、契约登记和真实边界测试，不能从本仓库直接复制。
- **隔离**：`torch`/`timm`/`transformers`/音频库/CUDA/FSDP2/`torch.compile`/HF Hub/S3；不把第三方对象穿透公共契约，不把本项目直接变成生产底座。
- **不吸收**：未被当前源码证明的“服务超时、取消、崩溃恢复、缓存事务、外部重试、GPU 隔离”能力；当前只记录缺口，不生成第二套运行时。

## 21. 未验证项与后续复核清单

1. 未安装依赖、未导入完整 `open_clip`、未运行 pytest；当前 Python/torch/timm/transformers/torchaudio 版本未形成实测证据。
2. 未下载或读取任何真实 pretrained 权重；HF Hub、URL、safetensors、SHA256、cache 并发/断点行为未验证。
3. 未执行 CPU 端最小模型推理、图文 embedding round-trip、zero-shot classifier、CSV/WebDataset/synthetic 数据链。
4. 未执行 NaFlex timm transform、坏图/坏音频、全坏流、超长文本、prefetch 提前关闭和 persistent worker 残留探针。
5. 未执行 CoCa/MaMMUT/GenLIP/GenLAP 的真实 caption loss、fused CE、`text_valid`/`pad_id` 交叉组合探针。
6. 未执行 DDP、FSDP2、gradient checkpointing、`torch.compile`、AMP/bf16、EMA 与 checkpoint 往返组合；相关测试存在但可能条件跳过。
7. 未执行 checkpoint 强杀、DCP 目录残缺、latest rename 窗口、remote sync 失败/子进程残留恢复。
8. 未验证 `urllib.request.urlopen` 无 timeout 导致的长阻塞和下载半文件清理；这是当前明确的资源治理缺口。
9. 本轮 `origin/main` 与本地 HEAD 已一致；后续上游新提交仍需重新读取 README、factory、NaFlex、tokenizer、训练 CLI。
10. 细探旧文档已吸收但保留；若未来发现其与源码冲突，必须在本文修正并保留冲突说明，不回写旧细探制造双事实源。

## 22. 当前核对验证与证据

### 22.1 实际执行命令与退出码

| 命令 | 退出码 | 结果 |
|---|---:|---|
| `git status --short; git branch --show-current; git rev-parse HEAD; git log -1 --format='%H%n%ci%n%s'; git ls-remote origin refs/heads/main` | 0 | `main`；本地 HEAD=`602d4af74f86df6f2ff81ba0f0a847b0b70ad2e5`；远程同一提交；工作区有未跟踪 `.codegraph/` 与根 `ARCHITECTURE.md` |
| Python 只读计数脚本（`src` Python/`tests` Python/模型配置/非 Git 文件及字节数） | 0 | `70 / 47 / 190 / 376 / 15434694`；与本文原有规模叙述一致（测试主文件数以现场 glob 为准） |
| 目标仓库只读结构校验（读取文档标记、旧细探大小与存在性，并对 `src`+`tests` 共 117 个 Python 文件执行 `ast.parse`） | 0 | `doc_bytes=51213`、`doc_lines=495`、旧细探 `2064` bytes；`ast_failures=0`、`markdown_structure=PASS`；旧细探 SHA256=`97b6ef31e9c6c6d66914b0591a274f96f5cf3d38d1450e064ff86159270ec62c` |
| 当前核对 `read_file` 完整读取 `细探-open_clip.md` 与 `ARCHITECTURE.md` | 0 | 旧细探 65 行、当前架构文档原 289 行，已逐段对照；旧文件仍存在 |
| MCP | 未使用 | 按用户授权跳过 MCP，不生成开工、反馈或验证记录 |
| `codegraph status` | 0 | 目标仓库独立索引：126 files、3,118 nodes、7,432 edges、9.44 MB，index up to date |
| `codegraph explore` | 0 | 定位 `create_model_and_transforms`、`create_model`、`load_checkpoint`、`get_tokenizer`、`get_data` 等调用/测试关系 |

### 22.2 文档验收口径

- 当前核对只允许并只修改：`/Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/40_embedding_retrieval/open_clip/ARCHITECTURE.md`。
- `细探-open_clip.md` 未删除、未改写；源码、README、配置、依赖、测试未修改。
- 本文现在包含流程图、真实调用链、契约表、节点表、资源生命周期、失败/超时/取消/崩溃矩阵、L0-L4 防假绿、未验证项和吸收/不吸收裁决。
- 当前核对未把“源码存在/测试存在/历史成功证据”写成当前测试通过；未验证项保持明确。

## 23. 本次建档变更记录

- 修改：`ARCHITECTURE.md`（本文件），吸收完整 `细探-open_clip.md` 并补充深度事实表与验证边界。
- 保留：`细探-open_clip.md`，不删除、不作为后续权威维护入口。
- 未修改：源码、README、依赖、模型配置、测试、Git 配置。
- 未执行：安装、服务启动、权重/数据下载、训练、pytest 全量、GPU/分布式/外部系统验证、提交。

## 24. 后续通用底座映射（当前核对增补）

> 本节是后续“项目能力 → 公共底座”的裁决输入，不是 open_clip 的生产改造方案。当前系统工程平台 `system_engineering_toolkit` 的能力搜索对“多模态嵌入、图文嵌入、模型提供者、资源预算、取消/超时/断点恢复、checkpoint/远程同步/分布式”等关键词均返回空候选；因此以下能力 id、包名和装配均标记为**待登记/未实现**，不能把本仓库代码或平台说明当作已装配能力。

### 24.1 归属裁决：支持库、模型提供者、运行核心

| open_clip 能力/事实 | 公共底座归属 | 单链路职责 | 后续裁决 | 源码证据 |
|---|---|---|---|---|
| `CLIP`/`CustomTextCLIP` 的 `encode_image`、`encode_text`，L2 归一化和 `logit_scale` 点积 | **多模态嵌入支持库**的原子契约；具体模型执行下沉到 provider | 定义输入/输出向量、维度、dtype、归一化、模型/预处理摘要和错误码；不暴露 `torch.Tensor`/模型对象 | **新建候选能力，待需求登记**；现有能力搜索无命中 | `src/open_clip/model.py:421-455` |
| `CoCa`/`MaMMUT` 的双向编码与 caption 路径、`CLAP` 的音频/文本编码、GenLIP/GenLAP 的媒体前缀生成 | **多模态嵌入支持库**的同一契约下的模型策略；仅图文嵌入首期落地 | provider 可按模型族选择策略；模块不得复制第二套编码流程 | **吸收为策略，不拆成多条公开图文链** | `src/open_clip/coca_model.py:142-164,280-285`；`clap_model.py:72-103`；`naflex_genlip_model.py:772-854` |
| `factory.py` 的模型名/结构配置/预训练 tag/本地目录/HF Hub 解析，`transform.py` 的 mean/std/resize/interpolation | **多模态嵌入支持库**持有稳定元数据契约；**OpenCLIP 模型提供者**持有第三方实现 | 请求携带模型标识、revision、权重摘要、预处理摘要；返回必须绑定同一组元数据，禁止“模型加载成功但预处理漂移” | **吸收边界，provider 隔离实现** | `factory.py:387-462,620-763`；`transform.py:17-108` |
| checkpoint 解析、state dict 转换、full/sharded DCP、optimizer/scaler/EMA/epoch 恢复 | 支持库定义 checkpoint 制品/摘要/兼容性契约；provider 读写模型状态；**运行核心**负责原子提交、保留策略、恢复选择和证据 | 只有完整、可读、版本匹配的制品可成为恢复候选；训练进程不把半成品标为成功 | **升级资源管理/制品能力，不能直接复用训练脚本为平台能力** | `task/checkpoint.py:56-216`；`main.py:683-767` |
| NaFlex patch/sequence/token budget、长度分桶、decode/patchify/collate | **多模态嵌入支持库**定义变长输入/预算参数契约；provider 调用 timm/OpenCLIP；运行核心执行资源预算 | `patch_valid`/`text_valid` 和 token budget 是显式字段；不可用时 fail-fast，不允许偷偷退回固定尺寸 | **吸收为通用变长数据模式；timm 只归 provider** | `naflex_config.py:16-132`；`naflex_data.py:461-689`；`data.py:650-736` |
| `remote_sync_s3`/`remote_sync_fsspec`、周期同步子进程、`--resume latest` | 远端对象存储/同步是受管 **checkpoint transport provider**；同步时机、重试、deadline、取消、残留和恢复由运行核心 | 只同步已完成制品；排除正在变化的 `epoch_latest.pt`；远端候选需摘要/版本校验 | **隔离并升级，不把 `aws` subprocess 作为公共实现** | `file_utils.py:12-63`；`main.py:162-232,772-784` |
| DDP/FSDP2、rank/world size、NCCL/Gloo、collective/barrier、`torchrun` | **运行核心**的分布式执行单元、GPU 租约和故障治理；provider 只声明所需 backend/拓扑并执行训练 | 运行核心分配 GPU/rank、启动/排空/终止进程组；provider 不自建网关、端口或第二套调度 | **吸收执行模型，待平台能力登记** | `distributed.py:80-183`；`main.py:108-126,239-244,765-767` |
| CUDA/MPS/CPU、AMP/fp16/bf16、FSDP CPU offload、梯度 checkpoint、compile、worker/pin memory | **运行核心**拥有资源预算、设备选择、并发/队列、健康和释放；provider 负责模型特有的 dtype/compile 约束 | 资源预算必须在 provider 启动前检查，超预算排队或明确拒绝；不向调用方泄漏 CUDA 对象 | **吸收治理原则；GPU provider 需独立进程** | `distributed.py:23-41,169-175`；`params.py:601-627,840-905` |

### 24.2 现有能力命中、缺口与复用裁决

| 结论 | 依据 | 处理 |
|---|---|---|
| 现有“多模态嵌入/图文编码”公开能力 | `system_engineering_toolkit` `capability_search` 当前核对 7 组关键词均返回 `[]` | **缺口**；登记一个能力 owner 后再做装配，当前不声称复用 |
| 现有 `支持库/后端/资源管理` 的原子写入、临时登记、CAS/摘要模式 | 平台 `开发文档/支持库总览.md` 的资源管理边界 | **复用/升级候选**：用于 checkpoint 制品、临时目录、摘要和幂等释放；不承载模型推理 |
| 现有 `支持库/适配层/本地LLM提供者` | 平台现有提供者目录是本地文本模型边界，与 open_clip 的图文塔、NaFlex、GPU 训练契约不同；能力搜索无命中 | **不直接复用**；只借鉴受管 provider 生命周期，避免把文本模型 provider 改成多模态万能包 |
| `启动监督器`/`运行核心` 的独立进程、租约、超时、取消、崩溃回收原则 | 平台 `开发文档/项目说明.md` 的执行单元契约与 provider 统一边界 | **复用运行核心治理**；不让 `open_clip_train.main` 自己成为平台调度器 |
| `open_clip` 的 `file_utils.py`、`main.py` remote sync 和训练 CLI | 源码是项目内脚本：无请求 deadline、无取消令牌、S3 `subprocess.run` 无超时，周期进程仅正常尾部 `terminate()` | **废弃为公共底座实现**；只保留为适配 provider 的历史参考 |
| 零样本分类、检索指标、caption 生成 | 这些是上层任务流程，不是图文编码原子能力 | **待建模块**；先复用唯一嵌入能力，不能再各自加载模型和 tokenizer |

**后续归属结论：**

1. **多模态嵌入支持库**：拥有唯一的图文编码契约、预处理/Tokenizer 元数据、向量结果、模型 revision/权重摘要、维度/dtype/归一化和输入边界；首期只定义图像+文本对齐编码，音频/生成式路径作为同契约策略扩展。
2. **OpenCLIP 模型提供者**：唯一允许加载 `torch`、`open_clip`、`timm`、`transformers`、HF 权重和 CUDA 依赖；把 `create_model_and_transforms`、tokenizer、`encode_image`/`encode_text`、NaFlex batch 转换为公共结果。provider 不向模块或网关暴露模型对象、第三方异常、GPU context 或本地 checkpoint 路径。
3. **运行核心**：拥有 execution unit/lease、CPU/GPU/显存/内存/文件/队列/进程预算、按需启动或有界缓存、超时、取消、进程组终止、健康检查、崩溃回收、checkpoint 原子提交、远程同步和恢复证据。HTTP 网关只传统一请求/响应，不复制一套执行逻辑。
4. **不在当前核对归属**：模型训练损失、检索业务、零样本分类和 caption 生成不进入图文嵌入支持库的原子入口；需要时由上层模块组合同一编码能力。

### 24.3 唯一图文嵌入链路

```text
任意调用方
  → 唯一 HTTP 能力网关（request_id + capability_id + contract_version + deadline + resource_budget）
  → 运行核心唯一能力调用器/注册表
  → 多模态嵌入支持库：唯一能力 `多模态嵌入.编码图文`（候选 id，尚未登记）
  → OpenCLIP 模型提供者（唯一 torch/open_clip/timm/HF/CUDA 边界）
  → 运行核心分配或复用受管 GPU execution unit/lease
  → 模型/权重/预处理元数据一致性校验
  → 图像：受控制品/字节 → image transform/NaFlex patchify → encode_image
  → 文本：受控文本 → tokenizer/text_valid/pad 校验 → encode_text
  → provider 内部统一 L2 normalize，生成配对向量与维度/dtype/模型/预处理摘要
  → 运行核心记录请求、provider 版本、权重摘要、资源预算、释放结论
  → 统一结果返回（不携带模型对象、GPU 对象或内部路径）
  → 上层检索/零样本模块只消费该结果，禁止旁路加载 open_clip
```

这条链的硬约束是：图像和文本可以在 provider 内并行计算，但只能从同一个 `model_id + revision + checkpoint_digest + preprocess_digest + tokenizer_digest` 组合产生结果；任何模块、项目适配层或脚本直接调用 `open_clip.create_model*`、`encode_image`、`encode_text` 或第三方 tokenizer 均属于侧链。图像单向/文本单向批量如果未来需要公开，也必须归入同一能力 owner 和同一 provider 版本策略，不能形成第二个注册表或第二套错误转换。

### 24.4 资源预算、取消、超时、崩溃和断点恢复契约

| 维度 | open_clip 当前事实 | 底座应如何接管 | 当前核对状态 |
|---|---|---|---|
| 输入/输出 | 图像受 transform/patch 上限约束，文本受 context/pad cap 约束；向量通常按 `N×D` 累积到 CPU | 契约声明最大字节、像素、音频秒数、文本 token、batch、向量字节和输出制品大小 | **待实现** |
| NaFlex 显存/批预算 | `max_tokens_per_batch` 可显式传入，否则按 batch × 最大 seq_len（GenLIP 另加 text cap）推导；`batch_divisor` 约束批量 | 启动前预算校验；GPU 显存不足返回稳定错误或排队，不静默改 seq/batch；记录实际 peak/吞吐 | **源码有预算，平台未接管** |
| CPU/原始数据内存 | `bucket_pool` 默认 2048，预取池还会按 `pool × prefetch_pools` 缓存原始字节；NaFlex batcher 尽量一次只解码一个完整样本 | 预算必须包含 worker、pool、prefetch、pin memory、模型和输出；超限拒绝或降低并发并留下证据 | **待实现** |
| GPU/进程/并发 | `init_distributed_device` 选择设备；DDP/FSDP2 依赖 rank/world size 和 collective 同步 | 运行核心分配 GPU lease、进程组和并发槽；provider 只接收不透明 execution id | **待实现** |
| 主动取消 | open_clip 没有统一 cancellation token；NaFlex 预取只在迭代器提前结束时 `stop.set()`，且不显式 join daemon thread | 由运行核心传播 cancel token；provider 在 batch/epoch/collective 边界检查；超时后 kill 整个 provider 进程组并验证残留 | **缺口** |
| 请求超时 | 预训练 URL 使用 `urllib.request.urlopen(url)` 无 timeout；S3 `subprocess.run` 无 timeout；训练/保存没有请求 deadline | 网关/运行核心设硬 deadline、I/O timeout、checkpoint/save timeout；超时返回 `TIMEOUT` 且 `retryable` 明确 | **缺口** |
| provider 崩溃/OOM | 当前源码依赖 Python/torch/OS 回收；分布式 rank 异常可能让 collective 报错或阻塞；无统一残留探针 | 监督器记录退出码/信号/OOM，隔离失败执行单元，回收进程组/GPU/临时目录/端口，再决定有限重启 | **缺口** |
| full checkpoint | 保存 `epoch/state_dict/optimizer/scaler/global_step/samples_seen`；`save_most_recent` 使用 `tmp.pt`→`os.replace` | 仅允许摘要、schema、模型/预处理/代码环境匹配的完整制品进入 latest；写入由资源管理支持库原子提交 | **部分实现，未真实验证** |
| sharded checkpoint | DCP 目录由所有 rank 写，master 写 `_metadata_extra.pt`；latest 使用 `_tmp_latest`/`_trash_latest` 交换 | 运行核心扫描 `.metadata`、全部 shard、metadata 和摘要；恢复前排除半目录，保留最近可读版本 | **部分实现，未真实验证** |
| remote sync | S3 `aws s3 sync` 排除 `epoch_latest.pt`；fsspec 逐 key 复制；周期同步在独立进程 | 同步任务要有 deadline、取消、重试退避、完整制品 manifest、远端摘要和半成品隔离；进程由监督器管理 | **部分实现，未真实验证** |
| resume/断点恢复 | `--resume latest` 由 master 选路径并广播；恢复 epoch、optimizer、scaler、global_step、samples_seen；未证明 RNG/精确样本位点恢复 | 恢复契约必须区分“epoch 级恢复”和“精确样本级恢复”；只对可验证 manifest 的 checkpoint 返回成功 | **epoch 级部分实现；样本级待核** |

### 24.5 后续失败/终态验收矩阵

```text
正常完成
  → 图文向量与元数据返回
  → 一次性 provider 退出，或 lease/cache 按 owner/TTL 保留
  → checkpoint/远端 manifest 完整，资源释放证据为零残留

业务失败（非法输入、缺模型、权重不兼容、坏图/坏文本）
  → 稳定 error_code + retryable
  → 不写半成品、不返回随机模型或空向量冒充成功
  → 文件、队列、GPU、进程和临时目录回收

主动取消/超时
  → 运行核心标记请求终态
  → provider 停止接受新 batch，排空/终止进程组
  → kill 超时未退出的子进程，回收 GPU/端口/目录/句柄
  → 返回 `CANCELLED`/`TIMEOUT`，可重试性由是否产生完整 checkpoint 决定

provider/宿主崩溃/OOM
  → 监督器记录信号、退出码和最后 checkpoint manifest
  → execution unit 进入失败/回收中，禁止句柄复活
  → 只从最近完整且摘要匹配的 checkpoint 恢复
  → 若无可读恢复点，返回 `PROVIDER_CRASHED`，不能伪造成功
```

open_clip 当前能证明的是部分正常路径和源码级恢复意图；它不能证明上述四种终态已经由平台实现。尤其是 URL 下载半文件、fsspec/S3 中途失败、远程同步子进程、DCP 目录交换、DDP collective 阻塞和 GPU OOM 均必须由运行核心的真实边界测试补齐。

### 24.6 后续 L0-L4 验收等级（映射专用）

| 等级 | 当前核对必须证明 | 当前事实/状态 | 禁止声称 |
|---|---|---|---|
| L0 文档/声明 | 唯一 `ARCHITECTURE.md` 有当前核对映射、归属、链路、预算、终态和风险；旧细探仍保留 | **已完成**：本文追加第 24 节，旧 `细探-open_clip.md` 未删除 | 不能声称能力已登记或 provider 已装配 |
| L1 静态源码 | `model.py`、`factory.py`、`transform.py`、`naflex_*`、checkpoint、remote sync、distributed、tests 路径存在且 AST/结构检查通过 | **已完成**：目标仓库 `src/open_clip` 与 `src/open_clip_train` 共 70 个 Python 文件，`ast.parse` 失败数 0；文档标记检查通过，旧细探仍存在 | 不能声称依赖、权重、CUDA、HF/S3 可用 |
| L2 本地单进程 | 在隔离环境用小模型/夹具真实完成图文编码、预处理、向量维度/归一化、checkpoint 往返、坏输入和取消清理 | **未执行**；未安装依赖、未下载权重 | 不能把测试存在、importorskip 或历史证据当通过 |
| L3 真实执行边界 | NaFlex token budget/length bucketing/prefetch、GPU OOM/峰值预算、DDP/FSDP2/compile、full/sharded checkpoint、强杀后恢复和资源零残留 | **未执行**；需专门 GPU/多进程工作包 | 不能声称分布式、GPU 预算、崩溃恢复或精确断点恢复已验证 |
| L4 外部系统 | HF Hub/URL 权重、SHA256、S3/fsspec 远端同步、断网/超时/取消/权限失败/远端恢复和多节点证据 | **未执行**；当前核对未触碰外部网络或云存储 | 不能声称线上模型、远端同步或跨节点恢复可用 |

**L1 现场验证的最低命令集合**（不改变源码、依赖、配置或测试）：

```text
python3 -c 'import ast; from pathlib import Path; r=Path("."); fs=list((r/"src"/"open_clip").rglob("*.py"))+list((r/"src"/"open_clip_train").rglob("*.py")); [ast.parse(p.read_text(encoding="utf-8"), filename=str(p)) for p in fs]; print(f"AST_PASS files={len(fs)} failures=0")'
git diff --check -- ARCHITECTURE.md
```

命令成功只证明文档/源码静态边界，不升级为 L2-L4。真实 GPU、远端和强杀验证必须由运行核心工作包在独立临时目录执行，并回传测试数量、退出码、资源残留检查和 checkpoint manifest。

### 24.7 装配计划与唯一 owner（不启动实现）

1. **需求登记**：以 `多模态嵌入.编码图文` 为候选能力，明确输入是受控制品引用还是字节、最大尺寸、向量格式、模型许可、归一化和幂等键。
2. **复用搜索**：再次搜索资源管理、制品摘要、执行单元、GPU 探针、进程组和对象存储能力；当前核对多模态搜索无命中，不能绕过登记直接写 provider。
3. **能力占用**：能力只允许一个支持库 owner；`OpenCLIP模型提供者` 作为该能力的唯一初始策略，其他模型必须在同一契约下注册，禁止另建图文入口。
4. **支持库契约**：定义模型/预处理/tokenizer/checkpoint manifest、向量 dtype/维度/归一化、错误码、deadline/cancel/resource_budget、制品引用和释放证据。
5. **provider 工作包**：隔离 `torch/open_clip/timm/transformers/CUDA/HF`，先做冷启动探针，再做 CPU 夹具；禁止把 provider 对象导出到模块或网关。
6. **运行核心工作包**：实现 GPU/内存/CPU/worker/队列预算、execution unit/lease、超时/取消、进程组回收、健康与崩溃恢复、checkpoint 原子制品和远程同步监督。
7. **模块装配**：零样本/检索/媒体分析只调用唯一图文嵌入能力，不得重复加载模型、tokenizer、权重或 preprocessing。
8. **分级验收**：先 L0/L1，再 L2 单进程，最后 L3 GPU/分布式/强杀和 L4 外部同步；每一级只在真实证据达到要求后晋级。

当前核对没有登记需求、占用能力、生成 provider、修改平台底座或启动任何训练；上述步骤只是经证据约束的后续装配计划。

## 25. 后续收口：注册、加载、预处理、推理与资源终态

> 本节是后续对当前本地源码的函数级收口，专门回答“模型如何被注册、权重如何进入模型、预处理如何绑定、batch/设备/显存如何流动、缓存和失败如何收尾”。它不把源码中缺少的 deadline、取消、显存配额或释放 API 写成已实现能力。

### 25.1 两套注册表及覆盖/变异规则

**结构模型注册表（`factory.py`）**：

1. 模块导入时 `_MODEL_CONFIG_PATHS` 初始只含 `src/open_clip/model_configs/`；`_rescan_model_configs()` 遍历 `.json`，先做 `_translate_external_config()`，仅将含 `embed_dim + vision_cfg + text_cfg`、`embed_dim + audio_cfg + text_cfg`、GenLAP 或 MaMMUT 结构的文件写入 `_MODEL_CONFIGS`，最后按 `_natural_key` 排序（`src/open_clip/factory.py:38-130`）。
2. `list_models()` 只返回当前进程内 `_MODEL_CONFIGS` 的 key；`add_model_config(path)` 是进程内全局扩展，追加路径后重新扫描（`factory.py:133-143`）。它不是带版本、锁、来源摘要或卸载操作的注册服务。
3. 同名 `cf.stem` 没有重复检测：后扫描文件覆盖先扫描文件；扫描也没有先清空 `_MODEL_CONFIGS`，所以动态添加路径后，已存在 key 会覆盖，而曾经注册但后来从路径消失的 key 可能继续留在当前进程。用户配置的 legacy MaMMUT `has_mlp=False` 等不支持情况只 warning 跳过，不阻断整个扫描（`factory.py:93-127`）。
4. 内置配置读取返回 `deepcopy`；`create_model()` 随后会对副本应用 `quick_gelu`、image/context 覆盖并 `pop('custom_text')`。因此内置注册表不会被一次创建调用直接污染；local-dir/HF 配置则在调用时从文件/Hub 读取、翻译后再处理（`factory.py:212-227,387-527,608-617`）。
5. `pretrained.py` 是静态 `_PRETRAINED`（模型名 → tag → cfg），tag 通过小写和 `-`→`_` 归一化，但模型 key 不在此处做同样别名归一化；导入时把所有 `quick_gelu=True` tag 深拷贝为 `<model>-quickgelu` 族（`pretrained.py:460-768,770-810`）。源码没有公开的动态 pretrained 注册/删除接口，也没有把模型结构、权重 revision、预处理摘要固化成一个不可变 manifest。
6. `create_model()` 对无 schema 的 `model_name` 先把 `/` 替换为 `-` 再查结构配置；而 `get_tokenizer()` 对内置标识直接以原字符串查配置（`factory.py:468-475,897-905`）。因此下游若传入带 `/` 的旧式别名，模型构造和 tokenizer 解析可能走不同分支；公共适配层必须先统一 canonical model id，不能依赖这两个入口自然一致。

### 25.2 完整权重加载顺序、所有权与部分成功

```text
解析 schema/model cfg/pretrained tag
  → URL/HF 下载或 local-dir 找候选文件
  → 依据最终 cfg 选择 CLIP/CustomTextCLIP/CoCa/MaMMUT/CLAP/GenLIP/GenLAP
  → 在目标 device 上实例化并执行 precision 转换
  → full checkpoint 以 device='cpu' 读入、转换 state dict、strict load
  → 可选 image/text/audio tower 权重再以 strict=False 覆盖
  → 设置最终 preprocess_cfg
  → 返回 model
```

- `load_state_dict()` 对 `.safetensors` 调 `safetensors.torch.load_file(device=...)`；其他格式调 `torch.load(map_location=device, weights_only=True)`，默认只接受安全权重对象。若顶层存在 `state_dict` 就取该字段；若首个 key 以 `module` 开头则去除前缀（`factory.py:230-248`）。空 state dict 在 `next(iter(...))` 处并无友好错误。
- full checkpoint 经第三方格式转换、NaFlex state-dict 转换、旧 custom-text 键迁移、`logit_scale/logit_bias` 0-D/1-D reshape、旧 transformers `position_ids` 删除、视觉/文本位置 embedding resize，最后 `model.load_state_dict(..., strict=True)`（`factory.py:251-296`）。这条路径对结构漂移 fail-fast；位置 embedding resize 是内存内改写，不回写 checkpoint 文件。
- `create_model()` 先把模型 `.to(device)`/转低精度，再用 `load_checkpoint(..., device='cpu')` 读 full 权重（`factory.py:615-643`）。因此加载阶段同时存在目标设备模型与 CPU state dict；不能把 `device='cuda'` 理解为 checkpoint 直接在 GPU 读取，也不能据此推导峰值显存为零。
- `pretrained_image_path`、`pretrained_text_path`、`pretrained_audio_path` 是后置 tower 覆盖；这些分支使用 `strict=False`，路径不存在或加载异常主要记录 warning/error 并继续，不像 full checkpoint 那样统一抛错（`factory.py:645-725`）。`require_pretrained=True` 只检查 full `pretrained_loaded`，tower-only 成功不满足该门槛；`create_model_from_pretrained()` 因而适合作为“必须有完整权重”的入口（`factory.py:727-740,1359-1476`）。
- 若 HF/local-dir 找到配置但没有默认权重，HF 分支允许 warning 后继续 config-only；只有 require gate 才阻断。若 builtin tag 下载失败则直接抛 `RuntimeError`。`load_weights=False` 会丢弃已找到的 full checkpoint 路径，但仍可能按 tower 配置构造默认基础权重（`factory.py:440-462,478-500,542-569`）。
- `force_preprocess_cfg` 在权重加载后才写入 visual 模块的最终配置；若此后预处理构造失败，源码没有事务回滚/显式模型释放，调用方只能依赖栈展开后的引用回收（`factory.py:746-763,1188-1220`）。

### 25.3 预处理与 tokenizer 的绑定边界

1. `PreprocessCfg` 只有 `size/mode/mean/std/interpolation/resize_mode/fill_color`，overlay 只接受这些字段且忽略未知字段；预训练 tag 的 mean/std/interpolation/resize_mode 先合并，最终视觉塔的 `image_size` 会覆盖 `size`，调用者的 mean/std/interpolation/resize_mode 再作为最高优先级覆盖（`transform.py:17-59`; `factory.py:478-487,751-758,1322-1328`）。
2. 普通图像验证链按 `resize_mode` 分为 `shortest`（保持比例 resize + center crop）、`longest`（保持比例 + pad）、`squash`（直接 resize），随后 `MaybeConvertMode → MaybeToTensor → Normalize`；训练链使用随机裁剪，timm/NaFlex 训练需显式 `use_timm=True`，否则 NaFlex 配置直接 `ValueError`（`transform.py:367-492`）。`interpolation='random'` 只影响训练侧，验证侧按 bicubic 处理。
3. `_build_preprocess()` 按模型实际模态分支：GenLAP 先走音频 NaFlex factory；NaFlex CLAP 走音频 patch factory；普通 CLAP 走 `audio_transform_v2`；其余图像模型走 image transform。NaFlex 验证返回 factory，必须再次以 `max_seq_len` 与 `patch_size` 调用，不能当作普通 `PIL → Tensor` callable（`factory.py:1188-1220`）。
4. 图像/音频 transform 在 CPU 数据管线执行；`TrainingTask.prepare_batch()` 才递归把浮点张量按 `input_dtype`、整数张量保持 dtype、嵌套 patch dict 以 `non_blocking=True` 搬到 device（`task/base_task.py:135-157`）。因此 preprocessing 的 CPU 内存、pin memory 和 device batch 是三个不同资源阶段。
5. tokenizer 由 `get_tokenizer()` 独立解析 model schema/config：tiktoken、HF、SigLIP 或 SimpleTokenizer。`_validate_special_tokens()` 对 eos/pad/variable_text 做 fail-fast；但 HF schema 配置失败时允许以 model id 作为 HF tokenizer fallback，最终 tokenizer 能创建不等于模型 config/权重完整可用（`factory.py:847-983`）。图像 preprocess 与 tokenizer 没有由一个运行时对象自动共同版本化；调用方必须把二者和 checkpoint 元数据一起固定。

### 25.4 推理语义、batch 形状与显存放大点

- `CLIP`/`CustomTextCLIP` 的 `encode_image()` 和 `encode_text()` 默认 `normalize=False`；`forward()` 则分别编码并 L2 normalize，`get_logits()` 也强制两侧 normalize，再做 `exp(logit_scale) * image @ text.T`（可加 `logit_bias`）（`model.py:421-455,634-655,747-767`）。调用方若直接使用 encode 结果而未传 `normalize=True`，不能假设可直接点积比较。
- factory 不调用 `model.eval()`、不包裹 `no_grad`/`inference_mode`，也不自动启用 autocast；README 示例显式执行 `model.eval()` 与 `torch.no_grad()/torch.autocast()`。因此 BatchNorm/stochastic depth、autograd graph 和低精度策略的推理风险/收益均由调用方承担（`README.md:120-133`; `factory.py:615-763`）。
- 模型 forward 以第 0 维作为 batch，普通 CLIP 文本形状为 `[B, context_length]`，图像为 `[B, C, H, W]`；源码没有推理端自动 micro-batch、动态显存探测或 OOM 重试。`get_logits()` 会产生 `[B_image, B_text]` 矩阵，图文 batch 不必相等但矩阵显存随笛卡尔积增长（`model.py:431-455`）。
- 零样本分类器是显式的类 batch：默认 `num_classes_per_batch=10`，每类的多个 template 文本一次编码，均值后重新归一化，再按类拼接；整个过程 `torch.no_grad()`，但 `num_classes_per_batch=None` 会一次性处理所有类（`zero_shot_classifier.py:20-73`）。
- 训练评估把每个 batch 的 features `.cpu()` 后追加到列表，GPU feature 常驻被压低但系统内存仍是 `O(N×D)`；随后 retrieval 以默认 4096 chunk 分块搬运/打分，避免一次 `N×N` score 矩阵，但总计算仍是 `O(N²)`，`retrieval_chunk_size<=0` 会退化为整集 score（`open_clip_train/train.py:290-351`; `open_clip_train/metrics.py:5-27,95-169`）。
- 普通 CSV/DataLoader 使用 `batch_size=args.batch_size`、`pin_memory=True`、训练 `drop_last=True`；WebDataset 先 tokenize/可选 length bucketing，再 decode/transform/batch，训练端按 `world_size × workers` 对齐完整 batch，非训练端允许最后 partial batch；persistent workers 默认在 workers>0 时开启（`open_clip_train/data.py:950-1009,1012-1121`）。
- NaFlex 的 token budget 只在可变长度数据包装器中生效：未显式给出时按 `batch_size × (max train seq len + GenLIP/GenLAP caption token cap)` 推导，`batch_divisor` 再约束有效 batch；它不是普通 `create_model().encode_*()` 的运行时显存保护器（`naflex_config.py:118-128`; `data.py:1062-1087`）。

### 25.5 设备、dtype、缓存和显存的真实边界

| 维度 | 当前源码事实 | 后续结论 |
|---|---|---|
| 设备迁移 | `_set_model_device_and_precision()` 对 fp32/其他精度执行 `model.to(device)`；`fp16/bf16` 先迁移再把适用参数转 LP，timm 额外把 `LayerNormFp32` 权重恢复为 fp32；`pure_fp16/pure_bf16` 把整个模块直接转目标 dtype（`factory.py:986-1015`） | 设备选择是构造期动作，不是按请求动态租约；dtype 组合必须按模型族验证 |
| 输入 dtype | task 的 `prepare_batch()` 只改浮点输入 dtype，token/索引保持整数；普通 inference API 不替调用方搬输入或改 dtype | CPU transform 结果不会自动跟随 model device |
| full checkpoint 峰值 | 模型已在目标设备，checkpoint 仍以 CPU state dict 读取后 strict load | 可能同时占用 CPU 权重副本、目标设备模型和加载临时张量；源码没有峰值显存/内存预算 |
| 普通 batch | 只依赖 `[B,…]` shape，无 token-budget/micro-batch/OOM fallback | batch 超预算通常由 PyTorch/CUDA 异常暴露，非稳定 OpenCLIP error code |
| NaFlex batch | 由数据侧 token budget、seq/patch schedule、length bucketing、padding/collate 限制 | 只能约束已接入 NaFlex data path，不能保护任意 provider 推理调用 |
| 评估检索 | GPU 上只保留当前 score chunk；features 列表在 CPU 累积 | GPU 有界不代表主机内存有界；整集仍需 `N×D` |
| cache 位置 | URL 默认 `~/.cache/clip` 或传入 `cache_dir`；HF 由 `hf_hub_download` 管理其 cache/revision | URL cache 与 HF cache 是两套机制，源码没有统一 cache manifest |

### 25.6 下载缓存的并发、校验与失败语义

- URL 下载以 `basename(url)` 作为 cache 文件名，默认目录为 `~/.cache/clip`；仅对 `openaipublic` 路径段或 `mlfoundations` 文件名后缀推导 SHA256 前缀，其他 URL 不校验。已有文件若无 expected hash 直接复用（`pretrained.py:818-846`）。
- 下载直接 `urlopen(url)` 后以最终目标名 `open(..., 'wb')` 写入，无 timeout、临时文件、原子 rename、文件锁或并发 owner。进程中断可能留下“看起来存在”的部分文件；有 expected hash 时下次会重下，无 expected hash 时可能永久复用残缺文件（`pretrained.py:848-861`）。整个文件被读入内存计算 hash，也会制造额外 CPU 内存峰值。
- HF 下载优先尝试对应 `.safetensors`，异常被静默吞掉后再尝试 `.bin/.pth`；最终路径交给 `torch.load` 或 safetensors loader。HF Hub 自身负责其 cache，但本项目调用层没有统一 manifest、权重摘要回传、下载 deadline 或取消（`pretrained.py:872-919`）。
- `download_pretrained()` 在 HF 可用且 cfg 同时有 `hf_hub` 时默认偏向 HF，因而同一 tag 的 URL 与 Hub 来源可能不是同一缓存/校验路径；`file` 配置则直接返回路径，不做存在性、hash 或格式校验（`pretrained.py:922-954`）。

### 25.7 失败路径、取消和释放终态收口

| 场景 | 当前实现 | 资源/安全结论 |
|---|---|---|
| 配置/模型不存在 | local-dir 缺目录/JSON/`model_cfg`、builtin 缺 config 抛 `FileNotFoundError`/`ValueError`/`RuntimeError`；未知用户 JSON 单文件可被扫描跳过 | 结构解析总体 fail-fast，但动态 registry 无版本/锁 |
| HF 配置成功、权重失败 | HF `create_model` 记录 warning 后允许 config-only；`require_pretrained` 再阻断 | 普通入口可能返回随机初始化模型，必须用 `create_model_from_pretrained` 或外层检查 |
| full 权重损坏/结构漂移 | loader/转换/strict load 抛错 | full 路径可见失败；不存在统一错误码或临时对象 rollback |
| tower 权重损坏/路径无效 | image/text/audio 分支多为 error/warning 后继续 | 可能返回部分加载或随机模型，不能仅看“create_model 返回”判成功 |
| 预处理/特殊 token 错误 | 特殊 token fail-fast；transform 参数断言/ValueError | 模型可能已分配，工厂没有 finally 清理 |
| URL 中断/超时 | `urlopen` 无 timeout，最终 cache 文件可能是半文件；无取消 API | 可能无界等待或残留，需外层下载器治理 |
| batch OOM/shape 错误 | 由 PyTorch/timm 异常直接暴露，无自动拆 batch/重试 | 不具备稳定可重试语义 |
| 预取提前结束 | NaFlex 设置 `stop` 并排空 queue，但 daemon producer 不显式 `join` | 不能宣称线程零残留 |
| DataLoader 结束 | 普通 DataLoader/WebLoader 依赖 iterator/对象生命周期；persistent workers 可跨 iterator 保留 | 没有统一 `close()`/worker 残留探针 |
| 分布式 rank/collective 异常 | 依赖 torch.distributed 报错/阻塞；源码搜索未见统一 `destroy_process_group()` | 无应用级 deadline、强杀和重启恢复 |
| remote sync 异常/宿主崩溃 | 正常尾部只 `terminate()` 同步进程，未统一 wait；异常路径没有总 finally | 可能残留子进程或远端半成品 |
| 模型/显存释放 | 源码没有 provider 级 `close/release`、`torch.cuda.empty_cache()` 或显存归还契约 | 依赖调用方 `del`/引用归零/进程退出；GPU 隔离应放到外部 execution unit |

因此，当前 OpenCLIP 能证明的是“部分输入/配置/权重错误可见失败、正常推理/训练路径存在、评估有 CPU feature spill 和 score chunk”；不能证明四种终态（成功、业务失败、取消/超时、崩溃/OOM）都做到资源零残留。

### 25.8 后续验收矩阵与剩余风险

| 子域 | L1 源码事实 | 当前核对真实执行 | 收口结论 |
|---|---|---|---|
| 模型/预训练注册 | 已逐条读取 `factory.py:38-143`、`pretrained.py:460-810` | 未调用依赖/未在线注册 | **已静态收口；动态覆盖、并发注册未验证** |
| full/tower 权重加载 | 已逐条读取 `factory.py:230-296,387-763` | 未加载真实 checkpoint | **加载顺序和失败差异已收口；真实格式兼容未验证** |
| preprocess/tokenizer | 已逐条读取 `factory.py:766-983,1188-1220`、`transform.py:17-59,367-518` | 未运行 PIL/timm/HF/audio transform | **元数据优先级和 NaFlex factory 边界已收口；依赖运行未验证** |
| inference/batch | 已逐条读取 `model.py:421-455,560-580,634-655`、zero-shot/metrics/train eval | 未做 CPU/GPU forward | **归一化、矩阵放大、类 batch、检索 chunk 已收口；吞吐/峰值未验证** |
| device/显存 | 已逐条读取 `factory.py:986-1015`、`task/base_task.py:135-157`、NaFlex config/data | 未做 dtype/GPU/OOM 探针 | **迁移和 dtype 语义已收口；显存预算/回收未实现** |
| cache/下载 | 已逐条读取 `pretrained.py:818-954` | 未联网、未断点/并发下载 | **校验和半文件风险已收口；HF/URL 边界未实测** |
| 失败/释放 | 已静态搜索 close/release/empty_cache/destroy/join 与主退出路径 | 未注入异常、取消、强杀、OOM | **缺口已证实；不能声称资源安全** |

后续只修改了本文件；旧 `细探-open_clip.md` 继续保留且未改写。后续若要把 OpenCLIP 接入平台，最低新增验收不是“能加载一个模型”，而是：canonical model/preprocess/tokenizer/checkpoint manifest、下载临时文件原子提交与并发锁、请求 deadline/cancel、batch/显存预算拒绝、provider 独立进程、四终态资源清理和失败后现场读回。

## 26. 2026-08-22 复审收口

### 26.1 当前版本与代码地图

- 源码根目录：`/Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/40_embedding_retrieval/open_clip`。
- 当前 `HEAD` 与 `origin/main`：`602d4af74f86df6f2ff81ba0f0a847b0b70ad2e5`；提交主题为 tiktoken 配置字段与词表缺口健壮性修复。
- 工作树仅有未跟踪 `.codegraph/` 与根 `ARCHITECTURE.md`；未修改源码 checkout。
- `codegraph status`：126 files、3,118 nodes、7,432 edges、9.44 MB，index up to date；Python 文件 123 个。
- 本轮按用户授权未使用 MCP；代码图仅用于导航，行为结论以源码和 Git 证据为准。

### 26.2 关键调用链复核

1. `create_model_and_transforms`（`src/open_clip/factory.py:1239`）调用 `create_model`（`:322`），后者在 checkpoint 路径上调用 `load_checkpoint`（`:251-296`）；模型、权重、设备精度和预处理在 factory 中完成装配。
2. `get_tokenizer`（`src/open_clip/factory.py:833`）独立解析 Simple/HF/SigLIP/TikToken 配置；特殊 token 验证与 variable text 约束不等于权重可用，调用方必须绑定 tokenizer、preprocess 和 checkpoint manifest。
3. `create_loss`（`src/open_clip/factory.py:1043`）按任务配置选择对比、SigLIP、CoCa、Distill、MaMMUT 等 loss；分布式 gather/chunked loss 的通信和显存边界仍由训练任务与 torch.distributed 决定。
4. 训练数据入口 `get_data`（`src/open_clip_train/data.py:1218`）与 dataset factory 组合 CSV/WebDataset/音频/NaFlex；变量文本 collate 与 token budget 只在对应数据路径生效，不能当作任意推理请求的 OOM 防护。
5. `load_checkpoint` 会转换第三方 state dict、调整 logit 参数和位置 embedding，最终 `model.load_state_dict(strict=...)`；full checkpoint 与 tower-only 覆盖的失败语义不同，不能只以 factory 返回对象判断完整权重成功。

### 26.3 L0-L4 状态

| 等级 | 本轮状态 | 证据 |
|---|---|---|
| L0 静态 | 完成 | Git SHA、远程 SHA、目录、依赖与 CodeGraph 已核对 |
| L1 源码调用链 | 完成 | factory/tokenizer/tower/loss/data/checkpoint/metrics 有 file:line 证据 |
| L2 单元测试 | 未执行 | 未安装依赖或运行 pytest |
| L3 集成 | 未执行 | 未加载真实 checkpoint、模型、GPU、音频或 WebDataset |
| L4 生产故障 | 未执行 | 未做下载中断、并发 cache、OOM、分布式 rank、worker/线程和显存残留验证 |

### 26.4 可复现验证命令

```bash
git fetch origin main
git rev-parse HEAD
git ls-remote origin refs/heads/main
codegraph status
codegraph explore "create_model create_model_and_transforms get_tokenizer TrainingTask contrastive loss get_data load_checkpoint"
git diff --check -- '开发文档/源码参考研究/项目/30_多模态与媒体分析/40_embedding_retrieval/open_clip/ARCHITECTURE.md'
```

本轮版本核对、CodeGraph 查询与 `git diff --check` 均已执行并退出 0；测试、模型下载、GPU/分布式和服务命令未执行，不得标记为通过。
