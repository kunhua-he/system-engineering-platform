# eexcel2000 架构建档

> 首轮全量架构建档。本文是本项目唯一正式架构文档；后续细探、复核和增量结论只维护本文件。
>
> 研究边界：仅做源码、工程、入口、API、数据模型、依赖、Git 远程和旧细探盘点；未修改源码/配置/依赖，未构建、未运行服务或 Excel。

## 1. 项目定位

`eexcel2000` 是面向易语言（EPL）的 Windows Excel 支持库工程，目标是以易语言支持库 ABI 暴露“EXCEL2000支持库”，服务于 Excel 2000/XP/2003 或以上版本。库元数据在 `eexcel2000_dllMain.cpp:31-87` 声明：库 GUID 为 `F86EC5989E044d42BC98C692C0B54727`，版本 `2.0.8`，要求易语言系统 `3.7`、系统核心支持库 `3.7`，平台标志为 `__OS_WIN`，语言为 `__GBK_LANG_VER`。

源码形态是一个 Visual Studio C++ 支持库模板/骨架：命令目录、命令参数元数据、易语言自定义数据类型/组件元数据、DLL/静态库适配和通知转发框架已具备；Excel 实际操作命令大多没有实现，部分命令函数体仅从 `pArgInf` 取出参数，未见 COM/OLE 调用或返回值写入。

## 2. 总体流程

```text
易语言 IDE/运行时
        │
        │ 加载 .fne；查找导出 GetNewInf
        ▼
Source_eexcel2000.def ───────► eexcel2000_dllMain.cpp::GetNewInf
                                      │
                                      ├─ LIB_INFO
                                      │   ├─ g_DataType_eexcel2000_global_var
                                      │   ├─ g_cmdInfo_eexcel2000_global_var
                                      │   ├─ g_cmdInfo_eexcel2000_global_var_fun
                                      │   └─ eexcel2000_ProcessNotifyLib_eexcel2000
                                      │
                                      ├─ 命令调用
                                      │   └─ eexcel2000_cmdDef.cpp
                                      │       └─ 36 个命令入口（当前多数为空/仅取参）
                                      │
                                      ├─ 自定义类型/组件发现
                                      │   └─ eexcel2000_dtType.cpp
                                      │       ├─ ExcelApp
                                      │       ├─ ExcelWorkbooks
                                      │       └─ ExcelCharts
                                      │
                                      └─ 系统通知
                                          ▼
                              elib/fnshare.cpp::ProcessNotifyLib
                                          │
                                          ├─ 保存 PFN_NOTIFY_SYS
                                          ├─ 查询运行类型 NRS_GET_PRG_TYPE
                                          └─ 可转发用户通知回调

静态库构建路径：
 eexcel2000_static/eexcel2000_static.vcxproj
        └─ 复用同一批 .cpp/.h，定义 __E_STATIC_LIB
```

## 3. 目录与分层地图

仓库当前 Git 跟踪文件数为 23（由 `git ls-files` 现场统计）：

