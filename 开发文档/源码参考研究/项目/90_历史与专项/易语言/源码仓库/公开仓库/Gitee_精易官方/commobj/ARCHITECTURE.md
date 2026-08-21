# commobj 架构建档

> 本文件是 `commobj` 项目根目录唯一架构事实源。首轮建档按当前本地源码与 Git 元数据完成；源码只读，未修改源码、未安装依赖、未构建、未运行服务或测试、未提交 Git。

## 1. 项目定位

`commobj` 是一个面向 Windows 易语言运行时/IDE 的支持库工程，库名为“通用对象支持库”。它声明并导出两个自定义数据类型：`RapidString`（快速文本对象）和 `RapidBinary`（快速字节集对象），为易语言的文本、字节集数据提供对象方法元数据和命令入口。

当前仓库中的命令实现文件明显是**生成后的接口骨架/未完成实现快照**：共生成 140 个命令函数，其中 106 个函数体为空，另外 34 个函数体仅从 `pArgInf` 提取局部参数，没有对 `pRetData` 写返回值，也没有对象状态读写或算法调用。因此，当前源码足以分析支持库的注册、元数据和 ABI 边界，但不能据此证明“快速文本对象/快速字节集对象”的运行时功能已经实现。

## 2. 证据基线

| 项目 | 当前事实 |
|---|---|
| 本地根目录 | `/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/commobj` |
| 本地分支 | `master`，跟踪 `origin/master` |
| 本地提交 | `b9deb37193152ac4c29cb0ef6a1988543509b859` |
| 本地提交时间 | `2022-12-19T16:53:41+08:00` |
| 本地提交主题 | `初始化仓库` |
| 远程地址 | `https://gitee.com/JYtechnology/commobj.git` |
| 远程 `HEAD`/`master` | `b9deb37193152ac4c29cb0ef6a1988543509b859`，与本地一致 |
| 工作树 | 建档前干净；本轮只新增本文件，未提交 |
| 仓库形态 | Git 浅克隆（存在 `.git/shallow`），当前仅见 `master` 与 `origin/master` |
| 源码文件编码 | C/C++ 中文源码实测按 `gb18030` 可读，文件含 CRLF；不是 UTF-8 证据 |
| 目录级说明 | 未发现 `README*`、`AGENTS.md`、`CLAUDE.md`、旧 `细探-*.md` 或既有 `ARCHITECTURE.md` |

```text
易语言 IDE/运行时（e.exe 等）
        │
        ├─ 动态库路径：加载 commobj*.fne/.dll
        │       │
        │       ├─ 导出入口 GetNewInf()
        │       │       └─ 返回 LIB_INFO
        │       │                 ├─ 2 个自定义数据类型
        │       │                 ├─ 140 项 CMD_INFO
        │       │                 └─ 140 项 PFN_EXECUTE_CMD
        │       │
        │       └─ NL_SYS_NOTIFY_FUNCTION → commobj_ProcessNotifyLib_commobj
        │                                 → elib/fnshare.cpp::ProcessNotifyLib
        │
        ├─ 命令调用：CMD_INFO 索引
        │       └─ PFN_EXECUTE_CMD(pRetData, nArgCount, pArgInf)
        │                       └─ commobj_cmdDef.cpp 中的 140 个入口骨架
        │
        └─ 静态库路径：commobj_static.vcxproj
                └─ 用 __E_STATIC_LIB 编译同一组实现/元数据源码
                   └─ 通过通知码返回命令函数名、通知函数名、依赖列表
```

## 3. 真实目录与文件地图

仓库共 22 个受 Git 跟踪的项目文件（不含 `.git` 元数据）：

```text
commobj/
├── commobj.sln                         # VS 解决方案，动态库 + 静态库两个项目
├── commobj.vcxproj                     # commobj 动态库项目
├── commobj.vcxproj.filters             # VS 文件筛选器
├── commobj.vcxproj.user                # 用户级 VS 配置
├── commobj_static/
│   ├── commobj_static.vcxproj         # commobj_static 静态库项目
│   ├── commobj_static.vcxproj.filters
│   └── commobj_static.vcxproj.user
├── include_commobj_header.h            # 统一公共头、全量命令声明
├── commobj_cmd_typedef.h               # COMMOBJ_DEF：140 项命令的唯一宏清单
├── commobj_cmdInfo.cpp                 # ARG_INFO 参数元数据、CMD_INFO 命令表
├── commobj_cmdDef.cpp                  # 140 个命令函数入口（当前为骨架）
├── commobj_dtType.cpp                  # RapidString/RapidBinary 类型和方法索引
├── commobj_const.cpp                   # 常量表（当前数量为 0）
├── commobj_dllMain.cpp                 # DllMain、LIB_INFO、GetNewInf、通知分发
├── Source_commobj.def                  # Win32 动态库导出 GetNewInf
└── elib/
    ├── lib2.h                          # 易语言支持库核心 ABI/数据结构/通知码
    ├── mtypes.h                        # 基础类型兼容定义
    ├── lang.h                          # GBK/英语/BIG5/SJIS 语言版本宏
    ├── krnllib.h                       # 核心库相关兼容头
    ├── fnshare.h                       # 支持库共享辅助函数/内存/数组操作
    ├── fnshare.cpp                     # 通知回调和调试版本状态
    ├── untshare.h                      # 对象/属性序列化与窗口辅助头
    └── PublicIDEFunctions.h            # IDE 公共函数声明
```

### 文件职责与真实引用关系

