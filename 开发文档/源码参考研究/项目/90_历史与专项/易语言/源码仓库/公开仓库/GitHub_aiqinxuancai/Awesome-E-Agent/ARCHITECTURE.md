# Awesome-E-Agent 架构与内容边界

> 本文件是 `Awesome-E-Agent` 项目根唯一的架构事实源。本文档只描述当前仓库实际存在的内容，并将 README 中关于相关项目的宣传性/操作性描述与本仓库自身实现严格区分。

## 1. 项目定位

`Awesome-E-Agent` 当前是一个面向易语言开发者的实践白皮书，而不是可执行的 Agent、IDE 插件或打包器源码仓库。仓库当前提交只包含 `README.md`，README 以“三条路径”说明如何让 AI 理解、迁移或接管易语言项目：

1. **AI 驱动的语言迁移**：使用 `e-packager` 解包，再由 `Claude Code`、`Codex` 等 Agent 将易语言源码迁移为 C#、C++、Python 等现代语言。
2. **AutoLinker**：在易语言 IDE 内嵌 AI 对话，并通过本地 MCP 服务让外部 Agent 操作易语言工程。
3. **e-packager + AI 开发**：将二进制 `.e` 项目解包为可读目录，允许 Git 和 AI Agent 直接处理文本源码，完成后重新封包。

README 的核心结论是：易语言存量代码可以通过解包、上下文注入、Agent 编辑和重新封包接入现代工程工作流；其中路径一被标为“最推荐”。这些是项目文档中的方案描述，不等同于本仓库已经实现或验证的能力。

## 2. 当前可确认的范围

```text
易语言项目 / .e 文件
        │
        ├── 路径一：e-packager unpack
        │          └── 文本源码 + AGENTS.md → Claude Code / Codex → 现代语言项目
        │
        ├── 路径二：AutoLinker.fne 加载到易语言 IDE
        │          ├── IDE 内 AI 对话面板 → OpenAI-compatible 模型服务
        │          └── LocalMCP :19207/mcp → 外部 Agent → 读取/搜索/编辑/编译/命令
        │
        └── 路径三：e-packager unpack
                   └── src/*.txt、*.xml + project/image/audio/info.json
                              ↓ AI Agent 修改
                         e-packager pack → 新的 .e 文件

本仓库（Awesome-E-Agent）
        └── README.md：方案说明、命令示例、能力清单、路径对比和相关资源链接
```

上图中从“易语言项目 / `.e` 文件”开始的部分是 README 记录的外部工作流；本仓库自身的可执行边界截至当前版本只有 Markdown 文档，没有实现上述工具或服务的源码。

## 3. 版本基线与仓库状态

| 项目 | 现场结果 |
|---|---|
| 本地项目根 | `/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/GitHub_aiqinxuancai/Awesome-E-Agent` |
| Git 分支 | `main` |
| 远程 | `https://github.com/aiqinxuancai/Awesome-E-Agent.git` |
| 本地 HEAD | `40fd1b637d59e3b99d5f467ba22dc9ff933f0665` |
| 本地 HEAD 时间 | `2026-06-08T17:47:53+08:00` |
| HEAD 提交说明 | `Update README.md` |
| 远程 `HEAD` / `origin/main` | `40fd1b637d59e3b99d5f467ba22dc9ff933f0665` |
| 工作树 | 初始检查无源码改动、无未跟踪文件；本次仅新增本文件 |
| 远程新鲜度 | `git ls-remote` 返回的远程 `HEAD` 与本地 HEAD 相同，无需 fetch 或独立快照 |
| 提交历史 | 当前本地仓库为浅克隆；当前可见历史只有根提交 `Update README.md` |

版本结论仅基于现场 Git 元数据。没有执行安装、服务启动、构建或代码运行。

## 4. 真实目录地图

当前 `HEAD` 的源码树只有：

```text
Awesome-E-Agent/
├── README.md              # 易语言 × AI Agent 实践白皮书
└── .git/                  # Git 元数据，不属于项目运行层
```

