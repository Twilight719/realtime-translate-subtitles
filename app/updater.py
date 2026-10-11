"""检查更新与下载更新包。

检查：GitHub Releases API（数据量小，直连通常没问题）。
下载：优先走国内可用的 GitHub 加速镜像，全部失败才回退 GitHub 直连。
"""

import hashlib
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from . import flavor as flavor_mod
from . import pack_meta
from .pack_meta import load_manifest
from .version import GITHUB_RELEASES_URL, GITHUB_REPO, __version__

log = logging.getLogger("subtitle.updater")

# GitHub 文件加速镜像（前缀式，拼在原始 URL 前）。镜像服务随时间可能失效，
# 所以按顺序逐个尝试，最后保底 GitHub 直连。
DOWNLOAD_MIRRORS = [
    "https://ghfast.top/",
    "https://gh-proxy.com/",
    "https://ghproxy.net/",
]

# 更新包资产名特征（避免误选源码 zip 等其他附件）。
# 两个包只差后缀：CPU 小包沿用老名字，CUDA 包多一个 -cuda。
# 这保证了 ≤1.3.9 的老客户端（只认 endswith("windows-x64.zip")）永远只会拿到 CPU 小包。
CPU_SUFFIX = "windows-x64.zip"
CUDA_SUFFIX = "windows-x64-cuda.zip"

# ---- 下载通道自适应（规划 §9）----
# 免费加速镜像的速度可在分钟级波动几百倍（2026-10-11 实测同一条通道 8 KB/s ~ 5.6 MB/s），
# 所以不再按固定顺序硬试：先给每条通道短暂测速、从最快的开始下；下载中滚动测速，
# 通道"慢性死亡"（涓流/断流）就带着断点续传到下一条。
PROBE_SECONDS = 3.0            # 每条通道的测速时长（各通道并发测，总耗时≈这个值）
PROBE_MAX_BYTES = 8 << 20      # 测速最多读这么多字节（快通道不必读满时长）
SPEED_WINDOW_S = 8.0           # 滚动测速窗口：每这么久算一次平均速度
MIN_SPEED_BPS = 400 << 10      # 低于此速度判该通道"慢性死亡"→ 换下一个
RESTART_MAX_BYTES = 16 << 20   # 已下进度不足这么多字节时，允许在不能续传的通道上从零重来
RESTART_MAX_RATIO = 0.15       # ……或不足整包的这么多比例时

USER_AGENT = {"User-Agent": "realtime-translate-subtitles-updater"}

# 启动时的自动检查节流间隔：避免每次启动都请求 GitHub API（匿名限流 60 次/小时/IP）
AUTO_CHECK_INTERVAL_S = 6 * 3600


def _state_path():
    """节流状态文件路径（环境变量 RTS_UPDATE_STATE 可覆盖，测试用）。"""
    override = os.environ.get("RTS_UPDATE_STATE")
    if override:
        return override
    from .paths import base_dir

    return os.path.join(base_dir(), "update_state.json")


def _read_state():
    """本地更新状态（节流时间、换包提示是否已弹过等）；损坏时当作空。"""
    try:
        with open(_state_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write_state(**updates):
    state = _read_state()
    state.update(updates)
    try:
        with open(_state_path(), "w", encoding="utf-8") as f:
            json.dump(state, f)
    except OSError:
        log.warning("更新状态写入失败", exc_info=True)


def auto_check_due():
    """启动时的自动更新检查是否到期（手动点“检查更新”不受此限制）。"""
    try:
        last = float(_read_state().get("last_check", 0))
    except (TypeError, ValueError):
        return True
    return time.time() - last >= AUTO_CHECK_INTERVAL_S


def mark_auto_checked():
    """记录本次自动检查时间（仅当确实拿到了服务器响应时调用，网络失败不记，
    下次启动立即重试）。"""
    _write_state(last_check=time.time())


def prompt_due(key):
    """某个"只提示一次"的提示还没弹过？（状态存在 update_state.json 里，跨重启）"""
    return not _read_state().get(key)


def mark_prompted(key):
    _write_state(**{key: True})


def flavor_prompt_due():
    """是否该提示"可以切换到 CUDA 版"（只提示一次，用户不想换就不会再打扰）。"""
    return prompt_due("flavor_prompted")


def mark_flavor_prompted():
    mark_prompted("flavor_prompted")


def parse_version(text):
    """'v1.2.3' / '1.2.3' → (1, 2, 3)；无法解析时返回 None。"""
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))


