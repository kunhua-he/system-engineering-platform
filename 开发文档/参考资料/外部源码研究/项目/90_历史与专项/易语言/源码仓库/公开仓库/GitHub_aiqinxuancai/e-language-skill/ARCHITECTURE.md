# e-language-skill 架构说明

## 1. 项目定位

`e-language-skill` 是面向 AI Agent 的易语言（Easy Programming Language / EPL）工程开发技能包，不是易语言编译器、运行时、IDE 插件实现，也不是一个包含 `.e` / `.ec` 业务工程的可执行源码仓库。

项目通过 `SKILL.md` 提供任务分流、修改边界、入口判断、代码生成规则和验证条件；通过 `references/` 提供按需加载的语言语义、工程模型、文本格式、互操作、工具链和排错知识。目标是让 Agent 把易语言工程当作由 IDE 管理的结构化工程处理，而不是按普通文本仓库随意重写。

主要覆盖四类工作模式：

- **AutoLinker MCP**：连接已经打开的易语言 IDE，读取和修改 IDE 内存工程，并调用编译能力。
- **AutoLinker 无头编译**：直接调用带 AutoLinker 的 `e.exe` 编译磁盘上的 `.e`，输出结构化 JSON 和产物。
- **e-packager 文本工作区**：将二进制 `.e` / `.ec` 解包到可读目录，编辑受支持的 `src/*.txt` 后回包。
- **只读理解、代码生成、排错与迁移**：没有 IDE 或工具时，依据真实工程、依赖公开接口和当前 ABI 约束分析易语言代码。

另外，技能包含 BlackMoon/黑月本机编译、RC 资源、黑月界面类、Win32/DLL、窗口事件、GDI/GDI+、回调和 `置入代码` / x86 机器码的风险边界。

## 2. 总体流程图

```text
用户提出易语言工程任务
        │
        ▼
读取 SKILL.md，识别工作模式与工程类型
        │
        ├── AutoLinker MCP
        │       │
        │       ├─ refresh_workspace_mirror
        │       ├─ list_files / search_code / read_files / read_code_item
        │       ├─ read_real_file（写入前取得真实内容与 code_hash）
        │       ├─ diff_file / edit_file / multi_edit_file / write_file
        │       └─ compile_with_output_path + 运行产物验证
        │
        ├── AutoLinker 无头编译
        │       └─ e.exe <input.e> --autolinker-headless-compile
        │          → 结果 JSON → 检查退出码、ok、产物指纹 → 运行 EXE
        │
        ├── e-packager 工作区
        │       ├─ unpack <input.e|input.ec> <output-dir>
        │       ├─ 读取 AGENTS.md、project/、src/、ecom/、elib/、header/
        │       ├─ 局部编辑受支持的 src/*.txt
        │       ├─ update（仅获授权时刷新依赖/资源）
        │       ├─ pack → 新的 .e/.ec 产物
        │       └─ compare-bundle / verify-roundtrip + IDE 编译运行
        │
        └── 只读理解 / 迁移
                ├─ 搜索程序项、调用者、事件、资源和依赖公开接口
                ├─ 判断入口、页面、参数属性、数组和 ABI
                └─ 输出中文说明或经验证的最小代码片段
```

## 3. 真实目录与分层

### 3.1 仓库目录地图

当前远程基线包含以下项目文件：

```text
 e-language-skill/
 ├── AGENTS.md
 ├── LICENSE
 ├── README.md
 ├── SKILL.md
 ├── agents/
 │   └── openai.yaml
 └── references/
     ├── autolinker-headless-compile.md
     ├── autolinker-mcp.md
     ├── blackmoon.md
     ├── declarations-and-text-format.md
     ├── e-packager.md
     ├── embedded-machine-code.md
     ├── engineering-and-debugging.md
     ├── language-basics.md
     ├── patterns.md
     ├── project-model.md
     └── windows-and-interop.md
```

仓库中没有 `.e`、`.ec`、`.fne`、`.fnr`、`.rc`、源程序测试目录、运行时配置或包管理清单。`agents/openai.yaml` 只提供 Agent 显示名称、简介和默认提示，不承载运行逻辑。

### 3.2 文档分层

```text
README.md
    └─ 对外定位、安装方式、使用方式、文档地图、限制和许可证
        │
        ▼
SKILL.md
    └─ 技能入口、工作模式路由、修改前检查、入口规则、生成与验证铁律
        │
        ├─ 语言层：language-basics.md、declarations-and-text-format.md、patterns.md
        ├─ 工程层：project-model.md、engineering-and-debugging.md
        ├─ 工具层：autolinker-mcp.md、autolinker-headless-compile.md、e-packager.md
        └─ 平台层：blackmoon.md、windows-and-interop.md、embedded-machine-code.md
```

`SKILL.md` 是唯一默认入口，`references/` 是渐进式披露的历史研究资料；README 的文档地图是索引，不应被当成独立实现规范。各参考文档中的源码路径、命令、类名、函数名、字段名和协议名保留原文，解释和风险说明使用中文。

## 4. 核心数据模型与持久化

### 4.1 易语言工程模型

技能将以下对象区分为不同模型，不允许互相替代：

