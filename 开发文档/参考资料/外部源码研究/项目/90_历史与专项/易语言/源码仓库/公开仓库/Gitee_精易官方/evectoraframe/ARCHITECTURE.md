# evectoraframe 架构建档

> 本文件是本项目唯一的架构事实归档。首轮建档只读源码、工程文件和 Git 元数据；未修改源码、未安装依赖、未构建、未启动服务、未提交 Git。

## 1. 项目定位

`evectoraframe` 是一个面向 Windows 易语言运行时/IDE 的支持库骨架，库名为“矢量动画框”。它通过易语言支持库 ABI 暴露一组矢量动画、精灵、帧、层、矢量图形、矢量编辑框、矢量按钮和声音相关的命令及自定义数据类型元数据。

源码表现为 Visual Studio C/C++ 支持库工程，而不是完整的矢量动画引擎：

- 支持库登记信息、命令表、参数表、数据类型表、事件表和属性表已经声明；
- DLL 入口、易语言系统通知转发和静态库函数名导出框架已经提供；
- 125 个命令函数均只有参数提取或空函数体，没有实际业务执行、返回值写回或对象状态管理；
- 矢量动画框控件的创建、属性序列化和属性通知函数仍是模板/占位实现；
- 因此当前仓库更准确的定位是“矢量动画支持库接口/元数据骨架”，不能据源码认定为可运行的矢量动画实现。

## 2. 版本与证据基线

| 项目 | 现场事实 |
|---|---|
| 本地根目录 | `~/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/evectoraframe` |
| 本地分支 | `master` |
| HEAD | `fdedd7b5a9388977a963e88a50efd91d8278abaa` |
| HEAD 时间 | `2022-12-19T16:08:17+08:00` |
| HEAD 提交说明 | `初始化仓库` |
| 远程 | `https://gitee.com/JYtechnology/evectoraframe.git` |
| 远程默认分支探测 | `refs/heads/master`，当前远程哈希同为 `fdedd7b5a9388977a963e88a50efd91d8278abaa` |
| 历史深度 | 本地 `.git/shallow` 仅包含 HEAD，为浅克隆；不能据此推断完整历史 |
| 工作树 | 建档开始时干净，无已跟踪或未跟踪变更 |
| 代码地图 | 目标仓库没有 `.codegraph/`，本机 `codegraph_explore` 明确返回未索引；改用只读文件/源码分析 |
| 旧细探 | 目标根未发现 `细探-*.md` |
| 原有架构文档 | 建档前不存在 `ARCHITECTURE.md` |

当前核对通过本地 `system_engineering_toolkit` HTTP MCP（`http://127.0.0.1:8766/mcp/`）先调用了 `project_context` 与 `codegraph_explore`。该 MCP 的项目上下文绑定的是系统工程平台，代码地图也只覆盖系统工程平台，不能作为本仓库源码证据；其 `codegraph_explore` 对 `evectoraframe` 返回无相关代码。目标仓库的事实以下列本地文件为准。

## 3. 真实目录与工程组成

仓库 HEAD 共 23 个跟踪文件（含 Git 元数据之外的工作文件共 23 个）：

