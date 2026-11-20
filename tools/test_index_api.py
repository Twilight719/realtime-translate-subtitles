# -*- coding: utf-8 -*-
"""实测 Index-Translate 后端 + 看图直翻。"""
import sys

sys.path.insert(0, r"D:\翻译插件")

from app.translator import build_chain

# ① 纯 Index 后端
chain = build_chain({"order": ["index_api"]})
print("① 日→中:", chain.translate("君は変わらないね。これからもずっと一緒にいよう。", "ja", "zh"))
print("① 英→中:", chain.translate("We are gonna beat the game together.", "en", "zh"))

# 流式测试（定稿字幕用）
acc = []
zh = chain.translate("hello world, nice to meet you", "en", "zh", on_delta=lambda a: acc.append(a))
print("① 流式结果:", zh, "| 回调次数:", len(acc))

# ② 看图直翻：用 Qt 造一张带日语文字的测试图（不引入 PIL 依赖）
import os
import PyQt5
from PyQt5.QtCore import QCoreApplication

QCoreApplication.addLibraryPath(
    os.path.join(os.path.dirname(PyQt5.__file__), "Qt5", "plugins")
)
from PyQt5.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter

app = QGuiApplication([])
img = QImage(900, 300, QImage.Format_RGB32)
img.fill(QColor("white"))
p = QPainter(img)
p.setFont(QFont("Yu Gothic", 28))
p.setPen(QColor("black"))
p.drawText(30, 100, "君は変わらないね。")
p.drawText(30, 200, "これからもずっと一緒にいよう。")
p.end()
img.save(r"D:\翻译插件\tools\.vision_test.png")

from app.ocr_tool import vision_translate_image

src, zh = vision_translate_image(r"D:\翻译插件\tools\.vision_test.png", "ja", "zh")
print("② 看图直翻 原文:", src)
print("② 看图直翻 译文:", zh)
