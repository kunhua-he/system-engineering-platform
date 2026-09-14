"""第十四阶段 工作包05 发布者视图 测试：审核/签名/发布/撤销/回滚/签名失效检查。

全部调用生产实现（统一能力服务 + 包仓库 + 发布管理 + 授权），
临时目录隔离；验证源码变化后旧签名失效真实发生。
"""
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 平台控制面.统一入口 import 统一能力服务
from 平台控制面.授权 import 发布者
from 支持库.适配层 import 生成密钥对
from 开发工具.统一能力入口.视图.发布者视图 import 发布者视图


class Test发布者视图(unittest.TestCase):
    """发布者视图：完整发布工作流与真实签名失效校验。"""

    def setUp(self):
        self.目录 = Path(tempfile.mkdtemp(prefix="发布者视图测试_"))
        self.服务 = 统一能力服务(self.目录)
        self.身份id = "发布者1"
        self.令牌 = self.服务.授权.注册身份(身份id=self.身份id)
        # 引导授予 发布者 角色并切换（受信提权唯一路径）
        成功, 消息 = self.服务.授权.引导授予(身份id=self.身份id, 角色=发布者, 授予者="系统引导")
        self.assertTrue(成功, 消息)
        成功, 消息 = self.服务.授权.切换角色(self.令牌, 发布者)
        self.assertTrue(成功, 消息)
        # 发布者密钥：信任目录登记公钥 + 密钥环导入私钥
        self.私钥, self.公钥 = 生成密钥对()
        self.服务.仓库.登记发布者(发布者=self.身份id, 公钥PEM=self.公钥)
        self.服务.导入签名密钥(身份id=self.身份id, 私钥PEM=self.私钥)
        # 构建候选制品
        成功, 消息, self.制品摘要 = self.服务.仓库.构建制品(
            包id="发布包", 版本="1",
            文件表={"主.py": "print('发布者视图')", "说明.md": "候选发布"},
            构建输入={"源码": "示例源码仓", "构建命令": "python3.14 主.py"})
        self.assertTrue(成功, 消息)
        # 登记并确认需求（发布策略要求已确认需求）
        需求快照 = self.服务.需求.登记需求(目标="发布者视图需求", 调用者=self.身份id, 角色=发布者)
        self.需求id = 需求快照["需求id"]
        成功, 消息 = self.服务.需求.确认需求(需求id=self.需求id, 调用者=self.身份id, 角色=发布者)
        self.assertTrue(成功, 消息)
        self.视图 = 发布者视图(self.服务)

    def test_审核候选返回制品记录(self):
        """测试1：审核候选返回包id/版本/构建输入/来源证据/签名状态。"""
        结果 = self.视图.审核候选(令牌=self.令牌, 制品摘要=self.制品摘要)
        self.assertTrue(结果["成功"], 结果)
        self.assertEqual(结果["包id"], "发布包")
        self.assertEqual(结果["版本"], "1")
        self.assertEqual(结果["构建输入"]["源码"], "示例源码仓")
        self.assertEqual(结果["来源证据"]["构建命令"], "python3.14 主.py")
        self.assertEqual(结果["签名状态"], "未签名")
        self.assertEqual(结果["签名者"], "")

    def test_签名成功且状态变更(self):
        """测试2：签名成功，制品签名状态变更为已签名。"""
        结果 = self.视图.签名(令牌=self.令牌, 制品摘要=self.制品摘要)
        self.assertTrue(结果["成功"], 结果)
        self.assertEqual(结果["发布者"], self.身份id)
        制品 = self.服务.状态.读取记录("制品", "制品摘要", self.制品摘要)
        self.assertEqual(制品["状态"], "已签名")
        self.assertEqual(制品["签名者"], self.身份id)
        self.assertTrue(制品["签名"], "签名值必须真实写入")

    def test_签名与发布完整链路成功(self):
        """测试3：签名与发布全链路（签名→安装→灰度→激活→证据）。"""
        结果 = self.视图.签名与发布(
            令牌=self.令牌, 制品摘要=self.制品摘要, 需求id=self.需求id, 灰度比例=0.1)
        self.assertTrue(结果["成功"], 结果)
        self.assertEqual(结果["激活指针"]["目标"], self.制品摘要)
        self.assertTrue(结果["证据id"], "必须返回证据id")
        # 发布记录进入完成态；安装目录真实存在
        发布表 = self.服务.状态.查询记录("发布", "包id=? AND 状态='完成'", ("发布包",))
        self.assertEqual(len(发布表), 1)
        安装文件 = self.目录 / "已激活" / "发布包" / "主.py"
        self.assertTrue(安装文件.is_file(), "安装目录必须真实落盘")
        self.assertEqual(安装文件.read_text(encoding="utf-8"), "print('发布者视图')")

    def test_撤销成功且发布记录状态变化(self):
        """测试4a：撤销：先读发布状态，再回滚，发布记录状态变化。"""
        结果 = self.视图.签名与发布(
            令牌=self.令牌, 制品摘要=self.制品摘要, 需求id=self.需求id, 灰度比例=0.1)
        self.assertTrue(结果["成功"], 结果)
        发布id = self.服务.状态.查询记录("发布", "包id=? AND 状态='完成'", ("发布包",))[0]["发布id"]
        撤销结果 = self.视图.撤销(令牌=self.令牌, 发布id=发布id, 回滚目标="v1")
        self.assertTrue(撤销结果["成功"], 撤销结果)
        self.assertEqual(撤销结果["撤销前状态"], "完成")
        记录 = self.服务.状态.读取记录("发布", "发布id", 发布id)
        self.assertEqual(记录["状态"], "已回滚")
        指针 = self.服务.发布.当前激活("发布包")
        self.assertEqual(指针["目标"], "v1", "回滚后指针切到回滚目标")

    def test_回滚成功且发布记录状态变化(self):
        """测试4：回滚成功，发布记录状态变化，历史证据保留。"""
        结果 = self.视图.签名与发布(
            令牌=self.令牌, 制品摘要=self.制品摘要, 需求id=self.需求id, 灰度比例=0.1)
        self.assertTrue(结果["成功"], 结果)
        发布id = self.服务.状态.查询记录("发布", "包id=? AND 状态='完成'", ("发布包",))[0]["发布id"]
        回滚结果 = self.视图.回滚(令牌=self.令牌, 发布id=发布id, 回滚目标="v1")
        self.assertTrue(回滚结果["成功"], 回滚结果)
        记录 = self.服务.状态.读取记录("发布", "发布id", 发布id)
        self.assertEqual(记录["状态"], "已回滚")
        self.assertIn("v1", 记录["回滚事务"])
        指针 = self.服务.发布.当前激活("发布包")
        self.assertEqual(指针["目标"], "v1")
        证据 = self.服务.状态.查询证据(主题="发布包", 限制=50)
        self.assertTrue(证据, "发布历史证据必须保留")

    def test_篡改安装文件后签名失效检查必须失败(self):
        """测试5：发布后篡改安装目录真实文件，旧签名必须失效。"""
        结果 = self.视图.签名与发布(
            令牌=self.令牌, 制品摘要=self.制品摘要, 需求id=self.需求id, 灰度比例=0.1)
        self.assertTrue(结果["成功"], 结果)
        # 篡改前：签名有效且磁盘一致
        检查 = self.视图.签名失效检查(令牌=self.令牌, 制品摘要=self.制品摘要)
        self.assertTrue(检查["成功"], 检查)
        # 篡改安装目录中真实文件（源码变化）
        安装文件 = self.目录 / "已激活" / "发布包" / "主.py"
        self.assertTrue(安装文件.is_file())
        安装文件.write_text(安装文件.read_text(encoding="utf-8") + "\n# 被篡改\n", encoding="utf-8")
        # 再次签名验证必须失败：重算摘要与签名覆盖摘要不一致
        检查2 = self.视图.签名失效检查(令牌=self.令牌, 制品摘要=self.制品摘要)
        self.assertFalse(检查2["成功"], "源码变化后旧签名必须失效")
        self.assertIn("篡改", 检查2["消息"])
        self.assertIn("被篡改", 检查2["检查表"]["安装目录"]["差异表"][0])
        self.assertEqual(检查2["检查表"]["安装目录"]["一致"], False)
        # 制品仓库未动 → 仓库级校验仍有效，差异真实定位在安装目录
        有效, _ = self.服务.仓库.校验签名(制品摘要=self.制品摘要)
        self.assertTrue(有效, "制品仓库未被篡改时仓库校验应仍有效")

    def test_按角色过滤且视图不提供非发布操作(self):
        """测试6：越权拒绝（按角色过滤）与视图边界（无非发布操作）。"""
        # 视图边界：只暴露发布操作面，不提供需求确认/组件创建/诊断等
        for 方法名 in ("需求确认", "创建组件", "查看诊断", "提交候选包", "调用能力"):
            self.assertFalse(hasattr(self.视图, 方法名),
                             f"视图不得提供非发布操作: {方法名}")
        # 未授予发布者角色（普通用户等级1）执行签名与发布 → 等级不足被拒
        令牌普通 = self.服务.授权.注册身份(身份id="访客1")
        结果 = self.服务.执行操作(令牌=令牌普通, 操作="签名与发布",
                                 参数={"制品摘要": self.制品摘要})
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "PERMISSION_DENIED")
        # 发布者未授予平台维护者角色 → 切换被拒（角色不可自举）
        成功, _ = self.服务.授权.切换角色(self.令牌, "平台维护者")
        self.assertFalse(成功)


if __name__ == "__main__":
    unittest.main()
