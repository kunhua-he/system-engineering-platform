# spec（易语言特殊功能支持库）架构建档

## 1. 文档边界与结论口径

本文件是仓库根目录唯一的架构建档，依据当前本地源码、Visual Studio 工程文件和 Git 基线人工读取整理。只允许把源码中可以定位的事实写成“已实现”；工程声明、注释说明、命令元数据或未在当前环境执行的内容分别标为“仅声明/设计信息”或“未验证”。本轮没有修改源码、工程、依赖、测试、配置或 Git，也没有删除旧细探文件。

仓库未发现 `README.md`、`AGENTS.md` 或 `细探-*.md`；因此本文件不以缺失的说明文档作为实现证据。源码中大量中文文本以 GB18030/本地 Windows 编码保存，接口标识符和源码路径保持原文。

**一句话定位：** `spec` 是一个面向易语言 Windows 运行时/IDE 的动态支持库，同时提供一套静态库工程复用同一批命令实现；它向易语言注册“特殊功能支持库”的版本、分类、命令、参数和执行函数，并通过 `GetNewInf`、系统通知回调和 `krnln.fne` 交互完成地址获取、调试、调用、延迟、内存、系统功能等高级能力。

## 2. 总体流程

```text
易语言 IDE/运行时
    │ 加载 spec.fne，按固定导出名调用 GetNewInf()
    ▼
LIB_INFO（spec_dllMain.cpp）
    ├─ 版本/GUID/语言/OS/依赖描述
    ├─ 4 个全局命令类别
    ├─ CMD_INFO[] ← SPEC_DEF(_MAKE) 单一命令清单
    │                 └─ ARG_INFO[] 参数类型、默认值、变量/数组标志
    ├─ PFN_EXECUTE_CMD[] ← 与命令表按索引一一对应
    ├─ 空的自定义数据类型表、空的常量表
    └─ spec_ProcessNotifyLib_spec()
              │ NL_SYS_NOTIFY_FUNCTION 注入 PFN_NOTIFY_SYS
              ▼
    elib/fnshare.cpp：缓存系统通知函数、查询调试/运行版本
              │ NotifySys(NRS_*)
              ├──────────────► 易语言运行时：事件循环、内存申请/释放、程序类型
              │
              └─ spec_cmdDef.cpp 各命令执行函数
                    ├─ 直接读写 PMDATA_INF 参数/返回值
                    ├─ 调用 NotifySys()
                    ├─ 调用 krnln.fne 的 GetNewInf/命令表（调试输出、检查）
                    └─ timeSetEvent → TimerProc → 延迟调用子程序

spec_static.vcxproj
    └─ 以 __E_STATIC_LIB 编译同一批 .cpp，生成静态库；通过命令名数组和通知函数名
       为静态编译链提供符号信息（是否可成功产物化：本机未验证）。
```

## 3. 真实目录与分层

```text
spec/
├── spec.sln                         Visual Studio 解决方案，包含动态/静态两个项目
├── spec.vcxproj                     动态库项目（DynamicLibrary）
├── spec_static/
│   └── spec_static.vcxproj          静态库项目（StaticLibrary），引用上级同一批源码
├── Source_spec.def                  动态库导出定义，仅导出 GetNewInf
├── include_spec_header.h            项目总头：底座头、命令宏、全局表声明、命令函数声明
├── spec_cmd_typedef.h               SPEC_DEF 单一命令清单和命名拼接宏
├── spec_cmdInfo.cpp                 ARG_INFO 参数表、CMD_INFO 命令元数据表
├── spec_cmdDef.cpp                  16 个命令实现及其辅助函数
├── spec_dllMain.cpp                 DllMain、LIB_INFO、GetNewInf、通知入口、静态名数组
├── spec_const.cpp                   空常量表（仅占位）
├── spec_dtType.cpp                  空自定义数据类型表（仅占位）
└── elib/                            易语言支持库 ABI/运行时共享定义
    ├── lib2.h                       DATA_TYPE、ARG_INFO、CMD_INFO、MDATA_INF、LIB_INFO 等核心 ABI
    ├── fnshare.h/.cpp                NotifySys、内存/数据复制辅助、通知状态缓存
    ├── krnllib.h                     系统核心支持库数据类型编号、版本和索引常量
    ├── lang.h                        语言版本常量，当前为 GBK
    ├── mtypes.h                      Windows 基础类型兼容定义与宏
    ├── untshare.h                    组件/事件/属性/通知相关共享结构
    └── PublicIDEFunctions.h          IDE 插件/附加功能号常量与数据结构
```

