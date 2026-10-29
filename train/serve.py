"""本地推理服务（WSL 内运行）：Qwen2.5-7B 4bit + 紫曦 LoRA，提供 OpenAI 兼容接口。

从 Windows 启动（或双击 start_local_llm.bat）：
    wsl -d Ubuntu-24.04 -u root -- bash -lc "/root/train-venv/bin/python '/mnt/d/Virtual Girlfriend/train/serve.py'"

端口 8100，Windows 通过 http://127.0.0.1:8100/v1 访问（WSL2 localhost 转发）。
"""
import os

import torch
import uvicorn
from fastapi import FastAPI
from peft import PeftModel
from pydantic import BaseModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

MODEL_PATH = os.getenv("ZIXI_BASE_MODEL", "/root/models/Qwen2.5-7B-Instruct")
ADAPTER_PATH = os.getenv("ZIXI_ADAPTER", "/root/outputs/zixi-qlora")
PORT = int(os.getenv("ZIXI_PORT", "8100"))
MAX_NEW_TOKENS = int(os.getenv("ZIXI_MAX_NEW_TOKENS", "160"))

app = FastAPI(title="zixi-local-llm")

print(f"[load] base={MODEL_PATH}", flush=True)
print(f"[load] adapter={ADAPTER_PATH}", flush=True)
tokenizer = AutoTokenizer.from_pretrained(ADAPTER_PATH, trust_remote_code=True)
model = AutoModelForCausalLM.from_pretrained(
    MODEL_PATH,
    quantization_config=BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    ),
    device_map=None,
    trust_remote_code=True,
).to("cuda")
model = PeftModel.from_pretrained(model, ADAPTER_PATH)
model.eval()
print("[load] done", flush=True)


class ChatRequest(BaseModel):
    messages: list[dict]
    model: str | None = None
    temperature: float = 0.8
    max_tokens: int | None = None
    response_format: dict | None = None  # 兼容字段，模型已微调保证 JSON 输出


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/v1/chat/completions")
def chat_completions(req: ChatRequest):
    text = tokenizer.apply_chat_template(
        req.messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(text, return_tensors="pt").to("cuda")
    n_prompt = inputs["input_ids"].shape[1]
    with torch.inference_mode():
        out = model.generate(
            **inputs,
            max_new_tokens=req.max_tokens or MAX_NEW_TOKENS,
            do_sample=True,
            temperature=max(req.temperature, 1e-4),
            top_p=0.9,
            repetition_penalty=1.05,
            pad_token_id=tokenizer.eos_token_id,
        )
    reply = tokenizer.decode(out[0][n_prompt:], skip_special_tokens=True).strip()
    print(f"[gen] prompt={n_prompt} new={out.shape[1] - n_prompt}", flush=True)
    return {
        "id": "chatcmpl-local",
        "object": "chat.completion",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": reply},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": int(n_prompt),
                  "completion_tokens": int(out.shape[1] - n_prompt)},
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
