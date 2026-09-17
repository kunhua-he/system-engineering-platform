"""注册口径漂移（默认值/必填 新维度）判据与**发布门禁接线**测试。

覆盖两件事：
1. 判据分治（2026-09-17 新增判据，提交 222e485f）：默认值/必填 **硬不一致判红**、
   漏声明按 *注册口径存量基线.json* **分桶**（基线内=存量只报／基线外=新增判红）、
   判据**承重**（把新判据从模块源码里删掉后，同一夹具不再被报 ⇒ 判红确由新判据承担）。
2. 发布门禁接线：门禁项「契约声明一致（注册口径，新增类）」是**默认强制项**，
   新增类不一致**真阻断**、仅存量场景**不阻断只报**（否则上线即红，废掉存量分治）。

夹具一律落 `tempfile` 临时根（不写仓库任何文件）；真实仓库只读取、只断言现状。
"""
from __future__ import annotations

import ast
import io
import contextlib
import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.基础类型.逻辑类型 import 真, 假
from 开发工具.契约编译.漂移检测 import 全仓注册口径统计, 默认存量基线路径
from 开发工具.发布门禁.运行发布门禁 import 执行门禁, 注册口径新增判据

门禁模块路径 = 系统根 / "开发工具" / "发布门禁" / "运行发布门禁.py"
判据模块路径 = 系统根 / "开发工具" / "契约编译" / "漂移检测.py"
门禁新增项名 = "契约声明一致（注册口径，新增类）"

# 夹具源包：真实存在、且其「注册口径存量基线」里有 2 条存量漏声明，
# 正好用来验证「同一包内存量与新增分桶互不干扰」。
夹具源包 = 系统根 / "支持库" / "前端" / "桌面宿主"
基准包相对路径 = "支持库/前端/桌面宿主"
受管验证原串 = '"受管验证", "类型": "逻辑型", "必填": False, "默认值": False'
篡改默认值不等 = '"受管验证", "类型": "逻辑型", "必填": False, "默认值": True'
篡改默认值缺失 = '"受管验证", "类型": "逻辑型", "必填": False'
篡改必填不等 = '"受管验证", "类型": "逻辑型", "必填": True, "默认值": False'

_夹具缓存: dict[str, Path] = {}
_缓存根 = tempfile.mkdtemp(prefix="注册口径漂移测试_")


def 建夹具(名: str, 篡改: str = "", 相对路径: str = 基准包相对路径) -> Path:
    """复制真实包成夹具系统根；篡改只落在目标包 `__init__.py` 的注册行上。"""
    if 名 in _夹具缓存:
        return _夹具缓存[名]
    根 = Path(_缓存根) / 名
    目标 = 根 / 相对路径
    目标.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(夹具源包, 目标, ignore=shutil.ignore_patterns("__pycache__"))
    if 篡改:
        入口 = 目标 / "__init__.py"
        文本 = 入口.read_text(encoding="utf-8")
        assert 受管验证原串 in 文本, f"{名}: 夹具失效——源包注册行已变，请更新 受管验证原串"
        入口.write_text(文本.replace(受管验证原串, 篡改), encoding="utf-8")
    _夹具缓存[名] = 根
    return 根


def 统计(根: Path) -> dict:
    """按仓库正式基线跑一次全仓注册口径统计（夹具根 / 真实根均适用）。"""
    return 全仓注册口径统计(根, 基线文件=默认存量基线路径())


