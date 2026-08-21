# exmlrpc 架构档案

## 1. 项目定位

`exmlrpc` 是 Gitee `JYtechnology/exmlrpc` 仓库中的易语言支持库源码，目标定位为“远程服务支持库”：向易语言 IDE 暴露服务器端 `ERPCServer` 与客户端 `ERPCClient` 两个对象，以及启动/连接、文本/字节集请求、同步/异步收发、回调通知等命令。

**重要边界：** 当前仓库的可见源码是支持库适配层、命令元数据和 Visual Studio 工程骨架；`exmlrpc_cmdDef.cpp` 中 29 个命令实现函数均只解析局部参数，未见网络收发、XML 编解码、线程池、状态对象或返回值写回。因此“XML-RPC/远程服务”的运行时实现并不在本仓库当前可见源码中，不能据此宣称已有可运行协议栈。

## 2. 版本与仓库身份

| 项目 | 事实 |
|---|---|
| 本地根目录 | `/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/exmlrpc` |
| Git 远程 | `https://gitee.com/JYtechnology/exmlrpc.git` |
| 本地分支 | `master` |
| 本地基线提交 | `385f68de400b570fb16e22dab3aab987a62e2ba1` |
| 基线时间 | `2022-12-19T16:55:50+08:00` |
| 基线提交信息 | `初始化仓库` |
| 远程复核 | `origin/HEAD` 与 `origin/master` 均为 `385f68de400b570fb16e22dab3aab987a62e2ba1` |
| 工作树 | 现场检查无源码改动；本文件为本次新增架构文档 |
| 历史/旧细探 | 未发现 README、`细探-*.md` 或其他 Markdown 架构文档 |

## 3. 总体流程图

```text
易语言程序
    │ 调用支持库命令（对象方法 + 参数 PMDATA_INF）
    ▼
exmlrpc_cmd_typedef.h
    │ EXMLRPC_DEF(_MAKE) 统一命令表：索引、中文名、英文名、返回类型、参数区间
    ├──────────────────────┬────────────────────────┐
    ▼                      ▼                        ▼
exmlrpc_cmdInfo.cpp   exmlrpc_dtType.cpp       include_exmlrpc_header.h
命令/参数元数据        ERPCServer/ERPCClient     宏声明各命令实现
    │                  数据类型与方法索引             │
    └──────────────────┬──────────────────────────────┘
                       ▼
             exmlrpc_cmdDef.cpp
             29 个导出命令函数骨架
             （当前仅取参数，未见实际网络/XML/RPC执行）
                       │
                       ▼
             exmlrpc_dllMain.cpp
             LIB_INFO + 命令函数指针表
             + exmlrpc_ProcessNotifyLib_exmlrpc
                       │
          ┌────────────┴────────────┐
          ▼                         ▼
     动态库入口                  静态库入口
  GetNewInf / .fne          exmlrpc_static.vcxproj
          │                         │
          ▼                         ▼
       易语言运行时 / IDE ← elib/fnshare.cpp/h
                             NotifySys / ProcessNotifyLib
```

## 4. 真实目录与分层

```text
exmlrpc/
├── exmlrpc.sln                         # VS 解决方案，含动态库和静态库两个项目
├── exmlrpc.vcxproj                     # 动态库项目，目标扩展名 Win32 为 .fne
├── exmlrpc.vcxproj.filters             # VS 文件分类
├── exmlrpc.vcxproj.user                # 空用户工程配置
├── exmlrpc_static/
│   ├── exmlrpc_static.vcxproj          # 静态库项目
│   ├── exmlrpc_static.vcxproj.filters
│   └── exmlrpc_static.vcxproj.user
├── Source_exmlrpc.def                  # 动态库仅导出 GetNewInf
├── include_exmlrpc_header.h            # 支持库公共聚合头和命令声明
├── exmlrpc_cmd_typedef.h               # 单一命令定义表与符号拼接宏
├── exmlrpc_cmdDef.cpp                  # 命令实现入口（当前为骨架）
├── exmlrpc_cmdInfo.cpp                 # 参数表、命令描述表
├── exmlrpc_dtType.cpp                  # 两个自定义数据类型及方法索引
├── exmlrpc_const.cpp                   # 常量表（当前 0 个常量）
├── exmlrpc_dllMain.cpp                 # DLL 生命周期、库信息、通知入口
└── elib/
    ├── fnshare.cpp/h                   # 易语言系统通知、内存和数据辅助
    ├── lib2.h                          # 支持库 ABI、命名宏、数据类型和库结构
    ├── lang.h                          # 语言版本（GBK）
    ├── krnllib.h                       # 系统核心支持库常量与版本契约
    ├── mtypes.h                         # 非 Windows/静态场景的基础类型兼容定义
    ├── untshare.h                       # 易语言单元/组件辅助接口
    └── PublicIDEFunctions.h             # IDE 通知功能定义
```