| 对象 | 真实性质 | 本项目中的处理结论 |
|---|---|---|
| `.e` | 易语言二进制工程，包含代码、窗口、资源、依赖和编辑信息 | 不用普通文本或十六进制替换修改 |
| `.ec` | 易模块工程，公开可复用的易语言代码接口 | 可作为独立工程自测，但被主工程引用时通常不作为主入口 |
| `.fne` / `.fnr` | 支持库动态形态，通常按易语言支持库 ABI 导出 | 只查询公开接口，不把接口导出文本当实现源码 |
| `.lib` | 支持库或原生代码静态链接产物 | 由目标编译后端和依赖决定，不能仅以 IDE 能识别命令推断可链接 |
| `src/*.txt` | e-packager 或 IDE 桥接层生成的结构化文本 | 仅在明确支持的工作区流程中局部编辑 |
| `src/*.xml` | 窗口设计器信息 | 默认只读，不猜 XML schema |
| `project/` | e-packager 回包元数据和工程辅助信息 | 不手工删除、重排或猜测性修改 |
| `ecom/` / `elib/` / `header/` | 模块、支持库和公开接口的派生快照 | 只读参考，不直接靠改快照改变依赖 |
| `image/` / `audio/` | 资源文件和 `list.json` 索引 | 只能通过 e-packager `update` 同步维护 |

### 4.2 文本声明模型

`src/*.txt` 不是自由格式 CSV，而是固定槽位文本。`.程序集`、`.子程序`、`.参数`、`.局部变量`、`.程序集变量`、`.全局变量`、`.数据类型`、`.成员`、`.DLL命令`、`.常量` 等声明的中间空槽必须保留；说明中的逗号、引号内逗号和数组维数中的逗号不能误当结构分隔符。

重点字段关系如下：

- `.子程序`：名称、返回类型、公开属性、说明；参数必须位于局部变量前。
- `.参数`：名称、类型、参数属性、说明；普通子程序使用 `参考`、`可空`、`数组`，DLL 导出文本使用 `传址`、`数组`。
- `.局部变量`：名称、类型、静态属性、数组维数、说明。
- `.程序集变量`：名称、类型、保留空槽、数组维数、说明。
- `.DLL命令`：名称、返回类型、DLL 文件名、DLL 入口名、公开属性、说明；默认调用约定和 `cdecl` 的 `@` 入口前缀必须以真实目标接口确认。
- `.数据类型` / `.成员`：字段顺序、宽度、数组维数、传址属性共同决定结构布局。

### 4.3 入口与状态

入口判断顺序为：

1. 先查是否存在窗口程序集 `_启动窗口`；存在时它优先被载入并无视 `_启动子程序`。
2. 没有 `_启动窗口` 时，查普通程序集中的 `_启动子程序`。
3. 易模块可包含 `_启动子程序`，显式编译为控制台 EXE 时可用于模块自测。
4. BlackMoon DLL 使用 `Dll入口函数`，不能套用 EXE 入口。

BlackMoon 界面类的应用初始化和唯一消息循环属于普通程序集的 `_启动子程序`，不属于易语言可视化窗口的 `__启动窗口_创建完毕`。保留 `_启动窗口` 再从其事件中调用 `应用程序类.运行` 会混叠两套窗口体系和消息循环。

### 4.4 持久化边界

本仓库持久化的是 Markdown 技能知识、YAML Agent 元数据和 MIT 许可证，版本由 Git 管理。易语言工程的代码、窗口、资源和依赖持久化在用户自己的 `.e/.ec` 及 e-packager 工作区；AutoLinker MCP 操作的是易语言 IDE 内存工程，通过镜像和 `code_hash`/CAS 写入保证基线一致。AutoLinker 镜像、编译产物、临时 JSON、运行时日志和 Windows IDE 状态均不属于本仓库持久数据。

## 5. 真实读取、写入与执行调用链

### 5.1 AutoLinker MCP 链路

AutoLinker 在易语言 IDE 中提供本地 Streamable HTTP MCP 服务，文档记录的常见地址为 `http://127.0.0.1:19207/mcp`（端口可能顺延）。首次源码读写必须先刷新镜像：

```text
易语言 IDE 内存工程
    → refresh_workspace_mirror
    → list_files / search_code / read_files / read_code_item
    → read_real_file(file_path)
       → real_source + code_hash
    → diff_file 或 edit_file / multi_edit_file / write_file
       → expected_base_hash 做 CAS 冲突保护
    → compile_with_output_path
    → 读取完整编译输出、产物路径和产物指纹
    → 按工程类型运行并测试实际行为
```

`src/*.xml` 窗口界面和控件绑定是只读边界；工具可以修改对应窗口程序集 `.txt` 的既有代码，但新增事件子程序不等于建立了事件绑定。窗口、控件、布局和事件绑定应由 IDE 设计器完成。

### 5.2 AutoLinker 无头编译链路

无头编译直接调用目标 `e.exe`，不依赖当前 MCP 会话：

```text
e.exe <input.e>
    --autolinker-headless-compile
    --autolinker-output <output>
    --autolinker-target <auto|win_exe|win_console_exe|win_dll|ecom>
    --autolinker-result <result.json>
    --autolinker-startup-timeout <seconds>
    [--autolinker-static]
        │
        ▼
独立 IDE 实例加载工程并编译
        │
        ▼
退出码 + result.json
        │
        ├─ 退出码为 0
        ├─ JSON 的 ok 为 true
        ├─ artifact_verified 或输出存在且本次编译后更新
        └─ 运行指定输出并检查 stdout / 实际行为
```

