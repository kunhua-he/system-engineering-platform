# erawsock 架构档案

> 本文件是 `erawsock` 项目根目录唯一的架构归档文件。本文档依据本地源码、Visual Studio 工程文件和 Git 元数据建立；本轮仅做只读取证，没有修改源码、依赖、测试、配置，没有安装、构建或提交。

## 1. 项目定位

`erawsock` 是面向易语言的 Windows 支持库工程，库名为“网络通讯支持库二”。源码意图覆盖两类底层网络能力：

1. **原始套接字（RawSocket）**：按协议类型创建/关闭原始套接字，构造和解析 IP/TCP/ICMP 报头，并收发原始数据报。
2. **ARP 协议（ARP）**：打开和配置网络适配器，构造/解析以太网头与 ARP 头，发送和接收 ARP 数据包。

从当前提交的实际实现看，项目主要完成了易语言支持库的**命令元数据、数据类型描述、DLL/静态库装载接口和命令函数空壳生成**；`erawsock_cmdDef.cpp` 中 20 个命令的函数体只做了参数取值或保持空函数体，没有发现 socket、WinPcap、报文拼装、校验和、收发循环或资源句柄管理的实际实现。因此，“支持原始套接字和 ARP”是库元数据声明的目标能力，不应在当前版本中等同为已实现并可运行的网络功能。

## 2. 现场与版本基线

| 项目 | 现场事实 |
|---|---|
| 本地根目录 | `/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/erawsock` |
| 远程仓库 | `https://gitee.com/JYtechnology/erawsock.git` |
| 本地分支 | `master`，跟踪 `origin/master` |
| HEAD | `e0b7f5f1b9c896145d0da97d1eadfc3e71fef4bd` |
| HEAD 提交 | 2022-12-19 16:55:17 +08:00，`初始化仓库` |
| 远程 `HEAD` / `refs/heads/master` | `e0b7f5f1b9c896145d0da97d1eadfc3e71fef4bd` |
| Git 状态 | 建档前工作树干净；本地与远程指针一致 |
| 仓库形态 | shallow repository；只有一个可见的初始化提交 |
| 纳入版本控制的文件 | 23 个 |
| 工作区源码/工程文件总大小 | 196,693 字节（约 192 KB，按现场逐文件统计；不含 `.git` 与本档案） |

本地没有发现 `README.md`、`AGENTS.md`、`CLAUDE.md` 或旧 `细探-*.md`；因此本档案没有可吸收的项目级旧细探内容。远程版本只通过 `git ls-remote` 复核，未执行 fetch、pull 或构建。

## 3. 总体流程图

```text
易语言 IDE / 编译器
        |
        | 动态库装载：GetNewInf()
        v
+-----------------------------+
| erawsock.dll / .fne         |
| erawsock_dllMain.cpp        |
+-----------------------------+
        |
        +--> LIB_INFO
        |      |-- GUID/版本/名称/说明/系统版本要求
        |      |-- g_DataType_erawsock_global_var[9]
        |      |-- g_cmdInfo_erawsock_global_var[20]
        |      `-- g_cmdInfo_erawsock_global_var_fun[20]
        |
        +--> 易语言通知入口
        |      `-- erawsock_ProcessNotifyLib_erawsock()
        |              `-- ProcessNotifyLib() -> fnshare.cpp
        |
        `--> 命令分发表
               |
               +--> RawSocket（命令索引 0..9）
               |      +--> CreateSocket / CloseSocket
               |      +--> FillIPHeader / FillTCPHeader / FillICMPHeader
               |      +--> recvfrom / sendto
               |      `--> GetIPHeader / GetTCPHeader / GetICMPHeader
               |
               `--> ARP（命令索引 10..19）
                      +--> OpenAdapter / SetAdapter / CloseAdapter
                      +--> FillEthHeader / FillArpHeader
                      +--> SendArpPacket / RecvArpPacket
                      `--> GetArpIPHeader / GetEthHeader / GetArpHeader

