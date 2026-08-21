# sock 架构建档

## 1. 文档范围与结论

- **项目**：`sock`，Gitee `JYtechnology/sock`，精易官方公开仓库。
- **定位**：面向易语言支持库 ABI 的“网络通讯支持库”工程，目标接口覆盖 TCP 服务器、TCP 客户端、UDP 数据报、本机网络信息，以及对应的易语言自定义数据类型。
- **首轮结论**：仓库已经完成支持库的工程骨架、命令/参数/自定义类型元数据、DLL 入口和通知分发框架；网络 socket 行为本身尚未实现。`sock_cmdDef.cpp` 中 23 个命令函数均只有参数提取或空函数体，没有 Winsock 调用、返回值填充、句柄状态管理或资源释放逻辑。
- **实现状态口径**：
  - **已实现**：Visual Studio solution/project 组织；易语言支持库 `LIB_INFO` 注册；`GetNewInf` 导出；命令元数据和命令函数指针表的生成；自定义数据类型描述；系统通知的最小转发骨架。
  - **仅声明/元数据**：23 个命令的中文名、英文名、返回类型、参数类型、对象归属、隐藏/析构标志和文档说明；3 个网络对象及 1 个“对方信息”复合类型。
  - **未实现**：监听、连接、收发、关闭、IP/端口查询、UDP 发送接收、本机名/IP/端口查询、对象析构，以及所有失败处理和返回值语义。
  - **未验证**：在当前 macOS 环境未使用 Visual Studio/MSBuild 编译或加载到易语言运行时；仓库没有测试工程和测试文件。因此不能把元数据可读、源码可编译或接口描述等同于运行时可用。
- **边界**：本文件是项目根目录唯一架构事实源。本轮只新增/更新本文件，未修改源码、工程、依赖、测试、配置或 Git 历史；未删除任何旧细探文件（现场未发现旧细探文件）。

## 2. 总体流程图

```text
易语言 IDE / 编译器
        │  加载支持库，按固定名称查找 GetNewInf
        ▼
Source_sock.def ────── 导出 GetNewInf
        │
        ▼
sock_dllMain.cpp::GetNewInf()
        │ 返回静态 LIB_INFO
        ├── 库版本/GUID/语言/平台/作者信息
        ├── g_DataType_sock_global_var[]  ← sock_dtType.cpp
        ├── g_cmdInfo_sock_global_var[]   ← sock_cmdInfo.cpp + SOCK_DEF
        ├── g_cmdInfo_sock_global_var_fun[] ← sock_dllMain.cpp + SOCK_DEF
        ├── g_ConstInfo_sock_global_var[] ← sock_const.cpp（当前 0 个常量）
        └── sock_ProcessNotifyLib_sock
                    │
                    ├── NL_SYS_NOTIFY_FUNCTION
                    │       ▼
                    │   elib/fnshare.h::ProcessNotifyLib
                    │       ▼
                    │   易语言系统通知函数（当前仅转发，不保存自有状态）
                    ├── NL_GET_CMD_FUNC_NAMES → 命令实现名数组（动态库分支）
                    ├── NL_GET_NOTIFY_LIB_FUNC_NAME → 通知函数名
                    └── NL_GET_DEPENDENT_LIBS → 空依赖串

用户调用对象命令
        │  命令索引/函数指针
        ▼
PFN_EXECUTE_CMD(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)
        │
        ▼
sock_cmdDef.cpp 中 23 个 sock_*_*_* 函数
        │ 当前只读取 pArgInf 的 m_int/m_pText/m_pByte/
        │ m_pBool/m_pCompoundData/m_ppCompoundData
        ├── 预期：创建/使用 WinSock 句柄、等待、收发并填写 pRetData
        └── 现状：没有系统调用、没有状态读写、没有返回值写入
```

## 3. 目录与工程地图

仓库当前 Git 追踪源码共 23 项（不含本架构文档写入前的 `.git` 内部文件）：

