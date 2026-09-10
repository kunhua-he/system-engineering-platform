# regex 支持库架构档案

> 首轮全量架构建档。本文是当前仓库的唯一架构事实源；后续细探应直接更新本文件，不另建平行架构摘要。
>
> **证据口径**：凡写“已实现”，必须能在当前源码中找到可执行代码；仅有命令表、类型表、函数声明或注释的内容标记为“仅声明/已登记”；无法由当前仓库确认的运行时行为标记为“未验证”。本仓库没有 README、测试目录、例程或构建产物，因此不能把命令说明当成正则引擎实现证据。

## 1. 项目定位与结论

`regex` 是面向易语言的 Windows 正则表达式支持库工程，目标形态是向易语言 IDE/运行时注册“正则表达式”和“搜索结果”两种自定义数据类型，并登记匹配、创建、搜索、替换等对象命令。工程同时提供：

- `regex`：Visual C++ 动态库项目，Win32 配置明确将目标后缀设为 `.fne`；
- `regex_static`：复用同一批源码的静态库项目，通过 `__E_STATIC_LIB` 预处理分支适配静态编译；
- `elib/`：易语言支持库 ABI、运行时数据类型、通知机制和 IDE 接口的配套头文件/实现。

**首轮结论**：当前提交主要是支持库模板/接口登记骨架。命令元数据、参数元数据、对象类型元数据、DLL 入口和通知函数已登记；`regex_cmdDef.cpp` 中 17 个命令函数均只有参数读取或空函数体，没有看到正则表达式编译、匹配、搜索结果构造、替换或资源释放的实际算法。因此“正则表达式支持库的接口面已定义”可以确认；“正则功能已经可运行”不能由当前源码确认，且按当前命令实现代码判断不成立。

**后续底座结论**：对解析/编译/匹配路径、缓存、并发、错误、超时和底层库边界复核后，结论没有被推翻，且可以进一步收紧：仓库没有正则解析器、编译器、执行器或底层 regex 库的调用边界；也没有缓存、锁、超时预算、错误码映射或取消协议。现有代码只提供易语言支持库 ABI 的注册壳和参数读取样板。后文把“源码事实”和“实现底座必须补齐的设计约束”分开，避免把接口注释误认成引擎能力。

## 2. 中文流程图

### 2.1 动态支持库装载与调用流程

```text
易语言 IDE / 编译运行时
        │ LoadLibrary + 查找固定导出 GetNewInf
        ▼
regex_dllMain.cpp
        │ 返回静态 LIB_INFO g_LibInfo_regex_global_var
        │ 包含 GUID、版本、命令表、类型表、命令函数指针表、通知入口
        ├──────────────────────────────┐
        ▼                              ▼
读取 g_DataType / g_cmdInfo       保存命令函数地址
        │                              │
        ▼                              ▼
建立“正则表达式”“搜索结果”类型   调用 regex_*_N_regex
                                       │
                                       ▼
                             regex_cmdDef.cpp 参数读取骨架
                                       │
                                       ├─ 当前源码未见正则引擎对象
                                       ├─ 当前源码未见结果对象填充
                                       └─ 当前源码未见 pRetData 写回

系统通知方向：
易语言运行时 ──NL_SYS_NOTIFY_FUNCTION──► regex_ProcessNotifyLib_regex
                                             │
                                             ▼
                                      elib/fnshare.cpp
                                             │ 保存 PFN_NOTIFY_SYS
                                             └─ 后续 NotifySys 转发给运行时
```

### 2.2 静态库命名与复用流程

```text
regex_static 工程
        │ 定义 __E_STATIC_LIB（部分配置另含 __E_FNENAME=regex）
        ▼
复用 regex_cmdDef.cpp / regex_cmdInfo.cpp / regex_const.cpp
      / regex_dllMain.cpp / regex_dtType.cpp / elib/fnshare.cpp
        │
        ├─ 命令函数名通过 REGEX_NAME / __E_FNENAME 拼接
        ├─ 动态 LIB_INFO、DllMain、命令信息导出分支被排除或切换
        └─ 静态编译所需命令名数组由 regex_dllMain.cpp 的分支提供
```

### 2.3 目标业务调用意图（声明层，不是实现证据）

```text
正则表达式.创建(表达式文本, 是否区分大小写)
        │
        ▼
正则表达式对象（声明的 this + MultiLine 成员）
        │
        ├─ .匹配(文本) ───────────────► 逻辑值
        ├─ .搜索(文本, 起始位置, 搜索长度) ► 搜索结果
        │                                  ├─ .取匹配文本(原文本, 起始位置引用)
        │                                  └─ .取子匹配文本(原文本, 索引, 起始位置引用)
        ├─ .替换(文本, 格式, 起始位置, 长度, 保留不匹配, 全部替换) ► 文本
        ├─ .搜索全部(文本) ───────────► 搜索结果一维数组
        ├─ .取文本() ─────────────────► 文本
        ├─ .取子表达式个数() ─────────► 整数
        └─ .是否为空() ───────────────► 逻辑值

说明：以上是 regex_cmd_typedef.h 的命令契约和注释所表达的调用意图；
      当前 regex_cmdDef.cpp 没有实现上述业务链，属于“仅声明/未验证”。
```

