"""安装能力：制品安装（临时目录 + 备份/替换/失败还原三段式，安装前后双重校验）。

边界（2026-09-17 B-04 安全修复，两条都收在本文件）：
- 安装目标必须是**受控父目录下的单层合法目录名**（包id）：先经同仓已有工具
  `支持库.后端.系统核心支持库.路径安全.校验文件名` 判定（拒绝路径分隔符、
  `..`、点开头、空名），再断言 `目标目录.resolve().parent == 父目录.resolve()`。
  `包id = "x/../../../evil"` 这类构造在拼路径后立刻被拒，不可能逃出存储目录。
  这是**唯一一处**安装目标判定（`校验安装目标目录`），发布链与安装实现共用，
  不再各拼各判。
- 替换不再是「先删后改」：旧目标先 `os.rename` 成备份（改名不丢数据）→ 新目录
  就位 → 第二步失败即把备份改名还原旧版；只有替换成功后才丢弃备份。
  照搬同仓 平台客户端制品._原子写入安装目录（:419-428）的同款三段式，
  不自创第二套实现。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path

from 支持库.后端.系统核心支持库.路径安全 import 校验文件名


def 校验安装目标目录(目标目录, 受控目录=None) -> tuple[bool, str]:
    """判定安装目标是否为受控父目录下的单层合法目录（包id）。

    唯一判定入口：安装实现（安装制品）与发布链（统一入口.签名与发布）
    共用这一处，避免同一事两套口径。判定不看文件系统权限、只判形态：
    ①目录名必须是合法单层名（无分隔符/无 `..`/非点开头/非空）；
    ②路径**任何一段**都不得是 `..` 或 `.`——只比"解析后是否父目录子项"是挡不住的：
       `已激活/x/../../../evil` 的父路径本身就被 `..` 抬到了存储目录之外，
       解析后它照样是（那个已经跑偏的）父目录的直接子项（2026-09-17 实测踩坑）；
    ③解析后必须仍是父目录的直接子项（挡符号链接归位异常）；
    ④给了 `受控目录` 时，解析后的父目录必须**等于**该受控目录（拼路径处用）。
    """
    路径 = Path(目标目录)
    名字结果 = 校验文件名(路径.name)
    if not 名字结果.成功:
        return False, f"包id 非法: {名字结果.错误说明}"
    if not 名字结果.值.get("通过"):
        return False, f"包id 非法: {名字结果.值.get('原因', '')}"
    段表 = 路径.parts[1:] if 路径.is_absolute() else 路径.parts
    for 段 in 段表:
        if 段 in ("..", "."):
            return False, f"安装目标含目录跳转段（. / ..）: {路径}"
    父目录 = 路径.parent.resolve()
    实际目录 = 路径.resolve()
    if 实际目录.parent != 父目录:
        return False, f"安装目标未归位到父目录直接子项: {路径}"
    if 受控目录 is not None:
        根目录 = Path(受控目录).resolve()
        if 实际目录.parent != 根目录:
            return False, f"安装目标越出受控目录 {根目录}: {实际目录}"
    return True, ""


class 安装能力:
    """安装能力：安装制品到目标目录，全程防篡改。"""

    def 安装制品(self, *, 制品摘要: str, 目标目录: Path) -> tuple[bool, str]:
        """安装候选：临时目录复制 → 安装前后都校验 → 备份/替换/失败还原。

        不能把被篡改内容复制出去：安装前校验失败立即中止。
        替换失败必须还原旧版：旧版先改名备份，绝不先删。
        """
        制品 = self.状态.读取记录("制品", "制品摘要", 制品摘要)
        if 制品 is None:
            return False, "制品不存在"
        目标目录 = Path(目标目录)
        # 路径形态判定先于一切磁盘操作与签名计算：拼路径之后立刻挡目录逃逸
        目标通过, 目标原因 = 校验安装目标目录(目标目录)
        if not 目标通过:
            return False, f"安装被拒: {目标原因}"
        # 安装前校验（签名 + 磁盘一致性）
        有效, 消息 = self.校验签名(制品摘要=制品摘要)
        if not 有效:
            return False, f"安装被拒: {消息}"
        源目录 = self.制品根目录 / 制品摘要
        临时目标 = 目标目录.parent / f".安装临时_{uuid.uuid4().hex[:8]}"
        备份 = 目标目录.parent / f".安装备份_{uuid.uuid4().hex[:8]}"
        # 备份只作旧版还原依据：仅当旧目标改名为备份后才会存在
        已备份 = False
        临时目标.mkdir(parents=True)
        try:
            for 文件 in 源目录.rglob("*"):
                if 文件.is_file() and 文件.name != "物料清单.json":
                    相对 = 文件.relative_to(源目录)
                    目标文件 = 临时目标 / 相对
                    目标文件.parent.mkdir(parents=True, exist_ok=True)
                    目标文件.write_bytes(文件.read_bytes())
                    模式 = json.loads(制品["文件清单"]).get(str(相对), {}).get("模式")
                    if 模式 is not None:
                        目标文件.chmod(int(模式) & 0o7777)
            # 安装后再次校验磁盘摘要（防复制过程篡改）
            for 路径, 摘要信息 in json.loads(制品["文件清单"]).items():
                实际 = hashlib.sha256((临时目标 / 路径).read_bytes()).hexdigest()
                if 实际 != 摘要信息["sha256"]:
                    raise RuntimeError(f"安装后校验失败: {路径}")
            # 原子替换三段式（照搬同仓 平台客户端制品._原子写入安装目录:419-428）：
            # 旧目录先改名备份 → 新目录就位 → 失败即把备份改名还原。
            # 禁止先 rmtree：rmtree 与 rename 之间中断会让 已激活/<包id> 彻底消失。
            if 目标目录.exists():
                os.rename(目标目录, 备份)
                已备份 = True
            try:
                os.rename(临时目标, 目标目录)
            except OSError:
                if 备份.exists() and not 目标目录.exists():
                    os.rename(备份, 目标目录)
                    已备份 = False
                raise
        except Exception as 错误:
            shutil.rmtree(临时目标, ignore_errors=True)
            # 还原未完成时保留备份目录：旧版仍可人工恢复，不让旧版彻底消失
            return False, f"安装失败: {错误}" + (f"（旧版已备份于 {备份}）" if 已备份 else "")
        # 新目录已就位：旧版备份不再是回滚依据（回滚走 发布管理.回滚），丢弃
        if 已备份 and 备份.exists():
            shutil.rmtree(备份, ignore_errors=True)
        self.状态.条件更新("制品", {"状态": "已安装"}, "制品摘要=?", (制品摘要,))
        return True, f"已安装到 {目标目录}"
