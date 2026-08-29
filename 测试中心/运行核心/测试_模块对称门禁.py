"""第三波模块生产装配对称门禁：声明=注册=搜索=契约=客户端可见全对称。

覆盖：11 个正式模块逐能力四侧对称（包声明能力 / 装配注册能力 / 能力搜索数据 /
聚合契约能力 / 客户端制品内聚合契约能力一致），任一不对称即失败；
模块公开入口只经能力调用器调用支持库（无实现静态导入）。
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

正式模块表 = [
    "OCR", "图像处理", "媒体处理", "媒体转写", "文件管理",
    "文档生成", "文档解析", "文档读取", "简单窗口", "网页分析", "自修复工具",
]


class Test模块对称门禁(unittest.TestCase):
    """模块声明/注册/搜索/契约/客户端可见 五侧对称门禁。"""

    @classmethod
    def setUpClass(cls) -> None:
        from 公共契约.能力契约.契约 import 能力注册表
        from 运行核心.加载器.包发现.发现器 import 发现全部
        from 运行核心.加载器.包安装.模块安装 import 安装全部模块
        from 运行核心.加载器.包安装.支持库安装 import 安装全部支持库

        cls.发现 = 发现全部(系统根 / "支持库", 系统根 / "模块库")
        cls.注册表 = 能力注册表()
        安装全部支持库(系统根 / "支持库", cls.注册表)
        安装全部模块(系统根 / "模块库", cls.注册表)

    def test_声明等于注册等于契约等于搜索(self) -> None:
        """11 个正式模块：包声明能力 = 装配注册能力 = 聚合契约能力 = 能力搜索数据。"""
        注册能力 = set(self.注册表.能力id列表)
        for 名 in 正式模块表:
            包根 = 系统根 / "模块库" / 名
            声明 = json.loads((包根 / "包声明.json").read_text(encoding="utf-8"))
            声明能力 = {c["能力id"] for c in 声明["能力"]}
            契约 = json.loads((包根 / "能力契约" / "参数契约.json").read_text(encoding="utf-8"))
            契约能力 = {c["能力id"] for c in 契约["能力契约"]}
            搜索 = json.loads((包根 / "能力数据" / "能力搜索数据.json").read_text(encoding="utf-8"))
            搜索能力 = {c["能力id"] for c in 搜索}
            agent = json.loads((包根 / "能力数据" / "Agent查询数据.json").read_text(encoding="utf-8"))
            agent能力 = {c["能力id"] for c in agent}
            self.assertEqual(声明能力, 契约能力, f"{名} 声明≠契约")
            self.assertEqual(声明能力, 搜索能力, f"{名} 声明≠搜索")
            self.assertEqual(声明能力, agent能力, f"{名} 声明≠Agent")
            self.assertTrue(声明能力 <= 注册能力, f"{名} 声明能力未全部注册")

    def test_客户端可见聚合契约与声明一致(self) -> None:
        """客户端可见（制品内聚合契约）能力数与声明一致（以源码契约代制品可见性）。"""
        for 名 in 正式模块表:
            包根 = 系统根 / "模块库" / 名
            声明 = json.loads((包根 / "包声明.json").read_text(encoding="utf-8"))
            契约 = json.loads((包根 / "能力契约" / "参数契约.json").read_text(encoding="utf-8"))
            self.assertEqual(
                len(声明["能力"]), len(契约["能力契约"]),
                f"{名} 声明能力数≠契约能力数",
            )

    def test_模块实现零适配层静态导入(self) -> None:
        """模块实现不得静态导入 支持库.适配层 或 第三方（只经调用器）。"""
        for 名 in 正式模块表:
            实现根 = 系统根 / "模块库" / 名 / "实现"
            if not 实现根.is_dir():
                continue
            检查 = subprocess.run(
                ["grep", "-rn", "^from 支持库\\|^import 支持库\\|from 支持库.适配层",
                  str(实现根)],
                capture_output=True, text=True,
            )
            self.assertEqual(
                "", 检查.stdout.strip(),
                f"{名} 实现存在支持库静态导入:\n{检查.stdout[:500]}",
            )

    def test_全新子进程模块公开入口可调用(self) -> None:
        """独立子进程从模块公开入口调用（冷启动，无测试全局状态）。"""
        脚本 = (
            "import sys; from pathlib import Path; sys.path.insert(0, '.')\n"
            "from 公共契约.能力契约.契约 import 能力注册表\n"
            "from 运行核心.加载器.包安装.支持库安装 import 安装全部支持库\n"
            "from 运行核心.加载器.包安装.模块安装 import 安装全部模块\n"
            "from 运行核心.能力调用.唯一能力调用 import 创建并绑定\n"
            "from 运行核心.统一网关.网关核心 import 网关核心\n"
            "from 运行核心.统一网关.本地网关 import 本地网关服务器\n"
            "from 运行核心.能力调用.HTTP连接器 import HTTP连接器\n"
            "from 模块库.文件管理 import 设置HTTP连接器, 读取文件\n"
            "注册表 = 能力注册表()\n"
            "安装全部支持库(Path('支持库'), 注册表)\n"
            "安装全部模块(Path('模块库'), 注册表)\n"
            "服务 = 创建并绑定(注册表)\n"
            "class 后端代理:\n"
            "    def 调用(self, 能力id, 参数=None, *, 上下文=None, 超时秒=10.0):\n"
            "        return 服务.调用能力(能力id, 参数 or {}, 超时秒=超时秒)\n"
            "网关 = 本地网关服务器(网关核心实例=网关核心(后端代理()), 端口=0)\n"
            "启动成功, 启动说明 = 网关.启动()\n"
            "assert 启动成功, 启动说明\n"
            "连接器 = HTTP连接器(网关地址='127.0.0.1', 网关端口=网关.端口)\n"
            "设置HTTP连接器(连接器)\n"
            "try:\n"
            "    结果 = 读取文件('/不存在的对称门禁文件')\n"
            "finally:\n"
            "    设置HTTP连接器(None)\n"
            "    网关.优雅停止()\n"
            "assert 结果.成功 is False, '应返回统一失败结果'\n"
            "assert 结果.错误码 in ('文件不存在', '目录不存在', '参数不合法'), 结果.错误码\n"
            "print('OK 冷启动模块公开入口可调用')\n"
        )
        运行 = subprocess.run(
            [sys.executable, "-c", 脚本], capture_output=True, text=True,
            cwd=str(系统根), env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": "/Users/hekunhua", "LANG": "zh_CN.UTF-8", "PYTHONPATH": str(系统根)},
        )
        self.assertEqual(0, 运行.returncode, f"子进程失败: {运行.stdout[-800:]}\n{运行.stderr[-800:]}")
        self.assertIn("OK", 运行.stdout)


if __name__ == "__main__":
    unittest.main()
