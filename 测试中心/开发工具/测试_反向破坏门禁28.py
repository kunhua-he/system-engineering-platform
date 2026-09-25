"""第二十八阶段反向破坏门禁：新增图像原子能力与提供者契约硬收口的反向断言。

覆盖：主进程零加载 Pillow、清空 PYTHONPATH 子进程自举、超时/取消无残留、
抽帧真实宽高非固定、感知哈希确定性与差异性、非法 Tesseract 路径明确失败。全部真实执行，不 mock 成功。

★ 2026-09-25 按「不保留旧腿」删掉原用例 `test_新能力九要素与摘要齐全`
（它断言 `支持库/适配层/Pillow提供者/能力定义.json` 的 `能力列表` 含 6 条 `图像解码.*`）。
裁决依据：`开发文档/分析/批R单据_R28_T1能力面合并_20260924.md` §一/§三判据 1 ——
华哥裁决①「适配层孪生能力面删、保留后端腿 id」，Pillow 9 条能力面**已删**（`能力列表` → `[]`），
同名能力面收归后端腿 `支持库/后端/图像处理支持库/图像解码`（对外 id 不变，生产调用点零改动）。
故该用例测的是一个**已被裁决删除的能力面**：断言对象不存在了，留着重写只会变成假红。
本包**实现**（`实现/` 下 9 个函数）按 R-28 §二「明确未碰」保留 ⇒ 其余 6 条用例照旧直调实现，
一个都没删、也没放宽。
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
            # 私有档案/私有写回入口：被测链路只在 实现 层取用「未注册的内部组合函数」，
            # 无包级入口可替代；转换与压缩本身仍是真实执行，不做任何打桩假成功。
            # - 测试_上下文压缩写回往返.py：取 上下文压缩.实现.压缩会话（未注册的内部组合入口）
            # - 测试_文字文档.py / 测试_演示文稿.py：只把 soffice 可执行入口换成私有档案包装
            "测试_上下文压缩写回往返.py", "测试_文字文档.py", "测试_演示文稿.py",
            # ── 2026-09-25 补登记（本用例的**白名单落后于仓库**，不是新开口子）────────────
            # 现场：下列 11 个测试文件直导 实现 层，但白名单自 2026-09-17（071de14f）之后
            # 未再随新增测试同步 ⇒ 本用例从 2026-09-19 起恒红（本仓「判据在≠判据接线」的老坑）。
            # 补登记口径**逐条沿用本文件既有的四类**（Provider 内部协议 / 内部生命周期与资源收口 /
            # 内部协议漂移守卫 / 私有档案与私有写回入口），不放宽判据本身：
            # `assertEqual([], 越界)` 一字未动，只是把「谁属于内部协议测试」这个事实补齐。
            # · Provider 内部协议测试（同名能力面已按批R·R-28 收归后端腿，本包只剩实现）：
            "测试_LibreOffice双腿行为差异.py",   # 直读 实现.文档转换，比对前后端两条腿的行为差异
            "测试_SwiftCompiler提供者.py",       # 直读 实现.Swift工具（子进程边界的私有协议）
            "测试_pdfplumber提供者.py",          # 直读 实现.PDF文本表格（第三方解析器私有协议）
            "测试_转写跨平台后端.py",            # 直读 实现.子进程解析，比对适配层/后端两条腿
            # · 私有实现件（无包级入口可替代；被测行为本身在 实现 层）：
            "测试_后端原子支持库.py",            # 直读 实现.时间日期（实现别名，非注册能力）
            "测试_文本补丁.py",                  # 直读 实现.文本补丁（私有原子写腿）
            "测试_路径安全.py",                  # 直读 实现.路径安全.校验路径（同动作唯一腿的内部件）
            "测试_隔离腿唯一化收口.py",          # 直读 实现.临时文件（私有子模块，收口判据要读它）
            # · 内部协议/口径漂移守卫（必须读实现内部表或私有件才能比对）：
            "测试_模型连接器归一化.py",          # 直读 实现.响应归一化（内部归一表）
            "测试_模型连接器环境配置.py",        # 直读 实现.环境配置（内部模块本体成员）
            "测试_项目文档支持库_集合级.py",      # 直读 实现.集合扫描 的私有件 _归一豁免/_被豁免
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


if __name__ == "__main__":
    unittest.main()
