"""
Service cartographie : couches pour la carte interactive.

3 couches :
  - BPE géolocalisée : via fichier local bpe_geo.jsonl (indexé par commune)
  - Arrêts de transport en commun : via API Overpass OpenStreetMap
  - Pistes cyclables : via API Overpass OpenStreetMap

Renvoie du GeoJSON prêt à être affiché par Leaflet.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import httpx

from ..cache_store import get as cache_get, set_ as cache_set
from ..config import DATA_DIR

BPE_GEO_JSONL = DATA_DIR / "bpe_geo.jsonl"

# Mapping lettre domaine → nom
DOMAINE_NAMES = {
    "A": "services", "B": "commerces", "C": "enseignement",
    "D": "sante", "E": "transport", "F": "sport_culture", "G": "tourisme",
}
DOMAINE_COLORS = {
    "services":       "#8e44ad",
    "commerces":      "#d35400",
    "enseignement":   "#27ae60",
    "sante":          "#c0392b",
    "transport":      "#2980b9",
    "sport_culture":  "#f39c12",
    "tourisme":       "#16a085",
}

# Cache en mémoire du JSONL (chargé paresseusement)
_cache_bpe = {"by_codgeo": None}


def _load_bpe() -> None:
    if _cache_bpe["by_codgeo"] is not None:
        return
    if not BPE_GEO_JSONL.exists():
        _cache_bpe["by_codgeo"] = {}
        return
    by_com = {}
    with open(BPE_GEO_JSONL, "r", encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line)
                by_com[obj["codgeo"]] = obj["items"]
            except (ValueError, KeyError):
                continue
    _cache_bpe["by_codgeo"] = by_com


def get_bpe_geojson(codes_communes: list, domaines: Optional[list] = None) -> dict:
    """
    Retourne un GeoJSON FeatureCollection des équipements BPE pour une liste de
    communes. Filtre optionnel sur les domaines (liste de noms : services,
    commerces, enseignement, sante, transport, sport_culture, tourisme).
    """
    _load_bpe()
    if not _cache_bpe["by_codgeo"]:
        return {
            "type": "FeatureCollection",
            "features": [],
            "_warning": "Fichier BPE géolocalisée absent. Lance "
                        "`python scripts/convert_bpe_geo_to_jsonl.py BPE24.csv` pour l'activer.",
        }
    keep_domaines = set(domaines) if domaines else set(DOMAINE_NAMES.values())
    features = []
    for code in codes_communes:
        items = _cache_bpe["by_codgeo"].get(str(code), [])
        for lon, lat, typequ in items:
            dom_letter = typequ[:1].upper() if typequ else ""
            domaine = DOMAINE_NAMES.get(dom_letter)
            if not domaine or domaine not in keep_domaines:
                continue
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "typequ": typequ,
                    "domaine": domaine,
                    "color": DOMAINE_COLORS.get(domaine, "#888"),
                },
            })
    return {"type": "FeatureCollection", "features": features}


# ============================================================
# Couches OSM via Overpass
# ============================================================

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

OVERPASS_HEADERS = {
    "User-Agent": "GT-BDDe/0.2 (Sciences Po Bordeaux / AREP - projet de diagnostic territorial)",
    "Accept": "application/json",
    "Accept-Encoding": "gzip, deflate",
}


def _overpass_query(query: str, cache_key: str) -> Optional[dict]:
    """Exécute une requête Overpass avec cache disque et fallback sur miroirs."""
    cached = cache_get("overpass", cache_key)
    if cached is not None:
        return cached
    last_error = None
    for url in OVERPASS_ENDPOINTS:
        try:
            with httpx.Client(timeout=60.0, headers=OVERPASS_HEADERS) as client:
                r = client.post(url, data={"data": query})
                r.raise_for_status()
                data = r.json()
                cache_set("overpass", cache_key, data)
                return data
        except Exception as e:
            last_error = f"{url} -> {e}"
            continue
    return {"_error": last_error or "Overpass indisponible", "elements": []}


def _bbox_around(lat: float, lon: float, radius_km: float = 15) -> tuple:
    """Retourne une bbox (south, west, north, east) autour d'un point."""
    # Approximation : 1° ≈ 111 km
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(0.1, abs(0.7)))  # cos approximé pour la France
    return (lat - dlat, lon - dlon, lat + dlat, lon + dlon)