def 去判据模块():
    """把新判据（默认值/必填 比对段）从模块源码里删掉，作为「没有新判据」的对照组。

    这是**判据承重**证明：若删掉后夹具不再被报，则判红确由新判据承担，不是别处巧合报出。
    故本测试与源码里的两处锚点注释绑定——锚点改名时本测试会失败并提示更新锚点，
    这正是它要守的边界（判据不可被静默摘除）。
    """
    文本 = 判据模块路径.read_text(encoding="utf-8")
    起点锚点 = "        # 新判据：默认值 / 必填"
    终点锚点 = "    if 基线键集 is not None:\n        结果.基线过期列表"
    assert 起点锚点 in 文本, "去判据失败：找不到新判据起点锚点，请同步本测试"
    assert 终点锚点 in 文本, "去判据失败：找不到新判据终点锚点，请同步本测试"
    改写 = (文本[:文本.index(起点锚点)]
          + "        pass  # 【判据承重对照：新判据已被删除】\n"
          + 文本[文本.index(终点锚点):])
    assert "注册参数 未声明默认值" not in 改写, "去判据失败：改写后仍残留新判据"
    路径 = Path(_缓存根) / "漂移检测_去判据_注册口径.py"
    路径.write_text(改写, encoding="utf-8")
    规格 = importlib.util.spec_from_file_location("漂移检测_去判据_注册口径", 路径)
    模块 = importlib.util.module_from_spec(规格)
    sys.modules["漂移检测_去判据_注册口径"] = 模块  # dataclass 需要能在 sys.modules 里找到自己
    规格.loader.exec_module(模块)
    return 模块


class 判据分桶测试(unittest.TestCase):
    """默认值/必填 新判据：硬不一致判红、漏声明按基线分桶。"""

    def test_默认值硬不一致判红(self) -> None:
        统计结果 = 统计(建夹具("夹具A_默认值不等", 篡改默认值不等))
        self.assertEqual(1, 统计结果["默认值硬不一致数"],
                         f"注册默认值 True ≠ 契约默认值 False 必须计硬不一致；"
                         f"判红={统计结果['问题列表'][:3]}")
        self.assertTrue(any("默认值" in 行 for 行 in 统计结果["问题列表"]),
                        f"硬不一致必须进判红清单：{统计结果['问题列表'][:3]}")

    def test_必填硬不一致判红(self) -> None:
        统计结果 = 统计(建夹具("夹具C_必填不等", 篡改必填不等))
        self.assertEqual(1, 统计结果["必填硬不一致数"],
                         f"注册 必填 True ≠ 契约 必填 False 必须计硬不一致；"
                         f"判红={统计结果['问题列表'][:3]}")

    def test_漏声明基线内只报不判红(self) -> None:
        统计结果 = 统计(建夹具("夹具B1_默认值缺失_基线内"))
        self.assertEqual([], 统计结果["问题列表"], "基线内漏声明不得判红（存量分治）")
        self.assertEqual(0, 统计结果["新增漏声明数"])
        self.assertEqual(2, 统计结果["存量漏声明数"], "该包基线内应有 2 条存量漏声明")
        self.assertTrue(统计结果["基线"]["生效"], "基线必须生效，否则分不出存量/新增")

    def test_漏声明基线外新增判红(self) -> None:
        统计结果 = 统计(建夹具("夹具B2_默认值缺失_基线外", 篡改默认值缺失))
        self.assertEqual(1, 统计结果["新增漏声明数"],
                         f"基线外漏声明必须判红：{统计结果['新增漏声明列表'][:3]}")
        self.assertEqual(1, len(统计结果["问题列表"]))
        self.assertIn("未声明默认值", 统计结果["新增漏声明列表"][0])

    def test_同包内存量与新增分桶互不干扰(self) -> None:
        统计结果 = 统计(建夹具("夹具B2_默认值缺失_基线外", 篡改默认值缺失))
        self.assertEqual(2, 统计结果["存量漏声明数"],
                         "新增（受管验证）不得把同包 2 条存量（基线内）一并带成新增")

    def test_新包漏声明全部判新增(self) -> None:
        统计结果 = 统计(建夹具("夹具D_新包", 相对路径="模块库/桌面宿主新包"))
        self.assertGreaterEqual(统计结果["新增漏声明数"], 1,
                                "基线里没有的包，其漏声明必须按新增判红")

    def test_基准未改动零判红(self) -> None:
        统计结果 = 统计(建夹具("夹具基准"))
        self.assertEqual([], 统计结果["问题列表"], "未改动真实包不得被判红")
        self.assertEqual(2, 统计结果["存量漏声明数"], "未改动真实包的存量漏声明照旧只报")


