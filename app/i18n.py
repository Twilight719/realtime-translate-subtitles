"""界面多语言。

用法：用户可见的字符串用 tr("中文原文") 包一层；ui.language=en 时返回英文，
未收录的字符串原样返回中文（安全降级）。
"""

_lang = "zh"

_EN = {}


def set_language(lang):
    global _lang
    _lang = "en" if lang == "en" else "zh"


def current_language():
    return _lang


def register(mapping):
    """注册 中文→英文 映射（在 i18n_strings.py 里集中维护）。"""
    _EN.update(mapping)


def tr(s):
    if _lang == "en":
        return _EN.get(s, s)
    return s
