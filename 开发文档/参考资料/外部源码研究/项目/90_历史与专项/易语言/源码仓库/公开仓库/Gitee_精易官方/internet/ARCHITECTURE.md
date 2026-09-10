# internet 支持库架构建档

> 首轮全量架构建档。本文是本仓库根目录唯一的架构事实源；源码、工程文件和 Git 记录优先于注释中的产品描述。
>
> 状态标记：**已实现**=源码中存在可执行实现；**仅声明/元数据**=接口、命令说明或工程接线存在，但没有可确认的业务执行逻辑；**未验证**=当前环境无法完成构建、装载或运行验证。

## 1. 项目定位

`internet` 是面向易语言的 Windows 网络功能支持库工程，目标是向易语言 IDE/运行时登记一组网络相关命令，覆盖三类：邮件发送、HTTP/FTP 操作、拨号上网。仓库采用易语言支持库 ABI，通过 `LIB_INFO`、`CMD_INFO`、`ARG_INFO` 和 `PFN_EXECUTE_CMD` 把 C/C++ 函数映射为易语言命令，并同时提供动态库工程和静态库工程。

**重要裁决：** 当前提交只完整提供了命令目录、参数元数据、支持库登记和通知/内存适配框架；25 个网络命令的函数体均只读取参数或为空，没有写入返回值，也没有调用 SMTP、HTTP、FTP、RAS 或 WinINet API。因此“支持 SMTP/HTTP/FTP”是库说明和命令契约层的目标，不是当前源码已证实的运行能力。

## 2. 总体流程图

```text
易语言 IDE / 运行时
        │
        │ 动态装载 GetNewInf()
        ▼
┌──────────────────────────────┐
│ internet_dllMain.cpp          │
│ LIB_INFO + 命令/函数指针表     │
└──────────────┬───────────────┘
               │ 引用
               ▼
┌──────────────────────────────┐
│ internet_cmd_typedef.h        │
│ INTERNET_DEF：25 条命令契约    │
└──────┬───────────────┬───────┘
       │               │
       ▼               ▼
cmdInfo.cpp       cmdDef.cpp
参数/返回值/分类   25 个执行函数（当前桩）
       │               │
       └───────┬───────┘
               ▼
       PMDATA_INF 参数 ABI
               │
               ├─ 当前：只提取 argN，未产生网络副作用/返回数据
               └─ 目标：SMTP、HTTP、FTP、RAS（源码未实现）

系统通知链：
易语言系统 ──NL_SYS_NOTIFY_FUNCTION──> internet_ProcessNotifyLib
                                      └─> ProcessNotifyLib
                                           ├─保存 PFN_NOTIFY_SYS
                                           ├─查询 NRS_GET_PRG_TYPE
                                           └─转发用户通知回调

静态库路径：
__E_STATIC_LIB ──> 同一批命令实现/头文件 ──> internet_static.lib
                  （静态命名宏；当前无调用方或链接验证）
```

## 3. 真实目录与分层

仓库根目录共 23 个 Git 跟踪文件，未发现 README、测试目录、文档目录或旧 `细探-*.md` 文件。

```text
internet/
├── internet.sln                         # VS 解决方案，含动态库和静态库
├── internet.vcxproj                     # 动态库工程
├── internet.vcxproj.filters             # VS 文件分组
├── internet.vcxproj.user                # 空用户属性
├── internet_static/
│   ├── internet_static.vcxproj          # 静态库工程，复用上层源码
│   ├── internet_static.vcxproj.filters
│   └── internet_static.vcxproj.user     # 空用户属性
├── internet_cmd_typedef.h               # INTERNET_DEF：命令单一事实定义
├── internet_cmdInfo.cpp                 # ARG_INFO / CMD_INFO 元数据表
├── internet_cmdDef.cpp                  # 命令执行入口，目前为桩
├── internet_dllMain.cpp                 # DLL 入口、LIB_INFO、通知分发、动态命名
├── internet_dtType.cpp                  # 自定义数据类型表，目前数量为 0
├── internet_const.cpp                   # 常量表，目前数量为 0
├── include_internet_header.h            # 公共聚合头和命令声明展开
├── Source_internet.def                  # DLL 仅导出 GetNewInf
└── elib/                                # 易语言支持库 ABI/辅助层
    ├── lib2.h                           # LIB_INFO、CMD_INFO、MDATA_INF 等核心 ABI
    ├── mtypes.h                         # 非 Windows 类型别名/宏兼容层
    ├── lang.h                           # 语言版本和 Windows 基础包含
    ├── krnllib.h                        # 核心支持库常量、类型和通知码
    ├── fnshare.h / fnshare.cpp          # 通知、内存、数组/文本/字节集辅助
    ├── untshare.h                       # 组件/属性辅助模板（本项目未使用业务组件）
    └── PublicIDEFunctions.h             # IDE AddIn 功能号定义（本项目未调用）
```

