# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：生成 onedir 版 exe（模型不打包，首次运行自动下载）。

构建：.venv\\Scripts\\python -m PyInstaller --noconfirm --clean subtitle.spec
输出：dist\\实时翻译字幕\\实时翻译字幕.exe
"""
import glob
import os
import sysconfig

from PyInstaller.utils.hooks import collect_data_files

site_packages = sysconfig.get_paths()["purelib"]

# NVIDIA cuBLAS/cuDNN DLL：ctranslate2 GPU 推理必需，PyInstaller 不会自动收集
binaries = []
for d in glob.glob(os.path.join(site_packages, "nvidia", "*", "bin")):
    for dll in glob.glob(os.path.join(d, "*.dll")):
        binaries.append((dll, os.path.relpath(d, site_packages)))

# silero VAD 模型文件（faster_whisper 包自带）+ 应用图标
datas = collect_data_files("faster_whisper", includes=["assets/*"])
datas += [("assets/icon.ico", "assets")]


a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=["sentencepiece"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="实时翻译字幕",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # 无控制台窗口（调试打包问题时可临时改 True）
    icon="assets/icon.ico",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="实时翻译字幕",
)
