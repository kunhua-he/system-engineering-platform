# btdownload 架构归档

## 1. 项目定位

`btdownload` 是一个面向易语言的 Windows BT 下载支持库源码仓库。它通过易语言支持库 ABI 暴露“BT下载”对象、Torrent 发布文件分析/制作、下载任务控制、Tracker/连接日志、代理与限速等命令和自定义数据类型。

**当前事实结论：** 当前仓库更接近“支持库接口/元数据与工程骨架”，不是完整 BT 引擎源码。`btdownload_cmdDef.cpp` 中 28 个命令处理函数均只做参数局部绑定或空函数体，没有给 `pRetData` 写返回值，也没有发现 bencode、网络 socket、文件分片、SHA-1 计算或 Tracker/Peer 协议实现。实际下载实现若存在，应位于仓库外部的运行时/原闭源组件，不能从本仓库源码确认。

## 2. 真实执行流程

```text
易语言 IDE/编译器
    │ 加载 .fne/.fnl 或静态编译链接
    ▼
GetNewInf()  ──► g_LibInfo_btdownload_global_var
                       │
                       ├─ 支持库身份/版本/语言/Windows 平台信息
                       ├─ g_DataType_btdownload_global_var（8 个自定义数据类型）
                       ├─ g_cmdInfo_btdownload_global_var（28 个命令描述）
                       ├─ g_cmdInfo_btdownload_global_var_fun（28 个执行函数指针）
                       └─ g_ConstInfo_btdownload_global_var（0 个常量）
                                      │
                                      ▼
                       易语言运行时按命令索引分发
                                      │
                                      ▼
BTDOWNLOAD_NAME(index, name)
                                      │
                                      ▼
btdownload_<name>_<index>_btdownload()
                                      │
                                      ├─ 当前源码：读取/绑定 pArgInf 参数
                                      └─ 当前源码：未实现实际下载、返回值、错误与资源生命周期

支持库通知链：
易语言运行时 ──NL_SYS_NOTIFY_FUNCTION──► ProcessNotifyLib()
       │                                      │
       │                                      ├─ 保存 PFN_NOTIFY_SYS
       │                                      └─ 首次读取 NRS_GET_PRG_TYPE（调试/发布类型）
       └─ NL_FREE_LIB_DATA / NL_UNLOAD_FROM_IDE / 其它通知
```

## 3. 目录与文件地图

仓库根目录：`/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/btdownload`

```text
btdownload/
├── btdownload.sln                         Visual Studio 解决方案
├── btdownload.vcxproj                     动态库工程，输出 .fne（Win32 配置）
├── btdownload.vcxproj.filters             动态库工程筛选器
├── btdownload.vcxproj.user                空用户工程配置
├── btdownload_static/
│   ├── btdownload_static.vcxproj          静态库工程
│   ├── btdownload_static.vcxproj.filters  静态库工程筛选器
│   └── btdownload_static.vcxproj.user     空用户工程配置
├── Source_btdownload.def                  动态库导出表，仅导出 GetNewInf
├── include_btdownload_header.h             公共入口头文件、命令声明展开
├── btdownload_cmd_typedef.h               命令索引/名称宏 BTDOWNLOAD_DEF
├── btdownload_cmdInfo.cpp                 ARG_INFO、CMD_INFO 元数据表
├── btdownload_cmdDef.cpp                  28 个命令处理函数骨架
├── btdownload_dtType.cpp                  8 个自定义数据类型及成员/方法索引
├── btdownload_const.cpp                   常量表，目前数量为 0
└── elib/
    ├── lib2.h                             易语言支持库 ABI、LIB_INFO/MDATA_INF 等
    ├── lang.h                             语言版本宏
    ├── krnllib.h                          系统核心支持库常量/接口
    ├── mtypes.h                           基础类型兼容定义
    ├── untshare.h                         易语言单元/运行时相关定义
    ├── PublicIDEFunctions.h               IDE 功能通知编号与参数结构
    ├── fnshare.h                          通知、内存、数组/字节集辅助接口
    └── fnshare.cpp                        PFN_NOTIFY_SYS 保存与通知转发
```

源码基线现场共 23 个非 `.git` 文件（写入本归档前）；没有 `README`、`AGENTS.md`、Markdown 文档、测试目录、测试工程、CI 配置或发布脚本。

## 4. 支持库 ABI 与入口

### 4.1 动态库入口

- `Source_btdownload.def` 的 `EXPORTS` 仅导出 `GetNewInf`。
- `btdownload_dllMain.cpp::GetNewInf()` 返回 `&g_LibInfo_btdownload_global_var`。
- `DllMain` 仅保留四类 Windows 生命周期分支，当前分支均为空，返回 `TRUE`。
- `g_LibInfo_btdownload_global_var` 的关键身份字段：
  - `LIB_FORMAT_VER`：`20000101`；
  - GUID：`32F502732D7A44809082F855618D6BD4`；
  - 库版本：`2.0.0`；
  - 所需易语言系统：`3.7`；
  - 所需系统核心支持库：`3.7`；
  - 名称：`BT下载支持库`；
  - 语言：`__GBK_LANG_VER`；
  - 平台状态：`_LIB_OS(OS_ALL)`，但命令/数据类型元数据都标为 Windows；
  - 作者/地址/联系方式：源码中写为“大有吴涛易语言软件公司”及其大连联系方式；
  - 自定义数据类型：`g_DataType_btdownload_global_var`；
  - 命令表/函数表：各自的全局数组；
  - 依赖文件：`NULL`。

