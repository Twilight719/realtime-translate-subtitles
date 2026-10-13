"""翻译后端抽象接口。"""


class TranslationTextError(Exception):
    """该文本本身无法翻译（如后端不支持的语言/内容），属于文本级错误而非后端故障。

    回退链遇到此异常会换下一个后端重试，但不会让后端进入冷却。"""


class Translator:
    """所有翻译后端实现此接口。"""

    name = "base"
    # 译文是否依赖别的请求（如大模型带上一句做上下文）。为 True 的后端不参与
    # FallbackTranslator 的结果缓存：同一句原文在不同上下文里可能该译得不一样
    context_sensitive = False
    # 能不能用来翻"边说边出"的实时快照（声明 False 的后端只参与整句定稿）
    partial_ok = True
    # 快照链里的优先次序，小的排前面（见 FallbackTranslator.translate_fast）。
    # 只给"实测明显更快"的后端登记名次（有道 0.08s、Google、大模型）——它们要越过
    # 用户配置的顺序插到前面。没登记的一律 50，排序是稳定的，因此它们之间**保持
    # 用户配置的顺序**（比如默认顺序里的 NLLB 就仍排在 MyMemory 前面）
    partial_rank = 50

    def translate(self, text, src_lang, target="zh"):
        """text → target 语言。src_lang 为 whisper 语言码（如 'en'/'ja'），可为 None；
        target 为目标语言码（zh/en/ja/ko/ru）。
        失败时抛异常，由调用方回退到下一个后端。"""
        raise NotImplementedError

    def translate_partial(self, text, src_lang, target="zh"):
        """翻"边说边出"的快照（多半是半句话，几秒后就会被整句定稿覆盖）。

        默认与整句翻译同路；需要区别对待的后端在这里覆写——比如大模型不能把
        半句话记进上下文历史（会污染后面整句的译文），也不该按整句的超时去等。"""
        return self.translate(text, src_lang, target)

    def close(self):
        pass
