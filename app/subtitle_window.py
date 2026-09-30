"""PyQt5 悬浮字幕窗：半透明置顶、可拖动、点击穿透、无语音时自动淡出。

三行结构（借鉴专业同传）：
  历史行 —— 上一句定稿译文（小而暗，常驻供读完）
  原文行 —— 当前句：定稿部分稳定白 + 未确认尾部灰色斜体滚动
  译文行 —— 当前句：定稿部分稳定黄 + 未确认尾部暗黄斜体滚动
"""

from html import escape

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget


def _stable_tail_html(stable, tail, stable_color, tail_color):
    html = f'<span style="color:{stable_color};">{escape(stable)}</span>'
    if tail:
        html += f' <span style="color:{tail_color}; font-style:italic;">{escape(tail)}</span>'
    return html


def _dim(hex_color, alpha=110):
    """把 #RRGGBB 变成同色的半透明 rgba() 字符串（未确认尾部用）。"""
    c = QColor(hex_color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{alpha})"


class SubtitleWindow(QWidget):
    # 预览/错误提示等简单文本更新（主线程外通过此信号安全调用）
    subtitle_ready = pyqtSignal(str, str)  # 原文, 译文

    def __init__(self, cfg=None):
        super().__init__()
        cfg = cfg or {}
        self.fade_ms = cfg.get("fade_ms", 5000)
        self.click_through = cfg.get("click_through", True)
        self._bg_alpha = cfg.get("bg_alpha", 140)
        self._drag_pos = None
        self._font_size = cfg.get("font_size", 22)
        self._last_final_zh = ""
        self._last_final_src = ""
        self._src_color = cfg.get("src_color", "#FFFFFF")
        self._zh_color = cfg.get("zh_color", "#FFE34D")
        self._display_mode = cfg.get("display_mode", "both")  # both / zh / src

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        if self.click_through:
            self.setAttribute(Qt.WA_TransparentForMouseEvents)

        self.label_history = QLabel("")
        self.label_history.setWordWrap(True)

        self.label_src = QLabel("")
        self.label_src.setWordWrap(True)

        self.label_zh = QLabel("")
        self.label_zh.setWordWrap(True)

        self._apply_fonts()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 10, 18, 10)
        layout.addWidget(self.label_history)
        layout.addWidget(self.label_src)
        layout.addWidget(self.label_zh)

        width = cfg.get("width", 700)
        self.setMinimumWidth(width)
        self.setMaximumWidth(width)
        self.move(cfg.get("x", 300), cfg.get("y", 800))

        self.subtitle_ready.connect(self._show_simple)
        self._apply_display_mode()

        # 淡出计时
        self._opacity = 1.0
        self._fade_timer = QTimer(self)
        self._fade_timer.setInterval(50)
        self._fade_timer.timeout.connect(self._fade_step)
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._fade_timer.start)

    def _apply_fonts(self):
        fs = self._font_size
        self.label_history.setFont(QFont("Microsoft YaHei", max(10, fs - 10)))
        self.label_history.setStyleSheet("color: rgba(255,255,255,110);")
        self.label_src.setFont(QFont("Microsoft YaHei", max(10, fs - 8)))
        self.label_zh.setFont(QFont("Microsoft YaHei", fs, QFont.Bold))

    # ---------- 上屏接口（须在 Qt 主线程调用） ----------

    def _apply_display_mode(self):
        """字幕内容模式：both=双语、zh=只译文、src=只原文。"""
        self.label_src.setVisible(self._display_mode != "zh")
        self.label_zh.setVisible(self._display_mode != "src")
        self.label_history.setVisible(self._display_mode != "src")

    def show_live(self, payload):
        """实时快照：定稿区稳定显示 + 尾部滚动修订。"""
        self.label_src.setText(
            _stable_tail_html(
                payload["src_stable"], payload["src_tail"],
                self._src_color, _dim(self._src_color),
            )
        )
        self.label_zh.setText(
            _stable_tail_html(
                payload["zh_stable"], payload["zh_tail"],
                self._zh_color, _dim(self._zh_color),
            )
        )
        self._present()

    def show_final(self, src, zh):
        """段落定稿：当前句完整版以稳定样式显示，上一句译文挪到历史行。"""
        if zh and zh != self._last_final_zh:
            self.label_history.setText(self._last_final_zh)
            self._last_final_zh = zh
        self.label_src.setText(f'<span style="color:{self._src_color};">{escape(src)}</span>')
        self.label_zh.setText(f'<span style="color:{self._zh_color};">{escape(zh)}</span>')
        self._present()

    def update_text(self, src, zh):
        """预览/提示用简单更新（不影响历史行）。"""
        self.subtitle_ready.emit(src, zh or "")

    def _show_simple(self, src, zh):
        self.label_src.setText(f'<span style="color:{self._src_color};">{escape(src)}</span>')
        self.label_zh.setText(f'<span style="color:{self._zh_color};">{escape(zh)}</span>')
        self._present()

    def _present(self):
        self.adjustSize()
        self._opacity = 1.0
        self.setWindowOpacity(1.0)
        self.show()
        self._fade_timer.stop()
        self._idle_timer.start(self.fade_ms)

    # ---------- 外观配置 ----------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(0, 0, 0, self._bg_alpha))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(self.rect(), 12, 12)

    def apply_config(self, cfg):
        """实时应用外观配置（字体/透明度/宽度/位置/穿透/淡出时间/内容模式）。"""
        self.fade_ms = cfg.get("fade_ms", self.fade_ms)
        self._bg_alpha = cfg.get("bg_alpha", self._bg_alpha)
        self._font_size = cfg.get("font_size", 22)
        self._src_color = cfg.get("src_color", self._src_color)
        self._zh_color = cfg.get("zh_color", self._zh_color)
        self._display_mode = cfg.get("display_mode", self._display_mode)
        self._apply_display_mode()
        self._apply_fonts()
        width = cfg.get("width", 700)
        self.setMinimumWidth(width)
        self.setMaximumWidth(width)

        through = cfg.get("click_through", True)
        if through != self.click_through:
            self.click_through = through
            self.setAttribute(Qt.WA_TransparentForMouseEvents, through)
            if self.isVisible():
                self.hide()
                self.show()

        self.move(cfg.get("x", 300), cfg.get("y", 800))
        self.adjustSize()
        self.update()

    # ---------- 其他行为 ----------

    def _fade_step(self):
        self._opacity -= 0.08
        if self._opacity <= 0:
            self._fade_timer.stop()
            self.hide()
            self._opacity = 1.0
        else:
            self.setWindowOpacity(self._opacity)

    def set_running(self, running):
        """启停反馈：停止时立即隐藏字幕。"""
        if not running:
            self._fade_timer.stop()
            self._idle_timer.stop()
            self.hide()

    def enter_drag_mode(self):
        """临时关闭点击穿透并显示字幕条，让用户用鼠标拖动定位。"""
        self._drag_saved_through = self.click_through
        self.click_through = False
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.update_text("Drag me to the position you like", "拖动我到想要的位置，完成后点“完成定位”")
        self._idle_timer.stop()
        self._fade_timer.stop()
        self.setWindowOpacity(1.0)

    def exit_drag_mode(self):
        """恢复点击穿透设置并隐藏，返回当前位置 (x, y)。"""
        self.click_through = getattr(self, "_drag_saved_through", self.click_through)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, self.click_through)
        self.hide()
        return self.x(), self.y()

    # 拖动（点击穿透关闭时生效）
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and not self.click_through:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
