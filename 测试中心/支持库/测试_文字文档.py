"""文字文档支持库真实解析测试（unittest）。

覆盖：最小有效 docx / 多段落表格中文 / 空文档 / 损坏文件 / 扩展名伪装 /
缺提供者（monkeypatch 模拟）/ doc 转换链（LibreOffice 在则真实转换）/ 往返。
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

系统根 = Path(__file__).resolve().parents[2]

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.运行时 import 进程终止, 平台适配
from 支持库.后端.办公文档支持库.文字文档 import 解析文字文档

默认soffice路径 = "/Applications/LibreOffice.app/Contents/MacOS/soffice"


def _找soffice() -> str | None:
    """定位 soffice（环境变量 → PATH → macOS 应用包内路径），找不到返回 None。"""
    候选 = [os.getenv("LIBREOFFICE_BIN"), os.getenv("SOFFICE_BIN"),
           shutil.which("soffice"), 默认soffice路径]
    return next((项 for 项 in 候选 if 项 and Path(项).exists()), None)


def _转换办公文件(源: Path, 输出目录: Path, 目标格式: str, *,
              超时秒: float = 120.0, 尝试次数: int = 3) -> Path | None:
    """经 soffice 把 源 转成 目标格式，返回产物路径；重试后仍无产出返回 None。

    两处并发脆弱点在此收口：
    1) 私有档案：LibreOffice 桌面端是单实例，同一 UserInstallation（默认落在用户档案
       目录）下后到的 --convert-to 会被静默丢弃——退出码 0 但零产出。故每次尝试都用
       独立私有档案，与同机其它进程的实例完全隔离。
    2) 有限次重试：仍按指数退避重试，避免单次竞态直接把用例判红。
    """
    soffice = _找soffice()
    if not soffice:
        return None
    目标 = 输出目录 / f"{源.stem}.{目标格式}"
    for 第几次 in range(1, 尝试次数 + 1):
        档案 = Path(tempfile.mkdtemp(prefix=f"私有档案_{第几次}_", dir=str(输出目录.parent)))
        try:
            # 目标与源不同名、且每轮先清目标：LibreOffice 遇到已存在的同名目标会拒绝覆盖
            if 目标.exists():
                目标.unlink()
            进程 = subprocess.Popen(
                [soffice, f"-env:UserInstallation=file://{档案}", "--headless",
                 "--norestore", "--convert-to", 目标格式,
                 "--outdir", str(输出目录), str(源)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                **平台适配.子进程组启动标志())
            try:
                进程.communicate(timeout=超时秒)
            except subprocess.TimeoutExpired:
                # 按进程组回收：子 shell 包一层时也不会留下孤儿 soffice 持有档案锁
                进程终止.强制结束子进程(进程, 宽限秒=1.0, 等待秒=2.0)
                进程.communicate()
            if 目标.is_file() and 目标.stat().st_size > 0:
                return 目标
        finally:
            shutil.rmtree(档案, ignore_errors=True)
        if 第几次 < 尝试次数:
            time.sleep(2 ** (第几次 - 1))
    return None


@contextlib.contextmanager
def _实现走私有档案(档案根: Path):
    """让被测链路（实现内部的 soffice 调用）也走私有档案。

    实现 支持库.后端.文档转换支持库.LibreOffice转换 只用 查找LibreOffice() 取可执行
    路径（并缓存）。这里把该函数指向一个「每次调用用独立私有档案」的包装脚本——
    只换可执行入口，转换本身仍是真实 soffice，不做任何打桩假成功。
    """
    from 支持库.后端.文档转换支持库.LibreOffice转换.实现 import 文档转换 as 文档转换模块

    真实 = _找soffice()
    if not 真实:
        yield None
        return
    档案根.mkdir(parents=True, exist_ok=True)
    包装 = 档案根 / "soffice私有档案"
    # 脚本内变量名必须用 ASCII：macOS /bin/sh 不认多字节变量名（会报 Illegal byte sequence）
    包装.write_text(
        "#!/bin/sh\n"
        f'prof="{档案根}/call_$$"\n'
        'mkdir -p "$prof" || exit 1\n'
        "trap 'rm -rf \"$prof\"' EXIT\n"
        f'"{真实}" -env:UserInstallation="file://$prof" "$@"\n'
        'rc=$?\n'
        'exit $rc\n')
    os.chmod(包装, 0o755)
    with mock.patch.object(文档转换模块, "查找LibreOffice", return_value=str(包装)):
        yield str(包装)


class 假调用器:
    """测试注入的假能力调用器：所有能力返回 提供者不可用。"""

    def 调用能力(self, 能力id, 参数=None, **关键字):
        return 结果.失败("提供者不可用", f"{能力id} 不可用（模拟调用器）", 来源="测试", 可重试=True)

    def 幂等重放(self, *args, **kwargs):
        return False

    def 查询调用历史(self, 上限=50):
        return []

    def 最近失败(self, 上限=10):
        return []

    def 回答九问(self, *args, **kwargs):
        return {}


def _生成docx(路径: Path, 中文: bool = True) -> None:
    from docx import Document
    文档 = Document()
    文档.add_heading("测试标题", level=1)
    文档.add_paragraph("第一段：中文内容。" if 中文 else "First paragraph.")
    表格 = 文档.add_table(rows=2, cols=2)
    表格.cell(0, 0).text = "姓名"
    表格.cell(0, 1).text = "分数"
    表格.cell(1, 0).text = "张三"
    表格.cell(1, 1).text = "95"
    文档.save(str(路径))


class Test文字文档(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """装配唯一能力调用服务：安装全部支持库（含受管提供者）并绑定。"""
        from 公共契约.能力契约.契约 import 能力注册表
        from 运行核心.能力调用.唯一能力调用 import 创建并绑定
        from 运行核心.加载器.包安装.支持库安装 import 安装全部支持库

        cls.注册表 = 能力注册表()
        安装全部支持库(系统根 / "支持库", cls.注册表)
        cls.服务 = 创建并绑定(cls.注册表)

    @classmethod
    def tearDownClass(cls):
        from 运行核心.能力调用.唯一能力调用 import 销毁全局唯一服务
        销毁全局唯一服务()

    def setUp(self):
        self.临时目录 = tempfile.mkdtemp(prefix="测试_文字文档_")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.临时目录, ignore_errors=True)

    def test_解析最小docx(self):
        路径 = Path(self.临时目录) / "最小.docx"
        _生成docx(路径)
        结果 = 解析文字文档(str(路径), "docx")
        self.assertTrue(结果.成功, f"失败: {结果.错误说明 if not 结果.成功 else ''}")
        文档 = 结果.值
        self.assertEqual(文档.格式, "docx")
        self.assertEqual(文档.标题, "最小.docx")
        文本合集 = " ".join(块.文本 for 块 in 文档.块列表)
        self.assertIn("测试标题", 文本合集)
        self.assertIn("中文内容", 文本合集)
        self.assertTrue(any(块.类型 == "表格" for 块 in 文档.块列表))
        表格块 = next(块 for 块 in 文档.块列表 if 块.类型 == "表格")
        self.assertEqual(表格块.表格数据[0], ["姓名", "分数"])

    def test_空文档解析(self):
        路径 = Path(self.临时目录) / "空.docx"
        from docx import Document
        文档 = Document()
        文档.save(str(路径))
        结果 = 解析文字文档(str(路径), "docx")
        self.assertTrue(结果.成功)
        self.assertEqual(结果.值.块列表, [])

    def test_文件不存在(self):
        结果 = 解析文字文档("/不存在的路径/文件.docx", "docx")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "文件不存在")

    def test_格式非法(self):
        路径 = Path(self.临时目录) / "非法.docx"
        _生成docx(路径)
        结果 = 解析文字文档(str(路径), "pdf")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "参数不合法")

    def test_损坏文件(self):
        路径 = Path(self.临时目录) / "损坏.docx"
        路径.write_bytes(b"not a zip at all" * 100)
        结果 = 解析文字文档(str(路径), "docx")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "文件损坏")

    def test_扩展名伪装(self):
        路径 = Path(self.临时目录) / "伪装.docx"
        路径.write_text("这只是个文本文件", encoding="utf-8")
        结果 = 解析文字文档(str(路径), "docx")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "文件损坏")

    def test_缺提供者返回不可用(self):
        # 临时注入假调用器（受管提供者不可用）→ 如实返回 提供者不可用
        from 运行核心.能力调用.唯一能力调用 import 创建并绑定, 设置全局唯一服务

        路径 = Path(self.临时目录) / "任意.docx"
        路径.write_bytes(b"x")
        设置全局唯一服务(假调用器())
        try:
            结果 = 解析文字文档(str(路径), "docx")
            self.assertFalse(结果.成功)
            self.assertEqual(结果.错误码, "提供者不可用")
        finally:
            创建并绑定(self.__class__.注册表)

    def test_doc转换链(self):
        # 本机 LibreOffice 可用时真实转换
        if not _找soffice():
            self.skipTest("LibreOffice 不可用")
        源 = Path(self.临时目录) / "源文档.docx"
        _生成docx(源)
        # docx 内容另存为 doc（LibreOffice 转换 docx→doc 再验证反向）
        # 目标目录与源分开、且目标名与源不同名：同名目标已存在时 LibreOffice 拒绝覆盖，
        # 转换必然零产出（修复前 旧文档.doc 与 旧文档.docx 同根同名，正是此处踩坑）。
        输出目录 = Path(self.临时目录) / "转doc"
        输出目录.mkdir()
        doc路径 = _转换办公文件(源, 输出目录, "doc")
        if doc路径 is None:
            self.fail("LibreOffice doc 转换未产出：私有档案 + 3 次重试后仍无产物"
                      "（修复前此处的「没产出」被恒存在的旧路径冒充成解析失败）")
        with _实现走私有档案(Path(self.临时目录) / "实现档案"):
            结果 = 解析文字文档(str(doc路径), "doc")
        self.assertTrue(结果.成功, f"doc 解析失败: {结果.错误说明 if not 结果.成功 else ''}")
        self.assertIn("converted_from_doc", 结果.值.警告)

    def test_往返验证(self):
        路径 = Path(self.临时目录) / "往返.docx"
        _生成docx(路径)
        结果 = 解析文字文档(str(路径), "docx")
        self.assertTrue(结果.成功)
        文档 = 结果.值
        self.assertTrue(文档.原始文件摘要)
        self.assertEqual(文档.附加.get("来源"), "python_docx提供者")


if __name__ == "__main__":
    unittest.main()
