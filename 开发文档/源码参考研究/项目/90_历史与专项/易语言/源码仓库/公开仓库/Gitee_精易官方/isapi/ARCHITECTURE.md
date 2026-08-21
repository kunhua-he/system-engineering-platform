# isapi 架构建档

> 首轮全量架构建档。本文只依据本地仓库源码、工程文件和 Git 现场证据整理；源码文件主要为 GBK 编码。文中明确区分“源码已实现”“仅声明/元数据”“未验证”，不把命令注释或库说明误写成运行时能力。

## 1. 项目定位

`isapi` 是精易官方仓库中的易语言支持库源码，目标是向易语言 IDE/编译器注册一组面向 Microsoft IIS ISAPI Extension/Filter 的数据类型、命令和枚举，并以支持库 DLL（工程目标扩展名为 `.fne`）或静态库形式供易语言程序使用。

源码中的库元信息把本库命名为“互联网服务支持库”，GUID 为 `0DD316AB105442f882C4B535F45E63CB`，版本为 `3.1.1`，要求易语言系统及核心支持库版本 `3.7`，支持 Windows，语言版本为 `__GBK_LANG_VER`。库说明覆盖两条设计路径：

- 互联网扩展（Extension）：用户在 IIS 导出函数 `GetExtensionVersion`、`HttpExtensionProc`、可选的 `TerminateExtension` 中调用本支持库对象命令。
- 互联网筛选器（Filter）：用户在 IIS 导出函数 `GetFilterVersion`、`HttpFilterProc`、可选的 `TerminateFilter` 中调用本支持库对象命令。

**重要实现结论：**当前 `isapi_cmdDef.cpp` 中 83 个命令函数都只有参数读取或空函数体，没有看到对 IIS `EXTENSION_CONTROL_BLOCK`、`HTTP_FILTER_CONTEXT`、`ServerSupportFunction` 等真实 ISAPI 结构/函数的调用。因此，当前仓库已实现的是支持库登记、命令签名和元数据骨架；命令业务行为在本地源码中未实现或至少未被实现证据覆盖，不能据库说明推断为可运行的 ISAPI 封装。

## 2. 首轮范围与结论分级

| 分级 | 本轮结论 |
|---|---|
| 源码已实现 | Visual Studio solution/project 配置；动态库与静态库目标定义；`GetNewInf` 导出；库级 `LIB_INFO` 元数据；命令/参数/自定义数据类型登记表；通知转发骨架；`elib/fnshare.*` 中的内存、数组、文本/字节集辅助函数。 |
| 仅声明/元数据 | `isapi_cmd_typedef.h` 中命令宏登记的 83 个命令签名；`isapi_cmdDef.cpp` 中各命令的函数入口及参数局部变量；IIS 事件、返回值、服务器变量和扩展函数枚举；`Source_isapi.def` 对 `GetNewInf` 的导出声明。 |
| 未实现或未验证 | 命令是否真的向客户端写数据、读取请求、处理 Cookie/Session、调用 IIS 扩展函数、修改筛选器上下文、执行认证/日志/URL 映射；Windows/Visual Studio 实际编译、`.fne` 加载、易语言 IDE 显示和 IIS 集成；x64 配置是否能导出 `GetNewInf`；静态库与支持库宿主的完整链接行为。 |

## 3. 总体流程图

