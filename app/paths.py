"""路径解析：统一处理开发环境与 PyInstaller 打包后的目录布局。"""

import os
import sys


def base_dir():
    """程序数据目录（config.yaml、app.log、models/ 所在处）。

    打包后为 exe 所在目录，开发时为项目根目录。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(rel):
    """只读资源（图标等打包进程序的文件）：打包后在 _internal 里。"""
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, rel)
    return os.path.join(base_dir(), rel)
