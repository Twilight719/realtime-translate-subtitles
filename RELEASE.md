# 发版与维护操作手册 / Release & Maintenance Playbook

> 写给接手维护的 AI 或开发者：本文档记录本项目从修改代码到用户电脑上更新完成的**完整闭环**。
> 严格按步骤执行，每一步都有验证命令，不要跳过验证。

---

## 0. 环境背景（重要，先看这个）

- 项目源码：`D:\翻译插件`（Windows，Git Bash 环境，路径含中文）
- 用户本机安装目录（桌面快捷方式指向）：`C:\rtbuild\dist\实时翻译字幕`
  - 用户的 `config.yaml`、日志 `app.log`、模型 `models/` 都在这里，**更新时绝不能覆盖**
- 构建：本地不构建 exe，**由 GitHub Actions 构建**（本地路径含中文会触发 Qt 插件加载 bug）
- 开发用 Python 虚拟环境：`D:\翻译插件\.venv\Scripts\python.exe`（跑测试/验证都用它，建议加 `-X utf8`）
- GitHub 仓库：`Twilight719/realtime-translate-subtitles`

### 环境坑（都真实踩过）

1. **PowerShell 脚本含中文必须存成 UTF-8 带 BOM**，否则 PS 5.1 按 ANSI 读取会乱码导致路径错误：
   ```bash
   printf '\xef\xbb\xbf' > out.ps1 && cat script.ps1 >> out.ps1
   ```
2. **robocopy 经 Git Bash 调用处理中文路径可能静默失败** → 必须写进 `.ps1`（带 BOM）用 powershell 执行。
3. robocopy 退出码 **0~7 都是成功**（3 = 有复制+有多余文件）。退出码 ≥8 才是真失败。
4. **覆盖安装前必须先杀掉正在运行的软件**（`taskkill //F //IM "实时翻译字幕.exe"`），否则 exe 被锁定，robocopy 默认无限重试 = 脚本卡死。
5. curl 访问 GitHub API 要加 `--ssl-no-revoke`（本机证书吊销检查会卡住）。
6. git push 要加 `-c http.schannelCheckRevoke=false -c credential.helper=`，URL 里带用户名+token：
   ```bash
   git -c http.schannelCheckRevoke=false -c credential.helper= push "https://Twilight719:<TOKEN>@github.com/Twilight719/realtime-translate-subtitles.git" main
   ```
   注意必须带 `Twilight719:` 用户名前缀，裸 token 会报 "could not read Password"。
7. **token 不要写进任何提交到仓库的文件**（包括本文档）。token 由用户在对话中临时提供，用完即弃。
8. Git Bash 里 Python 的 `/tmp` 和 Windows Python 的 `/tmp` 不是同一个目录——跨工具临时文件用项目目录或 `%TEMP%` 的 Windows 路径。
9. Git Bash 内联 `python -c` 多行代码可能静默 exit 127——写成临时 .py 文件再跑。

---

## 1. 修改代码后：本地验证（发版前必做）

```bash
cd /d/翻译插件
# 语法检查（所有改动文件）
./.venv/Scripts/python.exe -X utf8 -c "
import ast
for f in ['main.py','app/xxx.py']:
    ast.parse(open(f,encoding='utf-8').read())
print('syntax OK')
"
# 相关回归测试（tools/ 下现有测试，按改动选择）
./.venv/Scripts/python.exe -X utf8 tools/test_hotkey_rebind.py      # 热键
./.venv/Scripts/python.exe -X utf8 tools/test_click_through.py      # 点击穿透
./.venv/Scripts/python.exe -X utf8 tools/test_ocr_frozen.py         # 截图翻译冻结帧
```

Qt 测试脚本必须在 `QApplication` 创建前加插件路径（否则 exit 127 无输出）：
```python
import os, PyQt5
from PyQt5.QtCore import QCoreApplication
QCoreApplication.addLibraryPath(os.path.join(os.path.dirname(PyQt5.__file__), "Qt5", "plugins"))
```

---

## 2. 写更新日志（CHANGELOG.md）

格式遵循 Keep a Changelog，**中英双语**，新版本插到文件最上方 `---` 之后：

```markdown
---

## [v1.3.8] - 2026-10-10

### 新增 / Added        ← 新功能
### 修复 / Fixed        ← bug 修复
### 其他 / Changed      ← 行为调整

- **中文加粗标题**：中文描述。
  English description of the same change.
```

要求：每条改动中文一行 + 英文一行（英文缩进两格跟在同一条目下）；标题加粗点出用户能感知的现象，不只写技术名词。

---

## 3. 版本号 + 提交 + 打 tag

版本号在 `app/version.py` 的 `__version__`（唯一需要改的地方，设置页标题和更新检查都读它）：

```bash
cd /d/翻译插件
# 1. 改 app/version.py: __version__ = "1.3.8"
# 2. 验证 CI 发版日志提取能正常工作（失败会终止，必须跑）
./.venv/Scripts/python.exe -X utf8 tools/extract_notes.py v1.3.8 tools/.n.md && rm tools/.n.md
# 3. 提交（先 git status 检查别把临时文件提交进去！）
git status --porcelain
git add -A && git commit -m "fix/feat: 简述；发布 v1.3.8"
# 4. 打 tag 并推送（tag 推送会触发 CI 自动构建+发版）
git tag v1.3.8
git -c http.schannelCheckRevoke=false -c credential.helper= push "https://Twilight719:<TOKEN>@github.com/Twilight719/realtime-translate-subtitles.git" main v1.3.8
```

