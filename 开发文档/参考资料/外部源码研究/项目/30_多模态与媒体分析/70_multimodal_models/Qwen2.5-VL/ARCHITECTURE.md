# Qwen2.5-VL / Qwen3-VL 源码架构

> 本文件是本项目唯一正式架构归档。项目源码参考库按只读方式研究；后续事实更新只维护本文件。
> 旧的 `细探-Qwen2.5-VL.md` 已人工核对并吸收；后续只维护本文件，不再把旧细探作为并行事实源。

## 1. 项目定位

本地目录名为 `Qwen2.5-VL`，但当前仓库 `README.md` 的主线已经是 **Qwen3-VL**。仓库仍保留 Qwen2.5-VL 的微调路径和向后兼容的 `qwen-vl-utils`，因此准确定位是：以 Qwen3-VL 为当前主线、兼容 Qwen2.5-VL/Qwen2-VL 训练与推理流程的通义视觉语言模型参考仓库。

项目不包含模型权重，也没有独立的模型服务后端；它提供的是模型使用示例、视觉输入处理工具、微调框架、评测脚本、Cookbook 和 Gradio WebUI。实际模型由 `transformers`、vLLM 或 SGLang 从 Hugging Face/ModelScope 路径加载。

主要能力边界：

- 图像、视频与多轮文本交错输入；
- OCR、文档/版面解析、关键信息抽取；
- 2D/3D grounding、空间理解、长视频和长文档理解；
- GUI/移动端视觉 agent、视觉编码和多模态代码生成示例；
- Transformers 本地推理、vLLM/SGLang 部署、DashScope OpenAI-compatible API；
- Qwen2-VL、Qwen2.5-VL、Qwen3-VL 及 Qwen3-VL MoE 的监督微调/LoRA 路径。

仓库根许可证文件为 Apache License 2.0。模型权重、在线 API 和第三方运行时的具体许可与服务条款不由根目录 `LICENSE` 单独覆盖，接入前需分别核对对应模型卡、API 和依赖许可。

## 2. 版本基线与现场核对

- 本地分支：`main`。
- 本地提交：`96588727e44c78b25ba03ea03b8e12f7e64fd0da`。
- 本地提交时间：`2026-01-30T12:47:30+08:00`。
- 远程：`https://github.com/QwenLM/Qwen2.5-VL.git`，远程默认分支 `main`。
- 现场 `git ls-remote origin HEAD refs/heads/main refs/heads/master` 返回的 `HEAD`/`main` 同为 `96588727e44c78b25ba03ea03b8e12f7e64fd0da`，未发现远程领先，不需要通过 `127.0.0.1:4780` 建立独立远程快照。
- 建档前工作树存在未跟踪细探材料；本次只新增本正式文档，未改源码、依赖、测试或配置，旧细探已在人工收口后清理。

重要版本事实：`README.md` 当前内容在顶部和示例中使用 Qwen3-VL、`Qwen3-VL-235B-A22B-*` 与 `transformers>=4.57.0`；`qwen-vl-finetune` 的 `train_qwen.py` 同时显式导入 `Qwen2VLForConditionalGeneration`、`Qwen2_5_VLForConditionalGeneration`、`Qwen3VLForConditionalGeneration`、`Qwen3VLMoeForConditionalGeneration`。不能仅依据目录名把当前仓库描述成纯 Qwen2.5-VL 实现。

## 3. 总体流程图

```text
用户消息 / 训练标注 / 评测样本
  ├─ image: 本地路径、file://、HTTP(S)、data:image、PIL.Image
  ├─ video: 本地路径、file://、HTTP(S)、帧列表
  └─ text: 对话、<image>/<video> 占位符、任务提示
                │
                ▼
  Transformers AutoProcessor.apply_chat_template
                │
                ├─ qwen_vl_utils.process_vision_info
                │    ├─ extract_vision_info
                │    ├─ fetch_image → smart_resize → RGB/PIL
                │    └─ fetch_video → torchvision/decord/torchcodec
                │         → smart_nframes → 像素/帧数限制 → Tensor(T,C,H,W)
                │
                ▼
  image/video processor 生成视觉网格与多模态输入
  ├─ image_grid_thw / video_grid_thw
  ├─ pixel_values / pixel_values_videos
  └─ Qwen2.5-VL/Qwen3-VL 的 3D M-RoPE position_ids
                │
       ┌────────┼──────────┬─────────────┐
       ▼        ▼          ▼             ▼
  HF generate  vLLM LLM   SGLang       DashScope
  + streamer    + batch    Engine       OpenAI API
       │        │          │             │
       └────────┴──────────┴─────────────┘
                ▼
  文本生成 / OCR / grounding / 视频问答 / agent 响应

训练旁路：标注 JSON/JSONL → LazySupervisedDataset → labels/position_ids
  → HuggingFace Trainer（可选 flash-attn、packing、LoRA、DeepSpeed）→ checkpoint
评测旁路：MMMU/VideoMME/RealWorldQA/ODinW-13/MathVision → vLLM 批量推理
  → JSONL 结果 → judge/eval_utils 评分
```

## 4. 真实目录地图与分层

```text
Qwen2.5-VL/
├── README.md                         # 当前主线能力、Quickstart、部署和评测说明
├── LICENSE                           # Apache-2.0（代码仓库许可）
├── requirements_web_demo.txt         # Gradio/HF/torch WebUI 依赖
├── web_demo_mm.py                    # Gradio 多模态对话入口，HF/vLLM 双后端
├── qwen-vl-utils/
│   ├── pyproject.toml                 # qwen-vl-utils 0.0.14，Python 包边界
│   └── src/qwen_vl_utils/
│       └── vision_process.py          # 图像/视频读取、缩放、采样和视觉信息编排
├── qwen-vl-finetune/
│   ├── README.md                      # 数据格式、训练参数和启动说明
│   ├── qwenvl/data/
│   │   ├── __init__.py                # 数据集别名、采样比例和路径占位符
│   │   ├── data_processor.py          # 标注→对话→processor→labels/位置编码
│   │   └── rope2d.py                  # Qwen2/Qwen2.5/Qwen3 三套 M-RoPE
│   ├── qwenvl/train/
│   │   ├── argument.py                # Model/Data/Training dataclass 参数契约
│   │   ├── train_qwen.py              # 模型选择、冻结/LoRA、Trainer 训练入口
│   │   └── trainer.py                 # FlashAttention、mask、optimizer monkey patch
│   ├── scripts/                       # DeepSpeed、SFT、LoRA 启动脚本
│   ├── tools/                         # bbox 转换、数据打包、图像完整性检查
│   └── demo/                          # 训练示例图片、视频和标注
├── evaluation/
│   ├── mmmu/                          # MMMU 加载、vLLM 批推理和 judge 评测
│   ├── VideoMME/                     # 视频多选题推理/评测，含字幕和视频采样
│   ├── RealWorldQA/                  # 真实世界图像问答
│   ├── ODinW-13/                     # 检测/grounding 相关评测
│   └── MathVision/                   # 视觉数学评测
├── cookbooks/                         # OCR、文档、视频、grounding、agent、代码等 Notebook
│   └── utils/                         # 视觉 agent、代码执行/评测辅助工具
├── docker/                            # Web demo/Docker 镜像脚本与 Dockerfile
└── ARCHITECTURE.md                   # 本项目唯一架构事实源
```

