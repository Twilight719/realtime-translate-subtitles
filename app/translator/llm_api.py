"""OpenAI 兼容大模型 API 翻译（DeepSeek / 豆包 / GPT 等，在 config.yaml 填 key 即用）。

支持术语提示词与上下文（上一句原文），游戏口语翻译质量最好。
"""

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

    def __init__(self, base_url, api_key, model, context_size=1, timeout=8):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.context_size = context_size
        self.timeout = timeout
        self._history = []  # [(原文, 译文), ...]

    def translate(self, text, src_lang, target="zh"):
        messages = [{"role": "system", "content": _system_prompt(target)}]
        for src, tgt in self._history[-self.context_size:]:
            messages.append({"role": "user", "content": src})
            messages.append({"role": "assistant", "content": tgt})
        messages.append({"role": "user", "content": text})

        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "messages": messages, "temperature": 0.3},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        result = resp.json()["choices"][0]["message"]["content"].strip()
        self._history.append((text, result))
        return result
