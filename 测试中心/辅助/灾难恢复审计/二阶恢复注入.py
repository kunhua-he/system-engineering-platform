"""二阶恢复强杀注入：真实子进程执行"发布管理.恢复未完成发布"的注入辅助模块。

用途（第十四阶段工作包13 二阶恢复强杀测试专用，不参与生产调用链）：
- 二阶强杀注入状态：平台状态 子类。真实执行 发布管理.恢复未完成发布()
  的状态机（恢复动作=完成/回滚的真实提交），仅在注入点处：先执行真实
  提交 → 落盘就绪信号 → 无限休眠等待父进程真实 kill -9。注入点位于
  "恢复动作提交后、恢复证据写入前"：恢复动作已真实提交（发布状态=完成
  或已回滚），恢复证据尚未写入（恢复证据由 二阶恢复校验.写入恢复证据
  负责）——再次启动恢复必须幂等落到明确版本，证据链只新增不覆盖。
- 子进程主入口：按环境变量执行 恢复（含注入）模式，输出 JSON 行。
  初始发布与一阶强杀（激活中途被杀）由 平台控制面/提供者/发布强杀注入.py
  负责，本模块只补二阶场景：恢复进程自身在恢复中途被强杀。

用法（测试中心/慢速层/第十四阶段/测试_工作包13_二阶恢复强杀.py 调用）：
    python3.14 测试中心/辅助/灾难恢复审计/二阶恢复注入.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def _定位系统根() -> Path:
    """定位含 平台控制面 且 测试中心 的仓库根。

    注意：测试中心/平台控制面/ 是测试目录（同名），不能作为系统根，
    因此必须同时满足「平台控制面」与「测试中心」两个目录都存在。
    """
    for 祖先 in Path(__file__).resolve().parents:
        if (祖先 / "平台控制面").is_dir() and (祖先 / "测试中心").is_dir():
            return 祖先
    return Path(__file__).resolve().parents[3]


系统根 = _定位系统根()
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 平台控制面.平台状态 import 平台状态
from 平台控制面.发布管理 import 发布管理


class 二阶强杀注入状态(平台状态):
    """平台状态 + 二阶注入钩子：恢复动作真实提交后暂停，等待父进程 kill -9。"""

    def __init__(self, 存储目录: Path, *, 注入点: str = "无", 就绪文件: str = "") -> None:
        super().__init__(存储目录)
        self.注入点 = 注入点
        self.就绪文件 = 就绪文件
        self._已注入 = False

    def 注入暂停(self) -> None:
        """就绪信号落盘后无限休眠；父进程看到就绪文件后真实 kill -9。"""
        if self.就绪文件:
            with open(self.就绪文件, "w", encoding="utf-8") as 文件:
                json.dump({"阶段": "恢复提交后", "pid": os.getpid(),
                           "时间": time.strftime("%H:%M:%S")}, 文件, ensure_ascii=False)
        while True:
            time.sleep(60)

    def 条件更新(self, 表: str, 更新: dict, 条件SQL: str, 参数: tuple) -> bool:
        if 表 == "发布" and 更新.get("状态") in ("完成", "已回滚") \
                and self.注入点 == "恢复提交后" and not self._已注入:
            self._已注入 = True
            结果 = super().条件更新(表, 更新, 条件SQL, 参数)  # 真实恢复动作提交
            self.注入暂停()  # 恢复动作提交后、恢复证据写入前：永不返回
            return 结果
        return super().条件更新(表, 更新, 条件SQL, 参数)


def 子进程主入口() -> int:
    """子进程入口：环境变量驱动，执行 恢复未完成发布（含注入）。"""
    模式 = os.environ["注入模式"]
    存储目录 = Path(os.environ["注入存储目录"])
    注入点 = os.environ.get("注入点", "恢复提交后")
    就绪文件 = os.environ.get("注入就绪文件", "")
    if 模式 == "恢复":
        状态 = 二阶强杀注入状态(存储目录, 注入点=注入点, 就绪文件=就绪文件)
        发布 = 发布管理(状态)
        恢复表 = 发布.恢复未完成发布()  # 恢复动作提交后触发注入暂停（若配置）
        输出 = {"恢复表": 恢复表, "发布记录表": 状态.查询记录("发布"),
                "指针表": 状态.查询记录("激活指针")}
    else:
        输出 = {"错误": f"未知注入模式: {模式}"}
        return 2
    print(json.dumps(输出, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(子进程主入口())