工程文件将动态库与静态库都编译以下核心单元：`elib/fnshare.cpp`、`exmlrpc_cmdDef.cpp`、`exmlrpc_cmdInfo.cpp`、`exmlrpc_const.cpp`、`exmlrpc_dllMain.cpp`、`exmlrpc_dtType.cpp`。未发现第三方源码、包管理文件、外部库目录、测试目录或运行示例。

## 5. 核心数据模型

### 5.1 易语言支持库元数据

`exmlrpc_dllMain.cpp` 组装一个静态 `LIB_INFO g_LibInfo_exmlrpc_global_var`：

- 格式版本：`LIB_FORMAT_VER`；
- GUID：`A36CFD538657479eBD7C0D287BBB3D95`；
- 支持库版本：`2.0.0`；
- 依赖的易语言系统版本：主 `3`、次 `7`；
- 依赖的系统核心支持库版本：主 `3`、次 `7`；
- 显示名：`远程服务支持库`；
- 语言：`__GBK_LANG_VER`；
- 平台状态：`_LIB_OS(OS_ALL)`，但命令和数据类型实际均标记 `_CMD_OS(__OS_WIN)` / `_DT_OS(__OS_WIN)`；
- 命令表、命令函数指针表、数据类型表、常量表均来自本仓库静态数组；
- `m_pfnNotify` 指向 `exmlrpc_ProcessNotifyLib_exmlrpc`；
- 外部依赖文件列表为 `NULL`。

`GetNewInf()` 在 `Source_exmlrpc.def` 中作为唯一导出符号，返回上述 `LIB_INFO` 地址。

### 5.2 自定义对象

`exmlrpc_dtType.cpp` 定义两个 `LIB_DATA_TYPE_INFO`：

| 中文类型 | 英文类型 | 方法索引 | 成员/事件数据 |
|---|---|---:|---|
| 远程服务 | `ERPCServer` | 16 个：命令索引 `0..13,27,28` | `ServerDataPtr`，`SDT_INT` |
| 请求客户端 | `ERPCClient` | 13 个：命令索引 `14..26` | `ConnectFlag`（注释称已废弃）、`ClientDataPtr`，均为 `SDT_INT` |

这里的 `ServerDataPtr`、`ClientDataPtr` 只是支持库数据类型成员元数据；当前命令实现没有创建或读取对应运行时对象的代码证据。

### 5.3 命令与参数

`exmlrpc_cmd_typedef.h` 以 `EXMLRPC_DEF(_MAKE)` 作为单一事实源，定义索引 `0` 到 `28` 共 29 条命令。不同宏展开分别生成：

1. `include_exmlrpc_header.h` 中的 C 函数声明；
2. `exmlrpc_cmdInfo.cpp` 中的 `CMD_INFO` 描述；
3. `exmlrpc_dllMain.cpp` 中的函数指针表；
4. 静态编译所需的命令名字符串数组。

`exmlrpc_cmdInfo.cpp` 有 39 个参数描述项（编号 `000`–`038`），涵盖 `SDT_INT`、`SDT_BOOL`、`SDT_TEXT`、`SDT_BIN`、`SDT_SUB_PTR`、`_SDT_ALL`，以及 `AS_RECEIVE_VAR`、`AS_RECEIVE_VAR_ARRAY`、`AS_DEFAULT_VALUE_IS_EMPTY` 等引用/默认值标志。

