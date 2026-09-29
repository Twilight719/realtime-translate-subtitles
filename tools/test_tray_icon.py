# -*- coding: utf-8 -*-
"""离屏渲染托盘图标两种状态，验证 tray.py 改动效果。"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 与 main.py 一致：显式注册 Qt 插件路径
import PyQt5 as _PyQt5
from PyQt5.QtCore import QCoreApplication

QCoreApplication.addLibraryPath(
    os.path.join(os.path.dirname(_PyQt5.__file__), "Qt5", "plugins")
)

from PyQt5.QtWidgets import QApplication

app = QApplication([])

from app.tray import _make_icon

_make_icon("#4CAF50").pixmap(48, 48).save("assets/_tray_running.png")
_make_icon("#888888").pixmap(48, 48).save("assets/_tray_stopped.png")
print("tray icons rendered")
