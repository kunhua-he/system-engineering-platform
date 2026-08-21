# jedi 架构档案

> 首轮全量建档。本文是本仓库唯一的架构事实入口；后续细探应增量维护本文，不在源码目录旁建立平行架构结论。
>
> **证据口径**：`已实现` 只表示源码中存在可执行实现或已静态确认的装配关系；`仅声明/注册` 表示有 ABI、元数据、原型或工程配置，但没有完整运行路径；`未验证` 表示本机无法以当前环境证明（尤其是 Windows/Visual Studio 构建与易语言宿主联调）。仓库中没有 README、测试目录或既有 `ARCHITECTURE.md`，因此本档案以源码和工程文件为主证据。

## 1. 项目定位

`jedi` 是精易官方 Gitee 仓库中的一个 **易语言支持库 C++ 工程模板/实现骨架**：通过易语言支持库 ABI 注册若干 Windows 窗口组件、命令、属性和事件，并宣称“封装了优秀的开源项目 JEDI 中的部分 VCL 组件”（`jedi_dllMain.cpp:44-47`）。

当前源码事实比项目说明更窄：仓库只包含易语言支持库 ABI 头文件、静态元数据、命令函数空壳和组件回调空壳；没有 JEDI/VCL 第三方源码、头文件、库文件、资源文件或组件对象实现。六个组件的 `ControlCreate_*` 均返回 `0`，属性读写及事件转发也没有形成完整运行链。因此首轮应将其定位为：

- **已实现**：Windows 易语言支持库 DLL 的登记结构、命令/数据类型/属性/事件元数据、通知入口骨架、部分 ABI 辅助函数。
- **仅声明/注册**：6 个窗口组件、9 条成员命令及其事件/属性描述；组件接口分派函数已注册，但组件创建、状态持有和事件产生未完成。
- **未验证/未形成**：实际 JEDI/VCL 组件封装、易语言 IDE 拖放/运行、命令业务效果、DLL/静态库在 Windows 上的编译和宿主联调。

仓库规模为 Git 跟踪的 23 个文件、单次初始化提交；无依赖锁定文件、无测试、无 CI、无构建脚本和无运行时数据目录。

## 2. 总体架构与流程

```text
易语言 IDE / 运行时
        │
        │ LoadLibrary + 查找导出 GetNewInf
        ▼
┌─────────────────────────────────────────────────────────┐
│ jedi DLL（jedi.vcxproj，DynamicLibrary，目标 .fne）     │
│                                                         │
│  GetNewInf() ──► LIB_INFO                              │
│      │               ├─ g_DataType[6]                  │
│      │               ├─ g_cmdInfo[9]                    │
│      │               ├─ g_cmdInfo_fun[9]                │
│      │               └─ g_ConstInfo[0]                  │
│      │                                                  │
│      └─► 元数据索引 ──► PFN_EXECUTE_CMD ──► 命令空壳    │
│                         （jedi_cmdDef.cpp）             │
│                                                         │
│  NL_SYS_NOTIFY_FUNCTION ─► jedi_ProcessNotifyLib_jedi   │
│                              └► ProcessNotifyLib         │
│                                   └► s_pfnNotifySys      │
│                                      └► NotifySys         │
│                                         └► 易语言系统    │
│                                                         │
│  数据类型元数据 ─► GetInterface_* ─► ControlCreate_*     │
│       │                         ├► 属性回调骨架          │
│       │                         ├► 事件/按键回调骨架      │
│       │                         └► 当前创建返回 HUNIT=0 │
└─────────────────────────────────────────────────────────┘
        │
        └─ elib ABI / Win32 内存、窗口、字体与通知契约

静态库分支：jedi_static.vcxproj ─► 复用同一批 .cpp/.h
                  └► __E_STATIC_LIB 下抑制 DLL 登记代码，供静态链接
```

### 2.1 关键调用链（源码证据）

