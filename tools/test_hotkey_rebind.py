"""热键重绑回归测试：多次重绑 + GC 后，热键回调仍应触发。

复现的 bug：旧 HotkeyManager.stop() 不移除 native event filter，旧管理器被 GC 后
Qt 过滤器链悬挂，热键消息静默丢失。
"""
import ctypes
import gc
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import main  # noqa: F401  安全导入顺序

import PyQt5
from PyQt5.QtCore import QCoreApplication, QEventLoop, QTimer

QCoreApplication.addLibraryPath(
    os.path.join(os.path.dirname(PyQt5.__file__), "Qt5", "plugins")
)
from PyQt5.QtWidgets import QApplication

app = QApplication([])

from app.hotkeys import HotkeyManager

user32 = ctypes.windll.user32
VK_MENU, VK_CONTROL, VK_SHIFT = 0x12, 0x11, 0x10
KEYUP = 0x0002

fired = []
mgr = None


def inject(hotkey):
    """keybd_event 注入组合键，如 ctrl+alt+f11。"""
    parts = hotkey.split("+")
    mods = {"alt": VK_MENU, "ctrl": VK_CONTROL, "shift": VK_SHIFT}
    for m in parts[:-1]:
        user32.keybd_event(mods[m], 0, 0, 0)
    k = parts[-1]
    key = 0x70 + int(k[1:]) - 1 if k.startswith("f") else ord(k.upper())
    user32.keybd_event(key, 0, 0, 0)
    user32.keybd_event(key, 0, KEYUP, 0)
    for m in parts[:-1]:
        user32.keybd_event(mods[m], 0, KEYUP, 0)


def pump(seconds=1.0):
    loop = QEventLoop()
    QTimer.singleShot(int(seconds * 1000), loop.quit)
    loop.exec_()


def rebind(hotkey, hotkey_id):
    """与 main._rebind_hotkey 相同顺序：先停旧的，再注册新的。"""
    global mgr
    if mgr is not None:
        mgr.stop()
    new = HotkeyManager(app=app, hotkey=hotkey, on_toggle=lambda: fired.append(hotkey),
                        hotkey_id=hotkey_id)
    new.start()
    old = mgr
    mgr = new
    del old
    gc.collect()  # 强制回收旧管理器——旧代码就是死在这一步之后


rebind("ctrl+alt+f11", 0xB010)
for i in range(3):
    rebind("ctrl+alt+f11", 0xB010)  # 同一个键反复重绑
    rebind("ctrl+shift+f11", 0xB010)
    rebind("ctrl+alt+f11", 0xB010)

inject("ctrl+alt+f11")
pump(1.5)
inject("ctrl+shift+f11")  # 已注销，不应触发
pump(1.0)
mgr.stop()

print("fired:", fired)
ok = fired == ["ctrl+alt+f11"]
print("HOTKEY_REGRESSION_OK" if ok else "HOTKEY_REGRESSION_FAIL")
sys.exit(0 if ok else 1)
