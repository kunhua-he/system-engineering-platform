"""硬件画像 → 离散档位 → 默认参数（§11 零配置自适应）契约与反向测试。

本文件守护四件事，**每一条都配了反向验证**（故意弄坏 → 确认真变红 → 还原恢复绿）：

1. **D1 画像探针真能采到事实**（不是读注释）：真跑一次 `读取硬件画像()`，
   断言物理内存/核数/磁盘可用都是正数、`未知项` 为空；再断言**缓存真的生效**
   （第二次调用返回同一对象），以及 `system_profiler` **全程只调一次**
   （用真计数器统计收口层被调用次数，不 patch 被测对象）。
2. **D2 档位是纯函数且输出确定**：喂四张**假画像**（16GB 无 GPU / 32GB /
   128GB 有 Metal / Linux 类服务器），断言档位键与容量阈值**确定**、
   同一画像两次输出**逐字段相同**、`0 未知` 走**最小档**保守降级。
3. **★首版零行为变化**：`标定参数集` 的每一个性能参数**逐字段对账现值**
   —— 现值从**真实源码 AST 读常量/默认参数**（不手抄），
   这样「档位表偷偷改了现值」会立刻变红。
4. **★安全红线（本批最重要的一条）**：喂「类服务器画像」（64 核/512GB/有 Metal），
   断言：
   - 参数集**不含**任何安全边界字段（`校验不含安全边界`）；
   - 用户覆盖里塞 `监听地址=0.0.0.0` / `要求凭证=False` / `允许路径表` **被整键拒收**；
   - 拒收后**拿真实网关安全边界**（`运行核心/统一网关/安全边界.py` 的 `请求限制器`）
     验证：`0.0.0.0` 仍然被拒、仍只允许回环 —— 即「画像再大也放不开监听地址」。

**反证方式（本文件的核心手法，非 mock）**：不 patch 被测对象、不伪造副作用；
用真画像、真缓存计数、真 AST 读源码常量、真网关安全边界判定。
唯一「造」出来的是**假画像数据** —— 那正是 D7 要求的口径：模拟的是**输入数据**，
不是真实环境动作（`0045` 第 2 条），**绝不触达真实装配/写删路径**。

全程不用 `unittest.mock`（与 `测试_超时执行线程准入.py` 同一纪律）。
"""

from __future__ import annotations

import ast
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 公共契约.基础类型.逻辑类型 import 真, 假
from 公共契约.运行时 import 平台适配
from 运行核心.自适应选型 import (
    三层合并,
    按画像定档位,
    标定参数集,
    校验不含安全边界,
    校验覆盖键安全,
    展示三层结果,
    档位表,
    内存档位表,
    部署形态域,
    安全边界字段名,
    容量基线字段表,
)
from 运行核心.自适应选型.档位表 import 内存水位硬上限比例
from 支持库.适配层.硬件画像探针 import (
    读取硬件画像,
    读取图形加速事实,
    清空画像缓存,
)

系统根 = Path(__file__).resolve().parents[2]
每GB = 1024 ** 3


@dataclass(frozen=True)
class 假画像:
    """测试用假画像（**只造输入数据**；字段与真实画像同名同类型）。"""

    逻辑核数: int = 8
    物理核数: int = 8
    物理内存字节: int = 16 * 每GB
    可用内存字节: int = 8 * 每GB
    有Metal: bool = 假
    磁盘可用字节: int = 500 * 每GB


#: 四张规定画像（D7 要求：16GB 无 GPU / 32GB / 128GB / Linux 服务器）
规定画像表 = {
    "16GB无GPU": 假画像(逻辑核数=8, 物理核数=8, 物理内存字节=16 * 每GB,
                    可用内存字节=8 * 每GB, 有Metal=假),
    "32GB有Metal": 假画像(逻辑核数=12, 物理核数=12, 物理内存字节=32 * 每GB,
                     可用内存字节=20 * 每GB, 有Metal=真),
    "128GB有Metal": 假画像(逻辑核数=24, 物理核数=24, 物理内存字节=128 * 每GB,
                      可用内存字节=64 * 每GB, 有Metal=真),
    "Linux类服务器": 假画像(逻辑核数=64, 物理核数=64, 物理内存字节=512 * 每GB,
                      可用内存字节=400 * 每GB, 有Metal=真,
                      磁盘可用字节=8000 * 每GB),
}


