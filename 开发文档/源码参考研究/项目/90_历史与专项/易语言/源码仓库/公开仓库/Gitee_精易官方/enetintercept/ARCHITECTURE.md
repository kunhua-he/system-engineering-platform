# enetintercept 架构档案

## 1. 项目定位

`enetintercept` 是精易科技公开的易语言 Windows 支持库源码，面向易语言 IDE/运行时提供 WinSock2 网络拦截的数据类型、命令和组件事件元数据。源码描述的拦截对象包括 `socket`、`closesocket`、`bind`、`listen`、`accept`、`connect`、`send`、`sendto`、`recv`、`recvfrom`。

本仓库实现的是易语言支持库适配层：

- DLL 形态通过固定导出 `GetNewInf` 返回 `LIB_INFO`；
- 支持库元数据登记 37 个命令、6 个自定义数据类型及 10 个 `NetIntercept` 组件事件；
- 通过 `PFN_NOTIFY_SYS`/`ProcessNotifyLib` 与易语言系统交换通知；
- 网络服务提供者文件 `ESPINN.dll(NN为当前版本)` 被文档和命令描述为外部安装对象，仓库内没有该 DLL 或 WinSock provider 实现；
- 当前命令执行函数基本是生成的空壳，仅保留参数取值局部变量，不能据此认定网络拦截功能已经在本仓库实现。

源码说明和字符串使用 GBK/GB18030 语境（`elib/lang.h:8-14` 定义 `__GBK_LANG_VER` 与 `__COMPILE_LANG_VER`）。

## 2. 真实调用与加载流程

```text
易语言 IDE/运行时
    │
    │ LoadLibrary / 固定入口查找
    ▼
enetintercept DLL
    │  Source_enetintercept.def 仅导出 GetNewInf
    ▼
GetNewInf()
    │
    │ 返回静态 g_LibInfo_enetintercept_global_var
    │  ├─ g_cmdInfo_enetintercept_global_var（命令元数据）
    │  ├─ g_cmdInfo_enetintercept_global_var_fun（命令函数指针表）
    │  ├─ g_DataType_enetintercept_global_var（数据类型/事件元数据）
    │  ├─ g_ConstInfo_enetintercept_global_var（当前 0 个常量）
    │  └─ enetintercept_ProcessNotifyLib_enetintercept（系统通知入口）
    ▼
系统发送 NL_SYS_NOTIFY_FUNCTION
    │  dwParam1 = PFN_NOTIFY_SYS
    ▼
enetintercept_ProcessNotifyLib_enetintercept
    │
    └─ ProcessNotifyLib → fnshare.cpp 保存系统回调

程序调用支持库命令
    │
    ▼
命令函数指针表 → enetintercept_*_<index>_enetintercept
    │
    ├─ 元数据/参数类型已登记
    └─ 当前实现大多为空，仅读取 pArgInf 参数，未调用 WinSock

NetIntercept 组件登记
    │
    ▼
enetintercept_GetInterface_NetIntercept
    │
    ├─ 返回组件创建/属性/通知接口函数指针
    └─ 组件创建函数当前返回 0，属性扩展接口多为占位实现

真正的 WinSock 拦截（按仓库文案的设计边界）
    │
    └─ 依赖外部 ESPINN.dll 网络服务提供者；该实现不在本仓库中
```

## 3. 仓库与工程结构

仓库根目录没有 README、AGENTS.md、测试目录、示例目录、预编译 provider DLL 或旧 `细探-*.md` 文档；当前 Git 跟踪文件共 20 个（不含 `.git` 内部文件）。

