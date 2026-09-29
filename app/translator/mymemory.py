"""MyMemory 免费翻译 API（无需 key），备用在线后端。"""

from .base import Translator

# 统一语言码 → MyMemory 语言码
MM_TARGET = {"zh": "zh-CN", "en": "en-US", "ja": "ja-JP", "ko": "ko-KR", "ru": "ru-RU"}


class MyMemoryTranslator(Translator):
    name = "mymemory"

    def __init__(self, timeout=10):
        self.timeout = timeout

    def translate(self, text, src_lang, target="zh"):
        from deep_translator import MyMemoryTranslator as _MM

        # MyMemory 不支持 auto，须显式给源语言（whisper 已检测出语言码）
        translator = _MM(source=src_lang or "en", target=MM_TARGET.get(target, "zh-CN"))
        return translator.translate(text)
