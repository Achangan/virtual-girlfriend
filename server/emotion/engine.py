"""情感引擎：心情状态（愉悦度/激活度，随时间向基线衰减）+ 好感度（累积升级）。"""


class EmotionEngine:
    BASELINE_VALENCE = 0.6
    BASELINE_AROUSAL = 0.4
    # 情绪 -> (愉悦度增量, 激活度增量)
    DELTAS = {
        "happy": (0.15, 0.10),
        "surprised": (0.05, 0.20),
        "shy": (0.08, 0.08),
        "tsundere": (0.05, 0.12),
        "relaxed": (0.08, -0.08),
        "calm": (0.0, -0.05),
        "sad": (-0.18, -0.05),
        "angry": (-0.15, 0.18),
    }
    LEVELS = [(800, "深爱"), (400, "心动"), (150, "亲密"), (50, "熟悉"), (0, "初识")]

    def __init__(self, store):
        self.store = store
        self.valence = float(store.get("valence", self.BASELINE_VALENCE))
        self.arousal = float(store.get("arousal", self.BASELINE_AROUSAL))
        self.affection = float(store.get("affection", 10))

    def _persist(self):
        self.store.set("valence", str(self.valence))
        self.store.set("arousal", str(self.arousal))
        self.store.set("affection", str(self.affection))

    def update(self, emotion: str, intensity: float):
        """每轮对话后调用：根据她表现出的情绪更新心情，并累积好感度。"""
        dv, da = self.DELTAS.get(emotion, (0, 0))
        self.valence += dv * intensity
        self.arousal += da * intensity
        # 向基线衰减 10%，情绪不会一直停在极端
        self.valence += (self.BASELINE_VALENCE - self.valence) * 0.1
        self.arousal += (self.BASELINE_AROUSAL - self.arousal) * 0.1
        self.valence = min(1.0, max(0.0, self.valence))
        self.arousal = min(1.0, max(0.0, self.arousal))
        self.affection += 0.5 + (0.3 if self.valence > 0.6 else 0)
        self._persist()

    def level(self) -> str:
        for threshold, name in self.LEVELS:
            if self.affection >= threshold:
                return name
        return "初识"

    def mood_text(self) -> str:
        v, a = self.valence, self.arousal
        if v >= 0.65 and a >= 0.55:
            return "开心雀跃"
        if v >= 0.65:
            return "心情不错"
        if v <= 0.35 and a >= 0.55:
            return "有点烦躁"
        if v <= 0.35:
            return "有点低落"
        return "平静放松"

    def snapshot(self) -> dict:
        return {
            "valence": round(self.valence, 2),
            "arousal": round(self.arousal, 2),
            "mood": self.mood_text(),
            "affection": round(self.affection, 1),
            "level": self.level(),
        }