def _读源码常量(相对路径: str, 变量名: str):
    """从真实源码 AST 读模块级 `变量名 = 字面量`（现值对账的**唯一取数口径**）。

    不 import 被测模块、不手抄数字：手抄的现值会随源码变化而静默过期，
    那正是「档位表偷偷改了现值却没人发现」的成因。

    覆盖两种**真实存在的写法**（第一次跑测试时实测到的形状，不是猜的）：
    ① 单名赋值 `名 = 字面量`；
    ② 元组解包 `名甲, 名乙, … = 值甲, 值乙, …`（如 `响应表上限` 与
       `最大允许池大小` 同写一行）—— 只认 ① 会让「同写一行的常量」判不出，
       而那是**源码风格差异**，不该让现值对账失效。
    """
    树 = ast.parse((系统根 / 相对路径).read_text(encoding="utf-8"))
    for 节点 in 树.body:
        if not isinstance(节点, ast.Assign):
            continue
        目标 = 节点.targets[0]
        if isinstance(目标, ast.Name) and 目标.id == 变量名:
            return ast.literal_eval(节点.value)
        if isinstance(目标, ast.Tuple) and isinstance(节点.value, ast.Tuple):
            名表 = [元素.id for 元素 in 目标.elts if isinstance(元素, ast.Name)]
            if 变量名 in 名表 and len(名表) == len(节点.value.elts):
                return ast.literal_eval(节点.value.elts[名表.index(变量名)])
    raise AssertionError(f"{相对路径} 里找不到模块级常量 {变量名}")


def _读配置默认(相对路径: str, 配置键: str):
    """读源码里 `某字典.get("配置键", 默认值)` 的**字面量默认值**。

    为什么需要它：网关的工作线程/超时现值**不在构造签名里**，而是
    `self.配置.get("并发上限", 64)` 这种「配置缺省」。只读签名会判不出，
    而这两个值恰恰是「零行为变化」里最要紧的两个。
    """
    树 = ast.parse((系统根 / 相对路径).read_text(encoding="utf-8"))
    for 节点 in ast.walk(树):
        if not isinstance(节点, ast.Call):
            continue
        if not (isinstance(节点.func, ast.Attribute) and 节点.func.attr == "get"):
            continue
        if len(节点.args) < 2 or not isinstance(节点.args[0], ast.Constant):
            continue
        if 节点.args[0].value == 配置键:
            try:
                return ast.literal_eval(节点.args[1])
            except ValueError:
                continue
    raise AssertionError(f"{相对路径} 里找不到配置键 {配置键} 的字面量缺省值")


def _读调用字面量(相对路径: str, 函数名: str, 位置: int = 0):
    """读源码里 `函数名(字面量, …)` 第 `位置` 个实参（如 `min(128, …)` 的 128）。"""
    树 = ast.parse((系统根 / 相对路径).read_text(encoding="utf-8"))
    for 节点 in ast.walk(树):
        if isinstance(节点, ast.Call) and isinstance(节点.func, ast.Name) \
                and 节点.func.id == 函数名 and len(节点.args) > 位置:
            try:
                return ast.literal_eval(节点.args[位置])
            except ValueError:
                continue
    raise AssertionError(f"{相对路径} 里找不到 {函数名}(…) 的第 {位置} 个字面量实参")


def _读构造默认参数(相对路径: str, 类名: str, 参数名: str):
    """从真实源码 AST 读某类 `__init__` 的关键字默认值（现值对账用）。"""
    树 = ast.parse((系统根 / 相对路径).read_text(encoding="utf-8"))
    for 节点 in ast.walk(树):
        if isinstance(节点, ast.ClassDef) and 节点.name == 类名:
            for 子 in 节点.body:
                if isinstance(子, ast.FunctionDef) and 子.name == "__init__":
                    位置名表 = [a.arg for a in 子.args.args]
                    默认表 = list(子.args.defaults)
                    if 参数名 in 位置名表:
                        序号 = 位置名表.index(参数名) - (len(位置名表) - len(默认表))
                        if 序号 >= 0:
                            return ast.literal_eval(默认表[序号])
                    for 参数, 默认 in zip(子.args.kwonlyargs, 子.args.kw_defaults):
                        if 参数.arg == 参数名 and 默认 is not None:
                            return ast.literal_eval(默认)
    raise AssertionError(f"{相对路径} 的 {类名}.__init__ 里找不到默认参数 {参数名}")


