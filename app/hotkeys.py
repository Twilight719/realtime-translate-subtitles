"""全局快捷键：Win32 RegisterHotKey 实现（Qt 原生事件过滤器，可靠接收物理与合成按键）。"""

import ctypes
from ctypes import wintypes

from PyQt5.QtCore import QAbstractNativeEventFilter

WM_HOTKEY = 0x0312
MOD_NOREPEAT = 0x4000
MODIFIERS = {"alt": 0x0001, "ctrl": 0x0002, "shift": 0x0004, "win": 0x0008}

user32 = ctypes.windll.user32


def parse_hotkey(hotkey):
    """'alt+t' → (修饰键掩码, 虚拟键码)"""
    parts = [p.strip().lower() for p in hotkey.split("+")]
    mods = MOD_NOREPEAT
    for p in parts[:-1]:
        if p not in MODIFIERS:
            raise ValueError(f"未知修饰键: {p}")
        mods |= MODIFIERS[p]
    key = parts[-1]
    if len(key) == 1:
        vk = ord(key.upper())
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 12:
        vk = 0x70 + int(key[1:]) - 1
    else:
        raise ValueError(f"不支持的按键: {key}")
    return mods, vk


class _HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, hotkey_id, callback):
        super().__init__()
        self.hotkey_id = hotkey_id
        self.callback = callback

    def nativeEventFilter(self, event_type, message):
        msg = wintypes.MSG.from_address(int(message))
        if msg.message == WM_HOTKEY and msg.wParam == self.hotkey_id:
            self.callback()
        return False, 0


class HotkeyManager:
    """注册全局热键，触发时在 Qt 主线程回调。需在 QApplication 创建后使用。"""

    HOTKEY_ID = 0xB001

    def __init__(self, app, hotkey="alt+t", on_toggle=None, hotkey_id=None):
        self.app = app
        self.hotkey = hotkey
        self.on_toggle = on_toggle
        self.hotkey_id = hotkey_id if hotkey_id is not None else self.HOTKEY_ID
        self._filter = None
        self._mods = None
        self._vk = None

    def start(self):
        self._mods, self._vk = parse_hotkey(self.hotkey)
        if not user32.RegisterHotKey(None, self.hotkey_id, self._mods, self._vk):
            raise RuntimeError(f"注册全局热键失败: {self.hotkey}（可能被其他程序占用）")
        self._filter = _HotkeyFilter(self.hotkey_id, self._handle)
        self.app.installNativeEventFilter(self._filter)

    def _handle(self):
        if self.on_toggle:
            self.on_toggle()

    def stop(self):
        user32.UnregisterHotKey(None, self.hotkey_id)
