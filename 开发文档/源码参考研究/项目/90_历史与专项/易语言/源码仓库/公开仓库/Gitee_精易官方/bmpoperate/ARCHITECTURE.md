# bmpoperate 架构归档

## 1. 项目定位

`bmpoperate` 是 Gitee `JYtechnology/bmpoperate` 仓库中的易语言 Windows 支持库源码，库中文名为“位图操作支持库”。目标是向易语言暴露一个名为 `DIB`、中文名为“位图”的自定义数据类型，用于读写标准 BMP 文件/字节集、访问像素和颜色表、创建与变换位图，以及和 Windows GDI 位图句柄交互。

当前仓库是一个支持库工程骨架：命令元数据、易语言 ABI/通知转接、动态库导出和静态库工程已经搭好，但 `bmpoperate_cmdDef.cpp` 中的 35 个命令实现函数只有参数取值或空函数体，没有看到实际 BMP 解析、编码、像素操作、GDI 操作或错误状态写入逻辑。因此不能把它描述为已经实现的位图库。

## 2. 真实流程图

```text
易语言 IDE/编译器
    │  加载 Windows .fne 动态库，或链接 bmpoperate_static 静态库
    ▼
GetNewInf()
    │  返回 g_LibInfo_bmpoperate_global_var
    │  提供库版本、GUID、系统要求、命令表、函数指针表、自定义数据类型表
    ▼
易语言支持库运行时
    │  按 g_cmdInfo_bmpoperate_global_var / g_cmdInfo_bmpoperate_global_var_fun 分发
    ▼
命令入口 bmpoperate_<英文名>_<索引>_bmpoperate(...)
    │  当前仅从 PMDATA_INF pArgInf 取部分参数；绝大多数入口未写 pRetData
    ▼
预期的 DIB 状态与 BMP/GDI 操作
    │  当前源码未实现
    ▼
结果/错误信息返回给易语言调用方

系统通知链：
易语言运行时 ──NL_SYS_NOTIFY_FUNCTION──> bmpoperate_ProcessNotifyLib_bmpoperate
    └─> ProcessNotifyLib() ──> fnshare.cpp 中的 NotifySys/用户通知回调
```

## 3. 目录与文件地图

| 路径 | 真实职责 |
|---|---|
| `bmpoperate.sln` | Visual Studio 解决方案，包含动态库和静态库两个项目，配置 Debug/Release 与 Win32/x64。 |
| `bmpoperate.vcxproj` | Windows 动态库工程；编译 `elib/fnshare.cpp`、命令实现、元数据、DLL 入口等文件，目标扩展名 Win32 配置为 `.fne`。 |
| `bmpoperate_static/bmpoperate_static.vcxproj` | 静态库工程；复用上级目录同一批源文件，定义 `__E_STATIC_LIB` 和 `__E_FNENAME=bmpoperate`。 |
| `bmpoperate_cmd_typedef.h` | `BMPOPERATE_DEF` 单一命令清单；生成声明、命令元数据、函数指针表、静态编译函数名。 |
| `bmpoperate_cmdDef.cpp` | 35 个命令入口的当前实现位置；现在是生成式空实现/参数提取骨架。 |
| `bmpoperate_cmdInfo.cpp` | `ARG_INFO` 参数表和 `CMD_INFO` 命令描述表。 |
| `bmpoperate_dtType.cpp` | `DIB` 数据类型的命令索引表、隐藏成员表和 `LIB_DATA_TYPE_INFO`。 |
| `bmpoperate_dllMain.cpp` | `DllMain`、`LIB_INFO`、`GetNewInf`、动态库函数指针/函数名表及系统通知处理。 |
| `bmpoperate_const.cpp` | 当前无预定义常量，常量表计数为 0。 |
| `include_bmpoperate_header.h` | 统一引入易语言运行时头文件，并根据 `BMPOPERATE_DEF` 展开命令声明。 |
| `Source_bmpoperate.def` | DLL 导出定义，仅导出 `GetNewInf`。 |
| `elib/` | 易语言支持库 SDK/运行时适配头与通知转接实现；不是本项目独立业务模块。 |

仓库没有 `README.md`、没有 `ARCHITECTURE.md`（本文件为本次唯一新增文档）、没有测试目录、没有示例程序、没有构建脚本之外的 CLI 入口。

## 4. 核心数据模型与 BMP 领域边界

### 4.1 易语言侧数据类型

`bmpoperate_dtType.cpp` 注册一个自定义数据类型：

- 中文名：`位图`；英文名：`DIB`。
- 说明明确限定为标准 BMP 文件格式数据，各种压缩格式暂不支持；16 位 BMP 仅支持 `BI_RGB`。
- 方法索引数组覆盖命令索引 `0` 至 `34`，运行时通过索引将 DIB 方法映射到命令表。
- 隐藏成员为 `this`（`SDT_INT`）和 `错误信息(STL 的 string)`（`SDT_INT`）。源码没有进一步给出成员布局、对象分配、字符串生命周期或错误信息写入实现。

### 4.2 计划中的 BMP 状态

从命令契约可以确认设计上需要维护：文件头/信息头、宽高、位深度、颜色表、像素点阵、水平/垂直分辨率、映射文件句柄及错误文本；颜色表用于位深度小于 16 的位图，16 位及以上不使用颜色表。`LoadBmpFile`/`LoadBin`、`GetBmFileBin`、`GetBits`/`SetBits` 和 `MapFile` 共同构成文件或内存数据边界；`GetPixelColor`/`SetPixelColor` 及索引版本构成像素访问边界。

