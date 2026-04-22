"""Configuration centralisée."""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent

load_dotenv(ROOT_DIR / ".env")

# --- APIs publiques (pas d'auth) ---
GEO_API_BASE = "https://geo.api.gouv.fr"
MELODI_BASE = "https://api.insee.fr/melodi"

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
APP_VERSION = "0.2.0"