def asset_for_flavor(assets, flavor):
    """从 Release 资产列表里挑出指定包型的 zip，返回 asset dict 或 None。"""
    want = CUDA_SUFFIX if flavor == flavor_mod.CUDA else CPU_SUFFIX
    for a in assets or []:
        name = a.get("name", "")
        if not name.endswith(want):
            continue
        if flavor != flavor_mod.CUDA and "-cuda.zip" in name:
            continue  # 双保险：CPU 规则绝不能选中 CUDA 包（endswith 本身已排除）
        return {
            "name": name,
            "url": a.get("browser_download_url", ""),
            "size": a.get("size", 0),
            # GitHub 资产的 sha256 摘要（"sha256:xxxx"），用于下载后校验
            "digest": (a.get("digest") or "").removeprefix("sha256:"),
            "flavor": flavor,
        }
    return None


def fetch_release(timeout=8):
    """取最新 Release 并解析出两种包型的资产。返回 dict：
    {tag, url(页面), assets{"cpu":dict|None, "cuda":dict|None}, error, reachable}
    """
    empty = {"tag": None, "url": GITHUB_RELEASES_URL, "assets": {"cpu": None, "cuda": None}}
    if "YOUR_USERNAME" in GITHUB_REPO:
        return {**empty, "error": "尚未配置仓库地址", "reachable": False}
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
            timeout=timeout,
            headers={"Accept": "application/vnd.github+json"},
        )
        if resp.status_code == 404:
            return {**empty, "error": "仓库还没有发布任何 Release", "reachable": True}
        resp.raise_for_status()
        data = resp.json()
        raw = data.get("assets", [])
        tag = data.get("tag_name", "")
        assets = {f: asset_for_flavor(raw, f) for f in (flavor_mod.CPU, flavor_mod.CUDA)}
        for a in assets.values():
            if a is not None:
                a["tag"] = tag
        return {
            "tag": tag,
            "url": data.get("html_url") or GITHUB_RELEASES_URL,
            "assets": assets,
            "error": None,
            "reachable": True,
        }
    except requests.RequestException as e:
        log.warning("检查更新失败: %s", e)
        if isinstance(e, requests.exceptions.SSLError):
            msg = "网络请求失败：HTTPS 证书校验未通过（如开着代理或杀毒软件拦截，请检查其设置）"
        elif isinstance(e, requests.exceptions.Timeout):
            msg = "网络请求失败：连接 GitHub 超时"
        elif isinstance(e, requests.exceptions.ConnectionError):
            msg = "网络请求失败：无法连接 GitHub（请检查网络或代理）"
        else:
            msg = f"网络请求失败：{type(e).__name__}"
        return {**empty, "error": msg, "reachable": False}


def check_update(timeout=8, flavor=None, cfg_device=""):
    """检查更新，返回 dict：

    has_update(bool), latest(str|None), url(str), error(str|None), reachable(bool),
    asset(dict|None)        当前包型对应的更新包（name/url/size/digest/flavor）
    flavor(str)             当前安装的包型（"cpu"/"cuda"）
    alt_asset(dict|None)    另一种包型的包（设置页"切换到 CUDA/CPU 版"用）
    flavor_missing(bool)    有新版本但缺少本包型的资产 → 不自动降级装另一个包
    """
    cur = flavor or flavor_mod.current(cfg_device)
    alt = flavor_mod.CUDA if cur == flavor_mod.CPU else flavor_mod.CPU
    rel = fetch_release(timeout)
    base = {"latest": rel["tag"], "url": rel["url"], "asset": None,
            "alt_asset": rel["assets"].get(alt), "flavor": cur, "flavor_missing": False}
    if rel["error"]:
        return {**base, "has_update": False, "error": rel["error"], "reachable": rel["reachable"]}
    latest_ver = parse_version(rel["tag"] or "")
    current_ver = parse_version(__version__)
    if latest_ver is None:
        return {**base, "has_update": False,
                "error": f"无法解析最新版本号: {rel['tag']}", "reachable": True}
    asset = rel["assets"].get(cur)
    # 目标包缺失（构建失败只发了一个包）：明确提示，**不**退而装另一个包——
    # 静默降级会留下"旧文件没删干净"的混合安装，比不更新更糟（规划 §1.6(b)）
    missing = asset is None
    return {
        **base,
        "has_update": latest_ver > current_ver,
        "asset": asset,
        "flavor_missing": missing,
        "error": (f"本次发布（{rel['tag']}）缺少{'CUDA' if cur == flavor_mod.CUDA else 'CPU'}版安装包，"
                  "请稍后重试或到下载页手动下载" if missing and latest_ver > current_ver else None),
        "reachable": True,
    }


