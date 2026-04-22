"""
Convertit le zip Filosofi INSEE (format SDMX/Melodi) en 2 CSV compacts.

Le fichier INSEE 2021+ est au format "long" (une ligne par observation) :
  GEO;GEO_OBJECT;FILOSOFI_MEASURE;UNIT_MEASURE;UNIT_MULT;CONF_STATUS;OBS_STATUS;TIME_PERIOD;OBS_VALUE

On pivote en "large" (une ligne par territoire) et on écrit 2 CSV :
  backend/data/filosofi_communes.csv  (GEO_OBJECT = COM)
  backend/data/filosofi_epci.csv      (GEO_OBJECT = EPCI)

Utilisation :
  python scripts/convert_filosofi_to_csv.py base-cc-filosofi-2021-geo2025_csv.zip
"""
from __future__ import annotations

import csv
import sys
import zipfile
from collections import defaultdict
from pathlib import Path


# Mapping code INSEE Melodi -> nom interne GT BDDe
MEASURE_MAP = {
    "MED_SL":               "revenu_median",          # Niveau de vie médian (€)
    "PR_MD60":              "taux_pauvrete",          # Taux de pauvreté 60% (%)
    "IR_D9_D1_SL":          "rapport_interdecile",    # D9/D1
    "D1_SL":                "decile1",                # 1er décile (€)
    "D9_SL":                "decile9",                # 9e décile (€)
    "S_HH_TAX":             "part_imposes",           # Part ménages imposés (%)
    "NUM_HH":               "nb_menages",
    "NUM_PER":              "nb_personnes",
    "NUM_CU":               "nb_uc",
    # Composition du revenu
    "S_EI_DI":              "part_rev_activite",
    "S_EI_DI_SAL":          "part_salaires",
    "S_EI_DI_UNE":          "part_chomage",
    "S_EI_DI_N_SAL":        "part_non_salaries",
    "S_RET_PEN_DI":         "part_retraites",
    "S_INC_ASS_DI":         "part_patrimoine",
    "S_SOC_BEN_DI":         "part_presta_sociales",   # Ensemble prestations sociales
    "S_SOC_BEN_DI_FAM_BEN": "part_presta_familiales",
    "S_SOC_BEN_DI_HOU_BEN": "part_presta_logement",
    "S_SOC_BEN_DI_MIN_SOC": "part_minima_sociaux",
    "S_DIR_TAX_DI":         "part_impots",
}


# Ordre des colonnes dans les CSV de sortie
OUTPUT_COLS = ["codgeo", "libgeo"] + list(MEASURE_MAP.values())


def _to_float_safe(v: str) -> str:
    """Normalise une valeur numérique INSEE (virgule décimale FR)."""
    if v is None or v == "":
        return ""
    return v.replace(",", ".").strip()


def process_data_csv(content: bytes) -> tuple[dict, dict]:
    """
    Lit le CSV SDMX long et retourne :
      ({code_commune: {col: val, ...}}, {code_epci: {col: val, ...}})
    """
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    by_com = defaultdict(dict)
    by_epci = defaultdict(dict)

    reader = csv.DictReader(text.splitlines(), delimiter=";")
    total, kept = 0, 0
    geo_objects_seen = defaultdict(int)

    for row in reader:
        total += 1
        geo_obj = (row.get("GEO_OBJECT") or "").strip()
        geo_objects_seen[geo_obj] += 1

        if geo_obj not in ("COM", "EPCI"):
            continue

        conf = (row.get("CONF_STATUS") or "").strip()
        status = (row.get("OBS_STATUS") or "").strip()
        if conf == "C" or status != "A":
            continue

        measure = (row.get("FILOSOFI_MEASURE") or "").strip()
        internal = MEASURE_MAP.get(measure)
        if not internal:
            continue

        code = (row.get("GEO") or "").strip()
        if not code:
            continue
        value = _to_float_safe(row.get("OBS_VALUE") or "")
        if value == "":
            continue

        bucket = by_com if geo_obj == "COM" else by_epci
        bucket[code][internal] = value
        kept += 1

    print(f"  {total} lignes lues, {kept} valeurs retenues")
    print(f"  Niveaux geo trouves : {dict(geo_objects_seen)}")
    return by_com, by_epci


def write_output(data: dict, path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(OUTPUT_COLS)
        for code in sorted(data.keys()):
            measures = data[code]
            row = [code, ""] + [measures.get(col, "") for col in MEASURE_MAP.values()]
            writer.writerow(row)
            n += 1
    return n


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage : python scripts/convert_filosofi_to_csv.py <fichier_zip>")
        sys.exit(1)
    src = Path(sys.argv[1]).resolve()
    if not src.exists():
        raise SystemExit(f"Fichier introuvable : {src}")

    project_root = Path(__file__).resolve().parent.parent
    data_dir = project_root / "backend" / "data"
    out_communes = data_dir / "filosofi_communes.csv"
    out_epci = data_dir / "filosofi_epci.csv"

    print(f"Lecture : {src}")

    if src.suffix.lower() == ".zip":
        with zipfile.ZipFile(src, "r") as z:
            all_csvs = [m for m in z.namelist() if m.lower().endswith(".csv")]
            # Écarter les fichiers metadata/dictionnaire
            data_members = [m for m in all_csvs if "metadata" not in m.lower()
                            and "dictionnaire" not in m.lower()
                            and "dico" not in m.lower()]
            if not data_members:
                raise SystemExit(f"Aucun CSV de données dans le zip. Vus : {all_csvs}")
            member = data_members[0]
            print(f"Traitement de {member}...")
            content = z.read(member)
    else:
        content = src.read_bytes()
        print(f"Traitement de {src.name}...")

    by_com, by_epci = process_data_csv(content)

    nc = write_output(by_com, out_communes)
    ne = write_output(by_epci, out_epci)

    print(f"\nOK : {out_communes} ({nc} communes, {out_communes.stat().st_size // 1024} Ko)")
    print(f"OK : {out_epci} ({ne} EPCI, {out_epci.stat().st_size // 1024} Ko)")


if __name__ == "__main__":
    main()
