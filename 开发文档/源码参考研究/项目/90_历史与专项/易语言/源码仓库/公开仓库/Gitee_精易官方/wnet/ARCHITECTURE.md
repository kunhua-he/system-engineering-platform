# wnet 架构与实现建档

## 1. 项目定位

`wnet` 是精易官方 Gitee 仓库中的易语言 Windows 支持库源码模板，目标是向易语言 IDE/编译器注册一个名为“局域网操作支持库”的 Windows-only 库，并提供“局域网操作（WNet）”对象及其成员命令、资源类型枚举。

本仓库当前提交是 2022-12-19 的“初始化仓库”。源码已经完成易语言支持库的**元数据、命令表、数据类型表、DLL 入口和通知协议骨架**，但核心局域网操作命令的函数体只有参数读取，没有 Windows Networking API 调用、返回值填充或错误处理。因此不能把它描述为已完成的局域网功能实现。

### 已实现 / 仅声明 / 未验证

| 范围 | 结论 | 证据 |
|---|---|---|
| 支持库注册入口 | 已实现源码定义：`GetNewInf()` 返回静态 `LIB_INFO`；DLL 通知函数已接入 | `wnet_dllMain.cpp:31-99` |
| 命令和参数元数据 | 已实现源码表：12 个命令、25 个参数元数据项 | `wnet_cmd_typedef.h:12-24`、`wnet_cmdInfo.cpp:5-71` |
| 自定义数据类型元数据 | 已实现源码表：`局域网操作` 对象、`资源类型` 枚举 | `wnet_dtType.cpp:4-51` |
| 命令符号与实现声明 | 已实现：宏展开生成声明、函数指针表和名称表 | `include_wnet_header.h:22-24`、`wnet_dllMain.cpp:42-99` |
| 12 个命令的业务行为 | 仅声明/骨架：函数只把 `pArgInf` 转为局部变量，未写 `pRetData`，未调用 WNet API | `wnet_cmdDef.cpp:6-129` |
| 易语言宿主通知转发 | 已实现基础转发：保存系统通知函数，调试版本查询，并调用用户回调 | `elib/fnshare.cpp:11-70` |
| Windows 编译、DLL 加载、易语言 IDE 集成 | 未验证；当前主机为 macOS，仓库没有测试、CI 或构建产物 | 工程文件与 Git 树现场检查 |

## 2. 总体流程

```text
易语言 IDE / 编译器
        │ 载入 .fne，查找固定导出 GetNewInf
        ▼
wnet.dll / wnet.fne
        │ GetNewInf()
        ▼
LIB_INFO（版本、GUID、平台、命令表、数据类型表、通知回调）
        │
        ├── g_DataType_wnet_global_var
        │       ├── 局域网操作（WNet 对象）
        │       │       └── 12 个对象成员命令索引
        │       └── 资源类型（枚举：全部/共享文件夹/共享打印机）
        │
        ├── g_cmdInfo_wnet_global_var
        │       └── WNET_DEF 宏生成的 12 条命令元数据
        │
        └── g_cmdInfo_wnet_global_var_fun
                └── 12 个 wnet_* 命令函数
                        │ 当前仅读取参数
                        └── 未实现 Windows WNet 操作、返回值和错误写回

易语言系统通知
        ▼
wnet_ProcessNotifyLib_wnet
        ├── NL_GET_CMD_FUNC_NAMES / NL_GET_NOTIFY_LIB_FUNC_NAME / NL_GET_DEPENDENT_LIBS
        ├── NL_SYS_NOTIFY_FUNCTION → ProcessNotifyLib → NotifySys
        └── 其他已识别通知当前返回默认成功或空处理
```

## 3. 工程与目录地图

仓库根目录只有一个 Visual Studio Solution，包含动态库工程和静态库工程；现场 Git 树共 23 个受版本控制文件，未发现 README、测试目录、CI 配置、发布脚本或历史细探文档。

