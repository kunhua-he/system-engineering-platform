# echartbar 架构建档

> 本文是本项目首轮全量架构档案，事实基线为当前工作树与 Git 提交 `4282922aed8711406c3ef7bf50643c4e566c71d9`。源码参考仓库按只读方式研究；本轮只新增本文件，未修改源码、工程配置、依赖或构建产物。

## 1. 项目定位

`echartbar` 是面向易语言 IDE/编译器的 Windows 图表控件支持库模板，库名为“数据图表支持库”，声明提供柱状图、饼形图和曲线图三类窗口组件，并声明三个同名“打印”命令。当前仓库更接近由易语言支持库模板生成的接口骨架：元数据、组件属性表、通知入口和回调函数已经搭好，但控件创建、属性持久化、绘制、打印和真实运行期状态逻辑尚未实现。

项目不是独立的图表绘制引擎，也没有示例易语言工程、运行时资源、第三方图表库、数据库或网络服务。它通过易语言支持库 ABI 与宿主通信，最终产物设计为 Windows 动态库（动态配置目标扩展名为 `.fne`）或静态库。

## 2. 总体流程

```text
易语言 IDE / 编译器
        │
        ├─ 动态装载：LoadLibrary → GetNewInf()
        │                         │
        │                         └─ 返回 LIB_INFO
        │                              ├─ 库身份/版本/系统要求
        │                              ├─ 3 个 LIB_DATA_TYPE_INFO
        │                              ├─ 3 个 CMD_INFO
        │                              ├─ 15 个命令参数元数据
        │                              ├─ 常量表（当前为空）
        │                              └─ echartbar_ProcessNotifyLib_echartbar
        │
        ├─ 组件设计/运行：LIB_DATA_TYPE_INFO
        │      ├─ BarChart → echartbar_GetInterface_BarChart
        │      │              ├─ 创建组件
        │      │              ├─ 属性 UI 可用性
        │      │              ├─ 自定义属性对话框
        │      │              ├─ 属性修改通知
        │      │              ├─ 读全部/单个属性
        │      │              ├─ 按键询问
        │      │              └─ 附加通知接收者
        │      ├─ PieChart → echartbar_GetInterface_PieChart
        │      └─ LineChart → echartbar_GetInterface_LineChart
        │
        ├─ 命令调用：CMD_INFO → PFN_EXECUTE_CMD
        │      ├─ BarPrint_0 → echartbar_BarPrint_0_echartbar
        │      ├─ PiePrint_1 → echartbar_PiePrint_1_echartbar
        │      └─ LinePrint_2 → echartbar_LinePrint_2_echartbar
        │             （当前只读取参数局部变量，未执行打印）
        │
        └─ 系统通知：NL_SYS_NOTIFY_FUNCTION
               → ProcessNotifyLib
               → fnshare.cpp 保存 PFN_NOTIFY_SYS
               → NotifySys 转发宿主通知
```

## 3. 真实目录与文件地图

```text
echartbar/
├── echartbar.sln                         # VS 解决方案，动态库+静态库两个项目
├── echartbar.vcxproj                     # echartbar 动态库工程
├── echartbar_static/
│   ├── echartbar_static.vcxproj          # 复用同一批源码的静态库工程
│   ├── echartbar_static.vcxproj.filters
│   └── echartbar_static.vcxproj.user
├── echartbar.vcxproj.filters
├── echartbar.vcxproj.user
├── Source_echartbar.def                  # 动态库导出定义，仅声明 GetNewInf
├── include_echartbar_header.h            # 项目统一头，声明全局元数据和命令函数
├── echartbar_cmd_typedef.h               # ECHARTBAR_DEF 命令单一宏定义
├── echartbar_cmdDef.cpp                  # 三个命令实现骨架
├── echartbar_cmdInfo.cpp                 # 参数元数据、命令描述数组
├── echartbar_const.cpp                   # 空常量表
├── echartbar_dllMain.cpp                 # DLL/库信息/通知入口/GetNewInf
├── echartbar_dtType.cpp                  # 三个控件的数据类型、属性表、接口回调
├── elib/
│   ├── fnshare.cpp                       # 宿主通知函数指针与调试状态
│   ├── fnshare.h                         # 内存、数组、文本、通知等公共辅助
│   ├── lib2.h                            # 易语言支持库 ABI 结构、类型、宏和常量
│   ├── lang.h                            # 语言版本定义（GBK）
│   ├── krnllib.h                         # 系统核心支持库接口声明
│   ├── mtypes.h                          # Win32/基础 C 类型兼容定义
│   ├── untshare.h                         # 控件/属性辅助类和 Win32 辅助
│   └── PublicIDEFunctions.h               # IDE 公共功能号和参数结构
└── LICENSE
```

