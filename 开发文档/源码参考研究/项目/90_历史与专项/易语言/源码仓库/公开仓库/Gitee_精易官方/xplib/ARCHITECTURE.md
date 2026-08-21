# xplib 架构建档

> 首轮全量架构建档。本文是本项目当前唯一的架构事实入口；源码归档只读，后续细探应增量更新本文件，不在项目内建立平行架构结论。
>
> **证据边界：** 以下“已实现”仅指在当前提交源码中存在对应实现；“仅声明/元数据”指有接口、宏或登记信息但没有可执行业务逻辑；“未验证”指本机没有 Windows/MSVC/易语言运行环境，未实际编译、装载或调用。

## 1. 项目定位

`xplib` 是精易官方 Gitee 仓库中的一个易语言支持库（SDK/运行时插件）示例/初始实现，库名为“XP风格界面库”。它通过易语言支持库 ABI 提供一个全局命令“XP风格”，计划根据参数切换当前应用程序窗口组件的 XP 界面风格；当前源码只读取参数，没有执行任何风格切换，也没有设置返回值。

项目同时维护两种构建目标：

- `xplib`：Visual Studio C++ 动态库，Win32 配置目标扩展名为 `.fne`，通过 `Source_xplib.def` 导出 `GetNewInf`。
- `xplib_static`：静态库目标，复用上级目录同一组 `.cpp/.h`，依赖 `__E_STATIC_LIB` 分支去除动态库元数据并保留静态编译辅助符号。

当前仓库是 2022-12-19 的“初始化仓库”快照，实际功能完成度很低：支持库登记、命令描述、常量和通知框架已搭出；唯一命令的业务函数仍为空壳。

## 2. 总体流程图（按当前源码）

```text
易语言 IDE / 运行环境
        │
        │ 动态装载 .fne，按固定符号查找 GetNewInf
        ▼
┌──────────────────────────────────────┐
│ xplib_dllMain.cpp                     │
│ DllMain()（当前仅返回 TRUE）          │
│ GetNewInf()                           │
│ xplib_ProcessNotifyLib_xplib()       │
└───────────────┬──────────────────────┘
                │ 返回 LIB_INFO
                ├──────────────► 命令元数据：g_cmdInfo...
                │                 └─ XP风格 / 1 个参数
                ├──────────────► 命令实现指针：g_cmdInfo..._fun
                │                 └─ xplib_SetXP_0_xplib
                ├──────────────► 常量：g_ConstInfo...
                │                 └─ 无风格 / 蓝色 / 绿色 / 银色
                └──────────────► 自定义数据类型：空（count=0）

易语言程序调用“XP风格(风格类型)”
                │
                ▼
PFN_EXECUTE_CMD(pRetData, nArgCount, pArgInf)
                │
                ▼
xplib_SetXP_0_xplib()
                ├─ 读取 pArgInf[0].m_int 到 arg1
                └─ 当前无风格切换、无返回值写入（未完成）

系统通知 NL_SYS_NOTIFY_FUNCTION
                │
                ▼
xplib_ProcessNotifyLib_xplib()
                └─ ProcessNotifyLib() → 保存 PFN_NOTIFY_SYS
                                  └─ 首次通知时调用 NRS_GET_PRG_TYPE

用户回调（可选）
SetUserSysNotify(pfn)
                │
                ▼
ProcessNotifyLib()
                └─ 将通知转发给 s_pfnuserNotifySys（当前仅框架）
```

## 3. 真实目录与文件地图

当前 `HEAD` 共 23 个受 Git 管理文件；仓库根没有 README、测试目录、构建脚本、CI 配置或旧 `细探-*.md`/旧 `ARCHITECTURE.md`。目录结构如下：

