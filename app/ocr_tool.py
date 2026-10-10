"""截图 OCR 翻译：框选屏幕区域 → Windows 内置 OCR → 走翻译链 → 区域旁弹窗显示译文。

OCR 用 Windows.Media.Ocr（系统自带，无需下载模型）；识别语言按
设置里的源语言选择（如日语需在 Windows 安装日语语言包，否则自动降级到已有语言）。
"""

import asyncio
import logging
import os
import re
import tempfile

from html import escape

from PyQt5.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import QApplication, QLabel, QWidget

from .i18n import tr
from . import i18n_strings  # noqa: F401  注册中英文映射

log = logging.getLogger("subtitle")

# 源语言码 → Windows 语言标签
LANG_TAGS = {"zh": "zh-Hans-CN", "en": "en-US", "ja": "ja-JP", "ko": "ko-KR", "ru": "ru-RU"}

# Windows OCR 对中日文逐字加空格（"你 好 世 界"），翻译前去掉 CJK 字符间的空格
_CJK = "　-〿぀-ヿ㐀-䶿一-鿿＀-￯"
_CJK_SPACE = re.compile("(?<=[%s]) +(?=[%s])" % (_CJK, _CJK))


def clean_cjk_spacing(text):
    return _CJK_SPACE.sub("", text)


def available_ocr_languages():
    from winsdk.windows.media.ocr import OcrEngine

    return [l.language_tag for l in OcrEngine.available_recognizer_languages]


def pick_ocr_language(source_lang):
    """按源语言选 OCR 语言；未安装对应语言包时降级到用户配置语言，并记日志提示。"""
    avail = available_ocr_languages()
    want = LANG_TAGS.get(source_lang)
    if want and any(a.lower().startswith(want.split("-")[0].lower()) for a in avail):
        return want
    log.warning(
        "Windows 未安装 %s 的 OCR 语言包（当前可用: %s）。"
        "可到 设置→时间和语言→语言 添加对应语言。本次使用系统默认语言识别。",
        want or source_lang, avail,
    )
    return None  # None = 用户配置语言


def ocr_image(image_path, lang_tag=None):
    """对图片文件做 OCR，返回识别文本（可能为空字符串）。"""
    from winsdk.windows.globalization import Language
    from winsdk.windows.graphics.imaging import BitmapDecoder
    from winsdk.windows.media.ocr import OcrEngine
    from winsdk.windows.storage import FileAccessMode, StorageFile

    async def _run():
        f = await StorageFile.get_file_from_path_async(image_path)
        stream = await f.open_async(FileAccessMode.READ)
        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()
        if lang_tag:
            engine = OcrEngine.try_create_from_language(Language(lang_tag))
        else:
            engine = OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            raise RuntimeError(f"OCR 引擎创建失败（语言包缺失？{lang_tag}）")
        result = await engine.recognize_async(bitmap)
        return result.text

    return asyncio.run(_run())


class SnipOverlay(QWidget):
    """全屏选区层：显示触发瞬间冻结的屏幕画面（半透明压暗），拖拽框选，Esc 取消。

    用冻结截图做背景而不是直接透视桌面：松开后直接从冻结图裁剪，
    避免"选区层还没来得及从屏幕消失就截图"导致的偶发识别为空。"""

    region_selected = pyqtSignal(QRect)
    cancelled = pyqtSignal()

    def __init__(self, bg_pixmap=None):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.CrossCursor)
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)
        self._bg = bg_pixmap  # 触发瞬间的屏幕截图（物理像素，自带 devicePixelRatio）
        self._origin = None
        self._rect = QRect()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._origin = e.pos()
            self._rect = QRect()

    def mouseMoveEvent(self, e):
        if self._origin is not None:
            self._rect = QRect(self._origin, e.pos()).normalized()
            self.update()

    def mouseReleaseEvent(self, e):
        if self._origin is None:
            return
        rect = QRect(self._origin, e.pos()).normalized()
        self._origin = None
        self.hide()
        if rect.width() >= 10 and rect.height() >= 10:
            self.region_selected.emit(rect)
        else:
            self.cancelled.emit()  # 点了一下没拖出区域，视为取消

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.hide()
            self.cancelled.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        if self._bg is not None and not self._bg.isNull():
            p.drawPixmap(self.rect(), self._bg)  # Qt 按 devicePixelRatio 自动缩放
        p.fillRect(self.rect(), QColor(0, 0, 0, 100))
        if not self._rect.isNull():
            # 选区挖空 + 蓝框
            p.setCompositionMode(QPainter.CompositionMode_Clear)
            p.fillRect(self._rect, QColor(0, 0, 0, 0))
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            p.setPen(QPen(QColor(79, 140, 255), 2))
            p.drawRect(self._rect)


