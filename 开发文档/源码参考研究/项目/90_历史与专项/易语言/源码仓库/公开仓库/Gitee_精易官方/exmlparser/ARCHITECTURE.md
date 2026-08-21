# exmlparser 架构建档

## 1. 项目定位

`exmlparser` 是 Gitee `JYtechnology/exmlparser` 公开仓库中的易语言“XML解析支持库”工程，目标是向易语言暴露一个 `EXMLParser` 自定义数据类型及其方法，用于在内存中创建、导入、查询、修改和导出 W3C XML 树。工程同时提供动态支持库（`.fne`/DLL 工程）和静态库工程。

重要边界：当前仓库只有支持库接口骨架与易语言运行时适配层，XML 解析/序列化业务实现没有落在源码中。`exmlparser_cmdDef.cpp` 中的 40 个导出命令函数均为空函数体，仅完成参数局部变量声明；仓库内也没有 XML 第三方解析器源码、测试或示例。

## 2. 端到端流程

```text
易语言程序/IDE
    │
    ├─ 动态加载 Source_exmlparser.def 导出的 GetNewInf
    │       │
    │       └─ 返回 g_LibInfo_exmlparser_global_var
    │                 ├─ 支持库元数据、版本、GUID
    │                 ├─ g_DataType_exmlparser_global_var：XML树/EXMLParser
    │                 ├─ g_cmdInfo_exmlparser_global_var：命令元数据
    │                 ├─ g_cmdInfo_exmlparser_global_var_fun：命令函数指针
    │                 └─ exmlparser_ProcessNotifyLib_exmlparser：系统通知入口
    │
    ├─ 创建 EXMLParser 数据对象
    │       └─ 数据成员：CreateFlag、pXMLRootNode（意图为内存 XML 根节点状态）
    │
    ├─ 命令调用（宏 EXMLPARSER_DEF 同时生成声明、元数据和函数指针表）
    │       ├─ 创建/导入/释放
    │       ├─ 节点和属性查询
    │       ├─ 节点和属性增删改
    │       ├─ 通配符批量操作
    │       └─ 文本返回值扩展 API
    │
    └─ 当前实际执行结果
            └─ 命令函数体为空，未创建/解析/读写 XML，也未设置返回数据

系统通知链：易语言系统 ──NL_SYS_NOTIFY_FUNCTION──> ProcessNotifyLib
    └─ fnshare.cpp 保存 NotifySys 回调并转发用户回调；NL_FREE_LIB_DATA 等通知目前无资源处理
```

## 3. 版本与仓库基线

| 项目 | 事实 |
|---|---|
| 本地根目录 | `/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/exmlparser` |
| Git 远程 | `https://gitee.com/JYtechnology/exmlparser.git` |
| 分支 | `master`，跟踪 `origin/master` |
| 本地提交 | `bb21b53b097a67259bc75502571d08dd9ca17620` |
| 提交时间 | `2022-12-19T16:55:42+08:00` |
| 远程 `HEAD` | `bb21b53b097a67259bc75502571d08dd9ca17620`，与本地一致 |
| 提交说明 | `初始化仓库` |
| 工作树 | 初始检查时干净；本次仅新增本文件 |
| 旧细探 | 未发现 `细探-*.md` 或其他 `细探*` 文件 |
| 项目说明/协作约束 | 未发现 `README*`、`AGENTS.md`、`CLAUDE.md` |
| 追踪文件 | Git 初始提交统计为 23 个文件、4630 行新增内容 |

源码中的中文字符串按 GB18030/GBK 语境编写；工程 XML 声明为 UTF-8，Visual Studio `CharacterSet` 为 `Unicode`。实际编译和运行时编码转换未在本仓库验证。

## 4. 目录与文件地图

