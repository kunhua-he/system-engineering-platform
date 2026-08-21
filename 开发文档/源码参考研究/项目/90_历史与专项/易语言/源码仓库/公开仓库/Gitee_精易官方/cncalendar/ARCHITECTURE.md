# cncalendar 架构建档

> 当前全量建档；本文是项目根唯一架构事实源。源码、工程文件和 Git 仓库均按只读方式检查，未修改源码、未安装依赖、未启动程序、未执行构建。

## 1. 项目定位与当前结论

`cncalendar` 是一个面向易语言的 Windows 农历日期支持库工程，目标是以 `.fne` 动态支持库或静态库的形式向易语言 IDE/运行时注册农历日期命令、枚举类型和两个窗口组件：`农历日期框`（`CnCalendar`）与 `农历月历`（`CnMonthCalendar`）。

当前仓库更接近“支持库接口/元数据骨架”而不是可用的农历算法实现：命令目录、参数、返回类型、组件属性/事件和库加载入口已经生成，但 `cncalendar_cmdDef.cpp` 中命令函数基本只读取参数，没有计算或写回结果；`cncalendar_dtType.cpp` 中组件创建、属性读写和通知回调也保留模板空实现。因此，不能把仓库中的日期范围说明或 API 元数据等同于已验证的运行能力。

## 2. 架构总览

```text
易语言 IDE / 运行时
        │
        │ LoadLibrary + 固定导出 GetNewInf（动态库）
        ▼
cncalendar_dllMain.cpp
  ├─ LIB_INFO：库身份、版本、依赖、类别、命令、数据类型、常量
  ├─ g_cmdInfo...fun：按命令索引映射到执行函数
  ├─ cncalendar_ProcessNotifyLib_cncalendar：系统通知入口
  └─ GetNewInf：返回 LIB_INFO
        │
        ├──────────────► cncalendar_cmdInfo.cpp
        │                 参数表 g_argumentInfo...
        │                 命令描述表 g_cmdInfo...
        │
        ├──────────────► cncalendar_cmdDef.cpp
        │                 0~14 全局日期/农历命令
        │                 30~34 农历日期框方法
        │                 50~52 农历月历方法
        │                 15~29、35~49 隐藏占位命令
        │
        ├──────────────► cncalendar_dtType.cpp
        │                 组件/枚举数据类型
        │                 属性表、事件表、组件接口回调
        │
        └──────────────► cncalendar_const.cpp
                          支持库代号常量

公共 ABI/运行时适配层：elib/*.h + elib/fnshare.cpp
        │
        ├─ MDATA_INF / PMDATA_INF：易语言参数和返回值载体
        ├─ LIB_INFO / LIB_DATA_TYPE_INFO：支持库注册模型
        ├─ PFN_NOTIFY_SYS / PFN_EXECUTE_CMD：通知与命令函数 ABI
        └─ DATE、窗口句柄、属性/事件/接口类型及 Windows 兼容定义

构建变体
  ├─ cncalendar.vcxproj：DynamicLibrary，目标输出扩展名主要为 .fne
  └─ cncalendar_static/cncalendar_static.vcxproj：StaticLibrary，定义 __E_STATIC_LIB
```

## 3. 真实目录与文件职责

当前提交中 Git 记录的项目文件共 23 个；仓库没有 README、`AGENTS.md`、测试目录、示例目录或旧 `既有专项文档` 文件。

