"""MyMemory 免费翻译 API（无需 key），备用在线后端。

直接自己用 requests 发请求（带超时），不再走 deep_translator：
后者的请求层没有 timeout，网络卡住时会冻结唯一的识别工作线程。
"""

import logging

import requests

from .base import Translator, TranslationTextError

log = logging.getLogger("subtitle.translator.mymemory")

URL = "https://api.mymemory.translated.net/get"

# 统一语言码 → MyMemory 语言码
MM_TARGET = {"zh": "zh-CN", "en": "en-US", "ja": "ja-JP", "ko": "ko-KR", "ru": "ru-RU"}

MAX_CHARS = 500  # MyMemory 单次请求的字符上限

# 文本级错误：这条文本它翻不了，换下一个后端重试，但不冷却本后端
_TEXT_ERRORS = ("INVALID LANGUAGE PAIR", "PLEASE SELECT TWO DISTINCT", "NO QUERY SPECIFIED")


class MyMemoryTranslator(Translator):
    name = "mymemory"

    def __init__(self, timeout=10):
        self.timeout = timeout
        self._session = requests.Session()

    def translate(self, text, src_lang, target="zh"):
        # 超长文本先自己拦下来：既省一次必然失败的请求，也让回退链知道这是文本级错误
        if len(text) > MAX_CHARS:
            raise TranslationTextError("文本超过 MyMemory 上限 %d 字符" % MAX_CHARS)
        src = MM_TARGET.get(src_lang or "", "en-US")
        tgt = MM_TARGET.get(target, "zh-CN")
        resp = self._session.get(
            URL,
            params={"q": text, "langpair": f"{src}|{tgt}"},
            timeout=self.timeout,
        )
        if resp.status_code == 429:
            raise RuntimeError("MyMemory 触发限流（429）")
        resp.raise_for_status()
        data = resp.json()
        translated = str(((data.get("responseData") or {}).get("translatedText")) or "").strip()
        upper = translated.upper()
        if upper.startswith("MYMEMORY WARNING"):
            raise RuntimeError("MyMemory 免费额度已用尽: %s" % translated[:60])
        if any(m in upper for m in _TEXT_ERRORS):
            raise TranslationTextError("MyMemory 无法翻译该文本: %s" % translated[:60])
        status = data.get("responseStatus")
        if not translated or status not in (200, "200"):
            raise RuntimeError("MyMemory 返回异常: status=%s body=%s" % (status, str(data)[:120]))
        return translated

    def close(self):
        self._session.close()