1. **DLL 登记**：`Source_jedi.def:1-4` 声明 DLL 名称并导出 `GetNewInf`；`jedi_dllMain.cpp:89-92` 返回静态 `LIB_INFO` 地址。
2. **登记内容**：`g_LibInfo_jedi_global_var`（`jedi_dllMain.cpp:31-87`）连接库版本、GUID、平台、类别、命令、命令函数表、数据类型、常量、通知函数和依赖列表。
3. **命令索引**：`jedi_cmd_typedef.h:12-21` 用 X-macro `JEDI_DEF` 作为唯一命令清单；`jedi_cmdInfo.cpp:33-43` 生成 `CMD_INFO[]`；`jedi_dllMain.cpp:26-29` 生成函数指针表；`jedi_cmdDef.cpp:6-70` 提供 9 个命令符号。
4. **宿主通知**：宿主发送 `NL_SYS_NOTIFY_FUNCTION` 后，`jedi_dllMain.cpp:125-132` 转发给 `elib/fnshare.cpp:24-36`，保存宿主的 `PFN_NOTIFY_SYS`；库侧通过 `NotifySys`（`elib/fnshare.cpp:11-17`）反向通知系统。
5. **组件登记与分派**：`jedi_dtType.cpp:692-741` 生成 6 个 `LIB_DATA_TYPE_INFO`；每个数据类型的 `m_pfnGetInterface` 指向对应 `jedi_GetInterface_*`；分派器按 `ITF_*` 返回创建、属性和通知回调（例如 `jedi_dtType.cpp:745-809`）。
6. **组件创建**：`jedi_ControlCreate_*` 接收属性数据、窗口句柄、位置、易语言窗体/组件 ID 和设计模式标志，但当前均只设置 `HUNIT hUnit = 0` 并返回（例如 `jedi_dtType.cpp:811-828`）。

## 3. 真实目录与模块职责

```text
jedi/
├── jedi.sln                         VS 解决方案：jedi + jedi_static
├── jedi.vcxproj                     DLL 工程（DynamicLibrary）
├── jedi_static/
│   ├── jedi_static.vcxproj          静态库工程（StaticLibrary）
│   ├── jedi_static.vcxproj.filters
│   └── jedi_static.vcxproj.user
├── Source_jedi.def                  DLL 导出定义：GetNewInf
├── include_jedi_header.h            统一入口及 DLL 元数据 extern/命令声明
├── jedi_cmd_typedef.h               命令 X-macro 清单和符号拼接
├── jedi_cmdDef.cpp                  9 个命令执行函数的当前实现
├── jedi_cmdInfo.cpp                 参数表和 CMD_INFO 元数据生成
├── jedi_const.cpp                   常量表（当前数量为 0）
├── jedi_dllMain.cpp                 DllMain、LIB_INFO、命令函数表、通知入口
├── jedi_dtType.cpp                  6 个数据类型、属性、事件及组件回调
└── elib/
    ├── mtypes.h                     基础 Win32 风格类型、句柄和宏
    ├── lib2.h                       易语言支持库 ABI、类型、通知和 LIB_INFO
    ├── lang.h                       GBK/英语/BIG5/SJIS 语言版本宏
    ├── krnllib.h                    系统核心库类型和通知常量
    ├── fnshare.h                    内存、通知、数组/文本辅助函数
    ├── fnshare.cpp                  宿主通知指针和库通知生命周期实现
    ├── untshare.h                   窗口/属性辅助骨架和占位宏
    └── PublicIDEFunctions.h          IDE 功能通知号及编辑器功能 ABI
```

### 3.1 模块职责表

