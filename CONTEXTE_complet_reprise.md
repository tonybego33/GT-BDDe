# GT BDDe — Brief complet pour reprise

> **À coller en début de conversation Claude Code pour qu'il ait tout le contexte du projet.**

---

## 0. Identité & contexte

Je m'appelle Tony, stagiaire AREP (filiale SNCF Gares & Connexions), pôle Conseil et Programmation. Master 1 SGM Sciences Po Bordeaux, formation Stratégies et Gouvernances Métropolitaines. Mon encadrant AREP est **Fabien Rosa** (GT BDDe), ma manager directe est **Yasmina**. Autres interlocuteurs : **Félix Pouchain** (dev outil Mobility AREP, basé à Lyon), **Antoine** (collaborateur SERM HDF), **Nils Le Bot / Arthur / Mathieu** (équipe RADAR/Flux AREP).

**Contraintes techniques :**
- Pas de Python sur poste AREP, je dev exclusivement dans **GitHub Codespaces**
- Repo unique sur compte perso : `https://github.com/tonybego33/GT-BDDe` (public)
- Workflow git : `git add . && git commit -m "..." && git push` sur `main`
- 2 terminaux : uvicorn port 8000 + http.server port 5500
- Les 2 ports doivent être en **Public** dans l'onglet PORTS de VS Code

---

## 1. Le projet GT BDDe en une phrase

Outil de **diagnostic territorial multicritère** qui objective le lien entre l'organisation territoriale d'une agglomération (habitat, équipements, centralités) et sa **dépendance automobile / ses émissions GES**. À terme : un outil sélectionnable par code INSEE ou SIREN EPCI qui produit un diagnostic comparatif automatisé.

**Corpus pilote (5 agglos) :**
- CA La Rochelle — `241700434`
- Grand Reims — `200067213`
- CA Pays Basque — `200067106`
- Nevers Agglomération — `245804406`
- Golfe Morbihan-Vannes — `200067932`

---

## 2. Architecture technique

```
GT-BDDe/
├── backend/                          (FastAPI Python)
│   ├── app.py                        Routes : /territoire /indicateurs /carto /search /gouvernance
│   ├── config.py
│   ├── cache_store.py                Cache disque pour Overpass
│   ├── data/
│   │   ├── indicateurs_export.csv    (15 Mo, 34 915 communes × 39 indicateurs, ex-Excel AREP)
│   │   ├── bpe_communes.csv          (943 Ko, 34 871 communes × 7 domaines BPE)
│   │   ├── filosofi_communes.csv     (~30 000 communes, INSEE Filosofi 2021)
│   │   ├── filosofi_epci.csv         (~1 200 EPCI)
│   │   └── gouvernance.db            SQLite des saisies manuelles
│   └── services/
│       ├── geo.py                    geo.api.gouv.fr + recherche par nom
│       ├── indicateurs_locaux.py     Lit indicateurs_export.csv
│       ├── bpe.py                    Lit bpe_communes.csv
│       ├── filosofi.py               Lit filosofi_communes.csv et _epci.csv
│       ├── scoring.py                Quantiles par typologie + rang percentile
│       ├── carto.py                  BPE+TC+Vélo via Overpass OSM (avec User-Agent + miroirs)
│       └── gouvernance.py            7 indicateurs manuels SQLite
├── frontend/
│   └── index.html                    ~1700 lignes, HTML/JS statique vanilla, Leaflet
└── scripts/
    ├── convert_xlsx_to_csv.py        Convertit l'Excel AREP en CSV
    ├── convert_bpe_to_csv.py         Convertit le BPE INSEE
    └── convert_filosofi_to_csv.py    Convertit le zip Filosofi (format SDMX/Melodi)
```

**Commande relance unique :**
```bash
pkill -f uvicorn ; pkill -f "http.server" ; sleep 2
python -m uvicorn backend.app:app --reload --host 0.0.0.0 &
cd frontend && python -m http.server 5500 &
```

---

## 3. Ce qui marche actuellement (V0.3 avril 2026)

### Backend
- **Routes opérationnelles** : `/`, `/search`, `/territoire/{code}`, `/indicateurs/{code}`, `/indicateurs/def`, `/carto/{code}?layers=bpe,tc,velo`, `/gouvernance/{code}` (POST), `/gouvernance/indicateurs`
- **Résolution territoires** via geo.api.gouv.fr
- **Recherche par nom** (autocomplétion) sur communes + EPCI, parallélisée
- **Couches carto OSM** via Overpass : User-Agent explicite + 3 miroirs en fallback (overpass-api.de → kumi.systems → private.coffee)
- **Scoring V1** : pour chaque indicateur scoré, calcul du **rang percentile** (`bisect.bisect_right`) à la fois dans la **typologie INSEE CATAEU2010** (grand_pole / moyen_pole / multipol / hors_influence) **et au niveau national**

