# opengl 架构建档

## 1. 文档范围与结论摘要

本文件是仓库根目录唯一的架构事实文档，依据当前工作树源码、Visual Studio 工程文件和 Git 元数据建立。源码参考库按只读研究处理；当前核对只新增本文件，不修改源码、工程、依赖、测试、配置或 Git 历史。

**首轮结论：** `opengl` 是一个面向易语言的 Windows OpenGL 支持库骨架。它已经实现了易语言支持库的装载/注册协议、命令/参数/常量/自定义类型元数据和 DLL/静态库两套工程入口；但 `opengl_cmdDef.cpp` 中登记的 126 个命令函数目前只有参数解包代码，没有 OpenGL、Windows、GLU 或 GLUT 调用，也没有向 `pRetData` 写回结果。因此，“命令已声明并登记”不能等同于“OpenGL 功能已实现”。

实现状态统一使用以下分类：

- **已实现**：当前源码中存在可执行逻辑，且可由静态代码直接确认。
- **仅声明/登记**：存在函数签名、元数据、宏或导出契约，但没有完成目标功能的执行逻辑。
- **未验证**：仓库缺少相应测试，或本机 macOS 无法直接验证 Windows/MSVC 构建和运行效果。

## 2. 项目定位

- **项目名**：`opengl`
- **支持库名称**：`OPenGL支持库`
- **用途（源码自述）**：为易语言提供 OpenGL 坐标变换、建模、测试运算、缓存、效果、纹理、显示列表、光栅、文字、特殊模型、3DS 模型载入和交互操作命令。
- **实际形态**：C/C++ 编写的易语言支持库工程，提供一个动态库项目和一个静态库项目。
- **运行边界**：工程配置面向 Windows，使用 Visual Studio/MSBuild 和 `v141` 工具集；支持库协议通过 `GetNewInf`、`LIB_INFO`、`CMD_INFO`、`PFN_EXECUTE_CMD` 等接口与易语言系统交互。
- **当前能力边界**：元数据与支持库生命周期通知链有实现；OpenGL 命令主体在当前提交中仅完成参数读取占位，不能据此宣称已经能够绘制或加载模型。

## 3. 中文文本流程图

```text
易语言 IDE/编译器
        │
        │ 加载支持库文件（动态库方案）
        ▼
Source_opengl.def ──仅导出──> GetNewInf
        │                         │
        │                         ▼
        │              g_LibInfo_opengl_global_var
        │              ├─库版本/GUID/名称/平台/依赖信息
        │              ├─13 个命令类别
        │              ├─CMD_INFO[126]
        │              ├─PFN_EXECUTE_CMD[126]
        │              ├─常量表[166]
        │              └─自定义类型 PIXELFORMATDESCRIPTOR
        │
        │ 易语言按命令索引分派
        ▼
OPENGL_DEF 宏（opengl_cmd_typedef.h）
        │
        ▼
opengl_cmdDef.cpp 的 opengl_*_<索引>_opengl 包装函数
        │
        ├─当前已实现：从 PMDATA_INF 读取 INT/BOOL/FLOAT/DOUBLE/文本/数组/字节集/引用等参数
        └─当前未实现：没有调用 OpenGL/Windows/GLU/GLUT API，没有填写返回值

易语言系统通知
        │ NL_SYS_NOTIFY_FUNCTION
        ▼
opengl_ProcessNotifyLib_opengl
        │
        ▼
ProcessNotifyLib → fnshare.cpp
        ├─保存易语言通知函数指针
        ├─查询 NRS_GET_PRG_TYPE 判定调试/运行版本
        └─按需转发用户通知函数
```

静态库编译路径如下：

```text
opengl_static.vcxproj
        │ 定义 __E_STATIC_LIB（Win32 Debug/Release）
        ▼
同一组 .cpp/.h 源码
        ├─保留命令包装函数的编译入口
        └─排除 DLL 的 LIB_INFO、CMD_INFO、常量表、数据类型表等注册数组
        ▼
静态链接到易语言静态编译产物
        │
        └─静态命令名/通知协议仍依赖源码中的条件编译契约，当前未做构建验证
```

## 4. 真实目录与文件地图

