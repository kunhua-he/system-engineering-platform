"""依赖与生命周期审计测试：合法提供者零违规/缺依赖锁/摘要漂移/混装/
缺健康探针/缺停止入口检出/真实跑现有提供者目录审计输出。

禁止 mock 成功：违规样本全部真实构造（删文件/改内容/多第三方声明）。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 支持库.后端.组件规范支持库 import 生成完整性摘要
from 开发工具.依赖生命周期审计.审计核心 import 审计单个提供者, 审计全部
from 运行核心.依赖防火墙 import 审计依赖

包id = "支持库.适配层.示例提供者"


def 构造合法提供者(目录: Path) -> Path:
    """在临时目录内构造完整合规的第三方支持库提供者目录。"""
    提供者目录 = 目录 / "示例提供者"
    提供者目录.mkdir()
    (提供者目录 / "包声明.json").write_text(json.dumps({
        "包id": 包id, "名称": "示例提供者", "类型": "支持库",
        "版本": "1.0.0", "依赖": [],
    }, ensure_ascii=False), encoding="utf-8")
    (提供者目录 / "依赖锁.json").write_text(json.dumps({
        "包": [{"名称": "示例第三方", "版本": "2.0.0"}],
        "提供者id": 包id,
    }, ensure_ascii=False), encoding="utf-8")
    (提供者目录 / "能力定义.json").write_text(json.dumps({
        "包id": 包id, "版本": "1.0.0",
        "能力列表": [{"能力id": "示例.健康探针", "中文名称": "健康探针", "版本": "1.0.0"}],
    }, ensure_ascii=False), encoding="utf-8")
    实现 = 提供者目录 / "实现"
    实现.mkdir()
    (实现 / "提供者.py").write_text(
        "def 执行任务(请求):\n    return 请求\n\n\ndef 停止():\n    pass\n",
        encoding="utf-8")
    摘要 = 生成完整性摘要(提供者目录, 包id=包id, 版本="1.0.0")
    (提供者目录 / "完整性摘要.json").write_text(
        json.dumps(摘要, ensure_ascii=False), encoding="utf-8")
    return 提供者目录


def 构造转调壳提供者(目录: Path, *, 腿含停止函数: bool, 腿含进程组证据: bool) -> Path:
    """构造「后端腿转调适配层腿」的提供者（D-1 收口形态），腿的真实实现单独造。

    平台把「同一份逻辑只能有一个实现」收口成转调壳：壳文件里只有
    ``sys.modules[__name__] = sys.modules[唯一实现名]``，函数定义全在适配层腿。
    判据必须跟得进这条壳，否则「实现里没有停止函数」是假红。
    """
    临时根 = 目录
    (临时根 / "模块库").mkdir()          # 锚点：让 _系统根 认到临时根（转调壳解析基准）
    腿实现 = 临时根 / "支持库" / "适配层" / "目标提供者" / "实现"
    腿实现.mkdir(parents=True)
    腿停止 = "def 停止():\n    pass\n" if 腿含停止函数 else ""
    腿证据 = "进程组 = None\n" if 腿含进程组证据 else ""
    (腿实现 / "实现文件.py").write_text(
        f"{腿停止}\n{腿证据}\ndef 执行任务(请求):\n    return 请求\n", encoding="utf-8")
    提供者目录 = 临时根 / "支持库" / "适配层" / "壳提供者"
    提供者目录.mkdir(parents=True)
    (提供者目录 / "包声明.json").write_text(json.dumps({
        "包id": "支持库.适配层.壳提供者", "名称": "壳提供者", "类型": "支持库",
        "版本": "1.0.0", "依赖": [],
    }, ensure_ascii=False), encoding="utf-8")
    (提供者目录 / "依赖锁.json").write_text(json.dumps({
        "包": [{"名称": "示例第三方", "版本": "2.0.0"}],
        "提供者id": "支持库.适配层.壳提供者",
    }, ensure_ascii=False), encoding="utf-8")
    (提供者目录 / "能力定义.json").write_text(json.dumps({
        "包id": "支持库.适配层.壳提供者", "版本": "1.0.0",
        "能力列表": [{"能力id": "壳.健康探针", "中文名称": "健康探针", "版本": "1.0.0"}],
    }, ensure_ascii=False), encoding="utf-8")
    (提供者目录 / "生命周期契约.json").write_text(json.dumps({
        "提供者id": "支持库.适配层.壳提供者",
        "资源模型": "独立子进程",
        "释放策略": "每次调用在 finally 中终止进程组",
    }, ensure_ascii=False), encoding="utf-8")
    壳实现 = 提供者目录 / "实现"
    壳实现.mkdir()
    (壳实现 / "壳.py").write_text(
        '"""转调壳：唯一实现在 支持库/适配层/目标提供者（本文件不定义任何函数）。"""\n'
        "import sys\n\n"
        '唯一实现名 = "支持库.适配层.目标提供者.实现.实现文件"\n'
        "sys.modules[__name__] = sys.modules[唯一实现名]\n",
        encoding="utf-8")
    摘要 = 生成完整性摘要(提供者目录, 包id="支持库.适配层.壳提供者", 版本="1.0.0")
    (提供者目录 / "完整性摘要.json").write_text(
        json.dumps(摘要, ensure_ascii=False), encoding="utf-8")
    return 提供者目录


class Test依赖与生命周期审计(unittest.TestCase):
    """合法提供者零违规；各类违规样本真实检出。"""

    def test_合法提供者零违规(self):
        目录 = Path(tempfile.mkdtemp(prefix="依赖审计_"))
        提供者目录 = 构造合法提供者(目录)
        结果 = 审计单个提供者(提供者目录)
        self.assertTrue(结果.是否通过, f"合法提供者不应违规: {结果.违规列表}")

    def test_缺依赖锁检出(self):
        目录 = Path(tempfile.mkdtemp(prefix="依赖审计_"))
        提供者目录 = 构造合法提供者(目录)
        (提供者目录 / "依赖锁.json").unlink()
        结果 = 审计单个提供者(提供者目录)
        self.assertTrue(any("缺依赖锁" in 违规 for 违规 in 结果.违规列表), 结果.违规列表)

    def test_混装检出(self):
        目录 = Path(tempfile.mkdtemp(prefix="依赖审计_"))
        提供者目录 = 构造合法提供者(目录)
        数据 = json.loads((提供者目录 / "依赖锁.json").read_text(encoding="utf-8"))
        数据["包"].append({"名称": "另一个第三方", "版本": "1.0.0"})
        (提供者目录 / "依赖锁.json").write_text(
            json.dumps(数据, ensure_ascii=False), encoding="utf-8")
        结果 = 审计单个提供者(提供者目录)
        self.assertTrue(any("混装" in 违规 for 违规 in 结果.违规列表), 结果.违规列表)

    def test_摘要漂移检出(self):
        目录 = Path(tempfile.mkdtemp(prefix="依赖审计_"))
        提供者目录 = 构造合法提供者(目录)
        (提供者目录 / "实现" / "提供者.py").write_text(
            "def 执行任务(请求):\n    return 请求 + 1\n\n\ndef 停止():\n    pass\n",
            encoding="utf-8")
        结果 = 审计单个提供者(提供者目录)
        self.assertTrue(any("摘要漂移" in 违规 for 违规 in 结果.违规列表), 结果.违规列表)

    def test_缺健康探针与缺停止入口检出(self):
        目录 = Path(tempfile.mkdtemp(prefix="依赖审计_"))
        提供者目录 = 构造合法提供者(目录)
        (提供者目录 / "能力定义.json").write_text(json.dumps({
            "包id": 包id, "版本": "1.0.0",
            "能力列表": [{"能力id": "示例.转换", "中文名称": "转换", "版本": "1.0.0"}],
        }, ensure_ascii=False), encoding="utf-8")
        (提供者目录 / "实现" / "提供者.py").write_text(
            "def 执行任务(请求):\n    return 请求\n", encoding="utf-8")
        结果 = 审计单个提供者(提供者目录)
        self.assertTrue(any("缺健康探针" in 违规 for 违规 in 结果.违规列表), 结果.违规列表)
        self.assertTrue(any("缺停止入口" in 违规 for 违规 in 结果.违规列表), 结果.违规列表)

    def test_生命周期契约入口与身份篡改检出(self):
        """契约不能靠任意非空文本假绿：入口必须存在且提供者身份必须匹配。"""
        目录 = Path(tempfile.mkdtemp(prefix="依赖审计_"))
        提供者目录 = 构造合法提供者(目录)
        (提供者目录 / "实现" / "提供者.py").write_text(
            "def 执行任务(请求):\n    return 请求\n", encoding="utf-8")
        (提供者目录 / "能力定义.json").write_text(json.dumps({
            "包id": 包id, "版本": "1.0.0", "能力列表": [],
        }, ensure_ascii=False), encoding="utf-8")
        (提供者目录 / "生命周期契约.json").write_text(json.dumps({
            "提供者id": "别的提供者", "健康探针": {
                "方式": "随便写", "入口": "不存在.py", "成功条件": "x", "失败码": "y"
            }, "资源模型": "调用内临时资源", "释放策略": "这是一段足够长但没有释放证据的文本",
        }, ensure_ascii=False), encoding="utf-8")
        摘要 = 生成完整性摘要(提供者目录, 包id=包id, 版本="1.0.0")
        (提供者目录 / "完整性摘要.json").write_text(
            json.dumps(摘要, ensure_ascii=False), encoding="utf-8")
        结果 = 审计单个提供者(提供者目录)
        self.assertTrue(any("缺健康探针" in 违规 for 违规 in 结果.违规列表), 结果.违规列表)
        self.assertTrue(any("缺停止入口" in 违规 for 违规 in 结果.违规列表), 结果.违规列表)

    def test_转调壳指向的适配层腿算本提供者证据(self):
        """正样本：函数定义全在适配层腿，判据跟得进转调壳 ⇒ 不判缺停止入口/释放策略不符。"""
        目录 = Path(tempfile.mkdtemp(prefix="依赖审计_"))
        提供者目录 = 构造转调壳提供者(目录, 腿含停止函数=True, 腿含进程组证据=True)
        结果 = 审计单个提供者(提供者目录)
        self.assertTrue(结果.是否通过, f"转调壳 + 腿有证据不应违规: {结果.违规列表}")

    def test_转调壳指向空腿仍判缺停止入口(self):
        """反向验证：壳跟随不是「一律放行」——腿里没有停止函数/资源证据时仍判红。"""
        目录 = Path(tempfile.mkdtemp(prefix="依赖审计_"))
        提供者目录 = 构造转调壳提供者(目录, 腿含停止函数=False, 腿含进程组证据=False)
        结果 = 审计单个提供者(提供者目录)
        self.assertTrue(any("缺停止入口" in 违规 for 违规 in 结果.违规列表), 结果.违规列表)
        self.assertTrue(any("释放策略不符" in 违规 for 违规 in 结果.违规列表), 结果.违规列表)

    def test_真实审计现有提供者输出(self):
        """真实跑 worktree 现有提供者目录，输出审计报告（不 mock）。"""
        结果列表, 跳过列表 = 审计全部(系统根)
        self.assertGreater(len(结果列表), 0, "应扫描到至少一个标准提供者")
        print("真实审计现有提供者:")
        for 结果 in 结果列表:
            print(f"  [{结果.提供者名}] 违规 {len(结果.违规列表)} 条: {结果.违规列表}")
        print(f"  跳过 {len(跳过列表)}: {跳过列表}")

    def test_依赖防火墙检出语法错误和属性动态导入(self):
        from 运行核心 import 依赖防火墙
        旧根 = 依赖防火墙.系统根
        try:
            临时根 = Path(tempfile.mkdtemp(prefix="依赖防火墙_"))
            (临时根 / "运行核心").mkdir()
            (临时根 / "测试中心").mkdir()
            (临时根 / "运行核心" / "坏.py").write_text("import importlib\n模块名 = input()\nimportlib.import_module(模块名)\n", encoding="utf-8")
            依赖防火墙.系统根 = 临时根
            结果 = 审计依赖(临时根)
            self.assertTrue(any("动态导入绕过" in 项.规则 for 项 in 结果.违规列表))
            (临时根 / "运行核心" / "坏.py").write_text("def x(:\n", encoding="utf-8")
            结果 = 审计依赖(临时根)
            self.assertTrue(any("源码无法解析" in 项.规则 for 项 in 结果.违规列表))
        finally:
            依赖防火墙.系统根 = 旧根


if __name__ == "__main__":
    unittest.main()
