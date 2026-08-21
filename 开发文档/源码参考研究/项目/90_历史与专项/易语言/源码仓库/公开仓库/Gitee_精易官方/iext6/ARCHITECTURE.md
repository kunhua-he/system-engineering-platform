# iext6 架构建档

> 本文是 `iext6` 当前本地源码快照的唯一架构说明。本文只记录源码和工程文件已经给出的事实；“已实现”“仅声明”“未验证”严格区分。源码参考仓库按只读研究处理，本轮只新增本文件，未修改源码、工程、依赖、测试、配置或 Git 历史。

## 1. 项目定位

`iext6` 是一个面向易语言的 Windows 可视化支持库工程，库名为“扩展界面支持库六”，目标是向易语言 IDE/运行时注册一个名为“多功能条”（英文名 `SuperBar`）的窗口单元，并提供该组件的属性、事件和组件交互接口。

当前快照是精易官方 Gitee 仓库的初始化骨架（提交时间为 2022-12-19）。元信息已经声明为 2.0.0、要求易语言系统 3.7 及系统核心支持库 3.7、GBK 语言、Windows 平台；但组件创建、属性数据持久化、属性变更联动、事件触发和实际窗口绘制等运行行为仍是模板/占位实现，不能把元信息注册完成等同于组件功能完成。

### 1.1 当前事实摘要

| 项目 | 当前事实 | 状态 |
|---|---|---|
| 支持库入口 | 导出 `GetNewInf`，返回静态 `LIB_INFO` | 已实现 |
| 支持库标识 | GUID `{E60056EA-07A8-4bf5-B6F0-DF05DE6FAE1F}`，版本 2.0.0 | 已实现（声明层） |
| 支持平台 | `__OS_WIN`，动态工程目标扩展名 `.fne` | 已实现（声明层） |
| 自定义数据类型 | 1 个：`多功能条` / `SuperBar` | 已实现（声明层） |
| 全局命令 | 1 个隐藏命令“无法识别的名字_0” | 仅声明；执行体为空 |
| 组件属性 | 8 个易语言固定属性 + 60 个组件自定义属性，共 68 项 | 已实现（元数据表）；读写逻辑未完成 |
| 组件事件 | `位置被改变`、`左按钮被单击`、`右按钮被单击` | 已实现（元数据表）；触发逻辑未实现 |
| 组件创建 | `iext6_ControlCreate_SuperBar` 固定返回 0 | 未实现 |
| 属性数据获取 | 全量获取固定返回 0；单项获取为占位分支 | 未实现 |
| 属性变更 | 仅索引 0 进入空分支，其余拒绝；没有合法性校验和状态更新 | 未实现 |
| 析构/释放 | 没有组件对象和资源管理实现 | 未实现 |
| 测试 | 仓库内未发现测试目录或测试文件 | 未提供/未验证 |
| 可构建性 | 工程文件存在，但当前环境为 macOS，不能据此验证 Visual Studio/MSVC 构建 | 未验证 |

## 2. 架构流程图

