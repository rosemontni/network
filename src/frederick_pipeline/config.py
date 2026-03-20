from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
REPORT_DIR = DATA_DIR / "reports"
DISCOVERY_DIR = DATA_DIR / "discoveries"
SOURCE_FILE = ROOT / "sources" / "frederick_sources.json"
DB_PATH = DATA_DIR / "frederick_people.db"


@dataclass(frozen=True)
class Settings:
    db_path: Path = DB_PATH
    source_file: Path = SOURCE_FILE
    cache_dir: Path = CACHE_DIR
    report_dir: Path = REPORT_DIR
    discovery_dir: Path = DISCOVERY_DIR
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    article_timeout_seconds: int = int(os.getenv("ARTICLE_TIMEOUT_SECONDS", "20"))
    max_article_chars: int = int(os.getenv("MAX_ARTICLE_CHARS", "12000"))
    min_person_confidence: float = float(os.getenv("MIN_PERSON_CONFIDENCE", "0.25"))
    min_connection_confidence: float = float(os.getenv("MIN_CONNECTION_CONFIDENCE", "0.4"))


def ensure_directories(settings: Settings) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    settings.report_dir.mkdir(parents=True, exist_ok=True)
    settings.discovery_dir.mkdir(parents=True, exist_ok=True)


def load_sources(settings: Settings) -> list[dict]:
    return json.loads(settings.source_file.read_text(encoding="utf-8"))
