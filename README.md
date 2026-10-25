# 虚拟女友 (Virtual Girlfriend)

有形象、有情绪、有声音、有记忆的 AI 女友。本地运行，数据不出本机。

> **形象来源**：[Wallpaper Engine（壁纸引擎）](https://store.steampowered.com/app/431960/Wallpaper_Engine/) 创意工坊作品
> [紫发少女动态壁纸（ID: 3810650535）](https://steamcommunity.com/sharedfiles/filedetails/?id=3810650535)，作者 **FRAC_LAB**。
> 素材版权归原作者所有，仅限本地个人使用，禁止二次分发或商用。

## 功能

- **视频形象**：预渲染动态形象，支持衣橱换装（站/坐/躺多姿态）
- **情感对话**：DeepSeek 驱动，带心情状态与会衰减的情绪引擎、好感度等级
- **语音双工**：浏览器录音 + VAD 自动断句 → faster-whisper 本地语音识别 → edge-tts 情感语音播报（御姐音可调）
- **记忆**：SQLite 保存对话历史，好感度/心情持久化
- **对话日志**：每轮对话实时打印到控制台并写入 `logs/chat.log`

## 快速开始

```powershell
# 1. 安装依赖（Python 3.10+）
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 2. 配置：复制 .env.example 为 .env，填入 DeepSeek API Key
#    https://platform.deepseek.com/api_keys

# 3. 启动
.\start.bat
# 浏览器打开 http://127.0.0.1:8000
```

首次使用语音识别会自动下载 faster-whisper small 模型（约 460MB，走国内镜像）。

## 使用说明

| 操作 | 说明 |
|---|---|
| 输入框打字 / 回车 | 文字聊天 |
| 🎤 按钮 | 开始/结束连续语音对话：开口自动录音，停顿自动发送，她语音回复后继续听你讲 |
| 👗 按钮 | 衣橱换装 |
| 右上角状态栏 | 实时心情 / 好感度 |

常用配置（`.env`）：`GIRL_NAME` 改名、`LLM_MODEL` 换模型、`TTS_EDGE_VOICE/RATE/PITCH` 调音色、`ASR_MODEL` 换识别模型（tiny/base/small/medium）。

## 形象资源来源与版权

`assets/` 目录**不在本仓库中**。形象素材来自 Wallpaper Engine（壁纸引擎）创意工坊：

- 作品：[紫发少女动态壁纸](https://steamcommunity.com/sharedfiles/filedetails/?id=3810650535)
- 作者：**FRAC_LAB**
- 平台：[Wallpaper Engine](https://store.steampowered.com/app/431960/Wallpaper_Engine/)（Steam 售价约 18 元，订阅即下载）
- 工坊 ID：`3810650535`（订阅后位于 `steamapps/workshop/content/431960/3810650535`）

素材版权归原作者所有，仅限本地个人使用，**禁止二次分发或商用**。获取方式：Wallpaper Engine 订阅该作品后，把 `media/1080p`、`images`、`catalog.js` 复制到项目 `assets/` 目录。

## 项目结构

```
server/          FastAPI 后端
  main.py        WebSocket 入口
  orchestrator.py 对话编排（人格 Prompt + 情绪 + 记忆 + TTS）
  emotion/       情绪引擎（心情衰减、好感度升级）
  memory/        SQLite 记忆
  llm/           LLM 客户端（OpenAI 兼容，可接本地微调模型）
  tts/           语音合成（edge-tts / 火山引擎）
  asr.py         语音识别（faster-whisper 本地模型）
web/             前端（视频渲染层 + 聊天 + 衣橱 + VAD 录音）
wsl/             WSL2 + ROCm 训练环境脚本（AMD 显卡 LoRA 微调用）
```

## 自己训练模型（可选）

支持 LoRA 微调开源模型（如 Qwen2.5-7B）作为她的大脑。AMD 显卡路线见 `wsl/setup_rocm.sh`（WSL2 + ROCm 一键配置）。训练完的模型用 Ollama/vLLM 起 OpenAI 兼容服务，改 `.env` 的 `LLM_BASE_URL` 即可接入。
