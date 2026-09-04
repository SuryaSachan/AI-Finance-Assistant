"""Central configuration, loaded from environment / .env."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


LLM_PROVIDER = (os.getenv("LLM_PROVIDER") or "ollama").strip().lower()
LLM_MODEL = (os.getenv("LLM_MODEL") or "qwen2.5:3b-instruct").strip()
LLM_MODEL_FALLBACK = (os.getenv("LLM_MODEL_FALLBACK") or "").strip()
LLM_BASE_URL = (os.getenv("LLM_BASE_URL") or "http://localhost:11434").rstrip("/")
LLM_API_KEY = (os.getenv("LLM_API_KEY") or "").strip()
LLM_TIMEOUT_SECONDS = _float("LLM_TIMEOUT_SECONDS", 60)
LLM_TEMPERATURE = _float("LLM_TEMPERATURE", 0.0)

DB_PATH = ROOT / (os.getenv("DB_PATH") or "data/finance.duckdb")
DATA_DIR = ROOT / "data"
WEB_DIR = ROOT / "web"

ANCHOR_DATE = (os.getenv("ANCHOR_DATE") or "").strip() or None

MAX_ROWS = _int("MAX_ROWS", 200)
LLM_ROW_BUDGET = _int("LLM_ROW_BUDGET", 25)

CURRENCY = "USD"
CURRENCY_SYMBOL = "$"
COMPANY = "Northwind Analytics Pvt. Ltd."
