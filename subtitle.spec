# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：生成 onedir 版 exe（模型不打包，首次运行自动下载）。

构建：.venv\\Scripts\\python -m PyInstaller --noconfirm --clean subtitle.spec
输出：dist\\实时翻译字幕\\实时翻译字幕.exe
"""
import glob
import os
import sysconfig

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

site_packages = sysconfig.get_paths()["purelib"]

# NVIDIA cuBLAS DLL：ctranslate2 GPU 推理必需，PyInstaller 不会自动收集。
# cuDNN 不打：ctranslate2 包自带 cudnn64_9.dll（重复打包白白大 700MB+）
binaries = []
for d in glob.glob(os.path.join(site_packages, "nvidia", "*", "bin")):
    if "cudnn" in d.lower():
        continue
    for dll in glob.glob(os.path.join(d, "*.dll")):
        binaries.append((dll, os.path.relpath(d, site_packages)))

# VC++ 运行时：大包构建时 PyInstaller 可能漏收 MSVCP140_1.dll，
# 缺失会导致 onnxruntime 加载时访问冲突（段错误）
for vc in ["msvcp140_1.dll", "msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"]:
    p = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", vc)
    if os.path.exists(p):
        binaries.append((p, "."))

# silero VAD 模型文件（faster_whisper 包自带）+ 应用图标
datas = collect_data_files("faster_whisper", includes=["assets/*"])
datas += [("assets/icon.ico", "assets")]


a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    # ctranslate2/faster_whisper 的子模块在冻结环境会被漏收（其 __init__ 里的
    # “from 包名 import 子模块” modulegraph 跟踪不到），显式全量收集
    hiddenimports=(
        collect_submodules("ctranslate2")
        + collect_submodules("faster_whisper")
        + ["sentencepiece"]
    ),
    hookspath=[],
    runtime_hooks=["tools/pyi_rth_preload.py"],  # 须在 PyQt5 rthook 之前预加载原生库
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
