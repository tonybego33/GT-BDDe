"""
Service Filosofi : revenu médian, pauvreté, inégalités (INSEE Filosofi 2021).

Lit les 2 CSV compacts générés par scripts/convert_filosofi_to_csv.py :
  backend/data/filosofi_communes.csv
  backend/data/filosofi_epci.csv

Pour les EPCI, on utilise DIRECTEMENT la valeur déjà agrégée par l'INSEE
(pas de recalcul maison, car les indicateurs Filosofi sont non sommables).
Pour les communes, on lit la ligne du code commune.

Note : les petites communes peuvent manquer certaines valeurs à cause du
secret statistique INSEE (moins de 11 ménages fiscaux).
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional

from ..config import DATA_DIR


FILOSOFI_COMMUNES = DATA_DIR / "filosofi_communes.csv"
FILOSOFI_EPCI = DATA_DIR / "filosofi_epci.csv"


# Indicateurs exposés côté frontend (dimension socio)
INDICATEURS_DEF = [
    {
        "code": "revenu_median",
        "col": "revenu_median",
        "label": "Revenu médian disponible par UC",
        "unite": "€/an",
        "format": "int_euro",
        "source": "INSEE Filosofi 2021",
    },
    {
        "code": "taux_pauvrete",
        "col": "taux_pauvrete",
        "label": "Taux de pauvreté (seuil 60 %)",
        "unite": "%",
        "format": "float1",
        "source": "INSEE Filosofi 2021",
    },
    {
        "code": "rapport_interdecile",
        "col": "rapport_interdecile",
        "label": "Rapport interdécile D9/D1",
        "unite": "",
        "format": "float1",
        "source": "INSEE Filosofi 2021",
    },
    {
        "code": "part_imposes",
        "col": "part_imposes",
        "label": "Part des ménages imposés",
        "unite": "%",
        "format": "float1",
        "source": "INSEE Filosofi 2021",
    },
    {
        "code": "part_presta_sociales",
        "col": "part_presta_sociales",
        "label": "Part des prestations sociales dans le revenu",
        "unite": "%",
        "format": "float1",
        "source": "INSEE Filosofi 2021",
    },
]


_cache = {"communes": None, "epci": None}


def _to_float(v) -> Optional[float]:
    if v is None or v == "" or v == "s" or v == "nd":
        return None
    try:
        return float(str(v).replace(",", ".").replace(" ", ""))
    except (TypeError, ValueError):
        return None


def _load(path: Path) -> dict:
    """Charge un CSV Filosofi en dict {codgeo: {col: value, ...}}."""
    if not path.exists():
        return {}
    out = {}
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = (row.get("codgeo") or "").strip()
            if not code:
                continue
            out[code] = {k: _to_float(v) for k, v in row.items()
                         if k not in ("codgeo", "libgeo")}
            out[code]["libgeo"] = row.get("libgeo", "")
    return out


def _ensure_loaded() -> None:
    if _cache["communes"] is None:
        _cache["communes"] = _load(FILOSOFI_COMMUNES)
    if _cache["epci"] is None:
        _cache["epci"] = _load(FILOSOFI_EPCI)


def _format_value(v: Optional[float], fmt: str) -> Optional[str]:
    if v is None:
        return None
    if fmt == "int_euro":
        return f"{round(v):,}".replace(",", " ") + " €"
    if fmt == "float1":
        return f"{v:,.1f}".replace(",", " ").replace(".", ",")
    if fmt == "float2":
        return f"{v:,.2f}".replace(",", " ").replace(".", ",")
    return str(v)


def get_indicateurs(territoire: dict) -> dict:
    """
    Retourne les indicateurs Filosofi pour un territoire.
    Format compatible avec indicateurs_locaux et bpe (dict {code: {valeur, ...}}).
    """
    _ensure_loaded()

    if not _cache["communes"] and not _cache["epci"]:
        return {"_erreur": "Fichiers Filosofi absents. Lance "
                          "'python scripts/convert_filosofi_to_csv.py <zip>' pour les générer."}

    if territoire["type"] == "commune":
        data = _cache["communes"].get(territoire["code"])
    else:
        data = _cache["epci"].get(territoire["code"])

    if not data:
        # Pas de donnée : commune trop petite (secret stat) ou EPCI absent
        return {}

    result = {}
    for ind in INDICATEURS_DEF:
        val = data.get(ind["col"])
        result[ind["code"]] = {
            "valeur": val,
            "valeur_formatee": _format_value(val, ind["format"]),
            "libelle": ind["label"],
            "unite": ind["unite"],
            "source": ind["source"],
            "dimension": "socio",
            "statut": "ok" if val is not None else "indisponible",
        }
    return result


def list_indicateurs_def() -> list:
    """Pour la route /indicateurs/def."""
    return [
        {"code": ind["code"], "label": ind["label"], "unite": ind["unite"],
         "source": ind["source"], "dimension": "socio"}
        for ind in INDICATEURS_DEF
    ]