| 层 | 路径 | 职责 |
|---|---|---|
| 解决方案 | `eexcel2000.sln` | VS 17 解决方案；包含动态库和静态库两个项目，Debug/Release × x86/x64 配置。 |
| 动态库工程 | `eexcel2000.vcxproj` | `DynamicLibrary`；Win32 目标扩展为 `.fne`，x64 配置未显式设置该扩展。编译器工具集 `v141`，Windows SDK `10.0.15063.0`。 |
| 静态库工程 | `eexcel2000_static/eexcel2000_static.vcxproj` | `StaticLibrary`；复用上级源码，以 `__E_STATIC_LIB` 和 `__E_FNENAME=eexcel2000` 适配静态编译。 |
| 支持库 ABI/导出 | `include_eexcel2000_header.h`、`Source_eexcel2000.def` | 引入易语言运行库定义；统一声明命令入口；DLL 仅导出 `GetNewInf`。 |
| 命令实现层 | `eexcel2000_cmdDef.cpp` | 36 个带序号、带库名前后缀的 `EEXCEL2000_EXTERN_C` 命令入口。当前为模板/占位实现。 |
| 命令定义与参数元数据 | `eexcel2000_cmd_typedef.h`、`eexcel2000_cmdInfo.cpp` | 用 `EEXCEL2000_DEF` 单一宏表生成命令名、命令元数据、函数指针数组和静态库命名数组；参数表索引 0–28。 |
| 数据类型/组件元数据 | `eexcel2000_dtType.cpp` | 定义 3 个易语言窗口单元/函数提供者、方法索引、属性、事件和组件接口回调。 |
| 库生命周期/通知 | `eexcel2000_dllMain.cpp`、`elib/fnshare.cpp` | `DllMain`、`GetNewInf`、支持库通知入口、系统通知回调保存与转发。 |
| 易语言公共底座 | `elib/lib2.h`、`lang.h`、`krnllib.h`、`mtypes.h`、`untshare.h`、`PublicIDEFunctions.h`、`fnshare.h` | 支持库 ABI 类型、运行时数据类型、窗口单元/属性/事件结构、IDE 接口和公共函数声明。 |
| 常量 | `eexcel2000_const.cpp` | 当前常量数量为 0（数组占位，`g_ConstInfo..._count = 0`）。 |

## 4. 入口、ABI 与调用边界

### 4.1 动态库入口

- `Source_eexcel2000.def:1-4` 仅导出 `GetNewInf`。
- `eexcel2000_dllMain.cpp:7-24` 的 `DllMain` 对四类 DLL 生命周期通知不做实际初始化/清理。
- `eexcel2000_dllMain.cpp:89-92` 的 `GetNewInf()` 返回静态 `g_LibInfo_eexcel2000_global_var`。
- `LIB_INFO` 将命令计数、命令描述、命令函数指针、数据类型、常量和通知函数绑定为易语言可发现的支持库 ABI。

### 4.2 命令符号

`eexcel2000_cmd_typedef.h:3-9` 将命令符号拼接为：

```text
<库名>_<英文名>_<序号>_<库名>
```

例如 `eexcel2000_Create_0_eexcel2000`。同一个 `EEXCEL2000_DEF(_MAKE)` 宏表（`eexcel2000_cmd_typedef.h:12-48`）被多种生成器复用，避免命令顺序在描述、函数数组和静态库名称数组之间漂移。

### 4.3 系统通知

- `eexcel2000_dllMain.cpp:101-177` 实现 `eexcel2000_ProcessNotifyLib_eexcel2000`。
- `NL_GET_CMD_FUNC_NAMES` 返回 `g_cmdNameseexcel2000`；`NL_GET_NOTIFY_LIB_FUNC_NAME` 返回通知函数名；`NL_GET_DEPENDENT_LIBS` 返回空依赖列表 `"\0\0"`。
- `NL_SYS_NOTIFY_FUNCTION` 转入 `elib/fnshare.cpp:24-64` 的 `ProcessNotifyLib`。
- `fnshare.cpp` 保存宿主 `PFN_NOTIFY_SYS`，首次收到系统通知时调用 `NRS_GET_PRG_TYPE` 更新 `s_isDebug`，并在存在时调用用户回调 `s_pfnuserNotifySys`。
- `NL_FREE_LIB_DATA`、卸载、IDE 就绪等通知目前没有项目专属清理或业务处理。

## 5. 命令/API 面

命令总数为 36，均声明于 `eexcel2000_cmd_typedef.h:13-48`，实现入口位于 `eexcel2000_cmdDef.cpp`：

| 对象/主题 | 序号 | 命令范围 | 主要参数/返回类型 |
|---|---:|---|---|
| `Excel程序` | 0–5 | `Create`、`Release`、`GetApp`、`Quit`、`ActivateApp`、`SendKeys` | 创建返回 `SDT_BOOL`；`GetApp` 返回易语言对象类型；`SendKeys` 使用文本键值和可选布尔等待。 |
| `Excel工作簿` | 6–30 | 置程序、释放、运行宏、取 `Workbooks/Workbook/Worksheets/Worksheet/Range`、打开/关闭/保存、打印、表格操作、图片、范围、边框 | 打开/置程序/运行宏等含布尔或对象返回；参数覆盖文件名、打印设置、表格序号、图片位置尺寸、边框样式。 |
| `Excel图表` | 31–35 | `SetSheet`、`Release`、`GetChart`、`SetSeries`、`AddChart` | 设置系列使用系列 ID/名称/数据标签；图表添加与设置系列标记为 `SDT_BOOL`。 |

