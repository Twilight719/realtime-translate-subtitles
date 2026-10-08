# 实时翻译字幕（Realtime Translate Subtitles）

简体中文 | [English](README_EN.md)

Windows 桌面实时翻译字幕工具：监听电脑播放的声音（视频、游戏、会议），实时语音识别 + 翻译，以悬浮字幕条显示在屏幕上。

## 功能特性

- **悬浮字幕条**：半透明置顶、点击穿透（不影响游戏操作）、可拖动定位、无语音自动淡出、双语/纯译文/纯原文三种显示模式
- **三行同传式字幕**：历史句 + 当前句原文 + 当前句译文；正在识别的部分以半透明斜体滚动显示，定稿部分稳定不闪
- **自动识别语言**：支持约 99 种语言的语音识别（Whisper），也可手动锁定源语言（中/英/日/韩/俄）提速提准；另可选 SenseVoice 极速引擎（中/英/日/韩/粤，CPU 约 30 倍实时速度）
- **多翻译后端**：有道 / 大模型 API（DeepSeek 等）/ MyMemory / Google / 本地 NLLB 离线兜底，按优先级自动回退
- **耳机插拔自动跟随**：默认输出设备切换时自动切换监听源
- **图形化设置界面**：字幕样式（字体/颜色/透明度/宽度/位置）、语言、模型、翻译后端、日志查看，附逐项说明
- **全局热键**启停（默认 Alt+T，可在设置页自定义为任意 Ctrl/Alt/Shift 组合）、系统托盘常驻
- **截图翻译**：按 Alt+R 框选屏幕区域 → Windows 内置 OCR 识别 → 翻译弹窗，看漫画/图片文字专用（日语需安装 Windows 日语语言包）
- **自动更新**：启动时静默检查新版本并托盘提醒；软件内一键下载更新（优先国内加速镜像，GitHub 直连保底），下载后自动替换重启，配置与模型保留

## 快速开始（普通用户）

1. 从 [Releases](../../releases) 下载最新压缩包，解压到任意目录
2. 运行 `实时翻译字幕.exe`（首次启动会被 Windows SmartScreen 提示，属正常现象，选“仍要运行”）
3. 按 **Alt+T** 开始监听；右键托盘图标可打开设置

### 首次运行会自动下载模型（重要）

- **语音识别模型**（约 460MB）：第一次按 Alt+T 时自动从国内镜像（hf-mirror.com）下载，请保持网络畅通，字幕条会显示下载提示
- **离线翻译模型**（约 600MB）：只有在线翻译全部失败、用到本地 NLLB 兜底时才下载
- 下载失败时字幕条会提示错误，检查网络后重新按 Alt+T 即可续传重试
- 模型下载一次永久有效，之后启动无需网络（翻译仍需联网，除非用 NLLB）

## 源码运行（开发者）

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

GPU（NVIDIA）可跑 `cuda`；纯 CPU 把设置里的运行设备改为 `cpu`（精度 int8）。

配置文件 `config.yaml` 首次运行自动生成（参考 `config.example.yaml`）。

## 自己打包 exe

```bash
.venv\Scripts\pip install -r requirements-dev.txt
build.bat
```

输出在 `dist\实时翻译字幕\`。注意：**项目路径不能含中文**（Qt 在中文路径下会算出错误的插件目录导致打包失败；目录联接 junction 无效，venv 会解析回真实路径）。如果项目在中文路径，先整目录复制到纯英文路径再构建：

```bat
robocopy "D:\翻译插件" "C:\rtbuild" /E /XD "D:\翻译插件\.git" "D:\翻译插件\dist" "D:\翻译插件\build" "D:\翻译插件\models" __pycache__ /XF "*.log"
cd /d C:\rtbuild && build.bat
```

（排除目录要写绝对路径，只写 `models` 会把 venv 里所有同名目录一并排除。）

## 检查更新

- **自动提醒**：软件启动后会静默检查一次新版本，有更新时托盘弹通知，点击通知打开设置页
- **手动检查**：设置 → 主页 → 关于 → 「检查更新」
- **软件内下载更新**：发现新版本后可直接在软件内下载——优先走国内 GitHub 加速镜像（ghfast.top / gh-proxy.com / ghproxy.net），全部失败才用 GitHub 直连保底；下载完成自动校验（zip 完整性 + 官方 sha256）、替换旧文件并重启，你的配置和已下载模型都会保留

每个版本的详细变化见 [更新日志](CHANGELOG.md)。

## 技术栈

faster-whisper（语音识别）· silero VAD（语音切分）· PyQt5（界面）· soundcard（音频回采）· CTranslate2/NLLB（离线翻译）

## 许可证

MIT（见 [LICENSE](LICENSE)）。

**作者：[Twilight719](https://github.com/Twilight719)**。欢迎参考、借鉴或二次开发，但请在你的项目说明中**标明原作者和本仓库地址**（例如"基于 [realtime-translate-subtitles](https://github.com/Twilight719/realtime-translate-subtitles) 开发"），并保留 LICENSE 中的版权声明——这也是 MIT 协议本身的要求。