```text
wnet/
├── wnet.sln                         # wnet + wnet_static，Debug/Release，Win32/x64
├── wnet.vcxproj                     # 动态库工程，目标扩展主要为 .fne
├── wnet.vcxproj.filters             # VS 文件筛选器
├── wnet.vcxproj.user                # 空用户工程设置
├── wnet_static/
│   ├── wnet_static.vcxproj          # 静态库工程，复用根目录源文件
│   ├── wnet_static.vcxproj.filters
│   └── wnet_static.vcxproj.user
├── Source_wnet.def                  # LIBRARY + EXPORTS + GetNewInf
├── include_wnet_header.h            # 公共包含、全局表 extern、命令声明
├── wnet_cmd_typedef.h               # WNET_DEF 命令单一宏清单
├── wnet_cmdDef.cpp                  # 12 个命令入口骨架
├── wnet_cmdInfo.cpp                 # ARG_INFO、CMD_INFO 元数据表
├── wnet_dtType.cpp                  # 数据类型/枚举元数据表
├── wnet_const.cpp                   # 空常量表（数量为 0）
├── wnet_dllMain.cpp                 # DllMain、LIB_INFO、GetNewInf、通知入口
└── elib/
    ├── lib2.h                       # 易语言支持库 SDK 核心类型、宏、LIB_INFO/CMD_INFO
    ├── mtypes.h                     # 基础类型兼容定义和句柄/结构体类型
    ├── krnllib.h                    # 系统核心支持库常量与版本信息
    ├── lang.h                       # 语言版本：GBK
    ├── fnshare.h / fnshare.cpp      # 宿主通知、易语言内存和通用辅助接口
    ├── untshare.h                   # 通用组件/属性辅助模板（当前命令未使用）
    └── PublicIDEFunctions.h         # IDE 操作功能编号及参数结构（当前无实现接线）
```

### 工程配置

- `wnet.sln` 定义 `Debug|x64`、`Debug|x86`、`Release|x64`、`Release|x86`；x86 在项目配置中映射为 `Win32`（`wnet.sln:10-32`）。
- `wnet.vcxproj` 的四个配置类型均为 `DynamicLibrary`，使用 `v141` 工具集和 Windows SDK `10.0.15063.0`（`wnet.vcxproj:43-75`）。
- Win32 Debug/Release 配置定义 `__E_FNENAME=wnet`、`WIN32`，并在链接器中指定 `Source_wnet.def`；Win32 目标扩展为 `.fne`（`wnet.vcxproj:95-152`）。
- x64 动态配置没有 `__E_FNENAME=wnet`，也没有 `ModuleDefinitionFile`；由于 `elib/lib2.h` 要求先定义 `__E_FNENAME`（`elib/lib2.h:11-25`），且 `GetNewInf` 依赖 `.def` 导出，这两套配置需要在 Windows/Visual Studio 上重新确认，当前不能宣称可构建或可加载。
- `wnet_static/wnet_static.vcxproj` 的 Win32 配置定义 `__E_STATIC_LIB;__E_FNENAME=wnet`，类型为 `StaticLibrary`；其 x64 配置缺少这两个关键宏（`wnet_static/wnet_static.vcxproj:49-70,94-115,132-155`），同样属于未验证且疑似不完整配置。
- 静态工程复用根目录的 `elib/fnshare.cpp`、5 个 `wnet_*.cpp` 源文件及全部头文件（`wnet_static/wnet_static.vcxproj:21-42`）。

## 4. 分层与模块职责

### 4.1 易语言 SDK 适配层：`elib/`

`elib/lib2.h` 定义了支持库命令函数签名 `PFN_EXECUTE_CMD`、`CMD_INFO`、`ARG_INFO`、`LIB_INFO`、操作系统标志、系统数据类型以及静态库名称改写宏。支持库通过 `__E_FNENAME=wnet` 将函数名拼成类似 `wnet_GetSharedRes_2_wnet` 的唯一符号（`elib/lib2.h:11-31`、`wnet_cmd_typedef.h:3-10`）。

