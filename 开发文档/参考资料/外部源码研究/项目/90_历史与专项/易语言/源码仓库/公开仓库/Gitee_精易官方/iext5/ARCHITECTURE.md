# iext5 架构与实现建档

## 1. 文档范围与结论摘要

本文件是 `iext5` 仓库根目录唯一的架构建档文档。内容依据当前工作树中人工读取的 C/C++ 源码、Visual Studio 工程文件和 Git 基线整理；不把仓库外的 MCP、其他项目或宣传资料当作本项目事实。

状态标签约定：

- **源码已实现**：源码中存在可执行实现，并且能够从静态代码确认其行为。
- **仅声明/注册**：有类型、命令、接口或工程配置声明，但没有可确认的完整业务实现。
- **未验证**：当前核对未在 Windows/Visual Studio/易语言 IDE 或运行时中编译、装载、拖放、执行和回归验证。

### 首轮结论

`iext5` 是面向易语言的 Windows 扩展界面支持库，目标是提供“气球提示框（Q_tip）”和“简单超文本框（SimpleHtml）”两个窗口组件，以及组件方法、属性和事件元数据。当前仓库已实现支持库描述表、命令/组件注册、导出入口和系统通知转发骨架；组件创建、属性持久化、实际窗口/HTML 渲染、提示框关联和命令业务逻辑仍是模板桩或空函数，不能仅凭元数据宣称功能已可运行。

## 2. 项目定位

- **项目名**：`iext5`
- **远程仓库**：`https://gitee.com/JYtechnology/iext5.git`
- **目标宿主**：易语言 IDE/运行时及其支持库加载机制。
- **目标平台**：工程配置声明为 Windows；命令、数据类型、属性和组件均以 `__OS_WIN` 或 `OS_ALL` 元数据标识，其中两个数据类型均带 Windows 组件标志。
- **主要能力（从元数据和注释可确认的设计目标）**：
  1. 气球提示框：把提示信息关联到窗口组件、工具条或多个窗口组件，或者在屏幕坐标处手动弹出提示。
  2. 简单超文本框：在窗口内显示简化 HTML/CSS 文本，并暴露自定义超链接事件。
- **当前实际完成度**：注册/描述层完整度高；运行时组件层为未完成模板。`iext5_dtType.cpp:388-390,569-571,613-617` 等位置明确保留 `TODO`、返回 `0` 的创建/属性实现。

## 3. 总体流程图

```text
易语言 IDE / 运行时
        │
        │ LoadLibrary / 支持库装载
        ▼
Source_iext5.def ───────────────► GetNewInf()
                                      │
                                      ▼
                        g_LibInfo_iext5_global_var
                 ┌──────────────┼────────────────┐
                 ▼              ▼                ▼
        命令元数据表       数据类型元数据表       常量表
        CMD_INFO[]         LIB_DATA_TYPE_INFO[]  空表(0项)
                 │              │
                 │              ├── Q_tip
                 │              │    ├── 20项方法索引
                 │              │    ├── 属性表
                 │              │    └── 3项事件
                 │              └── SimpleHtml
                 │                   ├── 20项方法索引
                 │                   ├── 属性表
                 │                   └── 1项事件
                 ▼
       g_cmdInfo... + g_cmdInfo..._fun[]
                 │
                 ▼
易语言命令调用 (PMDATA_INF 参数)
                 │
                 ▼
iext5_cmdDef.cpp 中 60 个命令入口
                 │
                 └── 当前大多数/全部函数体只取参数或为空，未形成实际业务效果

系统通知 NL_SYS_NOTIFY_FUNCTION
                 │
                 ▼
iext5_ProcessNotifyLib_iext5()
                 │
                 ▼
       elib/fnshare.cpp::ProcessNotifyLib()
                 │
                 ├── 保存 PFN_NOTIFY_SYS
                 ├── 查询程序版本类型
                 └── 可转发用户注册的通知回调
```

## 4. 真实目录与文件地图

