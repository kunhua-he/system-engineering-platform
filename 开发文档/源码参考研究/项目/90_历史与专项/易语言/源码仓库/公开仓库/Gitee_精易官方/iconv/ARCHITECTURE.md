# iconv 架构建档

> 本文件是 `iconv` 仓库的唯一架构事实源。首轮建档依据当前工作树中的源码、工程文件、构建日志和 Git 元数据；未运行或未能由源码直接证明的内容明确标为“未验证”。旧细探文件本轮未发现，因此无可吸收/删除项。后续深挖只更新本文件，不复制出平行架构文档。

## 1. 项目定位

`iconv` 是面向 Windows 易语言的编码转换支持库，库名为“编码转换支持库Ex”。它把 GNU libiconv 1.17 风格的编码转换接口封装成易语言支持库命令，同时保留 `iconv_open`、`iconv`、`iconv_close` 低层接口命令。

当前仓库不是纯跨平台 libiconv 工程，而是三部分的组合：

1. **易语言支持库适配层**：实现命令元数据、常量、命令函数表、易语言 ABI、内存/字节集封装和系统通知。
2. **嵌入式 GNU libiconv 实现**：`libiconv/iconv.c` 及其编码表、别名表、转换循环和转写表，作为主要转换内核。
3. **Windows 原生实现源码**：`win_iconv.c` 基于 Win32/MLang 的另一套 `iconv_open`/`iconv`/`iconv_close` 实现；当前工程确实把它列入编译项，但从易语言命令调用链不能证明运行时使用的是这条实现。

源码证据显示，命令元数据均使用 `_CMD_OS(__OS_WIN)`，核心适配代码调用 `CreateFile`、`ReadFile`、`WriteFile`、`SetFilePointer` 和 Windows 类型；因此实际可用边界应按 Windows 运行时理解。`LIB_INFO` 的 `OS_ALL` 声明与命令/代码的 Windows 限制存在口径差异，不能据此认定已支持非 Windows 系统。

## 2. 总体流程图与数据流

```text
易语言程序
   │ 调用支持库命令
   ▼
iconv.fne / Visual C++ DLL
   │ GetNewInf() 返回 LIB_INFO
   │ iconv_ProcessNotifyLib_iconv() 接收系统通知
   ▼
命令表 ICONV_DEF + 参数表 g_argumentInfo_iconv_global_var
   │ 分派到 Kiiconv_* 命令实现
   ▼
数据适配层
   ├─ 文本型：m_pText / m_ppText + strlen()
   └─ 字节集：GetAryElementInf() 解析易语言数组头
   │
   ├─ 组合命令：iconv_open → iconv → iconv_close
   ├─ 长连接命令：iconv_open → 多次 iconv → iconv_close
   ├─ 原始命令：直接转发 iconv_t、inbuf、outbuf、长度指针
   └─ 文件命令：CreateFile → 1 MiB 读入 → 4 MiB 转换缓冲 → WriteFile
   ▼
libiconv/iconv.h
   │ iconv_open/iconv/iconv_close 映射为 libiconv_open/libiconv/libiconv_close
   ▼
libiconv/iconv.c
   ├─ 编码名规范化、别名查找、CHAR/WCHAR_T 解析
   ├─ iconv_open1.h 解析源/目标编码及 //TRANSLIT、//IGNORE
   ├─ iconv_open2.h 初始化转换描述符和状态
   ├─ loop_unicode.h 通过 UCS-4 中转并处理错误/转写/回调
   ├─ loop_wchar.h 处理 wchar_t 相关路径（由配置宏决定）
   └─ converters.h + 约 200 个编码实现/表头
   ▼
输出缓冲区 / 易语言文本或字节集
```

## 3. 目录与文件地图

仓库当前由 335 个 Git 跟踪文件组成，根目录和主要目录如下。`libiconv/` 占 298 个跟踪文件，绝大多数为编码转换实现、查表数据或生成产物。