```text
enetintercept/
├── ARCHITECTURE.md                         # 本档案；当前核对唯一新增文件
├── enetintercept.sln                        # Visual Studio solution，DLL + static 两个项目
├── enetintercept.vcxproj                    # 动态库工程
├── enetintercept.vcxproj.filters            # 动态库文件过滤器
├── enetintercept.vcxproj.user               # 用户工程设置
├── enetintercept_static/
│   ├── enetintercept_static.vcxproj         # 静态库工程，复用上级源码
│   ├── enetintercept_static.vcxproj.filters
│   └── enetintercept_static.vcxproj.user
├── Source_enetintercept.def                 # DLL 模块定义，仅导出 GetNewInf
├── include_enetintercept_header.h           # 总头文件、外部元数据声明、命令原型宏
├── enetintercept_cmd_typedef.h              # 37 个命令的 X-macro 定义
├── enetintercept_cmdDef.cpp                 # 37 个命令函数桩
├── enetintercept_cmdInfo.cpp                # ARG_INFO/CMD_INFO 命令元数据（动态库模式）
├── enetintercept_dtType.cpp                 # 自定义类型、事件、组件接口桩
├── enetintercept_const.cpp                  # 常量表，当前数量为 0
├── enetintercept_dllMain.cpp                # DllMain、LIB_INFO、导出信息、系统通知入口
└── elib/
    ├── lib2.h                               # 易语言支持库 ABI/元数据结构和宏
    ├── krnllib.h                            # 系统核心支持库常量与版本（4.5）
    ├── lang.h                               # 语言编码版本
    ├── mtypes.h                             # Windows/基础类型兼容定义
    ├── fnshare.h                            # 通知、内存、数组/文本/字节集辅助函数
    ├── fnshare.cpp                           # 通知回调保存、调试版本、用户通知转发
    ├── untshare.h                            # 组件/事件占位宏与共享定义
    └── PublicIDEFunctions.h                 # 易语言 IDE 公共函数常量和结构
```

## 4. 工程与构建边界（静态读取，未执行构建）

### 4.1 Solution

`enetintercept.sln:5-7` 注册两个 Visual Studio C++ 项目：

- `enetintercept.vcxproj`：`DynamicLibrary`；
- `enetintercept_static/enetintercept_static.vcxproj`：`StaticLibrary`。

Solution 定义 `Debug|x64`、`Debug|x86`、`Release|x64`、`Release|x86`，x86 映射项目的 `Win32` 配置（`enetintercept.sln:10-32`）。两个项目声明 `VCProjectVersion=16.0`、`WindowsTargetPlatformVersion=10.0.15063.0`、`PlatformToolset=v141`。

### 4.2 动态库工程

`enetintercept.vcxproj:21-41` 将 `elib/fnshare.cpp`、命令定义/元数据、常量、DLL 入口、数据类型实现和所有公共头纳入工程，并将 `.def` 纳入项目。

Win32 Debug/Release 配置明确设置 `__E_FNENAME=enetintercept`，并设置 `TargetExt=.fne`（`enetintercept.vcxproj:95-103,109-153`）。x64 配置在项目文件中没有 `__E_FNENAME=enetintercept`，也没有 `TargetExt=.fne`，只声明 `DynamicLibrary`（`enetintercept.vcxproj:159-198`）。由于 `elib/lib2.h:23-25` 在未定义 `__E_FNENAME` 时直接 `#error`，x64 是否能编译取决于外部属性表或环境补充；仓库内未提供此补充，未执行构建验证。

Win32 链接显式使用 `Source_enetintercept.def`（`enetintercept.vcxproj:121-126,146-152`）；x64 配置未显式使用该 `.def`，因此 x64 导出行为未验证。

### 4.3 静态库工程

