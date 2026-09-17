"""端口池、资源键和场景分片。"""
from __future__ import annotations
from 开发工具.HTML验证.多步场景 import 多步骤验证场景, 验证场景束
def _解析端口池(端口池: str) -> list[int]:
    """解析端口池表达式："45080-45180" 区间 或 "45080,45082" 枚举。"""
    if not isinstance(端口池, str) or not 端口池.strip():
        raise ValueError("端口池必须是非空文本")
    部分表 = [部分.strip() for 部分 in 端口池.split(",") if 部分.strip()]
    if not 部分表:
        raise ValueError("端口池为空")
    端口表: list[int] = []
    for 部分 in 部分表:
        if "-" in 部分:
            左右 = 部分.split("-", 1)
            if len(左右) != 2 or not 左右[0].isdigit() or not 左右[1].isdigit():
                raise ValueError(f"端口池区间不合法: {部分!r}")
            起始, 结束 = int(左右[0]), int(左右[1])
            if 起始 > 结束:
                raise ValueError(f"端口池区间起始大于结束: {部分!r}")
            if not 1 <= 起始 <= 65535 or not 1 <= 结束 <= 65535:
                raise ValueError(f"端口池超出合法范围: {部分!r}")
            端口表.extend(range(起始, 结束 + 1))
        elif 部分.isdigit():
            端口 = int(部分)
            if not 1 <= 端口 <= 65535:
                raise ValueError(f"端口超出合法范围: {部分!r}")
            端口表.append(端口)
        else:
            raise ValueError(f"端口池项不合法: {部分!r}")
    if len(set(端口表)) != len(端口表):
        raise ValueError("端口池含重复端口")
    return 端口表

def _场景资源键(场景: 多步骤验证场景) -> tuple[str, ...]:
    """根据能力前缀锁定非线程安全的共享外部提供者（模块级，供分片与并发锁共用）。"""
    能力表 = {
        步骤.能力id
        for 阶段 in (场景.前置步骤, 场景.目标步骤, 场景.清理步骤)
        for 步骤 in 阶段
    }
    键表 = set()
    # Git 场景独占：创建工作区/提交/切换分支/合并分支 都对**同一个底座仓库**做
    # worktree/引用写操作；3 个制品实例默认并发跑同一场景时互相抢 index.lock 与分支，
    # 实测表现是「写入文件 断言值缺失」等连带失败（2026-09-15：单跑 37 步全绿，
    # 并发跑固定红 4 步）。加资源键后同键场景固定同实例并按键串行。
    if any(能力.startswith("版本控制支持库.Git操作.") for 能力 in 能力表):
        键表.add("Git仓库")
    if any(能力.startswith(("文档转换支持库.", "LibreOffice转换.")) for 能力 in 能力表):
        键表.add("LibreOffice")
    if any(能力.startswith("大语言模型支持库.模型连接器.") for 能力 in 能力表):
        键表.add("模型连接器")
    if any(能力.startswith("媒体处理支持库.FFmpeg媒体.") for 能力 in 能力表):
        键表.add("FFmpeg")
    if any(能力.startswith("组件控件.") for 能力 in 能力表):
        键表.add("组件控件")
    # 文件租约场景独占：`开工即占` / `收工释放` / `申请文件租约` 等对**同一份租约存储**
    # 与**同一批仓库路径**做原子占用；默认多实例并发跑同一场景时互相抢同一路径，
    # 实测表现是「开工即占 已开工=false」（他人先占）→ 后续步骤的动态引用取不到值
    # （2026-09-18 实测：单跑全绿、并发跑固定红）。加资源键后同键场景固定同实例并按键串行。
    if any(能力.startswith(("开工编排.", "平台控制面.能力目录.")) for 能力 in 能力表):
        键表.add("文件租约")
    return tuple(sorted(键表))

def _分片场景(场景束: 验证场景束, 实例数: int) -> list[list[多步骤验证场景]]:
    """把场景束分片到 N 个实例：资源键场景固定同实例，普通场景按场景id哈希轮询。"""
    if type(实例数) is not int or 实例数 < 1:
        raise ValueError("实例数必须是正整数")
    分片表: list[list[多步骤验证场景]] = [[] for _ in range(实例数)]
    资源实例表: dict[tuple[str, ...], int] = {}
    for 场景 in 场景束.场景列表:
        键表 = _场景资源键(场景)
        if 键表:
            实例 = 资源实例表.setdefault(键表, len(资源实例表) % 实例数)
            分片表[实例].append(场景)
        else:
            实例 = hash(场景.场景id) % 实例数
            分片表[实例].append(场景)
    return 分片表

def _检查端口可用(端口: int) -> tuple[bool, str]:
    import socket
    测试 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        测试.bind(("127.0.0.1", 端口))
        return True, ""
    except OSError as 错误:
        return False, f"端口 {端口} 已被占用: {错误}"
    finally:
        测试.close()