```text
exmlparser/
├── exmlparser.sln                         # VS 解决方案，动态库 + 静态库
├── exmlparser.vcxproj                     # 动态库工程，目标扩展名 Win32 配置为 .fne
├── exmlparser.vcxproj.filters/.user       # VS 筛选器和用户配置
├── Source_exmlparser.def                  # 动态库仅导出 GetNewInf
├── include_exmlparser_header.h            # 统一头文件；注册宏生成的命令声明
├── exmlparser_cmd_typedef.h               # 40 个命令的单一宏定义源
├── exmlparser_cmdInfo.cpp                 # 命令参数元数据和命令元数据数组
├── exmlparser_cmdDef.cpp                  # 40 个命令函数入口；当前均为空实现
├── exmlparser_dtType.cpp                  # EXMLParser 自定义数据类型、方法索引和成员
├── exmlparser_const.cpp                   # 常量表，占位且数量为 0
├── exmlparser_dllMain.cpp                 # DllMain、库信息、GetNewInf、系统通知入口
├── exmlparser_static/
│   ├── exmlparser_static.vcxproj          # 静态库工程，复用上层源码
│   ├── *.filters/.user                    # 静态工程筛选器和用户配置
└── elib/
    ├── lib2.h                             # 易语言支持库 ABI、数据类型、命令宏和结构定义
    ├── fnshare.h/.cpp                     # 内存、通知、数组/字节集适配辅助
    ├── lang.h                             # GBK/语言版本宏，当前编译语言为 GBK
    ├── krnllib.h                          # 系统核心支持库标识与版本常量
    ├── mtypes.h                           # 基础类型兼容定义
    ├── PublicIDEFunctions.h               # 易语言 IDE 公共接口声明
    └── untshare.h                         # 易语言支持库共享定义
```

## 5. 分层与真实调用链

### 5.1 支持库装载层

- `Source_exmlparser.def:1-4` 只导出 `GetNewInf`。
- `exmlparser_dllMain.cpp:31-52` 的 `DllMain` 仅对进程/线程装卸载返回 `TRUE`，没有初始化逻辑。
- `exmlparser_dllMain.cpp:54-102` 构造 `g_cmdInfo_exmlparser_global_var_fun`。`EXMLPARSER_DEF(EXMLPARSER_DEF_CMD_PTR)` 展开为按命令索引排列的函数指针表。
- `exmlparser_dllMain.cpp:57-102` 构造 `LIB_INFO`：库 GUID 为 `BE2297B7415349c8A55BC9DFEB6DD11A`，库名为“XML解析支持库”，版本 `2.2.1`，支持库所需易语言系统版本写为 `3.7`，所需系统核心支持库版本写为 `3.7`，平台标志为 `OS_ALL`。
- `exmlparser_dllMain.cpp:104-108` 的 `GetNewInf()` 返回 `&g_LibInfo_exmlparser_global_var`，是动态装载的主入口。

### 5.2 命令注册层

`exmlparser_cmd_typedef.h:12-52` 的 `EXMLPARSER_DEF(_MAKE)` 是单一事实源。它被多次传入不同宏，分别生成：

1. `include_exmlparser_header.h:22-24` 的 C 函数声明；
2. `exmlparser_cmdInfo.cpp:134-139` 的 `CMD_INFO` 元数据数组；
3. `exmlparser_dllMain.cpp:54-55` 的函数指针数组；
4. `exmlparser_dllMain.cpp:141-143` 的静态编译函数名数组。

`EXMLPARSER_NAME` 通过 `__E_FNENAME=exmlparser` 拼接出类似 `exmlparser_CreateNewTree_0_exmlparser` 的符号名。

### 5.3 系统通知与资源适配层

- `exmlparser_ProcessNotifyLib_exmlparser` 收到 `NL_SYS_NOTIFY_FUNCTION` 时调用 `ProcessNotifyLib`。
- `elib/fnshare.cpp:7-17` 保存系统的 `PFN_NOTIFY_SYS`，`NotifySys` 通过回调转发消息。
- `elib/fnshare.cpp:24-65` 处理 `NL_SYS_NOTIFY_FUNCTION`、`NL_FREE_LIB_DATA`、命令函数名和依赖库通知；除保存系统通知函数、调试版本外，其余分支没有实际资源动作。
- `elib/fnshare.cpp:67-71` 的 `SetUserSysNotify` 保存用户回调，并返回 `ProcessNotifyLib`。
- `elib/fnshare.h:25-39` 的 `ealloc/efree` 通过易语言系统通知申请和释放内存；数组、字节集复制辅助函数也依赖该机制。

### 5.4 命令实现层的现状

`exmlparser_cmdDef.cpp:5-248` 实现旧式布尔 API，`exmlparser_cmdDef.cpp:294-392` 实现文本/整数/字节集返回值 API；每个函数仅读取 `pArgInf` 到局部变量后结束，没有写入 `pRetData` 或引用参数，也没有调用 XML 解析器、文件 API 或 `ealloc/efree`。因此命令元数据是可见的 API 契约草图，不是已实现功能。