当前源码实际状态：上述命令入口均已声明并注册，但命令实现函数体没有完成底层网络调用。

静态编译分支：
  易语言静态编译器
        -> erawsock_static.lib
        -> __E_STATIC_LIB 条件编译
        -> g_cmdNameserawsock[] + erawsock_ProcessNotifyLib_erawsock()
```

## 4. 真实目录与分层

```text
erawsock/
├── erawsock.sln                         # VS 解决方案，动态库 + 静态库两个项目
├── erawsock.vcxproj                     # 动态库工程，目标扩展名 Win32 为 .fne
├── erawsock.vcxproj.filters             # 动态库工程筛选器
├── erawsock.vcxproj.user                # VS 用户工程设置，占位
├── erawsock_static/
│   ├── erawsock_static.vcxproj          # 静态库工程
│   ├── erawsock_static.vcxproj.filters  # 静态库筛选器
│   └── erawsock_static.vcxproj.user     # VS 用户工程设置，占位
├── Source_erawsock.def                  # 动态库导出 GetNewInf
├── include_erawsock_header.h            # 统一头文件与命令函数声明宏
├── erawsock_cmd_typedef.h               # 20 条命令的单一宏定义表
├── erawsock_cmdDef.cpp                  # 20 个命令执行函数入口（当前为空壳）
├── erawsock_cmdInfo.cpp                 # 命令参数元数据与 CMD_INFO 数组
├── erawsock_const.cpp                   # 常量表，当前数量为 0
├── erawsock_dtType.cpp                  # 9 个易语言数据类型/枚举及成员元数据
├── erawsock_dllMain.cpp                 # DLL 入口、LIB_INFO、通知分发、静态名称表
└── elib/
    ├── lib2.h                           # 易语言支持库 ABI、LIB_INFO/CMD_INFO 等基础定义
    ├── lang.h                           # 语言版本宏
    ├── krnllib.h                        # 系统核心支持库接口
    ├── mtypes.h                         # 基础 Windows/易语言类型
    ├── fnshare.h                         # NotifySys/ProcessNotifyLib/内存辅助函数
    ├── fnshare.cpp                       # 通知函数指针和调试版本状态转发
    ├── untshare.h                        # 单元/窗口相关辅助定义
    └── PublicIDEFunctions.h              # IDE 通知功能编号与参数结构
