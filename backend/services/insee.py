"""
Service INSEE Données Locales (api.insee.fr).

L'API demande un jeton OAuth2 obtenu depuis le couple consumer_key/consumer_secret.
Les données sont organisées en "cubes" (RP pour recensement, FILO pour Filosofi revenus, etc.).

Doc : https://portail-api.insee.fr/catalog/api/3d577cf9-d081-4054-977c-f9d081b054b2
"""
from __future__ import annotations

import base64
import time
from typing import Any, Optional

import httpx

from ..cache_store import get as cache_get, set_ as cache_set
from ..config import (
    INSEE_CONSUMER_KEY,
    INSEE_CONSUMER_SECRET,
    INSEE_TOKEN_URL,
    INSEE_DONNEES_LOCALES_BASE,
)


# --- OAuth token management --------------------------------------------------
_token_cache: dict = {"token": None, "expires_at": 0.0}


async def _get_token() -> str:
    """Récupère un jeton OAuth2, en le cachant en mémoire jusqu'à expiration."""
    if not INSEE_CONSUMER_KEY or not INSEE_CONSUMER_SECRET:
        raise RuntimeError(
            "INSEE_CONSUMER_KEY / INSEE_CONSUMER_SECRET non renseignés. "
            "Copie .env.example en .env et remplis-les."
        )
    # Token en mémoire encore valide ?
    if _token_cache["token"] and time.time() < _token_cache["expires_at"] - 30:
        return _token_cache["token"]

    auth = base64.b64encode(
        f"{INSEE_CONSUMER_KEY}:{INSEE_CONSUMER_SECRET}".encode("utf-8")
    ).decode("ascii")
    async with httpx.AsyncClient() as client:
        r = await client.post(
            INSEE_TOKEN_URL,
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials"},
            timeout=15.0,
        )
        r.raise_for_status()
        payload = r.json()

    _token_cache["token"] = payload["access_token"]
    _token_cache["expires_at"] = time.time() + int(payload.get("expires_in", 3600))
    return _token_cache["token"]


# --- Appel aux cubes INSEE ---------------------------------------------------
async def _get_cube(
    cube: str,
    geo_type: str,     # "COM" (commune) ou "EPCI"
    geo_code: str,
    *,
    modalite: Optional[str] = None,
) -> Any:
    """
    Appelle l'API Données Locales.
    Endpoint type : /donnees/{cube}/{geoType}-{geoCode}[?modalite=...]
    geoType : COM, EPCI, DEP, REG, FE, etc.
    """
    token = await _get_token()
    path = f"/donnees/{cube}/{geo_type}-{geo_code}"
    params = {}
    if modalite:
        params["modalite"] = modalite
    key = f"{path}?{httpx.QueryParams(params)}"
    cached = cache_get("insee", key)
    if cached is not None:
        return cached
    async with httpx.AsyncClient(base_url=INSEE_DONNEES_LOCALES_BASE) as client:
        r = await client.get(
            path,
            params=params,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=30.0,
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        data = r.json()
    cache_set("insee", key, data)
    return data


def _geo_type(territoire_type: str) -> str:
    """Convertit type interne → type INSEE."""
    return "COM" if territoire_type == "commune" else "EPCI"


# --- Indicateurs haut niveau -------------------------------------------------
async def population_legale(territoire: dict) -> Optional[int]:
    """
    Population légale millésimée via le cube GEOpop (recensement).
    Si indisponible, fallback sur la pop fournie par geo.api.gouv.fr.
    """
    gt = _geo_type(territoire["type"])
    try:
        data = await _get_cube("GEOpop2021RP2021", gt, territoire["code"])
        if data and "Cellule" in data:
            # Structure type : liste de cellules avec une valeur principale
            cells = data["Cellule"]
            if isinstance(cells, list) and cells:
                val = cells[0].get("Valeur")
                return int(float(val)) if val is not None else None
    except Exception:
        pass
    return territoire.get("population")


async def indicateurs_structure(territoire: dict) -> dict:
    """
    Indicateurs dimension "Structure territoriale" disponibles directement via INSEE.
    - Densité (hab/km²) calculée depuis population + superficie
    - Taux de logements vacants, taux résidences principales (indicatifs)
    - Indice de dispersion de l'habitat : EN SUSPENS (méthode non arrêtée)
    """
    pop = await population_legale(territoire) or territoire.get("population")
    surface = territoire.get("superficie_km2")
    densite = None
    if pop and surface and surface > 0:
        densite = round(pop / surface, 1)

    return {
        "densite_hab_km2": {
            "valeur": densite,
            "unite": "hab/km²",
            "source": "INSEE Recensement + geo.api.gouv.fr",
            "millesime": 2021,
        },
        "dispersion_habitat": {
            "valeur": None,
            "statut": "en_suspens",
            "note": "Méthode de calcul non arrêtée (cf. note du 9 mars : 'surface urbanisée / surface totale' correspond au taux d'artificialisation, pas à un indice de dispersion au sens propre).",
        },
        "artificialisation_hab": {
            "valeur": None,
            "statut": "a_brancher",
            "note": "À brancher sur CEREMA Fichiers Fonciers ou IGN OCS GE. Voir service à créer.",
        },
    }


async def indicateurs_socio(territoire: dict) -> dict:
    """
    Indicateurs socio-éco via INSEE Filosofi et Recensement.
    Pour l'instant squelette — on branchera les cubes exacts en itérant.
    """
    # TODO cube Filosofi : FILO pour revenus médians
    # TODO cube RP : part actifs stables dans leur aire
    return {
        "revenu_median": {
            "valeur": None,
            "statut": "a_brancher",
            "source_cible": "INSEE Filosofi (cube FILO)",
        },
        "part_emplois_epci": {
            "valeur": None,
            "statut": "a_brancher",
            "source_cible": "INSEE RP exploitation complémentaire (lieu de travail)",
        },
    }
