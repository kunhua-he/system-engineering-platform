# eoalib 架构建档

> 本文件是 `eoalib` 项目根目录唯一架构事实文档。首轮建档基于当前工作树源码、Visual Studio 工程文件和 Git 元数据；不把设计注释当作已实现功能，不把工程配置当作实际运行验证。
>
> 本仓库属于只读源码参考库。当前核对未修改源码、未安装依赖、未构建、未提交 Git；仅新增本文件。

## 1. 项目定位

`eoalib` 是一个面向易语言的 Windows 办公组件支持库源码，库对外表现为易语言支持库动态模块，提供名为“办公组件”的文档/页面/工作表/对象/表格/修订能力，以及配套自定义数据类型、命令元数据、IDE 组件接口和系统通知转发。

当前仓库是 `Gitee_精易官方/eoalib` 的初始仓库快照，项目说明与实现均集中在 C/C++ 源码和 Visual Studio 工程中，没有 README、测试目录、示例程序、第三方依赖清单或旧 `细探-*.md` 文档。源码注释描述了较完整的易语言支持库 ABI，但当前 `eoalib_cmdDef.cpp` 更接近由接口定义生成的命令实现骨架：285 个命令入口均存在，很多函数只读取参数到局部变量，未写入返回值，也未调用办公组件后端。

### 1.1 现场版本基线

| 项目 | 现场事实 |
|---|---|
| 本地路径 | `/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/eoalib` |
| 本地分支 | `master` |
| 本地 HEAD | `af4a0d93eefe4fca175034e21e79554097c4647a` |
| HEAD 时间 | `2022-12-19T16:07:00+08:00` |
| HEAD 提交 | `初始化仓库` |
| 远程 | `origin https://gitee.com/JYtechnology/eoalib.git` |
| 远程 `HEAD`/`master` | `af4a0d93eefe4fca175034e21e79554097c4647a`，与本地一致 |
| 工作树 | 建档前为干净；建档后仅新增 `ARCHITECTURE.md` |
| Git 跟踪文件 | 23 个源码/工程文件；不含构建产物 |

远程版本通过只读 `git ls-remote origin HEAD refs/heads/master` 复核，未执行 `fetch`、`pull` 或其他会改变仓库对象/引用的操作。

## 2. 总体架构与真实调用链

```text
易语言 IDE / 运行时
        │
        │ 载入 .fne/.fnl，调用导出的 GetNewInf()
        ▼
Source_eoalib.def
        │ 仅显式导出 GetNewInf
        ▼
eoalib_dllMain.cpp
  ┌────────────────────────────────────────────┐
  │ LIB_INFO g_LibInfo_eoalib_global_var       │
  │  - 版本/GUID/系统版本要求                  │
  │  - 285 条 CMD_INFO                          │
  │  - 285 个 PFN_EXECUTE_CMD 函数指针         │
  │  - 16 个 LIB_DATA_TYPE_INFO                 │
  │  - 0 个 LIB_CONST_INFO                      │
  │  - eoalib_ProcessNotifyLib_eoalib           │
  └────────────────────────────────────────────┘
        │                         │
        │ 命令索引                 │ 支持库/系统通知
        ▼                         ▼
eoalib_cmdInfo.cpp             fnshare.cpp
  CMD_INFO + ARG_INFO          ProcessNotifyLib
        │                         │
        │ 函数指针数组由           │ 保存 PFN_NOTIFY_SYS，
        │ EOALIB_DEF 同源生成      │ 转发 NRS_* / NL_* 通知
        ▼                         ▼
eoalib_cmdDef.cpp             易语言系统 NotifySys
  eoalib_<英文名>_<索引>_eoalib
  285 个 C ABI 命令入口
        │
        ├─ 当前实际：读取 pArgInf 到局部 arg 变量
        └─ 当前缺失：办公组件状态、pRetData 写回、事件/窗口后端

自定义类型注册链：
eoalib_dtType.cpp
  命令索引表 → LIB_DATA_TYPE_INFO
  OStar 组件 → 属性/事件/交互接口
  IPage/IWorkSheete/IObject/ITable/IEmend → 接口型复合数据
  PageMargin/CnFontSize/... → 枚举/成员数据类型
```

