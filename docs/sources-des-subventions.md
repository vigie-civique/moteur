# D'où vient l'argent public d'une association : les sources, financeur par financeur

*Note d'instruction, 05/10/2026. Elle n'ajoute aucun collecteur. Elle dit, pour
chaque financeur d'une association des trois instances (Lasalle, Saillans,
Brassac), où se publient ses subventions, sous quelle forme, avec quelle clé
de rattachement, et ce que le site doit dire quand il ne sait pas.*

## Le cas qui l'a ouverte

Une association de Lasalle reçoit des subventions de la commune, de la
communauté de communes, du Département et du FDVA, et elle a une convention
avec la mairie. Le constat de départ disait que la base ne connaît que la
commune et la communauté de communes, lues dans les procès-verbaux. **C'est
inexact pour l'État et la Région** : le moteur a déjà trois collecteurs qui
lisent d'autres financeurs (voir § 1). En revanche, ces collecteurs ne
couvrent ni le **Département**, ni le **FDVA de l'année en cours**, ni la
**Région Auvergne-Rhône-Alpes** (Saillans). Je n'ai pas pu vérifier ce que la
base de Lasalle contient réellement pour cette association : la base d'une
instance n'est pas dans le dépôt.

## Comment lire ce document : ce qui a été vu, et comment

Cette note a été écrite en deux passes, le 05/10/2026.

**La première** depuis un environnement dont le proxy refusait par politique
(HTTP 403) toutes les sources visées — data.gouv.fr, les portails des Régions
et des Départements, les sites de l'État. Rien n'a été contourné. Seul un
moteur de recherche répondait : il rend des titres, des adresses et un résumé,
pas le document lui-même.

**La seconde** depuis un poste à accès ouvert : les interfaces de data.gouv.fr,
de `data.laregion.fr` et de `data.economie.gouv.fr` ont été interrogées, et
plusieurs pages et PDF ouverts. Deux familles de sites sont restées fermées
même ainsi : les sites académiques (`ac-montpellier.fr`, `ac-grenoble.fr`), qui
refusent tout client qui n'est pas un navigateur, et Légifrance, non tenté —
les références juridiques restent donc [su].

Chaque affirmation porte l'une de ces cinq marques :

| Marque | Ce qu'elle veut dire |
|---|---|
| **[vu]** | Ouvert et lu à la seconde passe, le 05/10/2026 : page, PDF, ou réponse d'une interface de données. |
| **[lu]** | Ouvert et lu, **dans le dépôt** : code, essais construits sur le jeu réel, messages de commit qui consignent une vérification datée. La vérification date du commit, pas d'aujourd'hui. |
| **[cité]** | Trouvé cité dans un résultat de recherche du 05/10/2026 (titre, adresse, résumé). Le document n'a pas été ouvert. |
| **[su]** | Connaissance du cadre juridique ou administratif, **non revérifiée**. À contrôler avant d'en faire une phrase publiée. |
| **[non atteint]** | Cherché, sans réponse exploitable. |

## 1. Ce que le moteur collecte déjà

| Step | Module | Financeur | Source | Clé de rattachement | Ce qu'on en sait |
|---|---|---|---|---|---|
| `cm_flux` | `collectors/cm_finances.py` | commune, intercommunalité | texte des délibérations des **deux** assemblées | nom résolu vers une fiche existante | [lu] « attribuer à X une subvention de N € » et les tableaux de subventions votées. Depuis le 08/09/2026 (commit `851e7cb`), les délibérations communautaires sont lues : 211 délibérations de la CC qui mentionnaient une subvention n'avaient jamais été lues. |
| `subv_ouvertes` | `collectors/subventions_ouvertes.py` | toute autorité qui publie au schéma `scdl/subventions` | data.gouv.fr, découverte par le schéma (53 jeux au 08/09/2026), plus l'ADEME | `idBeneficiaire` (SIRET), `rnaBeneficiaire` (RNA) | [lu] Sur Lasalle le 08/09/2026 (commit `07a776c`) : 84 584 lignes lues, **zéro** pour le territoire. Le Département du Gard publiait alors 44 jeux sur data.gouv, **aucun** sur les subventions ; la CC (5 463 hab.) était absente de data.gouv ; la commune (1 202 hab.) est exemptée. [vu, 05/10/2026] Toujours 53 jeux au schéma, et 42 jeux du Département du Gard dont aucun sur les subventions. |
| `region` | `collectors/occitanie_region.py`, déclaré par l'instance (`collecteurs_regionaux`) | Région Occitanie | `data.laregion.fr`, jeu `subventions-du-conseil-regional`, export CSV intégral | `idbeneficiaire` = SIRET, via `beneficiaires_locaux` | [lu] Sur Lasalle (commit `b389dbe`) : 54 lignes, 15 bénéficiaires, environ 2,1 M€. Il n'a de sens qu'en Occitanie : Lasalle et Brassac oui, Saillans non. [vu, 05/10/2026] `collecteurs_regionaux` déclare bien `occitanie_region` à Lasalle et à Brassac, pas à Saillans. |
| `jaune` | `collectors/jaune_associations.py` | État, tous programmes, FDVA compris | annexe « jaune » au PLF, `data.economie.gouv.fr` | SIRET, SIREN (siège local), RNA | [lu] Quatre millésimes de versements (2012, 2014, 2016, 2023) ; l'export 2022 (PLF 2024) est publié cassé et écarté. Simulation du 24/09/2026 (commit `3f09bb4`) : Lasalle 21 flux, Saillans 18, Brassac 8. Les essais sont construits sur des lignes réelles du PLF 2025, dont « Fonct et Innov FDVA » et « Formation bénév FDVA » (programme 163). [vu, catalogue de `data.economie.gouv.fr`, 05/10/2026] Le jeu du PLF 2025 (112 722 lignes) date du 23/12/2024 ; celui du PLF 2024 n'a que 111 lignes, ce qui confirme qu'il est cassé ; **aucun jeu « jaune » n'a été publié depuis** : le dernier millésime lisible reste 2023. |
| `dotations_inv` | `collectors/dotations_investissement.py` | État (DETR, DSIL, DSID, DPV, Fonds vert) | DGCL et ministère de la Transition écologique | code INSEE, SIREN de l'EPCI | [lu] Ce sont des subventions à la **collectivité**, pas aux associations. Cité pour mémoire. |
| `syndicats` | `collectors/syndicats_comptes.py` | — | balances DGFiP des syndicats | SIREN | [lu] Ces balances donnent les subventions **reçues** par financeur (État, Région, Département, Europe), agrégées. Aucun flux par bénéficiaire. |

