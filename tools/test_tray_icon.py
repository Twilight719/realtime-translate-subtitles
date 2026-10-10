# -*- coding: utf-8 -*-
"""离屏渲染托盘图标两种状态，验证 tray.py 改动效果。"""
import os
import sys
import tempfile

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

# 写到系统临时目录：测试产物不进仓库（assets/ 不在 .gitignore 里，容易被 git add -A 误提交）。
# 临时目录不可写、或解析到项目目录时直接跳过，绝不往仓库里丢文件。
_proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_tmp_dir = os.environ.get("TEMP") or os.environ.get("TMP") or tempfile.gettempdir()
_out_dir = None
if not os.path.abspath(_tmp_dir).lower().startswith(os.path.abspath(_proj_root).lower()):
    try:
        _probe = os.path.join(_tmp_dir, ".rts_write_probe")
        with open(_probe, "w", encoding="utf-8") as f:
            f.write("probe")
        os.remove(_probe)
        _out_dir = _tmp_dir
    except OSError:
        _out_dir = None
for _name, _color in (("rts_tray_running.png", "#4CAF50"), ("rts_tray_stopped.png", "#888888")):
    if _out_dir is None:
        print("系统临时目录不可用，跳过:", _name)
        continue
    _path = os.path.join(_out_dir, _name)
    print("saved:", _make_icon(_color).pixmap(48, 48).save(_path, "PNG"), _path)