## 3. 真实目录与分层

当前 Git 提交共 23 个受版本控制文件，目录结构如下（不计 `.git/`）：

```text
regex/
├── ARCHITECTURE.md                 本架构档案（本次新增）
├── regex.sln                       VS 解决方案，含动态/静态两个项目
├── regex.vcxproj                   动态库项目
├── regex.vcxproj.filters           动态项目筛选器
├── regex.vcxproj.user              空用户属性组
├── regex_cmdDef.cpp                命令执行函数骨架（17 个命令）
├── regex_cmdInfo.cpp               命令参数信息与命令信息数组
├── regex_cmd_typedef.h             命令统一登记宏 REGEX_DEF
├── regex_const.cpp                 常量登记数组，当前为 0 个常量
├── regex_dllMain.cpp               DllMain、LIB_INFO、GetNewInf、通知入口
├── regex_dtType.cpp                两个自定义数据类型及成员/方法索引
├── include_regex_header.h          统一包含入口和命令声明
├── Source_regex.def                DLL 导出 GetNewInf
├── elib/
│   ├── fnshare.cpp                 NotifySys/ProcessNotifyLib 状态转发实现
│   ├── fnshare.h                   内存、数组、通知等支持库辅助函数
│   ├── krnllib.h                   系统核心库常量与版本标识
│   ├── lang.h                      GBK 编译语言标识
│   ├── lib2.h                      易语言支持库 ABI、数据类型、命令、通知结构
│   ├── mtypes.h                    基础类型兼容定义
│   ├── PublicIDEFunctions.h        IDE 公共功能号及参数结构
│   └── untshare.h                  通用组件/属性辅助骨架
└── regex_static/
    ├── regex_static.vcxproj        静态库项目，复用根目录源码
    ├── regex_static.vcxproj.filters 静态项目筛选器
    └── regex_static.vcxproj.user   空用户属性组
```

### 3.1 分层职责

| 层 | 主要文件 | 当前职责与状态 |
|---|---|---|
| 构建/封装层 | `regex.sln`、`regex.vcxproj`、`regex_static/regex_static.vcxproj` | 定义动态库/静态库、Win32/x64、Debug/Release；已实现为工程配置 |
| 统一头入口 | `include_regex_header.h` | 组合 `elib`、命令宏并声明命令函数；已实现为编译期接口 |
| 命令契约层 | `regex_cmd_typedef.h`、`regex_cmdInfo.cpp` | 通过 X-macro 登记 17 个命令及 19 项参数槽位；已登记，非业务实现 |
| 类型元数据层 | `regex_dtType.cpp` | 登记 `正则表达式`、`搜索结果` 两种类型、方法索引和成员；已登记，非对象存储实现 |
| 命令执行层 | `regex_cmdDef.cpp` | 暴露命令函数符号并读取参数；业务体均空/未写回；仅声明/骨架 |
| 库装载层 | `regex_dllMain.cpp`、`Source_regex.def` | 返回 `LIB_INFO`，导出 `GetNewInf`，处理运行时通知；入口/元数据已实现 |
| ABI/运行时适配层 | `elib/lib2.h`、`mtypes.h`、`lang.h`、`krnllib.h` | 提供易语言数据表示和通知协议；外部运行时能力，非本库正则算法 |
| 辅助层 | `elib/fnshare.*`、`untshare.h`、`PublicIDEFunctions.h` | 内存、数组、通知和 IDE 常量辅助；部分为通用模板，未被正则命令业务使用 |

## 4. 核心模块职责与调用关系

### 4.1 `regex_cmd_typedef.h`：单一命令登记源

`REGEX_DEF(_MAKE)` 以同一份 17 行宏清单生成不同表/声明：

- 命令索引 `0` 至 `16`；
- 中文名、英文名、说明、Windows 支持标志；
- 返回数据类型和对象命令标志；
- 参数数量及 `g_argumentInfo_regex_global_var` 的起始位置；
- 构造/析构/复制构造等隐藏方法。

`REGEX_NAME` 将命令名拼成类似 `regex_Match_0_regex` 的符号，保证声明、实现、函数指针和静态命令名使用同一命名规则。证据：`regex_cmd_typedef.h:3-29`。

### 4.2 `regex_cmdInfo.cpp`：编辑器可见的参数/命令描述

`g_argumentInfo_regex_global_var` 共 19 项参数描述，覆盖：文本、整数、逻辑值、复合对象、引用输出位置和默认值标志。`g_cmdInfo_regex_global_var` 由 `REGEX_DEF(REGEX_DEF_CMDINFO)` 生成，并记录命令数量。动态库分支受 `#if !defined(__E_STATIC_LIB)` 保护；静态库不保留该动态编辑信息数组。证据：`regex_cmdInfo.cpp:3-64`。

### 4.3 `regex_dtType.cpp`：对象方法索引和对象成员元数据

动态库分支登记两个类型：

1. `正则表达式` / `regex`：方法索引 `[1,2,3,4,5,6,13,0,7,15,16]`，成员有隐藏的 `this` 整数槽和 `多行模式` / `MultiLine` 逻辑成员，默认值为真；
2. `搜索结果` / `SearchResult`：方法索引 `[8,9,10,11,12,14]`，仅有隐藏的 `this` 整数槽。