`elib/mtypes.h` 提供 Windows/易语言 SDK 所需基础类型、数据类型、句柄兼容别名和宏；`elib/krnllib.h` 提供系统核心支持库的 GUID、名称和版本常量；`elib/lang.h` 固定编译语言为 GBK（`__GBK_LANG_VER`）。这些文件属于 SDK 兼容基础，不是 wnet 的局域网业务逻辑。

`elib/fnshare.cpp` 保存宿主回调 `s_pfnNotifySys` 和用户回调 `s_pfnuserNotifySys`。`ProcessNotifyLib()` 处理系统通知，在 `NL_SYS_NOTIFY_FUNCTION` 中保存系统函数指针，并通过 `NRS_GET_PRG_TYPE` 初始化调试/运行版本；随后把通知转发给用户回调。`NotifySys()` 仅在宿主回调非空时转发，否则返回 0（`elib/fnshare.cpp:7-70`）。

`elib/PublicIDEFunctions.h` 是较大的 IDE 功能号和参数结构定义集合，描述编辑器移动、编辑、文件、调试、资源等功能；当前工程没有源文件直接包含它，也没有 `NL_*`/`FN_*` 业务处理实现。`elib/untshare.h` 提供通用属性、窗口样式、日期和占位辅助代码，当前 wnet 命令实现没有调用它。

### 4.2 元数据与命令清单层

`wnet_cmd_typedef.h` 的 `WNET_DEF(_MAKE)` 是命令单一清单，共 12 项：构造函数、析构函数和 10 个用户可见对象成员命令。每一项同时携带索引、中文名、英文名、说明、Windows 平台标志、返回类型、用户等级、参数数目和参数元数据起点（`wnet_cmd_typedef.h:12-24`）。

同一个宏清单被多次展开：

1. `include_wnet_header.h:22-24` 展开为 12 个命令函数声明；
2. `wnet_cmdInfo.cpp:61-71` 通过 `WNET_DEF_CMDINFO` 展开为 `CMD_INFO` 元数据数组和计数；
3. `wnet_dllMain.cpp:42-45` 通过 `WNET_DEF_CMD_PTR` 展开为 12 个函数指针；
4. `wnet_dllMain.cpp:95-99` 通过 `WNET_DEF_CMDNAME_STR` 展开为静态命令符号名称数组。

这保证命令顺序在声明、元数据、函数指针和名称表之间保持一致；但它不保证命令函数内部已经实现。

`wnet_cmdInfo.cpp` 的参数表共有 25 项（索引 `000` 到 `024`），覆盖共享资源类型、资源/主机名输出数组、路径、设备名、用户名、密码、提示/自动重连开关、父窗口句柄、UNC 路径输出参数等（`wnet_cmdInfo.cpp:5-57`）。参数状态使用 SDK 的 `AS_*` 标志表达默认值、可空值、变量引用和数组引用约束。

### 4.3 数据类型层：`wnet_dtType.cpp`

- `局域网操作` / `WNet`：Windows 数据类型，命令索引数组包含 0 到 11 共 12 个命令；隐藏的 `this` 成员只有元数据占位（`wnet_dtType.cpp:4-19,36-41`）。
- `资源类型` / `ResType`：Windows 枚举，成员为 `全部=0`、`共享文件夹=1`、`共享打印机=2`（`wnet_dtType.cpp:20-29,43-49`）。
- 导出的数据类型数量由数组计算，实际为 2（`wnet_dtType.cpp:51`）。

### 4.4 命令执行层：`wnet_cmdDef.cpp`

源码提供 12 个 `WNET_EXTERN_C` 命令入口，统一签名为 `PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf`。当前每个函数的行为仅包括：按元数据预期读取 `pArgInf[1..n]` 到局部变量。例如：

- `取共享资源` 读取复合类型和两个数组指针；
- `取所有主机名` 读取主机名数组指针；
- `映射资源` 读取 4 个文本和 2 个逻辑值；
- `取资源路径` 读取输入路径和 3 个文本输出指针。