```text
根目录/
├── ARCHITECTURE.md                         # 本文件；首轮建档后唯一架构文档
├── include_evectoraframe_header.h          # 统一项目头；导入 elib 与命令声明宏
├── evectoraframe_cmd_typedef.h             # 125 条命令的单一宏定义表
├── evectoraframe_cmdInfo.cpp               # 命令参数表、命令元数据表
├── evectoraframe_cmdDef.cpp                # 125 个命令执行入口，目前全部为空实现
├── evectoraframe_dtType.cpp                # 数据类型、属性、事件、控件接口回调
├── evectoraframe_const.cpp                 # 常量表，目前数量为 0
├── evectoraframe_dllMain.cpp               # DLL 入口、LIB_INFO、通知处理、GetNewInf
├── Source_evectoraframe.def                # DLL 导出，仅导出 GetNewInf
├── evectoraframe.sln                       # Visual Studio 解决方案
├── evectoraframe.vcxproj                   # 动态库工程
├── evectoraframe.vcxproj.filters           # 动态库工程筛选器
├── evectoraframe.vcxproj.user              # 用户工程设置
├── evectoraframe_static/
│   ├── evectoraframe_static.vcxproj        # 静态库工程，复用根目录源码
│   ├── evectoraframe_static.vcxproj.filters
│   └── evectoraframe_static.vcxproj.user
└── elib/
    ├── lib2.h                              # 易语言支持库 ABI、元数据与数据传递契约
    ├── mtypes.h                            # 基础类型、Windows 兼容类型和宏
    ├── lang.h                              # 语言编码版本：GBK
    ├── krnllib.h                           # 系统核心支持库版本/GUID/控件类型常量
    ├── fnshare.h                           # 支持库通知、内存、文本/字节集和数组辅助函数
    ├── fnshare.cpp                          # 通知函数指针、调试版本和用户通知转发
    ├── untshare.h                           # 控件属性序列化辅助类/模板
    └── PublicIDEFunctions.h                # IDE 公共功能辅助定义；本项目仅间接纳入框架
```

源码文件均为 Windows/Visual C++ 风格，使用 CRLF；含中文的 C/C++ 文件现场按 GB18030 解码可读。仓库没有 README、测试目录、CMake、Makefile、包管理文件、第三方依赖清单或运行示例。

## 4. 总体流程图

```text
易语言运行时/IDE
    │
    │ DLL 加载：GetNewInf()
    ▼
LIB_INFO（库身份、版本、平台、命令表、数据类型表、常量表、通知入口）
    │
    ├── g_cmdInfo_evectoraframe_global_var[]
    │       │
    │       ├── 命令中文名/英文名/说明/返回类型/命令状态
    │       ├── 参数起始指针 → g_argumentInfo_evectoraframe_global_var[]
    │       └── 函数指针 → g_cmdInfo_evectoraframe_global_var_fun[]
    │                              │
    │                              ▼
    │                    evectoraframe_<命令>_<索引>_evectoraframe()
    │                              │
    │                              └── 当前仅提取 pArgInf 参数，未执行、未写回 pRetData
    │
    ├── g_DataType_evectoraframe_global_var[]
    │       │
    │       ├── VectorAnimationFrame（窗口组件）
    │       │       └── GetInterface → 创建/属性/通知回调
    │       ├── Sprite / Frame / Layer / Shape / EditText / Button / Sound
    │       └── VectorElementType（枚举）
    │
    └── evectoraframe_ProcessNotifyLib_evectoraframe()
            │
            ├── NL_SYS_NOTIFY_FUNCTION → elib/fnshare.cpp 保存系统通知函数指针
            │                                  → 查询 NRS_GET_PRG_TYPE
            ├── NL_GET_CMD_FUNC_NAMES → 静态编译函数名数组
            ├── NL_GET_NOTIFY_LIB_FUNC_NAME → 返回通知函数名
            ├── NL_GET_DEPENDENT_LIBS → 空依赖列表
            └── 其它生命周期/IDE通知 → 当前多数空处理
```

## 5. 分层与模块职责

### 5.1 支持库外壳层

`evectoraframe_dllMain.cpp` 是动态支持库的登记和通知外壳：

- `DllMain` 仅对进程/线程 attach/detach 做空分支，返回 `TRUE`（7-24 行）；
- `g_LibInfo_evectoraframe_global_var` 填写 ABI 版本 `LIB_FORMAT_VER`、固定 GUID `730FA7B73AAB409a8554F9553CF2DD87`、库版本 `2.0.0`、所需易语言系统 `4.0`、所需核心支持库 `4.0`、名称、GBK 语言、Windows 平台、作者信息以及命令/数据类型/常量指针（31-87 行）；
- `GetNewInf()` 是 DLL 唯一导出入口（89-94 行），并将索引 124 的英文命令名改为 `PlaySound`；
- `Source_evectoraframe.def` 只导出 `GetNewInf`，与 `FUNCNAME_GET_LIB_INFO` 固定约定一致。

