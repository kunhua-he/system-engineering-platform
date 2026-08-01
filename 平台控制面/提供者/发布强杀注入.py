"""发布强杀注入：真实子进程执行发布操作，在精确阶段被 kill -9 的注入辅助模块。

用途（第十三阶段真实强杀注入测试专用，不参与生产调用链）：
- 强杀注入状态：平台状态 子类。真实执行 发布管理.激活() 的状态机，仅在
  注入点处：先执行真实写入（提交后）→ 落盘就绪信号 → 无限休眠等待父进程
  真实 kill -9。注入点只插入"暂停"，不改变任何状态语义。
- 落账激活目标：指针切换前把发布记录的激活目标持久化（崩溃恢复意图）。
  发布管理.恢复未完成发布() 据此判定"指针已切→幂等完成 / 未切→回滚"，
  保证强杀后只落在明确旧版或新版，不存在半激活（指针单条原子 UPDATE）。
- 子进程主入口：按环境变量执行 发布（含注入）/ 恢复（恢复未完成发布+对账）
  两种模式，输出 JSON 行，供父进程断言。

用法（测试中心/第十三阶段/测试_发布强杀注入.py 调用）：
    python3.14 平台控制面/提供者/发布强杀注入.py   # 环境变量驱动
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

系统根 = Path(__file__).resolve().parents[2]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 平台控制面.平台状态 import 平台状态
from 平台控制面.发布管理 import 发布管理


class 强杀注入状态(平台状态):
    """平台状态 + 强杀注入钩子：真实写入提交后暂停，等待父进程 kill -9。"""

    def __init__(self, 存储目录: Path, *, 注入点: str = "无", 就绪文件: str = "") -> None:
        super().__init__(存储目录)
        self.注入点 = 注入点
        self.就绪文件 = 就绪文件
        self._已注入 = False

    def _落账激活目标(self, 包id: str, 目标: str) -> None:
        """指针切换前把发布记录的激活目标落账（持久意图）。

        恢复未完成发布() 以 记录.激活指针 vs 实际指针 判定完成/回滚：
        先落账意图、再切指针 → 任意时刻被杀都只有两种明确结局。
        """
        if not 包id or not 目标:
            return
        for 记录 in self.查询记录("发布", "包id=? AND 状态 IN ('准备','灰度')", (包id,)):
            # 主键必须显式传 "发布id"：写入记录 默认主键是 "id"，缺省会把
            # 部分字段写坏（其余列全 NULL，实测记录被清空）。
            super().写入记录("发布", {"发布id": 记录["发布id"], "激活指针": 目标},
                             主键="发布id")
            return

    def _注入暂停(self) -> None:
        """就绪信号落盘后无限休眠；父进程看到就绪文件后真实 kill -9。"""
        if self.就绪文件:
            with open(self.就绪文件, "w", encoding="utf-8") as 文件:
                json.dump({"阶段": self.注入点, "pid": os.getpid(),
                           "时间": time.strftime("%H:%M:%S")}, 文件, ensure_ascii=False)
        while True:
            time.sleep(60)

    def 写入记录(self, 表: str, 记录: dict, 主键: str = "id") -> None:
        if 表 == "激活指针" and self.注入点 == "切换后" and not self._已注入:
            self._已注入 = True
            self._落账激活目标(记录.get("指针id", ""), 记录.get("目标", ""))
            super().写入记录(表, 记录, 主键)  # 真实指针创建（首版）
            self._注入暂停()  # 永不返回
            return
        return super().写入记录(表, 记录, 主键)

    def 条件更新(self, 表: str, 更新: dict, 条件SQL: str, 参数: tuple) -> bool:
        if 表 == "发布" and 更新.get("状态") == "准备" and self.注入点 == "准备后" \
                and not self._已注入:
            self._已注入 = True
            结果 = super().条件更新(表, 更新, 条件SQL, 参数)  # 真实"准备"提交
            self._注入暂停()  # 永不返回
            return 结果
        if 表 == "激活指针" and self.注入点 == "切换后" and not self._已注入:
            self._已注入 = True
            self._落账激活目标(str(参数[0]) if 参数 else "", 更新.get("目标", ""))
            结果 = super().条件更新(表, 更新, 条件SQL, 参数)  # 真实指针 CAS 切换
            self._注入暂停()  # 永不返回
            return 结果
        return super().条件更新(表, 更新, 条件SQL, 参数)


def 执行发布操作(状态, *, 包id: str, 版本: str) -> dict:
    """真实发布操作：登记期望 → 灰度 → 激活（与 统一入口._签名发布 第 4 步同构）。"""
    发布 = 发布管理(状态)
    发布id = 发布.登记期望版本(包id=包id, 期望版本=版本)
    发布.开始灰度(发布id=发布id, 候选版本=版本, 比例=1.0)
    成功, 消息 = 发布.激活(发布id=发布id, 目标=版本)
    return {"发布id": 发布id, "成功": 成功, "消息": 消息}


def 子进程主入口() -> int:
    """子进程入口：环境变量驱动，模式=发布（含注入）/ 恢复。"""
    模式 = os.environ["注入模式"]
    存储目录 = Path(os.environ["注入存储目录"])
    注入点 = os.environ.get("注入点", "无")
    就绪文件 = os.environ.get("注入就绪文件", "")
    包id = os.environ.get("注入包id", "")
    版本 = os.environ.get("注入版本", "")
    if 模式 == "发布":
        状态 = 强杀注入状态(存储目录, 注入点=注入点, 就绪文件=就绪文件)
        结果 = 执行发布操作(状态, 包id=包id, 版本=版本)
        print(json.dumps({"结果": 结果}, ensure_ascii=False), flush=True)
        return 0
    if 模式 == "恢复":
        状态 = 平台状态(存储目录)
        发布 = 发布管理(状态)
        恢复表 = 发布.恢复未完成发布()
        输出 = {"恢复表": 恢复表, "发布记录表": 状态.查询记录("发布"),
                "指针表": 状态.查询记录("激活指针")}
        if os.environ.get("注入对账", "") == "是":
            # 对账单独跑：多发布历史的包id 会把历史完成记录重写为当前指针
            # （发布管理既有行为），因此由测试按场景决定是否启用。
            输出["对账表"] = 发布.对账()
        print(json.dumps(输出, ensure_ascii=False), flush=True)
        return 0
    print(json.dumps({"错误": f"未知注入模式: {模式}"}, ensure_ascii=False), flush=True)
    return 2


if __name__ == "__main__":
    sys.exit(子进程主入口())
