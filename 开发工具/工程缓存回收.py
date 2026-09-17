"""工程缓存回收脚本（WP6）。

清理工程缓存中的无回收残留：
  1. 按引用清理：工程缓存/验证缓存/文件/ 下路径哈希对应的测试文件已不存在的缓存。
  2. 按访问时间清理：工程缓存/验证缓存/ 下超过 30 天未命中的 json。
  3. 并行日志清理：工程缓存/并行_*.log 超过 7 天删除。
  4. 验证运行残留：工程缓存/验证运行/ 下超过 7 天的子目录删除。
  5. 边界保护：禁止触碰 提供者运行环境/、制品仓库/、发布证据/、核心快照/、
     说明书/、协作状态/、MCP任务观测/；删除前打印路径，--试运行 只打印不删。

用法：
    python3.14 开发工具/工程缓存回收.py            # 真实清理
    python3.14 开发工具/工程缓存回收.py --试运行    # 只打印待清理清单
"""
import argparse
from 公共契约.基础类型.逻辑类型 import 真, 假
import hashlib
import json
import shutil
import time
from pathlib import Path

仓库根 = Path(__file__).resolve().parent.parent
工程缓存根 = 仓库根 / "工程缓存"

边界保护目录 = (
    "提供者运行环境", "制品仓库", "发布证据", "核心快照",
    "说明书", "协作状态", "MCP任务观测",
)

并行日志保留天数 = 7
验证运行保留天数 = 7
缓存json保留天数 = 30
天秒数 = 24 * 60 * 60


def 路径哈希(相对路径: str) -> str:
    """路径哈希：相对路径 sha256 前 16 位，与验证缓存文件命名约定一致。"""
    return hashlib.sha256(相对路径.encode("utf-8")).hexdigest()[:16]


def 路径大小(路径: Path) -> int:
    """递归统计路径占用字节数（目录含全部子文件）。"""
    if 路径.is_file():
        try:
            return 路径.stat().st_size
        except OSError:
            return 0
    总大小 = 0
    try:
        for 子 in 路径.rglob("*"):
            if 子.is_file():
                try:
                    总大小 += 子.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return 总大小


def 格式大小(字节: int) -> str:
    """字节数格式化为人类可读字符串。"""
    if 字节 < 1024:
        return f"{字节} B"
    if 字节 < 1024 * 1024:
        return f"{字节 / 1024:.1f} KB"
    if 字节 < 1024 * 1024 * 1024:
        return f"{字节 / 1024 / 1024:.1f} MB"
    return f"{字节 / 1024 / 1024 / 1024:.1f} GB"


class 清理统计:
    """清理条目数与释放字节统计，失败项单独记录。"""

    def __init__(self) -> None:
        self.条目数 = 0
        self.释放字节 = 0
        self.失败表 = []

    def 增加(self, 大小: int) -> None:
        self.条目数 += 1
        self.释放字节 += 大小


def 在边界内(路径: Path) -> bool:
    """路径是否位于边界保护目录之内（防御性校验）。"""
    try:
        相对 = 路径.resolve().relative_to(工程缓存根.resolve())
    except ValueError:
        return 假
    return bool(相对.parts) and 相对.parts[0] in 边界保护目录


def 删除(路径: Path, 试运行: bool, 统计: 清理统计) -> None:
    """删除前打印路径；--试运行 只打印不删。边界目录一律拒绝。"""
    if 在边界内(路径):
        print(f"边界保护：拒绝删除 {路径}")
        return
    大小 = 路径大小(路径)
    if 试运行:
        print(f"[试运行] 将删除 {路径}（{格式大小(大小)}）")
    else:
        print(f"删除 {路径}（{格式大小(大小)}）")
        try:
            if 路径.is_dir():
                shutil.rmtree(路径)
            else:
                路径.unlink()
        except OSError as 错误:
            print(f"删除失败：{路径}（{错误}）")
            统计.失败表.append(str(路径))
            return
    统计.增加(大小)


