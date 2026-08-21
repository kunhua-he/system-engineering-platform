# EasyFne 架构文档

> 本文件是 EasyFne 当前源码的唯一架构事实源。本次只新增本文件；未修改源码、依赖、测试、配置或 Git 历史，未删除任何细探文件。

## 1. 项目定位

EasyFne 是面向易语言支持库（`ELIB`）的 Windows C/C++ 示例工程：通过 Visual Studio 生成动态支持库（`.fne`/DLL）或静态库配置，向易语言 IDE/运行时注册库元数据、数据类型、常量和 4 个整数运算命令。仓库名称为 EasyFne，但源码中的库展示名仍是 `Elib_TEST`，描述为 `VS2019+(runtime14.1-xp)封装测试`，因此应视为支持库封装测试/模板，而不是完整业务应用。

源码基线：

- 远程：`https://github.com/aiqinxuancai/EasyFne.git`
- 分支：`master`
- 本地与远程 `HEAD`：`d0d6cbba761bbed13d13f7e79199a5837d387366`
- 本地提交时间：`2023-09-27T11:13:49+08:00`
- 最新提交主题：`lib2更新`
- 工作树：盘点时干净（`master...origin/master`）

## 2. 总体流程

```text
易语言 IDE / 运行时
        │ 加载支持库并按固定入口取元数据
        ▼
EasyFne.def ──导出──> GetNewInf
        │                  │
        │                  └──返回静态 LIB_INFO
        │                       ├── DataTypes: RECT / Struct
        │                       ├── Commands: AddFunc / SubFunc / MulFunc / DivFunc
        │                       ├── constStruct: 3 个常量
        │                       ├── ExecuteCommand: 命令函数表
        │                       └── ELIB_MessageNotify: 系统通知入口
        ▼
易语言按 CMD_INFO / ARG_INFO 校验参数并调度
        │
        ▼
AddFunc / SubFunc / MulFunc / DivFunc
        │ 通过 PMDATA_INF 读整数参数并写回返回值
        ▼
ELIB_MessageNotify → ProcessNotifyLib → NotifySys
        │                         │
        │                         ├── NL_SYS_NOTIFY_FUNCTION 保存 PFN_NOTIFY_SYS
        │                         ├── NRS_GET_PRG_TYPE 取得运行类型
        │                         └── 可转发用户通知回调
        ▼
易语言系统核心支持库（由运行时提供）
```

## 3. 真实目录与分层

```text
EasyFne/
├── EasyFne.sln                 # 单项目 Visual Studio 解决方案
├── EasyFne.vcxproj             # C++ 工程、配置、源文件清单
├── EasyFne.vcxproj.filters     # Visual Studio 文件筛选器
├── EasyFne.filters             # 旧/附加筛选器文件
├── EasyFne.cpp                 # 库元数据、命令实现、通知入口、GetNewInf
├── EasyFne.h                   # 项目宏、接口声明、库身份常量
├── EasyFne.def                 # DLL 导出：GetNewInf
├── main.cpp                    # 最小 DllMain，不承载业务逻辑
└── elib/
    ├── lib2.h                  # 易语言支持库 ABI：类型、命令、库信息、通知协议
    ├── fnshare.h/.cpp          # 非窗口支持库通用通知、内存和数据辅助层
    ├── PublicIDEFunctions.h    # IDE 公共功能号与结构定义
    ├── krnllib.h               # 核心支持库控件/版本常量
    ├── lang.h                  # 编译语言版本（GBK）
    ├── mtypes.h                # 跨静态库/精简环境的基础类型兼容定义
    └── untshare.h               # 窗口组件/属性序列化辅助（本工程未见命令直接使用）
```

仓库没有 `README.md`、`AGENTS.md`、测试目录、CLI 入口或独立依赖清单；工程文件与源码注释是主要设计说明。

## 4. 核心数据模型

### 4.1 易语言支持库 ABI

`elib/lib2.h` 定义外部 ABI 和元数据结构，关键类型包括：