```text
易语言 IDE / 易语言运行时
        │
        │ LoadLibrary / 支持库装载
        ▼
Source_iext6.def
        │  导出固定入口 GetNewInf
        ▼
iext6_dllMain.cpp
        │  组装 LIB_INFO
        │  提供 iext6_ProcessNotifyLib_iext6
        ▼
LIB_INFO
 ├── 1 个命令元数据 → g_cmdInfo_iext6_global_var
 ├── 1 个命令函数指针 → g_cmdInfo_iext6_global_var_fun
 ├── 1 个自定义类型 → g_DataType_iext6_global_var
 │       └── 多功能条 / SuperBar
 │             ├── 68 个属性元数据
 │             ├── 3 个事件元数据
 │             └── iext6_GetInterface_SuperBar
 └── 系统通知回调 → iext6_ProcessNotifyLib_iext6
                         │ NL_SYS_NOTIFY_FUNCTION
                         ▼
                   elib/fnshare.cpp
                         │ 保存 PFN_NOTIFY_SYS
                         │ NotifySys / ProcessNotifyLib
                         ▼
                   易语言系统通知服务

组件创建/运行路径（当前为占位）

IDE 拖放组件
      │
      ▼
iext6_ControlCreate_SuperBar(...)
      │ 当前固定返回 0
      ▼
未创建 HUNIT，后续属性/事件路径无法形成完整运行闭环

组件交互路径（接口已登记，主体未完成）

易语言系统 → iext6_GetInterface_SuperBar(接口号)
      ├── ITF_CREATE_UNIT             → 创建函数（占位）
      ├── ITF_PROPERTY_UPDATE_UI     → 当前总是 TRUE
      ├── ITF_DLG_INIT_CUSTOMIZE_DATA→ 当前 pblModified=false、返回 FALSE
      ├── ITF_NOTIFY_PROPERTY_CHANGED→ 当前仅空分支/默认 FALSE
      ├── ITF_GET_ALL_PROPERTY_DATA  → 当前返回 0
      ├── ITF_GET_PROPERTY_DATA      → 当前占位并总返回 TRUE（索引非法除外）
      ├── ITF_IS_NEED_THIS_KEY       → 当前总是 FALSE
      └── ITF_GET_NOTIFY_RECEIVER    → 默认尺寸通知当前返回 0
```

### 2.1 核心数据流

1. **装载数据流**：易语言 IDE/运行时读取 `Source_iext6.def` 的 `GetNewInf` → 取得 `LIB_INFO` → 按 `m_nDataTypeCount`、`m_nCmdCount` 和对应指针读取 `SuperBar` 类型、命令及属性/事件元数据。
2. **命令数据流**：调用方按 `CMD_INFO` 的参数描述构造 `MDATA_INF` → 进入 `g_cmdInfo_iext6_global_var_fun[0]` 指向的 `iext6__bunengshibie__0_iext6` → 当前只读取 `pArgInf[1].m_pText`，没有向 `pRetData` 写回结果。
3. **组件数据流（设计意图）**：IDE 拖放组件 → `ITF_CREATE_UNIT` → `iext6_ControlCreate_SuperBar` → 返回 `HUNIT` → 通过属性接口读写组件状态 → 通过 `EVENT_NOTIFY2` 通知位置/按钮事件。当前创建函数返回 0，后续链路尚未建立。
4. **属性数据流（当前可见边界）**：易语言系统传入属性索引和值 → `iext6_PropChanged_SuperBar`；或请求属性值 → `iext6_PropGetData_SuperBar`。源码没有内部属性状态容器、序列化缓冲区或真实控件对象，因此元数据之外的数据流未实现。
5. **系统通知数据流**：易语言系统发送 `NL_SYS_NOTIFY_FUNCTION` → `iext6_ProcessNotifyLib_iext6` → `ProcessNotifyLib` 保存 `PFN_NOTIFY_SYS` → 后续 `NotifySys` 转发内存分配、事件、程序类型等通知；回调未设置时辅助函数返回 0。

## 3. 真实目录与模块地图

仓库当前 Git 追踪文件共 23 个，源码/工程文本总计约 4,415 行；没有 README、测试目录、文档目录或额外资源目录。

```text
iext6/
├── ARCHITECTURE.md                 # 本轮新增；项目架构唯一说明
├── Source_iext6.def                # DLL 模块定义，导出 GetNewInf
├── iext6.sln                       # Visual Studio 解决方案，含动态库与静态库两个项目
├── iext6.vcxproj                   # 动态支持库工程
├── iext6.vcxproj.filters           # 动态工程文件筛选器
├── iext6.vcxproj.user              # 动态工程用户配置，占位
├── iext6_static/
│   ├── iext6_static.vcxproj        # 静态库工程，复用上级源码
│   ├── iext6_static.vcxproj.filters
│   └── iext6_static.vcxproj.user
├── include_iext6_header.h          # 本项目统一头文件和命令声明
├── iext6_cmd_typedef.h             # 命令名拼接和 IEXT6_DEF 命令清单
├── iext6_cmdInfo.cpp               # 命令参数表、命令元数据表、命令数量
├── iext6_cmdDef.cpp                # 命令执行函数体（当前为空壳）
├── iext6_const.cpp                 # 常量表（当前数量为 0）
├── iext6_dllMain.cpp               # DLL 入口、LIB_INFO、系统通知回调、静态编译名表
├── iext6_dtType.cpp                # SuperBar 类型、属性/事件元数据、组件接口回调
└── elib/
    ├── lib2.h                      # 易语言支持库 ABI、数据类型、通知码、LIB_INFO
    ├── mtypes.h                    # 跨编译环境基础类型和句柄类型
    ├── lang.h                      # 编译语言版本（GBK）
    ├── krnllib.h                   # 系统核心支持库标识和版本常量
    ├── fnshare.h                   # 系统通知、内存、数组/文本辅助函数
    ├── fnshare.cpp                 # 通知函数指针和调试版本转发状态
    ├── untshare.h                  # 组件共享辅助函数及占位类/宏
    └── PublicIDEFunctions.h        # IDE AddIn 功能号声明（当前未接入）
```

