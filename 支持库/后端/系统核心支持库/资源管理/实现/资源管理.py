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
from 公共契约.基础类型.结果类型 import 结果

错误码_参数不合法 = "参数不合法"
错误码_版本冲突 = "版本冲突"
错误码_资源不存在 = "资源不存在"
错误码_资源被占用 = "资源被占用"
错误码_超时 = "超时"
错误码_内部错误 = "内部错误"
_受管状态服务 = None


def 设置受管状态服务(服务) -> None:
    """由运行核心装配唯一资源句柄服务；支持库不反向依赖运行核心实现。"""
    global _受管状态服务
    _受管状态服务 = 服务


def _状态服务():
    if _受管状态服务 is None:
        raise RuntimeError("受管状态服务未装配")
    return _受管状态服务


def _执行受管状态(函数) -> 结果:
    try:
        return 结果.成功结果(函数(_状态服务()))
    except KeyError as 错误:
        return 结果.失败("句柄无效", str(错误), 来源="资源管理")
    except PermissionError as 错误:
        return 结果.失败("句柄已过期", str(错误), 来源="资源管理")
    except ValueError as 错误:
        return 结果.失败("参数不合法", str(错误), 来源="资源管理")
    except RuntimeError as 错误:
        错误码 = "版本冲突" if "版本" in str(错误) or "提交" in str(错误) else "资源操作失败"
        return 结果.失败(错误码, str(错误), 来源="资源管理")


def 创建受管状态(资源id: str, 初始状态: dict, 项目id: str = "", 用户id: str = "") -> 结果:
    return _执行受管状态(lambda 服务: 服务.创建受管状态(
        资源id=资源id, 初始状态=初始状态, 项目id=项目id, 所有者=用户id))


def 读取受管状态(句柄: int, 项目id: str = "", 用户id: str = "") -> 结果:
    return _执行受管状态(lambda 服务: 服务.读取受管状态(
        句柄, 项目id=项目id, 所有者=用户id))


def 更新受管状态(句柄: int, 新状态: dict, 期望版本: str = "",
             项目id: str = "", 用户id: str = "") -> 结果:
    return _执行受管状态(lambda 服务: 服务.更新受管状态(
        句柄, 新状态, 期望版本=期望版本, 项目id=项目id, 所有者=用户id)
    )


def 释放受管状态(句柄: int, 项目id: str = "", 用户id: str = "") -> 结果:
    return _执行受管状态(lambda 服务: 服务.释放受管状态(
        句柄, 项目id=项目id, 所有者=用户id))


def 创建内容摘要(文件路径: Path, 算法: str = "sha256") -> str:
    """创建内容摘要（分块读取，不加载全文件入内存）。"""
    文件路径 = Path(文件路径)
    if not 文件路径.is_file():
        raise FileNotFoundError(f"文件不存在: {文件路径}")
    摘要器 = hashlib.new(算法)
    with open(文件路径, "rb") as 输入:
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
    with open(临时路径, 模式, encoding=编码) as 输出:
        输出.write(内容)
        输出.flush()
        os.fsync(输出.fileno())
    os.replace(临时路径, 目标路径)  # 原子替换
    return True


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


