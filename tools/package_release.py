# -*- coding: utf-8 -*-
"""发布打包：从**一次** PyInstaller 构建派生出 CUDA 完整包与 CPU 精简包，并校验一致性。

为什么不是"矩阵构建两个包"：两次构建的 checkout 时间/编译时间戳不同，exe 与 pyc
必然有差异，公共文件做不到逐字节相同（v1.4.0 规划 §1.6(a)）。派生则天然满足：
CPU 包的每个文件都与 CUDA 包中的同名文件是完全相同的字节。

用法：
    python tools/package_release.py --tag v1.4.0 [--dist "dist/实时翻译字幕"]
                                    [--out .] [--commit abc1234]

产出（--out 目录下）：
    realtime-translate-subtitles-<tag>-windows-x64-cuda.zip   CUDA 完整包（含 nvidia 运行库）
    realtime-translate-subtitles-<tag>-windows-x64.zip        CPU 小包（不带 CUDA 运行库）

校验不通过时退出码为 1 —— CI 里紧跟其后的是发布步骤，**不允许**发出半份或错配的包。
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.pack_meta import (FLAVOR_NAME, MANIFEST_NAME, compute_files,  # noqa: E402
                           is_user_path, load_manifest, sha256_file, write_meta)

# CUDA 运行库在包内的位置（派生 CPU 包时唯一要删的东西）
CUDA_SUBTREE = "_internal/nvidia"
TOP_DIR = "实时翻译字幕"

SIZE_LIMIT_CPU = 250 * 1024 * 1024
SIZE_LIMIT_CUDA = 900 * 1024 * 1024

EXE_NAME = TOP_DIR + ".exe"


def human(n):
    return f"{n / 1048576:.1f} MB"


def link_or_copy(src, dst):
    """优先硬链接（同盘瞬时完成，CI 上省几十秒），失败则复制。"""
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def copy_tree(src, dst):
    shutil.copytree(src, dst, copy_function=link_or_copy)


def zip_dir(root, dest_zip, top_dir):
    """把 root 目录打成 zip，内部顶层为 top_dir/（与手工安装/解压逻辑一致）。"""
    count = 0
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6,
                         allowZip64=True) as zf:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames.sort()
            for fn in sorted(filenames):
                abs_path = os.path.join(dirpath, fn)
                rel = os.path.relpath(abs_path, root).replace("\\", "/")
                if is_user_path(rel):
                    continue  # 打包机上残留的配置/日志/模型绝不进包（也不进清单）
                zf.write(abs_path, f"{top_dir}/{rel}")
                count += 1
    return count


def zip_check(path, expect_top):
    """zip 可读性 + 顶层目录结构校验。"""
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        bad = zf.testzip()
    if bad:
        return f"压缩包损坏（{bad}）"
    if not names:
        return "压缩包为空"
    tops = {n.split("/", 1)[0] for n in names}
    if tops != {expect_top}:
        return f"顶层目录异常: {sorted(tops)}"
    if not any(n.endswith("/" + EXE_NAME) for n in names):
        return f"找不到程序文件 {EXE_NAME}"
    return None


def check_consistency(cuda_dir, cpu_dir, tag, commit):
    """校验两份包的一一对应关系，返回问题列表（空 = 通过）。"""
    problems = []
    cuda_m = load_manifest(cuda_dir)
    cpu_m = load_manifest(cpu_dir)
    if not cuda_m or not cpu_m:
        return ["缺少 manifest.json（包不是由本脚本生成的？）"]

    cuda_files, cpu_files = cuda_m["files"], cpu_m["files"]
    version = tag.lstrip("v")
    for name, m, want in (("CUDA", cuda_m, "cuda"), ("CPU", cpu_m, "cpu")):
        if m.get("flavor") != want:
            problems.append(f"{name} 包的 flavor 应为 {want}，实际 {m.get('flavor')}")
        if str(m.get("version")) != version:
            problems.append(f"{name} 包版本 {m.get('version')} != tag {tag}")
        if commit and m.get("commit") != commit:
            problems.append(f"{name} 包 commit {m.get('commit')} != {commit}")

    extra = sorted(set(cpu_files) - set(cuda_files))
    if extra:
        problems.append(f"CPU 包出现 CUDA 包里没有的文件（{len(extra)} 个）: {extra[:5]}")
    only_cuda = sorted(set(cuda_files) - set(cpu_files))
    if not only_cuda:
        problems.append("两个包的文件完全相同：CPU 包没有瘦身，派生步骤没生效")
    wrong = [f for f in only_cuda if not f.startswith(CUDA_SUBTREE + "/")]
    if wrong:
        problems.append(f"CUDA 包独有文件里有非 CUDA 运行库内容（{len(wrong)} 个）: {wrong[:5]}")

    diff_bytes = [f for f in (set(cuda_files) & set(cpu_files)) - {FLAVOR_NAME}
                  if cuda_files[f] != cpu_files[f]]
    if diff_bytes:
        problems.append(f"公共文件内容不一致（{len(diff_bytes)} 个）: {diff_bytes[:5]}")

    # 真实文件也要对得上（防止有人绕过清单改东西）
    for rel in only_cuda[:1000]:
        if os.path.exists(os.path.join(cpu_dir, rel.replace("/", os.sep))):
            problems.append(f"CPU 包里仍存在该删的文件: {rel}")
            break
    return problems


def report_manifest_diff(cuda_m, cpu_m):
    only_cuda = sorted(set(cuda_m["files"]) - set(cpu_m["files"]))
    print(f"  CUDA 包 {len(cuda_m['files'])} 个文件 / CPU 包 {len(cpu_m['files'])} 个文件")
    print(f"  CPU 包省掉 {len(only_cuda)} 个文件，全部位于 {CUDA_SUBTREE}/")
    for rel in only_cuda[:8]:
        print(f"    - {rel}")


def main():
    ap = argparse.ArgumentParser(description="派生双包并校验一致性")
    ap.add_argument("--tag", required=True, help="版本 tag，如 v1.4.0")
    ap.add_argument("--dist", default=os.path.join("dist", TOP_DIR), help="PyInstaller 产物目录")
    ap.add_argument("--out", default=".", help="zip 输出目录")
    ap.add_argument("--commit", default=os.environ.get("GITHUB_SHA", "")[:7])
    ap.add_argument("--keep-staging", action="store_true", help="保留中间目录（排障用）")
    args = ap.parse_args()

    tag = args.tag.strip()
    if not tag.startswith("v"):
        print(f"tag 需要形如 v1.4.0，收到 {tag!r}")
        return 2
    dist = os.path.abspath(args.dist)
    out = os.path.abspath(args.out)
    exe = os.path.join(dist, EXE_NAME)
    if not os.path.isfile(exe):
        print(f"找不到构建产物: {exe}")
        return 2

    cuda_zip = os.path.join(out, f"realtime-translate-subtitles-{tag}-windows-x64-cuda.zip")
    cpu_zip = os.path.join(out, f"realtime-translate-subtitles-{tag}-windows-x64.zip")
    staging_root = os.path.join(out, ".pkg_staging")
    cpu_dir = os.path.join(staging_root, TOP_DIR)

    print(f"== 1/4 写入 CUDA 包元数据（{dist}） ==")
    files = compute_files(dist)
    cuda_manifest = write_meta(dist, "cuda", tag.lstrip("v"), args.commit, files)
    print(f"  文件 {len(cuda_manifest['files'])} 个，commit {args.commit or '(未提供)'}")

    print(f"== 2/4 派生 CPU 包（删 {CUDA_SUBTREE}/） ==")
    shutil.rmtree(staging_root, ignore_errors=True)
    copy_tree(dist, cpu_dir)
    shutil.rmtree(os.path.join(cpu_dir, CUDA_SUBTREE), ignore_errors=True)
    for name in (FLAVOR_NAME, MANIFEST_NAME):  # 由 write_meta 重新生成
        p = os.path.join(cpu_dir, name)
        if os.path.exists(p):
            os.remove(p)
    cpu_files = {k: v for k, v in files.items() if not k.startswith(CUDA_SUBTREE + "/")}
    cpu_manifest = write_meta(cpu_dir, "cpu", tag.lstrip("v"), args.commit, cpu_files)
    report_manifest_diff(cuda_manifest, cpu_manifest)

    print("== 3/4 压缩 ==")
    n = zip_dir(dist, cuda_zip, TOP_DIR)
    print(f"  {os.path.basename(cuda_zip)}: {n} 个条目, {human(os.path.getsize(cuda_zip))}")
    n = zip_dir(cpu_dir, cpu_zip, TOP_DIR)
    print(f"  {os.path.basename(cpu_zip)}: {n} 个条目, {human(os.path.getsize(cpu_zip))}")

    print("== 4/4 一致性校验 ==")
    problems = check_consistency(dist, cpu_dir, tag, args.commit)
    for z, d in ((cuda_zip, dist), (cpu_zip, cpu_dir)):
        err = zip_check(z, TOP_DIR)
        if err:
            problems.append(f"{os.path.basename(z)}: {err}")
    size_cuda, size_cpu = os.path.getsize(cuda_zip), os.path.getsize(cpu_zip)
    if size_cpu > SIZE_LIMIT_CPU:
        problems.append(f"CPU 包过大（{human(size_cpu)} > {human(SIZE_LIMIT_CPU)}）：可能混进了 CUDA 库")
    if size_cuda > SIZE_LIMIT_CUDA:
        problems.append(f"CUDA 包过大（{human(size_cuda)} > {human(SIZE_LIMIT_CUDA)}）")

    if not args.keep_staging:
        shutil.rmtree(staging_root, ignore_errors=True)

    if problems:
        print("\n校验未通过：")
        for p in problems:
            print(f"  ✗ {p}")
        return 1

    print("  校验通过：CPU 包是 CUDA 包的严格子集，公共文件逐字节相同")
    print(f"\n产物：\n  {cuda_zip}\n    {human(size_cuda)}  sha256 {sha256_file(cuda_zip)}")
    print(f"  {cpu_zip}\n    {human(size_cpu)}  sha256 {sha256_file(cpu_zip)}")
    with open(os.path.join(out, "release_sizes.json"), "w", encoding="utf-8") as f:
        json.dump({"tag": tag, "cuda": {"name": os.path.basename(cuda_zip), "size": size_cuda},
                   "cpu": {"name": os.path.basename(cpu_zip), "size": size_cpu}},
                  f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