| 模块 | 责任 | 当前状态 | 证据 |
|---|---|---|---|
| `elib/lib2.h` | 定义 `DATA_TYPE`、`MDATA_INF`、`CMD_INFO`、`LIB_DATA_TYPE_INFO`、`LIB_INFO`、通知号及回调原型 | 已实现为 ABI 头文件；不是本项目业务实现 | `elib/lib2.h:11-43, 158-292, 296-364, 693-729, 780-824, 1246-1318` |
| `elib/fnshare.cpp/.h` | 维护 `PFN_NOTIFY_SYS`，转发系统通知，申请/释放易语言内存 | 部分已实现；业务通知分支多数空操作 | `elib/fnshare.cpp:7-71` |
| `jedi_cmd_typedef.h` | 用一份命令清单生成声明、元数据、函数表和字符串表 | 已实现 | `jedi_cmd_typedef.h:3-21` |
| `jedi_cmdInfo.cpp` | 生成 5 个参数描述、9 条 `CMD_INFO` 记录 | 已实现元数据；无业务行为 | `jedi_cmdInfo.cpp:5-43` |
| `jedi_cmdDef.cpp` | 命令执行入口 | 仅函数壳；只有部分参数读取，未填返回值或产生副作用 | `jedi_cmdDef.cpp:6-70` |
| `jedi_dtType.cpp` | 6 个 Windows 组件的成员方法、属性、事件、接口分派及回调 | 元数据已实现；运行时回调为模板骨架 | `jedi_dtType.cpp:243-741, 745-1830` |
| `jedi_dllMain.cpp` | DLL 入口、库登记、`GetNewInf`、命令名称和系统通知 | DLL 登记链已实现；通知业务分支多数空 | `jedi_dllMain.cpp:7-100, 101-178` |
| `jedi_const.cpp` | 常量表 | 数组存在但数量为 0 | `jedi_const.cpp:14-18` |
| `elib/untshare.h` | 窗口样式、字体、属性序列化、图标等辅助函数/占位符 | 少量 Win32 辅助函数可执行；序列化和图标加载仍是空实现 | `elib/untshare.h:14-271` |
| `jedi.vcxproj` | 构建 DLL，Win32/x64、Debug/Release | 工程声明存在；x64 配置需 Windows/VS 复核 | `jedi.vcxproj:3-20, 21-48, 51-198` |
| `jedi_static/jedi_static.vcxproj` | 复用源码构建静态库 | 工程声明存在；x64/PCH 配置需复核 | `jedi_static/jedi_static.vcxproj:3-45, 48-163` |

## 4. 功能与数据模型

### 4.1 库登记模型

动态 DLL 的 `LIB_INFO` 事实值如下：

| 字段 | 值/含义 | 证据 |
|---|---|---|
| `m_dwLibFormatVer` | `LIB_FORMAT_VER`（`20000101`） | `jedi_dllMain.cpp:33`；定义于 `elib/lib2.h:1246` |
| `m_szGuid` | `{03085BE0-BB7A-4CAF-A49A-5A0D6BA8B3E2}` | `jedi_dllMain.cpp:34` |
| 版本 | `1.0.2` | `jedi_dllMain.cpp:35-37` |
| 所需系统/核心库 | 易语言 `4.0`；系统核心库 `4.5` | `jedi_dllMain.cpp:39-42` |
| 名称/语言/平台 | `jedi` / `__GBK_LANG_VER` / `__OS_WIN` | `jedi_dllMain.cpp:44-47`；`elib/lang.h:8-14` |
| 类别 | 2 个字符串：`分类1`、`分类2` | `jedi_dllMain.cpp:61-62` |
| 命令 | 9 条，`m_pCmdsFunc` 对应 9 个函数指针 | `jedi_cmd_typedef.h:12-21`；`jedi_dllMain.cpp:64-66` |
| 数据类型 | 6 个 | `jedi_dtType.cpp:692-741` |
| 常量 | 0 条（数组占位长度为 1，count 为 0） | `jedi_const.cpp:14-18` |
| AddIn/SuperTemplate | 均为 `NULL` | `jedi_dllMain.cpp:68-81` |
| 外部支持库依赖 | `m_szzDependFiles = NULL`；通知查询返回空双零字符串 | `jedi_dllMain.cpp:83-86, 117-123` |

### 4.2 命令模型

9 条命令由 `JEDI_DEF` 统一声明（`jedi_cmd_typedef.h:12-21`）：

