# LLaVA-NeXT 架构说明

> 本文件是本项目架构事实的唯一正式归档。说明文字使用中文；源码路径、类名、函数名、字段名、路由、命令和第三方名称保留原文。
>
> 此前 `细探-LLaVA-NeXT.md` 的有效结论已人工核对并吸收；后续架构维护只更新本文件，旧细探不再作为独立事实源。

## 1. 项目定位

LLaVA-NeXT 是一个以 Hugging Face Transformers 和 PyTorch 为运行底座的开放多模态大模型仓库，主线覆盖图像、视频、多图像/图文交错输入和视觉指令跟随。当前仓库同时包含三类代码：

1. **LLaVA-NeXT/OneVision 主模型链**：视觉编码器 + 可选视觉重采样器 + 多模态投影器 + Qwen/LLaMA/Mistral/Mixtral/Gemma 等因果语言模型。
2. **推理与服务链**：单图 CLI、FastAPI 控制器/模型 worker、Gradio 前端，以及可选的 SGLang worker。
3. **训练与评测链**：Hugging Face/DeepSpeed 训练脚本、SFT/DPO 训练、`lmms-eval` 外部评测；`llava-critic-r1/EasyR1` 是仓库内另一个面向多模态 GRPO 的扩展子项目。

README 已明确说明：本仓库原有训练流水线被视为 legacy，最新 LLaVA-OneVision/OneVision-2 训练流水线建议转向 `lmms-engine`。因此，本仓库的当前主要价值是模型实现、推理/服务代码、数据处理和历史训练参考，而不是一个持续演进的统一训练平台。

### 1.1 文本流程图

```text
图像 / 多图像 / 视频 + 文本指令
                │
                ▼
        Conversation / chat template
                │
                ▼
  tokenizer_image_token() 插入 IMAGE_TOKEN_INDEX
                │
                ▼
  image_processor / 视频采帧 / anyres 图像切块
                │
                ▼
  Vision Tower
  ├─ CLIP / CLIP S2
  ├─ SigLip
  ├─ HFVisionTower
  ├─ OpenCLIP
  ├─ ImageBind
  └─ MLCD / MLCD S2
                │
                ▼
  vision_resampler（Identity / SpatialPool / Perceiver / Qformer / MaskedDrop）
                │
                ▼
  mm_projector（linear / MLP / pooler / identity）
                │
                ▼
  LlavaMetaForCausalLM.prepare_inputs_labels_for_multimodal()
  将视觉特征替换到文本序列中的 IMAGE_TOKEN_INDEX 位置
                │
                ▼
  Qwen / LLaMA / Mistral / Mixtral / Gemma CausalLM.generate()
                │
       ┌────────┴────────┐
       ▼                 ▼
  本地 CLI 输出       Worker 流式 API
                         │
                         ▼
              Controller 调度 + Gradio UI
```

视频链路在视觉编码前先采样帧；在 `modalities=["video"]` 下，模型侧可按帧做 `get_2dPool()` 空间池化，并按 `mm_newline_position` 选择 grid/frame/one_token/no_token 的序列组织方式。

## 2. 真实分层与目录地图

### 2.1 主包 `llava/`

- `llava/constants.py`
  - 运行心跳常量：`CONTROLLER_HEART_BEAT_EXPIRATION`、`WORKER_HEART_BEAT_INTERVAL`。
  - 多模态特殊标记：`IMAGE_TOKEN_INDEX=-200`、`DEFAULT_IMAGE_TOKEN="<image>"`、`DEFAULT_IMAGE_PATCH_TOKEN`、`DEFAULT_IM_START_TOKEN`、`DEFAULT_IM_END_TOKEN`。
- `llava/conversation.py`
  - `SeparatorStyle` 定义 SINGLE/TWO/MPT/PLAIN/CHATML/LLAMA_2/LLAMA_3/QWEN/GEMMA。
  - `Conversation` 保存 system、roles、messages、分隔符、tokenizer 和停止条件，并负责 `get_prompt()`、消息追加、图像处理、Gradio 展示转换。
  - `conv_templates` 是按模型/协议选择 prompt 的注册字典，例如 `llava_llama_3`、`qwen_1_5`、`gemma_instruct`、`llava_v1`。
- `llava/mm_utils.py`
  - 图像预处理：`process_images()` 分派 `square/highres/anyres/anyres_max/crop_split/pad`。
  - any-resolution：`select_best_resolution()`、`resize_and_pad_image()`、`divide_to_patches()`、`get_anyres_image_grid_shape()`、`process_anyres_image()`。
  - 文本/图像对齐：`tokenizer_image_token()` 把 `<image>` 拆开并插入 `IMAGE_TOKEN_INDEX`。
  - 视频/图片传输辅助：`load_image_from_base64()`；生成停止：`KeywordsStoppingCriteria`。
- `llava/model/`
  - `builder.py`：唯一的主模型装载入口 `load_pretrained_model()`，根据 `model_name` 选择语言模型实现，支持 LoRA 合并、base model + `mm_projector.bin`、4/8 bit、`torch_dtype`、`device_map` 和 `attn_implementation`。
  - `llava_arch.py`：`LlavaMetaModel` 装配视觉模块；`LlavaMetaForCausalLM` 编码视觉输入并把特征插入语言模型 embedding 序列。
  - `language_model/`：`llava_llama.py`、`llava_qwen.py`、`llava_qwen_moe.py`、`llava_mistral.py`、`llava_mixtral.py`、`llava_gemma.py` 及 `modeling_llama.py`。
  - `multimodal_encoder/`：视觉塔实现与 `build_vision_tower()` 工厂。
  - `multimodal_resampler/`：`build_vision_resampler()` 工厂和 `MaskedDrop`、`SpatialPool`、`PerceiverResampler`、`Qformer`。
  - `multimodal_projector/`：`build_vision_projector()` 工厂和 `PoolerProjector`、线性/MLP/残差/Identity 投影。
- `llava/train/`
  - `train.py`：SFT 主入口，定义 `ModelArguments`、`DataArguments`、`TrainingArguments`、`LazySupervisedDataset`、`DataCollatorForSupervisedDataset`、`LLaVATrainer` 装配和保存逻辑。
  - `train_dpo.py`：DPO 数据集/数据整理器和 `LLaVADPOTrainer` 链路。
  - `llava_trainer.py`、`llava_trainer_eval.py`：训练器扩展。
