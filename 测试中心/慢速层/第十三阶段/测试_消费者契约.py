"""第十三阶段：消费者契约注册与真实回归测试。

契约注册：固定 12 稳定操作的 请求/返回结构键、错误码集合、权限要求、
超时与资源释放行为（契约文件：契约编译/消费者契约.py，新增文件不改共享实现）。
真实回归：subprocess 真实执行三个消费者（适配层示例 / 前后端核心示例 /
平台控制面示例），unset PYTHONPATH，断言退出码 0 与关键输出模式；
契约断言：错误码集合 / 结果结构键 与真实执行结果一致。
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[3]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 开发工具.契约编译.消费者契约 import (消费者契约, 稳定操作表, 操作契约, 全局错误码,
                             错误码全集, 角色等级表, 超时约定, 校验契约)
from 平台控制面.统一入口 import 统一能力服务, 允许验证命令, 验证输出上限
from 平台控制面.统一入口 import 稳定操作表 as 实现稳定操作表
from 平台控制面.授权 import 操作最小角色


class Test消费者契约注册(unittest.TestCase):
    """契约与真实实现一致：操作表 / 权限 / 错误码 / 结构键 / 超时 / 资源释放。"""

    def test_契约自检通过(self):
        通过, 问题表 = 校验契约()
        self.assertTrue(通过, f"契约自检失败: {问题表}")

    def test_稳定操作表固定12项与统一入口一致(self):
        self.assertEqual(稳定操作表, 实现稳定操作表, "契约操作表与实现漂移")
        self.assertEqual(len(稳定操作表), 12)

    def test_权限要求与授权表一致(self):
        # 授权表还含非 12 操作条目（登记需求/复用裁决/管理信任/监督资源），
        # 契约只固定 12 稳定操作：契约操作集合必须是授权表的子集且逐项一致
        self.assertLessEqual(set(操作契约), set(操作最小角色), "契约含未授权操作")
        for 操作, 项 in 操作契约.items():
            self.assertIn(项["最小角色"], 角色等级表, f"{操作} 角色非法")
            self.assertEqual(
                角色等级表[项["最小角色"]], 操作最小角色[操作],
                f"{操作} 权限与 授权.操作最小角色 漂移")

    def test_错误码全集闭合(self):
        for 码 in 全局错误码:
            self.assertIn(码, 错误码全集, f"全局错误码 {码} 不在全集")
        for 操作, 项 in 操作契约.items():
            for 码 in 项["错误码"]:
                self.assertIn(码, 错误码全集, f"{操作} 错误码 {码} 不在全集")
        self.assertEqual(错误码全集, sorted(set(错误码全集)), "全集必须去重排序")

    def test_超时与资源释放契约固定(self):
        self.assertEqual(超时约定["验证组件默认秒"], 30.0)
        self.assertEqual(超时约定["验证输出上限字节"], 验证输出上限)
        self.assertEqual(超时约定["调用能力默认秒"], 5.0)
        self.assertEqual(set(超时约定["验证命令白名单"]), 允许验证命令)
        for 操作, 项 in 操作契约.items():
            self.assertTrue(项["超时"], f"{操作} 缺超时声明")
            self.assertTrue(项["资源释放"], f"{操作} 缺资源释放声明")

    def test_真实错误码在契约集合内(self):
        """真实执行 无效参数/未知操作/越权/未注册能力 → 错误码落在契约集合。"""
        目录 = Path(tempfile.mkdtemp(prefix="消费者契约_"))
        服务 = 统一能力服务(目录)
        try:
            访客令牌 = 服务.授权.注册身份(身份id="契约访客")        # 默认普通用户
            开发令牌 = 服务.授权.注册身份(身份id="契约开发Agent")
            服务.授权.引导授予(身份id="契约开发Agent", 角色="组件开发Agent",
                              授予者="系统引导")
            服务.授权.切换角色(开发令牌, "组件开发Agent")
            场景表 = [
                (开发令牌, "确认需求", {}, "REQUIREMENT_REQUIRED"),
                (访客令牌, "查看能力", {}, "CAPABILITY_REQUIRED"),
                (访客令牌, "查看诊断", {}, "PERMISSION_DENIED"),
                (访客令牌, "不存在.操作", {}, "UNKNOWN_OPERATION"),
                (开发令牌, "调用能力", {"能力id": "不存在.能力"},
                 "CAPABILITY_NOT_FOUND"),
            ]
            for 令牌, 操作, 参数, 期望码 in 场景表:
                结果 = 服务.执行操作(令牌=令牌, 操作=操作, 参数=参数)
                self.assertFalse(结果["成功"], f"{操作} 应失败")
                self.assertEqual(结果["错误码"], 期望码, f"{操作} 错误码漂移")
                允许表 = set(全局错误码) | set(操作契约.get(操作, {}).get("错误码", []))
                self.assertIn(结果["错误码"], 允许表,
                              f"{操作} 错误码 {结果['错误码']} 不在契约集合")
        finally:
            服务.状态.关闭()

    def test_返回结构键在契约内(self):
        """真实成功路径返回键 ⊆ 契约返回键，且含统一键 成功/操作/调用者。"""
        目录 = Path(tempfile.mkdtemp(prefix="消费者契约_"))
        服务 = 统一能力服务(目录)
        try:
            访客令牌 = 服务.授权.注册身份(身份id="契约访客")
            结果 = 服务.执行操作(令牌=访客令牌, 操作="搜索能力",
                                参数={"关键词": "文本", "限制": 5})
            self.assertTrue(结果["成功"])
            self.assertIsInstance(结果["结果表"], list)
            self.assertLessEqual(set(结果), set(操作契约["搜索能力"]["返回键"]),
                                 "搜索能力 返回键超出契约声明")
            self.assertIn("成功", 结果)
            self.assertIn("操作", 结果, "执行操作 统一追加 操作 键")
            self.assertIn("调用者", 结果, "执行操作 统一追加 调用者 键")
        finally:
            服务.状态.关闭()


class Test消费者真实回归(unittest.TestCase):
    """三个消费者示例真实执行：subprocess + 退出码 0 + 关键输出模式。"""

    超时上限秒 = 180

    def _真实执行消费者(self, 消费者项: dict) -> str:
        入口 = 系统根 / 消费者项["入口"]
        self.assertTrue(入口.is_file(), f"消费者入口不存在: {入口}")
        环境 = dict(os.environ)
        环境.pop("PYTHONPATH", None)  # 铁律：unset PYTHONPATH
        进程 = subprocess.run(
            [sys.executable, str(入口)], cwd=str(系统根), env=环境,
            capture_output=True, text=True, timeout=self.超时上限秒)
        输出 = (进程.stdout or "") + (进程.stderr or "")
        失败说明 = f"退出码={进程.returncode}，输出尾部: {输出[-500:]}"
        self.assertEqual(进程.returncode, 消费者项["退出码"], 失败说明)
        for 模式 in 消费者项["关键输出"]:
            self.assertIn(模式, 输出, f"缺少关键输出「{模式}」: {失败说明}")
        return 输出

    def test_适配层示例真实执行(self):
        self._真实执行消费者(消费者契约[0])

    def test_前后端核心示例真实执行(self):
        self._真实执行消费者(消费者契约[1])

    def test_平台控制面示例真实执行(self):
        self._真实执行消费者(消费者契约[2])


if __name__ == "__main__":
    unittest.main()
