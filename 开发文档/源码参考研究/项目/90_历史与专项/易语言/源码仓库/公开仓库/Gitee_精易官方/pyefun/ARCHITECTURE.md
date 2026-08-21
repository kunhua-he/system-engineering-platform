# pyefun 架构建档

> 本文件是 `pyefun` 的唯一架构事实源。结论来自当前工作树源码、工程文件、文档和 Git 基线；README/文档中的愿景或“已支持”表述不自动等于实现证据。
>
> 本轮范围：首轮全量静态建档。只新增本文件，不修改源码、工程、依赖、测试、配置或 Git 历史；未安装依赖、未启动服务、未生成构建物，未执行完整测试套件。

## 1. 项目定位

`pyefun`（易函数、精易 pyefun 函数库）是一个以中文函数名和中文组件属性/事件为主要 API 的 Python 工具库，目标是把易语言核心支持库、精易模块式常用操作和部分桌面/自动化能力映射到 Python。当前代码形态是**扁平的函数/类适配集合**，不是带统一领域模型、服务进程或数据库的应用框架。

主要使用者和场景：

- 使用中文函数名快速完成文本、数组、文件、时间、编码、网络、并发、配置等基础开发；
- 用 `pyefun.wxefun` 将 wxPython 控件、事件、样式映射为中文命名，进行跨平台桌面 UI 开发；
- 按需接入 Selenium、Excel、二维码、JavaScript、OSS、定时任务、缓存、图表等第三方能力；
- 通过 `from pyefun import *` 获取核心函数集合，或按子模块显式引入可选能力。

README 宣称“超 300+ 实用函数”“企业级基础开发框架”等属于项目定位/宣传，不在本轮作为已验证能力结论；当前仓库没有服务端入口、数据库迁移、统一配置中心、CLI `entry_points` 或插件注册协议。

## 2. Git 基线与证据等级

### 2.1 当前版本基线

| 项目 | 当前证据 |
|---|---|
| 本地仓库 | `~/Documents/Agent/github 源码参考/90_历史与专项/易语言/源码仓库/公开仓库/Gitee_精易官方/pyefun` |
| 当前分支 | `master` |
| HEAD | `e430c5f8d5ad1fa1e06cf79ddba28549036904a7` |
| 短提交 | `e430c5f` |
| HEAD 提交时间 | `2021-06-19T11:03:30+08:00` |
| HEAD 提交主题 | `新增函数` |
| 远程 | `https://gitee.com/JYtechnology/pyefun.git`（fetch/push） |
| 远程 `HEAD`/`master` | `e430c5f8d5ad1fa1e06cf79ddba28549036904a7`；本轮 `git ls-remote` 与本地 HEAD 一致 |
| 建档前工作树 | `## master...origin/master`，未见已有变更 |
| 版本声明 | `pyefun/__init__.py:33` 为 `__version__ = '1.0.24'` |
| 打包版本 | `setup.py:8-16` 从 `pyefun/__init__.py` 读取版本并追加本地时间 `YYYYMMDD.HHMM` |

本次建档不执行 `fetch/pull/checkout`，因此“远程一致”仅指远程 `HEAD` 指针与本地 HEAD 一致，不代表代码内容经过运行验证，也不代表其他平台仓库状态一致。

### 2.3 Excel/Office 专项审计范围

本轮在既有总览基础上，对 `pyefun` 中尚未形成专项架构记录的 Excel 支持库做了第二轮静态审计。目标范围仅包括：

- `pyefun/excel/excel_openpyxl.py` 全部 176 行；
- `pyefun/excel/excel_xlwr.py` 全部 456 行；
- `pyefun/excel/__init__.py`、两个 Excel 示例、三个 Sphinx 模块文档；
- `setup.py`、`requirements.txt`、CI 测试清单及仓库内 Excel 测试文件盘点。

本专项没有修改 Excel 源码、示例、配置或 Sphinx 文档，也没有安装 `openpyxl`、`xlrd`、`xlwt`、`xlutils`、运行示例或执行测试。下文所有“已实现”均为源码存在证据，不表示运行通过。

### 2.2 状态标记

- **已实现**：当前源码有明确函数/类/导出/调用链证据；不代表本轮运行成功。
- **仅声明/线索**：README、注释、文档、空函数、示例或 CI 名称中有描述，但缺少可执行实现或本轮未验证。
- **未验证**：源码存在，但依赖、平台、外部服务、浏览器、桌面显示或运行时条件未在本轮确认。
- **存在风险**：静态阅读已发现异常、兼容性、默认参数或安全边界问题；不等同于已经复现的运行缺陷。

## 3. 总体流程图

```text
调用方 Python 代码
    │
    ├─ from pyefun import * / import pyefun as efun
    │       │
    │       └─ pyefun/__init__.py 聚合导出
    │              ├─ 核心支持库：算术、数组、磁盘、文本、系统、时间、类型、公共异常处理
    │              ├─ 常用工具：缓存、常用函数、进度、文本、时间、正则、并发、网络、配置、时钟
    │              └─ 编码子包：gzip/zlib/zip、二进制、Base64、URL
    │
    ├─ 按需导入可选子包
    │       ├─ wxefun：wxPython 原生控件 → 中文控件/属性/事件 → wx 事件循环
    │       ├─ networkUtil：输入 URL/参数/cookie/协议头 → requests → 网页返回类型
    │       ├─ seleniumUtil：浏览器/元素中文包装 → WebDriver → 外部浏览器/页面
    │       ├─ Excel/图像/二维码：Python 对象或字节集 ↔ 第三方库/文件
    │       ├─ asyncPool/threadingUtil/processPoolUtil：任务 → 线程/进程/事件循环 → Future/回调/队列
    │       ├─ config/cache：文本/环境/对象 → 配置解析器或缓存文件
    │       └─ APScheduler/OSS/JS/数据库：适配外部运行时或服务
    │
    └─ 返回 Python 基础值、中文包装对象、字节集、Future/任务句柄或第三方对象

持久化边界（非统一存储）：
    文件系统 ← dirkBase、cacheUtil、Excel、压缩、配置、图片
    外部网络 ← networkUtil、Selenium、OSS、邮件、远程浏览器
    外部数据库 ← mysqlUtil、peewee/mongo/redis 适配（未由 requirements.txt 完整声明）
    内存/运行时 ← 日期时间、数组、网页返回对象、线程/进程池、wx 控件树
```