- `DATA_TYPE` 与 `SDT_INT`、`SDT_TEXT`、`SDT_SHORT`、`SDT_FLOAT`、`SDT_BOOL`、`SDT_DATE_TIME`、`SDT_SUB_PTR`、`SDT_BIN`：易语言数据类型编码。
- `MDATA_INF`：命令参数/返回值载体；整数命令通过其 `m_int` 字段读写。
- `ARG_INFO`：参数名称、说明、图像索引、数据类型、默认值和参数类别。
- `CMD_INFO`：命令中英文名、说明、分类、返回类型、等级、参数数量和 `ARG_INFO` 指针。
- `LIB_DATA_TYPE_ELEMENT` / `LIB_DATA_TYPE_INFO`：自定义数据类型及成员描述。
- `LIB_CONST_INFO`：常量名称、说明、难度、值类型和值。
- `LIB_INFO`：库格式、GUID、版本、所需系统/核心库版本、名称、语言、状态、数据类型、分类、命令、执行函数、消息入口和常量等完整注册信息。

### 4.2 本项目注册的数据

`EasyFne.cpp` 中的静态表构成运行时注册模型：

- 自定义数据类型：`RECT`（中文名“矩形”，4 个 `SDT_INT` 成员 `left`/`top`/`right`/`bottom`）；`Struct`（中文名“复杂数据结构”，包含 `SDT_TEXT`、`SDT_SHORT`、`SDT_FLOAT`、`SDT_BOOL`、`SDT_DATE_TIME`、`SDT_SUB_PTR`、`SDT_BIN` 成员）。
- 常量：`ELB_VERSION`（文本 `1.0`）、`ELB_BOOL`（布尔真值）、`ELB_DOUBLE`（浮点值 1）。
- 命令类别：`LIB_TYPE_COUNT = 1`，类别串为 `0000基本命令`。
- 命令：`ELIB_加法`/`AddFunc`、`ELIB_减法`/`SubFunc`、`ELIB_乘法`/`MulFunc`、`ELIB_除法`/`DivFunc`；每个命令接受两个 `SDT_INT` 参数并返回 `SDT_INT`。

`LIB_INFO` 当前声明：GUID `{0961812A-BCF6-4639-90C6-64AB71945D22}`，库版本 `1.1`，构建号 `20180810`，所需易语言系统版本 `3.0`，所需核心支持库版本 `3.0`，语言 `__GBK_LANG_VER`，运行平台 `__OS_WIN`。

## 5. 关键调用链与执行语义

### 5.1 动态库加载与元数据

1. Windows 装载 DLL；`main.cpp` 的 `DllMain` 只对四类进程/线程通知直接放行并返回 `TRUE`。
2. `EasyFne.def` 仅导出 `GetNewInf`。
3. 易语言调用 `GetNewInf()`，取得 `EasyFne.cpp` 中静态 `LibInfo` 地址。
4. `LibInfo` 将 `DataTypes`、`Commands`、`ExecuteCommand`、`ELIB_MessageNotify` 和 `constStruct` 连接到 ABI 元数据。
5. `Commands` 的顺序必须与 `ExecuteCommand`、`CommandNames` 一一对应；当前顺序为加、减、乘、除。

### 5.2 四个命令

- `AddFunc(PMDATA_INF pRetData, INT iArgCount, PMDATA_INF pArgInf)`：当参数数为 2 时写入 `pArgInf[0].m_int + pArgInf[1].m_int`。
- `SubFunc(...)`：当参数数为 2 时写入减法结果。
- `MulFunc(...)`：当参数数为 2 时写入乘法结果。
- `DivFunc(...)`：源码条件是 `iArgCount == 2 && pArgInf[0].m_int != 0`，但实际除数是 `pArgInf[1].m_int`；这意味着零除检查疑似检查错参数，且不满足条件时没有显式错误结果。该行为未经运行时验证，应作为复核风险保留，不能当作已修复事实。

### 5.3 系统通知与运行时桥接

`ELIB_MessageNotify` 先处理动态库专用查询：

- `NL_GET_CMD_FUNC_NAMES` → 返回 `CommandNames`；
- `NL_GET_NOTIFY_LIB_FUNC_NAME` → 返回 `LIBARAYNAME`（`ELIB_MessageNotify`）；
- `NL_GET_DEPENDENT_LIBS` → 返回 `NULL`；
- 其余消息转到 `ProcessNotifyLib`。

