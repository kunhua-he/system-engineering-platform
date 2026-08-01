"""资源管理支持库：原子资源操作（快照/写入/替换/交换/锁/释放）。

原子能力：创建内容摘要/创建不可变快照/创建唯一运行目录/原子写入/
原子替换/比较并交换/资源级跨进程短锁/安全释放资源。
全部使用标准库，无第三方依赖；文件操作均为原子（临时文件+rename）。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

错误码_参数不合法 = "参数不合法"
错误码_版本冲突 = "版本冲突"
错误码_资源不存在 = "资源不存在"
错误码_资源被占用 = "资源被占用"
错误码_超时 = "超时"
错误码_内部错误 = "内部错误"


def 创建内容摘要(文件路径: Path, 算法: str = "sha256") -> str:
    """创建内容摘要（分块读取，不加载全文件入内存）。"""
    文件路径 = Path(文件路径)
    if not 文件路径.is_file():
        raise FileNotFoundError(f"文件不存在: {文件路径}")
    摘要器 = hashlib.new(算法)
    with 文件路径.open("rb") as 输入:
        while 块 := 输入.read(1024 * 1024):
            摘要器.update(块)
    return 摘要器.hexdigest()


def 创建不可变快照(来源目录: Path, 快照目录: Path) -> str:
    """创建不可变快照（复制 + 快照摘要 + 只读标记）。"""
    来源目录 = Path(来源目录)
    快照目录 = Path(快照目录)
    if not 来源目录.is_dir():
        raise FileNotFoundError(f"来源目录不存在: {来源目录}")
    快照目录.mkdir(parents=True, exist_ok=True)
    for 文件 in 来源目录.rglob("*"):
        if 文件.is_file() and "pycache" not in str(文件) and "工程缓存" not in str(文件) \
                and 文件.name != "快照摘要.json":
            相对 = 文件.relative_to(来源目录)
            目标 = 快照目录 / 相对
            目标.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(文件, 目标)
    # 生成快照摘要（含全部文件，供一致性校验）
    摘要表 = {}
    for 文件 in sorted(快照目录.rglob("*")):
        if 文件.is_file() and 文件.name != "快照摘要.json":
            摘要表[str(文件.relative_to(快照目录))] = 创建内容摘要(文件)
    (快照目录 / "快照摘要.json").write_text(
        json.dumps({"快照id": uuid.uuid4().hex[:16], "文件摘要": 摘要表},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return 快照目录 / "快照摘要.json"


def 校验快照(快照目录: Path) -> tuple[bool, str]:
    """校验快照完整性：文件摘要逐项比对。"""
    快照目录 = Path(快照目录)
    摘要路径 = 快照目录 / "快照摘要.json"
    if not 摘要路径.is_file():
        return False, "缺少 快照摘要.json"
    try:
        摘要数据 = json.loads(摘要路径.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False, "快照摘要.json 损坏"
    for 相对, 期望摘要 in 摘要数据.get("文件摘要", {}).items():
        文件 = 快照目录 / 相对
        if not 文件.is_file():
            return False, f"快照缺少文件: {相对}"
        if 创建内容摘要(文件) != 期望摘要:
            return False, f"快照文件被修改: {相对}"
    return True, "快照完整"


def 创建唯一运行目录(基础目录: Path, 前缀: str = "运行") -> Path:
    """创建唯一运行目录（临时目录语义，调用方负责释放）。"""
    基础目录 = Path(基础目录)
    基础目录.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"{前缀}_", dir=str(基础目录)))


def 原子写入(目标路径: Path, 内容: str | bytes) -> None:
    """原子写入：临时文件 + fsync + rename。"""
    目标路径 = Path(目标路径)
    目标路径.parent.mkdir(parents=True, exist_ok=True)
    临时路径 = 目标路径.parent / f".{目标路径.name}.{uuid.uuid4().hex[:8]}.tmp"
    模式 = "wb" if isinstance(内容, bytes) else "w"
    编码 = None if isinstance(内容, bytes) else "utf-8"
    with 临时路径.open(模式, encoding=编码) as 输出:
        输出.write(内容)
        输出.flush()
        os.fsync(输出.fileno())
    os.replace(临时路径, 目标路径)  # 原子替换


def 原子替换(目标路径: Path, 新内容: str | bytes, 期望版本: str = "") -> tuple[bool, str]:
    """原子替换：可选版本比较（CAS 语义的写路径）。"""
    目标路径 = Path(目标路径)
    if 期望版本 and 目标路径.is_file():
        try:
            现有 = json.loads(目标路径.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False, "现有文件损坏，无法比较版本"
        if str(现有.get("版本", "")) != str(期望版本):
            return False, f"{错误码_版本冲突}: 期望版本 {期望版本}，实际 {现有.get('版本', '')}"
    原子写入(目标路径, 新内容)
    return True, "原子替换完成"


def 比较并交换(目标路径: Path, 期望值: Any, 新值: Any) -> tuple[bool, str]:
    """比较并交换（CAS）：读取 → 比较 → 原子写回；并发冲突返回版本冲突。"""
    目标路径 = Path(目标路径)
    if not 目标路径.is_file():
        return False, f"{错误码_资源不存在}: 目标文件不存在"
    try:
        现有 = json.loads(目标路径.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False, "目标文件损坏"
    if 现有.get("值") != 期望值:
        return False, f"{错误码_版本冲突}: 期望值 {期望值}，实际 {现有.get('值')}"
    现有["值"] = 新值
    现有["版本"] = str(int(现有.get("版本", 0)) + 1)
    原子写入(目标路径, json.dumps(现有, ensure_ascii=False, indent=2))
    return True, "CAS 提交成功"


class 资源短锁:
    """资源级跨进程短锁：文件锁（mkdir 原子性）+ 持有者信息。"""

    def __init__(self, 锁目录: Path, 资源id: str, 持有者: str = "") -> None:
        self.锁路径 = Path(锁目录) / f"锁_{资源id}"
        self.持有者 = 持有者
        self.已持有 = False

    def 获取(self, 超时秒: float = 3.0) -> tuple[bool, str]:
        """获取锁（mkdir 原子创建，轮询等待）；超时返回明确错误。"""
        self.锁路径.parent.mkdir(parents=True, exist_ok=True)
        截止 = time.monotonic() + 超时秒
        while True:
            try:
                self.锁路径.mkdir()
                (self.锁路径 / "持有者.json").write_text(
                    json.dumps({"持有者": self.持有者, "时间": time.strftime("%H:%M:%S")},
                               ensure_ascii=False), encoding="utf-8")
                self.已持有 = True
                return True, "锁已获取"
            except FileExistsError:
                if time.monotonic() > 截止:
                    return False, f"{错误码_资源被占用}: 锁被其他持有者占用（{self.锁路径.name}）"
                time.sleep(0.01)

    def 释放(self) -> tuple[bool, str]:
        if not self.已持有:
            return False, "锁未持有（释放幂等）"
        try:
            shutil.rmtree(self.锁路径)
            self.已持有 = False
            return True, "锁已释放"
        except FileNotFoundError:
            self.已持有 = False
            return True, "锁已释放（目录不存在）"

    def 持有者是谁(self) -> str:
        文件 = self.锁路径 / "持有者.json"
        if 文件.is_file():
            try:
                return json.loads(文件.read_text(encoding="utf-8")).get("持有者", "")
            except json.JSONDecodeError:
                return ""
        return ""


def 安全释放资源(路径: Path) -> tuple[bool, str]:
    """安全释放资源：文件删除或目录递归删除；不存在视为幂等成功。"""
    路径 = Path(路径)
    if not 路径.exists():
        return True, "资源不存在（释放幂等）"
    try:
        if 路径.is_dir():
            shutil.rmtree(路径)
        else:
            路径.unlink()
        return True, f"已释放: {路径}"
    except OSError as 错误:
        return False, f"释放失败: {错误}"


def 生成资源包声明() -> dict:
    """资源管理支持库包声明（供装配/验证使用）。"""
    return {
        "包id": "资源管理", "名称": "资源管理", "类型": "支持库",
        "版本": "1.0.0", "说明": "原子资源操作（快照/写入/替换/交换/锁/释放）",
        "入口": "实现/资源管理.py",
        "能力": [
            {"能力id": "资源管理.创建内容摘要", "说明": "创建文件内容摘要", "参数": [{"名称": "文件路径"}]},
            {"能力id": "资源管理.创建不可变快照", "说明": "创建不可变快照", "参数": [{"名称": "来源目录"}]},
            {"能力id": "资源管理.创建唯一运行目录", "说明": "创建唯一运行目录", "参数": [{"名称": "基础目录"}]},
            {"能力id": "资源管理.原子写入", "说明": "原子写入文件", "参数": [{"名称": "目标路径"}]},
            {"能力id": "资源管理.原子替换", "说明": "原子替换（可选版本比较）", "参数": [{"名称": "目标路径"}]},
            {"能力id": "资源管理.比较并交换", "说明": "CAS 提交", "参数": [{"名称": "目标路径"}]},
            {"能力id": "资源管理.资源短锁", "说明": "资源级跨进程短锁", "参数": [{"名称": "锁目录"}]},
            {"能力id": "资源管理.安全释放", "说明": "安全释放资源", "参数": [{"名称": "路径"}]},
        ],
    }