本次建档新增：

```text
└── ARCHITECTURE.md        # 本文件；项目根唯一架构文档
```

以下目录/文件在当前提交中均未发现：`src/`、`project/`、`image/`、`audio/`、`info.json`、`AGENTS.md`、`CLAUDE.md`、`package.json`、`pyproject.toml`、`requirements.txt`、`*.csproj`、`*.sln`、`*.e`、`*.ec`、测试目录及 CI 配置。README 中展示的这些路径属于 e-packager 解包后目标项目的示例布局，不是本仓库实际目录。

## 5. README 内容分层

### 5.1 路径一：AI 驱动的语言迁移

README 第 23—79 行描述以下文档化流程：

```text
e-packager unpack LegacyApp.e LegacyApp/
        ↓
cd LegacyApp
        ↓
claude  或  codex
        ↓
读取 AGENTS.md 与 src/ 下源码
        ↓
重写为 C# / C++ / Python / 其他现代语言
        ↓
Review + 修正
```

README 给出的示例命令是：

```bash
e-packager unpack LegacyApp.e LegacyApp/
cd LegacyApp
claude
```

README 还给出一个迁移提示词示例，要求将 `src/` 下业务逻辑完整重写为 C# + WPF (.NET 10)。该提示词是使用示例，不是本仓库的 CLI、配置或测试契约。

### 5.2 路径二：AutoLinker IDE + LocalMCP

README 第 83—230 行将 `AutoLinker` 描述为外部易语言支持库插件：

```text
易语言 IDE
   ├── AutoLinker.fne → AI 对话面板 → OpenAI-compatible 模型服务
   └── LocalMCP → http://127.0.0.1:19207/mcp → Claude Code / Codex / Gemini CLI
```

README 记录的 LocalMCP 日志示例为：

```text
[AutoLinker][LocalMCP] listening on http://127.0.0.1:19207/mcp
```

README 记录的外部 MCP 配置边界：

- `Claude Code`：`~/.claude.json`，`transport` 为 `streamable_http`，URL 为 `http://127.0.0.1:19207/mcp`。
- `Codex`：`~/.codex/config.toml`，`[mcp_servers.AutoLinker]` 的 `url` 指向同一地址。
- `Gemini CLI`：`~/.gemini/settings.json`，使用 `streamable_http` 与同一地址。

这些配置属于外部客户端接入 AutoLinker 的文档示例；当前仓库没有对应 MCP server 实现、配置加载器、协议处理器或客户端适配代码。

### 5.3 路径三：e-packager 解包/编辑/回包

README 第 232—298 行给出的目标目录形态是：

```text
MyApp.e
  └── e-packager unpack
        └── MyApp/
            ├── src/          # 源码 .txt 与窗口 .xml
            ├── project/      # 元数据（README 标注勿删）
            ├── image/        # 图片资源
            ├── audio/        # 音频资源
            ├── AGENTS.md     # AI 项目说明
            └── info.json     # 文件元信息
```

README 给出的操作命令为：

```bash
e-packager unpack MyApp.e MyApp/
cd MyApp
claude
# 或 codex
e-packager pack MyApp/ MyApp_new.e
```

也记录了在项目目录直接运行 `e-packager`、将输出放到 `pack/` 的使用方式。该目录、命令和元数据格式均来自 README 对外部 `e-packager` 的说明，本项目没有这些命令的实现。

## 6. API、CLI、SDK 与协议边界

### 6.1 本仓库自身

- **API**：未发现 HTTP、RPC 或其他 API 入口。
- **CLI**：本仓库没有可执行文件、脚本、入口模块或命令行解析器。
- **SDK/插件**：本仓库没有 SDK、易语言支持库、`.fne` 插件或 Agent runtime。
- **协议**：本仓库没有 MCP server/client 实现。README 只描述外部 `AutoLinker` 的 `streamable_http` MCP 接入方式。

### 6.2 README 记录的外部能力名

