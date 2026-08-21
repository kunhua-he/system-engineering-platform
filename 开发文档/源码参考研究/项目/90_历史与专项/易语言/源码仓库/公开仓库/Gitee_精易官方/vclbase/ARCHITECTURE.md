# vclbase 架构档案

> 首轮全量架构建档。本文是当前仓库唯一架构说明；后续细探应直接更新本文件，不另建平行事实源。
>
> 研究边界：只读人工检查源码、Visual Studio 工程和 Git；未修改源码、工程、依赖、测试或 Git 历史。

## 1. 项目定位

`vclbase` 是面向易语言的 Windows VCL 控件支持库源码骨架。它以易语言支持库 ABI 为边界，向易语言 IDE/运行时注册 `VCLBase` 库信息、35 个全局/对象命令，以及 18 个可视化/对话框数据类型；数据类型包含属性、事件和组件接口回调。

项目名与库元数据均为 `VCLBase`，源码注释说明其目标是提供 Delphi VCL 窗口控件支持，并提到开源组件 `GIFImage`。当前快照更接近“支持库元数据 + 回调模板 + 接口骨架”：控件属性/事件/命令描述较完整，但命令函数和控件创建、属性存取等运行逻辑大量仍是占位实现，不能据此认定已经具备可运行的 VCL 控件功能。

## 2. 总体流程

```text
Visual Studio 构建
    ├─ 动态库目标 vclbase.vcxproj
    │    ├─ 编译 elib 基础 ABI 与内存/通知辅助
    │    ├─ 编译 vclbase_cmdInfo.cpp（参数、命令元数据）
    │    ├─ 编译 vclbase_cmdDef.cpp（35 个命令入口骨架）
    │    ├─ 编译 vclbase_dtType.cpp（数据类型、属性、事件、组件接口骨架）
    │    ├─ 编译 vclbase_const.cpp（常量表，当前为空）
    │    └─ 编译 vclbase_dllMain.cpp（库信息、函数指针表、通知入口）
    │
    └─ 静态库目标 vclbase_static/vclbase_static.vcxproj
         └─ 复用同一组 cpp/h，按 __E_STATIC_LIB 条件裁剪动态库导出/运行时信息

易语言 IDE/运行时
    │
    ├─ 加载模块并查找导出 GetNewInf
    │      └─ 返回 g_LibInfo_vclbase_global_var
    │             ├─ 库版本、GUID、平台、语言、依赖版本
    │             ├─ g_DataType_vclbase_global_var（20 个表项，含隐藏占位项）
    │             ├─ g_cmdInfo_vclbase_global_var（35 个命令描述）
    │             └─ g_cmdInfo_vclbase_global_var_fun（35 个命令函数指针）
    │
    ├─ 设计器按数据类型查找 PFN_INTERFACE
    │      ├─ ITF_CREATE_UNIT → vclbase_ControlCreate_*
    │      ├─ ITF_GET/SET_PROPERTY_* → 属性读写/更新回调
    │      ├─ ITF_GET_NOTIFY_RECEIVER → 事件/通知回调
    │      └─ 其他接口未处理时返回 NULL
    │
    ├─ 执行命令 → vclbase_*_N_vclbase(PMDATA_INF, ...)
    │      └─ 当前主要只读取/绑定参数，未形成控件操作闭环
    │
    └─ 系统通知 → vclbase_ProcessNotifyLib_vclbase
           ├─ NL_SYS_NOTIFY_FUNCTION → 转发 ProcessNotifyLib → 保存系统通知函数
           ├─ NL_GET_CMD_FUNC_NAMES → 返回命令实现名数组
           ├─ NL_GET_NOTIFY_LIB_FUNC_NAME → 返回通知函数名
           ├─ NL_GET_DEPENDENT_LIBS → 返回空依赖串
           └─ 其他通知按模板返回/忽略
```

## 3. 真实目录与文件地图

仓库首轮 Git 清单为 23 个受版本控制文件；没有 README、测试目录、开发文档、AGENTS.md 或旧 `细探-*.md`。

