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
import re
import threading
import time
from collections import Counter, deque

from ruamel.yaml import YAML

from app import model_download
from app.paths import base_dir, resource_path

BASE_DIR = base_dir()  # 打包后为 exe 所在目录，开发时为项目根目录
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")
LOG_PATH = os.path.join(BASE_DIR, "app.log")

# 实时快照间隔的自适应上限（秒）：识别+翻译一次要多久，快照间隔就至少拉多长
# （规划 §2.2 c，下限是配置里的 vad.partial_interval_s）
PARTIAL_INTERVAL_MAX_S = 2.0


class PipelineStats:
    """流水线耗时/丢弃统计：每半分钟汇总成一条日志。

    "识别和翻译各花多久""字幕是被处理不过来丢掉的，还是根本没识别出来"——
    以前这些只能靠一条条孤立的日志去猜。汇总成一行后，看直播时把 app.log
    发过来就能直接定位瓶颈在哪一环。"""

    WINDOW_S = 30.0
    MAX_SAMPLES = 300  # 单个窗口内最多留这么多样本（够算中位数，又不吃内存）

    def __init__(self):
        self._start = time.time()
        self._asr = deque(maxlen=self.MAX_SAMPLES)   # 识别耗时
        self._item = deque(maxlen=self.MAX_SAMPLES)  # 单条（识别+翻译）总耗时
        self._dropped = Counter()                    # 丢弃计数（按类型）
        self._interval = None                        # 当前快照间隔（自适应后的实际值）

    def record(self, asr_s=None, item_s=None):
        if asr_s is not None:
            self._asr.append(asr_s)
        if item_s is not None:
            self._item.append(item_s)

    def record_drop(self, kind):
        self._dropped[kind] += 1

    def set_interval(self, seconds):
        self._interval = seconds

    @staticmethod
    def _median(values):
        if not values:
            return 0.0
        ordered = sorted(values)
        mid = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[mid]
        return (ordered[mid - 1] + ordered[mid]) / 2

    def take_due(self, translator):
        """到点且这一窗确实干过活时，返回一行摘要，否则返回 None。"""
        if time.time() - self._start < self.WINDOW_S:
            return None
        if not self._item and not self._dropped:
            self._start = time.time()  # 没在听/没语音：不刷日志，只把窗口往后挪
            return None
        parts = []
        if self._item:
            parts.append(
                "处理 %d 条（单条中位 %.2fs 最慢 %.2fs，识别中位 %.2fs）"
                % (len(self._item), self._median(self._item),
                   max(self._item), self._median(self._asr))
            )
        if self._dropped:
            parts.append("丢弃 " + " ".join(
                "%s %d" % (k, v) for k, v in self._dropped.most_common()))
        if self._interval:
            parts.append("快照间隔 %.1fs" % self._interval)
        used = translator.take_usage() if hasattr(translator, "take_usage") else Counter()
        if used:
            parts.append("翻译后端 " + " ".join(
                "%s×%d" % (k, v) for k, v in used.most_common()))
        self._reset()
        return "流水线统计（近 %.0fs）：%s" % (self.WINDOW_S, " | ".join(parts))

    def _reset(self):
        self._start = time.time()
        self._asr.clear()
        self._item.clear()
        self._dropped.clear()


def partial_interval_for(elapsed, base):
    """按上一次「识别+翻译」的实测耗时算下一次快照间隔（规划 §2.2 c）。

    快的时候保持配置值（跟手性、首字延迟都不变），慢的时候拉到最多 2 秒——
    生成再多快照也只会被丢掉，白白占用识别算力。"""
    return min(PARTIAL_INTERVAL_MAX_S, max(base, elapsed * 1.2))

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

from app.audio_capture import (AudioCapture, get_default_input, get_default_loopback,
                               list_loopback_devices)
from app.hotkeys import HotkeyManager
from app.i18n import set_language, tr
import app.i18n_strings  # noqa: F401  注册中英文映射
from app.live_caption import LiveCaptionState
from app.subtitle_window import SubtitleWindow
from app.transcriber import Transcriber
from app.translator import build_chain
from app.translator import glossary
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
  device: cuda             # cuda / cpu（CPU 精简版安装包不含 CUDA 运行库，选 cuda 会自动降级为 CPU）
  compute_type: float16    # cuda 用 float16 或 int8_float16（更快更省显存）；cpu 建议 int8
  beam_size: 1             # 1 = 最快；提到 3~5 质量略好但更慢
  prompt:                  # 识别提示词（可选）：作品名/角色名/术语，如“原神 派蒙 元素爆发”，专名更准

vad:
  threshold: 0.5
  min_speech_ms: 250
  min_silence_ms: 250        # 停顿多久判定一句结束（调小出字幕更快，太小会把长句切断）
  max_segment_s: 10        # 连续说话时每段最长秒数（强制切段）
  partial_interval_s: 0.8  # 说话过程中每隔多少秒出一次实时快照字幕
                           # （调小更跟手；识别/翻译跟不上时会自动放慢，最多 2 秒）

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
  glossary: []                # 术语表（自定义词典）：每行一条“原文=译文”，如
                              #   - 原神=Genshin Impact
                              # 只有“大模型 API”后端翻译时会遵守；有道/Google/MyMemory/NLLB 不支持。
                              # 词条原文还会作为识别提示词喂给 whisper（专名更准），留空则完全不影响
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

