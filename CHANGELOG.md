# 更新日志 / Changelog

本文件记录每个版本的主要变化。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

All notable changes to this project are documented here, following [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [v1.3.0] - 2026-10-08

### 新增 / Added

- **界面多语言**：设置 → 主页 → 界面 → 界面语言，支持 中文 / English，覆盖设置窗口、托盘菜单、弹窗提示、字幕状态提示等全部界面文字（重启后完全生效）。
  UI language setting (Settings → Home → Interface → Language): Simplified Chinese or English, covering the settings window, tray menu, dialogs and subtitle status messages (takes full effect after restart).
- **截图翻译弹窗自定义**：设置 → 字幕外观 → 截图翻译弹窗，可调弹窗停留时长（0 = 不自动关闭，点击关闭）、字号、背景不透明度。弹窗现在默认 8 秒自动关闭。
  Customizable screenshot-translation popup: duration (0 = stay until clicked), font size, and background opacity (Settings → Subtitle Appearance). The popup now auto-closes after 8 seconds by default.

### 修复 / Fixed

- **截图翻译热键偶发失灵**：修改热键后旧的事件过滤器没有从 Qt 移除，被回收后留下悬挂指针，导致热键消息静默丢失（表现为一段时间后按热键无反应）。
  Fixed screenshot hotkey silently dying: rebinding a hotkey left a dangling native event filter in Qt's filter chain after the old manager was garbage-collected, which eventually swallowed hotkey messages.

---

## [v1.2.2] - 2026-10-08

### 变更 / Changed

- **截图翻译默认热键由 Alt+R 改为 Ctrl+Alt+R**：Alt+R 与 AMD Radeon 显卡面板等常见软件的全局热键冲突，导致部分电脑上注册失败。已自定义过热键的用户不受影响，新安装或未设置过的用户使用新默认值。
  Default screenshot-translation hotkey changed from Alt+R to Ctrl+Alt+R: Alt+R conflicts with common software such as the AMD Radeon overlay, causing registration to fail on some machines. Users who already customized the hotkey are unaffected.

---

## [v1.2.1] - 2026-10-08

### 修复 / Fixed

- **截图翻译中文/日文识别结果多余空格**：Windows OCR 对中日文会逐字加空格（"你 好 世 界"），直接送翻译会影响质量。现在自动清除 CJK 字符之间的空格后再翻译和显示。
  Screenshot translation: Windows OCR inserts a space between every CJK character ("你 好 世 界"). These spaces are now stripped before translation and display.

---

## [v1.2.0] - 2026-10-08

### 新增 / Added

- **截图翻译（OCR）**：按 Alt+R（可在设置页自定义）框选屏幕任意区域 → Windows 内置 OCR 识别文字 → 走当前翻译链 → 在选区旁弹窗显示原文和译文。看漫画、游戏内图片文字、不可复制的界面文字都可以直接翻。识别语言跟随设置的源语言（翻译日语需在 Windows 设置 → 时间和语言 → 语言 中安装日语语言包，否则自动降级到已有语言并记日志提示）。托盘菜单也新增"截图翻译"入口。
  Screenshot translation (OCR): press Alt+R (customizable) to drag-select any screen region → built-in Windows OCR recognizes the text → it goes through your translation chain → a popup next to the region shows original and translation. Great for manga, in-game image text, and non-copyable UI text. OCR language follows the configured source language (Japanese manga requires the Japanese language pack in Windows Settings → Time & Language → Language; otherwise it falls back gracefully).
- **第二个全局热键**：截图翻译热键与启停热键相互独立，均可在设置页点击捕获修改、一键恢复默认，保存后立即生效，无需重启。
  Second global hotkey: the OCR hotkey is independent from the start/stop hotkey — both are rebindable with capture-to-set, one-click restore to default, and apply instantly.

---

## [v1.1.0] - 2026-10-08

### 新增 / Added

- **SenseVoice 极速识别引擎**：设置 → 识别模型 → 识别引擎，新增 SenseVoice 选项（阿里开源，sherpa-onnx 推理）。专为中/英/日/韩/粤优化，CPU 上约 30 倍实时速度（7 秒语音约 0.25 秒出结果），模型加载仅约 1 秒，不占用显卡——显卡可以完全留给游戏。首次使用自动下载约 230MB 模型。看日/英视频强烈推荐；识别引擎切换保存后自动重启生效。
  New SenseVoice engine option (Settings → Recognition): optimized for zh/en/ja/ko/yue, ~30x real-time on CPU (a 7-second clip decodes in ~0.25 s), model loads in ~1 s, and uses no GPU at all. Downloads ~230 MB on first use.

---

## [v1.0.12] - 2026-10-08

### 新增 / Added

- **麦克风输入**：设置 → 主页 → 音频来源，除了系统声音（游戏/视频）外，现在可以选麦克风，用于会议、网课、语音聊天等场景。改动保存后自动重启监听生效。
  Microphone input: Settings → Home → audio source now lists real microphones alongside system audio, for meetings/online classes/voice chat. Applies with an automatic capture restart.
- **开机自动启动**：设置 → 主页 → 界面 → 勾选“开机自动启动”，登录 Windows 后自动托盘常驻。
  Optional “launch on Windows startup” toggle (tray-resident).
- **字幕记录页**：设置 → 字幕记录，回看本次会话的所有定稿字幕（最多 5000 条），可一键导出为带时间戳的 TXT 文本。
  New “Subtitle history” page: review all finalized subtitles of this session (up to 5000) and export them as a timestamped TXT file.

### 其他 / Misc

- 默认大模型名由 `deepseek-chat` 改为正式名称 `deepseek-flash`（DeepSeek V4.1 Flash；旧名官方已停用并被路由到新模型，旧配置不受影响）。
  Default LLM model name updated to `deepseek-flash` (DeepSeek V4.1 Flash). The retired `deepseek-chat` name is routed there by DeepSeek, so existing configs keep working.

---

## [v1.0.11] - 2026-09-30

### 新增 / Added

- **新增 large-v3-turbo 识别档位**：识别精准度接近最大的 large-v3，但专为实时设计（解码层仅 4 层），显卡上速度与 small 相当，追求准确度推荐使用。首次选择需下载约 1.6GB，显存多占约 1GB。
  New `large-v3-turbo` model tier: near-large-v3 accuracy at small-like speed on GPU (turbo is built for real-time use). First use downloads ~1.6 GB and uses ~1 GB more VRAM.
- **识别提示词**：设置 → 识别模型 → 识别提示词，填入作品名/角色名/术语（如“原神 派蒙 元素爆发”），专有名词识别明显更准。改动立即生效，无需重载模型。
  Recognition prompt: tell the recognizer background vocabulary (show/character names, terminology) for noticeably better proper-noun accuracy. Applies instantly without reloading the model.
- **int8_float16 计算精度选项**（cuda）：比 float16 更快、显存更省，质量几乎无损。
  New `int8_float16` compute type for CUDA: faster and less VRAM than float16 with nearly identical quality.

### 优化 / Improved

- **模型加载后自动预热**：加载完成即跑一遍静音识别，提前完成 CUDA 内核编译与调优，消除第一句话的 1~2 秒卡顿。
  Warm-up pass right after model load (CUDA kernels pre-compiled), removing the 1–2 s stall on the first sentence.
- **识别改为单遍模式**：旧版遇到嘈杂音频（游戏 BGM/音效）会触发升温重试、最多重复 8 遍，是长时间使用后延迟越积越高的隐藏原因之一。现在固定单遍出结果，杜绝延迟突刺。
  Single-pass recognition: the old temperature-fallback could re-run a noisy segment up to 8 times, a hidden cause of growing latency during long sessions. Now it always decodes in one pass.

---

## [v1.0.10] - 2026-09-30

### 新增 / Added

- **自定义全局热键**：设置 → 主页 → 全局热键，点击按钮后按下新组合键（Ctrl/Alt/Shift/Win + 字母/数字/F1~F12），保存后立即生效；旁边有"恢复默认 (Alt+T)"按钮。新热键被其他程序占用时会提示并保留原热键。托盘菜单的快捷键提示文字同步更新。
  Customizable global hotkey: press any Ctrl/Alt/Shift/Win + key combo in Settings → Home. Takes effect immediately on save, with a "restore default (Alt+T)" button; conflicts are detected and the old hotkey is kept.
- **新版本主动提醒**：软件启动后自动静默检查一次更新，发现新版本时托盘弹通知，点击通知直接打开设置页。
  Startup update check: a tray notification appears when a new version is available; clicking it opens the settings page.
- **软件内下载更新（镜像优先，GitHub 保底）**：发现新版本后可直接在软件内下载——优先依次尝试国内 GitHub 加速镜像（ghfast.top / gh-proxy.com / ghproxy.net），全部失败才用 GitHub 直连；带进度条、可取消；下载完成自动校验（zip 完整性 + GitHub 官方 sha256），确认后自动替换旧文件并重启，你的配置和已下载的模型都会保留。
  In-app update download: tries China-friendly GitHub mirrors first, falls back to GitHub direct; progress bar with cancel; verifies zip integrity and official sha256; then replaces files and restarts automatically, preserving your config and downloaded models.

### 修复 / Fixed

- **设置页改动识别/翻译参数可能不生效**：设置页与主程序共享同一个配置对象，导致"改动检测"永远认为没变化，修改识别模型等参数后不会自动重建。现在用独立快照对比，参数改动可靠生效。
  Changing recognition/translation settings could silently do nothing because the change-detection compared the shared config object against itself. A snapshot-based comparison now reliably detects changes.

---

## [v1.0.9] - 2026-09-30

### 新增 / Added

- **单实例运行**：重复双击快捷方式不再开出多个软件窗口，而是把已运行实例的设置页弹到前台（和其他桌面软件行为一致）。
  Single-instance: launching the app again now brings the running instance's settings window to the front instead of spawning a second copy.

### 修复 / Fixed

- **"热键被占用"误报**：之前多开的每个实例都会抢同一个全局热键，只有第一个能注册成功，其余实例报"alt+t 被其他程序占用"——占用的其实是自己。单实例化后此问题消除。
  The "hotkey alt+t is occupied" warning was caused by duplicate instances of this app competing for the same global hotkey. Single-instance enforcement removes the conflict.
- **模型加载失败：Requested float16 compute type...**：当 GPU 后端本次不可用（驱动/显存/缺库）时，float16 不被支持，旧版直接报错罢工。现在自动降级：同设备 int8 → CPU int8，并在日志中记录降级过程。
  Whisper model loading now falls back automatically (float16 → int8 → CPU int8) instead of failing outright when the GPU backend is unavailable.

---

## [v1.0.8] - 2026-09-30

### 修复 / Fixed

- **MyMemory 后端永远失败**：whisper 给的是 en/zh 短语言码，MyMemory 要求 en-US/zh-CN 格式，导致该后端一直报 "No support for the provided language"，从未成功过。已修正语言码映射。
  MyMemory backend never worked: whisper's short language codes (en) are now mapped to MyMemory's format (en-US).
- **有道频繁触发限流（411 请求频率过快）**：实时快照每 0.8 秒都会翻译一次尾部文字，即使尾部没变也重复请求。现在尾部内容不变时直接复用上次译文，大幅减少在线翻译请求量。
  Live snapshots no longer re-translate an unchanged tail, greatly reducing online translation calls that were tripping Youdao's rate limit.
- **NLLB 离线模型下载偶发失败**：下载失败时现在会记录完整错误堆栈，并 5 秒后自动重试一次。
  NLLB model download failures now log a full traceback and retry once automatically.
- **日志查看时滚动条被弹回顶部**：日志页每 2 秒自动刷新会重置滚动位置。现在翻阅历史时保持你的滚动位置，只有停在底部时才跟随最新日志。
  Log viewer no longer resets the scroll position on auto-refresh while you're reading history; it only follows new entries when you're already at the bottom.

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

[v1.3.0]: https://github.com/Twilight719/realtime-translate-subtitles/releases/tag/v1.3.0
[v1.2.2]: https://github.com/Twilight719/realtime-translate-subtitles/releases/tag/v1.2.2
[v1.2.1]: https://github.com/Twilight719/realtime-translate-subtitles/releases/tag/v1.2.1
[v1.2.0]: https://github.com/Twilight719/realtime-translate-subtitles/releases/tag/v1.2.0
[v1.1.0]: https://github.com/Twilight719/realtime-translate-subtitles/releases/tag/v1.1.0
[v1.0.12]: https://github.com/Twilight719/realtime-translate-subtitles/releases/tag/v1.0.12
[v1.0.11]: https://github.com/Twilight719/realtime-translate-subtitles/releases/tag/v1.0.11
[v1.0.10]: https://github.com/Twilight719/realtime-translate-subtitles/releases/tag/v1.0.10
[v1.0.9]: https://github.com/Twilight719/realtime-translate-subtitles/releases/tag/v1.0.9
[v1.0.8]: https://github.com/Twilight719/realtime-translate-subtitles/releases/tag/v1.0.8
[v1.0.7]: https://github.com/Twilight719/realtime-translate-subtitles/releases/tag/v1.0.7
[v1.0.6]: https://github.com/Twilight719/realtime-translate-subtitles/releases/tag/v1.0.6
[v1.0.5]: https://github.com/Twilight719/realtime-translate-subtitles/releases/tag/v1.0.5
[v1.0.4]: https://github.com/Twilight719/realtime-translate-subtitles/releases/tag/v1.0.4
[v1.0.3]: https://github.com/Twilight719/realtime-translate-subtitles/releases/tag/v1.0.3
[v1.0.2]: https://github.com/Twilight719/realtime-translate-subtitles/releases/tag/v1.0.2
[v1.0.1]: https://github.com/Twilight719/realtime-translate-subtitles/releases/tag/v1.0.1
[v1.0.0]: https://github.com/Twilight719/realtime-translate-subtitles/releases/tag/v1.0.0