```text
xplib/
├── ARCHITECTURE.md                 # 本次新增的唯一架构文档
├── Source_xplib.def                # 动态库 Win32 导出定义：GetNewInf
├── include_xplib_header.h          # 项目统一入口；引入 SDK 并声明全局登记数组
├── xplib.sln                       # VS 解决方案：xplib + xplib_static
├── xplib.vcxproj                   # 动态库工程
├── xplib.vcxproj.filters           # 动态库 VS 文件筛选器
├── xplib.vcxproj.user              # 本地 VS 用户属性（归档配置）
├── xplib_cmdDef.cpp                # 命令执行函数；当前只有一个空壳命令
├── xplib_cmdInfo.cpp               # 命令参数描述和 CMD_INFO 表
├── xplib_cmd_typedef.h             # XPLIB_DEF 单一命令清单及符号拼接宏
├── xplib_const.cpp                 # 4 个风格常量
├── xplib_dllMain.cpp               # DllMain、LIB_INFO、GetNewInf、通知分发、静态辅助命名
├── xplib_dtType.cpp                # 自定义数据类型表；当前为空
├── elib/                           # 易语言支持库 ABI/运行时兼容头与通知实现
│   ├── PublicIDEFunctions.h        # IDE 公共函数声明
│   ├── fnshare.cpp                 # 通知转发、调试版本、用户通知回调、运行时辅助
│   ├── fnshare.h                   # fnshare 接口、参数/表宏辅助
│   ├── krnllib.h                   # 系统核心支持库常量/类型编号
│   ├── lang.h                      # 语言版本常量（GBK=1）
│   ├── lib2.h                      # 支持库 ABI、数据类型、命令/库信息结构定义
│   ├── mtypes.h                    # Windows/基础 C 类型兼容定义
│   └── untshare.h                  # 窗口组件/单位相关辅助声明与宏
└── xplib_static/
    ├── xplib_static.vcxproj        # 静态库工程，引用上级源码
    ├── xplib_static.vcxproj.filters
    └── xplib_static.vcxproj.user
```

## 4. 构建工程与编译分支

### 4.1 解决方案层

`xplib.sln`（40 行）登记两个 C++ 项目，并声明 `Debug/Release × x86/x64` 四个解决方案配置。解决方案的 `x86` 映射到工程的 `Win32`，`x64` 映射到工程的 `x64`。

### 4.2 动态库 `xplib.vcxproj`

- `ConfigurationType=DynamicLibrary`；平台工具集为 `v141`；Windows SDK 目标为 `10.0.15063.0`；字符集为 Unicode。
- 编译输入是 `elib/fnshare.cpp`、五个根目录 `.cpp`（`xplib_cmdDef.cpp`、`xplib_const.cpp`、`xplib_dllMain.cpp`、`xplib_dtType.cpp`、`xplib_cmdInfo.cpp`）。
- Win32 Debug/Release 定义 `__E_FNENAME=xplib`、`XPLIB_EXPORTS` 等，并设置 `TargetExt=.fne`。
- Win32 Debug/Release 指定 `Source_xplib.def` 作为模块定义文件，因此源码中的 `GetNewInf` 可由该 `.def` 导出。
- x64 Debug/Release 没有 `__E_FNENAME=xplib`，没有 `.fne` 目标扩展设置，也没有 `ModuleDefinitionFile` 设置。源码是否能按预期形成可装载的 x64 支持库，当前仅能判定为**未验证且配置存在明显不一致**，不能按 Win32 结论外推。
- 没有额外第三方库、NuGet/vcpkg/子模块或自定义 include 目录；工程只引用仓库内 `elib` 和根目录文件及 Windows/编译器基础能力。

### 4.3 静态库 `xplib_static.vcxproj`

- `ConfigurationType=StaticLibrary`，源文件通过 `..\` 引用动态工程同一批源文件，避免第二份实现。
- Win32 Debug/Release 定义 `__E_STATIC_LIB;__E_FNENAME=xplib`，使 `#ifndef __E_STATIC_LIB` 包裹的动态库登记元数据被排除，并保留静态编译命令名/通知辅助逻辑。
- x64 Debug/Release 的预处理定义只有 `_DEBUG;_LIB` 或 `NDEBUG;_LIB`，没有 `__E_STATIC_LIB`、`__E_FNENAME=xplib`；同时这两项配置使用 `PrecompiledHeader=Use`，但仓库中没有 `pch.h`。这意味着静态 x64 构建至少存在配置/头文件缺口，未验证，不应视为可用构建目标。
- 工程没有链接依赖列表；动态库的 `m_szzDependFiles` 也明确返回 `"\0\0"`（无额外静态库依赖）。

## 5. 模块职责与真实调用链

### 5.1 `xplib_cmd_typedef.h`：单一命令清单（已实现元数据源）

`XPLIB_DEF(_MAKE)` 是 XPLIB 的单一事实源，当前只有一项：

