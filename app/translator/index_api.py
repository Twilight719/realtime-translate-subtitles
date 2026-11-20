"""B站 Index-Translate 官方免费 API（OpenAI 兼容，无需 key，国内直连）。

复用 LlmApiTranslator 的全部能力（流式、上下文、术语表）。
文档：https://github.com/bilibili/Index-Translate
"""

from .llm_api import LlmApiTranslator


class IndexApiTranslator(LlmApiTranslator):
    name = "index_api"

    def __init__(self, timeout=10, stream=True, glossary=None, context_size=1):
        super().__init__(
            base_url="https://index-translate.bilibili.com/v1",
            api_key="index",  # 官方免费 API 不校验 key，按文档任意填写
            model="Index-Translate-35B-A3B",
            context_size=context_size,
            timeout=timeout,
            stream=stream,
            glossary=glossary,
        )
        # 官方 WAF 会拦截 python-requests 默认 UA（412），必须声明客户端 UA
        self._session.headers["User-Agent"] = "Index-Translate-Client/1.0"