README 的“工具集”表列出以下外部 AutoLinker 工具名：

| 能力 | README 中的工具名 |
|---|---|
| 读取当前页完整源码 | `get_current_page_code` |
| 搜索整个工程源码 | `search_public_code` |
| 列出并搜索支持库声明 | `search_support_library_public_code` |
| 搜索模块公开接口 | `search_available_module_public_code` |
| 精确编辑任意程序树页面 | `edit_program_item_code` |
| 批量修改多个页面 | `multi_edit_program_item_code` |
| 触发编译并获取结果 | `compile_with_output_path` |
| 执行 PowerShell 命令 | `run_powershell_command` |
| 联网搜索参考资料 | `search_web_tavily` |

由于源码不在本仓库，无法从实现核实这些工具的参数、返回值、权限模型、错误协议、并发语义或真实可用性。它们应被视为待对 `AutoLinker` 源码逐项复核的外部接口线索。

## 7. 数据模型与持久化

### 7.1 本仓库

当前项目没有运行时数据模型、数据库、缓存、配置文件、序列化协议或持久化层。唯一实际内容是 Markdown 文本。

### 7.2 README 描述的外部解包数据

README 对 e-packager 输出目录给出了若干文件类别，但没有给出字段级 schema 或校验规则：

| 数据类别 | 文档化位置 | 当前可确认程度 |
|---|---|---|
| 易语言源码文本 | `src/*.txt` | README 明确描述为可读源码；未在本仓库实测 |
| 窗口描述 | `src/*.xml` | README 明确列出；未提供 XML schema |
| 项目元数据 | `project/` | README 标注“勿删”；未提供文件清单或字段定义 |
| 图片资源 | `image/` | README 列出目录；未提供格式约束 |
| 音频资源 | `audio/` | README 列出目录；未提供格式约束 |
| Agent 规范 | `AGENTS.md` | README 称由 e-packager 自动生成/供 AI 读取；未提供生成模板实现 |
| 文件元信息 | `info.json` | README 列出文件名；未提供 JSON schema |

因此，不能据此推导数据字段、版本兼容性、编码、事务边界或回包完整性保证。

## 8. 依赖、入口与运行方式

现场检查 `HEAD` 文件树和根目录后：

- 未发现包管理清单或依赖锁定文件；本仓库没有可安装的运行时依赖。
- 未发现应用入口、服务入口、插件入口或构建工程。
- 未发现 `Dockerfile`、CI workflow、发布脚本或部署配置。
- README 中出现的 `e-packager`、`AutoLinker.fne`、`Claude Code`、`Codex`、`Gemini CLI`、`.NET 10` 和 OpenAI-compatible API 均为外部工作流中的工具/技术名称，不是本仓库的依赖声明。
- README 中的 `e-packager unpack`、`e-packager pack`、`claude`、`codex` 是文档示例命令；没有本地入口可执行验证。

## 9. 测试与验证结构

当前仓库没有测试文件、测试目录、测试框架配置或 CI 测试工作流。因此：

- **测试存在性**：未发现。
- **测试执行结果**：没有可执行测试；本次未安装依赖、未启动服务、未构建项目。
- **文档可验证项**：已核对本地 Git 状态、当前提交、远程 `HEAD`/`origin/main`、文件树及 README 内容；Markdown 变更通过 `git diff --check` 后才可视为文档格式检查通过。
- **外部项目验证**：未把 `AutoLinker` 或 `e-packager` 当作本项目代码运行；其接口和格式仍需分别进入对应仓库复核。

## 10. 风险、未确认项与后续细探

### 已确认

1. `Awesome-E-Agent` 当前提交只有 `README.md`，本身是方案型白皮书。
2. 本地 `HEAD` 与远程 `HEAD`、`origin/main` 同为 `40fd1b637d59e3b99d5f467ba22dc9ff933f0665`，当前没有远程落后需要通过 `127.0.0.1:4780` 获取独立快照的情况。
3. README 提供三条工作流、示例目录、示例命令、AutoLinker MCP 地址和工具名，但没有实现代码。

