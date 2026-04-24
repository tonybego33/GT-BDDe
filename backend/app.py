"""
Backend FastAPI du GT BDDe.

Routes principales :
  GET  /                          → health check
  GET  /territoire/{code}         → métadonnées + contour (geo.api.gouv.fr)
  GET  /indicateurs/{code}        → diagnostic multicritère (Indicateurs_GT_BDDe)
  GET  /indicateurs/def           → définition des indicateurs exposés
  GET  /gouvernance/indicateurs   → liste des indicateurs manuels
  POST /gouvernance/{code}        → saisie d'un indicateur manuel

Lancement :
    python -m uvicorn backend.app:app --reload --host 0.0.0.0
"""
from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .config import APP_TITLE, APP_VERSION
from .services import geo as geo_service
from .services import gouvernance as gouv_service
from .services import indicateurs_locaux as local_service
from .services import bpe as bpe_service
from .services import filosofi as filosofi_service
from .services import scoring as scoring_service
from .services import carto as carto_service


DIMENSIONS_META = {
    "struct": {"libelle": "Structure territoriale", "ordre": 1},
    "access": {"libelle": "Accessibilité et maillage", "ordre": 2},
    "mob":    {"libelle": "Mobilité", "ordre": 3},
    "env":    {"libelle": "Performance environnementale", "ordre": 4},
    "socio":  {"libelle": "Structure socio-économique", "ordre": 5},
    "gouv":   {"libelle": "Gouvernance", "ordre": 6},
}


app = FastAPI(title=APP_TITLE, version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"app": APP_TITLE, "version": APP_VERSION, "status": "ok"}


@app.get("/search")
async def search(q: str = "", limit: int = 10):
    if not q or len(q.strip()) < 2:
        return {"results": []}
    try:
        results = await geo_service.search_territoires(q.strip(), limit=limit)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erreur recherche : {e}")
    return {"results": results}


