# esslayer 架构档案

## 1. 项目定位

`esslayer` 是 Gitee `JYtechnology/esslayer` 仓库中的易语言 Windows 支持库源码骨架，库名为“保密通讯支持库”。它面向易语言运行时/IDE 的支持库 ABI，声明一组“保密服务器”和“保密客户端”对象、命令元数据、命令处理函数指针、库通知入口及静态库兼容信息。

当前仓库基线只有一次初始化提交；源码中的网络、密钥、加密、收发和生命周期命令处理函数均为空函数体，未发现实际 socket、RSA、RC4、DES 或 SSL 数据通道实现。因此，本项目当前可确认是“支持库接口/元数据/工程模板”，不能据现有源码认定为可用的保密通信实现。

本档案仅基于当前工作树源码和 Git 元数据建立。首轮建档不修改源码、不安装依赖、不构建、不提交 Git。后续只维护本文件；没有发现旧 `细探-*.md` 或既有 `ARCHITECTURE.md`。

## 2. 总体架构与真实调用流

```text
易语言 IDE / 运行时
        │
        │  加载 DLL：按导出名调用 GetNewInf()
        ▼
Source_esslayer.def
        │
        ▼
esslayer_dllMain.cpp
        ├─ g_LibInfo_esslayer_global_var
        │    ├─ 库格式/版本/名称/作者/系统要求
        │    ├─ 自定义数据类型表 ───────────────┐
        │    ├─ 命令元数据表 ─────────────────┐ │
        │    ├─ 命令处理函数指针表 ──────────┐ │ │
        │    ├─ 常量表                       │ │ │
        │    └─ esslayer_ProcessNotifyLib_esslayer()
        │
        ├─ GetNewInf() → 返回 PLIB_INFO        │ │ │
        └─ ProcessNotify → 系统通知/静态库查询  │ │ │
                                                │ │ │
        ┌───────────────────────────────────────┘ │ │
        ▼                                         │ │
esslayer_cmd_typedef.h                            │ │
        └─ ESSLAYER_DEF(_MAKE) 一次声明 26 个命令   │ │
                                                  │ │
        ┌─────────────────────────────────────────┘ │
        ▼                                           │
esslayer_cmdInfo.cpp                            │
        ├─ 17 条参数 ARG_INFO                       │
        └─ ESSLAYER_DEF → CMD_INFO[]               │
                                                    │
        ┌───────────────────────────────────────────┘
        ▼
esslayer_cmdDef.cpp
        └─ 26 个导出命名的 PFN_EXECUTE_CMD 处理函数
           （当前均为空实现，仅局部读取 pArgInf 参数）

elib/fnshare.cpp
        └─ 接收 NL_SYS_NOTIFY_FUNCTION 保存 PFN_NOTIFY_SYS
           → NotifySys() 转发运行时通知
           → ealloc/efree 等公共辅助函数可通过该回调访问宿主
```

静态库路径如下：

```text
易语言静态编译
        │
        ▼
esslayer_static/esslayer_static.vcxproj
        ├─ 定义 __E_STATIC_LIB
        ├─ 复用根目录 6 个 .cpp 与公共头文件
        ├─ 不编译 DLL 入口/库元数据区（条件编译排除）
        └─ 通过 esslayer_ProcessNotifyLib_esslayer()
           提供命令函数名、通知函数名、依赖库列表查询
```

## 3. 目录与文件地图

