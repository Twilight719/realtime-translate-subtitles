"""OCR 接线冒烟测试：offscreen Qt 下实例化设置页/托盘/选区层，验证热键与信号接线。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import main  # noqa: F401  必须最先导入（onnxruntime→PyQt5 安全顺序）

import PyQt5
from PyQt5.QtCore import QCoreApplication, QRect
from PyQt5.QtWidgets import QApplication

QCoreApplication.addLibraryPath(
    os.path.join(os.path.dirname(PyQt5.__file__), "Qt5", "plugins")
)

app = QApplication([])

from app.ocr_tool import OcrResultPopup, SnipOverlay, pick_ocr_language
from app.settings_window import SettingsWindow
from app.tray import TrayIcon

cfg = main.load_config()
# 旧用户的 config.yaml 没有 hotkey_ocr，代码各处用 cfg.get(..., "alt+r") 兜底
print("config hotkey_ocr:", cfg.get("hotkey_ocr", "（旧配置缺省 → alt+r）"))

win = SettingsWindow(cfg, history_provider=lambda: [])
assert win.btn_hotkey_ocr.hotkey() == cfg.get("hotkey_ocr", "alt+r")
print("设置页 OCR 热键按钮 OK:", win.btn_hotkey_ocr.hotkey())

tray = TrayIcon(on_toggle=lambda: None, on_quit=lambda: None, on_ocr=lambda: None)
tray.set_ocr_hotkey("ctrl+shift+q")
print("托盘菜单 OK:", tray.action_ocr.text())

snip = SnipOverlay()
print("选区层 OK:", snip.geometry().width(), "x", snip.geometry().height())

popup = OcrResultPopup("テスト原文", "测试译文", QRect(100, 100, 300, 80))
print("结果弹窗 OK:", popup.width(), "x", popup.height())

lang = pick_ocr_language("ja")
print("OCR 语言选择 ja ->", lang)

# _on_apply 校验路径
win.btn_hotkey_ocr.setText("ctrl+shift+o")
win._on_apply()
assert cfg["hotkey_ocr"] == "ctrl+shift+o", cfg.get("hotkey_ocr")
print("_on_apply 保存 hotkey_ocr OK:", cfg["hotkey_ocr"])

print("SMOKE_OK")
