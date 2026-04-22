"""
Service INSEE Melodi.

L'API Melodi (https://api.insee.fr/melodi) remplace l'ancienne API Données Locales.
Pas besoin d'authentification — accès libre, limite 30 requêtes/minute.

Doc : https://www.insee.fr/fr/information/8203036
Catalogue des jeux de données : https://catalogue-donnees.insee.fr/fr/catalogue/recherche
"""
from __future__ import annotations

from typing import Any, Optional

import httpx

from ..cache_store import get as cache_get, set_ as cache_set


MELODI_BASE = "https://api.insee.fr/melodi"


# ============================================================================
# Appel générique Melodi
# ============================================================================
async def _fetch(dataset: str, params: dict) -> Any:
    """
    Appelle l'endpoint /melodi/data/{dataset} avec les paramètres donnés.
    Cache disque pour éviter de retaper l'API à chaque rechargement.
    """
    cache_key = f"{dataset}?{httpx.QueryParams(params)}"
    cached = cache_get("melodi", cache_key)
    if cached is not None:
        return cached
    async with httpx.AsyncClient(base_url=MELODI_BASE, timeout=20.0) as client:
        r = await client.get(f"/data/{dataset}", params=params, headers={"Accept": "application/json"})
        if r.status_code == 404:
            return None
        if r.status_code == 429:
            raise RuntimeError("Limite Melodi atteinte (30 req/min). Reessaie dans une minute.")
        r.raise_for_status()
        data = r.json()
    cache_set("melodi", cache_key, data)
    return data


def _geo_code_for(territoire: dict) -> str:
    """
    Convertit notre type interne en code GEO Melodi.
    Communes : code INSEE direct. EPCI : prefixe 'EPCI-'.
    """
    if territoire["type"] == "commune":
        return territoire["code"]
    return f"EPCI-{territoire['code']}"


def _extract_first_value(payload: Any) -> Optional[float]:
    """
    Helper pour recuperer la premiere observation d'un payload Melodi.
    Structure type :
      { "observations": [ { "value": "...", "GEO": "...", ... }, ... ] }
    """
    if not payload:
        return None
    obs = payload.get("observations") or payload.get("data") or []
    if not obs:
        return None
    first = obs[0]
    val = first.get("value") or first.get("OBS_VALUE")
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


# ============================================================================
# Indicateurs haut niveau
# ============================================================================
async def population_legale(territoire: dict) -> Optional[int]:
    """
    Population legale (recensement principal).
    Dataset : DS_RP_POPULATION_PRINC.
    Fallback : population fournie par geo.api.gouv.fr.
    """
    geo = _geo_code_for(territoire)
    try:
        data = await _fetch(
            "DS_RP_POPULATION_PRINC",
            {"GEO": geo, "maxResult": 5},
        )
        val = _extract_first_value(data)
        if val is not None:
            return int(val)
    except Exception as e:
        print(f"[melodi] population_legale fallback (raison: {e})")
    return territoire.get("population")


async def indicateurs_structure(territoire: dict) -> dict:
    """
    Dimension Structure territoriale.
    """
    pop = await population_legale(territoire)
    surface = territoire.get("superficie_km2")
    densite = None
    if pop and surface and surface > 0:
        densite = round(pop / surface, 1)

    return {
        "densite_hab_km2": {
            "valeur": densite,
            "unite": "hab/km2",
            "source": "INSEE Melodi (DS_RP_POPULATION_PRINC) + geo.api.gouv.fr",
            "millesime": "RP 2021",
            "statut": "ok" if densite is not None else "indisponible",
        },
        "dispersion_habitat": {
            "valeur": None,
            "statut": "en_suspens",
            "note": ("Methode de calcul non arretee. La formule donnee dans la note du 9 mars "
                     "(surface urbanisee / surface totale) correspond plutot au taux "
                     "d'artificialisation qu'a un indice de dispersion au sens strict."),
        },
        "artificialisation_hab": {
            "valeur": None,
            "statut": "a_brancher",
            "source_cible": "CEREMA Fichiers Fonciers ou IGN OCS GE",
        },
    }


async def indicateurs_socio(territoire: dict) -> dict:
    """
    Dimension Structure socio-economique. Squelette a completer.
    """
    return {
        "revenu_median": {
            "valeur": None,
            "statut": "a_brancher",
            "source_cible": "INSEE Filosofi via Melodi",
        },
        "part_emplois_dans_aire": {
            "valeur": None,
            "statut": "a_brancher",
            "source_cible": "INSEE RP exploitation complementaire",
        },
    }
