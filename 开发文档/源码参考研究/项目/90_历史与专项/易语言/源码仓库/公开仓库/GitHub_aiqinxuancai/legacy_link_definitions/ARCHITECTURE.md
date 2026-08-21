# legacy_link_definitions 架构归档

## 1. 项目定位

`legacy_link_definitions` 是一个 Windows/MSVC 静态库项目。README 的定位是：链接时附加该静态库，解决部分 VC6 静态库由较新 VC 链接器链接时缺少 `timezone` 符号的问题。

项目不是运行中的服务，也不是带命令行界面的应用；它通过静态链接向调用方补充兼容符号。当前仓库没有测试代码、第三方依赖清单或运行时配置文件。

## 2. 真实流程

```text
调用方链接 legacy_link_definitions.lib
        |
        v
legacy_link_definitions.cpp 提供 C 链接符号
        |
        +--> compute_timezone_value()
        |       |
        |       +--> _get_timezone(&t)（MSVC CRT）
        |       +--> 返回 long 时区偏移
        |
        +--> timezone()
                |
                +--> 首次调用：compute_timezone_value()
                +--> 写入函数内 static long value
                +--> 返回 long&，后续调用复用缓存值
```

## 3. 目录与分层地图

```text
legacy_link_definitions/
├── README.md                                      # 项目用途说明
├── legacy_link_definitions.sln                   # Visual Studio 解决方案
├── legacy_link_definitions/
│   ├── legacy_link_definitions.cpp                # 兼容符号实现
│   ├── legacy_link_definitions.vcxproj            # MSBuild 静态库工程配置
│   ├── legacy_link_definitions.vcxproj.filters   # Visual Studio 文件筛选器
│   ├── framework.h                                # Windows 头文件裁剪宏
│   ├── pch.h                                      # 预编译头入口
│   └── pch.cpp                                    # 预编译头编译单元
├── .gitattributes                                 # Git 文本/合并属性
└── .gitignore                                     # Visual Studio 生成物忽略规则
```

项目只有一个实现层，没有独立的业务层、数据访问层、服务层或测试层。`legacy_link_definitions.vcxproj` 将 `legacy_link_definitions.cpp` 与 `pch.cpp` 编译为 `StaticLibrary`。

## 4. 核心实现与数据模型

### 4.1 符号与调用关系

源码路径：`legacy_link_definitions/legacy_link_definitions.cpp`

- `compute_timezone_value()`：创建局部 `long t = 0`，调用 MSVC CRT 的 `_get_timezone(&t)`，返回 `t`。
- `timezone()`：返回 `long&`。函数内的 `static long value` 只在首次调用时通过 `compute_timezone_value()` 初始化，之后返回同一缓存对象。
- 两个函数位于 `extern "C"` 块内，目的是使用 C 链接名，避免 C++ 名字修饰，便于旧静态库/新链接器按 `timezone` 符号解析。

### 4.2 状态与持久化

项目没有业务数据模型、文件存储、数据库、网络请求或持久化机制。唯一的运行时状态是 `timezone()` 内部的函数级静态变量 `value`：

- 初始化来源：当前进程/CRT 环境中的 `_get_timezone`；
- 生命周期：进程生命周期；
- 更新方式：源码中没有更新接口，初始化后不会再次读取系统时区；
- 返回方式：以 `long&` 暴露给链接方，因此调用方理论上可以修改该缓存值。

`compute_timezone_value()` 直接返回 `_get_timezone` 写入的数值，没有错误码或失败结果封装；其行为与 MSVC CRT/目标平台 ABI 绑定。

## 5. API、CLI 与协议边界

### 对外符号

| 符号 | 原始签名 | 作用 |
|---|---|---|
| `compute_timezone_value` | `long compute_timezone_value()` | 从 `_get_timezone` 读取时区偏移并返回 `long` |
| `timezone` | `long& timezone()` | 返回首次计算后缓存的 `long` 引用 |

