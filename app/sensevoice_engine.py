"""SenseVoice（sherpa-onnx）极速识别引擎。

CPU 上约 30 倍实时速度（7 秒语音约 0.25 秒出结果），加载仅约 1 秒，
支持 中/英/日/韩/粤 五种语言。模型为 int8 量化版（约 230MB，首次使用自动下载）。
与 app.transcriber.Transcriber 保持同一接口，可互换。
"""

import logging
import os
import re
import time

import numpy as np

from .paths import base_dir

log = logging.getLogger("subtitle")

MODEL_REPO = "csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
MODEL_DIR = os.path.join(base_dir(), "models", "sensevoice")
MODEL_FILES = ["model.int8.onnx", "tokens.txt"]

SUPPORTED_LANGS = {"zh", "en", "ja", "ko", "yue"}

# SenseVoice 输出可能带 <|ja|><|HAPPY|><|Speech|> 这类元信息标签，上屏前剥掉
_TAG_RE = re.compile(r"<\|[^|]*\|>")


class SenseVoiceTranscriber:
    """transcribe(segment, language, prompt) -> (text, lang)，与 Transcriber 同接口。"""

    def __init__(self, num_threads=2):
        self._ensure_model()
        import sherpa_onnx  # 延迟导入：用 whisper 引擎时不加载

        self.recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=os.path.join(MODEL_DIR, "model.int8.onnx"),
            tokens=os.path.join(MODEL_DIR, "tokens.txt"),
            num_threads=num_threads,
            use_itn=True,   # 数字/标点转书面形式
            language="auto",
            debug=False,
        )
        log.info("SenseVoice 引擎已加载（极速模式，CPU）")

    @staticmethod
    def _ensure_model():
        missing = [f for f in MODEL_FILES
                   if not os.path.exists(os.path.join(MODEL_DIR, f))]
        if not missing:
            return
        from huggingface_hub import hf_hub_download

        os.makedirs(MODEL_DIR, exist_ok=True)
        for fn in missing:
            for attempt in (1, 2):
                try:
                    log.info("下载 SenseVoice 模型文件 %s（共约 230MB，仅首次）", fn)
                    hf_hub_download(MODEL_REPO, fn, local_dir=MODEL_DIR)
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    log.warning("SenseVoice 模型下载失败，5 秒后重试", exc_info=True)
                    time.sleep(5)

    def transcribe(self, segment, language=None, prompt=None):
        """segment: float32 (N,) 16kHz → (原文, 语言码)；无有效语音返回 ("", None)。

        language 为语言码（zh/en/ja/ko/yue），None 或不支持的值 = 自动检测。
        prompt 参数仅为接口兼容——SenseVoice 不支持提示词，传入会被忽略。
        """
        if language and language not in SUPPORTED_LANGS:
            log.warning("SenseVoice 不支持锁定语言 %s（仅支持 中/英/日/韩/粤），改用自动检测", language)
            language = None
        # 静音/极弱信号直接丢弃：SenseVoice 对纯静音会幻觉出内容（如 "그."），
        # 而 whisper 有 no_speech 阈值兜底，这里用能量门替代
        if float(np.abs(segment).max()) < 0.01:
            return "", None
        stream = self.recognizer.create_stream()
        stream.accept_waveform(16000, segment)
        self.recognizer.decode_stream(stream)
        result = stream.result
        text = _TAG_RE.sub("", result.text).strip()
        lang = _TAG_RE.sub("", getattr(result, "lang", "") or "").strip() or None
        if not text:
            return "", None
        return text, lang
