# eword2000 架构建档

## 1. 项目定位

`eword2000` 是面向易语言的 Windows `WORD2000支持库` 源码骨架，目标是为易语言提供 Microsoft Word 2000/XP/2003 或更高版本的 Word 自动化操作命令、可视化对象和属性元数据。项目不是独立的 Word 文档处理程序，而是一个按易语言支持库 ABI 装载的 `.fne` 动态库，同时提供静态库工程。

源码中的库说明明确表示：支持库需要机器安装 Word；设计目标是常用、简单的 Word 操作，并与易语言 3.7 的“对象”机制兼容。当前提交中的命令执行体和组件回调仍以生成模板/占位实现为主，不能据此断言已具备可运行的 Word COM 自动化能力。

## 2. 版本与证据基线

- 本地根目录：`/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/eword2000`
- Git 分支：`master`
- HEAD：`3f9cca2019cc6ef8c269260e1c52cb17454665e1`
- HEAD 时间：`2022-12-19T16:08:35+08:00`
- HEAD 提交：`初始化仓库`
- 远程：`https://gitee.com/JYtechnology/eword2000.git`
- 远程复核：`origin/HEAD` 与 `origin/master` 均为 `3f9cca2019cc6ef8c269260e1c52cb17454665e1`
- 工作树状态：建档前为干净状态；本次只新增本文件。
- Git 历史：当前浅克隆只有上述一个提交。
- 旧细探：项目根未发现 `细探-*.md`；此前不存在项目根 `ARCHITECTURE.md`。
- 研究边界：只读源码、工程、Git 元数据和头文件；未修改源码，未安装依赖，未构建、未运行、未提交。

## 3. 总体流程

```text
易语言 IDE/运行时
        │
        │ 装载 .fne / 读取支持库 ABI
        ▼
Source_eword2000.def ───────────────► 导出 GetNewInf
        │                                      │
        ▼                                      ▼
eword2000_dllMain.cpp                 LIB_INFO g_LibInfo_eword2000_global_var
        │                                      │
        ├─ DllMain（仅 DLL 模式生命周期占位）  ├─ 4 个自定义数据类型
        ├─ eword2000_ProcessNotifyLib         ├─ 33 个命令元数据
        ├─ 命令函数指针表                     ├─ 0 个预定义常量
        └─ 静态编译命令名表                   └─ ProcessNotifyLib 通知入口
        │
        ├──────────────────────┐
        ▼                      ▼
命令元数据链路               对象/组件元数据链路
eword2000_cmd_typedef.h      eword2000_dtType.cpp
  EWORD2000_DEF               4 个数据类型
        │                      │
        ├─ eword2000_cmdInfo   ├─ WordApp
        │  参数 ARG_INFO        ├─ WordDocuments
        │  命令 CMD_INFO        ├─ WordShapes
        │                      └─ Units 枚举
        ▼                      │
命令实现 eword2000_cmdDef.cpp  ├─ GetInterface_*
  33 个导出命令函数             ├─ ControlCreate_*
  当前大部分为空函数体           ├─ Prop* 属性回调
                                 └─ 设计器/运行时通知接口
        │
        ▼
elib/fnshare.cpp/.h
  保存 PFN_NOTIFY_SYS、转发通知、运行环境调试版本
        │
        ▼
易语言运行时通知协议
  NotifySys / ProcessNotifyLib / NRS_* / NL_*
```

## 4. 目录与文件地图

```text
eword2000/
├── ARCHITECTURE.md                         本权威架构文档
├── eword2000.sln                           VS 解决方案，含 DLL 与静态库两个项目
├── eword2000.vcxproj                       动态库工程，目标扩展名主要为 .fne
├── eword2000_static/
│   ├── eword2000_static.vcxproj             静态库工程
│   ├── eword2000_static.vcxproj.filters
│   └── eword2000_static.vcxproj.user
├── eword2000_cmd_typedef.h                  命令编号、中文名、英文名、返回类型、参数元数据宏
├── eword2000_cmdInfo.cpp                    ARG_INFO 参数表与 CMD_INFO 数组
├── eword2000_cmdDef.cpp                     33 个命令执行函数的实现位置
├── eword2000_dtType.cpp                     组件/对象/枚举数据类型、属性及接口回调
├── eword2000_const.cpp                      常量表；当前数量为 0
├── eword2000_dllMain.cpp                    DLL 入口、LIB_INFO、通知入口、函数指针表
├── include_eword2000_header.h               统一公共头，声明全局元数据和命令函数
├── Source_eword2000.def                     仅导出 GetNewInf
└── elib/
    ├── lib2.h                               易语言支持库 ABI、类型、命令、通知定义
    ├── fnshare.h / fnshare.cpp               通知函数保存与公共辅助函数
    ├── mtypes.h                              跨工程基础类型与 Win32 兼容类型
    ├── lang.h                                语言版本常量，当前编译为 GBK
    ├── krnllib.h                             核心支持库组件类型常量
    ├── PublicIDEFunctions.h                  IDE 辅助功能号与接口声明
    └── untshare.h                            组件公共辅助类/窗口属性占位工具
```

