# AQStringFormatFne 架构归档

## 1. 项目定位

`AQStringFormatFne` 是 aiqinxuancai 发布的易语言支持库源码，目标是编译一个 Windows Win32 x86 动态库（`.fne`），向易语言运行环境提供 `StringFormat` 全局命令。命令以第一个文本参数为格式串，接收可追加的通用参数，内部按参数类型把值压入 C 变参调用栈，再通过 `_vsnprintf` 生成格式化文本并返回。

仓库还保留一个静态库工程 `AQStringFormatFneStatic`，通过 `__E_STATIC_LIB` 编译宏复用同一组实现源码；主动态库工程使用 `GetNewInf` 作为易语言加载入口。

## 2. 真实执行流程

```text
易语言 IDE/运行环境
        │
        ├─ 加载 AQStringFormatFne.fne
        │       └─ 解析导出 GetNewInf
        │               └─ 返回 s_LibInfo
        │                       ├─ 命令元数据 s_CmdInfo
        │                       ├─ 命令实现表 s_RunFunc
        │                       └─ 系统通知回调 AQ_StringFormat_ProcessNotifyLib
        │
        ├─ 发送 NL_SYS_NOTIFY_FUNCTION
        │       └─ 保存 PFN_NOTIFY_SYS 到 AQ_StringFormat_g_fnNotifySys
        │
        └─ 调用命令 fn_wsprintf（命令名 StringFormat）
                ├─ 读取 pArgInf[0].m_pText 作为格式串
                ├─ 从末尾到开头检查其余参数的 m_dtDataType
                ├─ 将文本、日期、数值、逻辑等参数按 C 变参布局压栈
                ├─ 调用 sprintf_wsprintf → _vsnprintf(..., 4096, ...)
                ├─ AQ_StringFormat_CloneTextData 申请并复制 4096 字节结果
                └─ 写入 pRetData->m_pText
```

## 3. 目录与文件地图

```text
AQStringFormatFne/
├── AQStringFormatFne.dsw                    Visual Studio 6 工作区
├── AQStringFormatFne.positions               工作区二进制位置状态
├── AQStringFormatFne/                        动态库工程源码
│   ├── AQStringFormatFne.cpp                 DLL 入口、通知、格式化实现
│   ├── AQStringFormatFne.h                   支持库元数据、命令表、实现声明
│   ├── AQStringFormatFne.def                 仅导出 GetNewInf
│   ├── AQStringFormatFne.dsp                 Win32 x86 Debug/Release 工程
│   ├── StdAfx.cpp / StdAfx.h                 预编译头与易语言 SDK 头文件
│   ├── elib/lib2.h                           易语言支持库 ABI、数据类型、通知协议
│   ├── elib/lang.h                           GBK 语言版本定义
│   ├── elib/fnshare.h                        `_WT` 文本宏与 SDK 版权边界
│   ├── ReadMe.txt                            Visual Studio AppWizard 说明
│   └── LICENSE                               MIT License
├── AQStringFormatFneStatic/
│   └── AQStringFormatFneStatic.dsp            Win32 x86 静态库工程
├── .gitattributes                            文本自动 LF 规范化
└── .gitignore                                Visual Studio 生成物忽略规则
```

仓库没有独立的 `测试/`、`tests/`、构建脚本、包管理文件、运行时配置、数据库或网络服务目录。

## 4. 核心数据模型与持久化

项目不定义业务数据库、文件索引或持久化状态；状态全部位于 DLL 进程内，并通过易语言运行环境提供的回调完成内存管理与错误通知。

### 4.1 易语言 SDK ABI 数据模型

实现依赖 `elib/lib2.h` 中的 ABI：

- `ARG_INFO`：命令参数编辑信息，包括名称、解释、`DATA_TYPE`、默认值和 `m_dwState` 参数标志。
- `CMD_INFO`：命令编辑/运行元数据，包括中文名、英文名、解释、类别、返回类型、参数数量和参数表。
- `MDATA_INF`：运行时参数/返回值容器；联合体覆盖 `m_pText`、`m_date`、`m_byte`、`m_short`、`m_int`、`m_int64`、`m_float`、`m_double`、`m_bool`、数组和变量地址等字段，并用 `m_dtDataType` 描述实际类型。
- `LIB_INFO`：支持库身份、版本、所需易语言系统版本、语言、命令类别、命令表、实现函数表和通知回调。
- `PFN_EXECUTE_CMD`：命令实现函数原型 `void (PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)`。

`MDATA_INF` 在 `lib2.h` 中以一字节对齐，`AQStringFormatFne.cpp` 直接依赖其指针字段和联合成员，ABI 对齐、Win32 指针宽度及 `CDECL` 调用约定均属于不可变兼容边界。

### 4.2 项目元数据

`AQStringFormatFne.h` 的 `s_LibInfo` 固定声明：

