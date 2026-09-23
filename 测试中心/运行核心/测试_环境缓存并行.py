"""运行环境缓存与并行构建测试：命中/重建/失败三态证据、并行与串行锁。

构建路径**不再换掉被测本体**（`测试伪装门禁` 规则1 P1 收口，2026-09-23）：
经生产自带注入口 `环境管理器.venv`（`:692`「兼容显式注入的环境创建器」）注入
`环境夹具.假venv模块`，真 `_构建环境` 与真 `校验环境` 照跑（见
`测试中心/运行核心/环境夹具.py` 的取舍说明）；构建次数由**第三方边界实测**
（`假venv.调用次数`）给出，不再是夹具自增的计数器。失败路径用 venv.create
抛错触发真实清理逻辑；另用 无第三方依赖 提供者 与 已构建的真实提供者 验证缓存命中证据。
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 运行核心.运行环境管理器.环境管理器 import (
    并行确保环境, 批量确保环境, 计算环境摘要,
    环境目录, 读取依赖锁, 确保环境,
)
from 测试中心.运行核心.环境夹具 import 注入假venv, 钉住运行缓存根

受管仓库根 = Path(__file__).resolve().parents[2]
from 公共契约.运行时.平台适配 import 清只读后删除树
from 公共契约.基础类型.逻辑类型 import 真

#: ★ A 档泄漏收口（2026-09-23）：受管临时根在仓库内**固定排除目录** `工程缓存/` 下。
#: `dir=` 显式指向它 ⇒ 落点与**测试运行时**的 `TMPDIR` 解耦（平台跑测试时 `TMPDIR` 被指进
#: 仓库工作目录，裸 `mkdtemp()` 会把夹具造进仓库）。`工程缓存` 在
#: `开发工具/项目编译/工作区指纹.py` 的 `固定排除目录` 里 ⇒ 即便进程被 SIGKILL、
#: 清理没跑到，残留也进不了工作区指纹（`.gitignore` 保不住：指纹的未跟踪腿不用
#: `--exclude-standard`）。清理走平台唯一删树原语 `清只读后删除树`（本类用例常造
#: `0o555` 目录 / `0o444` 文件，plain `shutil.rmtree` 会被权限位挡住）。
受管临时根 = 受管仓库根 / "工程缓存" / "测试临时"
受管临时根.mkdir(parents=True, exist_ok=True)

假构建耗时秒 = 0.4


def 样例锁(版本: str = "1.2.0", 索引地址: str | None = None) -> dict:
    包 = {"名称": "python-docx", "版本": 版本, "模块名": "docx"}
    if 索引地址:
        包["索引地址"] = 索引地址
    return {"包": [包]}


class Test环境缓存并行(unittest.TestCase):
    """环境缓存审计与并行构建闭环测试。"""

    def setUp(self):
        self.临时 = Path(tempfile.mkdtemp(dir=受管临时根))
        self.addCleanup(清只读后删除树, self.临时, 忽略失败=真)
        # ★ 运行缓存根钉到**本用例的临时根**（返回还原函数登记给 addCleanup，还原进用例前原值）：
        # 不钉的话，网关进程设的 `系统底座_工程缓存根`/`系统底座_提供者环境根` 会把缓存根
        # 改指真仓库，证据与环境目录全落错地方（见 环境夹具.钉住运行缓存根）。
        self.addCleanup(钉住运行缓存根(self.临时 / "工程缓存"))
        # 模拟系统根结构：支持库+模块库 祖先后，工程缓存落在临时根
        (self.临时 / "支持库").mkdir()
        (self.临时 / "模块库").mkdir()

    def 新提供者(self, 名称: str, 锁: dict | None = None) -> Path:
        目录 = self.临时 / 名称
        目录.mkdir()
        if 锁 is not None:
            (目录 / "依赖锁.json").write_text(
                json.dumps(锁, ensure_ascii=False), encoding="utf-8")
        return 目录

    def 证据文件(self) -> Path:
        return self.临时 / "工程缓存" / "提供者运行环境" / "缓存证据.jsonl"

    def 证据行(self) -> list[dict]:
        文件 = self.证据文件()
        if not 文件.is_file():
            return []
        return [json.loads(行) for 行 in
                文件.read_text(encoding="utf-8").splitlines() if 行.strip()]

    def 注入构建(self, **参数):
        """经生产自带注入口注入假 venv（第三方边界）；真构建/真校验照跑。

        替换旧的 `mock.patch(…校验环境)` + `mock.patch(…_构建环境)`：那两处把被测
        逻辑整段换掉（`测试伪装门禁` 规则1 P1），断言对象是夹具本身。默认注入
        `耗时秒=假构建耗时秒`，用于观测并行度（真 `_构建环境` 会真 sleep 这一步）。
        """
        参数.setdefault("耗时秒", 假构建耗时秒)
        return 注入假venv(**参数)

    def test_缓存命中复用与证据(self):
        """同摘要两次确保 → 第二次命中、不重建、证据两行。"""
        提供者 = self.新提供者("docx提供者", 样例锁())
        with self.注入构建() as 假venv:
            结果一 = 确保环境(提供者)
            self.assertTrue(结果一.成功)
            self.assertEqual(假venv.调用次数, 1)
            结果二 = 确保环境(提供者)
            self.assertTrue(结果二.成功)
        self.assertEqual(假venv.调用次数, 1)  # 第二次未重建
        self.assertEqual(结果一.解释器路径, 结果二.解释器路径)
        证据 = self.证据行()
        self.assertEqual([行["类型"] for 行 in 证据], ["重建", "命中"])

    def test_输入变化新摘要重建旧目录保留(self):
        """依赖锁变化 → 新摘要目录重建，旧目录保留（不可变）。"""
        提供者 = self.新提供者("docx提供者", 样例锁("1.2.0"))
        with self.注入构建():
            结果一 = 确保环境(提供者)
            摘要一 = 结果一.环境摘要
            目录一 = 环境目录(提供者, 摘要一)
            self.assertTrue((目录一 / "bin" / "python3").is_file())
            # 输入变化：版本 1.2.0 → 1.1.0
            (提供者 / "依赖锁.json").write_text(
                json.dumps(样例锁("1.1.0"), ensure_ascii=False), encoding="utf-8")
            结果二 = 确保环境(提供者)
            摘要二 = 结果二.环境摘要
        self.assertNotEqual(摘要一, 摘要二)
        目录二 = 环境目录(提供者, 摘要二)
        self.assertTrue((目录二 / "bin" / "python3").is_file())
        self.assertTrue(目录一.is_dir())  # 旧目录保留
        证据 = self.证据行()
        self.assertEqual([行["类型"] for 行 in 证据], ["重建", "重建"])
        self.assertEqual({行["摘要"] for 行 in 证据}, {摘要一, 摘要二})

    def test_不同提供者不同制品仓库并行(self):
        """3 个不同提供者（不同制品仓库）并行 → 耗时明显小于串行且互不干扰。"""
        提供者表 = [
            self.新提供者(f"并行提供者{序号}", 样例锁("1.0", 索引地址=f"http://127.0.0.1:9{序号}/仓库"))
            for 序号 in (1, 2, 3)
        ]
        开始 = time.time()
        with self.注入构建() as 假venv:
            结果表 = 并行确保环境(提供者表)
        耗时 = time.time() - 开始
        self.assertTrue(all(结果.成功 for 结果 in 结果表))
        self.assertEqual(假venv.调用次数, 3)
        for 提供者 in 提供者表:
            锁 = 读取依赖锁(提供者)
            目标 = 环境目录(提供者, 计算环境摘要(锁, 提供者.name))
            self.assertTrue((目标 / "bin" / "python3").is_file())
        证据 = self.证据行()
        self.assertEqual(len([行 for 行 in 证据 if 行["类型"] == "重建"]), 3)
        # 并行度**与同批串行实测对比**，不写死秒数：真 `_构建环境` 每次有真实开销
        # （pip 安装 + import 校验两个子进程 + 原子落盘），写死阈值会把真实开销
        # 误判成「没并行」。串行对照用不同提供者名（摘要含提供者 id → 不会命中上一批缓存）。
        串行对照表 = [
            self.新提供者(f"串行对照提供者{序号}", 样例锁("1.0", 索引地址=f"http://127.0.0.1:8{序号}/仓库"))
            for 序号 in (1, 2, 3)
        ]
        开始串行 = time.time()
        with self.注入构建() as 假venv串行:
            for 提供者 in 串行对照表:
                确保环境(提供者)
        串行耗时 = time.time() - 开始串行
        self.assertEqual(假venv串行.调用次数, 3)
        self.assertLess(耗时, 串行耗时 * 0.75,
                        f"并行 {耗时:.2f}s 未明显快于同批串行 {串行耗时:.2f}s")

    def test_同提供者并发串行(self):
        """并发提交同一提供者 → 顺序构建：一次重建 + 一次命中，耗时 ≥ 串行。"""
        提供者 = self.新提供者("串行提供者", 样例锁())
        开始 = time.time()
        with self.注入构建() as 假venv:
            结果表 = 并行确保环境([提供者, 提供者])
        耗时 = time.time() - 开始
        self.assertTrue(all(结果.成功 for 结果 in 结果表))
        self.assertEqual(假venv.调用次数, 1)  # 第二个任务命中
        # 第二个任务被提供者锁阻塞直至首个构建完成 → 总耗时 ≥ 单次构建
        self.assertGreaterEqual(耗时, 假构建耗时秒 - 0.05)
        证据 = self.证据行()
        self.assertEqual([行["类型"] for 行 in 证据], ["重建", "命中"])

    def test_同制品仓库跨提供者串行(self):
        """不同提供者但同一制品仓库 → 锁串行（不并发构建）。"""
        提供者表 = [
            self.新提供者(f"同仓提供者{序号}", 样例锁("1.0", 索引地址="http://127.0.0.1:99/共用仓库"))
            for 序号 in (1, 2)
        ]
        开始 = time.time()
        with self.注入构建() as 假venv:
            结果表 = 并行确保环境(提供者表)
        耗时 = time.time() - 开始
        self.assertTrue(all(结果.成功 for 结果 in 结果表))
        self.assertEqual(假venv.调用次数, 2)
        self.assertGreaterEqual(耗时, 假构建耗时秒 * 2 - 0.15)  # 串行 ≈ 2×单次

    def test_构建失败清理半成品与失败证据(self):
        """venv 创建失败 → 清理临时目录 + 失败证据（错误码/错误说明/输入哈希）。"""
        提供者 = self.新提供者("失败提供者", 样例锁())
        with self.注入构建(抛错=OSError("模拟构建失败")):
            结果 = 确保环境(提供者, 超时秒=10)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "提供者不可用")
        self.assertIn("模拟构建失败", 结果.错误说明)
        # 半成品（.构建中_*）已清理
        残留 = list((self.临时 / "工程缓存" / "提供者运行环境" / "失败提供者").glob(".构建中_*"))
        self.assertEqual(残留, [])
        证据 = self.证据行()
        self.assertEqual(证据[-1]["类型"], "失败")
        self.assertEqual(证据[-1]["错误码"], "提供者不可用")
        self.assertIn("模拟构建失败", 证据[-1]["错误说明"])
        self.assertTrue(证据[-1]["输入哈希"])

    def test_无第三方依赖命中证据(self):
        """无依赖锁/仅系统工具 → 系统解释器 + 命中证据（真实路径）。"""
        无锁提供者 = self.新提供者("无锁提供者")
        结果 = 确保环境(无锁提供者)
        self.assertTrue(结果.成功)
        证据 = self.证据行()
        self.assertEqual(证据[-1]["类型"], "命中")
        self.assertEqual(证据[-1]["摘要"], "")
        系统工具提供者 = self.新提供者("系统工具提供者", {
            "包": [{"名称": "LibreOffice", "版本": "7.6", "模块名": "",
                    "来源": "外部应用"}]})
        结果二 = 确保环境(系统工具提供者)
        self.assertTrue(结果二.成功)
        证据二 = self.证据行()
        self.assertEqual(证据二[-1]["类型"], "命中")

    def test_证据可审计(self):
        """证据 jsonl 每行可解析且字段齐全。"""
        提供者 = self.新提供者("审计提供者", 样例锁())
        with self.注入构建():
            确保环境(提供者)
            确保环境(提供者)
        证据 = self.证据行()
        self.assertEqual(len(证据), 2)
        必填字段 = {"时间", "提供者id", "摘要", "类型", "输入哈希", "系统版本", "错误码", "错误说明"}
        for 行 in 证据:
            self.assertEqual(必填字段, set(行))
            self.assertIn(行["类型"], {"命中", "重建", "失败"})
        self.assertTrue(证据[0]["输入哈希"])
        self.assertTrue(证据[0]["时间"])

    def test_批量确保环境入口(self):
        """批量入口等价并行入口；空列表返回空。"""
        self.assertEqual(批量确保环境([]), [])
        提供者 = self.新提供者("批量提供者", 样例锁())
        with self.注入构建():
            结果表 = 批量确保环境([提供者])
        self.assertEqual(len(结果表), 1)
        self.assertTrue(结果表[0].成功)

    def test_真实已构建提供者缓存命中(self):
        """已构建的真实提供者（支持库/适配层）→ 命中复用，不触发重建。"""
        系统根 = Path(__file__).resolve().parents[2]
        # ★ 本条判的是**真仓库**那把缓存（`<系统根>/工程缓存` 下已构建的提供者环境）——
        # 与其余用例「临时根即运行缓存根」不同：把两个变量**重钉到真仓库根**
        # （addCleanup LIFO：这条的还原先跑 → 回到临时根 → 再回 setUp 记的原值）。
        # 不重钉的话，本类 setUp 钉的临时根会把真仓库已构建环境判成「未构建」而整条跳过。
        self.addCleanup(钉住运行缓存根(系统根 / "工程缓存"))
        适配层 = 系统根 / "支持库" / "适配层"
        已构建 = None
        if 适配层.is_dir():
            for 提供者目录 in sorted(适配层.iterdir()):
                依赖锁 = 读取依赖锁(提供者目录) if (提供者目录 / "依赖锁.json").is_file() else {}
                if not 依赖锁:
                    continue
                目标 = 环境目录(提供者目录, 计算环境摘要(依赖锁, 提供者目录.name))
                if (目标 / "bin" / "python3").is_file():
                    已构建 = 提供者目录
                    break
        if 已构建 is None:
            self.skipTest("未找到已构建的真实提供者环境")
        开始 = time.time()
        结果 = 确保环境(已构建, 超时秒=60)
        耗时 = time.time() - 开始
        self.assertTrue(结果.成功)
        self.assertEqual(结果.环境摘要,
                         计算环境摘要(读取依赖锁(已构建), 已构建.name))
        self.assertLess(耗时, 30)  # 命中不应触发真实重建
        真实证据文件 = 系统根 / "工程缓存" / "提供者运行环境" / "缓存证据.jsonl"
        self.assertTrue(真实证据文件.is_file())
        证据 = [json.loads(行) for 行 in
                真实证据文件.read_text(encoding="utf-8").splitlines() if 行.strip()]
        self.assertEqual(证据[-1]["类型"], "命中")
        self.assertEqual(证据[-1]["提供者id"], 已构建.name)


if __name__ == "__main__":
    unittest.main()