### 5.2 命令声明层

`evectoraframe_cmd_typedef.h` 通过 `EVECTORAFRAME_DEF(_MAKE)` 维护 0-124 共 125 条命令。该宏被多次展开以生成：

1. `include_evectoraframe_header.h` 中的 125 个函数声明；
2. `evectoraframe_cmdInfo.cpp` 中的命令元数据；
3. `evectoraframe_dllMain.cpp` 中的函数指针数组和静态编译函数名数组；
4. `evectoraframe_dtType.cpp` 中各自定义类型的成员命令索引；
5. `evectoraframe_cmdDef.cpp` 中的实际函数定义。

这种设计使命令索引、命令元数据和函数入口共享同一列表，但也形成强位置耦合：命令表增删或重排会影响参数偏移、类型成员索引、函数指针数组及静态编译名称。

命令按功能可分为：

- 全局转换：`转换为易动画`（`SWF_To_EVA`，索引 0）；
- 通用组件属性：索引、名称、位置、宽高、可视、缩放、旋转、透明度、深度、拖拽和焦点（索引 1-33 的主要公开/隐藏命令）；
- 动画结构：根精灵、精灵、图形、编辑框、按钮、声音、设置动画数据、复制/删除/调整层次（34-43）；
- 精灵/帧/层生命周期及播放：构造/析构、帧数、播放、停止、跳帧、播放次数、速率（44-79）；
- 矢量编辑框：文本、颜色、字体、只读、选择、换行、多行、对齐、光标和选择区域（80-112）；
- 按钮状态子对象：状态/元素索引对应的图形和编辑框（113-121）；
- 声音：取/置声音、播放声音（122-124）。

### 5.3 命令元数据与参数层

`evectoraframe_cmdInfo.cpp`：

- `g_argumentInfo_evectoraframe_global_var[]` 定义 75 条参数记录（5-138 行），每条含中文名称、说明、图像索引/数量、`DATA_TYPE`、默认值和 `AS_*` 参数标志；
- `g_cmdInfo_evectoraframe_global_var[]` 通过同一命令宏展开为命令描述数组（145-155 行）；
- 参数数组采用“命令宏中的起始偏移 + 参数数量”关联命令；例如索引 0 使用参数 0-1，`SetX` 使用参数 3-4，声音设置使用参数 70-74；
- `AS_RECEIVE_VAR`、`AS_DEFAULT_VALUE_IS_EMPTY` 等标志表达易语言编译器对变量引用、默认空参数和类型传递的约束；
- 调试构建下 `dbg_cmd_arg_count__` 仅计算参数表条数，用于人工确认偏移，不是运行时完整校验。

### 5.4 自定义数据类型/控件层

`evectoraframe_dtType.cpp` 是元数据和控件回调集中处：

- `g_DataType_evectoraframe_global_var[]` 注册 9 个数据类型（302-372 行）：
  - `VectorAnimationFrame`：`LDT_WIN_UNIT` 窗口组件；
  - `Sprite`、`Frame`、`Layer`、`Shape`、`EditText`、`Button`、`Sound`：对象/复合句柄类数据类型；
  - `VectorElementType`：`LDT_ENUM` 枚举类型，成员为 `VectorElementSprite=1`、`VectorElementButton=2`、`VectorElementShape=3`、`VectorElementEditText=4`（181-190 行）。
