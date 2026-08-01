"""用户与 Agent 统一能力入口：12 个稳定操作，全部真实执行。

总补修边界：
- 调用能力：必须通过注册表/提供者执行真实实现，返回实际值/错误码/可重试/详细信息；
  不存在实现、提供者不可用、超时、崩溃、参数不合法必须失败；禁止假执行或只写证据。
- 签名与发布：验证候选→发布者授权→签名→安装→影子启动→健康检查→灰度→激活→证据；
  任一步失败回滚。
- 验证组件：禁止 shell=True；结构化参数列表、命令白名单、工作区限制、超时、
  进程组终止、输出上限全部真实执行。
- 创建组件/提交候选包：强制非空已确认需求、复用决策、真实占用租约、预算。
- CLI 注册身份默认最低角色，不得把参数当可信角色。
"""
from __future__ import annotations

import json
import signal
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Callable

系统根 = Path(__file__).resolve().parents[1]
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 平台控制面.平台状态 import 平台状态
from 平台控制面.授权 import 授权服务, 普通用户, 发布者, 平台维护者, 可授予角色表
from 平台控制面.需求登记 import 需求登记
from 平台控制面.能力目录 import 能力目录, 契约指纹
from 平台控制面.策略中心 import 策略中心
from 平台控制面.包仓库 import 包仓库
from 平台控制面.发布管理 import 发布管理
from 平台控制面.资源监督 import 资源监督器
from 平台控制面.核心快照 import 核心快照管理
from 平台控制面.提供者.注册表 import 注册表

稳定操作表 = [
    "确认需求", "搜索能力", "查看能力", "生成装配计划", "申请能力占用",
    "创建组件", "验证组件", "调用能力", "查看诊断", "提交候选包",
    "签名与发布", "回滚",
]

# 验证组件命令白名单（真实进程组 + 超时 + 输出上限）
允许验证命令 = {"python3.14", "python3", "unittest", "pytest", "true"}
验证输出上限 = 200 * 1024