## 4. 模块职责与实现状态

| 模块 | 职责 | 状态与证据 |
|---|---|---|
| `internet_cmd_typedef.h` | 通过 `INTERNET_DEF(_MAKE)` 定义 25 条命令、索引、英文名、返回类型、分类、参数范围 | **已实现（契约）**；索引为 0–24，类别为邮件发送/HTTP及FTP操作/拨号上网 |
| `internet_cmdInfo.cpp` | 建立 46 项 `ARG_INFO`，再展开成 `CMD_INFO g_cmdInfo_internet_global_var[]` | **已实现（元数据）**；与命令索引和参数偏移对应 |
| `internet_cmdDef.cpp` | 暴露 25 个 `PFN_EXECUTE_CMD` 兼容函数 | **仅声明/桩实现**；函数体只有 `pArgInf[n]` 读取或为空，无 `pRetData` 写入、无网络 API 调用 |
| `internet_dllMain.cpp` | DLL 入口；建立函数指针表和 `LIB_INFO`；实现 `GetNewInf`；处理系统通知 | **部分已实现**；登记、动态命名和通知分支存在，网络业务未接入 |
| `internet_dtType.cpp` | 自定义数据类型登记 | **已实现为空表**；数组大小为 1，但 `g_DataType..._count = 0` |
| `internet_const.cpp` | 预定义常量登记 | **已实现为空表**；数组大小为 1，但 `g_ConstInfo..._count = 0` |
| `elib/fnshare.cpp/h` | 保存系统回调、通知系统、申请/释放易语言内存、克隆文本/字节集、解析数组 | **已实现（通用底座）**；本项目命令桩尚未使用这些网络业务辅助 |
| `elib/lib2.h` | 定义静态命名宏、基础数据类型、命令/库信息结构、通知函数原型 | **已实现（外部 ABI 依赖）** |
| `Source_internet.def` | DLL 导出表 | **已实现**；仅导出固定入口 `GetNewInf` |
| `internet.vcxproj` | Win32/x64、Debug/Release 动态库构建配置 | **工程声明已实现；构建未验证** |
| `internet_static/internet_static.vcxproj` | 复用上层源码构建静态库 | **工程声明已实现；构建未验证** |

### 4.1 25 条命令清单

| 索引 | 易语言名称 | 英文符号 | 分类 | 返回类型 | 当前执行状态 |
|---:|---|---|---|---|---|
| 0 | 连接发信服务器 | `ConnectSmtpServer` | 1 邮件发送 | `SDT_BOOL` | 桩 |
| 1 | 断开发信服务器 | `DisconnectSmtpServer` | 1 | `_SDT_NULL` | 空函数 |
| 2 | 添加附件文件 | `AttachFile` | 1 | `SDT_BOOL` | 桩 |
| 3 | 添加附件数据 | `AttachData` | 1 | `SDT_BOOL` | 桩 |
| 4 | 清除所有附件 | `EmptyAttachment` | 1 | `_SDT_NULL` | 空函数 |
| 5 | 发送邮件 | `SendMail` | 1 | `SDT_TEXT` | 桩 |
| 6 | 置代理服务器 | `SetProxyName` | 2 HTTP及FTP操作 | `_SDT_NULL` | 桩 |
| 7 | HTTP读文件 | `GetHttpFile` | 2 | `SDT_BIN` | 桩 |
| 8 | 连接FTP服务器 | `ConnectFTPServer` | 2 | `SDT_BOOL` | 桩 |
| 9 | 断开FTP服务器 | `DisconnectFTPServer` | 2 | `_SDT_NULL` | 空函数 |
| 10 | FTP文件下载 | `GetFtpFile` | 2 | `SDT_BOOL` | 桩 |
| 11 | FTP文件上传 | `PutFtpFile` | 2 | `SDT_BOOL` | 桩 |
| 12 | FTP删除文件 | `DeleteFtpFile` | 2 | `SDT_BOOL` | 桩 |
| 13 | FTP文件改名 | `RenameFtpFile` | 2 | `SDT_BOOL` | 桩 |
| 14 | FTP创建目录 | `CreateFtpDir` | 2 | `SDT_BOOL` | 桩 |
| 15 | FTP删除目录 | `RemoveFtpDir` | 2 | `SDT_BOOL` | 桩 |
| 16 | FTP置现行目录 | `SetCurrentFtpDir` | 2 | `SDT_BOOL` | 桩 |
| 17 | FTP取现行目录 | `GetCurrentFtpDir` | 2 | `SDT_TEXT` | 空函数 |
| 18 | FTP目录列表 | `ListFtpDir` | 2 | `SDT_INT` | 桩 |
| 19 | 取拨号连接数 | `GetEntriesCount` | 3 拨号上网 | `SDT_INT` | 空函数 |
| 20 | 取连接名称 | `GetEntryName` | 3 | `SDT_TEXT` | 桩 |
| 21 | 取用户帐号 | `GetUserNameW` | 3 | `SDT_TEXT` | 桩；登记时特判为 W 名称 |
| 22 | 拨号 | `RasDial` | 3 | `SDT_BOOL` | 桩 |
| 23 | 是否已在线 | `IsOnline` | 3 | `SDT_BOOL` | 空函数 |
| 24 | 挂断 | `RasHangUp` | 3 | `_SDT_NULL` | 空函数 |

