# python-fne 架构与事实审计

## 0. 范围、来源与结论边界

本文只审计本地只读参考仓库：

`/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/python-fne`

审计覆盖易语言桥接、`elib/lib2.h` ABI、Python C API 动态绑定、解释器生命周期、
`PyObject*` 包装、引用计数、GIL/线程状态、错误处理、动态 trampoline、工程配置、
示例测试和仓库文档。没有修改参考仓库源码。

证据口径如下：

- **源码事实**：可由当前 `.cpp`、`.h`、`.def` 或工程文件直接确认。
- **工程声明**：项目配置、更新说明或示例声称存在，但本轮没有 Windows 构建或宿主实测。
- **未验证**：当前 macOS 环境无法证明 Windows DLL、易语言宿主或 Python DLL 的运行行为。
- **风险**：源码已经暴露出需要目标环境复核的 ABI、所有权、错误、并发或资源问题。

总体结论：`python-fne` 是 Windows 原生 `.fne`/DLL，通过易语言支持库 ABI 暴露 Python
3.x C API 桥接。它具备较宽的命令和对象包装骨架，但没有形成封闭的版本握手、符号校验、
解释器状态机、错误契约、引用所有权、线程守卫或卸载闭环。它不应被描述为已验证支持
Python 3.8 以外版本、x64、线程安全、无泄漏或可安全卸载。

## 1. 定位与 CodeGraph 状态

### 1.1 项目定位

- `JYEPythonFne/JYEPythonFne/` 是支持库 DLL 的源码。
- `PythonFne_vs2019/` 包含 Visual Studio 解决方案、支持库工程和 `PythonTest` 控制台示例。
- `JYEPythonFne.def` 仅声明导出 `GetNewInf`。
- `更新说明.txt` 声称面向 Python 3.8 x32 C API，并写作“6 种库定义数据类型、85 种命令”。
- `JYEPythonFne.cpp` 实际注册 6 个自定义类型；源码命令注册点按“全局命令、类方法、继承方法”
  统计存在口径差异，当前不能把 85 或 87 直接当作最终 IDE 可见命令数。

### 1.2 CodeGraph 尝试

已在目标目录执行：

`codegraph explore "python-fne Python 易语言桥接 ABI 解释器 PyObject GIL 错误 线程 释放 build tests docs"`

结果：目标目录没有 `.codegraph` 索引，CodeGraph 不可用；没有执行初始化。后续使用文件清单、
全文检索和分段源码读取。该结果只说明索引不可用，不代表源码不存在或质量合格。

### 1.3 当前参考仓库状态

| 项目 | 事实 |
|---|---|
| HEAD | `3f6942850a324b02491bddcc699dbea6b41f7615` |
| HEAD 时间 | `2023-09-20T09:27:48+08:00` |
| 分支 | `master` |
| 远程 | `https://gitee.com/JYtechnology/python-fne.git` |
| 远程新鲜度 | 未执行网络 fetch，不能声称与远程当前一致 |
| 参考仓库工作树 | 本轮检查无显示修改 |

## 2. 总体架构与调用链

```text
易语言 IDE / 运行时
        │  LIB_INFO、CMD_INFO、MDATA_INF、PFN_EXECUTE_CMD
        ▼
JYEPythonFne.dll / .fne
        │
        ├─ DllMain：当前只返回 TRUE
        ├─ GetNewInf：首次装配静态 LIB_INFO
        ├─ Elib：命令、常量、6 个自定义类型和继承索引
        └─ EiFun：易语言命令回调
             ├─ EPython：解释器、模块、执行、错误、帧字典
             ├─ EdataToPydata：易语言值 → PyObject*
             └─ PyObj/PyList/PyDict/PyTuple/PyModule/PyIter
                    │
                    └─ PyDll：LoadLibrary + GetProcAddress
                               ▼
                         Python 3.x DLL / CPython C API
```

典型路径：

```text
设置解释器Py(path)
  → SetDllPath_Fun → SetDllPath
  → LoadLibrary(path) → 多次 GetProcAddress
  → 仅按 HMODULE 非空返回成功

初始化Py()
  → EPython::Initialize → Py_Initialize

运行代码Py(code)
  → EPython::SimpleString → PyRun_SimpleString
  → 将返回值写为易语言 SDT_INT

导入模块Py(name)
  → PyUnicode_DecodeLocale → PyImport_Import
  → PyModule 包装；异常时尝试 GetPyErrA

销毁Py()
  → EPython::FinalizeEx → Py_FinalizeEx
```

## 3. Python/易语言桥接

### 3.1 易语言命令边界

`EiFun.cpp` 的命令回调统一采用：

`void(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)`

回调读取 `m_dtDataType` 及标量、文本、字节集、复合数据字段，再调用 C++ 包装类，最后写回
`pRetData`。传址参数通过 `IsPtrArg`/`ArgFun` 处理。复合返回值通常由 `MMalloc(sizeof(T*))`
申请一个指针槽，把 `new PyObj`、`new PyList` 等对象地址写入 `m_ppCompoundData`，宿主类型的
析构回调再 `delete` C++ 对象。

这是一条进程内桥接，不是 IPC。易语言宿主、支持库 C++ 对象和 CPython 对象共享进程地址空间；
任一边界错误都可能直接破坏宿主进程。

### 3.2 支持的标准值转换

`EdataToPydata` 当前源码明确处理：

| 易语言类型 | Python 构造 | 事实与限制 |
|---|---|---|
| `SDT_BYTE` | `PyBytes_FromString` | 读取语义和长度边界需实测 |
| `SDT_SHORT`、`SDT_INT`、`SDT_INT64` | `PyLong_FromLong` | 三者都按 `int*` 读取，不能证明 64 位语义 |
| `SDT_BOOL` | `PyBool_FromLong` | 按 `int` 读取 |
| `SDT_TEXT` | `PyUnicode_DecodeLocale` | 受 locale/编码配置影响 |
| `SDT_BIN` | `PyByteArray_FromStringAndSize` | 直接解析易语言字节集内部布局 |
| `SDT_FLOAT`、`SDT_DOUBLE` | `PyFloat_FromDouble` | 源码按 `double*` 读取 |
| 库类型 | 取 `PyObj**` 并增加引用 | 只覆盖本项目 Python 包装类型 |

日期、子程序指针、数组、用户自定义类型等没有形成通用转换路径。反向转换通过类型 `repr`
字符串判断 `str/int/float/bool/bytearray`，这不是稳定的 Python 类型协议。

### 3.3 Python 可调用对象与动态函数

`Obj_CallMethod` 将追加的易语言参数转为 `PyTuple`，调用 `PyObject_CallObject`；
`Obj_CallArgDict` 将 `args`、`kwargs` 转换后调用 `PyObject_Call`。

`Module_AddFun` 不是普通静态注册：它使用 `VirtualAlloc(..., PAGE_EXECUTE_READWRITE)` 分配内存，
复制固定的 x86 `FunChar` 指令模板，把易语言子程序参数地址写入固定偏移，再把地址当作
`PyCFunction` 传给 `PyModule_AddFunctions`。这是强 ABI、强位数、可执行内存和代码注入边界；
源码未提供对应 `VirtualFree` 或重复注册清理路径，也没有测试覆盖。

## 4. 易语言 ABI、导出与元数据

### 4.1 导出与通知

- `.def` 只导出 `GetNewInf`。
- `GetNewInf` 返回全局静态 `LIB_INFO` 地址。
- `JYEPython_MessageNotify` 使用 `INT __stdcall(INT, DWORD, DWORD)`，处理命令名查询、通知函数名
  查询和依赖查询，再转发 `ProcessNotifyLib`。
- `NL_SYS_NOTIFY_FUNCTION` 通知把 `dwParam1` 转为 `PFN_NOTIFY_SYS`，保存到全局 `fnNotifySys`。
- `MMalloc`、`MFree`、`GReportError`、文本和字节集复制依赖这个宿主回调。

### 4.2 ABI 数据与生命周期

`elib/lib2.h` 定义 `DATA_TYPE`、`MDATA_INF`、`CMD_INFO`、`LIB_INFO`、
`LIB_DATA_TYPE_INFO` 和函数指针类型。结构体字段、打包、Win32 基础类型、指针宽度、调用约定、
字符编码和命令索引都属于宿主契约，不能跨边界传 C++ STL、异常或未声明所有权的内存。

`Elib` 使用全局 `vector<CMD_INFO>`、`vector<PFN_EXECUTE_CMD>`、`vector<LIB_DATA_TYPE_INFO>`。
`csh()` 将 vector 首地址写入静态 `LibInFo`。由于元数据保存的是 vector 内部地址，装配完成后
不能再追加导致重新分配；当前实现依赖“一次装配、后续复用”，不是实例隔离设计。

### 4.3 六个自定义类型

源码注册：`PyObj`、`PyList`、`PyDict`、`PyTuple`、`PyModule`、`PyIter`。类继承索引由
`ElibClass::BaseClass` 按名称筛选，最终命令表和类型表都以整数索引互相引用。增删或重排命令
可能改变旧程序所依赖的索引，不能只按函数名兼容判断。

## 5. Python DLL 与解释器生命周期

### 5.1 手工动态绑定

`PyDll.h/.cpp` 不链接 Python import library，而是手工声明 `PyObject` 和大量函数指针，并在
`SetDllPath` 中逐一 `GetProcAddress`。类别包括：

- 路径、版本、初始化、终止和内存释放；
- Unicode、bytes、数值和类型检查；
- 对象属性、调用、列表、字典、元组、模块和迭代器；
- 错误获取/恢复；
- GIL、`PyThreadState`、`PyEval_SaveThread`/`RestoreThread`；
- `PyArg_VaParse`、`PyArg_ParseTuple` 和模块函数注册。

当前函数只在 `LoadLibrary` 成功时返回 `true`，没有集中检查任何函数指针是否为空，没有检查
Python DLL 版本、Debug/Release ABI、位数、导出签名或依赖闭包。尤其源码把
`PyThreadState_Swap` 绑定到 `GetProcAddress(pydll, "PyEval_RestoreThread")`，名称和声明明显不一致，
必须作为阻断级问题在目标 Python 版本上复核。

### 5.2 初始化和终止

`EPython` 直接转发 `Py_SetPath`、`Py_Initialize`、`Py_IsInitialized`、`Py_FinalizeEx`、
`PyRun_SimpleString`。没有统一的“已加载/已初始化/关闭中/已终止”状态机，也没有阻止在
`FinalizeEx` 后继续调用、没有等待对象包装器归零、没有协调其他线程或回调。

`DllMain` 对所有原因只返回 `TRUE`，不初始化、不卸载 Python DLL，也不执行业务清理。源码没有
通用热卸载协议；调用 `FinalizeEx` 不是安全地卸载支持库或 Python DLL 的证明。

## 6. PyObject 引用、对象包装与 GIL

### 6.1 包装器所有权模型

`PyObj` 保存 `_obj` 和 `_new`：`_new=true` 时析构 `Py_DecRef`，复制构造增加引用，
`SetObj` 先释放旧对象再替换。派生类包装列表、字典、元组、模块和迭代器；部分 API 返回借用引用，
部分返回新引用，源码通过构造标志和显式 `addcref` 混合处理。

源码可见的高风险路径包括：

- `PyList_GetItem`、`PyDict_GetItem`、`PyTuple_GetItem` 返回借用引用，却以 `_new=true` 包装，
  并在部分路径再次 `addcref`；
- `PyDict_Next` 返回借用的 key/value，却用 `_new=true` 写入包装器；
- `PyList_SetItem`、`PyTuple_SetItem` 是窃取引用的 API，调用方又显式 `addcref`，语义必须逐项对账；
- `PyObj::SetAttr`、`PyDict::SetDictItem` 等路径额外增加引用，是否与目标 API 所有权匹配未验证；
- `GetType`、`GetAttr`、模块名称等临时对象在异常路径和包装复制中的计数需要实际 refcount 证据。

因此不能声称“引用计数正确”或“无泄漏”。需要 CPython debug build、对象生命周期场景和引用计数
前后对账，覆盖复制、返回、容器取值、容器写入、属性、模块、迭代器和宿主析构。

### 6.2 GIL 和线程状态

支持库把 `PyGILState_Check`、`PyGILState_Ensure`、`PyGILState_Release`、
`PyEval_SaveThread`、`PyEval_RestoreThread`、`PyThreadState_Get`、`PyThreadState_Swap`
直接暴露为易语言命令。参数和返回值使用 `SDT_INT`，而 `PyThreadState*` 在 x64 下不能安全压入
32 位整数。源码没有高层互斥、线程绑定、嵌套计数、异常保护或调用顺序守卫。

`SaveThread` 与 `GetPyEnsure` 的 token 不能混用；`RestoreThread` 与 `Release` 必须分别匹配对应
API。当前支持库让调用者自行管理这些协议，顺序错误可能导致崩溃、死锁或 Python 状态损坏。

迭代器另有逻辑问题：`PyIter::IsNext()` 只返回构造时的 `_isNext`，`IterNext()` 没有按成功/耗尽
更新该字段，故“是否还有值”的命令语义不能由源码证明。

## 7. 错误、编码与进程线程

### 7.1 错误处理

`SetLastError` 在 `EiFun.cpp` 中为空实现。`ImportPy` 检测 `PyErr_Occurred()` 后调用
`EPython::GetPyErrA()`，该函数 `PyErr_Fetch`、格式化后又 `PyErr_Restore`，没有统一的宿主错误
对象、清除策略、错误码或可重试字段。`GReportError`、`MMalloc` 和 `MFree` 直接调用
`fnNotifySys`，没有为空回调建立可靠保护。

失败命令还可能继续构造空包装器并写回复合对象；例如不可调用对象路径设置错误后仍需检查返回对象，
许多函数不验证输入指针、`PyObject*`、返回值或 Python 异常。当前错误边界只能描述为“零散文本/通知
尝试”，不能描述为闭环错误契约。

### 7.2 编码

项目使用 `__GBK_LANG_VER` 和 `CharToWchar`，`WcharTochar` 使用 `CP_ACP`；Python 侧使用
`PyUnicode_DecodeLocale`/`EncodeLocale`。工程的 Debug|Win32 为 MultiByte，其他支持库配置为
Unicode，而源码大量使用 `char*`/`LPSTR`。中文路径、非系统代码页、嵌入 NUL 和失败替换行为
没有目标环境证据。

### 7.3 线程与进程

源码没有创建工作线程、线程池或隔离子进程。所有易语言回调、C++ 包装器、Python 解释器、动态
函数 trampoline 和宿主窗口/回调都在同一进程。`PythonTest` 也是单进程控制台示例。

因此它不是崩溃、阻塞、原生扩展或不可信 Python 代码的隔离方案。平台若要承载不可信模块，必须
放入受管子进程，用版本化 IPC、deadline、退出码、强杀和 orphan 回收保护宿主。

## 8. 释放、卸载与资源所有权

当前资源边界如下：

| 资源 | 正常路径 | 未封闭风险 |
|---|---|---|
| Python DLL | `LoadLibrary` | 没有 `FreeLibrary` 路径，也没有重复加载/替换策略 |
| Python 解释器 | `Py_FinalizeEx` 命令 | 未阻止终止后调用；未排空线程、回调和包装对象 |
| `PyObject*` | `_new` 析构 `Py_DecRef` | 借用/新引用混用，可能泄漏或过度释放 |
| 易语言返回槽 | `MMalloc`/宿主析构回调 | 未见所有命令统一初始化返回类型和失败清理 |
| C++ 包装对象 | `new/delete` | 依赖宿主正确触发 `__del__`；异常路径不统一 |
| 动态函数 trampoline | `VirtualAlloc` | 未见 `VirtualFree`、模块注销或重复注册回收 |
| `std::vector` 元数据 | 静态存储期 | vector 地址发布后不可安全追加，非实例隔离 |
| 宿主通知回调 | 全局函数指针 | 未见注销/失效门禁，空指针调用风险 |

安全关闭至少需要：停止新调用、阻止新任务、排空进行中调用、注销 Python/宿主回调、释放
trampoline 和 C++ 包装对象、确认 Python 对象引用归零、再按逆序终止解释器和卸载 DLL。当前代码
没有这条协议，故不支持安全热卸载的结论。

## 9. 构建、依赖与文档事实

### 9.1 支持库工程

`PythonFne_vs2019.sln` 包含支持库和 `PythonTest` 两个项目。支持库工程声明：