| 索引 | 易语言名称 | 英文/符号 | 所属数据类型 | 参数 | 返回值 | 当前执行状态 |
|---:|---|---|---|---:|---|---|
| 0 | 开始 | `Start` | `CaptionButton` | 2 个 `SDT_INT` 坐标 | `_SDT_NULL` | 读取 `pArgInf[1/2]`，无动作 |
| 1 | 结束 | `End` | `CaptionButton` | 0 | `_SDT_NULL` | 空函数 |
| 2 | 跟踪 | `Trail` | `CaptionButton` | 2 个 `SDT_INT` 坐标 | `_SDT_NULL` | 读取 `pArgInf[1/2]`，无动作 |
| 3 | 按下 | `DoClick` | `FilenameEdit` | 0 | `_SDT_NULL` | 空函数 |
| 4 | 按下 | `DoClick` | `DirectoryEdit` | 0 | `_SDT_NULL` | 空函数 |
| 5 | 载入文件 | `LoadFromFile` | `TTipOfDay` | 1 个 `SDT_TEXT` 路径 | `SDT_BOOL` | 只读取路径指针，未设置返回值 |
| 6 | 存入文件 | `SaveToFile` | `TTipOfDay` | 1 个 `SDT_TEXT` 路径 | `SDT_BOOL` | 只读取路径指针，未设置返回值 |
| 7 | 打开 | `Execute` | `TTipOfDay` | 0 | `SDT_BOOL` | 空函数，未设置返回值 |
| 8 | 按下 | `DoClick` | `ComboEdit` | 0 | `_SDT_NULL` | 空函数 |

参数存储为一个全局 `ARG_INFO` 数组：0/1 为鼠标横纵坐标，2/3 为跟踪坐标，4 为文件名；命令表通过偏移和数量引用它（`jedi_cmdInfo.cpp:5-26, 38-43`）。

### 4.3 数据类型/组件模型

`g_DataType_jedi_global_var` 注册 6 个 Windows `LDT_WIN_UNIT` 类型（`jedi_dtType.cpp:698-739`）：

| 索引 | 中文名 / 英文名 | 方法索引 | 事件数 | 属性数 | 特殊标志 | 当前状态 |
|---:|---|---|---:|---:|---|---|
| 0 | 鼠标手势框 / `CaptionButton` | 0,1,2 | 9 | 13 | `LDT_WIN_UNIT` | 元数据已注册，创建/属性/事件实现为空壳 |
| 1 | 文件名编辑框 / `FilenameEdit` | 3 | 5 | 69 | `LDT_WIN_UNIT` | 同上 |
| 2 | 目录编辑框 / `DirectoryEdit` | 4 | 5 | 42 | `LDT_WIN_UNIT` | 同上 |
| 3 | 每日一贴 / `TTipOfDay` | 5,6,7 | 2 | 26 | `LDT_WIN_UNIT | LDT_IS_FUNCTION_PROVIDER` | 同上 |
| 4 | 字体选择框 / `FontComboBox` | 无 | 1 | 26 | `LDT_WIN_UNIT` | 无命令，创建/属性/事件实现为空壳 |
| 5 | 带按钮编辑框 / `ComboEdit` | 8 | 1 | 33 | `LDT_WIN_UNIT` | 同上 |

属性数组均以 8 个固定窗口属性开头（位置、尺寸、`tag`、可视、禁止、鼠标指针），随后追加组件专属属性；定义集中在 `jedi_dtType.cpp:279-570`。事件数组集中在 `jedi_dtType.cpp:572-690`，共 23 条 `EVENT_INFO2` 记录。事件描述只进入元数据，源码中没有对 `NRS_EVENT_NOTIFY`/`NRS_EVENT_NOTIFY2` 的实际发射调用。

组件交互 ABI 使用 `ITF_*` 编号（`elib/lib2.h:528-549`）：创建、属性 UI 更新、自定义数据对话框、属性变更、取全部/单个属性、按键询问、语言转换、消息过滤和附加通知接收者。每个 `jedi_GetInterface_*` 只为其中一部分返回函数指针；图标数据、语言转换和消息过滤分支直接落到 `NULL`（例如 `jedi_dtType.cpp:780-808`）。

### 4.4 宿主交换数据模型

`elib/lib2.h` 定义了运行时 ABI 的核心值模型：

- `MDATA_INF`（`elib/lib2.h:780-824`）：用联合体承载字节、整数、浮点、日期、文本、字节集、子程序指针、窗口单元 `MUNIT`、复合数据、数组以及变量地址，再以 `m_dtDataType` 标识实际类型。
- `MUNIT`（`elib/lib2.h:763-767`）：`m_dwFormID` + `m_dwUnitID` 标识窗体组件。
- `UNIT_PROPERTY` 与 `UNIT_PROPERTY_VALUE`（`elib/lib2.h:410-458, 581-663`）：属性元数据与属性值联合体，支持数值、文本、颜色、日期、字体、图片/图标/声音等。
- `EVENT_INFO2`、`EVENT_ARG_INFO2`、`EVENT_NOTIFY2`（`elib/lib2.h:491-522, 903-951`）：事件签名与运行时事件载荷，最多 `MAX_EVENT2_ARG_COUNT=12` 个参数。
- `LIB_DATA_TYPE_INFO`（`elib/lib2.h:693-729`）：把数据类型、成员方法索引、事件、属性和 `PFN_GET_INTERFACE` 绑定在一个登记记录中。