### 2.1 两条元数据同源链

`eoalib_cmd_typedef.h` 中的 `EOALIB_DEF(_MAKE)` 是命令定义的唯一源码清单。该宏被多次展开：

1. `include_eoalib_header.h` 通过 `EOALIB_DEF_CMD` 生成 285 个命令函数声明；
2. `eoalib_cmdInfo.cpp` 通过 `EOALIB_DEF_CMDINFO` 生成 `CMD_INFO[]` 命令说明表；
3. `eoalib_dllMain.cpp` 通过 `EOALIB_DEF_CMD_PTR` 生成函数指针表；
4. `eoalib_dllMain.cpp` 通过 `EOALIB_DEF_CMDNAME_STR` 生成静态编译所需的函数名数组；
5. `eoalib_cmdDef.cpp` 手工/生成落地 285 个同索引实现函数。

因此，命令索引是 ABI 关键字段：`eoalib_cmd_typedef.h` 中 0--284 连续且无缺号，`eoalib_cmdDef.cpp` 中也有 285 个对应函数。任意增删/重排都必须同步命令元数据、参数偏移、自定义类型方法索引、函数指针表和静态库函数名表。

## 3. 目录与文件地图

```text
eoalib/
├── ARCHITECTURE.md                 本架构文档（当前核对新增）
├── eoalib.sln                      VS solution，含动态库和静态库两个项目
├── eoalib.vcxproj                  eoalib 动态库工程
├── eoalib.vcxproj.filters          动态库工程过滤器
├── eoalib.vcxproj.user             VS 用户配置
├── eoalib_static/
│   ├── eoalib_static.vcxproj       eoalib_static 静态库工程
│   ├── eoalib_static.vcxproj.filters
│   └── eoalib_static.vcxproj.user
├── Source_eoalib.def               DLL 模块定义，仅导出 GetNewInf
├── include_eoalib_header.h         公共聚合头、命令声明与全局元数据 extern
├── eoalib_cmd_typedef.h            EOALIB_DEF 命令总表（285 条）
├── eoalib_cmdInfo.cpp              ARG_INFO 参数表、CMD_INFO 命令表
├── eoalib_cmdDef.cpp               285 个命令执行入口骨架
├── eoalib_dllMain.cpp              DllMain、LIB_INFO、GetNewInf、通知入口
├── eoalib_dtType.cpp               16 个自定义数据类型、组件接口、属性/事件表
├── eoalib_const.cpp                常量表；当前数量为 0
└── elib/
    ├── lib2.h                      易语言支持库 ABI 主定义
    ├── krnllib.h                   系统核心支持库版本/GUID常量
    ├── lang.h                      语言版本常量，当前编译语言为 GBK
    ├── mtypes.h                    Windows/基础类型兼容定义
    ├── fnshare.h                   支持库与运行时共享辅助函数
    ├── fnshare.cpp                 通知函数、调试版探测、用户通知回调
    ├── untshare.h                  无 MFC 的组件/属性/序列化辅助模板
    └── PublicIDEFunctions.h        IDE 公共功能通知编号和参数结构
```

工程文件把 `elib/fnshare.cpp` 与 5 个根目录 `.cpp` 编译进动态库/静态库；头文件作为项目输入，但没有额外源码目录、资源目录、测试目录或后端办公组件实现目录。

## 4. 分层与模块职责

### 4.1 ABI 与公共头层

