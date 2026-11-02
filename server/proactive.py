"""主动消息：早安、晚安、久未说话时，由她先开口。

main.py 在启动时拉起一个轮询任务（默认 60 秒一次）。只在有 WebSocket 连接
（浏览器开着）时推送，并受冷却时间与每日上限约束，避免打扰。
"""
import asyncio
import json
import time
from datetime import datetime

from config import settings


class ProactiveManager:
    def __init__(self, orchestrator, memory):
        self.orch = orchestrator
        self.memory = memory
        self.clients = set()
        self.last_user_ts = None
        self.last_proactive_ts = None
        self._task = None
        self._speaking = False  # 防止上一句还没生成完又触发

    def start(self):
        if not settings.PROACTIVE_ENABLED:
            print("[主动] 已关闭", flush=True)
            return
        self._task = asyncio.create_task(self._loop())
        print("[主动] 已开启（早安/晚安/久未说话）", flush=True)

    def add_client(self, ws):
        self.clients.add(ws)
        # 刚打开页面时不等轮询，几秒后立即判断一次
        asyncio.create_task(self._check_soon())

    def remove_client(self, ws):
        self.clients.discard(ws)

    def on_user_message(self):
        self.last_user_ts = time.time()

    async def _check_soon(self):
        await asyncio.sleep(5)
        await self._safe_check()

    async def _loop(self):
        while True:
            await asyncio.sleep(settings.PROACTIVE_TICK)
            await self._safe_check()

    async def _safe_check(self):
        try:
            await self._maybe_speak()
        except Exception as exc:  # 主动消息失败不能影响主服务
            print(f"[主动] 异常: {exc}", flush=True)

    def _daily_counter(self) -> tuple[str, int]:
        raw = self.memory.get("proactive_count", "") or ""
        day, _, num = raw.partition(":")
        return day, int(num) if num.isdigit() else 0

    def _bump_counter(self, today: str):
        _, num = self._daily_counter()
        self.memory.set("proactive_count", f"{today}:{num + 1}")

    def _pick_reason(self) -> str | None:
        """返回触发原因（morning / night / idle），不满足条件返回 None。"""
        if not self.clients or self._speaking:
            return None
        now = datetime.now()
        today = now.date().isoformat()

        # 全局冷却：避免连续打扰
        if (self.last_proactive_ts and
                time.time() - self.last_proactive_ts < settings.PROACTIVE_COOLDOWN_MIN * 60):
            return None
        # 每日上限
        if self._daily_counter()[1] >= settings.PROACTIVE_DAILY_MAX:
            return None

        hour = now.hour
        # 早晚问候只在用户安静时发，避免聊天中途突然说"早安"
        settled = self.last_user_ts is None or time.time() - self.last_user_ts >= 600
        if settled:
            if 6 <= hour < 11 and self.memory.get("proactive_morning") != today:
                return "morning"
            if (hour >= 23 or hour < 3) and self.memory.get("proactive_night") != today:
                return "night"
        # 久未说话：静默时长本身已保证不打扰
        if (self.last_user_ts and
                time.time() - self.last_user_ts > settings.PROACTIVE_IDLE_MIN * 60):
            return "idle"
        return None

    async def _maybe_speak(self):
        reason = self._pick_reason()
        if not reason:
            return
        self._speaking = True
        try:
            reply = await self.orch.generate_proactive(reason)
            payload = json.dumps(
                {"type": "reply", "proactive": True, "reason": reason, **reply},
                ensure_ascii=False)
            for ws in list(self.clients):
                try:
                    await ws.send_text(payload)
                except Exception:
                    self.remove_client(ws)
            self.last_proactive_ts = time.time()
            today = datetime.now().date().isoformat()
            self._bump_counter(today)
            if reason == "morning":
                self.memory.set("proactive_morning", today)
            elif reason == "night":
                self.memory.set("proactive_night", today)
        finally:
            self._speaking = False
