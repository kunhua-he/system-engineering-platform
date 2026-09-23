"""子进程入口（图像解码 / Pillow）：唯一实现在 支持库/适配层/Pillow提供者（D-1 收口，本包不放第二份）。

本文件原与 `支持库/适配层/Pillow提供者/实现/子进程入口.py` **逐字同源**，差异只有两处：
① 取根方式（后端腿**不再按层数**、改按锚目录判据取根，见 `公共契约/运行时/导入前缀`；适配层腿仍是 `parents[4]`。两腿实测各自都指向项目根，不是错误；见迁移清单 §10.8）；
② 部署自举（激活指针解析 + 注入）—— **这一处是后端腿侧的必要能力，必须逐字保留**：
部署布局下入口位于 `平台客户端环境/平台客户端/支持库/…`，此时 `支持库` 既不在
`sys.path` 上、包前缀也可能被重写成 `平台客户端.`，缺自举会 `ModuleNotFoundError: 支持库`
（2026-09-20 实测：按通用门面模板收口时漏掉本段 → 测试 `test_子进程自举激活指针解析` 真红，
故本文件的自举段**不并入通用模板，单独保留**）。

同一份逻辑只能有一个实现，故本文件**在完成自举之后**改为转调：让
`支持库.后端.图像处理支持库.图像解码.实现.子进程入口` 与适配层腿那唯一实现成为
**同一个模块对象**（`sys.modules[__name__] = 唯一实现`）。

**本文件就是被 `subprocess.Popen([sys.executable, 本文件路径])` 当脚本跑的那一个**，
因此 `__main__` 分支**按唯一实现名取模块对象**调用 `主循环`，不做跨包 `实现/` 导入
（那会被 `运行核心/依赖防火墙.py` 按 AST 判「跨包禁止导入 实现/ 目录」）。

协议：stdin 读一行 JSON 请求，stdout 写一行 JSON 响应。
响应：{"成功": true, "值": ...} | {"成功": false, "值": ..., "错误码": ..., "错误说明": ...}
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

激活指针文件名 = "当前.json"
客户端环境环境变量名 = "Pillow提供者_客户端环境目录"
_环境目录已注入 = False


def 解析平台客户端环境目录() -> Path | None:
    """解析平台客户端环境目录（部署自举）：环境变量覆盖 → parents[5] → 系统根相对路径。

    仅当 当前.json 激活指针可读且指向已安装 平台客户端 制品时返回该目录；
    否则返回 None（源码布局，parents[4] 即可自举，无需激活指针）。
    """
    候选表: list[Path] = []
    覆盖 = os.environ.get(客户端环境环境变量名)
    if 覆盖:
        候选表.append(Path(覆盖).resolve())
    else:
        入口文件 = Path(__file__).resolve()
        候选表.append(入口文件.parents[5])
        候选表.append(Path(__file__).resolve().parents[4]
                       / "工程缓存" / "制品仓库" / "平台客户端环境")
    for 环境目录 in 候选表:
        指针文件 = 环境目录 / 激活指针文件名
        if not 指针文件.is_file():
            continue
        try:
            指针 = json.loads(指针文件.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if 指针.get("制品目录") and (环境目录 / "平台客户端" / "__init__.py").is_file():
            return 环境目录
    return None


def 注入平台客户端路径() -> None:
    """把平台客户端环境目录加入 sys.path（幂等），支撑部署后重写导入前缀的入口。"""
    global _环境目录已注入
    if _环境目录已注入:
        return
    环境目录 = 解析平台客户端环境目录()
    if 环境目录 is not None:
        for 导入路径 in (环境目录, 环境目录 / "平台客户端"):
            if 导入路径.is_dir() and str(导入路径) not in sys.path:
                sys.path.insert(0, str(导入路径))
    _环境目录已注入 = True


# 自举前只能用标准库：本文件被当脚本跑时 `sys.path[0]` 是 `实现/`，平台模块此刻
# **不可导入** ⇒ 不能调 `公共契约.运行时.导入前缀`（循环依赖）。判据仍是**同一套锚目录**
# （不是 `parents[N]` 那种一改目录结构就静默指错树的层数写法），与共享模块逐字同判。
系统根 = next(
    祖先 for 祖先 in Path(__file__).resolve().parents
    if (祖先 / "支持库").is_dir() and (祖先 / "模块库").is_dir()
)
导入根 = 系统根.parent if 系统根.name == "平台客户端" else 系统根
if str(导入根) not in sys.path:
    sys.path.insert(0, str(导入根))
注入平台客户端路径()

import 支持库.适配层.Pillow提供者  # noqa: E402,F401 —— 公开入口（同层，合规）

from 公共契约.运行时.导入前缀 import 载入唯一实现, 取根前缀

唯一实现名 = 取根前缀(__name__) + "支持库.适配层.Pillow提供者.实现.子进程入口"

载入唯一实现(唯一实现名, 系统根 / "支持库" / "适配层" / "Pillow提供者" / "实现" / "子进程入口.py")

sys.modules[__name__] = sys.modules[唯一实现名]

if __name__ == "__main__":  # 按脚本路径启动这条路：走唯一实现名取模块对象，不做实现/ 导入
    sys.modules[唯一实现名].主循环()
    sys.stdout.flush()
    os._exit(0)