| 路径 | 职责 | 证据 |
|---|---|---|
| `esslayer.sln` | Visual Studio 解决方案，包含 DLL 项目和静态库项目 | 解决方案项目项 |
| `esslayer.vcxproj` | `DynamicLibrary` 工程；Win32/x64、Debug/Release 配置 | `ConfigurationType`、源文件列表 |
| `esslayer_static/esslayer_static.vcxproj` | `StaticLibrary` 工程；复用根目录源码 | `__E_STATIC_LIB`、相对路径源码项 |
| `Source_esslayer.def` | DLL 模块定义文件，仅导出 `GetNewInf` | `EXPORTS GetNewInf` |
| `include_esslayer_header.h` | 统一包含易语言 ABI 头、命令定义头；声明全局元数据；用宏生成命令声明 | `#include`、`ESSLAYER_DEF_CMD` |
| `esslayer_cmd_typedef.h` | 唯一命令清单；命令索引、中文名、英文符号、返回类型、参数数量和参数表起点 | `ESSLAYER_DEF(_MAKE)` |
| `esslayer_cmdDef.cpp` | 26 个命令处理函数的符号定义和参数读取骨架 | `esslayer_*_<index>_esslayer` |
| `esslayer_cmdInfo.cpp` | 17 条 `ARG_INFO` 和由命令清单展开的 `CMD_INFO[]` | `g_argumentInfo_...`、`g_cmdInfo_...` |
| `esslayer_dtType.cpp` | 两个用户数据类型、方法索引表和隐藏成员表 | `g_DataType_...` |
| `esslayer_const.cpp` | 常量元数据占位表；当前数量为 0 | `g_ConstInfo_..._count = 0` |
| `esslayer_dllMain.cpp` | DLL 生命周期空壳、`LIB_INFO`、`GetNewInf`、库通知入口、静态编译查询表 | `DllMain`、`GetNewInf`、`esslayer_ProcessNotifyLib_esslayer` |
| `elib/lib2.h` | 易语言支持库 ABI 基础定义、数据类型、命令/库/数据结构和通知码 | 被 `include_esslayer_header.h` 引入 |
| `elib/fnshare.h/.cpp` | 宿主系统通知回调、内存辅助、调试版本和通知转发 | `NotifySys`、`ProcessNotifyLib` |
| `elib/lang.h` | 编译语言版本；固定为 GBK | `__COMPILE_LANG_VER` |
| `elib/krnllib.h` | 核心支持库控件/类型常量和版本标识 | `DTC_*`、`LI_KRNL_LIB_*` |
| `elib/mtypes.h` | Windows/旧式基础类型兼容定义 | `DWORD`、`MDATA` 相关基础类型 |
| `elib/untshare.h` | 单元属性/序列化/窗口辅助占位工具 | `CPropertyInfo`、`GetWndPtr` 等 |
| `elib/PublicIDEFunctions.h` | IDE 公共功能通知码和扩展接口结构 | `NES_*`、`NRS_*`、`NL_*` |
| `*.vcxproj.filters` | Visual Studio 虚拟筛选器 | `源文件`、`头文件`、`elib` |
| `*.vcxproj.user` | 本地 Visual Studio 用户配置文件 | 工程文件清单 |

仓库共 22 个 Git 跟踪文件；没有 README、测试目录、构建产物或依赖锁文件。

## 4. 库元数据、入口与 ABI

### 4.1 DLL 导出入口

`Source_esslayer.def` 仅导出：

```text
GetNewInf
```

`esslayer_dllMain.cpp::GetNewInf()` 返回静态全局 `g_LibInfo_esslayer_global_var` 的地址。该结构由 `elib/lib2.h` 定义的 `LIB_INFO` ABI 描述，当前源码显式填入：

- 格式：`LIB_FORMAT_VER`；
- GUID：`931A3D5BC194493f97A2830FE4D7A32D`；
- 库版本：`2.0.0`；
- 易语言系统要求：`3.7`；
- 核心支持库要求：`3.7`；
- 名称：`保密通讯支持库`；
- 语言：`__GBK_LANG_VER`；
- 支持操作系统标志：`OS_ALL`，但命令和数据类型清单均使用 Windows 标志；
- 作者/联系信息：源码中的大连大有吴涛易语言软件开发有限公司信息；
- 自定义数据类型：2 个；
- 命令：26 个；
- 常量：0 个；
- AddIn、SuperTemplate、依赖文件列表：`NULL`；
- 库通知函数：`esslayer_ProcessNotifyLib_esslayer`。

### 4.2 系统通知入口

`esslayer_ProcessNotifyLib_esslayer(INT nMsg, DWORD dwParam1, DWORD dwParam2)` 使用 `switch` 分派：

| 通知 | 当前行为 |
|---|---|
| `NL_GET_CMD_FUNC_NAMES` | 返回静态命令函数名数组 `g_cmdNamesesslayer`（仅非 `__E_STATIC_LIB` 编译区） |
| `NL_GET_NOTIFY_LIB_FUNC_NAME` | 返回字符串 `esslayer_ProcessNotifyLib_esslayer`（仅非静态库区） |
| `NL_GET_DEPENDENT_LIBS` | 返回 `"\\0\\0"`，表示没有额外静态库依赖（仅非静态库区） |
| `NL_SYS_NOTIFY_FUNCTION` | 调用 `ProcessNotifyLib`，把宿主 `PFN_NOTIFY_SYS` 交给 `elib/fnshare.cpp` 保存 |
| `NL_FREE_LIB_DATA` | 空处理 |
| `NL_UNLOAD_FROM_IDE` | 空处理 |
| `NR_DELAY_FREE` | 空处理，不返回延迟释放语义 |
| `NL_IDE_READY` | 空处理 |
| `NL_RIGHT_POPUP_MENU_SHOW` | 空处理 |
| `NL_ADD_NEW_ELEMENT` | 空处理 |
| 其他 | 返回 `NR_ERR` |

