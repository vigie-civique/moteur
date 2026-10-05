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

L'accès réseau de cet environnement est restreint. Le proxy de sortie **refuse
par politique** (HTTP 403 au CONNECT) toutes les sources visées, aussi bien
depuis `curl` que depuis l'outil de lecture de pages. Domaines essayés le
05/10/2026 et refusés : `www.data.gouv.fr`, `data.economie.gouv.fr`,
`data.laregion.fr`, `data.auvergnerhonealpes.fr`, `www.associations.gouv.fr`,
`datasubvention.beta.gouv.fr`, `lecompteasso.associations.gouv.fr`,
`www.gard.fr`, `www.ladrome.fr`, `www.tarn.fr`, `opendata.tarn.fr`,
`data.ladrome.fr`, `www.culture.gouv.fr`, `www.caf.fr`,
`www.europe-en-france.gouv.fr`, `www.legifrance.gouv.fr`,
`schema.data.gouv.fr`, `www.caussesaigoual-cevennes.fr`,
`www.agence-cohesion-territoires.gouv.fr`, `www.eaurmc.fr`,
`www.economie.gouv.fr`, `www.budget.gouv.fr`, `ville-de-sauve.fr`. Rien n'a été
contourné. Seul un moteur de recherche répondait : il rend des titres, des
adresses et un résumé, pas le document lui-même.

Chaque affirmation porte donc l'une de ces quatre marques :

| Marque | Ce qu'elle veut dire |
|---|---|
| **[lu]** | Ouvert et lu, **dans le dépôt** : code, essais construits sur le jeu réel, messages de commit qui consignent une vérification datée. La vérification date du commit, pas d'aujourd'hui. |
| **[cité]** | Trouvé cité dans un résultat de recherche du 05/10/2026 (titre, adresse, résumé). Le document n'a pas été ouvert. |
| **[su]** | Connaissance du cadre juridique ou administratif, **non revérifiée** depuis cet environnement. À contrôler avant d'en faire une phrase publiée. |
| **[non atteint]** | Cherché, sans réponse exploitable. |

## 1. Ce que le moteur collecte déjà

| Step | Module | Financeur | Source | Clé de rattachement | Ce qu'on en sait |
|---|---|---|---|---|---|
| `cm_flux` | `collectors/cm_finances.py` | commune, intercommunalité | texte des délibérations des **deux** assemblées | nom résolu vers une fiche existante | [lu] « attribuer à X une subvention de N € » et les tableaux de subventions votées. Depuis le 08/09/2026 (commit `851e7cb`), les délibérations communautaires sont lues : 211 délibérations de la CC qui mentionnaient une subvention n'avaient jamais été lues. |
| `subv_ouvertes` | `collectors/subventions_ouvertes.py` | toute autorité qui publie au schéma `scdl/subventions` | data.gouv.fr, découverte par le schéma (53 jeux au 08/09/2026), plus l'ADEME | `idBeneficiaire` (SIRET), `rnaBeneficiaire` (RNA) | [lu] Sur Lasalle le 08/09/2026 (commit `07a776c`) : 84 584 lignes lues, **zéro** pour le territoire. Le Département du Gard publiait alors 44 jeux sur data.gouv, **aucun** sur les subventions ; la CC (5 463 hab.) était absente de data.gouv ; la commune (1 202 hab.) est exemptée. |
| `region` | `collectors/occitanie_region.py`, déclaré par l'instance (`collecteurs_regionaux`) | Région Occitanie | `data.laregion.fr`, jeu `subventions-du-conseil-regional`, export CSV intégral | `idbeneficiaire` = SIRET, via `beneficiaires_locaux` | [lu] Sur Lasalle (commit `b389dbe`) : 54 lignes, 15 bénéficiaires, environ 2,1 M€. Il n'a de sens qu'en Occitanie : Lasalle et Brassac oui, Saillans non. |
| `jaune` | `collectors/jaune_associations.py` | État, tous programmes, FDVA compris | annexe « jaune » au PLF, `data.economie.gouv.fr` | SIRET, SIREN (siège local), RNA | [lu] Quatre millésimes de versements (2012, 2014, 2016, 2023) ; l'export 2022 (PLF 2024) est publié cassé et écarté. Simulation du 24/09/2026 (commit `3f09bb4`) : Lasalle 21 flux, Saillans 18, Brassac 8. Les essais sont construits sur des lignes réelles du PLF 2025, dont « Fonct et Innov FDVA » et « Formation bénév FDVA » (programme 163). |
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
  région académique Auvergne-Rhône-Alpes. Il faut donc **trois pages** à
  suivre, une par académie ou par région académique, et leur forme n'est pas
  connue d'ici.
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
- **Limite décisive** : le seuil de 23 000 € cumulés exclut l'essentiel des
  petites associations. L'association de Lasalle n'y figure probablement pas,
  à vérifier en base.