### 3.1 模块职责与证据

| 模块 | 职责 | 关键证据 | 状态 |
|---|---|---|---|
| `Source_iext6.def` | DLL 导出固定入口 | `EXPORTS GetNewInf` | 已实现 |
| `iext6_dllMain.cpp` | 建立库级元信息、命令函数指针表、响应系统通知 | `g_LibInfo_iext6_global_var`、`GetNewInf`、`iext6_ProcessNotifyLib_iext6` | 元数据已实现；生命周期处理为空 |
| `iext6_cmd_typedef.h` | 用 `IEXT6_DEF` 作为单一命令清单，供声明/元数据/函数名数组复用 | `IEXT6_DEF(_MAKE)` | 已实现（仅 1 个占位命令） |
| `iext6_cmdInfo.cpp` | 定义参数描述和 `CMD_INFO` 数组 | `g_argumentInfo_iext6_global_var`、`g_cmdInfo_iext6_global_var` | 元数据已实现 |
| `iext6_cmdDef.cpp` | 执行库命令 | `iext6__bunengshibie__0_iext6` | 仅声明/空实现，未写返回数据 |
| `iext6_const.cpp` | 注册库常量 | `g_ConstInfo_iext6_global_var_count = 0` | 已明确无常量 |
| `iext6_dtType.cpp` | 注册 `SuperBar`、属性、事件、接口分发和回调 | `g_DataType_iext6_global_var`、`iext6_GetInterface_SuperBar` | 元数据/接口骨架已实现，业务逻辑未实现 |
| `elib/fnshare.cpp/.h` | 保存系统回调，转发通知，封装易语言内存/数组/文本 ABI | `s_pfnNotifySys`、`ProcessNotifyLib`、`ealloc` 等 | 部分辅助实现；未在本环境验证 ABI |
| `elib/lib2.h` | 外部 ABI 契约，不是本项目业务模块 | `LIB_INFO`、`MDATA_INF`、`LIB_DATA_TYPE_INFO`、`PFN_*` | 声明/辅助实现混合 |
| `elib/untshare.h` | 通用组件辅助模板和 Windows 操作辅助 | `CPropertyInfo`、`ModiUnitStyle`、`LoadIco` | 多处为空壳或注释代码，当前 SuperBar 未调用 |
| `.vcxproj/.sln` | 声明动态/静态构建矩阵和源码清单 | `ConfigurationType`、`PlatformToolset`、`ClCompile` | 工程声明存在，未验证构建 |

## 4. 核心数据模型

### 4.1 支持库级模型：`LIB_INFO`

`iext6_dllMain.cpp:31-87` 构造一个静态 `LIB_INFO`：

- `m_dwLibFormatVer = LIB_FORMAT_VER`，来自 `elib/lib2.h`，值为 `20000101`；
- `m_szGuid` 固定为 `{E60056EA-07A8-4bf5-B6F0-DF05DE6FAE1F}`；
- 版本为 `2.0.0`；
- 需要易语言系统 `3.7`、系统核心支持库 `3.7`；
- 名称“扩展界面支持库六”，解释为提供“多功能条”控件；
- 语言为 `__GBK_LANG_VER`；
- 状态为 `_LIB_OS(__OS_WIN)`；
- 自定义数据类型指向 `g_DataType_iext6_global_var`；
- 命令指向 `g_cmdInfo_iext6_global_var` 及 `g_cmdInfo_iext6_global_var_fun`；
- AddIn、超级模板、依赖文件、全局命令分类均为 `NULL`/0；
- 常量数量为 0；
- 系统通知回调为 `iext6_ProcessNotifyLib_iext6`。

