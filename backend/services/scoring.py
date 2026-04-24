"""
Service de scoring par quantiles typologiques.
Version patchée : calcul BPE par 10k hab pour EPCI (agrégation des communes membres).
"""
from __future__ import annotations

import bisect
import csv
from collections import defaultdict
from pathlib import Path
from typing import Optional

from ..config import DATA_DIR

INDICATEURS_CSV = DATA_DIR / "indicateurs_export.csv"
BPE_CSV = DATA_DIR / "bpe_communes.csv"


INDICATEURS_SENS = {
    "densite_brute":         +1,
    "artif_par_hab":         -1,
    "part_art_habitat":      -1,
    "dens_popclc":           +1,
    "ges_total_par_hab":     -1,
    "ges_transport_par_hab": -1,
    "conso_energie_par_hab": -1,
    "bpe_total_par_10k":     +1,
    "bpe_commerces_par_10k": +1,
    "bpe_sante_par_10k":     +1,
    "bpe_enseignement_par_10k": +1,
    "bpe_sport_culture_par_10k": +1,
    "part_actifs":           +1,
    "revenu_median":         +1,
    "taux_pauvrete":         -1,
    "rapport_interdecile":   -1,
    "part_imposes":          +1,
}

INDICATEUR_COLONNE = {
    "densite_brute":          ("calcul", "P21_POP / SURFKM2"),
    "artif_par_hab":          ("calcul", "art15naf21 / P21_POP"),
    "part_art_habitat":       ("col", "PartArtHabitat"),
    "dens_popclc":            ("col", "02b_DENS_POPCLC"),
    "ges_total_par_hab":      ("calcul", "(GES_tot_HorsTransp + ROUTE) / P21_POP"),
    "ges_transport_par_hab":  ("calcul", "ROUTE / P21_POP"),
    "conso_energie_par_hab":  ("calcul", "TOTAL_FLUX / P21_POP"),
    "part_actifs":            ("calcul", "P21_ACTOCC1564 / P21_POP"),
    "revenu_median":          ("col", "revenu_median"),
    "taux_pauvrete":          ("col", "taux_pauvrete"),
    "rapport_interdecile":    ("col", "rapport_interdecile"),
    "part_imposes":           ("col", "part_imposes"),
}

# Mapping codes BPE → domaine du CSV (utilisé pour calculer le ratio par 10k hab à la volée)
BPE_DOMAINES = {
    "bpe_total_par_10k":         "total",
    "bpe_commerces_par_10k":     "commerces",
    "bpe_sante_par_10k":         "sante",
    "bpe_enseignement_par_10k":  "enseignement",
    "bpe_sport_culture_par_10k": "sport_culture",
}

PONDERATIONS_DIMENSIONS = {
    "struct": {
        "densite_brute":     30,
        "artif_par_hab":     35,
        "part_art_habitat":  20,
        "dens_popclc":       15,
    },
    "access": {
        "bpe_total_par_10k":         30,
        "bpe_commerces_par_10k":     15,
        "bpe_sante_par_10k":         20,
        "bpe_enseignement_par_10k":  20,
        "bpe_sport_culture_par_10k": 15,
    },
    "env": {
        "ges_transport_par_hab": 45,
        "ges_total_par_hab":     30,
        "conso_energie_par_hab": 25,
    },
    "socio": {
        "revenu_median":       25,
        "taux_pauvrete":       25,
        "rapport_interdecile": 15,
        "part_imposes":        10,
        "part_actifs":         25,
    },
}

PONDERATIONS_GLOBALES = {
    "struct": 20,
    "access": 20,
    "mob":    0,
    "env":    30,
    "socio":  10,
    "gouv":   0,
}

TYPOLOGIE_GROUPES = {
    "grand_pole":     [111, 112],
    "moyen_pole":     [211, 212, 221, 222],
    "multipol":       [120, 300],
    "hors_influence": [400],
}

LIBELLES_TYPO = {
    "grand_pole":     "Grand pôle urbain et couronne",
    "moyen_pole":     "Pôle moyen ou petit",
    "multipol":       "Territoire multipolarisé",
    "hors_influence": "Hors influence des pôles",
    "national":       "Ensemble national",
}

