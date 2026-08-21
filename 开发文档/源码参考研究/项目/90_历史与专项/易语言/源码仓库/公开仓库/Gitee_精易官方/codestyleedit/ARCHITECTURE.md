# codestyleedit 架构建档

> 本文件是本项目首轮全量架构建档的唯一事实源。源码、工程文件和 `elib/` 仅作只读取证；后续细探应增量维护本文件，不再另建平行架构报告。

## 1. 项目定位

`codestyleedit` 是一个面向易语言（EPL）Windows 运行时/IDE 的“代码编辑框支持库”工程。它以易语言支持库 ABI 为边界，声明一个名为 `CodeStyleEdit` 的窗口组件、一个名为 `CodeEditConst` 的枚举常量数据类型，以及 184 个编辑框命令；动态库入口通过固定导出 `GetNewInf` 向易语言返回 `LIB_INFO`。

当前仓库更接近“支持库元数据与接口骨架”：命令定义、参数、属性、事件、库信息均已大量登记，但 184 个命令函数体只有参数提取、没有实际执行或返回值写回；组件创建、属性持久化和运行时交互回调也仍是模板桩。因此，不能把命令表中的能力描述等同于已经可运行的编辑器实现。

## 2. 版本与现场基线

| 项目 | 现场事实 |
|---|---|
| 本地根目录 | `/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/codestyleedit` |
| Git 分支 | `master`，工作树在建档前干净 |
| 本地 HEAD | `8fbbc63acc5d91028b070010f4c748d64e12a71b` |
| 本地提交时间 | `2022-12-19T07:47:21Z` |
| 最近提交 | `add LICENSE.` |
| 远程 | `https://gitee.com/JYtechnology/codestyleedit.git` |
| 远程 `HEAD`/`master` | `8fbbc63acc5d91028b070010f4c748d64e12a71b`，与本地一致 |
| 仓库形态 | shallow clone；现场 `git rev-parse --is-shallow-repository` 为 `true` |
| 版本新鲜度 | 远程 HEAD 与本地 HEAD 相同，未执行 fetch/pull |
| README/旧细探 | 根目录没有 README；没有发现 `细探-*.md`、`ARCHITECTURE.md` 等既有架构文档 |
| Git 跟踪文件数 | 24 |
| 测试目录/测试文件 | 未发现测试目录或测试文件 |

源码文件带 CRLF，中文源码以非 UTF-8 字节保存；`elib/lang.h` 明确声明编译语言为 `__GBK_LANG_VER`。本次阅读按 GB18030 兼容方式解码，未改动源码编码。

## 3. 总体流程图

```text
易语言 IDE / 编译器 / 运行时
          |
          | 动态库加载并查找固定导出 GetNewInf
          v
codestyleedit_dllMain.cpp
  |-- LIB_INFO：GUID、版本、系统需求、库名、命令表、函数指针表、通知回调
  |-- codestyleedit_ProcessNotifyLib_codestyleedit()
  |       |-- 接收 NL_SYS_NOTIFY_FUNCTION
  |       |     `-> 转发到 elib/fnshare.cpp::ProcessNotifyLib()
  |       |           `-> 保存易语言系统通知函数指针
  |       |-- 处理静态编译相关名称/依赖查询
  |       `-- 其他通知目前为空或返回默认错误
  |
  | 加载后按命令索引调用
  v
CODESTYLEEDIT_DEF(_MAKE) 统一命令宏
  |-- codestyleedit_cmd_typedef.h：184 条命令的名称/英文名/返回类型/参数偏移
  |-- codestyleedit_cmdInfo.cpp：184 条命令的 CMD_INFO 元数据
  |-- codestyleedit_dllMain.cpp：184 个函数指针数组
  `-> codestyleedit_cmdDef.cpp：184 个命令入口
          `-> 当前只读取 pArgInf 参数，未调用窗口/Scintilla，未写 pRetData

CodeStyleEdit 组件元数据
  |
  `-> codestyleedit_dtType.cpp::codestyleedit_GetInterface_CodeStyleEdit()
          |-- ITF_CREATE_UNIT             -> ControlCreate：当前返回 0
          |-- ITF_PROPERTY_UPDATE_UI      -> 当前固定返回 TRUE
          |-- ITF_DLG_INIT_CUSTOMIZE_DATA -> 当前固定未修改并返回 FALSE
          |-- ITF_NOTIFY_PROPERTY_CHANGED -> 当前未实现属性分支，返回 FALSE
          |-- ITF_GET_ALL_PROPERTY_DATA   -> 当前返回 0
          |-- ITF_GET_PROPERTY_DATA       -> 当前仅模板分支，返回 TRUE/默认值
          |-- ITF_IS_NEED_THIS_KEY        -> 当前返回 FALSE
          `-- ITF_GET_NOTIFY_RECEIVER     -> 当前返回默认通知接收者函数
