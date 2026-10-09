# -*- coding: utf-8 -*-
"""验证字幕窗点击穿透：Win32 样式 + WindowFromPoint 命中 + 渲染是否正常。"""
import ctypes
import os
import sys
from ctypes import wintypes

sys.path.insert(0, r"D:\翻译插件")

import PyQt5
from PyQt5.QtCore import QCoreApplication, QTimer

QCoreApplication.addLibraryPath(
    os.path.join(os.path.dirname(PyQt5.__file__), "Qt5", "plugins")
)

from PyQt5.QtGui import QGuiApplication
from PyQt5.QtWidgets import QApplication

from app.subtitle_window import SubtitleWindow

app = QApplication([])
user32 = ctypes.windll.user32

w = SubtitleWindow({"click_through": True, "x": 300, "y": 300, "width": 500})
w.update_text("test source line", "测试字幕穿透渲染")
w.show()
app.processEvents()

own = int(w.winId())
style = user32.GetWindowLongPtrW(wintypes.HWND(own), -20)
print("exstyle:", hex(style), "| WS_EX_TRANSPARENT:", bool(style & 0x20), "| LAYERED:", bool(style & 0x80000))

pt = wintypes.POINT(w.x() + 250, w.y() + 30)
hit = user32.WindowFromPoint(pt)
print("穿透开启  WindowFromPoint:", hit, "→", "PASS" if hit != own else "FAIL")

# 渲染验证：截取窗口区域
pix = QGuiApplication.primaryScreen().grabWindow(0, w.x() - 10, w.y() - 10, 520, 160)
pix.save(r"D:\翻译插件\tools\through_render.png", "PNG")

# 关闭穿透（模拟拖动模式）→ 应该能命中字幕窗
w.click_through = False
w._apply_through()
app.processEvents()
hit2 = user32.WindowFromPoint(pt)
print("穿透关闭  WindowFromPoint:", hit2, "→", "PASS" if hit2 == own else "FAIL")

# 再开回来
w.click_through = True
w._apply_through()
app.processEvents()
hit3 = user32.WindowFromPoint(pt)
print("穿透再开  WindowFromPoint:", hit3, "→", "PASS" if hit3 != own else "FAIL")

QTimer.singleShot(0, app.quit)
app.exec_()
