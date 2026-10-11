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
# cuda_nvrtc 不打：178 MB。2026-10-11 实测（隐藏 .venv 里的 nvidia/cuda_nvrtc 后
#   跑 whisper small fp16 GPU 识别正常）确认不是运行时必需。
binaries = []
for d in glob.glob(os.path.join(site_packages, "nvidia", "*", "bin")):
    if "cudnn" in d.lower() or "nvrtc" in d.lower():
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
        # sensevoice_engine 里是延迟导入，静态分析发现不了，必须显式声明
        + ["sentencepiece", "truststore", "sherpa_onnx"]  # truststore：打包后仍能走系统证书库，否则检查更新报证书错误
        # ocr_tool 里的 winsdk 导入是函数内延迟导入，静态分析会漏
        + ["winsdk.windows.media.ocr", "winsdk.windows.graphics.imaging",
           "winsdk.windows.storage", "winsdk.windows.globalization"]
    ),
    hookspath=[],
    # pyi_rth_preload 须在 PyQt5 rthook 之前预加载原生库；pyi_rth_no_av 用空壳顶掉 PyAV
    runtime_hooks=["tools/pyi_rth_preload.py", "tools/pyi_rth_no_av.py"],
    # hf_xet：应用已设 HF_HUB_DISABLE_XET=1（见 sensevoice/whisper 的下载路径），
    # huggingface_hub 找不到它会优雅降级，省 8.9 MB
    # av：本应用不解码音频文件，只被 faster_whisper 导入期引用一次，
    # 由 pyi_rth_no_av.py 顶成空壳，省掉 av + av.libs 约 65 MB
    #   （2026-10-11 实测 65.5 MiB = av 2.9 + av.libs 62.6；规划里的 129.4 MB
    #    出自旧构建——那份包里混了两代 av 库 avcodec-62 与 -63，各算了一遍）
    excludes=["hf_xet", "av"],
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
