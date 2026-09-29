"""通过 GitHub Releases 检查是否有新版本（设置页“检查更新”按钮调用）。"""

import logging
import re

import requests

from .version import GITHUB_RELEASES_URL, GITHUB_REPO, __version__

log = logging.getLogger("subtitle.updater")


def parse_version(text):
    """'v1.2.3' / '1.2.3' → (1, 2, 3)；无法解析时返回 None。"""
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))


def check_update(timeout=8):
    """检查更新，返回 dict：
    has_update(bool), latest(str|None), url(str), error(str|None)
    """
    if "YOUR_USERNAME" in GITHUB_REPO:
        return {"has_update": False, "latest": None, "url": GITHUB_RELEASES_URL,
                "error": "尚未配置仓库地址"}
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
            timeout=timeout,
            headers={"Accept": "application/vnd.github+json"},
        )
        if resp.status_code == 404:
            return {"has_update": False, "latest": None, "url": GITHUB_RELEASES_URL,
                    "error": "仓库还没有发布任何 Release"}
        resp.raise_for_status()
        data = resp.json()
        latest_tag = data.get("tag_name", "")
        latest_ver = parse_version(latest_tag)
        current_ver = parse_version(__version__)
        if latest_ver is None:
            return {"has_update": False, "latest": latest_tag, "url": GITHUB_RELEASES_URL,
                    "error": f"无法解析最新版本号: {latest_tag}"}
        return {
            "has_update": latest_ver > current_ver,
            "latest": latest_tag,
            "url": data.get("html_url") or GITHUB_RELEASES_URL,
            "error": None,
        }
    except requests.RequestException as e:
        log.warning("检查更新失败: %s", e)
        return {"has_update": False, "latest": None, "url": GITHUB_RELEASES_URL,
                "error": f"网络请求失败: {e}"}
