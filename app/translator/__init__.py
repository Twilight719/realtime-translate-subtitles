"""翻译后端工厂与故障回退链（带熔断：失败的后端冷却一段时间不再重试）。"""

import logging
import threading
import time
from collections import Counter, OrderedDict

from .base import Translator, TranslationTextError
from .google_web import GoogleWebTranslator
from .llm_api import LlmApiTranslator
from .mymemory import MyMemoryTranslator
from .nllb import NllbTranslator
from .youdao_web import YoudaoWebTranslator

log = logging.getLogger("subtitle.translator")

# 失败后的冷却阶梯（秒）：连续失败越多等越久，成功即清零。
# 一次性封 60 秒在实时字幕里代价太大——实测有道免费接口按 1 次/秒 的节奏打，
# 第 7 次就返回 411(请求频率过快)，静默 65 秒才恢复；也就是说一刀切 60 秒会让
# 恢复后的第一次抖动又把后端封印一分钟。阶梯退避既让网络抖动 5 秒后就能重试，
# 又能对真正的限流逐步拉开距离、不再反复去撞。
COOLDOWN_LADDER_S = (5, 20, 60)
COOLDOWN_S = COOLDOWN_LADDER_S[-1]  # 冷却上限（单次失败的最长等待）


def build_chain(cfg):
    """按 config 中的顺序构建后端列表，排在前面的优先，失败自动回退下一个。"""
    backends = []
    for name in cfg.get("order", ["youdao_web", "nllb", "mymemory"]):
        try:
            if name == "youdao_web":
                backends.append(YoudaoWebTranslator())
            elif name == "mymemory":
                backends.append(MyMemoryTranslator())
            elif name == "google_web":
                backends.append(GoogleWebTranslator())
            elif name == "nllb":
                backends.append(NllbTranslator(device=cfg.get("nllb_device", "cpu")))
            elif name == "llm_api":
                llm = dict(cfg.get("llm_api") or {})
                if llm.get("api_key"):
                    # 术语表挂在 translator 下（识别提示词与设置页都用同一份），
                    # 用 setdefault 传进去：用户真写进 llm_api 里也照收，且不会撞关键字
                    llm.setdefault("glossary", cfg.get("glossary"))
                    backends.append(LlmApiTranslator(**llm))
                else:
                    log.warning("llm_api 未配置 api_key，跳过")
        except Exception as e:
            log.warning("翻译后端 %s 初始化失败: %s", name, e)
    if not backends:
        raise RuntimeError("没有可用的翻译后端")
    return FallbackTranslator(backends)