```text
sock/
├── sock.sln                         # VS solution，包含 DLL 与静态库两个项目
├── sock.vcxproj                     # 动态支持库项目（DynamicLibrary）
├── sock.vcxproj.filters              # VS 过滤器映射
├── sock.vcxproj.user                 # 空用户属性组
├── sock_static/
│   ├── sock_static.vcxproj          # 静态库项目（StaticLibrary）
│   ├── sock_static.vcxproj.filters  # 静态库过滤器映射
│   └── sock_static.vcxproj.user     # 空用户属性组
├── Source_sock.def                  # DLL 只导出 GetNewInf
├── include_sock_header.h            # 统一包含、外部元数据声明、命令原型展开
├── sock_cmd_typedef.h               # SOCK_DEF 命令单一清单与名称拼接宏
├── sock_cmdDef.cpp                  # 23 个命令执行函数，目前是空实现骨架
├── sock_cmdInfo.cpp                 # ARG_INFO/CMD_INFO 参数和命令编辑元数据
├── sock_dtType.cpp                  # 4 个自定义数据类型及对象成员索引
├── sock_const.cpp                   # 常量表，目前数量为 0
├── sock_dllMain.cpp                 # DLL 入口、LIB_INFO、函数表、通知入口
└── elib/
    ├── lib2.h                       # 易语言支持库 ABI、数据类型、元数据结构和通知码
    ├── fnshare.h                    # 内存/文本/字节集/数组/通知辅助函数
    ├── fnshare.cpp                  # 工程纳入的源文件，当前为空
    ├── krnllib.h                    # 核心支持库类型/版本常量
    ├── lang.h                       # 语言版本，当前为 GBK 中文
    ├── mtypes.h                     # Windows/易语言兼容基础类型定义
    ├── untshare.h                   # 通用对象/窗口辅助代码，目前与网络行为无关
    └── PublicIDEFunctions.h         # 易语言 IDE 公共函数声明
```

### 工程分层

| 层 | 文件 | 职责 | 状态 |
|---|---|---|---|
| 工程/链接层 | `sock.sln`、`sock.vcxproj`、`sock_static/sock_static.vcxproj`、`Source_sock.def` | 选择 DLL/静态库产物、Win32/x64 与 Debug/Release、导出入口 | 已实现工程描述；是否能构建未验证 |
| ABI/公共类型层 | `elib/lib2.h`、`elib/mtypes.h`、`elib/lang.h`、`elib/krnllib.h` | 定义 `DATA_TYPE`、`MDATA_INF`、`ARG_INFO`、`CMD_INFO`、`LIB_INFO`、通知码和基础类型 | 已实现为随库携带的 ABI 头文件 |
| 支持库装配层 | `include_sock_header.h`、`sock_cmd_typedef.h` | 以 `SOCK_DEF` 单一清单展开声明、编辑信息、函数表和静态命令名 | 已实现 |
| 编辑/反射元数据层 | `sock_cmdInfo.cpp`、`sock_dtType.cpp`、`sock_const.cpp` | 命令参数、对象方法索引、自定义成员、常量信息 | 元数据已实现；不代表执行行为实现 |
| 运行时入口层 | `sock_dllMain.cpp` | `DllMain`、`GetNewInf`、`LIB_INFO`、通知处理和命令指针数组 | 框架已实现；业务状态管理缺失 |
| 网络命令层 | `sock_cmdDef.cpp` | TCP server/client、UDP、本机信息和析构命令 | 仅参数提取/空函数，网络行为未实现 |

## 4. 模块职责与真实调用关系

### 4.1 `SOCK_DEF` 单一命令清单

`sock_cmd_typedef.h:13-35` 用 `_MAKE` 宏列出索引 `0..22` 的 23 个命令。每行同时携带中文显示名、英文标识、说明、对象类别、Windows 状态、返回类型、参数个数和 `ARG_INFO` 起始地址。该清单被多次展开：

1. `include_sock_header.h:22-24` 用 `SOCK_DEF_CMD` 生成 23 个 `SOCK_NAME(...)` 执行函数原型；
2. `sock_cmdInfo.cpp:55-64` 用 `SOCK_DEF_CMDINFO` 生成 `CMD_INFO g_cmdInfo_sock_global_var[]`；
3. `sock_dllMain.cpp:26-29` 用 `SOCK_DEF_CMD_PTR` 生成 `PFN_EXECUTE_CMD g_cmdInfo_sock_global_var_fun[]`；
4. `sock_dllMain.cpp:94-98` 生成静态编译使用的命令名数组。

`SOCK_NAME` 在 `sock_cmd_typedef.h:3-9` 结合 `__E_FNENAME=sock` 与命令索引拼出稳定的支持库符号，例如 `sock_start_server_0_sock`。该命名是 ABI 连接点，不是网络业务实现。

### 4.2 DLL/支持库注册

