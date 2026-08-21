# einterprocess 架构建档

## 1. 项目定位

einterprocess 是 Gitee `JYtechnology/einterprocess` 仓库中的易语言 Windows 进程通讯支持库源码。它以易语言支持库（`.fne` 动态库）/静态库的 ABI 为外壳，向易语言暴露三组进程间通信数据类型与命令元数据：命名管道、Windows 邮槽、内存映射文件。

需要特别区分：当前仓库是“支持库接口与代码生成骨架”，不是已经完成 Windows IPC 调用的实现。`einterprocess_cmdDef.cpp` 中 26 个命令函数均只完成参数读取或空函数体，未见 `CreateNamedPipe`、`ReadFile`、`WriteFile`、`CreateMailslot`、`MapViewOfFile` 等 Windows API 的实际调用。因此，下面的“协议/能力”主要是源码中登记给易语言 IDE 的命令契约和注释，不应当当作已可运行的 IPC 实现。

## 2. 真实架构流程图

```text
易语言 IDE / 编译器
        │ 通过支持库格式加载 GetNewInf()
        ▼
einterprocess.dll（动态支持库，目标扩展名 Win32 Debug/Release 为 .fne）
        │
        ├─ LIB_INFO：库身份、版本、OS、类别、命令表、数据类型表、通知函数
        ├─ CMD_INFO[]：26 个命令的中文名、英文符号、返回类型、参数范围
        ├─ PFN_EXECUTE_CMD[]：命令实现函数指针表
        └─ LIB_DATA_TYPE_INFO[]：3 个对象数据类型及成员命令索引
                │
                ├─ 全局命令 0..6：命名管道
                ├─ 邮槽服务器对象：命令 7..11，隐藏构造/析构 + 创建/读/关
                ├─ 邮槽客户机对象：命令 12..16，隐藏构造/析构 + 创建/写/关
                └─ 内存映射文件对象：命令 17..25，隐藏构造/析构 + 创建/打开/映射/读写/关闭
                        │
                        └─ 当前源码中的命令函数只解析 PMDATA_INF 参数，未执行 Windows IPC API

易语言系统通知
        │ NL_SYS_NOTIFY_FUNCTION / NL_FREE_LIB_DATA / 其他 NL_* 消息
        ▼
einterprocess_ProcessNotifyLib_einterprocess()
        │
        ├─ 向 fnshare.cpp::ProcessNotifyLib() 转发系统通知
        └─ NL_GET_CMD_FUNC_NAMES / NL_GET_NOTIFY_LIB_FUNC_NAME /
           NL_GET_DEPENDENT_LIBS 为静态编译提供符号名和依赖列表

elib 适配层
        ├─ lib2.h：易语言支持库 ABI、类型、元数据、通知常量
        ├─ fnshare.h/.cpp：内存/数组/字节集辅助、系统通知转发、调试版本查询
        ├─ lang.h：语言版本宏
        ├─ krnllib.h：系统核心支持库接口声明
        ├─ mtypes.h：Windows 基础类型补充
        ├─ untshare.h：组件/单位共享定义
        └─ PublicIDEFunctions.h：IDE 辅助功能常量与结构
```

## 3. 目录与文件地图

仓库当前 Git 树包含 23 个文件（不含本架构文档）：