`elib/fnshare.cpp` 的 `ProcessNotifyLib` 负责：

1. 收到 `NL_SYS_NOTIFY_FUNCTION` 时保存系统回调 `PFN_NOTIFY_SYS`；首次初始化通过 `NotifySys(NRS_GET_PRG_TYPE, 0, 0)` 取得调试/发布运行类型。
2. `NotifySys` 通过系统回调转发 `NRS_*` 请求；`ealloc`/`efree` 等 `fnshare.h` 辅助函数最终依赖该通道。
3. `SetUserSysNotify` 保存用户回调并返回 `ProcessNotifyLib` 地址。
4. 未处理消息默认返回 `NR_ERR`；存在用户回调时再转发，回调结果覆盖当前返回值。

## 6. API、插件与 CLI 边界

### 对外 DLL/API 边界

- 固定导出：`GetNewInf`（`EasyFne.def`）。
- 运行时消息入口：`ELIB_MessageNotify`，通过 `LIB_INFO` 暴露，不是 `.def` 中的直接导出。
- 命令 ABI：`PFN_EXECUTE_CMD` 形态的 `AddFunc`、`SubFunc`、`MulFunc`、`DivFunc`。
- 依赖通知 ABI：`PFN_NOTIFY_SYS`、`ProcessNotifyLib`、`NotifySys`、`SetUserSysNotify`。
- 命名宏：`lib2.h` 的 `__LIB2_DEFFUNNAME` 将符号拼接为 `console_<函数名>_console`（由 `__E_FNENAME console` 控制），用于静态库避免符号冲突。

### 不存在的边界

- 没有 HTTP、RPC、数据库、配置文件、命令行参数、服务进程、插件发现器或跨平台运行入口。
- `PublicIDEFunctions.h` 提供易语言 IDE 功能号/结构协议，但本项目未发现实际命令调用这些 IDE 功能；只能视为随支持库模板携带的契约头文件。

## 7. 技术栈与依赖边界

| 层 | 实际内容 |
|---|---|
| 语言 | C++，项目源码使用 GB18030/GBK 中文编码；部分工程文件为 UTF-8 BOM |
| 平台 | Windows；`windows.h`、Win32 DLL ABI、`WINAPI`/`__stdcall` |
| IDE/构建 | Visual Studio 解决方案格式 12，`VisualStudioVersion = 16.0.30717.126`；`.vcxproj` 默认 `ToolsVersion=14.0` |
| 工具集 | `v143` 与兼容旧系统的 `v141_xp` 混用，具体由配置决定 |
| 运行库 | `fne_debug`/`fne_release` 配置显式使用 `MultiThreaded`；动态库/静态库输出由配置决定 |
| 外部运行时 | 易语言系统与核心支持库通过 `PFN_NOTIFY_SYS`、`NRS_*` 消息提供；不是仓库内可独立替代的依赖 |
| 随附 ABI | `elib/lib2.h`、`fnshare.*`、`mtypes.h`、`krnllib.h`、`PublicIDEFunctions.h` 等头/实现 |

工程引用的编译单元只有 `EasyFne.cpp`、`elib/fnshare.cpp`、`main.cpp`；没有包管理器、第三方源码依赖或安装脚本。

## 8. 构建配置与产物

`EasyFne.sln` 只包含项目 `EasyFne`，映射 `x86` 到 `Win32`。工程列出 `Debug`、`Release`、`fne_debug`、`fne_release`、`static_lib_debug`、`static_lib_release` 的 Win32/x64 组合。

- `fne_debug|Win32` 和 `fne_release|Win32` 将目标扩展名设为 `.fne`，输出到 `bin\\$(Configuration)\\`，中间文件到 `bin\\intermediate\\...`。
- 普通 `Debug`/`Release` 配置为 `DynamicLibrary`，使用 `Elib_fne.def`；`fne` 配置使用 `EasyFne.def` 或对应配置中的模块定义文件。
- 静态配置在项目文件中同时出现 `StaticLibrary` 与 x64 配置差异，尤其 `static_lib_debug|x64`、`static_lib_release|x64` 的 `ConfigurationType`/目标行为需要在 Windows Visual Studio 中实测，不据配置文本推断最终产物。
- 本机为 macOS，未安装/启动 Windows Visual Studio；本次未安装依赖、未构建、未启动 DLL，也未生成任何构建物。

