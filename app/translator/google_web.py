"""免费在线 Google 翻译（无需 API key），默认后端。"""

from .base import Translator

# 统一语言码 → Google 目标语言码
GOOGLE_TARGET = {"zh": "zh-CN", "en": "en", "ja": "ja", "ko": "ko", "ru": "ru"}


class GoogleWebTranslator(Translator):
    name = "google_web"

    def __init__(self):
        self._cache = {}  # 目标语言码 → GoogleTranslator 实例

    def translate(self, text, src_lang, target="zh"):
        code = GOOGLE_TARGET.get(target, "zh-CN")
        translator = self._cache.get(code)
        if translator is None:
            from deep_translator import GoogleTranslator

            translator = GoogleTranslator(source="auto", target=code)
            self._cache[code] = translator
        return translator.translate(text)
