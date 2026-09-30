"""OpenAI 兼容大模型 API 翻译（DeepSeek / 豆包 / GPT 等，在 config.yaml 填 key 即用）。

支持术语提示词与上下文（上一句原文），游戏口语翻译质量最好。
开启 stream 后按 SSE 流式接收，译文逐字上屏，观感更接近同传。
"""

import json

import requests

from .base import Translator

# 统一语言码 → 提示词中的语言名
TARGET_NAMES = {"zh": "简体中文", "en": "英语", "ja": "日语", "ko": "韩语", "ru": "俄语"}


def _system_prompt(target):
    return (
        f"你是游戏语音实时翻译器。把用户给的外语句子翻译成自然、口语化的{TARGET_NAMES.get(target, '简体中文')}。"
        "只输出译文，不要解释、不要引号、不要复述原文。"
        "保留游戏术语的惯用译法（如 gank、push、ultimate 等按目标语言玩家社区的惯用说法）。"
    )


class LlmApiTranslator(Translator):
    name = "llm_api"
    supports_stream = True  # 声明支持流式：FallbackTranslator 会传入 on_delta 回调

    def __init__(self, base_url, api_key, model, context_size=1, timeout=8, stream=True):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.context_size = context_size
        self.timeout = timeout
        self.stream = stream
        self._history = []  # [(原文, 译文), ...]
        # 复用长连接：免去每次请求的 TCP+TLS 握手，每次省 0.2~0.5 秒
        self._session = requests.Session()

    def _messages(self, text, target):
        messages = [{"role": "system", "content": _system_prompt(target)}]
        for src, tgt in self._history[-self.context_size:]:
            messages.append({"role": "user", "content": src})
            messages.append({"role": "assistant", "content": tgt})
        messages.append({"role": "user", "content": text})
        return messages

    def translate(self, text, src_lang, target="zh", on_delta=None):
        """on_delta(累计译文) 不为 None 且开启 stream 时逐段上屏，否则一次性返回。"""
        body = {
            "model": self.model,
            "messages": self._messages(text, target),
            "temperature": 0.3,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        url = f"{self.base_url}/chat/completions"

        if on_delta is not None and self.stream:
            body["stream"] = True
            resp = self._session.post(url, headers=headers, json=body,
                                      timeout=self.timeout, stream=True)
            try:
                resp.raise_for_status()
                acc = ""
                for line in resp.iter_lines(decode_unicode=True):
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    piece = (json.loads(data)["choices"][0].get("delta") or {}).get("content") or ""
                    if piece:
                        acc += piece
                        on_delta(acc)
            finally:
                resp.close()
            result = acc.strip()
        else:
            resp = self._session.post(url, headers=headers, json=body, timeout=self.timeout)
            resp.raise_for_status()
            result = resp.json()["choices"][0]["message"]["content"].strip()

        self._history.append((text, result))
        return result

    def close(self):
        self._session.close()