控制台验证应显式指定 `win_console_exe`，并在 `_启动子程序` 中调用目标逻辑和 `标准输出`；窗口 EXE 不提供可见控制台。`ecom` 目标不会执行模块自测入口。

### 5.3 e-packager 链路

```text
原始 .e / .ec
    → e-packager unpack <input> <output-dir>
    → AGENTS.md + info.json + project/ + src/ + ecom/ + elib/ + header/
    → 搜索和局部编辑 src/*.txt
    → （获授权时）e-packager update 同步模块、支持库或资源索引
    → e-packager pack <input-dir> <new-output.e|.ec>
    → compare-bundle / roundtrip / verify-roundtrip
    → 真实易语言 IDE / AutoLinker 编译
    → 运行产物验证
```

`e-packager` 是独立第三方转换工具，不是易语言编译器。文本回包成功不代表语法、依赖、编译或运行正确；`.ec` 工作区回包的实际输出还可能是 `.e`，不能只由输出扩展名判断内部格式。

### 5.4 BlackMoon 窗口链路

BlackMoon 是 32 位本机编译、资源编译和链接后端；`黑月界面类` 是建立纯代码 Win32 界面的易模块，二者不能混称。典型链路为：

```text
Windows 窗口程序工程（删除默认 _启动窗口）
    → 普通程序集中的 _启动子程序
    → 应用程序类.初始化
    → 窗口类 / 对话框类创建或创建自资源
    → 黑月窗口自己的 事件_创建完毕
    → 绑定控件、注册控件事件
    → 应用程序类.运行（唯一消息循环）
    → 窗口缩放、事件、销毁和资源释放
```

资源对话框模式还要求 `.e` 与同基本名 `.rc` 同目录，RC 中的 `#define` 数值与易语言 `#常量` 一致，并确认 `RC.EXE`、`CVTRES.EXE`、`LINK.EXE`、启动对象和 `.lib` 可用。

## 6. API、CLI、SDK 与协议边界

### 6.1 对外安装和 Agent 接口

- 安装命令：`npx skills add aiqinxuancai/e-language-skill`。
- Claude Code 触发：`/e-language`。
- OpenAI 系约定触发：`$e-language`。
- Agent 元数据：`agents/openai.yaml` 的 `display_name` 为“易语言开发”，默认提示为 `Use $e-language to inspect, modify, and validate this 易语言 project safely.`。

### 6.2 AutoLinker MCP

AutoLinker 的协议边界是本地 Streamable HTTP MCP。文档中明确的工具职责包括 `refresh_workspace_mirror`、`list_files`、`search_code`、`read_files`、`read_code_item`、`read_real_file`、`diff_file`、`edit_file`、`multi_edit_file`、`write_file` 和 `compile_with_output_path`。写操作必须带 `expected_base_hash`；哈希冲突时重新读取真实页，不能绕过 CAS。

### 6.3 e-packager CLI

核心命令包括：

```text
e-packager version
e-packager unpack <input.e|input.ec> <output-dir>
e-packager pack <input-dir> <output.e|output.ec>
e-packager update <workspace> [--add-ecom ...] [--add-elib ...] [--add-image ...] [--add-audio ...]
e-packager decrypt-fne <input.fne> <output.txt>
e-packager compare-bundle <input> <input-dir>
e-packager roundtrip <input> <work-dir> <output>
e-packager verify-roundtrip <input> <work-dir> <output>
e-packager /update [--force]
```

`update` 会改变依赖、部署要求或资源索引，只有用户明确授权时使用；`decrypt-fne` 只导出公开接口，不导出支持库实现。

### 6.4 BlackMoon / Win32 / DLL

BlackMoon 的已记录外部工具包括 `RC.EXE`、`CVTRES.EXE` 和 `LINK.EXE`；已观察到 `/machine:I386`、`/ENTRY:BMEntrypoint` 等构建参数，但具体版本仍以本地安装和完整编译日志为准。Win32/DLL 边界必须逐项确认位数、调用约定、`A/W` 编码、句柄/指针宽度、结构对齐、回调签名和资源所有权。`置入代码` 只能承载编译期确定的字节或已确认支持的原始二进制文件，不能被当作运行期解释器。

## 7. 技术栈与依赖边界

| 层级 | 技术 / 依赖 | 边界 |
|---|---|---|
| 文档与技能 | Markdown、YAML、Git | 本仓库自身无业务运行时 |
| 目标语言 | 易语言 / EPL，中文标识符，Windows / x86 为主要目标 | 命令和类型必须以当前工程依赖为准 |
| IDE 桥接 | AutoLinker.fne + 易语言 IDE + 本地 HTTP MCP | 操作 IDE 内存工程，不等同于磁盘解析 |
| 工程转换 | e-packager | 解包/回包/派生接口，不替代编译器和调试器 |
| 原生后端 | BlackMoon、RC/CVTRES/LINK、x86 `.obj` / `.lib` | 版本、位数和链接能力需现场验证 |
| 平台互操作 | Win32、GDI/GDI+、DLL、COM/OCX | ABI、编码、生命周期和线程要求严格 |
| 外部参考 | `aiqinxuancai/AutoLinker`、`aiqinxuancai/e-packager` | README 链接只作工具入口，当前安装和公开接口优先 |

当前仓库没有 `requirements.txt`、`pyproject.toml`、`package.json`、Composer 配置、编译脚本、数据库、网络服务或可安装运行依赖。当前本机通过 `command -v` 检查未发现 `e-packager`；没有安装依赖、启动 IDE、启动 MCP、构建或编译任何 Windows 工程。