这些是元数据和注释声明的目标模型，不是已经存在的可运行模型：实现文件没有实际字段、解析器、缓冲区、资源释放或结果写回代码。

## 5. 命令/API 边界

### 5.1 DIB 对象方法

`BMPOPERATE_DEF` 共声明 35 项：

| 索引 | 中文名 | 源码英文名 | 返回/参数摘要 |
|---:|---|---|---|
| 0 | 构造函数 | `Constructor` | 隐藏对象构造 |
| 1 | 析构函数 | `Desstructor` | 隐藏对象析构 |
| 2 | 复制构造函数 | `CopyConstructor` | 一个 DIB 源对象 |
| 3 | 取错误信息 | `GetErrorText` | 文本 |
| 4 | 载入文件 | `LoadBmpFile` | 文件名；逻辑型 |
| 5 | 载入数据 | `LoadBin` | BMP 字节集；逻辑型 |
| 6 | 取位图数据 | `GetBmFileBin` | BMP 字节集 |
| 7 | 取宽度 | `GetWidth` | 整数型 |
| 8 | 取高度 | `GetWidth` | 元数据英文名重复为 `GetWidth`，实现符号也是 `bmpoperate_GetWidth_8_bmpoperate` |
| 9 | 取位深度 | `GetBitCount` | 短整数型 |
| 10 | 创建 | `Create` | 宽、高、位深度、可选初始颜色；逻辑型 |
| 11 | 取颜色表 | `GetColorTable` | 整数数组 |
| 12 | 取像素点阵 | `GetBits` | 字节集 |
| 13 | 取某点颜色 | `GetPixelColor` | 横坐标、纵坐标；整数型 |
| 14 | 取某点颜色索引 | `GetPixelColorIndex` | 横坐标、纵坐标；整数型 |
| 15 | 是否使用颜色表 | `IsHasColorTable` | 逻辑型 |
| 16 | 是否为空 | `IsEmpty` | 逻辑型 |
| 17 | 置某点颜色 | `SetPixelColor` | 坐标、颜色；逻辑型 |
| 18 | 置某点颜色索引 | `SetPixelColorIndex` | 坐标、索引；逻辑型 |
| 19 | 置颜色表 | `SetColorTable` | 整数数组；逻辑型 |
| 20 | 置像素点阵 | `SetBits` | 字节集；逻辑型 |
| 21 | 转换位深度 | `SetBitCount` | 目标位深度；返回 DIB |
| 22 | 复制到 | `CopyTo` | 源矩形、目标对象/位置、可选透明色；逻辑型 |
| 23 | 取指针 | `GetPointers` | 两个引用参数，返回内部信息头/像素指针 |
| 24 | 旋转90度 | `Rotate90` | 是否顺时针；返回 DIB |
| 25 | 镜像 | `Mirror` | 水平/垂直；返回 DIB |
| 26 | 创建兼容位图 | `CreateCompitableBitmap` | 可选窗口句柄；返回 `HBITMAP` 整数 |
| 27 | 从句柄创建 | `FromHandle` | `HBITMAP`；逻辑型 |
| 28 | 旋转 | `Rotate` | 角度、背景色；返回 DIB |
| 29 | 取横向分辨率 | `GetHorzResolution` | 整数型，单位像素/米 |
| 30 | 取纵向分辨率 | `GetVertResolution` | 整数型，单位像素/米 |
| 31 | 置横向分辨率 | `GetHorzResolution` | 分辨率；逻辑型，英文名与 getter 重复 |
| 32 | 置纵向分辨率 | `GetVertResolution` | 分辨率；逻辑型，英文名与 getter 重复 |
| 33 | 映射文件 | `MapFile` | 文件名、DC 句柄；逻辑型 |
| 34 | 位图_转换位深度 | `Bitmap_ConvertBitCount` | DC 句柄、原始 BMP 字节集、目标位深度；字节集 |

### 5.2 全局导出与通知协议

- DLL 的公开导出由 `Source_bmpoperate.def` 限定为 `GetNewInf`。
- `GetNewInf()` 返回 `PLIB_INFO`，其 `m_szGuid` 为 `42305932-06E6-47a5-AC79-8BDCDC58DF61`，版本为 `2.0.0`，要求易语言系统 `3.8`、系统核心支持库 `3.7`，平台标志为 Windows。
- `bmpoperate_ProcessNotifyLib_bmpoperate` 处理 `NL_GET_CMD_FUNC_NAMES`、`NL_GET_NOTIFY_LIB_FUNC_NAME`、`NL_GET_DEPENDENT_LIBS`、`NL_SYS_NOTIFY_FUNCTION`、`NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE` 等通知。
- `NL_SYS_NOTIFY_FUNCTION` 会转发到 `elib/fnshare.cpp::ProcessNotifyLib`，后者保存系统通知回调、检测调试/编译版本，并可调用用户通知回调。
- `NL_GET_DEPENDENT_LIBS` 返回空依赖列表；源码未声明额外第三方静态库。

项目没有 HTTP API、RPC、命令行程序、脚本入口或独立 SDK；公开接口就是易语言支持库 ABI、DIB 方法表和 `GetNewInf`。

## 6. 真实调用链与资源边界

### 6.1 动态库装载

