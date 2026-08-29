"""自检睡：超长睡眠用于触发超时终止。"""
import time
import unittest


class 睡眠测试(unittest.TestCase):
    def test_长睡(self) -> None:
        time.sleep(120)


if __name__ == "__main__":
    unittest.main()
