# egrid 架构与能力审计

> 本文件只记录当前仓库可由源码、ABI 头文件和 Visual Studio 工程直接证明的事实。没有把命令名、返回类型或注释当成功能实现；没有运行 Windows 构建、易语言 IDE 或控件。

## 1. 结论先行

`egrid` 是易语言“高级表格支持库”的 DLL/静态库工程，当前交付物是支持库注册、命令元数据、数据类型元数据和 72 个命令入口的源码骨架。

它**不是可证明可运行的表格控件实现**。仓库中没有 EGrid 控件类、窗口过程、单元格/行列状态、绘制、编辑、剪贴板、文件序列化、打印或事件派发实现。

| 层次 | 当前状态 | 证据 |
|---|---|---|
| Visual Studio 工程 | 有 DLL 与静态库项目、x86/x64 Debug/Release 配置 | `egrid.sln`、两个 `.vcxproj` |
| 支持库 ABI 注册 | 有 | `Source_egrid.def`、`egrid_dllMain.cpp`、`elib/lib2.h` |
| 命令清单与参数元数据 | 有，72 个命令、146 个参数项 | `egrid_cmd_typedef.h`、`egrid_cmdInfo.cpp` |
| EGrid 数据类型元数据 | 有，1 个窗口单元、1 个枚举、38 个属性、10 个事件、45 个枚举成员 | `egrid_dtType.cpp` |
| 命令真实行为 | 未实现 | `egrid_cmdDef.cpp` 的函数只读取部分参数，未写 `pRetData` |
| 控件创建与状态 | 未实现 | `egrid_ControlCreate_EGrid` 返回 `0` |
| 属性持久化与变更 | 未实现 | `egrid_PropGetDataAll_EGrid` 返回 `0`，其余回调为空/占位 |
| 事件与消息处理 | 未实现 | 没有窗口消息过滤、事件触发或回调派发代码 |
| 测试与文档体系 | 无 | 没有 `tests/`、`build/`、`docs/`、README 或测试工程 |

## 2. 运行边界与调用链

```text
易语言 IDE / 运行时
        |
        | LoadLibrary + GetNewInf
        v
egrid DLL
  |-- LIB_INFO: 版本、GUID、库名、依赖、命令/数据类型表
  |-- egrid_ProcessNotifyLib_egrid: 系统通知、命令名、依赖库查询
  |-- g_cmdInfo_egrid_global_var_fun: 72 个命令函数指针
  `-- g_DataType_egrid_global_var: EGrid 与 EGridConst 元数据
        |
        `-- egrid_GetInterface_EGrid
              |-- 创建单元/属性回调（当前均为占位）
              `-- 事件、消息、图标等接口（多数为 NULL）
