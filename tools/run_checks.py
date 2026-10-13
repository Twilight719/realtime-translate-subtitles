# -*- coding: utf-8 -*-
"""一键回归检查：语法 → 逻辑 → GUI（可选）。

用法（项目根目录）:
    ./.venv/Scripts/python.exe -X utf8 tools/run_checks.py            # 全量（含 GUI 回归）
    ./.venv/Scripts/python.exe -X utf8 tools/run_checks.py --no-gui   # 仅语法 + 逻辑（CI 用）

GUI 项各自开子进程运行 tools/test_*.py（它们要建 QApplication、真实窗口），
任一失败则以非零退出码结束，方便本地和 CI 统一调用。
"""
import argparse
import ast
import glob
import hashlib
import json
import logging
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

results = []  # (名称, 是否通过, 失败说明)


def record(name, ok, detail=""):
    results.append((name, ok, detail))
    line = ("PASS  " if ok else "FAIL  ") + name
    if not ok and detail:
        line += "  —  " + detail
    print(line)


# ---------------- 1. 语法检查 ----------------

SKIP_DIRS = {".venv", "venv", "build", "dist", "__pycache__", ".git", "node_modules"}


def check_syntax():
    bad = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            try:
                with open(path, encoding="utf-8") as f:
                    ast.parse(f.read(), filename=path)
            except (SyntaxError, UnicodeDecodeError) as e:
                line = getattr(e, "lineno", "?")
                bad.append(f"{os.path.relpath(path, ROOT)}:{line}: {e}")
    record("语法检查（全项目 .py 可解析）", not bad, "; ".join(bad[:5]))


# ---------------- 2. 更新器逻辑 ----------------