class Test硬件画像探针真采到事实(unittest.TestCase):
    """D1：探针真跑、有界、缓存；`system_profiler` 全程只调一次。"""

    def setUp(self) -> None:
        清空画像缓存()

    def test_真画像全部字段取到事实(self) -> None:
        画像 = 读取硬件画像(含图形加速=True)
        self.assertTrue(画像.全部取到, f"画像存在未知项: {画像.未知项}")
        self.assertGreater(画像.物理内存字节, 0, "物理内存必须为正数")
        self.assertGreater(画像.可用内存字节, 0, "可用内存必须为正数")
        self.assertGreater(画像.逻辑核数, 0, "逻辑核数必须为正数")
        self.assertGreater(画像.磁盘可用字节, 0, "磁盘可用必须为正数")
        self.assertLessEqual(画像.可用内存字节, 画像.物理内存字节,
                             "可用内存不得大于物理内存")

    def test_画像缓存真的生效(self) -> None:
        """第二次调用返回**同一对象** —— 这是缓存生效的可观测形态。"""
        首次 = 读取硬件画像()
        再次 = 读取硬件画像()
        self.assertIs(首次, 再次, "缓存未生效：两次调用返回了不同对象")

    def test_含图形加速的请求不被默认画像缓存污染(self) -> None:
        """★缓存按「够用」判定（2026-09-18 验收修正后的守卫）。

        先按默认（不含图形加速）取一次画像，再请求含图形加速的画像：
        后者必须拿到**真采过图形**的那份，而不能被前者的 `有Metal=假` 顶掉。
        反证：把 `读取硬件画像` 的命中条件改回「只判 `已缓存 is not None`」→
        本用例的 `有Metal` 断言必然变红（本机实测有 Metal）。
        """
        清空画像缓存()
        默认画像 = 读取硬件画像()                      # 诊断路径先跑（不带图形加速）
        self.assertIs(默认画像.有Metal, 假, "默认画像按 fail-closed 应为无 Metal")
        含图形 = 读取硬件画像(含图形加速=True)          # 启动接线随后要真事实
        self.assertIsNot(含图形, 默认画像, "含图形加速的请求被不含的缓存顶掉了")
        本机应支持 = 平台适配.图形加速信息().get("Metal版本")
        if 本机应支持:
            self.assertIs(含图形.有Metal, 真,
                          f"本机 Metal 支持为 {本机应支持}，含图形加速的画像却判成无 Metal"
                          "（缓存被默认画像污染，档位随调用顺序漂移）")
        else:
            self.assertIs(含图形.有Metal, 假, "本机无 Metal 支持行，应保持 fail-closed 的假")

    def test_图形加速全程只调一次采样命令(self) -> None:
        """★「`system_profiler` 全程只调一次」的**真计数**验证（不 patch 被测对象）。

        手法：用真计数器包住收口层 `图形加速信息`（它是采样命令的唯一出口），
        连续调用 `读取图形加速事实()` 5 次，断言真实采样只发生 1 次。
        反证：把 `读取图形加速事实` 的缓存判断去掉 → 这里必然变成 5 次 → 变红。
        """
        调用次数 = {"次数": 0}
        原函数 = 平台适配.图形加速信息

        def 计数版():
            调用次数["次数"] += 1
            return 原函数()

        平台适配.图形加速信息 = 计数版
        try:
            for _ in range(5):
                读取图形加速事实()
        finally:
            平台适配.图形加速信息 = 原函数
        self.assertEqual(调用次数["次数"], 1,
                         f"图形加速采样被调了 {调用次数['次数']} 次，应为 1 次（全程只调一次）")

    def test_收口层字段齐全(self) -> None:
        """收口层四个取法都返回「支持/依据/原因」三件套（调用点不必猜平台）。"""
        for 取法 in (平台适配.内存容量信息, 平台适配.物理核数信息,
                    平台适配.处理器型号信息, 平台适配.图形加速信息):
            结果 = 取法()
            for 键 in ("支持", "依据", "原因"):
                self.assertIn(键, 结果, f"{取法.__name__} 缺字段 {键}")


