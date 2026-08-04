"""第三十阶段 C4 冷启动生产链反向门禁测试。

冷启动定义（S0 生产事实冻结）：全新 Python 进程、清空项目源码 PYTHONPATH、
无测试预注册、无历史全局单例，只使用已安装制品与声明配置，装配→注册→
调用全链路成立。任何经 sys.path 拼接、包 __path__、源码目录、测试预注册、
直接导入 实现/ 或全局状态残留跑通的链路均不算完成。

本测试全部场景都在独立 python3.14 子进程中真实执行（冷启动脚本.py）：
- 本测试文件只做纯文件系统构造（复制真实制品/写合成声明）与子进程编排，
  不 import 生产装配入口、不导入 实现/ 目录、不把生产函数作为夹具注入。
- 子进程只经生产装配入口执行：装配系统 / 创建并绑定 / 获取能力调用器。
- 覆盖：未装配失败 / 装配后成功 / 重复装配幂等 / 装配失败回滚 /
  进程重启重新装配 / 重复能力冲突 / 版本锁漂移拒绝 / 旧制品可回滚。
- 反向破坏：删除 包声明/注册入口/契约/锁/实现 任一项，生产链必须真实失败
  （删契约经 S0.4 组件合规 13/13 权威门禁证明，删锁经提供者依赖锁
  fail-closed 强制校验证明；运行时装配层的放行行为作为缺陷证据记录）。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
脚本路径 = Path(__file__).resolve().parent / "冷启动脚本.py"


def 干净环境() -> dict[str, str]:
    """子进程环境：清空工作区 PYTHONPATH 等，禁止继承测试全局状态。"""
    环境 = {
        k: v for k, v in os.environ.items()
        if k not in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP")
    }
    环境["PYTHONNOUSERSITE"] = "1"
    环境["PYTHONDONTWRITEBYTECODE"] = "1"
    return 环境


class 冷启动反向门禁基础(unittest.TestCase):
    """公共设施：临时暂存根（支持库+模块库）、子进程执行、合成包写入。"""

    子进程超时秒 = 120

    def setUp(self) -> None:
        self.临时根 = Path(tempfile.mkdtemp(prefix="冷启动门禁_"))
        self.根 = self.临时根 / "系统根"
        (self.根 / "支持库").mkdir(parents=True)
        (self.根 / "模块库").mkdir(parents=True)
        self.工作目录 = self.临时根 / "工作目录"
        self.工作目录.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.临时根, ignore_errors=True)

    def 运行脚本(self, *参数: str, 超时秒: int | None = None) -> dict:
        """在全新子进程中执行冷启动脚本，stdout 必须是单行 JSON。"""
        进程 = subprocess.run(
            [sys.executable, str(脚本路径), *参数],
            capture_output=True, env=干净环境(), cwd=str(self.工作目录),
            timeout=超时秒 or self.子进程超时秒, text=True, encoding="utf-8",
        )
        self.assertEqual(
            进程.returncode, 0,
            f"冷启动脚本退出码 {进程.returncode}：{进程.stderr[-800:]}",
        )
        return json.loads(进程.stdout)

    def 重置暂存(self) -> None:
        """重建空暂存根（支持库+模块库），保证各场景互不污染。"""
        shutil.rmtree(self.根, ignore_errors=True)
        (self.根 / "支持库").mkdir(parents=True)
        (self.根 / "模块库").mkdir(parents=True)

    def 复制真实制品(self) -> None:
        """复制已安装真实制品：文件系统/资源管理 支持库 + 文件管理 模块。

        另复制 运行核心 内部直接引用的 适配层 影子（系统探针/脱敏模式 模块
        与 密码签名提供者 包，去掉 包声明.json/依赖锁.json 使其不被发现装配），
        保证子进程内全部 支持库.* 导入都落在暂存制品上，不穿透到仓库。
        """
        self.重置暂存()
        支持库根 = 系统根 / "支持库"
        适配层影子 = self.根 / "支持库" / "适配层"
        适配层影子.mkdir(exist_ok=True)
        for 文件 in ("系统探针.py", "脱敏模式.py"):
            shutil.copy2(支持库根 / "适配层" / 文件, 适配层影子 / 文件)
        密码签名 = 支持库根 / "适配层" / "密码签名提供者"
        if 密码签名.is_dir():
            shutil.copytree(密码签名, 适配层影子 / "密码签名提供者")
            (适配层影子 / "密码签名提供者" / "包声明.json").unlink(missing_ok=True)
            (适配层影子 / "密码签名提供者" / "依赖锁.json").unlink(missing_ok=True)
            shutil.rmtree(适配层影子 / "密码签名提供者" / "__pycache__",
                           ignore_errors=True)
        模块库根 = 系统根 / "模块库"
        for 源, 目标 in (
            (支持库根 / "后端" / "文件系统", self.根 / "支持库" / "后端" / "文件系统"),
            (支持库根 / "后端" / "资源管理", self.根 / "支持库" / "后端" / "资源管理"),
            (模块库根 / "文件管理", self.根 / "模块库" / "文件管理"),
        ):
            shutil.copytree(源, 目标)
        shutil.copy2(支持库根 / "__init__.py", self.根 / "支持库" / "__init__.py")
        shutil.copy2(支持库根 / "后端" / "__init__.py", self.根 / "支持库" / "后端" / "__init__.py")
        shutil.copy2(模块库根 / "__init__.py", self.根 / "模块库" / "__init__.py")

    def 写合成支持库(
        self, 名称: str, 能力id: str, *,
        版本: str = "1.0.0", 注册能力id: str | None = None,
        依赖: list | None = None, 已废弃: bool = False, 返回值: str = "",
    ) -> Path:
        """写一份合成支持库（入口只注册 lambda 能力实现，无仓库孪生包）。"""
        目录 = self.根 / "支持库" / "适配层" / 名称
        目录.mkdir(parents=True, exist_ok=True)
        声明 = {
            "包id": f"支持库.适配层.{名称}", "名称": 名称, "类型": "支持库",
            "版本": 版本, "入口": "入口.py", "依赖": 依赖 or [],
            "能力": [{"能力id": 能力id, "名称": 名称}],
        }
        if 已废弃:
            声明["已废弃"] = True
        (目录 / "包声明.json").write_text(
            json.dumps(声明, ensure_ascii=False), encoding="utf-8")
        契约 = {
            "契约版本": "1.0.0",
            "能力契约": [{
                "能力id": 能力id, "版本": 版本, "说明": 名称,
                "参数": [], "返回": {"类型": "dict", "说明": "统一结果"},
                "错误码": [], "调用示例": "{}",
            }],
        }
        (目录 / "能力契约").mkdir(parents=True, exist_ok=True)
        (目录 / "能力契约" / "参数契约.json").write_text(
            json.dumps(契约, ensure_ascii=False), encoding="utf-8")
        from 运行核心.环境指纹 import 计算环境指纹
        指纹 = 计算环境指纹(含外部应用=False).详细信息
        系统名 = "macOS" if 指纹["os"] == "Darwin" else 指纹["os"]
        (目录 / "依赖锁.json").write_text(json.dumps({
            "包": [{"名称": "冷启动测试工具", "版本": "1.0.0",
                    "模块名": "冷启动测试工具", "来源": "外部应用"}],
            "提供者id": 名称, "直接依赖": [], "依赖闭包": [],
            "环境": {"Python": 指纹["python"], "操作系统": 系统名, "CPU": 指纹["架构"]},
        }, ensure_ascii=False), encoding="utf-8")
        返回值 = 返回值 or 名称
        (目录 / "入口.py").write_text(
            "from 公共契约.能力契约.契约 import 能力实现\n\n"
            "def 注册能力(注册表):\n"
            f"    注册表.注册(能力实现(\n"
            f"        能力id={注册能力id or 能力id!r}, 包id='支持库.适配层.{名称}',\n"
            f"        实现函数=lambda: {{'成功': True, '值': {返回值!r}}}))\n",
            encoding="utf-8")
        return 目录

    def 写合成实现包(self, 名称: str, 能力id: str, *, 带实现: bool = True) -> Path:
        """写一份入口导入 实现/ 文件的合成支持库（用于删实现破坏场景）。"""
        目录 = self.根 / "支持库" / "适配层" / 名称
        (目录 / "实现").mkdir(parents=True, exist_ok=True)
        (目录 / "__init__.py").write_text("", encoding="utf-8")
        (目录 / "实现" / "__init__.py").write_text("", encoding="utf-8")
        (目录 / "包声明.json").write_text(json.dumps({
            "包id": f"支持库.适配层.{名称}", "名称": 名称, "类型": "支持库",
            "版本": "1.0.0", "入口": "入口.py", "依赖": [],
            "能力": [{"能力id": 能力id, "名称": 名称}],
        }, ensure_ascii=False), encoding="utf-8")
        (目录 / "能力契约").mkdir(parents=True, exist_ok=True)
        (目录 / "能力契约" / "参数契约.json").write_text(json.dumps({
            "契约版本": "1.0.0",
            "能力契约": [{
                "能力id": 能力id, "版本": "1.0.0", "说明": 名称,
                "参数": [], "返回": {"类型": "dict", "说明": "统一结果"},
                "错误码": [], "调用示例": "{}",
            }],
        }, ensure_ascii=False), encoding="utf-8")
        from 运行核心.环境指纹 import 计算环境指纹
        指纹 = 计算环境指纹(含外部应用=False).详细信息
        系统名 = "macOS" if 指纹["os"] == "Darwin" else 指纹["os"]
        (目录 / "依赖锁.json").write_text(json.dumps({
            "包": [{"名称": "冷启动测试工具", "版本": "1.0.0",
                    "模块名": "冷启动测试工具", "来源": "外部应用"}],
            "提供者id": 名称, "直接依赖": [], "依赖闭包": [],
            "环境": {"Python": 指纹["python"], "操作系统": 系统名, "CPU": 指纹["架构"]},
        }, ensure_ascii=False), encoding="utf-8")
        (目录 / "入口.py").write_text(
            "from 支持库.适配层.{名}.实现.测试实现 import 能力\n\n"
            "from 公共契约.能力契约.契约 import 能力实现\n"
            "def 注册能力(注册表):\n"
            f"    注册表.注册(能力实现(\n"
            f"        能力id={能力id!r}, 包id='支持库.适配层.{名称}',\n"
            f"        实现函数=能力))\n".format(名=名称),
            encoding="utf-8")
        if 带实现:
            (目录 / "实现" / "测试实现.py").write_text(
                "def 能力():\n"
                f"    return {{'成功': True, '值': {名称!r}}}\n",
                encoding="utf-8")
        return 目录

    def 装配请求(self, *能力调用: tuple[str, dict]) -> str:
        return json.dumps({"能力表": [
            {"能力id": 能力id, "参数": 参数} for 能力id, 参数 in 能力调用
        ]}, ensure_ascii=False)


class Test冷启动子进程(冷启动反向门禁基础):
    """冷启动场景覆盖：全新进程、干净环境、只经生产装配入口。"""

    def test_未装配获取调用器失败(self) -> None:
        """全新进程未装配：获取能力调用器 必须明确失败（无预注册/无惰性钩子）。"""
        数据 = self.运行脚本("未装配")
        self.assertTrue(数据["失败"], "未装配时必须失败")
        self.assertIn("能力调用器未注入", 数据["错误"])

    def test_装配后调用成功且证据齐全(self) -> None:
        """全新进程冷启动：装配→注册→调用 全链路成立，支持库与模块都可调用。"""
        self.复制真实制品()
        写入路径 = self.根 / "冷启动输出.txt"
        请求 = self.装配请求(
            ("文件系统.写入文件", {"文件路径": str(写入路径), "内容": "冷启动成功", "编码": "utf-8"}),
            ("文件系统.判断存在", {"文件路径": str(写入路径)}),
            ("文件管理.写入文件", {"文件路径": str(写入路径), "内容": "模块链路成功"}),
            ("文件管理.读取文件", {"文件路径": str(写入路径)}),
        )
        数据 = self.运行脚本("装配", str(self.根), 请求)
        self.assertTrue(数据["装配成功"], str(数据["问题列表"]))
        self.assertGreaterEqual(数据["已注册能力数"], 30)
        self.assertEqual(数据["声明能力数"], 数据["已注册能力数"])
        self.assertTrue(数据["调用器可用"])
        结果表 = {项["能力id"]: 项 for 项 in 数据["调用结果表"]}
        # 支持库直接调用
        self.assertTrue(结果表["文件系统.写入文件"]["成功"])
        self.assertTrue(结果表["文件系统.判断存在"]["成功"])
        self.assertTrue(结果表["文件系统.判断存在"]["值"], "写入后应真实存在")
        # 模块经 获取能力调用器→注册表→支持库 的组合链路
        self.assertTrue(结果表["文件管理.写入文件"]["成功"])
        self.assertTrue(结果表["文件管理.读取文件"]["成功"])
        self.assertEqual(结果表["文件管理.读取文件"]["值"], "模块链路成功")
        # 完整调用证据（请求id/能力id/成功）
        for 项 in 数据["调用结果表"]:
            证据 = 项["证据"]
            self.assertTrue(证据.get("请求id"), f"{项['能力id']} 缺请求id")
            self.assertEqual(证据.get("能力id"), 项["能力id"])
            self.assertTrue(证据.get("成功"), f"{项['能力id']} 证据未记成功")

    def test_重复装配幂等(self) -> None:
        """同一注册表连续装配两次：结果一致、不冲突、装配后调用正常。"""
        self.复制真实制品()
        数据 = self.运行脚本("重复装配", str(self.根))
        self.assertTrue(数据["第一次"]["成功"], str(数据["第一次"]["问题列表"]))
        self.assertTrue(数据["第二次"]["成功"], str(数据["第二次"]["问题列表"]))
        self.assertEqual(
            数据["第一次"]["已注册能力数"], 数据["第二次"]["已注册能力数"],
            "重复装配能力数必须一致",
        )
        self.assertTrue(数据["重复装配后调用"]["成功"])

    def test_进程重启重新装配(self) -> None:
        """两个完全独立的子进程依次装配同一批制品：重启后重新装配仍然成立。"""
        self.复制真实制品()
        请求 = self.装配请求(
            ("文件系统.写入文件", {"文件路径": str(self.根 / "重启.txt"), "内容": "重启", "编码": "utf-8"}),
        )
        第一次 = self.运行脚本("装配", str(self.根), 请求)
        第二次 = self.运行脚本("装配", str(self.根), 请求)
        self.assertTrue(第一次["装配成功"], str(第一次["问题列表"]))
        self.assertTrue(第二次["装配成功"], str(第二次["问题列表"]))
        self.assertEqual(第一次["已注册能力数"], 第二次["已注册能力数"])
        self.assertTrue(第一次["调用结果表"][0]["成功"])
        self.assertTrue(第二次["调用结果表"][0]["成功"])

    def test_装配失败回滚不留半成品(self) -> None:
        """模块实现缺失 → 装配失败；生命周期回滚，失败模块能力不可用。

        缺陷证据（回传主协调）：装配失败后注册表未清空，支持库批次能力
        （文件系统.写入文件）仍可调用 —— 半装配残留，见 缺陷清单。
        """
        self.复制真实制品()
        (self.根 / "模块库" / "文件管理" / "实现" / "文件管理.py").unlink()
        请求 = self.装配请求(
            ("文件系统.写入文件", {"文件路径": str(self.根 / "残留.txt"), "内容": "残留", "编码": "utf-8"}),
            ("文件管理.写入文件", {"文件路径": str(self.根 / "半成品.txt"), "内容": "半成品"}),
        )
        数据 = self.运行脚本("装配", str(self.根), 请求)
        self.assertFalse(数据["装配成功"], "实现缺失必须装配失败")
        self.assertTrue(
            any("装配失败" in 问题 for 问题 in 数据["问题列表"]),
            str(数据["问题列表"]),
        )
        self.assertTrue(
            any(记录["操作名称"] == "回滚" for 记录 in 数据["生命周期记录"]),
            "装配失败必须产生回滚生命周期记录",
        )
        结果表 = {项["能力id"]: 项 for 项 in 数据["调用结果表"]}
        # 失败模块的能力不可用（半装配对调用方不可见）
        self.assertFalse(结果表["文件管理.写入文件"]["成功"])
        self.assertEqual(结果表["文件管理.写入文件"]["错误码"], "能力不存在")
        # 生产修复验证：装配失败后注册表恢复装配前状态，支持库能力同样不可残留
        self.assertFalse(结果表["文件系统.写入文件"]["成功"],
                         "装配失败后支持库能力必须不可调用（零半装配）")
        self.assertEqual(结果表["文件系统.写入文件"]["错误码"], "能力不存在")

    def test_重复能力冲突被拒绝(self) -> None:
        """重复能力冲突：声明级（发现器）与注册级（注册表）都必须拒绝。"""
        # 注册级：两个包声明不同能力，但注册同一能力 id → 注册表拒绝
        self.复制真实制品()
        self.写合成支持库("重复甲", "重复甲.能力", 注册能力id="冷启动.重复能力")
        self.写合成支持库("重复乙", "重复乙.能力", 注册能力id="冷启动.重复能力")
        数据 = self.运行脚本("装配", str(self.根), self.装配请求())
        self.assertFalse(数据["装配成功"], "重复注册必须装配失败")
        self.assertTrue(
            any("禁止" in 问题 and "重复注册" in 问题 for 问题 in 数据["问题列表"]),
            str(数据["问题列表"]),
        )
        self.assertTrue(
            any(记录["操作名称"] == "回滚" for 记录 in 数据["生命周期记录"]),
            "重复注册装配失败必须回滚",
        )
        # 声明级：两个包声明同一能力 id → 发现器拒绝
        self.复制真实制品()
        self.写合成支持库("声明甲", "冷启动.声明重复")
        self.写合成支持库("声明乙", "冷启动.声明重复")
        数据 = self.运行脚本("装配", str(self.根), self.装配请求())
        self.assertFalse(数据["装配成功"], "声明重复必须装配失败")
        self.assertTrue(
            any("能力 id 重复" in 问题 for 问题 in 数据["问题列表"]),
            str(数据["问题列表"]),
        )

    def test_版本锁漂移拒绝(self) -> None:
        """依赖声明版本锁漂移（要求 >=2.0.0，提供方 1.0.0）→ 装配拒绝。"""
        self.复制真实制品()
        self.写合成支持库(
            "漂移模块", "冷启动.漂移能力",
            依赖=[{"能力": "文件系统.读取文件", "版本": ">=2.0.0"}],
        )
        数据 = self.运行脚本("装配", str(self.根), self.装配请求())
        self.assertFalse(数据["装配成功"], "版本锁漂移必须装配失败")
        self.assertTrue(
            any("版本冲突" in 问题 or "要求" in 问题 for 问题 in 数据["问题列表"]),
            str(数据["问题列表"]),
        )

    def test_旧制品可回滚(self) -> None:
        """旧制品共存与回滚：已废弃旧版不参与；回滚翻转后旧版重新提供能力。"""
        self.复制真实制品()
        self.写合成支持库("回滚新", "冷启动.回滚能力", 版本="2.0.0", 返回值="新版本")
        self.写合成支持库("回滚旧", "冷启动.回滚能力", 版本="1.0.0",
                           已废弃=True, 返回值="旧版本")
        请求 = self.装配请求(("冷启动.回滚能力", {}))
        数据 = self.运行脚本("装配", str(self.根), 请求)
        self.assertTrue(数据["装配成功"], str(数据["问题列表"]))
        self.assertEqual(数据["调用结果表"][0]["值"], "新版本", "活跃新版本应提供能力")
        # 回滚：新版本标已废弃、旧版本恢复活跃（纯文件系统翻转声明）
        新声明 = self.根 / "支持库" / "适配层" / "回滚新" / "包声明.json"
        新数据 = json.loads(新声明.read_text(encoding="utf-8"))
        新数据["已废弃"] = True
        新声明.write_text(json.dumps(新数据, ensure_ascii=False), encoding="utf-8")
        旧声明 = self.根 / "支持库" / "适配层" / "回滚旧" / "包声明.json"
        旧数据 = json.loads(旧声明.read_text(encoding="utf-8"))
        旧数据.pop("已废弃", None)
        旧声明.write_text(json.dumps(旧数据, ensure_ascii=False), encoding="utf-8")
        # 全新进程重新装配：旧制品可回滚并提供能力
        数据 = self.运行脚本("装配", str(self.根), 请求)
        self.assertTrue(数据["装配成功"], str(数据["问题列表"]))
        self.assertEqual(数据["调用结果表"][0]["值"], "旧版本", "回滚后旧制品应提供能力")


class Test冷启动反向破坏(冷启动反向门禁基础):
    """反向破坏证明：删除 包声明/注册入口/契约/锁/实现 任一项生产链真实失败。"""

    def test_删包声明生产链失败(self) -> None:
        """删除全部 包声明.json → 装配必须失败（发现器拒绝）。"""
        self.复制真实制品()
        for 声明文件 in self.根.rglob("包声明.json"):
            声明文件.unlink()
        数据 = self.运行脚本("装配", str(self.根), self.装配请求())
        self.assertFalse(数据["装配成功"], "删包声明必须装配失败")
        self.assertTrue(
            any("未发现任何支持库或模块" in 问题 for 问题 in 数据["问题列表"]),
            str(数据["问题列表"]),
        )

    def test_删注册入口生产链失败(self) -> None:
        """删除 注册入口（入口.py）→ 装配必须失败（无仓库孪生回退）。"""
        self.复制真实制品()
        目录 = self.写合成支持库("删入口", "冷启动.删入口能力")
        (目录 / "入口.py").unlink()
        数据 = self.运行脚本("装配", str(self.根), self.装配请求())
        self.assertFalse(数据["装配成功"], "删注册入口必须装配失败")
        self.assertTrue(
            any("缺少入口文件" in 问题 for 问题 in 数据["问题列表"]),
            str(数据["问题列表"]),
        )

    def test_删实现生产链失败(self) -> None:
        """删除 实现/ 实现文件 → 入口导入失败，装配必须失败。"""
        self.复制真实制品()
        目录 = self.写合成实现包("删实现", "冷启动.删实现能力", 带实现=False)
        数据 = self.运行脚本("装配", str(self.根), self.装配请求())
        self.assertFalse(数据["装配成功"], "删实现必须装配失败")
        self.assertTrue(
            any("装配失败" in 问题 for 问题 in 数据["问题列表"]),
            str(数据["问题列表"]),
        )
        self.assertTrue(
            any(记录["操作名称"] == "回滚" for 记录 in 数据["生命周期记录"]),
            "删实现装配失败必须回滚",
        )

    def test_删契约生产链失败(self) -> None:
        """删除 能力契约/参数契约.json → S0.4 组件合规 13/13 门禁必须失败。

        缺陷证据（回传主协调）：运行时装配链不消费 参数契约.json，删契约后
        装配→注册→调用 仍放行（fail-open），仅合规门禁阻断 —— 见 缺陷清单。
        """
        self.复制真实制品()
        组件 = "模块库/文件管理"
        # 正向控制：契约存在时 13/13 全过
        数据 = self.运行脚本("组件合规", str(self.根), 组件)
        self.assertEqual(数据["通过数"], 13, f"基线合规必须 13/13：{数据}")
        # 反向破坏：删除聚合契约
        (self.根 / "模块库" / "文件管理" / "能力契约" / "参数契约.json").unlink()
        数据 = self.运行脚本("组件合规", str(self.根), 组件)
        self.assertLess(数据["通过数"], 13, "删契约后合规门禁必须失败")
        self.assertIn("契约", 数据["失败场景"])
        # 生产修复验证：运行时装配链也必须失败（fail-closed）
        数据 = self.运行脚本("装配", str(self.根), self.装配请求(
            ("文件系统.写入文件", {"文件路径": str(self.根 / "契约.txt"), "内容": "契约", "编码": "utf-8"}),
        ))
        self.assertFalse(数据["装配成功"], "删契约后装配必须失败（fail-closed）")
        self.assertTrue(
            any("聚合契约" in 问题 for 问题 in 数据["问题列表"]),
            str(数据["问题列表"]),
        )

    def test_删锁生产链失败(self) -> None:
        """删除 依赖锁.json → 提供者依赖锁 fail-closed 强制校验必须拒绝。

        缺陷证据（回传主协调）：装配系统以锁文件存在性区分第三方提供者，
        删锁后装配仍放行（fail-open）—— 见 缺陷清单。
        """
        self.复制真实制品()
        提供者名 = "冷启动提供者"
        构建 = self.运行脚本("构建提供者", str(self.根), 提供者名)
        self.assertTrue(构建["成功"])
        相对路径 = f"支持库/适配层/{提供者名}"
        # 正向控制：锁存在时校验通过、装配成功
        数据 = self.运行脚本("校验提供者环境", str(self.根), 相对路径)
        self.assertTrue(数据["成功"], str(数据["问题列表"]))
        数据 = self.运行脚本("装配", str(self.根), self.装配请求(
            (f"{提供者名}.最小能力", {}),
        ))
        self.assertTrue(数据["装配成功"], str(数据["问题列表"]))
        self.assertTrue(数据["调用结果表"][0]["成功"])
        # 反向破坏：删除依赖锁
        (self.根 / "支持库" / "适配层" / 提供者名 / "依赖锁.json").unlink()
        数据 = self.运行脚本("校验提供者环境", str(self.根), 相对路径)
        self.assertFalse(数据["成功"], "删锁后强制校验必须拒绝")
        self.assertTrue(
            any("缺少 依赖锁.json" in 问题["原因"] for 问题 in 数据["问题列表"]),
            str(数据["问题列表"]),
        )
        # 生产修复验证：装配系统删锁后必须拒绝（fail-closed）
        数据 = self.运行脚本("装配", str(self.根), self.装配请求(
            (f"{提供者名}.最小能力", {}),
        ))
        self.assertFalse(数据["装配成功"], "删锁后装配必须失败（fail-closed）")
        self.assertTrue(
            any("依赖锁缺失" in 问题 for 问题 in 数据["问题列表"]),
            str(数据["问题列表"]),
        )


if __name__ == "__main__":
    unittest.main()