## 4. 模块职责与实现状态

### 4.1 ABI 和公共运行时层（已实现为源码依赖）

- `elib/lib2.h:1-35` 定义 `__E_FNENAME` 命名拼接、`DEF_EXECUTE_CMD`、静态库符号避免冲突的宏；`elib/lib2.h:158-243` 定义 `SDT_*`、数组/变量标志和 `DATA_TYPE`；`elib/lib2.h:266-364` 定义 `ARG_INFO`、`CMD_INFO`；`elib/lib2.h:780-824` 定义 `MDATA_INF` 参数/返回值联合体；`elib/lib2.h:1239-1318` 定义 `PFN_EXECUTE_CMD`、`LIB_INFO` 和固定入口 `GetNewInf`。
- `elib/mtypes.h:10-58` 提供 `INT`、`DWORD`、`BOOL`、指针、句柄等基础类型；`elib/lang.h:8-14` 将编译语言版本设为 `__GBK_LANG_VER`。
- `elib/fnshare.h:21-194` 提供运行时导入函数宏、文本/字节集复制、数组访问和数据类型判断辅助；`elib/fnshare.cpp:7-70` 实际维护 `s_pfnNotifySys`、`s_isDebug` 并实现 `NotifySys`、`ProcessNotifyLib`、`SetUserSysNotify`。
- 这些文件属于支持库 ABI 的本地共享实现，不是独立第三方包；工程未声明外部包管理器或运行时安装步骤。

### 4.2 命令清单和元数据层（已实现表结构；内容部分是声明）

`spec_cmd_typedef.h:3-9` 将命令实现符号规范化为 `spec_<英文名>_<索引>_spec`（静态模式还会拼接 `__E_FNENAME`）。`spec_cmd_typedef.h:12-28` 的 `SPEC_DEF(_MAKE)` 是唯一命令清单，共 16 项，包含中文名、英文名、说明、分类、OS/状态标志、返回类型、难度级别、参数起始位置和参数数目。

`spec_cmdInfo.cpp:5-71` 实际填充参数元数据，`spec_cmdInfo.cpp:83-88` 由同一清单生成 `CMD_INFO[]` 和命令数量。参数类型、默认空参数、数组/变量接收约束属于 IDE 编辑/调用契约；它们不是执行逻辑本身。`_DEBUG` 下的参数序号计数只在 `spec_cmdInfo.cpp:73-75` 生成变量，未见单独测试断言。

命令清单如下（状态是源码审阅结论，不代表已在易语言宿主运行）：