仓库没有 `README.md`、`AGENTS.md`、测试目录、CI 配置或旧的 `细探-*.md` 文件；以下地图来自当前工作树，而不是 README 推断。

```text
opengl/
├── opengl.sln                         Visual Studio 解决方案，含动态库和静态库项目
├── opengl.vcxproj                     动态支持库项目（DynamicLibrary）
├── opengl.vcxproj.filters             动态项目的 VS 文件筛选器
├── opengl.vcxproj.user                空的用户级工程属性
├── opengl_static/
│   ├── opengl_static.vcxproj          静态库项目（StaticLibrary）
│   ├── opengl_static.vcxproj.filters  静态项目的 VS 文件筛选器
│   └── opengl_static.vcxproj.user     空的用户级工程属性
├── include_opengl_header.h            聚合头；暴露元数据数组并按命令宏生成函数声明
├── opengl_cmd_typedef.h               命令单一事实表 OPENGL_DEF，含 0～125 共 126 项
├── opengl_cmdDef.cpp                  126 个命令包装函数；当前均为参数解包占位
├── opengl_cmdInfo.cpp                 ARG_INFO、CMD_INFO 参数/命令描述数组
├── opengl_const.cpp                   OpenGL/Windows 常量描述数组
├── opengl_dtType.cpp                  PIXELFORMATDESCRIPTOR 自定义数据类型描述
├── opengl_dllMain.cpp                 DLL 入口、LIB_INFO、命令函数表、支持库通知处理
├── Source_opengl.def                  DLL 模块定义，仅导出 GetNewInf
└── elib/
    ├── lib2.h                         易语言支持库 ABI：LIB_INFO/CMD_INFO/ARG_INFO/通知码/数据类型
    ├── fnshare.h                       通知、内存、文本、字节集、数组等支持库辅助接口
    ├── fnshare.cpp                     通知函数指针和调试版本转发实现
    ├── lang.h                          语言编码版本定义，当前为 GBK
    ├── krnllib.h                       系统核心支持库类型/版本常量
    ├── mtypes.h                        Windows/易语言兼容基础类型与宏
    ├── untshare.h                      共享基础声明（已纳入两个工程）
    └── PublicIDEFunctions.h            IDE 公共功能结构和功能码定义
```

工程文件列出的 C++ 编译单元为 `elib/fnshare.cpp`、`opengl_cmdDef.cpp`、`opengl_const.cpp`、`opengl_dllMain.cpp`、`opengl_dtType.cpp`、`opengl_cmdInfo.cpp`；动态和静态项目均使用这一组源码。

## 5. 模块职责与实现状态

| 模块 | 职责 | 状态 | 关键证据 |
|---|---|---|---|
| `opengl_cmd_typedef.h` | 以 `OPENGL_DEF(_MAKE)` 集中声明 126 个命令的索引、易语言名、英文名、说明、类别、返回类型、参数范围 | 已实现为登记表 | `opengl_cmd_typedef.h:11-139` |
| `opengl_cmdDef.cpp` | 为每个命令提供 `PFN_EXECUTE_CMD` 兼容签名，并从 `PMDATA_INF` 读取参数 | 仅实现参数解包；目标功能未实现 | `opengl_cmdDef.cpp:6-1355`；各函数体仅出现 `argN = pArgInf[...]` 或为空 |
| `opengl_cmdInfo.cpp` | 建立 285 项参数元数据、`CMD_INFO` 命令元数据及计数 | 已实现元数据；静态库分支未完成 | `opengl_cmdInfo.cpp:5-423`；`TODO` 位于 `:3` |
| `opengl_const.cpp` | 建立 OpenGL/像素格式常量名称、说明和值 | 已实现动态库元数据 | `opengl_const.cpp:3-184`；动态条件编译 |
| `opengl_dtType.cpp` | 声明 `PIXELFORMATDESCRIPTOR` 及其 26 个成员 | 已实现动态库元数据 | `opengl_dtType.cpp:3-51`；动态条件编译 |
| `opengl_dllMain.cpp` | DLL 生命周期入口、库描述、命令函数指针表、`GetNewInf`、系统通知 | 已实现协议骨架；通知中的多数业务分支为空操作 | `opengl_dllMain.cpp:6-102`、`:103-182` |
| `elib/fnshare.cpp` | 保存/调用易语言系统通知回调，获取调试运行版本，转发用户回调 | 已实现 | `elib/fnshare.cpp:7-71` |
| `elib/fnshare.h` | 提供 `NotifySys`、`ealloc/efree`、数组/字节集/文本转换等内联支持函数声明与实现 | 已实现辅助层；本项目命令主体未使用其完成 OpenGL 调用 | `elib/fnshare.h:20-169` |
| `include_opengl_header.h` | 聚合 ABI 头，声明动态库元数据数组，利用宏生成命令函数声明 | 已实现 | `include_opengl_header.h:1-26` |
| `Source_opengl.def` | 指定 DLL 对外符号 | 已实现，只有 `GetNewInf` | `Source_opengl.def:1-4` |