```text
iext5/
├── iext5.sln                         # VS solution，包含 DLL 与 static 两个项目
├── iext5.vcxproj                     # 动态库工程，输出目标扩展名配置为 .fne（Win32）
├── iext5.vcxproj.filters             # 动态库工程文件分组
├── iext5.vcxproj.user                # 空的用户工程属性
├── iext5_static/
│   ├── iext5_static.vcxproj          # 静态库工程，复用根目录源码
│   ├── iext5_static.vcxproj.filters
│   └── iext5_static.vcxproj.user
├── Source_iext5.def                  # DLL 模块定义，仅导出 GetNewInf
├── include_iext5_header.h            # 公共聚合头、元数据外部声明、命令原型生成
├── iext5_cmd_typedef.h               # IEXT5_DEF 命令清单及名称拼接宏
├── iext5_cmdInfo.cpp                 # ARG_INFO/CMD_INFO 参数与命令描述表
├── iext5_cmdDef.cpp                  # 60 个命令执行入口的源码骨架
├── iext5_const.cpp                   # 常量表，当前数量为 0
├── iext5_dtType.cpp                  # 两个组件的数据类型、属性、事件和接口回调
├── iext5_dllMain.cpp                 # DLL 入口、LIB_INFO、通知分发、静态编译名称表
└── elib/
    ├── lib2.h                        # 易语言支持库 ABI、类型、命令、组件接口定义
    ├── fnshare.h / fnshare.cpp       # 系统通知、易语言内存和数据复制辅助
    ├── krnllib.h                     # 系统核心支持库版本/GUID及控件类型常量
    ├── lang.h                        # GBK/English/BIG5/SJIS语言版本常量
    ├── mtypes.h                      # Windows 风格基础类型兼容定义
    ├── untshare.h                    # 组件共享辅助声明
    └── PublicIDEFunctions.h          # IDE AddIn/API 编号和数据结构声明
```

仓库实际 Git 跟踪文件共 22 个；未发现 README、AGENTS、测试目录、CMake/Makefile 或其他架构文档。仓库中没有旧的 `细探-*.md` 可供吸收，本文件为首轮正式建档。

## 5. 模块职责与实现状态

| 模块 | 真实职责 | 状态 | 证据 |
|---|---|---|---|
| `include_iext5_header.h` | 引入 ABI 头和命令定义；生成命令函数声明；声明全局元数据数组 | 源码已实现（声明层） | `include_iext5_header.h:1-26` |
| `iext5_cmd_typedef.h` | 通过 `IEXT5_DEF(_MAKE)` 一次性维护命令索引、中文名、英文名、参数数、返回类型、组件归属 | 源码已实现（注册表） | `iext5_cmd_typedef.h:3-72` |
| `iext5_cmdInfo.cpp` | 建立 15 个参数描述，生成 60 项 `CMD_INFO`，计算命令总数 | 源码已实现（元数据） | `iext5_cmdInfo.cpp:5-55` |
| `iext5_cmdDef.cpp` | 提供 60 个 `PFN_EXECUTE_CMD` 入口；从 `PMDATA_INF` 取参数 | 仅声明/桩实现 | `iext5_cmdDef.cpp:6-503`；真实方法函数体没有业务调用/返回值填充 |
| `iext5_dtType.cpp` | 注册 `Q_tip`、`SimpleHtml`，定义属性、事件、方法索引和组件接口回调 | 元数据已实现；运行时未完成 | `iext5_dtType.cpp:83-304,309-372,489-553` |
| `iext5_dtType.cpp` 组件创建 | 应创建并返回 `HUNIT`/窗口组件 | 未实现 | `iext5_dtType.cpp:374-391,555-572`，均为 `TODO` + `return 0` |
| `iext5_dtType.cpp` 属性读写 | 应处理属性可编辑性、定制对话框、属性变更、单项/全部持久化 | 仅接口骨架 | `iext5_dtType.cpp:393-487,574-667` |
| `iext5_dllMain.cpp` | DLL 生命周期入口；组装 `LIB_INFO`；导出 `GetNewInf`；处理库通知 | 部分源码已实现 | `iext5_dllMain.cpp:7-24,26-98,101-178` |
| `iext5_const.cpp` | 提供库常量元数据 | 已实现为空表 | `iext5_const.cpp:14-18` |
| `elib/fnshare.cpp` | 保存系统通知回调，查询调试/发布运行类型，转发用户通知 | 源码已实现（基础设施） | `elib/fnshare.cpp:7-71` |
| `elib/*.h` | 提供易语言 ABI、数据结构、通知码、内存和通用接口定义 | 依赖声明/辅助实现 | `elib/lib2.h:243-292,296-729,1081-1239`；`elib/fnshare.h:20-141` |
| `iext5.vcxproj` | 动态库的 Win32/x64 Debug/Release 工程配置 | 工程声明；未验证 | `iext5.vcxproj:3-199` |
| `iext5_static/iext5_static.vcxproj` | 静态库工程，复用根源码 | 工程声明；存在配置疑点，未验证 | `iext5_static/iext5_static.vcxproj:21-164` |