- `llava/serve/`
  - `cli.py`：本地图像对话 CLI。
  - `controller.py`：worker 注册、心跳、模型列表和调度。
  - `model_worker.py`：真实模型加载与 `/worker_generate_stream`、`/worker_get_status`。
  - `gradio_web_server.py`：对话 UI、投票日志和到 controller/worker 的流式客户端。
  - `sglang_worker.py`：把推理转交 SGLang `RuntimeEndpoint`，提供相同 worker 形状的流式接口。
  - `register_worker.py`：手工向 controller 注册 worker。
  - `test_message.py`：面向服务链的手工请求冒烟脚本，不是 unittest 测试套件。
- `llava/eval/`
  - `model_vqa.py`、`evaluate_interleave.py`：仓库内的 VQA/交错输入评测辅助，完整基准主要由外部 `lmms-eval` 承担。

### 2.2 训练脚本与配置

- `scripts/train/`
  - `single_image.yaml`：单图数据组合。
  - `mid_stage.yaml`：中间阶段数据组合。
  - `onevision.yaml`：OneVision 阶段，覆盖单图、多图和视频。
  - `finetune_clip.sh`、`finetune_si.sh`、`finetune_ov.sh`、`pretrain_clip.sh`、`pretrain_siglip.sh`、`dpo.sh`、`dpo_ov7b.sh`：训练入口。
  - `README.md` 明确数据文件存在发布缺口，部分数据需要从 Hugging Face 数据集和历史项目拼装。
- `scripts/video/`
  - 视频训练 `train/exp.yaml` 与 SO400M/Qwen2 训练脚本。
  - 视频 demo/eval shell 脚本，负责参数化模型、prompt、采样帧数、空间池化和输出目录。
- `scripts/interleave/`
  - 多图像/视频/3D 交错输入评测脚本。
- `scripts/archived/`
  - 历史训练、数据转换和 checkpoint 工具，属于参考/兼容路径，不应当视为当前统一入口。
- `playground/`
  - 数据上传、检查、可视化、checkpoint 处理和 demo，属于实验辅助层，不被 `pyproject.toml` 的正式包发现规则纳入发行包。

### 2.3 `llava-critic-r1/EasyR1/`

这是仓库内的独立扩展，而不是 `llava/` 主推理包的一个普通模块：

- `verl/`：基于 EasyR1/veRL 风格的 RL 训练框架，包含 `trainer`、`workers/actor`、`workers/critic`、`workers/reward`、`workers/rollout`、FSDP/vLLM sharding 和 Ray 控制器。
- `examples/`：Qwen2.5-VL、ThinkLite-VL、Mimo-VL、LLaMA-3.2-Vision 等 GRPO 训练脚本/奖励函数。
- README 明确该 fork 是为 LLaVA-Critic-R1 做的定制，当前支持 GRPO、Reinforce++、ReMax、RLOO 等路线；LoRA/部分 VLM 并行能力仍列为待办或已知限制。

## 3. 核心数据模型与状态

本项目没有业务数据库或服务端持久化状态库；状态主要由内存对象、模型配置和文件系统产物构成。

### 3.1 输入数据

主 SFT 数据采用 JSON/JSONL/YAML 组合配置：

```json
{
  "id": "sample-id",
  "image": "relative/image.jpg",
  "conversations": [
    {"from": "human", "value": "<image>\\n请描述图片"},
    {"from": "gpt", "value": "参考回答"}
  ]
}
```

也支持：

- `image` 为字符串或图片路径列表（多图）。
- `video` 为视频路径，或特定数据集的帧目录/预计算 `.pkl`。
- YAML 的 `datasets` 列表，逐项指定 `json_path` 和 `sampling_strategy`，支持 `all`、`first:N`、`end:N`、`random:N` 及百分比。
- `DataArguments` 记录 `image_folder`、`video_folder`、`image_aspect_ratio`、`image_grid_pinpoints`、`video_fps`、`frames_upbound`、`force_sample`、`add_time_instruction` 等数据边界。

### 3.2 对话状态

`Conversation.messages` 是交替的 `[role, message]` 列表。含图像时 message 可以是 `(文本, 图像或图像列表, image_process_mode)` 元组。`get_prompt()` 根据 `SeparatorStyle` 生成发送给 tokenizer 的最终 prompt；`get_images()` 负责取出图片或视频引用。服务端 Gradio 使用 `state.dict()` 写入 JSONL 对话/投票日志。

### 3.3 模型配置状态

模型配置由 Transformers `PretrainedConfig` 子类承载，重要字段包括：

- 视觉：`mm_vision_tower`、`mm_vision_select_layer`、`mm_vision_select_feature`、`vision_tower_pretrained`。
- 融合：`mm_projector_type`、`mm_hidden_size`、`mm_patch_merge_type`、`mm_newline_position`。
- 分辨率：`image_aspect_ratio`、`image_grid_pinpoints`、`image_crop_resolution`、`image_split_resolution`。
- 视频：`mm_spatial_pool_stride`、`mm_spatial_pool_mode`、`add_faster_video`、`faster_token_stride`。
- 语言序列：`tokenizer_model_max_length`、`tokenizer_padding_side`、`max_position_embeddings`。

`LlavaQwenConfig`、`LlavaConfig`、`LlavaMistralConfig` 等通过 `AutoConfig.register()`/`AutoModelForCausalLM.register()` 注册为 Transformers 的可装载模型类型。

### 3.4 权重与日志持久化

- Hugging Face 缓存或本地 checkpoint 保存 tokenizer/config、模型权重、`mm_projector.bin`、`non_lora_trainables.bin` 和 LoRA 权重。
- SFT 的 `safe_save_model_for_hf_trainer()` 在仅训练 `mm_projector`/`vision_resampler` 时只保存适配器权重；LoRA 路径保存 LoRA state dict 和非 LoRA trainables。
- Gradio 服务将对话/投票写入 `LOGDIR` 下的日期 JSONL；图片按内容 MD5 写入 `LOGDIR/serve_images/YYYY-MM-DD/`。
- controller/worker 日志由 `build_logger()` 写入本地日志文件；没有事务、迁移或恢复机制。

## 4. 真实读取、推理与训练调用链

### 4.1 单图 Hugging Face 推理

```text
load_pretrained_model()
  -> AutoTokenizer.from_pretrained()
  -> Llava*ForCausalLM.from_pretrained()
  -> build_vision_tower()
  -> vision_tower.load_model()
  -> image_processor

PIL.Image
  -> process_images()
  -> tokenizer_image_token(prompt)
  -> IMAGE_TOKEN_INDEX
  -> model.generate(images=..., image_sizes=..., modalities=["image"])
  -> tokenizer.batch_decode()
```