## 5. 构建工程与依赖边界

### 5.1 动态库工程

`eword2000.vcxproj` 编译以下源文件：`elib/fnshare.cpp`、`eword2000_cmdDef.cpp`、`eword2000_const.cpp`、`eword2000_dllMain.cpp`、`eword2000_dtType.cpp`、`eword2000_cmdInfo.cpp`；公共头文件来自 `elib/`、`include_eword2000_header.h` 和 `eword2000_cmd_typedef.h`。

- 配置：`Debug|Win32`、`Release|Win32`、`Debug|x64`、`Release|x64`。
- Win32 目标类型：`DynamicLibrary`；Win32 配置设置 `TargetExt=.fne`。
- 工具集：`v141`；Windows SDK：`10.0.15063.0`；字符集：Unicode。
- Win32 预处理器包含 `__E_FNENAME=eword2000`；该宏参与命令函数名拼接。
- 链接通过 `Source_eword2000.def` 导出 `GetNewInf`，由易语言装载器取得 `PLIB_INFO`。
- 工程未声明第三方库或外部源码子模块；Word 自动化本身没有在本提交中出现 COM 接口调用、`#import`、`ole32`/`oleaut32` 链接声明或实现代码。

### 5.2 静态库工程

`eword2000_static/eword2000_static.vcxproj` 复用上层同一批源码，配置类型为 `StaticLibrary`，Win32 预处理器包含 `__E_STATIC_LIB;__E_FNENAME=eword2000`。静态模式依赖 `eword2000_dllMain.cpp` 中的条件编译路径：不生成 `DllMain` 和 DLL 元数据导出，但保留命令实现和静态命令名机制。

需要后续复核的工程问题：解决方案映射了 `x86` 到 `Win32`，而 x64 配置没有动态库 Win32 路径中的 `__E_FNENAME`、`.def`/`.fne` 目标扩展等完整对称设置；静态库 x64 配置还使用 `PrecompiledHeader=Use`，但仓库文件列表中没有 `pch.h`。本轮未在 Windows/Visual Studio 上验证构建，因此这些属于配置风险，不是已验证的构建失败结论。

### 5.3 源码依赖

- 运行时宿主：易语言 IDE/运行时支持库 ABI。
- 操作系统：Windows；库信息使用 `_LIB_OS(__OS_WIN)`，数据类型也标记 `_DT_OS(__OS_WIN)`。
- 编码：`elib/lang.h` 将 `__COMPILE_LANG_VER` 设为 `__GBK_LANG_VER`。
- 系统接口：头文件使用 Win32 类型/常量和窗口组件通知协议；`mtypes.h` 自带一组基础类型兼容定义。
- Word：库说明要求目标机器安装 Word 2000/XP/2003 或更高版本，但本提交没有可定位的 Word COM 调用实现，依赖关系目前只能记录为设计目标/运行前提。

## 6. 支持库 ABI 与启动链路

### 6.1 公共元数据

`include_eword2000_header.h` 引入 `elib/lib2.h`、`lang.h`、`krnllib.h` 和命令类型定义，并声明：

- `g_ConstInfo_eword2000_global_var` / `_count`
- `g_cmdInfo_eword2000_global_var` / `_fun` / `_count`
- `g_argumentInfo_eword2000_global_var`
- `g_DataType_eword2000_global_var` / `_count`

`elib/lib2.h` 定义易语言支持库的核心 ABI，包括 `LIB_INFO`、`CMD_INFO`、`ARG_INFO`、`LIB_DATA_TYPE_INFO`、`MDATA_INF`、`PFN_EXECUTE_CMD`、`PFN_NOTIFY_LIB` 等结构/函数类型。命令执行约定为 `void (PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)`。

### 6.2 DLL 装载