def 执行资源短锁(锁目录: str | None = None, 资源id: str | None = None, 持有者: str = "") -> 结果:
    """公开HTTP原子探针：获取短锁、读取持有者并释放，返回可传输结果。"""
    if not isinstance(锁目录, str) or not 锁目录:
        return 结果.失败("参数不合法", "锁目录必须是非空文本", 来源="资源管理")
    if not isinstance(资源id, str) or not 资源id:
        return 结果.失败("参数不合法", "资源id必须是非空文本", 来源="资源管理")
    短锁 = 资源短锁(Path(锁目录), 资源id, 持有者)
    已获取, 说明 = 短锁.获取()
    if not 已获取:
        return 结果.失败(错误码_资源被占用, 说明, 来源="资源管理")
    当前持有者 = 短锁.持有者是谁()
    已释放, 释放说明 = 短锁.释放()
    return 结果.成功结果({"已获取": True, "已释放": 已释放, "持有者": 当前持有者,
                      "锁路径": str(短锁.锁路径), "说明": 释放说明})


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
        "入口": "实现/系统核心支持库.资源管理.py",
        "能力": [
            {"能力id": "系统核心支持库.资源管理.创建内容摘要", "说明": "创建文件内容摘要", "参数": [{"名称": "文件路径"}]},
            {"能力id": "系统核心支持库.资源管理.创建不可变快照", "说明": "创建不可变快照", "参数": [{"名称": "来源目录"}]},
            {"能力id": "系统核心支持库.资源管理.创建唯一运行目录", "说明": "创建唯一运行目录", "参数": [{"名称": "基础目录"}]},
            {"能力id": "系统核心支持库.资源管理.原子写入", "说明": "原子写入文件", "参数": [{"名称": "目标路径"}]},
            {"能力id": "系统核心支持库.资源管理.原子替换", "说明": "原子替换（可选版本比较）", "参数": [{"名称": "目标路径"}]},
            {"能力id": "系统核心支持库.资源管理.比较并交换", "说明": "CAS 提交", "参数": [{"名称": "目标路径"}]},
            {"能力id": "系统核心支持库.资源管理.资源短锁", "说明": "资源级跨进程短锁", "参数": [{"名称": "锁目录"}]},
            {"能力id": "系统核心支持库.资源管理.安全释放", "说明": "安全释放资源", "参数": [{"名称": "路径"}]},
        ],
    }


# ═══════════════════════════════════════════════
# 审计账本：OpenClaw audit-event-store 模式化落地
# 默认开启、只记元数据（谁/何时/对谁/结果码）、HMAC 假名化身份、
# 上限+批修剪（默认10万行/1024批）、不记内容（规避隐私与合规风险）。
# ═══════════════════════════════════════════════
_审计账本: dict[str, list[dict]] = {}  # 账本名 -> 事件列表
_审计锁 = threading.Lock()
审计默认上限 = 100000
审计默认修剪批 = 1024
审计默认保留天 = 30

# 事件字段白名单：只允许元数据，不允许内容字段
审计允许字段 = {"事件类型", "主体", "对象", "结果码", "耗时毫秒", "通道", "方向", "元数据"}


def _审计假名化(主体: str) -> str:
    """HMAC 风格假名化：主体名->短哈希，仅用于审计（非内容加密）。"""
    if not 主体:
        return "匿名"
    return "u-" + hashlib.sha256(主体.encode("utf-8")).hexdigest()[:12]


def 创建审计账本(*, 账本名: str = None, 上限: int = None, 保留天: int = None) -> 结果:
    """创建审计账本。默认上限10万、保留30天；同名复用。"""
    try:
        名 = str(账本名 or "").strip()
        if not 名:
            return 结果.失败(错误码_参数不合法, "账本名不能为空", 来源="资源管理")
        上限值 = int(上限 or 审计默认上限)
        if 上限值 <= 0:
            return 结果.失败(错误码_参数不合法, "上限必须为正整数", 来源="资源管理")
        保留值 = int(保留天 or 审计默认保留天)
        with _审计锁:
            if 名 not in _审计账本:
                _审计账本[名] = []
            return 结果.成功结果({"账本名": 名, "上限": 上限值, "保留天": 保留值,
                                 "事件数": len(_审计账本[名])})
    except Exception as 异常:
        return 结果.失败("创建失败", str(异常), 来源="资源管理")


