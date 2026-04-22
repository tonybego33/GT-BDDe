"""
Service de scoring par quantiles typologiques.

Principe :
  1. Au 1er appel, on calcule pour chaque indicateur les valeurs par commune,
     groupées par typologie (colonne CATAEU2010 du CSV des indicateurs).
  2. Pour un territoire donné, on regarde son rang dans sa typologie
     et on attribue un score 0-100.
  3. On agrège en scores de dimension (moyenne pondérée), puis en score global.

Typologie CATAEU2010 (INSEE Aires d'Attraction des Villes 2010) :
  111 : Commune d'un grand pôle urbain (200k+ emplois)
  112 : Commune couronne grand pôle
  120 : Commune multipolarisée des grandes aires urbaines
  211 : Pôle moyen
  212 : Couronne pôle moyen
  221 : Petit pôle
  222 : Couronne petit pôle
  300 : Autre commune multipolarisée
  400 : Commune isolée hors influence des pôles

Pour un EPCI, on utilise la CATAEU2010 dominante (ville-centre).

Sens des indicateurs : +1 = plus = mieux, -1 = moins = mieux
Les indicateurs ambigus ne sont pas scorés (seulement affichés).
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from typing import Optional

from ..config import DATA_DIR

INDICATEURS_CSV = DATA_DIR / "indicateurs_export.csv"
BPE_CSV = DATA_DIR / "bpe_communes.csv"


# ============================================================
# CONFIGURATION SCORING (V1 indicative, à ajuster avec Fabien)
# ============================================================

# Sens des indicateurs : +1 = valeur haute = bon score
# Ne sont scorés que les indicateurs présents ici
INDICATEURS_SENS = {
    # Structure
    "densite_brute":         +1,  # + dense = + compact
    "artif_par_hab":         -1,  # - on étale, mieux c'est
    "part_art_habitat":      -1,  # - la part d'artif habitat
    "dens_popclc":           +1,  # densité sur zones urbanisées
    # Environnement
    "ges_total_par_hab":     -1,
    "ges_transport_par_hab": -1,
    "conso_energie_par_hab": -1,
    # Accessibilité
    "bpe_total_par_10k":     +1,
    "bpe_commerces_par_10k": +1,
    "bpe_sante_par_10k":     +1,
    "bpe_enseignement_par_10k": +1,
    "bpe_sport_culture_par_10k": +1,
    # Socio
    "part_actifs":           +1,
}

# Mapping code frontend → colonne CSV indicateurs (pour récup des valeurs)
INDICATEUR_COLONNE = {
    "densite_brute":          ("calcul", "P21_POP / SURFKM2"),
    "artif_par_hab":          ("calcul", "art15naf21 / P21_POP"),
    "part_art_habitat":       ("col", "PartArtHabitat"),
    "dens_popclc":            ("col", "02b_DENS_POPCLC"),
    "ges_total_par_hab":      ("calcul", "(GES_tot_HorsTransp + ROUTE) / P21_POP"),
    "ges_transport_par_hab":  ("calcul", "ROUTE / P21_POP"),
    "conso_energie_par_hab":  ("calcul", "TOTAL_FLUX / P21_POP"),
    "part_actifs":            ("calcul", "P21_ACTOCC1564 / P21_POP"),
    # Les bpe_* sont traités à part car viennent d'un autre CSV
}

# Pondération des indicateurs dans chaque dimension (total = 100 par dim)
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
        "part_actifs": 100,
    },
    # mob et gouv non scorés automatiquement pour l'instant
}

# Pondération des dimensions dans le score global (total = 100)
PONDERATIONS_GLOBALES = {
    "struct": 20,
    "access": 20,
    "mob":    0,   # en suspens
    "env":    30,  # finalité : impact carbone
    "socio":  10,
    "gouv":   0,   # pas encore saisi
}

# Typologies à scorer groupées. Si un code AAV est absent, fallback sur
# le groupe "autres".
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


# ============================================================
# CACHE EN MÉMOIRE
# ============================================================

_cache = {
    "loaded": False,
    "communes_data": {},   # {codgeo: {col: valeur, 'cat': int}}
    "quantiles": {},       # {groupe: {indicateur_code: [p20, p40, p60, p80]}}
    "bpe": {},             # {codgeo: {domaine: count}}
}


def _to_float(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _get_groupe(cataeu) -> str:
    """Retourne le groupe de typologie pour un code CATAEU2010."""
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
    """Calcule la valeur d'un indicateur pour une ligne de données."""
    if code.startswith("bpe_"):
        return None  # traité ailleurs
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
            # eval simple (on contrôle les entrées)
            result = eval(expr, {"__builtins__": {}}, {})
            return float(result) if result is not None else None
        except (ZeroDivisionError, ValueError, SyntaxError, TypeError):
            return None
    return None


def _compute_bpe_per_10k(bpe_row: dict, pop: Optional[float], domaine: str) -> Optional[float]:
    """Ratio équipements / 10 000 hab."""
    if not pop or pop <= 0:
        return None
    count = bpe_row.get(domaine, 0)
    return count / pop * 10000