- `include_commobj_header.h` 依次包含 `elib/lib2.h`、`elib/lang.h`、`elib/krnllib.h` 和 `commobj_cmd_typedef.h`，并在非静态模式下声明全局命令/类型/常量表。
- `commobj_cmd_typedef.h` 的 `COMMOBJ_DEF(_MAKE)` 是全量命令清单；其他源码通过宏多次展开它，生成函数声明、函数指针表、命令元数据和静态命令名数组。
- `commobj_cmdDef.cpp` 只包含 `include_commobj_header.h`，定义编号 `0..139` 的 C 链接命令函数。
- `commobj_cmdInfo.cpp` 只包含统一头，定义 57 条参数元数据和 `g_cmdInfo_commobj_global_var[]`；整个文件主体由 `#if !defined(__E_STATIC_LIB)` 包围。
- `commobj_dtType.cpp` 只包含统一头，定义两个对象类型各 60 个方法索引及各 10 个隐藏事件成员。
- `commobj_dllMain.cpp` 还包含 `elib/fnshare.h`、`elib/lang.h`，负责库级信息和系统通知。
- `elib/fnshare.cpp` 只包含 `fnshare.h`；`elib/fnshare.h` 只包含 `lib2.h`。源码没有项目内第三方库目录或外部 SDK 封装层。

## 4. 构建工程与目标

### 4.1 解决方案

`commobj.sln` 是 Visual Studio 17 格式（`Format Version 12.00`），包含：

1. `commobj` → `commobj.vcxproj` → `DynamicLibrary`。
2. `commobj_static` → `commobj_static/commobj_static.vcxproj` → `StaticLibrary`。

解决方案声明 `Debug/Release × x86/x64` 四类配置；解决方案的 `x86` 配置映射到项目的 `Win32`。

### 4.2 动态库项目

`commobj.vcxproj` 的编译源文件为：

- `elib/fnshare.cpp`
- `commobj_cmdDef.cpp`
- `commobj_const.cpp`
- `commobj_dllMain.cpp`
- `commobj_dtType.cpp`
- `commobj_cmdInfo.cpp`

头文件为 `elib/` 下 7 个头、`include_commobj_header.h`、`commobj_cmd_typedef.h`；`Source_commobj.def` 是项目的 `None` 项。

工程目标事实：

- `WindowsTargetPlatformVersion = 10.0.15063.0`。
- `PlatformToolset = v141`。
- 字符集为 `Unicode`。
- Win32 Debug/Release 的预处理器包含 `__E_FNENAME=commobj`，并使用 `Source_commobj.def` 链接；Win32 配置目标扩展为 `.fne`。
- Win32 Debug 使用静态运行库调试版，Release 使用静态运行库。
- x64 配置为动态库，但其预处理器定义中没有看到 `__E_FNENAME=commobj`，且 Link 节没有看到 `ModuleDefinitionFile`；这属于待在 Windows/MSVC 环境实际验证的配置风险，不能在本机 macOS 上下结论。

### 4.3 静态库项目