- **Délibérations de commission permanente** [su] : publiées par la Région,
  sans seuil. Ce serait la seule voie pour les petites aides régionales. Forme
  et adresse non atteintes.
- **Fonds européens** : la Région est autorité de gestion (§ 3.6).

**Auvergne-Rhône-Alpes (Saillans)**
- [non atteint] Aucun jeu régional de subventions n'a été trouvé.
  `data.auvergnerhonealpes.fr` est refusé par le proxy. Les résultats de
  recherche ne rendent que des délibérations de commission permanente en PDF,
  sur `edelib.auvergnerhonealpes.fr` [cité], et un jeu de l'ETS AURA (don du
  sang) sans rapport.
- **À vérifier avant tout collecteur** : la Région publie-t-elle ses
  conventions au-delà de 23 000 € (SCDL ou autre) ? Si c'est au schéma
  déclaré, `subv_ouvertes` les verrait déjà, et aucune ligne n'est remontée
  pour Saillans [su : à mesurer sur la base de Saillans].

### 3.4 Département

| | Gard (Lasalle) | Drôme (Saillans) | Tarn (Brassac) |
|---|---|---|---|
| Jeu de subventions ouvert | **aucun** sur data.gouv au 08/09/2026 [lu, commit `07a776c`] ; aucun trouvé [cité] | aucun trouvé [non atteint] | aucun trouvé [non atteint] ; les résultats renvoient au Tarn-et-Garonne, autre département |
| Délibérations / arrêtés | portail de dépôt « Subventions Gard » depuis 2024, à partir de 500 € (ou 1 000 € selon la source) [cité, source secondaire] ; délibérations de commission permanente non trouvées en ligne [non atteint] | **arrêtés d'attribution signés, en PDF**, sur `ladrome.fr`, avec des listes d'associations : en 2020, un arrêté pour 2 313 517,61 € et un autre pour 612 880,67 € [cité] | non trouvés [non atteint] |
| Annexe « concours attribués » du CA | [su] obligatoire ; non vérifiée | [su] idem | [su] idem |
| Clé de rattachement | RNA en W30… et SIRET exigés à la demande [cité] ; leur présence dans les listes publiées est inconnue | inconnue (nom probable) | inconnue |

- **Format** : PDF de délibération ou d'arrêté, au mieux. Pas d'API.
- **Granularité** [su] : bénéficiaire nommé, montant, objet, date de la
  commission. SIRET et RNA rarement présents.
- **Profondeur** : celle des archives en ligne de chaque site (Drôme : au
  moins 2020 [cité]).
- **Délai** : publication de l'acte quelques semaines après la commission [su].
- **Caractère public** : actes administratifs publiés, réutilisables selon le
  CRPA [su].
