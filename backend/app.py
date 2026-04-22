"""
Backend FastAPI du GT BDDe.
Routes principales :
  GET  /territoire/{code}   → métadonnées + contour
  GET  /indicateurs/{code}  → indicateurs par dimension
  POST /gouvernance/{code}  → saisie manuelle d'un indicateur de gouvernance

Lancement : uvicorn backend.app:app --reload
"""
from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import APP_TITLE, APP_VERSION
from .services import geo as geo_service
from .services import insee as insee_service
from .services import gouvernance as gouv_service

app = FastAPI(title=APP_TITLE, version=APP_VERSION)

# CORS : autorise un front local qui tape ce backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # en prod, restreindre au domaine du front
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Health ----------
@app.get("/")
def root():
    return {"app": APP_TITLE, "version": APP_VERSION, "status": "ok"}


# ---------- Territoire ----------
@app.get("/territoire/{code}")
async def territoire(code: str):
    """Résout un code commune (5 chiffres) ou EPCI (9 chiffres SIREN)."""
    try:
        t = await geo_service.resolve(code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return t


# ---------- Indicateurs ----------
@app.get("/indicateurs/{code}")
async def indicateurs(code: str):
    """
    Renvoie le diagnostic multicritère structuré en 6 dimensions.
    Les indicateurs non encore branchés sont marqués avec statut='a_brancher'
    ou 'en_suspens'. Aucune donnée n'est inventée.
    """
    try:
        t = await geo_service.resolve(code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Dimensions couvertes à ce stade (étape 1 du développement)
    struct = await insee_service.indicateurs_structure(t)
    socio = await insee_service.indicateurs_socio(t)
    gouv = gouv_service.indicateurs_gouvernance(t)

    return {
        "territoire": {
            "type": t["type"],
            "code": t["code"],
            "nom": t["nom"],
            "population": t.get("population"),
            "superficie_km2": t.get("superficie_km2"),
            "nb_communes": t.get("nb_communes"),
        },
        "dimensions": {
            "structure": {
                "libelle": "Structure territoriale",
                "indicateurs": struct,
            },
            "accessibilite": {
                "libelle": "Accessibilité et maillage",
                "statut": "a_brancher",
                "note": "Sera alimenté par BPE (INSEE) et GTFS des AOM. Service bpe.py à créer.",
            },
            "mobilite": {
                "libelle": "Mobilité",
                "statut": "en_suspens",
                "note": "En attente discussion avec Félix Pouchain (outil Mobility).",
            },
            "environnement": {
                "libelle": "Performance environnementale",
                "statut": "a_brancher",
                "note": "Sera alimenté par Inventaire GES Territorialisé (CITEPA). Service ges.py à créer.",
            },
            "socio_economique": {
                "libelle": "Structure socio-économique",
                "indicateurs": socio,
            },
            "gouvernance": {
                "libelle": "Gouvernance",
                "mode": "manuel",
                "indicateurs": gouv,
            },
        },
    }


# ---------- Gouvernance : saisie manuelle ----------
class GouvValueIn(BaseModel):
    indicateur_code: str
    valeur: Optional[str] = None
    source_url: Optional[str] = None
    remplisseur: Optional[str] = None


@app.post("/gouvernance/{code}")
async def set_gouv(code: str, payload: GouvValueIn):
    """Saisie / mise à jour d'une valeur d'indicateur de gouvernance."""
    try:
        t = await geo_service.resolve(code)
    except (ValueError, LookupError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    valid_codes = {i["code"] for i in gouv_service.INDICATEURS_GOUVERNANCE}
    if payload.indicateur_code not in valid_codes:
        raise HTTPException(
            status_code=400,
            detail=f"indicateur_code inconnu. Valides : {sorted(valid_codes)}",
        )
    gouv_service.set_value(
        t["type"], t["code"], payload.indicateur_code,
        payload.valeur, payload.source_url, payload.remplisseur,
    )
    return {"ok": True, "saved": payload.model_dump()}


@app.get("/gouvernance/indicateurs")
def list_gouv_indicateurs():
    """Liste les indicateurs de gouvernance disponibles (définition)."""
    return gouv_service.INDICATEURS_GOUVERNANCE