### 未确认

1. README 所述 `AutoLinker` 当前版本是否仍暴露全部列出的工具，需读取 `https://github.com/aiqinxuancai/AutoLinker` 当前源码和远程版本。
2. README 所述 `e-packager` 的 `.e` 解包格式、`info.json` schema、编码、回包兼容性和异常恢复，需读取 `https://github.com/aiqinxuancai/e-packager` 当前源码、测试和发布物。
3. `streamable_http` MCP 服务的认证、并发、生命周期、错误返回、Windows 权限边界和编译副作用，README 未说明。
4. AI 迁移示例中的“功能基本都完整”属于作者经验描述；没有本仓库内的验收样例、差分测试或可重复实验记录。
5. README 中引用的模型名称、`.NET 10` 和客户端命令可能随远程项目或工具版本变化；当前仅记录为文档基线。

### 后续复核建议

- 仅在明确启动外部项目专项研究时，分别建立 `AutoLinker` 与 `e-packager` 的源码证据；不要把它们的实现事实回填为 `Awesome-E-Agent` 自身能力。
- 对 AutoLinker：优先核对 LocalMCP server 注册、工具 schema、IDE 当前页上下文、编辑写回、编译结果返回和 PowerShell 执行边界。
- 对 e-packager：优先核对 `unpack`/`pack` 的格式版本、路径遍历防护、资源复制、编码和失败回滚。
- 对迁移路径：补充一个可公开复现的输入 `.e` 样例、迁移前后行为测试和人工 Review 记录，再讨论“完整迁移”结论。

以上未确认项保留在正式文档中，不以 README 的说明替代源码、测试或运行证据。

## 11. 证据索引

| 证据 | 用途 |
|---|---|
| `README.md:1-330` | 项目定位、三条路径、目录示例、命令、MCP URL、工具名和相关资源 |
| `git ls-tree -r --name-only HEAD` | 核实当前提交实际文件树只有 `README.md` |
| `git status --short --branch` | 核实初始工作树状态与分支 |
| `git log -1 --format='%H%n%ad%n%s' --date=iso-strict` | 核实本地版本、时间和提交说明 |
| `git remote -v` | 核实远程地址 |
| `git ls-remote origin HEAD refs/heads/main refs/heads/master` | 核实远程版本基线；本地与远程 HEAD 一致 |
| 本文件 | 唯一架构归档入口；后续事实更新应直接维护本文件 |

## 12. 归档声明

当前目标根未发现旧的 `细探-*.md` 或其他架构细探文件，因此没有可吸收或删除的旧细探内容。后续若出现细探文档，必须先逐条回到源码/测试核实并吸收到本文件，再按任务授权处理旧文件；不得让平行摘要替代本文件。

## 13. 第三轮：易语言 Agent 样例到通用底座的映射

### 13.1 研究边界与产品语义隔离

本轮研究对象不是本仓库内的 Agent 实现，而是 README 所描述的三个外部工作流：`e-packager` 的解包/回包、`AutoLinker.fne` 在易语言 IDE 内的 AI 面板与 LocalMCP、以及 Claude Code/Codex/Gemini CLI 等外部 Agent。当前仓库没有这些组件的源码、协议实现或测试；以下“通用底座映射”是基于 README 的边界抽取和架构裁决，不是已落地能力。

必须隔离、不能直接进入通用底座核心的产品语义包括：

- 易语言专有对象：`.e`、`.ec`、支持库、程序树页面、易语言 IDE、`AutoLinker.fne`；
- 产品专有入口：`LocalMCP`、`http://127.0.0.1:19207/mcp`、`get_current_page_code` 等工具名；
- 产品专有文件：`src/*.txt`、`src/*.xml`、`project/`、`image/`、`audio/`、`info.json`、同名 `.AGENTS.md`；
- 产品专有命令和宿主：`e-packager unpack/pack`、`run_powershell_command`、Windows/易语言编译器；
- 示例中的模型、客户端和版本：`claude-opus-4-5`、`gpt-4o`、`gemini-2.5-pro`、Claude Code、Codex、Gemini CLI、`.NET 10`。

