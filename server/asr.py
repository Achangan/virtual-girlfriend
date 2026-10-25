"""服务端语音识别：faster-whisper 本地模型，首次使用自动下载（走国内镜像）。"""
import io
import os

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")  # xet 存储不走镜像会 401，禁用后走普通下载

from config import settings

_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        print(f"[ASR] 加载模型 {settings.ASR_MODEL}（首次需下载）...", flush=True)
        _model = WhisperModel(settings.ASR_MODEL, device="cpu", compute_type="int8")
        print("[ASR] 模型就绪", flush=True)
    return _model


def transcribe(data: bytes) -> str:
    """把浏览器录制的音频（webm/opus、ogg、mp3 等）转成中文文字。"""
    import av
    import numpy as np

    container = av.open(io.BytesIO(data))
    resampler = av.AudioResampler(format="flt", layout="mono", rate=16000)
    pcm = []
    for frame in container.decode(audio=0):
        for resampled in resampler.resample(frame):
            pcm.append(resampled.to_ndarray().reshape(-1))
    if not pcm:
        return ""

    audio = np.concatenate(pcm).astype("float32")
    if len(audio) < 3200:  # 不足 0.2 秒，视为杂音
        return ""

    segments, _ = _get_model().transcribe(
        audio, language="zh", beam_size=5, vad_filter=True)
    return "".join(seg.text for seg in segments).strip()