方法索引中的 `0` 对应“匹配”，其余索引对应 `REGEX_DEF` 的方法；这说明类型表承担易语言对象成员的排列/可见性登记，但没有看到对象实例结构、正则编译对象或搜索结果持有的数据定义。证据：`regex_dtType.cpp:3-57`。

### 4.4 `regex_cmdDef.cpp`：命令执行骨架

文件定义了 `regex_Match_0_regex` 至 `regex_SearchAll_16_regex` 共 17 个 `PFN_EXECUTE_CMD` 形态函数。当前实际行为：

- `匹配`、`创建`、`搜索`、`取匹配文本`、`取子匹配文本`、`复制构造函数`、`替换`、`搜索全部`仅从 `pArgInf` 读取局部变量；
- 构造、析构、是否为空、取文本、取子表达式个数等函数体为空；
- 没有一个函数向 `pRetData` 写入返回类型/返回值；
- 没有对象状态释放、文本复制、数组创建或错误处理代码。

证据：`regex_cmdDef.cpp:1-158`。因此不能把命令注释中的匹配/替换逻辑写成当前已实现能力。

### 4.5 `regex_dllMain.cpp`：支持库注册和通知边界

动态分支包含空的 `DllMain` 生命周期处理，并构造 `g_LibInfo_regex_global_var`：

- 库格式号 `LIB_FORMAT_VER`；
- GUID `684944CB04624eb7BD5412A519421D34`；
- 支持库版本 `2.0.0`；
- 要求易语言系统 `3.8`、核心支持库 `3.7`；
- 名称“正则表达式支持库”；GBK 语言；操作系统 `OS_ALL`；
- 2 个自定义数据类型；17 个命令；命令信息和函数指针表；
- 无 AddIn、SuperTemplate、常量和依赖文件列表；
- `m_pfnNotify` 指向 `regex_ProcessNotifyLib_regex`。

`GetNewInf()` 返回 `LIB_INFO` 地址。通知函数处理命令函数名、通知函数名、依赖库名查询，并在 `NL_SYS_NOTIFY_FUNCTION` 时把通知转发到 `ProcessNotifyLib`；其他多数通知分支为空。证据：`regex_dllMain.cpp:5-100`、`regex_dllMain.cpp:101-180`。

### 4.6 `elib/fnshare.cpp`：运行时通知转发

文件维护两个静态通知函数指针和一个调试版本值：

- `NotifySys`：若已收到运行时通知函数，则调用它，否则返回 0；
- `ProcessNotifyLib`：在 `NL_SYS_NOTIFY_FUNCTION` 保存系统通知指针，并调用 `NRS_GET_PRG_TYPE` 初始化调试/运行版本；之后把通知转发给用户回调；
- `SetUserSysNotify`：设置用户回调并返回 `ProcessNotifyLib`。

证据：`elib/fnshare.cpp:3-71`。该层是支持库 ABI 通道，不是 regex 算法层。

## 5. 对外接口与契约

### 5.1 DLL/静态库入口

| 接口 | 证据 | 状态 |
|---|---|---|
| `GetNewInf()` | `regex_dllMain.cpp:89-92`；`Source_regex.def:1-4` 导出 | 动态库入口已实现 |
| `regex_ProcessNotifyLib_regex(INT,DWORD,DWORD)` | `regex_dllMain.cpp:101-180` | 通知入口已实现，但多数事件无业务动作 |
| `PFN_EXECUTE_CMD(PMDATA_INF,INT,PMDATA_INF)` | `elib/lib2.h:1234-1239` | ABI 类型已声明 |
| `regex_*_N_regex` 17 个命令符号 | `include_regex_header.h:22-24`、`regex_cmdDef.cpp:5-156` | 符号和声明存在，业务实现未完成 |

### 5.2 命令目录（登记契约）

以下名称、返回类型、参数来自 `regex_cmd_typedef.h`，不等于已运行验证：

