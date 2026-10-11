"""翻译后端工厂与故障回退链（带熔断：失败的后端冷却一段时间不再重试）。"""

import logging
import threading
import time
from collections import OrderedDict

from .base import Translator, TranslationTextError
from .google_web import GoogleWebTranslator
from .llm_api import LlmApiTranslator
from .mymemory import MyMemoryTranslator
from .nllb import NllbTranslator
from .youdao_web import YoudaoWebTranslator

log = logging.getLogger("subtitle.translator")

COOLDOWN_S = 60  # 后端失败后冷却秒数（如触发限流，1 分钟内不再打扰它）


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
        self._cache = OrderedDict()  # (文本, 源语言, 目标语言, 后端名) -> 译文（LRU）
        self._cache_lock = threading.Lock()

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
        """on_delta(累计译文) 非 None 时，支持流式的后端会逐段回调（观感更实时）。"""
        if src_lang and src_lang == target:
            return text  # 源语言与目标语言相同，无需翻译
        now = time.time()
        last_err = None
        tried_any = False
        # 缓存只在“首选后端（第一个没在冷却的）”上生效：同一句原文交给别的后端
        # 翻出来可能不一样，混着用会让重复出现的句子前后不一致
        first = next((b for b in self.backends
                      if now - self._failed_at.get(b, 0) >= COOLDOWN_S), None)
        if first is not None and not getattr(first, "context_sensitive", False):
            hit = self._cache_get((text, src_lang or "", target, first.name))
            if hit is not None:
                if on_delta is not None:
                    on_delta(hit)  # 流式调用方也按“一次到齐”的语义收到译文
                log.debug("翻译缓存命中（%s）: %s", first.name, text)
                return hit
        for backend in self.backends:
            failed_at = self._failed_at.get(backend, 0)
            if now - failed_at < COOLDOWN_S:
                continue  # 冷却中，跳过
            tried_any = True
            try:
                result = self._call(backend, text, src_lang, target, on_delta)
                if result and str(result).strip():
                    if backend is first and not getattr(backend, "context_sensitive", False):
                        self._cache_put((text, src_lang or "", target, backend.name), result)
                    return result
                # 空结果不等于成功：继续下一个后端，否则字幕只会显示空白
                log.info("翻译后端 %s 返回空结果，换下一个后端", backend.name)
                last_err = RuntimeError("%s 返回空结果" % backend.name)
            except TranslationTextError as e:
                # 文本级错误：该条文本它翻不了，换下一个后端，但不计入冷却
                log.info("翻译后端 %s 无法处理该文本: %s", backend.name, e)
                last_err = e
            except Exception as e:
                self._failed_at[backend] = time.time()
                log.warning("翻译后端 %s 失败（冷却 %ds）: %s", backend.name, COOLDOWN_S, e)
                last_err = e
        if not tried_any:
            # 全部在冷却中：仍按顺序尝试一次，避免长时间无翻译
            for backend in self.backends:
                try:
                    result = self._call(backend, text, src_lang, target, on_delta)
                    if result and str(result).strip():
                        return result
                    log.info("翻译后端 %s 返回空结果，换下一个后端", backend.name)
                    last_err = RuntimeError("%s 返回空结果" % backend.name)
                except Exception as e:
                    self._failed_at[backend] = time.time()
                    last_err = e
        raise last_err

    @staticmethod
    def _call(backend, text, src_lang, target, on_delta):
        """按后端是否声明支持流式，决定要不要把 on_delta 传下去。"""
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