```text
einterprocess/
├── einterprocess.sln                         Visual Studio 解决方案
├── einterprocess.vcxproj                     动态支持库工程
├── einterprocess.vcxproj.filters             动态工程筛选器
├── einterprocess.vcxproj.user                VS 用户工程设置
├── einterprocess_static/
│   ├── einterprocess_static.vcxproj          静态库工程，复用根目录源码
│   ├── einterprocess_static.vcxproj.filters  静态工程筛选器
│   └── einterprocess_static.vcxproj.user     VS 用户工程设置
├── Source_einterprocess.def                  DLL 导出定义，仅导出 GetNewInf
├── include_einterprocess_header.h            对外聚合头、元数据声明、命令函数声明
├── einterprocess_cmd_typedef.h               26 条命令的 X-macro 总定义
├── einterprocess_cmdDef.cpp                  26 个命令实现函数骨架
├── einterprocess_cmdInfo.cpp                 参数表与 CMD_INFO 命令元数据
├── einterprocess_dtType.cpp                  3 个自定义数据类型及对象成员映射
├── einterprocess_const.cpp                   常量表，占位为空
├── einterprocess_dllMain.cpp                 DLL 入口、LIB_INFO、通知函数、符号名
└── elib/
    ├── lib2.h                                易语言支持库 ABI 主定义
    ├── fnshare.h / fnshare.cpp               支持库通用辅助与通知桥接
    ├── lang.h                                语言版本定义
    ├── krnllib.h                             系统核心支持库声明
    ├── mtypes.h                              基础类型定义
    ├── untshare.h                            单位/组件共享定义
    └── PublicIDEFunctions.h                  IDE 功能消息和参数定义
```

动态工程 `einterprocess.vcxproj` 编译 `elib/fnshare.cpp` 与根目录 5 个 `.cpp`；静态工程通过 `..\` 路径复用同一批源码。两种工程均配置 Debug/Release 与 Win32/x64；动态工程的 Win32 配置设置 `TargetExt=.fne`，x64 配置没有同样的 `TargetExt` 覆盖，实际产物扩展名需在 Windows/Visual Studio 环境进一步核实。

## 4. 支持库宿主与 ABI 边界

### 4.1 动态库导出

`Source_einterprocess.def` 内容只有：

```text
LIBRARY

EXPORTS
    GetNewInf