它们应全部落在**项目适配层、协议适配层或 provider**，由唯一能力注册表归一化为通用能力 id、统一输入输出和统一错误，不得让核心模块依赖上述名称。产品语义只有在边界适配器中出现一次；任何上层任务、审计、重试和资源治理都使用通用字段。

### 13.2 组件、命令、模型/工具调用、配置、任务和资源映射

| README 样例元素 | 通用底座抽象 | 唯一 owner/边界 | 第三轮裁决 | 证据状态 |
|---|---|---|---|---|
| 易语言 IDE + `AutoLinker.fne` | `ProjectHostAdapter` / 交互式宿主适配器 | 项目适配层；核心不持有 IDE 对象 | **隔离**；仅负责当前工程、页面和宿主回写 | README:83-114；无本地实现 |
| AutoLinker AI 对话面板 | `AgentSessionClient` / 会话前端 | 会话网关 | **复用**通用会话能力，不复制一套 Agent 内核 | README:87-112；未核实实现 |
| LocalMCP `streamable_http` | `ProtocolIngressAdapter` | 统一网关的协议入口 | **升级/复用**统一 MCP/HTTP 入口；不得形成第二条业务链 | README:118-176；无 server 源码 |
| `e-packager` | `ArtifactTransformProvider` | 制品/项目适配器 | **隔离 provider**；`unpack` 和 `pack` 不是底座业务流程 | README:232-287；无本地实现 |
| Claude Code/Codex/Gemini CLI | 外部 Agent 客户端 | 外部调用方 | **隔离**；只提交任务或调用网关，不成为平台内部 owner | README:43-64、116-176 |
| Base URL/API Key/模型 ID | `ModelProviderProfile` | provider 注册表 + 秘密存储 | **复用**模型配置契约；Key 不进入任务、日志或项目文件 | README:98-110；字段语义未有源码验证 |
| `get_current_page_code` | `project.read.current` | 能力注册表 → 项目适配器 | **归一化别名**，不把产品名作为公共 id | README:178-192；schema 待核 |
| `search_public_code` | `project.search.source` | 能力注册表 → 索引/源码适配器 | **复用/待核**；统一分页、大小上限和权限 | README:178-192 |
| `search_support_library_public_code` | `project.search.dependency_api` | 支持库索引适配器 | **复用/待核**；不能让 Agent 直接读宿主内部结构 | README:180-192 |
| `search_available_module_public_code` | `capability.catalog.search` | 模块/能力目录 owner | **复用**平台能力发现，不另建产品目录 | README:180-192 |
| `edit_program_item_code` / `multi_edit_program_item_code` | `project.patch` / `project.batch_patch` | 项目写入 owner | **升级**统一写入契约，要求版本、幂等键、审计和回滚 | README:182-190；无参数/返回值证据 |
| `compile_with_output_path` | `project.validate.build` | 构建执行器 | **复用/隔离 provider**；统一结果模型，编译器留在 provider | README:188-191 |
| `run_powershell_command` | `host.command.exec` | 受策略约束的进程执行器 | **高风险隔离**；默认拒绝，必须沙箱、超时、输出截断和进程组清理 | README:190-192；权限边界待核 |
| `search_web_tavily` | `knowledge.retrieve.web` | 外部检索 provider | **复用**统一检索能力；域名、凭证和成本策略由网关持有 | README:190-192 |
| `e-packager unpack/pack` | `artifact.import` / `artifact.export` | 制品转换入口 | **统一命令契约**；输入清单、临时目录、校验和、失败清理必须显式 | README:37-40、252-287；未运行 |
| 项目 `.AGENTS.md` | `ProjectContextPolicy` | 上下文装配器 | **隔离内容、复用机制**；需版本/hash、来源和不可信标记，不能隐式覆盖系统策略 | README:200-219；生成规则待核 |
| `src/`、`project/`、资源目录 | `WorkspaceManifest` + `ArtifactStore` | 工作区/制品 owner | **复用资源边界**；按 manifest 管理读写，不把目录名写进核心 | README:242-249；schema 待核 |

