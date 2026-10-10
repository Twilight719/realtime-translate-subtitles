# -*- coding: utf-8 -*-
"""验证 OCR 弹窗颜色跟随字幕颜色设置。"""
import os
import sys

sys.path.insert(0, r"D:\翻译插件")

import PyQt5
from PyQt5.QtCore import QCoreApplication, QRect

QCoreApplication.addLibraryPath(
    os.path.join(os.path.dirname(PyQt5.__file__), "Qt5", "plugins")
)

from PyQt5.QtGui import QGuiApplication
from PyQt5.QtWidgets import QApplication

from app.ocr_tool import OcrResultPopup

app = QApplication([])

SRC = "君は変わらないね"
ZH = "你还是没变呢"

# 模拟用户把字幕颜色改成 译文青色 + 原文粉色
p = OcrResultPopup(
    SRC, ZH, QRect(100, 100, 200, 100),
    {"display_mode": "both", "font_size": 15, "bg_alpha": 235,
     "zh_color": "#00FFFF", "src_color": "#FF69B4", "duration_ms": 0},
)
p.move(500, 300)
p.show()
app.processEvents()

pix = QGuiApplication.primaryScreen().grabWindow(0, 480, 280, 500, 200)
print("saved:", pix.save(r"D:\翻译插件\tools\ocr_colors.png", "PNG"))
p.close()
print("done")