class Test档位纯函数输出确定(unittest.TestCase):
    """D2：四张假画像 → 档位输出确定、可复现、未知走最小档。"""

    def test_四张规定画像输出确定(self) -> None:
        期望 = {
            "16GB无GPU": ("内存16GB", "小核", "无Metal"),
            "32GB有Metal": ("内存32GB", "中核", "有Metal"),
            "128GB有Metal": ("内存128GB", "大核", "有Metal"),
            "Linux类服务器": ("内存128GB", "大核", "有Metal"),
        }
        for 名称, 画像 in 规定画像表.items():
            参数集 = 按画像定档位(画像, "个人机")
            键 = 参数集.选自档位
            self.assertEqual(f"内存{键.内存档GB}GB", 期望[名称][0], f"{名称} 内存档不符")
            self.assertEqual(键.核数档, 期望[名称][1], f"{名称} 核数档不符")
            self.assertEqual(键.图形档, 期望[名称][2], f"{名称} 图形档不符")

    def test_同一画像两次输出逐字段相同(self) -> None:
        """可复现性（`0045` 第 1 条）：纯函数不许有隐性状态。"""
        for 名称, 画像 in 规定画像表.items():
            首次 = 按画像定档位(画像, "个人机").转字典()
            再次 = 按画像定档位(画像, "个人机").转字典()
            self.assertEqual(首次, 再次, f"{名称} 两次输出不同 —— 档位函数有隐性状态")

    def test_未知项走最小档保守降级(self) -> None:
        """画像关键项取不到（全 0）→ 最小内存档/小核档/无 Metal，且不抛异常。"""
        参数集 = 按画像定档位(假画像(逻辑核数=0, 物理核数=0, 物理内存字节=0,
                                 可用内存字节=0, 有Metal=假, 磁盘可用字节=0), "个人机")
        self.assertEqual(参数集.选自档位.内存档GB, 内存档位表[0])
        self.assertEqual(参数集.选自档位.核数档, "小核")
        self.assertEqual(参数集.选自档位.图形档, "无Metal")
        self.assertTrue(参数集.选自档位.未知项, "未知画像必须留下降级说明")
        self.assertEqual(参数集.容量基线["内存上限MB"], 1024, "双未知时水位应取兜底值")

    def test_无Metal不因探不到而被当成有(self) -> None:
        """fail-closed：`有Metal` 只在画像**明确为真**时才进「有Metal」档。

        画像契约是只读属性、`有Metal` 是逻辑型，故这里只喂两种**类型合法**的取值
        （`真`/`假`）—— 喂 `0`/`""`/`None` 测的是「类型漂移容错」，
        那属画像探针的职责，不在档位纯函数的判据面内。
        """
        self.assertEqual(按画像定档位(假画像(有Metal=假), "个人机").选自档位.图形档, "无Metal")
        self.assertEqual(按画像定档位(假画像(有Metal=真), "个人机").选自档位.图形档, "有Metal")

    def test_容量水位恒小于可用内存(self) -> None:
        """★保守不变量：任何画像下，内存高水位都不得 ≥ 可用内存（绝不榨干整机）。"""
        for 名称, 画像 in 规定画像表.items():
            参数集 = 按画像定档位(画像, "个人机")
            水位 = 参数集.容量基线["内存上限MB"]
            可用MB = 画像.可用内存字节 // (1024 ** 2)
            self.assertGreater(水位, 0, f"{名称} 水位必须为正数")
            self.assertLess(水位, 可用MB * 内存水位硬上限比例 + 1,
                            f"{名称} 水位 {水位}MB 超过了可用内存的硬上限比例")

    def test_容量基线字段与启动监督器必需字段同名(self) -> None:
        """两处字段名必须逐字对应（否则 `声明基线` 会报「基线缺少必需字段」）。"""
        参数集 = 按画像定档位(规定画像表["32GB有Metal"], "个人机")
        self.assertEqual(set(参数集.容量基线), set(容量基线字段表))
        for 值 in 参数集.容量基线.values():
            self.assertGreater(值, 0, "容量基线每项都必须为正数（0/负数会被声明基线拒收）")

    def test_模型实例数按可用内存推导(self) -> None:
        大 = 按画像定档位(规定画像表["128GB有Metal"], "个人机").模型
        小 = 按画像定档位(规定画像表["16GB无GPU"], "个人机").模型
        self.assertGreater(大["可开实例数"], 小["可开实例数"],
                           "大内存画像的可开模型实例数应严格多于小内存画像")
        self.assertGreater(大["内存预算MB"], 小["内存预算MB"])
        self.assertEqual(小["可开实例数"], 0, "16GB/可用8GB 应开不出 9.4GB 的单实例")

    def test_部署形态域全覆盖且不在域内走缺省(self) -> None:
        表 = 档位表()
        self.assertEqual(len(表), len(内存档位表) * 3 * 2 * len(部署形态域))
        for 键 in 表:
            self.assertIn(键.部署形态, 部署形态域)
        参数集 = 按画像定档位(规定画像表["16GB无GPU"], "银河系形态")
        self.assertEqual(参数集.选自档位.部署形态, "个人机")
        self.assertIn("部署形态", 参数集.选自档位.未知项)