这些函数均没有调用 `WNetOpenEnum`、`WNetAddConnection`、`WNetCancelConnection`、`WNetGetConnection`、`WNetGetUniversalName`、`WNetGetResourceInformation` 或其他 Windows Networking API；也没有给 `pRetData` 写入返回类型/返回值，没有写数组输出，没有将 Win32 错误转换成易语言文本。因此“命令说明所描述的功能”是**仅声明/未实现**，不能从命令名或注释推断为可用功能（`wnet_cmdDef.cpp:6-129`）。

### 4.5 DLL 宿主生命周期层：`wnet_dllMain.cpp`

`DllMain()` 对四种 DLL 生命周期通知只做空分支并返回 `TRUE`，无初始化、线程状态或资源释放动作（`wnet_dllMain.cpp:7-28`）。

静态 `g_LibInfo_wnet_global_var` 注册：

- 库格式 `LIB_FORMAT_VER`；
- GUID `1F356293DD5846469639B8145EBEC9FE`；
- 库版本 `3.0.0`；
- 要求易语言系统 `3.8`、系统核心支持库 `3.8`；
- 名称“局域网操作支持库”；
- GBK 语言；
- Windows-only；
- 作者/联系信息；
- 2 个自定义数据类型；
- 12 个命令及其函数指针；
- 无常量、无 AddIn、无 SuperTemplate、无依赖文件列表；
- `m_pfnNotify` 指向 `wnet_ProcessNotifyLib_wnet`。

`GetNewInf()` 返回该结构地址，是动态库的固定入口（`wnet_dllMain.cpp:31-99`）。`Source_wnet.def` 只导出 `GetNewInf`（`Source_wnet.def:1-4`）。

通知函数当前明确实现/声明的分支：

| 通知 | 当前行为 |
|---|---|
| `NL_GET_CMD_FUNC_NAMES` | 返回静态命令名数组地址 |
| `NL_GET_NOTIFY_LIB_FUNC_NAME` | 返回字符串 `wnet_ProcessNotifyLib_wnet` |
| `NL_GET_DEPENDENT_LIBS` | 返回空依赖列表 `"\\0\\0"` |
| `NL_SYS_NOTIFY_FUNCTION` | 调用 `ProcessNotifyLib`，把宿主通知函数交给 `elib` 层 |
| `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NR_DELAY_FREE`、`NL_IDE_READY`、`NL_RIGHT_POPUP_MENU_SHOW`、`NL_ADD_NEW_ELEMENT` | 空处理，最后返回默认 `NR_OK` |
| 未知通知 | 返回 `NR_ERR` |

证据为 `wnet_dllMain.cpp:101-180`。其中“空处理后返回成功”是当前代码事实，不代表资源释放、IDE 插件或新元素处理已经实现。

## 5. 数据模型与接口契约

### 5.1 支持库注册模型

```text
LIB_INFO
├── m_szGuid = 1F356293DD5846469639B8145EBEC9FE
├── m_nMajorVersion/m_nMinorVersion/m_nBuildNumber = 3/0/0
├── m_nRqSysMajorVer/m_nRqSysMinorVer = 3/8
├── m_nRqSysKrnlLibMajorVer/m_nRqSysKrnlLibMinorVer = 3/8
├── m_dwState = _LIB_OS(__OS_WIN)
├── m_nDataTypeCount = 2 → g_DataType_wnet_global_var
├── m_nCmdCount = 12 → g_cmdInfo_wnet_global_var
├── m_pCmdsFunc → g_cmdInfo_wnet_global_var_fun
├── m_pfnNotify → wnet_ProcessNotifyLib_wnet
└── m_nLibConstCount = 0 → g_ConstInfo_wnet_global_var
```

该模型来自 `elib/lib2.h` 中 SDK 结构定义和 `wnet_dllMain.cpp:31-87` 的实际初始化。`LIB_INFO` 中的指针均指向静态数组，当前没有动态注册表、配置文件、数据库或外部服务。

### 5.2 命令接口

