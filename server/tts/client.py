"""TTS 客户端：双通道。

- edge（默认）：微软 Edge-TTS，免费免注册，零配置可用
- volcano：火山引擎语音合成，音质/情感更好，需要 APP_ID + ACCESS_TOKEN

通过 .env 的 TTS_PROVIDER 切换；统一返回 base64 编码的 mp3。
"""
import base64
import uuid

import httpx

from config import settings

# 情绪 -> Edge-TTS 语速/音调微调
EDGE_PROSODY = {
    "happy": ("+8%", "+10Hz"),
    "shy": ("-5%", "+5Hz"),
    "tsundere": ("+5%", "+8Hz"),
    "sad": ("-12%", "-10Hz"),
    "angry": ("+10%", "-5Hz"),
    "surprised": ("+12%", "+15Hz"),
    "relaxed": ("-5%", "+0Hz"),
    "calm": ("+0%", "+0Hz"),
}

# 情绪 -> 火山 emotion 参数
VOLCANO_EMOTION = {
    "happy": "happy", "tsundere": "happy", "shy": "happy",
    "surprised": "surprise", "sad": "sad", "angry": "angry",
    "calm": "calm", "relaxed": "calm",
}

VOLCANO_URL = "https://openspeech.bytedance.com/api/v1/tts"


def _combine(base: str, offset: str) -> str:
    """合并全局与情绪的语调偏移，如 '+10Hz' 与 '-8Hz' -> '+2Hz'。"""
    unit = "%" if base.endswith("%") else "Hz"
    total = int(base[:-len(unit)]) + int(offset[:-len(unit)])
    return f"{total:+d}{unit}"


class TTSClient:
    def __init__(self):
        self.provider = settings.TTS_PROVIDER
        if self.provider == "volcano" and not (
                settings.TTS_APP_ID and settings.TTS_ACCESS_TOKEN):
            print("[TTS] 火山凭证未配置，回退到 edge")
            self.provider = "edge"

    async def synthesize(self, text: str, emotion: str = "calm") -> str | None:
        """合成语音，返回 base64 mp3；失败返回 None（不阻断对话）。"""
        if not text.strip():
            return None
        try:
            if self.provider == "volcano":
                return await self._volcano(text, emotion)
            return await self._edge(text, emotion)
        except Exception as exc:
            print(f"[TTS] 合成异常({self.provider}): {exc}")
            return None

    async def _edge(self, text: str, emotion: str) -> str | None:
        import edge_tts

        erate, epitch = EDGE_PROSODY.get(emotion, EDGE_PROSODY["calm"])
        rate = _combine(settings.TTS_EDGE_RATE, erate)
        pitch = _combine(settings.TTS_EDGE_PITCH, epitch)
        communicate = edge_tts.Communicate(
            text, settings.TTS_EDGE_VOICE, rate=rate, pitch=pitch)
        chunks = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.extend(chunk["data"])
        if not chunks:
            return None
        return base64.b64encode(bytes(chunks)).decode()

    async def _volcano(self, text: str, emotion: str) -> str | None:
        payload = {
            "app": {
                "appid": settings.TTS_APP_ID,
                "token": settings.TTS_ACCESS_TOKEN,
                "cluster": settings.TTS_CLUSTER,
            },
            "user": {"uid": "virtual-girlfriend"},
            "audio": {
                "voice_type": settings.TTS_VOICE,
                "encoding": "mp3",
                "emotion": VOLCANO_EMOTION.get(emotion, "calm"),
            },
            "request": {
                "reqid": str(uuid.uuid4()),
                "text": text,
                "operation": "query",
            },
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                VOLCANO_URL,
                headers={"Authorization": f"Bearer;{settings.TTS_ACCESS_TOKEN}"},
                json=payload,
            )
            data = resp.json()
            if "data" not in data:
                print(f"[TTS] 火山合成失败: {data.get('message', data)}")
            return data.get("data")