`elib/fnshare.cpp::ProcessNotifyLib` 收到 `NL_SYS_NOTIFY_FUNCTION` 后保存宿主回调，并在调试状态初始值 `1253600` 时调用 `NotifySys(NRS_GET_PRG_TYPE, 0, 0)` 更新运行模式。之后还会把通知转发给可选用户回调 `s_pfnuserNotifySys`。`NotifySys` 在回调未设置时返回 0。

### 4.3 命令函数命名

`esslayer_cmd_typedef.h` 定义：

```text
ESSLAYER_NAME(index, english_name)
    → esslayer_<english_name>_<index>_esslayer
```

例如索引 1 的 `StartServer` 生成 `esslayer_StartServer_1_esslayer`。`include_esslayer_header.h` 用同一份命令清单生成命令声明，`esslayer_dllMain.cpp` 生成函数指针表和静态命令名表，避免元数据与函数索引分裂。

## 5. 数据模型与对象边界

`esslayer_dtType.cpp` 声明两个易语言用户数据类型，均只允许 Windows：

| 易语言类型 | 英文名 | 方法索引 | 隐藏成员 |
|---|---|---|---|
| `保密服务器` | `SecurityServer` | `0..13` | `服务器句柄` / `S_SOCKET` / `SDT_INT` |
| `保密客户端` | `SecurityClient` | `14..25` | `连接句柄` / `C_SOCKET` / `SDT_INT` |

源码只在元数据层声明句柄成员，没有看到句柄结构、socket 表、并发锁、连接状态、缓冲区或加密状态的实现。构造/析构函数是隐藏命令，由易语言对象生命周期机制调用，但当前处理函数为空。

## 6. 命令接口清单

所有 26 个命令通过 `ESSLAYER_DEF(_MAKE)` 同时进入元数据、函数声明和函数指针表。`_CMD_OS(__OS_WIN)` 使命令声明为 Windows-only；函数实现均接收统一 ABI：

```text
void(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)
```

### 6.1 保密服务器（索引 0–13）

| 索引 | 中文命令 | C 符号 | 返回 | 参数 |
|---:|---|---|---|---|
| 0 | `服务器的构造函数` | `CreateServer` | `_SDT_NULL` | 无；隐藏构造命令 |
| 1 | `启动` | `StartServer` | `SDT_BOOL` | `端口号: SDT_INT`；`处理函数: SDT_SUB_PTR` |
| 2 | `停止` | `StopServer` | `_SDT_NULL` | 无 |
| 3 | `置连接私钥` | `SetLinkPrivateKey` | `SDT_BOOL` | `私钥文本: SDT_TEXT`；`公共模数: SDT_TEXT` |
| 4 | `发送数据` | `ServerSendData` | `SDT_BOOL` | `客户端句柄: SDT_INT`；`数据: _SDT_ALL` |
| 5 | `取消息代码` | `ServerGetMsgCode` | `SDT_INT` | 无；要求在服务端处理函数中调用 |
| 6 | `取客户句柄` | `GetClientHandle` | `SDT_INT` | 无；要求在服务端处理函数中调用 |
| 7 | `取客户IP` | `GetClientIPAddr` | `SDT_TEXT` | `客户句柄: SDT_INT` |
| 8 | `取回数据` | `ServerGetMsgData` | `SDT_BOOL` | `&数据: SDT_BIN`，接收变量 |
| 9 | `断开连接` | `CloseClient` | `SDT_BOOL` | `客户句柄: SDT_INT` |
| 10 | `服务析构函数` | `ServerRelease` | `_SDT_NULL` | 无；隐藏析构命令 |
| 11 | `备用` | `BeiYong` | `SDT_BOOL` | 无；隐藏占位命令 |
| 12 | `备用` | `BeiYong` | `SDT_BOOL` | 无；隐藏占位命令 |
| 13 | `备用` | `BeiYong` | `SDT_BOOL` | 无；隐藏占位命令 |

服务器说明文本定义了消息代码：1=客户连接，2=客户断开，3=客户数据到达，-1=错误。`StartServer` 的处理函数参数说明为无参数回调。

### 6.2 保密客户端（索引 14–25）