```text
vclbase/
├── vclbase.sln                         # VS 解决方案，动态库 + 静态库
├── vclbase.vcxproj                     # vclbase 动态库工程
├── vclbase.vcxproj.filters             # VS 文件过滤器
├── vclbase.vcxproj.user                # VS 用户配置
├── vclbase_static/
│   ├── vclbase_static.vcxproj         # vclbase_static 静态库工程
│   ├── vclbase_static.vcxproj.filters
│   └── vclbase_static.vcxproj.user
├── Source_vclbase.def                  # 动态库模块定义，仅声明导出 GetNewInf
├── include_vclbase_header.h            # 总入口头文件、全局表声明、命令原型生成
├── vclbase_cmd_typedef.h               # VCLBASE_DEF 命令单一宏清单、命名宏
├── vclbase_cmdInfo.cpp                 # ARG_INFO、CMD_INFO 与参数索引
├── vclbase_cmdDef.cpp                  # 35 个命令函数入口（当前为骨架）
├── vclbase_const.cpp                   # 常量表（当前计数为 0）
├── vclbase_dtType.cpp                  # 数据类型、属性、事件、组件接口回调
├── vclbase_dllMain.cpp                 # DllMain、LIB_INFO、命令函数表、系统通知
└── elib/
    ├── lib2.h                          # 易语言 ABI 基础类型、命令/库/数据类型结构
    ├── mtypes.h                        # Win32 风格基础类型与兼容宏
    ├── krnllib.h                       # 系统核心支持库版本/GUID/文件名常量
    ├── lang.h                          # 语言版本宏（GBK 语言）
    ├── fnshare.h                       # 内存、通知、文本/二进制数据辅助函数
    ├── untshare.h                      # 窗口单元属性、字体、序列化等辅助
    ├── PublicIDEFunctions.h            # IDE 公共函数编号/结构
    └── fnshare.cpp                     # 系统通知转发和调试版本状态
```

## 4. 分层与模块职责

### 4.1 支持库装配层：`vclbase_dllMain.cpp`

- 定义 `DllMain`。四种 DLL 生命周期分支均只 `break`，没有资源初始化或释放逻辑。
- 通过 `VCLBASE_DEF_CMD_PTR` 将 `VCLBASE_DEF` 展开为命令函数指针数组。
- 构造静态 `LIB_INFO g_LibInfo_vclbase_global_var`：
  - `LIB_FORMAT_VER`；GUID `{6793B367-79D9-43F3-88B7-5EB6CF04B618}`；版本 `1.0.2`。
  - 要求易语言系统 `4.0`，系统核心支持库 `4.5`。
  - 库名 `VCLBase`，语言 `__GBK_LANG_VER`，平台 `_LIB_OS(__OS_WIN)`。
  - 数据类型指向 `g_DataType_vclbase_global_var`，命令描述指向 `g_cmdInfo_vclbase_global_var`，命令执行指针指向 `g_cmdInfo_vclbase_global_var_fun`。
  - AddIn、SuperTemplate、依赖文件均为 `NULL`；通知回调为 `vclbase_ProcessNotifyLib_vclbase`。
- 导出 `GetNewInf()`，返回 `&g_LibInfo_vclbase_global_var`。`Source_vclbase.def` 也只列出该导出。
- 处理动态库与静态库共用的系统通知。动态库分支可返回命令函数名、通知函数名和空依赖列表；收到 `NL_SYS_NOTIFY_FUNCTION` 时调用 `ProcessNotifyLib`。

### 4.2 命令契约层：`vclbase_cmd_typedef.h`、`vclbase_cmdInfo.cpp`

`vclbase_cmd_typedef.h` 的 `VCLBASE_DEF(_MAKE)` 是命令清单的单一宏源。当前共有 35 项，索引 `0..34`；其中英文名存在重载式重复：索引 9、10、34 都是 `Open`，通过索引参与 C 函数名拼接。

命令类别按源码注释和命名可归纳为：

