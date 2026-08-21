# script 架构建档

## 1. 项目定位与范围

`script` 是一个面向 Windows 易语言支持库 ABI 的 Visual C++ 工程。它声明了一个名为“脚本语言支持组件”的支持库，目标描述是为 JScript、VBScript 等脚本语言提供易语言命令和一个“脚本组件”。当前仓库更接近**支持库骨架/模板**：库元数据、命令签名、组件属性和通知入口已经登记；真正的脚本引擎调用、组件实例、属性持久化和返回值填充尚未实现。

本文件只记录当前源码与工程能够直接证明的事实。状态采用：

- **已实现**：源码中存在可执行逻辑或完整静态登记，未等同于已在易语言宿主中验证。
- **仅声明**：有原型、元数据或接口分派，但实现为空、返回占位值或没有完成数据处理。
- **未验证**：仓库没有测试/运行证据，不能仅凭工程配置或注释判定成功。

## 2. 总体流程

```text
易语言 IDE/运行时
      │
      │ 加载 .fne，按固定名字查找 GetNewInf
      ▼
script.dll ── GetNewInf() ──► LIB_INFO
                                  │
             ┌────────────────────┼─────────────────────┐
             ▼                    ▼                     ▼
      LIB_DATA_TYPE_INFO       CMD_INFO[]          LIB_CONST_INFO[]
       “脚本组件”                 4 条命令              1 个常量
             │                    │                     │
             │                    │                     └─ NoTimeOut
             │                    └─ 命令索引 0..3 ──► PFN_EXECUTE_CMD[]
             │                                            │
             │                                            └─ Execute / CalculateExp /
             │                                                Reset / Run（当前为空实现）
             │
             └─ PFN_GET_INTERFACE
                  ├─ 创建组件（返回 0，占位）
                  ├─ 属性更新（恒真）
                  ├─ 定制属性对话框（未实现）
                  ├─ 属性变更（未实现）
                  ├─ 获取全部/单个属性（未实现或空数据）
                  ├─ 按键询问（恒假）
                  └─ 设计器通知/默认尺寸（未实现）

易语言通知 ──► script_ProcessNotifyLib_script
                    ├─ NL_SYS_NOTIFY_FUNCTION
                    │    └─ fnshare::ProcessNotifyLib
                    │         ├─ 保存系统通知函数指针
                    │         └─ 查询程序类型，写入 isDebug 状态
                    └─ 其它通知：当前仅返回默认结果或错误
```

## 3. 版本与 Git 基线

| 项目 | 事实 |
|---|---|
| 本地路径 | `/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/script` |
| 分支 | `master` |
| HEAD | `df98374c5e48939ce7e2916b78818b3ae21ecbac` |
| 提交 | `初始化仓库` |
| 提交时间 | `2022-12-19 16:13:11 +0800` |
| 作者 | `精易科技` |
| 远程 | `https://gitee.com/JYtechnology/script.git` |
| 远程跟踪 | `origin/master`，`origin/HEAD` 指向该分支 |
| 标签 | 无 |
| 工作树基线 | 建档前 `git status --short --branch` 为 `## master...origin/master`，无已有工作树改动 |
| 历史形态 | Git 输出标记为 `grafted`，当前本地可见历史只有该初始化提交，不能据此推断完整上游历史 |

仓库内没有 `README`、`AGENTS.md`、测试文件、CI 配置或旧 `细探*.md`；也没有既有 `ARCHITECTURE.md`。当前核对不删除任何旧细探文件。

## 4. 目录与工程地图