def candidate_urls(asset_url):
    """下载候选地址（静态兜底顺序）：镜像优先，GitHub 直连保底。

    实际尝试顺序由下载前的测速决定，这里只保证"人人都试得到"。
    """
    return [m + asset_url for m in DOWNLOAD_MIRRORS] + [asset_url]


def channel_name(url):
    """通道显示名：取域名（ghfast.top / gh-proxy.com / github.com…），进度条与日志共用。"""
    m = re.match(r"https?://([^/]+)", url or "")
    return m.group(1) if m else (url or "未知通道")


def _probe_channel(url, cancel, seconds, max_bytes):
    """读一小段给通道测速：返回 (速度 B/s, 是否支持断点续传)。

    用 Range 请求顺便探明该通道支不支持续传（206=支持，200=忽略 Range）。
    失败返回 (0.0, None)，调用方据此把它排到最后。
    """
    t0, got, resume = time.time(), 0, None
    try:
        with requests.get(url, headers={**USER_AGENT, "Range": f"bytes=0-{max_bytes - 1}"},
                          stream=True, allow_redirects=True, timeout=(8, 10)) as resp:
            resp.raise_for_status()
            resume = resp.status_code == 206
            for chunk in resp.iter_content(chunk_size=256 * 1024):
                if cancel is not None and cancel.is_set():
                    break
                if chunk:
                    got += len(chunk)
                if got >= max_bytes or time.time() - t0 >= seconds:
                    break
    except Exception as e:
        log.info("通道测速失败 %s: %s", url, e)
        return 0.0, None
    return got / max(time.time() - t0, 0.001), resume


def rate_channels(urls, cancel=None, seconds=PROBE_SECONDS, max_bytes=PROBE_MAX_BYTES):
    """并发给各通道测速（总耗时≈一次测速时长），返回按速度降序的 [(速度, 地址, 可否续传)]。

    完全不可用的通道不返回。并发测速是为了不让"测 4 条通道"变成 4 倍等待。
    """
    out = []
    if not urls:
        return out
    with ThreadPoolExecutor(max_workers=min(4, len(urls))) as ex:
        futures = [ex.submit(_probe_channel, u, cancel, seconds, max_bytes) for u in urls]
        for url, fut in zip(urls, futures):
            try:
                speed, resume = fut.result()
            except Exception:
                speed, resume = 0.0, None
            if speed > 0:
                out.append((speed, url, resume))
    out.sort(key=lambda item: item[0], reverse=True)
    return out


def _download_from(url, dest_path, start, emit, cancel, connect_timeout,
                   read_timeout, min_speed, window_s):
    """从一条通道下载到 dest_path（start>0 = 断点续传）。

    返回 (状态, 速度)。状态：done / slow / noresume / cancel / error。
    - slow：窗口平均速度低于 min_speed → 该通道涓流，换下一条（已下部分留着续传）；
    - noresume：请求了续传却被忽略（返回 200，如 gh-proxy.com），尚未写入任何数据。
    emit(已下字节, 窗口速度) 用于进度显示。
    """
    headers = dict(USER_AGENT)
    if start:
        headers["Range"] = f"bytes={start}-"
    try:
        with requests.get(url, headers=headers, stream=True, allow_redirects=True,
                          timeout=(connect_timeout, read_timeout)) as resp:
            if start and resp.status_code == 200:
                return "noresume", 0.0
            resp.raise_for_status()
            done, win_t0, win_bytes, speed = start, time.time(), 0, 0.0
            with open(dest_path, "ab" if start else "wb") as f:
                for chunk in resp.iter_content(chunk_size=256 * 1024):
                    if cancel is not None and cancel.is_set():
                        return "cancel", speed
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)
                    win_bytes += len(chunk)
                    el = time.time() - win_t0
                    speed = win_bytes / max(el, 0.001)
                    if emit:
                        emit(done, speed)
                    if min_speed and el >= window_s:
                        if speed < min_speed:
                            log.warning("通道 %s 速度掉到 %.0f KB/s，换下一条",
                                        channel_name(url), speed / 1024)
                            return "slow", speed
                        win_t0, win_bytes = time.time(), 0
            return "done", speed
    except Exception as e:
        log.warning("通道 %s 下载出错: %s: %s", channel_name(url), type(e).__name__, e)
        return "error", 0.0