`sock_dllMain.cpp:31-87` 初始化一个静态 `LIB_INFO`：

- 格式号：`LIB_FORMAT_VER`；
- GUID：`A6B983789F624b2cBDFD7D671249C097`；
- 版本：`2.0.2`；
- 所需易语言系统版本：`3.7`；核心支持库版本：`3.7`；
- 名称：`网络通讯支持库`；说明：`本支持库实现对网络通讯的支持`；
- 语言：`__GBK_LANG_VER`；平台状态：`OS_ALL`；
- 自定义数据类型、命令信息、命令函数表、常量表均通过全局数组挂接；
- `m_pfnNotify` 指向 `sock_ProcessNotifyLib_sock`；
- `m_szzDependFiles` 为 `NULL`，未声明额外支持库文件依赖。

`Source_sock.def:1-4` 只导出 `GetNewInf`。`GetNewInf` 在 `sock_dllMain.cpp:89-92` 直接返回上述 `LIB_INFO` 地址。

### 4.3 系统通知

`sock_dllMain.cpp:101-178` 实现 `sock_ProcessNotifyLib_sock`：

- `NL_SYS_NOTIFY_FUNCTION`：调用 `ProcessNotifyLib(nMsg, dwParam1, dwParam2)`，将系统通知函数转发到 `elib/fnshare.h:48-50` 的 ABI 辅助入口；
- `NL_GET_CMD_FUNC_NAMES`：返回 `g_cmdNamessock`；
- `NL_GET_NOTIFY_LIB_FUNC_NAME`：返回文本 `sock_ProcessNotifyLib_sock`；
- `NL_GET_DEPENDENT_LIBS`：返回 `"\0\0"`；
- `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NL_IDE_READY`、`NL_RIGHT_POPUP_MENU_SHOW`、`NL_ADD_NEW_ELEMENT` 等分支均为空处理；未知通知返回 `NR_ERR`。

该模块没有初始化 WinSock、没有保存系统通知函数指针到 sock 自有状态，也没有退出时释放网络资源的实现。

## 5. 命令接口清单

下表来自 `sock_cmd_typedef.h:13-35`、`sock_cmdInfo.cpp:5-66` 与 `sock_cmdDef.cpp` 的函数签名。参数编号按源码访问方式从 `pArgInf[1]` 开始；`pArgInf[0]` 未被命令体使用。返回类型是**声明的易语言返回类型**，不是已验证的实际返回值。