```

`einterprocess_dllMain.cpp::GetNewInf()` 返回 `PLIB_INFO`，这是易语言加载本支持库的固定入口。`LIB_INFO` 来自 `elib/lib2.h`，当前登记值为：

| 字段 | 源码值 |
|---|---|
| `m_dwLibFormatVer` | `LIB_FORMAT_VER`（`20000101`） |
| `m_szGuid` | `FC8D8B0C3B5A44e78572B3FED401E9CA` |
| 版本 | `2.0.0` |
| 所需易语言系统 | `3.8` |
| 所需核心支持库 | `3.8` |
| 名称 | `进程通讯支持库` |
| 语言 | `__GBK_LANG_VER` |
| 说明 | `提供进程之间通讯的几种方式` |
| OS 状态 | `_LIB_OS(__OS_WIN)`，仅 Windows |
| 数据类型数 | `g_DataType_einterprocess_global_var_count`，3 个 |
| 全局类别数 | 1，字符串为 `0000命名管道` |
| 命令数 | `g_cmdInfo_einterprocess_global_var_count`，26 个 |
| 通知入口 | `einterprocess_ProcessNotifyLib_einterprocess` |
| 预定义常量数 | 0 |
| 依赖文件 | `NULL`；通知查询时返回空依赖列表 `"\0\0"` |

### 4.2 命令符号与 X-macro

`einterprocess_cmd_typedef.h` 用 `EINTERPROCESS_DEF(_MAKE)` 作为单一命令清单。相同清单被多次展开生成：

1. `include_einterprocess_header.h` 中的命令函数声明；
2. `einterprocess_cmdInfo.cpp` 中的 `CMD_INFO[]`；
3. `einterprocess_dllMain.cpp` 中的 `PFN_EXECUTE_CMD[]`；
4. 静态编译使用的命令名数组。

函数名由 `EINTERPROCESS_NAME(_index, _name)` 拼接支持库名、英文名、序号和库名。例如命令 0 的符号是 `einterprocess_CreateNamedPipeW_0_einterprocess`。`GetNewInf()` 又把命令 0 的元数据英文名改成 `CreateNamedPipe`，以回避宏导致的 A/W 名称问题；通知 `NL_GET_CMD_FUNC_NAMES` 时则显式返回 `CreateNamedPipeW` 版本符号。

### 4.3 命令执行 ABI

每个命令函数原型均为：

```cpp
void(PFN_EXECUTE_CMD)(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf);
```

`PMDATA_INF` 指向 `MDATA_INF`。`MDATA_INF` 采用 1 字节对齐，主体是一个同时承载数值、文本、字节集、复合数据、数组数据以及变量地址指针的 union，尾部为 `DATA_TYPE m_dtDataType`。输出字节集使用 `m_ppBin`，输入字节集使用 `m_pBin`；需要引用变量的参数在 `ARG_INFO.m_dwState` 中设置 `AS_RECEIVE_VAR`。

## 5. IPC 能力与命令模型

### 5.1 命名管道：全局命令 0..6

命令类别为 `命名管道`，所有命令设置 `_CMD_OS(__OS_WIN)`，面向句柄/名称/二进制数据：

| 索引 | 英文符号 | 返回 | 参数契约（按源码元数据） |
|---:|---|---|---|
| 0 | `CreateNamedPipeW` | `SDT_INT` | 名称 `SDT_TEXT`；注释称返回命名管道句柄，失败为 0 |
| 1 | `ListenNamedPipe` | `SDT_BOOL` | 命名管道句柄 `SDT_INT`；等待客户连接，可能阻塞 |
| 2 | `ConnectNamedPipe` | `SDT_INT` | 管道名称 `SDT_TEXT`、超时时间 `SDT_INT`；`-1` 表示无限等待，单位毫秒 |
| 3 | `ReadNamedPipe` | `SDT_BOOL` | 句柄 `SDT_INT`、引用字节集 `&数据 SDT_BIN` |
| 4 | `WriteNamedPipe` | `SDT_INT` | 句柄 `SDT_INT`、字节集 `SDT_BIN`；注释称返回实际写入字节数 |
| 5 | `DisConnectNamedPipe` | `_SDT_NULL` | 已连接管道句柄 `SDT_INT` |
| 6 | `ReleaseNamedPipe` | `_SDT_NULL` | 已创建管道句柄 `SDT_INT`；注释要求等待监听结束后再关闭 |

源码只登记了上述语义；`cmdDef.cpp` 对这些参数的读取也不完整地对应了实现所需变量，函数体没有进行句柄创建、连接、读写、断开或释放。

### 5.2 邮槽服务器对象：`MailslotServer`

`einterprocess_dtType.cpp` 将对象成员命令索引设置为 `[7, 8, 9, 10, 11]`，隐藏字段成员为 `SDT_INT` 的“邮槽服务器句柄”。

| 索引 | 英文符号 | 标志/返回 | 参数契约 |
|---:|---|---|---|
| 7 | `ConstructorServer` | 隐藏构造，无返回 | 无参数 |
| 8 | `DestructorServer` | 隐藏析构，无返回 | 无参数 |
| 9 | `CreateMailslotServer` | `SDT_BOOL` | 邮槽名称 `SDT_TEXT` |
| 10 | `rDataFromServer` | `SDT_BOOL` | 引用字节集 `&数据 SDT_BIN` |
| 11 | `CloseMailslotServer` | `_SDT_NULL` | 无参数 |

注释明确邮槽服务器负责创建、读取和关闭；Windows 邮槽本身是单向、不可靠的消息通信模型。当前仓库没有服务器句柄的实际创建、读出或关闭逻辑。

### 5.3 邮槽客户机对象：`MailslotClient`

成员命令索引为 `[12, 13, 14, 15, 16]`，隐藏字段成员为 `SDT_INT` 的“邮槽客户机句柄”。

| 索引 | 英文符号 | 标志/返回 | 参数契约 |
|---:|---|---|---|
| 12 | `ConstructorClient` | 隐藏构造，无返回 | 无参数 |
| 13 | `DestructorClient` | 隐藏析构，无返回 | 无参数 |
| 14 | `CreateMailslotClient` | `SDT_BOOL` | 服务器名称 `SDT_TEXT`、邮槽名称 `SDT_TEXT` |
| 15 | `wDataToClient` | `SDT_BOOL` | 字节集 `SDT_BIN`，注释限制长度小于 424 字节 |
| 16 | `CloseMailslotClient` | `_SDT_NULL` | 无参数 |

源码注释描述服务器名称可以是本机 `.`、域名或 `*` 广播范围；这些都是命令帮助文本层面的契约，未在实现中落地。

### 5.4 内存映射文件对象：`MapFile`

成员命令索引为 `[17, 18, 19, 20, 21, 22, 23, 24, 25]`，隐藏字段成员为 `SDT_INT` 的“映射文件指针”。

| 索引 | 英文符号 | 标志/返回 | 参数契约 |
|---:|---|---|---|
| 17 | `MapConstructor` | 隐藏构造，无返回 | 无参数 |
| 18 | `MapDestructor` | 隐藏析构，无返回 | 无参数 |
| 19 | `CreateMapFile` | `SDT_BOOL` | 文件名 `SDT_TEXT`、是否创建 `SDT_BOOL`、大小 `SDT_INT64`、可空名称 `SDT_TEXT` |
| 20 | `OpenMapFile` | `SDT_BOOL` | 映射文件名称 `SDT_TEXT` |
| 21 | `MapToMemory` | `SDT_BOOL` | 起始位置 `SDT_INT64`、大小 `SDT_INT` |
| 22 | `ReadMapFile` | `SDT_BOOL` | 起始位置 `SDT_INT64`、长度 `SDT_INT`、引用字节集 `&数据 SDT_BIN` |
| 23 | `WriteMapFile` | `SDT_BOOL` | 起始位置 `SDT_INT64`、字节集 `SDT_BIN` |
| 24 | `UnMapToMemory` | `SDT_BOOL` | 无参数 |
| 25 | `CloseMapFile` | `_SDT_NULL` | 无参数 |

帮助文本强调映射起始位置须符合 Windows 内存分配粒度（注释写为 64K 的倍数），读写不能越过映射文件边界，否则可能发生非法内存访问。当前源码没有文件句柄、映射句柄、视图地址或边界检查的实现。

## 6. 数据模型与内存管理

### 6.1 易语言元数据模型

- `ARG_INFO[]`：参数中文名、说明、位图信息、`DATA_TYPE`、默认值和参数接收标志。
- `CMD_INFO[]`：命令中文/英文名、解释、全局类别（对象成员使用 `-1`）、状态位、返回数据类型和参数表起点。
- `LIB_DATA_TYPE_INFO[]`：对象中文/英文名、成员命令索引、OS 状态和隐藏成员字段。
- `LIB_DATA_TYPE_ELEMENT[]`：对象内部字段。三个对象均只有一个隐藏 `SDT_INT` 字段，用于承载句柄/指针语义。
- `LIB_CONST_INFO[]`：当前为空表，计数为 0。

### 6.2 字节集/数组约定

`elib/fnshare.h` 里的辅助函数反映易语言运行时数据布局：

- `GetAryElementInf()` 读取数组维数和各维成员数，返回数据区首地址；
- `CloneBinData()` 创建“1 维数组 + 长度 + 数据区”的易语言字节集；
- `GetBinData()` 从易语言字节集取出数据并额外保留两个字节的结束空间；
- `ealloc()`/`efree()` 通过 `NotifySys(NRS_MALLOC/NRS_MFREE, ...)` 使用易语言系统内存管理；
- `AS_RECEIVE_VAR` 参数必须接收变量地址，读命名管道、邮槽服务器读、映射文件读的输出字节集均使用该约束。

这些辅助函数只是运行时适配基础，不能证明 IPC 命令已经调用了底层 API。尤其是 `einterprocess_cmdDef.cpp` 当前没有看到调用 `CloneBinData()`、`GetBinData()`、`ealloc()` 或释放句柄的代码。

## 7. DLL 生命周期与系统通知

`DllMain()` 仅保留标准 `DLL_PROCESS_ATTACH`、`DLL_PROCESS_DETACH`、`DLL_THREAD_ATTACH`、`DLL_THREAD_DETACH` 分支，分支体为空并直接返回 `TRUE`。

`einterprocess_ProcessNotifyLib_einterprocess()` 处理：

1. `NL_GET_CMD_FUNC_NAMES`：返回与 26 条命令一一对应的函数名数组，并修正命令 0 为 `CreateNamedPipeW`；
2. `NL_GET_NOTIFY_LIB_FUNC_NAME`：返回通知函数符号 `einterprocess_ProcessNotifyLib_einterprocess`；
3. `NL_GET_DEPENDENT_LIBS`：返回空的双零终止依赖列表；
4. `NL_SYS_NOTIFY_FUNCTION`：调用 `ProcessNotifyLib()`，把系统通知函数指针交给 `fnshare.cpp` 保存；
5. `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NR_DELAY_FREE`、`NL_IDE_READY`、`NL_RIGHT_POPUP_MENU_SHOW`、`NL_ADD_NEW_ELEMENT`：当前为空处理；
6. 未知消息：返回 `NR_ERR`。

`fnshare.cpp::ProcessNotifyLib()` 保存 `PFN_NOTIFY_SYS`，首次收到系统通知时调用 `NRS_GET_PRG_TYPE` 查询调试/编译版本，并在最后转调用户通过 `SetUserSysNotify()` 设置的回调。它不负责 IPC 资源生命周期。

## 8. 构建工程与依赖边界（仅静态读取，未构建）

| 工程 | 类型 | 配置 | 主要宏/目标 |
|---|---|---|---|
| `einterprocess.vcxproj` | `DynamicLibrary` | Debug/Release，Win32/x64 | Win32 定义 `__E_FNENAME=einterprocess`、`EINTERPROCESS_EXPORTS`；Win32 目标扩展名 `.fne` |
| `einterprocess_static/einterprocess_static.vcxproj` | `StaticLibrary` | Debug/Release，Win32/x64 | Win32 定义 `__E_STATIC_LIB`、`__E_FNENAME=einterprocess` |

工程使用 Visual Studio C++ 项目格式，`VCProjectVersion=16.0`，Windows SDK `10.0.15063.0`，Platform Toolset `v141`。解决方案显示为 Visual Studio 17 格式，包含动态和静态两个项目，并将 x86 映射到项目的 Win32 配置。

直接源码依赖为 `elib` 内的易语言支持库 SDK 头文件；`.def` 只导出 `GetNewInf`。`LIB_INFO.m_szzDependFiles` 与 `NL_GET_DEPENDENT_LIBS` 均未声明第三方静态库，Windows 系统库依赖由工程/系统链接环境隐式提供。没有 `README`、测试工程、CI 配置、包管理文件或运行时配置文件。

## 9. 版本、远程与仓库状态

- 远程：`https://gitee.com/JYtechnology/einterprocess.git`
- 当前分支：`master`
- 本地 `HEAD`：`85aa4db32d4870b83c92a16cf22f9f753c8f3bf3`
- `origin/master`：同为 `85aa4db32d4870b83c92a16cf22f9f753c8f3bf3`
- 提交时间：`2022-12-19T16:55:11+08:00`
- 提交说明：`初始化仓库`
- 仓库为浅克隆（Git 存在 `.git/shallow`），当前可见历史只有上述初始化提交。
- 本轮未执行 `fetch`、构建、运行、安装依赖或提交；远程“最新”仅能确认到本地已有 `origin/master` 引用，未作网络刷新。