这说明支持库装载协议的数据入口是完整的，但并不证明 `SuperBar` 的运行功能已经完成。

### 4.2 命令模型：`CMD_INFO` + `ARG_INFO`

`iext6_cmd_typedef.h:12-13` 通过宏清单声明 1 个命令：

- 中文名：`无法识别的名字_0`；
- 英文基名：`_bunengshibie_`；
- 组合后的导出/静态名：`iext6__bunengshibie__0_iext6`；
- 分类：`-1`，表示对象成员命令；
- 状态：Windows + `CT_IS_HIDED`，即隐藏；
- 返回类型：`SDT_BOOL`；
- 参数数量：1；
- 参数表起点：`g_argumentInfo_iext6_global_var + 0`。

`iext6_cmdInfo.cpp:5-20` 的唯一参数项为 `{NULL, NULL, 0, 0, SDT_TEXT, 0, NULL}`：参数名、说明、默认值和标志均为空/0，类型为 `SDT_TEXT`。`iext6_cmdDef.cpp:6-10` 中只读取 `pArgInf[1].m_pText` 到局部变量 `arg1`，没有设置 `pRetData`，也没有真实命令逻辑。因此当前只能确认命令元数据和符号存在，不能确认命令可用。

### 4.3 自定义类型模型：`LIB_DATA_TYPE_INFO`

`iext6_dtType.cpp:152-166` 注册单个库数据类型：

- 中文名：`多功能条`；
- 英文名：`SuperBar`；
- 标志：`_DT_OS(__OS_WIN) | LDT_WIN_UNIT`，表示 Windows 窗口单元；
- 成员命令数量：1，索引数组只有 `0`；
- 事件数量：3；
- 属性数量：68；
- 交互函数：`iext6_GetInterface_SuperBar`；
- 非窗口成员数组为空。

### 4.4 属性模型：68 项

属性元数据位于 `iext6_dtType.cpp:52-131`：

1. **固定属性 8 项**：左边、顶边、宽度、高度、标记、可视、禁止、鼠标指针。
2. **组件自定义属性 60 项（索引 0-59）**：
   - 外观/基础：类型、方向、风格；
   - 范围/行为：页改变值、行改变值、最小位置、最大位置、位置、显示百分比、允许用户调节、允许拖动跟踪、自动背景高度；
   - 两端区域：`Ends_`、显示两端按钮、两端按钮图片组；
   - 后台区域：`BackGround_`、显示后台、后台图片组、后台图片显示方式、显示后台两端、显示后台中间、缩进后台两端；
   - 前台区域：`ForeGround_`、显示前台、前台图片组、前台图片显示方式、显示前台两端、显示前台中间；
   - 中台区域：`CenterGround_`、显示中台、中台图片组、中台图片显示方式、显示中台两端、显示中台中间、自动伸缩中台；
   - 若干 Windows 隐藏保留槽位，以 `NULL` 名称和 `UW_IS_HIDED` 表示。

属性类型使用易语言支持库 ABI 中的 `UD_INT`、`UD_BOOL`、`UD_TEXT`、`UD_CURSOR`、`UD_PICK_INT`、`UD_FONT`、`UD_IMAGE_LIST` 等。选项属性的候选文本直接以 `\0` 分隔字符串存放。属性表是编辑器可见契约；源码没有相应的内部状态结构、序列化格式或真正的控件句柄存储。

### 4.5 事件模型：3 项

`iext6_dtType.cpp:134-150` 定义 `EVENT_INFO2`：

- `位置被改变`：无参数，无返回值；
- `左按钮被单击`：无参数，返回 `SDT_BOOL`；返回真或不返回值时位置减少行改变值，返回假时动作被忽略（语义写在元数据说明中，源码没有触发实现）；
- `右按钮被单击`：无参数，返回 `SDT_BOOL`；返回真或不返回值时位置增加行改变值，返回假时动作被忽略（同样只有声明）。