实现位于 `extern "C"`，但源码没有单独的公共头文件声明；调用方若需要直接调用这些符号，需要自行提供与 ABI 一致的声明或通过旧静态库的既有声明间接引用。

项目没有 CLI、HTTP API、SDK、插件协议、配置协议或 IPC 边界。`.sln`/`.vcxproj` 是构建边界，不是运行时接口。

## 6. 技术栈与依赖边界

- 语言：C++（实现使用 C 链接边界）。
- 构建系统：Visual Studio/MSBuild `.sln` + `.vcxproj`。
- 产物类型：`StaticLibrary`。
- 直接头文件：`<time.h>`、项目内 `pch.h`、`framework.h`。
- MSVC CRT 接口：`_get_timezone`。
- 预处理：`_CRT_SECURE_NO_WARNINGS`；`framework.h` 定义 `WIN32_LEAN_AND_MEAN`。
- 工程配置：`Debug|Win32`、`Release|Win32`、`Debug|x64`、`Release|x64`；大多数配置使用 `v143`，`Release|Win32` 使用 `v141`。
- 运行目标：Windows；当前 macOS 工作环境没有 Windows SDK/MSVC 构建链，因此本次不执行构建。

### 配置细节与潜在差异

- 解决方案配置使用 `Debug|x86`/`Release|x86`，并映射到工程的 `Win32` 配置；工程自身声明的是 `Win32`，不是 `x86`。
- `Release|Win32` 关闭 C++ 一致性模式并设置 `RuntimeLibrary=MultiThreaded`、`Optimization=MinSpace`；其余 Release/Debug 配置的编译选项存在差异。
- `Release|Win32` 明确设置了 `TargetName=legacy_link_definitions`，其他配置未显式设置同名目标，通常使用工程名默认值。

## 7. 测试、验证与未执行事项

### 现场验证

- 已检查仓库工作树：初始无未提交改动。
- 已检查完整 Git 树：共 10 个受版本控制的项目文件，未发现测试目录或测试文件。
- 已检查本地基线：`master` 为 `b984cdec6bb41f3513984f64ec1c18e86fb74ea0`，提交时间 `2023-10-11T14:47:31+08:00`，主题为 `Update README.md`。
- 已通过代理 `127.0.0.1:4780` 查询远程：`origin/master` 与本地均为 `b984cdec6bb41f3513984f64ec1c18e86fb74ea0`，未发现远程领先，因此没有创建独立远程快照。
- 已读取 README、C++ 实现、解决方案、工程配置、筛选器及头文件；实现文件的注释在当前文本显示链路中存在编码乱码，但代码结构和符号可辨识。

### 未执行

- 未执行 Visual Studio/MSBuild 编译：当前环境为 macOS，缺少 Windows/MSVC 工具链；且本次任务边界禁止安装、启动或构建。
- 未执行链接验证：仓库没有调用方工程或现成链接测试夹具。
- 未执行单元测试：仓库没有测试实现。
- 未执行 Windows ABI/CRT 兼容性验证：`_get_timezone`、`long` 大小及 `long& timezone()` 的链接/调用行为需要 Windows/MSVC 环境确认。

## 8. 风险与后续复核点

1. **缺少公共头文件**：实现符号没有随仓库提供的声明文件，外部调用方容易出现签名或调用约定不一致。
2. **`timezone()` 返回可写引用**：调用方可改写内部静态缓存，可能导致同一进程后续读取结果与系统时区不一致。
3. **初始化线程语义依赖编译器/运行库**：函数级静态变量的首次初始化需要在目标 MSVC 配置下确认线程安全语义；当前源码没有显式同步或重读策略。
4. **CRT 与 ABI 绑定**：`_get_timezone` 是 MSVC CRT 接口；跨工具链、跨运行库或非 Windows 环境不可直接假设可用。
5. **解决方案/工程平台命名不完全一致**：解决方案使用 `x86`，工程使用 `Win32`；后续若增加配置，应同步检查映射关系。
6. **版本较旧**：本地与远程当前一致，但最新远程基线停留在 2023-10-11；没有证据表明其已适配更新的 MSVC/Windows SDK。
7. **注释编码可读性**：源文件注释在当前读取环境显示为乱码，若后续需要维护文档或源码注释，应先确认文件实际编码，不要未经确认批量转码。