本项目没有数据库、配置文件、持久化实体或自有序列化格式；所有登记数据是进程内静态数组，组件状态若要存在必须由未实现的 `ControlCreate_*`/属性回调自行持有。

## 5. 接口、ABI 与边界

### 5.1 DLL/静态链接边界

- DLL 的唯一显式导出是 `GetNewInf`：`Source_jedi.def:1-4`。
- `GetNewInf` 返回 `PLIB_INFO`，宿主据此获取全部元数据和回调表：`jedi_dllMain.cpp:89-92`。
- `PFN_EXECUTE_CMD` 统一命令签名为 `void(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)`：`elib/lib2.h:1234-1239`。
- 命令符号通过 `__E_FNENAME` 生成 `jedi_<name>_<index>_jedi`，例子和宏见 `jedi_cmd_typedef.h:3-9`；动态/静态构建通过 `DEF_CMD` 等宏区分（`elib/lib2.h:11-43`）。
- `__E_STATIC_LIB` 下，`jedi_cmdInfo.cpp`、`jedi_const.cpp`、`jedi_dtType.cpp` 的 DLL 登记数据被 `#ifndef __E_STATIC_LIB` 排除；`jedi_dllMain.cpp` 的 `DllMain`、`LIB_INFO` 和命令名数组也被排除，但 `jedi_ProcessNotifyLib_jedi` 仍保留。

### 5.2 通知协议

| 方向 | 通知/函数 | 作用 | 当前实现 |
|---|---|---|---|
| 宿主 → 库 | `NL_SYS_NOTIFY_FUNCTION` | 注入 `PFN_NOTIFY_SYS` | 已实现保存并初始化调试/发布版本查询 |
| 库 → 宿主 | `NotifySys` | 通过注入函数发送 `NRS_*` | 已实现转发；未注入时返回 0 |
| 库 → 宿主 | `NRS_MALLOC` / `NRS_MFREE` | 使用易语言内存分配器 | `ealloc`/`efree` 已封装；`ealloc` 未检查空指针后即 `memset` |
| 库 → 宿主 | `NRS_GET_AND_CHECK_UNIT_PTR` | 取组件对象指针 | `GetWndPtr` 有调用封装，但组件创建未实现 |
| 库 → 宿主 | `NRS_EVENT_NOTIFY` / `NRS_EVENT_NOTIFY2` | 抛出事件 | 仅 ABI 声明/常量，仓库未找到实际调用 |
| 宿主 → 库 | `NL_GET_CMD_FUNC_NAMES` | 取命令名数组 | 动态分支返回 `g_cmdNamesjedi` |
| 宿主 → 库 | `NL_GET_NOTIFY_LIB_FUNC_NAME` | 取通知函数名 | 动态分支返回字符串 |
| 宿主 → 库 | `NL_GET_DEPENDENT_LIBS` | 取静态库依赖列表 | 返回 `"\0\0"`，表示无额外支持库 |
| 宿主 → 库 | `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NL_IDE_READY` 等 | 生命周期/IDE 通知 | 分支存在，但当前为空操作 |

### 5.3 IDE 功能边界

`elib/PublicIDEFunctions.h` 定义了通过 `NES_RUN_FUNC` 调用的 IDE 功能，包括光标移动、编辑、文件操作、编译运行、调试、剪贴板、程序文本查询和工作夹等（`elib/PublicIDEFunctions.h:5-7, 140-164, 166-490`）。本仓库没有调用这些 `FN_*` 功能的业务代码，也没有设置 `LBS_IDE_PLUGIN`，所以不能据此宣称已实现 IDE 插件能力。

## 6. 依赖与构建工程

### 6.1 已声明依赖