- `DynamicLibrary`、工具集 `v143`、Windows SDK `10.0`；
- `Debug/Release × Win32/x64` 四配置；
- 直接编译 `EiFun.cpp`、`Elib.cpp`、`EPython.cpp`、`JYEPythonFne.cpp`、`PyDll.cpp`；
- Debug|Win32 设置目标扩展 `.fne`、`JYEPythonFne.def` 和硬编码输出目录
  `E:\易语言正式版5.9\lib\`；
- Release|Win32、x64 配置没有对称声明相同 `.fne`、`.def` 和输出路径；
- Debug|Win32 为 MultiByte，Release|Win32 及 x64 为 Unicode，配置并不对称。

### 9.2 PythonTest

`PythonTest` 是直接包含 `Python.h` 并链接仓库 `libs` 快照的控制台应用；支持库则手工动态绑定，
这是两条不同 ABI 路径。示例执行 `Py_Initialize`、`PyRun_SimpleString`、导入 `dom`、调用
`add`、用 `PyModule_AddFunctions` 注入 `efun`、调用 `MyCall`，最后 `Py_Finalize`。

但示例没有断言、统一退出码、清理所有临时引用或失败报告；`dom.py` 的 `MyCall` 依赖 C++ 注入
的 `efun`，单独运行会因名称未定义失败。`PythonTest/include` 是 Python 头文件快照，`libs`
包含 `python3.lib`、`python38.lib` 及 debug 变体等文件；存在这些文件不等于当前环境已构建成功。

### 9.3 文档清晰度审计

- `更新说明.txt` 是功能宣传/使用说明，不是 ABI、版本兼容或运行证据。
- 仓库没有发现 `README.md`、`requirements.txt`、`pyproject.toml`、pytest/unittest 目录、CI
  配置或自动化回归脚本。
- 根参考仓库的 `ARCHITECTURE.md` 已能区分源码、工程声明和未验证项；本文件同步强化了该口径，
  并明确了原文容易混淆的命令计数、x64、GIL、引用计数、错误和释放边界。
- 本文件不把 `PythonTest` 示例称为测试通过，也不把工程存在的 x64 配置称为 x64 可用。

## 10. 验证现状与风险清单

### 10.1 本轮实际验证

- 已静态读取桥接、ABI、动态绑定、解释器、对象包装、错误、线程、释放、工程、示例和文档文件。
- 已尝试 CodeGraph；因没有 `.codegraph` 索引而不可用，未执行初始化。
- 未在 macOS 编译；未执行 Windows MSBuild、易语言 IDE 装载或真实 Python DLL 调用。
- 未运行 `SetDllPath`、`GetNewInf`、命令回调、析构、GIL、引用计数、trampoline 或卸载测试。

### 10.2 阻断级风险

1. `SetDllPath` 不检查函数指针，缺符号可能在后续调用中跳转空指针。
2. `PyThreadState_Swap` 的绑定名称错误，且线程状态通过 `SDT_INT` 暴露，x64 不安全。
3. Python 借用引用、新引用、窃取引用和显式 `addcref` 混用，所有权未闭环。
4. `FinalizeEx` 没有状态门禁、线程排空或包装器协调，终止后继续使用是未防护路径。
5. `VirtualAlloc(PAGE_EXECUTE_READWRITE)` 的 x86 trampoline 没有释放和安全验证。
6. `SetLastError` 为空，宿主错误回调和 Python 异常没有统一可观察契约。
7. 进程内执行没有崩溃/阻塞/资源隔离，不适合直接承载不可信 Python 或原生扩展。

### 10.3 重要风险

1. `SDT_INT64` 按 `int` 转换，指针和 `PyThreadState*` 通过 32 位字段传递。
2. 编码组合为 GBK、CP_ACP、locale、MultiByte/Unicode 工程设置混用。
3. 静态 vector 元数据地址、全局 Python API 指针和全局宿主通知回调均非实例隔离。
4. `PyIter::IsNext` 不随迭代更新；多个命令不设置返回类型或不检查空指针/异常。
5. 85/87 命令计数口径未与最终 IDE 可见表自动对账。

## 11. 推荐复核顺序

1. 在隔离 Windows 环境固定 Python 3.8 x86 Debug/Release、Visual Studio、SDK 和宿主版本，先完成
   `GetNewInf` 导出与 `LIB_INFO` 结构烟测。
2. 为 `PyDll` 建立逐符号清单、函数签名、位数、版本和失败原子回滚；修复或确认线程状态绑定。
3. 用最小宿主覆盖设置 DLL、初始化、执行、导入、错误、终止后的拒绝调用和重复初始化。
4. 用 CPython debug build 做引用计数对账，覆盖容器借用/新建/窃取引用、复制、属性、模块和迭代器。
5. 用真实多线程验证 GIL token 配对、线程状态归属、异常和取消；禁止把裸 `SDT_INT` 当作 x64 指针协议。
6. 对动态函数注册建立固定架构 trampoline、可执行内存生命周期、注销和失败清理测试。
7. 将 `PythonTest` 改为有断言、退出码、异常检查和引用清理的 Windows 回归程序，再声明构建/运行证据。
8. 若平台需要承载不可信代码，改为受管子进程和版本化 IPC，不在易语言宿主内直接加载。

## 12. 证据索引

| 主题 | 证据位置 |
|---|---|
| DLL 入口、版本、命令和 6 个类型 | `JYEPythonFne/JYEPythonFne/JYEPythonFne.cpp` |
| 易语言回调、转换、对象、容器、GIL、trampoline | `JYEPythonFne/JYEPythonFne/EiFun.cpp` |
| Python 包装、解释器和引用操作 | `JYEPythonFne/JYEPythonFne/EPython.cpp`、`EPython.h` |
| Python C API 函数指针和动态绑定 | `JYEPythonFne/JYEPythonFne/PyDll.cpp`、`PyDll.h` |
| 元数据、宿主通知和内存辅助 | `JYEPythonFne/JYEPythonFne/Elib.cpp`、`Elib.h` |
| 易语言 ABI 原始结构 | `JYEPythonFne/JYEPythonFne/elib/lib2.h`、`mtypes.h`、`lang.h` |
| 导出 | `JYEPythonFne/JYEPythonFne/JYEPythonFne.def` |
| 支持库构建 | `PythonFne_vs2019/PythonFne_vs2019/PythonFne_vs2019.vcxproj` |
| 直接链接 Python 的示例构建 | `PythonFne_vs2019/PythonTest/PythonTest.vcxproj` |
| C API 示例 | `PythonFne_vs2019/PythonTest/PythonTest.cpp` |
| Python 示例模块 | `PythonFne_vs2019/PythonTest/dom.py`、`py/dom.py`、`py/HmyPath.py` |
| 功能声明 | `PythonFne_vs2019/PythonFne_vs2019/更新说明.txt` |

---

**本次范围声明**：只更新系统工程平台根目录 `ARCHITECTURE.md`，将其从错误的 `eoalib/OpenAL`
审计改为 `python-fne` 全量分段事实审计；未修改参考仓库源码、参考仓库文档、测试、配置或 Git 历史。

---

# Prefect 工作流编排、插件与执行制品架构核对（2026-08-21）

## 1. 研究对象与证据边界

本轮选择源码参考库中尚未发现项目级 `ARCHITECTURE.md` 的开发工具/插件项目：
`/Users/hekunhua/Documents/Agent/github 源码参考/12_工作流编排/prefect`。
Prefect 是包含任务/流程执行引擎、插件入口点、部署 YAML 步骤、worker/runner 进程管理、bundle 文件制品、CLI、构建链和 docs 的 Python 工作流编排框架。

本轮不调用 MCP/Hermes，不安装依赖、不启动 Prefect Server、不执行测试或构建。已先尝试 CodeGraph；目标参考仓库没有 `.codegraph/` 索引，查询明确返回不可用，因此没有把 CodeGraph 结果当作源码证据。后续结论来自源码、测试、`pyproject.toml`、GitHub Actions 和 docs 的分段读取；“测试文件存在”与“本机运行通过”严格区分。

## 2. 项目模型与主要调用链

```text
用户 flow/task 定义 -> Flow/Task/Deployment 模型
  -> FlowRun/TaskRun 状态与输入依赖 -> Flow/Task Engine
  -> TaskRunner (thread/process/distributed)
  -> Runner/Worker -> FlowRunExecutor -> ProcessManager + control channel
  -> 独立 flow-run 进程 -> server/client 状态、日志、事件和终态

插件包 -> entry point: prefect.plugins -> pluggy PluginManager
       -> setup_environment / database params hooks -> 环境变量与诊断摘要

prefect.yaml -> build/push/pull 有序步骤 -> 模板解析 -> 可选 requires 自动安装
flow bundle -> 函数/上下文/依赖 + 可选文件 -> SHA-256 内容寻址 zip
            -> files/{hash}.zip -> bundle executor -> FlowRunExecutor
```

核心持久化模型是 `FlowRun`/`TaskRun` 与状态转换，而不是普通函数调用包装器。`BaseTaskRunEngine` 负责参数解析、缓存键、结果持久化、重试/失败状态和取消检查；`TaskRunner` 负责提交 future 和并发执行，任务状态仍由任务引擎处理。每次流程执行由 runner 创建一个 `FlowRunExecutor`，通过 `ProcessStarter` 启动子进程，并在进程仍存活时登记 `ProcessHandle`。

## 3. 插件与扩展边界

- `prefect.plugins` 是 pluggy 启动插件的公开门面。插件由 `prefect.plugins` entry-point group 发现，API 版本为 `0.1`，加载时检查 `PREFECT_PLUGIN_API_REQUIRES`，但非法版本声明只记录 debug 日志并继续加载，属于 best-effort 版本围栏。
- `prefect.collections` 是集合包导入入口点。`load_prefect_collections()` 使用进程内全局缓存，逐项捕获异常，并在日志尚未初始化时直接 `print` 警告；单个集合失败不会拖垮全部导入，但没有统一卸载或注册状态回滚。
- `run_startup_hooks()` 根据 enabled、allow、deny、safe mode、strict 和 setup timeout 调度插件。safe mode 只加载不执行 hook；正常模式在总超时范围内调用 `setup_environment`，再把 `SetupResult.env` 写入当前进程环境；strict 模式对失败或 required 结果退出。

插件 API 以 `HookContext`、`SetupResult`、`HookSpec` 集中定义契约，公共模块对 pluggy 实现懒加载。边界仍不完整：插件初始化在宿主进程内执行，可影响当前进程和子进程；超时不能强制终止已开始的同步工作；没有每插件独立进程、资源租约、取消句柄或反向清理 hook。平台若吸收该模型，应把第三方初始化放入受控提供者/子进程，明确 secrets 不入日志、每插件 deadline、取消和清理协议。

## 4. 部署、构建与步骤执行

`RunnerDeployment` 是 Pydantic 部署模型，承载名称、版本、entrypoint、参数 schema、schedule、work pool、job variables 和 storage。`prefect.yaml` 将 build、push、pull 表示为顺序步骤：步骤通过完全限定函数名导入，先解析 block、variable 和环境模板，再调用函数，输出按 step id 合并给后续步骤。

`deployments.steps.core` 的 `requires` 在导入失败时可以安装包后重新导入目标函数。`run_shell_script` 逐行启动子进程，默认使用参数化 exec，显式 `shell=True` 或 Windows 平台使用 shell，也允许从当前环境展开变量。这是构建/部署执行边界，不是安全沙箱：命令、目录、环境、网络和安装包来源必须由部署拥有者信任。步骤事件在解析前保留模板字符串以避免把已解析 secret 放入事件，但 stdout/stderr 仍可能暴露命令输出中的敏感数据。

构建使用 Hatchling + `versioningit`。`hatch_build.py` 在 sdist/wheel 构建时可要求两个 UI bundle 的 `index.html` 存在；`pyproject.toml` 显式包含 SDK Jinja 模板和生成的 `_build_info.py`。GitHub Actions 以 uv lock、Python 3.10–3.14、SQLite/Postgres、分组 pytest、pre-commit 和 pyright 组成矩阵；这是项目声明的 CI 覆盖，不是本机验证结果。目标目录未发现根 `Makefile` 或 `mkdocs.yml`，文档目录通过 MkDocs 相关依赖和现有配置生成 API 页面。

## 5. 进程、线程、取消与资源所有权

- `ThreadPoolTaskRunner` 和 `ProcessPoolTaskRunner` 使用 future 暴露结果；线程 runner 通过 `copy_context()` 传递上下文，源码文档明确指出循环中频繁修改 context 可能导致线程和文件描述符增长。
- `FlowRunExecutor` 先向服务端 propose submitting，再让 starter 通过 `task_status.started(handle)` 提前交付句柄，登记到 `ProcessManager`，等待子进程退出，记录 attempt conclusion，最后移除登记并按退出码决定 crashed。
- `ProcessManager` 维护 `flow_run_id -> ProcessHandle` 映射和异步锁；上下文退出时遍历并 kill 剩余进程。POSIX 先 SIGTERM 后 SIGKILL，进程组 leader 使用 `killpg`；Windows 使用控制事件/平台 API。强杀、系统崩溃或管理器自身异常仍可能留下外部资源，接入平台时还需 orphan 扫描和资源清单。
- `engine.py` 对 Abort、Pause 和已被编排器处理的 termination 以退出码 0 结束；未被证据确认的终止继续传播，普通异常退出码 1。异步 flow 在子进程主线程事件循环中运行，以保证 SIGTERM bridge 可用。
- `FlowRunExecutorContext` 以 `AsyncExitStack` 固定 client、process manager、limit manager、event emitter、run task group、cancellation manager 的退出次序。该顺序是架构事实，但不能推导第三方 flow 代码、Docker/Kubernetes 资源或外部进程已完全回收。

## 6. Bundle 制品与可复现性

`ZipBuilder` 将 base directory 内文件按相对路径排序，以统一斜杠把路径、文件模式、大小和内容写入 SHA-256；zip 写入和哈希在单次读取中完成，storage key 为 `files/{hash}.zip`。这是规范化文件集合哈希，不是 zip 原始字节哈希；压缩器元数据变化不等价于内容变化。实现只对超过 50 MiB 的 zip 发 warning，没有硬性拒绝、输入总量预算或构建事务提交。

临时 zip 目录由调用方显式 `cleanup()` 删除，未调用 cleanup 时不能由 `ZipBuilder` 自动保证释放。`execute_bundle_from_file()` 直接读取 JSON，核心字段交给 `FlowRun` 模型校验，随后进入 `FlowRunExecutorContext`；它是执行入口，不是制品签名或来源验证器。bundle 依赖可来自 `uv pip freeze`，launcher 存在时可能跳过 freeze；测试覆盖这些分支，但没有证明真实上传下载、篡改检测、强杀后临时目录回收或跨平台重放。

## 7. 测试与 docs 质量审计

测试结构覆盖插件入口点缓存/异常、bundle 文件 key 与 include_files、runner/process manager、task/flow engine、deployment steps、server、worker、CLI 和多数据库矩阵。`test_plugins.py` 主要 mock entry points；bundle 测试 mock `uv pip freeze`；process manager 测试大量 mock `os.kill`；deployment tests 覆盖 shell step、模板解析和自动安装路径。它们能证明控制流和错误分支存在，但不能替代真实插件包、真实外部命令、真实进程组、远端 storage、包仓库和 crashed worker 验收。

README 说明快速启动、server、serve deployment 和 Cloud；插件 docs 说明 opt-in、allow/deny、safe mode、strict、API 版本和 entry point；worker docs 说明 Pydantic job configuration、base job template、credentials 和模板变量；YAML docs 说明 build/push/pull 和 step 输出传递。主要缺口是：插件同进程执行和总超时语义没有形成资源安全契约；`requires` 自动安装和 shell step 没有统一沙箱策略；bundle 文档没有充分强调规范化 hash、临时目录 owner、50 MiB warning、签名缺失和强杀残留；丰富的 CI 矩阵也不等于本轮在当前环境运行通过。

## 8. 对本平台的吸收约束

1. 插件入口必须经过稳定能力契约、版本范围、allow/deny、safe mode 和审计日志；第三方插件默认进程隔离，不能以导入成功代替初始化成功。
2. 环境变量、数据库连接参数、模板解析和 shell/build 步骤必须声明敏感数据策略、调用者权限、网络范围、deadline、取消和输出脱敏规则。
3. 任务/流程执行采用显式状态机和 attempt evidence；启动进程必须先登记 owner，再允许取消；终态区分编排器已处理、正常退出、非零退出和未确认终止。
4. 线程池、进程池、外部命令和 worker 均要有并发/句柄/内存/输出上限、优雅停止、强杀、join/reap 和 orphan 回收，不能从 `shutdown` 或上下文管理器名称推断资源已清理。
5. 内容寻址制品必须区分规范化内容哈希、压缩文件摘要、签名/来源证明和临时制品生命周期；warning 不能替代硬预算和提交回滚。
6. 测试验收分为 mock 单元、真实本地进程、真实数据库/服务、跨平台 worker、制品上传下载和文档构建等级。本节结论仅为 L0/L1 静态核对，未声明 Prefect 在当前环境运行通过。

---

# espeechengine 分段审计

## 1. 范围、来源与 CodeGraph 结果

审计对象是只读参考目录：
`/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/espeechengine`。
本节只修改当前仓库根 `ARCHITECTURE.md`，没有修改参考仓库。参考仓库 HEAD 为
`2c92b9eb99bf77d834f5291c7d9cc842ca06aaca`，提交为“初始化仓库”；未在 Windows/MSBuild、易语言 IDE 或真实 Speech SDK 环境运行。

先尝试 CodeGraph：目标目录没有 `.codegraph/`，返回未建立索引，因此没有可用的符号图、调用图或影响分析证据。以下结论来自分段源码、工程文件、导出定义、测试/文档清单和 Git 现场读取。目标仓库只有一份 `ARCHITECTURE.md`，没有测试目录、测试工程、CI 配置或其他说明文档。

## 2. 分段事实审计

### 2.1 语音引擎与 COM

- 元数据声明文本转语音、WAV 输出、停止/暂停/恢复、音量、语速、语音库枚举/选择，以及中文/英文语音识别、训练和常用词加入。
- `espeechengine_cmdDef.cpp` 的 17 个入口只有取参代码或空函数；没有 `CoInitialize[Ex]`、`CoUninitialize`、`CoCreateInstance`、`ISpVoice`、`SpVoice`、SAPI 头文件、Speech SDK 类型或 COM 智能指针。
- “依赖 Speech SDK 5.1 或 Office”只是 `LIB_INFO` 的说明字符串和命令说明，不是可验证的链接依赖、安装探测、COM 初始化或后端实现。

### 2.2 音频、WAV、设备与播放控制

- 没有 `waveOut*`、WASAPI、DirectSound、MMDevice、音频设备枚举、采样缓冲、WAV 写入器或音频格式转换代码。
- `SpeekToWav` 只读取数据类别、发音数据和输出文件名；没有创建文件、写 RIFF/WAV、提交临时文件或回滚部分输出的路径。
- 停止、暂停、恢复、音量和语速入口没有设备/播放对象状态，也没有边界校验或返回值写入；后台播放和超时仅存在于参数说明。

### 2.3 回调、事件与线程

- 宿主通知链真实存在：`ProcessNotifyLib()` 保存 `PFN_NOTIFY_SYS`，首次通知通过 `NRS_GET_PRG_TYPE` 更新 `s_isDebug`，`NotifySys()` 可转发宿主通知；这不是语音播放回调，也不产生识别事件。
- `DTP_LABEL` 的播放开始/结束标签和 `ESpeechReco` 的识别事件只在元数据中声明；没有事件源、事件队列、回调注册表、取消订阅、线程安全规则或回调线程归属。
- 源码中没有 `CreateThread`、线程池、`std::thread`、消息循环、等待句柄或异步 worker。后台播放、等待超时和事件延迟没有实现证据。
- `SetUserSysNotify()` 只是进程内静态函数指针替换，未见并发保护、注销协议或生命周期绑定。

### 2.4 句柄、释放与 DLL 生命周期

- `DllMain` 的四个分支均为空；`NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE` 和 `NR_DELAY_FREE` 分支也为空，没有语音对象、识别对象、设备、线程、回调、文件或 COM 引用的释放路径。
- `StartSpeech`/`CloseSpeech`、`SetUpSR`/`ReleaseSR` 是命令契约，但当前没有对象句柄或状态结构；`ControlCreate_ESpeechReco()` 固定返回 `HUNIT=0`。
- `PropPopDlg_ESpeechReco()` 无条件解引用 `pblModified`，空指针输入可能崩溃；`PropGetDataAll` 返回 0，`PropGetData` 对属性不填值却可返回 TRUE。
- 不能声称支持安全卸载、热重载、幂等关闭或异常清理。未来实现应先停止新调用、排空/取消播放和识别、注销事件、关闭设备/线程、释放 COM 引用，再允许 DLL 卸载。

### 2.5 错误与诊断

- 17 个命令均为 `void` ABI，布尔结果必须写入 `pRetData`；当前实现没有写返回值，因此调用方拿到的结果不能证明成功或失败。
- 没有 `HRESULT`、SAPI 错误、设备错误、文件错误、超时错误码、阶段字段、重试性或关联标识的转换层，也没有日志路径。
- 元数据把失败返回假、未安装 Speech SDK 返回假写成预期语义，但实现没有对应检测和错误分支；这属于契约/实现差异，不是运行保证。

### 2.6 ABI、导出与工程元数据

- `Source_espeechengine.def` 只导出 `GetNewInf`；`GetNewInf()` 返回静态 `LIB_INFO`，GUID 为 `4AA6F3ADE9264fbe8B618A1FCD60364F`，版本为 `2.0.0`，Windows/GBK 元数据和 17 项命令表由宏清单生成。
- `espeechengine_cmd_typedef.h` 是命令单一清单，分别展开为 `CMD_INFO`、函数声明、函数指针表和静态库函数名表；序号、参数起始偏移和函数表顺序是 ABI 绑定点。
- 动态 Win32 配置设置 `__E_FNENAME=espeechengine`、`.fne` 和 `.def`；x64 动态配置未设置同样宏，也未设置 `ModuleDefinitionFile`。静态库 Win32 设置 `__E_STATIC_LIB`/`__E_FNENAME`，x64 配置缺少这两个宏且预编译头设置不同。
- `elib` 的通知接口使用 `DWORD` 承载回调和地址参数；在 x64 下指针宽度、函数指针转换和宿主 ABI 必须专门验证。`NL_GET_DEPENDENT_LIBS` 返回空依赖列表，与说明字符串宣称依赖 Speech SDK/Office 不一致。

## 3. 实现与元数据差异矩阵

| 元数据/说明承诺 | 实现证据 | 裁决 |
|---|---|---|
| 文本转语音与等待超时 | `Speek` 仅取参 | 未实现 |
| WAV 文件输出 | `SpeekToWav` 仅取参 | 未实现 |
| 停止/暂停/恢复 | 空函数 | 未实现 |
| 音量/语速/语音库 | 仅取参或空函数 | 未实现且无校验 |
| 识别创建/释放/训练/加词 | 空函数 | 未实现 |
| 识别组件与事件 | 创建返回 0，属性/事件占位 | 只有接口形状 |
| Speech SDK/Office 依赖 | 说明字符串；依赖列表为空 | 元数据与工程不一致 |
| 布尔成功/失败返回 | `pRetData` 未写入 | 契约未兑现 |
| 后台线程、回调和释放 | 无线程、设备、回调或释放实现 | 说明无运行时依据 |

## 4. 测试与文档质量审计

- 测试：参考仓库没有 `test*` 文件、测试目录、测试工程、CI 或自动化验证入口；不存在已通过的 ABI 快照、导出表核验、COM 初始化、设备矩阵、回调竞态、强杀回收或 x86/x64 回归证据。
- 现有 `espeechengine/ARCHITECTURE.md` 已区分契约层与执行层，列出 17 条命令、3 个数据类型、工程配置、导出入口和未验证项；这些内容与本轮分段读取总体一致。
- 文档局限是源码文件中文注释/元数据在当前读取环境中大量乱码，且“支持库说明”容易被误读为功能实现；缺少逐项 COM、音频设备、线程回调、句柄释放和错误 ABI 的独立证据表。
- 文档应持续使用“元数据声明”“源码存在”“未发现实现”“未运行验证”四种措辞；不能以命令名、返回类型或 Windows 标志推断 SAPI、COM、设备或异步能力。

## 5. 平台接入裁决与最小验收顺序

当前 `espeechengine` 只能作为“易语言支持库 ABI/元数据骨架”参考，不能作为可用语音引擎、音频后端或识别组件接入。若后续实现，验收顺序为：

1. 在 Windows + VS v141 分别构建 Win32 DLL、Win32 静态库和 x64 配置，核对宏、`.fne`、`.def`、符号表和结构体布局。
2. 在隔离环境验证 Speech SDK/SAPI 版本、COM apartment、线程归属、语音库和默认音频设备；记录真实 HRESULT 与设备错误。
3. 为每条命令补参数计数/指针/范围校验，确保所有 `SDT_BOOL` 都写 `pRetData`，并定义结构化错误和可重试性。
4. 为播放、WAV 输出、停止/暂停/恢复、超时和标签回调建立状态机、取消协议、线程安全规则和输出临时文件提交/回滚。
5. 为识别组件实现句柄、属性序列化、事件注册/注销、回调线程规则和 `HUNIT` 生命周期，覆盖空指针与重复释放。
6. 注入设备断开、SDK 缺失、COM 初始化失败、回调异常、超时、宿主卸载和进程强杀，确认线程、COM 引用、设备句柄、文件和回调无残留。

本次没有执行上述 Windows 验收；结论是源码静态审计结论，不是运行通过声明。

---

# eword2000 Word 自动化边界研究

## 1. 研究对象与证据边界

研究对象为外部只读参考源码：
`/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/eword2000`。
本节专门补齐 `eword2000`，不把 Excel 章节或 Word 文件解析器的事实复用为 Word COM 事实。
参考仓库 HEAD 为 `3f9cca2019cc6ef8c269260e1c52cb17454665e1`，只有初始化提交；其项目根已有
`ARCHITECTURE.md`，但没有 tests/test、docs、build、CI、README 或自动化验证入口。当前 macOS 环境未运行
Windows/Visual Studio/易语言/Word 链路，以下“存在”均为 L0 静态证据。

核心结论：`eword2000` 是易语言 `WORD2000支持库` 的 ABI/对象元数据骨架，不是已实现的 Word COM
自动化库。它声明 Word 2000/XP/2003 或更高版本为运行前提，但源码没有证明 Word 已连接、对象已创建、
命令已执行或文档已保存。

## 2. 装载、对象与事件事实

- 动态库由 `Source_eword2000.def` 仅导出 `GetNewInf`；返回静态 `LIB_INFO`，版本为 `2.0.0`，GUID
  为 `F30A56A231354a4a81AB13B54EF21665`，要求易语言系统/核心支持库 `3.7`，含 33 个命令、4 个
  数据类型、0 个常量，依赖列表为空。空依赖列表不等于 Word/COM 运行时已可用。
- `EWORD2000_DEF` 是命令编号、函数名、参数和元数据的单一宏源，生成 33 个命令函数及函数表。
  命令体中 17 个为空，其余主要只是读取 `pArgInf` 到局部变量；没有写 `pRetData`，也没有 Word API 调用。
- 对象模型只有声明：`WordApp`、`WordDocuments`、`WordShapes` 和 `Units`。前 3 个是 Windows
  单元/函数提供者，`Units` 是枚举。`WordApp` 的事件元数据有 6 项：文档关闭、打印、保存、打开、
  新建和退出；事件参数包含文档对象以及可写的取消布尔值。但没有事件接收器、连接点、回调桥、
  `Advise`/`Unadvise` 或事件解绑实现，不能把事件表当作可触发事件。
- `ControlCreate_*` 返回 `0`；`PropGetDataAll_*` 返回 `0`；属性对话框直接解引用 `pblModified`
  后返回 `FALSE`，未证明空指针安全；属性和设计器回调主要是模板返回值。对象属性、事件和对象返回
  类型是声明式 ABI，不是运行对象或持久化状态。

## 3. COM、线程、句柄与 ABI 分段裁决

### 3.1 COM 与对象所有权

全文和工程文件均未发现 `CoInitialize`/`CoInitializeEx`/`CoUninitialize`、`CoCreateInstance`、
`GetActiveObject`、`CLSID`/`IID`、`#import`、`IUnknown`/`IDispatch`、`VARIANT`/`BSTR`/`SAFEARRAY`、
`Invoke`、`HRESULT`、`IErrorInfo` 或 Word 类型库。`Create`、`Release`、`Quit`、`Open`、`SaveAs` 只是
易语言命令名，不能解释为 COM 创建、引用释放、Application.Quit、文件提交或回滚。