| 索引 | 易语言命令 | 执行函数 | 源码状态 | 主要边界 |
|---:|---|---|---|---|
| 0 | `置入代码` | `spec_MachineCode_0_spec` | **仅声明/空实现** | 隐藏命令；函数体 `spec_cmdDef.cpp:7-14` 无逻辑 |
| 1 | `取变量地址` | `spec_GetVarAddress_1_spec` | **已实现，未验证** | 从 `m_ppCompoundData` 转为地址；`spec_cmdDef.cpp:16-22` |
| 2 | `取子程序地址` | `spec_GetSubAddress_2_spec` | **已实现，未验证** | 从 `m_pCompoundData` 取地址；`spec_cmdDef.cpp:24-29` |
| 3 | `取变量数据地址` | `spec_GetVarDataAddr_3_spec` | **已实现，未验证** | 数组、基本类型、文本、字节集分支；`spec_cmdDef.cpp:32-94` |
| 4 | `调试输出` | `spec_Trace_4_spec` | **已实现，依赖外部库，未验证** | 格式化基本类型/数组后调用 `krnln.fne` 的“输出调试文本”；`spec_cmdDef.cpp:111-292,352-379` |
| 5 | `验证` | `spec_Verify_5_spec` | **已实现，依赖外部库，未验证** | 判断零值，调试运行时调用核心库“检查”；`spec_cmdDef.cpp:381-457` |
| 6 | `调用子程序` | `spec_CallFunction_6_spec` | **已实现源码，Win32 汇编路径，未验证** | 手工压栈、调用地址、回填多种返回类型；`spec_cmdDef.cpp:459-623` |
| 7 | `延迟` | `spec_Delay_7_spec` | **已实现，未验证** | `GetTickCount64` 忙等并反复 `NRS_DO_EVENTS`；`spec_cmdDef.cpp:625-642` |
| 8 | `推迟调用子程序` | `spec_DelayCallFunction_8_spec` | **已实现源码，未验证** | `timeSetEvent` 异步回调；`spec_cmdDef.cpp:644-775` |
| 9 | `申请内存` | `spec_AllocMem_9_spec` | **已实现，未验证** | `NRS_MALLOC`，可选 `memset` 清零；`spec_cmdDef.cpp:777-789` |
| 10 | `释放内存` | `spec_FreeMem_10_spec` | **已实现，未验证** | `NRS_MFREE`；`spec_cmdDef.cpp:791-796` |
| 11 | `调用易系统功能` | `spec_ESysFunction_11_spec` | **已实现，未验证** | 转发一个功能号及两个可选整数参数；`spec_cmdDef.cpp:798-806` |
| 12 | `取文本` | `spec_GetText_12_spec` | **仅声明/空实现** | 只读取两个数组指针后结束，未完成替换/格式化逻辑；`spec_cmdDef.cpp:808-816` |
| 13 | `取文本_属性设置` | `spec_GetText_Set_13_spec` | **仅声明/空实现** | 只读取四个文本参数，未写入状态或设置返回值；`spec_cmdDef.cpp:818-830` |
| 14 | `取文本_属性读取` | `spec_GetText_Get_14_spec` | **仅声明/空实现** | 只读取四个输出指针，未填充输出；`spec_cmdDef.cpp:832-844` |
| 15 | `推迟调用子程序_高精度计时` | `spec_DelayCallFunction_precisely_15_spec` | **已实现源码，未验证** | 复用异步参数复制/回调，分辨率传 `0`；`spec_cmdDef.cpp:846-864` |

### 4.3 支持库装载和通知层（已实现）

- `spec_dllMain.cpp:7-24` 的 `DllMain` 对四种 DLL 生命周期事件只做空处理并返回 `TRUE`，没有可见的初始化/清理逻辑。
- `spec_dllMain.cpp:31-87` 构造 `LIB_INFO`：格式号 `LIB_FORMAT_VER`、GUID `A512548E76954B6E92C21055517615B0`、版本 `3.1.0`、所需易系统 `3.8`、所需核心库 `3.0`、GBK、全 OS、4 个分类、命令数组、函数指针数组、空常量/数据类型表和 `spec_ProcessNotifyLib_spec` 通知函数。
- `Source_spec.def:1-5` 只导出 `GetNewInf`；`spec_dllMain.cpp:89-92` 实现同名入口并返回 `LIB_INFO` 地址。
- `spec_dllMain.cpp:101-177` 实现通知分派。动态库模式响应 `NL_GET_CMD_FUNC_NAMES`、`NL_GET_NOTIFY_LIB_FUNC_NAME`、`NL_GET_DEPENDENT_LIBS`；所有模式对 `NL_SYS_NOTIFY_FUNCTION` 调用 `ProcessNotifyLib`。其余列出的通知目前是空处理，未知消息返回 `NR_ERR`。
- `elib/fnshare.cpp:24-70` 接收宿主传入的 `PFN_NOTIFY_SYS`，然后通过 `NRS_GET_PRG_TYPE` 查询运行版本；用户自定义回调 `s_pfnuserNotifySys` 会在处理后被调用。

### 4.4 静态库适配层（工程已声明，未验证）

`spec_static/spec_static.vcxproj:21-38` 引用动态项目相同的 6 个 `.cpp` 与公共头文件，配置为 `StaticLibrary`（`spec_static/spec_static.vcxproj:48-72`），Debug/Release、Win32/x64 均有声明。`spec_dllMain.cpp:94-98` 生成静态命令名称数组；`spec_cmd_typedef.h:3-9` 和 `elib/lib2.h:12-41` 提供命名改写。