class 判据承重测试(unittest.TestCase):
    """删掉新判据后同一批夹具不再被报 ⇒ 判红确由新判据承担。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.去判据 = 去判据模块()
        cls.基线文件 = 默认存量基线路径()

    def _对照组统计(self, 名: str, 篡改: str) -> dict:
        return self.去判据.全仓注册口径统计(建夹具(名, 篡改), 基线文件=self.基线文件)

    def test_去判据后默认值不等不再被报(self) -> None:
        对照 = self._对照组统计("夹具A_默认值不等", 篡改默认值不等)
        self.assertEqual(0, 对照["默认值硬不一致数"])
        self.assertEqual([], 对照["问题列表"], "去掉新判据后同一夹具零判红")

    def test_去判据后必填不等不再被报(self) -> None:
        对照 = self._对照组统计("夹具C_必填不等", 篡改必填不等)
        self.assertEqual(0, 对照["必填硬不一致数"])
        self.assertEqual([], 对照["问题列表"])

    def test_去判据后新增漏声明不再被报(self) -> None:
        对照 = self._对照组统计("夹具B2_默认值缺失_基线外", 篡改默认值缺失)
        self.assertEqual(0, 对照["新增漏声明数"], "去掉新判据后漏声明维度也不再判红")


class 真实仓库现状测试(unittest.TestCase):
    """真实仓库：新判据不得引入历史红（存量已被正确分桶）。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.统计结果 = 统计(系统根)

    def test_真实仓库无默认值必填硬不一致(self) -> None:
        self.assertEqual(0, self.统计结果["默认值硬不一致数"],
                         f"{self.统计结果['默认值硬不一致列表'][:3]}")
        self.assertEqual(0, self.统计结果["必填硬不一致数"],
                         f"{self.统计结果['必填硬不一致列表'][:3]}")

    def test_真实仓库基线内零新增(self) -> None:
        self.assertTrue(self.统计结果["基线"]["生效"])
        self.assertEqual(0, self.统计结果["新增漏声明数"],
                         f"基线外出现新增漏声明（必须先在源码改对，不得扩基线）："
                         f"{self.统计结果['新增漏声明列表'][:3]}")
        self.assertGreaterEqual(self.统计结果["存量漏声明数"], 200,
                                "存量漏声明应如实报出（只报不阻断），不得被基线清空")