## 4. 真实目录与分层

仓库根的 `git ls-tree` 显示：`.github/`、`docs/`、`example/`、`pyefun/`、`README.md`、`README.rst`、`setup.py`、`requirements.txt`、`Makefile`、`make.bat`、`MANIFEST` 等。当前跟踪统计为 152 个 Python 文件，其中 36 个文件名匹配 `*_test.py`；Python AST 静态解析无语法错误。

```text
pyefun/
├── __init__.py                 # 公共聚合入口；导出核心/工具/编码函数；版本
├── public.py                   # 全局异常显示开关与异常吞噬装饰器
├── arithmeticOperationBase.py  # 算术/随机数
├── arrayActionBase.py          # 列表、字典、数组包装
├── stringBase.py               # 易语言核心文本操作
├── dirkBase.py                 # 文件/目录操作（文件名历史上为 dirk）
├── systemProcessingBase.py     # 平台判断、延时、命令执行
├── timeBase.py                 # pendulum 日期时间包装
├── typeConv.py                 # 基础类型/JSON/时间转换
├── codeConv.py                 # 编码、哈希、Base64、URL、进制转换
├── commonlyUtil.py              # 常用数据、临时目录、控制台、分块等
├── stringUtil.py                # 正则/随机数据/文本提取与格式工具
├── timeUtil.py                  # 计时器与平均耗时统计
├── regexpUtil.py                # re 标志、现代正则及精易式兼容类
├── networkUtil.py               # requests HTTP 封装与网页返回对象
├── threadingUtil.py             # Thread、锁、线程池
├── processPoolUtil.py           # multiprocessing 进程、队列、进程池
├── asyncPool/                   # asyncio 事件循环线程 + 协程/阻塞任务池
├── asyncPoolGevent/             # gevent ThreadPool 协程池
├── cacheUtil.py                 # ubelt Cacher/CacheStamp 中文包装
├── progiterUtil.py              # ubelt 进度迭代器包装
├── configUtil.py                # ConfigParser 中文包装
├── configEnvUtil.py             # .env 文本解析/加载与 os.environ
├── clockUtil.py                 # APScheduler 一次性/间隔任务
├── encoding/                    # compress、ebase64、ebinary、url
├── excel/                       # openpyxl 与 xlrd/xlwt/xlutils 两套 Excel 适配
├── imageUtil.py                 # Pillow 图片与字节集
├── qrcode/                      # qrcode 生成、pyzbar 识别
├── javscript/                   # PyExecJS/Node 等 JavaScript 运行时适配
├── seleniumUtil/                # Selenium WebDriver 与元素中文 API
├── wxefun/                      # wxPython 窗体、事件、函数、组件、公用方法、兼容层
├── alisdk/oss/                  # oss2 Bucket 授权与初始化
├── orm/                         # peewee/mongoengine 适配占位
├── mysqlUtil.py                 # pymysql 数据库/游标包装
├── redis/redisutil.py           # Redis 适配占位文件
├── emailUtil.py                 # zmail 邮件发送适配
├── chartUtil.py                 # matplotlib/numpy 图表对象封装
└── win32apiUtil.py              # Windows API；不在公共 __init__.py 中导出
```

`docs/source/model/modules.rst` 把模块分成“核心支持库”和“工具函数”，但该文档目录不是自动注册表；实际公共入口以 `pyefun/__init__.py` 的显式 `import *` 为准。

## 5. 公共入口与模块职责

### 5.1 `pyefun/__init__.py` 聚合边界

`pyefun/__init__.py:1-32` 显式导入：

- 核心：`arithmeticOperationBase`、`arrayActionBase`、`codeConv`、`dirkBase`、`public`、`stringBase`、`systemProcessingBase`、`timeBase`、`typeConv`；
- 工具：`cacheUtil`、`commonlyUtil`、`progiterUtil`、`stringUtil`、`timeUtil`、`regexpUtil`、`threadingUtil`、`processPoolUtil`、`networkUtil`、`configUtil`、`configEnvUtil`、`clockUtil`；
- 编码：`encoding.compress.egzip`、`ezlib`、`zip`、`ebinary.binary`、`ebase64.ebase64`、`url.url`。

因此，公共导入会递归加载这些依赖。Excel、wx、Selenium、二维码、数据库、OSS、JS、邮件、图表、Windows API 等模块没有从该文件统一导入，调用方需显式导入；README:69 还特别提示打包程序应使用 `import pyefun as efun` 而非 `import *`。

### 5.2 核心支持库

| 模块 | 已实现职责 | 主要输出/边界 | 证据 |
|---|---|---|---|
| `arithmeticOperationBase.py` | `四舍五入`、绝对值、取整、幂/根/三角函数、随机数、最小/最大、上下取整 | Python 数值、全局 `random` | `arithmeticOperationBase.py:18-241` |
| `arrayActionBase.py` | `数组` 类及列表/字典增删查改、排序、随机抽取 | 原地修改传入 list/dict；数组包装持有 `self.val` | `arrayActionBase.py:14-199` |
| `stringBase.py` | 长度、左右/中间截取、字符/代码、查找、大小写、全角半角、去空、替换、重复、分割 | Python `str`/`list`/整数 | `stringBase.py:21-225` |
| `dirkBase.py` | 创建/删除/复制/移动/改名、遍历、路径检查、读写字节、追加文本、权限/时间 | 直接访问本地文件系统，异常装饰器部分转为 `False` | `dirkBase.py:45-352` |
| `systemProcessingBase.py` | Windows/Linux/macOS 判断、延时、`os.popen` 执行命令 | 主机平台和命令输出文本 | `systemProcessingBase.py:20-67` |
| `timeBase.py` | `日期时间` 包装 `pendulum.DateTime`；格式、时间戳、分量、加减、差值、迭代 | 内存日期对象；默认使用当前时间解析路径 | `timeBase.py:20-168` |
| `typeConv.py` | bytes/str/float/int/日期及 JSON 转换 | 直接调用 Python 转换，错误通常直接抛出 | `typeConv.py:16-36` |
| `public.py` | `异常显示信息` 全局开关；`异常处理返回类型逻辑型` 装饰器 | 异常时打印可选信息并返回 `False` | `public.py:18-65` |

### 5.3 常用工具层

