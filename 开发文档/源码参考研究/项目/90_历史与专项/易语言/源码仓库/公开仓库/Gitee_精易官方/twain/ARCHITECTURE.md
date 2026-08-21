# twain 架构建档

> 首轮全量架构建档。本文是本仓库当前唯一的架构事实入口；后续细探应增量更新本文件，不在源码目录旁建立平行架构结论。
>
> **研究边界**：本次仅人工读取本地仓库中的源码、工程文件和 Git 信息；未修改源码、工程、依赖、测试、配置或 Git 历史，未安装依赖，未启动服务。本文严格区分“已实现”“仅声明/元数据”“未验证”。

## 1. 项目定位与结论摘要

`twain` 是一个面向易语言的 Windows 支持库源码仓库，目标是以易语言支持库 ABI 提供“数码设备（静态图像）”和“视频设备（动态图像）”两个窗口单元，以及相关命令、属性、事件和“像素类型”枚举。仓库通过同一份 C++ 源码分别构建动态库项目 `twain` 与静态库项目 `twain_static`。

**首轮结论**：仓库的支持库元数据、命令签名、数据类型/属性/事件描述、DLL 入口和通知转发骨架已经搭出；但 `twain_cmdDef.cpp` 中 17 个命令函数均只有参数读取或空函数体，没有看到 TWAIN/视频设备 SDK 调用、设备句柄、图像缓存、文件写入、压缩/解压缩或事件抛出实现；两个组件的创建函数返回 `0`，属性持久化/变更逻辑也仍是模板桩。因此当前更准确的定位是“易语言支持库接口/工程骨架”，而不是经源码验证可运行的 TWAIN 设备实现。

已明确的静态事实：

- Git 仓库只有 1 个提交，`master` 与 `origin/master` 同点：`b979ad4484147c443673286cdd47fabf2778e5ac`（2022-12-19，提交说明“初始化仓库”）。
- 远程地址：`https://gitee.com/JYtechnology/twain.git`；现场 `git ls-remote` 显示远程 `HEAD`/`master` 仍为同一提交。
- 跟踪文件共 20 个（不含 `.git` 内部文件），源码/头文件/工程文件总量约 256 KiB；仓库没有 README、测试目录、构建脚本或第三方 SDK 源码。
- 支持库信息中声明：库名“数码设备支持库”、GUID `730FA7B73AAB409a8554F9553CF2DD87`、版本 `2.0.0`、要求易语言系统 `3.7`、核心支持库 `3.7`、仅 Windows、GBK 语言。
- 元数据注册 3 个自定义数据类型、17 个命令、0 个常量；两个窗口单元各声明 1 个事件。

## 2. 中文文本流程图

```text
易语言 IDE / 运行时
        |
        | 载入支持库：固定导出符号 GetNewInf
        v
+---------------------------+
| twain_dllMain.cpp         |
| LIB_INFO / 命令函数表     |
| twain_ProcessNotifyLib    |
+-------------+-------------+
              |
              | NL_SYS_NOTIFY_FUNCTION
              v
+---------------------------+       系统通知/内存/运行环境查询
| elib/fnshare.cpp/.h       | <----------------------------------+
| NotifySys / ProcessNotify |                                    |
| SetUserSysNotify          | -----------------------------------+
+-------------+-------------+
              |
              | 注册的命令索引、参数信息、返回类型
              v
+---------------------------+
| twain_cmd_typedef.h       |
| TWAIN_DEF 单一命令清单    |
+-----+-------------+-------+
      |             |
      | 元数据      | 执行函数名
      v             v
+-----------+   +---------------------------+
| cmdInfo   |   | twain_cmdDef.cpp         |
| 17 命令   |   | 17 个函数当前为骨架/桩  |
+-----------+   +---------------------------+

+---------------------------+
| twain_dtType.cpp          |
| 3 数据类型注册            |
| 组件属性/事件/接口路由    |
+-----+---------------------+
      |
      +--> TwainControl：静态图像窗口单元
      |       4 个命令，19 个属性，1 个事件
      |
      +--> PelsType：像素类型枚举，9 个成员
      |
      +--> capControl：动态图像窗口单元
              13 个命令，12 个属性，1 个事件

动态构建：twain.vcxproj + Source_twain.def -> 预期 .fne DLL
静态构建：twain_static.vcxproj -> 静态库（依赖宿主按通知协议解析命令函数名）
```

