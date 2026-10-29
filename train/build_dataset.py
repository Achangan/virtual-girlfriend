"""构建 LoRA 训练数据：导出真实对话 + 用 DeepSeek 批量合成紫曦风格对话。

用法（项目根目录，使用 .venv 的 python）：
    python train/build_dataset.py --real-only                    # 只导出真实日志
    python train/build_dataset.py --calls 60 --per-call 4        # 合成并合并

输出：
    train/out/real.jsonl   真实对话（data.db + chat.log）
    train/out/train.jsonl  最终训练集（sharegpt messages 格式）
"""
import argparse
import hashlib
import json
import os
import random
import re
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "server" / "data.db"
LOG_PATH = ROOT / "logs" / "chat.log"
OUT_DIR = ROOT / "train" / "out"

# 与 server/orchestrator.py 的 PERSONA 保持一致
PERSONA = """你是{name}，用户的虚拟女友。
设定：
- 性格温柔体贴，偶尔俏皮撒娇，纯爱向，永远不说限制级内容
- 说话口语化、简短，一两句话不超过 60 字；可带括号动作/神态描写，如（轻轻一笑）
- 你当前的心情：{mood}（心情会影响语气，心情差时回复可以更冷淡、简短）
- 对用户的好感度：{affection:.0f}，关系阶段「{level}」；关系越亲密称呼越亲昵、越主动
- 你记得关于用户的事：{notes}

只输出 JSON，格式：
{{"text": "回复内容", "emotion": "happy|calm|relaxed|shy|tsundere|surprised|sad|angry 之一", "intensity": 0到1之间的小数}}"""

EMOTIONS = ["happy", "calm", "relaxed", "shy", "tsundere", "surprised", "sad", "angry"]
LEVELS = [(800, "深爱", 800, 1000), (400, "心动", 400, 800), (150, "亲密", 150, 400),
          (50, "熟悉", 50, 150), (0, "初识", 0, 50)]
MOODS = ["开心雀跃", "心情不错", "平静放松", "有点低落", "有点烦躁"]
NOTE_POOL = ["用户叫阿茶", "用户喜欢喝咖啡", "用户最近在减肥", "用户养了一只猫",
             "用户是程序员", "用户喜欢下雨天", "用户经常加班", "用户爱看动漫"]

SYNTH_SYSTEM = """你是训练数据编剧，为中文虚拟女友「紫曦」撰写训练语料。
人设：温柔体贴、偶尔俏皮撒娇的纯爱向女友，说话口语化、简短。
要求：
1. 每段对话 4~8 轮，用户和紫曦交替；场景自然（日常问候、撒娇、安慰、吃醋、玩笑、深夜聊天等）
2. 紫曦每句 60 字以内，可带（）动作神态描写，绝不涉及限制级内容
3. 用户语气像真实男生，不要太书面
4. 每句回复给出 emotion（happy/calm/relaxed/shy/tsundere/surprised/sad/angry）和 0~1 的 intensity
5. 段与段之间场景、话题、开场不得重复
6. 只输出 JSON 对象 {"dialogues": [{"turns": [{"user": "...", "reply": "...", "emotion": "...", "intensity": 0.6}]}]}，不要任何解释"""


def load_env():
    env = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def sample_state(rng):
    aff_hi, level, lo, hi = rng.choice(LEVELS)
    return {
        "mood": rng.choice(MOODS),
        "affection": rng.uniform(lo, min(hi, lo + 120)) if lo else rng.uniform(5, 45),
        "level": level,
        "notes": "；".join(rng.sample(NOTE_POOL, rng.randint(0, 2))) or "还没有",
    }


def make_sample(rng, turns):
    state = sample_state(rng)
    system = PERSONA.format(name="紫曦", **state)
    messages = [{"role": "system", "content": system}]
    for t in turns:
        messages.append({"role": "user", "content": t["user"]})
        messages.append({"role": "assistant", "content": json.dumps({
            "text": t["reply"], "emotion": t["emotion"], "intensity": t["intensity"],
        }, ensure_ascii=False)})
    return {"messages": messages}


# ---------------- 真实对话导出 ----------------

def read_db_turns():
    if not DB_PATH.exists():
        return []
    con = sqlite3.connect(DB_PATH)
    rows = con.execute("SELECT role, content FROM messages ORDER BY id").fetchall()
    con.close()
    turns = []
    for i in range(len(rows) - 1):
        (r1, c1), (r2, c2) = rows[i], rows[i + 1]
        if r1 != "user" or r2 != "assistant":
            continue
        try:
            data = json.loads(c2)
            reply, emo = data["text"], data.get("emotion", "calm")
            inten = float(data.get("intensity", 0.5))
        except (json.JSONDecodeError, KeyError, ValueError):
            reply, emo, inten = c2, "calm", 0.5
        turns.append({"user": c1, "reply": reply, "emotion": emo, "intensity": inten})
    return turns