`commobj_static/commobj_static.vcxproj` 复用父目录同一批 `.cpp/.h`，路径以 `..\` 引用；Win32 预处理器含 `__E_STATIC_LIB;__E_FNENAME=commobj`。静态库没有 `.def` 文件，依赖由通知码 `NL_GET_DEPENDENT_LIBS` 约定返回。

配置风险：静态库 x64 的 `PrecompiledHeader` 为 `Use`，但仓库文件地图没有 `pch.h`；同时 x64 预处理器定义没有 `__E_FNENAME=commobj`。这些均只做静态配置记录，未执行构建验证。

## 5. 核心数据模型与元数据

### 5.1 `LIB_INFO`

`elib/lib2.h` 定义 `LIB_INFO`，`commobj_dllMain.cpp` 初始化 `g_LibInfo_commobj_global_var`：

| 字段 | 当前值/含义 |
|---|---|
| `m_dwLibFormatVer` | `LIB_FORMAT_VER`，宏值 `20000101` |
| `m_szGuid` | `{A068799B-7551-46b9-8CA8-EEF8357AFEA4}` |
| 版本 | 主版本 `2`、次版本 `0`、构建号 `0` |
| 系统要求 | 易语言系统 `3.7`；系统核心支持库 `3.7` |
| `m_szName` | `通用对象支持库` |
| `m_nLanguage` | `__GBK_LANG_VER`（值 1） |
| `m_dwState` | `_LIB_OS(OS_ALL)`，未设置 IDE 插件/数据库等额外标志 |
| 作者信息 | `大有吴涛易语言软件开发有限公司`，地址/电话/邮箱/主页写在源码中 |
| 自定义类型 | `g_DataType_commobj_global_var`，数量 2 |
| 全局命令类别 | 1 个，字符串为 `0000命令分类\0\0` |
| 命令表 | `g_cmdInfo_commobj_global_var`，数量由数组计算为 140 |
| 函数指针表 | `g_cmdInfo_commobj_global_var_fun`，与命令表按索引一一对应 |
| 通知函数 | `commobj_ProcessNotifyLib_commobj`，按 ABI 不应为 NULL |
| 常量 | `g_ConstInfo_commobj_global_var`，数组容量 1，但数量为 0 |
| 依赖文件 | `m_szzDependFiles = NULL`，源码未声明额外支持文件 |

`GetNewInf()` 是固定 ABI 入口，返回 `&g_LibInfo_commobj_global_var`；进入函数时将命令索引 36 的英文名从生成名 `ReplaceTextW` 修正为 `ReplaceText`。

### 5.2 自定义数据类型

`commobj_dtType.cpp` 建立两条对象类型记录：

1. `快速文本对象` / `RapidString`：方法索引 `20..79`，共 60 个槽位。
2. `快速字节集对象` / `RapidBinary`：方法索引 `80..139`，共 60 个槽位。

每个类型还有 10 个 `LIB_DATA_TYPE_ELEMENT` 槽位，当前均为 `_SDT_INT`、`LES_HIDED` 且名称/说明为空；不是公开属性/事件实现的证据。两个对象的构造、复制构造、析构方法分别位于各自方法段开头，命令清单把它们标记为 `CT_IS_OBJ_CONSTURCT_CMD`、`CT_IS_OBJ_COPY_CMD`、`CT_IS_OBJ_FREE_CMD`。

### 5.3 命令与参数

`COMMOBJ_DEF` 共 140 项，编号连续 `0..139`：

- 95 项带 `CT_IS_HIDED`，主要是隐藏占位命令、构造/析构槽位和预留编号。
- 45 项可见命令，其中 `RapidString` 与 `RapidBinary` 各有一组同名/同语义方法。
- 文本对象公开能力覆盖：取长度、取/置/清除文本、添加、插入、删除字符、寻找/倒找、替换、分割、大小写转换、全半角转换、去空格、文件读写、缓冲区、内存容量与增量。
- 字节集对象公开能力覆盖：取长度、取/置/清除字节集、添加、插入、删除字节、取字节、寻找/倒找、替换、分割、文件读写、缓冲区、内存容量与增量。
- `commobj_cmdInfo.cpp` 有 57 条带序号注释的 `ARG_INFO` 数据，参数类型包含 `SDT_INT`、`SDT_BOOL`、`SDT_TEXT`、`SDT_BIN`、`SDT_BYTE`、`_SDT_ALL`，并使用 `AS_DEFAULT_VALUE_IS_EMPTY`、`AS_HAS_DEFAULT_VALUE`、`AS_RECEIVE_ALL_TYPE_DATA` 等标志。
- `SplitText`、`SplitBinary` 的命令状态含 `CT_RETRUN_ARY_TYPE_DATA`，表示返回数组数据。
- `GetBuffer` 的返回类型在元数据中是 `SDT_INT`，源码注释把它描述为缓冲区首地址；这是易语言运行时的 ABI 约定，不应按普通整数语义使用。

## 6. ABI、入口与调用边界

### 6.1 动态库入口

`Source_commobj.def` 只声明：

```text
LIBRARY
EXPORTS
    GetNewInf
```

因此 Win32 动态构建的显式外部入口是无 C++ 名字修饰的 `GetNewInf`。`GetNewInf` 的签名为 `EXTERN_C PLIB_INFO WINAPI GetNewInf()`，由易语言系统通过固定名称取得 `LIB_INFO`。

### 6.2 命令函数 ABI

`elib/lib2.h` 定义：

```text
typedef void (*PFN_EXECUTE_CMD)(PMDATA_INF pRetData,
                               INT nArgCount,
                               PMDATA_INF pArgInf);
```

`MDATA_INF` 通过 `#pragma pack(1)` 以 1 字节对齐，内部为数据联合体和 `DATA_TYPE m_dtDataType`。联合体既可承载立即数（`m_int`、`m_bool` 等），也可承载文本/字节集/复合对象/数组指针，以及传入变量时的指针形式。`pArgInf` 的实际参数读取遵循生成代码：公开命令按 `pArgInf[1]`、`pArgInf[2]` ……读取。

公共头中的 `COMMOBJ_DEF_CMD` 将每一宏条目展开为：

```text
EXTERN_C void COMMOBJ_NAME(_index, _szEgName)
    (PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf);
```

`COMMOBJ_NAME` 通过 `__E_FNENAME`、英文命令名和数字索引拼接符号，动态/静态构建均使用索引避免不同库之间的命令符号冲突。例如源码中出现 `commobj_GetText_24_commobj`、`commobj_ReplaceTextW_36_commobj`。

### 6.3 系统通知边界

`commobj_ProcessNotifyLib_commobj` 处理的通知包括：

- `NL_SYS_NOTIFY_FUNCTION`：记录系统回调指针并转发给 `elib/fnshare.cpp::ProcessNotifyLib`。
- 非静态构建下的 `NL_GET_CMD_FUNC_NAMES`：返回命令实现函数名数组，并把索引 36 修正为 `ReplaceTextW` 对应的宏函数名。
- 非静态构建下的 `NL_GET_NOTIFY_LIB_FUNC_NAME`：返回 `commobj_ProcessNotifyLib_commobj`。
- 非静态构建下的 `NL_GET_DEPENDENT_LIBS`：返回空的双零结尾字符串 `"\0\0"`。
- `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NR_DELAY_FREE`、`NL_IDE_READY`、`NL_RIGHT_POPUP_MENU_SHOW`、`NL_ADD_NEW_ELEMENT`：当前分支为空操作。
- 未知通知：返回 `NR_ERR`。

`elib/fnshare.cpp::ProcessNotifyLib` 维护 `s_pfnNotifySys`、用户回调 `s_pfnuserNotifySys` 和调试版本值 `s_isDebug`。收到系统通知时取 `NRS_GET_PRG_TYPE`；之后若设置过用户通知函数，继续调用用户回调。

## 7. 当前实现边界与风险

### 已由源码确认