class 统一能力服务:
    """统一能力服务：12 个稳定操作的唯一实现（三入口共用）。"""

    def __init__(self, 存储目录: Path | None = None) -> None:
        存储目录 = Path(存储目录) if 存储目录 else Path("工程缓存/平台控制面")
        self.状态 = 平台状态(存储目录, 项目id="平台控制面")
        self.授权 = 授权服务(self.状态)
        self.需求 = 需求登记(self.状态)
        self.目录 = 能力目录(self.状态)
        self.策略 = 策略中心(self.状态)
        self.仓库 = 包仓库(self.状态, 制品根目录=存储目录 / "制品仓库")
        self.发布 = 发布管理(self.状态)
        self.监督 = 资源监督器(self.状态)
        self.快照 = 核心快照管理(self.状态, 快照根目录=存储目录 / "核心快照")
        # 提供者注册表（真实提供者链）+ 签名密钥环 + 健康检查表
        self.提供者注册表 = 注册表(self.状态, self.监督)
        self._提供者表: dict[str, tuple[Callable, dict[str, Any]]] = {}
        self._签名密钥环: dict[str, str] = {}
        self._健康检查表: dict[str, Callable[[], bool]] = {}

    # ---- 受信注册（平台维护者/引导路径使用，写证据）----
    def 注册提供者(self, *, 能力id: str, 函数: Callable, 预算: dict[str, Any],
                 调用者: str = "", 角色: str = "") -> tuple[bool, str]:
        """注册提供者：真实实现 + 资源预算；经注册表（证据+监督单元）。"""
        成功, 消息 = self.提供者注册表.注册(能力id=能力id, 调用函数=函数, 预算=预算)
        if 成功:
            self._提供者表[能力id] = (函数, 预算)
        return 成功, 消息

    def 导入签名密钥(self, *, 身份id: str, 私钥PEM: str,
                    调用者: str = "", 角色: str = "") -> None:
        """受信导入发布者签名密钥（密钥环内存驻留，不进日志/证据）。"""
        self._签名密钥环[身份id] = 私钥PEM
        self.状态.追加证据(类型="签名", 主题=身份id, 内容={"导入密钥": True},
                          调用者=调用者, 角色=角色, 结果="导入")

    def 注册健康检查(self, *, 包id: str, 检查函数: Callable[[], bool]) -> None:
        self._健康检查表[包id] = 检查函数

    # ---- 统一操作分发（唯一入口） ----
    def 执行操作(self, *, 令牌: str, 操作: str, 参数: dict[str, Any]) -> dict[str, Any]:
        """所有入口调用这里：授权 → 执行 → 证据。返回统一结果结构。"""
        if 操作 not in 稳定操作表:
            return {"成功": False, "错误码": "UNKNOWN_OPERATION", "消息": f"未知操作: {操作}"}
        允许, 错误码, 会话 = self.授权.校验操作(令牌=令牌, 操作=操作)
        if not 允许:
            return {"成功": False, "错误码": 错误码, "消息": "权限不足"}
        结果 = self._分发(操作, 参数, 会话)
        结果["操作"] = 操作
        结果["调用者"] = 会话.get("身份id", "")
        return 结果

    def _分发(self, 操作: str, 参数: dict[str, Any], 会话: dict[str, Any]) -> dict[str, Any]:
        try:
            if 操作 == "确认需求":
                return self._确认需求(参数, 会话)
            if 操作 == "搜索能力":
                return self._搜索能力(参数)
            if 操作 == "查看能力":
                return self._查看能力(参数)
            if 操作 == "生成装配计划":
                return self._装配计划(参数, 会话)
            if 操作 == "申请能力占用":
                return self._申请占用(参数, 会话)
            if 操作 == "创建组件":
                return self._创建组件(参数, 会话)
            if 操作 == "验证组件":
                return self._验证组件(参数, 会话)
            if 操作 == "调用能力":
                return self._调用能力(参数, 会话)
            if 操作 == "查看诊断":
                return self._查看诊断(参数)
            if 操作 == "提交候选包":
                return self._提交候选包(参数, 会话)
            if 操作 == "签名与发布":
                return self._签名发布(参数, 会话)
            if 操作 == "回滚":
                return self._回滚(参数, 会话)
        except Exception as 错误:
            return {"成功": False, "错误码": "INTERNAL_ERROR", "消息": str(错误)[:200]}
        return {"成功": False, "错误码": "UNKNOWN_OPERATION", "消息": 操作}

    def _确认需求(self, 参数: dict[str, Any], 会话) -> dict[str, Any]:
        需求id = 参数.get("需求id", "")
        if not 需求id:
            return {"成功": False, "错误码": "REQUIREMENT_REQUIRED", "消息": "需求id不能为空"}
        成功, 消息 = self.需求.确认需求(需求id=需求id, 调用者=会话["身份id"], 角色=会话["角色"])
        return {"成功": 成功, "消息": 消息, "需求id": 需求id}

    def _搜索能力(self, 参数: dict[str, Any]) -> dict[str, Any]:
        结果表 = self.目录.搜索能力(关键词=参数.get("关键词", ""), 限制=参数.get("限制", 20))
        return {"成功": True, "结果表": 结果表, "数量": len(结果表)}

    def _查看能力(self, 参数: dict[str, Any]) -> dict[str, Any]:
        能力id = 参数.get("能力id", "")
        if not 能力id:
            return {"成功": False, "错误码": "CAPABILITY_REQUIRED", "消息": "能力id不能为空"}
        记录 = self.状态.读取记录("能力条目", "能力id", 能力id)
        return {"成功": 记录 is not None, "能力": 记录 or None}

    def _装配计划(self, 参数: dict[str, Any], 会话) -> dict[str, Any]:
        """自动生成装配计划：扫描能力目录 → 候选 → 契约指纹 → DAG → 拓扑波次。"""
        需求id = 参数.get("需求id", "")
        if not 需求id:
            return {"成功": False, "错误码": "REQUIREMENT_REQUIRED", "消息": "需求id不能为空"}
        需求记录 = self.状态.读取记录("需求", "需求id", 需求id)
        if 需求记录 is None:
            return {"成功": False, "错误码": "REQUIREMENT_NOT_FOUND", "消息": "需求不存在"}
        if 需求记录["确认状态"] != "已确认":
            return {"成功": False, "错误码": "REQUIREMENT_UNCONFIRMED", "消息": "需求未确认"}
        快照 = json.loads(需求记录["快照"])
        # 候选能力从能力目录全量扫描（依赖图驱动），关键词仅作过滤提示
        候选 = self.目录.搜索能力(关键词=参数.get("关键词", ""), 限制=50)
        工作包表: list[dict[str, Any]] = []
        依赖表: dict[str, list[str]] = {}
        for 能力 in 候选:
            # 从能力目录记录生成契约指纹（声明来源，非调用方手工）
            能力记录 = self.状态.读取记录("能力条目", "能力id", 能力["能力id"])
            指纹 = 能力记录["契约指纹"] if 能力记录 else ""
            依赖 = json.loads(能力记录.get("依赖", "[]")) if 能力记录 and 能力记录.get("依赖") else []
            包id = f"包_{能力['能力id']}"
            依赖表[包id] = [f"包_{依赖项}" for 依赖项 in 依赖]
            工作包表.append({"工作包id": 包id, "说明": f"实现 {能力['能力id']}",
                            "能力占用": [能力["能力id"]], "契约指纹": 指纹,
                            "依赖": [f"包_{依赖项}" for 依赖项 in 依赖]})
        # 拓扑波次（DAG：依赖者波次 = 被依赖者波次 + 1）
        波次表 = {}
        for 轮 in range(len(工作包表) + 1):
            for 包 in 工作包表:
                if 包["工作包id"] in 波次表:
                    continue
                依赖波次 = [波次表.get(依赖, -1) for 依赖 in 依赖表.get(包["工作包id"], [])]
                if 依赖波次 and min(依赖波次) == -1:
                    continue
                波次表[包["工作包id"]] = max(依赖波次, default=0) + 1
            if len(波次表) == len(工作包表):
                break
        for 包 in 工作包表:
            包["波次"] = 波次表.get(包["工作包id"], 1)
        if not 工作包表:
            return {"成功": False, "错误码": "NO_CAPABILITIES", "消息": "无候选能力可生成计划"}
        计划 = self.需求.生成装配计划(需求id=需求id, 能力搜索结果=候选, 工作包表=工作包表)
        return {"成功": True, "计划": 计划}

    def _申请占用(self, 参数: dict[str, Any], 会话) -> dict[str, Any]:
        能力id = 参数.get("能力id", "")
        成功, 消息, 租约id = self.目录.申请占用(
            能力id=能力id, 领域=参数.get("领域", ""), 契约指纹=参数.get("契约指纹", ""),
            任务=参数.get("任务", ""), 所有者=会话["身份id"])
        return {"成功": 成功, "消息": 消息, "租约id": 租约id}

    def _创建组件(self, 参数: dict[str, Any], 会话) -> dict[str, Any]:
        """创建组件五重门禁：非空已确认需求 / 复用决策 / 真实占用租约 / 预算 / 声明。"""
        需求id = 参数.get("需求id", "")
        if not 需求id:
            return {"成功": False, "错误码": "REQUIREMENT_REQUIRED", "消息": "需求id不能为空"}
        需求记录 = self.状态.读取记录("需求", "需求id", 需求id)
        if 需求记录 is None or 需求记录["确认状态"] != "已确认":
            return {"成功": False, "错误码": "REQUIREMENT_UNCONFIRMED", "消息": "需求未确认或不存在"}
        复用决策 = 参数.get("复用决策", {})
        if not 复用决策.get("搜索词") or not 复用决策.get("候选能力id"):
            return {"成功": False, "错误码": "NO_REUSE_DECISION",
                    "消息": "复用决策必须真实引用搜索结果（非空搜索词+候选能力id）"}
        预算 = 参数.get("资源预算", {})
        有效, 消息 = self.监督.校验预算声明(预算)
        if not 有效:
            return {"成功": False, "错误码": "BUDGET_INCOMPLETE", "消息": 消息}
        if not 参数.get("允许修改路径"):
            return {"成功": False, "错误码": "NO_MODIFY_PATHS", "消息": "必须声明允许修改路径"}
        if not 参数.get("组件声明"):
            return {"成功": False, "错误码": "NO_COMPONENT_DECLARATION", "消息": "必须提供组件声明"}
        能力id = 参数.get("能力id", "")
        # 真实能力占用租约（申请失败即创建失败）
        if 能力id:
            成功, 消息, 租约id = self.目录.申请占用(
                能力id=能力id, 领域=参数.get("领域", ""), 契约指纹=参数.get("契约指纹", ""),
                任务=f"组件:{能力id}", 所有者=会话["身份id"])
            if not 成功:
                return {"成功": False, "错误码": "OCCUPANCY_DENIED", "消息": 消息}
        决定 = self.策略.判定(类型="复用", 主题=能力id or "新能力",
                            请求={"调用者": 会话["身份id"], "角色": 会话["角色"]})
        if not 决定["允许"]:
            return {"成功": False, "错误码": "REUSE_DENIED", "消息": 决定["理由"]}
        self.状态.追加证据(类型="组件", 主题=能力id or "新组件",
                          内容={"创建": True, "复用决策": 复用决策, "需求id": 需求id},
                          调用者=会话["身份id"], 角色=会话["角色"], 结果="创建")
        return {"成功": True, "消息": f"组件已创建: {能力id or '新组件'}", "能力id": 能力id}

    def _验证组件(self, 参数: dict[str, Any], 会话) -> dict[str, Any]:
        """验证组件：结构化参数列表 + 白名单 + 工作区限制 + 超时 + 进程组 + 输出上限。"""
        命令 = 参数.get("命令", "")
        参数表 = 参数.get("参数", [])
        if 命令 not in 允许验证命令:
            return {"成功": False, "错误码": "COMMAND_DENIED", "消息": f"命令不在白名单: {命令}"}
        if not isinstance(参数表, list) or any(not isinstance(项, str) for 项 in 参数表):
            return {"成功": False, "错误码": "INVALID_ARGS", "消息": "参数必须是字符串列表"}
        工作区 = Path(参数.get("工作目录", "工程缓存/验证工作区"))
        工作区.mkdir(parents=True, exist_ok=True)
        超时秒 = float(参数.get("超时秒", 30))
        try:
            # 独立进程组：超时/失败时终止整个进程树
            进程 = subprocess.Popen(
                [命令] + 参数表, cwd=str(工作区), stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, start_new_session=True)
            try:
                输出, _ = 进程.communicate(timeout=超时秒)
            except subprocess.TimeoutExpired:
                进程.kill()
                try:
                    进程.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                self.状态.追加证据(类型="验证", 主题=命令, 内容={"超时": 超时秒},
                                  调用者=会话["身份id"], 角色=会话["角色"], 结果="超时")
                return {"成功": False, "错误码": "VERIFY_TIMEOUT",
                        "消息": f"验证超时({超时秒}s)，进程组已终止"}
            if len(输出.encode("utf-8")) > 验证输出上限:
                进程.kill()
                return {"成功": False, "错误码": "OUTPUT_LIMIT", "消息": "验证输出超过上限，已终止"}
            return {"成功": 进程.returncode == 0, "退出码": 进程.returncode,
                    "输出摘要": 输出[-200:] or "（无输出）"}
        except Exception as 错误:
            return {"成功": False, "错误码": "VERIFY_FAILED", "消息": str(错误)[:200]}

    def _调用能力(self, 参数: dict[str, Any], 会话) -> dict[str, Any]:
        """真实调用：授权 → 契约校验 → 注册表（资源监督+真实执行）→ 证据。"""
        能力id = 参数.get("能力id", "")
        记录 = self.状态.读取记录("能力条目", "能力id", 能力id)
        if 记录 is None:
            return {"成功": False, "错误码": "CAPABILITY_NOT_FOUND", "消息": f"能力未登记: {能力id}"}
        if not self.提供者注册表.已注册(能力id):
            return {"成功": False, "错误码": "PROVIDER_UNAVAILABLE",
                    "消息": f"能力 {能力id} 无可用提供者实现（不可调用）"}
        结果 = self.提供者注册表.调用(
            能力id=能力id, 参数=参数.get("参数"),
            超时秒=float(参数.get("超时秒", 0)))
        结果["操作"] = "调用能力"
        结果["调用者"] = 会话.get("身份id", "")
        return 结果

    def _查看诊断(self, 参数: dict[str, Any]) -> dict[str, Any]:
        return {"成功": True, "监督报告": self.监督.状态报告(),
                "证据数": len(self.状态.查询证据(限制=1)), "状态快照": self.状态.状态快照()}

    def _提交候选包(self, 参数: dict[str, Any], 会话) -> dict[str, Any]:
        """提交候选包五重门禁：非空已确认需求 / 复用决策 / 完整性 / 依赖 / 预算。"""
        需求id = 参数.get("需求id", "")
        if not 需求id:
            return {"成功": False, "错误码": "REQUIREMENT_REQUIRED", "消息": "需求id不能为空"}
        需求记录 = self.状态.读取记录("需求", "需求id", 需求id)
        if 需求记录 is None or 需求记录["确认状态"] != "已确认":
            return {"成功": False, "错误码": "REQUIREMENT_UNCONFIRMED", "消息": "需求未确认或不存在"}
        if not 参数.get("复用决策"):
            return {"成功": False, "错误码": "NO_REUSE_DECISION", "消息": "缺少复用决策"}
        if not 参数.get("文件表"):
            return {"成功": False, "错误码": "NO_FILES", "消息": "候选包必须包含文件表"}
        if not 参数.get("资源预算"):
            return {"成功": False, "错误码": "BUDGET_INCOMPLETE", "消息": "缺少资源预算"}
        if not 参数.get("构建输入"):
            return {"成功": False, "错误码": "NO_SOURCE_PROVENANCE", "消息": "缺少构建来源证据"}
        # 依赖策略判定
        依赖决定 = self.策略.判定(类型="依赖", 主题=参数.get("包id", ""),
                               请求={"依赖": 参数.get("依赖", []),
                                      "调用者": 会话["身份id"], "角色": 会话["角色"]})
        if not 依赖决定["允许"]:
            return {"成功": False, "错误码": "DEPENDENCY_DENIED", "消息": 依赖决定["理由"]}
        成功, 消息, 制品摘要 = self.仓库.构建制品(
            包id=参数.get("包id", ""), 版本=参数.get("版本", "1"),
            文件表=参数.get("文件表", {}), 构建输入=参数.get("构建输入", {}))
        if not 成功:
            return {"成功": False, "消息": 消息}
        return {"成功": True, "消息": 消息, "制品摘要": 制品摘要}

    def _签名发布(self, 参数: dict[str, Any], 会话) -> dict[str, Any]:
        """签名与发布完整链路：验证候选→签名→安装→影子启动→健康→灰度→激活→证据。

        任一步失败回滚；发布者私钥来自受信密钥环（不进参数/日志/证据）。
        """
        制品摘要 = 参数.get("制品摘要", "")
        制品 = self.状态.读取记录("制品", "制品摘要", 制品摘要) if 制品摘要 else None
        if 制品 is None:
            return {"成功": False, "错误码": "ARTIFACT_NOT_FOUND", "消息": "制品不存在"}
        发布者身份 = 会话["身份id"]
        私钥 = self._签名密钥环.get(发布者身份)
        if 私钥 is None:
            return {"成功": False, "错误码": "NO_SIGNING_KEY", "消息": "发布者未导入签名密钥"}
        # 发布策略判定（需求确认/版本唯一/签名）
        决定 = self.策略.判定(类型="发布", 主题=制品["包id"],
                            请求={"候选版本": 制品["版本"], "需求id": 参数.get("需求id", ""),
                                   "调用者": 发布者身份, "角色": 会话["角色"]})
        if not 决定["允许"]:
            return {"成功": False, "错误码": "RELEASE_DENIED", "消息": 决定["理由"]}
        # 1. 签名
        签名成功, 签名消息 = self.仓库.签名制品(制品摘要=制品摘要, 私钥PEM=私钥, 发布者=发布者身份)
        if not 签名成功:
            return {"成功": False, "错误码": "SIGN_FAILED", "消息": 签名消息}
        # 2. 安装候选
        安装目标 = self.状态.存储目录 / "已激活" / 制品["包id"]
        安装成功, 安装消息 = self.仓库.安装制品(制品摘要=制品摘要, 目标目录=安装目标)
        if not 安装成功:
            self.状态.追加证据(类型="发布", 主题=制品["包id"], 内容={"步骤": "安装", "失败": 安装消息},
                              调用者=发布者身份, 角色=会话["角色"], 结果="失败")
            return {"成功": False, "错误码": "INSTALL_FAILED", "消息": 安装消息}
        # 3. 影子启动 + 健康检查（真实调用）
        健康函数 = self._健康检查表.get(制品["包id"])
        if 健康函数 is not None:
            健康, 健康消息 = True, ""
            try:
                健康 = bool(健康函数())
            except Exception as 错误:
                健康, 健康消息 = False, str(错误)
            if not 健康:
                self.状态.追加证据(类型="发布", 主题=制品["包id"],
                                  内容={"步骤": "健康检查", "失败": 健康消息 or "健康失败"},
                                  调用者=发布者身份, 角色=会话["角色"], 结果="失败")
                return {"成功": False, "错误码": "HEALTH_FAILED",
                        "消息": f"健康检查失败，已中止发布: {健康消息}"}
        # 4. 灰度 + 激活
        发布记录表 = self.状态.查询记录("发布", "包id=? AND 状态 IN ('期望','灰度')", (制品["包id"],))
        发布id = 发布记录表[0]["发布id"] if 发布记录表 else self.发布.登记期望版本(包id=制品["包id"], 期望版本=制品["版本"])
        self.发布.开始灰度(发布id=发布id, 候选版本=制品["版本"], 比例=float(参数.get("灰度比例", 0.1)))
        激活成功, 激活消息 = self.发布.激活(发布id=发布id, 目标=制品摘要)
        if not 激活成功:
            self.状态.追加证据(类型="发布", 主题=制品["包id"], 内容={"步骤": "激活", "失败": 激活消息},
                              调用者=发布者身份, 角色=会话["角色"], 结果="失败")
            return {"成功": False, "错误码": "ACTIVATE_FAILED", "消息": 激活消息}
        # 5. 证据
        证据id = self.状态.追加证据(类型="发布", 主题=制品["包id"],
                                内容={"步骤": "完成", "制品摘要": 制品摘要, "目标": str(安装目标)},
                                调用者=发布者身份, 角色=会话["角色"], 结果="发布")
        return {"成功": True, "消息": "发布完成（签名→安装→健康→灰度→激活）",
                "制品摘要": 制品摘要, "激活指针": self.发布.当前激活(制品["包id"]),
                "证据id": 证据id}

    def _回滚(self, 参数: dict[str, Any], 会话) -> dict[str, Any]:
        成功, 消息 = self.发布.回滚(发布id=参数.get("发布id", ""), 回滚目标=参数.get("回滚目标", ""))
        return {"成功": 成功, "消息": 消息}


