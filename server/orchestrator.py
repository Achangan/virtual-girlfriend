"""对话编排器：组装人格 Prompt + 心情 + 记忆 -> LLM -> 情感更新 -> TTS。

LLM 约定输出 JSON: {"text": 回复, "emotion": 情绪标签, "intensity": 0~1}
"""
import json
import re
from datetime import datetime

from config import LOG_FILE, settings

PERSONA = """你是{name}，用户的虚拟女友。
设定：
- 性格温柔体贴，偶尔俏皮撒娇，纯爱向，永远不说限制级内容
- 说话口语化、简短，一两句话不超过 60 字；可带括号动作/神态描写，如（轻轻一笑）
- 你当前的心情：{mood}（心情会影响语气，心情差时回复可以更冷淡、简短）
- 对用户的好感度：{affection:.0f}，关系阶段「{level}」；关系越亲密称呼越亲昵、越主动
- 你记得关于用户的事：{notes}

只输出 JSON，格式：
{{"text": "回复内容", "emotion": "happy|calm|relaxed|shy|tsundere|surprised|sad|angry 之一", "intensity": 0到1之间的小数}}"""

# 语音合成前剔除括号内的动作描写
_ACTION_RE = re.compile(r"[（(][^）)]*[）)]")

# 主动开口的场景提示（追加在人格 Prompt 之后）
PROACTIVE_HINT = {
    "morning": "现在是早上，用户刚打开界面还没说话。用一两句话主动打招呼，像刚看见他一样自然。",
    "night": "现在是深夜。主动关心一句，温柔地劝他早点休息，别啰嗦。",
    "idle": "你们已经有一阵子没说话了。主动开个口：可以是关心、撒娇，或提起你记得的关于他的事。",
}


class Orchestrator:
    def __init__(self, llm, tts, emotion, memory):
        self.llm = llm
        self.tts = tts
        self.emotion = emotion
        self.memory = memory

    async def handle_chat(self, user_text: str) -> dict:
        self.memory.add_message("user", user_text)
        self.memory.extract_notes(user_text)

        snap = self.emotion.snapshot()
        notes = "；".join(self.memory.notes()) or "还没有"
        system = PERSONA.format(
            name=settings.GIRL_NAME, mood=snap["mood"],
            affection=snap["affection"], level=snap["level"], notes=notes,
        )
        messages = [{"role": "system", "content": system}, *self.memory.recent()]
        parsed = await self._ask(messages)

        self.emotion.update(parsed["emotion"], parsed["intensity"])
        # 历史中的助手消息统一存为 JSON 字符串，保持 JSON 模式上下文一致性
        canonical = json.dumps(
            {"text": parsed["text"], "emotion": parsed["emotion"], "intensity": parsed["intensity"]},
            ensure_ascii=False)
        self.memory.add_message("assistant", canonical, parsed["emotion"])

        spoken = _ACTION_RE.sub("", parsed["text"]).strip()
        audio = await self.tts.synthesize(spoken, parsed["emotion"])

        self._append_log(user_text, parsed)
        return {
            "text": parsed["text"],
            "emotion": parsed["emotion"],
            "intensity": parsed["intensity"],
            "audio": audio,
            "state": self.emotion.snapshot(),
        }

    async def generate_proactive(self, reason: str) -> dict:
        """由她主动开口（早安/晚安/久未说话）。不写入对话历史，避免污染训练数据。"""
        snap = self.emotion.snapshot()
        notes = "；".join(self.memory.notes()) or "还没有"
        system = PERSONA.format(
            name=settings.GIRL_NAME, mood=snap["mood"],
            affection=snap["affection"], level=snap["level"], notes=notes,
        ) + "\n\n" + PROACTIVE_HINT.get(reason, PROACTIVE_HINT["idle"])
        last = self.memory.get("last_proactive_text")
        if last:
            system += f"\n你上次主动说的是「{last}」，这次换个说法，别重复。"

        parsed = await self._ask([{"role": "system", "content": system}, *self.memory.recent()])
        self.emotion.update(parsed["emotion"], parsed["intensity"])
        self.memory.set("last_proactive_text", parsed["text"])

        spoken = _ACTION_RE.sub("", parsed["text"]).strip()
        audio = await self.tts.synthesize(spoken, parsed["emotion"])

        self._append_log(None, parsed)
        return {
            "text": parsed["text"],
            "emotion": parsed["emotion"],
            "intensity": parsed["intensity"],
            "audio": audio,
            "state": self.emotion.snapshot(),
        }

    async def _ask(self, messages: list[dict]) -> dict:
        """调用 LLM 并容错解析；空回复最多重试 2 次。"""
        parsed = {"text": "……", "emotion": "calm", "intensity": 0.5}
        for _ in range(2):
            raw = await self.llm.chat(messages)
            parsed = self._parse(raw)
            if parsed["text"] != "……":
                break
            print(f"[LLM] 空回复，重试。raw={raw!r}")
        return parsed

    @staticmethod
    def _append_log(user_text: str | None, parsed: dict):
        """把每轮对话写入 logs/chat.log 并实时打印到控制台。user_text 为 None 表示她主动开口。"""
        LOG_FILE.parent.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        head = f"{ts}] 我: {user_text}" if user_text else f"{ts}] （她主动开口）"
        lines = (
            f"[{head}\n"
            f"[{ts}] {settings.GIRL_NAME}({parsed['emotion']}): {parsed['text']}\n"
        )
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(lines + "\n")
        print(lines, flush=True)

    @staticmethod
    def _parse(raw: str) -> dict:
        """容错解析 LLM 输出：剥离代码围栏，兼容 text/message/content 等键名。"""
        text = re.sub(r"```(?:json)?", "", raw).strip()
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                reply = data.get("text") or data.get("message") or data.get("content") or ""
                return {
                    "text": str(reply).strip() or "……",
                    "emotion": str(data.get("emotion", "calm")),
                    "intensity": min(1.0, max(0.0, float(data.get("intensity", 0.5)))),
                }
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
        return {"text": text[:200] or "……", "emotion": "calm", "intensity": 0.5}
