# -*- coding: utf-8 -*-
"""手工发版辅助：带测速与断点续传地下载 GitHub Release 更新包。

用途：软件内更新下载奇慢时（免费加速镜像的速度可在分钟级波动几百倍，2026-10-11 实测），
用本脚本先对每个通道测速、从最快的开始下；下载中滚动测速，通道变慢或断流时自动切换，
支持 Range 的通道带断点续传（不会从零重下）。

用法（项目根目录）:
    ./.venv/Scripts/python.exe -X utf8 tools/fetch_release.py           # 下载最新版
    ./.venv/Scripts/python.exe -X utf8 tools/fetch_release.py v1.3.9    # 指定 tag
    ... --flavor cuda              # 指定包型（默认自动：看安装目录 flavor.json，再看本机显卡）
    ... --install-dir "C:/rtbuild/dist/实时翻译字幕"   # 自动识别包型时读这个目录的 flavor.json
    ... --dest D:/somewhere        # 指定输出目录（默认系统临时目录）
    ... --keep-going               # 允许为换通道而丢弃进度（默认只在能续传时切换）

下载完成后打印路径与 sha256 校验结果，接着按 RELEASE.md 第 5 节方式 B 手工安装。
"""
import argparse
import hashlib
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import requests  # noqa: E402

# 与主程序一致：走 Windows 系统证书库校验 HTTPS（本机有 TLS 拦截时 certifi 会失败）
try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass

from app import flavor as flavor_mod  # noqa: E402
from app.updater import DOWNLOAD_MIRRORS, asset_for_flavor  # noqa: E402  选包/通道只维护一份
from app.version import GITHUB_REPO  # noqa: E402

PROBE_SECONDS = 4
PROBE_BYTES = 16 * 1024 * 1024   # 测速最多读这么多
WINDOW = 8                        # 滚动测速窗口（秒）
MIN_SPEED = 400 * 1024            # 低于此速度（B/s）判该通道"慢性死亡"
UA = {"User-Agent": "realtime-translate-subtitles-fetch-tool"}


def human(n):
    return f"{n / 1024 / 1024:.2f} MB/s" if n >= 1024 * 1024 else f"{n / 1024:.0f} KB/s"


def api(path, **kw):
    return requests.get(f"https://api.github.com/repos/{GITHUB_REPO}{path}",
                        headers=UA, timeout=15, **kw).json()


def detect_flavor(explicit, install_dir):
    """下载哪个包：--flavor 优先；否则读安装目录的 flavor.json（包型以已装的为准）；
    都没有（比如还没装过 v1.4.0）才按本机有没有 N 卡猜。"""
    if explicit:
        return explicit
    base = install_dir or os.getcwd()
    marker = flavor_mod.read_marker(base)
    if marker:
        fl = marker.get("flavor", flavor_mod.CPU)
        print(f"包型: {fl}（读自 {os.path.join(base, flavor_mod.MARKER_NAME)}）")
        return fl
    fl = flavor_mod.CUDA if flavor_mod.nvcuda_available() else flavor_mod.CPU
    print(f"包型: {fl}（{base} 没有 flavor.json，按本机是否有 N 卡判断）")
    return fl


def resolve_asset(tag, want_flavor):
    """取 (tag, asset dict)。tag 为空则取最新 Release。选包规则与主程序共用一份实现。"""
    data = api(f"/releases/tags/{tag}") if tag else api("/releases/latest")
    if "assets" not in data:
        raise SystemExit(f"取 Release 失败: {data.get('message', data)}")
    got = data.get("tag_name", tag)
    listing = "、".join(f"{a['name']}（{a['size'] / 1048576:.0f} MB）"
                       for a in data["assets"] if a["name"].endswith(".zip"))
    if listing:
        print(f"{got} 的 zip 附件: {listing}")
    picked = asset_for_flavor(data["assets"], want_flavor)
    if picked is None:
        raise SystemExit(f"{got} 缺少 {want_flavor} 版安装包"
                         f"（该发布只有: {listing or '无 zip 附件'}）；要用另一个包请显式 --flavor")
    return got, picked


def channels(asset_url):
    return [(m, m + asset_url) for m in DOWNLOAD_MIRRORS] + [("GitHub直连", asset_url)]


def probe(name, url):
    """读一小段测速；返回 (速度 B/s, 是否支持续传)。失败返回 (0, None)。"""
    try:
        t0, got = time.time(), 0
        with requests.get(url, headers={**UA, "Range": f"bytes=0-{PROBE_BYTES - 1}"},
                          stream=True, timeout=(8, 10), allow_redirects=True) as r:
            r.raise_for_status()
            resume = (r.status_code == 206)
            for chunk in r.iter_content(chunk_size=256 * 1024):
                got += len(chunk)
                if time.time() - t0 >= PROBE_SECONDS or got >= PROBE_BYTES:
                    break
        return got / max(time.time() - t0, 0.001), resume
    except Exception as e:
        print(f"  测速失败 {name}: {type(e).__name__}: {e}")
        return 0, None