| 路径 | 职责 | 证据状态 |
|---|---|---|
| `iconv.vcxproj` | Visual Studio 动态库工程；编译易语言适配层、`libiconv/iconv.c`、`localcharset.c`、`win_iconv.c` | 已实现/已声明，工程可读 |
| `iconv.sln` | 解决方案；声明 `iconv` 与缺失的 `iconv_static/iconv_static.vcxproj` 两个项目 | 已声明；静态子工程未验证 |
| `iconv.vcxproj.filters` | VS 筛选器；把桥接代码、`elib`、`libiconv` 分组 | 已实现 |
| `Source_iconv.def` | DLL 导出定义：`GetNewInf`、`libiconv_open`、`libiconv`、`libiconv_close` | 已实现 |
| `iconv_dllMain.cpp` | DLL 生命周期、`LIB_INFO`、函数名表、易语言系统通知 | 已实现 |
| `iconv_cmd_typedef.h` | 用 `ICONV_DEF` 集中定义 10 个易语言命令及其参数偏移 | 已实现 |
| `iconv_cmdInfo.cpp` | 命令参数说明和 `CMD_INFO` 数组 | 已实现 |
| `iconv_const.cpp` | 116 个 `编码_*` 文本常量及其编码名 | 已实现 |
| `iconv_dtType.cpp` | 自定义数据类型注册；当前数量为 0 | 已实现 |
| `cppCode/iconv_0_iconv.cpp` | 组合转换、Ex 转换、文件转换命令实现 | 已实现 |
| `cppCode/iconv_1_iconv_open.cpp` | 两个 `编码转换_打开`/`iconv_open` 命令实现 | 已实现 |
| `cppCode/iconv_2_iconv_iconv.cpp` | 两个字节集/Ex 转换命令及一个原始指针接口 | 已实现 |
| `cppCode/iconv_3_iconv_close.cpp` | 关闭句柄命令 | 已实现 |
| `include_iconv_header.h` | 汇总易语言 SDK 头、命令声明和 `libiconv/iconv.h` | 已实现 |
| `elib/` | 易语言支持库 SDK 兼容头、类型、通知、内存和字节集辅助函数 | 已实现/第三方 SDK 代码 |
| `libiconv/iconv.c` | GNU libiconv 主调度、描述符、公开 C API、扩展 API | 已实现 |
| `libiconv/iconv.h` | `iconv_t`、公开 API、控制/回调扩展声明；版本宏 `_LIBICONV_VERSION=0x0111` | 已声明并有对应实现 |
| `libiconv/converters.h` | `conv_struct`、转换函数指针和编码头汇总 | 已实现 |
| `libiconv/encodings*.def` | 编码与别名的声明源；由预处理宏选择平台/扩展集合 | 已声明/编译期数据 |
| `libiconv/aliases*.h`、`canonical*.h` | gperf 生成的别名和规范名查找表 | 已实现/生成产物 |
| `libiconv/loop_unicode.h`、`loop_wchar.h` | Unicode 中转、`wchar_t` 路径、错误处理、转写、fallback/hook | 已实现 |
| `libiconv/translit.def`、`translit.h`、`cjk_variants.h` | Unicode 降级转写和 CJK 变体数据 | 已实现/数据表 |
| `libiconv/localcharset.c/.h` | 根据系统 locale/Windows codepage 得到规范编码名 | 已实现 |
| `win_iconv.c` | Win32 API/MLang 编码转换实现，可选动态加载外部 libiconv DLL | 已实现源码；当前命令链未证明使用 |
| `*.e`、`*.bak`、`*.fne`、`*.exe`、`*.dll`、`*.lib` | 易语言工程/导出库/Windows 构建或样例二进制 | 已存在；来源和与当前源码的一致性未验证 |
| `iconv.log` | Visual Studio Release 编译日志，含警告和产物路径 | 构建证据 |

仓库没有 `README`、`LICENSE`、测试目录、测试脚本、CI 配置或旧 `细探-*.md` 文件。

## 4. 模块职责与真实调用链

### 4.1 支持库注册与加载