`load_pretrained_model()` 还负责新增特殊 token、`resize_token_embeddings()`、推理 dtype、设备映射、上下文长度推断和可选 LoRA 合并。未提供 `model_base` 时按完整 LLaVA checkpoint 装载；提供 `model_base` 时可以仅加载 projector 或把 LoRA/非 LoRA 权重合并到 base model。

### 4.2 多模态 embedding 融合

`LlavaMetaForCausalLM.prepare_inputs_labels_for_multimodal()` 的关键步骤：

1. 判断 `vision_tower`、`images` 和输入序列是否有效。
2. 将 list/五维视频张量归一为可拼接的图像/帧批次。
3. 通过 vision tower 和 `mm_projector` 得到视觉特征。
4. 视频按 `get_2dPool()` 做空间池化；多 patch 图片依据 `image_aspect_ratio` 还原网格。
5. 依据 `mm_patch_merge_type` 选择 flat、spatial、maxpool、unpad、nobase 等合并策略。
6. 按 batch 中 `<image>` 的数量切分文本 token，把对应图像特征插入 `IMAGE_TOKEN_INDEX` 位置；插入的视觉位置 label 设为 `IGNORE_INDEX`。
7. 依据 `tokenizer_model_max_length` 截断，重新 padding 并构造 `attention_mask`/`position_ids`。

### 4.3 CLI 调用链

`python -m llava.serve.cli --image-file ...`（实际也可直接运行文件）执行：

1. `get_model_name_from_path()` 推断模型名。
2. `load_pretrained_model()` 装载 tokenizer/model/processor。
3. 自动或显式选择 `conv_mode`。
4. 读取本地/HTTP 图片并预处理到 CUDA FP16。
5. 循环接收输入，构造 `Conversation`，调用 `tokenizer_image_token()` 和 `model.generate()`。
6. 用 `TextStreamer` 增量打印输出。

该 CLI 硬编码 CUDA/FP16 路径，不能视为 CPU 或 macOS 本地推理入口。

### 4.4 Controller/Worker/Gradio 服务调用链

```text
Gradio add_text()/http_bot()
  -> POST controller /get_worker_address
  -> worker /worker_generate_stream
  -> ModelWorker.generate_stream_gate()
  -> base64 图片解码 + process_images()
  -> tokenizer_image_token()
  -> Thread(target=model.generate)
  -> TextIteratorStreamer
  -> NUL 分隔 JSON 流
  -> Gradio 增量刷新 state
```

controller 的实际 API：

- `POST /register_worker`：注册 worker、状态和心跳策略。
- `POST /refresh_all_workers`：重新探测并清理失效 worker。
- `POST /list_models`：返回模型名列表。
- `POST /get_worker_address`：按模型名返回调度到的 worker 地址。
- `POST /receive_heart_beat`：更新 worker 队列长度和心跳时间。
- `POST /worker_generate_stream`：controller 代理到 worker 的流式生成。
- `POST /worker_get_status`：聚合 worker 状态。

worker 的实际 API：

- `POST /worker_generate_stream`：请求 JSON 至少含 `prompt`，可选 `images`、`temperature`、`top_p`、`max_new_tokens`、`stop`；响应为 NUL 分隔 JSON，字段为 `text`、`error_code`。
- `POST /worker_get_status`：返回 `model_names`、`speed`、`queue_length`。

调度策略 `DispatchMethod` 支持 `lottery` 和 `shortest_queue`。worker 用 `asyncio.Semaphore` 限制并发，后台任务释放信号量并发送心跳。

### 4.5 训练调用链

```text
python llava/train/train.py
  -> HfArgumentParser(ModelArguments, DataArguments, TrainingArguments)
  -> get_model()
  -> Llava*ForCausalLM.from_pretrained()
  -> initialize_vision_modules()
  -> LazySupervisedDataset
       -> JSON/YAML 读取
       -> 图片预处理 / decord 视频采样
       -> preprocess_*()
       -> input_ids + labels
  -> DataCollatorForSupervisedDataset
  -> LLaVATrainer
  -> DeepSpeed/Accelerate/LoRA/量化
  -> safe_save_model_for_hf_trainer()
```

训练支持传统的 `tune_mm_mlp_adapter`/`tune_mm_vision_resampler` 控制，也支持 `mm_tunable_parts` 显式选择 `mm_vision_tower`、`mm_mlp_adapter`、`mm_vision_resampler`、`mm_language_model`。训练保存阶段对 LoRA、仅多模态适配器、完整模型有不同产物。

DPO 路径使用 `DPODataset` 和 `DPODataCollator`，样本包含 `prompt`、`answer`、`chosen`、`rejected` 等字段；DPO 训练依赖仓库内 `trl/` 以及 `LLaVADPOTrainer`。

## 5. API、CLI、SDK 与协议边界

- **Python SDK 边界**：`llava.model.builder.load_pretrained_model`、`llava.mm_utils.process_images`、`tokenizer_image_token`、`Conversation`、`Llava*ForCausalLM.generate`。
- **本地 CLI 边界**：`llava/serve/cli.py`，交互输入为 stdin，输出为 stdout；不提供稳定版本化的命令协议。
- **HTTP 边界**：FastAPI 的 controller/worker 路由，上述路由返回普通 JSON 或 NUL 分隔 JSON 流，不是 OpenAI 兼容 API。
- **前端边界**：Gradio `Blocks` UI，调用 controller/worker HTTP；状态是内存 `Conversation`，日志写文件。
- **SGLang 边界**：`sglang_worker.py` 通过 `RuntimeEndpoint` 获取后端模型信息，以 `@sgl.function` 的 `pipeline` 组装字符串/图片和 `sgl.gen()`。
- **外部评测边界**：`lmms-eval` 通过 `--model llava` 或 `--model llava_onevision/llava_vid` 加载模型；评测结果与日志输出到调用方指定 `--output_path`。
- **外部数据/权重边界**：Hugging Face checkpoint、LLaVA-OneVision-Data、LLaVA-Video-178K、LLaVA-Interleave-Bench 等不随仓库持久化，路径通过参数或 YAML 注入。

## 6. 技术栈与依赖边界

### 6.1 主项目

- Python `>=3.8`；README 推荐 Python 3.10 conda 环境。
- PyTorch、TorchVision、Transformers（`pyproject.toml` 指向固定 git commit）、DeepSpeed、PEFT、Accelerate、bitsandbytes。
- 图像/视频：Pillow、OpenCV、`decord`、`av`、`numpy`、`scipy`、`open_clip_torch`、`timm`。
- 服务：FastAPI、Uvicorn、Requests、Gradio、`httpx`。
- 数据/工具：datasets、PyYAML、sentencepiece、wandb、`einops`、`ftfy`、`shortuuid`。
- 可选高性能注意力：`flash-attn`；SGLang 路径需要外部安装 SGLang。