### 4.2 易语言通知协议

`btdownload_dllMain.cpp::btdownload_ProcessNotifyLib_btdownload()` 处理以下消息：

- `NL_GET_CMD_FUNC_NAMES`：返回静态编译所需的 `g_cmdNamesbtdownload`；
- `NL_GET_NOTIFY_LIB_FUNC_NAME`：返回字符串 `btdownload_ProcessNotifyLib_btdownload`；
- `NL_GET_DEPENDENT_LIBS`：返回 `"\0\0"`，表示没有额外静态库依赖；
- `NL_SYS_NOTIFY_FUNCTION`：调用 `ProcessNotifyLib()`，把系统通知函数指针交给 `elib/fnshare.cpp`；
- `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NR_DELAY_FREE`、`NL_IDE_READY`、`NL_RIGHT_POPUP_MENU_SHOW`、`NL_ADD_NEW_ELEMENT`：当前仅空处理；
- 未识别消息返回 `NR_ERR`。

`elib/fnshare.cpp` 保存运行时传入的 `PFN_NOTIFY_SYS`，首次收到系统通知时通过 `NRS_GET_PRG_TYPE` 读取程序类型；并转发用户注册的通知回调。`NotifySys`、`ealloc`、`efree`、`CloneTextData`、`CloneBinData`、`GetBinData` 等辅助函数均依赖易语言运行时 ABI，而非独立实现一套运行时。

### 4.3 静态库路径

`btdownload_static/btdownload_static.vcxproj` 复用根目录所有源文件，配置类型为 `StaticLibrary`。静态编译通过 `__E_STATIC_LIB` 关闭动态库信息表的一部分，并依靠 `btdownload_ProcessNotifyLib_btdownload` 返回命令名、通知函数名和依赖列表。动态库和静态库两套工程没有第二份业务实现，差异主要在编译宏和链接目标。

## 5. 命令接口模型

`btdownload_cmd_typedef.h::BTDOWNLOAD_DEF(_MAKE)` 是命令元数据的唯一集中定义点。该宏被重复展开为：函数声明、函数指针数组、命令名数组、`CMD_INFO` 表。命令函数名按 `btdownload_<英文名>_<索引>_btdownload` 形式拼接。

### 5.1 命令清单

|索引|易语言名称|英文名/实现名|返回类型|参数概要|类别/状态|
|---:|---|---|---|---|---|
|0|构造函数|`con`|空|无|隐藏对象构造|
|1|析构函数|`des`|空|无|隐藏对象析构|
|2|增加新任务|`AddNewTask`|逻辑型|任务信息|BT对象方法|
|3|暂停本任务|`PauseTask`|逻辑型|无|BT对象方法|
|4|继续本任务|`ContinueTask`|逻辑型|可选任务内容|BT对象方法|
|5|停止本任务|`StopTask`|逻辑型|无|BT对象方法|
|6|增加连接|`AddConnect`|逻辑型|地址、端口号|BT对象方法|
|7|减少连接|`DelConnect`|逻辑型|无|BT对象方法|
|8|取下载速度|`GetDownloadRate`|整数型|无|BT对象方法|
|9|取上传速度|`GetUploadRate`|整数型|无|BT对象方法|
|10|`info构造函数`|`StopTask`|空|无|隐藏发布文件信息构造|
|11|`intfo拷贝构造函数`|`StopTask`|空|无|隐藏发布文件信息复制|
|12|`info析构函数`|`StopTask`|空|无|隐藏发布文件信息析构|
|13|分析发布文件|`AnalyseTorrentFile`|发布文件信息|发布文件名|全局命令，类别 1|
|14|制做发布文件|`MakeTorrentFile`|整数型|文件类型、名称、服务器地址、发布路径、块大小、注释、可选创建者|全局命令，类别 1|
|15|`task构造函数`|`StopTask`|空|无|隐藏任务信息构造|
|16|`task拷贝构造函数`|`StopTask`|空|无|隐藏任务信息复制|
|17|`task析构函数`|`StopTask`|空|无|隐藏任务信息析构|
|18|限制下载速度|`SetDownloadRate`|逻辑型|下载速度|BT对象方法|
|19|限制上传速度|`SetUploadRate`|逻辑型|上传速度|BT对象方法|
|20|下载设置|`DownloadSet`|逻辑型|下载设置信息|全局命令，类别 1|
|21|取任务内容|`GetTaskInfo`|逻辑型|传引用任务内容|BT对象方法|
|22|重新检查完整性|`ReChcekWhole`|逻辑型|发布文件名、本地路径、本地文件名、传引用百分比/字节数/任务内容、日志回调|全局命令，类别 1|
|23|取下载号|`GetDownloadNumber`|整数型|无|BT对象方法|
|24|是否停止|`IsStopTask`|逻辑型|无|BT对象方法|
|25|测试代理服务器|`TestProxyServer`|逻辑型|地址、端口|全局命令，类别 1|
|26|添加服务器|`AddTreckerServer`|逻辑型|地址、端口|BT对象方法；英文名拼写为 `Trecker`|
|27|拷贝构造函数|`copy`|空|无|隐藏 BT对象复制|