- 索引：`0`
- 中文名：`XP风格`
- 英文标识：`SetXP`
- 说明：设置当前应用程序所有窗口组件为 XP 界面风格，声称成功返回真/失败返回假
- 类别：`1`
- 系统：`_CMD_OS(__OS_WIN)`，即 Windows
- 返回类型：`SDT_BOOL`
- 用户级别：`LVL_SIMPLE`
- 参数数：`1`
- 参数描述起点：`g_argumentInfo_xplib_global_var + 0`

`XPLIB_NAME`/`XPLIB_NAME_STR` 将库名、命令名和索引拼成符号/字符串，例如在 `__E_FNENAME=xplib` 时执行符号为 `xplib_SetXP_0_xplib`。同一清单被复用于命令声明、命令表、动态命令函数指针数组和静态命令名数组，避免这些表格各自漂移。

### 5.2 `include_xplib_header.h`：统一入口与声明桥接

引入 `elib/lib2.h`、`elib/lang.h`、`elib/krnllib.h` 和 `xplib_cmd_typedef.h`；动态分支下声明常量、命令、参数、自定义数据类型全局数组。随后用 `XPLIB_DEF(XPLIB_DEF_CMD)` 展开所有命令的执行函数声明。

### 5.3 `xplib_cmdDef.cpp`：命令执行层（部分实现）

`xplib_SetXP_0_xplib(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)` 已定义，读取 `pArgInf[0].m_int` 到局部变量 `arg1`。除此之外函数体没有：

- 检查 `nArgCount` 或参数类型；
- 调用 Windows API、`NotifySys` 或其它风格实现；
- 设置 `pRetData->m_bool`；
- 设置 `pRetData->m_dtDataType`；
- 错误处理或状态返回。

因此“命令存在”已实现，但“XP 风格切换”及声称的布尔结果均为**仅声明/未实现**，不是可运行功能。

### 5.4 `xplib_cmdInfo.cpp`：编辑期命令信息（已实现）

动态分支建立 `g_argumentInfo_xplib_global_var`，唯一参数为：

- 名称：`风格类型`
- 类型：`SDT_INT`
- 解释：要求 `0.#无风格`、`1.#蓝色风格`、`2.#绿色风格`、`3.#银色风格`
- 默认值字段：`0`
- 参数状态：`NULL`（未设置引用、数组、默认值标志）

再由 `XPLIB_DEF_CMDINFO` 展开生成 `g_cmdInfo_xplib_global_var`，并计算命令数。`_DEBUG` 下另有 `dbg_cmd_arg_count__` 用于核对参数数组数量。注释明确提到“静态库需要的部分”尚待补充，但静态路径中该文件的命令元数据整体被 `#if !defined(__E_STATIC_LIB)` 排除。

### 5.5 `xplib_const.cpp`：常量层（已实现）

动态分支登记 4 个 `CT_NUM` 数值常量，名称与值一一对应：

| 索引 | 易语言名称 | 数值 |
|---:|---|---:|
| 0 | `无风格` | 0 |
| 1 | `蓝色风格` | 1 |
| 2 | `绿色风格` | 2 |
| 3 | `银色风格` | 3 |

英文名和说明均为 `NULL`，布局字段为 `1`，数组数量由 `sizeof` 计算。

### 5.6 `xplib_dtType.cpp`：自定义数据类型层（已实现为空表）

动态分支定义 `g_DataType_xplib_global_var[1]`，但数量为 `0`。该占位数组避免空数组声明问题，`LIB_INFO` 通过 count=0 表示当前没有自定义数据类型、窗口组件、枚举或成员命令。

### 5.7 `xplib_dllMain.cpp`：动态库生命周期、库登记与通知入口

- `DllMain` 对进程/线程加载卸载事件只做空处理并返回 `TRUE`。
- `g_LibInfo_xplib_global_var` 登记 ABI 版本、GUID、版本、系统要求、库名称、语言、命令/常量/数据类型指针和通知函数。
- `GetNewInf()` 返回 `&g_LibInfo_xplib_global_var`，是 `.def` 中唯一导出的固定入口。
- `g_cmdInfo_xplib_global_var_fun[]` 由 `XPLIB_DEF_CMD_PTR` 展开，与命令表按索引对齐。
- `g_cmdNamesxplib[]` 由 `XPLIB_DEF_CMDNAME_STR` 展开；源码注释称其“给静态编译使用”，但该数组实际位于 `#ifndef __E_STATIC_LIB` 动态分支内，静态工程不会建立它。
- `xplib_ProcessNotifyLib_xplib()` 处理通知：
  - `NL_GET_CMD_FUNC_NAMES` 返回命令名数组地址；
  - `NL_GET_NOTIFY_LIB_FUNC_NAME` 返回自身函数名字符串；
  - `NL_GET_DEPENDENT_LIBS` 返回双空字符串，声明无附加依赖；
  - `NL_SYS_NOTIFY_FUNCTION` 转给 `ProcessNotifyLib`；
  - `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NR_DELAY_FREE`、`NL_IDE_READY`、`NL_RIGHT_POPUP_MENU_SHOW`、`NL_ADD_NEW_ELEMENT` 当前空处理；
  - 未知通知返回 `NR_ERR`，其余默认返回 `NR_OK`。