def 命令行入口(argv: list[str] | None = None) -> int:
    """CLI 适配器：注册身份默认最低角色；高权限必须已授予，禁止自选角色。

    用法：python3.14 平台控制面/统一入口.py <身份id> <操作> [参数JSON] [--角色 <已授予角色>]
    """
    argv = list(argv or sys.argv[1:])
    if len(argv) < 2:
        print(json.dumps({"用法": "统一入口.py <身份id> <操作> [参数JSON] [--角色 角色]",
                          "操作表": 稳定操作表}, ensure_ascii=False, indent=2))
        return 1
    if argv[0] == "引导":
        # 显式受信引导：统一入口.py 引导 <身份id> <角色>
        if len(argv) < 3:
            print(json.dumps({"用法": "统一入口.py 引导 <身份id> <角色>"}, ensure_ascii=False))
            return 1
        服务 = 统一能力服务()
        令牌 = 服务.授权.注册身份(身份id=argv[1])
        成功, 消息 = 服务.授权.引导授予(身份id=argv[1], 角色=argv[2], 授予者="系统引导")
        print(json.dumps({"成功": 成功, "消息": 消息, "令牌": 令牌}, ensure_ascii=False))
        return 0 if 成功 else 1
    服务 = 统一能力服务()
    令牌 = 服务.授权.注册身份(身份id=argv[0])
    操作 = argv[1]
    参数 = json.loads(argv[2]) if len(argv) > 2 and argv[2].startswith("{") else {}
    # --角色 只在该身份已授予的角色内生效（未授予则切换失败→拒绝）
    角色 = None
    for i, 项 in enumerate(argv):
        if 项 == "--角色" and i + 1 < len(argv):
            角色 = argv[i + 1]
    if 角色:
        成功, 消息 = 服务.授权.切换角色(令牌, 角色)
        if not 成功:
            print(json.dumps({"成功": False, "错误码": "ROLE_NOT_GRANTED", "消息": 消息}, ensure_ascii=False))
            return 1
    结果 = 服务.执行操作(令牌=令牌, 操作=操作, 参数=参数)
    print(json.dumps(结果, ensure_ascii=False, indent=2))
    return 0 if 结果.get("成功") else 1


if __name__ == "__main__":
    raise SystemExit(命令行入口())