```text
LoadLibrary(.fne)
  → GetNewInf
  → g_LibInfo_bmpoperate_global_var
  → g_DataType_bmpoperate_global_var / g_cmdInfo_bmpoperate_global_var
  → g_cmdInfo_bmpoperate_global_var_fun
  → 对应 bmpoperate_* 命令入口
```

`g_cmdInfo_bmpoperate_global_var_fun` 由同一份 `BMPOPERATE_DEF` 生成，保证命令元数据和函数指针按索引排列；静态编译还通过 `g_cmdNamesbmpoperate` 返回完整函数名数组。

### 6.2 参数与结果

命令入口统一签名为 `void(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)`。当前代码只展示参数读取，例如 `pArgInf[n].m_int`、`m_short`、`m_bool`、`m_float`、`m_pBin`、`m_pText`、`m_pCompoundData`、`m_pAryData` 和 `m_pInt`；没有实际设置 `pRetData`，也没有可确认的对象状态转换。

`elib/fnshare.h` 提供 `ealloc`/`efree`、`CloneBinData`、`GetBinData`、`GetAryElementInf` 等易语言内存/数组辅助函数，但 `bmpoperate_cmdDef.cpp` 当前没有把这些辅助函数接入 BMP 业务逻辑。`elib/untshare.h` 主要提供 Windows/资源辅助代码，当前命令实现没有显示调用它。

### 6.3 资源与生命周期

设计注释要求映射文件保持打开并占有至对象销毁；兼容位图返回的 `HBITMAP` 要由调用者通过 Windows `DeleteObject` 释放。当前实现没有建立映射句柄、DIB 缓冲区、GDI 句柄的所有权字段，也没有析构/释放逻辑，因此资源生命周期尚未闭环。`DllMain` 的四种 DLL 生命周期分支当前均为空。

## 7. 技术栈与依赖边界

- 语言：C++，以 Visual Studio 工程为目标。
- 平台：Windows；`elib/lib2.h` 直接包含 `windows.h`，库/命令/数据类型状态均设置 Windows 标志。
- 构建：Visual Studio 解决方案，动态库目标；静态库项目复用同一源码。
- 工具集：项目文件声明 `PlatformToolset=v141`，Windows SDK 目标 `10.0.15063.0`。
- 运行时：易语言支持库 ABI（`LIB_INFO`、`CMD_INFO`、`ARG_INFO`、`LIB_DATA_TYPE_INFO`、`PMDATA_INF`）和 `NotifySys` 通知机制。
- 外部依赖：未发现第三方包管理配置；`NL_GET_DEPENDENT_LIBS` 明确返回空依赖。Windows 系统 API/GDI 是平台依赖。
- 编码：元数据是中文 GBK/易语言生态文本；部分当前终端按 UTF-8 读取会出现乱码，应以源码字节和原文件编码为准。

## 8. 构建、测试与验证现状

### 已确认

- 解决方案包含 `bmpoperate` 动态库与 `bmpoperate_static` 静态库。
- `BMPOPERATE_DEF` 展开得到 35 个命令；参数表索引覆盖到 42，`g_cmdInfo..._count` 和 `g_DataType..._count` 由数组大小计算。
- 本地提交为 `fd2dff40176f7dcdb858796ff2a9727a6abdf595`，提交时间 `2022-12-19T16:52:23+08:00`，工作树在建档前干净。
- `origin` 为 `https://gitee.com/JYtechnology/bmpoperate.git`；`git ls-remote origin HEAD` 与本地 `HEAD` 同为 `fd2dff40176f7dcdb858796ff2a9727a6abdf595`，因此没有远程落后需要通过 `127.0.0.1:4780` 建独立快照的情况。
- 远程与本地都没有 `README.md` 或既有 `ARCHITECTURE.md`。

### 未执行/无法执行

- 仓库没有测试文件或测试入口，不能报告功能测试通过。
- 未执行 Windows Visual Studio 构建：当前执行环境为 macOS ARM64，现场未发现 `msbuild` 或 `cl`，而项目直接依赖 `windows.h`、Windows ABI 与 v141 工具集；仅有 `/usr/bin/xcodebuild` 不能替代该构建链。
- 未安装依赖、未启动服务、未生成 DLL/静态库、未运行易语言 IDE；符合源码参考库只读边界。

## 9. 风险、未确认项与后续复核点

### 阻断性事实

1. `bmpoperate_cmdDef.cpp` 的 35 个命令没有业务实现：没有 BMP 文件头解析、位深度转换、像素读写、旋转/镜像、颜色表处理、GDI 句柄转换、错误文本维护或 `pRetData` 写回。当前源码不能作为可运行 BMP 操作实现交付。
2. 没有测试夹具、测试代码或 Windows 构建结果，命令契约与 ABI 只能由静态源码确认，运行时行为未证实。

### 重要风险