## 10. 测试与验证状态

仓库未发现测试目录、测试源文件、CI 工作流或可执行示例。本轮按只读架构建档要求：

- 已读取解决方案、动态/静态工程、导出定义、命令总定义、命令函数、命令元数据、数据类型、DLL 通知入口及 `elib` ABI/辅助层；
- 已核对 Git 远程、分支、提交和工作树基线；
- 未运行 Visual Studio/MSBuild，未在 macOS 上尝试编译 Windows 工程；
- 未加载 DLL，未调用易语言 IDE，未进行跨进程通信实测；
- 因此不能声明构建通过、DLL 可加载、命令可用或 IPC 协议互通。

## 11. 风险、缺口与后续复核点

1. **核心实现缺失**：26 个 `PFN_EXECUTE_CMD` 函数目前是骨架，命令登记与实际功能不一致；这是最高优先级缺口。
2. **参数下标异常风险**：部分 `cmdDef.cpp` 函数从 `pArgInf[1]` 或更高下标读取第一个参数（例如邮槽和映射文件命令），而 `ARG_INFO`/命令定义按 0 起始数组组织；若不是生成器约定，则存在越界或错读风险，需要在 Windows 易语言运行时验证。
3. **句柄模型未落地**：对象字段登记为 `SDT_INT`，但 Windows 句柄/映射视图在 64 位环境可能需要指针宽度和生命周期策略；x64 工程虽存在，但源码未提供兼容性证明。
4. **同步与阻塞未实现**：命名管道监听、连接超时、读写完成、邮槽阻塞读取、映射视图并发访问均没有实现或错误处理代码。
5. **边界/资源释放未实现**：字节集长度、映射边界、句柄关闭、视图解除映射、异常路径释放都未覆盖。
6. **协议并非独立线协议**：源码没有自定义消息帧、序列化、认证、重试或版本协商；它只是把 Windows IPC 原语包装成易语言命令。后续若补实现，应分别定义每个原语的同步/错误/生命周期契约，而不是抽象成当前未存在的统一协议。
7. **旧细探未发现**：目标根目录未发现 `细探-*.md`，因此本轮没有可吸收的旧细探内容；后续若出现旧文档，必须逐条回对源码后仍只更新本文件。
8. **工具索引限制**：目标目录没有 `.codegraph/`，`codegraph_explore` 无法建立符号索引；本轮改用只读文件、脚本解码和 Git 查询完成取证，未对源码建立索引。