流程图中“预期”仅表示工程配置目标；本机为 macOS，未有 Visual Studio/MSBuild/Windows SDK 运行验证，不能把 DLL/静态库产物视为已生成。

## 3. 真实目录与文件地图

```text
twain/
├── ARCHITECTURE.md                 # 本文；本次新增
├── Source_twain.def                # DLL 模块定义，仅导出 GetNewInf
├── include_twain_header.h          # 统一包含入口、外部注册数组、命令声明
├── twain_cmd_typedef.h             # TWAIN_DEF 命令单一清单及名称拼接宏
├── twain_cmdDef.cpp                # 17 个命令执行函数；当前为未完成实现
├── twain_cmdInfo.cpp               # 17 个命令的参数/显示元数据
├── twain_const.cpp                 # 常量表，占位数组，实际数量 0
├── twain_dllMain.cpp               # DLL 入口、LIB_INFO、命令函数表、系统通知入口
├── twain_dtType.cpp                # 数据类型、组件属性事件、组件接口回调骨架
├── twain.sln                       # Visual Studio 解决方案，动态/静态两个项目
├── twain.vcxproj                   # DynamicLibrary，Win32/x64，Debug/Release
├── twain.vcxproj.filters           # IDE 文件筛选器
├── twain.vcxproj.user              # 空用户属性组
├── twain_static/
│   ├── twain_static.vcxproj        # StaticLibrary，复用根目录源码
│   ├── twain_static.vcxproj.filters
│   └── twain_static.vcxproj.user   # 空用户属性组
└── elib/
    ├── fnshare.cpp                 # 支持库系统通知/调试版本转发实现
    ├── fnshare.h                   # 内存、数据、通知等辅助函数声明/内联封装
    ├── krnllib.h                   # 易语言核心库相关声明（本轮未展开实现）
    ├── lang.h                      # GBK/英语/BIG5/SJIS 语言版本宏
    ├── lib2.h                      # 支持库 ABI 数据结构、标志、接口常量
    ├── mtypes.h                    # Windows/基础类型兼容定义
    ├── PublicIDEFunctions.h        # IDE 扩展功能常量与结构
    └── untshare.h                  # 窗口单元辅助函数/属性事件掩码
```