def _fetch_via(url, dest_path, offset, size, idx, count, progress_cb, cancel,
               connect_timeout, read_timeout, min_speed, window_s, restart_ok=False):
    """在一条通道上把包下完（必要时按规则从零重来）。返回 (状态, 之后的 offset, 实测速度)。

    状态：done / slow / error / skip（该通道不适用，保留进度换下一条）/ cancel。
    restart_ok 为真表示"已经没有别的通道可试了"，此时忽略 Range 的通道也直接从零重下
    （最后一招：宁可白费已下进度，也不能让更新下不来）。
    """
    name = channel_name(url)

    def emit(done, speed):
        if progress_cb:
            progress_cb(done, size, idx, count, name, speed)

    status, speed = _download_from(url, dest_path, offset, emit, cancel, connect_timeout,
                                   read_timeout, min_speed, window_s)
    if status == "noresume" and offset:
        # 这条通道忽略 Range：已下的进度保不住。下得不多就重来，下得多了先换一条能续传的；
        # 要是别的通道都试过了（restart_ok），宁可作废进度也要把包拿下来
        if restart_ok or offset < max(RESTART_MAX_BYTES, size * RESTART_MAX_RATIO):
            log.warning("%s 不支持断点续传，已下的 %.1f MB 作废，改从零下载", name, offset / 1048576)
            status, speed = _download_from(url, dest_path, 0, emit, cancel, connect_timeout,
                                           read_timeout, min_speed, window_s)
        else:
            log.warning("%s 不支持断点续传，保留已下的 %.1f MB 换通道", name, offset / 1048576)
            return "skip", offset, speed  # 没动过文件，进度保持原样
    if status == "done":
        return "done", size, speed
    # 其余情况（涓流/出错）：磁盘上有多少字节就是多少——下一条通道从这里续传
    try:
        return status, os.path.getsize(dest_path), speed
    except OSError:
        return status, offset, speed


