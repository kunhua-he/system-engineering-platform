"""数据类中文门面定向测试：证明它与标准库 dataclasses **逐字等价**。

口径（平台铁律）：中文门面只做可读性收口，**不改变任何语义**。故本文件的核心断言
一律是「同一声明用中文门面写 与 用标准库写，结果必须一致」——不是「看起来能跑」。

注意本文件自身是测试代码，允许使用标准库对照写法（这正是它的职责）。
"""

from __future__ import annotations

import dataclasses
import os
import sys
import unittest

根 = "/Users/hekunhua/Documents/Agent/PHP/系统工程平台"
if 根 not in sys.path:
    sys.path.insert(0, 根)
os.environ.pop("PYTHONPATH", None)

from 公共契约.基础类型.数据类 import (  # noqa: E402
    不可变数据类,
    字段,
    字段们,
    是数据类,
    数据类,
    转字典,
)


class 测试裸用等价(unittest.TestCase):
    """@数据类 与 @dataclass 等价。"""

    def test_实例化与默认值一致(self):
        @数据类
        class 中文版:
            名称: str
            年龄: int = 0

        @dataclasses.dataclass
        class 标准版:
            名称: str
            年龄: int = 0

        甲, 乙 = 中文版("甲", 3), 标准版("甲", 3)
        self.assertEqual(甲.名称, 乙.名称)
        self.assertEqual(甲.年龄, 乙.年龄)

    def test_相等语义一致(self):
        @数据类
        class 中文版:
            值: int

        @dataclasses.dataclass
        class 标准版:
            值: int

        # 与**标准库 dataclasses** 逐项对照才是真测「等价语义」：
        # 原写法 `assertEqual(中文版(1), 中文版(1))` 是**恒真断言**
        # （同一表达式两侧），被测试伪装门禁判「规则3·恒真断言」拦下 —— 这是真判定，按此改正。
        self.assertEqual(中文版(1) == 中文版(1), 标准版(1) == 标准版(1))
        self.assertEqual(中文版(1) == 中文版(2), 标准版(1) == 标准版(2))
        self.assertNotEqual(中文版(1), 中文版(2))
        # repr 的**格式**对照（类名必然不同，只比字段段）
        self.assertEqual(repr(中文版(1)).split("(", 1)[1], repr(标准版(1)).split("(", 1)[1])

    def test_打印与字段清单一致(self):
        @数据类
        class 中文版:
            甲: int
            乙: str = "x"

        @dataclasses.dataclass
        class 标准版:
            甲: int
            乙: str = "x"

        # 标准库 repr 形如 `<模块.类名(甲=1, 乙='x')>`：类名本来就不同，
        # 故只比「字段=值」那一段（门面不参与类名与 repr 格式）。
        self.assertEqual(repr(中文版(1)).split("(", 1)[1], repr(标准版(1)).split("(", 1)[1])
        self.assertEqual([f.name for f in 字段们(中文版)], [f.name for f in dataclasses.fields(标准版)])

    def test_是被识别为数据类(self):
        @数据类
        class 中文版:
            值: int

        self.assertTrue(是数据类(中文版))
        self.assertTrue(dataclasses.is_dataclass(中文版))


class 测试不可变等价(unittest.TestCase):
    """@数据类(不可变=True) 与 @不可变数据类 都等价 @dataclass(frozen=True)。"""

    def test_不可变参数生效(self):
        @数据类(不可变=True)
        class 中文版:
            值: int

        实例 = 中文版(1)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            实例.值 = 2

    def test_不可变简写生效(self):
        @不可变数据类
        class 中文版:
            值: int

        with self.assertRaises(dataclasses.FrozenInstanceError):
            中文版(1).值 = 2

    def test_简写与带参写法等价(self):
        @不可变数据类
        class 甲:
            值: int

        @数据类(不可变=True)
        class 乙:
            值: int

        # 标准库 __eq__ 要求 `other.__class__ is self.__class__`（同类才相等），
        # 甲乙是两个类，故比「类参数 + 字段清单」而不是比实例相等。
        甲参, 乙参 = 甲.__dataclass_params__, 乙.__dataclass_params__
        self.assertEqual(甲参.frozen, 乙参.frozen)
        self.assertEqual(甲参.eq, 乙参.eq)
        self.assertEqual([f.name for f in 字段们(甲)], [f.name for f in 字段们(乙)])
        self.assertEqual(repr(甲(1)).split("(", 1)[1], repr(乙(1)).split("(", 1)[1])

    def test_中文参数与英文原名同结果(self):
        """两套写法不得得到不同结果（兼容既有英文写法）。"""

        @数据类(不可变=True)
        class 中文参数:
            值: int

        @数据类(frozen=True)  # type: ignore[call-arg]
        class 英文参数:
            值: int

        self.assertEqual(
            中文参数.__dataclass_params__.frozen, 英文参数.__dataclass_params__.frozen
        )


class 测试字段等价(unittest.TestCase):
    """字段() 三种写法都与 dataclasses.field 等价。"""

    def test_带默认值(self):
        @数据类
        class 中文版:
            值: int = 字段(默认值=7)

        self.assertEqual(中文版().值, 7)

    def test_默认工厂(self):
        @数据类
        class 中文版:
            表: list = 字段(默认工厂=list)

        self.assertEqual(中文版().表, [])
        self.assertIsNot(中文版().表, 中文版().表)

    def test_空字段声明(self):
        @数据类
        class 中文版:
            值: int = 字段()

        self.assertEqual(中文版(5).值, 5)

    def test_默认值_None_与没给默认值必须区分(self):
        """哨兵的意义：给了 None 作默认值 ≠ 没给默认值。"""

        @数据类
        class 中文版:
            值: object = 字段(默认值=None)

        self.assertIsNone(中文版().值)
        self.assertIn("值", {f.name for f in 字段们(中文版)})

    def test_三写法与标准库逐字一致(self):
        @数据类
        class 中文版:
            甲: int = 字段(默认值=1)
            乙: list = 字段(默认工厂=list, 比较=False)

        @dataclasses.dataclass
        class 标准版:
            甲: int = dataclasses.field(default=1)
            乙: list = dataclasses.field(default_factory=list, compare=False)

        中字段 = {f.name: (f.default, f.compare) for f in 字段们(中文版)}
        标字段 = {f.name: (f.default, f.compare) for f in dataclasses.fields(标准版)}
        self.assertEqual(中字段, 标字段)


class 测试只读小件等价(unittest.TestCase):
    """转字典 等直通别名与标准库一致。"""

    def test_转字典一致(self):
        @数据类
        class 中文版:
            值: int
            表: list = 字段(默认工厂=list)

        @dataclasses.dataclass
        class 标准版:
            值: int
            表: list = dataclasses.field(default_factory=list)

        self.assertEqual(转字典(中文版(1)), dataclasses.asdict(标准版(1)))


class 测试误用必须报错(unittest.TestCase):
    """裸用带参数要报错（标准库同样报错），不能静默吞掉参数。"""

    def test_裸用带参数报错(self):
        with self.assertRaises(TypeError):
            数据类(object(), 不可变=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