## 6. 对外 API 清单

数据类型：`XML树` / `EXMLParser`，方法共 40 个索引（0-39）。

| 索引 | 中文命令 | C 入口后缀 | 返回/用途 |
|---:|---|---|---|
| 0 | 创建 | `CreateNewTree` | `SDT_BOOL`，根节点名 |
| 1 | 导入 | `LoadFrom` | `SDT_BOOL`，文件名或字节集 |
| 2 | 导出到文件 | `WriteToFile` | `SDT_BOOL`，文件/字符集/换行/缩进 |
| 3 | 释放 | `Release` | `_SDT_NULL`，对象释放命令 |
| 4 | 取根节点名 | `GetRootNodeCaption` | `SDT_BOOL`，填充文本变量 |
| 5 | 取子节点数 | `GetChildNodeNumber` | `SDT_BOOL`，填充整数 |
| 6 | 取子节点名 | `GetChildNodeCaption` | `SDT_BOOL`，填充文本数组 |
| 7 | 取节点值 | `GetChildNodeValue` | `SDT_BOOL`，填充文本 |
| 8 | 取二进制值 | `GetBinaryValue` | `SDT_BOOL`，填充字节集 |
| 9 | 取全部属性名 | `GetNodeAttrName` | `SDT_BOOL`，填充文本数组 |
| 10 | 取属性值 | `GetNodeAttrValue` | `SDT_BOOL`，节点路径/属性名/填充文本 |
| 11 | 插入节点 | `InsertNode` | `SDT_BOOL`，父路径/名/值/CDATA |
| 12 | 插入属性 | `InsertAttr` | `SDT_BOOL`，节点路径/属性名/值 |
| 13 | 删除节点 | `DelNode` | `SDT_BOOL`，不允许根节点 |
| 14 | 删除属性 | `DelAttr` | `SDT_BOOL`，属性名可用 `@索引` |
| 15 | 修改节点名 | `ModifyNodeCaption` | `SDT_BOOL` |
| 16 | 修改节点值 | `ModifyNodeValue` | `SDT_BOOL`，支持 CDATA |
| 17 | 修改二进制值 | `ModifyNodeBinaryValue` | `SDT_BOOL` |
| 18 | 修改属性名 | `ModifyNodeAttrCaption` | `SDT_BOOL` |
| 19 | 修改属性值 | `ModifyNodeAttrValue` | `SDT_BOOL` |
| 20 | 批量删除节点 | `BatchDeleteNode` | `SDT_BOOL`，路径支持 `*`、`?` |
| 21 | 批量取节点值 | `BatchGetNodeValue` | `SDT_BOOL`，返回文本数组 |
| 22 | 批量修改节点值 | `BatchModifyNodeValue` | `SDT_BOOL`，支持 CDATA |
| 23 | 匹配通配符 | `BlurMatch` | `SDT_BOOL`，匹配文本/常量文本 |
| 24-29 | 无法识别的名字 | `_bunengshibie_` | `NULL` 说明、0 参数的占位命令；函数体为空 |
| 30 | 取根节点名文本 | `GetRootNodeCaption` | `SDT_TEXT`，可选执行结果变量 |
| 31 | 取子节点个数 | `GetChildNodeNumber` | `SDT_INT`，可选执行结果变量 |
| 32 | 取所有子节点名 | `GetAllChildNodeCaption` | 文本数组返回，带可选执行结果 |
| 33 | 取节点值文本 | `GetChildNodeValue` | `SDT_TEXT`，带可选执行结果 |
| 34 | 取节点值字节集 | `GetBinaryValue` | `SDT_BIN`，带可选执行结果 |
| 35 | 取属性个数 | `GetNodeAttrCount` | `SDT_INT`，带可选执行结果 |
| 36 | 取所有属性名 | `GetNodeAllAttrName` | 文本数组返回，带可选执行结果 |
| 37 | 取属性值文本 | `GetNodeAttrValue` | `SDT_TEXT`，属性名/执行结果 |
| 38 | 取 XML 数据 | `GetXMLData` | `SDT_BIN`，字符集/执行结果/换行/缩进 |
| 39 | 取节点名文本 | `GetNodeCaption` | `SDT_TEXT`，路径/执行结果 |