```text
cncalendar/
├── cncalendar.sln                         Visual Studio 解决方案；动态库 + 静态库
├── cncalendar.vcxproj                     动态支持库工程
├── cncalendar.vcxproj.filters             动态工程文件分组
├── cncalendar.vcxproj.user                用户工程空配置
├── cncalendar_static/
│   ├── cncalendar_static.vcxproj          静态库工程，引用上级源文件
│   ├── cncalendar_static.vcxproj.filters  静态工程文件分组
│   └── cncalendar_static.vcxproj.user     用户工程空配置
├── Source_cncalendar.def                  动态库模块定义文件，仅导出 GetNewInf
├── include_cncalendar_header.h            聚合 elib、命令类型并声明命令实现
├── cncalendar_cmd_typedef.h               CNCALENDAR_DEF 命令单一宏定义及命名拼接
├── cncalendar_cmdDef.cpp                  命令执行函数骨架
├── cncalendar_cmdInfo.cpp                 参数描述表和 CMD_INFO 表
├── cncalendar_const.cpp                   支持库常量表
├── cncalendar_dtType.cpp                  数据类型、枚举、组件属性/事件/接口骨架
└── elib/
    ├── lib2.h                             易语言支持库 ABI、数据类型和通知定义
    ├── mtypes.h                           Windows/基础类型兼容定义
    ├── lang.h                             GBK/英语/BIG5/SJIS 语言版本常量
    ├── krnllib.h                          系统核心支持库接口头
    ├── PublicIDEFunctions.h               IDE 辅助函数常量
    ├── untshare.h                         组件属性序列化/窗口辅助模板（多处仍为模板空实现）
    ├── fnshare.h                          通知/内存/共享辅助声明
    └── fnshare.cpp                        NotifySys、ProcessNotifyLib、SetUserSysNotify
```

## 4. 启动、注册与通知调用链

### 4.1 动态库入口

1. 易语言加载 `.fne` 后通过固定导出名 `GetNewInf` 获取 `PLIB_INFO`；`Source_cncalendar.def` 当前只声明导出 `GetNewInf`。
2. `GetNewInf()` 返回静态对象 `g_LibInfo_cncalendar_global_var`。
3. `LIB_INFO` 将库格式号、GUID、版本、所需易语言/核心支持库版本、库名、语言、说明、操作系统标志、作者信息、数据类型、命令类别、命令表、命令函数表、通知回调和常量表串起来。
4. `g_cmdInfo_cncalendar_global_var_fun` 由 `CNCALENDAR_DEF(CNCALENDAR_DEF_CMD_PTR)` 展开，保证命令定义宏的索引顺序与函数指针数组顺序一致。
5. 系统通知进入 `cncalendar_ProcessNotifyLib_cncalendar`；`NL_SYS_NOTIFY_FUNCTION` 被转发到 `elib/fnshare.cpp::ProcessNotifyLib`，从而缓存系统通知函数指针并允许公共辅助函数调用宿主。
6. `NL_GET_CMD_FUNC_NAMES`、`NL_GET_NOTIFY_LIB_FUNC_NAME`、`NL_GET_DEPENDENT_LIBS` 仅在非静态库路径返回静态编译所需信息；`NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE` 等当前没有释放或卸载逻辑。

### 4.2 命令执行 ABI

所有命令都采用易语言支持库 ABI：

```text
void 命令实现(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)
```

`pArgInf` 是参数数组，命令函数按元数据约定读取 `m_int`、`m_bool`、`m_date`、`m_pText` 以及对应的指针成员（如 `m_pInt`、`m_pDate`、`m_pBool`、`m_ppText`）。需要写回的引用参数必须通过这些指针更新，返回值必须写入 `pRetData`；当前实现没有完成这些写回/返回动作。

### 4.3 组件交互 ABI

`cncalendar_dtType.cpp` 为两个 `LDT_WIN_UNIT` 数据类型提供 `PFN_GET_INTERFACE` 风格分发函数。`ITF_CREATE_UNIT`、属性更新、属性变化、属性数据读写、按键需求和附加通知接收者等接口号分别映射到组件回调。当前组件创建函数返回 `HUNIT hUnit = 0`，属性数据导出返回 `0`，多数回调只返回模板值，尚未形成可运行的窗口组件生命周期。

## 5. 命令/API 边界

### 5.1 全局命令（索引 0~14）

命令类别为索引 `1`，库中类别字符串为 `0000农历日期处理`。公开的全局命令及声明返回类型如下：

