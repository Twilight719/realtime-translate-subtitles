"""文本的语种判据（纯函数：只依赖标准库，CI 上可直接测）。

截图翻译在「源语言 = 自动检测」时必须自己判断这段字是什么语言，才能：
① 选对 Windows OCR 引擎——中文引擎读日语会把假名认成形近汉字；
② 把判定出的源语言传给翻译链——否则 MyMemory/NLLB 会把日语当英语翻。
音频字幕那条路不需要它：whisper 自己会检测语言。

判据全是字符集统计，实测依据（1100×70 渲染样图，zh-Hans-CN 与 ja-JP 两个引擎）：
  - 日语真句「こんにちは、今日はいい天気ですね」：日语引擎 假名 18/汉字 8（0.69）；
    中文引擎假名 0，输出是「乙 、今 日 00 天 氦 ℃ 稳」这种形近字乱码
  - 中文真句「今天天气很好，我们一起去学校吧」：中文引擎正确；
    日语引擎 假名 1/汉字 13（0.071，形近误认）
  → 假名比例在 0.07 与 0.69 之间分界干净（阈值 0.15），但短文本上 1~2 个误报假名
    就能冲过比例线，所以另加「最少字符数」门槛（MIN_KANA 等）。
"""

import re

# ---------------------------------------------------------------- 字符集
# 假名：平假名 + 片假名 + 长音符 ー + 半角片假名。刻意不含 ・(U+30FB) 与浊点，
# 那些是标点，不是判据
_RE_KANA = re.compile(r"[ぁ-ゖゝ-ゟァ-ヺー-ヿｦ-ﾝ]")
# 汉字：扩展 A + 基本区 + 兼容表意文字（々 与 〇 不计：太稀有且中日都用）
_RE_HAN = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
# 谚文：字母 + 兼容字母 + 音节 + 扩展 B
_RE_HANGUL = re.compile(r"[ᄀ-ᇿ㄰-㆏가-힣ힰ-퟿]")
_RE_CYRILLIC = re.compile(r"[Ѐ-ӿԀ-ԯ]")
# 拉丁：ASCII + 拉丁扩展 + 全角字母（游戏界面里的 ＨＰ/ＭＰ 也算拉丁）
_RE_LATIN = re.compile(r"[A-Za-zÀ-ɏḀ-ỿＡ-Ｚａ-ｚ]")

# 简体专用字：只收「简体 / 繁体 / 日文新字体」三形各不相同的字（或简体独有的偏旁）。
# ⚠ 绝不能收日文新字体与简体同形的字（学 国 会 体 医 来 万 与 参 双 当 台 党 旧 点 号
#   円 気 実 …）：收了会把日语判成中文，而翻译链里「源语言 == 目标语言直接回显原文」
#   （app/translator/__init__.py 的 FallbackTranslator），会把日语原文当成译文显示，
#   静默且看起来像"翻译坏了"。
_SIMP_ONLY = (
    # 言字旁（日文用 言）
    "说话请谢记认识词语试计让论议讨训讯讲许设访证评诉译谁调谈课读该详谅谋谎谐谓询讽谜"
    # 纟 / 钅 / 饣 / 门 偏旁（日文用 糸 / 金 / 食 / 門）
    "红级纪纯纸线练组细织终结给络绝统继维绿约纳缩缝缓缠绍绎绑绒缴"
    "钱铁银错钢铜锁钟针铺锦镜"
    "饭饮馆饼饿饱"
    "门问间闻闲闷闹闸闭阐阔闪"
    # 独立简体字（日文形/繁体形都不同）
    "们这东车书见长马鸟鱼龙贝页风飞义乐习乡亚产亲亿众优伟传伤军农办务动历压卫"
    "单图围团对归艺听时关头发买卖贵费员圆职联边过还进远运达连处备观现觉实变气电"
)
# 繁体专用字：同样避开日文新字体（東 車 馬 語 話 時 間 開 買 貴 費 員 職 連 過 進 運 達
# 備 現 觀 視 覺 規 種 鐘 飯 館 … 日语也用，不算）。只用于「这不是简体中文」的否决。
_TRAD_ONLY = "們這說國對經實變學會來體醫萬與歸藝讓點讀聽單戰產賣圓關總樣條錢鐵"

_SIMP_SET = frozenset(_SIMP_ONLY)
_TRAD_SET = frozenset(_TRAD_ONLY)

# 判据阈值：比例 + 最少字符数（短文本只看比例会被 1~2 个形近误认击穿）
MIN_KANA, RATIO_KANA = 3, 0.15       # 假名 / (假名 + 汉字)
MIN_HANGUL, RATIO_HANGUL = 2, 0.15   # 谚文 / 文字类字符
MIN_CYRILLIC, RATIO_CYRILLIC = 2, 0.5


