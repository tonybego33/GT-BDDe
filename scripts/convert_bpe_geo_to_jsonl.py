"""
Convertit BPE24.csv (BPE 2024 INSEE) en JSONL indexe par commune.
Version ultra-robuste : parse les lignes manuellement (split ';')
car csv.reader de Python bug sur les guillemets mal echappes.

Usage : python scripts/convert_bpe_geo_to_jsonl.py BPE24.csv
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

# Positions 0-based des colonnes utiles (verifiees via head -1 BPE24.csv)
I_DEPCOM = 9    # colonne 10 : code INSEE commune
I_TYPEQU = 15   # colonne 16 : type d'equipement
I_LON = 68      # colonne 69 : LONGITUDE (WGS84)
I_LAT = 69      # colonne 70 : LATITUDE (WGS84)


def parse_field(f):
    """Nettoie un champ : enleve guillemets autour et espaces."""
    f = f.strip()
    if f.startswith('"') and f.endswith('"') and len(f) >= 2:
        f = f[1:-1]
    return f


def convert(src_csv, dst_jsonl):
    print(f"Lecture : {src_csv}")
    by_com = defaultdict(list)

    n = 0
    n_ok = 0
    n_skip_geo = 0
    n_skip_err = 0

    with open(src_csv, "r", encoding="utf-8", errors="replace") as f:
        # Skip header
        header = f.readline()
        # Split du header pour verifier les colonnes
        parts = header.strip().split(";")
        print(f"Header ({len(parts)} colonnes) : DEPCOM={parse_field(parts[I_DEPCOM])!r}, "
              f"TYPEQU={parse_field(parts[I_TYPEQU])!r}, "
              f"LON={parse_field(parts[I_LON])!r}, "
              f"LAT={parse_field(parts[I_LAT])!r}")
        print()

        for line in f:
            n += 1
            if n % 200000 == 0:
                print(f"  ... {n:>8} lignes lues, {n_ok} OK")

            # Split simple par point-virgule
            parts = line.rstrip("\n\r").split(";")
            if len(parts) < 70:
                n_skip_err += 1
                continue

            try:
                codgeo = parse_field(parts[I_DEPCOM])
                typequ = parse_field(parts[I_TYPEQU])
                lon_raw = parse_field(parts[I_LON]).replace(",", ".")
                lat_raw = parse_field(parts[I_LAT]).replace(",", ".")

                if not codgeo or not typequ:
                    n_skip_geo += 1
                    continue

                if not lon_raw or not lat_raw:
                    n_skip_geo += 1
                    continue

                lon = float(lon_raw)
                lat = float(lat_raw)

                # Sanity check : eviter (0,0)
                if abs(lat) < 0.5 and abs(lon) < 0.5:
                    n_skip_geo += 1
                    continue

                lon = round(lon, 5)
                lat = round(lat, 5)
                by_com[codgeo].append([lon, lat, typequ])
                n_ok += 1

            except (ValueError, IndexError):
                n_skip_geo += 1
                continue

    print(f"\nOK : {n} lignes lues, {n_ok} geolocalisees")
    print(f"  {n_skip_geo} sans coords valides, {n_skip_err} erreurs structure")
    print(f"  {len(by_com)} communes distinctes")

    # Ecrire JSONL
    dst_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with open(dst_jsonl, "w", encoding="utf-8") as f:
        for codgeo in sorted(by_com.keys()):
            obj = {"codgeo": codgeo, "items": by_com[codgeo]}
            f.write(json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n")

    size_mb = dst_jsonl.stat().st_size / 1024 / 1024
    print(f"\nEcrit : {dst_jsonl} ({size_mb:.1f} Mo)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage : python scripts/convert_bpe_geo_to_jsonl.py <BPE24.csv>")
        sys.exit(1)
    p = Path(sys.argv[1]).resolve()
    if not p.exists():
        raise SystemExit(f"Fichier introuvable : {p}")
    root = Path(__file__).resolve().parent.parent
    dst = root / "backend" / "data" / "bpe_geo.jsonl"
    convert(p, dst)