| 索引 | 对象/命令 | 返回值 | 参数摘要 | 当前状态 |
|---:|---|---|---|---|
| 0 | `正则表达式.匹配` / `Match` | `SDT_BOOL` | 文本 | 仅参数读取 |
| 1 | 隐藏构造函数 | `_SDT_NULL` | 无 | 空函数体 |
| 2 | 隐藏析构函数 | `_SDT_NULL` | 无 | 空函数体 |
| 3 | `正则表达式.创建` / `Create` | `SDT_BOOL` | 表达式文本；可选区分大小写 | 仅参数读取 |
| 4 | `正则表达式.是否为空` / `IsEmpty` | `SDT_BOOL` | 无 | 空函数体 |
| 5 | `正则表达式.取文本` / `GetText` | `SDT_TEXT` | 无 | 空函数体 |
| 6 | `正则表达式.取子表达式个数` / `GetSubExpCount` | `SDT_INT` | 无 | 空函数体 |
| 7 | `正则表达式.搜索` / `Search` | `MAKELONG(0x02,0)` | 文本；起始位置；可选搜索长度 | 仅参数读取 |
| 8 | 隐藏构造函数 | `_SDT_NULL` | 无 | 空函数体 |
| 9 | 隐藏析构函数 | `_SDT_NULL` | 无 | 空函数体 |
| 10 | `搜索结果.是否为空` / `IsEmpty` | `SDT_BOOL` | 无 | 空函数体 |
| 11 | `搜索结果.取匹配文本` / `GetMatchText` | `SDT_TEXT` | 原文本；起始位置引用 | 仅参数读取 |
| 12 | `搜索结果.取子匹配文本` / `GetSubMatchText` | `SDT_TEXT` | 原文本；子表达式索引；起始位置引用 | 仅参数读取 |
| 13 | 正则表达式复制构造函数 | `_SDT_NULL` | `正则表达式`复合对象 | 仅参数读取 |
| 14 | 搜索结果复制构造函数 | `_SDT_NULL` | `搜索结果`复合对象 | 仅参数读取 |
| 15 | `正则表达式.替换` / `Replace` | `SDT_TEXT` | 原文本；替换格式；起始位置；长度；保留不匹配；全部替换 | 仅参数读取 |
| 16 | `正则表达式.搜索全部` / `SearchAll` | 数组形式 `MAKELONG(0x02,0)` | 原文本 | 仅参数读取 |

### 5.3 参数与数据表示

命令执行函数使用 `MDATA_INF` 联合数据：文本从 `m_pText` 读取，整数从 `m_int` 读取，逻辑值从 `m_bool` 读取，引用整数从 `m_pInt` 读取，复合对象从 `m_pCompoundData` 读取。ABI 约定命令返回值应写入 `pRetData`，但当前命令体未写回。证据：`elib/lib2.h:769-823`、`elib/lib2.h:1234-1239`、`regex_cmdDef.cpp:5-156`。

默认参数由元数据层处理：

- `Create` 的 `是否区分大小写`标记为 `AS_DEFAULT_VALUE_IS_EMPTY`，注释声明省略时默认为真；
- `Search` 的起始位置默认值为 `1`，搜索长度为空默认值；
- `Replace` 的起始替换位置默认值为 `1`，替换长度为空默认值，保留不匹配和全部替换默认值为 `1`。

这些是易语言编辑/调用契约，当前执行函数没有消费或验证默认值。证据：`regex_cmdInfo.cpp:18-43`。

## 6. 数据模型、生命周期与持久化

### 6.1 声明的数据模型

| 数据类型 | 元数据成员 | 预期用途 | 实际存储实现 |
|---|---|---|---|
| `正则表达式` / `regex` | 隐藏 `this: SDT_INT`；`多行模式/MultiLine: SDT_BOOL`，默认真 | 保存表达式对象及搜索/替换选项 | 当前仓库未发现对象结构、编译后的 pattern、原文本或析构释放逻辑 |
| `搜索结果` / `SearchResult` | 隐藏 `this: SDT_INT` | 作为 `搜索`返回值，供匹配文本和子匹配查询 | 当前仓库未发现匹配区间、捕获组、表达式关联或原文本引用存储逻辑 |
| `搜索全部`返回值 | 一维 `SearchResult` 数组契约 | 批量返回每次搜索结果 | 当前仓库未发现数组分配、成员构造和旧数组销毁代码 |

### 6.2 生命周期（契约意图与事实分开）

```text
创建对象
  └─ 声明层：调用隐藏构造函数（函数体为空）

创建/重建正则表达式
  └─ 声明层：传入表达式文本和大小写选项
  └─ 实现事实：regex_Create_3_regex 只读取参数，不创建对象

搜索
  └─ 声明层：返回 SearchResult
  └─ 实现事实：regex_Search_7_regex 只读取文本/位置/长度

读取匹配/子匹配
  └─ 声明层：从调用方再次传入原文本，并写回起始位置引用
  └─ 实现事实：函数未读取结果状态，也未写回返回文本/位置

销毁/复制
  └─ 声明层：由隐藏析构/复制构造方法处理
  └─ 实现事实：对应函数为空或只读取源复合对象
```

当前没有文件、数据库、注册表或其他持久化层；所有可能的对象状态应当是易语言运行时复合数据/内存状态，但具体布局未实现、未验证。

## 7. 依赖与构建边界

### 7.1 工程配置

- Visual Studio solution format 12.00，`VisualStudioVersion=17.3.32901.215`；证据：`regex.sln:1-7`。
- 两个项目均配置 `Debug/Release × Win32/x64`；证据：`regex.sln:10-32`、两份 `.vcxproj:3-19`。
- 动态项目 `regex.vcxproj`：`ConfigurationType=DynamicLibrary`，`PlatformToolset=v141`，Windows SDK `10.0.15063.0`，Unicode，Win32 配置目标后缀 `.fne`；证据：`regex.vcxproj:43-75`、`regex.vcxproj:95-105`。
- 静态项目 `regex_static/regex_static.vcxproj`：`ConfigurationType=StaticLibrary`，`PlatformToolset=v141`；Win32 Debug/Release 定义 `__E_STATIC_LIB;__E_FNENAME=regex`，x64 配置只显示 `_DEBUG/_LIB` 或 `NDEBUG/_LIB`，没有显式列出 `__E_STATIC_LIB` 和 `__E_FNENAME=regex`；证据：`regex_static/regex_static.vcxproj:40-73`、`:92-163`。这项配置差异是构建时应复核的风险，不在当前核对修复。
- 动态 Win32 Debug/Release 使用 `Source_regex.def`；x64 链接配置未显式指定该 `.def`，因此 x64 导出行为不能仅凭当前工程断言与 Win32 一致；证据：`regex.vcxproj:109-157`、`:159-198`。
- 源码文件均通过项目直接编译，未发现第三方包管理文件、CMake、Makefile、NuGet、源码内正则库或外部 regex 引擎引用。

