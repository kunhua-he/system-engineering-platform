"""唯一能力注册表与调用器注入测试（第三十阶段C2工作包）。

覆盖（任务书第6条）：
- 未装配失败：冷启动/销毁后 获取能力调用器 必须抛 未装配 状态与 E未装配 错误码；
- 装配后成功：经生产装配（装配系统）自动注册能力并调用成功；
- 重复装配幂等：同摘要重复装配结果一致，装配次数递增，状态保持 已装配；
- 装配失败回滚：失败后状态=装配失败+错误码，无半装配残留，可重新装配恢复；
- 进程重启重新装配：全新子进程冷启动装配→调用→销毁→再装配 全链路成立；
- 测试间无能力残留：装配/销毁对称，异常也清理，后一测试不得继承前一测试能力。

同时覆盖（任务书第1/2/5条）：
- 唯一执行权威：唯一能力调用服务只接受 公共契约.能力契约.契约.能力注册表；
- 生产装配自动注册：测试不手工 注册能力()，能力全部经 装配系统 注册；
- 调用证据字段完整：请求id/模块版本/能力id/支持库包id/提供者版本/制品摘要/
  成功失败/资源释放结论，成功与失败路径均完整。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 公共契约.能力契约.调用器 import (
    获取能力调用器, 查询装配状态, 注册能力调用器, 设置惰性装配函数,
    能力调用器状态异常,
)
from 公共契约.能力契约.契约 import 能力注册表, 能力实现
from 公共契约.基础类型.结果类型 import 结果
from 运行核心.能力调用.唯一能力调用 import (
    创建并绑定, 销毁全局唯一服务, 唯一能力调用服务, _惰性装配,
)
from 运行核心.能力调用.运行上下文.上下文 import 全局上下文管理器, 运行上下文
from 运行核心.加载器.生命周期管理.管理器 import 装配系统

系统根 = Path(__file__).resolve().parents[2]

支持库声明 = {
    "包id": "迷你.支持库",
    "名称": "迷你支持库",
    "类型": "支持库",
    "版本": "1.2.3",
    "入口": "入口.py",
    "依赖": [],
    "能力": [{
        "能力id": "迷你支持库.问候",
        "名称": "问候",
        "参数": [{"名称": "名称", "类型": "文本"}],
        "返回": "结果",
    }],
}

模块声明 = {
    "包id": "迷你.模块",
    "名称": "迷你模块",
    "类型": "基础模块",
    "版本": "2.0.0",
    "入口": "入口.py",
    "依赖": [{"能力": "迷你支持库.问候"}],
    "能力": [{
        "能力id": "迷你模块.组合问候",
        "名称": "组合问候",
        "参数": [{"名称": "名称", "类型": "文本"}],
        "返回": "结果",
    }],
}

支持库入口代码 = '''\
"""迷你支持库入口：只经 能力注册表 注册，不产生导入副作用。"""

from __future__ import annotations

from 公共契约.基础类型.结果类型 import 结果


def 问候(名称):
    return 结果.成功结果(f"你好{名称}")


def 注册能力(注册表) -> None:
    from 公共契约.能力契约.契约 import 能力实现

    注册表.注册(能力实现(
        能力id="迷你支持库.问候", 包id="迷你.支持库",
        实现函数=问候, 参数=[{"名称": "名称", "类型": "文本"}],
        返回="结果", 说明="迷你问候",
        版本="1.2.3", 提供者id="迷你提供者", 提供者版本="3.4.5",
        制品摘要="摘要迷你123",
    ))
'''

模块入口代码 = '''\
"""迷你模块入口：只持能力 id，经 获取能力调用器 调用支持库能力。"""

from __future__ import annotations

from 公共契约.基础类型.结果类型 import 结果


def 组合问候(名称):
    from 公共契约.能力契约.调用器 import 获取能力调用器

    return 获取能力调用器().调用能力(
        "迷你支持库.问候", {"名称": f"模块{名称}"}, 调用方="迷你模块")


def 注册能力(注册表) -> None:
    from 公共契约.能力契约.契约 import 能力实现

    注册表.注册(能力实现(
        能力id="迷你模块.组合问候", 包id="迷你.模块",
        实现函数=组合问候, 参数=[{"名称": "名称", "类型": "文本"}],
        返回="结果", 说明="迷你组合",
        版本="2.0.0",
    ))
'''


def 写迷你包(根目录: Path, 相对目录: str, 声明: dict, 入口代码: str) -> None:
    """在迷你系统根下写一份包（包声明.json + 入口.py）。"""
    目录 = 根目录 / 相对目录
    目录.mkdir(parents=True, exist_ok=True)
    (目录 / "包声明.json").write_text(
        json.dumps(声明, ensure_ascii=False, indent=2), encoding="utf-8")
    (目录 / "入口.py").write_text(入口代码, encoding="utf-8")


def 构造迷你系统根() -> tuple[Path, Path, Path]:
    """构造迷你系统根：支持库(迷你支持库) + 模块库(迷你模块)。"""
    临时 = Path(tempfile.mkdtemp(prefix="测试_唯一注册表调用器_"))
    支持库根 = 临时 / "支持库"
    模块库根 = 临时 / "模块库"
    支持库根.mkdir()
    模块库根.mkdir()
    写迷你包(支持库根, "迷你支持库", 支持库声明, 支持库入口代码)
    写迷你包(模块库根, "迷你模块", 模块声明, 模块入口代码)
    return 临时, 支持库根, 模块库根


class 唯一注册表调用器测试基类(unittest.TestCase):
    """装配/销毁对称基类：每测试前后回到 未装配，禁止跨测试残留。"""

    def setUp(self):
        # 先销毁再恢复惰性钩子：保证从干净 未装配 开始
        销毁全局唯一服务()
        self.恢复惰性钩子()

    def tearDown(self):
        销毁全局唯一服务()
        self.恢复惰性钩子()

    def 恢复惰性钩子(self) -> None:
        """恢复生产惰性装配钩子（本文件各测试可临时禁用）。"""
        设置惰性装配函数(_惰性装配)

    def 禁用惰性钩子(self) -> None:
        设置惰性装配函数(None)


class Test装配状态机(唯一注册表调用器测试基类):
    """未装配/装配失败/销毁的明确状态与错误码。"""

    def test_未装配获取失败_状态与错误码(self):
        self.禁用惰性钩子()
        self.assertEqual(查询装配状态()["状态"], "未装配")
        with self.assertRaises(能力调用器状态异常) as 上下文:
            获取能力调用器()
        异常 = 上下文.exception
        self.assertEqual(异常.状态, "未装配")
        self.assertEqual(异常.错误码, "E未装配")

    def test_装配失败后获取_携带状态错误码与原因(self):
        设置惰性装配函数(lambda: (_ for _ in ()).throw(ValueError("模拟装配失败")))
        with self.assertRaises(能力调用器状态异常) as 上下文:
            获取能力调用器()
        异常 = 上下文.exception
        self.assertEqual(异常.状态, "装配失败")
        self.assertEqual(异常.错误码, "E装配失败")
        self.assertIn("模拟装配失败", 异常.错误说明)
        状态 = 查询装配状态()
        self.assertEqual(状态["状态"], "装配失败")
        self.assertEqual(状态["错误码"], "E装配失败")
        # 粘性失败：不重新装配不得恢复
        with self.assertRaises(能力调用器状态异常) as 上下文二:
            获取能力调用器()
        self.assertEqual(上下文二.exception.状态, "装配失败")

    def test_装配失败后可重新装配恢复(self):
        设置惰性装配函数(lambda: (_ for _ in ()).throw(RuntimeError("模拟装配失败")))
        with self.assertRaises(能力调用器状态异常):
            获取能力调用器()
        注册表 = 能力注册表()
        注册表.注册(能力实现(
            能力id="恢复.能力", 包id="恢复.包",
            实现函数=lambda: 结果.成功结果("已恢复"), 参数=[], 返回="结果"))
        创建并绑定(注册表)
        self.assertEqual(查询装配状态()["状态"], "已装配")
        调用器 = 获取能力调用器()
        self.assertTrue(调用器.调用能力("恢复.能力", {}).成功)

    def test_销毁后回到未装配(self):
        注册表 = 能力注册表()
        注册表.注册(能力实现(
            能力id="临时.能力", 包id="临时.包",
            实现函数=lambda: 结果.成功结果("临时"), 参数=[], 返回="结果"))
        创建并绑定(注册表)
        self.assertEqual(查询装配状态()["状态"], "已装配")
        销毁全局唯一服务()
        self.assertEqual(查询装配状态()["状态"], "未装配")
        self.assertEqual(查询装配状态()["错误码"], "")
        self.禁用惰性钩子()
        with self.assertRaises(能力调用器状态异常) as 上下文:
            获取能力调用器()
        self.assertEqual(上下文.exception.状态, "未装配")


class Test唯一注册表执行权威(唯一注册表调用器测试基类):
    """全仓唯一执行权威：唯一能力调用服务只接受 能力契约.契约.能力注册表。"""

    def test_非权威注册表被拒绝(self):
        with self.assertRaises(TypeError):
            唯一能力调用服务("不是注册表")  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            创建并绑定("不是注册表")  # type: ignore[arg-type]
        # 创建并绑定 异常必须回滚状态，不留 装配中 半状态
        状态 = 查询装配状态()
        self.assertEqual(状态["状态"], "装配失败")
        self.assertEqual(状态["错误码"], "E装配失败")

    def test_绑定对象是唯一权威注册表类型(self):
        注册表 = 能力注册表()
        注册表.注册(能力实现(
            能力id="权威.能力", 包id="权威.包",
            实现函数=lambda: 结果.成功结果("权威"), 参数=[], 返回="结果"))
        服务 = 创建并绑定(注册表)
        from 公共契约.能力契约.契约 import 能力注册表 as 权威注册表类型
        self.assertIsInstance(服务.注册表, 权威注册表类型)
        self.assertEqual(服务.注册表.获取("权威.能力").包id, "权威.包")


class Test生产装配自动注册(唯一注册表调用器测试基类):
    """模块公开能力必须由生产装配自动注册，测试不手工注册。"""

    def test_装配系统自动注册能力并注入调用器(self):
        临时, 支持库根, 模块库根 = 构造迷你系统根()
        self.addCleanup(shutil.rmtree, 临时, ignore_errors=True)
        结果 = 装配系统(支持库根, 模块库根)
        self.assertTrue(结果.成功, str(结果.问题列表))
        self.assertEqual(结果.声明能力数, 2)
        self.assertEqual(结果.已注册能力数, 2)
        状态 = 查询装配状态()
        self.assertEqual(状态["状态"], "已装配")
        调用器 = 获取能力调用器()
        # 模块能力经唯一调用服务调用支持库能力（模块只持能力 id）
        self.assertEqual(调用器.调用能力("迷你模块.组合问候", {"名称": "世界"}).值,
                         "你好模块世界")


class Test装配与调用闭环(唯一注册表调用器测试基类):
    """装配后成功、失败路径、证据字段完整。"""

    def test_装配后调用成功_证据字段完整(self):
        临时, 支持库根, 模块库根 = 构造迷你系统根()
        self.addCleanup(shutil.rmtree, 临时, ignore_errors=True)
        结果 = 装配系统(支持库根, 模块库根)
        self.assertTrue(结果.成功, str(结果.问题列表))
        调用器 = 获取能力调用器()
        全局上下文管理器.进入(运行上下文(模块id="迷你.模块", 包版本="2.0.0"))
        try:
            调用结果 = 调用器.调用能力("迷你模块.组合问候", {"名称": "世界"})
        finally:
            全局上下文管理器.退出()
        self.assertTrue(调用结果.成功, str(调用结果.错误))
        self.assertEqual(调用结果.值, "你好模块世界")
        记录 = 调用器.查询调用历史(1)[0]
        证据 = 记录["证据"]
        必填字段表 = ("请求id", "模块版本", "能力id", "支持库包id", "提供者版本",
                       "制品摘要", "成功", "资源释放结论")
        for 字段 in 必填字段表:
            self.assertIn(字段, 证据, f"证据缺少字段: {字段}")
        self.assertTrue(证据["请求id"])
        self.assertEqual(证据["能力id"], "迷你模块.组合问候")
        # 模块自身能力：提供实现的支持库包 id 即模块包（S0.3 模块经调用器组合）
        self.assertEqual(证据["支持库包id"], "迷你.模块")
        self.assertEqual(证据["模块版本"], "2.0.0")
        self.assertTrue(证据["成功"])
        self.assertEqual(证据["资源释放结论"], "版本锁已释放")
        # 直接调用支持库能力：支持库包id/提供者版本/制品摘要/支持库版本 齐全
        支持库结果 = 调用器.调用能力("迷你支持库.问候", {"名称": "支持库"})
        self.assertTrue(支持库结果.成功)
        self.assertEqual(支持库结果.值, "你好支持库")
        支持库证据 = 调用器.查询调用历史(1)[0]["证据"]
        self.assertEqual(支持库证据["支持库包id"], "迷你.支持库")
        self.assertEqual(支持库证据["版本"], "1.2.3")
        self.assertEqual(支持库证据["提供者版本"], "3.4.5")
        self.assertEqual(支持库证据["制品摘要"], "摘要迷你123")
        # 版本锁零残留
        服务 = 获取能力调用器()
        self.assertEqual(服务.版本锁定.引用数(包id="迷你.模块", 版本="2.0.0"), 0)
        self.assertEqual(服务.版本锁定.引用数(包id="迷你.支持库", 版本="1.2.3"), 0)

    def test_失败路径证据完整(self):
        临时, 支持库根, 模块库根 = 构造迷你系统根()
        self.addCleanup(shutil.rmtree, 临时, ignore_errors=True)
        装配系统(支持库根, 模块库根)
        调用器 = 获取能力调用器()
        失败结果 = 调用器.调用能力("不存在.能力", {})
        self.assertFalse(失败结果.成功)
        self.assertEqual(失败结果.错误码, "能力不存在")
        最近 = 调用器.最近失败(1)[0]
        证据 = 最近["证据"]
        self.assertFalse(证据["成功"])
        self.assertEqual(证据["错误码"], "能力不存在")
        self.assertEqual(证据["能力id"], "不存在.能力")
        self.assertIn("资源释放结论", 证据)
        self.assertEqual(证据["资源释放结论"], "无版本锁定需求")

    def test_重复装配幂等(self):
        临时, 支持库根, 模块库根 = 构造迷你系统根()
        self.addCleanup(shutil.rmtree, 临时, ignore_errors=True)
        结果一 = 装配系统(支持库根, 模块库根)
        结果二 = 装配系统(支持库根, 模块库根)
        self.assertTrue(结果一.成功, str(结果一.问题列表))
        self.assertTrue(结果二.成功, str(结果二.问题列表))
        self.assertEqual(结果一.已注册能力数, 结果二.已注册能力数)
        self.assertEqual(结果一.顺序列表, 结果二.顺序列表)
        状态 = 查询装配状态()
        self.assertEqual(状态["状态"], "已装配")
        self.assertGreaterEqual(状态["装配次数"], 2)
        # 同一注册表显式传入再次装配：同摘要幂等成功
        共享注册表 = 能力注册表()
        结果三 = 装配系统(支持库根, 模块库根, 共享注册表)
        self.assertTrue(结果三.成功, str(结果三.问题列表))
        调用器 = 获取能力调用器()
        self.assertEqual(调用器.调用能力("迷你支持库.问候", {"名称": "幂等"}).值,
                         "你好幂等")

    def test_装配中拒绝并发重复装配(self):
        from 公共契约.能力契约.调用器 import 标记装配中
        标记装配中()
        try:
            注册表 = 能力注册表()
            with self.assertRaises(能力调用器状态异常) as 上下文:
                创建并绑定(注册表)
            self.assertEqual(上下文.exception.状态, "装配中")
            self.assertEqual(上下文.exception.错误码, "E装配中")
        finally:
            销毁全局唯一服务()


class Test进程重启重新装配(唯一注册表调用器测试基类):
    """全新进程冷启动：装配→注册→调用→销毁→再装配 全链路成立。"""

    def test_全新子进程冷启动装配与调用(self):
        临时, 支持库根, 模块库根 = 构造迷你系统根()
        self.addCleanup(shutil.rmtree, 临时, ignore_errors=True)
        脚本 = f"""
