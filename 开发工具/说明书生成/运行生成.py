"""说明书生成一键脚本：从包声明生成全部说明书到 工程缓存/说明书/。"""

from __future__ import annotations

import sys
from pathlib import Path

系统根 = Path(__file__).resolve().parents[1]
for _祖先 in 系统根.parents:
    if (_祖先 / "支持库").is_dir() and (_祖先 / "模块库").is_dir():
        系统根 = _祖先
        break
if str(系统根) not in sys.path:
    sys.path.insert(0, str(系统根))

from 运行核心.加载器.包发现.发现器 import 发现全部
from 开发工具.说明书生成.说明书生成器 import 写出说明书


def 主函数() -> int:
    发现 = 发现全部(系统根 / "支持库", 系统根 / "模块库")
    if not 发现.成功:
        print(f"发现失败: {发现.问题列表}")
        return 1
    输出目录 = 系统根 / "工程缓存" / "说明书"
    写入列表 = 写出说明书(发现.声明列表, 输出目录)
    print(f"已生成 {len(写入列表)} 份说明书到 {输出目录}")
    return 0


if __name__ == "__main__":
    raise SystemExit(主函数())