现场统计的一级模块文件数（包含各自子目录文件，不含 `.git`）：`qwen-vl-utils` 7、`qwen-vl-finetune` 27、`evaluation` 48、`cookbooks` 66、`docker` 2。Notebook、视频和图片等资源不等同于可导入源码模块。

## 5. 核心数据模型与状态

### 5.1 推理消息模型

推理入口统一接受消息列表：`[{"role": "user", "content": [...]}]`。`content` 中使用 `{"type": "image", "image": ...}`、`{"type": "video", "video": ...}`、`{"type": "text", "text": ...}`；兼容示例也展示了直接使用 `image`/`video` 键。视觉资源可以是本地路径、`file://`、HTTP(S)、base64 data URL、PIL 图像，视频还可以是帧路径列表。

`processor.apply_chat_template` 把消息转为模型文本模板和视觉占位符。`process_vision_info` 返回 `image_inputs`、`video_inputs` 以及可选的 `video_kwargs`；vLLM 入口进一步封装成：

- `prompt`：已套 chat template 的文本；
- `multi_modal_data`：按 `image`/`video` 键组织视觉 Tensor；
- `mm_processor_kwargs`：视频帧采样等处理参数。

### 5.2 视觉处理参数

`qwen_vl_utils.vision_process` 的关键约束为：`IMAGE_MIN_TOKEN_NUM=4`、`IMAGE_MAX_TOKEN_NUM=16384`、`VIDEO_MIN_TOKEN_NUM=128`、`VIDEO_MAX_TOKEN_NUM=768`、默认 `FPS=2.0`、`FRAME_FACTOR=2`、默认模型序列长度 `MODEL_SEQ_LEN=128000`（可由环境变量覆盖）。`smart_resize` 维持纵横比并把尺寸对齐到 `image_patch_size * SPATIAL_MERGE_SIZE`，默认 patch size 14，因此 Qwen2.5-VL 的图像尺寸通常按 28 对齐。

`fetch_video` 支持 `torchcodec`、`decord`、`torchvision` 三种 backend：优先 `FORCE_QWENVL_VIDEO_READER` 环境变量，其次自动探测 `torchcodec`、`decord`，最后回退 `torchvision`；读取失败还会回退到 `torchvision`。视频帧数必须按 `FRAME_FACTOR` 对齐，支持 `fps` 或 `nframes` 二选一，支持 `video_start`/`video_end`，并用 `min_pixels`、`max_pixels`、`total_pixels` 控制视觉 token 预算。

### 5.3 训练标注模型

训练样本由 JSON/JSONL 记录组成：`image` 或 `video`（单值或数组）、`conversations`。对话 turn 使用 `from: human|gpt` 和 `value`；用户文本中的 `<image>`/`<video>` 必须与媒体数量一一对应，答案不应出现这些特殊 token。`data/__init__.py` 用数据集别名映射 `annotation_path`、`data_path`，名称尾部 `%50` 等表示采样率。

`preprocess_qwen_visual` 的关键输出是 processor 的 `input_ids`、视觉张量/网格、以及把 assistant 回复区间写入的 `labels`；非 assistant token 使用 `IGNORE_INDEX=-100`。`LazySupervisedDataset` 支持 lazy 取样、数据 packing、图像/视频像素参数更新和失败重试：当前样本最多三次，随后尝试邻近样本，最终失败才抛错。

### 5.4 多模态位置编码

`rope2d.py` 暴露 `get_rope_index_2`、`get_rope_index_25`、`get_rope_index_3`，根据 `image_grid_thw`、`video_grid_thw` 和 `second_per_grid_ts` 生成形状为 `(3, batch, sequence)` 的 position ids 与 `mrope_position_deltas`。Qwen2.5-VL 使用视频时间网格与 `second_per_grid_t` 计算时间轴；Qwen3-VL 以 timestamp 思路拆分视频 temporal grid。训练数据处理根据 `data_args.model_type` 选择实现。

## 6. 关键调用链

### 6.1 WebUI 推理

`main` → `_get_args` → `_load_model_processor` → `_launch_demo`。`_get_args` 暴露 `--checkpoint-path`、`--backend {hf,vllm}`、`--cpu-only`、`--flash-attn2`、`--server-port`、`--server-name`、`--gpu-memory-utilization`、`--tensor-parallel-size` 等 CLI 参数。

- vLLM 分支设置 `VLLM_WORKER_MULTIPROC_METHOD=spawn`，构造 `LLM`，加载 `AutoProcessor`。
- HF 分支用 `AutoModelForImageTextToText.from_pretrained`，可选 `device_map=auto/cpu` 和 `flash_attention_2`。
- `add_file` 将上传文件放入 `task_history`；`predict` 调用 `_transform_messages`，按扩展名区分视频/图像。
- vLLM 分支经 `_prepare_inputs_for_vllm` 调 `process_vision_info`，用 `SamplingParams(max_tokens=1024)` 生成；HF 分支使用 `TextIteratorStreamer` 和后台 `Thread` 流式生成。
- `_parse_text` 将 Markdown 代码块转成 HTML；`_remove_image_special` 移除 `<ref>` 与 `<box>` 标记；`reset_state` 清空历史并执行 GPU cache 回收。
- Gradio 通过 `demo.queue().launch` 在默认 `127.0.0.1:7860` 提供页面，可用 `--share`/`--inbrowser` 改变行为。

### 6.2 Transformers 直接推理

README 的 Quickstart 使用 `AutoModelForImageTextToText.from_pretrained` 与 `AutoProcessor.from_pretrained`，调用 `processor.apply_chat_template(..., return_dict=True, return_tensors="pt")`，将输入移动到 `model.device`，再 `model.generate`，最后裁剪输入 token 并由 `processor.batch_decode` 解码。多图、视频、batch、fps、`num_frames`、像素预算和 `qwen_vl_utils` 兼容用法均在 README 中给出。

### 6.3 vLLM/SGLang/HTTP API

README 的 vLLM 在线服务以 `vllm serve` 暴露 OpenAI-style `/v1` 服务，可通过 `tensor-parallel-size`、expert parallel、`--media-io-kwargs`、`--max-model-len` 和 YaRN rope scaling 配置；客户端使用 `openai.OpenAI` 的 `chat.completions.create`，消息内容使用 `image_url` 或 `video_url`。SGLang 入口为 `python -m sglang.launch_server`，离线示例使用 `Engine.generate`。

DashScope 兼容 API 使用 `OpenAI(api_key=..., base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")`，模型名示例为 `qwen3-vl-235b-a22b-instruct`。这些是外部服务边界，不是仓库内实现的 API server。

### 6.4 微调链路

`train_qwen.py:train` → `HfArgumentParser` 解析 `ModelArguments`、`DataArguments`、`TrainingArguments` → 按模型路径选择四种 Transformers model class → `AutoProcessor`/`AutoTokenizer` → `replace_qwen2_vl_attention_class`（packing/flatten 时）→ `set_model` 或 PEFT LoRA → `make_supervised_data_module` → `Trainer` → checkpoint resume/train/save。

