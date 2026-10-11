"""PyInstaller 运行时钩子：把 PyAV（av）换成"能 import、调用即报错"的空壳（规划 §1.3）。

为什么能砍：`faster_whisper/audio.py` 只是**在导入期** `import av`（为了导出
decode_audio），所有 `av.*` 调用都在 `decode_audio()` 函数体里；本应用的声音
来自 WASAPI 捕获、从不解码音频文件，所以 PyAV 及其自带的 FFmpeg 库
（av + av.libs，约 129 MB）可以整个不打包。

为什么必须是"空壳"而不是直接 exclude 掉：不留任何模块的话 `import av` 会抛
ImportError，而 `faster_whisper/__init__.py` 第一行就 import 它 → 识别引擎直接
起不来。空壳保证导入照常成功，真去解码时才抛一个说得清原因的错误。
"""

import sys
import types

_HELP = ("本安装包已移除 PyAV（av）及其 FFmpeg 库以减小体积，"
         "本应用不解码音频文件（声音由 WASAPI 捕获）。装了完整源码版可恢复该功能。")


class _AvStub(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            # dunder（__spec__/__path__/__all__ 等）照常 AttributeError：
            # 拷贝、pickle、打包工具都会来问，拦下来只会制造怪问题
            raise AttributeError(name)
        raise RuntimeError(f"av.{name} 不可用：{_HELP}")


sys.modules["av"] = _AvStub("av")