| 模块 | 职责与状态 | 证据 |
|---|---|---|
| `commonlyUtil.py` | 约 81 个函数及 `临时目录`、`控制台`、`分块` 类，提供随机/UUID/对象/容器等常用操作；已实现但范围较杂 | AST 统计；模块头部导入 `ubelt`、`collections`、`uuid` 等 |
| `stringUtil.py` | 基于 `stringBase` 的文本左右截取、随机字母/数字/汉字/手机号/邮箱/IP、正则提取、字符判断、格式化、批量取中间文本；拼音函数运行时导入 `pypinyin` | `stringUtil.py:18-394` |
| `regexpUtil.py` | `正则` 标志常量、`正则表达式` 的编译/搜索/替换、`正则表达式类` 精易式兼容 API | `regexpUtil.py:18-130` 及后续类方法；测试为打印式演示 `regexpUtil_test.py:7-107` |
| `timeUtil.py` | `时间统计` 上下文计时、`计时统计` 基于 `ubelt.timerit` 做平均/最小/标准差展示 | `timeUtil.py:22-262` |
| `progiterUtil.py` | `进度显示` 包装 `ubelt.ProgIter`/格式化能力 | AST/模块导入证据；单测文件存在 |
| `cacheUtil.py` | `缓存` 包装 `ubelt.Cacher`，按 key hash 和目录保存版本文件；`缓存标记` 包装 `ub.CacheStamp` | `cacheUtil.py:19-87` |
| `configUtil.py` | `配置项(configparser.ConfigParser)`，从字符串加载、读写节/项、导出文本/嵌套字典 | `configUtil.py:17-66` |
| `configEnvUtil.py` | `.env` 字符串解析/加载，读写 `os.environ` | `configEnvUtil.py:19-57` |
| `clockUtil.py` | 每次调用创建 APScheduler Blocking/Background scheduler，注册 interval/date job 后立即 `start()` | `clockUtil.py:14-57` |

### 5.4 网络、外部服务与数据适配

- `networkUtil.py`：`网页返回类型` 保存 `源码`、`字节集`、`cookie`、`协议头`、`状态码`、原始 response、JSON；`网页_访问_会话` 和模块函数 `网页_访问` 将 URL、请求方式、参数、cookie、headers、代理、上传文件、JSON、超时映射为 requests 调用（`networkUtil.py:98-237`、`:240-364`）。这是一条已实现的同步 HTTP 调用链，外部网络与证书/响应内容未在本轮验证。
- `seleniumUtil/seleniumUtil.py`：`浏览器类`、`浏览器元素操作` 包装 WebDriver、元素定位、等待、点击、输入、页面导航、Cookie/脚本等；依赖本地浏览器驱动或远程 Selenium，测试使用百度页面并需要驱动/网络（`seleniumUtil.py:1-120`、`seleniumUtil_test.py:8-88`）。实现存在，运行未验证。
- `mysqlUtil.py`：`数据库类`、`游标类` 对 pymysql 连接/游标做中文包装（AST 类证据；完整模块 255 行）；需要数据库连接参数，未在本轮连接验证。
- `orm/peeweeUtil.py`、`orm/mongoUtil.py`、`redis/redisutil.py`：当前文件主要为第三方模块导入/适配入口，不能据此宣称完整 ORM/Redis 数据层；标记为仅部分实现/未验证。
- `alisdk/oss/oss.py`：`获取授权`、`初始化Bucket` 两个类调用 `oss2.Auth`/`Bucket`，提供阿里云 OSS 适配入口；需要真实凭据和网络，未验证。
- `emailUtil.py`：`zmail` 发送邮件适配函数；需要邮件账户/网络，未验证。

### 5.5 编码、文件、媒体与数据交换

- `encoding/compress/egzip.py`、`ezlib.py`、`zip.py`：gzip/zlib 压缩及目录/文件 zip 操作；前两者在公共入口导出，`zip.py` 由编码包提供但不在 `__init__.py` 顶层直接导入。
- `encoding/ebase64/ebase64.py`、`encoding/ebinary/binary.py`、`encoding/url/url.py`：Base64、二进制十六进制、URL quote/unquote；公共入口导出。
- `codeConv.py`：`chardet` 检测编码、文本编码转换、UTF-8/GBK、Base64、MD5/SHA/SHA3/HMAC/CRC32、进制转换；错误被公共装饰器转换为 `False` 的函数范围见 `codeConv.py:52-187`。
- `imageUtil.py`：Pillow 图片对象与 PNG 字节集互转、尺寸读取、显示（`imageUtil.py:19-36`）。
- `qrcode/eqrcode.py`：二维码字节集生成和识别；生成使用 `qrcode`+Pillow，识别使用 `pyzbar`，识别失败返回空文本（`eqrcode.py:26-63`）。
- `excel/excel_openpyxl.py`：`Excel` 类以 workbook/active worksheet 为状态，支持打开/创建、切 sheet、单元格读写、图片、行列尺寸、合并、样式、保存（`excel_openpyxl.py:27-130` 及后续）。`excel_xlwr.py` 是另一套 `xlrd/xlwt/xlutils` 适配。均为文件型持久化，不是数据库模型。
- `chartUtil.py`：matplotlib/numpy 图表类，包括饼图、柱状图、折线图等；绘图对象/图像输出依赖图形后端，未验证。
- `javscript/javscript.py`：`javscript` 类和 `运行js`，经 PyExecJS 选择 Node 等运行时执行/编译脚本；需外部 Node/JS 引擎（`javscript.py:30-69`）。
- `clipBoard.py`、`win32apiUtil.py`：剪贴板和 Windows API 适配；Windows 专有模块不在公共入口导出，跨平台状态未验证。

### 5.8 Excel/Office 专项实现

Excel 支持库不是统一抽象，而是两条互不兼容的后端路径：

```text
调用方
  ├─ pyefun.excel.excel_openpyxl.Excel
  │    └─ openpyxl.Workbook/load_workbook → 当前 Worksheet → XLSX 文件
  └─ pyefun.excel.excel_xlwr
       ├─ xlrd 读取 XLS → 可选 xlutils.copy → xlwt 写回 XLS
       └─ Excel / ExcelSheet / Excel写工作簿 + 样式包装
```

#### `excel_openpyxl.Excel`

