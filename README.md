# Vigie Civique

Un observatoire citoyen des décisions publiques d'une petite commune, construit
à partir de données et de documents publics uniquement.

Instance de référence : **[Lasalle (Gard, 30460)](https://vigie-civique-lasalle.pages.dev)**
— environ 1 800 acteurs, 4 300 actes, les marchés publics, le budget et le foncier.

En dessous de 3 500 habitants, l'obligation légale d'ouvrir ses données ne
s'applique pas. C'est précisément là que rien n'est publié, et c'est le trou que
ce dispositif cherche à combler.

---

## Ce que fait le dispositif

Des **collecteurs** interrogent des sources publiques (SIRENE, RNA, BODACC, DVF,
OFGL/DGFiP, DECP/BOAMP, Sitadel, Géorisques, RNE, résultats électoraux, Hub'Eau,
sites officiels de la commune et de l'intercommunalité) et alimentent une base
SQLite. `python3 -m collectors.run_all` en enchaîne 34.

Un **script de publication** (`scripts/build_public_snapshot.py`) en extrait un
snapshot JSON filtré, qui alimente un **site statique** SvelteKit sans backend
ni base de données en ligne.

Un **atelier** (`dashboard/` + `api.py`) permet de corriger, valider et annoter
la base. Il est **facultatif** et ne se met pas en ligne à la légère : voir
« Les deux moitiés » plus bas.

Le filtrage n'est pas un détail : c'est le cœur du dispositif. Il écarte les
personnes physiques sans rôle civique public, les pistes de travail non
établies, les liens de famille, les domiciles et les dates de naissance. Sur
l'instance de Lasalle, il écarte environ 3 800 personnes et 4 500 relations de
la base de travail.

**Une entité non classée n'est pas publiée.** Le classement de périmètre
(C1 la commune, C2 l'intercommunalité, C3 le supra-communal, `lien` le
rattachement) est le dernier step de la collecte, et le snapshot refuse de se
construire sur une base qui ne l'a jamais reçu. Le défaut inverse — publier ce
qu'on n'a pas classé — a tenu jusqu'au 14/08/2026 : sur une instance neuve, il
publiait 10 735 fiches dont 6 151 relevaient d'une commune voisine.

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

## Les deux moitiés : le site public et l'atelier

|  | **Site public** | **Atelier** |
|---|---|---|
| Sert | le snapshot filtré | la base de travail entière, **non filtrée** |
| Hébergement | fichiers statiques, aucun backend | un serveur — ou rien du tout |
| Nécessaire ? | c'est l'objet du dispositif | **non** |

L'atelier lit et écrit la base de travail : celle qui contient ce que le site
public écarte. Le mettre sur l'internet public, c'est exposer ce que le filtre
retient. Trois usages possibles, par ordre de prudence :

1. **en local**, le temps d'une session de travail, sur la machine qui porte la
   base — rien n'est exposé, aucun secret à gérer. C'est le mode par défaut, et
   il suffit tant qu'une seule personne tient l'instance ;
2. **derrière un accès restreint** (VPN, réseau local) pour travailler à
   plusieurs ;
3. **en ligne avec TLS et comptes nommés**, quand plusieurs personnes
   contribuent depuis des lieux différents.

Le troisième cas n'est pas une décision technique : c'est une décision sur qui a
accès à des données qu'on a choisi de ne pas publier. `deploy/README.md` détaille
les trois, et ce que le dispositif fait — et ne fait pas — pour vous.

---

## Rejouer sur une autre commune : l'état réel

Le site a longtemps publié que « changer de commune tient dans un seul fichier
de configuration ». C'était exagéré. Voici où en est la mesure, refaite à
chaque publication par `mesurer_replicabilite()` :

| | fichiers nommant une commune | occurrences |
|---|---|---|
| moteur (collecteurs, scripts, API) | 0 | 0 |
| site public | 0 | 0 |
| atelier | 0 | 0 |

Ces chiffres sont produits par `scripts/verifier_generique.py`, qui est aussi le
contrôle d'admission du kit : le moteur est analysé par AST — pour ne pas
confondre une docstring qui documente un piège avec le code qui l'applique — et
le site, qui est du texte éditorial, ligne à ligne. Vous pouvez les refaire :

```bash
python3 scripts/verifier_generique.py
```

Le contrôle interdit des **formes** et pas seulement des mots : un code INSEE ou
un SIREN littéral, un identifiant d'entité en dur (`XXX_ID = 63` — c'est un
numéro de ligne, il désigne n'importe quoi dans une autre base), une URL de site
officiel, un nom de base de données. Ces quatre règles-là sont exhaustives. La
cinquième, qui cherche des noms de communes, ne vaut que ce que vaut sa liste.

Ce qui est effectivement paramétré :

| Où | Quoi | Versionné ? |
|---|---|---|
| `config/instance.json` | commune, INSEE, EPCI, communes membres, centroïde, éditeur | non |
| `config/publication_rules.json` | règles de publication, sources autorisées, axes de provenance | non (exemple fourni) |
| `config/profils_locaux.json` | élus et candidats | non |
| `config/seed_local.json` | catalogue des comptes rendus, subventions, baux | non |
| `public/src/lib/instance.js`, `dashboard/src/lib/instance.js` | libellés du site et de l'atelier | non — **générés** |

Les deux `instance.js` ne s'éditent pas : `scripts/generer_libelles.py` les
écrit depuis l'instance, et calcule les formes grammaticales — « d'Alès » et non
« de Alès », « au Bez » et non « à Le Bez ». Une chaîne « de {COMMUNE} » écrite
à la main finit toujours par produire une faute sur la commune suivante.

Ce qui reste irréductible : les **collecteurs de sites officiels**
(`events_scraper`, `cm_*`, connecteurs) dépendent de la structure du site de
chaque mairie. Le moteur fournit des connecteurs pour deux familles courantes
(WordPress via son API REST, Drupal en HTML) ; hors de là, il faut écrire
l'analyseur. Il n'existe pas de format commun aux sites de mairie.

En clair : les collecteurs nationaux (SIRENE, RNA, BODACC, DVF, OFGL, RNE,
Sitadel, DECP, élections, Hub'Eau) fonctionnent tels quels pour n'importe quelle
commune française. Le reste demande du travail. Comptez plutôt quelques jours
qu'une heure.

---

## Installation

```bash
python3 -m venv venv && venv/bin/pip install -r requirements.txt

# 1. Amorcer l'instance depuis le code INSEE de la commune.
#    Interroge geo.api.gouv.fr et recherche-entreprises.api.gouv.fr, écrit
#    config/instance.json, adapte les règles de publication, et génère les
#    libellés du site et de l'atelier.
venv/bin/python scripts/init_instance.py 30140

#    → relire config/instance.json : c'est le SEUL endroit du dispositif où une
#      donnée de commune a le droit d'exister. Renseigner la clé « editeur »
#      (nom, statut, courriel, hébergeur) : les mentions légales l'affichent.

cp config/profils_locaux.exemple.json config/profils_locaux.json
cp config/seed_local.exemple.json config/seed_local.json

# 2. Collecter. Le step « init » crée la base, le step « perimetre » la classe.
venv/bin/python -m collectors.run_all

# 3. Publier : snapshot filtré → contrôles → site statique dans public/build/
cd public && npm install && cd ..
./deploy/publier-site.sh
```

### Contrôles

```bash
pip install pytest
python3 -m pytest                        # 100 tests, ~2 s, sans réseau ni base
python3 scripts/verifier_generique.py    # le moteur ne nomme aucune commune
```

Ils portent sur les trois fonctions qui décident de ce qui sort du dispositif :
le filtre de publication, le classement de périmètre, et la liste des fichiers
distribués. Chacune a laissé passer un défaut réel en août 2026. La même chose
tourne en intégration continue à chaque envoi, avec en plus la chaîne complète
sur une commune factice — base, snapshot, contrôle d'étanchéité, site.

`init_instance.py` liste en fin d'exécution ce qui reste à renseigner à la main
— typiquement l'adresse du site de la mairie et le connecteur qui sait le lire.

---

## Travailler à plusieurs, sans serveur

La base est reconstructible : les collecteurs relisent des sources publiques,
n'importe qui la refait avec ce code et un code INSEE. Ce qui ne se régénère
pas, c'est le jugement humain — les sièges tranchés, les sites validés, les
corrections, les notes. C'est petit, et c'est ça qu'on partage.

Chacun collecte donc chez lui, et les ateliers échangent leurs **décisions** par
un dépôt privé, un envoi, une clé USB :

```bash
python3 scripts/exporter_decisions.py            # → decisions/
python3 scripts/importer_decisions.py            # simulation, chez l'autre
python3 scripts/importer_decisions.py --appliquer
```

Les décisions sont désignées par des **clés naturelles** — SIREN, numéro RNA,
identifiant d'avis BOAMP, empreinte de source pour les actes — et jamais par les
`id`, qui sont des compteurs locaux ne voulant rien dire sur une autre machine.

Trois refus, et ce sont eux qui comptent :

- une clé qui ne désigne rien ici **n'est pas rattachée au hasard**, elle est
  rapportée : l'autre atelier a collecté ce que cette base n'a pas ;
- deux jugements contraires sur le même objet **ne sont pas fusionnés**. C'est un
  désaccord éditorial, il remonte à un humain ;
- des décisions portant sur **une autre commune** sont refusées d'emblée.

⚠ **L'export peut nommer des personnes physiques** : l'atelier travaille sur la
base non filtrée. Le dépôt qui le reçoit doit être privé, et ses membres avoir
déjà accès à la base. `--sans-personnes` les retire, au prix de reprendre ces
arbitrages à la main de l'autre côté.

Pour une séance de travail en direct, plutôt qu'en différé : une machine tient
l'atelier, les autres s'y connectent par un réseau privé maillé (Tailscale,
WireGuard). L'atelier continue de n'écouter qu'en local — c'est le « local » qui
s'étend. Rien n'est exposé à l'internet.

---

## Ouvrir l'atelier, en local

L'atelier sert **la base de travail entière, non filtrée** : personnes physiques
sans rôle civique, pistes non établies, liens de famille, adresses. Tout ce que
le site public écarte. En local il n'écoute que `127.0.0.1` et rien n'est
exposé — c'est le mode par défaut, et il suffit tant qu'une seule personne tient
l'instance. Pour les deux autres modes, voir `deploy/README.md`.

Quatre étapes, dans cet ordre. **Les deux premières sont des prérequis** : sans
elles l'API démarre mais refuse toute connexion, et l'erreur n'est pas parlante.

```bash
# 1. Le secret de session. Sans lui, l'API REFUSE DE DÉMARRER et le dit :
#    un service qui ne peut authentifier personne n'a rien à faire en écoute.
#    ⚠ Ne faire ce `cp` qu'UNE FOIS. Le rejouer sur un .env déjà rempli remet
#      le secret à vide, et l'atelier redevient inaccessible.
cp deploy/env.exemple .env
chmod 600 .env
openssl rand -hex 32                      # coller la valeur après « JWT_SECRET= »
#    ADMIN_KEY peut rester VIDE : c'est une clé de service qui contourne le
#    verrou JWT, et une clé absente ne donne aucun accès. ALLOWED_ORIGINS ne
#    sert qu'à un atelier en ligne ; en local, laissez-la vide.

# 2. Un compte. Le mot de passe est demandé au clavier, il n'apparaît nulle part.
venv/bin/python scripts/create_user.py add --email vous@exemple.org --role admin
#    Rôles : admin, validator, contributor.
venv/bin/python scripts/create_user.py list

# 3. L'API — dans un terminal qu'on laisse ouvert.
venv/bin/uvicorn api:app --port 8765

# 4. L'interface — dans un autre terminal.
cd dashboard && npm install && npm run dev
```

Puis **http://localhost:5173**. Vite proxie `/api` vers le port 8765 : rien
d'autre à régler.

Pour vérifier que le verrou fonctionne, l'API étant lancée :

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8765/api/stats
```

**401** est la bonne réponse : la route existe et refuse sans jeton. Ce contrôle
ne dit rien du secret, lui — sans `JWT_SECRET`, l'API ne serait pas là pour
répondre : elle refuse de démarrer, en l'écrivant dans son terminal.

Deux pannes se ressemblent et n'ont rien à voir :

| Ce qu'on voit | Ce que c'est |
|---|---|
| L'API s'arrête au lancement, avec un message sur `JWT_SECRET` | secret vide — étape 1 |
| « Serveur inaccessible » sur la page de connexion, alors que les deux terminaux tournent | l'interface n'atteint pas l'API — port, proxy, ou service arrêté |

Dans le second cas, `curl` sur `127.0.0.1:8765` répond alors que le navigateur
ne passe pas : viser un service local par `127.0.0.1` et jamais par `localhost`,
qui résout d'abord en IPv6 là où le service n'écoute qu'en IPv4.

---

## Publier

`./deploy/publier-site.sh` enchaîne trois étapes, et chacune peut refuser :

1. **le snapshot** — s'arrête si le périmètre n'a jamais été classé ;
2. **les invariants** (`scripts/verify_snapshot.py`) — un contrôle écrit comme
   un adversaire, qui **n'importe pas le builder** et attaque le répertoire
   publié : confidences privées, relations hors liste, coordonnées de personnes,
   secrets, chemins locaux, et part de la commune dans ce qui est publié. Si le
   builder et le contrôleur partageaient du code, ils partageraient leurs bugs ;
3. **le build** — `npm run build` échoue si une page est livrée sans son contenu
   (`public/scripts/verifier_build.mjs`). Les données étant figées au build,
   chaque page lit le snapshot dans son `+page.server.js` : rien n'est chargé
   côté client.

Le résultat est un site statique ordinaire dans `public/build/`, à téléverser où
vous voulez. Le script sait pousser vers Cloudflare Pages
(`CF_PROJECT=… ./deploy/publier-site.sh --deployer`) ; pour tout autre
hébergeur, rien à changer avant la dernière étape.

Détails, atelier sur serveur, secrets et durcissement : **`deploy/README.md`**.

---

## Ce que ce dépôt ne contient pas

Ni base de données, ni snapshot publié, ni notes d'enquête, ni fichiers
nominatifs. Ce n'est pas un oubli : un dépôt public d'un projet qui documente
des personnes doit être tenu à la même règle que le site qu'il produit.

Les fichiers `config/instance.json`, `config/profils_locaux.json` et
`config/seed_local.json` restent sur la machine qui fait tourner la collecte.

`scripts/build_kit.py` fabrique une archive du dispositif — utile pour
l'emporter là où un dépôt distant n'est pas commode. Sa liste de fichiers vient
de `git ls-files` et non d'un parcours du disque : ce qui n'est pas versionné
n'est pas distribué, une règle unique et vérifiable. Un fichier qu'il ne sait
pas lire est **refusé**, pas ignoré.

Son usage principal est cependant d'être un **contrôle** : il refuse de
construire si un nom de personne, un secret, un chemin personnel ou un binaire
non identifié s'est glissé dans ce qui serait distribué. Il tourne à ce titre en
intégration continue, même quand personne n'a besoin de l'archive. L'archive
elle-même n'est pas versionnée.

---

## Cadre

Les données publiées sont sous **licence ODbL**, le code sous **licence MIT**.

Une licence ouverte ne dispense pas du RGPD. Les personnes physiques ne figurent
sur le site qu'au titre d'une fonction publique, d'un mandat électif ou d'une
responsabilité inscrite dans un registre public. Un droit de réponse est ouvert,
et toute rectification est appliquée puis signalée comme telle — la donnée
collectée étant conservée à côté de la rectification, jamais remplacée.

La note de licence de `config/publication_rules.json` décrit le jeu de données
de l'instance dont l'exemple est tiré : elle doit être relue et réécrite avant
publication, pas recopiée.

Si vous rejouez ce dispositif ailleurs : la partie difficile n'est pas
technique. C'est de décider ce qu'il est légitime de faire dire aux données, et
de tenir cette ligne quand un chiffre exact suggère une conclusion que rien
n'établit.