1. `iconv_dllMain.cpp` 定义 `g_LibInfo_iconv_global_var`，登记 GUID `{A0005538-9391-4dd9-B4D6-8EB7B9360F08}`、版本 `3.0.1`、依赖的易语言系统/核心库版本 `3.7`、名称、分类、命令表、常量表和通知函数。
2. `GetNewInf()` 返回 `&g_LibInfo_iconv_global_var`，由易语言加载器获取库描述。
3. `ICONV_DEF` 通过宏生成命令元数据、函数指针数组和静态编译命令名数组；`ICONV_NAME` 将库名、英文名、序号拼接为实现符号。
4. `iconv_ProcessNotifyLib_iconv()` 处理 `NL_GET_CMD_FUNC_NAMES`、`NL_GET_NOTIFY_LIB_FUNC_NAME`、`NL_GET_DEPENDENT_LIBS`、`NL_SYS_NOTIFY_FUNCTION` 等通知；系统通知转发到 `elib/fnshare.cpp` 的 `ProcessNotifyLib()`。
5. `fnshare.cpp` 保存易语言系统通知回调，首次收到 `NL_SYS_NOTIFY_FUNCTION` 后通过 `NRS_GET_PRG_TYPE` 获取调试/编译环境标识。

### 4.2 一次性组合转换：`编码转换` / `编码转换Ex`

`cppCode/iconv_0_iconv.cpp` 先从 `_SDT_ALL`、`SDT_BIN` 或 `SDT_TEXT` 取得输入指针和长度；字节集通过 `GetAryElementInf()` 跳过易语言数组头，文本通过 `strlen()` 取长度。空输入直接失败。

随后调用 `iconv_open(tocode, fromcode)`，分配 `输入长度 × 4` 的输出容量，调用 `iconv()`，成功后将结果包装成易语言字节集（前两个 `INT` 保存维数和数据长度），最后调用 `iconv_close()`。Ex 版本在“返回文本型”参数为真时直接把转换缓冲区标为文本类型，否则包装为字节集。失败时释放 `ealloc()` 内存并将可选“执行结果”写为假。

### 4.3 长连接转换：`编码转换_打开` / `编码转换_转换` / `编码转换_关闭`

- `cppCode/iconv_1_iconv_open.cpp` 调用 `iconv_open()`，把 `iconv_t` 强制转换为易语言 `INT` 返回；`-1` 表示失败。
- `cppCode/iconv_2_iconv_iconv.cpp` 从句柄整数恢复 `iconv_t`，允许同一句柄多次转换；普通版本返回字节集，Ex 版本按选项返回文本或字节集。
- 原始 `iconv` 命令直接把易语言整数解释为 `iconv_t`、`char**`、`size_t*`，调用底层 `iconv()` 并返回 `size_t` 整数；这要求调用者自行保证指针、长度和缓冲区有效。
- `cppCode/iconv_3_iconv_close.cpp` 调用 `iconv_close()`，返回值为 0 时返回真。

### 4.4 文件转换：`编码转换_文件Ex`

`cppCode/iconv_0_iconv.cpp` 的文件路径实现使用 Windows 文件句柄。输入文件以共享读写方式打开，输出文件以 `OPEN_ALWAYS` 打开；建立转换句柄后，循环使用 1 MiB 输入缓冲区和 4 MiB 输出缓冲区，调用 `ReadFile`、`iconv`、必要时用 `SetFilePointer` 回退未消费输入，再调用 `WriteFile`。最后释放两个缓冲区、关闭转换句柄和文件句柄。

源码没有看到输出文件截断、写入位置初始化、输入输出文件相同校验或完整的 `iconv` flush 调用，因此这些行为不能按注释中的“不能同文件”视为已实现保证。

## 5. 核心数据模型与状态

### 5.1 libiconv 转换描述符

`libiconv/converters.h` 定义核心 `struct conv_struct`：

| 字段 | 含义 |
|---|---|
| `lfuncs` | 选择 `unicode_loop_convert`、`wchar_*` 或 `wchar_id_*` 转换/重置循环 |
| `iindex` / `ifuncs` / `istate` | 源编码索引、源侧多字节到 Unicode 函数表、源状态 |
| `oindex` / `ofuncs` / `oflags` / `ostate` | 目标编码索引、Unicode 到目标编码函数表、转写能力标志、目标状态 |
| `transliterate` | 是否启用 `//TRANSLIT` |
| `discard_ilseq` | 是否启用 `//IGNORE` 对非法序列丢弃 |
| `fallbacks` | 非 `LIBICONV_PLUG` 构建下的四类 fallback 回调和用户数据 |
| `hooks` | Unicode/wide character 成功转换 hook 和用户数据 |