现场核对结果：项目共 26 个非 `.git` 文件（含 2 个工程目录及工程文件），没有 `README`、`AGENTS.md`、`CLAUDE.md`、测试目录、测试文件或旧 `细探-*.md`。因此不存在可吸收的旧细探；本文件为项目根唯一架构事实源。

## 4. 构建工程与产物边界

### 4.1 解决方案

`echartbar.sln` 使用 Visual Studio 17 格式，包含：

- `echartbar.vcxproj`：`DynamicLibrary`，项目 GUID `{CEADC3DD-024E-4173-9CCF-E60334B2944F}`；
- `echartbar_static/echartbar_static.vcxproj`：`StaticLibrary`，项目 GUID `{5FF16995-6AD6-4964-A421-E0842E1BE946}`。

两项目均声明 `Debug/Release × Win32/x64` 配置。工程使用 `PlatformToolset=v141`，目标 Windows SDK `10.0.15063.0`，字符集 `Unicode`，源码实际通过本地 `mtypes.h` 提供 Windows 风格基础类型，并由 `elib/lib2.h` 包含 `windows.h`、`stdio.h`、`math.h`、`assert.h`。

### 4.2 动态库

动态工程编译 6 个源文件：`elib/fnshare.cpp`、`echartbar_cmdDef.cpp`、`echartbar_const.cpp`、`echartbar_dllMain.cpp`、`echartbar_dtType.cpp`、`echartbar_cmdInfo.cpp`。Win32 Debug/Release 配置显式使用 `Source_echartbar.def`，输出目标扩展名为 `.fne`；x64 配置没有看到同样的 `ModuleDefinitionFile` 和 `.fne` 设置。

`Source_echartbar.def` 只有一个导出：`GetNewInf`。宿主从该导出取 `PLIB_INFO`，而不是从普通 C++ API 发现库能力。

### 4.3 静态库

静态工程复用动态工程的 6 个源码文件，路径以 `..\` 指向根目录，并在 Win32 配置定义 `__E_STATIC_LIB`、`__E_FNENAME=echartbar`。静态模式下，`cmdInfo.cpp` 的命令参数/命令描述数组和 `dllMain.cpp` 的动态库信息区段受 `#ifndef __E_STATIC_LIB` 保护；仍保留命令名数组和通知函数名，用于静态编译阶段回取符号。

已确认的工程风险：静态工程 x64 Debug/Release 配置使用 `PrecompiledHeader=Use`，但项目文件未列出 `pch.h`；同时 x64 配置没有像 Win32 一样定义 `__E_STATIC_LIB` 与 `__E_FNENAME=echartbar`。这些是工程配置事实，是否在特定 VS 环境下被属性表补齐、是否导致 x64 静态构建失败，尚未在 Windows/Visual Studio 上验证。

## 5. 核心模块与调用边界

### 5.1 `echartbar_dllMain.cpp`：宿主库入口

`g_LibInfo_echartbar_global_var` 固定声明：

- 支持库格式号：`LIB_FORMAT_VER`；
- GUID：`9A3F84D7FDEB4a0486F2711D5104B7F7`；
- 库版本：`2.0.0`；
- 要求易语言系统版本：`3.8`；
- 要求系统核心支持库版本：`3.9`；
- 库名：“数据图表支持库”；
- 语言：`__GBK_LANG_VER`；
- 运行平台：`_LIB_OS(__OS_WIN)`；
- 自定义数据类型表：3 项；命令表：3 项；常量表：0 项；
- 系统通知回调：`echartbar_ProcessNotifyLib_echartbar`。

`GetNewInf()` 直接返回上述静态 `LIB_INFO` 地址，没有动态分配和初始化事务。`DllMain` 四类 DLL 生命周期分支均为空，仅返回 `TRUE`。

`echartbar_ProcessNotifyLib_echartbar` 处理动态库命令名、通知函数名、依赖库列表、系统通知、释放、卸载和 IDE 就绪等通知；其中系统通知转发到 `ProcessNotifyLib`，其余多数分支为空。动态模式下依赖库列表返回 `"\0\0"`，未声明额外静态库依赖。

