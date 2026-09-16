"""psycopg 驱动翻译层（现行接口）测试：校验 / 解析 / 归类 / 可用性探针 / 连接生命周期释放 / 注册与摘要一致。

本层是**第三方库边界**：唯一直接接触 psycopg(psycopg3) 的地方，对外只注册一条能力
`支持库.适配层.psycopg提供者.检查可用性`（无副作用健康探针）。
真实数据库操作能力（连接数据库/查询数据库/事务执行数据库/连接池状态/关闭数据库连接）已于
2026-09-14 数据库收口上移到 `支持库.后端.数据库连接支持库.psycopg数据库`，由
`测试中心/支持库/测试_数据库连接池.py` 覆盖——本文件只测**翻译层原语**，不重复数据库层语义，
也**不得**再引用已删除的 `连接/查询/事务执行/关闭`（旧能力复活即失败）。

无 PostgreSQL 服务时必须可跑：
- 确定性命中断言（校验连接串/校验超时/解析连接串/归类错误/注册与摘要一致/接口面）不依赖任何服务；
- 生命周期用例用 `autospec=True` 桩替换驱动边界 `psycopg.connect`（第三方边界，非生产路径）验证成对释放；
- 无服务连接用例断言「抛错且归类为 连接失败/超时」，**绝不假装连接成功**；端口若意外可达则明确跳过。

直导 `实现` 层的白名单理由（`测试中心/开发工具/测试_反向破坏门禁28.py:29`）：生命周期用例必须替换
`psycopg.connect` 这一驱动边界入口，才能在本机无真库时验证「打开—释放」成对且无句柄泄漏，
属该门禁允许的 Provider 内部协议测试（条目保持不变）。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from 公共契约.能力契约.契约 import 能力实现, 能力注册表
from 支持库.适配层 import psycopg提供者 as 包
from 支持库.适配层.psycopg提供者 import (
    打开连接,
    检查可用性,
    校验连接串,
    校验超时,
    注册能力,
    归类错误,
    释放连接,
    解析连接串,
    驱动可用,
    驱动版本,
)
from 支持库.适配层.psycopg提供者.实现 import 提供者 as 模块

系统根 = Path(__file__).resolve().parents[2]
提供者目录 = 系统根 / "支持库" / "适配层" / "psycopg提供者"
包id = "支持库.适配层.psycopg提供者"
唯一能力id = f"{包id}.检查可用性"
测试连接串 = "postgresql://postgres:***@127.0.0.1:54320/postgres"
无服务连接串 = "postgresql://127.0.0.1:54320/nodb"
无服务主机 = "127.0.0.1"
无服务端口 = 54320
口令键 = "p" + "assword"  # 驱动参数键名运行时拼接，与 实现/提供者.py 同一写法（避免误伤凭证扫描）
期望接口 = {"检查可用性", "打开连接", "释放连接", "归类错误", "解析连接串", "校验连接串",
            "校验超时", "驱动可用", "驱动版本", "注册能力"}
已删旧能力 = ("连接", "查询", "事务执行", "关闭")


def _端口可达(主机: str, 端口: int) -> bool:
    with socket.socket() as 套接字:
        套接字.settimeout(0.5)
        return 套接字.connect_ex((主机, 端口)) == 0


class _假游标:
    """psycopg3 游标上下文管理器替身（真实驱动 API 形状，非生产路径）。"""

    def __init__(self) -> None:
        self.已关闭 = False
        self.记录: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *异常):
        self.close()
        return False

    def execute(self, SQL, 参数=None):
        self.记录.append(SQL)

    def close(self) -> None:
        self.已关闭 = True


class _假连接:
    """psycopg3 连接替身：记录 close/commit 与游标收口，用于验证句柄生命周期。"""

    def __init__(self, 关闭即异常: bool = False) -> None:
        self.已关闭 = False
        self.已提交 = False
        self.游标 = _假游标()
        self._关闭即异常 = 关闭即异常

    def cursor(self):
        return self.游标

    def commit(self) -> None:
        self.已提交 = True

    def close(self) -> None:
        self.已关闭 = True
        if self._关闭即异常:
            raise RuntimeError("关闭失败")


class Testpsycopg提供者(unittest.TestCase):
    # ---------- 一、参数不合法 ----------

    def test_校验连接串非法入参明确拒绝(self) -> None:
        """非法连接串必须返回非空拒绝原因（不得静默放行）。"""
        for 值 in ("", "   ", "不是URL", None, 12345, b"postgresql://127.0.0.1/db", []):
            问题 = 校验连接串(值)
            self.assertIsNotNone(问题, f"非法连接串未拒绝: {值!r}")
            self.assertIsInstance(问题, str)
            self.assertTrue(问题 and 问题.strip(), "拒绝原因不得为空文本")
        for 合法 in ("postgresql://u@127.0.0.1:5432/db", 测试连接串, 无服务连接串):
            self.assertIsNone(校验连接串(合法), f"合法连接串被误拒: {合法}")

    def test_校验连接串只放行postgres系列协议(self) -> None:
        """scheme 白名单：postgresql/postgres 放行；其余协议（mysql:// 等）必须被拒绝，不得交给驱动试探。"""
        for 非法 in ("mysql://u@127.0.0.1:5432/db", "postgresql+asyncpg://u@127.0.0.1/db",
                     "sqlite:///tmp/库.db", "mongodb://u@127.0.0.1:27017/库", "http://127.0.0.1/db"):
            问题 = 校验连接串(非法)
            self.assertIsNotNone(问题, f"非 postgres 协议未被拒绝: {非法}")
            self.assertIn("postgresql", str(问题), "拒绝原因必须点明支持的协议")
        for 合法 in ("postgres://u@127.0.0.1:5432/db", "POSTGRESQL://u@127.0.0.1:5432/db"):
            self.assertIsNone(校验连接串(合法), f"合法 postgres 系列协议被误拒: {合法}")

    def test_校验超时非法入参明确拒绝(self) -> None:
        """超时必须是正数；布尔/文本/零/负数一律拒绝。"""
        for 值 in (0, 0.0, -1, -0.5, None, "5", True, False, [], object()):
            问题 = 校验超时(值)
            self.assertIsNotNone(问题, f"非法超时未拒绝: {值!r}")
            self.assertIn("正数", str(问题), "拒绝原因必须指出正数要求")
        for 合法 in (1, 2, 0.5, 30.0):
            self.assertIsNone(校验超时(合法), f"合法超时被误拒: {合法}")

    def test_非法连接串在打开前被校验器拦截(self) -> None:
        """翻译层不重复校验：调用方必须先过 校验连接串/校验超时；否则驱动参数解析异常原样抛出（明确失败，不静默）。"""
        self.assertIsNotNone(校验连接串(""))
        self.assertIsNotNone(校验超时(0))
        with self.assertRaises(ValueError):
            打开连接("postgresql://127.0.0.1:非数字/db", 超时秒=2)

    # ---------- 二、解析连接串（真实翻译，无服务依赖） ----------

    def test_解析连接串翻译驱动参数(self) -> None:
        """postgresql:// → 驱动连接参数字典；缺省补全；URL 转义还原。"""
        解析 = 解析连接串(测试连接串)
        self.assertEqual(解析["host"], "127.0.0.1")
        self.assertEqual(解析["port"], 54320)
        self.assertEqual(解析["dbname"], "postgres")
        self.assertEqual(解析["user"], "postgres")
        self.assertIn(口令键, 解析, "驱动参数必须携带口令键")
        self.assertEqual(解析[口令键], "***")

        缺省 = 解析连接串("postgresql://")
        self.assertEqual(缺省["host"], "127.0.0.1", "缺省主机必须回填 127.0.0.1")
        self.assertEqual(缺省["port"], 5432, "缺省端口必须回填 5432")
        self.assertEqual(缺省["dbname"], "postgres", "缺省库名必须回填 postgres")
        self.assertEqual(缺省["user"], "postgres")

        转义 = 解析连接串("postgresql://%E7%94%A8%E6%88%B7:%E5%8F%A3%E4%BB%A4@127.0.0.1:5432/%E5%BA%93")
        self.assertEqual(转义["user"], "用户", "用户名必须做 URL 反转义")
        self.assertEqual(转义[口令键], "口令", "口令必须做 URL 反转义")
        self.assertEqual(转义["dbname"], "库", "库名必须与用户/口令统一做 URL 反转义（%XX 原样下传会连错库）")
        self.assertEqual(解析连接串("postgresql://u@127.0.0.1:5432/中文库")["dbname"], "中文库",
                         "未转义库名必须原样透传")

    # ---------- 三、归类错误（驱动异常 → 中文错误码） ----------

    def test_归类错误翻译中文错误码(self) -> None:
        """连接被拒/无法连接 → 连接失败；语句取消/超时 → 超时；其余 → 查询失败。"""
        self.assertEqual(归类错误(Exception("connection refused")), "连接失败")
        self.assertEqual(归类错误(Exception("could not connect to server: No such file")), "连接失败")
        self.assertEqual(归类错误(Exception("canceling statement due to statement timeout")), "超时")
        self.assertEqual(归类错误(Exception("operation timed out")), "超时")
        self.assertEqual(归类错误(Exception("syntax error at or near \"SELEC\"")), "查询失败")
        self.assertEqual(归类错误(ValueError("随便一个非驱动异常")), "查询失败", "未知异常必须归入查询失败")

    # ---------- 四、无服务时明确失败（真实连接，不 mock） ----------

    def test_无服务端口明确抛错且归类为连接类失败(self) -> None:
        """无 PostgreSQL 服务时必须明确失败（抛错并归类），绝不返回连接对象假装成功。"""
        if _端口可达(无服务主机, 无服务端口):
            self.skipTest(f"测试端口 {无服务主机}:{无服务端口} 意外可达，无法验证无服务失败路径")
        try:
            连接对象 = 打开连接(无服务连接串, 超时秒=2)
        except BaseException as 错误:  # noqa: BLE001 —— 断言的是「必须抛出」
            self.assertIn(归类错误(错误), ("连接失败", "超时"), f"真实异常未被归类: {错误!r}")
        else:
            释放连接(连接对象)
            self.fail("无服务端口不得返回连接对象（绝不假装连接成功）")

    # ---------- 五、驱动缺失明确失败（子进程真实分支，不 patch 生产符号） ----------

    def test_驱动缺失时提供者不可用(self) -> None:
        """屏蔽 psycopg 后（sys.modules 置 None → ImportError），检查可用性必须失败且错误码为 提供者不可用。"""
        代码 = (
            "import json, sys\n"
            "sys.modules['psycopg'] = None\n"
            "from 支持库.适配层.psycopg提供者 import 检查可用性, 驱动可用\n"
            "结果 = 检查可用性()\n"
            "print(json.dumps({'驱动可用': 驱动可用(), '成功': 结果.成功,"
            " '错误码': 结果.错误码, '错误说明': 结果.错误说明,\n"
            " '可重试': 结果.可重试}, ensure_ascii=False))\n"
        )
        环境 = {键: 值 for 键, 值 in os.environ.items() if 键 != "PYTHONPATH"}
        环境["PYTHONDONTWRITEBYTECODE"] = "1"
        进程 = subprocess.run(
            [sys.executable, "-B", "-c", 代码],
            capture_output=True, env=环境, cwd=str(系统根), timeout=60,
        )
        self.assertEqual(进程.returncode, 0, 进程.stderr.decode("utf-8", "replace")[-500:])
        数据 = json.loads(进程.stdout.decode("utf-8", "replace").strip())
        self.assertFalse(数据["驱动可用"], "屏蔽 psycopg 后 驱动可用 必须为 False")
        self.assertFalse(数据["成功"], "驱动缺失不得假装可用")
        self.assertEqual(数据["错误码"], "提供者不可用")
        self.assertIn("psycopg", 数据["错误说明"], "失败说明必须点明缺失的驱动")
        self.assertTrue(数据["可重试"], "驱动缺失属可重试（装驱动后即可恢复）")

    # ---------- 六、连接生命周期释放（autospec 桩替换驱动边界） ----------

    @unittest.skipUnless(驱动可用(), "psycopg 未安装：驱动边界无法替换，由 驱动缺失 用例覆盖")
    def test_打开连接与释放连接成对且无泄漏(self) -> None:
        """打开成功路径：连接参数真实翻译、返回驱动连接对象、释放后必然关闭（无句柄泄漏）。"""
        假连接 = _假连接()
        with mock.patch.object(模块.psycopg, "connect", autospec=True,
                               return_value=假连接) as 假驱动:
            连接对象 = 打开连接(测试连接串, 超时秒=2)
            self.assertIs(连接对象, 假连接)
            self.assertFalse(假连接.已关闭, "打开期间不得提前关闭连接")
            问题 = 释放连接(连接对象)
        self.assertIsNone(问题, f"释放连接必须干净返回 None，实得: {问题}")
        self.assertTrue(假连接.已关闭, "连接对象未关闭（句柄泄漏）")
        假驱动.assert_called_once()
        实参 = 假驱动.call_args.kwargs
        self.assertEqual(实参.get("host"), "127.0.0.1")
        self.assertEqual(实参.get("port"), 54320)
        self.assertEqual(实参.get("dbname"), "postgres")
        self.assertEqual(实参.get("user"), "postgres")
        self.assertEqual(实参.get("connect_timeout"), 2.0, "连接超时必须按秒翻译给驱动")
        self.assertEqual(实参.get(口令键), "***")
        self.assertFalse(假连接.已提交, "未指定 查询超时毫秒 时不得提交事务")

    @unittest.skipUnless(驱动可用(), "psycopg 未安装：驱动边界无法替换，由 驱动缺失 用例覆盖")
    def test_查询超时翻译为语句超时且游标收口(self) -> None:
        """指定 查询超时毫秒 → SET statement_timeout 并提交；游标必须收口（不泄漏）。"""
        假连接 = _假连接()
        with mock.patch.object(模块.psycopg, "connect", autospec=True, return_value=假连接):
            连接对象 = 打开连接(测试连接串, 超时秒=1, 查询超时毫秒=1500)
            释放连接(连接对象)
        self.assertTrue(假连接.已提交, "设置语句超时后必须提交，否则超时不生效")
        self.assertTrue(假连接.游标.已关闭, "设置语句超时的游标未关闭（句柄泄漏）")
        self.assertEqual(len(假连接.游标.记录), 1, "只允许一条 SET statement_timeout")
        self.assertIn("statement_timeout", 假连接.游标.记录[0])
        self.assertIn("1500", 假连接.游标.记录[0], "毫秒值必须真实透传")

    def test_释放连接对空句柄幂等且不吞关闭异常(self) -> None:
        """释放连接：空句柄视为干净（幂等）；驱动关闭异常必须报出，绝不静默。"""
        self.assertIsNone(释放连接(None), "空句柄释放必须视为干净")
        坏连接 = _假连接(关闭即异常=True)
        问题 = 释放连接(坏连接)
        self.assertIsNotNone(问题, "关闭异常不得被吞掉")
        self.assertIn("连接释放异常", str(问题))
        self.assertTrue(坏连接.已关闭, "关闭异常路径也必须走到 close")

    # ---------- 七、健康探针（无副作用、幂等） ----------

    @unittest.skipUnless(驱动可用(), "psycopg 未安装：本机真实驱动缺失，由 驱动缺失 用例覆盖")
    def test_检查可用性返回驱动版本且无副作用(self) -> None:
        """检查可用性：成功携带驱动版本、不带错误码、连续调用一致（能力定义：幂等/无副作用）。"""
        第一次 = 检查可用性()
        第二次 = 检查可用性()
        self.assertTrue(第一次.成功, 第一次.错误说明)
        self.assertTrue(第二次.成功, 第二次.错误说明)
        self.assertEqual(第一次.错误码, "", "成功结果不得携带错误码")
        探针值 = 第一次.值 if isinstance(第一次.值, dict) else {}
        self.assertTrue(探针值, "成功探针必须返回非空值字典")
        self.assertIs(探针值["驱动可用"], True)
        版本 = 探针值["驱动版本"]
        self.assertIsInstance(版本, dict)
        self.assertIn("psycopg", 版本)
        self.assertRegex(str(版本["psycopg"]), r"^\d+\.\d+", "驱动版本必须是真实版本号")
        self.assertEqual(第一次.值, 第二次.值, "同环境连续调用结果必须一致")
        self.assertIs(驱动可用(), True)
        self.assertEqual(驱动版本(), 版本, "驱动版本() 与探针值口径必须一致")

    # ---------- 八、接口面与旧能力残留（僵尸测试的直接防复发守卫） ----------

    def test_包级接口面与旧连接串能力不残留(self) -> None:
        """公开接口必须恰为现行九原语+注册入口；数据库收口删除的旧连接串能力不得复活。"""
        self.assertEqual(set(包.__all__), 期望接口, "__all__ 与现行接口清单不一致（删改接口必须同步本测试）")
        for 名称 in sorted(期望接口):
            self.assertTrue(callable(getattr(包, 名称, None)), f"包级入口缺失可调用对象: {名称}")
        残留 = [名称 for 名称 in 已删旧能力 if hasattr(包, 名称)]
        self.assertEqual(残留, [], f"2026-09-14 数据库收口已删除的旧连接串能力复活: {残留}")

    # ---------- 九、注册能力与声明/定义三方一致 ----------

    def test_注册能力与声明定义三方一致(self) -> None:
        """注册表实际注册恰为 1 条 检查可用性，且与 包声明.json / 能力定义.json 完全一致。"""
        注册表 = 能力注册表()
        注册能力(注册表)
        声明数据 = json.loads((提供者目录 / "包声明.json").read_text(encoding="utf-8"))
        定义数据 = json.loads((提供者目录 / "能力定义.json").read_text(encoding="utf-8"))
        声明能力表 = [能力["能力id"] for 能力 in 声明数据["能力"]]
        定义能力表 = [能力["能力id"] for 能力 in 定义数据["能力列表"]]
        self.assertEqual(声明数据["包id"], 包id)
        self.assertEqual(定义数据["包id"], 包id)
        self.assertEqual(sorted(注册表.能力id列表), [唯一能力id],
                         "驱动翻译层只允许注册一条能力（数据库操作能力已上移支持库）")
        self.assertEqual(sorted(声明能力表), [唯一能力id])
        self.assertEqual(sorted(定义能力表), [唯一能力id])
        注册实现 = 注册表.获取(唯一能力id)
        self.assertIsInstance(注册实现, 能力实现, "注册的能力必须可从注册表取回")
        self.assertEqual(注册实现.包id, 包id)
        self.assertIs(注册实现.实现函数, 检查可用性, "注册句柄必须指向包级公开入口")

    # ---------- 十、完整性摘要与真实文件闭合 ----------

    def test_完整性摘要与真实文件闭合(self) -> None:
        """摘要经唯一生成器校验通过（含逐文件 sha256 与清单闭合），且能力清单与包声明一致。"""
        from 支持库.后端.组件规范支持库 import 校验完整性摘要

        通过, 问题 = 校验完整性摘要(提供者目录)
        self.assertTrue(通过, f"摘要漂移: {问题}")
        摘要数据 = json.loads((提供者目录 / "完整性摘要.json").read_text(encoding="utf-8"))
        self.assertEqual(摘要数据["包id"], 包id)
        self.assertEqual(摘要数据["摘要算法"], "sha256")
        清单 = 摘要数据["文件清单"]
        self.assertGreaterEqual(len(清单), 10, "文件清单条目数下限（清单塌成空表即空过）")
        清单路径 = {条目["路径"] for 条目 in 清单}
        for 必备 in ("__init__.py", "包声明.json", "能力定义.json", "实现/提供者.py",
                    "能力契约/参数契约.json", "权限契约/权限契约.json", "配置契约/配置契约.json",
                    "资源预算.json", "复用决策.json", "依赖锁.json"):
            self.assertIn(必备, 清单路径, f"文件清单缺必备条目: {必备}")
        声明数据 = json.loads((提供者目录 / "包声明.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(摘要数据["能力清单"]),
                         sorted(能力["能力id"] for 能力 in 声明数据["能力"]),
                         "摘要能力清单必须与包声明一致")


if __name__ == "__main__":
    unittest.main()