def _quantiles(values: list, ps=(20, 40, 60, 80)) -> list:
    """Calcule des quantiles simples (linéaires)."""
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
    """Charge toutes les données et précalcule les quantiles par groupe × indicateur."""
    if _cache["loaded"]:
        return

    # Charger le CSV indicateurs
    if not INDICATEURS_CSV.exists():
        raise FileNotFoundError(f"Fichier {INDICATEURS_CSV} introuvable.")
    communes = {}
    with open(INDICATEURS_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            codgeo = str(row.get("CODGEO", "")).strip()
            if not codgeo:
                continue
            # On garde toutes les colonnes numériques utiles
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

    # Charger le CSV BPE
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

    # Précalculer les valeurs d'indicateurs pour toutes les communes
    # et grouper par typologie
    values_by_group = defaultdict(lambda: defaultdict(list))
    values_national = defaultdict(list)

    for codgeo, data in communes.items():
        groupe = data["groupe"]
        # Indicateurs depuis le CSV principal
        for code in INDICATEURS_SENS.keys():
            if code.startswith("bpe_"):
                continue
            val = _compute_indicateur_value(data, code)
            if val is not None:
                values_by_group[groupe][code].append(val)
                values_national[code].append(val)
        # Indicateurs BPE
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

    # Calculer les quantiles
    quantiles = {}
    for groupe, by_ind in values_by_group.items():
        quantiles[groupe] = {}
        for code, vals in by_ind.items():
            quantiles[groupe][code] = _quantiles(vals)
    # Toujours avoir un fallback national
    quantiles["national"] = {}
    for code, vals in values_national.items():
        quantiles["national"][code] = _quantiles(vals)
    _cache["quantiles"] = quantiles
    _cache["loaded"] = True


def _score_from_quantiles(val: float, quantiles: list, sens: int) -> float:
    """
    Convertit une valeur en score 0-100 selon les quantiles P20/P40/P60/P80.
    sens = +1 : plus haut = meilleur score
    sens = -1 : plus bas = meilleur score
    """
    if not quantiles or any(q is None for q in quantiles):
        return 50.0
    p20, p40, p60, p80 = quantiles
    if sens == +1:
        if val <= p20: return 10
        if val <= p40: return 30
        if val <= p60: return 50
        if val <= p80: return 70
        return 90
    else:
        if val <= p20: return 90
        if val <= p40: return 70
        if val <= p60: return 50
        if val <= p80: return 30
        return 10


def get_scoring_for_territoire(territoire: dict, indicateurs_locaux: dict, bpe_ind: dict) -> dict:
    """
    Calcule les scores pour un territoire.

    Retourne :
    {
      "scores_indicateurs": { code: {score, quantiles, groupe, sens} },
      "scores_dimensions": { dim: {score, grade} },
      "score_global": {valeur, grade, groupe_typo}
    }
    """
    try:
        _load()
    except FileNotFoundError as e:
        return {"_erreur": str(e)}

    # Déterminer le groupe de typologie du territoire
    if territoire["type"] == "commune":
        data = _cache["communes_data"].get(territoire["code"])
        groupe = data["groupe"] if data else "hors_influence"
    else:
        # Pour un EPCI : groupe dominant parmi les communes membres
        codes = territoire.get("codes_communes", [])
        if codes:
            groupes = [
                _cache["communes_data"][c]["groupe"]
                for c in codes
                if c in _cache["communes_data"]
            ]
            if groupes:
                # Groupe le plus fréquent, pondéré par la population
                counts = defaultdict(float)
                for c in codes:
                    if c in _cache["communes_data"]:
                        d = _cache["communes_data"][c]
                        counts[d["groupe"]] += d.get("P21_POP") or 0
                groupe = max(counts.keys(), key=counts.get) if counts else "hors_influence"
            else:
                groupe = "hors_influence"
        else:
            groupe = "hors_influence"

    quantiles_groupe = _cache["quantiles"].get(groupe, _cache["quantiles"].get("national", {}))

    # Extraire les valeurs des indicateurs du territoire
    scores_indicateurs = {}
    for code, sens in INDICATEURS_SENS.items():
        # Récupérer la valeur depuis la structure déjà calculée par app.py
        val = None
        if code in indicateurs_locaux:
            val = indicateurs_locaux[code].get("valeur")
        elif code in bpe_ind:
            val = bpe_ind[code].get("valeur")
        if val is None:
            continue
        quants = quantiles_groupe.get(code)
        if not quants or any(q is None for q in quants):
            # Fallback national
            quants = _cache["quantiles"].get("national", {}).get(code)
        if not quants or any(q is None for q in quants):
            continue
        score = _score_from_quantiles(val, quants, sens)
        scores_indicateurs[code] = {
            "score": score,
            "valeur": val,
            "quantiles": quants,
            "sens": sens,
            "groupe": groupe,
        }

    # Scores de dimension (moyenne pondérée)
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

    # Score global (moyenne pondérée des dimensions)
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
