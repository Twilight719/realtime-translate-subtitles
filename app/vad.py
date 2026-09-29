"""silero VAD（ONNX 版）：检测人声，把连续语音切成片段。

直接使用 faster-whisper 包自带的 silero_vad_v6.onnx（无需联网下载）。
v6 模型接口：输入 input(1, 576) = 64 采样上下文 + 512 采样帧，状态 h/c (1,1,128)。
"""

import os

import faster_whisper  # 仅用于定位自带的 VAD 模型文件（开发环境/打包后都有效）
import numpy as np
import onnxruntime  # 顶层导入：避免多线程并发加载原生扩展导致段错误

MODEL_PATH = os.path.join(
    os.path.dirname(faster_whisper.__file__), "assets", "silero_vad_v6.onnx"
)

SAMPLE_RATE = 16000
WINDOW = 512       # v6 要求的帧长（32ms）
CONTEXT = 64       # v6 要求的上下文采样数


class SileroVad:
    """单帧（512 采样点 / 32ms）人声概率检测，状态跨帧保持。"""

    def __init__(self, model_path=MODEL_PATH):
        opts = onnxruntime.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.log_severity_level = 4
        self.session = onnxruntime.InferenceSession(
            model_path, sess_options=opts, providers=["CPUExecutionProvider"]
        )
        self.reset()

    def reset(self):
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, CONTEXT), dtype=np.float32)

    def speech_prob(self, frame_512):
        """frame_512: float32 (512,) → 返回 0~1 的人声概率。"""
        x = np.concatenate([self._context, frame_512[np.newaxis, :]], axis=1)
        out, h, c = self.session.run(
            None, {"input": x, "h": self._h, "c": self._c}
        )
        self._h, self._c = h, c
        self._context = frame_512[np.newaxis, -CONTEXT:]
        return float(out.reshape(-1)[0])


class VadSegmenter:
    """把音频帧流切分成语音片段。

    回调 on_segment(ndarray float32) 在每个完整语音片段结束时触发。
    """

    FRAME_MS = 32  # 每帧毫秒数（512 / 16000）

    def __init__(
        self,
        on_segment,
        on_partial=None,
        threshold=0.5,
        min_speech_ms=250,
        min_silence_ms=400,
        max_segment_s=12,
        padding_ms=200,
        partial_interval_s=2.5,
    ):
        self.vad = SileroVad()
        self.on_segment = on_segment
        self.on_partial = on_partial
        self.threshold = threshold
        self.min_speech_frames = max(1, round(min_speech_ms / self.FRAME_MS))
        self.min_silence_frames = max(1, round(min_silence_ms / self.FRAME_MS))
        self.max_frames = round(max_segment_s * 1000 / self.FRAME_MS)
        self.padding_frames = max(1, round(padding_ms / self.FRAME_MS))
        self.partial_frames = max(1, round(partial_interval_s * 1000 / self.FRAME_MS))
        self.reset()

    def reset(self):
        self._buffer = []
        self._pre_buffer = []
        self._speaking = False
        self._silence_run = 0
        self._last_partial = 0

    def feed(self, frame_512):
        prob = self.vad.speech_prob(frame_512)
        if not self._speaking:
            self._pre_buffer.append(frame_512)
            if len(self._pre_buffer) > self.padding_frames:
                self._pre_buffer.pop(0)
            if prob >= self.threshold:
                self._speaking = True
                self._buffer = list(self._pre_buffer)
                self._silence_run = 0
        else:
            self._buffer.append(frame_512)
            if prob < self.threshold:
                self._silence_run += 1
            else:
                self._silence_run = 0
            if self._silence_run >= self.min_silence_frames or len(self._buffer) >= self.max_frames:
                self._emit()
            elif (
                self.on_partial
                and self._silence_run < 3
                and len(self._buffer) - self._last_partial >= self.partial_frames
            ):
                # 说话过程中的增量快照：让字幕边说边出，不等段落结束
                self._last_partial = len(self._buffer)
                self.on_partial(np.concatenate(self._buffer))

    def flush(self):
        """停止捕获时，把未完成的片段也发出去。"""
        if self._speaking and self._buffer:
            self._emit()

    def _emit(self):
        speech_frames = len(self._buffer) - self._silence_run
        if speech_frames >= self.min_speech_frames:
            segment = np.concatenate(self._buffer)
            self.on_segment(segment)
        self.vad.reset()
        self.reset()


if __name__ == "__main__":
    # 自测：播放语音时应打印每个语音片段的时长
    import time

    from app.audio_capture import AudioCapture

    t0 = time.time()

    def on_segment(seg):
        print(f"[{time.time() - t0:6.1f}s] 语音片段: {len(seg) / SAMPLE_RATE:.2f} 秒")

    s = VadSegmenter(on_segment)
    cap = AudioCapture()
    cap.start()
    print("开始监听 20 秒，请播放外语语音...")
    try:
        end = time.time() + 20
        while time.time() < end:
            s.feed(cap.queue.get(timeout=1))
    except KeyboardInterrupt:
        pass
    finally:
        cap.stop()
    print("结束")