接口说明中的行为承诺包括：增加任务的“真”不代表已开始；要以“其它日志/下载已全部停止”判断结束；制作 Torrent 的返回码约定为 `0` 成功、`-1` 参数错误、`-2` 编码错误、`-3` 写文件失败、`-4` SHA1 失败；重新检查完整性回传百分比、字节数和任务内容。这些是元数据注释/说明，不是当前仓库内已实现并验证的行为。

### 5.2 参数传递与返回值 ABI

- `PFN_EXECUTE_CMD` 统一签名：`void(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)`。
- `elib/lib2.h` 的 `MDATA_INF` 通过联合字段承载整数、文本、字节集、子程序地址、复合数据和“传引用”指针。
- 复合对象参数使用 `m_pCompoundData`；文本使用 `m_pText`；字节集使用 `m_pBin`；传引用字节集使用 `m_ppBin`；传引用整数/长整数使用 `m_pInt`/`m_pInt64`；回调使用 `m_dwSubCodeAdr`。
- 参数标志由 `ARG_INFO.m_dwState` 表达，如默认值、允许空、传变量、传引用等。
- 当前 `btdownload_cmdDef.cpp` 仅把参数绑定到 `argN` 局部变量，未设置 `pRetData->m_dtDataType` 或返回数据字段。
- 现场还发现若干参数索引与注释序号不一致，例如 `AnalyseTorrentFile` 使用 `pArgInf[0]`、`AddTreckerServer` 使用 `pArgInf[1]`/`[2]`；这应在后续实现或兼容性复核中优先确认，当前不擅自修复。

## 6. 自定义数据类型与数据模型

定义文件：`btdownload_dtType.cpp`。共 8 个类型，其中复合类型 4 个、枚举类型 4 个。

|索引|中文名/英文名|性质|成员/方法|
|---:|---|---|---|
|0|`BT下载` / `BT download`|复合对象|隐藏 `BT对象句柄`（整数）；方法索引 `0-9,18,19,21,23,24,26,27`|
|1|`任务信息` / `task info`|复合数据|`发布文件名`、`本地文件路径`、`本地文件名`、`服务器日志`回调、`上传下载日志`回调、`其它日志`回调、主动连接数、最大连接数、任务内容；方法 `15-17`|
|2|`服务器日志` / `ServerLog`|枚举整数|服务器地址、连接服务器、连接失败、发送请求、接收/分析返回数据、重试时间、重定向等 12 项|
|3|`上传下载日志` / `UlLog`|枚举整数|选 IP、连接、握手、完成百分比、上传、下载、写盘、连接完成等 13 项|
|4|`发布文件信息` / `TorrentFileInfo`|复合数据|服务器列表、注释、建立者、文件目录或名称、总长度、块长度、块数、多文件长度/名称、SHA1、建立时间；方法 `10-12`|
|5|`其它日志` / `OtherLog`|枚举整数|完整性检查后、远程客户端、监听端口、检查完整性中、下载已全部停止 5 项|
|6|`下载设置信息` / `GlobleInfo`|复合数据|每地址连接数、监听端口范围、阻塞值、连接超时、代理类型/地址/端口/用户名/口令、Tracker/Peer 连接超时等 12 项|
|7|`块大小` / `PieceSize`|枚举整数|`KB32`、`KB64`、`KB128`、`KB256`、`KB512`、`KB1024`、`KB2048`，值为 1-7|

### 6.1 日志回调协议

`任务信息` 中的三个回调由元数据约定：

- `服务器日志`：6 个参数，下载号、`ServerLog` 常量、文本/整数/整数、日期时间，返回逻辑型；
- `上传下载日志`：5 个参数，下载号、`UlLog` 常量、连接序号、整数、文本，返回逻辑型；说明要求跨作用域修改时使用易语言“进入许可区/退出许可区”；
- `其它日志`：6 个参数，下载号、`OtherLog` 常量、整数、整数、文本、文本，返回逻辑型。

这些回调定义存在于 `LIB_DATA_TYPE_ELEMENT` 的说明文本中，当前 C++ 命令处理器未调用它们，线程模型和回调取消语义也未在本仓库实现。

### 6.2 持久化与文件模型

仓库没有数据库、配置文件、任务状态文件、缓存目录或序列化实现。Torrent 的字段模型只存在于 `TorrentFileInfo` 元数据；`任务内容` 只作为易语言 `SDT_BIN` 参数/传引用参数描述，未提供实际编码格式、版本、校验或恢复代码。磁盘写入、分片、SHA1 校验和多文件目录遍历均未出现在当前源码中。

## 7. 工程、编译与依赖边界

### 7.1 解决方案

`btdownload.sln` 为 Visual Studio 解决方案格式 12.00（Visual Studio 17），包含：

1. `btdownload`：`DynamicLibrary`；
2. `btdownload_static`：`StaticLibrary`。

解决方案配置为 `Debug/Release x64/x86`，x86 映射到工程的 `Win32` 配置。

### 7.2 动态库工程

`btdownload.vcxproj` 声明 Debug/Release 的 Win32 与 x64 配置，使用 `PlatformToolset=v141`、Windows SDK `10.0.15063.0`、Unicode 字符集。Win32 配置设置 `TargetExt=.fne`、模块定义文件 `Source_btdownload.def`；x64 配置没有同样的 `TargetExt` 与模块定义文件设置，属于待核对的工程差异。源文件为 6 个 `.cpp`（含 `elib/fnshare.cpp`），头文件为 9 个。

### 7.3 静态库工程

