# -*- coding: utf-8 -*-
"""验证字幕窗点击穿透：Win32 样式 + WindowFromPoint 命中 + 渲染是否正常。

截图写到系统临时目录（不再往仓库里丢文件，避免被 `git add -A` 误提交）。
"""
import ctypes
import os
import sys
import tempfile
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

# 渲染验证：截取窗口区域。截图只写系统临时目录；临时目录不可写或解析到项目目录时跳过，
# 绝不往仓库里丢文件（否则会被 `git add -A` 误提交）。
_proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_tmp_dir = os.environ.get("TEMP") or os.environ.get("TMP") or tempfile.gettempdir()
out = None
if not os.path.abspath(_tmp_dir).lower().startswith(os.path.abspath(_proj_root).lower()):
    try:
        _probe = os.path.join(_tmp_dir, ".rts_write_probe")
        with open(_probe, "w", encoding="utf-8") as f:
            f.write("probe")
        os.remove(_probe)
        out = os.path.join(_tmp_dir, "rts_through_render.png")
    except OSError:
        out = None
if out is None:
    print("渲染截图：系统临时目录不可用，跳过（不影响结论）")
else:
    pix = QGuiApplication.primaryScreen().grabWindow(0, w.x() - 10, w.y() - 10, 520, 160)
    print("渲染截图:", out, "→", pix.save(out, "PNG"))

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
