import json
import tempfile
import unittest
from pathlib import Path

根目录 = Path(__file__).resolve().parents[2]
import sys
if str(根目录) not in sys.path:
    sys.path.insert(0, str(根目录))

from 开发工具.轻代码前端编辑器.页面模型 import 校验页面, _读取能力目录
from 开发工具.轻代码前端编辑器.编译页面 import 编译


def 页面(组件列表):
    return {"页面id": "主页", "标题": "测试", "路由": "/", "组件列表": 组件列表}


class 测试页面模型编译(unittest.TestCase):
    def test_模板能力不进入页面能力目录(self):
        self.assertNotIn("_模板.示例能力", _读取能力目录())

    def test_模板能力绑定_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "属性能力不存在"):
            校验页面(页面([{
                "组件id": "按钮", "对象id": "按钮", "类型": "按钮",
                "属性": {"能力id": "_模板.示例能力"},
            }]))

    def test_未知组件阻断(self):
        with self.assertRaisesRegex(ValueError, "未知组件"):
            校验页面(页面([{"组件id": "甲", "对象id": "甲", "类型": "不存在", "属性": {}}]))

    def test_重复组件和对象阻断(self):
        项 = {"组件id": "甲", "对象id": "甲对象", "类型": "按钮", "属性": {}}
        with self.assertRaisesRegex(ValueError, "组件id重复"):
            校验页面(页面([项, dict(项, 对象id="乙对象")]))
        with self.assertRaisesRegex(ValueError, "对象id重复"):
            校验页面(页面([项, dict(项, 组件id="乙")]))

    def test_父组件必须存在且为容器(self):
        with self.assertRaisesRegex(ValueError, "父组件不存在"):
            校验页面(页面([{"组件id": "甲", "对象id": "甲", "类型": "按钮", "父组件id": "丙", "属性": {}}]))
        with self.assertRaisesRegex(ValueError, "不是容器"):
            校验页面(页面([
                {"组件id": "甲", "对象id": "甲", "类型": "按钮", "属性": {}},
                {"组件id": "乙", "对象id": "乙", "类型": "按钮", "父组件id": "甲", "属性": {}},
            ]))

    def test_页面编译输出规范树(self):
        with tempfile.TemporaryDirectory() as 临时:
            输出 = Path(临时) / "制品.json"
            源 = Path(临时) / "源.json"
            源.write_text(json.dumps(页面([
                {"组件id": "容器", "对象id": "容器", "类型": "容器", "属性": {}},
                {"组件id": "按钮", "对象id": "按钮", "类型": "按钮", "父组件id": "容器", "属性": {}, "事件": ["点击"]},
            ]), ensure_ascii=False), encoding="utf-8")
            结果 = 编译(源, 输出)
            self.assertEqual(结果["页面"]["组件列表"][1]["父组件id"], "容器")
            self.assertEqual(结果["页面"]["组件列表"][1]["事件"][0]["名称"], "点击")

    def test_事件能力必须存在且不得重复(self):
        基础 = {"组件id": "按钮", "对象id": "按钮", "类型": "按钮", "属性": {}}
        with self.assertRaisesRegex(ValueError, "事件能力不存在"):
            校验页面(页面([dict(基础, 事件=[{"名称": "点击", "能力id": "不存在.能力"}])]))
        with self.assertRaisesRegex(ValueError, "重复绑定事件"):
            校验页面(页面([dict(基础, 事件=["点击", "点击"])]))

    def test_事件能力进入编译依赖(self):
        with tempfile.TemporaryDirectory() as 临时:
            输出 = Path(临时) / "制品.json"
            源 = Path(临时) / "源.json"
            源.write_text(json.dumps(页面([{
                "组件id": "按钮", "对象id": "按钮", "类型": "按钮", "属性": {},
                "事件": [{"名称": "点击", "能力id": "数据操作支持库.文本处理.统计长度"}],
            }]), ensure_ascii=False), encoding="utf-8")
            结果 = 编译(源, 输出)
            self.assertEqual(结果["能力依赖"], ["数据操作支持库.文本处理.统计长度"])


if __name__ == "__main__":
    unittest.main()
