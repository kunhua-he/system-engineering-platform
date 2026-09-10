# python-fne 架构建档

> 首轮全量架构建档。本文只记录当前本地源码、工程文件与 Git 基线能够直接证明的事实；不把 README/更新说明中的宣传或未执行的构建结果当作实现证据。后续细探应继续更新本文件，不另起平行架构事实源。

## 1. 项目定位

`python-fne` 是精易科技面向易语言的 Python 支持库（`.fne` 动态库）源码。它通过易语言支持库 ABI 暴露命令和自定义数据类型，再通过 Windows `LoadLibrary`/`GetProcAddress` 动态加载 Python DLL，调用 Python C API，完成以下桥接：

- 配置 Python DLL 路径、模块搜索路径；
- 初始化/销毁 Python 解释器，执行单行 Python 代码；
- 导入模块、访问 `__main__`、已载入模块、builtins、locals、globals；
- 将易语言基础数据转换为 Python 对象，将 Python 对象转换回易语言数据；
- 以支持库自定义类型包装 Python 对象、列表、字典、元组、模块和迭代器；
- 暴露 Python 可调用对象调用、属性读写、容器读写、迭代和 GIL/线程状态操作。

仓库不是纯 Python 项目，而是 **Windows C/C++ 原生 DLL + Python C API 动态绑定 + 易语言支持库 ABI + 极少量 Python 示例/夹具**。当前实现描述明确以源码为准：`更新说明.txt` 声称“6种库定义数据类型、85种命令”，但 `JYEPythonFne.cpp` 中实际可见 `.addFun(...)` 注册点为 87 个（包含类方法与全局命令，继承方法还存在去重口径差异），两者未在源码中自动对账。

## 2. 版本与证据状态

### 2.1 Git 基线

| 项目 | 当前事实 |
|---|---|
| 本地分支 | `master` |
| HEAD | `3f6942850a324b02491bddcc699dbea6b41f7615`（短号 `3f69428`） |
| HEAD 时间 | `2023-09-20T09:27:48+08:00` |
| HEAD 作者 | `精易科技 <800073686@b.qq.com>` |
| HEAD 提交信息 | `commit message` |
| 远程 | `origin=https://gitee.com/JYtechnology/python-fne.git` |
| 工作树基线 | 首轮检查时 `master...origin/master`，无已显示修改 |
| 提交/远程新鲜度 | 未执行网络 fetch；不能据此声称远程当前仍与本地一致 |

### 2.2 证据分级

- **已实现（源码直接证实）**：`GetNewInf` 注册入口、支持库元信息装配、命令函数、Python C API 包装类、动态符号绑定、PythonTest 示例主流程。
- **仅声明/配置（文件声明但未由当前核对构建证实）**：Visual Studio 解决方案、Win32/x64 配置、`.fne` 输出后缀、Python 3.8 调试/发布库文件、导出符号 `GetNewInf`。
- **未验证**：本机 macOS 上无法直接验证 Windows `LoadLibrary`、`windows.h`、易语言宿主加载、Visual Studio/MSBuild 编译、`.fne` 在易语言 IDE/运行时中的装载，以及 Python DLL 版本兼容性。
- **风险性事实（代码可见但未做行为测试）**：错误处理留痕不完整、引用计数和内存所有权复杂、若干指针/函数签名存在可疑实现，详见“风险与未确认项”。

## 3. 总体架构与流程图

```text
易语言 IDE / 运行时
        │  支持库 ABI：LIB_INFO、CMD_INFO、MDATA_INF、PFN_EXECUTE_CMD
        ▼
JYEPythonFne.dll / .fne
        │
        ├─ DllMain：DLL 进程入口（当前仅返回 TRUE）
        ├─ GetNewInf：一次性构建支持库元信息并返回 PLIB_INFO
        │       ├─ Elib：全局命令、常量、自定义类型登记
        │       └─ ElibClass：类成员、继承成员索引登记
        └─ EiFun：易语言命令回调
                │  解析 PMDATA_INF，读写 pRetData
                ├─ EPython：解释器生命周期、导入、执行、错误与帧字典
                ├─ EdataToPydata：易语言值 → PyObject*
                └─ PyObj/PyList/PyDict/PyTuple/PyModule/PyIter
                        │  统一持有或借用 PyObject*
                        ▼
                PyDll：LoadLibrary(Python DLL)
                        │  GetProcAddress 取得 Python C API 函数指针
                        ▼
                Python 3.x DLL / Python 解释器
                        │
                        └─ sys.path → PythonTest/py/dom.py、用户模块
```