| 索引 | 易语言命令 | C++ 实现名 | 返回类型 | 主要输入/输出 |
|---:|---|---|---|---|
| 0 | 农历转公历 | `FromLunarDate` | `SDT_BOOL` | 农历年月日、闰月；写回公历 `DATE` |
| 1 | 公历转农历 | `ToLunarDate` | `SDT_BOOL` | 公历 `DATE`；写回农历年月日和闰月 |
| 2 | 取农历月总天数 | `GetLunarMonthDays` | `SDT_INT` | 农历年、月、闰月 |
| 3 | 取农历年总天数 | `GetLunarYearDays` | `SDT_INT` | 农历年 |
| 4 | 取农历闰月 | `GetLunarLeapMonth` | `SDT_INT` | 农历年 |
| 5 | 取农历节气 | `GetLunarJieqi` | `SDT_TEXT` | 农历日期；可写回节气序号 |
| 6 | 取年属相 | `GetYearShuxiang` | `SDT_TEXT` | 农历年；可写回属相序号 |
| 7 | 取天干地支 | `GetTianganDizhi` | `SDT_TEXT` | 天干序号、地支序号 |
| 8 | 取六十甲子 | `Get60Jiazi` | `SDT_TEXT` | 1~60 序号 |
| 9 | 取四柱 | `Get4Zhu` | `SDT_BOOL` | 公历日期；写回年/月/日/时柱文本 |
| 10 | 取四柱序号 | `Get4ZhuIndex` | `SDT_BOOL` | 公历日期；写回四柱 1~60 序号 |
| 11 | 取六十甲子纳音 | `Get60JiaziNayin` | `SDT_TEXT` | 六十甲子文本 |
| 12 | 格式化日期 | `FormatDate` | `SDT_TEXT` | 公历日期、可选格式化文本 |
| 13 | 取交节气时刻 | `GetJieqiDatetime` | `SDT_DATE_TIME` | 公历年份、节气序号 |
| 14 | 取属相 | `GetShuxiang` | `SDT_TEXT` | 公历日期；可写回属相序号 |

索引 `15~29` 是生成/兼容用的隐藏命令，占位实现名为 `_bunengshibie_`，状态带 `CT_IS_HIDED`，不应作为公开 API 使用。

### 5.2 `农历日期框` 方法（索引 30~34）

数据类型英文名为 `CnCalendar`，方法索引表为 `30, 34, 31, 32, 33`，对应：

- `置农历日期` / `SetLunarDate`：农历年月日和可选闰月；
- `增减日期` / `IncreaseDate`：默认增减天数为 `1`；
- `打开选择窗口` / `OpenWindow`；
- `关闭选择窗口` / `CloseWindow`；
- `置公历日期` / `SetDate`：公历年月日。

索引 `35~49` 是该组件的隐藏占位命令。

### 5.3 `农历月历` 方法（索引 50~52）

数据类型英文名为 `CnMonthCalendar`，方法为：

- `置农历日期` / `SetLunarDate`；
- `置公历日期` / `SetDate`；
- `增减日期` / `IncreaseDate`。

同名方法通过不同命令索引和宏生成名区分，最终 C++ 符号包含索引，不是普通 C++ 重载。

## 6. 数据模型与元数据

### 6.1 库级元数据

`g_LibInfo_cncalendar_global_var` 声明：

- GUID：`{18C0788E-59AE-4112-B452-6BF0C1B727FB}`；版本 `2.0.1`；
- 要求易语言系统 `3.7`、系统核心支持库 `3.7`；
- 库名：`农历日期支持库`；编码声明：`__GBK_LANG_VER`；
- 目标系统标志：`_LIB_OS(__OS_WIN)`；
- 公开说明声称日期范围主要为 `1902-2047`，并称与万年历核对；该说明来自元数据，当前没有测试或算法证据支持；
- 只有一个命令类别；常量表只有 `支持库代号 = "CnCalendar"`；无额外依赖文件声明。

### 6.2 自定义数据类型

`g_DataType_cncalendar_global_var` 共 11 个槽位：