1. 元数据索引 8“取高度”的英文名为 `GetWidth`，对应实现符号也为 `bmpoperate_GetWidth_8_bmpoperate`；索引 31/32 的分辨率 setter 也复用了 getter 英文名。这可能造成静态编译命名冲突、调用映射错误或文档显示错误，需在真实易语言 SDK/生成器规则下复核。
2. `Bitmap_ConvertBitCount` 的注释将第一个参数描述为 DC 句柄，但实现骨架读取 `pArgInf[0].m_int`，而其他普通参数从 `pArgInf[1]` 开始；参数基址约定需结合易语言运行时真实调用验证。
3. `CopyTo` 的元数据声明有 8 个参数且包含多个可选参数；实现仅提取参数，没有默认值归一化、矩形边界检查或重叠复制语义。
4. `m_pCompoundData`、数组、字节集和指针参数的所有权/长度/边界未在本项目中定义；尤其 `GetPointers` 暴露内部指针，后续实现必须明确失效时机和线程安全。
5. `MapFile` 的文件句柄/映射视图释放、`CreateCompitableBitmap` 返回 `HBITMAP` 的调用者责任，以及 DIB 析构顺序都未实现。
6. 文件说明宣称压缩 BMP 不支持、16 位仅支持 `BI_RGB`，但没有解析器或校验代码证明这些限制已经执行。

### 后续复核顺序

1. 先固定 `PMDATA_INF` 的对象成员布局、数组/字节集 ABI、返回值写入和错误文本分配规则。
2. 再补 DIB 内部模型与统一资源释放路径，覆盖文件载入、字节集载入、创建、析构、映射文件和 GDI 句柄。
3. 为每个命令建立 Windows 测试夹具：至少覆盖 1/4/8/16/24/32 位 BMP、top-down 高度、颜色表、越界坐标、非法数据、旋转/镜像、映射文件和句柄释放。
4. 修正或确认命令索引 8、31、32、34 的英文名/参数索引后，再生成动态库和静态库并在易语言实际运行时验证命令表一致性。
5. 对 `GetPointers`、透明色复制和 `MapFile` 增加资源泄漏、失效指针和异常路径测试。

## 10. 后续：图像支持库、运行核心与统一网关的底座映射

> 本节是后续底座映射和装配输入，不是对当前仓库实现程度的改写。当前项目上下文工具错绑到了 `/Users/hekunhua/Documents/Agent/PHP/华世王镞_v3`，其代码图和验证结果已丢弃；以下结论只使用本目录源码的静态证据，属于弱验证。源码事实仍以第 1～9 节为准。

### 10.1 边界总裁决：什么归谁

本项目的真实公开边界只有易语言支持库 ABI：`Source_bmpoperate.def` 仅导出 `GetNewInf`；`bmpoperate_dllMain.cpp:31-86` 组装 `LIB_INFO`，`bmpoperate_dllMain.cpp:101-178` 处理支持库通知；`bmpoperate_cmd_typedef.h:12-47` 和 `bmpoperate_cmdDef.cpp:6-315` 定义 35 个 DIB 命令入口。因此不能把“支持库命令入口”“Windows/GDI 句柄”“易语言内存格式”混成一个业务层。

| 边界 | 应归属 | 本项目证据/映射 | 明确不归属 |
|---|---|---|---|
| BMP/DIB 语义、文件头/信息头、stride、颜色表、像素、位深度转换、旋转/镜像、分辨率 | **图像支持库** | `bmpoperate_dtType.cpp:23-37` 注册 `DIB`；命令清单覆盖 `LoadBin`、`GetBits`、像素、颜色表和变换 | 运行核心不解释 BMP 字节；统一网关不实现像素算法 |
| DIB 对象状态、错误文本、替换提交、复制构造/析构、图像资源所有权 | **图像支持库** | 隐藏成员在 `bmpoperate_dtType.cpp:15-21`；构造/析构/复制入口当前为空（`bmpoperate_cmdDef.cpp:6-26`） | 网关不保存 DIB 内部指针；运行核心不拥有图像业务状态 |
| `PMDATA_INF`、参数/返回值 ABI、易语言数组/字节集/文本格式、`pRetData` 写回 | **运行核心适配层** | `elib/lib2.h:780-824,1234-1239`；入口统一为 `PFN_EXECUTE_CMD` | 图像库不得伪造另一套 ABI；网关不得直接读 `m_pCompoundData` |
| 易语言分配器、返回值旧内存释放、通用数组/字节集复制 | **运行核心**（图像库调用其公开适配函数） | `elib/fnshare.h:25-39,58-85,107-140,160-169`；`ealloc/efree` 经 `NRS_MALLOC/NRS_MFREE` | 不把 `efree`/`MFree` 规则复制到网关或第三方 provider |
| `HBITMAP`、`HDC`、`HWND` 等外部句柄的借用/转移/释放登记 | **运行核心的通用句柄租约 + 图像支持库的类型策略** | 命令元数据以 `SDT_INT` 传句柄（`bmpoperate_cmdInfo.cpp:68-82`）；`CreateCompitableBitmap` 明确要求调用者 `DeleteObject`（`bmpoperate_cmd_typedef.h:39`） | 网关不把裸整数当永久资源；外部库不决定易语言对象生命周期 |
| 文件打开、文件映射、映射视图和路径编码 | **图像支持库**负责一次调用内的文件语义；**运行核心**负责通用句柄/异常清理 | `MapFile` 契约声称文件占有至 DIB 销毁（`bmpoperate_cmd_typedef.h:46`），但当前没有字段和实现 | 网关不直接 `CreateFile`/`MapViewOfFile`；不把路径或 FILE/MAP 句柄泄漏给调用方 |
| Windows GDI、`kernel32/user32/gdi32` 和系统支持库调用 | **受管外部 provider/平台适配**，经图像支持库唯一组合点调用 | `elib/lib2.h:989-991,1137-1139` 定义通用位图通知；`bmpoperate_dllMain.cpp:120-123` 依赖列表为空，常用系统库按 SDK 规则省略 | 不能从网关、业务模块或多个 provider 旁路直连 GDI |
| 公开能力 id、版本、权限、超时、取消、观测、统一错误和资源证据 | **统一网关** | 本项目没有 HTTP/RPC 网关；`GetNewInf`/通知仅是旧 ABI 入口，需由适配器接入规范能力 | 网关不复制 DIB 算法、错误解析、句柄释放或第二套 fallback |

