"""第二十九阶段 G3：权威合规收敛测试（组件合规 / 逐包合规器 / MCP合规 三方口径一致）。

覆盖：齐全包三方一致通过；反向破坏（删除任一要素）三方结论一致且失败；
以及发布门禁内部三个私有判据（监听端口快照、工程缓存源码扫描、英文命名扫描）。

注意：发布门禁自 2026-08-29 裁决起不再调用 执行逐包权威合规（逐包13/13 已从发布链移除，
发布只认 HTML 黑盒验证）。本文件因此只证明“合规器与 MCP 合规两边口径一致”，
不能当作“门禁仍在做逐包合规”的证据；门禁侧证据以 运行发布门禁 的检查项为准。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 开发工具.组件合规.合规测试包 import 组件合规
from 支持库.后端.组件规范支持库 import 生成完整性摘要
from 开发工具.发布门禁.运行发布门禁 import 执行逐包权威合规

破坏能力1 = {
    "能力id": "破坏模块.破坏能力1", "版本": "1.0.0", "说明": "门禁收敛破坏能力1",
    "参数": [{"名称": "文本", "类型": "文本", "必填": True,
              "默认值": None, "说明": "待处理文本"}],
    "返回": {"类型": "结果", "值结构": {}},
    "错误码": ["参数不合法"],
    "调用示例": {"能力id": "破坏模块.破坏能力1", "参数": {"文本": "示例"}},
}

入口源码 = '''"""破坏模块包级中文入口。"""
from __future__ import annotations

from 实现.实现 import 破坏能力1

__all__ = ["破坏能力1"]


def 注册能力(注册表) -> None:
    """由模块加载器调用。"""
    from 公共契约.能力契约.契约 import 能力实现

    注册表.注册(能力实现(
        能力id="破坏模块.破坏能力1", 包id="模块库.破坏模块", 实现函数=破坏能力1,
        参数=[{"名称": "文本", "类型": "文本"}], 返回="结果", 说明="门禁收敛能力",
    ))
'''

实现源码 = '''"""破坏模块实现。"""
from __future__ import annotations


def 破坏能力1(文本: str) -> dict:
    if not 文本:
        return {"成功": False, "错误码": "参数不合法"}
    return {"成功": True, "值": {"长度": len(文本)}}
'''


def 建临时模块库() -> tuple[Path, Path]:
    """在临时根构造 模块库/破坏模块（正式包形态齐全），返回 (临时根, 模块目录)。"""
    临时根 = Path(tempfile.mkdtemp(prefix="门禁收敛_"))
    模块目录 = 临时根 / "模块库" / "破坏模块"
    for 子目录 in ("能力契约", "依赖契约", "配置契约", "权限契约", "实现", "说明"):
        (模块目录 / 子目录).mkdir(parents=True)
    (模块目录 / "能力契约" / "参数契约.json").write_text(
        json.dumps({"契约版本": "1.0.0", "能力契约": [破坏能力1]},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    (模块目录 / "依赖契约" / "依赖契约.json").write_text(
        json.dumps({"依赖": []}, ensure_ascii=False), encoding="utf-8")
    (模块目录 / "配置契约" / "配置契约.json").write_text(
        json.dumps({"默认超时秒": 10}, ensure_ascii=False), encoding="utf-8")
    (模块目录 / "权限契约" / "权限契约.json").write_text(
        json.dumps({"破坏模块.破坏能力1": {"允许用户": ["*"]}}, ensure_ascii=False),
        encoding="utf-8")
    (模块目录 / "资源预算.json").write_text(
        json.dumps({"内存上限": 50, "线程上限": 2, "子进程上限": 1,
                    "并发调用上限": 2, "队列长度": 5, "文件句柄上限": 20,
                    "临时空间上限": 50, "单次调用超时": 3,
                    "每分钟重启次数": 2, "空闲回收时间": 30}, ensure_ascii=False),
        encoding="utf-8")
    (模块目录 / "复用决策.json").write_text(
        json.dumps({"搜索词": "破坏", "候选能力id": ["破坏模块.破坏能力1"]},
                   ensure_ascii=False), encoding="utf-8")
    (模块目录 / "验证场景引用.json").write_text(
        json.dumps({"验证场景引用": [{"场景id": "模块.装配验证",
                                     "目标": "模块库.破坏模块", "范围": "装配"}]},
                   ensure_ascii=False), encoding="utf-8")
    (模块目录 / "包声明.json").write_text(json.dumps({
        "包id": "模块库.破坏模块", "名称": "破坏模块", "类型": "基础模块",
        "版本": "1.0.0", "说明": "门禁收敛测试模块", "入口": "__init__.py",
        "依赖": [],
    }, ensure_ascii=False), encoding="utf-8")
    (模块目录 / "__init__.py").write_text(入口源码, encoding="utf-8")
    (模块目录 / "实现" / "实现.py").write_text(实现源码, encoding="utf-8")
    (模块目录 / "说明" / "使用说明.md").write_text(
        "# 破坏模块说明书\n\n破坏能力1，错误码：参数不合法。\n", encoding="utf-8")
    摘要 = 生成完整性摘要(模块目录, 包id="模块库.破坏模块", 版本="1.0.0")
    (模块目录 / "完整性摘要.json").write_text(
        json.dumps(摘要, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 临时根, 模块目录


def _MCP合规(临时根: Path, 模块名: str = "破坏模块") -> dict:
    from 开发工具.组件合规.模块合规 import 校验模块合规
    return 校验模块合规(临时根, 模块名)


class Test发布门禁收敛(unittest.TestCase):
    """合规器与 MCP 合规口径一致，及门禁内部私有判据（非“门禁已接入逐包合规”）。"""

    def test_监听端口快照容忍非UTF8系统输出(self) -> None:
        """系统进程字段可能含非 UTF-8 字节，门禁不能因此误报资源残留。"""
        from 开发工具.发布门禁 import 运行发布门禁 as 门禁

        模拟结果 = type("模拟结果", (), {
            "returncode": 0,
            "stdout": b"COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n"
                       b"svc 1 user 3u IPv4 0 0 0 127.0.0.1:45678 (LISTEN)\xff\xfe\n",
            "stderr": b"",
        })()
        with patch.object(门禁.subprocess, "run", return_value=模拟结果):
            self.assertEqual(门禁._监听端口快照(), {"127.0.0.1:45678"})

    def test_齐全包_合规_MCP_门禁三通过(self) -> None:
        """齐全正式包：组件合规 13/13、MCP 合规成功、逐包合规器 13/13。"""
        临时根, 模块目录 = 建临时模块库()
        try:
            报告 = 组件合规(模块目录).执行()
            self.assertEqual(报告.通过数, 13,
                             [f"{名称}: {详情}" for 名称, 通过, 详情 in 报告.场景结果表 if not 通过])
            MCP结果 = _MCP合规(临时根)
            self.assertTrue(MCP结果["成功"], MCP结果)
            通过, 证据表 = 执行逐包权威合规([模块目录])
            self.assertTrue(通过, 证据表)
            self.assertEqual(证据表[0][3], 13, "逐包证据必须为 13/13")
            self.assertEqual(证据表[0][2], True)
        finally:
            shutil.rmtree(临时根, ignore_errors=True)

    def test_删除实现_三者一致失败(self) -> None:
        """删除 实现/实现.py → 组件合规/逐包合规器/MCP 结论一致且失败。"""
        临时根, 模块目录 = 建临时模块库()
        try:
            (模块目录 / "实现" / "实现.py").unlink()
            报告 = 组件合规(模块目录).执行()
            self.assertFalse(报告.成功)
            通过, 证据表 = 执行逐包权威合规([模块目录])
            self.assertFalse(通过, "逐包合规器必须失败而非零退出")
            self.assertLess(证据表[0][3], 13)
            self.assertIn("公共入口", 证据表[0][1], "逐包证据必须列明失败场景")
            MCP结果 = _MCP合规(临时根)
            self.assertFalse(MCP结果["成功"], "MCP 合规必须一致失败")
        finally:
            shutil.rmtree(临时根, ignore_errors=True)

    def test_删除入口_三者一致失败(self) -> None:
        """删除 __init__.py → 组件合规/逐包合规器/MCP 结论一致且失败。"""
        临时根, 模块目录 = 建临时模块库()
        try:
            (模块目录 / "__init__.py").unlink()
            报告 = 组件合规(模块目录).执行()
            self.assertFalse(报告.成功)
            通过, _ = 执行逐包权威合规([模块目录])
            self.assertFalse(通过)
            MCP结果 = _MCP合规(临时根)
            self.assertFalse(MCP结果["成功"], "MCP 合规必须一致失败")
        finally:
            shutil.rmtree(临时根, ignore_errors=True)

    def test_删除验证证据_三者一致失败(self) -> None:
        """删除 验证场景引用.json → 组件合规/逐包合规器/MCP 结论一致且失败。"""
        临时根, 模块目录 = 建临时模块库()
        try:
            (模块目录 / "验证场景引用.json").unlink()
            报告 = 组件合规(模块目录).执行()
            self.assertFalse(报告.成功)
            场景表 = {名称: 通过 for 名称, 通过, _ in 报告.场景结果表}
            self.assertFalse(场景表["结构"], "缺验证证据必须使结构场景失败")
            通过, _ = 执行逐包权威合规([模块目录])
            self.assertFalse(通过)
            MCP结果 = _MCP合规(临时根)
            self.assertFalse(MCP结果["成功"], "MCP 七要素含验证场景引用，必须一致失败")
        finally:
            shutil.rmtree(临时根, ignore_errors=True)

    def test_删除配置契约_合规与门禁一致失败(self) -> None:
        """删除 配置契约 → 组件合规/逐包合规器一致失败（S0 缺项阻断清单）。"""
        临时根, 模块目录 = 建临时模块库()
        try:
            shutil.rmtree(模块目录 / "配置契约")
            报告 = 组件合规(模块目录).执行()
            self.assertFalse(报告.成功)
            场景表 = {名称: 通过 for 名称, 通过, _ in 报告.场景结果表}
            self.assertFalse(场景表["配置"], "缺 配置契约 必须使配置场景失败")
            通过, 证据表 = 执行逐包权威合规([模块目录])
            self.assertFalse(通过)
            self.assertIn("配置", 证据表[0][1], "逐包证据必须列明 配置 失败")
        finally:
            shutil.rmtree(临时根, ignore_errors=True)

    def test_逐包证据输出格式(self) -> None:
        """逐包证据：包名/失败场景/通过/13 项计数齐全。"""
        临时根, 模块目录 = 建临时模块库()
        try:
            通过, 证据表 = 执行逐包权威合规([模块目录])
            self.assertTrue(通过)
            名称, 失败场景, 通过标记, 通过数 = 证据表[0]
            self.assertEqual(名称, "破坏模块")
            self.assertEqual(失败场景, "", "通过包失败场景必须为空")
            self.assertEqual(通过标记, True)
            self.assertEqual(通过数, 13)
        finally:
            shutil.rmtree(临时根, ignore_errors=True)
    def test_支持库合规失败必须阻断(self) -> None:
        """支持库缺少配置契约时，逐包13/13不能只披露后放行。"""
        临时根, 包目录 = 建临时模块库()
        try:
            声明路径 = 包目录 / "包声明.json"
            声明 = json.loads(声明路径.read_text(encoding="utf-8"))
            声明["类型"] = "支持库"
            声明路径.write_text(json.dumps(声明, ensure_ascii=False), encoding="utf-8")
            shutil.rmtree(包目录 / "配置契约")
            通过, 证据表 = 执行逐包权威合规([包目录])
            self.assertFalse(通过, "支持库合规失败不能只披露后返回通过")
            self.assertLess(证据表[0][3], 13)
        finally:
            shutil.rmtree(临时根, ignore_errors=True)
    def test_当前验证任务目录源码不误判为持久源码(self) -> None:
        """嵌套门禁执行期间只忽略当前任务目录，其他缓存源码仍须阻断。"""
        from 开发工具.发布门禁 import 运行发布门禁 as 门禁

        临时根 = Path(tempfile.mkdtemp(prefix="门禁缓存源码_"))
        try:
            活动目录 = 临时根 / "工程缓存" / "验证运行" / "任务1" / "已激活"
            持久目录 = 临时根 / "工程缓存" / "未登记源码"
            活动目录.mkdir(parents=True)
            持久目录.mkdir(parents=True)
            (活动目录 / "主.py").write_text("", encoding="utf-8")
            (持久目录 / "主.py").write_text("", encoding="utf-8")
            with patch.object(门禁, "系统根", 临时根), patch.dict(
                os.environ, {"系统底座_任务id": "任务1"}, clear=False
            ):
                结果 = 门禁._扫描工程缓存Python源码()
            self.assertEqual(结果, ["工程缓存/未登记源码/主.py"])
        finally:
            shutil.rmtree(临时根, ignore_errors=True)

    def test_编译缓存内生成制品源码不误判为持久源码(self) -> None:
        """不可变编译产物属于生成物；缓存外未登记源码仍必须阻断。"""
        from 开发工具.发布门禁 import 运行发布门禁 as 门禁

        临时根 = Path(tempfile.mkdtemp(prefix="门禁编译缓存源码_"))
        try:
            生成目录 = 临时根 / "工程缓存" / "编译缓存" / "项目" / "版本" / "abc"
            持久目录 = 临时根 / "工程缓存" / "未登记源码"
            生成目录.mkdir(parents=True)
            持久目录.mkdir(parents=True)
            (生成目录 / "启动.py").write_text("", encoding="utf-8")
            (持久目录 / "主.py").write_text("", encoding="utf-8")
            with patch.object(门禁, "系统根", 临时根):
                结果 = 门禁._扫描工程缓存Python源码()
            self.assertEqual(结果, ["工程缓存/未登记源码/主.py"])
        finally:
            shutil.rmtree(临时根, ignore_errors=True)


    def test_英文命名扫描覆盖全部正式目录(self) -> None:
        """漏扫的正式层放入英文函数时必须被门禁发现。"""
        from 开发工具.发布门禁 import 运行发布门禁 as 门禁
        临时根 = Path(tempfile.mkdtemp(prefix="门禁英文边界_"))
        try:
            (临时根 / "启动监督器").mkdir()
            (临时根 / "启动监督器" / "越界.py").write_text(
                "def main():\n    return 1\n", encoding="utf-8")
            with patch.object(门禁, "系统根", 临时根):
                结果 = 门禁._扫描英文函数命名()
            self.assertIn("越界.py", 结果)
            self.assertIn("main", 结果)
        finally:
            shutil.rmtree(临时根, ignore_errors=True)


    def test_英文命名扫描放行AST访问器协议(self) -> None:
        """AST 回调族（visit_*/generic_visit）必须放行，且真实英文业务名仍被拦住。

        正反对照缺一不可：只断言「visit_ 不报」在门禁整个失效（扫描为空）时也会通过；
        必须同时断言同文件里的普通英文名仍被检出。
        """
        from 开发工具.发布门禁 import 运行发布门禁 as 门禁
        临时根 = Path(tempfile.mkdtemp(prefix="门禁AST协议_"))
        try:
            (临时根 / "支持库").mkdir()
            (临时根 / "支持库" / "访问器.py").write_text(
                "class 访问器:\n"
                "    def generic_visit(self, 节点):\n"
                "        return None\n"
                "    def visit_FunctionDef(self, 节点):\n"
                "        return None\n"
                "    def visit_ClassDef(self, 节点):\n"
                "        return None\n"
                "    def handle_stuff(self, 节点):\n"
                "        return None\n",
                encoding="utf-8")
            with patch.object(门禁, "系统根", 临时根):
                结果 = 门禁._扫描英文函数命名()
            self.assertNotIn("generic_visit", 结果)
            self.assertNotIn("visit_FunctionDef", 结果)
            self.assertNotIn("visit_ClassDef", 结果)
            self.assertIn("handle_stuff", 结果)
        finally:
            shutil.rmtree(临时根, ignore_errors=True)


class Test模块合规口径对齐(unittest.TestCase):
    """E-f：模块合规的同包判定必须与 依赖防火墙/能力调用图审计 同一结论。

    修前实测：`_分类导入('模块库.能力目录.实现.能力索引')` → `{'类别': '白名单外导入'}`
    （集成运行时真实报出），而同一条 import 在防火墙与调用图审计里放行 —— 三处审计
    对同一行代码两个结论。修后三处共用 `运行核心/依赖防火墙.py::同包实现导入`。
    """

    def setUp(self) -> None:
        临时根, self.模块目录 = 建临时模块库()
        self.临时根 = 临时根
        self.addCleanup(shutil.rmtree, 临时根, ignore_errors=True)

    def _边界(self) -> list[dict]:
        from 开发工具.组件合规.模块合规 import 审计模块边界

        return 审计模块边界(self.临时根, "破坏模块")["违规列表"]

    def test_同包实现导入放行(self) -> None:
        """同包 `实现/` 导入放行：修前落到「白名单外导入」，修后与防火墙同一结论。

        `实现.实现`（包目录被塞进 sys.path 的短名）与 `模块库.破坏模块.实现.实现`
        （仓库全名）两种写法都要放行 —— 前者是 `组件合规._加载入口` 的加载约定。
        """
        (self.模块目录 / "实现" / "实现.py").write_text(
            "from 模块库.破坏模块.实现.实现 import 破坏能力1\n"
            "from 实现.实现 import 破坏能力1\n", encoding="utf-8")
        self.assertEqual(self._边界(), [])

    def test_跨包实现导入判红且用同一缺口词(self) -> None:
        """跨包 `实现/` 直连照旧阻断，类别与防火墙同一个词（实现目录导入）。

        修前这条落在「白名单外导入」——同一个违规在两个审计器里连名字都不一样。
        断言到**具体条目**（文件/行/模块/类别）：只断言「类别表里有实现目录导入」
        在漏判整行、或误报到别处时也会通过。
        """
        (self.模块目录 / "实现" / "实现.py").write_text(
            "from 模块库.别的模块.实现.内部 import 东西\n", encoding="utf-8")
        self.assertIn(
            {"文件": "模块库/破坏模块/实现/实现.py", "行": 1,
             "模块": "模块库.别的模块.实现.内部", "类别": "实现目录导入"},
            self._边界())

    def test_跨包实现判定与权威函数同源(self) -> None:
        """判据同源：换掉权威函数即换掉本审计器的结论（防止又长出一份私有副本）。"""
        from 开发工具.组件合规 import 模块合规
        from 运行核心 import 依赖防火墙

        调用次数 = []
        原函数 = 依赖防火墙.同包实现导入

        def 计数(文件, 模块名):
            调用次数.append((文件, 模块名))
            return 原函数(文件, 模块名)

        (self.模块目录 / "实现" / "实现.py").write_text(
            "from 模块库.破坏模块.实现.实现 import 破坏能力1\n", encoding="utf-8")
        with patch.object(模块合规, "同包实现导入", side_effect=计数):
            模块合规.审计模块边界(self.临时根, "破坏模块")
        self.assertTrue(调用次数, "审计必须真的走权威函数，不得本地复判")


if __name__ == "__main__":
    unittest.main()
