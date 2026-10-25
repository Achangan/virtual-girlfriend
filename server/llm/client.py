"""LLM 客户端：OpenAI 兼容协议（DeepSeek/豆包均可），要求 JSON 输出。

未配置 LLM_API_KEY 时返回占位回复，保证骨架无密钥也能跑通链路。
"""
import json

import httpx

from config import settings


class LLMClient:
    def __init__(self):
        self.enabled = bool(settings.LLM_API_KEY)

    async def chat(self, messages: list[dict]) -> str:
        """返回 LLM 原始文本（约定为 JSON 字符串）。"""
        if not self.enabled:
            return json.dumps({
                "text": "（还没配置 LLM_API_KEY 哦，去项目根目录 .env 里填好再来找我~）",
                "emotion": "calm",
                "intensity": 0.3,
            }, ensure_ascii=False)
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{settings.LLM_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"},
                json={
                    "model": settings.LLM_MODEL,
                    "messages": messages,
                    "response_format": {"type": "json_object"},
                    "temperature": 0.8,
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
