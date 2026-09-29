"""翻译后端工厂与故障回退链（带熔断：失败的后端冷却一段时间不再重试）。"""

import logging
import time

from .base import Translator
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
                llm = cfg.get("llm_api", {})
                if llm.get("api_key"):
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

    def __init__(self, backends):
        self.backends = backends
        self._failed_at = {}  # backend -> 上次失败时间戳

    def translate(self, text, src_lang, target="zh"):
        if src_lang and src_lang == target:
            return text  # 源语言与目标语言相同，无需翻译
        now = time.time()
        last_err = None
        tried_any = False
        for backend in self.backends:
            failed_at = self._failed_at.get(backend, 0)
            if now - failed_at < COOLDOWN_S:
                continue  # 冷却中，跳过
            tried_any = True
            try:
                result = backend.translate(text, src_lang, target)
                return result
            except Exception as e:
                self._failed_at[backend] = time.time()
                log.warning("翻译后端 %s 失败（冷却 %ds）: %s", backend.name, COOLDOWN_S, e)
                last_err = e
        if not tried_any:
            # 全部在冷却中：仍按顺序尝试一次，避免长时间无翻译
            for backend in self.backends:
                try:
                    return backend.translate(text, src_lang, target)
                except Exception as e:
                    self._failed_at[backend] = time.time()
                    last_err = e
        raise last_err