### 5.2 `echartbar_cmd_typedef.h`、`echartbar_cmdInfo.cpp`、`echartbar_cmdDef.cpp`：命令三件套

`ECHARTBAR_DEF(_MAKE)` 是命令元数据的单一宏源，共 3 项：

| 序号 | 易语言名 | 英文符号 | 说明 | 返回 | 参数 |
|---:|---|---|---|---|---:|
| 0 | `打印` | `BarPrint` | 打印柱状图 | `_SDT_NULL` | 5 |
| 1 | `打印` | `PiePrint` | 打印饼形图 | `_SDT_NULL` | 5 |
| 2 | `打印` | `LinePrint` | 打印线图 | `_SDT_NULL` | 5 |

同一宏被重复展开为：命令实现声明、函数指针数组、命令名数组和 `CMD_INFO` 表，避免这些表的序号脱节。`cmdInfo.cpp` 为每个命令建立 5 个参数元数据：`打印对象` 为 `DTP_PRINTER`，后四项为 `SDT_INT`，分别是起始横坐标、起始纵坐标、图表宽度、图表高度；后四项带 `AS_DEFAULT_VALUE_IS_EMPTY`。

三个实现函数位于 `echartbar_cmdDef.cpp`，均读取 `pArgInf[1]` 至 `pArgInf[5]` 的字段到局部变量，但没有使用打印对象、没有校验 `nArgCount`、没有写 `pRetData`、没有调用 Win32 打印 API，也没有返回错误状态。它们当前是可被宿主调度的空实现。

### 5.3 `echartbar_dtType.cpp`：组件类型与属性回调

文件声明并注册 3 个 `LDT_WIN_UNIT` 窗口组件：

| 数据类型 | 英文名 | 命令索引 | 属性表项数 | 当前实现状态 |
|---|---|---:|---:|---|
| 柱状图控件 | `BarChart` | 0 | 38 | 接口骨架，创建/读写/绘制未实现 |
| 饼形图控件 | `PieChart` | 1 | 31 | 接口骨架，创建/读写/绘制未实现 |
| 曲线图控件 | `LineChart` | 2 | 37 | 接口骨架，创建/读写/绘制未实现 |

每个组件的前 8 项是易语言窗口单元通用属性：位置、尺寸、标记、可视、禁止、鼠标指针；随后是图表专属属性。柱状图和曲线图使用二维数据语义（图例索引 × X 轴标注索引），饼图使用一维数据语义（图例索引）。属性表还声明标题、背景、边框、三维、坐标轴、图例、数据值、小数位和提示文本等元数据。

每个组件都有 `echartbar_GetInterface_*`，按 `ITF_*` 编号返回回调函数指针，包括创建、属性 UI 更新、自定义属性对话框、属性修改、读全部/单个属性、按键处理和附加通知接收者；语言转换、消息过滤和图标数据接口当前返回空。

三个组件回调的真实行为基本一致：

- `ControlCreate_*`：标记 `TODO`，令 `HUNIT hUnit = 0` 后返回 0，未创建窗口或保存属性；
- `PropUpDate_*`：无条件返回 `TRUE`；
- `PropPopDlg_*`：将 `*pblModified` 设为 `false`，返回 `FALSE`；未检查指针是否为空；
- `PropChanged_*`：仅保留 `switch` 占位，默认返回 `false`，未做属性范围检查或状态更新；
- `PropGetDataAll_*`：返回 0；
- `PropGetData_*`：仅有占位分支，部分路径返回 `true`，但未填充 `pPropertyVaule`；
- `PropKetInfo_*`：返回 `FALSE`；
- `PropNotifyReceiver_*`：未实现设计器默认尺寸，返回 0。

因此属性表描述的是预期控件模型，不应被误读为已经存在的运行时数据模型；当前没有实际控件句柄、窗口过程、数据数组、序列化格式或绘制对象。

## 6. 数据模型与持久化

### 6.1 元数据模型

数据由易语言 ABI 的静态 C 数组表达：

