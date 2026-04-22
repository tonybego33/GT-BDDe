"""
Convertit le fichier DS_BPE_2024_data.csv (BPE 2024 INSEE, format européen standardisé)
en CSV compact agrégé par commune × domaine.

Utilisation :
    python scripts/convert_bpe_to_csv.py DS_BPE_2024_data.csv

Le CSV sera écrit dans backend/data/bpe_communes.csv.
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

DOMAINE_MAPPING = {
    "A": "services",
    "B": "commerces",
    "C": "enseignement",
    "D": "sante",
    "E": "transport",
    "F": "sport_culture",
    "G": "tourisme",
}

DOMAINES_OUT = ["services", "commerces", "enseignement", "sante",
                "transport", "sport_culture", "tourisme"]


def convert(src_csv: Path, dst_csv: Path) -> None:
    print(f"Lecture : {src_csv}")
    counts = defaultdict(lambda: {d: 0 for d in DOMAINES_OUT})

    with open(src_csv, "r", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter=";", quotechar='"')
        headers = next(reader)
        print(f"Colonnes : {headers}")

        try:
            i_code = headers.index("GEO")             # Colonne 1 : code géographique
            i_type = headers.index("GEO_OBJECT")      # Colonne 2 : type (COM, DEP, REG...)
            i_dom = headers.index("FACILITY_DOM")
            i_measure = headers.index("BPE_MEASURE")
            i_value = headers.index("OBS_VALUE")
        except ValueError as e:
            raise SystemExit(f"Colonne attendue introuvable : {e}")

        n, n_com, n_skip = 0, 0, 0
        for row in reader:
            n += 1
            if n % 200000 == 0:
                print(f"  ... {n:>8} lignes lues, {n_com:>7} communes conservées")
            try:
                # Filtrer sur GEO_OBJECT == "COM" (commune)
                if row[i_type] != "COM":
                    continue
                if row[i_measure] != "FACILITIES":
                    continue

                codgeo = row[i_code].strip()
                dom_code = row[i_dom].strip()[:1].upper() if row[i_dom] else ""
                domaine = DOMAINE_MAPPING.get(dom_code)
                if not domaine:
                    n_skip += 1
                    continue
                try:
                    value = int(float(row[i_value]))
                except (ValueError, TypeError):
                    n_skip += 1
                    continue

                counts[codgeo][domaine] += value
                n_com += 1
            except IndexError:
                n_skip += 1
                continue

    print(f"\n✓ Lecture terminée : {n} lignes, {n_com} comptabilisées (COM), {n_skip} ignorées")
    print(f"  → {len(counts)} communes distinctes")

    dst_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(dst_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["CODGEO", "LIBGEO"] + DOMAINES_OUT + ["total"])
        for codgeo in sorted(counts.keys()):
            c = counts[codgeo]
            total = sum(c.values())
            writer.writerow([codgeo, ""] + [c[d] for d in DOMAINES_OUT] + [total])

    size_kb = dst_csv.stat().st_size / 1024
    print(f"\n✓ Écrit : {dst_csv} ({size_kb:.0f} Ko)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage : python scripts/convert_bpe_to_csv.py <DS_BPE_2024_data.csv>")
        sys.exit(1)
    p = Path(sys.argv[1]).resolve()
    if not p.exists():
        raise SystemExit(f"Fichier introuvable : {p}")
    project_root = Path(__file__).resolve().parent.parent
    csv_path = project_root / "backend" / "data" / "bpe_communes.csv"
    convert(p, csv_path)