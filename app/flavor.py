"""安装变体（flavor）识别：CPU 小包 / CUDA 完整包。

两个包的内容差异只有一处：CUDA 包多带 `nvidia/*/bin/*.dll`（cuBLAS 等），
其余文件逐字节相同（构建时由 `tools/package_release.py` 保证并校验）。

包内随附 `flavor.json`（构建时写入，随包发布）：
    {"flavor": "cpu"|"cuda", "version": "1.4.0", "commit": "abc1234"}

更新的选包原则：**包跟着"装的是什么"走，不跟着硬件走**——
CPU 包用户不会被塞 750 MB，CUDA 包用户不会被静默降级（那等于悄悄拿走他的 GPU 加速）。
判断顺序：包内标记 → 旧安装（≤1.3.9 没有标记）按硬件与配置保守推断。详见 v1.4.0 规划 §1.6。
"""

import ctypes
import glob
import json
import logging
import os
import sys

log = logging.getLogger("subtitle.flavor")

CPU = "cpu"
CUDA = "cuda"

MARKER_NAME = "flavor.json"


def cuda_lib_dirs():
    """CUDA 运行库所在目录（打包后是 _internal/nvidia/*/bin，开发环境是 site-packages）。"""
    if getattr(sys, "frozen", False):
        roots = [getattr(sys, "_MEIPASS", sys.prefix)]
    else:
        roots = [os.path.join(sys.prefix, "Lib", "site-packages")]
    dirs = []
    for root in dict.fromkeys(roots):
        dirs += glob.glob(os.path.join(root, "nvidia", "*", "bin"))
    return dirs


def has_cuda_libs():
    """当前安装（或开发环境）是否带 CUDA 运行库。

    注意：**不能**用 `ctranslate2.get_cuda_device_count()` 代替本函数——没有 cuBLAS
    时它照样返回机器上的显卡数量（实测），会把 CPU 包误判成 CUDA 包。
    """
    return any(glob.glob(os.path.join(d, "*.dll")) for d in cuda_lib_dirs())


def nvcuda_available():
    """显卡驱动是否存在（能加载 nvcuda.dll）→ 机器上有可用的 N 卡。

    仅用于"要不要提示切换到 CUDA 版"这类引导，不用于判断当前装的是哪种包。
    """
    try:
        ctypes.WinDLL("nvcuda.dll")
        return True
    except OSError:
        return False
    except Exception:  # 非 Windows 等异常情况：当作没有
        return False


def read_marker(base_dir=None):
    """读包内 flavor.json，返回 dict；没有/损坏返回 None（≤1.3.9 的旧安装没有它）。"""
    if base_dir is None:
        from .paths import base_dir as _bd

        base_dir = _bd()
    try:
        with open(os.path.join(base_dir, MARKER_NAME), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    flavor = str(data.get("flavor") or "").lower()
    if flavor not in (CPU, CUDA):
        log.warning("flavor.json 内容异常，忽略: %r", data)
        return None
    data["flavor"] = flavor
    return data


def current(cfg_device="", base_dir=None):
    """当前安装的变体（"cpu" / "cuda"）。

    1. 包内标记优先（最可靠，切换包型后随包更新）；
    2. 没有标记（≤1.3.9 旧安装、源码运行、手工拆包）→ 按"配置要 GPU 且机器有 N 卡"推断;
       否则给 CPU 小包（对无卡用户是纯赚，对误判用户有设置页的切换入口兜底）。
    """
    marker = read_marker(base_dir)
    if marker:
        flavor = marker["flavor"]
        # 自检：标记说 cuda 但目录里没有 CUDA 库 = 安装不完整/被手工裁剪过，
        # 按实际能力当 CPU 对待，避免更新后仍然拉 750 MB 却始终用不上 GPU
        if flavor == CUDA and not has_cuda_libs():
            log.warning("标记为 CUDA 包但目录里没有 CUDA 运行库，按 CPU 包对待")
            return CPU
        return flavor
    return CUDA if (str(cfg_device or "").lower() == CUDA and nvcuda_available()) else CPU


def switch_suggestion(base_dir=None):
    """该向用户建议切换到哪种包型（"cuda"/"cpu"），无需切换时返回 None。

    只在"确实是安装包"（包内有标记）时才给建议：源码运行时切换毫无意义，
    而且会把安装包覆盖到源码目录上。
    """
    if read_marker(base_dir) is None:
        return None
    cur = current(base_dir=base_dir)
    if cur == CPU and nvcuda_available():
        return CUDA  # 换了 N 卡：小包里没有 cuBLAS，改 device 也启用不了 GPU
    if cur == CUDA and not nvcuda_available():
        return CPU  # 没有 N 卡（换机/驱动没了）：完整版每次更新都白下 600 MB
    return None