命令元数据的参数默认值和传址语义集中在 `internet_cmdInfo.cpp`：SMTP 端口/账号/密码/等待时间，FTP 用户名/密码/端口/被动模式，文件列表的数组输出参数，以及 `RasDial` 的状态标签 `DTP_LABEL` 均已描述；这些描述不能替代执行实现。

## 5. 数据模型与状态

### 5.1 支持库登记模型

`internet_dllMain.cpp` 静态创建一个 `LIB_INFO g_LibInfo_internet_global_var`，关键字段为：

- `m_dwLibFormatVer = LIB_FORMAT_VER`；
- GUID `707ca37322474f6ca841f0e224f4b620`；
- 版本 `2.0.0`；
- 需要易语言系统 `3.0`、核心支持库 `3.0`；
- 支持语言 `__GBK_LANG_VER`；
- 支持系统 `_LIB_OS(OS_ALL)`，但工程和头文件实际明显依赖 Windows；
- 3 个命令分类、25 个命令、0 个自定义数据类型、0 个常量；
- `m_pfnNotify = internet_ProcessNotifyLib_internet`；
- 无 AddIn、SuperTemplate、额外依赖文件声明。

`GetNewInf()` 返回上述结构地址，并把第 21 个命令的英文名改为 `GetUserName`。动态命令函数名数组则把第 21 项改为 `GetUserNameW`，这是源码明确存在的 A/W 名称兼容特判。

### 5.2 命令调用数据

`PFN_EXECUTE_CMD` 统一签名为：

```cpp
void (*)(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)
```

`MDATA_INF` 是易语言数据交换单元，包含 `m_dtDataType` 以及数值、文本、字节集、复合数据、数组、变量地址等 union 视图。当前 `internet_cmdDef.cpp` 只把 `pArgInf` 转成 `LPSTR`、`INT`、`BOOL`、`LPBYTE`、`void**` 或 `void*` 局部变量，没有实际使用 `pRetData`。因此当前没有可确认的邮件附件状态、SMTP 会话、FTP 会话、代理配置、拨号句柄或结果缓存模型。

### 5.3 通知/生命周期状态

`elib/fnshare.cpp` 维护三个进程内静态状态：

- `s_pfnNotifySys`：易语言系统通知函数指针；
- `s_pfnuserNotifySys`：上层用户设置的通知回调；
- `s_isDebug`：初值 `1253600`，首次收到 `NL_SYS_NOTIFY_FUNCTION` 后调用 `NRS_GET_PRG_TYPE` 更新。

`ProcessNotifyLib` 会保存系统回调，处理框架级通知并最终转发用户回调；当前没有资源释放、网络连接和失败恢复状态机。

### 5.4 持久化

未发现数据库、配置文件、缓存文件、序列化存储或外部持久化实现。所有已确认状态均为静态/进程内状态或调用参数。

## 6. 关键调用链与接口边界

### 6.1 动态库装载

```text
系统 LoadLibrary
  → DLL 导出 GetNewInf（Source_internet.def）
  → 返回 PLIB_INFO
  → 读取 g_cmdInfo_internet_global_var 与 g_cmdInfo_internet_global_var_fun
  → 按命令索引调用 internet_<命令>_<索引>_internet
```