- `elib/mtypes.h`：定义 `INT`、`DWORD`、`BOOL`、`HUNIT` 相关基础类型、句柄别名及部分 Win32 兼容宏。
- `elib/lib2.h`：定义易语言支持库 ABI，包括 `MDATA_INF`、`CMD_INFO`、`ARG_INFO`、`LIB_DATA_TYPE_INFO`、`LIB_INFO`、事件/属性结构、通知码和函数指针类型。
- `elib/krnllib.h`：声明系统核心支持库身份：GUID `d09f2340818511d396f6aaf844c7e325`、文件名 `krnln`、版本 `4.5`。
- `elib/lang.h`：语言版本常量；`__GBK_LANG_VER` 为 1，`__COMPILE_LANG_VER` 取 GBK。
- `include_eoalib_header.h`：组合 `lib2.h`、`lang.h`、`krnllib.h` 和本库命令定义，并声明动态库模式下的全局表。

### 4.2 命令元数据层

`eoalib_cmd_typedef.h` 的每一项包含：整数索引、中文名称、英文符号名、说明、分类、操作系统状态、返回 `DATA_TYPE`、用户等级、参数数量和 `ARG_INFO` 起始偏移。全部命令是对象成员命令，宏中 `_shtCategory` 为 `-1`。

`eoalib_cmdInfo.cpp` 保存 200 个参数项（索引 0--199），参数包含名称、说明、类型、默认值和参数标志，例如 `AS_HAS_DEFAULT_VALUE`、`AS_DEFAULT_VALUE_IS_EMPTY`、`AS_RECEIVE_VAR`。`CMD_INFO[]` 通过同一命令宏构造，命令总数由 `sizeof` 计算而非手写常量。

### 4.3 命令执行层

`eoalib_cmdDef.cpp` 每个入口采用统一签名：

```cpp
void eoalib_<EnglishName>_<Index>_eoalib(
    PMDATA_INF pRetData,
    INT nArgCount,
    PMDATA_INF pArgInf
)
```

源码盘点结果：

- 285 个入口函数全部存在；
- 159 个函数体去除注释和空行后为空；
- 126 个函数体仅把 `pArgInf[n]` 读取为 `arg1`、`arg2` 等局部变量；
- 当前没有发现命令函数写入 `pRetData` 的代码；
- 当前没有发现命令函数调用 `NotifySys`、组件对象接口或外部办公组件实现；
- 因此，命令表/入口 ABI 已建模，但办公功能行为在当前快照中尚未实现或尚未接入。

这一区分很重要：注释中的“成功返回真”“打开文件”“保存到 FTP”等是命令说明，不是当前代码已完成行为的证据。

### 4.4 支持库生命周期与通知层

`eoalib_dllMain.cpp`：

- `DllMain` 对 `DLL_PROCESS_ATTACH`、`DLL_PROCESS_DETACH`、线程 attach/detach 仅执行空分支并返回 `TRUE`；
- `g_LibInfo_eoalib_global_var` 填入库元信息；
- `GetNewInf()` 返回 `PLIB_INFO`，并把命令索引 15 的英文名从 `ReplaceTextW` 修正为 `ReplaceText`；
- `eoalib_ProcessNotifyLib_eoalib()` 处理易语言系统发给库的通知。

当前库元数据实值：

| 字段 | 值 |
|---|---|
| `m_dwLibFormatVer` | `LIB_FORMAT_VER` = `20000101` |
| GUID | `05B2708EF81049a78EED8531D4A8DFB9` |
| 版本 | `4.0.1` |
| 所需易语言系统 | `3.8` |
| 所需系统核心支持库 | `3.8` |
| 名称 | `办公组件支持库` |
| 语言 | `__GBK_LANG_VER` |
| 平台 | `_LIB_OS(__OS_WIN)`，Windows |
| 数据类型数 | 16 |
| 命令数 | 285 |
| 全局命令类别数 | 0 |
| 常量数 | 0 |
| AddIn/SuperTemplate | 未提供 |
| 依赖文件字符串 | `NULL` |

`elib/fnshare.cpp` 维护三个进程内静态状态：系统通知回调 `s_pfnNotifySys`、用户回调 `s_pfnuserNotifySys`、调试版本值 `s_isDebug`。`ProcessNotifyLib(NL_SYS_NOTIFY_FUNCTION, ...)` 保存系统回调并调用 `NRS_GET_PRG_TYPE`；处理完内部通知后再调用用户回调。`NotifySys()` 在回调存在时把请求转交给易语言运行时，否则返回 0。

