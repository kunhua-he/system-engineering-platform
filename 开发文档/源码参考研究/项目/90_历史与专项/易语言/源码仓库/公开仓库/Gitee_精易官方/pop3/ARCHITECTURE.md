# pop3 架构与实现建档

## 1. 文档范围与结论

- **仓库**：`Gitee_精易官方/pop3`
- **项目类型**：面向易语言的 Windows POP3 邮件接收支持库源码骨架，提供动态库工程 `pop3` 与静态库工程 `pop3_static`。
- **首轮结论**：仓库已经实现了易语言支持库的命令、参数、自定义数据类型、库信息和通知协议元数据注册，也生成了 33 个命令入口函数；但 `pop3_cmdDef.cpp` 中 33 个命令函数的函数体均为空，未见 POP3 socket、认证、协议收发、邮件 MIME 解析、附件解析、回调调度或错误状态存储实现。因此，不能把本仓库描述为已实现可用的 POP3 客户端；更准确的定位是**支持库接口/元数据模板与未完成的命令入口层**。
- **证据等级**：
  - **源码已实现**：元数据静态表、命令入口声明/定义、易语言 `LIB_INFO` 注册、通知分发骨架、数组/类型索引表。
  - **仅声明或仅生成入口**：POP3 连接、收信、解析、删除、代理、回调等业务命令；函数虽然有签名并在命令表中注册，但没有业务逻辑和返回值写入。
  - **未验证**：Visual Studio 编译、`.fne`/静态库产物、易语言 IDE 加载、真实 POP3 服务器交互、所有命令运行行为。
- **范围约束**：当前核对只新增本文件；未修改源码、工程、依赖、测试、配置或 Git 历史；未删除任何旧细探文件。仓库内未发现 `README`、测试文件、`AGENTS.md` 或 `细探-*.md`。

## 2. 中文文本流程图

### 2.1 动态支持库加载与命令调用

```text
易语言 IDE/运行时
    │
    │ LoadLibrary 加载 pop3 动态支持库
    ▼
Source_pop3.def
    │ 只导出 GetNewInf
    ▼
GetNewInf()
    │ 返回 g_LibInfo_pop3_global_var
    ▼
LIB_INFO
    ├─ 库身份/版本/语言/系统要求
    ├─ 3 个自定义数据类型
    ├─ 1 个命令分类：0000邮件接收
    ├─ 33 个 CMD_INFO 命令描述
    ├─ g_cmdInfo_pop3_global_var_fun[33] 命令函数指针
    └─ pop3_ProcessNotifyLib_pop3 通知函数
    │
    │ 用户调用“连接收信服务器”等易语言命令
    ▼
命令索引 → g_cmdInfo_pop3_global_var_fun[index]
    │
    ▼
pop3_<英文名>_<index>_pop3(pRetData, nArgCount, pArgInf)
    │
    ├─ 当前实现：部分函数只把 pArgInf 转成本地变量
    └─ 当前缺失：网络连接、协议命令、数据解析、pRetData 返回值、错误状态
```

### 2.2 通知与易语言运行时内存通道

```text
易语言系统
    │ 通过 NL_SYS_NOTIFY_FUNCTION 下发 PFN_NOTIFY_SYS
    ▼
pop3_ProcessNotifyLib_pop3()
    │ 转发给 fnshare.cpp::ProcessNotifyLib()
    ▼
保存 s_pfnNotifySys
    │ 首次通知时调用 NotifySys(NRS_GET_PRG_TYPE,...)
    ▼
NotifySys()
    │ 调用易语言提供的系统回调
    ├─ NRS_MALLOC/NRS_MFREE：易语言托管内存
    └─ NRS_GET_PRG_TYPE：调试/发布版本查询
```

### 2.3 元数据生成链

```text
POP3_DEF(_MAKE) 宏（pop3_cmd_typedef.h）
    ├─ POP3_DEF_CMD       → pop3_cmdDef.cpp 中 33 个函数声明/入口
    ├─ POP3_DEF_CMDINFO   → pop3_cmdInfo.cpp 中 33 个 CMD_INFO
    ├─ POP3_DEF_CMD_PTR   → pop3_dllMain.cpp 中 33 个 PFN_EXECUTE_CMD
    └─ POP3_DEF_CMDNAME_STR → 静态编译命令名数组

pop3_dtType.cpp
    └─ 自定义数据类型、成员命令索引、枚举成员

pop3_dllMain.cpp
    └─ 将上述表组装成 LIB_INFO，并由 GetNewInf() 暴露
```

## 3. 项目结构与真实分层