- `创建空白工作簿()` 创建 `openpyxl.Workbook` 并把 `active` sheet 放入 `self.st`；`打开Excel()` 使用 `load_workbook()`，没有显式的只读、数据只读、VBA 保留或密码参数。
- `置当前sheet名称()` 修改当前工作表名称；`创建Sheet()` 创建并立即切换到新 sheet；`置当前sheet()` 按名称切换。`取当前sheet对象()` 直接暴露底层 `Worksheet`，调用方可绕过包装器修改状态。
- 单元格行列使用 Excel 风格的 1 基索引，`取某行/列的所有内容()` 以 `max_row/max_column` 为边界，可能包含格式造成的尾部空单元格。
- 支持 XLSX 单元格读写、图片、列宽、行高、合并、背景、对齐、字体、边框、删除 sheet、保存和关闭；源码没有 XLS/CSV/PPT/DOC 转换能力。模块文档标题写成“xls xlsx”，但实现只调用 openpyxl 的 XLSX 工作簿接口，不能据此宣称支持旧 `.xls`。
- `关闭()` 直接调用 `Workbook.close()`；没有 `__enter__/__exit__`、未保存修改检测、异常回滚、临时文件或原子替换。图片路径由第三方库读取，包装层不做清理对账。
- 多个方法体开头的 `pass` 是无效噪声，不构成额外初始化或校验；`删除当前sheet()` 只捕获 `IndexError`，底层名称不存在、工作簿未初始化或只剩一个 sheet 的异常行为没有统一契约。

#### `excel_xlwr` 旧 `.xls` 路径

- `Excel.打开Excel()` 通过 `xlrd.open_workbook()` 建立读工作簿；`编辑=True` 时通过 `xlutils.copy.copy()` 创建 `xlwt` 写工作簿。读取对象和写入对象是两个状态，`ExcelSheet` 只有在编辑模式下才有 `sheetw`。
- `取sheet从索引()`、`取sheet从名称()`、`取sheet数量()`、`取sheet名称()`、行列读取和单元格读取均使用 0 基索引，与 `excel_openpyxl.Excel` 的 1 基索引不同；项目没有统一说明或转换层。
- `ExcelSheet.置内容/置列宽/置行高/置图片*()` 依赖 `sheetw`。以只读方式打开后调用这些方法会在 `None` 上失败；以编辑方式打开后读取 sheet 再写入，写对象通过索引/名称另行取得，两个对象的状态不会自动同步。
- `Excel.保存()` 只适用于 `编辑=True`，但没有参数校验，读模式或未打开状态会产生属性错误；`创建Excel空工作簿()` 返回独立的 `Excel写工作簿` 写路径。
- `Excel字体`、`Excel对齐方式`、`Excel样式`、背景/边框/保护工厂是对 `xlwt` 对象的薄包装。`创建Excel样式()` 的默认参数在函数定义时创建并复用可变样式对象；调用方若修改返回样式，后续调用可能共享状态。
- 该路径依赖旧 BIFF `.xls` 生态：`xlrd` 新版本不支持 `.xlsx`，`xlwt` 只能写 `.xls`；模块名 `excel_xlwr` 是历史拼写，文档和示例必须按源码真实名称引用。

#### 专项事实表

| 后端 | 格式 | 读取 | 写入 | 索引 | 样式/图片 | 当前测试证据 |
|---|---|---|---|---|---|---|
| `excel_openpyxl.Excel` | 实际为 `.xlsx` | `load_workbook` | `Workbook.save` | 1 基 | openpyxl 样式、图片、合并 | 无 Excel 专项测试 |
| `excel_xlwr.Excel` | `.xls` | `xlrd` | 仅 `编辑=True` 时经 `xlutils`/`xlwt` | 0 基 | xlwt 样式、BMP 图片 | 无 Excel 专项测试 |
| `Excel写工作簿` | `.xls` | 不负责读取 | `xlwt.Workbook.save` | 0 基 | xlwt 样式、BMP 图片 | 只有示例调用 |

不要把两套 `Excel` 类视为可替换实现：方法名相似，但文件格式、索引、打开/编辑模型、异常和样式对象均不同。

### 5.6 并发与调度

- `threadingUtil.py`：`启动线程`、`互斥锁`、`递归锁`、`信号量`、`事件锁`、`线程` 管理类、`线程池(ThreadPoolExecutor)`。任务返回 Future，可注册完成回调，`等待()` 调用 shutdown（`threadingUtil.py:21-280`）。
- `processPoolUtil.py`：`进程队列` → `multiprocessing.Queue`；`进程` → `multiprocessing.Process`；`进程池` → `multiprocessing.Pool.apply_async/map_async`，可回调、关闭、终止、等待和读取结果（`processPoolUtil.py:18-92`）。
- `asyncPool/asyncPool.py`：启动独立事件循环线程，使用 `asyncio.Semaphore` 控制协程数量，使用 `queue.Queue` 统计任务，`投递任务` 提交异步函数，`投递任务2` 把阻塞函数放入线程池，支持回调、停止和等待（`asyncPool.py:24-347`）。代码使用 `asyncio.Semaphore(..., loop=...)`、`asyncio.Task.all_tasks(loop=...)` 等旧 API，现代 Python 兼容性未验证。
- `asyncPoolGevent/asyncPoolGevent.py`：导入即 `monkey.patch_all()`，用 `gevent.threadpool.ThreadPool` 投递/等待/关闭任务（`asyncPoolGevent.py:24-59`）。该导入具有全局运行时副作用，需由调用方评估。
- `apscheduler/eapscheduler.py`：间隔/一次性两类函数，阻塞或后台 scheduler 二选一，按 `同时允许的线程数` 设置 `max_instances`（`eapscheduler.py:11-57`）；无统一 scheduler 生命周期对象返回值。

### 5.7 wxefun 桌面 UI

`wxefun/__init__.py:1-5` 汇总 `evt.py`、`func.py`、`component.__init__`、`compatible.py`。

```text
调用方 import pyefun.wxefun as wx
        │
        ├─ evt.py
        │    └─ 事件、鼠标指针、边框、窗口/按钮/文本/标签样式
        │       └─ 常量映射到 wx.EVT_*、wx.CURSOR_*、wx 样式值
        ├─ func.py
        │    └─ 约 169 个窗口/消息/系统/控件辅助函数
        ├─ component/__init__.py
        │    └─ 31 个中文组件模块导出
        │       └─ 每个类通常继承对应 wx 控件与 wxControl.公用方法
        └─ compatible.py
             └─ Button/Frame/TextCtrl/... 英文 wx 类名兼容包装
```