`pyproject.toml` 的 `[project.optional-dependencies].train` 是相对清晰的安装声明；根 `requirements.txt` 是一份更宽、更重且包含重复 `llava`/多套版本记录的环境快照，不能把二者当作严格一致的锁文件。

### 6.2 EasyR1 子项目

EasyR1 README 声明 Python 3.9+、`transformers>=4.51.0`、`flash-attn>=2.4.3`、`vllm>=0.8.3`，运行依赖 Ray/FSDP/vLLM 等多 GPU 训练组件，与主项目的 PyTorch 2.1.2/旧 Transformers 约束不同。两个依赖域应隔离环境，不应混装为一个可复现环境。

## 7. 测试、验证与当前执行状态

### 7.1 现有测试结构

现场扫描到的仓库级文件统计：约 390 个 Git 跟踪文件、188 个 Python 文件、13 个 Markdown 文件、39 个 JSON/YAML 文件；按文件名/目录约定没有成体系的 `tests/` 或 `test_*.py` 套件，唯一明显的测试/冒烟文件是 `llava/serve/test_message.py`。

`test_message.py` 是服务链手工冒烟：查询 controller 的模型列表和 worker 地址，向 `/worker_generate_stream` 发送文本 prompt，然后消费 NUL 分隔 JSON 流；它依赖正在运行的 controller/worker，不是离线单元测试。

### 7.2 本次验证

- 未安装依赖、未下载权重、未启动服务、未运行模型推理或训练，符合源码参考库只读边界。
- 仅对本次新增文档执行 `git diff --check`；该验证用于检查 Markdown 写入产生的空白/冲突标记问题，不代表模型功能或服务链已通过。
- 推理、训练、HTTP 服务和评测均保留为“未执行”，不能将 README 示例视为本机成功证据。

## 8. 未确认项、风险与后续复核点

1. **运行环境未实测**：当前机器没有在本任务内安装/确认 CUDA、FlashAttention、decord、bitsandbytes、DeepSpeed、SGLang、vLLM 或具体模型权重，因此不能确认任何模型能在本机启动。
2. **版本漂移**：本地 `main` 为提交 `bce12e479bc4dfee2b9c50c88137b01ff51bd483`，提交时间为 `2026-06-15T14:32:49+08:00`；远程 `origin/main` 的 `ls-remote` 结果也是该提交，当前本地没有发现远程落后/领先。后续更新需重新核对。
3. **文档与代码边界**：README/文档描述了 OneVision、Video、Interleave 和 Critic-R1 多条线；实际可执行入口分散在主包、脚本、实验目录和 EasyR1 子项目，不能把所有文档中的命令当作同一版本协议。
4. **模型名驱动分派**：`load_pretrained_model()`、`train.py::get_model()` 和服务层大量通过模型名字符串分支；checkpoint 目录命名错误会导致错误的语言模型类、conversation template 或视频路径。
5. **设备与精度耦合**：CLI/worker 对 CUDA、FP16/BF16、显存和上下文长度有强假设；worker 对 `max_new_tokens` 有 1024 上限，Gradio 侧又有 1536 上限，服务链并非无限上下文。
6. **输入一致性**：worker 要求图片数量与 prompt 中 `<image>` 数量一致；anyres、视频帧数、`mm_patch_merge_type`、`mm_newline_position` 和 tokenizer template 必须与 checkpoint 配置匹配，否则视觉 token/文本 token 可能不一致。
7. **服务可靠性**：controller 的 worker 状态是内存态；心跳线程没有持久化恢复，worker/控制器重启后需重新注册。流式生成在后台线程中运行，错误以 `error_code` JSON 返回，调用方必须消费完整流并处理错误。
8. **日志与隐私**：Gradio 会保存对话状态、客户端 IP 和图片 MD5/图片文件；生产部署前需单独确定日志目录权限、保留周期和隐私合规边界。
9. **数据可获得性**：训练 README 已明确列出缺失数据文件和需要外部下载/拼装的数据集；不能仅凭仓库 checkout 复现论文训练。
10. **EasyR1 隔离**：EasyR1 与主包版本和分布式运行时不同，且 README 列有 LoRA/ulysses/VLM 兼容限制；后续研究该子项目应单独读取其 `setup.py`、配置、worker 和 reward 链，不套用主包推理结论。
11. **代码质量遗留**：源码中存在 `except:`、注释中的 FIXME、旧路径和实验性分支；本次只做架构取证，不修改源码、不把这些现象包装成已修复。

## 9. 对系统底座的可借鉴点

以下是基于当前源码的候选，不是对平台的直接实现承诺：

- **统一多模态输入契约**：把图片、视频帧、多图像统一为“媒体批次 + 原始尺寸 + modality”三元信息，再由模型适配器处理。
- **模型适配器边界**：视觉塔、重采样器、投影器和语言模型由工厂/注册表选择，适合提炼为显式 provider，而不是在业务层散落字符串分支。
- **高分辨率 token 预算**：anyres 网格、视频空间池化和最大 patch 数是资源预算的一部分，应在进入 GPU 推理前可观测、可拒绝。
- **流式推理协议**：worker 的 NUL 分隔 JSON 流表达了增量文本和错误码；若进入平台底座，应升级为版本化、可取消、可超时、可回收的正式协议。
- **重型第三方隔离**：PyTorch/CUDA/FlashAttention/视频解码器/DeepSpeed/SGLang/vLLM 应视为重型提供者，主进程与模型进程、服务进程、评测进程应有明确生命周期和资源边界。
- **训练与推理分离**：主项目已经事实分为推理装载、服务、SFT/DPO 和外部评测四条链；平台化时应保留不同依赖和资源预算，不强行合成一条入口。

## 10. 证据路径与版本基线