工程文件的实际源码输入一致：动态项目编译 `elib/fnshare.cpp` 和根目录 5 个 `.cpp`；静态项目用 `..\` 路径复用完全相同的 6 个 `.cpp` 和 9 个头文件。仓库中没有 `README.md`、`AGENTS.md`、`CLAUDE.md`、测试文件、资源文件、TWAIN SDK 头文件或外部库文件。

## 4. 架构分层与模块职责

### 4.1 支持库 ABI 与平台兼容层：`elib/`

- `elib/lib2.h` 定义易语言支持库 ABI 的核心结构和协议，包括 `LIB_INFO`、`CMD_INFO`、`ARG_INFO`、`LIB_DATA_TYPE_INFO`、`UNIT_PROPERTY`、`EVENT_INFO2`、`MDATA_INF`、`PFN_EXECUTE_CMD`、`PFN_NOTIFY_LIB`、`PFN_NOTIFY_SYS` 等。
- `elib/mtypes.h` 提供基础/Windows 风格类型别名，如 `INT`、`DWORD`、`HWND`、`HGLOBAL`、`HUNIT` 所依赖的基础类型，以及 `TRUE/FALSE`、`MAKEWORD` 等宏。它不是完整 Windows SDK；真正编译仍依赖工程/平台提供的 Windows 类型与 API 环境，当前源码中也未看到设备 API 头文件。
- `elib/lang.h` 固定 `__COMPILE_LANG_VER` 为 `__GBK_LANG_VER`，即中文 GBK 支持库。
- `elib/fnshare.cpp/.h` 封装宿主通知：`NotifySys` 通过 `s_pfnNotifySys` 回调宿主；`ProcessNotifyLib` 接收库通知，在 `NL_SYS_NOTIFY_FUNCTION` 中保存宿主回调并通过 `NRS_GET_PRG_TYPE` 查询调试/运行类型，然后把通知继续转发给 `s_pfnuserNotifySys`。`ealloc/efree` 也是通过宿主 `NRS_MALLOC/NRS_MFREE` 申请/释放内存的内联封装。
- `elib/untshare.h` 提供窗口单元属性/样式/窗口句柄等辅助 ABI；本项目的组件回调目前没有实际调用这些辅助设施。
- `elib/PublicIDEFunctions.h` 是 IDE AddIn/编辑操作常量和结构的通用头，本项目的 `LIB_INFO.m_pfnRunAddInFn` 为 `NULL`，没有注册 IDE 插件功能。

### 4.2 命令声明与元数据层：`twain_cmd_typedef.h`、`twain_cmdInfo.cpp`

`TWAIN_DEF(_MAKE)` 是命令单一清单。每条记录包括索引、中文名、英文名、说明、对象类别、操作系统状态、返回数据类型、用户级别、参数个数及参数表首地址。该宏被多次展开以生成：

1. `include_twain_header.h` 中的 17 个命令函数声明；
2. `twain_cmdInfo.cpp` 中的 `CMD_INFO g_cmdInfo_twain_global_var[]`；
3. `twain_dllMain.cpp` 中的执行函数指针表和静态编译函数名表。

这种 X-Macro 设计使命令索引、显示元数据和实现函数名共享同一顺序；因此任何插入、删除或重排都必须同步验证 `TWAIN_DEF`、参数数组偏移、实现函数名和函数指针表。

`twain_cmdInfo.cpp` 的 `g_argumentInfo_twain_global_var[]` 提供 18 个参数元数据（索引 0 至 17）；默认值/可空标志已经声明，例如来源选项默认 `-1`、预览速率默认 `-1`、捕获帧间隔默认 `66`、捕获提示/鼠标结束默认真、捕获时间默认 `-1`。这些是编辑器/编译器元数据，不等于运行时已执行参数校验。

### 4.3 命令执行层：`twain_cmdDef.cpp`

源码定义 17 个 `TWAIN_EXTERN_C void` 命令函数，统一签名为：

```cpp
void (PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)
```

已声明/已注册但尚未完成设备逻辑的命令如下：

| 索引 | 英文名 | 中文名 | 返回类型 | 现状 |
|---:|---|---|---|---|
| 0 | `ChooseSource` | 选定来源 | `SDT_INT` | 读取两个参数后无调用、无返回值写入 |
| 1 | `GetImage` | 获取图像 | `SDT_BOOL` | 读取参数后无实现 |
| 2 | `SaveToFile` | 保存到文件 | `SDT_BOOL` | 读取文本指针后无实现 |
| 3 | `Init` | 初始化 | `SDT_BOOL` | 空函数体 |
| 4 | `SetVideoSource` | 设置视频输入 | `SDT_BOOL` | 空函数体 |
| 5 | `SetVideoFormat` | 设置视频格式 | `SDT_BOOL` | 空函数体 |
| 6 | `SetVideoDisplay` | 设置视频显示 | `SDT_BOOL` | 空函数体 |
| 7 | `Preview` | 预览 | `SDT_BOOL` | 读取两个参数后无实现 |
| 8 | `VideoOverlay` | 视频重叠 | `SDT_BOOL` | 读取参数后无实现 |
| 9 | `StartCapture` | 捕获视频 | `SDT_BOOL` | 读取 7 个参数后无实现 |
| 10 | `SetVideoCompression` | 设置压缩格式 | `SDT_BOOL` | 空函数体 |
| 11 | `SaveToImage` | 保存为图片 | `SDT_BOOL` | 读取文本指针后无实现 |
| 12 | `StopCapture` | 结束捕获 | `SDT_BOOL` | 空函数体 |
| 13 | `Compress` | 压缩一帧图像 | `SDT_BIN` | 读取字节集指针后无实现 |
| 14 | `UnCompress` | 解压缩一帧图像 | `SDT_BIN` | 读取字节集指针后无实现 |
| 15 | `FillOneFrame` | 填充一帧图像 | `SDT_BOOL` | 读取字节集指针后无实现 |
| 16 | `IsCanDestroy` | 是否可销毁 | `SDT_BOOL` | 隐藏命令，空函数体 |

源码注释提到 AVI/BMP、视频帧、Microsoft Windows Media Video 9 等目标行为，但当前仓库没有对应调用或依赖，因此只能记录为接口说明/设计意图，不能记录为已实现能力。

### 4.4 数据类型注册与组件回调层：`twain_dtType.cpp`

`g_DataType_twain_global_var[]` 注册三个数据类型：

1. `TwainControl`（中文“数码设备”）：Windows 窗口单元、`LDT_WIN_UNIT | LDT_IS_FUNCTION_PROVIDER`，命令索引 `[0,1,2,3]`，1 个事件，19 个属性，接口函数 `twain_GetInterface_TwainControl`。
2. `PelsType`（中文“像素类型”）：Windows 枚举 `LDT_ENUM`，9 个成员：`BW=0`、`GRAY=1`、`RGB=2`、`PALETTE=3`、`CMY=4`、`CMYK=5`、`YUV=6`、`YUVK=7`、`CIEXYZ=8`。
3. `capControl`（中文“视频设备”）：Windows 窗口单元 `LDT_WIN_UNIT`，命令索引 `[4..16]`，1 个事件，12 个属性，接口函数 `twain_GetInterface_capControl`。

两个窗口单元都实现了相同的接口选择路由：

- `ITF_CREATE_UNIT` -> `twain_ControlCreate_*`
- `ITF_PROPERTY_UPDATE_UI` -> `twain_PropUpDate_*`
- `ITF_DLG_INIT_CUSTOMIZE_DATA` -> `twain_PropPopDlg_*`
- `ITF_NOTIFY_PROPERTY_CHANGED` -> `twain_PropChanged_*`
- `ITF_GET_ALL_PROPERTY_DATA` -> `twain_PropGetDataAll_*`
- `ITF_GET_PROPERTY_DATA` -> `twain_PropGetData_*`
- `ITF_IS_NEED_THIS_KEY` -> `twain_PropKetInfo_*`
- `ITF_GET_NOTIFY_RECEIVER` -> `twain_PropNotifyReceiver_*`
- 图标数据、语言转换、消息过滤接口当前返回 `NULL`。

组件回调现状：

- `twain_ControlCreate_TwainControl` 与 `twain_ControlCreate_capControl` 都注释 `TODO`，创建 `HUNIT hUnit = 0` 并返回 0；未创建窗口、设备对象或内部状态。
- `twain_PropUpDate_*` 无条件返回 `TRUE`，没有按属性/状态判断。
- `twain_PropPopDlg_*` 将 `*pblModified = false` 后返回 `FALSE`；没有自定义属性对话框。
- `twain_PropChanged_*` 仅保留 `case 0` 模板分支，最终返回 `false`；没有属性校验、状态更新或重建逻辑。
- `twain_PropGetDataAll_*` 返回 0；没有序列化所有属性。
- `twain_PropGetData_*` 仅保留 `case 0` 模板分支，最终返回 `true`；没有填充 `pPropertyVaule`，因此“返回成功”不能视为返回了有效属性数据。
- `twain_PropKetInfo_*` 返回 `FALSE`；不截获按键。
- `twain_PropNotifyReceiver_*` 对 `NU_GET_CREATE_SIZE_IN_DESIGNER` 不写入宽高且返回 0；没有默认设计尺寸。

## 5. 数据模型、属性与事件

### 5.1 支持库级模型

`LIB_INFO g_LibInfo_twain_global_var` 是宿主发现本库的根描述对象，关键字段来自 `twain_dllMain.cpp`：

| 字段 | 当前值/来源 | 结论 |
|---|---|---|
| `m_dwLibFormatVer` | `LIB_FORMAT_VER`（`20000101`） | 已声明 ABI 格式 |
| `m_szGuid` | `730FA7B73AAB409a8554F9553CF2DD87` | 已声明库身份 |
| 版本 | `2.0.0` | 已声明版本，不代表功能完成度 |
| 系统要求 | 易语言 `3.7`，核心库 `3.7` | 已声明兼容要求 |
| 名称/语言 | “数码设备支持库” / `__GBK_LANG_VER` | 已声明 |
| OS 状态 | `_LIB_OS(__OS_WIN)` | Windows-only 元数据 |
| 数据类型 | `g_DataType_twain_global_var` / count 3 | 已注册 |
| 命令 | `g_cmdInfo_twain_global_var` / count 17 | 已注册 |
| 命令实现 | `g_cmdInfo_twain_global_var_fun` | 指针表已注册，函数逻辑未完成 |
| 常量 | `g_ConstInfo_twain_global_var_count = 0` | 无预定义常量 |
| 依赖文件 | `NULL` | 未声明额外支持文件；不等于无系统/运行时依赖 |
| 库通知 | `twain_ProcessNotifyLib_twain` | 已实现入口骨架 |

### 5.2 `TwainControl` 属性

属性顺序是组件回调中 `nPropertyIndex` 的 ABI 索引。前 8 项为易语言窗口单元通用属性，后 11 项为组件属性：

| 索引范围 | 属性 | 类型/标志 | 说明 |
|---|---|---|---|
| 0–7 | `left`、`top`、`width`、`height`、`tag`、`visible`、`disable`、`MousePointer` | `UD_INT`/`UD_TEXT`/`UD_BOOL`/`UD_CURSOR` | 通用窗口属性 |
| 0–3（组件部分） | `SourceCount`、`SourceName`、`SourceNo`、`ErrorText` | `UD_INT`/`UD_TEXT`；前两项只读，`SourceNo` `UW_CANNOT_INIT` | 来源选择与错误信息意图 |
| 4–10（组件部分） | `PixelType`、`ResulotionX`、`ImageTop`、`ImageBottom`、`ImageLeft`、`ImageRight`、`ResulotionY` | `UD_INT`/`UD_DOUBLE`；均 `UW_CANNOT_INIT` | 图像格式、分辨率和采集范围意图 |

源码英文属性名 `ResulotionX/ResulotionY` 保持原样记录（拼写为源码事实）。

事件“图片传送完毕”有三个 `EVENT_ARG_INFO2` 参数：`图片`（`SDT_BIN`）、`图片宽度`（`SDT_INT`）、`图片高度`（`SDT_INT`）。事件状态带 `_EVENT_OS(OS_ALL) | EV_IS_VER2`，无返回值。事件数组已注册，但在命令实现中没有找到抛出事件的代码。

### 5.3 `capControl` 属性

`capControl` 也有 8 项通用窗口属性，组件部分有 4 项：`SourceCount`（只读）、`SourceName`（只读）、`SourceNo`（`UW_CANNOT_INIT`）、`ErrorText`（只读）。

事件“收到一帧数据后”有 1 个参数 `图片`（`SDT_BIN`），说明为位图格式；事件只声明“捕获状态下触发”，当前实现中没有捕获循环、帧缓冲或事件通知逻辑。

### 5.4 参数/返回值传递模型

命令通过宿主提供的 `PMDATA_INF` 传入参数和返回槽位；`MDATA_INF` 的数据联合包含基础数值、逻辑、文本/字节集指针等，具体 ABI 定义在 `elib/lib2.h`。当前命令函数只读取 `pArgInf[i]`（如 `.m_bool`、`.m_int`、`.m_pText`、`.m_pBin`），未看到：

- `pRetData` 返回类型/值写入；
- `nArgCount` 范围校验；
- 文本/字节集复制或释放；
- 设备错误到 `ErrorText` 的映射；
- 并发、生命周期或资源释放状态。

## 6. 外部接口与调用边界

### 6.1 DLL 导出与库发现

`Source_twain.def` 仅导出 `GetNewInf`。`twain_dllMain.cpp` 中：

```cpp
EXTERN_C PLIB_INFO WINAPI GetNewInf()
{
    return &g_LibInfo_twain_global_var;
}
```

这是支持库宿主发现 `LIB_INFO` 的固定边界。动态项目在 Win32 Debug/Release 配置中通过 `Source_twain.def` 指定模块定义文件，x64 配置未配置该字段；这属于工程配置事实，是否影响目标平台导出需在 Windows/MSBuild 环境实测。

### 6.2 库通知协议

`twain_ProcessNotifyLib_twain` 处理/转发以下通知：

- `NL_SYS_NOTIFY_FUNCTION`：调用 `ProcessNotifyLib` 保存宿主 `PFN_NOTIFY_SYS`；
- `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NR_DELAY_FREE`、`NL_IDE_READY`、`NL_RIGHT_POPUP_MENU_SHOW`、`NL_ADD_NEW_ELEMENT`：当前为空处理；
- 静态库相关 `NL_GET_CMD_FUNC_NAMES`、`NL_GET_NOTIFY_LIB_FUNC_NAME`、`NL_GET_DEPENDENT_LIBS`：返回静态函数名数组、通知函数名和空依赖列表；
- 未知通知：返回 `NR_ERR`。

`fnshare.cpp::ProcessNotifyLib` 在处理本库自身通知后，还会调用用户通过 `SetUserSysNotify` 设置的回调；这是库内部向宿主/上层转发的唯一可见通知骨架。

### 6.3 组件接口边界

两个 `twain_GetInterface_*` 都是 `PFN_GET_INTERFACE` 类型的按编号路由器。它们暴露的是易语言窗口单元 ABI，而不是公开的 TWAIN API。源码没有独立 SDK 适配接口、设备会话对象或跨模块服务层。

### 6.4 静态库边界

`twain_static.vcxproj` 定义 `__E_STATIC_LIB`（Win32 配置）并编译相同源文件。动态库专用的 `LIB_INFO`、命令元数据和数据类型元数据多数包在 `#ifndef __E_STATIC_LIB` 中；静态场景由 `twain_ProcessNotifyLib_twain` 返回命令函数名数组、通知函数名和依赖库列表，供宿主静态编译流程消费。x64 静态配置的预编译头设置为 `Use`，但项目文件没有列出 `pch.h`，这一配置未验证。