- 库格式号：`LIB_FORMAT_VER`，当前值为 `20000101`。
- GUID：`EA968347-300C-4515-93CA-F1D3BA3DF66F`。
- 库版本：主版本 `1`、次版本 `2`、构建号 `1`。
- 所需易语言系统版本：`3.0`；所需核心支持库版本：`3.0`。
- 语言：`__GBK_LANG_VER`。
- 类别数：`13`；类别字符串为 `0000...` 的 GBK 编码文本表。
- 自定义数据类型、常量、依赖文件和 AddIn 均未提供。

## 5. 核心调用链与模块职责

### 5.1 支持库加载与命令分发

1. PE 导出文件 `AQStringFormatFne.def` 只导出 `GetNewInf`。
2. `GetNewInf()` 返回 `&s_LibInfo`。
3. `s_LibInfo.m_pBeginCmdInfo` 指向 `s_CmdInfo`，其中只有一个命令条目。
4. `s_LibInfo.m_pCmdsFunc` 指向 `s_RunFunc`，其第一个函数为 `fn_wsprintf`。
5. 易语言运行环境按命令索引调用 `fn_wsprintf`。

`g_CmdNames` 同时提供英文实现名 `fn_wsprintf`，用于 `NL_GET_CMD_FUNC_NAMES` 通知查询；用户可见英文命令名由 `CMD_INFO` 中的 `StringFormat` 给出。

### 5.2 `StringFormat` 命令

`AQStringFormatFne.h` 的命令元数据定义：

- 用户可见命令名：`StringFormat`。
- 英文名：`StringFormat`。
- 返回类型：`SDT_TEXT`。
- 参数数：至少两个。
- 第一个参数：文本型格式串。
- 第二个参数：`_SDT_ALL`，空值默认标志为 `AS_DEFAULT_VALUE_IS_EMPTY`。
- 状态：`CT_ALLOW_APPEND_NEW_ARG`，因此运行时可接收多个追加参数。

`fn_wsprintf` 的实际实现步骤：

1. 分配固定 4096 字节的 `pszoutbuf`。
2. 从 `pArgInf[0].m_pText` 取得格式串。
3. 令 `j` 从 `1` 递增到 `nArgCount - 1`，使用 `i = nArgCount - j`，即从最后一个实参倒序处理。
4. 对每个参数按 `m_dtDataType` 分支：
   - `SDT_TEXT`、`SDT_DATE_TIME`、`SDT_BYTE`、`SDT_SHORT`、`SDT_INT`、`SDT_BOOL`：把对应指针压入栈；
   - `SDT_INT64`：拆为高低 32 位后压入两个栈参数，并增加 `iArgCount`；
   - `SDT_FLOAT`、`SDT_DOUBLE`：以 x86 栈上的 8 字节浮点布局压入，并增加 `iArgCount`；
   - 其他类型：调用 `AQ_StringFormat_GReportError("不支持的参数数据类型")` 后返回。
5. 以内联汇编把格式串、输出缓冲区和参数数量安排好，调用 `sprintf_wsprintf`。
6. `sprintf_wsprintf` 使用 `_vsnprintf(szbuf, 4096, fmt, argptr)`。
7. 使用 `AQ_StringFormat_CloneTextData(pszoutbuf, 4096)` 申请运行环境内存并复制结果，写入 `pRetData->m_pText`。
8. 释放 C++ 数组 `pszoutbuf`。

### 5.3 通知、内存与错误边界

- `AQ_StringFormat_ProcessNotifyLib` 处理 `NL_GET_CMD_FUNC_NAMES`、`NL_GET_NOTIFY_LIB_FUNC_NAME`、`NL_GET_DEPENDENT_LIBS` 等库查询通知；其他通知交给 `_AQ_StringFormat_ProcessNotifyLib`。
- 收到 `NL_SYS_NOTIFY_FUNCTION` 后，把 `dwParam1` 转换为 `PFN_NOTIFY_SYS`，保存到全局 `AQ_StringFormat_g_fnNotifySys`。
- `AQ_StringFormat_CloneTextData` 通过 `NRS_MALLOC` 向易语言运行环境申请文本内存。
- `AQ_StringFormat_GReportError` 通过 `NRS_RUNTIME_ERR` 报告运行时错误。
- `AQ_StringFormat_NotifySys` 是对已保存系统通知回调的包装；如果回调为空则返回 `0`。
- `AQ_StringFormat_GetAryElementInf` 可解析易语言数组数据头，当前格式化命令链没有调用它。
- `OutputStringToELog`、`AQ_StringFormat_EnumChildCallback` 提供向易语言日志窗口发送字符串的辅助实现，但当前 `fn_wsprintf` 中调用日志的语句被注释，没有进入正常调用链。

## 6. API、CLI、插件与协议边界

### 对外二进制边界

