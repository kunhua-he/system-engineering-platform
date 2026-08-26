"""文件系统补充原子能力实现（不对外暴露，只经包级中文入口调用）。

职责：文件搜索/压缩解压/权限/追加写入（参考易语言文件读写类模块）。
纯标准库，不做业务逻辑。
"""

from __future__ import annotations

import fnmatch
import os
import zipfile

from 公共契约.基础类型.结果类型 import 结果


def 搜索文件(目录: str = None, 通配符: str = None, 递归: bool = None) -> 结果:
    """按通配符搜索文件。返回 {文件数, 文件列表}。"""
    if not isinstance(目录, str) or not 目录.strip():
        return 结果.失败("参数不合法", "目录必须是非空字符串", 来源="文件系统")
    if not isinstance(通配符, str) or not 通配符.strip():
        return 结果.失败("参数不合法", "通配符必须是非空字符串", 来源="文件系统")
    if not os.path.isdir(目录):
        return 结果.失败("目录不存在", f"目录不存在: {目录}", 来源="文件系统")
    文件列表 = []
    if 递归:
        for 根, 子目录, 文件 in os.walk(目录):
            for f in 文件:
                if fnmatch.fnmatch(f, 通配符):
                    文件列表.append(os.path.join(根, f))
    else:
        try:
            for f in os.listdir(目录):
                if fnmatch.fnmatch(f, 通配符):
                    完整路径 = os.path.join(目录, f)
                    if os.path.isfile(完整路径):
                        文件列表.append(完整路径)
        except OSError as 错误:
            return 结果.失败("读取失败", str(错误), 来源="文件系统")
    return 结果.成功结果({"文件数": len(文件列表), "文件列表": sorted(文件列表)})


def 追加写入(路径: str = None, 内容: str = None) -> 结果:
    """追加文本到文件末尾。返回 {路径, 追加字节数}。"""
    if not isinstance(路径, str) or not 路径.strip():
        return 结果.失败("参数不合法", "路径必须是非空字符串", 来源="文件系统")
    if 内容 is None:
        return 结果.失败("参数不合法", "内容不能为空", 来源="文件系统")
    try:
        with open(路径, "a", encoding="utf-8") as f:
            字节数 = f.write(str(内容))
        return 结果.成功结果({"路径": 路径, "追加字节数": 字节数})
    except OSError as 错误:
        return 结果.失败("写入失败", str(错误), 来源="文件系统")


def 压缩文件(源路径: str = None, 目标路径: str = None) -> 结果:
    """压缩文件/目录为 zip。返回 {目标路径, 条目数}。"""
    if not isinstance(源路径, str) or not 源路径.strip():
        return 结果.失败("参数不合法", "源路径必须是非空字符串", 来源="文件系统")
    if not isinstance(目标路径, str) or not 目标路径.strip():
        return 结果.失败("参数不合法", "目标路径必须是非空字符串", 来源="文件系统")
    if not os.path.exists(源路径):
        return 结果.失败("源不存在", f"源不存在: {源路径}", 来源="文件系统")
    try:
        条目数 = 0
        with zipfile.ZipFile(目标路径, "w", zipfile.ZIP_DEFLATED) as 压缩包:
            if os.path.isfile(源路径):
                压缩包.write(源路径, os.path.basename(源路径))
                条目数 = 1
            else:
                for 根, 子目录, 文件 in os.walk(源路径):
                    for f in 文件:
                        完整路径 = os.path.join(根, f)
                        相对路径 = os.path.relpath(完整路径, os.path.dirname(源路径))
                        压缩包.write(完整路径, 相对路径)
                        条目数 += 1
        return 结果.成功结果({"目标路径": 目标路径, "条目数": 条目数})
    except Exception as 错误:
        return 结果.失败("压缩失败", str(错误), 来源="文件系统")


def 解压文件(源路径: str = None, 目标目录: str = None) -> 结果:
    """解压 zip 到目录。返回 {目标目录, 条目数}。"""
    if not isinstance(源路径, str) or not 源路径.strip():
        return 结果.失败("参数不合法", "源路径必须是非空字符串", 来源="文件系统")
    if not isinstance(目标目录, str) or not 目标目录.strip():
        return 结果.失败("参数不合法", "目标目录必须是非空字符串", 来源="文件系统")
    if not os.path.isfile(源路径):
        return 结果.失败("源不存在", f"源文件不存在: {源路径}", 来源="文件系统")
    try:
        os.makedirs(目标目录, exist_ok=True)
        with zipfile.ZipFile(源路径, "r") as 压缩包:
            for 成员 in 压缩包.infolist():
                # 防 zip 炸弹：路径穿越防护
                目标 = os.path.normpath(os.path.join(目标目录, 成员.filename))
                if not 目标.startswith(os.path.normpath(目标目录)):
                    return 结果.失败("解压失败", f"非法路径穿越: {成员.filename}", 来源="文件系统")
            压缩包.extractall(目标目录)
            条目数 = len(压缩包.infolist())
        return 结果.成功结果({"目标目录": 目标目录, "条目数": 条目数})
    except Exception as 错误:
        return 结果.失败("解压失败", str(错误), 来源="文件系统")


def 获取文件权限(路径: str = None) -> 结果:
    """获取文件权限。返回 {路径, 权限, 可读, 可写, 可执行}。"""
    if not isinstance(路径, str) or not 路径.strip():
        return 结果.失败("参数不合法", "路径必须是非空字符串", 来源="文件系统")
    if not os.path.exists(路径):
        return 结果.失败("路径不存在", f"路径不存在: {路径}", 来源="文件系统")
    try:
        权限 = oct(os.stat(路径).st_mode & 0o777)
        return 结果.成功结果({"路径": 路径, "权限": 权限,
                                "可读": os.access(路径, os.R_OK),
                                "可写": os.access(路径, os.W_OK),
                                "可执行": os.access(路径, os.X_OK)})
    except OSError as 错误:
        return 结果.失败("读取失败", str(错误), 来源="文件系统")