`component/__init__.py:1-31` 是组件导出清单，组件覆盖窗口、容器、按钮、文本框、列表、选择器、日期/时间、进度条、图片等。`compatible.py:8-130` 多数类是中文组件类与 `公用方法` 的空子类，目的是让 `import pyefun.wxefun as wx` 保持接近原生 wx 命名。

`evt.py:102-220` 把大量 wx 事件常量映射成中文类属性；`func.py` 和 `component/wxControl.py` 负责函数及通用属性/事件操作。README:98-146 给出窗口 → 容器 → 按钮/编辑框 → 属性/绑定事件 → `wx.App.MainLoop()` 的端到端示例。该路径源码已实现，但必须有 wxPython、桌面显示和平台事件循环，未在本轮运行验证。

## 6. 数据模型与持久化边界

本项目没有统一数据库实体、迁移、Repository、HTTP API schema 或事件模型。可识别的数据对象如下：

| 数据对象 | 结构/所有权 | 生命周期与持久化 | 状态 |
|---|---|---|---|
| `日期时间` | `self.t` 为 `pendulum.DateTime` | 内存对象，可转文本/时间戳 | 已实现，依赖未验证 |
| `数组` | `self.val` 为 list | 内存，方法多为原地变更 | 已实现 |
| `网页返回类型` | 文本、字节集、cookie、headers、status、raw response、json | 单次 HTTP 调用内存对象 | 已实现，外部请求未验证 |
| `缓存`/`缓存标记` | ubelt 计算 key、缓存目录、扩展名/版本 | 文件系统缓存（默认 `./cache/`） | 已实现，文件权限/并发未验证 |
| `配置项` | `ConfigParser` 的 section/key/value | 从文本加载，导出文本；不自动写文件 | 已实现 |
| `.env` 数据 | dotenv 字典及 `os.environ` | 进程环境变量；可影响后续子进程 | 已实现，环境副作用未验证 |
| `Excel` | `Workbook` + 当前 `Worksheet` | XLSX 文件读写 | 已实现，openpyxl 未验证 |
| 图片/二维码 | Pillow `Image` 与 `bytes` | 内存字节，调用方保存 | 已实现，pyzbar 识别未验证 |
| 线程/进程/协程任务 | Thread/Future/Process/Queue/asyncio loop | 运行时资源，需调用方等待/关闭 | 已实现，资源回收边界需后续复核 |
| wx 控件树 | wx 原生窗口对象及属性/事件绑定 | 桌面进程内存 + wx event loop | 已实现声明，未运行 |
| MySQL/ORM/OSS 等 | 第三方连接/客户端对象 | 外部系统 | 仅适配入口，未验证 |

文件类操作主要由 `dirkBase.py` 提供：`写到文件` 覆盖写二进制，`读入文件` 返回字节，`文件_追加文本` 追加并补换行，`文件_保存` 做简单内容比较后写入（`dirkBase.py:105-135`、`:301-333`）。没有事务、锁、版本号、原子替换或统一编码策略。

## 7. 关键调用链

### 7.1 公共核心函数

```text
调用方
  → pyefun/__init__.py 的 import *
  → 目标中文函数（如 文件_写出/文本_取左边/日期时间）
  → Python 标准库或第三方库
  → 基础值/包装对象

若函数带 @异常处理返回类型逻辑型：
  → try 执行
  → 异常
  → 按全局 异常显示信息 打印 0/1/2 级信息
  → 返回 False
```

证据：`pyefun/__init__.py:1-33`、`public.py:18-65`、`dirkBase.py:60-76`。

### 7.2 HTTP

```text
网页_访问 / 网页_访问_会话.网页_访问
  → 清理 URL，缺协议时补 http://
  → 解析 cookie、协议头、参数、代理、上传文件、json、超时
  → requests.get/post/put/delete/head/options
  → response.text/content/cookies/headers/status_code/json
  → 网页返回类型
```

证据：`networkUtil.py:118-237`、`networkUtil.py:241-364`。静态风险：`网页_取外网IP` 使用外部响应片段 `eval`（`:20-51`）；请求默认 `证书验证=False`（`:118`、`:241`），需后续安全复核。

### 7.3 并发任务

```text
调用方投递函数
  ├─ threadingUtil.线程池.投递任务
  │    → ThreadPoolExecutor.submit → Future → done callback → 等待/shutdown
  ├─ processPoolUtil.进程池.投递任务
  │    → multiprocessing.Pool.apply_async → AsyncResult → callback/error_callback
  ├─ asyncPool.协程池.投递任务
  │    → queue 计数 → run_coroutine_threadsafe
  │    → Semaphore → async 函数 → Future callback/task_done
  └─ asyncPoolGevent.协程池.投递任务
       → gevent ThreadPool.spawn → Greenlet → join/kill
```

这些链路源码存在，但异常传播、取消、池关闭时仍在途任务、跨平台 multiprocessing 启动方式等没有统一契约；本轮不把测试文件存在当作并发语义已验证。

### 7.4 wx UI

```text
wx.App.MainLoop
  → 窗口/容器构造
  → 中文组件构造（继承 wx 控件）
  → 属性别名（公用方法/各组件类）
  → 事件常量（evt.事件）+ 绑定事件
  → wx.EVT_* 回调
  → 调用方中文事件处理函数
```

证据：README:98-146、`wxefun/evt.py:110-220`、`wxefun/component/__init__.py:1-31`、`wxefun/compatible.py:8-130`。

## 8. 接口边界

### 8.1 Python 导入接口

已实现的主要导入方式：

```python
from pyefun import *
import pyefun as efun
from pyefun import networkUtil
from pyefun.asyncPool import 协程池
import pyefun.wxefun as wx
```

公共顶层导出受 `pyefun/__init__.py` 限定；可选模块不应假设会从顶层出现。模块名 `javscript`（缺少一个 `a`）是源码真实名称，不能在文档或调用中擅自改成 `javascript`。

### 8.2 函数/类接口