`iconv_open1.h` 解析编码名、大小写、别名、本地 `CHAR`/`WCHAR_T`、`//TRANSLIT` 和 `//IGNORE`；`iconv_open2.h` 填充函数表、选择循环、清零 `istate`/`ostate`，并初始化 fallback/hook。`iconv()` 在空输入指针时走 reset，正常输入时走转换循环；`iconv_close()` 释放描述符。

### 5.2 编码索引与查找表

- `encodings.def` 以 `DEFENCODING` 声明编码、别名、源侧 `xxx_mbtowc` 和目标侧 `xxx_wctomb`；当前文件共 1040 行，`converters.h` 汇总实际编码实现头。
- `aliases.h` 是 gperf 产物，头部声明 `TOTAL_KEYWORDS 349`、`MAX_WORD_LENGTH 45`，用于快速别名到 `encoding_index` 的查找。
- `canonical*.h` 保存规范名称偏移；`iconv_canonicalize()` 会先转大写、去除 `//TRANSLIT`/`//IGNORE`，查别名并返回规范名，未知名称原样返回。
- `encodings_local.def` 声明 `CHAR` 与 `WCHAR_T` 两个运行时本地编码占位符，实际由 `locale_charset()` 和平台 `wchar_t` 条件决定。

### 5.3 易语言数据表示

`elib/fnshare.h` 的 `CloneBinData()` 和命令实现共同表明字节集布局为：

```text
[维数 INT=1][元素数量 INT][连续字节数据]
```

`GetAryElementInf()` 读取维数和各维长度，返回数据区首地址和元素总数。命令输出通过 `ealloc()` 从易语言运行时申请内存，失败时通过 `efree()` 释放。文本型路径直接使用 `char*` 与 `strlen()`，因此源码没有证明对内嵌 NUL 的文本数据提供长度安全处理。

### 5.4 Windows 原生描述符（备用源码路径）

`win_iconv.c` 定义 `rec_iconv_t`，内部包含底层 `iconv_t`、函数指针 `iconv_close`/`iconv`、`errno` 获取函数、源/目标 `csconv_t`，可选保存外部 libiconv DLL 句柄。`csconv_t` 保存 codepage、flags、字符转换函数、状态 `mode`、兼容映射表。其 Windows 路径可使用 Kernel32 的 `MultiByteToWideChar`/`WideCharToMultiByte`，ISO-2022/EUC-JP 可动态加载 `mlang.dll`。

## 6. 对外接口

### 6.1 易语言命令

| 类别 | 命令 | 参数/返回 | 源码实现 | 状态 |
|---|---|---|---|---|
| 编码转换 | `编码转换` | 数据、源编码、目标编码、可选执行结果；返回 `SDT_BIN` | `iconv_0_iconv.cpp` | 已实现 |
| 编码转换 | `编码转换_打开` | 源编码、目标编码；返回 `SDT_INT` 句柄 | `iconv_1_iconv_open.cpp` | 已实现 |
| 编码转换 | `编码转换_转换` | 句柄、数据、可选执行结果；返回 `SDT_BIN` | `iconv_2_iconv_iconv.cpp` | 已实现 |
| 编码转换 | `编码转换_关闭` | 句柄；返回 `SDT_BOOL` | `iconv_3_iconv_close.cpp` | 已实现 |
| 编码转换 | `编码转换Ex` | 数据、源编码、目标编码、返回文本型、可选执行结果；返回 `_SDT_ALL` | `iconv_0_iconv.cpp` | 已实现 |
| 编码转换 | `编码转换_转换Ex` | 句柄、数据、返回文本型、可选执行结果；返回 `_SDT_ALL` | `iconv_2_iconv_iconv.cpp` | 已实现 |
| 编码转换 | `编码转换_文件Ex` | 源编码、目标编码、输入文件、输出文件；返回 `SDT_BOOL` | `iconv_0_iconv.cpp` | 已实现源码；边界行为未验证 |
| iconv | `iconv_open` | `tocode`、`fromcode`；返回 `SDT_INT` | `iconv_1_iconv_open.cpp` | 已实现 |
| iconv | `iconv_close` | `icd`；返回 `SDT_BOOL` | `iconv_3_iconv_close.cpp` | 已实现 |
| iconv | `iconv` | `icd`、`inbuf`、`inbytesleft`、`outbuf`、`outbytesleft`；返回 `SDT_INT` | `iconv_2_iconv_iconv.cpp` | 已实现 |