- `VectorAnimationFrame` 绑定 10 个成员命令索引 34-43、15 个事件、10 个属性（8 个固定窗口属性 + 动画文件名/时钟周期两个专属属性）；
- `Sprite` 绑定索引 44、45 以及通用组件和播放相关命令；`Frame` 绑定 60-66；`Layer` 绑定 67-72；`Shape`/`EditText`/`Button`/`Sound` 通过各自索引数组绑定专属和通用命令；
- 事件参数表 `s_eventArgInfo_evectoraframe_VectorAnimationFrame` 覆盖鼠标、键盘、字符输入和帧加载事件；事件数组共 15 项（192-300 行），并使用 `EV_IS_VER2`；
- 属性数组包含固定的左/顶/宽/高/标记/可视/禁止/鼠标指针，以及 `UD_FILE_NAME` 动画文件名和 `UD_INT` 时钟周期（117-139 行）。

### 5.5 控件交互回调层

`evectoraframe_GetInterface_VectorAnimationFrame()` 将易语言接口编号映射到回调（377-440 行）：

- `ITF_CREATE_UNIT` → `evectoraframe_ControlCreate_VectorAnimationFrame`；
- `ITF_PROPERTY_UPDATE_UI` → 属性可编辑判断；
- `ITF_DLG_INIT_CUSTOMIZE_DATA` → 定制属性对话框；
- `ITF_NOTIFY_PROPERTY_CHANGED` → 属性修改通知；
- `ITF_GET_ALL_PROPERTY_DATA` / `ITF_GET_PROPERTY_DATA` → 属性序列化/读取；
- `ITF_IS_NEED_THIS_KEY` → 按键拦截判断；
- `ITF_GET_NOTIFY_RECEIVER` → 附加通知接收者；
- 图标数据、语言转换、消息过滤接口未提供实现，返回 `NULL`。

当前实际回调状态：

- 创建函数返回 `0`，明确标注 `TODO`（442-459 行）；
- 属性更新函数恒返 `TRUE`（461-466 行）；
- 定制对话框将 `*pblModified=false` 后返回 `FALSE`（468-476 行）；
- 属性变更只保留索引 0 的空分支，最终恒返 `false`（478-497 行）；
- 获取全部属性恒返 `0`（499-504 行）；
- 获取单属性对默认索引 0 走空分支，最后恒返 `true`，其它索引返回 `false`（506-526 行），属于占位语义而非真实属性读取；
- 按键需求恒返 `FALSE`；设计期默认尺寸通知恒返 0（528-555 行）。

### 5.6 命令执行层

`evectoraframe_cmdDef.cpp` 定义 125 个 `EVECTORAFRAME_EXTERN_C void` 命令入口，统一签名为 `(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)`。

源码扫描结果：125/125 个函数体均为“局部参数变量声明或空体”，不存在实际语句、`pRetData` 写回、对象句柄查找、状态更新、系统通知、资源分配或底层播放/解析调用。典型证据：

- `SWF_To_EVA` 只读取 `pArgInf[0].m_pBin` 和 `pArgInf[1].m_ppBin`（1-11 行）；
- `SetX` 只读取整数和重画标志（45-50 行）；
- `SetAnimationData` 只读取二进制参数（334-340 行）；
- `CopyElement`/`DeleteElement`/`ZOrder` 只读取通用对象指针和索引参数（342-382 行）；
- `SetText`/`SetFont`/`SetSound`/`PlaySoundW` 只读取参数（661-674、708-718、1007-1027 行）。

因此命令表的“声明契约”较完整，但“执行契约”尚未落地。所有命令返回值（包括本应返回整数、文本、逻辑值、对象或字节集的命令）在当前源码中都没有被填充。

### 5.7 通知与内存辅助层

`elib/fnshare.cpp` / `elib/fnshare.h` 是项目与易语言系统沟通的共享层：