```text
script/
├── script.sln                         # VS 解决方案，包含动态库与静态库项目
├── script.vcxproj                     # 动态链接支持库项目，目标扩展名 Win32 为 .fne
├── Source_script.def                  # 动态库导出表，仅导出 GetNewInf
├── script_static/
│   ├── script_static.vcxproj          # 静态库项目，复用上层源码
│   ├── script_static.vcxproj.filters
│   └── script_static.vcxproj.user
├── include_script_header.h            # 公共包含入口、全局表 extern、命令声明展开
├── script_cmd_typedef.h               # SCRIPT_DEF X-macro：4 条命令的唯一登记源
├── script_cmdDef.cpp                  # 4 个命令执行函数；当前均为空/占位
├── script_cmdInfo.cpp                 # 命令参数与 CMD_INFO 元数据
├── script_const.cpp                   # 预定义常量元数据
├── script_dtType.cpp                  # “脚本组件”类型、属性与接口回调
├── script_dllMain.cpp                 # DllMain、LIB_INFO、GetNewInf、库通知入口
└── elib/
    ├── lib2.h                         # 易语言支持库 ABI：LIB_INFO、CMD_INFO、数据类型、通知号等
    ├── fnshare.h/.cpp                 # 通知转发、宿主内存辅助、调试版本状态
    ├── mtypes.h                       # 基础类型/句柄/宏兼容定义
    ├── lang.h                         # GBK/英语/BIG5/SJIS 语言版本常量
    ├── krnllib.h                      # 系统核心支持库类型/版本常量
    ├── untshare.h                      # 窗口单元辅助函数、属性/事件掩码宏
    └── PublicIDEFunctions.h            # IDE 功能号与编辑器数据类型定义；本项目未实际调用
```

工程文件共登记两个目标：`script` 动态库与 `script_static` 静态库。动态项目编译 6 个 `.cpp`，静态项目同样复用 `elib/fnshare.cpp` 与 5 个根目录 `.cpp`；两者均引用 `elib` 公共头和两个 `script` 头文件（`script.vcxproj:21-42`、`script_static/script_static.vcxproj:21-38`）。

## 5. 模块职责与实现状态

### 5.1 命令定义与命令实现

| 模块 | 职责 | 状态 | 证据 |
|---|---|---|---|
| `script_cmd_typedef.h` | 用 `SCRIPT_DEF(_MAKE)` 一次定义命令索引、中文/英文名、说明、Windows 标志、返回类型、参数数量和参数数组起点 | 已实现（登记层） | `script_cmd_typedef.h:11-16` |
| `include_script_header.h` | 引入 ABI；声明常量/命令/参数/数据类型全局表；再次展开 `SCRIPT_DEF` 生成 4 个命令函数原型 | 已实现（声明层） | `include_script_header.h:3-24` |
| `script_cmdInfo.cpp` | 建立 4 个参数描述项及 `CMD_INFO[]`，计算数量 | 已实现（元数据层） | `script_cmdInfo.cpp:5-42` |
| `script_cmdDef.cpp` | 实现 `Execute`、`CalculateExp`、`Reset`、`Run` | 仅声明/占位 | `script_cmdDef.cpp:5-34`；函数只读取参数或为空，没有脚本引擎调用、错误信息写入或返回值写入 |
| `script_dllMain.cpp` 的 `g_cmdInfo_script_global_var_fun` | 按同一 X-macro 顺序生成函数指针表 | 已实现（绑定层） | `script_dllMain.cpp:26-29` |

4 条命令实际登记如下：

| 索引 | 易语言名 | 英文符号 | 返回类型 | 参数 | 备注 |
|---:|---|---|---|---|---|
| 0 | 执行 | `Execute` | `SDT_BOOL` | `脚本代码: SDT_TEXT` | 计划执行代码并返回成功/失败；实现未填返回值 |
| 1 | 计算表达式 | `CalculateExp` | `SDT_TEXT` | `表达式: SDT_TEXT` | 计划计算并返回文本；实现未填返回值 |
| 2 | 清除 | `Reset` | `_SDT_NULL` | 无 | 计划清除上次代码/过程；函数为空 |
| 3 | 运行 | `Run` | `SDT_TEXT` | `过程或函数名: SDT_TEXT`、`参数: _SDT_ALL` | 允许追加参数；实现只取指针，不调用过程 |

`Run` 的最后一个参数设置 `AS_DEFAULT_VALUE_IS_EMPTY | AS_RECEIVE_ALL_TYPE_DATA`，这只证明编辑器/调用协议的参数约束，不证明运行时已实现数组/非数组处理（`script_cmdInfo.cpp:18-23`）。所有命令 `_shtCategory=-1`，因此按 `CMD_INFO` 约定属于“脚本组件”的对象命令，而不是全局命令（`script_cmd_typedef.h:13-16`、`elib/lib2.h:302-305`）。

### 5.2 常量