未来实现必须把 Word 对象集中放入唯一 provider 边界，定义 Application/Document/Selection/Shapes
对象的 owner、引用计数、跨命令不透明句柄、创建/接管标记和失效校验。公共 ABI 不得传递 COM 指针、
`IDispatch*` 或宿主对象地址；`VARIANT`、`BSTR`、`SAFEARRAY` 和异常必须在边界内转换并由分配方释放。

### 3.2 线程与事件

`DllMain` 的进程/线程 attach/detach 均为空；项目未创建线程、线程池、消息泵、同步原语或后台任务，
也没有 COM apartment 模型。因此不能声称命令线程安全、事件回调线程、跨线程 COM marshaling 或消息
循环已存在。若实现进程内自动化，默认应由单一 STA worker 初始化 COM、拥有全部 Word 对象并泵送消息；
命令和事件通过有界队列进入该 worker，关闭先停止新调用、解绑事件并等待队列排空。需要强制取消、隔离
崩溃或防止 Word 卡死时，应使用受管子进程而不是把线程终止写成安全取消。

### 3.3 句柄、释放与进程残留

本项目只有宿主 `HUNIT`、`HWND/HMENU` 等 ABI 参数和声明式复合对象，没有对象表、引用计数、文件句柄、
进程句柄、PID、临时目录或 Word 进程控制。`NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NR_DELAY_FREE`
和 `DllMain` detach 没有业务清理；`fnshare.cpp` 保存的系统通知回调也没有在卸载时清空。不能证明
Release 顺序、重复释放、宿主卸载或 Word 进程零残留。

未来释放顺序固定为：拒绝新命令 → 停止事件并 `Unadvise` → 排空/取消 worker → 关闭仅由本库创建且已
明确保存决策的文档 → 释放 Selection/Range/Shapes/Document 临时引用 → 仅退出本库创建的 Word 实例
→ 释放 Application → 在同一 COM 线程 `CoUninitialize` → 有界等待并对账 PID、窗口、线程、句柄、临时
文件和输出制品。不能无条件关闭用户已有 Word，也不能以线程返回替代进程残留证据。

### 3.4 异常与 ABI

命令没有参数计数/类型防御、`HRESULT` 检查、统一错误码、超时、取消、失败回滚或异常保护；C++ 异常
不得穿过 `PFN_EXECUTE_CMD(PMDATA_INF, INT, PMDATA_INF)`。`MDATA_INF`、`HUNIT`、`HGLOBAL`、文本指针和
函数指针服从 `elib/lib2.h` 的历史 ABI；`MAKELONG(0x10030, 0)` 对象返回值以及 `DWORD`/`INT` 承载的
指针不能视为 x64 安全句柄。必须逐配置核对调用约定、结构布局、默认文本的长度/编码、对象句柄宽度、
输出槽所有权和导出表，错误须转换为结构化结果而非 `FALSE`、0 或未初始化返回槽。

## 4. build、tests 与文档审计

- `eword2000.vcxproj` 和静态库工程提供 Debug/Release × Win32/x64，工具集 `v141`、Windows SDK
  `10.0.15063.0`、Unicode。仅 Win32 设置 `.fne`、`__E_FNENAME=eword2000` 和 `.def`；x64 缺少
  对称的宏、`.fne`/`.def` 配置，静态 x64 还启用不存在的 `pch.h`。这些是配置风险，不是已运行的构建失败证据。
- 工程未声明 COM/Word 类型库、`ole32`/`oleaut32` 或外部库；`m_szzDependFiles=NULL` 只表示支持库
  元数据未声明依赖，不能替代 Word 安装、注册、位数和版本预检。
- 仓库没有测试目录、测试工程、CI、build 脚本或 Word 冒烟脚本。本轮未执行 MSBuild、导出解析、
  `GetNewInf`、对象创建、COM 事件、异常/释放、x86/x64 ABI、保存失败、Word 卡死或进程残留测试。
  最低验收应覆盖创建/接管边界、重复 Release、文档打开/保存/取消、事件取消参数、事件解绑、STA 消息泵、
  HRESULT/异常映射、超时/强杀、PID 与句柄回收、x86/x64 导出和真实 Word 版本矩阵。
- 与本文重复的通用规则以现有 ABI、资源所有权和隔离原则为准；本节只保留 `eword2000` 的证据和差异。
  Excel 章节只描述 Excel，不能覆盖或替代 Word；ADO 章节的 COM 反例与本节一致，但不能证明 Word COM
  已实现；Word 文件解析器章节描述的是离线解析，不是 Office 自动化。以上裁决消除“声明式对象/事件 =
  已实现 COM”以及“空依赖 = 无运行时依赖”两类冲突。

当前结论：`eword2000` 只能作为易语言支持库 ABI、Word 对象/事件元数据和未闭合资源边界的静态参考；
在 Windows + Word + Visual Studio 的真实构建、调用、故障注入和零残留证据产生前，不得把它登记为
Word 自动化 provider 或可用文档能力。

---

# vclbase VCL 控件支持库源码与元数据审计

## 1. 范围与证据边界

研究对象是只读参考仓库：`/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/vclbase`。当前 HEAD 为 `a0b89a1e8b5c0d38c4557a97fff468c3a2368763`（2022-12-19），远程为 `https://gitee.com/JYtechnology/vclbase.git`。本轮只修改本仓库根 `ARCHITECTURE.md`，不修改外部参考仓库。

已尝试用当前项目 CodeGraph 查询 `vclbase`、VCL 对象、窗口、消息、控件、事件、线程、句柄、释放、ABI、tests 和 docs。该外部仓库不在当前 CodeGraph 索引中：首次查询命中本项目无关网页解析符号，第二次返回无相关代码。因此下文以外部仓库当前磁盘源码、头文件、Visual Studio 工程和其根 `ARCHITECTURE.md` 的分段读取为依据，不把 CodeGraph 查询或未执行测试写成证据。

`vclbase` 是易语言 Windows VCL 控件支持库的 ABI、元数据和回调骨架，不是已完成的 Delphi/VCL 控件运行库。真实实现集中在库注册、命令/参数目录、控件属性/事件目录、接口选择器和模板回调；35 个命令函数及 18 个实际可视化数据类型的创建、属性存取、消息/事件桥接仍大面积为空或默认返回。

## 2. 对象、窗口、控件与元数据

`vclbase_dllMain.cpp` 的 `GetNewInf()` 返回静态 `LIB_INFO`：GUID 为 `{6793B367-79D9-43F3-88B7-5EB6CF04B618}`，版本 `1.0.2`，要求易语言系统 `4.0`、核心支持库 `4.5`，平台为 Windows、语言为 GBK。`Source_vclbase.def` 只显式导出 `GetNewInf`。

`vclbase_cmd_typedef.h` 的单一 `VCLBASE_DEF` 宏同时生成命令原型、元数据、函数表和静态函数名数组，共索引 `0..34` 的 35 项。索引 9、10、34 都名为 `Open`，通过索引拼接符号名；索引和参数起始偏移因此是 ABI 兼容边界。`vclbase_const.cpp` 的数组容量为 1，但常量计数为 0，不能宣称提供常量。

`g_DataType_vclbase_global_var` 有 20 个表项，其中索引 0、12 是隐藏占位，索引 1–11、13–19 是 18 个实际类型：`VCLForm`、`VCLPanel`、`VCLGrid`、`VCLComboBoxEx`、`ColorDialog`、`FindDialog`、`LabeledEdit`、`MaskEdit`、`VCLTBitBtn`、`VCLRadioGroup`、`ValueListEditor`、`HotKey`、`OpenPictureDialog`、`VCLScrollBox`、`VCLRbSplitter`、`VCLSplitter`、`SingleInstance`、`GIFButton`。属性表通常以 left/top/width/height/tag/visible/disable/MousePointer 八项固定窗口属性开头，再追加控件属性；事件表描述表格移动/选择、组合框编辑、对话框显示关闭、编辑变化、热键等事件。

每个类型的 `vclbase_GetInterface_<Type>` 都能返回创建、属性、按键需求和通知接收器等函数指针。但所有 `vclbase_ControlCreate_*` 函数都只是 `HUNIT hUnit = 0; return hUnit;`：没有 VCL 对象创建、`HUNIT` 映射、父子关系登记或销毁闭环；“Windows 单元/容器/函数提供者”是宿主分类，不是已存在的对象实例。

## 3. 消息、属性与事件实现差异

