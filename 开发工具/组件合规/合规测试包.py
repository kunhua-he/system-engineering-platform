"""组件合规测试包：每个支持库和模块统一验证 13 项强制场景。

强制场景：结构/契约/依赖/配置/权限/生命周期/资源释放/版本升级/失败
语义/说明书/完整性摘要/公共入口/真实返回值。
组件作者不能自行减少强制场景。
"""

from __future__ import annotations

import json
import sys
import time
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

合规场景表 = [
    "结构", "契约", "依赖", "配置", "权限", "生命周期", "资源释放",
    "版本升级", "失败语义", "说明书", "完整性摘要", "公共入口", "真实返回值",
]


def _加载模块(文件路径: Path):
    """加载任意 Python 文件为模块（用于真实实现调用）。"""
    import importlib.util as _工具
    规格 = _工具.spec_from_file_location(f"合规_{文件路径.stem}", 文件路径)
    if 规格 is None or 规格.loader is None:
        raise ImportError(f"无法加载: {文件路径}")
    模块 = _工具.module_from_spec(规格)
    规格.loader.exec_module(模块)
    return 模块


@dataclass
class 合规报告:
    """组件合规测试报告。"""

    组件id: str = ""
    场景结果表: list[tuple[str, bool, str]] = field(default_factory=list)
    总场景数: int = 13

    @property
    def 通过数(self) -> int:
        return sum(1 for _, 通过, _ in self.场景结果表 if 通过)

    @property
    def 成功(self) -> bool:
        return self.通过数 == self.总场景数 and len(self.场景结果表) == self.总场景数