```text
源码与工程文件
    |
    +--> isapi.sln
    |       |
    |       +--> isapi.vcxproj --------------------+
    |       |       |                               |
    |       |       +--> .cpp/.h + elib ------------+--> 动态库目标（配置为 .fne）
    |       |                                       |
    |       +--> isapi_static/isapi_static.vcxproj-+--> 静态库目标（.lib，名称/输出未在文件中明确）
    |
    +--> include_isapi_header.h
            |
            +--> isapi_cmd_typedef.h
            |       |
            |       +--> ISAPI_DEF(_MAKE)：统一生成命令声明、实现指针表、命令信息表、函数名表
            |
            +--> isapi_cmdDef.cpp：83 个命令入口（当前主要为参数读取/空体）
            +--> isapi_cmdInfo.cpp：参数说明与 CMD_INFO（动态库条件编译）
            +--> isapi_dtType.cpp：自定义数据类型、方法索引、枚举成员（动态库条件编译）
            +--> isapi_const.cpp：空常量表（动态库条件编译）
            +--> isapi_dllMain.cpp
                    |
                    +--> DllMain（当前仅返回 TRUE）
                    +--> g_LibInfo_isapi_global_var
                    +--> GetNewInf() ------------------> 易语言宿主读取支持库信息
                    +--> isapi_ProcessNotifyLib_isapi
                            |
                            +--> NL_SYS_NOTIFY_FUNCTION --> elib/fnshare.cpp 保存通知函数
                            +--> 其它支持库通知          --> 当前多数分支空处理

易语言宿主 / IIS 调用链（设计目标，运行效果未验证）
    易语言程序导出的 IIS 函数
        |
        +--> GetExtensionVersion / GetFilterVersion
        +--> HttpExtensionProc / HttpFilterProc
                |
                +--> 调用本支持库对象命令
                        |
                        +--> 当前源码仅读取 PMDATA_INF 参数
                        +--> 未见真实 IIS 上下文调用
```

## 4. 目录与模块地图

```text
isapi/
├── isapi.sln                         两个 Visual Studio C++ 项目的 solution
├── isapi.vcxproj                     动态库项目，ConfigurationType=DynamicLibrary
├── isapi_static/
│   ├── isapi_static.vcxproj          静态库项目，ConfigurationType=StaticLibrary
│   ├── isapi_static.vcxproj.filters  静态库文件筛选器
│   └── isapi_static.vcxproj.user     空用户属性组
├── isapi.vcxproj.filters              动态库文件筛选器
├── isapi.vcxproj.user                 空用户属性组
├── Source_isapi.def                   动态库模块定义，仅导出 GetNewInf
├── include_isapi_header.h             统一包含与外部全局表声明
├── isapi_cmd_typedef.h                ISAPI_DEF 命令目录、命名宏、签名登记
├── isapi_cmdDef.cpp                   命令函数入口骨架
├── isapi_cmdInfo.cpp                  参数元数据、CMD_INFO 表（非静态库）
├── isapi_dtType.cpp                   数据类型/枚举元数据（非静态库）
├── isapi_const.cpp                    常量元数据（当前数量为 0）
├── isapi_dllMain.cpp                  DllMain、LIB_INFO、GetNewInf、通知处理
└── elib/
    ├── lib2.h                         易语言支持库 ABI、类型、通知码和结构定义
    ├── fnshare.h / fnshare.cpp        通知转发与宿主内存/数据辅助函数
    ├── lang.h                         GBK/语言版本宏
    ├── krnllib.h                      系统核心支持库版本/GUID 常量
    ├── mtypes.h                       Windows/基础类型兼容定义
    ├── PublicIDEFunctions.h           IDE 辅助接口声明
    └── untshare.h                     通用支持库辅助声明/模板片段
```

### 模块职责

| 模块 | 职责 | 现状 |
|---|---|---|
| `isapi_cmd_typedef.h` | 通过单一 `ISAPI_DEF(_MAKE)` 目录登记命令索引、中文名、英文名、返回类型、参数数量、参数表偏移和状态位；`ISAPI_NAME` 生成类似 `isapi_test_0_isapi` 的符号名。 | 已实现元数据宏；不是业务执行层。 |
| `isapi_cmdDef.cpp` | 为命令目录提供 `PFN_EXECUTE_CMD` 兼容的 C 导出函数入口。 | 83 个函数均存在；43 个函数含参数局部读取，其余为空；未见业务调用和返回值写回。 |
| `isapi_cmdInfo.cpp` | 定义 100 项左右的参数说明数组，并由 `ISAPI_DEF_CMDINFO` 生成 `CMD_INFO` 表及数量。 | 动态库编译时实现登记；`__E_STATIC_LIB` 下整体排除。 |
| `isapi_dtType.cpp` | 定义两个对象类型及其方法索引，及 IIS 相关枚举成员，生成 `LIB_DATA_TYPE_INFO` 表。 | 动态库编译时实现登记；`__E_STATIC_LIB` 下整体排除。 |
| `isapi_const.cpp` | 提供库常量表。 | 当前 `g_ConstInfo...` 数组长度为 1，但数量变量为 0，没有实际常量成员。 |
| `isapi_dllMain.cpp` | DLL 入口、命令函数指针表、库信息、`GetNewInf`、系统通知入口及静态编译函数名表。 | 支持库 ABI 骨架已实现；`DllMain` 四类事件均无额外逻辑。 |
| `elib/fnshare.*` | 保存易语言宿主通知函数；提供 `NotifySys`、`ProcessNotifyLib`、`SetUserSysNotify` 以及宿主内存和易语言数组/字节集格式辅助。 | 辅助逻辑有实际实现；不是 IIS 适配实现。 |
| `elib/lib2.h` 等 | 提供易语言支持库 ABI：`LIB_INFO`、`CMD_INFO`、`ARG_INFO`、`MDATA_INF`、通知码、数据类型和宏。 | 作为随仓库附带的 ABI 依赖被直接包含。 |

