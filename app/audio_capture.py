"""WASAPI loopback 音频捕获：抓系统声音，输出 16kHz 单声道 float32 流。"""

import logging
import queue
import threading
import time

import numpy as np
import soundcard as sc

log = logging.getLogger("subtitle.audio")

SAMPLE_RATE = 16000
BLOCK_SIZE = 512  # 每次回调的音频块（32ms），与 VAD 帧长一致


def list_loopback_devices():
    """返回所有可用的 loopback（扬声器回环）设备。"""
    devices = []
    for mic in sc.all_microphones(include_loopback=True):
        if mic.isloopback:
            devices.append(mic)
    return devices


def list_input_devices():
    """返回所有真实麦克风（非 loopback）。"""
    return [m for m in sc.all_microphones(include_loopback=False) if not m.isloopback]


def get_default_loopback():
    speaker = sc.default_speaker()
    return sc.get_microphone(speaker.id, include_loopback=True)


def get_default_input():
    return sc.default_microphone()


class AudioCapture:
    """在后台线程中持续捕获 loopback 音频，重采样后推入队列。"""

    def __init__(self, device=None, out_queue=None):
        self.device = device if device is not None else get_default_loopback()
        self.queue = out_queue if out_queue is not None else queue.Queue(maxsize=200)
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self):
        # WASAPI 共享模式会按请求的采样率自动重采样，直接以 16kHz 录制。
        # record() 可能因音频服务重启/设备被独占抢占/系统休眠等抛异常，
        # 这里自动重建录音器重试（指数退避），避免捕获线程无声死亡、
        # 软件"听不到声音"只能重启监听的已知问题。
        backoff = 1.0
        while not self._stop.is_set():
            try:
                with self.device.recorder(samplerate=SAMPLE_RATE, channels=2, blocksize=BLOCK_SIZE) as rec:
                    backoff = 1.0  # 录音器建立成功，重置退避
                    while not self._stop.is_set():
                        data = rec.record(numframes=BLOCK_SIZE)
                        chunk = data.mean(axis=1).astype(np.float32)
                        if len(chunk) < BLOCK_SIZE:
                            chunk = np.pad(chunk, (0, BLOCK_SIZE - len(chunk)))
                        try:
                            self.queue.put_nowait(chunk)
                        except queue.Full:
                            pass  # 下游处理不过来时丢帧，避免音频线程阻塞
            except Exception as e:
                if self._stop.is_set():
                    break
                log.warning("音频捕获中断（%.0fs 后自动重连）: %s", backoff, e)
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 15)

    def is_alive(self):
        """捕获线程是否还活着（供看门狗检测）。"""
        return self._thread is not None and self._thread.is_alive()


if __name__ == "__main__":
    # 自测：打印音量电平，播放声音时应看到数值变化
    import time

    devs = list_loopback_devices()
    print("可用 loopback 设备:")
    for i, d in enumerate(devs):
        print(f"  [{i}] {d.name}")

    cap = AudioCapture()
    cap.start()
    print("开始捕获 10 秒，请播放声音...")
    try:
        for _ in range(333):
            chunk = cap.queue.get(timeout=1)
            level = np.abs(chunk).max()
            bar = "#" * int(level * 100)
            print(f"\r{level:.3f} {bar:<50}", end="", flush=True)
            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        cap.stop()
    print("\n结束")
