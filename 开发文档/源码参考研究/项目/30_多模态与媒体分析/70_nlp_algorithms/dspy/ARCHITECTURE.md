# DSPy 架构文档

> 项目根：`/Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/70_nlp_algorithms/dspy`
>
> 本文是该项目的正式架构归档。原有 `细探-dspy.md` 已人工核对并吸收；后续架构维护只更新本文，旧细探不再作为独立事实源。
>
> 研究范围：本地源码、README、`pyproject.toml`、测试目录、文档导航、Git 版本与远程 `origin/main` 快照。

## 1. 项目定位

DSPy（Declarative Self-improving Python）是一个以 Python 代码编排语言模型程序的框架。它把任务输入/输出写成 `Signature`，把一次模型调用封装为 `Predict` 等模块，把提示词/结构化输出转换交给 `Adapter`，再通过 `Evaluate` 和 `Teleprompter`/`GEPA` 等优化器用数据和指标改进程序。

核心理念是“Programming—not prompting”：调用方组合声明式签名和模块，而不是把完整提示词作为业务逻辑硬编码。项目同时覆盖：

- 语言模型客户端：`LM`、`BaseLM`、`Provider`、缓存、重试、历史与用量；
- 声明与类型：`Signature`、`InputField`、`OutputField`、Pydantic 类型以及 `Example`/`Prediction`；
- 调用适配：`ChatAdapter`、`JSONAdapter`、`XMLAdapter`、`TwoStepAdapter` 及多模态/工具类型；
- 程序模块：`Module`、`Predict`、`ChainOfThought`、`ReAct`、`ProgramOfThought`、`RLM`、`BestOfN`、`Refine` 等；
- 数据与评估：`Dataset`、内置数据集、检索器、`Evaluate`、指标；
- 编译/优化：`BootstrapFewShot` 家族、`MIPROv2`、`SIMBA`、`GEPA`、`GRPO` 等；
- 流式、回调、并行、异步、持久化以及 MCP/工具调用。

## 2. 真实执行流程

```text
用户定义 Signature / Module / Example
        │
        ▼
 dspy.configure(lm=..., adapter=...) 或 dspy.context(...)
        │
        ▼
 Module.__call__ / Predict.__call__
        │  输入校验、默认值、demos、config、LM 选择
        ▼
 Adapter.__call__ / Adapter.acall
        │  _call_preprocess：工具与原生响应能力规划
        │  format：系统说明、示例、历史、当前输入
        ▼
 LMRequest（LMMessage、LMPart、LMToolSpec、LMConfig）
        │
        ▼
 Adapter._call_lm → BaseLM.__call__ / LM.forward
        │  兼容 legacy 或 typed_lm 契约
        ▼
 LM → LiteLLM / OpenAIProvider / 其他 Provider
        │  缓存、重试、流式、供应商请求与异常归一化
        ▼
 LMResponse（LMOutput、LMUsage、工具调用、推理、多模态内容）
        │  当前适配层仍经 legacy_outputs_from_lm_response 兼容解析
        ▼
 ChatAdapter / JSONAdapter.parse
        │
        ▼
 Prediction.from_completions → Prediction / Module history
        │
        ├─ Evaluate：在 devset 上批量执行并计算 metric
        └─ Teleprompter/GEPA：根据训练集、验证集、trace、反馈改写程序
```

## 3. 分层与目录地图

项目正式 Python 包位于 `dspy/`，测试位于 `tests/`，文档站位于 `docs/`。

```text
dspy/
├── __init__.py                 # 对外聚合导出、configure/context、版本与异常
├── adapters/                   # Signature/输入/输出到 LM 消息的格式化与解析
├── clients/                    # BaseLM、LM、Provider、缓存、OpenAI/LiteLLM 转换
├── core/                       # LMRequest/LMResponse 等标准化请求响应类型
├── datasets/                   # Dataset、DataLoader 与内置数据集
├── dsp/                        # settings、历史兼容工具、ColBERTv2 等基础能力
├── evaluate/                   # Evaluate、指标、自动评估
├── experimental/               # 实验性类型/接口
├── predict/                    # Predict 与内置预测/Agent/推理模块
├── primitives/                 # Module、Example、Prediction、解释器、沙箱类型
├── propose/                    # 数据集摘要、grounded proposer 等提议能力
├── retrievers/                 # Retrieve、Embeddings、Weaviate/Databricks RM
├── signatures/                 # Signature、字段、动态签名解析
├── streaming/                  # streamify、StreamListener、规范化消息
├── teleprompt/                 # Teleprompter、few-shot/指令/权重优化器
└── utils/                      # 回调、并行、异步、缓存、保存、日志、MCP 等
```

当前本地盘点：`dspy/` 含 149 个 Python 源文件、15 个主要子包；`tests/` 含 87 个 `test_*.py` 文件；`docs/` 含文档站源码和 API 页面。数量来自目标根现场扫描，不采用旧 README 数字。

### 3.1 对外聚合入口

`dspy/__init__.py` 聚合导出：

- `dspy.Predict`、`dspy.Module`、`dspy.Signature`、`InputField`、`OutputField`；
- `dspy.LM`、`dspy.BaseLM`、`LMRequest`、`LMResponse` 及 `System`/`User`/`Assistant`/`ToolResult`；
- `dspy.Adapter`、`ChatAdapter`、`JSONAdapter`、`XMLAdapter`、`TwoStepAdapter` 与多模态/工具类型；
- `dspy.Evaluate`、`dspy.Example`、`dspy.Prediction`、检索器和优化器；
- `dspy.configure`、`dspy.context`、`dspy.load`、`dspy.streamify`、`dspy.track_usage`；
- `dspy.LMError` 及认证、计费、限流、超时、上下文窗口、供应商等错误类型。

## 4. 核心数据模型与状态

### 4.1 `Signature` 与字段契约

`dspy/signatures/signature.py` 的 `Signature` 继承 Pydantic `BaseModel`，使用 `SignatureMeta` 管理字段与类级指令：

- 类式声明：`class MySig(dspy.Signature)`，字段用 `InputField`/`OutputField`；
- 字符串声明：`dspy.Signature("question, context -> answer")`，由 `make_signature`、AST 解析和类型解析生成新的签名类；
- `instructions` 来自类 docstring 或默认输入/输出说明；
- `input_fields`、`output_fields`、`fields` 保留字段顺序；
- `with_instructions`、`append_instructions`、`with_updated_fields`、`prepend`、`append`、`insert`、`delete` 返回新签名，不就地修改原签名；
- `dump_state`/`load_state` 保存指令、字段前缀与描述，供 `Predict` 持久化。