`script_const.cpp` 声明 1 个数值常量：中文名 `无超时`、英文名 `NoTimeOut`，数值字段为 `NULL`，说明为“用于设置脚本组件的超时属性，使脚本引擎的执行无超时”（`script_const.cpp:4-18`）。常量已挂入 `LIB_INFO`；源码没有看到它被命令或组件运行逻辑读取，因此“可在支持库元数据中展示”已实现，“改变运行时超时行为”仅声明/未实现。

### 5.3 “脚本组件”数据类型与属性

`script_dtType.cpp:76-90` 登记一个 `LIB_DATA_TYPE_INFO`：

- 中文名：`脚本组件`；英文名：`Script`；说明：`支持运行各种脚本语言`。
- 命令索引表为 `0,1,2,3`，把四条命令绑定为该对象的方法。
- 平台为 `__OS_WIN`，类型标志为 `LDT_WIN_UNIT | LDT_IS_FUNCTION_PROVIDER`。
- 无事件；属性数组包含 8 个固定窗口属性与 3 个自定义属性。
- 自定义属性：`Language`（可编辑选择 `JScript`/`VBScript`）、`ErrorInfo`（只读）、`TimeOut`（整数）。
- 交互函数为 `script_GetInterface_Script`。

接口表 `script_GetInterface_Script` 按 `ITF_*` 返回回调函数（`script_dtType.cpp:95-158`）。登记层已实现；实际回调状态如下：

| 回调 | 预期作用 | 当前事实 | 状态 |
|---|---|---|---|
| `script_ControlCreate_Script` | 创建设计时/运行时组件 | `HUNIT hUnit = 0; return hUnit;` | 仅声明/占位，不能证明组件可创建（`script_dtType.cpp:160-177`） |
| `script_PropUpDate_Script` | 判断属性是否可编辑 | 无条件 `return TRUE` | 已实现为恒真策略，但不含业务状态（`180-184`） |
| `script_PropPopDlg_Script` | 处理 `UD_CUSTOMIZE` 属性对话框 | `*pblModified=false` 后返回 `FALSE` | 仅声明/占位（`186-194`） |
| `script_PropChanged_Script` | 校验并应用属性修改 | 只对索引 0 空分支，最终返回 `false` | 仅声明/占位（`196-215`） |
| `script_PropGetDataAll_Script` | 序列化全部属性 | 直接返回 0 | 仅声明/占位（`217-222`） |
| `script_PropGetData_Script` | 读取某属性当前值 | 索引 0 不写值却返回 `true`；其它索引返回 `false` | 仅声明/占位，存在“成功但无数据”风险（`224-244`） |
| `script_PropKetInfo_Script` | 询问组件是否拦截按键 | 无条件 `FALSE` | 已实现为恒假策略，但未体现组件逻辑（`246-251`） |
| `script_PropNotifyReceiver_Script` | 设计器通知/默认尺寸 | `NU_GET_CREATE_SIZE_IN_DESIGNER` 分支不写宽高且返回 0 | 仅声明/占位（`253-272`） |

注释描述了属性值合法性校验、设计时/运行时取值区别和内存释放要求，但这些是接口契约说明，不是当前实现证据。

### 5.4 动态库入口、元数据与通知

`script_dllMain.cpp:31-87` 构造 `LIB_INFO`：

- 格式号 `LIB_FORMAT_VER`；GUID `EDF19861DC454d15BA0B9E3FF9CA4F57`。
- 版本 `2.0.0`；要求易语言系统 `3.7`、系统核心支持库 `3.7`。
- 名称“脚本语言支持组件”，语言为 `__GBK_LANG_VER`，平台仅 `__OS_WIN`。
- 作者和联系信息为源码中的固定字符串。
- 关联 1 个数据类型、4 个命令、1 个常量；无全局命令类别、AddIn、SuperTemplate 和依赖文件声明。
- `m_pfnNotify` 指向 `script_ProcessNotifyLib_script`，符合 `LIB_INFO` 要求的非空通知入口。

`Source_script.def` 仅导出 `GetNewInf`（第 1-4 行）；`GetNewInf()` 返回上述静态 `LIB_INFO` 地址（`script_dllMain.cpp:89-92`），这就是动态库与易语言装载器的主要 ABI 边界。

`DllMain` 对四种 DLL 生命周期事件均为空，仅返回 `TRUE`（`script_dllMain.cpp:6-24`），没有资源初始化或释放逻辑。

