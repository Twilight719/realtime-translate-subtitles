"""有道翻译网页接口（无需 key，国内直连），默认在线后端。"""

import requests

from .base import Translator, TranslationTextError

URL = "https://aidemo.youdao.com/trans"

# 统一语言码 → 有道语言码（源/目标通用）
YOUDAO_LANG = {"zh": "zh-CHS", "en": "en", "ja": "ja", "ko": "ko", "ru": "ru"}

# 文本级错误码：该条文本无法翻译（语言不支持/超长等），不算后端故障
_TEXT_ERRORS = {"102", "103"}


class YoudaoWebTranslator(Translator):
    name = "youdao_web"

    def __init__(self, timeout=8):
        self.timeout = timeout
        self._session = requests.Session()

    def translate(self, text, src_lang, target="zh"):
        src = YOUDAO_LANG.get(src_lang, "auto") if src_lang else "auto"
        resp = self._session.post(
            URL,
            data={"q": text, "from": src, "to": YOUDAO_LANG.get(target, "zh-CHS")},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        if "translation" not in data:
            if str(data.get("errorCode")) in _TEXT_ERRORS:
                raise TranslationTextError(f"有道无法翻译该文本: {data}")
            raise RuntimeError(f"有道返回异常: {data}")
        return "".join(data["translation"]).strip()

    def close(self):
        self._session.close()