`SignatureMeta._validate_fields` 强制每个模型字段带 `InputField` 或 `OutputField` 的 DSPy 元数据。未显式给出字段类型时默认按 `str` 处理并记录 `IS_TYPE_UNDEFINED` 标记。

### 4.2 规范化 LM 请求/响应

`dspy/core/types.py` 用 Pydantic 模型承载跨供应商协议边界：

- `LMMessage`：角色、`parts`、名称和元数据；可从 OpenAI 风格 `content`、`tool_calls`、tool 消息归一化；
- `LMPart` 联合类型：`LMTextPart`、`LMImagePart`、`LMAudioPart`、`LMVideoPart`、`LMDocumentPart`、`LMBinaryPart`、`LMToolCallPart`、`LMToolResultPart`、`LMThinkingPart`、`LMCitationPart`、`LMRefusalPart`；
- `LMToolSpec`：供应商无关的函数工具描述；
- `LMReasoningConfig`、`LMToolChoice`、`LMCacheConfig`、`LMPromptCacheConfig`、`LMConfig`：生成、推理、工具、DSPy 缓存和供应商扩展配置；
- `LMRequestPatch`：适配器在渲染阶段合并消息、内容部件、工具、配置和字段删除计划；
- `LMRequest`：模型、消息、工具、配置和元数据；`from_call` 将直接调用输入归一化；
- `LMOutput`：内容部件、结束原因、截断、logprobs、供应商数据；
- `LMResponse`：多个输出、使用量、成本、缓存命中、响应标识和供应商元数据；保留 `to_values`/`to_outputs` 兼容旧输出；
- `LMStream*Event` 与 `LMOutputBuilder`：将开始、增量、输出结束、结束和错误事件组装为 `LMResponse`；输出/部件索引必须从 0 连续。

`LMHistoryEntry` 同时实现 Pydantic 模型和 `Mapping`，把规范化 request/response 作为权威字段，并按需派生旧式 `prompt`、`messages`、`outputs`、`usage`、`kwargs`。

### 4.3 `Example`、`Prediction` 与训练状态

- `Example` 是动态字段容器，内部 `_store` 保存样本；`with_inputs` 标记输入字段，`inputs()` 返回输入子集，`labels()` 返回非输入字段；支持字典访问、属性访问、复制、递归 `toDict`。
- `Prediction` 继承 `Example`，去掉输入/演示标记，保存 `_completions` 和 `_lm_usage`；可从多候选 completion 生成，并用 `score` 支持数值比较与算术。
- `Predict` 保存 `stage`、`signature`、`config`、`lm`、`traces`、`train`、`demos`；`dump_state` 保存签名、LM 状态、训练/轨迹数据，明确排除 API key 等敏感配置。
- `Module` 保存 `_compiled`、`callbacks`、`history`；其 `__getstate__` 排除运行时 history/callbacks，`__setstate__` 恢复空容器。

## 5. 关键调用链

### 5.1 模块与预测

`dspy/primitives/module.py` 的 `ProgramMeta` 在实例化时先执行 `Module._base_init`，即使子类没有显式调用 `super().__init__` 也保证 `callbacks` 和 `history` 存在。`Module.__call__`：

1. 用 `with_callbacks` 包裹调用；
2. 将当前模块加入 `settings.caller_modules`；
3. 在 `track_usage` 开启时创建用量跟踪上下文；
4. 调用子类 `forward`，最后把 token 用量附着到 `Prediction`；
5. `acall` 对应异步链路。

`Module.named_predictors` 递归发现 `Predict`，`set_lm`/`get_lm` 管理模块内 LM，`batch` 委托 `Parallel` 批量执行。

`dspy/predict/predict.py` 的 `Predict` 在 `_forward_preprocess` 中：

- 合并构造时 config 与调用时 config；
- 解析临时 `signature`、`demos`、`lm`；没有 LM 时要求调用方先 `dspy.configure`；
- 填充签名字段默认值，警告多余输入和类型不匹配；
- 根据 LM 的 `n`/`num_generations` 与温度设置多候选调用的默认随机性；
- 根据 `settings.send_stream` 和 `stream_listeners` 判断是否流式。

随后 `forward` 选择 `settings.adapter` 或 `ChatAdapter`，执行适配器调用，再用 `Prediction.from_completions` 生成结果并写入 trace。

### 5.2 Adapter 到 LM

`dspy/adapters/base.py` 的适配器边界分为：

1. `_call_preprocess`：处理原生函数调用、`Tool`/`ToolCalls`、原生 `Reasoning`/`Citations` 等类型；必要时从渲染签名删除已由供应商原生处理的字段；
2. `format`：组合系统说明、few-shot demos、会话 `History` 和当前用户输入；
3. `_render_request`：把旧式消息先转为 `LMMessage`，再生成 `LMRequest`；
4. `_call_lm`/`_acall_lm`：当前仍通过 `to_openai_chat_request` 转成旧 BaseLM 参数调用；
5. `legacy_outputs_from_lm_response`：将规范化响应暂时转回旧字典/字符串，以保持现有 parser 行为；
6. `_call_postprocess`：解析输出、填充原生字段、恢复工具调用并返回字典列表。

源码中的 TODO 明确表明该层处于迁移期：未来计划以 `_AdapterPlan` 取代隐式的签名删除/配置变更，并直接解析 `LMResponse`，目前仍保留 legacy 兼容桥。

`ChatAdapter` 使用 `[[ ## field_name ## ]]` 字段标记和 `[[ ## completed ## ]]` 完成标记；解析缺失字段或类型转换失败时抛 `AdapterParseError`。其非 LM 异常默认回退到 `JSONAdapter`，但 `LMError`、上下文窗口错误以及显式禁用回退时原样抛出。

`JSONAdapter` 默认启用原生函数调用：

- 若模型支持 `response_format`，为签名构造 Pydantic 结构化输出模型；
- 开放式 `dict`、工具输出不适合结构化 schema 或模型不支持 schema 时改用 `json_object`；
- 用 `json_repair` 和嵌套对象正则提取 JSON，再按输出字段类型转换；
- 结构化输出设置失败时只回退到 JSON 模式，不吞掉 `LMError`。

### 5.3 BaseLM、LM 与供应商

`dspy/clients/base_lm.py` 定义自定义 LM 的扩展契约：