属性元数据与真实属性实现分离：`PropUpDate_*` 基本直接返回 `TRUE`；`PropGetDataAll_*` 返回 `0`；`PropChanged_*` 只保留模板并最终返回 `FALSE`；`PropGetData_*` 对索引 0 空分支后返回 `TRUE`，没有填充 `UNIT_PROPERTY_VALUE`，存在“成功但无值”的假成功风险。`PropPopDlg_*` 无条件执行 `*pblModified = false`，没有空指针检查，宿主若传 `NULL` 可直接崩溃。

事件方面，`EVENT_INFO2`/参数数组只注册名称、参数和返回类型，没有发现 VCL 窗口过程、事件订阅、消息转换或向易语言宿主投递事件的实现。接口选择器中的 `ITF_MSG_FILTER` 保留模板分支并返回 `NULL`，不能写成已实现窗口消息过滤桥。`NU_GET_CREATE_SIZE_IN_DESIGNER` 实际返回 `0`，不写默认宽高。`NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NR_DELAY_FREE`、`NL_IDE_READY` 等通知分支也没有资源或生命周期动作。

## 4. 命令 ABI 与返回值

35 个命令入口统一使用：

```cpp
void vclbase_<EnglishName>_<index>_vclbase(
    PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf
)
```

实现通常只从 `pArgInf[1..n]` 读取数据到局部变量，许多函数体完全为空。没有 `nArgCount`、`pArgInf`、数据类型或输出指针校验，没有 `GetWndPtr`/`NotifySys` 控件查找，没有设置 `pRetData`，也没有文本/字节集输出的宿主分配与释放。因此 `CMD_INFO` 的返回类型和成功/失败说明是契约元数据，不是命令行为证据。

## 5. 线程、句柄、内存与释放

没有发现 vclbase 自己创建线程、消息循环、定时器或异步队列的实现；`DllMain` 的四个 attach/detach 分支均为空，也没有 `HUNIT` 实例表、窗口子类、VCL 对象销毁、延迟释放或卸载收口路径。`elib/fnshare.cpp` 只保存宿主 `PFN_NOTIFY_SYS`，没有锁、引用计数、回调注销或并发约束。

`fnshare.h` 的 `ealloc`/`efree`、文本/字节集复制和数组辅助依赖宿主内存服务。`efree` 将指针转换为 `DWORD` 传给 `NotifySys`，在 64 位进程存在指针截断风险；通知参数和函数指针也通过 `DWORD` 承载。`untshare.h` 的序列化和 `LoadIco` 主要是注释/占位；`GetWndPtr` 只按窗体/单元 ID 请求宿主指针，不拥有或释放对象。

当前不能证明句柄状态机、线程归属、消息线程切换、重复释放保护、父窗口销毁联动或 DLL 卸载安全性。后续实现必须先明确 `HUNIT`、`HWND`、VCL 对象、属性缓冲区、事件回调和宿主分配内存的唯一 owner 与关闭顺序。

## 6. 工程元数据漂移

- 动态库 Win32 定义 `__E_FNENAME=vclbase`，输出 `.fne` 并链接 `Source_vclbase.def`；动态库 x64 未配置同名宏、`.fne` 目标扩展或模块定义文件。
- 静态库 Win32 定义 `__E_STATIC_LIB;__E_FNENAME=vclbase`；静态库 x64 只有 `_DEBUG;_LIB` 或 `NDEBUG;_LIB`，与共享源码所需条件宏不对称。
- 两个工程声明 Windows SDK `10.0.15063.0`、工具集 `v141`、Unicode，但源码/库语言元数据仍使用 GBK/`LPSTR` 语义；编码、结构布局和调用约定未在 Windows 验证。
- `LIB_INFO` 的依赖串为 `NULL`，不能推导 Delphi/VCL 或 `GIFImage` 依赖已经随仓库提供；库说明中的 `GIFImage` 只是定位文本，仓库没有对应 VCL 实现源码或资源。

## 7. Tests 与 docs 清晰度裁决

外部仓库没有 `tests`/`test` 目录、测试工程、CI、README、构建说明或示例程序。外部根 `vclbase/ARCHITECTURE.md` 的首轮结论方向正确：已区分 20 表项/18 实际类型、35 个命令、空创建回调、x64 配置差异和未执行 Windows 验证；文档中“支持库”一词必须始终附带“元数据/ABI 骨架”限定，避免把接口数量误读成可运行能力。

| 领域 | 元数据/声明 | 真实实现 | 证据 |
|---|---|---|---|
| VCL 对象/窗口 | 18 类型、属性、创建签名 | 无对象创建或窗口句柄桥 | 源码静态确认 |
| 消息 | `NL_*`、`NU_*`、`ITF_MSG_FILTER` 常量/接口 | 通知模板；消息过滤返回 `NULL` | 源码静态确认 |
| 控件 | 类型名称、设计器参数 | `ControlCreate_*` 返回 0 | 源码静态确认 |
| 事件 | `EVENT_INFO2` 名称/参数/返回类型 | 无窗口过程或事件投递 | 源码静态确认 |
| 线程/释放 | Windows 类型和宿主内存 API | 无自有线程、owner、销毁或卸载闭环 | 源码静态确认 |
| ABI | `GetNewInf`、`LIB_INFO`、命令/回调原型 | 未核对导出、布局、位数和真实调用 | Windows 验证缺失 |
| tests | 无测试目录/CI | 无行为证据 | 未执行 |

本轮未执行 Visual Studio/MSBuild、`dumpbin`、Windows DLL 装载、易语言 IDE 设计器拖放、命令调用、属性序列化、事件触发、x64 构建或卸载测试。最终裁决：`vclbase` 具备可继续施工的 ABI 元数据骨架，但不能写成已实现 VCL 控件支持。

## 8. 后续验收门槛

- Win32 动态库构建并核对 `.fne`、`GetNewInf` 导出、结构布局和命令函数表；x64 先修复或明确宏、`.def`、目标扩展和 PCH 差异。
- 每个控件补齐创建、属性快照/实时读取、属性写入、消息过滤、事件投递和销毁，并用真实宿主调用验证返回值。
- 对 `pArgInf`、`nArgCount`、输出指针、`pblModified`、属性缓冲区和通知函数指针做 ABI 可空性与位数校验。
- 建立 `HUNIT`/`HWND`/VCL 对象/回调/宿主内存 owner 表，验证关闭、重复关闭、父窗口销毁、卸载和异常路径无悬挂指针。
- 增加 Windows 构建与行为测试 CI；测试真正运行前只记录“源码存在/路径可达”，不记录“通过”。

---

# exmlrpc 分段源码审计：ABI 外壳与未落地的远程协议

## 1. 定位、范围与 CodeGraph 结果

目标源码位于本地只读参考仓库：

`/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/exmlrpc`

本轮按编码、HTTP/传输、请求/响应、超时、错误、线程、句柄/释放、ABI、tests、docs 分段读取了：
`exmlrpc_cmd_typedef.h`、`exmlrpc_cmdDef.cpp`、`exmlrpc_cmdInfo.cpp`、`exmlrpc_dtType.cpp`、
`exmlrpc_dllMain.cpp`、`include_exmlrpc_header.h`、`elib/lib2.h`、`elib/fnshare.h/.cpp`、
`Source_exmlrpc.def`、动态/静态 Visual Studio 工程和参考 `ARCHITECTURE.md`。

目标目录没有 `.codegraph/` 索引；已尝试执行 CodeGraph 查询
`exmlrpc XML-RPC encoding HTTP request response timeout error thread handle release ABI tests docs`，
工具明确返回没有可用索引。因此以下结论来自逐文件静态读取，不是 CodeGraph、构建、运行时或 Windows 宿主测试证据。

**总裁决：`exmlrpc` 当前可见提交是易语言远程服务支持库的 ABI 注册壳和命令接口骨架，
不是已落地的 XML-RPC/HTTP 协议实现。** 命令说明宣称服务器、客户端、文本/字节集、同步/异步、
线程池和超时，但 `exmlrpc_cmdDef.cpp` 的 29 个命令体只读取局部 `PMDATA_INF` 参数；没有网络收发、
XML 编解码、对象状态、`pRetData` 写回、线程池或结果缓存代码。

## 2. 证据等级与真实交互线

| 主题 | 源码证据 | 当前结论 |
|---|---|---|
| 命令语义 | `exmlrpc_cmd_typedef.h`、`exmlrpc_cmdInfo.cpp` | 29 个命令、39 个参数元数据和中文说明存在；属于声明契约 |
| 对象模型 | `exmlrpc_dtType.cpp` | `ERPCServer` 覆盖 `0..13,27,28`，`ERPCClient` 覆盖 `14..26`；成员只是 `SDT_INT` 元数据 |
| 执行实现 | `exmlrpc_cmdDef.cpp` | 函数普遍只局部取参；未见业务执行、状态分配或返回值写回 |
| 动态入口 | `.def`、`exmlrpc_dllMain.cpp` | `.fne` 仅显式导出 `GetNewInf`，返回静态 `LIB_INFO` |
| 协议/编码 | 全目录逐段读取 | 未发现 XML、XML-RPC 方法名、序列化器、HTTP、TCP、socket 或第三方网络库 |
| 测试 | 目录清单和工程文件 | 未发现 `tests/`、测试工程、示例、CI 或运行脚本 |
| 文档 | 参考 `ARCHITECTURE.md` | 有接口和边界说明，但没有运行通过证据；本节不把说明当实现 |

源码能够证明的交互线只有：

```text
易语言宿主
  -> LoadLibrary(.fne)
  -> Source_exmlrpc.def::GetNewInf
  -> g_LibInfo_exmlrpc_global_var
  -> 命令表/数据类型表/函数指针表
  -> exmlrpc_*_N_exmlrpc(PMDATA_INF, INT, PMDATA_INF)
  -> 当前仅读取 pArgInf；没有网络/XML/RPC 后续
```

通知线是另一条 ABI 辅助链：

```text
NL_SYS_NOTIFY_FUNCTION
  -> exmlrpc_ProcessNotifyLib_exmlrpc
  -> elib/fnshare.cpp::ProcessNotifyLib
  -> 保存 PFN_NOTIFY_SYS
  -> NotifySys / ealloc / efree / CloneTextData / CloneBinData
```

`NL_GET_CMD_FUNC_NAMES`、`NL_GET_NOTIFY_LIB_FUNC_NAME`、`NL_GET_DEPENDENT_LIBS` 有静态返回；
`NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NR_DELAY_FREE`、`NL_IDE_READY` 等分支没有额外业务动作。
未发现从这些通知转入服务器、客户端或协议执行器的调用链。

## 3. 编码、HTTP、请求与响应边界

### 3.1 编码

- `LIB_INFO` 声明 `__GBK_LANG_VER`，公共字符串字段和命令元数据使用 `LPCSTR`；这是易语言支持库描述层的编码事实。
- 请求参数声明为 `SDT_TEXT` 或 `SDT_BIN`，实现入口分别读取 `m_pText`、`m_pBin`，结果参数读取 `m_ppText`、`m_ppBin`。
- 未见 UTF-8/GBK 转换、XML 转义、XML 字符实体、base64、日期类型、数值类型或 XML-RPC value 编解码。
- 因此不能声称文本会以 UTF-8、GBK 或 XML-RPC 标准编码上网，也不能声称字节集会经过 base64 或保持原样。

### 3.2 HTTP 与传输

全目录没有 HTTP 客户端/服务端、监听 socket、连接建立、请求头、Content-Type、Host、Keep-Alive、
状态码、重定向、TLS、代理或响应体读取实现。命令说明中的“服务器”“端口”“IP”只证明目标接口语义，
不能证明传输层是 HTTP，更不能证明符合 XML-RPC 规范。

### 3.3 请求/响应

声明层提供两组抽象：服务端 `GetRequestText/GetRequestBin` 读取消息，`SendText/SendBinary` 回复；
客户端 `SendSynRequestText/SendSynRequestBin` 等待结果，`SendAsynRequest*` 后由
`GetResultText/GetResultBin` 读取结果。实现层没有消息对象、request id、响应匹配表、状态码、
fault struct、并发队列、部分响应或输出提交协议。同步返回值 `1/0/-1` 只是注释约定，不是可观测实现。

## 4. 超时、错误、线程与资源矩阵

| 主题 | 声明/辅助代码 | 缺失或风险 |
|---|---|---|
| 超时 | `ServerSetTimeout`；同步请求有 `SDT_INT` 超时参数，单位说明为秒 | 命令体为空；没有计时器、deadline、取消、socket timeout 或超时后的连接状态处理 |
| 错误 | 返回 `SDT_BOOL`、`SDT_INT`，通用通知返回 `NR_OK/NR_ERR` | 没有协议错误、HTTP 状态、XML parse fault、底层错误码、重试性或结构化诊断 |
| 线程 | 说明提到线程池、串行处理和回调 | 未发现线程创建、池、锁、原子、条件变量、任务队列或并发状态保护 |
| 句柄 | `GetClientHandle`、`Disconnect`、`ClientDataPtr/ServerDataPtr` 元数据 | 没有句柄表、生成/校验/失效、引用计数、重复关闭或跨线程所有权实现 |
| 释放 | 构造/析构命令 `ServerRelease/ReleaseClient`；`efree` 和 `Clone*` 辅助存在 | 析构命令为空；没有 server/client 对象、socket、线程、回调、结果缓冲区的释放路径 |
| 取消/崩溃 | 未见取消令牌、worker、进程或恢复协议 | 阻塞调用、回调异常、宿主卸载和进程崩溃的资源收口均未定义 |

`fnshare.h` 的 `ealloc/efree` 通过宿主 `NotifySys` 分配和释放内存；`CloneTextData` 与
`CloneBinData` 也只提供数据复制辅助。它们不能替代 RPC 句柄生命周期，且 `DWORD` 承载通知参数和地址，
必须按匹配位数验证，不能从工程存在 x64 配置推断 ABI 安全。

## 5. ABI 与工程边界

- 命令函数由宏生成 `extern "C" void(PMDATA_INF, INT, PMDATA_INF)` 入口；`GetNewInf` 为
  `EXTERN_C PLIB_INFO WINAPI GetNewInf()`，动态 `.def` 只导出该符号。
- `EXMLRPC_DEF` 是命令单一登记源，同步生成声明、`CMD_INFO`、函数指针表、静态命令名和对象方法索引；
  索引 `0..28` 的静态一致性可核对，但一致性不等于函数实现。
- ABI 传递 `INT/DWORD/LPSTR/LPBYTE/PMDATA_INF`，并使用引用文本、引用字节集和数组指针；所有权、长度、
  旧值释放和异常路径需要宿主契约，当前命令体没有执行这些动作。
- 动态 Win32 Debug/Release 设置 `.fne`、`__E_FNENAME=exmlrpc` 和 `Source_exmlrpc.def`；x64
  配置未见同等宏、`.fne` 后缀或模块定义文件。x64 只能视为待验证工程配置，不能视为可加载目标。
- `DllMain` 的 attach/detach/thread 分支为空；初始化依赖 `NL_SYS_NOTIFY_FUNCTION`，没有 DLL 卸载事务。
  在存在回调、线程或网络句柄的未来实现中，必须先停止新调用、排空任务、注销回调、关闭连接和线程，
  再释放宿主内存和 DLL 状态。

## 6. tests、docs 与文档视觉审计

`exmlrpc` 没有测试目录、测试工程、示例程序或 CI。可做的静态核对只有命令索引与函数名、参数编号、
数据类型方法索引、`LIB_INFO` 表计数、`.def` 导出关系。以下证据均未取得：Windows/MSVC 构建、易语言 IDE 加载、
真实 HTTP/XML-RPC 字节、同步 deadline、异步回调、线程并发、句柄重复关闭、卸载和崩溃清理。

参考档案的视觉清晰度总体良好：先给定位和结论，再给流程图、目录、接口表、调用链、缺口、风险和证据索引；
但接口表较容易让读者把“声明契约”误读为“实现能力”。后续文档应保持以下版式规则：

1. 每个参考项目开头固定写“源码事实/运行证据/未验证边界”三行摘要。
2. 把“声明”“源码实现”“真实构建/运行”“故障与并发测试”用表格分栏，不在同一 bullet 混写。
3. 先放一条能闭合到当前源码的交互线，再放目标架构或建议，不用命名推断缺失模块。
4. 对协议、编码、超时、错误、线程、句柄和释放使用固定矩阵；缺失项明确写“未发现”，避免空泛的“支持”。
5. 长章节保留短标题、代码块和表格，但控制每段只表达一个结论；把路径、基线、测试状态放在证据索引，减少重复叙述。

## 7. 吸收裁决与后续验收门槛

可吸收的只有：X-macro 单一命令契约、支持库 `LIB_INFO/GetNewInf` 注册模式、显式对象方法索引、
宿主通知与分配器边界，以及“声明不等于实现”的文档分层方式。不可吸收为当前能力的包括 XML-RPC 编码、
HTTP 传输、请求/响应匹配、线程池、超时取消、结构化错误和安全卸载。

若未来补齐实现，最低验收顺序应为：

1. 先固定协议版本、编码、Content-Type、请求/响应 DTO、fault 错误码和长度上限。
2. 再以独立 owner 实现连接、request id、同步/异步状态、deadline、取消、回调和重复关闭保护。
3. 在 Windows x86/x64 分别验证导出、结构布局、调用约定、宿主分配器、真实 XML/HTTP 字节和错误映射。
4. 最后故障注入超时、半关闭、回调异常、线程竞争、重复 release、DLL 卸载和进程崩溃，逐项对账线程、句柄、
   socket、回调、缓冲区和临时资源；没有这些证据，不得把命令说明写成“已支持 XML-RPC”。

---

# evectoraframe 矢量动画框架源码审计

## 1. 范围与结论边界

研究对象为只读参考仓库：
`/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/evectoraframe`。
HEAD 为 `fdedd7b5a9388977a963e88a50efd91d8278abaa`，远程为
`https://gitee.com/JYtechnology/evectoraframe.git`；本地是浅克隆，只有初始化提交。