Et ce que le site en dit déjà : `scripts/snapshot/couverture.py::FINANCEURS`
publie une fois, dans `couverture.json`, la table financeur → collecteurs
(commit `ccc1efb`, 04/10/2026). Le Département y figure **sans collecteur**.
L'État y figure avec `jaune` et `subventions`, la Région avec `region`.

**Historique** : les commits des 08/09/2026 (`d1ed44f` « Fusion : les
subventions des autres collectivités entrent dans le moteur », `07a776c`,
`b389dbe`, `de2f28d`) et du 24/09/2026 (`3f09bb4`) sont le travail antérieur
sur les subventions des autres collectivités. Le dépôt n'en contient pas
d'autre, ni sur le Département, ni sur l'Europe.

## 2. Le cadre commun

### L'obligation de publication

- **Article 10 de la loi n° 2000-321 et décret n° 2017-779 du 5 mai 2017.**
  Toute autorité administrative qui attribue une subvention de plus de
  23 000 € (seuil de la convention obligatoire) en publie les données
  essentielles sous forme électronique, pour les conventions signées à
  compter du 1er août 2017. [cité] : résumé des jeux « Données essentielles
  des conventions de subvention » sur data.gouv.fr. [lu] : en-tête de
  `subventions_ouvertes.py`, qui ajoute l'exemption des collectivités de moins
  de 3 500 habitants et un délai de trois mois.
  - **Conséquence pour nos trois communes** : l'obligation ne porte que sur
    les conventions de **plus de 23 000 €**. Une petite association en reçoit
    rarement autant. Même un Département ou une Région parfaitement en règle
    ne publie donc **rien** sur la plupart des subventions qui nous
    intéressent. Ce n'est pas une lacune de la source : c'est son périmètre.
  - Format : schéma `scdl/subventions` d'OpenDataFrance, publié sur
    `schema.data.gouv.fr` [cité ; non atteint].
- **Annexes budgétaires des collectivités** [su] : le compte administratif (et
  le budget) d'une commune de 3 500 habitants ou plus, d'un Département ou
  d'une Région porte en annexe la liste des concours attribués aux tiers, en
  nature ou en subventions (CGCT, articles L. 2313-1, L. 3313-1, L. 4313-2, et
  les maquettes M57). Ces documents sont publics. Ils sont publiés en PDF, et
  parfois mis en ligne au format des « budgets » du SCDL. **C'est la seule
  source qui couvre les petites subventions départementales**, sans seuil.
  Elle est à vérifier pour chacun des trois Départements.
- **Délibérations** [su] : toute subvention d'une collectivité est votée par
  son assemblée ou sa commission permanente. La délibération est un acte
  publié et communicable (CRPA, art. L. 311-1). Une fois publiée, elle est
  librement réutilisable (CRPA, art. L. 321-1 et suivants), sauf les droits de
  tiers. Elle est publiée en ligne sur le site de la collectivité, au plus
  tard depuis la réforme de la publicité des actes de 2022 (ordonnance
  n° 2021-1310 ; décret n° 2021-1311). C'est la source « PDF de délibération »
  de chaque financeur local.