## 6. 命令表与功能分区

`OPENGL_DEF` 是命令元数据和函数指针数组共同使用的单一登记源。当前命令索引连续为 `0`～`125`，共 126 项；支持库描述声称有 13 个全局类别，类别串定义于 `opengl_dllMain.cpp:61-62`。

| 类别编号 | 类别名 | 登记的代表命令 | 当前实现判定 |
|---:|---|---|---|
| 1 | 设备操作 | `ChoosePixelFormat`、`SetPixelFormat`、`wglCreateContext`、`wglMakeCurrent`、`wglDeleteContext`、`gethdc`、`ShowCursor`、`ReleaseDC` | 仅登记/参数解包 |
| 2 | 坐标变换 | `glLoadIdentity`、`glMatrixMode`、`glTranslate`、`glRotate`、`glScale`、`glFrustum`、`glOrtho`、`glViewport`、`gluPerspective`、`gluLookAt` | 仅登记/参数解包 |
| 3 | 建模操作 | `glBegin`、`glEnd`、`glVertex`、`glRect`、裁剪、多边形、曲线曲面命令 | 仅登记/参数解包 |
| 4 | 测试运算 | `glHint`、`glAlphaFunc`、`glBlendFunc`、`glDepthFunc`、`glStencilFunc`、`glStencilOp` | 仅登记/参数解包 |
| 5 | 缓存操作 | `SwapBuffers`、`glFinish`、`glFlush`、`glAccum`、`glClear*`、`glColor`、`glIndex` | 仅登记/参数解包 |
| 6 | 显示效果 | `glEnable`、`glDisable`、`glLight*`、`glMaterial*`、`glFog`、`glNormal`、`glShadeModel` | 仅登记/参数解包 |
| 7 | 纹理图片 | `glBindTexture`、`glTexParameter`、`glTexImage1D/2D`、`glTexCoord`、`glTexEnv`、`glGenTextures`、BMP/TGA 载入 | 仅登记/参数解包 |
| 8 | 显示列表 | `glNewList`、`glEndList`、`glGenLists`、`glCallList(s)`、`glDeleteLists` | 仅登记/参数解包 |
| 9 | 光栅操作 | `glRasterPos`、`glBitmap`、`glCopyPixels`、`glPixelStore`、`glPixelZoom` | 仅登记/参数解包 |
| 10 | 文字轮廓 | `IsDBCSLeadByte`、`wglUseFontOutlinesW` | 仅登记/参数解包 |
| 11 | 特殊模型 | `glutSolid/WireSphere/Cube/Cone/Torus`、多面体、圆柱、圆台 | 仅登记/参数解包 |
| 12 | 其他 | `glGetError`、`glLoad3DS` | 仅登记/参数解包 |
| 13 | 交互操作 | `glInitNames`、`glPushName`、`glPopName`、`glLoadName`、`glSelect`、`gluProject/UnProject` | 仅登记/参数解包 |

**重要边界：** 表中的“代表命令”是命令表登记事实，不是 OpenGL API 已被调用的事实。`opengl_cmdDef.cpp` 只包含包装函数定义和参数变量提取，未包含 `#include <GL/...>`、`#include <Windows.h>`、`#pragma comment(lib, ...)`、`gl*`/`glu*`/`glut*`/`wgl*` 执行调用、返回值写入或错误处理逻辑。

