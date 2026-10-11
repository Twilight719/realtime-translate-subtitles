# -*- coding: utf-8 -*-
"""冻结包探针：从 subtitle.spec 派生一个探针包，验证剪枝（av / hf_xet / nvrtc…）没把 import 链剪断。

    ./.venv/Scripts/python.exe -X utf8 tools/probe_frozen_pack.py [--work C:/rtbuild]

为什么单开一个：`run_checks` 里的 PyAV 空壳检查跑在**源码环境**（往 sys.modules 里塞空壳），
而打包环境里 av 是**整个不存在**——只有真构建一次，才能证明 `faster_whisper.audio`
的导入链、以及应用的识别模块在缺 av 的冻结环境里照样能起来。
探针包只跑 import 与"调用即抛错"的断言，不开窗口、不碰音频、不联网，随时可跑。

注意：项目路径不能含中文（Qt 算出的插件路径会错，见 README「自己打包 exe」），
所以默认借一个纯英文目录当构建车间（默认 C:\\rtbuild，须已备好 .venv 与 PyInstaller）。
车间目录里的源码每次都会被本脚本刷新，不会有"改了代码却在测旧包"的问题。
"""
import argparse
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 探针本体：模拟应用真实的导入链（main.py 顶层就 import faster_whisper，
# app.transcriber 也一样），只砍掉 Qt 与音频设备
PROBE = '''"""探针（由 tools/probe_frozen_pack.py 生成，勿手改）。"""
import os
import sys

ok = True


def check(label, fn):
    global ok
    try:
        print(f"  OK   {label} -> {fn()}")
    except Exception as e:
        ok = False
        print(f"  FAIL {label}: {type(e).__name__}: {e}")


def _no_av_files():
    d = os.path.join(os.path.dirname(sys.executable), "_internal")
    hit = [n for n in os.listdir(d) if n.startswith("av")]
    if hit:
        raise AssertionError(f"包内仍带 {hit}")
    return "包内无 av/av.libs"


def _av_module():
    import av
    return type(av).__name__


def _av_call():
    import av
    try:
        av.open("x.wav")
    except RuntimeError as e:
        return f"调用抛 RuntimeError（{str(e)[:32]}…）"
    raise AssertionError("空壳没拦住 av.open")


def _fw():
    import faster_whisper
    return faster_whisper.__version__


def _decode():
    from faster_whisper.audio import decode_audio
    try:
        decode_audio("x.wav")
    except RuntimeError as e:
        return f"调用抛 RuntimeError（{str(e)[:32]}…）"
    raise AssertionError("decode_audio 居然没报错")


def _engines():
    import ctranslate2
    import onnxruntime
    from app import transcriber, model_download, sensevoice_engine   # noqa: F401
    return (f"ctranslate2 {ctranslate2.__version__} / onnxruntime {onnxruntime.__version__}"
            " / 应用识别模块 OK")


check("包内无 av 文件", _no_av_files)
check("import av（空壳）", _av_module)
check("av.open 被拦下", _av_call)
check("import faster_whisper", _fw)
check("decode_audio 被拦下", _decode)
check("识别引擎与应用模块", _engines)
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
'''

# 车间目录里必须齐的源码（其余如 .venv/dist/config.yaml 留在原样，不动）
SOURCES = [("subtitle.spec", "subtitle.spec"), ("assets/icon.ico", "assets/icon.ico")]


def sync(work):
    """把仓库源码刷进车间目录（不含 .venv 等），返回刷了多少个文件。"""
    n = 0
    for src, dst in SOURCES:
        d = os.path.join(work, dst)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copyfile(os.path.join(ROOT, src), d)
        n += 1
    for sub in ("app", "tools"):
        for dp, dn, fn in os.walk(os.path.join(ROOT, sub)):
            dn[:] = [x for x in dn if x != "__pycache__"]
            for f in fn:
                if not f.endswith(".py"):
                    continue
                rel = os.path.relpath(os.path.join(dp, f), ROOT)
                d = os.path.join(work, rel)
                os.makedirs(os.path.dirname(d), exist_ok=True)
                shutil.copyfile(os.path.join(ROOT, rel), d)
                n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default=r"C:\rtbuild",
                    help="纯英文的构建车间目录（须已有 .venv 与 PyInstaller）")
    args = ap.parse_args()
    work = os.path.abspath(args.work)
    py = os.path.join(work, ".venv", "Scripts", "python.exe")
    if not os.path.exists(py):
        print(f"车间目录里没有 {py}；先按 README「自己打包 exe」把项目和 .venv 放过去")
        return 2
    if subprocess.run([py, "-c", "import PyInstaller"], capture_output=True).returncode:
        print(f"{py} 里没装 PyInstaller；在车间目录跑一次 build.bat 或 pip install pyinstaller")
        return 2

    # 车间里的 venv 要跟 build.bat 一样补上 sitecustomize（Qt/onnxruntime 加载顺序）
    shutil.copyfile(os.path.join(ROOT, "tools", "sitecustomize_pyi.py"),
                    os.path.join(work, ".venv", "Lib", "site-packages", "sitecustomize.py"))

    spec = open(os.path.join(ROOT, "subtitle.spec"), encoding="utf-8").read()
    probe_spec = spec.replace('["main.py"]', '["probe_av.py"]')
    assert probe_spec != spec, "subtitle.spec 的入口不是 [\"main.py\"]，入口替换失败"
    probe_spec = probe_spec.replace('name="实时翻译字幕",\n    debug=False',
                                    'name="av_probe",\n    debug=False')
    probe_spec = probe_spec.replace('console=False,  # 无控制台窗口（调试打包问题时可临时改 True）',
                                    'console=True,')
    probe_spec = probe_spec.replace('name="实时翻译字幕",\n)', 'name="av_probe",\n)')
    assert 'name="av_probe"' in probe_spec, "EXE/COLLECT 名字替换失败，spec 结构可能变了"

    if work != ROOT:            # 路径本来就是纯英文时可以直接在仓库里构建
        print(f"刷源码到车间目录：{sync(work)} 个文件 -> {work}")
    open(os.path.join(work, "probe_av.py"), "w", encoding="utf-8").write(PROBE)
    open(os.path.join(work, "probe_av.spec"), "w", encoding="utf-8").write(probe_spec)

    env = dict(os.environ, PYI_SAFE_IMPORT="1")
    print("构建探针包（约 1~2 分钟）…")
    r = subprocess.run([py, "-m", "PyInstaller", "--noconfirm", "--clean",
                        "--distpath", "dist_probe", "--workpath", "build_probe",
                        "probe_av.spec"], cwd=work, env=env)
    if r.returncode:
        print(f"PyInstaller 失败（exit {r.returncode}），日志见 {work}\\build_probe")
        return r.returncode

    exe = os.path.join(work, "dist_probe", "av_probe", "av_probe.exe")
    print(f"跑探针：{exe}")
    return subprocess.run([exe]).returncode


if __name__ == "__main__":
    sys.exit(main())