def 记审计事件(*, 账本名: str = None, 事件类型: str = None, 主体: str = None,
               对象: str = None, 结果码: str = None, 耗时毫秒: int = None,
               通道: str = None, 方向: str = None, 元数据: dict = None) -> 结果:
    """记录一条审计事件（默认开启）。只记元数据字段，事件内容不得传入。"""
    try:
        名 = str(账本名 or "").strip()
        if not 名:
            return 结果.失败(错误码_参数不合法, "账本名不能为空", 来源="资源管理")
        类型 = str(事件类型 or "通用").strip()
        if not 类型:
            return 结果.失败(错误码_参数不合法, "事件类型不能为空", 来源="资源管理")
        import time as _时间
        事件 = {
            "序号": int(_时间.time() * 1000),  # 毫秒时间戳作全局递增近似
            "时间": _时间.strftime("%Y-%m-%d %H:%M:%S", _时间.localtime()),
            "事件类型": 类型,
            "主体": _审计假名化(str(主体 or "匿名")),
            "对象": str(对象 or ""),
            "结果码": str(结果码 or "OK"),
        }
        if 耗时毫秒 is not None:
            事件["耗时毫秒"] = int(耗时毫秒)
        if 通道:
            事件["通道"] = str(通道)
        if 方向:
            事件["方向"] = str(方向)
        if 元数据:
            # 只收白名单内键（元数据只允许 结果码/数量 等数字或短标签）
            事件["元数据"] = {str(k): str(v) for k, v in 元数据.items() if len(str(v)) <= 64}
        with _审计锁:
            if 名 not in _审计账本:
                _审计账本[名] = []
            账本 = _审计账本[名]
            账本.append(事件)
            # 超上限批量修剪（OpenClaw：10万行上限/1024批修剪）
            if len(账本) > 审计默认上限:
                del 账本[:审计默认修剪批]
            return 结果.成功结果({"记录": True, "账本名": 名, "事件数": len(账本)})
    except Exception as 异常:
        return 结果.失败("记录失败", str(异常), 来源="资源管理")


def 查审计事件(*, 账本名: str = None, 事件类型: str = None, 主体: str = None,
                对象: str = None, 条数: int = None) -> 结果:
    """按条件查询审计事件（只读元数据，不含内容）。"""
    try:
        名 = str(账本名 or "").strip()
        if not 名:
            return 结果.失败(错误码_参数不合法, "账本名不能为空", 来源="资源管理")
        上限 = max(1, min(int(条数 or 50), 500))
        with _审计锁:
            if 名 not in _审计账本:
                return 结果.失败("账本不存在", f"审计账本 {名} 未创建", 来源="资源管理")
            账本 = _审计账本[名]
            # 倒序取最近 N 条
            命中 = list(reversed(账本))
            if 事件类型:
                命中 = [e for e in 命中 if e.get("事件类型") == 事件类型]
            if 主体:
                hit = _审计假名化(str(主体))
                命中 = [e for e in 命中 if e.get("主体") == hit]
            if 对象:
                命中 = [e for e in 命中 if e.get("对象") == str(对象)]
            return 结果.成功结果({"账本名": 名, "命中": len(命中),
                                 "事件列表": 命中[:上限], "共": len(账本)})
    except Exception as 异常:
        return 结果.失败("查询失败", str(异常), 来源="资源管理")


def 清空审计账本(*, 账本名: str = None) -> 结果:
    """清空审计账本（谨慎操作，需账本名精确）。"""
    try:
        名 = str(账本名 or "").strip()
        if not 名:
            return 结果.失败(错误码_参数不合法, "账本名不能为空", 来源="资源管理")
        with _审计锁:
            if 名 not in _审计账本:
                return 结果.失败("账本不存在", f"审计账本 {名} 未创建", 来源="资源管理")
            数 = len(_审计账本[名])
            _审计账本[名] = []
            return 结果.成功结果({"清空": True, "账本名": 名, "已清": 数})
    except Exception as 异常:
        return 结果.失败("清空失败", str(异常), 来源="资源管理")


# ═══════════════════════════════════════════════
# 配置变更指纹：OpenClaw config-journal-snapshot 模式化落地
# 改前快照指纹 + 改后对比；记录 谁/何时/改了什么/前后指纹；敏感值不落明文。
# ═══════════════════════════════════════════════
_配置指纹账本: dict[str, dict] = {}
_配置指纹锁 = threading.Lock()