- `s_pfnNotifySys` 保存易语言系统通知函数指针；`NotifySys()` 负责转发通知（7-16 行）；
- `ProcessNotifyLib()` 处理 `NL_SYS_NOTIFY_FUNCTION`，保存通知入口并通过 `NRS_GET_PRG_TYPE` 查询编辑/调试/发布运行类型，同时在末尾转发给用户回调（24-64 行）；
- `SetUserSysNotify()` 设置用户通知函数并返回 `ProcessNotifyLib`（67-71 行）；
- `ealloc`/`efree` 经 `NotifySys(NRS_MALLOC/NRS_MFREE)` 使用易语言内存；`CloneTextData`、`CloneBinData`、`GetBinData`、数组解析等辅助函数定义在 `fnshare.h`；
- `mtypes.h` 提供 Windows 兼容基础类型，`lang.h` 固定 `__COMPILE_LANG_VER` 为 `__GBK_LANG_VER`，`krnllib.h` 固定系统核心支持库 GUID、文件名和版本常量。

## 6. 核心数据模型

本项目没有数据库、文件型业务模型、C++ 持久化对象或显式运行时状态类。其“数据模型”由易语言支持库 ABI 的静态描述数组组成：

1. **命令模型**：`CMD_INFO`（`elib/lib2.h:297-364`）保存名称、说明、类别、状态、返回类型、学习级别、参数数和参数起始指针；
2. **参数模型**：`ARG_INFO`（`elib/lib2.h:266-292`）保存参数名、说明、数据类型、默认值、传递/引用标志；
3. **数据类型模型**：`LIB_DATA_TYPE_INFO`（`elib/lib2.h:693-729`）保存成员命令索引、窗口组件标志、事件/属性数组、交互接口或枚举成员；
4. **属性模型**：`UNIT_PROPERTY` 和 `UNIT_PROPERTY_VALUE`（`elib/lib2.h:410-458、581-663`）表达设计期/运行期控件属性及其整数、布尔、文本、文件、定制数据等值；
5. **事件模型**：`EVENT_INFO2` / `EVENT_ARG_INFO2`（`elib/lib2.h:493-522`）表达事件名称、参数、返回类型和平台/隐藏标志；
6. **运行参数模型**：`MDATA_INF`（`elib/lib2.h:780-824`）以 union 承载整数、浮点、布尔、文本、字节集、复合数据、变量指针和数组标志；
7. **库登记模型**：`LIB_INFO`（`elib/lib2.h:1248-1318`）把上述命令、函数指针、数据类型、常量、通知函数和依赖文件绑定为一个可加载支持库。

当前模型的生命周期只有框架级入口：DLL 加载、系统通知、命令调用、控件接口调用和卸载通知；没有 `HUNIT` 对应的实际对象分配、索引/名称解析、EVA/SWF 数据结构解析、帧播放计时器、声音缓冲区或属性持久化实现。

## 7. 对外边界与调用契约

### 7.1 DLL/静态库边界

- 动态库外部入口：`GetNewInf`（`.def` 导出）；
- 支持库信息要求：`LIB_FORMAT_VER`、库 GUID、版本、语言、平台、命令/数据类型数组、通知函数；
- 静态库通过 `__E_STATIC_LIB` 分支复用同一源码，并通过 `NL_GET_CMD_FUNC_NAMES`、`NL_GET_NOTIFY_LIB_FUNC_NAME`、`NL_GET_DEPENDENT_LIBS` 返回链接所需信息；
- `include_evectoraframe_header.h` 的 `EVECTORAFRAME_DEF_CMD` 宏生成所有命令的 C 链接声明。

### 7.2 命令边界

- 输入统一是 `PMDATA_INF pArgInf`，参数下标遵循命令参数表偏移；
- 返回统一写入 `PMDATA_INF pRetData`，但当前所有命令均未写入；
- `_SDT_ALL` 用于对象/通用类型参数，不能直接返回数组或含额外内存的复合类型；该限制来自 `elib/lib2.h:337-341`；
- 二进制参数使用 `m_pBin`，输出引用使用 `m_ppBin`；文本使用 `m_pText`，变量/复合数据使用对应指针字段；
- 命令操作系统声明基本都为 `_CMD_OS(__OS_WIN)`，库和数据类型也声明 Windows-only。

### 7.3 控件边界