### 4.6 运行时数据模型：`HUNIT` 与 `MDATA_INF`

外部 ABI 在 `elib/lib2.h` 中定义：

- `HUNIT` 是组件句柄（`DWORD`）；
- `MDATA_INF` 是命令输入/输出数据容器，包含基础数值、文本、字节集、数组、复合数据、窗口单元及变量地址联合体，并以 `m_dtDataType` 标识数据类型；
- `UNIT_PROPERTY_VALUE` 是属性读写值联合体；
- `EVENT_NOTIFY2` 是第二类事件通知载体，支持最多 `MAX_EVENT2_ARG_COUNT=12` 个参数。

本仓库只使用这些类型签名，未实现从 `HUNIT` 到内部窗口对象、属性存储和事件派发队列的具体映射。

## 5. 接口与调用边界

### 5.1 DLL/静态库入口

| 接口 | 位置 | 语义 | 状态 |
|---|---|---|---|
| `GetNewInf()` | `iext6_dllMain.cpp:89-92`；`Source_iext6.def:3-4` 导出 | 返回 `LIB_INFO*` | 已实现 |
| `iext6_ProcessNotifyLib_iext6(INT,DWORD,DWORD)` | `iext6_dllMain.cpp:101-178` | 接收系统通知；动态库场景返回命令函数名表、通知函数名和依赖串，并转发系统通知 | 部分实现 |
| `iext6_GetInterface_SuperBar(INT)` | `iext6_dtType.cpp:171-234` | 按 `ITF_*` 编号返回组件交互函数指针 | 接口表已实现，具体行为多为空壳 |

### 5.2 系统通知

`iext6_ProcessNotifyLib_iext6` 当前处理：

- `NL_GET_CMD_FUNC_NAMES`：返回 `g_cmdNamesiext6`；
- `NL_GET_NOTIFY_LIB_FUNC_NAME`：返回字符串 `iext6_ProcessNotifyLib_iext6`；
- `NL_GET_DEPENDENT_LIBS`：返回 `"\0\0"`，表示没有额外静态库依赖；
- `NL_SYS_NOTIFY_FUNCTION`：调用 `ProcessNotifyLib`，将系统通知函数指针交给 `elib/fnshare.cpp`；
- `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NR_DELAY_FREE`、`NL_IDE_READY`、`NL_RIGHT_POPUP_MENU_SHOW`、`NL_ADD_NEW_ELEMENT`：空处理；
- 未知消息：返回 `NR_ERR`。

`elib/fnshare.cpp:24-64` 的 `ProcessNotifyLib` 在收到 `NL_SYS_NOTIFY_FUNCTION` 时保存 `PFN_NOTIFY_SYS`，首次通过 `NRS_GET_PRG_TYPE` 查询程序类型，并可调用用户设置的通知回调。`NotifySys` 仅在回调非空时转发；回调未初始化时返回 0。内存和数组辅助函数在 `elib/fnshare.h` 中通过 `NotifySys(NRS_MALLOC/NRS_MFREE)` 与易语言运行时交互。

### 5.3 组件交互接口

`iext6_GetInterface_SuperBar` 已登记的接口如下：