| 范围 | 能力主题 | 命令示例 | 当前证据 |
|---|---|---|---|
| 0 | VCL 面板提示 | `SetHint` | 入口存在，仅读取文本参数 |
| 1–4 | VCL 表格单元格文本/附加数据 | `GetCellString`、`SetCellString`、`GetCellData`、`SetCellData` | 入口存在，未调用控件或系统接口 |
| 5–7 | 高级组合框项目 | `AddItem`、`GetItem`、`ModifyItem` | 参数绑定存在，未形成数据操作 |
| 8–11 | 项目数量/打开/关闭 | `GetItemCount`、两个 `Open`、`Close` | 函数体为空 |
| 12–13 | 键值编辑器文本 | `SetCells`、`GetCells` | 参数绑定存在，未读写组件 |
| 14–25 | 属性、下拉、只读、掩码、键名、最大长度 | `SetItemProps`…`GetItemMaxLength` | 参数绑定或空函数，未形成属性实现 |
| 26–27 | 键值 | `SetItemValue`、`GetItemValue` | 参数绑定存在，未操作键值编辑器 |
| 28–30 | 选择区/下拉存在 | `SetSelection`、`GetSelection`、`HasPickList` | 参数绑定存在，未与组件交互 |
| 31–33 | 行操作 | `DeleteRow`、`FindRow`、`InsertRow` | 参数绑定存在，未操作表格 |
| 34 | 另一个 `Open` | `Open` | 函数体为空 |

`vclbase_cmdInfo.cpp` 为每个命令建立 `ARG_INFO` 参数数组，并以 `g_argumentInfo_vclbase_global_var + N` 记录起始偏移；随后用同一 `VCLBASE_DEF` 生成 `CMD_INFO g_cmdInfo_vclbase_global_var`，计算命令数。参数类型使用 `SDT_INT`、`SDT_TEXT`、`SDT_BOOL`，部分输出参数带 `AS_RECEIVE_VAR`。

### 4.3 命令执行层：`vclbase_cmdDef.cpp`

35 个命令函数均使用统一 ABI 签名：

```cpp
void vclbase_<EnglishName>_<index>_vclbase(
    PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf
)
```

实现状态必须区分：

- **已实现：** 函数符号、参数读取类型、与索引对应的函数名均已落盘；可被元数据指针表引用。
- **仅声明/占位：** 除局部变量绑定外，没有设置 `pRetData`、没有检查 `nArgCount`、没有通过 `NotifySys`/`GetWndPtr` 获取控件、没有返回成功/失败结果，也没有释放输出数据。
- **未验证：** 未在 Windows/Visual Studio 中编译或由易语言运行时加载验证，因此不能确认 ABI、调用约定、返回数据布局和静态编译模式全部可用。

### 4.4 数据类型与组件接口层：`vclbase_dtType.cpp`

该文件约 5078 行，包含静态描述表和按数据类型复制的接口回调模板。`g_DataType_vclbase_global_var` 有 20 个表项：索引 0 和 12 是隐藏占位项，索引 1–11、13–19 为 18 个实际数据类型：

| 索引 | 中文名 | 英文名 | 类型/职责标志 | 属性数 | 事件数 |
|---:|---|---|---|---:|---:|
| 1 | VCL窗体 | `VCLForm` | Windows 单元、容器 | 9 | 0 |
| 2 | VCL面板 | `VCLPanel` | Windows 单元、容器 | 13 | 0 |
| 3 | VCL表格 | `VCLGrid` | Windows 单元、容器 | 42 | 3 |
| 4 | VCL高级组合框 | `VCLComboBoxEx` | Windows 单元 | 24 | 5 |
| 5 | 选择颜色对话框 | `ColorDialog` | Windows 单元、函数提供者 | 9 | 0 |
| 6 | 寻找文本对话框 | `FindDialog` | Windows 单元、函数提供者 | 19 | 3 |
| 7 | 带标签编辑框 | `LabeledEdit` | Windows 单元 | 26 | 4 |
| 8 | 掩码编辑框 | `MaskEdit` | Windows 单元 | 21 | 3 |
| 9 | 位图按钮 | `VCLTBitBtn` | Windows 单元 | 16 | 1 |
| 10 | 单选分组框 | `VCLRadioGroup` | Windows 单元 | 15 | 1 |
| 11 | 键值编辑器 | `ValueListEditor` | Windows 单元 | 57 | 14 |
| 13 | 热键框 | `HotKey` | Windows 单元 | 23 | 1 |
| 14 | 打开图片文件对话框 | `OpenPictureDialog` | Windows 单元、函数提供者 | 16 | 0 |
| 15 | 滚动框 | `VCLScrollBox` | Windows 单元、容器 | 20 | 0 |
| 16 | 高级分隔条 | `VCLRbSplitter` | Windows 单元 | 17 | 2 |
| 17 | VCL分割条 | `VCLSplitter` | Windows 单元 | 14 | 2 |
| 18 | 单一实例 | `SingleInstance` | Windows 单元、函数提供者 | 10 | 0 |
| 19 | GIF动画按钮 | `GIFButton` | Windows 单元 | 16 | 1 |