- 创建参数包括已有属性数据、窗口样式、父窗口句柄、坐标尺寸、窗体/单元 ID、设计窗口句柄和设计模式标志；
- 属性回调必须在设计期返回保存值、运行期返回实时值；源码注释明确了这一 ABI 要求，但实现尚未完成；
- `NU_GET_CREATE_SIZE_IN_DESIGNER` 可返回默认控件尺寸，当前未填宽高且返回 0；
- 事件由支持库元数据注册，实际触发/消息分发依赖未实现的控件对象和易语言运行时。

## 8. 工程、编译配置与依赖边界

### 8.1 工程配置

`evectoraframe.sln` 包含两个项目：动态库 `evectoraframe.vcxproj` 和静态库 `evectoraframe_static/evectoraframe_static.vcxproj`，各自声明 Debug/Release、Win32/x64 配置。解决方案的 `x86` 映射到项目 `Win32`。

动态库工程（`evectoraframe.vcxproj`）：

- 编译单元：`elib/fnshare.cpp`、四个根 C++ 源文件及 `evectoraframe_cmdInfo.cpp`；
- 头文件：`elib` 头文件、统一头、命令 typedef；
- 配置类型：`DynamicLibrary`；
- Win32 Debug/Release 使用 `PlatformToolset=v141`、Unicode、`TargetExt=.fne`；
- Win32 预处理器定义含 `__E_FNENAME=evectoraframe` 和 `EVECTORAFRAME_EXPORTS`；
- Win32 链接使用 `Source_evectoraframe.def`；
- 目标 Windows SDK 写死为 `10.0.15063.0`（43-49 行）。

静态库工程：

- 通过 `..\` 引用根目录源码和头文件；
- 配置类型为 `StaticLibrary`；
- Win32 Debug/Release 预处理器定义含 `__E_STATIC_LIB` 与 `__E_FNENAME=evectoraframe`；
- x64 配置的预处理器定义和预编译头设置与 Win32 不完全一致，存在需要后续在 Windows/Visual Studio 上核对的风险。

### 8.2 框架依赖

源码只显式依赖仓库内 `elib` 框架头和 Windows/Visual C++ ABI：

- `elib/lib2.h`：支持库 ABI、命令/数据类型/事件/属性/通知协议；
- `elib/mtypes.h`：基础类型和兼容宏；
- `elib/lang.h`：GBK 语言版本；
- `elib/krnllib.h`：系统核心支持库契约；
- `elib/fnshare.h/.cpp`：通知和内存辅助；
- `elib/untshare.h`、`PublicIDEFunctions.h`：控件/IDE 辅助定义。

未发现第三方库、包管理描述、外部静态库、运行时服务、配置文件或资源文件。`m_szDependFiles` 在 `LIB_INFO` 中填为 `NULL`，通知返回的依赖库列表为两个零字节字符串。

## 9. 真实调用链与当前完成度

### 9.1 DLL 加载链

```text
易语言加载 evectoraframe.fne
  → 导出符号 GetNewInf
  → 返回 g_LibInfo_evectoraframe_global_var
  → 运行时读取 m_pDataType / m_pBeginCmdInfo / m_pCmdsFunc / m_pfnNotify
  → 支持库可被识别，但是否可运行取决于实际函数体与控件实现
```

该链条的登记部分由 `evectoraframe_dllMain.cpp:31-94` 完成；本地没有 Windows 易语言宿主可供当前核对验证。

### 9.2 命令调用链

```text
易语言编译器/运行时
  → 按 CMD_INFO 的命令索引找到 g_cmdInfo...m_pCmdsFunc[index]
  → 调用 evectoraframe_<英文名>_<index>_evectoraframe(pRetData,nArgCount,pArgInf)
  → 当前函数只读取部分 pArgInf
  → 未调用底层矢量动画库
  → 未修改对象状态
  → 未向 pRetData 写入返回类型/返回值
