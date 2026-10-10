# -*- coding: utf-8 -*-
"""验证截图翻译冻结图方案：选区层显示冻结画面；裁剪结果不被压暗且 DPI 尺寸正确。"""
import os
import sys

sys.path.insert(0, r"D:\翻译插件")

import PyQt5
from PyQt5.QtCore import QCoreApplication, QPoint, Qt
from PyQt5.QtGui import QMouseEvent

QCoreApplication.addLibraryPath(
    os.path.join(os.path.dirname(PyQt5.__file__), "Qt5", "plugins")
)

from PyQt5.QtGui import QGuiApplication, QImage
from PyQt5.QtWidgets import QApplication

from app.ocr_tool import SnipOverlay, crop_frozen

app = QApplication([])
screen = QApplication.primaryScreen()
frozen = screen.grabWindow(0)
print("frozen size:", frozen.width(), "x", frozen.height(), "dpr:", frozen.devicePixelRatio())

got = []
ov = SnipOverlay(frozen)
ov.region_selected.connect(lambda r: got.append(r))
ov.show()
app.processEvents()

# 模拟拖拽：按下 (200,200) → 移动到 (600,400) → 松开
press = QMouseEvent(QMouseEvent.MouseButtonPress, QPoint(200, 200), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
move = QMouseEvent(QMouseEvent.MouseMove, QPoint(600, 400), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
release = QMouseEvent(QMouseEvent.MouseButtonRelease, QPoint(600, 400), Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
ov.mousePressEvent(press)
ov.mouseMoveEvent(move)
ov.mouseReleaseEvent(release)
app.processEvents()

assert got, "region_selected 未触发"
rect = got[0]
print("selected rect:", rect.x(), rect.y(), rect.width(), "x", rect.height())

path = crop_frozen(frozen, rect)
assert path, "crop_frozen 失败"
img = QImage(path)
print("crop size:", img.width(), "x", img.height())
dpr = frozen.devicePixelRatio()
assert abs(img.width() - round(rect.width() * dpr)) <= 2, "DPI 裁剪宽度不符"

# 亮度校验：裁剪图应与屏幕原内容亮度接近（若抓到压暗层会明显偏暗）
def mean_brightness(image):
    image = image.scaled(50, 30)
    total = 0
    for y in range(image.height()):
        for x in range(image.width()):
            c = image.pixelColor(x, y)
            total += (c.red() + c.green() + c.blue()) / 3
    return total / (image.width() * image.height())

crop_b = mean_brightness(img)
# 对照组：此刻直接重新截取同一区域（选区层已 hide）。两者亮度应接近；
# 若裁剪图抓到的是压暗层，会比直接截取暗一大截（压暗层 alpha=100 ≈ 39% 亮度损失起步）
fresh = screen.grabWindow(0, rect.x(), rect.y(), rect.width(), rect.height()).toImage()
fresh_b = mean_brightness(fresh)
print("crop brightness:", round(crop_b, 1), "| fresh grab brightness:", round(fresh_b, 1))
assert crop_b > fresh_b * 0.7, "裁剪图比直接截取暗很多（可能抓到压暗层）"
os.remove(path)
ov.close()
print("ALL PASS")