```text
pop3/
├── pop3.sln                         Visual Studio 解决方案；动态库 + 静态库
├── pop3.vcxproj                     动态库项目，输出目标类型 DynamicLibrary
├── pop3_static/
│   └── pop3_static.vcxproj          静态库项目，输出目标类型 StaticLibrary
├── Source_pop3.def                  动态库模块定义文件，只导出 GetNewInf
├── include_pop3_header.h            公共聚合头；声明元数据和命令入口
├── pop3_cmd_typedef.h               POP3_DEF 命令总表（唯一命令清单）
├── pop3_cmdInfo.cpp                 参数表与 CMD_INFO 元数据
├── pop3_cmdDef.cpp                  33 个命令入口函数（当前为空实现）
├── pop3_dtType.cpp                  MailInfo/AttachmentInfo/CmdType 元数据
├── pop3_const.cpp                   常量表，当前数量为 0
├── pop3_dllMain.cpp                  DLL 入口、LIB_INFO、命令函数表、通知处理
└── elib/                            易语言支持库 ABI/运行时公共头与通知辅助代码
    ├── lib2.h                       LIB_INFO、CMD_INFO、MDATA_INF、数据类型等 ABI
    ├── fnshare.h / fnshare.cpp      系统通知、内存辅助、调试版本状态
    ├── lang.h                       语言编码版本宏，当前为 GBK
    ├── krnllib.h                    系统核心支持库常量和版本标识
    ├── mtypes.h                     Windows 风格基础类型兼容定义
    ├── untshare.h                    窗口/组件辅助代码（本项目未使用业务路径）
    └── PublicIDEFunctions.h          IDE 公共函数声明
```

### 3.1 工程收录关系

两个 `.vcxproj` 均直接编译同一组源文件：`elib/fnshare.cpp`、`pop3_cmdDef.cpp`、`pop3_cmdInfo.cpp`、`pop3_const.cpp`、`pop3_dllMain.cpp`、`pop3_dtType.cpp`，区别主要是输出类型和预处理宏。动态工程通过 `Source_pop3.def` 配置 Win32 模块导出；静态工程通过 `__E_STATIC_LIB` 选择静态编译路径（但仅在 Win32 配置中显式定义，见第 10 节）。

## 4. 模块职责

| 模块 | 真实职责 | 当前状态 | 证据 |
|---|---|---|---|
| `pop3_cmd_typedef.h` | 以一个 `POP3_DEF(_MAKE)` 宏清单集中定义 33 个命令的索引、中文名、英文名、返回类型、分类、参数数量和参数表起点 | 已实现元数据源；不是业务实现 | `pop3_cmd_typedef.h:3-46` |
| `include_pop3_header.h` | 引入 `elib` ABI；声明动态模式全局表；用 `POP3_DEF_CMD` 展开所有命令声明 | 已实现 | `include_pop3_header.h:3-24` |
| `pop3_cmdInfo.cpp` | 定义 23 个参数描述项；按命令表生成 33 个 `CMD_INFO` | 已实现描述表；含一处静态库 TODO | `pop3_cmdInfo.cpp:3-79` |
| `pop3_cmdDef.cpp` | 提供 33 个 `PFN_EXECUTE_CMD` 兼容入口；部分入口读取参数到局部变量 | 入口已生成，业务逻辑未实现 | `pop3_cmdDef.cpp:6-273` |
| `pop3_dtType.cpp` | 定义 `MailInfo`、`AttachmentInfo`、`CmdType` 三种易语言数据类型及成员/方法索引 | 已实现元数据；无对象实际存储/解析逻辑 | `pop3_dtType.cpp:3-97` |
| `pop3_const.cpp` | 提供支持库常量表 | 当前为空表，数量为 0 | `pop3_const.cpp:14-18` |
| `pop3_dllMain.cpp` | 动态库入口、库描述、命令函数指针数组、`GetNewInf`、系统通知处理、静态编译命令名 | 骨架已实现；资源释放/业务初始化为空 | `pop3_dllMain.cpp:6-178` |
| `elib/fnshare.cpp` | 保存易语言系统通知回调；转发通知；查询调试/发布版本；提供用户通知回调链 | 辅助运行时已实现 | `elib/fnshare.cpp:7-71` |
| `elib/lib2.h` | 定义易语言支持库 ABI 的命令、参数、数据类型、运行时数据、库信息结构 | 外部 ABI 依赖，非本项目业务 | `elib/lib2.h:266-364, 369-390, 693-729, 753-824, 1229-1315` |

## 5. 命令与接口清单

### 5.1 统一命令元数据