属性表普遍以 8 个固定窗口属性开头：左边、顶边、宽度、高度、标记、可视、禁止、鼠标指针；其余属性按控件补充。事件表使用 `EVENT_INFO2`/`EVENT_ARG_INFO2`，例如表格有“列被移动、行被移动、单元格被选择”，键值编辑器有编辑、刷新、行删除、选择变化等事件。

每个实际数据类型提供同一套接口选择器 `vclbase_GetInterface_<Type>`，按 `nInterfaceNO` 返回函数指针：

- `ITF_CREATE_UNIT` → `vclbase_ControlCreate_<Type>`；
- `ITF_PROPERTY_UPDATE_UI` → `vclbase_PropUpDate_<Type>`；
- `ITF_DLG_INIT_CUSTOMIZE_DATA` → `vclbase_PropPopDlg_<Type>`；
- `ITF_NOTIFY_PROPERTY_CHANGED` → `vclbase_PropChanged_<Type>`；
- `ITF_GET_ALL_PROPERTY_DATA` → `vclbase_PropGetDataAll_<Type>`；
- `ITF_GET_PROPERTY_DATA` → `vclbase_PropGetData_<Type>`；
- `ITF_IS_NEED_THIS_KEY` → `vclbase_PropKetInfo_<Type>`；
- `ITF_GET_NOTIFY_RECEIVER` → `vclbase_PropNotifyReceiver_<Type>`；
- 图标数据、语言转换、消息过滤等未实现分支返回 `NULL`。

当前实现状态：接口选择器和元数据表已实现；`ControlCreate` 函数均保留 `//TODO 在这里创建组件并返回`，返回 `0`；属性全集读取返回 `0`；属性变更仅有 `case 0` 空分支，默认失败；属性读取是模板化返回；自定义对话框将 `*pblModified` 置 `false` 后返回 `FALSE`；按键需求返回 `FALSE`；通知接收器目前只处理默认尺寸消息的模板分支且返回 `0`。这些是已编译的回调骨架，不是完整控件生命周期实现。

### 4.5 运行时辅助层：`elib/`

- `elib/lib2.h`：定义易语言支持库 ABI，包括 `LIB_INFO`、`CMD_INFO`、`ARG_INFO`、`LIB_DATA_TYPE_INFO`、`MDATA_INF`、事件和窗口单元接口常量；同时直接包含 Windows SDK 的 `windows.h`，并提供数据类型/消息/命令宏。
- `elib/mtypes.h`：提供 `INT`、`DWORD`、`HWND`、`HUNIT` 相关基础类型兼容定义，以及 `RECT`、`POINT`、`SIZE` 等 Win32 风格结构和基础宏。
- `elib/fnshare.h/.cpp`：通过 `NotifySys` 使用易语言系统内存服务；提供 `ealloc`/`efree`、文本/字节集复制、数组数据辅助、系统通知转发、调试版本查询和 `SetUserSysNotify`。
- `elib/untshare.h`：围绕窗口单元提供固定属性、属性占位、窗口指针、字体、边框、序列化等辅助；本仓库的 `vclbase_dtType.cpp` 主要依赖其数据结构与宏，而没有形成完整控件封装。
- `elib/krnllib.h`：声明系统核心支持库 `krnln` 的标识和版本 `4.5`，与 `LIB_INFO` 的最低依赖版本相符。
- `elib/lang.h`：提供语言版本宏；库元数据选择 `__GBK_LANG_VER`。
- `elib/PublicIDEFunctions.h`：提供 IDE 公共操作编号和相关结构，当前源码未见将其扩展为独立插件入口。

## 5. 核心数据模型

### 5.1 支持库清单模型 `LIB_INFO`

`vclbase_dllMain.cpp` 构造 `LIB_INFO`，它是宿主加载支持库时的根对象：