- **Licence** : les jeux publiés sur data.gouv.fr ou un portail public le sont
  en très grande majorité sous **Licence Ouverte 2.0**. C'est [cité] pour le
  jeu de la Région Occitanie, et [su] pour les autres : chaque jeu déclare la
  sienne, à relire au moment d'écrire le collecteur.

### Les jeux « subventions » de data.gouv.fr

- [lu] Découverte par le schéma : 53 jeux déclaraient `scdl/subventions` au
  08/09/2026. Aucun ne concernait le territoire de Lasalle. Saillans et
  Brassac n'ont pas été mesurés dans ce commit.
- [cité] Le moteur de recherche rend des jeux de collectivités qui publient
  sans déclarer le schéma : CC du Frontonnais, Estérel Côte d'Azur, Grenoble-
  Alpes Métropole, Martigues, communes de Montpellier Méditerranée Métropole.
  Aucun ne concerne nos territoires.
- [vu, 05/10/2026] Le schéma compte toujours **53 jeux**. Aucun n'est publié
  par le Gard, la Drôme, le Tarn, la Région Occitanie ou la Région
  Auvergne-Rhône-Alpes.
- [cité] « PLF - Jaune - Associations subventionnées » existe aussi sur
  data.gouv.fr, à côté de `data.economie.gouv.fr`.

### Data.Subvention et Le Compte Asso : ce qui est réservé aux agents

- **Data.Subvention** (`datasubvention.beta.gouv.fr`, application
  `app.datasubvention.beta.gouv.fr`) [cité] rassemble, par association, les
  demandes et les subventions accordées par plusieurs administrations de
  l'État et des opérateurs, avec une API interministérielle. **L'accès est
  réservé aux agents publics**, sur compte : agents de l'État, de la fonction
  publique territoriale et des opérateurs. **Non exploitable** par un site
  citoyen. Une collectivité partenaire pourrait y lire ce que le site ne voit
  pas, mais elle ne pourrait pas le republier sans une base légale de
  diffusion propre à chaque ligne.
- [vu, fiche « API Data.Subvention » de data.gouv.fr, 05/10/2026] L'accès est
  **restreint** : agents de l'État, de la fonction publique territoriale et
  des opérateurs, sur demande. Producteur : la DINUM. Rien n'a changé.
- **Le Compte Asso** (`lecompteasso.associations.gouv.fr`) [cité] est le
  guichet où l'association **dépose** sa demande (FDVA notamment) et reçoit
  son résultat. Le résultat individuel est notifié dans le dossier de
  l'association. Ce n'est pas une source publique.

## 3. Financeur par financeur

### 3.1 État — FDVA (volets 1 « formation des bénévoles » et 2 « fonctionnement-innovation »)

- **Qui instruit** [cité] : en Occitanie, la DRAJES de la région académique
  (rectorat), avec les services départementaux (SDJES) des DSDEN. La campagne
  est annoncée par une note d'orientation régionale et départementale, par
  exemple la [note départementale d'orientation du Gard, FDVA 2 2023-2024](https://www.gard.gouv.fr/contenu/telechargement/56266/422199/file/Note%20departementale%20d'orientation%20GARD%20FDVA%202%20-%202023%202024.pdf)
  ou la [note FDVA 2 du Tarn](https://foottarn.fff.fr/wp-content/uploads/sites/72/2025/01/note-d-orientation-fdva-2-tarn-38807.pdf).
  Dépôt sur Le Compte Asso ; campagne 2026 dans le Gard du 6 janvier au
  3 mars 2026 [cité].
- **Où sont publiées les listes de bénéficiaires** [cité] : sur le site de
  l'**académie**, après les collèges départementaux et la commission
  consultative régionale. Pour l'Occitanie-Est (Gard) : `ac-montpellier.fr`,
  page « FDVA 2 … les résultats de la campagne » ; résultats 2025 publiés après
  la commission du 24/06/2025. Exemple d'une autre académie : [résultats FDVA 1
  et 2, campagne 2025, Paris](https://www.ac-paris.fr/resultats-fdva-1-2-campagne-2025-132839).
  [su] Le Tarn (Brassac) relève de l'académie de Toulouse, dans la même région
  académique Occitanie, et la Drôme (Saillans) de l'académie de Grenoble,
  région académique Auvergne-Rhône-Alpes. La première passe en concluait qu'il
  fallait suivre trois pages ; la seconde montre qu'il y en a deux (voir
  « Seconde passe », plus bas).
  - **Format** [non atteint] : listes en page web ou en PDF, a priori par
    département et par volet.
  - **Granularité** [su] : nom de l'association, montant, volet, département.
    **SIRET et RNA : inconnus**, probablement absents.
  - **Profondeur et délai** : publication au début de l'été pour l'année en
    cours [cité, 2025]. Profondeur historique inconnue.
  - **Licence** : information publique publiée par une administration,
    réutilisable selon le CRPA [su]. Aucune licence déclarée connue.