## 8. 测试、验证结构与未执行事项

### 8.1 仓库内验证结构

仓库没有自动化测试目录、测试文件、CI 配置或构建入口。`references/engineering-and-debugging.md` 规定的测试策略是方法性约束，而不是本仓库已经执行的测试：应覆盖正常、空值、边界、中文/特殊字符、失败返回、重复调用、窗口关闭、线程取消和程序退出。

### 8.2 工程任务的验证分级

1. 先做声明槽位、参数/局部变量顺序、控制流闭合、入口和名称冲突检查。
2. 检查窗口事件、类公开性、DLL 参数、资源常量和依赖边界。
3. AutoLinker 任务使用 `compile_with_output_path`；磁盘 `.e` 使用无头 `e.exe`。
4. 逻辑验证使用显式 `win_console_exe` 和 `标准输出`，读取真实 stdout。
5. 涉及 UI、线程、网络、文件、DLL、回调、资源或内存时，补充真实运行场景。
6. BlackMoon 还要验证 RC、资源、窗口创建、控件绑定、事件、缩放和正常关闭；DLL 要从真实宿主加载。
7. `置入代码` 或动态回调跳板必须对最终目标模式反汇编并检查栈平衡、非易失寄存器、返回约定和生命周期。

### 8.3 本次实际验证与未执行事项

已执行：

- 检查目标根目录，确认项目为 `e-language-skill`。
- 读取 `AGENTS.md`、`README.md`、`SKILL.md`、`agents/openai.yaml` 和全部 `references/*.md`。
- 检查本地 Git 状态、分支、远程地址、提交和远程默认分支。
- 通过 `http://127.0.0.1:4780` 代理 fetch 远程 `origin/main`，并在独立 `/tmp/e-language-skill-remote` 快照中读取远程版本基线。
- 确认目标根原先不存在 `ARCHITECTURE.md`，不存在 `历史研究-*.md`，工作树原先无未提交修改。
- 检查 `e-packager`，本机 `PATH` 中未发现该命令。
- 对本次文档变更执行 `git diff --check`（最终门禁由专属工具记录）。

未执行：

- 未安装 `e-packager` 或任何 Windows 工具。
- 未打开或启动易语言 IDE、AutoLinker MCP、BlackMoon、`e.exe` 或 Windows 运行产物。
- 未解包、回包、编译或运行 `.e/.ec`；仓库本身也没有 `.e/.ec` 输入。
- 未执行 e-packager roundtrip、AutoLinker 编译、RC/CVTRES/LINK、反汇编、UI、DLL、回调或机器码运行测试。
- 未删除或改写源码、依赖、测试、配置、远程仓库或 Git 提交。

## 9. 未确认项、风险与后续复核点

- **工具版本未现场确认**：`AutoLinker.fne`、易语言 IDE、e-packager、BlackMoon 及 `黑月界面类` 的具体版本和安装路径需在 Windows 目标机复核。
- **API 代际风险**：`黑月界面类`、`黑月类模块`、`黑月模块` 和第三方改版可能有同名但不兼容的类与方法；必须以 `project/.module.json`、`header/header.txt` 和可运行示例为准。
- **入口风险**：只要 `_启动窗口` 仍存在，易语言可能优先进入它；黑月应用初始化和 `应用程序类.运行` 不得放入 `__启动窗口_创建完毕`。
- **ABI 风险**：经典 x86 栈帧、`整数型` 句柄映射、`cdecl`/`stdcall`、文本/字节集/数组内部布局及类方法回调都不是跨版本保证。
- **资源风险**：RC 编码、同名同目录、`#define` 数值、资源类型和输出链接必须以实际编译产物检查；RC 定义不会自动成为易语言常量。
- **窗口与生命周期风险**：父窗口创建完成前不能绑定子控件；长期对象不能错误地只放在局部变量；销毁前必须注销回调、停止线程并释放 GDI/GDI+/COM/句柄资源。
- **远程链接内容风险**：README 的易语言大模型基准评分链接属于外部参考，不是本仓库实现或验证依据；未对该站点内容做本次架构事实背书。
- **文档事实范围**：本仓库是方法论技能，没有当前实际易语言业务工程，因此不能从本仓库证明任何具体支持库命令、模块版本、编译成功率或运行行为。

后续若要验证具体工程，应先取得真实 `.e/.ec`、依赖公开接口、目标 IDE/编译器版本和 Windows 运行环境，再按对应 AutoLinker 或 e-packager 流程建立基线，并把编译输出、运行结果和目标模式明确记录。

## 10. 证据路径与版本基线

### 本地目标路径

```text
~/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/GitHub_aiqinxuancai/e-language-skill
```

关键证据：

- `AGENTS.md`：要求分析 `.e/.ec` 时优先检查并使用 `e-packager version`。
- `README.md`：项目定位、安装命令、触发方式、文档地图和边界。
- `SKILL.md`：工作模式选择、入口规则、强制生成规则和完成条件。
- `references/project-model.md`：`.e/.ec/.fne/.fnr/.lib`、入口、页面、依赖和资源模型。
- `references/declarations-and-text-format.md`：声明固定槽位和结构化文本保护规则。
- `references/autolinker-mcp.md`：MCP 镜像、真实页、CAS 写入和编译调用链。
- `references/autolinker-headless-compile.md`：磁盘 `.e` 无头编译参数和成功判定。
- `references/e-packager.md`：解包、工作区、回包、资源/依赖更新和往返验证。
- `references/blackmoon.md`：BlackMoon 入口、x86 编译链接、RC、窗口、DLL 和验证。
- `references/windows-and-interop.md`：窗口事件、Win32/DLL、编码、GDI/GDI+、回调和生命周期。
- `references/embedded-machine-code.md`：`置入代码`、x86 ABI、动态跳板、反汇编和 W^X 风险。
- `references/engineering-and-debugging.md`：排错、审查、测试、迁移和运行验证策略。