通知入口处理事实（`script_dllMain.cpp:101-178`）：

- `NL_GET_CMD_FUNC_NAMES` 返回静态命令实现名数组；`NL_GET_NOTIFY_LIB_FUNC_NAME` 返回通知函数名；`NL_GET_DEPENDENT_LIBS` 返回空依赖列表。动态库路径下这三项已实现为静态编译兼容协议。
- `NL_SYS_NOTIFY_FUNCTION` 把宿主提供的 `PFN_NOTIFY_SYS` 转交给 `elib/fnshare.cpp` 的 `ProcessNotifyLib`。后者保存回调，并首次通过 `NRS_GET_PRG_TYPE` 取得程序类型写入 `s_isDebug`（`elib/fnshare.cpp:7-36`）。
- `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NR_DELAY_FREE`、`NL_IDE_READY`、`NL_RIGHT_POPUP_MENU_SHOW`、`NL_ADD_NEW_ELEMENT` 分支均为空；没有资源释放、IDE 菜单、成员注入或延迟释放逻辑。
- 未匹配通知返回 `NR_ERR`。`NL_SYS_NOTIFY_FUNCTION` 分支忽略了 `ProcessNotifyLib` 的返回值并保持 `NR_OK`。

`elib/fnshare.h/.cpp` 还提供 `NotifySys`、`ealloc`、`efree`、`SetUserSysNotify` 等辅助边界，但本项目源码没有看到脚本引擎或组件逻辑调用这些辅助函数；因此不能把公共能力当作本项目已接入能力。

## 6. 数据模型与状态

本项目无数据库、配置文件格式、持久化文件、网络协议或消息队列。运行时数据主要是易语言 ABI 传入/传出的内存结构：

| 数据结构 | 用途 | 本项目实例/来源 |
|---|---|---|
| `LIB_INFO` | 支持库身份、版本、平台、命令/类型/常量表和通知函数 | `g_LibInfo_script_global_var`，`script_dllMain.cpp:31-87` |
| `CMD_INFO` | 单条命令的显示名、英文名、说明、标志、返回类型和参数区间 | `g_cmdInfo_script_global_var[]`，`script_cmdInfo.cpp:32-42` |
| `ARG_INFO` | 命令参数名称、说明、数据类型、默认值和参数标志 | `g_argumentInfo_script_global_var[]`，`script_cmdInfo.cpp:5-25` |
| `PFN_EXECUTE_CMD[]` | 命令索引到执行函数的并行数组 | `g_cmdInfo_script_global_var_fun[]`，`script_dllMain.cpp:26-29` |
| `LIB_CONST_INFO` | 支持库预定义常量 | `g_ConstInfo_script_global_var[]`，`script_const.cpp:4-18` |
| `LIB_DATA_TYPE_INFO` | “脚本组件”及其命令索引、属性和接口回调 | `g_DataType_script_global_var[]`，`script_dtType.cpp:76-90` |
| `UNIT_PROPERTY` | 组件固定属性和自定义属性的编辑描述 | `s_objPropertyscript_Script_static_var_00[]`，`script_dtType.cpp:52-74` |
| `MDATA_INF` / `PMDATA_INF` | 易语言命令参数和返回值的运行时数据 | ABI 定义于 `elib/lib2.h:1234-1239`；命令函数仅读取 `m_pText`/`m_pAryData` |

只有 `fnshare.cpp` 存在少量进程内状态：`s_pfnNotifySys`、`s_pfnuserNotifySys` 和初始值为 `1253600` 的 `s_isDebug`（`elib/fnshare.cpp:3-9`）。没有脚本源码缓存、脚本语言实例、错误文本、超时计时器、组件句柄映射或属性值存储。`Reset` 的“清除上次执行代码”因此只有元数据语义，没有可清除的本地状态证据。

## 7. 关键调用链与数据流

### 7.1 装载与命令登记

```text
宿主 LoadLibrary(.fne)
  → 导出表 Source_script.def::GetNewInf
  → g_LibInfo_script_global_var
  → 读取 g_DataType_script_global_var / g_cmdInfo_script_global_var /
    g_cmdInfo_script_global_var_fun / g_ConstInfo_script_global_var
  → 根据数据类型的命令索引 0..3 将对象方法显示并绑定
```

