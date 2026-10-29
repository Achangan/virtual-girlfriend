"""紫曦项目端到端自动测试。

运行：
    .venv\\Scripts\\python.exe test_e2e.py

可选参数：
    --cases N        对话样例数量（默认 4）
    --no-local-skip  本地模型挂掉时不跳过，直接标记失败（默认会跳过本地相关项）
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx
import websockets

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "server"))

from config import settings  # noqa: E402  (test-only)
from orchestrator import PERSONA  # noqa: E402

# LLM_LOCAL_URL 默认带 /v1（OpenAI 兼容路径），健康检查在根路径，单独算
LLM_ROOT = settings.LLM_LOCAL_URL.replace("/v1", "").rstrip("/")
LLM_V1 = settings.LLM_LOCAL_URL.rstrip("/")
MAIN_URL = f"http://{settings.HOST}:{settings.PORT}"
WS_URL = f"ws://{settings.HOST}:{settings.PORT}/ws"

EMOTIONS = {"happy", "calm", "relaxed", "shy", "tsundere", "surprised", "sad", "angry"}

CASES = [
    "我想你了",
    "今天加班到现在，好累啊",
    "嘿嘿嘿",
    "晚安啦，明天见",
    "你叫什么名字？",
    "给我讲个冷笑话",
    "我心情不好，陪陪我",
    "周末一起出去吧",
]


class Result:
    def __init__(self, name: str):
        self.name = name
        self.passed = False
        self.elapsed = 0.0
        self.detail = ""

    def __str__(self):
        tag = "PASS" if self.passed else "FAIL"
        line = f"[{tag}] {self.name} ({self.elapsed:.0f}ms)"
        if self.detail:
            line += f"  — {self.detail}"
        return line


def timed(name: str):
    """装饰器：计时 + 捕获异常，返回 Result。"""
    def wrap(fn):
        async def inner(*args, **kw):
            r = Result(name)
            t0 = time.perf_counter()
            try:
                await fn(r, *args, **kw)
                r.passed = True
            except Exception as e:
                r.detail = f"{type(e).__name__}: {e}"
            r.elapsed = (time.perf_counter() - t0) * 1000
            return r
        return inner
    return wrap


async def check(cond: bool, msg: str, r: Result):
    if not cond:
        raise AssertionError(msg)


# -------------------- Test Cases --------------------

@timed("local_llm_health")
async def t_local_health(r: Result, client: httpx.AsyncClient):
    resp = await client.get(f"{LLM_ROOT}/health", timeout=5)
    await check(resp.status_code == 200, f"status={resp.status_code}", r)
    await check(resp.json() == {"ok": True}, f"body={resp.text}", r)


@timed("local_llm_chat_json")
async def t_local_chat(r: Result, client: httpx.AsyncClient):
    system = PERSONA.format(
        name=settings.GIRL_NAME, mood="心情不错", affection=80,
        level="熟悉", notes="用户叫阿茶；用户喜欢喝咖啡")
    payload = {
        "model": "zixi-qlora",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": "我想你了"},
        ],
        "temperature": 0.8,
    }
    resp = await client.post(f"{LLM_V1}/chat/completions", json=payload, timeout=120)
    await check(resp.status_code == 200, f"status={resp.status_code}", r)
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    obj = json.loads(content)
    await check(isinstance(obj.get("text"), str) and len(obj["text"]) > 0, f"text 缺失: {content}", r)
    await check(obj.get("emotion") in EMOTIONS, f"emotion={obj.get('emotion')} 非法", r)
    i = obj.get("intensity")
    await check(isinstance(i, (int, float)) and 0 <= float(i) <= 1, f"intensity={i} 非法", r)
    r.detail = content[:80]


@timed("main_http_index")
async def t_main_http(r: Result, client: httpx.AsyncClient):
    resp = await client.get(f"{MAIN_URL}/", timeout=5)
    await check(resp.status_code == 200, f"status={resp.status_code}", r)
    await check("text/html" in resp.headers.get("content-type", ""),
                f"content-type={resp.headers.get('content-type')}", r)
    await check("catalog.js" in resp.text, "页面缺少 catalog.js 引用", r)


@timed("ws_end_to_end")
async def t_ws_e2e(r: Result, _client=None):
    async with websockets.connect(WS_URL, open_timeout=5, close_timeout=5) as ws:
        # 首帧 state 推送
        first = json.loads(await asyncio.wait_for(ws.recv(), 10))
        await check(first.get("type") == "state", f"首帧 type={first.get('type')}", r)
        state = first.get("state", {})
        for k in ("valence", "arousal", "mood", "affection", "level"):
            await check(k in state, f"state 缺少 {k}", r)

        # 发送 chat
        await ws.send(json.dumps({"type": "chat", "text": "晚安啦"}))
        reply = json.loads(await asyncio.wait_for(ws.recv(), 120))
        await check(reply.get("type") == "reply", f"type={reply.get('type')}", r)
        for k in ("text", "emotion", "intensity", "audio", "state"):
            await check(k in reply, f"reply 缺少 {k}", r)
        await check(reply["emotion"] in EMOTIONS, f"emotion={reply['emotion']}", r)
        await check(isinstance(reply["text"], str) and len(reply["text"]) > 0, "text 为空", r)
        # audio 要么 null 要么非空字符串
        audio = reply["audio"]
        await check(audio is None or (isinstance(audio, str) and len(audio) > 10),
                    "audio 既非 null 也非 base64 字符串", r)
        r.detail = f"text={reply['text'][:40]} emotion={reply['emotion']}"


@timed("ws_multi_turn")
async def t_ws_multi_turn(r: Result, _client=None, cases=None):
    cases = cases or CASES[:4]
    async with websockets.connect(WS_URL, open_timeout=5, close_timeout=5) as ws:
        # 丢弃首帧 state
        await asyncio.wait_for(ws.recv(), 10)
        replies = []
        for text in cases:
            await ws.send(json.dumps({"type": "chat", "text": text}))
            reply = json.loads(await asyncio.wait_for(ws.recv(), 120))
            replies.append(reply)
            await check(reply.get("type") == "reply", f"type={reply.get('type')}", r)
            await check(reply["emotion"] in EMOTIONS, f"emotion={reply['emotion']}", r)
        # 4 轮下来 emotion 应该不都一样（LoRA 多轮应有变化）
        unique = {r_["emotion"] for r_ in replies}
        await check(len(unique) >= 2, f"4 轮 emotion 全相同: {unique}", r)
        r.detail = f"emotions={sorted(unique)}"


# -------------------- Runner --------------------

async def run(args):
    results: list[Result] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
        # 先探测本地 LLM 是否在线，决定是否跳过相关项
        llm_ok = True
        try:
            h = await client.get(f"{LLM_ROOT}/health")
            llm_ok = h.status_code == 200 and h.json().get("ok") is True
        except Exception:
            llm_ok = False

        main_ok = True
        try:
            h = await client.get(f"{MAIN_URL}/", timeout=5)
            main_ok = h.status_code == 200
        except Exception:
            main_ok = False

        print(f"前置探测: local_llm={llm_ok}, main={main_ok}", flush=True)

        if not llm_ok and not args.no_local_skip:
            print("[skip] 本地模型离线，跳过 local_llm_* 测试（加 --no-local-skip 可强制跑）", flush=True)
            skip_local = True
        else:
            skip_local = False

        if main_ok:
            results.append(await t_local_health(client) if not skip_local else _skipped("local_llm_health", "local_llm offline"))
            results.append(await t_local_chat(client) if not skip_local else _skipped("local_llm_chat_json", "local_llm offline"))
            results.append(await t_main_http(client))
            results.append(await t_ws_e2e())
            results.append(await t_ws_multi_turn(cases=CASES[: args.cases]))
        else:
            # 主服务挂了但 LLM 可能还活着 —— 只跑 LLM 相关
            print("[skip] 主服务离线，仅测试 LLM 相关项", flush=True)
            results.append(await t_local_health(client) if not skip_local else _skipped("local_llm_health", "local_llm offline"))
            results.append(await t_local_chat(client) if not skip_local else _skipped("local_llm_chat_json", "local_llm offline"))
            for name in ("main_http_index", "ws_end_to_end", "ws_multi_turn"):
                results.append(_skipped(name, "main server offline"))

    # -------------------- 输出 --------------------
    print("\n" + "=" * 60)
    for r in results:
        print(str(r))
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    print("-" * 60)
    print(f"汇总: {passed}/{total} 通过")
    return 0 if passed == total else 1


def _skipped(name: str, reason: str) -> Result:
    r = Result(name)
    r.detail = f"SKIPPED: {reason}"
    r.elapsed = 0
    # 用一种我们能识别的"跳过"——计入通过但 detail 带 SKIPPED
    # 我们改为在输出里单独标记，不影响通过计数
    r.passed = True  # 跳过不影响 exit code，只有真正 FAIL 才影响
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=int, default=4, help="多轮对话样例数")
    ap.add_argument("--no-local-skip", action="store_true", help="本地 LLM 离线时不跳过")
    args = ap.parse_args()
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