## 9. 测试与验证现状

仓库没有测试目录、测试工程、CI 配置或 README 中的验证命令。可做的源码级检查包括：

- 表结构与 `LIB_INFO` 字段数量/顺序静态核对；
- `Commands`、`CommandNames`、`ExecuteCommand` 顺序一致性核对；
- Windows Visual Studio 下编译各 `fne_*` 配置；
- 在真实易语言 IDE/运行时中加载 `.fne`，验证 `GetNewInf`、四个命令、通知回调和静态库配置；
- 专门验证 `DivFunc` 的零除条件、参数数错误和返回值未初始化路径。

本次未执行构建或运行测试；“没有测试文件”与“测试通过”严格区分。

## 10. 风险、未确认项与后续复核

1. `DivFunc` 的除零条件检查 `pArgInf[0].m_int != 0` 与实际除数 `pArgInf[1].m_int` 不一致，需在真实 ABI 环境确认是否为示例代码缺陷。
2. `INT`/`DWORD`/指针在 `mtypes.h` 与 Windows 头之间存在兼容宏和位宽假设；x64 配置是否安全不能仅凭 macOS 静态阅读确认。
3. `LIB_DESCRIPTION_STR`、`LIB_NAME_STR`、GUID、构建号仍为测试模板值，不能据此推断发布身份。
4. `ProcessNotifyLib` 的 `NL_FREE_LIB_DATA`、依赖库查询等分支为空或返回默认值；实际易语言版本兼容性未验证。
5. `EasyFne.h` 直接 `#include "fnshare.cpp"`，同时工程又单独编译 `elib/fnshare.cpp`；当前工程可能依赖宏/链接配置避免重复定义，需在目标 Windows 工具链实测。
6. 易语言官方支持库头文件注释声明存在授权范围；任何复用必须遵循原项目和易语言授权条件。
7. 未发现 `细探-*.md`；因此没有旧细探可吸收或删除。

## 11. 第三轮：FNE/DLL ABI、加载、注册与生命周期

> 本节是基于当前仓库源码的第三轮增量，不把平台的 L0-L4 当成 EasyFne 已有实现。源码没有 HTTP/RPC、句柄注册表、受管子进程或统一网关；下文的底座归属是映射与裁决。`project_context` 本轮错误绑定到 `~/Documents/Agent/PHP/华世王镞_v3`，该环境问题不作为 EasyFne 证据；以下证据全部重新取自本目录静态源码，因此验证强度为“源码存在/未运行”。

### 11.1 ABI 边界与动态/静态两条装载路径

| 边界 | 当前源码事实 | 资源/所有权含义 | 底座归属 |
|---|---|---|---|
| FNE/DLL 入口 | `EasyFne.def` 只导出固定名字 `GetNewInf`；`EasyFne.cpp:227-230` 返回静态 `LibInfo` 地址 | `PLIB_INFO` 和其指向的静态表是借用视图，宿主不得释放 | L0 ABI 契约、L1 ABI 支持库 |
| 动态命令表 | `LibInfo.m_pBeginCmdInfo=Commands`、`m_pCmdsFunc=ExecuteCommand`，另有 `m_pfnNotify=ELIB_MessageNotify` | 命令元数据、函数指针和名称数组由模块静态持有；宿主按索引消费，不是运行时注册对象 | L1 注册适配器；L2 负责加载/卸载状态 |
| 动态加载 | 工程的 `fne_debug|Win32`/`fne_release|Win32` 是 `DynamicLibrary`，目标扩展名 `.fne`，模块定义文件为 `EasyFne.def` | Windows 宿主装载模块后取 `GetNewInf`；仓库没有 `LoadLibrary`/`GetProcAddress` 调用方，装载动作属于宿主 | L2 运行核心，不放在网关 |
| 静态加载 | `static_lib_debug|Win32`、`static_lib_release|Win32` 设置 `ConfigurationType=StaticLibrary`；Win32 静态调试配置显式定义 `__E_STATIC_LIB`，使 `LibInfo`、`Commands`、`ExecuteCommand` 等动态元数据段被预处理排除 | 静态库没有本项目自己的 `GetNewInf` 注册路径，依赖易语言静态编译约定和通知握手 | L0 ABI 兼容层；L2 负责静态依赖解析/生命周期 |
| 静态命名 | `elib/lib2.h:12-42` 提供 `__LIB2_DEFFUNNAME`、`DEF_EXECUTE_CMD`、`DEF_CMD`，默认前缀为 `console`，用于避免静态库符号冲突 | 这是链接期符号命名，不是能力注册表；跨库调用必须保持前缀、调用约定和声明一致 | L1 ABI 支持库 |