- 项目根：`~/Documents/Agent/github 源码参考/30_多模态与媒体分析/70_multimodal_models/LLaVA-NeXT`
- 正式文档：`ARCHITECTURE.md`
- 此前历史细探（已人工吸收并清理）
- 主说明：`README.md`
- 包声明：`pyproject.toml`、`requirements.txt`
- 核心实现：`llava/model/builder.py`、`llava/model/llava_arch.py`、`llava/mm_utils.py`、`llava/conversation.py`
- 服务实现：`llava/serve/controller.py`、`llava/serve/model_worker.py`、`llava/serve/gradio_web_server.py`、`llava/serve/cli.py`
- 训练实现：`llava/train/train.py`、`llava/train/train_dpo.py`
- 官方文档：`docs/LLaVA_OneVision.md`、`docs/LLaVA_Video_1003.md`、`docs/LLaVA-NeXT-Interleave.md`、`docs/LLaVA-NeXT-Video.md`
- 扩展子项目：`llava-critic-r1/EasyR1/README.md`、`llava-critic-r1/EasyR1/verl/README.md`
- Git 基线：本地 `main` 与 `origin/main` 均为 `bce12e479bc4dfee2b9c50c88137b01ff51bd483`；远程地址 `https://github.com/LLaVA-VL/LLaVA-NeXT.git`
- CodeGraph：目标仓库没有 `.codegraph/` 索引，目标路径探索返回“CodeGraph isn't available here”；因此本次架构事实以现场读取的源码/README/文档/依赖/ Git 版本信息为证据，不运行 `codegraph init`，也不改目标仓库其他文件。

## 11. 第三轮：通用底座映射与唯一推理链路

本节是第三轮增量结论：不把平台概念反写成 LLaVA-NeXT 已经具备的实现，而是把源码中的真实职责映射到“多模态模型支持库、视觉模块、模型提供者、运行核心”四个底座边界。凡写“应落点/候选/待核”的地方均是平台装配建议，不是本仓库已经存在的目录或接口。

### 11.1 取证范围与裁决口径

本轮重新核对的主要证据为：

- `llava/mm_utils.py`：`process_images()`、`process_anyres_image()`、`process_highres_image()`、`tokenizer_image_token()`、`KeywordsStoppingCriteria`。
- `llava/model/builder.py`：`load_pretrained_model()` 的模型名分派、HF/LoRA/projector 权重装载、量化、视觉塔装载和上下文长度推断。
- `llava/model/llava_arch.py`：`LlavaMetaModel`、`encode_images()`、`encode_multimodals()`、`prepare_inputs_labels_for_multimodal()`。
- `llava/model/multimodal_encoder/builder.py`、`clip_encoder.py`：视觉塔工厂、`CLIPVisionTower`/`CLIPVisionTowerS2` 的延迟加载、冻结、dtype/device 和特征选择。
- `llava/serve/model_worker.py`、`controller.py`、`gradio_web_server.py`：worker 执行单元、并发信号量、心跳、流式协议、调度和 UI 客户端。
- `llava/train/train.py`：`LazySupervisedDataset`、`DataCollatorForSupervisedDataset`、`get_model()`、训练保存和多模态 batch 结构。

裁决分三类：**吸收**（源码事实可以成为底座契约输入）、**升级**（模式有价值但必须补统一入口/资源/错误语义）、**隔离或废弃**（只能作为兼容适配，不能复制为平台第二套核心）。

### 11.2 四类底座的职责映射

| 源码能力 | 真实实现位置 | 归属底座 | 第三轮裁决 |
|---|---|---|---|
| 文本 prompt、Conversation 模板、角色与停止串 | `llava/conversation.py`、`llava/mm_utils.py::tokenizer_image_token` | **多模态模型支持库** | 吸收“文本+媒体占位符→统一 token 序列”的纯转换契约；模板枚举、模型名猜模板不能继续散落在服务层。 |
| 图片 RGB 解码、base64 解码、尺寸记录 | `load_image_from_base64()`、`PIL.Image.open()`、训练 `process_image()` | 多模态模型支持库；Pillow/视频解码器属于**模型提供者** | 升级为可声明的媒体输入提供者；解码失败要有稳定错误码和尺寸/字节上限，不能把第三方异常直接透出。 |
| square/highres/anyres/crop_split/pad、网格选择、patch 切分 | `process_images()` 及其辅助函数 | **多模态模型支持库** | 吸收为版本化预处理能力；`grid_pinpoints`、patch 数、原图尺寸必须进入资源预算，不能只在进入 GPU 后才发现超限。 |
| `<image>`、start/end token、`IMAGE_TOKEN_INDEX` 与 tokenizer 对齐 | `tokenizer_image_token()`、`preprocess_multimodal()`、`initialize_vision_tokenizer()` | 多模态模型支持库 | 升级为单一 token/媒体计数校验；当前 worker 的“图片数量=占位符数量”校验应成为公开契约而不是局部 `ValueError`。 |
| CLIP/SigLip/HF/OpenCLIP/ImageBind/MLCD 视觉塔选择与特征抽取 | `multimodal_encoder/builder.py`、各 `*_encoder.py` | **视觉模块** | 吸收工厂思想，但改为能力注册表；视觉塔只负责媒体→视觉特征，不拥有服务、队列或全局模型生命周期。 |
| SpatialPool/Perceiver/Qformer/MaskedDrop、patch merge、newline token | `multimodal_resampler/`、`llava_arch.py` | 视觉模块（融合子模块） | 升级为视觉输出形状契约；`flat/spatial/unpad/nobase` 和视频 frame/grid 规则需显式记录 token 预算。 |
| Qwen/LLaMA/Mistral/Mixtral/Gemma CausalLM 选择 | `language_model/`、`builder.py`、`train.py::get_model()` | **模型提供者** | 隔离第三方 Transformers 类和模型名分支；统一返回“可生成模型句柄+能力描述”，禁止业务/服务层直接判断字符串。 |
| `from_pretrained()`、HF cache、PEFT merge、bitsandbytes 4/8 bit、`mm_projector.bin` | `llava/model/builder.py` | 模型提供者 + 运行核心资源治理 | 提供者负责真实装载/卸载；运行核心负责租约、设备、预算、超时和崩溃回收。当前没有校验摘要、原子激活或事务恢复，不能原样复制。 |
| `model.generate()`、`TextIteratorStreamer`、单请求后台 `Thread` | `model_worker.py::generate_stream()` | **运行核心**调用模型提供者 | 把一次生成封装为可追踪执行单元；线程只是当前实现，不是平台公共并发模型。必须补取消、硬截止、异常归一化和线程/进程回收。 |
| 训练样本读取、媒体预处理、padding、`images/image_sizes/modalities` batch | `LazySupervisedDataset`、`DataCollatorForSupervisedDataset` | 多模态模型支持库 + 运行核心批处理调度 | 吸收数据结构；区分“训练 DataLoader batch”和“在线推理批次”。当前在线服务没有动态 batch，不能宣称已有批处理推理。 |
| CUDA/FP16/BF16、`device_map`、4/8 bit、FlashAttention、DeepSpeed/FSDP | `builder.py`、`model_worker.py`、`train.py` | **运行核心**资源治理；实际 CUDA/库调用在模型提供者 | 升级为设备/精度/显存预算契约；服务层不得直接 `.cuda()` 或假设单一 GPU。 |
| worker 注册、队列长度、lottery/shortest_queue、心跳 | `controller.py`、`model_worker.py` | 运行核心调度/监督 | 吸收调度信号，不吸收内存字典和无限心跳线程；状态需有租约、过期、重启和证据。 |
| FastAPI worker/controller、Gradio、CLI、SGLang worker | `llava/serve/` | 项目适配层/服务适配器，最终只调用运行核心唯一入口 | 隔离现有 NUL 分隔流和直连 HTTP；它们是多个外部入口，不得各自复制模型推理链。 |
| checkpoint、LoRA、非 LoRA trainables、projector、日志图片 | `torch.load()`、`PeftModel`、`safe_save_model_for_hf_trainer()`、Gradio `LOGDIR` | 模型提供者（权重格式）+ 运行核心（制品/租约/清理） | 吸收文件类型事实；升级为内容摘要、来源、版本、原子写入、失败残留清理。 |