def check_updater():
    from app import updater

    ok, detail = True, []

    def fail(msg):
        nonlocal ok
        ok = False
        detail.append(msg)

    for text, want in [("v1.2.3", (1, 2, 3)), ("1.2", (1, 2, 0)), ("v1.4", (1, 4, 0)),
                       ("", None), ("abc", None)]:
        got = updater.parse_version(text)
        if got != want:
            fail(f"parse_version({text!r})={got} 期望 {want}")

    urls = updater.candidate_urls("https://example.com/a.zip")
    if urls[-1] != "https://example.com/a.zip" or len(urls) < 2:
        fail(f"候选下载地址异常: {urls}")

    tmp = tempfile.mkdtemp(prefix="rts_checks_")
    try:
        good = os.path.join(tmp, "good.zip")
        with zipfile.ZipFile(good, "w") as zf:
            zf.writestr("实时翻译字幕/实时翻译字幕.exe", b"MZ")
        if updater.verify_package(good) is not None:
            fail("完好的 zip 应通过校验")

        with open(good, "rb") as f:
            raw = f.read()
        digest = hashlib.sha256(raw).hexdigest()
        if updater.verify_package(good, digest) is not None:
            fail("sha256 匹配时应通过")
        if updater.verify_package(good, "0" * 64) is None:
            fail("sha256 不匹配应判失败")

        truncated = os.path.join(tmp, "truncated.zip")
        with open(truncated, "wb") as f:
            f.write(raw[: len(raw) // 2])
        if updater.verify_package(truncated) is None:
            fail("截断的 zip 应判失败")

        notzip = os.path.join(tmp, "notzip.zip")
        with open(notzip, "wb") as f:
            f.write(b"<html>error page</html>")
        if updater.verify_package(notzip) is None:
            fail("非 zip 文件应判失败")

        # 启动自动检查节流：状态文件用环境变量重定向，不碰真实安装目录
        state = os.path.join(tmp, "state.json")
        os.environ["RTS_UPDATE_STATE"] = state
        if not updater.auto_check_due():
            fail("无状态文件时应视为到期")
        updater.mark_auto_checked()
        if updater.auto_check_due():
            fail("刚检查过应被节流")
        with open(state, "w", encoding="utf-8") as f:
            f.write('{"last_check": 0}')
        if not updater.auto_check_due():
            fail("上次检查时间很久以前应到期")
        with open(state, "w", encoding="utf-8") as f:
            f.write("not json")
        if not updater.auto_check_due():
            fail("状态文件损坏时应视为到期")
        os.environ.pop("RTS_UPDATE_STATE", None)
    finally:
        os.environ.pop("RTS_UPDATE_STATE", None)
        shutil.rmtree(tmp, ignore_errors=True)

    record("更新器逻辑（版本解析/包校验/检查节流）", ok, "; ".join(detail))


# ---------------- 3. 翻译回退链 ----------------


def check_translator():
    from app.translator import FallbackTranslator

    ok, detail = True, []

    def fail(msg):
        nonlocal ok
        ok = False
        detail.append(msg)

    closed = []

    class Fake:
        supports_stream = False

        def __init__(self, name, behavior):
            self.name = name
            self.behavior = behavior
            self.calls = 0

        def translate(self, text, src_lang, target="zh", on_delta=None):
            self.calls += 1
            if isinstance(self.behavior, Exception):
                raise self.behavior
            return self.behavior

        def close(self):
            closed.append(self.name)

    a, b = Fake("a", RuntimeError("boom")), Fake("b", "ok")
    chain = FallbackTranslator([a, b])
    if chain.translate("hello", "en", "zh") != "ok":
        fail("首个后端失败应回退到下一个")
    if (a.calls, b.calls) != (1, 1):
        fail(f"调用次数异常 a={a.calls} b={b.calls}")

    chain.translate("again", "en", "zh")  # a 进入冷却，应被跳过
    if a.calls != 1:
        fail("冷却中的后端不应再被调用")

    empty, c = Fake("e", ""), Fake("c", "done")
    chain2 = FallbackTranslator([empty, c])
    if chain2.translate("x", "en", "zh") != "done":
        fail("空译文应视同失败、继续下一个后端")

    if chain2.translate("你好", "zh", "zh") != "你好" or c.calls != 1:
        fail("源语言=目标语言时应直接返回原文且不调用后端")

    chain2.close()
    if sorted(closed) != ["c", "e"]:
        fail(f"close 未关闭全部后端: {closed}")

    # 会话级缓存（规划 §2.2 a）：同文复用；语言组合不同不串味
    d = Fake("d", "译1")
    chain3 = FallbackTranslator([d])
    chain3.translate("同一句", "ja", "zh")
    if chain3.translate("同一句", "ja", "zh") != "译1" or d.calls != 1:
        fail(f"相同文本应命中缓存不再请求后端（实际调用 {d.calls} 次）")
    chain3.translate("同一句", "ja", "en")
    chain3.translate("同一句", "ko", "zh")
    if d.calls != 3:
        fail(f"源/目标语言不同不应命中缓存（实际调用 {d.calls} 次）")
    # 首个后端失败、由后备后端顶上的结果不进缓存：下次仍要按顺序试一遍
    boom, ok2 = Fake("boom", RuntimeError("x")), Fake("ok2", "好")
    chain5 = FallbackTranslator([boom, ok2])
    chain5.translate("会失败", "ja", "zh")
    chain5.translate("会失败", "ja", "zh")
    if ok2.calls != 2:
        fail("后备后端顶上的结果不应进缓存（否则首选后端恢复了也轮不到它）")

    # 带上下文的大模型后端不进缓存（同一句在不同上下文里可能该译得不一样）
    class Ctx(Fake):
        context_sensitive = True

    e = Ctx("e2", "译2")
    chain4 = FallbackTranslator([e])
    chain4.translate("同文", "ja", "zh")
    chain4.translate("同文", "ja", "zh")
    if e.calls != 2:
        fail("带上下文的后端不应走缓存")

    record("翻译回退链（回退/冷却/空译文/缓存/close）", ok, "; ".join(detail))


# ---------------- 4. 大模型上下文 ----------------


def check_llm_context():
    from app.translator.llm_api import LlmApiTranslator

    ok, detail = True, []

    def fail(msg):
        nonlocal ok
        ok = False
        detail.append(msg)

    t = LlmApiTranslator(base_url="http://localhost/v1", api_key="k", model="m", context_size=2)
    for i in range(5):
        t._record_context(f"句{i}", f"译{i}", "ja", "zh")
    hist = [s for s, _ in t._history]
    if hist != ["句3", "句4"]:
        fail(f"上下文未按 context_size 裁剪: {hist}")

    t._record_context("new", "新", "en", "zh")  # 源语言变化 → 先清空
    if [s for s, _ in t._history] != ["new"]:
        fail(f"语言变化未清空上下文: {[s for s, _ in t._history]}")

    contents = [m["content"] for m in t._messages("当前句", "zh")]
    if contents[-1] != "当前句" or "new" not in contents or "新" not in contents:
        fail(f"上下文未正确注入消息序列: {contents}")

    t0 = LlmApiTranslator(base_url="http://localhost/v1", api_key="k", model="m", context_size=0)
    t0._record_context("a", "b", "ja", "zh")
    if t0._history:
        fail("context_size=0 不应保留历史")
    msgs0 = t0._messages("当前句", "zh")
    if len(msgs0) != 2:
        fail(f"context_size=0 时消息应只有 system+user，实际 {len(msgs0)} 条")

    record("大模型上下文（裁剪/语言切换清空/关闭上下文）", ok, "; ".join(detail))


# ---------------- 5. 实时字幕状态机 ----------------


def _old_live_reference(texts, lang, tr):
    """v1.3.9 的实时字幕算法（新确认的前缀翻一次、尾部再翻一次）。

    只用于对比请求量——它每次快照把同一段文字翻两遍，正是 v1.4.0 §2.2 要解决的问题。
    """
    prev, conf_src, last_tail = "", "", None

    def common_prefix(a, b):
        cp = os.path.commonprefix([a, b])
        if " " in b:
            i = cp.rfind(" ")
            return cp[: i + 1] if i >= 0 else ""
        return cp[:-2] if len(cp) > 2 else ""

    for text in texts:
        cp = common_prefix(prev, text)
        if len(cp) > len(conf_src):
            newly = cp[len(conf_src):].strip()
            if newly:
                tr(newly, lang)
            conf_src = cp
        tail = text[len(conf_src):].strip()
        if tail and tail != last_tail:
            tr(tail, lang)
            last_tail = tail
        prev = text


def _live_snapshots(full, step=6, revise=0.5, seed=1):
    """把一句完整的话切成逐步增长的识别结果，末尾偶尔认错（下一帧改回来）。"""
    rnd = random.Random(seed)
    out, n = [], 0
    while n < len(full):
        n = min(len(full), n + step)
        text = full[:n]
        if n < len(full) and rnd.random() < revise:
            text = text[:-1] + "※"
        out.append(text)
    out.append(full)
    return out


def check_live_caption():
    from app.live_caption import LiveCaptionState

    ok, detail = True, []

    def fail(msg):
        nonlocal ok
        ok = False
        detail.append(msg)

    calls = []

    def fake_translate(text, lang):
        calls.append(text)
        return "<" + text + ">"

    st = LiveCaptionState(fake_translate)
    p1 = st.update("今日はいい天気ですね", "ja")
    if not p1["zh_tail"]:
        fail("第一帧就必须有译文（首字延迟是硬指标）")
    if len(calls) != 1:
        fail(f"第一帧应只发一次请求，实际 {len(calls)} 次")

    p2 = st.update("今日はいい天気ですね。散歩しましょう", "ja")
    if p2["src_stable"] != "今日はいい天気で":
        fail(f"CJK 前缀确认异常: {p2['src_stable']!r}")
    if not p2["zh_stable"]:
        fail("确认区译文为空")

    p3 = st.update("今日はいい天気ですね。散歩しましょう", "ja")
    if not p3["src_stable"].startswith(p2["src_stable"]):
        fail("确认区应当只增不减/前缀稳定")

    n = len(calls)
    p4 = st.update("今日はいい天気ですね。散歩しましょう", "ja")  # 尾部没变
    if len(calls) != n:
        fail(f"尾部未变化时不应重复调用翻译（多发了 {len(calls) - n} 次）")
    if not p4["zh_stable"].startswith(p3["zh_stable"]):
        fail("确认区译文应当只增不改")

    st.reset()
    if (st.committed_src or st.committed_zh or st.prev_text
            or st.region_src or st.region_zh or st._region_end is not None):
        fail("reset 未清空状态")

    # 空格分词语言：只确认到完整词边界，不确认半个词
    st2 = LiveCaptionState(fake_translate)
    st2.update("hello world foo", "en")
    p = st2.update("hello world foo bar baz", "en")
    if p["src_stable"] != "hello world":
        fail(f"英文词边界确认异常: {p['src_stable']!r}")
    st2b = LiveCaptionState(fake_translate)
    st2b.update("hello wor", "en")
    p = st2b.update("hello world", "en")
    if p["src_stable"] != "hello":
        fail(f"英文不应把半个词定稿: {p['src_stable']!r}")

    # 翻译抛异常时不能把整条流水线带崩
    def boom(text, lang):
        raise RuntimeError("boom")

    st3 = LiveCaptionState(boom)
    try:
        p = st3.update("こんにちは、いい天気ですね", "ja")
        if p["zh_tail"] != "…":
            fail(f"翻译失败时应回退占位符: {p['zh_tail']!r}")
        if st3.region_src:
            fail("翻译失败不应记为已翻译（否则这句话再也不会重试）")
    except Exception as e:
        fail(f"翻译失败不应向外抛异常: {e!r}")

    # ---- 请求量：新算法对比 v1.3.9 参考实现（规划 §2.4 验收）----
    sentences = [
        "うちの中学は弁当制で持って行くのは当たり前だった",
        "今日はいい天気ですね、散歩しましょうか",
        "ちょっと待って、今そっちに行くから",
        "え、なんでそんなことになったの",
        "ありがとう、助かったよ",
        "はい、そうです",
        "hello world i think we should go now",
        "yes that is right",
    ]
    old_calls, new_calls, chars_old, chars_new, chars_src = [], [], 0, 0, 0
    for s in sentences:
        snaps = _live_snapshots(s)
        chars_src += len(s)
        tr_old = lambda t, lang: old_calls.append(t)  # noqa: E731
        _old_live_reference(snaps, "ja", tr_old)
        live = LiveCaptionState(lambda t, lang: new_calls.append(t) or "<%s>" % t)
        last = None
        for t in snaps:
            last = live.update(t, "ja")
        # 上屏不丢字：定稿区 + 滚动区 == 这段识别结果（英文会在词间补空格）
        shown = (last["src_stable"] + last["src_tail"]).replace(" ", "")
        if shown != snaps[-1].replace(" ", ""):
            fail(f"上屏丢字: {shown!r} != {snaps[-1]!r}")
    chars_old = sum(len(c) for c in old_calls)
    chars_new = sum(len(c) for c in new_calls)
    if len(new_calls) > len(old_calls) * 0.5:
        fail(f"在线请求应减少 ≥50%：旧 {len(old_calls)} 次 → 新 {len(new_calls)} 次")
    if chars_new > chars_src * 1.3:
        fail(f"每个字应只被翻一次左右：原文 {chars_src} 字，实际翻译 {chars_new} 字")
    detail.append(f"请求 {len(old_calls)}→{len(new_calls)} 次，"
                  f"翻译字数 {chars_old}→{chars_new}（原文 {chars_src} 字）")

    record("实时字幕状态机（定稿/节流/首字延迟/异常兜底）", ok, "; ".join(detail))


# ---------------- 5b. 快照节流（自适应间隔） ----------------


def check_snapshot_pacing():
    ok, detail = True, []

    def fail(msg):
        nonlocal ok
        ok = False
        detail.append(msg)

    try:
        import main as app_main
        from app.vad import VadSegmenter
    except ImportError as e:
        record("快照节流（自适应间隔）", True, f"跳过（本环境缺依赖 {getattr(e, 'name', e)}）")
        return

    # 间隔算法：快的时候不拉长（跟手性/首字延迟不变），慢的时候拉长、封顶
    if app_main.partial_interval_for(0.2, 0.8) != 0.8:
        fail("翻译很快时快照间隔应保持配置值")
    if abs(app_main.partial_interval_for(1.5, 0.8) - 1.8) > 1e-6:
        fail(f"翻译慢时快照间隔应随之拉长，实际 {app_main.partial_interval_for(1.5, 0.8)}")
    if app_main.partial_interval_for(30, 0.8) != app_main.PARTIAL_INTERVAL_MAX_S:
        fail("快照间隔应封顶")

    # VAD 侧的触发节奏：本段第一次快照按基础间隔，之后按自适应间隔
    seg = VadSegmenter.__new__(VadSegmenter)  # 不加载 silero 模型，只验节奏
    seg._base_partial_frames = 25             # 0.8s / 32ms
    seg.partial_frames = 25
    seg._last_partial = 0
    seg._buffer = [0] * 25
    if not seg._partial_due():
        fail("本段第一次快照应按基础间隔触发")
    seg.partial_frames = 62                   # 后端慢：间隔被拉到约 2s
    seg._last_partial = 20
    seg._buffer = [0] * 60
    if seg._partial_due():
        fail("间隔拉长后不应还按老节奏出快照")
    seg._buffer = [0] * 82
    if not seg._partial_due():
        fail("攒够自适应间隔后应出快照")
    seg.set_partial_interval(0.1)             # 比基础间隔还小：不能低于基础值
    if seg.partial_frames != 25:
        fail("自适应间隔不应低于配置的基础间隔")

    record("快照节流（自适应间隔）", ok, "; ".join(detail))


# ---------------- 5c. 配置模板一致性 ----------------


def check_config_template():
    """内置默认配置（main.DEFAULT_CONFIG）必须和 config.example.yaml 逐项一致。

    两份都是手写的、都要给用户看（初装自动生成 / 仓库里的模板），改一份忘另一份
    会让"程序生成的配置"和"文档里的配置"对不上。"""
    try:
        import io

        from ruamel.yaml import YAML

        import main as app_main
    except ImportError as e:
        record("配置模板一致", True, f"跳过（本环境缺依赖 {getattr(e, 'name', e)}）")
        return

    yaml = YAML(typ="safe")
    builtin = yaml.load(app_main.DEFAULT_CONFIG)
    with io.open(os.path.join(ROOT, "config.example.yaml"), encoding="utf-8") as f:
        example = yaml.load(f.read())

    diffs = []

    def walk(a, b, path=""):
        if isinstance(a, dict) or isinstance(b, dict):
            for k in sorted(set(a or {}) | set(b or {})):
                walk((a or {}).get(k), (b or {}).get(k), f"{path}/{k}")
        elif a != b:
            diffs.append(f"{path}: 内置={a!r} 模板={b!r}")

    walk(builtin, example)
    record("配置模板一致（内置默认 == config.example.yaml）", not diffs, "; ".join(diffs[:3]))


# ---------------- 5d. 快照/定稿后端分级 + 冷却阶梯 ----------------


def check_partial_backend():
    ok, detail = True, []

    def fail(msg):
        nonlocal ok
        ok = False
        detail.append(msg)

    from app.translator import COOLDOWN_LADDER_S, FallbackTranslator

    class Fake:
        partial_ok = True
        partial_rank = 50

        def __init__(self, name, result="译"):
            self.name, self.result = name, result  # partial_rank 走类属性，别在实例上覆盖
            self.calls = 0
            self.partial_calls = 0

        def translate(self, text, src_lang, target="zh", on_delta=None):
            self.calls += 1
            if isinstance(self.result, Exception):
                raise self.result
            return self.result

        def translate_partial(self, text, src_lang, target="zh"):
            self.partial_calls += 1
            return self.translate(text, src_lang, target)

        def close(self):
            pass

    class Big(Fake):
        """大模型：整句排第一（用户就这么配的），快照排在有道之后。"""
        context_sensitive = True
        supports_stream = True
        partial_rank = 10

    class Quick(Fake):
        partial_rank = 0

    class Slow(Fake):
        partial_rank = 20

    class NoPartial(Fake):
        partial_ok = False

    big, quick, slow = Big("big", "大模型译文"), Quick("quick", "快译文"), Slow("slow", "兜底译文")
    chain = FallbackTranslator([big, quick, slow])  # 配置顺序：大模型排第一
    if chain.translate("整句定稿", "ja", "zh") != "大模型译文" or big.calls != 1:
        fail("整句定稿应走配置顺序（大模型排第一就用大模型）")
    if chain.translate_fast("半句快照", "ja", "zh") != "快译文" or quick.partial_calls != 1:
        fail("快照应按 partial_rank 重排（先走快的后端，不看配置顺序）")
    if big.partial_calls:
        fail("快后端没被限流时不该动大模型")

    # 快后端被限流 → 大模型顶上（而不是掉到最慢的 MyMemory）
    quick.result = RuntimeError("有道返回异常: 请求频率过快 411")
    chain2 = FallbackTranslator([big, quick, slow])
    if chain2.translate_fast("半句快照", "ja", "zh") != "大模型译文" or big.partial_calls != 1:
        fail("快后端限流时快照应落到大模型")
    if slow.partial_calls:
        fail("有快后端和大模型时不该掉到 MyMemory")

    # 没登记 partial_rank 的后端保持用户配置的顺序（别把默认顺序里的 NLLB/MyMemory 颠倒）
    seen_order = []

    class Traced(Fake):
        def translate_partial(self, text, src_lang, target="zh"):
            seen_order.append(self.name)
            raise RuntimeError("都没成，只看顺序")

    try:
        FallbackTranslator([Traced("a"), Traced("b"), Traced("c")]).translate_fast("半句", "ja", "zh")
    except Exception:
        pass
    if seen_order != ["a", "b", "c"]:
        fail(f"没排名的后端应保持配置顺序，实际 {seen_order}")

    # 快照必须走 translate_partial 而不是 translate（后端要能区别对待）
    class Marked(Fake):
        partial_rank = 0

        def translate(self, *a, **kw):
            return "走了 translate（错）"

        def translate_partial(self, text, src_lang, target="zh"):
            self.partial_calls += 1
            return "走了 translate_partial"

    if FallbackTranslator([Marked("marked")]).translate_fast("半句", "ja", "zh") != "走了 translate_partial":
        fail("快照没走 translate_partial（大模型那条不记上下文的约定会失效）")

    # 全部后端都声明不吃快照时不能没译文：退回完整顺序
    if FallbackTranslator([NoPartial("np", "整句译文")]).translate_fast("半句", "ja", "zh") != "整句译文":
        fail("全是慢后端时应退回完整顺序，保证快照有译文")

    from app.translator.llm_api import LlmApiTranslator
    from app.translator.mymemory import MyMemoryTranslator
    from app.translator.youdao_web import YoudaoWebTranslator

    if not getattr(LlmApiTranslator, "partial_ok", False):
        fail("LlmApiTranslator 应参与快照（排在有道之后）")
    ranks = [YoudaoWebTranslator.partial_rank, LlmApiTranslator.partial_rank,
             MyMemoryTranslator.partial_rank]
    if ranks != sorted(ranks) or len(set(ranks)) != len(ranks):
        fail(f"快照顺序应为 有道 < 大模型 < MyMemory，实际 {ranks}")

    # 大模型的快照调用：不记上下文、用短超时（否则半句话会污染整句译文，
    # 慢调用还会挡住下一次识别）
    llm = LlmApiTranslator(base_url="https://example.invalid/v1", api_key="k",
                           model="m", context_size=1)
    seen = {}
    llm._request = lambda text, target, on_delta, timeout: (
        seen.update(timeout=timeout, on_delta=on_delta) or "译文")
    if llm.translate_partial("半句快照", "ja", "zh") != "译文":
        fail("大模型快照翻译没走到 _request")
    if llm._history:
        fail("快照翻译不该记进上下文历史（会污染后面的整句译文）")
    if seen.get("timeout") != LlmApiTranslator.PARTIAL_TIMEOUT_S:
        fail("快照该用更短的超时")
    if seen.get("on_delta") is not None:
        fail("快照不该走流式（半句话逐字上屏只会闪）")
    llm.translate("整句定稿", "ja", "zh")
    if len(llm._history) != 1:
        fail("整句翻译应该记上下文")
    if LlmApiTranslator.PARTIAL_TIMEOUT_S >= 8:
        fail("快照超时应明显短于整句的 8 秒")

    # main.py 的快照路径要真接上
    with open(os.path.join(ROOT, "main.py"), encoding="utf-8") as f:
        main_src = f.read()
    if "def _fast_translate" not in main_src:
        fail("main.py 里没有 _fast_translate")
    if "LiveCaptionState(lambda t, lang: self._fast_translate" not in main_src:
        fail("快照状态机没接 _fast_translate（分级不会生效）")

    # 冷却阶梯：连续失败越等越久，成功即回到最短
    f = Fake("f", RuntimeError("boom"))
    ladder_chain = FallbackTranslator([f, Fake("g", "好")])
    if ladder_chain._cooldown_s(f) != COOLDOWN_LADDER_S[0]:
        fail("首次失败应只有最短冷却")
    ladder_chain._mark_failed(f, time.time())
    ladder_chain._mark_failed(f, time.time())
    if ladder_chain._cooldown_s(f) != COOLDOWN_LADDER_S[1]:
        fail("连续两次失败应升到第二档冷却")
    for _ in range(5):
        ladder_chain._mark_failed(f, time.time())
    if ladder_chain._cooldown_s(f) != COOLDOWN_LADDER_S[-1]:
        fail("连续失败应封顶在最长冷却")
    ladder_chain._mark_ok(f)
    if ladder_chain._cooldown_s(f) != COOLDOWN_LADDER_S[0]:
        fail("成功之后冷却档位应清零")
    if COOLDOWN_LADDER_S[-1] != 60:
        fail("最长冷却应保持 60 秒（限流恢复时间实测约 65 秒）")

    # 真实链路：失败后被跳过，冷却到点后重新启用
    x = Fake("x", RuntimeError("boom"))
    chain3 = FallbackTranslator([x, Fake("y", "好")])
    if chain3.translate("一", "ja", "zh") != "好" or x.calls != 1:
        fail("首个后端失败应回退到下一个")
    chain3.translate("二", "ja", "zh")
    if x.calls != 1:
        fail("冷却期内不应再调用失败过的后端")
    chain3._failed_at[x] = time.time() - COOLDOWN_LADDER_S[0] - 0.1
    chain3.translate("三", "ja", "zh")
    if x.calls != 2:
        fail("冷却到点后应重新尝试该后端")

    # 后端用量统计（统计行里的"翻译后端 xxx×N"）
    chain4 = FallbackTranslator([Fake("u", "好")])
    chain4.translate("甲", "ja", "zh")
    chain4.translate("乙", "ja", "zh")
    if chain4.take_usage().get("u") != 2:
        fail(f"后端用量统计不准: {chain4.take_usage()}")
    if chain4.take_usage():
        fail("take_usage 之后应清零，日志里的数字才是本窗口的")

    record("快照/定稿后端分级 + 冷却阶梯", ok, "; ".join(detail))


# ---------------- 5e. 流水线统计日志 ----------------


def check_pipeline_stats():
    ok, detail = True, []

    def fail(msg):
        nonlocal ok
        ok = False
        detail.append(msg)

    try:
        import main as app_main
    except ImportError as e:
        record("流水线统计", True, f"跳过（本环境缺依赖 {getattr(e, 'name', e)}）")
        return

    class Translator:
        def take_usage(self):
            return app_main.Counter({"youdao_web": 3})

    stats = app_main.PipelineStats()
    stats.record(asr_s=0.5, item_s=0.6)
    stats.record(asr_s=0.7, item_s=0.9)
    stats.record_drop("实时快照")
    stats.set_interval(1.5)
    if stats.take_due(Translator()) is not None:
        fail("没到窗口时间就不该输出统计")

    stats._start -= app_main.PipelineStats.WINDOW_S + 1  # 把窗口推到到点
    line = stats.take_due(Translator())
    if not line:
        fail("到点后应输出一行统计")
    else:
        for want in ("处理 2 条", "单条中位 0.75", "最慢 0.90", "识别中位 0.60",
                     "丢弃 实时快照 1", "快照间隔 1.5s", "youdao_web×3"):
            if want not in line:
                fail(f"统计行缺少 {want!r}: {line}")
    if stats.take_due(Translator()) is not None:
        fail("输出后应重新计时，不重复输出同一窗口")

    idle = app_main.PipelineStats()
    idle._start -= app_main.PipelineStats.WINDOW_S + 1
    if idle.take_due(Translator()) is not None:
        fail("空闲窗口不该刷统计日志")

    with open(os.path.join(ROOT, "main.py"), encoding="utf-8") as f:
        src = f.read()
    if "def _put_latest(self, q, item, kind)" not in src:
        fail("_put_latest 应为实例方法（丢弃要进统计）")
    if "self._stats.record_drop(kind)" not in src:
        fail("丢弃时没计入统计（\"处理跟不上语速\"那条日志会看不见）")
    if "self._stats.take_due(self._translator)" not in src:
        fail("识别线程没有定期输出统计")

    record("流水线统计（耗时/丢弃/后端用量）", ok, "; ".join(detail))


def check_asr_repeat():
    """识别复读：压缩比判据 + 重跑门槛 + 折叠兜底（真机日志里出过 600 字 21 遍的复读）。"""
    ok, detail = True, []

    def fail(msg):
        nonlocal ok
        ok = False
        detail.append(msg)

    # 源码断言放最前面：不需要第三方依赖，CI（只装 requests）上也能守住
    # 重跑只由压缩比触发，且必须带上温度（否则重跑等于白跑）
    with open(os.path.join(ROOT, "app", "transcriber.py"), encoding="utf-8") as f:
        src = f.read()
    for want in ("temperature=temperature", "RETRY_TEMPERATURE", "_compression_ratio(text)",
                 "collapse_repeats(text)", "condition_on_previous_text=False"):
        if want not in src:
            fail(f"transcriber.py 缺少 {want!r}")
    if "temperature=[0.0," in src or "temperature=[0," in src:
        fail("别退回多级温度阶梯：默认那套 8 级会在嘈杂音频上连跑好几遍")

    try:
        import numpy as np

        from app.transcriber import DEGENERATE_RATIO, _compression_ratio, collapse_repeats
    except ImportError as e:
        # 纯函数与接线验证都得 import transcriber 本体（它顶层 import numpy/faster_whisper），
        # CI 装不起依赖就标跳过——本地全量 run_checks 是发版前的硬门槛
        record("识别复读（压缩比判据/重跑/折叠兜底）", ok,
               "; ".join(detail + [f"跳过（本环境缺依赖 {getattr(e, 'name', e)}）"]))
        return

    if not 2.0 < DEGENERATE_RATIO <= 3.0:
        fail(f"压缩比阈值 {DEGENERATE_RATIO} 偏离 whisper 官方推荐区间")

    # 真机日志里的两条复读（2026-10-12 22:34 / 22:36）：压缩比必须超阈值，
    # 否则重跑不会触发；同时正常句子的压缩比要远低于阈值，别误触发
    loops = [
        "Where is it? " + "I don't think there is one. " * 21,
        ("Rage my god, haha, that is the funniest joke I've heard all month Veedle. "
         "There is absolutely no way that you are six feet four inches. ")
        + "What's up guys? A little out of place, huh? " * 10,
    ]
    normal = "Well, I'm gonna be real with you guys. It doesn't really feel like a sleepover."
    for t in loops:
        if _compression_ratio(t) <= DEGENERATE_RATIO:
            fail(f"复读文本压缩比 {_compression_ratio(t):.2f} 未超阈值，重跑不会触发")
    if _compression_ratio(normal) > 1.5:
        fail(f"正常句子压缩比偏高（{_compression_ratio(normal):.2f}），会误触发重跑")

    # 折叠：复读留下 1 遍，去重遍数要报对
    folded_text, folded = collapse_repeats(loops[0])
    if folded != 20 or folded_text != "Where is it? I don't think there is one.":
        fail(f"英文复读折叠不对：folded={folded} text={folded_text!r}")
    _, folded2 = collapse_repeats(loops[1])
    if folded2 != 9:
        fail(f"长句复读折叠遍数不对：{folded2}")

    # 不该误伤：强调式重复（2~4 遍）、单字重复、日语拟声词都应原样保留
    for t in ["No no no no no no.",
              "I don't know. I don't know. I don't know. I don't know.",
              "ビリビリビリビリビリビリが生きている限り",
              normal]:
        out, n = collapse_repeats(t)
        if n or out != t:
            fail(f"不该折叠却被改了：{t!r} → {out!r}（{n} 遍）")

    # 中文（无空格）复读走字符周期
    zh_out, zh_n = collapse_repeats("今天天气真不错。" * 8)
    if zh_n != 7 or zh_out != "今天天气真不错。":
        fail(f"中文复读折叠不对：{zh_n} 遍 → {zh_out!r}")

    # 中间复读、首尾保留
    mid_out, mid_n = collapse_repeats("好的。" + "我知道了。" * 6 + "那就这样。")
    if mid_n != 5 or mid_out != "好的。我知道了。那就这样。":
        fail(f"中间复读折叠不对：{mid_out!r}（{mid_n} 遍）")

    # 接线验证：拿假模型跑通 transcribe()，确认①正常语音只跑一遍（不多花时间）
    # ②复读时才补跑 0.6 并采用重跑结果 ③重跑也压不住时交给折叠兜底
    from app.transcriber import Transcriber

    class _Seg:
        def __init__(self, text):
            self.text = text

    class _Info:
        language = "en"
        language_probability = 0.99

    class _FakeModel:
        def __init__(self, by_temperature):
            self.by_temperature = by_temperature
            self.calls = []

        def transcribe(self, segment, **kw):
            t = kw.get("temperature")
            self.calls.append(t)
            return [_Seg(self.by_temperature[t])], _Info()

    def _run(mapping):
        tr = Transcriber.__new__(Transcriber)  # 绕开模型加载，只测接线
        tr.beam_size, tr.model = 1, _FakeModel(mapping)
        return tr.transcribe(np.zeros(1600, dtype=np.float32)), tr.model.calls

    (text, lang), calls = _run({0.0: normal})
    if calls != [0.0] or text != normal:
        fail(f"正常语音不该重跑：calls={calls} text={text!r}")

    (text, lang), calls = _run({0.0: loops[0], 0.6: "Where is it? I don't think there is one."})
    if calls != [0.0, 0.6] or text != "Where is it? I don't think there is one.":
        fail(f"复读时应补跑 0.6 并采用其结果：calls={calls} text={text!r}")

    (text, lang), calls = _run({0.0: loops[0], 0.6: loops[0]})
    if calls != [0.0, 0.6] or text != "Where is it? I don't think there is one.":
        fail(f"重跑仍复读时应折叠兜底：calls={calls} text={text!r}")

    record("识别复读（压缩比判据/重跑/折叠兜底）", ok, "; ".join(detail))


# ---------------- 6. 包型识别与选包 ----------------

CPU_NAME = "realtime-translate-subtitles-v9.9.9-windows-x64.zip"
CUDA_NAME = "realtime-translate-subtitles-v9.9.9-windows-x64-cuda.zip"


def _asset(name):
    return {"name": name, "size": 123, "digest": "", "browser_download_url": "https://e/" + name}


def check_flavor():
    import json

    from app import flavor, updater

    ok, detail = True, []

    try:
        import main as app_main  # 依赖 onnxruntime/PyQt5/ruamel.yaml
    except ImportError as e:
        # CI 只装 requests（快）：默认配置那几项跳过，其余选包逻辑照查
        app_main = None
        detail.append(f"跳过默认配置检查（本环境缺依赖 {getattr(e, 'name', e)}）")

    def fail(msg):
        nonlocal ok
        ok = False
        detail.append(msg)

    # 选包：精确后缀，且 CPU 规则绝不能命中 CUDA 包
    if updater.asset_for_flavor([_asset(CUDA_NAME), _asset(CPU_NAME)], "cpu")["name"] != CPU_NAME:
        fail("CPU 规则未选中 CPU 包")
    if updater.asset_for_flavor([_asset(CPU_NAME), _asset(CUDA_NAME)], "cuda")["name"] != CUDA_NAME:
        fail("CUDA 规则未选中 CUDA 包")
    if updater.asset_for_flavor([_asset(CUDA_NAME)], "cpu") is not None:
        fail("只有 CUDA 包时，CPU 规则不应命中任何资产")
    if updater.asset_for_flavor([_asset(CPU_NAME)], "cuda") is not None:
        fail("只有 CPU 包时，CUDA 规则不应命中任何资产")
    # ≤1.3.9 的老客户端只认 endswith("windows-x64.zip")：CUDA 包名绝不能命中，
    # 否则老用户会被塞 750 MB（这是"新用户默认拿小包"的地基）
    if CUDA_NAME.endswith("windows-x64.zip"):
        fail("CUDA 包名以 windows-x64.zip 结尾，老客户端会误选它")
    if not CPU_NAME.endswith("windows-x64.zip"):
        fail("CPU 包名必须沿用老名字，老客户端才能拿到小包")

    real_has_libs = flavor.has_cuda_libs
    real_nvcuda = flavor.nvcuda_available
    real_fetch = updater.fetch_release
    tmp = tempfile.mkdtemp(prefix="rts_flavor_")
    try:
        def write_marker(fl):
            with open(os.path.join(tmp, "flavor.json"), "w", encoding="utf-8") as f:
                json.dump({"flavor": fl, "version": "9.9.9", "commit": "abc"}, f)

        write_marker("cpu")
        if flavor.current(base_dir=tmp) != "cpu":
            fail("有 cpu 标记时应判为 cpu 包")
        flavor.has_cuda_libs = lambda: True
        write_marker("cuda")
        if flavor.current(base_dir=tmp) != "cuda":
            fail("有 cuda 标记且带 CUDA 库时应判为 cuda 包")
        flavor.has_cuda_libs = lambda: False
        if flavor.current(base_dir=tmp) != "cpu":
            fail("标记 cuda 但目录里没有 CUDA 库（安装不完整）应判为 cpu 包")
        os.remove(os.path.join(tmp, "flavor.json"))
        flavor.nvcuda_available = lambda: True
        if flavor.current(cfg_device="cuda", base_dir=tmp) != "cuda":
            fail("无标记 + device=cuda + 有 N 卡 应判为 cuda 包")
        if flavor.current(cfg_device="cpu", base_dir=tmp) != "cpu":
            fail("无标记 + device=cpu 应判为 cpu 包")
        flavor.nvcuda_available = lambda: False
        if flavor.current(cfg_device="cuda", base_dir=tmp) != "cpu":
            fail("无标记 + 没有 N 卡 应判为 cpu 包")
        # 换包建议只在"确实装了包"（有标记）时给
        flavor.has_cuda_libs = lambda: True
        if flavor.switch_suggestion(base_dir=tmp) is not None:
            fail("没有包内标记（源码运行）不应给换包建议")
        write_marker("cpu")
        flavor.nvcuda_available = lambda: True
        if flavor.switch_suggestion(base_dir=tmp) != "cuda":
            fail("CPU 包 + 有 N 卡 应建议切到 CUDA 版")
        write_marker("cuda")
        if flavor.switch_suggestion(base_dir=tmp) is not None:
            fail("CUDA 包 + 有 N 卡 不该建议换包")
        flavor.nvcuda_available = lambda: False
        if flavor.switch_suggestion(base_dir=tmp) != "cpu":
            fail("CUDA 包 + 没 N 卡 应建议切到 CPU 版")

        # 缺包时不回退另一个包（规划 §1.6(b)）
        flavor.has_cuda_libs = lambda: True
        with open(os.path.join(tmp, "flavor.json"), "w", encoding="utf-8") as f:
            json.dump({"flavor": "cuda", "version": "9.9.9", "commit": "abc"}, f)
        updater.fetch_release = lambda timeout=8: {
            "tag": "v9.9.9", "url": "u", "error": None, "reachable": True,
            "assets": {"cpu": _asset(CPU_NAME), "cuda": None},
        }
        res = updater.check_update(flavor="cuda")
        if not res["has_update"]:
            fail("有新版本时应 has_update=True")
        if res["asset"] is not None:
            fail("缺少 CUDA 包时不应退而给出 CPU 包")
        if not res["flavor_missing"] or not res["error"]:
            fail("缺少目标包时必须给出明确提示")
        if res["alt_asset"] is None:
            fail("另一种包型的资产应作为换包入口的备选返回")
        res2 = updater.check_update(flavor="cuda", cfg_device="")
        if res2["flavor"] != "cuda":
            fail(f"显式传入包型时应按传入值处理，实际 {res2['flavor']}")
        updater.fetch_release = lambda timeout=8: {
            "tag": "v9.9.9", "url": "u", "error": None, "reachable": True,
            "assets": {"cpu": _asset(CPU_NAME), "cuda": _asset(CUDA_NAME)},
        }
        res3 = updater.check_update(flavor="cpu")
        if res3["asset"]["name"] != CPU_NAME or res3["flavor_missing"]:
            fail("两个包都在时应正常选中 CPU 包")

        # 换包提示只弹一次；写状态不能把更新检查的节流时间冲掉（两者共用一个文件）
        state = os.path.join(tmp, "update_state.json")
        old_env = os.environ.get("RTS_UPDATE_STATE")
        os.environ["RTS_UPDATE_STATE"] = state
        try:
            if not updater.flavor_prompt_due():
                fail("没有记录时应允许提示一次换包")
            updater.mark_auto_checked()
            updater.mark_flavor_prompted()
            if updater.flavor_prompt_due():
                fail("提示过一次后不应再提示")
            if updater.auto_check_due():
                fail("记录换包提示时不应覆盖更新检查的节流时间")
            with open(state, encoding="utf-8") as f:
                st = json.load(f)
            if not st.get("last_check") or not st.get("flavor_prompted"):
                fail(f"状态文件应同时保留两项记录，实际 {st}")
            with open(state, "w", encoding="utf-8") as f:
                f.write("not json")
            if not updater.flavor_prompt_due() or not updater.auto_check_due():
                fail("状态文件损坏时应按“没查过、没提示过”处理")
        finally:
            if old_env is None:
                os.environ.pop("RTS_UPDATE_STATE", None)
            else:
                os.environ["RTS_UPDATE_STATE"] = old_env

        # 首次运行默认配置按能力选设备
        if app_main is not None:
            flavor.nvcuda_available = lambda: True
            if "device: cuda" not in app_main.default_config_text():
                fail("有 CUDA 库 + 有 N 卡 时应默认 cuda")
            flavor.has_cuda_libs = lambda: False
            text = app_main.default_config_text()
            if "device: cpu" not in text or "device: cuda" in text:
                fail("CPU 包（或没有 N 卡）时默认配置应写 cpu/int8")
            if "compute_type: int8" not in text:
                fail("CPU 默认配置的 compute_type 应为 int8")
    finally:
        flavor.has_cuda_libs = real_has_libs
        flavor.nvcuda_available = real_nvcuda
        updater.fetch_release = real_fetch
        shutil.rmtree(tmp, ignore_errors=True)

    record("包型识别与选包（CPU/CUDA、缺包不回退、默认设备）", ok, "; ".join(detail))


# ---------------- 7. 双包打包与剪枝 ----------------


def _load_pkg_module():
    import importlib.util

    path = os.path.join(ROOT, "tools", "package_release.py")
    spec = importlib.util.spec_from_file_location("rts_package_release", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_fake_dist(base):
    """造一个玩具 dist：含 exe、普通 dll 与 CUDA 运行库，外加用户数据（不应进包）。"""
    dist = os.path.join(base, "dist", "实时翻译字幕")
    os.makedirs(os.path.join(dist, "_internal", "nvidia", "cublas", "bin"))
    os.makedirs(os.path.join(dist, "_internal", "PyQt5"))
    os.makedirs(os.path.join(dist, "models", "sensevoice"))
    files = {
        "实时翻译字幕.exe": b"MZ" + b"x" * 5000,
        "_internal/ctranslate2.dll": b"ct" * 2000,
        "_internal/cudnn64_9.dll": b"cd" * 500,
        "_internal/PyQt5/Qt5Core.dll": b"qt" * 900,
        "_internal/nvidia/cublas/bin/cublasLt64_12.dll": b"cb" * 4000,
        "_internal/nvidia/cublas/bin/cublas64_12.dll": b"cb" * 1500,
        "config.yaml": b"whisper:\n  device: cuda\n",
        "app.log": b"log\n",
        "models/sensevoice/model.onnx": b"model",
    }
    for rel, data in files.items():
        with open(os.path.join(dist, rel.replace("/", os.sep)), "wb") as f:
            f.write(data)
    return dist


def check_packaging():
    import json

    from app.updater import compute_prune_list

    ok, detail = True, []

    def fail(msg):
        nonlocal ok
        ok = False
        detail.append(msg)

    tmp = tempfile.mkdtemp(prefix="rts_pkg_")
    try:
        dist = _make_fake_dist(tmp)
        out = os.path.join(tmp, "out")
        os.makedirs(out, exist_ok=True)
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", os.path.join(ROOT, "tools", "package_release.py"),
             "--tag", "v9.9.9", "--dist", dist, "--out", out, "--commit", "abcdef0",
             "--keep-staging"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if proc.returncode != 0:
            fail(f"打包脚本退出码 {proc.returncode}: {(proc.stdout or '')[-300:]} {(proc.stderr or '')[-200:]}")
        cpu_zip = os.path.join(out, "realtime-translate-subtitles-v9.9.9-windows-x64.zip")
        cuda_zip = os.path.join(out, "realtime-translate-subtitles-v9.9.9-windows-x64-cuda.zip")
        if not (os.path.exists(cpu_zip) and os.path.exists(cuda_zip)):
            fail("两个 zip 未生成")
        else:
            with zipfile.ZipFile(cuda_zip) as z:
                cuda_names = set(z.namelist())
            with zipfile.ZipFile(cpu_zip) as z:
                cpu_names = set(z.namelist())
            if os.path.getsize(cpu_zip) >= os.path.getsize(cuda_zip):
                fail("CPU 包不应大于等于 CUDA 包")
            missing = [n for n in cpu_names if n not in cuda_names]
            if missing:
                fail(f"CPU 包出现 CUDA 包里没有的条目: {missing[:3]}")
            if not any("nvidia" in n for n in cuda_names - cpu_names):
                fail("CUDA 包独有内容里应包含 nvidia 运行库")
            if any("config.yaml" in n or "app.log" in n or "models/" in n for n in cuda_names):
                fail("用户数据（配置/日志/模型）不应进包")

            # 换包剪枝：把玩具 dist 当旧安装，CPU 包当新包 → 应清掉 nvidia 下的文件
            install = os.path.join(tmp, "install")
            shutil.copytree(dist, install)
            # 断言基准必须是 realpath：compute_prune_list 内部一律 realpath（防清单里的
            # 相对路径跳出去），而 mkdtemp 给的可能是 8.3 短名（CI 的 runneradmin 就是
            # C:\Users\RUNNER~1\...）——长短名相减会算出 ../../../.. 这种爬升路径
            install_real = os.path.realpath(install)
            staging_cpu = os.path.join(out, ".pkg_staging", "实时翻译字幕")
            files, dirs = compute_prune_list(staging_cpu, install)
            rel = sorted(os.path.relpath(f, install_real).replace("\\", "/") for f in files)
            if rel != ["_internal/nvidia/cublas/bin/cublas64_12.dll",
                       "_internal/nvidia/cublas/bin/cublasLt64_12.dll"]:
                fail(f"CUDA→CPU 待删清单异常: {rel}")
            if any(os.path.basename(d) == "models" for d in dirs):
                fail("剪枝目录里不应出现 models（用户数据）")
            if not dirs or os.path.relpath(dirs[-1], install_real).replace("\\", "/") != "_internal/nvidia":
                fail(f"待删目录应由深到浅、含 _internal/nvidia: {dirs}")
            # 反向（CPU→CUDA）不该删任何东西
            files2, _ = compute_prune_list(dist, staging_cpu)
            if files2:
                fail(f"CPU→CUDA 不应产生待删文件: {files2[:3]}")

            # 旧安装没有清单（≤1.3.9）：按 CUDA 运行库目录兜底清理
            legacy = os.path.join(tmp, "legacy")
            shutil.copytree(dist, legacy)
            for name in ("manifest.json", "flavor.json"):
                p = os.path.join(legacy, name)
                if os.path.exists(p):
                    os.remove(p)
            files3, _ = compute_prune_list(staging_cpu, legacy)
            if len(files3) != 2:
                fail(f"旧安装无清单时应兜底清理 2 个 CUDA 库，实际 {len(files3)}")
            for f in files3:
                if "config.yaml" in f or "app.log" in f:
                    fail("兜底清理不应涉及用户数据")

        # 校验函数本身要能抓出问题（防止它变成永远通过的摆设）
        mod = _load_pkg_module()
        cuda_dir, cpu_dir = os.path.join(tmp, "m_cuda"), os.path.join(tmp, "m_cpu")
        for d, flavor_name in ((cuda_dir, "cuda"), (cpu_dir, "cpu")):
            os.makedirs(os.path.join(d, "_internal"), exist_ok=True)
            with open(os.path.join(d, "实时翻译字幕.exe"), "wb") as f:
                f.write(b"MZ")
            with open(os.path.join(d, "_internal", "a.dll"), "wb") as f:
                f.write(b"A")
            if flavor_name == "cuda":  # CUDA 包独有内容，CPU 包里必须真的没有
                os.makedirs(os.path.join(d, "_internal", "nvidia"), exist_ok=True)
                with open(os.path.join(d, "_internal", "nvidia", "c.dll"), "wb") as f:
                    f.write(b"C")
            manifest = {
                "flavor": flavor_name, "version": "9.9.9", "commit": "abcdef0",
                "files": {"实时翻译字幕.exe": "h1", "_internal/a.dll": "h2"},
            }
            if flavor_name == "cuda":
                manifest["files"]["_internal/nvidia/c.dll"] = "h3"
            with open(os.path.join(d, "manifest.json"), "w", encoding="utf-8") as f:
                json.dump(manifest, f)
        problems = mod.check_consistency(cuda_dir, cpu_dir, "v9.9.9", "abcdef0")
        if problems:
            fail(f"合法的一份包被误判: {problems}")
        cpu_manifest_path = os.path.join(cpu_dir, "manifest.json")
        with open(cpu_manifest_path, encoding="utf-8") as f:
            cpu_m = json.load(f)

        def write_cpu_manifest(payload):
            with open(cpu_manifest_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)

        cpu_m["files"]["_internal/extra.dll"] = "h9"  # CPU 包冒出 CUDA 包里没有的文件
        write_cpu_manifest(cpu_m)
        if not mod.check_consistency(cuda_dir, cpu_dir, "v9.9.9", "abcdef0"):
            fail("CPU 包多出文件时应被判为不一致")

        del cpu_m["files"]["_internal/extra.dll"]
        cpu_m["files"]["_internal/a.dll"] = "DIFFERENT"  # 公共文件内容不一致
        write_cpu_manifest(cpu_m)
        if not mod.check_consistency(cuda_dir, cpu_dir, "v9.9.9", "abcdef0"):
            fail("公共文件内容不一致时应被抓住")

        cpu_m["files"]["_internal/a.dll"] = "h2"  # 先恢复成合法状态
        write_cpu_manifest(cpu_m)
        cuda_manifest_path = os.path.join(cuda_dir, "manifest.json")
        with open(cuda_manifest_path, encoding="utf-8") as fh:
            cuda_m = json.load(fh)
        cuda_m["files"]["_internal/other.dll"] = "h8"  # 差集里出现非 CUDA 运行库
        with open(cuda_manifest_path, "w", encoding="utf-8") as fh:
            json.dump(cuda_m, fh)
        problems = mod.check_consistency(cuda_dir, cpu_dir, "v9.9.9", "abcdef0")
        if not any("非 CUDA 运行库" in p for p in problems):
            fail(f"CUDA 包独有文件不是运行库时应被抓住，实际 {problems}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    record("双包打包与剪枝（派生/清单/一致性校验）", ok, "; ".join(detail))


# ---------------- 8. 下载通道自适应（规划 §9） ----------------


class _ChannelHandler(BaseHTTPRequestHandler):
    """测试用下载通道：按设定速率吐字节，可模拟涓流、忽略 Range 等真实镜像的毛病。"""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass  # 别把测试服务器的访问日志刷到屏幕上

    def do_GET(self):
        cfg = self.server.cfg
        cfg["hits"].append(self.headers.get("Range") or "")
        data = cfg["payload"]
        start, end = 0, len(data) - 1
        status = 200
        rng = self.headers.get("Range")
        if rng and not cfg.get("ignore_range"):
            m = re.match(r"bytes=(\d+)-(\d*)", rng)
            if m:
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else end
                status = 206
        body = data[start:end + 1]
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Accept-Ranges", "none" if cfg.get("ignore_range") else "bytes")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
        self.end_headers()
        sent = 0
        try:
            while sent < len(body):
                rate = cfg["rate"]
                if cfg.get("slow_after") is not None and start + sent >= cfg["slow_after"]:
                    rate = cfg["slow_rate"]
                # 分片大小跟着速率走：慢通道用小块，速度曲线才平滑（否则一觉睡半秒）
                piece = body[sent:sent + max(512, min(4096, rate // 10))]
                self.wfile.write(piece)
                self.wfile.flush()
                sent += len(piece)
                time.sleep(len(piece) / rate)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass  # 客户端换通道会主动断开，属正常现象


def _start_channel(payload, rate=2 << 20, **kw):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _ChannelHandler)
    srv.daemon_threads = True
    srv.cfg = {"payload": payload, "rate": rate, "hits": [], **kw}
    # poll_interval 调小：测试结束要 shutdown 掉一批服务器，默认 0.5s 会白白拖时间
    threading.Thread(target=srv.serve_forever, args=(0.05,), daemon=True).start()
    return srv


def _channel_url(srv, name="a.zip"):
    return f"http://127.0.0.1:{srv.server_address[1]}/{name}"


def check_download_channels():
    import io

    from app import updater

    ok, detail = True, []

    def fail(msg):
        nonlocal ok
        ok = False
        detail.append(msg)

    # 假更新包：必须是合法 zip，才能过完整性校验这一关（store 模式保证体积够大）
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("实时翻译字幕/实时翻译字幕.exe", b"MZ" + b"\0" * 40000,
                    compress_type=zipfile.ZIP_STORED)
    payload = buf.getvalue()
    digest = hashlib.sha256(payload).hexdigest()
    tmp = tempfile.mkdtemp(prefix="rts_chan_")
    state = os.path.join(tmp, "state.json")
    old_mirrors = updater.DOWNLOAD_MIRRORS
    old_env = os.environ.get("RTS_UPDATE_STATE")
    servers = []
    # 测速 0.25 秒、看门狗窗口 0.25 秒、阈值 100 KB/s：桩服务器上几秒内就能跑完全流程
    kw = {"probe_seconds": 0.25, "probe_max_bytes": 8192, "min_speed": 100 << 10,
          "window_s": 0.25, "read_timeout": 5}
    try:
        os.environ["RTS_UPDATE_STATE"] = state
        if os.path.exists(state):
            os.remove(state)

        def make(payload_bytes=payload, **cfg):
            s = _start_channel(payload_bytes, **cfg)
            servers.append(s)
            return s

        def asset(url="a.zip"):
            return {"name": "a.zip", "url": url, "size": len(payload), "digest": digest}

        # ---- 1. 下载前测速：从最快的通道开始 ----
        slow = make(rate=40 << 10)
        fast = make(rate=2 << 20)
        ranked = updater.rate_channels([_channel_url(slow), _channel_url(fast)], None, 0.25, 8192)
        if not ranked or ranked[0][1] != _channel_url(fast):
            fail(f"测速排序错误: {[(round(s), u) for s, u, _ in ranked]}")
        if len(ranked) < 2 or ranked[0][2] is not True:
            fail(f"测速应探明支持续传: {ranked}")
        updater.DOWNLOAD_MIRRORS = [f"http://127.0.0.1:{slow.server_address[1]}/",
                                    f"http://127.0.0.1:{fast.server_address[1]}/"]
        dest = os.path.join(tmp, "a.zip")
        used, err = updater.download_asset(asset(), dest, **kw)
        if err or not used or str(fast.server_address[1]) not in used:
            fail(f"应选中最快的通道，实际 used={used} err={err}")
        if updater.verify_package(dest, digest) is not None:
            fail("下载完成后 sha256 应校验通过")
        if json.load(open(state, encoding="utf-8")).get("last_channel") != _channel_url(fast):
            fail("成功通道未记进 update_state.json（下次更新免测速用）")
        if not slow.cfg["hits"]:
            fail("测速应访问过慢通道")

        # ---- 2. 中途变慢：自动换通道并断点续传（记忆通道热启动路径）----
        os.remove(dest)
        dropping = make(rate=2 << 20, slow_after=16000, slow_rate=40 << 10)  # 开头快，随后涓流
        good = make(rate=2 << 20)
        os.remove(state)
        with open(state, "w", encoding="utf-8") as f:
            # 上次成功用的是这条"会变慢"的通道：本次免测速直接开工
            json.dump({"last_channel": _channel_url(dropping)}, f)
        updater.DOWNLOAD_MIRRORS = [f"http://127.0.0.1:{dropping.server_address[1]}/",
                                    f"http://127.0.0.1:{good.server_address[1]}/"]
        rec = []
        used, err = updater.download_asset(
            asset(), dest, progress_cb=lambda *a: rec.append(a), **kw)
        if err or not used or str(good.server_address[1]) not in used:
            fail(f"通道变慢后应换到第二条，实际 used={used} err={err}")
        if not dropping.cfg["hits"]:
            fail("记忆的通道应被优先使用（免测速热启动）")
        if not [h for h in good.cfg["hits"] if re.fullmatch(r"bytes=[1-9]\d*-", h)]:
            fail(f"换通道时没带 Range 续传: {good.cfg['hits']}")
        if updater.verify_package(dest, digest) is not None:
            fail("换通道续传后 sha256 应校验通过")
        if not rec or rec[-1][1] != len(payload):
            fail(f"进度回调应报出完整字节数: {rec[-1] if rec else None}")
        if any(not isinstance(r[4], str) or r[5] < 0 for r in rec):
            fail("进度回调应带上通道名与实测速度")

        # ---- 3. 通道忽略 Range（返回 200）：不丢进度，换能续传的通道 ----
        os.remove(state)
        os.remove(dest)
        # 先"下"了一部分再中断（模拟上次下载没完成），重试时应当接着下
        with open(dest, "wb") as f:
            f.write(payload[:10240])
        noresume = make(rate=2 << 20, ignore_range=True)  # 最快但忽略 Range
        resumable = make(rate=300 << 10)
        updater.DOWNLOAD_MIRRORS = [f"http://127.0.0.1:{noresume.server_address[1]}/",
                                    f"http://127.0.0.1:{resumable.server_address[1]}/"]
        used, err = updater.download_asset(asset(), dest, **kw)
        if err or not used or str(resumable.server_address[1]) not in used:
            fail(f"不支持的通道应被跳过、由能续传的接手: used={used} err={err}")
        if not any(h.startswith("bytes=10240-") for h in resumable.cfg["hits"]):
            fail(f"续传起点应是已有进度 10240: {resumable.cfg['hits']}")
        if updater.verify_package(dest, digest) is not None:
            fail("续传完成后的包应校验通过")

        # ---- 4. 所有通道都慢：退回最快的一条硬下（最坏情况不比旧版差）----
        os.remove(state)
        os.remove(dest)
        buf2 = io.BytesIO()
        with zipfile.ZipFile(buf2, "w") as zf:
            zf.writestr("实时翻译字幕/实时翻译字幕.exe", b"MZ" + b"\0" * 6000,
                        compress_type=zipfile.ZIP_STORED)
        tiny = buf2.getvalue()
        a = make(tiny, rate=40 << 10)
        b = make(tiny, rate=20 << 10)
        updater.DOWNLOAD_MIRRORS = [f"http://127.0.0.1:{a.server_address[1]}/",
                                    f"http://127.0.0.1:{b.server_address[1]}/"]
        used, err = updater.download_asset(
            {"name": "a.zip", "url": "a.zip", "size": len(tiny),
             "digest": hashlib.sha256(tiny).hexdigest()},
            dest, **kw)
        if err or not used:
            fail(f"全通道都慢时也要把包下完（退回最快通道）: used={used} err={err}")
        elif updater.verify_package(dest, hashlib.sha256(tiny).hexdigest()) is not None:
            fail("退回最快通道后文件应完整且校验通过")

        # ---- 5. 已下一大截 + 只剩忽略 Range 的通道：作废进度从零重下（不能变成"下不下来"）----
        os.remove(state)
        os.remove(dest)
        with open(dest, "wb") as f:
            f.write(payload[:10240])
        # 把"重来还是换通道"的门槛压到 1KB，让这点进度就算"下了一大截"（真实阈值 16 MB / 15%）
        old_max, old_ratio = updater.RESTART_MAX_BYTES, updater.RESTART_MAX_RATIO
        updater.RESTART_MAX_BYTES, updater.RESTART_MAX_RATIO = 1024, 0.0
        try:
            only = make(rate=2 << 20, ignore_range=True)
            updater.DOWNLOAD_MIRRORS = [f"http://127.0.0.1:{only.server_address[1]}/"]
            used, err = updater.download_asset(asset(), dest, **kw)
        finally:
            updater.RESTART_MAX_BYTES, updater.RESTART_MAX_RATIO = old_max, old_ratio
        if err or not used:
            fail(f"只剩忽略 Range 的通道时也要把包下完（从零重下）: used={used} err={err}")
        elif updater.verify_package(dest, digest) is not None:
            fail("从零重下后的包应完整且校验通过")

        # ---- 6. 取消：立刻返回并删掉半成品 ----
        os.remove(state)
        os.remove(dest)
        slow2 = make(rate=8 << 10)
        updater.DOWNLOAD_MIRRORS = [f"http://127.0.0.1:{slow2.server_address[1]}/"]
        cancel = threading.Event()
        cancel.set()
        used, err = updater.download_asset(asset(), dest, cancel=cancel, **kw)
        if used is not None or err != "已取消":
            fail(f"已取消的下载应立即返回: used={used} err={err}")
    finally:
        updater.DOWNLOAD_MIRRORS = old_mirrors
        if old_env is None:
            os.environ.pop("RTS_UPDATE_STATE", None)
        else:
            os.environ["RTS_UPDATE_STATE"] = old_env
        for s in servers:
            s.shutdown()
            s.server_close()
        shutil.rmtree(tmp, ignore_errors=True)

    record("下载通道自适应（测速选路/滚动看门狗/断点续传/兜底）", ok, "; ".join(detail))


# ---------------- 9. 模型下载进度（规划 §3） ----------------


def check_model_download():
    from app import model_download as md

    ok, detail = True, []

    def fail(msg):
        nonlocal ok
        ok = False
        detail.append(msg)

    events = []
    old_reporter = md._reporter
    # 本检查故意制造两次失败（下载失败回退、加载失败），日志里的告警堆栈是预期输出
    import logging

    noisy = [logging.getLogger(n) for n in ("subtitle", "subtitle.model_download")]
    old_levels = [lg.level for lg in noisy]
    for lg in noisy:
        lg.setLevel(logging.CRITICAL)
    tmp = tempfile.mkdtemp(prefix="rts_md_")
    model_dir = os.path.join(tmp, "whisper-small")
    os.makedirs(model_dir, exist_ok=True)
    with open(os.path.join(model_dir, "model.bin"), "wb") as f:
        f.write(b"x")
    try:
        md.set_reporter(lambda *a: events.append(a))

        # ---- 1. 字节汇总：聚合条（多文件）取最大值，单文件条（先后出现）累加 ----
        sess = md._Session("测试")
        with md._session_active(sess):
            agg1 = md.ProgressTqdm(desc="Downloading bytes", total=0, initial=0, unit="B")
            agg2 = md.ProgressTqdm(desc="Reconstructing", total=0, initial=0, unit="B")
            agg1.total = agg2.total = 300          # 库会就地累加 .total（各文件大小之和）
            agg1.update(100)
            agg2.update(100)
            if sess.totals() != (100, 300):
                fail(f"聚合条应取最大值（不能翻倍）: {sess.totals()}")
            files = md.ProgressTqdm(desc="Fetching 2 files", total=2)
            files.update(1)
            if sess.totals() != (100, 300):
                fail(f"按文件数的进度条不该计入字节: {sess.totals()}")
        with md._session_active(md._Session("测试2")):
            b1 = md.ProgressTqdm(desc="tokens.txt", total=100, unit="B")
            b1.update(60)
            b1.close()
            b2 = md.ProgressTqdm(desc="model.int8.onnx", total=50, initial=10, unit="B")
            b2.update(20)
            if b2._session.totals() != (90, 150):
                fail(f"先后出现的单文件条应累加: {b2._session.totals()}")

        # ---- 2. 阶段上报：立即送达；纯进度更新受节流 ----
        events.clear()
        md.report_stage("load", "语音识别模型")
        if events != [("load", "语音识别模型", 0, 0)]:
            fail(f"阶段变化应立即上报: {events}")
        md._last_report = time.time()
        md._emit("download", "X", 1, 2)
        if events != [("load", "语音识别模型", 0, 0)]:
            fail("紧接着的进度更新应被节流丢弃")
        md._emit("download", "X", 3, 4, force=True)
        if len(events) != 2:
            fail("force 上报不应被节流")

        # ---- 3. whisper 预下载：替换 faster-whisper 内部被禁用的进度条类 ----
        try:
            import faster_whisper.utils as fw_utils
        except ImportError:
            detail.append("（未安装 faster-whisper，跳过 whisper 预下载检查）")
            fw_utils = None
        if fw_utils is not None:
            seen = {}
            origin_download = fw_utils.download_model
            origin_tqdm = fw_utils.disabled_tqdm

            def fake_download(size_or_id, *a, **kw):
                seen["arg"] = size_or_id
                seen["tqdm"] = fw_utils.disabled_tqdm
                return model_dir

            try:
                fw_utils.download_model = fake_download
                got = md.ensure_whisper_model("small", "语音识别模型")
                if got != model_dir:
                    fail(f"预下载成功应返回本地目录（WhisperModel 见到目录不会再下载）: {got}")
                if seen.get("tqdm") is not md.ProgressTqdm:
                    fail("下载期间应把 faster-whisper 禁用的进度条换成我们的实现")
                if seen.get("arg") != "small":
                    fail(f"应把档位名原样交给 faster-whisper: {seen.get('arg')}")

                # 目录不完整 → 交回原路径（不能让进度功能变成新的失败点）
                seen.clear()
                got = md.ensure_whisper_model("small", "语音识别模型")
                if got != model_dir:
                    fail("第二次应直接命中缓存目录")

                def broken(size_or_id, *a, **kw):
                    raise RuntimeError("模拟下载失败")

                fw_utils.download_model = broken
                if md.ensure_whisper_model("small", "语音识别模型") is not None:
                    fail("下载失败时应返回 None，交给原有加载路径处理")
                seen.clear()
                fw_utils.download_model = fake_download
                if md.ensure_whisper_model(tmp, "语音识别模型") is not None:
                    fail("本地目录不该触发下载")
                if seen:
                    fail("本地目录不该调用 faster-whisper 的下载")
            finally:
                fw_utils.download_model = origin_download
                fw_utils.disabled_tqdm = origin_tqdm
                if fw_utils.disabled_tqdm is not origin_tqdm:
                    fail("用完后必须把 faster-whisper 的进度条类还原")

        # ---- 4. Transcriber 把预下载的目录交给 WhisperModel（依赖重，CI 跳过）----
        try:
            import app.transcriber as transcriber_mod
        except ImportError:
            detail.append("（无 faster-whisper/ctranslate2，跳过 Transcriber 接线检查）")
        else:
            used = []

            class FakeModel:
                def __init__(self, model, **kw):
                    used.append(model)

                def transcribe(self, *a, **kw):
                    raise RuntimeError("warmup 失败无所谓")

            origin_cls = transcriber_mod.WhisperModel
            origin_ensure = transcriber_mod.ensure_whisper_model
            try:
                transcriber_mod.WhisperModel = FakeModel
                transcriber_mod.ensure_whisper_model = lambda size, label: model_dir
                transcriber_mod.Transcriber("small")
                if used != [model_dir]:
                    fail(f"Transcriber 应用预下载好的本地目录，实际: {used}")
                used.clear()
                transcriber_mod.ensure_whisper_model = lambda size, label: None
                transcriber_mod.Transcriber("small")
                if used != ["small"]:
                    fail(f"预下载不可用时应回退到档位名，实际: {used}")
            finally:
                transcriber_mod.WhisperModel = origin_cls
                transcriber_mod.ensure_whisper_model = origin_ensure
    finally:
        md.set_reporter(old_reporter)
        for lg, lv in zip(noisy, old_levels):
            lg.setLevel(lv)
        shutil.rmtree(tmp, ignore_errors=True)

    record("模型下载进度（三段状态/字节汇总/whisper 缓存复用）", ok, "; ".join(detail))


# ---------------- 10. 术语表（规划 §5.1） ----------------


def check_glossary():
    """术语表：解析容错、注入大模型 system prompt、并进识别提示词，留空时零影响。"""
    try:
        from app.translator import build_chain, glossary
        from app.translator.llm_api import LlmApiTranslator, _system_prompt
    except ImportError as e:
        record("术语表（解析/注入/留空零影响）", True, f"跳过（本环境缺依赖 {getattr(e, 'name', e)}）")
        return

    ok, detail = True, []

    def fail(msg):
        nonlocal ok
        ok = False
        detail.append(msg)

    # ---- 1. 解析：列表/整段文本都收，空行、# 注释、行尾注释、没等号、重复条目都要挡住 ----
    pairs = glossary.parse([
        "原神=Genshin Impact",
        "",
        "# 注释行",
        "  元素爆发 = Elemental Burst  ",
        "没有等号",
        "原神=重复的应被丢掉",
        "C#=C井",  # 术语里的 # 不能被当成注释
        "派蒙=Paimon  # 行尾注释",
    ])
    want = [("原神", "Genshin Impact"), ("元素爆发", "Elemental Burst"),
            ("C#", "C井"), ("派蒙", "Paimon")]
    if pairs != want:
        fail(f"解析结果不符: {pairs}")
    if glossary.parse("原神=Genshin\n\n# x\n派蒙=Paimon") != [("原神", "Genshin"), ("派蒙", "Paimon")]:
        fail("整段多行文本形态没解析对")
    if glossary.parse(None) or glossary.parse([]):
        fail("空配置应解析为空表")
    if glossary.parse(["=空原文", "空译文=", "   =   ", "原神=Genshin Impact"]) != [("原神", "Genshin Impact")]:
        fail("原文或译文为空的行应被丢掉")
    long_src = "字" * (glossary.MAX_TERM_CHARS + 1)
    if glossary.parse([f"{long_src}=X"]):
        fail("超长词条应被丢掉")
    many = [f"词{i}=T{i}" for i in range(glossary.MAX_ENTRIES + 50)]
    if len(glossary.parse(many)) != glossary.MAX_ENTRIES:
        fail(f"词条数应封顶在 {glossary.MAX_ENTRIES}")

    # ---- 2. 注入 system prompt：没词条时与 v1.3.9 逐字相同（留空零影响）----
    base = _system_prompt("zh")
    if "术语对照" in base:
        fail("没有术语表时不应出现术语提示")
    rules = glossary.rules_text(["原神=Genshin Impact", "元素爆发=Elemental Burst"])
    if "原神=Genshin Impact" not in rules or "元素爆发=Elemental Burst" not in rules:
        fail(f"术语规则文本没带上词条: {rules!r}")
    prompted = _system_prompt("zh", rules)
    if not prompted.startswith(base) or not prompted.endswith(rules):
        fail("带术语表的提示词应是原提示词 + 术语片段")
    if _system_prompt("zh", glossary.rules_text([])) != base:
        fail("空术语表拼出来的提示词必须和原来一致")

    # ---- 3. 后端接线：术语表要真的传到 llm_api 后端（translator.glossary → 构造参数）----
    chain = build_chain({
        "order": ["llm_api"],
        "glossary": ["原神=Genshin Impact"],
        "llm_api": {"base_url": "http://127.0.0.1:1/v1", "api_key": "k", "model": "m"},
    })
    try:
        backend = chain.backends[0]
        if not isinstance(backend, LlmApiTranslator):
            fail(f"应构建出大模型后端，实际 {backend.name}")
        elif "原神=Genshin Impact" not in backend.glossary_rules:
            fail("术语表没传进大模型后端")
        elif "术语对照" not in backend._messages("hello", "zh")[0]["content"]:
            fail("大模型请求的 system 提示词里没有术语表")
    finally:
        chain.close()

    # ---- 4. 识别提示词：用户提示词 + 术语原文，两者都空时返回 None（与旧行为一致）----
    cfg = {"whisper": {"prompt": "原神 派蒙"},
           "translator": {"glossary": ["元素爆发=Elemental Burst", "风之翼=Wind Glider"]}}
    got = glossary.recognition_prompt(cfg)
    if got != "原神 派蒙 元素爆发 风之翼":
        fail(f"识别提示词拼接不符: {got!r}")
    if glossary.recognition_prompt({"whisper": {"prompt": "   "}, "translator": {}}) is not None:
        fail("没有任何提示词时应返回 None（保持旧行为）")
    if glossary.recognition_prompt({"translator": {"glossary": ["原神=Genshin Impact"]}}) != "原神":
        fail("只有术语表时应只喂术语原文")
    if len(glossary.source_terms([f"很长的词条{i}" for i in range(80)])) > glossary.MAX_TERMS_CHARS:
        fail("识别提示词里的术语部分应截断")

    # ---- 5. 界面：必须写清"仅大模型后端生效"，且保存时要落进配置 ----
    src = open(os.path.join(ROOT, "app", "settings_window.py"), encoding="utf-8").read()
    if "只对“大模型 API”后端生效" not in src:
        fail("设置页缺少“仅大模型后端生效”的说明（用户会以为有道/Google 也吃词典）")
    if 't["glossary"]' not in src:
        fail("设置页保存时没把术语表写回配置")

    record("术语表（解析/注入/留空零影响）", ok, "; ".join(detail))


# ---------------- 11. 音频电平 / VAD 状态指示（规划 §5.2） ----------------


class _FakeRecorder:
    """假录音器：按脚本吐音频块，用来在不接真声卡的情况下验证电平与看门狗行为。"""

    def __init__(self, blocks):
        self.blocks = blocks
        self.i = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def record(self, numframes):
        block = self.blocks[min(self.i, len(self.blocks) - 1)]
        self.i += 1
        return block


class _FakeDevice:
    def __init__(self, blocks):
        self.blocks = blocks
        self.name = "假音频设备"

    def recorder(self, samplerate, channels, blocksize):
        return _FakeRecorder(self.blocks)


def check_audio_level():
    """音频电平（捕获线程自记、界面只读、不抢队列）+ VAD 说话状态回调。"""
    try:
        import queue

        import numpy as np

        from app.audio_capture import BLOCK_SIZE, AudioCapture
        from app import vad as vad_mod
    except ImportError as e:
        record("音频电平与 VAD 状态（不抢队列/状态回调）", True,
               f"跳过（本环境缺依赖 {getattr(e, 'name', e)}）")
        return

    ok, detail = True, []

    def fail(msg):
        nonlocal ok
        ok = False
        detail.append(msg)

    loud = np.full((BLOCK_SIZE, 1), 0.5, dtype=np.float32)
    quiet = np.zeros((BLOCK_SIZE, 1), dtype=np.float32)

    # ---- 1. 电平：有声音就抬起来，静音后自己降下去（界面刷新比音频块慢，必须峰值保持）----
    cap = AudioCapture(device=_FakeDevice([loud] * 20), out_queue=queue.Queue(maxsize=200))
    cap.start()
    try:
        t0 = time.time()
        while time.time() - t0 < 2 and cap.last_level < 0.4:
            time.sleep(0.01)
        if cap.last_level < 0.4:
            fail(f"有声音时电平没抬起来: {cap.last_level:.3f}")
        # 换成静音：电平应衰减（不是立刻归零，也不是一直不降）。
        # 就地改这个列表——录音器持有的是同一个对象，换新列表它看不见
        cap.device.blocks[:] = [quiet] * 20
        time.sleep(0.2)
        if cap.last_level > 0.2:
            fail(f"静音后电平没降下来: {cap.last_level:.3f}")
    finally:
        cap.stop()

    # ---- 2. 电平不消费队列（红线：从队列取音频 = 抢主流水线的帧）----
    q = queue.Queue(maxsize=200)
    cap2 = AudioCapture(device=_FakeDevice([loud] * 20), out_queue=q)
    cap2.start()
    try:
        t0 = time.time()
        while time.time() - t0 < 2 and q.qsize() < 3:
            time.sleep(0.01)
        before = q.qsize()
        for _ in range(5):
            cap2.last_level  # 界面读电平时只读字段
        if q.qsize() != before:
            fail(f"读电平动到了音频队列: {before} → {q.qsize()}")
    finally:
        cap2.stop()

    # ---- 3. VAD 状态回调：开始说话 → True，段落结束 → False，且状态不变时不重复回调 ----
    states = []
    real_vad = vad_mod.SileroVad

    class StubVad:
        """按脚本给概率的假 VAD，省掉 onnxruntime 与模型文件。"""

        def __init__(self, probs):
            self.probs = probs
            self.i = 0

        def speech_prob(self, frame):
            p = self.probs[min(self.i, len(self.probs) - 1)]
            self.i += 1
            return p

        def reset(self):
            pass

    try:
        seg = vad_mod.VadSegmenter(on_segment=lambda s: None, on_state=states.append,
                                   threshold=0.5, min_speech_ms=64, min_silence_ms=64,
                                   padding_ms=32)
        seg.vad = StubVad([0.9] * 10)
        for _ in range(10):
            seg.feed(quiet[:, 0])
        if states != [True]:
            fail(f"说话状态回调不对: {states}（应只有一次 True）")
        seg.vad = StubVad([0.0] * 10)  # 静音够长 → 段落结束
        for _ in range(10):
            seg.feed(quiet[:, 0])
        if states != [True, False]:
            fail(f"段落结束后应回调 False: {states}")
        seg.feed(quiet[:, 0])
        if states != [True, False]:
            fail(f"状态没变化时不该重复回调: {states}")

        # 回调抛异常不能把 VAD 线程带走（回调在 VAD 线程上跑）
        def boom(_):
            raise RuntimeError("界面炸了")

        seg2 = vad_mod.VadSegmenter(on_segment=lambda s: None, on_state=boom, threshold=0.5,
                                    min_speech_ms=64, min_silence_ms=64, padding_ms=32)
        seg2.vad = StubVad([0.9])
        vlog = logging.getLogger("subtitle.vad")
        vlevel = vlog.level
        vlog.setLevel(logging.CRITICAL)  # 这条告警是本检查故意制造的
        try:
            seg2.feed(quiet[:, 0])
        except Exception as e:
            fail(f"状态回调抛异常时应被吞掉，实际冒泡: {e}")
        finally:
            vlog.setLevel(vlevel)
    finally:
        vad_mod.SileroVad = real_vad

    # ---- 4. 流水线对外只读接口：不消费队列，且停下时不再报"正在说话" ----
    try:
        import main as app_main
    except ImportError as e:
        detail.append(f"跳过流水线接口检查（缺依赖 {getattr(e, 'name', e)}）")
    else:
        pipe = app_main.Pipeline({"whisper": {}, "translator": {}, "audio": {}, "vad": {}},
                                 lambda payload: None)
        pipe._cap = cap2
        pipe._speech = True
        before = cap2.queue.qsize()
        level, speaking, listening = pipe.audio_status()
        if cap2.queue.qsize() != before:
            fail("流水线读音频状态时动了队列（红线）")
        if not listening or not speaking or level <= 0:
            fail(f"音频状态快照不对: {(level, speaking, listening)}")
        pipe._cap = None
        if pipe.audio_status()[2]:
            fail("没在监听时不应报 listening=True")

    record("音频电平与 VAD 状态（不抢队列/状态回调）", ok, "; ".join(detail))


# ---------------- 12. PyAV 空壳（规划 §1.3） ----------------


def check_av_stub():
    """打包剔掉 PyAV（av + av.libs，65 MB）的前提：导入照常成功、真解码才报错。

    验证方式：就地执行打包用的运行时钩子，把 sys.modules["av"] 换成空壳，
    再重新导入 faster_whisper.audio —— 导入必须成功（它的 import 在导入期），
    decode_audio() 必须抛一个说得清原因的错误。用完把真的 av 绑回去。
    """
    try:
        import importlib
        import sys as _sys

        import faster_whisper.audio as fw_audio  # noqa: F401
    except ImportError as e:
        record("PyAV 空壳（导入可用/调用报错）", True, f"跳过（本环境缺依赖 {getattr(e, 'name', e)}）")
        return

    ok, detail = True, []

    def fail(msg):
        nonlocal ok
        ok = False
        detail.append(msg)

    hook = os.path.join(ROOT, "tools", "pyi_rth_no_av.py")
    saved = _sys.modules.get("av")
    try:
        with open(hook, encoding="utf-8") as f:
            exec(compile(f.read(), hook, "exec"), {"__name__": "pyi_rth_no_av"})
        stub = _sys.modules.get("av")
        if stub is saved:
            fail("空壳没顶掉真的 av")
        # 空壳对外表现：import 成功（已由上面证明）、调用即报错、dunder 不拦
        try:
            stub.open
            fail("空壳的 av.open 居然能用")
        except RuntimeError as e:
            if "PyAV" not in str(e):
                fail(f"空壳报错不说人话: {e}")
        except Exception as e:
            fail(f"空壳应报 RuntimeError，实际 {type(e).__name__}: {e}")
        try:
            stub.__some_dunder__
            fail("空壳不该拦 dunder（打包工具/拷贝会问）")
        except AttributeError:
            pass
        # 关键：装上空壳后 faster_whisper.audio 仍要能导入（导入期就 import av）
        importlib.reload(fw_audio)
        try:
            fw_audio.decode_audio("不存在的文件.mp3")
            fail("装了空壳还能解码音频？")
        except RuntimeError as e:
            if "PyAV" not in str(e):
                fail(f"解码报错不说人话: {e}")
        except Exception as e:
            fail(f"解码应报 RuntimeError，实际 {type(e).__name__}: {e}")
    finally:
        if saved is not None:
            _sys.modules["av"] = saved
        else:
            _sys.modules.pop("av", None)
        try:
            importlib.reload(fw_audio)  # 把真的 av 绑回去，别影响后续检查
        except Exception:
            fail("还原真 av 后没法重新导入 faster_whisper.audio")

    # 打包配置确实挂了这个钩子、也确实排除了 av（改一处忘另一处就白省 65 MB）
    spec = open(os.path.join(ROOT, "subtitle.spec"), encoding="utf-8").read()
    if "pyi_rth_no_av" not in spec:
        fail("subtitle.spec 没挂 PyAV 空壳运行时钩子")
    if '"av"' not in spec:
        fail('subtitle.spec 没把 "av" 加进 excludes')

    # 空壳成立的前提：本应用自己从不解码音频文件（哪天要解码了，这段得跟着改）
    for src in ("main.py",) + tuple(glob.glob(os.path.join(ROOT, "app", "*.py"))) + \
            tuple(glob.glob(os.path.join(ROOT, "app", "translator", "*.py"))):
        with open(src, encoding="utf-8") as f:
            if "decode_audio" in f.read():
                fail(f"{os.path.relpath(src, ROOT)} 用到了 decode_audio——剔掉 PyAV 会让它炸")

    record("PyAV 空壳（导入可用/调用报错）", ok, "; ".join(detail))


def check_i18n():
    """界面多语言覆盖：`tr("字面量")` 必须都在 i18n_strings.py 里注册。

    漏了不会报错——`tr` 找不到键就原样返回中文（安全降级），英文界面里悄悄冒出中文，
    只能靠人肉翻界面才发现。实测踩过：v1.4.0 的包型/换包提示整段没注册。
    只查字面量；`tr(变量)` 查不了（那类键在调用点本来就看不到）。
    """
    import ast

    ok, detail = True, []
    src = os.path.join(ROOT, "app", "i18n_strings.py")
    keys = set()
    for n in ast.walk(ast.parse(open(src, encoding="utf-8").read())):
        if isinstance(n, ast.Dict):
            for k in n.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    keys.add(k.value)
    if not keys:
        record("界面多语言覆盖（tr 字面量都已注册）", False, "i18n_strings.py 里一个键都没解析出来")
        return

    files = [os.path.join(ROOT, "main.py")]
    for dp, dn, fn in os.walk(os.path.join(ROOT, "app")):
        dn[:] = [d for d in dn if d != "__pycache__"]
        files += [os.path.join(dp, f) for f in fn
                  if f.endswith(".py") and f != "i18n_strings.py"]

    missing = {}
    for p in files:
        try:
            tree = ast.parse(open(p, encoding="utf-8").read())
        except SyntaxError as e:
            ok = False
            detail.append(f"{os.path.relpath(p, ROOT)} 解析失败: {e}")
            continue
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == "tr" and n.args):
                a = n.args[0]
                if (isinstance(a, ast.Constant) and isinstance(a.value, str)
                        and a.value not in keys):
                    missing.setdefault(a.value, []).append(f"{os.path.relpath(p, ROOT)}:{n.lineno}")

    if missing:
        ok = False
        shown = [f"{k[:30]}{'…' if len(k) > 30 else ''}（{len(v)} 处，如 {v[0]}）"
                 for k, v in list(missing.items())[:5]]
        detail.append(f"{len(missing)} 条未注册：" + "；".join(shown))
    record("界面多语言覆盖（tr 字面量都已注册）", ok, "; ".join(detail))


def check_ocr_lang():
    """截图翻译的语言判定：脚本判据 + 多引擎选择（用例全是实机 OCR 的真实输出串）。

    纯函数检查：不 import PyQt5/winsdk（那些在 app/ocr_tool.py 里），
    CI 只装 requests 也能真跑，不会退化成"跳过"。
    """
    try:
        from app.lang_detect import choose_ocr_text, detect_script
    except ImportError as e:
        record("截图语言判定（脚本判据 + 多引擎选择）", True,
               f"跳过（本环境缺依赖 {getattr(e, 'name', e)}）")
        return

    ok, detail = True, []

    def fail(msg):
        nonlocal ok
        ok = False
        detail.append(msg)

    # 判据：右侧全是 1100×70 渲染样图在 zh-Hans-CN / ja-JP 两个引擎上的真实输出
    for want, text in [
        ("ja", "こんにちは、今日はいい天気ですね。一緒に学校へ行きましょう。"),
        (None, "乙 、 今 日 00 天 氦 ℃ 稳 。 一 緒 学 校 八 行 岂 0 0 。"),  # 中文引擎读日语（乱码）
        ("ja", "コーヒーとケーキをください。"),
        (None, "匕 一 亡 一 丰 < 芑 0 。"),                                # 中文引擎读片假名
        (None, "東京大学医学部附属病院"),                                   # 纯汉字：中日同形，判不了
        ("zh", "今天天气很好，我们一起去学校吧。"),
        (None, "今 天 天 气 很 好 , 我 們 - 起 去 学 校 ロ 巴 。"),           # 日语引擎读中文
        ("ja", "そうですね、わかりました"),
        ("ko", "안녕하세요, 오늘 날씨가 좋네요."),
        ("ru", "Привет, мир! Сегодня хорошая погода."),
        # 证据不足一律不判（宁可不判也不误判）：短文本、纯汉字、拉丁、数字
        (None, "はい"), (None, "今日は"), (None, "あ"), (None, ""),
        (None, "Hello world"), (None, "2026-10-11 12:30"),
    ]:
        got = detect_script(text)
        if got != want:
            fail(f"detect_script({text[:20]!r}) = {got!r}，期望 {want!r}")

    # 日文新字体与简体同形的字（学 国 会 体 医 来 万 与 …）不许当简体证据：
    # 一旦把日语判成 zh，而目标语言也是 zh，翻译链会「源=目标直接回显」，日语原文会
    # 被当成译文显示——静默且看起来像"翻译坏了"
    if detect_script("学生が学校へ行きます") != "ja":
        fail("含「学生/学校」的日语没判成日语——简体字表混进了中日同形字")
    if detect_script("我們一起去看這部電影") == "zh":
        fail("繁体中文被判成了简体（繁体该交给后端 auto，才有繁→简的机会）")

    # 多引擎选择：{引擎标签: 文本} → (选中文本, 判定语言)
    zh_ok, ja_ok = "今天天气很好，我们一起去学校吧。", "こんにちは、今日はいい天気ですね。"
    zh_junk, ja_junk = "乙 、 今 日 00 天 氦 ℃ 稳 。", "今 天 天 气 很 好 , 我 們 - 起 去 学 校 ロ 巴 。"
    for results, profile, want, note in [
        ({"zh-Hans-CN": zh_ok, "ja": ja_junk}, "zh-Hans-CN", (zh_ok, "zh"), "中文串胜出"),
        ({"zh-Hans-CN": zh_junk, "ja": ja_ok}, "zh-Hans-CN", (ja_ok, "ja"), "日语串胜出"),
        ({"zh-Hans-CN": "東京大学医学部附属病院", "ja": "東京大学医学部附属病院"},
         "zh-Hans-CN", ("東京大学医学部附属病院", None), "纯汉字→不判定、用默认引擎"),
        ({"en-US": "hello"}, "en-US", ("hello", None), "拉丁→默认引擎"),
        ({"zh-Hans-CN": "??", "ko": "안녕하세요"}, "zh-Hans-CN", ("안녕하세요", "ko"), "韩语胜出"),
        ({}, None, ("", None), "全空"),
    ]:
        got = choose_ocr_text(results, profile)
        if got != want:
            fail(f"choose_ocr_text（{note}）= {got!r}，期望 {want!r}")

    # 接线（防重构时接错线）：auto 分支必须真的走多引擎，判据模块必须顶层导入
    sources = {}
    for rel in ("main.py", "app/ocr_tool.py", "app/lang_detect.py"):
        with open(os.path.join(ROOT, rel.replace("/", os.sep)), encoding="utf-8") as f:
            sources[rel] = f.read()
    if "ocr_image_multi" not in sources["main.py"]:
        fail("main.py 的自动检测分支没接 ocr_image_multi")
    if "def ocr_image_multi" not in sources["app/ocr_tool.py"]:
        fail("app/ocr_tool.py 里没有 ocr_image_multi")
    if "from .lang_detect import" not in sources["app/ocr_tool.py"]:
        fail("ocr_tool.py 必须顶层导入 lang_detect（函数内导入会被 PyInstaller 漏收）")

    # lang_detect 必须保持零第三方依赖，否则 CI（只装 requests）里本检查会静默跳过
    import ast

    for n in ast.walk(ast.parse(sources["app/lang_detect.py"])):
        mods = []
        if isinstance(n, ast.Import):
            mods = [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom) and not n.level:
            mods = [n.module or ""]
        for m in mods:
            if m.split(".")[0] not in ("re", "__future__"):
                fail(f"app/lang_detect.py 引入了第三方依赖 {m}（CI 上会没法跑）")

    record("截图语言判定（脚本判据 + 多引擎选择）", ok, "; ".join(detail))


# ---------------- 13. GUI 回归（子进程） ----------------

GUI_TESTS = [
    ("热键重绑回归", "tools/test_hotkey_rebind.py", 120),
    ("字幕窗点击穿透", "tools/test_click_through.py", 60),
    ("截图冻结帧与裁剪", "tools/test_ocr_frozen.py", 60),
    ("术语表界面读写", "tools/test_glossary_ui.py", 60),
    ("音频电平指示", "tools/test_audio_level_ui.py", 60),
]


def check_gui():
    for name, script, timeout in GUI_TESTS:
        env = dict(os.environ)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        try:
            proc = subprocess.run(
                [sys.executable, "-X", "utf8", os.path.join(ROOT, script)],
                cwd=ROOT, env=env, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            record(name, False, f"超时（>{timeout}s）")
            continue
        if proc.returncode == 0:
            record(name, True)
        else:
            tail = [ln for ln in (proc.stdout or "").strip().splitlines() if ln.strip()][-3:]
            err = [ln for ln in (proc.stderr or "").strip().splitlines() if ln.strip()][-3:]
            record(name, False, f"exit={proc.returncode} | " + " / ".join(tail + err))


# ---------------- 入口 ----------------


def main():
    parser = argparse.ArgumentParser(description="项目回归检查")
    parser.add_argument("--no-gui", action="store_true", help="跳过 GUI 回归（CI/无桌面环境）")
    args = parser.parse_args()

    t0 = time.time()
    print(f"项目目录: {ROOT}")
    # 每项独立兜底：某一项自己抛异常（而不是 return fail）时，剩下的项照跑，
    # 一次性看全所有问题，而不是修一个跑一次
    for fn in (check_syntax, check_updater, check_translator, check_llm_context,
               check_live_caption, check_snapshot_pacing, check_config_template,
               check_partial_backend, check_pipeline_stats, check_asr_repeat,
               check_flavor, check_packaging, check_download_channels,
               check_model_download, check_glossary, check_audio_level,
               check_av_stub, check_i18n, check_ocr_lang):
        try:
            fn()
        except Exception:
            record(fn.__name__, False, "检查自身异常: " + traceback.format_exc().strip().splitlines()[-1])
            traceback.print_exc()
    if args.no_gui:
        print("（--no-gui：跳过 GUI 回归）")
    else:
        check_gui()

    failed = [r for r in results if not r[1]]
    print(f"\n共 {len(results)} 项，失败 {len(failed)} 项，用时 {time.time() - t0:.1f}s")
    if failed:
        for name, _, d in failed:
            print(f"  FAIL {name}: {d}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