## 7. 依赖与构建配置

### 已声明依赖

- Visual Studio C++ 工程格式，工具集 `v141`。
- Windows SDK 目标版本 `10.0.15063.0`。
- Windows 目标平台；Unicode 字符集（动态/静态 Win32/x64 配置均声明）。
- 易语言支持库 ABI 头文件（仓库内 `elib/`）。
- 动态库链接模块定义文件 `Source_twain.def`（仅 Win32 配置明确设置）。

### 未出现/未验证依赖

- 没有 TWAIN DSM/SDK 头文件、导入库、设备厂商 SDK 或视频采集 SDK。
- 没有 `windows.h`、TWAIN API 调用、视频捕获 API 调用、Media Foundation/DirectShow/Video for Windows 调用的源码证据。
- 命令注释提及 Windows Media Video 9，但工程没有对应库声明，当前也没有压缩实现。
- 没有 NuGet、vcpkg、Conan、CMake、MSBuild 自定义脚本或 CI 配置。

### 工程配置事实

| 项目 | 类型 | 配置 | 平台 | 运行库/特征 |
|---|---|---|---|---|
| `twain.vcxproj` | `DynamicLibrary` | Debug/Release | Win32/x64 | Win32 Debug/Release 配置 `TargetExt=.fne`；Win32 使用 `Source_twain.def`；Release 开启优化 |
| `twain_static.vcxproj` | `StaticLibrary` | Debug/Release | Win32/x64 | Win32 定义 `__E_STATIC_LIB`、`__E_FNENAME=twain`；Win32 多处理器编译 |

