# deelxregex 架构建档

> 本文件为首轮全量架构建档的唯一项目事实文档。本文档依据当前工作树源码、Visual Studio 工程文件和 Git 元数据整理；不把仓库宣传信息当作已实现能力。后续细探只增量维护本文件。

## 1. 项目定位与当前结论

`deelxregex` 是一个面向易语言支持库 ABI 的 Windows C/C++ 工程，目标是将 DEELX 正则表达式引擎封装成易语言支持库（库显示名为“正则表达式支持库(Deelx版)”）。接口元数据声称支持 DEELX v1.2、Perl 兼容正则表达式语法和六类匹配模式：`SINGLELINE`、`MULTILINE`、`GLOBAL`、`IGNORECASE`、`RIGHTTOLEFT`、`EXTENDED`。

**首轮现场最重要的结论：当前仓库不是可用的正则引擎实现，而是支持库接口/工程骨架。** `deelxregex_cmdDef.cpp` 注册了 44 个命令函数，但命令函数体只有参数局部变量读取或空体，没有编译、匹配、搜索、替换、分割、结果对象填充或返回值写回；仓库内也没有 DEELX 引擎源码、第三方正则库源码、导入库或测试夹具。因此不能依据命令说明宣称运行时功能已经完成。

## 2. 现场版本基线

- 项目根目录：`~/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/deelxregex`
- 本地分支：`master`
- 当前提交：`bb27061c1e6482244ae64e1a8eaa5baaf836fe42`
- 当前提交时间：`2022-12-19T16:54:17+08:00`
- 当前提交主题：`初始化仓库`
- 远程：`origin https://gitee.com/JYtechnology/deelxregex.git`
- 远程默认分支：`refs/heads/master`
- 远程 `HEAD` 当前查询结果：`bb27061c1e6482244ae64e1a8eaa5baaf836fe42`
- 本地工作树：建档前 `git status --short --branch` 仅显示 `master...origin/master`，未见源码改动。
- Git 历史：仓库为浅历史（存在 `.git/shallow`），现场可见历史只有初始化提交；不能据此判断更早版本、引擎源码或发布包是否曾存在。
- 仓库统计：23 个 Git 跟踪文件，约 4,636 行；无 `README`、`LICENSE`、测试目录、示例目录、依赖锁定文件或构建脚本。

## 3. 总体流程图

```text
易语言编译器/IDE
        │
        │ 载入 .fne DLL，查找导出的 GetNewInf()
        ▼
DLL: deelxregex_dllMain.cpp
        │
        ├─ g_LibInfo_deelxregex_global_var
        │     ├─ 库版本 2.3.0、系统要求 5.3
        │     ├─ 数据类型表 g_DataType_deelxregex_global_var
        │     ├─ 命令元数据表 g_cmdInfo_deelxregex_global_var
        │     ├─ 命令函数指针表 g_cmdInfo_deelxregex_global_var_fun
        │     └─ 常量表 g_ConstInfo_deelxregex_global_var（当前数量为 0）
        │
        ├─ GetNewInf() ───────────────► 返回 PLIB_INFO
        ├─ deelxregex_ProcessNotifyLib_deelxregex()
        │     ├─ NL_GET_CMD_FUNC_NAMES
        │     ├─ NL_GET_NOTIFY_LIB_FUNC_NAME
        │     ├─ NL_GET_DEPENDENT_LIBS
        │     └─ NL_SYS_NOTIFY_FUNCTION ─► elib/fnshare.cpp
        │
        └─ 易语言按命令索引调用
              ▼
        deelxregex_cmdDef.cpp
              │
              ├─ 读取 PMDATA_INF 参数
              └─ 当前实现止于空函数/参数读取
                    （未接入 DEELX 引擎，未写回 pRetData）

静态库路径：
Visual Studio Solution
  ├─ deelxregex.vcxproj ─────► DLL / .fne（动态库目标）
  └─ deelxregex_static/deelxregex_static.vcxproj
                              └► 静态库目标，复用上层 6 个实现源文件
```