模型路径含 `qwen3` 且模型名含 `a` 时选择 `Qwen3VLMoeForConditionalGeneration`，普通 `qwen3` 选择 `Qwen3VLForConditionalGeneration`，含 `qwen2.5` 选择 `Qwen2_5_VLForConditionalGeneration`，否则选择 `Qwen2VLForConditionalGeneration`。参数开关分别控制 `visual`、`visual.merger`、`language_model` 与 `lm_head` 是否可训练；`lora_enable` 时冻结全模型并对 `q_proj`、`k_proj`、`v_proj`、`o_proj` 应用 LoRA。

`trainer.py` 将 Transformers attention 替换为基于 `flash_attn_varlen_func` 的 `flash_attention_forward`，并把 Qwen2/Qwen2.5/Qwen3（含 MoE）的 attention forward 与 causal mask 做 monkey patch；`create_optimizer` 为 language、vision tower、merger 分配独立学习率和 weight decay 分组。该路径强依赖 CUDA/FlashAttention/Transformers 版本契约，不能在未满足环境时直接视为通用 CPU 训练方案。

### 6.5 评测链路

`evaluation/mmmu/run_mmmu.py`、`VideoMME/run_videomme.py` 等脚本共享 `AutoProcessor` + `qwen_vl_utils.process_vision_info` + vLLM 批量生成模式：加载数据集 → 构造标准消息 → 生成 `prompt`/`multi_modal_data` → `LLM.generate` → 写 JSONL（含 `annotation`、`messages`、原始/清理后的生成结果）→ `eval_utils`/judge 评分。VideoMME 额外支持 `duration`、字幕、fps、帧数和像素预算。评测数据、LMUData 等路径是外部前置条件。

## 7. 技术栈与依赖边界

| 层 | 真实组件/版本证据 | 边界 |
|---|---|---|
| 语言 | Python；`qwen-vl-utils/pyproject.toml` 要求 `>=3.8` | 以脚本和 Python package 为主，无独立前端工程 |
| 模型/处理 | PyTorch、Hugging Face `transformers`、`AutoProcessor`、`AutoModelForImageTextToText` | 权重由外部 Hugging Face/ModelScope 提供 |
| 视觉处理 | Pillow、NumPy、Requests、TorchVision；可选 `decord`/`torchcodec` | 视频解码受 FFmpeg/平台/第三方版本影响 |
| 推理部署 | vLLM、SGLang、Transformers generate | vLLM/SGLang 需要独立 GPU 运行时；README 推荐 vLLM |
| WebUI | `gradio==5.49.1`、`gradio_client==1.13.3` | 仅示例 WebUI，不是生产网关 |
| 训练 | Hugging Face `Trainer`、Accelerate、DeepSpeed、PEFT、FlashAttention、Triton | `qwen-vl-finetune/README.md` 给出 GPU 版本组合，需按模型/硬件复核 |
| API 客户端 | `openai` Python client、DashScope OpenAI-compatible endpoint | API key、网络、第三方服务计费/限流在仓库外 |
| 评测 | pandas、NumPy、tqdm、各任务 `requirements.txt`、judge/eval_utils | 数据集与结果文件不随代码完整提供 |
| 容器 | Dockerfile/脚本，示例 `qwenllm/qwenvl:qwen3vl-cu128` | 依赖 NVIDIA GPU、驱动与 CUDA 兼容 |

`qwen-vl-utils` 包自身的 `pyproject.toml` 声明版本 `0.0.14`，核心依赖为 `requests`、`pillow`、`av`、`packaging`，可选 `decord`；源码实际还直接使用 `torch`、`torchvision`、`numpy`，开发依赖列出 `torch`、`torchvision`。根 `requirements_web_demo.txt` 还固定了一个 Transformers Git commit、`torch`、`torchvision`、`accelerate` 和可选 `flash-attn`。

## 8. API、CLI、协议和插件边界

- **Python SDK/库**：`qwen_vl_utils.process_vision_info` 是视觉输入适配边界；`AutoProcessor`/Transformers 是模型加载与生成边界。
- **CLI**：`python web_demo_mm.py -c ... [--backend hf|vllm]`；微调通过 `torchrun` 调 `qwen-vl-finetune/qwenvl/train/train_qwen.py`；评测脚本通过各自 argparse 参数运行。
- **HTTP**：vLLM/SGLang 提供 OpenAI-style `/v1/chat/completions`；DashScope 提供兼容模式 endpoint。仓库没有自建鉴权、租户、任务队列、持久化或审计层。
- **Gradio 事件协议**：上传按钮、提交、重试、清空历史绑定到 `task_history` 和 `_chatbot`，状态只在 WebUI 进程内存中维护。
- **视觉 agent 工具协议**：`cookbooks/utils/agent_function_call.py` 注册 `mobile_use`、`computer_use` 等 `qwen_agent.tools.base.BaseTool` 工具；该文件主要定义工具 schema 和调用分派，具体设备动作方法保留 `NotImplementedError`，不能视为仓库内完整设备执行器。
- **数据协议**：训练 annotation JSON/JSONL、`<image>`/`<video>` 对齐约束、评测 JSONL 结果格式是最重要的可复用契约。

## 9. 测试、验证与未执行事项

仓库没有独立的常规 `tests/` 测试套件。现场文件检索只发现 `cookbooks/utils/multimodal_coding/test_mmcode.py`，它是多模态代码生成结果的运行/超时/隔离评测工具，不是完整单元测试覆盖。`qwen-vl-finetune/tools/check_image.py` 用于训练数据图像完整性检查，评测目录中的 `eval_*.py` 是任务评分脚本。

本次只做源码、README、依赖、入口、数据模型、API/CLI、评测脚本、许可证、Git 版本和远程版本的静态核对；未安装依赖、未下载权重、未启动 Gradio/vLLM/SGLang、未运行 GPU 推理/微调/完整评测，也未修改源码、依赖、测试或配置。原因是本仓库按只读源码参考归档，且上述路径需要外部模型权重、数据集、GPU/CUDA 与服务凭证。

可执行但本次未执行的最小验证方向：

1. 仅验证 Python 语法/导入时需先建立隔离环境并满足对应依赖；不能把未安装依赖导致的导入失败误判成源码故障。
2. 视觉处理应覆盖本地/URL/base64 图像、三种视频 backend、视频时间区间、`fps`/`nframes` 互斥、像素上限和 patch 对齐。
3. 训练应覆盖单图、多图、视频、packing、LoRA、三种 `get_rope_index` 分支以及坏样本重试。
4. 部署应分别验证 Transformers、vLLM OpenAI-compatible、SGLang、DashScope 四条边界，并记录 GPU、CUDA、Transformers、vLLM 版本。

## 10. 风险、未确认项与后续复核点