```

## 4. 真实目录与职责地图

```text
codestyleedit/
├── codestyleedit.sln                         # VS 解决方案，DLL + 静态库两个项目
├── codestyleedit.vcxproj                     # 动态库项目，4 个 Win32/x64 Debug/Release 配置
├── codestyleedit_static/
│   ├── codestyleedit_static.vcxproj          # 静态库项目，复用上层全部源码
│   ├── codestyleedit_static.vcxproj.filters
│   └── codestyleedit_static.vcxproj.user
├── Source_codestyleedit.def                  # DLL 只声明导出 GetNewInf
├── include_codestyleedit_header.h            # 统一头文件、全局元数据声明、命令入口声明宏
├── codestyleedit_cmd_typedef.h               # CODESTYLEEDIT_DEF：184 条命令的单一宏清单
├── codestyleedit_cmdInfo.cpp                 # ARG_INFO（166 个参数记录）和 CMD_INFO 数组
├── codestyleedit_cmdDef.cpp                  # 184 个命令入口；当前均为未实现桩
├── codestyleedit_const.cpp                   # 全局常量数组；当前数量为 0
├── codestyleedit_dtType.cpp                  # CodeStyleEdit/CodeEditConst 元数据与组件接口桩
├── codestyleedit_dllMain.cpp                 # DLL 入口、LIB_INFO、函数指针表、系统通知分发
├── elib/
│   ├── lib2.h                                # 易语言支持库 ABI、数据类型、LIB_INFO、命令/组件结构
│   ├── mtypes.h                              # Windows 风格基础类型与句柄兼容定义
│   ├── lang.h                                # GBK/英语/BIG5/SJIS 语言版本宏
│   ├── krnllib.h                             # 系统核心支持库版本/GUID/文件名常量
│   ├── fnshare.h / fnshare.cpp               # NotifySys、内存、通知转发和公共数据辅助函数
│   ├── untshare.h                            # 组件属性、窗口样式、序列化等公共模板辅助；本项目未形成具体组件实现
│   └── PublicIDEFunctions.h                  # IDE 功能通知常量和参数结构
└── LICENSE                                    # MIT License，版权主体为 2022 精易科技
```

项目没有 README、构建脚本、包管理清单、第三方源码目录、资源文件、示例工程或测试工程。

## 5. 工程与构建拓扑

### 5.1 动态库项目

`codestyleedit.vcxproj` 的 `ConfigurationType` 为 `DynamicLibrary`，目标工具集为 `v141`，Windows SDK 目标版本为 `10.0.15063.0`，源码文件为：

- `elib/fnshare.cpp`
- `codestyleedit_cmdDef.cpp`
- `codestyleedit_const.cpp`
- `codestyleedit_dllMain.cpp`
- `codestyleedit_dtType.cpp`
- `codestyleedit_cmdInfo.cpp`

Win32 Debug/Release 配置定义了 `__E_FNENAME=codestyleedit`、`WIN32`、DLL/Debug 或 Release 宏，并设置 `TargetExt=.fne`；Win32 链接配置引用 `Source_codestyleedit.def`，因此预期通过 `.def` 导出 `GetNewInf`。

x64 Debug/Release 配置没有定义 `__E_FNENAME=codestyleedit`，也没有设置 `TargetExt` 或 `ModuleDefinitionFile`。这是一个未在本机编译验证的工程配置风险：`elib/lib2.h` 在未定义 `__E_FNENAME` 时会直接触发预处理错误，且 x64 DLL 的固定入口导出方式未在工程配置中明确。

### 5.2 静态库项目

`codestyleedit_static/codestyleedit_static.vcxproj` 的 `ConfigurationType` 为 `StaticLibrary`，复用上层全部 `.cpp/.h`，Win32 Debug/Release 定义 `__E_STATIC_LIB;__E_FNENAME=codestyleedit`，以便命令符号改名并避免动态库信息路径。

x64 Debug/Release 同样缺少 `__E_STATIC_LIB` 和 `__E_FNENAME=codestyleedit` 定义，并且把预编译头设置为 `Use`，而 Win32 配置为 `NotUsing`；这与源码的宏前提不一致，属于需要在 Windows/Visual Studio 环境复核的高风险配置。

两个项目均未声明额外链接库，也没有随仓库提供 Scintilla 源码、头文件或二进制库。源码注释和命令命名采用 Scintilla API 语义（例如 `GetText`、`SetLexer`、`BraceMatch`、`GetSCWindowHwnd`），但当前仓库本身没有形成到 Scintilla 控件的调用链。

## 6. 核心模块与真实行为

### 6.1 支持库入口和 ABI 元数据

`include_codestyleedit_header.h` 引入 `elib/lib2.h`、`elib/lang.h`、`elib/krnllib.h` 和命令 typedef，并声明：

- `g_ConstInfo_codestyleedit_global_var` 及其计数；
- `g_cmdInfo_codestyleedit_global_var`、函数指针表及其计数；
- `g_argumentInfo_codestyleedit_global_var`；
- `g_DataType_codestyleedit_global_var` 及其计数。

`codestyleedit_dllMain.cpp` 建立 `LIB_INFO g_LibInfo_codestyleedit_global_var`：

- GUID：`{E5E6A8E356A843bd94609DDD678BD6D8}`；
- 库版本：`2.2.0`；
- 要求易语言系统 `3.0`、系统核心支持库 `3.8`；
- 库名：`代码编辑框支持库`；
- 支持语言：GBK；
- 支持操作系统：`OS_ALL` 字段实际写入 `_LIB_OS(OS_ALL)`，但数据类型/命令自身均标为 Windows；
- 作者/联系信息来自源码静态字符串；
- 自定义数据类型 2 个、全局命令类别 0 个、命令数来自 `g_cmdInfo..._count`；
- `m_pfnNotify` 指向 `codestyleedit_ProcessNotifyLib_codestyleedit`；
- 依赖文件列表为 `NULL`。

`GetNewInf()` 返回 `LIB_INFO` 地址，并在返回前把第 18 条命令（索引 17）的英文名从宏表中的 `FindTextW` 改写为 `FindText`，注释说明这是为了避免宏名称转换造成兼容问题。`Source_codestyleedit.def` 只导出 `GetNewInf`。

### 6.2 命令声明、参数和分组

`codestyleedit_cmd_typedef.h` 用 `CODESTYLEEDIT_DEF(_MAKE)` 维护唯一的 184 条命令清单，索引连续为 `0..183`。宏同时供命令函数声明、函数指针数组、命令名数组和 `CMD_INFO` 生成使用，减少这些数组的索引漂移风险。

命令能力按源码清单可分为：

| 索引范围 | 主要能力 |
|---|---|
| 0–16 | 文本/风格文本读写、插入、保存点、字符与风格位 |
| 17–20 | 查找、搜索锚点、上/下一个匹配 |
| 21–50 | 剪贴板、撤消/重做、长度/行数、光标/选择/行列定位、滚动与行尾 |
| 51–65 | 行结束模式、旁注栏类型/宽度/掩码/鼠标响应/左右边距、折叠颜色 |
| 66–79 | 默认风格、风格清理、字体/大小/粗体/斜体/下划线/前景背景/字符集、文本尺寸 |
| 80–86 | 词法分析器、关键字、风格处理 |
| 87–107 | 行状态、TAB/缩进、括号匹配、高亮向导 |
| 108–119 | 标志定义、标志增删查和句柄操作 |
| 120–123 | 指示器风格、前景色 |
| 124–152 | 右键菜单、文档指针/文档引用、自动完成配置 |
| 153–161 | 用户列表、提示块和提示块颜色/高亮 |
| 162–178 | 可视行/文档行、折叠层级、显示/隐藏、词法属性 |
| 179–183 | Scintilla 窗口句柄、UTF-8/字节位置转换、行底线 |

`codestyleedit_cmdInfo.cpp` 登记 166 个参数记录，索引为 `0..165`；参数类型主要是 `SDT_INT`、`SDT_BOOL`、`SDT_TEXT`、`SDT_BIN`、`SDT_BYTE`，并使用 `AS_HAS_DEFAULT_VALUE`、`AS_DEFAULT_VALUE_IS_EMPTY`、`AS_RECEIVE_VAR`、`AS_RECEIVE_VAR_ARRAY` 等易语言参数标志。

关键的真实实现结论：`codestyleedit_cmdDef.cpp` 有 184 个 `CODESTYLEEDIT_EXTERN_C void` 入口，源码中 `pRetData` 只出现在 184 个函数签名里，没有 `pRetData->...` 写入，没有 `SendMessage`、`SCI_*` 或窗口句柄调用。每个函数最多把参数复制到 `arg1`、`arg2` 等局部变量，然后直接结束。因此当前版本命令调用链在命令实现层是空操作/未定义返回状态，不能据此声称这些 API 已可用。

### 6.3 CodeStyleEdit 数据类型

`codestyleedit_dtType.cpp` 的 `g_DataType_codestyleedit_global_var` 注册两个数据类型：

1. `代码编辑框` / `CodeStyleEdit`
   - 标志：`_DT_OS(__OS_WIN) | LDT_WIN_UNIT`；
   - 绑定 184 条命令索引；
   - 10 个事件；
   - 26 个属性（8 个易语言固定窗口属性 + 18 个组件属性）；
   - 绑定 `codestyleedit_GetInterface_CodeStyleEdit` 组件交互分发函数。
2. `代码编辑框常量` / `CodeEditConst`
   - 标志：`_DT_OS(__OS_WIN) | LDT_ENUM`；
   - 无命令、属性或事件；
   - 枚举成员表源码末项索引为 `389`，即按连续索引口径约 390 个常量，内容覆盖查找方式、词法分析器和多种语言风格常量。

组件事件共有 10 个：`更新界面`、`处理新字符`、`保存点开始`、`保存点结束`、`错误写操作`、`旁注栏被单击`、`显示完成`、`用户列表被选择`、`提示块被单击`、`自动完成项被选择`。事件参数表登记 9 个参数槽，包含接收字符、功能键状态、单击位置、旁注号、列表类型、文本、提示块位置等。

组件属性除固定的左/顶/宽/高/标记/可视/禁止/鼠标指针外，还登记：只读模式、滚动条、空白区域填充及颜色、光标类型、行结束模式、显示行结束、选择色、光标色/行色/闪烁周期/宽度、编码、缩进向导和自动换行。

### 6.4 组件接口回调

`codestyleedit_GetInterface_CodeStyleEdit(INT nInterfaceNO)` 以接口号分发回调：

- `ITF_CREATE_UNIT`：返回 `codestyleedit_ControlCreate_CodeStyleEdit`；但该函数只初始化 `HUNIT hUnit = 0` 并返回 0，源码有 `TODO`，没有创建窗口/Scintilla 控件。
- `ITF_PROPERTY_UPDATE_UI`：固定返回 `TRUE`，没有按属性或状态判断。
- `ITF_DLG_INIT_CUSTOMIZE_DATA`：把 `*pblModified` 设为 `false` 后返回 `FALSE`，没有定制数据。
- `ITF_NOTIFY_PROPERTY_CHANGED`：只留下 `case 0` 模板分支，最终返回 `false`。
- `ITF_GET_ALL_PROPERTY_DATA`：直接返回 0。
- `ITF_GET_PROPERTY_DATA`：只有模板 `switch`，默认返回 `false`，当前可见分支最后返回 `true`，没有填充属性值。
- `ITF_IS_NEED_THIS_KEY`：固定返回 `FALSE`。
- `ITF_GET_NOTIFY_RECEIVER`：返回 `codestyleedit_PropNotifyReceiver_CodeStyleEdit`；该函数只处理 `NU_GET_CREATE_SIZE_IN_DESIGNER` 的空模板，默认/最终返回 0。
- 图标数据、语言转换、消息过滤接口没有注册实现，分支直接落到 `NULL`。

### 6.5 系统通知与公共辅助层

`elib/fnshare.cpp/.h` 提供支持库公共通知层：

- `NotifySys`：通过易语言系统回调发送消息；
- `ProcessNotifyLib`：接收 `NL_SYS_NOTIFY_FUNCTION`，保存系统通知函数，并初始化调试/编译版本信息；
- `SetUserSysNotify`：登记用户通知回调；
- `ealloc`/`efree`：通过易语言系统申请/释放内存；
- `CloneTextData`、`CloneBinData`、数组/数据类型辅助函数。

`codestyleedit_dllMain.cpp` 在 `NL_SYS_NOTIFY_FUNCTION` 时调用上述 `ProcessNotifyLib`，其他通知如资源释放、卸载、IDE ready、右键菜单等目前只保留空分支。`elib/untshare.h` 和 `PublicIDEFunctions.h` 是通用支持库/IDE 模板和常量，并未被本项目填充为完整业务组件。

## 7. 依赖边界

| 类别 | 事实 |
|---|---|
| 语言 | C/C++，源码以易语言支持库 SDK 风格组织 |
| 编译器 | Visual Studio 工程，`PlatformToolset=v141` |
| 目标平台 | Windows；组件和命令元数据均使用 `__OS_WIN` |
| SDK | `WindowsTargetPlatformVersion=10.0.15063.0` |
| 系统 API | Windows 头/窗口/句柄/消息/字体/内存等；由 `elib/lib2.h` 等 SDK 头提供 |
| 易语言 SDK | 仓库内 `elib/`，提供 ABI 数据结构、系统通知、组件接口和公共辅助 |
| 第三方库 | 工程文件未声明额外链接库；仓库未携带 Scintilla 源码/库 |
| 运行宿主 | 易语言 IDE/编译器/运行时负责加载 `.fne`、提供通知函数和窗口环境 |
| 发行形态 | 动态支持库 `.fne`；另有静态库项目供静态编译整合 |

命令描述明显借鉴 Scintilla 编辑控件 API，但当前源码没有真正的 Scintilla 依赖声明或消息调用；“底层是 Scintilla”只能作为元数据/命名线索，不能作为本仓库已完成的实现事实。

## 8. 测试与验证现状

- 仓库内没有测试文件、测试工程、CI 配置或示例程序。
- 本次没有安装依赖、没有构建、没有启动 DLL/易语言宿主；目标工程是 Windows/Visual Studio 工程，当前现场为 macOS，且任务边界要求只读建档。
- 已完成的静态取证包括：Git 工作树/远程/本地与远程提交核对、Git 文件树盘点、解决方案与两个 `.vcxproj` 阅读、`.def` 阅读、全部顶层 C/C++ 源码的文本读取、`elib` 关键头文件读取、命令/参数/组件元数据计数和空实现特征核对。
- 因未执行 Windows 构建，以下事项仍不能宣称通过：编译器语法/ABI 兼容、链接与导出、`.fne` 加载、静态编译整合、组件创建、事件回调、184 条命令实际行为。

## 9. 风险、缺口与后续复核点

### 已由源码直接确认

1. **功能实现缺口（高）**：184 个命令入口没有任何窗口/控件调用和返回值写入；组件创建和属性数据接口也为模板桩。
2. **x64 工程宏缺口（高）**：动态库与静态库的 x64 配置均缺 `__E_FNENAME=codestyleedit`；静态库 x64 还缺 `__E_STATIC_LIB`。`elib/lib2.h` 明确要求先定义 `__E_FNENAME`。
3. **x64 DLL 导出/后缀配置缺口（中高）**：动态库 x64 配置没有 `TargetExt=.fne` 和 `Source_codestyleedit.def`，固定入口是否导出、产物是否符合易语言支持库命名未确认。
4. **没有测试与宿主验证（高）**：没有任何自动化回归来保护命令索引、参数偏移、属性/事件计数或 ABI。
5. **依赖边界不完整（中高）**：命令语义指向 Scintilla，但源码库没有 Scintilla 实现、头文件或链接库，实际控件来源未登记。
6. **通知与组件生命周期未实现（高）**：资源释放、卸载、IDE 通知、窗口创建、属性序列化等回调大多为空或默认返回。
7. **返回值未定义（高）**：命令元数据声明了多种返回类型，但命令函数从不写 `pRetData`，运行时返回值行为不能视为契约已实现。

### 需要后续复核但当前核对不做

- 在 Windows + Visual Studio 对 Win32 Debug/Release 和 x64 Debug/Release 分别编译，记录真实错误并确认 `.fne` 导出表；
- 明确本项目预期接入的 Scintilla 版本、控件创建方式、窗口句柄/文档指针保存方式和消息分发层；
- 依据 `CODESTYLEEDIT_DEF` 逐条补齐命令调用/返回/内存释放，再以易语言宿主做最小真实冒烟；
- 依据 26 个属性与 10 个事件实现组件数据存储、设计时序列化、运行时实时取值、事件通知和资源释放；
- 为命令索引、参数偏移、数据类型元数据和 x64 工程配置增加可在 Windows 上运行的验证。

## 10. 后续：编辑器/文本缓冲、配置、文件、插件与命令资源的底座映射

当前核对只把源码已经暴露的边界映射到“开发工具—支持库—模块库—运行核心”的职责面，不把未来设计写成当前实现。结论基线仍是：`codestyleedit` 目前是易语言支持库的声明层/接口骨架；`codestyleedit_cmdDef.cpp` 的 184 个入口没有实际控件调用或返回值写回，`codestyleedit_ControlCreate_CodeStyleEdit()` 返回 0，属性/事件/释放通知也大多是模板分支。因此，下面带“建议/应归”的内容属于后续底座裁决，不是本仓库已经完成的功能。

### 10.1 能力事实与归属裁决表

| 能力面 | 源码事实证据 | 本仓库当前状态 | 底座归属裁决 |
|---|---|---|---|
| 编辑器/文本缓冲 | `codestyleedit_cmd_typedef.h:12-195` 登记取/置/插入/查找/撤消/行列/词法/折叠/自动完成等 184 个命令；`codestyleedit_cmdDef.cpp:3-1545` 仅提取 `pArgInf` 参数 | 只有命令语义和参数元数据，没有文本缓冲、光标、撤消栈、文档状态或 Scintilla 消息调用 | **模块库**负责“编辑器文本缓冲”领域流程和统一位置/编码契约；**支持库**只提供具体控件/缓冲 provider 薄适配；**运行核心**持有组件句柄、文档引用、租约和释放证据 |
| 配置/属性 | `codestyleedit_dtType.cpp:178-193` 登记 26 个属性；`codestyleedit_PropChanged_CodeStyleEdit():672-691` 只有 `case 0` 模板；`codestyleedit_PropGetDataAll_CodeStyleEdit():693-698` 返回 0 | 没有属性快照、默认值合并、配置文件解析或持久化；设计时/运行时实时值也未实现 | **支持库**提供配置文件/字节解析和原子读写；**模块库**负责编辑器配置合并、校验、默认值和应用顺序；**运行核心**负责快照、锁、原子替换、崩溃恢复，不让模块各自持有裸文件句柄 |
| 文件读写 | `codestyleedit_dllMain.cpp:83-86` 的 `m_szzDependFiles=NULL`；全仓库源码无 `CreateFile`/`fopen`/`ifstream`/`ofstream`/`LoadLibrary` 等调用；命令清单没有打开/保存文件实现 | 没有路径解析、权限检查、临时文件、原子替换、部分写入回滚或恢复 | 原子文件能力归**支持库/文件系统**；“加载文本→绑定缓冲→保存/刷新配置”的流程归**模块库**；事务、租约、临时目录清理和崩溃恢复归**运行核心** |
| 插件/IDE 扩展 | `codestyleedit_dllMain.cpp:68-81` 的 `m_pfnRunAddInFn=NULL`、`m_szzAddInFnInfo=NULL`；`m_dwState` 未含 `LBS_IDE_PLUGIN`；`NL_IDE_READY`、`NL_RIGHT_POPUP_MENU_SHOW`、`NL_ADD_NEW_ELEMENT` 分支 `155-176` 为空 | 没有插件注册、菜单注入、命令冲突检测、权限隔离或卸载协议 | 当前应**隔离/废弃为可用能力**；若需求确认，注册/契约发现归**开发工具**，插件 provider 归**支持库**，领域编排归**模块库**，加载、权限、超时、卸载和进程隔离归**运行核心**，禁止把插件回调散落到各命令桩 |
| 命令注册 | `CODESTYLEEDIT_DEF` 是 `codestyleedit_cmd_typedef.h:12-196` 的单一 184 项清单；它被 `codestyleedit_cmdInfo.cpp:295-305` 生成 `CMD_INFO`，被 `codestyleedit_dllMain.cpp:26-29/96-100` 生成函数指针和静态函数名数组 | 注册元数据链路真实存在，但没有注册后的能力实现校验；`GetNewInf():89-94` 还在返回前改写索引 17 的英文名 | **开发工具**保留“单一清单→契约/搜索/校验产物”的编译与静态门禁；运行时只保留一个能力注册表/调用器；历史别名只在该入口归一化，不能由消费者各自翻译 |
| 命令执行资源 | ABI 的 `PFN_EXECUTE_CMD` 只有 `pRetData,nArgCount,pArgInf`（`elib/lib2.h:1234-1239`），命令描述包含文档指针/引用和自动完成等资源语义（`codestyleedit_cmd_typedef.h:137-145`） | 没有执行上下文、取消令牌、截止时间、句柄校验、资源预算、错误信封或释放回调 | **运行核心**提供统一执行上下文、句柄/文档引用、取消/超时、资源监督和结果证据；**模块库**把一次命令转成领域操作；**支持库**不得暴露 provider 对象穿透模块边界 |

特别注意：命令说明中的“创建文档/增加文档引用/释放文档引用”（索引 127-129）以及“取消自动完成”（索引 131）只是**声明文本**；源码入口仍是空函数，不能据此证明文档引用计数、自动完成窗口或取消逻辑已经存在。

### 10.2 L0-L4 分层落点

```text
L4 项目适配层 / IDE 使用方
  绑定宿主版本、配置来源、项目路径、权限、历史中文/英文命令别名；不持有 provider 裸句柄
        |