### Git 版本

```text
远程地址：https://github.com/aiqinxuancai/e-language-skill.git
本地初始 HEAD：dfe1e8bb1b1b9d39d6e2dc1b865f23ae257e5ed7
本地初始提交时间：2026-08-04T10:47:37+08:00
远程 origin/main：e0da33c4d654a431005f3db416c9d3b65b9c8206
远程提交时间：2026-08-17T13:53:04+08:00
远程相对本地：领先 5 个提交；已通过 127.0.0.1:4780 fetch，并以独立快照读取
```

远程提交 `e0da33c` 的主要变化是补充 BlackMoon `_启动子程序` 与唯一消息循环的入口约束、声明固定槽位和 DLL 调用约定说明，以及 README 的模型基准链接。本文按远程最新内容建立，独立快照不作为第二事实源；后续只维护目标根这一份 `ARCHITECTURE.md`。

## 11. 当前裁决：底座映射与唯一执行链路

### 11.1 事实边界与映射原则

当前审计只把当前仓库已经记录的技能、命令、协议、宿主和验证约束映射到底座边界，不把本仓库描述成已有运行时。`e-language-skill` 只有 `SKILL.md`、Markdown 参考资料和 `agents/openai.yaml`，没有能力注册表、模块运行代码、任务状态机、资源监督器或网关实现。因此以下“开发工具支持库 / 模块库 / 运行核心 / 网关”是**底座接入裁决和契约候选**，不是本仓库已经落地的实现。

映射时遵守四条边界：

1. **开发工具支持库**拥有外部工具/宿主适配、能力声明、命令参数和原始结果转换；不拥有业务流程状态。
2. **模块库**拥有一个领域工作流的编排和统一输入输出；不直接散落调用 `e.exe`、IDE HTTP 或 `e-packager`。
3. **运行核心**拥有提交、排队、超时、取消、进程/会话监督、状态持久化、证据和资源回收；不解释易语言业务语义。
4. **网关**拥有对外搜索、契约、授权、请求校验、统一错误/事件和版本兼容；不直接持有宿主句柄或旁路第三方工具。

### 11.2 技能、命令与宿主注册归属

| 注册对象 | 当前源码事实 | 开发工具支持库 | 模块库 | 运行核心 | 网关 | 当前证据等级 |
|---|---|---|---|---|---|---|
| 技能注册 | `SKILL.md` front matter 声明 `name: e-language`、触发描述和适用范围；README 记录 `npx skills add`、`/e-language`、`$e-language` | 保存技能描述、触发别名、版本和能力索引；别名在唯一入口归一化 | 只消费已登记的技能能力，不复制触发规则 | 校验技能版本、装载状态和执行上下文 | 对外暴露搜索/契约/执行，不把 Markdown 直接当可执行能力 | L0，静态文档 |
| Agent 宿主注册 | `agents/openai.yaml` 只有 `display_name` 和默认提示，不承载运行逻辑 | 维护 Agent 元数据与宿主适配声明；提示文本不能冒充工具实现 | 将任务路由到具体工作流 | 绑定会话、预算、超时和取消上下文 | 校验调用者、权限、请求版本 | L0，静态文档 |
| AutoLinker MCP 注册 | `autolinker-mcp.md` 记录本地 Streamable HTTP MCP、默认 `127.0.0.1:19207/mcp`、工具名和先刷新镜像的顺序 | 注册 MCP endpoint、工具名、请求参数、结果解析和宿主健康探针 | 组合刷新、探索、真实页读取、CAS 编辑、编译验证 | 管理 MCP 会话、镜像代次、超时、断线和取消；不把旧会话路径/哈希复用到新会话 | 暴露统一的 MCP/HTTP 请求面、鉴权和事件流 | L0；未启动宿主 |
| 无头编译命令注册 | `autolinker-headless-compile.md` 给出 `e.exe`、`--autolinker-*` 参数、结果 JSON、退出码 `0/1/2/3/4/6` | 注册 `e.exe` 命令适配器、目标类型、结果 JSON 解析和产物指纹校验 | 编排“准备输入→编译→读取结果→运行产物”，不自己实现编译 | 负责独立 IDE 进程、唯一输出/结果路径、超时、进程组和回收 | 将编译请求转为稳定请求/响应和统一错误 | L0；Windows 宿主未验证 |
| e-packager 命令注册 | `e-packager.md` 记录 `version/unpack/pack/update/decrypt-fne/compare-bundle/roundtrip/verify-roundtrip` | 注册 CLI、版本探针、参数校验、stdout/stderr 和返回码适配 | 编排解包、阅读、局部编辑、授权更新、回包、往返和 IDE 编译 | 管理工作目录、临时输出、取消、失败清理和原件保护 | 对外暴露命令契约与授权边界；禁止网关直接写工作区 | L0；本机未发现 `e-packager` |
| BlackMoon/Win32 宿主注册 | `blackmoon.md`、`windows-and-interop.md` 规定 x86、RC/CVTRES/LINK、DLL/ABI、窗口和消息循环边界 | 注册工具链版本、位数、库/资源探针和 ABI 声明 | 编排资源构建、窗口运行或 DLL 验证 | 监督真实进程、句柄、线程、回调和关闭顺序 | 对外只暴露验证结果，不暴露原生句柄 | L0；未在本机 Windows 执行 |