### 13.3 模型调用与工具调用的统一契约

README 只证明“可配置模型”和“工具名线索”，没有证明参数、返回值、错误码或调用顺序。因此底座应采用下列唯一链路，而不是让内嵌面板、MCP 客户端和 CLI 各自实现一套 Agent：

```text
用户目标
  → TaskCommand（任务 id、项目范围、权限、幂等键）
  → 统一会话/任务网关
  → ProjectContextPolicy + WorkspaceManifest（装配上下文）
  → ModelProvider（模型请求/流式结果/用量）
  → CapabilityRegistry（唯一能力 id 与 schema）
  → CapabilityExecutor（项目读写、检索、构建、受控命令）
  → 结果归一化 + 事件/审计
  → 必要时再次调用 ModelProvider
  → verify / artifact.export
```

`AutoLinker` 面板、LocalMCP 和外部 CLI 只是三种 ingress；它们必须在“统一会话/任务网关”处汇合。产品工具名只能在 ingress adapter 中映射一次，例如 `edit_program_item_code → project.patch`，不能让模型、模块和审计分别认识一组别名。模型不能直接取得宿主对象、数据库连接或 PowerShell 句柄；工具执行器只接收经过 schema 校验的值，并返回统一的 `success/result/error/evidence/resource_delta` 结构。

### 13.4 配置、任务和资源边界

| 边界 | 创建/持有者 | 允许内容 | 成功释放/提交 | 失败、取消、崩溃要求 |
|---|---|---|---|---|
| provider 配置 | 配置中心/秘密存储 | endpoint、模型 id、超时、预算、能力白名单；API Key 只引用 secret | 任务只读快照并记录 profile 版本 | 缺失/失效时在调用前失败；禁止把 secret 写入 prompt、日志和 diff |
| 项目上下文 | 项目适配器 + context assembler | manifest、规范文件、源码摘要、版本/hash | 以 context snapshot id 关联模型调用 | 文件变化、超限或策略冲突时重新快照/拒绝；不可信文档不能覆盖系统策略 |
| 任务/会话 | 任务网关 | task id、parent id、状态、幂等键、取消令牌、配额 | 终态事件写入事实/审计 owner | `queued/running/waiting_tool/verifying/succeeded/failed/cancelled/expired/recovered` 状态单向迁移；重试不得重复写入 |
| 模型上下文 | ModelProvider adapter | messages、工具 schema、截断策略、usage | 返回 normalized response 和 usage | 超时/断线/无效响应可重试但必须带 attempt；不可恢复错误终止任务 |
| 工作区/临时目录 | Workspace manager | 输入制品、staging、编译输出、日志 | 成功提交制品后删除临时目录 | 业务失败、取消、超时、宿主崩溃都执行清理和残留扫描；禁止任意路径写入 |
| 工具/进程 | CapabilityExecutor | 受控参数、环境白名单、资源预算 | 关闭句柄、回收子进程组、记录 exit code | 超时杀进程组；崩溃后重启扫描 pid/临时文件/锁；二次释放必须幂等 |
| 外部制品 | ArtifactStore / export provider | 原始 `.e`、解包目录、回包文件、manifest/hash | 原子 rename 或版本指针切换 | 部分写入不得覆盖旧版本；校验失败回滚 staging，保留证据 |

这张表是通用底座的边界契约，不是对本仓库当前实现的声明。当前仓库没有任务状态机、配置加载器、工作区管理器、模型客户端或进程执行器。

## 14. 唯一链路与生命周期

### 14.1 单一权威调用链