### 7.2 头文件依赖边界

```text
regex_cmdDef.cpp / regex_cmdInfo.cpp / regex_const.cpp
regex_dllMain.cpp / regex_dtType.cpp
        │
        ▼
include_regex_header.h
        ├─ elib/lib2.h       易语言 ABI、MDATA_INF、LIB_INFO、通知号
        ├─ elib/lang.h       GBK 语言版本
        ├─ elib/krnllib.h    核心库 GUID/版本和常量
        └─ regex_cmd_typedef.h 命令名与统一登记宏

regex_dllMain.cpp / fnshare.cpp
        └─ elib/fnshare.h → elib/lib2.h
```

`elib/lib2.h` 引入 Windows 头文件、`stdio.h`、`math.h` 和 `assert.h`，并提供 Win32 类型、易语言基本数据类型编码、数组/复合数据指针和系统通知号。证据：`elib/lib2.h:53-67`、`:149-243`、`:769-823`、`:1019-1179`。

## 8. 测试、验证与当前可执行性

### 8.1 仓库内测试现状

- 未发现 `test/`、`tests/`、`spec/`、例程目录或测试工程；
- 未发现 CI 配置、构建脚本或发布脚本；
- `regex.vcxproj.user` 和 `regex_static/regex_static.vcxproj.user` 仅包含空的 `PropertyGroup`；
- 当前 Git 提交只有一次“初始化仓库”，没有测试提交或实现迭代证据。

因此：**测试存在：否；测试已通过：未验证；运行时功能验证：未执行/当前源码不足以证明可运行。**

### 8.2 当前核对已做的静态验证

当前核对仅进行人工源码、工程、Git 读取和静态盘点，没有安装依赖、没有启动服务、没有修改源码、没有执行 Windows/Visual Studio 构建。已核对：

1. `REGEX_DEF` 的 17 个命令索引与 `regex_cmdDef.cpp` 中 17 个函数名对应；
2. 两个数据类型的方法索引与命令索引表对应；
3. `LIB_INFO` 的命令数、类型数、函数指针表和 `GetNewInf`/`.def` 导出关系；
4. 命令实现函数是否写入 `pRetData`：当前未发现；
5. 当前仓库文件清单、Git 分支/提交/远程和工作树基线。

### 8.3 需要后续验证的最小闭环

在具备 Windows + Visual Studio v141 + 易语言运行时后，至少应验证：

```text
动态 Win32 编译
  → 生成可被易语言识别的 regex.fne
  → LoadLibrary/GetNewInf
  → 检查 2 类型、17 命令、GUID/版本
  → 创建/销毁正则表达式对象
  → 匹配/搜索/子匹配/替换/搜索全部
  → 检查文本、数组和引用参数的内存释放

静态 Win32/x64 编译
  → 检查 __E_STATIC_LIB 与 __E_FNENAME 分支
  → 检查命令名数组和通知函数名
  → 检查 x64 配置是否仍定义必要宏并能链接
```

这些是后续验证项，不是当前已完成能力。

## 9. 风险、缺口与后续复核点

### 阻断级缺口（针对“可运行正则支持库”结论）

1. **命令业务实现缺失**：`regex_cmdDef.cpp` 的 17 个函数没有正则表达式算法、状态管理、结果填充或返回值写回。证据：`regex_cmdDef.cpp:5-158`。
2. **对象数据布局缺失**：类型表只有 `this`/`MultiLine` 元数据，没有对应的 C++ 复合对象结构和构造/析构代码。证据：`regex_dtType.cpp:19-57`、`regex_cmdDef.cpp:11-130`。
3. **没有正则引擎依赖或实现**：源码中未发现第三方 regex 引擎包含、编译器正则 API 调用或自研解析器。当前只能确认接口登记。
4. **没有测试证据**：无测试目录、构建脚本和 CI，无法证明 ABI、内存、数组、边界位置或返回类型正确。

### 重要风险

