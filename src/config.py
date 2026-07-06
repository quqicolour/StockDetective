"""Configuration loader."""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default)


class Config:
    # DeepSeek
    DEEPSEEK_API_KEY: str = _get("DEEPSEEK_API_KEY")
    DEEPSEEK_BASE: str = _get("DEEPSEEK_BASE", "https://api.deepseek.com")
    DEEPSEEK_MODEL: str = _get("DEEPSEEK_MODEL", "deepseek-chat")

    # Universe
    STOCK_UNIVERSE: str = _get("STOCK_UNIVERSE", "hs300")

    # Screener
    TOP_N: int = int(_get("TOP_N", "10"))
    MIN_SCORE: float = float(_get("MIN_SCORE", "0"))

    # Paths
    REPORTS_DIR: Path = ROOT / "reports"
    DATA_DIR: Path = ROOT / "data"
    CACHE_DIR: Path = DATA_DIR / "cache"

    # HTTP
    HTTP_TIMEOUT: int = 15

    @classmethod
    def ensure_dirs(cls):
        for d in (cls.REPORTS_DIR, cls.DATA_DIR, cls.CACHE_DIR):
            d.mkdir(parents=True, exist_ok=True)


config = Config()