### 4.5 自定义数据类型与组件接口层

`eoalib_dtType.cpp` 导出 16 个 `LIB_DATA_TYPE_INFO`：

| 索引 | 中文名 | 英文名 | 角色 |
|---:|---|---|---|
| 0 | 办公组件 | `OStar` | Windows 组件，主对象 |
| 1 | 页面接口 | `IPage` | 接口型复合数据 |
| 2 | 工作表接口 | `IWorkSheete` | 接口型复合数据 |
| 3 | 对象接口 | `IObject` | 接口型复合数据 |
| 4 | 表格接口 | `ITable` | 接口型复合数据 |
| 5 | 修订接口 | `IEmend` | 接口型复合数据 |
| 6 | 页面边距 | `PageMargin` | 复合成员数据 |
| 7 | 中文字号 | `CnFontSize` | 枚举，16 个成员 |
| 8 | 位置 | `Position` | 枚举：最后/之前/之后 |
| 9 | 对象种类 | `ObjectType` | 枚举，27 个成员 |
| 10 | 文本位置 | `TextPos` | 枚举：最前/最后/当前位置 |
| 11 | 文字类型 | `TextType` | 枚举：正常/上标/下标 |
| 12 | 横向对齐 | `HorAlign` | 枚举，5 个成员 |
| 13 | 纵向对齐 | `VerAlign` | 枚举，3 个成员 |
| 14 | 图表类型 | `ChartType` | 枚举，7 个成员 |
| 15 | 填充类型 | `FillType` | 枚举：自动/复制/等差/等比 |

组件 `OStar` 有 72 个成员命令索引、14 个属性条目和 16 个事件。前 8 个固定属性是“左边、顶边、宽度、高度、标记、可视、禁止、鼠标指针”，另有文本框自动增高、右键菜单、工作表菜单、水平标尺、垂直标尺、打印参数设置对话框 6 个组件属性。

接口命令索引表如下：

| 数据类型 | 方法数 | 索引范围 | 说明 |
|---|---:|---:|---|
| `OStar` | 72 | 0--282 | 主组件成员，引用文档/页面/工作表/对象/表格/修订及通用操作 |
| `IPage` | 27 | 25--121 | 页面尺寸、边距、方向、页眉页脚、页码等 |
| `IWorkSheete` | 18 | 25--215 | 工作表增删改名、当前表、复制粘贴等 |
| `IObject` | 82 | 24--280 | 对象布局、层级、锁定、文本框、图形、菜单等 |
| `ITable` | 76 | 25--284 | 表格行列、单元格、合并拆分、字体/颜色/填充等 |
| `IEmend` | 14 | 25--272 | 修订状态、颜色、查找、接受/拒绝修订 |

接口合计引用数大于 285，是因为同一命令可被多个数据类型接口复用；真正的执行函数仍按全库命令索引唯一登记。

`OStar` 的 `eoalib_GetInterface_OStar()` 根据 `ITF_*` 编号返回创建组件、属性更新、定制对话框、属性变更、取属性数据、按键询问和通知接收者等函数指针。当前组件后端仍为模板状态：`eoalib_ControlCreate_OStar()` 返回 0；属性数据获取/全部属性数据和通知接收者未实现完整状态管理；`eoalib_PropPopDlg_OStar()` 返回 `FALSE`；多数接口回调只有模板分支。

## 5. API、ABI 与内存边界

### 5.1 动态库导出边界

`Source_eoalib.def` 仅导出：

```text
LIBRARY

EXPORTS
    GetNewInf
```

命令函数不通过 PE 导出表直接暴露，而是由 `GetNewInf()` 返回的 `LIB_INFO` 中 `m_pBeginCmdInfo` 与 `m_pCmdsFunc` 以索引对应关系提供给易语言系统。`eoalib_ProcessNotifyLib_eoalib` 通过 `LIB_INFO.m_pfnNotify` 注册。