## 5. 构建与装载边界

### 5.1 Solution 与目标

`isapi.sln` 声明两个 C++ 项目：

- `isapi`：`isapi.vcxproj`，动态库；
- `isapi_static`：`isapi_static/isapi_static.vcxproj`，静态库。

Solution 提供 `Debug|x86`、`Release|x86`、`Debug|x64`、`Release|x64` 四组映射；x86 映射到工程的 `Win32`，x64 映射到 `x64`。

两个工程都使用：

- `WindowsTargetPlatformVersion=10.0.15063.0`；
- `PlatformToolset=v141`；
- Unicode 字符集；
- `/W3`、`SDLCheck=true`、`ConformanceMode=true`；
- Debug 使用静态多线程调试运行库，Release 使用静态多线程运行库。

动态库 x86 的 `TargetExt` 明确设置为 `.fne`；x64 条件组没有同样的 `TargetExt` 设置。动态库的 Win32 Debug/Release 链接组明确设置 `ModuleDefinitionFile=Source_isapi.def`，x64 链接组没有该设置。由于本仓库未在当前 macOS 环境执行 Visual Studio/MSBuild，x64 是否仍通过其它机制导出 `GetNewInf` 未验证。

### 5.2 编译单元

动态库和静态库均编译以下源文件：

- `elib/fnshare.cpp`
- `isapi_cmdDef.cpp`
- `isapi_cmdInfo.cpp`
- `isapi_const.cpp`
- `isapi_dllMain.cpp`
- `isapi_dtType.cpp`

静态库工程通过 `..\` 路径复用根目录源码，不含独立实现副本。动态库还把 `Source_isapi.def` 列为工程 None 项，并在 Win32 链接设置中引用它。

### 5.3 导出接口

`Source_isapi.def` 内容只有：

```text
LIBRARY

EXPORTS
    GetNewInf