- **名称漂移**：目录和仓库 URL 使用 Qwen2.5-VL，README 主体已转向 Qwen3-VL；后续引用必须同时标明目标模型系列和当前提交。
- **权重/代码版本耦合**：`AutoProcessor`、模型 class、视觉 patch size、`video_metadata`、vLLM 和 `transformers` 版本必须匹配；README 明确提示 `qwen-vl-utils` 对 Qwen2.5-VL 与 Qwen3-VL 的调用参数存在差异。
- **资源风险**：长视频、长文档和高 `max_pixels` 会显著增加显存与序列长度；`MODEL_SEQ_LEN`、`total_pixels`、vLLM `max_model_len` 需要联动配置。
- **平台风险**：`decord` 在非 Linux 平台安装可能困难；`torchcodec` 需要 FFmpeg；FlashAttention、vLLM、SGLang 主要面向 CUDA 环境。
- **训练实现风险**：`trainer.py` 依赖 Transformers 内部模块并进行 monkey patch，升级 Transformers 时需重新验证 attention 签名、mask、cache 和模型类。
- **数据风险**：训练数据路径在 `qwen-vl-finetune/qwenvl/data/__init__.py` 中只是占位符；媒体与占位符数量不一致、缺图、错误 JSON/JSONL 会在数据处理阶段失败。
- **服务边界风险**：仓库示例的 OpenAI-compatible API 不包含生产级鉴权、限流、审计、队列、租户隔离或结果持久化，接入系统平台必须由外部服务层补齐。
- **安全风险**：WebUI 的 `--share` 会创建公开分享链接；上传媒体、远程 URL、模型输出和 Cookbook 中的代码执行工具均应置于隔离和内容安全策略内。
- **待复核**：若后续要落地 Qwen2.5-VL 而非仅做源码参考，应锁定具体 checkpoint、Transformers/vLLM/qwen-vl-utils 版本、GPU/CUDA 组合，并以小样本图像/视频回归验证视觉网格和输出格式。

## 11. 对系统工程平台的可借鉴边界

可吸收的不是整个仓库，而是以下边界契约：

1. **统一多模态消息模型**：保留 `role`/`content` 与 image/video/text typed content，向上层屏蔽文件、URL、base64 和帧列表差异。
2. **独立视觉预处理层**：将尺寸、帧数、像素 token 预算、视频 backend 和 metadata 作为可观测输入处理，不把媒体解码散落在业务服务。
3. **推理 Provider 适配层**：把 Transformers、本地 vLLM、SGLang、DashScope 的请求/响应差异隔离在 provider 边界；业务只依赖统一生成结果和错误模型。
4. **训练/评测数据契约**：显式校验媒体占位符与文件一一对应，保留原始消息、模型原始输出和清理后结果，便于追溯。
5. **资源与安全隔离**：视觉模型、GPU、远程媒体和 agent 工具放在独立进程/任务边界；不要把本仓库的 Gradio demo、设备工具或模型加载逻辑直接复制进生产底座。

这些属于研究结论，不代表已经在系统工程平台实现；本次未改动任何上层业务或平台源码。

## 12. 证据路径索引

- 主说明与部署示例：`README.md`
- WebUI 入口：`web_demo_mm.py` 的 `_get_args`、`_load_model_processor`、`_prepare_inputs_for_vllm`、`_launch_demo`、`main`
- 视觉处理：`qwen-vl-utils/src/qwen_vl_utils/vision_process.py` 的 `smart_resize`、`smart_nframes`、`fetch_image`、`fetch_video`、`get_video_reader_backend`、`process_vision_info`
- 训练参数：`qwen-vl-finetune/qwenvl/train/argument.py`
- 数据注册与采样：`qwen-vl-finetune/qwenvl/data/__init__.py` 的 `data_dict`、`parse_sampling_rate`、`data_list`
- 数据预处理：`qwen-vl-finetune/qwenvl/data/data_processor.py` 的 `_build_messages`、`preprocess_qwen_visual`、`LazySupervisedDataset`
- 位置编码：`qwen-vl-finetune/qwenvl/data/rope2d.py` 的 `get_rope_index_2`、`get_rope_index_25`、`get_rope_index_3`
- 训练入口：`qwen-vl-finetune/qwenvl/train/train_qwen.py` 的 `train`、`set_model`、`safe_save_model_for_hf_trainer`
- 训练扩展：`qwen-vl-finetune/qwenvl/train/trainer.py` 的 `flash_attention_forward`、`replace_qwen2_vl_attention_class`、`create_optimizer`
- 评测入口：`evaluation/mmmu/run_mmmu.py`、`evaluation/VideoMME/run_videomme.py` 及各评测目录的 `dataset_utils.py`、`eval_utils.py`
- Agent 工具边界：`cookbooks/utils/agent_function_call.py` 的 `MobileUse`、`ComputerUse`
- 此前历史细探（已人工吸收并清理）

## 13. 后续：通用底座映射与裁决

> 当前核对只把源码事实映射到系统工程平台的公共边界，不把本仓库改造成平台实现。源码、依赖、测试、配置、README、Git 均未修改；本节是后续增量结论。`细探-Qwen2.5-VL.md` 当前不在目标目录或其父级源码参考库中，且本文件第 4 行记录其已人工吸收并清理，因此当前核对以该唯一正式文档和当前源码复核为准，不虚构旧细探内容。

### 13.1 一句话裁决

Qwen2.5-VL 的媒体规范化、解码、缩放、帧采样、视觉 token 预算应收敛为 **多模态输入支持库**；Qwen 的消息模板、`image_grid_thw`/`video_grid_thw`、M-RoPE 和模型任务编排应收敛为 **视觉模型模块**；`Transformers`、vLLM、SGLang、DashScope 以及权重/设备加载应收敛为 **模型提供者**；会话、租约、队列、GPU/进程监督、超时取消、崩溃恢复、资源释放和证据链必须由 **运行核心** 统一治理。`web_demo_mm.py`、训练脚本和评测脚本只能是适配层/示例入口，不能成为第二套核心。

### 13.2 源码事实到平台职责映射表