### 5.2 `LIB_INFO` 注册契约

`elib/lib2.h` 的 `LIB_INFO` 字段依次承载格式号、GUID、版本、所需系统/核心版本、名称/语言/说明、库状态、作者资料、数据类型表、命令表/函数表、AddIn、通知回调、SuperTemplate、常量表和依赖文件列表。`eoalib_dllMain.cpp` 以静态全局对象填充这些字段，`GetNewInf()` 返回其地址；生命周期是进程内静态存活，不需要释放 `LIB_INFO`。

### 5.3 命令参数与返回值

`MDATA_INF` 在 `lib2.h` 中以 1 字节对齐（`#pragma pack(1)`）定义，主体是一个数据联合体加 `DATA_TYPE m_dtDataType`。联合体同时覆盖：

- 基础值：`BYTE`、`SHORT`、`INT`、`INT64`、`FLOAT`、`DOUBLE`、`DATE`、`BOOL`；
- 文本/字节集：`char* m_pText`、`LPBYTE m_pBin`；
- 子程序/语句/组件/复合/数组指针；
- 传引用参数：`m_pInt`、`m_ppText`、`m_ppBin`、`m_pUnit`、`m_ppCompoundData` 等。

`PFN_EXECUTE_CMD` 固定为：

```cpp
typedef void (*PFN_EXECUTE_CMD)(
    PMDATA_INF pRetData,
    INT nArgCount,
    PMDATA_INF pArgInf
);
```

`ARG_INFO` 的参数标志明确区分可空参数、默认值、传变量、传数组、数组/非数组数据以及引用类型。`eoalib_cmdDef.cpp` 只读取输入参数，不释放或替换由运行时托管的文本、字节集和复合数据；一旦补齐真实实现，必须遵守 `NRS_MALLOC`/`NRS_MFREE` 等易语言内存契约，不能直接使用不匹配的 CRT 分配器向 `pRetData` 写入可释放数据。

### 5.4 自定义类型 ABI

`LIB_DATA_TYPE_INFO` 通过命令索引数组把成员命令映射到全局 `CMD_INFO[]`，组件类型还带位图资源 ID、事件数组、属性数组和 `PFN_GET_INTERFACE`。枚举/复合成员则使用 `LIB_DATA_TYPE_ELEMENT`，包括成员类型、中文/英文名、说明、隐藏/默认状态和枚举整数值。

组件创建/属性回调使用 `HUNIT`、`UNIT_PROPERTY_VALUE` 等 Win32/易语言 ABI 类型。`eoalib_dtType.cpp` 当前对这些接口提供了符号和数据表，但真实组件句柄、窗口创建、属性序列化和事件派发尚未形成闭环。

## 6. 功能域地图

根据 285 条命令的中文说明和接口索引，当前 API 可按以下功能域理解：

| 索引范围 | 数量 | 功能域 |
|---:|---:|---|
| 0--52 | 53 | 文档打开/保存/新建、文件内容、修改状态、查找替换、页面基本设置、页眉页脚、分页、背景和页面图像 |
| 53--137 | 85 | 工作表接口、对象接口基础、对象布局/层级/锁定、图形/水印/文本框 |
| 138--197 | 60 | 表格结构、行列、单元格内容/颜色/字体/对齐、合并拆分 |
| 198--258 | 61 | 单元格菜单/锁定/类型、文字编辑、用户、菜单、URL、印章/绘图/图片/图表/填充 |
| 259--284 | 26 | 修订接口、查找/接受/拒绝修订、打印、字体预览、程序名、表格单元格别名和文本 |

这里的范围是按命令索引连续区间归纳，不代表实现文件内部有对应的业务类或状态模块；当前所有命令仍集中在单一的 `eoalib_cmdDef.cpp` 中。

## 7. 依赖与平台边界

### 7.1 源码依赖图