## 9. 证据路径与版本基线

- 项目根：`~/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/GitHub_aiqinxuancai/legacy_link_definitions`
- 核心实现：`legacy_link_definitions/legacy_link_definitions.cpp`
- 工程配置：`legacy_link_definitions/legacy_link_definitions.vcxproj`
- 解决方案：`legacy_link_definitions.sln`
- 项目说明：`README.md`
- 本次归档文件：`ARCHITECTURE.md`
- 本地/远程版本：`b984cdec6bb41f3513984f64ec1c18e86fb74ea0`

## 10. 第三轮：旧链接定义的真实含义

### 10.1 “旧链接定义”不是声明文件，也不是动态加载器

README 所说的“链接时附加此静态库”，指的是：旧 VC6 产物在被较新 MSVC 链接器重新链接时，对某个 `timezone` 外部符号存在未解析引用；调用方把本项目生成的 `.lib` 加入链接输入，由静态链接器从库成员中取出定义以满足该引用。这个用途是项目说明中的**兼容意图（L0）**，仓库没有附带 VC6 调用方、链接日志或最终可执行文件，故不能把“解决过某个真实调用方”写成已实测事实。

源码能直接证明的实现（L1）只有：

1. `legacy_link_definitions/legacy_link_definitions.cpp` 在 `extern "C"` 块内定义 `compute_timezone_value` 与 `timezone`；
2. `compute_timezone_value` 调用 MSVC CRT 的 `_get_timezone(&t)`；
3. `timezone` 通过函数级 `static long value` 缓存一次计算结果并返回 `long&`；
4. `legacy_link_definitions.vcxproj` 将该源文件编译为 `StaticLibrary`（构建声明，L2）。

因此这里的“链接定义”是**补充链接期符号定义的 ABI shim**，不是对旧库源码的重新编译，不是运行时服务，也不是 `LoadLibrary`/`GetProcAddress` 一类动态加载机制。仓库没有 `.def` 文件、DLL、导出表、注册表、IPC、启动入口或运行时装配代码。

### 10.2 声明、意图与实际实现分离

| 层次 | 仓库内证据 | 能证明什么 | 不能证明什么 |
|---|---|---|---|
| 用途声明 | `README.md:3` | 作者希望通过附加静态库补足 `timezone` 链接符号 | 没有证明某个 VC6 调用方在目标环境已成功链接 |
| 源码实现 | `legacy_link_definitions/legacy_link_definitions.cpp` | 两个函数的函数体、`extern "C"` 语言链接、CRT 调用和缓存逻辑 | 没有证明实际目标对象中的符号拼写、修饰和调用约定与所有旧消费者一致 |
| 构建声明 | `legacy_link_definitions/legacy_link_definitions.vcxproj`、`.sln` | 输出类型为静态库、Win32/x64 配置、工具集与 SDK 声明 | 没有证明 MSBuild 在本机或任何 Windows 机器上成功产出 `.lib` |
| 公共接口声明 | **不存在**独立 `.h` 或 `.def` | 只能从定义反推源码签名 | 没有可供消费者稳定包含的版本化声明、宏、导入库或符号清单 |
| 实际链接/运行 | 仓库未提供调用方、测试、二进制或日志 | 当前仅能做静态取证 | 不能声称已完成 L3 符号验证或 L4 Windows 集成验证 |

特别是，`extern "C"` 是编译器语言链接说明，不等于公共头文件，不等于导出清单，也不等于跨编译器 ABI 保证。调用方若自行写声明，必须精确匹配 `long compute_timezone_value()` 与 `long& timezone()`；仓库没有提供该声明作为正式契约。