## 4. 目录与文件地图

### 4.1 构建入口

| 路径 | 作用 | 现场事实 |
|---|---|---|
| `deelxregex.sln` | Visual Studio 解决方案 | 包含 DLL 项目和静态库项目；解决方案配置为 `Debug/Release` × `x64/x86`，`x86` 映射项目的 `Win32` |
| `deelxregex.vcxproj` | 动态库工程 | `ConfigurationType=DynamicLibrary`；编译 6 个 `.cpp`；Win32 Debug/Release 设置 `TargetExt=.fne` 并引用 `Source_deelxregex.def` |
| `deelxregex_static/deelxregex_static.vcxproj` | 静态库工程 | `ConfigurationType=StaticLibrary`；通过 `..\` 路径复用同一组 6 个 `.cpp` |
| `*.vcxproj.filters` | Visual Studio 文件筛选器 | 仅组织 IDE 显示，不改变编译依赖 |
| `*.vcxproj.user` | 用户工程设置 | 当前只有空的 `PropertyGroup`，无调试启动配置 |
| `Source_deelxregex.def` | DLL 导出定义 | 仅显式导出 `GetNewInf`；`LIBRARY` 名为空 |

### 4.2 支持库桥接层

| 路径 | 作用 |
|---|---|
| `include_deelxregex_header.h` | 总头文件；引入 `elib` ABI 头、命令定义；声明全局元数据表；用 `DEELXREGEX_DEF_CMD` 批量生成 44 个命令函数声明 |
| `deelxregex_cmd_typedef.h` | 命令索引/英文名/显示名/说明/返回类型/参数信息的 X-macro 单一清单；定义符号命名宏 `DEELXREGEX_NAME` |
| `deelxregex_cmdDef.cpp` | 44 个命令入口的实现骨架；目前没有业务执行逻辑 |
| `deelxregex_cmdInfo.cpp` | `ARG_INFO` 参数描述数组和 `CMD_INFO` 命令描述数组；由同一 `DEELXREGEX_DEF` 清单生成命令元数据 |
| `deelxregex_dtType.cpp` | 两个用户数据类型的方法索引表、一个常量枚举类型表、`LIB_DATA_TYPE_INFO` 数据类型元数据 |
| `deelxregex_const.cpp` | 支持库常量表；当前 `g_ConstInfo_deelxregex_global_var_count=0`，没有实际全局常量 |
| `deelxregex_dllMain.cpp` | DLL 生命周期空钩子、命令函数指针表、库描述 `LIB_INFO`、`GetNewInf()`、通知处理函数和静态库辅助命令名表 |

### 4.3 `elib` 易语言 ABI/运行时辅助头

| 路径 | 作用 |
|---|---|
| `elib/lib2.h` | 易语言支持库 SDK 核心 ABI：命名宏、`CMD_INFO`、`ARG_INFO`、`LIB_INFO`、`LIB_DATA_TYPE_INFO`、`PFN_EXECUTE_CMD`、通知编号和返回码等 |
| `elib/mtypes.h` | Windows/易语言兼容基础类型、指针别名、句柄别名、宏和结构体 |
| `elib/lang.h` | 编译语言版本常量；本库通过 `__GBK_LANG_VER` 声明 GBK 中文环境 |
| `elib/krnllib.h` | 系统核心支持库相关接口声明 |
| `elib/fnshare.h` | 易语言内存申请/释放、文本/字节集/数组包装、系统通知转发等辅助函数和宏 |
| `elib/fnshare.cpp` | `NotifySys`、`ProcessNotifyLib`、调试版本识别、用户通知回调保存；实现依赖易语言宿主通过通知回调注入的函数指针 |
| `elib/PublicIDEFunctions.h` | 易语言 IDE 公共函数声明集合；当前项目源文件未见直接使用其实现 |
| `elib/untshare.h` | SDK 通用共享定义；当前主要作为工程头文件集合的一部分 |

## 5. 分层与职责边界

```text
宿主层：易语言 IDE / 编译器 / 运行时
  └─ 支持库加载、通知回调、PMDATA_INF 参数与返回值管理、易语言内存管理

