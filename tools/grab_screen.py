"""截全屏保存到 tools/screen_dbg.png 供检查。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["QT_QPA_PLATFORM"] = ""  # 真实屏幕

import main  # noqa: F401

import PyQt5
from PyQt5.QtCore import QCoreApplication
from PyQt5.QtWidgets import QApplication

QCoreApplication.addLibraryPath(
    os.path.join(os.path.dirname(PyQt5.__file__), "Qt5", "plugins")
)
app = QApplication([])
from PyQt5.QtGui import QGuiApplication

screen = QGuiApplication.primaryScreen()
pix = screen.grabWindow(0)
out = os.path.abspath("tools/screen_dbg.png")
pix.save(out, "PNG")
print("saved", out, pix.width(), pix.height())
