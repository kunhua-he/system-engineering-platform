"""环境缓存远程镜像测试：契约/校验器/伪造攻击/回退语义/可选接入。

覆盖：
- 契约：配置结构（启用开关/镜像地址/信任指纹/发布者公钥）、制品摘要=
  环境目录摘要、匹配条件=制品摘要+依赖锁+Python版本+系统版本+架构 全部一致。
- 校验器：公钥签名验证 + 信任指纹双保险 + 五条件全部匹配才允许命中；
  签名无效（镜像签名无效）/伪造镜像（摘要不匹配/锁不匹配/版本不符/
  系统版本不符/架构不符/指纹不符/清单不完整）→ 拒绝。
- 回退语义：镜像不可用/镜像签名无效/镜像摘要不匹配/镜像下载失败 →
  明确回退本地构建，不得把失败伪装成缓存命中。
- 默认关闭：未启用时完全走现有本地缓存路径（行为零变化）。
- 端到端：file:// 临时测试镜像（隔离地址，不接触业务数据库/生产制品）。
- 密钥角色边界：测试内生成临时密钥对（发布角色语义），运行核心只验证。
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 支持库.适配层.密码签名提供者 import 生成密钥对
from 运行核心.运行环境管理器.环境管理器 import (
    计算环境摘要, 确保环境, 环境目录, 读取依赖锁,
)
from 运行核心.运行环境管理器.远程镜像 import (
    计算制品摘要, 镜像不可用, 镜像下载失败, 镜像校验请求, 镜像摘要不匹配,
    镜像签名无效, 签名清单, 读取远程镜像配置, 下载镜像制品, 获取镜像清单,
    远程镜像校验器, 远程镜像配置,
)
from 公共契约.诊断.忽略记录 import 记录忽略
from 公共契约.基础类型.逻辑类型 import 真, 假
from 测试中心.运行核心.环境夹具 import 注入假venv, 钉住运行缓存根

受管仓库根 = Path(__file__).resolve().parents[2]
from 公共契约.运行时.平台适配 import 清只读后删除树

#: ★ A 档泄漏收口（2026-09-23）：受管临时根在仓库内**固定排除目录** `工程缓存/` 下。
#: `dir=` 显式指向它 ⇒ 落点与**测试运行时**的 `TMPDIR` 解耦（平台跑测试时 `TMPDIR` 被指进
#: 仓库工作目录，裸 `mkdtemp()` 会把夹具造进仓库）。`工程缓存` 在
#: `开发工具/项目编译/工作区指纹.py` 的 `固定排除目录` 里 ⇒ 即便进程被 SIGKILL、
#: 清理没跑到，残留也进不了工作区指纹（`.gitignore` 保不住：指纹的未跟踪腿不用
#: `--exclude-standard`）。清理走平台唯一删树原语 `清只读后删除树`（本类用例常造
#: `0o555` 目录 / `0o444` 文件，plain `shutil.rmtree` 会被权限位挡住）。
受管临时根 = 受管仓库根 / "工程缓存" / "测试临时"
受管临时根.mkdir(parents=True, exist_ok=True)

测试指纹 = "测试信任指纹-7f3a"


def 生成测试密钥对() -> tuple[str, str]:
    """测试内生成临时 Ed25519 密钥对（发布角色语义，运行核心不持私钥）。"""
    结果 = 生成密钥对()
    assert 结果.成功, 结果.错误说明
    return 结果.值["私钥PEM"], 结果.值["公钥PEM"]


def 样例锁(版本: str = "1.2.0") -> dict:
    return {"包": [{"名称": "python-docx", "版本": 版本, "模块名": "docx"}]}


def 锁文件摘要(锁文件: Path) -> str:
    return hashlib.sha256(锁文件.read_bytes()).hexdigest()[:16]


class Test远程镜像契约(unittest.TestCase):
    """镜像契约：配置结构与默认关闭。"""

    def setUp(self):
        self.临时 = Path(tempfile.mkdtemp(dir=受管临时根))
        self.addCleanup(清只读后删除树, self.临时, 忽略失败=真)
        # ★ 运行缓存根钉到本用例临时根（见 环境夹具.钉住运行缓存根）：网关进程设的
        # `系统底座_工程缓存根`/`系统底座_提供者环境根` 会把缓存根改指真仓库。
        self.addCleanup(钉住运行缓存根(self.临时 / "工程缓存"))

    def test_默认配置关闭(self):
        """无配置文件 → 启用=False（默认关闭，行为零变化）。"""
        配置 = 读取远程镜像配置()
        self.assertFalse(配置.启用)
        self.assertEqual(配置.镜像地址, "")
        self.assertEqual(配置.信任指纹, "")

    def test_配置文件读取启用(self):
        """配置文件 {启用/镜像地址/信任指纹/公钥PEM} 正确解析。"""
        配置路径 = self.临时 / "远程镜像配置.json"
        配置路径.write_text(json.dumps({
            "启用": 真, "镜像地址": "http://镜像.example.com/环境制品",
            "信任指纹": "sha256-abc123", "公钥PEM": "-----BEGIN PUBLIC KEY-----\n测试",
        }, ensure_ascii=False), encoding="utf-8")
        配置 = 读取远程镜像配置(配置路径)
        self.assertTrue(配置.启用)
        self.assertEqual(配置.镜像地址, "http://镜像.example.com/环境制品")
        self.assertEqual(配置.信任指纹, "sha256-abc123")
        self.assertEqual(配置.公钥PEM, "-----BEGIN PUBLIC KEY-----\n测试")

    def test_配置文件损坏回退默认关闭(self):
        """无效 JSON/缺字段 → 默认关闭（安全失败）。"""
        配置路径 = self.临时 / "远程镜像配置.json"
        配置路径.write_text("不是json{", encoding="utf-8")
        配置 = 读取远程镜像配置(配置路径)
        self.assertFalse(配置.启用)
        # 缺 启用 字段但有关键字段 → 仍默认关闭
        配置路径.write_text(json.dumps({"镜像地址": "http://x"}),
                            encoding="utf-8")
        配置二 = 读取远程镜像配置(配置路径)
        self.assertFalse(配置二.启用)
        self.assertEqual(配置二.镜像地址, "http://x")

    def test_制品摘要为环境目录稳定摘要(self):
        """制品摘要=环境目录摘要；排除 __pycache__/.pyc 保持稳定。"""
        环境体 = self.临时 / "环境体"
        (环境体 / "bin").mkdir(parents=True)
        (环境体 / "bin" / "python3").write_text("#!/bin/sh\nexit 0\n")
        (环境体 / "site-packages").mkdir()
        (环境体 / "site-packages" / "docx.py").write_text("x=1\n")
        摘要一 = 计算制品摘要(环境体)
        # 新增易变文件（.pyc/__pycache__）不得改变摘要
        (环境体 / "site-packages" / "docx.cpython-314.pyc").write_text("pyc")
        (环境体 / "site-packages" / "__pycache__").mkdir()
        (环境体 / "site-packages" / "__pycache__" / "temp.pyc").write_text("t")
        摘要二 = 计算制品摘要(环境体)
        self.assertEqual(摘要一, 摘要二)
        # 真实内容变化必须改变摘要
        (环境体 / "site-packages" / "docx.py").write_text("x=2\n")
        摘要三 = 计算制品摘要(环境体)
        self.assertNotEqual(摘要一, 摘要三)
        self.assertEqual(len(摘要一), 16)


class Test远程镜像校验器(unittest.TestCase):
    """校验器：公钥签名 + 信任指纹双保险 + 五条件匹配才允许命中。"""

    def setUp(self):
        self.请求 = 镜像校验请求(
            依赖锁摘要="锁摘要-1111",
            python版本="3.14.0",
            系统版本="测试系统 26.1",
            架构="arm64",
        )
        self.私钥PEM, self.公钥PEM = 生成测试密钥对()
        self.清单 = self.签名清单()

    def 签名清单(self, **覆盖: str) -> dict:
        """发布侧模拟：组装清单并用测试私钥签名（签名正文=稳定序列化）。"""
        清单 = {
            "制品摘要": "制品摘要-aaaa",
            "依赖锁摘要": "锁摘要-1111",
            "python版本": "3.14.0",
            "系统版本": "测试系统 26.1",
            "架构": "arm64",
            "信任指纹": 测试指纹,
            **覆盖,
        }
        签名结果 = 签名清单(清单, self.私钥PEM)
        self.assertTrue(签名结果.成功, 签名结果.错误说明)
        return 签名结果.值

    def test_全部匹配允许命中(self):
        结果 = 远程镜像校验器(self.请求, self.清单, 测试指纹,
                               公钥PEM=self.公钥PEM)
        self.assertTrue(结果.允许命中)
        self.assertEqual(结果.制品摘要, "制品摘要-aaaa")

    def test_签名被篡改拒绝(self):
        """签名值被改（签名与正文不符）→ 拒绝（镜像签名无效）。"""
        篡改清单 = dict(self.清单)
        篡改清单["签名"] = "00" * 128
        结果 = 远程镜像校验器(self.请求, 篡改清单, 测试指纹,
                               公钥PEM=self.公钥PEM)
        self.assertFalse(结果.允许命中)
        self.assertEqual(结果.错误码, 镜像签名无效)

    def test_公钥被替换拒绝(self):
        """配置公钥与签名私钥不配对 → 拒绝（镜像签名无效）。"""
        他人公钥 = 生成测试密钥对()[1]
        结果 = 远程镜像校验器(self.请求, self.清单, 测试指纹,
                               公钥PEM=他人公钥)
        self.assertFalse(结果.允许命中)
        self.assertEqual(结果.错误码, 镜像签名无效)

    def test_伪造镜像摘要不匹配拒绝(self):
        """签名有效但下载内容与声明不符 → 拒绝（镜像摘要不匹配）。"""
        结果 = 远程镜像校验器(self.请求, self.清单, 测试指纹,
                                公钥PEM=self.公钥PEM,
                                实际制品摘要="伪造制品摘要-ffff")
        self.assertFalse(结果.允许命中)
        self.assertEqual(结果.错误码, 镜像摘要不匹配)
        self.assertIn("制品摘要不匹配", 结果.错误说明)

    def test_伪造镜像依赖锁不匹配拒绝(self):
        """发布者合法签名但依赖锁摘要与本地期望不符 → 拒绝。"""
        伪造清单 = self.签名清单(依赖锁摘要="伪造锁摘要-ffff")
        结果 = 远程镜像校验器(self.请求, 伪造清单, 测试指纹,
                               公钥PEM=self.公钥PEM)
        self.assertFalse(结果.允许命中)
        self.assertEqual(结果.错误码, 镜像摘要不匹配)
        self.assertIn("依赖锁不匹配", 结果.错误说明)

    def test_伪造镜像Python版本不符拒绝(self):
        伪造清单 = self.签名清单(python版本="3.9.0")
        结果 = 远程镜像校验器(self.请求, 伪造清单, 测试指纹,
                               公钥PEM=self.公钥PEM)
        self.assertFalse(结果.允许命中)
        self.assertEqual(结果.错误码, 镜像摘要不匹配)
        self.assertIn("Python版本不匹配", 结果.错误说明)

    def test_伪造镜像系统版本不符拒绝(self):
        伪造清单 = self.签名清单(系统版本="伪造系统 1.0")
        结果 = 远程镜像校验器(self.请求, 伪造清单, 测试指纹,
                               公钥PEM=self.公钥PEM)
        self.assertFalse(结果.允许命中)
        self.assertEqual(结果.错误码, 镜像摘要不匹配)
        self.assertIn("系统版本不匹配", 结果.错误说明)

    def test_伪造镜像架构不符拒绝(self):
        伪造清单 = self.签名清单(架构="x86_64")
        结果 = 远程镜像校验器(self.请求, 伪造清单, 测试指纹,
                               公钥PEM=self.公钥PEM)
        self.assertFalse(结果.允许命中)
        self.assertEqual(结果.错误码, 镜像摘要不匹配)
        self.assertIn("架构不匹配", 结果.错误说明)

    def test_信任指纹不符拒绝(self):
        """签名有效但配置指纹与镜像声明不一致 → 拒绝（双保险仍生效）。"""
        结果 = 远程镜像校验器(self.请求, self.清单, "伪造指纹-ffff",
                               公钥PEM=self.公钥PEM)
        self.assertFalse(结果.允许命中)
        self.assertEqual(结果.错误码, 镜像摘要不匹配)
        self.assertIn("信任指纹不匹配", 结果.错误说明)

    def test_清单不完整拒绝(self):
        """缺失任一匹配字段 → 拒绝（不静默放行）。"""
        缺失架构 = {**self.清单}
        缺失架构.pop("架构")
        结果 = 远程镜像校验器(self.请求, 缺失架构, 测试指纹,
                               公钥PEM=self.公钥PEM)
        self.assertFalse(结果.允许命中)
        self.assertEqual(结果.错误码, 镜像摘要不匹配)
        self.assertIn("架构", 结果.错误说明)
        空清单 = {}
        结果二 = 远程镜像校验器(self.请求, 空清单, 测试指纹,
                                 公钥PEM=self.公钥PEM)
        self.assertFalse(结果二.允许命中)
        self.assertEqual(结果二.错误码, 镜像摘要不匹配)

    def test_签名缺失拒绝(self):
        """无签名字段（信任指纹不能作为唯一依据）→ 拒绝（镜像签名无效）。"""
        无签名清单 = {
            "制品摘要": "制品摘要-aaaa",
            "依赖锁摘要": "锁摘要-1111",
            "python版本": "3.14.0",
            "系统版本": "测试系统 26.1",
            "架构": "arm64",
            "信任指纹": 测试指纹,
        }
        结果 = 远程镜像校验器(self.请求, 无签名清单, 测试指纹,
                               公钥PEM=self.公钥PEM)
        self.assertFalse(结果.允许命中)
        self.assertEqual(结果.错误码, 镜像签名无效)

    def test_伪造镜像全条件不符拒绝(self):
        """综合伪造攻击：锁/版本/系统/架构/指纹全错（合法签名）→ 拒绝。"""
        伪造清单 = self.签名清单(
            制品摘要="伪造-aaaa",
            依赖锁摘要="伪造锁",
            python版本="2.7",
            系统版本="伪造系统",
            架构="sparc",
            信任指纹="伪造指纹",
        )
        结果 = 远程镜像校验器(self.请求, 伪造清单, 测试指纹,
                               公钥PEM=self.公钥PEM)
        self.assertFalse(结果.允许命中)
        self.assertEqual(结果.错误码, 镜像摘要不匹配)
        self.assertNotEqual(结果.制品摘要, "伪造-aaaa")


class Test远程镜像接入(unittest.TestCase):
    """可选接入：默认关闭零变化；启用后命中/回退语义端到端（file:// 隔离地址）。"""

    @classmethod
    def setUpClass(cls):
        cls.私钥PEM, cls.公钥PEM = 生成测试密钥对()

    def setUp(self):
        self.临时 = Path(tempfile.mkdtemp(dir=受管临时根))
        self.addCleanup(清只读后删除树, self.临时, 忽略失败=真)
        # ★ 运行缓存根钉到本用例临时根（见 环境夹具.钉住运行缓存根）：不钉的话，
        # 网关进程设的两个变量会把 证据/环境目录/镜像配置 全改指真仓库 ⇒ 用例恒红。
        self.addCleanup(钉住运行缓存根(self.临时 / "工程缓存"))
        (self.临时 / "支持库").mkdir()
        (self.临时 / "模块库").mkdir()
        self.配置路径 = self.临时 / "工程缓存" / "远程镜像配置.json"

    def 新提供者(self, 名称: str = "docx提供者", 锁: dict | None = None) -> Path:
        目录 = self.临时 / 名称
        目录.mkdir()
        if 锁 is not None:
            (目录 / "依赖锁.json").write_text(
                json.dumps(锁, ensure_ascii=False), encoding="utf-8")
        return 目录

    def 证据行(self) -> list[dict]:
        证据文件 = self.临时 / "工程缓存" / "提供者运行环境" / "缓存证据.jsonl"
        if not 证据文件.is_file():
            return []
        return [json.loads(行) for 行 in
                证据文件.read_text(encoding="utf-8").splitlines() if 行.strip()]

    def 注入构建(self, **参数):
        """经生产自带注入口注入假 venv（第三方边界）；真构建/真校验全照跑。

        替换旧的 `mock.patch(…环境管理器.校验环境)` + `mock.patch(…环境管理器._构建环境)`：
        那两处把被测逻辑整段换掉（`测试伪装门禁` 规则1 P1），断言对象是夹具本身。
        注入后构建次数由**第三方边界实测**（`假venv.调用次数`）给出。见
        `测试中心/运行核心/环境夹具.py`。
        """
        return 注入假venv(**参数)

    def 写镜像配置(self, 镜像地址: str, 启用: bool = 真) -> 远程镜像配置:
        self.配置路径.parent.mkdir(parents=True, exist_ok=True)
        self.配置路径.write_text(json.dumps({
            "启用": 启用, "镜像地址": 镜像地址, "信任指纹": 测试指纹,
            "公钥PEM": self.公钥PEM,
        }, ensure_ascii=False), encoding="utf-8")
        return 远程镜像配置(启用=启用, 镜像地址=镜像地址,
                            信任指纹=测试指纹, 公钥PEM=self.公钥PEM)

    def 构造镜像制品(self, 提供者: Path, 摘要: str, *,
                      锁摘要覆盖: str | None = None,
                      不打包制品: bool = 假,
                      签名后篡改: bool = 假,
                      解释器失败: bool = 假) -> str:
        """在临时目录构造 file:// 临时测试镜像（隔离地址，发布侧签名）。

        镜像结构：镜像仓库/<提供者id>/<摘要>/镜像清单.json + 制品.tar.gz。
        清单由测试私钥（发布角色语义）签名；返回 file:// 镜像地址。

        `解释器失败=真`：镜像里的解释器骨架写成**退出码 1** —— 于是「镜像环境
        本地复校验」由**真实子进程**判失败（不再 `mock.patch(…校验环境, return_value=假)`），
        而本地构建注入的假 venv 仍落退出码 0 的解释器 → 回退构建成功。
        """
        仓库 = self.临时 / "镜像仓库"
        镜像项目录 = 仓库 / 提供者.name / 摘要
        环境体 = 镜像项目录 / "环境体"
        (环境体 / "bin").mkdir(parents=True)
        解释器脚本 = "#!/bin/sh\nexit 1\n" if 解释器失败 else "#!/bin/sh\nexit 0\n"
        (环境体 / "bin" / "python3").write_text(解释器脚本, encoding="utf-8")
        (环境体 / "bin" / "python3").chmod(0o755)
        (环境体 / "site-packages").mkdir()
        (环境体 / "site-packages" / "docx.py").write_text("ok=1\n", encoding="utf-8")
        if not 不打包制品:
            with tarfile.open(镜像项目录 / "制品.tar.gz", "w:gz") as 压缩包:
                压缩包.add(环境体, arcname=".")
        清单 = {
            "制品摘要": 计算制品摘要(环境体),
            "依赖锁摘要": 锁摘要覆盖 or 锁文件摘要(提供者 / "依赖锁.json"),
            "python版本": sys.version.split()[0],
            "系统版本": _真实系统版本(),
            "架构": platform.machine(),
            "信任指纹": 测试指纹,
        }
        签名结果 = 签名清单(清单, self.私钥PEM)
        assert 签名结果.成功, 签名结果.错误说明
        签名后清单 = 签名结果.值
        if 签名后篡改:
            签名后清单["签名"] = "00" * 128
        (镜像项目录 / "镜像清单.json").write_text(
            json.dumps(签名后清单, ensure_ascii=False), encoding="utf-8")
        return "file://" + str(仓库)

    def test_未启用时行为零变化(self):
        """无配置文件（默认关闭）→ 不调用镜像、证据与本地构建完全不变。"""
        提供者 = self.新提供者(锁=样例锁())
        # 不 patch `获取镜像清单`/`下载镜像制品`：默认关闭时真实现**本来就不走到**那一步，
        # 用真实副作用证明——证据只有 [重建, 命中] 两行且错误码全空（若走了镜像且失败，
        # 必留一行 类型=失败 的镜像证据，见 `_尝试镜像命中`）。
        self.assertFalse(读取远程镜像配置(self.配置路径).启用)
        with self.注入构建() as 假venv:
            结果一 = 确保环境(提供者)
            结果二 = 确保环境(提供者)
        self.assertTrue(结果一.成功)
        self.assertTrue(结果二.成功)
        self.assertEqual(假venv.调用次数, 1)  # 第二次命中本地缓存
        证据 = self.证据行()
        self.assertEqual([行["类型"] for 行 in 证据], ["重建", "命中"])
        self.assertEqual([行["错误码"] for 行 in 证据], ["", ""])

    def test_镜像命中恢复环境(self):
        """启用镜像 + 全部匹配 → 从镜像恢复（镜像命中），不触发本地构建。"""
        提供者 = self.新提供者(锁=样例锁())
        摘要 = 计算环境摘要(样例锁(), 提供者.name)
        镜像地址 = self.构造镜像制品(提供者, 摘要)
        self.写镜像配置(镜像地址)
        with self.注入构建() as 假venv:
            结果 = 确保环境(提供者)
        self.assertTrue(结果.成功)
        self.assertEqual(假venv.调用次数, 0)  # 未走本地构建
        目标 = 环境目录(提供者, 摘要)
        self.assertTrue((目标 / "bin" / "python3").is_file())
        self.assertTrue((目标 / "site-packages" / "docx.py").is_file())
        证据 = self.证据行()
        self.assertEqual([行["类型"] for 行 in 证据], ["镜像命中"])

    def test_镜像不可用回退本地构建(self):
        """镜像服务不可访问（地址不存在）→ 镜像不可用 + 明确回退本地构建。"""
        提供者 = self.新提供者(锁=样例锁())
        self.写镜像配置("file://" + str(self.临时 / "不存在的镜像仓库"))
        with self.注入构建() as 假venv:
            结果 = 确保环境(提供者)
        self.assertTrue(结果.成功)
        self.assertEqual(假venv.调用次数, 1)  # 回退本地构建成功
        证据 = self.证据行()
        self.assertEqual([行["类型"] for 行 in 证据], ["失败", "重建"])
        self.assertEqual(证据[0]["错误码"], 镜像不可用)
        self.assertTrue(证据[0]["错误说明"])

    def test_镜像摘要不匹配回退本地构建(self):
        """伪造镜像（依赖锁摘要不符）→ 镜像摘要不匹配 + 回退本地构建。"""
        提供者 = self.新提供者(锁=样例锁())
        摘要 = 计算环境摘要(样例锁(), 提供者.name)
        镜像地址 = self.构造镜像制品(提供者, 摘要, 锁摘要覆盖="伪造锁摘要-ffff")
        self.写镜像配置(镜像地址)
        with self.注入构建() as 假venv:
            结果 = 确保环境(提供者)
        self.assertTrue(结果.成功)
        self.assertEqual(假venv.调用次数, 1)
        证据 = self.证据行()
        self.assertEqual([行["类型"] for 行 in 证据], ["失败", "重建"])
        self.assertEqual(证据[0]["错误码"], 镜像摘要不匹配)
        self.assertIn("依赖锁不匹配", 证据[0]["错误说明"])

    def test_镜像签名无效回退本地构建(self):
        """镜像清单签名被篡改 → 镜像签名无效 + 回退本地构建（信任指纹不足为凭）。"""
        提供者 = self.新提供者(锁=样例锁())
        摘要 = 计算环境摘要(样例锁(), 提供者.name)
        镜像地址 = self.构造镜像制品(提供者, 摘要, 签名后篡改=真)
        self.写镜像配置(镜像地址)
        with self.注入构建() as 假venv:
            结果 = 确保环境(提供者)
        self.assertTrue(结果.成功)
        self.assertEqual(假venv.调用次数, 1)
        证据 = self.证据行()
        self.assertEqual([行["类型"] for 行 in 证据], ["失败", "重建"])
        self.assertEqual(证据[0]["错误码"], 镜像签名无效)
        self.assertIn("签名", 证据[0]["错误说明"])

    def test_镜像下载失败回退本地构建(self):
        """清单匹配但制品缺失 → 镜像下载失败 + 回退本地构建。"""
        提供者 = self.新提供者(锁=样例锁())
        摘要 = 计算环境摘要(样例锁(), 提供者.name)
        镜像地址 = self.构造镜像制品(提供者, 摘要, 不打包制品=真)
        self.写镜像配置(镜像地址)
        with self.注入构建() as 假venv:
            结果 = 确保环境(提供者)
        self.assertTrue(结果.成功)
        self.assertEqual(假venv.调用次数, 1)
        证据 = self.证据行()
        self.assertEqual([行["类型"] for 行 in 证据], ["失败", "重建"])
        self.assertEqual(证据[0]["错误码"], 镜像下载失败)

    def test_镜像环境复校验失败拒绝不落盘(self):
        """镜像环境无法通过本地校验 → 拒绝（镜像下载失败），不落盘、回退构建。"""
        提供者 = self.新提供者(锁=样例锁())
        摘要 = 计算环境摘要(样例锁(), 提供者.name)
        # 镜像里的解释器是**退出码 1** 的真骨架 → 本地复校验由真实子进程判失败
        # （不再 `mock.patch(…校验环境, return_value=假)`）；本地构建注入的假 venv
        # 仍落退出码 0 的解释器 → 回退构建成功。两处都是真实状态，不换被测函数。
        镜像地址 = self.构造镜像制品(提供者, 摘要, 解释器失败=真)
        self.写镜像配置(镜像地址)
        with self.注入构建() as 假venv:
            结果 = 确保环境(提供者)
        self.assertTrue(结果.成功)  # 回退本地构建成功
        self.assertEqual(假venv.调用次数, 1)
        目标 = 环境目录(提供者, 摘要)
        self.assertTrue((目标 / "bin" / "python3").is_file())  # 本地构建落盘
        证据 = self.证据行()
        self.assertEqual([行["类型"] for 行 in 证据], ["失败", "重建"])
        self.assertEqual(证据[0]["错误码"], 镜像下载失败)
        self.assertIn("复校验失败", 证据[0]["错误说明"])

    def test_镜像失败不伪装缓存命中(self):
        """镜像任一失败 → 证据类型 失败（不得伪装成 命中）。"""
        提供者 = self.新提供者(锁=样例锁())
        self.写镜像配置("file://" + str(self.临时 / "不存在的镜像仓库"))
        with self.注入构建() as 假venv:
            确保环境(提供者)
        证据 = self.证据行()
        self.assertEqual(证据[0]["类型"], "失败")
        self.assertNotIn("命中", [行["类型"] for 行 in 证据])

    def test_镜像命中后本地缓存复用(self):
        """镜像恢复后再次确保 → 本地缓存命中（镜像结果已落盘可复用）。"""
        提供者 = self.新提供者(锁=样例锁())
        摘要 = 计算环境摘要(样例锁(), 提供者.name)
        镜像地址 = self.构造镜像制品(提供者, 摘要)
        self.写镜像配置(镜像地址)
        with self.注入构建() as 假venv:
            结果一 = 确保环境(提供者)
            结果二 = 确保环境(提供者)
        self.assertTrue(结果一.成功)
        self.assertTrue(结果二.成功)
        证据 = self.证据行()
        self.assertEqual([行["类型"] for 行 in 证据], ["镜像命中", "命中"])


def _真实系统版本() -> str:
    """与 环境管理器._系统版本详情 一致的真实系统版本（端到端匹配）。"""
    import subprocess
    try:
        结果 = subprocess.run(["sw_vers"], capture_output=True, timeout=10)
        if 结果.returncode == 0:
            return 结果.stdout.decode("utf-8", "ignore").strip()
    except Exception as 错误:  # 允许忽略，但留痕（哲学第 15 条）
        记录忽略('测试_环境镜像._真实系统版本', 错误)
    import platform as 平台
    return f"{平台.system()} {平台.release()}"


if __name__ == "__main__":
    unittest.main()