结论：`bmpoperate` 适合作为“图像支持库 provider/适配器”的源码参考，不适合作为运行核心或统一网关的实现模板。图像支持库只能通过运行核心公开的 ABI、内存和句柄契约交换数据；统一网关只编排能力和生命周期证据。任何未来实现都必须避免“网关 → GDI”“模块 → `m_pBin`/`m_pCompoundData`”这类侧链。

### 10.2 现有能力命中、缺口与复用裁决

| 能力系列 | 现有源码命中 | 缺口/真实性 | 后续裁决 |
|---|---|---|---|
| DIB 类型与 35 个命令注册 | `bmpoperate_dtType.cpp:5-37`、`bmpoperate_cmd_typedef.h:12-47`、`bmpoperate_cmdInfo.cpp:91-101` | 元数据和函数表存在，但命令体没有状态、结果或错误写回 | **复用适配层，升级图像支持库**；不把注册表当能力已实现 |
| BMP 文件/字节集输入输出 | `LoadBmpFile`、`LoadBin`、`GetBmFileBin` 的声明和 `m_pText/m_pBin` 取参（`bmpoperate_cmdDef.cpp:35-56`） | 无解析、长度校验、编码处理、返回字节集和失败回滚 | **新建图像解析/编码原子能力**；旧命令只做兼容映射，待 Windows 验证 |
| 像素、颜色表、点阵 | 命令契约和参数表（`bmpoperate_cmd_typedef.h:24-33`、`bmpoperate_cmdInfo.cpp:31-49`） | 无 stride/边界/位深度实现；不支持范围也未由代码执行 | **升级图像支持库**；运行核心只提供安全 buffer 访问，不承载格式算法 |
| 旋转、镜像、复制、位深度转换 | `bmpoperate_cmdDef.cpp:181-263` 只取参数；索引 34 还从 `pArgInf[0]` 取 DC（`bmpoperate_cmdDef.cpp:305-315`） | 无算法、默认值归一化、重叠复制策略、异常边界；原始数据非法可崩溃（`bmpoperate_cmdInfo.cpp:80-82`） | **隔离/升级图像支持库**；原生或不可信输入优先进程隔离，禁止网关复刻算法 |
| GDI `HBITMAP`/DC 对接 | `CreateCompitableBitmap`、`FromHandle`、`MapFile` 元数据（`bmpoperate_cmdDef.cpp:239-303`） | 无 `CreateCompatibleBitmap`、拷贝/归属判定、`DeleteObject` 或 DC 校验 | **建立通用句柄租约能力，图像库实现类型适配**；裸句柄入口标记待核，不直接吸收为安全能力 |
| 文件映射 | `MapFile` 契约声明“占有直到对象销毁”（`bmpoperate_cmd_typedef.h:46`） | DIB 隐藏成员只有声明性 `this`/错误信息，没有文件句柄、映射句柄或视图字段 | **新建资源生命周期能力后再升级图像库**；不能以注释作为已实现证据 |
| 易语言 ABI/通知/分配 | `elib/lib2.h`、`elib/fnshare.h`；`GetNewInf` 和通知分发存在 | 属于 SDK 适配骨架；`NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`DllMain` 分支为空（`bmpoperate_dllMain.cpp:7-24,134-153`） | **复用运行核心公共适配层**；不复制 `elib` 为网关私有实现 |
| 外部库依赖登记 | `NL_GET_DEPENDENT_LIBS` 返回 `"\0\0"`（`bmpoperate_dllMain.cpp:117-123`） | 只证明未声明额外静态支持库，不证明没有 Windows/GDI 运行依赖 | **保留平台 provider 边界，待构建/装载验证**；不虚报“零外部依赖” |

本表中的“复用/升级/新建/隔离”是装配动作，不是当前实现状态；当前仓库没有可称为 L2 以上的能力证据。

### 10.3 单链路落点与网关禁止事项

```text
易语言旧 DIB 方法/统一网关图像能力 id
  → 唯一图像适配器（参数/版本/权限/超时/句柄租约归一化）
  → 运行核心能力注册表与唯一调用器
  → 图像支持库 DIB 服务（解析、像素、变换、错误、资源事务）
  → 受管 Windows/GDI provider 或隔离的图像 worker
  → BMP 字节/文件、HBITMAP/HDC 等外部资源
  → 统一结果、错误码、资源释放回执和审计证据
