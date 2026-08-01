"""第十四阶段 工作包03 测试：组件开发Agent视图（需求/复用/占用/创建/提交）。

调用生产实现（平台控制面.统一入口.统一能力服务 + 工程缓存视图），
不复制简化算法；临时目录隔离，引导授予 组件开发Agent 角色后真实操作。
"""
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 平台控制面.统一入口 import 统一能力服务
from 开发工具.统一能力入口.视图.组件开发Agent视图 import 组件开发Agent视图


def 建服务() -> tuple[统一能力服务, Path]:
    目录 = Path(tempfile.mkdtemp(prefix="工作包03_视图_"))
    return 统一能力服务(目录), 目录


def 提权(服务: 统一能力服务) -> tuple[组件开发Agent视图, str]:
    """受信引导：注册 → 引导授予 组件开发Agent → 切换角色；返回视图与令牌。"""
    身份id = "组件开发Agent_视图测试"
    令牌 = 服务.授权.注册身份(身份id=身份id)
    成功, 消息 = 服务.授权.引导授予(身份id=身份id, 角色="组件开发Agent", 授予者="系统引导")
    assert 成功, 消息
    成功, 消息 = 服务.授权.切换角色(令牌, "组件开发Agent")
    assert 成功, 消息
    return 组件开发Agent视图(服务), 令牌


def 完整预算() -> dict:
    return {"内存上限": 100, "线程上限": 4, "子进程上限": 1, "并发调用上限": 4,
            "队列长度": 10, "文件句柄上限": 50, "临时空间上限": 100,
            "单次调用超时": 5, "每分钟重启次数": 2, "空闲回收时间": 60}


def 登记统计能力(服务: 统一能力服务) -> None:
    契约 = {"能力id": "统计.汇总", "名称": "统计汇总", "参数": [{"名称": "数据"}],
            "返回": {"类型": "数值"}, "错误码": [], "副作用": "无",
            "宿主": "后端", "权限": ""}
    成功, 消息 = 服务.目录.登记能力(能力id="统计.汇总", 契约=契约,
                                组件="统计组件", 领域="统计")
    assert 成功, 消息


