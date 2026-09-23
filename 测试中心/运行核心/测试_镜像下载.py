"""镜像下载强化测试（工作包三）：代理配置/直连/防路径穿越/复校验/原子落盘。

覆盖：
- 代理：配置 代理地址 生效（本地 HTTP 镜像 + 本地 HTTP 记录代理，端到端）；
  未配置代理显式直连（代理零请求，地址一律来自配置、不硬编码）；
  代理不可用 → 镜像下载失败，端到端明确回退本地构建。
- 解包防逃逸：拒绝 绝对路径/.. 穿越/符号链接逃逸，失败不落半成品。
- 复校验：文件清单 sha256（镜像清单声明时比对，不符拒绝）。
- 原子落盘：fsync + os.replace；成功可读；失败无残留；半成品清理。
- 签名衔接（wp1）：下载链清单必须签名有效（端到端命中/篡改回退）。
"""

from __future__ import annotations

import hashlib
import http.server
import io
import json
import platform
import sys
import tarfile
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 支持库.适配层.密码签名提供者 import 生成密钥对
from 运行核心.运行环境管理器.环境管理器 import (
    计算环境摘要, 确保环境, 环境目录,
)
from 运行核心.运行环境管理器.远程镜像 import (
    计算制品摘要, 计算文件清单摘要, 获取镜像清单, 镜像不可用,
    镜像下载失败, 读取远程镜像配置, 下载镜像制品, 签名清单, 原子落盘,
)
from 公共契约.诊断.忽略记录 import 记录忽略
from 公共契约.基础类型.逻辑类型 import 真, 假
from 测试中心.运行核心.环境夹具 import 注入假venv

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


class _镜像处理器(http.server.SimpleHTTPRequestHandler):
    """本地 HTTP 测试镜像（静态目录服务，隔离地址；根来自服务器实例）。"""

    def __init__(self, 请求, 客户端地址, 服务器):
        super().__init__(请求, 客户端地址, 服务器,
                         directory=str(服务器.仓库根))

    def log_message(self, *参数):
        pass


class _记录代理处理器(http.server.BaseHTTPRequestHandler):
    """极简 HTTP 代理：记录请求路径并转发到镜像服务器（显式直连上游）。"""

    请求记录: list[str] = []

    def do_GET(self):
        _记录代理处理器.请求记录.append(self.path)
        目标 = self.path if self.path.startswith("http") else (
            self.server.镜像地址 + self.path)
        打开器 = urllib.request.build_opener(
            urllib.request.ProxyHandler({}))
        try:
            with 打开器.open(目标, timeout=10) as 上游:
                数据 = 上游.read()
        except Exception as 错误:
            self.send_error(502, f"代理转发失败: {错误}")
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(数据)))
        self.end_headers()
        self.wfile.write(数据)

    def log_message(self, *参数):
        pass


def _启动服务器(处理器类, **属性) -> http.server.ThreadingHTTPServer:
    服务器 = http.server.ThreadingHTTPServer(("127.0.0.1", 0), 处理器类)
    for 名称, 值 in 属性.items():
        setattr(服务器, 名称, 值)
    threading.Thread(target=服务器.serve_forever, daemon=True).start()
    return 服务器


def _启动镜像服务器(仓库根: Path) -> http.server.ThreadingHTTPServer:
    """以 仓库根 为静态根启动镜像服务器（根绑定到服务器实例）。"""
    return _启动服务器(_镜像处理器, 仓库根=仓库根)


def _关闭服务器(服务器) -> None:
    try:
        服务器.shutdown()
    finally:
        服务器.server_close()


def _已关闭端口() -> int:
    """取一个已关闭的本地端口（模拟不可用代理）。"""
    服务器 = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), http.server.BaseHTTPRequestHandler)
    端口 = 服务器.server_address[1]
    服务器.server_close()
    return 端口


def _路径尾(路径文本: str) -> str:
    return urllib.parse.unquote(str(路径文本).rsplit("/", 1)[-1])