1. `Source_eword2000.def` 仅声明 `GetNewInf` 为导出符号。
2. `GetNewInf()` 返回 `&g_LibInfo_eword2000_global_var`。
3. `LIB_INFO` 固定库格式号 `LIB_FORMAT_VER`，GUID 为 `F30A56A231354a4a81AB13B54EF21665`。
4. 库版本为 `2.0.0`；要求易语言系统 `3.7`、核心支持库 `3.7`。
5. 库名为 `WORD2000支持库`，语言为 `__GBK_LANG_VER`，仅支持 Windows。
6. `m_nDataTypeCount` 指向 4 个自定义数据类型；`m_nCmdCount` 指向 33 个命令；常量数为 0；无 AddIn 和 SuperTemplate；通知函数为 `eword2000_ProcessNotifyLib_eword2000`。

### 6.3 通知链路

`eword2000_ProcessNotifyLib_eword2000` 处理库级通知：

- `NL_GET_CMD_FUNC_NAMES`：返回由 `EWORD2000_DEF` 生成的命令函数名数组。
- `NL_GET_NOTIFY_LIB_FUNC_NAME`：返回 `eword2000_ProcessNotifyLib_eword2000` 的函数名。
- `NL_GET_DEPENDENT_LIBS`：返回空依赖列表 `"\\0\\0"`。
- `NL_SYS_NOTIFY_FUNCTION`：调用 `ProcessNotifyLib`，将系统通知函数指针交给 `elib/fnshare.cpp` 保存。
- `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NL_IDE_READY` 等：当前为空处理。
- 未识别通知：返回 `NR_ERR`。

`elib/fnshare.cpp` 的 `NotifySys` 通过保存的 `PFN_NOTIFY_SYS` 回调系统；`ProcessNotifyLib` 在收到 `NL_SYS_NOTIFY_FUNCTION` 时保存系统回调，并通过 `NRS_GET_PRG_TYPE` 初始化调试/运行版本值；还可将通知转发给 `SetUserSysNotify` 设置的用户回调。

## 7. 命令模型与实际命令面

### 7.1 生成式命令定义

`eword2000_cmd_typedef.h` 以单一 `EWORD2000_DEF(_MAKE)` 宏保存命令目录。该宏被复用生成：

- `eword2000_cmdDef.cpp` 的函数声明/实现对应关系；
- `eword2000_cmdInfo.cpp` 的 `CMD_INFO` 元数据数组；
- `eword2000_dllMain.cpp` 的函数指针数组；
- DLL 静态编译所需的命令函数名数组。

函数名由 `EWORD2000_NAME` 拼接为类似 `eword2000_Create_0_eword2000` 的符号，编号是 ABI 对应关系的一部分，不能随意重排。

### 7.2 33 个命令

所有命令类别字段为对象成员（`m_shtCategory=-1`），操作系统标志为 Windows；命令按对象职责分为：

- `Word程序`（0–4）：`Create`、`Release`、`GetApp`、`Quit`、`ActivateWindow`。
- `Word文档集`（5–24）：`SetWordApp`、`Release`、`RunMacro`、`GetDocuments`、`GetDocument`、`GetSelection`、`Add`、`Open`、`SaveAs`、`PrintPreview`、`ClosePrintPreview`、`PrintOut`、`ActivateDoc`、`KeyboardInput`、`SelectAll`、`GoTo`、`MoveLeft`、`MoveRight`、`MoveUp`、`MoveDown`。
- `Word图形`（25–32）：`SetWordDocument`、`Release`、`GetShapes`、`AddPicture`、`AddShapes`、`AddTextbox`、`AddTextEffect`、`Close`。

命令返回类型覆盖 `_SDT_NULL`、`SDT_BOOL`、`SDT_FLOAT`/整数参数以及通过 `MAKELONG(0x10030, 0)` 表示的兼容对象返回类型。`RunMacro` 允许追加参数；`ActivateDoc` 带 `CT_IS_HIDED` 隐藏标志；`PrintOut` 是 16 参数的高复杂度命令；其它命令主要使用 0–8 个参数。

### 7.3 参数表

`eword2000_cmdInfo.cpp` 的 `ARG_INFO` 参数表按偏移被命令元数据引用，共使用索引 `0–64` 的参数描述槽位（实际数组声明以源码为准）。参数类型包括：

- `MAKELONG(0x01, 0)`：Word 程序对象；
- `MAKELONG(0x02, 0)`：Word 文档集对象；
- `SDT_BOOL`、`SDT_INT`、`SDT_FLOAT`、`SDT_TEXT`；
- 默认值通过 `AS_HAS_DEFAULT_VALUE` 标志及 `m_nDefault` 提供；文本默认值在生成的元数据中以指针整数形式出现，实际解释依赖易语言 ABI。