`POP3_DEF` 在 `pop3_cmd_typedef.h:13-45` 中给出完整清单。索引是命令函数表和 `MailInfo`/`AttachmentInfo` 成员索引的共同基础；命令名通过 `POP3_NAME` 组合为 `pop3_<英文名>_<索引>_pop3`（宏定义见 `pop3_cmd_typedef.h:3-9`）。所有命令状态都带 `_CMD_OS(__OS_WIN)`，因此元数据声明为 Windows 命令。

### 5.2 对象类型 `MailInfo` 的成员命令

成员索引来自 `pop3_dtType.cpp:5-10`，对应 `POP3_DEF` 命令索引：

| 命令索引 | 易语言名 | 英文入口 | 返回类型 | 状态 |
|---:|---|---|---|---|
| 0 | 构造函数 | `pop3_MailInfo_0_pop3` | `_SDT_NULL` | 入口空实现 |
| 1 | 拷贝构造函数 | `pop3_CopyMailInfo_1_pop3` | `_SDT_NULL` | 入口空实现 |
| 2 | 析构函数 | `pop3_MailInfo_2_pop3` | `_SDT_NULL` | 入口空实现 |
| 3 | 取发件人地址 | `pop3_GetSendAddress_3_pop3` | `SDT_TEXT` | 入口空实现 |
| 4 | 取主题 | `pop3_GetSubject_4_pop3` | `SDT_TEXT` | 入口空实现 |
| 5 | 取日期 | `pop3_GetDate_5_pop3` | `SDT_DATE_TIME` | 入口空实现 |
| 6 | 取大小 | `pop3_GetSize_6_pop3` | `SDT_INT` | 入口空实现 |
| 7 | 取文本内容 | `pop3_GetTextContent_7_pop3` | `SDT_TEXT` | 入口空实现 |
| 8 | 取附件个数 | `pop3_GetAttNum_8_pop3` | `SDT_INT` | 入口空实现 |
| 9 | 取附件 | `pop3_GetAttachment_9_pop3` | `MAKELONG(0x02, 0)` 数组返回 | 入口空实现 |
| 21 | 取发件人名称 | `pop3_GetSenderName_21_pop3` | `SDT_TEXT` | 入口空实现 |
| 22 | 取回复地址 | `pop3_GetReplyAddress_22_pop3` | `SDT_TEXT` | 入口空实现 |
| 23 | 取原始信息 | `pop3_GetOriMessage_23_pop3` | `SDT_TEXT` | 入口空实现 |
| 26 | 取超文本内容 | `pop3_GetHTMLContent_26_pop3` | `SDT_TEXT` | 入口空实现 |

`MailInfo` 的元数据成员见 `pop3_dtType.cpp:20-35`，包含发件人地址、主题、日期、大小、文本内容、附件个数、附件信息、发件人姓名、回复地址、原始信息、超文本内容。所有成员均带 `LES_HIDED`，说明其主要作为支持库内部/对象成员描述，而不是普通用户可见的数据成员。

### 5.3 对象类型 `AttachmentInfo` 的成员命令

成员索引来自 `pop3_dtType.cpp:13-17`，对应 `POP3_DEF` 命令索引：

| 命令索引 | 易语言名 | 英文入口 | 返回类型 | 状态 |
|---:|---|---|---|---|
| 16 | 取大小 | `pop3_GetAttSize_16_pop3` | `SDT_INT` | 入口空实现 |
| 17 | 取类型 | `pop3_GetAttType_17_pop3` | `SDT_TEXT` | 入口空实现 |
| 18 | 取文件名 | `pop3_GetAttFilename_18_pop3` | `SDT_TEXT` | 入口空实现 |
| 19 | 取编码方式 | `pop3_GetAttEncode_19_pop3` | `SDT_TEXT` | 入口空实现 |
| 20 | 取数据 | `pop3_GetAttData_20_pop3` | `SDT_BIN` | 入口空实现 |
| 27 | 取是否嵌入式附件 | `pop3_GetIsRelate_27_pop3` | `SDT_BOOL` | 入口空实现 |
| 28 | 取名称 | `pop3_GetName_28_pop3` | `SDT_TEXT` | 入口空实现 |

`AttachmentInfo` 的声明式字段见 `pop3_dtType.cpp:38-49`。`取数据` 声明为字节集，未发现任何附件数据生成、释放或 MIME 解码代码。

### 5.4 全局邮件命令

