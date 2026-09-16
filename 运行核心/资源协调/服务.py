"""运行核心资源协调：跨进程权威状态 + CAS 提交闭环 + 快照一致性。

修改流程：读取基础版本和摘要 → 私有工作副本 → 无锁修改与验证 →
提交前比较版本 → 资源级短锁 → CAS（sqlite 事务）→ fsync → 原子替换
→ 新快照（唯一临时目录 + fsync + 原子改名，只读不可覆盖）→ 事务证据
→ 释放。
并发冲突返回 版本冲突；旧读取者读旧快照；引用归零才清理旧快照；
崩溃清理仅回收 心跳过期 + 项目/所有者匹配 的死亡进程资源。
运行核心只经支持库包级中文公开入口调用，禁止导入 实现/ 目录。
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

# 支持库包级中文公开入口（禁止深入 实现/ 目录）
from 支持库.后端.系统核心支持库.资源管理 import (
    创建唯一运行目录, 原子写入,
)
from 运行核心.权威状态 import 权威状态
from 运行核心.资源id编码 import 校验资源id, 安全资源id
from 公共契约.句柄体系 import 生成句柄id
from 运行核心.进程身份 import 进程身份


class 事务证据:
    """一次修改事务的完整证据（含 旧摘要/新摘要/所有者/提交结果）。"""

    def __init__(self, *, 事务id: str, 资源id: str, 资源版本: str,
                 旧摘要: str, 新摘要: str, 所有者: str, 提交结果: str) -> None:
        self.事务id = 事务id
        self.资源id = 资源id
        self.资源版本 = 资源版本
        self.旧摘要 = 旧摘要
        self.新摘要 = 新摘要
        self.所有者 = 所有者
        self.提交结果 = 提交结果
        self.提交时间 = time.strftime("%Y-%m-%d %H:%M:%S")

    def 转字典(self) -> dict[str, Any]:
        return {
            "事务id": self.事务id, "资源id": self.资源id, "资源版本": self.资源版本,
            "旧摘要": self.旧摘要, "新摘要": self.新摘要, "所有者": self.所有者,
            "提交结果": self.提交结果, "提交时间": self.提交时间,
        }


class 资源协调器:
    """资源协调器：权威状态（sqlite）+ 快照 + CAS 提交。"""

    def __init__(self, 存储目录: Path, *, 项目id: str = "", 所有者: str = "") -> None:
        self.存储目录 = Path(存储目录)
        self.存储目录.mkdir(parents=True, exist_ok=True)
        self.快照目录 = self.存储目录 / "快照"
        self.快照目录.mkdir(parents=True, exist_ok=True)
        self.工作目录 = self.存储目录 / "工作"
        self.工作目录.mkdir(parents=True, exist_ok=True)
        self.状态 = 权威状态(self.存储目录 / "状态", 项目id=项目id, 所有者=所有者)
        self.事务证据表: dict[str, dict[str, Any]] = {}

    def _资源id(self, 资源id: str) -> str:
        """资源 id 安全编码：拒绝逃逸 + 摘要映射。"""
        合法, 消息 = 校验资源id(资源id)
        if not 合法:
            raise ValueError(f"资源 id 非法: {消息}")
        return 安全资源id(资源id)

    def 初始化资源(self, 资源id: str, 初始值: Any = None) -> None:
        """初始化资源（多进程安全：INSERT OR IGNORE 幂等）。"""
        self.状态.初始化资源(self._资源id(资源id), 初始值)

    def 读取基础版本(self, 资源id: str) -> tuple[dict[str, Any], str, str]:
        """读取基础版本、摘要和栅栏令牌（权威状态）。"""
        资源id = self._资源id(资源id)
        数据 = self.状态.读取资源(资源id)
        if 数据 is None:
            raise FileNotFoundError(f"资源不存在: {资源id}")
        return 数据, str(数据["版本"]), str(数据.get("栅栏令牌", "0"))

    def 打开读取句柄(self, 资源id: str, *, 项目id: str = "", 所有者: str = "") -> tuple[dict[str, Any], str]:
        """打开读取句柄：锁定当前快照版本（旧读取者读旧快照）。"""
        资源id = self._资源id(资源id)
        数据, 版本, _令牌 = self.读取基础版本(资源id)
        句柄id = 生成句柄id()
        self.状态.保存句柄(
            句柄id=句柄id, 句柄类型="读取句柄", 资源id=资源id,
            项目id=项目id, 所有者=所有者, 状态="有效", 版本=版本,
            进程身份键=self.状态.身份.身份键())
        try:
            self._发布快照(资源id, 版本, 数据.get("值"))
            # 引用计数 +1（引用归零才清理旧快照）
            self.状态.增加引用(包id=资源id, 版本=版本)
        except Exception:
            # 句柄已落账但后续快照/引用失败时必须回滚句柄，不能留下
            # 永久有效句柄和悬挂引用。
            self.状态.失效句柄(句柄id, "读取句柄打开失败")
            raise
        return {"句柄id": 句柄id, "版本": 版本, "值": 数据.get("值")}, 句柄id

    def 关闭读取句柄(self, *, 句柄id: str, 资源id: str, 版本: str,
                    项目id: str = "", 所有者: str = "") -> None:
        """关闭读取句柄：失效句柄 + 引用归零（幂等）。"""
        资源id = self._资源id(资源id)
        句柄 = self.状态.读取句柄(句柄id)
        if 句柄 is None:
            raise KeyError("句柄不存在")
        if 句柄["句柄类型"] != "读取句柄" or 句柄["资源id"] != 资源id or str(句柄["版本"]) != str(版本):
            raise PermissionError("句柄与资源/版本不匹配")
        if 句柄["项目id"] and 句柄["项目id"] != 项目id:
            raise PermissionError("句柄所属项目不匹配")
        if 句柄["所有者"] and 句柄["所有者"] != 所有者:
            raise PermissionError("句柄所属所有者不匹配")
        if 句柄["状态"] == "已失效":
            return
        if not self.状态.失效句柄(句柄id, "读取完成"):
            return
        self.状态.减少引用(包id=资源id, 版本=版本)

    def _发布快照(self, 资源id: str, 版本: str, 值: Any) -> None:
        """发布快照：唯一临时目录写入 + fsync + 同目录 os.rename 原子改名；已发布只读不可覆盖。

        为什么改用 os.rename 而不是 shutil.move（现场取证结论）：
        - 临时目录由 创建唯一运行目录（`tempfile.mkdtemp(dir=快照目录)`）建在 **快照目录之下**，
          与目标「资源id@版本」是**同一个父目录** → 恒定同一文件系统，os.rename 必然是原子
          改名，不存在「跨文件系统退化为复制+删除」的可能（跨设备复制只发生在源/目标不同
          设备时，而同父目录已排除该可能）。
        - shutil.move 在目标已存在时会把源**移进**目标目录：并发竞争窗口里会把临时目录
          塞进已发布快照、污染只读快照；os.rename 对非空目标目录直接报错，正好落进
          「丢弃临时」分支。
        落盘顺序：值.json 写入（原子写入 内部已 fsync 文件与父目录=临时目录，值.json 的
        目录项已落盘）→ os.rename → fsync 快照目录（让「资源id@版本」这个新目录项落盘）。
        真正缺的只有改名后的父目录 fsync；它失败必须显式报错，不允许静默降级成假承诺。
        """
        快照 = self.快照目录 / f"{资源id}@{版本}"
        if 快照.exists():
            return  # 已发布快照只读不可覆盖
        临时 = 创建唯一运行目录(self.快照目录, f"快照_{资源id}")
        try:
            值文件 = 临时 / "值.json"
            原子写入(值文件, json.dumps({"值": 值, "版本": 版本}, ensure_ascii=False))
            try:
                os.rename(临时, 快照)
            except OSError:
                if 快照.exists():
                    # 并发下另一进程已发布 → 丢弃临时（只读快照不可覆盖）
                    shutil.rmtree(临时, ignore_errors=True)
                    return
                raise
            # 原子改名后同步父目录：确保「资源id@版本」目录项落盘
            self._同步目录(self.快照目录)
        except Exception:
            shutil.rmtree(临时, ignore_errors=True)
            raise

    @staticmethod
    def _同步目录(目录: Path) -> None:
        """fsync 目录元数据（保证改名结果落盘）；失败显式报错，不静默降级。"""
        try:
            目录fd = os.open(str(目录), os.O_RDONLY)
        except OSError as 错误:
            raise RuntimeError(f"目录 fsync 失败（无法打开目录 {目录}）: {错误}") from 错误
        try:
            os.fsync(目录fd)
        except OSError as 错误:
            raise RuntimeError(f"目录 fsync 失败（{目录}）: {错误}") from 错误
        finally:
            os.close(目录fd)

    def 读取快照值(self, 资源id: str, 版本: str) -> Any:
        """读取句柄按版本读取快照（旧句柄读旧值）。"""
        资源id = self._资源id(资源id)
        快照 = self.快照目录 / f"{资源id}@{版本}"
        if not 快照.is_dir():
            raise FileNotFoundError(f"快照不存在: {资源id}@{版本}")
        数据 = json.loads((快照 / "值.json").read_text(encoding="utf-8"))
        return 数据.get("值")

    def 创建修改事务(self, 资源id: str, *, 项目id: str = "", 所有者: str = "") -> tuple[str, str, str, str]:
        """创建修改事务句柄 + 私有工作副本；返回 (事务id, 句柄id, 基础版本, 基础令牌)。"""
        资源id = self._资源id(资源id)
        数据, 版本, 令牌 = self.读取基础版本(资源id)
        事务id = uuid.uuid4().hex[:16]
        句柄id = 生成句柄id()
        self.状态.保存句柄(
            句柄id=句柄id, 句柄类型="修改事务句柄", 资源id=资源id,
            项目id=项目id, 所有者=所有者, 状态="有效", 版本=版本,
            进程身份键=self.状态.身份.身份键())
        self.状态.创建事务(事务id=事务id, 资源id=资源id, 句柄id=句柄id,
                          基础版本=版本, 基础令牌=令牌,
                          进程身份键=self.状态.身份.身份键())
        # 私有工作副本（无锁修改）
        工作文件 = self.工作目录 / f"{事务id}.json"
        原子写入(工作文件, json.dumps({"值": 数据.get("值"), "基础版本": 版本, "基础令牌": 令牌}, ensure_ascii=False))
        return 事务id, 句柄id, 版本, 令牌

    def 修改工作副本(self, 事务id: str, 新值: Any) -> None:
        工作文件 = self.工作目录 / f"{事务id}.json"
        if not 工作文件.is_file():
            raise KeyError(f"未知事务: {事务id}")
        数据 = json.loads(工作文件.read_text(encoding="utf-8"))
        数据["值"] = 新值
        原子写入(工作文件, json.dumps(数据, ensure_ascii=False))

    def 提交(self, *, 事务id: str, 句柄id: str, 资源id: str,
             项目id: str = "", 所有者: str = "", 锁超时秒: float = 3.0) -> tuple[bool, str, str]:
        """提交闭环（跨进程安全）：版本比较 → 短锁 → CAS → 原子替换 → 快照 → 证据 → 释放。

        返回 (成功, 消息, 新版本)；并发冲突返回 版本冲突。
        """
        资源id = self._资源id(资源id)
        工作文件 = self.工作目录 / f"{事务id}.json"
        if not 工作文件.is_file():
            return False, f"未知事务: {事务id}", ""
        # 1. 句柄校验（权限与所有者）
        句柄 = self.状态.读取句柄(句柄id)
        if 句柄 is None or 句柄["状态"] != "有效":
            return False, f"句柄已失效（{句柄['失效原因'] if 句柄 else '不存在'}），不能自动复活", ""
        if 句柄["项目id"] and 句柄["项目id"] != 项目id:
            return False, f"跨项目复用被拒绝: 句柄属 {句柄['项目id']}，请求 {项目id}", ""
        if 句柄["所有者"] and 句柄["所有者"] != 所有者:
            return False, f"跨所有者复用被拒绝: 句柄属 {句柄['所有者']}，请求 {所有者}", ""
        # 2. 提交前比较版本
        当前数据, 当前版本, 当前令牌 = self.读取基础版本(资源id)
        工作数据 = json.loads(工作文件.read_text(encoding="utf-8"))
        基础版本 = str(工作数据.get("基础版本", ""))
        基础令牌 = str(工作数据.get("基础令牌", "0"))
        if 当前版本 != 基础版本:
            self.状态.失效句柄(句柄id, "版本冲突")
            self.状态.完成事务(事务id=事务id, 成功=False)
            return False, f"版本冲突: 基础版本 {基础版本}，当前 {当前版本}（他人已提交，禁止覆盖）", ""
        # 3. 资源级短锁（跨进程）：授权时原子签发新栅栏令牌
        锁成功, 锁消息, 锁令牌 = self.状态.获取锁(
            资源id, 事务id=事务id, 进程身份键=self.状态.身份.身份键(),
            项目id=项目id, 所有者=所有者, 超时秒=锁超时秒)
        if not 锁成功:
            self.状态.失效句柄(句柄id, "锁获取失败")
            self.状态.完成事务(事务id=事务id, 成功=False)
            return False, 锁消息, ""
        try:
            # 4. 锁内再次比较（跨进程 CAS 防线）→ sqlite 事务内原子条件提交
            新值 = 工作数据.get("值")
            新版本 = str(int(当前版本) + 1)
            新数据 = {"值": 新值}
            # 先计算新摘要（基于 资源id+新版本+新值，无自引用）
            import hashlib
            新摘要 = hashlib.sha256(
                json.dumps({"资源id": 资源id, "版本": 新版本, "值": 新值},
                           ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
            成功, 消息 = self.状态.提交资源(
                资源id=资源id, 期望版本=基础版本, 期望令牌=str(锁令牌),
                事务id=事务id, 进程身份键=self.状态.身份.身份键(),
                项目id=项目id, 所有者=所有者, 新值=新值, 新摘要=新摘要)
            if not 成功:
                self.状态.失效句柄(句柄id, "版本冲突")
                self.状态.完成事务(事务id=事务id, 成功=False)
                return False, f"版本冲突: {消息}", ""
            # 5. 新快照（原子发布，只读不可覆盖）
            self._发布快照(资源id, 新版本, 新值)
            # 6. 事务证据（真实旧摘要：提交前读取的基础摘要）
            旧摘要 = 当前数据.get("摘要") or "（初始未记录）"
            证据 = 事务证据(
                事务id=事务id, 资源id=资源id, 资源版本=新版本,
                旧摘要=旧摘要, 新摘要=新摘要, 所有者=所有者 or 句柄["所有者"],
                提交结果="成功",
            )
            self.事务证据表[事务id] = 证据.转字典()
            self.状态.完成事务(事务id=事务id, 成功=True, 新版本=新版本)
            return True, "提交成功", 新版本
        finally:
            # 7. 释放锁（结构化所有权校验）+ 失效事务句柄 + 清理工作副本（幂等）
            self.状态.释放锁(资源id, 事务id=事务id,
                            进程身份键=self.状态.身份.身份键(), 令牌=锁令牌)
            self.状态.失效句柄(句柄id, "事务完成")
            self.工作目录.joinpath(f"{事务id}.json").unlink(missing_ok=True)

    def 查询证据(self, 事务id: str) -> dict[str, Any] | None:
        return self.事务证据表.get(事务id)

    def 恢复未完成事务(self) -> list[str]:
        """重启后恢复未完成事务。

        资源 CAS 提交与快照发布之间存在进程崩溃窗口：若权威版本已经
        前进，事务不能再被标记为失败，必须先重建对应快照再完成事务；
        只有权威版本仍停留在基础版本时才执行回滚。
        """
        恢复列表 = []
        for 事务 in self.状态.进行中事务():
            事务id = 事务["事务id"]
            当前 = self.状态.读取资源(事务["资源id"])
            基础版本 = str(事务.get("基础版本", ""))
            工作数据路径 = self.工作目录 / f"{事务id}.json"
            if 当前 is not None and str(当前.get("版本", "")) != 基础版本:
                新版本 = str(当前["版本"])
                self._发布快照(事务["资源id"], 新版本, 当前.get("值"))
                self.状态.完成事务(事务id=事务id, 成功=True, 新版本=新版本)
                self.状态.失效句柄(事务["句柄id"], "崩溃后快照恢复")
                工作数据路径.unlink(missing_ok=True)
                恢复列表.append(f"{事务id}:已提交快照恢复")
                continue
            self.状态.完成事务(事务id=事务id, 成功=False)
            self.状态.失效句柄(事务["句柄id"], "事务未完成回滚")
            工作数据路径.unlink(missing_ok=True)
            恢复列表.append(f"{事务id}:未提交回滚")
        return 恢复列表

    def 清理死亡进程资源(self) -> list[str]:
        """精准回收：仅清理 心跳过期 + 项目/所有者匹配 的死亡进程锁与租约。"""
        return self.状态.清理死亡进程资源(
            项目id=self.状态.项目id, 所有者=self.状态.身份.所有者)

    def 清理过期快照(self) -> list[str]:
        """引用归零后清理旧快照（引用计数为 0 的版本快照）。"""
        清理列表 = []
        for 快照目录 in self.快照目录.iterdir():
            if not 快照目录.is_dir():
                continue
            名称 = 快照目录.name
            if "@" not in 名称:
                continue
            资源id, 版本 = 名称.rsplit("@", 1)
            if self.状态.引用数(包id=资源id, 版本=版本) == 0:
                # 仅清理非当前版本（当前版本保留）
                当前 = self.状态.读取资源(资源id)
                if 当前 and str(当前["版本"]) == 版本:
                    continue
                try:
                    shutil.rmtree(快照目录)
                except OSError as 错误:
                    raise RuntimeError(f"快照清理失败: {名称}: {错误}") from 错误
                if 快照目录.exists():
                    raise RuntimeError(f"快照清理后仍残留: {名称}")
                清理列表.append(名称)
        return 清理列表

    def 恢复缺失快照(self) -> list[str]:
        """崩溃恢复闭环：权威状态已提交但新快照未发布（提交后崩溃窗口）。

        根据权威状态重建缺失快照；幂等（已存在跳过）；恢复中再次崩溃可继续。
        """
        恢复列表 = []
        失败列表 = []
        for 资源 in self.状态.全部资源版本():
            资源id = 资源["资源id"]
            版本 = str(资源["版本"])
            快照 = self.快照目录 / f"{资源id}@{版本}"
            if not 快照.is_dir():
                try:
                    self._发布快照(资源id, 版本, 资源["值"])
                    恢复列表.append(f"{资源id}@{版本}")
                except Exception as 错误:
                    失败列表.append(f"{资源id}@{版本}: {错误}")
        if 失败列表:
            raise RuntimeError("快照恢复失败: " + "；".join(失败列表))
        return 恢复列表

    def 清理崩溃残留(self) -> list[str]:
        """崩溃清理 = 恢复未完成事务 + 清理死亡进程资源 + 恢复缺失快照。"""
        return (self.恢复未完成事务() + self.清理死亡进程资源()
                + self.恢复缺失快照())

    def 状态快照(self) -> dict[str, Any]:
        return {
            "权威状态": self.状态.状态快照(),
            "事务证据数": len(self.事务证据表),
            "身份": self.状态.身份.身份键(),
        }