静态工程通过 `..\` 路径复用同一批源文件（`enetintercept_static/enetintercept_static.vcxproj:21-38`）。Win32 Debug/Release 设置 `__E_STATIC_LIB;__E_FNENAME=enetintercept`（同文件 `:92-129`）；但 x64 Debug/Release 的预处理器定义只包含 `_DEBUG;_LIB` 或 `NDEBUG;_LIB`，没有 `__E_STATIC_LIB` 和 `__E_FNENAME`（同文件 `:130-163`）。此外 x64 配置为 `PrecompiledHeader=Use`，仓库文件清单中没有 `pch.h`，属于待在 Windows 工具链上复核的工程风险。

`__E_STATIC_LIB` 会改变源码编译边界：

- `enetintercept_cmdInfo.cpp:4-80` 的命令参数/命令元数据整段排除；
- `enetintercept_dtType.cpp:43-247` 的数据类型、成员、事件和 `g_DataType...` 元数据排除；
- `enetintercept_dllMain.cpp:6-100` 的 `DllMain`、命令函数表、`LIB_INFO`、`GetNewInf` 和命令名数组排除；
- 命令函数定义和 `ProcessNotifyLib` 仍会进入静态编译，但静态集成所需的完整外部登记方式不在本仓库中说明。

### 4.4 模块导出

`Source_enetintercept.def:1-4` 内容为：

- `LIBRARY`；
- `EXPORTS`；
- `GetNewInf`。

因此 DLL 的固定 ABI 入口是 `GetNewInf`，其返回值类型为 `PLIB_INFO`（`enetintercept_dllMain.cpp:89-92`；`elib/lib2.h:1317-1318`）。

## 5. 核心元数据模型

公共 ABI 来自 `elib/lib2.h`：

- `ARG_INFO`：命令参数名称、说明、类型、默认值和传参限制（`elib/lib2.h:266-292`）；
- `CMD_INFO`：命令名称、英文名、说明、OS/隐藏/对象构造析构复制标志、返回类型、参数数量与参数数组（`elib/lib2.h:297-364`）；
- `LIB_DATA_TYPE_ELEMENT`：数据类型成员/枚举成员（`elib/lib2.h:369-390`）；
- `EVENT_ARG_INFO2` 与 `EVENT_INFO2`：组件事件参数与返回类型（`elib/lib2.h:491-522`）；
- `LIB_DATA_TYPE_INFO`：自定义类型的成员命令、组件事件、组件接口或枚举成员（`elib/lib2.h:693-729`）；
- `LIB_CONST_INFO`：预定义常量表（`elib/lib2.h:735-748`）；
- `LIB_INFO`：支持库版本、系统要求、作者信息、数据类型、命令、通知回调、常量和依赖文件（`elib/lib2.h:1248-1315`）；
- `PFN_EXECUTE_CMD`：统一命令执行签名 `void (pRetData, nArgCount, pArgInf)`（`elib/lib2.h:1234-1239`）。

`include_enetintercept_header.h:11-19` 声明动态库模式的全局元数据数组，并在 `:22-24` 用 `ENETINTERCEPT_DEF` 为所有命令生成外部 C 函数声明。命令名通过 `__E_FNENAME` 拼接为带库名后缀的符号，例如 `enetintercept_GetProcessID_4_enetintercept`（宏定义位于 `enetintercept_cmd_typedef.h:3-9`）。

## 6. 命令面与数据类型面

### 6.1 命令登记

`enetintercept_cmd_typedef.h:12-49` 定义索引连续的 37 个命令（0–36），全部限定 `_CMD_OS(__OS_WIN)`。按数据类型分组如下：

| 命令索引 | 所属类型 | 成员命令 |
|---|---|---|
| 0–5 | `SockCallerInfo` | `CallerInfoConstruction`、`CallerInfoDestruction`、`CallerInfoCopyCmd`、`GetProcessName`、`GetProcessID`、`GetThreadID` |
| 6–14、35–36 | `SockAddr` | `SockAddrConstruction`、`SockAddrDestruction`、`SockAddrCopyCmd`、`GetFamily`、`SetFamily`、`GetData`、`SetData`、`GetDataCount`、`SetDataCount`、`GetIPPort`、`SetIPPort` |
| 15–25 | `SockData` | `SockDataConstruction`、`SockDataDestruction`、`SockDataCopyCmd`、`GetLen`、`Malloc`、`MallocFromText`、`MallocFromBin`、`Free`、`GetData`、`ToText`、`ToBin` |
| 26–31 | `ProviderInstall` | `ProviderInstallConstruction`、`ProviderInstallDestruction`、`ProviderInstallCopyCmd`、`IsInstalled`、`Install`、`Uninstall` |
| 32–34 | `NetIntercept` | `Open`、`Close`、`GetProviderVersion` |

对象构造/析构/复制命令使用 `CT_IS_OBJ_CONSTURCT_CMD`、`CT_IS_OBJ_FREE_CMD`、`CT_IS_OBJ_COPY_CMD` 标志，部分内部数据操作命令使用 `CT_IS_HIDED`（`enetintercept_cmd_typedef.h:13-49`）。

### 6.2 命令参数元数据

`enetintercept_cmdInfo.cpp:5-60` 定义 26 个 `ARG_INFO` 项，索引由命令宏中的 `g_argumentInfo_enetintercept_global_var + offset` 引用；`CMD_INFO` 数组在 `:68-80` 通过同一 X-macro 生成，动态模式下数量由 `sizeof` 计算。

参数类型覆盖 `SDT_SHORT`、`SDT_INT`、`SDT_BYTE`、`SDT_TEXT`、`SDT_BIN`，并使用 `AS_RECEIVE_VAR` 标记输出引用参数。`SockAddr` 的 `GetIPPort`/`SetIPPort` 通过 4 个字节和 1 个端口参数表达 IPv4 地址；`Install` 接受 provider 文件全路径；`SockData` 支持按长度/文本/字节集分配、按序号读写和文本/字节集转换。

### 6.3 自定义数据类型

`enetintercept_dtType.cpp:195-244` 登记 6 个类型：

| 索引 | 中文名 / 英文名 | 角色 | 成员命令数/事件数 |
|---|---|---|---:|
| 0 | `调用者信息` / `SockCallerInfo` | 保存进程名、ProcessID、ThreadID | 6 / 0 |
| 1 | `网址信息` / `SockAddr` | 对应 WinSock `sockaddr_in`，保存 IP/端口 | 11 / 0 |
| 2 | `网络数据` / `SockData` | 保存发送/接收数据 | 11 / 0 |
| 3 | `网络服务安装` / `ProviderInstall` | 安装/卸载外部 provider | 6 / 0 |
| 4 | `网截` / `NetIntercept` | `LDT_WIN_UNIT | LDT_IS_FUNCTION_PROVIDER` 组件 | 3 / 10 |
| 5 | `拦截操作` / `NetInterceptAction` | `LDT_ENUM` 枚举 | 4 枚举成员 |

前四个对象类型各有一个隐藏的 `SDT_INT` 句柄成员：`CallerInfoHandle`、`SockAddrHandle`、`SockDataHandle`、`SPIInstallHandle`（`enetintercept_dtType.cpp:82-111`）。这只是支持库对象存储槽位的元数据，仓库没有看到句柄分配和实际对象状态实现。

`NetInterceptAction` 的 4 个枚举值（`enetintercept_dtType.cpp:114-122`）为：

- `DefaultCall=0`：默认调用；
- `InvalidCall=1`：无效调用；
- `ChangeCall=2`：更改调用；
- `CloseSock=3`：关闭当前 WinSock 连接。

### 6.4 NetIntercept 事件

`enetintercept_dtType.cpp:125-193` 定义 36 个事件参数和 10 个 `EVENT_INFO2` 事件，参数均通过 `EAS_BY_REF` 表达可由事件处理读取/修改的引用数据：

| 事件索引 | 事件名 | 对应 WinSock | 参数数 | 返回类型 |
|---:|---|---|---:|---|
| 0 | `调创建套接字` | `socket` | 4 | `SDT_INT` |
| 1 | `调关闭套接字` | `closesocket` | 2 | `_SDT_NULL` |
| 2 | `调绑定` | `bind` | 3 | `SDT_INT` |
| 3 | `调侦听` | `listen` | 3 | `SDT_INT` |
| 4 | `调连接` | `connect` | 3 | `SDT_INT` |
| 5 | `调许可连接` | `accept` | 3 | `SDT_INT` |
| 6 | `调发送` | `send` | 4 | `SDT_INT` |
| 7 | `调定向发送` | `sendto` | 5 | `SDT_INT` |
| 8 | `调接收` | `recv` | 4 | `SDT_INT` |
| 9 | `调定向接收` | `recvfrom` | 5 | `SDT_INT` |

事件返回值使用整数动作码，文案定义 0 为默认调用、1 为无效调用、2 为更改调用、3 为关闭连接；事件描述明确禁止返回需要额外空间释放的文本、字节集或复合数据类型（`enetintercept_dtType.cpp:176-190`）。

## 7. 实现状态与真实调用链

### 7.1 命令实现是桩代码

`enetintercept_cmdDef.cpp` 为 37 个命令生成统一签名函数。构造、析构、查询、转换、安装/卸载、打开/关闭等多数函数体为空；带参数命令通常只把 `pArgInf` 转换到局部变量，未写入 `pRetData`，也未调用 WinSock、文件安装或 provider API。例如：

- `CallerInfoConstruction`、`GetProcessName`、`GetProcessID`、`GetThreadID` 等为空（`:6-47`）；
- `SockAddr`/`SockData`/`ProviderInstall` 构造析构及查询转换命令基本为空（`:52-260`）；
- `Open`、`Close`、`GetProviderVersion` 为空（`:264-281`）；
- `GetIPPort`、`SetIPPort` 只读取 5 个参数到局部变量（`:283-313`）。

因此当前仓库可确认的是“命令契约与事件契约的生成骨架”，不能确认“运行时网络拦截已实现”。

### 7.2 DLL 元数据与通知

`enetintercept_dllMain.cpp:31-87` 构造 `LIB_INFO`：

- 格式号：`LIB_FORMAT_VER`；
- GUID：`FD53D936D9604c659A8F1512C539C818`；
- 支持库版本：1.1，build 6；
- 易语言系统要求：3.7；
- 系统核心支持库要求：3.7；
- 语言：`__GBK_LANG_VER`；
- OS：`_LIB_OS(__OS_WIN)`；
- 自定义类型数：`g_DataType_enetintercept_global_var_count`；
- 命令数：`g_cmdInfo_enetintercept_global_var_count`；
- 常量数：0；
- 通知回调：`enetintercept_ProcessNotifyLib_enetintercept`；
- 依赖文件字符串：`NULL`。

`enetintercept_dllMain.cpp:101-180` 的 `enetintercept_ProcessNotifyLib_enetintercept`：

- `NL_GET_CMD_FUNC_NAMES` 返回动态命令函数名数组；
- `NL_GET_NOTIFY_LIB_FUNC_NAME` 返回 `enetintercept_ProcessNotifyLib_enetintercept` 名称；
- `NL_GET_DEPENDENT_LIBS` 返回 `"\0\0"`；
- `NL_SYS_NOTIFY_FUNCTION` 转发到共享层 `ProcessNotifyLib`；
- 其它已列通知（释放、IDE 卸载、延迟释放、IDE ready、右键菜单、新成员）当前为空处理；未知通知返回 `NR_ERR`。

### 7.3 共享通知和内存层

`elib/fnshare.cpp:11-71` 实现支持库与易语言系统之间的薄转发层：

- `NotifySys` 调用已保存的 `PFN_NOTIFY_SYS`，没有回调时返回 0；
- `ProcessNotifyLib` 在 `NL_SYS_NOTIFY_FUNCTION` 中保存系统回调，并通过 `NRS_GET_PRG_TYPE` 初始化 `s_isDebug`；
- 其它静态库通知分支只是注释/空分支；
- `SetUserSysNotify` 保存用户回调，并让用户回调在通知处理末尾收到同一消息。

`elib/fnshare.h` 另外提供 `ealloc`/`efree`、文本/字节集复制、数组元素解析和数组分配等辅助函数，但这些是支持库 ABI 辅助，不是网络拦截实现。`CloneBinData`/`GetBinData` 等函数通过易语言系统通知分配内存，使用时存在 ABI/生命周期前提。

### 7.4 NetIntercept 组件接口

`enetintercept_dtType.cpp:249-313` 的 `enetintercept_GetInterface_NetIntercept` 对以下接口返回函数指针：

- `ITF_CREATE_UNIT` → `enetintercept_ControlCreate_NetIntercept`；
- `ITF_PROPERTY_UPDATE_UI` → `enetintercept_PropUpDate_NetIntercept`；
- `ITF_DLG_INIT_CUSTOMIZE_DATA` → `enetintercept_PropPopDlg_NetIntercept`；
- `ITF_NOTIFY_PROPERTY_CHANGED` → `enetintercept_PropChanged_NetIntercept`；
- `ITF_GET_ALL_PROPERTY_DATA` → `enetintercept_PropGetDataAll_NetIntercept`；
- `ITF_GET_PROPERTY_DATA` → `enetintercept_PropGetData_NetIntercept`；
- `ITF_IS_NEED_THIS_KEY` → `enetintercept_PropKetInfo_NetIntercept`；
- `ITF_GET_NOTIFY_RECEIVER` → `enetintercept_PropNotifyReceiver_NetIntercept`。

未实现/返回 `NULL` 的接口包括图标属性、语言转换、消息过滤。对应实现仍是占位：

- `enetintercept_ControlCreate_NetIntercept` 返回 `0`（`:315-332`）；
- `enetintercept_PropPopDlg_NetIntercept` 将 `*pblModified=false` 后返回 `FALSE`（`:341-348`）；
- 属性读写函数没有实际属性模型（`:351-399`）；
- `enetintercept_PropNotifyReceiver_NetIntercept` 对默认创建尺寸通知返回 0（`:408-429`）。

## 8. 外部依赖与边界

| 依赖/边界 | 证据 | 结论 |
|---|---|---|
| Windows SDK / Win32 | `elib/lib2.h:61-63` 包含 `windows.h` 等；工程为 Win32/x64 | 非跨平台源码，macOS/Linux 不具备直接构建条件 |
| Visual C++ v141 | 两个 `.vcxproj` 的 `PlatformToolset` | 目标是旧版 Visual Studio C++ 工具链 |
| 易语言支持库 ABI | `elib/lib2.h`、`elib/krnllib.h`、`elib/untshare.h` | 需要易语言运行时/IDE 的 `LIB_INFO`、通知、数据布局约定 |
| 系统核心支持库 | `enetintercept_dllMain.cpp` 要求 3.7；`elib/krnllib.h` 定义 4.5 常量 | 版本语义需与实际易语言环境复核，源码没有运行时校验代码 |
| 外部 provider | 命令说明反复引用 `ESPINN.dll(NN为当前版本)`；`Install` 接受文件全名 | provider 不在仓库；安装/卸载/注册/拦截行为无法从本仓库闭环验证 |
| 静态库链接依赖 | DLL 通知接口返回 `"\0\0"`，`LIB_INFO.m_szzDependFiles=NULL` | 源码未声明额外支持库文件；不等于没有 Windows/易语言运行时依赖 |
| 编码 | `lang.h` 使用 GBK 语言版本，C++ 文件含中文字符串 | 修改/转换编码可能破坏 IDE 显示和二进制 ABI 预期 |

## 9. 风险与未验证项

### 9.1 高风险

1. **网络功能实现缺失**：命令体没有 WinSock/provider 调用，`Open`、`Close`、安装、卸载和数据操作均未形成真实执行链；仅有事件元数据不能证明拦截有效。
2. **外部 provider 不随库交付**：仓库没有 `ESPINN.dll`，且 `m_szzDependFiles=NULL`。依赖安装位置、注册协议、版本兼容和卸载恢复只能依赖外部文件/易语言环境。
3. **工程配置跨架构不一致**：动态 x64 缺少 `__E_FNENAME` 和 `.def` 设置；静态 x64 缺少 `__E_STATIC_LIB`/`__E_FNENAME` 且启用不存在的 `pch.h` 预编译头设置。是否被全局属性补齐尚未验证。
4. **ABI 与指针宽度风险**：`elib/mtypes.h` 将 `DWORD` 和 `HUNIT` 定义为 32 位语义，并将句柄/指针混用在支持库 ABI 中；工程声称支持 x64，但 x64 ABI 是否安全未有编译或运行证据。
5. **事件引用数据生命周期风险**：事件参数大量使用 `EAS_BY_REF`，`lib2.h:496-501` 要求支持库确保引用内存可访问；当前事件触发代码不在仓库，无法核实引用对象、缓冲区和释放策略。

### 9.2 中风险

1. `GetIPPort`/`SetIPPort`、`SockAddr`、`SockData` 的成员槽位只有元数据和空命令桩，潜在的边界检查、长度检查、空指针处理和所有权规则未实现。
2. `enetintercept_PropPopDlg_NetIntercept` 直接解引用 `pblModified`，虽然调用约定注释通常会传入有效指针，但源码没有空指针保护。
3. `ProcessNotifyLib` 中 `NL_GET_CMD_FUNC_NAMES`、`NL_GET_NOTIFY_LIB_FUNC_NAME`、`NL_GET_DEPENDENT_LIBS` 在共享层为空分支；动态入口实现了对应返回，但静态编译路径的完整通知协议仍未验证。
4. `LIB_INFO` 的详细作者/联系方式/说明文本与实际 provider 交付状态未经过远程文档或运行环境复核，不能把文案当作实现证据。
5. `enetintercept_cmdInfo.cpp` 的调试计数 `dbg_cmd_arg_count__` 只在 `_DEBUG` 下存在；没有测试代码实际检查命令索引、参数偏移和函数表长度。

### 9.3 未验证项

- 未在 Windows/Visual Studio 上构建 DLL 或 static library；
- 未加载 `GetNewInf`，未验证 `LIB_INFO` ABI、函数表长度、命令名数组和 `.def` 导出；
- 未安装或运行 `ESPINN.dll`，未验证 WinSock provider 的注册、拦截、卸载和重启要求；
- 未触发任意 `NetIntercept` 事件，未验证 `EVENT_INFO2` 参数引用、动作码和返回值；
- 未验证 x86/x64、Debug/Release 的工程配置和 `pch.h`/属性表补充情况；
- 未找到测试、示例、CI、发布包或旧细探文档；
- 未对源码做任何构建、安装、服务启动或网络运行操作。

## 10. Git 与版本基线

现场读取结果：

- 本地分支：`master`；
- 本地 HEAD：`7db7323d6f1449c67e38b886ca6b1b5e7c7b4cf8`；
- 提交主题：`初始化仓库`；
- 作者：`精易科技`；
- 提交时间：`2022-12-19T16:06:40+08:00`；
- 远程：`origin https://gitee.com/JYtechnology/enetintercept.git`；
- 本地 `origin/master` 与 HEAD 同为 `7db7323d6f1449c67e38b886ca6b1b5e7c7b4cf8`；
- `git ls-remote origin HEAD` 返回同一提交，远程 HEAD 为 `master`；
- 初始检查时工作树为 `## master...origin/master`，无源码改动；
- 本仓库是浅克隆（`.git/shallow` 存在），历史仅现场可见这一条 grafted 提交，不能据此推断完整项目历史。

