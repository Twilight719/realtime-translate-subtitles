"""LocalAgreement 风格的实时字幕状态机。

借鉴 whisper_streaming：每次快照识别整段缓冲，只有与上一次识别结果
一致的前缀才“定稿”——定稿部分永远不再变（显示稳定、只翻译一次），
尾部未确认部分允许滚动修订。段落结束（VAD 切段）时整体重置。
"""

import os.path


class LiveCaptionState:
    def __init__(self, translate):
        """translate: fn(text, src_lang) -> 中文"""
        self._translate = translate
        self.reset()

    def reset(self):
        self.prev_text = ""
        self.confirmed_src = ""
        self.confirmed_zh = ""
        self._last_tail_src = None  # 尾部缓存：快照间隔内尾部往往没变，避免重复请求在线翻译（会触发限流）
        self._last_tail_zh = ""

    @staticmethod
    def _common_prefix(a, b, spaced):
        cp = os.path.commonprefix([a, b])
        if spaced:
            # 空格分词语言（英/韩等）：只确认到完整词边界，避免确认半个词
            idx = cp.rfind(" ")
            return cp[: idx + 1] if idx >= 0 else ""
        # 无空格语言（日/中等）：末尾两个字最不稳定，不确认
        return cp[:-2] if len(cp) > 2 else ""

    def _safe_translate(self, text, lang):
        try:
            return self._translate(text, lang)
        except Exception:
            return "…"

    def update(self, text, lang):
        """输入本次快照识别的完整原文，返回上屏所需的四个部分。"""
        spaced = " " in text
        cp = self._common_prefix(self.prev_text, text, spaced)

        # 确认区只增不减
        if len(cp) > len(self.confirmed_src):
            newly = cp[len(self.confirmed_src):].strip()
            if newly:
                zh = self._safe_translate(newly, lang)
                self.confirmed_zh += zh + (" " if spaced else "")
            self.confirmed_src = cp

        tail_src = text[len(self.confirmed_src):].strip()
        if tail_src:
            if tail_src == self._last_tail_src:
                tail_zh = self._last_tail_zh
            else:
                tail_zh = self._safe_translate(tail_src, lang)
                self._last_tail_src, self._last_tail_zh = tail_src, tail_zh
        else:
            tail_zh = ""
            self._last_tail_src = None
        self.prev_text = text

        return {
            "kind": "live",
            "src_stable": self.confirmed_src.strip(),
            "src_tail": tail_src,
            "zh_stable": self.confirmed_zh.strip(),
            "zh_tail": tail_zh,
        }