```

`isapi_dllMain.cpp` 中 `GetNewInf()` 返回 `&g_LibInfo_isapi_global_var`，这是当前源码可以确认的支持库宿主入口。命令函数通过宏生成并放入 `g_cmdInfo_isapi_global_var_fun[]`，它们不是 `.def` 中的 DLL 公共导出项。

## 6. 核心数据模型

### 6.1 易语言 ABI 数据

`elib/lib2.h` 定义支持库 ABI：

- `LIB_INFO`：库格式号、GUID、版本、所需系统/核心库版本、库名、语言、说明、数据类型表、命令表、命令函数指针表、通知函数、常量表和依赖文件列表。
- `CMD_INFO`：命令中文名/英文名/说明、分类、状态、返回类型、用户级别、参数个数和 `ARG_INFO` 起始指针。
- `ARG_INFO`：参数名、说明、图像索引、类型、默认值和参数标志。
- `LIB_DATA_TYPE_INFO`：自定义数据类型名称、英文名、说明、方法索引数组以及枚举/成员数组。
- `LIB_DATA_TYPE_ELEMENT`：枚举或复合类型成员的类型、名称、英文名、说明、状态和默认值。
- `MDATA_INF`：运行时命令返回值/参数载体，支持整数、布尔、日期、文本、字节集、复合数据及对应指针字段；命令函数签名为 `void(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)`。

命令通过 `pArgInf[1]...pArgInf[n]` 读取参数。`isapi_cmdDef.cpp` 中可见的读取方式包括 `m_int`、`m_pText`、`m_byte`、`m_bool`、`m_date`、`m_pBin`、`m_pInt`、`m_ppText`，与 `ARG_INFO` 中声明的参数类型大体对应；但是当前函数没有将结果写入 `pRetData`，也没有调用宿主分配/释放或 IIS API。

### 6.2 本库自定义类型

`isapi_dtType.cpp` 声明 13 个数据类型槽位，其中 11 个有名称、2 个为隐藏空槽：

| 类型 | 形式 | 证据中的内容 |
|---|---|---|
| `互联网扩展` / `InternetExtension` | 对象型 | 方法索引 `0..30`；隐藏成员包括句柄、前标志、后标志。 |
| `互联网扩展返回值` / `InternetExtensionResult` | 枚举 | `成功=1`、`失败=4`、`成功并保持连接=2`、`PENDING=3`。 |
| `服务器变量类型` / `ServerVariable` | 枚举 | 40 个 IIS 服务器变量成员，如 `ALL_HTTP`、`CONTENT_LENGTH` 等。 |
| `互联网扩展函数` / `ServerSupportFunction` | 枚举 | 33 个扩展函数值，供扩展对象的“调用扩展函数”命令使用。 |
| 隐藏槽位 004、005 | 隐藏 | 没有名称、方法或成员。 |
| `互联网筛选器` / `InternetFilter` | 对象型 | 方法索引 `59..82`；隐藏成员为 1 个句柄成员。 |
| `筛选器事件` / `FilterNotificationType` | 枚举 | 11 个 IIS 筛选器通知事件。 |
| `筛选器端口` / `FilterSecurePort` | 枚举 | 安全/非安全端口两项。 |
| `筛选器优先级` / `FilterPriority` | 枚举 | 4 个优先级成员。 |
| `筛选器返回值` / `FilterResult` | 枚举 | 6 个筛选器返回值。 |
| `筛选器扩展函数` / `FilterServerSupportFunction` | 枚举 | 9 个 `SF_REQ_*` 值。 |
| `筛选器拒绝理由` / `FilterDeniedReason` | 枚举 | 登录、访问控制列表、筛选器、扩展程序或 CGI、服务器配置等 5 项。 |

这些枚举成员是编译期元数据及常量值，不等价于本库已经调用了对应 IIS API。

### 6.3 命令目录

`ISAPI_DEF` 共登记索引 `0..82` 的 83 个命令：

- 索引 `0..30`：`互联网扩展` 对象的构造/析构及请求读写、URL 编解码、模板替换、Cookie、Session、重定向、扩展函数调用等命令。
- 索引 `31..58`：28 个隐藏的“无法识别的名字”占位命令。
- 索引 `59..82`：`互联网筛选器` 对象的构造/析构、事件初始化、事件类型、服务器变量、HTTP 头、客户端写入、内存、读写数据、认证、URL 映射、日志、拒绝访问信息等命令。

`isapi_cmdInfo.cpp` 的参数表索引最高到 `99`，参数类型使用 `SDT_INT`、`SDT_TEXT`、`SDT_BYTE`、`SDT_BOOL`、`SDT_DATE_TIME`、`SDT_BIN`，并使用 `AS_HAS_DEFAULT_VALUE`、`AS_DEFAULT_VALUE_IS_EMPTY`、`AS_RECEIVE_VAR` 等标志表达可选参数和引用参数。

## 7. 真实数据流与调用链

### 7.1 支持库加载/登记链（源码有实现）

```text
易语言宿主
  |
  +--> 加载动态库并查找 GetNewInf
          |
          +--> GetNewInf()
                  |
                  +--> g_LibInfo_isapi_global_var
                          |
                          +--> g_DataType_isapi_global_var（非静态库）
                          +--> g_cmdInfo_isapi_global_var
                          +--> g_cmdInfo_isapi_global_var_fun
                          +--> g_ConstInfo_isapi_global_var（数量为 0）
                          +--> isapi_ProcessNotifyLib_isapi