### 3.1 典型初始化与执行调用链

```text
易语言：设置解释器Py(路径)
  → SetDllPath_Fun
  → SetDllPath
  → LoadLibrary(路径)
  → GetProcAddress(Python C API 符号)
  → 返回布尔成功

易语言：置模块目录Py(目录串)
  → SetPath
  → EPython::SetPath
  → Py_SetPath

易语言：初始化Py()
  → Initialize
  → EPython::Initialize
  → Py_Initialize

易语言：运行代码Py(代码)
  → SimpleString
  → EPython::SimpleString
  → PyRun_SimpleString
  → pRetData.m_int = 0/负值（源码直接透传返回值）

易语言：导入模块Py(模块名)
  → ImportPy
  → EPython::Import
  → PyUnicode_DecodeLocale + PyImport_Import
  → 若 PyErr_Occurred，则调用 EPython::GetPyErrA
  → 返回 PyModule* 包装指针

易语言：销毁Py()
  → FinalizeEx
  → EPython::FinalizeEx
  → Py_FinalizeEx
```

## 4. 目录与工程地图

仓库根目录仅有两个源码/工程目录（另有 `.gitignore` 和 `.git`）：

```text
python-fne/
├── ARCHITECTURE.md                         # 本文；首轮新增
├── JYEPythonFne/
│   └── JYEPythonFne/
│       ├── JYEPythonFne.cpp                # DLL 入口、GetNewInf、全部元信息登记
│       ├── JYEPythonFne.def                # 导出 GetNewInf
│       ├── EiFun.h / EiFun.cpp              # 易语言命令声明与实现，约 1101 行实现
│       ├── Elib.h / Elib.cpp                # 易语言支持库元数据/命令/类型登记
│       ├── EPython.h / EPython.cpp          # Python 对象包装及解释器 API 包装
│       ├── PyDll.h / PyDll.cpp              # Python C API 函数指针类型、全局指针、动态加载
│       ├── StdAfx.h / StdAfx.cpp            # 预编译/公共源文件占位
│       └── elib/
│           ├── lib2.h                       # 易语言支持库 ABI 与数据结构定义，约 1388 行
│           ├── lang.h / mtypes.h            # 编码、基础类型和宏
│           ├── PublicIDEFunctions.h         # IDE 公共函数声明/常量
│           ├── container.* / fnshare.*      # 易语言运行库辅助实现
│           ├── mem.* / untshare.*           # 内存/共享辅助实现
│           ├── krnllib.h / StdAfx.*          # 运行库声明与预编译辅助
├── PythonFne_vs2019/
│   ├── PythonFne_vs2019.sln                 # VS 解决方案：支持库 DLL + PythonTest
│   ├── PythonFne_vs2019/
│   │   ├── PythonFne_vs2019.vcxproj        # DynamicLibrary，引用 JYEPythonFne 源码
│   │   └── 更新说明.txt                     # 功能说明与命令/类型数量口径
│   └── PythonTest/
│       ├── PythonTest.vcxproj               # Application，直接链接 Python 头/库
│       ├── PythonTest.cpp                   # Python C API 示例主程序
│       ├── dom.py                           # add、MyCall 示例模块
│       ├── py/dom.py                        # 备用/重复示例模块
│       ├── py/HmyPath.py                    # Python 路径和 sys.modules 示例
│       ├── include/                         # Python 头文件快照（含 cpython/internal）
│       └── libs/                            # python3/python38 的 .lib 快照
```