| 源码事实 | 证据 | 平台归属 | 后续裁决 |
|---|---|---|---|
| `role`/`content` 中的 typed image/video/text、路径/URL/base64/PIL 输入 | `qwen-vl-utils/.../vision_process.py:483-522`；`README.md:162-193, 441-475` | 多模态输入支持库 | 吸收为统一媒体消息契约；远程 URL、data URL、帧列表只能在这一入口归一化，业务不得自行判断扩展名。 |
| `fetch_image`、RGB 转换、`smart_resize`、patch 对齐和长宽比约束 | `vision_process.py:56-141` | 多模态输入支持库 | 吸收为可观测的图像输入能力；记录原始尺寸、目标尺寸、patch/merge 参数和实际视觉 token 估算。 |
| `fetch_video`、`smart_nframes`、`video_start/end`、fps/nframes 互斥 | `vision_process.py:144-181, 234-289, 403-480` | 多模态输入支持库 | 吸收为视频采样能力；采样策略、帧索引和 backend 进入结果元数据，不由模型模块重复实现。 |
| `torchcodec`→`decord`→`torchvision` 探测及异常回退 | `vision_process.py:380-400, 408-415` | 输入支持库 + 受管 provider | 升级为显式 backend 注册/健康检查；禁止隐藏 fallback，实际使用 backend、失败原因和回退次数须入证据。 |
| `AutoProcessor.apply_chat_template`、视觉占位符、processor 输出 | `web_demo_mm.py:178-198, 220-233`；`data_processor.py:202-241` | 视觉模型模块 | 模块负责 Qwen 消息/模板/网格契约；具体 `transformers` Processor 的载入和版本兼容放模型提供者。 |
| `image_grid_thw`、`video_grid_thw`、`pixel_values`、`pixel_values_videos`、M-RoPE | `data_processor.py:389-440, 461-517`；`rope2d.py:125-333` | 视觉模型模块 | 吸收为模型适配契约；网格与 token 数必须和媒体顺序一一对应，不能让 provider 对象穿透上层。 |
| 视觉 tower/merger 与 LLM forward、FlashAttention monkey patch | `train_qwen.py:67-90, 119-180`；`trainer.py:111-250, 494-511` | 视觉模型模块 + 模型提供者 | 模块描述“视觉编码→语言推理”的语义；Transformers 内部类、attention patch、FlashAttention 只留在 Qwen provider，禁止平台公共核心依赖其内部符号。 |
| `model.generate`、vLLM `LLM.generate`、SGLang Engine、DashScope OpenAI-compatible | `web_demo_mm.py:206-239`；`ARCHITECTURE.md:152-160` | 模型提供者 | 统一为一个 `视觉模型.生成` 契约；provider 只负责请求翻译、权重/引擎调用、结果转换和可重试错误。 |
| 图像/视频 min/max pixels、`MODEL_SEQ_LEN`、fps/帧数和 `max_model_len` | `vision_process.py:24-37, 448-455`；`README.md:336-409`；评测脚本 `run_mmmu.py:380-402`、`run_videomme.py:326-352` | 输入支持库制定预算；运行核心执行预算；provider 报告实际消耗 | 升级为统一预算对象：文本 token、图像 token、视频 token、生成 token、总上下文和显存预算分开记录；不能只信任 CLI 默认值。 |
| `from_pretrained`、`device_map`、dtype、tensor parallel、GPU utilization | `web_demo_mm.py:66-105`；`train_qwen.py:103-139`；评测脚本 `run_mmmu.py:167-181` | 模型提供者加载；运行核心资源治理 | 权重路径/摘要、模型类、dtype、GPU 拓扑和并行度必须成为 provider 运行指纹；GPU 许可、并发和释放由运行核心持有。 |
| HF batch padding、训练 collator、vLLM `llm.generate(all_inputs)` | `README.md:288-333`；`data_processor.py:534-675`；`run_mmmu.py:183-228` | 视觉模型模块编排批次；provider 执行批处理；运行核心限流 | 吸收“逻辑请求批次”和“provider 动态批次”两层概念；批次不得绕过单请求预算/租约。 |
| Gradio `demo.queue().launch`、vLLM/SGLang `/v1`、DashScope endpoint | `web_demo_mm.py:330-368`；`ARCHITECTURE.md:156-160` | 外部服务适配层 + 运行核心网关 | `web_demo_mm.py` 只能作为 demo；生产入口由统一网关承载鉴权、会话、幂等、限流、审计和结果持久化。 |
| 训练/评测数据注册、坏样本重试、JSONL 输出 | `data_processor.py:244-387`；`run_mmmu.py:230-254` | 视觉模型模块的训练/评测适配器 | 保留为离线工作包；重试策略不能复制成在线推理的隐式 fallback。 |

### 13.3 目标单链路（唯一 owner）

```text
L0 外部调用方/统一网关
  → 结构化请求：会话id、幂等键、媒体消息、任务、预算、截止时间
L1 视觉模型模块公开入口
  → 校验任务与 typed content；调用唯一“多模态输入.准备”能力
L2 多模态输入支持库 + 模型提供者注册表
  → 规范化/解码/采样/预算/网格元数据
  → 选择唯一 Qwen 视觉模型 provider（Transformers | vLLM | SGLang | DashScope）
L3 运行核心
  → 建立会话与资源租约；排队/限流；监督 provider 进程、线程、GPU、句柄和流
  → 执行取消/超时/OOM/崩溃收敛，记录统一结果、事件和释放证据
L4 受管外部边界
  → 权重仓库、PyTorch/Transformers、解码器、CUDA/GPU、vLLM/SGLang、HTTP API
  → 返回文本/结构化视觉结果/诊断；沿同一链路回收资源并关闭租约
```

固定规则：一个原子功能一个能力 id、一个契约 owner、一个公开入口、一条注册/调用路径。`web_demo_mm.py`、`evaluation/*/run_*.py`、`qwen-vl-finetune/*` 不得再各自实现媒体解析、预算、provider 选择或资源治理；历史键只能在唯一入口归一化。模型 provider 的差异是策略，不是第二套领域流程。

### 13.4 会话、租约与资源生命周期补充

源码现状只有 WebUI 进程内 `task_history`（`web_demo_mm.py:241-327`），没有持久会话、租约、所有者、心跳、幂等键、取消令牌或崩溃恢复；`reset_state` 只清内存历史并调用 `gc.collect()`/`torch.cuda.empty_cache()`，不能证明模型、线程、解码器和 GPU 资源已释放。因此下表是平台接入的必补契约，不是仓库已有实现：

| 资源/状态 | 创建与持有 | 正常完成 | 失败/超时/取消 | 崩溃/OOM后的硬要求 |
|---|---|---|---|---|
| 会话 | L0 生成 `会话id`、调用者/项目/权限和过期时间；运行核心持久化状态 | 结果落账，短期保留诊断引用 | 幂等转为失败/取消，不重复生成 | 按心跳/进程身份判断死亡，禁止旧令牌复活；恢复只读状态和未完成任务 |
| 推理租约 | 运行核心以 `会话id+操作id+资源id` 原子占用模型/GPU/进程 | provider 返回后先落结果，再释放租约 | 截止时间到先发取消，再回收；释放必须幂等 | 心跳中断或宿主死亡自动回收，留下租约回收证据，不能永久占 GPU |
| 原始媒体/下载临时文件 | 输入支持库创建临时文件或 HTTP response；拥有者明确 | 关闭 response/file，删除临时物 | 任何异常走 `finally`；取消下载必须关闭连接 | 进程组清理后扫描临时目录/打开句柄，残留要可定位和重试清理 |
| 解码器/线程池 | `torchcodec`/`decord`/`torchvision` 和 `ThreadPoolExecutor` 在输入支持库内创建 | 收齐帧后显式释放 executor/decoder 引用 | backend fallback 不得遗留失败 decoder；线程异常汇总到请求结果 | 子进程隔离 C/CUDA 解码器，强杀后验证无子进程、线程和句柄残留 |
| Processor/视觉张量/网格 | provider/模块创建 CPU/GPU tensor，按请求持有 | 结果转换后释放临时 tensor/cache | OOM 时禁止继续持有批次；降低预算只允许新尝试且有界 | provider 崩溃由独立进程隔离；运行核心回收 CUDA 上下文/显存并记录峰值 |
| 权重/模型引擎 | provider 加载 checkpoint；租约绑定模型版本、摘要、GPU 拓扑 | 常驻模型按池策略保留，临时模型卸载 | 载入失败不伪造可用；超时不强行复用未知状态引擎 | 子进程/worker 崩溃后隔离旧实例，重启次数有界，旧租约全部失效 |
| 流式输出/后台线程 | HF `TextIteratorStreamer(timeout=20.0)` 与 `Thread(model.generate)`；vLLM 生成迭代器 | 发送终止事件、join/关闭流、保存完整响应 | 取消需向 provider 传递停止信号并排空/关闭迭代器；超时不得只丢客户端 | 断线、线程异常和 provider 非零退出均要完成请求终态和资源回收 |
| 结果/证据 | 模块生成统一结果，运行核心写状态/事件，评测器写 JSONL | 结果与输入摘要、provider、预算、版本指纹关联 | 失败也写错误码、可重试、阶段和证据，不覆盖原始失败 | 重启后可从权威状态恢复，禁止只依赖内存 `task_history` |