class FallbackTranslator(Translator):
    name = "fallback"

    # 会话级结果缓存的容量（条）。实时字幕里同一条文本反复出现的概率很高
    # （短句、重复台词、滚动区回退），命中一次就省一次在线请求（规划 §2.2 a）
    CACHE_SIZE = 256

    def __init__(self, backends):
        self.backends = backends
        self._failed_at = {}  # backend -> 上次失败时间戳
        self._fail_count = {}  # backend -> 连续失败次数（决定冷却阶梯长度）
        self._cache = OrderedDict()  # (文本, 源语言, 目标语言, 后端名) -> 译文（LRU）
        self._cache_lock = threading.Lock()
        self._used = Counter()  # 本窗口内各后端成功翻译次数（流水线日志统计，见 take_usage）
        self._used_lock = threading.Lock()

    # ---- 冷却（熔断）----

    def _cooldown_s(self, backend):
        n = self._fail_count.get(backend, 1)
        return COOLDOWN_LADDER_S[min(n, len(COOLDOWN_LADDER_S)) - 1]

    def _cooling(self, backend, now):
        return now - self._failed_at.get(backend, 0) < self._cooldown_s(backend)

    def _mark_failed(self, backend, now):
        self._fail_count[backend] = self._fail_count.get(backend, 0) + 1
        self._failed_at[backend] = now
        return self._cooldown_s(backend)

    def _mark_ok(self, backend):
        """成功即清零：下一次偶发失败又从最短冷却重新开始。"""
        self._fail_count.pop(backend, None)
        self._failed_at.pop(backend, None)

    def take_usage(self):
        """取走并清零"各后端成功翻译次数"（流水线日志用来回答"现在到底谁在翻"）。

        取走而不是只读：这样日志里的数字是"这一段时间内"的分布，不是开机以来的总量。"""
        with self._used_lock:
            used, self._used = self._used, Counter()
        return used

    def _cache_get(self, key):
        with self._cache_lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        return None

    def _cache_put(self, key, value):
        with self._cache_lock:
            self._cache[key] = value
            self._cache.move_to_end(key)
            while len(self._cache) > self.CACHE_SIZE:
                self._cache.popitem(last=False)

    def translate(self, text, src_lang, target="zh", on_delta=None):
        """整句翻译（段落定稿用）：按配置顺序走完整后端链，质量优先。

        on_delta(累计译文) 非 None 时，支持流式的后端会逐段回调（观感更实时）。"""
        return self._run(self.backends, text, src_lang, target, on_delta)

    def translate_fast(self, text, src_lang, target="zh"):
        """实时快照用：按"跟手优先"重排后端，并且走 translate_partial。

        顺序 = 登记过 partial_rank 的后端按实测快慢排（有道 0.08 秒且免费 → Google →
        大模型几百毫秒），其余后端**保持用户配置的顺序**跟在后面（见 base.partial_rank）。
        没配大模型 key 的用户链子里本来就没有它，这里自然不受影响。
        大模型这一次不记上下文，也不会按整句的超时去等（半句话喂进历史会污染后面的整句译文）。
        全是慢后端时退回完整顺序，保证快照至少有译文。"""
        fast = sorted((b for b in self.backends if getattr(b, "partial_ok", True)),
                      key=lambda b: getattr(b, "partial_rank", 50))
        return self._run(fast or self.backends, text, src_lang, target, None, partial=True)

    def _run(self, backends, text, src_lang, target, on_delta, partial=False):
        """在给定的后端顺序上跑一遍回退链。"""
        if src_lang and src_lang == target:
            return text  # 源语言与目标语言相同，无需翻译
        now = time.time()
        last_err = None
        tried_any = False
        # 缓存只在“首选后端（第一个没在冷却的）”上生效：同一句原文交给别的后端
        # 翻出来可能不一样，混着用会让重复出现的句子前后不一致
        first = next((b for b in backends if not self._cooling(b, now)), None)
        if first is not None and not getattr(first, "context_sensitive", False):
            hit = self._cache_get((text, src_lang or "", target, first.name))
            if hit is not None:
                if on_delta is not None:
                    on_delta(hit)  # 流式调用方也按“一次到齐”的语义收到译文
                log.debug("翻译缓存命中（%s）: %s", first.name, text)
                return hit
        for backend in backends:
            if self._cooling(backend, now):
                continue  # 冷却中，跳过
            tried_any = True
            try:
                result = self._call(backend, text, src_lang, target, on_delta, partial)
                if result and str(result).strip():
                    if backend is first and not getattr(backend, "context_sensitive", False):
                        self._cache_put((text, src_lang or "", target, backend.name), result)
                    self._mark_ok(backend)
                    self._count_use(backend.name)
                    return result
                # 空结果不等于成功：继续下一个后端，否则字幕只会显示空白
                log.info("翻译后端 %s 返回空结果，换下一个后端", backend.name)
                last_err = RuntimeError("%s 返回空结果" % backend.name)
            except TranslationTextError as e:
                # 文本级错误：该条文本它翻不了，换下一个后端，但不计入冷却
                log.info("翻译后端 %s 无法处理该文本: %s", backend.name, e)
                last_err = e
            except Exception as e:
                cd = self._mark_failed(backend, time.time())
                log.warning("翻译后端 %s 失败（冷却 %ds）: %s", backend.name, cd, e)
                last_err = e
        if not tried_any:
            # 全部在冷却中：仍按顺序尝试一次，避免长时间无翻译
            for backend in backends:
                try:
                    result = self._call(backend, text, src_lang, target, on_delta, partial)
                    if result and str(result).strip():
                        self._mark_ok(backend)
                        self._count_use(backend.name)
                        return result
                    log.info("翻译后端 %s 返回空结果，换下一个后端", backend.name)
                    last_err = RuntimeError("%s 返回空结果" % backend.name)
                except Exception as e:
                    self._mark_failed(backend, time.time())
                    last_err = e
        raise last_err

    def _count_use(self, name):
        with self._used_lock:
            self._used[name] += 1

    @staticmethod
    def _call(backend, text, src_lang, target, on_delta, partial=False):
        """选调用入口：快照走 translate_partial（后端可区别对待），
        整句才用流式（快照没有回调，半句话逐字上屏只会闪）。"""
        if partial:
            return backend.translate_partial(text, src_lang, target)
        if on_delta is not None and getattr(backend, "supports_stream", False):
            return backend.translate(text, src_lang, target, on_delta=on_delta)
        return backend.translate(text, src_lang, target)

    def close(self):
        """关闭所有后端连接（设置页改配置重建翻译链、程序退出时调用）。"""
        for backend in self.backends:
            try:
                backend.close()
            except Exception:
                log.warning("关闭翻译后端 %s 失败", backend.name, exc_info=True)
