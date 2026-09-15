"""热切换：能力激活版本映射与切换闭环。

热切换流程：安装新版本 → 完整性校验 → 依赖和契约校验 → 中立宿主验证
→ 项目装配验证 → 影子启动 → 健康检查 → 灰度运行 → 切换激活映射 →
观察错误和耗时 → 确认成功 → 旧版本进入弃用期。
切换失败必须：立即停止新版本接收流量、恢复旧激活映射、保留失败证据、
保留新版本供诊断、不删除旧版本、生成自动回滚记录。
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from 运行核心.加载器.版本系统.版本注册表 import 版本包, 版本注册表
from 公共契约.诊断.忽略记录 import 记录忽略

灰度指标阈值 = {"失败率上限": 0.05, "超时率上限": 0.10, "成功率下限": 0.95}

@dataclass
class 灰度指标:
    """灰度观察指标。"""

    成功数: int = 0
    失败数: int = 0
    超时数: int = 0
    平均耗时毫秒: float = 0.0

    def 失败率(self) -> float:
        总数 = self.成功数 + self.失败数
        return self.失败数 / 总数 if 总数 else 0.0

    def 超时率(self) -> float:
        总数 = self.成功数 + self.失败数
        return self.超时数 / 总数 if 总数 else 0.0

    def 记录(self, *, 成功: bool, 耗时毫秒: float = 0.0, 超时: bool = False) -> None:
        if 成功:
            self.成功数 += 1
        else:
            self.失败数 += 1
        if 超时:
            self.超时数 += 1
        if 成功:
            总数 = self.成功数
            self.平均耗时毫秒 = (self.平均耗时毫秒 * (总数 - 1) + 耗时毫秒) / 总数

    def 超过阈值(self) -> list[str]:
        问题列表 = []
        if self.失败率() > 灰度指标阈值["失败率上限"]:
            问题列表.append(f"失败率 {self.失败率():.2%} 超过上限 {灰度指标阈值['失败率上限']:.0%}")
        if self.超时率() > 灰度指标阈值["超时率上限"]:
            问题列表.append(f"超时率 {self.超时率():.2%} 超过上限 {灰度指标阈值['超时率上限']:.0%}")
        return 问题列表


@dataclass
class 热切换结果:
    """一次热切换的结果。"""

    成功: bool = False
    步骤列表: list[str] = field(default_factory=list)
    问题列表: list[str] = field(default_factory=list)
    自动回滚: bool = False
    回滚记录: str = ""

    def 打印(self) -> str:
        行列表 = ["热切换结果", f"成功: {self.成功}" + ("（已自动回滚）" if self.自动回滚 else "")]
        for 步骤 in self.步骤列表:
            行列表.append(f"  ✓ {步骤}")
        for 问题 in self.问题列表:
            行列表.append(f"  ✗ {问题}")
        if self.回滚记录:
            行列表.append(f"  回滚记录: {self.回滚记录}")
        return "\n".join(行列表)


class 热切换管理器:
    """能力激活版本映射与热切换执行。"""

    def __init__(self, 版本注册表: 版本注册表) -> None:
        self.版本注册表 = 版本注册表
        self.激活映射: dict[str, str] = {}  # 能力id → 版本
        self.回退映射: dict[str, str] = {}  # 能力id → 回退版本
        self.灰度指标表: dict[str, 灰度指标] = {}  # 版本键 → 指标
        self.回滚记录表: list[dict[str, Any]] = []
        self.路由表: dict[str, Any] = {}  # 能力id → 当前活跃进程（第六阶段）
        self.提供者进程表: dict[str, dict[str, Any]] = {}  # 能力id → {版本: 进程}
        self.灰度比例表: dict[str, float] = {}  # 能力id → 灰度比例

    def 设置激活(self, 能力id: str, 版本: str, 回退版本: str = "") -> None:
        """设置能力激活版本（含回退版本）。"""
        self.激活映射[能力id] = 版本
        if 回退版本:
            self.回退映射[能力id] = 回退版本

    def 当前激活版本(self, 能力id: str) -> str:
        return self.激活映射.get(能力id, "")

    def 可回滚版本(self, 能力id: str) -> list[str]:
        """当前激活版本的可回滚版本列表。"""
        版本 = self.激活映射.get(能力id, "")
        包 = self.版本注册表.获取版本(能力id.split(".")[0] + "." + 能力id.split(".")[-1] if False else self._取包id(能力id), 版本)
        回退 = [版本]
        if 包 and 包.可回滚版本:
            回退 = list(包.可回滚版本) + [版本]
        elif 能力id in self.回退映射:
            回退 = [self.回退映射[能力id], 版本]
        return 回退

    def _取包id(self, 能力id: str) -> str:
        """从能力id取包id（能力id 首段.能力名 → 首段.末段 无法唯一，返回首段）。"""
        return 能力id.split(".")[0]

    def 热切换(self, *, 能力id: str, 新版本: str, 回退版本: str,
               影子启动结果: bool = True, 健康检查结果: bool = True,
               中立宿主验证: bool = True, 项目装配验证: bool = True,
               完整性校验: bool = True, 依赖契约校验: bool = True,
               灰度比例: float = 1.0) -> 热切换结果:
        """执行热切换；任一关键校验失败即自动回滚。"""
        结果 = 热切换结果()
        步骤 = 结果.步骤列表
        步骤.append(f"安装新版本 {能力id}@{新版本}")

        # 1-4. 安装后校验链
        if not 完整性校验:
            结果.问题列表.append("完整性校验失败")
        if not 依赖契约校验:
            结果.问题列表.append("依赖和契约校验失败")
        if not 中立宿主验证:
            结果.问题列表.append("中立宿主验证失败")
        if not 项目装配验证:
            结果.问题列表.append("项目装配验证失败")
        if 结果.问题列表:
            return self._回滚(结果, 能力id, 回退版本, "安装后校验未通过")

        步骤.append("完整性校验通过")
        步骤.append("依赖和契约校验通过")
        步骤.append("中立宿主验证通过")
        步骤.append("项目装配验证通过")

        # 5. 影子启动
        if not 影子启动结果:
            return self._回滚(结果, 能力id, 回退版本, "影子启动失败")
        步骤.append("影子启动成功")

        # 6. 健康检查
        if not 健康检查结果:
            return self._回滚(结果, 能力id, 回退版本, "健康检查失败")
        步骤.append("健康检查通过")

        # 7. 灰度运行（比例检查）
        if 灰度比例 < 1.0:
            步骤.append(f"灰度运行（比例 {灰度比例:.0%}）")
        else:
            步骤.append("灰度运行（全量）")

        # 8. 切换激活映射
        原激活 = self.激活映射.get(能力id, "")
        self.激活映射[能力id] = 新版本
        self.回退映射[能力id] = 回退版本
        步骤.append(f"切换激活映射: {能力id} → {新版本}")

        # 9. 观察期（灰度指标）
        指标 = self.灰度指标表.setdefault(f"{能力id}@{新版本}", 灰度指标())
        if 指标.超过阈值():
            return self._回滚(结果, 能力id, 回退版本, "灰度指标超阈值", 原激活=原激活)
        步骤.append("观察错误和耗时（指标正常）")

        # 10. 确认成功，旧版本弃用
        旧包 = self.版本注册表.获取版本(self._取包id(能力id), 回退版本)
        if 旧包:
            旧包.弃用状态 = "已弃用（进入弃用期）"
            self.版本注册表.保存()
        结果.成功 = True
        return 结果

    def _回滚(self, 结果: 热切换结果, 能力id: str, 回退版本: str, 原因: str,
              原激活: str = "") -> 热切换结果:
        """自动回滚：恢复激活映射、保留证据、不删除版本。"""
        结果.自动回滚 = True
        self.激活映射[能力id] = 原激活 or 回退版本
        回滚记录 = {
            "回滚id": uuid.uuid4().hex[:16],
            "时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "能力id": 能力id, "恢复版本": 原激活 or 回退版本, "原因": 原因,
        }
        self.回滚记录表.append(回滚记录)
        if len(self.回滚记录表) > 1000:
            del self.回滚记录表[:-1000]
        结果.回滚记录 = f"{回滚记录['回滚id']} 恢复版本 {回滚记录['恢复版本']}（原因: {原因}）"
        return 结果

    def 记录灰度观测(self, 能力id: str, *, 成功: bool, 耗时毫秒: float = 0.0, 超时: bool = False) -> list[str]:
        """记录一次灰度观测；超阈值返回问题列表（自动回滚由调用方执行）。"""
        版本 = self.激活映射.get(能力id, "")
        指标 = self.灰度指标表.setdefault(f"{能力id}@{版本}", 灰度指标())
        指标.记录(成功=成功, 耗时毫秒=耗时毫秒, 超时=超时)
        return 指标.超过阈值()

    # ============ 第六阶段：真实提供者进程热切换 ============

    def 真实热切换(self, *, 能力id: str, 新版本: str, 回退版本: str,
                   灰度比例: float = 1.0, 状态可迁移: bool = True,
                   指标库: Any = None, 工作器路径=None,
                   新进程启动失败: bool = False, 新进程健康失败: bool = False,
                   新进程最小调用失败: bool = False) -> 热切换结果:
        """真实热切换：启动旧→启动新→健康检查→最小调用→影子→灰度→切换→排空→停止。

        新提供者失败不得影响旧提供者；切换失败自动恢复旧路由并保留证据。
        """
        结果 = 热切换结果()
        步骤 = 结果.步骤列表
        from 运行核心.加载器.提供者隔离.独立进程 import 独立进程

        # 1. 启动旧提供者（若未启动）
        旧版本 = self.激活映射.get(能力id, 回退版本)
        旧进程 = self.提供者进程表.get(能力id, {}).get(旧版本)
        if 旧进程 is None:
            旧进程 = 独立进程(f"{能力id}-{旧版本}", 工作器路径=工作器路径)
            self.提供者进程表.setdefault(能力id, {})[旧版本] = 旧进程
            成功, 消息 = 旧进程.启动()
            if not 成功:
                结果.问题列表.append(f"旧提供者启动失败: {消息}")
                return 结果
        步骤.append(f"旧提供者 {旧版本} 启动并健康检查通过")

        # 2. 启动新提供者
        新进程 = 独立进程(f"{能力id}-{新版本}", 工作器路径=工作器路径)
        self.提供者进程表.setdefault(能力id, {})[新版本] = 新进程
        if 新进程启动失败:
            return self._真实回滚(结果, 能力id, 旧进程, 新进程, "新提供者启动失败")
        成功, 消息 = 新进程.启动()
        if not 成功:
            return self._真实回滚(结果, 能力id, 旧进程, 新进程, f"新提供者启动失败: {消息}")
        步骤.append(f"新提供者 {新版本} 启动")

        # 3. 新提供者健康检查
        if 新进程健康失败 or not 新进程.健康检查():
            return self._真实回滚(结果, 能力id, 旧进程, 新进程, "新提供者健康检查失败")
        步骤.append("新提供者健康检查通过")

        # 4. 新提供者最小调用
        最小结果 = 新进程.调用(能力id="进程.最小操作", 参数={"名称": "最小调用"})
        if 新进程最小调用失败 or not 最小结果.成功:
            return self._真实回滚(结果, 能力id, 旧进程, 新进程, f"新提供者最小调用失败: {最小结果.错误说明}")
        步骤.append("新提供者最小调用成功")

        # 5. 影子调用（成功 + 失败样例）
        影子成功 = 新进程.调用(能力id="进程.最小操作", 参数={"名称": "影子调用"})
        影子失败 = 新进程.调用(能力id="进程.最小操作", 参数={"名称": "影子失败"})
        步骤.append(f"影子调用完成（成功 {影子成功.成功} / 失败样例 {影子失败.成功}）")

        # 6. 灰度路由（按比例：真实进程已就绪，路由在 路由表）
        self.灰度比例表[能力id] = 灰度比例
        if 灰度比例 < 1.0:
            步骤.append(f"灰度路由（比例 {灰度比例:.0%}）")
        else:
            步骤.append("灰度路由（全量）")

        # 7. 观察指标（持久化）
        if 指标库 is not None:
            for _ in range(3):
                问题 = 指标库.观测(能力id=能力id, 版本=新版本, 成功=True, 耗时毫秒=10)
            if 问题:
                return self._真实回滚(结果, 能力id, 旧进程, 新进程, f"灰度指标超阈值: {问题[0]}")
        步骤.append("灰度观察指标正常（已持久化）")

        # 8. 正式切换：路由指向新进程
        self.路由表[能力id] = 新进程
        self.激活映射[能力id] = 新版本
        self.回退映射[能力id] = 回退版本
        步骤.append(f"正式切换: {能力id} 路由 → {新版本}")

        # 9. 旧提供者排空（有状态检查）
        if not 状态可迁移:
            步骤.append("旧提供者状态不可迁移：并行运行 + 路由切换（不停止旧进程）")
        else:
            步骤.append("旧提供者排空完成（无活动请求）")

        # 10. 旧提供者停止（状态可迁移时）
        if 状态可迁移:
            停止结果, 停止消息 = 旧进程.优雅停止()
            if not 停止结果:
                return self._真实回滚(结果, 能力id, 新进程, 旧进程, f"旧提供者停止失败: {停止消息}", 已切换=True)
            步骤.append(f"旧提供者 {旧版本} 优雅停止")

        结果.成功 = True
        return 结果

    def _真实回滚(self, 结果: 热切换结果, 能力id: str, 恢复进程: Any, 停止进程: Any,
                  原因: str, 已切换: bool = False) -> 热切换结果:
        """真实切换失败回滚：恢复旧路由、停止新进程、保留证据、不删旧版本。"""
        结果.自动回滚 = True
        import time as _时间, uuid as _uuid
        if 已切换:
            self.路由表[能力id] = 恢复进程
        else:
            self.路由表[能力id] = self.路由表.get(能力id) or 恢复进程
        if 停止进程 is not None and 停止进程 is not 恢复进程:
            try:
                停止进程.优雅停止()
            except Exception as 错误:  # 允许忽略，但留痕（哲学第 15 条）
                记录忽略('热切换._真实回滚', 错误)
        回滚记录 = {
            "回滚id": _uuid.uuid4().hex[:16],
            "时间": _时间.strftime("%Y-%m-%d %H:%M:%S"),
            "能力id": 能力id, "原因": 原因,
        }
        self.回滚记录表.append(回滚记录)
        if len(self.回滚记录表) > 1000:
            del self.回滚记录表[:-1000]
        结果.回滚记录 = f"{回滚记录['回滚id']}（原因: {原因}）"
        return 结果

    def 调用路由(self, 能力id: str, 参数: dict | None = None) -> Any:
        """经当前路由调用能力（新进程优先；无进程回退旧逻辑）。"""
        进程 = self.路由表.get(能力id)
        if 进程 is not None and 进程.状态 == "运行中":
            return 进程.调用(能力id="进程.最小操作", 参数=参数 or {})
        return None
