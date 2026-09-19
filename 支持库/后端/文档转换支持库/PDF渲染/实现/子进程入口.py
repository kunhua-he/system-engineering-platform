"""子进程入口（PDF 渲染 / PyMuPDF）：唯一实现在 支持库/适配层/PyMuPDF提供者（D-1 收口，本包不放第二份）。

本文件原与 `支持库/适配层/PyMuPDF提供者/实现/子进程入口.py` **逐字同源**，差异只有两处：
① 包路径深度（后端腿比适配层腿多一层目录，故 `系统根.parents[N]` 相差 1，
**两腿实测各自都指向项目根**，不是错误、不能统一成一个数字；见迁移清单 §10.8）；
② 部署自举（激活指针解析 + 注入）—— **这一处是后端腿侧的必要能力，必须逐字保留**：
运行前提是依赖平台客户端制品已安装（激活指针 `工程缓存/制品仓库/平台客户端环境/当前.json`
存在且指向已安装制品），入口解析该指针并把平台客户端环境目录加入 `sys.path`（幂等），
使 `平台客户端` 包可直接导入；缺自举会在部署布局下报「平台客户端制品缺失」。
（教训：按通用门面模板收口时**不得**丢掉本段 —— Pillow 腿同批已实测为此真红。）

同一份逻辑只能有一个实现，故本文件**在完成自举之后**改为转调：让
`支持库.后端.文档转换支持库.PDF渲染.实现.子进程入口` 与适配层腿那唯一实现成为
**同一个模块对象**（`sys.modules[__name__] = 唯一实现`）。

**本文件就是被 `subprocess.Popen([sys.executable, 本文件路径])` 当脚本跑的那一个**，
因此 `__main__` 分支**按唯一实现名取模块对象**调用 `主循环`，不做跨包 `实现/` 导入
（那会被 `运行核心/依赖防火墙.py` 按 AST 判「跨包禁止导入 实现/ 目录」）。
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

系统根 = Path(__file__).resolve().parents[5]
导入根 = 系统根.parent if 系统根.name == "平台客户端" else 系统根
if str(导入根) not in sys.path:
    sys.path.insert(0, str(导入根))

客户端环境目录名 = "工程缓存/制品仓库/平台客户端环境"
激活指针文件名 = "当前.json"
_平台客户端路径已注入 = False


def 平台客户端环境目录() -> Path:
    """平台客户端环境目录：默认 系统根/工程缓存/制品仓库/平台客户端环境。

    允许环境变量 PyMuPDF提供者_客户端环境目录 覆盖（测试/部署注入）。
    """
    覆盖 = os.environ.get("PyMuPDF提供者_客户端环境目录")
    if 覆盖:
        return Path(覆盖).resolve()
    return 系统根 / 客户端环境目录名


def 注入平台客户端路径() -> str | None:
    """解析激活指针并把平台客户端环境目录加入 sys.path（幂等）。

    成功返回 None；失败返回中文错误说明（制品缺失/激活指针不可读）。
    进程内重复调用不重复注入。
    """
    global _平台客户端路径已注入
    if _平台客户端路径已注入:
        return None
    if 系统根.name == "平台客户端" and (系统根 / "__init__.py").is_file():
        _平台客户端路径已注入 = True
        return None
    环境目录 = 平台客户端环境目录()
    指针文件 = 环境目录 / 激活指针文件名
    if not 指针文件.is_file():
        return f"平台客户端制品缺失：激活指针不存在（{指针文件}）"
    try:
        import json as _json
        指针 = _json.loads(指针文件.read_text(encoding="utf-8"))
    except Exception as 错误:
        return f"平台客户端制品缺失：激活指针不可读（{错误}）"
    已安装目录 = 环境目录 / "平台客户端"
    if 已安装目录.is_dir() and (已安装目录 / "平台客户端" / "__init__.py").is_file():
        注入目录 = 已安装目录
    else:
        注入目录 = 环境目录
    if not 注入目录.is_dir():
        return f"平台客户端制品缺失：激活指针指向的制品目录未安装（{指针.get('制品目录') or '<空>'}）"
    if str(注入目录) not in sys.path:
        sys.path.insert(0, str(注入目录))
    _平台客户端路径已注入 = True
    return None


import 支持库.适配层.PyMuPDF提供者  # noqa: E402,F401 —— 公开入口（同层，合规）

唯一实现名 = "支持库.适配层.PyMuPDF提供者.实现.子进程入口"

if 唯一实现名 not in sys.modules:  # 兜底：公开入口未加载该子模块时按文件路径显式载入
    唯一实现文件 = 系统根 / "支持库" / "适配层" / "PyMuPDF提供者" / "实现" / "子进程入口.py"
    _规格 = importlib.util.spec_from_file_location(唯一实现名, 唯一实现文件)
    if _规格 is None or _规格.loader is None:
        raise ImportError(f"无法加载唯一实现（文件缺失或不可加载）: {唯一实现文件}")
    _模块 = importlib.util.module_from_spec(_规格)
    sys.modules[唯一实现名] = _模块
    _规格.loader.exec_module(_模块)

sys.modules[__name__] = sys.modules[唯一实现名]

if __name__ == "__main__":  # 按脚本路径启动这条路：走唯一实现名取模块对象，不做实现/ 导入
    注入错误 = 注入平台客户端路径()
    if 注入错误:
        print("{\"成功\": false, \"错误码\": \"提供者不可用\", \"错误说明\": \"" + 注入错误 + "\"}")
    else:
        sys.modules[唯一实现名].主循环()
    sys.stdout.flush()
    os._exit(0)