| 索引 | 对象/英文命令 | 易语言显示名 | 声明返回 | 参数声明 | 执行实现状态 |
|---:|---|---|---|---|---|
| 0 | `socket_server.start_server` | 启动 | `SDT_BOOL` | `端口: SDT_INT` | 仅读取端口，未启动 |
| 1 | `socket_server.stop_server` | 停止 | `SDT_BOOL` | 无 | 空函数，未停止 |
| 2 | `socket_server.accept_server` | 监听 | `SDT_INT` | `等待时间: SDT_INT` | 仅读取等待时间，未监听 |
| 3 | `socket_server.recv_server` | 接收 | `SDT_BIN` | `客户端句柄: SDT_INT`；`等待时间: SDT_INT`；可选引用 `是否成功: SDT_BOOL` | 仅读取参数，未接收/填充结果 |
| 4 | `socket_server.send_server` | 发送 | `SDT_BOOL` | `客户端句柄: SDT_INT`；`数据: _SDT_ALL`；`等待时间: SDT_INT` | 仅读取参数，未发送 |
| 5 | `socket_server.close_client` | 断开连接 | `SDT_BOOL` | `客户端句柄: SDT_INT` | 仅读取句柄，未关闭 |
| 6 | `socket_server.get_client_ip` | 取客户IP | `SDT_TEXT` | `客户端句柄: SDT_INT` | 仅读取句柄，未查询 |
| 7 | `socket_server.get_client_port` | 取客户端口 | `SDT_INT` | `客户端句柄: SDT_INT` | 仅读取句柄，未查询 |
| 8 | `socket_client.connect_client` | 连接 | `SDT_BOOL` | `IP地址: SDT_TEXT`；`端口: SDT_INT` | 仅读取文本/端口，未连接 |
| 9 | `socket_client.client_close` | 断开 | `SDT_BOOL` | 无 | 空函数，未关闭 |
| 10 | `socket_client.recv_client` | 接收 | `SDT_BIN` | `等待时间: SDT_INT`；可选引用 `是否成功: SDT_BOOL` | 仅读取参数，未接收/填充结果 |
| 11 | `socket_client.send_client` | 发送 | `SDT_BOOL` | `数据: _SDT_ALL`；`等待时间: SDT_INT` | 仅读取参数，未发送 |
| 12 | `socket_udp.setup_udp` | 配置 | `SDT_BOOL` | `端口: SDT_INT`，元数据标记 `AS_HAS_DEFAULT_VALUE` | 仅读取端口，未配置 |
| 13 | `socket_udp.close_udp` | 关闭 | `SDT_BOOL` | 无 | 空函数，未关闭 |
| 14 | `socket_udp.recvfrom_udp` | 接收 | `SDT_BIN` | `等待时间: SDT_INT`；引用 `对方信息: MAKELONG(0x04,0)`；可选引用 `是否成功: SDT_BOOL` | 仅读取参数，未接收/填充对方信息 |
| 15 | `socket_udp.sendto_udp` | 发送 | `SDT_BOOL` | `对方信息: MAKELONG(0x04,0)`；`数据: _SDT_ALL`；`等待时间: SDT_INT` | 仅读取参数，未发送 |
| 16 | 全局 `get_local_name` | 取本机名 | `SDT_TEXT` | 无 | 空函数，未查询 |
| 17 | 全局 `get_local_ip` | 取本机IP | `SDT_TEXT`，标记 `CT_RETRUN_ARY_TYPE_DATA` | 无 | 空函数，未查询/生成数组 |
| 18 | `socket_client/socket_udp.get_local_port` | 取本机端口 | `SDT_INT` | 无 | 空函数，未查询 |
| 19 | 全局 `get_local_port_old` | 取本机端口 | `SDT_INT` | 无 | 隐藏、已废弃兼容命令，函数体空 |
| 20 | `socket_server.server_obj_free_cmd` | 析构函数 | `_SDT_NULL` | 无 | 隐藏析构标志已声明，未释放对象 |
| 21 | `socket_client.client_obj_free_cmd` | 析构函数 | `_SDT_NULL` | 无 | 隐藏析构标志已声明，未释放对象 |
| 22 | `socket_udp.udp_obj_free_cmd` | 析构函数 | `_SDT_NULL` | 无 | 隐藏析构标志已声明，未释放对象 |

### 执行函数的 ABI 形态

所有函数均为 `extern "C" void`，签名统一为 `PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf`。真实定义在 `sock_cmdDef.cpp:5-202`：

- 整数参数读 `pArgInf[n].m_int`；
- 文本参数读 `m_pText`；
- 通用字节数据读 `m_pByte`；
- 可选引用逻辑参数读 `m_pBool`；
- 复合数据引用读 `m_ppCompoundData`，非引用复合数据读 `m_pCompoundData`。

当前实现没有一次写入 `pRetData`，也没有通过 `CloneTextData`、`CloneBinData` 或 `NotifySys` 构造返回数据；因此所有声明的成功/失败、空数据、`-1`、IP 文本和数组返回语义都未落地。

## 6. 自定义数据模型

`sock_dtType.cpp:4-93` 在非静态库编译分支中注册 4 个 `LIB_DATA_TYPE_INFO`：

| 中文名 | 英文名 | 结构/成员 | 方法索引 | 状态 |
|---|---|---|---|---|
| 网络服务器 | `socket_server` | 隐藏成员 `S_SOCKET: SDT_INT`（服务器句柄） | `0,1,2,3,4,5,6,7,20` | 类型/成员描述已实现；句柄无实际存储初始化和生命周期逻辑 |
| 网络客户端 | `socket_client` | 隐藏成员 `C_SOCKET: SDT_INT`（连接句柄） | `8,9,10,11,21,18` | 类型/成员描述已实现；连接句柄未创建/维护 |
| 网络数据报 | `socket_udp` | 隐藏成员 `U_SOCKET: SDT_INT`（数据报句柄） | `12,13,14,15,22,18` | 类型/成员描述已实现；UDP 句柄未创建/维护 |
| 对方信息 | `halve_info` | `halve_ip: SDT_TEXT`；`halve_port: SDT_INT` | 无 | 复合成员描述已实现；发送/接收函数未读写其成员 |

这里的“对象”是易语言支持库元数据中的自定义数据类型，不是 C++ 类。源码没有 `socket_server`、`socket_client`、`socket_udp` 的 C++ 类、全局句柄表、锁、引用计数或对象实例管理器。

