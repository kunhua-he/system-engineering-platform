"""第十三阶段：核心切换/回滚/恢复测试（真实执行链，禁止模拟绿灯）。

4 个真实场景：① 健康失败（健康检查返回 False）→ 切换中止回退、激活指针
原样，旧核心继续服务（旧快照仍可校验）；② 健康通过 → 切换成功（指针 CAS
指向新快照，版本/栅栏令牌递增）；③ 回滚 CAS 到旧版（指针回退旧快照 +
发布记录已回滚）；④ 切换中真实强杀：真实子进程执行迁移，指针 CAS 提交后
被 kill -9 → 重启（全新子进程）幂等完成，恢复为明确新版，无半激活、
无二次递增。强杀注入钩子只插入"真实提交后暂停"，不改变任何状态语义。
"""
import json, os, shutil, signal, subprocess, sys, tempfile, time, unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[3]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))
from 平台控制面.平台状态 import 平台状态
from 平台控制面.核心快照 import 核心快照管理
from 平台控制面.发布管理 import 发布管理
from 平台控制面.提供者.版本兼容 import 版本兼容
from 支持库.适配层.密码适配 import 生成密钥对


def 建旧快照(状态, 快照) -> tuple[str, str]:
    """真实创建旧核心快照 + Ed25519 签名 + 激活指针指向旧快照，返回 (旧id, 私钥)。"""
    私钥, 公钥 = 生成密钥对()
    状态.写入记录("信任", {"发布者": "发布者甲", "公钥": 公钥, "状态": "有效",
                        "轮换时间": "", "过期时间": ""})
    旧id = 快照.创建快照(运行核心版本="1.2.0", 前端核心版本="1.2.0",
                      后端核心版本="1.2.0", 状态兼容范围="1.0.0-1.4.0",
                      回滚许可=True, 迁移方式="扩展",
                      文件表={"核心.manifest": "旧核心 1.2.0"})
    成功, 消息 = 快照.签名快照(快照id=旧id, 私钥PEM=私钥, 发布者="发布者甲")
    if not 成功:
        raise RuntimeError(f"旧快照签名失败: {消息}")
    状态.写入记录("激活指针", {"指针id": "核心", "目标": 旧id,
                            "版本": 1, "栅栏令牌": 1, "状态": "激活"})
    return 旧id, 私钥


def 扩展并双读(兼容, 迁移id: str, 私钥: str) -> None:
    """扩展（真实创建新快照+签名）→ 双读（双实例同库）推进，失败抛异常。"""
    结果 = 兼容.扩展(迁移id=迁移id, 运行核心版本="1.3.0", 前端核心版本="1.3.0",
                   后端核心版本="1.3.0", 状态兼容范围="1.0.0-1.4.0",
                   文件表={"核心.manifest": "新核心 1.3.0", "能力清单.json": "扩展结构"},
                   私钥PEM=私钥, 发布者="发布者甲")
    if not 结果["成功"]:
        raise RuntimeError(f"扩展失败: {结果.get('错误')}")
    结果 = 兼容.双读(迁移id=迁移id, 新状态版本="1.4.0")
    if not 结果["成功"]:
        raise RuntimeError(f"双读失败: {结果.get('错误')}")


class 切换注入状态(平台状态):
    """强杀注入钩子：真实指针 CAS 提交后落盘就绪信号并无限休眠等 kill -9。"""
    def __init__(self, 存储目录, *, 就绪文件: str) -> None:
        super().__init__(存储目录)
        self.就绪文件, self._已注入 = 就绪文件, False

    def 条件更新(self, 表, 更新, 条件SQL, 参数) -> bool:
        if 表 == "激活指针" and not self._已注入:
            self._已注入 = True
            结果 = super().条件更新(表, 更新, 条件SQL, 参数)  # 真实 CAS 提交
            with open(self.就绪文件, "w", encoding="utf-8") as 文件:
                json.dump({"阶段": "切换后", "pid": os.getpid()}, 文件, ensure_ascii=False)
            while True:
                time.sleep(60)
        return super().条件更新(表, 更新, 条件SQL, 参数)


