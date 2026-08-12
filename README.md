# Vigie Civique

Un observatoire citoyen des décisions publiques d'une petite commune, construit
à partir de données et de documents publics uniquement.

Instance de référence : **[Lasalle (Gard, 30460)](https://vigie-civique-lasalle.pages.dev)**
— 1 807 acteurs, 4 333 actes, 78 marchés publics, budget et foncier.

En dessous de 3 500 habitants, l'obligation légale d'ouvrir ses données ne
s'applique pas. C'est précisément là que rien n'est publié, et c'est le trou que
ce dispositif cherche à combler.

---

## Ce que fait le dispositif

Des **collecteurs** interrogent des sources publiques (SIRENE, RNA, BODACC, DVF,
OFGL/DGFiP, DECP/BOAMP, Sitadel, Géorisques, RNE, résultats électoraux, sites
officiels de la commune et de l'intercommunalité) et alimentent une base SQLite.

Un **script de publication** (`scripts/build_public_snapshot.py`) en extrait un
snapshot JSON filtré, qui alimente un **site statique** SvelteKit sans backend
ni base de données en ligne.

Le filtrage n'est pas un détail : c'est le cœur du dispositif. Il écarte les
personnes physiques sans rôle civique public, les pistes de travail non
établies, les liens de famille, les domiciles et les dates de naissance. Sur
l'instance de Lasalle, il exclut environ 3 850 personnes, 4 500 relations et
59 entités de la base de travail.

## Ce que le dispositif dit de lui-même

Trois principes, visibles dans le code autant que sur le site :

**La provenance de chaque acte est affichée sur sa propre ligne**, en trois
axes indépendants — d'où vient l'information (source primaire, registre
national, source secondaire), si le document est consultable, et ce qui a été
fait entre la source et l'affichage (donnée structurée, extraction
automatique, rectification humaine). Voir `provenance()` dans le script de
publication.

**Un fait, un calcul et une interprétation n'ont pas la même apparence.** Le
composant `public/src/lib/components/Niveau.svelte` matérialise cette
distinction. Un chiffre que le site calcule dit qu'il le calcule et sur quoi.

**Les lacunes sont publiées.** La page `/couverture` expose la période
réellement couverte par source, la fraîcheur de chaque collecteur et ce que le
dispositif ne sait pas faire. Sur Lasalle, elle annonce en tête que 4,2 % des
actes seulement renvoient vers la pièce elle-même.

---

## Rejouer sur une autre commune : l'état réel

Le site a longtemps publié que « changer de commune tient dans un seul fichier
de configuration ». **C'était exagéré**, et la page « Méthode » affiche
désormais la mesure plutôt que la promesse.

Ce qui est effectivement paramétré :

| Où | Quoi |
|---|---|
| `collectors/config.py` | commune, code INSEE, EPCI, communes membres, périmètres |
| `config/publication_rules.json` | règles de publication, sources autorisées, axes de provenance |
| `config/profils_locaux.json` | élus et candidats (non versionné) |
| `config/seed_local.json` | catalogue des comptes rendus, subventions, baux (non versionné) |
| `public/src/lib/site.js` | nom du site, adresse canonique |

Ce qui ne l'est pas :

- **20 fichiers du moteur** contiennent encore le nom de la commune en dur,
  soit 39 occurrences (URL de scraping, cas particuliers de rattachement) ;
- **38 fichiers du site** en comptent 98 : titres, chapeaux, descriptions. Ils
  ne sont pas paramétrés, il faut les reprendre à la main ;

Ces deux chiffres ne sont pas déclaratifs : ils sont recomptés à chaque
publication par `mesurer_replicabilite()` (analyse AST pour le moteur, afin de
ne pas confondre une docstring qui documente un piège avec du code qui
l'applique) et affichés sur la page « Méthode » du site. Vous pouvez les
refaire.

- les **collecteurs de sites officiels** (`events_scraper`, `cc_cac_scraper`,
  `cm_*`) sont écrits pour la structure des sites de Lasalle et de son
  intercommunalité. Un autre site demande un autre parseur. C'est la partie
  irréductible : il n'existe pas de format commun aux sites de mairie.

En clair : les collecteurs nationaux (SIRENE, BODACC, DVF, OFGL, RNE, Sitadel,
DECP) fonctionnent tels quels pour n'importe quelle commune française. Le reste
demande du travail. Comptez plutôt quelques jours qu'une heure.

---

## Installation

```bash
python3 -m venv venv && venv/bin/pip install -r requirements.txt
sqlite3 db/commune.db < db/schema.sql

cp config/profils_locaux.exemple.json config/profils_locaux.json
cp config/seed_local.exemple.json config/seed_local.json
# → renseigner collectors/config.py (commune, INSEE, EPCI)

venv/bin/python -m collectors            # collecte
venv/bin/python scripts/build_public_snapshot.py   # → snapshot JSON

cd public && npm install && npm run build          # → build/
```

`npm run build` échoue si une page est livrée sans son contenu : voir
`public/scripts/verifier_build.mjs`. Les données étant figées au build, chaque
page lit le snapshot dans son `+page.server.js` — rien n'est chargé côté client.

---

## Ce que ce dépôt ne contient pas

Ni base de données, ni snapshot publié, ni notes d'enquête, ni fichiers
nominatifs. Ce n'est pas un oubli : un dépôt public d'un projet qui documente
des personnes doit être tenu à la même règle que le site qu'il produit.

Les fichiers `config/*_local*.json` et `config/profils_locaux.json` restent sur
la machine qui fait tourner la collecte.

---

## Cadre

Les données publiées sont sous **licence ODbL**, le code sous **licence MIT**.

Une licence ouverte ne dispense pas du RGPD. Les personnes physiques ne figurent
sur le site qu'au titre d'une fonction publique, d'un mandat électif ou d'une
responsabilité inscrite dans un registre public. Un droit de réponse est ouvert,
et toute rectification est appliquée puis signalée comme telle — la donnée
collectée étant conservée à côté de la rectification, jamais remplacée.

Si vous rejouez ce dispositif ailleurs : la partie difficile n'est pas
technique. C'est de décider ce qu'il est légitime de faire dire aux données, et
de tenir cette ligne quand un chiffre exact suggère une conclusion que rien
n'établit.