| 命令索引 | 易语言命令 | 英文入口 | 参数 | 返回类型 | 当前实现证据 |
|---:|---|---|---:|---|---|
| 10 | 连接收信服务器 | `pop3_ConnectPop3Server_10_pop3` | 6 | `SDT_BOOL` | 仅读取 6 个参数到局部变量；`pop3_cmdDef.cpp:84-93` |
| 11 | 断开收信服务器 | `pop3_DisConnectPop3Server_11_pop3` | 0 | `_SDT_NULL` | 空函数体；`pop3_cmdDef.cpp:97-100` |
| 12 | 获取邮件信息 | `pop3_GetMailInfo_12_pop3` | 2 | `SDT_BOOL` | 仅取得两个输出指针；未写入；`pop3_cmdDef.cpp:105-110` |
| 13 | 获取邮件大小 | `pop3_GetMailSize_13_pop3` | 2/3 | `SDT_BOOL` | 仅取得参数；未填数组/返回值；`pop3_cmdDef.cpp:116-122` |
| 14 | 接收邮件 | `pop3_ReceiveMail_14_pop3` | 1 | `MAKELONG(0x01, 0)` | 仅读取邮件序号；未构造 `MailInfo`；`pop3_cmdDef.cpp:126-130` |
| 15 | 取邮件错误信息 | `pop3_GetMailErrorMsg_15_pop3` | 0 | `SDT_TEXT` | 空函数体；`pop3_cmdDef.cpp:134-137` |
| 24 | 删除邮件 | `pop3_DeleteMail_24_pop3` | 1 | `SDT_BOOL` | 仅读取邮件序号；未发送命令；`pop3_cmdDef.cpp:197-201` |
| 25 | 复位邮件 | `pop3_ResetMail_25_pop3` | 0 | `SDT_BOOL` | 空函数体；`pop3_cmdDef.cpp:205-208` |
| 29 | 接收邮件序号 | `pop3_GetMailNo_29_pop3` | 2 | `SDT_BOOL` | 仅取得序号参数和数组指针；未写入；`pop3_cmdDef.cpp:234-239` |
| 30 | 接收邮件前几行 | `pop3_GetMailTop_30_pop3` | 2 | `MAKELONG(0x01, 0)` | 仅读取两个整数；未请求服务器；`pop3_cmdDef.cpp:244-249` |
| 31 | 注册邮件接收回调函数 | `pop3_SetMailRecvCallBack_31_pop3` | 1 | `SDT_BOOL` | 仅读取 `m_dwSubCodeAdr`；未保存回调；`pop3_cmdDef.cpp:253-257` |
| 32 | 设置代理服务器 | `pop3_SetProxyServer_32_pop3` | 5 | `SDT_BOOL` | 仅读取 5 个参数；未保存或使用；`pop3_cmdDef.cpp:265-273` |

### 5.5 参数描述与默认值

`pop3_cmdInfo.cpp:28-58` 定义 23 个 `ARG_INFO`，关键参数如下：

| 参数序号 | 名称 | 类型 | 默认值/标志 | 使用命令 |
|---:|---|---|---|---|
| 0 | 收信邮件服务器地址 | `SDT_TEXT` | 无 | 连接 |
| 1 | 端口号 | `SDT_INT` | 110，`AS_HAS_DEFAULT_VALUE` | 连接 |
| 2 | 用户名 | `SDT_TEXT` | 无 | 连接 |
| 3 | 密码 | `SDT_TEXT` | 无 | 连接 |
| 4 | 最长等待时间 | `SDT_INT` | 30000 毫秒，`AS_HAS_DEFAULT_VALUE` | 连接 |
| 5 | 重试次数 | `SDT_INT` | 3，`AS_HAS_DEFAULT_VALUE` | 连接 |
| 6/7 | 个数/大小 | `SDT_INT` | `AS_RECEIVE_VAR` | 获取邮件信息输出 |
| 8 | 第几封 | `SDT_INT` | -1，`AS_HAS_DEFAULT_VALUE` | 获取邮件大小 |
| 9 | 大小 | `SDT_INT` | `AS_RECEIVE_VAR_OR_ARRAY` | 获取邮件大小输出 |
| 10 | 总数 | `SDT_INT` | 空默认值 | 获取邮件大小 |
| 11 | 第几封 | `SDT_INT` | 无 | 接收邮件 |
| 12 | 第几封 | `SDT_INT` | 无 | 删除邮件 |
| 13/14 | 第几封/序号 | `SDT_INT`/`SDT_TEXT` | 第几封默认 -1；序号为变量或数组 | 接收邮件序号 |
| 15/16 | 第几封/共几行 | `SDT_INT` | 无 | 接收邮件前几行 |
| 17 | 函数地址 | `SDT_SUB_PTR` | 0 表示取消 | 注册回调 |
| 18-22 | 类型/地址/端口/用户名/口令 | 混合 | 类型默认 0 | 设置代理服务器 |

注意：参数默认值和说明只代表编辑器元数据；因为对应命令函数没有逻辑，不能据此推断运行时会连接服务器、重试或写出结果。

## 6. 数据模型与持久化边界

### 6.1 易语言可见数据类型