- `forward_contract="legacy"`：实现 `forward(prompt=None, messages=None, **kwargs)`，返回 OpenAI/LiteLLM 风格响应；
- `forward_contract="typed_lm"`：实现 `forward(request: dspy.LMRequest) -> dspy.LMResponse`，是新自定义 LM 的首选；
- `BaseLM.__call__` 默认维持旧的 `list[str | dict]` 返回形状；显式传入 `LMRequest`、在 `dspy.context(experimental=True)` 中调用或声明 `typed_lm` 时走规范化路径；
- legacy 响应经 `_process_lm_response`、`_legacy_outputs_to_lm_response` 归一化；规范化调用结束后记录 usage 和 `LMHistoryEntry`；
- `dump_state` 排除 API key 并记录类路径；`load_state` 默认只允许内置 `dspy.clients.lm.LM`，加载自定义 LM 必须显式 `allow_custom_lm_class=True`；
- `GLOBAL_HISTORY` 上限为 `MAX_HISTORY_SIZE=10000`，单 LM 与模块 history 受 `settings.max_history_size` 控制。

`dspy/clients/lm.py` 的 `LM` 是 LiteLLM 主实现：

- 从 `provider/model` 推断 provider，支持 `chat`、`text`、`responses` 三种 model type；
- 在 `forward`/`aforward` 中合并默认和单次 config，剥离 rollout/cache 控制后调用 LiteLLM；
- 通过 `request_cache` 和 LiteLLM cache 参数实现 DSPy 级缓存与供应商级缓存边界；
- 根据供应商异常、HTTP 状态和上下文窗口错误映射到 DSPy 的结构化 `LMError` 子类；
- 支持流式 completion、工具调用、reasoning、response schema、finetune 和 reinforce 能力探测；
- `dump_state` 保存可重建参数，但不保存 API key。

### 5.4 配置、并发与上下文

`dspy/dsp/utils/settings.py` 的 `Settings` 是单例：

- `configure` 修改进程级 `main_thread_config`，第一次调用的线程成为配置 owner，其他线程不能再次全局修改；
- `context` 使用 `contextvars` 创建临时覆盖，可跨线程/异步任务使用；
- `Parallel`、`asyncify` 等 DSPy 原语负责把上下文覆盖传播到派生执行；
- 默认配置包括 `lm`、`adapter`、`rm`、`trace`、`callbacks`、线程数、最大错误数、流式、历史、usage tracker、工具异步转同步开关；
- `settings.save/load` 使用 `cloudpickle`，加载 pickle 默认拒绝，因为反序列化可执行任意代码。

## 6. 优化、评估与检索边界

### 6.1 评估

`dspy/evaluate/evaluate.py` 的 `Evaluate` 接受 `devset` 和 metric，调用 `ParallelExecutor` 并行执行 `program(**example.inputs())`，收集 `(example, prediction, score)`，输出 `EvaluationResult`：

- `score` 为百分比形式的平均得分；
- `results` 保存每个样本的原例、预测和指标值；
- 支持 `max_errors`、失败分数、进度、可选 pandas 表格；
- 可将结果保存为 CSV/JSON；
- pandas、IPython 属于可选展示依赖，缺失时评估核心仍可运行。

### 6.2 Teleprompt/GEPA

`dspy/teleprompt/teleprompt.py` 只定义优化器接口：`compile(student, trainset, teacher=None, valset=None, **kwargs)` 与 `get_params`。

具体优化器通过 `compile` 返回优化后的 `Module`，常见状态边界是：学生模块、训练集、验证集、指标、demo/trace、候选指令或权重，而不是直接修改供应商服务。

`dspy/teleprompt/gepa/gepa.py` 将 DSPy 与外部 `gepa` 包连接：

- `GEPA` 要求 metric 接收 `gold`、`pred`、完整 trace、目标 predictor 名称和 predictor 子 trace；
- 以 candidate 的 predictor instruction 为种子，运行评估、收集失败反馈、调用 reflection LM 提议新指令；
- 支持 `light`/`medium`/`heavy` 自动预算，或 `max_full_evals`/`max_metric_calls`；三者必须且只能指定一个；
- 支持 Pareto/current-best 选择、合并候选、日志目录、W&B/MLflow、随机种子和详细结果；
- `DspyGEPAResult` 保存 candidates、parents、验证集分数、逐样本分数、最优候选和预算统计；
- 本地版本的 GEPA 依赖为 `gepa[dspy]==0.1.1`；远程最新版本已升级到 `0.1.4`，并引入 `Flex` 代码组件优化相关接口，不能把远程行为当成本地实现。

### 6.3 数据集与检索

`dspy/datasets/dataset.py` 的 `Dataset` 以确定性 seed 打乱并切分 `train`/`dev`/`test`，懒缓存切分结果；每个样本包装为 `Example`，可用 `input_keys` 标记模块输入。`prepare_by_seed` 为多个训练 seed 生成训练集和评估子集。

`dspy/retrievers/` 提供 `Retrieve`、`Embeddings`、`WeaviateRM`、`DatabricksRM` 等边界；检索服务/向量数据库不属于 DSPy 核心状态库，具体连接由对应 retriever 和外部依赖承担。

## 7. API、CLI、SDK 与协议边界

### 7.1 Python SDK 公共调用

项目没有以独立 CLI 作为主入口；主要入口是 Python SDK：

```python
import dspy

class QA(dspy.Signature):
    question: str = dspy.InputField()
    answer: str = dspy.OutputField()

lm = dspy.LM("openai/gpt-4o-mini")
dspy.configure(lm=lm)
qa = dspy.Predict(QA)
pred = qa(question="What is DSPy?")
```

真实公共符号集中在 `dspy/__init__.py`，而不是某个命令行脚本。外部集成应优先依赖这些公开导出，不应依赖 `dspy/` 下的私有实现路径。

### 7.2 工具、MCP 与多模态

`dspy/adapters/types/` 定义 `Image`、`Audio`、`File`、`Document`、`History`、`Tool`、`ToolCalls`、`Reasoning`、`Citations` 等类型。适配器根据签名字段和 LM 能力决定：

- 作为消息内容部件发送；
- 通过供应商原生工具/函数调用发送；
- 通过普通文本或 JSON 表示；
- 从响应的 tool calls、reasoning、citations 和多模态部件恢复到 `Prediction`。

`dspy/utils/mcp.py` 与 `tests/utils/resources/mcp_server.py` 提供 MCP 相关工具/测试边界；它属于可选能力，不改变 `Signature → Adapter → LM` 的核心调用链。

### 7.3 流式与异步