- PE 导出：`GetNewInf`，由易语言加载器按固定名称查找。
- 支持库通知入口：`AQ_StringFormat_ProcessNotifyLib`，通过 `LIB_INFO.m_pfnNotify` 注册。
- 命令执行 ABI：`PFN_EXECUTE_CMD`；本项目对应实现为 `fn_wsprintf`。
- 命令查询协议：`NL_GET_CMD_FUNC_NAMES` 返回 `g_CmdNames`，`NL_GET_NOTIFY_LIB_FUNC_NAME` 返回 `AQ_StringFormat_ProcessNotifyLib`，`NL_GET_DEPENDENT_LIBS` 返回 `NULL`。
- 系统回调协议：`PFN_NOTIFY_SYS`；使用 `NRS_MALLOC` 和 `NRS_RUNTIME_ERR`。

### 用户调用边界

本项目没有 HTTP API、CLI、SDK、配置文件、插件发现器或独立进程协议。用户侧唯一功能入口是易语言命令 `StringFormat`；静态库工程只改变链接方式，不新增命令或协议。

## 7. 技术栈与依赖边界

| 层次 | 实际技术/依赖 |
|---|---|
| 语言 | C/C++，旧式 Win32 API 与 Microsoft Visual C++ 语法 |
| 目标平台 | `Win32 (x86)`；使用 `__asm`、`_vsnprintf`、`WINAPI`、`__declspec(dllexport)` |
| 工程系统 | Visual Studio Developer Studio 6.00 `.dsp/.dsw` |
| 易语言接口 | 仓库内 `elib/lib2.h`、`elib/lang.h`、`elib/fnshare.h` |
| 系统库 | Windows、User32 等链接库；动态工程配置列出 `kernel32.lib`、`user32.lib`、`advapi32.lib` 等 |
| 第三方包 | 无包管理声明、无外部运行时包依赖 |
| 内存模型 | 输出临时缓冲区用 `new[]`，返回文本通过易语言 `NRS_MALLOC` 分配 |
| 编码 | `__GBK_LANG_VER`；源码中部分 SDK 文件为 GBK/本地编码文本 |

动态库工程设置了 `/MT` 或 `/MTd`，关闭 MFC，目标架构为 `I386`；静态库工程定义 `__E_STATIC_LIB`，因此 `AQStringFormatFne.h` 中的动态 DLL 元数据注册段会被条件编译排除。

## 8. 构建、测试与验证现状

### 已确认

- Debug 与 Release 两个动态库配置均输出 `AQStringFormatFne.fne` 到对应目录。
- 静态库配置输出 `AQStringFormatFne_static.lib`。
- 代码入口、命令元数据和导出定义在源码层一致：`GetNewInf` → `s_LibInfo` → `s_CmdInfo/s_RunFunc` → `fn_wsprintf`。
- 仓库没有单元测试、集成测试、测试夹具、CI 配置或可在当前 macOS 环境直接执行的验证脚本。

### 未执行与原因

- 未执行原生构建：工程要求旧版 Microsoft Visual C++ `cl.exe/link.exe`、Win32 x86 内联汇编和 Windows SDK；当前环境为 macOS，不能据此声称构建通过。
- 未执行易语言运行时调用：仓库未提供 `.fne` 产物、易语言运行环境或可复现的宿主测试。
- 未执行运行时 ABI 测试：需要真实 `PFN_NOTIFY_SYS`、`PMDATA_INF` 和易语言内存回调，静态源码检查不能替代运行验证。
- 未修改源码、工程文件、依赖、测试或配置，也未安装依赖、启动服务或提交 Git。

## 9. 风险与未确认项

1. `fn_wsprintf` 依赖 32 位 x86 内联汇编和特定 C 变参栈布局，不能直接迁移到 x64 或非 MSVC 编译器。
2. `pszoutbuf` 固定为 4096 字节，`_vsnprintf` 达到上限时的截断/终止行为未在宿主环境验证；代码随后固定复制 4096 字节，而不是按实际返回长度复制。
3. `AQ_StringFormat_CloneTextData` 直接调用 `AQ_StringFormat_g_fnNotifySys`；若宿主在完成 `NL_SYS_NOTIFY_FUNCTION` 之前调用命令，可能解引用空回调。
4. `fn_wsprintf` 中 `pptr`、`iResult`、`pp` 等局部变量和 `sprintf_wsprintf` 的返回值没有形成明确的错误处理链；格式化失败、截断和异常格式串的行为未定义为项目契约。
5. `SDT_DOUBLE` 分支先把值转换为 `float`（`pp=(float)pArgInf[i].m_double`），存在精度损失；这是当前源码事实，不应推断为完整双精度支持。
6. `SDT_INT64`、`SDT_FLOAT`、`SDT_DOUBLE` 依靠 `iArgCount` 修正栈参数数量，是否与目标 MSVC 运行库的 `va_list` 布局完全匹配，需要 Win32 实机测试。
7. `fn_hexToString` 和 `fn_stringToHex` 仅有空壳实现，且未被 `s_RunFunc` 注册；它们不是当前公开命令，但属于源码中的未完成辅助方向。
8. `OutputStringToELog` 使用硬编码窗口类名 `ENewFrame`、控件 ID `1011` 和消息号 `194`，当前调用被注释，兼容性没有测试证据。
9. `AQStringFormatFne.h` 中可见中文字符串在当前读取环境出现编码显示异常；`s_LibInfo` 明确声明 GBK，发布构建必须保持与易语言宿主约定的编码。
10. `elib/fnshare.h` 含有易语言作者的第三方开发授权限制说明；后续再分发或移植前应重新核对该文件的许可边界。