1. `commobj_cmdDef.cpp` 定义 140 个命令函数；106 个函数体完全为空。
2. 其余 34 个函数体只包含 `pArgInf` 局部变量提取语句；没有 `pRetData->...` 写入、没有 `return` 业务值、没有 `m_pCompoundData` 对象状态读写、没有文件 API/文本算法/字节算法调用。
3. 项目内没有 `RapidString`/`RapidBinary` 的 C++ 类或对象存储结构定义；只有 `LIB_DATA_TYPE_INFO` 的声明元数据。
4. `commobj_cmdInfo.cpp`、`commobj_dtType.cpp`、`commobj_dllMain.cpp` 使用全局静态数组建立注册信息，命令函数指针表由 `COMMOBJ_DEF` 宏展开生成。
5. `commobj_const.cpp` 的常量表容量为 1，但 `g_ConstInfo_commobj_global_var_count = 0`。
6. `elib/fnshare.h` 提供 `ealloc`/`efree`、文本/字节集复制、数组布局解析等通用辅助函数，但当前命令入口没有调用它们。

### 尚未验证/不能从当前仓库推出

- Windows SDK、MSVC v141、Visual Studio 17 下四种配置是否均能编译通过。
- `GetNewInf` 在目标 x86/x64 产物中是否能按预期导出并被易语言系统加载。
- `MDATA_INF`、`LIB_INFO` 与目标易语言运行时的实际结构布局和调用约定是否完全匹配；当前只能依据仓库内 `elib/lib2.h` 记录。
- 140 个命令在真实易语言 IDE/运行时中的行为、返回值、错误处理、内存释放、数组布局和对象生命周期。
- `RapidString`/`RapidBinary` 的真正实现是否存在于未提交历史、外部生成源、分支或发布二进制；当前浅克隆和当前工作树均未发现。
- x64 工程配置中缺失 `__E_FNENAME=commobj`、动态库 Link 节缺失 `.def`、静态库 x64 使用未见 `pch.h` 的问题是否会在具体工具链中触发。
- 工程没有测试目录、测试工程、CI 配置或脚本；没有可从仓库复现的自动化验证入口。

## 8. 测试与验证结构

当前仓库只包含 Visual Studio 工程与 C/C++ 头源文件：

- 未发现 `test`、`tests`、`测试` 目录。
- 未发现 CTest、GoogleTest、Catch2、脚本化验收、GitHub/Gitee Actions 或其他 CI 配置。
- 未执行构建或测试，原因是目标项目为 Windows/MSVC 易语言支持库，当前工作环境为 macOS，且本任务明确禁止构建运行。
- 建档阶段已做的只读验证：目标目录核对、Git 分支/提交/远程读取、远程 `HEAD` 对账、项目文件和源码文本盘点、宏命令数量与函数体统计、头文件 ABI/依赖读取。

建议后续在隔离 Windows + Visual Studio 环境中按以下顺序验证，不把建议命令当作本轮已执行事实：

```text
1. 以 VS 解决方案分别检查 Debug/Release、Win32/x64 工程加载和编译诊断
2. 检查 Win32 产物扩展名、PE 导出表中的 GetNewInf
3. 由易语言 IDE 加载支持库，读取 LIB_INFO、两个数据类型和 140 项命令元数据
4. 在真实易语言运行时逐项调用文本/字节集方法，先确认当前骨架会出现的返回值/状态问题
5. 如需恢复功能，实现对象数据生命周期、命令处理、返回值填充和内存释放后再建立行为测试
```

## 9. 后续复核清单

- [ ] 找到并核实上游完整历史或发布包，确认当前“接口骨架”是否为刻意的 SDK 模板、生成中间物或不完整提交。
- [ ] 在 Windows/MSVC 环境核对 x86/x64 预处理器和导出配置，特别是 `__E_FNENAME=commobj`、`Source_commobj.def`、静态库 x64 `pch.h`。
- [ ] 以目标易语言 SDK 头文件核对 `MDATA_INF`/`LIB_INFO` 的 ABI、`PMDATA_INF` 参数索引规则和 `GetBuffer` 指针返回约定。
- [ ] 补充真实对象内部数据结构和生命周期说明；当前源码没有该实现证据，禁止从命令名称反推实现。
- [ ] 为动态库加载、通知分发、命令元数据、对象构造/析构、文本与字节集核心操作建立隔离测试。
- [ ] 对 `ReplaceTextW`/`ReplaceText` 的名称修正、静态命令名数组和命令索引一致性增加专门回归验证。
- [ ] 若后续发现旧 `细探-*.md`，逐条和源码核对后吸收到本文件；本轮未发现旧细探，未执行删除。

## 10. 第三轮：原生对象支持库、运行核心与宿主边界

本轮只做底座映射，不把 `commobj` 的接口声明改造成生产实现。以下结论分为“源码事实”和“底座候选裁决”两类；候选裁决不是本仓库已经存在的代码。另：开工上下文工具曾误绑定到另一个 V3 项目，该结果未作为 `commobj` 证据；本轮证据全部重新来自本项目本地源码静态读取。

### 10.1 先固定两个边界：ABI 骨架不等于对象实现