公共 ABI 数据模型来自 `elib/lib2.h`：

- `DATA_TYPE` 为 `DWORD`（`lib2.h:243-244`），基本类型通过 `SDT_INT`、`SDT_BOOL`、`SDT_TEXT`、`SDT_BIN` 等宏编码；
- `ARG_INFO`（`lib2.h:266-292`）描述参数名、类型、默认值和引用/数组标志；
- `CMD_INFO`（`lib2.h:297-364`）描述命令名、类别、状态、返回类型和参数数组；
- `LIB_DATA_TYPE_INFO`（`lib2.h:693-729`）描述自定义类型的成员命令和枚举/复合成员；
- `MDATA_INF`（`lib2.h:800-824`）使用联合字段承载整数、文本、字节集、布尔引用、复合数据引用和数组数据，命令 ABI 通过它传入/传出数据；
- `LIB_INFO`（`lib2.h:1248-1315`）把库版本、平台、类型表、命令表、函数表、通知函数和依赖文件串组装为易语言可加载的库信息。

## 7. 数据流与状态边界

### 7.1 当前可证实的数据流

```text
SOCK_DEF 命令清单
  ├─> g_cmdInfo_sock_global_var[]       编辑器显示信息
  ├─> g_cmdInfo_sock_global_var_fun[]   运行时函数地址表
  ├─> SOCK_NAME(...) 函数声明
  └─> g_cmdNamessock[]                  静态编译命令名

易语言参数
  └─> MDATA_INF pArgInf
       └─> sock_cmdDef.cpp 读取联合成员
            └─> （当前无后继网络调用，也无 pRetData 写入）

易语言系统通知
  └─> sock_ProcessNotifyLib_sock
       └─> ProcessNotifyLib / 返回名称或依赖信息
```

### 7.2 预期但未实现的数据流

```text
启动/配置命令
  → 创建 WinSock socket
  → bind/listen 或 bind UDP
  → 将 OS socket 句柄写入对象隐藏成员

连接/监听命令
  → accept/connect
  → 返回客户端句柄或布尔结果

收发命令
  → 等待时间转换为阻塞/非阻塞或超时策略
  → recv/send/recvfrom/sendto
  → 复制字节集/文本、写入“是否成功”和“对方信息”

关闭/析构命令
  → close/closesocket
  → 清理对象成员、避免重复关闭
```

上述流程只由命令说明和数据类型设计暗示，源码中没有对应 WinSock API、超时机制、缓冲区、错误码转换或资源释放代码，必须标为未实现而不是设计完成。

### 7.3 当前没有的持久化与外部状态

项目没有数据库、文件存储、配置文件、线程队列、日志模块或跨进程状态。理论上的运行状态只可能存在于易语言对象成员和未来的 OS socket 句柄中；当前源码没有实际状态容器。

## 8. 依赖与构建配置

### 8.1 工程配置

`sock.sln:5-38` 包含：

- `sock`：动态库项目，GUID `{CEADC3DD-024E-4173-9CCF-E60334B2944F}`；
- `sock_static`：静态库项目，GUID `{5FF16995-6AD6-4964-A421-E0842E1BE946}`；
- `Debug/Release × x86(x86 映射到 Win32)/x64` 四种 solution 配置。

`sock.vcxproj:43-75`：

- `ConfigurationType=DynamicLibrary`；
- Windows SDK `10.0.15063.0`；
- `PlatformToolset=v141`；字符集 Unicode；
- Win32 Debug/Release 的目标扩展为 `.fne`（`sock.vcxproj:95-105`）；x64 配置未设置 `TargetExt`；
- Win32 Debug 定义 `__E_FNENAME=sock;WIN32;_DEBUG;SOCK_EXPORTS...`，Win32 Release 同样定义库名；但 x64 Debug/Release 的预处理器定义中没有 `__E_FNENAME=sock`（`sock.vcxproj:159-189`）。`elib/lib2.h:23-25` 对缺失 `__E_FNENAME` 有 `#error`，因此 x64 构建存在明确配置风险，尚未实测。

`sock_static/sock_static.vcxproj:40-72` 为静态库，定义 `__E_STATIC_LIB` 和 `__E_FNENAME=sock` 只出现在 Win32 Debug/Release（`96`、`115` 行）；x64 Debug/Release 的预处理器定义（`134`、`151` 行）同样未定义 `__E_FNENAME`。此外静态库 x64 设置 `PrecompiledHeader=Use`（`136-137`、`153-154`），而项目文件中未列出 `pch.h`，存在另一项待 Windows 工具链验证的构建风险。

