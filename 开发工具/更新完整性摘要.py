#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫描所有包，重新计算文件哈希并更新 完整性摘要.json"""

import json
import hashlib
from pathlib import Path

系统根 = Path("~/Documents/Agent/PHP/系统工程平台")
目标目录 = ["支持库", "模块库", "技能库"]  # 扫描这些目录下的包

def 计算sha256(路径):
    if not 路径.exists():
        return None
    sha = hashlib.sha256()
    with open(路径, "rb") as f:
        for 块 in iter(lambda: f.read(65536), b""):
            sha.update(块)
    return sha.hexdigest()

def 更新摘要(摘要路径):
    try:
        数据 = json.loads(摘要路径.read_text(encoding="utf-8"))
    except:
        return False, "JSON解析失败"
    
    包id = 数据.get("包id", "未知")
    文件清单 = 数据.get("文件清单", [])
    更新数 = 0
    
    for 条目 in 文件清单:
        相对路径 = 条目["路径"]
        文件路径 = 摘要路径.parent / 相对路径
        新哈希 = 计算sha256(文件路径)
        if 新哈希 is None:
            print(f"  ⚠️ 文件不存在: {相对路径}")
            continue
        if 条目["sha256"] != 新哈希:
            条目["sha256"] = 新哈希
            更新数 += 1
    
    if 更新数:
        摘要路径.write_text(json.dumps(数据, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  ✅ 更新 {更新数} 个文件")
        return True, f"更新 {更新数} 个文件"
    return False, "无需更新"

def 主():
    找到 = 0
    更新 = 0
    for 目录 in 目标目录:
        for 摘要路径 in (系统根 / 目录).rglob("完整性摘要.json"):
            if "工程缓存" in str(摘要路径) or "__pycache__" in str(摘要路径):
                continue
            找到 += 1
            print(f"📄 {摘要路径.relative_to(系统根)}")
            已更新, 信息 = 更新摘要(摘要路径)
            if 已更新:
                更新 += 1
    print(f"\n总计: 扫描 {找到} 个包, 更新 {更新} 个")

if __name__ == "__main__":
    主()