已尝试 CodeGraph。目标仓库没有 `.codegraph/`，当前索引只覆盖本平台；查询返回的是本平台无关符号，不能作为目标源码证据。以下结论来自参考仓库源码、ABI 头文件、工程文件和已有 `ARCHITECTURE.md`，没有安装依赖、构建、启动 Windows 宿主或运行测试。

总裁决：`evectoraframe` 是 Windows 易语言支持库的 ABI/元数据骨架，不是已实现的矢量动画引擎。它声明 125 个命令和 9 个数据类型，但命令没有真实执行、对象状态、绘制、帧播放、缓存、声音后端或返回值写回。

## 2. 文件与调用链

| 文件 | 源码事实 |
|---|---|
| `evectoraframe_cmd_typedef.h` | 单一宏表定义索引 0-124 的 125 条命令 |
| `evectoraframe_cmdInfo.cpp` | 75 条参数记录和命令元数据 |
| `evectoraframe_cmdDef.cpp` | 125 个统一签名入口，当前为空体或仅提取参数 |
| `evectoraframe_dtType.cpp` | 9 个数据类型、属性、15 个事件和控件回调 |
| `evectoraframe_dllMain.cpp` | `DllMain`、`LIB_INFO`、`GetNewInf`、通知分发 |
| `elib/lib2.h` | `MDATA_INF`、`HUNIT`、命令/属性/事件/库登记 ABI |
| `elib/fnshare.h/.cpp` | 宿主通知、内存分配、文本/字节集/数组辅助 |
| `Source_evectoraframe.def` | DLL 唯一导出 `GetNewInf` |

```text
易语言运行时/IDE → GetNewInf → LIB_INFO
  → CMD_INFO + 参数表 + 函数指针数组
  → evectoraframe_<命令>_<索引>_evectoraframe(...)
  → 当前只读取部分 pArgInf，未写 pRetData、未改变对象状态

IDE 创建 VectorAnimationFrame
  → LIB_DATA_TYPE_INFO → GetInterface(ITF_CREATE_UNIT)
  → ControlCreate(...) → 当前返回 HUNIT=0
```

`EVECTORAFRAME_DEF` 同时生成声明、元数据、函数指针、静态函数名和类型成员索引，降低独立表漂移，但造成强位置耦合。命令增删/重排会影响参数偏移、成员索引和函数入口；调试计数只统计参数总数，不验证逐命令偏移和类型。

## 3. 矢量图、帧、绘制和缓存

声明的功能分组为：索引 0 的 SWF→EVA；1-33 的位置、尺寸、可视、缩放、旋转、透明度和交互属性；34-43 的精灵/图形/编辑框/按钮/声音及复制、删除、层级；44-79 的精灵、帧、层构造析构和播放；80-112 的编辑框；113-121 的按钮状态对象；122-124 的声音。

但源码没有 EVA/SWF 格式解析、矢量元素存储、帧/层对象、播放时钟、绘制循环、重绘策略、变换/裁剪/合成、缓存键或缓存淘汰。`SWF_To_EVA` 只读取输入和输出指针；`Play`、`GotoOneFrame`、`SetAnimationData`、`CopyElement`、`DeleteElement`、`ZOrder` 等均无业务语句。不能把命令和属性声明写成已具备动画能力。

## 4. 资源、内存、线程、窗口、句柄与释放

已读实现只拥有静态元数据数组、函数指针数组和宿主通知指针。没有线程、锁、定时器、消息循环、绘制上下文、GDI/DirectX 对象、文件句柄、声音设备、缓存容器、后台队列或外部进程。业务资源尚未创建，不能据此宣称资源泄漏已解决。

`DllMain` 的 attach/detach 分支为空；`NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NR_DELAY_FREE`、`NL_IDE_READY` 也为空处理。构造/析构、`IsValid` 和 `HUNIT` 生命周期没有状态机、引用计数、失效标记、关闭顺序或并发保护，因此不支持可证明的安全卸载和线程安全。

`MDATA_INF` 在 `#pragma pack(1)` 下以 union 承载输入/输出。输入文本、字节集和复合数据通常是只读指针；输出文本/字节集需通过 `m_ppText`/`m_ppBin` 配合宿主 `MFree`；数组输出涉及 `NRS_FREE_VAR`；`ealloc`/`efree` 通过 `NRS_MALLOC/NRS_MFREE`。当前命令没有实际分配或释放，但未来实现必须禁止跨 CRT `new/delete` 和宿主 allocator 混用。`efree` 将指针传入 `DWORD`，在 x64 下存在地址截断风险，必须做真实 ABI 核验；`CloneBinData`、`GetBinData` 和数组乘积也缺少统一长度/溢出上限。

未来关闭顺序应为：阻止新命令/绘制，停止帧时钟和 worker，排空或取消调用，注销宿主回调/窗口消息，释放绘制、音频、帧层对象、缓存和宿主内存，最后使句柄失效。当前仓库未实现任何一环。

## 5. 错误、ABI 与工程审计

元数据虽描述了 `-1`、`FALSE`、空文本等失败值，但函数没有写回返回值，没有统一错误码、阶段、可重试性、关联 id 或底层错误信息；空函数可被宿主误判为成功，属于假成功风险。未知通知返回 `NR_ERR`，生命周期通知却多为空成功路径，无法区分未初始化、未支持和已释放。

动态库导出 `GetNewInf`，`LIB_INFO` 声明格式版本、GUID `730FA7B73AAB409a8554F9553CF2DD87`、库版本 `2.0.0`、系统/核心支持库 `4.0`、GBK、Windows-only 和通知入口。动态 Win32 工程配置 v141、SDK `10.0.15063.0`、`__E_FNENAME=evectoraframe`、`.fne` 和 `.def`；x64 配置缺少同样的名字定义、目标扩展和模块定义文件。静态 x64 配置缺少 Win32 的 `__E_STATIC_LIB`/`__E_FNENAME` 且启用未见 `pch.h` 的预编译头。当前 macOS 未构建，均为待核风险。

必须逐字节核对导出符号、调用约定、`SHORT/INT/DWORD/BOOL` 宽度、指针宽度、`MDATA_INF`/`LIB_INFO` 布局、GBK 字符串、`HUNIT` 和通知编号；x86/x64 不得共享未经验证的句柄表示。

源码没有文件/输入长度、元素数、帧数、声音大小、内存、绘制区域或缓存容量上限。未来解析不可信媒体时应优先采用受管子进程、deadline、资源上限、强杀和 orphan 回收，避免同进程崩溃拖垮宿主。

## 6. tests 与 docs 质量

目标仓库没有 tests、测试工程、CI、README、CMake、Makefile、包管理文件、第三方依赖清单或运行示例。以下全部未验证：加载和导出、125 条命令参数偏移/类型/返回值、Win32/x64 动态/静态构建、控件线程与属性序列化、对象析构/重复释放、坏/超大 EVA/SWF、帧切换和缓存淘汰、声音停止释放、宿主卸载、异常和并发。

目标 `ARCHITECTURE.md` 对文件、宏表、占位实现、ABI 和缺口的描述与源码总体一致，且区分“声明存在”和“功能实现”；但它是人工静态归档，没有自动命令偏移检查、导出快照、ABI layout 测量、构建日志、宿主测试或资源故障注入证据。文档中的“支持/注册/绑定”只能解释为元数据登记。

## 7. 交付前验收清单

- [ ] 自动校验 125 条命令的索引、参数偏移、数量、类型、返回类型和成员映射。
- [ ] Windows v141 分别构建动态/静态 Win32 和 x64，记录导出表、宏和结构布局。
- [ ] 建立真实 `HUNIT`/对象 owner，覆盖构造、引用、失效、复制、析构和重复释放。
- [ ] 定义 EVA/SWF 边界、格式版本、帧/层/元素模型、绘制线程、缓存预算和重绘策略。
- [ ] 所有命令正确写回 `pRetData`，显式返回结构化错误，禁止空函数假成功。
- [ ] 覆盖窗口、帧时钟、绘制、声音、线程、队列、缓存的正常/异常/取消/强杀释放和 orphan 对账。
- [ ] 在 Windows/易语言宿主中验证真实加载、命令、事件、属性、绘制、播放和卸载。

## 8. 证据索引

| 主题 | 证据 |
|---|---|
| 命令宏表 | `evectoraframe_cmd_typedef.h:12-137` |
| 参数/命令元数据 | `evectoraframe_cmdInfo.cpp:5-155` |
| 125 个命令空实现 | `evectoraframe_cmdDef.cpp:1-1028` |
| 类型/事件/属性/控件回调 | `evectoraframe_dtType.cpp:43-555` |
| DLL 登记/通知 | `evectoraframe_dllMain.cpp:7-181` |
| 内存/通知辅助 | `elib/fnshare.h:20-170`、`elib/fnshare.cpp:7-71` |
| 参数 union/所有权 | `elib/lib2.h:780-828` |
| 命令/属性/事件 ABI | `elib/lib2.h:266-364`、`395-729` |
| `LIB_INFO` ABI | `elib/lib2.h:1248-1318` |
| 动态/静态工程 | `evectoraframe.vcxproj:21-202`、`evectoraframe_static/evectoraframe_static.vcxproj:21-167` |
| 目标已有文档 | 目标仓库 `ARCHITECTURE.md:1-409` |

本节只更新当前平台根 `ARCHITECTURE.md`；未修改 `evectoraframe` 参考仓库或当前平台其他文件。

---

# OpenCode 源码参考交互、状态与资源审计

## 1. 研究边界与目录事实

本节只记录本地只读参考库的源码、测试和说明文件事实，不把参考库实现复制进本平台，也不把未运行的测试写成运行通过。实际 OpenCode 源码目录是：

`/Users/hekunhua/Documents/Agent/源码研究工作区/opencode-最新版本`

核心实现分布在 `packages/core`、`packages/opencode`、`packages/server`、`packages/sdk/js` 和 `packages/sdk-next`。该目录没有 `.codegraph`；本轮已执行 `codegraph explore`，工具明确返回索引不存在，因此以下定位来自分段 Glob/Grep/Read，而不是 CodeGraph 证据。根 `README.md` 主要是安装、内置 agent 和贡献入口；`packages/opencode/README.md` 仍是 Bun 初始化模板；`packages/sdk-next/README.md` 才描述 in-process host、durable session event replay 和 scoped 释放。三者不是同等权威的架构说明。

## 2. 交互总线与会话链

```text
HTTP API / SDK / ACP / CLI / TUI
        │ directory/workspace/instance 路由与授权中间件
        ▼
Session / SessionInput.admit / SessionExecution
        │ publish durable Session event
        ▼
EventV2：SQLite event + aggregate sequence + projector
        ├─ SessionProjector：Session、message、part、input 投影
        ├─ EventV2Bridge：补 location 后转向服务层
        └─ durable(after) / SSE：历史回放后接 live wakeup
        ▼
SessionRunner / legacy SessionProcessor
        ├─ provider turn
        ├─ durable Tool.Called
        ├─ local tool settlement
        └─ 下一轮 provider turn
```

- `EventV2.publish` 对 durable definition 在同一数据库事务中分配 aggregate sequence、执行注册 projector、执行可选 local commit hook，再写 sequence/event 表；提交后才唤醒 aggregate stream。`durable({ aggregateID, after })` 先读历史，再用内存 wakeup 重新读取，适合 cursor 恢复，但 live PubSub 不是持久队列。
- `SessionProjector` 将 Session lifecycle、消息、part、prompt admitted/promoted、tool 和 revert 等事件写入投影表，并用冲突检查和序列字段阻止明显重复/漂移。projector defect 会中止事务，不能扩大解释成跨服务最终一致性保证。
- `EventV2Bridge` 是 location 发布边界；HTTP event handler 使用无界队列、按目录/workspace 过滤、发送 connected、heartbeat 和 disposed。SSE 断开后不从内存队列恢复，恢复必须重新查询或消费 durable session stream。
- `SessionInput.admit` 先按 message id 去重，再发布 `PromptAdmitted`；缺 durable sequence 或发生 lifecycle conflict 会失败。它表示 prompt 已登记，不是通用容量准入、资源预留或跨节点 lease。
- `SessionExecution` 明确是本进程 active ownership；`SessionRunner` 当前是本地 continuation。源码注释仍将 durable multi-node ownership、durable busy/retry/idle/terminal status 和统一取消 settlement 列为未完成项，不能把 event durability 当成 execution durability。

## 3. 状态、准入与工具结算

- Event 状态由 `event.id`、`aggregateID`、版本化 type 和单调 `seq` 构成；replay 校验同 aggregate、连续序列、owner 和 payload 一致性，偏离即失败。
- Prompt 状态至少区分 admitted 与 promoted；projector 对 message 已存在、重复 admission、promotion 不匹配进行 `LifecycleConflict` 检查。
- 进程内 `BackgroundJob` 只有 `running/completed/error/cancelled`，用 token、pending、sequence 和 scoped fiber 防止旧执行覆盖新执行，并可 wait/promote/cancel；源码明确声明重启或 owner scope 关闭会丢状态并中断工作。它不是 durable queue，也没有 restart recovery 或 remote worker ownership。
- legacy `SessionProcessor` 用内存 Deferred 跟踪 tool call，V2 runner 则先 durable record tool call，再授权执行、记录 success/failure 并等待 settlements。两条链同时存在，不能把一条链的语义扩展到另一条链。
- file mutation 明确留下 `Tool.Called` 与 durable settlement 之间 crash recovery/idempotency 未定义的 TODO；runner 也列出取消 settlement、进度和最终状态持久化未完成。外部副作用需要 intent、attempt、receipt、unknown 和 reconciliation，不能只增加状态枚举。

## 4. Provider、远程缓存与资源生命周期

- provider handler 将 ModelsDev catalog、enabled/disabled 配置、connected provider 和 credential 合并为公开列表；provider loader 动态加载 AI SDK 包，并根据环境变量、Auth、配置和模型状态决定 autoload。这是 discovery/auth/model routing，不是 provider lease、配额账本或跨节点连接池。
- provider 对 SSE response 有 header timeout 和逐次 read timeout，并用 AbortController 取消；这只覆盖 provider HTTP 流，不能推出整个 session deadline、工具子进程 deadline、重试预算或 settlement 已持久化。
- `repository-cache.ts` 是本地 Git remote checkout cache：按 remote/branch 算路径，用 flock 串行 clone/fetch/checkout/reset，刷新采用 hard reset，并明确允许读者观察 checkout 在其下移动。它不是远程模型/结果缓存，没有内容寻址、generation、租约、读快照或引用优先 GC。
- PTY 是 location-scoped、进程内 Map；输出保留上限 2 MiB，退出 session 最多保留 25 个并可显式删除。关闭会 kill running process 并通知订阅者，但进程重启不恢复 PTY。
- PTY WebSocket 使用一次性 ticket、CSRF header、Origin 校验、目录/workspace scope、cursor replay 和单 writer outbox；连接结束后 detach。canonical `/api/pty` 保留 exited session，legacy surface 只暴露 running session，这是兼容行为而非两套持久状态机。
- server 用 Layer 组装 Database、Event、SessionProjector、Provider、BackgroundJob、PTY ticket、HTTP routes 和 Observability。SDK JS 通过 spawn `opencode serve` 等待 listening 输出，超时/abort 调 stop；`sdk-next` 在内存执行同一 router，不开 listener、不做网络 I/O，并以 Effect scope 释放资源。两种 SDK 不是同一资源模型。

## 5. 测试证据与文档冲突

- 相关测试覆盖 session history 的 aggregate cursor/replay、prompt admission、projector migration、provider env/config/whitelist、HTTP event SSE、PTY exited retention、ticket/CSRF、WebSocket input/output、plugin shell environment 和 SDK session history。测试使用 Bun，部分 PTY/真实 OS 场景按平台或 live fixture 执行；本轮未安装依赖或运行参考库测试，因此只记录“测试存在”。
- 不能从现有测试推出：跨进程 session recovery、multi-node owner takeover、provider quota、remote cache snapshot isolation、强杀后 PTY/子进程回收、Tool.Called 外部副作用对账、SSE 断线自动恢复、全局 admission resource budget 或 SDK server 子进程 orphan 回收。
- 根档案中其他项目章节反复出现 L0-L4、状态机、资源矩阵、unknown/reconcile、发布门禁等模板。它们可作为平台约束，但不是 OpenCode 当前实现事实；本节用“已实现/未完成/平台借鉴约束”区分，避免目标架构伪装成参考源码能力。
- OpenCode 文档层级不对称：根 README 描述产品安装和 agent，`packages/opencode/README.md` 没有实际架构信息，`sdk-next/README.md` 描述过渡包和 scoped in-process host。引用时以源码和测试为事实源，以 sdk-next README 解释 SDK 表面，不用模板 README 证明 durable、准入、资源和恢复语义。

## 6. 对本平台的落地约束

1. 将 event log、projection、live notification、execution ownership 和 external side effect 分成五个概念；SSE/PubSub 只能作为观测通道，不能作为恢复来源。
2. admission 必须记录 scope、capability/policy snapshot、resource reservation、deadline、attempt 和 owner；prompt admitted 只能代表输入已登记。
3. provider、tool、PTY 和 remote checkout 必须声明进程边界、取消语义、输出预算、清理责任和重启语义；未提供 durable ownership 的组件不得伪装成可恢复 worker。
4. 对 `Tool.Called` 之后的副作用采用 intent/receipt/unknown/reconcile；对 provider timeout、连接断开、进程强杀和缓存刷新保留可查询证据。
5. API 兼容层必须标记 legacy 与 canonical surface；cursor、generation、scope 和 capability snapshot 必须在恢复时重新校验。
6. 借鉴 OpenCode 时只复用可验证结构：版本化 durable event、aggregate sequence、幂等 replay、projector conflict check、ticket-scoped PTY attach 和 bounded output；不得直接复用其进程内 registry 作为分布式保证。