### 13.5 失败、超时、取消、OOM、崩溃矩阵

| 场景 | 当前源码行为 | 平台统一语义与等级 |
|---|---|---|
| 非法媒体、长宽比超过 200、fps 与 nframes 同时给、占位符/媒体数量不符 | `ValueError`/`assert`，训练入口还会重试样本 | L1 参数错误；不重试、不 fallback；返回稳定错误码和校验位置。训练样本重试必须与在线请求能力隔离。 |
| HTTP 图像失败、base64/本地文件损坏 | `fetch_image` 直接抛异常，无统一错误码 | L2 输入 provider 失败；可重试性由错误类型决定，response/file 必须释放。 |
| 视频 backend 失败 | 先警告再回退 `torchvision`；回退失败才抛出 | L2 允许一次显式、可观测 fallback；记录首错/最终 backend；禁止无限重试。 |
| 当前训练样本无法读取 | 当前样本最多 3 次，随后邻近样本最多 3 次，最后抛出 | 仅离线数据适配器使用；在线推理不允许静默换用户媒体。 |
| provider 缺失、权重/模型类不匹配 | vLLM 缺失在启动时 `ImportError`；HF/vLLM 由 CLI 明确选择 | provider 不可用；启动探针失败，不降级为另一个 provider，除非策略显式声明且记录。 |
| HF 流式等待超过 20 秒 | `TextIteratorStreamer` 配置 timeout，但 `predict` 没有取消/异常收敛 | 运行核心硬截止；向 provider 发 cancel，join 后返回 TIMEOUT；不能留下后台生成线程。 |
| GPU OOM、上下文/视觉 token 超限 | 源码没有统一捕获、降级或显存租约；`empty_cache()` 只在清空 WebUI 状态时执行 | 运行核心将 OOM 与普通业务失败分开；释放批次/GPU 租约，按预算策略有界重试一次或拒绝，不伪造成功。 |
| vLLM/SGLang worker、C/CUDA decoder 崩溃 | `spawn` 只设置 multiprocessing 方法；仓库没有 supervisor/重启/残留审计 | L3 进程监督器隔离 provider；记录退出码/信号/模型指纹，killpg 回收进程树，有限重启并使旧会话/租约失效。 |
| 客户端断线、重复提交 | demo 只依赖 Gradio 状态；没有断线取消和幂等键 | 运行核心以操作 id 幂等；断线触发取消或继续策略必须显式，结果不能重复写。 |

### 13.6 能力契约、复用/升级/新建裁决

| 能力候选 | 责任边界 | 裁决 |
|---|---|---|
| `多模态输入.规范化消息` | typed image/video/text、来源白名单、路径/URL/data URL/PIL 归一化 | **升级现有支持库**；将 `process_vision_info` 的输入契约抽象为 provider-neutral，保留 Qwen 适配。 |
| `多模态输入.读取图像` / `读取视频` | RGB、缩放、backend、采样、帧索引、metadata、临时资源 | **升级现有支持库**；解码器作为受管 provider，不让业务直连。 |
| `多模态输入.估算视觉预算` | image/video token、总像素、总上下文、生成预算 | **建立原子能力候选**；先登记契约和预算验证，再决定是否落生产，不在当前核对改平台。 |
| `视觉模型.准备输入` | Qwen chat template、视觉网格、M-RoPE、输入张量 | **建立/升级视觉模型模块**；模型模块只编排，模型内部类留 provider。 |
| `视觉模型.生成` | 统一 prompt、视觉数据、sampling、文本/结构化结果 | **升级模型提供者注册表**；Transformers/vLLM/SGLang/DashScope 共用契约，不复制业务流程。 |
| `视觉模型.权重与设备` | checkpoint、摘要、dtype、GPU/TP、引擎启动和探针 | **模型提供者 + 运行核心**；provider 管实际加载，运行核心管租约、预算和释放。 |
| `视觉模型.批处理` | 逻辑批次、padding、动态 batching、吞吐/失败逐项关联 | **模块编排 + provider 执行 + 运行核心限额**；禁止仅按 batch 成功掩盖单项失败。 |
| `多模态服务入口` | 鉴权、会话、幂等、SSE/HTTP、限流、审计、结果存储 | **接入统一网关/运行核心**；Gradio 只保留 demo，不作为生产 owner。 |
| 训练/评测脚本 | 数据集、LoRA/DeepSpeed、评测 judge、JSONL | **隔离为离线适配器**；可复用契约和 provider，但不进入在线运行核心。 |

当前核对不执行生产底座修改：缺少平台能力目录搜索、需求确认、占用租约、消费者验收契约和装配计划时，不新增能力包、不复制 Qwen 代码、不接入网关。`吸收`仅指契约结论进入本文件；`升级/建立候选`是后续工作包，不代表已实现。

### 13.7 L0-L4 验收契约与证据等级

| 层级 | 必须证明的事实 | 最低验收证据 |
|---|---|---|
| L0 | 请求可鉴权、可幂等、可绑定会话/截止时间，媒体消息结构完整 | 统一入口契约 + 非法参数/重复请求实测 |
| L1 | 视觉模型模块只调用唯一输入支持能力和唯一 provider 入口；模板、网格、M-RoPE 对齐 | 单图、多图、视频、混合消息；输入/网格/输出对账 |
| L2 | 输入支持库和 provider 的版本、backend、预算、错误码可观测；不隐藏 fallback | 本地/URL/base64、三 backend、坏媒体、预算上限、缺 provider |
| L3 | 会话/租约、GPU/进程/线程/句柄可回收，超时取消真实生效，失败证据落账 | 超时、客户端断线、取消、OOM 注入、SIGKILL/非零退出；ps/句柄/显存/临时目录复核 |
| L4 | 外部权重、CUDA/GPU、解码器、HF/vLLM/SGLang/HTTP 真实可用且版本匹配 | 锁定 checkpoint 摘要和环境指纹后，真实小样本图像/视频回归；无权重/GPU/API 时只能标未验证 |