## 6. 数据模型与元数据结构

本项目没有数据库、配置文件格式或磁盘持久化模型。其核心“数据模型”是易语言支持库 ABI 的静态元数据表和运行时传参结构。

### 6.1 支持库描述模型

`g_LibInfo_iext5_global_var` 是宿主加载入口返回的 `LIB_INFO`：

- 格式号：`LIB_FORMAT_VER`。
- GUID：`{E5000198-4471-40e2-92BC-D0BA075BDBB2}`。
- 版本：主版本 `2`、次版本 `0`、构建号 `0`。
- 运行时要求：易语言系统 `4.0`，核心支持库 `4.0`。
- 名称：`扩展界面支持库五`。
- 编码语言：`__GBK_LANG_VER`。
- 平台标识：`_LIB_OS(__OS_WIN)`。
- 命令来源：`g_cmdInfo_iext5_global_var` 和 `g_cmdInfo_iext5_global_var_fun`。
- 数据类型来源：`g_DataType_iext5_global_var`。
- 常量来源：`g_ConstInfo_iext5_global_var`，当前数量为 `0`。
- 库通知函数：`iext5_ProcessNotifyLib_iext5`。
- 依赖静态库列表：在通知 `NL_GET_DEPENDENT_LIBS` 中返回 `"\0\0"`，即未声明额外静态库依赖。

证据：`iext5_dllMain.cpp:31-87`；`elib/lib2.h:1246-1295`。

### 6.2 命令模型

`IEXT5_DEF` 共列出索引 `0..59` 的 60 项命令：

- `0`：隐藏全局命令 `全局命令一`，返回 `SDT_BOOL`，1 个 `SDT_TEXT` 参数。
- `1..19`：隐藏/无法识别的全局占位命令，返回 `_SDT_NULL`，无参数。
- `20..39`：`气球提示框` 对象方法槽位；可见方法包括 `AssociateWindow`、`AssociateToolBar`、`AssociateWindows`、`ShowTooltip`，其余为隐藏占位槽。
- `40..59`：`简单超文本框` 对象方法槽位，当前均为隐藏占位槽。

命令定义使用 `CMD_INFO` 描述名称、英文名、说明、对象类别、平台状态、返回类型、参数数量和参数数组；执行函数指针数组由同一宏清单生成，避免命令描述和函数数组顺序分离。证据：`iext5_cmd_typedef.h:11-72`、`iext5_cmdInfo.cpp:45-55`、`iext5_dllMain.cpp:26-29`。

### 6.3 参数模型

`g_argumentInfo_iext5_global_var` 共 15 项，按命令清单中的起始指针复用：

- `AssociateWindow`：窗口组件、提示文本、图标索引、热点区域 x/y/宽/高。
- `AssociateToolBar`：工具条。
- `AssociateWindows`：窗口组件数组或非数组，使用 `AS_RECEIVE_ALL_TYPE_DATA`。
- `ShowTooltip`：屏幕横纵坐标、提示文本、图标索引、可选自动关闭布尔值。

参数值在 ABI 中通过 `MDATA_INF` 联合体传递，可表示数字、文本、数组、窗口单元、复合数据或变量地址。证据：`iext5_cmdInfo.cpp:5-38`；`elib/lib2.h:261-292,780-824`。

### 6.4 组件模型

`g_DataType_iext5_global_var` 注册两个 `LIB_DATA_TYPE_INFO`：

1. **`Q_tip` / 气球提示框**
   - Windows 窗口组件：`_DT_OS(__OS_WIN) | LDT_WIN_UNIT | LDT_IS_FUNCTION_PROVIDER`。
   - 方法索引：`20..39`，共 20 个槽位。
   - 属性：固定 8 项 + 自定义元数据项，代码数组实际到索引 `70`。
   - 事件：3 项。
   - 交互入口：`iext5_GetInterface_Q_tip`。