## 7. 数据模型与内存布局

本项目没有数据库、文件持久化、配置文件解析或运行时业务实体；其“数据模型”是编译期静态支持库描述表和运行时易语言 ABI 数据结构。

### 7.1 支持库描述模型

`LIB_INFO`（定义于 `elib/lib2.h:1248-1315`，实例位于 `opengl_dllMain.cpp:31-87`）包含：

- 库格式号 `LIB_FORMAT_VER`、GUID、主/次/构建版本；
- 所需易语言系统版本 `3.0` 和核心支持库版本 `3.0`；
- 名称、GBK 语言版本、说明、Windows 状态；
- 自定义数据类型数组及计数；
- 13 个类别及类别串；
- 命令描述数组 `g_cmdInfo_opengl_global_var`；
- 命令执行函数指针数组 `g_cmdInfo_opengl_global_var_fun`；
- 通知函数 `opengl_ProcessNotifyLib_opengl`；
- 常量数组及计数；
- 依赖文件串（当前为 `NULL`）。

源码登记的库版本为 `2.0.0`，GUID 为 `F05D3E4CE9E84d0f82332D62BAF6447F`，库名为 `OPenGL支持库`，作者字段为 `大连大有吴涛易语言软件开发有限公司`，平台状态为 `_LIB_OS(__OS_WIN)`。这些是当前源码字符串，不代表远端项目的其他版本信息。

### 7.2 命令与参数模型

- `CMD_INFO` 的字段包括中文名、英文名、说明、类别、状态、返回类型、学习级别、参数数量和参数描述起始地址，结构见 `elib/lib2.h:297-364`。
- `ARG_INFO` 的字段包括参数名称、说明、图像索引、`DATA_TYPE`、默认值和参数传递标志，结构见 `elib/lib2.h:266-292`。
- `opengl_cmdInfo.cpp` 的参数索引从 `0` 到 `284`，共 285 个参数描述，命令表通过 `g_argumentInfo_opengl_global_var + N` 引用其连续片段。
- 支持的参数表示包括 `SDT_INT`、`SDT_BOOL`、`SDT_SHORT`、`SDT_FLOAT`、`SDT_DOUBLE`、`SDT_TEXT`、`SDT_BIN`、`SDT_SUB_PTR`、数组和引用参数；包装函数通过 `PMDATA_INF` 的 `m_int`、`m_bool`、`m_short`、`m_float`、`m_double`、`m_pText`、`m_pBin`、`m_pAryData`、`m_pDouble`、`m_pInt`、`m_ppAryData`、`m_dwSubCodeAdr` 等成员读取。
- `PFN_EXECUTE_CMD` 原型为 `void (*)(PMDATA_INF pRetData, INT nArgCount, PMDATA_INF pArgInf)`，见 `elib/lib2.h:1234-1239`。

### 7.3 自定义类型模型

`opengl_dtType.cpp` 注册一个动态库自定义类型：

- 中文名：`像素格式`
- 英文名：`PIXELFORMATDESCRIPTOR`
- 平台：Windows
- 成员数：26
- 成员包括 `nSize`、`nVersion`、`dwFlags`、`iPixelType`、颜色位、累计缓存位、深度/模板缓存位、层/遮罩等，见 `opengl_dtType.cpp:5-34`。

这些成员是易语言编辑器可见的结构元数据。当前源码未发现把该结构转换为 Windows SDK `PIXELFORMATDESCRIPTOR` 并传给 `ChoosePixelFormat`/`SetPixelFormat` 的执行代码。

### 7.4 常量模型

`opengl_const.cpp` 注册 166 个 `LIB_CONST_INFO` 条目（索引 `000`～`165`），以数值常量为主，涵盖像素格式标志、矩阵模式、图元模式、裁剪/测试、缓存、光照、纹理、显示列表、曲线曲面等 OpenGL 1.x 风格常量；结构定义见 `elib/lib2.h:735-748`。常量表是编辑/编译元数据，不产生 OpenGL 状态变更。

## 8. 真实调用链与接口边界

### 8.1 动态库注册链