项目没有 PostBuild 命令；`*.vcxproj.user` 仅为空 `PropertyGroup`。

## 8. 测试与验证状态

### 仓库内测试资产

未发现测试目录、测试源文件、测试工程、断言、CI 工作流、示例易语言程序或设备模拟器。工程筛选器中的“资源文件”也没有实际资源文件。

### 本轮执行的验证

- 已人工读取：`twain.sln`、两个 `.vcxproj`、两个 `.filters`、两个 `.user`、`Source_twain.def`、全部根目录 C++/头文件和 `elib/` 头/源文件。
- 已检查 Git 工作树、分支、远程地址、提交基线，并用 `git ls-remote origin HEAD refs/heads/master` 核对远程指针。
- 已通过源码静态阅读核对：命令数量 17、数据类型数量 3、常量数量 0、`TwainControl`/`capControl` 的命令索引与属性/事件数组。
- **未执行构建**：当前主机为 macOS，仓库是 Windows Visual Studio 工程；本轮没有 Windows/MSBuild/Visual Studio 环境，不能声称编译通过。
- **未执行运行验证**：没有 Windows 易语言宿主、TWAIN 设备或视频设备，不能声称 DLL 可载入、命令可运行、事件会触发或图像可保存。

## 9. 已实现、仅声明、未验证清单