| 槽位 | 类型 | 英文名 | 结构 |
|---:|---|---|---|
| 0 | 窗口组件 | `CnCalendar` | 20 个方法槽（其中 5 个公开方法和隐藏槽）、5 个事件、19 个属性 |
| 1 | 枚举 | `TianGan` | 天干 10 项，值 1~10 |
| 2 | 枚举 | `DiZhi` | 地支 12 项，值 1~12 |
| 3 | 枚举 | `ShuXiang` | 属相 12 项，值 1~12 |
| 4 | 枚举 | `JieQi` | 节气 24 项，值 1~24 |
| 5~9 | 未命名保留槽 | 无 | 空定义，未形成公开类型 |
| 10 | 窗口组件 | `CnMonthCalendar` | 3 个方法、4 个事件、22 个属性 |

两个组件均包含易语言固定窗口属性（位置、尺寸、标记、可视、禁止、鼠标指针），并定义公历日期、农历年月日、闰月、主视图、格式化文本及只读显示字段。`CnCalendar` 的显示字段包含农历年月日文本、属相、节气、星期、本月/本年天数和最终显示文本；`CnMonthCalendar` 还增加 `是否显示表头`。

### 6.3 组件事件

- `CnCalendar`：`日期被选择`、`日期被悬停`、`选择窗口打开`、`选择窗口关闭`、`日期被改变`。
- `CnMonthCalendar`：`日期被选择`、`日期被悬停`、`日期被改变`、`日期被右击`。
- 事件参数使用 `EVENT_ARG_INFO2`，内容为农历年、月、日、是否闰月；事件返回类型均为 `_SDT_NULL`。

## 7. 关键模块与调用关系

### 7.1 `cncalendar_cmd_typedef.h`

这是 API 的单一宏源。`CNCALENDAR_DEF(_MAKE)` 为每一个索引同时定义中文名、英文名、说明、类别、平台状态、返回类型、参数数量和参数表起点。`CNCALENDAR_NAME` 将 `__E_FNENAME`、英文名和索引拼接为实际符号，避免组件方法同名冲突。`include_cncalendar_header.h` 再用该宏生成所有命令函数前置声明。

### 7.2 `cncalendar_cmdInfo.cpp`

定义 `g_argumentInfo_cncalendar_global_var` 参数元数据，包含参数名、类型、默认值、引用/可选标志；定义 `g_cmdInfo_cncalendar_global_var` 命令描述数组，并计算命令数量。这里是 IDE 展示和运行时参数校验所依赖的契约，不是算法实现。

### 7.3 `cncalendar_cmdDef.cpp`

实现 53 个命令函数的符号入口。可见命令函数会从 `pArgInf` 取出形参，但函数体没有调用农历计算、没有为 `pRetData` 写结果，也没有写回引用参数；隐藏命令为空函数。因此这是当前最主要的实现缺口。

### 7.4 `cncalendar_dtType.cpp`

集中放置组件和枚举的元数据，以及两个组件的 `GetInterface`、创建、属性读写和通知回调。枚举值和属性/事件契约较完整，但组件创建和持久化/实时属性访问仍是模板行为；`TODO 在这里创建组件并返回` 出现于两个组件创建函数。

### 7.5 `elib/fnshare.cpp` 与 `elib/*.h`

`elib` 是随仓库携带的易语言支持库 SDK 适配层，不是第三方包管理依赖。`fnshare.cpp` 保存宿主通知函数指针、判断调试运行版本、转发系统通知和设置用户通知回调。`lib2.h` 定义 `MDATA_INF`、`LIB_INFO`、`LIB_DATA_TYPE_INFO`、`UNIT_PROPERTY`、`EVENT_INFO2`、`PFN_INTERFACE`、`PFN_NOTIFY_SYS`、`PFN_EXECUTE_CMD` 以及 `SDT_*`/`LDT_*`/`ITF_*`/`NL_*` 常量。

## 8. 构建与依赖边界

### 8.1 工程事实