## 10. 版本与证据基线

- 项目根：`~/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/GitHub_aiqinxuancai/AQStringFormatFne`
- 远程仓库：`https://github.com/aiqinxuancai/AQStringFormatFne.git`
- 当前分支：`main`，工作树在归档前无源码修改。
- 本地提交：`36b434112d842602e25c75a51cfd7c02a60793b8`，提交信息 `解决符号冲突问题`，时间 `2021-01-22T16:03:00+08:00`。
- 远程 `HEAD`/`refs/heads/main` 经本机代理 `127.0.0.1:4780` 查询均为同一提交 `36b434112d842602e25c75a51cfd7c02a60793b8`；本地未落后远程，因此未创建独立远程快照，也未执行 fetch/pull。
- 关键证据路径：`AQStringFormatFne/AQStringFormatFne.h`、`AQStringFormatFne/AQStringFormatFne.cpp`、`AQStringFormatFne/AQStringFormatFne.def`、`AQStringFormatFne/AQStringFormatFne.dsp`、`AQStringFormatFneStatic/AQStringFormatFneStatic.dsp`、`AQStringFormatFne/elib/lib2.h`、`AQStringFormatFne/elib/lang.h`、`AQStringFormatFne/elib/fnshare.h`、`AQStringFormatFne/ReadMe.txt`、`AQStringFormatFne/LICENSE`。

本文件是该项目唯一的架构归档文档；后续复核应直接更新本文件，不另建平行架构报告。

## 11. 第三轮：字符串格式化、DLL/FNE、ABI 与平台底座边界

本轮只做源码证据到平台边界的映射，不把目标平台的“文本/ABI 支持库、运行核心、网关”倒推成项目已有实现。项目源码中没有这些平台目录；下表中的“平台落点”是装配裁决，不是本仓库现状。

### 11.1 真实实现、部分实现与骨架分界

| 能力/部件 | 源码事实 | 结论 |
|---|---|---|
| DLL/FNE 入口 | `AQStringFormatFne/AQStringFormatFne.def:1-4` 只导出 `GetNewInf`；`AQStringFormatFne.cpp:8-31` 在非 `__E_STATIC_LIB` 下提供 `DllMain` 与 `GetNewInf`，后者返回静态 `s_LibInfo` | **真实实现（L2）**：有导出和返回值静态证据；没有 Windows/易语言宿主实测，不能升到 L3/L4 |
| DLL 元数据与命令注册 | `AQStringFormatFne.h:29-129` 在非静态编译下定义 `s_RunFunc`、`g_CmdNames`、`s_ArgInfo`、`s_CmdInfo`、`s_LibInfo`；只有 `fn_wsprintf` 一个实现入口、一个 `StringFormat` 命令 | **真实实现（L2）**：注册表是静态数组，不是动态注册中心 |
| 静态库路径 | `AQStringFormatFneStatic/AQStringFormatFneStatic.dsp:43-45,66-67` 定义 `__E_STATIC_LIB`，复用 `AQStringFormatFne.cpp/.h`；头文件的命令表、库信息和通知查询分支均被 `#ifndef __E_STATIC_LIB` 排除 | **部分实现（L1/L2）**：能编译静态对象/库的工程路径有证据，但静态宿主如何获取命令名、通知函数名和依赖列表没有实现/实测证据；`AQStringFormat_ProcessNotifyLib` 对这些查询在静态路径会落到默认 `NR_ERR` |
| 字符串格式化 | `AQStringFormatFne.cpp:147-153,172-288` 实现 `sprintf_wsprintf`、x86 栈压参和 `fn_wsprintf`；支持文本、日期、byte、short、int、int64、float、double、bool 分支 | **真实实现但强 ABI 约束（L2）**：不是骨架；格式串、变参栈布局、输出截断和错误路径未在宿主执行 |
| 字节集/十六进制方向 | `AQStringFormatFne.cpp:157-169` 的 `fn_hexToString` 只计算数组指针/长度后结束，`fn_stringToHex` 函数体为空；二者也不在 `s_RunFunc` | **骨架/不可用（L0）**：不是公开命令，不能写成已提供能力 |
| 宿主通知回调 | `AQStringFormatFne.cpp:41-54` 接收 `NL_SYS_NOTIFY_FUNCTION` 并保存 `PFN_NOTIFY_SYS`；`AQ_StringFormat_NotifySys` 有空指针保护，但 `CloneTextData` 与 `GReportError` 在 `:72-98` 直接调用全局回调 | **部分实现（L2，失败安全不足）**：回调接线真实，生命周期、空回调和并发语义不完整 |
| IDE 日志 HWND | `AQStringFormatFne.cpp:118-139` 定义全局 `HWND`、枚举控件和 `SendMessageA` 辅助函数，但 `fn_wsprintf` 中调用 `OutputStringToELog` 的语句在 `:178` 被注释 | **孤立辅助/非主链（L1）**：不能归入已实现的宿主交互；没有创建、持有者、销毁或失效句柄治理 |
| 释放与卸载 | `fn_wsprintf` 正常尾部 `:286-288` 删除 `new char[4096]`；SDK 另定义 `NRS_MFREE` 与 `NL_FREE_LIB_DATA`（`elib/lib2.h:1135-1137,1178-1179`），但项目没有调用/处理它们；`DllMain:8-23` 对 attach/detach 仅返回 TRUE | **部分实现（L1/L2）**：只覆盖局部临时缓冲区成功路径，不是完整资源生命周期 |