## 12. 证据路径索引

- `einterprocess_cmd_typedef.h`：命令总表、命令索引、返回类型、OS/隐藏/构造析构标志。
- `einterprocess_cmdInfo.cpp`：参数名称、类型、引用标志、默认值和命令表展开。
- `einterprocess_cmdDef.cpp`：26 个命令函数骨架及帮助注释；当前实现缺失的直接证据。
- `einterprocess_dtType.cpp`：`MailslotServer`、`MailslotClient`、`MapFile` 数据类型、隐藏字段和成员命令索引。
- `einterprocess_dllMain.cpp`：`DllMain`、`LIB_INFO`、`GetNewInf`、通知函数和静态符号名。
- `include_einterprocess_header.h`：元数据外部声明、X-macro 命令函数声明。
- `elib/lib2.h`：`ARG_INFO`、`CMD_INFO`、`LIB_DATA_TYPE_INFO`、`MDATA_INF`、`PFN_EXECUTE_CMD`、`LIB_INFO` ABI。
- `elib/fnshare.h` / `elib/fnshare.cpp`：系统通知桥接、易语言内存/字节集/数组辅助。
- `einterprocess.vcxproj`：动态库源文件、Win32/x64 配置、`.fne` 目标设置。
- `einterprocess_static/einterprocess_static.vcxproj`：静态库配置及复用根目录源码关系。
- `Source_einterprocess.def`：DLL 唯一导出 `GetNewInf`。
- Git 元数据：远程、分支与版本基线由本地 `.git/config`、refs 和 `git log` 核对。

本文件是本项目首轮架构事实源；后续细探只增量维护此文件，不另建平行架构报告。