## 6. 命令边界与声明契约

### 6.1 服务端 `ERPCServer`

| 索引 | 英文名 | 声明的用途 | 返回/关键参数 |
|---:|---|---|---|
| 0 | `CreateServer` | 构造函数（隐藏） | 无返回值 |
| 1 | `StartServer` | 启动服务并注册处理函数 | `端口号`、`处理函数`、可选串行处理标志；`SDT_BOOL` |
| 2 | `StopServer` | 停止服务 | 无返回值 |
| 3 | `SetPoolThreadNum` | 设置四个线程池的最小/最大线程数 | 两个 `SDT_INT`；`SDT_BOOL` |
| 4 | `GetRequestText` | 在处理函数中读取请求代码和文本 | 消息地址 + 两个引用文本；`SDT_BOOL` |
| 5 | `GetRequestBin` | 在处理函数中读取请求代码和字节集 | 消息地址 + 引用文本/字节集；`SDT_BOOL` |
| 6 | `SendText` | 向请求代码或客户句柄发送文本 | 目的端 + 文本；`SDT_BOOL` |
| 7 | `SendBinary` | 向请求代码或客户句柄发送字节集 | 目的端 + 字节集；`SDT_BOOL` |
| 8 | `GetClientHandle` | 由消息地址取得客户句柄 | 消息地址 + 引用整数；`SDT_BOOL` |
| 9 | `GetClientIPAddr` | 由客户句柄取得 IP | 句柄 + 引用文本；`SDT_BOOL` |
| 10 | `GetClientCount` | 取得当前客户端数 | `SDT_INT`，声明错误时为 `-1` |
| 11 | `GetAllClient` | 取得全部客户端句柄数组 | 引用数组；`SDT_BOOL` |
| 12 | `Disconnect` | 断开指定客户 | 客户句柄 |
| 13 | `ServerRelease` | 析构函数（隐藏） | 无返回值 |
| 27 | `GetMsgKind` | 读取服务端处理函数的消息类型 | 消息地址；`SDT_INT` |
| 28 | `ServerSetTimeout` | 设置网络交互超时 | 当前命令表标记隐藏，元数据声明 `SDT_BOOL` |

### 6.2 客户端 `ERPCClient`

| 索引 | 英文名 | 声明的用途 | 返回/关键参数 |
|---:|---|---|---|
| 14 | `CreateClient` | 构造函数（隐藏） | 无返回值 |
| 15 | `ClientConnect` | 连接服务器 | 端口、地址、同步/异步标志、异步处理函数；`SDT_BOOL` |
| 16 | `ClientdisConnect` | 断开服务器连接 | 无返回值 |
| 17 | `SendSynRequestText` | 同步发送文本并等待结果 | 请求文本、引用结果文本、超时毫秒；`SDT_INT`：1/0/-1 的约定写在说明中 |
| 18 | `SendSynRequestBin` | 同步发送字节集并等待结果 | 请求字节集、引用结果字节集、超时毫秒；`SDT_INT` |
| 19 | `SendAsynRequestText` | 异步发送文本 | 请求文本；`SDT_BOOL` |
| 20 | `SendAsynRequestBin` | 异步发送字节集 | 请求字节集；`SDT_BOOL` |
| 21 | `GetResultText` | 在客户端回调中读取异步文本结果 | 消息地址 + 引用文本；`SDT_BOOL` |
| 22 | `GetResultBin` | 在客户端回调中读取异步字节集结果 | 消息地址 + 引用字节集；`SDT_BOOL` |
| 23 | `ReleaseClient` | 析构函数（隐藏） | 无返回值 |
| 24 | `ClientGetMsgKind` | 在客户端回调中读取消息类型 | 消息地址；`SDT_INT` |
| 25–26 | `BeiYong` | 隐藏备用命令 | 当前无参数 |

以上是“命令元数据/注释契约”，不是已验证的运行时行为。真正实现需要 `pRetData` 写回、对象生命周期和网络/协议代码；本基线没有这些证据。

## 7. 真实调用链