- **Le jaune les contient-il ?** [lu] Oui. Les lignes FDVA y figurent sous le
  programme 163, avec un SIRET (objets « Fonct et Innov FDVA », « Formation
  bénév FDVA » dans les essais construits sur le PLF 2025), et le collecteur
  `jaune` les relève déjà. **Avec quel retard** [lu + cité] : le jaune annexé
  au PLF de l'année N+1, déposé en octobre N, porte les versements de
  l'année N-1. Le collecteur lit « 2023 » dans le PLF 2025. Une subvention FDVA
  versée en 2026 apparaîtra donc au PLF 2028, à l'automne 2027 : **12 à
  24 mois de retard**. Et le jeu 2022 (PLF 2024) est cassé.
- **Clé** : SIRET dans le jaune [lu] ; nom seul dans les listes académiques
  (probable).

- **Seconde passe (05/10/2026)** :
  - **Deux foyers, pas trois** [cité] : les notes d'orientation du Gard *et*
    du Tarn renvoient à la même page de l'académie de Montpellier, tenue par la
    DRAJES pour toute l'Occitanie
    (`ac-montpellier.fr/fdva-2-fonctionnement-global-et-nouveaux-services-mode-d-emploi-en-region-occitanie-122636`) ;
    résultats 2026 annoncés « à partir du 19 juin ». Pour Auvergne-Rhône-Alpes,
    les résultats sont des PDF déposés sur `ac-grenoble.fr` et `ac-lyon.fr`.
  - **Ordre de grandeur, Drôme 2025** [cité] : enveloppe de 484 226 €,
    305 demandes, 183 associations financées, de 1 000 à 7 500 € chacune.
  - **Ces sites refusent les robots** [vu] : `ac-montpellier.fr` et
    `ac-grenoble.fr` répondent 403 à tout client qui n'est pas un navigateur,
    depuis un poste à accès ouvert comme depuis l'environnement d'origine. Le
    format des listes et la présence d'un SIRET restent donc [non atteint], et
    un collecteur automatique y serait refusé de la même façon : prévoir un
    **dépôt manuel** du fichier.
  - La note du Tarn citée plus haut est une copie relayée par un district
    sportif, faute de l'avoir trouvée sur un site de l'État : à remplacer par
    l'original.


### 3.2 État — DRAC et autres subventions de l'État aux associations