```

### 7.2 系统通知链（部分有实现）

```text
易语言系统
  |
  +--> isapi_ProcessNotifyLib_isapi(nMsg, dwParam1, dwParam2)
          |
          +--> NL_SYS_NOTIFY_FUNCTION
          |      +--> ProcessNotifyLib(...)
          |             +--> s_pfnNotifySys = dwParam1
          |             +--> 首次尝试 NotifySys(NRS_GET_PRG_TYPE,...)
          |
          +--> 其它消息
          |      +--> NL_GET_CMD_FUNC_NAMES：动态库返回命令名数组
          |      +--> NL_GET_NOTIFY_LIB_FUNC_NAME：返回通知函数名
          |      +--> NL_GET_DEPENDENT_LIBS：返回 "\\0\\0"
          |      +--> NL_FREE_LIB_DATA / NL_UNLOAD_FROM_IDE / NR_DELAY_FREE / NL_IDE_READY / ...：空处理
          |
          +--> 默认消息：返回 NR_ERR
```

在 `fnshare.cpp` 中，`ProcessNotifyLib` 还会在 `s_pfnuserNotifySys` 非空时把通知转发给用户函数；用户函数由 `SetUserSysNotify` 设置。`NotifySys` 在宿主通知指针非空时转调宿主，否则返回 0。

### 7.3 命令执行链（入口有实现，业务未实现）

```text
易语言运行时
  |
  +--> 从 CMD_INFO 取命令索引与 PFN_EXECUTE_CMD
          |
          +--> isapi_<命令>_<索引>_isapi(pRetData, nArgCount, pArgInf)
                  |
                  +--> 部分函数读取 pArgInf[1..n] 到局部变量
                  +--> 当前没有 pRetData 写回
                  +--> 当前没有 IIS API/上下文调用
                  +--> 调用结果与内存生命周期：未验证/未实现证据
