"""入口：FastAPI + WebSocket /ws，静态托管 /assets 与前端页面。

运行（项目根目录）：
    python server/main.py
或：
    uvicorn main:app --app-dir server --host 127.0.0.1 --port 8000

消息协议（JSON）：
  客户端 -> {"type": "chat", "text": "..."}
  服务端 -> {"type": "reply", "text", "emotion", "intensity", "audio"(base64|null), "state"}
"""
import json

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from config import ASSETS_DIR, WEB_DIR, settings
from emotion.engine import EmotionEngine
from llm.client import LLMClient
from memory.store import MemoryStore
from orchestrator import Orchestrator
from tts.client import TTSClient

app = FastAPI(title="Virtual Girlfriend")

memory = MemoryStore()
emotion = EmotionEngine(memory)
llm = LLMClient()
tts = TTSClient()
orchestrator = Orchestrator(llm, tts, emotion, memory)


@app.websocket("/ws")
async def chat_ws(websocket: WebSocket):
    await websocket.accept()
    # 连接建立即推送一次状态，供前端初始化心情/好感度显示
    await websocket.send_text(json.dumps(
        {"type": "state", "state": emotion.snapshot()}, ensure_ascii=False))
    try:
        while True:
            msg = json.loads(await websocket.receive_text())
            if msg.get("type") == "chat" and msg.get("text", "").strip():
                reply = await orchestrator.handle_chat(msg["text"].strip())
                await websocket.send_text(
                    json.dumps({"type": "reply", **reply}, ensure_ascii=False))
            elif msg.get("type") == "voice" and msg.get("audio"):
                # 浏览器录音 -> 本地 ASR -> 走同一聊天管道，回复附带识别出的文字
                import asyncio
                import base64

                import asr

                audio_bytes = base64.b64decode(msg["audio"])
                try:
                    heard = await asyncio.to_thread(asr.transcribe, audio_bytes)
                except Exception as e:
                    print(f"[ASR] 识别失败: {e}", flush=True)
                    heard = ""
                # 识别结果立即回显（没听清则推空文本提示）
                await websocket.send_text(json.dumps(
                    {"type": "heard", "text": heard}, ensure_ascii=False))
                if not heard:
                    continue
                print(f"[ASR] 听到: {heard}", flush=True)
                reply = await orchestrator.handle_chat(heard)
                await websocket.send_text(json.dumps(
                    {"type": "reply", **reply}, ensure_ascii=False))
    except WebSocketDisconnect:
        pass
    except json.JSONDecodeError:
        await websocket.close(code=1003)


app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT)