| 编号 | 接口 | 返回函数 | 当前行为 |
|---:|---|---|---|
| 1 | `ITF_CREATE_UNIT` | `iext6_ControlCreate_SuperBar` | 固定返回 0，未创建窗口 |
| 2 | `ITF_PROPERTY_UPDATE_UI` | `iext6_PropUpDate_SuperBar` | 无条件返回 `TRUE` |
| 3 | `ITF_DLG_INIT_CUSTOMIZE_DATA` | `iext6_PropPopDlg_SuperBar` | 写 `*pblModified=false`，返回 `FALSE`；未检查空指针 |
| 4 | `ITF_NOTIFY_PROPERTY_CHANGED` | `iext6_PropChanged_SuperBar` | 仅对索引 0 进入空分支，其余 `FALSE`，无值校验 |
| 5 | `ITF_GET_ALL_PROPERTY_DATA` | `iext6_PropGetDataAll_SuperBar` | 固定返回 0 |
| 6 | `ITF_GET_PROPERTY_DATA` | `iext6_PropGetData_SuperBar` | 默认路径返回 `FALSE`；索引 0 空分支后返回 `TRUE`，没有填充值 |
| 7 | `ITF_GET_ICON_PROPERTY_DATA` | 无 | `switch` 空分支，最终 `NULL` |
| 8 | `ITF_IS_NEED_THIS_KEY` | `iext6_PropKetInfo_SuperBar` | 固定返回 `FALSE` |
| 9 | `ITF_LANG_CNV` | 无 | 未实现，返回 `NULL` |
| 11 | `ITF_MSG_FILTER` | 无 | 未实现，返回 `NULL` |
| 12 | `ITF_GET_NOTIFY_RECEIVER` | `iext6_PropNotifyReceiver_SuperBar` | 仅识别默认尺寸消息，但仍返回 0 |

注意：`iext6_PropPopDlg_SuperBar` 直接解引用 `pblModified`，调用方若传空指针会产生未定义行为；这是源码可见风险，尚未运行验证。

## 6. 构建与依赖边界

### 6.1 动态库工程

`iext6.vcxproj` 声明：

- Visual Studio C++ 工程，`VCProjectVersion=16.0`；
- `WindowsTargetPlatformVersion=10.0.15063.0`；
- `PlatformToolset=v141`；
- `Debug/Release × Win32/x64` 四种配置；
- 配置类型为 `DynamicLibrary`；
- Win32 Debug/Release 使用 `__E_FNENAME=iext6`，目标扩展名为 `.fne`；
- Win32 使用 `Source_iext6.def`；x64 配置中没有显式 `ModuleDefinitionFile` 和 `TargetExt`；
- 运行库为静态多线程（Debug `MultiThreadedDebug`，Release `MultiThreaded`）；
- 源文件为 6 个 `.cpp`：`elib/fnshare.cpp`、`iext6_cmdDef.cpp`、`iext6_const.cpp`、`iext6_dllMain.cpp`、`iext6_dtType.cpp`、`iext6_cmdInfo.cpp`；
- 头文件包含 `elib` 下的 ABI/辅助头及项目头。

### 6.2 静态库工程

`iext6_static/iext6_static.vcxproj` 复用上级全部 6 个 `.cpp` 和 9 个头文件，配置类型为 `StaticLibrary`，Win32 Debug/Release 定义 `__E_STATIC_LIB;__E_FNENAME=iext6`。`iext6_dllMain.cpp`、`iext6_cmdInfo.cpp`、`iext6_const.cpp` 中多处以 `#ifndef __E_STATIC_LIB` 排除动态库元数据，`iext6_cmd_typedef.h` 和 `iext6_dllMain.cpp` 仍生成静态链接所需的函数名信息。

解决方案 `iext6.sln` 同时包含动态项目 `iext6` 和静态项目 `iext6_static`，并将 x86 映射到 Win32。

### 6.3 外部依赖

源码直接依赖：

- Windows API/类型：`windows.h`、窗口句柄、`GetWindowLongW`、`SetWindowLongW`、`SystemParametersInfoW`、字体和窗口样式 API 等；
- C/C++ 运行库：`stdio.h`、`math.h`、`time.h`、字符串/内存函数；
- 易语言 SDK/ABI：仓库内 `elib/lib2.h`、`mtypes.h`、`krnllib.h`、`lang.h` 等头文件；
- 编译工具链：Visual Studio C++ v141 与 Windows SDK 10.0.15063.0（工程声明）。

未发现第三方包管理文件、NuGet/vcpkg 清单、运行时配置或外部服务依赖。`m_szzDependFiles` 与 `NL_GET_DEPENDENT_LIBS` 均声明无额外支持文件。

## 7. 已实现、仅声明、未验证清单

### 7.1 源码已经实现