1. DLL 由 Windows/易语言加载。
2. `Source_opengl.def` 导出固定入口 `GetNewInf`。
3. `GetNewInf()` 在 `opengl_dllMain.cpp:89-94` 返回 `&g_LibInfo_opengl_global_var`，并修正索引 82 的英文名为 `wglUseFontOutlines`。
4. 易语言读取 `LIB_INFO`，获得 `CMD_INFO` 数组和 `PFN_EXECUTE_CMD` 数组。
5. 命令索引与 `OPENGL_DEF` 保持一一对应；函数名通过 `OPENGL_NAME` 拼接为带库名和索引的符号。
6. 当前真正调用包装函数时，只会执行参数解包占位逻辑；`pRetData` 未被填充，因此返回型命令的结果不可由当前源码确认。

### 8.2 系统通知链

`opengl_ProcessNotifyLib_opengl` 的接口为 `INT WINAPI (INT nMsg, DWORD dwParam1, DWORD dwParam2)`，在 `opengl_dllMain.cpp:103-182` 实现：

- `NL_SYS_NOTIFY_FUNCTION`：调用 `ProcessNotifyLib`，把易语言系统通知函数指针交给 `fnshare.cpp`。
- `NL_GET_CMD_FUNC_NAMES`：返回静态命令实现函数名称数组；动态库分支修正索引 82 的 `W` 版本名称。
- `NL_GET_NOTIFY_LIB_FUNC_NAME`：返回 `opengl_ProcessNotifyLib_opengl`。
- `NL_GET_DEPENDENT_LIBS`：返回空依赖字符串 `"\\0\\0"`。
- `NL_FREE_LIB_DATA`、`NL_UNLOAD_FROM_IDE`、`NR_DELAY_FREE`、`NL_IDE_READY`、`NL_RIGHT_POPUP_MENU_SHOW`、`NL_ADD_NEW_ELEMENT`：当前为空操作。
- 未知通知：返回 `NR_ERR`。

`fnshare.cpp:24-71` 保存 `PFN_NOTIFY_SYS`，首次收到系统通知时通过 `NotifySys(NRS_GET_PRG_TYPE, 0, 0)` 查询程序类型，并通过 `s_pfnuserNotifySys` 转发用户回调。`NotifySys` 在 `fnshare.cpp:11-16` 中仅在回调非空时转发。

### 8.3 静态库边界

`include_opengl_header.h:11-20`、`opengl_cmdInfo.cpp:4`、`opengl_const.cpp:3`、`opengl_dtType.cpp:3` 和 `opengl_dllMain.cpp:6` 使用 `__E_STATIC_LIB` 进行条件编译。静态模式下动态库注册数组和 DLL 入口相关数据会被排除或改变；`opengl_static/opengl_static.vcxproj:48-72` 将项目类型设为 `StaticLibrary`，Win32 Debug/Release 定义了 `__E_STATIC_LIB` 和 `__E_FNENAME=opengl`。

需要注意：静态项目的 x64 配置（`opengl_static/opengl_static.vcxproj:130-163`）没有显式定义 `__E_STATIC_LIB`，与 Win32 配置不一致；其实际预处理结果和可链接性未在本机验证，属于工程风险而非已证实运行故障。

## 9. 依赖与构建工程

### 9.1 工程配置