def download_asset(asset, dest_path, progress_cb=None, status_cb=None, cancel=None,
                   connect_timeout=8, read_timeout=15, probe_seconds=PROBE_SECONDS,
                   probe_max_bytes=PROBE_MAX_BYTES, min_speed=MIN_SPEED_BPS,
                   window_s=SPEED_WINDOW_S):
    """通道自适应地下载更新包，返回 (使用的地址, None) 或 (None, 错误描述)。

    progress_cb(已下载字节, 总字节, 通道序号, 通道总数, 通道名, 实测速度 B/s) 更新进度条；
    status_cb(阶段, 通道名, 序号, 总数) 在测速/换通道时调用（阶段：probe / channel，文案由界面组织）；
    cancel 为 threading.Event，置位后中止并删除半成品文件。

    要点（规划 §9）：①下载前并发测速，从最快通道开始；②下载中滚动测速，
    涓流通道换掉；③换通道带 Range 续传，不被支持的通道按已下进度决定"重来还是跳过"；
    ④所有通道都慢时退回实测最快的一条继续下（最坏情况不比旧版顺序试更差）；
    ⑤整包 sha256 校验在续传/换通道后照常执行。
    """
    size = int(asset.get("size") or 0)
    urls = candidate_urls(asset["url"])
    if cancel is not None and cancel.is_set():
        return None, "已取消"

    # 上次留下的半成品：接着下，不白费已经花掉的流量
    offset = os.path.getsize(dest_path) if os.path.exists(dest_path) else 0
    if offset and size:
        if offset > size:
            _remove_quiet(dest_path)
            offset = 0
        elif offset == size:
            if verify_package(dest_path, asset.get("digest")) is None:
                log.info("更新包已完整下载并校验通过，直接复用: %s", dest_path)
                return dest_path, None
            offset = 0
    if offset:
        log.info("发现未下完的更新包（%.1f MB），尝试断点续传", offset / 1048576)

    mem = _read_state().get("last_channel")
    if mem in urls and not offset:
        # 上次成功的通道：直接开工，省掉测速（要是它变慢了，看门狗会换掉它）
        log.info("沿用上次成功的下载通道 %s（免测速）", channel_name(mem))
        ranked = [(None, mem, None)] + [(None, u, None) for u in urls if u != mem]
    else:
        if status_cb:
            status_cb("probe", "", 1, len(urls))
        ranked = rate_channels(urls, cancel, probe_seconds, probe_max_bytes)
        if cancel is not None and cancel.is_set():
            return None, "已取消"
        if not ranked:
            # 一条都测不出速度（可能被拦截了 Range 探测）：退回静态顺序硬试
            log.warning("所有通道测速失败，退回按固定顺序尝试")
            ranked = [(None, u, None) for u in urls]
        else:
            log.info("通道测速结果: %s",
                     "、".join(f"{channel_name(u)} {s / 1024:.0f} KB/s" for s, u, _ in ranked))

    tried, held, last_err, done_url = set(), [], None, None
    for i, (speed, url, resume) in enumerate(ranked):
        if cancel is not None and cancel.is_set():
            return None, "已取消"
        if url in tried:
            continue
        tried.add(url)
        if offset and resume is False:
            # 已经下了一截，而这条通道不能续传：留作最后兜底（用它就得从零重下），先试能续传的
            held.append((speed or 0.0, url, True))
            continue
        if status_cb:
            status_cb("channel", channel_name(url), i + 1, len(ranked))
        log.info("从 %s 下载更新包（%s%s）", channel_name(url),
                 f"实测 {speed / 1024:.0f} KB/s " if speed else "",
                 {True: "支持续传", False: "不支持续传"}.get(resume, "续传未知"))
        status, offset, got = _fetch_via(url, dest_path, offset, size, i + 1, len(ranked),
                                         progress_cb, cancel, connect_timeout, read_timeout,
                                         min_speed, window_s)
        if status == "done":
            done_url = url
            break
        if status == "cancel":
            _remove_quiet(dest_path)
            return None, "已取消"
        if status in ("slow", "skip"):
            # 慢但有进展 / 不能续传：留作最后的兜底候选（skip 的要用它就得从零重下）
            held.append((got or speed or 0.0, url, status == "skip"))
        else:
            last_err = f"{channel_name(url)}: {status}"
    else:
        # 所有通道都没下完：要是还有"慢但能跑"的通道，关掉速度看门狗让它硬跑完
        # （最坏情况 = 旧版从第一个通道慢慢磨，不会更差）
        if held:
            # 先挑能接着续传的，实在没有就挑最快的从零重下；
            # 否则"已下一大截 + 只剩忽略 Range 的通道"会变成下不下来（比旧版还差）
            held.sort(key=lambda it: (it[2], -it[0]))
            _, url, restart = held[0]
            log.warning("所有通道都没能下完，退回实测最快的一条（%s）继续下载%s",
                        channel_name(url), "（不支持续传，从零重下）" if restart else "")
            if status_cb:
                status_cb("channel", channel_name(url), len(ranked), len(ranked))
            status, offset, _ = _fetch_via(url, dest_path, offset, size, len(ranked), len(ranked),
                                           progress_cb, cancel, connect_timeout, read_timeout,
                                           0, window_s, restart_ok=restart)
            if status == "done":
                done_url = url
            elif status == "cancel":
                _remove_quiet(dest_path)
                return None, "已取消"
            else:
                last_err = f"{channel_name(url)}: {status}"

    if not done_url:
        return None, f"所有下载通道均失败（最后错误：{last_err or '速度过低'}）"
    # 体积明显不符（镜像出错时可能返回 HTML 错误页）直接判失败
    if size and os.path.getsize(dest_path) != size:
        _remove_quiet(dest_path)
        return None, (f"文件大小不符（期望 {size}，实际 {os.path.getsize(dest_path)}），"
                      "请重试或到下载页手动下载")
    err = verify_package(dest_path, asset.get("digest"))
    if err:
        _remove_quiet(dest_path)
        return None, err
    log.info("更新包下载完成: %s（来自 %s）", dest_path, channel_name(done_url))
    _write_state(last_channel=done_url)
    return done_url, None