```

- 图像支持库是 BMP/DIB 领域契约 owner：输入只接受带长度的受控字节、只读路径快照或显式句柄租约；不接受网关直接塞入未经校验的裸地址。
- 运行核心是 ABI/内存/句柄/宿主生命周期 owner：负责把 `PMDATA_INF` 转成内部类型、管理返回 `SDT_TEXT/SDT_BIN` 的所有权、登记可清理资源、把取消/超时/崩溃转成统一终态；不决定颜色表或旋转结果。
- 统一网关是策略和观测 owner：做能力 id、版本、输入大小、权限、deadline、幂等/请求 id、统一错误和证据关联；不直接调用 Windows API，不读取 DIB 隐藏成员，不返回未登记的 `HBITMAP` 裸整数。
- 外部 provider 只在图像支持库的唯一组合点出现。`gdi32/user32/kernel32` 这类系统库由构建/运行环境提供；第三方图像库若未来引入，必须在 provider manifest 中声明 ABI、位数、许可证、线程模型和释放函数，不能借 `NL_GET_DEPENDENT_LIBS` 为空而隐藏依赖。
- 旧 `GetNewInf`/命令索引只保留为兼容适配入口；不得为旧英文名冲突（索引 8、31、32）再生成第二套命令表。统一能力 id 应在唯一适配器归一化后进入运行核心。

### 10.4 资源、所有权与释放契约（当前实现 vs 验收要求）

| 资源 | 创建/借用 | 持有与转移 | 正常释放 | 失败/取消/超时 | 宿主崩溃与当前证据 |
|---|---|---|---|---|---|
| DIB 内部状态与像素 buffer | `Create`/`LoadBin`/`FromHandle` 预期创建；输入字节来自 `m_pBin`，按 `elib/lib2.h:793-799` 视为借用 | 图像支持库独占；替换应先构造临时对象，提交成功后再释放旧状态；`GetPointers` 只能借用 | DIB 析构、显式替换和失败回滚统一走 idempotent `release` | 非法头、溢出、分配失败不得半提交；超时需回收临时 buffer | 析构入口为空（`bmpoperate_cmdDef.cpp:14-17`），崩溃无法依赖 DLL 清理；需 worker/OS 回收并做现场验证 |
| 易语言文本/字节集/数组 | 返回值由图像库生成，适配层用 `CloneTextData/CloneBinData/allocArray` | `ealloc` 所得由 `efree` 释放；写 `m_ppText/m_ppBin` 前必须按 `lib2.h:811-817` 释放旧值；输入 `m_pText/m_pBin/m_pAryData` 不得修改 | 正常返回交给运行时；中途失败释放临时副本；数组返回必须由运行时格式接管 | 空输入、长度越界、数组维度乘法溢出、分配失败均返回确定失败和错误文本 | 进程崩溃由宿主回收；本项目未执行 ABI 实测，不能证明无泄漏 |
| 文件句柄、file mapping、view | `LoadBmpFile` 短时打开；`MapFile` 预期创建持久映射 | `MapFile` 契约指定 DIB 持有至销毁（`bmpoperate_cmd_typedef.h:46`）；不可把 `HANDLE` 交给网关或调用方 | 关闭文件、`UnmapViewOfFile`、关闭 mapping，顺序固定且可重复；替换/析构都执行 | 打开、映射、视图或解析失败按已创建资源逆序释放；取消只能在安全边界提交 | 没有字段/实现/释放代码；若进程内崩溃无法保证清理，隔离 worker 由 OS 关闭句柄 |
| `HBITMAP` | `CreateCompitableBitmap` 预期创建；`FromHandle` 借入或转化外部句柄的语义未定 | 返回句柄当前文档明确由调用者 `DeleteObject`；`FromHandle` 是否借用/接管/复制需契约冻结，不能猜 | `CreateCompitableBitmap` 的调用方负责 `DeleteObject`；图像库内部临时 GDI 对象必须在本命令内释放 | GDI 创建/拷贝失败立即释放已创建对象；句柄无效不得进入 DIB | `lib2.h:989-991` 也提示 HBITMAP 用完需释放；当前没有句柄登记/泄漏验证；x64 下 `SDT_INT` 承载指针大小句柄需专项验证 |
| `HDC`/`HWND` 与原始指针 | `bmpoperate_cmdDef.cpp:241-244,298-302` 通过 `m_int` 取；`GetPointers` 通过 `m_pInt` 输出 | 默认借用，不得由图像库释放窗口/DC；像素指针只在当前 DIB 未变更期间有效 | 不释放借用句柄；失效、替换、析构后指针必须标记不可用 | 空指针、无效句柄、跨线程使用、DIB 变更后的 stale pointer 必须拒绝或返回错误 | 直接指针越界可能进程崩溃；当前无防护、无线程模型和无崩溃回收证据 |
| 运行时通知回调 | `NL_SYS_NOTIFY_FUNCTION` 注入 `PFN_NOTIFY_SYS`，转发到 `ProcessNotifyLib`（`bmpoperate_dllMain.cpp:125-132`） | 运行核心持有；图像库不得缓存已卸载宿主的回调 | `NL_FREE_LIB_DATA`/卸载时注销或清空 | 回调缺失、返回错误、卸载竞态不得继续调用；当前分支为空 | DLL 的 `DllMain` 四分支为空（`bmpoperate_dllMain.cpp:7-24`），不能作为清理保障 |

资源契约的最低验收条件是四种终态都能读回现场：正常完成、业务失败、主动取消/超时、宿主/worker 崩溃。必须检查文件句柄、mapping/view、GDI 对象、临时文件/缓冲区、线程/进程、端口和回调引用没有无界残留；本仓库当前没有这些实现和测试。

### 10.5 失败、崩溃与恢复矩阵

| 场景 | 必须的前置校验/结果 | 当前静态证据 | 底座处理 |
|---|---|---|---|
| 空 DIB 调用查询/像素/指针 | 返回约定失败值（如 `-1/假/空`），设置可立即读取的错误文本，不解引用隐藏成员 | 仅元数据声明；`GetErrorText` 和查询入口空体（`bmpoperate_cmdDef.cpp:28-33,58-77`） | 图像支持库统一前置 guard；网关只映射错误码和 request id |
| 截断/伪造/压缩/不支持位深度 BMP | 校验签名、头大小、偏移、stride、尺寸乘法和可读范围；失败不改旧 DIB | `DIB` 说明宣称压缩不支持、16 位仅 `BI_RGB`（`bmpoperate_dtType.cpp:29-34`），无解析器 | 解析在临时对象完成后原子提交；超限/不可验证输入可送隔离 worker |
| 越界坐标、颜色索引、颜色表或点阵长度 | 不读写越界；返回失败并清晰错误 | 参数说明要求越界失败（`bmpoperate_cmdInfo.cpp:31-49`），实现只有取参 | 支持库按宽高/位深度计算上界；网关设置最大图像尺寸和字节数 |
| `CopyTo` 默认值、目的区域越界、自身重叠 | 先归一化可选参数，检查源/目的矩形；重叠策略显式（临时 buffer 或拒绝） | `bmpoperate_cmdInfo.cpp:51-58` 只有声明，`bmpoperate_cmdDef.cpp:198-209` 只有取参 | 兼容适配器不得自行解释默认值；由图像库唯一实现 |
| 无效 `HBITMAP/HDC/HWND`、GDI 分配失败 | 调用前类型/有效性检查，GDI 失败释放已创建对象，不把伪句柄写入 DIB | 句柄均以 `SDT_INT` 声明（`bmpoperate_cmdInfo.cpp:68-82`），无实现 | 句柄租约必须带 kind、owner、位数和 release 函数；不合约的裸句柄拒绝 |
| `GetPointers` 后修改/销毁/重分配 DIB | 指针借用不可跨变更/调用边界；变更时使 token 失效 | 源码明确警告直接改指针可能造成崩溃（`bmpoperate_cmd_typedef.h:36`），无 token/保护 | 运行核心只传短期 borrow view；禁止把裸地址放入网关消息或异步队列 |
| 非法 `Bitmap_ConvertBitCount` 原始字节 | 必须带长度并完整校验；禁止按声明外索引读取；异常不得穿过 ABI | 声明明确“甚至造成程序崩溃”（`bmpoperate_cmdInfo.cpp:80-82`）；实现从 `pArgInf[0]` 取 DC（`bmpoperate_cmdDef.cpp:309-314`） | 立即列为 P0 契约缺口；修复参数基址并在 worker/边界捕获异常，未修复前隔离/废弃该入口 |
| `ealloc`/`efree`、返回值替换、数组维度溢出 | 检查分配返回值和整数溢出；临时对象失败自动释放；返回值按运行时 allocator 交接 | `ealloc` 直接 `memset(pMem,...)` 未展示空指针保护（`elib/fnshare.h:25-39`）；`MDATA_INF` 规定旧值释放（`elib/lib2.h:811-817`） | 运行核心提供 checked allocator/统一 cleanup；图像库不得跨 allocator 释放 |
| 文件/映射中途失败、重复加载、取消/超时 | 逆序释放已取得资源；旧 DIB 状态保持可定义；同步命令在安全点检查 deadline | `MapFile` 只声明持有关系；所有入口空体 | 网关/核心负责 deadline 和取消证据；不可协作取消的原生调用进程隔离 |
| C++ 异常、访问违规、宿主/DLL 崩溃 | ABI 边界不泄漏异常；崩溃任务与宿主分离，重启后通过 lease/worker 状态判定未完成 | 当前无 `try/catch`、worker、崩溃恢复；`DllMain` 空 | 图像支持库先采用 no-throw 边界；复杂/不可信解码走独立 worker；网关把 crash 作为明确失败而非假成功 |

恢复原则：失败路径不得只打印日志或返回空值而不写错误；不得把“析构函数被调用”当成崩溃清理证据；不得把子代理/历史构建/声明性注释当成资源释放或外部依赖已验证。

### 10.6 L0-L4 验证等级（本项目现状）

| 等级 | 证明内容 | 当前核对证据/命令 | 当前状态 |
|---|---|---|---|
| **L0 源码存在** | 目标仓库、文件、符号和声明确实存在 | 目标目录静态读取；`git log -1 --format='%H%n%ad%n%D' --date=iso-strict` 得 `fd2dff40176f7dcdb858796ff2a9727a6abdf595`；`bmpoperate_cmdDef.cpp:6-315` | **已确认**：源码骨架和命令契约存在；不等于功能存在 |
| **L1 结构静态** | 命令表、数据类型、导出、通知、工程配置可静态对齐 | `BMPOPERATE_DEF` 35 项；`GetNewInf`/`Source_bmpoperate.def`；`bmpoperate.sln`、两个 `.vcxproj`；当前核对未使用错绑代码图 | **已确认（弱验证）**：可证明结构，不证明编译/运行 |
| **L2 构建/装载** | Windows VS/v141 真实编译、链接、导出和支持库加载 | 本机 macOS ARM64；未执行 `msbuild/cl`，未生成 DLL/静态库；既有文档记录 `PlatformToolset=v141` | **未验证**：没有构建产物、退出码或装载回读 |
| **L3 运行契约** | Windows/易语言 ABI 下成功、失败、边界、返回值、错误文本和资源释放均真实通过 | 仓库无测试目录/夹具；未运行易语言 IDE、Windows GDI 或真实 `PMDATA_INF` 调用 | **未验证**：尤其未证明 x64 句柄、`pRetData`、映射和崩溃边界 |
| **L4 外部集成/韧性** | 真实宿主、系统 GDI、外部 provider、超时/取消/崩溃恢复、泄漏和重启现场通过 | `NL_GET_DEPENDENT_LIBS` 仅静态返回空依赖；无 provider manifest、worker、压力/泄漏/崩溃报告；项目上下文错绑 | **未验证/阻断**：不能宣称零外部依赖、无泄漏或可恢复 |

因此本项目后续交付等级为 **L1（弱验证）**；能力实现和底座集成不得写成“已完成”。

### 10.7 验收契约与装配计划

在任何生产底座改动前，必须冻结以下契约：

1. **输入/输出**：所有 `SDT_BIN` 均显式携带长度；文本编码和路径规则明确；`SDT_INT` 句柄在 Win32/x64 的宽度策略明确；返回 `SDT_TEXT/SDT_BIN/数组/复合 DIB` 明确创建者、接管者和释放函数。
2. **对象与资源**：定义 DIB 内部字段、版本/指针 token、文件映射三件套（file/mapping/view）、GDI handle kind 和 `FromHandle` 的 borrow/copy/adopt 语义；析构、替换、失败、取消、超时、崩溃各有可重复 cleanup。
3. **错误与提交**：错误码和错误文本由图像支持库唯一生成，成功清空旧错误；解析/变换先临时构造、成功后一次提交；C++ 异常/访问违规不得跨 `PFN_EXECUTE_CMD`；`Bitmap_ConvertBitCount` 参数索引必须先修正并回归。
4. **网关与核心**：网关只接收能力 id、版本、大小限制、deadline、取消 token、句柄 lease 和 request id；核心负责 ABI、allocator、lease、取消/崩溃终态和证据；图像库负责像素/格式语义；provider 只负责受控系统/第三方调用。
5. **验证门禁**：L2 必须有 Windows 构建/导出/装载回读；L3 至少覆盖 1/4/8/16/24/32 位、top-down、颜色表、截断/压缩/超限、越界、旋转/镜像/重叠复制、映射关闭、GDI DeleteObject、返回值释放；L4 必须覆盖 x64、allocator mismatch、重复调用、取消/超时、worker 崩溃后句柄/文件/进程现场和宿主重启恢复。

装配顺序固定为：

```text
冻结句柄/内存/错误/长度契约
  → 修复命令索引与参数基址风险
  → 在图像支持库实现 DIB 状态与解析/变换原子能力
  → 接入运行核心 allocator、返回值、lease、cleanup 和 no-throw 边界
  → 以唯一网关适配器映射旧 DIB 方法/能力 id
  → Windows L2 构建装载
  → Windows L3 功能/失败/资源回收
  → L4 外部 provider、x64、超时取消、崩溃隔离和重启现场