`Source_internet.def` 只导出 `GetNewInf`；命令实现函数通过 C 链接和宏命名供表内函数指针使用，不是该 `.def` 文件的直接导出接口。

### 6.2 系统通知

```text
系统 → internet_ProcessNotifyLib_internet
     → NL_SYS_NOTIFY_FUNCTION：ProcessNotifyLib(...)
         → 保存 PFN_NOTIFY_SYS
         → NRS_GET_PRG_TYPE
         → 更新 s_isDebug
         → 转发 s_pfnuserNotifySys
     → NL_GET_CMD_FUNC_NAMES：返回命令名数组
     → NL_GET_NOTIFY_LIB_FUNC_NAME：返回自身函数名文本
     → NL_GET_DEPENDENT_LIBS：返回 "\0\0"
     → 其他已列分支：当前不做资源操作，返回 NR_OK
```

动态模式下 `internet_dllMain.cpp` 明确处理 `NL_GET_CMD_FUNC_NAMES`、`NL_GET_NOTIFY_LIB_FUNC_NAME`、`NL_GET_DEPENDENT_LIBS`；静态库模式下则由 `ProcessNotifyLib` 作为通用通知框架承接，但静态调用链没有仓库内示例验证。

### 6.3 静态命名

`lib2.h` 与 `internet_cmd_typedef.h` 通过 `__E_FNENAME=internet` 生成类似 `internet_ConnectSmtpServer_0_internet` 的唯一符号。`__E_STATIC_LIB` 会关闭动态登记数组并启用静态命名路径。静态工程 Win32 配置显式定义了这两个宏；其 x64 配置未显式定义，见风险章节。

## 7. 工程、依赖与构建边界

| 项目 | 配置 | 工程声明 |
|---|---|---|
| `internet.vcxproj` | Debug/Release Win32 | `DynamicLibrary`，工具集 `v141`，目标 SDK `10.0.15063.0`，Win32 `TargetExt=.fne`，链接 `Source_internet.def` |
| `internet.vcxproj` | Debug/Release x64 | `DynamicLibrary`，工具集 `v141`；未设置 `TargetExt` 和 `ModuleDefinitionFile` |
| `internet_static/internet_static.vcxproj` | Debug/Release Win32 | `StaticLibrary`，工具集 `v141`，显式 `__E_STATIC_LIB;__E_FNENAME=internet` |
| `internet_static/internet_static.vcxproj` | Debug/Release x64 | `StaticLibrary`；预处理宏缺少 `__E_STATIC_LIB` 和 `__E_FNENAME=internet` |

已确认依赖边界：

1. C++/Visual Studio MSBuild 工程，未声明第三方包管理依赖。
2. `elib/lang.h` 直接包含 `<windows.h>`；`fnshare.h` 使用 `lstrlenA`、Windows 内存通知和 `wchar_t`；`untshare.h` 使用窗口样式、字体和句柄 API。
3. `internet_cmdDef.cpp` 当前没有实际链接 SMTP/WinINet/FTP/RAS API 的代码，因此不能据此宣称存在相应系统库链接。
4. `mtypes.h` 虽定义了部分 Windows 类型兼容别名，但不能消除 `windows.h` 和 Windows API 依赖。
5. `internet.vcxproj.user` 与静态对应文件均只有空 `PropertyGroup`，没有本地调试/运行配置。

## 8. 测试与验证现状

### 已完成的静态取证

- 人工读取全部 23 个 Git 跟踪文件中的工程、入口、命令元数据、命令实现、ABI 头和辅助层。
- 核对 `INTERNET_DEF` 的索引连续性：0–24，共 25 条命令。
- 核对参数元数据：`internet_cmdInfo.cpp` 中 46 个参数条目，命令偏移覆盖到拨号参数。
- 核对动态/静态项目都复用同一批 `internet_*` 与 `elib/*` 源码。
- 核对 DLL 导出表仅包含 `GetNewInf`。
- 核对工作树原始状态干净，远程 `origin/master` 与本地 `HEAD` 同为 `9f118dbbe83d6569b...`。

### 未完成/不可声称通过的验证

- 当前 macOS 环境未发现 `msbuild`、`xbuild`、`cl` 或 `devenv`，未执行 Windows 编译。
- 未装载 `.fne`、未在易语言 IDE/运行时中调用 `GetNewInf`。
- 未执行 SMTP、HTTP、FTP、拨号和代理端到端测试。
- 未验证命令 ABI 的返回值约定、数组写回、文本/字节集内存释放和线程安全。
- 未验证 x64 工程配置能否通过预处理、链接和导出检查。
- 仓库是浅克隆（`git rev-parse --is-shallow-repository` 返回 `true`），无法据此确认更早历史。