### 5.8 `elib/fnshare.cpp/.h`：运行时通知桥（已实现框架）

`fnshare.cpp` 用 `__LIB2_DEFFUNNAME` 对内部符号加库前后缀，维护三个静态状态：

- `s_pfnNotifySys`：易语言系统提供的通知函数指针；
- `s_pfnuserNotifySys`：通过 `SetUserSysNotify()` 注册的用户回调；
- `s_isDebug`：初值 `1253600`，收到系统通知后调用 `NRS_GET_PRG_TYPE` 查询程序类型。

`ProcessNotifyLib(NL_SYS_NOTIFY_FUNCTION, ...)` 保存系统通知指针，并在首次收到时查询调试/发布版本；处理其它已知通知后再调用用户回调。`NotifySys()` 是对系统通知指针的转发，`SetUserSysNotify()` 保存用户回调并返回 `ProcessNotifyLib` 地址。该层没有业务风格逻辑。

## 6. 支持库元数据与数据模型

### 6.1 `LIB_INFO` 实例

`g_LibInfo_xplib_global_var` 的当前值：

| 字段 | 当前值/含义 |
|---|---|
| `m_dwLibFormatVer` | `LIB_FORMAT_VER`（头文件定义为 `20000101`） |
| `m_szGuid` | `7F54B9CE8887428dBA9CEEB94CEF4C72` |
| 版本 | `2.0.0` |
| 所需易语言系统 | `3.7` |
| 所需系统核心支持库 | `3.7` |
| `m_szName` | `XP风格界面库` |
| `m_nLanguage` | `__GBK_LANG_VER`（1） |
| `m_dwState` | `_LIB_OS(__OS_WIN)`，仅 Windows |
| 类别 | 1 个：`0000XP风格界面`（双 `\0` 结尾的字符串表） |
| 自定义数据类型 | count=0，指向占位数组 |
| 命令 | 1 个，指向命令表和实现指针表 |
| AddIn/SuperTemplate | 均为 `NULL` |
| 通知函数 | `xplib_ProcessNotifyLib_xplib`，非空 |
| 常量 | 4 个，指向 `g_ConstInfo_xplib_global_var` |
| 依赖文件 | `NULL` |
| 作者资料 | 大有吴涛易语言软件公司及其地址、电话、邮箱、主页等硬编码信息 |
| 说明 | 明确称 Windows 95 不支持 |

`LIB_INFO` 的字段布局来自 `elib/lib2.h:1248-1315`；当前登记完全依赖静态全局对象的地址，未见运行时分配或释放。

### 6.2 命令调用数据模型

命令 ABI 使用 `PFN_EXECUTE_CMD(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)`。`MDATA_INF` 在 `elib/lib2.h:780-824` 中采用一字节对齐，包含一个覆盖基本值、指针、窗口单元、复合数据和数组数据的联合体，以及 `m_dtDataType` 类型标识。对本项目而言：

- 输入参数声明为 `SDT_INT`；实现按 `pArgInf[0].m_int` 读取。
- 命令登记声明返回 `SDT_BOOL`。
- 当前实现没有写入 `pRetData`，所以返回值契约尚未兑现；不能根据命令注释推断运行时会自动生成返回值。
- `SDT_BOOL` 的 SDK 真值宏为 `BL_TRUE=-1`、假值为 `BL_FALSE=0`，但本命令没有使用它们。

### 6.3 常量模型

`LIB_CONST_INFO`（`elib/lib2.h:735-748`）为名称、英文名、说明、布局、类型、文本和值的结构。xplib 仅使用 `CT_NUM` 和 `m_dbValue`，没有文本/复合数据持久化。

## 7. 外部接口与边界

### 7.1 动态装载接口