源码有两个必须标弱的配置问题：一是多个动态配置引用 `Elib_fne.def`，仓库实际只发现 `EasyFne.def`；二是 `static_lib_debug|x64`、`static_lib_release|x64` 的 `ConfigurationType` 是 `DynamicLibrary`，且未定义 `__E_STATIC_LIB`，不能按名称当作已验证的 x64 静态库。另有 `EasyFne.h:9` 直接包含 `elib/fnshare.cpp`，而 `EasyFne.vcxproj:425` 又把 `elib\\fnshare.cpp` 单独编译，可能造成重复定义；必须在 Windows 工具链实测，不能以源码意图替代链接结果。

静态通知握手也没有完全落地：`EasyFne.cpp:168-178` 在 `__E_STATIC_LIB` 下跳过 `NL_GET_CMD_FUNC_NAMES`、`NL_GET_NOTIFY_LIB_FUNC_NAME`、`NL_GET_DEPENDENT_LIBS` 的专用分支，直接进入 `ProcessNotifyLib`；后者 `fnshare.cpp:41-54` 对这些消息只有空分支。因此“头文件要求静态库处理”是 ABI 规范线索，不是本仓库已经实现的静态注册事实。

### 11.2 命令注册与实际执行的平行数组契约

动态模式下注册不是调用 `注册()` 函数，而是四份按同一索引排列的静态数据：

```text
Commands[0..3]       -> CMD_INFO（中文名/英文名/返回类型/参数表）
ExecuteCommand[0..3]  -> AddFunc/SubFunc/MulFunc/DivFunc
CommandNames[0..3]    -> "AddFunc"/"SubFunc"/"MulFunc"/"DivFunc"
LibInfo               -> 三者数量、首地址、ELIB_MessageNotify
```

`EasyFne.cpp:101-161` 证明当前顺序是加、减、乘、除；每个 `CMD_INFO` 声明两个 `SDT_INT` 参数和一个 `SDT_INT` 返回值，`ARG_INFO` 与实现函数没有独立的运行时校验器。`lib2.h:1291-1303` 规定 `m_nCmdCount`、`m_pBeginCmdInfo`、`m_pCmdsFunc` 和通知函数的 ABI 位置，`PFN_EXECUTE_CMD` 固定为 `void(PMDATA_INF, INT, PMDATA_INF)` 且要求 CDECL（`lib2.h:1234-1239`）。

因此命令注册的真实契约是“元数据索引 = 函数表索引 = 名称索引”，任何一表插入/排序而不同步都会把命令描述绑定到错误实现。当前四个实现只在 `iArgCount == 2` 时写 `pRetData->m_int`（`EasyFne.cpp:63-96`），不返回统一错误码，也不保证失败时初始化返回值。`DivFunc` 检查的是 `pArgInf[0].m_int != 0`，实际除数却是 `pArgInf[1].m_int`；这是可导致除零异常的源码级缺陷线索，不是已验证的运行结果。

### 11.3 内存、数据指针与“句柄”边界

