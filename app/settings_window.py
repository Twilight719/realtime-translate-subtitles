"""设置主窗口：深色主题，侧边栏导航（主页 / 字幕外观 / 识别模型 / 翻译服务 / 日志）。"""

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .version import __version__

try:
    from .paths import base_dir
    from .hotkeys import parse_hotkey
    from .i18n import tr
    from . import i18n_strings  # noqa: F401  注册中英文映射
except ImportError:  # 直接运行本文件做界面预览时
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app.paths import base_dir
    from app.hotkeys import parse_hotkey
    from app.i18n import tr
    import app.i18n_strings  # noqa: F401

QSS = """
QMainWindow, QWidget { background: #1e1e26; color: #e6e6ea; font-family: "Microsoft YaHei"; font-size: __FS__px; }
QListWidget#sidebar { background: #17171d; border: none; font-size: __FS_SIDEBAR__px; outline: none; }
QListWidget#sidebar::item { padding: 14px 18px; color: #9a9aa5; }
QListWidget#sidebar::item:selected { background: #2d2d3a; color: #ffffff; border-left: 3px solid #4f8cff; }
QListWidget#sidebar::item:hover { color: #ffffff; }
QGroupBox { border: 1px solid #34343f; border-radius: 8px; margin-top: 14px; padding-top: 10px; font-weight: bold; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; color: #8ab4ff; }
QPushButton { background: #2d2d3a; border: none; border-radius: 6px; padding: 8px 16px; }
QPushButton:hover { background: #3a3a4c; }
QPushButton:pressed { background: #25252f; }
QPushButton#primary { background: #4f8cff; color: white; font-weight: bold; }
QPushButton#primary:hover { background: #6ba0ff; }
QPushButton#danger { background: #c0492f; color: white; }
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit {
    background: #17171d; border: 1px solid #34343f; border-radius: 6px; padding: 6px 8px;
    selection-background-color: #4f8cff;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: #4f8cff; }
QComboBox QAbstractItemView { background: #2d2d3a; selection-background-color: #4f8cff; }
QSlider::groove:horizontal { height: 6px; background: #34343f; border-radius: 3px; }
QSlider::handle:horizontal { width: 16px; height: 16px; margin: -5px 0; border-radius: 8px; background: #4f8cff; }
QSlider::sub-page:horizontal { background: #4f8cff; border-radius: 3px; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; }
QListWidget#orderList { background: #17171d; border: 1px solid #34343f; border-radius: 6px; }
QLabel#hint { color: #8a8a95; font-size: __FS_HINT__px; }
QLabel#statusDot { font-size: __FS_DOT__px; }
QPushButton#helpToggle { background: transparent; color: #8ab4ff; text-align: left; padding: 4px 0; border: none; }
QPushButton#helpToggle:hover { color: #a8c6ff; }
"""


def build_qss(fs=13):
    """按界面字号生成样式表：正文用 fs，侧边栏/状态点略大，提示文字略小。"""
    return (
        QSS.replace("__FS_SIDEBAR__", str(fs + 2))
        .replace("__FS_DOT__", str(fs + 5))
        .replace("__FS_HINT__", str(max(10, fs - 1)))
        .replace("__FS__", str(fs))
    )

class SliderSpin(QWidget):
    """拖动条 + 精确数值输入二合一控件，点右侧按钮切换显示模式，两者双向同步。"""

    valueChanged = pyqtSignal(int)

    def __init__(self, minimum, maximum, value, suffix="", step=1, parent=None):
        super().__init__(parent)
        self._suffix = suffix

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setSingleStep(step)
        self.slider.setValue(value)
        self.label = QLabel(f"{value} {suffix}".strip())
        self.label.setMinimumWidth(70)
        slider_page = QWidget()
        h = QHBoxLayout(slider_page)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.slider, 1)
        h.addWidget(self.label)

        self.spin = QSpinBox()
        self.spin.setRange(minimum, maximum)
        self.spin.setSingleStep(step)
        self.spin.setValue(value)
        self.spin.setSuffix(f" {suffix}" if suffix else "")

        self.stack = QStackedWidget()
        self.stack.addWidget(slider_page)
        self.stack.addWidget(self.spin)

        self.btn_mode = QPushButton("✎")
        self.btn_mode.setToolTip(tr("切换 拖动条 / 精确数值输入"))
        self.btn_mode.setFixedWidth(34)
        self.btn_mode.clicked.connect(self._toggle_mode)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack, 1)
        layout.addWidget(self.btn_mode)

        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)

    def _toggle_mode(self):
        self.stack.setCurrentIndex(1 - self.stack.currentIndex())

    def _from_slider(self, v):
        self.spin.blockSignals(True)
        self.spin.setValue(v)
        self.spin.blockSignals(False)
        self.label.setText(f"{v} {self._suffix}".strip())
        self.valueChanged.emit(v)

    def _from_spin(self, v):
        self.slider.blockSignals(True)
        self.slider.setValue(v)
        self.slider.blockSignals(False)
        self.label.setText(f"{v} {self._suffix}".strip())
        self.valueChanged.emit(v)

    def value(self):
        return self.slider.value()

    def setValue(self, v):
        self.slider.setValue(v)  # 会经 _from_slider 同步到 spin 并发出 valueChanged


DEFAULT_HOTKEY = "alt+t"
DEFAULT_HOTKEY_OCR = "ctrl+alt+r"


class HotkeyCaptureButton(QPushButton):
    """点击进入捕获状态，下一次按下的组合键成为新热键；Esc 取消。"""

    def __init__(self, hotkey=DEFAULT_HOTKEY, parent=None):
        super().__init__(hotkey, parent)
        self._capturing = False
        self._original = hotkey
        self.clicked.connect(self._begin_capture)

    def hotkey(self):
        return self.text().strip().lower()

    def _begin_capture(self):
        self._capturing = True
        self._original = self.text()
        self.setText(tr("请按下新热键…（Esc 取消）"))
        self.grabKeyboard()

    def _end_capture(self, text=None):
        self.releaseKeyboard()
        self._capturing = False
        self.setText(text if text else self._original)

    def keyPressEvent(self, e):
        if not self._capturing:
            super().keyPressEvent(e)
            return
        key = e.key()
        if key == Qt.Key_Escape:
            self._end_capture()
            return
        if key in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta):
            return  # 只按了修饰键，继续等完整组合
        name = self._key_name(key)
        if name is None:
            self._end_capture()
            QMessageBox.warning(self, tr("不支持的热键"), tr("只支持 字母 / 数字 / F1~F12 与 Ctrl/Alt/Shift/Win 的组合。"))
            return
        mods = e.modifiers()
        parts = []
        if mods & Qt.ControlModifier:
            parts.append("ctrl")
        if mods & Qt.AltModifier:
            parts.append("alt")
        if mods & Qt.ShiftModifier:
            parts.append("shift")
        if mods & Qt.MetaModifier:
            parts.append("win")
        if not parts:
            # 不带修饰键的裸键会劫持正常打字，必须组合使用
            self.setText(tr("需同时按住 Ctrl/Alt/Shift 之一，请重按…"))
            return
        parts.append(name)
        self._end_capture("+".join(parts))

    @staticmethod
    def _key_name(key):
        if Qt.Key_A <= key <= Qt.Key_Z:
            return chr(ord("a") + key - Qt.Key_A)
        if Qt.Key_0 <= key <= Qt.Key_9:
            return chr(ord("0") + key - Qt.Key_0)
        if Qt.Key_F1 <= key <= Qt.Key_F12:
            return f"f{key - Qt.Key_F1 + 1}"
        return None