路径契约来自 `exmlparser_cmdInfo.cpp`：节点路径可以使用名称串 `/` 连接，也可以使用从 1 开始的子节点索引形式 `@1/@2`，两者可混用；批量命令仅在名称路径段支持 `*`、`?`，索引段不支持通配符。属性名也支持 `@1` 形式。上述规则由参数说明声明，但当前命令函数没有执行它们。

## 7. 数据模型与状态

`exmlparser_dtType.cpp:23-37` 注册一个自定义库数据类型：

- 中文名：`XML树`；英文名：`EXMLParser`；平台：`__OS_WIN`。
- 方法索引数组：`0..22`、`30..39`，共 33 个可见方法；索引 `23`（通配符匹配）及 `24..29` 占位命令没有挂到对象方法索引中。
- 成员数组共 2 个：
  - `CreateFlag` / `创建标志`：`SDT_INT`，说明 `1为已经创建 0为没有创建`；
  - `pXMLRootNode` / `XML根节点的指针`：`SDT_INT`，`LES_HIDED` 隐藏成员，意图保存 XML 根节点指针。
- 没有事件、属性或组件交互子程序。

设计意图是每个易语言对象实例拥有一个创建标志和根节点指针，以根节点为入口维护内存树；但仓库未提供节点结构体、属性结构体、分配/释放逻辑和树操作实现，因此这是 ABI 数据模型声明，不是可运行的持久状态实现。

## 8. 输入输出、编码与持久化边界

- 输入：`LoadFrom` 的 `_SDT_ALL` 参数按说明接受文本型文件名或字节集；源码仅把它取为 `pArgInf[1].m_pByte`，未做分支判断。
- 输出：`WriteToFile` 声明文件名、字符集、换行文本、缩进文本；`GetXMLData` 声明同样的格式化参数并返回字节集。参数说明明确“字符集”只写入 XML 声明的 `encoding` 属性，不负责编码转换。
- XML 能力宣称：W3C 标准、支持 BASE64 编码文本和 CDATA，不支持 DTD；支持编码声明 ANSI、GB2312、GB18030。这些内容来自 `exmlparser_dllMain.cpp:75-76` 的库说明，未在实现中验证。
- 持久化：没有数据库、缓存、配置文件或项目内样例 XML。按设计只有内存 XML 树和显式导出文件；当前文件导出同样未实现。
- 内存：易语言数组/字节集布局由 `elib/fnshare.h` 辅助函数处理；当前 XML 命令没有调用这些辅助函数。

## 9. 工程、依赖与构建契约

### 9.1 动态工程

`exmlparser.vcxproj` 为 Visual Studio C++ `DynamicLibrary`，包含 6 个 `.cpp`：`elib/fnshare.cpp`、`exmlparser_cmdDef.cpp`、`exmlparser_const.cpp`、`exmlparser_dllMain.cpp`、`exmlparser_dtType.cpp`、`exmlparser_cmdInfo.cpp`；目标 Win32 Debug/Release 设置 `.fne` 和 `Source_exmlparser.def`，Win32 使用 `v141`、Windows SDK `10.0.15063.0`，x64 配置虽列出但未设置同等的 `TargetExt`/模块定义文件契约。

### 9.2 静态工程