2. **`SimpleHtml` / 简单超文本框**
   - Windows 窗口组件：`_DT_OS(__OS_WIN) | LDT_WIN_UNIT`。
   - 方法索引：`40..59`，共 20 个槽位。
   - 属性：固定 8 项 + 自定义项，代码数组实际到索引 `24`。
   - 事件：1 项。
   - 交互入口：`iext5_GetInterface_SimpleHtml`。

证据：`iext5_dtType.cpp:83-304`；结构定义见 `elib/lib2.h:693-729`。

### 6.5 属性与事件

- `Q_tip` 元数据描述外观、背景渐变、手柄、透明度、图标/图片组、CSS、行为、尺寸、延时、边线和阴影等属性；事件包括“自定义超链接被单击”“提示框即将弹出”“提示框即将隐藏”。
- `SimpleHtml` 元数据描述边框、HTML、CSS、根路径、背景色、图标/图片组等属性；事件为“自定义超链接被单击”。
- 事件参数使用 `EVENT_INFO2`/`EVENT_ARG_INFO2`，允许通过 `EAS_BY_REF` 修改提示坐标和文本。ABI 对事件、属性、接口号的定义见 `elib/lib2.h:491-549,570-685`。

这些属性和事件是**注册层事实**；对应运行时窗口绘制、事件产生、属性数据编码/解码在当前源码中没有闭环实现。

## 7. 真实调用链与数据流

### 7.1 支持库加载

1. 宿主按 `.fne` 模块加载 DLL。
2. `Source_iext5.def` 仅导出 `GetNewInf`。
3. `GetNewInf()` 返回静态 `g_LibInfo_iext5_global_var`。
4. 宿主从 `LIB_INFO` 读取命令、函数指针、数据类型、常量和通知函数地址。

证据：`Source_iext5.def:1-4`；`iext5_dllMain.cpp:31-91`。

### 7.2 命令调用

1. 易语言编译/运行时按 `CMD_INFO` 识别命令索引和参数约束。
2. 宿主从 `g_cmdInfo_iext5_global_var_fun[]` 取得与索引同序的函数指针。
3. 函数以 `PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf` 接收返回值和参数。
4. `iext5_cmdDef.cpp` 当前只完成参数局部变量读取，例如 `AssociateWindow` 读取 `m_pByte/m_pText/m_int`，`ShowTooltip` 读取坐标、文本、图标和布尔值；没有调用窗口、Tooltip、HTML 或事件 API，也没有填充 `pRetData`。

因此“命令已注册”成立，“命令能产生目标 UI 行为”不成立。

### 7.3 组件接口调用

1. 宿主按 `LIB_DATA_TYPE_INFO.m_pfnGetInterface` 查询接口号。
2. `iext5_GetInterface_Q_tip` / `iext5_GetInterface_SimpleHtml` 对创建、属性更新、定制对话框、属性变更、全量/单项属性、按键判断和通知接收者返回函数指针。
3. 当前创建回调返回 `HUNIT=0`；属性全量读取返回 `0`；属性单项读取只是模板 `switch`；通知接收者仅处理空模板分支，默认返回 `0`。

证据：`iext5_dtType.cpp:309-487,489-667`。

### 7.4 系统通知

1. 宿主通过 `iext5_ProcessNotifyLib_iext5(NL_SYS_NOTIFY_FUNCTION, ...)` 传入 `PFN_NOTIFY_SYS`。
2. 函数调用 `ProcessNotifyLib`，由 `elib/fnshare.cpp` 保存回调。
3. 首次收到系统通知函数时，调用 `NotifySys(NRS_GET_PRG_TYPE, 0, 0)` 读取程序类型，保存到 `s_isDebug`。
4. `SetUserSysNotify` 注册的用户回调会在 `ProcessNotifyLib` 尾部被调用。
5. `NL_GET_CMD_FUNC_NAMES`、`NL_GET_NOTIFY_LIB_FUNC_NAME` 和 `NL_GET_DEPENDENT_LIBS` 在动态库分支由 `iext5_dllMain.cpp` 返回；其他通知只做空分支或返回默认状态。

证据：`iext5_dllMain.cpp:101-178`；`elib/fnshare.cpp:11-71`。

## 8. 外部接口边界

### 8.1 DLL 导出接口