import json, sys
from pathlib import Path
sys.path.insert(0, {str(系统根)!r})
from 公共契约.能力契约.调用器 import 查询装配状态, 获取能力调用器
from 运行核心.能力调用.唯一能力调用 import 销毁全局唯一服务
from 运行核心.加载器.生命周期管理.管理器 import 装配系统

支持库根 = Path({str(支持库根)!r})
模块库根 = Path({str(模块库根)!r})
# 冷启动：全新进程默认 未装配（无历史全局单例、无测试预注册）
if 查询装配状态()["状态"] != "未装配":
    raise SystemExit("冷启动状态异常: " + json.dumps(查询装配状态(), ensure_ascii=False))
结果一 = 装配系统(支持库根, 模块库根)
if not 结果一.成功:
    raise SystemExit("装配失败: " + json.dumps(结果一.问题列表, ensure_ascii=False))
if 查询装配状态()["状态"] != "已装配":
    raise SystemExit("装配后状态异常")
调用器 = 获取能力调用器()
结果 = 调用器.调用能力("迷你支持库.问候", {{"名称": "冷启动"}})
if not 结果.成功 or 结果.值 != "你好冷启动":
    raise SystemExit("调用失败: " + json.dumps(结果.转字典(), ensure_ascii=False))
# 销毁后再次装配（进程内重装）
销毁全局唯一服务()
if 查询装配状态()["状态"] != "未装配":
    raise SystemExit("销毁后状态异常")