ocr:
  duration_ms: 8000        # 截图翻译弹窗停留毫秒数（0=不自动关闭，点击关闭）
  font_size: 15            # 弹窗字号
  bg_alpha: 235            # 弹窗背景不透明度（0~255）

ui:
  font_size: 13            # 设置界面字体大小（10~22），改大后窗口可手动拉大
  language: zh             # 界面语言：zh=中文；en=English（重启后生效）

app:
  autostart: false         # 开机自动启动（托盘常驻）

hotkey: alt+t              # 全局启停快捷键（设置页可自定义，格式如 ctrl+shift+t）
hotkey_ocr: ctrl+alt+r     # 截图翻译快捷键：框选屏幕区域 → OCR 识别 → 翻译（看漫画/图片文字用）
"""


def default_config_text():
    """首次运行写出的默认配置。

    识别设备按本机实际能力选：CPU 小包（或没有 N 卡驱动）默认写 cpu + int8，
    避免"默认 cuda 但包里没有 CUDA 库"时每次启动都要走一遍加载失败降级。
    """
    try:
        from app import flavor as flavor_mod

        if flavor_mod.has_cuda_libs() and flavor_mod.nvcuda_available():
            return DEFAULT_CONFIG
    except Exception:  # 打包异常等情况下退回保守默认
        log.warning("检测 CUDA 可用性失败，默认配置按 CPU 生成", exc_info=True)
    text = DEFAULT_CONFIG.replace("device: cuda", "device: cpu", 1)
    text = text.replace("compute_type: float16", "compute_type: int8", 1)
    if "device: cpu" not in text:
        # 模板改了措辞导致替换失配：宁可原样生成并留下告警，也别悄悄给错默认值
        log.warning("默认配置模板未匹配到 device: cuda，按模板原样生成")
        return DEFAULT_CONFIG
    return text


def load_config(path=CONFIG_PATH):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(default_config_text())
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
        raise RuntimeError(tr("找不到麦克风: {name}").format(name=name))
    if not name:
        return get_default_loopback()
    for dev in list_loopback_devices():
        if name in dev.name:
            return dev
    raise RuntimeError(tr("找不到音频设备: {name}").format(name=name))


def _whisper_model_params(w):
    """识别模型重建只关心这些参数；prompt 等热更新参数不参与对比。"""
    w = dict(w or {})
    w.pop("prompt", None)
    return w


def _close_quiet(obj):
    """尽力关闭对象（翻译后端等），失败只记日志、不影响主流程。"""
    try:
        obj.close()
    except Exception:
        log.warning("关闭资源失败", exc_info=True)


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
        # 模型加载完成时置位：由 VAD 线程自己丢弃加载期间累积的旧音频
        self._vad_reset_pending = threading.Event()
        self._gen = 0  # 代数标记：旧线程发现代数变了立即退出，防止僵尸线程抢任务
        # 定稿段落：有序、容量小，满时丢弃最旧的（优先跟上当前语音，避免延迟越积越多）
        self._seg_q = queue.Queue(maxsize=3)
        # 实时快照：容量 1，永远只留最新一条（旧快照是同一段话的过期识别，处理它纯属浪费）
        self._partial_q = queue.Queue(maxsize=1)
        self._model_lock = threading.Lock()
        self._model_ready = threading.Event()
        self._model_error = None
        # 未指定设备名时记录系统默认设备（扬声器/麦克风）的 id：运行中插拔耳机等
        # 导致默认设备变化后自动跟随（见 _vad_loop_inner 看门狗三）
        self._default_id = None
        self._default_kind = None
        self._segmenter = None
        self._partial_base_s = 0.8  # 配置里的 vad.partial_interval_s（快照间隔下限）
        self._speech = False  # VAD 是否判定"正在说话"（设置页状态指示用，见 audio_status）
        self._stats = PipelineStats()  # 耗时/丢弃统计（每半分钟一条日志）

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
        self._vad_reset_pending.clear()
        # 清空队列里的残留：上次停止时可能留有旧语音，混入会造成识别错乱
        self._drain_queues()
        self._stats = PipelineStats()  # 统计窗口从本次启动重新算起
        threading.Thread(target=self._load_models_safe, daemon=True).start()
        audio_cfg = self.cfg.get("audio") or {}
        source = audio_cfg.get("source", "loopback")
        self._cap = AudioCapture(device=pick_device(audio_cfg.get("device_name"), source))
        self._cap.start()
        # 未指定具体设备时记录当前系统默认设备 id：运行中插拔耳机/换默认麦克风
        # 会导致默认设备变化，检测到后自动跟随（见看门狗三）
        self._default_id = None
        self._default_kind = None
        if not audio_cfg.get("device_name"):
            import soundcard as sc

            try:
                if source == "mic":
                    self._default_id = sc.default_microphone().id
                    self._default_kind = "mic"
                else:
                    self._default_id = sc.default_speaker().id
                    self._default_kind = "loopback"
            except Exception as e:
                log.warning("读取默认音频设备失败: %s", e)
        v = self.cfg.get("vad", {})
        self._partial_base_s = v.get("partial_interval_s", 0.8)
        segmenter = VadSegmenter(
            on_segment=self._enqueue_segment,
            on_partial=self._enqueue_partial,
            on_state=self._on_vad_state,
            threshold=v.get("threshold", 0.5),
            min_speech_ms=v.get("min_speech_ms", 250),
            min_silence_ms=v.get("min_silence_ms", 250),
            max_segment_s=v.get("max_segment_s", 10),
            partial_interval_s=self._partial_base_s,
        )
        self._segmenter = segmenter
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
        self._speech = False  # 停了就别再显示"检测到人声"

    def close(self):
        """程序退出前调用：停止流水线并释放翻译后端（连接池等）。"""
        self.stop()
        with self._model_lock:
            translator = self._translator
            self._translator = None
        if translator is not None:
            _close_quiet(translator)

    def _drain_queues(self):
        """丢弃待处理队列里的全部条目（启动、模型就绪等时间点上的过期语音）。"""
        for q in (self._seg_q, self._partial_q):
            while True:
                try:
                    q.get_nowait()
                except queue.Empty:
                    break

    def _put_latest(self, q, item, kind):
        """队列满时丢弃最旧的、放入最新的——宁可跳句也不让字幕越落越远。"""
        try:
            q.put_nowait(item)
        except queue.Full:
            try:
                q.get_nowait()
                self._stats.record_drop(kind)
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
            with self._model_lock:
                old = self._translator
                self._translator = None
            threading.Thread(target=self._rebuild_translator, args=(old,), daemon=True).start()

    def get_translator(self):
        """获取翻译链（OCR 等不经过音频流水线的功能也用）。未构建时现场构建。"""
        with self._model_lock:
            if self._translator is None:
                self._translator = build_chain(self.cfg["translator"])
            return self._translator

    def _rebuild_translator(self, old=None):
        try:
            translator = build_chain(self.cfg["translator"])
            with self._model_lock:
                self._translator = translator
            log.info("翻译后端已重建: %s", self.cfg["translator"].get("order"))
        except Exception as e:
            log.exception("翻译后端重建失败: %s", e)
            return
        if old is not None:
            # 旧链可能正被工作线程使用（在途请求）：延迟 10 秒再关，避免掐断正在进行的翻译
            timer = threading.Timer(10.0, _close_quiet, args=(old,))
            timer.daemon = True
            timer.start()

    def _load_models_safe(self):
        try:
            self._ensure_models()
            # 加载期间（首次要下载模型，可能几分钟）采集的音频已经过期：
            # 让 VAD 线程丢弃已累积的缓冲，避免就绪后补翻几分钟前的旧语音
            self._vad_reset_pending.set()
            # 加载完成后告知用户（首次下载模型可能需要几分钟，之前没有任何就绪提示）
            if self._cap is not None:
                log.info("模型已就绪")
                self.on_subtitle({"kind": "info", "zh": tr("模型已就绪，开始监听")})
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
        last_recover = 0.0
        while not self._stop.is_set() and self._gen == gen:
            if self._vad_reset_pending.is_set():
                # 模型刚加载完：丢弃加载期间累积的旧音频，只从新语音开始出字幕
                # （由 VAD 线程自己复位，避免跨线程改 segmenter 状态）
                self._vad_reset_pending.clear()
                segmenter.reset()
            # 每 2 秒做一轮健康检查（捕获线程存活 / 设备是否失效 / 默认设备是否变化）
            if time.time() - last_check > 2:
                last_check = time.time()
                # 看门狗一：捕获线程异常死亡（理论上内部会自恢复，这里兜底）→ 重建
                if not cap.is_alive():
                    log.warning("检测到音频捕获线程已停止，自动重启捕获")
                    cap = self._recover_capture(cap, segmenter)
                # 看门狗二：线程活着但设备已失效（如麦克风被拔掉）会一直重试同一个
                # 死设备——连续失败到阈值后按配置重新解析设备，插回即自动恢复
                elif cap.fail_streak >= 3 and time.time() - last_recover > 20:
                    last_recover = time.time()
                    log.warning("音频设备连续 %d 次捕获失败，尝试重新连接", cap.fail_streak)
                    cap = self._recover_capture(cap, segmenter)
                # 看门狗三：未指定设备名时跟随系统默认设备变化（插拔耳机/换默认麦克风）
                if self._default_id is not None:
                    try:
                        import soundcard as sc

                        current = (sc.default_microphone() if self._default_kind == "mic"
                                   else sc.default_speaker()).id
                        if current != self._default_id:
                            func = get_default_input if self._default_kind == "mic" else get_default_loopback
                            cap.stop()
                            cap = AudioCapture(device=func(), out_queue=cap.queue)
                            cap.start()
                            self._cap = cap
                            self._default_id = current
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

    def _on_vad_state(self, speaking):
        """VAD 状态回调（在 VAD 线程上跑）：只记一个标记，界面自己去读。
        别在这里做界面调用或耗时操作——会把 VAD 线程拖住。"""
        self._speech = bool(speaking)

    def audio_status(self):
        """给设置页音频电平/状态指示用的只读快照：(电平 0~1, 是否正在说话, 是否在监听)。

        电平由捕获线程自记、这里只读队列之外的值，**不消费音频队列**
        （消费会抢走主流水线的帧，规划 §5.2 红线）。"""
        cap = self._cap  # 看门狗可能换过捕获对象，每次都取当前的
        return (cap.last_level if cap is not None else 0.0,
                self._speech,
                self.running)

    def _fast_translate(self, text, lang):
        """快照翻译：走"跟手优先"的那条路（见 FallbackTranslator.translate_fast）。

        快照每 1~2 秒一次，所以按实测快慢另排一遍后端（有道 → 大模型 → MyMemory），
        而不是照 config 里的整句优先级；大模型这一次不记上下文、超时也更短。"""
        translator = self._translator
        fn = getattr(translator, "translate_fast", None) or translator.translate
        return fn(text, lang, self._target_lang())

    def _adapt_partial_interval(self, elapsed):
        """把实测耗时反馈给 VAD：识别/翻译慢时自动拉长快照间隔（规划 §2.2 c）。

        否则会生成一堆处理不完、只会被丢掉的快照，白白占用识别算力。
        每段语音的第一次快照不受影响（首字延迟优先），见 VadSegmenter.set_partial_interval。
        """
        seg = self._segmenter
        if seg is not None:
            interval = partial_interval_for(elapsed, self._partial_base_s)
            seg.set_partial_interval(interval)
            self._stats.set_interval(interval)

    def _recover_capture(self, cap, segmenter):
        """按配置重新解析设备并重建捕获线程（配置设备不存在时回退到默认设备）。
        返回可用的 AudioCapture（重建失败时原样返回旧对象）。"""
        audio_cfg = self.cfg.get("audio") or {}
        source = audio_cfg.get("source", "loopback")
        device = None
        fallback = False
        try:
            device = pick_device(audio_cfg.get("device_name"), source)
        except Exception as e:
            try:
                # 配置的设备当前不存在（如麦克风被拔掉）：先回退到系统默认设备，
                # 保证有声音可听；插回后下次重启监听/启动即恢复原选择
                device = get_default_input() if source == "mic" else get_default_loopback()
                fallback = True
            except Exception as e2:
                log.warning("重新解析音频设备失败: %s / %s", e, e2)
                return cap
        try:
            cap.stop()
            new_cap = AudioCapture(device=device, out_queue=cap.queue)
            new_cap.start()
        except Exception as e:
            log.warning("重建音频捕获失败: %s", e)
            return cap
        self._cap = new_cap
        segmenter.reset()
        name = getattr(device, "name", str(device))
        if fallback:
            log.warning("原音频设备暂不可用，已回退到默认设备: %s", name)
            self.on_subtitle({"kind": "info",
                              "zh": tr("原音频设备不可用，已切换到：{name}").format(name=name)})
        else:
            log.info("音频捕获已重新连接: %s", name)
        return new_cap

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
            self.on_subtitle({"kind": "info", "zh": tr("内部错误：识别线程异常退出，请停止后重新开始")})
        finally:
            log.info("识别工作线程已退出")

    def _worker_loop_inner(self, gen):
        # 等待模型加载完成（首次启动需要下载模型，可能要几分钟）
        self._model_ready.wait()
        if self._model_error is not None:
            self.on_subtitle({
                "kind": "final", "src": "",
                "zh": tr("模型加载失败：{err}。请检查网络后重新按热键重试").format(err=self._model_error),
            })
            return
        # 加载期间（首次要下载模型，可能几分钟）采集到的音频早已过期：
        # 清掉积压，否则就绪瞬间会集中补翻几分钟前的旧语音
        self._drain_queues()
        live = LiveCaptionState(lambda t, lang: self._fast_translate(t, lang))
        while not self._stop.is_set() and self._gen == gen:
            summary = self._stats.take_due(self._translator)
            if summary:
                log.info("%s", summary)
            # 优先处理定稿段落（要挪入历史行）；没有定稿再取最新快照
            try:
                item = self._seg_q.get_nowait()
            except queue.Empty:
                try:
                    item = self._partial_q.get(timeout=0.2)  # 超时轮询，保证 _stop 能即时生效
                except queue.Empty:
                    continue
            seg, is_partial = item
            t0 = time.time()
            try:
                tag = "实时快照" if is_partial else "语音片段"
                # 快照每 0.8 秒就来一次，按 INFO 记会把滚动日志刷满，降到 DEBUG
                log_fn = log.debug if is_partial else log.info
                log_fn("%s %.1fs，开始识别", tag, len(seg) / 16000)
                text, lang = self._transcriber.transcribe(
                    seg, language=self._source_lock(),
                    # 识别提示词 = 用户填的提示词 + 术语表原文词条（见 glossary.recognition_prompt）
                    prompt=glossary.recognition_prompt(self.cfg),
                )
                asr_s = time.time() - t0
                if not text:
                    # 识别没出字（静音/音乐误触发）：只记识别耗时，别把它算进处理条数
                    self._stats.record(asr_s=asr_s, item_s=asr_s)
                    continue
                self._stats.record(asr_s=asr_s)
                if is_partial:
                    # 快照：走 LocalAgreement，定稿区稳定、尾部滚动
                    payload = live.update(text, lang)
                    self.on_subtitle(payload)
                    log.debug("识别 [%s]（实时）: %s", lang, text)
                    # 处理一次要多久，决定下一次快照隔多久（后端慢就别催）
                    elapsed = time.time() - t0
                    self._stats.record(item_s=elapsed)
                    self._adapt_partial_interval(elapsed)
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
                        "zh": zh if zh else tr("…翻译服务暂时不可用…"),
                    })
                    self._stats.record(item_s=time.time() - t0)
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
        # 界面语言须在创建任何窗口前生效（托盘/设置页的 tr() 在构建时取值）
        set_language((self.cfg.get("ui") or {}).get("language", "zh"))
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
        # 模型下载进度回调（whisper / SenseVoice / NLLB 共用，规划 §3）
        model_download.set_reporter(self._model_reporter)

        self.tray = TrayIcon(on_toggle=self.toggle, on_quit=self.quit,
                             on_settings=self.open_settings, on_ocr=self.start_ocr_snip)
        self.tray.set_hotkey(self.cfg.get("hotkey", "alt+t"))
        self.tray.set_ocr_hotkey(self.cfg.get("hotkey_ocr", "ctrl+alt+r"))
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
                app=self.app, hotkey=self.cfg.get("hotkey_ocr", "ctrl+alt+r"),
                on_toggle=self.start_ocr_snip, hotkey_id=0xB002,
            )
            self.ocr_hotkeys.start()
        except Exception as e:
            log.warning("截图翻译热键注册失败: %s", e)
        self._snip = None
        self._ocr_notices_shown = set()  # 截图翻译的同类提示本次运行只弹一次

        hotkey = self.cfg.get("hotkey", "alt+t")
        tip = (tr("按 {hk} 开始监听，右键托盘打开设置").format(hk=hotkey) if self.hotkeys
               else tr("热键 {hk} 被占用（是否有另一个实例在运行？），可右键托盘操作").format(hk=hotkey))
        self.tray.showMessage(
            tr("实时翻译字幕"), tip,
            QSystemTrayIcon.Information, 3000,
        )

        self._start_instance_server()

        # 启动后静默检查一次更新：有新版本时弹托盘通知，点击通知打开设置页下载
        self._latest_update = None
        self.tray.messageClicked.connect(lambda *_: self.open_settings())
        QTimer.singleShot(5000, lambda: self._check_update(auto=True))
        # 老用户（≤1.3.9 只会拿到 CPU 小包）里有 N 卡的，提示一次去换 CUDA 完整版
        QTimer.singleShot(9000, self._maybe_suggest_flavor_switch)

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

    def _model_reporter(self, stage, label, done, total):
        """模型下载/加载进度（后台线程调用）→ 字幕条 + 设置页（规划 §3）。

        三段状态：下载中（x/y MB，z%）→ 加载中 → 就绪。名称是中文标签，在这里翻译。
        """
        name = tr(label)
        if stage == "download":
            if total:
                text = tr("正在下载{name}：{done:.0f}/{total:.0f} MB（{pct:.0f}%）").format(
                    name=name, done=done / 1048576, total=total / 1048576,
                    pct=min(100.0, done * 100 / total),
                )
            else:
                text = tr("正在下载{name}：{done:.0f} MB").format(name=name, done=done / 1048576)
        elif stage == "load":
            text = tr("正在加载{name}…").format(name=name)
        else:
            text = tr("{name}已就绪").format(name=name)
        self._emit_subtitle({"kind": "model_status", "text": text})

    def _on_subtitle(self, payload):
        if payload.get("kind") == "model_status":
            # 模型下载/加载进度：字幕条和设置页同时显示（首次使用最需要看见的一句话）
            self.window.update_text("", payload["text"])
            if self.settings_window is not None:
                self.settings_window.set_model_status(payload["text"])
        elif payload.get("kind") == "info":
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
        # 先抓取屏幕再盖选区层：选区画面与最终裁剪用同一张冻结图，
        # 避免选区层未消失就截图导致的偶发"未识别到文字"
        screen = QApplication.primaryScreen()
        pix = screen.grabWindow(0)
        self._snip = SnipOverlay(pix)
        self._snip.region_selected.connect(self._on_ocr_region)
        self._snip.cancelled.connect(lambda: log.info("截图翻译已取消"))
        self._snip.show()

    def _on_ocr_region(self, rect):
        from app.ocr_tool import crop_frozen, grab_region

        pix = self._snip._bg if self._snip is not None else None
        path = crop_frozen(pix, rect)
        if path is None:  # 冻结图不可用时回退到直接截屏（选区层已隐藏）
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
        from app.ocr_tool import (LANG_NAMES, clean_cjk_spacing, ocr_image,
                                  ocr_image_multi, pack_missing, pick_ocr_language)

        try:
            notice, notice_once = "", ""
            if src_lang == "auto":
                # 自动检测：系统默认引擎 + 已装的中/日/韩/俄引擎各识别一遍再挑
                # （中文引擎读日语会把假名认成形近汉字："こんにちは"→"乙 、今 日 00"）
                text, det_lang = ocr_image_multi(path)
                if pack_missing("ja"):
                    # 没装日语引擎就认不出日语（中文引擎读日语时假名数为 0，判据够不着），
                    # 所以只能按"装了才有得看"提示一次；是否真弹由主线程查重后决定
                    notice = tr(
                        "系统没有安装日语 OCR 语言包，日语截图会被认成形近汉字。"
                        "装上后即可自动识别日语：Windows 设置 → 时间和语言 → 语言和区域 → "
                        "添加语言 → 日语（勾选“语言包/OCR”）。"
                    )
                    notice_once = "ocr_ja_pack"
            else:
                lang_tag = pick_ocr_language(src_lang)
                if lang_tag is None:
                    notice = tr(
                        "未安装{lang}的 OCR 语言包，本次用系统默认语言识别；"
                        "可在 Windows 设置 → 时间和语言 → 语言和区域 中添加。"
                    ).format(lang=tr(LANG_NAMES.get(src_lang, src_lang)))
                text = ocr_image(path, lang_tag)
                det_lang = src_lang
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            if not lines:
                self.bridge.ocr_result.emit({"src": "", "zh": "", "anchor": rect,
                                             "notice": notice, "notice_once": notice_once})
                return
            # 中日文按字符书写，多行直接拼接；空格分词语言用空格连接
            sep = "" if (det_lang or "") in ("zh", "ja") else " "
            src = clean_cjk_spacing(sep.join(lines))
            zh = None
            if not re.search(r"[\w぀-ヿ一-鿿]", src, re.UNICODE):
                # 纯符号/数字/噪点，没有可翻译的文字，直接显示原文
                log.info("OCR [%s→%s]: %s（无有效文字，跳过翻译）",
                         src_lang, det_lang or "未判定", src)
                self.bridge.ocr_result.emit({"src": src, "zh": src, "anchor": rect,
                                             "notice": notice, "notice_once": notice_once})
                return
            try:
                # 判定出的语言要显式传下去：MyMemory/NLLB 收到 None 会按英语翻
                zh = self.pipeline.get_translator().translate(src, det_lang, target)
            except Exception as e:
                log.warning("截图翻译失败: %s", e)
            log.info("OCR [%s→%s]: %s → %s", src_lang, det_lang or "未判定", src, zh)
            self.bridge.ocr_result.emit({"src": src, "zh": zh, "anchor": rect,
                                         "notice": notice, "notice_once": notice_once})
        except Exception as e:
            log.exception("OCR 失败: %s", e)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def _show_ocr_notice(self, payload):
        """截图翻译的提示（语言包缺失等）。

        由 _ocr_worker（工作线程）随结果带过来、在主线程弹出：Qt 托盘不能跨线程碰。
        notice_once 的提示只弹一次（状态记在 update_state.json，见 app/updater.py）；
        其余同类提示本次运行只弹一次，避免连按热键被刷屏。
        """
        notice = payload.get("notice")
        if not notice:
            return
        key = payload.get("notice_once")
        if key:
            from app import updater

            if not updater.prompt_due(key):
                return
            updater.mark_prompted(key)
        elif notice in self._ocr_notices_shown:
            return
        self._ocr_notices_shown.add(notice)
        self.tray.showMessage(tr("实时翻译字幕"), notice, QSystemTrayIcon.Warning, 8000)

    def _show_ocr_result(self, payload):
        from app.ocr_tool import OcrResultPopup

        self._show_ocr_notice(payload)
        if not payload.get("src"):
            self.tray.showMessage(
                tr("实时翻译字幕"), tr("截图区域未识别到文字"),
                QSystemTrayIcon.Information, 3000,
            )
            return
        zh = payload.get("zh") or tr("…翻译服务暂时不可用…")
        # 弹窗颜色跟随字幕颜色设置（ocr 段可单独覆盖）
        ocr_cfg = dict(self.cfg.get("ocr") or {})
        sub_cfg = self.cfg.get("subtitle") or {}
        ocr_cfg.setdefault("zh_color", sub_cfg.get("zh_color", "#FFE34D"))
        ocr_cfg.setdefault("src_color", sub_cfg.get("src_color", "#FFFFFF"))
        popup = OcrResultPopup(payload["src"], zh, payload["anchor"], ocr_cfg)
        old = getattr(self, "_ocr_popup", None)
        if old is not None:
            # duration_ms=0 的旧弹窗不会自动关闭；显示新弹窗前先收掉，避免叠一层
            old.close()
        self._ocr_popup = popup
        popup.show()

    def _maybe_suggest_flavor_switch(self):
        """装了 CPU 精简版、机器却有 N 卡、配置里又要用 GPU 时，提示一次换包。

        只会提示一次（记在 update_state.json）。不在这里自动下载 700 MB：点“去切换”
        只打开设置页，真正的下载在设置页还会再确认一次。"""
        from app import flavor as flavor_mod
        from app import updater

        if flavor_mod.switch_suggestion() != flavor_mod.CUDA:
            return
        if (self.cfg.get("whisper") or {}).get("device") != "cuda":
            return  # 用户本来就在用 CPU 引擎（如极速），不打扰
        if not updater.flavor_prompt_due():
            return
        updater.mark_flavor_prompted()

        box = QMessageBox()
        box.setWindowTitle(tr("实时翻译字幕"))
        box.setIcon(QMessageBox.Information)
        box.setText(tr("检测到 NVIDIA 显卡，但当前安装的是 CPU 精简版"))
        box.setInformativeText(tr(
            "精简版不含 CUDA 运行库，识别已自动改用 CPU（比 GPU 慢不少）。\n"
            "可以换成 CUDA 完整版（约 640 MB，软件内下载）：点下面的按钮，"
            "在设置页“检查更新”处点“切换到 CUDA 版”。"
        ))
        go = box.addButton(tr("去设置页切换"), QMessageBox.AcceptRole)
        box.addButton(tr("以后再说"), QMessageBox.RejectRole)
        box.exec_()
        log.info("已提示一次可切换到 CUDA 完整版")
        if box.clickedButton() is go:
            self.open_settings()

    def _check_update(self, auto=False):
        """后台线程查询 GitHub Releases，结果经 bridge 回主线程显示。auto=True 为启动时的静默检查。"""
        from app import updater

        if auto and not updater.auto_check_due():
            # 节流：频繁重启软件时不再每次都请求 GitHub（匿名限流 60 次/小时）；
            # 手动点“检查更新”不受此限制
            log.info("启动更新检查节流中（%.0f 小时内已检查过），跳过",
                     updater.AUTO_CHECK_INTERVAL_S / 3600)
            return

        def run():
            # 按当前安装的包型取更新包（CPU 小包 / CUDA 完整包），不按硬件猜
            result = updater.check_update(
                cfg_device=(self.cfg.get("whisper") or {}).get("device", "")
            )
            result["auto"] = auto
            if result.get("reachable"):
                updater.mark_auto_checked()
            log.info("检查更新: %s", result)
            self.bridge.update_result.emit(result)

        threading.Thread(target=run, daemon=True).start()

    def _show_update_result(self, result):
        auto = result.pop("auto", False)
        if result.get("has_update"):
            self._latest_update = result
            if auto:
                self.tray.showMessage(
                    tr("实时翻译字幕"),
                    tr("发现新版本 {latest}，点击此通知打开设置页下载更新").format(latest=result["latest"]),
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
                None, tr("开发模式"),
                tr("当前运行的是源码版，无法自动替换更新。\n"
                   "新版本文件已下载到：\n{path}\n\n"
                   "如果你平时用的是安装包版本，请关闭本程序后改用桌面快捷方式启动，"
                   "再执行一次「检查更新 → 软件内下载更新」。").format(path=new_app_dir),
            )
            return
        import subprocess
        import tempfile

        from app import updater

        pid = os.getpid()
        target = os.path.dirname(sys.executable)
        exe = sys.executable
        staging_root = os.path.dirname(new_app_dir)
        # 下载的 zip 与解压目录同名（去 _extract 加 .zip），更新完成后一并清理
        zip_path = staging_root[:-len("_extract")] + ".zip" if staging_root.endswith("_extract") else ""
        # robocopy /E 只覆盖、不删多余文件：先算出"旧包有、新包没有"的清单
        # （换包型时清理 CUDA 运行库等；用户数据不进清单，永远不动）
        try:
            prune_files, prune_dirs = updater.compute_prune_list(new_app_dir, target)
        except Exception:
            log.warning("计算待清理文件失败，本次只做覆盖安装", exc_info=True)
            prune_files, prune_dirs = [], []
        log.info("本次更新待清理旧文件 %d 个、空目录 %d 个", len(prune_files), len(prune_dirs))
        tmp = tempfile.gettempdir()
        prune_list = os.path.join(tmp, "rts_prune_files.txt")
        prune_dir_list = os.path.join(tmp, "rts_prune_dirs.txt")
        for path, items in ((prune_list, prune_files), (prune_dir_list, prune_dirs)):
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(items))
        script = f"""