现场统计：12 个 `.cpp`、149 个 `.h`（其中 134 个为 `PythonTest/include` 的 Python 头快照）、3 个 `.py`、2 个 `.vcxproj`、1 个 `.sln`、1 个 `.def`、1 个 `.txt`；Git 跟踪文件共 186 个。仓库磁盘占用约 3.2 MB，其中 `PythonTest/include` 和 `libs` 是本地构建依赖快照，不是业务运行时数据。

## 5. 模块职责

### 5.1 支持库 ABI 与元数据层：`Elib.*`、`elib/lib2.h`

`elib/lib2.h` 定义易语言侧契约：`DATA_TYPE`、基础类型常量（`SDT_INT`、`SDT_TEXT`、`SDT_BIN` 等）、传址/数组标志、`MDATA_INF`/`PMDATA_INF`、`CMD_INFO`、`LIB_DATA_TYPE_INFO`、`LIB_INFO`、`PFN_EXECUTE_CMD`、通知消息常量等。

`Elib` 维护全局元数据容器：

- `CmdInfo`：`CMD_INFO` 命令说明数组；
- `PtrFuns`：命令实现函数指针数组，与 `CmdInfo` 位置对应；
- `ChangLIangInFo`：常量数组；
- `MyType`：自定义数据类型数组。

`Elib::addFun` 将命令描述与回调指针并列追加；`Elib::csh` 将 vector 首地址和数量写回 `LibInFo`，完成支持库元信息冻结。`ElibClass` 为自定义类型建立元素列表和命令索引，并可用 `BaseClass` 按分号分隔的名称筛选继承属性/方法。

### 5.2 DLL 装配层：`JYEPythonFne.cpp`

- `DllMain` 当前不做初始化，只返回 `TRUE`。
- `GetNewInf` 是易语言约定入口（`.def` 也只导出 `GetNewInf`）。
- 首次调用时设置版本 `1.1.1205`、GUID `{E7DD2D1E-E9E4-4467-B850-AD8F7A560C81}`、名称“精易Python支持库”、作者/主页/分类等信息。
- 注册四类命令分类：Python命令、Python类型、Python线程、调试相关。
- 注册六个自定义类型 ID：`SDT_Obj_Class`、`SDT_List_Class`、`SDT_Dict_Class`、`SDT_Tuple_Class`、`SDT_Module_Class`、`SDT_Iter_Class`。
- 注册全局命令、对象类命令以及列表/字典/元组/模块/迭代器类命令，最后调用 `myLib.csh()` 并返回 `myLib.GetInFo()`。

源码意图是“首次装配、后续复用”——以 `myLib.isCsh()` 防止重复注册；但全局 vector、全局函数指针和静态 `LibInFo` 也意味着该入口不是实例隔离设计。

### 5.3 Python 动态绑定层：`PyDll.*`

`PyDll.h` 不直接包含 CPython 官方 `Python.h`，而是手工声明 `PyObject`、`PyMethodDef` 和大量函数指针类型；`PyDll.cpp` 定义这些全局函数指针。`SetDllPath`：

1. `LoadLibrary(pstr)` 加载调用方传入的 Python DLL；
2. 对 `Py_GetPath`、`Py_Initialize`、`PyRun_SimpleString`、对象/列表/字典/元组/模块/线程/GIL/错误等符号逐一 `GetProcAddress`；
3. 不对每个符号是否为空做集中校验，最后只要 DLL 句柄非空就返回 `true`。

这是“运行时绑定 Python 版本”的关键边界，但同时把 ABI、函数签名、符号可用性和调用顺序责任全部放到了本项目。源码还将 `PyThreadState_Swap` 绑定到 `GetProcAddress(pydll, "PyEval_RestoreThread")`，该映射与函数名不一致，属于必须在 Windows/Python 目标版本上复核的高风险点。

### 5.4 Python 对象封装层：`EPython.*`

`PyObj` 是基类，持有 `_obj`（`PyObject*` 抽象指针）和 `_new` 所有权标记：

- `_new=true` 时析构调用 `Py_DecRef`；复制构造会 `Py_IncRef`；
- `SetObj` 会先释放旧引用，再替换对象和所有权标志；
- 提供 `Repr`、`GetType`、`GetSize`、`GetBytesSize`、`GetText`、`GetAttr`、`SetAttr`、`GetIter` 等操作。