### 11.2 DLL/FNE、命令注册和 ABI 的真实链路

动态 DLL 的实际链路是固定数组和固定导出，不经过本项目之外的注册服务：

```text
易语言加载器
  → PE 导出 GetNewInf（AQStringFormatFne.def）
  → &s_LibInfo（AQStringFormatFne.h）
  → m_pBeginCmdInfo = s_CmdInfo（1 条 StringFormat）
  → m_pCmdsFunc = s_RunFunc（1 个 fn_wsprintf）
  → PFN_EXECUTE_CMD(pRetData, nArgCount, pArgInf)
  → fn_wsprintf
  → AQ_StringFormat_CloneTextData
  → pRetData->m_pText
```

注册细节必须按源码原样保留：

- `s_ArgInfo` 有两个声明参数（`SDT_TEXT` 格式串、`_SDT_ALL` 追加参数），第二个带 `AS_DEFAULT_VALUE_IS_EMPTY`；`s_CmdInfo` 的 `m_nArgCount` 为 `2`，并设置 `CT_ALLOW_APPEND_NEW_ARG`（`AQStringFormatFne.h:45-83`）。因此“至少两个参数、末尾可继续追加”是编辑/调用契约；代码没有自行校验 `nArgCount >= 2`。
- `g_CmdNames` 返回的是实现符号名 `_WT("fn_wsprintf")`，用户可见命令名来自 `CMD_INFO` 的 `StringFormat`，二者不是同一个注册字段（`AQStringFormatFne.h:37-41,66-83`）。
- `AQ_StringFormat_ProcessNotifyLib` 在动态路径处理 `NL_GET_CMD_FUNC_NAMES`、`NL_GET_NOTIFY_LIB_FUNC_NAME`、`NL_GET_DEPENDENT_LIBS`（返回 `NULL`），随后才转交 `_AQ_StringFormat_ProcessNotifyLib`；静态路径预处理分支被排除（`AQStringFormatFne.cpp:56-66`）。
- `elib/lib2.h:815-883` 对 `MDATA_INF` 使用 `#pragma pack(1)`，其 union 同时承载值、文本/数组指针和变量地址指针，末尾 `m_dtDataType` 决定解释方式。`PFN_EXECUTE_CMD` 在 `elib/lib2.h:1218-1224` 明确要求 CDECL；这是 `fn_wsprintf` 能否被宿主调用的 ABI 硬边界。
- `PFN_NOTIFY_SYS` 在 `elib/lib2.h:1206-1215` 是 `WINAPI` 回调；`NL_SYS_NOTIFY_FUNCTION` 的 `dwParam1` 是该函数指针（`elib/lib2.h:1171-1177`）。项目把它从 `DWORD` 转换保存，依赖 Win32 x86 指针宽度；不能把此转换当成 x64 兼容实现。

### 11.3 `StringFormat` 的真实数据/变参路径与边界

`fn_wsprintf` 的源码行为不是抽象的“格式化文本”，而是以下具体步骤（`AQStringFormatFne.cpp:172-288`）：

1. 先 `new char[4096]`，不检查分配结果；直接读 `pArgInf[0].m_pText` 作为格式串，也不检查参数数量、参数类型或指针有效性。
2. 对 `j=1..nArgCount-1`，用 `i=nArgCount-j` 从追加参数尾部向前扫描 `m_dtDataType`。文本、日期、byte、short、int、bool 分支把对应地址放入 x86 栈；`INT64` 拆成两个 32 位值；float/double 在栈上扩成 8 字节槽位并增加 `iArgCount`。
3. `SDT_DOUBLE` 先执行 `pp=(float)pArgInf[i].m_double`（`AQStringFormatFne.cpp:252-260`），所以源码并非保持完整双精度；该事实不能包装成“支持无损 double”。
4. 不支持的类型调用 `AQ_StringFormat_GReportError("不支持的参数数据类型")` 后直接 `return`；这条返回路径没有释放此前的 `pszoutbuf`，且没有写入明确错误结果。
5. 内联汇编调用 `sprintf_wsprintf`，后者用 `_vsnprintf(szbuf, 4096, fmt, argptr)`（`AQStringFormatFne.cpp:147-153`）。返回值写入汇编临时寄存器后未用于输出长度或错误判断，`iResult` 也没有形成错误链。
6. 无论实际写入长度、截断状态或格式化失败结果如何，尾部都调用 `AQ_StringFormat_CloneTextData(pszoutbuf, 4096)`；该函数按固定 4096 字节复制，再写结尾 `\0`（`AQStringFormatFne.cpp:72-80,286-288`）。因此固定长度复制和 `_vsnprintf` 的截断/未终止行为属于真实风险，不是文档推测。
7. 成功路径把宿主分配的指针写入 `pRetData->m_pText`，没有显式设置 `m_dtDataType`；固定命令元数据已声明返回 `SDT_TEXT`。命令 ABI 的返回类型不是 JSON/异常对象，而是宿主 `MDATA_INF` 的文本指针。