- **Le jaune couvre tous les programmes** [lu] : culture comprise, avec un
  identifiant. [su] Les crédits culturels déconcentrés passent par les
  programmes 131 (création), 175 (patrimoines) et 361 (transmission des
  savoirs et démocratisation de la culture, où vit l'EAC). Une subvention de la
  DRAC à une association du territoire est donc **déjà relevée** par `jaune`,
  avec le même retard.
- **Publications propres de la DRAC Occitanie** [cité] : des listes
  ponctuelles, comme la [liste des bénéficiaires](https://www.culture.gouv.fr/Media/medias-creation-rapide/Liste-des-beneficiaires)
  du plan de relance du spectacle vivant (juin 2021), et des pages par
  domaine. Pas de jeu de données régulier trouvé [non atteint]. Les demandes
  passent par `demarche.numerique.gouv.fr` (exemple : Passeurs d'images
  Occitanie 2027) [cité].
- **Data.Subvention** couvrirait les subventions de l'État mieux que le jaune,
  mais il est fermé (§ 2).
- **Clé** : SIRET dans le jaune.

### 3.3 Région

**Occitanie (Lasalle, Brassac)**
- **Source** : `data.laregion.fr`, jeu `subventions-du-conseil-regional`, aussi
  référencé sur data.gouv.fr. [cité] Subventions **votées en commission
  permanente depuis 2018**, pour les bénéficiaires dont le cumul annuel atteint
  **23 000 €**. CSV (≈ 12 Mo) et JSON. **Licence Ouverte 2.0**. Mis à jour le
  29/05/2026. [lu] Il porte `idbeneficiaire` (SIRET), et le collecteur prend
  l'export intégral.
- **Seconde passe** [vu, interface du portail, 05/10/2026] : 64 541 lignes ;
  décisions du 02/02/2018 au 16/12/2025 ; plus petit cumul annuel par
  bénéficiaire : 23 000 € exactement ; Licence Ouverte v2.0 ; dernière
  modification le 29/05/2026. Champs : `nomattribuant`, `idattribuant`,
  `nombeneficiaire`, `idbeneficiaire`, `objet`, `date_de_decision`,
  `referencedecision`, `montant_vote`, `mt_vote_pour_le_tiers_sur_l_annee`,
  `annee_decision`. Les décisions de 2026 n'y sont pas encore : **cinq à
  dix-sept mois de retard** selon la date du vote.
- **Limite décisive** : le seuil de 23 000 € cumulés exclut l'essentiel des
  petites associations. L'association de Lasalle n'y figure probablement pas,
  à vérifier en base.
- **Délibérations de commission permanente** [su] : publiées par la Région,
  sans seuil. Ce serait la seule voie pour les petites aides régionales. Forme
  et adresse non atteintes.
- **Fonds européens** : la Région est autorité de gestion (§ 3.6).

**Auvergne-Rhône-Alpes (Saillans)**
- **Aucun jeu régional de subventions trouvé** [vu, 05/10/2026] : la Région
  n'a aucun jeu parmi les 53 du schéma `scdl/subventions` ; aucun titre de
  « subvention », d'« aide », de « délibération » ou de « budget » parmi les
  300 premiers jeux de son organisation sur data.gouv.fr ; les recherches n'y
  rendent que les tableaux de l'Établissement français du sang, sans rapport.
  Son portail `data.auvergnerhonealpes.fr` ne répond pas à l'interface de
  catalogue qu'expose celui de l'Occitanie : il reste à ouvrir à la main.
- Les délibérations de commission permanente sont en PDF sur
  `edelib.auvergnerhonealpes.fr` [cité].
- **Conséquence** : `subv_ouvertes` ne peut rien remonter de la Région pour
  Saillans, puisqu'il découvre par le schéma. Le zéro régional de Saillans
  est une absence de source, pas un fait.

### 3.4 Département

| | Gard (Lasalle) | Drôme (Saillans) | Tarn (Brassac) |
|---|---|---|---|
| Jeu de subventions ouvert | **aucun** : 42 jeux du Département sur data.gouv.fr au 05/10/2026, aucun sur les subventions [vu] (44 et aucun au 08/09/2026 [lu, commit `07a776c`]) | aucun au schéma `scdl/subventions` [vu] | aucun au schéma [vu] ; les recherches renvoient au Tarn-et-Garonne, autre département |
| Tableau annuel des concours aux associations | non trouvé [non atteint] | **en ligne pour 2020 et 2021** [vu] : « Tableau des subventions, prêts, prestations en nature accordés par le Département aux associations en 2021 », 20 pages, PDF de texte | non trouvé [non atteint] |
| Délibérations | [vu, page du Département] deux portails : `deliberations.gard.fr` jusqu'au 31/03/2024, `cg30.kiosk.qualigraf.fr` depuis ; assemblée et commission permanente | page « Délibérations » et recueil mensuel des actes en PDF sur `ladrome.fr` [vu] | [vu, page du Département] `actes.tarn.fr` avant le 01/01/2024, `cd-tarn.kiosk.qualigraf.fr` depuis ; recueil des actes à part |
| Clé de rattachement | RNA et SIRET exigés à la demande [cité] ; dans les délibérations, inconnue (nom probable) | **SIRET** dans le tableau annuel [vu] ; nom seul dans les arrêtés [vu] | inconnue (nom probable) |

- **Le tableau annuel de la Drôme** [vu] est la pièce que la première version
  de cette note supposait : le relevé des concours attribués aux associations
  (CGCT, art. L. 3313-1 [su]). Colonnes : nom de l'association, objet (avec la
  référence du dossier), **SIRET**, montant, prêt, montant garanti, prestations
  en nature. **Sans seuil** : des lignes de 150 € y figurent. Deux millésimes
  sont liés depuis la page du recueil des actes
  ([2021](https://www.ladrome.fr/wp-content/uploads/2022/04/2021-subventions.pdf),
  [2020](https://www.ladrome.fr/wp-content/uploads/2021/04/com-subventions-2020.pdf)) ;
  aucun plus récent n'y était lié le 05/10/2026. Le 2021 a été mis en ligne en
  avril 2022 : **délai d'environ quatre mois** après la fin de l'exercice.
- **Les arrêtés drômois de 2020 ne sont pas une source régulière** [vu,
  [arrêté n° 20_DPT_01](https://www.ladrome.fr/wp-content/uploads/2020/05/20-dpt-01signtamponn.pdf)].
  Ils visent l'ordonnance n° 2020-391, qui permettait pendant la crise
  sanitaire au président d'attribuer les subventions à la place de
  l'assemblée. Colonnes de leur annexe : politique, service instructeur, type
  d'aide, nom du bénéficiaire, objet, montant, fonctionnement ou
  investissement — **ni SIRET ni commune**. Hors de cette période, les
  subventions se lisent dans les délibérations.
- **Gard et Tarn partagent un logiciel** [vu] : leurs deux kiosques servent la
  même application (mêmes fichiers, mêmes routes publiques). C'est une
  application qui se charge par script : la page ne contient aucun acte, et
  la forme de ce qu'elle interroge n'a pas été explorée. Un connecteur écrit
  pour l'un vaut pour l'autre, **s'il peut lire le kiosque sans navigateur**.
- **Format** : PDF. Pas d'API documentée.
- **Granularité des délibérations** [su] : bénéficiaire nommé, montant, objet,
  date de la commission. SIRET et RNA rarement présents.
- **Profondeur** : Drôme, tableaux 2020 et 2021 [vu] ; Gard et Tarn, celle de
  leurs deux portails successifs, non mesurée.
- **Caractère public** : actes administratifs publiés, réutilisables selon le
  CRPA [su].
- **Obligation SCDL** : les trois Départements y sont soumis pour les
  conventions de plus de 23 000 € [su]. Aucun ne s'y conforme sur data.gouv.fr :
  le schéma y compte 53 jeux le 05/10/2026, aucun d'eux [vu].
### 3.5 Intercommunalité, et la CGEAC de la CC Causses Aigoual Cévennes Terres Solidaires

- **Subventions votées en conseil communautaire** : déjà lues par `cm_flux`
  [lu]. La CC (5 463 hab.) est soumise au décret 2017-779 au-delà de
  23 000 € [su], mais elle était absente de data.gouv au 08/09/2026 [lu].
- **La CGEAC** (convention territoriale de généralisation de l'éducation
  artistique et culturelle) :
  - **Qui la signe** : la CC et la **DRAC Occitanie** [cité]. Le résultat de
    recherche indique que la CC « a lancé un appel à candidatures pour une
    résidence-mission » dans le cadre d'une convention signée avec la DRAC :
    12 semaines, en deux périodes (14/09–23/10 et 09/11–19/12/2026), sur le
    thème « Les patrimoines », arts visuels ou spectacle vivant [cité]. [su]
    Les CGEAC associent en général l'Éducation nationale (DSDEN ou rectorat),
    parfois le Département et la Région. **Les signataires effectifs de celle-ci
    ne sont pas établis.**
  - **Où sont publiés ses financements et ses bénéficiaires** :
    1. la **délibération communautaire** qui approuve la convention et son plan
       de financement — déjà dans les actes collectés si elle a été publiée
       [su : à chercher dans la base de Lasalle, par exemple « éducation
       artistique » dans les actes de la CC] ;
    2. l'**appel à candidatures** de la résidence-mission, publié par la DRAC
       et la CC (montant de la rémunération de l'artiste) [cité, non ouvert] ;
    3. les crédits de la DRAC versés à une **association** porteuse figurent
       dans le jaune, programme 361 [su], avec 12 à 24 mois de retard ;
    4. un **bilan** : d'autres territoires publient le leur. Exemple [vu] :
       [Sète agglopôle méditerranée, bilan 2021-2025 de son service EAC](https://www.agglopole.fr/wp-content/uploads/2026/07/Bilan-2021-2025-du-Service-education-artistique-et-culturelle.pdf)
       (Hérault — et non Alès Agglomération, comme l'écrivait la première
       version de cette note). Il nomme ses signataires — l'État par la DRAC
       Occitanie, le ministère délégué à la Ville par la DDETS, l'Éducation
       nationale — et la part de l'agglomération année par année (6 000 € en
       2023, 8 000 € en 2024, 20 000 € en 2025). C'est la forme de document à
       demander à la CC. Aucun bilan n'a été trouvé pour elle.
  - **Ce que dit l'appel à candidatures** [vu, page du ministère de la
    Culture] : « Résidence de territoire "Patrimoines Aigoual et vallées
    cévenoles" », candidatures jusqu'au 8 juillet 2026, deux périodes de six
    semaines. Il ne nomme **aucun autre signataire** que la DRAC, et ne donne
    **ni la rémunération ni le plan de financement**. Les candidatures sont
    reçues par une structure du territoire : c'est probablement elle, et non
    l'artiste, qui porte le financement — à lire dans la délibération.
  - **Publics et réutilisables ?** La convention et la délibération sont des
    documents administratifs communicables (CRPA L. 311-1). Une fois publiées,
    elles sont réutilisables (L. 321-1) [su]. Les noms des artistes retenus sont
    ceux de **personnes physiques bénéficiaires d'un financement public** : la
    règle du projet admet de les nommer au titre de la subvention reçue,
    seulement dans ce cadre. Aucun de ces documents n'a pu être ouvert d'ici.

### 3.6 Autres financeurs, une ligne chacun

| Financeur | Source ouverte ? |
|---|---|
| **CAF** (Gard, Drôme, Tarn) | **Non.** Les règlements d'aide aux partenaires sont publiés, la liste des subventions versées ne l'est pas ; `monenfant.fr` liste les structures conventionnées, sans montants [cité]. Soumise au décret 2017-779 au-delà de 23 000 € [su], sans jeu trouvé. |
| **LEADER** (FEADER, via les GAL) | **Avec réserve.** La Région Occitanie, autorité de gestion, a sélectionné 38 GAL [cité]. [su] Les règlements européens imposent de publier la liste des opérations et des bénéficiaires, au plus tard chaque trimestre ou tous les quatre mois, avec nom, montant et objet. Forme : un fichier régional, à localiser. Clé : le nom, parfois le SIRET. [vu] La rubrique « Open Data » de `europe-en-occitanie.eu` renvoie à `data.laregion.fr`, où une recherche « feder », « feader », « leader », « fonds européens » ne rend **aucun** jeu de bénéficiaires (05/10/2026). |
| **FEDER / FSE+** | **Avec réserve.** Même obligation de liste des opérations [su] ; des listes de bénéficiaires FEDER (Midi-Pyrénées) existent sur data.gouv.fr (étiquettes `feder`, `fse`) [cité]. Bénéficiaires rarement associatifs à cette échelle. [vu] Même constat que pour LEADER : rien sur `data.laregion.fr`. [su] Le portail européen Kohesio recense les opérations FEDER et FSE+ par bénéficiaire ; non exploré. |
| **ANCT** | **Oui, partiellement.** Jeu « Fabriques de territoire » sur data.gouv.fr (tiers-lieux labellisés et subventionnés) [cité]. Les autres dispositifs (France services, Petites villes de demain) ne sont pas connus sous forme de liste de subventions. [vu] Le jeu existe sur data.gouv.fr (ANCT, modifié le 24/09/2025). |
| **Agence de l'eau** | **Non, au niveau du bénéficiaire.** Rhône Méditerranée Corse (Gard, Drôme) publie des communiqués trimestriels agrégés par territoire [cité]. Brassac relève d'**Adour-Garonne** [su], non instruite. Bénéficiaires associatifs rares (rivières, pêche). |
| **Fondations reconnues d'utilité publique** | **Non.** Elles publient leurs comptes annuels au JOAFE (au-delà de 153 000 € de dons) [cité], pas la liste des subventions qu'elles versent. Ce ne sont pas des fonds publics au sens du projet. |

## 4. Synthèse

| Financeur | Source | Exploitable maintenant | Avec réserve | Non |
|---|---|:-:|:-:|:-:|
| Commune | délibérations (`cm_flux`) | ✔ (déjà) | | |
| Intercommunalité | délibérations (`cm_flux`) | ✔ (déjà) | | |
| Intercommunalité, CGEAC | délibération + appel à candidatures + jaune | | ✔ PDF, signataires à établir | |
| État, tous programmes (DRAC comprise) | jaune budgétaire (`jaune`) | ✔ (déjà) | retard de 12 à 24 mois, millésime 2022 cassé | |
| État, FDVA de l'année | listes des académies | | ✔ PDF ou page web, nom seul, deux foyers ; sites fermés aux robots [vu] | |
| État, détail par dossier | Data.Subvention | | | ✘ réservé aux agents |
| Région Occitanie | `data.laregion.fr` (`region`) | ✔ (déjà, ≥ 23 000 €) | | |
| Région Occitanie, petites aides | délibérations de commission permanente | | ✔ PDF, à localiser | |
| Région Auvergne-Rhône-Alpes | délibérations de CP (`edelib`) ; aucun jeu trouvé [vu] | | ✔ à instruire | |
| Département du Gard | délibérations sur kiosque Qualigraf (depuis le 31/03/2024) et `deliberations.gard.fr` (avant) ; annexe du CA non trouvée | | ✔ PDF, nom seul | ✘ aucun jeu ouvert [vu] |
| Département de la Drôme | **tableau annuel des subventions aux associations, avec SIRET** (2020, 2021) | ✔ (PDF de texte, sans seuil) | années suivantes à localiser | |
| Département du Tarn | délibérations sur kiosque Qualigraf (depuis le 01/01/2024) et `actes.tarn.fr` (avant) ; annexe du CA non trouvée | | ✔ PDF, nom seul | ✘ aucun jeu trouvé |
| Toute autorité ≥ 23 000 € | SCDL sur data.gouv (`subv_ouvertes`) | ✔ (déjà) | | |
| LEADER, FEDER | listes d'opérations de l'autorité de gestion | | ✔ à localiser : aucun jeu sur `data.laregion.fr` [vu] | |
| ANCT | Fabriques de territoire | ✔ (jeu cité) | | |
| CAF | — | | | ✘ |
| Agence de l'eau | — | | | ✘ au niveau du bénéficiaire |
| Fondations RUP | — | | | ✘ |

## 5. Dans quel ordre écrire les collecteurs

Du meilleur rapport couverture/effort au pire :

0. **Avant d'écrire quoi que ce soit** : vérifier que `region` est déclaré
   dans `config/instance.json` de Lasalle et de Brassac, et mesurer, base par
   base, ce que `jaune`, `region` et `subv_ouvertes` rendent pour les
   associations de chaque commune. Effort : une heure. C'est peut-être là
   qu'est l'écart avec le constat de départ.
1. **Le Département, par le tableau annuel des concours attribués aux
   associations.** Une seule pièce par an et par Département, sans seuil, avec
   tous les bénéficiaires. **La Drôme d'abord** : son tableau de 2021 est en
   ligne, en PDF de texte, **avec le SIRET** [vu, § 3.4] — c'est la seule
   source départementale qui se rattache sans passer par le nom. Reste à
   trouver les années suivantes, et la même pièce pour le Gard et le Tarn.
2. **Les délibérations du Gard et du Tarn, par leur kiosque commun.** Les deux
   Départements publient leurs actes sur le même logiciel (`kiosk.qualigraf.fr`,
   § 3.4) : un seul connecteur pour deux instances, à condition que le kiosque
   se laisse lire sans navigateur — à instruire avant d'écrire. Le nom seul,
   donc une relecture à l'atelier.
3. **Les listes FDVA des académies** : elles donnent l'année en cours, quand le
   jaune n'arrive qu'un à deux ans après. Il y a **deux** foyers et non trois
   (une page pour toute l'Occitanie, des PDF pour Auvergne-Rhône-Alpes), le nom
   seul, et les sites académiques **refusent tout client qui n'est pas un
   navigateur** (§ 3.1) : à n'écrire qu'avec un dépôt manuel du fichier et une
   relecture à l'atelier, sur le modèle de `collectors/marches_extraits.py`.
4. **La Région Auvergne-Rhône-Alpes** : aucun jeu trouvé à la seconde passe
   (§ 3.3). Ouvrir à la main son portail et `edelib` avant de décider ; un
   collecteur régional déclaré, comme `occitanie_region`, seulement s'il
   existe un jeu.
5. **Les listes d'opérations LEADER et FEDER** de chaque autorité de gestion.
   Les montants sont importants mais les bénéficiaires associatifs sont rares.
6. **Les délibérations de commission permanente des Régions**, pour les aides
   sous 23 000 € : beaucoup de PDF pour peu de lignes par commune.

Pas de collecteur pour la CAF, les agences de l'eau, les fondations ni
Data.Subvention : il n'y a pas de source ouverte au niveau du bénéficiaire.

## 6. Ce que le site doit dire quand il ne sait pas

Une phrase par source non exploitable, à afficher dans le bloc « Ce que cette
fiche peut dire » (`couverture.financeurs`). Les crochets sont remplis depuis
l'instance, jamais écrits en dur.

- **Département, sans collecteur** : « Le Département [du Gard] ne publie pas
  ses subventions dans un format que ce site sait lire. L'absence d'une aide
  départementale sur cette fiche ne veut pas dire que [l'association] n'en
  reçoit pas. »
- **Région, au-dessous du seuil** : « La Région ne publie en données ouvertes
  que ses aides de 23 000 € et plus par an et par bénéficiaire. Une aide plus
  petite n'apparaît pas ici. »
- **Région Auvergne-Rhône-Alpes** : « Les subventions de la Région
  Auvergne-Rhône-Alpes ne sont pas encore relevées par ce site. »
- **FDVA de l'année** : « Les aides du FDVA n'apparaissent ici qu'avec l'annexe
  budgétaire de l'État, publiée un à deux ans après leur versement : les plus
  récentes manquent. »
- **État, en général** : « Les subventions de l'État sont relevées dans
  l'annexe au projet de loi de finances, publiée avec un à deux ans de retard.
  Le détail par dossier, tenu par l'administration (Data.Subvention), est
  réservé aux agents publics. »
- **CAF** : « La Caisse d'allocations familiales ne publie pas la liste des
  subventions qu'elle verse. Ce site ne peut pas dire si [l'association] en
  reçoit. »
- **Fonds européens** : « Les aides européennes (LEADER, FEDER) ne sont pas
  encore relevées par ce site. »
- **Agence de l'eau** : « L'agence de l'eau ne publie ses aides que par
  totaux, sans liste des bénéficiaires. »
- **Fondations** : « Les fondations privées, même reconnues d'utilité
  publique, ne publient pas les subventions qu'elles versent. »

## 7. Décisions à prendre

1. Faut-il commencer par mesurer, sur les trois bases, ce que `jaune`, `region`
   et `subv_ouvertes` rendent déjà, avant tout nouveau collecteur ? (oui / non)
2. Pour le Département, faut-il commencer par l'annexe du compte administratif
   plutôt que par les délibérations ? (annexe / délibérations)
3. Une source qui ne donne que le **nom** du bénéficiaire (listes FDVA,
   arrêtés départementaux) doit-elle passer par une relecture à l'atelier,
   ligne par ligne, avant publication ? (oui / non)
4. Faut-il un collecteur FDVA propre alors que le jaune relève déjà le FDVA,
   avec retard ? (oui / non, le retard est dit sur la fiche)
5. Les noms d'artistes, personnes physiques, rémunérés au titre d'une
   résidence-mission CGEAC sont-ils publiés au titre de la « subvention
   reçue » ? (oui / non, seulement la structure porteuse)
6. Le bloc « Ce que cette fiche peut dire » doit-il afficher les phrases du § 6
   pour **chaque** financeur non relevé, ou seulement pour ceux qui
   financent habituellement ce type d'acteur ? (tous / pertinents seulement)
7. Faut-il demander l'ouverture des données à chaque Département (lettre
   CADA ou demande de publication au schéma SCDL), en parallèle des
   collecteurs ? (oui / non)
8. Un accès Data.Subvention par une collectivité partenaire, pour contrôler le
   site **sans** republier, est-il envisagé ? (oui / non)
