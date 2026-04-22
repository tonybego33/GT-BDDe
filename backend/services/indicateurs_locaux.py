"""
Service indicateurs locaux.

Lit un fichier CSV pré-compilé depuis l'Excel Indicateurs_GT_BDDe.xlsx
(feuille EXPORT) et sert les indicateurs par code commune ou par code EPCI
(avec agrégation automatique : somme des valeurs des communes membres).

Pour générer le CSV depuis l'Excel, utiliser le script
`scripts/convert_xlsx_to_csv.py` (voir plus bas dans ce fichier).

Structure du CSV attendu (header ligne 1) :
    TYPE_com,GEO_com,CODGEO,LIBGEO,CATAEU2010,EPCI,LIBEPCI,DEP,REG,
    P15_POP,P21_POP,SURFM2,SURFHA,SURFKM2,TOTALCLC11,TOTALCLC11a13,
    naf09art23,art09hab23,art09inc23,PartArtHabitat,art15naf21,
    GES_tot_HorsTransp,GES_agri,CO2_BIOMASSE,DECHETS,ENERGIE,INDUSTRIE,
    RESID,ROUTE,TERTIAIRE,Gaz,Electricité,TOTAL_FLUX,P21_ACTOCC1564,
    02a_DENS_POP,02b_DENS_POPCLC,03_ART_POPSUP,04_GES_POP,05_ENERGIE_POP
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional

from ..config import DATA_DIR


# Chemin du CSV pré-compilé
INDICATEURS_CSV = DATA_DIR / "indicateurs_export.csv"


# Définition des indicateurs exposés.
# Pour chaque indicateur :
#   - col : colonne dans le CSV
#   - label : libellé affiché
#   - unite : unité d'affichage
#   - dimension : dimension GT BDDe (struct, access, mob, env, socio, gouv)
#   - agregation : somme | moyenne_ponderee_pop | derive (calculé depuis d'autres)
#   - format : "int" | "float1" | "float2" | "percent"
INDICATEURS_DEF = [
    # === Structure territoriale ===
    {"code": "population_2021", "col": "P21_POP", "label": "Population 2021", "unite": "hab.",
     "dimension": "struct", "agregation": "somme", "format": "int",
     "source": "INSEE Recensement 2021"},
    {"code": "population_2015", "col": "P15_POP", "label": "Population 2015", "unite": "hab.",
     "dimension": "struct", "agregation": "somme", "format": "int",
     "source": "INSEE Recensement 2015"},
    {"code": "superficie_km2", "col": "SURFKM2", "label": "Superficie", "unite": "km²",
     "dimension": "struct", "agregation": "somme", "format": "float2",
     "source": "IGN Admin Express"},
    {"code": "densite_brute", "col": None, "label": "Densité brute", "unite": "hab/km²",
     "dimension": "struct", "agregation": "derive", "format": "float1",
     "formule": "P21_POP / SURFKM2",
     "source": "Calcul INSEE + IGN"},
    # === Artificialisation ===
    {"code": "artif_naf09_23", "col": "naf09art23", "label": "Consommation ENAF 2009→2023", "unite": "m²",
     "dimension": "struct", "agregation": "somme", "format": "int",
     "source": "Artificialisation développement durable"},
    {"code": "artif_habitat_09_23", "col": "art09hab23", "label": "Artificialisation habitat 2009→2023", "unite": "m²",
     "dimension": "struct", "agregation": "somme", "format": "int",
     "source": "Artificialisation développement durable"},
    {"code": "artif_infra_09_23", "col": "art09inc23", "label": "Artificialisation infrastructures 2009→2023", "unite": "m²",
     "dimension": "struct", "agregation": "somme", "format": "int",
     "source": "Artificialisation développement durable"},
    {"code": "part_art_habitat", "col": "PartArtHabitat", "label": "Part artificialisation habitat", "unite": "",
     "dimension": "struct", "agregation": "moyenne_ponderee_pop", "format": "percent",
     "source": "Artificialisation développement durable"},
    {"code": "artif_15_21", "col": "art15naf21", "label": "Artificialisation 2015→2021", "unite": "m²",
     "dimension": "struct", "agregation": "somme", "format": "int",
     "source": "Artificialisation développement durable"},
    {"code": "artif_par_hab", "col": None, "label": "Artificialisation 2015→2021 par habitant", "unite": "m²/hab",
     "dimension": "struct", "agregation": "derive", "format": "float1",
     "formule": "art15naf21 / P21_POP",
     "source": "Calcul"},
    {"code": "dens_popclc", "col": "02b_DENS_POPCLC", "label": "Densité sur zones artificialisées (CLC)", "unite": "hab/km²",
     "dimension": "struct", "agregation": "moyenne_ponderee_pop", "format": "float1",
     "source": "Calcul CLC + INSEE"},
    {"code": "totalclc11", "col": "TOTALCLC11", "label": "Surface CLC artif (nomenclature 11)", "unite": "m²",
     "dimension": "struct", "agregation": "somme", "format": "int",
     "source": "Corine Land Cover"},
    {"code": "totalclc11a13", "col": "TOTALCLC11a13", "label": "Surface CLC artif étendue (11 à 13)", "unite": "m²",
     "dimension": "struct", "agregation": "somme", "format": "int",
     "source": "Corine Land Cover"},
    # === Environnement / GES ===
    {"code": "ges_total", "col": None, "label": "GES total (tous secteurs)", "unite": "tCO₂eq",
     "dimension": "env", "agregation": "derive", "format": "int",
     "formule": "GES_tot_HorsTransp + ROUTE",
     "source": "ADEME IGT"},
    {"code": "ges_hors_transport", "col": "GES_tot_HorsTransp", "label": "GES hors transport", "unite": "tCO₂eq",
     "dimension": "env", "agregation": "somme", "format": "int",
     "source": "ADEME IGT"},
    {"code": "ges_agri", "col": "GES_agri", "label": "GES agriculture", "unite": "tCO₂eq",
     "dimension": "env", "agregation": "somme", "format": "int",
     "source": "ADEME IGT"},
    {"code": "ges_route", "col": "ROUTE", "label": "GES transport routier", "unite": "tCO₂eq",
     "dimension": "env", "agregation": "somme", "format": "int",
     "source": "ADEME IGT"},
    {"code": "ges_resid", "col": "RESID", "label": "GES résidentiel", "unite": "tCO₂eq",
     "dimension": "env", "agregation": "somme", "format": "int",
     "source": "ADEME IGT"},
    {"code": "ges_tertiaire", "col": "TERTIAIRE", "label": "GES tertiaire", "unite": "tCO₂eq",
     "dimension": "env", "agregation": "somme", "format": "int",
     "source": "ADEME IGT"},
    {"code": "ges_industrie", "col": "INDUSTRIE", "label": "GES industrie", "unite": "tCO₂eq",
     "dimension": "env", "agregation": "somme", "format": "int",
     "source": "ADEME IGT"},
    {"code": "ges_energie", "col": "ENERGIE", "label": "GES production énergie", "unite": "tCO₂eq",
     "dimension": "env", "agregation": "somme", "format": "int",
     "source": "ADEME IGT"},
    {"code": "ges_dechets", "col": "DECHETS", "label": "GES déchets", "unite": "tCO₂eq",
     "dimension": "env", "agregation": "somme", "format": "int",
     "source": "ADEME IGT"},
    {"code": "co2_biomasse", "col": "CO2_BIOMASSE", "label": "CO₂ biomasse", "unite": "tCO₂eq",
     "dimension": "env", "agregation": "somme", "format": "int",
     "source": "ADEME IGT"},
    {"code": "ges_transport_par_hab", "col": None, "label": "Émissions transport par habitant", "unite": "tCO₂eq/hab",
     "dimension": "env", "agregation": "derive", "format": "float2",
     "formule": "ROUTE / P21_POP",
     "source": "Calcul"},
    {"code": "ges_total_par_hab", "col": None, "label": "GES total par habitant", "unite": "tCO₂eq/hab",
     "dimension": "env", "agregation": "derive", "format": "float2",
     "formule": "(GES_tot_HorsTransp + ROUTE) / P21_POP",
     "source": "Calcul"},
    # === Énergie ===
    {"code": "conso_gaz", "col": "Gaz", "label": "Consommation gaz", "unite": "MWh",
     "dimension": "env", "agregation": "somme", "format": "int",
     "source": "GRDF"},
    {"code": "conso_elec", "col": "Electricité", "label": "Consommation électricité", "unite": "MWh",
     "dimension": "env", "agregation": "somme", "format": "int",
     "source": "RTE"},
    {"code": "total_flux_energie", "col": "TOTAL_FLUX", "label": "Flux énergie total", "unite": "MWh",
     "dimension": "env", "agregation": "somme", "format": "int",
     "source": "RTE + GRDF"},
    {"code": "conso_energie_par_hab", "col": None, "label": "Consommation énergie par habitant", "unite": "MWh/hab",
     "dimension": "env", "agregation": "derive", "format": "float2",
     "formule": "TOTAL_FLUX / P21_POP",
     "source": "Calcul"},
    # === Socio-éco ===
    {"code": "actifs_occupes_15_64", "col": "P21_ACTOCC1564", "label": "Actifs occupés 15-64 ans", "unite": "pers.",
     "dimension": "socio", "agregation": "somme", "format": "int",
     "source": "INSEE Recensement 2021"},
    {"code": "part_actifs", "col": None, "label": "Part d'actifs occupés dans la population", "unite": "",
     "dimension": "socio", "agregation": "derive", "format": "percent",
     "formule": "P21_ACTOCC1564 / P21_POP",
     "source": "Calcul"},
    # === Indicateurs de synthèse (déjà calculés dans le fichier) ===
    {"code": "indic_02a_dens_pop", "col": "02a_DENS_POP", "label": "Indicateur 02a - Densité population", "unite": "",
     "dimension": "struct", "agregation": "moyenne_ponderee_pop", "format": "float2",
     "source": "Calcul AREP"},
    {"code": "indic_03_art_popsup", "col": "03_ART_POPSUP", "label": "Indicateur 03 - Artificialisation / pop surface", "unite": "",
     "dimension": "struct", "agregation": "moyenne_ponderee_pop", "format": "float2",
     "source": "Calcul AREP"},
    {"code": "indic_04_ges_pop", "col": "04_GES_POP", "label": "Indicateur 04 - GES par habitant", "unite": "",
     "dimension": "env", "agregation": "moyenne_ponderee_pop", "format": "float2",
     "source": "Calcul AREP"},
    {"code": "indic_05_energie_pop", "col": "05_ENERGIE_POP", "label": "Indicateur 05 - Énergie par habitant", "unite": "",
     "dimension": "env", "agregation": "moyenne_ponderee_pop", "format": "float2",
     "source": "Calcul AREP"},
]


# === Cache mémoire des données ===
_cache = {"by_codgeo": None, "by_epci": None, "headers": None}


def _to_float(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _load_csv() -> None:
    """Charge le CSV en mémoire une fois pour toutes."""
    if _cache["by_codgeo"] is not None:
        return
    if not INDICATEURS_CSV.exists():
        raise FileNotFoundError(
            f"Fichier {INDICATEURS_CSV} introuvable. "
            "Lance 'python scripts/convert_xlsx_to_csv.py' pour le générer depuis l'Excel."
        )
    by_codgeo = {}
    by_epci = {}
    with open(INDICATEURS_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        _cache["headers"] = reader.fieldnames
        for row in reader:
            codgeo = str(row.get("CODGEO", "")).strip()
            if not codgeo:
                continue
            # Convertir les colonnes numériques en float
            parsed = dict(row)
            for k, v in row.items():
                if k not in ("TYPE_com", "GEO_com", "CODGEO", "LIBGEO", "CATAEU2010",
                             "EPCI", "LIBEPCI", "DEP", "REG"):
                    parsed[k] = _to_float(v)
            by_codgeo[codgeo] = parsed
            epci = str(row.get("EPCI", "")).strip()
            if epci:
                by_epci.setdefault(epci, []).append(parsed)
    _cache["by_codgeo"] = by_codgeo
    _cache["by_epci"] = by_epci


def _get_commune_data(codgeo: str) -> Optional[dict]:
    _load_csv()
    return _cache["by_codgeo"].get(codgeo)


def _get_epci_rows(epci_code: str) -> list:
    _load_csv()
    return _cache["by_epci"].get(epci_code, [])


def _aggregate(rows: list, col: str, mode: str, pop_col: str = "P21_POP") -> Optional[float]:
    """Agrège une colonne sur une liste de lignes (communes)."""
    if not rows:
        return None
    if mode == "somme":
        total = sum((r[col] or 0) for r in rows if r.get(col) is not None)
        return total if total != 0 or any(r.get(col) for r in rows) else None
    if mode == "moyenne_ponderee_pop":
        num, den = 0.0, 0.0
        for r in rows:
            v, p = r.get(col), r.get(pop_col)
            if v is not None and p is not None:
                num += v * p
                den += p
        return num / den if den > 0 else None
    return None


def _compute_derive(formule: str, data: dict) -> Optional[float]:
    """Calcule une formule simple comme 'P21_POP / SURFKM2' ou '(A + B) / C'."""
    try:
        # Remplacer les noms de colonnes par les valeurs
        expr = formule
        # On remplace les noms les plus longs en premier pour éviter les collisions
        cols = sorted(
            ["P21_POP", "SURFKM2", "GES_tot_HorsTransp", "ROUTE", "art15naf21",
             "TOTAL_FLUX", "P21_ACTOCC1564"],
            key=len, reverse=True,
        )
        for c in cols:
            val = data.get(c)
            if val is None or val == 0:
                # Division par zéro possible : on renvoie None
                if f"/ {c}" in expr or f"/{c}" in expr:
                    return None
            expr = expr.replace(c, str(val) if val is not None else "0")
        result = eval(expr, {"__builtins__": {}}, {})
        return float(result)
    except (ValueError, ZeroDivisionError, SyntaxError, TypeError):
        return None


def _format_value(v: Optional[float], fmt: str) -> Optional[str]:
    if v is None:
        return None
    if fmt == "int":
        return f"{round(v):,}".replace(",", " ")
    if fmt == "float1":
        return f"{v:,.1f}".replace(",", " ").replace(".", ",")
    if fmt == "float2":
        return f"{v:,.2f}".replace(",", " ").replace(".", ",")
    if fmt == "percent":
        # Si v est un ratio (0-1), on multiplie par 100. Sinon on suppose déjà en %.
        if abs(v) <= 1.0:
            v = v * 100
        return f"{v:.1f} %".replace(".", ",")
    return str(v)


def _build_aggregated_data(rows: list) -> dict:
    """Construit un dict avec les sommes de base pour pouvoir calculer les dérivés."""
    if not rows:
        return {}
    base_cols = ["P21_POP", "P15_POP", "SURFKM2", "GES_tot_HorsTransp", "ROUTE",
                 "art15naf21", "TOTAL_FLUX", "P21_ACTOCC1564"]
    agg = {}
    for c in base_cols:
        agg[c] = _aggregate(rows, c, "somme")
    return agg


def get_indicateurs(territoire: dict) -> dict:
    """
    Point d'entrée du service.
    territoire = dict {'type': 'commune'|'epci', 'code': '...', ...}
    Renvoie un dict {code_indicateur: {valeur, valeur_brute, libelle, unite, source, dimension, statut}}.
    """
    try:
        _load_csv()
    except FileNotFoundError as e:
        return {"_erreur": str(e)}

    if territoire["type"] == "commune":
        data = _get_commune_data(territoire["code"])
        if not data:
            return {"_erreur": f"Commune {territoire['code']} absente du fichier Indicateurs_GT_BDDe."}
        base = data
        rows = [data]
    else:
        rows = _get_epci_rows(territoire["code"])
        if not rows:
            return {"_erreur": f"EPCI {territoire['code']} absent du fichier Indicateurs_GT_BDDe."}
        base = _build_aggregated_data(rows)

    result = {}
    for ind in INDICATEURS_DEF:
        val = None
        if ind["agregation"] == "derive":
            val = _compute_derive(ind["formule"], base)
        elif ind["col"]:
            val = _aggregate(rows, ind["col"], ind["agregation"])
        result[ind["code"]] = {
            "valeur": val,
            "valeur_formatee": _format_value(val, ind["format"]),
            "libelle": ind["label"],
            "unite": ind["unite"],
            "source": ind["source"],
            "dimension": ind["dimension"],
            "statut": "ok" if val is not None else "indisponible",
        }
    return result


def list_indicateurs_def() -> list:
    """Liste les indicateurs exposés avec leur métadonnée, pour une route /indicateurs/def."""
    return [
        {k: v for k, v in ind.items() if k not in ("formule",)}
        for ind in INDICATEURS_DEF
    ]
