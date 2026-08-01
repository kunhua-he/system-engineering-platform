"""项目初始化：创建标准项目目录骨架与初始声明。

生成结构：
项目/
├── 项目声明.json
├── 依赖声明.json
├── 依赖锁定.json
├── 项目代码/
├── 项目模块/
├── 项目配置/
├── 项目资源/
├── 测试/
└── 运行入口/
"""

from __future__ import annotations

import json
from pathlib import Path

from 项目适配层.项目声明.项目声明 import 项目声明, 写入项目声明

标准目录列表 = ["项目代码", "项目模块", "项目配置", "项目资源", "测试", "运行入口"]


def 创建项目(项目路径: Path | str, 项目名称: str, 项目id: str = "") -> Path:
    """创建项目目录骨架，返回项目根目录路径。

    已存在的目录不覆盖（幂等）；重复创建同一项目结果一致。
    """
    根目录 = Path(项目路径)
    根目录.mkdir(parents=True, exist_ok=True)
    项目id = 项目id or f"项目.{项目名称}"

    声明 = 项目声明(
        项目id=项目id,
        项目名称=项目名称,
        支持库绑定=[],
        模块绑定=[],
        验证范围=["结构", "契约", "资产", "装配", "加载器", "项目适配"],
    )
    写入项目声明(声明, 根目录 / "项目声明.json")

    for 子目录 in 标准目录列表:
        (根目录 / 子目录).mkdir(exist_ok=True)

    依赖声明路径 = 根目录 / "依赖声明.json"
    if not 依赖声明路径.exists():
        依赖声明路径.write_text(
            json.dumps({"项目id": 项目id, "支持库绑定": [], "模块绑定": []}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    锁定路径 = 根目录 / "依赖锁定.json"
    if not 锁定路径.exists():
        锁定路径.write_text(
            json.dumps({"项目id": 项目id, "锁定版本": "1.0.0", "包列表": []}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    (根目录 / "运行入口").mkdir(exist_ok=True)
    return 根目录