```

## 8. 接口清单

### 8.1 支持库 ABI 接口

| 接口/符号 | 位置 | 说明 | 状态 |
|---|---|---|---|
| `GetNewInf` | `isapi_dllMain.cpp:89-92`、`Source_isapi.def` | 返回 `PLIB_INFO`，动态库宿主入口。 | 源码已实现；实际导出/加载未验证。 |
| `isapi_ProcessNotifyLib_isapi` | `isapi_dllMain.cpp:101-178` | 处理宿主通知，提供命令名、通知函数名、依赖库列表和系统通知转发。 | 源码已实现部分分支；宿主交互未验证。 |
| `g_cmdInfo_isapi_global_var_fun` | `isapi_dllMain.cpp:26-29` | 由 `ISAPI_DEF` 展开的命令函数指针数组。 | 源码已实现表生成。 |
| `g_cmdInfo_isapi_global_var` | `isapi_cmdInfo.cpp:175-180` | 命令显示/参数元数据。 | 源码已实现登记（非静态库）。 |
| `g_DataType_isapi_global_var` | `isapi_dtType.cpp:218-317` | 自定义数据类型与枚举元数据。 | 源码已实现登记（非静态库）。 |

### 8.2 命令接口分组

| 分组 | 索引 | 代表命令 | 设计输入/输出 | 实现状态 |
|---|---:|---|---|---|
| 扩展生命周期 | 0-3 | `InitVersionInfo`、`InitHttp` | IIS 版本信息、描述、扩展上下文；返回布尔/空 | 仅签名与参数读取，未见实际初始化。 |
| 扩展请求/响应 | 4-10、26-30 | `WriteText`、`GetServerVar`、`ReadText`、`ReadBin`、`Redirect`、`SendResponeHeaderEx` | 文本、字节集、HTTP 状态/头 | 仅声明/骨架；未见 `EXTENSION_CONTROL_BLOCK` 调用。 |
| 编解码/模板 | 11-15、25 | `DecodeText`、`GetKeyField`、`TemplateReplace`、`EncodeText` | 文本与标志 | 仅参数读取；未见算法实现。 |
| Cookie/Session | 16-24 | `SetCookie`、`GetCookie`、`SessionStart` 等 | Cookie、会话名值、超时 | 仅参数读取/空体；未见状态存储。 |
| 筛选器生命周期/事件 | 59-66 | `FilterInitVersion`、`FilterInitFilterProc`、`FilterGetEventType` | `HTTP_FILTER_*` 上下文、事件通知 | 仅签名/元数据；未见上下文保存。 |
| 筛选器响应/数据 | 67-76 | HTTP 头、写客户端、申请内存、原始数据 | 文本、字节集、指针引用 | 仅参数读取；未见 `HTTP_FILTER_CONTEXT` 调用。 |
| 筛选器认证/映射/日志 | 77-82 | `FilterGetAuthInfo`、`FilterURLMap`、`FilterGetLogInfo` | 引用文本/整数、URL/日志信息 | 仅参数读取；未见 IIS 调用。 |

## 9. 依赖与平台边界

### 仓库内依赖

- `elib/lib2.h`：核心支持库 ABI 与 Windows/易语言数据类型、通知码、函数签名。
- `elib/lang.h`：语言编码常量；`__COMPILE_LANG_VER` 固定为 GBK。
- `elib/mtypes.h`：基础类型兼容层，定义 `INT`、`DWORD`、`LPBYTE`、`HINSTANCE` 等。
- `elib/fnshare.h/.cpp`：宿主通知、内存、文本、数组和字节集辅助。
- `elib/krnllib.h`：系统核心支持库版本/GUID 常量；本工程直接包含但 `LIB_INFO` 的需求版本字段是源码手写的 `3.7`。
- `elib/PublicIDEFunctions.h`、`elib/untshare.h`：IDE/通用支持库接口声明，当前核心源文件未显示实际调用。

### 工具链/外部平台

- Visual Studio C++ 项目格式，工具集 `v141`。
- Windows SDK 目标 `10.0.15063.0`。
- 运行宿主是易语言支持库 ABI，入口名固定为 `GetNewInf`。
- 目标运行环境设计上依赖 IIS ISAPI Extension/Filter API；当前源码没有包含 IIS 头文件或调用实现证据。
- 本仓库没有第三方包清单、NuGet/CMake/Makefile、安装脚本或运行时配置文件。

## 10. 测试与验证现状

### 仓库内测试

现场盘点未发现测试目录、测试源文件、CI 配置、README 或独立验证脚本。`isapi.sln` 只包含构建项目，没有测试项目。

### 本轮已做的静态验证

- 人工读取 `isapi.sln`、两个 `.vcxproj`、两个 `.filters`、两个 `.user`、`Source_isapi.def`。
- 人工读取核心源文件 `isapi_dllMain.cpp`、`isapi_cmdDef.cpp`、`isapi_cmdInfo.cpp`、`isapi_dtType.cpp`、`isapi_const.cpp`、`isapi_cmd_typedef.h`、`include_isapi_header.h`。
- 人工读取 `elib/fnshare.cpp/.h`、`elib/lib2.h`、`elib/lang.h`、`elib/mtypes.h`，并核对 ABI 类型与命令入口签名。
- 静态统计确认：命令目录索引 `0..82` 共 83 项；筛选器对象方法索引 `59..82`；扩展对象方法索引 `0..30`；数据类型表有 13 个槽位，其中 11 个命名类型；`isapi_cmdDef.cpp` 有 83 个入口，函数体中只观察到参数局部读取，没有观察到 `pRetData` 写回或 IIS API 调用。
- Git 工作树初始状态为干净的 `master` 分支，且 `master` 与 `origin/master` 同步。

### 未执行/不能据此宣称通过的验证

- 未在 macOS 上执行 Visual Studio/MSBuild，未验证 Win32/x64 Debug/Release 编译。
- 未生成或加载 `.fne`/`.lib`，未验证 `GetNewInf` 导出、ABI 兼容和易语言 IDE 注册。
- 未在 IIS 上部署 Extension/Filter，未验证 HTTP 请求、响应、Cookie、Session、认证、日志、URL 映射或筛选器事件。
- 未运行命令级单元测试；当前源码也没有可直接运行的测试目标。

## 11. 风险、矛盾与后续复核点

1. **命令实现严重不完整：**命令函数均有入口，但参数读取后没有业务逻辑和返回值写回；本项目不能按库说明认定为可用 ISAPI 支持库。
2. **ISAPI 上下文缺失：**源码中未发现 `EXTENSION_CONTROL_BLOCK`、`HTTP_FILTER_CONTEXT`、`GetExtensionVersion`、`HttpExtensionProc`、`GetFilterVersion`、`HttpFilterProc` 的具体封装实现或状态保存结构。
3. **x64 导出风险：**Win32 工程组明确引用 `Source_isapi.def`，x64 工程组没有该设置；需要在 Windows/Visual Studio 中确认 `GetNewInf` 是否导出，否则 x64 DLL 可能无法被宿主加载。
4. **静态库条件编译差异：**`isapi_cmdInfo.cpp`、`isapi_dtType.cpp`、`isapi_const.cpp` 的主要全局表都位于 `#ifndef __E_STATIC_LIB` 中；静态库工程只在 Win32 Debug/Release 预定义 `__E_STATIC_LIB` 与 `__E_FNENAME=isapi`，x64 配置未定义这些宏，静态/动态行为可能不一致，必须在目标工具链中复核。
5. **配置不一致：**静态库 Win32 使用 `__E_STATIC_LIB`、`__E_FNENAME=isapi`，但 x64 Debug/Release 的预处理定义仅有 `_DEBUG;_LIB` 或 `NDEBUG;_LIB`；这可能导致宏展开、表定义与预期不同。
6. **ABI/指针宽度风险：**`elib/mtypes.h` 把 `DWORD` 定义为 `unsigned long`，并在辅助函数中把指针转换为 `DWORD`；这套代码显然面向旧式 Windows/易语言 ABI，x64 可移植性未验证。
7. **命名和文案历史遗留：**命令索引 6 的英文名为 `GetDataMethoed`，索引 24 返回类型登记为 `SDT_TEXT` 但说明是会话轮询时间；这些是源码登记事实，不应在文档中擅自修正。
8. **编码依赖：**源码包含中文 GBK 文本，`lang.h` 明确设置 `__GBK_LANG_VER`；不同编译器源码编码设置未验证。
9. **依赖声明为空：**`LIB_INFO.m_szzDependFiles=NULL`，通知分支 `NL_GET_DEPENDENT_LIBS` 返回空列表；这只说明本库未声明附加静态库依赖，不代表 IIS 或易语言运行时依赖不存在。