派生包装：

- `PyDict`：创建/清空/包含判断/复制/键/值/取写键值/遍历；
- `PyTuple`：创建/取写元素/切片；
- `PyList`：创建/取写元素/插入/追加/转元组/切片；
- `PyModule`：取模块字典/名称/增加函数；
- `PyIter`：获取迭代器、`IterNext`、读取当前数据。

这些类主要是 C++ 内部对象；易语言侧通过 `m_pCompoundData` 指向其堆对象，类构造/析构/复制回调负责跨 ABI 生命周期。

### 5.5 易语言命令适配层：`EiFun.*`

`EiFun.cpp` 把易语言命令回调统一实现为 `void(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)`：

- 读取 `m_dtDataType` 判断传值/传址；
- 读取 `m_int`、`m_double`、`m_bool`、`m_pText`、`m_pBin` 或 `m_ppCompoundData`；
- 调用 `EPython`、`PyObj` 和 Python C API；
- 将返回值写回 `pRetData`，复合对象内存通常通过 `MMalloc(sizeof(T*))` 写出指针。

功能分组如下：

| 分组 | 主要源码函数 | 职责 |
|---|---|---|
| 解释器/模块 | `SetDllPath_Fun`、`GetPath_Py`、`SetPath`、`Initialize`、`FinalizeEx`、`SimpleString`、`ImportPy`、`GetModule` | DLL、路径、生命周期、代码执行、模块导入 |
| 错误/帧 | `GetPyErr`、`GetPyErrXiang`、`GetBuiltins`、`GetLocals`、`GetGlobals` | 查询 Python 错误和当前执行环境字典 |
| 值转换 | `EdataToPydata`、`AddPythonData`、`Obj_GetEi*` | 易语言标准数据与 Python 对象互转 |
| 可调用对象 | `Obj_CallMethod`、`Obj_CallArgDict`、`Obj_GetAttr`、`Obj_SetAttr` | 调用、属性访问、`args/kwargs` 传递 |
| 对象管理 | `Obj__init__`、`Obj__del__`、`Obj__copy__`、`Obj_GetPtr`、`Obj_SetPtr`、`Obj_AddCref`、`Obj_SubCref` | 复合对象生命周期、指针和引用计数 |
| 容器 | `List_*`、`Dict_*`、`Tuple_*` | 列表/字典/元组增删改查、切片和转换 |
| 模块 | `Module__*`、`Module_AddFun`、`Module_AddObj` | 模块名称、字典、动态增加函数/属性 |
| 迭代 | `Iter__*`、`IterNext`、`IterIsNext`、`IterGetData` | 迭代器状态与当前值 |
| 线程 | `InGIL`、`GetPyGIL`、`SaveThread`、`RestoreThread`、`GetPyEnsure`、`Release`、`ThreadStateSwap` | GIL 与线程状态 API 直通 |

### 5.6 易语言运行库辅助层：`JYEPythonFne/elib/`

该目录主要承载官方/项目复制的易语言支持库 ABI 和运行辅助代码，而非 Python 业务逻辑。`Elib.cpp` 通过 `MMalloc/MFree`、`fnNotifySys`、`NRS_RUNTIME_ERR` 等与易语言宿主交互；`PublicIDEFunctions.h` 和 `lib2.h` 提供 IDE/运行时通知、支持库结构和消息常量。

## 6. 数据模型与所有权

### 6.1 易语言调用数据

每次命令由 `PMDATA_INF` 传入：

```text
PMDATA_INF
├── m_dtDataType       # DATA_TYPE，含系统/库类型、数组/传址标志
├── 标量联合字段       # m_int / m_double / m_bool 等
├── m_pText/m_ppText   # 文本值或文本指针
├── m_pBin             # 字节集
└── m_pCompoundData
    └── m_ppCompoundData → PyObj/PyList/.../PyIter 堆对象
```

`pRetData` 使用同一 ABI 返回标量、易语言内存文本、字节集或复合对象句柄。复合对象输出一般是“易语言宿主分配一个指针槽，再写入 C++ 对象地址”，对应类型的 `__del__` 负责 `delete`。