### Frontend
- Sélection territoire par 5 pills agglos pilotes + barre de recherche autocomplétée (n'importe quelle commune ou EPCI de France)
- Bandeau jaune en haut pour configurer l'URL backend (testée à chaque modif, badge "connecté" / "non connecté")
- **Carte Leaflet** avec contour officiel + 3 toggles de couches (Équipements BPE / Arrêts transport / Voies cyclables) chargées à la demande
- **Score global / 100** + **radar synthétique 6 dimensions**
- 6 cartes dimensions (Structure, Accessibilité, Mobilité, Environnement, Socio-éco, Gouvernance) avec score de dimension + jauge + détail des indicateurs
- Sous chaque indicateur scoré : **2 mini-barres de positionnement neutres** (gris, sans couleur bon/mauvais) montrant le **rang percentile dans sa typologie** ET le **rang national**, avec le nombre de communes dans chaque référentiel
- **Multi-comparaison illimitée** : pills colorées (palette de 7 couleurs cycliques), ajout par autocomplétion, retrait par ✕, "Tout effacer". Le radar superpose jusqu'à 4 polygones, les jauges de dimension affichent un trait par comparé, sous chaque indicateur on voit `● Reims · 52%`, `● Vannes · 68%` etc., et la carte affiche tous les contours avec leurs couleurs
- **Drawer Gouvernance** : panneau latéral qui glisse depuis la droite, accessible via bouton "✏️ Saisir / mettre à jour" dans la dimension Gouvernance. Champs adaptés au type (booléens Oui/Non, nombres, années, texte), URL source optionnelle par champ, nom du remplisseur en bas, bouton "Enregistrer tout" qui POST sur le backend
- Badges sources `LIVE` (vert) / `DÉMO` (gris) / `À BRANCHER` (orange) sur chaque indicateur

### Données INSEE branchées
- **indicateurs_export AREP** : 39 colonnes essentiellement environnementales (GES par secteur, énergie, artificialisation 2009-2023 et 2015-2021, CLC nomenclature 11 et 11-13, densités) + 1 socio (P21_ACTOCC1564)
- **BPE 2024** : 7 domaines d'équipements par commune (services, commerces, enseignement, santé, transport, sport/culture, tourisme)
- **Filosofi 2021** : revenu médian, taux pauvreté, rapport interdécile D9/D1, déciles, part imposés, part prestations sociales (totale + ses 3 composantes), composition du revenu par source. Format SDMX/Melodi pivot long→large via `convert_filosofi_to_csv.py`. URL source : `https://www.insee.fr/fr/statistiques/fichier/7756729/base-cc-filosofi-2021-geo2025_csv.zip`

### Scoring (méthodo actuelle, V1 indicative)
- **Indicateurs scorés (16) :**
  - Struct : `densite_brute`, `artif_par_hab`, `part_art_habitat`, `dens_popclc`
  - Access (BPE par 10k hab) : `bpe_total_par_10k`, `bpe_commerces_par_10k`, `bpe_sante_par_10k`, `bpe_enseignement_par_10k`, `bpe_sport_culture_par_10k`
  - Env : `ges_transport_par_hab`, `ges_total_par_hab`, `conso_energie_par_hab`
  - Socio : `revenu_median`, `taux_pauvrete`, `rapport_interdecile`, `part_imposes`, `part_actifs`
- **Pondérations dimensions actuelles** : Struct 20, Access 20, Env 30, Socio 10, **Mobilité 0** (en attente Félix), **Gouvernance 0** (saisie manuelle)
- **Sens des indicateurs** stocké dans `INDICATEURS_SENS` du `scoring.py` (+1 = haut = mieux, -1 = bas = mieux)
- **Fallback national** automatique si la typologie a moins de 10 communes (rang non fiable)

---

## 4. Ce qui ne marche pas encore / chantiers ouverts

### Bloquants moyens
- **Mobilité** : entièrement à brancher, en attente de Félix Pouchain (outil Mobility AREP). Indicateurs cibles : part modale voiture, taux motorisation, distance domicile-travail, actifs hors EPCI, fréquence TC. Sources potentielles : INSEE MOBPRO + GTFS AOM locaux
- **Recensement INSEE détaillé** : pour étoffer la dimension socio (CSP, chômage, diplômes, lieu de travail), pas encore branché
- **Indicateurs BPE bruts** : actuellement seuls les ratios par 10k hab sont scorés, pas les nombres absolus (qui sont juste descriptifs)

### Chantiers IT / déploiement
- **Repo sur compte perso** : devrait migrer sur l'organisation AREP à valider avec Fabien
- **Déploiement** : aujourd'hui uniquement Codespaces (pas pérenne). Cible : Render gratuit ou serveur AREP
- **L'Excel AREP brut (78 Mo) est sur le repo public** par inadvertance, "osef pour l'instant", à voir avec Fabien
- **BPE géolocalisée abandonnée** : 4h de débogage sur le fichier BPE24.csv (157 Mo) qui ne contenait pas La Rochelle. Décision : utiliser OSM Overpass à la place pour la carte (déjà fait dans `carto.py`)

### Chantiers méthodo (réunion Fabien à venir)
Voir section 5.

---

## 5. Réunion Fabien (16h aujourd'hui) — questions à trancher

J'ai préparé un xlsx `GT_BDDe_grille_notation.xlsx` avec **86 indicateurs listés** (scorés et non-scorés), 3 onglets : Notation des indicateurs / Pondérations globales / Questions méthodo.

**Questions clés :**

1. **Typologie de référence pour le scoring par pairs**
   Aujourd'hui CATAEU2010 (dépréciée). Alternatives : **AAV 2020** (officielle INSEE actuelle, mon pari) ou **typologie AREP propre** (croisement taille + densité + littoral/intérieur + mono/polycentrique). À trancher.

2. **Sens des indicateurs ambigus** :
   - Revenu médian : + = mieux, ou nuancer (gentrification) ?
   - Part artif habitat : - = mieux (sobriété) ou neutre ?
   - Densité CLC zones urbanisées : + = mieux (compacité) ou pondérer ?
   - Part prestations sociales dans le revenu : - = mieux (autonomie) ou neutre ?
   - GES agriculture / hab : peu pertinent en territoire rural ?
   - Conso énergie globale vs par hab : on score quoi ?

3. **Pondérations dimensions** : valider Struct 20 / Access 20 / Env 30 / Socio 10 / Mob 0 / Gouv 0.

4. **Gouvernance dans le score global ?** Si oui, à quel seuil de remplissage (70% des champs) ?

5. **Indicateurs à ajouter / retirer** : la grille permet à Fabien de pointer ce qui manque ou ce qui est inutile.

6. **Périmètre Mobilité** : qu'attend-on exactement de Félix ?

7. **Étendre le corpus** au-delà des 5 agglos pilotes ?

---

## 6. Prochaines étapes proposées (après réunion)

1. Brancher l'**outil Mobility de Félix** (dimension Mobilité) — selon retour Fabien
2. **Migration repo** vers organisation AREP
3. **Déploiement Render** (URL stable pour partage à l'équipe GT BDDe)
4. **Note méthodo courte** formalisant les choix de scoring validés par Fabien
5. Brancher **CSP / chômage / diplômes** (recensement INSEE) pour étoffer socio
6. Éventuellement passer à la **typologie AAV 2020** si Fabien valide
7. Décider du sort de la **dimension Gouvernance** dans le score global

---

## 7. Préférences de communication

- Français direct, pas d'em-dashes, pas de formules ampoulées
- Donne-moi du **code à coller** plutôt que des explications théoriques. Si tu modifies un fichier, livre-le complet ou le diff exact.
- Je patiente mal quand on tourne en rond sur un bug. Si quelque chose foire, demande-moi un test rapide (`curl`, `grep`) plutôt que de spéculer.
- Pour les changements lourds, propose un plan en quelques étapes avant de te lancer
- Vérifie toujours avant de livrer (`grep -c` sur le fichier de sortie pour confirmer que les modifs sont bien là)

---

## 8. Repères utiles

- Backend health-check : `curl -s http://localhost:8000/`
- Vérifier que le scoring marche : `curl -s http://localhost:8000/indicateurs/241700434 | grep rang_typo | head -3`
- Vérifier qu'un fichier frontend a la bonne version : `grep -c "rang_typo" frontend/index.html` (doit être > 0)
- Recherche autocomplete : `curl -s "http://localhost:8000/search?q=imp" | python -m json.tool`
- Tester une couche carto : `curl -s "http://localhost:8000/carto/241700434?layers=tc" | head -c 300`

---

**Mon blocage / chantier actuel :** la réunion Fabien va définir les priorités. En attendant, l'outil est fonctionnel et démontrable sur les 5 agglos pilotes, avec Filosofi branché, multi-comparaison opérationnelle, et drawer Gouvernance qui sauvegarde bien dans la SQLite.
