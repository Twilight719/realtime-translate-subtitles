# -*- coding: utf-8 -*-
"""模拟 CI 环境（只装了 requests）跑一遍 run_checks --no-gui。"""
import importlib.abc
import os
import sys

BLOCK = {"onnxruntime", "faster_whisper", "PyQt5", "ruamel", "soundcard", "truststore",
         "numpy", "ctranslate2", "sherpa_onnx", "av", "huggingface_hub"}


class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCK:
            raise ImportError("CI 模拟：没有安装 %s" % name, name=name)
        return None


sys.meta_path.insert(0, Blocker())
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(root)
sys.path.insert(0, root)
sys.argv = ["run_checks.py", "--no-gui"]
code = open(os.path.join(root, "tools", "run_checks.py"), encoding="utf-8").read()
exec(compile(code, "tools/run_checks.py", "exec"), {"__name__": "__main__", "__file__": "tools/run_checks.py"})