def 清理按引用(试运行: bool, 统计: 清理统计) -> None:
    """按引用清理：清理 验证缓存/文件/ 下对应测试文件已不存在的缓存。"""
    文件缓存目录 = 工程缓存根 / "验证缓存" / "文件"
    if not 文件缓存目录.is_dir():
        return
    测试中心根 = 仓库根 / "测试中心"
    现存哈希集合 = set()
    if 测试中心根.is_dir():
        for 测试文件 in 测试中心根.rglob("测试_*.py"):
            相对路径 = 测试文件.relative_to(仓库根).as_posix()
            现存哈希集合.add(路径哈希(相对路径))
    for 缓存项 in 文件缓存目录.iterdir():
        命中 = 缓存项.name in 现存哈希集合 or 缓存项.stem in 现存哈希集合
        if not 命中:
            删除(缓存项, 试运行, 统计)


def 清理过期json(试运行: bool, 统计: 清理统计) -> None:
    """按访问时间清理：验证缓存/ 下超过 30 天未命中的 json。"""
    缓存目录 = 工程缓存根 / "验证缓存"
    if not 缓存目录.is_dir():
        return
    当前时间 = time.time()
    上限秒数 = 缓存json保留天数 * 天秒数
    for 路径 in sorted(缓存目录.glob("*.json")):
        最后命中 = 0.0
        try:
            数据 = json.loads(路径.read_text(encoding="utf-8"))
            时间戳 = 数据.get("时间戳", 0) if isinstance(数据, dict) else 0
            最后命中 = float(时间戳)
        except (OSError, ValueError, TypeError):
            最后命中 = 0.0
        if 最后命中 <= 0:
            try:
                最后命中 = 路径.stat().st_mtime
            except OSError:
                最后命中 = 当前时间
        if 当前时间 - 最后命中 > 上限秒数:
            删除(路径, 试运行, 统计)


def 清理旧单文件缓存(试运行: bool, 统计: 清理统计) -> None:
    """旧结构单文件缓存清理：工程缓存/验证缓存.json（目录 验证缓存/ 之外的旧文件）。

    第 1 层已把验证缓存从单文件 验证缓存.json 改为目录 验证缓存/{阶段名}.json；
    旧单文件不再被读取，属于废弃残留，删除避免混淆与占盘。
    """
    旧路径 = 工程缓存根 / "验证缓存.json"
    if 旧路径.is_file():
        删除(旧路径, 试运行, 统计)


def 清理并行日志(试运行: bool, 统计: 清理统计) -> None:
    """并行日志清理：工程缓存/并行_*.log 超过 7 天删除。"""
    当前时间 = time.time()
    上限秒数 = 并行日志保留天数 * 天秒数
    for 路径 in sorted(工程缓存根.glob("并行_*.log")):
        try:
            年龄 = 当前时间 - 路径.stat().st_mtime
        except OSError:
            continue
        if 年龄 > 上限秒数:
            删除(路径, 试运行, 统计)


def 清理验证运行(试运行: bool, 统计: 清理统计) -> None:
    """验证运行残留：验证运行/ 下超过 7 天的子目录删除。"""
    运行目录 = 工程缓存根 / "验证运行"
    if not 运行目录.is_dir():
        return
    当前时间 = time.time()
    上限秒数 = 验证运行保留天数 * 天秒数
    for 路径 in sorted(运行目录.iterdir()):
        if not 路径.is_dir():
            continue
        try:
            年龄 = 当前时间 - 路径.stat().st_mtime
        except OSError:
            continue
        if 年龄 > 上限秒数:
            删除(路径, 试运行, 统计)


def 主函数() -> int:
    参数解析器 = argparse.ArgumentParser(description="工程缓存回收脚本")
    参数解析器.add_argument("--试运行", action="store_true", help="只打印待清理清单，不实际删除")
    参数 = 参数解析器.parse_args()

    统计 = 清理统计()
    清理旧单文件缓存(参数.试运行, 统计)
    清理按引用(参数.试运行, 统计)
    清理过期json(参数.试运行, 统计)
    清理并行日志(参数.试运行, 统计)
    清理验证运行(参数.试运行, 统计)

    if 统计.条目数 == 0:
        print("无需清理：未发现过期或失去引用的缓存残留。")
    else:
        动作 = "待清理" if 参数.试运行 else "已清理"
        print(f"{动作} {统计.条目数} 条，释放估算 {格式大小(统计.释放字节)}")
    if 统计.失败表:
        print(f"清理失败 {len(统计.失败表)} 条：")
        for 失败 in 统计.失败表:
            print(f"  {失败}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(主函数())