注册表的最小统一记录建议为：`能力id`、版本、入口类型（MCP/CLI）、提供者、宿主要求、输入契约、输出契约、错误码、超时、取消语义、幂等性、资源责任和证据要求。以上字段是底座契约建议；本仓库只分别给出了其中的工具名、命令参数、目标类型、结果 JSON、退出码和部分限制，不能宣称已经存在完整注册表。

### 11.3 文档契约如何分层

当前文档已经形成四类可吸收契约，但权威 owner 必须拆开：

| 契约层 | 当前证据 | 归属与职责 |
|---|---|---|
| 技能/安装契约 | `README.md` 的安装、触发方式、文档地图；`SKILL.md` 的 front matter 和工作模式选择 | 开发工具支持库维护描述和版本；网关只读取已编译的能力元数据，不直接解析任意 README 执行 |
| 工具命令契约 | `autolinker-headless-compile.md` 的参数、目标、结果 JSON、成功四条件；`e-packager.md` 的命令、路径和更新副作用 | 开发工具支持库拥有原始工具契约；参数别名、平台差异和版本兼容在适配器内收敛 |
| 领域工作流契约 | AutoLinker 的刷新→探索→真实页→CAS→编译；e-packager 的解包→编辑→回包→往返→真实编译；黑月的入口→窗口→消息循环 | 模块库拥有公开工作流输入输出和前置条件；模块不得把提供者对象、IDE 页面对象或原生句柄穿透给消费者 |
| 执行/传输契约 | 文档明确区分 IDE 内存工程、磁盘 `.e/.ec`、派生 `src/`、输出产物和真实运行验证 | 运行核心拥有状态、证据和资源生命周期；网关拥有请求 envelope、鉴权、统一错误、事件和版本；当前仓库未给出网关 JSON schema，必须标“待核” |

建议的公共能力契约形状如下，字段是平台层补齐项，不是本仓库现有 JSON：

```text
能力契约
├── 能力id / 版本 / 提供者 / 宿主要求
├── 请求：输入工程、工作区或端点、目标、参数、基线哈希、超时、幂等键
├── 返回：统一结果、产物引用、stdout/stderr 摘要、原始结果引用、验证结论
├── 错误：稳定错误码、消息、可重试、根因、宿主/依赖诊断
├── 状态：请求id、操作id、阶段、开始/结束时间、取消/超时/崩溃原因
└── 资源：所有者、临时目录、进程组、MCP 会话、输出路径、释放结果
```

特别要保留源项目的真假边界：`pack` 成功不等于编译成功，编译退出码为 `0` 也还要检查结果 JSON、产物是否由本次编译创建/更新，并在需要时运行产物；`read_real_file` 返回的真实内容和 `code_hash` 才能作为 AutoLinker 写入基线；`src/*.xml`、`project/`、`ecom/`、`elib/`、`header/` 的只读/派生性质不能被模块层改写成普通文本契约。

### 11.4 执行状态与资源边界

执行状态由运行核心单一持有，建议状态机如下：

```text
未登记
  → 已登记
  → 宿主探测中
       ├─ 宿主可用 → 可执行
       └─ 宿主不可用 → HOST_UNAVAILABLE（终态，可重新探测）
可执行
  → 已提交 → 排队 → 运行中
运行中
  ├─ 结果通过 + 产物/行为验证通过 → 成功
  ├─ 工具返回失败/结果 JSON 失败/校验失败 → 失败
  ├─ 调用方主动取消 → 取消中 → 已取消
  ├─ 截止时间到 → 超时中 → 超时
  └─ 宿主/进程异常退出 → 宿主崩溃
成功/失败/已取消/超时/宿主崩溃
  → 资源回收中 → 已回收 → 已归档
```

状态规则：

- 只有“统一结果成功 + 本次产物校验通过 + 任务要求的真实行为验证通过”才能进入 `成功`；打印“编译成功”、旧文件存在或 `pack` 完成不能推进成功状态。
- `HOST_UNAVAILABLE`、`workspace_refresh_required`、哈希冲突、请求参数错误和依赖缺失必须在状态中保留原始错误和宿主诊断，不能伪装成模块业务失败。
- 取消、超时和宿主崩溃是不同终态：取消来自调用方，超时来自运行核心截止时间，崩溃来自宿主/子进程事实；三者都必须有进程回收和资源清点证据。
- 状态转移和证据写入由运行核心完成；模块库只返回领域结果，开发工具支持库只返回原始工具结果，网关不直接改状态库。

资源责任按“创建者声明、持有者使用、转移者留证、运行核心兜底回收”执行：

