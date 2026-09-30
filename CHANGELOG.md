# 更新日志 / Changelog

本文件记录每个版本的主要变化。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

All notable changes to this project are documented here, following [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [v1.0.7] - 2026-09-30

### 修复 / Fixed

- **停止后再开始可能永远不出字幕（严重）**：旧版"停止监听"会往任务队列里塞一个结束标记；这个标记如果没被及时消费掉，下次"开始监听"时新线程会立刻把它吃掉并退出——之后所有语音都进队列但无人处理，表现为字幕完全不出现、日志只剩丢弃警告。现在停止时改为等待线程自然退出，启动时清空队列残留，从根上消除这个问题。
  Fixed a critical bug where toggling stop→start could permanently break subtitles: a leftover stop-marker in the queue was immediately consumed by the new worker thread, killing it. Stop now waits for threads to exit, and start purges queue leftovers.
- **线程意外死亡无痕迹**：VAD 线程和识别线程增加了崩溃日志与退出日志；识别线程异常退出时字幕条会提示"请停止后重新开始"。
  VAD/worker threads now log unexpected exits, and the subtitle bar warns if the worker thread dies.

### 排查工具 / Internal

- 流水线线程增加"代数"标记：重启后旧线程即使因长任务滞留也会自动退出，不会和新线程抢任务。
  Pipeline threads carry a generation marker so stale threads from a previous session retire themselves.

---

## [v1.0.6] - 2026-09-30

### 修复 / Fixed

- **字幕延迟越积越多**：之前所有待处理语音排在同一个队列里（最多 8 条，每条最长 10 秒），一旦某条处理慢了，队列逐渐堆满，积压的旧段落仍按顺序慢慢上屏，导致字幕落后视频越来越多。现在：
  - 实时快照队列容量为 1，新快照直接替换旧快照（旧快照是同一段话的过期识别，处理它纯属浪费）
  - 定稿段落单独一个小队列（3 条），满了丢弃**最旧的**而不是最新的，宁可跳句也不让字幕越落越远
  - 段落定稿时自动清掉它之前滞留的过期快照
  - 发生丢弃时日志会记录"处理跟不上语速"，方便排查
  Subtitle lag no longer accumulates: live snapshots now keep only the newest one (older snapshots of the same utterance are worthless), finalized segments use a small drop-oldest queue, and stale snapshots are purged when a segment finalizes.

---

## [v1.0.5] - 2026-09-30

### 新增 / Added

- **字幕内容模式**：设置 → 字幕外观新增"字幕内容"选项，可切换 双语显示 / 只显示译文 / 只显示原文，支持实时预览。
  New "subtitle content" option: bilingual / translation only / original only, with live preview.
- **大模型流式翻译**：设置 → 翻译服务新增"流式输出"开关（默认开）。开启后译文逐字上屏，不用等整句翻完，观感接近同传。仅当"大模型 API"后端实际承担翻译时生效——想体验它，请把大模型 API 移到后端优先级第一位。
  New "streaming output" toggle for the LLM API backend (on by default): translations appear word-by-word instead of all at once. Applies when the LLM backend actually handles the translation — move it to the top of the backend priority list to experience it.

### 优化 / Changed

- **翻译连接复用**：大模型 API 翻译改为长连接，每次翻译省 0.2~0.5 秒的握手开销（有道此前已是长连接）。
  LLM API translation now reuses a persistent HTTP connection, saving 0.2~0.5s of handshake per call.
- **默认参数调快**：语音停顿判定 400ms → 250ms（句子定稿更快），快照间隔 1.5s → 0.8s（实时字幕更跟手）。已有用户的 config.yaml 不会被覆盖，可在配置文件中手动调整 vad 段。
  Faster defaults: VAD silence threshold 400ms → 250ms (sentences finalize sooner), snapshot interval 1.5s → 0.8s (more responsive live captions). Existing config.yaml files keep their values — edit the vad section manually if desired.

---

## [v1.0.4] - 2026-09-30

### 优化 / Changed

- **模型就绪提示**：模型加载完成后字幕条会显示"模型已就绪，开始监听"，不再需要猜测什么时候加载完。
  The subtitle bar now shows a "model ready, listening" message once model loading finishes.
- **日志不再误导**：之前每次按开始监听，日志都会写一句"首次启动需加载模型"（实际模型早已加载好）；现在只在真正加载模型时才记录"模型加载中"，模型已在内存时直接记"已开始监听"。
  The log previously printed "first-run model loading" on every start even when models were already loaded; it now only mentions loading when a load is actually happening.

---

## [v1.0.3] - 2026-09-30

### 新增 / Added

- **创作者署名**：设置页"关于"区域新增作者（Twilight719）与 GitHub 仓库链接（可点击跳转）。
  Settings → About now shows the author (Twilight719) and a clickable link to the GitHub repository.
- **开源协议文件**：补充 MIT LICENSE 文件；README 明确：借鉴或二次开发请标明原作者与仓库地址。
  Added the MIT LICENSE file; READMEs now ask that adaptations and derivative works credit the original author and link back to this repository.

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

[v1.0.7]: https://github.com/Twilight719/realtime-translate-subtitles/releases/tag/v1.0.7
[v1.0.6]: https://github.com/Twilight719/realtime-translate-subtitles/releases/tag/v1.0.6
[v1.0.5]: https://github.com/Twilight719/realtime-translate-subtitles/releases/tag/v1.0.5
[v1.0.4]: https://github.com/Twilight719/realtime-translate-subtitles/releases/tag/v1.0.4
[v1.0.3]: https://github.com/Twilight719/realtime-translate-subtitles/releases/tag/v1.0.3
[v1.0.2]: https://github.com/Twilight719/realtime-translate-subtitles/releases/tag/v1.0.2
[v1.0.1]: https://github.com/Twilight719/realtime-translate-subtitles/releases/tag/v1.0.1
[v1.0.0]: https://github.com/Twilight719/realtime-translate-subtitles/releases/tag/v1.0.0