- `Module.acall`、`Predict.aforward`、`Adapter.acall`、`BaseLM.acall`、`LM.aforward` 是异步链路；
- `dspy/streaming/streamify.py`、`streaming_listener.py` 和 `messages.py` 管理流式监听与事件；
- LM 层将供应商流式 chunk 转发到 `MemoryObjectSendStream`，并最终用 `LMOutputBuilder` 组装规范化响应；
- `syncify`/`asyncify` 提供同步/异步包装，但工具异步转同步受 `allow_tool_async_sync_conversion` 控制。

## 8. 依赖与运行边界

`pyproject.toml` 本地版本为 `3.3.0b1`，要求 `Python >=3.10, <3.15`。核心运行依赖包括：

- `openai`、`litellm`：模型供应商/协议入口；
- `pydantic`：签名、规范化 LM 类型和结构化输出；
- `regex`、`json-repair`、`orjson`：解析、修复和序列化；
- `requests`、`anyio`、`tenacity`、`cachetools`、`diskcache`：网络、异步、重试和缓存；
- `tqdm`：评估/并行进度；
- `cloudpickle`：程序与设置序列化；
- `gepa[dspy]==0.1.1`：GEPA 优化器。

可选依赖通过 extras 分组：`anthropic`、`weaviate`、`mcp`、`langchain`、`optuna`、`numpy`、`litellm`、`dev`、`test_extras`。`pandas`、`IPython` 等仅在相应展示/测试场景按需导入。

仓库源码不内置 API key、数据库或持久化业务数据。LM 访问凭据由 LiteLLM/供应商环境和调用配置提供；保存/加载接口对 pickle 和自定义 LM 类有显式信任边界。

## 9. 测试与验证结构

本地 `tests/` 按能力域组织，现场统计如下：

| 目录 | 测试文件数 | 覆盖重点 |
|---|---:|---|
| `adapters` | 13 | Chat/JSON/XML/工具/多模态/解析 |
| `clients` | 9 | LM、缓存、Embedding、序列化、provider |
| `predict` | 14 | Predict、CoT、ReAct、RLM、Refine、并行 |
| `teleprompt` | 14 | Bootstrap、GEPA、SIMBA、ensemble 等 |
| `utils` | 13 | 设置、并行、异步、回调、保存、MCP |
| `signatures` | 4 | 签名、类型、文件/图像适配 |
| `adapters`/`clients`/其他 | 20 | 评估、数据集、检索、流式、原语、文档和可靠性 |

`tests/README.md` 明确说明：该目录主要验证代码正确性和 Adapter 可靠性；端到端模块/优化器质量另由 LangProBe 关注。测试夹具包含本地 mock LM、LiteLLM server、MCP server、可靠性生成程序和保存文件。

未在本任务中安装依赖、启动服务、构建文档或运行网络模型测试。架构文档验证仅应采用文档级/差异级检查；依赖供应商、API key、Deno、外部向量数据库和 live LM 测试不应被误报为本地静态验证已通过。

## 10. 本地/远程版本基线

### 10.1 本地基线

- 分支：`main`；
- 本地提交：`0f458222c1af67ce902f01093237fb8ca27dc75e`；
- 本地提交时间：`2026-07-24T03:00:18-07:00`；
- 本地提交摘要：`docs(predict): move class-level docstrings to ChainOfThought and BestOfN (#9953)`；
- 本地包版本：`3.3.0b1`；
- 建档前工作树存在未跟踪细探材料；本任务未修改源码、依赖、测试或配置，旧细探已在人工收口后清理。

### 10.2 远程基线

已通过本机代理 `http://127.0.0.1:4780` fetch 并用独立快照读取 `origin/main`：

- 远程提交：`e0400fd32feac35cf8e19f18640d6a36f71724b7`；
- 远程提交时间：`2026-08-20T17:05:55-04:00`；
- 远程提交摘要：`chore(deps): bump mkdocs-material from 9.7.6 to 9.7.7 in /docs (#10110)`；
- `git rev-list --left-right --count HEAD...origin/main`：`0 61`，即本地没有领先提交，远程领先 61 个提交；
- 远程包版本已为 `3.3.0`，`gepa[dspy]` 已升至 `0.1.4`，并新增 `deno` extra；
- 远程新增 `dspy/predict/flex/` 和 Flex/GEPA 代码优化能力，并扩展了 Responses API、回调、解释器和测试；
- 远程版本只能作为最新实现线索。本正式文档的实现事实以本地提交 `0f45822...` 为准，未执行 pull、merge、安装或构建。

## 11. 风险、未确认项与后续复核点

1. **版本漂移**：远程领先 61 个提交，本地架构与远程最新行为不完全一致；若要升级，应以独立快照逐文件复核后再决定，不应直接覆盖本地工作树。
2. **标准化迁移未完成**：`Adapter` 和 `BaseLM` 中存在明确的 compatibility/TODO 路径，当前仍是规范化 `LMRequest/LMResponse` 与 legacy OpenAI/LiteLLM 输出并存，而非纯 typed 链路。
3. **外部依赖边界**：LiteLLM、OpenAI/provider、GEPA、可选 MCP、向量数据库和 Deno 未在本任务中启动或实测；其版本兼容性需按 lockfile/CI 或独立环境验证。
4. **安全加载边界**：`dspy.load`、`Settings.load` 和自定义 LM state 可触发 pickle/cloudpickle 反序列化；只允许来自可信来源的文件，并显式传 `allow_pickle=True`/`allow_unsafe_lm_state=True`。
5. **缓存与历史副作用**：LM 调用默认可能写入 request cache、LM history、模块 history 和全局 history；评估/优化时要明确关闭、隔离或清理这些运行态。
6. **并发状态**：全局 `configure` 有 owner 线程约束，临时覆盖应使用 `context`；并行评估、异步调用、流式 listener 与 callback 组合时需通过专门测试确认上下文传播。
7. **结构化输出兼容性**：不同供应商对 response schema、tool calls、reasoning、多模态 content block 的支持不同；`JSONAdapter` 的 schema/json-object/native-tool 分支不能简单视作等价。
8. **资源和凭据未确认**：本地未核对实际 API key、可用模型、Deno、外部数据库或网络服务可用性；本架构文档不声称这些外部运行条件已满足。
9. **细探收口**：`细探-dspy.md` 的初步结论已吸收到本文的定位、目录、签名、适配器、优化、依赖和风险章节；后续不要再创建第二份并行正式架构文档。
10. **MCP 上下文归属异常**：目标根由本地路径和 Git 现场核对为 dspy；任务所用的系统工程 MCP `project_context` 返回的是平台自身根目录，不能作为 dspy 源码根证据。后续若依赖平台 MCP 的项目上下文，应先修正实例/项目绑定。