- Windows SDK / Win32：`elib/lib2.h:61-64` 包含 `windows.h`、`stdio.h`、`math.h`；源码使用窗口、字体、内存、系统颜色和窗口样式 API。
- Visual C++：工程使用 `PlatformToolset=v141`，目标 Windows SDK `10.0.15063.0`，解决方案格式为 Visual Studio 17（`jedi.sln:1-4`；`jedi.vcxproj:43-55`）。
- 语言编码：`__COMPILE_LANG_VER` 固定为 `__GBK_LANG_VER`（`elib/lang.h:8-14`）。
- JEDI/VCL：只在 `m_szExplain` 中作为项目定位文字出现；本仓库没有相应源码/头文件/`.lib`/`.dll`/资源或工程链接项，因此属于**声明/外部前提，未验证**，不是已落地依赖。
- 易语言运行时 ABI：依赖宿主提供 `PFN_NOTIFY_SYS`、内存分配、组件对象、事件和库装载协议；契约由 `elib` 头文件定义。

### 6.2 DLL 工程

`jedi.vcxproj` 将 6 个 `.cpp`（包含 `elib/fnshare.cpp`）和 9 个头文件加入工程，配置 Debug/Release × Win32/x64；Win32 配置声明 `__E_FNENAME=jedi`、`JEDI_EXPORTS` 并使用 `Source_jedi.def`（`jedi.vcxproj:109-157`）。Win32 DLL 输出扩展名为 `.fne`（`jedi.vcxproj:95-102`）。

需要保留的工程风险（未在 Windows/VS 实测）：

1. x64 的预处理定义（`jedi.vcxproj:159-197`）没有 `__E_FNENAME=jedi`，而 `elib/lib2.h:23-25` 明确会因缺少该宏触发 `#error`；
2. x64 Link 配置没有像 Win32 一样设置 `ModuleDefinitionFile=Source_jedi.def`，因此 `GetNewInf` 的 x64 导出行为未确认；
3. x64 配置与 Win32 配置在 ABI/导出定义上不对称，不能仅凭工程文件声称四种配置均可构建。

### 6.3 静态库工程

`jedi_static/jedi_static.vcxproj` 复用上级目录的全部源文件（`jedi_static/jedi_static.vcxproj:21-38`），输出类型为 `StaticLibrary`（`jedi_static/jedi_static.vcxproj:48-72`）；Win32 Debug/Release 定义 `__E_STATIC_LIB;__E_FNENAME=jedi`（`...:92-128`）。

静态库工程的未验证风险：

- x64 配置的预处理定义（`...:130-155`）没有 `__E_FNENAME=jedi`；
- x64 配置使用 `PrecompiledHeader=Use` 和 `pch.h`，但仓库文件清单中没有 `pch.h`（`...:130-138, 145-154`；Git 跟踪文件共 23 个）；
- 静态库排除了 DLL 登记数组，宿主如何获得组件/命令元数据不由本仓库说明，需要外部静态链接集成契约。

## 7. 已实现、仅声明与未验证矩阵

| 能力 | 结论 | 证据与边界 |
|---|---|---|
| `GetNewInf` 导出和 `LIB_INFO` 组装 | **已实现（动态源码路径）** | `.def` + `jedi_dllMain.cpp:31-92`；未在 Windows DLL 中实测 |
| 9 条命令元数据及函数指针映射 | **已实现元数据/函数符号；行为仅部分空壳** | `jedi_cmd_typedef.h`、`jedi_cmdInfo.cpp`、`jedi_dllMain.cpp:26-29` |
| 命令实际文件载入、保存、窗口打开、鼠标手势 | **仅声明/未实现** | `jedi_cmdDef.cpp:6-70` 只读取参数或空函数，无 Win32/VCL/JEDI 调用、无返回值写入 |
| 6 个组件名称、属性、事件、方法登记 | **已实现静态登记** | `jedi_dtType.cpp:243-741` |
| 6 个组件实际创建 | **未实现** | 6 个 `jedi_ControlCreate_*` 均返回 `0`，例如 `jedi_dtType.cpp:811-828` |
| 属性更新 UI | **模板默认行为** | 6 个 `jedi_PropUpDate_*` 返回 `TRUE`，没有按属性判断 |
| 属性变更 | **未实现** | `jedi_PropChanged_*` 只有空 `switch`，通常返回 `false` |
| 属性读取/整体序列化 | **未实现** | `jedi_PropGetDataAll_*` 返回 `0`；`jedi_PropGetData_*` 不填值即返回 `true`；`untshare.h:30-64` 的序列化也为空 |
| 事件触发 | **仅声明** | `EVENT_INFO2` 元数据存在；未找到 `NRS_EVENT_NOTIFY`/`NRS_EVENT_NOTIFY2` 调用 |
| IDE AddIn | **未启用** | `m_pfnRunAddInFn=NULL`、没有 `LBS_IDE_PLUGIN`（`jedi_dllMain.cpp:47,68-73`） |
| 外部 JEDI/VCL 封装 | **未验证且源码未落地** | 只有说明字符串；工程未链接第三方实现 |
| 内存/宿主通知辅助 | **部分已实现** | `elib/fnshare.cpp:11-70`；未建立空指针、并发和宿主生命周期保障 |
| DLL/静态库四配置构建 | **未验证** | 当前环境为 macOS，无 Visual Studio/MSBuild/Windows 易语言宿主；工程 x64 还有上述配置缺口 |