| 资源 | 创建/持有方 | 释放责任与边界 |
|---|---|---|
| AutoLinker MCP 会话、镜像代次 | 开发工具支持库创建；模块持有操作引用 | 运行核心负责超时/取消/断线收口；新会话不得复用旧路径、哈希和分页代次 |
| `e.exe`/独立 IDE 进程 | 支持库启动；运行核心登记进程组 | 运行核心负责截止时间、优雅停止、强制终止、等待回收和残留检查；模块不直接 `kill` |
| e-packager 工作区、临时目录 | 模块申请，支持库读写 | 运行核心绑定操作所有者；成功产物原子发布，失败/取消删除临时目录，原始 `.e/.ec` 不被覆盖 |
| `result.json`、stdout/stderr、日志 | 支持库产生 | 运行核心按请求/操作 id 隔离并限制大小；网关只返回摘要和证据引用，不无限转发输出 |
| 编译产物/回包产物 | 支持库生成，模块声明目标 | 只有验证通过才能发布为可消费制品；旧产物不能冒充本次产物；取消在发布前必须无残留 |
| IDE 真实页、`code_hash`/CAS 基线 | AutoLinker 宿主/支持库 | `read_real_file` 是写入前唯一基线；哈希冲突必须重读，不得绕过 CAS |
| 文件、资源、窗口、DLL、GDI/GDI+、线程、回调、句柄 | 目标工程/宿主创建 | 支持库声明借用或拥有；运行核心监督关闭顺序；窗口销毁前注销回调、停止线程并释放句柄，模块不跨边界保存裸句柄 |

资源句柄只能以可序列化的 `资源id`、文件路径引用、产物引用或诊断引用跨层传递；不能把 IDE 对象、MCP 客户端对象、Windows 原生句柄或第三方 Python/进程对象放进网关响应或模块公共契约。

### 11.5 唯一链路与禁止侧链

同类能力只保留一个规范能力 id、一个契约 owner、一个模块公开入口和一个注册/调用路径。候选链路为：

```text
SKILL.md / agents/openai.yaml / README 事实
        ↓（编译为注册元数据；别名只在此处归一化）
开发工具支持库：能力注册表 + 宿主/命令适配器
        ↓（网关只取已登记能力）
统一网关：搜索 → 契约 → 授权 → 执行
        ↓
模块库：易语言工程工作流公开入口
        ↓
运行核心：请求id/操作id → 排队 → 监督执行 → 状态/取消/超时/证据
        ↓
开发工具支持库：MCP / e.exe / e-packager / BlackMoon provider
        ↓
真实 IDE、e.exe、e-packager、Windows 工具链或目标产物
        ↓
结果归一化 → 产物/行为验证 → 资源回收 → 网关响应与事件
```

唯一链路要求：

- AutoLinker MCP、无头编译和 e-packager 是不同宿主适配器，不能各自再实现一套状态机、日志、超时和错误翻译；这些共性归运行核心。
- `e-packager pack` 只能由 e-packager 支持库执行；模块库编排回包和验证，不得直接改二进制或直接调用另一个打包器旁路。
- AutoLinker 写入必须统一经过 `read_real_file → expected_base_hash → edit/multi_edit/write`；任何“镜像哈希直接写入”或直接覆盖 IDE 当前工程都属于侧链。
- 工具原始错误只在支持库转换一次；模块库不逐个翻译退出码，网关不根据文本猜错误。别名、旧命令名和不同宿主键在注册入口统一归一化。
- 公开结果只返回统一结果、产物引用和诊断摘要；provider 对象、临时路径细节和原生句柄不穿透。

### 11.6 失败、取消与恢复矩阵

下表中带“建议”的稳定错误名是底座统一命名候选；源项目明确给出的原始事实仍以 `workspace_refresh_required`、退出码和结果 JSON 为准。

| 场景 | 首个事实 | 归属 | 对外结果（建议） | 恢复/重试要求 |
|---|---|---|---|---|
| 技能/命令/宿主声明缺失 | 无法形成完整注册记录 | 开发工具支持库 | `CONTRACT_INVALID` | 禁止执行；补齐声明后重新注册 |
| `e-packager`、IDE 或 `e.exe` 不存在 | 命令探针/宿主探测失败 | 支持库 + 运行核心 | `HOST_UNAVAILABLE` | 可重新探测；不得用模拟输出代替 |
| MCP 未刷新或会话代次失效 | 工具返回 `workspace_refresh_required` 或分页代次不匹配 | 支持库 | `SESSION_STALE` | 刷新镜像后重新读取；不得复用旧哈希 |
| `expected_base_hash` 缺失/冲突 | 写入前没有真实页基线或真实页已变化 | 支持库 | `BASE_HASH_REQUIRED` / `BASE_HASH_CONFLICT` | 重新 `read_real_file`，重新生成局部修改；禁止强写 |
| 参数/目标/路径非法 | 参数校验失败或无效输出目标 | 支持库 | `INVALID_ARGUMENT` | 不启动宿主；修正请求后重试 |
| 编译返回失败 | 退出码 `1` 或结果 JSON `ok=false` | 支持库解析，运行核心落账 | `COMPILE_FAILED` | 读取第一组根因、输出窗口和诊断字段；不能按“编译成功”文本判绿 |
| 启动/内部/弹窗阻塞 | 文档记录退出码 `3/4/6` 或对应错误 | 支持库 + 运行核心 | `HOST_TIMEOUT` / `HOST_INTERNAL` / `HOST_BLOCKED` | 检查宿主进程、指定结果 JSON 和日志；按错误类型决定是否重试 |
| 产物未创建或仍是旧文件 | `artifact_verified=false` 或未满足本次更新时间/路径 | 运行核心 | `ARTIFACT_NOT_VERIFIED` | 隔离旧产物，保留证据，不进入成功 |
| 回包/往返不一致 | `compare-bundle`/`verify-roundtrip` 失败 | 模块库 + 支持库 | `ROUNDTRIP_MISMATCH` | 保留原文件、工作区和输出，禁止覆盖原件 |
| 调用方在启动前或排队中取消 | 尚未创建宿主进程或任务尚未运行 | 运行核心 | `CANCELLED` | 不启动；清理排队记录和临时目录，写取消证据 |
| 运行中取消 | 宿主已运行，调用方发出取消 | 运行核心 | `CANCELLED`（附 `取消阶段`） | 先优雅停止，超出宽限再终止整个进程组；等待回收后才能结束状态 |
| 截止时间到 | 运行核心单调时钟超时 | 运行核心 | `TIMEOUT` | 与主动取消分开记账；终止/回收/排干输出，标记可重试条件 |
| 宿主崩溃或非零异常退出 | 进程退出、连接断开或无有效 JSON | 运行核心 + 支持库 | `HOST_CRASHED` | 检查子进程、锁、临时目录和部分产物；只有幂等且基线仍有效才允许重试 |
| 发布后收到取消 | 制品已原子发布并写入成功证据 | 运行核心 | `ALREADY_COMMITTED` | 取消不回滚已提交事实；通过新事务/回滚命令处理，不伪造“已取消” |
| 释放失败或残留 | 进程、文件、句柄、连接或临时目录仍存在 | 运行核心 | `RESOURCE_CLEANUP_FAILED` | 任务不能算成功；保留残留清单和二次回收任务，必要时隔离宿主 |

