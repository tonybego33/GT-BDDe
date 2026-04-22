"""
Service Gouvernance : indicateurs remplis manuellement par l'équipe GT.

Chaque indicateur a :
- un code (ex: 'plan_velo', 'pcaet', 'budget_mobilite_hab')
- un type (boolean, number, text, date)
- un libellé affiché
- une éventuelle unité

Les valeurs sont saisies par territoire et horodatées. Les réponses exposent
la valeur, qui l'a saisie, quand, et la source fournie.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any, Optional

from ..config import GOUVERNANCE_DB


# Définition statique des indicateurs de gouvernance (pourra être étendue)
INDICATEURS_GOUVERNANCE = [
    {
        "code": "plan_velo",
        "libelle": "Plan vélo structurant adopté",
        "type": "boolean",
        "unite": None,
        "dimension": "gouv",
    },
    {
        "code": "pcaet",
        "libelle": "PCAET adopté",
        "type": "boolean",
        "unite": None,
        "dimension": "gouv",
    },
    {
        "code": "pcaet_annee",
        "libelle": "Année d'adoption du PCAET",
        "type": "date",
        "unite": None,
        "dimension": "gouv",
    },
    {
        "code": "budget_mobilite_hab",
        "libelle": "Budget mobilité par habitant et par an",
        "type": "number",
        "unite": "€/hab/an",
        "dimension": "gouv",
    },
    {
        "code": "rues_aux_ecoles",
        "libelle": "Politique de rues aux écoles",
        "type": "boolean",
        "unite": None,
        "dimension": "gouv",
    },
    {
        "code": "km_pistes_cyclables",
        "libelle": "Kilomètres de pistes cyclables (réseau structurant)",
        "type": "number",
        "unite": "km",
        "dimension": "gouv",
    },
    {
        "code": "photovoltaique_installe",
        "libelle": "Puissance photovoltaïque installée",
        "type": "number",
        "unite": "MW",
        "dimension": "gouv",
    },
]


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(GOUVERNANCE_DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Crée la table si absente. Idempotent."""
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS gouvernance_values (
                territoire_type TEXT NOT NULL,
                territoire_code TEXT NOT NULL,
                indicateur_code TEXT NOT NULL,
                valeur TEXT,
                source_url TEXT,
                remplisseur TEXT,
                saisie_at TEXT NOT NULL,
                PRIMARY KEY (territoire_type, territoire_code, indicateur_code)
            )
        """)


def get_values(territoire_type: str, territoire_code: str) -> dict[str, dict]:
    """Renvoie toutes les valeurs saisies pour un territoire."""
    init_db()
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM gouvernance_values WHERE territoire_type=? AND territoire_code=?",
            (territoire_type, territoire_code),
        ).fetchall()
    return {r["indicateur_code"]: dict(r) for r in rows}


def set_value(
    territoire_type: str,
    territoire_code: str,
    indicateur_code: str,
    valeur: Any,
    source_url: Optional[str] = None,
    remplisseur: Optional[str] = None,
) -> None:
    """Enregistre (ou met à jour) une valeur saisie."""
    init_db()
    now = datetime.utcnow().isoformat(timespec="seconds")
    with _conn() as c:
        c.execute(
            """
            INSERT INTO gouvernance_values (territoire_type, territoire_code, indicateur_code, valeur, source_url, remplisseur, saisie_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(territoire_type, territoire_code, indicateur_code) DO UPDATE SET
                valeur=excluded.valeur,
                source_url=excluded.source_url,
                remplisseur=excluded.remplisseur,
                saisie_at=excluded.saisie_at
            """,
            (territoire_type, territoire_code, indicateur_code,
             str(valeur) if valeur is not None else None,
             source_url, remplisseur, now),
        )


def indicateurs_gouvernance(territoire: dict) -> list[dict]:
    """
    Renvoie la liste des indicateurs de gouvernance avec leur valeur saisie (ou None).
    """
    values = get_values(territoire["type"], territoire["code"])
    out = []
    for ind in INDICATEURS_GOUVERNANCE:
        v = values.get(ind["code"])
        out.append({
            **ind,
            "valeur": v["valeur"] if v else None,
            "statut": "rempli" if v else "a_remplir",
            "source_url": v["source_url"] if v else None,
            "remplisseur": v["remplisseur"] if v else None,
            "saisie_at": v["saisie_at"] if v else None,
        })
    return out