---

# eexcel2000 Excel COM/对象架构核对

## 0. 范围与证据边界

研究对象为本地只读参考源码：

`/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/eexcel2000`

外部目录没有 `.codegraph` 索引；已尝试 `codegraph explore "eexcel2000 Excel COM 对象 事件 线程 句柄 释放 进程 ABI"`，
无法取得该项目的 CodeGraph 证据，以下只依据源码、头文件、工程、导出定义和项目内 `eexcel2000/ARCHITECTURE.md`
的分段静态读取。未执行 Windows/MSVC、Excel、易语言 IDE、COM 运行、构建产物或测试。本次只修改本平台根
`ARCHITECTURE.md`，未修改外部参考仓库。

## 1. 真实实现与模板差异

- `Source_eexcel2000.def` 仅导出 `GetNewInf`；`eexcel2000_dllMain.cpp` 返回静态 `LIB_INFO`，元数据为 GUID
  `F86EC5989E044d42BC98C692C0B54727`、版本 `2.0.8`、Windows、易语言系统/核心支持库 `3.7`、GBK 语言。
- `eexcel2000_cmd_typedef.h` 用 `EEXCEL2000_DEF` 宏表生成 36 个命令的声明、元数据索引和函数指针数组；
  `eexcel2000_cmdInfo.cpp` 有 29 项参数元数据。这证明 ABI 描述集中，不证明命令后端存在。
- `eexcel2000_cmdDef.cpp` 的 36 个入口未出现 Excel COM/OLE 创建、调用或对象存储。`Create`、`Release`、`GetApp`、
  `Quit`、对象获取、打开/保存/关闭/打印/图表等函数为空；少数入口最多读取 `pArgInf`，未见 `pRetData` 写回。
  命令说明中的“成功返回真”或对象返回只是元数据意图。
- `eexcel2000_dtType.cpp` 注册 `ExcelApp`、`ExcelWorkbooks`、`ExcelCharts` 三个易语言类型，方法、属性和事件表较完整；
  但 `ControlCreate_*` 返回 `HUNIT 0`，`PropGetDataAll_*` 返回 0，属性变更/通知仍是模板分支。元数据完整不等于对象可用。

## 2. COM、对象与事件

源码未发现 `CoInitializeEx`/`CoUninitialize`、`CoCreateInstance`、`IDispatch`、`IUnknown`、`VARIANT`、`SAFEARRAY`、
`BSTR`、`QueryInterface`、`AddRef`/`Release`、Excel 类型库导入或 `HRESULT` 处理。`ExcelApp`、`ExcelWorkbooks`、
`ExcelCharts` 是易语言 `LIB_DATA_TYPE_INFO` 描述，不是已实现的 COM 包装对象。

`ExcelApp` 声明 9 个事件，包括工作簿打开/激活/取消激活、关闭前、保存前、打印前、新建表格、表格激活和取消激活；
事件参数引用 `Workbook`/`Worksheet` 等类型。但未发现 Excel 连接点、`IConnectionPoint` 订阅、事件接收器、取消订阅、
回调线程切换或事件触发代码。`EnableEvents` 只是属性元数据。对象关系 `Application -> Workbooks -> Worksheet/Range`
也只存在于说明，未实现对象句柄表、父子所有权、引用计数、当前对象状态或失效对象检测。

## 3. 线程、句柄、异常、释放与进程残留

- `DllMain` 的进程/线程 attach/detach 分支均为空；没有线程创建、消息泵、线程池、COM apartment 初始化或线程亲和性声明。
- `elib/fnshare.cpp` 的宿主通知回调和调试状态是无锁进程内静态变量，未见原子同步、重入保护或并发契约。不能宣称
  Excel COM 可跨线程安全调用；若补实现，必须明确 STA/MTA、消息泵和代理封送。
- `HUNIT`、`HWND`、`HMENU`、`HGLOBAL` 只是 ABI/Win32 类型。没有 Excel 窗口/进程句柄、COM 指针、临时文件或线程的登记、
  关闭和所有权表；未发现 `CreateProcess`、等待、超时、进程组终止、orphan 扫描或 Excel.exe 残留检测。
- `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NR_DELAY_FREE` 和 `NL_IDE_READY` 分支没有项目专属清理，`DllMain` detach 也不清理。
  命令名虽有三处 `Release`，实现为空；没有事件退订、子对象逆序释放、`Quit` 等待、`CoUninitialize`、失败回滚或宿主内存回收。
- 未发现 COM `IErrorInfo`/`EXCEPINFO`/`DISP_E_*` 映射、统一错误对象、超时或取消协议。未知宿主通知返回 `NR_ERR` 不能替代 Excel 错误模型。
  因而不能宣称线程安全、异常可恢复、安全卸载、无泄漏或零进程残留。

## 4. ABI、build 与配置

- 命令入口是易语言 ABI 的 `void(PMDATA_INF, INT, PMDATA_INF)`，`GetNewInf` 使用 `WINAPI`；`LIB_INFO`、命令/类型表、结构布局、
  指针宽度、调用约定和字符编码均属于宿主契约，不能跨边界传 C++ STL、异常或未声明所有权的内存。
- 动态工程为 `v141`、Windows SDK `10.0.15063.0`、Debug/Release × Win32/x64；只有 Win32 显式设置 `.fne` 和
  `Source_eexcel2000.def`。x64 未显式设置 `__E_FNENAME=eexcel2000`、目标扩展和模块定义文件。
- 静态工程复用同一源码；Win32 定义 `__E_STATIC_LIB`/`__E_FNENAME=eexcel2000`，x64 没有同等宏，且使用预编译头设置但未见
  对应 `pch.h` 证据。这些是静态配置风险，不是已构建失败或通过的证据。
- `NL_GET_DEPENDENT_LIBS` 返回空依赖列表，工程也没有 Excel 类型库、COM import、第三方库或链接设置；“机器安装 Excel”只是目标前提。

## 5. tests、docs、重复与冲突

外部目录没有测试目录、测试工程、CI、示例调用程序或构建产物；缺少命令返回、COM 生命周期、事件、线程、句柄、异常、卸载和
Excel.exe 残留回归证据。项目内 `eexcel2000/ARCHITECTURE.md` 已正确写出“命令为占位实现、没有 COM/OLE 调用、未构建未运行”，
本节不重复其目录地图，只补充 COM 符号、连接点、线程/进程管理、HRESULT/异常映射和对称释放均不存在的证据。

平台 `模块库/_模板/` 只有通用 Python 示例能力和简短说明，不描述 Windows DLL、COM、Excel 对象、事件或资源生命周期；不能以
模板的“能力可用”示例替代 eexcel2000 的 C++ 实现，也不能把 eexcel2000 的命令元数据反向当作平台能力清单。统一解释规则是：
命令/属性/事件“存在”只表示元数据声明；“支持 Excel 2000 或以上”只表示目标前提；“释放”只表示命令名；除非有 Windows 构建、
真实 COM 调用和进程/句柄对账，均不得升级为已实现或已验证能力。

## 6. 结论与验收缺口

`eexcel2000` 当前可确认是易语言 Excel 支持库的 ABI、命令表、对象/属性/事件元数据和动态/静态工程模板，不能确认具备可用的
Excel COM 自动化能力。后续必须在 Windows 补齐并验证：COM apartment 与对象引用释放；`HRESULT`/`EXCEPINFO`、超时/取消和失败回滚；
连接点订阅/退订、消息泵和回调重入；组件句柄、属性序列化、`Quit`、卸载和 `CoUninitialize`；x86/x64 Debug/Release 构建、导出 ABI、
静态库宏配置、真实 Excel 进程/句柄/残留扫描，以及覆盖上述边界的回归测试。测试存在并真实通过前，文档只能标注“接口声明/未实现/未验证”。

## 证据索引

| 主题 | 证据位置 |
|---|---|
| DLL、库元数据、通知、导出 | `eexcel2000_dllMain.cpp:5-177`、`Source_eexcel2000.def:1-4` |
| 命令宏表、参数、入口骨架 | `eexcel2000_cmd_typedef.h:3-48`、`eexcel2000_cmdInfo.cpp:5-80`、`eexcel2000_cmdDef.cpp:1-301` |
| 对象、属性、事件、组件回调 | `eexcel2000_dtType.cpp:123-346`、`eexcel2000_dtType.cpp:350-891` |
| ABI 头文件 | `include_eexcel2000_header.h`、`elib/lib2.h`、`elib/fnshare.h`、`elib/untshare.h` |
| 动态/静态构建 | `eexcel2000.vcxproj:1-202`、`eexcel2000_static/eexcel2000_static.vcxproj:1-167`、`eexcel2000.sln:1-40` |
| 项目内架构文档与平台模板 | `eexcel2000/ARCHITECTURE.md`、`模块库/_模板/实现/_模板.py`、`模块库/_模板/说明/使用说明.md` |

---

# KAG 知识增强生成架构分段复核

## 1. 定位与证据边界

目标是外部只读参考仓库：
`/Users/hekunhua/Documents/Agent/github 源码参考/30_多模态与媒体分析/55_knowledge_graph_rag/KAG`。
版本文件为 `KAG_VERSION=0.8.0`，许可证为 Apache-2.0。KAG 根目录没有 `.codegraph/`，已尝试
`codegraph explore "Scanner Reader Splitter Extractor Vectorizer Aligner Writer Schema SPG Reasoner Flow Solver"`
并收到索引不存在的明确结果，未自行初始化；后续按目录、关键词和源码分段读取。未启动 OpenSPG、
Neo4j、Java Reasoner、真实 LLM、向量服务或外部 MCP，因此以下是源码/测试/文档事实，不是外部系统
运行通过证据。

本节是 KAG 的唯一完整根文档记录。`开发文档/临时文档/细探/细探-KAG.md` 和参考仓库的
`ARCHITECTURE.md` 是历史/外部说明，不再重复维护相同长篇结论。

## 2. 总体链路

```text
输入
  -> Scanner(file/dir/csv/json/dataset/ODPS/SLS/语雀)
  -> Reader(txt/md/pdf/docx/dict)
  -> Splitter(length/outline/pattern/semantic/table)
  -> Extractor(schema_free/schema_constraint/knowledge_unit/chunk/table/summary/naive_rag)
  -> Vectorizer(dense/sparse batch)
  -> PostProcessor / Aligner
  -> Writer(KG/OpenSPG 或 MemoryGraph)
  -> SPG 子图、Chunk 节点和 source 互索引

查询
  -> SolverMain / pipeline
  -> SelfCognition
  -> Planner(LF、静态 DAG、迭代或 MCP)
  -> Context 依赖分组
  -> Executor(Retrieval/Math/Deduce/Output/MCP)
  -> Generator / Reporter
```

组件由 `kag.interface.*ABC` 注册表和 `from_config` 工厂装配。`type`、输入/输出类型和 YAML
配置构成组件形状契约，但注册表是进程内全局状态，不是版本化、隔离、可卸载插件系统。

## 3. 构建段逐组件事实

| 段 | 实现位置 | 已核对行为 | 边界/风险 |
|---|---|---|---|
| Scanner | `kag/builder/component/scanner/` | `DirectoryScanner` 用 `os.walk` 和正则收集路径，默认只匹配 `.*txt$`；另有 CSV/JSON/数据集/ODPS/SLS/语雀扫描器 | 未见统一真实路径信任、符号链接策略、大小/数量上限或稳定排序；默认不是“所有文档” |
| Reader | `component/reader/mix_reader.py` 及 txt/md/pdf/docx/dict | MixReader 对字典或路径分派，按路径最后一个点后的后缀选择 reader | 大小、MIME、编码、超时不由 MixReader 统一控制；大写后缀、无后缀和多点后缀依赖字符串行为；失败抛 Python 异常 |
| Splitter | `component/splitter/` | 长度 splitter 支持句子切分、滑窗、表格和 strict 硬切；outline/pattern/semantic 是替代策略 | 长度是 Python 字符数而非模型 token/字节预算，window、表格和语义切分没有统一资源账本 |
| Extractor | `component/extractor/` | LLM NER、标准化、三元组、知识单元、事件/关系和表格抽取；外部图可补 NER；通常最多 3 次指数重试 | 没有贯穿调用链的 deadline；知识单元同步 NER 空结果抛异常，而异步路径不完全对称，不能概括为全链路一致 |
| Vectorizer | `batch_vectorizer.py` | 按文本去重占位符，批量 dense/sparse 向量化后回填节点属性，支持同步和异步 | 异步函数构造 `sub_texts` 后却把 `texts[start:end]` 传给 `avectorize`，空白替换未生效；请求数、返回数、维度和字段映射缺少显式校验 |
| Aligner | `spg_aligner.py`、`kag_aligner.py` | SPG 按 `type#name` 合并；非基础/多值属性逗号拼接后 set 去重；KAG 按 Node/Edge 相等去重 | 值本身含逗号会损坏语义；内存合并不是存储侧原子 upsert；`from_spg_record` 会修改传入 record 的属性字典 |
| Writer | `kg_writer.py`、`memory_graph_writer.py` | KGWriter 做 namespace/JSON 规范化后 GraphClient upsert/delete；checkpoint 只记录 key；MemoryGraphWriter 只规范化并返回图 | checkpoint 成功不等于远端事务可见；两种 writer 的 delete/错误返回不对称；异常后的重试/幂等不由 writer 统一定义 |

`DefaultUnstructuredBuilderChain` 的顺序是 reader → splitter → extractor → vectorizer →
post-processor → writer。reader/splitter 先在主流程展开，之后按 chunk 用 `ThreadPoolExecutor`
并发；结构化链则 mapping → vectorizer（可选）→ writer。多层并发并不等于统一 DAG 调度器。

## 4. Schema、SPG、Reasoner 与检索 Flow

- `knext/schema/marklang/schema_ml.py` 是缩进敏感 DSL，覆盖类型、继承、属性、关系、约束、索引和
  Datalog 风格规则；schema diff 存在先删后建和继承属性保护，外部 REST/服务端事务不在本地源码内。
- `SubGraph` 以节点/边承载实体、事件、知识单元和 Chunk。抽取器把知识节点连到 Chunk 的
  `source` 边，Chunk `content` 保存标题与全文，形成知识到文本回链，但也造成全文复制、存储放大和
  敏感内容扩散。
- `ReasonerClient.syn_execute` 通过 `reason_run_post` 提交 DSL；`SchemaCache` 按 project id 缓存
  session。远端 URI 组装包含 user/password/database/namespace 查询参数，存在凭据泄漏风险；Java
  `reasoner-local-runner` 的规则和 MATCH 细节只能标为外部边界。
- `KAGFlow` 把分号/箭头字符串解析为 networkx DAG，拒绝环，按拓扑层并行执行。默认组件是
  `kg_cs`（精确一跳）、`kg_fr`（模糊一跳/PPR）、`rc`（向量 chunk）、`kag_merger`（合并/摘要）。
  该链是代码默认配置，不是所有项目 YAML 的固定协议；每个逻辑节点还会建立线程池。
- Solver 的 LF 计划包含 Retrieval、Math、Deduce、Output；静态 pipeline 用依赖分组和
  `asyncio.gather`，迭代 pipeline 受 `max_iteration` 限制。LLM 输出同时是数据和状态机信号，解析失败、
  unknown 和检索异常的降级必须区分“无证据”和“执行失败”。

## 5. 队列、缓存、子进程与资源边界

`AsyncTaskManager` 有 10 个 worker，但内部是无界 `queue.Queue`；结果用 `TTLCache(maxsize=1000,
ttl=3600)` 保存 running/completed/failed。提交没有背压、deadline、取消、可见性租约或幂等键，正在
运行的函数不能被强制终止。`LinkCache`、`SchemaCache` 只是进程内 TTL 包装；checkpointer 按 key
保存，不能替代跨进程提交账本。

Math executor 把 LLM 生成的 Python 写入临时文件，用当前解释器 `subprocess.run(timeout=5)` 执行并
删除文件。MCP executor 可从 HTTP(S) 下载 `.py/.js` 到 checkpoint 目录，再用 Python/node 通过 stdio
启动；源码没有签名/哈希/来源白名单、沙箱、进程组、CPU/内存/网络/输出限制或 orphan 扫描。timeout
只能限制等待，不等于安全执行。默认应把这两条链视为阻断级高风险。

## 6. Tests 与 docs 审计

`tests/unit/builder/component/` 覆盖 scanner、reader、splitter、extractor、mapping、postprocessor、
vectorizer、writer；`tests/unit/common/` 覆盖 registry/config/checkpointer/LLM/vectorize model；
`tests/unit/solver/` 覆盖逻辑形式解析和 planner。测试文件存在不代表当前运行通过，且 OpenSPG REST、
Neo4j、Java Reasoner、真实向量服务、外部 URL 和 MCP 子进程不能由普通本地单元测试证明可用。

文档中最容易重复或冲突的表述已在本节统一：

- “有界队列”改为“worker 有界、内部队列无界”。
- “默认 Flow 链”明确为代码默认配置，不宣称所有配置固定一致。
- “空结果均重试”改为同步/异步实现不完全对称，必须按源码路径核对。
- “Reasoner 可执行图推理”改为只能确认 Python 客户端 DSL 提交边界。
- 临时探查稿保留历史来源，不与根文档并列维护第二份完整事实表。

## 7. 平台吸收门禁与结论

1. Scanner 先限制真实路径、符号链接、单文件字节数、总数量和稳定排序；Reader 再统一 MIME/编码/超时。
2. 从 Scanner 到 Writer 使用统一任务 envelope，记录输入/配置摘要、attempt、deadline、取消原因和
   输出摘要；只有 writer 提交确认后才能推进 checkpoint。
3. Vectorizer 校验文本数、向量数、维度和字段映射，修复异步空白文本路径后再开放批量写入。
4. Reasoner/图/schema 调用使用受控认证头和脱敏日志，不把凭据拼到 URL；服务端事务能力列外部证据。
5. Math/MCP 默认拒绝；启用时必须受管子进程、独立进程组、资源限制、强杀回收、制品签名/摘要和来源白名单保护。

