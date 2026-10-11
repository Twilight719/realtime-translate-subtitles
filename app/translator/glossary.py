"""术语表（自定义词典）：解析与两种注入方式（规划 §5.1）。

只在两个地方生效，其它后端吃不了词典（界面必须写清，否则用户以为坏了）：
① 大模型后端的 system prompt —— 强约束译法，质量提升最明显；
② whisper 的识别提示词 —— 只喂原文词条，帮它把专名拼对（SenseVoice 不支持提示词）。

配置形态是"每行一条 原文=译文"的列表（`translator.glossary`），
也容忍用户手写成整段多行文本；空行、# 注释、没等号的行一律跳过。
"""

import re

MAX_ENTRIES = 200       # 注入提示词的词条上限：再多对模型是噪音，还拖慢请求
MAX_TERM_CHARS = 40     # 单条词条长度上限，超长的多半是误粘的整句
MAX_TERMS_CHARS = 300   # 识别提示词里词条部分的长度上限（whisper 提示窗口约 224 token）

# 行尾注释：只把"前面带空白的 #"当注释，避免误伤 "C#" 这类术语
_COMMENT = re.compile(r"\s+#")


def parse(raw):
    """配置里的术语表 → [(原文, 译文), ...]（顺序即用户书写顺序，原文去重、先写的赢）。

    raw 可以是列表（每项一条 "原文=译文"）或一整段多行文本；None/空返回 []。
    """
    if not raw:
        return []
    lines = raw.splitlines() if isinstance(raw, str) else list(raw)
    out, seen = [], set()
    for line in lines:
        if not isinstance(line, str):
            continue
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = _COMMENT.split(line, 1)[0].strip()
        src, sep, dst = line.partition("=")
        src, dst = src.strip(), dst.strip()
        if not sep or not src or not dst:
            continue
        if len(src) > MAX_TERM_CHARS or len(dst) > MAX_TERM_CHARS:
            continue
        if src in seen:
            continue
        seen.add(src)
        out.append((src, dst))
        if len(out) >= MAX_ENTRIES:
            break
    return out


def rules_text(raw):
    """术语表 → system prompt 片段（没有词条时返回空串，此时提示词与不带术语表时逐字相同）。"""
    pairs = parse(raw)
    if not pairs:
        return ""
    items = "；".join(f"{s}={d}" for s, d in pairs)
    return f"\n术语对照表（必须采用下列译法，不要改写、不要另起炉灶）：{items}。"


def source_terms(raw):
    """术语表原文 → 识别提示词片段（按书写顺序，超出长度上限就截断）。"""
    pairs = parse(raw)
    out, used = [], 0
    for src, _ in pairs:
        if used + len(src) + 1 > MAX_TERMS_CHARS:
            break
        out.append(src)
        used += len(src) + 1
    return " ".join(out)


def recognition_prompt(cfg):
    """识别提示词 = 配置里填的识别提示词 + 术语表原文词条；都没有时返回 None。

    whisper 拿它偏置解码（专名/生造词更准），SenseVoice 会忽略（接口兼容）。
    """
    base = ((cfg.get("whisper") or {}).get("prompt") or "").strip()
    terms = source_terms((cfg.get("translator") or {}).get("glossary"))
    if not terms:
        return base or None
    return f"{base} {terms}".strip()