- **宿主借用数据**：`MDATA_INF` 的联合体同时表达值、复合数据/数组指针和传入变量地址（`lib2.h:780-824`）。文本、字节集、数组和复合对象的指针来自易语言运行时；头文件明确要求文本/字节集输入只读，写回变量前先释放旧值。EasyFne 的四个整数命令没有创建这些对象。
- **运行时分配器**：`NRS_MALLOC/NRS_MFREE/NRS_MREALLOC`（`lib2.h:1099-1112`）是跨 ABI 内存入口。`fnshare.h:25-39` 的 `ealloc` 通过 `NotifySys` 申请并清零，`efree` 通过 `NotifySys` 释放；`CloneTextData`、`CloneTextDataW`、`CloneBinData`、`GetBinData`、`allocArray` 都返回由宿主分配器产生的内存，注释要求调用方最终 `efree`（`fnshare.h:58-169`）。
- **所有权缺口**：`ealloc` 不检查 `NotifySys(NRS_MALLOC,...)` 返回的空指针就 `memset`；`CloneBinData` 不检查非空 `pData`；长度为负、整数溢出、损坏数组头或重复 `efree` 均无本地保护。源码没有句柄表、引用计数、所有者/项目绑定、过期标记或 double-free 检测。
- **句柄只是 ABI 类型**：`mtypes.h:52-59` 将 `HGLOBAL`、`HANDLE`、`HWND` 等定义为 `DWORD`（而 `HINSTANCE` 为指针）；`lib2.h` 还描述 `HBITMAP`/`HGLOBAL` 和组件句柄的通知操作，但本工程没有调用这些操作，也没有创建/销毁句柄。不能把这些 typedef 误读为 EasyFne 的内存句柄管理实现。
- **平台责任**：支持库适配层只负责把宿主分配器封装成可审计的借用/新建/释放契约；句柄生命周期、释放去重、崩溃回收和位宽检查应归运行核心。若跨进程，不能把 `MDATA_INF` 内的裸指针或 `DWORD` 句柄直接穿过 IPC，必须复制成受限消息并由拥有者释放。

### 11.4 宿主通知与库生命周期

```text
宿主载入模块/登记静态库
  → 调用 ELIB_MessageNotify(NL_SYS_NOTIFY_FUNCTION, PFN_NOTIFY_SYS, 0)
  → ProcessNotifyLib 保存 s_pfnNotifySys
  → 首次通过 NotifySys(NRS_GET_PRG_TYPE) 缓存调试/发布类型
  → 宿主按 LibInfo/命令索引调用命令
  → 运行中由 NotifySys 申请/释放宿主内存或发运行时通知
  → NL_FREE_LIB_DATA / NL_UNLOAD_FROM_IDE
  → 模块卸载或进程结束
```

`fnshare.cpp:7-35` 只有三个进程内静态状态：系统通知回调、用户通知回调、调试版本值；后续 `NL_SYS_NOTIFY_FUNCTION` 会覆盖旧系统回调，这符合头文件“可能多次通知，后值覆盖前值”的约定。`SetUserSysNotify` 保存用户回调并返回 `ProcessNotifyLib`（`fnshare.cpp:67-71`），`ProcessNotifyLib` 最后会把所有消息转给用户回调，用户返回值覆盖本地结果（`fnshare.cpp:55-64`）。这些状态没有锁、代际号或卸载屏障，不能安全推导出并发/热卸载能力。

| 生命周期事件 | 当前实现 | 释放/失败责任 |
|---|---|---|
| 绑定宿主回调 | 保存 `PFN_NOTIFY_SYS`，首次查询 `NRS_GET_PRG_TYPE` | 当前不检查回调为空、失败码或线程安全；L2 应登记宿主会话与回调代际 |
| 普通通知 | 已知消息返回 `NR_OK`，未知消息先为 `NR_ERR`，再可能被用户回调覆盖 | 调用方必须保存原始消息、返回值和回调来源；不能把用户回调覆盖视为成功证明 |
| `NL_FREE_LIB_DATA` | `ProcessNotifyLib` 空分支，项目无库私有数据可释放 | 当前无释放动作；平台应把它作为“停止接收新调用→排空→释放句柄/回调”的阶段，不应只调用空函数 |
| `NL_UNLOAD_FROM_IDE` | 未在 `ELIB_MessageNotify` 特判，落到 `ProcessNotifyLib` 默认 `NR_ERR` | 卸载通知没有显式确认/延迟释放状态；`NR_DELAY_FREE` 未使用，需宿主实测 |
| `DllMain(DLL_PROCESS_DETACH)` | `main.cpp:8-16` 四类通知均空处理，始终返回 `TRUE` | 没有清空回调、释放缓存或阻止并发调用；异常/强杀时不能依赖 DllMain 补偿 |