参数分组与命令对应关系在 `EWORD2000_DEF` 中明确：`SetWordApp` 使用对象名/是否添加文档；`RunMacro` 使用宏名；`Open`/`SaveAs` 使用文件名；`PrintOut` 使用打印范围、文件、页码、份数、页面类型等 16 个参数；移动命令使用度量单位/单位数/延伸；图形命令使用文本、图形类型、坐标、宽高、字体等参数。

## 8. 数据模型、对象和属性

### 8.1 四个库数据类型

`eword2000_dtType.cpp` 声明 `g_DataType_eword2000_global_var`，数量为 4：

| 索引 | 中文名 | 英文名 | 类型/职责 |
|---:|---|---|---|
| 0 | `Word程序` | `WordApp` | Windows 窗口单元、函数提供者；创建/操作 Word 程序 |
| 1 | `Word文档集` | `WordDocuments` | Windows 窗口单元、函数提供者；操作文档集、文档和选定内容 |
| 2 | `Word图形` | `WordShapes` | Windows 窗口单元、函数提供者；添加 Word 图形 |
| 3 | `度量单位` | `Units` | Windows 枚举数据类型；为移动操作提供单位 |

三个对象类型均通过 `GetInterface_*` 暴露组件接口；`WordApp` 和 `WordDocuments` 有属性数组，`WordShapes` 没有属性数组；`Units` 通过成员数据数组提供枚举值。`dtType` 中同时声明了对象命令索引、属性、事件和交互函数指针，但这些表/回调大量是模板化数据或占位逻辑。

### 8.2 属性与接口模型

对象组件遵循 `elib/lib2.h` 的接口编号：`ITF_CREATE_UNIT`、`ITF_PROPERTY_UPDATE_UI`、`ITF_DLG_INIT_CUSTOMIZE_DATA`、`ITF_NOTIFY_PROPERTY_CHANGED`、`ITF_GET_ALL_PROPERTY_DATA`、`ITF_GET_PROPERTY_DATA`、`ITF_IS_NEED_THIS_KEY`、`ITF_GET_NOTIFY_RECEIVER` 等。

`WordApp` 属性包含窗口坐标、标题、窗口状态、显示/版本、打印机、全屏和缩放等信息；`WordDocuments` 属性包含文档/选区相关状态；公共属性宏还包含左/顶/宽/高、标记、可视、禁止、鼠标指针等。具体属性名称和顺序必须以 `eword2000_dtType.cpp` 数组为准，属性索引是回调协议的一部分。

每个对象的组件接口都提供以下同构回调族：

- `eword2000_GetInterface_WordApp/WordDocuments/WordShapes`；
- `ControlCreate_*`；
- `PropUpDate_*`；
- `PropPopDlg_*`；
- `PropChanged_*`；
- `PropGetDataAll_*`；
- `PropGetData_*`；
- `PropKetInfo_*`；
- `PropNotifyReceiver_*`。

### 8.3 持久化与所有权

本提交未发现业务数据库、文件存储层或自定义持久化格式。`elib/untshare.h` 中的 `CPropertyInfo`、`SaveData`、`LoadData` 和字符串/图标序列化辅助实现基本为空或被注释，不能视为已经建立可用的属性持久化机制。组件属性数据按易语言 ABI 约定以 `HGLOBAL`/字节缓冲区形式交给宿主，但本项目中的 `PropGetDataAll_*` 当前返回 0，属性变更回调也只保留模板分支。

## 9. 真实调用链与当前实现状态

### 9.1 命令调用链

```text
易语言程序调用对象命令
  → 易语言运行时按 CMD_INFO 定位命令编号
  → 从 g_cmdInfo_eword2000_global_var_fun 取得 PFN_EXECUTE_CMD
  → 调用 eword2000_<Name>_<Index>_eword2000(pRetData, nArgCount, pArgInf)
  → 命令体读取 pArgInf[n].m_* 字段
  → 应填充 pRetData 或调用 Word 自动化对象
  → 当前源码：大部分函数仅读取参数局部变量后结束，未见 Word 自动化调用
```

`eword2000_cmdDef.cpp` 中实际有 33 个函数；按空函数体模式统计，17 个函数体为空，另外 16 个仅读取参数或保留空实现。文件中没有可验证的 Word COM 对象创建、方法调用、异常映射或返回值填充链路。

### 9.2 组件创建/属性调用链

