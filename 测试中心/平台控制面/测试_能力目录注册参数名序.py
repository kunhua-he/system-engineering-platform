"""能力目录装配期参数名序闸门测试：判据必须与**真契约**比对，不是文件内自比。

背景（2026-09-23 修的静默漂移）：
`平台控制面/能力目录/__init__.py` 的 `_校验参数名序()` 原先只拿「注册镜像
`_参数契约表`」与「注册名序 `_注册参数名序`」互比 —— 两份**都在同一个文件里**、
由同一次手写产生，一起写错即互证「一致」，**从不与真契约
`能力契约/参数契约.json`（其源 `能力定义.json`）比**。
现场事实：`释放文件租约` 的真契约名序是 `[租约id清单, 原因, 项目根, 存储目录]`，
而入口镜像/名序是 `[…, 存储目录, 项目根]` —— 顺序不一致被静默放过
（按关键字传参无害，按位置传参即把 `项目根` 与 `存储目录` 对调）。
设计说明 `说明/设计说明.md`「改能力参数的两条铁律」第 1 条已写明：
入口名序必须与契约逐字逐序一致，参数事实源只有契约一处。

本测试固定四件事（判据在 ≠ 判据覆盖）：
1. **正向**：现仓真契约与镜像/名序四方一致 ⇒ `注册能力` 装配通过（不 raise）；
2. **判据真的接上了真契约**：把真契约读腿换成「名序被打乱」的契约 ⇒ 装配必须 raise；
3. **反向三类**：镜像错序 / 名序错序 / 真契约缺该能力，判据都必须 raise；
4. **旧自比判据的盲区**：镜像与名序同源同文件 ⇒ 只比这两份的旧判据对上述漂移恒绿
   （「静默放过」的机理，用「镜像名序 == 注册名序 恒成立」钉住）。

运行（仓库根目录）：
    export PATH=/Library/Developer/CommandLineTools/usr/bin:$PATH; unset PYTHONPATH;
    python3.14 -m unittest 测试中心.平台控制面.测试_能力目录注册参数名序 -v

**注入手法（2026-09-23 改写）**：只读真实仓库文件；「真契约名序被打乱」这一拍用
**真实状态注入** —— 把入口 `__init__.py` 与一份**真文件形态**的打乱契约放进 `tempfile`
临时包目录，让**真实** `注册能力` 在真文件上跑（**不 patch 任何生产成员**，也不改任何
既有文件）。改前那拍用 `mock.patch.object(注册腿, "读契约表", …)` 换掉了被测模块读契约的
那个成员，断言对象是夹具。
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 公共契约.基础类型.逻辑类型 import 真
from 公共契约.能力契约.契约 import 能力注册表
from 公共契约.运行时.平台适配 import 清只读后删除树
from 平台控制面.能力目录 import (
    _校验参数名序,
    _读真契约名序,
    注册能力,
)
from 平台控制面.能力目录.实现 import 注册文件租约 as 注册腿

包目录 = 系统根 / "平台控制面" / "能力目录"
契约路径 = 包目录 / "能力契约" / "参数契约.json"
释放能力id = "平台控制面.能力目录.释放文件租约"
#: 本条漂移的现场事实：真契约（`能力契约/参数契约.json`）里的名序。
释放契约名序 = ["租约id清单", "原因", "项目根", "存储目录"]
#: 修前入口镜像/名序的错序（`项目根` 与 `存储目录` 对调）——反向验证的注入形态。
释放错序 = ["租约id清单", "原因", "存储目录", "项目根"]


def _读契约条目表() -> list[dict]:
    """读真契约文件的 `能力契约` 条目表（只读，用于构造判据输入与期望值）。"""
    return json.loads(契约路径.read_text(encoding="utf-8"))["能力契约"]


def _名序投影(条目表: list[dict]) -> dict[str, list[str]]:
    return {条目["能力id"]: [参数["名称"] for 参数 in (条目.get("参数") or [])]
            for 条目 in 条目表}


def _镜像与名序(真名序: dict[str, list[str]]) -> tuple[dict, dict]:
    """按给定名序造出「镜像 + 名序」两份输入（模拟入口里那两份同源数据）。"""
    镜像 = {能力id: [{"名称": 名称} for 名称 in 名序] for 能力id, 名序 in 真名序.items()}
    名序 = {能力id: list(名序) for 能力id, 名序 in 真名序.items()}
    return 镜像, 名序


def _加载副本包(目录: Path):
    """按文件路径加载入口副本（包形态），返回模块对象供直接调 `注册能力`。"""
    import importlib.util

    名 = f"能力目录名序副本_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(
        名, 目录 / "__init__.py", submodule_search_locations=[str(目录)])
    模块 = importlib.util.module_from_spec(spec)
    sys.modules[名] = 模块
    try:
        spec.loader.exec_module(模块)
    except BaseException:
        sys.modules.pop(名, None)
        raise
    return 模块


class 参数名序闸门测试(unittest.TestCase):
    def setUp(self) -> None:
        # 夹具根由 setUp 造（`self.夹具根`）—— 夹具根若当形参/外部名字传，
        # `测试写入边界门禁` 判据一解析不出，`目录 / "能力契约"` 一类合法临时夹具写
        # 会被整片计入「未解析」违规（判据 fail-closed）。
        self.夹具根 = Path(tempfile.mkdtemp(prefix="名序闸门_"))

    def tearDown(self) -> None:
        清只读后删除树(self.夹具根, 忽略失败=真)

    def 写打乱真契约的包(self) -> None:
        """把**现仓真契约**读出来、只把 `释放文件租约` 的名序改乱，写进 `self.夹具根`。

        同时把入口 `__init__.py` **原样复制**过去：入口全是绝对导入（无相对导入），
        所以副本只带「入口 + 契约」两件就能让**真实** `注册能力` 真跑 —— 它读真契约的
        那一段走 `Path(__file__).resolve().parent`，落在本临时包目录上，读到的就是这份
        打乱了的**真文件**（真实状态注入，不是把读腿的返回值换掉）。
        """
        目录 = self.夹具根
        数据 = json.loads(契约路径.read_text(encoding="utf-8"))
        for 条目 in 数据["能力契约"]:
            if 条目["能力id"] != 释放能力id:
                continue
            参数 = 条目["参数"]
            下标 = {参数项["名称"]: 序号 for 序号, 参数项 in enumerate(参数)}
            参数[下标["项目根"]], 参数[下标["存储目录"]] = (
                参数[下标["存储目录"]], 参数[下标["项目根"]])
        (目录 / "能力契约").mkdir(parents=True, exist_ok=True)
        (目录 / "能力契约" / "参数契约.json").write_text(
            json.dumps(数据, ensure_ascii=False), encoding="utf-8")
        (目录 / "__init__.py").write_text(
            (包目录 / "__init__.py").read_text(encoding="utf-8"), encoding="utf-8")

    def test_正向_现仓真契约与镜像名序一致_装配通过(self):
        """四方（能力定义/真契约/镜像/名序）一致时，装配期闸门必须放行。"""
        注册表 = 能力注册表()
        注册能力(注册表)  # 任一处不一致会在装配期 raise，这里必须不 raise
        self.assertIn(释放能力id, 注册表.能力id列表)
        self.assertEqual(len(注册表.能力id列表), len(_读契约条目表()),
                         "契约里的能力必须全部注册（不许多、不许少）")

    def test_数据_释放文件租约名序以真契约为准(self):
        """数据修复的回归钉：真契约与入口镜像/名序里的 `释放文件租约` 名序逐字逐序一致。"""
        真名序 = _读真契约名序(包目录)
        self.assertEqual(真名序[释放能力id], 释放契约名序)
        # 真契约文件（读腿的唯一事实源）里也必须是这个序
        self.assertEqual(_名序投影(_读契约条目表())[释放能力id], 释放契约名序)
        # 镜像与名序各自都对（`注册能力` 里那两份同源数据）
        镜像, 名序 = _镜像与名序(真名序)
        镜像[释放能力id] = [{"名称": 名称} for 名称 in 释放契约名序]
        self.assertEqual([项["名称"] for 项 in 镜像[释放能力id]], 名序[释放能力id])

    def test_反向_真契约名序被打乱_装配必须判红(self):
        """把**真契约文件**里 `释放文件租约` 的名序改乱 ⇒ `注册能力` 装配必须 raise。

        **真实状态注入**：造一个临时包目录（真 `__init__.py` 副本 + 打乱了的真契约文件），
        让**真实** `注册能力` 跑 —— 它读真契约那一段读到的就是这份打乱的真文件。
        修前判据只比「镜像 vs 名序」（都在本文件、同源）⇒ 这里必然绿（静默放过）；
        现在判据接上了真契约 ⇒ 必须红。**不 patch 任何生产成员**（原写法是
        `mock.patch.object(注册腿, "读契约表", return_value=打乱契约表)`，断言对象是夹具）。
        """
        self.写打乱真契约的包()
        打乱表 = 注册腿.读契约表(self.夹具根)   # 唯一读腿真读那份真文件
        self.assertEqual([参数项["名称"] for 参数项 in 打乱表[释放能力id]["参数"]],
                         释放错序, "注入的真契约文件必须真的被改乱")
        副本 = _加载副本包(self.夹具根)
        with self.assertRaises(ValueError) as 捕获:
            副本.注册能力(能力注册表())
        self.assertIn(释放能力id, str(捕获.exception))
        self.assertIn("真契约", str(捕获.exception))

    def test_反向_镜像名序与真契约不一致_判据必须判红(self):
        真名序 = _读真契约名序(包目录)
        镜像, 名序 = _镜像与名序(真名序)
        镜像[释放能力id] = [{"名称": 名称} for 名称 in 释放错序]  # 只错镜像
        with self.assertRaises(ValueError) as 捕获:
            _校验参数名序(镜像, 名序, 真名序)
        self.assertIn("注册镜像参数名序", str(捕获.exception))

    def test_反向_名序与真契约不一致_判据必须判红(self):
        真名序 = _读真契约名序(包目录)
        镜像, 名序 = _镜像与名序(真名序)
        名序[释放能力id] = list(释放错序)  # 只错名序
        with self.assertRaises(ValueError) as 捕获:
            _校验参数名序(镜像, 名序, 真名序)
        self.assertIn("注册参数名序", str(捕获.exception))

    def test_反向_真契约缺该能力_判据必须判红(self):
        真名序 = _读真契约名序(包目录)
        真名序.pop(释放能力id)
        镜像, 名序 = _镜像与名序(_名序投影(_读契约条目表()))
        with self.assertRaises(ValueError) as 捕获:
            _校验参数名序(镜像, 名序, 真名序)
        self.assertIn(释放能力id, str(捕获.exception))

    def test_旧自比判据的盲区_镜像与名序同源恒相等(self):
        """钉住「静默放过」的机理：旧判据只比镜像与名序，两份同源 ⇒ 恒绿。

        镜像名序 == 注册名序（旧判据看到的）永真；而真契约一旦被改乱，新判据立刻红。
        """
        真名序 = _读真契约名序(包目录)
        镜像, 名序 = _镜像与名序(真名序)
        打乱真名序 = dict(真名序)
        打乱真名序[释放能力id] = list(释放错序)
        self.assertEqual([项["名称"] for 项 in 镜像[释放能力id]], 名序[释放能力id],
                         "镜像与名序同源：旧自比判据对这类漂移恒绿")
        self.assertNotEqual([项["名称"] for 项 in 镜像[释放能力id]],
                            打乱真名序[释放能力id], "真契约的错序必须能被看出")
        with self.assertRaises(ValueError):
            _校验参数名序(镜像, 名序, 打乱真名序)


if __name__ == "__main__":
    unittest.main()