但 `spec_static` 的 x64 配置使用预编译头 `pch.h`（`spec_static/spec_static.vcxproj:130-154`），仓库中没有 `pch.h`；同时动态工程 Win32 配置明确使用 `Source_spec.def` 和 `.fne`（`spec.vcxproj:95-126`），x64 配置未看到相同的模块定义/目标扩展设置。上述是静态工程/配置事实，不等价于构建必然失败；本机 macOS 没有执行 Visual Studio/MSBuild，因此标为未验证。

## 5. 核心数据模型与调用契约

### 5.1 支持库注册模型

`LIB_INFO`（`elib/lib2.h:1248-1315`）是宿主识别支持库的根模型：格式和版本、GUID、系统/核心库最低版本、名称/语言/说明、OS 与库状态、作者信息、数据类型表、类别表、命令表、执行函数表、通知函数、常量表和依赖文件列表。当前实例由 `spec_dllMain.cpp:31-87` 静态构造，除命令/通知外的附加能力多为空指针或空表。

### 5.2 命令与参数模型

- `CMD_INFO`（`elib/lib2.h:297-364`）：名称、英文名、解释、分类、状态位、返回 `DATA_TYPE`、用户级别、图标信息、参数数量和参数表起始指针。
- `ARG_INFO`（`elib/lib2.h:266-292`）：参数名、解释、图标信息、期望类型、默认值和 `AS_*` 参数接收约束。
- `MDATA_INF`（`elib/lib2.h:780-824`）：一个运行时参数/返回值。联合体可承载基本值、文本/字节集指针、子程序地址、数组/复合数据指针以及接收变量时的各类指针；`m_dtDataType` 另带 `_SDT_NULL`、`DT_IS_ARY` 等标志。
- 执行 ABI 固定为 `PFN_EXECUTE_CMD(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)`（`elib/lib2.h:1239`）。`include_spec_header.h:22-24` 用清单生成所有实现函数声明，`spec_dllMain.cpp:26-29` 用同一清单生成函数指针数组，保证设计上的索引对齐。

### 5.3 自定义类型和常量模型

`LIB_DATA_TYPE_INFO`（`elib/lib2.h:693-729`）支持组件事件、属性、接口或复合成员；`LIB_CONST_INFO`（`elib/lib2.h:735-748`）支持空/数值/逻辑/文本常量。但本仓库的 `spec_dtType.cpp:7-8` 和 `spec_const.cpp:15-16` 将两者数量都设为 `0`，因此当前库没有注册自定义数据类型和预定义常量。不能把底座头文件中定义的能力误写成 spec 已提供能力。

## 6. 关键数据流与真实调用链

### 6.1 装载与命令发现

1. 宿主装载 `spec.fne`，按 `Source_spec.def:3-5` 查找 `GetNewInf`。
2. `GetNewInf` 返回 `g_LibInfo_spec_global_var`（`spec_dllMain.cpp:89-92`）。
3. 宿主从 `LIB_INFO` 读取 `CMD_INFO[]`、参数表和 `PFN_EXECUTE_CMD[]`；命令表由 `SPEC_DEF` 生成（`spec_cmdInfo.cpp:78-88`）。
4. 宿主发送 `NL_SYS_NOTIFY_FUNCTION`，`spec_ProcessNotifyLib_spec` 转发到 `ProcessNotifyLib`；后者保存系统回调并查询程序类型（`spec_dllMain.cpp:125-132`、`elib/fnshare.cpp:24-36`）。

### 6.2 调试输出

`spec_Trace_4_spec` 遍历参数（`spec_cmdDef.cpp:352-367`），按基本类型或数组格式化为一行文本（`spec_cmdDef.cpp:111-292`），复制文本后通过 `CallElibFunc("krnln.fne", "输出调试文本", ...)` 查找并调用核心库命令（`spec_cmdDef.cpp:294-348,373-377`）。因此调试输出的最终显示依赖宿主安装的 `krnln.fne` 和其命令名，不是本库内部实现。

