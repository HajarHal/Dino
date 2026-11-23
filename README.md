---
title: Dino
emoji: 🦕
colorFrom: purple
colorTo: pink
sdk: docker
app_port: 7860
pinned: false
---

# Dino · Ma couverture auto

« Découvrez ce qui est couvert sur votre véhicule et comprenez votre assurance simplement. »

1. L'assuré choisit son assureur. Les **Conditions Générales sont intégrées** à l'application : il n'a jamais à les ajouter.
2. Il ajoute ses **Conditions Particulières** (photo, scan ou PDF). Le modèle de vision les lit deux fois et compare les lectures.
3. Deux écrans :
   - **Ma couverture** : un cas par situation (Ma police, Conducteur, Bris de glace, Vol, Passagers, Incendie,
     Catastrophes, Assistance, Défense et recours). Pour chacun, la photo réelle de la voiture avec chaque pièce
     (couvert ou non, plafond, franchise) et un **scénario fautif / non fautif**.
   - **Mes documents** : les CG expliquées (garanties, délais, sinistre, faute ou non, indemnisation, exclusions)
     et la CP expliquée (garanties souscrites, plafonds, franchises avec exemples chiffrés, véhicule, contrat).

## Lancer

```bash
pip install -r requirements.txt
cp .env.example .env                                     # clé du modèle de vision (lecture des CP)
cd frontend && npm install && npm run build && cd ..     # Node 20+
uvicorn ica.api:app --port 8000                          # http://127.0.0.1:8000
pytest
```

Développement de l'interface avec rechargement : `cd frontend && npm run dev` (http://127.0.0.1:5173, `/api` redirigé).
Liens directs : `/?case=theft&fault=not_at_fault`, `/?tab=documents&doc=cp`.
Sans clé API, l'application fonctionne avec la CP d'exemple (« Essayer avec un exemple de contrat »).

## Conditions Générales intégrées (`config/cg_library/`)

Règle : **l'application n'écrit rien**. Les titres affichés sont des valeurs de la CP (franchise, plafond, garantie
présente ou absente) ; toute explication est un **extrait mot pour mot** des CG de l'assureur, affiché avec son article.

