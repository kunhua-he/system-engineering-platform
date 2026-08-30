"""后端核心：通用运行宿主。

后端核心负责：支持库和模块发现、包版本解析、项目适配装配、能力注册、
能力调用、服务生命周期、后台任务、外部提供者管理、请求上下文、权限
检查、超时和取消、统一错误、运行事件、诊断关联、版本切换、停止和卸载。

后端核心不实现具体业务，只提供通用运行宿主。公开入口只能是能力契约
和统一结果。
"""

from __future__ import annotations

import copy
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from 公共契约.基础类型.结果类型 import 结果
from 公共契约.能力契约.契约 import 能力实现, 能力注册表
from 运行核心.能力调用.运行上下文.上下文 import 运行上下文, 全局上下文管理器
from 运行核心.资源协调 import 资源句柄服务

_装配模板: 能力注册表 | None = None
_装配锁 = threading.Lock()


@dataclass
class 后端状态:
    """后端核心运行状态。"""

    状态: str = "未启动"  # 未启动/启动中/运行中/已停止/故障
    启动时间: str = ""
    能力数: int = 0
    请求总数: int = 0
    失败请求数: int = 0
    活动请求数: int = 0


class 后端核心:
    """后端核心宿主：装配、注册、调用、任务、生命周期。"""

    def __init__(self, 系统根目录: Path | None = None) -> None:
        self.系统根目录 = 系统根目录 or Path(后端核心.默认系统根())
        self.注册表 = 能力注册表()
        self.状态 = 后端状态()
        self.权限表: dict[str, set[str]] = {}  # 能力id → 允许用户id集合
        self.请求锁 = threading.Lock()
        self.停止标记 = False
        self.事件日志 = None
        self.排空 = None  # 自动排空管理器（启动时装配）
        self.资源句柄服务 = 资源句柄服务(self.系统根目录 / "工程缓存" / "权威状态")

    def 资源状态(self, 句柄: int, *, 项目id: str = "", 所有者: str = "") -> dict | None:
        return self.资源句柄服务.状态(句柄, 项目id=项目id, 所有者=所有者)

    def 资源续租(self, 句柄: int, *, 租约秒: float = 300,
                 项目id: str = "", 所有者: str = "") -> dict:
        return self.资源句柄服务.续租(句柄, 租约秒=租约秒, 项目id=项目id, 所有者=所有者)

    def 资源关闭(self, 句柄: int, *, 项目id: str = "", 所有者: str = "") -> dict:
        return self.资源句柄服务.关闭(句柄, 项目id=项目id, 所有者=所有者)

    def 启用自动排空(self, 排空超时秒: float = 3.0) -> None:
        """启用自动有状态排空：调用前后自动计数，异常路径也减。"""
        from 运行核心.资源协调.有状态排空.排空管理 import 排空管理器
        self.排空 = 排空管理器(排空超时秒=排空超时秒)

    def 注册排空终止器(self, 名称: str, 终止函数: Callable[[], Any]) -> None:
        """登记由后端核心统一触发的真实资源终止函数。"""
        if self.排空 is None:
            self.启用自动排空()
        self.排空.注册强制终止器(名称, 终止函数)

    @staticmethod
    def 默认系统根() -> str:
        return str(Path(__file__).resolve().parents[1])

    def 装配(self) -> 结果:
        """发现并装配系统内全部支持库与模块（装配模板缓存复用）。"""
        global _装配模板
        from 运行核心.加载器.生命周期管理.管理器 import 装配系统
        with _装配锁:
            if _装配模板 is None:
                # 首次：全量装配并把纯净注册表存为模板
                装配结果 = 装配系统(
                    self.系统根目录 / "支持库", self.系统根目录 / "模块库", self.注册表
                )
                if not 装配结果.成功:
                    return 结果.失败("装配失败", "; ".join(装配结果.问题列表), 来源="后端核心")
                _装配模板 = copy.deepcopy(self.注册表)
            else:
                # 后续：模板深拷贝，避免重复全量扫描（大幅降低测试/多实例开销）
                self.注册表 = copy.deepcopy(_装配模板)
                if self.注册表 is None:
                    return 结果.失败("装配失败", "装配模板缺失", 来源="后端核心")
        return 结果.成功结果(len(self.注册表.能力id列表))

    def 启动(self) -> 结果:
        """启动后端核心（装配 + 就绪）。"""
        self.停止标记 = False
        self.状态.状态 = "启动中"
        装配结果 = self.装配()
        if not 装配结果.成功:
            self.状态.状态 = "故障"
            return 装配结果
        self.状态.状态 = "运行中"
        self.状态.启动时间 = time.strftime("%Y-%m-%d %H:%M:%S")
        self.状态.能力数 = len(self.注册表.能力id列表)
        return 结果.成功结果(f"后端核心已就绪，{self.状态.能力数} 个能力")

    def 注册能力(self, 能力id: str, 实现函数: Callable, *, 参数: list | None = None,
                 返回: str = "结果", 说明: str = "") -> 结果:
        try:
            self.注册表.注册(能力实现(
                能力id=能力id, 包id="后端核心", 实现函数=实现函数,
                参数=参数 or [], 返回=返回, 说明=说明,
            ))
        except ValueError as 错误:
            return 结果.失败("能力重复", str(错误), 来源="后端核心")
        return 结果.成功结果(能力id)

    def 设置权限(self, 能力id: str, 允许用户id列表: list[str]) -> None:
        self.权限表[能力id] = set(允许用户id列表)

    def 调用(self, 能力id: str, 参数: dict | None = None, *,
             上下文: 运行上下文 | None = None, 超时秒: float = 10.0) -> 结果:
        """按能力契约调用；权限/超时/取消/统一错误；自动排空计数。"""
        if self.状态.状态 != "运行中":
            return 结果.失败("外部不可访问", f"后端核心未运行（状态 {self.状态.状态}）", 来源="后端核心")
        上下文 = 上下文 or 运行上下文()
        排空活动 = False
        if self.排空 is not None:
            if not self.排空.开始请求():
                return 结果.失败("外部不可访问", "排空中，拒绝新请求", 来源="后端核心")
            排空活动 = True
        try:
            全局上下文管理器.进入(上下文)
            try:
                return self._调用内部(能力id, 参数, 上下文)
            finally:
                全局上下文管理器.退出()
        finally:
            if 排空活动:
                self.排空.结束请求()  # 异常路径也减计数

    def _调用内部(self, 能力id: str, 参数: dict | None,
                 上下文: 运行上下文) -> 结果:
        with self.请求锁:
            self.状态.请求总数 += 1
            self.状态.活动请求数 += 1
        try:
            允许用户 = self.权限表.get(能力id)
            if 允许用户 is not None and 上下文.用户id and 上下文.用户id not in 允许用户:
                返回结果 = 结果.失败("权限不足", f"用户 {上下文.用户id} 无权限调用 {能力id}", 来源="后端核心")
            else:
                实现 = self.注册表.获取(能力id)
                if 实现 is None:
                    返回结果 = 结果.失败("能力不存在", f"能力未注册: {能力id}", 来源="后端核心")
                else:
                    try:
                        调用结果 = 实现.调用(**dict(参数 or {}))
                        返回结果 = 调用结果 if isinstance(调用结果, 结果) else 结果.成功结果(调用结果)
                    except TypeError as 错误:
                        返回结果 = 结果.失败("参数不合法", f"调用参数错误: {错误}", 来源="后端核心")
                    except FileNotFoundError as 错误:
                        # 文件/资源能力的标准缺失语义必须跨 HTTP 保留，
                        # 不能被通用异常转换成无法定位的“内部错误”。
                        返回结果 = 结果.失败("文件不存在", str(错误), 来源="后端核心")
                    except Exception as 错误:  # noqa: BLE001 - 能力边界统一转换外部实现异常
                        返回结果 = 结果.失败("内部错误", f"调用异常: {错误}", 来源="后端核心")
            if not 返回结果.成功:
                with self.请求锁:
                    self.状态.失败请求数 += 1
            return 返回结果
        finally:
            with self.请求锁:
                self.状态.活动请求数 = max(0, self.状态.活动请求数 - 1)

    def 健康检查(self) -> 结果:
        if self.状态.状态 == "运行中":
            return 结果.成功结果({"状态": "健康", "能力数": self.状态.能力数})
        return 结果.失败("外部不可访问", f"后端核心状态: {self.状态.状态}", 来源="后端核心")

    def 能力搜索(self, *, 关键词: str = "", 限制: int = 20) -> list[dict]:
        """按关键词返回紧凑候选；完整契约只能经 能力详情 按需读取。"""
        if isinstance(限制, bool) or not isinstance(限制, int) or 限制 < 1:
            限制 = 20
        限制 = min(限制, 100)
        return [
            {"能力id": 能力id, "包id": self.注册表.获取(能力id).包id,
             "简介": self._紧凑说明(self.注册表.获取(能力id).说明 or "")}
            for 能力id in self.注册表.能力id列表
            if not 关键词 or 关键词 in 能力id or 关键词 in (self.注册表.获取(能力id).说明 or "")
        ][:限制]

    @staticmethod
    def _紧凑说明(说明: str, 上限: int = 60) -> str:
        """目录简介最多 60 字；去除换行和多余空白。"""
        文本 = " ".join(str(说明 or "").split())
        return 文本 if len(文本) <= 上限 else 文本[:上限 - 1] + "…"

    def _包目录路径(self, 包id: str) -> Path | None:
        """仅允许读取已注册包自己的公开声明目录。"""
        if not isinstance(包id, str) or not 包id:
            return None
        已注册包 = {
            self.注册表.获取(能力id).包id for 能力id in self.注册表.能力id列表
        }
        if 包id not in 已注册包:
            return None
        候选 = self.系统根目录.joinpath(*包id.split(".")).resolve()
        try:
            候选.relative_to(self.系统根目录.resolve())
        except ValueError:
            return None
        return 候选 if (候选 / "包声明.json").is_file() else None

    @staticmethod
    def _读取JSON(路径: Path) -> dict:
        try:
            数据 = json.loads(路径.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        return 数据 if isinstance(数据, dict) else {}

    def 能力目录(self, *, 关键词: str = "", 偏移: int = 0, 限制: int = 20) -> dict:
        """Skill 式第一层：分页返回包级树和紧凑简介，不返回命令参数。"""
        if isinstance(偏移, bool) or not isinstance(偏移, int) or 偏移 < 0:
            偏移 = 0
        if isinstance(限制, bool) or not isinstance(限制, int) or 限制 < 1:
            限制 = 20
        限制 = min(限制, 100)
        包表: dict[str, dict] = {}
        for 能力id in self.注册表.能力id列表:
            实现 = self.注册表.获取(能力id)
            if 实现.包id in 包表:
                包表[实现.包id]["能力数"] += 1
                continue
            包目录 = self._包目录路径(实现.包id)
            声明 = self._读取JSON(包目录 / "包声明.json") if 包目录 else {}
            名称 = str(声明.get("名称") or 实现.包id.rsplit(".", 1)[-1])
            简介 = self._紧凑说明(str(声明.get("说明") or 实现.说明 or ""))
            包表[实现.包id] = {
                "包id": 实现.包id, "名称": 名称, "简介": 简介, "能力数": 1,
            }
        if 关键词:
            包表 = {
                包id: 条目 for 包id, 条目 in 包表.items()
                if 关键词 in 包id or 关键词 in 条目["名称"] or 关键词 in 条目["简介"]
            }
        包条目表 = [条目 for _, 条目 in sorted(包表.items())]
        总数 = len(包条目表)
        当前页 = 包条目表[偏移:偏移 + 限制]
        下一偏移 = 偏移 + len(当前页)
        支持库树: dict[str, list[dict]] = {}
        模块列表: list[dict] = []
        for 条目 in 当前页:
            包id = 条目["包id"]
            if 包id.startswith("支持库."):
                分段 = 包id.split(".")
                领域 = 分段[1] if len(分段) > 2 else "其他"
                支持库树.setdefault(领域, []).append(条目)
            elif 包id.startswith("模块库."):
                模块列表.append(条目)
        return {
            "使用顺序": ["选择包", "查看包详情", "查看能力详情", "调用能力"],
            "支持库": [{"领域": 领域, "包": 包列表} for 领域, 包列表 in sorted(支持库树.items())],
            "模块库": 模块列表,
            "包数": len(当前页),
            "总包数": 总数,
            "偏移": 偏移,
            "限制": 限制,
            "下一偏移": 下一偏移 if 下一偏移 < 总数 else None,
            "是否完成": 下一偏移 >= 总数,
        }

    def 包详情(self, 包id: str) -> dict | None:
        """Skill 式第二层：只返回该包的命令目录，不展开参数正文。"""
        包目录 = self._包目录路径(包id)
        if 包目录 is None:
            return None
        声明 = self._读取JSON(包目录 / "包声明.json")
        命令表 = []
        for 能力 in 声明.get("能力", []):
            if not isinstance(能力, dict) or not 能力.get("能力id"):
                continue
            命令表.append({
                "能力id": 能力["能力id"],
                "名称": 能力.get("名称") or str(能力["能力id"]).rsplit(".", 1)[-1],
                "简介": self._紧凑说明(str(能力.get("说明") or "")),
            })
        return {
            "包id": 包id, "名称": 声明.get("名称", ""),
            "简介": self._紧凑说明(str(声明.get("说明") or "")),
            "版本": 声明.get("版本", ""), "命令": 命令表,
            "下一步": "选中能力id后调用 能力详情；此处不返回参数正文",
        }

    def 能力详情(self, 能力id: str) -> dict | None:
        """Skill 式第三层：按需读取单个能力的完整权威契约和调用方式。"""
        实现 = self.注册表.获取(能力id)
        if 实现 is None:
            return None
        包目录 = self._包目录路径(实现.包id)
        if 包目录 is None:
            return None
        契约总表 = self._读取JSON(包目录 / "能力契约" / "参数契约.json")
        能力表 = 契约总表.get("能力契约", 契约总表.get("能力列表", []))
        正文 = next((项 for 项 in 能力表
                   if isinstance(项, dict) and 项.get("能力id") == 能力id), None)
        if 正文 is None:
            正文 = {
                "能力id": 能力id, "说明": 实现.说明,
                "参数": 实现.参数, "返回": {"类型": 实现.返回},
            }
        声明 = self._读取JSON(包目录 / "包声明.json")
        返回正文 = copy.deepcopy(正文)
        返回正文["包id"] = 实现.包id
        返回正文["包版本"] = 声明.get("版本", 实现.版本)
        返回正文["契约版本"] = 契约总表.get("契约版本", "")
        返回正文["依赖"] = 声明.get("依赖", [])
        返回正文["配置契约"] = self._读取JSON(包目录 / "配置契约" / "配置契约.json")
        返回正文["资源预算"] = self._读取JSON(包目录 / "资源预算.json")
        返回正文["调用方式"] = {
            "操作": "调用能力", "目标": 能力id,
            "参数": 正文.get("调用示例", {}).get("参数", 正文.get("调用示例", {})),
        }
        return 返回正文

    def 优雅关闭(self) -> 结果:
        """优雅关闭：等待活动请求归零后停止。"""
        if self.状态.状态 == "已停止":
            return 结果.成功结果("已停止（幂等）")
        self.停止标记 = True
        if self.排空 is not None:
            排空结果 = self.排空.排空()
            if not 排空结果.成功:
                return 结果.失败("排空超时", 排空结果.诊断记录, 来源="后端核心")
        try:
            self.资源句柄服务.关闭服务()
        except Exception as 错误:
            self.状态.状态 = "故障"
            return 结果.失败(
                "资源释放失败", f"资源句柄服务关闭失败: {错误}", 来源="后端核心")
        self.状态.状态 = "已停止"
        return 结果.成功结果("后端核心已优雅关闭")

    def 强制关闭(self) -> 结果:
        self.停止标记 = True
        if self.排空 is not None:
            排空结果 = self.排空.排空()
            if not 排空结果.成功:
                return 结果.失败("资源未释放", 排空结果.诊断记录, 来源="后端核心")
        try:
            self.资源句柄服务.关闭服务()
        except Exception as 错误:
            self.状态.状态 = "故障"
            return 结果.失败(
                "资源释放失败", f"资源句柄服务关闭失败: {错误}", 来源="后端核心")
        self.状态.状态 = "已停止"
        return 结果.成功结果("后端核心已强制关闭")

    def 状态快照(self) -> dict[str, Any]:
        return {
            "状态": self.状态.状态, "启动时间": self.状态.启动时间,
            "能力数": self.状态.能力数, "请求总数": self.状态.请求总数,
            "失败请求数": self.状态.失败请求数, "活动请求数": self.状态.活动请求数,
        }