### 6.2 Python 对象模型

```text
PyObject*（Python 解释器对象）
        ▲
        │ _obj + _new 所有权标志、Py_IncRef/Py_DecRef
        │
PyObj
├── PyList
├── PyDict
├── PyTuple
├── PyModule
└── PyIter（内部还持有 PyObj obj/data）
```

`_new` 表示当前包装器是否负责引用释放，不是 Python 对象本身的类型信息；借用引用与新引用由各个 Python C API 调用约定决定。当前代码存在多处“先构造 `true`、再额外 `addcref`”或对借用返回值再次包装的路径，所有权是否严格匹配需在目标 Python 版本下通过 refcount/宿主销毁场景验证，不能仅凭类型声明认定安全。

### 6.3 易语言标准值到 Python 值

`EdataToPydata` 的实现路径：

```text
MDATA_INF
  → IsPtrArg / ArgFun 去除传址标志
  → GetDataTypeType 判定系统类型/库类型
  ├─ 系统类型
  │   ├─ BYTE       → PyBytes_FromString
  │   ├─ SHORT/INT/INT64 → PyLong_FromLong（源码实际使用 int 指针）
  │   ├─ BOOL       → PyBool_FromLong
  │   ├─ TEXT       → PyUnicode_DecodeLocale
  │   ├─ BIN        → 读取易语言字节集头后 PyByteArray_FromStringAndSize
  │   └─ FLOAT/DOUBLE → PyFloat_FromDouble
  ├─ 库类型
  │   └─ 取 PyObj**，增加引用，返回其 PyObject 包装
  └─ 其他类型 → SetLastError，返回默认 PyObj
```

源码只明确支持上述标准类型；日期、子程序指针、数组/用户类型等没有在该转换函数中形成完整通用路径。

## 7. 接口边界

### 7.1 易语言支持库导出接口

- DLL 导出：`GetNewInf`（`JYEPythonFne.def`）。
- 支持库信息：`PLIB_INFO`，包含版本、GUID、命令分类、命令数组、类型数组、常量数组、通知回调等。
- 命令回调统一签名：`PFN_EXECUTE_CMD(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)`。
- 宿主通知：`ProcessNotifyLib` 接收 `NL_SYS_NOTIFY_FUNCTION`，保存 `PFN_NOTIFY_SYS fnNotifySys`，供 `MMalloc`、`MFree`、`GReportError` 等调用。

### 7.2 Python C API 动态接口

由 `SetDllPath` 解析的 API 类别包括：解释器路径/初始化/终止、Unicode/bytes、对象属性/调用/类型、列表/元组/字典、模块、错误获取恢复、GIL、线程状态、迭代器、函数参数解析。项目没有链接 Python import library 来调用这些 API，而是运行时保存函数指针。

### 7.3 Python 用户模块接口

`PythonTest/PythonTest.cpp` 证实的示例边界：

1. `Py_Initialize`；
2. `PyRun_SimpleString("import sys")`、`import os`、`sys.path.append("./")`、设置 `curDir`；
3. `PyImport_Import(PyUnicode_DecodeLocale("dom", NULL))`；
4. 获取 `dom.add` / `dom.MyCall` 并调用；
5. 用 `PyModule_AddFunctions` 动态添加 `efun`；
6. `Py_Finalize`。

`PythonTest/dom.py` 只实现 `add(a,b)` 和调用未定义的 `efun()` 的 `MyCall()`；后者用于演示动态注入函数，但其完整成功路径依赖 C++ 侧 `PyModule_AddFunctions` 和 ABI 正确性。

## 8. 关键行为与实际数据流

### 8.1 Python 函数调用

```text
易语言 Py对象.调用(参数...)
  → Obj_CallMethod
  → PyCallable_Check
  ├─ 无参数 → PyObject_CallObject(obj, NULL)
  └─ 有参数 → 每个 MDATA_INF 经 EdataToPydata
              → PyTuple_New(nArgCount-1)
              → PyTuple_SetItem
              → PyObject_CallObject(obj, tuple)
  → new PyObj(返回 PyObject*, true)
  → 写回易语言复合对象槽
```