def _生成密钥对() -> tuple[str, str]:
    """测试内生成临时 Ed25519 密钥对（发布角色语义，运行核心不持私钥）。"""
    结果 = 生成密钥对()
    assert 结果.成功, 结果.错误说明
    return 结果.值["私钥PEM"], 结果.值["公钥PEM"]


def _构建环境体(环境体: Path) -> None:
    """构造镜像制品环境体（bin/python3 + site-packages/docx.py）。

    解释器骨架必须 `chmod 0o755`：镜像恢复后真 `校验环境` 会把它当可执行文件起
    子进程做 import 校验（旧写法把 `校验环境` 整段 mock 掉，从没碰到这一层），
    不可执行会 `PermissionError` → 复校验失败 → 镜像永远命不中。
    """
    (环境体 / "bin").mkdir(parents=True)
    (环境体 / "bin" / "python3").write_text("#!/bin/sh\nexit 0\n")
    (环境体 / "bin" / "python3").chmod(0o755)
    (环境体 / "site-packages").mkdir()
    (环境体 / "site-packages" / "docx.py").write_text("ok=1\n")


def _真实系统版本() -> str:
    """与 环境管理器._系统版本详情 一致的真实系统版本（端到端匹配）。"""
    import subprocess
    try:
        结果 = subprocess.run(["sw_vers"], capture_output=True, timeout=10)
        if 结果.returncode == 0:
            return 结果.stdout.decode("utf-8", "ignore").strip()
    except Exception as 错误:  # 允许忽略，但留痕（哲学第 15 条）
        记录忽略('测试_镜像下载._真实系统版本', 错误)
    return f"{platform.system()} {platform.release()}"


def 构造镜像(镜像仓库: Path, 摘要: str, 私钥PEM: str, *,
             清单覆盖: dict | None = None,
             含文件清单摘要: bool = 假) -> dict:
    """在镜像仓库构造签名镜像（HTTP 可访问）；返回签名后清单。"""
    镜像项目录 = 镜像仓库 / "docx提供者" / 摘要
    环境体 = 镜像项目录 / "环境体"
    _构建环境体(环境体)
    with tarfile.open(镜像项目录 / "制品.tar.gz", "w:gz") as 压缩包:
        压缩包.add(环境体, arcname=".")
    清单 = {
        "制品摘要": 计算制品摘要(环境体),
        "依赖锁摘要": "锁摘要-1111",
        "python版本": sys.version.split()[0],
        "系统版本": _真实系统版本(),
        "架构": platform.machine(),
        "信任指纹": 测试指纹,
    }
    if 含文件清单摘要:
        清单["文件清单摘要"] = 计算文件清单摘要(环境体)
    清单.update(清单覆盖 or {})
    签名结果 = 签名清单(清单, 私钥PEM)
    assert 签名结果.成功, 签名结果.错误说明
    (镜像项目录 / "镜像清单.json").write_text(
        json.dumps(签名结果.值, ensure_ascii=False), encoding="utf-8")
    return 签名结果.值


def 放置坏制品(镜像仓库: Path, 摘要: str, 成员表) -> None:
    """放置含非法成员的制品 tar 到镜像仓库（下载后解包失败）。"""
    制品路径 = 镜像仓库 / "docx提供者" / 摘要 / "制品.tar.gz"
    制品路径.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(制品路径, "w:gz") as 压缩包:
        for 成员名, 链接目标, 内容 in 成员表:
            信息 = tarfile.TarInfo(成员名)
            if 链接目标 is not None:
                信息.type = tarfile.SYMTYPE
                信息.linkname = 链接目标
                压缩包.addfile(信息)
            else:
                信息.size = len(内容 or b"")
                信息.mode = 0o644
                压缩包.addfile(信息, io.BytesIO(内容 or b""))