## 8. 生命周期、错误处理与风险

1. **库加载阶段**：宿主应先读取 `LIB_INFO`，再以 `NL_SYS_NOTIFY_FUNCTION` 注入通知函数；`s_pfnNotifySys` 是进程内静态全局变量，没有锁或多宿主隔离（`elib/fnshare.cpp:7-16, 24-36`）。
2. **版本识别**：第一次收到系统通知时，如果调试版本值仍为 `1253600`，会调用 `NRS_GET_PRG_TYPE` 更新 `s_isDebug`；这是当前唯一明确的宿主运行时查询路径（`elib/fnshare.cpp:7-21`）。
3. **内存契约**：`ealloc` 使用 `NRS_MALLOC` 后立即 `memset`，分配失败且返回 `NULL` 时存在未检查风险；`CloneTextData`、`CloneBinData`、`CloneTextDataW`、`GetBinData` 依赖宿主分配器（`elib/fnshare.h:25-140`）。
4. **组件对象生命周期**：创建回调不返回有效 `HUNIT`，因此 `NRS_GET_AND_CHECK_UNIT_PTR`、属性实际读写、消息过滤和事件触发均没有可验证的对象状态基础。
5. **错误处理**：`jedi_ProcessNotifyLib_jedi` 对未知通知返回 `NR_ERR`，已列通知大多返回 `NR_OK` 或空操作；命令函数没有参数数量/类型校验，没有设置 `pRetData` 的成功或失败值。
6. **资源/序列化**：`CPropertyInfo::SaveData` 返回空句柄，`LoadData` 对有效输入仍直接返回 `TRUE`，`LoadIco` 始终返回 `NULL`，`SerializeCString` 为空实现（`elib/untshare.h:14-69, 180-195, 198-271`）。
7. **线程与重入**：仓库未提供线程模型、锁、消息队列或异步任务；不能假定命令、通知和属性回调可并发安全。
8. **平台边界**：登记和所有数据类型均标记 Windows；`elib/lib2.h` 直接包含 Win32 头并使用 Windows API，非 Windows 构建未声明支持。

## 9. 测试、验证与当前基线

### 9.1 测试现状

- Git 跟踪文件中没有 `test/`、`tests/`、单元测试源、集成测试、CI 配置或测试数据。
- 工程文件只有 Visual Studio 构建配置，没有可执行的测试目标或测试命令。
- 本次没有在 macOS 上伪造 Windows 编译结果，也没有启动易语言 IDE/运行时；因此“测试通过”不能成立。

### 9.2 本轮已做的静态验证