### 11.4 文本/ABI 支持库、运行核心、网关的归属裁决

| 主题 | 当前项目的真实归属 | 平台应归属的唯一 owner | 不应做的事 |
|---|---|---|---|
| 格式串解析、参数类型到文本变参的转换、输出长度/编码规则 | `fn_wsprintf` 和 `sprintf_wsprintf`，但混在 FNE ABI 适配文件中 | **文本支持库**：提供有界、类型明确的 `文本.格式化` 原子能力；将易语言参数转换作为该能力的 ABI 适配层 | 不把 x86 `__asm`、裸 C 变参和 `_vsnprintf` 截断语义直接复制为平台通用实现 |
| `MDATA_INF`、`ARG_INFO`、`CMD_INFO`、`LIB_INFO`、`PFN_EXECUTE_CMD`、`PFN_NOTIFY_SYS`、`GetNewInf`、`.def` 导出 | `elib/lib2.h` + `AQStringFormatFne.h/.def/.cpp` | **ABI 支持库/适配层**：固定结构布局、调用约定、导出和宿主通知协议；必须单独做 Win32 x86 兼容校验 | 不让文本能力直接依赖 `DWORD` 指针转换、`#pragma pack(1)` 或宿主窗口句柄 |
| DLL 加载、回调登记、句柄持有、卸载、超时、崩溃隔离和残留审计 | 本项目只有空操作 `DllMain`、全局回调和孤立 HWND；没有生命周期管理器 | **运行核心**：动态库/宿主会话监督、句柄登记、所有权转移、释放、强杀/重启和崩溃证据 | 不把 DLL 的静态全局变量当成运行核心；不在文本支持库中自行实现第二套加载/释放器 |
| 外部请求认证、限流、请求/响应版本、错误归一化和调用审计 | 本项目没有 HTTP、CLI、网关、认证或请求协议 | **统一网关**：只接收结构化文本格式化请求，调用文本支持库公开能力，再返回统一结果 | 不让网关直调 `fn_wsprintf` 或接收 `PMDATA_INF`/裸指针；不在网关复制格式化逻辑 |
| 易语言 IDE/运行时的消息与内存交互 | `AQ_StringFormat_ProcessNotifyLib`、`NRS_MALLOC`/`NRS_RUNTIME_ERR` 直连 | ABI 支持库负责适配；运行核心负责回调生命周期和失败隔离；网关不参与宿主指针管理 | 不把 `PFN_NOTIFY_SYS` 误命名成网关回调，也不把 `NRS_MALLOC` 当平台堆接口 |

当前项目的真实链路仍是“易语言宿主 → FNE ABI → `fn_wsprintf`”，没有运行核心和网关节点。平台目标链路只能写成：

```text
统一网关（可选外部入口）
  → 运行核心（装载/监督/句柄/超时/崩溃）
  → ABI 支持库（宿主适配与类型边界）
  → 文本支持库（格式化原子能力）
  → 统一结果/证据/释放
```

### 11.5 句柄、宿主交互和释放生命周期