| 索引 | 中文命令 | C 符号 | 返回 | 参数 |
|---:|---|---|---|---|
| 14 | `客户端的构造函数` | `CreateClient` | `_SDT_NULL` | 无；隐藏构造命令 |
| 15 | `置连接公钥` | `SetLinkPublicKey` | `SDT_BOOL` | `公钥文本: SDT_TEXT`；`公共模数: SDT_TEXT` |
| 16 | `置加密方式` | `SetEncryptStyle` | `_SDT_NULL` | `加密方式: SDT_INT`，0=RC4，1=DES |
| 17 | `连接` | `ClientConnect` | `SDT_BOOL` | `服务器地址: SDT_TEXT`；`端口: SDT_INT`；`处理函数: SDT_SUB_PTR`；可选 `处理函数参数: SDT_INT` |
| 18 | `断开` | `DisconnectClient` | `_SDT_NULL` | 无 |
| 19 | `取消息代码` | `ClientGetMsgCode` | `SDT_INT` | 无；要求在客户端处理函数中调用 |
| 20 | `取回数据` | `recv_client` | `SDT_BOOL` | `&数据: SDT_BIN`，接收变量 |
| 21 | `发送数据` | `send_client` | `SDT_BOOL` | `数据: _SDT_ALL` |
| 22 | `客户端的析构函数` | `ReleaseClient` | `_SDT_NULL` | 无；隐藏析构命令 |
| 23 | `备用` | `BeiYong` | `SDT_BOOL` | 无；隐藏占位命令 |
| 24 | `备用` | `BeiYong` | `SDT_BOOL` | 无；隐藏占位命令 |
| 25 | `备用` | `BeiYong` | `SDT_BOOL` | 无；隐藏占位命令 |

客户端说明文本定义了消息代码：1=服务器断开，2=数据到达，-1=错误。`ClientConnect` 允许处理函数接收 0 或 1 个整数参数；参数 4 通过 `AS_DEFAULT_VALUE_IS_EMPTY` 表示可省略/空默认值。

## 7. 参数与 ABI 数据流

`esslayer_cmdInfo.cpp` 按命令清单使用参数表起点索引，共定义 17 条 `ARG_INFO`：

- 服务器：端口、服务端处理函数、私钥、公模、客户端句柄、发送数据、客户句柄、接收数据；
- 客户端：公钥、公模、加密方式、服务器地址、端口、客户端处理函数、处理函数参数、接收数据、发送数据。

`esslayer_cmdDef.cpp` 中已明确显示的参数解码方式：

| 易语言类型 | 处理函数读取字段 |
|---|---|
| `SDT_INT` | `pArgInf[n].m_int` |
| `SDT_TEXT` | `pArgInf[n].m_pText` |
| `SDT_SUB_PTR` | `pArgInf[n].m_dwSubCodeAdr` |
| `_SDT_ALL` | `pArgInf[n].m_pByte` |
| `SDT_BIN` 接收变量 | `pArgInf[n].m_ppBin` |

当前处理函数只完成局部变量读取，没有设置 `pRetData`，也没有调用 `NotifySys`、socket API、加密 API 或内存管理辅助函数。因而返回值行为在当前源码中未实现，接口表里的返回类型只是编辑器/运行时元数据声明。

## 8. 编译工程与依赖边界

### 8.1 DLL 工程

`esslayer.vcxproj`：

- 类型：`DynamicLibrary`；
- 配置：`Debug|Win32`、`Release|Win32`、`Debug|x64`、`Release|x64`；
- 工具集：`v141`；
- Windows SDK：`10.0.15063.0`；
- 字符集：Unicode；
- Win32 Debug/Release 配置设置 `TargetExt=.fne`；x64 配置未设置相同目标扩展；
- Win32 Debug/Release 通过 `Source_esslayer.def` 设置模块定义文件；x64 配置未设置该链接项；
- 运行库：Win32 Debug=`MultiThreadedDebug`，Win32 Release=`MultiThreaded`，x64 对应配置也分别设置静态运行库；
- 源文件：根目录 5 个支持库 `.cpp` 加 `elib/fnshare.cpp`；
- 依赖：工程仅通过源码内 `#include` 依赖 Windows SDK 和仓库内 `elib` 头文件，`m_szzDependFiles=NULL`。

### 8.2 静态库工程

`esslayer_static/esslayer_static.vcxproj`：