| 索引 | 易语言命令 | 英文符号 | 返回类型 | 参数数 | 当前实现状态 |
|---:|---|---|---|---:|---|
| 0 | 构造函数 | `Constructor` | 空 | 0 | 空函数，仅声明 |
| 1 | 析构函数 | `Desstructor` | 空 | 0 | 空函数，仅声明 |
| 2 | 取共享资源 | `GetSharedRes` | `SDT_INT` | 3 | 只读取参数，未执行 |
| 3 | 取所有主机名 | `GetServerName` | `SDT_INT` | 1 | 只读取参数，未执行 |
| 4 | 取连接速度 | `GetConnectionSpeed` | `SDT_INT64` | 1 | 只读取参数，未执行 |
| 5 | 映射资源 | `MapRes` | `SDT_TEXT` | 6 | 只读取参数，未执行 |
| 6 | 断开映射 | `CancelResMap` | `SDT_BOOL` | 3 | 只读取参数，未执行 |
| 7 | 打开映射对话框 | `OpenMapDlg` | `SDT_TEXT` | 5 | 只读取参数，未执行 |
| 8 | 打开中断对话框 | `OpenCancelMapDlg` | 空 | 1 | 只读取参数，未执行 |
| 9 | 取对应资源 | `GetResPath` | `SDT_TEXT` | 1 | 只读取参数，未执行 |
| 10 | 取资源路径 | `GetUNCPath` | `SDT_BOOL` | 4 | 只读取参数，未执行 |
| 11 | 取错误信息 | `GetLastError` | `SDT_TEXT` | 0 | 空函数，仅声明 |

命令的参数默认值、可空性、变量/数组引用约束以 `wnet_cmdInfo.cpp:5-57` 为准；命令名称、返回类型和参数数以 `wnet_cmd_typedef.h:12-24` 为准。上表没有把注释中的预期返回值写成已实现行为。

### 5.3 错误与内存模型

- SDK 级通知函数使用 `NR_OK=0` / `NR_ERR=-1`（`elib/lib2.h`）。
- 运行时参数按 `MDATA_INF` 访问；数组、文本和复合数据的指针形态由 `pArgInf` 字段决定（`wnet_cmdDef.cpp:23-123`）。
- `elib/fnshare.h` 提供 `ealloc`、`efree`、`CloneTextData`、`CloneBinData` 等易语言内存辅助，但当前命令函数没有使用这些接口，也没有内存释放路径（`elib/fnshare.h` 相关内联函数）。
- `GetLastError` 命令函数为空，当前没有把 Win32 `GetLastError()` 转成易语言文本的实现证据。`wnet_cmdDef.cpp` 中出现的是命令名/注释，不是错误调用。

## 6. 依赖边界

### 编译依赖

```text
wnet_*.cpp / include_wnet_header.h
        ├── elib/lib2.h
        │     ├── Windows SDK: windows.h
        │     ├── stdio.h / math.h
        │     └── 易语言 SDK 结构：MDATA_INF、CMD_INFO、LIB_INFO、通知常量
        ├── elib/lang.h
        ├── elib/krnllib.h
        └── wnet_cmd_typedef.h
```

- 目标平台硬编码为 Windows：命令元数据使用 `_CMD_OS(__OS_WIN)`，数据类型使用 `_DT_OS(__OS_WIN)`，工程依赖 `windows.h` 和 Visual Studio C++ 工具链。
- 动态库链接通过 `Source_wnet.def` 导出 `GetNewInf`；静态库通过 `__E_STATIC_LIB` 和名称改写宏复用同一套源文件。
- `g_LibInfo` 声明“无依赖文件列表”，但这只是易语言支持库元数据中的 `m_szzDependFiles=NULL`；编译时仍依赖 Windows SDK 与易语言 SDK 头文件。
- 当前源码没有第三方包管理文件、源码内网络客户端、数据库、文件持久化、线程池或配置系统。

## 7. 构建、测试与验证状态

### 仓库内验证资产

