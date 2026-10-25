@echo off
cd /d "%~dp0"
title 虚拟女友 - 紫曦
start "" http://127.0.0.1:8000
.venv\Scripts\python.exe server\main.py
pause