```

`Source_egrid.def` 只导出 `GetNewInf`。`GetNewInf()` 返回 `egrid_dllMain.cpp` 中的静态 `LIB_INFO`；DLL 生命周期四个 `DllMain` 分支均为空。

`egrid_ProcessNotifyLib_egrid` 的实际行为只有：

- 转发 `NL_SYS_NOTIFY_FUNCTION` 到 `elib/fnshare.cpp`，保存系统通知函数并读取运行类型；
- 返回静态命令名数组、通知函数名和空依赖列表 `"\0\0"`；
- 其他已列出的通知大多空处理，未知通知返回 `NR_ERR`。

## 3. 注册与 ABI

### 3.1 `LIB_INFO`

| 字段 | 当前源码值 |
|---|---|
| GUID | `0B4337DA651B4b619ACF61334A7E8B47` |
| 版本 | `2.11.0` |
| 所需易语言系统/核心支持库 | `3.0` / `3.0` |
| 名称 | `高级表格支持库` |
| 语言 | `__GBK_LANG_VER` |
| 平台标记 | `OS_ALL` |
| 作者 | `大有吴涛易语言软件公司` |
| 依赖文件 | `NULL`；通知查询返回空列表 |

`elib/lib2.h` 定义了 `LIB_INFO`、`CMD_INFO`、`ARG_INFO`、`LIB_DATA_TYPE_INFO`、属性/事件结构、`HUNIT` 和 `PFN_*` 回调类型。命令 ABI 为：

```cpp
void(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)
```

### 3.2 X-macro 命令注册

`egrid_cmd_typedef.h` 的 `EGRID_DEF(_MAKE)` 是命令单一清单，被展开为：

1. `include_egrid_header.h` 中的函数声明；
2. `egrid_cmdInfo.cpp` 中的 `CMD_INFO` 表；
3. `egrid_dllMain.cpp` 中的函数指针表；
4. 静态编译所需的命令名数组。

命令索引 0 至 71 连续，末项为隐藏的 `ClientBackgroundColor`（索引 70），索引稳定性对已编译易语言程序有兼容性意义。`egrid_dtType.cpp` 的 EGrid 命令索引表并非简单的 0 至 71 顺序表：在索引 33、34、35 前插入了 43、44，必须视为独立映射，不能只按命令清单顺序推断。

## 4. 元数据模型

### 4.1 数据类型

`g_DataType_egrid_global_var` 声明两项：

- `EGrid`：Windows 窗口单元，72 个命令、固定窗口属性 8 项、组件属性 30 项、事件 10 项；
- `EGridConst`：Windows 枚举，45 个成员。

属性和事件只描述 IDE/运行时可见的名字、类型、说明、默认值和索引。它们不等于内部状态或行为已经存在。

### 4.2 属性与事件

EGrid 的 38 个属性由 8 个固定窗口属性加 30 个组件属性组成。组件属性覆盖颜色、行列数、行列尺寸、编辑、打印、选择、边框和显示格式等。

10 个事件覆盖光标移动、编辑前后、行高/列宽改变、单击、列表项选择、可否编辑、表头单击/双击。仓库没有事件触发源，也没有 `ITF_MSG_FILTER` 实现。

### 4.3 枚举

`EGridConst` 的值覆盖行/列线、左右/居中对齐、文本/数值/日期/列表/图片/货币单元格、日期和货币格式、图片显示方式、四则运算、线型和打印页边距。定义位于 `egrid_dtType.cpp`，不是 `egrid_const.cpp`。

`egrid_const.cpp` 只有被注释的常量草稿以及一个实际计数为 0 的常量数组；因此“45 个枚举成员”和“库常量数量”是两个不同概念，不能混写。

## 5. 真实实现审计

### 5.1 命令函数

`egrid_cmdDef.cpp` 的 72 个函数都具备 ABI 入口。部分函数把 `pArgInf` 读入局部变量，例如 `SetData`、`SetFontName`、`PrintTo` 和 `SetEditFontAndColor`；但没有访问控件对象、没有边界/空指针检查、没有写 `pRetData`，函数随后结束。

因此命令元数据中的“成功/失败”“返回 -1”“返回布尔值”“读写文件/打印/公式”等内容只能判定为**声明或历史意图**，不能判定为可调用能力。

### 5.2 控件与属性回调

`egrid_ControlCreate_EGrid` 明确保留 TODO，忽略所有创建参数并返回 `HUNIT 0`。

`egrid_GetInterface_EGrid` 当前提供的回调及结果：

| 接口 | 实际结果 |
|---|---|
| `ITF_CREATE_UNIT` | 返回创建函数，但创建函数返回 0 |
| `ITF_PROPERTY_UPDATE_UI` | 无条件返回 `TRUE` |
| `ITF_DLG_INIT_CUSTOMIZE_DATA` | 写 `*pblModified=false` 后返回 `FALSE`，且未检查空指针 |
| `ITF_NOTIFY_PROPERTY_CHANGED` | 只有空的 `case 0`，其他索引返回 `false` |
| `ITF_GET_ALL_PROPERTY_DATA` | 返回 0 |
| `ITF_GET_PROPERTY_DATA` | 只有空的 `case 0`，未填值；其他索引返回 `false` |
| `ITF_IS_NEED_THIS_KEY` | 返回 `FALSE` |
| `ITF_GET_NOTIFY_RECEIVER` | 返回通知函数，但默认创建尺寸仍返回 0 |
| `ITF_GET_ICON_PROPERTY_DATA`、`ITF_LANG_CNV`、`ITF_MSG_FILTER` | `NULL` |

`elib/untshare.h` 提供的 `CPropertyInfo`、序列化、图标加载和窗口样式辅助函数也多为模板或注释代码，不能作为 EGrid 实现证据。

## 6. 工程、ABI 和配置风险

- DLL 工程 `egrid.vcxproj` 使用 `v141`、Windows SDK `10.0.15063.0`，Win32 配置设置了 `__E_FNENAME=egrid` 和 `.fne` 目标扩展名；x64 配置没有这两个关键设置，也没有模块定义文件配置。`lib2.h` 在未定义 `__E_FNENAME` 时会直接报错，因此 x64 配置至少需要在 Windows/VS 环境实际核验。
- 静态库工程 Win32 配置设置 `__E_STATIC_LIB;__E_FNENAME=egrid`；x64 Debug/Release 只设置 `_LIB`，缺少这两个宏，并且使用 `PrecompiledHeader=Use`，但工程文件未列出 `pch.h`。该配置不能按“已有静态库构建能力”表述。
- 解决方案把 x86 映射到项目的 Win32 配置，把 x64 映射到 x64 配置；解决方案存在不代表四种配置都能编译。
- `LIB_INFO` 使用 `OS_ALL`，而 EGrid 数据类型、命令和大部分属性实际标记 Windows；这属于注册平台声明与实际数据模型之间的冲突，不能据此推断跨平台可用。
- 源码含 GBK/本地中文编码痕迹，项目工程设置为 Unicode，但支持库语言元数据固定为 GBK；编码和 ABI 兼容性需要 Windows 工具链实测。
- `egrid_cmd_typedef.h`、参数数组、命令实现和数据类型命令索引分散维护，仓库没有一致性测试；新增、删除或重排命令可能破坏 ABI/静态命名兼容。

## 7. 仓库范围与缺失项

当前仓库的源文件和工程文件集中在根目录及 `elib/`、`egrid_static/`：

- 注册/导出：`Source_egrid.def`、`egrid_dllMain.cpp`；
- 命令：`egrid_cmd_typedef.h`、`include_egrid_header.h`、`egrid_cmdInfo.cpp`、`egrid_cmdDef.cpp`；
- 数据类型：`egrid_dtType.cpp`、`egrid_const.cpp`；
- ABI：`elib/lib2.h`、`krnllib.h`、`fnshare.h/.cpp`、`lang.h`、`mtypes.h`、`untshare.h`、`PublicIDEFunctions.h`；
- 构建：`egrid.sln`、`egrid.vcxproj`、`egrid_static/egrid_static.vcxproj` 及其 filters/user 文件。

未发现：`tests/`、`build/`、`docs/`、README、脚本、资源文件、第三方控件源码、包管理清单、子模块或运行时数据。根文档本身是当前取证新增的唯一说明文件。

## 8. 验证状态

### 已完成

- 在目标 egrid 根目录完成 CodeGraph 尝试；目录没有 `.codegraph/` 索引，CodeGraph 未运行，未自行初始化。
- 分段读取注册、命令表、控件/属性/事件、ABI、元数据、实现、测试目录、构建工程和文档目录。
- 静态交叉核对 72 个命令、146 个参数项、2 个数据类型、38 个属性、10 个事件和 45 个枚举成员。
- 确认没有 `tests/`、`build/`、`docs/` 目录，也没有 README 或其他架构/研究材料文档可合并。

### 未完成

- 未执行 Visual Studio/MSBuild、编译器或链接器；
- 未加载 DLL/静态库，未调用 `GetNewInf`，未在易语言 IDE 中创建 EGrid；
- 未运行命令、属性、事件、打印、文件读写或 ABI 兼容测试；
- 未验证 x86/x64 四种配置的实际构建结果。

## 9. 后续核验顺序

1. 在 Windows + 对应 Visual Studio 工具链中分别构建 DLL 和静态库四种配置，先修复/确认 x64 宏、PCH 和 `.def` 差异。
2. 用导出检查确认 DLL 只暴露 `GetNewInf`，加载后核对 `LIB_INFO`、命令表、参数索引和数据类型表。
3. 追查历史版本或外部依赖中是否存在真正的 EGrid 控件实现；当前仓库不能补足这部分证据。
4. 若控件实现确实缺失，再分别建立创建/销毁、属性序列化、命令返回值、事件派发、文件读写和打印测试。
5. 建立自动一致性检查，覆盖 X-macro 命令索引、146 个参数起始偏移、命令函数表和 EGrid 命令映射。

## 10. 基线

- 项目根：`~/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/egrid`
- 远程：`https://gitee.com/JYtechnology/egrid.git`
- 分支/提交：`master` / `f034f889ee97276ea2a77f3fa75256e14041cb20`
- 提交说明：`初始化仓库`
- 当前取证修改：仅根 `ARCHITECTURE.md`；未修改源码、工程文件或 ABI 头文件。