```text
AutoLinker 面板 / LocalMCP / 外部 CLI
        ↓（三个入口仅做协议与产品语义归一化）
统一任务网关：认证、授权、幂等、配额、取消、审计
        ↓
项目适配器：IDE 当前工程 或 解包文本工作区
        ↓
上下文装配器：ProjectContextPolicy + WorkspaceManifest + 版本快照
        ↓
唯一 ModelProvider / CapabilityRegistry
        ↓
唯一 CapabilityExecutor：读、搜、改、编译、检索、受控命令
        ↓
事实/制品 owner：staging → verify → commit/export
        ↓
统一事件、结果、用量、错误和资源残留证据
```

禁止以下侧链：面板直连模型并自行写工程、MCP server 复制一套编辑逻辑、CLI 绕过网关直跑编译器、模块各自解析 `.e`、模型直接执行 PowerShell、失败时隐藏 fallback 到另一 provider。不同产品入口可以不同，但业务能力、写入 owner、错误归一化和资源清理必须只有一份。

### 14.2 生命周期状态与终态处理

| 阶段 | 进入条件与动作 | 权威状态/证据 | 四类终态处理 |
|---|---|---|---|
| `discover` | 校验 `.e` 或工作区、manifest、版本和权限 | `task.accepted`、输入 hash | 非法输入立即失败，不创建长生命周期资源 |
| `prepare` | 建立隔离 staging、context snapshot、取消令牌 | workspace id、snapshot id | 失败删除 staging；保留输入只读 |
| `plan` | 读取项目规范，调用模型生成计划/工具请求 | model attempt、usage、tool schema hash | 超时/断线按 attempt 重试；取消停止后续调用 |
| `execute` | 注册表查能力，schema 校验后执行读/搜/改/编译 | tool call id、参数摘要、exit code | 重复 call 以幂等键去重；进程失败回收进程组 |
| `stage` | 写入 staging，生成 diff、manifest、输出日志 | staged artifact hash | 冲突或部分写入不覆盖权威版本，转 `failed` |
| `verify` | 编译/检查/格式或行为验收 | verification level、结果和证据路径 | 编译失败可回到 plan，但有次数/预算上限 |
| `commit/export` | 原子提交工作区变更或 `artifact.export` | 新制品 hash、父版本、提交事件 | 回包失败保留旧版本，清理新 staging |
| `close/recover` | 写终态、释放上下文/进程/临时目录并扫描残留 | `task.finished` + cleanup report | 取消/超时/崩溃必须可恢复；残留转告警，不伪报成功 |

当前只具备 README 级流程线索，以上状态名、事件名和清理报告均应视为底座验收契约，不能写成 AutoLinker 或 e-packager 已实现。

## 15. 失败矩阵（底座验收输入）

