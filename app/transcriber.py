"""faster-whisper 语音识别：语音片段 → 原文文字（自动检测语言）。"""

import logging

import numpy as np
from faster_whisper import WhisperModel  # 顶层导入：避免多线程并发加载原生扩展导致段错误

log = logging.getLogger("subtitle")


class Transcriber:
    def __init__(self, model_size="small", device="cuda", compute_type="float16", beam_size=1):
        self.model = self._load_with_fallback(model_size, device, compute_type)
        self.beam_size = beam_size

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

    def transcribe(self, segment, language=None):
        """segment: float32 (N,) 16kHz → (原文, 语言码)；无有效语音返回 ("", None)。
        language 为 whisper 语言码（如 'en'/'ja'），None 表示自动检测。"""
        segments, info = self.model.transcribe(
            segment,
            language=language,  # None = 自动检测
            beam_size=self.beam_size,
            vad_filter=False,  # 上游已做过 VAD
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
        )
        text = "".join(s.text for s in segments).strip()
        if not text or info.language_probability < 0.5:
            return "", None
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