当前核对实际验证等级为 **L1（静态源码/文档/入口链路复核）**，不是 L2-L4 运行通过：未安装依赖、未下载权重、未启动服务、未运行 GPU 推理或故障注入。后续正式接入必须逐级提升，且每个失败路径与资源清理都要有独立证据。

## 14. 后续结论与剩余风险

- **吸收**：typed 多模态消息、媒体解码/采样元数据、视觉 token/上下文预算、网格与 M-RoPE、统一生成结果、provider 差异隔离和训练/评测输入契约。
- **待核**：平台现有“多模态输入支持库”“视觉模型模块”“模型提供者”实际能力 id、版本/租约接口、统一错误码和网关路由；项目本地 CodeGraph 已建立并可用于 Python 源码符号交叉校验，但未覆盖 notebook、shell、Markdown 和配置。
- **隔离**：`web_demo_mm.py` 的 Gradio 状态、隐式 GPU cache 回收、HF 后台线程、训练样本换样本重试、评测脚本批量写 JSONL，均不能直接当平台底座模式。
- **高风险**：当前 `process_vision_info` 对远程资源和解码器的生命周期、HF 流式线程取消、OOM 后模型状态、vLLM worker 崩溃回收、GPU 句柄释放均缺统一实现；这些必须由运行核心/独立 provider 补齐。
- **唯一事实源**：本文件继续是 Qwen2.5-VL 项目架构记录；旧细探不恢复、不删除源码、不生成平行报告。

## 15. 当前 checkout 目录与入口索引

| 区域 | 代表入口 | 职责 |
|---|---|---|
| 模型说明 | `README.md`、`Qwen2.5-VL-*.md` | checkpoint、能力和基础示例 |
| Transformers 示例 | `cookbooks/`、`web_demo_mm.py` | processor、chat、generate |
| 视觉工具 | `qwen-vl-utils/src/qwen_vl_utils/vision_process.py` | image/video 解码、缩放、采样、metadata |
| 微调 | `qwen-vl-finetune/` | SFT、LoRA、DeepSpeed、数据 collator |
| 评测 | `evaluation/` | MMMU、MathVista、RealWorldQA、VideoMME |
| vLLM 集成 | `evaluation/*/run_*.py` | batch multimodal prompt、SamplingParams |
| 量化/部署 | `quantization/`、Docker/脚本 | dtype、AWQ/GPTQ、GPU runtime |
| package | `setup.py`、`qwen-vl-utils` | Python 包和依赖边界 |

关键 file:line：`vision_process.py:56-80` 的 `smart_resize` 将像素约束到 patch factor；`vision_process.py:147-182` 的 `smart_nframes` 将 fps/min_frames/max_frames 转成采样帧数；`vision_process.py:184-219` 负责 torchvision 视频读取和 timestamps；`run_videomme.py:27-57` 将 `process_vision_info` 结果转为 vLLM `mm_data/mm_processor_kwargs`；`run_realworldqa.py:26-56` 采用同一输入契约。

## 16. 模型加载、视觉 token 与推理资源

典型链路为：`AutoProcessor.from_pretrained` 加载 tokenizer/image processor/video processor，`Qwen2_5_VLForConditionalGeneration.from_pretrained` 加载权重，消息经 `apply_chat_template` 生成文本和 image/video placeholder，`process_vision_info` 产出张量与视频元数据，processor 负责 padding/网格，模型 `generate` 输出 token，再由 tokenizer decode。模型权重、processor、视觉张量和 KV cache 的生命周期不相同，不能只在请求结束清理 Python 引用就声称显存释放。

`smart_resize` 的 `factor` 通常对应视觉 patch 倍数；`min_pixels/max_pixels` 直接改变视觉 token 上限和显存。视频由 fps 或 nframes 采样，短视频最少帧、长视频最大帧受边界保护；视频输入还可能返回 `video_metadata`，缺失 metadata 时 provider 不能假设恒定 fps。

资源控制表：

| 资源 | 分配点 | 释放/风险 |
|---|---|---|
| checkpoint mmap/GPU weights | `from_pretrained` | worker 生命周期；OOM 后需重启/隔离 |
| processor/tokenizer cache | `from_pretrained` | 进程缓存，版本漂移需锁定 |
| image/video tensor | `process_vision_info` | request finally；大视频会瞬时放大内存 |
| CUDA stream/event | Transformers/vLLM backend | provider finally 和 worker shutdown |
| KV cache | `generate`/engine | batch 并发受 max model len 限制 |
| temporary video/file | URL/file decode | 超时、异常和取消均需删除 |
| JSONL evaluation output | evaluation scripts | 逐样本 flush 与失败对账 |

## 17. 训练、量化、服务与并发边界

`qwen-vl-finetune` 的 shell 脚本是离线训练入口，`sft_7b.sh` 通过 `max_pixels=50176`、`min_pixels=784` 约束图像预算；训练数据、LoRA adapter、DeepSpeed stage 和 checkpoint 保存不属于在线 inference API。量化目录和文档描述 AWQ/GPTQ 等权重格式，实际 kernel、CUDA、bitsandbytes/auto-gptq 版本必须按环境指纹验证。

vLLM 评测脚本创建 `LLM` 和 `SamplingParams`，通过 `limit_mm_per_prompt` 限制视频数量并批量提交请求；批量成功不能隐藏单条输入 decode 或生成错误。高并发服务需同时限制 request、图像 token、视频帧、生成 token、GPU KV cache 和排队时延，不能把 Python thread count 当吞吐上限。

服务形态包括 Transformers 进程、vLLM OpenAI-compatible server、SGLang/HTTP provider 和 Gradio demo。Gradio `web_demo_mm.py` 是交互样板，不是生产鉴权/限流/租约实现；vLLM/SGLang worker 崩溃、客户端断线、SSE 取消和 CUDA OOM 均需外部 supervisor 负责回收。

## 18. 测试、部署与未验证项

仓库评测目录提供 dataset loader、prompt builder、inference/eval 脚本，但当前没有统一的跨后端服务验收入口。已检查的静态测试/评测意图包括：视觉 resize、视频帧采样、MMMU/MathVision/RealWorldQA/VideoMME 结果 JSONL、vLLM 多模态请求和微调脚本参数；均未在本机执行。

部署前必须锁定：Python/PyTorch/Transformers/torchvision、CUDA/driver、checkpoint SHA、processor config、vLLM/SGLang 版本、视频 codec、GPU 型号、显存、并发与 token budgets。未下载权重、无 GPU 或 provider 不可达时，只能报告静态可用性。

剩余高风险：远程 URL 下载 SSRF/超时、视频解码资源泄漏、视觉 token 预算绕过、混合 batch padding 浪费、模型 OOM 后 worker 污染、量化 kernel 不兼容、评测结果部分写入、客户端取消未停止 CUDA kernel。所有这些均为未验证，不得写成已通过。

## 19. 审计终态

本次只修改平台唯一 `ARCHITECTURE.md`，源码 checkout 保留项目本地 `.codegraph/` 和源码侧 `ARCHITECTURE.md`，不改源码。当前 HEAD `9658872`，origin 为 `https://github.com/QwenLM/Qwen2.5-VL.git`；项目本地 CodeGraph 已初始化并保持 up to date（32 files、679 nodes、1,122 edges），不经过 MCP。未使用任何 MCP；事实来自 shell/git、CodeGraph、现有文档和源码静态行号。后续运行验证应继续追加本文件，不创建第二份报告。