`调用2` 使用 `PyObject_Call(obj, args, kwargs)`，其中 `args`/`kwargs` 也通过 `EdataToPydata` 得到。

### 8.2 Python 对象回易语言

- 文本：检查对象类型 repr 是否等于 `PyTypeStr`，调用 `GetText`/`PyUnicode_EncodeLocale`，写入易语言文本。
- 数值：允许 `int/float` 路径，调用 `PyFloat_AsDouble` 写入 `m_double`。
- 逻辑：检查 bool 后用 `PyLong_AsLong` 写入 `m_bool`。
- 字节集：检查 bytes/bytearray 类型，读取长度并调用 `CloneBinData` 生成易语言字节集布局。
- 容器/模块：新建对应包装器写入 `m_pCompoundData`。

### 8.3 动态增加 Python 函数

`Module_AddFun` 从易语言接收名称和子程序指针，申请可执行内存 `VirtualAlloc(..., PAGE_EXECUTE_READWRITE)`，复制 `FunChar` 模板并把参数区域写入，转为 `PyCFunction` 后调用 `PyModule::AddFun`。这不是普通静态 C 函数注册，而是运行时生成 trampoline 的实现；其 ABI、可执行内存释放、跨位数布局和安全边界均未由测试覆盖。

## 9. 工程、依赖与构建声明

### 9.1 支持库工程

`PythonFne_vs2019.sln` 含两个项目：`PythonFne_vs2019` 和 `PythonTest`。支持库项目：