class Test首版标定与现值一致(unittest.TestCase):
    """★首版零行为变化：逐字段对账**真实源码**里的现值（不手抄）。"""

    def test_网关与超时执行器现值对账(self) -> None:
        # 网关的工作线程/超时/队列现值是「配置缺省」（`self.配置.get("并发上限", 64)`），
        # 不在构造签名里 —— 故走 `_读配置默认`；队列上限是 `min(128, 最大工作线程)` 的字面量。
        self.assertEqual(标定参数集["网关工作线程"],
                         _读配置默认("运行核心/统一网关/本地网关.py", "并发上限"))
        self.assertEqual(标定参数集["网关请求队列上限"],
                         _读调用字面量("运行核心/统一网关/本地网关.py", "min", 0))
        self.assertEqual(标定参数集["调用超时秒"],
                         _读配置默认("运行核心/统一网关/本地网关.py", "请求超时秒"))
        self.assertEqual(标定参数集["流式并发通道"],
                         _读构造默认参数("运行核心/统一网关/流式HTTP.py",
                                      "流式HTTP服务器", "并发上限"))
        self.assertEqual(标定参数集["流式事件数上限"],
                         _读源码常量("运行核心/统一网关/流式HTTP.py", "最大事件数上限"))
        self.assertEqual(标定参数集["流式持续秒上限"],
                         _读源码常量("运行核心/统一网关/流式HTTP.py", "最大持续秒上限"))
        self.assertEqual(标定参数集["超时执行全局线程"],
                         _读源码常量("运行核心/能力调用/超时执行.py", "默认全局执行线程上限"))
        self.assertEqual(标定参数集["超时执行每能力线程"],
                         _读源码常量("运行核心/能力调用/超时执行.py", "默认每能力执行线程上限"))
        self.assertEqual(标定参数集["每能力闸门数上限"],
                         _读源码常量("运行核心/能力调用/超时执行.py", "每能力闸门数上限"))
        self.assertEqual(标定参数集["每能力占用明细上限"],
                         _读源码常量("运行核心/能力调用/超时执行.py", "每能力占用明细上限"))
        self.assertEqual(标定参数集["准入拒绝明细上限"],
                         _读源码常量("运行核心/能力调用/超时执行.py", "准入拒绝明细上限"))

    def test_任务池与提供者池现值对账(self) -> None:
        self.assertEqual(标定参数集["任务池活动数"],
                         _读构造默认参数("运行核心/任务调度/任务进程.py",
                                      "任务进程池", "最大活动数"))
        self.assertEqual(标定参数集["任务池排队深度"],
                         _读构造默认参数("运行核心/任务调度/任务进程.py",
                                      "任务进程池", "最大排队数"))
        self.assertEqual(标定参数集["非模型提供者池大小"],
                         _读构造默认参数("运行核心/加载器/提供者隔离/独立进程.py",
                                      "提供者进程池", "池大小"))
        self.assertEqual(标定参数集["资源键表容量"],
                         _读构造默认参数("运行核心/加载器/提供者隔离/独立进程.py",
                                      "提供者进程池", "最大资源键数"))
        self.assertEqual(标定参数集["提供者池大小上限"],
                         _读源码常量("运行核心/加载器/提供者隔离/独立进程.py", "最大允许池大小"))
        self.assertEqual(标定参数集["平台控制面进程池大小"],
                         _读构造默认参数("平台控制面/提供者/进程提供者.py",
                                      "本地进程提供者", "池大小"))
        self.assertEqual(标定参数集["提供者响应表上限"],
                         _读源码常量("平台控制面/提供者/进程提供者.py", "响应表上限"))

    def test_模型侧现值对账(self) -> None:
        self.assertEqual(标定参数集["模型内存安全比例"],
                         _读源码常量("支持库/后端/大语言模型支持库/模型连接器/实现/模型连接器.py",
                                  "内存安全阈值"))

    def test_每档性能参数都等于标定参数集(self) -> None:
        """首版零行为变化：**任何**档位槽位的性能参数都必须逐字段等于标定值。"""
        for 键, 槽位 in 档位表().items():
            self.assertEqual(槽位.性能参数, 标定参数集,
                             f"档位 {键.文本()} 的性能参数偏离了标定值（首版必须零行为变化）")

    def test_任意画像的最终性能参数都等于现值(self) -> None:
        """换画像不换性能参数 —— 首版接线不改变任何行为（分档差异化留给后续批次）。"""
        for 名称, 画像 in 规定画像表.items():
            for 形态 in 部署形态域:
                参数集 = 按画像定档位(画像, 形态)
                self.assertEqual(参数集.性能参数, 标定参数集,
                                 f"{名称}/{形态} 的性能参数偏离现值")


