"""faster-whisper 语音识别：语音片段 → 原文文字（自动检测语言）。"""

import logging
import zlib

import numpy as np
from faster_whisper import WhisperModel  # 顶层导入：避免多线程并发加载原生扩展导致段错误

from .model_download import ensure_whisper_model, report_stage

log = logging.getLogger("subtitle")

LABEL = "语音识别模型"  # 进度提示里的名字（界面层再翻译；与侧边栏"识别模型"区分开，避免撞 i18n 键）

# 单遍识别（temperature=0.0）在音乐、笑声、多人抢话上偶尔会"卡带"，把同一句复读十几遍
# ——实测一条 5.9 秒语音出过 600 字、21 遍 "I don't think there is one."，译文也跟着复读。
# 判据用 whisper 官方的压缩比：正常语音≈0.9，复读文本能到 3~13（gzip 压得动重复内容）。
DEGENERATE_RATIO = 2.4      # 超过这个压缩比 = 判定为复读，用 0.6 温度重跑一遍
RETRY_TEMPERATURE = 0.6     # 重跑温度：采样而不是贪心，是 whisper 跳出复读的标准手段

# 兜底折叠的阈值。人强调式重复一般 2~4 遍（"我不算进去。我不算进去。"），
# whisper 卡住是十几二十遍，隔着量级，所以取 5 遍不会误伤正常说话。
# 实测旁证：拿 TTS 把同一句话念 8 遍喂给模型，它自己只输出一遍（压缩比 0.82）——
# 语音里的真实重复本来就会被 whisper 折叠掉，所以文本里出现 5 遍以上连续重复
# 只可能是解码器卡带，不会是"用户真的说了 5 遍"。
_REPEAT_MIN_TIMES = 5
_REPEAT_MIN_PERIOD = 4       # 有空格的语言：至少这么多个词
_REPEAT_MIN_PERIOD_CJK = 4   # 无空格语言（中日韩）：至少这么多个字
_REPEAT_MAX_PERIOD = 24      # 周期再长就不像复读了，不去猜


def _compression_ratio(text):
    """gzip 压缩比，与 faster_whisper.transcribe.get_compression_ratio 同款算法。"""
    data = text.encode("utf-8")
    return len(data) / len(zlib.compress(data))


def collapse_repeats(text):
    """折叠"卡带"式重复，返回 (新文本, 折叠掉的遍数)；没重复时原样返回。

    重跑是正解（见 transcribe），这里是兜底：万一重跑也压不住，至少别把满屏
    重复的原文（连带译文）端给用户。只在同一段短语连续重复 ≥5 遍时才动手。"""
    if not text:
        return text, 0
    spaced = " " in text
    units = text.split() if spaced else list(text.replace(" ", ""))
    min_period = _REPEAT_MIN_PERIOD if spaced else _REPEAT_MIN_PERIOD_CJK
    kept, i, removed = [], 0, 0
    n = len(units)
    while i < n:
        best_period = best_times = 0
        for period in range(min_period, _REPEAT_MAX_PERIOD + 1):
            if i + period * _REPEAT_MIN_TIMES > n:
                break
            times = 1
            while (i + (times + 1) * period <= n
                   and units[i:i + period] == units[i + times * period:i + (times + 1) * period]):
                times += 1
            if times >= _REPEAT_MIN_TIMES and period * times > best_period * best_times:
                best_period, best_times = period, times
        if best_period:
            kept.extend(units[i:i + best_period])  # 保留一遍
            removed += best_times - 1
            i += best_period * best_times
        else:
            kept.append(units[i])
            i += 1
    if not removed:
        return text, 0
    return (" ".join(kept) if spaced else "".join(kept)), removed


