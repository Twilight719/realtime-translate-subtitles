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
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

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

    record("翻译回退链（回退/冷却/空译文/close）", ok, "; ".join(detail))


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
    st.update("今日はいい天気ですね", "ja")
    p2 = st.update("今日はいい天気ですね。散歩しましょう", "ja")
    if p2["src_stable"] != "今日はいい天気で":
        fail(f"CJK 前缀确认异常: {p2['src_stable']!r}")
    if not p2["zh_stable"]:
        fail("确认区译文为空")

    p3 = st.update("今日はいい天気ですね。散歩しましょう", "ja")
    if not p3["src_stable"].startswith(p2["src_stable"]):
        fail("确认区应当只增不减/前缀稳定")

    n = len(calls)
    st.update("今日はいい天気ですね。散歩しましょう", "ja")  # 尾部没变
    if len(calls) != n:
        fail("尾部未变化时不应重复调用翻译")

    st.reset()
    if st.confirmed_src or st.confirmed_zh or st.prev_text:
        fail("reset 未清空状态")

    # 空格分词语言：只确认到完整词边界，不确认半个词
    st2 = LiveCaptionState(fake_translate)
    st2.update("hello world foo", "en")
    p = st2.update("hello world foo bar baz", "en")
    if p["src_stable"] != "hello world":
        fail(f"英文词边界确认异常: {p['src_stable']!r}")

    # 翻译抛异常时不能把整条流水线带崩
    def boom(text, lang):
        raise RuntimeError("boom")

    st3 = LiveCaptionState(boom)
    try:
        p = st3.update("こんにちは、いい天気ですね", "ja")
        if p["zh_tail"] != "…":
            fail(f"翻译失败时应回退占位符: {p['zh_tail']!r}")
    except Exception as e:
        fail(f"翻译失败不应向外抛异常: {e!r}")

    record("实时字幕状态机（前缀确认/尾部缓存/异常兜底）", ok, "; ".join(detail))


# ---------------- 6. GUI 回归（子进程） ----------------

GUI_TESTS = [
    ("热键重绑回归", "tools/test_hotkey_rebind.py", 120),
    ("字幕窗点击穿透", "tools/test_click_through.py", 60),
    ("截图冻结帧与裁剪", "tools/test_ocr_frozen.py", 60),
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
    check_syntax()
    check_updater()
    check_translator()
    check_llm_context()
    check_live_caption()
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
