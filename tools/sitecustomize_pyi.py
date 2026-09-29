"""PyInstaller 构建专用：预先按安全顺序导入原生扩展包。

背景：PyInstaller 分析依赖时会在子进程里先导入 PyQt5 再导入
onnxruntime/sentencepiece 等包，这个顺序在 Windows 上会段错误。
build.bat 会把本文件复制为 .venv/Lib/site-packages/sitecustomize.py
并设置 PYI_SAFE_IMPORT=1，使每个 Python 进程启动时先加载这些包。
"""

import os

if os.environ.get("PYI_SAFE_IMPORT"):
    import onnxruntime  # noqa: F401
    import faster_whisper  # noqa: F401
    import ctranslate2  # noqa: F401
    import sentencepiece  # noqa: F401