## 12. 证据路径与复核命令

本次研究使用的事实路径：

- `README.md`：项目定位、安装方式、论文与官方文档入口；
- `pyproject.toml`：版本、Python 范围、依赖、extras、包发现和 pytest/ruff 配置；
- `dspy/__init__.py`：公开导出与顶层配置别名；
- `dspy/signatures/signature.py`：签名元类、字段解析、动态签名和状态；
- `dspy/primitives/module.py`、`predict/predict.py`：模块执行、LM 选择、适配器调用和预测生成；
- `dspy/adapters/base.py`、`chat_adapter.py`、`json_adapter.py`：格式化、规范化桥、解析与回退；
- `dspy/core/types.py`、`clients/base_lm.py`、`clients/lm.py`：LM 数据模型、兼容契约、LiteLLM 调用和错误边界；
- `dspy/primitives/example.py`、`prediction.py`、`datasets/dataset.py`：训练/评估数据模型；
- `dspy/evaluate/evaluate.py`、`teleprompt/teleprompt.py`、`teleprompt/gepa/gepa.py`：评估和优化；
- `dspy/dsp/utils/settings.py`、`utils/saving.py`：全局配置、上下文和持久化安全边界；
- `tests/README.md`、`tests/`：测试职责和现场测试分类；
- 此前历史细探（已人工吸收并清理）；
- Git 本地提交、`origin/main` fetch 和经 `127.0.0.1:4780` 获取的独立远程快照：版本基线。

建议的只读复核命令：

```bash
cd "/Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/70_nlp_algorithms/dspy"
git status --short
git log -1 --format='%H%n%aI%n%s'
git rev-list --left-right --count HEAD...origin/main
python3 -c 'from pathlib import Path; print(sum(p.is_file() and p.suffix == ".py" for p in Path("dspy").rglob("*")))'
```

本次未执行安装、启动、构建、Git 提交或源码/依赖/测试配置修改。

## 13. 后续：向模型支持库、模块库、运行核心与网关映射

当前核对只做底座映射和裁决，不把 DSPy 源码复制进生产底座，也不修改 DSPy 源码、依赖、配置或测试。此前调用平台 `project_context` 时返回的是另一个项目（`/Users/hekunhua/Documents/Agent/PHP/华世王镞_v3`），与本目标根不一致；该结果仅记录为环境错绑，不作为 DSPy 的代码地图、验证或架构证据。当前核对结论均回到目标仓库本地源码静态取证。

### 13.1 现有能力命中与归属表

| DSPy 能力/源码证据 | 平台归属 | 后续裁决 | 边界 |
|---|---|---|---|
| `dspy/signatures/signature.py` 的 `SignatureMeta`、`make_signature`、字段顺序/类型/指令、`dump_state`/`load_state` | 公共契约 + 模块库的声明模型 | **吸收契约模式** | 签名是模块输入/输出契约，不是 provider 配置；动态签名生成必须由唯一契约编译入口管理 |
| `dspy/core/types.py` 的 `LMRequest`/`LMResponse`、`LMMessage`/`LMPart`/`LMToolSpec`/`LMConfig` | 模型支持库的跨 provider 标准类型 | **升级现有模型支持库候选** | 统一多模态、工具、reasoning、usage、cost、cache_hit 和 provider metadata；不把供应商对象穿透到模块 |
| `dspy/clients/base_lm.py` 的 `BaseLM`、`forward_contract`、history、usage 和安全 state load | 模型支持库 | **吸收，优先 typed contract** | `typed_lm` 是新适配器首选；`legacy` 仅作为兼容桥，不能成为平台第二套契约 |
| `dspy/clients/lm.py`、`clients/provider.py`、`clients/openai.py`、`clients/_litellm.py` | 模型支持库的 provider 适配边界 | **升级/隔离 provider** | provider 推断、模型能力探测、请求重试、错误归一化、launch/kill、训练 job 均应由支持库/受管 provider 拥有 |
| `dspy/clients/cache.py`、`dspy/utils/caching.py` | 模型支持库的工程缓存 | **吸收缓存契约，隔离缓存实现** | 缓存可删除、可重建，不是事实源；API key/base URL 等不进入 key；磁盘 pickle 必须有信任边界 |
| `dspy/primitives/module.py`、`predict/`、`adapters/`、`primitives/example.py`/`prediction.py` | 模块库 | **吸收模块编排模式** | Module/Predict/Adapter 只组合契约和能力；模块不应直接导入第三方 provider 或持有 provider 私有对象 |
| `dspy/evaluate/`、`teleprompt/`、`propose/`、`datasets/`、`retrievers/` | 模块库的评估/编译优化流程 | **吸收为模块能力，编译状态由核心治理** | `Evaluate` 产生评估制品；Teleprompter/GEPA 产生候选程序/参数；训练数据、指标和候选不能旁路写正式状态 |
| `dspy/dsp/utils/settings.py`、`utils/parallelizer.py`、callbacks、usage tracker、streaming | 运行核心 | **升级运行核心候选** | 负责请求上下文、调度、并发、事件、统计、取消和资源治理；DSPy 当前实现仍有隐式单例和弱取消，不能原样照搬 |
| `dspy/primitives/base_module.py` 的 `_compiled`、参数遍历、deepcopy、state save/load | 运行核心 + 模块制品治理 | **吸收状态/制品边界** | 编译后的子模块冻结；正式平台应以不可变制品和激活指针表达，禁止靠内存布尔值作为唯一发布状态 |
| `dspy/__init__.py`、Python SDK 示例 | SDK/网关客户端门面 | **不等同统一网关** | `__init__.py` 只是本地 Python 聚合导出；HTTP/MCP/CLI/SDK 必须在平台网关汇聚到同一能力调用器，不能各自直连 `LM` |
| `dspy/utils/mcp.py`、测试 MCP server | 可选协议适配器/网关边界 | **待核，不能视为平台网关** | 其存在只证明 DSPy 有 MCP 相关边界，不证明已有统一认证、租约、幂等、状态、审计或资源回收网关 |

### 13.2 缺口表与复用/升级/新建/隔离裁决