建议后续轮次按以下顺序复核：先在 Windows 中验证四组构建和导出，再定位历史版本/上游是否存在真正 ISAPI 实现；如要补实现，应先建立 IIS 结构到易语言对象状态的生命周期模型，再补命令测试和宿主集成测试。

## 12. Git 基线与证据路径

### Git 基线

- 仓库：`~/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/isapi`
- 分支：`master`
- HEAD：`6f53cefe0490c4145d6c141a65d2efb967a37f61`
- 提交时间：`2022-12-19 16:56:10 +0800`
- 提交说明：`初始化仓库`
- 远程：`https://gitee.com/JYtechnology/isapi.git`
- 现场状态：初始工作树干净，`master...origin/master`，HEAD 与 `origin/master`/`origin/HEAD` 一致；本轮只新增/更新本文件，未修改源码、工程、依赖、测试、配置或 Git 元数据。

### 关键证据路径

- 库入口与元信息：`isapi_dllMain.cpp:5-100`
- 通知处理：`isapi_dllMain.cpp:101-178`
- 命令函数入口：`isapi_cmdDef.cpp:1-773`
- 命令目录与索引：`isapi_cmd_typedef.h:3-95`
- 参数元数据：`isapi_cmdInfo.cpp:5-180`
- 自定义类型与枚举：`isapi_dtType.cpp:3-321`
- 空常量表：`isapi_const.cpp:12-18`
- 统一包含与全局表声明：`include_isapi_header.h:1-26`
- 动态库导出：`Source_isapi.def:1-4`
- 动态库工程：`isapi.vcxproj:21-201`
- 静态库工程：`isapi_static/isapi_static.vcxproj:21-166`
- Solution 配置：`isapi.sln:5-40`
- 通知/内存/数组辅助：`elib/fnshare.cpp:1-71`、`elib/fnshare.h:20-169`
- 支持库 ABI：`elib/lib2.h:266-364`、`elib/lib2.h:369-389`、`elib/lib2.h:693-824`、`elib/lib2.h:1155-1317`
- 语言和基础类型：`elib/lang.h:6-14`、`elib/mtypes.h:4-176`

> 本文已吸收本仓库首轮源码与工程细探；后续架构维护以根目录 `ARCHITECTURE.md` 为唯一正式文档，不另建平行细探文档。