| 层 | `commobj` 中的真实证据 | 能证明什么 | 不能证明什么 |
|---|---|---|---|
| ABI/注册骨架 | `GetNewInf()`、`LIB_INFO`、`CMD_INFO`、`PFN_EXECUTE_CMD`、`Source_commobj.def`；见 `commobj_dllMain.cpp:26-100`、`elib/lib2.h:1225-1318` | 宿主可以按固定入口发现库、类型、命令、函数表和通知函数 | 不能证明 DLL 能编译、能加载，不能证明任何命令有业务效果 |
| 对象类型元数据 | `commobj_dtType.cpp:1-83` 把 `RapidString`/`RapidBinary` 各映射到 60 个方法槽位 | 两个类型的名称、解释、方法索引和隐藏成员槽位已登记 | 没有 C++ 对象类、字段、缓冲区或实例表；不能推出内部布局 |
| 生命周期契约声明 | `commobj_cmd_typedef.h:33-35,93-95` 给构造、复制构造、析构命令加 `CT_IS_OBJ_*`；`CMD_INFO` 注释规定全零初始化、复制和析构责任 | 易语言运行时会以对象值生命周期语义调用这些槽位 | 当前三个函数体均为空；不能证明构造、深拷贝、释放或异常安全已经实现 |
| 命令入口 | `commobj_cmdDef.cpp` 140 个函数，静态统计 106 个空函数、34 个仅读取 `pArgInf` 局部变量；全体无 `pRetData` 写入、对象状态访问或算法调用 | 生成器已经输出了入口形状 | 不能证明“快速文本/字节集”可读写、查找、替换、文件 I/O 或返回值正确 |
| 宿主消息常量 | `elib/lib2.h:1046-1146` 定义 `NRS_MALLOC`、`NRS_MFREE`、`NRS_FREE_ARY`、`NRS_FREE_COMOBJECT` 等 | SDK 规定了库与运行时交互的消息编号 | `commobj` 当前没有在命令实现中调用这些消息；`NRS_FREE_COMOBJECT` 不是本库已有 COM 实现 |
| COM/引用计数 | 全仓库静态检索不到 `IUnknown`、`QueryInterface`、`AddRef`、`Release`、引用计数字段或 COM 类；只找到 `NRS_FREE_COMOBJECT` 定义 | 仅能确认宿主 SDK 预留了一个 COM 对象释放消息 | 不能把 `CT_IS_OBJ_COPY_CMD` 当成 `AddRef`，也不能把 `CT_IS_OBJ_FREE_CMD` 当成 COM `Release` |

因此，本项目当前应标记为“**支持库 ABI/元数据骨架 + 未完成原生对象实现**”。任何把 140 个命令名、注释或 `RapidString` 名称直接当成可复用算法的做法都属于把声明误当实现。

### 10.2 真实调用链与建议的单链路归属

当前源码能确认的调用链是：

```text
易语言 IDE/运行时
  → LoadLibrary（动态库；当前平台未实测）
  → GetNewInf()                         [ABI 骨架]
  → LIB_INFO：类型表 + CMD_INFO + PFN_EXECUTE_CMD[]
  → NL_SYS_NOTIFY_FUNCTION              [宿主回传 PFN_NOTIFY_SYS]
  → commobj_ProcessNotifyLib_commobj()
  → ProcessNotifyLib()/fnshare.cpp      [只保存全局回调并取调试版本]
  → 构造/复制/普通命令/析构函数槽位      [当前实现为空或只取参]
  → NL_FREE_LIB_DATA / NL_UNLOAD_FROM_IDE
  → DllMain(DLL_PROCESS_DETACH)         [当前为空操作]
```

第三轮的底座单链路候选为：

```text
易语言宿主
  → 原生对象支持库公开 ABI 适配层
      → 运行核心/宿主接口桥（调用约定、位宽、消息、分配/释放、回调注销）
          → 原生对象支持库对象工厂
              → RapidString/RapidBinary 实例与缓冲区
                  →（有明确需求时）COM 适配器/IUnknown 生命周期
          → 运行核心句柄/租约/崩溃清理与证据
  → 统一返回值、宿主错误通知、释放确认
```

归属裁决如下：

| 能力 | 归属 | 理由与边界 |
|---|---|---|
| `LIB_INFO`、`CMD_INFO`、命令/类型索引、`GetNewInf`、`.def` 导出 | 原生对象支持库 | 这是该对象库的公开 ABI 和元数据；运行核心不应复制每个库的命令清单 |
| `RapidString`/`RapidBinary` 的字段、缓冲区策略、文本/字节算法、文件操作 | 原生对象支持库 | 这是领域对象行为；当前源码没有实现，需新建真实实现而不能从名字补齐 |
| `PFN_NOTIFY_SYS` 的接入/替换/注销、调用约定、`MDATA_INF` 安全解码、指针位宽检查 | 运行核心宿主接口层 | 属于所有原生支持库共享的宿主边界；不应由每个对象库各写一套 |
| 宿主内存、数组、复合数据成员释放与跨边界所有权 | 运行核心宿主接口层 + 对象库按契约调用 | 分配器 owner 是宿主；对象库只能通过已登记消息释放，不能跨 DLL 混用 CRT `malloc/free` |
| 通用消息路由、未知消息拒绝、回调生命周期、线程/重入保护 | 运行核心 | `commobj` 的 `ProcessNotifyLib` 只是一份薄壳，不足以承担平台级治理 |
| COM `IUnknown`、接口 IID、`QueryInterface`、`AddRef/Release`、STA/MTA 约束 | 原生对象支持库的 COM 适配边界；公共句柄/崩溃清理由运行核心 | 当前仓库没有这些实现。若未来确有 COM 需求，应显式定义一个 COM 适配器，不把宿主 `NRS_FREE_COMOBJECT` 偷换成普通引用计数 |
| 模块编排、业务流程、项目方别名 | 模块库/项目适配层 | 只能调用支持库公开契约，不能直接摸 `m_pCompoundData`、裸 COM 指针或 `PFN_NOTIFY_SYS` |