现场扫描到：没有 `README`、`test/`、`tests/`、测试源文件、CI 工作流、构建脚本、发布脚本或已编译 `.fne/.dll/.lib` 产物。Solution 与两个 `.vcxproj` 是唯一构建描述。

### 本轮实际验证

- 已人工读取根目录源文件、`elib` SDK 头/实现、Solution、动态/静态工程、过滤器、`.def` 和 Git 元数据。
- 已确认本地 `master` 与 `origin/master` 指向同一提交；远程 `HEAD` 为 `master`，且远程最新提交与本地一致。
- 未在 macOS 上执行 Visual Studio/MSBuild；未执行 DLL 加载、`GetNewInf` 调用、易语言 IDE 集成或局域网命令端到端测试。
- 因此“源码可解析/元数据链路静态闭合”可以确认；“Windows 构建通过、导出正确、命令可运行”均为未验证。

如在 Windows 环境继续验证，建议至少覆盖：

1. Win32 Debug/Release 动态库构建，检查 `.fne` 生成和 `GetNewInf` 导出；
2. Win32 Debug/Release 静态库构建，检查名称改写后的 12 个命令符号；
3. x64 两个工程先修订/确认 `__E_FNENAME`、`__E_STATIC_LIB` 和 DLL `.def` 导出策略，再构建；
4. 用易语言 IDE 装载库，检查 `LIB_INFO`、2 个数据类型、12 个命令和参数默认值；
5. 仅在补齐 `wnet_cmdDef.cpp` 后，才测试共享资源枚举、主机名、映射/断开、UNC 解析、连接速度和错误信息。

## 8. Git 基线

| 项目 | 现场值 |
|---|---|
| 仓库 | `https://gitee.com/JYtechnology/wnet.git` |
| 分支 | `master` |
| 本地 HEAD | `c41f259a17c9d0085c61410b9d194c0d5b4d4800` |
| 远程 `origin/master` | `c41f259a17c9d0085c61410b9d194c0d5b4d4800` |
| 远程默认分支 | `master` |
| 提交时间 | 2022-12-19 16:57:48 +0800 |
| 提交作者/说明 | `精易科技` / `初始化仓库` |
| 工作树（建档前） | 干净 |
| 历史完整性 | 浅克隆（`git rev-parse --is-shallow-repository` 为 `true`），仅有初始化提交可供本地历史读取 |

本文件是本项目架构建档的唯一长期文档；后续细探应直接更新本文件，不另建平行架构事实源。

## 9. 证据路径索引

- 项目入口与注册：`wnet_dllMain.cpp:7-180`、`Source_wnet.def:1-4`
- 命令单一清单：`wnet_cmd_typedef.h:3-25`
- 命令函数声明与公共表 extern：`include_wnet_header.h:3-26`
- 命令元数据与参数：`wnet_cmdInfo.cpp:5-74`
- 命令骨架：`wnet_cmdDef.cpp:6-129`
- 数据类型：`wnet_dtType.cpp:4-56`
- 常量：`wnet_const.cpp:1-18`
- 宿主通知与内存辅助：`elib/fnshare.cpp`、`elib/fnshare.h`
- SDK 核心 ABI/结构/宏：`elib/lib2.h`
- 基础兼容类型：`elib/mtypes.h`
- 核心库版本常量：`elib/krnllib.h`
- 语言版本：`elib/lang.h`
- IDE 功能号：`elib/PublicIDEFunctions.h`
- 通用组件辅助：`elib/untshare.h`
- 动态工程：`wnet.vcxproj`、`wnet.vcxproj.filters`、`wnet.vcxproj.user`
- 静态工程：`wnet_static/wnet_static.vcxproj`、`wnet_static/wnet_static.vcxproj.filters`、`wnet_static/wnet_static.vcxproj.user`
- Solution：`wnet.sln`
- Git 基线：`.git/`，现场命令为 `git status --short --branch`、`git remote -v`、`git show-ref`、`git ls-remote --heads origin`、`git ls-remote --symref origin HEAD`
