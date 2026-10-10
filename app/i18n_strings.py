"""集中维护界面 中文→英文 翻译映射。

key 必须与代码里传给 tr() 的中文原文逐字一致（含标点、空格、换行）；
f-string 模板用命名占位符（如 {hk}），英文模板同占位名、可调整语序。
新增界面文字时同步在此添加映射，然后在末尾 register(MAP) 统一注册。
"""

from app.i18n import register

MAP = {
    # ---------- settings_window.py · 通用控件 ----------
    "切换 拖动条 / 精确数值输入": "Switch between slider / precise input",
    "请按下新热键…（Esc 取消）": "Press the new hotkey… (Esc to cancel)",
    "不支持的热键": "Unsupported Hotkey",
    "只支持 字母 / 数字 / F1~F12 与 Ctrl/Alt/Shift/Win 的组合。":
        "Only letters / digits / F1~F12 combined with Ctrl/Alt/Shift/Win are supported.",
    "需同时按住 Ctrl/Alt/Shift 之一，请重按…":
        "Hold one of Ctrl/Alt/Shift while pressing the key, please try again…",
    "各项说明 ▾": "Details ▾",
    "各项说明 ▴": "Details ▴",

    # ---------- 翻译后端（BACKENDS） ----------
    "有道翻译（在线）": "Youdao Translate (Online)",
    "国内直连，无需 key，质量良好": "Direct connection in China, no key needed, good quality",
    "MyMemory（在线）": "MyMemory (Online)",
    "免费无需 key，备用": "Free, no key needed, backup",
    "Google 翻译（在线）": "Google Translate (Online)",
    "需要能访问 Google 的网络": "Requires a network that can access Google",
    "大模型 API": "LLM API",
    "DeepSeek/豆包/GPT 等，口语质量最好，需填 key":
        "DeepSeek/Doubao/GPT etc., best colloquial quality, API key required",
    "NLLB 本地模型": "NLLB Local Model",
    "离线兜底，无需网络，速度较慢": "Offline fallback, no network needed, slower",

    # ---------- settings_window.py · 窗口与侧边栏 ----------
    "实时翻译字幕 · 设置 v{ver}": "Realtime Translate Subtitles · Settings v{ver}",
    "主页": "Home",
    "字幕外观": "Subtitle Style",
    "识别模型": "Recognition",
    "翻译服务": "Translation",
    "字幕记录": "Subtitle History",
    "日志": "Log",
    "保存并应用": "Save & Apply",

    # ---------- settings_window.py · 主页 ----------
    "运行状态": "Status",
    "已停止": "Stopped",
    "开始监听": "Start Listening",
    "当前配置": "Current Configuration",
    "全局热键": "Global Hotkeys",
    "音频来源": "Audio Source",
    "识别模型": "Recognition Model",
    "翻译后端": "Translation Backend",
    "恢复默认 (Alt+T)": "Reset to Default (Alt+T)",
    "启停监听": "Toggle Listening",
    "恢复默认 (Ctrl+Alt+R)": "Reset to Default (Ctrl+Alt+R)",
    "截图翻译": "Screenshot Translate",
    "点击左侧按钮后按下新的组合键（Ctrl/Alt/Shift + 字母/数字/F1~F12），“保存并应用”后立即生效。":
        "Click the button on the left, then press the new key combination "
        "(Ctrl/Alt/Shift + letter/digit/F1~F12). It takes effect right after \"Save & Apply\".",
    "输入设备": "Input Device",
    "系统声音 = 游戏 / 视频 / 播放器；麦克风 = 会议、网课、语音聊天。改动“保存并应用”后自动重启监听。":
        "System sound = games / videos / players; Microphone = meetings, online classes, "
        "voice chat. Listening restarts automatically after \"Save & Apply\".",
    "统计": "Statistics",
    "本次会话字幕": "Subtitles This Session",
    "界面": "Interface",
    "界面字体大小": "UI Font Size",
    "中文": "Chinese",
    "界面语言 / Language": "Language",
    "拖动即可看到效果；“保存并应用”后下次打开保持。界面语言在重启软件后完全生效。":
        "Drag to see the effect instantly; it persists after \"Save & Apply\". "
        "The interface language fully takes effect after restarting the app.",
    "开机自动启动（托盘常驻，不弹窗）": "Launch at Windows startup (stays in tray, no window)",
    "仅打包版（exe）支持开机自启": "Auto-start is only supported in the packaged (exe) build",
    "关于": "About",
    "当前版本": "Current Version",
    '作者：<a href="https://github.com/Twilight719">Twilight719</a>'
    '　·　开源地址：<a href="https://github.com/Twilight719/realtime-translate-subtitles">GitHub</a>'
    '　·　MIT 协议':
        'Author: <a href="https://github.com/Twilight719">Twilight719</a>'
        ' · Open source: <a href="https://github.com/Twilight719/realtime-translate-subtitles">GitHub</a>'
        ' · MIT License',
    "创作者": "Credits",
    "检查更新": "Check for Updates",
    "提示：托盘图标双击可快速启停；关闭本窗口不会退出程序（托盘常驻）。":
        "Tip: double-click the tray icon to toggle quickly; closing this window "
        "does not quit the app (it stays in the tray).",
    "默认扬声器（系统声音，跟随系统默认输出）":
        "Default Speaker (system sound, follows the system default output)",
    "扬声器：{name}": "Speaker: {name}",
    "麦克风：{name}": "Microphone: {name}",
    "麦克风：": "Microphone: ",
    "扬声器：": "Speaker: ",
    "（未连接）": " (not connected)",

    # ---------- settings_window.py · 字幕外观 ----------
    "样式": "Style",
    "字体大小": "Font Size",
    "背景不透明度": "Background Opacity",
    "字幕条宽度": "Subtitle Bar Width",
    "无语音淡出": "Fade-out When Silent",
    "点击穿透（鼠标操作穿透字幕窗，不影响游戏）":
        "Click-through (mouse clicks pass through the subtitle window, doesn't affect the game)",
    "双语显示（原文 + 译文）": "Bilingual (original + translation)",
    "只显示译文": "Translation Only",
    "只显示原文": "Original Only",
    "字幕内容": "Subtitle Content",
    "颜色": "Colors",
    "译文颜色": "Translation Color",
    "原文颜色": "Original Color",
    "未确认中的滚动文字会自动使用同色的半透明效果。":
        "Unconfirmed scrolling text automatically uses a semi-transparent version of the same color.",
    "截图翻译弹窗": "Screenshot Translate Popup",
    "弹窗停留时长": "Popup Duration",
    "弹窗字号": "Popup Font Size",
    "弹窗背景不透明度": "Popup Background Opacity",
    "弹窗内容": "Popup Content",
    "弹窗显示在框选区域附近；停留时长填 0 表示不自动关闭（点击弹窗关闭）。":
        "The popup appears near the selected area; set the duration to 0 to keep it "
        "open until clicked.",
    "位置": "Position",
    "顶部居中": "Top Center",
    "屏幕中央": "Screen Center",
    "底部居中": "Bottom Center",
    "手动拖动定位": "Drag to Position",
    "点击后字幕条会显示出来，用鼠标拖到想要的位置 → 点“完成定位” → “保存并应用”":
        "After clicking, the subtitle bar appears; drag it to the desired position "
        "→ click \"Done\" → \"Save & Apply\"",
    "完成定位": "Done",
    "预览字幕效果": "Preview Subtitles",
    "恢复默认设置": "Restore Defaults",
    "外观改动会实时预览（不写入配置）；关闭本窗口时未保存的改动自动还原。点“保存并应用”后才持久生效。":
        "Appearance changes are previewed live (not written to config); unsaved changes are "
        "reverted when this window closes. They only persist after \"Save & Apply\".",
    "字体大小：译文行的字号，原文行和历史行会按比例自动缩小。":
        "Font size: size of the translation line; the original and history lines shrink proportionally.",
    "背景不透明度：字幕条黑底的深浅，20 几乎全透明，255 全黑。":
        "Background opacity: how dark the subtitle bar's black background is; "
        "20 is almost fully transparent, 255 is solid black.",
    "字幕条宽度：字幕的最大宽度，文字超出会自动换行。":
        "Subtitle bar width: the maximum width of subtitles; longer text wraps automatically.",
    "无语音淡出：多久没有新字幕后自动隐藏字幕条，有声音时立即重新显示。":
        "Fade-out when silent: hides the subtitle bar after this long without new subtitles; "
        "it reappears immediately when sound resumes.",
    "点击穿透：开启后鼠标可以穿过字幕条操作游戏；用“手动拖动定位”时会临时关闭。":
        "Click-through: when enabled, the mouse passes through the subtitle bar to the game; "
        "temporarily disabled while using \"Drag to Position\".",
    "字幕内容：双语显示 = 原文+译文两行；只显示译文适合专注看翻译；只显示原文适合练听力。":
        "Subtitle content: bilingual = original + translation lines; translation-only for "
        "focused reading; original-only for listening practice.",
    "颜色：译文/原文的显示颜色，正在识别中的滚动文字自动使用同色的半透明效果。":
        "Colors: display colors of the translation/original; in-progress scrolling text uses "
        "a semi-transparent version of the same color.",
    "位置：预设档位一键摆放到顶部/中央/底部，也可填坐标或手动拖动精确定位。":
        "Position: presets place the bar at top/center/bottom in one click; you can also "
        "enter coordinates or drag it precisely.",
    "选择字幕颜色": "Choose Subtitle Color",
    "确定把字幕外观恢复为默认值吗？\n（点“保存并应用”后才会写入配置）":
        "Restore the subtitle appearance to defaults?\n"
        "(It is only written to the config after \"Save & Apply\")",

    # ---------- settings_window.py · 识别模型 ----------
    "语言": "Language",
    "自动检测": "Auto Detect",
    "英语": "English",
    "日语": "Japanese",
    "韩语": "Korean",
    "俄语": "Russian",
    "源语言（听到的）": "Source Language (heard)",
    "目标语言（翻译成）": "Target Language (translate into)",
    "自动检测适合视频里语言混说；看单一语言视频时锁定源语言，识别更快更准。"
    "语言改动保存后立即生效，无需重启监听。":
        "Auto Detect works well when multiple languages are mixed in a video; for "
        "single-language videos, lock the source language for faster, more accurate "
        "recognition. Language changes take effect immediately after saving — no need "
        "to restart listening.",
    "语音识别引擎": "Speech Recognition Engine",
    "faster-whisper（精准，支持约 99 种语言）": "faster-whisper (accurate, supports ~99 languages)",
    "SenseVoice（极速·CPU 即可，仅 中/英/日/韩/粤）":
        "SenseVoice (ultra-fast, CPU-only, zh/en/ja/ko/yue only)",
    "识别引擎": "Recognition Engine",
    "模型档位": "Model Size",
    "运行设备": "Device",
    "计算精度": "Compute Type",
    "可选：作品名 / 角色名 / 术语，如：原神 派蒙 元素爆发":
        "Optional: title / character names / terms, e.g. Genshin Paimon Elemental Burst",
    "识别提示词": "Recognition Prompt",
    "识别参数改动后自动重启监听生效（需重新加载模型，等待几秒）。":
        "Recognition parameter changes take effect by automatically restarting listening "
        "(the model reloads — wait a few seconds).",
    "识别引擎：faster-whisper 精准、语言多（可选 large-v3-turbo）；SenseVoice 专为中日韩语优化，"
    "CPU 上约 30 倍实时速度、加载仅 1 秒、不抢显卡，看日/英视频强烈推荐。选 SenseVoice 时"
    "下面的模型档位/设备/精度/提示词不生效。":
        "Recognition engine: faster-whisper is accurate and multilingual (large-v3-turbo "
        "available); SenseVoice is optimized for Chinese/Japanese/Korean — about 30x realtime "
        "on CPU, loads in 1 second, no GPU contention — highly recommended for "
        "Japanese/English videos. With SenseVoice, the model size/device/compute type/prompt "
        "below do not apply.",
    "源语言：听到的语言。自动检测适合视频里多国语言混说；看单一语言视频时锁定，识别更快更准。"
    "注意 SenseVoice 只支持 中/英/日/韩/粤，锁定其他语言会自动改回自动检测。":
        "Source language: the language being heard. Auto Detect suits videos mixing multiple "
        "languages; lock it for single-language videos for faster, more accurate recognition. "
        "Note: SenseVoice only supports zh/en/ja/ko/yue — locking any other language falls "
        "back to Auto Detect.",
    "目标语言：字幕翻译成的语言。改动保存后立即生效，无需重启。":
        "Target language: the language subtitles are translated into. Changes take effect "
        "immediately after saving — no restart needed.",
    "模型档位：tiny/base 最快但错字多；small 均衡；large-v3-turbo 最准，专为实时设计，"
    "显卡上速度和 small 相当（首次需下载约 1.6GB，显存多占约 1GB），追求准确度推荐它。":
        "Model size: tiny/base are fastest but error-prone; small is balanced; large-v3-turbo "
        "is the most accurate, designed for realtime use, matching small's speed on GPU "
        "(first run downloads ~1.6GB, uses ~1GB more VRAM) — recommended for accuracy.",
    "运行设备：cuda = 用显卡识别（快）；cpu = 用处理器（慢 3~5 倍），显卡被占满时才考虑。":
        "Device: cuda = GPU recognition (fast); cpu = processor (3~5x slower) — only consider "
        "it when the GPU is fully occupied.",
    "计算精度：cuda 选 float16 或 int8_float16（更快、显存更省，质量几乎无损）；cpu 选 int8。":
        "Compute type: for cuda choose float16 or int8_float16 (faster, less VRAM, almost no "
        "quality loss); for cpu choose int8.",
    "Beam size：识别时每步比较的候选数量。1 最快（实时字幕推荐）；3~5 略准但明显变慢。":
        "Beam size: number of candidates compared at each recognition step. 1 is fastest "
        "(recommended for realtime subtitles); 3~5 is slightly more accurate but noticeably "
        "slower.",
    "识别提示词：告诉模型当前内容的背景词汇（作品名/角色名/术语），专有名词识别明显更准；"
    "改动立即生效，不会重载模型。":
        "Recognition prompt: gives the model background vocabulary (titles/characters/terms) "
        "for noticeably better proper-noun recognition; changes apply immediately without "
        "reloading the model.",
    "识别为单遍模式：嘈杂音频（BGM/音效）不会反复重试，避免延迟累积。":
        "Recognition runs in single-pass mode: noisy audio (BGM/sound effects) is not retried "
        "repeatedly, avoiding latency buildup.",

    # ---------- settings_window.py · 翻译服务 ----------
    "后端优先级（勾选启用，自上而下依次尝试）":
        "Backend Priority (check to enable; tried top to bottom)",
    "上移": "Move Up",
    "下移": "Move Down",
    "NLLB 运行设备": "NLLB Device",
    "大模型 API（选择“大模型 API”后端时生效）":
        "LLM API (applies when the \"LLM API\" backend is selected)",
    "模型名": "Model Name",
    "流式输出（译文逐字上屏，不用等整句翻完，观感更实时）":
        "Streaming output (translation appears word by word — feels more realtime)",
    "后端优先级：排最上面的先用，失败或限流时自动切换到下一个，全部失败会稍后自动恢复重试。":
        "Backend priority: the topmost is used first; on failure or rate-limiting it "
        "automatically falls back to the next, and recovers automatically later if all fail.",
    "有道翻译：免 key、国内直连，速度快，但只支持“外语 ↔ 中文”。":
        "Youdao Translate: no key, direct connection in China, fast — but only supports "
        "\"foreign language ↔ Chinese\".",
    "大模型 API：DeepSeek 等，口语和游戏术语翻译质量最好，需要填 API Key（按量计费）。":
        "LLM API: DeepSeek etc. — best quality for colloquial speech and game terms; "
        "requires an API key (pay-as-you-go).",
    "MyMemory / Google：免费备用；Google 需要能访问它的网络。":
        "MyMemory / Google: free backups; Google requires a network that can access it.",
    "NLLB 本地模型：离线兜底，断网也能翻，质量一般、速度较慢。":
        "NLLB local model: offline fallback — works without Internet, but mediocre quality "
        "and slower.",
    "NLLB 运行设备：cpu 不占显存（推荐，把显存留给识别和游戏）；cuda 更快但多占约 1GB 显存。":
        "NLLB device: cpu uses no VRAM (recommended — leave VRAM for recognition and the "
        "game); cuda is faster but uses ~1GB more VRAM.",
    "Base URL / API Key / 模型名：选择“大模型 API”后端时生效，DeepSeek 官方地址为 https://api.deepseek.com/v1。":
        "Base URL / API Key / Model name: apply when the \"LLM API\" backend is selected; "
        "DeepSeek's official endpoint is https://api.deepseek.com/v1.",
    "流式输出：开启后译文逐字上屏（像打字一样），不用等整句翻完；关闭则等整句翻完一次性显示。仅对“大模型 API”后端生效。":
        "Streaming output: when on, the translation appears word by word (like typing) "
        "without waiting for the full sentence; when off, the full sentence appears at once. "
        "Only applies to the \"LLM API\" backend.",
    "API Key 以明文保存在本地 config.yaml 中。翻译后端改动立即重建，无需重启监听。":
        "The API key is stored in plain text in the local config.yaml. Translation backend "
        "changes are rebuilt immediately — no need to restart listening.",

    # ---------- settings_window.py · 字幕记录 ----------
    "{n} 条": "{n} items",
    "刷新": "Refresh",
    "导出为 TXT": "Export as TXT",
    "清空记录": "Clear History",
    "记录本次会话所有定稿字幕（最多保留 5000 条，退出程序后清空）。":
        "Records all finalized subtitles of this session (up to 5000 entries; "
        "cleared when the app exits).",
    "导出字幕记录": "Export Subtitle History",
    "当前还没有字幕记录。": "There is no subtitle history yet.",
    "字幕记录_%Y%m%d_%H%M.txt": "subtitle_history_%Y%m%d_%H%M.txt",
    "文本文件 (*.txt)": "Text Files (*.txt)",
    "实时翻译字幕 · 会话记录\n": "Realtime Translate Subtitles · Session History\n",
    "导出时间：%Y-%m-%d %H:%M:%S": "Exported: %Y-%m-%d %H:%M:%S",
    "导出完成": "Export Complete",
    "已导出 {n} 条到：\n{path}": "Exported {n} entries to:\n{path}",
    "确定清空本次会话的字幕记录吗？": "Clear this session's subtitle history?",

    # ---------- settings_window.py · 日志 ----------
    "自动刷新": "Auto Refresh",
    "清空日志": "Clear Log",
    "打开所在目录": "Open Containing Folder",
    "（暂无日志）": "(No logs yet)",
    "确定清空 app.log 吗？": "Clear app.log?",

    # ---------- settings_window.py · 状态/更新 ----------
    "运行中": "Running",
    "停止监听": "Stop Listening",
    "正在检查…": "Checking…",
    "检查失败：{err}": "Check failed: {err}",
    "发现新版本 {latest}（当前 v{ver}），点“检查更新”可下载":
        "New version {latest} available (current v{ver}) — click \"Check for Updates\" to download",
    "发现新版本": "New Version Available",
    "最新版本 {latest} 已发布（当前 v{ver}）。\n\n"
    "“软件内下载”会优先走国内加速镜像，全部失败才用 GitHub 直连；\n"
    "下载完成后自动替换旧文件并重启（你的配置和已下载模型都会保留）。":
        "Version {latest} has been released (current v{ver}).\n\n"
        "\"In-app download\" tries China acceleration mirrors first, falling back to direct "
        "GitHub only if all fail;\nafter downloading, it automatically replaces the old "
        "files and restarts (your config and downloaded models are kept).",
    "软件内下载更新（推荐）": "Download In-App (Recommended)",
    "打开下载页面": "Open Download Page",
    "取消": "Cancel",
    "已是最新版本（v{ver}）": "Already up to date (v{ver})",
    "准备下载…": "Preparing download…",
    "下载更新 {latest}": "Downloading Update {latest}",
    "GitHub 直连": "GitHub direct",
    "镜像 {n}": "Mirror {n}",
    "正在下载（{channel}，第 {idx}/{count} 个通道）：\n{done:.0f} / {total:.0f} MB":
        "Downloading ({channel}, channel {idx}/{count}):\n{done:.0f} / {total:.0f} MB",
    "正在下载（{channel}）：{done:.0f} MB": "Downloading ({channel}): {done:.0f} MB",
    "下载失败": "Download Failed",
    "{info}\n\n可以点“检查更新 → 打开下载页面”用浏览器手动下载。":
        "{info}\n\nYou can click \"Check for Updates → Open Download Page\" to download "
        "manually in a browser.",
    "解压失败": "Extraction Failed",
    "{e}\n\n可以用浏览器手动下载后覆盖安装。":
        "{e}\n\nYou can download manually in a browser and install over the existing files.",
    "下载完成": "Download Complete",
    "更新包已就绪，立即重启完成更新吗？\n（当前配置和已下载的模型都会保留）":
        "The update package is ready. Restart now to finish updating?\n"
        "(Your current config and downloaded models will be kept)",
    "更新包结构异常：找不到程序文件": "Invalid update package: program files not found",
    "默认扬声器 (loopback)": "Default Speaker (loopback)",
    "SenseVoice 极速 / cpu": "SenseVoice fast / cpu",
    "热键无效": "Invalid Hotkey",
    "热键“{hk}”无法识别（{err}），本次保留原热键 {old}。":
        "Hotkey \"{hk}\" is not recognized ({err}); keeping the previous hotkey {old}.",

    # ---------- tray.py ----------
    "实时翻译字幕（已停止）": "Realtime Translate Subtitles (Stopped)",
    "实时翻译字幕（运行中）": "Realtime Translate Subtitles (Running)",
    "开始": "Start",
    "停止": "Stop",
    "设置": "Settings",
    "退出": "Quit",

    # ---------- ocr_tool.py ----------
    "（无译文）": "(No translation)",

    # ---------- subtitle_window.py ----------
    "拖动我到想要的位置，完成后点“完成定位”":
        "Drag me to the position you want, then click \"Done\"",

    # ---------- main.py ----------
    "实时翻译字幕": "Realtime Translate Subtitles",
    "模型已就绪，开始监听": "Models ready, listening started",
    "内部错误：识别线程异常退出，请停止后重新开始":
        "Internal error: the recognition thread exited unexpectedly. Please stop and start again.",
    "模型加载失败：{err}。请检查网络后重新按热键重试":
        "Model loading failed: {err}. Check your network and press the hotkey to retry",
    "找不到麦克风: {name}": "Microphone not found: {name}",
    "找不到音频设备: {name}": "Audio device not found: {name}",
    "…翻译服务暂时不可用…": "...translation service temporarily unavailable...",
    "按 {hk} 开始监听，右键托盘打开设置":
        "Press {hk} to start listening; right-click the tray icon to open Settings",
    "热键 {hk} 被占用（是否有另一个实例在运行？），可右键托盘操作":
        "Hotkey {hk} is occupied (is another instance running?); use the tray right-click menu instead",
    "截图区域未识别到文字": "No text recognized in the selected area",
    "发现新版本 {latest}，点击此通知打开设置页下载更新":
        "New version {latest} available — click this notification to open Settings and "
        "download the update",
    "开发模式": "Development Mode",
    "当前运行的是源码版，无法自动替换更新。\n"
    "新版本文件已下载到：\n{path}\n\n"
    "如果你平时用的是安装包版本，请关闭本程序后改用桌面快捷方式启动，"
    "再执行一次「检查更新 → 软件内下载更新」。":
        "You are running the source-code build, which cannot replace itself.\n"
        "The new version was downloaded to:\n{path}\n\n"
        "If you normally use the packaged build, close this app, start it from the "
        "desktop shortcut, and run \"Check for Updates → Download Update\" again.",
    "实时预览：样式改动即时生效": "Live preview: style changes apply instantly",
    "这是字幕样式预览。": "This is a preview of the subtitle style.",
    "热键注册失败": "Hotkey Registration Failed",
    "热键 {hk} 注册失败（可能被其他程序占用），已保留原热键 {old}。":
        "Failed to register hotkey {hk} (possibly occupied by another program); "
        "kept the previous hotkey {old}.",
    "配置已保存并应用": "Configuration saved and applied",
    "正在加载模型…（首次运行需下载识别模型约 460MB，请保持网络畅通）":
        "Loading models… (first run downloads ~460MB of recognition models — "
        "please keep the network connected)",
    "错误": "Error",
}

register(MAP)