| Fichier | Contenu |
|---|---|
| `pdf/<id>.pdf` | Le document original de l'assureur (ouvrable depuis « Mes documents », route `/api/cg/<id>/pdf`). |
| `text/<id>.txt` | Son texte, extrait du PDF (régénéré automatiquement s'il manque). |
| `<id>.yaml` | Extraits du PDF rangés par garantie et par rubrique (délais, sinistre, faute ou non, indemnisation, exclusions), avec article. |
| `base.yaml` | Structure seule : cas et pièces de la voiture de chaque garantie. Aucun texte. |
| `insurers.yaml` | Assureurs proposés ; `cg: <id>` quand les CG sont intégrées. |

Intégrées : AtlantaSanad, Sanlam, Wafa Assurance, RMA, AXA Assurance Maroc, MCMA. Sans CG (seule la CP est
affichée) : Allianz Maroc, MAMDA, CAT, MATU.

Ajouter un assureur : copier son PDF dans `pdf/<id>.pdf`, créer `<id>.yaml` (même format), mettre `cg: <id>` dans
`insurers.yaml`. Pour trouver les passages : `python tools/cg_find.py <id> toc` (sommaire), `grep <regex>` ou `after <regex>` (passage).
`pytest` refuse tout extrait introuvable dans le PDF (comparaison sans accents, casse ni ponctuation ; « … » relie
deux morceaux) et toute explication affichée qui ne serait pas un extrait.

## Photos des véhicules (`config/car_photos.yaml`, `assets/cars/`)

Fond blanc : `pip install "rembg[cpu]"` puis `python tools/white_background.py` (originaux gardés dans
`assets/cars/original/`). Avec `rembg` installé, la photo envoyée par l'assuré est aussi mise sur fond blanc.

37 modèles courants au Maroc, photos Wikimedia Commons sous licence libre (auteur et licence affichés sous la photo).
`anchors` donne la position de chaque pièce sur la photo. Ordre de choix : photo de l'assuré > modèle choisi dans
« Plus » > modèle lu sur la CP > même marque > même carrosserie. Si le modèle n'est pas certain, la photo est
marquée « Photo d'illustration ».

## Architecture

| Module | Rôle |
|---|---|
| `ica/cg_library.py` | Charge les CG intégrées d'un assureur (socle + ses propres textes). |
| `ica/coverage_view.py` | Calcule sans IA tout ce qu'affichent les deux écrans, à partir de la CP et des CG. |
| `ica/cars.py`, `ica/vehicle_photo.py` | Photo du catalogue ; photo de l'assuré (redressée, sans métadonnées GPS, pièces repérées). |
| `ica/extraction/` | Lecture des CP par le modèle de vision (double lecture, arbitrage), client LLM. |
| `ica/parsing.py`, `ica/verification.py` | Montants, franchises ; contrôle que chaque valeur figure dans sa ligne. |
| `ica/db.py`, `ica/pipeline.py` | Stockage versionné des lectures, cloisonné par utilisateur. |
| `ica/api.py` | FastAPI : profil, CP, `GET /api/dossier` (réponse unique des deux écrans), photos. |
| `frontend/` | React + TypeScript, mobile d'abord. |

## Règles d'affichage

- Les montants viennent **toujours** de la CP ; le sens des garanties vient des CG. Une valeur absente est « non indiquée », jamais supposée nulle.
- Couvert / sous condition (pneus exclus, tiers identifié requis…) / non couvert (garantie absente d'une CP lue en entier) / à vérifier (CP lue partiellement).
- Non fautif : l'assurance du responsable paie, la franchise n'est généralement pas retenue si le responsable est identifié ; la vétusté peut rester à charge sans Rachat de vétusté.
- Fautif : garanties dommages moins la franchise ; prime RC +20 % par sinistre matériel, +30 % corporel (Conditions-Type, art. 19).
- Nom, CIN et adresse de l'assuré ne sont jamais extraits.

## Garanties non reconnues

Rapprochement d'un libellé de CP, sans IA : alias exact, puis libellé très proche (92 %), puis mots-clés
(`keywords` dans `config/taxonomy.yaml` : « Incapacité » -> capital invalidité, situation Conducteur ;
« Incapacité passagers » -> Passagers). Le groupe de mots le plus long gagne ; à égalité entre deux garanties,
rien n'est choisi.

Si les règles échouent et que les CG de l'assureur sont intégrées, **l'IA propose un classement**
(`ica/ai_classifier.py`), sous quatre contrôles :
1. liste fermée de codes (ou « aucun ») ;
2. citation des CG obligatoire, retrouvée mot pour mot dans le PDF, sinon refus ; confiance faible = refus ;
3. réponse enregistrée (`data/label_classifications.json`) : un appel par libellé et par assureur, toujours la même réponse ;
4. l'assuré confirme ou refuse (« Correct ? ») ; un refus remet la ligne en « À vérifier ».
Seuls le libellé de garantie et des pages des CG publiques sont envoyés au modèle.

Une ligne toujours sans situation devient **sa propre situation** dans « Ma couverture » (bouton à côté de Vol,
Incendie…) : libellé imprimé, plafond, franchise, « À vérifier ». Chaque libellé non reconnu est noté dans
`data/unrecognised_labels.json` ; `python tools/unrecognised.py` les liste, à ajouter aux `aliases` ou `keywords`.

## Comptes

Connexion par e-mail et mot de passe (`ica/auth.py`). Mot de passe jamais stocké (empreinte scrypt salée) ; session
dans un cookie httpOnly (30 jours), seule l'empreinte du jeton est en base ; 5 échecs = 60 s d'attente. Toute route
`/api` exige une session, sauf `/api/meta`, `/api/auth/*`, `/api/cars/*`, `/api/cg/*`. Chaque compte ne voit que ses
contrats (`Repository(session, user_id)`) ; profil par compte dans `data/profiles/<id>.json`.
« Quitter » (onglet Plus) ferme la session : les contrats restent, il faut se reconnecter. Le premier compte créé
reprend les contrats déjà enregistrés sur le poste avant l'arrivée des comptes.

## Limites connues

- Le scénario non fautif ne montre que ce que disent la CP et les CG (recours, rachat de vétusté…) : rien n'est supposé sur l'assurance de l'autre conducteur.
- Avant de vrais utilisateurs : HTTPS, réinitialisation du mot de passe par e-mail, stockage chiffré, modèle sans conservation des données.