class Transcriber:
    def __init__(self, model_size="small", device="cuda", compute_type="float16", beam_size=1):
        # 首次使用要下载约 460MB：先在带进度的情况下下好，再交给 WhisperModel 加载。
        # 拿到本地目录就直接用（它见到目录不会再去下载，缓存命中也不会重下）；
        # 拿不到（下载失败等）就照旧把档位名交给 WhisperModel，由它自己处理
        prepared = ensure_whisper_model(model_size, LABEL)
        report_stage("load", LABEL)
        self.model = self._load_with_fallback(prepared or model_size, device, compute_type)
        self.beam_size = beam_size
        self._warmup()
        report_stage("ready", LABEL)

    def _warmup(self):
        """加载后跑一遍静音识别：提前完成 CUDA 内核编译与自动调优，
        否则第一句真实语音要慢 1~2 秒。"""
        try:
            self.model.transcribe(
                np.zeros(16000 // 2, dtype=np.float32),
                beam_size=1, temperature=0.0,
            )
            log.info("识别模型预热完成")
        except Exception as e:
            log.warning("识别模型预热失败（不影响使用）: %s", e)

    @staticmethod
    def _load_with_fallback(model_size, device, compute_type):
        """按配置加载模型，失败时自动降级，而不是直接报"模型加载失败"。

        典型场景：配置 cuda+float16，但本次启动 GPU 后端不可用（驱动/显存/打包缺库），
        ctranslate2 会拒绝 float16 → 依次降级：同设备 int8 → cpu int8。
        """
        attempts = [(device, compute_type)]
        if compute_type == "float16":
            attempts.append((device, "int8"))
        if device == "cuda":
            attempts.append(("cpu", "int8"))
        last_err = None
        for dev, ctype in attempts:
            try:
                model = WhisperModel(model_size, device=dev, compute_type=ctype)
                if (dev, ctype) != (device, compute_type):
                    log.warning("识别模型按 %s/%s 加载失败，已自动降级为 %s/%s", device, compute_type, dev, ctype)
                return model
            except Exception as e:
                log.warning("识别模型加载失败（%s/%s）: %s", dev, ctype, e)
                last_err = e
        raise last_err

    def _decode(self, segment, language, prompt, temperature):
        """跑一遍识别，返回 (原文, info)。"""
        segments, info = self.model.transcribe(
            segment,
            language=language,  # None = 自动检测
            beam_size=self.beam_size,
            temperature=temperature,
            initial_prompt=prompt or None,
            vad_filter=False,  # 上游已做过 VAD
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
        )
        return "".join(s.text for s in segments).strip(), info

    def transcribe(self, segment, language=None, prompt=None):
        """segment: float32 (N,) 16kHz → (原文, 语言码)；无有效语音返回 ("", None)。
        language 为 whisper 语言码（如 'en'/'ja'），None 表示自动检测。
        prompt 为可选提示词（作品名/术语等），提升专有名词识别准确率。"""
        # 常规是单遍：默认的温度回退阶梯（0.0→1.0 共 8 级）在嘈杂音频上会连跑好几遍，
        # 延迟突刺越积越多。这里只在识别结果"卡带"（压缩比超阈值）时补跑一遍 0.6，
        # 最坏多花 0.05 秒（实测 9 秒音频 GPU），正常语音一分钱不多花。
        text, info = self._decode(segment, language, prompt, 0.0)
        if text:
            ratio = _compression_ratio(text)
            if ratio > DEGENERATE_RATIO:
                retry_text, retry_info = self._decode(segment, language, prompt, RETRY_TEMPERATURE)
                if retry_text and _compression_ratio(retry_text) <= DEGENERATE_RATIO:
                    log.warning("识别结果疑似复读（压缩比 %.1f），已用 %.1f 温度重跑一遍", ratio, RETRY_TEMPERATURE)
                    text, info = retry_text, retry_info
                else:
                    log.warning("识别结果疑似复读（压缩比 %.1f），重跑仍不理想，交给折叠兜底", ratio)
        if not text or info.language_probability < 0.5:
            return "", None
        text, folded = collapse_repeats(text)
        if folded:
            log.warning("识别原文连续重复 %d 遍，已折叠为一遍：%s", folded + 1, text[:60])
        return text, info.language


if __name__ == "__main__":
    # 自测：监听 15 秒，打印识别出的原文与语言
    import time

    from audio_capture import AudioCapture
    from vad import VadSegmenter

    tr = Transcriber()

    def on_segment(seg):
        text, lang = tr.transcribe(seg)
        if text:
            print(f"[{lang}] {text}")

    s = VadSegmenter(on_segment)
    cap = AudioCapture()
    cap.start()
    print("开始监听 15 秒，请播放外语语音...")
    try:
        end = time.time() + 15
        while time.time() < end:
            s.feed(cap.queue.get(timeout=1))
    finally:
        cap.stop()