```text
Windows SDK / Win32 headers
        │
        ├── elib/mtypes.h
        ├── elib/lib2.h ── stdio.h / math.h / assert.h
        └── elib/PublicIDEFunctions.h
                │
        elib/krnllib.h + elib/lang.h
                │
        include_eoalib_header.h
          ├── eoalib_cmd_typedef.h
          ├── eoalib_cmdInfo.cpp
          ├── eoalib_cmdDef.cpp
          ├── eoalib_const.cpp
          ├── eoalib_dllMain.cpp
          └── eoalib_dtType.cpp

elib/fnshare.h ── elib/lib2.h
        │
        elib/fnshare.cpp
        eoalib_dllMain.cpp
```

源码直接依赖 Windows/Win32 ABI：`windows.h`、`HWND`、`HMODULE`、`HMENU`、`HGLOBAL`、窗口样式、字体、系统颜色和 `WINAPI` 调用约定。`elib/untshare.h` 明确声明不使用 MFC，但仍使用 Win32 窗口/字体 API。没有发现网络库、数据库、压缩库、办公文档解析库或其他第三方 C/C++ 库的 include/link 配置。

`LIB_INFO.m_szzDependFiles` 为 `NULL`，`NL_GET_DEPENDENT_LIBS` 返回空的双零字符串，表示源码层未声明额外静态库依赖。运行时仍依赖易语言宿主提供 `PFN_NOTIFY_SYS`，并依赖系统核心支持库契约版本。

### 7.2 编码与字符集

源码主体含大量中文字符串，`eoalib_cmd_typedef.h`、`eoalib_cmdDef.cpp`、`eoalib_dtType.cpp` 等按当前文件内容以 CP936/GBK 解码可读；`elib/lang.h` 把编译语言设置为 `__GBK_LANG_VER`。工程的动态库 Win32/x64配置均声明 `CharacterSet=Unicode`，但支持库元数据字符串字段是 `LPCSTR`，命令实现里也主要读取 `LPSTR`，实际编译/运行时编码边界应由易语言 ABI和字符串宏决定，不能仅凭工程 `CharacterSet` 判断。

## 8. 工程、构建与发布形态

### 8.1 动态库工程

`eoalib.vcxproj` 是 `DynamicLibrary`，目标扩展在 Win32 Debug/Release 中设置为 `.fne`；使用 `PlatformToolset v141`、Windows SDK `10.0.15063.0`、Unicode 字符集。Win32 配置显式设置 `__E_FNENAME=eoalib`、`WIN32`、`EOALIB_EXPORTS`、`_WINDOWS`、`_USRDLL`，并通过 `Source_eoalib.def` 参与链接。

### 8.2 静态库工程

`eoalib_static/eoalib_static.vcxproj` 是 `StaticLibrary`，复用上级目录的 6 个 `.cpp` 和 9 个头文件；Win32 Debug/Release 设置 `__E_STATIC_LIB;__E_FNENAME=eoalib`，用于走 `#ifndef __E_STATIC_LIB` 的静态库分支，并编译静态函数名/依赖通知逻辑。

### 8.3 工程配置风险

工程文件虽然列出 Debug/Release 的 x64 配置，但当前配置存在需要后续在 Windows + VS 中复核的风险：

1. 动态库 x64 Debug/Release 的 `PreprocessorDefinitions`（`eoalib.vcxproj:159-184`）没有 `__E_FNENAME=eoalib`，而 `eoalib_cmd_typedef.h` 的 `EOALIB_NAME` 和 `lib2.h` 的符号拼接依赖该宏；
2. 动态库 x64 链接配置（`eoalib.vcxproj:171-197`）没有像 Win32 一样声明 `ModuleDefinitionFile=Source_eoalib.def`；
3. 静态库 x64 Debug/Release 的预处理定义（`eoalib_static/eoalib_static.vcxproj:130-151`）没有 `__E_STATIC_LIB` 和 `__E_FNENAME=eoalib`，但 `include_eoalib_header.h`、`eoalib_dllMain.cpp` 和 `eoalib_dtType.cpp` 的静态/动态分支依赖这些宏；
4. 静态库 x64 使用 `<PrecompiledHeader>Use</PrecompiledHeader>`，但项目文件中没有列出对应 `pch.h`；这可能是旧工程配置残留，需在真实 VS 环境中确认。