class 发布门禁接线测试(unittest.TestCase):
    """门禁强制项：新增类不一致真阻断，仅存量不阻断。"""

    @classmethod
    def setUpClass(cls) -> None:
        from 开发工具.契约编译 import 漂移检测
        cls.漂移检测 = 漂移检测
        # staticmethod 包一层：函数赋给类属性会被当方法绑定，`self.原统计函数(根, ...)`
        # 会把 self 当第一个参数传进去（真错，不是类型噪音）。
        cls.原统计函数 = staticmethod(漂移检测.全仓注册口径统计)

    def _跑门禁(self, 根: Path) -> Any:
        """把夹具统计结果接进真实门禁路径，看那条检查真的红还是真的绿。

        统计结果本身由**真实检测器**扫**真实夹具树**算出（不伪造数字），
        这里只替换「门禁取统计」这一步接线，因为仓库里没有、也不允许有真不一致的包。
        """
        self.漂移检测.全仓注册口径统计 = (
            lambda *参数, **关键词: self.原统计函数(根, 基线文件=默认存量基线路径()))
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                结果 = 执行门禁(运行测试=假, 运行编译=假, 真实进程=假)
        finally:
            self.漂移检测.全仓注册口径统计 = self.原统计函数
        return 结果

    @staticmethod
    def _强制未通过项(结果) -> set[str]:
        return {项.名称 for 项 in 结果.门禁项列表
                if 项.强制 and not 项.通过 and 项.核验状态 != "未核验"}

    def test_新增漏声明夹具真阻断(self) -> None:
        结果 = self._跑门禁(建夹具("夹具B2_默认值缺失_基线外", 篡改默认值缺失))
        项 = next((项 for 项 in 结果.门禁项列表 if 项.名称 == 门禁新增项名), None)
        self.assertIsNotNone(项, f"门禁缺少强制项「{门禁新增项名}」")
        self.assertTrue(项.强制, "本项必须是强制项（不得是只报项）")
        self.assertEqual("已核验", 项.核验状态)
        self.assertFalse(项.通过, f"新增类不一致必须阻断；详情={项.详情[:200]}")
        self.assertIn("新增漏声明 1", 项.详情)
        self.assertEqual("失败", 结果.发布状态, 结果.汇总())

    def test_仅存量夹具不阻断只报(self) -> None:
        结果 = self._跑门禁(建夹具("夹具B1_默认值缺失_基线内"))
        项 = next((项 for 项 in 结果.门禁项列表 if 项.名称 == 门禁新增项名), None)
        self.assertIsNotNone(项)
        self.assertTrue(项.通过, f"基线内存量不得阻断；详情={项.详情[:200]}")
        self.assertIn("存量漏声明 2 条只报不阻断", 项.详情)
        self.assertNotIn(门禁新增项名, self._强制未通过项(结果),
                         "存量场景不得因本项红")
        # 红项对照：仅存量场景比新增场景**少且只少**本项（不得顺带制造无关新红）
        红_with_new = self._强制未通过项(
            self._跑门禁(建夹具("夹具B2_默认值缺失_基线外", 篡改默认值缺失)))
        红_存量 = self._强制未通过项(结果)
        self.assertEqual({门禁新增项名}, 红_with_new - 红_存量,
                         f"两场景红项差异应恰好只有本项：{红_with_new ^ 红_存量}")

    def test_门禁新项默认强制且未降级为只报(self) -> None:
        """源码级锁：该检查调用不得带 `强制=False`，且判据来源是 注册口径新增判据。"""
        树 = ast.parse(门禁模块路径.read_text(encoding="utf-8"), filename=str(门禁模块路径))
        命中 = []
        for 节点 in ast.walk(树):
            if not isinstance(节点, ast.Call) or not 节点.args:
                continue
            if getattr(节点.func, "id", "") != "检查":
                continue
            首参 = 节点.args[0]
            if isinstance(首参, ast.Constant) and 首参.value == 门禁新增项名:
                命中.append(节点)
        self.assertTrue(命中, f"门禁未接线「{门禁新增项名}」")
        for 节点 in 命中:
            降级 = [关键词 for 关键词 in 节点.keywords
                    if 关键词.arg == "强制"
                    and isinstance(关键词.value, ast.Constant)
                    and 关键词.value.value is 假]
            self.assertFalse(降级, "本项被降级成只报（强制=False），新增不一致将拦不住")
        源码 = 门禁模块路径.read_text(encoding="utf-8")
        self.assertIn("注册口径新增判据(口径统计)", 源码,
                      "门禁必须复用唯一判据函数，不得内联第二套判据")

    def test_判据函数只判新增类(self) -> None:
        """纯函数级锁：硬不一致/新增漏声明判红，存量只报不参与判定。"""
        def _统计(默认值硬: int, 必填硬: int, 新增: int, 存量: int) -> dict:
            return {"默认值硬不一致数": 默认值硬, "必填硬不一致数": 必填硬,
                    "新增漏声明数": 新增, "存量漏声明数": 存量,
                    "默认值硬不一致列表": [], "必填硬不一致列表": [], "新增漏声明列表": [],
                    "基线": {"生效": 真}}
        通过, 详情 = 注册口径新增判据(_统计(0, 0, 0, 221))
        self.assertTrue(通过, 详情)
        self.assertIn("存量漏声明 221 条只报不阻断", 详情)
        for 参数 in ((1, 0, 0), (0, 1, 0), (0, 0, 1)):
            通过, 详情 = 注册口径新增判据(_统计(*参数, 221))
            self.assertFalse(通过, f"新增类 {参数} 必须判不通过；详情={详情}")


if __name__ == "__main__":
    unittest.main()