class Test安全红线画像再大也不放开边界(unittest.TestCase):
    """★本批最重要的一条：自适应只决定性能档位，永远不决定安全边界。"""

    def test_参数集不含任何安全边界字段(self) -> None:
        for 名称, 画像 in 规定画像表.items():
            参数集 = 按画像定档位(画像, "服务器")
            通过, 说明 = 校验不含安全边界(参数集.全部最终值())
            self.assertTrue(通过, f"{名称}: {说明}")

    def test_类服务器画像的覆盖被整键拒收(self) -> None:
        """喂「类服务器画像 + 用户想放开边界」→ 越权键**整键拒收并点名**。"""
        结果 = 三层合并(规定画像表["Linux类服务器"], "服务器",
                      用户配置={"监听地址": "0.0.0.0", "要求凭证": 假,
                              "允许路径表": {"/任意"}, "网关工作线程": 96})
        self.assertIn("用户显式配置", 结果.拒收表)
        被拒 = set(结果.拒收表["用户显式配置"])
        self.assertEqual(被拒, {"监听地址", "要求凭证", "允许路径表"})
        最终值 = 结果.最终值表()
        for 键 in ("监听地址", "要求凭证", "允许路径表"):
            self.assertNotIn(键, 最终值, f"安全边界字段 {键} 竟然进了最终值")
        self.assertEqual(最终值["网关工作线程"], 96, "合法性能旋钮必须真的生效")

    def test_拒收后真实网关仍只允许回环(self) -> None:
        """★红线落地的**真实判据**：拒收之后拿真网关安全边界复核。

        用 `运行核心/统一网关/安全边界.py` 的 `请求限制器`（唯一实现）判定：
        `0.0.0.0` 必须仍被拒、`127.0.0.1` 必须仍通过 ——
        即「画像再大（512GB/64核/有 Metal）也放不开监听地址」。
        """
        from 运行核心.统一网关.安全边界 import 请求限制器

        结果 = 三层合并(规定画像表["Linux类服务器"], "服务器",
                      用户配置={"监听地址": "0.0.0.0"})
        self.assertIn("用户显式配置", 结果.拒收表, "0.0.0.0 的覆盖竟然没被拒收")
        self.assertNotIn("监听地址", 结果.最终值表())

        限制器 = 请求限制器()
        通过, _ = 限制器.校验监听地址("0.0.0.0")
        self.assertFalse(通过, "★红线破了：类服务器画像下 0.0.0.0 竟然通过监听校验")
        通过, _ = 限制器.校验监听地址("127.0.0.1")
        self.assertTrue(通过, "回环地址必须仍然允许")
        通过, _ = 限制器.校验监听地址("::")
        self.assertFalse(通过, "IPv6 通配也不得通过")

    def test_三层任何一层都拒收安全边界(self) -> None:
        """判据在**每一层**都成立（不只用户层）：逐层调 `校验覆盖键安全`。"""
        for 层名 in ("内置档位", "部署Profile", "用户显式配置"):
            for 键 in sorted(安全边界字段名):
                通过, 说明, 越权 = 校验覆盖键安全(层名, {键: "任意值"})
                self.assertFalse(通过, f"{层名} 层放过了安全边界字段 {键}")
                self.assertEqual(越权, (键,))
                self.assertIn(键, 说明, "拒收说明必须点名具体字段（不是笼统失败）")
        通过, _, _ = 校验覆盖键安全("用户显式配置", {"网关工作线程": 96})
        self.assertTrue(通过, "合法性能旋钮不得被误拒")
        通过, _, _ = 校验覆盖键安全("用户显式配置", None)
        self.assertTrue(通过, "空覆盖必须通过")

    def test_安全边界名单与决策记录表C逐项对应(self) -> None:
        """名单是**唯一事实源**：`0045` 表 C 的每一项都必须能在名单里找到。"""
        决策记录 = (系统根 / "开发文档/决策记录/0045_零配置自适应与安全红线.md")
        文本 = 决策记录.read_text(encoding="utf-8")
        行 = next((行 for 行 in 文本.splitlines() if "绝不自适应" in 行), "")
        self.assertTrue(行, "决策记录里找不到「绝不自适应」那一行（表 C 的出处）")
        for 关键词 in ("监听地址", "鉴权", "TLS", "权限范围", "允许路径表",
                      "数据目录", "部署形态", "对外服务"):
            self.assertIn(关键词, 行, f"表 C 少了 {关键词}，本测试的对照前提已失效")
        for 字段 in ("监听地址", "要求凭证", "允许路径表", "默认权限范围",
                    "允许本地不验证SSL", "数据目录", "激活指针", "部署形态",
                    "启用对外服务"):
            self.assertIn(字段, 安全边界字段名,
                          f"表 C 的字段 {字段} 不在 `安全边界字段名` 里（判据会漏）")