### 6.3 验证

`spec_Verify_5_spec` 对所有参数调用 `verify_IsZeroValue`（`spec_cmdDef.cpp:383-448`），按数字、逻辑、文本、字节集、日期、子程序指针或数组判断零值；只有 `NRS_GET_PRG_TYPE` 返回 `PT_DEBUG_RUN_VER` 时才通过 `CallElibFunc` 调核心库“检查”（`spec_cmdDef.cpp:449-455`）。源码注释说明的“运行版继续执行参数语句”属于命令意图；当前函数未直接执行参数表达式，只对传入的已求值参数做检查。

### 6.4 内存和系统能力

`申请内存` 调 `NotifySys(NRS_MALLOC, size, 0)`，可选清零；`释放内存` 调 `NotifySys(NRS_MFREE, address, 0)`（`spec_cmdDef.cpp:780-796`）。`调用易系统功能` 将功能号和两个可选整数转发给 `NotifySys`（`spec_cmdDef.cpp:802-806`）。这些操作完全依赖宿主 `PFN_NOTIFY_SYS` 已成功注入；若未注入，`elib/fnshare.cpp:11-16` 返回默认 `0`。

### 6.5 延迟调用

`推迟调用子程序` 在非正延迟时立即调用 `spec_CallFunction_6_spec`，否则 `dalayecallfunc::mytimeSetEvent` 复制 `pArgInf[1..]` 到堆内存，调用 Windows `timeSetEvent`，回调 `TimerProc` 再调用子程序并释放参数（`spec_cmdDef.cpp:696-775`）。高精度命令复用该路径但将分辨率传 `0`（`spec_cmdDef.cpp:852-862`）。源码仅复制 `MDATA_INF` 浅层结构，文本/字节集/复合成员的生命周期由调用方保障，注释也明确提示需保证异步调用时参数仍有效；当前实现未见深拷贝、取消句柄或全局生命周期管理。

## 7. 技术栈、平台和外部依赖

| 类别 | 现场证据 | 结论 |
|---|---|---|
| 语言 | `.cpp`/`.h`，`spec.vcxproj:22-38` | C++，包含 Windows API、内联汇编和 C++ STL |
| 构建 | `spec.sln:1-14` | Visual Studio 17 解决方案，兼容最低 VS 10；Debug/Release、Win32/x64 |
| 动态产物 | `spec.vcxproj:51-76`、`95-126` | `DynamicLibrary`；Win32 显式目标扩展 `.fne`，x64 未显式设置 `.fne` |
| 静态产物 | `spec_static/spec_static.vcxproj:48-72` | `StaticLibrary`；复用同一批源码 |
| 工具集 | `spec.vcxproj:54,60,67,73` | `v141` |
| Windows SDK | `spec.vcxproj:48` | `10.0.15063.0` |
| 系统 API | `spec_cmdDef.cpp:298-315,631,753` | `LoadLibraryA`、注册表 `Software\\FlySky\\E\\Install`、`GetTickCount64`、`timeSetEvent`、`VariantTimeToSystemTime` 等 |
| 链接库 | `spec_cmdDef.cpp:6` | `#pragma comment(lib, "winmm.lib")` |
| 宿主支持库 | `spec_cmdDef.cpp:294-348,373-377,449-455` | 运行时通过 `krnln.fne`、`GetNewInf` 和命令表调用“输出调试文本”“检查” |
| 语言编码 | `elib/lang.h:8-14`、`spec_dllMain.cpp:45` | GBK/GB18030 语言版本 |
| 第三方包 | 工程未发现包管理文件 | 未声明外部包管理依赖 |

`CallElibFunc` 首先按给定文件名加载 `krnln.fne`；失败后读取当前用户注册表 `HKCU\\Software\\FlySky\\E\\Install` 的 `Path` 值并拼接文件名（`spec_cmdDef.cpp:294-316`）。这同时构成运行环境前置条件和 Windows-only 边界。

## 8. 接口、导出和插件边界

### 外部导出

