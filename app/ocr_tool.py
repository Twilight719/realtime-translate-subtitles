"""截图 OCR 翻译：框选屏幕区域 → Windows 内置 OCR → 走翻译链 → 区域旁弹窗显示译文。

OCR 用 Windows.Media.Ocr（系统自带，无需下载模型）。识别语言：设置里锁定了源语言就
按它选引擎；「自动检测」则用系统默认引擎 + 已装的中/日/韩/俄引擎各识别一遍，按字符集
判据挑一个（`ocr_image_multi`，判据见 app/lang_detect.py）——中文引擎读日语会把假名
认成形近汉字（"こんにちは"→"乙 、今 日 00"），只跑默认引擎就是"日语被认成中日混合"。
日语等语言包没装时：锁定语言的路径降级到系统默认引擎并记日志（界面会给一次提示）。
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
from .lang_detect import analyze, choose_ocr_text, tag_lang  # 顶层导入：PyInstaller 静态分析才收得到
from . import i18n_strings  # noqa: F401  注册中英文映射

log = logging.getLogger("subtitle")

# 源语言码 → Windows 语言标签
LANG_TAGS = {"zh": "zh-Hans-CN", "en": "en-US", "ja": "ja-JP", "ko": "ko-KR", "ru": "ru-RU"}

# 语言码 → 界面名（提示文案用；这些键在 i18n_strings.py 里已注册）
LANG_NAMES = {"zh": "中文", "en": "英语", "ja": "日语", "ko": "韩语", "ru": "俄语"}

# 自动检测模式下，除系统默认引擎外还额外跑哪些语言（装了才跑）。
# 实测单个引擎 5~8ms/次，四个引擎也就 20ms 上下，相对网络翻译可忽略
AUTO_ENGINES = ("zh", "ja", "ko", "ru")

# Windows OCR 对中日文逐字加空格（"你 好 世 界"），翻译前去掉 CJK 字符间的空格
_CJK = "　-〿぀-ヿ㐀-䶿一-鿿＀-￯"
_CJK_SPACE = re.compile("(?<=[%s]) +(?=[%s])" % (_CJK, _CJK))


def clean_cjk_spacing(text):
    return _CJK_SPACE.sub("", text)


def available_ocr_languages():
    from winsdk.windows.media.ocr import OcrEngine

    return [l.language_tag for l in OcrEngine.available_recognizer_languages]


def _installed_tag_map():
    """{语言码: 实际安装的 Windows 标签}，只收 AUTO_ENGINES 里的语言；zh 优先取简体。

    实际标签不一定是我们期望的规范形式——实测中文系统上日语引擎的标签是 "ja"
    而不是 "ja-JP"，所以一律以系统枚举出来的为准，别硬编码。
    """
    out = {}
    for tag in available_ocr_languages():
        code = tag_lang(tag)
        if code not in AUTO_ENGINES:
            continue
        if code not in out or (code == "zh" and tag.lower().startswith("zh-hans")):
            out[code] = tag
    return out


def pick_ocr_language(source_lang):
    """按源语言选 OCR 语言；未安装对应语言包时降级到用户配置语言，并记日志提示。

    返回**实际安装的标签**（不是 LANG_TAGS 里的规范形式）：以前返回硬编码标签，
    只装了 zh-Hant-TW 的机器会拿到 "zh-Hans-CN"、建引擎失败，截图翻译直接没反应。
    """
    code = tag_lang(LANG_TAGS.get(source_lang, source_lang))
    installed = _installed_tag_map()
    if code and code in installed:
        return installed[code]
    log.warning(
        "Windows 未安装 %s 的 OCR 语言包（当前可用: %s）。"
        "可到 设置→时间和语言→语言 添加对应语言。本次使用系统默认语言识别。",
        LANG_TAGS.get(source_lang, source_lang), available_ocr_languages(),
    )
    return None  # None = 用户配置语言


def pack_missing(language):
    """该语言的 OCR 语言包是否没装（"auto"/认不出的语言返回 False）。界面据此提示一次。"""
    code = tag_lang(LANG_TAGS.get(language, language))
    return bool(code) and code not in _installed_tag_map()


def _engine(lang_tag):
    """按标签建 OCR 引擎；lang_tag=None 表示系统默认（用户配置语言）。失败返回 None。"""
    from winsdk.windows.globalization import Language
    from winsdk.windows.media.ocr import OcrEngine

    if lang_tag:
        return OcrEngine.try_create_from_language(Language(lang_tag))
    return OcrEngine.try_create_from_user_profile_languages()


async def _decode_bitmap(image_path):
    from winsdk.windows.graphics.imaging import BitmapDecoder
    from winsdk.windows.storage import FileAccessMode, StorageFile

    f = await StorageFile.get_file_from_path_async(image_path)
    stream = await f.open_async(FileAccessMode.READ)
    decoder = await BitmapDecoder.create_async(stream)
    return await decoder.get_software_bitmap_async()


def _profile_tag():
    """系统默认 OCR 引擎实际用的语言标签（问不出来时返回 None）。"""
    try:
        engine = _engine(None)
        return engine.recognizer_language.language_tag if engine is not None else None
    except Exception:
        log.debug("读取系统默认 OCR 引擎的语言失败", exc_info=True)
        return None


def _recognize(image_path, tags):
    """一次解码、多个引擎依次识别 → {标签: 文本}；单个引擎失败只记日志，不拖垮整次。"""
    async def _run():
        bitmap = await _decode_bitmap(image_path)
        out = {}
        for tag in tags:
            engine = _engine(tag)
            if engine is None:
                continue
            try:
                out[tag] = (await engine.recognize_async(bitmap)).text
            except Exception:
                log.warning("OCR 引擎 %s 识别失败", tag, exc_info=True)
        return out

    return asyncio.run(_run())


def _brief(results):
    """一行日志用的判据摘要（调阈值时靠它攒真实样本）。"""
    return "，".join(
        "%s: 假名%d 汉字%d 简%d 繁%d" % (tag, s["kana"], s["han"], s["simp"], s["trad"])
        for tag, s in ((t, analyze(x)) for t, x in results.items())
    ) or "无结果"


def ocr_image(image_path, lang_tag=None):
    """按指定引擎（None = 系统默认）对图片做 OCR，返回识别文本（可能为空字符串）。"""
    async def _run():
        bitmap = await _decode_bitmap(image_path)
        engine = _engine(lang_tag)
        if engine is None:
            raise RuntimeError(f"OCR 引擎创建失败（语言包缺失？{lang_tag}）")
        result = await engine.recognize_async(bitmap)
        return result.text

    return asyncio.run(_run())


def ocr_image_multi(image_path):
    """自动检测模式：系统默认引擎 + 已装的中/日/韩/俄引擎各识别一遍，挑最可信的结果。

    返回 (文本, 判定语言码或 None)；None 表示判不出（拉丁/纯汉字/数字符号），
    调用方照旧把它传给翻译后端（有道/Google 真 auto），行为与改动前一致。
    """
    profile_tag = _profile_tag()
    tags = [profile_tag] if profile_tag else []
    installed = _installed_tag_map()
    for code in AUTO_ENGINES:
        tag = installed.get(code)
        if tag and tag not in tags:
            tags.append(tag)
    if not tags:
        raise RuntimeError("没有可用的 OCR 引擎（语言包缺失？）")

    results = _recognize(image_path, tags)
    if not results:
        raise RuntimeError("OCR 引擎均识别失败")
    text, lang = choose_ocr_text(results, profile_tag)
    chosen = next((t for t, v in results.items() if v == text), profile_tag or tags[0])
    log.info("OCR 多引擎[默认=%s]: %s → 选 %s（%s）",
             profile_tag or "无", _brief(results), chosen, lang or "语言未判定")
    return text, lang


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
