"""用 Qt 渲染一段文字成图片，再跑真实 Windows OCR 验证 winsdk 链路。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import main  # noqa: F401

import PyQt5
from PyQt5.QtCore import QCoreApplication
from PyQt5.QtGui import QColor, QFont, QImage, QPainter
from PyQt5.QtWidgets import QApplication

QCoreApplication.addLibraryPath(
    os.path.join(os.path.dirname(PyQt5.__file__), "Qt5", "plugins")
)
app = QApplication([])

# offscreen 平台不加载系统字体库，手动注册雅黑字体才能画出文字
from PyQt5.QtGui import QFontDatabase
fid = QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
print("font loaded:", fid, QFontDatabase.applicationFontFamilies(fid))

import tempfile
img = QImage(600, 120, QImage.Format_RGB32)
img.fill(QColor("white"))
p = QPainter(img)
p.setPen(QColor("black"))
p.setFont(QFont("Microsoft YaHei", 28))
p.drawText(img.rect(), 0, "你好世界，这是识别测试")
p.end()
# 项目路径含中文，先存到纯英文临时路径排除路径编码问题
path = os.path.join(tempfile.gettempdir(), "rts_ocr_dbg.png")
ok = img.save(path, "PNG")
print("image saved:", path, ok, img.size().width(), img.size().height())
# 校验图像非全白
colors = set()
for x in range(0, 600, 7):
    for y in range(0, 120, 7):
        colors.add(img.pixel(x, y))
print("distinct sampled colors:", len(colors))

from app.ocr_tool import ocr_image, pick_ocr_language

lang = pick_ocr_language("zh")
print("OCR lang:", lang)
text = ocr_image(path, lang)
print("OCR result:", repr(text))
os.remove(path)
# Windows OCR 对中日文逐字加空格，比对前去掉空格（个别字误识别不影响链路验证）
print("OCR_E2E_OK" if "你好世界" in text.replace(" ", "") else "OCR_E2E_FAIL")