class Test镜像下载代理(unittest.TestCase):
    """代理配置生效/未配置直连/代理不可用（本地 HTTP 镜像 + 记录代理）。"""

    def setUp(self):
        self.临时 = Path(tempfile.mkdtemp(dir=受管临时根))
        self.addCleanup(清只读后删除树, self.临时, 忽略失败=真)
        self.私钥PEM, self.公钥PEM = _生成密钥对()
        self.镜像仓库 = self.临时 / "镜像仓库"
        self.镜像仓库.mkdir(parents=True)
        self.镜像服务器 = _启动镜像服务器(self.镜像仓库)
        镜像端口 = self.镜像服务器.server_address[1]
        self.镜像地址 = f"http://127.0.0.1:{镜像端口}"
        self.代理服务器 = _启动服务器(
            _记录代理处理器, 镜像地址=self.镜像地址)
        代理端口 = self.代理服务器.server_address[1]
        self.代理地址 = f"http://127.0.0.1:{代理端口}"
        _记录代理处理器.请求记录.clear()

    def tearDown(self):
        _关闭服务器(self.代理服务器)
        _关闭服务器(self.镜像服务器)

    def test_配置代理下载走代理(self):
        """配置 代理地址 → 清单与制品下载均经代理（地址来自配置）。"""
        摘要 = "代理摘要-0001"
        清单 = 构造镜像(self.镜像仓库, 摘要, self.私钥PEM)
        目标 = self.临时 / "解包目标"
        清单结果 = 获取镜像清单(self.镜像地址, "docx提供者", 摘要,
                                代理地址=self.代理地址)
        self.assertTrue(清单结果.成功, 清单结果.错误说明)
        下载结果 = 下载镜像制品(self.镜像地址, "docx提供者", 摘要, 目标,
                            代理地址=self.代理地址, 镜像清单=清单)
        self.assertTrue(下载结果.成功, 下载结果.错误说明)
        self.assertTrue((目标 / "bin" / "python3").is_file())
        self.assertEqual(
            {_路径尾(项) for 项 in _记录代理处理器.请求记录},
            {"镜像清单.json", "制品.tar.gz"})

    def test_未配置代理显式直连(self):
        """未配置代理 → 直连下载成功，代理零请求（不硬编码任何地址）。"""
        摘要 = "直连摘要-0002"
        清单 = 构造镜像(self.镜像仓库, 摘要, self.私钥PEM)
        目标 = self.临时 / "解包目标"
        结果 = 下载镜像制品(self.镜像地址, "docx提供者", 摘要, 目标,
                          镜像清单=清单)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertTrue((目标 / "site-packages" / "docx.py").is_file())
        self.assertEqual(_记录代理处理器.请求记录, [])

    def test_代理不可用下载失败(self):
        """代理不可达 → 镜像下载失败（不落半成品）。"""
        摘要 = "坏代理摘要-0003"
        构造镜像(self.镜像仓库, 摘要, self.私钥PEM)
        目标 = self.临时 / "解包目标"
        结果 = 下载镜像制品(
            self.镜像地址, "docx提供者", 摘要, 目标,
            代理地址=f"http://127.0.0.1:{_已关闭端口()}")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, 镜像下载失败)
        self.assertTrue(结果.错误说明)
        self.assertFalse(目标.exists())
        self.assertEqual(list(self.临时.glob(".制品下载_*")), [])

    def test_代理地址配置字段解析(self):
        """远程镜像配置 的 代理地址 字段解析；缺省为空。"""
        配置路径 = self.临时 / "远程镜像配置.json"
        配置路径.write_text(json.dumps({
            "启用": 真, "镜像地址": "http://镜像.example.com/环境制品",
            "代理地址": self.代理地址,
        }, ensure_ascii=False), encoding="utf-8")
        配置 = 读取远程镜像配置(配置路径)
        self.assertEqual(配置.代理地址, self.代理地址)
        self.assertEqual(配置.镜像地址, "http://镜像.example.com/环境制品")
        self.assertEqual(读取远程镜像配置().代理地址, "")


