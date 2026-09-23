"""第十四阶段 工作包04 维护者视图 测试：诊断/证据/裁决/回滚建议/权限拦截。

维护者（角色等级 4）可只读诊断与建议；签名与发布（等级 5）、回滚
（等级 5）必须被统一能力服务授权真实拦截（越权操作）。
调用生产实现（统一能力服务 + 维护者视图），禁止模拟绿灯。
"""
import sys
import tempfile
import unittest
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 平台控制面.统一入口 import 统一能力服务
from 开发工具.统一能力入口.视图.维护者视图 import 维护者视图

from 公共契约.运行时.平台适配 import 清只读后删除树
from 公共契约.基础类型.逻辑类型 import 真

#: ★ A 档泄漏收口（2026-09-23）：受管临时根在仓库内**固定排除目录** `工程缓存/` 下。
#: `dir=` 显式指向它 ⇒ 落点与**测试运行时**的 `TMPDIR` 解耦（平台跑测试时 `TMPDIR` 被指进
#: 仓库工作目录，裸 `mkdtemp()` 会把夹具造进仓库）。`工程缓存` 在
#: `开发工具/项目编译/工作区指纹.py` 的 `固定排除目录` 里 ⇒ 即便进程被 SIGKILL、
#: 清理没跑到，残留也进不了工作区指纹（`.gitignore` 保不住：指纹的未跟踪腿不用
#: `--exclude-standard`）。清理走平台唯一删树原语 `清只读后删除树`（本类用例常造
#: `0o555` 目录 / `0o444` 文件，plain `shutil.rmtree` 会被权限位挡住）。
受管临时根 = 系统根 / "工程缓存" / "测试临时"
受管临时根.mkdir(parents=True, exist_ok=True)

#: 模块级临时夹具登记：本模块的夹具**在模块级 helper 里**造（helper 拿不到 TestCase 实例，
#: 用不了 `self.addCleanup`）⇒ 走 unittest 的**模块级收尾钩子** `tearDownModule` 登记清理
#: （同样「用例失败也跑」）。拿得到用例实例的站点一律用 `self.addCleanup`。
_临时夹具登记: list[Path] = []


def tearDownModule() -> None:
    """模块收尾：清理本模块造在 `受管临时根` 下的全部夹具（**用例失败也跑**）。"""
    for 夹具 in _临时夹具登记:
        清只读后删除树(夹具, 忽略失败=真)
    _临时夹具登记.clear()



def 建服务() -> tuple[统一能力服务, Path]:
    目录 = Path(tempfile.mkdtemp(prefix="维护者视图测试_", dir=受管临时根))
    _临时夹具登记.append(目录)
    return 统一能力服务(目录), 目录


def 提权(服务: 统一能力服务, 身份id: str, 角色: str) -> str:
    """注册身份 → 引导授予 → 切换角色（真实授权路径）。"""
    令牌 = 服务.授权.注册身份(身份id=身份id)
    成功, 消息 = 服务.授权.引导授予(身份id=身份id, 角色=角色, 授予者="系统引导")
    assert 成功, 消息
    成功, 消息 = 服务.授权.切换角色(令牌, 角色)
    assert 成功, 消息
    return 令牌


