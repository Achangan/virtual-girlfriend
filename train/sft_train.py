"""Qwen2.5-7B QLoRA SFT（绕过 LLaMA-Factory，直接在 WSL 内运行）。

用法：
    /root/train-venv/bin/python /mnt/d/Virtual\ Girlfriend/train/sft_train.py
"""
import json
from pathlib import Path

import torch
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import (AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig,
                          DataCollatorForSeq2Seq, Trainer, TrainingArguments)

MODEL_PATH = "/root/models/Qwen2.5-7B-Instruct"
DATA_PATH = Path("/mnt/d/Virtual Girlfriend/train/out/train.jsonl")
OUT_DIR = "/root/outputs/zixi-qlora"
MAX_LEN = 1024
EPOCHS = 3
BS = 1
GRAD_ACC = 8
LR = 1e-4


def load_features(tokenizer, path):
    samples = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    features = []
    for s in samples:
        messages = s["messages"]
        text = tokenizer.apply_chat_template(messages, tokenize=False)
        enc = tokenizer(text, add_special_tokens=False, truncation=True, max_length=MAX_LEN)
        ids = enc["input_ids"]
        labels = [-100] * len(ids)
        # 只对 assistant 回复计算 loss
        for i, m in enumerate(messages):
            if m["role"] != "assistant":
                continue
            prefix = tokenizer.apply_chat_template(
                messages[:i], tokenize=False, add_generation_prompt=True)
            upto = tokenizer.apply_chat_template(messages[: i + 1], tokenize=False)
            start = len(tokenizer(prefix, add_special_tokens=False)["input_ids"])
            end = min(len(tokenizer(upto, add_special_tokens=False)["input_ids"]), len(ids))
            if start < end:
                labels[start:end] = ids[start:end]
        if all(x == -100 for x in labels):
            continue
        features.append({"input_ids": ids, "labels": labels})
    return features


def main():
    tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        MODEL_PATH,
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True),
        device_map=None, trust_remote_code=True).to("cuda")
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=False)
    model = get_peft_model(model, LoraConfig(
        r=16, lora_alpha=32, lora_dropout=0.05, bias="none",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        task_type="CAUSAL_LM"))
    model.config.use_cache = False

    features = load_features(tokenizer, DATA_PATH)
    print(f"样本 {len(features)}", flush=True)

    args = TrainingArguments(
        output_dir=OUT_DIR,
        per_device_train_batch_size=BS,
        gradient_accumulation_steps=GRAD_ACC,
        num_train_epochs=EPOCHS,
        learning_rate=LR,
        lr_scheduler_type="cosine",
        warmup_ratio=0.1,
        bf16=True,
        logging_steps=10,
        save_strategy="no",
        report_to=[],
        remove_unused_columns=False,
        dataloader_num_workers=0,
    )
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=features,
        data_collator=DataCollatorForSeq2Seq(tokenizer, padding=True, label_pad_token_id=-100),
    )
    trainer.train()

    Path(OUT_DIR).mkdir(parents=True, exist_ok=True)
    model.save_pretrained(OUT_DIR)
    tokenizer.save_pretrained(OUT_DIR)
    print("saved to", OUT_DIR, flush=True)


if __name__ == "__main__":
    main()