| 项目 | 类型 | 平台/配置 | 工具链与关键设置 | 输出/入口 |
|---|---|---|---|---|
| `opengl.vcxproj` | `DynamicLibrary` | `Win32/x64`，Debug/Release | `PlatformToolset=v141`；Windows SDK `10.0.15063.0`；Unicode；Win32 Debug/Release 使用 `__E_FNENAME=opengl` | Win32 配置目标扩展名 `.fne`；模块定义文件为 `Source_opengl.def` |
| `opengl_static/opengl_static.vcxproj` | `StaticLibrary` | `Win32/x64`，Debug/Release | `PlatformToolset=v141`；Windows SDK `10.0.15063.0`；Win32 Debug/Release 定义 `__E_STATIC_LIB` | 静态库；源文件通过 `..\` 引用根目录源码 |
| `opengl.sln` | 解决方案 | `Debug/Release x86/x64` | Visual Studio 17 格式；x86 映射 `Win32` | 同时编排两个项目 |

动态项目的 Win32 Debug/Release 配置在 `opengl.vcxproj:51-63`、`:109-158`；x64 配置在 `:64-75`、`:159-198`。静态项目的类型和 Win32 条件定义在 `opengl_static/opengl_static.vcxproj:48-72`、`:92-129`，x64 条件在 `:130-163`。

### 9.2 依赖边界

- **源码直接依赖**：仓库内 `elib` 支持库 ABI 头文件；聚合入口为 `include_opengl_header.h`。
- **平台依赖意图**：命令名和说明引用 Windows/WGL、OpenGL、GLU、GLUT、GDI 等 API 名称，且库状态限定 `__OS_WIN`。
- **当前可见链接证据**：没有发现 OpenGL SDK 头文件、Windows SDK 头文件包含、`#pragma comment(lib, ...)`、额外 `.lib` 文件或动态加载代码；`LIB_INFO.m_szzDependFiles` 为 `NULL`，`NL_GET_DEPENDENT_LIBS` 返回空列表。
- **结论**：不能从本仓库证明实际 OpenGL 运行时链接已经接通。即使工程在 Windows 上编译成功，也仍需单独验证命令包装函数是否完成真正 API 调用。

## 10. 测试、验证与未确认项

### 10.1 仓库内测试现状

- 未发现 `test`/`tests` 目录、测试源文件、测试项目、CI 工作流或构建脚本。
- `opengl.sln` 只包含动态库和静态库两个项目，没有测试项目。
- `opengl.vcxproj.user` 和 `opengl_static/opengl_static.vcxproj.user` 只有空的 `<PropertyGroup />`，没有可复用的本地测试启动配置。

### 10.2 当前核对已做的静态验证

- 人工读取并交叉核对 `opengl.sln`、两个 `.vcxproj`、两个 `.filters`、两个 `.user`、`Source_opengl.def`、核心 C++/头文件及 `elib` ABI 定义。
- 统计确认 `OPENGL_DEF` 登记索引范围为 `0`～`125`，`opengl_cmdDef.cpp` 有 126 个对应包装函数。
- 静态检查确认 `opengl_cmdDef.cpp` 中没有实际 OpenGL/Windows/GLU/GLUT 调用语句，也没有 `pRetData` 写回逻辑；该结论基于源码人工阅读和文本证据，不是运行时行为推测。
- 读取 Git 本地和远程引用，确认版本基线一致。

### 10.3 未执行/未验证

- **未执行 Windows/MSVC 构建**：当前执行环境为 macOS，无法直接运行 `msbuild`/Visual Studio 工具链。
- **未执行 DLL 加载、易语言 IDE 注册或命令运行验证**。
- **未验证 OpenGL 上下文、像素格式、纹理、3DS/TGA/BMP、字体轮廓和 GLUT 模型行为**。
- **未验证静态库 x64 条件编译差异是否导致构建问题**。
- **未验证 `PIXELFORMATDESCRIPTOR` 元数据与真实 Windows SDK 结构的 ABI 兼容性**。

因此，本文件只把元数据/协议骨架标为“已实现”，把 OpenGL 命令功能标为“仅声明/登记”或“未验证”，没有把命令注释中的目标效果当作实现证据。

## 11. 风险与后续复核点