适配层：deelxregex_dllMain.cpp + include_deelxregex_header.h
  └─ 导出 GetNewInf、提供 LIB_INFO、提供命令指针表、接收系统通知

声明层：deelxregex_cmd_typedef.h + deelxregex_cmdInfo.cpp + deelxregex_dtType.cpp
  └─ X-macro 命令清单、参数契约、返回类型、数据类型方法索引、正则常量枚举

执行层：deelxregex_cmdDef.cpp
  └─ 预期承载正则对象/搜索结果对象命令；当前只有空实现和参数读取

引擎层：仓库内缺失
  └─ 未发现 DEELX parser/compiler/matcher、对象状态、捕获组存储或替换/分割算法

辅助层：elib/fnshare.* 与 elib/*.h
  └─ 易语言 SDK ABI、宿主通知和内存/数组/文本包装
```

边界判断：本仓库目前的真实职责是“易语言支持库接口壳 + 编译工程”，不是完整 DEELX 引擎。命令说明中描述的正则语义只能作为目标契约/历史意图，不能作为当前实现证据。

## 6. 数据模型与运行时状态

### 6.1 支持库注册元数据

`deelxregex_dllMain.cpp` 组装静态 `LIB_INFO`：

- GUID：`6CE139EAF3484af3AE10E402BB263AB8`
- 库版本：主版本 `2`、次版本 `3`、构建号 `0`
- 要求易语言系统：主版本 `5`、次版本 `3`
- 要求系统核心支持库版本：`0.0`
- 显示名：`正则表达式支持库(Deelx版)`
- 语言：`__GBK_LANG_VER`
- 操作系统标志：`_LIB_OS(__OS_WIN)`，定位为 Windows 支持库
- 作者字段：`邓学彬(泪闯天涯)`、`王家元(带眼镜de狼)`
- 依赖文件列表：`NULL`；通知处理函数返回的依赖列表为空字符串双零结尾
- 命令数、数据类型数、常量数：分别引用各表的编译期计数

### 6.2 自定义数据类型

`deelxregex_dtType.cpp` 声明 6 个数据类型槽位，其中可见的公开类型为：

1. `正则表达式DEELX` / `DeelxRegex`：预期持有编译后的正则表达式对象，方法索引 29 项。
2. `搜索结果DEELX` / `DeelxSearchResult`：预期持有一次匹配/搜索及捕获组位置，方法索引 15 项。
3. `正则常量` / `DeelxConst`：`LDT_ENUM` 枚举，含 6 项模式常量。
4. 其他 3 个槽位隐藏且名称为空，属于对象/内部占位槽位。

当前源码没有定义这两个对象的数据结构、构造/析构存储、复制语义、匹配结果字段、捕获组数组或所有权规则。`Copy`、`Create`、`Release` 命令均是空函数，因此对象生命周期尚未落地。

### 6.3 文本与字节集

命令元数据区分：

- `SDT_TEXT`：窄字符文本接口；源代码参数读取为 `LPSTR`。
- `SDT_BIN`：Unicode/字节集接口；源代码参数读取为 `LPBYTE`，辅助函数在 `elib/fnshare.h` 中提供数组头解析和字节复制。
- `W` 后缀命令：Unicode 字节集变体，如 `CreateW`、`MatchW`、`ReplaceW`。

命令说明称内部位置基于 Unicode 字符串；但当前未实现任何文本转换、长度计算或索引换算，不能确认该语义已实现。

## 7. 命令/API 边界

### 7.1 命令清单

命令索引是 ABI 的稳定顺序，英文实现名由 `DEELXREGEX_NAME(index, name)` 拼为类似 `deelxregex_Create_2_deelxregex` 的符号。下表按索引记录当前清单；“隐藏”表示主要供对象生命周期/内部调用，不等于实现已完成。

| 索引 | 实现名 | 目标对象 | 返回/形态 | 备注 |
|---:|---|---|---|---|
| 0 | `Create` | `DeelxRegex` | 空 | 隐藏构造 |
| 1 | `Release` | `DeelxRegex` | 空 | 隐藏析构 |
| 2 | `Create` | `DeelxRegex` | `SDT_BOOL` | 编译表达式、模式、易语言转义 |
| 3 | `Create` | `DeelxSearchResult` | 空 | 隐藏构造 |
| 4 | `Release` | `DeelxSearchResult` | 空 | 隐藏析构 |
| 5 | `Match` | `DeelxRegex` | 搜索结果对象 | 位置可选 |
| 6 | `IsEmpty` | `DeelxSearchResult` | `SDT_BOOL` | 结果为空判断 |
| 7 | `GetStart` | 结果 | `SDT_INT` | 整体匹配起点 |
| 8 | `GetEnd` | 结果 | `SDT_INT` | 整体匹配终点 |
| 9 | `GetGroupStart` | 结果 | `SDT_INT` | 按组号取起点 |
| 10 | `GetGroupEnd` | 结果 | `SDT_INT` | 按组号取终点 |
| 11 | `MaxGroupNumber` | 结果/表达式 | `SDT_INT` | 最大捕获组号 |
| 12 | `MatchExact` | `DeelxRegex` | 搜索结果对象 | 绝对匹配 |
| 13 | `GetNamedGroupNumber` | `DeelxRegex` | `SDT_INT` | 名称到组号 |
| 14 | `PrepareMatch` | `DeelxRegex` | 搜索结果对象 | 隐藏的预备匹配 |
| 15 | `Replace` | `DeelxRegex` | `SDT_TEXT` | 替换起点和次数可选 |
| 16 | `ReleaseString` | `DeelxRegex` | `SDT_BOOL` | 隐藏的返回字符串释放 |
| 17 | `GetRegExText` | `DeelxRegex` | `SDT_TEXT` | 取表达式文本 |
| 18 | `GetResultText` | 结果 | `SDT_TEXT` | 按起止位置取结果文本 |
| 19 | `GetSubExpCount` | 结果 | `SDT_INT` | 子表达式数量兼容接口 |
| 20 | `GetMatchText` | 结果 | `SDT_TEXT` | 取整体匹配文本 |
| 21 | `GetSubMatchText` | 结果 | `SDT_TEXT` | 按组号/名称取捕获文本 |
| 22 | `IsMatched` | 结果 | `SDT_INT` | 匹配状态 |
| 23 | `Search` | `DeelxRegex` | 搜索结果对象 | 兼容接口 |
| 24 | `SearchNext` | `DeelxRegex` | 搜索结果对象 | 自动偏移 |
| 25 | `SearchAll` | `DeelxRegex` | 一维结果数组 | 全部搜索 |
| 26 | `CreateW` | `DeelxRegex` | `SDT_BOOL` | Unicode 字节集表达式 |
| 27 | `MatchW` | `DeelxRegex` | 搜索结果对象 | Unicode 文本 |
| 28 | `SearchW` | `DeelxRegex` | 搜索结果对象 | Unicode 文本 |
| 29 | `SearchAllW` | `DeelxRegex` | 一维结果数组 | Unicode 全部搜索 |
| 30 | `ReplaceW` | `DeelxRegex` | `SDT_BIN` | Unicode 替换 |
| 31 | `GetRegExTextW` | `DeelxRegex` | `SDT_BIN` | Unicode 表达式文本 |
| 32 | `GetResultTextW` | 结果 | `SDT_BIN` | Unicode 结果文本 |
| 33 | `GetMatchTextW` | 结果 | `SDT_BIN` | Unicode 整体匹配 |
| 34 | `GetSubMatchTextW` | 结果 | `SDT_BIN` | Unicode 子匹配 |
| 35 | `MatchExactW` | `DeelxRegex` | 搜索结果对象 | Unicode 绝对匹配 |
| 36 | `Test` | `DeelxRegex` | `SDT_BOOL` | 完全匹配校验 |
| 37 | `TestW` | `DeelxRegex` | `SDT_BOOL` | Unicode 完全匹配校验 |
| 38 | `Split` | `DeelxRegex` | `SDT_TEXT` 数组 | 正则分割 |
| 39 | `SplitW` | `DeelxRegex` | `SDT_BIN` 数组 | Unicode 正则分割 |
| 40 | `GetAllMatchText` | `DeelxRegex` | `SDT_TEXT` 数组 | 全部整体匹配文本 |
| 41 | `GetAllMatchTextW` | `DeelxRegex` | `SDT_BIN` 数组 | Unicode 全部整体匹配 |
| 42 | `Copy` | `DeelxRegex` | 空 | 隐藏复制构造 |
| 43 | `Copy` | `DeelxSearchResult` | 空 | 隐藏复制构造 |

### 7.2 参数契约来源

`deelxregex_cmdInfo.cpp` 的 `ARG_INFO` 数组共有 43 个参数描述槽（编号 `000` 至 `042`），并由命令清单中的指针偏移复用：表达式文本、匹配文本、起始位置、分组编号、命名分组名、替换文本、替换起始位置、替换次数、结果起止位置、子表达式索引/名称、分割/匹配数量等。默认值/可空性通过 `AS_DEFAULT_VALUE_IS_EMPTY`、`AS_HAS_DEFAULT_VALUE` 等 SDK 标志表达。

`SearchAll`、`Split`、`GetAllMatchText` 及其 `W` 版本通过 `CT_RETRUN_ARY_TYPE_DATA` 表示数组返回；`GetSubMatchText` 的参数类型为 `_SDT_ALL`，契约允许组号、名称或 Unicode 字节集形式。

### 7.3 DLL/宿主协议

- `Source_deelxregex.def` 显式导出 `GetNewInf`。
- `GetNewInf()` 返回静态 `LIB_INFO` 地址，宿主从中获得元数据表和命令函数指针表。
- `deelxregex_ProcessNotifyLib_deelxregex()` 处理 `NL_GET_CMD_FUNC_NAMES`、`NL_GET_NOTIFY_LIB_FUNC_NAME`、`NL_GET_DEPENDENT_LIBS`、`NL_SYS_NOTIFY_FUNCTION` 等宿主通知。
- `NL_SYS_NOTIFY_FUNCTION` 被转发到 `elib/fnshare.cpp::ProcessNotifyLib`，用于保存宿主注入的 `PFN_NOTIFY_SYS`；`ealloc/efree` 等辅助函数依赖它调用宿主内存服务。
- `DllMain` 四类进程/线程事件当前均为空，仅返回 `TRUE`。

## 8. 真实调用链与实现缺口

以 `Create` / `Match` 为例，当前真实链路如下：

```text
易语言调用
  → 宿主按 LIB_INFO.m_pCmdsFunc[index] 取得函数指针
  → deelxregex_Create_2_deelxregex / deelxregex_Match_5_deelxregex
  → 从 pArgInf[1..n] 读取 m_pText/m_pBin/m_int/m_bool
  → （当前没有后续调用）
  → 没有 pRetData 写回，没有对象字段写入，没有错误码/异常契约
```

已确认的缺口：

1. 没有 DEELX 引擎源码或链接库；
2. 没有正则表达式编译器、AST/字节码、匹配器或回溯/并发策略；
3. 没有 `DeelxRegex` / `DeelxSearchResult` 的真实数据布局；
4. 没有结果对象构造、析构、复制和释放实现；
5. 没有 `pRetData` 返回值写入；
6. 没有字符串/字节集结果内存交给宿主的完整实现；
7. 没有数组创建、数组元素填充和数组生命周期实现；
8. 没有编译错误定位信息、匹配失败信息或错误状态；
9. `g_ConstInfo...` 数量为 0，而元数据实际把模式常量放在 `DeelxConst` 枚举数据类型中；
10. `elib/fnshare.cpp` 的宿主通知链存在，但业务命令没有调用它。

## 9. 技术栈、依赖和构建边界

### 9.1 工程配置

- C++ Visual Studio 工程，`VCProjectVersion=16.0`，解决方案文件标注 Visual Studio 17。
- 工具集：`v141`（Win32 配置明确设置）；目标 Windows SDK：`10.0.15063.0`。
- DLL 工程配置：Debug/Release × Win32/x64；Win32 Debug/Release 为 `DynamicLibrary`，运行库分别为多线程 Debug/Release。
- 静态库工程：`StaticLibrary`；Win32 Debug/Release 明确启用多处理器编译。
- DLL Win32 Debug/Release 使用 `Source_deelxregex.def`，输出扩展名设置为 `.fne`；x64 配置未看到同样的 `TargetExt`/`ModuleDefinitionFile` 设置，需后续在 Windows/Visual Studio 中验证导出和产物命名。
- 静态库 x64 配置设置了 `PrecompiledHeader=Use`，但仓库没有 `pch.h` 文件条目；这属于未验证的构建风险。
- 工程没有自定义 `AdditionalIncludeDirectories`、`AdditionalDependencies` 或 PostBuild 命令；依赖主要来自源码内的 `elib` 头和宿主 ABI。

### 9.2 依赖边界

| 类别 | 证据 | 结论 |
|---|---|---|
| 易语言 SDK/ABI | `elib/lib2.h`、`elib/mtypes.h`、`elib/fnshare.h` 等 | 必需；这些文件承担宿主数据结构、通知号、内存/数组包装 |
| Windows | `__OS_WIN`、`WINAPI`/`HMODULE`/`DllMain`/Windows 句柄和消息类型 | 目标平台明确为 Windows |
| DEELX 引擎 | `deelxregex_dllMain.cpp` 的库说明文字 | 仅有声明/宣传证据；当前仓库没有实现或链接证据 |
| 第三方正则库 | 全部 23 个跟踪文件及 include 扫描 | 未发现 PCRE、Boost.Regex、`std::regex`、正则引擎源码或外部库配置 |
| 外部运行服务/数据库/配置 | 全库扫描 | 未发现 |

源码文件为无 BOM 文本，中文注释/字符串按 GB18030/GBK 兼容方式读取可恢复；`elib/lang.h` 明确声明 `__GBK_LANG_VER`。工程未显式设置源文件编码，跨机器编译时应把编码确认列为风险。

## 10. 测试、验证和当前核对未执行事项

- 仓库没有测试文件、测试目录、测试工程、示例程序、CI 配置或测试数据。
- 当前核对只做了静态现场读取、文件清单、源码符号/内容扫描、Git 状态与远程版本查询。
- 按任务边界未安装依赖、未构建、未启动 DLL、未调用易语言宿主、未在 Windows/Visual Studio 中验证 ABI。
- 因宿主是 Windows 易语言运行时，本机 macOS 环境不能直接证明 `DllMain`/`GetNewInf`/命令表装载成功。
- `git diff --check` 等仅针对建档文档的检查可在收口阶段执行；不存在可运行的项目级测试入口。

## 11. 风险清单

| 等级 | 风险 | 证据/影响 |
|---|---|---|
| P0 | 业务命令全部为空实现 | `deelxregex_cmdDef.cpp` 的 44 个接口只有空体/参数读取；任何正则能力、返回值和对象状态均未实现 |
| P0 | DEELX 引擎缺失 | 未见引擎源文件、静态库、DLL 导入、头文件或第三方库链接；库说明不能替代实现 |
| P0 | 未定义对象内存/生命周期契约 | 两个自定义对象有元数据索引但无结构体、构造、析构、复制和释放；宿主调用可能无法安全运行 |
| P1 | 返回值和数组 ABI 未实现 | `pRetData` 从未写回；数组命令和 Unicode 字节集结果缺乏所有权/布局实现 |
| P1 | x64 工程配置不对称 | x64 DLL 配置未见 `.def`/`.fne` 设置；静态库 x64 使用预编译头但未见 `pch.h`；需在 Windows 工具链实测 |
| P1 | 编码依赖未在工程显式固定 | 中文源文件无 BOM，库宣称 GBK；不同 MSVC/编辑器代码页可能造成字符串或注释乱码 |
| P1 | ABI/指针宽度风险 | `elib/mtypes.h` 自定义 `DWORD`、句柄和 `INT`，辅助代码有把指针转 `DWORD`/`INT` 的历史兼容写法；x64 未验证，可能截断指针 |
| P2 | 版本/宣传与实现不一致 | `LIB_INFO` 宣称版本 2.3.0、DEELX v1.2、Perl 兼容语法，但仓库只有接口骨架；发布时容易误把声明当完成度 |
| P2 | 浅克隆导致历史不可见 | `.git/shallow` 且只有初始化提交；旧版实现、分支、发布产物和删除原因未确认 |
| P2 | 无自动化质量门禁 | 没有测试/CI/示例；后续修复无法通过仓库内回归证明行为兼容 |

## 12. 未确认项与后续复核点

1. `DEELX` 引擎是否通过未纳入仓库的预编译库、宿主运行时或外部文件提供；需在上游完整历史、发布包或 Windows 构建机核实。
2. 44 个空函数是否是上游刻意提交的接口模板，还是初始化提交未完成；需查远程后续提交/分支或 Gitee 页面历史。
3. `elib` 文件的授权范围和来源版本未在本仓库单独标明；需核对易语言支持库 SDK 授权文件和对应 SDK 版本。
4. `Source_deelxregex.def` 在 x64 配置是否被间接使用、`GetNewInf` 是否依靠其他导出机制；需在 Windows MSVC 中查看最终导出表。
5. x64 下 `DWORD`/`INT` 指针转换及 `LPDATA` ABI 是否由易语言 SDK 特殊约定；需用匹配位数的宿主 SDK 验证，不能在 macOS 上推断。
6. `GetSubExpCount` 的目标对象虽列在结果对象方法索引中，但命令清单说明为表达式兼容接口；真实宿主绑定归属需查 SDK/历史支持库行为。
7. `正则常量` 为数据类型枚举成员而非全局库常量，是否符合易语言显示/引用约定需在 IDE 中观察。
8. 空的 `DllMain`、通知处理和 `ReleaseString` 是否需要宿主特定清理动作目前没有测试证据。

## 13. 证据路径索引

- 接口总清单与符号命名：`deelxregex_cmd_typedef.h:3-57`
- 命令实现骨架：`deelxregex_cmdDef.cpp:1-389`
- 参数/命令元数据：`deelxregex_cmdInfo.cpp:1-104`
- 数据类型及方法索引：`deelxregex_dtType.cpp:1-88`
- DLL 库描述、导出入口、宿主通知：`deelxregex_dllMain.cpp:1-180`
- 常量表：`deelxregex_const.cpp:1-18`
- 统一头与 44 个函数声明生成：`include_deelxregex_header.h:1-26`
- 易语言 ABI：`elib/lib2.h:1-1604`、`elib/mtypes.h:1-176`
- 宿主内存/通知/数组辅助：`elib/fnshare.h:1-380`、`elib/fnshare.cpp:1-71`
- DLL 导出：`Source_deelxregex.def:1-4`
- 构建拓扑：`deelxregex.sln:1-40`、`deelxregex.vcxproj:1-202`、`deelxregex_static/deelxregex_static.vcxproj:1-167`
- Git 版本基线：`.git/config`、`.git/HEAD`、`.git/shallow`、Git 提交 `bb27061c1e6482244ae64e1a8eaa5baaf836fe42`

## 14. 首轮归档边界

当前核对已将当前源码、工程、接口、依赖边界、测试缺口、Git 远程和未确认项收口到本文件。仓库未发现 `README` 或 `细探-*.md`，因此没有可吸收的旧细探文档；未删除任何文件。后续深挖只应在本文件基础上补充源码证据、Windows 构建验证、上游历史或引擎来源，不应把当前空实现包装成已完成的正则库。