| 接口 | 形式 | 当前行为 |
|---|---|---|
| `GetNewInf` | `EXTERN_C PLIB_INFO WINAPI GetNewInf()` | 返回 `g_LibInfo_iext5_global_var` |
| `iext5_ProcessNotifyLib_iext5` | `EXTERN_C INT WINAPI ...`，由 `LIB_INFO.m_pfnNotify` 使用 | 处理宿主通知；动态/静态分支行为不同 |

`Source_iext5.def` 只显式导出 `GetNewInf`；通知函数通过描述结构传递，不是 `.def` 中的导出符号。

### 8.2 易语言命令 ABI

所有命令函数遵循 `PFN_EXECUTE_CMD`：

```text
void (*)(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)
```

函数名通过 `iext5_cmd_typedef.h` 的 `IEXT5_NAME` 拼接为类似 `iext5_AssociateWindow_20_iext5` 的唯一符号。动态库函数指针数组与静态编译命令名称数组均由同一命令宏生成。证据：`include_iext5_header.h:22-24`；`iext5_cmd_typedef.h:3-12`；`iext5_dllMain.cpp:26-29,94-98`。

### 8.3 组件回调 ABI

组件交互函数由 `PFN_GET_INTERFACE(INT nInterfaceNO)` 返回，支持的接口号来自 `elib/lib2.h:531-549`。组件创建、属性访问和通知回调的参数签名来自 `elib/lib2.h:553-685`，当前两组件都实现了函数符号和接口映射，但业务体未完成。

## 9. 技术栈与依赖

| 类别 | 事实 |
|---|---|
| 语言 | C/C++（`.cpp`、`.h`） |
| 构建系统 | Visual Studio/MSBuild `.sln` + `.vcxproj` |
| 工具集 | 工程声明 `PlatformToolset v141`，Windows SDK `10.0.15063.0` |
| 目标 | 动态库 `DynamicLibrary` 与静态库 `StaticLibrary` |
| 平台 | Win32/x86、x64 配置；支持库元数据目标为 Windows |
| ABI | 易语言支持库 ABI，核心定义在 `elib/lib2.h` |
| 编码 | `lang.h` 将库语言设为 `__GBK_LANG_VER`；源码文件为非 UTF-8 的扩展 ASCII/GBK 风格文本 |
| UI/系统依赖 | `windows.h`、Windows HWND/HGLOBAL/HMENU 等类型；实际 UI 控件实现未出现在当前源码中 |
| 易语言核心依赖 | `krnllib.h` 声明核心支持库 GUID/版本为 4.5；`LIB_INFO` 要求核心支持库 4.0 |
| 额外静态库 | 源码通知返回空依赖列表；未发现第三方库文件或包管理文件 |
| MFC | 当前仓库未发现 MFC 实现；`fnshare.h` 注释称本单元不使用 MFC |

### 工程配置注意事项

- 根动态工程 Win32 Debug/Release 设置了 `__E_FNENAME=iext5`、`TargetExt=.fne` 和 `Source_iext5.def`；x64 配置没有同样的 `__E_FNENAME=iext5`、`TargetExt`、模块定义文件链接配置，需在 Windows/VS 中复核是否为可构建的完整配置。
- 静态工程的 Win32 Debug/Release 设置了 `__E_STATIC_LIB;__E_FNENAME=iext5`；但 x64 Debug/Release 的预处理器定义只有 `_DEBUG;_LIB` 或 `NDEBUG;_LIB`，未声明 `__E_STATIC_LIB` 与 `__E_FNENAME`，而 `elib/lib2.h:15-25` 要求先定义 `__E_FNENAME`。这是静态工程配置上的高风险未验证项，不在当前核对修改。

## 10. 测试、构建与验证状态

### 10.1 仓库内测试现状

未发现测试源文件、测试工程、测试脚本、CI 配置、README 或构建说明。Git 跟踪文件名中没有 `test`、`spec`、`CMakeLists.txt`、`Makefile`、`.yml` 或 `.yaml`。

### 10.2 当前核对已执行的验证

当前核对只做了静态人工取证，没有安装依赖、没有启动服务、没有执行 Windows 构建：