def find_cached_download(asset, dest_path):
    """dest_path 已有完整且校验通过的更新包（上次下载留下的）时返回 True，可直接复用。"""
    if not os.path.exists(dest_path):
        return False
    if asset.get("size") and os.path.getsize(dest_path) != asset["size"]:
        return False
    if verify_package(dest_path, asset.get("digest")) is not None:
        return False
    log.info("更新包已下载过且校验通过，复用: %s", dest_path)
    return True


def compute_prune_list(new_app_dir, target_dir):
    """算出"旧包有、新包没有"的文件与目录，返回 (files, dirs) 两个绝对路径列表。

    用途：安装新包前先删掉旧包独有的文件。最典型的是 CPU / CUDA 换包
    （CUDA → CPU 若不删，安装目录会残留约 600 MB CUDA 运行库，磁盘没省下、
    还容易让人误以为已经是 CUDA 版）。robocopy /E 不删多余文件，所以必须自己做。

    - 只依据包内 manifest.json（包自己的文件清单，用户数据永不进清单）→ 天然不碰
      config.yaml / app.log / models / update_state.json；
    - 旧包没有清单（≤1.3.9 或手工拆包）时，退化为只清理 _internal/nvidia
      （CUDA 运行库目录；新包是 CUDA 版时不需要清理）；
    - dirs 按由深到浅排序，安装脚本对它们只在"已空"时删除，不会误删有内容的目录。
    """
    target_real = os.path.realpath(target_dir)
    new_manifest = load_manifest(new_app_dir)
    old_manifest = load_manifest(target_dir)
    new_files = set((new_manifest or {}).get("files", {}))
    new_flavor = (flavor_mod.read_marker(new_app_dir) or {}).get("flavor")

    stale = set()
    if old_manifest and new_manifest:
        stale = {rel for rel in old_manifest["files"] if rel not in new_files}
        if old_manifest.get("flavor") != new_manifest.get("flavor"):
            log.info("换包型安装: %s → %s，旧包独有文件 %d 个待清理",
                     old_manifest.get("flavor"), new_manifest.get("flavor"), len(stale))
    elif new_flavor == flavor_mod.CPU:
        # 旧安装没有清单：只按已知的 CUDA 运行库目录兜底清理
        for dirpath, _dirnames, filenames in os.walk(os.path.join(target_dir, "_internal", "nvidia")):
            for fn in filenames:
                stale.add(os.path.relpath(os.path.join(dirpath, fn), target_dir).replace("\\", "/"))
        if stale:
            log.info("旧安装无清单，按 CUDA 运行库目录兜底清理 %d 个文件", len(stale))

    files, dirs = [], set()
    for rel in sorted(stale):
        if pack_meta.is_user_path(rel):
            log.warning("剪枝清单里出现用户数据，已跳过: %s", rel)
            continue
        abs_path = os.path.realpath(os.path.join(target_dir, rel.replace("/", os.sep)))
        if not abs_path.startswith(target_real + os.sep) or not os.path.isfile(abs_path):
            continue
        files.append(abs_path)
        parent = os.path.dirname(abs_path)
        while parent.startswith(target_real + os.sep) and len(parent) > len(target_real):
            rel_dir = os.path.relpath(parent, target_real).replace("\\", "/")
            # 新包里还有文件在这个目录下 → 目录不是"旧包独有"，不能删
            if any(f.startswith(rel_dir + "/") for f in new_files):
                break
            dirs.add(parent)
            parent = os.path.dirname(parent)
    ordered_dirs = sorted(dirs, key=len, reverse=True)  # 深的先删
    return files, ordered_dirs


def verify_package(path, expected_sha256=None):
    """校验更新包：必须是完整 zip；有官方摘要时再核对 sha256。返回 None=通过。"""
    import zipfile

    try:
        with zipfile.ZipFile(path) as zf:
            bad = zf.testzip()
            if bad:
                return f"压缩包损坏（损坏文件: {bad}）"
    except zipfile.BadZipFile:
        return "下载的文件不是有效的压缩包"
    if expected_sha256:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        if h.hexdigest().lower() != expected_sha256.lower():
            return "文件校验和不匹配（下载可能被损坏）"
    else:
        # Release API 未返回摘要（如接口变化）：不能静默跳过，留下痕迹便于排查
        log.warning("官方未提供 sha256 摘要，%s 仅校验了 zip 完整性", os.path.basename(path))
    return None


def _remove_quiet(path):
    try:
        os.remove(path)
    except OSError:
        pass