两个项目编译的源码集合相同：动态库从项目根引用 `elib/fnshare.cpp` 和 5 个 `sock_*.cpp`；静态库通过 `..\` 路径引用同一批源码（各项目文件 `22-27`）。

### 8.2 依赖边界

- 直接包含：`include_sock_header.h` 包含 `elib/lib2.h`、`elib/lang.h`、`elib/krnllib.h` 和 `sock_cmd_typedef.h`。
- `elib/lib2.h` 包含 Windows SDK 的 `windows.h`、标准头 `stdio.h`、`math.h`、`assert.h`（关键包含在 `lib2.h:61-102`）。
- `elib/mtypes.h` 提供部分 Windows 兼容基础 typedef，但 `lib2.h` 仍依赖 Windows 类型/API。
- `m_szzDependFiles=NULL`，且通知分支返回空依赖字符串；工程 Link 节没有显式 `ws2_32.lib` 或其他网络库依赖。
- 全仓库源码中没有 `#include <winsock.h>`/`<winsock2.h>`、`socket`、`bind`、`listen`、`accept`、`connect`、`recv`、`send`、`WSAStartup` 等网络实现调用；因此当前工程实际上还不是可工作的 WinSock 实现。
- `elib/fnshare.cpp` 被项目纳入但内容为空；辅助函数主要为 `fnshare.h` 中 inline 定义，内存和通知通过易语言系统 ABI 完成（`fnshare.h:20-50`、`58-169`）。

## 9. 测试与验证现状

### 已做的静态取证

- 人工读取 solution、两个 `.vcxproj`、两个 filters、两个 `.user`、`.def`、全部 sock 核心 `.cpp/.h` 和 `elib` ABI 头文件。
- 逐个检查 `sock_cmdDef.cpp` 的 23 个函数体：没有网络调用，也没有 `pRetData` 写入；有参数读取的函数只做局部变量赋值。
- 核对 `SOCK_DEF` 的 23 个索引与对象方法索引：服务器 `0,1,2,3,4,5,6,7,20`；客户端 `8,9,10,11,21,18`；UDP `12,13,14,15,22,18`。
- 核对本地与远程 Git 提交基线：二者均为 `63b4b34f2ba1f126a33321b1703f94ae9b44ebf3`。

### 未执行/不存在

- 仓库未发现 `test/`、`tests/`、单元测试、集成测试、CI 配置或测试工程。
- 未在 macOS 上执行 MSVC/MSBuild；当前工程面向 Windows SDK/VS `v141`，本机环境不能据此宣称通过编译。
- 未加载 DLL、未调用 `GetNewInf`、未在易语言 IDE/运行时注册支持库、未进行真实 TCP/UDP 回环测试。
- 未验证 `MDATA_INF` ABI 在目标易语言版本中的布局兼容性、x86/x64 指针/句柄转换、命令参数索引约定和 `MAKELONG(0x04,0)` 复合类型编码。

## 10. 风险、缺口与后续复核点