### 已实现（源码中有明确可执行代码）

- `GetNewInf` 返回静态 `LIB_INFO` 地址。
- `twain_ProcessNotifyLib_twain` 的通知分派骨架、未知通知错误返回、动态/静态函数名查询分支。
- `elib/fnshare.cpp` 的宿主通知指针保存、调试运行类型查询、用户通知回调转发。
- 命令/数据类型/属性/事件/库信息的静态数组初始化和 X-Macro 生成关系。
- 两个 `twain_GetInterface_*` 的接口编号路由。
- 各命令函数读取已声明参数的局部变量动作（这不等于命令行为实现）。

### 仅声明/元数据（不能当作功能完成）

- 17 个命令的名称、说明、参数类型、默认值、返回类型和对象归属。
- 两个组件的属性、事件、像素枚举及 Windows 支持标志。
- “获取来源/采集图像/视频预览/捕获/压缩/保存”的目标语义。
- `LIB_INFO` 的版本、GUID、作者、系统版本要求和支持库注册信息。
- `Source_twain.def` 的 `GetNewInf` 导出声明。

### 未验证或明确未完成

- TWAIN DSM 连接、来源枚举/选择、初始化、采集、图像传送和 BMP 保存。
- 视频输入/格式/显示/覆盖/预览/捕获/停止以及帧事件。
- 图像压缩、解压缩、填充窗口和 Windows Media Video 9 适配。
- 两个组件的实际窗口/设备对象创建、属性存储、序列化和销毁。
- `pRetData` 返回槽位、错误码/`ErrorText`、参数越界、资源释放。
- Windows 编译、DLL 导出、静态编译链接及易语言 IDE 装载。
- 真实硬件兼容性、线程模型、并发、重入、取消和异常恢复。