- `LIB_INFO`：支持库身份、版本、系统要求、命令/类型/常量指针及通知入口；
- `CMD_INFO[]`：命令显示名、英文名、说明、状态、返回类型、参数数量和参数数组指针；
- `ARG_INFO[]`：参数显示名、说明、类型、默认值与参数标志；
- `LIB_DATA_TYPE_INFO[]`：组件类型名、英文名、组件标志、命令索引数组、属性数组和 `PFN_GET_INTERFACE`；
- `UNIT_PROPERTY[]`：属性名、英文名、说明、`UD_*` 类型、平台标志和备选文本；
- `UNIT_PROPERTY_VALUE`/`MDATA_INF`：由宿主 ABI 提供，当前回调只读取部分输入，未完成读写。

### 6.2 运行时状态

当前仓库没有自己的持久化层。没有文件写入、注册表、数据库、网络协议、配置文件解析或外部资源加载。所有表均为静态编译数据；`fnshare.cpp` 只保存宿主通知函数指针和调试版本整数。

### 6.3 预期但未落地的状态

从属性定义和回调注释可以推断后续实现需要管理：控件窗口句柄、设计态属性快照、运行态实时属性、图例/X 轴/数据数组、字体/颜色/图片资源、打印上下文以及属性修改后的重绘/重建。但这些只是接口注释所表达的实现意图，不是当前可验证事实。

## 7. 依赖边界

源码依赖分为三层：

1. **项目层**：`include_echartbar_header.h`、`echartbar_cmd_typedef.h` 与 5 个项目源文件；
2. **易语言支持库 SDK 层**：`elib/lib2.h`、`lang.h`、`krnllib.h`、`mtypes.h`、`fnshare.h/.cpp`、`untshare.h`、`PublicIDEFunctions.h`；
3. **宿主/系统层**：`lib2.h` 引入 `windows.h` 及标准 C 头，类型和回调使用 Win32 `HWND`、`HMENU`、`HGLOBAL`、`HUNIT`、`WINAPI` 等约定。

当前没有 package manager、依赖锁、第三方图表库或额外静态库清单。动态库通知分支也返回空依赖列表。项目实际只面向 Windows；在当前 macOS 工作环境中不能直接假设其工程可构建。

## 8. 入口、接口和命令边界

### 外部入口

- 动态库导出：`GetNewInf`，由 `Source_echartbar.def` 声明；
- 静态编译通知入口：`echartbar_ProcessNotifyLib_echartbar`；
- 命令执行函数：`echartbar_BarPrint_0_echartbar`、`echartbar_PiePrint_1_echartbar`、`echartbar_LinePrint_2_echartbar`；
- 三个组件接口分发函数：`echartbar_GetInterface_BarChart`、`echartbar_GetInterface_PieChart`、`echartbar_GetInterface_LineChart`。

### 宿主回调边界

宿主负责提供 `PMDATA_INF` 参数数据、组件创建环境、属性值结构、窗口句柄、通知函数和生命周期调用顺序；支持库负责按 ABI 返回元数据、函数指针和属性结果。当前实现没有对宿主传入指针、参数数量、属性索引、资源句柄或窗口生命周期作完整校验。

### 命名/链接边界

`ECHARTBAR_NAME` 和 `__E_FNENAME` 宏把命令英文名、序号和库名拼成类似 `echartbar_BarPrint_0_echartbar` 的 ABI 符号；动态/静态模式通过 `__E_STATIC_LIB` 控制元数据和命令表的编译范围。这种“宏定义一次、多个表展开”的方式是本项目最重要的注册契约。

## 9. 测试与验证现状

- 仓库没有测试目录、测试源码、测试夹具、CI 配置或独立验证脚本；
- 没有执行构建，符合本轮“禁止构建”的边界；
- 没有在 macOS 上执行 Visual Studio/MSBuild，也没有 Windows SDK、`v141` 工具链或易语言宿主环境验证；
- 已做只读静态核对：目录清单、工程文件、源文件、头文件、命令宏、组件属性表、导出定义、Git 状态和远程引用；
- 代码图工具报告该仓库没有 `.codegraph/` 索引，因此本档案使用现场源码与工程文件作为证据，不把其他项目代码地图结果混入本项目。

## 10. 风险与未验证项

### 已从源码确认的风险