参数元数据位于 `eexcel2000_cmdInfo.cpp:5-63`，共有索引 `000–028` 的 29 项：文本、布尔、整数、浮点、`_SDT_ALL`、易语言对象/复合数据等。默认值和可选参数通过 `AS_HAS_DEFAULT_VALUE` 表达，例如打印页号默认 `-1`、打印份数默认 `1`、边框样式/粗细/颜色有默认值。

**实现状态核对：**现场按 `eexcel2000_cmdDef.cpp` 的 36 个函数体扫描，函数体中未发现 Excel COM/OLE API 调用。`SendKeys`、`SetExcelApp`、`RunMacro`、`Open`、`BaoCun`、`PrintOut`、`Move`、`AddPicture`、`BorderAround`、`SetSheet`、`SetSeries` 仅出现 `pArgInf` 取参；其余命令函数体为空。当前不能把命令说明当成已实现能力。

## 6. 数据模型与状态

### 6.1 支持库元数据模型

`eexcel2000_dtType.cpp:318-346` 注册 3 个 `LIB_DATA_TYPE_INFO`：

1. `ExcelApp`（中文名 `Excel程序`）：6 个方法、9 个事件、23 个属性；标志包含 `LDT_WIN_UNIT | LDT_IS_FUNCTION_PROVIDER`。
2. `ExcelWorkbooks`（中文名 `Excel工作簿`）：25 个方法、38 个属性；无事件数组。
3. `ExcelCharts`（中文名 `Excel图表`）：5 个方法、21 个属性；无事件数组。

方法索引由 `eexcel2000_dtType.cpp:125-145` 映射到全局命令索引：`ExcelApp=0..5`、`ExcelWorkbooks=6..30`、`ExcelCharts=31..35`。

### 6.2 ExcelApp 属性/事件

`ExcelApp` 的专属属性（`eexcel2000_dtType.cpp:165-179`）包括 `LeftPos`、`TopPos`、`Width`、`Height`、`Title`、`WindowState`、`Display`、`EnableEvents`、只读 `Version`、`ActivePrinter`、`DisplayFullscreen`、`DefaultFontName`、`DefaultFontSize`、`Zoom`、只读/不可初始化 `IsCreate`。事件有 9 个：工作簿打开、激活、取消激活、即将关闭、即将保存、即将打印、建新表格、表格激活、表格取消激活（`eexcel2000_dtType.cpp:299-316`）。

### 6.3 ExcelWorkbooks 属性/范围模型

`ExcelWorkbooks` 属性（`eexcel2000_dtType.cpp:202-231`）覆盖：

- 当前单元格内容和 `SetNumberFormatLocal`；
- `SheetName`、`SheetID`、只读 `SheetsCount`；
- `BackgroundPicture`、默认行列尺寸；
- `RangeFirst`、`RangeLast` 定义当前操作区域；源码说明后续读写/格式化前必须先设置首尾单元格；
- 对齐、缩进、换行、列宽/行高；
- 字体组（粗体、颜色、倾斜、名称、阴影、大小、删除线、上下标、下划线）。

这是**设计时/支持库元数据层面的目标模型**，不是已验证的运行时 Excel 状态模型；对应属性读写回调仍是模板实现。

### 6.4 ExcelCharts 属性模型

`ExcelCharts` 属性（`eexcel2000_dtType.cpp:254-266`）包括图表类型、标题、X/Y 轴标题、图表位置尺寸、按行/列绘制、Y/X 轴首尾范围。`ChartType` 的说明内嵌大量 Excel `XlChartType` 常量值，但未见本项目常量表注册（`eexcel2000_const.cpp` 计数为 0）。