`btdownload_static.vcxproj` 复用根目录源文件，目标类型为 `StaticLibrary`。Win32 Debug/Release 明确设置 `__E_STATIC_LIB` 与 `__E_FNENAME=btdownload`；x64 配置的预处理器定义未出现这两个宏，且使用预编译头 `pch.h`，但仓库未提供 `pch.h`。这可能使 x64 静态配置无法按设计编译，需在 Windows/Visual Studio 环境单独验证。

### 7.4 依赖

- 直接依赖：易语言支持库 ABI 头文件及 Windows API/基础 C++ 运行时；
- 仓库内依赖：`elib/` 目录的 8 个头文件和 `fnshare.cpp`；
- 动态库额外依赖：`Source_btdownload.def` 未声明，`LIB_INFO.m_szzDependFiles=NULL`；
- 未发现第三方包管理文件、外部 SDK、网络库、数据库库、测试框架或构建脚本。

## 8. 测试、验证与当前质量状态

### 已完成的只读核验

- 现场扫描真实树：23 个非 `.git` 文件；
- 读取解决方案、动态/静态 `.vcxproj`、两个 `.filters`、两个空 `.user` 文件；
- 读取入口、命令定义/元数据、数据类型、常量表、`elib` ABI 与通知辅助代码；
- 统计命令处理器：28 个函数，均无实际业务语句；
- 核对 `HEAD`、`origin/master` 与远程地址；
- 检索目标树及源码参考库中以 `btdownload` 命名的既有细探材料文件。

### 未执行事项

按当前取证只读建档边界，未进行编译、链接、运行 DLL、安装易语言、网络连接、Tracker/Peer 交互、Torrent 文件生成/解析或测试执行。仓库本身未提供自动化测试，因此不能宣称接口行为通过验证。

### 质量结论

当前可验证的是“易语言支持库注册/描述层”和“空的命令实现骨架”。不能从该仓库验证 BT 下载功能、协议兼容性、并发、断点续传、磁盘一致性、代理、限速、错误码或回调线程安全。

## 9. Git 与版本基线

- 本地分支：`master`；
- 本地提交：`ed6aa59267235ae34ad213da4193c6fc9c2c8218`；
- 本地提交时间：`2022-12-19T16:53:10+08:00`；
- 提交信息：`初始化仓库`；
- 远程：`origin https://gitee.com/JYtechnology/btdownload.git`（fetch/push 相同）；
- 远程默认跟踪：`origin/master`；
- 当前远程跟踪引用与本地 `HEAD` 同为上述提交；当前取证未执行 fetch，不把该引用当作在线远程实时状态；
- 初始工作树干净；本次只新增本文件。

## 10. 既有细探材料、代码地图与证据限制

- 目标根没有 `既有专项文档`、README 或其它旧架构文档；在源码参考库按 `*btdownload*` 文件名检索也未发现独立既有细探材料；因此不存在可吸收后删除的既有细探材料文件。
- 首先调用项目上下文工具时，专属 MCP 返回的项目身份是 `/Users/hekunhua/Documents/Agent/PHP/华世王镞_v3`，与本目标不一致；该结果未用于本归档的源码事实。
- 随后以目标绝对路径调用 `codegraph_explore`，工具明确返回目标没有 `.codegraph/` 索引；本项目没有可用代码地图。
- 因此本文件所有结构、调用链、命令和数据模型结论均来自目标目录的真实文件读取；代码地图状态如实记为“不可用”，没有用其它项目地图冒充证据。

## 11. 后续复核重点

1. 确认 `btdownload_cmdDef.cpp` 是否有意仅提交接口模板，或缺失真正 BT 引擎源码；
2. 追溯 `BT对象句柄` 的宿主实现、对象生命周期和全局任务表；
3. 确认 `任务内容` 的真实序列化格式、版本、校验与断点恢复协议；
4. 复核所有 `pArgInf` 起始索引、返回值填充和 `pRetData` 内存所有权；
5. 在 Windows/Visual Studio 中分别核验 Win32/x64 动态库与静态库工程，重点关注 x64 的 `.def`、`.fne`、`__E_STATIC_LIB`、`__E_FNENAME` 和缺失 `pch.h`；
6. 若找到外部实现，再补充 Tracker HTTP、Peer BT 握手、分片校验、磁盘写入、代理、限速、日志回调和停止/取消调用链；
7. 若要做行为级归档，应新增真实夹具和测试，但这不属于当前取证只读建档。

## 12. 扩展取证：到底座的映射边界

本节是**平台映射建议**，不是把当前仓库没有的 BT 引擎补写成已实现功能。当前源码只能证明支持库 ABI、命令/数据类型元数据和空处理器：`btdownload_cmdDef.cpp:21-248` 的处理器最多把 `pArgInf` 绑定到局部变量；`btdownload_cmdInfo.cpp:20-57` 与 `btdownload_dtType.cpp:35-136` 只描述参数、任务内容、日志事件、代理和超时；`btdownload_dllMain.cpp:29-101` 只装配函数表并处理支持库通知。因此下表的“归属”是未来实现的单链路裁决，不能反推本仓库已有网络、文件或队列实现。

### 12.1 能力命中与归属表