### 11.5 失败、崩溃与释放矩阵

| 场景 | 源码可确认行为 | 风险等级/结论 |
|---|---|---|
| 参数个数不是 2 | 四个命令直接返回，不写 `pRetData` | 高：返回值可能保留旧值/未初始化；没有 `INVALID_ARGUMENT` 契约 |
| `pRetData`、`pArgInf` 为空 | 命令实现无空指针检查 | 高：宿主错误输入可直接访问冲突 |
| 除数为 0 | `DivFunc` 检查错误的第一个参数，可能仍执行第二个参数为 0 的整数除法 | 高：Windows 运行时异常/宿主进程崩溃路径未隔离 |
| 内存申请失败 | `ealloc` 对空指针立即 `memset` | 高：失败没有转成可重试错误，可能在支持库内崩溃 |
| 无效/损坏文本、字节集、数组 | 辅助函数只做极少空值/零长度判断，未校验布局、长度上限和溢出 | 高：越界读写/崩溃；应在 L1/L2 边界拒绝 |
| 系统通知回调缺失或失败 | `NotifySys` 无回调时返回 0；`ProcessNotifyLib` 不检查 `NRS_GET_PRG_TYPE` 结果 | 中高：后续分配/运行时通知可能使用失效宿主；状态仍被视为已初始化 |
| 未知通知 | 默认 `NR_ERR`，但用户回调存在时其返回值会覆盖 | 中：审计必须保留“本地拒绝”和“用户覆盖”两层结果 |
| `NL_FREE_LIB_DATA`/卸载 | 无私有释放逻辑；回调和静态状态仍可保留 | 高：回调悬挂、卸载期间调用、跨代指针风险 |
| 重复释放/跨模块释放 | 没有本地表或所有权校验，`efree` 原样转发 `NRS_MFREE` | 高：由宿主分配器决定后果，未验证 double-free 语义 |
| 并发通知/命令 | 三个 `static` 状态无锁，命令与回调也无同步 | 中高：数据竞争与回调代际错配未验证 |
| DLL 崩溃/强杀 | `DllMain` 不做恢复；工程未提供守护、重启、崩溃报告或转储 | 高：若在宿主进程内加载，故障边界就是易语言宿主进程 |
| ABI 位宽不匹配 | `ELIB_MessageNotify` 把 `CommandNames`、`LIBARAYNAME` 指针强转为 `INT`；通知参数是 `DWORD`；`mtypes.h` 还把句柄定义为 `DWORD` | 高：x64 配置存在指针截断/句柄失真风险；本机 macOS 无法验证 Windows ABI |
| C++ 异常 | `fne_debug|Win32` 设置 `ExceptionHandling=false`，命令无异常边界 | 高：不能把异常传过 C ABI；应由受管进程兜底 |

### 11.6 L0-L4 底座映射与裁决

本项目源码没有 L0-L4 命名，以下是平台接入时的五层解释，**不是把 EasyFne 现有层伪装成平台实现**：

