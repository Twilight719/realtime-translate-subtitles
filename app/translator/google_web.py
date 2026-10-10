"""免费在线 Google 翻译（无需 API key），备用后端。

直接自己抓 translate.google.com/m 的结果容器（带超时），不再走 deep_translator：
后者的请求层没有 timeout，网络不通（国内直连不通时就是这种）会长时间挂住。
"""

import html
import logging
import re

import requests

from .base import Translator, TranslationTextError

log = logging.getLogger("subtitle.translator.google")

URL = "https://translate.google.com/m"

# 统一语言码 → Google 语言码（源/目标通用）
GOOGLE_LANG = {"zh": "zh-CN", "en": "en", "ja": "ja", "ko": "ko", "ru": "ru"}

MAX_CHARS = 5000  # Google 单次请求的字符上限

# 结果容器：<div class="result-container">…</div>（页面偶用 class="t0"）
_RESULT_RE = re.compile(r'class="(?:result-container|t0)"[^>]*>(.*?)</div>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")

# 不带浏览器 UA 容易被 Google 挡下
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


class GoogleWebTranslator(Translator):
    name = "google_web"

    def __init__(self, timeout=8):
        self.timeout = timeout
        self._session = requests.Session()

    def translate(self, text, src_lang, target="zh"):
        if len(text) > MAX_CHARS:
            raise TranslationTextError("文本超过 Google 上限 %d 字符" % MAX_CHARS)
        resp = self._session.get(
            URL,
            params={
                "tl": GOOGLE_LANG.get(target, "zh-CN"),
                # 已知源语言就明确传给 Google（与有道后端一致），不确定时用 auto
                "sl": GOOGLE_LANG.get(src_lang or "", "auto"),
                "q": text,
            },
            headers=_HEADERS,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        m = _RESULT_RE.search(resp.text)
        if not m:
            raise RuntimeError("Google 返回结构无法解析（可能被拦截或页面已改版）")
        result = html.unescape(_TAG_RE.sub("", m.group(1))).strip()
        if not result:
            raise RuntimeError("Google 返回空结果")
        return result

    def close(self):
        self._session.close()