- 固定入口：`GetNewInf`（`Source_xplib.def:3-4`；实现于 `xplib_dllMain.cpp:89-92`）。
- 入口返回：`PLIB_INFO`。
- 动态库命令实现指针：`g_cmdInfo_xplib_global_var_fun`，与 `g_cmdInfo_xplib_global_var` 索引对应。
- Win32 导出配置由 `Source_xplib.def` 提供；x64 工程未配置该 `.def`，属于未验证配置差异。

### 7.2 命令接口

用户可见命令：`XP风格(风格类型)`。

- 参数：一个 `SDT_INT`，预期值为 0~3 的风格常量。
- 返回：元数据声明为 `SDT_BOOL`。
- 实际：只读取第一个参数，未做范围校验、未改变窗口样式、未写返回值。

### 7.3 系统通知接口

`PFN_NOTIFY_LIB` 和 `PFN_NOTIFY_SYS` 均为 `INT (WINAPI*)(INT,DWORD,DWORD)`，通知常量定义于 `elib/lib2.h:1051-1230`。当前实际使用的通知是：

- `NL_SYS_NOTIFY_FUNCTION=1`：接收系统通知函数指针；
- `NL_GET_CMD_FUNC_NAMES=14`：返回静态编译所需命令名数组；
- `NL_GET_NOTIFY_LIB_FUNC_NAME=15`：返回通知入口名称；
- `NL_GET_DEPENDENT_LIBS=16`：返回附加静态库列表；
- `NL_FREE_LIB_DATA=6` 等生命周期通知：当前空处理；
- `NRS_GET_PRG_TYPE=2030`：通过系统通知查询程序类型。

### 7.4 静态编译边界

静态库通过编译宏而非另一份源代码切换行为：

- `__E_STATIC_LIB` 会排除 `LIB_INFO`、命令信息、常量和数据类型的动态登记定义；
- `__E_FNENAME=xplib` 用于生成 `xplib_*_*_xplib` 符号；
- 动态编译分支中的 `g_cmdNamesxplib` 和通知函数名返回值用于宿主取回函数名/通知入口；这两个查询分支位于 `xplib_dllMain.cpp:6-100` 的 `#ifndef __E_STATIC_LIB` 内，并非静态编译分支的通用实现。
- `xplib_ProcessNotifyLib_xplib` 本身在静态路径仍会编译，但静态路径不会建立 `LIB_INFO`、命令元数据表或 `g_cmdNamesxplib`；静态宿主如何取得命令登记信息，当前仓库没有独立实现证据。

但 x64 静态配置缺少上述关键宏，当前不能视为等价的静态编译路径。

## 8. 依赖边界

### 仓库内依赖

```text
根目录业务实现
  ├─ include_xplib_header.h
  │   ├─ elib/lib2.h       # 易语言支持库 ABI 与运行时数据结构
  │   ├─ elib/lang.h       # GBK/语言版本
  │   ├─ elib/krnllib.h    # 核心支持库类型/版本常量
  │   └─ xplib_cmd_typedef.h
  └─ elib/fnshare.h/.cpp   # 通知与辅助运行时桥
        ├─ elib/mtypes.h
        └─（声明上依赖易语言宿主提供的通知函数）
```

### 外部/宿主依赖

- Windows API/ABI 类型和 DLL/静态库链接环境；工程声明 Windows 目标和 `v141` 工具集。
- 易语言系统宿主提供的 `PFN_NOTIFY_SYS`，以及 `NRS_MALLOC/NRS_MFREE/NRS_GET_PRG_TYPE` 等通知服务（本项目没有实现宿主）。
- 易语言支持库加载器理解 `LIB_INFO`、`.fne`、`GetNewInf` 和命令表 ABI。
- 目标语言编码为 GBK；源码中的中文注释/元数据不是 UTF-8 证据，文件以 GB18030/GBK 方式读取可还原中文。

未发现第三方包管理文件、网络服务、数据库、配置文件、资源图片、部署脚本或运行时生成数据。

## 9. 测试与验证现状

### 已有测试证据

未发现 `test/`、`tests/`、单元测试、集成测试、CI 工作流、测试数据或测试命令。`xplib.vcxproj` 仅设置 Visual Studio 编译属性，没有测试目标。

### 本轮实际检查