| 缺口或风险 | 本地源码事实 | 落点裁决 |
|---|---|---|
| 没有平台级唯一能力注册/调用器 | DSPy 的公开入口是 Python SDK；`Predict.forward` 直接拿到 `Adapter` 和 `BaseLM` | **新建平台网关/运行核心装配，不改 DSPy 源码**；所有“模型调用、模块执行、编译、评估”先归一成能力 id |
| typed 与 legacy 双轨 | `BaseLM.__call__` 按调用形态在 `LMRequest/LMResponse` 与旧 list/dict 输出间切换；Adapter 仍有 legacy bridge | **升级模型支持库**；外部契约只发布规范类型，legacy 只在支持库兼容层归一化 |
| provider 错误/重试分散在 LiteLLM 边界 | `LM.forward/aforward` 传 `num_retries`，并把 LiteLLM 异常映射为 DSPy `LMError` 子类 | **复用错误契约，升级 provider 适配器**；重试预算、退避、可重试标记由运行核心统一注入和审计 |
| 缓存与历史是进程/对象运行态 | `Cache` 有内存 LRU + `FanoutCache`；LM 有自身、全局、模块 history | **吸收为可选工程缓存/事件投影**；禁止缓存或 history 成为事实库，正式事实/证据由平台权威 owner 写入 |
| 并行超时后仍可能有在途线程 | `ParallelExecutor` 对 straggler 最多重提交一次，最终 `executor.shutdown(wait=False)`；没有强杀线程 | **升级运行核心**；任务必须有取消 token、硬超时、受管执行单元和现场残留检查，不能宣称线程已停止 |
| 训练/强化学习 job 的终态和取消依赖 provider | `TrainingJob` 是 `Future`；`ReinforceJob` 仅定义抽象状态/终止接口；`LM` 明确留下 KeyboardInterrupt/cancel TODO | **隔离成受管训练 provider**；运行核心统一 job 状态和资源租约，provider 实现实际取消 |
| 编译状态不等于发布状态 | `Module._compiled` 仅影响参数遍历/冻结；部分优化器把它设为 `True` | **模块库产生候选，运行核心/控制面负责制品、签名、激活和回滚**；`_compiled` 只能作为模块内部提示 |
| 没有跨 HTTP/MCP/SDK 的单一对外结果信封 | DSPy 主要返回 `Prediction`/`EvaluationResult`/`LMResponse`，没有平台统一网关信封 | **新建网关契约**；只向外暴露成功/值/错误码/错误说明/可重试/状态/证据引用，隐藏 provider 异常对象 |

结论是：DSPy 最值得吸收的是“规范请求响应 + 声明式模块 + 评估编译闭环 + provider 适配边界”，不是整个框架作为一个新运行时接入。没有需求确认、能力搜索、复用决策、占用租约、验收契约和装配计划时，当前核对不修改平台生产底座。

## 14. 唯一调用链与责任转移

### 14.1 DSPy 本地真实链（实现事实）

```text
调用方
  → dspy.configure(lm=...) / dspy.context(...)
  → Module.__call__ / Predict.__call__
  → Predict._forward_preprocess（signature、demos、config、LM、默认值、类型告警）
  → Adapter.__call__/acall
  → Adapter._call_preprocess + format + _render_request
  → BaseLM.__call__/acall（LMRequest 或 legacy 兼容）
  → LM.forward/aforward
  → request_cache → LiteLLM completion/text/responses
  → provider 外部 API/受管模型服务
  → LMResponse/旧响应归一化
  → Adapter.parse / _call_postprocess
  → Prediction.from_completions
  → Module history、LM history、GLOBAL_HISTORY、usage、trace、callbacks
  → Evaluate 或 Teleprompter/GEPA 读取结果并生成评估/候选编译状态
```

证据分别位于 `dspy/predict/predict.py:141-275`、`dspy/primitives/module.py:93-129`、`dspy/clients/base_lm.py:321-406`、`dspy/clients/lm.py:208-322`、`dspy/clients/cache.py:216-310` 和 `dspy/evaluate/evaluate.py:162-226`。这条链是 DSPy 当前 Python 内部链，不应被误写成平台已经存在的统一网关。

### 14.2 平台唯一装配链（后续落点）

```text
正式代码/上层项目
  → 项目适配层（版本、配置、权限、路径、密钥引用、项目别名）
  → 统一网关公开入口（HTTP/MCP/SDK/CLI 只做协议转换）
  → 唯一能力调用器/能力注册表（能力 id + 契约版本 + 幂等键）
  → 运行核心 admission/上下文/预算/调度/取消/资源租约
  → 模块库公开入口（模块流程：签名→适配→评估/编译）
  → 模型支持库公开能力（规范 LMRequest/LMResponse、缓存、错误、usage）
  → 锁定 provider/受管独立进程/第三方 SDK
  → 统一结果、状态事件、证据引用与资源释放
```

唯一规则：模型调用只有一个能力 id 和一个契约 owner；不同 provider 只是该能力的策略，不复制模块流程。模块只能调用模型支持库公开入口；项目适配层、网关和正式代码不能构造 `LM`、调用 LiteLLM 或读取 provider 私有状态。provider 对象、API key、连接句柄和线程句柄不得穿过网关/模块契约。

## 15. 资源生命周期与四种终态