`iconv_cmd_typedef.h` 的 `ICONV_DEF` 是上述接口的权威命令顺序和参数偏移来源；`iconv_cmdInfo.cpp` 的参数说明另外声明数据编码名不区分大小写，并允许使用库常量或直接输入编码文本。

### 6.2 DLL 导出接口

`Source_iconv.def` 只声明导出：

```text
GetNewInf
libiconv_open
libiconv
libiconv_close
```

`libiconv/iconv.h` 在未定义 `LIBICONV_PLUG` 时把标准名宏映射为 `libiconv_*`，使易语言桥接层链接到 GNU libiconv 实现。`iconvctl`、`iconvlist`、`iconv_canonicalize` 等 libiconv 扩展在头文件/源码中存在，但未列入此 DLL `.def`，不能视为本支持库对外导出的易语言接口。

## 7. 编码与转换语义

源码已实现或以静态表纳入的编码族包括：

- Unicode/通用：`UTF-8`、`UTF-7`、`UCS-2`/`UCS-4`、`UTF-16`、`UTF-32`、大小端和 swapped/internal 变体、`C99`、`JAVA`。
- 8 位编码：ISO-8859 系列、KOI8 系列、Windows CP125x、DOS CP4xx/8xx、Mac 系列、HP-ROMAN8、NEXTSTEP、ARMSCII、Georgian、TIS-620、VISCII、TCVN 等。
- 中日韩：GB2312、GBK、GB18030、EUC-CN/TW/JP/KR、BIG5/CP950/BIG5-HKSCS、Shift-JIS/CP932、JIS X、ISO-2022-JP/CN/KR、CP949/JOHAB 等。
- 条件/扩展：AIX、OSF/1、DOS、z/OS EBCDIC 和 `ENABLE_EXTRA` 对应编码；是否被当前 MSVC 预处理配置纳入，取决于 `config.h` 与工程宏，不能仅凭文件存在认定全部进入最终二进制。

转换循环支持：

- 以 Unicode 为 pivot 的多字节输入/输出转换；
- 目标缓冲区不足返回 `E2BIG`；输入不完整返回 `EINVAL`；非法序列返回 `EILSEQ`；
- `//TRANSLIT`：使用引号、重音、CJK 变体和 `translit` 表进行降级；
- `//IGNORE`：丢弃非法输入或无法表示的字符；
- 非 `LIBICONV_PLUG` 下的 Unicode/wide fallback 与字符 hook；
- reset 时刷新待处理字符、输出 shift sequence，并清零转换状态。

## 8. 技术栈、构建与依赖

### 8.1 工程声明

- Visual Studio solution format `12.00`，VS 版本 `17.3.32901.215`。
- `iconv.vcxproj` 使用 `PlatformToolset v141`、Windows SDK `10.0.19041.0`，配置为 `DynamicLibrary`。
- 声明 `Debug/Release × Win32/x64`；Win32 Debug/Release 设置 `.fne` 目标扩展，x64 未设置该扩展。
- Release Win32 定义 `__E_FNENAME=Kiiconv`，Debug Win32 定义 `__E_FNENAME=iconv`；x64 配置未出现同名易语言库宏，能否按预期生成支持库未验证。
- Win32 Release 使用 `AdditionalIncludeDirectories>\libiconv;</...>`，这是以根路径开头的 Windows 路径写法，是否能在目标机器正确解析未验证。
- Release/Debug 运行库、优化、增量链接和模块定义文件配置均在 `iconv.vcxproj` 中；Win32 配置使用 `Source_iconv.def`，x64 配置没有配置该 `.def`。

### 8.2 直接依赖边界