def make_help_widget(lines):
    """可折叠的“各项说明”：一个切换按钮 + 默认隐藏的说明文本（不占地方）。"""
    container = QWidget()
    v = QVBoxLayout(container)
    v.setContentsMargins(0, 4, 0, 0)
    v.setSpacing(4)
    btn = QPushButton(tr("各项说明 ▾"))
    btn.setObjectName("helpToggle")
    btn.setCheckable(True)
    detail = QLabel("\n".join(lines))
    detail.setObjectName("hint")
    detail.setWordWrap(True)
    detail.setVisible(False)

    def _toggle(on):
        detail.setVisible(on)
        btn.setText(tr("各项说明 ▴") if on else tr("各项说明 ▾"))

    btn.toggled.connect(_toggle)
    v.addWidget(btn)
    v.addWidget(detail)
    return container


BACKENDS = {
    "youdao_web": (tr("有道翻译（在线）"), tr("国内直连，无需 key，质量良好")),
    "mymemory": (tr("MyMemory（在线）"), tr("免费无需 key，备用")),
    "google_web": (tr("Google 翻译（在线）"), tr("需要能访问 Google 的网络")),
    "llm_api": (tr("大模型 API"), tr("DeepSeek/豆包/GPT 等，口语质量最好，需填 key")),
    "nllb": (tr("NLLB 本地模型"), tr("离线兜底，无需网络，速度较慢")),
}