| 资源 | 创建/取得 | 当前持有者 | 正常释放证据 | 失败/超时/取消/崩溃处置 |
|---|---|---|---|---|
| `pszoutbuf` | `fn_wsprintf` 的 `new char[4096]`（`:174`） | 当前函数栈帧 | 正常尾部 `delete []pszoutbuf`（`:288`） | 不支持类型在 `:266-269` 直接返回而不删除；`CloneTextData`/宿主回调崩溃时也没有 `finally` 等价路径；进程崩溃由宿主回收，源码无独立证据 |
| 返回文本 `pRetData->m_pText` | `AQ_StringFormat_CloneTextData` 通过 `NRS_MALLOC`（`:72-80`；SDK 定义在 `elib/lib2.h:1129-1137`） | **易语言运行时/宿主**，不是 C++ `delete[]` | 项目只把指针交给 `pRetData`，没有调用 `NRS_MFREE`；SDK 语义要求宿主/运行时负责相应释放 | `NRS_MALLOC` 失败由 SDK 的 `dwParam2=0` 语义可能触发运行时错误/退出；若回调返回空指针，源码随后 `memcpy`，可能崩溃；没有超时/取消路径 |
| `PFN_NOTIFY_SYS` | `NL_SYS_NOTIFY_FUNCTION` 的 `dwParam1`（`:46-48`） | 全局 `AQ_StringFormat_g_fnNotifySys`（头文件 `:17-18` 初始化为 `NULL`） | 没有清空、引用计数、代际校验或卸载回调；后通知覆盖先通知 | 宿主重启/卸载后旧函数指针是否仍有效未处理；并发读写无锁；回调失效可能跳转崩溃 |
| `HWND _AQ_StringFormat_eLogHwnd` | `FindWindowExA` + `EnumChildWindows`（`:118-135`） | 全局裸 HWND | 没有 `DestroyWindow`（本项目不创建它）、失效检测或清零；且主链调用被注释 | 该辅助函数不属于公开命令；若未来启用，窗口重建/句柄复用/跨线程消息均未验证 |
| DLL 模块句柄 | `DllMain(HANDLE hModule,...)` 收到但未使用（`:8-23`） | 宿主加载器 | `DllMain` 的 detach 分支为空；没有 `FreeLibrary` 或资源清理 | 进程/宿主卸载时没有项目级清理钩子；崩溃恢复、残留检查、重复装载语义均未实现 |
| `s_LibInfo`、`s_CmdInfo`、`s_RunFunc`、`g_CmdNames` | 静态存储期对象（`.h:31-129`） | 模块映像/加载器只读引用 | 不应释放；依赖 DLL/静态库生命周期 | DLL 卸载后任何外部保存的指针均失效；项目没有防止宿主在卸载后继续调用的机制 |

SDK 明确提供了 `NRS_MFREE`（`elib/lib2.h:1135-1137`）和 `NL_FREE_LIB_DATA`（`elib/lib2.h:1178-1179`），但这只能说明**协议存在**，不能证明本项目实现了释放。当前 `_AQ_StringFormat_ProcessNotifyLib` 只识别 `NL_SYS_NOTIFY_FUNCTION`，其他消息返回 `NR_ERR`（`AQStringFormatFne.cpp:41-54`）。因此“有 SDK 释放码”与“项目完成释放闭环”必须分开记录。

### 11.6 失败、崩溃和未定义行为矩阵

| 场景 | 真实源码路径 | 现状/后果 | 证据等级 |
|---|---|---|---|
| 宿主未先发送 `NL_SYS_NOTIFY_FUNCTION` | `CloneTextData:77-80`、`GReportError:95-98` 直接调用全局函数指针；只有 `AQ_StringFormat_NotifySys:33-39` 有空保护，但这两个调用方不使用包装器 | 空回调时可能空指针调用；不是结构化失败返回 | 静态已确认，L2；无宿主实测 |
| `nArgCount` 为 0、首参非文本或 `pArgInf` 为空 | `fn_wsprintf:176-177` 无条件访问 `pArgInf[0].m_pText` | 越界/空指针/错误解释，可能崩溃 | 静态已确认，L2 |
| 追加参数为未支持类型 | `:266-269` 报 `NRS_RUNTIME_ERR` 后 `return` | `pszoutbuf` 泄漏，`pRetData` 未填；错误依赖宿主回调 | 静态已确认，L2 |
| 格式串与压入类型不匹配、异常 `%` 格式或变参布局不匹配 | `:200-265` 的裸栈压参 + `:274-284` 内联汇编调用 `_vsnprintf` | C 运行库未定义行为，可能读错栈或崩溃；项目无捕获/错误码 | 静态已确认，L2；Win32 x86 实测缺失 |
| 输出达到/超过 4096 | `_vsnprintf(...,4096,...)` 返回值被忽略，随后固定复制 4096 字节 | 截断/未终止语义未归一化；可能把未初始化缓冲内容带入返回文本 | 静态已确认，L2 |
| 宿主 `NRS_MALLOC` 失败或回调返回空 | `CloneTextData:77-79` 先 `memcpy(pd,...)`，没有 `pd==NULL` 判断 | 可能崩溃；SDK 的自动运行时错误语义由宿主决定 | 静态已确认，L2 |
| DLL/宿主卸载、回调替换、进程崩溃 | `DllMain:14-22` 空操作；全局回调/句柄无卸载清理 | 无回滚、重启、残留或旧指针失效治理 | 静态已确认，L1/L2；无端到端证据 |
| 静态库查询命令名/通知函数名/依赖 | `#ifndef __E_STATIC_LIB` 排除 `g_CmdNames` 及查询返回分支 | 静态工程虽然有复用源码，但静态宿主接入契约不闭合，不能声称“静态版等价可用” | 静态已确认，L1/L2 |
| IDE 日志窗口不存在或窗口重建 | `OutputStringToELog:132-139` 使用固定类名、控件 ID 和消息号；主调用被注释 | 当前不可达；未来启用时句柄有效性/线程归属未定义 | 静态已确认，L1 |

### 11.7 L0-L4 验证等级

本项目的 L0-L4 是研究验收等级，不是易语言 SDK 的运行时常量：

