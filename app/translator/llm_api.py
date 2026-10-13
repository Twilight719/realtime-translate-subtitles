"""OpenAI 兼容大模型 API 翻译（DeepSeek / 豆包 / GPT 等，在 config.yaml 填 key 即用）。

支持术语表（自定义词典）与上下文（上一句原文），游戏口语翻译质量最好。
开启 stream 后按 SSE 流式接收，译文逐字上屏，观感更接近同传。
"""

import json

import requests

from .base import Translator
from .glossary import rules_text

# 统一语言码 → 提示词中的语言名
TARGET_NAMES = {"zh": "简体中文", "en": "英语", "ja": "日语", "ko": "韩语", "ru": "俄语"}


def _system_prompt(target, rules=""):
    """rules 为术语表片段（见 glossary.rules_text）；没有术语表时与不带术语表逐字相同。"""
    return (
        f"你是游戏语音实时翻译器。把用户给的外语句子翻译成自然、口语化的{TARGET_NAMES.get(target, '简体中文')}。"
        "只输出译文，不要解释、不要引号、不要复述原文。"
        "保留游戏术语的惯用译法（如 gank、push、ultimate 等按目标语言玩家社区的惯用说法）。"
        + rules
    )


class LlmApiTranslator(Translator):
    name = "llm_api"
    supports_stream = True  # 声明支持流式：FallbackTranslator 会传入 on_delta 回调
    # 快照链里排在有道之后：大模型每次几百毫秒，比 MyMemory 还快、质量好得多，
    # 但有道只要 0.08 秒且免费，所以还是让有道先扛，它被限流时再顶上来
    partial_rank = 10
    # 快照用的超时：比整句短得多。快照卡住会挡住下一次识别（识别和翻译同一条线程），
    # 宁可放弃这一次快照、退回 MyMemory，也不能让整条流水线跟着等
    PARTIAL_TIMEOUT_S = 3.0

    def __init__(self, base_url, api_key, model, context_size=1, timeout=8, stream=True,
                 glossary=None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.context_size = context_size
        # 术语表只在构建时解析一次（每句话都要拼 system prompt，别每次都解析一遍）
        self.glossary_rules = rules_text(glossary)
        # 带上下文时同一句在不同上下文里可能译得不同 → 不参与结果缓存（见 base.Translator）
        self.context_sensitive = bool(context_size)
        self.timeout = timeout
        self.stream = stream
        self._history = []  # [(原文, 译文), ...]
        self._ctx_key = None  # 上一次翻译的语言组合，变化时清空上下文
        # 复用长连接：免去每次请求的 TCP+TLS 握手，每次省 0.2~0.5 秒
        self._session = requests.Session()

    def _messages(self, text, target):
        messages = [{"role": "system", "content": _system_prompt(target, self.glossary_rules)}]
        keep = max(0, int(self.context_size or 0))
        for src, tgt in (self._history[-keep:] if keep else []):
            messages.append({"role": "user", "content": src})
            messages.append({"role": "assistant", "content": tgt})
        messages.append({"role": "user", "content": text})
        return messages

    def _record_context(self, text, result, src_lang, target):
        """记录本轮翻译并裁剪上下文。源/目标语言变化时先清空：
        旧语言的对话记录喂给模型会干扰新语言的译文。"""
        ctx_key = (src_lang or None, target)
        if self._ctx_key is not None and ctx_key != self._ctx_key:
            self._history.clear()
        self._ctx_key = ctx_key
        self._history.append((text, result))
        keep = max(0, int(self.context_size or 0))
        if keep:
            del self._history[:-keep]
        else:
            self._history.clear()

    def translate(self, text, src_lang, target="zh", on_delta=None):
        """on_delta(累计译文) 不为 None 且开启 stream 时逐段上屏，否则一次性返回。"""
        result = self._request(text, target, on_delta, self.timeout)
        self._record_context(text, result, src_lang, target)
        return result

    def translate_partial(self, text, src_lang, target="zh"):
        """快照用：不记上下文、用更短的超时（见 PARTIAL_TIMEOUT_S 与 base.Translator）。"""
        return self._request(text, target, None, self.PARTIAL_TIMEOUT_S)

    def _request(self, text, target, on_delta, timeout):
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
                                      timeout=timeout, stream=True)
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
            return acc.strip()
        resp = self._session.post(url, headers=headers, json=body, timeout=timeout)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()

    def close(self):
        self._session.close()