- `cncalendar.sln` 是 Visual Studio 17 方案，同时包含动态库 `cncalendar` 和静态库 `cncalendar_static`。
- 工程配置为 `Debug/Release` × `Win32/x64`；解决方案的 `x86` 映射到项目的 `Win32`。
- `cncalendar.vcxproj` 配置类型为 `DynamicLibrary`，Win32 配置指定 `TargetExt=.fne`，Win32 链接配置引用 `Source_cncalendar.def`。
- `cncalendar_static.vcxproj` 配置类型为 `StaticLibrary`，通过 `..\` 引用同一批源文件，并在 Win32 配置定义 `__E_STATIC_LIB`。
- 目标 Windows SDK 为 `10.0.15063.0`，平台工具集为 `v141`，字符集为 Unicode；公共源码自定义 `mtypes.h` 将部分 Windows 类型映射为兼容类型。
- 源码包括 C++ 标准库/Windows 风格 API 和随库提供的 `elib` 头文件；没有 `package.json`、`requirements.txt`、NuGet/CMake/第三方库清单或外部运行服务。

### 8.2 已发现的工程风险（未执行构建验证）

1. 动态工程的 Win32 配置显式设置 `ModuleDefinitionFile=Source_cncalendar.def`，但 x64 配置未见同项；x64 产物是否导出固定入口 `GetNewInf` 未验证。
2. 动态工程的 x64 配置没有像 Win32 那样定义 `__E_FNENAME=cncalendar`；静态工程的 x64 配置也没有该定义，而 `lib2.h`/`cncalendar_cmd_typedef.h` 依赖 `__E_FNENAME` 生成符号。x64 是否能编译通过未验证。
3. 静态工程的 x64 配置使用 `<PrecompiledHeader>Use</PrecompiledHeader>`，仓库文件清单没有 `pch.h`；是否由宿主工程或环境提供未验证。
4. 项目使用 GBK 文本元数据（`__GBK_LANG_VER`），当前 macOS 只做了按 `gb18030` 解码读取；Windows/易语言实际加载时的编码兼容未验证。

## 9. 测试、验证与发布现状

### 已完成的只读取证

- 核对真实目录、全部工程文件、全部项目源文件和 `elib` 关键 ABI 定义；
- 核对 Git 分支、提交、远程地址、远程跟踪分支和远程 `HEAD`；
- 从命令宏、参数表、数据类型表、属性表和事件表整理 API/数据模型；
- 搜索 `TODO`、空回调和明显零值返回，确认实现骨架状态。

### 未完成/未执行

- 仓库没有自动化测试、测试夹具、示例程序或 CI 配置；
- 未在 macOS 上运行 Visual Studio/MSBuild，不具备该 Windows 构建环境；
- 未执行任何构建、链接、DLL 加载、易语言 IDE 注册或 API 运行验证；
- 未验证日期算法、闰月边界、节气时刻、四柱、属相切换、日期范围或编码兼容；
- `codegraph` 对该目录不可用：目标目录及其上级没有 `.codegraph/` 索引，因此当前取证使用逐文件只读取证替代，没有初始化索引。

## 10. 风险与后续复核点

按优先级排列：

1. **P0 功能缺失**：先实现或接入真正的农历算法，再逐个补齐 0~14 全局命令的返回值和引用参数写回；目前命令调用不会产生可信计算结果。
2. **P0 组件不可运行**：补齐 `CnCalendar`/`CnMonthCalendar` 的真实窗口句柄、日期状态、属性序列化、实时属性读取、事件触发和资源释放；当前创建返回空句柄。
3. **P1 工程矩阵**：修订或验证 x64 的 `__E_FNENAME`、`.def` 导出和预编译头配置，分别完成动态库/静态库的 Win32、x64 Debug/Release 构建矩阵验证。
4. **P1 API 契约测试**：为命令索引、参数类型/引用标志、默认值、失败返回约定、4 个枚举值域、属性/事件数量和方法索引建立自动化契约测试。
5. **P1 日期边界测试**：覆盖元数据声称的 `1902-2047` 范围、节气单独声称的 `1880-2079` 范围、闰月、春节/立春边界、跨年增减和无效日期；必须以实际算法行为裁决说明文字。
6. **P2 资源与 ABI 安全**：确认文本返回值的分配/释放规则、`m_ppText` 写回约束、宿主通知指针生命周期、组件销毁路径和 `NL_FREE_LIB_DATA` 行为。
7. **P2 版本与来源**：当前仓库只有一个 2022-12-19 的初始化提交，远程与本地跟踪到同一提交；后续应复核上游是否已有功能提交，不能把本地初始化骨架当作最终实现。

## 11. Git 版本基线与证据路径

- 项目根：`/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/cncalendar`
- 分支：`master`，工作树在建档前为干净状态；本地 `master`、`origin/master`、`origin/HEAD` 均指向同一提交。
- 提交：`d20d21cd2399760bc32c7c28838d43dfd32651b9`
- 提交时间：`2022-12-19T15:36:44+08:00`
- 远程：`https://gitee.com/JYtechnology/cncalendar.git`
- 提交说明：`初始化仓库`
- 远程只读核对：`git ls-remote origin HEAD refs/heads/master` 返回同一提交；没有执行 fetch/pull。
- 主要证据：`cncalendar_cmd_typedef.h`、`cncalendar_cmdDef.cpp`、`cncalendar_cmdInfo.cpp`、`cncalendar_dtType.cpp`、`cncalendar_dllMain.cpp`、`cncalendar_const.cpp`、`include_cncalendar_header.h`、`cncalendar.vcxproj`、`cncalendar_static/cncalendar_static.vcxproj`、`Source_cncalendar.def`、`elib/lib2.h`、`elib/fnshare.cpp`。
- 既有细探材料：目标根及其子目录未发现 `既有专项文档`，因此没有可吸收的既有细探材料结论；后续只维护本文件。

