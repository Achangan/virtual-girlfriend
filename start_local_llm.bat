@echo off
cd /d "%~dp0"
title 紫曦本地模型 - Qwen2.5-7B + LoRA (WSL/ROCm)
echo 首次加载约 1-2 分钟，看到 [load] done 即就绪，此窗口需保持打开。
wsl -d Ubuntu-24.04 -u root -- bash -lc "/root/train-venv/bin/python '/mnt/d/Virtual Girlfriend/train/serve.py'"
pause