_cache = {
    "loaded": False,
    "communes_data": {},
    "quantiles": {},
    "sorted_values": {},
    "sorted_national": {},
    "bpe": {},
}


def _to_float(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _get_groupe(cataeu) -> str:
    if cataeu is None:
        return "hors_influence"
    try:
        code = int(float(str(cataeu)))
    except (ValueError, TypeError):
        return "hors_influence"
    for groupe, codes in TYPOLOGIE_GROUPES.items():
        if code in codes:
            return groupe
    return "hors_influence"


def _compute_indicateur_value(data: dict, code: str) -> Optional[float]:
    if code.startswith("bpe_"):
        return None
    defn = INDICATEUR_COLONNE.get(code)
    if not defn:
        return None
    kind, spec = defn
    if kind == "col":
        return _to_float(data.get(spec))
    if kind == "calcul":
        try:
            expr = spec
            for var in ["P21_POP", "SURFKM2", "GES_tot_HorsTransp", "ROUTE",
                        "art15naf21", "TOTAL_FLUX", "P21_ACTOCC1564"]:
                val = _to_float(data.get(var))
                if val is None:
                    return None
                expr = expr.replace(var, str(val))
            result = eval(expr, {"__builtins__": {}}, {})
            return float(result) if result is not None else None
        except (ZeroDivisionError, ValueError, SyntaxError, TypeError):
            return None
    return None


def _compute_bpe_per_10k(bpe_row: dict, pop: Optional[float], domaine: str) -> Optional[float]:
    if not pop or pop <= 0:
        return None
    count = bpe_row.get(domaine, 0)
    return count / pop * 10000


def _quantiles(values: list, ps=(20, 40, 60, 80)) -> list:
    if not values:
        return [None] * len(ps)
    sorted_v = sorted(v for v in values if v is not None)
    n = len(sorted_v)
    if n < 5:
        return [None] * len(ps)
    result = []
    for p in ps:
        i = int(round(n * p / 100)) - 1
        i = max(0, min(n - 1, i))
        result.append(sorted_v[i])
    return result


def _load() -> None:
    if _cache["loaded"]:
        return

    if not INDICATEURS_CSV.exists():
        raise FileNotFoundError(f"Fichier {INDICATEURS_CSV} introuvable.")
    communes = {}
    with open(INDICATEURS_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            codgeo = str(row.get("CODGEO", "")).strip()
            if not codgeo:
                continue
            data = {}
            for k in ["P21_POP", "P15_POP", "SURFKM2", "PartArtHabitat", "02b_DENS_POPCLC",
                      "GES_tot_HorsTransp", "ROUTE", "TOTAL_FLUX", "art15naf21",
                      "P21_ACTOCC1564"]:
                data[k] = _to_float(row.get(k))
            data["cataeu"] = row.get("CATAEU2010", "")
            data["groupe"] = _get_groupe(row.get("CATAEU2010"))
            data["epci"] = str(row.get("EPCI", "")).strip()
            data["libgeo"] = row.get("LIBGEO", "")
            communes[codgeo] = data
    _cache["communes_data"] = communes

    if BPE_CSV.exists():
        bpe_data = {}
        with open(BPE_CSV, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                codgeo = str(row.get("CODGEO", "")).strip()
                if not codgeo:
                    continue
                try:
                    bpe_data[codgeo] = {
                        "services":       int(row.get("services", 0) or 0),
                        "commerces":      int(row.get("commerces", 0) or 0),
                        "enseignement":   int(row.get("enseignement", 0) or 0),
                        "sante":          int(row.get("sante", 0) or 0),
                        "transport":      int(row.get("transport", 0) or 0),
                        "sport_culture":  int(row.get("sport_culture", 0) or 0),
                        "tourisme":       int(row.get("tourisme", 0) or 0),
                        "total":          int(row.get("total", 0) or 0),
                    }
                except (ValueError, TypeError):
                    pass
        _cache["bpe"] = bpe_data

    filosofi_csv = DATA_DIR / "filosofi_communes.csv"
    if filosofi_csv.exists():
        cols_filo = ["revenu_median", "taux_pauvrete", "rapport_interdecile",
                     "part_imposes", "part_presta_sociales"]
        with open(filosofi_csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = str(row.get("codgeo", "")).strip()
                if code in communes:
                    for c in cols_filo:
                        communes[code][c] = _to_float(row.get(c))

    values_by_group = defaultdict(lambda: defaultdict(list))
    values_national = defaultdict(list)

    for codgeo, data in communes.items():
        groupe = data["groupe"]
        for code in INDICATEURS_SENS.keys():
            if code.startswith("bpe_"):
                continue
            val = _compute_indicateur_value(data, code)
            if val is not None:
                values_by_group[groupe][code].append(val)
                values_national[code].append(val)
        bpe_row = _cache["bpe"].get(codgeo, {})
        pop = data.get("P21_POP")
        for dom, code_front in [
            ("total", "bpe_total_par_10k"),
            ("commerces", "bpe_commerces_par_10k"),
            ("sante", "bpe_sante_par_10k"),
            ("enseignement", "bpe_enseignement_par_10k"),
            ("sport_culture", "bpe_sport_culture_par_10k"),
        ]:
            val = _compute_bpe_per_10k(bpe_row, pop, dom)
            if val is not None:
                values_by_group[groupe][code_front].append(val)
                values_national[code_front].append(val)

    quantiles = {}
    for groupe, by_ind in values_by_group.items():
        quantiles[groupe] = {}
        for code, vals in by_ind.items():
            quantiles[groupe][code] = _quantiles(vals)
    quantiles["national"] = {}
    for code, vals in values_national.items():
        quantiles["national"][code] = _quantiles(vals)
    _cache["quantiles"] = quantiles

    sorted_by_group = {}
    for groupe, by_ind in values_by_group.items():
        sorted_by_group[groupe] = {code: sorted(v for v in vals if v is not None)
                                   for code, vals in by_ind.items()}
    _cache["sorted_values"] = sorted_by_group
    _cache["sorted_national"] = {code: sorted(v for v in vals if v is not None)
                                 for code, vals in values_national.items()}

    _cache["loaded"] = True


def _percentile_rank(val: float, sorted_values: list) -> Optional[float]:
    if not sorted_values:
        return None
    n = len(sorted_values)
    idx = bisect.bisect_right(sorted_values, val)
    return round(100 * idx / n, 1)


def _score_from_rank(rang: float, sens: int) -> float:
    return rang if sens == +1 else 100 - rang


# ============================================================
# NOUVEAU : calcul de la valeur BPE pour un territoire (commune ou EPCI)
# ============================================================
def _compute_bpe_value_for_territoire(territoire: dict, code_bpe: str) -> Optional[float]:
    """
    Pour une commune : ratio direct.
    Pour un EPCI : agrégation (somme équipements / somme pop * 10000).
    """
    domaine = BPE_DOMAINES.get(code_bpe)
    if not domaine:
        return None

    if territoire["type"] == "commune":
        codgeo = territoire["code"]
        bpe_row = _cache["bpe"].get(codgeo, {})
        data = _cache["communes_data"].get(codgeo, {})
        pop = data.get("P21_POP")
        return _compute_bpe_per_10k(bpe_row, pop, domaine)

    # EPCI
    codes = territoire.get("codes_communes", [])
    if not codes:
        return None
    total_equip = 0
    total_pop = 0.0
    for c in codes:
        bpe_row = _cache["bpe"].get(c, {})
        data = _cache["communes_data"].get(c, {})
        pop = data.get("P21_POP") or 0
        if pop > 0:
            total_equip += bpe_row.get(domaine, 0)
            total_pop += pop
    if total_pop <= 0:
        return None
    return total_equip / total_pop * 10000


def get_scoring_for_territoire(territoire: dict, indicateurs_locaux: dict, bpe_ind: dict) -> dict:
    try:
        _load()
    except FileNotFoundError as e:
        return {"_erreur": str(e)}

    if territoire["type"] == "commune":
        data = _cache["communes_data"].get(territoire["code"])
        groupe = data["groupe"] if data else "hors_influence"
    else:
        codes = territoire.get("codes_communes", [])
        if codes:
            counts = defaultdict(float)
            for c in codes:
                if c in _cache["communes_data"]:
                    d = _cache["communes_data"][c]
                    counts[d["groupe"]] += d.get("P21_POP") or 0
            groupe = max(counts.keys(), key=counts.get) if counts else "hors_influence"
        else:
            groupe = "hors_influence"

    quantiles_groupe = _cache["quantiles"].get(groupe, _cache["quantiles"].get("national", {}))
    sorted_groupe = _cache["sorted_values"].get(groupe, {})
    sorted_national = _cache["sorted_national"]

    scores_indicateurs = {}
    for code, sens in INDICATEURS_SENS.items():
        # === RÉSOLUTION DE LA VALEUR ===
        val = None

        # 1. Cas BPE : on calcule nous-mêmes (commune OU EPCI agrégé)
        if code in BPE_DOMAINES:
            val = _compute_bpe_value_for_territoire(territoire, code)

        # 2. Sinon : on cherche dans les dictionnaires fournis
        if val is None and code in indicateurs_locaux:
            v = indicateurs_locaux[code]
            val = v.get("valeur") if isinstance(v, dict) else v

        if val is None and code in bpe_ind:
            v = bpe_ind[code]
            val = v.get("valeur") if isinstance(v, dict) else v

        if val is None:
            continue

        sorted_typo_vals = sorted_groupe.get(code, [])
        if len(sorted_typo_vals) < 10:
            sorted_typo_vals = sorted_national.get(code, [])
            groupe_effectif = "national"
        else:
            groupe_effectif = groupe
        rang_typo = _percentile_rank(val, sorted_typo_vals)
        rang_national = _percentile_rank(val, sorted_national.get(code, []))

        if rang_typo is None and rang_national is None:
            continue

        score = _score_from_rank(rang_typo if rang_typo is not None else rang_national, sens)
        score_national = _score_from_rank(rang_national, sens) if rang_national is not None else None

        scores_indicateurs[code] = {
            "score": round(score, 1),
            "score_national": round(score_national, 1) if score_national is not None else None,
            "rang_typo": rang_typo,
            "rang_national": rang_national,
            "valeur": val,
            "quantiles": quantiles_groupe.get(code),
            "sens": sens,
            "groupe": groupe_effectif,
            "libelle_typo": LIBELLES_TYPO.get(groupe_effectif, groupe_effectif),
            "n_typo": len(sorted_typo_vals),
            "n_national": len(sorted_national.get(code, [])),
        }

    scores_dimensions = {}
    for dim, ponds in PONDERATIONS_DIMENSIONS.items():
        total_weight, total_score = 0, 0
        inds_detail = []
        for code, weight in ponds.items():
            if code in scores_indicateurs:
                total_score += scores_indicateurs[code]["score"] * weight
                total_weight += weight
                inds_detail.append({"code": code, "score": scores_indicateurs[code]["score"], "poids": weight})
        if total_weight > 0:
            score = total_score / total_weight
            scores_dimensions[dim] = {
                "score": round(score, 1),
                "grade": _grade(score),
                "indicateurs_utilises": inds_detail,
            }
        else:
            scores_dimensions[dim] = {"score": None, "grade": "nd", "indicateurs_utilises": []}

    total_w, total_s = 0, 0
    for dim, weight in PONDERATIONS_GLOBALES.items():
        if dim in scores_dimensions and scores_dimensions[dim]["score"] is not None:
            total_s += scores_dimensions[dim]["score"] * weight
            total_w += weight
    if total_w > 0:
        score_global = round(total_s / total_w, 1)
    else:
        score_global = None

    return {
        "scores_indicateurs": scores_indicateurs,
        "scores_dimensions": scores_dimensions,
        "score_global": {
            "valeur": score_global,
            "grade": _grade(score_global) if score_global is not None else "nd",
            "groupe_typo": groupe,
            "libelle_typo": LIBELLES_TYPO.get(groupe, groupe),
        },
        "meta": {
            "ponderations_dimensions": PONDERATIONS_DIMENSIONS,
            "ponderations_globales": PONDERATIONS_GLOBALES,
            "avertissement": "Scoring indicatif V1. À valider avec Fabien Rosa.",
        },
    }


def _grade(score: Optional[float]) -> str:
    if score is None: return "nd"
    if score >= 65: return "high"
    if score >= 45: return "mid"
    return "low"