上述是静态配置审计结论，不是本机编译结论；本机为 macOS，未执行 MSVC 构建。

## 9. 状态、资源与错误边界

### 9.1 当前可确认的状态

- `s_pfnNotifySys`、`s_pfnuserNotifySys`、`s_isDebug` 是 `fnshare.cpp` 的进程内静态状态；没有线程锁或生命周期管理。
- `g_LibInfo_eoalib_global_var`、命令/参数/类型表是静态存储期数据；没有动态注册和卸载逻辑。
- `eoalib_dllMain.cpp` 的 `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NL_IDE_READY` 等分支当前为空操作。
- 组件创建、属性数据、事件派发和真实文档句柄状态未实现；不能据当前源码推断线程安全、重入安全或多组件隔离能力。

### 9.2 内存管理边界

`elib/fnshare.h` 提供 `ealloc`/`efree`，内部通过 `NotifySys(NRS_MALLOC/NRS_MFREE, ...)` 与易语言系统交互；`CloneTextData`、`CloneTextDataW`、`CloneBinData`、`allocArray` 等辅助函数使用该分配路径。真实返回文本/字节集/数组/复合数据时应继续使用宿主分配协议，并在写回前设置正确 `DATA_TYPE` 和数据布局。

当前命令骨架没有产生返回数据，也没有释放外部资源；因此不能把“没有泄漏”作为已验证结论，只能说当前代码未形成可执行资源路径。

## 10. 测试与验证现状

现场盘点未发现测试文件、测试工程、CI 配置、GitHub/Gitee Actions、示例调用程序或预构建 `.fne/.fnl/.fnr/.lib/.dll` 产物。根目录也没有 README、AGENTS、CLAUDE 或旧 `细探-*.md`。

当前核对执行的只读验证：

- `git status --short --branch`：确认分支和工作树边界；
- `git log -1`、`git remote -v`、`git ls-remote origin`：确认本地/远程版本一致；
- 文件清单/字节头盘点：确认 23 个 Git 跟踪文件，无构建产物；
- C/C++/头文件按 CP936/UTF-8 解码读取并统计符号；
- 解析 `EOALIB_DEF`：285 个连续命令索引，0--284 无缺号；
- 解析实现入口：285 个 `eoalib_*` 命令函数；
- 解析类型表：16 个 `LIB_DATA_TYPE_INFO`；
- 解析接口索引表：`OStar` 72、`IPage` 27、`IWorkSheete` 18、`IObject` 82、`ITable` 76、`IEmend` 14；
- 代码图工具尝试：目标仓库没有 `.codegraph` 索引，因此转为本地只读盘点；未重复调用代码图。

未执行的验证：

- 未执行 Windows/MSVC 编译；
- 未执行 DLL 加载、`GetNewInf` ABI 烟测；
- 未执行易语言 IDE/运行时联调；
- 未执行命令功能、组件创建、属性序列化或事件派发验证；
- 未执行静态库 x64 配置验证。

## 11. 主要风险与后续复核点

### 阻断级（若目标是可运行办公组件）

1. **命令后端缺失**：285 个入口没有 `pRetData` 写回，且没有办公组件对象状态/文档引擎调用；命令表可被宿主发现不等于功能可运行。证据：`eoalib_cmdDef.cpp:8-2336` 的入口集合，函数体仅参数读取或为空。
2. **组件生命周期未闭环**：`eoalib_ControlCreate_OStar()` 返回 0，属性数据和事件接收接口仍是模板；拖放创建、运行时句柄、销毁通知和属性持久化不能工作。证据：`eoalib_dtType.cpp:565-681`。
3. **真实宿主 ABI 未验证**：项目只有 Windows VS 工程，当前环境为 macOS；没有可执行构建或运行时烟测证据。

