"""发布包的元数据文件：`flavor.json`（包型标记）与 `manifest.json`（文件清单 + sha256）。

写方只有一处：`tools/package_release.py`（CI 打包时调用）。
读方有两处：`app/updater.py`（安装时做精确剪枝：删掉旧包有、新包没有的文件）
和 `tools/package_release.py` 自己的发布前校验（CPU 清单必须是 CUDA 清单的子集）。

清单格式：
    {"flavor": "cuda", "version": "1.4.0", "commit": "abc1234",
     "files": {"_internal/foo.dll": "<sha256>", ...}}
路径用正斜杠、相对包根目录；`manifest.json` 本身不进清单（否则无法自洽）。
"""

import hashlib
import json
import os

FLAVOR_NAME = "flavor.json"
MANIFEST_NAME = "manifest.json"

# 用户数据：任何情况下都不进清单、不参与剪枝（打包机/开发机上残留也不打包）
USER_FILES = {"config.yaml", "update_state.json"}
USER_PREFIXES = ("app.log",)
USER_DIRS = {"models"}


def is_user_path(rel):
    """相对路径是否属于用户数据（配置 / 日志 / 已下载模型）。"""
    rel = rel.replace("\\", "/").lstrip("./")
    head = rel.split("/", 1)[0]
    name = rel.rsplit("/", 1)[-1]
    return (head in USER_DIRS or name in USER_FILES
            or name.startswith(USER_PREFIXES))


def iter_package_files(root):
    """遍历包内所有应进清单的文件，返回 [(相对路径, 绝对路径)]（路径已排序）。"""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        rel_dir = "" if rel_dir == "." else rel_dir.replace("\\", "/")
        # 用户数据目录整棵跳过
        dirnames[:] = [d for d in dirnames
                       if not is_user_path(f"{rel_dir}/{d}" if rel_dir else d)]
        for fn in filenames:
            rel = f"{rel_dir}/{fn}" if rel_dir else fn
            if rel in (MANIFEST_NAME, FLAVOR_NAME) or is_user_path(rel):
                continue
            out.append((rel, os.path.join(dirpath, fn)))
    out.sort()
    return out


def sha256_file(path, chunk=4 * 1024 * 1024):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def compute_files(root, hashes=None):
    """算出清单里的 files 字段。hashes 可传入已有的 {相对路径: sha256} 复用（派生 CPU 包时用）。"""
    files = {}
    for rel, abs_path in iter_package_files(root):
        if hashes is not None and rel in hashes:
            files[rel] = hashes[rel]
        else:
            files[rel] = sha256_file(abs_path)
    return files


def write_meta(root, flavor, version, commit, files=None):
    """写入 flavor.json 与 manifest.json（把 flavor.json 本身也纳入清单）。

    返回写好的 manifest dict。files 可传入（复用已有哈希），否则现算。
    """
    if files is None:
        files = compute_files(root)
    flavor_payload = {"flavor": flavor, "version": version, "commit": commit}
    with open(os.path.join(root, FLAVOR_NAME), "w", encoding="utf-8") as f:
        json.dump(flavor_payload, f, ensure_ascii=False, indent=2)
    files = dict(files)
    files[FLAVOR_NAME] = sha256_file(os.path.join(root, FLAVOR_NAME))
    manifest = dict(flavor_payload)
    manifest["files"] = files
    with open(os.path.join(root, MANIFEST_NAME), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1, sort_keys=True)
    return manifest


def load_manifest(root):
    """读包内 manifest.json；没有/损坏返回 None（≤1.3.9 的旧安装没有它）。"""
    try:
        with open(os.path.join(root, MANIFEST_NAME), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data.get("files"), dict):
        return None
    return data