```text
LIB_INFO
├── 格式与身份：LIB_FORMAT_VER、GUID、主/次/构建版本
├── 兼容性：易语言系统版本、系统核心支持库版本
├── 描述：名称、语言、说明、作者、主页、Windows 状态
├── 数据类型：数量 + LIB_DATA_TYPE_INFO 数组
├── 命令：数量 + CMD_INFO 数组 + PFN_EXECUTE_CMD 指针数组
├── IDE 扩展：AddIn / SuperTemplate（本库均 NULL）
├── 通讯：PFN_NOTIFY_LIB = vclbase_ProcessNotifyLib_vclbase
└── 依赖文件：m_szzDependFiles（本库为 NULL）
```

### 5.2 命令与参数模型

`CMD_INFO` 描述中文名、英文名、解释、类别、状态、返回数据类型、权限级别、图像信息、参数数量和 `ARG_INFO` 起始指针。`ARG_INFO` 描述参数名、解释、类型、默认值和 `AS_*` 参数标志。命令清单通过 `VCLBASE_DEF` 多次展开，保证命令描述、执行函数指针和静态编译函数名数组按相同索引对齐。

参数运行时载体是 `MDATA_INF`：其数据类型字段为 `m_dtDataType`，根据类型保存整数、文本、字节集、复合数据或窗口单元信息；`PMDATA_INF pArgInf` 约定从下标 1 读取命令参数。当前命令骨架只读取 `m_int`、`m_pText`、`m_ppText`、`m_pInt`、`m_bool` 等字段，尚未写入 `pRetData`。

### 5.3 自定义数据类型模型 `LIB_DATA_TYPE_INFO`

每个数据类型记录中文/英文名、说明、命令索引数组及计数、Windows/容器/函数提供者标志、事件数组及计数、属性数组及计数、接口选择器，以及可选子成员。`vclbase` 当前 18 个实际类型均是 Windows 单元，部分为容器或函数提供者；未使用枚举/普通复合成员数据。

### 5.4 属性与事件模型

- `UNIT_PROPERTY`：属性名、英文名、解释、`UD_*` 类型、平台/隐藏/自定义状态和可选选择字符串。
- 固定窗口属性由 `FIXED_WIN_UNIT_PROPERTY` 提供，确保多对象属性表的名称一致。
- `EVENT_INFO2`：事件名、解释、事件状态、参数数量、`EVENT_ARG_INFO2` 数组和返回类型。
- `EVENT_ARG_INFO2`：参数名、解释、引用状态和 `DATA_TYPE`。
- 属性值运行时由 `UNIT_PROPERTY_VALUE` 承载，回调以 `HUNIT`、属性索引和属性值指针读写。

## 6. 真实调用链与边界

### 6.1 加载链

1. Windows 加载器加载动态库。
2. 宿主按固定名字 `GetNewInf` 获取 `PLIB_INFO`。
3. 宿主读取库版本、平台、语言、命令和数据类型元数据。
4. 宿主通过 `m_pfnNotify` 发送系统通知；`NL_SYS_NOTIFY_FUNCTION` 将系统函数指针交给 `fnshare.cpp` 保存。
5. 宿主根据命令索引调用 `m_pCmdsFunc[index]`，即 `vclbase_*` 命令函数。

### 6.2 可视化设计器链

1. 设计器从 `g_DataType_vclbase_global_var` 取得数据类型。
2. 通过 `m_pfnGetInterface` 查询所需 `ITF_*` 接口。
3. 选择器返回创建、属性、事件通知等回调。
4. 创建回调接收已有属性字节、父窗口句柄、ID、位置尺寸、设计窗口句柄和设计模式标志。
5. 当前创建回调不创建真实控件，统一返回空 `HUNIT`；属性和事件回调同样主要是模板行为。

### 6.3 系统通知链

`vclbase_ProcessNotifyLib_vclbase` 负责宿主到支持库的通知分发：

- `NL_GET_CMD_FUNC_NAMES`：返回 `g_cmdNamesvclbase`，用于静态编译取命令函数名；
- `NL_GET_NOTIFY_LIB_FUNC_NAME`：返回 `vclbase_ProcessNotifyLib_vclbase` 的文本名；
- `NL_GET_DEPENDENT_LIBS`：返回 `"\0\0"`，表示未声明额外静态依赖；
- `NL_SYS_NOTIFY_FUNCTION`：调用 `ProcessNotifyLib`，由 `elib/fnshare.cpp` 保存 `PFN_NOTIFY_SYS` 并查询调试/运行版本；
- `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NR_DELAY_FREE`、`NL_IDE_READY`、`NL_RIGHT_POPUP_MENU_SHOW`、`NL_ADD_NEW_ELEMENT`：当前模板分支不执行实际资源、IDE 或菜单逻辑。

