"""入口：装配音频捕获 → VAD → whisper → 翻译 → 字幕窗，含快捷键与托盘。"""

import os
import sys

# 窗口模式打包（--windowed）下没有控制台，sys.stdout/stderr 为 None，
# faulthandler 和 logging 会因此崩溃，先补成空设备
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

import faulthandler

faulthandler.enable()  # 原生崩溃时打印 Python 调用栈（打包版排查用）

import copy
import queue
import threading
import time
from collections import deque

from ruamel.yaml import YAML

from app.paths import base_dir, resource_path

BASE_DIR = base_dir()  # 打包后为 exe 所在目录，开发时为项目根目录
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")
LOG_PATH = os.path.join(BASE_DIR, "app.log")

# HuggingFace 直连不通时走国内镜像（须在 huggingface_hub 被导入前设置）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
# xet 下载通道在国内鉴权不稳定，禁用后走普通 CDN
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

# onnxruntime/faster-whisper 必须先于 PyQt5 导入，否则 Windows 下加载原生 DLL 会崩溃
import onnxruntime  # noqa: F401
import faster_whisper  # noqa: F401

# 本机代理/杀毒软件可能拦截 TLS 并换发自签证书，Python 内置 certifi 不认；
# 改用 Windows 系统证书库校验（检查更新、模型下载等都受益）
try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass

# 让 ctranslate2 找到 pip 安装的 cuBLAS/cuDNN DLL（GPU 推理必需）。
# 直接用完整路径预加载，之后 ctranslate2 按名称 LoadLibrary 即可命中已加载模块。
import ctypes as _ctypes
import glob as _glob

_cuda_roots = [
    os.path.join(sys.prefix, "Lib", "site-packages"),  # 开发环境（venv）
    getattr(sys, "_MEIPASS", sys.prefix),              # PyInstaller 打包后：_internal/nvidia/*/bin
]
for _root in dict.fromkeys(_cuda_roots):
    for _d in _glob.glob(os.path.join(_root, "nvidia", "*", "bin")):
        for _dll in sorted(_glob.glob(os.path.join(_d, "*.dll"))):
            try:
                _ctypes.CDLL(_dll)
            except OSError:
                pass

from PyQt5.QtCore import QObject, QCoreApplication, QTimer, pyqtSignal
from PyQt5.QtGui import QIcon
from PyQt5.QtNetwork import QLocalServer, QLocalSocket
from PyQt5.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

# Qt 5.15 在中文路径下会把插件目录错算成 "????"，需显式注册插件路径
import PyQt5 as _PyQt5

QCoreApplication.addLibraryPath(
    os.path.join(os.path.dirname(_PyQt5.__file__), "Qt5", "plugins")
)

from app.audio_capture import AudioCapture, get_default_loopback, list_loopback_devices
from app.hotkeys import HotkeyManager
from app.live_caption import LiveCaptionState
from app.subtitle_window import SubtitleWindow
from app.transcriber import Transcriber
from app.translator import build_chain
from app.tray import TrayIcon
from app.vad import VadSegmenter

import logging
from logging.handlers import RotatingFileHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        # 滚动日志：单文件 2MB，保留 2 个备份，总量封顶约 6MB
        RotatingFileHandler(
            LOG_PATH, maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8"
        ),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("subtitle")