本轮只维护当前平台根 `ARCHITECTURE.md`，未修改 KAG 外部源码、外部文档或测试；未运行 KAG 测试，
因为依赖和外部服务未准备且用户要求的是全项目静态审计。

---

# einterprocess IPC 支持库审计

## 0. 范围、定位与证据边界

研究对象：`/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/einterprocess`。

该目录是易语言 Windows 进程通讯支持库的接口/代码生成骨架，不是完成的 IPC 实现。源码登记了命名管道、Windows 邮槽和内存映射文件三组能力、3 个对象类型和 26 个命令，但 `einterprocess_cmdDef.cpp` 的命令函数只读取少量参数或为空，未发现 `CreateNamedPipe`、`ReadFile`、`WriteFile`、`CreateMailslot`、`MapViewOfFile` 等实际 API 调用。本节只记录静态源码事实，不声明 Windows 构建、DLL 装载或跨进程实测通过。

目标目录没有 `.codegraph`。已尝试 `codegraph explore "einterprocess IPC shared memory pipe message lock process timeout disconnect handle cleanup ABI tests docs"`，返回的是当前平台中无关符号，不能作为该仓库源码证据；后续以 Glob、分段读取和目标仓库 Git 文件为准。

## 1. IPC 原语与消息模型

| 能力 | 源码登记 | 可确认事实 | 未实现/不可确认 |
|---|---|---|---|
| 命名管道 0-6 | 创建、监听、按名称连接、读、写、断开、释放 | 注释称可靠双向通信；连接超时为毫秒，`-1` 表示无限等待 | 没有底层创建/连接/读写；未定义消息边界、部分读写、缓冲上限、错误映射 |
| 邮槽服务器 7-11 | 构造、析构、创建、读、关 | 注释称单向、不可靠；服务端读取 | 没有句柄创建、读取、等待、丢失/广播语义或关闭实现 |
| 邮槽客户机 12-16 | 构造、析构、连接服务器/邮槽、写、关 | 帮助文本限制单次数据小于 424 字节，并描述 `.`, 域名和 `*` | 424 字节没有代码校验；没有写入、投递确认、重试或断连实现 |
| 内存映射文件 17-25 | 创建/打开、映射、读写、解除映射、关闭 | 注释要求偏移遵守 Windows 分配粒度且不得越界 | 没有文件句柄、映射句柄、视图地址、边界校验、并发可见性或提交规则 |

“消息”只存在于邮槽概念说明和命令帮助中。源码没有自定义帧头、长度、序列号、认证、版本协商、确认、重放保护或统一序列化格式；映射文件只是共享字节区域，不是已经实现的消息队列。

## 2. 锁、同步、进程、超时与断连

- 没有互斥量、事件、信号量、临界区、命名锁、原子状态、线程表或进程创建代码。不能宣称 IPC 对象线程安全，也不能假设多个读写者安全。
- `ListenNamedPipe` 的帮助文本明确可能阻塞；只有 `ConnectNamedPipe` 登记了显式超时。读、写、邮槽读取和映射读写没有独立 timeout、取消令牌或整体 deadline。
- 没有 worker、`CreateProcess`、作业对象、进程树回收、心跳、租约、重连、幂等键或 orphan 扫描。对端崩溃不会被该库自动恢复。
- `-1` 无限等待是元数据层约定，不是已经执行的等待策略；实现完成前不能验证负值、零值、系统错误和超时竞态。
- 没有管道 EOF/断连状态机、邮槽不可达语义、映射删除后的行为或对端退出错误转换。实现时必须把这些与取消、重试和资源回收分开定义。

## 3. 句柄、清理与 DLL 生命周期

三个对象类型各只有一个隐藏 `SDT_INT` 字段，分别标为邮槽服务器句柄、邮槽客户机句柄和映射文件指针；没有 owner、状态、引用计数、类型标签或关闭标志。

命名管道登记了断开/释放，映射文件登记了解除映射/关闭，邮槽登记了析构/关闭，但函数体没有 Windows 资源释放。`DllMain` 四个分支为空；通知中的 `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NR_DELAY_FREE`、`NL_IDE_READY` 也为空。`fnshare.cpp` 只保存系统通知函数指针并转发用户回调，不拥有 IPC 资源。

因此不能声称支持安全卸载、析构自动关闭、重复关闭幂等、调用中关闭保护、视图先解除再关闭映射、管道先断开再关闭句柄或异常路径零残留。未来实现至少需要 `未创建 → 已创建/已打开 → 已连接/已映射 → 关闭中 → 已关闭/失败` 状态机，并由唯一 owner 对账句柄、视图、等待、线程和缓冲区。

## 4. ABI、参数索引与位数

- `.def` 只导出 `GetNewInf`；命令按 `PFN_EXECUTE_CMD(PMDATA_INF, INT, PMDATA_INF)` 表格调用。`LIB_INFO` 登记 GUID、版本 `2.0.0`、Windows 标志、3 个数据类型和 26 个命令。
- X-macro 同时生成声明、命令元数据、函数表和静态符号名。`GetNewInf` 将命令 0 展示名改成 `CreateNamedPipe`，通知查询又返回 `CreateNamedPipeW`；展示名、元数据名和调用符号不能只按字符串核对。
- 输入字节集使用 `m_pBin`，输出引用字节集使用 `m_ppBin` 并标记 `AS_RECEIVE_VAR`；命令实现没有调用 `CloneBinData`、`GetBinData`、`ealloc` 或 `efree`，返回数据所有权未落地。
- 全局命名管道函数从 `pArgInf[0]` 读取；邮槽和映射对象函数从 `pArgInf[1]` 开始。若运行时没有为对象隐式占用 0 号参数，这是参数错位/越界风险，必须在宿主 ABI 烟测中裁决。
- 句柄/指针登记为 `SDT_INT`，工程却同时有 Win32/x64 配置；未见 `INT_PTR`、`HANDLE` 封装、位数断言或 x64 真实调用证据。x64 工程存在不等于 x64 兼容。
- 源码含 GBK/CP936 中文字符串，ABI 还包括结构体对齐、调用约定、文本编码和易语言分配器；这些不能由 Visual Studio 工程字段单独证明。

## 5. 文档审计：遗漏、重复、冲突与视觉结构

现有目标 `einterprocess/ARCHITECTURE.md` 已正确记录“26 个函数为空”、三类 IPC、对象索引、ABI、工程和无测试等主结论，但存在以下可读性和边界问题：

1. 未把“无锁、无同步、无进程 supervisor”作为独立结论，容易把能力登记误读为可靠运行时。
2. 已写连接超时，却没有明确其他阻塞点没有 timeout、取消或 deadline，也没有区分连接超时和整个调用预算。
3. 已列出断开、关闭和解除映射命令，却未逐项强调函数体为空、卸载通知为空、没有重复 close 或调用中关闭保护。
4. 邮槽“不可靠”、424 字节、映射偏移粒度和越界要求来自注释/元数据，不是实现校验；应统一标为“源码声明”。
5. “能力模型”“风险缺口”“测试状态”重复描述实现为空，但缺少最终状态矩阵，事实、注释和建议容易混读。
6. 目录文件数、无 README/测试/CI、工程扩展名等扫描结论应带当前 Git 树和静态读取限定，不能写成永久事实。

本节用“登记/可确认/不可确认”表格拆开 IPC 原语，并按范围、原语、可靠性边界、ABI、文档审计、验收顺序组织；根文档本身是多项目长文档，暂不重排其他章节或建立平行细探副本。

## 6. 测试与接入门禁

目标目录未发现测试目录、测试源、CI 或可执行示例。本轮未运行 MSBuild、Windows IDE、DLL 装载或 IPC 实测。实现或接入前至少需要：

- ABI：Win32/x64 导出、`GetNewInf`、命令表顺序、调用约定、GBK/Unicode、`MDATA_INF` 布局和字节集所有权。
- 命名管道：创建/监听/连接、有限 deadline、部分读写、断连、对端退出、重复 close 和错误码。
- 邮槽：单向语义、424 字节边界、不可达服务器、读取阻塞/取消、广播名称和关闭顺序。
- 映射文件：创建/打开、粒度校验、映射/解除映射、读写边界、空名称、并发可见性和关闭顺序。
- 生命周期：构造失败回滚、异常释放、重复关闭、卸载通知、崩溃/强杀后的句柄和临时资源清理。

在这些测试、资源 owner 和真实 Windows 证据完成前，只能把 `einterprocess` 注册为“待实现的 IPC 命令 ABI 骨架”，不得宣称其已具备共享内存、管道消息、锁、超时、断连恢复或进程隔离能力。

---

# wnet Windows 网络支持库源码核对

## 1. 范围与事实裁决

研究对象为本地只读参考源码：`/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/wnet`。本节按 Windows network、HTTP/连接、认证、线程/超时、关闭/错误、句柄/释放、ABI、tests 和 docs 分段核对。外部参考目录没有 CodeGraph 索引，已尝试查询并收到 `no .codegraph/index`；以下事实来自当前磁盘源码和工程文件。

最重要的结论：`wnet` 是易语言 Windows 支持库的元数据和 DLL/静态库接入骨架，不是已实现的 Windows Networking 客户端，更不是 HTTP/WinHTTP/WinINet 客户端。12 个命令函数只读取参数，没有调用 Windows WNet API、写 `pRetData`、写输出数组或转换错误码。命令说明中的映射、枚举、认证、断开、路径解析和速度查询只能视为目标契约。

## 2. 全交互链

```text
易语言 IDE/编译器
  -> .fne/DLL -> Source_wnet.def::GetNewInf
  -> LIB_INFO（版本、GUID、命令表、数据类型表、通知回调）
  -> wnet_ProcessNotifyLib_wnet
       -> NL_SYS_NOTIFY_FUNCTION -> ProcessNotifyLib -> NotifySys
  -> g_cmdInfo_wnet_global_var / g_cmdInfo_wnet_global_var_fun
  -> wnet_* 命令入口 -> PMDATA_INF 参数读取
  -> 当前实现结束：无 WNet/HTTP/连接/认证/返回值闭环
```

`WNET_DEF` 是命令单一清单，同一清单生成命令声明、`CMD_INFO`、函数指针表和名称表，共 12 项、25 个参数元数据项。`wnet_dtType.cpp` 另外登记 `WNet` 对象和 `ResType` 枚举。这证明元数据链路静态闭合，不证明业务链路闭合。

## 3. Windows network、HTTP、连接与认证

- `wnet_cmdDef.cpp` 没有 `WNetOpenEnum`、`WNetAddConnection`、`WNetCancelConnection`、`WNetGetConnection`、`WNetGetUniversalName`、`WNetGetResourceInformation` 或其他网络 API。
- 工程和源码没有 `WinHTTP`、`WinINet`、socket、HTTP 请求、DNS、TLS、代理、响应体或连接池实现。
- `映射资源` 的用户名、密码、提示开关和自动重连开关只在 `ARG_INFO` 和局部变量中出现；没有凭证校验、保存、擦除、传输、认证结果或凭证泄漏防护证据。
- `取共享资源`、主机名、速度和路径命令没有枚举器、连接对象、网络资源缓存或服务端状态。`取错误信息` 函数为空，也没有调用 Win32 `GetLastError()`。

## 4. 线程、超时、关闭、错误与资源释放

- `DllMain` 的四个分支全部为空；源码没有线程、异步 I/O、取消令牌、连接超时、重试、退避或 deadline。自动重连只是参数说明。
- `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NR_DELAY_FREE`、`NL_IDE_READY` 等通知被识别但空处理，返回默认成功；这不是资源释放或卸载安全证明。
- 当前命令没有 `HANDLE`、socket、文件、线程、连接或第三方库句柄，也没有 `CloseHandle`、`closesocket`、`FreeLibrary`、`free/delete` 或对称释放路径。只能说尚未实现可释放资源，不能宣称无泄漏。
- `elib/fnshare.cpp` 保存宿主通知函数指针和用户回调，没有互斥、原子状态、代次、注销或并发关闭协议；`NL_FREE_LIB_DATA` 也不清空这些指针。
- `ealloc`/`efree` 走易语言宿主分配器；当前命令没有分配输出，因此没有可证明的返回值所有权，未来实现不能混用 CRT/宿主堆。

## 5. ABI、位数与构建边界

- 动态入口只有 `.def` 导出的 `GetNewInf`；命令签名为 `extern "C" void(PMDATA_INF, INT, PMDATA_INF)`，通知函数为 `INT WINAPI (INT, DWORD, DWORD)`。
- `LIB_INFO` 登记 GUID `1F356293DD5846469639B8145EBECC9FE`、版本 `3.0.0`、易语言系统/核心支持库 `3.8`、GBK 和 Windows-only。版本和 GUID 是 ABI 握手字段，不是实现完成标志。
- `MDATA_INF`、`DWORD`、`INT`、指针、文本编码、数组头、`SDT_BOOL` 值和宿主分配器构成边界契约；不能跨边界传 STL、C++ 异常、未声明布局或由错误分配器释放的内存。把指针压入 `DWORD` 的辅助路径也要求按 x86 契约审查。
- Solution 虽列 x86/x64，但动态工程仅 Win32 配置设置 `__E_FNENAME=wnet`、`.fne` 和 `Source_wnet.def`；x64 缺少这些关键设置。静态工程的 x64 也缺少 `__E_STATIC_LIB`/`__E_FNENAME`，因此不能宣称 x64 可构建、可导出或可加载。

## 6. tests、docs 与重复/冲突审计

- `wnet` 目录没有 README、tests/test、测试源文件、CI、构建/发布脚本或已编译 DLL/FNE/LIB。`wnet/ARCHITECTURE.md` 是参考仓库唯一同主题文档，根 `ARCHITECTURE.md` 此前没有该项目章节。
- 参考文档与源码一致的核心事实是“元数据已实现、12 条业务命令仍为空、Windows 构建和 IDE 集成未验证”。本节在根文档建立同一长期事实源，不复制为另一份可独立漂移的项目文档。
- “Windows Networking 支持”只能作为库定位/目标描述；若写成“支持映射资源、认证、断开或网络请求”，即与 `wnet_cmdDef.cpp` 冲突。`WNet` 对象也不能与 HTTP 客户端、通用连接池或平台网络层混称。
- 根文档的通用 ABI、句柄、超时、隔离和测试原则适用于平台设计，但不是 `wnet` 已有能力，不能把其他参考项目的 HTTP、线程池、取消或恢复语义移植到 `wnet`。

## 7. 平台吸收裁决与验收顺序

若未来实现，应将 Windows API 放在受控支持库/适配层，并通过版本化公共契约向模块暴露。调用方不得直接持有 Win32 连接或窗口句柄。每次操作应绑定 owner、凭证作用域、deadline、取消状态和结构化错误；关闭前停止新调用，等待或取消进行中操作，擦除凭证，释放资源并核对残留。网络失败、认证失败、权限不足、超时、用户取消、资源不存在和未知副作用必须区分。

Windows 验收至少按以下顺序执行：

1. Win32 动态/静态构建，确认宏、`.fne` 目标和 `GetNewInf` 导出。
2. 装载测试，核对 GUID、版本、2 个数据类型、12 个命令、参数默认值和函数指针顺序。
3. 在隔离测试资源上验证每个 WNet API 的成功、权限/认证失败、取消、超时和 Win32 错误映射。
4. 验证凭证不落日志、不跨请求复用，连接/句柄/线程在正常、失败、取消、卸载和强杀后对账。
5. 分别验证 x86/x64 的 ABI、指针宽度、文本编码、数组输出、宿主堆释放和真实 IDE 集成。

在上述验证完成前，`wnet` 的正确状态是“Windows 易语言支持库元数据骨架，业务网络命令未实现，运行和资源生命周期未验证”。

---

# emmedia 多媒体支持库架构审计

## 1. 研究边界与结论

研究对象为仓库外只读参考项目：
`/Users/hekunhua/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/emmedia`。

本轮按输入、播放、解码/转换、设备、线程、事件、句柄/释放、ABI、tests/docs 分段读取源码、Visual Studio 工程、易语言 SDK 头文件和目标项目现有 `ARCHITECTURE.md`。目标目录没有 `.codegraph`；已尝试 CodeGraph，但工具明确报告索引不存在，因此以下结论来自逐文件静态读取，不是 CodeGraph、Windows 构建、DLL 装载、易语言宿主或真实设备运行证据。本轮只修改当前平台根目录 `ARCHITECTURE.md`，未修改参考项目。

**总裁决：`emmedia` 是多媒体支持库的 ABI/元数据和可视化组件模板，不是已落地的输入、播放、解码或设备实现。** `EMMEDIA_DEF` 登记 81 个命令、7 个对象和 1 个枚举，但 `emmedia_cmdDef.cpp` 中命令只读取部分参数或为空，没有发现 `mciSendString`、`waveOut*`、`waveIn*`、`midi*` 等后端调用，也没有向 `pRetData` 写返回值。说明文字和返回类型只能证明设计意图，不能证明能力可用。

## 2. 真实交互链

```text
易语言 IDE/运行时
  -> Source_emmedia.def::GetNewInf
  -> emmedia_dllMain.cpp::g_LibInfo_emmedia_global_var
  -> 命令元数据 + 参数表 + 81 项函数指针 + 数据类型表
  -> emmedia_cmdDef.cpp::emmedia_*_<index>_emmedia
  -> 当前只读取 PMDATA_INF；没有设备、文件、MCI、编解码器调用，也没有 pRetData 写回

易语言 IDE 可视化对象
  -> LIB_DATA_TYPE_INFO::m_pfnGetInterface
  -> ITF_* 回调
  -> 当前创建返回 HUNIT 0，属性/通知/数据接口为模板默认值

NL_SYS_NOTIFY_FUNCTION
  -> emmedia_ProcessNotifyLib_emmedia
  -> elib/fnshare.cpp::ProcessNotifyLib
  -> 保存宿主 PFN_NOTIFY_SYS，并首次查询 NRS_GET_PRG_TYPE
```