- 人工读取并交叉核对 23 个 Git 跟踪文件的目录/工程/源码声明。
- 读取 `xplib.sln`、两个 `.vcxproj`、`.def`、全部根目录实现文件及 `elib` 中 ABI/通知头文件关键声明。
- 检查 Git 工作树、提交日志、本地远程引用，并执行 `git ls-remote origin HEAD refs/heads/master`：远程 `HEAD` 与 `master` 均为 `cd238b09a05e80013b4a1a642b512e4a627f9092`。
- 未在当前 macOS 环境执行 MSVC/Visual Studio 构建、Windows DLL 装载、易语言 IDE 注册或运行时命令调用；因此没有“编译通过/功能通过”的结论。

### 建议的后续验证（未执行）

1. 在 Windows + Visual Studio v141 或兼容工具链中分别尝试 `Debug|Win32`、`Release|Win32`，核对 `.fne` 产物及 `GetNewInf` 导出。
2. 修正或明确 x64 配置后再尝试 x64 动态/静态构建；特别检查 `__E_FNENAME`、`__E_STATIC_LIB`、`.def` 和静态库 `pch.h` 缺口。
3. 用易语言支持库加载器验证 `LIB_INFO`、命令表、常量表和类别表能否注册。
4. 写宿主级最小调用验证 `XP风格(0..3)` 是否切换样式、是否正确写入 `BL_TRUE/BL_FALSE`；当前源码预期会暴露返回值未写入问题。
5. 验证 `NL_SYS_NOTIFY_FUNCTION` 的指针宽度与 `DWORD` 传参在目标 ABI 下是否符合宿主约定；本源码使用的是旧式 32 位数据模型，不能由 macOS 编译器替代验证。

## 10. 已实现 / 仅声明 / 未验证清单

| 范围 | 状态 | 证据与结论 |
|---|---|---|
| 支持库 `LIB_INFO` 静态登记 | 已实现（源码层） | `xplib_dllMain.cpp:31-87` 初始化完整结构 |
| 固定入口 `GetNewInf` | 已实现（源码层） | `xplib_dllMain.cpp:89-92`；Win32 `.def` 声明导出 |
| Win32 动态库工程 | 仅工程声明，未验证 | `xplib.vcxproj:51-153` 配置了 DLL、`.fne` 和 `.def`，本轮未用 MSVC 构建 |
| 全局命令元数据 | 已实现（元数据层） | `xplib_cmdInfo.cpp:5-37`，命令数为 1 |
| 命令执行入口 | 已实现（空壳） | `xplib_cmdDef.cpp:5-9` 可读参数，但无业务效果 |
| XP 风格切换 | 未实现 | 源码没有 Windows 风格 API/宿主通知调用 |
| `SDT_BOOL` 返回结果 | 仅声明 | `xplib_cmd_typedef.h:13` 声明返回 BOOL；执行函数未写 `pRetData` |
| 4 个风格常量 | 已实现 | `xplib_const.cpp:4-22` |
| 自定义数据类型 | 已实现为空表 | `xplib_dtType.cpp:7-8` count=0 |
| 系统通知桥 | 已实现（框架层） | `elib/fnshare.cpp:11-71` 保存/转发指针；业务通知处理为空 |
| 生命周期/IDE 插件通知 | 仅声明/空处理 | `xplib_dllMain.cpp:134-171` 分支存在但没有动作 |
| 静态库 Win32 宏路径 | 工程声明，未验证 | `xplib_static/xplib_static.vcxproj:92-128` 定义 `__E_STATIC_LIB` 等 |
| 静态库 x64 路径 | 未验证且存在配置缺口 | `xplib_static/xplib_static.vcxproj:130-163` 缺少关键宏并使用不存在的 `pch.h` |
| x64 动态库导出/装载 | 未验证且存在配置差异 | x64 配置未设置 `Source_xplib.def` 与 `.fne` |
| 自动化测试/CI | 未发现 | 目录与 Git 文件清单无测试/CI 文件 |

## 11. 风险、矛盾与后续复核点