class Test镜像下载安全解包(unittest.TestCase):
    """解包防路径穿越/符号链接逃逸；文件清单复校验；失败无残留。"""

    def setUp(self):
        self.临时 = Path(tempfile.mkdtemp(dir=受管临时根))
        self.addCleanup(清只读后删除树, self.临时, 忽略失败=真)
        self.私钥PEM, self.公钥PEM = _生成密钥对()
        self.镜像仓库 = self.临时 / "镜像仓库"
        self.镜像仓库.mkdir(parents=True)
        self.镜像服务器 = _启动镜像服务器(self.镜像仓库)
        端口 = self.镜像服务器.server_address[1]
        self.镜像地址 = f"http://127.0.0.1:{端口}"

    def tearDown(self):
        _关闭服务器(self.镜像服务器)

    def test_路径穿越拒绝(self):
        """tar 含 .. 穿越成员 → 拒绝（镜像下载失败），不落半成品。"""
        摘要 = "穿越摘要-0011"
        放置坏制品(self.镜像仓库, 摘要, [("../逃逸.txt", None, "逃逸".encode("utf-8"))])
        目标 = self.临时 / "解包目标"
        结果 = 下载镜像制品(self.镜像地址, "docx提供者", 摘要, 目标)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, 镜像下载失败)
        self.assertIn("非法路径", 结果.错误说明)
        self.assertFalse(目标.exists())
        self.assertEqual(list(self.临时.glob(".制品下载_*")), [])
        # 逃逸文件不得出现在目标目录外
        self.assertFalse((self.临时 / "逃逸.txt").exists())

    def test_绝对路径拒绝(self):
        摘要 = "绝对摘要-0012"
        放置坏制品(self.镜像仓库, 摘要, [("/绝对.txt", None, "绝对".encode("utf-8"))])
        目标 = self.临时 / "解包目标"
        结果 = 下载镜像制品(self.镜像地址, "docx提供者", 摘要, 目标)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, 镜像下载失败)
        self.assertFalse(目标.exists())
        self.assertFalse((self.临时 / "绝对.txt").exists())

    def test_符号链接逃逸拒绝(self):
        """tar 符号链接指向解包根外 → 拒绝（相对与绝对链接均拦截）。"""
        摘要 = "链接摘要-0013"
        放置坏制品(self.镜像仓库, 摘要, [
            ("bin/链接", "../../../../../../../../etc/passwd", None)])
        目标 = self.临时 / "解包目标"
        结果 = 下载镜像制品(self.镜像地址, "docx提供者", 摘要, 目标)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, 镜像下载失败)
        self.assertIn("链接", 结果.错误说明)
        self.assertFalse(目标.exists())
        # 绝对链接同样拒绝
        摘要二 = "链接摘要-0014"
        放置坏制品(self.镜像仓库, 摘要二, [("bin/链接", "/etc/passwd", None)])
        结果二 = 下载镜像制品(self.镜像地址, "docx提供者", 摘要二,
                            self.临时 / "解包目标二")
        self.assertFalse(结果二.成功)
        self.assertEqual(结果二.错误码, 镜像下载失败)

    def test_文件清单摘要不符拒绝(self):
        """镜像清单声明 文件清单摘要 与解包内容不符 → 拒绝（防半成品）。"""
        摘要 = "复校验摘要-0015"
        构造镜像(self.镜像仓库, 摘要, self.私钥PEM,
                  清单覆盖={"文件清单摘要": "错" * 16})
        目标 = self.临时 / "解包目标"
        结果 = 下载镜像制品(self.镜像地址, "docx提供者", 摘要, 目标,
                          镜像清单=json.loads(
                              (self.镜像仓库 / "docx提供者" / 摘要
                               / "镜像清单.json").read_text(encoding="utf-8")))
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, 镜像下载失败)
        self.assertIn("文件清单摘要复校验失败", 结果.错误说明)
        self.assertFalse(目标.exists())

    def test_文件清单摘要匹配通过(self):
        """文件清单摘要一致 → 解包后复校验通过，正常落盘。"""
        摘要 = "复校验摘要-0016"
        清单 = 构造镜像(self.镜像仓库, 摘要, self.私钥PEM,
                       含文件清单摘要=真)
        目标 = self.临时 / "解包目标"
        结果 = 下载镜像制品(self.镜像地址, "docx提供者", 摘要, 目标,
                          镜像清单=清单)
        self.assertTrue(结果.成功, 结果.错误说明)
        self.assertTrue((目标 / "bin" / "python3").is_file())
        self.assertEqual(list(self.临时.glob(".制品下载_*")), [])