- `GetNewInf()`：唯一 DLL 导出，返回 `PLIB_INFO`；定义在 `Source_spec.def:3-5`、实现于 `spec_dllMain.cpp:89-92`。
- 命令函数不是直接 DLL 导出名，而是通过 `LIB_INFO.m_pCmdsFunc` 指针表暴露给易语言运行时；动态模式命名由 `SPEC_NAME` 拼接，静态模式另提供 `g_cmdNamesspec`。

### 宿主回调

- `PFN_NOTIFY_SYS`：宿主通过 `NL_SYS_NOTIFY_FUNCTION` 传入，库使用 `NotifySys` 转发 `NRS_*` 通知；定义见 `elib/lib2.h:1229`，缓存见 `elib/fnshare.cpp:11-36`。
- `PFN_NOTIFY_LIB`：`LIB_INFO.m_pfnNotify` 指向 `spec_ProcessNotifyLib_spec`，处理系统向支持库发送的通知；未知消息返回 `NR_ERR`。

### 静态编译协议

`NL_GET_CMD_FUNC_NAMES` 返回命令实现函数名数组，`NL_GET_NOTIFY_LIB_FUNC_NAME` 返回通知函数名，`NL_GET_DEPENDENT_LIBS` 返回空依赖串（`spec_dllMain.cpp:106-123`）。这部分有源码实现，但没有当前平台构建或宿主静态编译验证证据。

## 9. 测试、构建与验证状态

### 仓库内测试

未发现测试目录、测试源文件、CI 配置、构建脚本或样例宿主工程。仓库仅有 23 个 Git 跟踪文件，其中 6 个 `.cpp`、9 个公共头、动态/静态 VS 工程及解决方案。源码存在 `_DEBUG` 参数计数变量（`spec_cmdInfo.cpp:73-75`），但它不是测试套件。

### 本轮已完成的静态核验

- 人工读取 `spec.sln`、两个 `.vcxproj`、`Source_spec.def`、项目头、全部项目源码和 `elib` 关键 ABI 定义。
- 核对 `SPEC_DEF` 的 16 个索引与 `spec_cmdDef.cpp` 函数命名；清单索引为 `0..15`，无重复索引。
- 核对动态入口、命令元数据数组、函数指针数组、通知函数和空数据类型/常量表的连接关系。
- 核对本地分支与远程跟踪分支均指向 `4a84e04141ea0cd546c8202e4da8a9a1a0001ccf`，工作树在建档前干净。

### 未执行/不能据此宣称通过的验证

- 本机为 macOS，未执行 Visual Studio/MSBuild、Windows 链接、`.fne` 产物加载或易语言宿主运行。
- 未执行真实 `krnln.fne` 交互、系统通知回调、内存申请/释放、异步计时器和命令调用 ABI 测试。
- 未执行静态库链接、Win32 内联汇编路径、x64 配置构建或 `Source_spec.def` 导出检查。
- 因而“已实现”仅表示源码存在非空执行路径；不表示 ABI 正确、宿主兼容、线程安全或可发布。

## 10. 风险与未确认项