class OcrResultPopup(QWidget):
    """译文弹窗：显示在选区附近，点击或超时自动关闭。"""

    def __init__(self, src, zh, anchor: QRect, cfg=None):
        super().__init__()
        cfg = cfg or {}
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        label = QLabel(self)
        font_size = int(cfg.get("font_size", 15))
        bg_alpha = int(cfg.get("bg_alpha", 235))
        zh_color = cfg.get("zh_color", "#FFE34D")  # 默认与字幕译文颜色一致
        src_color = cfg.get("src_color", "#FFFFFF")
        label.setStyleSheet(
            f"background: rgba(23,23,29,{bg_alpha}); color: {zh_color}; border-radius: 8px;"
            f"padding: 12px 16px; font-family: 'Microsoft YaHei'; font-size: {font_size}px;"
        )
        mode = cfg.get("display_mode", "both")  # both / zh / src
        # 原文行：用原文颜色调暗 + 小一号字（QLabel 富文本不支持 rgba 时退化为灰色）
        dim_src = QColor(src_color)
        dim_src_css = (
            f"rgba({dim_src.red()},{dim_src.green()},{dim_src.blue()},150)"
            if dim_src.isValid() else "#9a9aa5"
        )
        if mode == "src":
            text = escape(src) if src else escape(zh or "") or tr("（无译文）")
            if src:
                label.setStyleSheet(
                    label.styleSheet().replace(f"color: {zh_color}", f"color: {src_color}")
                )
        elif mode == "zh":
            text = escape(zh) if zh else tr("（无译文）")
        else:
            text = escape(zh) if zh else tr("（无译文）")
            if src:
                text = f"{text}\n\n<span style='color:{dim_src_css};font-size:{max(font_size - 3, 9)}px'>{escape(src)}</span>"
        label.setText(text)
        label.setTextFormat(Qt.RichText)  # 转义后的实体 + span 样式按富文本渲染
        label.setWordWrap(True)
        label.setMaximumWidth(520)
        label.adjustSize()
        self.resize(label.size())

        # 默认放选区正下方，越界则挪到上方/屏幕内
        screen = QApplication.primaryScreen().availableGeometry()
        x = min(anchor.x(), screen.right() - self.width() - 10)
        y = anchor.bottom() + 8
        if y + self.height() > screen.bottom():
            y = anchor.top() - self.height() - 8
        self.move(max(screen.left() + 10, x), max(screen.top() + 10, y))

        duration = int(cfg.get("duration_ms", 8000))
        if duration > 0:
            from PyQt5.QtCore import QTimer

            QTimer.singleShot(duration, self.close)

    def mousePressEvent(self, e):
        self.close()


def grab_region(rect: QRect):
    """截取屏幕区域保存为临时 PNG，返回文件路径。失败返回 None。"""
    screen = QApplication.primaryScreen()
    pix = screen.grabWindow(0, rect.x(), rect.y(), rect.width(), rect.height())
    return save_pixmap(pix)


def save_pixmap(pix):
    """把 QPixmap 存为临时 PNG，返回文件路径。失败返回 None。"""
    if pix is None or pix.isNull():
        return None
    fd, path = tempfile.mkstemp(suffix=".png", prefix="rts_ocr_")
    os.close(fd)
    if not pix.save(path, "PNG"):
        os.remove(path)
        return None
    return path


def crop_frozen(pixmap, rect: QRect):
    """从触发时冻结的屏幕图裁剪选区（逻辑坐标 → 物理像素，考虑 DPI 缩放），
    保存为临时 PNG 返回路径；pixmap 无效时返回 None（调用方可回退 grab_region）。"""
    if pixmap is None or pixmap.isNull():
        return None
    dpr = pixmap.devicePixelRatio()
    if dpr and dpr != 1.0:
        rect = QRect(
            round(rect.x() * dpr), round(rect.y() * dpr),
            round(rect.width() * dpr), round(rect.height() * dpr),
        )
    return save_pixmap(pixmap.copy(rect))