```

命令入口数量与命令元数据数量均由同一宏表生成，静态结构一致；但行为实现缺失，不能视为有效功能链。

### 9.3 控件调用链

```text
IDE 创建“矢量动画框”
  → 查 LIB_DATA_TYPE_INFO(VectorAnimationFrame)
  → GetInterface(ITF_CREATE_UNIT)
  → ControlCreate(...)
  → 当前返回 HUNIT=0

IDE 读写属性/通知
  → GetInterface 对应 ITF_* 回调
  → 当前多为恒定返回或空分支
  → 没有属性数据存储，也没有窗口句柄/动画实例关联
```

## 10. 已确认的架构特征

1. **单宏源注册**：命令表由 `EVECTORAFRAME_DEF` 一次定义，多处展开，避免命令名/索引/函数指针独立维护。
2. **ABI 元数据优先**：支持库通过静态表描述命令、参数、返回值、事件、属性和数据类型，运行时按索引关联。
3. **动态库/静态库双构建目标**：同一套实现源码通过 `__E_STATIC_LIB` 分支服务 `.fne` 动态库和静态库链接场景。
4. **Windows-only 声明**：库、命令、数据类型和事件均主要使用 `__OS_WIN`，不是跨平台实现。
5. **句柄/复合类型模型**：对象命令使用 `_SDT_ALL` 和库数据类型索引，实际句柄生命周期需要实现者维护。
6. **框架回调完整、业务回调空壳**：接口编号和回调映射已搭好，但创建、属性、通知、命令处理均没有真实状态载体。
7. **编码和宿主耦合**：库标记为 GBK，中文元数据直接进入 C 字符串；编译/运行环境需要兼容易语言的编码和 Windows ABI。

## 11. 风险、缺口与未验证项

### 11.1 当前阻断缺口

- **命令执行缺失**：125 个命令均未写返回值或调用任何实现，支持库不能提供声明之外的真实矢量动画能力。
- **控件实例缺失**：`ControlCreate` 返回 0，没有 HUNIT 对象、窗口句柄、动画数据或定时器管理。
- **属性持久化缺失**：全部属性读写/变更回调没有实际序列化，设计期工程保存和恢复不能据源码确认。
- **资源/生命周期缺失**：构造/析构命令为空，未见动画文件解析、声音缓冲、GDI/窗口资源或内存释放路径。
- **转换实现缺失**：`SWF_To_EVA` 仅提取参数，没有 SWF 解析器或 EVA 编码器。

### 11.2 重要风险

- **命令索引强耦合**：宏表索引同时进入命令元数据、参数偏移、函数指针和数据类型成员列表；修改时必须全链路校验。
- **参数偏移人工维护**：命令宏中的 `g_argumentInfo... + N` 与 75 条参数表靠人工同步；现有调试计数只检查总条数，不检查每条命令的偏移和参数类型。
- **x64 工程配置漂移**：动态库 x64 配置未明显复用 Win32 的 `__E_FNENAME`/`.def` 设置；静态库 x64 使用预编译头但工程文件没有对应 `pch.h` 条目。未构建，暂列待核。
- **浅克隆历史不完整**：`.git/shallow` 只保留初始化提交；无法通过本地历史判断项目是否曾有后续功能分支或被截断的提交。
- **字符编码依赖**：源码包含 GB18030/GBK 中文字符串，换用 UTF-8 或非 Windows 工具链可能改变 ABI 字符串解释。
- **宿主版本耦合**：库要求易语言系统 4.0、核心支持库 4.0，且依赖 `lib2.h` 中的 ABI 结构布局和消息编号；没有宿主兼容性测试。
- **返回值约束尚未落实**：命令声明中存在 `_SDT_ALL`、`SDT_BIN`、文本和对象返回类型，实际写回需要遵守易语言内存管理规则；目前没有任何实现证据。

### 11.3 未验证项

- 未在 Windows/Visual Studio `v141` + Windows SDK `10.0.15063.0` 上编译动态库或静态库；
- 未确认 `evectoraframe.fne` 是否能被易语言 IDE/运行时加载；
- 未调用 `GetNewInf` 验证结构布局、命令计数、数据类型计数和函数指针数组；
- 未验证 `x86`/`x64` 两种目标架构的 ABI、结构对齐和导出符号；
- 未验证 125 条命令的参数偏移是否与参数表逐项一致；
- 未验证 `PlaySound` 索引 124 的运行时命名修正是否覆盖全部静态/动态调用场景；
- 未验证事件触发、事件返回值和 `EV_IS_VER2` 在宿主中的实际行为；
- 未验证属性数据序列化格式、`HGLOBAL` 所有权和 `ealloc/efree` 配对；
- 未验证 EVA 文件格式、SWF 转换格式、动画时钟周期、声音采样率/位数/声道实际语义；
- 未验证仓库远程是否存在未拉取的历史分支或标签（本次只做了远程 heads/tags 探测，未改变浅克隆）；
- 未运行测试，因为仓库没有测试工程，且任务边界禁止构建和运行。

## 12. 后续复核建议

后续若要把该仓库作为实现参考，建议按以下顺序另立深挖任务；当前核对不启动实现：

1. 在隔离 Windows 环境核对 `lib2.h` 结构布局、Visual Studio 配置和 `GetNewInf` 加载；
2. 先补一个最小 `HUNIT`/控件生命周期闭环，再验证固定属性的读写和设计器保存恢复；
3. 冻结命令索引和参数表，自动生成/校验命令索引、参数偏移、返回类型和对象成员列表；
4. 明确 EVA 数据模型与动画对象所有权，再实现 `SWF_To_EVA`、播放、帧跳转、声音和对象操作；
5. 为每个命令建立宿主级真实验证，而不是只检查元数据存在；
6. 分别核对动态库 Win32、动态库 x64、静态库 Win32、静态库 x64 的预处理器、导出和预编译头配置；
7. 若需要完整历史，另建只读远程镜像或解除浅克隆，不在本架构文档中假定缺失历史内容。

## 13. 证据路径索引

| 主题 | 证据 |
|---|---|
| 统一头和命令声明 | `include_evectoraframe_header.h:3-24` |
| 125 条命令定义 | `evectoraframe_cmd_typedef.h:12-137` |
| 命令参数表/命令元数据 | `evectoraframe_cmdInfo.cpp:5-155` |
| 命令函数实现骨架 | `evectoraframe_cmdDef.cpp:1-1028` |
| 数据类型、事件、属性表 | `evectoraframe_dtType.cpp:43-372` |
| 控件接口与占位回调 | `evectoraframe_dtType.cpp:377-555` |
| DLL 登记信息和通知 | `evectoraframe_dllMain.cpp:26-181` |
| 常量表为空 | `evectoraframe_const.cpp:12-18` |
| DLL 导出 | `Source_evectoraframe.def:1-4` |
| 动态库工程 | `evectoraframe.vcxproj:21-201` |
| 静态库工程 | `evectoraframe_static/evectoraframe_static.vcxproj:21-166` |
| 解决方案 | `evectoraframe.sln:1-40` |
| 易语言 ABI 命令/参数 | `elib/lib2.h:149-364` |
| 控件接口/属性/事件 ABI | `elib/lib2.h:395-729` |
| 运行参数 union | `elib/lib2.h:780-824` |
| 支持库登记 ABI | `elib/lib2.h:1248-1318` |
| 系统通知/内存辅助 | `elib/fnshare.h:20-141`、`elib/fnshare.cpp:7-71` |
| 系统核心支持库版本 | `elib/krnllib.h:114-131` |
| GBK 语言标记 | `elib/lang.h:6-14` |

> 维护规则：后续深挖只更新本文件；不得再把新的“细探”摘要并列为事实源。源码、构建、依赖和宿主验证结果必须标明真实执行证据与未验证边界。