| 失败场景 | 检测点 | 统一处理 | 必须清理/保留的证据 | 本仓库状态 |
|---|---|---|---|---|
| 输入 `.e` 不存在、格式未知或路径越界 | `discover` | 拒绝任务，不调用模型 | 输入路径、校验错误、无 staging 残留 | 未验证；README 只给命令 |
| `unpack` 部分成功/manifest 缺失 | `prepare`/import provider | 原子失败，隔离并删除 staging | 输入 hash、失败文件、provider exit code | 未验证 |
| `.AGENTS.md` 缺失、过期或含冲突指令 | context assembler | 标记不可信/需确认，不覆盖系统策略 | 文件 hash、来源、冲突项 | 未验证 |
| model endpoint 不可达、Key 无效或额度耗尽 | provider preflight | 在工具执行前失败；按错误类型限次重试 | profile 版本、脱敏错误、attempt/usage | 未验证 |
| 模型响应超时、断流、格式非法 | model adapter | 终止当前 attempt；可重试且不可重复副作用 | request id、attempt、截断原因 | 未验证 |
| 工具 id 未注册、schema/权限不通过 | registry/executor | 拒绝工具调用，不执行副作用 | canonical capability id、schema errors | 未验证 |
| 并发编辑导致版本/hash 冲突 | project write owner | 重新读取并生成 patch 或人工确认，禁止盲写 | base hash、current hash、diff | 未验证 |
| `edit` 写入失败或部分写入 | staging | 回滚到临时版本，权威版本不变 | before/after hash、写入日志 | 未验证 |
| 编译器缺失、编译失败或输出越界 | build provider | 归一化诊断；按预算回到 plan 或失败 | stdout/stderr、exit code、输出 hash | README 仅声明工具名 |
| PowerShell/外部命令被拒绝、超时或产生子进程 | process executor | 默认拒绝；超时杀进程组 | 命令摘要、策略命中、pid 清单 | 权限/并发待核 |
| 网络检索失败、结果不可信或超预算 | retrieval provider | 降级为无检索或失败，不能静默编造 | URL、响应状态、来源 hash | 未验证 |
| 重复请求、重复事件或客户端重连 | gateway | 以 task/call 幂等键去重，返回已知结果 | idempotency key、状态迁移日志 | 未验证 |
| 用户取消、任务超时 | task manager | 传播取消令牌，停止新调用并清理资源 | cancel reason、终态、cleanup report | 未验证 |
| IDE/Agent/子进程崩溃 | supervisor/recovery | 从 snapshot 恢复或标记 `recovered/failed`，不得假成功 | crash marker、残留扫描、父版本 | 未验证 |
| `pack/export` 校验失败或目标已存在 | export provider | 原子替换前拒绝；保留旧制品 | manifest、hash、旧/新路径 | 未验证 |

失败矩阵中的“统一处理”是产品无关的验收要求；不能用 README 中“然后去喝杯茶”或“功能基本都完整”等宣传描述替代失败证据。

## 16. L0-L4 验证分级与当前裁决

| 等级 | 严格定义 | 本项目可放入的证据 | 本轮结论 |
|---|---|---|---|
| **L0 线索/声明** | 仅有 README、示例命令、宣传语或外链描述 | 三条路径、AutoLinker 工具名、模型配置项、MCP URL、解包目录 | README:23-40、83-219、232-298；只能说明“文档声称” |
| **L1 本地静态事实** | 目标仓库文件树、Git 元数据和本地文本可复读 | 当前仓库只有 `README.md`；本文件为归档文档；无实现、依赖、测试 | 已完成；不扩展为外部组件事实 |
| **L2 契约映射/人工推导** | 将 L0 元素映射到通用能力、owner、状态和资源边界，并明确未证实项 | 本轮第 13—15 节的适配器、唯一能力 id、生命周期、失败矩阵 | 已补充；属于架构输入，不是运行证明 |
| **L3 本地可执行验证** | 读取目标实现并实际运行单测、协议探针、构建或故障注入，记录命令/退出码/清理 | 当前仓库无可执行实现、测试、依赖或服务；不能把命令示例当 L3 | 未达到 |
| **L4 外部端到端验证** | 真实 AutoLinker/e-packager/易语言 IDE/模型服务/客户端联调，覆盖成功和失败终态 | 本轮未读取外部仓库、未安装、未启动、未联调 | 未达到 |

第三轮的跨项目裁决为：

- **吸收**：将“多入口 → 唯一任务网关 → 项目适配器 → 能力注册表 → provider → 统一结果/证据”的结构吸收到通用底座原则；将任务幂等、能力 schema、制品 staging、四类终态清理和 L0-L4 作为验收契约。
- **隔离**：`AutoLinker.fne`、LocalMCP、`e-packager`、易语言 IDE、`.e`/`.ec` 文件格式、产品工具名、PowerShell 和具体模型客户端只能作为适配器/provider/外部调用方存在。
- **待核**：所有外部工具的真实 schema、鉴权、并发、取消、回滚、编译副作用、文件格式校验、资源清理和崩溃恢复；需进入对应 `AutoLinker`、`e-packager` 源码专项后才能升级验证等级。

本轮没有修改源码、依赖、配置、测试、README、Git 或外部项目；仅在目标根唯一 `ARCHITECTURE.md` 增补第三轮架构映射和验收边界。