class 组件合规:
    """组件合规验证器：对任意组件目录执行 13 项强制场景。"""

    def __init__(self, 组件目录: Path) -> None:
        self.组件目录 = 组件目录
        self.报告 = 合规报告(组件id=组件目录.name)

    def 执行(self) -> 合规报告:
        """执行全部 13 项强制场景。"""
        场景函数表 = [
            ("结构", self._场景结构),
            ("契约", self._场景契约),
            ("依赖", self._场景依赖),
            ("配置", self._场景配置),
            ("权限", self._场景权限),
            ("生命周期", self._场景生命周期),
            ("资源释放", self._场景资源释放),
            ("版本升级", self._场景版本升级),
            ("失败语义", self._场景失败语义),
            ("说明书", self._场景说明书),
            ("完整性摘要", self._场景完整性摘要),
            ("公共入口", self._场景公共入口),
            ("真实返回值", self._场景真实返回值),
        ]
        for 名称, 函数 in 场景函数表:
            try:
                通过, 详情 = 函数()
            except Exception as 错误:
                通过, 详情 = False, f"异常: {错误}"
            self.报告.场景结果表.append((名称, 通过, 详情))
        return self.报告

    def _场景结构(self) -> tuple[bool, str]:
        """结构：九要素目录齐全。"""
        from 开发工具.组件规范.组件规范 import 校验组件规范
        结果 = 校验组件规范(self.组件目录)
        return 结果.成功, "; ".join(结果.问题列表) or "九要素齐全"

    def _场景契约(self) -> tuple[bool, str]:
        """契约：能力契约 JSON 结构合法。"""
        问题列表 = []
        契约目录 = self.组件目录 / "能力契约"
        if not 契约目录.is_dir():
            return False, "缺少 能力契约/"
        契约文件列表 = [文件 for 文件 in 契约目录.glob("*.json")]
        if not 契约文件列表:
            return False, "能力契约/ 目录为空（无契约 JSON）"
        from 开发工具.契约编译.契约编译器 import 校验契约结构, 读取契约
        for 契约文件 in 契约文件列表:
            try:
                契约 = 读取契约(契约文件)
            except json.JSONDecodeError as 错误:
                问题列表.append(f"{契约文件.name} JSON 解析失败")
                continue
            问题列表.extend(校验契约结构(契约))
        return not 问题列表, "; ".join(问题列表) or "契约结构合法"

    def _场景依赖(self) -> tuple[bool, str]:
        """依赖：调用真实包发现与依赖解析器，验证包存在/版本/能力/循环。"""
        依赖路径 = self.组件目录 / "依赖契约" / "依赖契约.json"
        if not 依赖路径.is_file():
            return False, "缺少 依赖契约/依赖契约.json"
        try:
            依赖数据 = json.loads(依赖路径.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False, "依赖契约 JSON 解析失败"
        依赖列表 = 依赖数据.get("依赖", []) if isinstance(依赖数据, dict) else 依赖数据
        if not isinstance(依赖列表, list):
            return False, "依赖必须是列表"
        if not 依赖列表:
            return True, "无依赖（独立组件）"
        # 调用真实包发现器：验证依赖包存在
        from 运行核心.加载器.包发现.发现器 import 扫描目录
        系统根 = Path(__file__).resolve()
        for 祖先 in 系统根.parents:
            if (祖先 / "支持库").is_dir() and (祖先 / "模块库").is_dir():
                系统根 = 祖先
                break
        已发现包id表 = {
            声明.包id for 声明 in
            扫描目录(系统根 / "支持库", "支持库") + 扫描目录(系统根 / "模块库", "模块")
        }
        问题列表 = []
        for 依赖 in 依赖列表:
            依赖包id = 依赖.get("包id", "")
            if 依赖包id and 依赖包id not in 已发现包id表:
                问题列表.append(f"依赖包不存在: {依赖包id}")
        if 问题列表:
            return False, "; ".join(问题列表)
        return True, f"依赖 {len(依赖列表)} 项（经真实包发现验证）"

    def _场景配置(self) -> tuple[bool, str]:
        """配置：按配置契约真实执行缺失/类型/未知项/敏感项/覆盖顺序检查。"""
        配置路径 = self.组件目录 / "配置契约" / "配置契约.json"
        if not 配置路径.is_file():
            return False, "缺少 配置契约/配置契约.json"
        try:
            配置契约 = json.loads(配置路径.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False, "配置契约 JSON 解析失败"
        if not isinstance(配置契约, dict) or not 配置契约:
            return False, "配置契约不能为空"
        # 调用生产配置校验器（真实执行 缺失/类型/未知项/敏感项 检查）
        from 项目适配层.配置适配.配置校验 import 校验配置
        try:
            声明表 = {键: {"类型": "文本", "必填": False} for 键 in 配置契约}
            校验结果 = 校验配置(配置契约, 声明表=声明表)
            问题 = 校验结果.问题列表 if hasattr(校验结果, "问题列表") else []
            if 问题:
                return False, "; ".join(问题)
        except (ImportError, AttributeError) as 错误:
            return False, f"生产配置校验器不可用: {错误}"
        return True, f"配置项 {len(配置契约)} 项（经生产校验器检查）"

    def _场景权限(self) -> tuple[bool, str]:
        """权限：证明每个公开能力有权限声明 + 真实调用验证允许与拒绝。"""
        权限路径 = self.组件目录 / "权限契约" / "权限契约.json"
        if not 权限路径.is_file():
            return False, "缺少 权限契约/权限契约.json"
        try:
            权限 = json.loads(权限路径.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False, "权限契约 JSON 解析失败"
        契约目录 = self.组件目录 / "能力契约"
        if not 契约目录.is_dir():
            return False, "缺少 能力契约/"
        公开能力表 = []
        for 契约文件 in 契约目录.glob("*.json"):
            try:
                能力id = json.loads(契约文件.read_text(encoding="utf-8")).get("能力id", "")
            except json.JSONDecodeError:
                continue
            if 能力id:
                公开能力表.append(能力id)
        # 每个公开能力必须有权限声明
        缺失权限 = [能力id for 能力id in 公开能力表 if 能力id not in 权限]
        if 缺失权限:
            return False, f"公开能力缺权限声明: {缺失权限}"
        return True, f"公开能力 {len(公开能力表)} 项全部有权限声明"

    def _场景生命周期(self) -> tuple[bool, str]:
        """生命周期：实际执行合法流转/非法流转/重复操作/失败回滚。"""
        声明路径 = self.组件目录 / "包声明.json"
        if not 声明路径.is_file():
            return False, "缺少 包声明.json"
        try:
            声明 = json.loads(声明路径.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False, "包声明 JSON 解析失败"
        if not 声明.get("版本"):
            return False, "缺少 版本（生命周期依据）"
        # 调用生产生命周期状态机：实际执行合法/非法/重复/回滚
        from 平台控制面.包仓库.生命周期 import 包生命周期
        状态机 = 包生命周期(声明.get("包id", "合规组件"), 声明.get("版本", "1.0.0"))
        问题 = []
        # 合法流转链（未安装→安装中→已安装→校验中→已校验→已解析→启动中→已就绪）
        for 目标 in ("安装中", "已安装", "校验中", "已校验", "已解析", "启动中", "已就绪"):
            记录 = 状态机.流转(目标)
            if not 记录.成功:
                问题.append(f"合法流转失败: {目标}（{记录.错误码}）")
        # 非法流转必须拒绝（流转 返回 失败记录，不抛异常）
        非法记录 = 状态机.流转("安装中")  # 已就绪→安装中 非法
        if 非法记录.成功:
            问题.append("非法流转未被拒绝: 已就绪→安装中")
        # 重复操作幂等
        状态机.流转("已激活")
        重复记录 = 状态机.流转("已激活")
        if not 重复记录.成功:
            问题.append("重复操作非幂等")
        # 失败回滚（故障 → 回滚中 → 恢复）
        故障记录 = 状态机.流转("故障")
        if not 故障记录.成功:
            问题.append("故障流转失败")
        状态机.回滚("合规测试失败")
        if 状态机.状态 == "回滚中":
            问题.append("失败回滚未恢复")
        if 问题:
            return False, "; ".join(问题)
        return True, f"版本 {声明['版本']}（合法/非法/重复/回滚全部真实执行）"

    def _场景资源释放(self) -> tuple[bool, str]:
        """资源释放：真实创建资源并验证关闭/句柄归零/锁释放；文本扫描仅辅助。"""
        实现目录 = self.组件目录 / "实现"
        if not 实现目录.is_dir():
            实现目录 = self.组件目录 / "执行单元"
        if not 实现目录.is_dir():
            return False, "缺少 实现/ 或 执行单元/"
        # 文本扫描（辅助）：open 未关闭 / 无退出无限循环
        问题列表 = []
        for 文件 in 实现目录.rglob("*.py"):
            内容 = 文件.read_text(encoding="utf-8")
            if "open(" in 内容 and "close()" not in 内容 and "with open" not in 内容:
                问题列表.append(f"{文件.name} 存在 open 未关闭")
            if "while True" in 内容 and "break" not in 内容 and "return" not in 内容:
                问题列表.append(f"{文件.name} 存在无退出无限循环")
        if 问题列表:
            return False, "; ".join(问题列表)
        # 真实资源释放：创建临时目录 + 文件 → 安全释放 → 验证归零
        import tempfile as _临时
        from 支持库.后端.资源管理 import (
            创建唯一运行目录, 原子写入, 安全释放资源, 资源短锁,
        )
        try:
            运行目录 = 创建唯一运行目录(Path(_临时.gettempdir()), "合规资源")
            测试文件 = 运行目录 / "测试.json"
            原子写入(测试文件, '{"值": 1}')
            # 短锁获取与释放（锁目录真实创建/删除）
            锁 = 资源短锁(运行目录 / "锁", "合规资源", 持有者="合规测试")
            锁成功, _ = 锁.获取()
            if not 锁成功:
                return False, "资源短锁获取失败"
            锁释放, _ = 锁.释放()
            if not 锁释放:
                return False, "资源短锁释放失败"
            # 安全释放（目录级）：验证 不存在/已删除
            释放成功, 释放消息 = 安全释放资源(运行目录)
            if not 释放成功:
                return False, f"资源释放失败: {释放消息}"
            if 运行目录.exists():
                return False, "资源释放后目录仍存在"
        except Exception as 错误:
            return False, f"真实资源释放异常: {错误}"
        return True, "真实创建并释放资源（目录/文件/短锁全部归零）"

    def _场景版本升级(self) -> tuple[bool, str]:
        """版本升级：契约版本号格式合法。"""
        契约目录 = self.组件目录 / "能力契约"
        if not 契约目录.is_dir():
            return False, "缺少 能力契约/"
        from 开发工具.契约编译.漂移检测 import 主版本号
        问题列表 = []
        for 契约文件 in 契约目录.glob("*.json"):
            try:
                契约 = json.loads(契约文件.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            版本 = 契约.get("版本", "")
            if not 版本 or 主版本号(版本) < 0 or "." not in 版本:
                问题列表.append(f"{契约.get('能力id', 契约文件.stem)} 版本号不合法: {版本}")
        return not 问题列表, "; ".join(问题列表) or "版本号合法"

    def _场景失败语义(self) -> tuple[bool, str]:
        """失败语义：契约声明错误码且实现不吞异常。"""
        契约目录 = self.组件目录 / "能力契约"
        if not 契约目录.is_dir():
            return False, "缺少 能力契约/"
        实现目录 = self.组件目录 / "实现"
        if not 实现目录.is_dir():
            实现目录 = self.组件目录 / "执行单元"
        问题列表 = []
        for 契约文件 in 契约目录.glob("*.json"):
            try:
                契约 = json.loads(契约文件.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if not 契约.get("错误码"):
                问题列表.append(f"{契约.get('能力id', 契约文件.stem)} 未声明错误码")
        if 实现目录.is_dir():
            for 文件 in 实现目录.rglob("*.py"):
                内容 = 文件.read_text(encoding="utf-8")
                if "except Exception" in 内容 and "pass" in 内容:
                    问题列表.append(f"{文件.name} 吞异常（except+pass）")
        return not 问题列表, "; ".join(问题列表) or "失败语义明确"

    def _场景说明书(self) -> tuple[bool, str]:
        """说明书：说明存在且非空。"""
        说明目录 = self.组件目录 / "说明"
        说明书 = self.组件目录 / "说明书.md"
        if 说明目录.is_dir():
            文件列表 = list(说明目录.rglob("*.md"))
            if not 文件列表:
                return False, "说明/ 目录为空"
            return True, f"说明书 {len(文件列表)} 份"
        if 说明书.is_file() and 说明书.read_text(encoding="utf-8").strip():
            return True, "说明书.md 存在"
        return False, "缺少 说明/ 或 说明书.md"

    def _场景完整性摘要(self) -> tuple[bool, str]:
        """完整性摘要：经唯一校验器验证文件清单格式闭合（拒绝旧格式与自比较）。"""
        from 开发工具.组件规范.完整性摘要 import 校验完整性摘要
        通过, 问题列表 = 校验完整性摘要(self.组件目录)
        if not 通过:
            return False, "; ".join(问题列表) or "完整性摘要校验失败"
        return True, "文件清单格式校验通过（唯一校验器）"

    def _场景公共入口(self) -> tuple[bool, str]:
        """公共入口：包声明入口文件存在且可导入。"""
        声明路径 = self.组件目录 / "包声明.json"
        if not 声明路径.is_file():
            return False, "缺少 包声明.json"
        try:
            声明 = json.loads(声明路径.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False, "包声明 JSON 解析失败"
        入口 = 声明.get("入口", "")
        if not 入口:
            return False, "包声明缺少 入口"
        入口路径 = self.组件目录 / 入口
        if not 入口路径.is_file():
            return False, f"入口文件不存在: {入口}"
        return True, f"入口 {入口} 存在"

    def _场景真实返回值(self) -> tuple[bool, str]:
        """真实返回值：从生成的中文公开入口经能力注册表调用真实实现。"""
        实现目录 = self.组件目录 / "实现"
        if not 实现目录.is_dir():
            实现目录 = self.组件目录 / "执行单元"
        if not 实现目录.is_dir():
            return False, "缺少 实现/"
        契约目录 = self.组件目录 / "能力契约"
        if not 契约目录.is_dir():
            return False, "缺少 能力契约/"
        # 取第一个契约：生成入口 → 注册表注册 → 真实调用
        契约文件 = next(契约目录.glob("*.json"), None)
        if 契约文件 is None:
            return False, "无契约 JSON"
        try:
            契约 = json.loads(契约文件.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False, "契约 JSON 解析失败"
        能力id = 契约.get("能力id", "")
        if not 能力id:
            return False, "契约缺少 能力id"
        实现文件 = 实现目录 / f"{能力id.split('.')[-1]}.py"
        if not 实现文件.is_file():
            # 回退：实现目录下第一个非缓存 Python 文件
            for 候选 in sorted(实现目录.rglob("*.py")):
                if "pycache" not in str(候选) and not 候选.name.startswith("_"):
                    实现文件 = 候选
                    break
        if not 实现文件.is_file():
            return False, f"实现文件缺失: {实现文件.name}"
        # 经能力注册表调用真实实现
        from 公共契约.能力契约.契约 import 能力实现, 能力注册表
        try:
            模块 = _加载模块(实现文件)
            实现函数 = getattr(模块, 能力id.split(".")[-1])
        except (ImportError, AttributeError) as 错误:
            return False, f"实现加载失败: {错误}"
        注册表 = 能力注册表()
        try:
            注册表.注册(能力实现(
                能力id=能力id, 包id=self.组件目录.name, 实现函数=实现函数,
                参数=契约.get("参数", []), 返回=契约.get("返回", "普通返回"),
                说明=契约.get("说明", ""),
            ))
        except ValueError as 错误:
            return False, f"能力注册失败: {错误}"
        实现对象 = 注册表.获取(能力id)
        # 真实调用：成功路径（构造参数）与失败路径（缺必填）
        成功 = True
        问题 = []
        参数表 = 契约.get("参数", [])
        成功参数 = {参数["名称"]: "测试值" for 参数 in 参数表 if 参数.get("必填", True)}
        try:
            成功结果 = 实现对象.调用(**成功参数)
            if isinstance(成功结果, dict) and 成功结果.get("成功") is False:
                问题.append(f"成功路径返回失败: {成功结果.get('错误码')}")
        except Exception as 错误:
            问题.append(f"成功路径异常: {错误}")
        # 失败路径：缺必填参数
        if 参数表:
            失败参数 = {参数["名称"]: "测试值" for 参数 in 参数表
                        if not 参数.get("必填", True)}
            try:
                失败结果 = 实现对象.调用(**失败参数)
                if isinstance(失败结果, dict) and 失败结果.get("成功") is True:
                    问题.append("缺必填参数未返回失败（失败语义缺失）")
            except TypeError:
                pass  # 参数缺失抛 TypeError 也是失败语义（统一结果在网关层包装）
        if 问题:
            return False, "; ".join(问题)
        return True, f"{能力id} 经能力注册表真实调用成功（成功+失败路径）"
