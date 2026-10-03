"""
Configuration manager for KON.
"""
from pathlib import Path
from typing import Optional
import os
from dotenv import load_dotenv

# Base Project Paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"

# Ensure runtime directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Load .env file
ENV_FILE = BASE_DIR / ".env"
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)
else:
    load_dotenv()


class Settings:
    """
    Application settings with default fallback values.
    """
    def __init__(self) -> None:
        self.host: str = os.getenv("KON_HOST", "127.0.0.1")
        self.port: int = int(os.getenv("KON_PORT", "8000"))
        self.debug: bool = os.getenv("KON_DEBUG", "true").lower() in ("true", "1", "yes")

        # Security mode
        self.security_mode: str = os.getenv("KON_SECURITY_MODE", "CONFIRM").upper()

        # Paths
        self.base_dir: Path = BASE_DIR
        self.data_dir: Path = DATA_DIR
        self.logs_dir: Path = LOGS_DIR
        self.db_path: Path = DATA_DIR / "kon.db"
        self.log_file: Path = LOGS_DIR / "kon.log"

        # AI & Voice Providers (for future stages)
        self.ai_provider: str = os.getenv("AI_PROVIDER", "none")
        self.ai_api_key: Optional[str] = os.getenv("AI_API_KEY", None)
        self.ai_model: str = os.getenv("AI_MODEL", "gpt-4o-mini")

        # Voice & Speech Recognition Settings
        self.stt_provider: str = os.getenv("STT_PROVIDER", "speech_recognition")
        self.stt_language: str = os.getenv("STT_LANGUAGE", "pt-BR")
        _mic_idx = os.getenv("MIC_DEVICE_INDEX", "")
        self.mic_device_index: Optional[int] = int(_mic_idx) if _mic_idx.strip().isdigit() else None
        self.mic_device_name: str = os.getenv("MIC_DEVICE_NAME", "Microfone (Realtek(R) Audio)")
        self.stt_timeout: int = int(os.getenv("STT_TIMEOUT", "5"))
        self.stt_phrase_time_limit: int = int(os.getenv("STT_PHRASE_TIME_LIMIT", "8"))
        self.stt_recognition_timeout: int = int(os.getenv("STT_RECOGNITION_TIMEOUT", "10"))

        self.tts_provider: str = os.getenv("TTS_PROVIDER", "system")
        self.wake_word_engine: str = os.getenv("WAKE_WORD_ENGINE", "mock")
        self.wake_word: str = os.getenv("WAKE_WORD", "Okay KON")


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