### 11.3 规范化契约与执行单元

#### 11.3.1 多模态推理请求契约

平台适配层应把当前多种入口归一为一个请求，不让 `cli.py`、`model_worker.py`、Gradio 和评测各自翻译：

```text
推理请求 {
  request_id,
  model_ref,                 # 不用模糊 model_name 字符串猜类
  messages/text,             # 已选模板或结构化消息
  media: [{kind, bytes/ref, original_size, ordinal}],
  preprocess_profile,
  generation: {temperature, top_p, max_new_tokens, stop},
  resource_budget: {deadline, max_pixels, max_patches, max_context, gpu_bytes},
  cancellation_token,
  tenant/owner
}
```

支持库输出的是规范化中间对象：`文本 token`、`媒体 tensor/媒体批次`、`original_size`、`modalities`、`image_token_positions`、`预处理诊断`。视觉模块输出视觉特征及形状诊断；模型提供者输出可生成句柄；运行核心输出统一的增量事件：`started`、`token_delta`、`completed`、`failed`、`cancelled`、`timed_out`，而不是直接暴露 `\0` 分隔字节。

#### 11.3.2 执行单元

本项目至少存在三种不同执行单元，平台不能混称：

1. **在线推理执行单元**：`/worker_generate_stream` 一次请求。当前由 `asyncio.Semaphore` 占用名额，`generate_stream_gate()` 调用 `model.generate()`，再由后台 `Thread` 产出 `TextIteratorStreamer`。其资源边界应是 request id、模型句柄租约、CPU/GPU 输入、输出流和截止时间。
2. **训练样本执行单元**：`LazySupervisedDataset.__getitem__()` 读取一个样本并完成图片/视频预处理、对话 token 化；`DataCollatorForSupervisedDataset.__call__()` 将多个样本 padding 为 batch。它有数据重试和替换样本语义，不得复用在线请求的重试语义。
3. **模型装载执行单元**：`load_pretrained_model()` 一次装载 tokenizer、语言模型、视觉塔、processor、projector/LoRA 权重。它应当拥有独立装载超时、失败回滚和模型句柄；当前实现是 worker 进程初始化阶段同步调用，失败通常直接阻止服务启动。

### 11.4 唯一推理链路

#### 11.4.1 当前源码的核心事实链

当前最完整的在线路径是：

```text
Gradio http_bot() / CLI / 直接 HTTP
  → controller.get_worker_address()
  → worker /worker_generate_stream
  → ModelWorker.generate_stream_gate()
  → load_image_from_base64() + process_images()
  → tokenizer_image_token() + IMAGE_TOKEN_INDEX
  → vision_tower() → mm_projector
  → prepare_inputs_labels_for_multimodal()
       → 视频 get_2dPool() / 多 patch merge / unpad / padding
       → 文本 embed_tokens + 视觉 embedding 插入
  → model.generate() + TextIteratorStreamer
  → NUL 分隔 JSON {text,error_code}
  → Gradio 增量 state 或 CLI 输出
```

`load_pretrained_model()` 不是每请求调用，而是 worker 启动时完成：`AutoTokenizer.from_pretrained()` → `Llava*ForCausalLM.from_pretrained()` → 视觉塔 `load_model()` → processor/context length。在线推理的唯一模型计算节点是 `model.generate()`；`encode_images()`/`prepare_inputs_labels_for_multimodal()` 是它内部的多模态准备阶段。

#### 11.4.2 平台应收敛的唯一链路

```text
服务/CLI/评测适配器
  → 唯一推理请求入口（校验、request_id、幂等/取消）
  → 多模态模型支持库（消息、媒体、预处理、token 对齐）
  → 视觉模块（vision tower → resampler/projector → 特征形状）
  → 模型提供者（已装载模型句柄 → generate/stream）
  → 运行核心执行单元（队列、GPU/显存预算、deadline、监督）
  → 统一事件流/结果/错误/证据
  → 服务适配器响应
```

这是一条**平台规范链**，不是对当前仓库已经有统一门面的误述。当前 `cli.py`、Gradio 和 worker 的输入限制、停止条件、超时和错误转换有重复；第三轮裁决为：**吸收核心算子，升级为唯一入口；隔离多套服务侧拼接逻辑和 NUL 私有协议**。

### 11.5 L0-L4 五级落点

| 层级 | 通用底座职责 | LLaVA-NeXT 真实证据 | 必须保留/补齐的契约 |
|---|---|---|---|
| **L0 输入与边界** | 请求身份、媒体引用、消息、权限、尺寸/字节/patch/context/GPU 预算、deadline、取消令牌 | `Conversation`、worker `params`、Gradio 文本/图片硬截断、图片数量检查 | 统一 schema、request_id、幂等、输入上限、敏感日志策略；现状仅部分存在。 |
| **L1 预处理与对齐** | RGB/视频解码、帧采样、anyres/grid/pad、tokenizer、`IMAGE_TOKEN_INDEX`、原尺寸/模态保留 | `mm_utils.py`、`LazySupervisedDataset`、`preprocess_*()`、`DataCollator` | 版本化预处理 profile、媒体与 token 一一对应、patch/token 预算、失败可定位；当前有多处分支和硬编码。 |
| **L2 模型组装与提供者** | tokenizer、vision tower、resampler/projector、CausalLM、权重/量化/注意力后端 | `load_pretrained_model()`、`build_vision_tower()`、`LlavaMetaModel`、HF/PEFT/bitsandbytes | provider registry、模型能力描述、权重摘要/版本/依赖、装载/卸载接口；当前由 `model_name` 字符串和 import 分支驱动。 |
| **L3 运行与资源核心** | 执行单元、队列、批处理策略、GPU/显存、超时、取消、OOM、崩溃、句柄/租约、事件 | worker `Semaphore`、后台 `Thread`、controller 心跳/队列、`device_map`、`.cuda()`、`torch_dtype` | 统一监督器和资源回收；当前无取消端点、无真实显存预算、无 OOM 隔离、无崩溃自动恢复。 |
| **L4 服务与证据** | HTTP/CLI/UI/评测适配、版本化流式协议、日志/指标/审计、重启恢复 | FastAPI routes、Gradio `http_bot()`、`test_message.py`、`LOGDIR` JSONL | 一个公开入口、事件协议、错误码、脱敏与留存、健康/心跳/重启证据；当前是内存 controller + 本地日志，非事务恢复。 |