| 类型 | 类型标识 | 成员/枚举 | 源码事实 |
|---|---|---|---|
| `MailInfo` | `_DT_OS(__OS_WIN)` | 11 个元数据成员；14 个成员命令索引 | `pop3_dtType.cpp:5-35,75-81` |
| `AttachmentInfo` | `_DT_OS(__OS_WIN)` | 7 个元数据成员；7 个成员命令索引 | `pop3_dtType.cpp:12-17,38-49,82-88` |
| `CmdType` | `_DT_OS(__OS_WIN) \| LDT_ENUM` | 11 个整数枚举值，0 至 10 | `pop3_dtType.cpp:51-67,89-95` |

`CmdType` 枚举值为：等待接收数据 `0`、验证用户名 `1`、验证口令 `2`、接收邮件 `3`、获取邮件信息 `4`、获取邮件大小 `5`、删除邮件 `6`、重置邮件 `7`、获取邮件序号 `8`、接收邮件前几行 `9`、其它 `10`。

### 6.2 运行时参数数据模型

易语言 ABI 的 `MDATA_INF` 在 `elib/lib2.h:780-824` 定义为一字节对齐结构，union 既可承载基本值，也可承载文本、字节集、复合数据、数组和变量地址；`m_dtDataType` 表示实际类型。当前命令入口实际使用的字段包括：

- `m_pText`：文本参数，如服务器地址、用户名、密码、代理地址。
- `m_int`：整数参数，如端口、邮件序号、超时、重试次数。
- `m_pInt`：整数变量地址，如“个数”“大小”输出。
- `m_ppAryData`：数组/非数组变量地址，如邮件大小、邮件序号输出。
- `m_dwSubCodeAdr`：易语言子程序地址，如接收回调。

这些字段被读取的源码位置见 `pop3_cmdDef.cpp:84-91,107-109,118-120,128,199,236-237,246-247,255,267-271`。实现没有进一步校验 `nArgCount`、`m_dtDataType`、空指针或数组格式。

### 6.3 内部状态、持久化和资源

- 未发现 POP3 服务器连接对象、socket 句柄、TLS/SSL 对象、会话状态、认证状态、邮件列表缓存、错误字符串、回调地址存储或代理配置存储。
- 未发现文件、数据库、注册表或其他持久化读写。
- 未发现 MIME/RFC 822 解析器、Base64/Quoted-Printable 解码器、邮件头解析器、附件临时文件处理。
- `MailInfo` 与 `AttachmentInfo` 目前只有 `LIB_DATA_TYPE_INFO`/`LIB_DATA_TYPE_ELEMENT` 描述，并没有对应对象存储实现。`pop3_cmdDef.cpp` 的构造、复制、析构入口均为空，不能证明这些类型可安全创建、复制或释放。
- `pop3_const.cpp` 的常量数量为 0；`CmdType` 是枚举元数据，不是独立持久化数据。

## 7. 外部接口、ABI 与调用边界

### 7.1 动态库入口

- `Source_pop3.def:1-4`：模块库名无显式名称，`EXPORTS` 仅导出 `GetNewInf`。
- `pop3_dllMain.cpp:89-92`：`GetNewInf()` 返回 `&g_LibInfo_pop3_global_var`。
- `pop3_dllMain.cpp:31-87`：`g_LibInfo_pop3_global_var` 描述格式号、GUID、版本、系统要求、库名、命令分类、命令表、函数表、通知函数、常量表和依赖文件。
- 库身份：GUID `6639134E82344637A71AB1D6B70C2051`，版本 `2.0.1`，要求易语言系统 `3.7`、系统核心支持库 `3.7`，语言 `__GBK_LANG_VER`，名称“邮件接收支持库”。这些是源码元数据，不代表运行验证通过。

### 7.2 命令 ABI

易语言运行时要求命令函数形如：

```text
void PFN_EXECUTE_CMD(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)
```

该 ABI 定义在 `elib/lib2.h:1234-1239`。项目通过 `POP3_DEF_CMD` 和 `POP3_NAME` 生成 `pop3_<英文名>_<索引>_pop3`，并在 `g_cmdInfo_pop3_global_var_fun` 中按同一清单排列函数指针（`pop3_dllMain.cpp:26-29`）。

### 7.3 系统通知接口

`pop3_ProcessNotifyLib_pop3` 位于 `pop3_dllMain.cpp:101-178`，当前处理如下：