此链条的表构造和指针关系由源码支持；真实 `LoadLibrary`、易语言 IDE 展示和命令调用未在本机验证。

### 7.2 命令执行

```text
易语言运行时
  → PFN_EXECUTE_CMD(index)
  → script_Execute_0_script / script_CalculateExp_1_script /
    script_Reset_2_script / script_Run_3_script
  → 当前最多读取 pArgInf[1] 或 pArgInf[2]
  → 没有创建脚本引擎、执行代码、计算表达式、设置错误信息、设置超时
  → 返回数据 pRetData 未被业务逻辑填充
```

`PFN_EXECUTE_CMD` ABI 要求由命令函数通过 `pRetData` 提供返回数据（`elib/lib2.h:1234-1239`），而四个函数没有完成该契约，所以不能认定“执行/计算/运行”已实现。

### 7.3 组件创建与属性

```text
IDE/运行时请求 Script 类型接口
  → script_GetInterface_Script(ITF_*)
  → 对应 script_ControlCreate_Script / script_Prop* 回调
  → 当前没有真实 HUNIT、属性内存块或脚本对象
  → 组件创建返回 0；属性读写/序列化没有完成
```

### 7.4 系统通知

```text
宿主 → script_ProcessNotifyLib_script(NL_SYS_NOTIFY_FUNCTION, PFN_NOTIFY_SYS, ...)
  → fnshare::ProcessNotifyLib
  → 保存系统通知函数
  → NotifySys(NRS_GET_PRG_TYPE, 0, 0)
  → 保存程序类型到 s_isDebug
```

`NotifySys` 仅在 `s_pfnNotifySys` 非空时转发（`elib/fnshare.cpp:11-16`）；除上述初始化和辅助函数外，源码没有实现脚本引擎所需的宿主服务调用链。

## 8. 接口、ABI 与边界

### 对外导出

- DLL 导出：`GetNewInf`，由 `Source_script.def:1-4` 固定声明。
- `GetNewInf` 返回 `PLIB_INFO`，名称与 ABI 常量 `FUNCNAME_GET_LIB_INFO` 一致（`elib/lib2.h:1315-1318`）。
- 命令实现函数名由 `SCRIPT_NAME` 拼接生成，动态库命名模式来自 `script_cmd_typedef.h:3-9`；当前生成名在源码中明确为 `script_Execute_0_script`、`script_CalculateExp_1_script`、`script_Reset_2_script`、`script_Run_3_script`。

### 宿主回调

- `PFN_NOTIFY_LIB`：宿主通知支持库；项目实现为 `script_ProcessNotifyLib_script`。
- `PFN_NOTIFY_SYS`：支持库向宿主发通知；由 `fnshare.cpp` 保存。
- `PFN_EXECUTE_CMD`：命令执行统一签名。
- `PFN_GET_INTERFACE`：组件接口查询；项目返回若干属性/创建回调。
- `UNIT_PROPERTY_VALUE`、`HGLOBAL` 等结构/句柄的生命周期由易语言 ABI 约定，项目当前没有完成实际内存管理。

### IDE 功能接口

`elib/PublicIDEFunctions.h` 定义了光标移动、编辑、文件、编译、调试、AddIn 等大量功能号，并定义 `GET_PRG_TEXT_PARAM` 等参数结构；当前 `script` 源码没有引用这些 `FN_*` 功能号，也没有设置 `LBS_IDE_PLUGIN`，所以它们是可用的公共契约，不是本项目已暴露功能。

## 9. 技术栈、依赖与构建配置

| 类别 | 当前事实 |
|---|---|
| 语言 | C++，源码包含 UTF-8/GB18030 文件；中文源码注释/元数据以 GBK 语义为主 |
| 构建系统 | Visual Studio `.sln` + MSBuild `.vcxproj` |
| 工具集 | `v141` |
| Windows SDK | `10.0.15063.0` |
| 字符集 | 工程多数配置为 `Unicode`，但易语言元数据使用 `LPCSTR`/GBK；需宿主 ABI 兼容验证 |
| 目标 | 动态库 `script`（Win32 目标扩展 `.fne`，x64 配置未单独设置扩展名）与静态库 `script_static` |
| 平台 | 解决方案配置为 `x86`、`x64`；代码元数据和库状态只声明 `__OS_WIN` |
| 外部库 | `m_szzDependFiles=NULL`；公共 `elib` 头依赖 Windows/易语言宿主 ABI，实际系统库由工程/宿主环境提供 |
| 脚本引擎 | 未发现 JScript/VBScript COM、Active Scripting、`IActiveScript`、文件加载或第三方引擎依赖 |
| 数据库/网络 | 未发现 |