### 重要风险

1. **x64 工程宏/DEF 配置不对称**：见 `eoalib.vcxproj:159-197`、`eoalib_static/eoalib_static.vcxproj:130-163`，可能导致符号拼接、静态分支和 DLL 导出行为偏离 Win32。
2. **命令索引强耦合**：命令索引同时被 `EOALIB_DEF`、实现符号、函数表、参数偏移和 6 类接口索引引用；增加命令必须保持已有索引稳定，否则旧易语言程序/类型表可能错配。
3. **共享通知状态无并发治理**：`fnshare.cpp:7-9,24-64` 使用全局回调指针和调试状态，没有锁、原子或重入约束说明。
4. **编码边界未实测**：GBK 资源字符串、`LPCSTR/LPSTR`、工程 Unicode 配置并存；需要在目标易语言版本中确认字符串转换和 `ReplaceText` 特例行为。
5. **文档说明与代码行为脱节**：命令说明里包含 FTP、远程文件、打印、图表等能力，但当前仓库没有相应实现依赖或状态对象，不能据说明判定功能存在。

### 建议复核顺序

```text
Windows + VS v141 环境确认
        ↓
先修/确认 x64 预处理宏、DEF、PCH 配置
        ↓
最小 ABI 烟测：加载模块 → GetNewInf → 校验 LIB_INFO
        ↓
命令表/参数表/函数表索引一致性检查
        ↓
实现 OStar 创建、销毁、属性、通知闭环
        ↓
实现一个最小文档链：新建 → 写入/读取 → 保存 → 返回值
        ↓
再按 IPage / IWorkSheete / IObject / ITable / IEmend 分域补实现
        ↓
补宿主集成测试、静态库测试、x86/x64 双架构验证
```

## 12. 证据路径索引

| 主题 | 证据 |
|---|---|
| 库聚合头和全局表声明 | `include_eoalib_header.h:1-26` |
| 285 条命令定义 | `eoalib_cmd_typedef.h:11-298` |
| 参数表和命令元数据生成 | `eoalib_cmdInfo.cpp:5-334` |
| 285 个命令实现入口 | `eoalib_cmdDef.cpp:8-2336` |
| 库注册、GetNewInf、通知入口 | `eoalib_dllMain.cpp:5-184` |
| 自定义类型、方法索引、属性和事件 | `eoalib_dtType.cpp:43-495` |
| 组件接口回调 | `eoalib_dtType.cpp:500-681` |
| 导出边界 | `Source_eoalib.def:1-4` |
| 动态库工程配置 | `eoalib.vcxproj:1-201` |
| 静态库工程配置 | `eoalib_static/eoalib_static.vcxproj:1-166` |
| ABI 结构和函数指针 | `elib/lib2.h:300-430, 520-729, 735-824, 1229-1315` |
| 通知与系统核心版本 | `elib/lib2.h:1046-1174`、`elib/krnllib.h:114-131` |
| 通知转发与宿主内存辅助 | `elib/fnshare.cpp:1-71`、`elib/fnshare.h:20-169` |
| IDE 公共通知定义 | `elib/PublicIDEFunctions.h:1-493` |

## 13. 首轮结论

`eoalib` 的架构骨架是清晰的：以易语言标准 `LIB_INFO` 注册结构为根，以 `EOALIB_DEF` 宏维持命令元数据/函数表/静态编译符号的一致性，以 `LIB_DATA_TYPE_INFO` 描述一个主 Windows 组件和 15 个接口/枚举/复合类型，再通过 `fnshare` 与宿主通知和内存管理协议对接。

但当前快照更准确的定性是“办公组件支持库 ABI 与接口元数据模板/命令骨架”，不是已完成的办公组件运行库。后续任何“功能已支持”“可打开/保存文档”“组件可拖放运行”的结论，都必须以 Windows 目标环境中的真实构建、模块加载、`GetNewInf` 校验和命令/组件端到端证据为准。
