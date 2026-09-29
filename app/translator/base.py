"""翻译后端抽象接口。"""


class Translator:
    """所有翻译后端实现此接口。"""

    name = "base"

    def translate(self, text, src_lang, target="zh"):
        """text → target 语言。src_lang 为 whisper 语言码（如 'en'/'ja'），可为 None；
        target 为目标语言码（zh/en/ja/ko/ru）。
        失败时抛异常，由调用方回退到下一个后端。"""
        raise NotImplementedError

    def close(self):
        pass