| 资源 | 创建/持有者 | 正常完成 | 业务失败 | 超时/主动取消 | 宿主崩溃/残留风险 |
|---|---|---|---|---|---|
| `Signature` 动态类、字段元数据 | `SignatureMeta`/`make_signature`；调用进程持有 | 随模块/调用引用释放 | 解析失败在构造阶段抛错 | 无独立取消；需由调用上下文丢弃 | 动态类只在进程内；持久化只保存指令、prefix、description，不是运行句柄 |
| `Module`/`Predict`、demos、traces | 模块实例；`Module.__call__` 借用调用上下文 | 返回 `Prediction`；history/trace 按上限保留 | callback/forward 异常向上；运行态不应写成制品 | `acall` 可被任务取消，但源码没有统一取消清理协议 | `__getstate__` 排除 history/callbacks；平台应禁止把运行态快照当正式制品 |
| `LMRequest`/`LMResponse`、消息部件、工具调用 | Adapter 创建，BaseLM/LM 在一次调用中持有 | parse 后转 `Prediction`，响应可进 history/usage | `LMError` 归一化；敏感参数不进 history/cache key | provider async 调用可收到任务取消，但没有统一 cancel hook/现场证据 | 外部连接/流可能残留；必须由 provider 适配器关闭 session/stream |
| provider HTTP/SDK 会话、模型服务进程 | `LM`/`Provider` 或平台运行核心 | 返回结果并释放会话/租约 | `LM.forward` 映射错误；重试耗尽后释放 | 超时由 provider/运行核心中断；当前 DSPy 未证明能强杀在途请求 | `launch/kill` 是 provider 扩展点；平台必须核查进程、端口、连接和临时目录 |
| DSPy cache 内存 LRU | `dspy.cache`/`Cache` 创建；锁保护 | 命中返回深拷贝；未命中写入 | key 生成失败不写缓存；异常通常 debug 记录 | 可停用/清内存；没有按任务的取消语义 | 进程退出释放；无界参数可造成内存压力，必须配置上限 |
| DSPy disk cache | `FanoutCache` 创建；16 shards、diskcache timeout=10、size limit | 返回缓存副本；内存 cache 可回填 | 反序列化失败删除坏 entry；写盘异常被吞并 | 不能把 diskcache timeout 当 LM 请求硬超时 | 目录/锁/残留要由平台缓存治理扫尾；pickle 必须可信或 restricted |
| LM/module/global history、trace、usage | `BaseLM._process_lm_response`/`_finalize_lm_response`、`Module.__call__` | 按 `max_history_size`/`max_trace_size` 滚动保留 | 可用 `disable_history`/上下文关闭；错误前可能已有 callback 事件 | 取消前已产生的 usage/event 需标记 partial，不应伪装成功 | `GLOBAL_HISTORY` 是进程全局运行态；禁止作为跨进程事实源 |
| `ThreadPoolExecutor`、Future、并行任务 | `ParallelExecutor.execute` 创建；运行核心应持有 | 收集结果并关闭进度条 | `max_errors` 触发 `cancel_jobs`，未完成任务返回取消异常 | SIGINT 设置 event；straggler 达 timeout 时最多重提交一次；`shutdown(wait=False)` 不等于已停止 | 线程无法安全强杀；平台必须独立进程/租约/强杀回收并验证无残留 |
| `TrainingJob`/`ReinforceJob`、训练线程 | `LM.finetune` 创建线程和 `TrainingJob`；provider 持有远端 job | `Future.set_result` 返回新 LM；RL 由 provider checkpoint/terminate | `_run_finetune_job` 捕获异常并写入 Future | `TrainingJob.cancel` 默认仅 Future 语义；provider 必须覆盖远端取消；LM 留有 cancel TODO | 训练远端 job、文件、线程可能脱离父进程；平台必须有 job owner、status poll、回收和超时 |
| save/load 文件、pickle/cloudpickle | `BaseModule.save`/`Settings.save`/LM state；调用方提供路径 | JSON/state 或 program 制品写入 | 非可序列化/版本不一致警告或失败 | 取消写入要采用临时文件+原子替换，源码当前未统一保证 | 不可信 pickle 可执行任意代码；平台只允许可信制品和签名校验 |

本表区分了“源码中有释放/上限钩子”和“当前核对真实证明已释放”。DSPy 当前只读静态证据不足以证明 provider、网络流、线程、远端训练 job 在四种终态均无残留。

## 16. 失败、超时、取消与状态裁决

| 场景 | 源码行为 | 平台必须保留的语义 |
|---|---|---|
| 签名格式/字段方向非法 | `_parse_signature` 要求恰好一个 `->`；`SignatureMeta._validate_fields` 要求 `InputField`/`OutputField` | `invalid_contract`，不重试，不调用 provider |
| 未配置或类型错误 LM | `Predict._forward_preprocess` 在 adapter 前检查 LM 是否为 `BaseLM`；缺失直接 `ValueError` | `not_configured`/`invalid_dependency`，在 admission 阶段失败 |
| provider 认证、计费、限流、服务、传输、模型或上下文窗口错误 | `LM._wrap_litellm_exception` 按异常/status 映射 `LMAuthError`、`LMBillingError`、`LMRateLimitError`、`LMServerError`、`LMTransportError`、`LMTimeoutError`、`ContextWindowExceededError` 等；LiteLLM 使用 `num_retries` 和 exponential backoff | 统一错误码、provider/model/request_id/retry_after；只对标记可重试错误按预算重试；上下文窗口/非法请求不得盲目换 Adapter 重试 |
| DSPy cache 命中 | `Cache.get` 返回深拷贝并清空 usage、标记 `cache_hit=True`；LM 不把 cache hit 计入 usage | 事件标记命中、成本为零/未知、结果仍可审计；缓存不是事实源 |
| 缓存 key/反序列化/写入异常 | key 生成失败返回 miss；坏 disk entry 删除；写盘异常仅 debug 记录 | 缓存故障降级为 miss，但需有指标和可选告警；不能吞掉关键事实写入错误 |
| 评估单样本异常 | `ParallelExecutor.safe_func` 返回异常并累计 error；`Evaluate` 用 `failure_score` 填充缺失结果 | 结果必须区分成功预测、失败样本、失败分数、异常和取消；不能只报平均分 |
| `max_errors` 达阈值 | `cancel_jobs` 置位；顺序执行抛出“cancelled”，并行执行停止收集并 `shutdown(wait=False)` | 取消原因、已完成/在途/未启动分开记录；不可把未执行样本当失败分数或成功 |
| SIGINT/任务取消 | 顺序路径捕获 `KeyboardInterrupt`；并行 handler 设置 event 并调用原 handler | 必须向 provider、线程/进程、流和临时资源传播 cancellation token，并核实终态 |
| 并行 straggler | `timeout` 只在剩余任务不多时检查，超时任务最多重提交一次；原任务可能仍运行 | 重试必须幂等且有去重键；“重新提交”不是“取消原任务”；核心需有硬超时和资源隔离 |
| fine-tune/RL job 取消 | `TrainingJob.cancel` 默认只调用 `Future.cancel()`；OpenAI provider 有 provider 级取消；`LM._run_finetune_job` 注释明确未统一监听 KeyboardInterrupt | job 状态必须由 `created/running/succeeded/failed/cancel_requested/cancelled/timed_out` 等统一状态机裁决，provider 负责实际终止 |
| stream listener/流式响应异常 | LM 通过 `MemoryObjectSendStream` 发送 chunk，`LMOutputBuilder` 组装；异常路径和下游关闭责任不在统一核心 | stream owner、关闭方、背压、取消和残留必须显式；不能只把 chunk 当普通返回值 |

### 16.1 状态分层