class Test镜像原子落盘(unittest.TestCase):
    """原子落盘：fsync + os.replace；成功可读；失败无残留。"""

    def setUp(self):
        self.临时 = Path(tempfile.mkdtemp(dir=受管临时根))
        self.addCleanup(清只读后删除树, self.临时, 忽略失败=真)

    def test_原子落盘成功可读(self):
        临时目录 = self.临时 / "落盘临时"
        (临时目录 / "bin").mkdir(parents=True)
        (临时目录 / "bin" / "python3").write_text("#!/bin/sh\nexit 0\n")
        目标 = self.临时 / "落盘目标"
        原子落盘(临时目录, 目标)
        self.assertTrue((目标 / "bin" / "python3").is_file())
        self.assertEqual((目标 / "bin" / "python3").read_text(),
                         "#!/bin/sh\nexit 0\n")
        self.assertFalse(临时目录.exists())  # 改名后临时目录消失

    def test_原子落盘失败无残留(self):
        """临时目录不存在（半成品）→ OSError，目标不出现。"""
        目标 = self.临时 / "落盘目标"
        with self.assertRaises(OSError):
            原子落盘(self.临时 / "不存在的临时目录", 目标)
        self.assertFalse(目标.exists())

    def test_半成品清理解包失败无残留(self):
        """解包失败后：临时 .tar.gz 与解包目标全部清理（无半成品）。"""
        摘要 = "清理摘要-0021"
        坏制品路径 = self.临时 / "坏制品.tar.gz"
        with tarfile.open(坏制品路径, "w:gz") as 压缩包:
            信息 = tarfile.TarInfo("../逃逸.txt")
            信息.size = 3
            压缩包.addfile(信息, io.BytesIO(b"abc"))
        目标 = self.临时 / "解包目标"
        目标.mkdir(parents=True, exist_ok=True)
        临时制品文件 = self.临时 / f".制品下载_{摘要[:8]}.tar.gz"
        临时制品文件.write_bytes(坏制品路径.read_bytes())
        结果 = 下载镜像制品(
            "file://" + str(self.临时 / "无此镜像"), "docx提供者", 摘要, 目标)
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, 镜像下载失败)
        self.assertFalse(临时制品文件.exists())
        self.assertFalse(目标.exists())