`exmlparser_static/exmlparser_static.vcxproj` 为 `StaticLibrary`，通过 `..\` 复用同一批源码和头文件，Win32 Debug/Release 定义 `__E_STATIC_LIB;__E_FNENAME=exmlparser`。x64 配置列出但只保留通用 `_DEBUG`/`NDEBUG`、`_LIB`，没有 Win32 配置中的 `__E_STATIC_LIB` 和 `__E_FNENAME=exmlparser`，且 Debug/Release x64 使用 `PrecompiledHeader>Use` 但仓库没有 `pch.h` 文件，存在构建不可用风险。

### 9.3 依赖边界

- Windows/Visual C++：`lib2.h` 直接包含 `<windows.h>`、`<stdio.h>`、`<math.h>`；工程是 Windows-only 实现，尽管 `LIB_INFO` 填写 `_LIB_OS(OS_ALL)`。
- 易语言支持库 ABI：`lib2.h`、`fnshare.h`、`PublicIDEFunctions.h`、`krnllib.h`、`untshare.h`、`mtypes.h`。
- XML 第三方依赖：未发现 `tinyxml`、`libxml`、`pugixml`、`rapidxml` 或同类 include/源码/库链接配置。
- `LIB_INFO.m_szDependFiles` 为 `NULL`；系统通知 `NL_GET_DEPENDENT_LIBS` 返回空列表 `"\0\0"`。
- 版本疑点：`exmlparser_dllMain.cpp` 的 `LIB_INFO` 声明所需核心库为 `3.7`，但 `elib/krnllib.h` 内部标识为 `LI_KRNL_LIB_MAJOR_VER=4`、`LI_KRNL_LIB_MINOR_VER=5`；需结合目标易语言 SDK 复核，不应直接视为一致契约。

## 10. 测试与验证

仓库未发现测试工程、测试源码、CI 配置、样例程序或 README。未执行构建：当前环境为 macOS，工程依赖 Windows SDK、`windows.h`、Visual Studio `v141` 和易语言支持库 ABI，不能据此宣称可编译或可运行。

已做的只读核验：

- 读取解决方案、动态/静态工程 XML、DEF、所有核心 `.cpp/.h`；
- 核对命令宏、函数入口、参数元数据、数据类型注册和通知链；
- 核对本地 `HEAD` 与远程 `origin/master`，两者均为 `bb21b53b097a67259bc75502571d08dd9ca17620`；
- 检查根目录未发现旧 `细探` 文档；
- 未安装依赖、未构建、未启动服务、未修改源码/配置、未提交 Git。

## 11. 未确认项、风险与后续复核点

1. **核心功能缺失（高）**：40 个命令函数体为空，没有 XML 节点实现；需要确认该仓库是否仅为自动生成接口模板，或源码在其他历史仓库/分支。
2. **编码契约未验证（中）**：源文件含 GB18030 中文文本，工程标记 Unicode；需在 Windows + 目标易语言 SDK 下核验编译器对源码和运行时字符串的处理。
3. **构建矩阵不完整（高）**：x64 配置缺少关键预处理宏/DEF 配置，静态 x64 还引用未提供的预编译头；需在原始开发环境复核。
4. **ABI 版本矛盾（中）**：`LIB_INFO` 所需系统核心库版本 `3.7` 与 `krnllib.h` 声明 `4.5` 不一致，需确认是兼容下限、历史模板残留还是错误。
5. **平台标识矛盾（中）**：库元数据标记 `OS_ALL`，自定义数据类型和命令却均为 `__OS_WIN`，实际应按 Windows 支持库处理。
6. **声明与行为不能等同（高）**：W3C、BASE64、CDATA、编码、DTD 限制、路径通配符等目前只有元数据/说明证据，不能作为已实现能力。
7. **静态/动态行为差异待核对**：宏在 `__E_STATIC_LIB` 下会改变符号名和函数表，但没有实际构建产物验证。
8. **全局对象状态待核对**：数据类型成员描述了实例状态，但 `exmlparser_cmdDef.cpp` 只使用 `pArgInf`，没有展示如何取/写 `m_pCompoundData`。

本文件为项目根唯一架构事实源；后续深挖应直接增量更新本文件，不另建平行架构报告。

## 12. 关键证据索引

- `exmlparser_dllMain.cpp:31-180`：DLL 入口、`LIB_INFO`、`GetNewInf`、系统通知。
- `Source_exmlparser.def:1-4`：动态导出边界。
- `include_exmlparser_header.h:1-26`：核心包含关系与命令声明宏。
- `exmlparser_cmd_typedef.h:5-52`：命令命名宏和 0-39 命令注册源。
- `exmlparser_cmdInfo.cpp:5-142`：参数说明、类型、默认值和引用/数组标志。
- `exmlparser_cmdDef.cpp:1-395`：命令入口；函数体为空的直接证据。
- `exmlparser_dtType.cpp:1-39`：`EXMLParser` 数据类型、方法索引和两个成员。
- `elib/fnshare.cpp:1-71`、`elib/fnshare.h:20-170`：通知、内存、数组和字节集适配。
- `exmlparser.vcxproj:21-202`：动态工程、Win32/x64 配置和链接契约。
- `exmlparser_static/exmlparser_static.vcxproj:21-167`：静态工程与预处理宏。
- `exmlparser.sln:1-40`：解决方案项目和平台映射。
- Git 基线：`bb21b53b097a67259bc75502571d08dd9ca17620`，远程 `https://gitee.com/JYtechnology/exmlparser.git`。
