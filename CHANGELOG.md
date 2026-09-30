# 更新日志 / Changelog

本文件记录每个版本的主要变化。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

All notable changes to this project are documented here, following [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [v1.0.2] - 2026-09-30

### 修复 / Fixed

- **打包版"检查更新"报 HTTPS 证书错误**：打包环境漏装 `truststore`（用 Windows 系统证书库校验 HTTPS 的库），导致在网络存在 TLS 拦截的环境中检查更新失败。已将其加入打包清单。
  Fixed "check for updates" failing with an SSL certificate error in the packaged build: `truststore` (which validates HTTPS against the Windows system certificate store) was not bundled. It is now included in the build.
- **网络错误提示过长**：检查更新失败时原本会显示一整段英文堆栈，现在精简为一句中文提示（如"无法连接 GitHub（请检查网络或代理）"），完整错误仍记录在日志中。
  Network error messages shown in the settings window were a long raw exception dump; they are now concise one-line messages, with details still written to the log file.

---

## [v1.0.1] - 2026-09-30

### 修复 / Fixed

- **打包版启动即崩溃**：窗口模式（无控制台）下 `sys.stderr` 为 `None`，`faulthandler` 初始化直接抛异常导致程序无法启动（双击 exe / 桌面快捷方式均受影响）。启动时现在会把空标准流重定向到空设备。
  Fixed the packaged build crashing on startup: in windowed mode (no console) `sys.stderr` is `None`, which made `faulthandler` initialization raise. Null stdio streams are now redirected to the null device at startup.
- **桌面快捷方式中文名乱码**：创建快捷方式的 PowerShell 脚本保存为无 BOM 的 UTF-8，被 Windows PowerShell 5.1 按 GBK 误读。脚本已改为带 BOM 的 UTF-8。
  Fixed garbled Chinese characters in the desktop shortcut name: the shortcut script was saved as UTF-8 without BOM, which Windows PowerShell 5.1 misreads as GBK. The script is now saved with a BOM.

---

## [v1.0.0] - 2026-09-29

首个公开发布版本。 / First public release.

### 功能 / Features

- **实时字幕流水线**：捕获系统扬声器回环音频 → Silero VAD 语音分段 → faster-whisper 本地识别 → 翻译 → 悬浮字幕窗显示。
  Real-time caption pipeline: system audio loopback capture → Silero VAD segmentation → local faster-whisper recognition → translation → floating subtitle overlay.
- **语音识别**：faster-whisper，支持 tiny / base / small / medium 档位，CUDA（float16）或 CPU（int8），可调 beam size；首次运行自动从镜像下载模型并显示进度。
  Speech recognition via faster-whisper with tiny/base/small/medium model sizes, CUDA (float16) or CPU (int8), adjustable beam size; models download automatically on first run with progress display.
- **语言**：源语言自动检测，也可手动锁定中/英/日/韩/俄；目标语言可自由设置为这五种之一。
  Source language auto-detection with optional manual lock to Chinese/English/Japanese/Korean/Russian; target language freely selectable among these five.
- **翻译后端链**：有道网页翻译 → 大模型 API（OpenAI 兼容，默认 DeepSeek，可填自己的 key）→ MyMemory → 本地 NLLB 模型，按顺序自动回退。
  Translation backend chain with automatic fallback: Youdao web → LLM API (OpenAI-compatible, DeepSeek by default, bring your own key) → MyMemory → local NLLB model.
- **实时快照字幕**：说话过程中每隔约 1.5 秒出一次快照，配合 LocalAgreement 策略让已定稿部分稳定、尾部滚动，兼顾及时性和可读性。
  Live partial captions every ~1.5s during speech with a LocalAgreement-style strategy: confirmed text stays stable while the tail keeps updating.
- **字幕窗口**：无边框悬浮窗，可调字体大小、字幕条宽度、背景透明度、原文/译文颜色、淡出时间、位置（支持手动拖拽定位）、点击穿透开关。
  Borderless overlay with adjustable font size, bar width, background opacity, source/translation text colors, fade-out time, position (drag-to-place supported), and click-through toggle.
- **设置界面**：类 app 的图形化设置页，含外观实时预览、恢复默认（带二次确认）、运行状态与统计、日志查看、音频设备选择、模型档位等；设置项均附说明文字。
  App-style settings window with live style preview, restore-defaults (with confirmation), runtime status and stats, log viewer, audio device selection, model options; every setting includes a short explanation.
- **全局热键**：默认 Alt+T 启停监听；托盘图标双击启停、右键打开设置/退出；热键被占用时降级提示不崩溃。
  Global hotkey (Alt+T by default) to start/stop listening; tray icon double-click toggles, right-click opens settings/quit; hotkey conflicts degrade gracefully.
- **耳机插拔自适应**：监听默认输出设备时，每 2 秒检测默认设备变化（如插拔耳机），自动切换到新的回环源。
  Automatic audio source switching: when listening to the default output, device changes (e.g. plugging in headphones) are detected every 2 seconds and capture follows the new device.
- **日志**：滚动日志文件（单文件 2MB，保留 2 份，总量约 6MB 封顶），设置页内可直接查看。
  Rotating log files (2 MB each, 2 backups, ~6 MB total cap), viewable directly in the settings window.
- **检查更新**：设置页一键查询 GitHub Releases 是否有新版本。
  One-click update check against GitHub Releases in the settings window.
- **打包发布**：PyInstaller onedir 打包，模型不含在包内（首次运行自动下载），解压即用无需安装 Python。
  Distributed as a PyInstaller onedir build; models are not bundled (downloaded on first run). No Python installation required.

[v1.0.2]: https://github.com/Twilight719/realtime-translate-subtitles/releases/tag/v1.0.2
[v1.0.1]: https://github.com/Twilight719/realtime-translate-subtitles/releases/tag/v1.0.1
[v1.0.0]: https://github.com/Twilight719/realtime-translate-subtitles/releases/tag/v1.0.0