# 首次运行（或打包后 config.yaml 不在 exe 旁边）时创建的默认配置
DEFAULT_CONFIG = """# 实时翻译字幕配置

audio:
  source: loopback         # loopback = 听系统声音（游戏/视频）；mic = 听麦克风（会议/网课）
  device_name:             # null = 默认设备；也可填设置页“音频来源”里列出的设备名

whisper:
  engine: whisper          # whisper = 精准（可选 large-v3-turbo）；sensevoice = 极速（CPU 即可，约 30 倍实时速度，仅支持 中/英/日/韩/粤）
  model_size: small        # tiny / base / small / medium / large-v3-turbo（最准，首次需下载约 1.6GB）
  device: cuda             # cuda / cpu
  compute_type: float16    # cuda 用 float16 或 int8_float16（更快更省显存）；cpu 建议 int8
  beam_size: 1             # 1 = 最快；提到 3~5 质量略好但更慢
  prompt:                  # 识别提示词（可选）：作品名/角色名/术语，如“原神 派蒙 元素爆发”，专名更准

vad:
  threshold: 0.5
  min_speech_ms: 250
  min_silence_ms: 250        # 停顿多久判定一句结束（调小出字幕更快，太小会把长句切断）
  max_segment_s: 10        # 连续说话时每段最长秒数（强制切段）
  partial_interval_s: 0.8  # 说话过程中每隔多少秒出一次实时快照字幕（调小更跟手，翻译请求更频繁）

language:
  source: auto             # 源语言：auto=自动检测；看单一语言视频可锁定 zh/en/ja/ko/ru，识别更快更准
  target: zh               # 目标语言：zh/en/ja/ko/ru

translator:
  order:                               # 排前面优先，失败自动回退下一个
                                      # 可选 youdao_web / mymemory / google_web / llm_api / nllb
                                      # google_web 需要能访问 Google 的网络
  - youdao_web
  - nllb
  - mymemory
  nllb_device: cpu            # 本地 NLLB 默认 CPU，不占显存
  llm_api:
    base_url: https://api.deepseek.com/v1
    api_key: ""             # 填 key 后在 order 里加 llm_api 即启用
    model: deepseek-flash   # DeepSeek 最新 V4.1 Flash；旧名 deepseek-chat 已被路由到此
    context_size: 1
    stream: true            # true=译文逐字上屏（更实时）；false=整句翻完一次性显示

subtitle:
  width: 700
  font_size: 22
  fade_ms: 5000            # 无新字幕多少毫秒后淡出
  click_through: true      # true=点击穿透（不影响游戏）；false=可拖动位置
  display_mode: both       # both=双语显示；zh=只显示译文；src=只显示原文
  x: 300
  y: 800
  bg_alpha: 140
  zh_color: '#FFE34D'
  src_color: '#FFFFFF'

ui:
  font_size: 13            # 设置界面字体大小（10~22），改大后窗口可手动拉大

app:
  autostart: false         # 开机自动启动（托盘常驻）

hotkey: alt+t              # 全局启停快捷键（设置页可自定义，格式如 ctrl+shift+t）
hotkey_ocr: alt+r          # 截图翻译快捷键：框选屏幕区域 → OCR 识别 → 翻译（看漫画/图片文字用）
"""


def load_config(path=CONFIG_PATH):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(DEFAULT_CONFIG)
        log.info("未找到配置文件，已创建默认配置: %s", path)
    yaml = YAML()
    yaml.preserve_quotes = True
    with open(path, encoding="utf-8") as f:
        return yaml.load(f)


def save_config(cfg, path=CONFIG_PATH):
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096  # 避免注释被折行
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f)


def pick_device(name, source="loopback"):
    """按配置选音频设备。source: loopback=扬声器回环 / mic=麦克风。"""
    from app.audio_capture import get_default_input, list_input_devices

    if source == "mic":
        if not name:
            return get_default_input()
        for dev in list_input_devices():
            if name in dev.name:
                return dev
        raise RuntimeError(f"找不到麦克风: {name}")
    if not name:
        return get_default_loopback()
    for dev in list_loopback_devices():
        if name in dev.name:
            return dev
    raise RuntimeError(f"找不到音频设备: {name}")


def _whisper_model_params(w):
    """识别模型重建只关心这些参数；prompt 等热更新参数不参与对比。"""
    w = dict(w or {})
    w.pop("prompt", None)
    return w


