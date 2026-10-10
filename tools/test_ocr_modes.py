# -*- coding: utf-8 -*-
"""验证 OCR 弹窗三种显示模式的渲染效果，截图检查。"""
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

SRC = "君は<変わらない>ね & これからも"  # 含 HTML 特殊字符，验证转义
ZH = "你还是没变呢，今后也是"

pops = []
for i, mode in enumerate(["both", "zh", "src"]):
    p = OcrResultPopup(
        SRC, ZH, QRect(100, 100, 200, 100),
        {"display_mode": mode, "font_size": 15, "bg_alpha": 235, "duration_ms": 0},
    )
    p.move(420, 200 + i * 150)  # 竖排错开
    p.show()
    pops.append(p)
app.processEvents()

pix = QGuiApplication.primaryScreen().grabWindow(0, 400, 180, 700, 560)
ok = pix.save(r"D:\翻译插件\tools\ocr_modes.png", "PNG")
print("screenshot saved:", ok)

for p in pops:
    p.close()
print("done")