| 通知 | 当前行为 | 证据 |
|---|---|---|
| `NL_GET_CMD_FUNC_NAMES` | 返回静态编译用命令名数组 | `pop3_dllMain.cpp:106-111` |
| `NL_GET_NOTIFY_LIB_FUNC_NAME` | 返回 `pop3_ProcessNotifyLib_pop3` 文本 | `pop3_dllMain.cpp:112-116` |
| `NL_GET_DEPENDENT_LIBS` | 返回空的双零结尾文本 | `pop3_dllMain.cpp:117-123` |
| `NL_SYS_NOTIFY_FUNCTION` | 调用 `ProcessNotifyLib` 保存系统回调 | `pop3_dllMain.cpp:125-132` |
| `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NR_DELAY_FREE`、`NL_IDE_READY`、`NL_RIGHT_POPUP_MENU_SHOW`、`NL_ADD_NEW_ELEMENT` | 空处理并返回默认成功 | `pop3_dllMain.cpp:134-172` |
| 未知通知 | 返回 `NR_ERR` | `pop3_dllMain.cpp:173-177` |

`elib/fnshare.cpp:24-71` 保存 `PFN_NOTIFY_SYS`，并把用户注册的通知函数链到 `s_pfnuserNotifySys`。当前 POP3 业务命令没有调用 `NotifySys`、`ealloc`、`efree`、`CloneTextData` 或其他辅助函数。

### 7.4 静态编译边界

动态专用的 `DllMain`、`LIB_INFO`、元数据全局表和命令名数组均受 `#ifndef __E_STATIC_LIB` 保护；静态模式保留命令函数入口和 `pop3_ProcessNotifyLib_pop3`，由宿主处理静态命令名/通知协议。相关条件编译见：

- `include_pop3_header.h:11-20`
- `pop3_const.cpp:14-18`
- `pop3_cmdInfo.cpp:4-5`
- `pop3_dtType.cpp:3-4`
- `pop3_dllMain.cpp:6-6,26-100,106-124`

## 8. 依赖与构建配置

### 8.1 源码依赖

- Windows/Visual C++ 兼容头：`elib/lib2.h` 直接包含 `<windows.h>`、`<stdio.h>`、`<math.h>`（`elib/lib2.h:61-63`）。
- 易语言 ABI：`elib/lib2.h` 提供 `LIB_INFO`、`CMD_INFO`、`ARG_INFO`、`MDATA_INF`、数据类型标识和通知编号。
- 易语言语言/核心支持库约定：`elib/lang.h` 定义 GBK 语言版本；`elib/krnllib.h` 提供核心库 GUID、文件名和版本常量。
- C/C++ 运行时：源码使用 `memset`、`memcpy`、字符串/长度函数等；没有第三方库声明。
- 网络依赖：工程文件没有显式链接 Winsock、Schannel、OpenSSL、MFC 或其他 POP3/MIME 第三方库；源码也没有出现 socket/HTTP/SOCKS/MIME 实现。

### 8.2 动态工程 `pop3.vcxproj`

- 配置：`Debug/Release × Win32/x64`，`ConfigurationType=DynamicLibrary`（`pop3.vcxproj:51-75`）。
- 工具集：`v141`；Windows SDK `10.0.15063.0`；字符集 `Unicode`（`pop3.vcxproj:43-49,51-75`）。
- Win32 预处理宏：`__E_FNENAME=pop3`、`POP3_EXPORTS`、`_WINDOWS`、`_USRDLL`，Debug/Release 分别带 `_DEBUG`/`NDEBUG`（`pop3.vcxproj:109-145`）。
- Win32 链接：引用 `Source_pop3.def`；输出扩展名显式为 `.fne`（`pop3.vcxproj:95-102,121-126,146-153`）。
- x64 配置未显式设置 `__E_FNENAME=pop3`，也未在 Link 节点显式引用 `Source_pop3.def`；是否能通过预处理、是否能导出 `GetNewInf` 未验证。
- Release 使用 `/MT`，Debug 使用 `/MTd`（`pop3.vcxproj:119,144`）。

### 8.3 静态工程 `pop3_static/pop3_static.vcxproj`

- 配置：`Debug/Release × Win32/x64`，`ConfigurationType=StaticLibrary`（`pop3_static/pop3_static.vcxproj:48-72`）。
- Win32 预处理宏包含 `__E_STATIC_LIB`、`__E_FNENAME=pop3` 和 `_LIB`（`pop3_static/pop3_static.vcxproj:92-121`）。
- x64 预处理宏只有 `_DEBUG;_LIB` 或 `NDEBUG;_LIB`，未显式包含 `__E_STATIC_LIB`、`__E_FNENAME=pop3`（`pop3_static/pop3_static.vcxproj:130-155`）。由于 `elib/lib2.h:23-25` 要求先定义 `__E_FNENAME`，这是一个需要在 Windows/Visual Studio 环境复核的高风险配置缺口。
- x64 配置设置 `PrecompiledHeader=Use`/`PrecompiledHeaderFile=pch.h`，但工程收录列表中没有 `pch.h` 或 `pch.cpp`；Win32 配置则为 `NotUsing`（`pop3_static/pop3_static.vcxproj:92-101,130-138`）。实际构建结果未验证。