## 11. 小型仓规模说明与边界

`egrid` 仅包含 23 个跟踪文件，全部为支持库生成模板：`egrid_cmdDef.cpp`、`egrid_cmdInfo.cpp`、`egrid_cmd_typedef.h`、`egrid_dtType.cpp`、`egrid_const.cpp`、`egrid_dllMain.cpp`、`include_egrid_header.h`、`Source_egrid.def`、动态/静态 `vcxproj` 及 `elib/*`。未发现网格控件实现、资源、示例、测试或第三方依赖。

因此不能从命令元数据推导单元格模型、绘制、编辑、事件派发或线程安全已经实现；也没有 Windows/MSVC 构建和易语言宿主加载证据。文档保持小型仓应有的事实密度，并明确将 DLL 导出、ABI 宽度、空处理器和资源释放列为使用前验证项。
## 14. 当前源码级深审收口

### 14.1 真实文件树与入口

- ./ARCHITECTURE.md
- ./Source_egrid.def
- ./egrid.sln
- ./egrid.vcxproj
- ./egrid.vcxproj.filters
- ./egrid.vcxproj.user
- ./egrid_cmdDef.cpp
- ./egrid_cmdInfo.cpp
- ./egrid_cmd_typedef.h
- ./egrid_const.cpp
- ./egrid_dllMain.cpp
- ./egrid_dtType.cpp
- ./egrid_static/egrid_static.vcxproj
- ./egrid_static/egrid_static.vcxproj.filters
- ./egrid_static/egrid_static.vcxproj.user
- ./elib/PublicIDEFunctions.h
- ./elib/fnshare.cpp
- ./elib/fnshare.h
- ./elib/krnllib.h
- ./elib/lang.h
- ./elib/lib2.h
- ./elib/mtypes.h
- ./elib/untshare.h
- ./include_egrid_header.h

