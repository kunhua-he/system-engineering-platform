"""第十四阶段 P1-01 普通用户视图测试：角色过滤 / 详情不泄密 / 真实调用 / 失败建议。

调用生产实现 普通用户视图 + 统一能力服务（临时存储目录），不复制简化算法。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 开发工具.统一能力入口.视图.普通用户视图 import 普通用户视图
from 平台控制面.统一入口 import 统一能力服务


def 完整预算() -> dict:
    return {"内存上限": 100, "线程上限": 4, "子进程上限": 1, "并发调用上限": 4,
            "队列长度": 10, "文件句柄上限": 50, "临时空间上限": 100,
            "单次调用超时": 5, "每分钟重启次数": 2, "空闲回收时间": 60}


def 提权(服务: 统一能力服务, 身份id: str, 角色: str) -> str:
    """受信引导夹具：注册 → 引导授予 → 切换；返回令牌。"""
    令牌 = 服务.授权.注册身份(身份id=身份id)
    成功, 消息 = 服务.授权.引导授予(身份id=身份id, 角色=角色, 授予者="系统引导")
    assert 成功, 消息
    成功, 消息 = 服务.授权.切换角色(令牌, 角色)
    assert 成功, 消息
    return 令牌


def 搭建(秘密: str = ""):
    """临时服务：登记能力 + 注册返回 42 的提供者 + 可选导入密钥。"""
    目录 = Path(tempfile.mkdtemp(prefix="视图测试_"))
    服务 = 统一能力服务(目录)
    服务.目录.登记能力(
        能力id="计算.求值", 组件="示例组件", 领域="计算", 成熟度="实验",
        契约={"能力id": "计算.求值", "名称": "求值",
              "参数": [{"名称": "数值", "类型": "整数"}],
              "返回": {}, "错误码": [], "副作用": "无", "宿主": "后端", "权限": ""},
        资源={"参数说明": [{"名称": "数值", "说明": "要计算的数值"}]})
    服务.注册提供者(能力id="计算.求值", 函数=lambda 数值: 42, 预算=完整预算())
    if 秘密:
        服务.导入签名密钥(身份id="发布者1", 私钥PEM=秘密)
    令牌 = 服务.授权.注册身份(身份id="普通用户1")
    return 普通用户视图(服务), 令牌, 服务


class Test普通用户视图(unittest.TestCase):
    """普通用户视图：角色过滤 / 详情不泄密 / 真实调用 / 失败建议。"""

    def setUp(self):
        self.视图, self.令牌, self.服务 = 搭建(秘密="私钥测试内容_勿外泄")

    def test_普通用户只看到搜索与查看能力(self):
        摘要 = self.视图.展示能力摘要()
        操作表 = [项["操作名"] for 项 in 摘要]
        self.assertEqual(sorted(操作表), ["搜索能力", "查看能力"], "角色过滤真实生效")
        全部文案 = json.dumps(摘要, ensure_ascii=False)
        for 禁词 in ("签名与发布", "调用能力", "查看诊断", "回滚", "创建组件"):
            self.assertNotIn(禁词, 全部文案, f"普通用户摘要不得出现: {禁词}")
        self.assertEqual({项["可用状态"] for 项 in 摘要}, {"可用"},
                         "可用状态来自真实状态快照")

    def test_查看能力详情返回中文且不含密钥日志路径(self):
        详情 = self.视图.查看能力详情("计算.求值")
        self.assertTrue(详情["成功"])
        self.assertEqual(详情["中文名称"], "计算.求值")
        self.assertIn("示例组件", 详情["作用"])
        self.assertEqual(详情["输入参数说明"],
                         [{"名称": "数值", "说明": "要计算的数值"}])
        self.assertIn("调用Agent", 详情["权限要求"])
        self.assertEqual(详情["可用状态"], "可用")
        self.assertIn("处理建议", 详情)
        文案 = json.dumps(详情, ensure_ascii=False)
        for 禁词 in ("私钥测试内容_勿外泄", "日志", "契约指纹",
                     str(self.服务.状态.存储目录), "统一入口.py"):
            self.assertNotIn(禁词, 文案, f"详情不得出现: {禁词}")

    def test_调用能力真实返回结果(self):
        agent令牌 = 提权(self.服务, "调用Agent1", "调用Agent")
        结果 = self.视图.调用能力(agent令牌, "计算.求值", {"数值": 5})
        self.assertTrue(结果["成功"])
        self.assertEqual(结果["结果"], 42, "真实调用提供者返回结果")
        self.assertEqual(结果["错误码"], "")
        self.assertEqual(结果["处理建议"], "操作成功，无需处理")

    def test_失败返回错误码与中文建议(self):
        普通结果 = self.视图.调用能力(self.令牌, "计算.求值", {})
        self.assertFalse(普通结果["成功"])
        self.assertEqual(普通结果["错误码"], "PERMISSION_DENIED")
        self.assertEqual(普通结果["处理建议"], "当前账号没有该操作权限")
        self.assertEqual(普通结果["消息"], "当前账号没有该操作权限")
        agent令牌 = 提权(self.服务, "调用Agent2", "调用Agent")
        结果 = self.视图.调用能力(agent令牌, "不存在的能力", {})
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "CAPABILITY_NOT_FOUND")
        self.assertEqual(结果["处理建议"], "该功能暂不可用，请稍后再试")
        self.assertNotIn("不存在的能力", 结果["消息"], "失败消息为中文建议，不含内部原文")

    def test_视图输出不含源码路径与密钥内容(self):
        输出 = json.dumps({
            "摘要": self.视图.展示能力摘要(),
            "详情": self.视图.查看能力详情("计算.求值"),
            "建议": self.视图.失败处理建议(
                {"成功": False, "错误码": "PERMISSION_DENIED"})},
            ensure_ascii=False)
        for 禁词 in ("私钥测试内容_勿外泄", "统一入口.py",
                     str(self.服务.状态.存储目录), "验证缓存"):
            self.assertNotIn(禁词, 输出, f"视图输出不得出现: {禁词}")


if __name__ == "__main__":
    unittest.main()
