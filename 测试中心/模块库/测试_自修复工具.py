"""模块库.自修复工具 组合能力真实端到端测试（HTTP 网关装配）。

setUpClass 启动真实后端与本地回环网关并装配 HTTP连接器，模块公开能力
全部经真实 HTTP 网关调用；保留既有进程内装配用例（注册支持库能力+注入
全局唯一服务）与真实 git 流程用例。

覆盖：worktree 创建→补丁应用→验证→提交→挑拣合入→回滚→验证还原；
补丁多重匹配/路径逃逸/验证失败不提交/回滚失败中止/未提交修改拒绝；
平台不可用（连接器未装配如实返回 提供者不可用）；参数错误；
获取当前提交哈希；零残留（临时仓库/worktree/进程/登记临时资源全清理）。

注：本地进程适配器属适配层豁免包，装配系统不自动收录
“本地进程.执行命令受控”，setUpClass 按真实提供者补注册到后端，
保证 验证修复 的受管验证命令可经 HTTP 网关执行。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 模块库.自修复工具 import 创建修复工作区, 获取当前提交哈希, 回滚修复, 验证修复
from 支持库.后端.文件系统支持库.文件操作 import 清理全部临时资源
from 支持库.后端.系统核心支持库.资源管理 import 创建内容摘要
from 后端核心.后端核心 import 后端核心
from 运行核心.统一网关.网关核心 import 网关核心
from 运行核心.统一网关.本地网关 import 本地网关服务器
from 运行核心.能力调用.HTTP连接器 import HTTP连接器

def 运行命令(命令列表: list[str], 工作目录: str) -> subprocess.CompletedProcess:
    return subprocess.run(命令列表, cwd=工作目录, capture_output=True, text=True)

def 装配能力调用器() -> None:
    """真实装配：注册支持库能力与模块能力，注入唯一能力调用服务。"""
    from 公共契约.能力契约.契约 import 能力注册表
    from 运行核心.能力调用.唯一能力调用 import 设置全局唯一服务, 唯一能力调用服务
    from 支持库.后端.版本控制支持库.Git操作 import 注册能力 as 注册Git
    from 支持库.后端.文件系统支持库.文件操作 import 注册能力 as 注册文件系统
    from 支持库.后端.系统核心支持库.资源管理 import 注册能力 as 注册资源管理
    # 2026-09-19（开工-20260919-193541-2a8e）：模块实现调用的是
    # `系统核心支持库.进程管理.执行命令`（进程管理包的正式能力，已存在），
    # 而本测试原先自造 `本地进程.执行命令受控` 并注册适配器实现 —— 那是
    # 模块早期的能力 id，早已换成正式能力，测试夹具没跟，导致 3 个用例长期
    # 报「能力未注册」（此前该测试文件 import 即失败，缺陷被掩盖）。
    # 修法：按生产真源注册 进程管理 包（不自造第二份能力声明）。
    from 支持库.后端.系统核心支持库.进程管理 import 注册能力 as 注册进程管理
    from 模块库.自修复工具 import 注册能力 as 注册自修复

    注册表 = 能力注册表()
    注册Git(注册表)
    注册文件系统(注册表)
    注册资源管理(注册表)
    注册进程管理(注册表)
    注册自修复(注册表)
    设置全局唯一服务(唯一能力调用服务(注册表))

def 卸载能力调用器() -> None:
    from 运行核心.能力调用.唯一能力调用 import 设置全局唯一服务
    设置全局唯一服务(None)

class Test自修复工具(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """启动真实后端和随机回环网关，所有测试请求走 HTTP。"""
        cls.后端 = 后端核心()
        启动结果 = cls.后端.启动()
        if not 启动结果.成功:
            raise RuntimeError(f"后端核心启动失败: {启动结果.错误说明}")
        # 本地进程适配器属适配层豁免包（无 包声明.json），装配系统不收录其
        # 能力；按真实提供者补注册，保证 验证修复 的受管验证命令经网关可执行。
        from 支持库.适配层.本地进程适配器 import 本地进程适配器
        注册结果 = cls.后端.注册能力(
            "本地进程.执行命令受控",
            本地进程适配器().执行命令受控,
            参数=[{"名称": "命令列表", "类型": "列表"},
                  {"名称": "超时秒", "类型": "浮点数"},
                  {"名称": "输出上限字节", "类型": "整数"},
                  {"名称": "工作目录", "类型": "文本"}],
            返回="结果",
            说明="验证命令受管执行（真实子进程）",
        )
        if not 注册结果.成功:
            cls.后端.优雅关闭()
            raise RuntimeError(f"本地进程能力补注册失败: {注册结果.错误说明}")
        cls.网关 = 本地网关服务器(
            网关核心实例=网关核心(cls.后端), 地址="127.0.0.1", 端口=0,
            # 请求超时秒 取平台口径 1800（运行核心/启动运行核心网关.py:44；本地网关默认同值）：
            # 10 会把能力契约声明的 超时秒=60/300 判成「超时时间超出允许范围」而全红。
            配置={"请求超时秒": 1800, "要求凭证": False, "禁止客户端身份": False},
        )
        成功, 说明 = cls.网关.启动()
        if not 成功:
            cls.后端.优雅关闭()
            raise RuntimeError(f"网关启动失败: {说明}")

    @classmethod
    def tearDownClass(cls):
        cls.网关.优雅停止()
        cls.后端.优雅关闭()

    def setUp(self):
        """真实临时 git 仓库：初始提交含 待修复文件与 重复文本文件。"""
        self.临时根 = Path(tempfile.mkdtemp(prefix="测试_自修复工具_"))
        仓库目录 = self.临时根 / "仓库"
        仓库目录.mkdir()
        for 参数 in (["git", "init", "-b", "主干"], ["git", "config", "user.email", "测试@本地"], ["git", "config", "user.name", "测试者"]):
            subprocess.run(参数, cwd=仓库目录, check=True, capture_output=True)
        self.仓库 = 仓库目录
        (仓库目录 / "修复目标.txt").write_text(
            "第一行\n旧版本内容\n第三行\n", encoding="utf-8")
        (仓库目录 / "重复文本.txt").write_text(
            "重复出现\n重复出现\n", encoding="utf-8")
        运行命令(["git", "add", "."], str(仓库目录))
        运行命令(["git", "commit", "-m", "初始提交"], str(仓库目录))
        装配能力调用器()

    def tearDown(self):
        卸载能力调用器()
        清理全部临时资源()
        shutil.rmtree(self.临时根, ignore_errors=True)

    def 补丁(self, 文件: str = "修复目标.txt") -> list:
        return [{"文件": 文件, "旧内容": "旧版本内容", "新内容": "新修复内容"}]

    def 验证命令(self, 期望文本: str = "新修复内容") -> list:
        断言 = f"import sys; c=open('修复目标.txt',encoding='utf-8').read(); sys.exit(0 if '{期望文本}' in c else 1)"
        return ["python3.14", "-c", 断言]

    def test_端到端创建验证提交回滚还原(self):
        """worktree 创建→补丁应用→验证通过→提交→挑拣合入→回滚→验证还原。"""
        创建 = 创建修复工作区(
            str(self.仓库), self.补丁(), self.验证命令(), "修复提交")
        self.assertTrue(创建.成功, 创建.错误说明)
        值 = 创建.值
        self.assertTrue(值["提交"])
        self.assertEqual(值["工作区清理"], "已关闭")
        # 主仓库未被直接修改（修复在独立 worktree 中）
        原始内容 = (self.仓库 / "修复目标.txt").read_text(encoding="utf-8")
        self.assertNotIn("新修复内容", 原始内容)
        # 挑拣合入修复提交到主仓库
        挑拣 = 回滚修复(str(self.仓库), 值["提交"], 操作="挑拣合入")
        self.assertTrue(挑拣.成功, 挑拣.错误说明)
        self.assertIn("新修复内容",
                      (self.仓库 / "修复目标.txt").read_text(encoding="utf-8"))
        # 验证修复（主仓库上再次定向验证）
        验证 = 验证修复(str(self.仓库), self.验证命令())
        self.assertTrue(验证.成功, 验证.错误说明)
        # 回滚：git revert 撤销修复提交
        回滚 = 回滚修复(str(self.仓库), 值["提交"], 操作="回滚")
        self.assertTrue(回滚.成功, 回滚.错误说明)
        self.assertIn("新提交", 回滚.值)
        还原后 = (self.仓库 / "修复目标.txt").read_text(encoding="utf-8")
        self.assertNotIn("新修复内容", 还原后)
        self.assertIn("旧版本内容", 还原后)

    def test_验证摘要比对通过与不匹配(self):
        """期望摘要匹配通过；不匹配返回 验证失败。"""
        正确摘要结果 = 创建内容摘要(self.仓库 / "修复目标.txt")
        # #92（2026-09-21）：本能力改为返回 结果 信封，期望摘要要取 `.值` ——
        # 直接传 结果 对象会让 验证修复 里「str 比 结果」恒不匹配（实测报 内容摘要不匹配）。
        self.assertTrue(正确摘要结果.成功, 正确摘要结果.错误说明)
        正确摘要 = 正确摘要结果.值
        通过 = 验证修复(str(self.仓库), ["git", "status"], 正确摘要, "修复目标.txt")
        self.assertTrue(通过.成功, 通过.错误说明)
        self.assertEqual(通过.值["摘要"], 正确摘要)
        失败 = 验证修复(
            str(self.仓库), ["git", "status"], "0" * 64, "修复目标.txt")
        self.assertFalse(失败.成功)
        self.assertEqual(失败.错误码, "验证失败")

    def test_补丁多重匹配拒绝(self):
        """旧内容出现 2 次 → 补丁多重匹配，不提交不产生工作区残留。"""
        创建 = 创建修复工作区(
            str(self.仓库), self.补丁("重复文本.txt"), ["git", "status"],
            "不应提交")
        self.assertFalse(创建.成功)
        self.assertEqual(创建.错误码, "补丁多重匹配")
        # 主仓库没有新提交
        日志 = 运行命令(["git", "log", "--oneline"], str(self.仓库))
        self.assertEqual(len(日志.stdout.strip().splitlines()), 1)
        # 零残留：临时宿主/worktree 目录已被清理
        self.assertEqual(清理全部临时资源().成功, True)

    def test_路径逃逸拒绝(self):
        """补丁文件 ../ 或绝对路径 → 路径逃逸拒绝。"""
        for 文件 in ("../逃逸.txt", "/etc/逃逸.txt", ""):
            with self.subTest(文件=文件):
                创建 = 创建修复工作区(
                    str(self.仓库),
                    [{"文件": 文件, "旧内容": "x", "新内容": "y"}],
                    ["git", "status"], "不应提交")
                self.assertFalse(创建.成功)
                self.assertEqual(创建.错误码, "路径逃逸")

    def test_验证失败不提交(self):
        """验证命令退出码非零 → 验证失败，主仓库无新提交。"""
        创建 = 创建修复工作区(
            str(self.仓库), self.补丁(),
            ["python3.14", "-c", "import sys; sys.exit(3)"], "不应提交")
        self.assertFalse(创建.成功)
        self.assertEqual(创建.错误码, "验证失败")
        日志 = 运行命令(["git", "log", "--oneline"], str(self.仓库))
        self.assertEqual(len(日志.stdout.strip().splitlines()), 1)
        self.assertEqual(清理全部临时资源().成功, True)

    def test_回滚失败中止(self):
        """挑拣合入不存在的提交 → 回滚失败；冲突自动中止保持干净。"""
        失败 = 回滚修复(str(self.仓库), "a" * 7, 操作="挑拣合入")
        self.assertFalse(失败.成功)
        self.assertEqual(失败.错误码, "回滚失败")
        # 冲突自动中止后仓库保持干净、无残留冲突状态
        状态 = 运行命令(["git", "status", "--porcelain"], str(self.仓库))
        self.assertEqual(状态.stdout.strip(), "")

    def test_未提交修改拒绝回滚(self):
        """主仓库存在未提交修改 → 未提交修改 拒绝。"""
        (self.仓库 / "修复目标.txt").write_text("脏修改\n", encoding="utf-8")
        结果 = 回滚修复(str(self.仓库), "a" * 7, 操作="回滚")
        self.assertFalse(结果.成功)
        self.assertEqual(结果.错误码, "未提交修改")

    def test_获取当前提交哈希(self):
        """获取当前提交哈希与分支（经 HTTP 网关 Git操作 能力）。"""
        结果 = 获取当前提交哈希(str(self.仓库))
        self.assertTrue(结果.成功, 结果.错误说明)
        实际哈希 = 运行命令(["git", "rev-parse", "HEAD"], str(self.仓库)).stdout.strip()
        self.assertEqual(结果.值["提交哈希"], 实际哈希)
        self.assertEqual(结果.值["分支"], "主干")

    def test_平台不可用如实失败(self):
        """未装配调用器 → 返回 提供者不可用，不抛异常。

        2026-09-19（开工-20260919-193541-2a8e）：模块不再自持连接器；要测
        「不可用」须同时停用惰性装配钩子，否则下次获取会把调用器装回来。
        """
        原惰性装配 = _停用惰性装配()
        try:
            结果 = 创建修复工作区(
                str(self.仓库), self.补丁(), self.验证命令(), "不应提交")
            self.assertFalse(结果.成功)
            self.assertEqual(结果.错误码, "提供者不可用")
            # 验证命令执行失败按原语义包装为 验证失败（不抛异常如实失败）
            验证 = 验证修复(str(self.仓库), ["git", "status"])
            self.assertFalse(验证.成功)
            self.assertEqual(验证.错误码, "验证失败")
        finally:
            _恢复惰性装配(原惰性装配)

    def test_平台不可用返回提供者不可用(self):
        """卸载调用器后调用能力：模块返回 提供者不可用，不抛异常。"""
        原惰性装配 = _停用惰性装配()
        try:
            结果 = 获取当前提交哈希(str(self.仓库))
            self.assertFalse(结果.成功)
            self.assertEqual(结果.错误码, "提供者不可用")
        finally:
            _恢复惰性装配(原惰性装配)

    def test_参数错误(self):
        """提交消息为空/验证命令非列表/操作非法/补丁列表为空 → 参数不合法。"""
        with self.subTest(场景="提交消息为空"):
            结果 = 创建修复工作区(
                str(self.仓库), self.补丁(), self.验证命令(), "  ")
            self.assertFalse(结果.成功)
            self.assertEqual(结果.错误码, "参数不合法")
        with self.subTest(场景="验证命令非列表"):
            结果 = 验证修复(str(self.仓库), "git status")
            self.assertFalse(结果.成功)
            self.assertEqual(结果.错误码, "参数不合法")
        with self.subTest(场景="操作非法"):
            结果 = 回滚修复(str(self.仓库), "a" * 7, 操作="未知操作")
            self.assertFalse(结果.成功)
            self.assertEqual(结果.错误码, "参数不合法")
        with self.subTest(场景="补丁列表为空"):
            结果 = 创建修复工作区(
                str(self.仓库), [], ["git", "status"], "不应提交")
            self.assertFalse(结果.成功)
            self.assertEqual(结果.错误码, "参数不合法")

    def test_零残留(self):
        """创建全程后：无 worktree、宿主临时目录已自释放、登记表不留残留（F-4 回归）。

        修复前：成功路径只 `登记临时资源`，而 `清理全部临时资源` 全仓非测试代码无调用方
        → 宿主目录 + 登记项都留在进程里没人清（目录越积越多）。
        修复后：关闭工作区成功即在收口处自释放（真删目录 + 清登记项）；只有关闭失败
        （可能有残留，如未提交修改）才登记留痕交兜底收口。
        """
        from 支持库.后端.文件系统支持库.文件操作.实现.文件系统 import _临时资源登记表
        登记前 = list(_临时资源登记表)
        创建 = 创建修复工作区(
            str(self.仓库), self.补丁(), self.验证命令(), "修复提交")
        self.assertTrue(创建.成功, 创建.错误说明)
        清单 = 运行命令(["git", "worktree", "list"], str(self.仓库))
        # 创建成功后 worktree 已关闭，仅主工作区
        self.assertEqual(len(清单.stdout.strip().splitlines()), 1)
        # 零残留：宿主临时目录被真删（不是「登记了等人清」）
        工作区路径 = (创建.值 or {}).get("路径", "")
        self.assertTrue(工作区路径, "成功结果必须带工作区路径")
        宿主目录 = Path(工作区路径).parent
        self.assertFalse(宿主目录.exists(),
                         f"成功路径必须自释放宿主临时目录，仍存在: {宿主目录}")
        self.assertFalse([项 for 项 in _临时资源登记表 if 项 not in 登记前],
                         "成功路径不得留下临时资源登记项")
        清理 = 清理全部临时资源()
        self.assertTrue(清理.成功, 清理.错误说明)
        self.assertFalse(_临时资源登记表, "清理后登记表应为空")


def _停用惰性装配():
    """停用惰性装配钩子并卸下调用器，返回原钩子（供「调用器不可用」用例使用）。

    2026-09-19（开工-20260919-193541-2a8e）：模块不再自持 `设置HTTP连接器`，
    只经 `获取能力调用器()` 取注入调用器。卸载调用器后若不**同时**停用惰性装配
    钩子，下一次获取会触发惰性装配把调用器装回来 —— 用例就测不到「不可用」分支。
    """
    from 公共契约.能力契约.调用器 import 设置惰性装配函数, 注册能力调用器
    原惰性装配 = 设置惰性装配函数.__globals__.get("_惰性装配函数")
    设置惰性装配函数(None)
    注册能力调用器(None)
    return 原惰性装配


def _恢复惰性装配(原惰性装配) -> None:
    """还原惰性装配钩子并重新装配（后续用例不受影响）。"""
    from 公共契约.能力契约.调用器 import 设置惰性装配函数
    from 运行核心.能力调用.唯一能力调用 import 创建并绑定
    设置惰性装配函数(原惰性装配)
    创建并绑定()

if __name__ == "__main__":
    unittest.main()