### 6.5 组件回调状态

三个组件都提供 `eexcel2000_GetInterface_*`，可返回创建、属性更新、属性对话框、属性改变、全部属性、单属性、按键询问和通知接收者回调。实际回调存在明显模板状态：

- `eexcel2000_ControlCreate_*` 只返回 `HUNIT hUnit = 0`；
- `PropGetDataAll_*` 返回 0；
- `PropChanged_*` 只有空的 `switch` 模板；
- `PropGetData_*` 只有占位索引分支；
- 组件事件/通知框架已声明，但没有 Excel 对象生命周期或窗口句柄实现。

## 7. 工程、依赖与构建边界

- 工程：Visual Studio 解决方案格式 12.00，VS 17；目标平台 Win32/x64，Debug/Release。
- 编译器：动态库和静态库均主要使用 `v141`；字符集为 Unicode；Win32 动态库 `TargetExt=.fne`。
- Windows：`WindowsTargetPlatformVersion=10.0.15063.0`。
- 运行平台：命令和数据类型均以 `_CMD_OS(__OS_WIN)` / `_DT_OS(__OS_WIN)` 为 Windows 平台约束。
- 本地底座：`elib/*.h` 是随仓库提供的易语言支持库/IDE ABI 头文件，不是通过包管理器拉取的第三方依赖。
- 外部运行时前提：库说明要求机器安装 Excel 2000 或以上版本；源码当前没有证明其已建立 COM/OLE 连接。
- `NL_GET_DEPENDENT_LIBS` 返回空列表；工程 XML 也未配置额外 include/library 目录或第三方静态库。
- 静态库工程复用同一源码，Win32 Debug/Release 显式定义 `__E_STATIC_LIB`、`__E_FNENAME=eexcel2000`；x64 配置未显式继承同样的 `__E_STATIC_LIB`/库名定义，属于需要复核的工程一致性风险。

## 8. 真实调用链

### 8.1 支持库加载

```text
易语言加载 eexcel2000.fne
  -> 导出 GetNewInf()
  -> g_LibInfo_eexcel2000_global_var
  -> 发现 36 个 CMD_INFO、3 个 LIB_DATA_TYPE_INFO
  -> 通过 g_cmdInfo_eexcel2000_global_var_fun 建立命令索引到函数地址映射
```

证据：`Source_eexcel2000.def:1-4`、`eexcel2000_dllMain.cpp:31-92`、`eexcel2000_cmd_typedef.h:12-48`。

### 8.2 命令调用

```text
易语言命令索引 N
  -> g_cmdInfo_eexcel2000_global_var_fun[N]
  -> eexcel2000_<命令>_<N>_eexcel2000(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)
  -> 当前代码最多读取 pArgInf[N] 到局部变量
  -> 未见 Excel COM 调用、对象句柄存储或 pRetData 写回
```

因此当前源码可以证明“命令 ABI 和参数描述存在”，不能证明“Excel 操作链路已完成”。

### 8.3 组件设计器调用

```text
易语言 IDE
  -> g_DataType... 中的 PFN_INTERFACE
  -> eexcel2000_GetInterface_ExcelApp/ExcelWorkbooks/ExcelCharts
  -> ControlCreate_* / Prop*_* / PropNotifyReceiver_*
  -> 当前为通用模板回调，未创建实际 HUNIT 或持久化属性数据
```

## 9. 测试、验证与未执行事项

- 仓库内没有测试目录、测试工程或测试脚本（现场 Git 文件清单未发现相关文件）。
- 未执行 Visual Studio 构建：当前环境为 macOS，且用户明确禁止构建运行。
- 未加载 DLL、未调用 `GetNewInf`、未调用任何命令、未连接 Excel、未验证易语言 IDE 组件回调。
- 已做只读静态核验：文件清单、工程配置、入口/导出、Git 状态与版本、远程 HEAD、命令数量/函数体、参数/数据类型/属性/事件表。

## 10. Git 基线与旧细探