def 子进程主入口() -> int:
    """真实子进程：切换中（指针 CAS 提交后被父进程真实强杀）/ 重启恢复（幂等完成）。"""
    测试 = Test核心切换回滚恢复()
    测试.setUp()
    迁移id = os.environ.get("核心切换迁移id", "")
    if os.environ["核心切换子进程模式"] == "切换中":
        迁移id, _ = 测试._推进到双读()
    结果 = 测试.兼容.切换(迁移id=迁移id, 健康检查=lambda: True)  # 切换中：CAS 后暂停被杀；恢复：幂等完成
    print(json.dumps({"结果": 结果, "指针": 测试.发布.当前激活("核心"),
                      "迁移": 测试.兼容.查询迁移(迁移id)}, ensure_ascii=False), flush=True)
    测试.状态.关闭()
    return 0


class Test核心切换回滚恢复(unittest.TestCase):
    """核心切换/回滚/恢复：4 个真实场景。"""

    def setUp(self):
        self.目录 = (Path(os.environ["核心切换存储目录"]) if os.environ.get("核心切换存储目录")
                     else Path(tempfile.mkdtemp(prefix="核心切换_")))
        self.状态 = (切换注入状态(self.目录, 就绪文件=os.environ["核心切换就绪文件"])
                    if os.environ.get("核心切换子进程模式") == "切换中"
                    else 平台状态(self.目录, 项目id="核心切换测试"))
        self.快照 = 核心快照管理(self.状态, 快照根目录=self.目录 / "核心快照")
        self.发布 = 发布管理(self.状态)
        self.兼容 = 版本兼容(self.状态, self.快照, self.发布)
        if os.environ.get("核心切换子进程模式") != "恢复":
            self.旧id, self.私钥 = 建旧快照(self.状态, self.快照)
        self.注入进程 = None

    def tearDown(self):
        进程 = getattr(self, "注入进程", None)
        if 进程 is not None and 进程.poll() is None:
            try:
                os.killpg(进程.pid, signal.SIGKILL)
                进程.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                pass
        self.状态.关闭()
        shutil.rmtree(self.目录, ignore_errors=True)

    def _推进到双读(self) -> tuple[str, str]:
        迁移id = self.兼容.开始迁移(旧快照id=self.旧id, 目标版本="1.3.0",
                                 状态兼容范围="1.0.0-1.4.0")["迁移id"]
        扩展并双读(self.兼容, 迁移id, self.私钥)
        return 迁移id, self.兼容.查询迁移(迁移id)["新快照id"]

    def test_场景1_新核心健康失败旧核心继续服务(self):
        """健康检查返回 False → 切换中止回退，激活指针原样，旧核心继续服务。"""
        迁移id, _ = self._推进到双读()
        结果 = self.兼容.切换(迁移id=迁移id, 健康检查=lambda: False)
        self.assertFalse(结果["成功"])
        self.assertTrue(结果["回退"], 结果.get("错误"))
        指针 = self.发布.当前激活("核心")
        self.assertEqual(指针["目标"], self.旧id, "健康失败指针必须保持旧快照")
        self.assertEqual((指针["版本"], 指针["栅栏令牌"]), (1, 1), "指针不得被触碰")
        self.assertEqual(self.兼容.查询迁移(迁移id)["阶段"], "双读", "失败不得推进状态机")
        self.assertTrue(self.快照.校验快照(快照id=self.旧id)[0], "旧核心继续服务：旧快照仍可校验")

    def test_场景2_新核心健康通过切换成功(self):
        """健康检查返回 True → 指针 CAS 切到新快照，版本/栅栏令牌单调递增。"""
        迁移id, 新id = self._推进到双读()
        self.assertTrue(self.兼容.切换(迁移id=迁移id, 健康检查=lambda: True)["成功"])
        指针 = self.发布.当前激活("核心")
        self.assertEqual(指针["目标"], 新id, "切换成功指针 CAS 必须指向新快照")
        self.assertEqual((指针["版本"], 指针["栅栏令牌"], 指针["状态"]), (2, 2, "激活"),
                         "CAS 切换必须单调递增且状态激活")

    def test_场景3_回滚CAS到旧版发布记录已回滚(self):
        """切换成功后有发布记录 → 回滚 CAS 切回旧快照，发布记录已回滚。"""
        迁移id, 新id = self._推进到双读()
        self.assertTrue(self.兼容.切换(迁移id=迁移id, 健康检查=lambda: True)["成功"])
        发布id = self.发布.登记期望版本(包id="核心", 期望版本="1.3.0")
        self.assertTrue(self.发布.激活(发布id=发布id, 目标=新id)[0])
        self.assertTrue(self.发布.回滚(发布id=发布id, 回滚目标=self.旧id)[0])
        指针 = self.发布.当前激活("核心")
        self.assertEqual(指针["目标"], self.旧id, "回滚后指针必须回到旧快照")
        self.assertEqual((指针["版本"], 指针["栅栏令牌"], 指针["状态"]), (3, 3, "回滚"), "回滚走 CAS 继续递增")
        记录 = self.状态.读取记录("发布", "发布id", 发布id)
        self.assertEqual(记录["状态"], "已回滚", "发布记录必须已回滚")
        self.assertEqual(json.loads(记录["回滚事务"])["回滚到"], self.旧id)

    def test_场景4_切换中真实强杀重启后恢复明确版本(self):
        """真实子进程指针 CAS 提交后被 kill -9 → 重启幂等完成，恢复为明确新版。"""
        杀目录, 就绪文件 = self.目录 / "强杀", self.目录 / "强杀" / "就绪.json"
        环境 = dict(os.environ, 核心切换子进程模式="切换中", 核心切换存储目录=str(杀目录),
                    核心切换就绪文件=str(就绪文件))
        环境.pop("PYTHONPATH", None)
        进程 = subprocess.Popen([sys.executable, str(__file__)], env=环境,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True)
        self.注入进程 = 进程
        截止 = time.monotonic() + 15
        while not 就绪文件.exists() and 进程.poll() is None and time.monotonic() < 截止:
            time.sleep(0.02)
        self.assertTrue(就绪文件.exists(), f"等待注入就绪信号超时（子进程 rc={进程.poll()}）")
        就绪 = json.loads(就绪文件.read_text(encoding="utf-8"))
        self.assertEqual(就绪["阶段"], "切换后", "就绪阶段必须是指针 CAS 提交后")
        os.killpg(进程.pid, signal.SIGKILL)  # 真实强杀整个进程组
        进程.wait(timeout=10)
        self.assertEqual(进程.returncode, -9, "必须真实被 SIGKILL 杀死")
        进程.communicate()
        # 杀后直读：指针明确新版（CAS 已提交），迁移记录未完成 → 无半激活
        杀后 = 平台状态(杀目录)
        try:
            指针 = 杀后.读取记录("激活指针", "指针id", "核心")
            迁移记录 = [json.loads(r["值"]) for r in 杀后.查询记录("元信息")
                        if r["键"].startswith("版本迁移:")][0]
        finally:
            杀后.关闭()
        self.assertEqual(迁移记录["阶段"], "双读", "杀后迁移必须未完成")
        新id = 迁移记录["新快照id"]
        self.assertEqual(指针["目标"], 新id, "指针 CAS 已提交 → 杀后指针必须明确新版")
        self.assertEqual((指针["版本"], 指针["栅栏令牌"], 指针["状态"]), (2, 2, "激活"), "指针仅递增一次")
        # 重启（全新子进程）：重新执行切换 → 幂等完成，恢复为明确新版，不二次递增
        try:
            恢复 = json.loads(subprocess.run(
                [sys.executable, str(__file__)],
                env=dict(环境, 核心切换子进程模式="恢复", 核心切换迁移id=迁移记录["迁移id"]),
                capture_output=True, text=True, timeout=30, check=True).stdout)
        except subprocess.CalledProcessError as 错误:
            self.fail(f"恢复子进程失败 rc={错误.returncode} 输出={错误.stdout} 错误={错误.stderr}")
        self.assertTrue(恢复["结果"]["成功"], 恢复["结果"].get("错误"))
        self.assertEqual(恢复["指针"]["目标"], 新id, "重启后必须恢复为明确新版")
        self.assertEqual((恢复["指针"]["版本"], 恢复["指针"]["栅栏令牌"]), (2, 2), "恢复幂等，不得二次递增")
        self.assertEqual((恢复["迁移"]["阶段"], 恢复["迁移"]["指针"]["目标"]), ("切换", 新id),
                         "迁移记录与实际指针一致")


if __name__ == "__main__":
    if os.environ.get("核心切换子进程模式"):
        sys.exit(子进程主入口())
    unittest.main(verbosity=2)