1. 动态项目 x64 配置没有显式 `TargetExt=.fne`，也未显式设置 `ModuleDefinitionFile=Source_regex.def`；Win32 与 x64 产物/导出契约可能不同。
2. 静态项目 x64 配置没有像 Win32 配置那样显式设置 `__E_STATIC_LIB` 与 `__E_FNENAME=regex`；需要在 Windows 构建环境中确认是否由其他属性继承，否则可能导致命名宏或动态/静态分支错误。
3. `regex_cmdDef.cpp` 使用 `pArgInf[1]` 作为第一个参数，而 ABI 注释描述 `pArgInf` 数目等同于 `nArgCount`；需要结合易语言支持库调用约定确认参数数组是否有意从下标 1 开始。当前仅凭本仓库无法验证。
4. `elib/fnshare.h` 的 `ealloc/efree`、数组辅助函数依赖运行时通知和 Win32 指针/整数约定；64 位构建的 `DWORD`、句柄、指针转换边界需要专门验证。
5. `regex_dtType.cpp` 的 `MultiLine` 默认值为真，但命令契约只显式登记 `是否区分大小写`，二者如何共同影响实际引擎未实现。
6. 注释称 `搜索结果`不保存被搜索文本，读取方法要求调用方再次传入原文本；若未来实现，必须明确结果的有效期、原文本一致性、索引单位和失败时起始位置行为。

### 建议的后续深挖顺序

1. 先确认上游是否存在后续提交/分支包含真正的正则引擎实现；当前本地仓库是浅历史，仅有初始化提交。
2. 在 Windows 环境逐项确认 Win32/x64 动态导出和静态宏配置，不修改本研究归档源码。
3. 定义并实现对象内存布局、异常/失败返回约定、数组分配释放和复制/析构语义。
4. 对 17 个命令建立黑盒契约测试，重点覆盖空对象、非法表达式、边界位置、捕获组、零长度匹配、全量替换、重复搜索和多行模式。
5. 补充 ABI/内存所有权测试，确认 `pRetData`、`m_pText`、`m_pCompoundData`、数组数据和引用参数在易语言运行时中的真实约定。

## 10. Git 基线与证据索引

### 10.1 Git 基线（当前核对读取时）

- 根目录：`~/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/regex`
- 当前分支：`master`
- 当前提交：`502a84b1f5b7136eeebe3bb25a6eb899ef35fa0e`
- 提交时间：`2022-12-19T16:57:01+08:00`
- 提交主题：`初始化仓库`
- 远程：`https://gitee.com/JYtechnology/regex.git`
- 本地 `master` 与 `origin/master` 指向同一提交；读取时工作树无已跟踪文件修改。
- 历史为浅克隆/单个 grafted 提交，不能据此断言上游完整历史只有一次提交。

本次允许的变更范围只有目标根目录 `ARCHITECTURE.md`；未修改源码、工程、依赖、测试、配置或 Git 元数据，未删除任何旧细探文件（现场未发现 `细探-*.md`）。

### 10.2 关键证据路径

| 主题 | 文件与行 |
|---|---|
| 命令统一清单 | `regex_cmd_typedef.h:3-29` |
| 命令函数骨架 | `regex_cmdDef.cpp:1-158` |
| 参数表与命令表 | `regex_cmdInfo.cpp:3-64` |
| 数据类型/成员/方法索引 | `regex_dtType.cpp:3-57` |
| DLL 入口与库信息 | `regex_dllMain.cpp:5-100` |
| 系统通知入口 | `regex_dllMain.cpp:101-180` |
| DLL 导出 | `Source_regex.def:1-4` |
| 统一包含与函数声明 | `include_regex_header.h:1-26` |
| 支持库 ABI 与 `MDATA_INF` | `elib/lib2.h:149-243`、`elib/lib2.h:769-823` |
| 命令/通知 ABI | `elib/lib2.h:282-364`、`elib/lib2.h:1149-1239` |
| `LIB_INFO` ABI | `elib/lib2.h:1246-1318` |
| 通知/内存转发 | `elib/fnshare.cpp:3-71`、`elib/fnshare.h:20-170` |
| 动态构建配置 | `regex.vcxproj:43-198` |
| 静态构建配置 | `regex_static/regex_static.vcxproj:40-163` |
| 解决方案平台 | `regex.sln:1-40` |
| 项目文件归类 | `regex.vcxproj.filters:1-74`、`regex_static/regex_static.vcxproj.filters:1-66` |

## 11. 状态标签汇总

| 能力 | 状态 |
|---|---|
| Visual Studio 动态/静态工程文件 | 已实现/已声明（仅表示工程配置存在，未在本机执行构建） |
| `GetNewInf` 导出与 `LIB_INFO` 注册 | 已实现（静态源码路径证据；未运行加载验证） |
| 17 个命令的名称、参数、返回类型登记 | 已实现为元数据 |
| 两个自定义类型及成员登记 | 已实现为元数据 |
| `NotifySys`/`ProcessNotifyLib` 通知桥 | 已实现部分通用桥接；未验证运行时行为 |
| 正则表达式编译/匹配/搜索/替换算法 | 未实现于当前命令函数，未验证 |
| 正则对象和搜索结果数据结构 | 仅声明/元数据，无当前源码实现 |
| 数组返回、文本返回、引用位置写回、内存释放 | 未实现/未验证 |
| 单元测试、集成测试、CI | 未发现 |
| Windows 构建与易语言运行时兼容性 | 未验证 |

## 12. 后续底座映射：解析、执行与运行治理

本节是当前核对新增的专项映射。**“当前事实”只接受可在本仓库源码中定位的代码；“底座要求”是后续实现正则能力时的边界建议，不代表当前仓库已经具备。**

### 12.1 解析与编译链：当前没有实现节点