| 源码信号/需求 | 规范归属 | 跨边界只传递 | 当前证据与裁决 |
|---|---|---|---|
| Tracker/Peer 地址、端口、连接、发送/接收、HTTP 重定向、代理 | **网络支持库**提供 DNS/TCP/TLS/HTTP/代理/连接超时等原子能力；BT 模块拥有 Tracker/Peer 协议语义 | 地址、协议参数、`request_id`、截止时间、取消令牌、统一结果；不传 socket/连接对象 | `ServerLog` 元数据列出 `ConnectServer`、`SendGet`、`RecvData`、`HTTPRedirect`（`btdownload_dtType.cpp:51-67`），`GlobleInfo` 列出代理与连接超时（`:119-136`）；当前没有网络调用。归入网络支持库，但需待真实 provider 取证。 |
| Torrent 文件读取、bencode/字段解析、目录遍历、块大小和 SHA-1 | **文件支持库**负责受控文件流、随机读、目录/路径安全和临时文件；摘要计算作为稳定的校验原子能力；BT/Torrent 模块负责字段语义与协议模型 | `artifact_id`/文件引用、路径策略、块范围、摘要结果；不传裸 `FILE*`/句柄 | `TorrentFileInfo` 仅有服务器列表、名称、长度、块长、SHA1 等元数据；`MakeTorrentFile` 注释声明写文件/SHA1 错误（`btdownload_cmdDef.cpp:112-128`），但没有实现。不能把字段表当解析器。 |
| 分片下载、部分写入、随机补块、完成后提交 | **文件支持库**提供有界流写、范围写、`fsync`/原子替换、文件锁/路径校验；BT 模块只决定 piece/block 语义 | `file_session_id`、范围、校验摘要、写入结果、制品引用 | `UlLog`/`OtherLog` 的“写盘”“完整性检查”只是日志常量（`btdownload_dtType.cpp:69-117`）；没有文件打开、偏移、锁、提交或回滚代码。属于缺口。 |
| 断点、`TaskContent`、已下载字节数/百分比、重新检查 | **运行核心**拥有任务状态、检查点提交、恢复和幂等；文件支持库只读写受管检查点/部分文件 | `task_id`、`checkpoint_version`、`artifact_id`、摘要、状态快照 | `ContinueTask` 接收可选 `SDT_BIN`，`GetTaskInfo` 通过 `m_ppBin` 输出，`ReChcekWhole` 通过传引用输出百分比、`INT64` 字节数和二进制任务内容（`btdownload_cmdDef.cpp:34-40,180-206`）；格式、版本、校验和崩溃恢复均未实现。 |
| 多任务排队、并发、暂停/继续/停止、失败重试 | **运行核心**是唯一队列、调度、背压、重试和任务状态 owner；BT 模块不得另建无界线程池或隐式重试 | `task_id`、队列状态、尝试号、幂等键、截止时间、取消原因 | `AddNewTask` 的说明只承诺“加入任务”，并要求通过“其它日志/下载已全部停止”判断结束；暂停/继续/停止只有空处理器（`:21-47`）。归入运行核心，当前未验证。 |
| 日志回调、下载速度、连接数、停止原因 | BT 模块产生领域事件；运行核心统一事件顺序、取消/终态和证据；网关按订阅/流式响应转发 | 事件 envelope（`request_id`、`task_id`、序号、时间、类型、数据） | 三类 `SDT_SUB_PTR` 回调和事件枚举存在元数据，但当前命令处理器没有调用回调（`btdownload_dtType.cpp:35-42`、`btdownload_cmdDef.cpp:188-206`）。回调不是资源 owner，也不能绕过运行核心直写状态。 |
| 易语言外部调用、结果/错误/事件透传 | **统一网关**只做协议解析、能力路由、鉴权、请求 id、结果/事件转发 | JSON/HTTP 中的值、`artifact_id`、`execution_id`/`lease_id`；禁止裸指针、socket、文件流、provider 对象 | 本仓库的 `GetNewInf`/命令表是易语言 ABI，不是 HTTP 网关（`btdownload_dllMain.cpp:31-91`）。网关应适配规范能力，不直接加载该 DLL 内部对象或复制 BT 流程。 |

### 12.2 缺口、裁决和禁止的侧链

| 事项 | 裁决 | 不能采用的做法 | 证据等级 |
|---|---|---|---|
| 网络下载/Tracker/Peer | **建立或复用网络支持库原子能力**，BT 模块只组合协议流程 | 网关直接 `curl`/socket；每个任务自己维护代理、连接池和重试 | 当前只有日志/配置声明；待核 |
| 文件流/分片/临时文件 | **建立或升级文件支持库**，把部分文件、检查点和最终制品纳入统一资源治理 | 模块直接打开任意路径；用内存或 Base64 承载无界下载；以改名代替原子提交但不校验 | 当前无文件 API；待核 |
| 断点与 `TaskContent` | **由运行核心定义版本化检查点契约**，文件支持库执行落盘；不能把 `SDT_BIN` 本身当稳定格式 | 以指针/对象地址当断点；没有版本、摘要、幂等键的自由格式二进制；多个 owner 同时写任务状态 | 参数元数据存在，实现缺失 |
| 失败重试 | **运行核心统一 attempt/backoff/deadline/idempotency 策略**；网络支持库仅报告可重试的传输原因，文件支持库仅报告 I/O/锁/空间原因 | 网络层、模块层、网关层各重试一次造成乘法重试；对已提交的非幂等写入盲重试 | 仅有失败日志常量和注释错误码；待核 |
| 句柄/租约 | **用不透明 `execution_id`/`lease_id`，由运行核心签发、校验、过期和回收** | 暴露 `BT对象句柄` 的真实指针、Windows `HANDLE`、socket 或 provider 对象；租约过期后允许旧句柄复活 | `BT对象句柄` 只是隐藏 `SDT_INT` 成员（`btdownload_dtType.cpp:27-32`），没有生命周期实现 |
| 网关与长任务 | **同步小结果；长任务返回任务/租约/制品引用，事件走受控流** | 网关持有任务线程、文件流或网络连接；客户端断开即把业务状态误判成取消；网关自行清理 provider | 当前没有 HTTP 实现；平台边界建议 |