## 7. 接口与 ABI 契约

### 对外导出

| 符号 | 来源 | 状态 |
|---|---|---|
| `GetNewInf` | `vclbase_dllMain.cpp`、`Source_vclbase.def` | 已定义；动态库 Win32 工程显式通过 `.def` 导出 |
| `vclbase_ProcessNotifyLib_vclbase` | `vclbase_dllMain.cpp` | 已定义并挂入 `LIB_INFO.m_pfnNotify` |
| `vclbase_*_N_vclbase` | `vclbase_cmdDef.cpp` | 已定义并通过函数指针数组供宿主调用 |
| `vclbase_GetInterface_*` 与组件回调 | `vclbase_dtType.cpp` | 已定义为内部支持库接口函数，是否由宿主直接查找取决于 `LIB_DATA_TYPE_INFO` |

### 调用约束

- 使用 Windows 调用约定宏 `WINAPI`/`__stdcall` 兼容定义；命令入口用 `EXTERN_C` 规避 C++ 名字修饰。
- 命令函数名由 `__E_FNENAME`、索引和英文名宏拼接，避免多支持库静态链接时冲突。
- 命令函数参数数组从 `pArgInf[1]` 开始；当前代码没有显式核验 `nArgCount` 或空指针。
- 文本、复合数据和需要宿主管理的数据必须遵守 `MDATA_INF` 与 `NotifySys` 的内存/释放约定；当前命令代码没有产出数据，未验证释放路径。
- 属性回调的 `HUNIT`、`UNIT_PROPERTY_VALUE`、`HGLOBAL` 和 `PFN_INTERFACE` 均来自 `elib` ABI；当前回调没有建立真实句柄生命周期。

## 8. 构建工程与依赖

### 8.1 解决方案

`vclbase.sln` 使用 Visual Studio 17 格式，包含：

- `vclbase.vcxproj`：`DynamicLibrary`，项目 GUID `{ceadc3dd-024e-4173-9ccf-e60334b2944f}`；
- `vclbase_static/vclbase_static.vcxproj`：`StaticLibrary`，项目 GUID `{5ff16995-6ad6-4964-a421-e0842e1be946}`；
- 配置：`Debug|Win32`、`Release|Win32`、`Debug|x64`、`Release|x64`。

### 8.2 工程设置证据

- 两个工程均声明 Windows SDK `10.0.15063.0`、平台工具集 `v141`、Unicode 字符集。
- 动态库 Win32 使用 `__E_FNENAME=vclbase`、`VCLBASE_EXPORTS` 等预处理宏，链接 `Source_vclbase.def`，目标扩展为 `.fne`。
- 动态库 x64 的 `ItemDefinitionGroup` 未配置 `ModuleDefinitionFile`，也未看到 `TargetExt=.fne`；是否依赖其他导出机制、是否能产出宿主期望格式，当前未验证。
- 静态库 Win32 明确设置 `__E_STATIC_LIB;__E_FNENAME=vclbase`；静态库 x64 的预处理器定义仅显示 `_DEBUG;_LIB` 或 `NDEBUG;_LIB`，没有看到 `__E_STATIC_LIB` 和 `__E_FNENAME=vclbase`，这是配置差异，需在 Windows 构建时复核。
- 动态库和静态库工程复用同一批 `.cpp/.h`；静态模式依靠 `#ifndef __E_STATIC_LIB` 等条件编译排除 DLL 专属的 `DllMain`、导出元数据和动态库表。

### 8.3 外部依赖

| 依赖 | 证据 | 用途 |
|---|---|---|
| Windows SDK / Win32 API | `elib/lib2.h` 直接 `#include <windows.h>`；工程 Windows SDK 设置 | 基础句柄、窗口单元、DLL/GUI ABI |
| 易语言系统/运行时 ABI | `elib/lib2.h`、`elib/krnllib.h`、`elib/fnshare.h` | `LIB_INFO`、`MDATA_INF`、系统通知、内存服务 |
| 系统核心支持库 4.5 | `vclbase_dllMain.cpp` `m_nRqSysKrnlLibMajorVer/MinorVer` | 运行时兼容性声明 |
| Visual Studio C++ v141 | 两个 `.vcxproj` | 构建工具链 |
| Delphi VCL / GIFImage | `vclbase_dllMain.cpp` 库说明字符串和数据类型命名 | 目标控件生态；本仓库未包含 Delphi/VCL 实现源码 |