| 验证项 | 结果 | 证据/说明 |
|---|---|---|
| 仓库身份 | 通过 | 目标路径为 `.../Gitee_精易官方/jedi`，Git 远程为 `https://gitee.com/JYtechnology/jedi.git` |
| 工作树基线 | 通过（建档前） | `git status --short --branch` 为 `## master...origin/master`，无变更 |
| 远程基线 | 通过 | `git ls-remote origin HEAD refs/heads/master` 与本地均为 `e509cdc3b7ca683242ff1208ad43a13ed4cae810` |
| 提交历史 | 已确认 | 单个 grafted 初始化提交，时间 `2022-12-19T16:12:38+08:00`，作者“精易科技” |
| 源码清单 | 通过 | `git ls-files` 共 23 个文件；无 README、测试和旧细探文件 |
| 工程 XML 可读性 | 已人工读取 | `jedi.sln`、两个 `.vcxproj`、两个 `.filters`、两个 `.user` 已读取；未运行 MSBuild |
| 元数据规模 | 静态确认 | 9 条命令、6 个数据类型、23 个事件；数组和 count 均由源码 `sizeof` 计算 |
| 真实运行路径 | 未验证 | 需要 Windows + 对应 VS 工具链 + 易语言宿主；本机 macOS 不具备该运行环境 |

## 10. Git 基线与证据路径

### 10.1 Git 基线

- 远程：`https://gitee.com/JYtechnology/jedi.git`
- 分支：`master`，跟踪 `origin/master`
- 本地/远程 HEAD：`e509cdc3b7ca683242ff1208ad43a13ed4cae810`
- 提交主题：`初始化仓库`
- 作者：`精易科技 <413188828@qq.com>`
- 提交时间：`2022-12-19T16:12:38+08:00`
- 历史形态：单个 grafted/shallow 初始化提交；没有可供比较的旧实现历史
- 建档前工作树：干净
- 本轮允许的唯一仓库变更：根目录 `ARCHITECTURE.md`

### 10.2 证据索引

- 库入口与导出：`Source_jedi.def:1-4`、`jedi_dllMain.cpp:31-123`
- 生命周期通知：`jedi_dllMain.cpp:101-178`、`elib/fnshare.cpp:7-71`
- 命令定义与参数：`jedi_cmd_typedef.h:1-22`、`jedi_cmdInfo.cpp:5-45`、`jedi_cmdDef.cpp:1-73`
- 数据类型/属性/事件/组件回调：`jedi_dtType.cpp:243-741`、`jedi_dtType.cpp:745-1830`
- ABI 数据结构：`elib/lib2.h:158-364`、`elib/lib2.h:410-729`、`elib/lib2.h:763-951`、`elib/lib2.h:960-1318`
- 内存和通用辅助：`elib/fnshare.h:20-240`、`elib/untshare.h:14-337`
- IDE 功能协议：`elib/PublicIDEFunctions.h:1-493`
- 工程与配置：`jedi.sln:1-40`、`jedi.vcxproj:1-202`、`jedi_static/jedi_static.vcxproj:1-167`、对应 `.filters`/`.user`
- 语言与基础类型：`elib/lang.h:1-18`、`elib/mtypes.h:1-176`、`elib/krnllib.h:1-133`

## 11. 后续复核边界

后续轮次应沿同一 `ARCHITECTURE.md` 增量补证，不将下列事项提前写成已实现：

1. 在 Windows + Visual Studio 中逐配置验证 x86/x64 Debug/Release，先修复或确认 `__E_FNENAME`、`.def` 导出和静态库 `pch.h` 配置。
2. 取得真实 JEDI/VCL 依赖来源，确认是否存在许可、版本、二进制链接和组件类映射；当前仓库无法证明这些内容。
3. 为每个 `ControlCreate_*` 建立真实窗口对象、属性持有、销毁和 `HUNIT` 映射，再验证 `ITF_*` 全部回调。
4. 为 9 个命令补齐参数校验、返回值、文件/窗口/手势业务逻辑，并在易语言宿主中验证命令索引与运行时行为。
5. 将事件元数据与实际 `NRS_EVENT_NOTIFY2` 触发链逐一对齐，验证事件参数数量和 `EVENT_ARG_INFO2` 偏移；当前部分空参数数组使用 `+1` 偏移，需由宿主 ABI 复核。
6. 增加不依赖正式易语言宿主的 ABI/元数据静态测试，再增加 Windows 宿主集成测试；测试结果必须单独记录，不能用本架构文档中的静态读取替代。
7. 复核内存失败、组件销毁、重复加载/卸载、线程并发和跨语言编码边界，尤其是 `ealloc` 空指针、文本/字节集释放和属性序列化。