## 9. 真实数据流与缺失调用链

### 9.1 当前可证实的数据流

```text
命令元数据 POP3_DEF
  → CMD_INFO + ARG_INFO
  → LIB_INFO
  → 易语言加载/显示支持库
  → 命令索引选择 PFN_EXECUTE_CMD
  → 入口函数读取少量 MDATA_INF 字段
  → 函数结束
```

### 9.2 设计意图中应存在、但当前源码未发现的调用链

```text
连接收信服务器
  → 建立 TCP/TLS/代理连接
  → 读取 POP3 greeting
  → USER/PASS 或其他认证
  → 保存会话/连接状态

获取邮件信息
  → STAT
  → 解析邮件总数与总字节数
  → 写入 pArgInf[0].m_pInt / pArgInf[1].m_pInt
  → pRetData 写入 BOOL

获取邮件大小/序号/前几行
  → LIST/UIDL/TOP
  → 解析多行响应和结束标记
  → 写入易语言整数或数组格式

接收邮件
  → RETR
  → RFC 822/MIME 解析
  → 构造 MailInfo/AttachmentInfo
  → 管理文本、HTML、附件字节集和释放责任

删除/复位
  → DELE/RSET
  → 处理 POP3 事务状态与 QUIT

回调/代理/错误
  → 保存配置
  → 接收过程中按 CmdType 调用易语言子程序
  → 保存最后错误信息
```

上图后半段是协议实现所需的架构缺口，不是源码已经实现的流程。当前 `pop3_cmdDef.cpp` 没有任何网络 API 调用，也没有对 `pRetData` 或输出变量进行写入。

## 10. 测试、验证与 Git 基线

### 10.1 测试现状

- Git 跟踪文件中没有测试目录、测试源文件、测试脚本、CI 配置或测试数据。
- 未发现 `README` 或构建说明；工程文件是当前唯一构建入口证据。
- 当前核对未执行 Visual Studio/MSBuild 编译：当前执行环境为 macOS，仓库依赖 Windows SDK、`windows.h` 和 Visual C++ 工具集；强行替换工具链不能证明 Windows 目标构建成立。
- 未连接 POP3 服务器，未验证端口、认证、代理、邮件拉取、MIME、回调、删除/复位或错误处理。
- 源码静态计数结果：`pop3_cmdDef.cpp` 有 33 个 `POP3_EXTERN_C void` 函数，返回语句为 0；这支持“入口存在、业务返回未实现”的结论，但不是运行测试。

### 10.2 Git 基线

- 本地分支：`master`
- HEAD：`57afb8de256c66cc8e2cebd3abbf18af4f15ca48`
- HEAD 提交时间：`2022-12-19T16:56:47+08:00`
- HEAD 提交说明：`初始化仓库`
- 远程：`origin https://gitee.com/JYtechnology/pop3.git`
- `origin/HEAD` 与本地 `HEAD` 均为 `57afb8de256c66cc8e2cebd3abbf18af4f15ca48`；当前核对通过 `git ls-remote` 核对，远程 `master` 同一提交。
- 写入本文件前工作树干净；当前核对不提交 Git。写入后预期唯一工作树变化为根目录 `ARCHITECTURE.md`。

## 11. 风险、未确认项与后续复核点

### 11.1 高风险

1. **业务命令全部空实现**：连接、收信、邮件信息、邮件大小、错误信息、删除、代理和回调均不能据源码证明可用；优先级为 P0。
2. **返回值/输出参数未填充**：多个 `SDT_BOOL` 命令未写 `pRetData`，输出变量命令未写 `m_pInt`/`m_ppAryData`；即使入口被调用，也无法提供声明的结果。
3. **对象生命周期未实现**：`MailInfo`/`AttachmentInfo` 构造、复制、析构函数为空；文本、字节集、复合数据的内存责任未定义。
4. **静态库 x64 工程宏不完整**：缺少 `__E_FNENAME` 会触发 `lib2.h` 的预处理错误；同时未显式选择静态模式。需在 Windows 工具链中复核。
5. **动态库 x64 导出/宏不完整**：x64 配置未显式设置命名宏和 `.def` 链接，`GetNewInf` 是否成功导出未验证。

### 11.2 重要风险

