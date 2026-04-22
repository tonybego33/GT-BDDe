# GT BDDe · Backend + démo

Outil de diagnostic territorial multicritère pour le GT BDDe (AREP).

## Architecture

```
gtbdde_backend/
├── backend/
│   ├── app.py                         # API FastAPI
│   ├── config.py                      # config centralisée
│   ├── cache_store.py                 # cache disque simple
│   ├── data/
│   │   ├── indicateurs_export.csv     # extrait de l'Excel (généré, ~15 Mo)
│   │   └── gouvernance.db             # SQLite des indicateurs manuels
│   └── services/
│       ├── geo.py                     # geo.api.gouv.fr (contours + codes)
│       ├── indicateurs_locaux.py      # lit le CSV et sert les indicateurs
│       ├── insee.py                   # (legacy, plus utilisé)
│       └── gouvernance.py             # indicateurs remplis manuellement (SQLite)
├── frontend/
│   └── index.html                     # démo + prototype V0.3
├── scripts/
│   └── convert_xlsx_to_csv.py         # convertit Indicateurs_GT_BDDe.xlsx → CSV
├── .env.example
├── requirements.txt
└── README.md
```

## Flux de données

1. **Source métier** : fichier Excel `Indicateurs_GT_BDDe.xlsx` (34 915 communes × 39 indicateurs)
2. **Conversion** : un script transforme la feuille `EXPORT` en CSV léger (15 Mo au lieu de 78 Mo)
3. **Service** : le backend charge le CSV en mémoire et agrège à la volée pour les EPCI
4. **API** : `/indicateurs/{code}` renvoie le diagnostic structuré par dimension
5. **Frontend** : consomme l'API et affiche avec le design V0.2 (radar, cartes, gauges)

## Installation en local

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate
pip install -r requirements.txt

# Générer le CSV depuis l'Excel (à faire une fois)
python scripts/convert_xlsx_to_csv.py /chemin/vers/Indicateurs_GT_BDDe.xlsx

python -m uvicorn backend.app:app --reload --host 0.0.0.0
# Dans un autre terminal :
cd frontend && python -m http.server 5500
```

Puis ouvrir `http://localhost:5500` et coller l'URL du backend (`http://localhost:8000`) dans l'encadré en haut.

## Pour le Codespace GitHub

```bash
pip install -r requirements.txt

# Uploader Indicateurs_GT_BDDe.xlsx dans l'arborescence VS Code (drag&drop), puis :
python scripts/convert_xlsx_to_csv.py Indicateurs_GT_BDDe.xlsx

# Terminal 1
python -m uvicorn backend.app:app --reload --host 0.0.0.0

# Terminal 2
cd frontend && python -m http.server 5500
```

Dans l'onglet PORTS de VS Code, mettre **8000** et **5500** en **Port Visibility → Public** (clic droit sur chaque ligne). Ouvrir le 5500, coller l'URL du 8000 dans l'encadré du frontend.

## Endpoints

| Méthode | URL                          | Description |
|---------|------------------------------|-------------|
| GET     | `/`                          | Health check |
| GET     | `/territoire/{code}`         | Résolution code INSEE (5) ou SIREN EPCI (9) + contour |
| GET     | `/indicateurs/{code}`        | Diagnostic multicritère |
| GET     | `/indicateurs/def`           | Définitions des indicateurs exposés |
| GET     | `/gouvernance/indicateurs`   | Liste des indicateurs manuels |
| POST    | `/gouvernance/{code}`        | Saisie d'un indicateur manuel |

## Agrégation EPCI

Pour un EPCI, les valeurs sont automatiquement agrégées depuis les communes membres :
- **Somme** pour les stocks / flux (population, émissions, surface…)
- **Moyenne pondérée par la population** pour les ratios (densités, %)
- **Calculs dérivés** pour les indicateurs par habitant (stock total / population totale)

## Sources

| Source | Indicateurs | Mise à jour |
|--------|-------------|-------------|
| INSEE Recensement 2015, 2021 | Population, actifs occupés | Annuelle |
| IGN Admin Express | Surface | 2024 |
| Artificialisation développement durable | ENAF, artif habitat, artif infra | Avril 2024 |
| ADEME Inventaire GES Territorialisé | GES par secteur | Avril 2023 |
| Corine Land Cover | CLC 11 (artif), CLC 11-13 | 2018 |
| RTE / GRDF | Consommations électricité, gaz | 2024 |
| geo.api.gouv.fr | Contours EPCI et communes | 2025 |
