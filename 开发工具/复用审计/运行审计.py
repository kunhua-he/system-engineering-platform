"""运行审计：模块库 能力调用图与原子旁路审计 命令行入口。

用法：
    python3.14 开发工具/复用审计/运行审计.py [--目录 路径]
退出码：0 = 无违规；1 = 存在违规。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

系统根 = next(祖先 for 祖先 in Path(__file__).resolve().parents
             if (祖先 / "模块库").is_dir() and (祖先 / "测试中心").is_dir())
sys.path.insert(0, str(系统根))

from 开发工具.复用审计.能力调用图审计 import 审计模块库


def 主() -> int:
    解析器 = argparse.ArgumentParser(description="模块库 能力调用图与原子旁路审计")
    解析器.add_argument("--目录", type=Path, default=None, help="审计目标目录（默认 系统根/模块库）")
    参数 = 解析器.parse_args()
    报告 = 审计模块库(参数.目录)
    for 违规 in 报告.违规列表:
        print(f"{违规.文件}:{违规.行号}:{违规.类型}")
    print(f"审计文件数: {报告.审计文件数}；违规数: {len(报告.违规列表)}")
    return 0 if 报告.成功 else 1


if __name__ == "__main__":
    sys.exit(主())