```

在 L2/L3 未通过前，`CreateCompitableBitmap`、`FromHandle`、`MapFile`、`GetPointers` 和 `Bitmap_ConvertBitCount` 只能标为 **待核/隔离**，不能作为公共底座能力直接复用。

## 11. 证据路径与版本基线

- `bmpoperate_cmd_typedef.h`：命令清单、中文契约、返回类型、参数数量与方法状态。
- `bmpoperate_cmdDef.cpp`：命令入口及当前空实现/参数提取事实。
- `bmpoperate_cmdInfo.cpp`：参数类型、默认值、引用参数和数组参数表。
- `bmpoperate_dtType.cpp`：`位图`/`DIB` 数据类型、方法索引、隐藏成员。
- `bmpoperate_dllMain.cpp`：库元信息、`GetNewInf`、通知协议、函数指针/静态函数名表。
- `include_bmpoperate_header.h`：SDK 头依赖与命令声明生成。
- `elib/lib2.h`、`elib/fnshare.h`、`elib/fnshare.cpp`、`elib/untshare.h`：易语言 ABI、内存/数组辅助、系统通知与 Windows 辅助边界。
- `bmpoperate.vcxproj`、`bmpoperate_static/bmpoperate_static.vcxproj`、`bmpoperate.sln`：动态/静态构建配置。
- `Source_bmpoperate.def`：DLL 导出边界。
- 后续新增裁决的直接证据：`bmpoperate_cmd_typedef.h:12-47`（命令/资源/失败声明）、`bmpoperate_cmdDef.cpp:6-315`（入口空实现、句柄/指针/参数取值）、`bmpoperate_cmdInfo.cpp:5-101`（ABI 参数与非法输入警告）、`bmpoperate_dtType.cpp:5-37`（DIB 隐藏成员）、`bmpoperate_dllMain.cpp:7-178`（DLL/通知/依赖边界）、`elib/fnshare.h:20-169`（通知与 allocator）、`elib/lib2.h:780-824,989-991,1137-1169,1234-1239`（数据所有权、位图通知、生命周期通知与命令 ABI）。
- 版本：本地与远程 `fd2dff40176f7dcdb858796ff2a9727a6abdf595`，远程地址 `https://gitee.com/JYtechnology/bmpoperate.git`。

本文件是项目根唯一架构事实文档；后续复核应直接更新本文件，不另建平行架构报告。
