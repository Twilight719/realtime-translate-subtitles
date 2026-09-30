"""本地 NLLB-200 蒸馏版 int8（CTranslate2），离线后备后端。

模型（约 600MB）在第一次真正用到 NLLB 翻译时才下载/加载，
避免启动时就拖慢首次运行。模型存到程序目录 models/ 下。
"""

import logging
import os

from ..paths import base_dir
from .base import Translator

log = logging.getLogger("subtitle.translator.nllb")

MODEL_ID = "JustFrederik/nllb-200-distilled-600M-ct2-int8"
MODEL_DIR = os.path.join(base_dir(), "models", "nllb-600m-int8")

# whisper 语言码 → NLLB 语言码（常用语种，未列出的走 flores-200 同构规则兜底）
WHISPER_TO_NLLB = {
    "en": "eng_Latn", "ja": "jpn_Jpan", "ko": "kor_Hang", "zh": "zho_Hans",
    "ru": "rus_Cyrl", "fr": "fra_Latn", "de": "deu_Latn", "es": "spa_Latn",
    "pt": "por_Latn", "it": "ita_Latn", "ar": "arb_Arab", "th": "tha_Thai",
    "vi": "vie_Latn", "id": "ind_Latn", "uk": "ukr_Cyrl", "tr": "tur_Latn",
}


def _ensure_model(model_dir=MODEL_DIR):
    if not os.path.exists(os.path.join(model_dir, "model.bin")):
        import time

        from huggingface_hub import snapshot_download

        log.info("首次使用离线翻译，需下载 NLLB 模型（约 600MB），请保持网络畅通...")
        try:
            snapshot_download(MODEL_ID, local_dir=model_dir)
        except Exception:
            # 镜像偶发失败：记完整堆栈，5 秒后自动重试一次；再失败交给上层熔断
            log.exception("NLLB 模型下载失败，5 秒后重试一次")
            time.sleep(5)
            snapshot_download(MODEL_ID, local_dir=model_dir)
    return model_dir


class NllbTranslator(Translator):
    name = "nllb"

    def __init__(self, device="cpu"):
        self.device = device
        self._translator = None
        self._sp = None

    def _load(self):
        if self._translator is not None:
            return
        import ctranslate2
        import sentencepiece

        model_dir = _ensure_model()
        self._translator = ctranslate2.Translator(
            model_dir, device=self.device,
            compute_type="int8" if self.device == "cpu" else "float16",
        )
        # sentencepiece 在中文路径下 LoadFromFile 会失败，改为读字节加载
        with open(os.path.join(model_dir, "sentencepiece.bpe.model"), "rb") as f:
            self._sp = sentencepiece.SentencePieceProcessor(model_proto=f.read())
        log.info("NLLB 离线翻译模型已加载")

    def translate(self, text, src_lang, target="zh"):
        self._load()
        src = WHISPER_TO_NLLB.get(src_lang or "", "eng_Latn")
        tgt = WHISPER_TO_NLLB.get(target, "zho_Hans")
        tokens = [src] + self._sp.encode(text, out_type=str) + ["</s>"]
        results = self._translator.translate_batch(
            [tokens], target_prefix=[[tgt]], beam_size=2, max_decoding_length=256
        )
        # hypotheses[0][0] 是目标语言标记，需跳过
        return self._sp.decode(results[0].hypotheses[0][1:]).strip()