### 7.1 支持库加载链

1. 易语言加载 `.fne` 动态库。
2. `Source_exmlrpc.def` 导出 `GetNewInf`。
3. `exmlrpc_dllMain.cpp::GetNewInf()` 返回 `g_LibInfo_exmlrpc_global_var`。
4. 运行时读取 `g_cmdInfo_exmlrpc_global_var`、`g_cmdInfo_exmlrpc_global_var_fun`、`g_DataType_exmlrpc_global_var` 和常量表。
5. 运行时按命令索引调用形如 `exmlrpc_StartServer_1_exmlrpc(PMDATA_INF, INT, PMDATA_INF)` 的函数。

### 7.2 命令分发链

`EXMLRPC_DEF` → `EXMLRPC_DEF_CMD` 生成函数声明 → `exmlrpc_cmdDef.cpp` 提供函数体 → `EXMLRPC_DEF_CMD_PTR` 生成函数指针表 → `CMD_INFO` 的命令元数据通过相同索引关联实现。该设计避免命令名、描述、参数和实现指针分别维护。

### 7.3 系统通知链

`exmlrpc_ProcessNotifyLib_exmlrpc` 处理易语言通知：

- `NL_SYS_NOTIFY_FUNCTION`：调用 `elib/fnshare.cpp::ProcessNotifyLib`，保存系统通知函数并触发调试版查询；
- `NL_GET_CMD_FUNC_NAMES`：返回静态编译需要的命令名数组；
- `NL_GET_NOTIFY_LIB_FUNC_NAME`：返回通知函数名字符串；
- `NL_GET_DEPENDENT_LIBS`：返回空的双零结尾依赖列表；
- `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NR_DELAY_FREE`、`NL_IDE_READY`、`NL_RIGHT_POPUP_MENU_SHOW`、`NL_ADD_NEW_ELEMENT`：当前分支无实际处理；
- 未识别通知返回 `NR_ERR`。

`elib/fnshare.cpp::NotifySys` 通过保存的 `PFN_NOTIFY_SYS` 调用易语言系统；`ealloc`/`efree`、`CloneTextData`、`CloneBinData` 等辅助函数依赖该回调进行内存和数据交换。

### 7.4 当前实现缺口

`exmlrpc_cmdDef.cpp` 的函数体普遍只做 `pArgInf` 参数取值，例如 `StartServer` 读取端口、回调地址和串行标志，`SendSynRequestText` 读取请求文本、结果引用和超时；没有调用 `NotifySys`、没有给 `pRetData` 赋值、没有分配/释放 `ServerDataPtr` 或 `ClientDataPtr`，也没有连接、收发、编码、解码和线程池实现。由此可确认当前提交更像“支持库接口生成/占位源码”，不是完整的远程服务实现。

## 8. 协议、网络与依赖边界

### 已确认

- 命令说明使用“服务器/客户端/请求/结果/端口/IP/超时/同步/异步”等远程通信概念。
- 元数据声明文本与二进制两条数据通道，并声明可注册处理函数。
- 支持库仅将 `__OS_WIN` 标记在命令和数据类型上。
- `elib` 提供易语言支持库 ABI、Windows 风格基础类型、内存和系统通知辅助。

### 未发现

对全部仓库源码检索未发现 `HTTP`、`TCP`、`socket`、XML 解析器、RPC 方法名/序列化器、第三方依赖、配置文件、端口监听实现或测试客户端。项目名中的 `xmlrpc` 不能替代源码证据，当前不能确认其线协议是否为标准 XML-RPC，也不能确认实际传输层。

### 工程声明的构建依赖

- Visual Studio C++ 项目格式，`VCProjectVersion 16.0`；
- Win32/x64、Debug/Release 配置；
- 工具集 `v141`（静态库工程显式配置）；
- Windows SDK `10.0.15063.0`（动态库工程显式配置）；
- 动态库 Win32 目标扩展名 `.fne`，通过 `Source_exmlrpc.def` 导出 `GetNewInf`；
- 静态库 Win32 Debug/Release 预处理宏包含 `__E_STATIC_LIB;__E_FNENAME=exmlrpc`；
- 静态库 x64 配置未见这两个宏，动态库 x64 配置也未见 `__E_FNENAME=exmlrpc`，且动态库 x64 链接配置未见 `ModuleDefinitionFile`，属于待复核的工程配置漂移。