**复用/升级/新建/废弃裁决：** ABI 字段和生命周期标志可“吸收”为契约参考；运行核心应“升级”出唯一宿主接口桥；真实 `RapidString/RapidBinary` 应“新建”原生对象支持库实现；COM 能力在没有实现和需求前“待核”，不得先建伪 COM；直接复制生成骨架、每库各自保存宿主回调、用 `DWORD` 传裸指针、让模块直连复合对象布局应“废弃”。

### 10.3 对象、复合数据、消息与所有权契约

`MDATA_INF` 在 `elib/lib2.h:780-824` 以 `#pragma pack(1)` 描述联合数据：立即数、文本/字节集借用指针、`m_pCompoundData` 复合数据指针、`m_pAryData` 数组数据指针，以及变量写入用的 `m_ppText`、`m_ppBin`、`m_ppCompoundData`、`m_ppAryData`。其注释明确说复合数据格式见缺失的 `run.h`，所以当前仓库没有足够证据定义 `RapidString` 或 `RapidBinary` 的存储结构。

| 数据/资源 | 当前源码给出的责任 | 原生支持库实现时的硬契约 |
|---|---|---|
| `pArgInf`、`m_pText`、`m_pBin` | 宿主传入；文本/字节集只可读取 | 视为借用引用，不缓存，不修改，不在对象析构时释放 |
| `m_pCompoundData` | 当前命令可“直接更改成员”，但格式由宿主 `run.h` 规定；修改成员前要先释放该成员 | 只能由 ABI 适配层解码已确认布局；未知布局不得猜读/猜写 |
| `m_ppText`、`m_ppBin` | 写入新值前必须释放旧值，头注释指定宿主释放路径 | 由宿主拥有指针槽；对象库先按宿主契约释放旧值，再交付宿主分配的新值 |
| `m_ppAryData` | 数组变量写入前必须释放原值；注释写 `NRS_FREE_VAR` | 当前 `elib/lib2.h` 只定义了 `NRS_FREE_ARY`，未找到 `NRS_FREE_VAR` 定义；这是必须先向 SDK/目标运行时核对的契约缺口，不能自行猜消息号 |
| `ealloc`/`efree` | `elib/fnshare.h:25-39` 通过 `NotifySys(NRS_MALLOC/MFREE)` 对接宿主 | 统一由运行核心封装并检查回调可用性；跨边界内存禁止用对象库 CRT 释放 |
| 返回文本/字节集 | `CMD_INFO` 只声明 `SDT_TEXT`/`SDT_BIN`，当前函数没有填充 `pRetData` | 成功必须分配宿主可释放的结果并填正确 `m_dtDataType`；失败必须有稳定错误路径，不得留下旧返回值 |
| COM 对象 | 仅有宿主消息 `NRS_FREE_COMOBJECT`（`elib/lib2.h:1141-1143`） | 若未来返回 COM 指针，必须声明“创建引用/借用引用/转移引用/最终释放”四者之一；一次且仅一次调用正确释放路径 |

`CT_IS_OBJ_CONSTURCT_CMD`、`CT_IS_OBJ_COPY_CMD`、`CT_IS_OBJ_FREE_CMD` 是**对象值生命周期回调**：构造时内容全零、复制时目标未初始化、析构时内容可能全零，均来自 `elib/lib2.h:313-334`。它们不是 COM 引用计数接口，也没有并发计数语义。未来原生对象支持库如采用内部共享缓冲区，必须另行实现显式引用计数，并证明“对象值复制”与“COM 接口复制”不会互相释放。

### 10.4 生命周期状态机：当前事实与目标契约

