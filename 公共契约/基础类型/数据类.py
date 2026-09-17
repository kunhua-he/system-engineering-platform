"""基础类型：中文数据类门面（标准库 ``dataclasses`` 的唯一中文入口）。

**为什么有这一层**：平台铁律是「全中文命名，英文只留给语言关键字/框架标准属性」。
``dataclass`` 属标准库，保留英文合规，但调用点满屏 ``from dataclasses import``
对读者（尤其非程序员）不友好。这里把英文入口**收口一次**，业务代码只写中文
——与 ``公共契约/运行时/进程终止.py`` 收口 ``os.killpg``、``平台适配.py`` 收口
``sys.platform`` 是同一做法：**英文只留在最底层一处**。

用法（与标准库等价，不改变任何语义）：

```python
from 公共契约.基础类型.数据类 import 数据类, 字段

@数据类
class 用户:
    名称: str
    年龄: int = 0

@数据类(不可变=True)      # 等价于 @dataclass(frozen=True)
class 配置:
    路径: str
    开关: bool = 字段(default=False)
```

**为什么只做别名、不重写实现**：数据类实例化、比较、哈希、替换、序列化这些语义
由标准库保证；重写一份必然与标准库漂移（哲学 1.3 结果唯一即收口）。中文门面的价值
在**可读性**，不在替换实现。参数名做中英映射，英文原名**原样透传**（兼容既有写法，
两套写法不会得到不同结果）。
"""

from __future__ import annotations

from dataclasses import (
    Field as _Field,
    asdict as _asdict,
    astuple as _astuple,
    dataclass as _dataclass,
    field as _field,
    fields as _fields,
    is_dataclass as _is_dataclass,
    replace as _replace,
)
from typing import Any
from 公共契约.基础类型.逻辑类型 import 真, 假

#: 中文参数名 → 标准库参数名（只映射本平台用得上的那几个；英文原名原样透传）
参数名对照 = {
    "不可变": "frozen",
    "相等": "eq",
    "顺序": "order",
    "只写": "kw_only",
    "槽": "slots",
    "初始化": "init",
    "打印": "repr",
    "不安全哈希": "unsafe_hash",
    "匹配参数": "match_args",
}

#: 字段参数的额外对照（`字段()` 专用）
字段参数名对照 = {
    **参数名对照,
    "默认值": "default",
    "默认工厂": "default_factory",
    "比较": "compare",
    "元数据": "metadata",
}

#: 「没给默认值」的哨兵：与「给了 None 作默认值」必须区分开
_未给 = object()


def _译参数(参数: dict[str, Any]) -> dict[str, Any]:
    """把中文参数名译成标准库参数名；未识别的键原样透传（英文原名合法）。"""
    return {参数名对照.get(键, 键): 值 for 键, 值 in 参数.items()}


def _译字段参数(参数: dict[str, Any]) -> dict[str, Any]:
    """字段参数的同一口径译本。"""
    return {字段参数名对照.get(键, 键): 值 for 键, 值 in 参数.items()}


def 数据类(目标: Any = None, /, **参数: Any) -> Any:
    """中文数据类装饰器。两种用法都与标准库 ``dataclass`` 等价：

    - ``@数据类``                —— 裸用，直接装饰；
    - ``@数据类(不可变=True)``   —— 带参数调用，返回装饰器。

    参数名支持中文（见 ``参数名对照``），也接受标准库的英文原名。
    """
    if 目标 is not None:
        # 裸用：此时 目标 就是被装饰的类，不允许再带参数（标准库同样会报 TypeError）
        if 参数:
            raise TypeError("数据类：裸用时不允许带参数，请写 @数据类(参数=值)")
        return _dataclass(目标)
    return lambda 类: _dataclass(类, **_译参数(参数))


def 不可变数据类(目标: Any = None, /, **参数: Any) -> Any:
    """``@数据类(不可变=True)`` 的简写：不可变（frozen）数据类。

    单独给出这个名字，是因为「不可变」在本平台是**默认倾向**（结果、契约这类值对象
    都要求不可变），写 ``@不可变数据类`` 比 ``@数据类(不可变=True)`` 更短也更难写错。
    """
    return 数据类(目标, 不可变=真, **参数) if 目标 is None else _dataclass(目标, frozen=True)


def 字段(默认值: Any = _未给, /, **参数: Any) -> Any:
    """字段声明（等价 ``dataclasses.field``）。

    三种写法都等价：``字段()``、``字段(默认值=…)``、``字段(默认工厂=…)``；
    参数名同样中英通用（``默认值``/``default``、``默认工厂``/``default_factory``）。
    """
    if 默认值 is _未给:
        return _field(**_译字段参数(参数))
    return _field(default=默认值, **_译字段参数(参数))


#: 以下为只读小件的直通别名：名字中文、语义与标准库逐字一致，不包一层逻辑。
字段们 = _fields
字段类型 = _Field
转字典 = _asdict
转元组 = _astuple
替换字段 = _replace
是数据类 = _is_dataclass

__all__ = [
    "数据类",
    "不可变数据类",
    "字段",
    "字段们",
    "字段类型",
    "转字典",
    "转元组",
    "替换字段",
    "是数据类",
    "参数名对照",
]
