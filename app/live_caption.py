"""LocalAgreement 风格的实时字幕状态机。

借鉴 whisper_streaming：每次快照识别整段缓冲，只有与上一次识别结果
一致的前缀才“定稿”——定稿部分永远不再变（显示稳定、只翻译一次），
尾部未确认部分允许滚动修订。段落结束（VAD 切段）时整体重置。

v1.4.0 起定稿的粒度是**滚动区的译文**而不是识别出的每个碎片（规划 §2.2）：
识别出的新文字先留在滚动区跟着整段一起翻，等这段文字在两次识别之间
**整体**保持不变，才连同它的译文一起挪进定稿区。旧实现是“新确认的前缀
翻一次、尾部再翻一次”，同一段文字每次快照要被翻两遍（实测 7.2 秒语音
10 次在线请求、每个词至少翻两遍），既浪费又容易触发有道等后端限流。

配套节流（同属 §2.2）：滚动区没长出新内容、或新增太少且距上次请求太近时，
本次不请求——原文照常上屏（那是最新的），只是译文晚一拍，不会漏字。

尾部预留：最后 `TAIL_GRACE_CHARS` 个字最容易在下一次识别里被改写，既不翻译
也不定稿，等它退到安全位置再说；有空格的语言则只在完整词边界上定稿，
避免把半个词翻出来又改。
"""

import os
import time


class LiveCaptionState:
    # ---- 节流参数（调大更省请求，调小更跟手）----
    MIN_NEW_CHARS = 3       # 滚动区至少新增这么多字符才值得再请求一次
    MIN_INTERVAL_S = 1.0    # 距上次请求不足这么久、且新增不足上一行时跳过

    # ---- 定稿位置 ----
    TAIL_GRACE_CHARS = 2    # 尾部预留：最后 2 个字先不翻译也不定稿（无空格语言）
    MIN_REGION_CHARS = 4    # 短句（剩余不足这么多字）不预留尾部，直接整段翻
    MAX_PREVIEW_CHARS = 20  # 有空格的语言这么久等不到词边界就先给个预览，别停住

    def __init__(self, translate):
        """translate: fn(text, src_lang) -> 译文"""
        self._translate = translate
        self.reset()

    def reset(self):
        self.prev_text = ""
        self.committed_src = ""   # 定稿区原文（一定是当前原文的前缀）
        self.committed_zh = ""    # 定稿区译文（只增不改）
        self.region_src = ""      # 上一次请求翻译的滚动区原文
        self.region_zh = ""       # 它的译文（滚动区上屏用，允许被下一次覆盖）
        self._region_end = None   # 请求时滚动区在原文里的结束位置；None = 不参与定稿
        self._last_req_at = 0.0

    def _safe_translate(self, text, lang):
        """返回 (译文, 是否成功)。失败时给占位符且不算“已翻译”，下次会重试。"""
        try:
            zh = self._translate(text, lang)
        except Exception:
            return "…", False
        zh = (zh or "").strip()
        return (zh, True) if zh else ("", False)

    @staticmethod
    def _join(prev, add, spaced):
        if not prev:
            return add
        if not add:
            return prev
        return prev + (" " if spaced else "") + add

    def update(self, text, lang, now=None):
        """输入本次快照识别的完整原文，返回上屏所需的四个部分。"""
        now = time.monotonic() if now is None else now
        if not text.startswith(self.committed_src):
            # 识别把已定稿的部分也改了（罕见）：整体重来，避免新旧拼接错位
            self.reset()
        spaced = " " in text

        # ① 定稿：上一次请求的滚动区整体保持下来了 → 原文和译文一起转入定稿区
        #    （滚动区不含最容易变的那几个字，所以“整体保持”并不苛刻）
        if (self.region_src and self._region_end is not None
                and len(os.path.commonprefix([self.prev_text, text])) >= self._region_end):
            self.committed_src = text[: self._region_end]
            self.committed_zh = self._join(self.committed_zh, self.region_zh, spaced)
            self.region_src = self.region_zh = ""
            self._region_end = None
        self.prev_text = text

        # ② 本次滚动区 = 定稿区之后的全部文字，去掉还不稳定的尾巴
        pending = text[len(self.committed_src):]
        fresh = not self.committed_src and not self.region_zh  # 这句话还没出过译文
        if spaced:
            # 有空格的语言：只翻/只定稿到完整的词，半个词留着
            cut = pending.rfind(" ")
            if cut > 0:
                region_raw, committable = pending[:cut], True
            elif fresh or len(pending) - len(self.region_src) >= self.MAX_PREVIEW_CHARS:
                # 还没定稿过，或迟迟等不到词边界（超长复合词）：先给个预览，
                # 预览的边界不在词上，所以不参与定稿，下次照样会被整段替换
                region_raw, committable = pending, False
            else:
                region_raw, committable = "", False
        elif len(pending) > self.TAIL_GRACE_CHARS + self.MIN_REGION_CHARS:
            region_raw, committable = pending[: -self.TAIL_GRACE_CHARS], True
        elif fresh:
            region_raw, committable = pending, True  # 短句/开场：整段翻，首字优先
        else:
            # 尾巴太短、这句话又已经出过字：不值得为它将就发一次请求，
            # 等它长出来（或段落结束时整句重译）
            region_raw, committable = "", False
        region = region_raw.strip()

        # ③ 要不要为它发一次请求
        if region:
            if region.startswith(self.region_src):
                new_chars = len(region) - len(self.region_src)
            else:
                new_chars = len(region)  # 识别改写了滚动区，值得重翻
            if (self.region_zh and new_chars < self.MIN_NEW_CHARS
                    and now - self._last_req_at < self.MIN_INTERVAL_S):
                pass  # 没长出新内容：省一次请求，译文晚一拍
            else:
                zh, ok = self._safe_translate(region, lang)
                if ok:
                    self.region_src, self.region_zh = region, zh
                    self._region_end = (len(self.committed_src) + len(region_raw)
                                        if committable else None)
                    self._last_req_at = now
                else:
                    # 翻不出来也上屏占位符（用户看得出是在翻），但**不**记为已翻译：
                    # 下一次快照还要重试，不能因为一次限流就整段没了译文
                    self.region_src, self.region_zh = "", zh

        return {
            "kind": "live",
            "src_stable": self.committed_src.strip(),
            "src_tail": pending.strip(),
            "zh_stable": self.committed_zh.strip(),
            "zh_tail": self.region_zh,
        }
