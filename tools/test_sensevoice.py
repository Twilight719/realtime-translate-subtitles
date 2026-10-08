import sys, time, wave
sys.path.insert(0, r"D:\翻译插件")
import numpy as np, sherpa_onnx

t0 = time.time()
rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
    model=r"D:\翻译插件\models\sensevoice\model.int8.onnx",
    tokens=r"D:\翻译插件\models\sensevoice\tokens.txt",
    num_threads=2, use_itn=True, language="auto", debug=False,
)
print(f"load: {time.time()-t0:.1f}s")

with wave.open(r"D:\翻译插件\models\sensevoice\test_wavs\ja.wav") as w:
    sr, n, ch = w.getframerate(), w.getnframes(), w.getnchannels()
    raw = w.readframes(n)
wav = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
if ch > 1:
    wav = wav.reshape(-1, ch).mean(axis=1)
if sr != 16000:
    from scipy.signal import resample
    wav = resample(wav, int(len(wav) * 16000 / sr)).astype(np.float32)
dur = len(wav) / 16000
print(f"audio: {dur:.1f}s sr={sr}")

t0 = time.time()
s = rec.create_stream()
s.accept_waveform(16000, wav)
rec.decode_stream(s)
dt = time.time() - t0
print(f"decode: {dt:.2f}s  (RTF={dt/dur:.3f})")
print("raw result:", repr(s.result.text))