L3 模块库：编辑器文本模块 / 文件加载保存流程 / 配置应用流程 /（需求确认后）插件命令编排
  统一位置、编码、错误和事件；只调用支持库公开能力，不直连 Win32、Scintilla 或文件系统
        |
L2 支持库：文本控件或缓冲 provider / 配置解析 / 文件原子读写 / 插件协议适配
  一个能力 id 一个契约 owner；只做薄适配、输入边界和结果转换，不复制模块流程
        |
L1 运行核心：能力调用器、句柄与文档引用、租约、取消/超时、资源监督、崩溃恢复、证据
  统一创建/转移/释放；不让命令入口自行 new、持有或旁路释放资源
        |
L0 易语言宿主 ABI / Windows / 外部控件或系统 API
  `GetNewInf`、`LIB_INFO`、`PFN_EXECUTE_CMD`、`PFN_CREATE_UNIT`、系统通知和实际控件/文件 API
```

分层规则不是把本仓库的每个 C++ 文件机械搬入某个目录：

- **开发工具**只负责从声明生成/检查命令契约、参数偏移、能力搜索数据、版本兼容和注册完整性；不在运行时读写编辑器缓冲。
- **支持库**负责“能调用什么 provider”，例如文本缓冲 provider、配置解析器、文件系统 provider；公开返回统一结果和错误码，不把 `HWND`、Scintilla 文档指针、文件描述符直接交给模块外部。
- **模块库**负责“一个领域流程如何完成”，例如“打开文件→解码→创建/绑定文档→写入缓冲→应用词法配置→返回编辑器状态”；同一流程切换 provider 时不复制第二套流程。
- **运行核心**负责“资源是否有资格被使用以及何时结束”：句柄/引用计数/租约/锁/临时文件/线程或子进程/回调都必须有 owner、转移记录和四终态释放路径。
- **项目适配层**只绑定宿主差异、路径、配置和权限；它可以把旧的 `FindTextW`/`FindText` 或中文动作名归一化，但不能另建命令表、另调第三方或绕过唯一调用器。

### 10.3 唯一注册与执行链

#### 当前源码中已经存在的唯一元数据链

```text
codestyleedit_cmd_typedef.h::CODESTYLEEDIT_DEF（184 项单一清单）
  ├─> codestyleedit_cmdInfo.cpp::CMD_INFO + ARG_INFO
  ├─> codestyleedit_dllMain.cpp::g_cmdInfo...fun（函数指针数组）
  ├─> codestyleedit_dllMain.cpp::g_cmdNames...（静态编译函数名）
  └─> codestyleedit_dllMain.cpp::g_LibInfo... -> GetNewInf
              └─> 易语言宿主按命令索引调用 codestyleedit_cmdDef.cpp 入口
                         └─> 当前只读 pArgInf，链路在此终止