- `ConfigurationType=DynamicLibrary`；目标为 `.fne`（Debug|Win32 明确设置）；
- `PlatformToolset=v143`，`WindowsTargetPlatformVersion=10.0`；
- 配置有 `Debug/Release × Win32/x64`；解决方案将 x86 映射到 `Win32`；
- 直接编译 `EiFun.cpp`、`Elib.cpp`、`EPython.cpp`、`JYEPythonFne.cpp`、`PyDll.cpp`，并引用 `elib` 头文件；
- Debug|Win32 的输出路径硬编码为 `E:\易语言正式版5.9\lib\`，链接模块定义文件 `JYEPythonFne.def`。

### 9.2 PythonTest 工程

`PythonTest.vcxproj` 是控制台应用，Debug|Win32 增加本地 `include` 与 `libs` 搜索路径；仓库内包含 `python3_d.lib`、`python38_d.lib`、`python38.lib`、`python3.lib`、`_tkinter.lib` 等快照。代码包含 `Python.h`，因此与支持库的手工动态绑定是两条不同验证路径：

- 支持库：不直接链接 Python import library，运行时加载 DLL；
- PythonTest：按工程配置直接使用 Python C API 头文件和本地 `.lib`。

### 9.3 依赖边界

| 依赖 | 证据 | 状态 |
|---|---|---|
| Windows API（`windows.h`、`LoadLibrary`、`GetProcAddress`、`VirtualAlloc`） | `Elib.h`、`PyDll.cpp`、`EiFun.cpp` | 已实现声明/调用；macOS 未验证 |
| 易语言支持库 ABI | `elib/lib2.h`、`mtypes.h`、`PublicIDEFunctions.h` | 已随源码携带并调用 |
| Python C API | `PyDll.h/.cpp`、`PythonTest/include/Python.h` | 已实现调用；版本兼容未验证 |
| C++ STL | `vector`、`list`、`memory`、`string` | 已实现使用 |
| Python 标准库模块 | `PythonTest/dom.py`、`py/HmyPath.py` | 仅示例验证材料，无自动测试 |
| Visual Studio/MSBuild v143 | `.sln`、`.vcxproj` | 仅工程声明，未在当前核对执行 |

## 10. 测试与验证现状

### 10.1 已有验证材料

`PythonTest.cpp` 是手工示例/冒烟程序，不是测试框架：它验证（按源码路径）解释器初始化、执行 Python 语句、获取当前模块变量、导入 `dom`、取得可调用函数、位置参数构造、Python 函数调用、动态函数表添加和 `MyCall` 调用。代码使用 `printf` 输出结果，没有断言、测试报告或退出码约定；函数最后也没有显式 `return 0`。

`dom.py` 的 `add(a,b)` 是可直接调用的成功样例；`MyCall` 调用的 `efun` 依赖 C++ 运行时注入，单独运行 Python 文件会触发名称未定义。

### 10.2 未发现的测试机制

本仓库没有发现 `README.md`、`requirements.txt`、`pyproject.toml`、pytest/unittest 测试目录、CI 配置或自动化测试脚本。`PythonTest` 只是 VS 控制台项目；仓库中没有当前核对可执行的跨 Windows/易语言宿主测试命令。

### 10.3 当前核对未执行的验证

- 未在 macOS 编译：源码依赖 Windows 类型、Windows API、Visual Studio 项目系统；
- 未在 Windows + Visual Studio 下编译 Debug/Release、Win32/x64；
- 未加载真实 Python DLL 并执行 `SetDllPath`；
- 未由易语言 IDE/运行时调用 `GetNewInf`、命令回调和对象析构；
- 未验证 Python 3.8 x86、其他 Python 3.x、Debug/Release DLL 的兼容矩阵；
- 未验证线程/GIL、引用计数、动态 trampoline 和长生命周期资源释放。

## 11. 风险与未确认项

以下不是推测性功能结论，而是源码审阅发现、需后续在目标 Windows 环境建立证据：

1. **版本/位数边界**：支持库说明明确以 Python 3.8 x32 C API 开发；工程同时列 Win32/x64，但 `PyObject`、指针到 `int` 的转换（如 `Obj_GetPtr`）和易语言指针槽大小都可能导致 x64 不安全。x64 是否可用未证实。
2. **动态符号缺失未集中失败**：`SetDllPath` 只检查 `LoadLibrary` 是否成功，不检查每个 `GetProcAddress` 结果；缺符号后可能在后续调用中跳转空指针。
3. **函数指针映射疑点**：`PyThreadState_Swap` 被绑定为 `PyEval_RestoreThread`，必须逐版本复核。
4. **错误处理不闭环**：`SetLastError` 在 `EiFun.cpp` 中为空实现；`GetPyErrA` 抓取错误后又 `PyErr_Restore`，但未见一致的宿主错误记录/清除策略。`GReportError` 直接调用 `fnNotifySys`，未检查回调是否为空。
5. **引用计数/借用引用复杂**：`PyList::GetListItem`、`PyDict::GetDictItem`、`PyObj::GetType` 等路径对 Python 借用引用包装并额外增计数，多个函数又显式 `addcref`；需用 CPython debug/refcount 工具验证是否泄漏或过度释放。
6. **内存所有权跨边界**：文本/字节集使用易语言宿主内存函数，复合对象使用 C++ `new/delete`；`Module_AddFun` 通过 `VirtualAlloc` 申请可执行内存但未见对应释放；异常或重复装载时可能泄漏。
7. **Python C API 参数宽度**：`SDT_INT64` 在 `EdataToPydata` 中和 `SDT_INT` 一样读取 `int` 并调用 `PyLong_FromLong`，长整数的真实 64 位语义未实现证实。
8. **路径/编码**：项目声明 `__GBK_LANG_VER`，`CharToWchar` 使用指定 code page，`WcharTochar` 使用 `CP_ACP`；Python `PyUnicode_DecodeLocale`/`EncodeLocale` 又受宿主 locale 影响，中文路径和非系统代码页未验证。
9. **执行器生命周期**：`GetNewInf` 全局静态元数据只初始化一次；`FinalizeEx` 可由命令显式调用，但后续命令是否被阻止、包装器是否仍持有 Python 对象，源码没有统一状态门禁。
10. **并发语义**：源码暴露 GIL 与线程状态 API，但支持库自身没有看到高层互斥/线程状态守卫；调用者若顺序错误可能导致解释器崩溃。`PyIter::IsNext` 只返回构造时 `_isNext`，`IterNext` 没有更新该字段，语义需实测。
11. **可执行内存与宿主安全**：`VirtualAlloc(PAGE_EXECUTE_READWRITE)` 生成函数 trampoline，且把易语言参数地址布局复制到固定模板偏移，强依赖 Win32/x86 ABI；这是高风险、未测试边界。
12. **工程配置漂移**：解决方案注释/版本为 VS16，但项目工具集是 v143；Debug Win32 有硬编码本地路径，Release 配置的预编译头/输出配置与 Debug 不完全对称。能否在干净环境复现构建，未验证。
13. **计数口径漂移**：`更新说明.txt` 的 6 类/85 命令与源码 6 类/87 个注册点不一致；应在目标易语言 IDE 中导出最终可见命令后再定口径。

## 12. 后续复核建议

按风险优先级，后续细探应保留证据路径并增量更新本文：

1. 在隔离 Windows 环境按 `Debug|Win32`、`Release|Win32`、`Debug|x64`、`Release|x64` 逐项构建，记录编译器、Python DLL、输出 `.fne` 和错误；
2. 用 Python 3.8 x86 与宿主真实加载 `GetNewInf`，验证 6 个自定义类型、最终命令数量、命令分类与 `LIB_INFO` 指针生命周期；
3. 建立“设置 DLL → 初始化 → 执行/导入 → 对象转换 → 销毁”的宿主级冒烟程序，覆盖异常路径；
4. 对 `PyDll` 符号表做运行时完整性校验，逐项核对函数签名，尤其是线程状态 API、`PyObject*` 宽度和 x64；
5. 用 CPython debug build 或 refcount 统计覆盖复制、返回、容器取值、模块属性和易语言对象析构；
6. 用两个真实线程验证 GIL/`PyEval_SaveThread`/`PyEval_RestoreThread`/`PyGILState_Ensure` 的调用协议；
7. 将 `PythonTest` 从手工 printf 示例扩展为有返回码的最小回归程序，但这属于后续开发，不是当前核对修改范围。

## 13. 证据路径索引

- 支持库入口与命令/类型注册：`JYEPythonFne/JYEPythonFne/JYEPythonFne.cpp`
- 易语言回调声明：`JYEPythonFne/JYEPythonFne/EiFun.h`
- 易语言回调实现、数据转换、对象/容器/线程命令：`JYEPythonFne/JYEPythonFne/EiFun.cpp`
- Python 包装对象与解释器生命周期：`JYEPythonFne/JYEPythonFne/EPython.h`、`EPython.cpp`
- Python C API 手工函数指针声明/动态绑定：`JYEPythonFne/JYEPythonFne/PyDll.h`、`PyDll.cpp`
- 支持库元信息装配、ABI 容器：`JYEPythonFne/JYEPythonFne/Elib.h`、`Elib.cpp`
- 易语言支持库 ABI 原始定义：`JYEPythonFne/JYEPythonFne/elib/lib2.h`
- 易语言基础类型/编码：`JYEPythonFne/JYEPythonFne/elib/mtypes.h`、`lang.h`
- 宿主 IDE 公共接口：`JYEPythonFne/JYEPythonFne/elib/PublicIDEFunctions.h`
- DLL 导出：`JYEPythonFne/JYEPythonFne/JYEPythonFne.def`
- VS 解决方案/配置：`PythonFne_vs2019/PythonFne_vs2019.sln`、`PythonFne_vs2019/PythonFne_vs2019/PythonFne_vs2019.vcxproj`
- C API 示例：`PythonFne_vs2019/PythonTest/PythonTest.cpp`
- Python 示例模块：`PythonFne_vs2019/PythonTest/dom.py`、`py/dom.py`、`py/HmyPath.py`
- 构建依赖快照：`PythonFne_vs2019/PythonTest/include/`、`PythonFne_vs2019/PythonTest/libs/`
- 项目功能说明：`PythonFne_vs2019/PythonFne_vs2019/更新说明.txt`
- Git 基线：`git status --short --branch`、`git log -1`、`git remote -v`（当前核对现场结果见第 2 节）

---

**范围声明**：当前核对只新增根目录 `ARCHITECTURE.md`，未修改源码、工程、依赖、测试、配置、Git 历史或删除任何旧细探文件。
