"""音频电平 / VAD 状态指示的界面回归（规划 §5.2）。

界面只读捕获线程自记的电平（不消费音频队列），所以这里用一个假的
status_provider 喂数据，验证：dB 换算、条与文字跟着状态变、未监听时归零、
数据源异常时界面不炸。
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
from PyQt5.QtWidgets import QApplication

app = QApplication([])

from ruamel.yaml import YAML

from app.settings_window import SettingsWindow, level_percent

failures = []


def check(label, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + label + ("" if cond else f"  {detail}"))
    if not cond:
        failures.append(label)


# ---- 1. 峰値 → 条百分比：底噪留空、正常语音占大半、满刻度封顶 ----
check("静音（0）不点亮", level_percent(0) == 0, level_percent(0))
check("底噪（约 -50dB 以下）不点亮", level_percent(0.003) == 0, level_percent(0.003))
check("小声说话也看得见条动", 25 <= level_percent(0.02) <= 60, level_percent(0.02))
check("正常语音占大半", 70 <= level_percent(0.5) <= 100, level_percent(0.5))
check("满刻度封顶 100", level_percent(1.0) == 100 and level_percent(5.0) == 100)
check("脏数据不炸", level_percent(None) == 0 and level_percent("x") == 0)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(ROOT, "config.example.yaml"), encoding="utf-8") as f:
    cfg = YAML(typ="safe").load(f)

state = {"level": 0.5, "speech": True, "listening": True}


def provider():
    if state["boom"]:
        raise RuntimeError("数据源炸了")
    return state["level"], state["speech"], state["listening"]


state["boom"] = False
win = SettingsWindow(cfg, status_provider=provider)

# ---- 2. 有声音 + 检测到人声 ----
win._refresh_audio_status()
check("电平条跟着电平走", win.level_bar.value() == level_percent(0.5), win.level_bar.value())
check("说话时显示“检测到人声”", win.level_state.text() == "检测到人声", win.level_state.text())

# ---- 3. 在监听但没人说话 ----
state.update(speech=False, level=0.0)
win._refresh_audio_status()
check("没人说话时显示“静音”且条归零",
      win.level_state.text() == "静音" and win.level_bar.value() == 0,
      f"{win.level_state.text()} / {win.level_bar.value()}")

# ---- 4. 没在监听：不显示残留电平 ----
state.update(listening=False, level=0.8)
win._refresh_audio_status()
check("未监听时显示“未监听”且条归零",
      win.level_state.text() == "未监听" and win.level_bar.value() == 0,
      f"{win.level_state.text()} / {win.level_bar.value()}")

# ---- 5. 数据源异常：界面静默保持，不抛异常 ----
state["boom"] = True
try:
    win._refresh_audio_status()
    ok = True
except Exception as e:  # noqa: BLE001
    ok = False
    check("数据源异常时界面不炸", False, repr(e))
if ok:
    check("数据源异常时界面不炸", True)

# ---- 6. 定时器：只在窗口可见时刷（150ms）----
check("电平定时器间隔 150ms", win._level_timer.interval() == 150)
check("刚构造时定时器没在跑（窗口不可见）", not win._level_timer.isActive())

print("AUDIO_LEVEL_UI_FAIL: " + "; ".join(failures) if failures else "AUDIO_LEVEL_UI_OK")
sys.exit(1 if failures else 0)