```

这条链应吸收为“注册声明的单一事实源”模式，但不能吸收其空执行语义。`GetNewInf()` 对索引 17 进行运行时英文名改写（`codestyleedit_dllMain.cpp:89-94`），说明兼容别名必须集中在唯一入口处理；未来不得让模块、适配层和前端各自维护 `FindTextW`/`FindText` 映射。

#### 目标底座中的唯一能力调用链（后续装配约束）

```text
L4 项目适配层：版本/路径/权限/历史别名
  → L3 模块库公开入口：编辑器加载、编辑、保存、配置应用或插件命令流程
  → 唯一能力调用器/能力注册表：能力 id 归一化、契约、授权、预算、幂等键
  → L2 支持库公开能力：文本缓冲/配置解析/文件原子写/插件协议 provider
  → L1 运行核心：句柄绑定、文档引用、租约、取消/超时、提交/回滚、证据
  → L0 Windows/控件/文件 API 或受管独立进程
  → 统一结果/事件/状态投影
  → finally 释放句柄、引用、临时文件、回调和进程组
```

唯一链路的硬约束：

1. 一个原子能力只有一个规范能力 id、一个注册 owner、一个公开入口；`CODESTYLEEDIT_DEF` 的“同一清单生成多种视图”可以保留，但不能再出现第二张手写命令表。
2. 模块库只编排领域流程，不能直接调用 `SendMessage`/Scintilla、`CreateFile` 或插件 SDK；当前源码没有这些调用，后续实现也必须先进入支持库边界。
3. provider 失败必须转换为统一错误，不得由每个命令各自决定“返回空文本/0/-1/假”；当前命令声明中虽写了这些失败语义，但当前入口没有写 `pRetData`，只能标为未实现。
4. 注册、执行、结果和释放是同一条可审计链；不能注册时一套 owner、执行时偷偷 fallback 到另一 provider、释放时由调用方猜测句柄归属。

### 10.4 失败、取消与释放矩阵

| 阶段/资源 | 必须识别的失败 | 主动取消/超时 | 正常/失败/取消/崩溃的释放要求 | 当前源码证据与结论 |
|---|---|---|---|---|
| ABI 加载/注册 | `GetNewInf` 为空、格式/GUID/版本不兼容、命令索引或参数偏移不一致 | 加载尚未完成时不得暴露半注册表 | 丢弃临时注册表；不留下函数名数组、回调或版本锁 | `GetNewInf` 直接返回静态 `LIB_INFO`，无校验；未知通知才返回 `NR_ERR`（`codestyleedit_dllMain.cpp:103-180`）。当前为**未验证/部分实现** |
| 组件创建/句柄绑定 | 父窗口无效、属性数据损坏、宿主/控件 provider 不可用 | 创建阶段取消应销毁已创建的窗口/文档并返回空句柄 | `HUNIT`、窗口、文档引用、事件接收者必须由运行核心登记并反向释放 | `PFN_CREATE_UNIT` 的契约明确成功/失败（`elib/lib2.h:553-558`），但 `ControlCreate` 固定返回 0（`codestyleedit_dtType.cpp:636-653`） |
| 文本缓冲命令 | 空句柄、范围越界、只读写入、编码非法、provider 缺失、并发版本冲突 | 在 provider 调用前检查取消；已启动操作需可中止或返回“取消”，不可把取消伪装成成功 | 临时文本/字节集、锁、借用引用和事件载荷必须在四终态释放 | `cmdDef` 只复制参数；无 `pRetData->`、无控件调用（`codestyleedit_cmdDef.cpp` 全文件）。取消契约不存在，不能宣称支持 |
| 配置读取/应用 | 文件不存在、路径逃逸、权限不足、编码/格式错误、字段不兼容、部分应用 | 解析可取消；应用采用快照+原子提交，取消不得留下半配置 | 文件句柄、临时快照、锁和旧配置引用均在 finally 清理；失败保持旧配置 | `PropChanged`/`PropGetDataAll` 为模板，仓库无配置/文件 API；当前为**待核** |
| 文件保存/原子提交 | 磁盘满、写权限、短写、替换失败、版本冲突 | 超时/取消时删除临时文件，旧文件不得被半写覆盖 | 临时文件、文件句柄、锁、快照和回滚证据必须清理/可恢复 | `LIB_INFO.m_szzDependFiles=NULL`，全仓无文件 I/O；当前不能把“保存点”命令当文件保存 |
| 插件/命令注册 | 重复能力 id、版本不兼容、未授权、provider 不可用、命令名冲突 | 注册事务取消则回滚整批，不得残留部分菜单/回调 | 菜单项、回调、动态库句柄/独立进程和注册租约必须反注册；卸载幂等 | `m_pfnRunAddInFn=NULL`，相关通知空分支；当前无插件能力 |
| 运行/宿主卸载 | provider 崩溃、回调异常、宿主退出、DLL 卸载顺序错误 | 取消执行后等待/强杀受管进程，回收进程组和队列 | 正常、业务失败、取消/超时、宿主崩溃均清理句柄、回调、文档引用和临时物 | `DllMain` 的 attach/detach 为空；`NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NR_DELAY_FREE` 均空（`codestyleedit_dllMain.cpp:7-24,138-151`） |

当前唯一能确认的失败返回主要是 ABI 模板层：未知接口返回 `NULL`（`codestyleedit_dtType.cpp:571-634`）、未知系统通知返回 `NR_ERR`（`codestyleedit_dllMain.cpp:177-180`）、组件创建返回 0、属性部分返回 `FALSE`。这些返回不能替代领域错误码；尤其命令入口没有写 `pRetData`，不能把空值解释为“合法空文本”、0 解释为“合法句柄”或 -1 解释为“真实查找失败”。

### 10.5 资源 owner 与 L0-L4 生命周期

| 资源 | 创建/取得点 | 持有 owner | 转移边界 | 四终态释放/恢复 | 当前实现等级 |
|---|---|---|---|---|---|
| `HUNIT`/窗口句柄 | L0 `PFN_CREATE_UNIT` → L1 句柄登记 | 运行核心；模块只持有不透明句柄 | 通过模块公开入口传递句柄 id，不传裸窗口对象 | 正常/失败/取消销毁窗口；崩溃由运行核心按 owner/租约回收 | `ControlCreate` 返回 0，未创建；L0 契约存在、L1 实现缺失 |
| 文档指针/引用计数 | 文本 provider 创建或宿主绑定 | 运行核心文档表 | `创建文档`/`AddrefDocument`/`ReleaseDocument` 只能走唯一调用器 | 引用归零释放；失败/取消回滚新增引用；崩溃扫描死亡 owner | 仅 `cmd_typedef.h:127-129` 有声明文本，无实现 |
| 文本/风格缓冲 | provider 创建/借用 | 支持库 provider + L1 句柄表 | 模块只取得统一快照/结果，不拿内部指针 | 释放借用视图、临时转换缓冲、撤消事务；取消回滚未提交编辑 | 无缓冲对象、无 `SCI_*`/`SendMessage` |
| 配置快照/临时文件 | 支持库读取，L1 建立操作目录 | 运行核心事务；模块只持有快照 id | 原子提交前不得转为权威路径 | 成功 rename/commit；失败/取消删临时物；崩溃恢复旧快照 | 仓库无文件 I/O，属待核设计 |
| 命令注册表/函数指针 | L0 加载 `LIB_INFO`，开发工具生成产物 | 运行核心唯一注册表；开发工具持有源声明 | 注册事务完成后只读；别名在入口归一化 | 注册失败丢弃整批；卸载移除 owner；禁止悬空函数指针 | 元数据数组真实存在；执行实现空桩 |
| 系统通知回调 | `NL_SYS_NOTIFY_FUNCTION` → `fnshare.cpp::ProcessNotifyLib` | 当前是静态全局 `s_pfnNotifySys` | 仅宿主通知层可注入；不得向模块扩散 | `NL_FREE_LIB_DATA`/卸载时应清零并拒绝后续调用；异常应隔离 | `ProcessNotifyLib` 只保存指针（`elib/fnshare.cpp:24-37`），释放分支为空，存在悬空回调风险 |
| 用户通知回调 | `SetUserSysNotify` 设置 `s_pfnuserNotifySys` | 当前是静态全局 | 只能由统一宿主边界设置 | 卸载/取消/崩溃必须清零；调用前检查 owner/代次 | `SetUserSysNotify` 只赋值并返回 `ProcessNotifyLib`（`elib/fnshare.cpp:67-71`），无清理 |

因此，**释放责任不能放在 184 个命令函数各自猜测**。未来应由运行核心建立操作上下文和资源表，命令入口只提交能力请求；所有 provider 返回借用数据、创建数据、回调和临时文件都必须标明“借用/转移/新建”及对应释放函数。

### 10.6 后续复用/升级/新建/废弃裁决

- **吸收**：`CODESTYLEEDIT_DEF` 作为“一个声明清单生成命令元数据、函数表、静态函数名”的单一事实源；`LIB_INFO`/`PFN_EXECUTE_CMD`/`PFN_CREATE_UNIT` 的 ABI 分层；`elib/fnshare.cpp` 的系统通知转发思想。吸收时必须补统一结果、能力契约、版本兼容和释放责任，不能吸收空实现。
- **升级现有支持库**：把“文本/风格缓冲 provider”“配置解析”“文件原子读写”纳入既有支持库公开能力；能力 id、参数、返回、错误、超时、取消和资源释放由支持库契约固定，第三方/Windows 控件差异留在 provider。
- **升级现有模块库**：建立一个编辑器领域模块，统一“配置→文件→缓冲→事件/结果”流程；查找、撤消、自动完成、折叠、编码位置等命令只作为同一模块的子能力，不建立第二套编辑器内核。
- **运行核心落点**：句柄/文档引用、租约、取消/超时、临时文件、原子提交、进程组/回调清理、崩溃恢复和证据；执行资源不由支持库静态全局变量长期持有。
- **废弃/隔离**：把当前命令注释当作已实现 API、把“保存点”当作文件保存、把 `m_pfnRunAddInFn`/空通知分支当作插件支持、让模块直连 Scintilla/Win32/文件 API、让消费者各维护 `FindTextW` 别名，均与单链路原则冲突。
- **待核**：实际 Scintilla 版本和控件来源；`HUNIT` 与窗口/文档指针的真实 owner；配置格式及文件编码/原子保存语义；插件是否为真实需求；宿主是否提供可取消/超时上下文；Windows 下 `.fne` 加载和事件回调顺序。没有这些证据，不建立生产底座实现。

### 10.7 L0-L4 验收契约（后续实现的门禁，不是当前核对通过项）

| 等级 | 必须验证 | 当前核对状态 |
|---|---|---|
| L0 ABI | Windows 宿主加载 `GetNewInf`；GUID/版本/命令数/参数偏移/导出一致；未知接口和通知有稳定错误 | 仅源码静态核对；未构建、未加载 |
| L1 运行核心 | 真实 `HUNIT`/文档引用登记；命令执行有上下文、授权、预算、取消、超时和四终态释放；崩溃后无悬空回调/句柄 | 当前没有运行核心接线，未验证 |
| L2 支持库 | provider 缺失、非法范围、只读、编码错误、文件权限、重复注册均返回统一错误；借用/新建数据的释放可观测 | 当前没有 provider/错误结果实现，未验证 |
| L3 模块库 | 真实“配置→文件→文本缓冲→编辑事件→保存/回滚”单链路；模块不直连 provider 内部对象；取消不产生部分写入 | 当前只有元数据声明，未验证 |
| L4 项目适配/宿主 | 版本/路径/权限/历史别名绑定；IDE 卸载、重复加载、宿主崩溃、重启恢复；无第二命令表/旁路文件写入 | 当前插件/配置/文件接线为空，未验证 |

当前核对可落盘的结论是“如何归属”和“哪些声明不能算实现”，不是“已完成编辑器底座”。

## 11. 许可证与边界说明

根目录 `LICENSE` 是 MIT License，版权行写明 `Copyright (c) 2022 精易科技`。但 `elib/*.h` 内含易语言作者吴涛的版权/授权限制声明（例如 `fnshare.h`、`untshare.h`），该声明与根目录 MIT 文件同时存在；不能仅凭根目录 LICENSE 就推断 `elib` SDK 头文件的独立授权边界。后续复用或发布前应按文件来源分别核对许可证。

## 12. 证据路径

- 支持库入口与 ABI：`include_codestyleedit_header.h`、`codestyleedit_dllMain.cpp`、`Source_codestyleedit.def`
- 命令单一清单：`codestyleedit_cmd_typedef.h`
- 命令参数/元数据：`codestyleedit_cmdInfo.cpp`
- 命令实现现状：`codestyleedit_cmdDef.cpp`
- 组件、属性、事件、枚举和接口：`codestyleedit_dtType.cpp`
- 公共支持库通知：`elib/fnshare.cpp`、`elib/fnshare.h`
- ABI 结构和接口常量：`elib/lib2.h`、`elib/mtypes.h`、`elib/krnllib.h`、`elib/lang.h`、`elib/untshare.h`、`elib/PublicIDEFunctions.h`
- 构建拓扑：`codestyleedit.sln`、`codestyleedit.vcxproj`、`codestyleedit_static/codestyleedit_static.vcxproj`
- 版本与远程：`.git/`、`git remote origin`（远程 URL 如上）
- 许可证：`LICENSE`

**后续结论**：当前核对已把编辑器/文本缓冲、配置、文件、插件、命令注册与执行资源分别落到 L0-L4 的职责边界，并固定唯一注册/调用链、失败/取消/正常释放/崩溃清理要求；源码事实仍是支持库声明层和接口骨架，尚未形成可验证的代码编辑框运行实现。后续只能围绕 Windows 构建配置、Scintilla 依赖来源、组件创建链、文件/配置真实语义和命令执行链补证，不应从当前命令说明反推功能已完成。
