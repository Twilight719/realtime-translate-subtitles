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

import requests

from .version import GITHUB_RELEASES_URL, GITHUB_REPO, __version__

log = logging.getLogger("subtitle.updater")

# GitHub 文件加速镜像（前缀式，拼在原始 URL 前）。镜像服务随时间可能失效，
# 所以按顺序逐个尝试，最后保底 GitHub 直连。
DOWNLOAD_MIRRORS = [
    "https://ghfast.top/",
    "https://gh-proxy.com/",
    "https://ghproxy.net/",
]

# 更新包资产名特征（避免误选源码 zip 等其他附件）
ASSET_SUFFIX = "windows-x64.zip"

# 启动时的自动检查节流间隔：避免每次启动都请求 GitHub API（匿名限流 60 次/小时/IP）
AUTO_CHECK_INTERVAL_S = 6 * 3600


def _state_path():
    """节流状态文件路径（环境变量 RTS_UPDATE_STATE 可覆盖，测试用）。"""
    override = os.environ.get("RTS_UPDATE_STATE")
    if override:
        return override
    from .paths import base_dir

    return os.path.join(base_dir(), "update_state.json")


def auto_check_due():
    """启动时的自动更新检查是否到期（手动点“检查更新”不受此限制）。"""
    try:
        with open(_state_path(), encoding="utf-8") as f:
            last = float(json.load(f).get("last_check", 0))
    except (OSError, ValueError, TypeError):
        return True
    return time.time() - last >= AUTO_CHECK_INTERVAL_S


def mark_auto_checked():
    """记录本次自动检查时间（仅当确实拿到了服务器响应时调用，网络失败不记，
    下次启动立即重试）。"""
    try:
        with open(_state_path(), "w", encoding="utf-8") as f:
            json.dump({"last_check": time.time()}, f)
    except OSError:
        log.warning("更新检查节流状态写入失败", exc_info=True)


def parse_version(text):
    """'v1.2.3' / '1.2.3' → (1, 2, 3)；无法解析时返回 None。"""
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))


def check_update(timeout=8):
    """检查更新，返回 dict：
    has_update(bool), latest(str|None), url(str), error(str|None),
    asset(dict|None: 更新包信息 name/url/size/digest)
    """
    if "YOUR_USERNAME" in GITHUB_REPO:
        return {"has_update": False, "latest": None, "url": GITHUB_RELEASES_URL,
                "error": "尚未配置仓库地址", "asset": None, "reachable": False}
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
            timeout=timeout,
            headers={"Accept": "application/vnd.github+json"},
        )
        if resp.status_code == 404:
            return {"has_update": False, "latest": None, "url": GITHUB_RELEASES_URL,
                    "error": "仓库还没有发布任何 Release", "asset": None, "reachable": True}
        resp.raise_for_status()
        data = resp.json()
        latest_tag = data.get("tag_name", "")
        latest_ver = parse_version(latest_tag)
        current_ver = parse_version(__version__)
        if latest_ver is None:
            return {"has_update": False, "latest": latest_tag, "url": GITHUB_RELEASES_URL,
                    "error": f"无法解析最新版本号: {latest_tag}", "asset": None, "reachable": True}
        asset = None
        for a in data.get("assets", []):
            if a.get("name", "").endswith(ASSET_SUFFIX):
                asset = {
                    "name": a["name"],
                    "url": a["browser_download_url"],
                    "size": a.get("size", 0),
                    # GitHub 资产的 sha256 摘要（"sha256:xxxx"），用于下载后校验
                    "digest": (a.get("digest") or "").removeprefix("sha256:"),
                }
                break
        return {
            "has_update": latest_ver > current_ver,
            "latest": latest_tag,
            "url": data.get("html_url") or GITHUB_RELEASES_URL,
            "error": None,
            "asset": asset,
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
        return {"has_update": False, "latest": None, "url": GITHUB_RELEASES_URL,
                "error": msg, "asset": None, "reachable": False}


def candidate_urls(asset_url):
    """下载候选地址：镜像优先，GitHub 直连保底。"""
    return [m + asset_url for m in DOWNLOAD_MIRRORS] + [asset_url]


def download_asset(asset, dest_path, progress_cb=None, cancel=None,
                   connect_timeout=8, read_timeout=15):
    """多通道下载更新包，返回 (使用的地址, None) 或 (None, 错误描述)。

    progress_cb(已下载字节, 总字节, 当前通道序号/总数) 用于进度条；
    cancel 为 threading.Event，置位后中止并清理半成品文件。
    下载完成后做完整性校验（zip 结构 + GitHub 提供的 sha256）。
    """
    urls = candidate_urls(asset["url"])
    last_err = None
    for i, url in enumerate(urls):
        if cancel is not None and cancel.is_set():
            return None, "已取消"
        source = "GitHub 直连" if i == len(urls) - 1 else f"镜像 {i + 1}"
        log.info("尝试从%s下载更新包: %s", source, url)
        try:
            with requests.get(url, stream=True, allow_redirects=True,
                              timeout=(connect_timeout, read_timeout)) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("Content-Length") or asset.get("size") or 0)
                done = 0
                with open(dest_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=256 * 1024):
                        if cancel is not None and cancel.is_set():
                            raise _Cancelled()
                        if not chunk:
                            continue
                        f.write(chunk)
                        done += len(chunk)
                        if progress_cb:
                            progress_cb(done, total, i, len(urls))
            # 体积明显不符（镜像出错时可能返回 HTML 错误页）直接判失败
            if asset.get("size") and os.path.getsize(dest_path) != asset["size"]:
                raise IOError(f"文件大小不符（期望 {asset['size']}，实际 {os.path.getsize(dest_path)}）")
            err = verify_package(dest_path, asset.get("digest"))
            if err:
                raise IOError(err)
            log.info("更新包下载完成: %s（来自%s）", dest_path, source)
            return url, None
        except _Cancelled:
            _remove_quiet(dest_path)
            return None, "已取消"
        except Exception as e:
            last_err = f"{source}: {type(e).__name__}: {e}"
            log.warning("从%s下载失败: %s", source, e)
            _remove_quiet(dest_path)
    return None, f"所有下载通道均失败（最后错误：{last_err}）"


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


class _Cancelled(Exception):
    pass