| 阶段 | 当前 `commobj` 行为 | 目标底座验收语义 |
|---|---|---|
| 加载 | `DllMain` 四类分支均为空；全局元数据静态初始化 | 运行核心先建立宿主桥，再发布“可调用”状态；失败不得暴露半初始化函数表 |
| 注册 | `GetNewInf` 返回全局 `LIB_INFO`，每次把索引 36 的英文名改为 `ReplaceText` | 元数据只读发布；名称修正应在构建期或一次性初始化完成，不能让并发调用写全局表 |
| 宿主回调接入 | `NL_SYS_NOTIFY_FUNCTION` 把 `dwParam1` 强转为 `PFN_NOTIFY_SYS` 保存到静态变量 | 校验非空、记录宿主世代/线程约束；重新接入先注销旧回调，卸载前清空，避免悬空回调 |
| 对象构造 | 两个构造入口为空 | 分配对象状态、初始化所有字段；失败时对象必须仍可安全析构，不能返回半初始化对象 |
| 对象复制 | 两个复制构造入口为空 | 目标处于未初始化/全零状态时执行深拷贝或明确共享引用；源全零必须可处理；失败不泄漏、不破坏源 |
| 普通命令 | 106 个空，34 个只取参，无返回写入 | 运行核心先校验参数数量/类型/变量标志，再进入对象库；所有返回槽、借用引用和临时分配均有终态 |
| 缓冲区借用 | `取缓冲区/释放缓冲区` 只有元数据和空函数；说明要求调用者随后释放/回报长度 | 只能有一个活动缓冲区借用；析构、异常、宿主退出时必须收回或阻止二次使用 |
| COM 接口（未来） | 当前没有 COM 对象 | `QueryInterface` 成功增加对应引用；`AddRef/Release` 原子且成对；最终 Release 后句柄失效，不能复活 |
| 正常销毁 | `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`DllMain(DLL_PROCESS_DETACH)` 均未清理对象资源 | 先阻止新调用，再排空活动调用/借用，释放对象和 COM 引用，注销宿主回调，最后卸载 |
| 失败/超时/取消 | 同步 ABI 没有取消协议；当前也没有业务失败返回实现 | 运行核心定义失败为可观察结果；超时/取消只能在不再访问宿主指针后完成；不能用线程强杀替代释放协议 |
| 宿主崩溃/进程终止 | 当前没有本地持久状态或崩溃恢复；`DllMain` 也不承担恢复 | 进程级资源由 OS 回收；跨进程 COM/临时文件/外部句柄由运行核心记录 owner、租约和残留清理证据 |

### 10.5 失败与崩溃矩阵

下表把“源码已出现的危险”与“未来实现必须防的风险”分开，避免把推演写成已发生故障。

| 场景 | 证据/性质 | 可能结果 | 归属与验收 |
|---|---|---|---|
| 返回型命令不写 `pRetData` | 当前 140 个入口统计均无写入 | 宿主看到未初始化/旧返回值；文本/字节集返回还可能被错误释放 | 原生对象支持库必须每条命令填充成功/失败返回；L2 失败用例必须抓住 |
| `nArgCount` 与生成元数据不一致 | 当前入口直接读 `pArgInf[1...]`，没有本地边界检查 | 直接调用或 ABI 漂移时越界读，可能崩溃或读出假值 | 运行核心做最小参数闸门；对象库不能假定所有调用都来自可靠编译器 |
| `ealloc` 在宿主回调未接入时被调用 | `fnshare.h:27-32` 调 `NotifySys` 后立即 `memset(pMem, 0, size)`，无 NULL 检查 | `NRS_MALLOC` 失败时可能对 NULL 写入而崩溃 | 运行核心初始化门禁；先验证 allocator，再允许对象命令执行 |
| 复合数据布局猜错 | `MDATA_INF` 注释把格式外置到 `run.h`，本仓库没有该头 | 错位读写、越界、破坏宿主栈/堆 | L1 必须取得同版本 SDK/运行时布局；没有布局证据就只能待核 |
| x64 指针穿过 `DWORD` | ABI 通知参数普遍是 `DWORD`，包括 COM 释放消息；x64 配置又缺部分名字/导出配置证据 | 高位截断、释放错误地址、随机崩溃 | L1/L4 必须以目标 SDK 的 x64 定义和真实 PE/宿主调用验证；不能把 Win32 经验外推 |
| 回调悬空或并发替换 | `fnshare.cpp:7-9,24-35,60-70` 使用进程级静态回调，无清空/锁/重入状态 | 宿主卸载后回调 UAF，或并发替换导致竞态 | 运行核心拥有回调注册表、世代和注销屏障；不能保留现有静态全局模式作为生产实现 |
| 未知通知/用户回调覆盖错误码 | `ProcessNotifyLib` 默认 `NR_ERR`，随后用户回调返回值覆盖 `nRet` | 错误语义漂移，宿主无法区分“不支持”和“用户处理结果” | 固定消息契约和结果优先级；增加未知消息、重复卸载、重复注册测试 |
| 空的构造/复制/析构 | `commobj_cmdDef.cpp:166-185,671-690` 为空 | 对象槽位可能保留全零/旧数据；实际析构若后来补字段会泄漏或二次释放 | L2 必须先定义对象所有权和全零安全析构，再实现算法 |
| COM 双重释放/漏释放（未来风险） | 当前没有 COM 实现，只有 `NRS_FREE_COMOBJECT` 预留 | 引用归零过早会 UAF，漏 Release 会进程/宿主泄漏 | L3 用真实 COM 对象做 AddRef/Release/QI 并发和最终释放测试；不得用模拟计数替代 |
| 缓冲区借用跨析构（未来风险） | 元数据说明调用者需再调 `释放缓冲区`，当前实现为空 | 借用指针失效后写入，或析构与释放缓冲区竞态 | 对象库登记借用 token；运行核心禁止析构前仍有活动借用 |
| 宿主进程崩溃 | 当前无持久资源账本、无恢复代码 | 进程内内存由 OS 回收，但外部文件/COM/子进程等可能残留 | L4 做强杀/重启/残留审计；不能以“进程退出了”代替资源验证 |

### 10.6 L0-L4 验证等级（防止 ABI 假绿）

这里的 L0-L4 是本轮底座验收分层，不是 `commobj` 已实现的能力等级：

| 等级 | 验收目标 | 当前状态 | 证据等级 |
|---|---|---|---|
| L0 | 静态 ABI：入口、结构、命令索引、类型索引、消息号、函数表数量一致 | 已完成静态盘点：140 命令、2 类型、各 60 槽位、`GetNewInf`/`.def` 存在 | **源码存在；本轮未编译** |
| L1 | 宿主桥：Win32/x64 调用约定、`MDATA_INF` 布局、分配/释放/通知/数组协议、回调注销 | 仅有 SDK 头和薄包装；`run.h`/真实易运行时、x64 导出均未验证 | **部分声明；未实测** |
| L2 | 原生对象：构造、复制、析构、文本/字节缓冲区、返回值、文件和算法行为 | 缺失；函数体无业务实现和对象存储 | **明确未实现** |
| L3 | COM/引用计数/消息重入：QI、AddRef、Release、线程模型、宿主释放和异常路径 | 缺失；仅 `NRS_FREE_COMOBJECT` 常量，未发现 COM 类型或计数器 | **明确未实现/待需求** |
| L4 | 真实宿主与崩溃验收：Windows 编译加载、IDE/运行时调用、故障注入、强杀、重启、残留清理 | 当前 macOS，仓库无测试/CI，任务边界禁止构建运行 | **未验证** |

### 10.7 底座能力命中、缺口与装配计划

| 裁决 | 能力 | 单一落点 | 本轮结论 |
|---|---|---|---|
| 吸收 | `LIB_INFO`/`CMD_INFO`/类型索引/构造复制析构标志的契约模式 | 原生对象支持库公开 ABI 契约 | 可作为契约输入，不复制生成空函数 |
| 吸收并升级 | 宿主消息、allocator、数组/复合数据释放、回调注册 | 运行核心唯一宿主接口桥 | 需要补非空检查、位宽、注销、重入和错误码 |
| 新建 | `RapidString`/`RapidBinary` 的真实对象状态和算法 | 原生对象支持库实现层 | 当前源码没有可迁移实现；必须先定字段/所有权/返回形状 |
| 待核 | COM 对象包装、接口查询、引用计数、线程单元模型 | 原生对象支持库 COM 适配器 + 运行核心句柄/崩溃治理 | 只有收到真实 COM 需求和 SDK 契约后立项 |
| 待核 | `NRS_FREE_VAR` 与 `NRS_FREE_ARY` 的差异 | 运行核心宿主协议 | 当前头文件自相矛盾，先核目标 SDK，不得猜消息号 |
| 废弃 | 每个支持库保存自己的全局 `PFN_NOTIFY_SYS`、直接用 `DWORD` 裸传指针、模块直读 `m_pCompoundData` | 无生产落点 | 会产生回调 UAF、x64 截断和布局耦合 |
| 废弃 | 将注释、命令名、历史二进制或“能返回 `LIB_INFO`”算作功能通过 | 无 | 统一归为 ABI 骨架证据，不得进入真实能力目录 |

装配计划（本轮不执行生产改造）：

```text
波次 0：冻结 ABI 契约
  → 取得同版本 run.h/SDK、确认 x86/x64 结构和消息号
  → 把 ABI 骨架、宿主借用、宿主拥有、转移拥有写成测试契约