结果二 = 装配系统(支持库根, 模块库根)
if not 结果二.成功:
    raise SystemExit("二次装配失败")
if 获取能力调用器().调用能力("迷你模块.组合问候", {{"名称": "重装"}}).值 != "你好模块重装":
    raise SystemExit("二次装配后调用失败")
print(json.dumps({{"冷启动": True, "重装": True}}, ensure_ascii=False))
"""
        进程 = subprocess.run(
            [sys.executable, "-c", 脚本], capture_output=True, text=True,
            timeout=300, cwd=str(系统根),
        )
        self.assertEqual(进程.returncode, 0, f"子进程失败:\n{进程.stdout}\n{进程.stderr}")
        self.assertIn("冷启动", 进程.stdout)


class Test测试间无能力残留(唯一注册表调用器测试基类):
    """装配/销毁对称：销毁后获取必须 未装配，后一测试不继承前一测试能力。"""

    def test_销毁后无能力残留(self):
        临时, 支持库根, 模块库根 = 构造迷你系统根()
        self.addCleanup(shutil.rmtree, 临时, ignore_errors=True)
        # 先真实装配并调用
        装配系统(支持库根, 模块库根)
        调用器 = 获取能力调用器()
        self.assertTrue(调用器.调用能力("迷你支持库.问候", {"名称": "世界"}).成功)
        # 销毁 → 未装配 → 获取失败（禁止残留让后一测试继承）
        销毁全局唯一服务()
        self.assertEqual(查询装配状态()["状态"], "未装配")
        self.禁用惰性钩子()
        with self.assertRaises(能力调用器状态异常) as 上下文:
            获取能力调用器()
        self.assertEqual(上下文.exception.状态, "未装配")
        self.assertEqual(上下文.exception.错误码, "E未装配")
        # 重新装配 → 全新注册表，调用再次成功
        self.恢复惰性钩子()
        装配系统(支持库根, 模块库根)
        调用器二 = 获取能力调用器()
        self.assertTrue(调用器二.调用能力("迷你支持库.问候", {"名称": "再来"}).成功)


if __name__ == "__main__":
    unittest.main()
