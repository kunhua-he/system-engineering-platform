"""测试写入边界门禁：**测试不得假绿**四条判据（债务 #106 + 2026-09-22/23 实测现场）。

本件名里的「写入边界」是**判据一**的落点；判据二、三、四同属「测试不得假绿」一族，
按父任务要求**同件增项**（不另开第二个判据件，避免同类判据散成多条腿），
故件名保留历史、判据面在件内如实列全 —— 读本件先读这张表：

| 判据 | 防的是什么 | 缺口类型常量 | 存量口径 |
|---|---|---|---|
| 一 写仓库内相对路径 | 测试把夹具造进仓库正式根（污染共享状态） | `测试写入-写仓库内相对路径` | 基线内 1 键 / 2 处（只减不增） |
| 一 写动作**未解析**（fail-closed） | 「解析不出」被当放行 ⇒ 判据一全盲（1151/1153 处没判过） | `测试写入-写动作未解析` | 基线内 854 键 / 1151 处（只减不增） |
| 二 只断言「成功」 | 未装配空转 ⇒ `成功=True` 而**什么都没测** | `测试断言-只断言成功` | 基线内 18 条（只减不增） |
| 三 mock 空转 | mock 的环境变量键**在实现里零读取点** | `测试mock-环境变量零读点` | 基线内 0 条 |
| 四 临时根**建了不清**（fail-closed） | `mkdtemp`/`mkstemp` 造出的**根**没人清 ⇒ 每跑一次泄漏一个临时目录 | `测试写入-临时根未清` | 基线内 0 键（本包（P1）收口后现场为 0，只减不增） |

## 判据一：测试只许写 `tempfile` / `工程缓存/` 下的受管目录，禁止写仓库正式根

**现场证据**：2026-09-20 实证一次真实污染 —— `测试中心/开发工具/测试_退出码诚实口径.py`
的**早期版本**把夹具造在仓库里（`支持库/适配层/未生成丙提供者/`、`真实甲提供者/`
两个目录各含一个 `依赖锁.json`，**未跟踪、全仓零引用**），违反 `AGENTS.md`
「测试不得破坏共享状态」。当时已手工清除夹具，但**没有留下机器判据**。

对 `测试中心/**.py` 里每个**写动作**调用，解析其**目标路径表达式的左端基**：

| 左端基 | 判定 |
|---|---|
| 仓库相对字面量（`"支持库/适配层/未生成丙提供者"`、`"模块库"`…） | **判红**（`测试写入-写仓库内相对路径`） |
| `__file__` 派生且表达式里出现仓库内相对字面量（`Path(__file__).parents[2] / "支持库"`） | **判红**（`测试写入-写仓库内相对路径`） |
| `工程缓存` 开头的相对字面量（`"工程缓存/xxx"`） | **放行**（受管目录） |
| 绝对路径 / 环境变量 / 裸文件名等**解析得出、且不落在仓库内相对路径** | **放行**（本判据管的是「仓库相对路径」） |
| `tempfile.mkdtemp(dir=…)` 一族派生**且带 `dir=`**（2026-09-23 修盲点一） | **按 `dir=` 判**（落点由 `dir=` 决定，不由 `tempfile` 决定）：`dir=` 指向 `工程缓存/…` ⇒ **受管写**；指向仓库内相对路径 ⇒ **判红**；指向仓库外绝对路径 ⇒ **放行**；`dir=` 解析不出 ⇒ **未解析** |
| `tempfile.mkdtemp()` 一族派生**不带 `dir=`**（2026-09-23 修盲点二） | **放行**，条件是**运行时临时根**安全 = 在仓库外 **或** 在仓库内**固定排除目录**下；不安全（临时根落在仓库内非固定排除目录）则退回**未解析**（fail-closed）。★ 本档读的是**门禁进程自己**的临时根，**测试进程的读不到** —— 这一半**无法在门禁侧判定**，替代落点是**显式 `dir=`**（见 `_运行时临时根安全`） |
| **解析不出左端基**（外部名字 / 未知函数返回值 / 运行期拼装） | **单列「未解析」档 ⇒ 计入违规**（fail-closed，见下节） |

### 判据一的「未解析」档：不再「解析不出就放行」（2026-09-23 修，债务 #106）

**修的是什么**：本判据原先对「左端基解析不出」的写动作**直接放行**，与平台同族口径相反
—— `运行核心/依赖防火墙.py:359`：「判定路径：**fail-closed，绝不因为解析不出来就静默放行**」。
实测后果（2026-09-23 现场复测）：`测试中心/**.py` 共 **1153** 处写动作，其中 **1151** 处
因「解析不出」被放行、只有 **2** 处真正被判过 ⇒ 门禁如实打印 `判据一 写动作 N 处`，
但那个 N 是「数出来了」而不是「判过了」——**判据一全盲**。

**改成什么**：解析不出的写动作**单列一档「未解析」**（缺口类型
`测试写入-写动作未解析`），**计入违规**，并报出**处数**与**样例（文件:行）**；
放行只留给「解析得出、且确实不落在仓库内相对路径」的那一类
（绝对路径 / 环境变量 / 受管目录 / 裸文件名）。

**为什么必须配「存量冻结」**：1151 处未解析里绝大多数是**合法**的临时夹具写
（`临时根 = tempfile.mkdtemp()` 之后再 `临时根.mkdir()`）—— 静态判不出它不写仓库，
但也不该被当成仓库污染。若直接判红，门禁**一口气全红、等于没有门禁**。
故按 13.2「债务冻结」五态落地：把这 1151 处冻进存量基线（桶 `测试写入-写动作未解析`），
**新增或处数超出即判红**，存量只报不拦但**如实报出处数**。

**写动作面**（必须两个位置都看，否则漏掉真实形态）：

- **接收者位**（`X.mkdir()` / `X.write_text(...)`）—— 历史污染正是这一形态
  （`夹具根.mkdir(parents=True, exist_ok=True)`），只看位置实参的判据对它**全盲**；
- **位置实参位**（`os.mkdir(路径)` / `shutil.rmtree(路径)` / `open(路径, "w")` /
  `shutil.copy2(源, 目标)`）。

`str.replace` **不在**写动作面里：`原文.replace("…", "…")` 是字符串方法，
把它当 `Path.replace` 会产出假红（2026-09-21 实测：`测试中心/运行核心/
测试_跨平台收口原语.py:556` 被误报）。`pathlib.Path` 的改名走 `rename`。

### 写动作面的「接收者位 vs 位置实参位」（2026-09-23 修接收者位缺陷）

**修的是什么**：`_写动作目标` 原先对**接收者写动作**一律先取接收者 —— 那是**方法调用**的语义
（`夹具根.mkdir()` 的目标就是 `夹具根`）。但 `接收者写动作 ∩ 实参写动作` 有 **6 个交叠名字**
（`mkdir`/`makedirs`/`rename`/`rmdir`/`rmtree`/`unlink`），于是**模块限定调用**的目标被取成
**模块名**：`shutil.rmtree(临时根)` → 目标 `['shutil']`；`os.mkdir(路径)` → `['os']`；
`os.rename(源, 目标)` → `['os', '源', '目标']`（既漏判目标、又把**源**当写入目标）。
目标解析不出 ⇒ 落进「未解析」⇒ 这正是判据一「解析不出而放行」盲区的成因之一
（实测：全仓 **132** 处 `shutil.rmtree(…)` 全部被取成模块名、全部落进未解析）。

**改成什么**：交叠名字下，**接收者是模块引用**（`os`/`shutil`/`pathlib`/`tempfile`，含 `os.path`
形态，且**不是**同名局部变量）⇒ 取**位置实参位**（`rename` 取末位实参 = 只判目标）；
**纯方法调用**（接收者是路径表达式）⇒ **保持现行为**（取接收者）。
判定依据见 `_是模块引用`；反向验证：`shutil.rmtree(x)` / `os.mkdir(x)` 改前取模块名、改后取 `x`；
`夹具根.mkdir()` 前后都取 `夹具根`。

## 判据一的两处判据盲点与收口（2026-09-23）

| 盲点 | 现场 | 收口 |
|---|---|---|
| 一 `dir=` 实参不看 | `mkdtemp(...)` **一律**直接判「临时落点 ⇒ 放行」，连 `mkdtemp(dir="模块库")`（仓库内路径）也放行 | 落点**由 `dir=` 决定** ⇒ 核 `dir=` 并**递归判那个表达式**（见 `判目标`） |
| 二 环境错配 | `_临时落点在仓库外()` 核的是**门禁进程自己**的 `tempfile.gettempdir()`；平台跑门禁时 `TMPDIR` 在仓库外、跑测试时被指进仓库 ⇒ 两套环境，判据答的是另一个问题（实测：默认环境 未解析 470/绿；`TMPDIR=仓库根` 时 未解析 1173/555 项违规/红） | 判据不再只看「在不在仓库外」，改为**运行时临时根是否安全**（在仓库外 **或** 在仓库内**固定排除目录**下，见 `_运行时临时根安全`）；★ **测试进程的临时根门禁侧读不到** ⇒ 这一半**无法在门禁侧判定**，如实声明，替代落点是**显式 `dir=`**（使判定与运行环境无关） |

**为什么盲点二的替代落点是「显式 `dir=`」而不是「把无 `dir=` 的一律判未解析」**：
全仓 **664** 处写动作的落点来自 `tempfile` 且**不带 `dir=`**（535 `mkdtemp` + 129
`TemporaryDirectory`），只有 **39** 处带 `dir=`。把无 `dir=` 的一律判未解析 ⇒ 门禁**一口气
全红、等于没有门禁**（与 2026-09-23 未解析档落地时同一条理由：判据要拦**新增**，
不是把存量一口气判红）。故「无 `dir=`」这一档按**运行时临时根**判，并把**门禁侧无法判定**
的那一半**如实印在判据行上**（`判据一` 行尾会打印本次判定所依据的运行时临时根）。

## 判据四：`tempfile` 建出来的**根**必须在 `addCleanup` / 收尾钩子里被清（防「建了不清」）

**现场证据（2026-09-23 实测，本包 P1 收口）**：本判据**上线前**先拿它在改前树上量 ——
`测试中心/**.py` 共 **217** 处临时根，其中 **7 处 / 6 个模块**没人清（`未清 2` + `根不可达 5`），
每跑一次测试就泄漏一个临时目录（跑 N 遍泄漏 N 个）。判据一管的是「落点在哪」
（别造进仓库正式根），**管不到「清没清」**：落点在系统临时目录的夹具同样会长期堆积。
故本判据补的是**清没清**这一半。修完当场复量：**217 处全部已清、违规 0**（见本件 `判据四` 行）。

**判定口径**（逐 `mkdtemp` / `mkstemp` 调用，fail-closed）：

| 情形 | 判定 |
|---|---|
| 根绑定给名字（`X` / `self.X` / `cls.X`），该名字出现在**清理面**任一处 | **放行** |
| 根绑定给名字，清理面上**找不到**该名字 | **判红**（`测试写入-临时根未清`） |
| 根**没绑定**给名字（`Path(mkdtemp()) / "x"` 这类**派生到子路径**、或直接当实参） | **判红**（根不可达 ⇒ 判不出它被清，fail-closed） |
| helper 造根并 `return`，清理在**调用点**做 | 该 helper 的**全部**调用点绑定名都在清理面上才放行（**部分清**同样判红） |
| helper 造根并**自己登记**清理（模块级登记表 + `tearDownModule`，或 helper 内 `addCleanup`） | 放行（一处登记覆盖全部调用点） |

**清理面**（四条等效的清理腿，任一命中即算清过）：

1. `addCleanup(清理原语, 根, …)` / `addClassCleanup(…)` 的实参（含 `addCleanup(lambda: rmtree(根))`
   的 lambda 体内清理调用的实参）；
2. `tearDown` / `tearDownClass` / `tearDownModule` / `doCleanups` 函数体里的清理调用实参；
3. **`try` 的 `finally` / `except` 体**里的清理调用实参（用例失败路径也跑，与 `addCleanup` 等效）；
4. 模块级登记表 `表.append(根)`，且该表在 `tearDownModule` 里被 `for … in 表` 消费。

**清理原语**（`清理调用名`）= `清只读后删除树` / `rmtree` / `rmdir` / `unlink` / `remove` / `删除树`。
**为什么清理面上要找的是「名字」而不是「值」**：静态判不出两个表达式指向同一路径，
按名字判是**唯一可静态落地**的口径；代价是「清了一个同名的别的变量」会算作已清 ——
这一半如实声明为**漏报**，但**假绿方向**被「名字必须真的出现在清理调用里」卡住（不是看到
清理词就算过）。

**为什么「根没绑定给名字」也判红（fail-closed）**：`Path(mkdtemp(...)) / "x.json"` 里
**只有派生出来的那个文件路径**有名字，根**没有名字** ⇒ 静态判不出根被清 —— 而这正是
本判据要防的形态（判据一侧实测过同一形态：`测试_公开调用完整性门禁.py` 把**文件路径**
交给 `addCleanup(清只读后删除树, …)`，目录树原语对文件必然失败、`忽略失败=真` 只留痕 ⇒
**根全程无人清**）。与判据一同口径：**解析不出 ⇒ 计入违规**，不猜。

## 判据二：测试断言必须看**业务字段**，不能只看 `成功`（防「未装配空转假绿」）

**现场证据（2026-09-22 实测，已提交 dd1123a0）**：
`测试中心/支持库/测试_语义索引.py` 的 `test_合法调用` 在 `python3.14 -m unittest` 下
`成功=True`，但**什么都没测** —— `建代码索引` 内部 `收集代码块` 要经 `能力调用器`，
而本仓 unittest 环境**没有装配**（`[E未装配] 能力调用器未注入且无惰性装配钩子`）
⇒ 每个文件都被跳过 ⇒ 块列表为空 ⇒ 在
`支持库/后端/代码解析支持库/语义索引/实现/语义索引.py:62` **早退**返回「成功（块数 0）」。
返回值里 `块数=0` / `文件数=0` / `跳过清单` 全是被跳的文件 ——
**只看 `成功` 的断言与「真的索引出了东西」在这一刻长得一模一样**。

口径：逐**用例**（`def test_*`）收它全部断言调用；若**每一条**断言的判定表达式
都只由 `X.成功` 构成（出现下标 / 比较 / 别的字段 / 断言里再调用 ⇒ 不算），
该用例进**待核清单**。真源说明：`成功` 只回答「流程没抛异常」，不回答
「产出物里有东西」；业务字段（`块数` / `文件数` / `错误码` / `值` / `跳过清单`…）
才是那条断言真正想看的东西。

## 判据三：mock 的环境变量键必须在**实现面**有读取点（防 mock 空转）

**同族陷阱（同一批修掉的）**：mock 一个**实现里不存在**的环境变量开关也是空转 ——
原 `test_提供者不可用` mock 了 `语义索引_禁用库`，而 `git grep` 证明该变量
**全仓只出现在测试自己**，实现里零命中；且实现里根本没有 `提供者不可用` 这个错误码。

口径：取 `mock.patch.dict(os.environ, {键: …})` 的**字符串键**，反查该键在
**实现面**（`公共契约.正式根.遍历源码` 的 `.py` + `.json`，**排除 `测试中心/`**）
有没有出现点。零命中时**再排除「测试内自洽」**：若该键在测试中心里还出现在
**别的位置**（不是那个 mock 字典的键），说明测试自己造了消费者（例：
`测试_LibreOffice双腿行为差异.py` 往临时目录写一个假 `soffice` 脚本，脚本里
`os.environ.get("FAKE_LO_COUNTER")` 读它）⇒ 不算空转。两者都零命中 ⇒ **空转**。

## 口径边界（如实声明，不假装扫到了）

- **裸文件名**（`open("结果.json", "w")`）判不出是「仓库根」还是「cwd」——
  它既不匹配任何仓库内相对路径、也无法静态判定运行期 cwd，故判据一**放行**
  （放行的理由是「解析得出、且不落在仓库内相对路径」，**不是**「解析不出」）；
- 目标路径由**运行期拼装**（读配置/环境变量后再拼）的写法、以及未知函数的**返回值**
  （`环境目录(真实提供者目录, 摘要)` 的实参是本仓路径、返回值却是 `工程缓存/提供者运行环境/…`）
  静态解析不出来 ⇒ 归入**「未解析」档并计入违规**（fail-closed），**不猜**
  —— 这一类是「未解析」档的主要来源，靠**处数冻结**兜住存量、靠**处数比对**拦住新增；
- 判据一/二/四只覆盖 `测试中心/`；判据三的**反查面**是「除 `测试中心/` 外的全仓源码」；
- 判据四的**名字口径**（如实声明，不假装精确）：清理面上比对的是**名字**（`根` / `self.根`），
  不是值 —— 静态判不出两个表达式指向同一路径。故「清了**同名的另一个变量**」会被算作已清，
  这是**漏报**方向（**不是**假绿：判据仍要求该名字真的出现在清理调用里，且 `self.X` 还要
  核对**类归属**与基类链）；另一半「名字出现 ≠ 真的删干净」判不了（运行时才知道），
  本判据只管**有没有清理动作**；
- 判据四**不覆盖** `TemporaryDirectory` 上下文管理器（`with … as 根:` 退出即清，属语言保证）；
  也不覆盖**子进程脚本模板字符串**里的 `mkdtemp`（那是子进程自己造的根，本进程不持有
  —— `测试中心/运行核心/测试_平台准入.py` 属这一档，如实不算它的面）；
- 判据二按**用例**判（不是按断言）：一条用例里只要有一处业务断言，整条用例就不进待核
  —— 「有业务断言」是它真的看过产出的证据；这会漏掉「一行业务断言 + 九行只看成功」的
  用例，属**如实声明的漏报**，不假装是全覆盖。

## fail-closed（本项目核心纪律）

- 扫描面为空（`测试中心` 不存在，或一个 `.py` 都没扫到）→ 判红（空集不是通过）；
- 某个 `.py` **解析不了**（语法错/读不成/解码错）→ 判红，**不静默跳过**
  —— 跳过等于把「这份测试写了什么未知」压成「它没写仓库」；
- 判据一的**未解析**档 → 计入违规（解析不出**不等于**没写仓库，见上文）；
- 存量基线**缺失 / 读不成 / 形状非法 / 缺桶** → 判红（「存量已登记」的唯一凭据没了，
  不许静默按空基线判绿）。

## 存量与阻断（13.2 五态：基线内只报不拦，基线外新增判红，只减不增）

各判据面各有自己的存量桶，逐条**具名登记**在
`开发工具/测试写入边界门禁存量基线.json`（桶键 = 判据面里的唯一标识，
**不含行号** —— 行号一改基线就失效，那是把基线做成易碎品）。
桶值有两种等价写法：**字符串数组**（简写 = 每个桶键允许 **1** 处）与
**「桶键 → 允许处数」对象**（同一桶键允许多处）。比对按**处数**（不是集合）：
同一桶键现场处数**超过**登记处数同样判红 —— 与 `第三方导入分布基线门禁` 同口径
（「处数也是被冻结的量」）；低于登记处数只留痕。

- 判据一桶键 = `文件::动作::目标`（**未解析**档的「目标」位是目标表达式的源码文本，
  如 `临时根 / "结果.json"`）；判据二桶键 = `文件::类名.用例名`；判据三桶键 = `文件::键`。
  判据二的桶键**带类名**：同一文件里两个类各有一个同名用例是实际存在的
  （`测试中心/支持库/测试_文档生成.py` 的 DOCX 类与 XLSX 类各有一个
  `test_最小有效文件与签名`），只用「文件::用例名」会让两条并成一条 ——
  存量数不清、收敛判定跟着错。
- 当前（2026-09-23 现场实测）存量 **872 键 / 1170 处**：判据一「写仓库内相对路径」
  **1** 键 / **2** 处
  （`测试中心/平台控制面/测试_文件租约.py` 往**真实** `模块库/开工编排/实现/开工编排.py`
  写一个字节再在 `finally` 里还原 —— 并行维修期这会把**别人刚改的内容回滚成旧内容**，
  故如实登记为存量、不许它增长；修好该测试后须**下调**基线）、
  判据一「未解析」**854** 键 / **1151** 处、判据二 **18** 键（现场 17 处，1 键收敛）、
  判据三 **0** 键。
  （未解析档的处数随 `测试中心/` 新增测试而增长 —— 这正是「新增一处即判红」要拦的；
  2026-09-23 落地当天就实拦到一次：并行会话往
  `测试中心/开发工具/测试_薄壳返回可控.py` 新加 3 处未解析写（2 处处数超出 + 1 处新键），
  门禁当场判红并逐条报出「处数 1 → 2（超出基线 1 处）」。
  合法新增的出口是**显式重新登记本基线**并进提交，见 `--存量明细`。）
- 基线里多于现场的条目 = **收敛**，只留痕（提示下调基线），不判红。
- 判据二的已知**假红形态**（如实声明，不假装精确）：用例里用**非断言语句**做验证的写法
  会被列进待核 —— 例：`测试中心/开发工具/测试_支持库模板生成器.py::test_生成文件可编译`
  在 `assertTrue(结果.成功)` 之后用 `py_compile.compile(..., doraise=True)` 真编译产物。
  这类条目是「待核」不是「判红」，人工核完把桶键留在基线里即可。

## 用法

    python3.14 -m 开发工具.测试写入边界门禁              # 跑门禁（四条判据）
    python3.14 -m 开发工具.测试写入边界门禁 --根 <目录>    # 覆盖扫描根（反向验证用）
    python3.14 -m 开发工具.测试写入边界门禁 --只报        # 只打印不判红（排查用）
    python3.14 -m 开发工具.测试写入边界门禁 --存量明细     # 逐条打印存量键（重建基线用）

退出码：0 = 通过（含「基线内 N 键 / M 处存量」）；1 = 判红；2 = 用法错误。
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

仓库根 = Path(__file__).resolve().parents[1]
if str(仓库根) not in sys.path:
    sys.path.insert(0, str(仓库根))

from 公共契约.正式根 import 遍历源码
from 公共契约.基础类型.逻辑类型 import 真, 假

#: 扫描根（相对仓库根）。
扫描根名 = "测试中心"

#: 唯一受管落点：仓库内相对路径只许落在这里（`工程缓存/` 是生成式缓存区）。
受管目录名 = "工程缓存"

#: 缺口类型常量（报告逐条打印；反向验证按这些字符串断言）。
缺扫描面 = "测试写入-扫描面为空"
缺源码不可解析 = "测试写入-源码不可解析"
写仓库内相对路径 = "测试写入-写仓库内相对路径"
未解析写动作 = "测试写入-写动作未解析"
临时根未清 = "测试写入-临时根未清"
只断言成功 = "测试断言-只断言成功"
mock空转 = "测试mock-环境变量零读点"
缺存量基线 = "测试写入-存量基线不可用"

#: 存量基线的五个桶名（**顺序即报告顺序**；缺桶 = 形状非法 ⇒ 判红）。
#: 「未解析」桶紧跟「写仓库内相对路径」—— 两者同属判据一（判据一现在有两档）；
#: 「临时根未清」桶紧跟两者 —— 判据四与判据一同属「临时目录该建得干净、也该清得干净」一族。
存量桶名 = (写仓库内相对路径, 未解析写动作, 临时根未清, 只断言成功, mock空转)

#: 桶名 → 统计里的判据键（报告打印用，避免在打印处再写一遍 if 链）。
#: 「未解析」单列 `判据一·未解析`：判据一有两档，共用 `判据一` 会互相覆盖存量统计。
判据键 = {写仓库内相对路径: "判据一", 未解析写动作: "判据一·未解析",
        临时根未清: "判据四", 只断言成功: "判据二", mock空转: "判据三"}

#: 未解析档：报告里**样例（文件:行）**的条数上限（存量上千处，逐条打印会把判据行淹掉）。
未解析样例上限 = 5
#: 未解析档：`--存量明细` 之外，逐条打印存量桶键的条数上限（其余只报处数）。
存量明细上限 = 5

#: 存量基线落点。
存量基线路径 = 仓库根 / "开发工具" / "测试写入边界门禁存量基线.json"

#: 接收者位写动作（路径在 `节点.func.value`）。
接收者写动作 = frozenset({
    "mkdir", "makedirs", "touch", "write_text", "write_bytes", "unlink", "rmdir",
    "rmtree", "rename", "chmod", "symlink_to", "link_to", "truncate",
})
#: 位置实参位写动作（路径在 `节点.args`）。
#: ★ 已知覆盖缺口（只报不改）：本平台自己的删树原语 `清只读后删除树`
#: （`公共契约.运行时.平台适配`）**不在**本面内 ⇒ 判据对它全盲。不纳入的原因：纳入后
#: `测试中心/运行核心/测试_清只读删除与落盘跨平台.py` 里几处「目标来自方法返回值/元组解包」
#: 的调用会新判出未解析（新增即红），而那属该文件的存量写法，不在本包范围内。
#: 处置建议：单独一包把该原语纳入写动作面，并同步修那几处夹具根写法。
实参写动作 = frozenset({
    "mkdir", "makedirs", "remove", "unlink", "rmdir", "rmtree", "rename",
    "open", "copy", "copy2", "copyfile", "copytree", "move",
})
#: 两个位置实参都是路径的写动作（源、目标）—— **只判目标**（末位实参）。
#: 判源会假红：`shutil.copytree(系统根 / "开发工具" / "发布门禁", 隔离根 / …)`
#: 的源是本仓路径（**读**），把它当写入目标会当场判红（2026-09-22 实测：
#: `测试中心/第一批维修/测试_发布门禁.py:219` 被误报）。
双路径写动作 = frozenset({"copy", "copy2", "copyfile", "copytree", "move"})

#: 左端基回溯时**只认**这些路径构造器：别的调用返回值解析不出来（见 `左端基`）。
#: `join` 另走 `_是os_path` 判定 —— `str.join` 与 `os.path.join` 同名不同义。
路径构造器名 = frozenset({"Path", "PosixPath", "WindowsPath", "PurePath",
                     "PurePosixPath", "PureWindowsPath", "str"})

#: 路径方法（接收者是路径、返回值仍是路径）：基随**接收者**。
路径方法名 = frozenset({"resolve", "absolute", "expanduser", "joinpath",
                    "with_name", "with_suffix"})

#: **临时落点构造器**（2026-09-23 扩解析器）：`tempfile` 一族**证明**返回系统临时目录下的
#: 绝对路径（`tempfile.gettempdir()`），静态即可判 —— 按判据表首条「绝对路径 ⇒ 放行」同一档，
#: 不再掉进「未解析」。
#: ★ 2026-09-23 修盲点一：`tempfile` 一族的落点**由 `dir=` 决定**（`dir=` 缺省时才回落
#: `tempfile.gettempdir()`）—— 故 `dir=` 必须核（见 `_取临时落点dir实参` 与 `判目标`）。
#: 落点是否真安全由 `_运行时临时根安全()` 运行期核（运行时临时根落在仓库内非固定排除目录
#: 时本档失效、仍走 fail-closed 未解析）。
临时落点构造器 = frozenset({
    "mkdtemp", "mkstemp", "gettempdir", "TemporaryDirectory",
    "NamedTemporaryFile", "TemporaryFile", "SpooledTemporaryFile",
})

#: `tempfile` 一族里 `dir=` 可能落在**第 3 位置实参**的名字（标准库签名 `(suffix, prefix, dir)`）。
#: `NamedTemporaryFile` 一族签名是 `(mode, buffering, encoding, newline, suffix, prefix, dir, …)`，
#: 位置位不固定 ⇒ 只认关键字位（本仓写位置实参的形态为零，实测）。
临时落点三参名 = frozenset({"mkdtemp", "mkstemp", "TemporaryDirectory"})

#: **模块引用名**：`os.mkdir(x)` / `shutil.rmtree(x)` 的接收者是**模块**、目标在位置实参位
#: （见 `_写动作目标` 的接收者位/位置实参位分派与 `_是模块引用`）。
模块引用名 = frozenset({"os", "shutil", "pathlib", "tempfile"})

#: `_运行时临时根安全()` 的结果缓存（每次门禁跑一次解析，不必每处重算）。
_运行时临时根缓存: bool | None = None


def _固定排除目录表() -> tuple[str, ...]:
    """仓库的**固定排除目录**（**唯一事实源** = `开发工具/项目编译/工作区指纹.py`，不复制清单）。"""
    from 开发工具.项目编译.工作区指纹 import 固定排除目录
    return tuple(固定排除目录)


def _运行时临时根安全() -> bool:
    """运行时临时根会不会把落点带进仓库**正式根**（安全 = 不会）。

    安全 = 临时根在仓库外 **或** 在仓库内的**固定排除目录**下。后一半的依据：判据一防的是
    「污染正式根 / 工作区指纹」，而 `开发工具/项目编译/工作区指纹.py` 的未跟踪腿用
    `git ls-files --others -z`（**不带** `--exclude-standard`）⇒ 只认 `固定排除目录`/
    `固定排除文件`，`.gitignore` 保不住工作区；落点落在固定排除目录下时，即便被 SIGKILL
    残留也进不了指纹。

    ★ **如实声明（本档无法在门禁侧判定的那一半）**：本函数读的是**门禁进程自己**的
    `tempfile.gettempdir()`。**测试进程**的 `TMPDIR` 门禁侧**读不到** —— 平台跑门禁与跑测试
    是两套环境（2026-09-23 实测：默认环境 未解析 470 / 退出码 0（绿）；`TMPDIR=仓库根` 时
    未解析 1173 / 555 项违规 / 退出码 1（红））。故本档只能回答「**门禁进程**所处环境是否安全」，
    **不能**回答「**测试运行时**是否安全」。收口手段（替代落点）：让落点**显式**指向受管目录
    —— `tempfile.*(dir=…)` 指向 `工程缓存/`，使判定**与运行环境无关**（见 `判目标`）。
    解析不出 / 取不到一律不认（fail-closed，不静默放行）。
    """
    global _运行时临时根缓存
    if _运行时临时根缓存 is None:
        try:
            临时 = Path(tempfile.gettempdir()).resolve()
            根 = 仓库根.resolve()
            if 临时 != 根 and 根 not in 临时.parents:
                _运行时临时根缓存 = 真
            else:
                # 在仓库内：只有落在**固定排除目录**下才算安全（见上）。
                相对 = 临时.relative_to(根)
                _运行时临时根缓存 = any(
                    str(相对) == 排除 or str(相对).startswith(排除 + "/")
                    or 排除 in 相对.parts for 排除 in _固定排除目录表())
        except Exception:  # noqa: BLE001 —— 解析不出即不认（fail-closed，不静默放行）
            _运行时临时根缓存 = 假
    return _运行时临时根缓存


def 运行时临时根说明() -> str:
    """本次判定所依据的**运行时临时根**（打印用）—— 门禁侧只能观测到自己那一份。"""
    try:
        临时 = Path(tempfile.gettempdir()).resolve()
    except Exception:  # noqa: BLE001
        return "<解析不出>"
    安全 = "安全" if _运行时临时根安全() else "不安全"
    return f"{临时}（门禁进程自己的；{安全}）"


def _取临时落点dir实参(调用: ast.AST) -> ast.expr | None:
    """`tempfile` 一族的 `dir=` 实参；没有 `dir=` 返回 None（落点回落 `tempfile.gettempdir()`）。

    关键字位优先；`mkdtemp`/`mkstemp`/`TemporaryDirectory` 另认第 3 位置实参
    （标准库签名 `(suffix, prefix, dir)`），见 `临时落点三参名`。
    """
    if not isinstance(调用, ast.Call):
        return None
    for 关键字 in 调用.keywords:
        if 关键字.arg == "dir":
            return 关键字.value
    if isinstance(调用.func, ast.Attribute):
        名 = 调用.func.attr
    elif isinstance(调用.func, ast.Name):
        名 = 调用.func.id
    else:
        名 = ""
    if 名 in 临时落点三参名 and len(调用.args) >= 3:
        return 调用.args[2]
    return None


def _取临时落点调用(沿途: list[ast.AST]) -> ast.AST | None:
    """沿途表达式里**最先**出现的 `tempfile` 构造调用（`dir=` 就挂在它身上）。

    为什么要搜而不是取 `沿途[0]`：`临时 = Path(tempfile.mkdtemp())` 之后再
    `临时 / "x"` 时，沿途是 `[Path(tempfile.mkdtemp()), tempfile.mkdtemp()]` ——
    `沿途[0]` 是外层 `Path(...)`，`dir=` 挂在**内层**那个调用上。
    """
    for 表达式 in 沿途:
        for 子 in ast.walk(表达式):
            if isinstance(子, ast.Call) and _是临时落点构造器(子.func):
                return 子
    return None


def _是临时落点构造器(被调: ast.AST) -> bool:
    """`tempfile.mkdtemp(...)`（模块限定）或 `mkdtemp(...)`（from-import）形态。"""
    if isinstance(被调, ast.Attribute):
        return (被调.attr in 临时落点构造器
                and isinstance(被调.value, ast.Name) and 被调.value.id == "tempfile")
    return isinstance(被调, ast.Name) and 被调.id in 临时落点构造器


def _是模块引用(表达式: ast.AST, 变量表: dict[str, ast.AST]) -> bool:
    """`os` / `shutil` / `pathlib` / `tempfile`（含 `os.path` 形态）的**模块引用**。

    为什么要判它：`_写动作目标` 对**接收者写动作**优先取接收者（方法调用 `夹具根.mkdir()`
    的目标就是 `夹具根`）；但 `os.mkdir(x)` / `shutil.rmtree(x)` 的接收者是**模块**、
    目标在**位置实参位** —— 两集合交叠的 6 个名字（`mkdir`/`makedirs`/`rename`/`rmdir`/
    `rmtree`/`unlink`）此前一律取接收者，目标于是取成 `os`/`shutil`，解析不出 ⇒ 未解析
    （实测全仓 132 处 `shutil.rmtree(…)` 全落进未解析）。

    为什么加「**不在变量表里**」这一条：同名局部/模块级变量（`path = Path(…)`）优先按**变量**
    算 —— 否则 `path.mkdir()` 会被当成模块调用、目标取成空 ⇒ 整个写动作**漏判**（比假红更糟）。
    """
    if isinstance(表达式, ast.Name):
        名 = 表达式.id
    elif isinstance(表达式, ast.Attribute) and isinstance(表达式.value, ast.Name):
        名 = 表达式.value.id
    else:
        return 假
    return 名 in 模块引用名 and 名 not in 变量表

#: 判据二：业务字段的反面 —— 这个字段名单独成立时说明不了「测到了东西」。
成功字段名 = "成功"
#: 判据二：单值断言的**判定表达式只取首位实参**（`assertTrue(expr, msg=None)`）。
单值断言名 = frozenset({"assertTrue", "assertFalse"})
#: 判据二：双值断言的判定表达式取前两位（第三位起是 `msg`）。
双值断言名 = frozenset({
    "assertEqual", "assertNotEqual", "assertIs", "assertIsNot", "assertIn",
    "assertNotIn", "assertGreater", "assertGreaterEqual", "assertLess",
    "assertLessEqual", "assertIsNone", "assertIsNotNone", "assertRegex",
    "assertNotRegex", "assertCountEqual", "assertAlmostEqual", "assertIsInstance",
})


def _是os_path(被调: ast.AST) -> bool:
    """``os.path.join`` / ``path.join`` 形态（**排除** `"sep".join(...)` 这类字符串方法）。"""
    if not isinstance(被调, ast.Attribute) or 被调.attr != "join":
        return 假
    接收 = 被调.value
    if isinstance(接收, ast.Name):
        return 接收.id in ("path", "os")
    return (isinstance(接收, ast.Attribute) and 接收.attr == "path"
            and isinstance(接收.value, ast.Name) and 接收.value.id == "os")


def _仓库内顶层目录名() -> set[str]:
    """仓库内相对路径的**首段白名单**：仓库根下实际存在的目录 ∪ 正式根 ∪ 源码层。

    用「实际存在的顶层目录」而不是写死清单：新增正式根时判据自动跟上
    （写死清单会让新根下的写入漏检，且属第二事实源）。
    """
    from 公共契约.正式根 import 正式根名表, 源码层名表
    名 = {p.name for p in 仓库根.iterdir() if p.is_dir()}
    名 |= set(正式根名表) | set(源码层名表)
    return 名


def 像仓库内相对路径(文本: str) -> bool:
    """该字面量是否形如「仓库内相对路径」（首段是仓库顶层目录名，且不是绝对路径）。"""
    净 = 文本.strip().lstrip("./")
    if not 净 or 净.startswith(("/", "~")):
        return 假
    return 净.split("/")[0] in _仓库内顶层目录名()


def 是受管路径(文本: str) -> bool:
    """该字面量是否指向受管目录（`工程缓存/…` 或 `工程缓存` 本身）。"""
    净 = 文本.strip().lstrip("./")
    return 净 == 受管目录名 or 净.startswith(受管目录名 + "/")


# ---------------------------------------------------------------------------
# 判据一：写动作目标的左端基
# ---------------------------------------------------------------------------

def 左端基(节点: ast.AST, 变量表: dict[str, ast.AST], 深度: int = 0,
        实例定义域: dict[str, dict[str, ast.AST]] | None = None
        ) -> tuple[str, str, list[ast.AST], dict[str, ast.AST]] | None:
    """路径表达式的**左端基**：``("字面量", 文本, 沿途表达式, 作用域表)`` / ``("__file__", "", …, 表)`` / ``None``。

    只有「最左端那个字面量」能说明这条路径**从哪生根**：
    `临时根 / "支持库"` 的左端基是 `临时根`（不是 `"支持库"`），
    而 `"支持库/适配层/x"` 的左端基就是它自己 —— 前者是受管临时目录下的
    合法夹具，后者是写进仓库。按「调用实参里出现过仓库路径字面量」判会把
    前者全判红（2026-09-21 实测：`测试中心` 里 23 条候选**全部**是这种假红）。

    第三个元素是**沿途表达式**（含回溯到的变量值）：`__file__` 派生时
    `Path(__file__).parents[2] / "支持库" / "适配层"` 的仓库内字面量散落在
    整条表达式与变量值里，只看调用实参本身（可能只是一个名字 `根`）会漏判
    —— 反向验证实测过这一条漏判。

    `None` = 解析不出（外部名字、未知函数返回值、运行期拼装等）⇒ 判「未解析」（fail-closed）。
    `tempfile.mkdtemp()` 一族**不在此列**：它们返回临时目录下的绝对路径，单列「临时落点」档，
    由 `判目标` 核 `dir=`（有则递归判落点、无则按运行时临时根判 —— 见 `_运行时临时根安全`）。

    第四个元素是**解析这个基所用的作用域表**。为什么必须带上它：`self.X` 的基在 `self.X`
    的**定义处**作用域里解析 —— `setUp` 里 `夹具根 = 仓库根 / "工程缓存" / …` 是 `setUp`
    的**局部名**，在用例方法的作用域里找不到；若拿**使用处**的表去解析 `dir=夹具根`，
    会把它假判成「未解析」（反向验证实测：`测试中心/支持库/测试_原子写失败目标逐字不变.py`
    的夹具根就是这么写的）。
    """
    域 = 实例定义域 or {}
    if 深度 > 24:
        return None
    if isinstance(节点, ast.Constant) and isinstance(节点.value, str):
        return ("字面量", 节点.value, [节点], 变量表)
    if isinstance(节点, ast.Name):
        if 节点.id == "__file__":
            return ("__file__", "", [节点], 变量表)
        if 节点.id in 变量表:
            值 = 变量表[节点.id]
            内 = 左端基(值, 变量表, 深度 + 1, 域)
            if 内 is None:
                return None
            return (内[0], 内[1], [值, *内[2]], 内[3])
        return None
    if isinstance(节点, ast.BinOp) and isinstance(节点.op, ast.Div):
        左 = 左端基(节点.left, 变量表, 深度 + 1, 域)
        if 左 is None:
            return None
        右 = 左端基(节点.right, 变量表, 深度 + 1, 域)
        return (左[0], 左[1], [*左[2], *(右[2] if 右 else [])], 左[3])
    if isinstance(节点, ast.Attribute):
        # `self.X`（夹具根常在 `setUp` 里造）——按**类级**收集到的绑定回溯，
        # 否则 `self.临时 / "支持库"` 的左端基是 `self`（外部名字）⇒ 未解析。
        # ★ 用**定义处**的作用域表解析绑定值（见函数 docstring 第四个元素）。
        if isinstance(节点.value, ast.Name) and 节点.value.id == "self":
            名 = "self." + 节点.attr
            属性值 = 变量表.get(名)
            if 属性值 is not None:
                内 = 左端基(属性值, 域.get(名, 变量表), 深度 + 1, 域)
                if 内 is None:
                    return None
                return (内[0], 内[1], [属性值, *内[2]], 内[3])
        return 左端基(节点.value, 变量表, 深度 + 1, 域)
    if isinstance(节点, ast.Call):
        # **只认路径构造器与路径方法**，别的调用一律解析不出 ⇒ 放行。
        # 为什么不能取「args[0] 当基」：`环境目录(真实提供者目录, 摘要)` 的
        # args[0] 是本仓路径，但**返回值是 `工程缓存/提供者运行环境/…`**
        # （`运行核心/运行环境管理器/环境管理器.py:198`）⇒ 按 args[0] 判会把
        # 受管写入报成仓库写入（2026-09-22 实测：`测试中心/运行核心/
        # 测试_强制校验.py:191` 被误报）。未知函数的返回值静态解析不出来，
        # 如实归入「解析不出」这一档，不猜。
        #
        # 两类必须认：
        #   · 构造器（`Path(...)` / `os.path.join(...)`）—— 基是 args[0]；
        #   · 路径方法（`Path(__file__).resolve()` / `.joinpath(x)`）—— 基是**接收者**。
        #     漏掉第二类会连 `Path(__file__).resolve().parents[2] / "支持库"`
        #     这一整条最典型的形态都解析不出（反向验证实测过这条漏判）。
        #
        # 第三类（2026-09-23 扩解析器）：**临时落点构造器**（`tempfile.mkdtemp()` 一族）
        # ——返回值是临时目录下的绝对路径，静态可判 ⇒ 单列 `临时落点` 档，
        # 由 `判目标` 核 `dir=` 与运行时临时根（见 `_运行时临时根安全`）。
        被调 = 节点.func
        if _是临时落点构造器(被调):
            return ("临时落点", "", [节点], 变量表)
        if isinstance(被调, ast.Attribute):
            名 = 被调.attr
        elif isinstance(被调, ast.Name):
            名 = 被调.id
        else:
            名 = None
        if 名 in 路径方法名 and isinstance(被调, ast.Attribute):
            return 左端基(被调.value, 变量表, 深度 + 1, 域)
        if 名 in 路径构造器名 and 节点.args:
            return 左端基(节点.args[0], 变量表, 深度 + 1, 域)
        if 名 == "join" and _是os_path(被调) and 节点.args:
            return 左端基(节点.args[0], 变量表, 深度 + 1, 域)
        return None
    if isinstance(节点, ast.Subscript):
        return 左端基(节点.value, 变量表, 深度 + 1, 域)
    if isinstance(节点, (ast.List, ast.Tuple)) and 节点.elts:
        return 左端基(节点.elts[0], 变量表, 深度 + 1, 域)
    return None


def 判目标(目标: ast.AST, 变量表: dict[str, ast.AST], 深度: int = 0,
        实例定义域: dict[str, dict[str, ast.AST]] | None = None) -> tuple[str, str]:
    """``(结论, 证据)``：结论 ∈ ``{"仓库内写", "受管写", "放行", "未解析"}``。

    `未解析` = 左端基解析不出来（外部名字 / 未知函数返回值 / 运行期拼装）。
    **它不再被当放行**（fail-closed）：解析不出**不等于**没写仓库，
    调用方把它单列一档、计入违规，由存量基线按处数冻结（见模块 docstring）。
    `放行` 只留给「解析得出、且确实不落在仓库内相对路径」的那一类。

    `深度` 只给 `tempfile` 一族的 `dir=` **递归判**用（`dir=…` 本身可能又是临时落点）。
    `实例定义域` 见 `左端基` 的第四个元素：`dir=` 必须在**它的书写处**作用域里解析。
    """
    if 深度 > 8:
        return "未解析", ""
    基 = 左端基(目标, 变量表, 实例定义域=实例定义域)
    if 基 is None:
        return "未解析", ""
    类, 值, 沿途, 基作用域表 = 基
    if 类 == "临时落点":
        # `tempfile` 一族的落点**由 `dir=` 决定**（`dir=` 缺省时才回落 `tempfile.gettempdir()`）
        # —— 故先核 `dir=`（修盲点一）：
        #   · 有 `dir=` ⇒ 落点**静态可判** ⇒ 递归判那个表达式
        #     （`dir=工程缓存/…` ⇒ 受管写；`dir="模块库"` ⇒ 仓库内写；`dir="/tmp"` ⇒ 放行；
        #      `dir=函数参数` 解析不出 ⇒ 未解析）；解析用**基作用域表**（书写处）。
        #   · 无 `dir=` ⇒ 落点 = **运行时临时根**，按环境判（修盲点二，见 `_运行时临时根安全`：
        #     该档只能答「门禁进程所处环境」，测试进程的临时根门禁侧读不到 ⇒ 如实声明）。
        dir实参 = _取临时落点dir实参(_取临时落点调用(沿途))
        if dir实参 is not None:
            return 判目标(dir实参, 基作用域表, 深度 + 1, 实例定义域)
        return ("放行", "") if _运行时临时根安全() else ("未解析", "")
    if 类 == "字面量":
        if 是受管路径(值):
            return "受管写", 值
        if 像仓库内相对路径(值):
            return "仓库内写", 值
        return "放行", ""
    # `__file__` 派生：**整条表达式链**里的字面量都要看
    # （`Path(__file__).parents[2] / "支持库"`，可能还经过一层变量）。
    字面量们 = [子.value for 表达式 in [目标, *沿途] for 子 in ast.walk(表达式)
             if isinstance(子, ast.Constant) and isinstance(子.value, str)]
    for 文 in 字面量们:
        if 是受管路径(文):
            return "受管写", 文
    for 文 in 字面量们:
        if 像仓库内相对路径(文):
            return "仓库内写", 文
    return "放行", ""


def _表达式文本(节点: ast.AST) -> str:
    """目标表达式的源码文本 —— 「未解析」桶键的判别段（`unparse` 失败时退回节点类型名）。

    为什么用表达式文本当判别段：未解析档的「目标」位解析不出**值**，
    但表达式的**形状**（`临时根 / "结果.json"`、`shutil`、`self.工作根`）是稳定可读的
    唯一标识 —— 与判据一另一档的「目标 = 仓库内路径字面量」同构。
    """
    try:
        return ast.unparse(节点)
    except Exception:  # ast.unparse 对合法 AST 不会失败；留兜底不静默丢键
        return f"<{type(节点).__name__}>"


def _赋值收集(节点: ast.AST, 表: dict[str, ast.AST]) -> None:
    """把 `节点` 下**本层作用域**的 `名字 = 表达式` 收进 `表`（不进嵌套函数/类）。

    不进嵌套定义是必须的：同名变量在不同方法里可以指完全不同的东西
    （`目标 = 环境目录(self.提供者目录, …)` 与 `目标 = 环境目录(真实提供者目录, …)`
    在同一份测试里各出现一次），把两层压成一张表会让判据按**另一个方法**的绑定
    去判当前这一处 —— 那正是「用 A 处的证据判 B 处」的假红。
    """
    for 子 in ast.iter_child_nodes(节点):
        if isinstance(子, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(子, ast.Assign) and len(子.targets) == 1 \
                and isinstance(子.targets[0], ast.Name):
            表.setdefault(子.targets[0].id, 子.value)
        elif isinstance(子, ast.AnnAssign) and isinstance(子.target, ast.Name) \
                and 子.value is not None:
            表.setdefault(子.target.id, 子.value)
        elif isinstance(子, ast.With):
            # `with tempfile.TemporaryDirectory(…) as 临时:` —— 绑定名拿到的就是上下文
            # 表达式的值（临时目录）。不认这一支，`根 = Path(临时)` 整片解析不出
            # （2026-09-23 实测：测试_退出码诚实口径.py 的 `with tempfile.TemporaryDirectory()`
            # 夹具根就是这么来的）。
            for 项 in 子.items:
                if isinstance(项.optional_vars, ast.Name):
                    表.setdefault(项.optional_vars.id, 项.context_expr)
        _赋值收集(子, 表)


def _全文件实例属性(树: ast.AST, 变量表: dict[str, ast.AST]
                ) -> tuple[dict[str, ast.AST], dict[str, dict[str, ast.AST]]]:
    """``(绑定表, 定义域表)``：**文件级** `self.X = 表达式` 绑定（键 `self.X`），供 `左端基` 解析夹具根。

    为什么要文件级而不是按类收：夹具根常定义在**基类/mixin** 的 `setUp` 里、
    在**子类**的用例里用（`清只读夹具.setUp` 造 `self.根`，`Test清只读后删除树` 用它；
    `假环境根夹具.建假环境根` 用子类 `setUp` 造的 `self.临时`）——只按类体收就整片漏。

    为什么要「同类」守卫（**不跨类硬合并**）：不同类可以有同名 `self.X` 指完全不同的东西
    （一个指临时根、一个指仓库内相对路径）。只在**全部绑定解析出同一个左端基类**、
    且属于下面两类可安全合并的情形之一时才认这个名字：

    - 全部是 `临时落点`（各绑定是**不同**的临时目录也安全：落点类别决定判定，与具体值无关）；
    - 全部**同形**（`ast.dump` 逐字相同）—— 值不同的字面量类绑定不合并，
      否则会把 A 类的仓库内写按 B 类的受管路径判放行（假绿）。

    其余一律不认、落回「未解析」档（fail-closed：宁可多报，不可误放行）。

    **定义域表**（键 `self.X` → 该绑定的**书写处**作用域表）：绑定表达式会被搬到别的作用域里用，
    而它可能引用书写处的**局部名**（`setUp` 里 `夹具根 = 仓库根 / "工程缓存" / …` 再
    `self.临时目录 = Path(tempfile.mkdtemp(dir=夹具根))`）—— 拿使用处的表去解析 `dir=夹具根`
    会假判未解析（反向验证实测）。故必须把书写处的表一并带出。
    """
    分组: dict[str, list[ast.AST]] = {}
    定义域: dict[str, list[dict[str, ast.AST]]] = {}
    for 子, 作用域表 in _带作用域(树, 变量表):
        if isinstance(子, ast.Assign) and len(子.targets) == 1:
            目标 = 子.targets[0]
        elif isinstance(子, ast.AnnAssign) and 子.value is not None:
            目标 = 子.target
        else:
            continue
        if isinstance(目标, ast.Attribute) and isinstance(目标.value, ast.Name) \
                and 目标.value.id == "self":
            名 = "self." + 目标.attr
            分组.setdefault(名, []).append(子.value)
            定义域.setdefault(名, []).append(作用域表)
    out: dict[str, ast.AST] = {}
    域: dict[str, dict[str, ast.AST]] = {}
    for 名, 表达式们 in 分组.items():
        基类集 = {左端基(表达式, 变量表)[0] if 左端基(表达式, 变量表) else None
                for 表达式 in 表达式们}
        if len(基类集) != 1:
            continue
        if 基类集 == {"临时落点"} or len({ast.dump(表达式) for 表达式 in 表达式们}) == 1:
            out[名] = 表达式们[0]
            域[名] = 定义域[名][0]
    # 定义域表必须**同时看得见全部 `self.X` 绑定**：书写处的局部表里只有局部名
    # （`_赋值收集` 不收 `self.X = …` 这种属性目标），而绑定表达式自身可能引用别的
    # `self.Y`（`self.根 = Path(self._临时.name).resolve()` 就引用了 `self._临时`）
    # —— 不补这一手，用定义域表解析反而比用使用处的表更差（反向验证实测：补前
    # `self.根` 判未解析、补后判「临时落点」）。
    for 表 in 域.values():
        表.update(out)
    return out, 域


def _带作用域(节点: ast.AST, 表: dict[str, ast.AST]):
    """逐节点产出 ``(节点, 该节点所属作用域的表)``；函数/类体用自己的表（叠加外层）。"""
    for 子 in ast.iter_child_nodes(节点):
        if isinstance(子, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            内层 = dict(表)
            _赋值收集(子, 内层)
            yield 子, 内层
            yield from _带作用域(子, 内层)
        else:
            yield 子, 表
            yield from _带作用域(子, 表)


def _写动作目标(节点: ast.Call, 变量表: dict[str, ast.AST]) -> tuple[str, list[ast.expr]]:
    """``(动作名, 目标表达式列表)``；不是写动作时动作名为空串。

    **接收者位 vs 位置实参位**（2026-09-23 修接收者位缺陷，见模块 docstring 同名小节）：

    - `名 ∈ 接收者写动作` **且接收者不是模块引用** ⇒ **方法调用**，目标在**接收者位**
      （`夹具根.mkdir()`、`Path(x).mkdir()`）；
    - `名 ∈ 接收者写动作` **但接收者是模块引用** ⇒ **模块限定调用**，目标在**位置实参位**
      （`os.mkdir(x)` / `shutil.rmtree(x)` / `os.makedirs(x, exist_ok=True)`）。
      交叠的 6 个名字不这样分派，目标就会被取成模块名 `os`/`shutil` ⇒ 解析不出 ⇒ 未解析。
    """
    if isinstance(节点.func, ast.Attribute):
        名 = 节点.func.attr
        接收者 = 节点.func.value
        if 名 in 接收者写动作 and not _是模块引用(接收者, 变量表):
            # 接收者位就是路径（`夹具根.mkdir()`）；rename 的第二位置实参也是路径。
            目标们: list[ast.expr] = [接收者]
            if 名 == "rename":
                目标们 += list(节点.args)
            return 名, 目标们
        if 名 in 双路径写动作:
            return 名, _取写入目标(节点.args)
        if 名 in 实参写动作 and _是模块引用(接收者, 变量表):
            # **模块限定**调用才走位置实参位（`os.mkdir(x)` / `os.remove(x)` /
            # `os.rename(源, 目标)`）。为什么必须挂「是模块引用」这一条：不挂的话
            # `sys.path.remove(str(适配层))`（**列表**方法，不是文件写）会被取成
            # `remove` 的写入目标、按 `__file__` 派生判成「写仓库内相对路径」
            # —— 反向验证实测过这处假红。
            if 名 == "rename":
                return 名, _取写入目标(节点.args)
            return 名, list(节点.args[:1])
        return "", []
    if not isinstance(节点.func, ast.Name):
        return "", []
    名 = 节点.func.id
    if 名 not in 实参写动作:
        return "", []
    if 名 == "open":
        模式 = ""
        if len(节点.args) > 1 and isinstance(节点.args[1], ast.Constant) \
                and isinstance(节点.args[1].value, str):
            模式 = 节点.args[1].value
        if not any(旗标 in 模式 for 旗标 in ("w", "a", "x", "+")):
            return "", []
    if 名 in 双路径写动作 or 名 == "rename":
        return 名, _取写入目标(节点.args)
    return 名, list(节点.args[:1])


def _取写入目标(实参们: list[ast.expr]) -> list[ast.expr]:
    """源/目标双参形态里**只取目标**（末位实参）；只有一位时它就是目标。"""
    return [实参们[-1]] if len(实参们) >= 2 else list(实参们[:1])


# ---------------------------------------------------------------------------
# 判据二：只断言「成功」的用例
# ---------------------------------------------------------------------------

def _是断言调用(节点: ast.AST) -> bool:
    """`self.assertTrue(...)` / `assertEqual(...)` 形态（`assert*` 一族）。"""
    return isinstance(节点, ast.Call) and isinstance(节点.func, ast.Attribute) \
        and 节点.func.attr.startswith("assert")


def _断言判定表达式(调用: ast.Call) -> list[ast.expr]:
    """断言里**参与判定**的表达式（把 `msg` 那一位摘掉，避免消息文本被当业务字段）。"""
    参数 = list(调用.args)
    名 = 调用.func.attr if isinstance(调用.func, ast.Attribute) else ""
    if 名 in 单值断言名:
        return 参数[:1]
    if 名 in 双值断言名:
        return 参数[:2]
    return 参数


def 只看成功字段(参数们: list[ast.expr]) -> bool:
    """这些判定表达式是否**只**由 `X.成功` 构成。

    出现下标 / 比较 / 别的字段名 / 断言里再调用函数 ⇒ 判定它真的看了业务字段。
    """
    有成功 = False
    for 参数 in 参数们:
        for 子 in ast.walk(参数):
            if isinstance(子, ast.Attribute):
                if 子.attr != 成功字段名:
                    return 假
                有成功 = True
            elif isinstance(子, (ast.Subscript, ast.Compare, ast.Call, ast.BinOp)):
                return 假
            elif isinstance(子, ast.UnaryOp) and not isinstance(子.op, ast.Not):
                return 假
    return 有成功


#: 判据二：**辅助断言方法**名里的标记 —— `self.断言OOXML签名(...)` / `self.校验XX(...)`
#: 这类调用本身就是业务验证（实测假红样本：`测试中心/支持库/测试_文档生成.py`
#: 的 `self.断言OOXML签名("xlsx", 结果.值.字节)`），不把它们算业务验证会假红。
辅助断言标记 = ("断言", "校验", "核对", "验证")


def _是辅助断言(节点: ast.Call) -> bool:
    return isinstance(节点.func, ast.Attribute) \
        and any(标记 in 节点.func.attr for 标记 in 辅助断言标记)


def _收集用例(树: ast.AST) -> list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, str]]:
    """``(用例节点, 限定名)`` —— 限定名 = `类名.用例名`（模块级用例只有用例名）。

    为什么带类名：同一文件里**两个类各有一个同名用例**是实际存在的
    （`测试中心/支持库/测试_文档生成.py` 的 DOCX 类与 XLSX 类各有一个
    `test_最小有效文件与签名`），只用「文件::用例名」当桶键会让两条并成一条
    —— 存量基线于是数不清，收敛判定也跟着错。
    """
    出: list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, str]] = []

    def 走(节点: ast.AST, 前缀: str) -> None:
        for 子 in ast.iter_child_nodes(节点):
            if isinstance(子, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if 子.name.startswith("test"):
                    出.append((子, f"{前缀}{子.name}"))
            elif isinstance(子, ast.ClassDef):
                走(子, f"{前缀}{子.name}.")

    for 顶层 in getattr(树, "body", []):
        if isinstance(顶层, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if 顶层.name.startswith("test"):
                出.append((顶层, 顶层.name))
        elif isinstance(顶层, ast.ClassDef):
            走(顶层, f"{顶层.name}.")
    return 出


# ---------------------------------------------------------------------------
# 判据三：mock 环境变量键零读点
# ---------------------------------------------------------------------------

def _是mock字典调用(节点: ast.AST) -> bool:
    """`mock.patch.dict(...)` / `patch.dict(...)` 形态。"""
    return (isinstance(节点, ast.Call)
            and isinstance(节点.func, ast.Attribute) and 节点.func.attr == "dict"
            and isinstance(节点.func.value, ast.Attribute)
            and 节点.func.value.attr == "patch")


def _mock字典键(树: ast.AST) -> tuple[list[tuple[str, int]], set[int]]:
    """``(键们, 键节点 id 集)`` —— 键节点 id 集用于把「mock 自己那一处」排除在「其他出现」外。"""
    键们: list[tuple[str, int]] = []
    键节点: set[int] = set()
    for 节点 in ast.walk(树):
        if not _是mock字典调用(节点) or not isinstance(节点, ast.Call):
            continue
        for 参 in 节点.args:
            if not isinstance(参, ast.Dict):
                continue
            for 键 in 参.keys:
                if isinstance(键, ast.Constant) and isinstance(键.value, str):
                    键们.append((键.value, 键.lineno))
                    键节点.add(id(键))
    return 键们, 键节点


# ---------------------------------------------------------------------------
# 扫描
# ---------------------------------------------------------------------------

def _测试文件表(根: Path) -> list[Path]:
    测试根 = 根 / 扫描根名
    if not 测试根.is_dir():
        return []
    return sorted(p for p in 测试根.rglob("*.py") if "__pycache__" not in p.parts)


def _读并解析(文件: Path) -> tuple[ast.AST | None, str]:
    """``(树, 错误说明)``；读不成/语法错时树为 None、错误说明非空（调用方判红）。"""
    try:
        源码 = 文件.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as 错误:
        return None, f"读不成（{type(错误).__name__}）"
    try:
        return ast.parse(源码), ""
    except SyntaxError as 错误:
        return None, f"语法错（{错误.msg}）"


def 扫描写入(根: Path) -> tuple[list[dict], dict]:
    """判据一：``(违规, 统计)``；统计里含「受管写」「放行」「未解析」计数 —— 证明判据确实看过了写动作。

    为什么要有统计：只报「违规 0 条」的判据无法自证它看过任何东西
    （扫描面为空与真的干净长得一模一样，正是 A-3 那类自证恒绿）。
    **「写动作数」本身不是自证**：1135 处里 1133 处曾被「解析不出」放行（判据一全盲），
    故统计必须把「判过了多少」拆开 —— `仓库内写` / `受管写` / `放行写` / `未解析` 四项之和
    才等于 `写动作数`，其中 `未解析` 计入违规、由存量基线冻结。
    """
    根 = Path(根)
    违规: list[dict] = []
    统计 = {"文件数": 0, "写动作数": 0, "受管写": 0, "放行写": 0, "仓库内写": 0,
           "未解析": 0, "未解析样例": [], "不可解析": 0}
    文件表 = _测试文件表(根)
    for 文件 in 文件表:
        统计["文件数"] += 1
        相对 = 文件.relative_to(根).as_posix()
        树, 错误 = _读并解析(文件)
        if 树 is None:
            统计["不可解析"] += 1
            违规.append({"文件": 相对, "行": 0, "动作": "-", "目标": "-",
                         "缺口类型": 缺源码不可解析, "桶键": f"{相对}::-::-",
                         "详情": f"{错误} ⇒ 这份测试写了什么未知，不静默跳过"})
            continue
        变量表: dict[str, ast.AST] = {}
        _赋值收集(树, 变量表)
        # 文件级 `self.X` 夹具根绑定（跨类收：基类/mixin 的 setUp 造的根在子类用例里用），
        # 连同**书写处作用域表**（`dir=` 必须在书写处解析，见 `_全文件实例属性`）。
        实例属性, 实例定义域 = _全文件实例属性(树, 变量表)
        变量表.update(实例属性)
        for 节点, 作用域表 in _带作用域(树, 变量表):
            if not isinstance(节点, ast.Call):
                continue
            动作, 目标们 = _写动作目标(节点, 作用域表)
            if not 动作:
                continue
            for 目标 in 目标们:
                统计["写动作数"] += 1
                结论, 证据 = 判目标(目标, 作用域表, 实例定义域=实例定义域)
                if 结论 == "仓库内写":
                    统计["仓库内写"] += 1
                    违规.append({
                        "文件": 相对, "行": 节点.lineno, "动作": 动作, "目标": 证据,
                        "缺口类型": 写仓库内相对路径, "桶键": f"{相对}::{动作}::{证据}",
                        "详情": (f"写动作 {动作} 的目标是**仓库内相对路径** `{证据}` ⇒ "
                                 "违反「测试只许写 tempfile / 工程缓存 下的受管目录」；"
                                 "夹具应建在 tempfile.mkdtemp()/TemporaryDirectory() 里"
                                 "并 addCleanup 清理"),
                    })
                elif 结论 == "未解析":
                    # fail-closed：解析不出**不是**放行的理由（同族口径见
                    # `运行核心/依赖防火墙.py:359`）。单列一档、计入违规，
                    # 存量由基线按「文件::动作::表达式」的**处数**冻结。
                    统计["未解析"] += 1
                    表达式 = _表达式文本(目标)
                    if len(统计["未解析样例"]) < 未解析样例上限:
                        统计["未解析样例"].append(f"{相对}:{节点.lineno}")
                    违规.append({
                        "文件": 相对, "行": 节点.lineno, "动作": 动作, "目标": 表达式,
                        "缺口类型": 未解析写动作, "桶键": f"{相对}::{动作}::{表达式}",
                        "详情": (f"写动作 {动作} 的目标表达式 `{表达式}` **静态解析不出左端基**"
                                 "（外部名字 / 未知函数返回值 / tempfile 派生 / 运行期拼装）⇒ "
                                 "判不出它是否写进仓库正式根；fail-closed：计入违规，"
                                 "存量按「文件::动作::表达式」的处数冻结，"
                                 "新增或处数超出即判红"),
                    })
                elif 结论 == "受管写":
                    统计["受管写"] += 1
                else:
                    统计["放行写"] += 1
    if not 文件表:
        违规.append({"文件": 扫描根名, "行": 0, "动作": "-", "目标": "-",
                     "缺口类型": 缺扫描面, "桶键": f"{扫描根名}::-::-",
                     "详情": f"{根 / 扫描根名} 下未发现任何 .py ⇒ 扫描面为空，"
                             "空集不是通过（fail-closed）"})
    return 违规, 统计


# ---------------------------------------------------------------------------
# 判据四：临时根建了没清
# ---------------------------------------------------------------------------

#: 判据四的**清理原语**（清理面上被点名即算「清过」）。与写动作面分开列：写动作面收了
#: `mkdir`/`copy2` 一类**造**的动作，这里只要**销毁**的动作。
清理调用名 = frozenset({"清只读后删除树", "rmtree", "rmdir", "unlink", "remove", "删除树"})

#: 判据四的收尾钩子（它们的函数体跑在**用例失败之后**，与 `addCleanup` 同一条腿）。
收尾钩子名 = frozenset({"tearDown", "tearDownClass", "tearDownModule", "doCleanups"})

#: 判据四的清理登记调用（`unittest.TestCase` 自带）。
清理登记名 = frozenset({"addCleanup", "addClassCleanup"})

#: 接收者是路径、且是**销毁**动作的名字（`根.rmdir()` / `锁.unlink()` 形态）。
销毁式接收者名 = frozenset({"rmdir", "unlink", "rmtree", "清只读后删除树", "删除树"})

#: 判据四认的临时根构造器（`tempfile` 一族里**造目录/文件后缀名**的两个）。
临时根构造器 = frozenset({"mkdtemp", "mkstemp"})


def _函数名(节点: ast.AST) -> str:
    """`X.attr` / `name` 的末段名；其余空串。"""
    if isinstance(节点, ast.Attribute):
        return 节点.attr
    if isinstance(节点, ast.Name):
        return 节点.id
    return ""


def _名字引用(节点: ast.AST) -> set[str]:
    """表达式里出现的**名字**引用集（判据四的「名字口径」，见模块 docstring）。

    - `Name` / `Attribute` ⇒ 其源码文本（`根` / `self.临时`）；
    - `Path(x)` / `str(x)` ⇒ 递归取 `x`（包装不改变它指的是哪个目录）；
    - `a / b` ⇒ 两边都取（`self.根 / "不存在"` 里 `self.根` 是真名字）。
    """
    if isinstance(节点, (ast.Name, ast.Attribute)):
        return {_表达式文本(节点)}
    if isinstance(节点, ast.Call) and _函数名(节点.func) in ("Path", "str") and 节点.args:
        return _名字引用(节点.args[0])
    if isinstance(节点, ast.BinOp) and isinstance(节点.op, ast.Div):
        return _名字引用(节点.left) | _名字引用(节点.right)
    出: set[str] = set()
    for 子 in ast.iter_child_nodes(节点):
        出 |= _名字引用(子)
    return 出


def _是临时根调用(节点: ast.AST) -> bool:
    """`tempfile.mkdtemp(...)`（模块限定）或 `mkdtemp(...)`（from-import）形态。"""
    if not isinstance(节点, ast.Call):
        return 假
    被调 = 节点.func
    if isinstance(被调, ast.Attribute):
        return (被调.attr in 临时根构造器
                and isinstance(被调.value, ast.Name) and 被调.value.id == "tempfile")
    return isinstance(被调, ast.Name) and 被调.id in 临时根构造器


def _父节点表(树: ast.AST) -> dict[int, ast.AST]:
    父: dict[int, ast.AST] = {}
    for 节点 in ast.walk(树):
        for 子 in ast.iter_child_nodes(节点):
            父[id(子)] = 节点
    return 父


def _根表达式(调用: ast.AST, 父: dict[int, ast.AST]) -> tuple[ast.AST, bool]:
    """从临时根调用上溯到**它自己的根表达式**；返回 ``(表达式, 是否派生到子路径)``。

    上溯两种包裹（都不改变「根是哪个目录」）：
    - `Path(tempfile.mkdtemp(...))` / `str(tempfile.mkdtemp(...))` —— 外层是构造器；
    - `Path(tempfile.mkdtemp(...)) / "x.json"` —— **派生到子路径**：派生出来的那条
      **文件路径**才是被赋名的东西，根**没有名字**（`子路径=真`）。
    """
    节点 = 调用
    子路径 = 假
    while id(节点) in 父:
        上 = 父[id(节点)]
        if isinstance(上, ast.Call) and _函数名(上.func) in ("Path", "str") \
                and 上.args and 上.args[0] is 节点:
            节点 = 上
            continue
        if isinstance(上, ast.BinOp) and isinstance(上.op, ast.Div):
            子路径 = 真
            if id(上) not in 父:
                return 上, 子路径
            更上 = 父[id(上)]
            if isinstance(更上, ast.Call) and _函数名(更上.func) in ("Path", "str"):
                节点 = 更上
                continue
            return 上, 子路径
        break
    return 节点, 子路径


def _根绑定名(根表达式: ast.AST, 父: dict[int, ast.AST]) -> list[str]:
    """根表达式被赋给了哪些名字（`x` / `self.x` / `cls.x`）；没有被赋名 ⇒ 空列表。

    为什么是**列表**：`mkstemp` 的标准形态是**元组解包**
    （`句柄, 路径 = tempfile.mkstemp()`），根被拆成两个名字接住
    —— 只认单名会把这一整类判成「根没绑定」（假红，实测踩过）。
    """
    p = 父.get(id(根表达式))
    目标表: list[ast.AST] = []
    if isinstance(p, ast.Assign) and len(p.targets) == 1:
        目标表 = [p.targets[0]]
    elif isinstance(p, ast.AnnAssign) and isinstance(p.target, ast.AST):
        目标表 = [p.target]
    出: list[str] = []
    for 目标 in 目标表:
        if isinstance(目标, (ast.Name, ast.Attribute)):
            出.append(_表达式文本(目标))
            continue
        for 子 in ast.walk(目标):
            if isinstance(子, (ast.Name, ast.Attribute)):
                出.append(_表达式文本(子))
    return 出


def _所在函数(节点: ast.AST, 父: dict[int, ast.AST]) -> ast.AST | None:
    当前 = 节点
    while id(当前) in 父:
        if isinstance(当前, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return 当前
        当前 = 父[id(当前)]
    return None


def _类结构表(树: ast.AST) -> tuple[dict[str, list[str]], list[ast.ClassDef]]:
    """``(类名 → 基类名列表, 全部类节点)`` —— 供 `_所属类` 与基类链回溯用。"""
    基类表: dict[str, list[str]] = {}
    全部类: list[ast.ClassDef] = []
    for 节点 in ast.walk(树):
        if isinstance(节点, ast.ClassDef):
            全部类.append(节点)
            基类表[节点.name] = [基.id for 基 in 节点.bases if isinstance(基, ast.Name)]
    return 基类表, 全部类


def _所属类(全部类: list[ast.ClassDef], 节点: ast.AST) -> str:
    """`节点` 最内层的**所属类名**；不在任何类里 ⇒ 空串（模块级）。"""
    最佳名 = ""
    最小规模: int | None = None
    for 类 in 全部类:
        if not any(子 is 节点 for 子 in ast.walk(类)):
            continue
        规模 = sum(1 for _ in ast.walk(类))
        if 最小规模 is None or 规模 < 最小规模:
            最小规模 = 规模
            最佳名 = 类.name
    return 最佳名


def _祖先链(基类表: dict[str, list[str]], 类名: str) -> set[str]:
    """类名 → 它自己 + 全部祖先类名（含基类链，防「根在子类、清理在基类」被误判）。"""
    出: set[str] = set()
    待 = [类名]
    while 待:
        当前 = 待.pop()
        if not 当前 or 当前 in 出:
            continue
        出.add(当前)
        待.extend(基类表.get(当前, []))
    return 出


def _清理面名字(树: ast.AST) -> tuple[set[str], dict[str, set[str]]]:
    """判据四的**清理面**：被清理动作点过名的名字集（四条等效清理腿，见模块 docstring）。

    返回 ``(文件级名字集, self.X/cls.X 名字 → 提供清理证据的类名集)``。

    ★ 为什么不是「文件里出现过清理词」：那会把「清了别的目录」算成本根已清（假绿）。
    本函数只在**清理调用真的点到了某个名字**时才把它记进清理面。

    ★ 为什么要按**类**再分一张表（2026-09-23 反向验证实测）：同一文件里两个类各有一个
    同名 `self.工作`（`测试_SwiftCompiler提供者.py` 的 `Test编译源代码` 与 `Test签名`
    就是这么写的）—— 只按文件级收名字，删掉前者的 `addCleanup` 后者的登记会替它顶包
    ⇒ **弄坏不红**（反向验证第一拍拍到过）。故 `self.X` / `cls.X` 的证据必须归到
    **它所在的类**（含基类链），判根时再按「根所在类 ∈ 证据类」比对。
    """
    证据: set[str] = set()
    证据类: dict[str, set[str]] = {}
    基类表, 全部类 = _类结构表(树)

    def _记(名: str, 提供处: ast.AST | None = None) -> None:
        证据.add(名)
        if 名.startswith(("self.", "cls.")) and 提供处 is not None:
            证据类.setdefault(名, set()).add(_所属类(全部类, 提供处))

    # ④ 模块级登记表：`tearDownModule` 里 `for 夹具 in 表: 清只读后删除树(夹具, …)`
    # ★ 必须核**循环体里真的对循环变量调了清理**：只认「表出现在 tearDownModule 的 for 里」
    # 会把空转收尾（`for 夹具 in 表: pass`）算成已清 —— 反向验证拍5 实测过这一处 fail-open。
    登记表: set[str] = set()
    for 节点 in ast.walk(树):
        if not (isinstance(节点, (ast.FunctionDef, ast.AsyncFunctionDef))
                and 节点.name == "tearDownModule"):
            continue
        for 子 in ast.walk(节点):
            if not isinstance(子, ast.For):
                continue
            变量名 = _表达式文本(子.target)
            if not any(
                    函数名 in 清理调用名
                    and any(变量名 in _名字引用(参) for 参 in 调用.args)
                    for 语句 in 子.body for 调用 in ast.walk(语句)
                    if isinstance(调用, ast.Call)
                    for 函数名 in [_函数名(调用.func)]):
                continue
            登记表.add(_表达式文本(子.iter).split(".")[-1])
    # ① addCleanup / addClassCleanup
    for 节点 in ast.walk(树):
        if not (isinstance(节点, ast.Call) and _函数名(节点.func) in 清理登记名):
            continue
        for 参 in list(节点.args[1:]) + [k.value for k in 节点.keywords]:
            for 名 in _名字引用(参):
                _记(名, 节点)
        # `addCleanup(lambda: __import__("shutil").rmtree(根, ignore_errors=True))` 形态：
        # lambda 体内**清理调用的实参**才算（把 lambda 里所有名字都收会把「只读别的根」
        # 误判成本根被清 ⇒ 假绿）。
        for 首参 in list(节点.args[:1]):
            if isinstance(首参, ast.Lambda):
                for 内 in ast.walk(首参):
                    if isinstance(内, ast.Call) and _函数名(内.func) in 清理调用名:
                        for 参 in 内.args:
                            for 名 in _名字引用(参):
                                _记(名, 节点)
                        if isinstance(内.func, ast.Attribute) \
                                and _函数名(内.func) in 销毁式接收者名:
                            for 名 in _名字引用(内.func.value):
                                _记(名, 节点)
    # ④ 登记表 append（`表.append(根)`）
    # ★ 表名必须**真的在 tearDownModule 里被清理循环消费**（见上面 `登记表` 的核法）：
    # 只按「名字里有『登记』」认会把**没被消费**的登记表算成已清 —— 反向验证拍5 实测过
    # 这一处 fail-open（`for 夹具 in 表: pass` 照样算清过）。
    for 节点 in ast.walk(树):
        if isinstance(节点, ast.Call) and _函数名(节点.func) == "append" and 节点.args \
                and isinstance(节点.func, ast.Attribute):
            接收 = _表达式文本(节点.func.value).split(".")[-1]
            if 接收 in 登记表:
                for 名 in _名字引用(节点.args[0]):
                    _记(名, 节点)

    def _收体(语句表: list[ast.stmt]) -> None:
        """收一段语句体（收尾钩子 / try 的 finally / except）里全部清理调用的目标名。"""
        for 语句 in 语句表:
            for 子 in ast.walk(语句):
                if not (isinstance(子, ast.Call) and _函数名(子.func) in 清理调用名):
                    continue
                for 参 in 子.args:
                    for 名 in _名字引用(参):
                        _记(名, 子)
                if isinstance(子.func, ast.Attribute) and _函数名(子.func) in 销毁式接收者名:
                    for 名 in _名字引用(子.func.value):
                        _记(名, 子)

    def _走(节点: ast.AST) -> None:
        for 子 in ast.iter_child_nodes(节点):
            if isinstance(子, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if 子.name in 收尾钩子名:  # ② 收尾钩子
                    _收体(子.body)
                _走(子)
                continue
            if isinstance(子, ast.Try):  # ③ try 的 finally / except
                _收体(子.finalbody)
                for 处理器 in 子.handlers:
                    _收体(处理器.body)
                _走(子)
                continue
            _走(子)

    _走(树)
    return 证据, 证据类


def _返回根的局部名(函数: ast.AST) -> set[str]:
    """该函数里「造出来又 `return` 出去」的临时根**局部名**（没有则是空集）。"""
    局部: set[str] = set()
    for 子 in ast.walk(函数):
        if isinstance(子, ast.Assign) and len(子.targets) == 1 \
                and isinstance(子.targets[0], ast.Name):
            if any(_是临时根调用(c) for c in ast.walk(子.value)):
                局部.add(子.targets[0].id)
    if not 局部:
        return set()
    出: set[str] = set()
    for 子 in ast.walk(函数):
        if isinstance(子, ast.Return) and 子.value is not None:
            for 孙 in ast.walk(子.value):
                if isinstance(孙, ast.Name) and 孙.id in 局部:
                    出.add(孙.id)
    return 出


def _helper调用点绑定名(树: ast.AST, 父: dict[int, ast.AST], 函数名: str,
                全部类: list[ast.ClassDef]) -> dict[str, set[str]]:
    """该 helper 的全部调用点**绑定到的名字** → 该绑定**所在类**集（含元组解包）。

    ★ 为什么要带上「所在类」：helper 返回根的清理登记在**调用点**（`self.addCleanup(…,
    组件目录)`），而 `self.X` 证据是按类核的 —— 拿 mkdtemp **节点所在的类**（helper 体内，
    模块级 = 空串）去比会把「用例类里的清理登记」判成不匹配 ⇒ 假红（反向验证实测过）。
    """
    出: dict[str, set[str]] = {}

    def _记(名: str, 位置节点: ast.AST) -> None:
        出.setdefault(名, set()).add(_所属类(全部类, 位置节点))

    for 节点 in ast.walk(树):
        if not (isinstance(节点, ast.Call) and _函数名(节点.func) == 函数名):
            continue
        当前 = 节点
        while id(当前) in 父:
            上 = 父[id(当前)]
            if isinstance(上, ast.BinOp) and isinstance(上.op, ast.Div):
                当前 = 上
                continue
            if isinstance(上, ast.Call) and _函数名(上.func) in ("Path", "str") and 上.args \
                    and 上.args[0] is 当前:
                当前 = 上
                continue
            break
        p = 父.get(id(当前))
        目标们: list[ast.AST] = []
        if isinstance(p, ast.Assign):
            目标们 = list(p.targets)
        elif isinstance(p, ast.AnnAssign):
            目标们 = [p.target]
        for 目标 in 目标们:
            if isinstance(目标, (ast.Name, ast.Attribute)):
                _记(_表达式文本(目标), 目标)
            for 孙 in ast.walk(目标):
                if isinstance(孙, (ast.Name, ast.Attribute)):
                    # 裸 `self` / `cls` 不是**根的名字**（它只是接收者）—— 把它收进「调用点
                    # 绑定名」会让「已清」永远不成立（`self` 永不出现在清理面 ⇒ 恒判红）。
                    if isinstance(孙, ast.Name) and 孙.id in ("self", "cls"):
                        continue
                    _记(_表达式文本(孙), 孙)
    return 出


def 扫描临时根未清(根: Path) -> tuple[list[dict], dict]:
    """判据四：``(违规, 统计)`` —— 每条临时根造出来之后**有没有人清**。

    统计把「判过了多少」拆开：`临时根数` = `已清` + `未清` + `根不可达` + `不可解析` 之和
    —— 只报「违规 0 条」的判据无法自证它看过任何东西（同判据一的理由）。
    """
    根 = Path(根)
    违规: list[dict] = []
    统计 = {"文件数": 0, "临时根数": 0, "已清": 0, "未清": 0, "根不可达": 0, "不可解析": 0,
           "helper返回根": 0}
    文件表 = _测试文件表(根)
    for 文件 in 文件表:
        统计["文件数"] += 1
        相对 = 文件.relative_to(根).as_posix()
        树, 错误 = _读并解析(文件)
        if 树 is None:
            统计["不可解析"] += 1
            违规.append({"文件": 相对, "行": 0, "动作": "-", "目标": "-",
                         "缺口类型": 缺源码不可解析, "桶键": f"{相对}::-::-",
                         "详情": f"{错误} ⇒ 这份测试造了什么临时根未知，不静默跳过"})
            continue
        临时根们 = [节点 for 节点 in ast.walk(树) if _是临时根调用(节点)]
        if not 临时根们:
            continue
        父 = _父节点表(树)
        清理面, 清理面类 = _清理面名字(树)
        基类表, 全部类 = _类结构表(树)

        def _本处算清(名们: list[str], 调用节点: ast.AST, 所在类: str | None = None) -> bool:
            """这些名字里**至少一个**在本处被清（`self.X` / `cls.X` 还要核类归属）。

            `self.X` 必须按类核：同文件两个类各有同名 `self.工作` 时，A 类的登记
            不能替 B 类顶包（反向验证实测过：不核类则删掉 A 的 addCleanup 也不红）。
            核类时带**基类链**（`祖先链`）：根在子类、清理写在基类 `tearDown` 里是仓内
            常见形态，不认基类会假红。

            `所在类` 显式给出时以它为准（helper 形态：根造在模块级 helper 里，
            但清理登记在**调用点所在的用例类**，按 mkdtemp 节点所在的类（空串）核必然错）。
            """
            本处类 = 所在类 if 所在类 is not None else _所属类(全部类, 调用节点)
            for 名 in 名们:
                if 名 not in 清理面:
                    continue
                if not 名.startswith(("self.", "cls.")):
                    return True
                提供类 = 清理面类.get(名, set())
                if _祖先链(基类表, 本处类) & 提供类:
                    return True
            return False

        helper根: dict[str, set[str]] = {}
        for 节点 in ast.walk(树):
            if isinstance(节点, (ast.FunctionDef, ast.AsyncFunctionDef)):
                局部名 = _返回根的局部名(节点)
                if 局部名:
                    helper根[节点.name] = 局部名
        helper可清: dict[str, dict[str, set[str]]] = {
            名: _helper调用点绑定名(树, 父, 名, 全部类) for 名 in helper根}
        for 调用 in 临时根们:
            统计["临时根数"] += 1
            根表达式, 子路径 = _根表达式(调用, 父)
            绑定们 = _根绑定名(根表达式, 父)
            绑定 = 绑定们[0] if 绑定们 else None
            所在 = _所在函数(调用, 父)
            返回本根 = (isinstance(所在, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and 所在.name in helper根
                    and bool(绑定们) and all(名 in helper根[所在.name] for 名 in 绑定们))
            if 返回本根:
                统计["helper返回根"] += 1
            if 子路径:
                # 根**没有名字**（派生出来的文件路径才有名字）⇒ 判不出根被清。
                # fail-closed：与判据一同口径，解析不出**不是**放行的理由。
                统计["根不可达"] += 1
                违规.append({
                    "文件": 相对, "行": 调用.lineno, "动作": _函数名(调用.func),
                    "目标": _表达式文本(根表达式),
                    "缺口类型": 临时根未清,
                    "桶键": f"{相对}::{_函数名(调用.func)}::根不可达::{_表达式文本(根表达式)}",
                    "详情": (f"`{_表达式文本(根表达式)}` 的**临时根没有绑定给任何名字**"
                             "（只把派生出来的子路径绑了名）⇒ 静态判不出根被清，"
                             f"fail-closed 计入违规。修法：把根绑成名字并 "
                             f"`addCleanup(清只读后删除树, 根, 忽略失败=真)` 或登记进"
                             "模块级登记表（由 tearDownModule 消费）"),
                })
                continue
            if not 绑定们:
                统计["根不可达"] += 1
                违规.append({
                    "文件": 相对, "行": 调用.lineno, "动作": _函数名(调用.func),
                    "目标": _表达式文本(根表达式),
                    "缺口类型": 临时根未清,
                    "桶键": f"{相对}::{_函数名(调用.func)}::根未绑定::{_表达式文本(根表达式)}",
                    "详情": (f"`{_表达式文本(根表达式)}` 造出的临时根**没有绑定给名字**"
                             "⇒ 判不出它被清（fail-closed）。修法：绑成名字再登记清理"),
                })
                continue
            if _本处算清(绑定们, 调用):
                统计["已清"] += 1
                continue
            if 返回本根:
                # helper 返回根 ⇒ 根在各调用点叫**别的名字**，「本地名 vs 调用点名」对不上。
                # 两条等效的清理腿，**任一成立即算已清**：
                #   A) helper 自己登记了清理（本地根名出现在清理面 —— 上面 `_本处算清` 已判）；
                #   B) 每个调用点各自清（该 helper 的**全部**调用点绑定名在**各自所在类**里
                #      都出现在清理面上）。
                # ★ 只认「部分调用点清了」会漏判成绿 ⇒ 必须**全量包含**。
                调用点名 = helper可清.get(所在.name, {})
                调用点漏 = sorted(
                    名 for 名, 类集 in 调用点名.items()
                    if not any(_本处算清([名], 调用, 所在类=类) for 类 in 类集))
                if 调用点名 and not 调用点漏:
                    统计["已清"] += 1
                    continue
                统计["未清"] += 1
                违规.append({
                    "文件": 相对, "行": 调用.lineno, "动作": _函数名(调用.func),
                    "目标": _表达式文本(根表达式),
                    "缺口类型": 临时根未清,
                    "桶键": f"{相对}::{_函数名(调用.func)}::helper根未清::{所在.name}",
                    "详情": (f"helper `{所在.name}` 造出临时根并返回，但**根没人清**："
                             f"本地名 `{绑定}` 不在清理面、且调用点绑定名 "
                             f"{sorted(调用点名) or '<无>'} 未全部出现在清理面 "
                             f"（缺 {调用点漏}）。修法二选一："
                             "helper 内登记模块级登记表（tearDownModule 消费，一处覆盖全调用点）"
                             "，或每个调用点 addCleanup/try-finally 清根"),
                })
                continue
            统计["未清"] += 1
            违规.append({
                "文件": 相对, "行": 调用.lineno, "动作": _函数名(调用.func),
                "目标": _表达式文本(根表达式),
                "缺口类型": 临时根未清,
                "桶键": f"{相对}::{_函数名(调用.func)}::{绑定}",
                "详情": (f"临时根 `{绑定}`（`{_表达式文本(根表达式)}`）**建了没清**："
                         "清理面上找不到它（addCleanup 实参 / tearDown / try-finally / "
                         "except / 模块级登记表四条腿都没点它）⇒ 每跑一次测试泄漏一个临时目录。"
                         "修法：`self.addCleanup(清只读后删除树, "
                         f"{绑定}, 忽略失败=真)`，或登记进模块级登记表由 tearDownModule 消费"),
            })
    if not 文件表:
        违规.append({"文件": 扫描根名, "行": 0, "动作": "-", "目标": "-",
                     "缺口类型": 缺扫描面, "桶键": f"{扫描根名}::-::-",
                     "详情": f"{根 / 扫描根名} 下未发现任何 .py ⇒ 扫描面为空，"
                             "空集不是通过（fail-closed）"})
    return 违规, 统计


def 扫描只断言成功(根: Path) -> tuple[list[dict], dict]:
    """判据二：``(待核清单, 统计)``。"""
    根 = Path(根)
    待核: list[dict] = []
    统计 = {"文件数": 0, "用例数": 0, "有断言用例": 0, "只成功断言用例": 0, "不可解析": 0}
    文件表 = _测试文件表(根)
    for 文件 in 文件表:
        统计["文件数"] += 1
        相对 = 文件.relative_to(根).as_posix()
        树, 错误 = _读并解析(文件)
        if 树 is None:
            统计["不可解析"] += 1
            待核.append({"文件": 相对, "行": 0, "用例": "-", "缺口类型": 缺源码不可解析,
                         "桶键": f"{相对}::<不可解析>",
                         "详情": f"{错误} ⇒ 这份测试断言了什么未知，不静默跳过"})
            continue
        for 用例节点, 限定名 in _收集用例(树):
            统计["用例数"] += 1
            断言们 = [子 for 子 in ast.walk(用例节点)
                   if isinstance(子, ast.Call) and _是断言调用(子)]
            辅助 = [子 for 子 in ast.walk(用例节点)
                  if isinstance(子, ast.Call) and _是辅助断言(子)]
            if not 断言们 and not 辅助:
                continue
            统计["有断言用例"] += 1
            if 辅助:
                continue
            if not all(只看成功字段(_断言判定表达式(子)) for 子 in 断言们):
                continue
            统计["只成功断言用例"] += 1
            待核.append({
                "文件": 相对, "行": 用例节点.lineno, "用例": 限定名,
                "缺口类型": 只断言成功, "桶键": f"{相对}::{限定名}",
                "详情": (f"用例 {限定名} 的断言**全部**只看 `成功` 字段 ⇒ "
                         "流程没抛异常就等于通过（未装配空转也是 `成功=True`）；"
                         "必须补一条业务字段断言（产出物计数 / 错误码 / 内容字段），"
                         "否则这条用例证明不了它测到了东西"),
            })
    if not 文件表:
        待核.append({"文件": 扫描根名, "行": 0, "用例": "-", "缺口类型": 缺扫描面,
                     "桶键": f"{扫描根名}::<扫描面为空>",
                     "详情": f"{根 / 扫描根名} 下未发现任何 .py ⇒ 扫描面为空，"
                             "空集不是通过（fail-closed）"})
    return 待核, 统计


def 扫描mock空转(根: Path) -> tuple[list[dict], dict]:
    """判据三：``(空转清单, 统计)``。

    反查面 = `公共契约.正式根.遍历源码` 的 `.py` + `.json`，**排除 `测试中心/`**；
    零命中时再看该键在测试中心里有没有「其他出现」（测试自造的假件消费者）。
    """
    根 = Path(根)
    空转: list[dict] = []
    统计 = {"文件数": 0, "mock键数": 0, "实现面文件数": 0, "有读点": 0,
           "测试内自洽": 0, "空转": 0, "不可解析": 0}
    文件表 = _测试文件表(根)
    if not 文件表:
        空转.append({"文件": 扫描根名, "行": 0, "键": "-", "缺口类型": 缺扫描面,
                     "桶键": f"{扫描根名}::<扫描面为空>",
                     "详情": f"{根 / 扫描根名} 下未发现任何 .py ⇒ 扫描面为空，"
                             "空集不是通过（fail-closed）"})
        return 空转, 统计
    键表: dict[str, dict] = {}
    for 文件 in 文件表:
        统计["文件数"] += 1
        相对 = 文件.relative_to(根).as_posix()
        树, 错误 = _读并解析(文件)
        if 树 is None:
            统计["不可解析"] += 1
            空转.append({"文件": 相对, "行": 0, "键": "-", "缺口类型": 缺源码不可解析,
                         "桶键": f"{相对}::<不可解析>",
                         "详情": f"{错误} ⇒ 这份测试 mock 了什么未知，不静默跳过"})
            continue
        键们, 键节点 = _mock字典键(树)
        if not 键们:
            continue
        # 「其他出现」= 该键在**本份测试里、mock 字典之外**还出现过（**子串**口径）：
        # 测试自造的假件常常把键写在**一整块多行字符串**里（`测试_LibreOffice双腿行为差异.py`
        # 往临时目录写一个假 `soffice` 脚本，脚本正文里 `os.environ.get("FAKE_LO_COUNTER")`），
        # 那种形态下键不是独立的字符串常量、而是大字符串的一部分 ⇒ 按「常量相等」数会
        # 全数漏掉，把 6 个有真实消费者的键全报成空转（2026-09-22 实测过这一版假红）。
        其他出现 = [子.value for 子 in ast.walk(树)
                if isinstance(子, ast.Constant) and isinstance(子.value, str)
                and id(子) not in 键节点]
        for 键值, 行 in 键们:
            条目 = 键表.setdefault(键值, {"文件": 相对, "行": 行, "其他出现": 0})
            if any(键值 in 文本 for 文本 in 其他出现):
                条目["其他出现"] += 1
    # 实现面反查：文本包含即可（键是环境变量名，出现即说明有读取/声明点）。
    # **排除本件自身**：判据件的正文里会举例提到这些键（本模块 docstring 就写了
    # `语义索引_禁用库` 与 `FAKE_LO_COUNTER`）—— 判据件不是实现，把自己算进反查面
    # 会让「被写进文档的键」自动获得一个假读点（2026-09-22 实测：`FAKE_LO_COUNTER`
    # 只因被本件 docstring 提到就漏判成「有读点」）。这是判据污染自己的反查面。
    本件 = Path(__file__).resolve()
    实现面: list[tuple[Path, str]] = []
    for 路径 in 遍历源码(根, 后缀=(".py", ".json")):
        if 扫描根名 in 路径.relative_to(根).parts:
            continue
        try:
            if 路径.resolve() == 本件:
                continue
            实现面.append((路径, 路径.read_text(encoding="utf-8", errors="ignore")))
        except OSError:
            continue
    统计["实现面文件数"] = len(实现面)
    for 键值, 条目 in sorted(键表.items()):
        统计["mock键数"] += 1
        读点 = [路径 for 路径, 文本 in 实现面 if 键值 in 文本]
        if 读点:
            统计["有读点"] += 1
            continue
        if 条目["其他出现"]:
            统计["测试内自洽"] += 1
            continue
        统计["空转"] += 1
        空转.append({
            "文件": 条目["文件"], "行": 条目["行"], "键": 键值,
            "缺口类型": mock空转, "桶键": f"{条目['文件']}::{键值}",
            "详情": (f"mock 的环境变量键 `{键值}` 在**实现面零读取点**、"
                     f"且在本仓其他位置也零出现 ⇒ mock 空转（开关没人读，"
                     "断言必然与「没 mock」同结果）；实现里真有这个开关，"
                     "或删掉这条 mock"),
        })
    return 空转, 统计


# ---------------------------------------------------------------------------
# 存量基线
# ---------------------------------------------------------------------------

def 读存量基线(路径: Path | None = None) -> tuple[dict[str, dict[str, int]], list[str]]:
    """``(基线, 问题)``；问题非空 ⇒ fail-closed（调用方判红）。

    桶值两种等价写法（都归一成 ``{桶键: 允许处数}``）：
    **字符串数组**（简写 = 每键允许 1 处）与 **「桶键 → 允许处数」对象**。
    后者是「未解析」档必须的形态：同一 `文件::动作::表达式` 现场出现多处是常态
    （实测 847 键 / 1133 处，其中 151 键各出现 2 处以上）—— 数组形态会把这些
    并成一条，处数就冻结不住（与 `第三方导入分布基线门禁` 同口径：处数也是被冻结的量）。
    """
    路径 = Path(路径 or 存量基线路径)
    空: dict[str, dict[str, int]] = {名: {} for 名 in 存量桶名}
    if not 路径.is_file():
        return 空, [f"存量基线不存在：{路径}（「存量已登记」的唯一凭据没了，"
                    "不许静默按空基线判绿）"]
    try:
        数据 = json.loads(路径.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as 错误:
        return 空, [f"存量基线读不成（{type(错误).__name__}）：{路径}"]
    if not isinstance(数据, dict):
        return 空, [f"存量基线形状非法（顶层不是对象）：{路径}"]
    基线: dict[str, dict[str, int]] = {}
    问题: list[str] = []
    for 名 in 存量桶名:
        值 = 数据.get(名)
        if 值 is None:
            问题.append(f"存量基线缺桶 `{名}`：{路径}")
            基线[名] = {}
        elif isinstance(值, list) and all(isinstance(项, str) for 项 in 值):
            基线[名] = {项: 1 for 项 in 值}
        elif isinstance(值, dict) and all(
                isinstance(键, str) and isinstance(处, int) and not isinstance(处, bool)
                and 处 >= 1 for 键, 处 in 值.items()):
            基线[名] = dict(值)
        else:
            问题.append(f"存量基线桶 `{名}` 形状非法"
                        "（须是字符串数组，或「桶键 → 允许处数（正整数）」对象）："
                        f"{路径}")
            基线[名] = {}
    return 基线, 问题


def 应用存量基线(当前: dict[str, int], 基线: dict[str, int]
            ) -> tuple[list[str], list[str], list[str]]:
    """``(基线外新增/超量, 基线内存量, 收敛项)`` —— 只减不增：新增判红、收敛只留痕。

    按**处数**比对（不是集合比对）：桶键在基线里登记 `n` 处、现场出现 `n+1` 处
    同样进「新增」⇒ 判红 —— 这正是 `第三方导入分布基线门禁` 的口径
    「处数也是被冻结的量」。少了则进「收敛」，只留痕。
    """
    新增 = sorted(键 for 键, 处 in 当前.items() if 处 > 基线.get(键, 0))
    存量 = sorted(键 for 键, 处 in 当前.items() if 处 <= 基线.get(键, 0))
    收敛 = sorted(键 for 键, 处 in 基线.items() if 当前.get(键, 0) < 处)
    return 新增, 存量, 收敛


# ---------------------------------------------------------------------------
# 门禁入口
# ---------------------------------------------------------------------------

def _分桶(清单: list[dict], 桶清单: dict[str, list[dict]]) -> list[dict]:
    """把某判据的清单按**缺口类型**分进各存量桶；不属于任何桶的条目原样返回。

    判据一现在有**两档**（`写仓库内相对路径` / `写动作未解析`），共用 `扫描写入` 的同一份
    清单 —— 不按缺口类型分桶就会拿未解析的键去比对「写仓库内相对路径」桶的基线，
    853 个键当场全成「新增」（2026-09-23 实测过一次这个假红）。
    判据**自身缺口**（`扫描面为空` / `源码不可解析`）不属于任何存量桶 ⇒ 直接判红，
    绝不因为「桶里没有它」而被静默丢掉（fail-closed）。
    """
    其余: list[dict] = []
    for 条 in 清单:
        桶名 = 条["缺口类型"]
        if 桶名 in 桶清单:
            桶清单[桶名].append(条)
        else:
            其余.append(条)
    return 其余


def 运行门禁(根: Path | None = None, *, 基线路径: Path | None = None
          ) -> tuple[list[dict], dict[str, list[dict]], dict]:
    """``(违规, 存量报告, 统计)`` —— 发布门禁与编译口消费的入口。

    - `违规` = 全部**判红**项：基线外新增（含同桶键处数超出基线）+ 判据自身缺口
      （扫描面空 / 源码不可解析 / 存量基线不可用）；
    - `存量报告` = 各桶「基线内、只报不拦」的条目（收敛留痕在 `统计` 里）；
    - `统计` = 逐判据统计 + 每桶的 `存量基线` 五态计数（`当前` / `当前处数` /
      `存量` / `存量处数` / `新增` / `收敛`）。
    """
    根 = Path(根 or 仓库根).resolve()
    违规: list[dict] = []
    存量报告: dict[str, list[dict]] = {名: [] for 名 in 存量桶名}
    基线, 基线问题 = 读存量基线(基线路径)
    for 说明 in 基线问题:
        违规.append({"文件": 存量基线路径.name, "行": 0, "动作": "-", "目标": "-",
                     "缺口类型": 缺存量基线, "桶键": "存量基线::<不可用>", "详情": 说明})

    判据一, 统计一 = 扫描写入(根)
    判据二, 统计二 = 扫描只断言成功(根)
    判据三, 统计三 = 扫描mock空转(根)
    判据四, 统计四 = 扫描临时根未清(根)

    统计: dict[str, Any] = {"判据一": 统计一, "判据二": 统计二, "判据三": 统计三,
                        "判据四": 统计四, "判据一·未解析": {}}

    桶清单: dict[str, list[dict]] = {名: [] for 名 in 存量桶名}
    for 判据清单 in (判据一, 判据二, 判据三, 判据四):
        违规.extend(_分桶(判据清单, 桶清单))

    for 桶名 in 存量桶名:
        # 按**处数**比对：同一桶键在清单里出现多次就是多处（未解析档的常态）。
        当前 = Counter(条["桶键"] for 条 in 桶清单[桶名])
        新增, 存量, 收敛 = 应用存量基线(当前, 基线[桶名])
        清单表 = {条["桶键"]: 条 for 条 in 桶清单[桶名]}
        for 键 in 存量:
            存量报告[桶名].append(清单表[键])
        for 键 in 新增:
            条 = dict(清单表[键])
            旧 = 基线[桶名].get(键)
            if 旧 is not None:
                # 桶键已在基线里、只是现场处数更多 ⇒ 说清是「超量」不是「新增键」。
                条["详情"] = (f"{条['详情']}；处数 {旧} → {当前[键]}"
                              f"（超出基线 {当前[键] - 旧} 处）")
            违规.append(条)
        统计桶 = {"当前": len(当前), "当前处数": sum(当前.values()),
                 "存量": len(存量), "存量处数": sum(当前[键] for 键 in 存量),
                 "新增": len(新增), "收敛": 收敛}
        统计[判据键[桶名]]["存量基线"] = 统计桶

    # `存量总数` = 存量**键**数（逐条具名登记的条目数）；`存量总处数` = 各处数之和。
    # 两者必须分开报：未解析档 854 键 / 1151 处，只报一个数就会被读成另一个。
    统计["存量总数"] = sum(len(项) for 项 in 存量报告.values())
    统计["存量总处数"] = sum(统计[判据键[名]]["存量基线"]["存量处数"] for 名 in 存量桶名)
    return 违规, 存量报告, 统计


def _打印判据(标号: str, 统计: dict) -> None:
    if 标号 == "判据一":
        print(f"  [{标号} 写仓库内相对路径] 扫描 {统计['文件数']} 个 .py；"
              f"写动作 {统计['写动作数']} 处（仓库内写 {统计['仓库内写']}／"
              f"受管目录内 {统计['受管写']}／解析得出但不涉仓库 {统计['放行写']}／"
              f"未解析（计入违规，fail-closed）{统计['未解析']}）")
        # 如实报出本档判「无 dir= 的临时落点」时依据的是**哪一个**临时根 ——
        # 门禁侧只能观测到自己那一份，测试进程的读不到（见 `_运行时临时根安全`）。
        print(f"    [运行时临时根] {运行时临时根说明()}")
    elif 标号 == "判据四":
        print(f"  [{标号} 临时根未清] 扫描 {统计['文件数']} 个 .py；"
              f"临时根 {统计['临时根数']} 处（已清 {统计['已清']}／"
              f"未清 {统计['未清']}（计入违规，fail-closed）／"
              f"根不可达（未绑定给名字，计入违规）{统计['根不可达']}）；"
              f"其中 helper 返回根 {统计['helper返回根']} 处")
    elif 标号 == "判据二":
        print(f"  [{标号} 只断言成功] 扫描 {统计['文件数']} 个 .py；"
              f"用例 {统计['用例数']} 个（有断言 {统计['有断言用例']}）⇒ "
              f"只成功断言 {统计['只成功断言用例']} 条")
    else:
        print(f"  [{标号} mock空转] 扫描 {统计['文件数']} 个 .py；"
              f"mock 环境变量键 {统计['mock键数']} 个；"
              f"实现面 {统计['实现面文件数']} 文件 ⇒ 有读点 {统计['有读点']}／"
              f"测试内自洽 {统计['测试内自洽']}／空转 {统计['空转']}")


def 主程序(argv: list[str] | None = None) -> int:
    解析 = argparse.ArgumentParser(description="测试写入边界门禁（债务 #106，四条判据）")
    解析.add_argument("--根", default=None, help="覆盖扫描根（反向验证用）")
    解析.add_argument("--只报", action="store_true", help="只打印不判红（排查用）")
    解析.add_argument("--存量明细", action="store_true",
                    help="逐条打印存量桶键（默认只报处数与样例；重建基线用）")
    参数 = 解析.parse_args(argv)
    根 = Path(参数.根).expanduser() if 参数.根 else 仓库根
    违规, 存量报告, 统计 = 运行门禁(根)
    print(f"测试写入边界门禁：根={根}／扫描面={扫描根名}/")
    for 标号 in ("判据一", "判据四", "判据二", "判据三"):
        _打印判据(标号, 统计[标号])
    样例 = 统计["判据一"]["未解析样例"]
    if 样例:
        print(f"  [判据一 未解析样例] 共 {统计['判据一']['未解析']} 处，"
              f"前 {len(样例)} 处（文件:行）：{'、'.join(样例)}")
    for 桶名 in 存量桶名:
        统计桶 = 统计[判据键[桶名]]["存量基线"]
        if 统计桶["收敛"]:
            print(f"  [{桶名}] 基线比现场少 {len(统计桶['收敛'])} 键（处数下降）⇒ 已收敛，"
                  f"请下调 `{存量基线路径.name}` 该桶：{统计桶['收敛'][:3]}")
    for 桶名, 条目们 in 存量报告.items():
        统计桶 = 统计[判据键[桶名]]["存量基线"]
        if 桶名 == 未解析写动作 and not 参数.存量明细:
            # 未解析存量上千处：逐条打印会把判据行淹掉，默认只报**处数 + 样例**；
            # `--存量明细` 才逐条透出（重建基线的唯一入口，见模块 docstring「用法」）。
            样例行 = "、".join(f"{条['文件']}:{条['行']}" for 条 in 条目们[:存量明细上限])
            print(f"  [存量·只报不拦·{桶名}] {统计桶['存量']} 键 / "
                  f"{统计桶['存量处数']} 处（fail-closed 冻结：新增或处数超出即判红）；"
                  f"样例：{样例行}")
            continue
        for 条 in 条目们:
            print(f"  [存量·只报不拦·{桶名}] {条['文件']}:{条['行']} "
                  f"{条.get('用例', 条.get('目标', 条.get('键', '')))}")
    if not 违规:
        if 统计["存量总数"]:
            print(f"测试写入边界门禁结论：绿 —— 基线内 {统计['存量总数']} 键 / "
                  f"{统计['存量总处数']} 处存量（只报不拦，只减不增）")
        else:
            print("测试写入边界门禁通过：四条判据零违规、零存量"
                  "（受管落点 = tempfile / 工程缓存）")
        return 0
    头 = "测试写入边界门禁失败（只报态，不判红）" if 参数.只报 else "测试写入边界门禁失败"
    print(f"{头}：共 {len(违规)} 项违规")
    for 条 in 违规:
        print(f"[{条['缺口类型']}] {条['文件']}:{条['行']} "
              f"动作={条.get('动作', '-')} 目标={条.get('目标', 条.get('用例', 条.get('键', '-')))} "
              f"详情={条['详情']}")
    return 0 if 参数.只报 else 1


if __name__ == "__main__":
    sys.exit(主程序())