## 11. 符号、ABI 与版本兼容契约

### 11.1 当前实际符号契约

| 符号 | 源码定义 | 兼容作用 | ABI 风险 |
|---|---|---|---|
| `compute_timezone_value` | `long compute_timezone_value()` | 每次调用创建局部 `long`，调用 `_get_timezone` 后返回值 | `long` 宽度、调用约定、链接名和 CRT 行为均依赖目标 MSVC/平台；源码未用 `static_assert` 或版本检查固定它们 |
| `timezone` | `long& timezone()` | 返回函数级静态 `long` 的可写引用 | 返回引用是 C++ 类型语义；虽然函数名处于 C linkage，C 源码不能直接表达该签名，消费者的声明/调用代码必须与 MSVC ABI 一致 |
| `_get_timezone` | `<time.h>` 中的 MSVC CRT 接口 | 为实现提供时区偏移 | 是实现侧 CRT 依赖，不是本库向消费者发布的独立接口；调用返回状态被忽略 |

源码没有显式写 `__cdecl`、结构体打包、位宽别名、`noexcept`、版本号或能力标识。Win32 下默认调用约定和符号前缀、x64 下统一调用约定等细节不能仅凭 README 视为已兼容；本轮没有 `dumpbin /symbols`、实际 `.lib` 或消费者链接结果，相关判断均标记为未验证。

`timezone()` 的静态值来自首次调用时的 `_get_timezone`。`compute_timezone_value` 先把 `t` 初始化为 `0`，然后无条件忽略 `_get_timezone` 的返回状态并返回 `t`；若 CRT 调用失败或没有写入有效值，源码没有错误分支，调用者可能得到 `0` 或 CRT 留下的值。函数级静态初始化及其线程语义由目标编译器/运行库负责，源码没有显式锁、重试、失效或刷新接口。

### 11.2 版本/平台兼容矩阵（声明与证据分开）

| 维度 | 工程声明 | 当前证据级别 | 结论 |
|---|---|---:|---|
| Windows SDK | `10.0.22000.0` | L2 | 仅是 `.vcxproj` 配置声明，未在本机验证 |
| Debug/Win32、Debug/x64 | `v143` | L2 | 构建输入配置存在，未产出库 |
| Release/x64 | `v143` | L2 | 构建输入配置存在，未产出库 |
| Release/Win32 | `v141`、`RuntimeLibrary=MultiThreaded`、关闭一致性模式 | L2 | 与其他配置不一致，属于版本/运行库风险点 |
| 解决方案 x86 | 映射到工程 `Win32` | L2 | 映射存在，但没有真实链接验证 |
| 解决方案 x64 | 映射到工程 `x64` | L2 | 映射存在，但没有真实链接验证 |
| VC6 静态库消费者 | README 声称为目标场景 | L0 | 无调用方、无链接日志，不能升级为兼容性结论 |
| 非 MSVC/非 Windows | 无工程支持声明 | L1/L2 | 不能假设可用；`_get_timezone` 与目标 ABI 直接限制可移植性 |

同一仓库同时使用 `v141` 与 `v143`，且 Win32 Release 单独设置运行库选项；这不是“所有配置具有同一 ABI”的证据。版本兼容至少应以“目标架构 + 工具集 + CRT 选择 + 实际符号表 + 真实旧消费者链接”联合验收，当前只具备前两项的工程文本声明。

## 12. 生成与加载契约，以及三层归属

### 12.1 当前仓库的生成/消费链

```text
开发工具（Visual Studio/MSBuild）
  └─读取 .sln/.vcxproj、选择 Win32 或 x64 + Debug/Release
       └─编译 legacy_link_definitions.cpp / pch.cpp
            └─生成静态归档 legacy_link_definitions.lib（未在本仓库验证）
                 └─消费者链接命令显式加入该 .lib
                      └─静态链接期解析旧对象的 timezone 外部符号
                           └─进程运行时执行 timezone() / compute_timezone_value()
```