本项目的吸收结论是：可吸收命令语义、日志分类、代理/超时字段和 `TaskContent` 的“需要检查点”信号，作为候选契约输入；不能吸收其隐藏整数句柄、空处理器或未定义二进制格式作为底座实现。网络、文件、运行核心和网关均应先命中唯一 owner，再由 BT/Torrent 模块装配，不能把该支持库仓库升级成第二套下载内核。

## 13. 下载、文件流、断点、队列与重试的单链路

### 13.1 推荐调用链

```text
调用方
  → 统一网关（能力路由/鉴权/request_id/结果与事件透传）
  → 运行核心（task_id、队列、租约、deadline、取消、attempt、状态 owner）
  → BT/Torrent 模块（解析元数据、选择 Tracker/Peer、piece 调度、领域事件）
  → 网络支持库（连接/代理/HTTP 或 Peer 字节流/超时）
  → 文件支持库（安全路径/临时文件/范围写/检查点/摘要/原子提交）
  → 系统 API 或受管 provider
  → 统一结果、事件、制品引用和释放证据
```

网关不应传输无界文件内容，也不应持有网络连接或文件流；大文件以受管 `artifact_id`/临时文件引用和大小、摘要、有效期返回。运行核心负责一次任务的 admission、排队、并发预算和终态；模块负责领域决策；支持库负责一次网络/文件操作的可验证资源闭合。

### 13.2 断点与临时文件契约（平台建议，非当前实现）

建议把一个下载任务拆成四类不透明标识：

| 标识 | owner | 作用 | 过期/提交规则 |
|---|---|---|---|
| `task_id` | 运行核心 | 跨重启的业务任务身份 | 只增不复用；终态仍可查询证据 |
| `execution_id` | 运行核心 | 某次执行/尝试的身份 | provider 崩溃后标记 lost，不复活旧执行 |
| `lease_id` | 运行核心 | 某调用者在有限 TTL 内操作任务的授权 | 过期后所有操作返回 `EXECUTION_HANDLE_EXPIRED`；释放幂等 |
| `artifact_id` | 文件支持库/制品 owner | `.part`、检查点、最终文件或报告的受管引用 | 包含摘要、大小、路径权限和有效期；最终提交后旧临时引用只读或回收 |

文件支持库内部可以使用任务目录、部分文件、检查点文件、piece bitmap、锁和临时目录，但这些不是跨网关的公共对象。建议写入顺序为：写临时块 → 校验块/范围 → 持久化检查点版本 → `fsync`（按实现能力）→ 原子提交最终制品；恢复时只接受版本、长度、摘要和文件状态一致的检查点，孤儿临时目录进入运行核心的回收队列。当前仓库没有任何上述文件或检查点实现，不能声称支持断点续传。

### 13.3 失败与重试矩阵

| 失败场景 | 记录 owner | 默认动作 | 是否可重试 |
|---|---|---|---|
| DNS/连接建立失败、代理拒绝、Peer/Tracker 断线 | 网络支持库报告；运行核心计 attempt | 关闭本次连接，保留任务状态，按截止时间和退避再次选端点 | 通常可重试；必须受总 deadline、次数和端点预算限制 |
| HTTP 429/5xx、Tracker 重定向 | 网络支持库解析状态；BT 模块决定端点/协议语义 | 记录响应和 `Retry-After`（如有），不得把重定向变成无限跳转 | 依状态可重试；4xx 参数/权限错误通常不可重试 |
| 接收中途断流、块长度不符 | 网络支持库终止流；BT 模块丢弃本块；文件支持库不得提交不完整范围 | 回滚未提交范围，保留已确认块/检查点 | 可重试，但不能重复计入已提交字节 |
| 文件权限、磁盘满、锁冲突、部分写入 | 文件支持库报告具体阶段和偏移；运行核心冻结或失败任务 | 关闭流、回滚临时写、保留可诊断证据；空间/权限修复后才允许人工恢复 | 磁盘满/权限通常不可自动重试；瞬时锁可有限重试 |
| SHA-1/块摘要不匹配 | 文件支持库/摘要能力报告；BT 模块标记坏块 | 不提交该块，清除其完成位并重新取源；超过预算转失败 | 可重试，但不能掩盖源数据持续损坏 |
| 队列满、并发/资源预算超限 | 运行核心 | 背压、排队拒绝或延迟 admission；不在网关无限等待 | 由调用方按 `retry_after` 重试，不能在各层叠加 |
| deadline、主动取消 | 运行核心发出取消；网络/文件在安全点协作退出 | 停止新工作、排空队列、关闭连接、提交或回滚明确状态、释放租约 | 只有幂等且旧执行已确认终止时可重试 |
| provider/宿主崩溃 | 运行核心监督器 | 隔离 `execution_id`，回收进程组/端口/句柄/临时目录，读回检查点后决定恢复 | 可恢复需重新 admission；不得复用旧句柄或假报成功 |
| 网关客户端断开 | 网关记录传输断开；运行核心仍拥有任务状态 | 默认只断开观察者，不自动取消业务；显式取消才改变任务状态 | 查询/订阅可重连；下载执行不因观察者断开而重复提交 |

