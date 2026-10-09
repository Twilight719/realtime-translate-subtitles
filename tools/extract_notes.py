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

zip_name = f"realtime-translate-subtitles-{TAG}-windows-x64.zip"
notes = f"""## 下载 / Download

解压 `{zip_name}`，运行其中的 `实时翻译字幕.exe`（无需安装 Python，首次运行自动下载识别模型）。
Unzip `{zip_name}` and run `实时翻译字幕.exe` (no Python needed; the speech model downloads on first run).

---

{body}
"""

with open(OUT, "w", encoding="utf-8") as f:
    f.write(notes)
print(f"notes extracted for {TAG}: {len(notes)} chars")
