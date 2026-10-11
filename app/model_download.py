"""模型下载的统一进度上报（规划 §3）。

whisper（约 460MB）/ SenseVoice（约 230MB）/ NLLB（约 600MB）三个模型首次使用时
都要下载，过去只有一条"正在加载模型…"的静止提示，用户不知道是在下载、卡住了还是
已经失败。这里把三者的下载进度统一成一条回调，界面据此显示
"下载中：x/y MB（z%）→ 加载中 → 就绪"三段状态（字幕条 + 设置页）。

三家的下载体各不相同，所以各有各的接法：

- **whisper**：faster-whisper 内部调 huggingface_hub 下载，而且 `download_model()`
  里**硬编码** `tqdm_class=disabled_tqdm`（它自己不想要进度条）。它在调用时才从
  `faster_whisper.utils` 模块取这个名字，所以临时替换掉那个类就能拿到进度，
  其余（仓库映射、缓存目录、文件清单、local_files_only 语义）**完全保持原样**——
  缓存命中时不会重下一次；返回的本地目录直接交给 WhisperModel，
  它见到目录就不再走下载分支（`os.path.isdir` 判断），天然不会重复下载。
- **SenseVoice**：`hf_hub_download`，直接传 `tqdm_class`。
- **NLLB**：`snapshot_download`，直接传 `tqdm_class`。

回调由上层（main.py）用 `set_reporter()` 注册，签名：
`reporter(阶段, 名称, 已下字节, 总字节)`，阶段 ∈ {"download", "load", "ready"}；
名称为中文标签（"识别模型" 等），由界面层再经 tr() 翻译。上报做了节流（见
`_THROTTLE_S`），不会因为每 256KB 一次而淹没 GUI 线程。
"""

import fnmatch
import logging
import os
import threading
import time

log = logging.getLogger("subtitle.model_download")

_THROTTLE_S = 0.3  # 进度上报的最小间隔（阶段切换不受限）

_reporter = None
_callback_lock = threading.Lock()
_last_report = 0.0


def set_reporter(fn):
    """注册进度回调 `fn(阶段, 名称, 已下字节, 总字节)`；None = 不上报。"""
    global _reporter
    with _callback_lock:
        _reporter = fn


def _emit(stage, label, done, total, force=False):
    """把一次进度/阶段变化交给回调（节流：太频繁的纯进度更新会被丢掉）。"""
    global _last_report
    with _callback_lock:
        fn = _reporter
        now = time.time()
        if fn is None:
            return
        if not force and now - _last_report < _THROTTLE_S:
            return
        _last_report = now
    try:
        fn(stage, label, int(done), int(total))
    except Exception:
        log.warning("模型进度上报失败（不影响下载）", exc_info=True)


def report_stage(stage, label):
    """阶段变化（"load" 加载中 / "ready" 就绪）：立即上报，不受节流限制。"""
    _emit(stage, label, 0, 0, force=True)


# ---------------- 会话：把 huggingface_hub 的进度条折算成字节数 ----------------

_current = None  # 当前下载会话（同时只会有一个：模型加载在主线程/单一工作线程里串行）


class _Session:
    """一次下载的进度汇总。

    huggingface_hub 1.x 会创建两类"按字节"的进度条（其余按文件数的不关心）：
    - **聚合条**：`snapshot_download` 用它汇总整个仓库的多文件下载（以 total=0 创建，
      随后把每个文件的大小累加到 `.total` 上）；
    - **单文件条**：每个文件一条，先后依次出现（前一条 close 再开下一条）。
    聚合条们（下载/落盘各一条）报的是同一份字节，直接求和会翻倍，所以取最大值；
    单文件条则累加。`total` 直接从进度条对象上读（库会就地改它）。
    """

    def __init__(self, label, announce_total=0):
        self.label = label
        self.announce_total = announce_total or 0
        self.bars = []
        self.lock = threading.Lock()

    def add(self, bar):
        with self.lock:
            self.bars.append(bar)

    def totals(self):
        with self.lock:
            agg = [b for b in self.bars if b.aggregate]
            if agg:
                done = max(b.n for b in agg)
                total = max(b.total or 0 for b in agg)
            else:
                done = sum(b.n for b in self.bars)
                total = sum(b.total or 0 for b in self.bars)
        return done, max(total, self.announce_total)