1. **核心功能缺失（阻断）**：23 个命令均无网络行为；不能声称支持 TCP/UDP 运行。
2. **返回值契约缺失（阻断）**：函数体不写 `pRetData`，可选 `BOOL*` 参数也不写成功状态；声明的 `SDT_BOOL`/`SDT_BIN`/`SDT_TEXT`/数组返回均不可用。
3. **资源生命周期缺失（阻断）**：自定义对象只有隐藏整数成员定义，没有 socket 创建、初始化、关闭、析构、重复关闭和失败回滚逻辑。
4. **平台/依赖缺失（阻断）**：源码没有 Winsock 头文件和 API，也没有工程级 `ws2_32.lib` 链接配置；`m_szzDependFiles` 为空不能替代链接依赖。
5. **x64 预处理器风险（重要）**：两个 x64 配置没有定义 `__E_FNENAME`，会触发 `elib/lib2.h:23-25` 的硬错误；必须在目标 Windows 工具链中确认或修正后才能宣称 x64 支持。本轮按边界未修改工程。
6. **静态库 x64 预编译头风险（重要）**：静态项目 x64 配置要求使用 `pch.h`，但仓库没有该文件的工程条目；构建行为未验证。
7. **句柄模型未定义（重要）**：元数据把服务器/客户端/UDP 句柄都编码为 `SDT_INT`，未说明 OS `SOCKET` 到易语言整数的安全转换、错误值、64 位布局或句柄表策略。
8. **阻塞/超时语义未定义（重要）**：命令说明规定 `0` 无限等待、`-1` 不等待、其他值为毫秒，但没有实现转换、取消、并发和错误返回策略。
9. **数据复制与所有权未定义（重要）**：`SDT_BIN`、`SDT_TEXT` 与 `halve_info` 的返回/写入需要遵守易语言内存管理；当前没有调用 `CloneBinData`/`CloneTextData`，也没有说明接收缓冲区所有权。
10. **兼容元数据风险（建议）**：`get_local_port_old` 标记为隐藏/废弃但仍注册；需在真实易语言 IDE 中确认隐藏状态、方法索引和析构命令行为。
11. **异常/线程模型缺失（建议）**：没有 WSA 错误映射、并发访问保护、连接状态机、读写线程模型或日志/诊断接口。
12. **编码/构建一致性待核对（建议）**：源码中文文本为 GB18030/GBK 语义，工程字符集为 Unicode；需在 Windows 编译和易语言 IDE 加载时验证元数据编码展示。

## 11. Git 基线与证据路径

### Git 基线

- 远程：`origin https://gitee.com/JYtechnology/sock.git`。
- 分支：`master`，跟踪 `origin/master`。
- HEAD：`63b4b34f2ba1f126a33321b1703f94ae9b44ebf3`。
- 提交时间：`2022-12-19T16:57:21+08:00`。
- 提交主题：`初始化仓库`。
- `git ls-remote origin HEAD refs/heads/master` 与本地 HEAD 一致，远程无更新差异可见。
- 建档前工作树：`master...origin/master`，无源码/工程未提交变更。建档后预期唯一变更为本文件 `ARCHITECTURE.md`。

### 关键证据索引

| 事实 | 证据 |
|---|---|
| Solution 两项目、四种配置 | `sock.sln:5-32` |
| DLL 工程源码、类型、配置、目标扩展 | `sock.vcxproj:21-48`、`sock.vcxproj:51-198` |
| 静态库工程及宏/预编译头配置 | `sock_static/sock_static.vcxproj:21-45`、`sock_static/sock_static.vcxproj:48-163` |
| DLL 只导出 `GetNewInf` | `Source_sock.def:1-4` |
| 统一头、外部数组和命令原型 | `include_sock_header.h:3-24` |
| 命令清单与命令 ABI 名称 | `sock_cmd_typedef.h:1-35` |
| 23 个命令执行函数 | `sock_cmdDef.cpp:5-202` |
| 参数元数据和命令元数据 | `sock_cmdInfo.cpp:5-69` |
| 自定义类型、成员和方法索引 | `sock_dtType.cpp:4-93` |
| 空常量表 | `sock_const.cpp:1-14` |
| `LIB_INFO`、函数表、入口、通知处理 | `sock_dllMain.cpp:5-178` |
| 支持库 ABI 结构和 `MDATA_INF` | `elib/lib2.h:243-364`、`elib/lib2.h:693-729`、`elib/lib2.h:800-824`、`elib/lib2.h:1234-1318` |
| 内存/文本/字节集/通知辅助 | `elib/fnshare.h:20-169` |
| GBK 语言版本 | `elib/lang.h:6-14` |
| 核心支持库版本和网络数据类型编号 | `elib/krnllib.h:41-45`、`elib/krnllib.h:114-126` |
| 未发现测试/旧细探 | 现场文件清单与 Git tree；仓库无 `test*`/`tests*`、无 `细探-*.md` |

## 12. 首轮建档后的维护规则

- 后续深挖只更新本 `ARCHITECTURE.md`，不再生成平行的项目架构说明。
- 任何“已实现”结论必须有源码调用链、工程配置、测试或目标运行时证据；命令说明、注释和元数据只能证明“声明”。
- 网络行为实现后，至少需要补充：WinSock 初始化/清理、句柄生命周期、阻塞/超时策略、错误映射、字节集/文本所有权、x86/x64 构建结果、TCP/UDP 回环测试和易语言加载验证。
- 本文不把未执行的 Windows 构建或运行测试写成通过；不把对象成员描述写成真实 C++ 对象状态。