```

### 4.1 支持库 ABI 层

`include_erawsock_header.h` 依赖 `elib/lib2.h`、`elib/lang.h`、`elib/krnllib.h` 和项目自己的 `erawsock_cmd_typedef.h`。它在非静态库模式下声明：

- `g_ConstInfo_erawsock_global_var`；
- `g_cmdInfo_erawsock_global_var`；
- `g_cmdInfo_erawsock_global_var_fun`；
- `g_argumentInfo_erawsock_global_var`；
- `g_DataType_erawsock_global_var`。

同一头文件通过 `ERAWSOCK_DEF_CMD` 将命令宏表展开成统一的 `EXTERN_C void ... (PMDATA_INF, INT, PMDATA_INF)` 函数声明，确保命令元数据、函数指针和实现入口使用相同的 0..19 索引。

### 4.2 命令描述层

`erawsock_cmd_typedef.h` 是命令定义的单一来源。`ERAWSOCK_DEF(_MAKE)` 为每条命令给出：索引、中文名、英文名、说明、Windows 限定、返回类型、参数个数及参数元数据起始地址。该宏被至少四种场景复用：

- `include_erawsock_header.h`：生成实现函数声明；
- `erawsock_cmdInfo.cpp`：生成易语言 IDE 展示用的 `CMD_INFO`；
- `erawsock_dllMain.cpp`：生成运行期函数指针数组；
- `erawsock_dllMain.cpp`：生成静态编译所需的函数名字符串数组。

这套 X-macro 结构是本项目最明确的架构约束：**命令编号必须保持一致，新增/删除命令必须同步影响所有展开点**。

### 4.3 数据类型与协议头模型层

`erawsock_dtType.cpp` 将数据类型分为两种可挂载命令的方法对象和若干结构/枚举对象：

| 索引 | 中文名 | 英文名 | 类型 | 成员/方法 |
|---:|---|---|---|---:|
| 0 | 原始套接字 | `RawSocket` | 方法对象 | 10 条方法，命令索引 0..9 |
| 1 | ARP协议 | `ARP` | 方法对象 | 10 条方法，命令索引 10..19 |
| 2 | IP报头 | `IPHeader` | 结构数据类型 | 11 个成员 |
| 3 | TCP报头 | `TCPHeader` | 结构数据类型 | 10 个成员 |
| 4 | ICMP报头 | `ICMPHeader` | 结构数据类型 | 5 个成员 |
| 5 | 以太网头 | `ETHHeader` | 结构数据类型 | 3 个成员 |
| 6 | ARP头 | `ARPHeader` | 结构数据类型 | 9 个成员 |
| 7 | 协议类型常量 | `protocol` | Windows 枚举 | 10 个成员 |
| 8 | ARP常量 | `ArpConst` | Windows 枚举 | 6 个成员 |

所有数据类型均设置 `_DT_OS(__OS_WIN)`；`protocol` 和 `ArpConst` 另带 `LDT_ENUM`。`ARP` 类型的说明明确写着：正常使用 ARP 命令前需要安装 `WinPcap 3.1` 驱动。

## 5. 命令与调用边界

### 5.1 RawSocket 命令组

| 索引 | 易语言方法 | C/C++ 入口 | 返回 | 参数事实 |
|---:|---|---|---|---|
| 0 | `创建` | `erawsock_CreateSocket_0_erawsock` | `SDT_BOOL` | `协议类型: SDT_INT` |
| 1 | `关闭` | `erawsock_CloseSocket_1_erawsock` | `SDT_BOOL` | 无 |
| 2 | `构造IP报头` | `erawsock_FillIPHeader_2_erawsock` | `_SDT_NULL` | `IPHeader` |
| 3 | `构造TCP报头` | `erawsock_FillTCPHeader_3_erawsock` | `_SDT_NULL` | `TCPHeader` |
| 4 | `构造ICMP报头` | `erawsock_FillICMPHeader_4_erawsock` | `_SDT_NULL` | `ICMPHeader` |
| 5 | `接收` / `recvfrom` | `erawsock_recvfrom_5_erawsock` | `SDT_BIN` | 可选 `等待时间: SDT_INT`；说明限制单次最大 20480 字节 |
| 6 | `发送` / `sendto` | `erawsock_sendto_6_erawsock` | `SDT_BOOL` | `对方IP: SDT_TEXT`、可选端口、可选等待时间、可选 `_SDT_ALL` 数据 |
| 7 | `取IP报头` | `erawsock_GetIPHeader_7_erawsock` | `_SDT_NULL` | `数据: SDT_BIN`、`IPHeader` |
| 8 | `取TCP报头` | `erawsock_GetTCPHeader_8_erawsock` | `_SDT_NULL` | `数据: SDT_BIN`、`TCPHeader` |
| 9 | `取ICMP报头` | `erawsock_GetICMPHeader_9_erawsock` | `_SDT_NULL` | `数据: SDT_BIN`、`ICMPHeader` |

### 5.2 ARP 命令组

| 索引 | 易语言方法 | C/C++ 入口 | 返回 | 参数事实 |
|---:|---|---|---|---|
| 10 | `打开网络适配器` | `erawsock_OpenAdapter_10_erawsock` | `SDT_BOOL` | 可选 `网卡序号: SDT_INT` |
| 11 | `配置网络适配器` | `erawsock_SetAdapter_11_erawsock` | `SDT_BOOL` | 可选模式、缓冲区大小、等待时间 |
| 12 | `关闭网络适配器` | `erawsock_CloseAdapter_12_erawsock` | `_SDT_NULL` | 无 |
| 13 | `构造以太网头` | `erawsock_FillEthHeader_13_erawsock` | `_SDT_NULL` | `ETHHeader` |
| 14 | `构造ARP头` | `erawsock_FillArpHeader_14_erawsock` | `_SDT_NULL` | `ARPHeader` |
| 15 | `发送` / `SendArpPacket` | `erawsock_SendArpPacket_15_erawsock` | `SDT_BOOL` | 可选 `发送次数: SDT_INT` |
| 16 | `接收` / `RecvArpPacket` | `erawsock_RecvArpPacket_16_erawsock` | `SDT_BIN` | 无 |
| 17 | `取IP报头` | `erawsock_GetArpIPHeader_17_erawsock` | `_SDT_NULL` | `数据: SDT_BIN`、`IPHeader` |
| 18 | `取以太网头` | `erawsock_GetEthHeader_18_erawsock` | `_SDT_NULL` | `数据: SDT_BIN`、`ETHHeader` |
| 19 | `取ARP头` | `erawsock_GetArpHeader_19_erawsock` | `_SDT_NULL` | `数据: SDT_BIN`、`ARPHeader` |

### 5.3 当前实际调用链

以 DLL 模式为例，源码可确认的链路如下：

```text
易语言运行时
  -> LoadLibrary(erawsock.fne)
  -> GetProcAddress("GetNewInf")
  -> GetNewInf()
  -> 返回 g_LibInfo_erawsock_global_var
  -> 读取 g_cmdInfo_erawsock_global_var / g_cmdInfo_erawsock_global_var_fun
  -> 按命令索引调用 erawsock_<命令>_<索引>_erawsock()
  -> 当前实现仅从 pArgInf 读取参数
  -> 没有继续调用 Winsock、WinPcap、NIC 句柄或报文编解码函数