## 10. 风险与后续复核点

1. **功能实现缺口**：当前命令和组件回调大部分是自动生成模板，后续不能只补设备调用，还需要设计对象状态、宿主内存、事件生命周期和销毁协议。
2. **返回值契约风险**：命令声明了 `SDT_BOOL`、`SDT_INT`、`SDT_BIN` 等返回类型，但函数没有填充 `pRetData`；接入宿主前应逐命令定义成功/失败/错误值及字节集所有权。
3. **属性索引风险**：属性数组包含“默认通用属性”与“组件属性”两段，回调中的 `nPropertyIndex` 语义必须与易语言 ABI 确认，不能直接按注释中的局部 `case 0` 模板实现。
4. **事件所有权风险**：事件参数含 `SDT_BIN`，而 `EVENT_INFO2` 规定含额外空间的数据由支持库负责释放；后续必须明确图像缓冲分配、复制、释放和事件抛出时机。
5. **平台工程风险**：Win32 动态配置设置 `.fne` 和 `.def`，x64 动态配置未设置 `ModuleDefinitionFile`；静态 x64 使用预编译头但未见 `pch.h`。须在目标 Windows 工具链中验证。
6. **协议版本风险**：`elib/` 是随仓库复制的支持库 ABI 头，声明易语言系统/核心库版本 3.7；后续升级 ABI 或接入其他支持库时要重新核对结构布局、调用约定和 `#pragma pack`。
7. **来源可信度风险**：提交只有初始化提交，无法通过 Git 历史确认模板后续演进；README/示例/发布包也不存在，功能意图只能依据当前注释和元数据。
8. **名称/编码风险**：库使用 GBK 字符串；`ResulotionX/ResulotionY` 等英文名存在源码拼写，任何兼容实现必须保留原名或显式规划迁移。