1. **没有输入合法性和 ABI 校验**：入口未检查 `nArgCount`、类型标识、空指针、数组维度和变量可写性。
2. **没有网络安全边界**：未见 TLS、证书校验、密码保护、超时实现或认证失败清理；声明了代理类型但未实现。
3. **没有协议状态机**：未见 greeting、认证、事务态、`QUIT`、多行响应结束、服务器错误码解析和断线恢复。
4. **没有解析/编码策略**：未见 GBK/其他编码转换、邮件头解码、MIME boundary、附件传输编码解析。
5. **没有测试与发布证据**：不存在测试项目或 CI，版本号/库说明只是静态元数据。
6. **通知处理默认空成功**：多个生命周期/IDE 通知分支不做资源动作；当后续加入全局连接状态后，释放时机必须补齐。

### 11.3 待核查问题

- Win32 Debug/Release 是否能使用目标版本 `v141` 与 SDK `10.0.15063.0` 成功编译。
- x64 动态工程是否由外部属性表补充 `__E_FNENAME` 和 `.def`；当前仓库没有对应 `.props`/`.targets` 证据。
- 易语言支持库宿主对 `MailInfo`/`AttachmentInfo` 复合数据的预期布局，以及 `MAKELONG(0x01/0x02, 0)` 的真实类型编码。
- `GetNewInf` 的 `.fne` 装载规则、静态库命令名返回协议和宿主内存释放协议。
- 远程仓库后续提交是否引入实现；当前远程 `master` 与本地基线同一提交，不能代表未来版本。

## 12. 证据索引

### 12.1 项目与构建

- `pop3.sln:5-40`：解决方案、动态/静态两个项目、Win32/x64 Debug/Release 映射。
- `pop3.vcxproj:21-48`：动态工程源文件、头文件、`.def` 和基础属性。
- `pop3.vcxproj:51-201`：动态库类型、工具集、宏、运行库、Win32 `.fne` 和 `.def` 配置。
- `pop3_static/pop3_static.vcxproj:21-45`：静态工程收录同一组源文件。
- `pop3_static/pop3_static.vcxproj:48-166`：静态库类型、Win32/x64 预处理宏和预编译头差异。
- `pop3.vcxproj.filters:3-74`、`pop3_static/pop3_static.vcxproj.filters:3-66`：Visual Studio 文件筛选映射。
- `Source_pop3.def:1-4`：仅导出 `GetNewInf`。

### 12.2 接口元数据与实现入口

- `pop3_cmd_typedef.h:3-9`：命名宏。
- `pop3_cmd_typedef.h:12-45`：33 个命令清单及返回类型/参数索引。
- `include_pop3_header.h:3-24`：公共头和命令声明展开。
- `pop3_cmdInfo.cpp:28-60`：23 个参数描述项。
- `pop3_cmdInfo.cpp:67-79`：`CMD_INFO` 表生成。
- `pop3_cmdDef.cpp:6-273`：33 个命令函数入口；当前函数体为空或仅读参数。
- `pop3_dtType.cpp:3-97`：三种数据类型、成员索引和枚举成员。
- `pop3_const.cpp:12-18`：常量表为空。

### 12.3 支持库 ABI 与通知

- `pop3_dllMain.cpp:5-29`：DLL 入口声明和命令函数表。
- `pop3_dllMain.cpp:31-92`：`LIB_INFO` 与 `GetNewInf`。
- `pop3_dllMain.cpp:94-178`：静态命令名和通知分发。
- `elib/lib2.h:12-43`：命名宏和命令声明宏。
- `elib/lib2.h:232-292`：`DATA_TYPE`、`ARG_INFO`、参数标志。
- `elib/lib2.h:296-364`：`CMD_INFO`、命令状态和返回类型。
- `elib/lib2.h:369-390`：`LIB_DATA_TYPE_ELEMENT`。
- `elib/lib2.h:693-729`：`LIB_DATA_TYPE_INFO`。
- `elib/lib2.h:753-824`：`MDATA_INF` 运行时参数布局。
- `elib/lib2.h:1225-1318`：通知函数类型、命令函数 ABI、`LIB_INFO`。
- `elib/fnshare.cpp:7-71`：通知回调、调试版本和用户通知链。
- `elib/fnshare.h:20-84`：内存/通知辅助函数声明和实现约定。
- `elib/lang.h:6-14`：GBK 语言版本。
- `elib/mtypes.h:10-49,61-176`：基础类型兼容定义。

## 13. 首轮归档声明

本文件是 `pop3` 项目的唯一首轮架构事实源。后续深挖应直接更新本文件，并继续区分“源码已实现”“仅声明/入口存在”“未验证”；不得把接口注释、工程配置或旧文档当作运行实现证据。若后续发现历史细探文件，应先逐条与源码核对并吸收到本文件，再决定是否归档或删除。