## 12. 当前取证验收口径

当前取证交付物仅为本文件。文档应满足：中文说明、源码标识符/路径原文保留、包含 `text` 流程图、真实目录/入口/API/数据模型/依赖/测试/版本基线、明确区分“存在于元数据”和“已实现/已验证”，并诚实列出未验证事项。源码和工程文件保持原状。

## 13. 小型仓规模说明与边界

本仓库只有 23 个 Git 跟踪文件，核心由易语言支持库生成器文件组成；没有业务源码目录、运行时资源、示例程序或测试夹具。因此文档不人为扩张到 500 行，以下事实覆盖全部文件：

- `cncalendar_cmdDef.cpp`：命令元数据和处理器占位；需与 `cncalendar_cmdInfo.cpp` 的名称、参数数量逐项对应。
- `cncalendar_cmd_typedef.h`：命令函数指针、参数包装和返回类型声明，是 ABI 的第一入口。
- `cncalendar_dtType.cpp`：自定义数据类型注册；当前只描述类型，不提供日期算法实现。
- `cncalendar_const.cpp`：常量表；为空或仅含占位时，不能推导出运行时常量。
- `cncalendar_dllMain.cpp`：导出入口、库信息、`GetNewInf` 注册和宿主通知挂接。
- `include_cncalendar_header.h`：公共声明聚合，供动态工程与静态工程共享。
- `Source_cncalendar.def`：DLL 导出名边界；必须与 `dllMain` 的导出符号一致。
- `cncalendar.vcxproj`：动态 DLL 的编译单元、预处理宏、链接配置和输出目录。
- `cncalendar_static/cncalendar_static.vcxproj`：静态库配置；与动态工程共享源码但输出形态不同。
- `elib/*`：易语言宿主 ABI 头文件和内存/通知桥接，不是本项目的日期业务实现。

未发现 `tests/`、示例、第三方依赖清单或可执行资源。当前环境为 macOS，无法运行 MSVC、易语言 IDE 或 Windows DLL；因此命令返回值、线程安全、异常回收和跨版本兼容均未验证。任何使用方都应先在目标 Windows 环境确认导出表、宿主装载和空实现行为。