class Test维护者视图核心(unittest.TestCase):
    """查看诊断/证据/裁决/回滚建议 真实数据。"""

    def setUp(self):
        self.服务, self.目录 = 建服务()
        self.视图 = 维护者视图(self.服务)
        self.令牌 = 提权(self.服务, "维护者", "平台维护者")

    def test_查看诊断返回监督报告与证据数(self):
        结果 = self.视图.查看诊断(self.令牌)
        self.assertTrue(结果["成功"], 结果.get("消息"))
        self.assertIn("监督报告", 结果)
        self.assertIsInstance(结果["证据数"], int)
        self.assertIn("状态快照", 结果)
        self.assertIn("结构版本", 结果["状态快照"])

    def test_查看证据返回真实追加证据链(self):
        主题 = "证据主题_维护者"
        self.服务.状态.追加证据(类型="维护者测试", 主题=主题,
                             内容={"动作": "真实追加"}, 调用者="维护者",
                             角色="平台维护者", 结果="成功")
        结果 = self.视图.查看证据(self.令牌, 主题)
        self.assertTrue(结果["成功"])
        self.assertEqual(结果["数量"], 1)
        链 = 结果["证据链"]
        self.assertEqual(链[0]["类型"], "维护者测试")
        self.assertEqual(链[0]["结果"], "成功")
        self.assertTrue(链[0]["时间"])
        # 证据只读：视图未修改证据内容
        self.assertEqual(结果["证据表"][0]["内容"]["动作"], "真实追加")
        # 限制参数真实生效
        结果2 = self.视图.查看证据(self.令牌, 主题, 限制=0)
        self.assertEqual(结果2["数量"], 0)

    def test_冲突裁决写入能力条目可读回(self):
        self.服务.目录.登记能力(能力id="能力1", 契约={"能力id": "能力1"},
                             组件="组件1", 领域="领域1")
        结果 = self.视图.冲突裁决(self.令牌, "能力1", "复用")
        self.assertTrue(结果["成功"], 结果.get("消息"))
        记录 = self.服务.状态.读取记录("能力条目", "能力id", "能力1")
        self.assertEqual(记录["复用裁决"], "复用")
        self.assertEqual(记录["裁决状态"], "已裁决")
        # 裁决有真实证据
        证据 = self.服务.状态.查询证据(主题="能力1", 类型="能力目录")
        self.assertEqual(证据[0]["内容"]["裁决"], "复用")
        # 非法裁决值被拒
        结果 = self.视图.冲突裁决(self.令牌, "能力1", "任意值")
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "裁决被拒")
        # 未登记能力被拒
        结果 = self.视图.冲突裁决(self.令牌, "不存在", "复用")
        self.assertEqual(结果["错误码"], "能力不存在")

    def test_回滚建议返回可回滚目标且只读(self):
        发布id = self.服务.发布.登记期望版本(包id="建议包", 期望版本="2")
        self.服务.发布.激活(发布id=发布id, 目标="制品摘要v2")
        结果 = self.视图.回滚建议(self.令牌, 发布id)
        self.assertTrue(结果["成功"], 结果.get("消息"))
        self.assertEqual(结果["包id"], "建议包")
        self.assertEqual(结果["当前激活"]["目标"], "制品摘要v2")
        self.assertTrue(结果["可回滚目标表"])
        self.assertIn("不执行回滚", 结果["建议"])
        # 只读建议：指针未变化、发布状态未变（未执行回滚）
        指针 = self.服务.发布.当前激活("建议包")
        self.assertEqual(指针["目标"], "制品摘要v2")
        记录 = self.服务.状态.读取记录("发布", "发布id", 发布id)
        self.assertEqual(记录["状态"], "完成")
        # 未知发布id被拒
        结果 = self.视图.回滚建议(self.令牌, "不存在发布")
        self.assertEqual(结果["错误码"], "发布不存在")