- **L0：骨架/声明**——函数或方向存在，但没有完整函数体、没有公开注册或没有可达调用链。
- **L1：编译可见或孤立实现**——能进入某个工程编译路径，或有辅助代码，但未形成宿主可调用闭环。
- **L2：源码真实实现**——实现、注册关系或资源操作可由当前源码静态复核；不代表构建/宿主运行通过。
- **L3：宿主 ABI 实测**——在匹配的 Windows Win32 x86 + 易语言运行时中，真实加载、命令调用、错误/释放路径已执行并读回结果。
- **L4：生产生命周期证据**——在 L3 之上，还覆盖卸载、重复装载、并发、超限、取消/超时、宿主/子进程崩溃恢复、句柄和内存残留审计。

| 项目能力 | 当前等级 | 不能越级声称的内容 |
|---|---:|---|
| `.def` → `GetNewInf` → `s_LibInfo` → `StringFormat` 注册 | L2 | 不能声称 `.fne` 已成功加载或宿主登记成功 |
| `fn_wsprintf` 的文本/数值分支与 x86 压栈 | L2 | 不能声称格式串兼容、浮点精度、变参安全或截断契约已验证 |
| `fn_hexToString`/`fn_stringToHex` | L0 | 不能声称存在字节集能力 |
| `PFN_NOTIFY_SYS`、`NRS_MALLOC`、`NRS_RUNTIME_ERR` 交互 | L2（接线）；L1（释放闭环） | 不能声称回调有效性、宿主分配失败和释放均安全 |
| 静态 `.lib` 复用构建 | L1/L2 | 不能声称静态宿主能完成命令/通知查询注册 |
| HWND/IDE 日志辅助 | L1 | 不能声称已提供日志功能或句柄生命周期 |
| 运行核心/统一网关 | L0（本仓库无实现，仅映射目标） | 不能把平台规划写成项目已有模块 |

### 11.8 第三轮底座裁决与装配计划（不改生产底座）

| 裁决对象 | 结论 | 允许吸收的边界 |
|---|---|---|
| `MDATA_INF` 一字节对齐、`PFN_EXECUTE_CMD` CDECL、`GetNewInf`/`.def`、命令元数据表 | **吸收**为 ABI 支持库的证据和兼容测试夹具 | 只吸收字段/调用约定/版本元数据事实；仍需在目标 Windows x86 实测 |
| `fn_wsprintf` 的 x86 内联汇编和固定 4096 复制 | **待核并隔离**，不直接升级为平台文本能力 | 可作为遗留 FNE 适配器；平台文本支持库必须重新定义类型、长度、错误和编码契约 |
| `PFN_NOTIFY_SYS` 全局裸回调、`NRS_MALLOC` 直连 | **待核** | 由 ABI 适配层封装；回调登记、代际/失效检查、释放和崩溃隔离交给运行核心 |
| `OutputStringToELog`/固定 `HWND` | **废弃/隔离**为非主链诊断线索 | 不进入文本支持库公开能力、网关协议或运行核心通用句柄 API |
| `fn_hexToString`/`fn_stringToHex` | **废弃**当前能力声明，除非另有完整实现证据 | 不注册、不写入能力目录、不用骨架推导需求 |
| 网关接入 | **待核**，本项目没有网关 | 若平台需要对外服务，网关只做认证/限流/契约/错误归一化，调用文本支持库，不承载 FNE ABI |

装配计划只保留一条链：

```text
网关请求（可选）
  → 运行核心监督与资源预算
  → ABI 支持库适配（仅在需要兼容 FNE/易语言宿主时）
  → 文本支持库“有界字符串格式化”能力
  → 统一结果/错误码/证据
  → 运行核心释放与残留检查
```

对本项目现状，不能回写任何平台代码、能力注册表、网关路由或运行核心模块；后续若真正生产化，前置验收必须至少补齐：Windows Win32 x86 实机加载、命令调用、错误类型、4096 边界、宿主回调未初始化、`NRS_MALLOC` 失败、静态库接入、卸载/重复加载、并发调用和崩溃后残留检查。

### 11.9 本轮证据与验证边界

- 本轮重新读取的关键证据：`AQStringFormatFne/AQStringFormatFne.cpp:8-288`、`AQStringFormatFne/AQStringFormatFne.h:17-129`、`AQStringFormatFne/AQStringFormatFne.def:1-4`、`AQStringFormatFne/AQStringFormatFne.dsp:5-128`、`AQStringFormatFneStatic/AQStringFormatFneStatic.dsp:5-112`、`AQStringFormatFne/elib/lib2.h:815-883,1124-1146,1171-1224,1232-1329`、`AQStringFormatFne/StdAfx.h:15-24`。
- 本轮做了源码静态读取和编码/符号定位；没有在 macOS 上伪造 Windows 构建结果，没有安装依赖，没有启动易语言宿主，没有运行 `.fne`，也没有执行 DLL/FNE ABI、句柄释放或崩溃恢复实测。
- 因此本轮所有 L3/L4 项均保持“未验证”，失败矩阵中的崩溃结论是由可见的空指针、越界、裸变参和未清理路径推导的静态风险，不是虚构的运行日志。
