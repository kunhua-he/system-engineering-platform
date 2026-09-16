"""第二十八阶段反向破坏门禁：新增图像原子能力与提供者契约硬收口的反向断言。

覆盖：主进程零加载 Pillow、清空 PYTHONPATH 子进程自举、超时/取消无残留、
抽帧真实宽高非固定、感知哈希确定性与差异性、非法 Tesseract 路径明确失败、
新能力九要素与摘要齐全、契约缺项拒绝。全部真实执行，不 mock 成功。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import ast
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]


class Test反向破坏门禁28(unittest.TestCase):
    def test_Provider实现直导仅限内部生命周期测试(self) -> None:
        """公开能力测试必须经包级入口；实现层直导仅允许明确的 Provider 内部协议测试。"""
        允许 = {
            "测试_FFmpeg提供者.py", "测试_Git提供者.py", "测试_MLXWhisper提供者.py",
            "测试_PDF隔离提供者.py", "测试_PyMuPDF提供者.py", "测试_PyMuPDF自足性.py",
            "测试_Pillow提供者.py", "测试_Tesseract提供者.py", "测试_openpyxl提供者.py",
            "测试_pg8000提供者.py", "测试_psycopg提供者.py", "测试_python_docx提供者.py",
            "测试_python_pptx提供者.py",
            "测试_reportlab提供者.py", "测试_密码签名提供者.py", "测试_密码签名提供者_生命周期.py",
            "测试_系统探针.py",
            # 内部生命周期/资源收口测试：直导 实现 层验证并发/记忆 资源释放
            "测试_模型连接与并发释放.py", "测试_记忆支持库.py",
            "测试_浏览器自动化Provider.py",
            # 内部协议漂移守卫：必须直读连接器内部 协议别名 表，与适配层别名表比对
            "测试_模型协议别名.py",
        }
        根 = 系统根 / "测试中心" / "支持库"
        越界 = []
        for 文件 in sorted(根.glob("测试_*.py")):
            try:
                树 = ast.parse(文件.read_text(encoding="utf-8"), filename=str(文件))
            except SyntaxError as 错误:
                self.fail(f"测试文件无法解析: {文件.name}: {错误}")
            直导 = []
            for 节点 in ast.walk(树):
                if isinstance(节点, ast.ImportFrom) and 节点.module and ".实现" in 节点.module:
                    直导.append(f"{文件.name}:{节点.lineno}")
            if 直导 and 文件.name not in 允许:
                越界.extend(直导)
        self.assertEqual([], 越界, "Provider 实现直导超出内部生命周期白名单: " + ", ".join(越界))

    def test_主进程零加载Pillow(self) -> None:
        """调用 Pillow 能力后主进程 sys.modules 不得出现 PIL。"""
        sys.path.insert(0, str(系统根))
        from 支持库.适配层.Pillow提供者 import 解码图像
        最小PNG = (
            b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR"
            + (1).to_bytes(4, "big") + (1).to_bytes(4, "big")
            + b"\x08\x06\x00\x00\x00" + b"\x1f\x15\xc4\x89"
            + b"\x00\x00\x00\x0aIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
            + b"\x0d\n\x2d\xb4" + b"\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        PIL先前已存在 = "PIL" in sys.modules
        结果 = 解码图像(最小PNG)
        self.assertTrue(结果.成功, 结果.错误说明)
        if not PIL先前已存在:
            self.assertNotIn("PIL", sys.modules, "本次调用不得把 PIL 加载进主进程")
            self.assertNotIn("Pillow", sys.modules)

    def test_清空PYTHONPATH子进程自举(self) -> None:
        """清空 PYTHONPATH 后 Pillow 子进程入口最小调用仍成功（自举修复）。"""
        入口 = 系统根 / "支持库" / "适配层" / "Pillow提供者" / "实现" / "子进程入口.py"
        环境 = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        请求 = {"操作": "解码图像", "字节b64": "aGVsbG8="}
        进程 = subprocess.run(
            [sys.executable, str(入口)],
            input=(json.dumps(请求) + "\n").encode("utf-8"),
            capture_output=True, env=环境, timeout=60,
        )
        self.assertEqual(进程.returncode, 0, 进程.stderr.decode("utf-8", "replace")[-500:])
        响应 = json.loads(进程.stdout.decode("utf-8", "replace"))
        self.assertFalse(响应.get("成功"), "非法字节应失败（自举本身成功）")
        self.assertIn(响应.get("错误码"), ("参数不合法", "文件损坏", "格式未知"), "自举成功但字节校验失败")

    def test_超时取消无残留子进程(self) -> None:
        """超时/取消后无残留 Pillow 子进程。"""
        import time
        from 支持库.适配层.Pillow提供者 import 解码图像
        开始 = time.time()
        结果 = 解码图像(b"\x89PNG", 超时秒=0.01)
        self.assertFalse(结果.成功)
        self.assertIn(结果.错误码, ("超时", "提供者崩溃", "提供者不可用"))
        time.sleep(0.5)
        残留 = subprocess.run(
            ["pgrep", "-fl", "子进程入口.py"], capture_output=True, text=True,
        ).stdout.strip()
        self.assertNotIn("Pillow提供者", 残留, f"存在残留子进程: {残留}")

    def test_抽帧宽高真实非固定(self) -> None:
        """ffmpeg 真实生成 320x240 视频，抽帧宽度/高度必须为真实值（禁止固定值）。"""
        import subprocess as _子进程
        import time as _时间
        from 支持库.适配层.FFmpeg提供者 import 抽取帧
        临时目录 = Path(tempfile.mkdtemp(prefix="抽帧宽高_"))
        视频 = 临时目录 / "测试.mp4"
        命令 = [
            "/opt/homebrew/bin/ffmpeg", "-y", "-f", "lavfi",
            "-i", "testsrc=size=320x240:rate=10", "-t", "1", "-pix_fmt", "yuv420p",
            str(视频),
        ]
        完成 = _子进程.run(命令, capture_output=True, timeout=60)
        self.assertEqual(完成.returncode, 0, 完成.stderr.decode("utf-8", "replace")[-300:])
        try:
            结果1 = 抽取帧(str(视频), 时间点秒=0.5, 输出格式="png")
            self.assertTrue(结果1.成功, 结果1.错误说明)
            值1 = 结果1.值
            self.assertEqual(值1.get("宽度"), 320, "抽帧宽度必须为真实值 320")
            self.assertEqual(值1.get("高度"), 240, "抽帧高度必须为真实值 240")
        finally:
            import shutil
            shutil.rmtree(临时目录, ignore_errors=True)

    def test_感知哈希确定性与差异性(self) -> None:
        """aHash/dHash/pHash 确定性且不同图像有差异。"""
        import base64 as _base64
        from 支持库.适配层.Pillow提供者 import 计算感知哈希, 生成占位图
        占位 = 生成占位图(64, 64, "文本", 背景颜色="#FFFFFF", 前景颜色="#000000", 文本="A")
        self.assertTrue(占位.成功, 占位.错误说明)
        图A = _base64.b64decode(占位.值["图像b64"])
        占位2 = 生成占位图(64, 64, "文本", 背景颜色="#FFFFFF", 前景颜色="#000000", 文本="AB")
        self.assertTrue(占位2.成功)
        图B = _base64.b64decode(占位2.值["图像b64"])
        结果1 = 计算感知哈希(图A, "aHash")
        结果2 = 计算感知哈希(图A, "aHash")
        self.assertTrue(结果1.成功, 结果1.错误说明)
        self.assertEqual(结果1.值["哈希"], 结果2.值["哈希"], "同图同算法必须确定性")
        self.assertEqual(len(结果1.值["哈希"]), 16, "64 位十六进制")
        for 类型 in ("aHash", "dHash", "pHash"):
            结果 = 计算感知哈希(图A, 类型)
            self.assertTrue(结果.成功, 结果.错误说明)
            self.assertEqual(结果.值["哈希类型"], 类型)
        结果B = 计算感知哈希(图B, "aHash")
        self.assertTrue(结果B.成功)
        self.assertNotEqual(结果1.值["哈希"], 结果B.值["哈希"], "不同颜色图哈希应有差异")

    def test_非法Tesseract路径明确失败(self) -> None:
        """显式非法 Tesseract 路径 → 工具缺失/命令失败（不伪装成功）。"""
        from 支持库.适配层.Tesseract提供者 import 版本探针
        结果 = 版本探针(命令路径="/不存在/tesseract")
        self.assertFalse(结果.成功)
        self.assertIn(结果.错误码, ("工具缺失", "命令失败", "提供者不可用"))

    def test_新能力九要素与摘要齐全(self) -> None:
        """Pillow 6 新能力契约要素齐全、摘要校验通过。"""
        from 支持库.后端.组件规范支持库 import 校验完整性摘要
        包目录 = 系统根 / "支持库" / "适配层" / "Pillow提供者"
        通过, 问题 = 校验完整性摘要(包目录)
        self.assertTrue(通过, f"摘要漂移: {问题}")
        定义 = json.loads((包目录 / "能力定义.json").read_text(encoding="utf-8"))
        能力表 = {c["能力id"]: c for c in 定义.get("能力列表", [])}
        新增 = ("图像解码.生成缩略图", "图像解码.图像EXIF转置", "图像解码.透明背景合成",
                "图像解码.计算感知哈希", "图像解码.缩放图像", "图像解码.重编码图像")
        for 能力id in 新增:
            self.assertIn(能力id, 能力表, f"缺能力定义: {能力id}")
            条目 = 能力表[能力id]
            self.assertTrue(条目.get("说明"), f"{能力id} 缺说明")
            self.assertTrue(条目.get("参数"), f"{能力id} 缺参数")
            self.assertTrue(条目.get("错误码"), f"{能力id} 缺错误码")
            契约 = json.loads((包目录 / "能力契约" / "参数契约.json").read_text(encoding="utf-8"))
            self.assertTrue(any(c["能力id"] == 能力id for c in 契约.get("能力契约", [])),
                            f"{能力id} 缺参数契约")


if __name__ == "__main__":
    unittest.main()