`emmedia_cmd_typedef.h` 是命令单一清单，宏展开到函数声明、参数元数据、函数指针表、静态编译命名表和对象命令索引。因此索引是实际 ABI 字段：不能重排、删除或改变参数起始位置而不同时更新所有展开结果。对象表还把 CD 播放的索引 70 插入到 38--55 之间、把媒体播放的 79/80 放在对象方法尾部，阅读时必须以索引表为准，不能按源码函数出现顺序推断方法顺序。

## 3. 分段审计

### 3.1 输入、录音与波形输入

- `WaveRecord` 的元数据声明 `Record`、暂停、继续、停止、格式设置、保存 WAV 和位置查询；`WaveInForm` 声明设备打开/关闭、采样间隔、上限和波形值读取。
- 当前实现没有录音设备句柄、缓冲区、回调、采样线程、格式校验、文件写入或停止后的缓冲收尾。`SaveFile` 只把路径和覆盖布尔值读入局部变量。
- `GetWaveFormat`、`GetWaveValue` 等引用参数没有检查 `pArgInf`、引用指针、类型和范围；返回值也没有写入，因而“失败返回假/成功写回引用”只是注释契约。
- 文档把输入格式限制写在命令说明中，但没有定义设备不可用、格式不支持、输入过载、缓冲溢出、保存失败或部分文件的错误码和回滚语义。

### 3.2 播放、CD、窗口和事件

- `CDPlay` 和 `MediaPlay` 的说明意图基于 Windows MCI，并暴露打开、关闭、播放、暂停、恢复、停止、跳转、位置/长度/状态、MCI alias 和视频窗口句柄。
- 源码没有 MCI alias 注册表、`MCI_OPEN`/`mciSendString` 调用、命令序列化、状态机、窗口消息处理或播放完成事件。`GetHwnd`、`SetHwnd`、`GetMode` 等命令均没有实际返回。
- `SysVolume` 元数据声明两个事件，但 `emmedia_ProcessNotifyLib_emmedia` 不处理媒体完成、设备变化或音量变化；对象通知接收者只保留生成器的设计器尺寸分支并返回 0。故事件从设备到宿主的闭环不存在。
- `SetHwnd` 的参数在 ABI 元数据中是 `SDT_INT`，文档却描述 Windows 窗口句柄；在 32/64 位下这不是可直接假定安全的句柄协议，必须明确位宽、宿主所有权、窗口线程和失效通知。

### 3.3 解码、编码和格式转换

- `AudioConvert` 登记初始化、编码器查询、编码器选择和文件转换；数据类型说明提到 WAV/MP3、DirectX 和系统编码器/解码器。
- 工程没有第三方库、额外链接库、DirectX/Media Foundation/codec 绑定或编码器发现实现；`Convert` 只读取源文件、目标文件和编码器索引。
- 因而不存在可审计的 demux/decode/encode 管线、输入输出格式协商、临时文件提交、目标文件覆盖策略、取消/超时或外部编解码器进程回收。不能把“解码器/编码器”写成当前依赖或能力。

### 3.4 设备、线程与并发

- 系统音量、Wave、MIDI、CD 和媒体对象均没有全局/实例上下文、设备枚举缓存、锁、队列、线程或回调线程模型。当前可确认的进程级状态只有 `fnshare.cpp` 的宿主通知函数指针、用户通知函数指针和调试类型。
- 源码没有 `CreateThread`、线程池、异步队列、定时器、设备回调或消息泵；因此不存在“后台播放线程已安全停止”或“录音线程可 join”的实现证据。
- `DllMain` 的四个通知分支均为空，没有禁用线程通知，也没有在卸载阶段关闭设备、停止回调或等待工作线程。若未来加入 WinMM/MCI 回调，必须先定义线程归属、回调取消和宿主退出顺序，不能在 `DllMain` 中执行阻塞清理。

### 3.5 句柄、事件和释放

- 当前没有真实 `HMMIO`、`HWAVEIN`、`HWAVEOUT`、`HMIDIOUT`、MCI device id、文件句柄或媒体上下文被创建，因此也没有相应释放路径。
- 所有 `ControlCreate_*` 都返回 0；`PropGetDataAll_*` 返回 0；属性定制回调直接写 `*pblModified = false`，却没有检查该指针是否为空。这些是模板默认值，不是安全的句柄生命周期实现。
- `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE` 和 `NR_DELAY_FREE` 分支为空；卸载时没有停止设备、撤销通知、释放宿主分配文本、清理 alias 或阻止并发命令。现状不能宣称支持安全热卸载或零残留。
- `fnshare.h` 的 `ealloc`/`efree` 依赖宿主通知分配器，`CloneTextData`/`CloneBinData` 返回的内存要求调用方对称 `efree`；但 emmedia 命令没有产生这些返回对象，未来实现必须明确“谁分配、谁释放、释放前是否仍被宿主/异步回调引用”。

## 4. ABI、失败语义和工程风险

- 动态库 `.def` 只导出 `GetNewInf`；其 `WINAPI` 返回 `PLIB_INFO`，库 GUID 为 `824F144B108A4bcbB966F45670D42A00`，版本为 3.0.0，要求系统/核心支持库 3.7，语言标识为 `__GBK_LANG_VER`，命令函数统一为 `void(PMDATA_INF, INT, PMDATA_INF)`。
- 命令名由 `__E_FNENAME` 拼接为 `emmedia_<name>_<index>_emmedia`；静态库通过 `__E_STATIC_LIB` 改变函数命名和通知路径。动态/静态共用源码，x64 工程却没有与 Win32 对称的 `__E_FNENAME`、`.fne`、`.def` 和静态宏配置，静态 x64 还启用 `pch.h` 预编译头但工程文件未列出该文件。这些是待 Windows/MSVC 复现的配置风险，不是本轮构建结论。
- `ARG_INFO` 记录默认值、可空和 `AS_RECEIVE_VAR` 引用标志，但实现没有校验 `nArgCount`、数据类型、空指针、文本编码、句柄宽度或默认参数状态。由于 `pRetData` 从未写回，声明的 `SDT_BOOL`/`SDT_INT`/`SDT_TEXT` 返回类型与实际行为不一致。
- 系统通知未知消息返回 `NR_ERR`；已声明的释放、卸载、延迟释放和 IDE ready 消息大多返回成功默认值或空处理。错误没有统一错误码、系统错误码、阶段、设备、alias、文件路径、可重试性或 trace 信息，失败路径无法诊断。
- `DWORD`、`INT`、`LPSTR`、`HWND` 和 `HUNIT` 混用在宿主 ABI 中；GBK 语言标识与 Unicode 工程并存，媒体路径、alias、设备名和错误文本的编码边界未实现。不能将指针、窗口句柄或 64 位设备标识压缩进 `INT`。

## 5. Tests、docs 与可读性审计

- 目标仓库没有 README、tests 目录、示例程序、CI/CD、构建脚本、设备模拟器、MCI/Wave/MIDI 夹具或 ABI 自动校验。Visual Studio solution 只能证明工程声明存在，不能证明 DLL 可装载或设备可用。
- 现有目标 `ARCHITECTURE.md` 的事实分层、证据边界和风险清单可读性较好，但源码注释和字符串出现明显乱码；命令清单的中文说明因编码问题无法可靠审阅。文档应同时保留稳定英文标识、索引和结构化参数表，避免只依赖乱码中文文本。
- 建议后续测试按“无设备静态 ABI -> Windows 无硬件 mock -> 真实设备/宿主”分层：验证导出表与 `LIB_INFO`、81 项函数表/参数偏移/对象索引一致；验证每个命令在坏参数和失败设备上写回确定结果；再验证录音、播放、MIDI、CD、转换的正常/暂停/停止/关闭/重复关闭/宿主卸载路径。
- 真实媒体测试还必须覆盖线程回调取消、MCI alias 冲突、窗口句柄失效、编码器缺失、源/目标文件相同、部分输出回滚、超时取消、设备拔出和宿主强杀后的句柄/临时文件对账。没有这些证据，不得把元数据数量写成已实现能力数量。

## 6. emmedia 资源 owner 矩阵与吸收裁决

| 资源/边界 | 当前实现 | 正常释放证据 | 失败/崩溃缺口 |
|---|---|---|---|
| 设备与播放上下文 | 未创建，命令为空壳 | 无 | 无状态机、无关闭、无设备拔出恢复 |
| 录音/波形缓冲 | 未创建 | 无 | 无回调线程、溢出策略或部分 WAV 回滚 |
| MCI alias/窗口句柄 | 仅元数据说明 | 无 | alias 冲突、窗口线程、失效句柄和关闭顺序未定义 |
| 编解码器/转换进程 | 未链接、未调用 | 无 | 无依赖发现、deadline、取消或输出提交 |
| 宿主通知/用户回调 | `fnshare` 静态函数指针 | 无注销 | 卸载和并发回调竞态未处理 |
| `HUNIT`/属性数据 | 创建恒为 0，属性数据恒为空 | 无 | 空指针写入、无对象 owner、无序列化协议 |

可吸收的仅是“单一 X-Macro 命令清单 + `LIB_INFO` 注册 + ABI/元数据与执行函数分离”的壳层模式，以及将设备能力、播放状态、错误和资源 owner 写成可验证契约的文档方法。不可吸收为平台已有能力的是 MCI 播放、Wave/MIDI 设备、解码/编码、线程安全、事件回调、句柄释放和真实测试。任何后续接入都应先补齐状态机、结构化错误、所有权/关闭协议、位宽与编码契约，并在 Windows 工具链和受控设备夹具上取得运行证据。

---

# 本平台 IPC 交互链审计（运行核心）

## 1. 范围、证据和裁决

本节只记录当前仓库运行核心的 IPC 事实，范围覆盖提供者隔离、任务调度、资源协调、句柄、进程身份、进程组和对应测试。已尝试 CodeGraph 查询 `interprocess IPC shared memory pipe message lock process timeout disconnect handle cleanup ABI`；仓库没有 `.codegraph/` 索引，查询命中无关网页解析符号，不能作为 IPC 证据。以下以当前源码和测试源码为准。

本文件包含外部参考源码审计与平台吸收约束，不是运行时契约。`开发文档/项目说明.md` 中“唯一 HTTP 能力网关”是对外通信入口，不否定运行核心内部使用受管本地 IPC。参考章节中的 IPC、进程、消息队列、timeout 或零残留描述，不能反向证明本平台已实现对应能力。

## 2. 实际 IPC 形态

当前实现有两条内部进程通信路径，没有共享内存实现证据：

```text
提供者监督器
  ├─ 独立进程.py → subprocess stdin/stdout → UTF-8 JSON 行协议
  │                  READY/健康/调用/停止，select + os.read，有界行缓冲
  └─ 任务进程.py → multiprocessing.Context(fork).Pipe(duplex=False)
                     单次任务一条 UTF-8 JSON bytes，poll/recv_bytes

跨进程权威状态 → SQLite WAL + 事务 + 资源级短锁
               → 文件快照/工作副本，不是共享内存
```

源码未发现 `multiprocessing.shared_memory`、共享映射、命名共享内存或 mmap 作为 IPC 数据面。SQLite、文件快照和 Python Pipe 不能被描述为共享内存。任务池等待队列是父进程内存中的有界调度队列，不是跨进程持久消息队列。

## 3. 提供者行协议交互链

```text
路由/监督器
  → 启动解释器与工作器
  → 子进程 stdout 输出 READY
  → 父进程在启动 deadline 内读取 READY
  → 健康请求/响应
  → 请求id + 能力id + 契约版本 + 参数 + 超时秒 + 取消标记
  → 子进程 flush JSON 响应
  → 父进程转换统一结果
  → 停止请求或 TERM/KILL
  → wait、关闭 stdin/stdout/stderr、记录退出码和清理结论
```

`运行核心/加载器/提供者隔离/独立进程.py` 用 `select`/`os.read` 避免文本包装器预读，限制单响应行 1 MiB；EOF、读错误、非法 JSON 和提前退出进入结构化失败。`进程工作器.py` 只注册标准测试能力，未知能力和能力异常不穿过 IPC 边界。

`平台控制面/提供者/进程提供者.py` 也是 stdin/stdout JSON 行协议，但通过读取线程按请求 id 分发响应，并以 `start_new_session=True` 建立进程组。它与运行核心的独立进程实现不是同一生命周期类；公共裁决是对外只返回结构化结果，不暴露 `Popen`、管道对象或底层句柄。

## 4. 任务 Pipe、消息边界和背压

`任务进程池` 为每个任务创建单向 Pipe 和取消事件，子进程通过 `send_bytes(json.dumps(...))` 发送一次响应，父进程 `poll()` 后 `recv_bytes()` 取回；请求与结果经过 JSON 往返，拒绝任意 Python 对象跨进程泄漏。

背压只在父进程调度层实现：活动进程数、等待队列和提交截止均有上限；超容量返回“资源繁忙”。池只保留一个轮询监视线程，停止时拒绝新提交、清空排队、终止活动进程并等待监视线程退出。该协议没有流式分片、消息重放、持久 broker、共享内存大对象通道或跨主机语义；大结果应使用受管制品引用。

## 5. 超时、取消、断连和进程组

| 路径 | 超时/断连处理 | 终态证据 |
|---|---|---|
| 提供者 JSON 行 | 读取 deadline 到期返回超时；EOF/写管道失败返回外部不可访问；可触发有界重启 | 请求 id、能力、错误码、重启次数、退出码 |
| 任务 Pipe | 监视线程按任务 deadline 判超时；取消后 terminate，有界等待后 kill | 任务状态、错误码、进程退出、连接关闭 |
| 进程树/外部命令 | 独立进程组 TERM/KILL 后 wait，核对 PID、端口和临时目录 | 未退出 PID、端口可重绑、目录清理 |

取消事件本身不是停止证据。只有工作进程真实退出、连接关闭并发布终态，任务池才返回“已取消”。超时治理的 Future 兼容路径明确承认已开始任务可能继续运行，不能把调用超时写成真实取消。进程组管理覆盖三层进程树、组长自杀、重复强杀和端口释放，不等于所有 subprocess 自动具备孙进程回收能力。

断连重试不能复用旧请求、旧进程、旧 PID、旧句柄或旧函数表；提供者重启必须重新 READY/健康握手，重试必须由错误码和幂等契约决定。

## 6. 锁、权威状态、句柄和清理

跨进程共享状态由 SQLite WAL、`BEGIN IMMEDIATE`、事务和结构化锁表解决。资源提交链为：读取版本/栅栏令牌 → 私有工作副本 → 提交前比较 → 资源级短锁 → 锁内 CAS → 原子状态提交 → 发布不可覆盖快照 → 事务证据 → 释放锁、失效句柄和删除工作副本。版本、栅栏令牌、锁所有权和进程身份独立校验。

进程身份是 `pid + 启动指纹`，带项目、所有者、实例和心跳；清理只回收心跳过期且项目/所有者匹配的死亡资源。句柄状态为“已创建 → 有效 → 已失效”，失效不可自动复活，跨项目/跨所有者复用拒绝；读取句柄引用计数归零后才清理旧快照。

统一清理顺序：停止新请求 → 排空或取消 → 有界终止进程/进程组 → `wait`/reap → 关闭 stdin/stdout/stderr 或 Pipe → 失效句柄/租约 → 清理工作副本、临时目录、端口和旧快照 → 写终态与释放证据。零残留核对必须同时检查子进程、标准管道、调用线程、临时目录和有界日志。

## 7. ABI 与跨边界数据

本平台 IPC 使用 JSON 文本或 UTF-8 JSON bytes，不传 C/C++ 指针、Python 对象、STL、异常、线程、锁、数据库连接、GPU context、文件描述符或原生句柄。运行上下文通过 JSON 字典传递请求、任务、项目、用户、会话、能力、契约和提供者字段；反序列化只接受白名单字段。

这里的“ABI”指协议字段、编码、长度上限、错误码、版本和所有权契约，不等于 DLL 的 C ABI。动态库/原生提供者必须在适配层或独立进程内做真实 ABI 校验；跨位数不得把指针/句柄压入整数，只传固定协议值或受管制品引用。

## 8. 测试覆盖与未闭合缺口

定向测试源码覆盖：提供者 READY/健康/调用/停止/重启、调用超时滞留响应、取消、崩溃、端口和零残留；任务池活动数、队列上限、提交截止、真实取消、停止排空和单监视线程；多进程快照、同版本唯一 CAS、强杀恢复、租约回收和进程身份；三层进程树、孤儿进程组、端口和目录回收。

测试源码证明覆盖意图，不等于本轮运行通过。当前仍缺少共享内存协议、跨主机 IPC、Pipe/JSON 统一公共契约、流式大消息/分片校验、双向并发复用、半关闭、写端阻塞上限、系统级 orphan 扫描补偿和 Windows/非 `fork` 任务池证据。`任务进程.py` 明确依赖 `fork`；`独立进程.py` 的 stderr 虽由管道承载，但没有独立持续排空和输出上限闭环，接入高 stderr 提供者时需补测试。

## 9. 文档重复与冲突裁决

- `开发文档/项目说明.md` 的 HTTP 网关规则是对外边界；本节是网关以下运行核心内部 IPC，二者不冲突。
- 本文件现有易语言 ABI、进程或释放段落属于参考或吸收约束，不能替代 `独立进程.py`、`任务进程.py` 和 `资源协调/服务.py` 的实现事实。
- 项目说明中的零残留是验收目标；未执行场景仍是待验证，不能被参考章节重复写成已完成。
- 项目记忆、阶段报告和临时文档只作历史证据；旧的“每任务监视线程”“无限任务进程”“进程内状态自动释放”表述以当前源码和项目说明为准。