def get_tc_arrets(bbox: tuple) -> dict:
    """Arrêts de bus/tram/métro dans une bbox. bbox = (south, west, north, east)."""
    s, w, n, e = bbox
    key = f"tc_{s:.3f}_{w:.3f}_{n:.3f}_{e:.3f}"
    # Requête Overpass : arrêts de transport (public_transport=stop_position OU highway=bus_stop OU railway=tram_stop)
    query = f"""
[out:json][timeout:45];
(
  node["highway"="bus_stop"]({s},{w},{n},{e});
  node["railway"="tram_stop"]({s},{w},{n},{e});
  node["public_transport"="stop_position"]({s},{w},{n},{e});
  node["amenity"="bus_station"]({s},{w},{n},{e});
);
out body;
"""
    data = _overpass_query(query, key)
    if not data or "_error" in data:
        return {"type": "FeatureCollection", "features": [], "_error": data.get("_error") if data else "?"}
    features = []
    for el in data.get("elements", []):
        if el.get("type") != "node":
            continue
        tags = el.get("tags", {})
        type_tc = "bus"
        if tags.get("railway") == "tram_stop":
            type_tc = "tram"
        elif tags.get("amenity") == "bus_station":
            type_tc = "gare_routiere"
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [el["lon"], el["lat"]]},
            "properties": {
                "name": tags.get("name", ""),
                "type": type_tc,
                "operator": tags.get("operator", ""),
            },
        })
    return {"type": "FeatureCollection", "features": features}


def get_cyclable(bbox: tuple) -> dict:
    """Voies cyclables dans une bbox."""
    s, w, n, e = bbox
    key = f"velo_{s:.3f}_{w:.3f}_{n:.3f}_{e:.3f}"
    query = f"""
[out:json][timeout:60];
(
  way["highway"="cycleway"]({s},{w},{n},{e});
  way["cycleway"~"lane|track|opposite_lane|opposite_track"]({s},{w},{n},{e});
  way["cycleway:left"~"lane|track"]({s},{w},{n},{e});
  way["cycleway:right"~"lane|track"]({s},{w},{n},{e});
  way["bicycle"="designated"]({s},{w},{n},{e});
);
out geom;
"""
    data = _overpass_query(query, key)
    if not data or "_error" in data:
        return {"type": "FeatureCollection", "features": [], "_error": data.get("_error") if data else "?"}
    features = []
    for el in data.get("elements", []):
        if el.get("type") != "way" or "geometry" not in el:
            continue
        coords = [[pt["lon"], pt["lat"]] for pt in el["geometry"]]
        if len(coords) < 2:
            continue
        tags = el.get("tags", {})
        # Classifier grossièrement
        cat = "voie_partagee"
        if tags.get("highway") == "cycleway":
            cat = "piste_dediee"
        elif "track" in (tags.get("cycleway", "") + tags.get("cycleway:left", "") + tags.get("cycleway:right", "")):
            cat = "piste_dediee"
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {
                "name": tags.get("name", ""),
                "categorie": cat,
                "highway": tags.get("highway", ""),
            },
        })
    return {"type": "FeatureCollection", "features": features}


def get_layers_for_territoire(territoire: dict, layers: list = None) -> dict:
    """
    Agrège toutes les couches demandées pour un territoire.
    layers : liste parmi ["bpe", "tc", "velo"]. Si None, toutes.
    """
    layers = layers or ["bpe", "tc", "velo"]
    result = {}

    codes = []
    if territoire["type"] == "commune":
        codes = [territoire["code"]]
    else:
        codes = territoire.get("codes_communes") or []

    # Calcul de la bbox à partir du contour ou des centres
    bbox = _compute_bbox_from_territoire(territoire)

    if "bpe" in layers:
        result["bpe"] = get_bpe_geojson(codes)
    if "tc" in layers and bbox:
        result["tc"] = get_tc_arrets(bbox)
    if "velo" in layers and bbox:
        result["velo"] = get_cyclable(bbox)
    return result


def _compute_bbox_from_territoire(territoire: dict) -> Optional[tuple]:
    """Retourne une bbox (south, west, north, east) à partir du contour ou du centre."""
    contour = territoire.get("contour")
    if contour:
        try:
            # Parcourir toutes les coords du GeoJSON pour trouver la bbox
            lons, lats = [], []
            def walk(g):
                if isinstance(g, dict):
                    if g.get("type") in ("Polygon", "MultiPolygon"):
                        coords = g["coordinates"]
                        _flatten(coords, lons, lats)
                    elif "coordinates" in g:
                        _flatten(g["coordinates"], lons, lats)
                    for v in g.values():
                        if isinstance(v, (list, dict)):
                            walk(v)
                elif isinstance(g, list):
                    for v in g:
                        walk(v)
            walk(contour)
            if lons and lats:
                return (min(lats), min(lons), max(lats), max(lons))
        except Exception:
            pass
    # Fallback : centre + rayon
    centre = territoire.get("centre")
    if centre and centre.get("coordinates"):
        lon, lat = centre["coordinates"]
        return _bbox_around(lat, lon, 15)
    return None


def _flatten(coords, lons: list, lats: list) -> None:
    """Extrait récursivement toutes les paires (lon, lat) d'une structure GeoJSON."""
    if not isinstance(coords, list):
        return
    if len(coords) == 2 and all(isinstance(c, (int, float)) for c in coords):
        lons.append(coords[0]); lats.append(coords[1])
        return
    for c in coords:
        _flatten(c, lons, lats)