- 版本 HEAD f034f889ee97276ea2a77f3fa75256e14041cb20；代码地图目录存在但 CLI 在该父仓返回未初始化/不可用，以下结论来自上述文件树和 rg 源码定位。

### 14.2 核心符号与 ABI

- egrid_dtType.cpp:4-389 的 EGrid/EGridConst 类型、属性表和 10 类事件。
- egrid_dllMain.cpp、Source_egrid.def、include_egrid_header.h 和 egrid_cmd_typedef.h 共同定义 DllMain/GetNewInf、导出边界、命令参数和函数指针表。
- elib/mtypes.h、fnshare.h、PublicIDEFunctions.h、krnllib.h 提供 PMDATA_INF、HUNIT、属性/事件结构和宿主内存约定。

### 14.3 调用流程

易语言装载器 -> GetNewInf -> 命令/数据类型表 -> 参数转换 -> 原生实现 -> 返回值或事件 -> 宿主释放

### 14.4 构建与资源

- egrid.sln/.vcxproj 提供 Visual Studio Win32/x64 配置，静态工程位于 egrid_static（若存在）；当前未执行 MSBuild。
- 句柄、COM/Windows 控件、PMDATA_INF、HGLOBAL 和回调归宿主与 DLL 协同管理，仓库没有统一资源账本。
- 未发现独立自动化测试；测试证据限于源码和工程配置。

### 14.5 失败边界与平台复用

- ABI 位数/调用约定、命令索引漂移、属性越界、宿主提前卸载、外部 Excel/COM/GUI 依赖和回调重入是主要失败边界。
- 不宣称跨进程恢复、重试、取消或事务；平台复用时应将该 DLL 包装为受管提供者，显式转换错误、权限和资源释放。
- 当前文档仅修改根 ARCHITECTURE.md；源码、工程、资源未改。
### 14.6 完整审计裁决

- 远端 `origin/HEAD` 与本地 HEAD 均为 `f034f889ee97276ea2a77f3fa75256e14041cb20`，未发现需要同步的提交；工作树只有根文档和代码地图缓存未跟踪。
- `egrid_cmd_typedef.h` 的 72 个命令和 146 个参数只生成元数据/函数指针；`egrid_cmdDef.cpp` 当前函数体未形成控件状态实现，不能把命令名称当作可运行功能。
- `egrid_dtType.cpp:210-222` 登记 EGrid 与 EGridConst；`egrid_GetInterface_EGrid:230-287` 只返回回调地址，`egrid_ControlCreate_EGrid:296` 返回空句柄，属性数据和通知回调没有可证明的状态存储。
- `egrid_dllMain.cpp:7-20` 的 DllMain 分支为空；`GetNewInf` 返回静态 LIB_INFO；`Source_egrid.def` 仅导出 GetNewInf。宿主通知只覆盖系统通知函数和命令名查询。
- 依赖边界是 Windows、易语言运行时、MSVC Win32/x64 和 elib ABI；没有测试工程、构建脚本、控件实现、消息泵或持久化文件。
- 平台复用启示：只可吸收“能力注册表/命令元数据/宿主回调契约”模式；必须补齐受管控件实现、句柄租约、错误结果、构建验证和卸载清理后才能作为支持库。
- 未验证项保持明确：Windows MSBuild、LoadLibrary/GetNewInf、EGrid 控件创建、属性变更、事件派发、命令返回、资源释放和多线程重入均未运行。