| 层级 | 归属 | 应吸收的源码事实 | 不应吸收/当前缺口 | 裁决 |
|---|---|---|---|---|
| L0 | 宿主/OS/原生 ABI | `GetNewInf`、`LIB_INFO` 固定布局，`PFN_EXECUTE_CMD`/`PFN_NOTIFY_*` 调用约定，`MDATA_INF`/`#pragma pack(1)`，Win32 DLL/静态库和位宽要求 | 不在 L0 直接执行业务命令，不把裸指针当通用消息 | **吸收为外部 ABI 契约；x64 待核** |
| L1 | ABI 支持库 | `lib2.h` 类型/通知常量，`fnshare` 的回调转发、宿主分配器封装、FNE 元数据/命令注册适配 | 当前没有统一错误对象、所有权声明、句柄注册表、回调注销和双向 ABI 版本检查 | **升级现有 ABI 支持库候选；只保留薄适配层** |
| L2 | 运行核心 | 应集中管理动态/静态加载选择、版本/能力注册、调用前参数校验、句柄/内存所有权、排空、超时、释放证据、失败归因 | EasyFne 只有模块静态变量和空释放分支，没有装配、监督、恢复、租约或幂等释放 | **建立唯一运行核心 owner；不复制 EasyFne 的旁路状态** |
| L3 | 受管进程 | 将不可信 FNE/DLL 放入独立进程，IPC 中只传复制后的命令参数/结果；子进程崩溃后由核心回收并按策略重启/隔离 | 仓库没有子进程、守护、重启、崩溃恢复；裸 `MDATA_INF`/回调/句柄不能跨进程 | **新建受管进程边界；原生库默认不直接进网关进程** |
| L4 | 统一网关 | 网关只接收稳定能力/命令请求，做鉴权、限流、超时、请求证据和统一错误，再调用 L2/L3 | EasyFne 没有 HTTP/RPC/API 网关；`GetNewInf`、`ELIB_MessageNotify` 不是外部网关接口 | **网关只做适配调用，不暴露 FNE 指针/函数名；待平台装配** |

单链路应固定为：`L4 网关请求 → L2 运行核心契约/资源监督 → L3 受管 FNE/DLL（或 L1 进程内 ABI 适配）→ L0 宿主 ABI → 结果复制/错误归一化/释放证据 → L4 响应`。只有确认 ABI 稳定、位宽一致、异常边界和卸载语义后，才允许 L2 选择进程内 L1；否则默认 L3 隔离。`EasyFne.cpp` 的四个算术实现可作为 ABI 夹具或适配层验证样本，不能直接成为网关、运行核心或句柄中心。

### 11.7 第三轮验证等级与验收缺口

| 等级 | 必须验证的事实 | 当前状态 |
|---|---|---|
| L0 静态 ABI | `LIB_INFO` 字段顺序、`MDATA_INF` 对齐/指针宽度、`GetNewInf` 导出、命令三表索引一致 | 已完成静态核对；无 Windows 编译器实测 |
| L1 Win32 构建 | `fne_debug/release|Win32`、`static_lib_debug/release|Win32` 编译/链接；确认 `Elib_fne.def` 引用和 `fnshare.cpp` 重复定义 | 未执行，必须在 Windows/VS 验证 |
| L2 宿主握手 | 真实宿主发送 `NL_SYS_NOTIFY_FUNCTION`、命令名查询、通知返回值、内存申请/释放和卸载顺序 | 未执行；没有测试宿主 |
| L3 故障隔离 | 错参数、零除、空回调、分配失败、强杀/崩溃、重复释放、卸载中调用；验证宿主不被拖垮且子进程可回收 | 未执行；源码未提供隔离能力 |
| L4 网关链路 | 统一请求 → 授权/超时/错误 → 受管调用 → 结果复制 → 释放/证据读回 | EasyFne 仓库不存在此层；只能作为平台装配验收项 |

本轮结论只能写成“静态证据充分、运行验证缺失”：成功注册链和失败/释放缺口均来自源码；没有把未构建、未加载、未崩溃注入的场景记为通过。

## 12. 证据路径

- 工程入口与实现：`EasyFne.cpp:63-230`、`main.cpp:1-16`。
- 项目接口与库身份：`EasyFne.h:1-40`。
- DLL 导出：`EasyFne.def:1-3`。
- 工程配置与源码清单：`EasyFne.vcxproj:1-443`、`EasyFne.sln`。
- 通知/内存辅助：`elib/fnshare.cpp:1-71`、`elib/fnshare.h:1-378`。
- ABI 与数据模型：`elib/lib2.h:1-1598`。
- IDE 协议：`elib/PublicIDEFunctions.h`。
- 核心库常量：`elib/krnllib.h`；语言版本：`elib/lang.h`；基础类型：`elib/mtypes.h:1-59`。
- 当前版本：Git `d0d6cbba761bbed13d13f7e79199a5837d387366`，本地 `HEAD` 与远程 `origin/HEAD` 一致。
