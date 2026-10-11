"""从 CHANGELOG.md 提取指定版本的更新说明，作为 GitHub Release 的正文。

用法: python tools/extract_notes.py v1.0.12 notes.md
找不到对应小节时输出一份通用说明。
"""

import re
import sys

TAG = sys.argv[1]          # 如 v1.0.12
OUT = sys.argv[2]          # 输出文件

if not TAG:
    sys.exit("ERROR: 未提供标签名（TAG 为空），终止发布以避免生成无版本号的说明")

with open("CHANGELOG.md", encoding="utf-8") as f:
    text = f.read().replace("\r\n", "\n")

m = re.search(
    rf"## \[{re.escape(TAG)}\].*?(?=\n---\n)",  # 从小节标题到下一个分隔线
    text, re.S,
)
if m:
    body = m.group(0).strip()
else:
    sys.exit(f"ERROR: CHANGELOG.md 中找不到 [{TAG}] 小节，终止发布以避免生成空日志")

cpu_zip = f"realtime-translate-subtitles-{TAG}-windows-x64.zip"
cuda_zip = f"realtime-translate-subtitles-{TAG}-windows-x64-cuda.zip"


def _size(path, fallback):
    """体积说明：优先用打包脚本产出的真实大小（release_sizes.json），避免文档与包体脱节。"""
    try:
        import json

        with open("release_sizes.json", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("tag") == TAG:
            mb = data[path]["size"] / 1048576
            return f"约 {mb:.0f} MB"
    except Exception:
        pass
    return fallback


cpu_size = _size("cpu", "约 110 MB")
cuda_size = _size("cuda", "约 640 MB")
notes = f"""## 下载 / Download

**怎么选 / Which one?**
- 没有 NVIDIA 显卡，或用「极速」识别引擎 → 选 `{cpu_zip}`（{cpu_size}，两种包功能完全一样）
- 有 NVIDIA 显卡且想让识别更快（设置页设备选 cuda）→ 选 `{cuda_zip}`（{cuda_size}，多带 CUDA 运行库）

解压后运行其中的 `实时翻译字幕.exe`（无需安装 Python，首次运行自动下载识别模型）。
Unzip and run `实时翻译字幕.exe` (no Python needed; the speech model downloads on first run).
Both packages contain the same program — the CUDA one just adds the NVIDIA runtime libraries.

> 软件内「检查更新」会自动下载与你当前版本对应的那一个，无需手动选择。
> In-app update automatically picks the matching package.

---

{body}
"""

with open(OUT, "w", encoding="utf-8") as f:
    f.write(notes)
print(f"notes extracted for {TAG}: {len(notes)} chars")
