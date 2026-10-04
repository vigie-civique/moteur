# Refonte du contenu publié — note de conception

> Brouillon, 04/10/2026. Rien n'est codé : cette note décrit ce qui est publié
> aujourd'hui, ce que le site fait faire à ses lecteurs, et propose une forme
> qui parte des séances et des dossiers. Les décisions qui reviennent au
> porteur sont en fin de note (§ 6).

## 0. Comment cette note a été faite

Chaque affirmation porte sa provenance :

- **[code]** — lu dans le dépôt, à la révision `39480a9` (`main`) ;
- **[CI]** — mesuré sur la base d'épreuve, reconstruite comme le fait le job
  `site` (`tests/amorcer_base_ci.py`, puis `build_public_snapshot.py`,
  `verify_snapshot.py`, `npm run build`) ;
- **[en ligne]** — lu sur lasalle., saillans. et brassac.vigie-civique.fr le
  04/10/2026 (manifestes, `stats.json`, `couverture.json`, `events.json`,
  `marches.json`, `dossiers.json`, `liens.json`, pages HTML). Les tailles
  « brut / gzip » sont celles que le serveur renvoie sans et avec
  `Accept-Encoding: gzip` ;
- **[supposé]** — déduit, non vérifié ; dit pourquoi.

Je n'ai pas eu accès à la base de Lasalle : tout ce qui concerne Lasalle vient
de ce qu'elle publie.

**L'essentiel, en dix lignes.**

1. Le snapshot publie 39 entrées, dont quatre familles de fichiers (48 fichiers
   sur la base de CI, 4 953 à Lasalle). Cinq ne sont lus par aucune page ; trois choses sont lues par le
   site sans être déclarées par le registre (§ 1.2, § 1.3).
2. Les feuilles « en clair » ne sont pas des pages du site : ce sont des HTML
   autonomes sous `/data/conseils/`, sans en-tête, sans recherche, sans pied de
   page, absents du sitemap. Les dossiers sont absents du sitemap aussi.
3. Ni l'accueil, ni « Qui décide ? », ni la recherche ne mènent à une séance
   relue ou à un dossier. Les pages de données qui traitent du même sujet qu'un
   dossier (l'eau, les déchets, la forêt, l'enfance, les télécoms) ne le citent
   pas, et le dossier ne les cite pas.
