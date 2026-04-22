# GT BDDe · Backend + démo

Base de code pour le diagnostic territorial multicritère à partir d'APIs officielles.

## Architecture

```
gtbdde_backend/
├── backend/               # API Python FastAPI
│   ├── app.py             # routes
│   ├── config.py          # config + chargement .env
│   ├── cache_store.py     # cache disque simple avec TTL
│   └── services/
│       ├── geo.py         # geo.api.gouv.fr (résolution codes, contours)
│       ├── insee.py       # INSEE Données Locales (OAuth2 + cubes)
│       └── gouvernance.py # indicateurs manuels (SQLite)
├── frontend/
│   └── index.html         # front de démo pour tester le backend
├── .env.example
├── requirements.txt
└── README.md
```

## Installation

```bash
# 1. Créer un venv Python 3.11+
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 2. Installer les dépendances
pip install -r requirements.txt

# 3. Configurer le jeton INSEE
cp .env.example .env
# Éditer .env et renseigner INSEE_CONSUMER_KEY et INSEE_CONSUMER_SECRET
# (récupérés sur https://portail-api.insee.fr → tes applications)
```

## Lancement

Depuis la racine du projet :

```bash
uvicorn backend.app:app --reload
```

Le backend tourne sur `http://localhost:8000`.

Ouvre ensuite `frontend/index.html` dans le navigateur (double-clic ou via
un petit serveur statique : `python -m http.server 5500` depuis `frontend/`).

## Endpoints

| Méthode | URL | Rôle |
|--------|-----|------|
| GET | `/territoire/{code}` | Résout code INSEE (5 chiffres) ou SIREN EPCI (9 chiffres) |
| GET | `/indicateurs/{code}` | Diagnostic multicritère sur 6 dimensions |
| GET | `/gouvernance/indicateurs` | Liste des indicateurs de gouvernance disponibles |
| POST | `/gouvernance/{code}` | Enregistre une valeur de gouvernance |

Tests rapides avec `curl` :

```bash
# CA La Rochelle
curl http://localhost:8000/territoire/241700434 | jq

# Commune La Rochelle
curl http://localhost:8000/indicateurs/17300 | jq

# Saisir une valeur de gouvernance
curl -X POST http://localhost:8000/gouvernance/241700434 \
  -H "Content-Type: application/json" \
  -d '{"indicateur_code":"plan_velo","valeur":"true","source_url":"https://...","remplisseur":"Tony"}'
```

## État d'avancement par dimension

| Dimension | Statut | Source | Reste à faire |
|-----------|--------|--------|---------------|
| Structure territoriale | Partiel | INSEE RP + geo.api.gouv.fr | Densité OK · Artificialisation à brancher sur CEREMA · Dispersion en suspens |
| Accessibilité & maillage | À faire | BPE géolocalisée + GTFS | Service `bpe.py` à créer |
| Mobilité | En suspens | (Mobility de F. Pouchain) | Attendre retour Lyon |
| Performance environnementale | À faire | IGT CITEPA | Service `ges.py` à créer |
| Structure socio-économique | Squelette | INSEE Filosofi + RP | Brancher les cubes exacts |
| Gouvernance | OK | Saisie manuelle | Interface front de saisie |

## Cache

Les réponses des APIs sont mises en cache disque dans `backend/cache/` pendant
24h par défaut (configurable via `CACHE_TTL_SECONDS` dans `.env`).
Pour forcer un rafraîchissement : supprimer le dossier `backend/cache/`.

## Validation avec les BDD perso

Le code est structuré pour qu'on puisse lancer un mode "validation" comparant
les valeurs renvoyées par l'API avec celles de tes fichiers Excel/Access. À
brancher une fois que tu m'auras partagé les fichiers de référence.
