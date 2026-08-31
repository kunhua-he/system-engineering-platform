"""Agent 查询入口：统一查询 API（替代直接读源码的标准流程）。

标准流程：搜索能力 → 查看契约 → 查看版本 → 查看配置 → 查看验证状态
→ 查看已知失败 → 再决定调用或升级。
"""

from __future__ import annotations

import sys
from pathlib import Path

系统根 = Path(__file__).resolve().parents[1]
for _祖先 in 系统根.parents:
    if (_祖先 / "支持库").is_dir() and (_祖先 / "模块库").is_dir():
        系统根 = _祖先
        break
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))  # 支持直接运行（python3.14 Agent查询/查询入口.py）

from dataclasses import dataclass, field
from typing import Any

from 运行核心.运行诊断.诊断中心.诊断中心 import 归类失败, 关联验证场景, 诊断失败, 生成失败摘要
from 运行核心.加载器.版本系统.热切换 import 热切换管理器
from 运行核心.加载器.版本系统.版本注册表 import 版本注册表


@dataclass
class 查询结果:
    """一次查询的结果。"""

    成功: bool = False
    数据: Any = None
    说明: str = ""


class 查询入口:
    """Agent 标准查询入口（只读，不修改系统状态）。"""

    def __init__(self, 版本注册表实例: 版本注册表 | None = None,
                 热切换: 热切换管理器 | None = None,
                 失败库: Any = None) -> None:
        self.版本注册表 = 版本注册表实例 or 版本注册表()
        self.热切换 = 热切换 or 热切换管理器(self.版本注册表)
        self.失败库 = 失败库

    def 搜索能力(self, 声明列表: list | None = None, *, 关键词: str = "") -> 查询结果:
        """搜索能力（只读声明，不加载实现）。"""
        from 开发工具.能力搜索.能力搜索器 import 搜索带原因
        from 运行核心.加载器.包发现.发现器 import 发现全部
        from pathlib import Path

        系统根 = Path(__file__).resolve().parents[1]
        for _祖先 in 系统根.parents:
            if (_祖先 / "支持库").is_dir() and (_祖先 / "模块库").is_dir():
                系统根 = _祖先
                break
        声明列表 = 声明列表 or 发现全部(系统根 / "支持库", 系统根 / "模块库").声明列表
        结果列表, 原因 = 搜索带原因(声明列表, 关键词=关键词)
        if 原因:
            return 查询结果(成功=False, 说明=原因)
        return 查询结果(成功=True, 数据=结果列表, 说明=f"找到 {len(结果列表)} 个能力")

    def 查看包版本(self, 包id: str = "") -> 查询结果:
        版本列表 = self.版本注册表.查询版本(包id=包id)
        return 查询结果(成功=True, 数据=[包.转字典() for 包 in 版本列表],
                         说明=f"{len(版本列表)} 个版本")

    def 查看能力版本(self, 能力id: str) -> 查询结果:
        激活版本 = self.热切换.当前激活版本(能力id)
        回滚版本 = self.热切换.可回滚版本(能力id)
        return 查询结果(成功=True, 数据={
            "能力id": 能力id, "当前激活版本": 激活版本, "可回滚版本": 回滚版本,
        })

    def 查看兼容范围(self, 能力id: str) -> 查询结果:
        return 查询结果(成功=True, 数据={"能力id": 能力id, "说明": "兼容范围见契约兼容判断"}, 说明="调用 契约兼容.检查契约兼容")

    def 查询失败记录(self, *, 包id: str = "", 错误码: str = "", 状态: str = "") -> 查询结果:
        if self.失败库 is None:
            return 查询结果(成功=False, 说明="失败记录库未接入")
        记录列表 = self.失败库.查询(包id=包id, 错误码=错误码, 状态=状态)
        return 查询结果(成功=True, 数据=[记录.转字典() for 记录 in 记录列表],
                         说明=f"{len(记录列表)} 条失败记录")

    def 查看诊断详情(self, 记录id: str) -> 查询结果:
        if self.失败库 is None:
            return 查询结果(成功=False, 说明="失败记录库未接入")
        记录 = self.失败库.记录表.get(记录id)
        if 记录 is None:
            return 查询结果(成功=False, 说明=f"失败记录不存在: {记录id}")
        return 查询结果(成功=True, 数据=诊断失败(记录).结论)

    def 查看关联验证场景(self, 错误码: str) -> 查询结果:
        return 查询结果(成功=True, 数据=关联验证场景(错误码),
                         说明=f"错误码 {错误码} 推荐验证场景")

    def 执行升级前检查(self, 能力id: str, 新版本: str) -> 查询结果:
        """升级前检查：契约/版本/失败记录（不执行切换）。"""
        检查项 = [
            f"版本 {新版本} 已注册: {self.版本注册表.获取版本(能力id.split('.')[0], 新版本) is not None}",
            f"当前激活版本: {self.热切换.当前激活版本(能力id)}",
            f"失败归类参考: {归类失败('版本不兼容')}",
        ]
        return 查询结果(成功=True, 数据=检查项, 说明="升级前检查完成")

    def 查看升级状态(self, 能力id: str) -> 查询结果:
        回滚记录 = [记录 for 记录 in self.热切换.回滚记录表 if 记录.get("能力id") == 能力id]
        return 查询结果(成功=True, 数据={"回滚记录": 回滚记录[-3:]},
                         说明=f"最近回滚 {len(回滚记录)} 次")

    def 生成诊断摘要(self, *, 包id: str = "") -> 查询结果:
        if self.失败库 is None:
            return 查询结果(成功=False, 说明="失败记录库未接入")
        记录列表 = self.失败库.查询(包id=包id)
        return 查询结果(成功=True, 数据=生成失败摘要(记录列表))

    def 查看验证状态(self, *, 证据目录参数: str | Path | None = None,
               提交: str = "", 工作区指纹: str = "") -> 查询结果:
        """只读正式发布证据，与开发入口共享同一唯一事实源。"""
        from MCP工具箱.发布治理 import 读取正式发布状态
        状态 = 读取正式发布状态(
            证据目录=证据目录参数, 提交=提交, 工作区指纹=工作区指纹)
        return 查询结果(成功=状态.成功, 数据=状态.数据, 说明=状态.消息)

    def 标准流程(self, 关键词: str) -> list[str]:
        """标准调用前流程：搜索→契约→版本→配置→验证→已知失败。"""
        步骤 = [f"① 搜索能力（关键词: {关键词}）"]
        搜索 = self.搜索能力(关键词=关键词)
        步骤.append(f"② 查看契约（{'成功' if 搜索.成功 else 搜索.说明}）")
        步骤.append("③ 查看版本（版本注册表）")
        步骤.append("④ 查看配置（项目配置/默认配置.json）")
        步骤.append("⑤ 查看验证状态（当前测试中心 unittest 模块记录）")
        步骤.append("⑥ 查看已知失败（诊断中心）")
        return 步骤