---

## 4. CI 自动构建与发版（无需手动干预）

打 tag 推送后，`.github/workflows/release.yml` 自动完成：
安装依赖 → PyInstaller 打包 → 压缩 zip → 从 CHANGELOG 提取本版本日志 → 创建 GitHub Release 并上传 zip。

### 监控 CI（轮询 API）

```bash
curl -s --ssl-no-revoke -H "Authorization: token <TOKEN>" \
  "https://api.github.com/repos/Twilight719/realtime-translate-subtitles/actions/runs?per_page=1" \
  | python -c "import json,sys; r=json.load(sys.stdin)['workflow_runs'][0]; print(r['head_branch'], r['status'], r['conclusion'])"
```
- 正常约 4~6 分钟完成，`status=completed conclusion=success` 即成功。
- 失败时拉日志：`GET /actions/runs/{id}/jobs` 拿 job id，再 `GET /actions/jobs/{job_id}/logs`（curl 加 `-L` 跟随重定向）。

### 发布后验证 Release 页面

```bash
curl -s --ssl-no-revoke -H "Authorization: token <TOKEN>" \
  "https://api.github.com/repos/Twilight719/realtime-translate-subtitles/releases/tags/v1.3.8"
```
检查三点：① body 含完整双语日志（不是"详见 CHANGELOG.md"兜底）② 附件 zip 文件名带版本号 ③ 记录 `digest`（sha256）备用。

---

## 5. 更新用户电脑上的安装（两种方式）

### 方式 A：用户自助（首选）

软件内「设置 → 检查更新 → 软件内下载更新」，下载完点"是"自动重启完成。
（v1.3.6+ 误关界面后重试会复用已下载的包，不重复下载。）

### 方式 B：AI 手动应用（用户不会操作或自更新失败时）

```powershell
# 写成带 BOM 的 .ps1 执行。先 taskkill！
$zip = "C:\Users\张坤源\AppData\Local\Temp\realtime-translate-subtitles-vX.Y.Z-windows-x64.zip"
$stage = "C:\Users\张坤源\AppData\Local\Temp\rts_stage"
$dst = "C:\rtbuild\dist\实时翻译字幕"
Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue
Expand-Archive -Path $zip -DestinationPath $stage -Force
# /XF 保留用户配置和日志；/XD 保留已下载的模型；/R:2 /W:2 防止卡死
robocopy "$stage\实时翻译字幕" $dst /E /IS /XF config.yaml app.log app.log.1 app.log.2 /XD models /NFL /NDL /NJH /NJS /R:2 /W:2 | Out-Null
Remove-Item -Recurse -Force $stage
Remove-Item -Force $zip
```

下载更新包（镜像优先，GitHub 直连保底，**必须校验大小和 sha256**）：
```bash
for MIRROR in "https://ghfast.top/" "https://gh-proxy.com/" ""; do
  curl -sL --ssl-no-revoke --connect-timeout 8 -o "$DEST" "${MIRROR}${URL}"
  # 对比 Release API 里的 size 和 digest(sha256)，不符则换下一个通道
done
```

应用后启动并验证版本：
```bash
cd /c/rtbuild/dist && start "" "实时翻译字幕\实时翻译字幕.exe"
sleep 12
grep -o "'has_update': [A-Za-z]*\|latest': '[^']*'" "/c/rtbuild/dist/实时翻译字幕/app.log" | tail -2
# has_update: False 且 latest 等于新版本号 = 升级成功
```

---

## 6. 清理

- 删除 Temp 里的更新包 zip、解压目录、临时 ps1 脚本（用户在意 C 盘空间）
- 删除 tools/ 下的调试截图（已在 .gitignore：`screen_dbg.png` `ocr_modes.png` `ocr_colors.png`）
- `git status --porcelain` 确认无遗漏文件再提交

---

## 7. 排障速查

| 现象 | 原因 | 处理 |
|------|------|------|
| Release 页面日志只有"详见 CHANGELOG" | 日志提取步骤版本号为空/格式不匹配 | 本地跑 `tools/extract_notes.py <tag>` 复现；修复后用 API PATCH release body 回填 |
| 软件内更新弹"开发模式" | 用户运行的是源码版（python main.py）而非安装包版 | 杀掉 python main.py 进程，用桌面快捷方式启动后重新更新 |
| 覆盖安装脚本卡死 | exe 正在运行被锁定，robocopy 无限重试 | 先 `taskkill //F //IM "实时翻译字幕.exe"` |
| GitHub API 401 | token 被 GitHub 吊销（明文泄露会自动吊销） | 让用户生成新 token（Settings → Developer settings → PAT classic → 勾 repo） |
| Qt 测试脚本 exit 127 无输出 | 缺 Qt 插件路径 | 见第 1 节的 addLibraryPath |
| 点桌面快捷方式没反应 | 已有源码版实例在跑（单实例机制会转发给它） | 杀掉 dev 实例再用快捷方式 |