## 20. 调用链细化

```text
messages[{type:text|image|video}]
  → processor.apply_chat_template
  → process_vision_info(messages)
  → smart_resize / smart_nframes
  → image_inputs/video_inputs/video_kwargs
  → processor(text, images, videos, return_tensors="pt")
  → model.generate(**inputs, sampling params)
  → tokenizer.batch_decode
  → result text + usage/metadata
```

图像消息可来自本地路径、file URI、base64 或 URL；视频可附 start/end、fps、nframes、min/max frames、min/max pixels 和 audio metadata。调用方必须在入口限制协议、大小、重定向和总媒体数；仓库工具函数不等于生产安全网关。

## 21. 参数风险表

| 参数 | 影响 | 失控后果 |
|---|---|---|
| `min_pixels` | 最低视觉分辨率/token | 小图被过度放大、显存上涨 |
| `max_pixels` | 最高视觉分辨率/token | 大图截断或 OOM |
| `fps` | 视频采样密度 | 长视频 token 爆炸 |
| `nframes` | 固定视频帧数 | 丢失时序信息或超上下文 |
| `min_frames/max_frames` | fps 模式边界 | 短/长视频不稳定 |
| `max_new_tokens` | 生成预算 | KV cache 与时延增长 |
| `limit_mm_per_prompt` | 单请求媒体数 | batch 不可控 |
| `dtype` | 权重/激活精度 | 显存与数值稳定性 |
| `device_map` | 权重分布 | 跨卡通信/加载失败 |
| `tensor_parallel_size` | vLLM TP | GPU 数和拓扑约束 |
| `max_model_len` | 上下文上限 | 输入拒绝或截断 |

## 22. 运行前后检查清单

运行前：确认 checkpoint 摘要、processor 与模型版本相容；验证视频 codec、GPU driver、CUDA、显存和临时目录；设置媒体大小、像素、帧数、token、超时和并发上限；禁止把真实生产 URL/token 直接放入 benchmark。

运行中：记录每请求媒体计数、实际 resize、帧索引、视觉 token、prompt token、生成 token、GPU 显存、排队和 decode 时延；将 provider error、OOM、取消、超时和部分 batch 失败分开计数。

运行后：等待生成 future/worker 终态；释放 CPU/GPU tensors、视频 reader、临时文件和 HTTP response；核对输出 JSONL 条数与输入条数；检查残留进程、GPU memory、句柄和端口。SIGKILL/宿主崩溃后必须以 supervisor 扫描 orphan，而不能依赖 Python finally。

## 23. 结论

Qwen2.5-VL checkout 主要提供模型配置/示例、qwen-vl-utils 视觉预处理、finetune 训练和 evaluation 脚本；它不是完整生产服务。最可复用的架构事实是视觉 token 预算、视频采样 metadata、统一多模态消息和 provider/engine 解耦。最不能直接继承的是 Gradio demo、评测脚本的全局状态、vLLM worker 默认值和未验证的 GPU/codec 资源语义。
## 24. CodeGraph 与全量文件事实

本次在源码目录执行 `codegraph init`，结果为“Already initialized”；随后 `codegraph status`：Files 32、Nodes 679、Edges 1,122、DB 2.12 MB、Backend `node:sqlite`、Journal `wal`，语言 Python 32，索引状态 up to date。`codegraph explore smart_resize smart_nframes process_vision_info Qwen2_5_VLForConditionalGeneration --max-files 8` 返回 34 symbols across 2 files，确认 `process_vision_info → fetch_image → smart_resize` 调用链；该索引为源码目录本地 `.codegraph`，不经过 MCP。

当前 git 受跟踪文件 154 个，主要目录为 `qwen-vl-utils`、`qwen-vl-finetune`、`evaluation`、`cookbooks`、`quantization` 与根目录脚本。工作树仅有未跟踪 `.codegraph/`、源码侧 `ARCHITECTURE.md`，未改源码。

## 25. 测试与部署索引

评测入口：`evaluation/VideoMME/run_videomme.py`、`evaluation/RealWorldQA/run_realworldqa.py`、`evaluation/MathVision/run_mathv.py`、`evaluation/MMMU/run_mmmu.py`；数据处理：对应 `dataset_utils.py`；服务/交互：`web_demo_mm.py` 与 OpenAI-compatible 示例；训练：`qwen-vl-finetune/scripts/sft_*.sh`、DeepSpeed 配置；部署：vLLM/SGLang/Transformers 文档和量化脚本。

本轮未运行测试、未下载权重、未启动 GPU/HTTP 服务、未执行量化或视频 codec 验证。CodeGraph 统计与当前 HEAD 已写入唯一文档；版本差异以 `git log -1` 为准，未执行远程 pull 以避免污染含未跟踪文件的 checkout。

## 26. 版本与复核边界

HEAD `9658872` 是本地研究基线，不宣称远程最新；remote ref 更新应单独 fetch 后比较，不能覆盖未跟踪文档或 `.codegraph`。当前 CodeGraph 只索引 Python 源码 32 文件，未覆盖 notebook、shell、Markdown 和配置，因此不能把 679 nodes 当全仓完整语义图。

复核优先级：先验证 `smart_resize` 与 `smart_nframes` 边界，再验证 `process_vision_info` 混合 image/video，随后小模型 CPU/GPU smoke、vLLM batch、长视频 token 上限、OOM/取消和临时资源回收。任何 provider、权重、显存、codec 和服务结果都必须绑定环境指纹与退出码。

本轮 Qwen2.5-VL 研究文档最终达到 500 行以上要求，CodeGraph 初始化与探索成功；只使用 shell/git/CodeGraph，未调用 MCP。

### 26.1 证据摘要

- 源码提交：`9658872`。
- 代码地图：32 files / 679 nodes / 1,122 edges。
- 关键调用：`process_vision_info:501` → `fetch_image:93` → `smart_resize:56`。
- 视频采样常量：`FRAME_FACTOR=2`、`FPS=2.0`、`FPS_MIN_FRAMES=4`、`FPS_MAX_FRAMES=768`。
- 图像默认 token 预算：`IMAGE_MIN_TOKEN_NUM=4`、`IMAGE_MAX_TOKEN_NUM=16384`。
- 视频默认 token 预算：`VIDEO_MIN_TOKEN_NUM=128`、`VIDEO_MAX_TOKEN_NUM=768`。
- 本地验证：只执行 git/rg/codegraph；无运行态通过证据。

### 26.2 未验证项

- 权重下载和摘要校验未执行。
- CUDA/GPU/显存和量化 kernel 未执行。
- vLLM/SGLang/HTTP 服务未启动。
- URL、base64、file URI 的安全与超时未执行。
- 长视频、音频、混合多媒体输入未执行。
- 客户端断线、取消、OOM、SIGKILL 回收未执行。
- 评测数据集和 JSONL 结果未执行。

审计终态：静态证据完整，运行态留空。

本文件为唯一架构记录。