当前源码中没有以下任一节点：

| 预期节点 | 应承担的职责 | 当前证据 | 当前状态 |
|---|---|---|---|
| 语法解析器 | 将表达式文本解析为 AST/指令或引擎可接受的形式 | 全仓库未发现扫描器、递归下降、词法 token、AST 类型 | 缺失 |
| 编译器/编译入口 | 校验语法、解析捕获组、生成可执行 pattern | `regex_Create_3_regex` 只读取 `m_pText` 与 `m_bool`，不调用任何编译 API | 缺失 |
| 编译产物 | 保存已编译 pattern、选项、子表达式计数 | 类型元数据只有 `this` 和 `MultiLine`；没有 C++ 对象结构或句柄定义 | 缺失 |
| 执行器 | 在文本和起始/长度范围内执行匹配并生成区间 | `Match`/`Search`/`SearchAll` 函数没有匹配调用，也不写 `pRetData` | 缺失 |
| 替换展开器 | 解析替换格式中的 `$1` 等捕获引用并拼接结果 | `Replace` 仅读取六个参数 | 缺失 |

因此，命令注释中提到的括号捕获、`^`/`$` 多行语义、搜索范围和替换格式只是产品契约草稿。当前代码没有定义：转义规则、字符编码、贪婪/懒惰量词、反向引用、非法表达式诊断、未参与匹配的捕获组以及零长度匹配的推进策略。后续实现必须先选定底层引擎或自研语法子集，再冻结这些语义，不能从注释反推兼容某个具体 regex 方言。

### 12.2 缓存：不存在，且不应把对象状态误称为缓存

全仓库没有 pattern cache、LRU、哈希键、缓存容量、命中统计或缓存失效代码。`正则表达式` 的 `this` 槽只是易语言复合数据的隐藏成员，并没有证据表明它指向编译结果；`正则表达式.创建` 的说明“原有数据被释放”也只是命令说明，当前析构和创建函数都没有释放/替换动作。

后续若增加缓存，应把它限定为**编译产物缓存**而不是跨对象共享可变执行状态：

1. 缓存键至少包含表达式字节序列、编码/语言模式、大小写选项、`MultiLine` 及底层引擎版本；不能只用表达式文本。
2. 缓存值应为不可变、可并发读取的编译产物；匹配工作区、捕获结果和超时状态必须是每次调用或每线程独立的。
3. 必须有明确的容量、淘汰、引用保持和销毁时机。不能在易语言对象析构时直接释放仍被其他调用使用的共享产物。
4. 当前没有任何缓存实现或证据，故不能声称重复 `Create`、复制构造或多线程调用会复用编译结果。

### 12.3 线程安全：静态通知状态未提供并发保证

`elib/fnshare.cpp` 使用三个进程内静态变量：`s_pfnNotifySys`、`s_pfnuserNotifySys` 和 `s_isDebug`。它们由 `ProcessNotifyLib`、`SetUserSysNotify` 和 `NotifySys` 直接读写，没有互斥量、原子操作、一次性初始化或生命周期引用计数。`regex_dllMain.cpp` 的 `DllMain` 四个分支也没有建立线程/进程级同步或清理逻辑。

这只能证明“当前桥接状态没有声明线程安全”，不能进一步断言一定发生竞态，因为真实调用时序由易语言运行时决定。至少存在以下待验证边界：

- 两次 `NL_SYS_NOTIFY_FUNCTION` 或用户回调替换时，旧函数指针是否仍可能被并发调用；
- `s_isDebug` 的首次初始化是否可能被多个线程同时触发；
- `NL_FREE_LIB_DATA`/卸载期间，正在执行的命令是否还会使用通知函数；
- 若未来把 regex 对象或缓存放入全局容器，读写、析构和 DLL 卸载的锁顺序是什么。

后续实现应优先让编译产物和对象状态局部化，禁止用这些静态通知变量承载 regex 业务状态；若必须共享，需定义初始化、读写、卸载和回调重入协议，并在 Win32/x64 两种 ABI 下验证。

### 12.4 错误模型：命令返回值不足以承载诊断

命令登记只给出 `SDT_BOOL`、`SDT_TEXT`、`SDT_INT` 或 `_SDT_NULL` 返回类型；`regex_cmdDef.cpp` 当前没有向 `pRetData` 写回任何值，也没有 `try/catch`、错误码、错误文本或最后错误状态。`elib/lib2.h` 虽定义了 `NRS_RUNTIME_ERR`、`NR_OK` 和 `NR_ERR`，但 regex 命令没有使用这些机制；通知入口对未知消息返回 `NR_ERR`，这不是正则表达式语法/执行错误通道。

因此至少要区分以下错误类别，而当前均未实现：

| 类别 | 示例 | 不能用什么替代 |
|---|---|---|
| 输入/范围错误 | 空文本指针、负起始位置、长度溢出、捕获组索引越界 | 不能静默当成“未匹配” |
| 编译错误 | 未闭合括号、非法转义、引擎不支持的语法 | 不能只返回 `false` 而丢失位置/说明 |
| 执行资源错误 | 内存不足、结果数组分配失败 | 不能返回半初始化对象 |
| 运行时超时/取消 | 回溯超限或外部取消 | 不能与合法的零匹配混淆 |
| ABI/所有权错误 | `pRetData`、文本、数组或复合对象所有权不满足运行时约定 | 不能让底层异常越过支持库边界 |