### 工程配置风险（源码/工程事实，不是运行结论）

1. `script.vcxproj` 的 Win32 Debug/Release 配置设置了 `__E_FNENAME=script`、`Source_script.def` 和 `.fne`；x64 配置没有设置 `__E_FNENAME=script`，也没有配置 `ModuleDefinitionFile`，且没有设置 `.fne` 目标扩展（`script.vcxproj:95-108`、`159-198`）。x64 动态库的导出和命名因此需要在 Windows/MSBuild 环境实际检查。
2. `script_static.vcxproj` 的 Win32 配置定义 `__E_STATIC_LIB;__E_FNENAME=script`，但 x64 Debug/Release 的 `PreprocessorDefinitions` 仅有 `_DEBUG`/`NDEBUG`、`_LIB`，未见 `__E_STATIC_LIB` 或 `__E_FNENAME=script`（`script_static/script_static.vcxproj:92-162`）。静态 x64 目标的预处理路径和命令名生成未验证。
3. 静态项目 x64 配置使用 `PrecompiledHeader>Use`，仓库文件清单没有 `pch.h`；这属于可疑工程配置，未在 Windows 编译器中确认具体失败点。
4. `include_script_header.h:17` 在非静态路径声明 `extern ARG_INFO g_argumentInfo_script_global_var[]`，而 `script_cmdInfo.cpp:5` 随后以 `static ARG_INFO` 定义同名数组；这是需要 MSVC 实际编译确认的链接属性冲突风险。静态库因 `__E_STATIC_LIB` 条件会跳过该元数据定义。
5. `script.sln` 将 `Debug|x86` 映射为项目的 `Debug|Win32`，而两个项目本身声明的是 `Win32` 配置；这是合法的解决方案映射意图，但不能替代实际构建验证（`script.sln:10-32`）。
6. `script_ProcessNotifyLib_script` 将命令名数组/字符串常量指针强制转换为 `INT` 返回（`script_dllMain.cpp:108-123`）。这是旧 ABI 形式；在 x64 下指针宽度与 `INT` 的兼容性必须由宿主 ABI/编译结果验证，不能假定安全。
7. `g_LibInfo_script_global_var` 要求系统核心支持库 `3.7`（`script_dllMain.cpp:39-42`），而 `elib/krnllib.h` 的静态常量标识为 `LI_KRNL_LIB_MAJOR_VER=4`、`LI_KRNL_LIB_MINOR_VER=5`（`elib/krnllib.h:114-126`）。这可能是模板历史值或兼容范围差异，当前没有宿主版本验证。

## 10. 测试与验证现状

### 仓库内现状

- 未发现单元测试、集成测试、测试数据、CI、构建脚本或运行示例。
- `script_cmdInfo.cpp` 仅在 `_DEBUG` 下计算参数数组项数（`script_cmdInfo.cpp:27-29`），不是测试套件。
- 代码中的 `TODO` 和空回调是未完成实现提示，不是验证证据。

### 当前核对实际执行

当前核对仅做了只读人工源码、工程和 Git 取证，并确认：文件清单、项目配置、命令/属性元数据、入口导出、通知链和占位实现。未在 macOS 上运行 Visual Studio/MSBuild、易语言 IDE、`.fne` 装载、脚本引擎或 Windows 宿主测试；因此以下均为**未验证**：

- 动态库 Win32/x64 编译与 `GetNewInf` 导出；
- 静态库 Win32/x64 编译与静态命令符号绑定；
- 支持库在易语言 3.7+ 宿主中的登记、组件拖放和命令调用；
- JScript/VBScript 的真实执行、表达式计算、过程调用、错误信息和超时；
- 属性保存/恢复、设计时与运行时属性值一致性；
- `PFN_NOTIFY_SYS`、宿主内存和组件句柄 ABI 的运行兼容性。

## 11. 结论、风险与后续复核点

### 已确认的可复用结构