class ProgressTqdm:
    """冒充 tqdm 交给 huggingface_hub 的 `tqdm_class`（详见 `_Session` 的说明）。

    必须能接住 tqdm 的各种参数与方法调用（不同版本调用的方法不一样），
    认不出的方法一律当空操作，绝不因为它影响下载本身。
    """

    def __init__(self, *args, **kwargs):
        total = kwargs.get("total")
        self.n = kwargs.get("initial") or 0
        self.total = total
        # 聚合条以 total=0 创建后由库自己累加；单文件条一创建就带着自己的大小
        self.aggregate = total == 0
        self._session = _current if kwargs.get("unit") == "B" else None
        self._lock = threading.Lock()
        if self._session is not None:
            self._session.add(self)

    # --- tqdm 的关键接口 ---
    def update(self, n=1):
        with self._lock:
            self.n += n or 0
        if self._session is not None:
            done, total = self._session.totals()
            _emit("download", self._session.label, done, total)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    # --- 其余方法（set_description / set_postfix / refresh / unpause / update_transfer…）---
    def __getattr__(self, name):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return lambda *a, **kw: None


class _session_active:
    """进入一次下载会话（嵌套时恢复上一层，互不干扰）。"""

    def __init__(self, session):
        self.session = session
        self.prev = None

    def __enter__(self):
        global _current
        self.prev, _current = _current, self.session
        return self.session

    def __exit__(self, *exc):
        global _current
        _current = self.prev
        return False


# ---------------- 三个模型的下载入口 ----------------


def _repo_total_bytes(repo_id, allow_patterns=None):
    """仓库（或其中匹配 allow_patterns 的文件）的总字节数——尽力而为。

    只是为了让进度条一开始就有个稳定的分母；拿不到（接口变化/网络异常）就返回 0，
    上层会自动改用下载库自己上报的总量。
    """
    try:
        from huggingface_hub import HfApi

        info = HfApi().model_info(repo_id, files_metadata=True)
        total = 0
        for sib in getattr(info, "siblings", None) or []:
            name = getattr(sib, "rfilename", None) or getattr(sib, "path", "") or ""
            if allow_patterns and not any(fnmatch.fnmatch(name, p) for p in allow_patterns):
                continue
            total += getattr(sib, "size", 0) or 0
        return total
    except Exception:
        log.debug("取仓库体积失败（不影响下载，进度条分母会稍后由下载库补上）", exc_info=True)
        return 0


def ensure_whisper_model(model_size, label="识别模型"):
    """按 faster-whisper 自己的下载路径把识别模型准备好，返回本地目录。

    失败/不可用一律返回 None，调用方按老办法（把档位名交给 WhisperModel）继续，
    行为与 v1.3.9 完全一致——进度显示只是"锦上添花"，绝不能成为新的失败点。
    """
    if os.path.isdir(model_size):  # 配置里直接写的是本地目录：无需下载
        return None
    try:
        import faster_whisper.utils as fw_utils
    except ImportError:
        return None
    if not hasattr(fw_utils, "disabled_tqdm"):
        return None
    repo_id = fw_utils._MODELS.get(model_size, model_size)
    session = _Session(label, announce_total=_repo_total_bytes(repo_id))
    old_tqdm, fw_utils.disabled_tqdm = fw_utils.disabled_tqdm, ProgressTqdm
    try:
        with _session_active(session):
            path = fw_utils.download_model(model_size)
    except Exception:
        log.warning("预下载识别模型失败，回退到原加载路径（WhisperModel 自己会再试）", exc_info=True)
        return None
    finally:
        fw_utils.disabled_tqdm = old_tqdm
    if path and os.path.isfile(os.path.join(path, "model.bin")):
        log.info("识别模型已就绪: %s", path)
        return path
    log.warning("识别模型目录不完整（缺 model.bin），回退到原加载路径: %s", path)
    return None


def download_file_with_progress(repo_id, filename, local_dir, label):
    """`hf_hub_download` + 进度（SenseVoice 的两个文件）。"""
    from huggingface_hub import hf_hub_download

    session = _Session(label)
    with _session_active(session):
        try:
            return hf_hub_download(repo_id, filename, local_dir=local_dir,
                                   tqdm_class=ProgressTqdm)
        except TypeError:  # 老版本 huggingface_hub 不收 tqdm_class：退回不带进度的下载
            log.info("当前 huggingface_hub 不支持自定义进度条，本次下载不显示进度")
            return hf_hub_download(repo_id, filename, local_dir=local_dir)


def download_repo_with_progress(repo_id, local_dir, label):
    """`snapshot_download` + 进度（NLLB 整个仓库）。"""
    from huggingface_hub import snapshot_download

    session = _Session(label, announce_total=_repo_total_bytes(repo_id))
    with _session_active(session):
        try:
            return snapshot_download(repo_id, local_dir=local_dir, tqdm_class=ProgressTqdm)
        except TypeError:
            log.info("当前 huggingface_hub 不支持自定义进度条，本次下载不显示进度")
            return snapshot_download(repo_id, local_dir=local_dir)
