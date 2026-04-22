"""Service geo.api.gouv.fr : résolution de codes territoriaux et contours."""
from __future__ import annotations

import re
from typing import Any, Optional

import httpx

from ..cache_store import get as cache_get, set_ as cache_set
from ..config import GEO_API_BASE

CODE_INSEE_COMMUNE = re.compile(r"^\d[\dAB]\d{3}$")  # 5 car., gère 2A/2B Corse
CODE_SIREN_EPCI = re.compile(r"^\d{9}$")


def detect_type(code: str) -> str:
    """Renvoie 'commune' | 'epci' | 'unknown'."""
    code = code.strip().upper()
    if CODE_INSEE_COMMUNE.match(code):
        return "commune"
    if CODE_SIREN_EPCI.match(code):
        return "epci"
    return "unknown"


async def _fetch(client: httpx.AsyncClient, url: str, params: dict) -> Any:
    key = f"{url}?{httpx.QueryParams(params)}"
    cached = cache_get("geo", key)
    if cached is not None:
        return cached
    r = await client.get(url, params=params, timeout=20.0)
    r.raise_for_status()
    data = r.json()
    cache_set("geo", key, data)
    return data


async def resolve(code: str) -> dict:
    """
    Résout un code (commune ou EPCI) vers ses métadonnées et son contour.
    Renvoie un dict normalisé avec : type, code, nom, population, superficie_km2,
    nb_communes, contour (GeoJSON), codes_communes (si EPCI).
    """
    ttype = detect_type(code)
    if ttype == "unknown":
        raise ValueError(f"Code non reconnu : {code!r}. Attendu : 5 chiffres (commune) ou 9 chiffres (SIREN EPCI).")

    async with httpx.AsyncClient(base_url=GEO_API_BASE) as client:
        if ttype == "commune":
            data = await _fetch(
                client, "/communes",
                {"code": code, "fields": "nom,code,population,surface,centre,contour,codeEpci,epci", "format": "json", "geometry": "contour"},
            )
            if not data:
                raise LookupError(f"Commune {code} introuvable.")
            c = data[0]
            return {
                "type": "commune",
                "code": c["code"],
                "nom": c["nom"],
                "population": c.get("population"),
                "superficie_km2": (c.get("surface") or 0) / 100.0,  # surface en hectares → km²
                "nb_communes": 1,
                "centre": c.get("centre"),
                "contour": c.get("contour"),
                "epci_rattachement": {
                    "code": c.get("codeEpci"),
                    "nom": (c.get("epci") or {}).get("nom") if isinstance(c.get("epci"), dict) else None,
                },
                "codes_communes": [c["code"]],
            }

        # EPCI
        data = await _fetch(
            client, "/epcis",
            {"code": code, "fields": "nom,code,type,populationTotale,surface,centre,contour", "format": "json", "geometry": "contour"},
        )
        if not data:
            raise LookupError(f"EPCI {code} introuvable.")
        e = data[0]
        communes = await _fetch(
            client, f"/epcis/{code}/communes",
            {"fields": "nom,code,population", "format": "json"},
        )
        return {
            "type": "epci",
            "code": e["code"],
            "nom": e["nom"],
            "type_epci": e.get("type"),  # CA, CU, CC, METRO
            "population": e.get("populationTotale"),
            "superficie_km2": (e.get("surface") or 0) / 100.0,
            "nb_communes": len(communes),
            "centre": e.get("centre"),
            "contour": e.get("contour"),
            "codes_communes": [c["code"] for c in communes],
            "communes": communes,  # détail pour reventilation éventuelle
        }


async def search_territoires(q: str, limit: int = 10) -> list[dict]:
    """
    Recherche par nom. Renvoie une liste mixte commune + EPCI triée par pertinence
    (EPCI d'abord si match exact, puis communes par population décroissante).

    Chaque item : {type, code, nom, libelle, population, sublibelle}
      - libelle   : texte principal affiché (nom du territoire)
      - sublibelle: ligne secondaire (département / nb communes / etc.)
    """
    q = (q or "").strip()
    if len(q) < 2:
        return []

    async with httpx.AsyncClient(base_url=GEO_API_BASE) as client:
        # Requêtes en parallèle : communes + EPCI
        import asyncio
        comm_task = _fetch(
            client, "/communes",
            {
                "nom": q,
                "fields": "nom,code,codeDepartement,codesPostaux,population",
                "boost": "population",
                "limit": limit,
            },
        )
        epci_task = _fetch(
            client, "/epcis",
            {
                "nom": q,
                "fields": "nom,code,type,populationTotale",
                "limit": max(3, limit // 2),
            },
        )
        try:
            communes, epcis = await asyncio.gather(comm_task, epci_task)
        except Exception:
            communes, epcis = [], []

    results = []

    # EPCI en tête (en général moins nombreux et plus pertinents pour GT BDDe)
    for e in epcis or []:
        type_label = {"CA": "Communauté d'agglomération", "CU": "Communauté urbaine",
                      "CC": "Communauté de communes", "METRO": "Métropole"}.get(e.get("type"), "EPCI")
        pop = e.get("populationTotale")
        sub = type_label
        if pop:
            sub += f" · {pop:,} hab.".replace(",", " ")
        results.append({
            "type": "epci",
            "code": e["code"],
            "nom": e["nom"],
            "libelle": e["nom"],
            "sublibelle": sub,
        })

    # Communes
    for c in communes or []:
        cp = (c.get("codesPostaux") or [""])[0]
        dept = c.get("codeDepartement") or ""
        pop = c.get("population")
        sub_parts = []
        if cp:
            sub_parts.append(cp)
        if dept:
            sub_parts.append(f"dép. {dept}")
        if pop:
            sub_parts.append(f"{pop:,} hab.".replace(",", " "))
        results.append({
            "type": "commune",
            "code": c["code"],
            "nom": c["nom"],
            "libelle": c["nom"],
            "sublibelle": " · ".join(sub_parts) if sub_parts else "Commune",
        })

    return results[:limit]