1. 三个命令函数是空实现，调用不会产生打印行为，也没有结果/错误契约。
2. 三个组件创建函数返回空句柄；属性读写、序列化、绘制、窗口消息和默认设计尺寸均未完成。
3. 属性元数据存在英文名重复/疑似笔误，例如多个“标题字体”英文名为 `Caption`，柱状图/曲线图“当前X轴标注文字”英文名为 `LegendColor`；是否会造成易语言侧成员关联冲突需宿主验证。
4. `PropPopDlg_*` 无条件解引用 `pblModified`，宿主若按可空指针调用可能崩溃。
5. `PropGetData_*` 在未填充输出结构的情况下存在返回成功路径，调用方可能读取未初始化/旧数据。
6. 动态 x64 工程未显式配置 `.def` 导出文件和 `.fne` 扩展名，`GetNewInf` 是否能按预期导出未确认。
7. 静态 x64 工程的预编译头和宏定义与 Win32 配置不一致，可能导致编译或链接行为漂移。
8. `DllMain` 不做生命周期初始化/清理，当前安全性取决于实现没有实际资源；一旦加入窗口、GDI、线程或缓存，需要重新设计释放顺序。
9. `echartbar_cmdDef.cpp` 直接按固定索引读取 5 个参数，未使用 `nArgCount` 做边界保护。

### 本轮未验证

- Windows 10/11 + Visual Studio v141/v143 下四种动态配置是否可编译、链接和装载；
- `GetNewInf` 导出是否在 x86/x64 两种动态产物中一致可见；
- 易语言 IDE 识别库版本、组件、命令和属性表的实际效果；
- `DTP_PRINTER` 参数在易语言宿主中的真实布局和打印调用约定；
- 属性英文名重复是否导致 IDE 成员冲突；
- 静态编译器消费命令名数组、通知函数名和静态宏的真实流程；
- 图表数据数组的宿主 ABI 表示、绘制后端、窗口消息模型和资源释放契约；
- 任何打印、绘制、属性保存、运行态更新或跨版本兼容行为。

## 11. Git 远程与版本基线

- 当前分支：`master`；
- 当前提交：`4282922aed8711406c3ef7bf50643c4e566c71d9`；
- 当前提交时间：`2022-12-19T08:35:16Z`；
- 提交说明：`add LICENSE.`；
- 远程：`origin = https://gitee.com/JYtechnology/echartbar.git`；
- 本地是 shallow repository；现场 `git ls-remote origin HEAD refs/heads/master` 返回同一提交 `4282922aed8711406c3ef7bf50643c4e566c71d9`，因此本轮观察到本地与远程 `master` 一致；
- 工作树在建档前干净；本轮预期唯一变更是根目录 `ARCHITECTURE.md`。

## 12. 后续复核顺序

1. 先在 Windows/Visual Studio 环境验证动态 x86/x64 工程的导出、目标后缀和 ABI 装载；
2. 再用易语言 IDE 实际加载，核对库元数据、三个组件、三个命令和属性英文名冲突；
3. 明确组件实例状态模型：设计态快照、运行态句柄、数据数组、资源所有权和线程/UI 线程边界；
4. 实现并验证属性全量序列化/反序列化和属性合法性校验；
5. 实现真实绘制、窗口消息、重绘和打印链路；
6. 为命令参数、组件生命周期、宿主通知、错误返回和资源释放建立 Windows 宿主测试夹具；
7. 最后再处理 x64 静态配置的 `pch.h`、`__E_STATIC_LIB`、`__E_FNENAME` 和动态 `.def` 配置差异。

---

## 证据索引

- 解决方案与构建矩阵：`echartbar.sln`；
- 动态工程与编译宏：`echartbar.vcxproj`；
- 静态工程与复用关系：`echartbar_static/echartbar_static.vcxproj`；
- 导出边界：`Source_echartbar.def`；
- 统一头和 ABI 声明：`include_echartbar_header.h`、`echartbar_cmd_typedef.h`；
- 库入口和版本元数据：`echartbar_dllMain.cpp`；
- 命令元数据：`echartbar_cmdInfo.cpp`；
- 命令实现骨架：`echartbar_cmdDef.cpp`；
- 控件类型、属性与接口回调：`echartbar_dtType.cpp`；
- 宿主通知和辅助运行时：`elib/fnshare.cpp`、`elib/fnshare.h`；
- ABI/基础类型/IDE 接口：`elib/lib2.h`、`elib/mtypes.h`、`elib/lang.h`、`elib/krnllib.h`、`elib/PublicIDEFunctions.h`、`elib/untshare.h`。