class Pipeline:
    """捕获 → VAD → 识别 → 翻译 的后台流水线，可整体启停。"""

    def __init__(self, cfg, on_subtitle):
        self.cfg = cfg
        self.on_subtitle = on_subtitle
        self._transcriber = None
        self._translator = None
        self._cap = None
        self._threads = []
        self._stop = threading.Event()
        self._gen = 0  # 代数标记：旧线程发现代数变了立即退出，防止僵尸线程抢任务
        # 定稿段落：有序、容量小，满时丢弃最旧的（优先跟上当前语音，避免延迟越积越多）
        self._seg_q = queue.Queue(maxsize=3)
        # 实时快照：容量 1，永远只留最新一条（旧快照是同一段话的过期识别，处理它纯属浪费）
        self._partial_q = queue.Queue(maxsize=1)
        self._model_lock = threading.Lock()
        self._model_ready = threading.Event()
        self._model_error = None
        self._speaker_id = None

    def _ensure_models(self):
        """首次启动时在后台线程加载模型，不卡 UI。"""
        with self._model_lock:
            if self._transcriber is None:
                w = self.cfg["whisper"]
                if w.get("engine", "whisper") == "sensevoice":
                    from app.sensevoice_engine import SenseVoiceTranscriber

                    self._transcriber = SenseVoiceTranscriber()
                else:
                    self._transcriber = Transcriber(
                        model_size=w["model_size"],
                        device=w["device"],
                        compute_type=w["compute_type"],
                        beam_size=w.get("beam_size", 1),
                    )
            if self._translator is None:
                self._translator = build_chain(self.cfg["translator"])
        self._model_ready.set()

    def start(self):
        if self._cap is not None:
            return
        self._stop.clear()
        # 清空队列里的残留：上次停止时可能留有旧语音，混入会造成识别错乱
        for q in (self._seg_q, self._partial_q):
            while True:
                try:
                    q.get_nowait()
                except queue.Empty:
                    break
        threading.Thread(target=self._load_models_safe, daemon=True).start()
        audio_cfg = self.cfg.get("audio") or {}
        source = audio_cfg.get("source", "loopback")
        self._cap = AudioCapture(device=pick_device(audio_cfg.get("device_name"), source))
        self._cap.start()
        # 仅在使用"默认扬声器 loopback"时记录扬声器 id，用于后续检测插拔耳机导致的设备切换
        if source == "mic" or audio_cfg.get("device_name"):
            self._speaker_id = None
        else:
            import soundcard as sc

            self._speaker_id = sc.default_speaker().id
        v = self.cfg.get("vad", {})
        segmenter = VadSegmenter(
            on_segment=self._enqueue_segment,
            on_partial=self._enqueue_partial,
            threshold=v.get("threshold", 0.5),
            min_speech_ms=v.get("min_speech_ms", 250),
            min_silence_ms=v.get("min_silence_ms", 250),
            max_segment_s=v.get("max_segment_s", 10),
            partial_interval_s=v.get("partial_interval_s", 0.8),
        )
        self._gen += 1
        gen = self._gen
        self._threads = [
            threading.Thread(target=self._vad_loop, args=(segmenter, gen), daemon=True),
            threading.Thread(target=self._worker_loop, args=(gen,), daemon=True),
        ]
        for t in self._threads:
            t.start()

    def stop(self):
        if self._cap is None:
            return
        self._stop.set()
        self._cap.stop()
        self._cap = None
        # 等工作线程真正退出（它们每 0.2s 轮询一次 _stop，很快）：
        # 不能用往队列塞 None 的方式通知——残留的 None 会被下次 start 的新线程
        # 立刻吃掉并退出，导致流水线无声坏死（历史上真实发生过的 bug）
        for t in self._threads:
            t.join(timeout=2)
        self._threads = []

    @staticmethod
    def _put_latest(q, item, kind):
        """队列满时丢弃最旧的、放入最新的——宁可跳句也不让字幕越落越远。"""
        try:
            q.put_nowait(item)
        except queue.Full:
            try:
                q.get_nowait()
                log.warning("处理跟不上语速，丢弃最旧的%s，优先处理最新语音", kind)
            except queue.Empty:
                pass
            try:
                q.put_nowait(item)
            except queue.Full:
                pass

    @property
    def running(self):
        return self._cap is not None

    @property
    def models_ready(self):
        return self._model_ready.is_set() and self._model_error is None

    def update_cfg(self, cfg, reload_transcriber=False, reload_translator=False):
        """应用新配置。模型改动在下次启动时重建；若正在运行且识别参数变了，自动重启。"""
        self.cfg = cfg
        if reload_transcriber:
            self._transcriber = None
            self._model_ready.clear()
            if self.running:
                self.stop()
                self.start()
        if reload_translator:
            self._translator = None
            threading.Thread(target=self._rebuild_translator, daemon=True).start()

    def get_translator(self):
        """获取翻译链（OCR 等不经过音频流水线的功能也用）。未构建时现场构建。"""
        with self._model_lock:
            if self._translator is None:
                self._translator = build_chain(self.cfg["translator"])
            return self._translator

    def _rebuild_translator(self):
        try:
            translator = build_chain(self.cfg["translator"])
            with self._model_lock:
                self._translator = translator
            log.info("翻译后端已重建: %s", self.cfg["translator"].get("order"))
        except Exception as e:
            log.exception("翻译后端重建失败: %s", e)

    def _load_models_safe(self):
        try:
            self._ensure_models()
            # 加载完成后告知用户（首次下载模型可能需要几分钟，之前没有任何就绪提示）
            if self._cap is not None:
                log.info("模型已就绪")
                self.on_subtitle({"kind": "info", "zh": "模型已就绪，开始监听"})
        except Exception as e:
            self._model_error = e
            self._model_ready.set()

    def _enqueue_segment(self, segment):
        # 段落定稿后，滞留的旧快照（同一段话的过期识别）已无意义，清掉
        while True:
            try:
                self._partial_q.get_nowait()
            except queue.Empty:
                break
        self._put_latest(self._seg_q, (segment, False), "语音段落")

    def _enqueue_partial(self, segment):
        self._put_latest(self._partial_q, (segment, True), "实时快照")

    def _vad_loop(self, segmenter, gen):
        try:
            self._vad_loop_inner(segmenter, gen)
        except Exception:
            log.exception("VAD 线程意外退出！请把此日志反馈给开发者")
        finally:
            log.info("VAD 线程已退出")

    def _vad_loop_inner(self, segmenter, gen):
        cap = self._cap
        last_check = time.time()
        while not self._stop.is_set() and self._gen == gen:
            # 每 2 秒检查默认输出设备是否变化（如插拔耳机），变了就自动切换监听源
            if self._speaker_id is not None and time.time() - last_check > 2:
                last_check = time.time()
                try:
                    import soundcard as sc

                    current = sc.default_speaker().id
                    if current != self._speaker_id:
                        cap.stop()
                        cap = AudioCapture(device=get_default_loopback())
                        cap.start()
                        self._cap = cap
                        self._speaker_id = current
                        segmenter.reset()
                        log.info("默认音频设备已变化，已自动切换监听源: %s", cap.device.name)
                except Exception as e:
                    log.warning("检测音频设备变化失败: %s", e)
            try:
                chunk = cap.queue.get(timeout=0.2)
            except queue.Empty:
                continue
            segmenter.feed(chunk)
        segmenter.flush()

    def _source_lock(self):
        """源语言锁定：auto → None（自动检测），否则返回 whisper 语言码。"""
        src = (self.cfg.get("language") or {}).get("source", "auto")
        return None if src == "auto" else src

    def _target_lang(self):
        return (self.cfg.get("language") or {}).get("target", "zh")

    def _worker_loop(self, gen):
        try:
            self._worker_loop_inner(gen)
        except Exception:
            # 线程意外死亡 = 流水线无声坏死（不出字幕且无日志），必须留下痕迹
            log.exception("识别工作线程意外退出！请把此日志反馈给开发者")
            self.on_subtitle({"kind": "info", "zh": "内部错误：识别线程异常退出，请停止后重新开始"})
        finally:
            log.info("识别工作线程已退出")

    def _worker_loop_inner(self, gen):
        # 等待模型加载完成（首次启动需要下载模型，可能要几分钟）
        self._model_ready.wait()
        if self._model_error is not None:
            self.on_subtitle({
                "kind": "final", "src": "",
                "zh": f"模型加载失败：{self._model_error}。请检查网络后重新按热键重试",
            })
            return
        live = LiveCaptionState(
            lambda t, lang: self._translator.translate(t, lang, self._target_lang())
        )
        while not self._stop.is_set() and self._gen == gen:
            # 优先处理定稿段落（要挪入历史行）；没有定稿再取最新快照
            try:
                item = self._seg_q.get_nowait()
            except queue.Empty:
                try:
                    item = self._partial_q.get(timeout=0.2)  # 超时轮询，保证 _stop 能即时生效
                except queue.Empty:
                    continue
            seg, is_partial = item
            try:
                tag = "实时快照" if is_partial else "语音片段"
                log.info("%s %.1fs，开始识别", tag, len(seg) / 16000)
                text, lang = self._transcriber.transcribe(
                    seg, language=self._source_lock(),
                    prompt=(self.cfg.get("whisper") or {}).get("prompt"),
                )
                if not text:
                    continue
                if is_partial:
                    # 快照：走 LocalAgreement，定稿区稳定、尾部滚动
                    payload = live.update(text, lang)
                    self.on_subtitle(payload)
                    log.info("识别 [%s]（实时）: %s", lang, text)
                else:
                    # 段落定稿：整句重译，挪入历史行
                    live.reset()
                    zh = None
                    target = self._target_lang()
                    try:
                        llm_cfg = (self.cfg.get("translator") or {}).get("llm_api") or {}
                        if llm_cfg.get("stream", True):
                            # 流式：译文逐字上屏（仅支持流式的后端会逐段回调，其余一次返回）
                            zh = self._translator.translate(
                                text, lang, target,
                                on_delta=lambda acc, t=text: self.on_subtitle(
                                    {"kind": "stream", "src": t, "zh": acc}),
                            )
                        else:
                            zh = self._translator.translate(text, lang, target)
                    except Exception as e:
                        log.warning("翻译整体失败，先显示原文: %s", e)
                    self.on_subtitle({
                        "kind": "final", "src": text,
                        "zh": zh if zh else "…翻译服务暂时不可用…",
                    })
                    log.info("识别 [%s]: %s → %s", lang, text, zh)
            except Exception as e:
                log.exception("处理片段出错: %s", e)