- 本地分支：`master`，工作树在盘点时干净（`git status --short --branch` 为 `master...origin/master`）。
- 本地提交：`bf78ecba42d01b03169bde74de1d65eea4aa00c9`，时间 `2022-12-19T16:05:13+08:00`，提交说明 `初始化仓库`。
- 远程：`origin = https://gitee.com/JYtechnology/eexcel2000.git`。
- 远程 `HEAD` / `refs/heads/master` 现场查询均为 `bf78ecba42d01b03169bde74de1d65eea4aa00c9`，与本地基线一致。
- 项目内未发现 `细探-*.md`、既有 `ARCHITECTURE.md` 或其他旧架构报告；不存在需要吸收/删除的旧细探。
- `codegraph_explore` 已按要求调用，但该项目及其父目录没有 `.codegraph/` 索引，工具明确返回无法查询；本次改用源码文件和工程文件逐项静态读取，未创建索引。

## 11. 风险、未确认项与后续复核点

1. **核心实现缺失风险（高）**：36 个命令入口中多数为空，非空者也仅取参；需要在 Windows + Excel 环境核实是否源码截断、是否依赖未纳入仓库的实现，或项目本身就是支持库骨架。
2. **返回值/状态缺失风险（高）**：命令入口未见 `pRetData` 写回，组件创建返回 `0`，属性序列化/反序列化未实现，实际运行不可据此推断。
3. **COM/OLE 边界未落地（高）**：说明文字描述 `Application`、`Workbook`、`Range`、`Chart` 对象，但源码未出现对象创建、释放、异常处理、线程模型或宿主进程管理。
4. **静态库配置一致性（中）**：Win32 静态库配置定义 `__E_STATIC_LIB`/`__E_FNENAME`，x64 配置没有同等定义；需在 Windows VS 中复核预处理结果。
5. **x64 DLL 导出/扩展名（中）**：动态库 Win32 配置显式引用 `Source_eexcel2000.def` 并设置 `.fne`，x64 配置未显式设置 `TargetExt` 和模块定义文件；需复核 x64 产物是否满足易语言装载契约。
6. **字符编码风险（中）**：C++ 源码主要为 GB18030/GBK 可解码字节，工程字符集为 Unicode；应在 Windows 编译器和易语言支持库加载器中验证中文命令说明与 ABI 文本编码。
7. **事件元数据与实现脱节（中）**：`ExcelApp` 注册 9 个事件，但没有宿主 Excel 事件连接或事件触发实现。
8. **常量缺失（低/中）**：Excel 图表/边框等常量只在文本说明中出现，支持库常量数组为空。

## 12. 首轮结论

`eexcel2000` 当前可确认的是一个完整度较高的易语言支持库**接口描述与工程模板**：ABI 入口、命令单一宏表、29 项参数元数据、3 个自定义数据类型、属性/事件定义、动态/静态库工程和通知框架均已搭好；不能确认其具备可用的 Excel 自动化能力。后续深挖应优先在 Windows 环境确认来源分支/提交是否包含遗漏实现，并逐一补齐 Excel COM 生命周期、命令返回值、组件属性持久化和事件连接；在此之前，任何“支持打开/保存/打印/图表”等能力只能标记为接口意图，不能标记为已实现。

## 证据索引

- 项目工程：`eexcel2000.sln`、`eexcel2000.vcxproj`、`eexcel2000_static/eexcel2000_static.vcxproj`
- 导出/库信息：`Source_eexcel2000.def`、`eexcel2000_dllMain.cpp:31-177`
- 命令表：`eexcel2000_cmd_typedef.h:3-48`、`eexcel2000_cmdDef.cpp`、`eexcel2000_cmdInfo.cpp:5-80`
- 类型/属性/事件：`eexcel2000_dtType.cpp:123-346`、`eexcel2000_dtType.cpp:350-891`
- 公共 ABI：`include_eexcel2000_header.h`、`elib/lib2.h`、`elib/fnshare.h`、`elib/untshare.h`、`elib/PublicIDEFunctions.h`
- 通知实现：`elib/fnshare.cpp:11-71`
- 常量：`eexcel2000_const.cpp`（计数为 0）
