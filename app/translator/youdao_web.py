"""有道翻译网页接口（无需 key，国内直连），默认在线后端。"""

import requests

from .base import Translator

URL = "https://aidemo.youdao.com/trans"

# 统一语言码 → 有道目标语言码
YOUDAO_TARGET = {"zh": "zh-CHS", "en": "en", "ja": "ja", "ko": "ko", "ru": "ru"}


class YoudaoWebTranslator(Translator):
    name = "youdao_web"

    def __init__(self, timeout=8):
        self.timeout = timeout
        self._session = requests.Session()

    def translate(self, text, src_lang, target="zh"):
        resp = self._session.post(
            URL,
            data={"q": text, "from": "auto", "to": YOUDAO_TARGET.get(target, "zh-CHS")},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        if "translation" not in data:
            raise RuntimeError(f"有道返回异常: {data}")
        return "".join(data["translation"]).strip()

    def close(self):
        self._session.close()