def download(name, url, dest, size, resume_ok, offset):
    """下载到 dest（从 offset 起）。返回 'done' / 'slow' / 'error' / 'noresume'。"""
    headers = dict(UA)
    if offset:
        headers["Range"] = f"bytes={offset}-"
    try:
        with requests.get(url, headers=headers, stream=True, timeout=(8, 15),
                          allow_redirects=True) as r:
            if offset and r.status_code == 200:
                return "noresume"
            r.raise_for_status()
            with open(dest, "ab" if offset else "wb") as f:
                done, win_t0, win_bytes, last_print = offset, time.time(), 0, 0.0
                for chunk in r.iter_content(chunk_size=256 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)
                    win_bytes += len(chunk)
                    el = time.time() - win_t0
                    if el < WINDOW:
                        continue
                    speed = win_bytes / el
                    if time.time() - last_print > 3:
                        last_print = time.time()
                        print(f"    {human(speed)}  {done / 1048576:.0f}/{size / 1048576:.0f} MB"
                              f"（{done * 100 / size:.1f}%）")
                    if speed < MIN_SPEED:
                        return "slow"
                    win_t0, win_bytes = time.time(), 0
        return "done"
    except Exception as e:
        print(f"  通道出错 {name}: {type(e).__name__}: {e}")
        return "error"


def verify(dest, size, sha256):
    got = os.path.getsize(dest)
    if got != size:
        return f"大小不符: {got} != {size}"
    h = hashlib.sha256()
    with open(dest, "rb") as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    actual = h.hexdigest()
    print(f"  实际 sha256: {actual}")
    if not sha256:
        print("  警告：官方 Release 未提供 sha256，仅校验了大小与 zip 完整性")
        return None
    return None if actual.lower() == sha256.lower() else f"sha256 不匹配，期望 {sha256}"


def main():
    ap = argparse.ArgumentParser(description="带测速与断点续传的 Release 包下载器")
    ap.add_argument("tag", nargs="?", default="", help="版本 tag（默认最新）")
    ap.add_argument("--dest", default="", help="输出目录（默认系统临时目录）")
    ap.add_argument("--keep-going", action="store_true",
                    help="允许为换通道丢弃已下进度（默认只在能续传时切换）")
    ap.add_argument("--flavor", choices=["cpu", "cuda"], default="",
                    help="要下载的包型（默认自动识别）")
    ap.add_argument("--install-dir", default="",
                    help="自动识别包型时，读这个安装目录的 flavor.json（默认当前目录）")
    args = ap.parse_args()

    tag, asset = resolve_asset(args.tag, detect_flavor(args.flavor, args.install_dir))
    name, url, size, sha256 = asset["name"], asset["url"], asset["size"], asset["digest"]
    dest_dir = args.dest or tempfile.gettempdir()
    dest = os.path.join(dest_dir, name)
    print(f"目标: {tag} / {name}（{asset['flavor']} 包）")
    print(f"官方基准: {size} 字节, sha256 {sha256 or '(接口未提供)'}")
    print(f"保存到: {dest}")

    offset = os.path.getsize(dest) if os.path.exists(dest) else 0
    if offset:
        if offset == size and verify(dest, size, sha256) is None:
            print("\n本地已有完整且校验通过的包，直接复用")
            return 0
        print(f"发现半成品 {offset / 1048576:.0f} MB，尝试续传")

    print("\n== 逐通道测速（各 4 秒）==")
    ranked = []
    for cname, curl in channels(url):
        speed, resume = probe(cname, curl)
        note = "（可续传）" if resume else "（不可续传）" if resume is False else ""
        print(f"  {cname}: {human(speed) if speed else '不可用'}{note}")
        if speed > 0:
            ranked.append((speed, cname, curl, resume))
    if not ranked:
        print("所有通道均不可用")
        return 1

    print("\n== 从最快的通道开始下载 ==")
    tried = set()
    done = False
    for est, cname, curl, resume in sorted(ranked, reverse=True):
        if cname in tried:
            continue
        tried.add(cname)
        if offset and not resume and not args.keep_going:
            print(f"  跳过 {cname}：不支持续传，换它会丢失已下的 {offset / 1048576:.0f} MB")
            continue
        start = offset if resume else 0
        print(f"  使用 {cname}（实测 {human(est)}）"
              f"{f'，从 {start / 1048576:.0f} MB 续传' if start else ''}")
        status = download(cname, curl, dest, size, resume, start)
        if status == "done":
            done = True
            break
        if status == "slow":
            print("    速度掉到阈值以下，换通道")
            offset = os.path.getsize(dest) if os.path.exists(dest) else 0
        elif status == "noresume":
            print(f"    {cname} 忽略 Range 请求，无法续传，跳过")
    if not done:
        print("所有可用通道都没把包下完，重跑一次通常能接上（支持续传）")
        return 1

    print("\n== 校验 ==")
    err = verify(dest, size, sha256)
    if err:
        print(f"  校验失败: {err}")
        return 1
    print(f"  校验通过: {dest}")
    print("\n接下来按 RELEASE.md 第 5 节方式 B 手工安装（先 taskkill，再 robocopy）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
