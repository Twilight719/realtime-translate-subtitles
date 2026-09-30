"""系统托盘图标：显示运行状态，提供启停与退出菜单。"""

import os

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt5.QtWidgets import QAction, QMenu, QSystemTrayIcon

ICON_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "icon.png"
)


def _make_icon(color):
    """应用图标 + 右下角状态点（颜色区分运行/停止）；图标缺失时退化为纯色圆点。"""
    pix = QPixmap(ICON_PATH)
    if pix.isNull():
        pix = QPixmap(32, 32)
        pix.fill(QColor(0, 0, 0, 0))
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(color))
        p.setPen(Qt.NoPen)
        p.drawEllipse(4, 4, 24, 24)
        p.end()
        return QIcon(pix)

    pix = pix.scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    # 状态点：深色描边 + 彩色圆点，放在右下角
    d = 18
    x, y = 48 - d - 1, 48 - d - 1
    p.setBrush(QColor("#17171d"))
    p.setPen(Qt.NoPen)
    p.drawEllipse(x - 3, y - 3, d + 6, d + 6)
    p.setBrush(QColor(color))
    p.drawEllipse(x, y, d, d)
    p.end()
    return QIcon(pix)


class TrayIcon(QSystemTrayIcon):
    def __init__(self, on_toggle, on_quit, on_settings=None, parent=None):
        super().__init__(_make_icon("#888888"), parent)
        self.setToolTip("实时翻译字幕（已停止）")

        # QAction 必须挂在 self 上，否则 Python 引用被回收后菜单项会消失
        self.action_toggle = QAction("开始 (Alt+T)", self)
        self.action_toggle.triggered.connect(on_toggle)
        self.action_settings = QAction("设置", self)
        if on_settings:
            self.action_settings.triggered.connect(on_settings)
        self.action_quit = QAction("退出", self)
        self.action_quit.triggered.connect(on_quit)

        menu = QMenu()
        menu.addAction(self.action_toggle)
        menu.addAction(self.action_settings)
        menu.addSeparator()
        menu.addAction(self.action_quit)
        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)
        self._on_toggle = on_toggle
        self._on_settings = on_settings
        self._running = False
        self._hotkey_label = "Alt+T"

    def set_hotkey(self, hotkey):
        """自定义热键后同步菜单里的提示文字。"""
        self._hotkey_label = "+".join(p.capitalize() for p in hotkey.split("+"))
        self._refresh_toggle_text()

    def _refresh_toggle_text(self):
        self.action_toggle.setText(
            f"{'停止' if self._running else '开始'} ({self._hotkey_label})"
        )

    def _on_activated(self, reason):
        # 双击打开设置主界面（符合大多数用户的直觉）
        if reason == QSystemTrayIcon.DoubleClick and self._on_settings:
            self._on_settings()

    def set_running(self, running):
        self._running = running
        if running:
            self.setIcon(_make_icon("#4CAF50"))
            self.setToolTip("实时翻译字幕（运行中）")
        else:
            self.setIcon(_make_icon("#888888"))
            self.setToolTip("实时翻译字幕（已停止）")
        self._refresh_toggle_text()
