"""测试资源 模块定向测试：骨架（模板产出）+ 单能力定向冒烟（经 后端核心 真实装配）。

冒烟范围（不跑门禁、不跑全量）：
- 两个能力经 `后端核心` 装配后真实调用（真实文件删除、真实清单读写、真实进程句柄终止）；
- 安全边界真实拒绝：临时根越界、临时根=工程缓存自身、资源越界；
- 缺能力如实失败：端口/线程/句柄 回收留失败表 + 真实证据文件。
"""

from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.基础类型.结果类型 import 结果
from 模块库.测试资源 import 申请资源, 回收资源, 注册能力


class Test测试资源模块(unittest.TestCase):
    """装配冒烟：公开入口可导入、注册能力齐全、调用返回统一结果。"""

    def test_公开入口可导入(self):
        for 能力名 in ['申请资源', '回收资源']:
            self.assertTrue(callable(globals()[能力名]), f"{能力名} 未从公开入口导出")

    def test_注册能力齐全(self):
        from 公共契约.能力契约.契约 import 能力注册表
        注册表 = 能力注册表()
        注册能力(注册表)
        for 能力id in ['测试资源.申请资源', '测试资源.回收资源']:
            self.assertIn(能力id, 注册表.能力id列表)

    # ── 注册参数口径（2026-09-18 两拍缺陷的回归护盾）────────

    def test_注册参数逐条镜像契约JSON不丢必填默认值(self):
        """注册参数项必须逐字等于 能力契约/参数契约.json 的原值（含 必填/默认值）。

        这是「丢参」缺陷的正面判据：入口一旦只抽 名称+类型（第一拍形态）或改回
        函数内推导（第二拍形态），本用例即红。
        """
        import json

        from 公共契约.能力契约.契约 import 能力注册表 as 注册表类

        契约 = json.loads(
            (Path(__file__).resolve().parents[2]
             / "模块库" / "测试资源" / "能力契约" / "参数契约.json").read_text(encoding="utf-8"))
        契约参数表 = {条["能力id"]: [dict(参数) for 参数 in 条["参数"]]
                  for 条 in 契约["能力契约"]}
        注册表 = 注册表类()
        注册能力(注册表)
        for 能力id, 契约参数 in 契约参数表.items():
            在线实现 = 注册表.获取(能力id)
            self.assertIsNotNone(在线实现, f"{能力id} 未注册")
            assert 在线实现 is not None
            在线参数 = 在线实现.参数
            self.assertEqual([参数["名称"] for 参数 in 在线参数],
                             [参数["名称"] for 参数 in 契约参数],
                             f"{能力id} 注册参数名序与契约不一致")
            for 在线, 期望 in zip(在线参数, 契约参数):
                self.assertIn("必填", 在线, f"{能力id}.{期望['名称']} 注册项丢了 必填")
                self.assertIn("默认值", 在线, f"{能力id}.{期望['名称']} 注册项丢了 默认值")
                self.assertEqual(在线["必填"], 期望["必填"],
                                 f"{能力id}.{期望['名称']} 必填 与契约不一致")
                self.assertEqual(在线["默认值"], 期望["默认值"],
                                 f"{能力id}.{期望['名称']} 默认值 与契约不一致")
                # 契约没声明的键不得补（补出来的默认值就是第二套事实源）
                self.assertEqual(set(在线) - {"名称", "类型", "必填", "默认值"}, set(),
                                 f"{能力id}.{期望['名称']} 注册项多出契约未声明的键")

    def test_注册参数表在注册能力函数体内可静态解析(self):
        """`_参数契约表` 必须是 `注册能力` **函数体内的字面量**，且含 必填 键。

        为什么要有它：`开发工具/契约编译/漂移检测` 的 AST 读取器只收 `注册能力`
        函数体内的 `ast.List/ast.Dict` 字面量赋值。参数表一旦改成「函数内推导」
        （`_参数声明(能力id, …)`）或「运行时读 JSON」，本包两条能力的参数口径就
        全判「未解析」——门禁看不见 = 等于没有（判据是 AST 能否解出含 必填 的整条参数）。
        """
        import ast
        import inspect

        import 模块库.测试资源 as 模块入口

        树 = ast.parse(inspect.getsource(模块入口.注册能力))
        # 用与漂移检测同一支 AST 静态求值：解不出即判「不可静态判定」，本用例红。
        from 开发工具.契约编译.漂移检测 import _静态字面量, 常量种子绑定, 未解析哨兵

        函数体 = 树.body[0].body if isinstance(树.body[0], ast.FunctionDef) else 树.body
        # 种子绑定与生产读取器同源（`常量种子绑定` 从 `_常量导入源` 派生）：
        # 本用例只解析 注册能力 的**函数体**，模块级 import 不在这棵树里，
        # 不播种子则中文 `真`/`假` 会落「未解析」（与生产侧同一坑，勿各写一份）。
        绑定: dict = dict(常量种子绑定())
        for 节点 in 函数体:
            if isinstance(节点, ast.Assign) and isinstance(节点.targets[0], ast.Name):
                绑定[节点.targets[0].id] = 节点.value
        self.assertIn("_参数契约表", 绑定, "`_参数契约表` 未写在 注册能力 函数体内")
        # 2026-09-23 判据唯一化③：本包原先那份「镜像 vs 名序」同文件自比
        # （`_注册参数名序` + `_校验参数名序()`）已删除——两份输入同一次手写产生，
        # 一起写错即恒绿。名序/返回口径的唯一判据在装配期闸门
        # （`运行核心/加载器/生命周期管理/管理器.装配系统` → `能力注册表.校验声明一致`）。
        self.assertNotIn("_注册参数名序", 绑定,
                         "自比拷贝 `_注册参数名序` 已随判据唯一化删除，不得回潮")
        契约表 = _静态字面量(绑定["_参数契约表"], 绑定)
        self.assertIsNot(契约表, 未解析哨兵,
                         "_参数契约表 静态解析不出（AST 门禁看不见 → 参数口径判未解析）")
        assert isinstance(契约表, dict)
        self.assertEqual(sorted(契约表),
                         sorted(["测试资源.申请资源", "测试资源.回收资源"]))
        for 能力id, 参数列表 in 契约表.items():
            self.assertTrue(参数列表, f"{能力id} 参数表为空")
            self.assertTrue(all("必填" in 参数 for 参数 in 参数列表),
                            f"{能力id} 参数表有项不含 必填（AST 门禁读不到必填口径）")
            self.assertTrue(all("默认值" in 参数 for 参数 in 参数列表),
                            f"{能力id} 参数表有项不含 默认值")

    def test_网关按注册参数拦下缺必填参数(self):
        """真注册表 → 网关唯一校验点：缺必填即 400 文案，不落进实现体抛 TypeError。

        这是「500 改回 400」的回归护盾：注册项一旦丢 必填，网关 `项.get("必填") is 真`
        判假、必填校验静默失效，用户拿到的是 HTTP 500 而不是干净的 400。
        """
        from 公共契约.能力契约.契约 import 能力注册表 as 注册表类
        from 运行核心.统一网关.协议.类型规格 import 校验能力参数

        注册表 = 注册表类()
        注册能力(注册表)
        申请实现 = 注册表.获取("测试资源.申请资源")
        self.assertIsNotNone(申请实现)
        assert 申请实现 is not None
        self.assertTrue(校验能力参数("测试资源.申请资源", 申请实现.参数, {}).startswith(
            "参数不合法：能力 测试资源.申请资源 缺少必填参数 临时根目录"),
            "缺必填文案前缀变了（实现会追加「（本能力参数…）」清单，故只钉前缀，不钉全串）")
        self.assertTrue(校验能力参数("测试资源.申请资源", 申请实现.参数,
                                 {"临时根目录": "/tmp"},
                                 ).startswith(
            "参数不合法：能力 测试资源.申请资源 缺少必填参数 清单路径"),
            "缺必填文案前缀变了（实现会追加「（本能力参数…）」清单，故只钉前缀，不钉全串）")
        回收实现 = 注册表.获取("测试资源.回收资源")
        self.assertIsNotNone(回收实现)
        assert 回收实现 is not None
        self.assertTrue(校验能力参数("测试资源.回收资源", 回收实现.参数, {}).startswith(
            "参数不合法：能力 测试资源.回收资源 缺少必填参数 临时根目录"),
            "缺必填文案前缀变了（实现会追加「（本能力参数…）」清单，故只钉前缀，不钉全串）")
        全给 = 校验能力参数("测试资源.申请资源", 申请实现.参数, {
            "临时根目录": "/tmp", "清单路径": "/tmp/清单.jsonl", "资源路径": "/tmp/x.txt",
            "资源类型": "文件", "保留": False, "开工id": "", "句柄": 0})
        self.assertEqual(全给, "", f"参数齐全却被判不合法: {全给}")

    def test_申请资源_返回统一结果(self):
        返回值 = 申请资源("", "", "", "", False, "", 0)
        self.assertIsInstance(返回值, 结果)

    def test_回收资源_返回统一结果(self):
        返回值 = 回收资源("", "", "", "")
        self.assertIsInstance(返回值, 结果)