1. **功能名与执行体不一致：** 元数据描述为完整 XP 风格切换，但 `xplib_SetXP_0_xplib` 只有局部读取；不能把当前仓库当作功能完成的 XP 皮肤库。
2. **返回值契约未兑现：** 返回类型为 `SDT_BOOL`，但 `pRetData` 从未初始化/写入；宿主对该命令的结果行为未定义，必须在 Windows/易语言环境验证或补齐实现后再下结论。
3. **命令参数未防御：** 直接读取 `pArgInf[0]`，不检查 `nArgCount`、`m_dtDataType` 或值域；这是实现层风险，不是 ABI 自动保障。
4. **动态/静态登记分支不对称：** 动态 metadata 全部被 `__E_STATIC_LIB` 排除；静态工程的 x64 配置又没有定义该宏，可能导致错误地编译动态路径。
5. **x64 工程属性不完整：** 动态 x64 没有 `.def`/`.fne` 配置；静态 x64 使用 `pch.h`，但仓库没有该文件。两者均只能标记为未验证，不能声称支持 x64。
6. **旧 ABI/指针模型：** SDK 自定义 `DWORD=unsigned long`，通知函数参数也使用 `DWORD` 承载指针；目标是旧式 Windows/易语言 ABI，不能用本机 macOS 编译结果替代验证。
7. **编码约束：** 文件中文内容按 GBK/GB18030 存储；后续编辑若转 UTF-8，可能破坏易语言支持库显示文本或与既有工具链的兼容性。
8. **版权/授权边界：** `elib/fnshare.*` 等文件头声明易语言作者版权并限定用途；本档仅做架构记录，不把这些兼容头声明为可自由复用代码。

## 12. Git 基线与证据索引

### Git 基线

- 本地路径：`~/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/xplib`
- 远程：`https://gitee.com/JYtechnology/xplib.git`
- 分支：`master`
- 本地 `HEAD`：`cd238b09a05e80013b4a1a642b512e4a627f9092`
- 本地提交：`2022-12-19 16:57:56 +0800`，作者/提交者 `精易科技`，提交信息 `初始化仓库`
- 远程 `HEAD` 和 `refs/heads/master`：同为 `cd238b09a05e80013b4a1a642b512e4a627f9092`（本轮 `git ls-remote` 实测）
- 本轮建档前工作树：干净，只有 `master...origin/master`；没有旧 `ARCHITECTURE.md` 或细探文档可吸收。
- 本轮允许的变更：仅新增项目根 `ARCHITECTURE.md`；未修改源码、工程、依赖、测试、配置、Git，也未删除文件。

### 关键证据路径

- 项目定位、库元数据、导出入口、通知分发：`xplib_dllMain.cpp:5-178`
- 单一命令清单、符号拼接：`xplib_cmd_typedef.h:3-14`
- 统一头与命令声明：`include_xplib_header.h:3-24`
- 唯一命令空壳实现：`xplib_cmdDef.cpp:3-9`
- 命令参数/命令表：`xplib_cmdInfo.cpp:3-39`
- 4 个常量：`xplib_const.cpp:3-23`
- 空自定义类型表：`xplib_dtType.cpp:3-10`
- 通知桥和调试版本查询：`elib/fnshare.cpp:3-71`、`elib/fnshare.h:21-55`
- ABI 数据类型、`ARG_INFO`、`CMD_INFO`、`LIB_DATA_TYPE_INFO`、`LIB_CONST_INFO`、`MDATA_INF`、`LIB_INFO`：`elib/lib2.h:149-243`、`elib/lib2.h:260-364`、`elib/lib2.h:693-748`、`elib/lib2.h:780-824`、`elib/lib2.h:1225-1318`
- 语言编码和核心库版本常量：`elib/lang.h:8-14`、`elib/krnllib.h:116-126`
- 动态库配置：`xplib.vcxproj:21-48`、`xplib.vcxproj:51-76`、`xplib.vcxproj:95-198`
- 静态库配置：`xplib_static/xplib_static.vcxproj:21-45`、`xplib_static/xplib_static.vcxproj:48-73`、`xplib_static/xplib_static.vcxproj:92-163`
- 解决方案平台映射：`xplib.sln:5-32`
- Win32 导出定义：`Source_xplib.def:1-4`
- Git 初始提交范围：`git show --stat cd238b0`，对应 23 个文件、4080 行新增。

## 13. 首轮结论

xplib 的架构是一个典型的“单一命令清单 → 多表展开 → `LIB_INFO` 注册 → 易语言宿主按 ABI 调用”的支持库骨架。它已经把宿主识别所需的库信息、类别、常量、命令参数和通知入口拼接起来，且 Win32 动态工程的预期链路清晰；但真正的 XP 风格业务尚未实现，唯一命令也没有返回值写入。当前最有价值的后续工作不是扩展更多元数据，而是先在 Windows/易语言宿主中修正并验证命令执行契约、Win32 导出链路及动态/静态 x64 配置差异。