class Test组件开发Agent视图(unittest.TestCase):
    """视图六项真实行为：登记+计划 / 未确认拒绝 / 缺决策拒绝 / 创建成功+租约 / 提交 / 复用分析。"""

    def setUp(self):
        self.服务, self.目录 = 建服务()
        self.视图, self.令牌 = 提权(self.服务)

    def test_登记需求并生成装配计划(self):
        登记统计能力(self.服务)
        登记结果 = self.视图.登记需求(self.令牌, "实现统计汇总能力")
        self.assertTrue(登记结果["成功"], 登记结果)
        需求id = 登记结果["需求id"]
        self.assertTrue(需求id)
        确认结果 = self.视图.确认需求(self.令牌, 需求id)
        self.assertTrue(确认结果["成功"], 确认结果)
        计划结果 = self.视图.生成装配计划(self.令牌, 需求id)
        self.assertTrue(计划结果["成功"], 计划结果)
        self.assertEqual(计划结果["计划"]["需求id"], 需求id)
        self.assertTrue(计划结果["计划"]["工作包表"], "装配计划必须含工作包")

    def test_未确认需求创建组件被拒(self):
        登记结果 = self.视图.登记需求(self.令牌, "未确认目标")
        需求id = 登记结果["需求id"]
        创建结果 = self.视图.创建组件(
            self.令牌, 需求id, 复用决策={"搜索词": "统计", "候选能力id": ["统计.汇总"]},
            资源预算=完整预算(), 允许修改路径=["组件库/x"],
            组件声明={"名称": "x"}, 能力id="统计.汇总")
        self.assertFalse(创建结果["成功"])
        self.assertEqual(创建结果["错误码"], "REQUIREMENT_UNCONFIRMED")

    def test_缺复用决策创建组件被拒(self):
        登记结果 = self.视图.登记需求(self.令牌, "缺决策目标")
        需求id = 登记结果["需求id"]
        确认结果 = self.视图.确认需求(self.令牌, 需求id)
        self.assertTrue(确认结果["成功"], 确认结果)
        创建结果 = self.视图.创建组件(
            self.令牌, 需求id, 复用决策={}, 资源预算=完整预算(),
            允许修改路径=["组件库/x"], 组件声明={"名称": "x"}, 能力id="")
        self.assertFalse(创建结果["成功"])
        self.assertEqual(创建结果["错误码"], "NO_REUSE_DECISION")

    def test_确认需求后创建组件成功_真实占用租约(self):
        登记统计能力(self.服务)
        登记结果 = self.视图.登记需求(self.令牌, "统计汇总")
        需求id = 登记结果["需求id"]
        self.视图.确认需求(self.令牌, 需求id)
        # 视图申请真实占用租约
        占用结果 = self.视图.申请能力占用(
            self.令牌, "统计.汇总", "统计", "指纹统计", "汇总实现任务")
        self.assertTrue(占用结果["成功"], 占用结果)
        租约id = 占用结果["租约id"]
        self.assertTrue(租约id)
        # 带完整复用决策创建组件（复用决策引用已占用能力，能力id 由租约承载）
        创建结果 = self.视图.创建组件(
            self.令牌, 需求id, 复用决策={"搜索词": "统计", "候选能力id": ["统计.汇总"]},
            资源预算=完整预算(), 允许修改路径=["组件库/统计"],
            组件声明={"名称": "统计汇总组件"}, 能力id="")
        self.assertTrue(创建结果["成功"], 创建结果)
        租约 = self.服务.状态.读取记录("占用租约", "租约id", 租约id)
        self.assertEqual(租约["状态"], "活跃", "真实占用租约保持活跃")
        # 带能力id 创建：服务内部真实申请占用
        创建结果2 = self.视图.创建组件(
            self.令牌, 需求id, 复用决策={"搜索词": "图形", "候选能力id": ["图.绘制"]},
            资源预算=完整预算(), 允许修改路径=["组件库/图"],
            组件声明={"名称": "图形组件"}, 能力id="图.绘制")
        self.assertTrue(创建结果2["成功"], 创建结果2)
        占用表 = self.服务.状态.查询记录("占用租约", "能力id=? AND 状态='活跃'", ("图.绘制",))
        self.assertTrue(占用表, "创建组件内部真实占用租约")

    def test_提交候选包返回制品摘要_文件表真实写入(self):
        登记统计能力(self.服务)
        登记结果 = self.视图.登记需求(self.令牌, "统计候选包")
        需求id = 登记结果["需求id"]
        self.视图.确认需求(self.令牌, 需求id)
        文件表 = {"组件库/统计/统计.py": "def 汇总(数据):\n    return sum(数据)\n"}
        提交结果 = self.视图.提交候选包(
            self.令牌, 需求id, 复用决策={"搜索词": "统计", "候选能力id": ["统计.汇总"]},
            文件表=文件表, 资源预算=完整预算(),
            构建输入={"来源": "组件工作区", "命令": "python3.14 -m unittest"},
            包id="包.统计", 版本="1", 依赖=[])
        self.assertTrue(提交结果["成功"], 提交结果)
        制品摘要 = 提交结果["制品摘要"]
        self.assertTrue(制品摘要)
        制品 = self.服务.状态.读取记录("制品", "制品摘要", 制品摘要)
        self.assertIsNotNone(制品)
        self.assertEqual(制品["包id"], "包.统计")
        制品目录 = self.服务.仓库.制品根目录 / 制品摘要
        正式文件 = 制品目录 / "组件库/统计/统计.py"
        self.assertTrue(正式文件.is_file(), "文件表真实写入制品仓库")
        self.assertEqual(正式文件.read_text(encoding="utf-8"), "def 汇总(数据):\n    return sum(数据)\n")

    def test_复用分析返回候选列表和复用建议(self):
        登记统计能力(self.服务)
        登记结果 = self.视图.登记需求(self.令牌, "统计复用分析")
        需求id = 登记结果["需求id"]
        分析结果 = self.视图.复用分析(self.令牌, 需求id, "统计")
        self.assertTrue(分析结果["成功"], 分析结果)
        候选表 = 分析结果["候选能力表"]
        self.assertTrue(候选表, "必须返回候选能力列表")
        首项 = 候选表[0]
        self.assertEqual(首项["能力id"], "统计.汇总")
        self.assertEqual(首项["中文名称"], "统计组件")
        self.assertTrue(首项["契约指纹"])
        self.assertTrue(首项["候选原因"])
        self.assertEqual(分析结果["复用建议"]["类型"], "新提供者")
        self.assertEqual(分析结果["复用建议"]["首选能力id"], "统计.汇总")
        # 无候选 → 建议新增能力
        空结果 = self.视图.复用分析(self.令牌, 需求id, "不存在的领域")
        self.assertTrue(空结果["成功"], 空结果)
        self.assertEqual(空结果["复用建议"]["类型"], "新增能力")


if __name__ == "__main__":
    unittest.main()