- 通过 `SCRIPT_DEF` X-macro 同时生成命令声明、命令元数据、函数指针表和静态命令名数组，减少命令索引错位风险。
- 通过 `LIB_INFO` 将命令、数据类型、常量和通知函数聚合成易语言支持库登记对象。
- 通过 `LIB_DATA_TYPE_INFO` 的命令索引把对象方法与“脚本组件”关联。
- `elib/lib2.h`、`fnshare.*` 提供了可复用的支持库 ABI 和宿主通知/内存辅助层。

### 主要风险

1. **功能阻断风险**：四条脚本命令没有调用脚本引擎，也没有设置返回值；组件创建返回空句柄，属性回调未完成。当前源码不能作为可运行脚本组件的证据。
2. **数据一致性风险**：属性读取在索引 0 上返回成功但不写入 `UNIT_PROPERTY_VALUE`；所有属性没有持久化状态。
3. **构建阻断风险**：x64 预处理宏、动态库 `.def`/目标扩展、静态库预编译头和 `extern`/`static` 声明均需 Windows MSVC 验证。
4. **ABI/平台风险**：工程声明 x64，但若干旧 ABI 代码以 `INT` 承载指针；字符集和 GBK/Unicode 边界也未通过宿主验证。
5. **版本风险**：`LIB_INFO` 要求的核心支持库版本与 `krnllib.h` 固定标识不一致，需确认目标宿主版本策略。

### 后续复核顺序

```text
先在 Windows/MSVC 修复并验证工程矩阵
  → 确认动态/静态库 ABI 与导出符号
  → 为脚本组件建立真实 HUNIT/属性状态/序列化
  → 接入 JScript/VBScript 引擎和错误/超时处理
  → 实现四条命令的 pRetData 与参数校验
  → 在易语言 IDE/运行时做装载、拖放、执行、保存恢复测试
  → 再处理通知释放、x64 指针宽度和版本兼容性
```

当前核对没有修改源码、工程、依赖、测试、配置或 Git；唯一新增文件是本项目根目录的 `ARCHITECTURE.md`。后续架构更新应继续维护本文件，旧细探如未来出现，须先逐份核对源码后再收口，不能形成第二事实源。

## 12. 证据路径索引

- `script.sln:1-40`：解决方案、项目 GUID 和 x86/x64 配置映射。
- `script.vcxproj:21-48`、`:51-75`、`:95-198`：动态库源码清单、目标类型、工具集、预处理宏、导出/目标扩展配置。
- `script_static/script_static.vcxproj:21-45`、`:48-73`、`:92-162`：静态库源码清单和 Win32/x64 配置。
- `Source_script.def:1-4`：DLL 导出表。
- `include_script_header.h:3-24`：公共 ABI 包含、全局表声明和命令原型展开。
- `script_cmd_typedef.h:3-16`：命令 X-macro、命令索引和协议元数据。
- `script_cmdDef.cpp:1-34`：四个命令函数的当前空实现。
- `script_cmdInfo.cpp:5-42`：参数描述和 `CMD_INFO[]`。
- `script_const.cpp:4-18`：`NoTimeOut` 常量。
- `script_dtType.cpp:43-90`：组件命令索引、属性数组和 `LIB_DATA_TYPE_INFO`。
- `script_dtType.cpp:95-272`：组件接口分派及回调占位实现。
- `script_dllMain.cpp:6-24`、`:26-98`、`:101-178`：DLL 生命周期、`LIB_INFO`、`GetNewInf`、通知入口。
- `elib/lib2.h:270-364`：`ARG_INFO`/`CMD_INFO` 与命令标志。
- `elib/lib2.h:394-458`、`:665-729`：属性与组件接口数据结构。
- `elib/lib2.h:1225-1318`：通知函数、命令函数、`LIB_INFO` 和固定入口名称。
- `elib/fnshare.cpp:7-71`、`elib/fnshare.h:20-55`：宿主通知、内存辅助和调试状态转发。
- `elib/PublicIDEFunctions.h:1-493`：IDE 功能号公共定义，当前项目未接入。
- `elib/krnllib.h:114-131`、`elib/lang.h:6-14`：核心库版本与语言常量。
- Git 基线：`df98374c5e48939ce7e2916b78818b3ae21ecbac`，`master` 与 `origin/master` 同步，无标签。