@app.get("/territoire/{code}")
async def territoire(code: str):
    try:
        t = await geo_service.resolve(code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return t


@app.get("/indicateurs/def")
def indicateurs_def():
    return {
        "indicateurs_locaux": local_service.list_indicateurs_def(),
        "indicateurs_filosofi": filosofi_service.list_indicateurs_def(),
        "indicateurs_gouvernance": gouv_service.INDICATEURS_GOUVERNANCE,
        "dimensions": DIMENSIONS_META,
    }


@app.get("/indicateurs/{code}")
async def indicateurs(code: str):
    try:
        t = await geo_service.resolve(code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))

    local_indicateurs = local_service.get_indicateurs(t)
    local_error = local_indicateurs.pop("_erreur", None)

    bpe_indicateurs = bpe_service.get_indicateurs(t)
    bpe_error = bpe_indicateurs.pop("_erreur", None)

    filosofi_indicateurs = filosofi_service.get_indicateurs(t)
    filosofi_error = filosofi_indicateurs.pop("_erreur", None)

    gouv_list = gouv_service.indicateurs_gouvernance(t)

    dimensions = {}
    for dim_code, meta in DIMENSIONS_META.items():
        dimensions[dim_code] = {
            "libelle": meta["libelle"],
            "ordre": meta["ordre"],
            "indicateurs": [],
        }

    for ind_code, ind_data in local_indicateurs.items():
        dim = ind_data.get("dimension")
        if dim and dim in dimensions:
            dimensions[dim]["indicateurs"].append({"code": ind_code, **ind_data})

    for ind_code, ind_data in bpe_indicateurs.items():
        dim = ind_data.get("dimension")
        if dim and dim in dimensions:
            dimensions[dim]["indicateurs"].append({"code": ind_code, **ind_data})

    for ind_code, ind_data in filosofi_indicateurs.items():
        dim = ind_data.get("dimension")
        if dim and dim in dimensions:
            dimensions[dim]["indicateurs"].append({"code": ind_code, **ind_data})

    for g in gouv_list:
        dimensions["gouv"]["indicateurs"].append({
            "code": g["code"],
            "libelle": g["libelle"],
            "valeur": g["valeur"],
            "valeur_formatee": g["valeur"] if g["valeur"] else None,
            "unite": g["unite"],
            "source": "Saisie manuelle GT BDDe",
            "statut": g["statut"],
            "type_saisie": g["type"],
            "remplisseur": g.get("remplisseur"),
            "saisie_at": g.get("saisie_at"),
            "source_url": g.get("source_url"),
            "mode": "manuel",
        })

    for dim_code in ["access", "mob"]:
        if not dimensions[dim_code]["indicateurs"]:
            dimensions[dim_code]["statut"] = "a_brancher"
            dimensions[dim_code]["note"] = {
                "access": "Sera alimenté par BPE (INSEE) et GTFS des AOM.",
                "mob": "En attente discussion avec Félix Pouchain (outil Mobility).",
            }[dim_code]

    try:
        indicateurs_pour_scoring = {**local_indicateurs, **filosofi_indicateurs}
        scoring = scoring_service.get_scoring_for_territoire(t, indicateurs_pour_scoring, bpe_indicateurs)
        scoring_error = scoring.get("_erreur")
    except Exception as e:
        scoring = {}
        scoring_error = str(e)

    if "scores_indicateurs" in scoring:
        scores_ind = scoring["scores_indicateurs"]
        for dim_code, dim in dimensions.items():
            for ind in dim.get("indicateurs", []):
                code = ind.get("code")
                if code in scores_ind:
                    s = scores_ind[code]
                    ind["score"] = s["score"]
                    ind["score_national"] = s.get("score_national")
                    ind["rang_typo"] = s.get("rang_typo")
                    ind["rang_national"] = s.get("rang_national")
                    ind["libelle_typo"] = s.get("libelle_typo")
                    ind["n_typo"] = s.get("n_typo")
                    ind["n_national"] = s.get("n_national")
                    ind["quantiles"] = s["quantiles"]
                    ind["sens"] = s["sens"]

    if "scores_dimensions" in scoring:
        for dim_code, score_dim in scoring["scores_dimensions"].items():
            if dim_code in dimensions and score_dim["score"] is not None:
                dimensions[dim_code]["score"] = score_dim["score"]
                dimensions[dim_code]["grade"] = score_dim["grade"]

    response = {
        "territoire": {
            "type": t["type"],
            "code": t["code"],
            "nom": t["nom"],
            "population": t.get("population"),
            "superficie_km2": t.get("superficie_km2"),
            "nb_communes": t.get("nb_communes"),
        },
        "dimensions": dimensions,
        "score_global": scoring.get("score_global"),
        "scoring_meta": scoring.get("meta"),
    }
    if local_error:
        response["_warning_indicateurs_locaux"] = local_error
    if bpe_error:
        response["_warning_bpe"] = bpe_error
    if filosofi_error:
        response["_warning_filosofi"] = filosofi_error
    if scoring_error:
        response["_warning_scoring"] = scoring_error
    return response


class GouvValueIn(BaseModel):
    indicateur_code: str
    valeur: Optional[str] = None
    source_url: Optional[str] = None
    remplisseur: Optional[str] = None


@app.post("/gouvernance/{code}")
async def set_gouv(code: str, payload: GouvValueIn):
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
    return gouv_service.INDICATEURS_GOUVERNANCE


@app.get("/carto/{code}")
async def carto(code: str, layers: Optional[str] = None):
    try:
        t = await geo_service.resolve(code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))

    requested = None
    if layers:
        requested = [x.strip() for x in layers.split(",") if x.strip() in ("bpe", "tc", "velo")]
    return carto_service.get_layers_for_territoire(t, requested)


@app.get("/app")
def frontend():
    return FileResponse("frontend/index.html")