4. Une même séance porte deux nombres de délibérations selon la page (28 mai
   2026 : 39 sur l'accueil, 27 sur /conseils).
5. 1 400 résultats de la recherche de Lasalle mènent à une page qui ne les
   affiche pas, ou à une 404.
6. Recommandation : faire de **la séance** et du **dossier** les deux unités de
   lecture (architecture B), en commençant par des lots qui ne changent aucune
   URL ni aucun octet du snapshot.

---

## 1. L'inventaire

### 1.1 Les fichiers du snapshot

Ordre du registre (`scripts/snapshot/etapes.py`). « CI » : octets sur la base
d'épreuve [CI]. « Lasalle / Saillans / Brassac » : octets déclarés par le
manifeste en ligne [en ligne]. « Lu par » : la route qui lit le fichier, au
build (`+page.server.js`, `+layout.server.js`, `+server.js`) ou dans le
navigateur (`fetch`) [code].

| Fichier | Étape | Ce qu'il sert au lecteur | CI | Lasalle | Saillans | Brassac | Lu par |
|---|---|---|---:|---:|---:|---:|---|
| `couverture.json` | couverture | ce qui a été collecté, quand, et les lacunes connues | 1 850 | 8 482 | 8 868 | 8 648 | /budgets, /carte, /couverture, /deliberations, /vie-locale (build) |
| `entities.json` | ecrire_acteurs | l'annuaire complet | 1 529 | 888 348 | 777 967 | 652 882 | /acteurs-publics, /graphe (build) ; lien /methode, llms.txt |
| `relations.json` | ecrire_acteurs | les liens entre acteurs | 311 | 121 757 | 48 955 | 57 325 | /elus, /graphe, /qui-decide |
| `events.json` | ecrire_actes | tous les actes et événements | 6 735 | 4 135 500 | 2 585 325 | 3 956 166 | /deliberations, /deliberations/[annee], /com-com, /couverture, /vie-locale, sitemap |
| `event_links.json` | ecrire_actes | quel acteur est cité dans quel acte | 196 | 492 803 | 244 330 | 477 100 | **aucune route** (décrit au README) |
| `flows.json` | ecrire_flux | les versements | 31 | 247 118 | 131 786 | 143 170 | /argent, /finances |
| `layers/*.geojson` (4) | ecrire_couches | les points de la carte | 204 | 369 124 | 414 640 | 290 326 | /carte (navigateur) |
| `budget.json` | ecrire_finances | budgets annexes, comptes | 34 | 21 682 | 21 621 | 21 481 | /budgets |
| `budget_vote.json` | ecrire_finances | budget primitif voté | 37 | 26 296 | 37 | 37 | /budgets |
| `ofgl.json` | ecrire_finances | agrégats OFGL | 30 | 69 660 | 60 979 | 70 259 | /, /argent, /budgets |
| `dvf.json` | ecrire_finances | mutations foncières | 29 | 120 103 | 213 966 | 200 447 | /argent, /urbanisme |
| `marches.json` | ecrire_finances | marchés et avis | 33 | 39 110 | 35 339 | 28 721 | /, /argent, /marches |
| `approbations.json` | ecrire_finances | projets approuvés | 38 | 38 | 38 | 38 | /projets-approuves — **vide sur les trois instances** |
| `environnement.json` | environnement | eau, rivières, risques, ICPE, déchets, DPE | 304 | 226 275 | 165 059 | 234 662 | /environnement |
| `territoire.json` | territoire | INSEE, équipements, enfance, télécoms | 219 | 1 294 174 | 1 250 244 | 1 391 962 | /territoire |
| `popolo.json` | popolo | mandats au format Popolo | 2 446 | 607 767 | 512 702 | 469 296 | **aucune route** (lien /methode, llms.txt) |
| `elections.json` | elections | résultats électoraux | 2 | 10 961 | 14 505 | 14 725 | /elections, /qui-decide |
| `fiscalite.json` | fiscalite | taux d'imposition | 47 | 175 617 | 177 340 | 161 807 | /argent, /impots |
| `intercommunalite.json` | intercommunalite | compétences, délégués | 1 373 | 15 388 | 19 038 | 18 199 | /com-com, /elections |
| `elus_rne.json` | elus | élus en fonction (RNE) | 905 | 64 318 | 70 004 | 81 434 | /elus, /qui-decide |
| `urbanisme.json` | urbanisme | autorisations, PLU | 922 | 305 180 | 749 713 | 648 337 | /urbanisme |
| `croisement_foncier.json` | croisement_foncier | foncier croisé avec les actes | 35 | 5 246 | 9 215 | 10 726 | **aucune route** |
| `actualite.json` | actualite | le fil, les séances regroupées, l'agenda | 4 344 | 186 635 | 192 525 | 181 053 | /, /nouveautes, rss.xml |
| `corrections.json` | corrections | le journal des corrections | 33 | 3 586 | 1 772 | 1 771 | /corrections |
| `conseils.json` | graphe | l'index des séances relues | 33 | 4 960 | 33 | 33 | gabarit (toutes pages : `aConseils`), /conseils |
| `conseils/*.html` | graphe | les feuilles « en clair » | 0 fichier | 16 → 425 734 | 0 | 0 | lien direct depuis /conseils et /deliberations/[annee] |
| `dossiers.json` | graphe | les dossiers retenus, en markdown | 7 026 | 316 794 | 34 | 34 | gabarit (`aDossiers`), /dossiers, /dossiers/[slug] |
| `liens.json` | graphe | qui cite chaque acte ; alias d'ancres | 1 793 | 66 115 | 2 701 | 48 953 | /deliberations/[annee] |
| `lacunes.json` | graphe | questions ouvertes des dossiers | 2 134 | 6 052 | 50 | 50 | **aucune route** |
| `personnes_morales.json` | graphe | personnes morales par acte | 327 | 694 | 211 | 915 | **aucune route** (destiné à `docs/federation.md`) |
| `transparence.json` | transparence | HATVP, contentieux | 255 | 1 057 | 3 244 | 2 588 | /qui-decide |
| `conflits.json` | conflits | élus et structures, déports | 854 | 2 622 | 1 426 | 2 018 | /qui-decide, /elus-et-structures |
| `entite/*.json` | fiches_acteurs | une fiche par acteur | 3 → 2 551 | 1 456 → 5 086 463 | 1 255 → 2 595 359 | 1 075 → 4 117 903 | /entite/[id] (build), sitemap |
| `extrait/*.json` | extraits | le texte d'un acte | 6 → 870 | 3 442 → 11 124 415 | 975 → 2 689 793 | 2 062 → 2 198 078 | /deliberations/[annee] (navigateur, à la demande) |
| `entity_index.json` | index_recherche | index court des acteurs | 342 | 181 213 | 157 109 | 136 791 | /, /entite (liste des pages), /recherche (embarqué) |
| `recherche_index.json` | index_recherche | index transversal | 1 652 | 1 067 354 | 802 787 | 1 156 269 | /recherche (navigateur) |
| `stats.json` | stats | compteurs, statut, exclusions | 4 670 | 6 309 | 5 939 | 6 147 | gabarit et onze routes |
| `README.md` | dictionnaire | le dictionnaire des données | 6 027 | 6 517 | 6 403 | 6 431 | lien /methode, llms.txt |
| `manifeste.json` | manifeste | la preuve d'intégrité | 7 954 | 825 143 | 380 709 | 527 516 | `verify_snapshot.py`, `comparer_snapshots.py` |
| **Total** | | | **58 175** (48 fichiers) | **≈ 28,6 Mo** (4 953) | **≈ 14,4 Mo** (2 269) | **≈ 17,3 Mo** (3 176) | |

Remarques sur les tailles :

- **La base de CI ne contient aucune séance relue** [CI] : `conseils.json` y est
  vide et aucun `conseils/*.html` n'est produit. Le chemin des feuilles « en
  clair », le cœur du chantier, n'est éprouvé par aucune construction de CI.
  C'est le lot 0 (§ 5).
- Les fichiers les plus lourds ne sont pas ceux que le lecteur télécharge :
  `extrait/` (11 Mo à Lasalle) est lu acte par acte, `events.json` et
  `territoire.json` ne sont lus qu'au build. Ce que le navigateur télécharge
  en entier, c'est `recherche_index.json` (1,07 Mo, 159 Ko gzip) et les
  couches de la carte.
- Le nombre de fichiers compte : Lasalle publie 4 953 fichiers de données et
  ≈ 1 500 pages (son sitemap compte 1 501 URL), chacune accompagnée d'un
  `__data.json` [CI : 43 `__data.json` pour 44 pages]. Soit ≈ 8 000 fichiers
  servis [supposé, par extrapolation du ratio de la CI].

### 1.2 Publié sans être lu

[code] Aucune route ni aucun composant ne lit :

| Fichier | Poids à Lasalle | Ce qu'on peut en dire |
|---|---:|---|
| `event_links.json` | 493 Ko | Remplacé côté site par `entite/*.json` (cf. `fiches.py`, qui le dit). Reste au README comme donnée ouverte. |
| `popolo.json` | 608 Ko | Donnée ouverte délibérée (lien /methode, llms.txt). Pas un défaut. |
| `croisement_foncier.json` | 5 Ko | Ni lu, ni lié, ni dans llms.txt. Il n'existe que pour qui lit le README. |
| `lacunes.json` | 6 Ko | Les questions ouvertes des dossiers — exactement ce qu'un lecteur de dossier voudrait voir — ne sont affichées nulle part. |
| `personnes_morales.json` | 1 Ko | Préparé pour la fédération (`docs/federation.md`). Pas un défaut. |

Et deux fichiers lus mais vides partout : `approbations.json` (la page
/projets-approuves est servie vide sur les trois instances, et figure au
sitemap) ; `budget_vote.json` à Saillans et Brassac [en ligne]. `liens.json`
pèse 48 Ko à Brassac, qui n'a ni dossier ni séance relue : c'est la table
d'alias `#a{id}` → clé, gardée « pour un cycle » (`collectors/graphe.py`).

### 1.3 Lu sans être déclaré

[code] Ce que le site lit et que le registre ne déclare pas — donc que le
manifeste ne couvre pas et que le comparateur ne voit pas :

1. **`public/src/lib/instance.js`** — l'identité de l'instance (nom de la
   commune, intercommunalité, statut, contact), importée par presque toutes
   les pages. Générée par `scripts/generer_libelles.py`, appelée dans `main()`
   de `build_public_snapshot.py` avec un `except` qui la laisse passer en
   silence (« ne doit jamais bloquer la publication »), et pas par
   `build_snapshot()`. Un snapshot ne prouve donc pas avec quels libellés il a
   été construit. [supposé] Le flux de publication de l'atelier passe par
   `build_snapshot()` ; il ne régénère pas les libellés — non vérifié.
2. **`public/static/carte/fond.pmtiles`** — le fond de carte (≈ 2,2 Mo selon
   `lib/carte/fond.js`), produit par `scripts/carte_fond.py`, lu par /carte,
   /urbanisme et les fiches.
3. **`dossiers/*.md` de l'instance** — lus seulement en aperçu local
   (`VIGIE_DOSSIERS_BROUILLONS=1`). Légitime : rien ne sort par ce chemin.

### 1.4 Les routes

« CI » : octets du HTML prérendu sur la base d'épreuve [CI]. « Lasalle » :
brut / gzip [en ligne]. « Atteinte depuis » : les pages qui y mènent par un
lien écrit [code] (le bandeau d'état et le pied de page sont sur toutes les
pages).

| Route | Ce qu'elle sert | Lit | CI | Lasalle | Atteinte depuis |
|---|---|---|---:|---:|---|
| `/` | chiffres, trois portes, dernières séances, agenda | stats, actualite, entity_index, ofgl, marches | 20 804 | 27 747 / 6 371 | partout |
| `/nouveautes` « Récent » | le fil daté | actualite | 18 810 | 239 911 / 29 208 | en-tête, accueil |
| `/qui-decide` | carrefour gouvernance | stats, relations, elections, elus_rne, conflits, transparence | 15 943 | 16 924 / 4 469 | en-tête, accueil, comprendre, fil de /conseils |
| `/conseils` | liste des séances relues | conseils, stats | 10 717 | 21 011 / 4 406 | **en-tête seulement** |
| `/data/conseils/*.html` | une feuille « en clair » (hors gabarit) | — | — | ≈ 26 600 / feuille | /conseils, /deliberations/[annee] |
| `/dossiers` | liste des dossiers | dossiers | 13 043 | 58 169 / 9 851 | en-tête (s'il y en a), pied, menu mobile |
| `/dossiers/[slug]` | un dossier | dossiers | 24 335 | 153 391 / 39 774 (eau) | /dossiers, « Cité dans » de /deliberations/[annee] |
| `/deliberations` | sommaire et index des actes | events, couverture | 13 032 | **631 943 / 101 656** | accueil, qui-decide, budgets, comprendre/* |
| `/deliberations/[annee]` | les actes d'une année | events, liens, extrait/* | 13 410–18 575 | 603 297 / 38 410 (2025) | /deliberations, recherche, dossiers, feuilles CC |
| `/argent` | carrefour argent | stats, ofgl, marches, flows, dvf, fiscalite | 14 462 | 14 787 / 3 890 | en-tête, accueil, comprendre |
| `/budgets` | budget communal | budget, budget_vote, ofgl, couverture | 10 968 | 106 751 / 16 854 | argent, impots, comprendre/budget |
| `/finances` | versements | flows | 10 445 | 205 270 / 22 194 | argent |
| `/marches` | marchés et avis | marches | 11 360 | 72 077 / 10 096 | argent, accueil, urbanisme, projets-approuves |
| `/impots` | fiscalité | fiscalite | 10 631 | 149 510 / 10 733 | argent, environnement |
| `/urbanisme` | permis, PLU, DVF | urbanisme, dvf | 11 454 | 152 352 / 20 389 | argent |
| `/projets-approuves` | projets approuvés | approbations | 11 174 | 11 199 / 3 454 | marches — vide partout |
| `/acteurs-publics` « Qui agit » | l'annuaire | entities | 13 757 | 217 494 / 34 927 | en-tête, accueil, carte, fiches |
| `/carte` | la carte | stats, couverture, layers | 12 202 | 12 546 / 3 714 (+ couches) | accueil, annuaire |
| `/entite/[id]` | une fiche | entite/[id] | 11 609–13 616 | 268 135 / 29 522 (la CC) | annuaire, carte, recherche, marchés, finances… |
| `/graphe` | liens entre acteurs | entities, relations | 11 810 | 117 624 / 17 267 | qui-decide |
| `/elus` | conseils municipaux | elus_rne, relations | 11 111 | 59 043 / 8 038 | qui-decide, elections, comprendre/mandats |
| `/elus-et-structures` | déports | conflits | 12 428 | 17 375 / 5 100 | qui-decide (+ 301 depuis /conflits-interets) |
| `/elections` | scrutins | elections, intercommunalite | 10 728 | 34 970 / 6 277 | qui-decide |
| `/com-com` | l'intercommunalité | intercommunalite, events | 16 316 | 49 440 / 9 146 | accueil, qui-decide, comprendre |
| `/territoire` | INSEE, équipements, enfance, télécoms | territoire | 10 804 | 402 742 / 41 582 | pied, accueil, menu mobile, budgets |
| `/environnement` | eau, rivières, risques, forêt, déchets | environnement | 10 721 | 208 880 / 27 436 | pied, accueil, menu mobile |
| `/vie-locale` | agenda | events, couverture | 11 194 | 116 331 / 17 053 | pied, accueil, menu mobile, deliberations |
| `/recherche` | recherche transversale | entity_index (build), recherche_index (navigateur) | 11 320 | 167 283 / 37 550 + 1 067 354 / 159 474 | champ d'en-tête |
| `/comprendre` et 3 sous-pages | pédagogie | — | 12 853–18 049 | 12 874–18 100 | en-tête, accueil |
| `/methode` | sources, réutilisation | stats | 29 797 | 30 112 / 9 912 | pied, accueil, comprendre |
| `/couverture` | couverture et lacunes | couverture, events | 18 207 | 24 340 / 6 476 | bandeau d'état (toutes pages) |
| `/corrections`, `/contact`, `/mentions-legales`, `/repliquer` | institutionnel | corrections, stats | 10 782–16 352 | 10 823–20 137 | pied |
| `llms.txt`, `rss.xml`, `sitemap.xml`, `robots.txt` | machines | stats, actualite, events, entite/ | — | 3 608 ; 26 803 ; 183 273 | — |

Le plancher d'une page est ≈ 10,5 Ko de HTML [CI] : c'est le gabarit. Le
commentaire de /deliberations annonce « ~57 Ko » pour l'index des titres ; la
page en pèse 632 Ko brut à Lasalle [en ligne] — l'index des 3 658 actes
d'assemblée, dont chaque titre figure deux fois dans le HTML, liste et données
d'hydratation [en ligne, vérifié sur un échantillon].

### 1.5 Ce que l'inventaire fait voir

- **Les feuilles « en clair » sont hors du site.** `collectors/en_clair/rendu.py`
  écrit un document HTML complet avec un seul lien interne, « ← Toutes les
  séances » [code, en ligne]. Pas d'en-tête, pas de recherche, pas de pied de
  page (donc ni « Droit de réponse » ni « Corrections »), pas de contrôle par
  `verifier_build.mjs` (« 44 pages vérifiées » ne les compte pas) [CI].
- **Le sitemap ignore les deux pages qui comptent.** `/conseils` y figure ;
  `/dossiers`, chaque `/dossiers/[slug]` et chaque feuille en sont absents
  [code : `sitemap.xml/+server.js` ; en ligne : 1 501 URL, aucune de dossier].
- **Trois îles.** Les dossiers de Lasalle portent 129 liens internes, dont 128
  vers /deliberations et un vers /impots [en ligne] ; les pages /environnement et
  /territoire ont pourtant des ancres qui sont, au mot près, leurs sujets
  (`#eau-du-robinet`, `#foret-et-feu`, `#dechets`, `#enfance`, `#telecoms`) et
  ne renvoient à aucun dossier [code]. Une séance relue cite ses actes
  (52 retours « en clair » dans `liens.json` à Lasalle) mais aucun dossier ;
  la fiche d'un acteur ne sait pas qu'un dossier le cite.
- **Les feuilles municipales ne mènent pas aux actes.** Les feuilles du conseil
  communautaire relient leurs actes (11 liens vers /deliberations/2026 pour le
  23/09) ; celles du conseil municipal n'en ont aucun [en ligne]. Cause : sur
  les 176 délibérations municipales de 2026, 24 ont une clé datée
  (`c-2026-…`), les autres une ancre faible `a{id}` [en ligne] — le numéro de
  l'acte n'a pas été lu. Ce n'est pas un défaut de forme : c'est l'extraction.

---

## 2. Les parcours

Les clics sont comptés depuis l'accueil de Lasalle. « Mobile » : sous 1 216 px,
avec sept entrées d'en-tête, la navigation passe dans le menu
[code : `+layout.svelte`, règle `.sept`].

### 2.1 Un habitant : « qu'est-ce qui a été décidé sur l'eau ? »

| Chemin | Pages | Clics (bureau / mobile) | Poids gzip | Ce qu'il obtient |
|---|---:|---|---:|---|
| Par l'en-tête : « Dossiers thématiques » → « L'eau à Lasalle » | 3 | 2 / 3 | 56 Ko | la réponse, écrite, sourcée |
| Par les portes de l'accueil : « Qui décide ? » → « Délibérations & décisions » → filtrer « eau » → un résultat | 4 | 3 + saisie / idem | 151 Ko | des titres d'actes, un PDF partagé par toute la séance |
| Par la recherche (« Rechercher un acteur… ») | 2 | 1 + saisie | 197 Ko | actes, acteurs, marchés, versements — **ni dossier ni séance** |
| Par « Pour situer les chiffres » → Environnement → « L'eau du robinet » | 2 | 1 + défilement | 34 Ko | des indicateurs, sans lien vers le dossier |

Où il se perd :

1. Le corps de l'accueil ne nomme ni les dossiers ni les séances relues [code :
   aucun lien vers /dossiers ni /conseils dans `+page.svelte`]. Sur mobile, les
   deux pastilles mises en avant sont derrière le menu.
2. Les trois portes de l'accueil mènent toutes à de la donnée rangée ; le
   chemin qu'elles proposent pour « décidé sur l'eau » est le plus long et
   n'aboutit pas au dossier, sauf à remarquer le « Cité dans » sous un acte.
3. Le champ de recherche annonce « un acteur » ; l'index contient aussi les
   actes, mais pas les dossiers ni les séances.

Variante — « qu'a décidé le dernier conseil ? » : l'accueil affiche « 10 sept.
Conseil municipal — 9 délibérations ». Le lien mène à **/deliberations**, le
sommaire de toutes les années (632 Ko) [code, en ligne], alors qu'une feuille
« en clair » de cette séance existe, relue le 04/10. Il faut ensuite choisir
2026, puis retrouver le 10 septembre : 3 clics et 640 Ko pour une page qui
existe à 1 clic.

### 2.2 Un élu ou un agent : vérifier un fait

Cas : la feuille du 28 mai 2026 titre « Associations : l'enveloppe baisse de
30 % ».

| Étape | Page | Clics |
|---|---|---:|
| En-tête « Conseils en clair » | /conseils | 1 (2 sur mobile) |
| La séance | /data/conseils/2026-05-28_conseil-municipal.html — hors du site | 2 |
| Note de bas de page → la pièce | PDF de la commune | 3 |
| Retrouver l'acte sur le site | impossible depuis la feuille (feuille municipale, actes sans clé) : passer par /deliberations → 2026 → 28 mai | 6 |

Où il se perd :

1. **Deux nombres pour la même séance.** L'accueil annonce 39 délibérations le
   28 mai, /conseils en annonce 27 ; 9 contre 16 le 10 septembre ; 18 contre 19
   le 30 juin [en ligne]. L'un compte les actes publiés de la date et de
   l'assemblée (`actualite.py`), l'autre les actes du relevé relu
   (`en_clair.py`) [code]. Aucune page ne dit lequel croire ni pourquoi ils
   diffèrent — c'est précisément ce qu'un élu viendra contester.
2. Depuis la feuille, pas de pied de page : ni « Droit de réponse », ni
   « Corrections ».
3. Pour vérifier un zéro (« 0 marché attribué recensé »), l'accueil affirme :
   « Ce n'est pas une lacune de collecte » [en ligne, sur les trois
   instances]. Or les PV de Lasalle en contiennent 77 (constat du porteur).
   L'agent qui le sait conclut que le site se trompe partout ailleurs aussi.

### 2.3 Un journaliste ou un chercheur : trouver une source

| Besoin | Chemin | Clics | Remarque |
|---|---|---:|---|
| Les données en masse | pied « Méthode & sources » → « Réutiliser les données » | 2 | `events.json` : 4,1 Mo (313 Ko gzip) ; ni séances ni dossiers dans la liste (llms.txt non plus) |
| Citer un acte | /deliberations/2025#c-2025-41 | — | stable si la clé est datée ; à Lasalle, 152 des 176 délibérations municipales de 2026 n'ont qu'une ancre `a{id}`, qui change au rejeu (alias gardé « un cycle ») |
| Citer une séance relue | /data/conseils/…html | — | adresse sous `/data/`, hors sitemap, sans métadonnées de page |
| Trouver un dossier par un moteur | — | — | absent du sitemap |
| Suivre la source d'un résultat de recherche | /recherche → résultat | 1 | 1 421 des 5 079 résultats « acte » de Lasalle (BODACC 731, Sitadel 441, agenda, BOAMP…) pointent vers /deliberations/AAAA#a{id}, page qui n'affiche que les actes d'assemblée : l'ancre n'existe pas, et l'année manque parfois (/deliberations/2008 → 404) [en ligne ; CI : le « Scrutin d'épreuve » pointe vers /deliberations/2026, inexistante] |

Où il se perd : il trouve les faits bruts, mais rien ne lui dit qu'il existe un
texte relu qui les assemble, et les adresses qu'il citerait ne sont pas toutes
stables.

---

## 3. Trois architectures

Les trois respectent les mêmes règles de fond : rien qui ne soit déjà
publiable ; la commune et l'intercommunalité jamais mêlées sous un même titre
ou un même total ; aucun montant additionné entre deux budgets.

### A — Même plan, autre ordre

**Accueil.** Deux blocs en tête, chacun affiché seulement s'il a un contenu :
« La dernière séance relue » (lien vers sa feuille) et « Les dossiers » (titres
et chapeaux). Puis les chiffres et les trois portes, inchangés. Dans « Ce que
la commune vient de décider », une séance relue renvoie à sa feuille, les
autres à /deliberations/AAAA au lieu du sommaire.

**Navigation.** Inchangée, libellés alignés sur les titres (défaut 6). Une
carte « Le conseil en clair » sur /qui-decide.

**Routes.** Aucune ne change.

**Instance sans séance ni dossier.** L'accueil est celui d'aujourd'hui.

**Snapshot.** Rien d'obligatoire. Au mieux, un champ `en_clair` (le fichier)
sur les items de séance d'`actualite.json`.

**Ce que cela casse.** Rien.

**Limite.** Les feuilles restent hors du site, les deux nombres par séance
restent, et Saillans et Brassac n'y gagnent rien : la structure part toujours
de la donnée.

### B — La séance et le dossier comme unités de lecture (recommandée)

Deux entrées vers la décision, l'une par le temps (la séance), l'autre par le
sujet (le dossier). La donnée rangée devient le registre où l'on vérifie.

**Accueil.**

1. Une phrase : ce qu'est le site.
2. **Au conseil** — la dernière séance municipale et la dernière séance
   communautaire, en deux lignes nommées : date, titre (celui de la feuille si
   elle est relue, sinon « N délibérations lues dans les pièces »), lien vers
   la page de la séance. Le prochain conseil (bloc existant).
3. **Les dossiers** — les dossiers publiés. Sans dossier : « Ce que les données
   disent de… » et la liste des sujets que les pages de données couvrent déjà
   (l'eau, les déchets, la forêt, l'enfance, les télécoms…), vers leurs
   ancres — sans texte rédigé, donc sans rien à relire.
4. La recherche, annoncée pour ce qu'elle est : « un sujet, un nom, un montant ».
5. **Les données** — les chiffres (zéros avec leur raison, cf. défaut 2) et les
   trois portes, plus bas.

**Navigation.** Six entrées, dont le libellé est le titre de la page d'arrivée :
Séances · Dossiers · Qui décide · Où va l'argent · Qui agit · Comprendre.
« Récent » reste sur l'accueil (« Tout le flux ») et passe au pied de page. Les
mots exacts sont au porteur (§ 6).

**Les pages de séance.** Une page par séance publiée, dans le gabarit du site :
`/conseils/2026-05-28_conseil-municipal` — le même nom que la feuille
existante. Elle se construit pour **toutes** les séances, relues ou non, à
partir des actes déjà publiés regroupés par (date, portée) — le regroupement
qu'`actualite.py` fait déjà [code]. Elle porte : l'assemblée, la date, les
pièces, la liste des délibérations (titre, vote, lien vers l'ancre de l'acte),
et, si la séance est relue, la feuille « en clair » (intégrée ou liée, la
version A4 restant à son adresse pour l'impression). Quand le relevé et la
base ne comptent pas pareil, la page donne les deux nombres et dit d'où vient
chacun.

Rien de nouveau n'est publié : une séance non relue n'affiche que des actes
qui sont déjà sur /deliberations, sous une autre présentation.

**Les sujets.** Un registre de sujets, générique, dans le moteur (aucune
commune nommée) : identifiant, titre, sections de données correspondantes. Le
dossier déclare son sujet dans son en-tête (`sujet: eau`), la section de
données affiche « Lire le dossier » quand un dossier publié porte ce sujet, et
le dossier renvoie à la section. C'est le pont qui manque entre les îles, et
c'est ce qui donne une page /dossiers non vide à une instance qui n'a rien
écrit.

**Ce que devient chaque route.**

| Route | Devient |
|---|---|
| `/` | refondue (ci-dessus) |
| `/conseils` | la liste de **toutes** les séances, par année, les relues marquées |
| `/conseils/[seance]` | **nouvelle** : la page de séance |
| `/data/conseils/*.html` | conservées, version imprimable ; leur lien retour mène à la page de séance |
| `/dossiers`, `/dossiers/[slug]` | mêmes adresses ; la liste ajoute les sujets sans dossier ; le dossier renvoie aux sections de données |
| `/qui-decide` | ajoute la carte des séances (le fil d'Ariane de /conseils y mène déjà) |
| `/deliberations`, `/deliberations/[annee]` | inchangées : le registre ; « Cité dans » mène à la page de séance |
| `/environnement`, `/territoire` | inchangées ; chaque section-sujet gagne « Lire le dossier » s'il existe |
| `/nouveautes` | inchangée ; sort de l'en-tête |
| `/recherche` | indexe séances et dossiers ; chaque résultat mène à une page qui l'affiche |
| toutes les autres | inchangées |

**Instance sans séance relue ni dossier** (Saillans, Brassac, instance neuve).
/conseils liste 105 séances à Saillans et 314 à Brassac [en ligne : couples
(date, portée) distincts des séances publiées], aucune marquée « en clair ».
L'accueil montre la dernière séance de chaque assemblée. /dossiers liste les
sujets que les données couvrent. Une instance neuve, sans procès-verbal
collecté, affiche à la place de la liste la raison tirée de la couverture
(« les procès-verbaux du conseil municipal n'ont pas été collectés »), jamais
« aucune séance ».

**Ce que cela demande au snapshot.**

| Fichier | Changement |
|---|---|
| `seances.json` | **ajouté** : une ligne par séance publiée — identifiant, date, portée, assemblée, nombre d'actes publiés, pièces, et si relue `en_clair` {fichier, titre, relu_le, actes du relevé}. Nouvelle étape après `graphe`. |
| `conseils.json` | redondant avec `seances.json` : gardé un cycle, puis retiré (§ 6) |
| `conseils/*.html` | lien retour vers `/conseils/<nom>` |
| `actualite.json` | les items de séance gagnent `seance` (l'identifiant de page) |
| `liens.json` | un retour « en clair » désigne la page de séance, plus le fichier |
| `dossiers.json` | gagne `sujet`, lu dans l'en-tête du dossier |
| `recherche_index.json` | gagne les séances et les dossiers ; l'adresse d'un événement non délibératif devient celle où il s'affiche |
| `sujets.json` | **ajouté** (petit) : pour chaque sujet du registre, s'il a des données dans cette instance et s'il a un dossier |

**Ce que cela casse.** Aucune URL ne disparaît. `/conseils` change de contenu
(la liste grandit). Les adresses ajoutées (`/conseils/<nom>`) n'entrent en
collision avec rien. Poids : ≈ 216 pages de séance à Lasalle, 105 à Saillans,
314 à Brassac, chacune avec son `__data.json` [supposé : ≈ 15 Ko de HTML
chacune, d'après les pages comparables de la CI].

### C — Tout par sujet

**Accueil.** Une grille de sujets (l'eau, les déchets, l'école, le logement,
le budget, les élus…). Chaque page de sujet assemble le dossier s'il existe,
les sections de données aujourd'hui dispersées, les actes, marchés et
versements du sujet — commune et intercommunalité séparées.

**Navigation.** Sujets · Séances · Chercher · Comprendre.

**Routes.** `/environnement`, `/territoire`, `/vie-locale` sont découpées en
`/sujets/<slug>` ; `/dossiers/<slug>` devient `/sujets/<slug>` ; `/qui-decide`,
`/argent`, `/acteurs-publics` deviennent des index.

**Instance sans dossier.** Ne tient que si les actes, marchés et versements
sont étiquetés par sujet automatiquement. Sinon, des pages de sujet vides
partout.

**Snapshot.** Un étiquetage thématique de chaque acte, marché et versement — le
mécanisme que `docs/dossiers-thematiques.md` (§ 4.1) laisse à décider ; un
fichier par sujet ; `environnement.json` et `territoire.json` redécoupés.

**Ce que cela casse.** Toutes les adresses de pages de données et de dossiers
(301 à poser) ; et les ancres citées ailleurs (`/environnement#eau-du-robinet`)
ne survivent pas à une redirection, le fragment n'arrivant pas au serveur.

**Limite de fond.** Une étiquette posée par la machine est une extraction : la
publier sans relecture contredit « extraction ≠ publication », la relire pour
trois instances est un chantier d'atelier qui n'existe pas.

### Recommandation : B, livrée par les lots de A d'abord

1. **B donne une entrée vers la décision à chaque instance**, relue ou non :
   Saillans et Brassac ont des procès-verbaux (105 et 314 séances), pas de
   relecture. A ne leur apporte rien ; C leur promet des sujets vides.
2. **B ne casse aucune adresse.** C en casse des dizaines, ancres comprises.
3. **B règle ce qu'un élu contestera d'abord** : une séance, une page, ses deux
   nombres expliqués.
4. **B ramène les feuilles dans le site** : en-tête, recherche, droit de
   réponse, sitemap.
5. **Le snapshot ne fait que s'enrichir** : deux fichiers ajoutés, des champs
   ajoutés, un fichier retiré après un cycle. Chaque étape se juge au
   comparateur.
6. C reste l'horizon, quand un étiquetage par sujet existera et sera relu. Le
   registre des sujets de B en est la première pierre.

---

## 4. Les six défauts

| # | Défaut | Ce que la forme règle | Ce qui relève d'autre chose |
|---|---|---|---|
| 1 | L'accueil s'ouvre sur des compteurs et trois portes ; conseils et dossiers cachés sur mobile | Accueil et navigation de B (lots 1 et 7) : séances et dossiers dans le corps de la page, pas seulement dans l'en-tête. | Rien. |
| 2 | « 0 marché de la commune » alors que les PV en révèlent 77 | (a) La phrase « Ce n'est pas une lacune de collecte » est écrite en dur dans l'accueil et dans /marches [code] et s'affiche sur les trois instances [en ligne] : elle doit découler d'un état déclaré, pas d'un texte fixe. (b) Le snapshot calcule pour chaque compteur son état (`absente` / `vide` / `servie`) et sa raison, au lieu que chaque page le déduise en JavaScript. (c) Attention : `couverture.collecteurs[x].statut` est le statut du **dernier** passage — `marches` vaut `empty` sur les trois instances alors que `marches.json` porte 58 lignes [en ligne] ; l'état doit dire « a déjà rapporté », pas « a rapporté la dernière fois ». | Les 77 attributions lues dans les PV et jamais entrées en base : extraction et relecture à l'atelier. Le snapshot ne peut pas les voir. Les compter publiquement (« 77 lues, non relues ») est une décision (§ 6). |
| 3 | Deux fiches pour une association, l'une vide | La fiche vide dit quelles sources ont été consultées (cf. 4). Option : « Autres fiches au nom proche », calculé entre fiches **déjà publiées**, marqué comme calcul, sans affirmer l'identité (§ 6). | La fusion : atelier. `scripts/rapprocher_entites.py` propose les paires en lecture seule ; l'arbitrage vit hors du dépôt (`~/Claude/scripts/vigie_arbitrage.py`, cité dans sa docstring) [code]. Les paires devraient entrer dans la file de tâches de l'atelier. |
| 4 | La fiche ne dit pas ce qu'on ne sait pas (subventions département, État) | Un bloc « Ce que cette fiche peut dire » : pour chaque financeur, collecté ou non. La table financeur → collecteur se publie **une fois** dans `couverture.json`, pas dans chaque fiche (×1 456 à Lasalle). Aujourd'hui la section « Flux financiers » n'apparaît que s'il y a des flux, et la fiche vide dit « dans les sources collectées à ce jour » sans les nommer [code]. | Le collecteur départemental n'existe pas [code : `collectors/` a `occitanie_region`, `subventions_etat`, `jaune_associations`, rien pour le département]. |
| 5 | Un acheteur sous cinq graphies | Entièrement la forme : les 58 lignes de `marches.json` à Lasalle portent toutes `acheteur_id = 8631` [en ligne] ; la page liste les `acheteur_nom` bruts de chaque source [code : `marches/+page.svelte`]. Le snapshot publie le nom de la fiche publique de l'acheteur, garde la graphie de la source dans un champ à part, et la page groupe par identifiant. | Rien. |
| 6 | Titres et en-tête divergents | Une table de libellés : libellé de navigation = `<title>` = `<h1>` = fil d'Ariane. Relevé [code] : « Conseils en clair » / « Le conseil en clair » ; « Dossiers thématiques » / « Dossiers » (titre, pied, menu mobile) ; « Qui agit » / titre « Acteurs publics » / h1 « Qui agit ? » ; « Récent » / « Ce qui a changé ». Le fil « Qui décide › Le conseil en clair » mène à une page qui ne cite pas /conseils. Un contrôle au build peut l'exiger. | Rien. |

Deux constats hors des six, rencontrés en chemin :

- **La recherche mène à des pages qui n'affichent pas le résultat** (§ 2.3) :
  forme du snapshot (`recherche.py` donne à tout événement une adresse sous
  /deliberations). Lot 2.
- **Hors chantier, à trancher** : les titres BODACC de l'index de recherche
  portent des noms de personnes physiques (« … — AIGOUAL LOCATIONS BTP,
  FLORES, Jean-Luc, Bernard — … ») [en ligne]. La règle admet « une mention
  dans un acte » ; qu'une annonce BODACC en soit un est à confirmer.

---

## 5. Les lots

Du plus petit au plus grand. Chaque lot est livrable seul. « Comparateur » : ce
que `scripts/comparer_snapshots.py` doit dire entre le snapshot de référence
d'avant et celui d'après, sur la base de CI ; quand la sortie change, la
référence (`tests/fixtures/snapshot_reference/`) se régénère dans le même lot,
comme le prévoit `tests/snapshot_reference.py`. « En ligne » : le contrôle à
faire sur les trois sites après déploiement.

**Lot 0 — Une séance relue dans la base de CI.** Ajouter à
`tests/amorcer_base_ci.py` un relevé « en clair » retenu, et un événement non
délibératif cité par la recherche.
- Comparateur : `conseils.json` +1 séance, `conseils/*.html` +1 fichier,
  `liens.json` +1 retour, `recherche_index.json` +1 entrée. Rien d'autre.
- En ligne : sans objet.
- À décider avant : rien.

**Lot 1 — Les mots et les liens qui manquent** (défaut 6, une part du 1).
Libellés alignés ; carte « séances » sur /qui-decide ; /dossiers et les dossiers
au sitemap ; dans « Ce que la commune vient de décider », une séance relue
mène à sa feuille, les autres à leur année.
- Comparateur : **identique** — c'est la preuve que le lot ne touche que le
  site.
- En ligne : pour chaque entrée de l'en-tête, le `<title>` et le `<h1>` de la
  page d'arrivée reprennent son libellé ; `sitemap.xml` contient `/dossiers` ;
  le lien du 10 septembre sur l'accueil de Lasalle mène à la feuille.
- À décider avant : les mots (§ 6, Q2 et Q3).

**Lot 2 — Une recherche qui mène quelque part.** Adresse juste pour chaque
événement non délibératif ; dossiers et séances relues dans l'index ;
« un sujet, un nom, un montant ».
- Comparateur : `recherche_index.json` seul — entrées `acte` modifiées
  (champ `u`), entrées `dossier` et `seance` ajoutées.
- En ligne : un script parcourt `recherche_index.json` de chaque instance et
  vérifie que chaque `u` répond 200 et que son ancre existe dans la page (à
  Lasalle aujourd'hui : ≈ 1 400 échecs).
- À décider avant : Q9.

**Lot 3 — L'acheteur sous son nom** (défaut 5).
- Comparateur : `marches.json` seul — champ `acheteur_nom` modifié, champ de
  graphie source ajouté ; nombre de lignes inchangé.
- En ligne : /marches de Lasalle affiche « Acheteurs : 1 ».
- À décider avant : Q8.

**Lot 4 — Les zéros avec leur raison** (défaut 2, part de forme).
- Comparateur : `couverture.json` gagne un état par domaine ; aucun autre
  fichier.
- En ligne : la phrase « Ce n'est pas une lacune de collecte » n'apparaît plus
  sur un zéro dont la source n'a jamais rien rapporté ; sur les trois
  instances, chaque zéro de l'accueil et de /marches porte une raison.
- À décider avant : Q6.

**Lot 5 — Ce que la fiche ne sait pas** (défauts 4 et 3, part de forme).
- Comparateur : `couverture.json` (table financeurs → collecteurs) ;
  `entite/*.json` modifiés seulement si les fiches au nom proche sont retenues
  (champ ajouté sur quelques fiches).
- En ligne : la fiche de l'association de Lasalle dit « Département : non
  collecté ».
- À décider avant : Q7.

**Lot 6 — Les pages de séance** (cœur de B). Étape `seances`, route
`/conseils/[seance]`, /conseils liste tout, retours vers la page de séance.
- Comparateur : `seances.json` ajouté ; `actualite.json`, `liens.json`,
  `conseils/*.html` modifiés (champ `seance`, cible des retours, lien de
  retour) ; rien d'autre.
- En ligne : /conseils de Saillans liste ≈ 105 séances ; la page du 28 mai à
  Lasalle donne 39 et 27 et dit pourquoi ; les séances sont au sitemap ; le
  poids gzip de /conseils reste sous 10 Ko par année affichée.
- À décider avant : Q1, Q4, Q5, Q10.

**Lot 7 — L'accueil et l'en-tête de B** (défaut 1).
- Comparateur : identique si le lot 6 est passé.
- En ligne : le HTML de l'accueil ne dépasse pas les 27,7 Ko d'aujourd'hui
  (6,4 Ko gzip) ; à 360 px de large, le premier écran montre la dernière
  séance et les dossiers (capture par navigateur sans tête) ; Saillans et
  Brassac affichent une séance, pas un vide.
- À décider avant : Q11.

**Lot 8 — Les sujets.** Registre générique, `sujet` dans l'en-tête des
dossiers, liens dans les deux sens, /dossiers non vide pour une instance sans
dossier.
- Comparateur : `dossiers.json` (champ `sujet`), `sujets.json` ajouté.
- En ligne : `/environnement#eau-du-robinet` à Lasalle mène à /dossiers/eau ;
  /dossiers à Saillans liste des sujets.
- À décider avant : la liste des sujets et leurs identifiants, qui doivent être
  ceux des dossiers de Lasalle (`dechets`, `eau`, `enfance`, `incendie`,
  `logement`, `mourir`, `sante`, `telecoms`) ou les remplacer.

**Lot 9 — Les fichiers sans lecteur.** `event_links.json`,
`croisement_foncier.json`, la table d'alias de `liens.json` après son cycle,
`conseils.json` après le lot 6.
- Comparateur : fichiers retirés, aucun autre changement.
- En ligne : le nombre de fichiers du manifeste baisse d'autant ; aucune page
  n'a bougé.
- À décider avant : Q12.

---

## 6. Décisions à prendre

1. Retient-on l'architecture B (séances et dossiers comme unités, aucune URL
   retirée) ?
2. Le nom des séances, partout : « Séances du conseil » ou « Le conseil en
   clair » ?
3. Le nom des dossiers, partout : « Dossiers » ou « Dossiers thématiques » ?
4. La page d'une séance vit-elle à `/conseils/<date>_<assemblée>`, le nom de sa
   feuille actuelle ?
5. Une séance non relue a-t-elle sa page, faite des actes déjà publiés ?
6. Peut-on publier le **nombre** d'éléments extraits en attente de relecture
   (« 77 attributions lues dans les PV, non relues ») ?
7. Les fiches au nom proche sont-elles signalées sur le site public, ou
   seulement à l'atelier ?
8. L'acheteur s'affiche-t-il sous le seul nom de sa fiche, ou avec la graphie
   de la source en dessous ?
9. Un résultat de recherche BODACC, permis ou agenda mène-t-il à la source
   d'origine (oui) ou à /nouveautes (non) ?
10. Quand relevé et base comptent différemment, la page de séance montre-t-elle
    les deux nombres ?
11. « Récent » quitte-t-il l'en-tête pour l'accueil et le pied de page ?
12. Retire-t-on du snapshot les fichiers qu'aucune page ne lit
    (`event_links.json`, `croisement_foncier.json`, puis `conseils.json`) ?