后续设计至少需要统一“成功/值/错误码/错误说明/可重试/详细信息”的映射，再适配易语言既有的返回值和 `NRS_RUNTIME_ERR` 通知；具体映射必须以真实运行时 ABI 验证为准。

### 12.5 超时、回溯和取消：当前完全没有执行预算

仓库没有计时器、deadline、指令步数、回溯深度限制、线程中断、取消令牌或 `NRS_DO_EVENTS` 驱动的协作式取消。`Search`、`SearchAll` 和 `Replace` 的参数也没有超时字段；工程没有第三方引擎配置或底层执行选项。因此当前不能声称存在 ReDoS 防护，也不能保证恶意表达式/文本在有限时间内返回。

若未来选择支持可回溯引擎，超时必须在编译/执行契约中明确：

1. 以单次命令调用为预算单位，覆盖 `Match`、`Search`、`SearchAll` 和 `Replace`，而不是只限制外层 API 返回时间。
2. 预算耗尽要产生可识别的超时错误，并保证临时匹配结果、输出文本和数组按所有权规则回收。
3. 不能用强杀共享线程作为常规取消手段；若引擎不能安全中断，应使用受控独立进程/执行单元隔离不可控回溯。
4. 零长度匹配、超大输入和全量替换必须有最大结果数/输出大小边界，避免“有限时间但无限内存”。

这些是底座验收条件，不是现有源码的能力清单。

### 12.6 底层库边界与 ABI 危险面

当前可确认的底层边界只有 Windows/易语言 ABI：源码直接包含 `elib/lib2.h` 和 Windows 类型，项目使用 Visual C++ v141；没有 `std::regex`、Boost、PCRE、RE2、Oniguruma 或其他 regex 头文件/库，也没有依赖文件登记。`LIB_INFO.m_szzDependFiles` 为 `NULL`，`.def` 仅导出 `GetNewInf`。

此外，现有通用 ABI 代码本身暴露出必须由后续实现规避或验证的边界：

- `MDATA_INF` 的文本/复合/数组字段是运行时借用或间接所有权，注释明确要求返回文本通过运行时内存机制处理；正则层不能把 `m_pText` 当成可写缓冲区。
- `fnshare.h` 的 `ealloc`/`efree` 通过通知系统分配和释放，但 `efree` 把指针转换为 `DWORD`；x64 下这可能截断指针，必须在真实 64 位 ABI 中确认，不能直接作为安全的 64 位内存接口。
- `_GetPointerByIndex` 同样把基址转换为 `INT`，复合对象成员访问在 x64 下存在指针宽度风险；当前 regex 类型没有使用它，但未来对象布局若复用必须先修复/隔离。
- `ProcessNotifyLib` 把 `dwParam1` 转为函数指针；这依赖易语言运行时约定，不能跨平台或跨 ABI 泛化。
- `CloneTextData`、`allocArray` 等辅助函数没有被当前 regex 命令调用；未来返回文本/数组必须明确由谁分配、谁释放、失败时如何回滚。

因此“底层 regex 引擎边界”目前是空边界：尚未选型、尚未登记依赖、尚未定义异常/编码/线程/超时适配层。接入第三方引擎时，应把其头文件、编译选项、异常、分配器、线程模型和取消能力封装在独立适配层，禁止让 `regex_cmdDef.cpp` 直接依赖供应商 API。

## 13. 后续验收矩阵与映射落点

| 主题 | 当前事实 | 必须补齐的最小证据 |
|---|---|---|
| 解析/编译 | 无解析器、无编译调用、无编译产物 | 非法语法、捕获组计数、选项和编码的黑盒测试 |
| 匹配/搜索/替换 | 17 个函数为骨架，未写返回值 | 单次/全部、边界位置、零长度、替换引用和数组生命周期测试 |
| 缓存 | 无缓存 | 键完整性、容量淘汰、并发读取、析构竞态测试 |
| 线程安全 | 通知桥静态变量无同步 | 并发初始化、回调替换、卸载和对象复制/销毁测试 |
| 错误 | 无命令错误通道；仅有通用通知常量 | 编译错误、范围错误、内存错误、超时错误的统一映射测试 |
| 超时/资源 | 无 deadline、回溯限制、结果/输出上限 | 恶意回溯、超大文本、超大结果集和取消回收测试 |
| 底层库 | 未接入 regex 引擎；Windows/易语言 ABI 为唯一已见边界 | 依赖登记、异常隔离、编码、分配器、Win32/x64 ABI 构建与加载测试 |

**后续结论**：本仓库可映射出的“底座”目前止于支持库装载和易语言数据 ABI；正则引擎底座尚未落地。后续顺序应是：先冻结引擎方言与错误/超时契约，再定义对象和结果所有权，随后实现编译产物与局部执行状态，最后再引入有界缓存和并发验证。任何只补命令表、类型表或返回值占位而不补上述边界的改动，都不能升级状态标签为“正则功能已实现”。