未见 `CMakeLists.txt`、Makefile、NuGet/vcpkg 配置、第三方源码、运行时资源、图片或测试依赖声明。

## 9. 测试与验证状态

### 已发现

- Git 清单没有测试文件或测试目录。
- 没有 README、构建说明、CI 配置、测试工程或示例程序。
- 当前仓库在 macOS 主机上检查；Visual Studio/MSBuild、Windows SDK、易语言 IDE/运行时均不可由本次环境验证。

### 当前核对已执行的只读验证

- 人工读取并核对 Git 文件树、解决方案、动态库工程、静态库工程、`.def`、入口头文件、命令元数据、命令定义、数据类型源码和 `elib` 头文件。
- 通过 GBK 解码检查被通用文本阅读器识别为 binary 的 C/C++ 文件；确认 `vclbase_cmdDef.cpp` 有 35 个命令函数，`vclbase_dtType.cpp` 有 20 个数据类型表项（含 2 个隐藏占位项）和 18 个实际类型接口族。
- 检查工作树状态、当前分支、HEAD、远程地址和提交统计。

### 未执行/未验证

- 未在 Windows/Visual Studio 中编译 Debug/Release、Win32/x64 动态库或静态库。
- 未执行 `dumpbin /exports`、易语言支持库加载、IDE 设计器拖放、命令运行、属性序列化/反序列化、事件触发和 DLL 卸载验证。
- 未验证 x64 工程导出与静态库预处理宏差异是否为真实构建缺陷。
- 未验证命令参数声明与宿主 `MDATA_INF` 实际布局、命令返回值约定、`HUNIT` 句柄生命周期和内存释放。

## 10. 已实现、仅声明、未验证矩阵

| 范围 | 已实现证据 | 仅声明/占位证据 | 未验证项 |
|---|---|---|---|
| 库元数据 | `LIB_INFO`、GUID、版本、命令/数据类型指针、`GetNewInf` | 无 | Windows 宿主是否正确加载 |
| 系统通知 | `ProcessNotifyLib` 分发骨架、`NL_SYS_NOTIFY_FUNCTION` 保存通知指针 | 多数通知分支为空 | 实际宿主通知时序 |
| 命令契约 | `VCLBASE_DEF`、35 项 `CMD_INFO`、`ARG_INFO` | `vclbase_cmdDef.cpp` 无返回/业务调用 | 运行时命令行为 |
| 数据类型元数据 | 18 个实际类型、属性/事件表、接口选择器 | 20 表项含隐藏占位项 | IDE 展示与类型索引兼容性 |
| 控件创建 | 回调签名、设计时参数接口 | 所有 `ControlCreate_*` TODO，返回 0 | 是否能创建 VCL 控件 |
| 属性读写 | 固定/专有属性元数据，回调入口 | 全属性读写和变更大多模板返回 | 设计时/运行时数据一致性 |
| 事件 | 事件名、参数和返回类型元数据 | 未见实际事件投递到宿主的完整实现 | 事件回调与返回值 |
| 资源生命周期 | `DllMain` 四分支存在 | 分支为空，未管理组件/资源 | 加载、卸载、释放、延迟释放 |
| 构建 | 两个 VS 工程、四配置、源码清单 | 无 CI/脚本 | 实际编译、链接、导出格式 |

## 11. 风险与后续复核点