- **Obligation SCDL** : les trois Départements y sont soumis pour les
  conventions de plus de 23 000 € [su]. Aucun ne s'y conforme sur data.gouv
  pour ce qu'on a pu mesurer (le Gard, au 08/09/2026).

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
    4. un **bilan** : d'autres territoires publient le leur (exemple :
       [Alès Agglomération, bilan 2021-2025 de l'EAC](https://www.agglopole.fr/wp-content/uploads/2026/07/Bilan-2021-2025-du-Service-education-artistique-et-culturelle.pdf))
       [cité]. Aucun bilan n'a été trouvé pour la CC.
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
| **LEADER** (FEADER, via les GAL) | **Avec réserve.** La Région Occitanie, autorité de gestion, a sélectionné 38 GAL [cité]. [su] Les règlements européens imposent de publier la liste des opérations et des bénéficiaires, au plus tard chaque trimestre ou tous les quatre mois, avec nom, montant et objet. Forme : un fichier régional, à localiser. Clé : le nom, parfois le SIRET. |
| **FEDER / FSE+** | **Avec réserve.** Même obligation de liste des opérations [su] ; des listes de bénéficiaires FEDER (Midi-Pyrénées) existent sur data.gouv.fr (étiquettes `feder`, `fse`) [cité]. Bénéficiaires rarement associatifs à cette échelle. |
| **ANCT** | **Oui, partiellement.** Jeu « Fabriques de territoire » sur data.gouv.fr (tiers-lieux labellisés et subventionnés) [cité]. Les autres dispositifs (France services, Petites villes de demain) ne sont pas connus sous forme de liste de subventions. |
| **Agence de l'eau** | **Non, au niveau du bénéficiaire.** Rhône Méditerranée Corse (Gard, Drôme) publie des communiqués trimestriels agrégés par territoire [cité]. Brassac relève d'**Adour-Garonne** [su], non instruite. Bénéficiaires associatifs rares (rivières, pêche). |
| **Fondations reconnues d'utilité publique** | **Non.** Elles publient leurs comptes annuels au JOAFE (au-delà de 153 000 € de dons) [cité], pas la liste des subventions qu'elles versent. Ce ne sont pas des fonds publics au sens du projet. |

## 4. Synthèse

| Financeur | Source | Exploitable maintenant | Avec réserve | Non |
|---|---|:-:|:-:|:-:|
| Commune | délibérations (`cm_flux`) | ✔ (déjà) | | |
| Intercommunalité | délibérations (`cm_flux`) | ✔ (déjà) | | |
| Intercommunalité, CGEAC | délibération + appel à candidatures + jaune | | ✔ PDF, signataires à établir | |
| État, tous programmes (DRAC comprise) | jaune budgétaire (`jaune`) | ✔ (déjà) | retard de 12 à 24 mois, millésime 2022 cassé | |
| État, FDVA de l'année | listes des académies | | ✔ PDF ou page web, nom seul, trois académies | |
| État, détail par dossier | Data.Subvention | | | ✘ réservé aux agents |
| Région Occitanie | `data.laregion.fr` (`region`) | ✔ (déjà, ≥ 23 000 €) | | |
| Région Occitanie, petites aides | délibérations de commission permanente | | ✔ PDF, à localiser | |
| Région Auvergne-Rhône-Alpes | délibérations de CP (`edelib`) ; jeu inconnu | | ✔ à instruire | |
| Département du Gard | annexe du CA ; délibérations de CP | | ✔ à localiser | ✘ aucun jeu ouvert |
| Département de la Drôme | arrêtés d'attribution en PDF | | ✔ PDF avec listes | |
| Département du Tarn | annexe du CA ; délibérations | | ✔ à localiser | ✘ aucun jeu trouvé |
| Toute autorité ≥ 23 000 € | SCDL sur data.gouv (`subv_ouvertes`) | ✔ (déjà) | | |
| LEADER, FEDER | listes d'opérations de l'autorité de gestion | | ✔ | |
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
1. **Le Département, par l'annexe « concours attribués » de son compte
   administratif.** Une seule pièce par an et par Département, sans seuil,
   avec tous les bénéficiaires. Lecture de tableau PDF, déjà pratiquée pour
   les budgets votés. Trois Départements, donc trois sources, mais une seule
   forme de document (maquette M57).
2. **Les arrêtés et délibérations du Département** (la Drôme d'abord, dont les
   arrêtés listent les associations). C'est plus frais que l'annexe, mais il
   faut un connecteur par site et lire des PDF.
3. **Les listes FDVA des académies** : elles donnent l'année en cours, quand le
   jaune n'arrive qu'un à deux ans après. Il y a trois pages, le nom seul, et
   les noms se rattachent mal : à n'écrire qu'avec une relecture à l'atelier,
   sur le modèle de `collectors/marches_extraits.py`.
4. **La Région Auvergne-Rhône-Alpes** : d'abord instruire (jeu ouvert ou
   non) ; un collecteur régional déclaré, comme `occitanie_region`.
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
