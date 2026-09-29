"""PyInstaller 自定义运行时钩子（先于 PyQt5 的运行时钩子执行）。

PyQt5 的运行时钩子会 import PyQt5.QtCore 来写入 qt.conf；而 Qt 先于
onnxruntime 加载时，后者初始化会访问冲突（段错误；实测 Qt 之后再加载
sentencepiece 也会崩，但只要 onnxruntime 最先进程就全部安全）。
此钩子抢先把 onnxruntime 加载好。
"""

import onnxruntime  # noqa: F401