1. **核心功能空实现风险（高）**：126 个包装函数目前只读取参数，未调用任何目标 API；需要在 Windows/MSVC 环境中逐项补齐并验证 `pRetData`、引用参数、数组参数和错误状态。
2. **命令表与实现同步风险（高）**：`OPENGL_DEF` 同时驱动声明、函数表、命令名和命令元数据，索引错位会导致错误分派；应保留索引连续性检查。
3. **静态库条件编译风险（高）**：静态 x64 配置未定义 `__E_STATIC_LIB`，与 Win32 不一致；应在目标工具链中检查预处理结果和最终符号。
4. **依赖缺失/未接通风险（高）**：仓库没有 OpenGL/GLU/GLUT 头文件、库声明或加载器；应确认依赖由宿主/系统提供还是源码本应补充。
5. **返回值风险（高）**：命令元数据声明 `SDT_BOOL`、`SDT_INT`、`SDT_TEXT` 等返回类型，但包装函数未设置 `pRetData`；运行时结果不能视为已定义。
6. **资源生命周期风险（中）**：通知处理中的释放、IDE 卸载、延迟释放等分支为空；目标功能若后续持有 GL 上下文、纹理、显示列表或临时内存，需要明确释放契约。
7. **编码风险（中）**：库声明 `__GBK_LANG_VER`，源码文件存在 GBK 编码字节；跨工具链读取或转换时需保持字符串和易语言元数据编码。
8. **历史 API 兼容风险（中）**：命令说明混用 `glTranslate`、`glRotate`、`glScale` 等非标准 OpenGL 函数命名，同时通过宏生成带索引符号；需要以目标易语言运行时 ABI 和实际 API 绑定为准，不能只依据英文名猜测。

后续深挖建议按以下顺序进行：先在 Windows 工具链验证两个项目的预处理/构建；再补齐最小像素格式与上下文链路；随后按类别补齐命令实现和返回值；最后为每一类增加宿主级集成测试。所有后续结论都应继续回写本文件，避免产生第二份架构事实源。

## 12. Git 基线与证据路径

### 12.1 Git 基线

- **仓库根目录**：`~/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/opengl`
- **远程仓库**：`https://gitee.com/JYtechnology/opengl.git`
- **本地分支**：`master`
- **HEAD**：`c99208a28f043e3eb7ccc6162579365f5f79492f`
- **提交时间**：`2022-12-19T16:56:39+08:00`
- **提交主题**：`初始化仓库`
- **现场远程基线**：`origin/HEAD` 与 `origin/master` 均为 `c99208a28f043e3eb7ccc6162579365f5f79492f`。
- **建档前工作树**：干净，仅显示 `## master...origin/master`；当前核对仅新增/更新根目录 `ARCHITECTURE.md`。

### 12.2 证据索引

| 事实 | 证据路径 |
|---|---|
| 动态/静态解决方案组成 | `opengl.sln:1-40` |
| 动态库工程类型、Win32/x64 配置、`v141`、`.fne`、模块定义文件 | `opengl.vcxproj:21-49`、`:51-75`、`:95-158`、`:159-198` |
| 静态库工程类型和 `__E_STATIC_LIB` 条件 | `opengl_static/opengl_static.vcxproj:21-45`、`:48-73`、`:92-129`、`:130-163` |
| 文件归属和源码编译单元 | `opengl.vcxproj.filters:21-73`、`opengl_static/opengl_static.vcxproj.filters:19-66` |
| 命令集中登记表和索引 | `opengl_cmd_typedef.h:3-139` |
| 命令包装函数及参数解包 | `opengl_cmdDef.cpp:6-1355` |
| 参数和命令元数据 | `opengl_cmdInfo.cpp:5-423` |
| 常量表 | `opengl_const.cpp:3-184` |
| `PIXELFORMATDESCRIPTOR` 类型 | `opengl_dtType.cpp:3-51` |
| DLL 入口、库描述、命令函数表和通知处理 | `opengl_dllMain.cpp:6-182` |
| DLL 导出边界 | `Source_opengl.def:1-4` |
| 易语言 ABI 结构和通知码 | `elib/lib2.h:266-364`、`:693-748`、`:1150-1239`、`:1246-1315` |
| 系统通知/内存/数组辅助 | `elib/fnshare.h:20-169`、`elib/fnshare.cpp:7-71` |
| 语言编码 | `elib/lang.h:6-14` |
| Windows/基础类型兼容定义 | `elib/mtypes.h:1-176` |
| 核心支持库版本常量 | `elib/krnllib.h:114-131` |
| IDE 公共功能契约 | `elib/PublicIDEFunctions.h:5-6`、`:129-138`、`:164-180`、`:418-430` |

> 维护规则：本文件只记录当前源码可验证的架构事实；“命令说明想做什么”与“命令函数实际做了什么”必须分栏表达。旧细探文件不存在，当前核对没有删除任何旧研究材料。