- 核心函数主要接收 Python 基础类型，返回 Python 基础值；很多“成功”操作返回 `True`，异常装饰器返回 `False`。
- 包装类采用中文方法名，常见状态存放在实例属性，例如 `日期时间.t`、`网页返回类型.源码`、`Excel.wb/st`、`缓存` 的 ubelt 父类状态。
- 网络调用不提供独立 API 服务器或 OpenAPI；`网页_访问` 是本地同步函数。
- wxefun 提供类、常量、属性和事件适配，不改变 wx 的底层事件循环协议。
- 没有 `setup.py` 的 `console_scripts`、CLI 命令或服务启动入口；`setup.py:49-72` 只有 setuptools 包元数据、依赖、包数据和 README 长描述。

### 8.3 外部协议边界

| 边界 | 协议/库 | 入口 | 状态 |
|---|---|---|---|
| HTTP | requests | `networkUtil.py` | 已实现，网络/证书行为未验证 |
| 浏览器自动化 | Selenium WebDriver、Chrome/Firefox 或远程 Selenium | `seleniumUtil.py` | 已实现适配，未验证 |
| GUI | wxPython/wxPython Phoenix | `wxefun/` | 已实现适配，未验证 |
| 文件/XLSX | openpyxl、xlrd/xlwt/xlutils、Pillow | `excel/`、`imageUtil.py` | 已实现适配，未验证 |
| 压缩/编码 | Python gzip/zlib/zip/base64/urllib | `encoding/`、`codeConv.py` | 已实现 |
| JS | PyExecJS + Node 等 | `javscript.py` | 依赖外部运行时，未验证 |
| 数据库 | pymysql、peewee、mongoengine、redis | `mysqlUtil.py`、`orm/`、`redis/` | 部分适配，未验证 |
| 云存储/邮件 | oss2、zmail | `alisdk/oss/`、`emailUtil.py` | 适配入口，未验证 |
| 调度 | APScheduler | `apscheduler/eapscheduler.py` | 已实现，生命周期边界未验证 |

## 9. 依赖与配置

### 9.1 声明依赖

根 `requirements.txt:1-8` 只声明：`ubelt`、`pendulum`、`chardet`、`requests`、`python-dotenv`；注释提到需要剪切板 `pyperclip`、拼音 `pypinyin`。源码直接导入但未在根 requirements 中声明的可选/缺失依赖包括：`wx`、`selenium`、`gevent`、`apscheduler`、`openpyxl`、`xlwt`、`xlrd`、`xlutils`、`PIL/Pillow`、`qrcode`、`pyzbar`、`execjs`、`pymysql`、`peewee`、`mongoengine`、`oss2`、`zmail`、`matplotlib`、`numpy`、`pyperclip`、`pypinyin`、Windows `pywin32` 组件等。此结论来自 AST import 与 requirements 对照，不代表每个模块在所有安装方式中都会被加载。

GitHub CI 的测试工作流 `.github/workflows/python-app.yml:23-30` 额外安装 `pypinyin`、`Pillow`；这进一步证明部分运行依赖依靠 CI/调用方补充，而非完全由根 requirements 解决。

### 9.2 打包与文档配置

- `setup.py:20-30` 读取 requirements；`:51-60` 使用 `find_packages('.')`、`package_data={'': ['*.txt','*.rst','*.md']}`；`:64-72` 设置名称、描述、Apache 2 许可证、作者和项目 URL。
- `setup.py:5-6` 在导入时设置 `TZ=Asia/Shanghai`，具有进程环境副作用。
- `开发笔记..md:1-24` 记录 `setup.py install/develop/clean` 和 Sphinx 生成/预览命令；这是开发笔记，不是自动化脚本契约。
- `docs/source/index.rst:10-18` 加载模块目录、UI、wxefun、帮助和关于页面；`docs/source/model/modules.rst:4-49` 列出核心和工具模块。
- `.github/workflows/python-app.yml` 使用 Python 3.9、安装 pytest/flake8 但实际调用 `python -m unittest`；发布工作流 `.github/workflows/python-publish.yml:28-55` 使用 Python 3.7 构建并在 release/tag 条件下发布 PyPI。两条工作流的 Python 版本不一致，属于发布/兼容性待核项。

### 9.3 运行时配置/副作用

- 缓存默认目录 `./cache/`（`cacheUtil.py:20-41`）。
- 环境变量读取/写入 `os.environ`（`configEnvUtil.py:31-57`）。
- `setup.py` 写入 `TZ`；`asyncPoolGevent` 导入时执行 `monkey.patch_all()`；网络函数默认关闭证书验证；这些都不是集中配置系统，需由调用方承担边界。

## 10. 测试与验证现状

### 10.1 测试结构

仓库中有 36 个 `*_test.py` 跟踪文件，主要使用 `unittest.TestCase`，测试与模块并置。覆盖范围包括算术、数组、缓存、时钟、编码、常用函数、配置、目录、图像、网络、进程池、进度、正则、文本、线程、时间、类型、压缩、Base64、二进制、URL、二维码、JS、Selenium、wx/OSS 等部分模块。

GitHub CI 测试工作流明确运行以下模块：

```text
arithmeticOperationBase_test
arrayActionBase_test
cacheUtil_test
clockUtil_test
codeConv_test
configEnvUtil_test
configUtil_test
imageUtil_test
networkUtil_test
processPoolUtil_test
progiterUtil_test
regexpUtil_test
stringBase_test
stringUtil_test
systemProcessingBase_test
timeBase_test
timeUtil_test
typeConv_test
```

证据：`.github/workflows/python-app.yml:31-54`。CI 明确注释跳过 `commonlyUtil_test`、`dirkBase_test`、`threadingUtil_test`，因为“有问题无法自动测试”；`ewin32api_test.py` 虽被列出但当前为空（AST 统计无测试类/函数）。CI 名称写的是 pytest，但实际命令是 unittest。

### 10.2 测试内容分类