## 9. 测试与验证状态

- 仓库没有测试目录、测试工程、示例程序或 CI 配置。
- 本轮只进行只读源码、工程、Git 远程和配置取证；按任务边界未安装依赖、未构建、未运行 DLL/静态库、未启动网络服务。
- 已完成的静态验证：命令索引 `0..28` 与 `exmlrpc_cmdDef.cpp` 的 29 个函数名对应；服务端/客户端数据类型索引覆盖命令表；参数表编号覆盖 `000..038`；动态库导出文件包含 `GetNewInf`；远程 `HEAD` 与本地基线一致。
- 尚未验证：Windows/Visual Studio 编译、易语言 IDE 加载、命令实际分发、对象内存生命周期、网络线程池、协议字节格式、同步超时和异步回调。

## 10. 风险与后续复核点

1. **实现完整性风险（高）：** 命令体没有可见业务实现，不能把命令说明当作已实现功能。
2. **协议识别风险（高）：** 未发现 XML、HTTP、TCP 或序列化代码；需要查找同组织历史版本、发布二进制对应源码或远程仓库其他分支，才能确认“exmlrpc”命名的真实含义。
3. **工程配置风险（中）：** x64 项目宏和动态库导出配置与 Win32 不对称，需在 Windows 工具链中单独核对。
4. **ABI/指针宽度风险（中）：** `elib` 中大量 `DWORD`/`INT` 与指针互转（如通知参数、函数名地址），x64 配置可能存在兼容性问题；当前未构建，不能下最终结论。
5. **线程安全风险（待核）：** 元数据宣称四线程池及串行处理选项，但当前可见实现不包含线程池或锁代码。
6. **资源释放风险（待核）：** 元数据存在构造/析构命令和易语言内存辅助函数，但未见对象创建、连接关闭或结果缓冲区释放逻辑。

## 11. 证据索引

- `exmlrpc_cmd_typedef.h`：29 条命令的唯一宏定义、命令说明、返回类型、参数区间。
- `exmlrpc_cmdInfo.cpp`：39 个参数元数据项和 `CMD_INFO` 数组。
- `exmlrpc_cmdDef.cpp`：29 个命令入口的真实函数体与参数读取情况。
- `exmlrpc_dtType.cpp`：`ERPCServer`/`ERPCClient` 类型、方法索引和成员元数据。
- `exmlrpc_dllMain.cpp`：`LIB_INFO`、函数指针表、`GetNewInf`、通知处理入口。
- `include_exmlrpc_header.h`：公共 include、全局表声明和宏生成的实现声明。
- `elib/lib2.h`：支持库 ABI、命名规则、数据类型、库结构和系统常量。
- `elib/fnshare.cpp` / `elib/fnshare.h`：`NotifySys`、`ProcessNotifyLib`、易语言内存/数据辅助。
- `exmlrpc.vcxproj` / `exmlrpc_static/exmlrpc_static.vcxproj`：动态/静态构建目标、源码清单、配置宏与工具链声明。
- `Source_exmlrpc.def`：动态库导出边界，仅 `GetNewInf`。
- Git 基线：`385f68de400b570fb16e22dab3aab987a62e2ba1`，远程 `https://gitee.com/JYtechnology/exmlrpc.git`。

## 12. 首轮结论

`exmlrpc` 的架构骨架清晰：以 `EXMLRPC_DEF` 为单一命令契约，分别生成易语言元数据、对象方法索引、ABI 函数声明和动态/静态分发入口；通过 `LIB_INFO`/`GetNewInf` 接入易语言支持库体系，通过 `fnshare` 接收系统通知。但当前唯一 Git 基线中，真正的远程服务实现没有出现在命令函数体或其他本地源码里。后续研究应优先围绕版本/分支来源和缺失运行时实现取证，而不是从接口说明推导 XML-RPC 协议细节。