## 9. 风险、未确认项与后续复核点

1. **核心功能缺失风险（已由源码确认）：** 25 个命令没有业务执行逻辑；优先补齐返回值、错误文本、连接句柄、附件容器和资源释放，再谈网络兼容性。
2. **x64 工程宏风险（工程静态证据）：** 动态库和静态库的 x64 配置没有像 Win32 一样定义 `__E_FNENAME=internet`；`lib2.h` 对未定义 `__E_FNENAME` 有 `#error`，静态 x64 还缺少 `__E_STATIC_LIB`。需在 Windows/VS 中实际验证并由维护者决定是否修工程；当前核对不修改工程文件。
3. **x64 DLL 导出风险（工程静态证据）：** 动态库 x64 配置未设置 `TargetExt=.fne` 和 `ModuleDefinitionFile`，是否符合易语言支持库装载约定待验证。
4. **平台声明不一致：** `LIB_INFO` 声明 `OS_ALL`，而源码直接依赖 Windows；应在后续版本裁决真实支持平台，不能以 `OS_ALL` 作为运行能力证据。
5. **ABI/内存风险：** `MDATA_INF` 的文本、字节集、数组和变量地址有严格所有权规则；目前未实现写回，后续实现必须配套 `ealloc/efree`、`NRS_FREE_ARY` 和错误路径测试。
6. **通知资源风险：** `NL_FREE_LIB_DATA`、卸载和延迟释放分支当前为空；如果后续加入连接/附件状态，必须定义释放时机和重复通知行为。
7. **安全风险待核：** SMTP/FTP 凭据、代理凭据、证书/TLS、被动模式、超时、重定向和错误信息脱敏均没有实现或测试证据。
8. **版本新鲜度：** 当前本地与 `origin/master` 的可见提交一致，但仓库为浅克隆；需后续 fetch/复核完整历史和远端新增提交。

## 10. Git 基线

- 仓库：`Gitee_精易官方/internet`
- 远程：`https://gitee.com/JYtechnology/internet.git`
- 分支：`master`，跟踪 `origin/master`
- `HEAD`：`9f118dbbe83d6569b06e13644d5f32b34629a8db`
- 提交：`初始化仓库`
- 作者：`精易科技 <413188828@qq.com>`
- 提交时间：`2022-12-19 16:56:04 +08:00`
- 现场远程核对：`git ls-remote origin HEAD refs/heads/master` 返回同一 SHA
- 初始提交统计：23 个文件，4409 行新增（工作树在新增本架构文档前无改动）
- 当前核对边界：只新增/更新根目录 `ARCHITECTURE.md`，不修改源码、工程、依赖、测试、配置或 Git 历史。

## 11. 证据路径索引

- 命令总表和符号命名：`internet_cmd_typedef.h`、`include_internet_header.h`
- 参数默认值、参数类型、数组/传址标志：`internet_cmdInfo.cpp`
- 25 个执行入口及当前桩体：`internet_cmdDef.cpp`
- DLL 入口、`LIB_INFO`、动态函数表、通知分支：`internet_dllMain.cpp`
- 自定义数据类型与常量空表：`internet_dtType.cpp`、`internet_const.cpp`
- DLL 导出边界：`Source_internet.def`
- ABI 结构、通知码、静态命名和内存数据格式：`elib/lib2.h`、`elib/krnllib.h`、`elib/mtypes.h`、`elib/lang.h`
- 通知和易语言内存/数组辅助：`elib/fnshare.h`、`elib/fnshare.cpp`
- 组件/属性通用辅助（当前网络命令未使用）：`elib/untshare.h`
- IDE 功能号定义（当前未调用）：`elib/PublicIDEFunctions.h`
- 动态库工程：`internet.vcxproj`、`internet.vcxproj.filters`、`internet.vcxproj.user`
- 静态库工程：`internet_static/internet_static.vcxproj`、`internet_static/internet_static.vcxproj.filters`、`internet_static/internet_static.vcxproj.user`
- 解决方案与项目组合：`internet.sln`
- 版本和完整性：`.git/HEAD`、`git status --short --branch`、`git log -1`、`git ls-remote origin HEAD refs/heads/master`

> 后续细探应继续增量维护本文件，重点先验证 Windows 构建/装载，再为每个网络命令建立“输入 → 系统 API → 状态/输出 → 释放”的真实调用链；不要把当前命令元数据当作已完成的网络能力。