- **行为/单元演示已声明**：`stringBase_test.py`、`arrayActionBase_test.py`、`codeConv_test.py` 等包含 `unittest` 方法；许多方法主要打印结果，断言数量有限。
- **外部依赖/网络测试**：`networkUtil_test.py:8-18` 直接访问外网 IP、`125.la`、百度；不是离线确定性测试。
- **浏览器测试**：`seleniumUtil_test.py:10-45` 使用本地驱动和百度，`:47-88` 使用 `127.0.0.1:4444/wd/hub` 远程浏览器；需要外部环境且测试函数当前代码有 `pass` 开头。
- **协程示例**：`asyncPool_test.py:27-74` 创建 1000 个任务，包含 sleep、回调、线程释放和等待；未在本轮执行。
- **正则测试**：`regexpUtil_test.py:7-107` 大量打印匹配结果，部分测试方法没有断言，因此“测试文件存在”不能等价于行为契约完备。
- **时间测试**：`timeBase_test.py:6-89` 覆盖格式化、分量、加减、差值、时间戳和迭代，但主要打印。

### 10.3 本轮验证结论

本轮实际执行的验证仅包括：Git 基线查询、远程指针查询、文件/目录盘点、Python AST 静态解析。AST 解析结果：当前 `pyefun/` Python 文件无语法解析错误。未执行 `pip install`、`setup.py` 安装、Sphinx 构建、完整 `unittest`、网络请求、浏览器、wx GUI、数据库、OSS、邮件或外部 JS。

因此：

- “源码函数/类存在”可视为已实现静态证据；
- “依赖安装后能运行”“跨平台兼容”“CI 当前通过”“超过 300 个命令全部正确”均为未验证；
- 测试文件和 CI 命令只证明设计了测试路径，不证明本机当前通过。

### 10.4 Excel/Office 测试与示例审计

- 仓库文件名匹配 `*_test.py` 的测试中没有 `excel` 专项测试；CI 的实际 `unittest` 清单也没有加载 `excel_openpyxl` 或 `excel_xlwr`。因此 Excel 的单元格、sheet、样式、图片、保存/重开、错误输入和资源关闭均没有项目级自动化契约。
- `example/excel/excel_openpyxl_使用例子.py` 是可执行式脚本而不是测试：文件末尾直接执行两个流程，会写入 `test.xlsx`/`test2.xlsx`；它依赖 `pyefun` 随机文本函数和相对图片路径，且示例中的 `置图片("d%s" % x, ...)` 把单元格引用传给图片位置参数，路径参数却指向 `../wxefun/1.jpg`，不能当作稳定烟雾测试。
- `example/excel/excel_xlwr使用例子.py` 默认末尾执行 `读入一个列表()`，依赖外部 `test2.xls`、Windows 路径 `C:\python\...\1.bmp` 和第三方 Pillow；示例中 `创建Excel工作簿()` 与实现公开函数 `创建Excel空工作簿()` 名称不一致，后段还调用 `excel.save()`，而实现只有中文方法 `保存()`。该示例按当前源码不能作为成功调用链证据。
- Sphinx 文档只用 `automodule` 自动列出成员，没有说明格式边界、索引基准、编辑状态、依赖安装、异常、资源关闭或两套 API 不可替换；`excel_openpyxl` 标题写“xls xlsx”与实现事实冲突，属于文档漂移。
- `setup.py` 从根 `requirements.txt` 直接读取安装依赖，而该文件只列出 `ubelt`、`pendulum`、`chardet`、`requests`、`python-dotenv`。`openpyxl`、`xlrd`、`xlwt`、`xlutils` 没有声明为安装依赖；Excel 模块只能在调用方额外安装后导入，且导入发生在模块顶层，缺依赖时不是可选能力的延迟失败，而是模块导入失败。

## 11. 已实现、仅声明、未验证总表

| 能力 | 分类 | 当前判断 | 证据/原因 |
|---|---|---|---|
| 中文核心函数聚合 | 已实现 | `__init__.py` 有显式导出，核心模块有函数体 | `pyefun/__init__.py:1-33` |
| 易语言文本/数组/文件/时间/类型映射 | 已实现（静态） | 函数/类体存在 | `stringBase.py`、`arrayActionBase.py`、`dirkBase.py`、`timeBase.py`、`typeConv.py` |
| 公共异常转 `False` | 已实现 | 装饰器有明确 try/except 路径 | `public.py:31-65` |
| wxefun 中文 UI | 已实现适配 | 组件、事件、兼容类均有源码 | `wxefun/__init__.py`、`evt.py`、`component/__init__.py`、`compatible.py` |
| HTTP requests 包装 | 已实现适配 | 同步请求与返回对象路径完整 | `networkUtil.py:108-237` |
| Selenium 自动化 | 已实现适配 | WebDriver/元素类和测试示例存在 | `seleniumUtil.py`、`seleniumUtil_test.py` |
| Excel/图片/二维码 | 已实现适配 | 第三方库包装函数/类存在 | `excel/`、`imageUtil.py`、`qrcode/eqrcode.py` |
| 线程/进程/协程池 | 已实现适配 | 任务提交、回调、等待/关闭方法存在 | `threadingUtil.py`、`processPoolUtil.py`、`asyncPool/` |
| 定时任务 | 已实现适配 | 两个函数构造 scheduler 并注册任务 | `apscheduler/eapscheduler.py:14-57` |
| MySQL/ORM/Redis | 部分实现/未验证 | MySQL 有较完整包装；ORM/Redis 文件短且主要为入口 | `mysqlUtil.py`、`orm/*.py`、`redis/redisutil.py` |
| 统一数据库模型/迁移 | 未发现 | 仓库无 migrations/模型注册/事务层 | 目录盘点与模块读取 |
| HTTP 服务/API/CLI | 未发现 | `setup.py` 无 console script，源码无服务入口 | `setup.py:49-72` |
| 全平台兼容 | 仅声明/未验证 | README 宣称 Windows/macOS/Linux，但可选模块含 wx/win32/驱动差异 | `README.md:22-35`、`win32apiUtil.py` |
| “所有命令 100% 测试” | 仅声明，且与 CI 不完全一致 | README 宣称全部测试；CI 注释跳过 3 个有问题测试 | `README.md:27-29`、`.github/workflows/python-app.yml:38-53` |
| 企业级/高性能框架 | 仅愿景 | 当前结构无统一服务治理/事务/观测/发布契约 | `README.md:20` 与源码结构对照 |

## 12. 风险与后续复核点

以下是静态阅读发现的架构/实现风险，不代表本轮已运行复现：

