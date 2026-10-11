"""热键重绑回归测试：多次重绑 + GC 后，热键回调仍应触发；stop() 后必须彻底失效。

复现的 bug：旧 HotkeyManager.stop() 不移除 native event filter，旧管理器被 GC 后
Qt 过滤器链悬挂，热键消息静默丢失。

注入方式：PostThreadMessageW(WM_HOTKEY) 直接往本线程消息队列投递，由 Qt 事件循环
派发给事件过滤器。不依赖真实键盘注入（keybd_event 在无桌面/沙箱环境必失败）。
"""
import ctypes
import gc
import os
import sys

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
kernel32 = ctypes.windll.kernel32
WM_HOTKEY = 0x0312
HOTKEY_ID = 0xB010

fired = []
mgr = None
failures = []


def check(label, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + label + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(label)


def fire(hotkey_id=HOTKEY_ID):
    """往本线程消息队列投递一条 WM_HOTKEY，交给 Qt 事件循环派发。"""
    if not user32.PostThreadMessageW(
        kernel32.GetCurrentThreadId(), WM_HOTKEY, hotkey_id, 0
    ):
        raise OSError("PostThreadMessageW 失败")


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


# 结构断言用：跟踪 QApplication 上实际装着的 native event filter。
# 只靠“消息是否触发”判不出过滤器泄漏（泄漏的过滤器往往是静默失效、不误触发），
# 而旧 bug 的根因正是 stop() 不摘过滤器 → 必须直接盯住装/卸动作。
live_filters = []
_real_install = app.installNativeEventFilter
_real_remove = app.removeNativeEventFilter


def spy_install(f):
    live_filters.append(f)
    _real_install(f)


def spy_remove(f):
    if f in live_filters:
        live_filters.remove(f)
    _real_remove(f)


app.installNativeEventFilter = spy_install
app.removeNativeEventFilter = spy_remove

rebind("ctrl+alt+f11", HOTKEY_ID)
for _ in range(3):
    rebind("ctrl+alt+f11", HOTKEY_ID)  # 同一个键反复重绑
    rebind("ctrl+shift+f11", HOTKEY_ID)
    rebind("ctrl+alt+f11", HOTKEY_ID)

fire(HOTKEY_ID)
pump(1.0)
check("重绑 + GC 后热键仍能触发", fired == ["ctrl+alt+f11"])
check("多次重绑后只留一个活跃过滤器（无泄漏）", len(live_filters) == 1,
      f"live_filters={len(live_filters)}")

fire(HOTKEY_ID + 1)  # 其他热键 id 不应命中本回调
pump(0.5)
check("其他热键 id 不触发", fired == ["ctrl+alt+f11"])

mgr.stop()
fire(HOTKEY_ID)  # 已停止：过滤器必须已移除，否则老代码会在这里多触发一次
pump(0.5)
check("stop() 后不再触发", fired == ["ctrl+alt+f11"])
check("stop() 后过滤器已全部摘除（不会悬挂）", not live_filters,
      f"live_filters={len(live_filters)}")

rebind("ctrl+shift+f11", HOTKEY_ID)  # 停止后再重绑应恢复正常
fire(HOTKEY_ID)
pump(1.0)
check("重新注册后恢复触发", len(fired) == 2 and fired[-1] == "ctrl+shift+f11")

mgr.stop()
print("fired:", fired)
if failures:
    print("HOTKEY_REGRESSION_FAIL: " + "; ".join(failures))
else:
    print("HOTKEY_REGRESSION_OK")
sys.exit(1 if failures else 0)