重试只允许有一个策略 owner：网络支持库可以做连接级、幂等且有界的传输重试，但必须把尝试结果交给运行核心；文件支持库不能擅自重放已提交写入；网关不得再包一层通用重试。返回结果至少应区分 `retryable`、`attempt`、`deadline`、`cancelled`、`checkpoint_version` 和 `resource_release`。

## 14. 句柄、租约与资源生命周期

### 14.1 句柄契约

当前 `BT下载` 类型的“BT对象句柄”是隐藏整数成员，且 `con/des/copy` 命令只是元数据对应的空函数（`btdownload_dtType.cpp:27-32`、`btdownload_cmdDef.cpp:6-17,242-248`）。因此不能把它当作已经可用的对象系统。底座若保留易语言式对象体验，应在网关和运行核心之间改造成不透明句柄：

```text
创建/提交 → execution_id + lease_id
操作       → 校验 lease、能力、版本、deadline、并发归属
续租       → 仅在任务仍健康且未排空时延长 TTL
释放       → revoke lease → 排空 → 关闭内部资源 → 写释放证据
过期/崩溃  → 旧句柄不可复活；运行核心负责回收并返回过期/丢失错误
```

租约是授权和生命周期边界，不是任务状态本身；`task_id` 可以在重启后继续存在，`lease_id` 和 `execution_id` 不能跨失效状态复用。默认一个租约单并发，所有操作都携带 `request_id`、`deadline` 和幂等键；释放必须幂等，重复 `close/release` 只能返回已释放状态，不能二次 kill/close。

### 14.2 资源生命周期表

| 资源 | 创建/持有者 | 成功释放 | 业务失败/超时/取消 | 崩溃后的处理 | 当前仓库证据 |
|---|---|---|---|---|---|
| `execution_id`/`lease_id` | 运行核心签发和持有 | 任务终态后 revoke 或进入明确、有界缓存 | 停止 admission，排空并 revoke | 监督器标记 lost，禁止旧句柄复活 | 只有隐藏整数句柄元数据；未实现 |
| Tracker/Peer socket、代理会话 | 网络支持库 | 任务完成或连接替换时 close | deadline/取消时中断安全阻塞调用 | 由受管 provider/进程组回收并核对端口 | 只有地址/代理/超时字段；无 socket |
| Torrent/部分文件/文件流 | 文件支持库 | flush/校验/原子提交后关闭流 | 关闭流，回滚或保留带状态的 `.part`，不伪报完成 | 扫描孤儿目录/锁，按检查点恢复或清理 | 无文件打开和写入代码 |
| 检查点/任务内容 | 运行核心写 owner，文件支持库落盘 | 新版本提交并保留摘要/版本 | 失败写入不得覆盖最后一个有效版本 | 只读最后一致版本；坏版本隔离 | `SDT_BIN` 仅参数形状（`cmdDef.cpp:180-204`） |
| 队列项/worker/线程 | 运行核心 | 终态、排空、join 后删除或归档 | 取消令牌到达检查点，阻塞任务转受管进程 | 回收进程组、队列项和资源预算 | 没有队列/线程实现 |
| 易语言日志回调/事件订阅 | 运行核心事件 owner；调用方只订阅 | 任务终态后关闭订阅 | 回调异常不得阻塞核心；记录投递失败 | 断开订阅，不影响任务回收 | 元数据有 `SDT_SUB_PTR` 和临界区说明，但当前未调用 |
| 网关请求/流 | 网关持有传输连接；运行核心持有业务任务 | 返回结果/关闭流；任务不等于连接 | 连接断开默认只撤销观察者 | 网关进程重启后靠 `task_id` 查询 | 当前无 HTTP 网关 |

### 14.3 四种终态验收

每个未来实现的下载能力都必须分别验收：

1. **正常完成**：结果/制品摘要正确；队列项终态明确；网络连接、文件流、租约和临时目录已释放或进入有界缓存。
2. **业务失败**：错误码、失败阶段和最后一个有效检查点可读；未提交部分不冒充最终文件；所有句柄/流/锁释放。
3. **主动取消或超时**：真实停止新工作并排空；阻塞 I/O 终止；任务状态只能是 `cancelled`/`timed_out`；临时资源和租约有回收证据。
4. **宿主/provider 崩溃**：可见退出码/信号；进程组、端口、文件锁、临时目录和句柄无无界残留；若允许恢复，必须从版本化检查点重新 admission，而非继续使用旧句柄。

## 15. L0-L4 分层裁决

为本项目的底座映射采用以下五级，不把易语言支持库 ABI 层级误认为下载引擎层级：