- DLL 固定导出 `GetNewInf`；
- 静态 `LIB_INFO` 元数据组装；
- 命令清单宏、命令信息表、命令函数名表；
- `SuperBar` 类型的属性/事件元数据表；
- `ITF_*` 接口号到函数指针的分发骨架；
- 系统通知函数指针的保存与基础转发；
- 易语言内存、文本、字节集、数组辅助函数的源码封装（是否可与目标运行时 ABI 正常协作仍未验证）；
- 动态/静态两个 Visual Studio 项目的文件清单和配置声明。

### 7.2 仅声明或占位

- “多功能条”实际窗口类、窗口创建和 `HUNIT` 生命周期；
- 属性内部状态、默认值装载、全量属性序列化、单项属性读回；
- 属性修改后的范围校验、联动更新、窗口重建判断和提示文本；
- 两端/后台/前台/中台图片组解析、绘制、方向旋转和拉伸；
- 位置变化、左右按钮点击的鼠标/键盘消息处理与 `NRS_EVENT_NOTIFY2` 事件派发；
- 自定义属性对话框、图标数据、语言转换、消息过滤、按键拦截；
- 隐藏命令 `无法识别的名字_0` 的真实命令语义；
- 常量、AddIn、超级模板、依赖文件内容；
- `CPropertyInfo` 序列化、`LoadIco` 图标解析等共享辅助能力的完整实现。

### 7.3 当前无法验证

- Windows/MSVC 下动态 `.fne` 是否能成功编译、链接并由易语言装载；
- x64 配置是否能得到正确的库后缀、导出入口和 ABI；
- `GetNewInf` 返回结构在真实易语言系统中的兼容性；
- `MDATA_INF`、`UNIT_PROPERTY_VALUE`、`HUNIT` 与易语言运行时的真实内存布局协作；
- 支持库被 IDE 拖放、保存/重新打开工程、编译和运行；
- 事件回调、属性数据交换和释放是否符合易语言生命周期；
- 任意输入下的空指针、越界、属性索引和资源释放行为。

## 8. 测试与验证现状

仓库文件清单中没有 `tests`、`test`、测试工程、CI 配置、构建脚本或测试说明。当前没有可复制的仓库内自动化测试命令。

本轮执行的是静态人工架构取证，而不是编译或运行测试：

- 人工读取了项目所有源码/头文件/工程/解决方案/DEF 文件；
- 通过 Git 现场核对仓库状态、提交、远程和树；
- 通过源码行号核对命令、属性、事件和接口数量；
- 未在 macOS 上运行 Windows/MSVC 构建；
- 未启动易语言 IDE/运行时；
- 未安装依赖、未生成构建产物、未修改原始源码。

因此本文中的“已实现”主要指静态代码中存在真实定义或元数据注册；不代表跨进程、跨 ABI 或真实 IDE 场景已经通过。

## 9. 风险与后续复核点

1. **主功能尚未闭环**：创建函数返回 0，属性数据全量读取返回 0，事件没有触发路径，当前更接近支持库模板而不是可运行控件。
2. **命令返回未填充**：命令声明返回 `SDT_BOOL`，执行体没有设置 `pRetData`，若被实际调用，返回值语义未定义。
3. **属性接口数据未填充**：`iext6_PropGetData_SuperBar` 在索引 0 路径返回成功但不写 `pPropertyVaule`，可能向 IDE 暴露未初始化数据。
4. **空指针风险**：`iext6_PropPopDlg_SuperBar` 未检查 `pblModified`；其他接口也没有系统性校验句柄、属性指针和数据尺寸。
5. **索引/数量契约需复核**：自定义属性索引从 0 开始，固定属性占前 8 项；后续实现必须确认易语言 ABI 对属性索引的调用约定，避免把固定属性和自定义属性错位。
6. **x64 工程配置不完整迹象**：动态工程 x64 配置没有显式 `__E_FNENAME=iext6`、`.fne` 目标扩展名和 DEF 文件设置；这是工程文本可见风险，是否由默认设置补齐尚未验证。
7. **Windows 类型与 64 位兼容性**：`elib/mtypes.h` 将 `DWORD` 定义为 `unsigned long`，并大量使用 `DWORD` 承载句柄/指针和回调参数；在 x64 ABI 下需要由真实目标工具链和易语言 SDK 复核，不能仅凭工程名认定兼容。
8. **编码依赖**：源码含 GBK 中文字面量，`lang.h` 固定 `__COMPILE_LANG_VER` 为 GBK；必须用与工程字符集/易语言版本匹配的编码保存和编译。
9. **共享头文件并非独立 SDK**：`elib` 内文件带有“仅授权给第三方开发易语言支持库”的版权说明，后续复用应遵守上游授权边界。
10. **辅助实现存在模板残留**：`untshare.h` 中序列化和图标解析主体被注释，不能按函数名推断其已具备能力。