这里“生成契约”是工程层契约：输入是源文件、头文件、平台、工具集和配置，输出应是与消费者同架构的 `.lib`。这里“加载契约”在当前项目中应严格改称“链接消费契约”：没有运行时加载；库成员在链接期被选入最终映像，程序启动后不存在本项目自己的加载器、注册表或卸载动作。

### 12.2 归属裁决（第三轮映射，不等于仓库已有模块）

| 目标层 | 应归入的责任 | 本仓库实际情况 | 裁决 |
|---|---|---|---|
| 开发工具层 | 生成 `.lib`；选择架构/工具集；把库加入消费者链接输入；在交付前检查符号与架构 | `.sln`/`.vcxproj` 只声明了部分构建输入，没有生成脚本、符号清单、装配检查或调用方模板 | **保留为工具链适配责任**；不能把工程文件当运行核心能力 |
| ABI 支持库 | 唯一持有旧 `timezone` 兼容定义、CRT 边界、版本/架构兼容矩阵和失败语义 | 本项目源码正是一个最小 ABI 支持实现，但没有公共头、版本元数据、符号清单和验证夹具 | **吸收为 ABI 支持库候选**；不得在各模块或运行核心复制同一 fallback |
| 运行核心 | 消费已验证的 ABI 支持包或其稳定包装；承载最终进程生命周期、错误上报和证据 | 本仓库没有运行核心、服务入口、状态机、加载器或资源管理器 | **不归属实现**；运行核心不能直接拥有此 shim 的源码，也不能声称已加载/运行它 |

后续若平台要正式吸收，应由开发工具生成或装配“架构/工具集/CRT/符号集合”元数据，由 ABI 支持库提供唯一实现和兼容包装；运行核心只依赖经验证的支持库契约。若未来改成 DLL，必须另立显式的动态加载 ABI（导出名、版本、调用约定、失败码、卸载/句柄所有权）；该仓库没有这套实现，不能从当前静态库推导出来。

## 13. 失败、释放与资源生命周期

| 节点/资源 | 正常路径 | 业务/技术失败 | 取消/超时 | 崩溃/释放责任 | 证据与结论 |
|---|---|---|---|---|---|
| MSBuild 编译输入 | 编译两个 `.cpp`，归档为静态库 | 头文件、Windows SDK、工具集或架构不匹配则构建失败 | 非运行时操作；取消由构建工具负责 | 构建工具负责临时文件；源码没有清理钩子 | `.vcxproj` L2；本轮未构建 |
| 静态链接解析 | 消费者把匹配架构的 `.lib` 加入链接，未解析符号被库成员满足 | 未加入库、库顺序/输入配置错误、架构或符号名/签名不匹配时链接失败 | 无本项目取消协议 | 最终链接器/构建流水线负责中间产物清理 | 无消费者与链接日志，L3 未验证 |
| `long t` | `compute_timezone_value` 栈上创建，函数返回后结束生命周期 | `_get_timezone` 返回状态被忽略；无错误码、重试或回退契约 | 无异步等待，取消不适用 | 栈变量由函数返回自然结束，无显式释放 | C++ 实现 L1 |
| 函数级 `static long value` | 首次 `timezone()` 调用初始化，随后复用 | 首次初始化若得到错误/默认值会被缓存；没有刷新或失效接口 | 无取消/超时分支 | 进程结束时由运行环境回收；`long` 无析构/释放函数 | C++ 实现 L1 |
| `long&` 返回值 | 调用方借用静态存储的可写引用 | 调用方可写坏共享缓存；源码无只读视图、所有权标记或并发协议 | 无取消/转移协议 | 调用方不得 `free/delete` 或延长为独立所有权；本库没有二次释放路径 | 从签名静态推断，未做运行时验证 |
| CRT `_get_timezone` | 由目标 MSVC CRT 执行 | CRT/版本/线程环境异常由调用方进程承受；返回状态未转换 | 无本项目超时/取消 | CRT 内部资源不由本库显式拥有 | 依赖声明 L1/L2，未实测 |
| 运行时加载/卸载 | 当前不存在 | `LoadLibrary`、句柄泄漏、卸载顺序等不适用 | 不适用 | 不存在本项目可释放的 DLL 句柄、线程、队列、文件或连接 | 源码/文件清单未发现，L1 |