建议下一轮优先顺序：先在 Windows 工具链确认工程能否构建和导出，再读取/确认易语言支持库 ABI 的组件创建、事件抛出、属性序列化与内存所有权契约；之后单独设计 TWAIN/视频后端适配层和组件状态机，最后用模拟设备/真实设备补集成测试。上述均为后续研究建议，不表示本轮已启动实现。

## 11. Git 基线与证据路径

### Git 基线

```text
仓库根目录：/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/twain
远程：origin https://gitee.com/JYtechnology/twain.git
分支：master（跟踪 origin/master）
HEAD：b979ad4484147c443673286cdd47fabf2778e5ac
提交时间：2022-12-19 16:13:32 +0800
提交说明：初始化仓库
远程 HEAD/master：b979ad4484147c443673286cdd47fabf2778e5ac
本轮改动：仅新增/更新 ARCHITECTURE.md；未改源码、工程、依赖、测试、配置或 Git 历史
```

### 关键证据路径

- 库入口、版本、GUID、命令函数表、通知：`twain_dllMain.cpp`（`LIB_INFO`、`GetNewInf`、`twain_ProcessNotifyLib_twain`）。
- 命令单一清单和命令索引：`twain_cmd_typedef.h`。
- 命令参数元数据：`twain_cmdInfo.cpp`。
- 命令执行桩：`twain_cmdDef.cpp`。
- 数据类型/属性/事件数组、组件接口路由和回调桩：`twain_dtType.cpp`。
- 根包含与命令声明：`include_twain_header.h`。
- 常量数量：`twain_const.cpp`。
- 导出边界：`Source_twain.def`。
- 宿主通知转发：`elib/fnshare.cpp`、`elib/fnshare.h`。
- 支持库 ABI 结构/接口/标志：`elib/lib2.h`。
- 基础类型兼容层：`elib/mtypes.h`。
- 工程输入与配置：`twain.sln`、`twain.vcxproj`、`twain_static/twain_static.vcxproj` 及对应 `.filters`/`.user`。

> 本文件已吸收本轮首轮细探结论；后续只维护本文件。源码中的 TODO、空实现和未验证项必须继续显式保留，不能用元数据或注释把目标能力写成已实现能力。