```text
易语言 IDE 选择 Word 组件
  → LIB_DATA_TYPE_INFO 取得类型的 GetInterface
  → ITF_CREATE_UNIT → ControlCreate_*
  → 创建窗口单元并保存属性数据（预期）
  → ITF_* → PropUpDate_*/PropChanged_*/PropGetData_*
  → 通过 NotifySys/NRS_* 与宿主交换运行时信息
  → 当前源码：ControlCreate_* 返回 0；属性读写/持久化多为模板返回值
```

### 9.3 通知调用链

```text
易语言宿主
  → eword2000_ProcessNotifyLib_eword2000(NL_SYS_NOTIFY_FUNCTION, pfn, ...)
  → ProcessNotifyLib
  → fnshare.cpp 保存 s_pfnNotifySys
  → NotifySys(nMsg, dwParam1, dwParam2)
  → 宿主处理 NRS_* 通知并返回
```

## 10. 测试、验证与未执行事项

- 仓库没有测试目录、测试工程或自动化测试脚本。
- 已验证：文件清单、工程配置、Git 本地/远程提交指针、命令函数数量（33）、数据类型数量（4）、常量数量（0）、源码中空函数体数量（17）。
- 未执行：Visual Studio/MSBuild 构建、DLL 加载、静态库链接、易语言 IDE 集成、Word COM 自动化、命令行为、属性序列化、事件通知和跨平台编译。
- 当前 macOS 环境不具备该 Windows/Visual Studio/Word 运行链，不能把本轮静态阅读结果表述为可运行验证。

## 11. 风险与后续复核点

### 高风险

1. **核心功能未实现或未闭环**：命令函数体大多为空；未发现 Word COM 自动化实现、对象生命周期、异常处理和返回值写回。
2. **组件创建不可用**：`ControlCreate_*` 仍含 `TODO` 并返回 `0`；这会使 IDE 设计器/运行时组件创建链无法据源码确认成功。
3. **属性数据链为空**：`PropGetDataAll_*` 返回 0，`PropPopDlg_*`、`PropChanged_*` 使用模板逻辑，属性持久化尚未落地。
4. **运行时内存/所有权未闭环**：`MDATA_INF`、复合对象、文本、`HGLOBAL` 和 Word 对象的分配/释放边界未实现；不能安全推断宿主不会泄漏或崩溃。

### 中风险

1. **命令元数据与实现依赖宏同步**：编号、函数名、参数偏移必须保持同步；修改 `EWORD2000_DEF` 任一行可能破坏 ABI。
2. **兼容对象类型未解释**：`MAKELONG(0x10030, 0)` 返回值依赖易语言 3.7 “对象”协议，项目内没有对应实现或类型转换说明。
3. **GBK/文本指针风险**：库声明为 GBK，源码/工具链编码混杂；参数默认文本和 `LPSTR` 的生命周期、转换责任未在项目内说明。
4. **静态库配置不对称**：x64 配置与 Win32 的预处理器、预编译头和产物设置不完全一致；需要 Windows 工具链复核。
5. **宿主版本耦合**：要求易语言系统和核心支持库 3.7，通知码、结构布局、对象返回值均依赖 `elib/lib2.h` ABI。

### 低/待核

1. `elib/` 文件带有“授权给第三方开发易语言支持库”的版权限制说明，后续再利用前需要单独审查授权范围。
2. `LIB_INFO.m_szDependFiles` 为 `NULL`，但真正运行是否需要 Word/系统组件注册、额外 `.fne` 或 COM 依赖，源码未形成机器可检查的依赖清单。
3. `eword2000_dtType.cpp` 中对象属性/事件数组的完整语义、索引和默认值需要按 ABI 结构逐项复核，不能仅凭中文名称推断行为。
4. 当前浅克隆只有一个提交；无法从本地历史判断这些空实现是初始骨架、开发中间态还是有意保留的兼容接口。

## 12. 后续复核顺序

```text
第一轮（已完成）：静态架构、ABI、工程、命令/类型清单与风险建档
        ↓
第二轮：逐项核对 dtType 的对象命令索引、属性/事件数组和接口结构布局
        ↓
第三轮：追溯 Word COM/对象实现来源，确认是否缺失子模块、历史分支或生成步骤
        ↓
第四轮：在隔离 Windows + VS + Word 环境验证 DLL 装载、命令调用、组件创建和属性序列化
        ↓
第五轮：补充内存所有权、异常恢复、版本兼容、发布产物与安全审查
```

本文件是项目根唯一架构事实源；后续深挖应增量更新本文件，不应另建平行架构报告。
