"""术语表界面回归：设置页能把配置里的术语表读进编辑框、改完保存回配置。

复现的坑：术语表在配置里是列表（每行一条“原文=译文”），在界面上是多行文本框，
两边转换一旦对不上，用户填的词条就不生效，或者保存一次把注释/空行写乱。
这里直接构造设置窗口走一遍 读 → 改 → 保存，并确认界面上写清了“仅大模型后端生效”。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import main  # noqa: F401  安全导入顺序

import PyQt5
from PyQt5.QtCore import QCoreApplication

QCoreApplication.addLibraryPath(
    os.path.join(os.path.dirname(PyQt5.__file__), "Qt5", "plugins")
)
from PyQt5.QtWidgets import QApplication, QLabel

app = QApplication([])

from ruamel.yaml import YAML

from app.settings_window import SettingsWindow

failures = []


def check(label, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + label + ("" if cond else f"  {detail}"))
    if not cond:
        failures.append(label)


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(ROOT, "config.example.yaml"), encoding="utf-8") as f:
    cfg = YAML(typ="safe").load(f)
cfg.setdefault("translator", {})["glossary"] = ["原神=Genshin Impact", "  元素爆发=Elemental Burst  "]

win = SettingsWindow(cfg)

# ---- 1. 读：配置里的列表逐行进编辑框（原样显示，不偷偷改用户的书写）----
check("编辑框按行读入配置里的术语表",
      win.edit_glossary.toPlainText().splitlines()
      == ["原神=Genshin Impact", "  元素爆发=Elemental Burst  "],
      repr(win.edit_glossary.toPlainText()))

# ---- 2. 界面必须写明只有大模型后端吃词典（否则用户以为有道/Google 也生效）----
page = win.pages.widget(3)  # 翻译服务页
labels = [lb.text() for lb in page.findChildren(QLabel)]
check("翻译页写明了“仅大模型后端生效”",
      any("只对“大模型 API”后端生效" in t for t in labels))
check("翻译页有术语表输入框", win.edit_glossary.parent() is not None)

# ---- 3. 改 → 存：空行丢掉，注释与空格原样留给用户（解析时会被跳过）----
applied = []
win.request_apply.connect(lambda c: applied.append(c))
win.edit_glossary.setPlainText("# 游戏术语\n原神=Genshin Impact\n\n派蒙=Paimon  \n")
win._on_apply()
check("保存后 config 里的术语表逐行对得上",
      cfg["translator"]["glossary"] == ["# 游戏术语", "原神=Genshin Impact", "派蒙=Paimon"],
      repr(cfg["translator"]["glossary"]))
check("保存会通知主程序（否则改了不生效）", len(applied) == 1)

# ---- 4. 清空：写成空列表而不是 None/空串（配置干净，也不触发无谓的翻译链重建）----
win.edit_glossary.setPlainText("\n\n")
win._on_apply()
check("清空后写回空列表", cfg["translator"]["glossary"] == [],
      repr(cfg["translator"]["glossary"]))

print("GLOSSARY_UI_FAIL: " + "; ".join(failures) if failures else "GLOSSARY_UI_OK")
sys.exit(1 if failures else 0)