class SettingsWindow(QMainWindow):
    request_toggle = pyqtSignal()
    request_apply = pyqtSignal(dict)
    request_preview = pyqtSignal()
    request_drag_start = pyqtSignal()
    request_drag_end = pyqtSignal()
    request_live_preview = pyqtSignal(dict)  # 外观控件改动时实时预览
    request_check_update = pyqtSignal()  # “检查更新”按钮
    request_install_update = pyqtSignal(str)  # 更新包已下载解压，主程序执行替换重启
    request_clear_history = pyqtSignal()  # 清空字幕记录
    download_progress = pyqtSignal(int, int, int, int)  # 已下载字节, 总字节, 通道序号, 通道总数
    download_finished = pyqtSignal(bool, str, str)  # 成功?, 错误描述或使用的地址, zip 路径

    # 字幕外观默认值（“恢复默认设置”用）
    SUBTITLE_DEFAULTS = {
        "font_size": 22,
        "bg_alpha": 140,
        "width": 700,
        "fade_ms": 5000,
        "click_through": True,
        "display_mode": "both",
        "zh_color": "#FFE34D",
        "src_color": "#FFFFFF",
    }

    def __init__(self, cfg, history_provider=None):
        super().__init__()
        self.cfg = cfg
        self._history_provider = history_provider
        self.setWindowTitle(tr("实时翻译字幕 · 设置 v{ver}").format(ver=__version__))
        self.resize(760, 560)
        self._ui_font = (cfg.get("ui") or {}).get("font_size", 13)
        self.setStyleSheet(build_qss(self._ui_font))

        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = QListWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(150)
        for name in ["主页", "字幕外观", "识别模型", "翻译服务", "字幕记录", "日志"]:
            self.sidebar.addItem(QListWidgetItem(tr(name)))
        layout.addWidget(self.sidebar)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(20, 16, 20, 16)
        self.pages = QStackedWidget()
        right_layout.addWidget(self.pages)

        self._build_home_page()
        self._build_subtitle_page()
        self._build_whisper_page()
        self._build_translator_page()
        self._build_history_page()
        self._build_log_page()

        # 字幕外观控件改动 → 实时预览（不写配置，关闭窗口未保存则自动还原）
        self._live_dirty = False
        self.spin_font.valueChanged.connect(self._emit_live_preview)
        self.slider_alpha.valueChanged.connect(self._emit_live_preview)
        self.spin_width.valueChanged.connect(self._emit_live_preview)
        self.spin_fade.valueChanged.connect(self._emit_live_preview)
        self.chk_through.toggled.connect(self._emit_live_preview)
        self.combo_display.currentIndexChanged.connect(self._emit_live_preview)
        self.spin_x.valueChanged.connect(self._emit_live_preview)
        self.spin_y.valueChanged.connect(self._emit_live_preview)

        apply_bar = QHBoxLayout()
        apply_bar.addStretch()
        self.btn_apply = QPushButton(tr("保存并应用"))
        self.btn_apply.setObjectName("primary")
        self.btn_apply.setMinimumWidth(140)
        self.btn_apply.clicked.connect(self._on_apply)
        apply_bar.addWidget(self.btn_apply)
        right_layout.addLayout(apply_bar)

        layout.addWidget(right)
        self.sidebar.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.sidebar.setCurrentRow(0)

        self._log_timer = QTimer(self)
        self._log_timer.setInterval(2000)
        self._log_timer.timeout.connect(self._refresh_log)

    # ---------- 主页 ----------
    def _build_home_page(self):
        page = QWidget()
        v = QVBoxLayout(page)

        box = QGroupBox(tr("运行状态"))
        h = QHBoxLayout(box)
        self.status_dot = QLabel("●")
        self.status_dot.setObjectName("statusDot")
        self.status_label = QLabel(tr("已停止"))
        self.status_label.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        h.addWidget(self.status_dot)
        h.addWidget(self.status_label)
        h.addStretch()
        self.btn_toggle = QPushButton(tr("开始监听"))
        self.btn_toggle.setObjectName("primary")
        self.btn_toggle.setMinimumSize(120, 40)
        self.btn_toggle.clicked.connect(self.request_toggle.emit)
        h.addWidget(self.btn_toggle)
        v.addWidget(box)

        info = QGroupBox(tr("当前配置"))
        f = QFormLayout(info)
        self.info_hotkey = QLabel()
        self.info_device = QLabel()
        self.info_model = QLabel()
        self.info_backend = QLabel()
        f.addRow(tr("全局热键"), self.info_hotkey)
        f.addRow(tr("音频来源"), self.info_device)
        f.addRow(tr("识别模型"), self.info_model)
        f.addRow(tr("翻译后端"), self.info_backend)
        v.addWidget(info)

        hk_box = QGroupBox(tr("全局热键"))
        hf = QFormLayout(hk_box)
        hk_row = QHBoxLayout()
        self.btn_hotkey = HotkeyCaptureButton(self.cfg.get("hotkey", DEFAULT_HOTKEY))
        self.btn_hotkey.setMinimumWidth(140)
        btn_hk_default = QPushButton(tr("恢复默认 (Alt+T)"))
        btn_hk_default.clicked.connect(lambda: self.btn_hotkey.setText(DEFAULT_HOTKEY))
        hk_row.addWidget(self.btn_hotkey)
        hk_row.addWidget(btn_hk_default)
        hk_row.addStretch()
        hf.addRow(tr("启停监听"), hk_row)
        ocr_row = QHBoxLayout()
        self.btn_hotkey_ocr = HotkeyCaptureButton(
            self.cfg.get("hotkey_ocr", DEFAULT_HOTKEY_OCR)
        )
        self.btn_hotkey_ocr.setMinimumWidth(140)
        btn_ocr_default = QPushButton(tr("恢复默认 (Ctrl+Alt+R)"))
        btn_ocr_default.clicked.connect(
            lambda: self.btn_hotkey_ocr.setText(DEFAULT_HOTKEY_OCR)
        )
        ocr_row.addWidget(self.btn_hotkey_ocr)
        ocr_row.addWidget(btn_ocr_default)
        ocr_row.addStretch()
        hf.addRow(tr("截图翻译"), ocr_row)
        hk_hint = QLabel(tr("点击左侧按钮后按下新的组合键（Ctrl/Alt/Shift + 字母/数字/F1~F12），“保存并应用”后立即生效。"))
        hk_hint.setObjectName("hint")
        hk_hint.setWordWrap(True)
        hf.addRow(hk_hint)
        v.addWidget(hk_box)

        audio_box = QGroupBox(tr("音频来源"))
        adf = QFormLayout(audio_box)
        self.combo_audio = QComboBox()
        adf.addRow(tr("输入设备"), self.combo_audio)
        audio_hint = QLabel(tr("系统声音 = 游戏 / 视频 / 播放器；麦克风 = 会议、网课、语音聊天。改动“保存并应用”后自动重启监听。"))
        audio_hint.setObjectName("hint")
        audio_hint.setWordWrap(True)
        adf.addRow(audio_hint)
        v.addWidget(audio_box)
        self._refresh_audio_devices()

        stat = QGroupBox(tr("统计"))
        fh = QFormLayout(stat)
        self.stat_count = QLabel("0")
        fh.addRow(tr("本次会话字幕"), self.stat_count)
        v.addWidget(stat)

        ui_box = QGroupBox(tr("界面"))
        uf = QFormLayout(ui_box)
        self.spin_ui_font = SliderSpin(10, 22, self._ui_font, suffix="px")
        self.spin_ui_font.valueChanged.connect(self._apply_ui_font)
        uf.addRow(tr("界面字体大小"), self.spin_ui_font)
        self.combo_ui_lang = QComboBox()
        for code, name in [("zh", tr("中文")), ("en", "English")]:
            self.combo_ui_lang.addItem(name, code)
        ui_cfg = self.cfg.get("ui") or {}
        idx = self.combo_ui_lang.findData(ui_cfg.get("language", "zh"))
        self.combo_ui_lang.setCurrentIndex(max(0, idx))
        uf.addRow(tr("界面语言 / Language"), self.combo_ui_lang)
        ui_hint = QLabel(tr("拖动即可看到效果；“保存并应用”后下次打开保持。界面语言在重启软件后完全生效。"))
        ui_hint.setObjectName("hint")
        uf.addRow(ui_hint)
        self.chk_autostart = QCheckBox(tr("开机自动启动（托盘常驻，不弹窗）"))
        try:
            from .autostart import is_enabled as _as_enabled, is_supported as _as_supported
        except ImportError:
            from app.autostart import is_enabled as _as_enabled, is_supported as _as_supported
        self._autostart_supported = _as_supported()
        if self._autostart_supported:
            self.chk_autostart.setChecked(_as_enabled())
        else:
            self.chk_autostart.setEnabled(False)
            self.chk_autostart.setToolTip(tr("仅打包版（exe）支持开机自启"))
        uf.addRow(self.chk_autostart)
        v.addWidget(ui_box)

        about = QGroupBox(tr("关于"))
        af = QFormLayout(about)
        af.addRow(tr("当前版本"), QLabel(f"v{__version__}"))
        author = QLabel(
            tr(
                '作者：<a href="https://github.com/Twilight719">Twilight719</a>'
                '　·　开源地址：<a href="https://github.com/Twilight719/realtime-translate-subtitles">GitHub</a>'
                '　·　MIT 协议'
            )
        )
        author.setObjectName("hint")
        author.setOpenExternalLinks(True)
        af.addRow(tr("创作者"), author)
        update_row = QHBoxLayout()
        self.btn_update = QPushButton(tr("检查更新"))
        self.btn_update.clicked.connect(self._on_check_update)
        self.update_result = QLabel("")
        self.update_result.setObjectName("hint")
        update_row.addWidget(self.btn_update)
        update_row.addWidget(self.update_result)
        update_row.addStretch()
        af.addRow(update_row)
        v.addWidget(about)

        hint = QLabel(tr("提示：托盘图标双击可快速启停；关闭本窗口不会退出程序（托盘常驻）。"))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        v.addWidget(hint)
        v.addStretch()
        self.pages.addWidget(page)

    # ---------- 音频来源 ----------
    def _refresh_audio_devices(self):
        """刷新音频设备下拉框（耳机/麦克风插拔后重新列出），尽量保留原选择。"""
        current = self.combo_audio.currentData() if self.combo_audio.count() else None
        self.combo_audio.blockSignals(True)
        self.combo_audio.clear()
        self.combo_audio.addItem(tr("默认扬声器（系统声音，跟随系统默认输出）"), ("loopback", None))
        try:
            try:
                from .audio_capture import list_input_devices, list_loopback_devices
            except ImportError:
                from app.audio_capture import list_input_devices, list_loopback_devices
            for d in list_loopback_devices():
                self.combo_audio.addItem(tr("扬声器：{name}").format(name=d.name), ("loopback", d.name))
            for d in list_input_devices():
                self.combo_audio.addItem(tr("麦克风：{name}").format(name=d.name), ("mic", d.name))
        except Exception:
            pass
        audio_cfg = self.cfg.get("audio") or {}
        target = current or (audio_cfg.get("source", "loopback"), audio_cfg.get("device_name"))
        idx = self.combo_audio.findData(target)
        if idx < 0 and target and target[1]:
            # 配置里的设备当前没插：保留显示以免丢配置
            label = (tr("麦克风：") if target[0] == "mic" else tr("扬声器：")) + target[1] + tr("（未连接）")
            self.combo_audio.addItem(label, target)
            idx = self.combo_audio.count() - 1
        self.combo_audio.setCurrentIndex(max(0, idx))
        self.combo_audio.blockSignals(False)

    # ---------- 字幕外观 ----------
    def _build_subtitle_page(self):
        page = QWidget()
        v = QVBoxLayout(page)
        s = self.cfg["subtitle"]

        box = QGroupBox(tr("样式"))
        f = QFormLayout(box)

        self.spin_font = SliderSpin(12, 60, s.get("font_size", 22), suffix="px")
        f.addRow(tr("字体大小"), self.spin_font)

        self.slider_alpha = SliderSpin(20, 255, s.get("bg_alpha", 140), step=5)
        f.addRow(tr("背景不透明度"), self.slider_alpha)

        self.spin_width = SliderSpin(300, 2000, s.get("width", 700), suffix="px", step=10)
        f.addRow(tr("字幕条宽度"), self.spin_width)

        self.spin_fade = SliderSpin(1000, 30000, s.get("fade_ms", 5000), suffix="ms", step=500)
        f.addRow(tr("无语音淡出"), self.spin_fade)

        self.chk_through = QCheckBox(tr("点击穿透（鼠标操作穿透字幕窗，不影响游戏）"))
        self.chk_through.setChecked(s.get("click_through", True))
        f.addRow(self.chk_through)

        self.combo_display = QComboBox()
        for code, name in [("both", tr("双语显示（原文 + 译文）")),
                           ("zh", tr("只显示译文")),
                           ("src", tr("只显示原文"))]:
            self.combo_display.addItem(name, code)
        idx = self.combo_display.findData(s.get("display_mode", "both"))
        self.combo_display.setCurrentIndex(max(0, idx))
        f.addRow(tr("字幕内容"), self.combo_display)
        v.addWidget(box)

        color_box = QGroupBox(tr("颜色"))
        cf = QFormLayout(color_box)
        self._zh_color = s.get("zh_color", "#FFE34D")
        self._src_color = s.get("src_color", "#FFFFFF")
        self.btn_zh_color = QPushButton()
        self.btn_src_color = QPushButton()
        self.btn_zh_color.clicked.connect(lambda: self._pick_color("zh"))
        self.btn_src_color.clicked.connect(lambda: self._pick_color("src"))
        self._refresh_color_btns()
        cf.addRow(tr("译文颜色"), self.btn_zh_color)
        cf.addRow(tr("原文颜色"), self.btn_src_color)
        color_hint = QLabel(tr("未确认中的滚动文字会自动使用同色的半透明效果。"))
        color_hint.setObjectName("hint")
        cf.addRow(color_hint)
        v.addWidget(color_box)

        ocr_box = QGroupBox(tr("截图翻译弹窗"))
        of = QFormLayout(ocr_box)
        o = self.cfg.get("ocr") or {}
        self.spin_ocr_duration = SliderSpin(0, 60000, o.get("duration_ms", 8000), suffix="ms", step=1000)
        of.addRow(tr("弹窗停留时长"), self.spin_ocr_duration)
        self.spin_ocr_font = SliderSpin(10, 40, o.get("font_size", 15), suffix="px")
        of.addRow(tr("弹窗字号"), self.spin_ocr_font)
        self.spin_ocr_alpha = SliderSpin(20, 255, o.get("bg_alpha", 235), step=5)
        of.addRow(tr("弹窗背景不透明度"), self.spin_ocr_alpha)
        self.combo_ocr_display = QComboBox()
        for code, name in [("both", tr("双语显示（原文 + 译文）")),
                           ("zh", tr("只显示译文")),
                           ("src", tr("只显示原文"))]:
            self.combo_ocr_display.addItem(name, code)
        idx = self.combo_ocr_display.findData(o.get("display_mode", "both"))
        self.combo_ocr_display.setCurrentIndex(max(0, idx))
        of.addRow(tr("弹窗内容"), self.combo_ocr_display)
        ocr_hint = QLabel(tr("弹窗显示在框选区域附近；停留时长填 0 表示不自动关闭（点击弹窗关闭）。"))
        ocr_hint.setObjectName("hint")
        ocr_hint.setWordWrap(True)
        of.addRow(ocr_hint)
        v.addWidget(ocr_box)

        pos = QGroupBox(tr("位置"))
        pv = QVBoxLayout(pos)
        preset_row = QHBoxLayout()
        for label, key in [(tr("顶部居中"), "top"), (tr("屏幕中央"), "center"), (tr("底部居中"), "bottom")]:
            btn = QPushButton(label)
            btn.clicked.connect(lambda _, k=key: self._apply_preset(k))
            preset_row.addWidget(btn)
        pv.addLayout(preset_row)
        xy_row = QHBoxLayout()
        self.spin_x = QSpinBox()
        self.spin_x.setRange(0, 10000)
        self.spin_x.setValue(s.get("x", 300))
        self.spin_y = QSpinBox()
        self.spin_y.setRange(0, 10000)
        self.spin_y.setValue(s.get("y", 800))
        xy_row.addWidget(QLabel("X"))
        xy_row.addWidget(self.spin_x)
        xy_row.addWidget(QLabel("Y"))
        xy_row.addWidget(self.spin_y)
        xy_row.addStretch()
        pv.addLayout(xy_row)
        drag_row = QHBoxLayout()
        self.btn_drag = QPushButton(tr("手动拖动定位"))
        self.btn_drag.clicked.connect(self._on_drag_clicked)
        drag_row.addWidget(self.btn_drag)
        drag_hint = QLabel(tr("点击后字幕条会显示出来，用鼠标拖到想要的位置 → 点“完成定位” → “保存并应用”"))
        drag_hint.setObjectName("hint")
        drag_row.addWidget(drag_hint)
        drag_row.addStretch()
        pv.addLayout(drag_row)
        self._dragging = False
        v.addWidget(pos)

        btn_row = QHBoxLayout()
        btn_preview = QPushButton(tr("预览字幕效果"))
        btn_preview.clicked.connect(self.request_preview.emit)
        btn_row.addWidget(btn_preview)
        btn_restore = QPushButton(tr("恢复默认设置"))
        btn_restore.setObjectName("danger")
        btn_restore.clicked.connect(self._on_restore_defaults)
        btn_row.addWidget(btn_restore)
        btn_row.addStretch()
        v.addLayout(btn_row)

        hint = QLabel(tr("外观改动会实时预览（不写入配置）；关闭本窗口时未保存的改动自动还原。点“保存并应用”后才持久生效。"))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        v.addWidget(hint)

        v.addWidget(make_help_widget([
            tr("字体大小：译文行的字号，原文行和历史行会按比例自动缩小。"),
            tr("背景不透明度：字幕条黑底的深浅，20 几乎全透明，255 全黑。"),
            tr("字幕条宽度：字幕的最大宽度，文字超出会自动换行。"),
            tr("无语音淡出：多久没有新字幕后自动隐藏字幕条，有声音时立即重新显示。"),
            tr("点击穿透：开启后鼠标可以穿过字幕条操作游戏；用“手动拖动定位”时会临时关闭。"),
            tr("字幕内容：双语显示 = 原文+译文两行；只显示译文适合专注看翻译；只显示原文适合练听力。"),
            tr("颜色：译文/原文的显示颜色，正在识别中的滚动文字自动使用同色的半透明效果。"),
            tr("位置：预设档位一键摆放到顶部/中央/底部，也可填坐标或手动拖动精确定位。"),
        ]))
        v.addStretch()
        self.pages.addWidget(page)

    def _on_drag_clicked(self):
        if not self._dragging:
            self._dragging = True
            self.btn_drag.setText(tr("完成定位"))
            self.request_drag_start.emit()
        else:
            self._dragging = False
            self.btn_drag.setText(tr("手动拖动定位"))
            self.request_drag_end.emit()

    def set_position(self, x, y):
        """拖动完成后由主程序回调，把实际坐标填回输入框。"""
        self.spin_x.setValue(x)
        self.spin_y.setValue(y)

    def _pick_color(self, which):
        current = self._zh_color if which == "zh" else self._src_color
        color = QColorDialog.getColor(QColor(current), self, tr("选择字幕颜色"))
        if not color.isValid():
            return
        if which == "zh":
            self._zh_color = color.name().upper()
        else:
            self._src_color = color.name().upper()
        self._refresh_color_btns()
        self._emit_live_preview()

    def _refresh_color_btns(self):
        for btn, hex_color in ((self.btn_zh_color, self._zh_color), (self.btn_src_color, self._src_color)):
            c = QColor(hex_color)
            fg = "#000000" if (c.red() * 299 + c.green() * 587 + c.blue() * 114) > 150000 else "#FFFFFF"
            btn.setText(hex_color)
            btn.setStyleSheet(f"background: {hex_color}; color: {fg}; border-radius: 6px; padding: 6px 16px;")

    def _subtitle_ui_values(self):
        return {
            "font_size": self.spin_font.value(),
            "bg_alpha": self.slider_alpha.value(),
            "width": self.spin_width.value(),
            "fade_ms": self.spin_fade.value(),
            "click_through": self.chk_through.isChecked(),
            "display_mode": self.combo_display.currentData(),
            "x": self.spin_x.value(),
            "y": self.spin_y.value(),
            "zh_color": self._zh_color,
            "src_color": self._src_color,
        }

    def _emit_live_preview(self, *_):
        self._live_dirty = True
        self.request_live_preview.emit(self._subtitle_ui_values())

    def _on_restore_defaults(self):
        if QMessageBox.question(
            self, tr("恢复默认设置"),
            tr("确定把字幕外观恢复为默认值吗？\n（点“保存并应用”后才会写入配置）"),
        ) != QMessageBox.Yes:
            return
        d = self.SUBTITLE_DEFAULTS
        self.spin_font.setValue(d["font_size"])
        self.slider_alpha.setValue(d["bg_alpha"])
        self.spin_width.setValue(d["width"])
        self.spin_fade.setValue(d["fade_ms"])
        self.chk_through.setChecked(d["click_through"])
        idx = self.combo_display.findData(d["display_mode"])
        self.combo_display.setCurrentIndex(max(0, idx))
        self._zh_color = d["zh_color"]
        self._src_color = d["src_color"]
        self._refresh_color_btns()
        self._apply_preset("bottom")

    def _apply_preset(self, key):
        screen = QApplication.primaryScreen().availableGeometry()
        w = self.spin_width.value()
        x = screen.x() + (screen.width() - w) // 2
        if key == "top":
            y = screen.y() + 60
        elif key == "center":
            y = screen.y() + screen.height() // 2 - 60
        else:
            y = screen.y() + screen.height() - 220
        self.spin_x.setValue(x)
        self.spin_y.setValue(y)

    # ---------- 识别模型 ----------
    def _build_whisper_page(self):
        page = QWidget()
        v = QVBoxLayout(page)
        w = self.cfg["whisper"]

        lang_box = QGroupBox(tr("语言"))
        lf = QFormLayout(lang_box)
        lang_cfg = self.cfg.get("language") or {}
        self.combo_src_lang = QComboBox()
        for code, name in [("auto", tr("自动检测")), ("zh", tr("中文")), ("en", tr("英语")),
                           ("ja", tr("日语")), ("ko", tr("韩语")), ("ru", tr("俄语"))]:
            self.combo_src_lang.addItem(name, code)
        idx = self.combo_src_lang.findData(lang_cfg.get("source", "auto"))
        self.combo_src_lang.setCurrentIndex(max(0, idx))
        lf.addRow(tr("源语言（听到的）"), self.combo_src_lang)

        self.combo_tgt_lang = QComboBox()
        for code, name in [("zh", tr("中文")), ("en", tr("英语")), ("ja", tr("日语")),
                           ("ko", tr("韩语")), ("ru", tr("俄语"))]:
            self.combo_tgt_lang.addItem(name, code)
        idx = self.combo_tgt_lang.findData(lang_cfg.get("target", "zh"))
        self.combo_tgt_lang.setCurrentIndex(max(0, idx))
        lf.addRow(tr("目标语言（翻译成）"), self.combo_tgt_lang)

        lang_hint = QLabel(
            tr(
                "自动检测适合视频里语言混说；看单一语言视频时锁定源语言，识别更快更准。"
                "语言改动保存后立即生效，无需重启监听。"
            )
        )
        lang_hint.setObjectName("hint")
        lang_hint.setWordWrap(True)
        lf.addRow(lang_hint)
        v.addWidget(lang_box)

        box = QGroupBox(tr("语音识别引擎"))
        f = QFormLayout(box)

        self.combo_engine = QComboBox()
        self.combo_engine.addItem(tr("faster-whisper（精准，支持约 99 种语言）"), "whisper")
        self.combo_engine.addItem(tr("SenseVoice（极速·CPU 即可，仅 中/英/日/韩/粤）"), "sensevoice")
        idx = self.combo_engine.findData(w.get("engine", "whisper"))
        self.combo_engine.setCurrentIndex(max(0, idx))
        f.addRow(tr("识别引擎"), self.combo_engine)

        self.combo_model = QComboBox()
        self.combo_model.addItems(["tiny", "base", "small", "medium", "large-v3-turbo"])
        self.combo_model.setCurrentText(w.get("model_size", "small"))
        f.addRow(tr("模型档位"), self.combo_model)

        self.combo_device = QComboBox()
        self.combo_device.addItems(["cuda", "cpu"])
        self.combo_device.setCurrentText(w.get("device", "cuda"))
        f.addRow(tr("运行设备"), self.combo_device)

        self.combo_compute = QComboBox()
        self.combo_compute.addItems(["float16", "int8_float16", "int8"])
        self.combo_compute.setCurrentText(w.get("compute_type", "float16"))
        f.addRow(tr("计算精度"), self.combo_compute)

        self.spin_beam = QSpinBox()
        self.spin_beam.setRange(1, 5)
        self.spin_beam.setValue(w.get("beam_size", 1))
        f.addRow("Beam size", self.spin_beam)

        self.edit_prompt = QLineEdit(w.get("prompt") or "")
        self.edit_prompt.setPlaceholderText(tr("可选：作品名 / 角色名 / 术语，如：原神 派蒙 元素爆发"))
        f.addRow(tr("识别提示词"), self.edit_prompt)
        v.addWidget(box)

        hint = QLabel(tr("识别参数改动后自动重启监听生效（需重新加载模型，等待几秒）。"))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        v.addWidget(hint)

        v.addWidget(make_help_widget([
            tr(
                "识别引擎：faster-whisper 精准、语言多（可选 large-v3-turbo）；SenseVoice 专为中日韩语优化，"
                "CPU 上约 30 倍实时速度、加载仅 1 秒、不抢显卡，看日/英视频强烈推荐。选 SenseVoice 时"
                "下面的模型档位/设备/精度/提示词不生效。"
            ),
            tr(
                "源语言：听到的语言。自动检测适合视频里多国语言混说；看单一语言视频时锁定，识别更快更准。"
                "注意 SenseVoice 只支持 中/英/日/韩/粤，锁定其他语言会自动改回自动检测。"
            ),
            tr("目标语言：字幕翻译成的语言。改动保存后立即生效，无需重启。"),
            tr(
                "模型档位：tiny/base 最快但错字多；small 均衡；large-v3-turbo 最准，专为实时设计，"
                "显卡上速度和 small 相当（首次需下载约 1.6GB，显存多占约 1GB），追求准确度推荐它。"
            ),
            tr("运行设备：cuda = 用显卡识别（快）；cpu = 用处理器（慢 3~5 倍），显卡被占满时才考虑。"),
            tr("计算精度：cuda 选 float16 或 int8_float16（更快、显存更省，质量几乎无损）；cpu 选 int8。"),
            tr("Beam size：识别时每步比较的候选数量。1 最快（实时字幕推荐）；3~5 略准但明显变慢。"),
            tr(
                "识别提示词：告诉模型当前内容的背景词汇（作品名/角色名/术语），专有名词识别明显更准；"
                "改动立即生效，不会重载模型。"
            ),
            tr("识别为单遍模式：嘈杂音频（BGM/音效）不会反复重试，避免延迟累积。"),
        ]))
        v.addStretch()
        self.pages.addWidget(page)

    # ---------- 翻译服务 ----------
    def _build_translator_page(self):
        page = QWidget()
        v = QVBoxLayout(page)
        t = self.cfg["translator"]

        box = QGroupBox(tr("后端优先级（勾选启用，自上而下依次尝试）"))
        bl = QHBoxLayout(box)
        self.order_list = QListWidget()
        self.order_list.setObjectName("orderList")
        for name in t.get("order", []):
            self._add_backend_item(name, True)
        for name in BACKENDS:
            if name not in t.get("order", []):
                self._add_backend_item(name, False)
        bl.addWidget(self.order_list)
        btns = QVBoxLayout()
        btn_up = QPushButton(tr("上移"))
        btn_up.clicked.connect(lambda: self._move_item(-1))
        btn_down = QPushButton(tr("下移"))
        btn_down.clicked.connect(lambda: self._move_item(1))
        btns.addWidget(btn_up)
        btns.addWidget(btn_down)
        btns.addStretch()
        bl.addLayout(btns)
        v.addWidget(box)

        nllb_row = QFormLayout()
        self.combo_nllb = QComboBox()
        self.combo_nllb.addItems(["cpu", "cuda"])
        self.combo_nllb.setCurrentText(t.get("nllb_device", "cpu"))
        nllb_row.addRow(tr("NLLB 运行设备"), self.combo_nllb)
        v.addLayout(nllb_row)

        llm = QGroupBox(tr("大模型 API（选择“大模型 API”后端时生效）"))
        lf = QFormLayout(llm)
        cfg_llm = t.get("llm_api", {})
        self.edit_base_url = QLineEdit(cfg_llm.get("base_url", ""))
        self.edit_base_url.setPlaceholderText("https://api.deepseek.com/v1")
        self.edit_api_key = QLineEdit(cfg_llm.get("api_key", ""))
        self.edit_api_key.setEchoMode(QLineEdit.Password)
        self.edit_api_key.setPlaceholderText("sk-...")
        self.edit_model = QLineEdit(cfg_llm.get("model", ""))
        self.edit_model.setPlaceholderText("deepseek-flash")
        lf.addRow("Base URL", self.edit_base_url)
        lf.addRow("API Key", self.edit_api_key)
        lf.addRow(tr("模型名"), self.edit_model)
        self.chk_stream = QCheckBox(tr("流式输出（译文逐字上屏，不用等整句翻完，观感更实时）"))
        self.chk_stream.setChecked(cfg_llm.get("stream", True))
        lf.addRow(self.chk_stream)
        v.addWidget(llm)

        v.addWidget(make_help_widget([
            tr("后端优先级：排最上面的先用，失败或限流时自动切换到下一个，全部失败会稍后自动恢复重试。"),
            tr("有道翻译：免 key、国内直连，速度快，但只支持“外语 ↔ 中文”。"),
            tr("大模型 API：DeepSeek 等，口语和游戏术语翻译质量最好，需要填 API Key（按量计费）。"),
            tr("MyMemory / Google：免费备用；Google 需要能访问它的网络。"),
            tr("NLLB 本地模型：离线兜底，断网也能翻，质量一般、速度较慢。"),
            tr("NLLB 运行设备：cpu 不占显存（推荐，把显存留给识别和游戏）；cuda 更快但多占约 1GB 显存。"),
            tr("Base URL / API Key / 模型名：选择“大模型 API”后端时生效，DeepSeek 官方地址为 https://api.deepseek.com/v1。"),
            tr("流式输出：开启后译文逐字上屏（像打字一样），不用等整句翻完；关闭则等整句翻完一次性显示。仅对“大模型 API”后端生效。"),
        ]))

        hint = QLabel(tr("API Key 以明文保存在本地 config.yaml 中。翻译后端改动立即重建，无需重启监听。"))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        v.addWidget(hint)
        v.addStretch()
        self.pages.addWidget(page)

    def _add_backend_item(self, name, checked):
        title, desc = BACKENDS.get(name, (name, ""))
        item = QListWidgetItem(f"{title}  —  {desc}")
        item.setData(Qt.UserRole, name)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self.order_list.addItem(item)

    def _move_item(self, delta):
        row = self.order_list.currentRow()
        if row < 0:
            return
        new_row = row + delta
        if 0 <= new_row < self.order_list.count():
            item = self.order_list.takeItem(row)
            self.order_list.insertItem(new_row, item)
            self.order_list.setCurrentRow(new_row)

    # ---------- 字幕记录 ----------
    def _build_history_page(self):
        page = QWidget()
        v = QVBoxLayout(page)

        self.history_view = QPlainTextEdit()
        self.history_view.setReadOnly(True)
        self.history_view.setFont(QFont("Consolas", 10))
        v.addWidget(self.history_view)

        row = QHBoxLayout()
        self.history_count = QLabel(tr("{n} 条").format(n=0))
        self.history_count.setObjectName("hint")
        btn_refresh = QPushButton(tr("刷新"))
        btn_refresh.clicked.connect(lambda: self.refresh_history(force=True))
        btn_export = QPushButton(tr("导出为 TXT"))
        btn_export.clicked.connect(self._export_history)
        btn_clear = QPushButton(tr("清空记录"))
        btn_clear.setObjectName("danger")
        btn_clear.clicked.connect(self._clear_history)
        row.addWidget(self.history_count)
        row.addStretch()
        row.addWidget(btn_refresh)
        row.addWidget(btn_export)
        row.addWidget(btn_clear)
        v.addLayout(row)

        hint = QLabel(tr("记录本次会话所有定稿字幕（最多保留 5000 条，退出程序后清空）。"))
        hint.setObjectName("hint")
        v.addWidget(hint)
        self.pages.addWidget(page)

    def refresh_history(self, force=False):
        """刷新字幕记录视图。窗口隐藏时跳过（避免每条字幕都重建文本）。"""
        if not hasattr(self, "history_view"):
            return
        if not force and not self.isVisible():
            return
        items = self._history_provider() if self._history_provider else []
        lines = []
        for it in items:
            src, zh = (it.get("src") or "").strip(), (it.get("zh") or "").strip()
            if src and zh:
                lines.append(f"[{it['time']}] {src}\n            {zh}")
            else:
                lines.append(f"[{it['time']}] {zh or src}")
        self.history_view.setPlainText("\n".join(lines))
        self.history_count.setText(tr("{n} 条").format(n=len(items)))
        bar = self.history_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _export_history(self):
        items = self._history_provider() if self._history_provider else []
        if not items:
            QMessageBox.information(self, tr("导出字幕记录"), tr("当前还没有字幕记录。"))
            return
        default = time.strftime(tr("字幕记录_%Y%m%d_%H%M.txt"))
        path, _ = QFileDialog.getSaveFileName(self, tr("导出字幕记录"), default, tr("文本文件 (*.txt)"))
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(tr("实时翻译字幕 · 会话记录\n"))
            f.write(time.strftime(tr("导出时间：%Y-%m-%d %H:%M:%S")) + "\n\n")
            for it in items:
                f.write(f"[{it['time']}] {(it.get('src') or '').strip()}\n")
                zh = (it.get("zh") or "").strip()
                if zh:
                    f.write(f"            {zh}\n")
        QMessageBox.information(self, tr("导出完成"), tr("已导出 {n} 条到：\n{path}").format(n=len(items), path=path))

    def _clear_history(self):
        if QMessageBox.question(self, tr("清空记录"), tr("确定清空本次会话的字幕记录吗？")) != QMessageBox.Yes:
            return
        self.request_clear_history.emit()
        self.refresh_history(force=True)

    # ---------- 日志 ----------
    def _build_log_page(self):
        page = QWidget()
        v = QVBoxLayout(page)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Consolas", 9))
        v.addWidget(self.log_view)

        row = QHBoxLayout()
        self.chk_autolog = QCheckBox(tr("自动刷新"))
        self.chk_autolog.setChecked(True)
        self.chk_autolog.toggled.connect(
            lambda on: self._log_timer.start() if on else self._log_timer.stop()
        )
        btn_refresh = QPushButton(tr("刷新"))
        btn_refresh.clicked.connect(self._refresh_log)
        btn_clear = QPushButton(tr("清空日志"))
        btn_clear.setObjectName("danger")
        btn_clear.clicked.connect(self._clear_log)
        btn_open = QPushButton(tr("打开所在目录"))
        btn_open.clicked.connect(lambda: subprocess.Popen(["explorer", base_dir()]))
        row.addWidget(self.chk_autolog)
        row.addStretch()
        row.addWidget(btn_refresh)
        row.addWidget(btn_clear)
        row.addWidget(btn_open)
        v.addLayout(row)
        self.pages.addWidget(page)

    # ---------- 公共 ----------
    def set_running(self, running):
        if running:
            self.status_dot.setStyleSheet("color: #4CAF50;")
            self.status_label.setText(tr("运行中"))
            self.btn_toggle.setText(tr("停止监听"))
        else:
            self.status_dot.setStyleSheet("color: #888888;")
            self.status_label.setText(tr("已停止"))
            self.btn_toggle.setText(tr("开始监听"))

    def set_subtitle_count(self, n):
        self.stat_count.setText(str(n))

    def _apply_ui_font(self, size):
        """界面字号改动：立即重刷样式表（不写配置）。"""
        self._ui_font = size
        self.setStyleSheet(build_qss(size))

    # ---------- 检查更新 ----------
    def _on_check_update(self):
        self.btn_update.setEnabled(False)
        self.update_result.setText(tr("正在检查…"))
        self.request_check_update.emit()

    def show_update_result(self, result, popup=True):
        """主程序检查完成后回调（已在 Qt 主线程）。popup=False 时只更新文字（启动自动检查用）。"""
        import webbrowser

        self.btn_update.setEnabled(True)
        if result.get("error"):
            self.update_result.setText(tr("检查失败：{err}").format(err=result["error"]))
            return
        if result.get("has_update"):
            self._latest_update = result
            self.update_result.setText(
                tr("发现新版本 {latest}（当前 v{ver}），点“检查更新”可下载").format(
                    latest=result["latest"], ver=__version__
                )
            )
            if not popup:
                return
            box = QMessageBox(self)
            box.setWindowTitle(tr("发现新版本"))
            box.setText(
                tr(
                    "最新版本 {latest} 已发布（当前 v{ver}）。\n\n"
                    "“软件内下载”会优先走国内加速镜像，全部失败才用 GitHub 直连；\n"
                    "下载完成后自动替换旧文件并重启（你的配置和已下载模型都会保留）。"
                ).format(latest=result["latest"], ver=__version__)
            )
            btn_dl = box.addButton(tr("软件内下载更新（推荐）"), QMessageBox.AcceptRole)
            btn_web = box.addButton(tr("打开下载页面"), QMessageBox.ActionRole)
            box.addButton(tr("取消"), QMessageBox.RejectRole)
            box.exec_()
            clicked = box.clickedButton()
            if clicked is btn_dl:
                self._start_download(result)
            elif clicked is btn_web:
                webbrowser.open(result["url"])
        else:
            self._latest_update = None
            self.update_result.setText(tr("已是最新版本（v{ver}）").format(ver=__version__))

    # ---------- 软件内下载更新 ----------
    def _start_download(self, result):
        asset = result.get("asset")
        if not asset:
            # Release 里没有标准更新包附件（异常情况），退化为浏览器下载
            import webbrowser

            webbrowser.open(result["url"])
            return
        try:
            from .updater import download_asset
        except ImportError:
            from app.updater import download_asset

        dest = os.path.join(tempfile.gettempdir(), asset["name"])
        self._dl_cancel = threading.Event()
        self._dl_dialog = QProgressDialog(tr("准备下载…"), tr("取消"), 0, 100, self)
        self._dl_dialog.setWindowTitle(tr("下载更新 {latest}").format(latest=result["latest"]))
        self._dl_dialog.setWindowModality(Qt.WindowModal)
        self._dl_dialog.setMinimumDuration(0)
        self._dl_dialog.setMinimumWidth(420)
        self._dl_dialog.canceled.connect(self._dl_cancel.set)
        self.download_progress.connect(self._on_dl_progress)
        self.download_finished.connect(self._on_dl_finished)

        def run():
            used_url, err = download_asset(
                asset, dest,
                progress_cb=lambda *a: self.download_progress.emit(*a),
                cancel=self._dl_cancel,
            )
            self.download_finished.emit(err is None, err or used_url, dest)

        threading.Thread(target=run, daemon=True).start()

    def _on_dl_progress(self, done, total, idx, count):
        channel = tr("GitHub 直连") if idx == count - 1 else tr("镜像 {n}").format(n=idx + 1)
        if total:
            self._dl_dialog.setLabelText(
                tr("正在下载（{channel}，第 {idx}/{count} 个通道）：\n{done:.0f} / {total:.0f} MB").format(
                    channel=channel, idx=idx + 1, count=count,
                    done=done / 1048576, total=total / 1048576,
                )
            )
            self._dl_dialog.setValue(int(done * 100 / total))
        else:
            self._dl_dialog.setLabelText(
                tr("正在下载（{channel}）：{done:.0f} MB").format(channel=channel, done=done / 1048576)
            )

    def _on_dl_finished(self, ok, info, dest):
        self._dl_dialog.close()
        if not ok:
            if info != "已取消":
                QMessageBox.warning(
                    self, tr("下载失败"),
                    tr("{info}\n\n可以点“检查更新 → 打开下载页面”用浏览器手动下载。").format(info=info),
                )
            return
        try:
            app_dir = self._extract_update(dest)
        except Exception as e:
            QMessageBox.warning(self, tr("解压失败"), tr("{e}\n\n可以用浏览器手动下载后覆盖安装。").format(e=e))
            return
        if QMessageBox.question(
            self, tr("下载完成"),
            tr("更新包已就绪，立即重启完成更新吗？\n（当前配置和已下载的模型都会保留）"),
        ) == QMessageBox.Yes:
            self.request_install_update.emit(app_dir)

    @staticmethod
    def _extract_update(zip_path):
        """解压更新包，返回新版程序目录（内含 exe 的那层）。"""
        staging_root = zip_path[:-4] + "_extract"
        shutil.rmtree(staging_root, ignore_errors=True)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(staging_root)
        entries = os.listdir(staging_root)
        # 压缩包结构为 实时翻译字幕/…（单顶层目录）；容错处理平铺情况
        app_dir = (os.path.join(staging_root, entries[0])
                   if len(entries) == 1 and os.path.isdir(os.path.join(staging_root, entries[0]))
                   else staging_root)
        if not any(f.lower().endswith(".exe") for f in os.listdir(app_dir)):
            raise RuntimeError(tr("更新包结构异常：找不到程序文件"))
        return app_dir

    def refresh_info(self, device_name=""):
        self.info_hotkey.setText(self.cfg.get("hotkey", "alt+t"))
        self.info_device.setText(device_name or tr("默认扬声器 (loopback)"))
        w = self.cfg["whisper"]
        if w.get("engine", "whisper") == "sensevoice":
            self.info_model.setText(tr("SenseVoice 极速 / cpu"))
        else:
            self.info_model.setText(f"{w.get('model_size')} / {w.get('device')}")
        order = self.cfg["translator"].get("order", [])
        names = [BACKENDS.get(n, (n, ""))[0].split("（")[0] for n in order]
        self.info_backend.setText(" → ".join(names))

    def showEvent(self, event):
        self.refresh_info()
        self._refresh_audio_devices()
        self.refresh_history(force=True)
        self._refresh_log()
        if self.chk_autolog.isChecked():
            self._log_timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self._log_timer.stop()
        # 实时预览过但没点“保存并应用”→ 还原为已保存的外观
        if self._live_dirty:
            self._live_dirty = False
            saved = dict(self.SUBTITLE_DEFAULTS)
            saved.update(self.cfg["subtitle"])
            self.request_live_preview.emit(saved)
        super().hideEvent(event)

    def closeEvent(self, event):
        event.ignore()
        self.hide()

    def _refresh_log(self):
        path = os.path.join(base_dir(), "app.log")
        if not os.path.exists(path):
            self.log_view.setPlainText(tr("（暂无日志）"))
            return
        with open(path, encoding="utf-8", errors="replace") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 100 * 1024))
            content = f.read()
        bar = self.log_view.verticalScrollBar()
        scroll_at_bottom = bar.value() >= bar.maximum() - 10
        saved_pos = bar.value()
        self.log_view.setPlainText(content)
        if scroll_at_bottom:
            # 一直在底部 = 在追最新日志，继续跟住最新
            bar.setValue(bar.maximum())
        else:
            # 用户正在翻阅历史：恢复原位置，不被刷新打断
            bar.setValue(saved_pos)

    def _clear_log(self):
        if QMessageBox.question(self, tr("清空日志"), tr("确定清空 app.log 吗？")) != QMessageBox.Yes:
            return
        # 通过日志 handler 安全清空：先关闭流再截断重开，避免写入位置错乱
        import logging

        for h in logging.root.handlers:
            if getattr(h, "baseFilename", "").endswith("app.log"):
                h.acquire()
                try:
                    h.close()
                    open(h.baseFilename, "w", encoding="utf-8").close()
                    h.stream = open(h.baseFilename, h.mode, encoding=h.encoding)
                finally:
                    h.release()
        self._refresh_log()

    def _on_apply(self):
        cfg = self.cfg
        hk = self.btn_hotkey.hotkey()
        try:
            parse_hotkey(hk)
            cfg["hotkey"] = hk
        except ValueError as e:
            QMessageBox.warning(
                self, tr("热键无效"),
                tr("热键“{hk}”无法识别（{err}），本次保留原热键 {old}。").format(
                    hk=hk, err=e, old=cfg.get("hotkey", DEFAULT_HOTKEY)
                ),
            )
            self.btn_hotkey.setText(cfg.get("hotkey", DEFAULT_HOTKEY))
        hk_ocr = self.btn_hotkey_ocr.hotkey()
        try:
            parse_hotkey(hk_ocr)
            cfg["hotkey_ocr"] = hk_ocr
        except ValueError as e:
            QMessageBox.warning(
                self, tr("热键无效"),
                tr("热键“{hk}”无法识别（{err}），本次保留原热键 {old}。").format(
                    hk=hk_ocr, err=e, old=cfg.get("hotkey_ocr", DEFAULT_HOTKEY_OCR)
                ),
            )
            self.btn_hotkey_ocr.setText(cfg.get("hotkey_ocr", DEFAULT_HOTKEY_OCR))

        s = cfg["subtitle"]
        s["font_size"] = self.spin_font.value()
        s["bg_alpha"] = self.slider_alpha.value()
        s["width"] = self.spin_width.value()
        s["fade_ms"] = self.spin_fade.value()
        s["click_through"] = self.chk_through.isChecked()
        s["display_mode"] = self.combo_display.currentData()
        s["x"] = self.spin_x.value()
        s["y"] = self.spin_y.value()
        s["zh_color"] = self._zh_color
        s["src_color"] = self._src_color

        lang = cfg.get("language")
        if lang is None:
            cfg["language"] = lang = {}
        lang["source"] = self.combo_src_lang.currentData()
        lang["target"] = self.combo_tgt_lang.currentData()

        ui = cfg.get("ui")
        if ui is None:
            cfg["ui"] = ui = {}
        ui["font_size"] = self.spin_ui_font.value()
        ui["language"] = self.combo_ui_lang.currentData()

        ocr = cfg.get("ocr")
        if ocr is None:
            cfg["ocr"] = ocr = {}
        ocr["duration_ms"] = self.spin_ocr_duration.value()
        ocr["font_size"] = self.spin_ocr_font.value()
        ocr["bg_alpha"] = self.spin_ocr_alpha.value()
        ocr["display_mode"] = self.combo_ocr_display.currentData()

        audio = cfg.get("audio")
        if audio is None:
            cfg["audio"] = audio = {}
        audio_data = self.combo_audio.currentData()
        if audio_data:
            audio["source"], audio["device_name"] = audio_data[0], audio_data[1]

        if self._autostart_supported:
            app_cfg = cfg.get("app")
            if app_cfg is None:
                cfg["app"] = app_cfg = {}
            app_cfg["autostart"] = self.chk_autostart.isChecked()

        w = cfg["whisper"]
        w["engine"] = self.combo_engine.currentData()
        w["model_size"] = self.combo_model.currentText()
        w["device"] = self.combo_device.currentText()
        w["compute_type"] = self.combo_compute.currentText()
        w["beam_size"] = self.spin_beam.value()
        w["prompt"] = self.edit_prompt.text().strip() or None

        t = cfg["translator"]
        t["order"] = [
            self.order_list.item(i).data(Qt.UserRole)
            for i in range(self.order_list.count())
            if self.order_list.item(i).checkState() == Qt.Checked
        ]
        t["nllb_device"] = self.combo_nllb.currentText()
        t.setdefault("llm_api", {})
        t["llm_api"]["base_url"] = self.edit_base_url.text().strip()
        t["llm_api"]["api_key"] = self.edit_api_key.text().strip()
        t["llm_api"]["model"] = self.edit_model.text().strip()
        t["llm_api"]["stream"] = self.chk_stream.isChecked()

        self._live_dirty = False
        self.request_apply.emit(cfg)


if __name__ == "__main__":
    # 独立预览界面用
    import yaml

    with open("config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    app = QApplication(sys.argv)
    win = SettingsWindow(cfg)
    win.show()
    sys.exit(app.exec_())