def tag_lang(tag):
    """Windows 语言标签 → 内部语言码（"ja-JP"、"ja" → "ja"）；认不出返回 None。"""
    if not tag:
        return None
    code = str(tag).split("-")[0].lower()
    return code if code in ("zh", "en", "ja", "ko", "ru") else None


def analyze(text):
    """各类字符计数：kana/han/hangul/cyrillic/latin/simp/trad（数字、标点、空白不计）。"""
    text = text or ""
    return {
        "kana": len(_RE_KANA.findall(text)),
        "han": len(_RE_HAN.findall(text)),
        "hangul": len(_RE_HANGUL.findall(text)),
        "cyrillic": len(_RE_CYRILLIC.findall(text)),
        "latin": len(_RE_LATIN.findall(text)),
        "simp": sum(1 for ch in text if ch in _SIMP_SET),
        "trad": sum(1 for ch in text if ch in _TRAD_SET),
    }


def _letters(stats):
    return stats["kana"] + stats["han"] + stats["hangul"] + stats["cyrillic"] + stats["latin"]


def _ratio(part, whole):
    return part / whole if whole else 0.0


def detect_script(text):
    """判定语言码（ja/ko/ru/zh）；判不出返回 None——调用方保持原有行为（交给后端 auto）。

    刻意保守：宁可不判，也不误判。拉丁文本、纯汉字（中日同形）、繁体、数字符号
    一律返回 None：误判成 zh 会触发翻译链的「源=目标直接回显」，把原文当译文。
    """
    stats = analyze(text)
    letters = _letters(stats)
    # 谚文优先于假名：CJK 系引擎的输出里不会有谚文，它只可能来自韩语引擎或图像本身，
    # 证据比假名硬（假名可能是日语引擎读别的语言时的形近误认）
    if stats["hangul"] >= MIN_HANGUL and _ratio(stats["hangul"], letters) >= RATIO_HANGUL:
        return "ko"
    if stats["kana"] >= MIN_KANA and _ratio(stats["kana"], stats["kana"] + stats["han"]) >= RATIO_KANA:
        return "ja"
    if stats["cyrillic"] >= MIN_CYRILLIC and _ratio(stats["cyrillic"], letters) >= RATIO_CYRILLIC:
        return "ru"
    if stats["simp"] - stats["trad"] > 0:
        return "zh"
    return None


def choose_ocr_text(results, profile_tag=None):
    """多引擎识别结果 → (选中的文本, 判定语言码或 None)。

    results: {Windows 语言标签: 识别文本}；profile_tag 标出「系统默认引擎」那一项
    （自动模式下它才是"没把握时"的归宿，与改动前行为一致）。判不出语言时返回 None，
    调用方照旧把 None 传给翻译后端（有道/Google 真 auto）。
    """
    items = [(tag, text) for tag, text in (results or {}).items() if text and text.strip()]
    if not items:
        return "", None
    stats = {tag: analyze(text) for tag, text in items}
    texts = dict(items)

    def pick(lang, score):
        """有判据的候选（score > 0）里选一个：先「引擎语言与判据自洽」，再取证据最强。"""
        hits = [(score(stats[tag]), tag) for tag, _ in items]
        hits = [(strong, tag) for strong, tag in hits if strong > 0]
        if not hits:
            return None
        _, tag = sorted(hits, key=lambda hit: (tag_lang(hit[1]) != lang, -hit[0]))[0]
        return texts[tag], lang

    # ① 强判据：谚文 > 假名 > 西里尔（理由见 detect_script）
    for lang, score in (
        ("ko", lambda s: s["hangul"] if s["hangul"] >= MIN_HANGUL
         and _ratio(s["hangul"], _letters(s)) >= RATIO_HANGUL else 0),
        ("ja", lambda s: s["kana"] if s["kana"] >= MIN_KANA
         and _ratio(s["kana"], s["kana"] + s["han"]) >= RATIO_KANA else 0),
        ("ru", lambda s: s["cyrillic"] if s["cyrillic"] >= MIN_CYRILLIC
         and _ratio(s["cyrillic"], _letters(s)) >= RATIO_CYRILLIC else 0),
    ):
        got = pick(lang, score)
        if got:
            return got

    # ② 简体判据：没有任何强判据时，看"简体专用字 - 繁体专用字"最大且为正的那个结果。
    #    实测：中文真串（我们，+2）胜过日语引擎读中文的乱码串（我們，0）；
    #    日语真串 0 分，不会被误判成中文
    got = pick("zh", lambda s: s["simp"] - s["trad"])
    if got:
        return got

    # ③ 兜底：系统默认引擎的结果，不判定语言（拉丁/纯汉字/数字符号都走这里）
    if profile_tag in texts:
        return texts[profile_tag], None
    return items[0][1], None