- 类型：`StaticLibrary`；
- 同样声明 Debug/Release 与 Win32/x64 四配置；
- 预处理器在 Win32 Debug/Release 明确加入 `__E_STATIC_LIB` 和 `__E_FNENAME=esslayer`；x64 配置只出现 `_DEBUG`/`NDEBUG`、`_LIB`，没有显式 `__E_STATIC_LIB` 或 `__E_FNENAME=esslayer`，这是需后续复核的工程配置差异；
- 通过 `..\` 引用根目录源码和头文件；
- 含 `MultiProcessorCompilation=true` 的 Win32 配置；
- 不包含 `Source_esslayer.def`。

### 8.3 依赖关系

```text
Windows SDK / MSVC v141
        │
        ├─ windows.h、DLL/Win32 类型与 API
        └─ Visual Studio 工程/链接器

esslayer.vcxproj 或 esslayer_static.vcxproj
        │
        ▼
include_esslayer_header.h
        ├─ elib/lib2.h
        ├─ elib/lang.h
        ├─ elib/krnllib.h
        └─ esslayer_cmd_typedef.h
             │
             ├─ esslayer_cmdInfo.cpp → CMD_INFO/ARG_INFO
             ├─ esslayer_cmdDef.cpp  → 命令处理函数
             ├─ esslayer_dtType.cpp  → LIB_DATA_TYPE_INFO
             └─ esslayer_dllMain.cpp → LIB_INFO/GetNewInf/通知

esslayer_dllMain.cpp
        └─ elib/fnshare.h/.cpp → PFN_NOTIFY_SYS 宿主回调
```

仓库没有第三方包管理文件、外部源码子模块、运行配置、证书/密钥文件或测试依赖声明。源码注释提到 `RSATool2v14.rar` 和 SSL 原理，但仓库没有该工具、证书、算法库或实现调用，不能视为实际依赖。

## 9. 关键调用链

### 9.1 DLL 装载与命令注册

1. 易语言宿主按 `GetNewInf` 加载 DLL 导出；
2. `GetNewInf()` 返回 `g_LibInfo_esslayer_global_var`；
3. 宿主读取库版本、系统要求、2 个数据类型和 26 个命令；
4. 宿主使用 `m_pCmdsFunc` 中与 `CMD_INFO` 同索引的函数指针；
5. 命令进入对应 `esslayer_<name>_<index>_esslayer`；
6. 当前函数只读取参数，不执行实际业务，不写返回值。

### 9.2 宿主通知初始化

1. 宿主调用 `esslayer_ProcessNotifyLib_esslayer(NL_SYS_NOTIFY_FUNCTION, pfnNotifySys, ...)`；
2. 入口调用 `ProcessNotifyLib`；
3. `fnshare.cpp` 保存 `PFN_NOTIFY_SYS`；
4. 首次初始化时通过 `NRS_GET_PRG_TYPE` 获取运行模式；
5. 后续公共辅助函数可调用 `NotifySys`，但当前命令函数没有使用该链路。

### 9.3 事件语义（元数据声明）

```text
服务器启动(端口, 处理函数)
    ├─ 连接事件 → 处理函数 → 取消息代码=1 → 取客户句柄/取客户IP
    ├─ 断开事件 → 处理函数 → 取消息代码=2 → 取客户句柄/取客户IP/断开连接
    └─ 数据事件 → 处理函数 → 取消息代码=3 → 取客户句柄/取回数据

客户端连接(地址, 端口, 处理函数, 可选整数)
    ├─ 断开事件 → 处理函数 → 取消息代码=1
    └─ 数据事件 → 处理函数 → 取消息代码=2 → 取回数据