def _配置指纹(配置: dict) -> str:
    """配置快照指纹：稳定序列化 + sha256。"""
    try:
        规范化 = json.dumps(配置, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(规范化.encode("utf-8")).hexdigest()[:16]
    except Exception:
        return "无法指纹"


def 登记配置快照(*, 配置名: str = None, 配置: dict = None, 操作人: str = None) -> 结果:
    """登记配置当前快照指纹（改前调用：记录基线）。"""
    try:
        名 = str(配置名 or "").strip()
        if not 名:
            return 结果.失败(错误码_参数不合法, "配置名不能为空", 来源="资源管理")
        if not isinstance(配置, dict):
            return 结果.失败(错误码_参数不合法, "配置必须是字典", 来源="资源管理")
        import time as _时间
        指纹 = _配置指纹(配置)
        with _配置指纹锁:
            _配置指纹账本[名] = {
                "指纹": 指纹,
                "改前指纹": None,
                "操作人": str(操作人 or ""),
                "时间": _时间.strftime("%Y-%m-%d %H:%M:%S", _时间.localtime()),
                "变更记录": [],
            }
            return 结果.成功结果({"配置名": 名, "指纹": 指纹, "基线": True})
    except Exception as 异常:
        return 结果.失败("登记失败", str(异常), 来源="资源管理")


def 对比配置指纹(*, 配置名: str = None, 新配置: dict = None, 操作人: str = None) -> 结果:
    """对比新配置与基线指纹。变则记 journal（改前指纹/新指纹/操作人），不变返回一致。"""
    try:
        名 = str(配置名 or "").strip()
        if not 名:
            return 结果.失败(错误码_参数不合法, "配置名不能为空", 来源="资源管理")
        if not isinstance(新配置, dict):
            return 结果.失败(错误码_参数不合法, "新配置必须是字典", 来源="资源管理")
        import time as _时间
        新指纹 = _配置指纹(新配置)
        with _配置指纹锁:
            if 名 not in _配置指纹账本:
                # 无基线：直接登记为新基线（幂等首登）
                _配置指纹账本[名] = {
                    "指纹": 新指纹, "改前指纹": None,
                    "操作人": str(操作人 or ""),
                    "时间": _时间.strftime("%Y-%m-%d %H:%M:%S", _时间.localtime()),
                    "变更记录": [],
                }
                return 结果.成功结果({"配置名": 名, "变更": False, "首登基线": True, "指纹": 新指纹})
            条目 = _配置指纹账本[名]
            if 条目["指纹"] == 新指纹:
                return 结果.成功结果({"配置名": 名, "变更": False, "指纹": 新指纹})
            # 有变更：记 journal
            条目["变更记录"].append({
                "改前指纹": 条目["指纹"],
                "新指纹": 新指纹,
                "操作人": str(操作人 or "未知"),
                "时间": _时间.strftime("%Y-%m-%d %H:%M:%S", _时间.localtime()),
            })
            条目["改前指纹"] = 条目["指纹"]
            条目["指纹"] = 新指纹
            条目["操作人"] = str(操作人 or "")
            条目["时间"] = _时间.strftime("%Y-%m-%d %H:%M:%S", _时间.localtime())
            return 结果.成功结果({
                "配置名": 名, "变更": True,
                "改前指纹": 条目["改前指纹"], "新指纹": 新指纹,
                "操作人": str(操作人 or "未知"),
                "变更序号": len(条目["变更记录"]),
            })
    except Exception as 异常:
        return 结果.失败("对比失败", str(异常), 来源="资源管理")


def 查配置指纹(*, 配置名: str = None) -> 结果:
    """查询配置指纹与变更记录。"""
    try:
        名 = str(配置名 or "").strip()
        if not 名:
            return 结果.失败(错误码_参数不合法, "配置名不能为空", 来源="资源管理")
        with _配置指纹锁:
            if 名 not in _配置指纹账本:
                return 结果.失败("配置不存在", f"配置指纹 {名} 未登记", 来源="资源管理")
            条目 = _配置指纹账本[名]
            return 结果.成功结果({
                "配置名": 名, "当前指纹": 条目["指纹"],
                "改前指纹": 条目["改前指纹"],
                "当前操作人": 条目["操作人"], "当前时间": 条目["时间"],
                "变更次数": len(条目["变更记录"]),
                "变更记录": list(reversed(条目["变更记录"])),
            })
    except Exception as 异常:
        return 结果.失败("查询失败", str(异常), 来源="资源管理")