1. **功能完成度风险：** 命令入口、控件创建和属性回调大面积为模板。不能把元数据数量等同于功能完成度；后续应逐个确认控件句柄、VCL 消息桥、属性序列化和事件通知。
2. **返回值风险：** `vclbase_cmdDef.cpp` 中命令函数未写 `pRetData`；即便能链接，运行时结果也可能是未定义/空结果。需要以易语言支持库 ABI 的真实示例和 Windows 调试运行结果为准。
3. **句柄生命周期风险：** `HUNIT`、窗口句柄、设计器句柄和系统通知回调没有实际持久化/释放实现；重复创建、卸载、IDE 取消操作可能泄漏或失效。
4. **构建配置风险：** 动态库 x64 未看到 `.def` 与 `.fne` 配置；静态库 x64 未看到 `__E_STATIC_LIB`/`__E_FNENAME`，应优先在 Windows 上复核预处理输出和最终产物。
5. **ABI/编码风险：** 源码主体为 GBK/CRLF；宿主 ABI 使用 Windows 类型和调用约定。跨工具链转换或以 UTF-8/不同结构对齐编译时，需检查字符串、结构体 packing 和导出名。
6. **依赖边界风险：** 库说明提到 Delphi `GIFImage`，但仓库没有 Delphi/VCL 实现、资源或链接库；当前只能确认目标定位，不能确认外部控件依赖已满足。
7. **命令清单一致性风险：** `VCLBASE_DEF` 同时驱动命令描述、函数指针和静态函数名，后续新增/删除/重排命令必须保持参数数组偏移、实现函数和宿主持久化索引兼容。

## 12. Git 基线与证据索引

### Git 基线

- 根目录：`~/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/vclbase`
- 当前分支：`master`，跟踪 `origin/master`。
- HEAD：`a0b89a1e8b5c0d38c4557a97fff468c3a2368763`（短哈希 `a0b89a1`）。
- HEAD 时间：`2022-12-19 16:13:52 +0800`。
- 提交标题：`初始化仓库`。
- 远程：`https://gitee.com/JYtechnology/vclbase.git`。
- 仓库为浅历史/移植快照形态：当前 `git log` 仅见该初始化提交，不能据此推断完整上游历史。
- 建档前工作树：干净；当前核对允许的唯一变更是根目录 `ARCHITECTURE.md`。

### 关键源码证据

- `vclbase_dllMain.cpp:31-89`：`LIB_INFO` 字段、版本/GUID/兼容版本、命令和数据类型指针。
- `vclbase_dllMain.cpp:89-180`：`GetNewInf`、命令名数组及系统通知分发。
- `include_vclbase_header.h:3-24`：公共包含、动态库全局表声明、按命令清单生成命令原型。
- `vclbase_cmd_typedef.h:3-48`：名称拼接宏与 35 项 `VCLBASE_DEF` 命令清单。
- `vclbase_cmdInfo.cpp:1-118`：参数信息、命令信息数组及命令数量。
- `vclbase_cmdDef.cpp:1-353`：35 个命令函数入口和参数读取骨架。
- `vclbase_dtType.cpp:1-1815`：属性/事件/数据类型表；`vclbase_dtType.cpp:1820-5075`：组件接口选择器和回调模板。
- `vclbase_const.cpp:11-18`：当前常量数组大小为 1、实际常量数为 0。
- `elib/lib2.h:294-364`：`CMD_INFO`/`ARG_INFO`；`elib/lib2.h:368-729`：数据类型、事件、属性相关 ABI；`elib/lib2.h:1280-1318`：`LIB_INFO` 与 `GetNewInf` 约定。
- `elib/fnshare.cpp:1-71`、`elib/fnshare.h:21-55`：系统通知、易语言内存与调试版本辅助。
- `vclbase.vcxproj:21-48,51-75,109-153,159-198`：动态库源码、平台配置、工具集、SDK、预处理宏和链接设置。
- `vclbase_static/vclbase_static.vcxproj:21-45,48-72,92-164`：静态库源码复用和配置差异。
- `vclbase.sln:1-40`：解决方案项目及四种平台配置。
- `Source_vclbase.def:1-4`：动态库模块定义与唯一显式导出 `GetNewInf`。

## 13. 结论

首轮建档结论：`vclbase` 已完成支持库层面的 ABI 元数据和 VCL 控件目录描述，具备可供后续实现工作的工程骨架；其核心价值在于数据类型、属性、事件、命令签名和易语言支持库接入模板。当前不能认定为已完成的 VCL 控件运行库：35 个命令没有真正执行逻辑，18 个数据类型的创建/属性/事件回调主要是模板或默认返回，且没有测试、CI 或 Windows 构建证据。后续工作应优先围绕 Windows 构建基线、真实 VCL 控件句柄桥接、属性持久化、命令返回值、事件投递和 x64/静态配置差异开展，并继续在本文件中增量记录证据。
