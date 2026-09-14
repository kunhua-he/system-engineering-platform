"""能力级占用租约：同能力原子互斥、同包幂等、心跳续租、过期回收与按开工id释放。

测试全程使用临时隔离存储目录与临时隔离运行库（`系统库运行库` 指向临时库），
不复用真实 `工程缓存/平台控制面/权威状态.db` 与 `工程缓存/运行数据/底座运行.db`。
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from MCP工具箱.能力占用 import (
    申请能力占用, 续租能力占用, 释放能力占用, 释放开工id能力占用,
    回收过期能力占用, 查询能力占用, 能力键, 查询占用账本, 搬迁旧账本,
    参数不合法, 占用冲突, 同步错误,
)
from 平台控制面.平台状态 import 平台状态


def _读库载荷(库路径: str, 域: str = "能力占用") -> list[dict]:
    """经唯一能力调用入口读运行库（与模块同一条通道，不用桩）。"""
    import 运行核心.能力调用.唯一能力调用  # noqa: F401 —— 注册惰性装配钩子

    from 公共契约.能力契约.调用器 import 获取能力调用器

    结果对象 = 获取能力调用器().调用能力(
        "数据库连接支持库.SQLite数据库.查询运行态",
        {"数据库路径": 库路径, "域": 域, "限制": 100, "超时秒": 10.0})
    if not 结果对象.成功:
        raise AssertionError(f"运行库查询失败：{getattr(结果对象, '错误说明', '')}")
    行列表 = (结果对象.值 or {}).get("行列表") or []
    记录表: list[dict] = []
    for 行 in 行列表:
        载荷 = 行.get("载荷") if isinstance(行, dict) else None
        if isinstance(载荷, str) and 载荷:
            记录表.append(json.loads(载荷))
    return 记录表


class 能力占用测试(unittest.TestCase):
    def setUp(self) -> None:
        self._临时 = tempfile.TemporaryDirectory()
        根 = Path(self._临时.name)
        self.存储目录 = 根 / "平台控制面"
        # 运行库与旧账本目录都隔离到临时区（走生产同一入口：环境变量/显式入参）。
        self.运行库 = str(根 / "运行数据" / "底座运行.db")
        self.旧账本目录 = 根 / "工程缓存" / "能力占用"
        self._原运行库环境 = os.environ.get("系统库运行库")
        self._原缓存根环境 = os.environ.get("系统底座_工程缓存根")
        os.environ["系统库运行库"] = self.运行库
        os.environ["系统底座_工程缓存根"] = str(根 / "工程缓存")

    def tearDown(self) -> None:
        for 名称, 原值 in (("系统库运行库", self._原运行库环境),
                          ("系统底座_工程缓存根", self._原缓存根环境)):
            if 原值 is None:
                os.environ.pop(名称, None)
            else:
                os.environ[名称] = 原值
        self._临时.cleanup()

    def _改心跳(self, 键: str, 心跳: float) -> None:
        状态 = 平台状态(self.存储目录, 项目id="平台控制面")
        状态.条件更新("占用租约", {"心跳": 心跳}, "能力id=?", (键,))

    def test_申请成功与同能力互斥(self) -> None:
        首次 = 申请能力占用(self.存储目录, 能力id="图像解码.解码图像",
                          提供包id="支持库.适配层.Pillow提供者", 开工id="work-a")
        self.assertTrue(首次["成功"], 首次)
        self.assertFalse(首次["值"]["幂等"])
        self.assertEqual(首次["值"]["能力id"], "图像解码.解码图像")
        self.assertTrue(首次["值"]["租约id"])

        异包 = 申请能力占用(self.存储目录, 能力id="图像解码.解码图像",
                          提供包id="支持库.后端.图像处理", 开工id="work-c")
        self.assertFalse(异包["成功"])
        self.assertEqual(异包["错误码"], 占用冲突)
        self.assertEqual(异包["值"]["现有占用"]["提供包id"], "支持库.适配层.Pillow提供者")

    def test_同包重复占用幂等(self) -> None:
        首次 = 申请能力占用(self.存储目录, 能力id="PDF渲染.检测加密页数",
                          提供包id="支持库.后端.PDF渲染", 开工id="work-a")
        self.assertTrue(首次["成功"], 首次)
        同包 = 申请能力占用(self.存储目录, 能力id="PDF渲染.检测加密页数",
                          提供包id="支持库.后端.PDF渲染", 开工id="work-b")
        self.assertTrue(同包["成功"], 同包)
        self.assertTrue(同包["值"]["幂等"])
        self.assertEqual(同包["值"]["租约id"], 首次["值"]["租约id"])
        self.assertEqual(查询能力占用(self.存储目录)["数量"], 1)

    def test_参数不合法(self) -> None:
        空能力 = 申请能力占用(self.存储目录, 能力id="",
                          提供包id="示例包1", 开工id="work-a")
        self.assertFalse(空能力["成功"])
        self.assertEqual(空能力["错误码"], 参数不合法)
        空包 = 申请能力占用(self.存储目录, 能力id="示例能力1", 提供包id="  ", 开工id="work-a")
        self.assertEqual(空包["错误码"], 参数不合法)
        空开工 = 申请能力占用(self.存储目录, 能力id="示例能力1", 提供包id="示例包1", 开工id="")
        self.assertEqual(空开工["错误码"], 参数不合法)
        with self.assertRaises(ValueError):
            能力键("坏 id")

    def test_释放后可被重新认领(self) -> None:
        首次 = 申请能力占用(self.存储目录, 能力id="密码签名.签名",
                          提供包id="支持库.后端.密码签名", 开工id="work-a")
        租约id = 首次["值"]["租约id"]
        释放 = 释放能力占用(self.存储目录, [租约id], 证据="测试释放")
        self.assertTrue(释放["成功"])
        再申请 = 申请能力占用(self.存储目录, 能力id="密码签名.签名",
                          提供包id="支持库.后端.密码签名备用包", 开工id="work-b")
        self.assertTrue(再申请["成功"], "释放后应可被其他包重新认领")
        self.assertFalse(再申请["值"]["幂等"])

    def test_续租刷新心跳(self) -> None:
        首次 = 申请能力占用(self.存储目录, 能力id="数据操作.展平",
                          提供包id="支持库.后端.数据操作", 开工id="work-a")
        租约id = 首次["值"]["租约id"]
        self._改心跳(能力键("数据操作.展平"), time.time() - 1000)
        续租 = 续租能力占用(self.存储目录, [租约id])
        self.assertTrue(续租["成功"])
        占用 = 查询能力占用(self.存储目录, ["数据操作.展平"])["占用"][0]
        self.assertLess(占用["空闲秒"], 5.0)

    def test_过期回收后可接管(self) -> None:
        首次 = 申请能力占用(self.存储目录, 能力id="表格.解析单元格地址",
                          提供包id="支持库.后端.办公文档", 开工id="work-a")
        self.assertTrue(首次["成功"])
        self._改心跳(能力键("表格.解析单元格地址"), time.time() - 1000)

        接管 = 申请能力占用(self.存储目录, 能力id="表格.解析单元格地址",
                          提供包id="支持库.后端.办公文档备用包", 开工id="work-b")
        self.assertTrue(接管["成功"], "申请时会先回收过期占用，过期后应可接管")
        self.assertEqual(查询能力占用(self.存储目录, ["表格.解析单元格地址"])["占用"][0]["提供包id"],
                         "支持库.后端.办公文档备用包")

    def test_回收过期不误伤新鲜租约(self) -> None:
        申请能力占用(self.存储目录, 能力id="图像解码.解码图像",
                   提供包id="支持库.适配层.Pillow提供者", 开工id="work-a")
        回收 = 回收过期能力占用(self.存储目录)
        self.assertEqual(回收["回收数量"], 0)
        self.assertEqual(查询能力占用(self.存储目录)["数量"], 1)

    def test_查询只返回能力领域且可按能力id过滤(self) -> None:
        申请能力占用(self.存储目录, 能力id="图像解码.解码图像",
                   提供包id="支持库.适配层.Pillow提供者", 开工id="work-a")
        # 伪造一条文件租约（领域不同），必须不被"查询能力占用"混入。
        状态 = 平台状态(self.存储目录, 项目id="平台控制面")
        状态.原子插入("占用租约", {
            "租约id": "file000000000001", "能力id": "文件::支持库/示例包1.py", "领域": "文件",
            "契约指纹": "", "任务": "文件占用", "所有者": "aaaa000000000001",
            "心跳": time.time(), "过期时间": time.time() + 3000, "释放证据": "", "状态": "活跃",
        })
        全部 = 查询能力占用(self.存储目录)
        self.assertEqual(全部["数量"], 1)
        self.assertEqual(全部["占用"][0]["能力id"], "图像解码.解码图像")
        过滤空 = 查询能力占用(self.存储目录, ["源码/不存在.py"])
        self.assertEqual(过滤空["数量"], 0)

    def test_按开工id释放(self) -> None:
        申请能力占用(self.存储目录, 能力id="数据操作.展平",
                   提供包id="支持库.后端.数据操作", 开工id="work-a")
        申请能力占用(self.存储目录, 能力id="数据操作.分组",
                   提供包id="支持库.后端.数据操作", 开工id="work-a")
        申请能力占用(self.存储目录, 能力id="图像解码.解码图像",
                   提供包id="支持库.适配层.Pillow提供者", 开工id="work-b")
        释放 = 释放开工id能力占用(self.存储目录, "work-a", 证据="收口：work-a")
        self.assertEqual(释放["释放数量"], 2)
        剩余 = 查询能力占用(self.存储目录)
        self.assertEqual([项["能力id"] for 项 in 剩余["占用"]], ["图像解码.解码图像"])

    def test_开工id为空时跳过(self) -> None:
        结果 = 释放开工id能力占用(self.存储目录, "  ", 证据="收口")
        self.assertTrue(结果["成功"])
        self.assertEqual(结果["释放数量"], 0)

    def test_查询无占用返回空(self) -> None:
        结果 = 查询能力占用(self.存储目录)
        self.assertTrue(结果["成功"])
        self.assertEqual(结果["数量"], 0)
        self.assertEqual(结果["占用"], [])

    # ── 占用账本（运行库 `能力占用` 域；旧 JSON 只读兼容 + 首次搬迁）────────

    def test_申请与释放同步占用账本(self) -> None:
        """占用判据在租约表、占用账本在运行库：申请/释放/回收都如实落库。"""
        self.assertEqual(_读库载荷(self.运行库), [])
        首次 = 申请能力占用(self.存储目录, 能力id="图像解码.解码图像",
                          提供包id="支持库.适配层.Pillow提供者", 开工id="work-a")
        self.assertTrue(首次["成功"], 首次)
        记录 = _读库载荷(self.运行库)
        self.assertEqual(len(记录), 1)
        self.assertEqual(记录[0]["能力id"], "图像解码.解码图像")
        self.assertEqual(记录[0]["提供包id"], "支持库.适配层.Pillow提供者")
        self.assertEqual(记录[0]["开工id"], "work-a")
        self.assertEqual(记录[0]["状态"], "活跃")
        self.assertEqual(同步错误, "")

        释放 = 释放能力占用(self.存储目录, [首次["值"]["租约id"]], 证据="测试释放")
        self.assertTrue(释放["成功"], 释放)
        记录 = _读库载荷(self.运行库)
        self.assertEqual(记录[0]["状态"], "已释放")
        self.assertEqual(记录[0]["释放证据"], "测试释放")

        # 回收过期：账本行标为「已回收」（同一能力仍是一行，主键 能力id）。
        申请 = 申请能力占用(self.存储目录, 能力id="数据操作.展平",
                         提供包id="支持库.后端.数据操作", 开工id="work-b")
        self.assertTrue(申请["成功"], 申请)
        self._改心跳(能力键("数据操作.展平"), time.time() - 1000)
        回收 = 回收过期能力占用(self.存储目录)
        self.assertEqual(回收["回收数量"], 1)
        账本 = {项["能力id"]: 项 for 项 in _读库载荷(self.运行库)}
        self.assertEqual(账本["数据操作.展平"]["状态"], "已回收")

    def test_按开工id释放同步账本(self) -> None:
        申请能力占用(self.存储目录, 能力id="数据操作.展平",
                   提供包id="支持库.后端.数据操作", 开工id="work-a")
        申请能力占用(self.存储目录, 能力id="数据操作.分组",
                   提供包id="支持库.后端.数据操作", 开工id="work-a")
        释放 = 释放开工id能力占用(self.存储目录, "work-a", 证据="收口：work-a")
        self.assertEqual(释放["释放数量"], 2)
        账本 = {项["能力id"]: 项 for 项 in _读库载荷(self.运行库)}
        self.assertEqual(len(账本), 2)
        self.assertTrue(all(项["状态"] == "已释放" for 项 in 账本.values()), 账本)
        self.assertTrue(all(项["释放证据"] == "收口：work-a" for 项 in 账本.values()))

    def test_旧账本只读兼容并一次性搬迁(self) -> None:
        """库空时读旧 `工程缓存/能力占用/*.json` 并搬入库；旧文件保持原样。"""
        self.旧账本目录.mkdir(parents=True, exist_ok=True)
        旧文件 = self.旧账本目录 / "浏览器自动化.创建会话.json"
        旧记录 = {"能力id": "浏览器自动化.创建会话", "提供包id": "支持库.后端.浏览器自动化支持库",
                 "开工id": "982baca487dd44f4", "占用时间": "2026-09-05 19:58:32"}
        旧文件.write_text(json.dumps(旧记录, ensure_ascii=False, indent=1), encoding="utf-8")
        旧字节 = 旧文件.read_bytes()

        查询 = 查询占用账本(运行库路径=self.运行库, 旧账本目录=self.旧账本目录)
        self.assertEqual(查询["来源"], "旧文件")
        self.assertEqual(查询["数量"], 1)
        记录 = _读库载荷(self.运行库)
        self.assertEqual([项["能力id"] for 项 in 记录], ["浏览器自动化.创建会话"])
        self.assertEqual(记录[0]["状态"], "历史")
        self.assertEqual(旧文件.read_bytes(), 旧字节, "旧文件必须保持只读")

        # 搬迁后旧文件不再是事实源：库优先，来源变「运行库」，数量不减。
        再次 = 查询占用账本(运行库路径=self.运行库, 旧账本目录=self.旧账本目录)
        self.assertEqual(再次["来源"], "运行库")
        self.assertEqual(再次["数量"], 1)
        self.assertEqual(再次["记录"][0]["能力id"], "浏览器自动化.创建会话")

    def test_搬迁旧账本返回真实计数(self) -> None:
        self.旧账本目录.mkdir(parents=True, exist_ok=True)
        for 序号 in range(3):
            (self.旧账本目录 / f"能力{序号}.json").write_text(json.dumps({
                "能力id": f"示例.能力{序号}", "提供包id": "支持库.后端.示例",
                "开工id": f"work{序号}", "占用时间": "2026-09-05 19:58:32",
            }, ensure_ascii=False), encoding="utf-8")
        结果 = 搬迁旧账本(运行库路径=self.运行库, 旧账本目录=self.旧账本目录)
        self.assertTrue(结果["成功"], 结果)
        self.assertEqual((结果["旧文件数"], 结果["已搬迁"]), (3, 3))
        self.assertEqual(len(_读库载荷(self.运行库)), 3)
        self.assertEqual(len(list(self.旧账本目录.glob("*.json"))), 3, "旧文件不删")


if __name__ == "__main__":
    unittest.main()
