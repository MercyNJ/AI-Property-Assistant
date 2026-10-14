import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent

# backend/.env wins over the repo-root .env; real environment variables win over both.
load_dotenv(BACKEND_DIR / ".env")
load_dotenv(PROJECT_ROOT / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _str(name: str, default: str) -> str:
    """os.getenv that also falls back to the default when the variable is empty."""
    return os.getenv(name, "").strip() or default


class Settings:
    def __init__(self) -> None:
        self.openai_api_key: str = os.getenv("OPENAI_API_KEY", "").strip()
        self.openai_model: str = _str("OPENAI_MODEL", "gpt-5.4-mini")
        # Per model call; each chat turn is also capped at assistant.TURN_BUDGET_SECONDS.
        self.openai_timeout: int = _int("OPENAI_TIMEOUT", 25)
        # Empty for models that reject the reasoning parameter (e.g. gpt-4.1-mini).
        self.reasoning_effort: str = os.getenv("OPENAI_REASONING_EFFORT", "low").strip()
        self.database_url: str = _str("DATABASE_URL", f"sqlite:///{(BACKEND_DIR / 'properties.db').as_posix()}")
        # Relative paths resolve from the project root.
        self.seed_file: Path = PROJECT_ROOT / _str("SEED_FILE", "data/properties.json")
        self.cors_origins: list[str] = [
            o.strip()
            for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
            if o.strip()
        ]
        self.max_history_turns: int = _int("MAX_HISTORY_TURNS", 10)
        # /api/chat rate limits: per client IP, plus a global daily cap.
        self.chat_limit_per_minute: int = _int("CHAT_LIMIT_PER_MINUTE", 10)
        self.chat_limit_per_day: int = _int("CHAT_LIMIT_PER_DAY", 100)
        self.chat_limit_global_per_day: int = _int("CHAT_LIMIT_GLOBAL_PER_DAY", 1000)

    @property
    def ai_configured(self) -> bool:
        return bool(self.openai_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