| 依赖 | 作用 | 证据 |
|---|---|---|
| 易语言 SDK/运行时 | `LIB_INFO`、`CMD_INFO`、`MDATA_INF`、通知和内存 ABI | `elib/*.h`、`fnshare.cpp` |
| Windows API | DLL、文件读写、Win32 类型；`win_iconv.c` 还依赖 MLang | `iconv_dllMain.cpp`、`cppCode/iconv_0_iconv.cpp`、`win_iconv.c` |
| GNU libiconv 内嵌源码 | 编码表、别名表、转换循环和公开 API | `libiconv/*.c/.h/.def` |
| MSVC legacy stdio | 兼容 VS2017 链接器 | `#pragma comment(lib, "legacy_stdio_definitions.lib")` |
| `mlang.dll` | 仅 `win_iconv.c` 的 ISO-2022/EUC-JP 路径动态加载 | `load_mlang()` |
| 外部 libiconv DLL | 仅 `win_iconv.c` 在 `USE_LIBICONV_DLL` 编译宏启用时可选加载 | `WINICONV_LIBICONV_DLL` / `DEFAULT_LIBICONV_DLL` |

没有发现项目级包管理文件或可复现的依赖锁定文件。

## 9. 构建产物与持久化

本项目没有数据库、配置文件存储、网络服务或长期业务状态。持久状态只存在于单个 `iconv_t` 转换描述符及其源/目标编码状态，句柄关闭后释放。

仓库已有以下二进制/工程产物：`iconv.fne`、`iconv.exe`、`iconv_new.exe`、`iconv_vc2017.exe`、`iconv_vc6.exe`、`Project6.dll`、`iconv_static.lib`、`iconv.e`、`iconv.bak`、`iconv_vc6.e`。它们是 Git 中已跟踪的历史产物，不能证明与当前源码在本机可重建或相互匹配。

`iconv.log` 记录了一次 Windows Visual Studio Release 构建：编译了 `fnshare.cpp`、5 个根/桥接源文件、4 个 `cppCode` 文件、`iconv.c`、`localcharset.c`，并记录输出 `E:\支持库\功能库\iconv\Release\iconv.fne`。日志包含大量 C4819（代码页字符）、C4018（有符号/无符号比较）和 C4090（const 限定符）警告；日志没有显示构建失败，但这是历史日志，不是本轮在当前环境重新执行的结果。

## 10. 测试与验证状态

### 已有证据

- `iconv.log`：有一次 Windows Release 构建完成记录，末尾明确出现 `iconv.vcxproj -> ...\iconv.fne`。
- 已存在多个 `.fne/.exe/.dll/.lib` 二进制产物，说明仓库曾产生过构建结果。
- 源码层面可追踪命令注册、参数索引、转换描述符初始化和资源释放调用链。

### 未发现/未执行

- 未发现单元测试、集成测试、回归样例、CTest、CI 或自动化测试脚本。
- 本轮未在 macOS 上执行 Visual Studio/MSBuild，也未加载 Windows 二进制；因此未验证 DLL ABI、易语言 IDE 加载、命令实际分派、中文/GBK 文件转换、全部编码兼容性和 x64 构建。
- 未验证 `iconv.vcxproj` 同时编译 `libiconv/iconv.c` 与 `win_iconv.c` 后的最终导出/链接行为；从符号命名看两者可并存，但 `win_iconv.c` 是否被命令适配层选用仍无证据。
- 未验证 `iconv_static/iconv_static.vcxproj`，因为 `iconv.sln` 引用该路径，而当前仓库跟踪文件中不存在 `iconv_static/` 目录。
- 未验证 `编码转换_文件Ex` 的大文件、输出文件截断、同文件输入输出、跨块多字节字符、`E2BIG`/reset 处理和写入失败后的结果。

## 11. 风险与后续复核点