项目没有堆内存、文件、数据库、网络、线程、进程、动态库句柄或 GPU 资源；“释放完成”只能对栈上的 `t` 和进程结束时的静态 `value` 作有限描述。不能把没有资源对象误报成已经覆盖了主动取消、宿主崩溃清理或二次释放测试；这些路径是“不适用/未验证”，而非通过。

## 14. L0-L4 证据等级与本轮结论

本轮采用以下等级，避免把声明当实现或把静态存在当运行通过：

| 等级 | 定义 | 本项目证据 |
|---|---|---|
| L0 | README、注释、工程意图或历史描述 | README 的“解决 VC6 缺少 `timezone`”用途声明 |
| L1 | 直接读取源码/文件清单得到的静态事实 | 两个函数体、`extern "C"`、CRT 调用、静态缓存、无头文件/无加载器 |
| L2 | 构建图/配置/版本声明得到的事实 | `StaticLibrary`、Win32/x64、`v141`/`v143`、SDK 10.0.22000.0、`.sln` 映射 |
| L3 | 实际产物或链接级验证 | **未完成**：无 Windows/MSVC、无 `.lib`、无 `dumpbin` 符号表、无消费者链接夹具 |
| L4 | Windows 目标环境中的运行/集成/失败释放验证 | **未完成**：无 VC6 旧库调用方、无最终进程、无运行日志和资源现场 |

**第三轮可吸收结论**：实现性质上属于 ABI 支持库中的最小静态兼容 shim；`.sln`/`.vcxproj` 属于开发工具的生成输入；它不构成运行核心，也没有运行时加载契约。**待核结论**：能否准确满足目标 VC6 静态库的实际外部引用、x86/x64 下的符号拼写、`long&` 返回 ABI、各 CRT/工具集组合以及 `_get_timezone` 失败语义，必须在 Windows/MSVC 与真实消费者上升到 L3/L4 后才能裁决。

## 15. 第三轮缺口与验收契约

若要从“候选兼容 shim”升级为可复用 ABI 支持包，开发工具侧至少应生成/记录：

1. 目标架构、工具集、Windows SDK、CRT 选择和配置名称；
2. 实际 `.lib` 的符号清单（含 Win32/x64 对比）及其与旧消费者未解析符号的匹配结果；
3. 可包含的正式公共声明，明确 `extern "C"`、调用约定、`long` 宽度和 `timezone` 可写引用的所有权/并发限制；
4. `_get_timezone` 失败时的明确契约：返回码、默认值是否允许、是否重试、缓存是否失效；当前实现没有这些字段；
5. 至少一个真实旧库/最小消费者的链接夹具，并分别记录正常链接、缺库、错架构、符号不匹配和 CRT/工具集不兼容的失败结果；
6. 若保持静态库，验收对象是链接期归档和最终映像，不应伪造“加载成功”；若改动态库，则另建加载/卸载和句柄释放验收。

当前文件只记录这些装配与验收要求，未修改源码、工程配置或测试，也未把任何 L3/L4 结果写成已通过。

## 16. 本轮环境问题与验证声明

开工 `project_context` 返回了不相关的 `~/Documents/Agent/PHP/华世王镞_v3` 项目上下文；该错绑结果已按要求**不作为本仓库证据**，本轮改以目标目录的本地源码、工程文件和 Git 现场静态取证，并将链接/运行结论标为 L0-L2 或待核。目标仓库本轮唯一修改文件仍是根目录 `ARCHITECTURE.md`。