建议下一轮若要继续深挖，按以下顺序取证：

```text
先确认目标易语言 SDK/ABI 与 Win32/x64 工具链
        ↓
补齐 SuperBar 内部状态与 HUNIT 生命周期模型
        ↓
实现属性默认值/序列化/读写及范围校验
        ↓
实现窗口绘制、方向和图片组状态机
        ↓
接入鼠标/键盘消息与三个事件通知
        ↓
在 Windows + 易语言 IDE 中做装载、设计时、编译时、运行时验收
```

## 10. Git 基线与证据路径

### 10.1 Git 基线

- 仓库：`/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/iext6`
- 当前分支：`master`
- 当前提交：`bd1fe5790cea077eb7c014c437d5a7aaead581a4`
- 短提交：`bd1fe57`
- 提交信息：`初始化仓库`
- 提交时间：`2022-12-19T16:12:18+08:00`
- 远程：`https://gitee.com/JYtechnology/iext6.git`
- 本地与 `origin/master`：现场核对为同一提交；`git ls-remote origin HEAD refs/heads/master` 也返回同一 SHA
- 建档前工作树：干净；本轮之后预期仅新增 `ARCHITECTURE.md`
- 历史：当前浅克隆只显示该初始化提交，不能据此推断上游完整历史不存在。

### 10.2 证据路径索引

- 项目入口和库元信息：`iext6_dllMain.cpp:26-98`
- DLL 导出：`Source_iext6.def:1-4`
- 系统通知分发：`iext6_dllMain.cpp:101-178`
- 命令清单：`iext6_cmd_typedef.h:3-13`
- 命令元数据与参数：`iext6_cmdInfo.cpp:3-39`
- 命令执行占位：`iext6_cmdDef.cpp:3-10`
- 常量数量为 0：`iext6_const.cpp:12-18`
- SuperBar 属性/事件/类型表：`iext6_dtType.cpp:43-168`
- SuperBar 接口映射：`iext6_dtType.cpp:170-234`
- SuperBar 回调占位：`iext6_dtType.cpp:236-350`
- 项目头和外部符号：`include_iext6_header.h:1-26`
- 通知和内存辅助：`elib/fnshare.cpp:1-71`、`elib/fnshare.h:20-170`
- 易语言 ABI 数据类型和结构：`elib/lib2.h:149-824`
- 组件接口/属性/事件类型：`elib/lib2.h:394-729`
- 支持库信息和入口 ABI：`elib/lib2.h:1223-1319`
- 动态工程源码与配置：`iext6.vcxproj:21-202`
- 静态工程源码与配置：`iext6_static/iext6_static.vcxproj:21-167`
- 解决方案双项目关系：`iext6.sln:1-40`
- 工程筛选器：`iext6.vcxproj.filters`、`iext6_static/iext6_static.vcxproj.filters`
- IDE 扩展功能声明（当前未接入）：`elib/PublicIDEFunctions.h:1-493`

## 11. 本轮结论

`iext6` 已经具备一个可被易语言支持库机制识别的元数据骨架：固定导出入口、库信息、一个 `SuperBar` 窗口单元、68 个属性、3 个事件、动态/静态工程和系统通知 ABI 均已声明。但核心运行链路仍未完成，尤其是组件创建返回 0、属性读写为空壳、命令执行无返回值、事件没有派发实现；没有仓库内测试，也没有本地 Windows/MSVC 或易语言运行时验证证据。后续引用本项目时，应将其归类为“多功能条支持库的接口/元数据模板与未完成实现”，不要描述为已完成的可用控件。