### 11.6 批处理、GPU 与显存映射

#### 批处理事实

- 训练侧明确有 batch：`DataCollatorForSupervisedDataset` 将 `input_ids`/`labels` padding，并把每条媒体的 `image_sizes`、`modalities` 和 tensor 列表送入模型；图片可为 `(N,P,C,H,W)`，视频可为 `(N,F,C,H,W)` 的列表语义。
- 模型侧在 `prepare_inputs_labels_for_multimodal()` 将 list/5D 输入拼接为 `concat_images`，编码后按 `split_sizes` 拆回样本，再按视频/图片和 patch merge 组织；这是“多媒体输入批处理”，不是服务端动态 batching。
- 在线 worker 每个 HTTP 请求独立启动一个 `model.generate()` 线程，`model_semaphore` 只限制并发数；源码没有请求合并、micro-batch、batch token budget 或跨请求 KV cache。平台映射必须标为“并发限流，非批处理推理”。

#### GPU/显存事实

- `load_pretrained_model()` 支持 `device_map`、FP16/BF16、4/8 bit `BitsAndBytesConfig`、`attn_implementation`；视觉塔在 `device_map != "auto"` 时直接 `.to(device="cuda", dtype=torch.float16)`。
- worker 将图像 tensor `.to(self.model.device, dtype=torch.float16)`，文本 `input_ids` 使用 `.cuda()`；CLI 同样是 CUDA/FP16 假设。CPU、MPS、混合设备路径不是本轮实测能力。
- anyres/highres/S2/视频帧和 `mm_newline_position` 会改变视觉 token 数，随后 `max_new_tokens` 受 `max_context_length - input_ids - num_image_tokens` 限制；这说明视觉 token 是上下文和显存预算的一部分。
- 源码未在请求前读取 `torch.cuda.mem_get_info()`、未设显存硬预算、未对输入 patch/帧数作统一上限，也未在 OOM 后隔离/重启模型进程。平台的 GPU 预算与回收只能归运行核心，不能由某个视觉塔自行决定。

### 11.7 权重、模型句柄与资源生命周期

| 资源 | 创建/持有 | 正常释放 | 失败/超时/取消/崩溃现状 | 平台归属与补齐 |
|---|---|---|---|---|
| tokenizer/config/processor | `AutoTokenizer.from_pretrained()`、`AutoConfig.from_pretrained()`、vision tower processor | 随 worker 进程退出；无显式 close | 装载异常直接抛出，缓存/半成品由 HF/进程处理，未有本项目回滚证据 | 模型提供者创建句柄；运行核心登记版本、来源、租约和卸载动作。 |
| 语言模型权重 | `Llava*ForCausalLM.from_pretrained()`/`AutoModelForCausalLM.from_pretrained()` | 无请求级释放；worker 常驻 | 缺权重/类不支持/依赖异常通常启动失败；无加载超时和原子激活 | 模型提供者；运行核心负责隔离进程、加载超时、失败清理和单一激活指针。 |
| 视觉塔权重 | `CLIPVisionModel.from_pretrained()` 等 `load_model()`；`is_loaded` 防重复加载 | `requires_grad_(False)` 不是释放；无 unload | 视觉 provider 不存在或模型名未知时 `ValueError`；无自动重启 | 视觉模块调用模型提供者；必须增加 load/unload、设备转移和显存归还证据。 |
| `mm_projector`/resampler/LoRA | `torch.load()`、`load_state_dict()`、`PeftModel.merge_and_unload()` | merge 后对象交给 GC；保存由 `torch.save()` | key/shape 不符可能部分加载或异常；无摘要/事务/回滚 | 模型提供者格式适配；权重制品/完整性/原子写入归运行核心。 |
| PIL、CPU tensor、视频帧、GPU tensor | `load_image_from_base64()`、processor、`process_images()`、`.to(cuda)` | Python 引用离开作用域后由 GC/CUDA allocator 管理 | 训练读图失败会重试/换样本；在线错误只转 error JSON；取消时没有明确 tensor 清理 | 多模态支持库声明借用/拥有；运行核心在执行单元终态清理引用并记录峰值。 |
| `Thread`、`TextIteratorStreamer` | worker 每请求创建；streamer `timeout=15` | 生成自然结束后线程应结束；无 join/强制停止 | 客户端断开、controller timeout、streamer timeout 不提供取消模型线程；可能继续占 GPU | 运行核心必须用可终止子进程或受监督任务；线程不能作为唯一崩溃隔离边界。 |
| `asyncio.Semaphore` | 首次 `/worker_generate_stream` 创建；请求 acquire | `BackgroundTasks` 调 `release_model_semaphore` | 若生成器/连接异常路径未可靠执行后台释放，存在名额泄漏风险；没有租约校验 | 运行核心监督器；释放必须幂等并与请求终态绑定。 |
| worker/controller/heartbeat | 进程启动创建线程；controller `worker_info` 是内存字典 | 进程退出才消失；过期 heartbeat 删除 worker | worker 崩溃由 controller 超时移除；无自动重启、未完成请求恢复、模型句柄清理证据 | 运行核心进程组/租约/重启监督；L4 只负责健康投影。 |
| 日志、图片和对话 JSONL | Gradio `LOGDIR`、`serve_images`、`build_logger()` | 无自动保留/删除/事务 | 写失败可能影响请求末尾；无敏感数据擦除或崩溃对账 | L4 证据和留存策略；不能把现有日志当权威状态。 |

### 11.8 失败、超时、取消、OOM 与崩溃矩阵