```

上图来自命令说明文本，不是已被实现的运行时行为；当前代码没有事件循环或 socket 处理器。

## 10. 测试、验证与构建状态

### 已确认

- Git 工作树在建档前为干净状态：`master...origin/master`，无修改、无未跟踪文件；
- 本地 `HEAD`、`origin/master` 和 `origin/HEAD` 均为 `49eb913e0ddaf316c47cb42936b2d7dd36fa3627`；
- `git ls-remote origin HEAD refs/heads/master` 与本地远程引用一致；
- 最新提交时间为 `2022-12-19T16:55:24+08:00`，提交说明为“初始化仓库”；
- 源码清单和两个 Visual Studio 工程的源文件引用已人工对照；
- 命令清单索引为 0–25，服务器数据类型索引覆盖 0–13，客户端覆盖 14–25；
- 未发现 README、测试文件、旧 `细探-*.md` 或旧 `ARCHITECTURE.md`。

### 未执行

- 未在当前 macOS 环境执行 MSBuild/Visual Studio 构建：工程依赖 Windows SDK、MSVC v141 和 Windows 头文件，当前环境不具备可确认的 Windows 构建链；
- 未运行 DLL 加载、易语言 IDE 装载、静态编译或网络通信实测；
- 未进行 socket/RSA/RC4/DES/SSL 行为验证，因为当前命令处理函数为空；
- 未安装依赖、未启动服务、未生成二进制和构建目录。

### 构建前应复核

1. x64 DLL 配置是否需要补 `ModuleDefinitionFile=Source_esslayer.def`，否则 `GetNewInf` 可能不导出；
2. x64 DLL 配置是否需要与 Win32 一致设置 `.fne` 目标扩展；
3. 静态库 x64 配置是否需要补 `__E_STATIC_LIB` 与 `__E_FNENAME=esslayer`；
4. `LIB_INFO` 中声明的 `OS_ALL` 与对象/命令实际 Windows-only 标志是否符合目标宿主语义；
5. 命令实现是否来自另一个未纳入仓库的源码/分支；当前仓库本身没有实现证据。

## 11. 风险与未确认项

- **功能完整性风险（高）**：26 个命令处理函数均为空；当前不能建立、监听、连接、发送、接收、断开或加解密。
- **返回值风险（高）**：处理函数未写 `pRetData`，声明的 `SDT_BOOL`、`SDT_INT`、`SDT_TEXT` 返回值没有实现证据。
- **安全性风险（高）**：说明文本声称 RSA/RC4/DES/SSL 语义，但源码没有算法实现和密钥校验链；不能把说明文本当成密码学保证。
- **工程配置风险（中）**：DLL x64 和静态库 x64 配置相对 Win32 缺少关键宏/DEF/目标扩展设置，需在 Windows 构建环境复核。
- **ABI 兼容风险（中）**：`elib` 是仓库内复制的易语言 ABI 头文件，源码使用旧式 `DWORD`/指针转 `INT` 等接口约定；在不同位数工具链上需验证结构布局和指针宽度。
- **编码风险（中）**：库声明 `__GBK_LANG_VER`，源码文件实际含中文字符串；跨工具链或 UTF-8 默认编译环境需确认源文件编码处理。
- **资源生命周期风险（中）**：`DllMain`、`NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE` 和对象构造/析构处理均为空，真实实现若补入全局 socket/线程资源，必须定义释放顺序。
- **协议语义风险（中）**：服务端与客户端消息代码由说明文本给出，但没有队列、事件线程、并发模型、粘包拆包、错误码或超时设计证据。
- **依赖声明风险（低/待核）**：`m_szzDependFiles` 和静态依赖返回空，但真实加密/网络实现若在外部库中，当前声明会不完整。

## 12. 证据基线

- 项目根：`/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/esslayer`
- Git 远程：`https://gitee.com/JYtechnology/esslayer.git`
- 本地分支：`master`
- 基线提交：`49eb913e0ddaf316c47cb42936b2d7dd36fa3627`
- 基线提交时间：`2022-12-19T16:55:24+08:00`
- 主要入口：`Source_esslayer.def`、`esslayer_dllMain.cpp::GetNewInf`、`esslayer_dllMain.cpp::esslayer_ProcessNotifyLib_esslayer`
- 命令事实源：`esslayer_cmd_typedef.h::ESSLAYER_DEF`
- 命令实现：`esslayer_cmdDef.cpp`
- 参数元数据：`esslayer_cmdInfo.cpp`
- 数据类型元数据：`esslayer_dtType.cpp`
- ABI 事实源：`elib/lib2.h`、`elib/fnshare.h`、`elib/PublicIDEFunctions.h`
- 旧细探状态：未发现 `细探-*.md`；本文件为项目根唯一架构档案。

## 13. 首轮结论

`esslayer` 的可验证架构是：以 `ESSLAYER_DEF` 为单一命令清单，通过宏展开同步生成易语言命令元数据、参数表、处理函数声明/指针表和静态命令名表；以 `LIB_INFO`/`GetNewInf`/`ProcessNotifyLib` 对接易语言宿主 ABI；以两个用户数据类型包装服务器/客户端命令集合；以 `fnshare` 保存宿主系统通知回调。当前实现停留在接口骨架，业务通信和密码学行为没有落地证据。任何后续“保密通讯功能已实现”的结论，都必须补充真实 Windows 构建、宿主装载、端到端连接及算法/密钥验证证据。
