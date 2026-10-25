"""项目配置：从项目根目录 .env 读取，均有默认值。"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = BASE_DIR / "assets"
WEB_DIR = BASE_DIR / "web"
DB_PATH = BASE_DIR / "server" / "data.db"
LOG_FILE = BASE_DIR / "logs" / "chat.log"

load_dotenv(BASE_DIR / ".env")


class Settings:
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")
    LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")

    # 语音合成：edge（免费免注册）或 volcano（火山引擎，需凭证）
    TTS_PROVIDER = os.getenv("TTS_PROVIDER", "edge")
    TTS_APP_ID = os.getenv("TTS_APP_ID", "")
    TTS_ACCESS_TOKEN = os.getenv("TTS_ACCESS_TOKEN", "")
    TTS_CLUSTER = os.getenv("TTS_CLUSTER", "volcano_tts")
    TTS_VOICE = os.getenv("TTS_VOICE", "zh_female_qingxin")
    TTS_EDGE_VOICE = os.getenv("TTS_EDGE_VOICE", "zh-CN-XiaoyiNeural")
    TTS_EDGE_RATE = os.getenv("TTS_EDGE_RATE", "+0%")
    TTS_EDGE_PITCH = os.getenv("TTS_EDGE_PITCH", "+0Hz")

    # 语音识别（faster-whisper 本地模型）
    ASR_MODEL = os.getenv("ASR_MODEL", "small")

    GIRL_NAME = os.getenv("GIRL_NAME", "紫曦")
    HOST = os.getenv("HOST", "127.0.0.1")
    PORT = int(os.getenv("PORT", "8000"))


settings = Settings()
