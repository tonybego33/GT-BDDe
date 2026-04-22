"""Cache disque simple avec TTL. Pour éviter de retaper les APIs inutilement."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Optional

from .config import CACHE_DIR, CACHE_TTL_SECONDS


def _key_path(namespace: str, key: str) -> Path:
    h = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    return CACHE_DIR / f"{namespace}_{h}.json"


def get(namespace: str, key: str, ttl: Optional[int] = None) -> Optional[Any]:
    """Récupère une entrée du cache si elle existe et n'est pas expirée."""
    path = _key_path(namespace, key)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    ttl = ttl if ttl is not None else CACHE_TTL_SECONDS
    if time.time() - raw.get("_t", 0) > ttl:
        return None
    return raw.get("value")


def set_(namespace: str, key: str, value: Any) -> None:
    """Stocke une valeur dans le cache."""
    path = _key_path(namespace, key)
    payload = {"_t": time.time(), "_k": key, "value": value}
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