class Test测试资源定向冒烟(unittest.TestCase):
    """经 后端核心 装配后的真实调用冒烟（单能力定向，不起长期进程）。"""

    @classmethod
    def setUpClass(cls):
        from 后端核心.后端核心 import 后端核心
        cls.后端 = 后端核心()
        启动 = cls.后端.启动()
        if not 启动.成功:
            raise RuntimeError(f"后端核心装配失败：{启动.错误码} {启动.错误说明}")
        cls.工程缓存 = Path(cls.后端.系统根目录) / "工程缓存"
        cls.临时根 = cls.工程缓存 / "测试临时" / "测试资源定向冒烟"
        cls.临时根.mkdir(parents=True, exist_ok=True)
        cls.清单 = cls.临时根 / "冒烟清单.jsonl"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.临时根, ignore_errors=True)
        cls.后端.优雅关闭()

    def setUp(self):
        self.清单.unlink(missing_ok=True)
        证据 = self.临时根 / "清理失败.json"
        证据.unlink(missing_ok=True)

    def _调用(self, 能力id: str, 参数: dict) -> 结果:
        return self.后端.调用(能力id, 参数)

    def _新资源文件(self, 名称: str = "样本.txt") -> Path:
        文件 = self.临时根 / 名称
        文件.parent.mkdir(parents=True, exist_ok=True)
        文件.write_text("冒烟样本", encoding="utf-8")
        return 文件

    def test_01_装配后能力已注册且真实返回(self):
        self.assertIn("测试资源.申请资源", self.后端.注册表.能力id列表)
        self.assertIn("测试资源.回收资源", self.后端.注册表.能力id列表)
        文件 = self._新资源文件()
        登记 = self._调用("测试资源.申请资源", {
            "临时根目录": str(self.临时根), "清单路径": str(self.清单),
            "资源路径": str(文件), "资源类型": "文件", "开工id": "冒烟开工id",
        })
        self.assertTrue(登记.成功, 登记.错误说明)
        self.assertEqual(登记.值["类型"], "文件")
        self.assertEqual(登记.值["保留"], False)
        self.assertEqual(登记.值["work_id"], "冒烟开工id")
        记录 = json.loads(self.清单.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(记录["路径"], str(文件))
        self.assertEqual(记录["类型"], "文件")

    def test_02_回收资源_真实删除文件并删清单(self):
        文件 = self._新资源文件()
        self.assertTrue(self._调用("测试资源.申请资源", {
            "临时根目录": str(self.临时根), "清单路径": str(self.清单),
            "资源路径": str(文件),
        }).成功)
        self.assertTrue(文件.exists())
        回收 = self._调用("测试资源.回收资源", {
            "临时根目录": str(self.临时根), "清单路径": str(self.清单),
        })
        self.assertTrue(回收.成功, 回收.错误说明)
        self.assertEqual(回收.值["清理数"], 1)
        self.assertEqual(回收.值["保留数"], 0)
        self.assertEqual(回收.值["失败表"], [])
        self.assertFalse(文件.exists(), "文件必须被真实删除")
        self.assertFalse(self.清单.exists(), "清单必须被真实删除")

    def test_03_回收资源_目录与保留跳过(self):
        目录 = self.临时根 / "样本目录"
        (目录 / "内层").mkdir(parents=True, exist_ok=True)
        (目录 / "内层" / "深层.txt").write_text("深层", encoding="utf-8")
        保留文件 = self._新资源文件("保留.txt")
        for 路径, 保留 in ((目录, False), (保留文件, True)):
            self.assertTrue(self._调用("测试资源.申请资源", {
                "临时根目录": str(self.临时根), "清单路径": str(self.清单),
                "资源路径": str(路径), "资源类型": "目录" if 路径.is_dir() else "文件",
                "保留": 保留,
            }).成功)
        回收 = self._调用("测试资源.回收资源", {
            "临时根目录": str(self.临时根), "清单路径": str(self.清单),
        })
        self.assertTrue(回收.成功, 回收.错误说明)
        self.assertEqual(回收.值["清理数"], 1)
        self.assertEqual(回收.值["保留数"], 1)
        self.assertFalse(目录.exists())
        self.assertTrue(保留文件.exists(), "标记保留的资源不得被回收")

    def test_04_安全边界_临时根越界拒绝(self):
        文件 = self._新资源文件()
        越界 = self._调用("测试资源.申请资源", {
            "临时根目录": "/tmp", "清单路径": str(self.清单), "资源路径": str(文件),
        })
        self.assertFalse(越界.成功)
        self.assertEqual(越界.错误码, "临时根越界")
        self.assertFalse(self.清单.exists(), "越界请求不得写任何清单")

    def test_05_安全边界_临时根不能是工程缓存自身(self):
        self.assertIn("/工程缓存", str(self.工程缓存))
        结果值 = self._调用("测试资源.申请资源", {
            "临时根目录": str(self.工程缓存), "清单路径": str(self.清单),
            "资源路径": str(self.工程缓存 / "x.txt"),
        })
        self.assertFalse(结果值.成功)
        self.assertEqual(结果值.错误码, "临时根越界")

    def test_06_安全边界_资源越界拒绝(self):
        外部 = 系统根 / "README.md"
        self.assertTrue(外部.is_file())
        越界 = self._调用("测试资源.申请资源", {
            "临时根目录": str(self.临时根), "清单路径": str(self.清单),
            "资源路径": str(外部),
        })
        self.assertFalse(越界.成功)
        self.assertEqual(越界.错误码, "资源越界")
        self.assertFalse(self.清单.exists())

    def test_07_待补类型_回收如实失败并留证据(self):
        登记 = self._调用("测试资源.申请资源", {
            "临时根目录": str(self.临时根), "清单路径": str(self.清单),
            "资源路径": "端口:18080", "资源类型": "端口",
        })
        self.assertTrue(登记.成功, 登记.错误说明)
        self.assertEqual(登记.值["标识"], "18080")
        回收 = self._调用("测试资源.回收资源", {
            "临时根目录": str(self.临时根), "清单路径": str(self.清单),
        })
        self.assertFalse(回收.成功)
        self.assertEqual(回收.错误码, "资源清理失败")
        失败表 = 回收.详细信息.get("失败表") or []
        self.assertEqual(len(失败表), 1)
        self.assertIn("待补能力", 失败表[0]["原因"])
        证据 = self.临时根 / "清理失败.json"
        self.assertTrue(证据.is_file(), "失败必须留结构化证据")
        证据内容 = json.loads(证据.read_text(encoding="utf-8"))
        self.assertEqual(len(证据内容["失败"]), 1)
        self.assertEqual(证据内容["失败"][0]["类型"], "端口")

    def test_08_子进程_经受管句柄申请与回收(self):
        启动 = self._调用("系统核心支持库.进程管理.启动进程", {
            "命令": "/bin/sleep", "参数": ["30"],
        })
        self.assertTrue(启动.成功, 启动.错误说明)
        句柄 = 启动.值["句柄"]
        self.addCleanup(lambda: self._调用("系统核心支持库.进程管理.释放句柄", {"句柄": 句柄}))
        登记 = self._调用("测试资源.申请资源", {
            "临时根目录": str(self.临时根), "清单路径": str(self.清单),
            "资源路径": f"子进程:{句柄}", "资源类型": "子进程", "句柄": 句柄,
        })
        self.assertTrue(登记.成功, 登记.错误说明)
        self.assertEqual(登记.值["标识"], str(句柄))
        状态 = self._调用("系统核心支持库.进程管理.查询进程状态", {"句柄": 句柄})
        self.assertTrue(状态.成功 and 状态.值["运行中"], "被登记的子进程应在运行中")
        回收 = self._调用("测试资源.回收资源", {
            "临时根目录": str(self.临时根), "清单路径": str(self.清单),
        })
        self.assertTrue(回收.成功, 回收.错误说明)
        self.assertEqual(回收.值["清理数"], 1)
        释放后 = self._调用("系统核心支持库.进程管理.查询进程状态", {"句柄": 句柄})
        self.assertFalse(释放后.成功, "句柄应已随回收失效")
        self.assertEqual(释放后.错误码, "句柄失效")

    def test_09_子进程_无句柄登记被拒(self):
        被拒 = self._调用("测试资源.申请资源", {
            "临时根目录": str(self.临时根), "清单路径": str(self.清单),
            "资源路径": "子进程:123456", "资源类型": "子进程",
        })
        self.assertFalse(被拒.成功)
        self.assertEqual(被拒.错误码, "参数不合法")
        self.assertFalse(self.清单.exists())

    def test_10_边界与幂等_清单不存在与未知类型(self):
        回收 = self._调用("测试资源.回收资源", {
            "临时根目录": str(self.临时根), "清单路径": str(self.清单),
        })
        self.assertTrue(回收.成功, 回收.错误说明)
        self.assertEqual(回收.值["清理数"], 0)
        未知 = self._调用("测试资源.申请资源", {
            "临时根目录": str(self.临时根), "清单路径": str(self.清单),
            "资源路径": str(self.临时根 / "x.txt"), "资源类型": "未知类型",
        })
        self.assertFalse(未知.成功)
        self.assertEqual(未知.错误码, "参数不合法")
        空路径 = self._调用("测试资源.申请资源", {
            "临时根目录": str(self.临时根), "清单路径": str(self.清单), "资源路径": "",
        })
        self.assertFalse(空路径.成功)
        self.assertEqual(空路径.错误码, "参数不合法")


if __name__ == "__main__":
    unittest.main()