$ErrorActionPreference = "SilentlyContinue"
while (Get-Process -Id {pid}) {{ Start-Sleep -Milliseconds 500 }}
Start-Sleep -Seconds 1
if (Test-Path -LiteralPath "{prune_list}") {{
  Get-Content -LiteralPath "{prune_list}" -Encoding UTF8 | ForEach-Object {{
    if ($_ -and (Test-Path -LiteralPath $_)) {{ Remove-Item -LiteralPath $_ -Force }}
  }}
}}
robocopy "{new_app_dir}" "{target}" /E /IS /XF config.yaml app.log app.log.1 app.log.2 /XD models /NFL /NDL /NJH /NJS /R:2 /W:2 | Out-Null
if (Test-Path -LiteralPath "{prune_dir_list}") {{
  Get-Content -LiteralPath "{prune_dir_list}" -Encoding UTF8 | ForEach-Object {{
    if ($_ -and (Test-Path -LiteralPath $_)) {{ Remove-Item -LiteralPath $_ -Force }}
  }}
}}
Remove-Item -Force "{prune_list}"
Remove-Item -Force "{prune_dir_list}"
Start-Process "{exe}"
Remove-Item -Recurse -Force "{staging_root}"
Remove-Item -Force "{zip_path}"
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
        """运行时切换全局热键。必须先注销旧的再注册新的：同线程同 id 重复注册会
        “替换”旧注册，若先注册新的再停旧的，旧的 stop() 会把刚注册的新热键一起注销，
        导致换绑后热键静默失效（真实踩过的坑）。失败时回退恢复旧热键。"""
        if old_mgr is not None:
            old_mgr.stop()
        try:
            mgr = HotkeyManager(
                app=self.app, hotkey=hotkey, on_toggle=on_trigger, hotkey_id=hotkey_id
            )
            mgr.start()
        except Exception as e:
            log.warning("新热键 %s 注册失败: %s", hotkey, e)
            if old_mgr is not None:
                try:
                    old_mgr.start()
                except Exception:
                    log.warning("旧热键恢复失败", exc_info=True)
            return None
        log.info("全局热键已切换: %s", hotkey)
        return mgr

    def _live_preview(self, subtitle_cfg):
        """设置页外观改动：立即应用到字幕窗并显示预览（不写配置文件）。"""
        self.window.apply_config(subtitle_cfg)
        if self.settings_window is not None and self.settings_window.isVisible():
            self.window.update_text(
                "Live preview of the subtitle style.", tr("实时预览：样式改动即时生效")
            )

    def get_history(self):
        return list(self.history)

    def clear_history(self):
        self.history.clear()
        log.info("字幕记录已清空")

    def open_settings(self):
        if self.settings_window is None:
            from app.settings_window import SettingsWindow

            self.settings_window = SettingsWindow(
                self.cfg,
                history_provider=self.get_history,
                status_provider=self.pipeline.audio_status,  # 音频电平 / VAD 状态指示
            )
            self.settings_window.request_toggle.connect(self.toggle)
            self.settings_window.request_clear_history.connect(self.clear_history)
            self.settings_window.request_apply.connect(self.apply_config)
            self.settings_window.request_preview.connect(
                lambda: self.window.update_text(
                    "This is a preview of the subtitle style.", tr("这是字幕样式预览。")
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
            ("hotkey_ocr", "ocr_hotkeys", "ctrl+alt+r", self.start_ocr_snip, "btn_hotkey_ocr", 0xB002),
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
                    None, tr("热键注册失败"),
                    tr("热键 {hk} 注册失败（可能被其他程序占用），已保留原热键 {old}。").format(
                        hk=new_hotkey, old=old_hotkey
                    ),
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
            tr("实时翻译字幕"), tr("配置已保存并应用"),
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
                if not self.pipeline.models_ready:
                    # 模型未就绪时先给用户明确反馈（首次运行要下载约 460MB 识别模型），
                    # 随后 Pipeline 会持续上报"下载中 x/y MB → 加载中 → 就绪"的实时进度。
                    # 注意要在 start() 之前设：加载线程一起来就会开始上报，晚了会把进度顶掉
                    self.window.update_text(
                        "", tr("正在加载模型…（首次运行需下载识别模型约 460MB，请保持网络畅通）")
                    )
                self.pipeline.start()
                self.tray.set_running(True)
                if not self.pipeline.models_ready:
                    log.info("已开始监听，模型加载中（首次需下载约 460MB）")
                else:
                    log.info("已开始监听")
            if self.settings_window is not None:
                self.settings_window.set_running(self.pipeline.running)
        except Exception as e:
            log.exception("切换出错")
            QMessageBox.critical(None, tr("错误"), str(e))

    def quit(self):
        self.pipeline.close()
        if self.hotkeys is not None:
            self.hotkeys.stop()
        if self.ocr_hotkeys is not None:
            self.ocr_hotkeys.stop()
        self.app.quit()

    def run(self):
        sys.exit(self.app.exec_())


if __name__ == "__main__":
    MainApp().run()