当前源码只明确规定了“写入前 CAS”“超时检查”“失败/取消/退出测试应覆盖”和工具自身的错误/退出码，未明确 MCP 请求取消协议、统一网关错误码、资源租约格式或宿主崩溃后的自动重试。因此这些项目必须保持“待核”，不能写成已实现事实。

### 11.7 L0-L4 验证等级

| 等级 | 能证明什么 | 最低验证 | 不能宣称什么 | 本仓库现状 |
|---|---|---|---|---|
| **L0 文档事实** | 入口、命令、工具名、参数、边界和风险被源码资料记录 | 读取 `SKILL.md`、README、`agents/openai.yaml`、相关 `references/*.md`，标注实现/声明/未验证 | 不能证明命令存在、宿主可连接、编译或运行成功 | 已有 L0；当前审计静态取证 |
| **L1 注册与宿主探针** | 能力已登记，命令/端点/版本/位数/依赖可发现 | `e-packager version`、`command -v`、AutoLinker endpoint/IDE 信息、`e.exe`/工具链路径和版本探针；失败明确 `HOST_UNAVAILABLE` | 不能证明真实工程链路、产物正确或取消可用 | 仅有本机未发现 `e-packager` 的负证据；Windows/IDE 未探测 |
| **L2 支持库真实调用** | 单个 provider 可对真实宿主执行并返回可解析结果 | 唯一请求/结果路径、真实命令/MCP 调用、退出码/JSON/产物路径校验、超时和进程组回收；不使用模拟成功 | 不能证明模块流程或网关并发契约 | 未执行 |
| **L3 模块工作流闭环** | 一个领域流程从输入到产物/行为验证和清理闭环 | AutoLinker 刷新→CAS 写→编译→运行，或 e-packager 解包→局部编辑→回包→往返→真实编译；覆盖失败、重复、取消、超时和资源清理 | 不能直接证明多租户网关、版本兼容和高并发 | 未执行 |
| **L4 网关生产闭环** | 对外稳定能力可授权、可观测、可取消、可恢复并可审计 | 网关搜索/契约/执行；并发隔离、身份与权限、幂等、断线/宿主崩溃恢复、资源残留审计、版本兼容和真实跨宿主回归 | 不能以 L0 文档、L1 探针或单次 L2 结果替代 | 未执行；本项目没有网关实现 |

等级不可跳跃：L1 的“命令存在”不等于 L2 的“真实调用成功”；L2 的“编译成功”不等于 L3 的“工作流行为正确”；L3 的“单任务闭环”不等于 L4 的“网关生产可治理”。

### 11.8 当前裁决裁决

- **吸收**：把 AutoLinker 的真实页/CAS、无头编译的结果 JSON 与产物四条件、e-packager 的原件保护与往返验证、工程排错中的失败/取消/退出覆盖，吸收到“支持库原始契约 + 模块工作流 + 运行核心状态/资源 + 网关统一出口”的单链路设计。
- **待核**：真实技能注册表格式、宿主发现协议、MCP 取消语义、统一网关 envelope、租约/配额、进程组终止策略、跨 Windows 版本兼容和 L1-L4 的现场执行证据。本仓库没有这些实现，不能凭文档补齐为已完成。
- **废弃**：把 `SKILL.md` 当命令执行器；把 README/公开接口文本当支持库实现；让模块直接调用 `e.exe`/HTTP/文件系统旁路运行核心；用旧产物、打印日志、`pack` 成功或“有输出文件”伪造编译/运行成功；绕过 `refresh_workspace_mirror`、`read_real_file` 和 `expected_base_hash`；把宿主句柄或 provider 对象塞进公共结果。

当前审计只改变本架构文档的映射与验收口径；没有新增注册表、模块、运行核心、网关或任何真实宿主执行实现。