class Test三层来源可见(unittest.TestCase):
    """D3：每个最终值都能说出「由哪层决定」。"""

    def test_默认全部由内置档位决定(self) -> None:
        结果 = 三层合并(规定画像表["32GB有Metal"], "个人机")
        self.assertEqual(set(结果.来源表), set(结果.档位.全部最终值()))
        for 记录 in 结果.来源表.values():
            self.assertEqual(记录.决定层, "内置档位")
            self.assertEqual(记录.被覆盖的层, ())

    def test_用户覆盖被记账且记住被覆盖的层(self) -> None:
        结果 = 三层合并(规定画像表["32GB有Metal"], "个人机",
                      用户配置={"任务池活动数": 8})
        记录 = 结果.来源表["任务池活动数"]
        self.assertEqual(记录.最终值, 8)
        self.assertEqual(记录.决定层, "用户显式配置")
        self.assertEqual(记录.被覆盖的层, ("内置档位",))

    def test_展示含画像档位与决定层(self) -> None:
        结果 = 三层合并(规定画像表["16GB无GPU"], "个人机",
                      用户配置={"网关工作线程": 32})
        文本 = "\n".join(展示三层结果(结果))
        for 必需 in ("探测到的硬件画像", "选中档位", "最终参数与决定层",
                    "网关工作线程 = 32", "内置档位", "推导说明"):
            self.assertIn(必需, 文本, f"展示清单缺「{必需}」")
        self.assertIn("内存16GB", 文本)

    def test_合并结果不含安全边界且拒收可见(self) -> None:
        结果 = 三层合并(规定画像表["Linux类服务器"], "服务器",
                      用户配置={"监听地址": "0.0.0.0", "任务池活动数": 6})
        通过, 说明 = 校验不含安全边界(结果.最终值表())
        self.assertTrue(通过, 说明)
        self.assertIn("用户显式配置", 结果.拒收表)
        展示 = "\n".join(展示三层结果(结果))
        self.assertIn("被拒收的覆盖", 展示, "拒收必须出现在展示里，不能悄悄没生效")


if __name__ == "__main__":
    unittest.main()