## 11. 当前核对结论与后续复核方向

### 已确认

- 这是一个 Visual Studio C++ 易语言支持库工程，具备 DLL 与 static 两种工程外壳；
- 元数据层完整描述了 WinSock 拦截命令、对象数据类型、动作枚举和 10 个事件；
- DLL ABI 入口为 `GetNewInf`，通知入口为 `enetintercept_ProcessNotifyLib_enetintercept`；
- 当前仓库没有 provider 文件、测试或真实 WinSock 调用实现，命令和组件回调主要是生成桩。

### 后续复核顺序

1. 获取同一远程仓库的非浅历史或发布包，确认是否存在被忽略的 provider/资源/版本分支；
2. 在隔离的 Windows Visual Studio 环境只做编译前检查，先解决 x64 预处理器、`.def`、目标扩展名和 `pch.h` 配置差异；
3. 追溯 `ESPINN.dll` 的来源、版本协议、注册/卸载实现和 WinSock LSP/服务提供者调用链；
4. 对命令函数和事件触发路径建立 ABI 级验证：返回值、`pRetData`、引用参数、对象句柄、内存释放和错误码；
5. 只有发现真实实现源码或发布二进制后，才能把“网络拦截支持库”从“元数据/桩工程”升级判定为“可运行实现”。

本文件为本项目根目录唯一架构档案；旧 `细探-*.md` 未发现，后续仅维护本文件。