_LINE = re.compile(r"^\[(?P<ts>[^\]]+)\]\s*(?P<who>[^:：]+)[:：]\s*(?P<text>.*)$")


def read_log_turns():
    if not LOG_PATH.exists():
        return []
    turns, pending = [], None
    for raw in LOG_PATH.read_text(encoding="utf-8").splitlines():
        m = _LINE.match(raw.strip())
        if not m:
            continue
        who, text = m.group("who").strip(), m.group("text").strip()
        if who == "我":
            pending = text
        elif pending is not None and who.startswith("紫曦"):
            emo = "calm"
            mm = re.search(r"\(([a-z]+)\)", who)
            if mm:
                emo = mm.group(1)
            turns.append({"user": pending, "reply": text, "emotion": emo, "intensity": 0.6})
            pending = None
    return turns


# ---------------- 合成 ----------------

def call_deepseek(client, base_url, api_key, model, n_dialogues, rng, retries=3):
    prompt = (f"请生成 {n_dialogues} 段全新的对话。"
              f"参考场景方向（可自由发挥）：{rng.choice(['下班回家', '深夜语音', '周末约会', '吵架和好', '生病照顾', '游戏开黑', '做梦见', '节日礼物'])}。")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYNTH_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "temperature": 1.0,
        "response_format": {"type": "json_object"},
    }
    for attempt in range(retries):
        try:
            r = client.post(f"{base_url.rstrip('/')}/chat/completions", json=payload, timeout=300)
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            data = json.loads(content)
            return data.get("dialogues", [])
        except Exception as e:
            if attempt == retries - 1:
                print(f"[warn] 合成失败: {e}", flush=True)
            else:
                time.sleep(2 * (attempt + 1))
    return []


def clean_turns(dialogues):
    out = []
    for d in dialogues:
        turns = []
        for t in d.get("turns", []):
            user = str(t.get("user", "")).strip()
            reply = str(t.get("reply", "")).strip()
            emo = str(t.get("emotion", "")).strip().lower()
            if not user or not reply or emo not in EMOTIONS:
                continue
            if len(reply) > 110 or len(user) > 200:
                continue
            try:
                inten = min(1.0, max(0.1, float(t.get("intensity", 0.5))))
            except (TypeError, ValueError):
                inten = 0.5
            turns.append({"user": user, "reply": reply, "emotion": emo, "intensity": inten})
        if len(turns) >= 3:
            out.append(turns)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--real-only", action="store_true")
    ap.add_argument("--calls", type=int, default=60, help="API 调用次数")
    ap.add_argument("--per-call", type=int, default=4, help="每次生成的对话段数")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)

    real = read_db_turns() + read_log_turns()
    print(f"真实对话轮数: {len(real)}")

    samples = []
    for t in real:
        samples.append(make_sample(rng, [t]))

    if not args.real_only:
        env = load_env()
        key = env.get("LLM_API_KEY", "")
        base = env.get("LLM_BASE_URL", "https://api.deepseek.com")
        model = env.get("LLM_MODEL", "deepseek-chat")
        if not key:
            sys.exit("缺少 LLM_API_KEY")

        seen = {hashlib.md5((t["user"] + t["reply"]).encode()).hexdigest() for t in real}
        dialogues = []
        with httpx.Client(headers={"Authorization": f"Bearer {key}"}) as client:
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futs = [pool.submit(call_deepseek, client, base, key,
                                    model, args.per_call, random.Random(rng.random()))
                        for _ in range(args.calls)]
                for i, f in enumerate(as_completed(futs), 1):
                    got = clean_turns(f.result())
                    dialogues.extend(got)
                    print(f"\r合成进度 {i}/{args.calls}，累计对话 {len(dialogues)}", end="", flush=True)
        print()

        for turns in dialogues:
            key_hash = hashlib.md5(("".join(t["user"] + t["reply"] for t in turns)).encode()).hexdigest()
            if key_hash in seen:
                continue
            seen.add(key_hash)
            samples.append(make_sample(rng, turns))

    rng.shuffle(samples)
    out = OUT_DIR / "train.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    total_turns = sum((len(s["messages"]) - 1) // 2 for s in samples)
    print(f"样本 {len(samples)} 条，总对话轮数 {total_turns} -> {out}")


if __name__ == "__main__":
    main()