class ToggleBridge(QObject):
    """把后台线程的请求安全地送入 Qt 主线程。"""

    toggle_requested = pyqtSignal()
    subtitle_received = pyqtSignal(dict)  # 上屏负载：kind=live/final
    update_result = pyqtSignal(dict)      # 检查更新结果
    ocr_requested = pyqtSignal()          # 触发截图选区（须在主线程创建选区层）
    ocr_result = pyqtSignal(dict)         # OCR+翻译完成：{"src","zh","anchor"}


class MainApp:
    def __init__(self):
        self.cfg = load_config()
        # 上一次已生效配置的快照（设置页与主程序共享同一个 cfg 对象，
        # 直接对比 old/new 会永远相等，必须用独立快照判断哪些变了）
        self._prev_cfg = copy.deepcopy(self.cfg)
        # Windows 任务栏按 AppUserModelID 分组，显式设置后任务栏才会显示应用图标
        # 而不是 python.exe 的默认图标
        try:
            _ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "RealtimeTranslateSubtitles.1.0"
            )
        except Exception:
            pass
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)

        # 单实例：已有一个实例在运行时，通知它弹出设置页，本进程直接退出。
        # 否则多开实例会互抢全局热键（只有第一个能注册上 alt+t），用户看到的就是
        # "热键被占用"——占用的其实是自己多开的那个。
        if self._activate_existing_instance():
            sys.exit(0)
        # 应用图标：任务栏、标题栏、设置窗口统一使用
        _icon = resource_path(os.path.join("assets", "icon.ico"))
        if os.path.exists(_icon):
            self.app.setWindowIcon(QIcon(_icon))
        self.subtitle_count = 0
        self.settings_window = None
        # 本次会话的字幕历史（定稿句），设置页“字幕记录”可回看/导出
        self.history = deque(maxlen=5000)

        self.window = SubtitleWindow(self.cfg.get("subtitle", {}))

        self.bridge = ToggleBridge()
        self.bridge.toggle_requested.connect(self._do_toggle)
        self.bridge.subtitle_received.connect(self._on_subtitle)
        self.bridge.update_result.connect(self._show_update_result)
        self.bridge.ocr_requested.connect(self._do_ocr_snip)
        self.bridge.ocr_result.connect(self._show_ocr_result)

        # 后台工作线程经 bridge 信号把字幕送进 Qt 主线程（线程安全）
        self.pipeline = Pipeline(self.cfg, self._emit_subtitle)

        self.tray = TrayIcon(on_toggle=self.toggle, on_quit=self.quit,
                             on_settings=self.open_settings, on_ocr=self.start_ocr_snip)
        self.tray.set_hotkey(self.cfg.get("hotkey", "alt+t"))
        self.tray.set_ocr_hotkey(self.cfg.get("hotkey_ocr", "alt+r"))
        self.tray.show()

        self.hotkeys = None
        try:
            self.hotkeys = HotkeyManager(
                app=self.app, hotkey=self.cfg.get("hotkey", "alt+t"), on_toggle=self.toggle
            )
            self.hotkeys.start()
        except Exception as e:
            # 热键被占用（如另一个实例在运行）不应让程序退出，托盘/设置页仍可操作
            log.warning("全局热键注册失败: %s", e)

        self.ocr_hotkeys = None
        try:
            self.ocr_hotkeys = HotkeyManager(
                app=self.app, hotkey=self.cfg.get("hotkey_ocr", "alt+r"),
                on_toggle=self.start_ocr_snip, hotkey_id=0xB002,
            )
            self.ocr_hotkeys.start()
        except Exception as e:
            log.warning("截图翻译热键注册失败: %s", e)
        self._snip = None

        hotkey = self.cfg.get("hotkey", "alt+t")
        tip = (f"按 {hotkey} 开始监听，右键托盘打开设置" if self.hotkeys
               else f"热键 {hotkey} 被占用（是否有另一个实例在运行？），可右键托盘操作")
        self.tray.showMessage(
            "实时翻译字幕", tip,
            QSystemTrayIcon.Information, 3000,
        )

        self._start_instance_server()

        # 启动后静默检查一次更新：有新版本时弹托盘通知，点击通知打开设置页下载
        self._latest_update = None
        self.tray.messageClicked.connect(lambda *_: self.open_settings())
        QTimer.singleShot(5000, lambda: self._check_update(auto=True))

    _INSTANCE_KEY = "realtime-translate-subtitles-single-instance"

    @classmethod
    def _activate_existing_instance(cls):
        """尝试联系已运行的实例。联系成功（=已有实例）返回 True。"""
        sock = QLocalSocket()
        sock.connectToServer(cls._INSTANCE_KEY)
        if not sock.waitForConnected(300):
            return False
        sock.write(b"show-settings")
        sock.flush()
        sock.waitForBytesWritten(300)
        log.info("已有实例在运行，已通知它打开设置页，本实例退出")
        return True

    def _start_instance_server(self):
        self._instance_server = QLocalServer(self.app)
        # 清理上次异常退出可能残留的通道（Windows 上通常无残留，保险起见）
        QLocalServer.removeServer(self._INSTANCE_KEY)
        if not self._instance_server.listen(self._INSTANCE_KEY):
            # 极端情况：两个进程几乎同时启动，都没连上又都来监听 → 后到的退出
            log.warning("单实例通道创建失败，可能有另一个实例正在启动，本实例退出")
            sys.exit(0)
        self._instance_server.newConnection.connect(self._on_second_instance)

    def _on_second_instance(self):
        """后续实例启动时：消耗掉连接，把设置页弹到前台。"""
        while self._instance_server.hasPendingConnections():
            conn = self._instance_server.nextPendingConnection()
            conn.waitForReadyRead(100)
            conn.disconnectFromServer()
        log.info("检测到重复启动，改为打开设置页")
        self.open_settings()

    def _emit_subtitle(self, payload):
        self.bridge.subtitle_received.emit(payload)

    def _on_subtitle(self, payload):
        if payload.get("kind") == "info":
            # 状态提示（如"模型已就绪"）：只上屏，不计入字幕统计
            self.window.update_text("", payload["zh"])
        elif payload.get("kind") == "stream":
            # 流式翻译中间态：逐字刷新，定稿后再走 final
            self.window.update_text(payload["src"], payload["zh"])
        elif payload.get("kind") == "final":
            self.subtitle_count += 1
            self.history.append({
                "time": time.strftime("%H:%M:%S"),
                "src": payload["src"],
                "zh": payload["zh"],
            })
            if self.settings_window is not None:
                self.settings_window.set_subtitle_count(self.subtitle_count)
                self.settings_window.refresh_history()
            self.window.show_final(payload["src"], payload["zh"])
        else:
            self.window.show_live(payload)

    def _finish_drag(self):
        x, y = self.window.exit_drag_mode()
        self.settings_window.set_position(x, y)
        log.info("字幕位置已定位: (%d, %d)，点“保存并应用”生效", x, y)

    def start_ocr_snip(self):
        """热键/托盘触发截图翻译：经 bridge 切回主线程创建选区层。"""
        self.bridge.ocr_requested.emit()

    def _do_ocr_snip(self):
        from app.ocr_tool import SnipOverlay

        if self._snip is not None:
            self._snip.close()
        self._snip = SnipOverlay()
        self._snip.region_selected.connect(self._on_ocr_region)
        self._snip.cancelled.connect(lambda: log.info("截图翻译已取消"))
        self._snip.show()

    def _on_ocr_region(self, rect):
        from app.ocr_tool import grab_region

        path = grab_region(rect)
        if path is None:
            log.warning("截图失败")
            return
        lang_cfg = self.cfg.get("language") or {}
        threading.Thread(
            target=self._ocr_worker,
            args=(path, rect, lang_cfg.get("source", "auto"), lang_cfg.get("target", "zh")),
            daemon=True,
        ).start()

    def _ocr_worker(self, path, rect, src_lang, target):
        from app.ocr_tool import clean_cjk_spacing, ocr_image, pick_ocr_language

        try:
            lang_tag = None if src_lang == "auto" else pick_ocr_language(src_lang)
            text = ocr_image(path, lang_tag)
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            if not lines:
                self.bridge.ocr_result.emit({"src": "", "zh": "", "anchor": rect})
                return
            # 中日文按字符书写，多行直接拼接；空格分词语言用空格连接
            sep = "" if src_lang in ("zh", "ja") else " "
            src = clean_cjk_spacing(sep.join(lines))
            zh = None
            try:
                zh = self.pipeline.get_translator().translate(
                    src, None if src_lang == "auto" else src_lang, target
                )
            except Exception as e:
                log.warning("截图翻译失败: %s", e)
            log.info("OCR [%s]: %s → %s", src_lang, src, zh)
            self.bridge.ocr_result.emit({"src": src, "zh": zh, "anchor": rect})
        except Exception as e:
            log.exception("OCR 失败: %s", e)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def _show_ocr_result(self, payload):
        from app.ocr_tool import OcrResultPopup

        if not payload.get("src"):
            self.tray.showMessage(
                "实时翻译字幕", "截图区域未识别到文字",
                QSystemTrayIcon.Information, 3000,
            )
            return
        zh = payload.get("zh") or "…翻译服务暂时不可用…"
        self._ocr_popup = OcrResultPopup(payload["src"], zh, payload["anchor"])
        self._ocr_popup.show()

    def _check_update(self, auto=False):
        """后台线程查询 GitHub Releases，结果经 bridge 回主线程显示。auto=True 为启动时的静默检查。"""
        from app.updater import check_update

        def run():
            result = check_update()
            result["auto"] = auto
            log.info("检查更新: %s", result)
            self.bridge.update_result.emit(result)

        threading.Thread(target=run, daemon=True).start()

    def _show_update_result(self, result):
        auto = result.pop("auto", False)
        if result.get("has_update"):
            self._latest_update = result
            if auto:
                self.tray.showMessage(
                    "实时翻译字幕",
                    f"发现新版本 {result['latest']}，点击此通知打开设置页下载更新",
                    QSystemTrayIcon.Information, 8000,
                )
            if self.settings_window is not None:
                self.settings_window.show_update_result(result, popup=not auto)
        elif not auto and self.settings_window is not None:
            self.settings_window.show_update_result(result, popup=True)

    def _install_update(self, new_app_dir):
        """软件内更新：生成 PowerShell 脚本——等本进程退出后用新版覆盖程序目录
        （保留 config.yaml、models、日志），然后重新启动。镜像下载见 updater.py。"""
        if not getattr(sys, "frozen", False):
            QMessageBox.information(
                None, "开发模式",
                f"开发环境不执行自动替换。新版本文件位于：\n{new_app_dir}",
            )
            return
        import subprocess
        import tempfile

        pid = os.getpid()
        target = os.path.dirname(sys.executable)
        exe = sys.executable
        staging_root = os.path.dirname(new_app_dir)
        script = f"""
$ErrorActionPreference = "SilentlyContinue"
while (Get-Process -Id {pid}) {{ Start-Sleep -Milliseconds 500 }}
Start-Sleep -Seconds 1
robocopy "{new_app_dir}" "{target}" /E /IS /XF config.yaml app.log app.log.1 app.log.2 /XD models /NFL /NDL /NJH /NJS | Out-Null
Start-Process "{exe}"
Remove-Item -Recurse -Force "{staging_root}"
Remove-Item -Force $MyInvocation.MyCommand.Path
"""
        script_path = os.path.join(tempfile.gettempdir(), "rts_update.ps1")
        # UTF-8 BOM：路径含中文时 PowerShell 5.1 才能正确解析脚本
        with open(script_path, "w", encoding="utf-8-sig") as f:
            f.write(script)
        log.info("开始安装更新: %s → %s", new_app_dir, target)
        subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-WindowStyle", "Hidden", "-File", script_path],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.quit()

    def _rebind_hotkey(self, hotkey, on_trigger, old_mgr, hotkey_id=None):
        """运行时切换全局热键：先注册新的，成功后再注销旧的，失败则保持旧热键。"""
        try:
            mgr = HotkeyManager(
                app=self.app, hotkey=hotkey, on_toggle=on_trigger, hotkey_id=hotkey_id
            )
            mgr.start()
        except Exception as e:
            log.warning("新热键 %s 注册失败: %s", hotkey, e)
            return None
        if old_mgr is not None:
            old_mgr.stop()
        log.info("全局热键已切换: %s", hotkey)
        return mgr

    def _live_preview(self, subtitle_cfg):
        """设置页外观改动：立即应用到字幕窗并显示预览（不写配置文件）。"""
        self.window.apply_config(subtitle_cfg)
        if self.settings_window is not None and self.settings_window.isVisible():
            self.window.update_text(
                "Live preview of the subtitle style.", "实时预览：样式改动即时生效"
            )

    def get_history(self):
        return list(self.history)

    def clear_history(self):
        self.history.clear()
        log.info("字幕记录已清空")

    def open_settings(self):
        if self.settings_window is None:
            from app.settings_window import SettingsWindow

            self.settings_window = SettingsWindow(self.cfg, history_provider=self.get_history)
            self.settings_window.request_toggle.connect(self.toggle)
            self.settings_window.request_clear_history.connect(self.clear_history)
            self.settings_window.request_apply.connect(self.apply_config)
            self.settings_window.request_preview.connect(
                lambda: self.window.update_text(
                    "This is a preview of the subtitle style.", "这是字幕样式预览。"
                )
            )
            self.settings_window.request_drag_start.connect(self.window.enter_drag_mode)
            self.settings_window.request_drag_end.connect(self._finish_drag)
            self.settings_window.request_live_preview.connect(self._live_preview)
            self.settings_window.request_check_update.connect(self._check_update)
            self.settings_window.request_install_update.connect(self._install_update)
            self.settings_window.set_running(self.pipeline.running)
            self.settings_window.set_subtitle_count(self.subtitle_count)
        try:
            audio_cfg = self.cfg.get("audio") or {}
            device_name = pick_device(
                audio_cfg.get("device_name"), audio_cfg.get("source", "loopback")
            ).name
        except Exception:
            device_name = ""
        self.settings_window.refresh_info(device_name)
        if self._latest_update is not None:
            # 启动时已发现新版本：设置页关于区直接显示提示（不弹窗打扰）
            self.settings_window.show_update_result(self._latest_update, popup=False)
        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

    def apply_config(self, cfg):
        prev = self._prev_cfg
        for key, attr, default, handler, btn_name, hotkey_id in (
            ("hotkey", "hotkeys", "alt+t", self.toggle, "btn_hotkey", None),
            ("hotkey_ocr", "ocr_hotkeys", "alt+r", self.start_ocr_snip, "btn_hotkey_ocr", 0xB002),
        ):
            old_hotkey = prev.get(key, default)
            new_hotkey = cfg.get(key, default)
            if new_hotkey == old_hotkey:
                continue
            mgr = self._rebind_hotkey(new_hotkey, handler, getattr(self, attr), hotkey_id)
            if mgr is not None:
                setattr(self, attr, mgr)
                if key == "hotkey":
                    self.tray.set_hotkey(new_hotkey)
                else:
                    self.tray.set_ocr_hotkey(new_hotkey)
            else:
                # 新热键注册失败：配置回退为仍在生效的旧热键
                cfg[key] = old_hotkey
                if self.settings_window is not None:
                    getattr(self.settings_window, btn_name).setText(old_hotkey)
                QMessageBox.warning(
                    None, "热键注册失败",
                    f"热键 {new_hotkey} 注册失败（可能被其他程序占用），已保留原热键 {old_hotkey}。",
                )
        reload_transcriber = _whisper_model_params(cfg.get("whisper")) != _whisper_model_params(prev.get("whisper"))
        reload_translator = cfg.get("translator", {}) != prev.get("translator", {})
        audio_changed = cfg.get("audio", {}) != prev.get("audio", {})
        app_cfg = cfg.get("app") or {}
        if app_cfg.get("autostart") != (prev.get("app") or {}).get("autostart"):
            from app.autostart import is_supported, set_enabled

            if is_supported():
                err = set_enabled(bool(app_cfg.get("autostart")))
                if err:
                    log.warning("开机自启动设置失败: %s", err)
        save_config(cfg)
        self.cfg = cfg
        self.window.apply_config(cfg.get("subtitle", {}))
        self.pipeline.update_cfg(
            cfg,
            reload_transcriber=reload_transcriber,
            reload_translator=reload_translator,
        )
        if audio_changed and self.pipeline.running and not reload_transcriber:
            # 音频来源切换（如 系统声音→麦克风）需要重启捕获；识别参数变化时 update_cfg 已重启过
            self.pipeline.stop()
            self.pipeline.start()
            log.info("音频来源已切换，监听已自动重启")
        self._prev_cfg = copy.deepcopy(cfg)
        if self.settings_window is not None:
            self.settings_window.refresh_info()
        log.info("配置已保存并应用")
        self.tray.showMessage(
            "实时翻译字幕", "配置已保存并应用",
            QSystemTrayIcon.Information, 1500,
        )

    def toggle(self):
        self.bridge.toggle_requested.emit()

    def _do_toggle(self):
        try:
            if self.pipeline.running:
                self.pipeline.stop()
                self.window.set_running(False)
                self.tray.set_running(False)
                log.info("已停止")
            else:
                self.pipeline.start()
                self.tray.set_running(True)
                if not self.pipeline.models_ready:
                    # 模型未就绪时先给用户明确反馈（首次运行要下载约 460MB 识别模型），
                    # 就绪后 Pipeline 会再发一条"模型已就绪"提示
                    self.window.update_text(
                        "", "正在加载模型…（首次运行需下载识别模型约 460MB，请保持网络畅通）"
                    )
                    log.info("已开始监听，模型加载中（首次需下载约 460MB）")
                else:
                    log.info("已开始监听")
            if self.settings_window is not None:
                self.settings_window.set_running(self.pipeline.running)
        except Exception as e:
            log.exception("切换出错")
            QMessageBox.critical(None, "错误", str(e))

    def quit(self):
        self.pipeline.stop()
        if self.hotkeys is not None:
            self.hotkeys.stop()
        if self.ocr_hotkeys is not None:
            self.ocr_hotkeys.stop()
        self.app.quit()

    def run(self):
        sys.exit(self.app.exec_())


if __name__ == "__main__":
    MainApp().run()