1. **明显空实现：** `置入代码`、`取文本`、`取文本_属性设置`、`取文本_属性读取` 的元数据已注册，但函数体没有完成对应功能；宿主仍可能把它们展示/调用为有效命令。
2. **32/64 位边界：** 工程同时声明 x64，但 `取变量地址`、`取子程序地址`、`取变量数据地址` 和 `调用子程序` 大量使用 `int`/`DWORD` 保存指针，且 `CallFunction` 使用 MSVC `__asm`（`spec_cmdDef.cpp:464-540`）。x64 是否可编译、指针是否截断、调用约定是否成立均未验证。
3. **数组地址辅助函数可疑：** `get_arry_pdata` 的 `if (!nElementCount == 0)`（`spec_cmdDef.cpp:44-47`）运算优先级使其语义与直观的“元素数为 0”检查不同；数组数据布局和空数组行为需要 Windows 宿主实测。
4. **输入结构会被改写：** `spec_GetVarDataAddr_3_spec`、`spec_Trace_4_spec`、`verify_IsZeroValue` 会清除参数 `m_dtDataType` 的 `DT_IS_ARY` 标志（`spec_cmdDef.cpp:55-59,358-359,387-389`），调用方是否允许这种修改未见契约测试。
5. **空参数边界未保护：** 多个命令直接读取 `pArgInf[1]`、`pArgInf[2]` 或输出指针；元数据允许空参数，但实现是否覆盖所有 `nArgCount` 组合未验证。
6. **异步生命周期和线程安全：** 延迟调用只浅复制 `MDATA_INF`；定时器回调在其他线程执行，文本/字节集/复合数据和子程序地址的生命周期、宿主卸载时的回调竞态都没有可见保护。
7. **资源错误路径：** `spec_Trace_4_spec` 创建 `pDebugText` 后未在本函数中显式释放；`CallElibFunc` 仅在部分错误路径释放模块，运行时失败和宿主命令异常的清理策略需实测。
8. **依赖发现依赖注册表：** `krnln.fne` 加载失败时仅查询固定 HKCU 路径，未见 64 位注册表视图、路径编码或关闭/卸载并发策略处理。
9. **工程声明与实际文件漂移：** x64 静态项目配置使用 `pch.h`，仓库文件树没有该文件；动态项目只有 Win32 配置明确设置 `.fne` 和模块定义文件。需在 Windows/Visual Studio 中核实工程是否能完整生成目标产物。
10. **版本新鲜度限制：** 当前仓库已由 `git rev-parse --is-shallow-repository` 现场核实为 `true`；当前可见历史仅一个 grafted 提交，没有可供本地对比的更早历史；本文件只对当前提交负责。

## 11. Git 基线与证据索引

### 基线

- 仓库：`https://gitee.com/JYtechnology/spec.git`
- 分支：`master`；远程跟踪：`origin/master`；二者在建档时同指 `4a84e04141ea0cd546c8202e4da8a9a1a0001ccf`
- 提交时间：`2023-03-04T01:46:01Z`
- 提交标题：`!1 特殊功能支持库 Merge pull request !1 from AlongsCode/master`
- 提交统计：23 个文件、5019 行新增；当前可见提交为该仓库首个/唯一 grafted 提交
- 远程地址：`https://gitee.com/JYtechnology/spec.git`
- 建档前工作树：`master...origin/master`，无状态变更

### 关键证据路径

| 主题 | 证据 |
|---|---|
| 解决方案与平台 | `spec.sln:1-40` |
| 动态/静态工程类型 | `spec.vcxproj:43-76`；`spec_static/spec_static.vcxproj:40-73` |
| 动态 Win32 输出与导出 | `spec.vcxproj:95-126`；`Source_spec.def:1-5` |
| 项目总头和命令函数声明 | `include_spec_header.h:1-26` |
| 16 项命令唯一清单 | `spec_cmd_typedef.h:3-28` |
| 参数表与命令元数据 | `spec_cmdInfo.cpp:5-88` |
| 入口、注册信息和通知 | `spec_dllMain.cpp:7-177` |
| 命令执行实现 | `spec_cmdDef.cpp:7-864` |
| 空常量/数据类型表 | `spec_const.cpp:12-18`；`spec_dtType.cpp:1-10` |
| ABI 结构、类型和调用约定 | `elib/lib2.h:158-364,693-748,780-824,1239-1318` |
| 系统通知和共享辅助 | `elib/fnshare.h:21-194`；`elib/fnshare.cpp:1-71` |
| Windows/语言/核心库常量 | `elib/mtypes.h`；`elib/lang.h:8-14`；`elib/krnllib.h:6-131` |
| IDE 相关能力声明 | `elib/PublicIDEFunctions.h`、`elib/untshare.h` |

## 12. 后续复核顺序

```text
先在 Windows + VS v141 复核工程能否分别产出 Win32 .fne、x64 DLL 和静态库
    ↓
用易语言宿主装载 GetNewInf，核对 LIB_INFO / 16 项命令 / 参数索引
    ↓
逐命令建立 ABI 用例：基本类型、数组、空参数、变量引用、返回值
    ↓
优先补证空实现（取文本三命令、置入代码）与 32/64 位指针/汇编问题
    ↓
再测 krnln.fne 动态查找、NotifySys、内存、调试、异步定时器和卸载竞态
    ↓
把运行证据增量回写本文件；不要以注释或工程配置替代宿主实测结论
```