| 场景 | 源码行为 | 可重试/恢复判断 | 底座要求 |
|---|---|---|---|
| 图片数量与 `<image>` 不匹配、非法参数 | `generate_stream()` 抛 `ValueError`，`generate_stream_gate()` 返回 `error_code=1` | 输入错误不可盲目重试 | L0 稳定 `INVALID_INPUT`，不占用后续 GPU 资源；记录 request_id 和诊断。 |
| unknown vision tower/model class、checkpoint/权重缺失 | builder/factory `ValueError` 或 HF/torch 异常，常发生在 worker 启动 | 装载阶段可在新 provider/新配置重试；当前没有自动策略 | 返回 `MODEL_PROVIDER_UNAVAILABLE`/`WEIGHT_NOT_FOUND`，清理半装载句柄，禁止注册不完整 worker。 |
| 图片/视频损坏或训练样本读取失败 | 训练 `__getitem__()` 当前样本重试 3 次，再尝试其他样本 3 次，最终抛出；视频异常还递归取 `i+1` | 训练数据读取可有限重试/换样本；在线请求应失败而非换用户输入 | 记录原样本 id、重试次数、最终原因，禁止无限递归；在线和训练错误码分开。 |
| controller/worker HTTP 连接失败 | controller `get_worker_status`/转发 `requests` timeout=5；Gradio worker 流 timeout=100；worker heartbeat 失败循环每 5 秒重试 | 心跳可重试；请求转发有限重试，但生成是否仍在后台不确定 | 连接超时与生成超时分开；deadline 贯穿全链；重试必须幂等且不重复计费。 |
| streamer/生成超时 | `TextIteratorStreamer(timeout=15)` 可能抛异常；controller/Gradio 连接超时只返回服务错误；没有取消 API | 当前不能证明模型线程停止，不能标“已取消” | 运行核心必须向执行单元发送取消，等待确认；未确认只能 `timed_out_pending`，并回收/隔离模型进程。 |
| 客户端断开/主动取消 | 服务没有 stop/cancel 路由；注释中的 stop button 被禁用；后台 `Thread` 无取消句柄 | 不可安全重试为同一 request；可能继续消耗 GPU | 增加取消令牌、断开检测、线程/进程终止和信号量释放；取消事件要有终态证据。 |
| CUDA OOM/显存不足 | 代码显式捕获 `torch.cuda.CudaError`，其他 OOM 常落入宽泛 `Exception`；统一返回 `error_code=1` | 不能在同一上下文无界重试；可降级输入/新执行单元重试 | 识别 `OutOfMemoryError`/OOM 文本，清理临时 tensor、`empty_cache` 仅作辅助，必要时隔离并重启 provider；报告预算与峰值。 |
| `model.generate()` 未知异常 | `generate_stream_gate()` 捕获 `Exception`，返回通用错误；没有 traceback 结构化事件 | 是否可重试未知，不能默认重试 | 错误分类、关联 provider/模型句柄、保留脱敏 traceback；重试策略由错误码决定。 |
| worker 进程崩溃/被杀 | controller 心跳过期后删除内存中的 worker；未完成流中断；无自动拉起 | worker 需外部 supervisor 才可能恢复，当前源码无证据 | 运行核心用独立进程组、崩溃检测、有界重启、孤儿 GPU/端口/文件清理；恢复后重新注册并做健康检查。 |
| controller 重启 | `worker_info`、调度和心跳状态丢失，worker heartbeat 发现不存在后重新注册 | worker 可重新注册，但在途请求不恢复 | L4 状态重建与请求终态对账；不能把内存状态当持久权威。 |
| `max_new_tokens`/上下文超限 | worker 上限 1024，Gradio 上限 1536；上下文不足时返回文本提示 `Exceeds max token length` | 可由调用方缩短输入或输出重新提交 | L0 预估文本+视觉 token，统一拒绝/降级，不让不同入口各自截断。 |

### 11.9 第三轮复用、升级、隔离裁决

| 裁决 | 内容 | 原因 |
|---|---|---|
| **吸收** | `媒体批次 + original_size + modality`；`tokenizer_image_token()` 的占位符对齐；视觉 tower/resampler/projector 的分层；训练 collator 的 `images/image_sizes/modalities` 形状 | 这些是跨模型可复用的事实契约，且与服务入口无关。 |
| **升级** | `load_pretrained_model()` 的 provider 选择；HF/PEFT/bitsandbytes 权重装载；GPU/精度/device_map；worker semaphore/heartbeat/streamer | 有真实实现价值，但必须放到显式注册、资源监督和统一错误/事件契约下。 |
| **新建** | 多模态输入契约、模型句柄/权重制品契约、执行单元、GPU/显存预算、deadline/取消、OOM 分类、崩溃重启、统一流式事件、资源终态证据 | 当前仓库没有这些平台治理能力，不能把局部代码包装为已有能力。 |
| **隔离** | Pillow/decord/av、Transformers、PEFT、bitsandbytes、CUDA、FlashAttention、DeepSpeed、SGLang/vLLM | 重型/可选第三方依赖必须在模型提供者或独立进程边界，主运行核心不直接承载其崩溃风险。 |
| **废弃/禁止复制** | 服务层按 `model_name` 大量字符串分支；各入口直调 `process_images()`/`model.generate()`；`.cuda()`、FP16 硬编码；NUL 私有流；无取消的后台线程；内存 worker 注册表 | 会形成多套推理链、隐式 fallback、不可回收 GPU 任务和错误语义漂移。 |
| **待核** | EasyR1/veRL/vLLM 的批处理、分布式显存和多节点故障语义；SGLang worker 是否能完全满足同一模型句柄契约 | 属于独立扩展/外部运行时，本轮未执行其真实环境，不能直接纳入主链。 |

### 11.10 第三轮事实边界与验证等级

- **源码事实（已确认）**：上述函数、数据形状、入口和异常分支来自当前工作树源码；目标仓库无 CodeGraph 索引，不能提供代码图调用关系证据。
- **静态架构映射（本轮完成）**：完成 L0-L4、四类底座职责、唯一推理链、执行单元、生命周期和失败矩阵的文档化映射；没有把映射建议写成生产实现。
- **本机功能验证（未执行）**：未安装依赖、未下载 checkpoint、未运行 CUDA/模型、未启动 FastAPI/controller/worker/Gradio，故没有推理质量、吞吐、显存峰值、取消、OOM 或崩溃恢复的实测证据。
- **测试真假边界**：仓库没有成体系的离线 `tests/`；`llava/serve/test_message.py` 依赖正在运行的服务，只能作为外部服务冒烟，不可替代 L0-L4 单元/集成测试。
- **后续平台装配前置**：需要先登记能力需求、搜索现有能力、冻结唯一契约 owner、申请资源租约，再决定是否新建多模态支持库/视觉模块/provider/运行核心能力；本节不直接修改平台生产底座。