波次 1：运行核心宿主桥
  → 唯一回调注册/注销、消息路由、宿主 allocator、数组/复合释放
  → 调用约定/位宽闸门、重入/排空、错误和证据

波次 2：原生对象支持库
  → 真实 RapidString/RapidBinary 状态、构造/复制/析构
  → 命令参数校验、返回值、缓冲区借用和异常清理

波次 3：COM（仅需求确认后）
  → 明确 IID/QI、AddRef/Release、线程单元、借用/转移引用
  → 将 COM 释放与易语言对象析构、NRS_FREE_COMOBJECT 分开验收

波次 4：L4 真实验收
  → Windows/MSVC 编译与导出、真实 IDE/运行时、并发/强杀/重启/残留审计
```

### 10.8 第三轮验收契约

在没有以下证据前，不能宣布“通用对象支持库完成”：

1. **ABI**：Win32/x64 真实构建；`GetNewInf` 的导出和 `LIB_INFO` 布局由目标宿主读取；140 个函数指针与命令索引逐项对账。
2. **对象**：两个类型的构造、全零析构、复制、失败回滚、重复析构；至少覆盖空值、超界位置、超限内存、文件失败和非法参数。
3. **返回/所有权**：所有 `SDT_TEXT`/`SDT_BIN` 返回均使用宿主可释放内存；`pRetData` 类型和值不留旧数据；数组返回与 `CT_RETRUN_ARY_TYPE_DATA` 的释放责任由真实运行时验证。
4. **宿主消息**：回调未接入、回调替换、重复卸载、未知消息、宿主分配失败、数组/复合释放；核实 `NRS_FREE_VAR` 缺口。
5. **COM**：仅在实际有 COM 需求时验收 `QueryInterface`、引用计数并发、最终释放、重复 Release、宿主退出和 STA/MTA；不以 `NRS_FREE_COMOBJECT` 常量存在作为通过。
6. **崩溃/L4**：命令中途异常、宿主回调失效、对象析构期间强杀、COM 服务器退出、进程重启后句柄失效；确认无 UAF、双重释放、未释放外部句柄或临时文件残留。

本轮实际完成的是源码静态归属与验收契约补全，不是上述实现或真实运行验证。

## 11. 结论

`commobj` 的当前可确认架构是“易语言支持库元数据/ABI 壳 + 动态库与静态库双工程”：`COMMOBJ_DEF` 统一产生 140 个命令的声明、函数表和元数据，`LIB_INFO` 通过 `GetNewInf` 暴露给易语言系统，两个自定义对象类型各映射 60 个命令槽位。其核心业务实现目前没有落在命令函数体中，当前首轮建档应将它作为**支持库接口骨架/未完成功能快照**管理，而不是当作已经可运行的文本/字节集对象实现。

第三轮进一步裁决：ABI/类型注册归原生对象支持库；宿主回调、消息、跨边界内存/数组/复合释放、位宽与生命周期治理归运行核心；COM `IUnknown`/引用计数当前没有源码证据，只能作为需求确认后的原生对象适配能力，不能由 `NRS_FREE_COMOBJECT` 或对象析构标志推导出来。