```

`erawsock_dllMain.cpp` 的 `erawsock_ProcessNotifyLib_erawsock()` 能处理支持库生命周期和静态编译相关通知：

- `NL_GET_CMD_FUNC_NAMES`：返回 `g_cmdNameserawsock[]`；
- `NL_GET_NOTIFY_LIB_FUNC_NAME`：返回自身通知函数名；
- `NL_GET_DEPENDENT_LIBS`：返回 `"\0\0"`，表示没有声明额外静态库依赖；
- `NL_SYS_NOTIFY_FUNCTION`：转发给 `ProcessNotifyLib()`；
- `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NR_DELAY_FREE`、`NL_IDE_READY`、`NL_RIGHT_POPUP_MENU_SHOW`、`NL_ADD_NEW_ELEMENT`：当前为空处理；
- 未知通知：返回 `NR_ERR`。

`elib/fnshare.cpp` 中的 `ProcessNotifyLib()` 保存易语言系统传入的 `PFN_NOTIFY_SYS`，首次接到 `NL_SYS_NOTIFY_FUNCTION` 时调用 `NotifySys(NRS_GET_PRG_TYPE, 0, 0)` 获取调试/编译版本；`NotifySys()` 本身只是转发到已保存的函数指针。该层没有网络业务逻辑。

## 6. 数据模型与协议字段

### 6.1 `IPHeader`

源码字段顺序为：

- `h_lenver: SDT_BYTE`：4 位首部长度 + 4 位 IP 版本号；
- `tos: SDT_BYTE`：服务类型；
- `total_len: SDT_SHORT`：总长度；
- `ident: SDT_SHORT`：标识，默认值 `1`；
- `frag_and_flags: SDT_SHORT`：标志位；
- `ttl: SDT_BYTE`：生存时间，默认值 `0x80`；
- `proto: SDT_BYTE`：协议，默认值 `0x06`（TCP）；
- `checksum: SDT_SHORT`：IP 首部校验和；
- `sourceIP: SDT_TEXT`：源 IP 地址；
- `destIP: SDT_TEXT`：目的 IP 地址；
- `options: SDT_INT`：选项和填充。

### 6.2 `TCPHeader`

字段顺序为 `th_sport`、`th_dport`、`th_seq`、`th_ack`、`th_lenres`、`th_flag`、`th_win`、`th_sum`、`th_urp`、`th_options`。其中 `th_flag` 说明举例：`2` 表示 SYN、`1` 表示 FIN、`16` 表示 ACK 探测；源码没有实现其解析或序列化逻辑。

### 6.3 `ICMPHeader`

字段为 `type`、`code`、`checksum`、`seq`、`id`；`type` 默认 `8`（回送请求），`id` 默认 `1`。说明注明 `0` 为回送应答、`8` 为回送请求。

### 6.4 `ETHHeader` 与 `ARPHeader`

`ETHHeader` 字段：

- `eh_dst: SDT_TEXT`：以太网目的地址；`ffffffffffff` 被说明为广播地址；
- `eh_src: SDT_TEXT`：以太网源地址；
- `eh_type: SDT_SHORT`：帧类型，默认 `0x0806`（ARP）。

`ARPHeader` 字段：

- `hw_type` 默认 `1`，以太网硬件类型；
- `prot_type` 默认 `0x0800`，IP 协议类型；
- `hw_addr_size` 默认 `6`；
- `prot_addr_size` 默认 `4`；
- `opt` 默认 `1`，`1` 为 ARP 请求、`2` 为 ARP 应答；
- `src_hw_addr`、`src_ip_addr`、`des_hw_addr`、`des_ip_addr`：发送端/目的端硬件地址和 IP 地址。

这里的字段描述是易语言数据类型元数据，不是已验证的线缆级报文布局；当前命令函数没有实现将这些字段写入网络字节序报文的代码。

### 6.5 枚举常量

`protocol` 枚举给出：`IPPROTO_IP=0`、`IPPROTO_ICMP=1`、`IPPROTO_IGMP=2`、`IPPROTO_GGP=3`、`IPPROTO_TCP=6`、`IPPROTO_PUP=12`、`IPPROTO_UDP=17`、`IPPROTO_IDP=22`、`IPPROTO_ND=77`、`IPPROTO_RAW=255`。

`ArpConst` 枚举给出：`IP_PROTO_TYPE=0x0800`、`ARP_FRAME_TYPE=0x0806`、`ARP_REQUEST=1`、`ARP_REPLY=2`、`NDIS_PACKET_TYPE_DIRECTED=1`、`NDIS_PACKET_TYPE_PROMISCUOUS=2`。

## 7. 动态库、静态库与导出契约

### 7.1 动态库

`erawsock.vcxproj` 的 Win32 配置为 `DynamicLibrary`，`TargetExt` 为 `.fne`，模块定义文件为 `Source_erawsock.def`。`.def` 只导出 `GetNewInf`，因此易语言通过这个固定导出点取得 `LIB_INFO`，命令实现函数不直接作为普通 DLL API 导出。

`LIB_INFO` 在 `erawsock_dllMain.cpp` 中声明：

- `m_szGuid = "0166C2B421554aae940E6F74D9EEAE99"`；
- 版本 `2.0.4`；
- 要求易语言系统 `3.0`；
- 要求系统核心支持库 `3.7`；
- 名称 `网络通讯支持库二`；
- 语言 `__GBK_LANG_VER`；
- 平台状态 `_LIB_OS(OS_ALL)`；
- 命令数量由 `g_cmdInfo_erawsock_global_var_count` 提供；
- 自定义数据类型数量由 `g_DataType_erawsock_global_var_count` 提供；
- 附加 IDE 插件、SuperTemplate 和依赖文件列表均为 `NULL`（静态依赖通知另返回空字符串列表）。

### 7.2 静态库

`erawsock_static/erawsock_static.vcxproj` 的 Win32 配置为 `StaticLibrary`，并定义 `__E_STATIC_LIB;__E_FNENAME=erawsock`。它复用父目录的全部 `.cpp` 和 `.h` 文件，通过条件编译排除 DLL 专属的 `LIB_INFO` 数据，保留命令名数组和通知入口以配合易语言静态编译。

需要特别注意：静态工程的 `Debug|x64` 与 `Release|x64` 配置只显示 `_DEBUG;_LIB` 或 `NDEBUG;_LIB`，没有像 Win32 配置那样显式设置 `__E_STATIC_LIB` 和 `__E_FNENAME=erawsock`；动态工程的 x64 配置也没有显式设置 `__E_FNENAME=erawsock`，且没有 `ModuleDefinitionFile`。这属于工程配置风险，未经 Windows/MSBuild 环境实测，不直接断言一定失败。

## 8. 技术栈与依赖边界

| 层面 | 事实 |
|---|---|
| 语言 | C/C++，源码使用 Visual C++/Windows ABI 风格；注释和元数据以中文为主 |
| 构建系统 | Visual Studio `.sln` + `.vcxproj`，解决方案版本 12.00，VS 17 文件头 |
| 工具集 | `v141`；Windows SDK 目标 `10.0.15063.0` |
| 目标 | Win32/x86 与 x64；动态库 Win32 产物扩展名 `.fne`，静态库为静态库工程 |
| 宿主 ABI | 易语言支持库 ABI：`LIB_INFO`、`CMD_INFO`、`ARG_INFO`、`LIB_DATA_TYPE_INFO`、`PMDATA_INF` |
| 项目内基础库 | `elib/lib2.h`、`lang.h`、`krnllib.h`、`mtypes.h`、`fnshare.*`、`untshare.h`、`PublicIDEFunctions.h` |
| 网络依赖声明 | ARP 数据类型说明要求 `WinPcap 3.1`；工程文件未声明 `wpcap.lib`、`Packet.lib` 或其他第三方库 |
| Winsock 依赖 | 当前工程文件未发现 `ws2_32.lib` 等显式链接依赖；命令实现也未出现 Winsock API 调用 |
| 持久化 | 无数据库、文件存储、缓存或配置文件 |
| 运行期资源 | 元数据层没有持久资源；命令空壳也没有实际 socket/适配器句柄生命周期 |

`elib` 是项目随附的易语言支持库 SDK/兼容头文件集合，不应误记为业务网络依赖。`PublicIDEFunctions.h` 主要提供 IDE 功能编号和参数结构，本项目没有注册 IDE 插件功能（`m_pfnRunAddInFn = NULL`）。

## 9. 测试、验证与运行状态

### 9.1 现场发现

- 没有测试目录、测试源码、测试工程或测试脚本。
- 没有 README 或使用示例。
- 没有已编译 `.dll`、`.fne`、`.lib`、`.pdb`、抓包样本或 WinPcap 运行时文件。
- 本轮未安装 Visual Studio/Windows SDK/WinPcap，未执行构建、链接、加载 DLL、易语言 IDE 验证或真实网络收发。
- macOS 现场无法直接验证 Windows 专属编译和原始套接字/WinPcap 行为。

### 9.2 已完成的静态取证

- 核对本地工作树、分支、提交、远程 URL 和远程分支指针。
- 逐文件盘点 23 个受版本控制文件及目录结构。
- 读取命令宏表、命令实现空壳、参数元数据、数据类型元数据、DLL 通知入口、基础通知转发和两套工程配置。
- 通过源码交叉核对命令索引 0..19、RawSocket/ARP 两组 10 条方法索引、9 个数据类型登记项。
- 确认命令实现中没有实际网络 API 调用，避免把接口声明误写成可用实现。

### 9.3 后续验证建议（本轮不执行）

1. 在 Windows + Visual Studio 对 Win32 `Debug`/`Release` 分别进行动态库和静态库编译，记录 v141/SDK 兼容性。
2. 检查 x64 配置中预处理宏与 `.def` 导出设置是否需要补齐；任何修复应另行获得修改授权。
3. 若要恢复网络能力，先明确 Winsock 原始套接字和 WinPcap/Npcap 的依赖、权限、设备枚举及句柄释放契约。
4. 为每条命令补充单元/集成测试：报头字段边界、字节序、校验和、短包/超长包、超时、失败返回和重复关闭。
5. 在隔离 Windows 网络环境中做 ARP/原始报文抓包对照，验证 `RawSocket` 与 `ARP` 的数据模型是否真的映射到线缆布局。

## 10. 风险、缺口与未确认项

### 已确认风险

- **功能空壳风险**：20 个命令入口均未实现网络操作，返回值也没有在函数体中明确写入 `pRetData`。
- **依赖不闭合**：元数据要求 `WinPcap 3.1`，工程未声明第三方库链接项；动态库也没有显式 Winsock 链接项。
- **平台限制**：所有命令和数据类型均标记 Windows，不能按跨平台库使用。
- **x64 工程配置漂移**：x64 配置与 Win32 配置的预处理宏、导出设置不一致，需在 Windows 构建环境核实。
- **版本历史不足**：仓库为浅克隆且只有初始化提交，无法从本地 Git 历史判断后续实现计划或回归变化。

### 尚未确认

- 原始套接字预期采用 Winsock `SOCK_RAW` 还是其他封装方式；
- ARP 预期采用 WinPcap 3.1 的 `pcap_*` API、Packet API 还是项目外部封装；
- `Fill*Header` / `Get*Header` 的字节序、字段宽度、校验和和可变选项规则；
- `recvfrom` 20480 字节上限是协议约束、缓冲区约束还是历史实现约束；
- 命令注释中 `SDT_BOOL` 的返回写入约定及错误码/错误信息传递约定；
- Windows 管理员权限、原始套接字安全策略、Npcap/WinPcap 兼容范围；
- 真实可用的 `.fne` 安装位置、易语言版本兼容范围和静态编译器加载约定。

## 11. 证据路径索引

| 结论 | 主要证据 |
|---|---|
| 20 条命令、索引、返回类型和参数起始位置 | `erawsock_cmd_typedef.h`、`erawsock_cmdInfo.cpp` |
| 命令实现为空壳 | `erawsock_cmdDef.cpp` |
| RawSocket/ARP 方法分组 | `erawsock_dtType.cpp` 的两个 `s_dtCmdIndex...` 数组 |
| 9 个数据类型及成员 | `erawsock_dtType.cpp` |
| DLL 入口、库信息、命令函数表和通知 | `erawsock_dllMain.cpp` |
| `GetNewInf` 导出 | `Source_erawsock.def` |
| 支持库 ABI 与易语言类型 | `include_erawsock_header.h`、`elib/lib2.h`、`elib/mtypes.h` |
| 通知/内存辅助层 | `elib/fnshare.h`、`elib/fnshare.cpp` |
| 动态库配置 | `erawsock.vcxproj`、`erawsock.vcxproj.filters` |
| 静态库配置 | `erawsock_static/erawsock_static.vcxproj`、`erawsock_static/erawsock_static.vcxproj.filters` |
| 解决方案包含动态/静态两个项目 | `erawsock.sln` |
| Git 远程与版本基线 | `.git/config`、`git log`、`git ls-remote origin` |

## 12. 本轮结论

`erawsock` 的当前可验证核心不是一个完成的网络协议实现，而是一个**易语言支持库模板/接口骨架**：用 X-macro 统一生成命令声明、命令信息和函数表，用 `LIB_INFO` 接入易语言运行时，用数据类型元数据描述原始套接字、ARP 及报头字段，并保留动态库与静态库两条构建路径。后续研究或实现必须先解决“声明的网络能力与当前空函数体之间的落差”，再讨论协议细节和平台兼容；不能依据库说明或命令名称推断已有可运行的原始套接字/ARP 功能。