- 盘点 Git 跟踪文件和工程文件。
- 读取 `iext5.sln`、两个 `.vcxproj`、`.filters`、`.def`。
- 读取全部核心源码：`iext5_dllMain.cpp`、`iext5_cmdDef.cpp`、`iext5_cmdInfo.cpp`、`iext5_cmd_typedef.h`、`iext5_dtType.cpp`、`iext5_const.cpp`、`include_iext5_header.h` 和 `elib` 依赖头/实现。
- 对命令索引、组件索引、属性/事件数组和明显 `TODO`/空返回进行了交叉核对。
- 记录初始 Git 状态为干净的 `master` 工作树（本文件创建前）。

### 10.3 尚未验证事项

- Visual Studio v141 + Windows SDK `10.0.15063.0` 的 Win32/x64 动态/静态编译。
- `.fne` 产物是否能被易语言 IDE 装载。
- `GetNewInf` 返回结构是否通过宿主 ABI 校验。
- 60 个命令的实际返回值、窗口关联、提示显示、HTML 渲染和事件触发。
- 组件属性在设计时/运行时的序列化、反序列化和生命周期释放。
- `HUNIT` 资源创建、销毁、窗口消息过滤、系统内存分配和异常路径。
- GBK 编码在编译器和宿主环境中的正确显示。

## 11. 风险与后续复核优先级

1. **P0：运行时功能缺失**。两个组件创建回调均返回 `0`，全量属性读取返回 `0`，命令实现没有实际 UI 逻辑；应先确认该仓库是否为未完成模板或源码截断版本。
2. **P0：返回值与宿主契约风险**。命令元数据大量声明 `SDT_BOOL`，但命令函数没有写入 `pRetData`；实际运行结果未验证。
3. **重要：静态工程 x64 配置不完整**。缺少 `__E_FNENAME`/`__E_STATIC_LIB`，与 `lib2.h` 的强制宏要求冲突；需在 Windows 工具链中验证或修复工程配置。
4. **重要：资源生命周期未实现**。没有组件句柄创建/销毁、窗口消息、属性内存编码和释放调用，元数据事件不能自然产生。
5. **重要：命令槽位与隐藏占位项**。60 个索引中大量 `无法识别的名字_*`/隐藏项用于占位或兼容，需确认这是否是预期的版本兼容表，不能按 60 个可用命令统计能力。
6. **建议：补充可重复构建与宿主验收**。至少需要 Win32 Debug/Release 构建、DLL 导出检查、易语言 IDE 加载、两个组件拖放/属性编辑、四个可见方法执行、事件和资源释放测试。
7. **建议：保留编码与 ABI 证据**。源码使用 GBK/非 UTF-8 文本和旧式 Windows 类型，后续阅读或自动化转换不得无意改写源文件编码。

## 12. Git 基线与证据索引

### 12.1 基线

- 分支：`master`
- HEAD：`3f79c98af1fa9822b824bf6be30f6322cbc17c55`
- 提交主题：`初始化仓库`
- 提交作者：`精易科技`
- 提交时间：`2022-12-19T16:12:04+08:00`
- 远程：`origin https://gitee.com/JYtechnology/iext5.git`
- 当前核对约束：仅新增/更新本文件；不改源码、工程、依赖、测试、配置或 Git 历史。

### 12.2 关键证据路径

- 支持库入口与版本描述：`iext5_dllMain.cpp:31-98`
- 库通知分发：`iext5_dllMain.cpp:101-178`
- 命令清单：`iext5_cmd_typedef.h:3-72`
- 参数与命令元数据：`iext5_cmdInfo.cpp:5-57`
- 命令执行骨架：`iext5_cmdDef.cpp:1-503`
- 组件属性/事件/数据类型：`iext5_dtType.cpp:83-304`
- 组件接口映射：`iext5_dtType.cpp:309-372,489-553`
- 组件创建及属性桩：`iext5_dtType.cpp:374-487,555-667`
- 常量空表：`iext5_const.cpp:12-18`
- 系统通知辅助：`elib/fnshare.cpp:7-71`
- 支持库 ABI 结构和回调：`elib/lib2.h:243-292,296-729,1081-1295`
- 易语言内存/文本/数组辅助：`elib/fnshare.h:20-141`
- 动态库工程：`iext5.vcxproj:21-199`
- 静态库工程：`iext5_static/iext5_static.vcxproj:21-164`
- Solution 映射：`iext5.sln:1-40`
- DLL 导出：`Source_iext5.def:1-4`

本文件完成后，后续深挖应继续更新本文件，不再生成平行架构事实源；源码实现状态必须随着新的编译、宿主运行或测试证据重新分类。
