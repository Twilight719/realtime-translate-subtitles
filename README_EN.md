# Realtime Translate Subtitles 实时翻译字幕

[简体中文](README.md) | English

A Windows desktop tool for real-time translated subtitles: it listens to your PC's audio (videos, games, meetings), transcribes speech with Whisper, translates it, and shows the result as a floating subtitle overlay.

## Features

- **Floating subtitle bar**: translucent, always-on-top, click-through (never blocks your game), draggable, auto-fades when silent
- **Simultaneous-interpreter style captions**: previous sentence + current original + current translation; unconfirmed text scrolls in dim italics while confirmed text stays rock solid
- **Automatic language detection**: Whisper recognizes ~99 languages; you can also lock the source language (zh/en/ja/ko/ru) for better speed and accuracy. An optional SenseVoice engine offers ~30x real-time recognition on CPU for zh/en/ja/ko/yue
- **Multiple translation backends**: Youdao / LLM APIs (DeepSeek etc.) / MyMemory / Google / offline NLLB fallback, tried in priority order with automatic failover
- **Headphone hot-swap**: follows the default output device automatically when you plug/unplug headphones
- **GUI settings**: subtitle style (font/color/opacity/width/position), screenshot popup, languages, models, translation backends, log viewer — each option has a built-in explanation; UI available in Chinese and English
- **Global hotkey** (Alt+T by default, customizable to any Ctrl/Alt/Shift combo in Settings), system tray
- **Screenshot translation**: press Ctrl+Alt+R and drag-select any screen region → built-in Windows OCR → translation popup — made for manga and image text (Japanese requires the Windows Japanese language pack)
- **Auto-update**: silent update check on startup with a tray notification; in-app download (China-friendly GitHub mirrors first, GitHub direct as fallback), then automatic file replacement and restart — your config and downloaded models are preserved

## Quick start (users)

1. Download the latest package from [Releases](../../releases) and extract it anywhere
2. Run `实时翻译字幕.exe` (Windows SmartScreen may warn on first launch — choose "Run anyway")
3. Press **Alt+T** to start listening; right-click the tray icon for settings

### First run downloads models (important)

- **Speech recognition model** (~460MB): downloaded automatically from a mirror (hf-mirror.com) on first Alt+T — keep your network connected; the subtitle bar shows progress hints
- **Offline translation model** (~600MB): only downloaded when the local NLLB fallback is actually used
- If a download fails, the subtitle bar shows an error — check your network and press Alt+T again to resume
- Models are downloaded once and reused forever (translation itself still needs network unless you use NLLB)

## Run from source (developers)

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

With an NVIDIA GPU use `cuda`; for CPU-only, switch the device to `cpu` (compute type `int8`) in settings.

`config.yaml` is generated automatically on first run (see `config.example.yaml`).

## Build the exe yourself

```bash
.venv\Scripts\pip install -r requirements-dev.txt
build.bat
```

Output goes to `dist\实时翻译字幕\`. Note: **the project path must not contain non-ASCII characters** (Qt computes a broken plugin path otherwise). Copy the project (including `.venv`) to a plain-ASCII path before building — see README.md for the exact robocopy command.

## Check for updates

- **Automatic**: the app silently checks for updates on startup and shows a tray notification when a new version is available; click the notification to open Settings
- **Manual**: Settings → Home → About → "检查更新"
- **In-app download**: downloads via China-friendly GitHub mirrors first (ghfast.top / gh-proxy.com / ghproxy.net), falling back to GitHub direct; verifies the zip and its official sha256, then replaces files and restarts automatically, keeping your config and models

See [CHANGELOG.md](CHANGELOG.md) for per-version release notes (Chinese + English).

## Tech stack

faster-whisper (ASR) · silero VAD (speech segmentation) · PyQt5 (UI) · soundcard (loopback capture) · CTranslate2/NLLB (offline translation)

## License

MIT (see [LICENSE](LICENSE)).

**Author: [Twilight719](https://github.com/Twilight719)**. Feel free to learn from, adapt, or build upon this project — but please **credit the original author and link back to this repository** in your project's documentation (e.g. "Based on [realtime-translate-subtitles](https://github.com/Twilight719/realtime-translate-subtitles)"), and keep the copyright notice in LICENSE, as required by the MIT License.