class Test镜像下载端到端回退(unittest.TestCase):
    """端到端：走代理命中/代理不可用回退/复校验失败回退（不落半成品）。"""

    def setUp(self):
        self.临时 = Path(tempfile.mkdtemp(dir=受管临时根))
        self.addCleanup(清只读后删除树, self.临时, 忽略失败=真)
        (self.临时 / "支持库").mkdir()
        (self.临时 / "模块库").mkdir()
        self.私钥PEM, self.公钥PEM = _生成密钥对()
        self.配置路径 = self.临时 / "工程缓存" / "远程镜像配置.json"
        self.镜像仓库 = self.临时 / "镜像仓库"
        self.镜像仓库.mkdir()
        self.镜像服务器 = _启动镜像服务器(self.镜像仓库)
        镜像端口 = self.镜像服务器.server_address[1]
        self.镜像地址 = f"http://127.0.0.1:{镜像端口}"
        self.代理服务器 = _启动服务器(
            _记录代理处理器, 镜像地址=self.镜像地址)
        代理端口 = self.代理服务器.server_address[1]
        self.代理地址 = f"http://127.0.0.1:{代理端口}"
        _记录代理处理器.请求记录.clear()

    def tearDown(self):
        _关闭服务器(self.代理服务器)
        _关闭服务器(self.镜像服务器)

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

    def 写镜像配置(self, 代理地址: str = "") -> None:
        self.配置路径.parent.mkdir(parents=True, exist_ok=True)
        self.配置路径.write_text(json.dumps({
            "启用": 真, "镜像地址": self.镜像地址, "信任指纹": 测试指纹,
            "公钥PEM": self.公钥PEM, "代理地址": 代理地址,
        }, ensure_ascii=False), encoding="utf-8")

    def 锁文件摘要(self, 锁文件: Path) -> str:
        return hashlib.sha256(锁文件.read_bytes()).hexdigest()[:16]

    def 构造匹配镜像(self, 提供者: Path, 摘要: str,
                     清单覆盖: dict | None = None) -> None:
        """构造与本地期望匹配的签名镜像（依赖锁摘要=输入哈希）。"""
        return 构造镜像(self.镜像仓库, 摘要, self.私钥PEM, 清单覆盖={
            "依赖锁摘要": self.锁文件摘要(提供者 / "依赖锁.json"),
            **(清单覆盖 or {}),
        })

    def test_端到端走代理命中无半成品(self):
        """配置代理 + 全部匹配 → 镜像命中（清单/制品均经代理），无半成品。"""
        锁 = {"包": [
            {"名称": "python-docx", "版本": "1.2.0", "模块名": "docx"}]}
        提供者 = self.新提供者(锁=锁)
        摘要 = 计算环境摘要(锁, 提供者.name)
        self.构造匹配镜像(提供者, 摘要)
        self.写镜像配置(代理地址=self.代理地址)
        with self.注入构建() as 假venv:
            结果 = 确保环境(提供者)
        self.assertTrue(结果.成功)
        self.assertEqual(假venv.调用次数, 0)  # 未走本地构建
        目标 = 环境目录(提供者, 摘要)
        self.assertTrue((目标 / "bin" / "python3").is_file())
        self.assertTrue((目标 / "site-packages" / "docx.py").is_file())
        证据 = self.证据行()
        self.assertEqual([行["类型"] for 行 in 证据], ["镜像命中"])
        # 确实经代理获取清单与制品
        self.assertEqual(
            {_路径尾(项) for 项 in _记录代理处理器.请求记录},
            {"镜像清单.json", "制品.tar.gz"})
        # 不落半成品
        self.assertEqual(list(self.临时.glob(".镜像中_*")), [])
        self.assertEqual(list(self.临时.glob(".制品下载_*")), [])

    def test_端到端代理不可用回退本地构建(self):
        """代理不可达 → 明确错误码 + 回退本地构建，不落半成品。"""
        提供者 = self.新提供者(锁={"包": [
            {"名称": "python-docx", "版本": "1.2.0", "模块名": "docx"}]})
        self.写镜像配置(
            代理地址=f"http://127.0.0.1:{_已关闭端口()}")
        with self.注入构建() as 假venv:
            结果 = 确保环境(提供者)
        self.assertTrue(结果.成功)
        self.assertEqual(假venv.调用次数, 1)  # 回退本地构建成功
        证据 = self.证据行()
        self.assertEqual([行["类型"] for 行 in 证据], ["失败", "重建"])
        self.assertIn(证据[0]["错误码"], {镜像不可用, 镜像下载失败})
        self.assertTrue(证据[0]["错误说明"])
        self.assertEqual(list(self.临时.glob(".镜像中_*")), [])
        self.assertEqual(list(self.临时.glob(".制品下载_*")), [])

    def test_端到端文件清单摘要不符回退本地构建(self):
        """文件清单复校验失败 → 镜像下载失败 + 回退本地构建。"""
        提供者 = self.新提供者(锁={"包": [
            {"名称": "python-docx", "版本": "1.2.0", "模块名": "docx"}]})
        摘要 = 计算环境摘要({"包": [
            {"名称": "python-docx", "版本": "1.2.0", "模块名": "docx"}]},
            提供者.name)
        self.构造匹配镜像(提供者, 摘要,
                          清单覆盖={"文件清单摘要": "错" * 16})
        self.写镜像配置()
        with self.注入构建() as 假venv:
            结果 = 确保环境(提供者)
        self.assertTrue(结果.成功)
        self.assertEqual(假venv.调用次数, 1)
        证据 = self.证据行()
        self.assertEqual([行["类型"] for 行 in 证据], ["失败", "重建"])
        self.assertEqual(证据[0]["错误码"], 镜像下载失败)
        self.assertIn("文件清单摘要复校验失败", 证据[0]["错误说明"])
        self.assertEqual(list(self.临时.glob(".镜像中_*")), [])


if __name__ == "__main__":
    unittest.main()
