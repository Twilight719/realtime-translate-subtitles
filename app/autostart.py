"""开机自启动：读写 HKCU\\...\\Run 注册表项（仅打包版有意义）。"""

import os
import sys
import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "RealtimeTranslateSubtitles"


def _exe_cmd():
    return f'"{os.path.abspath(sys.executable)}"'


def is_supported():
    """开发模式（python main.py）下自启动没有意义。"""
    return bool(getattr(sys, "frozen", False))


def is_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            value, _ = winreg.QueryValueEx(k, VALUE_NAME)
        exe = os.path.abspath(sys.executable)
        return exe.lower() in value.lower()
    except OSError:
        return False


def set_enabled(enabled):
    """写入/删除自启动项。返回 None=成功，否则返回错误描述。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if enabled:
                winreg.SetValueEx(k, VALUE_NAME, 0, winreg.REG_SZ, _exe_cmd())
            else:
                try:
                    winreg.DeleteValue(k, VALUE_NAME)
                except FileNotFoundError:
                    pass
        return None
    except OSError as e:
        return str(e)