1. **平台声明不一致**：`LIB_INFO` 为 `OS_ALL`，命令却是 `__OS_WIN`，实现还直接依赖 Windows API。后续应以目标易语言版本和实际加载器行为裁决。
2. **x64 配置不完整**：x64 没有看到 `Source_iconv.def`、`__E_FNENAME` 和 `.fne` 目标扩展配置，需在 Windows 构建机验证。
3. **静态工程缺失**：solution 引用 `iconv_static/iconv_static.vcxproj`，但该目录不在当前仓库；静态库支持不能据此文档推定存在。
4. **文件转换边界**：源码按固定 1 MiB/4 MiB 分块，未显式调用 reset，且输出文件用 `OPEN_ALWAYS`；多字节边界和旧内容残留风险需运行测试确认。
5. **输入长度和缓冲区**：普通命令使用 `dwDataLen * 4`，存在整数溢出、极端扩张不足或 `ealloc` 失败未检查等未验证边界；文本使用 `strlen`，不支持带 NUL 的有效字节序列作为文本。
6. **句柄安全**：易语言把指针句柄转换为 `INT`，原始命令还允许直接传指针整数；调用者传入无效或已关闭句柄的行为未做保护。
7. **构建警告与编码**：历史日志已有 C4819/C4018/C4090，`libiconv/iconv.h` 与易语言 GBK 工程混用的编码问题应在 Windows 构建时重新确认。
8. **版本/来源边界**：`iconv_dllMain.cpp` 的说明声称 GNU libiconv 1.17，`libiconv/iconv.h` 的 `_LIBICONV_VERSION=0x0111` 与之相符；但没有仓库级 `COPYING.LIB`、上游提交号或完整发布元数据，许可证和上游精确版本仍应补证。
9. **导出边界**：头文件声明了较多 libiconv 扩展，`.def` 只导出四个符号；后续使用者不能把未导出扩展当作 DLL API。

## 12. Git 基线与证据索引

### Git 基线

- 仓库：`/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/iconv`
- 分支：`master`
- HEAD：`f9702c446345f56b7cb3cf43cb0680cc4102a824`
- HEAD 时间：`2023-02-08 01:52:36 +0000`
- HEAD 提交：`!1 提交修复后和扩展后的库 Merge pull request !1 from 心冷丶鱼儿/master`
- 作者：`精易科技 <63917125@qq.com>`；提交者：`Gitee <noreply@gitee.com>`
- 远程：`https://gitee.com/JYtechnology/iconv.git`
- 远程 `HEAD`/`master` 当前查询结果与本地均为 `f9702c446345f56b7cb3cf43cb0680cc4102a824`；本地工作树在建档前无修改。

### 关键源码证据路径

- 支持库注册/通知：`iconv_dllMain.cpp:6-106`、`iconv_dllMain.cpp:109-185`
- 命令与索引：`iconv_cmd_typedef.h:1-38`
- 参数元数据：`iconv_cmdInfo.cpp:1-73`
- 编码常量：`iconv_const.cpp:1-135`
- 组合/文件命令：`cppCode/iconv_0_iconv.cpp:1-236`
- 打开命令：`cppCode/iconv_1_iconv_open.cpp:1-18`
- 转换命令：`cppCode/iconv_2_iconv_iconv.cpp:1-151`
- 关闭命令：`cppCode/iconv_3_iconv_close.cpp:1-9`
- 易语言 ABI/内存/字节集：`elib/fnshare.h:20-141`、`elib/fnshare.cpp:11-71`
- 主 libiconv API：`libiconv/iconv.c:63-174`、`libiconv/iconv.c:234-365`、`libiconv/iconv.c:506-629`
- 描述符与编码实现汇总：`libiconv/converters.h:23-359`
- 编码解析：`libiconv/iconv_open1.h:20-228`、`libiconv/iconv_open2.h:20-89`
- Unicode 转换循环：`libiconv/loop_unicode.h:20-526`
- wchar 转换循环：`libiconv/loop_wchar.h:20-473`
- 本地编码：`libiconv/localcharset.c:818-1000`、`libiconv/localcharset.h:27-35`
- Windows 备用实现：`win_iconv.c:48-127`、`win_iconv.c:730-1019`、`win_iconv.c:1283-1937`
- DLL 导出：`Source_iconv.def:1-6`
- 工程源文件/配置：`iconv.vcxproj:21-211`、`iconv.sln:1-42`、`iconv.vcxproj.filters:1-101`
- 历史构建证据：`iconv.log:1-165`

## 13. 首轮结论

已能从当前源码确认：这是一个将 GNU libiconv 编码转换能力包装为易语言 Windows 支持库的项目；10 个命令、116 个编码常量、DLL 注册/通知链、字节集布局适配、核心转换描述符和 Unicode 中转循环均有源码证据。当前不能确认：非 Windows 运行、x64/静态工程可构建、所有常量均在最终二进制生效、`win_iconv.c` 是否为实际运行后端、文件分块转换的所有边界正确，以及历史二进制是否由当前源码产生。
