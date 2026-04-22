"""
Service Accessibilité / Maillage · Base Permanente des Équipements (BPE).

Source : BPE 2023 (INSEE) via bpe23-nettoye (Île-de-France Smart Services).
Le shapefile de ~1 Go a été pré-agrégé par commune × domaine (7 domaines)
dans le fichier backend/data/bpe_communes.csv via le script
scripts/convert_bpe_to_csv.py.

7 domaines BPE :
  - services        (A) services pour les particuliers
  - commerces       (B) commerces
  - enseignement    (C) écoles, collèges, lycées, supérieur
  - sante           (D) santé et action sociale
  - transport       (E) transports et déplacements (gares, arrêts)
  - sport_culture   (F) sports, loisirs, culture
  - tourisme        (G) hébergement, offices de tourisme
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional

from ..config import DATA_DIR

BPE_CSV = DATA_DIR / "bpe_communes.csv"

DOMAINES = ["services", "commerces", "enseignement", "sante",
            "transport", "sport_culture", "tourisme"]

LIBELLES = {
    "services": "Services pour les particuliers",
    "commerces": "Commerces",
    "enseignement": "Enseignement",
    "sante": "Santé et action sociale",
    "transport": "Transports et déplacements",
    "sport_culture": "Sports, loisirs, culture",
    "tourisme": "Tourisme",
}

_cache = {"by_codgeo": None}


def _load() -> None:
    if _cache["by_codgeo"] is not None:
        return
    if not BPE_CSV.exists():
        raise FileNotFoundError(
            f"Fichier {BPE_CSV} introuvable. "
            "Lance 'python scripts/convert_bpe_to_csv.py bpe23-nettoye.shp' pour le générer."
        )
    data = {}
    with open(BPE_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            codgeo = str(row.get("CODGEO", "")).strip()
            if not codgeo:
                continue
            parsed = {}
            for d in DOMAINES:
                try:
                    parsed[d] = int(row.get(d, 0) or 0)
                except (TypeError, ValueError):
                    parsed[d] = 0
            try:
                parsed["total"] = int(row.get("total", 0) or 0)
            except (TypeError, ValueError):
                parsed["total"] = sum(parsed[d] for d in DOMAINES)
            data[codgeo] = parsed
    _cache["by_codgeo"] = data


def _get_counts_for_commune(codgeo: str) -> Optional[dict]:
    _load()
    return _cache["by_codgeo"].get(codgeo)


def _get_counts_for_epci(codes_communes: list) -> dict:
    """Somme les équipements de toutes les communes de l'EPCI."""
    _load()
    agg = {d: 0 for d in DOMAINES}
    agg["total"] = 0
    for code in codes_communes:
        c = _cache["by_codgeo"].get(str(code))
        if c:
            for d in DOMAINES:
                agg[d] += c[d]
            agg["total"] += c["total"]
    return agg


def get_indicateurs(territoire: dict) -> dict:
    """
    Renvoie les indicateurs BPE d'un territoire.
    territoire : dict avec au moins 'type', 'code' et (pour les EPCI) 'codes_communes'.
    """
    try:
        _load()
    except FileNotFoundError as e:
        return {"_erreur": str(e)}

    if territoire["type"] == "commune":
        counts = _get_counts_for_commune(territoire["code"])
        if not counts:
            return {"_erreur": f"Commune {territoire['code']} absente de la BPE."}
    else:
        codes = territoire.get("codes_communes", []) or []
        if not codes:
            return {"_erreur": "Liste des communes membres de l'EPCI non disponible."}
        counts = _get_counts_for_epci(codes)

    pop = territoire.get("population") or 0
    result = {}

    # Total équipements
    result["bpe_total"] = {
        "valeur": counts["total"],
        "valeur_formatee": f"{counts['total']:,}".replace(",", " "),
        "libelle": "Total équipements BPE",
        "unite": "équip.",
        "source": "INSEE BPE 2023",
        "dimension": "access",
        "statut": "ok",
    }
    # Équipements pour 10 000 habitants
    if pop > 0:
        ratio = counts["total"] / pop * 10000
        result["bpe_total_par_10k"] = {
            "valeur": round(ratio, 1),
            "valeur_formatee": f"{ratio:,.1f}".replace(",", " ").replace(".", ","),
            "libelle": "Équipements pour 10 000 habitants",
            "unite": "équip./10k hab",
            "source": "INSEE BPE 2023 + RP 2021",
            "dimension": "access",
            "statut": "ok",
        }
    # Par domaine
    for d in DOMAINES:
        result[f"bpe_{d}"] = {
            "valeur": counts[d],
            "valeur_formatee": f"{counts[d]:,}".replace(",", " "),
            "libelle": f"Équipements · {LIBELLES[d]}",
            "unite": "équip.",
            "source": "INSEE BPE 2023",
            "dimension": "access",
            "statut": "ok",
        }
        # Ratio par 10k hab pour les domaines clés
        if pop > 0 and d in ("commerces", "sante", "enseignement", "sport_culture"):
            r = counts[d] / pop * 10000
            result[f"bpe_{d}_par_10k"] = {
                "valeur": round(r, 2),
                "valeur_formatee": f"{r:,.2f}".replace(",", " ").replace(".", ","),
                "libelle": f"{LIBELLES[d]} pour 10 000 hab",
                "unite": "équip./10k hab",
                "source": "INSEE BPE 2023 + RP 2021",
                "dimension": "access",
                "statut": "ok",
            }
    return result