1. **依赖边界不完整**：根 `requirements.txt` 没有覆盖大量被源码直接导入的可选模块；公共入口的导入链和按需模块的安装行为需要拆分 extras 或逐模块验证。
2. **平台耦合**：`win32apiUtil.py` 依赖 Windows API；wx、Selenium、Pillow、pyzbar、Node、远程浏览器分别依赖 OS/桌面/驱动/系统库。
3. **网络安全默认值**：`networkUtil.py` 多处请求默认 `证书验证=False`，外网 IP 解析用 `eval`；需在后续安全轮次明确可信解析、TLS 与错误策略。
4. **全局副作用**：`setup.py` 设置 `TZ`；gevent 模块导入即 monkey patch；环境变量和文件缓存修改进程/工作目录外部状态。
5. **异常语义不统一**：部分函数用公共装饰器把异常吞掉并返回 `False`，部分函数直接抛出异常，网络会返回空包装对象，二维码识别返回空文本；没有统一错误契约。
6. **可变默认参数**：静态代码中可见若干 `dict={}`、`协议头={}`、`json={}`、`字典参数={}` 形式，需后续检查跨调用污染风险。
7. **资源生命周期**：线程池、进程池、asyncio loop、APScheduler scheduler、浏览器、Excel workbook、HTTP session 的关闭/异常/取消契约分散在调用方；没有统一上下文管理协议。
8. **现代 Python 兼容性待核**：async pool 使用旧 asyncio loop 参数和 `Task.all_tasks` 形式；发布 CI 同时使用 Python 3.7 与 3.9，当前源码年代较早。
9. **测试可重复性不足**：网络、浏览器、GUI、外部数据库/OSS/Node 测试依赖外部环境；多处测试主要 `print`，CI 还显式跳过已知问题模块。
10. **包装 API 语义漂移风险**：部分注释沿用易语言参数说明，但实现直接采用 Python 0 基索引、异常或返回值；例如 `寻找文本` 直接返回 `str.find` 的 0 基位置而注释描述从 1 开始（`stringBase.py:91-102`），需后续以契约测试裁决。
11. **命名与实现细节**：`dirkBase.py`、`javscript/` 等历史命名必须按源码保留；部分函数存在 `pass`、变量遮蔽、宽泛 `except` 或无效/未完成路径，不能在架构文档中包装成完整能力。
12. **文档与源码漂移**：Sphinx `.rst` 是生成/索引文档，README 是愿景和使用说明；二者均需以当前源码复核，不能替代实现证据。

13. **Excel 双后端契约分裂**：同名 `Excel` 类使用不同文件格式和索引基准；调用方若在后端之间切换，可能发生 0/1 基偏移、只读对象写入失败或保存方法名错误。
14. **Excel 依赖与导入边界不完整**：Excel 第三方包未进入根依赖，且模块顶层导入；文档没有给出按后端安装和能力探测方式，导致缺依赖时只能得到原始 `ModuleNotFoundError`。
15. **Excel 示例不可复现**：两个示例都带有自动执行、副作用文件输出、外部路径或 API 名称漂移，不能作为验收命令；应改成显式入口、临时目录和断言式测试后再纳入 CI。
16. **Excel 资源与写入不具事务性**：两个后端都直接保存目标路径，没有原子替换、备份、锁、未保存状态或失败回滚；工作簿/图片/底层 sheet 对象的所有权由调用方隐式承担。

建议的后续深挖顺序：

```text
第一轮（本文件）
  → 第二轮：公共导出/可选依赖/平台矩阵与安装契约
  → 第三轮：并发池资源生命周期、异常传播、取消与现代 asyncio 兼容
  → 第四轮：文件/缓存/Excel/数据库边界与安全写入
  → 第五轮：wx/Selenium/外部服务的运行时验证和测试隔离
  → 第六轮：中文 API 语义与易语言 1 基索引/错误返回契约逐项对照
```

## 13. 本轮证据索引

- 项目描述、安装、使用、wx 示例、贡献约定：`README.md:1-221`
- 打包元数据、版本、依赖读取：`setup.py:1-72`
- 根依赖：`requirements.txt:1-8`
- 开发/文档命令：`开发笔记..md:1-24`
- 公共导出与版本：`pyefun/__init__.py:1-33`
- 异常处理：`pyefun/public.py:18-65`
- 核心文本：`pyefun/stringBase.py:21-225`
- 文本工具：`pyefun/stringUtil.py:18-394`
- 日期时间：`pyefun/timeBase.py:20-168`
- 文件系统：`pyefun/dirkBase.py:45-352`
- 网络：`pyefun/networkUtil.py:98-364`
- 线程/进程/协程：`pyefun/threadingUtil.py:21-280`、`pyefun/processPoolUtil.py:18-92`、`pyefun/asyncPool/asyncPool.py:24-347`、`pyefun/asyncPoolGevent/asyncPoolGevent.py:24-59`
- wx 入口/事件/组件/兼容层：`pyefun/wxefun/__init__.py:1-5`、`evt.py:102-220`、`component/__init__.py:1-31`、`compatible.py:8-130`
- Selenium：`pyefun/seleniumUtil/seleniumUtil.py:1-120`、`seleniumUtil_test.py:8-88`
- Excel/图片/二维码/JS：`pyefun/excel/excel_openpyxl.py:18-130`、`pyefun/imageUtil.py:19-36`、`pyefun/qrcode/eqrcode.py:20-63`、`pyefun/javscript/javscript.py:30-69`
- Excel/Office 专项：`pyefun/excel/excel_openpyxl.py:18-176`、`pyefun/excel/excel_xlwr.py:20-456`、`example/excel/excel_openpyxl_使用例子.py:1-97`、`example/excel/excel_xlwr使用例子.py:1-180`、`docs/source/model/pyefun.excel*.rst`、`setup.py:20-60`、`requirements.txt:1-9`
- 测试 CI：`.github/workflows/python-app.yml:1-55`
- 发布 CI：`.github/workflows/python-publish.yml:1-55`
- Sphinx 入口和模块地图：`docs/source/index.rst:1-43`、`docs/source/model/modules.rst:1-49`
- Git 证据：`git status --short --branch`、`git log -1`、`git remote -v`、`git ls-remote origin HEAD refs/heads/master`；基线为 `e430c5f8d5ad1fa1e06cf79ddba28549036904a7`。

旧 `ARCHITECTURE.md` 和 `细探-*.md` 在建档前均未发现，因此没有旧细探需要吸收或删除；后续只维护本文件，避免形成平行架构事实源。