| 层级 | owner | 应放入 btdownload 相关能力 | 明确不放入 | 当前状态 |
|---|---|---|---|---|
| **L0 原子系统能力** | 平台基础支持库/系统 API 适配 | 字节缓冲、时间/截止时间、路径规范化、摘要、错误分类、内存/编码和安全随机数等可重复原子操作 | Torrent 任务状态、网关请求、provider 对象和业务重试 | 本仓库仅通过 `elib` ABI 借用运行时内存/数据类型；无下载原子实现 |
| **L1 网络与文件支持库** | 唯一网络支持库 + 唯一文件支持库 | Tracker/Peer 传输所需连接/代理/超时；受控文件流、范围读写、临时目录、锁、检查点、摘要校验、原子提交 | 任务队列、BT 领域策略、HTTP 网关、裸句柄穿透 | 元数据提供线索；真实实现缺失，主要是待建/待复用能力 |
| **L2 BT/Torrent 模块库** | BT 领域模块 | Torrent 字段模型、bencode/Tracker/Peer 语义、piece 选择、任务事件、模块级错误到统一契约的转换 | 自建连接池/文件写入器/全局队列/进程监督器 | 当前只有 `TorrentFileInfo`、命令和日志声明；模块实现未发现 |
| **L3 运行核心** | 执行协调器/任务状态 owner | admission、队列与背压、并发/资源预算、`task_id`/`execution_id`/`lease_id`、deadline、取消、attempt/backoff、检查点恢复、provider 健康/崩溃回收 | 具体 Tracker/Peer 协议、路径拼接、HTTP JSON、易语言 UI 回调直连 | 当前支持库仅向易语言运行时注册函数；无运行核心实现 |
| **L4 统一网关与适配层** | 单一网关 | 鉴权、能力 id/契约版本、请求解析、结果/事件/制品引用转发、查询/订阅和错误透传 | 加载 DLL 内部对象、持有 socket/文件流、复制重试/队列、直接访问第三方 | `GetNewInf` 是易语言 ABI 入口，不是 L4 网关；当前无 HTTP/API 实现 |

### 15.1 单链路验收契约（待实现时使用）

建议能力契约至少包含：`capability_id`、`contract_version`、`request_id`、`task_id`/`execution_id`、`lease_id`（如有）、参数/制品引用、`deadline`、`idempotency_key`、资源预算、取消信号。结果至少包含：`success`、值或 `artifact_id`、`error_code`、`retryable`、`attempt`、`checkpoint_version`、`evidence` 和 `resource_release`。这些字段是平台建议，不是当前 `CMD_INFO` 已经提供的 HTTP 契约。

网关 → 运行核心 → BT 模块 → 网络/文件支持库的每个箭头都必须只有一个契约 owner；任何“模块直接连 Tracker”“网关直接写临时文件”“支持库自己改变任务状态”“回调自行续租”都属于侧链，应在实现评审中拒绝。

## 16. 扩展取证真假验证表与剩余风险

| 结论 | 源码存在 | 测试/构建证据 | 当前取证验证 | 结论等级 |
|---|---|---|---|---|
| 28 个命令、8 个自定义类型、函数指针表和 `GetNewInf` 注册 | 存在：`btdownload_cmd_typedef.h`、`btdownload_cmdInfo.cpp`、`btdownload_dtType.cpp`、`btdownload_dllMain.cpp` | 无测试工程；当前取证未编译 | 只读逐文件核对并统计处理器 | 源码事实，静态已确认 |
| Tracker/Peer、代理、连接超时、下载/上传日志等接口意图 | 存在于说明和元数据 | 没有调用/集成测试 | 对 `cmdDef`/`dtType` 逐项核对 | 声明/候选契约，不等于实现 |
| 网络请求、文件流、分片、断点、临时文件、队列、失败重试 | 未发现实现 | 无行为测试或运行证据 | 当前仓库静态搜索和处理器读取 | 未实现/不可从本仓库确认 |
| 句柄、租约、释放、超时取消、崩溃回收 | 未发现实现；只有隐藏整数成员、构造/析构/复制命令元数据 | 无生命周期测试 | 读取 `BT下载` 类型、空处理器、通知函数 | 平台待建/待核，不能宣称支持 |
| L0-L4 单链路映射 | 不是当前源码事实 | 未执行平台联调 | 基于真实字段和空实现提出归属 | 平台建议，需在目标底座验收 |

当前取证没有编译、启动、连接 Tracker/Peer、生成 Torrent、写入磁盘或调用外部网关；没有把注释中的返回码、历史接口说明、子代理回执或“项目上下文”工具结果当作运行证据。首次 `project_context` 错绑到 `/Users/hekunhua/Documents/Agent/PHP/华世王镞_v3`，已作为环境问题保留，不用于本项目事实。

## 17. 小型仓规模说明与边界

`btdownload` 只有 23 个跟踪文件，源码是下载库的命令/类型元数据骨架，并未包含 BitTorrent 协议、网络循环或磁盘调度实现。逐文件职责为：

- `btdownload_cmdDef.cpp`：命令处理器表；当前处理器是否为空必须以源码为准。
- `btdownload_cmdInfo.cpp`：命令名称、参数个数、返回类型和说明。
- `btdownload_cmd_typedef.h`：函数指针和自定义参数布局。
- `btdownload_dtType.cpp`：下载任务等类型的登记，不等于任务对象实现。
- `btdownload_const.cpp`：常量定义；`btdownload_dllMain.cpp`：导出与 `GetNewInf`。
- `include_btdownload_header.h`、`Source_btdownload.def`：头文件聚合与 DLL 导出契约。
- `btdownload.vcxproj`、`btdownload_static/...vcxproj`：动态/静态构建配置。
- `elib/*`：易语言宿主 ABI、通知和内存桥接。

仓库没有测试、Tracker/Peer 夹具、Torrent 样本、日志配置或第三方依赖锁定。未在 Windows/MSVC 中编译、加载或执行网络操作，无法确认连接、分片、断点、重试、取消、句柄释放和异常隔离。文档规模与 23 文件的极小仓事实相符，不能把元数据声明写成可运行下载器。