class Test维护者权限边界(unittest.TestCase):
    """维护者禁止签名/安装/发布/回滚；授权真实拦截。"""

    def setUp(self):
        self.服务, self.目录 = 建服务()
        self.视图 = 维护者视图(self.服务)
        self.令牌 = 提权(self.服务, "维护者", "平台维护者")

    def test_维护者签名与发布被授权拦截(self):
        结果 = self.服务.执行操作(令牌=self.令牌, 操作="签名与发布", 参数={})
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "越权操作")
        # 视图不提供签名/安装/发布执行方法
        for 方法名 in ("签名与发布", "安装制品", "执行发布"):
            self.assertFalse(hasattr(self.视图, 方法名))

    def test_维护者回滚被授权拦截(self):
        结果 = self.服务.执行操作(令牌=self.令牌, 操作="回滚", 参数={"发布id": "x"})
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "越权操作")
        # 发布者（等级5）可回滚：真实对照，证明拦截来自角色等级
        发布令牌 = 提权(self.服务, "发布者", "发布者")
        发布id = self.服务.发布.登记期望版本(包id="对照包", 期望版本="1")
        self.服务.发布.激活(发布id=发布id, 目标="摘要1")
        结果 = self.服务.执行操作(令牌=发布令牌, 操作="回滚",
                                参数={"发布id": 发布id, "回滚目标": "摘要旧"})
        self.assertTrue(结果["成功"], 结果.get("消息"))
        指针 = self.服务.发布.当前激活("对照包")
        self.assertEqual(指针["目标"], "摘要旧")

    def test_未授予身份访问视图被拒(self):
        访客令牌 = self.服务.授权.注册身份(身份id="访客")
        结果 = self.视图.查看依赖(访客令牌, "能力1")
        self.assertFalse(结果["成功"])
        self.assertEqual(结果["错误码"], "越权操作")
        结果 = self.视图.冲突裁决(访客令牌, "能力1", "复用")
        self.assertEqual(结果["错误码"], "越权操作")


class Test维护者视图只读视图(unittest.TestCase):
    """依赖/提供者/资源视图真实数据。"""

    def test_查看依赖与提供者真实数据(self):
        服务, 目录 = 建服务()
        视图 = 维护者视图(服务)
        令牌 = 提权(服务, "维护者", "平台维护者")
        服务.目录.登记能力(能力id="底层.能力", 契约={"能力id": "底层.能力"},
                         组件="底层", 领域="基础")
        服务.目录.登记能力(能力id="上层.能力", 契约={"能力id": "上层.能力"},
                         组件="上层", 领域="业务")
        服务.状态.条件更新("能力条目", {"依赖": '["底层.能力"]'}, "能力id=?", ("上层.能力",))
        预算 = {"内存上限": 100, "线程上限": 2, "子进程上限": 1, "并发调用上限": 2,
                "队列长度": 10, "文件句柄上限": 50, "临时空间上限": 100,
                "单次调用超时": 5, "每分钟重启次数": 2, "空闲回收时间": 60}
        成功, 消息 = 服务.注册提供者(能力id="上层.能力", 函数=lambda: 1, 预算=预算)
        self.assertTrue(成功, 消息)
        依赖 = 视图.查看依赖(令牌, "上层.能力")
        self.assertTrue(依赖["成功"])
        self.assertEqual(依赖["依赖表"], ["底层.能力"])
        self.assertEqual(依赖["被依赖表"], [])
        依赖反 = 视图.查看依赖(令牌, "底层.能力")
        self.assertEqual(依赖反["被依赖表"], ["上层.能力"])
        提供者 = 视图.查看提供者(令牌, "上层.能力")
        self.assertTrue(提供者["成功"])
        self.assertTrue(提供者["已注册"])
        self.assertEqual(提供者["预算"]["并发调用上限"], 2)
        提供者空 = 视图.查看提供者(令牌, "底层.能力")
        self.assertFalse(提供者空["已注册"])
        结果 = 视图.查看依赖(令牌, "不存在.能力")
        self.assertEqual(结果["错误码"], "能力不存在")

    def test_查看资源返回真实句柄与线程(self):
        服务, 目录 = 建服务()
        视图 = 维护者视图(服务)
        令牌 = 提权(服务, "维护者", "平台维护者")
        服务.状态.保存句柄(句柄id="句柄1", 句柄类型="文件", 资源id="资源1",
                         项目id="平台控制面", 所有者="测试", 状态="有效", 版本="1")
        结果 = 视图.查看资源(令牌)
        self.assertTrue(结果["成功"])
        self.assertEqual(结果["资源报告"]["活跃句柄数"], 1)
        self.assertGreater(结果["资源报告"]["活跃线程数"], 0)
        self.assertIn("监督单元", 结果["资源报告"])


if __name__ == "__main__":
    unittest.main()
