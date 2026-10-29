"""LLM 客户端：本地 QLoRA 模型（WSL）优先，DeepSeek 等 OpenAI 兼容 API 兜底。

LLM_PROVIDER=local 时先请求本地服务，失败自动回退 API；LLM_PROVIDER=api 时直接走 API。
均未配置时返回占位回复，保证骨架无密钥也能跑通链路。
"""
import json

import httpx

from config import settings


class LLMClient:
    def __init__(self):
        self.provider = settings.LLM_PROVIDER
        self.api_enabled = bool(settings.LLM_API_KEY)
        self.enabled = self.api_enabled or self.provider == "local"

    async def chat(self, messages: list[dict]) -> str:
        """返回 LLM 原始文本（约定为 JSON 字符串）。"""
        if self.provider == "local":
            try:
                return await self._request(
                    settings.LLM_LOCAL_URL, None, "zixi-qlora", messages, timeout=120)
            except Exception as e:
                print(f"[LLM] 本地模型不可用，回退 API: {e}", flush=True)
                if not self.api_enabled:
                    return self._fallback("（本地模型服务没启动哦，先运行 start_local_llm.bat~）")
        if self.api_enabled:
            try:
                return await self._request(
                    settings.LLM_BASE_URL, settings.LLM_API_KEY,
                    settings.LLM_MODEL, messages, timeout=60)
            except Exception as e:
                print(f"[LLM] API 请求失败: {e}", flush=True)
                return self._fallback("（网络好像不太好，等我缓缓再聊~）")
        return self._fallback("（还没配置 LLM_API_KEY 哦，去项目根目录 .env 里填好再来找我~）")

    @staticmethod
    async def _request(base_url, api_key, model, messages, timeout):
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json={
                    "model": model,
                    "messages": messages,
                    "response_format": {"type": "json_object"},
                    "temperature": 0.8,
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    @staticmethod
    def _fallback(text):
        return json.dumps(
            {"text": text, "emotion": "calm", "intensity": 0.3},
            ensure_ascii=False)
