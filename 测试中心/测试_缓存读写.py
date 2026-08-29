"""缓存读写定向测试：覆盖 验证缓存 的读取、写入、损坏容错与 阶段缓存可复用 判定语义。

引用 测试中心/运行测试.py 的 读取缓存/写入缓存/阶段缓存可复用。
所有缓存读写均使用临时目录隔离（tempfile.mkdtemp + tearDown 清理），
禁止触碰真实 工程缓存/验证缓存。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

系统根 = Path(__file__).resolve().parents[1]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

import 测试中心.运行测试 as 运行测试


def 构造缓存项(
    *,
    摘要: str = "源码摘要",
    成功: bool = True,
    测试数: int = 3,
    结构版本: str | None = None,
    环境摘要: str = "环境摘要",
    时间戳: float = 1000.0,
) -> dict:
    """构造一个完整的缓存项（未指定结构版本时使用当前缓存结构版本）。"""
    return 运行测试._补齐缓存证据({
        "摘要": 摘要,
        "成功": 成功,
        "测试数": 测试数,
        "结构版本": 结构版本 if 结构版本 is not None else 运行测试.缓存结构版本,
        "环境摘要": 环境摘要,
        "时间戳": 时间戳,
    })


class Test读取缓存(unittest.TestCase):
    """读取缓存：目录聚合读取、损坏容错、临时目录隔离。"""

    def setUp(self) -> None:
        self.临时目录 = Path(tempfile.mkdtemp(prefix="测试缓存读写-"))
        self.补丁 = patch.object(运行测试, "验证缓存目录", self.临时目录)
        self.补丁.start()
        self.addCleanup(self.补丁.stop)

    def tearDown(self) -> None:
        shutil.rmtree(self.临时目录, ignore_errors=True)

    def test_缓存目录不存在时读取返回空字典(self) -> None:
        临时空目录 = Path(tempfile.mkdtemp(prefix="测试缓存读写-空-"))
        try:
            with patch.object(运行测试, "验证缓存目录", 临时空目录):
                self.assertEqual(运行测试.读取缓存(), {})
        finally:
            shutil.rmtree(临时空目录, ignore_errors=True)

    def test_写入后能读回(self) -> None:
        缓存 = {"静态契约": 构造缓存项()}
        运行测试.写入缓存(缓存)
        self.assertEqual(运行测试.读取缓存(), 缓存)

    def test_损坏JSON文件读取时跳过且不抛异常(self) -> None:
        (self.临时目录 / "静态契约.json").write_text("{损坏的JSON", encoding="utf-8")
        self.assertEqual(运行测试.读取缓存(), {})

    def test_损坏JSON不影响其他阶段缓存读取(self) -> None:
        运行测试.写入缓存({"静态契约": 构造缓存项()})
        (self.临时目录 / "组件合规.json").write_text("{损坏的JSON", encoding="utf-8")
        缓存 = 运行测试.读取缓存()
        self.assertEqual(set(缓存), {"静态契约"})
        self.assertEqual(缓存["静态契约"]["测试数"], 3)


class Test写入缓存(unittest.TestCase):
    """写入缓存：按阶段独立文件、原子写无临时残留。"""

    def setUp(self) -> None:
        self.临时目录 = Path(tempfile.mkdtemp(prefix="测试缓存读写-"))
        self.补丁 = patch.object(运行测试, "验证缓存目录", self.临时目录)
        self.补丁.start()
        self.addCleanup(self.补丁.stop)

    def tearDown(self) -> None:
        shutil.rmtree(self.临时目录, ignore_errors=True)

    def test_按阶段生成独立缓存文件(self) -> None:
        运行测试.写入缓存({
            "静态契约": 构造缓存项(),
            "项目装配": 构造缓存项(摘要="装配摘要"),
        })
        阶段文件表 = sorted(路径.name for 路径 in self.临时目录.glob("*.json"))
        self.assertEqual(阶段文件表, ["静态契约.json", "项目装配.json"])

    def test_写入后无临时文件残留(self) -> None:
        运行测试.写入缓存({"静态契约": 构造缓存项()})
        残留表 = list(self.临时目录.glob("*.tmp"))
        self.assertEqual(残留表, [])

    def test_同阶段覆盖写入后读回最新内容(self) -> None:
        运行测试.写入缓存({"静态契约": 构造缓存项(测试数=3)})
        运行测试.写入缓存({"静态契约": 构造缓存项(测试数=9)})
        缓存 = 运行测试.读取缓存()
        self.assertEqual(缓存["静态契约"]["测试数"], 9)


class Test阶段缓存可复用(unittest.TestCase):
    """阶段缓存可复用 判定语义（纯逻辑，不触碰文件）。"""

    def test_有效缓存项对敏感与非敏感阶段均可复用(self) -> None:
        缓存项 = 构造缓存项()
        self.assertTrue(运行测试.阶段缓存可复用(
            "真实进程", 缓存项, "源码摘要", "环境摘要", 当前时间=1001,
        ))
        self.assertTrue(运行测试.阶段缓存可复用(
            "静态契约", 缓存项, "源码摘要", "环境摘要", 当前时间=1001,
        ))

    def test_摘要不匹配时不可复用(self) -> None:
        self.assertFalse(运行测试.阶段缓存可复用(
            "静态契约", 构造缓存项(), "新摘要", "环境摘要",
        ))

    def test_摘要缺失时不可复用(self) -> None:
        缓存项 = 构造缓存项()
        del 缓存项["摘要"]
        self.assertFalse(运行测试.阶段缓存可复用(
            "静态契约", 缓存项, "源码摘要", "环境摘要",
        ))

    def test_成功缺失或为假时不可复用(self) -> None:
        缺成功 = 构造缓存项()
        del 缺成功["成功"]
        self.assertFalse(运行测试.阶段缓存可复用(
            "静态契约", 缺成功, "源码摘要", "环境摘要",
        ))
        self.assertFalse(运行测试.阶段缓存可复用(
            "静态契约", 构造缓存项(成功=False), "源码摘要", "环境摘要",
        ))

    def test_测试数缺失或为零时不可复用(self) -> None:
        缺测试数 = 构造缓存项()
        del 缺测试数["测试数"]
        self.assertFalse(运行测试.阶段缓存可复用(
            "静态契约", 缺测试数, "源码摘要", "环境摘要",
        ))
        self.assertFalse(运行测试.阶段缓存可复用(
            "静态契约", 构造缓存项(测试数=0), "源码摘要", "环境摘要",
        ))

    def test_结构版本缺失或不符时不可复用(self) -> None:
        缺版本 = 构造缓存项()
        del 缺版本["结构版本"]
        self.assertFalse(运行测试.阶段缓存可复用(
            "静态契约", 缺版本, "源码摘要", "环境摘要",
        ))
        self.assertFalse(运行测试.阶段缓存可复用(
            "静态契约", 构造缓存项(结构版本="9.9.9"), "源码摘要", "环境摘要",
        ))

    def test_环境摘要变化时敏感阶段不可复用(self) -> None:
        self.assertFalse(运行测试.阶段缓存可复用(
            "真实进程", 构造缓存项(), "源码摘要", "变化后的环境", 当前时间=1001,
        ))

    def test_环境摘要变化时非敏感阶段也不可复用(self) -> None:
        """修复后语义：环境摘要对所有阶段生效，非敏感阶段同样校验。"""
        self.assertFalse(运行测试.阶段缓存可复用(
            "静态契约", 构造缓存项(), "源码摘要", "变化后的环境", 当前时间=1001,
        ))

    def test_环境摘要缺失时不可复用(self) -> None:
        """环境摘要是必要证据，缺失时不能复用旧缓存。"""
        缓存项 = 构造缓存项()
        del 缓存项["环境摘要"]
        self.assertFalse(运行测试.阶段缓存可复用(
            "静态契约", 缓存项, "源码摘要", "任意环境", 当前时间=1001,
        ))

    def test_敏感阶段时间戳过期时不可复用(self) -> None:
        过期时间 = 1000 + 运行测试.运行证据有效秒 + 1
        self.assertFalse(运行测试.阶段缓存可复用(
            "真实进程", 构造缓存项(), "源码摘要", "环境摘要",
            当前时间=过期时间,
        ))

    def test_慢速层强制慢速时不可复用(self) -> None:
        self.assertFalse(运行测试.阶段缓存可复用(
            "慢速层", 构造缓存项(), "源码摘要", "环境摘要",
            强制慢速=True, 当前时间=1001,
        ))

    def test_缓存项为空时不可复用(self) -> None:
        self.assertFalse(运行测试.阶段缓存可复用(
            "静态契约", None, "源码摘要", "环境摘要",
        ))
        self.assertFalse(运行测试.阶段缓存可复用(
            "静态契约", {}, "源码摘要", "环境摘要",
        ))

    def test_可编辑字段伪造的缓存必须拒绝(self) -> None:
        """仅填成功/测试数/摘要的旧式缓存不能冒充真实执行证据。"""
        伪造 = {
            "摘要": "源码摘要", "成功": True, "测试数": 999999,
            "结构版本": 运行测试.缓存结构版本, "环境摘要": "环境摘要",
        }
        self.assertFalse(运行测试.阶段缓存可复用(
            "静态契约", 伪造, "源码摘要", "环境摘要",
        ))


class Test摘要git指纹复用(unittest.TestCase):
    """_文件摘要/_目录摘要 的 git 指纹复用：干净文件免读盘，dirty/untracked 现场哈希。"""

    def setUp(self) -> None:
        运行测试._构建git指纹映射()

    def test_干净文件摘要稳定(self) -> None:
        """干净已跟踪文件连续两次调用摘要一致。"""
        干净文件 = 系统根 / ".gitignore"
        相对路径 = 运行测试._仓库根相对路径(干净文件)
        self.assertIn(相对路径, 运行测试._git指纹映射)
        self.assertNotIn(相对路径, 运行测试._git脏文件集合)
        self.assertEqual(运行测试._文件摘要(干净文件), 运行测试._文件摘要(干净文件))

    def test_干净文件摘要使用现场内容哈希(self) -> None:
        """即使文件干净也使用现场内容，避免并行修改期间复用陈旧 Git 快照。"""
        干净文件 = 系统根 / ".gitignore"
        期望 = hashlib.sha256(干净文件.read_bytes()).hexdigest()[:16]
        self.assertEqual(运行测试._文件摘要(干净文件), 期望)

    def test_dirty文件摘要随内容变化(self) -> None:
        """dirty（已跟踪但工作区修改）走现场哈希：内容变化 → 摘要变化。"""
        临时文件 = 系统根 / "工程缓存" / f"测试dirty临时_{uuid.uuid4().hex}.txt"
        临时文件.parent.mkdir(parents=True, exist_ok=True)
        self.addCleanup(临时文件.unlink, missing_ok=True)
        临时文件.write_text("第一版内容", encoding="utf-8")
        相对路径 = 运行测试._仓库根相对路径(临时文件)
        with patch.object(运行测试, "_git指纹映射", {相对路径: "0" * 40}), \
                patch.object(运行测试, "_git脏文件集合", {相对路径}):
            摘要1 = 运行测试._文件摘要(临时文件)
            临时文件.write_text("第二版内容", encoding="utf-8")
            摘要2 = 运行测试._文件摘要(临时文件)
        self.assertEqual(摘要1, hashlib.sha256("第一版内容".encode("utf-8")).hexdigest()[:16])
        self.assertNotEqual(摘要1, 摘要2)

    def test_untracked文件摘要与现场哈希一致(self) -> None:
        """仓库内未跟踪文件走现场 sha256。"""
        临时文件 = 系统根 / "工程缓存" / f"测试untracked临时_{uuid.uuid4().hex}.txt"
        临时文件.parent.mkdir(parents=True, exist_ok=True)
        self.addCleanup(临时文件.unlink, missing_ok=True)
        临时文件.write_text("未跟踪内容", encoding="utf-8")
        现场 = hashlib.sha256(临时文件.read_bytes()).hexdigest()[:16]
        self.assertEqual(运行测试._文件摘要(临时文件), 现场)

    def test_仓库外文件现场哈希(self) -> None:
        """仓库根之外的文件同样走现场 sha256。"""
        临时目录 = Path(tempfile.mkdtemp(prefix="测试摘要仓库外-"))
        self.addCleanup(shutil.rmtree, 临时目录, ignore_errors=True)
        临时文件 = 临时目录 / "外部.txt"
        临时文件.write_text("仓库外内容", encoding="utf-8")
        现场 = hashlib.sha256(临时文件.read_bytes()).hexdigest()[:16]
        self.assertEqual(运行测试._文件摘要(临时文件), 现场)

    def test_摘要统一为16位hex(self) -> None:
        """git 指纹与 sha256 现场摘要同长度（16 位 hex）。"""
        干净摘要 = 运行测试._文件摘要(系统根 / ".gitignore")
        临时文件 = 系统根 / "工程缓存" / f"测试长度临时_{uuid.uuid4().hex}.txt"
        临时文件.parent.mkdir(parents=True, exist_ok=True)
        self.addCleanup(临时文件.unlink, missing_ok=True)
        临时文件.write_text("长度测试", encoding="utf-8")
        现场摘要 = 运行测试._文件摘要(临时文件)
        for 摘要 in (干净摘要, 现场摘要):
            self.assertEqual(len(摘要), 16)
            int(摘要, 16)

    def test_目录摘要感知新增untracked文件(self) -> None:
        """防假绿：目录摘要保留 rglob 枚举，新增未跟踪文件必须改变摘要。"""
        临时目录 = 系统根 / f"_摘要测试临时_{uuid.uuid4().hex}"
        临时目录.mkdir()
        self.addCleanup(shutil.rmtree, 临时目录, ignore_errors=True)
        摘要空 = 运行测试._目录摘要(临时目录)
        (临时目录 / "新增文件.py").write_text("新增未跟踪文件", encoding="utf-8")
        摘要非空 = 运行测试._目录摘要(临时目录)
        self.assertNotEqual(摘要空, 摘要非空)


class Test文件级缓存(unittest.TestCase):
    """文件级缓存：复用判定、依赖变化失效、目录变化失效、弱依赖过期。"""

    def setUp(self) -> None:
        self.临时根 = 系统根 / f"_文件级缓存测试_{uuid.uuid4().hex}"
        self.临时根.mkdir()
        self.依赖根 = self.临时根 / "依赖"
        self.依赖根.mkdir()
        self.测试文件 = self.依赖根 / "测试_示例.py"
        self.测试文件.write_text("import unittest\n", encoding="utf-8")
        self.依赖文件 = self.依赖根 / "源.py"
        self.依赖文件.write_text("值 = 1\n", encoding="utf-8")
        self.依赖目录 = self.依赖根 / "数据目录"
        self.依赖目录.mkdir()
        (self.依赖目录 / "a.txt").write_text("a", encoding="utf-8")
        self.缓存目录 = self.临时根 / "缓存"
        self.缓存目录.mkdir()
        self.环境摘要 = "环境摘要测试"
        self.补丁 = patch.object(运行测试, "验证文件缓存目录", self.缓存目录)
        self.补丁.start()
        self.addCleanup(self.补丁.stop)
        self.addCleanup(shutil.rmtree, self.临时根, ignore_errors=True)

    def 写入缓存(self, *, 含目录: bool = True) -> None:
        缓存项 = 运行测试._补齐缓存证据({
            "成功": True,
            "测试数": 2,
            "测试文件摘要": 运行测试.文件级摘要(self.测试文件),
            "环境摘要": self.环境摘要,
            "结构版本": 运行测试.缓存结构版本,
            "依赖摘要表": {
                str(self.依赖文件.relative_to(系统根)): 运行测试._文件摘要(self.依赖文件),
            },
            "目录摘要表": (
                {str(self.依赖目录.relative_to(系统根)): 运行测试._目录清单摘要(self.依赖目录)}
                if 含目录 else {}
            ),
            "弱依赖标记": False,
            "时间戳": time.time(),
        })
        运行测试.写入文件级缓存(self.测试文件, 缓存项)

    def test_命中条件全部满足时复用(self) -> None:
        self.写入缓存()
        缓存项 = 运行测试.读取文件级缓存(self.测试文件)
        self.assertTrue(运行测试.文件级缓存可复用(self.测试文件, 缓存项, self.环境摘要))

    def test_依赖文件内容变化时失效(self) -> None:
        """假绿防护：依赖源文件内容变化必须使缓存失效。"""
        self.写入缓存()
        self.依赖文件.write_text("值 = 2\n", encoding="utf-8")
        缓存项 = 运行测试.读取文件级缓存(self.测试文件)
        self.assertFalse(运行测试.文件级缓存可复用(self.测试文件, 缓存项, self.环境摘要))

    def test_依赖文件缺失时失效(self) -> None:
        self.写入缓存()
        self.依赖文件.unlink()
        缓存项 = 运行测试.读取文件级缓存(self.测试文件)
        self.assertFalse(运行测试.文件级缓存可复用(self.测试文件, 缓存项, self.环境摘要))

    def test_目录内容新增文件时失效(self) -> None:
        """假绿防护：扫描目录新增文件必须使缓存失效（目录扫描型测试）。"""
        self.写入缓存()
        (self.依赖目录 / "b.txt").write_text("b", encoding="utf-8")
        缓存项 = 运行测试.读取文件级缓存(self.测试文件)
        self.assertFalse(运行测试.文件级缓存可复用(self.测试文件, 缓存项, self.环境摘要))

    def test_目录缺失时失效(self) -> None:
        self.写入缓存()
        shutil.rmtree(self.依赖目录)
        缓存项 = 运行测试.读取文件级缓存(self.测试文件)
        self.assertFalse(运行测试.文件级缓存可复用(self.测试文件, 缓存项, self.环境摘要))

    def test_无目录摘要表的旧缓存项仍可复用(self) -> None:
        """向后兼容：目录摘要表缺失（旧缓存项）不阻断复用，文件级校验仍生效。"""
        self.写入缓存(含目录=False)
        缓存项 = 运行测试.读取文件级缓存(self.测试文件)
        self.assertTrue(运行测试.文件级缓存可复用(self.测试文件, 缓存项, self.环境摘要))

    def test_弱依赖标记超过有效期后失效(self) -> None:
        缓存项 = {
            "成功": True,
            "测试数": 2,
            "测试文件摘要": 运行测试.文件级摘要(self.测试文件),
            "环境摘要": self.环境摘要,
            "结构版本": 运行测试.缓存结构版本,
            "依赖摘要表": {},
            "目录摘要表": {},
            "弱依赖标记": True,
            "时间戳": time.time() - 运行测试.弱依赖缓存有效秒 - 10,
        }
        运行测试.写入文件级缓存(self.测试文件, 缓存项)
        缓存项 = 运行测试.读取文件级缓存(self.测试文件)
        self.assertFalse(运行测试.文件级缓存可复用(self.测试文件, 缓存项, self.环境摘要))


if __name__ == "__main__":
    unittest.main()