| 状态对象 | DSPy 当前状态来源 | 平台化解释 |
|---|---|---|
| 配置 | `Settings.main_thread_config` + `contextvars` 覆盖；`configure` 有 owner thread/task 限制 | 运行上下文快照；不得由任意线程隐式改全局配置 |
| 模块 | `Module._compiled`、`callbacks`、`history`；`BaseModule` 跳过 compiled 子模块 | 编译候选/已编译制品/已激活制品必须分开；不可用布尔值代替控制面状态 |
| 预测器 | `Predict.signature/config/lm/traces/train/demos` | 模块参数状态；保存时剔除密钥和运行态，加载需版本/信任校验 |
| LM | `model/model_type/cache/num_retries/provider` + history；没有统一状态枚举 | 支持库对象只保存可重建配置；连接、会话、请求、provider job 属于运行时资源 |
| 评估 | `EvaluationResult(score, results)`，一次调用生成结果 | 评估制品带数据集版本、指标版本、模型/模块制品摘要和失败/取消统计 |
| 优化/编译 | `Teleprompter.compile` 返回 `Module`；部分优化器写 `student._compiled=True` | 编译任务由模块库发起，核心记录候选、指标、预算、父子关系和激活指针 |
| 训练/RL | `Future` 与 provider `status()`/`terminate()`/checkpoint | 统一 job 状态和资源租约，provider 只实现远端动作 |
| 缓存 | 内存 LRU、diskcache、命中标志 | 可重生成的工程加速层，设置 owner/配额/清理策略，不参与事实写入 |

## 17. L0-L4 真假验证矩阵

沿用源码参考库统一标准：

```text
L0：README/注释/命令表/函数声明存在
L1：源码中存在可执行路径
L2：测试源码覆盖该路径
L3：当前核对真实执行，记录命令、退出码、测试数和输出
L4：外部依赖/真实宿主/真实服务/真实资源释放已验证
```

| 结论项 | L0 | L1 | L2 | L3 | L4/当前边界 |
|---|---:|---:|---:|---:|---|
| Signature/Module/Predict/Adapter 主链 | ✓ 文档和 API 声明 | ✓ `signature.py`、`module.py`、`predict.py`、`adapters/` | 有对应模块/适配器测试目录 | **当前核对未运行** | 未接真实 provider |
| LM provider/错误/缓存 | ✓ docstring/依赖声明 | ✓ `clients/base_lm.py`、`lm.py`、`provider.py`、`cache.py` | `tests/clients/test_lm.py`、`test_cache.py`、`test_lm_local.py` 存在 | **当前核对未运行** | LiteLLM/API key/真实网络未验证 |
| Evaluate/编译优化 | ✓ `Evaluate`/`Teleprompter` API | ✓ `evaluate.py`、`teleprompt/`、`gepa/` | `tests/evaluate/test_evaluate.py`、`tests/teleprompt/test_teleprompt.py` 及优化器测试存在 | **当前核对未运行** | 外部 GEPA/真实模型质量未验证 |
| 缓存/历史/序列化 | ✓ save/load/cache 声明 | ✓ `clients/cache.py`、`settings.py`、`base_module.py` | `tests/clients/test_cache.py`、保存/设置相关测试存在 | **当前核对未运行** | 磁盘权限、pickle 信任边界、崩溃残留未验证 |
| 并发/超时/取消/训练 job | ✓ docstring/参数 | ✓ `parallelizer.py`、`provider.py`、`clients/openai.py` | `tests/utils/test_parallelizer.py`、provider/并行测试存在 | **当前核对未运行** | 真实强杀、远端取消、线程/进程/端口清理未验证 |
| 平台统一网关与单链路 | **DSPy 无统一平台网关声明** | **目标源码未见平台注册/HTTP/MCP 统一调用器** | DSPy MCP 测试只覆盖可选协议边界 | **当前核对未运行** | **L4 不成立，必须平台侧另行设计/实测** |

因此当前核对只能写：**L0/L1 已由文档和源码确认，L2 有测试源码覆盖，L3/L4 未验证**。测试文件存在不等于测试通过；当前核对没有安装依赖、启动 LiteLLM/HTTP/MCP/向量服务、调用真实模型、强杀线程/进程或验证远端训练取消，不能写“当前核对验证通过”。

## 18. 后续装配计划与验收契约

1. **需求与能力搜索**：先把“模型调用、模块执行、评估、编译/优化、训练 job、缓存读写、状态查询”登记为候选能力，搜索平台现有能力并确认是否已有唯一 owner。
2. **模型支持库**：以 `LMRequest/LMResponse`、统一错误、usage/cost/cache 元数据、provider 能力探测、重试预算、训练 job 句柄为公开契约；每个 provider 单独受管，API key/连接/线程不出边界。
3. **模块库**：以 `Signature`、`Module/Predict`、Adapter、Evaluate、Teleprompter/GEPA 的流程模型为候选模块；模块只保存能力 id/契约版本/制品引用，不保存 provider 私有对象。
4. **运行核心**：实现一次 admission、唯一调用器、请求上下文、超时/取消 token、重试预算、并发/队列上限、事件和资源租约；四种终态均需读回线程、进程、连接、缓存、临时目录和 job 状态。
5. **统一网关**：HTTP/MCP/SDK/CLI 只做协议转换、认证、权限、限流、幂等、版本和统一结果；所有入口转到同一能力 id/调用器，禁止直连 LiteLLM 或 `dspy.LM`。
6. **制品和状态**：评估结果、优化候选、编译模块、激活版本分别不可变保存；以签名/版本/激活指针发布，`_compiled` 只作为模块内部冻结提示，不承担回滚。
7. **验收契约**：至少包含正常调用、缺 LM、非法 Signature、provider 认证/限流/超时/上下文窗口、缓存命中/坏 entry、评估单样本失败、max_errors、主动取消、SIGINT、straggler 重提交、训练 job cancel、stream 关闭、崩溃恢复和二次释放；每项记录 L0-L4、命令、退出码、测试/跳过数、外部依赖和资源残留。
8. **装配前置**：未完成需求确认、能力命中、复用/升级/新建/废弃裁决、占用租约和验收契约前，不对生产底座实施任何新增能力。

后续最终裁决：**吸收** DSPy 的规范 LM 类型、声明式签名/模块、评估编译闭环、provider 隔离和缓存/历史边界；**升级** 模型支持库与运行核心的 typed 契约、错误/重试/资源生命周期；**新建** 平台唯一能力调用器和统一网关装配；**隔离/废弃** 直接把 DSPy 全局 Settings、隐式 fallback、线程弱取消、provider 私有对象和 Python SDK 当作平台治理或统一网关的做法；外部真实资源释放和跨进程语义继续 **待核**。
