"""Configuration centralisée."""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent

load_dotenv(ROOT_DIR / ".env")

# --- INSEE ---
INSEE_CONSUMER_KEY = os.getenv("INSEE_CONSUMER_KEY", "").strip()
INSEE_CONSUMER_SECRET = os.getenv("INSEE_CONSUMER_SECRET", "").strip()
INSEE_TOKEN_URL = "https://api.insee.fr/token"
INSEE_DONNEES_LOCALES_BASE = "https://api.insee.fr/donnees-locales/V0.1"

# --- GEO (pas d'auth) ---
GEO_API_BASE = "https://geo.api.gouv.fr"

# --- Paths ---
CACHE_DIR = BASE_DIR / "cache"
CACHE_DIR.mkdir(exist_ok=True)
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
GOUVERNANCE_DB = DATA_DIR / "gouvernance.db"

# --- Cache ---
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "86400"))

# --- App ---
APP_TITLE = "GT BDDe · Backend de diagnostic territorial"
APP_VERSION = "0.1.0"
