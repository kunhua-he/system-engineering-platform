"""镜像发布工具测试：合法发布/路径穿越拒绝/摘要一致/可验证元数据/私钥边界。

覆盖：
- 合法发布：收集（排除易变文件）/文件清单/制品摘要/签名/打包 产物齐全，
  输出 镜像清单.json/制品.tar.gz/镜像签名.txt/制品摘要.txt/发布元数据.json。
- 防路径穿越：../ 与绝对路径成员拒绝打包；符号链接逃逸出环境目录拒绝
  发布；解包侧（下载镜像制品）拒绝逃逸链接成员。
- 摘要一致：文件清单与磁盘 sha256 逐一比对；清单摘要重算一致；内容变化
  → 制品摘要/清单摘要/签名 联动变化。
- 与 wp1 签名验证衔接：发布产物经 验证清单签名/远程镜像校验器（公钥
  强制信任依据）全部验证通过；篡改/换公钥/伪造摘要一律拒绝；最小签名
  验证（提供者 验证签名 直接验签 签名原文b64）仍兼容。
- 发布者边界：私钥非空强制；产物不含私钥。
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 运行核心.运行环境管理器.镜像发布 import (
    _安全打包,
    发布摘要文件名,
    发布环境镜像,
    发布非法路径,
    发布结果,
    发布私钥缺失,
    发布签名文件名,
    发布清单文件名,
    发布元数据文件名,
    发布制品文件名,
)
from 运行核心.运行环境管理器.远程镜像 import (
    _清单稳定序列化,
    计算制品摘要,
    计算文件清单摘要,
    镜像校验请求,
    镜像签名无效,
    镜像摘要不匹配,
    镜像下载失败,
    远程镜像校验器,
    验证清单签名,
    下载镜像制品,
)
from 支持库.适配层.密码签名提供者 import 公钥指纹, 生成密钥对, 验证签名

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

测试指纹 = "测试发布信任指纹-9b2c"


class Test镜像发布(unittest.TestCase):
    """镜像发布工具：发布流程与产物可验证性（衔接 wp1 签名验证）。"""

    @classmethod
    def setUpClass(cls):
        密钥 = 生成密钥对()
        cls.私钥PEM = 密钥.值["私钥PEM"]
        cls.公钥PEM = 密钥.值["公钥PEM"]
        cls.指纹 = 公钥指纹(cls.公钥PEM).值

    def setUp(self):
        self.临时 = Path(tempfile.mkdtemp(dir=受管临时根))
        self.addCleanup(清只读后删除树, self.临时, 忽略失败=真)
        self.环境 = self.临时 / "环境体"
        (self.环境 / "bin").mkdir(parents=True)
        (self.环境 / "bin" / "python3").write_text("#!/bin/sh\nexit 0\n",
                                                   encoding="utf-8")
        (self.环境 / "site-packages").mkdir()
        (self.环境 / "site-packages" / "docx.py").write_text("x=1\n",
                                                             encoding="utf-8")
        (self.环境 / "依赖锁.json").write_text(json.dumps({
            "包": [{"名称": "python-docx", "版本": "1.2.0", "模块名": "docx"}],
        }, ensure_ascii=False), encoding="utf-8")
        (self.环境 / "site-packages" / "__pycache__").mkdir()
        (self.环境 / "site-packages" / "__pycache__" / "temp.pyc").write_text(
            "t", encoding="utf-8")
        self.输出 = self.临时 / "发布产物"
        self.元数据 = {"信任指纹": 测试指纹, "发布者": "测试发布者", "版本": "1.0"}

    def 发布(self, *, 元数据=None, 公钥PEM=None, 私钥PEM=None) -> 发布结果:
        return 发布环境镜像(
            self.环境, self.输出, 私钥PEM if 私钥PEM is not None else self.私钥PEM,
            元数据=元数据 if 元数据 is not None else self.元数据,
            公钥PEM=公钥PEM if 公钥PEM is not None else self.公钥PEM)

    def 读清单(self) -> dict:
        return json.loads(
            (self.输出 / 发布清单文件名).read_text(encoding="utf-8"))

    # ---- 合法发布 ----
    def test_合法发布产物齐全(self):
        """收集/清单/摘要/签名/打包 产物五件套齐全，易变文件排除。"""
        结果 = self.发布()
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertEqual(结果.文件数, 3)  # bin/python3 + docx.py + 依赖锁.json
        for 文件名 in (发布清单文件名, 发布制品文件名, 发布签名文件名,
                       发布摘要文件名, 发布元数据文件名):
            self.assertTrue((self.输出 / 文件名).is_file(), 文件名)
        self.assertEqual(结果.制品摘要, 计算制品摘要(self.环境))
        self.assertEqual(
            结果.制品摘要,
            (self.输出 / 发布摘要文件名).read_text(encoding="utf-8").strip())
        self.assertEqual(len(结果.签名hex), 128)  # Ed25519 = 64 字节 hex
        self.assertEqual(len(结果.清单摘要), 64)
        self.assertEqual(结果.公钥指纹, self.指纹)
        self.assertEqual(
            (self.输出 / 发布签名文件名).read_text(encoding="utf-8").strip(),
            结果.签名hex)

    def test_清单字段与校验器契约一致(self):
        """清单六匹配字段+文件清单+文件清单摘要+元数据+签名（wp1 格式）。"""
        结果 = self.发布()
        清单 = self.读清单()
        for 字段 in ("制品摘要", "依赖锁摘要", "python版本", "系统版本",
                     "架构", "信任指纹", "文件清单", "文件清单摘要",
                     "元数据", "签名"):
            self.assertIn(字段, 清单)
        self.assertEqual(清单["信任指纹"], 测试指纹)
        self.assertEqual(清单["元数据"]["发布者"], "测试发布者")
        self.assertIsInstance(清单["签名"], str)  # wp1 契约：签名=hex 文本
        self.assertEqual(len(清单["签名"]), 128)
        self.assertEqual(清单["文件清单摘要"],
                         计算文件清单摘要(self.环境))
        self.assertEqual(
            清单["依赖锁摘要"],
            hashlib.sha256((self.环境 / "依赖锁.json").read_bytes()).hexdigest())
        # 易变文件不进入文件清单
        self.assertNotIn("site-packages/__pycache__/temp.pyc",
                         清单["文件清单"])
        self.assertEqual(set(清单["文件清单"]),
                         {"bin/python3", "site-packages/docx.py", "依赖锁.json"})

    def test_文件清单与磁盘摘要一致(self):
        """文件清单逐项 sha256/大小 与磁盘一致。"""
        self.发布()
        清单 = self.读清单()
        for 相对文本, 摘要信息 in 清单["文件清单"].items():
            磁盘 = (self.环境 / 相对文本).read_bytes()
            self.assertEqual(摘要信息["sha256"],
                             hashlib.sha256(磁盘).hexdigest())
            self.assertEqual(摘要信息["大小"], len(磁盘))

    # ---- 与 wp1 签名验证衔接 ----
    def test_清单摘要与签名可验证(self):
        """清单摘要=去签名字段稳定序列化摘要；wp1 验证清单签名通过。"""
        结果 = self.发布()
        清单 = self.读清单()
        签名值 = 清单.pop("签名")
        self.assertEqual(结果.清单摘要,
                         hashlib.sha256(_清单稳定序列化(清单)).hexdigest())
        # wp1 衔接：验证清单签名（公钥强制信任依据）
        验证 = 验证清单签名({**清单, "签名": 签名值}, self.公钥PEM)
        self.assertTrue(验证.成功 and 验证.值, 验证.错误说明)
        # 篡改清单正文 → 签名无效
        篡改 = {**清单, "签名": 签名值, "架构": "x86_64"}
        self.assertFalse(验证清单签名(篡改, self.公钥PEM).成功)
        # 换公钥 → 签名无效
        self.assertFalse(
            验证清单签名({**清单, "签名": 签名值}, "他人公钥").成功)

    def test_签名原文b64最小验证兼容(self):
        """发布元数据携带 签名原文b64：持公钥直接验签（最小验证兜底）。"""
        结果 = self.发布()
        元数据 = json.loads(
            (self.输出 / 发布元数据文件名).read_text(encoding="utf-8"))
        清单 = self.读清单()
        签名值 = 清单["签名"]
        直接验证 = 验证签名(self.公钥PEM, 元数据["签名原文b64"], 签名值)
        self.assertTrue(直接验证.成功 and 直接验证.值, 直接验证.错误说明)
        # 篡改原文 → 验签失败
        self.assertFalse(
            验证签名(self.公钥PEM,
                      base64.b64encode("被篡改".encode("utf-8")).decode("ascii"),
                      签名值).值)

    def test_发布产物可被远程镜像校验器验证(self):
        """发布清单经 远程镜像校验器 全链（公钥签名+指纹+五条件）允许命中。"""
        结果 = self.发布()
        清单 = self.读清单()
        请求 = 镜像校验请求(
            依赖锁摘要=清单["依赖锁摘要"],
            python版本=清单["python版本"],
            系统版本=清单["系统版本"],
            架构=清单["架构"],
        )
        校验 = 远程镜像校验器(请求, 清单, 测试指纹,
                               公钥PEM=self.公钥PEM,
                               实际制品摘要=结果.制品摘要)
        self.assertTrue(校验.允许命中, 校验.错误说明)
        # 换公钥 → 镜像签名无效
        换公钥 = 远程镜像校验器(请求, 清单, 测试指纹, 公钥PEM="他人公钥")
        self.assertFalse(换公钥.允许命中)
        self.assertEqual(换公钥.错误码, 镜像签名无效)
        # 伪造下载内容 → 镜像摘要不匹配
        伪造 = 远程镜像校验器(请求, 清单, 测试指纹, 公钥PEM=self.公钥PEM,
                               实际制品摘要="伪造-ffff")
        self.assertFalse(伪造.允许命中)
        self.assertEqual(伪造.错误码, 镜像摘要不匹配)

    def test_制品包可解包且成员无非法路径(self):
        """制品包成员全为相对路径，无绝对路径/../；可完整解包还原。"""
        结果 = self.发布()
        with tarfile.open(self.输出 / 发布制品文件名, "r:gz") as 压缩包:
            成员表 = 压缩包.getnames()
        for 名称 in 成员表:
            self.assertFalse(名称.startswith("/"))
            self.assertNotIn("..", Path(名称).parts)
        self.assertEqual(set(成员表),
                         {"bin/python3", "site-packages/docx.py", "依赖锁.json"})

    def test_内容变化摘要与签名联动(self):
        """文件内容变化 → 制品摘要/清单摘要/签名 全部联动变化。"""
        结果一 = self.发布()
        (self.环境 / "site-packages" / "docx.py").write_text("x=2\n",
                                                             encoding="utf-8")
        结果二 = self.发布()
        self.assertTrue(结果一.成功 and 结果二.成功)
        self.assertNotEqual(结果一.制品摘要, 结果二.制品摘要)
        self.assertNotEqual(结果一.清单摘要, 结果二.清单摘要)
        self.assertNotEqual(结果一.签名hex, 结果二.签名hex)

    # ---- 路径穿越拒绝 ----
    def test_符号链接逃逸拒绝发布(self):
        """环境目录内符号链接指向目录外 → 拒绝（发布非法路径）。"""
        (self.临时 / "外部文件.txt").write_text("秘密", encoding="utf-8")
        (self.环境 / "逃逸链接").symlink_to(self.临时 / "外部文件.txt")
        结果 = self.发布()
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, 发布非法路径)
        self.assertIn("逃逸", 结果.错误说明)
        self.assertFalse((self.输出 / 发布制品文件名).exists())

    def test_绝对路径成员拒绝打包(self):
        """伪造绝对路径成员 → 打包拒绝。"""
        self.输出.mkdir(parents=True, exist_ok=True)
        with self.assertRaises(ValueError):
            _安全打包([("/绝对路径.txt", self.环境 / "bin" / "python3")],
                      self.输出 / 发布制品文件名)

    def test_点点路径成员拒绝打包(self):
        """伪造 ../ 穿越成员 → 打包拒绝。"""
        self.输出.mkdir(parents=True, exist_ok=True)
        with self.assertRaises(ValueError):
            _安全打包([("../逃逸.txt", self.环境 / "bin" / "python3")],
                      self.输出 / 发布制品文件名)

    def test_解包侧拒绝逃逸链接(self):
        """下载镜像制品：含逃逸链接成员（../../）→ 镜像下载失败，不落盘。"""
        镜像仓库 = self.临时 / "镜像仓库"
        项目录 = 镜像仓库 / "提供者id" / "摘要"
        项目录.mkdir(parents=True)
        恶意包 = 项目录 / 发布制品文件名
        with tarfile.open(恶意包, "w:gz") as 压缩包:
            信息 = tarfile.TarInfo("正常文件.txt")
            信息.size = 3
            压缩包.addfile(信息, io.BytesIO(b"ok\n"))
            链接信息 = tarfile.TarInfo("逃逸链接")
            链接信息.type = tarfile.SYMTYPE
            链接信息.linkname = "../../外部.txt"
            压缩包.addfile(链接信息)
        目标 = self.临时 / "解包目标"
        结果 = 下载镜像制品("file://" + str(镜像仓库), "提供者id", "摘要", 目标)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, 镜像下载失败)
        self.assertIn("逃逸", 结果.错误说明)

    # ---- 发布者角色边界 ----
    def test_私钥缺失拒绝发布(self):
        """私钥空/空白/None → 拒绝（发布私钥缺失）。"""
        for 非法私钥 in ("", "   ", None):
            结果 = 发布环境镜像(self.环境, self.输出, 非法私钥,
                                   元数据=self.元数据)
            self.assertFalse(结果.成功)
            self.assertEqual(结果.错误码, 发布私钥缺失)

    def test_发布产物不含私钥(self):
        """任何输出文件不得含私钥内容（私钥仅发布角色持有）。"""
        结果 = self.发布()
        self.assertTrue(结果.成功)
        for 文件 in self.输出.iterdir():
            if 文件.is_file():
                文本 = 文件.read_text(encoding="utf-8", errors="ignore")
                self.assertNotIn("PRIVATE KEY", 文本)


if __name__ == "__main__":
    unittest.main()
