# Dossiers thématiques — gabarit et pilote « eau »

> Brouillon de conception, 30/09/2026. Rien n'est encore codé.

Un dossier thématique répond à une question de citoyen — *qu'est-ce que je
paie, qui décide, depuis quand, qu'est-ce que je reçois* — en assemblant ce que
la base sait déjà (actes, comptes, indicateurs) et en **montrant ce qu'elle ne
sait pas**. Le dossier est aussi l'outil qui révèle les lacunes : chaque
rubrique déclare les données qui la remplissent ; une rubrique vide l'affiche
d'elle-même, avec la manière de la combler.

## 1. Deux familles

| Famille | Exemples | Remplissage | Instances |
|---------|----------|-------------|-----------|
| **Générique** | eau, déchets, télécoms, rivières/crues, forêt/incendie, transferts à l'EPCI | gabarit du moteur, requêtes paramétrées par `:insee` / `:epci_siren` | toutes, sans écriture |
| **Local** | La Cure (Lasalle) | récit rédigé, adossé à la même frise et aux mêmes chiffres | une seule |

Un dossier local qui touche un intérêt de l'auteur porte une **déclaration
d'intérêt** visible en tête.

## 2. Le gabarit — sept rubriques

| # | Rubrique | Question | Nature |
|---|----------|----------|--------|
| 0 | **La question** | ce que je paie, ce que je reçois | texte court, fixe par thème |
| 1 | **Qui décide** | commune → syndicat → EPCI → Département/État ; exploitant ; dates de transfert | chaîne datée, calculée |
| 2 | **L'objet physique** | le réseau, les ouvrages, la carte ; renvoi au chapitre relief | carte + liste |
| 3 | **Le service rendu** | qualité, continuité, couverture | indicateurs dans le temps |
| 4 | **Le prix** | combien, décomposé comment, évolution | série + décomposition |
| 5 | **L'argent public** | budgets annexes, comptes du syndicat, subventions, marchés | tableaux |
| 6 | **La frise** | délibérations, arrêtés, marchés, jalons | liste datée, liens vers les actes |
| 7 | **Ce qu'on ne sait pas** | lacunes, énigmes, et comment les combler | **calculée** à partir de 1–6 |

Le **relief** n'est pas une rubrique : c'est un chapitre transversal (« un
territoire en pente » : altitudes, hameaux, dispersion) auquel chaque dossier
renvoie depuis sa rubrique 2.

### Déclaration d'une rubrique

Chaque rubrique d'un dossier générique est une déclaration, pas du texte :

```toml
[[rubrique]]
id        = "eau.prix"
titre     = "Le prix de l'eau"
requete   = "SELECT annee, valeur FROM sispea_indicateurs i JOIN sispea_services s USING(code_service) WHERE s.communes LIKE '%'||:insee||'%' AND i.code='D102.0'"
attendu   = { lignes_min = 1, annees_depuis = 2015 }   # en deçà : « partiel »
combler   = { source = "SISPEA", action = "collecteur sispea", sinon = "RPQS de l'exploitant (CADA)" }
```

Le statut de chaque rubrique — **rempli / partiel / lacune** — est calculé, pas
déclaré. La rubrique 7 est la liste des rubriques non remplies et des énigmes
posées à la main (rubrique `enigme`, sans requête : une question ouverte avec
les pièces qui la fondent).

### Frise et actes : identité stable

Les conseils ont déjà été rejoués (recollecte, ré-OCR, re-découpage) : les
`events.id` changent d'un rejeu à l'autre. La frise ne référence donc jamais un
`id` ; elle retient la **clé naturelle de l'acte** (source, année, numéro
d'acte, date) et la résout au rendu. Les résumés de conseils de l'autre
chantier sont une source de la frise, pas une copie : le dossier pointe le
résumé et l'acte.

**Fait le 03/10/2026** — la clé datée (`collectors/cle_acte.py`) :

| Clé | Ce qu'elle désigne |
|-----|--------------------|
| `c-2021-41` | commune, année 2021, acte n° 41 |
| `cc-2025-12` | intercommunalité, 2025, acte n° 12 |
| `c-2021-03-04-s3` | acte sans numéro : 3ᵉ de la séance du 04/03/2021 |
| `c-2021-03-04-t1a2b3c4` | ni numéro ni rang : date + empreinte du titre — **faible**, jamais une ancre |
| `c-2021-03-04` | la séance elle-même |

L'ancre publique d'un acte est `/deliberations/{année}#{clé}` ; `#a{id}` reste
servi un cycle par la table d'alias de `liens.json`.

### Citer un acte dans un dossier

Rien à changer à la façon d'écrire : le snapshot relie seul les citations
naturelles (`collectors/citations.py`), contre les actes **publiés** seulement :

- `(CM du 14/04/2021)`, `(délibération CC du 02/04/2025)`,
  `conseil municipal du 4 mars 2026`, `délibération n°41/2021` ;
- une ligne de frise `| 17/02/2016 | Motion … | CM |` (la date est reliée).

Une séance qui a pris plusieurs actes est départagée par ce que la phrase dit
d'autre — une citation « entre guillemets » retrouvée dans le texte d'un seul
acte, un montant voté par un seul, l'objet d'une ligne de frise proche d'un
seul titre. Sinon le lien mène à la **séance**, signalé « imprécis ». Pour
lever l'ambiguïté, la syntaxe explicite :

```markdown
[le budget de la régie](acte:c-2021-42)      un acte, par sa clé
[la séance de mars](seance:c-2021-03-04)     une séance
[le registre signé](piece:c-2021-42)         la pièce source de l'acte
```

Une citation qui ne mène à rien de publié n'a pas de lien : elle entre au
relevé interne (`audits/citations_non_resolues.json`) et dans `lacunes.json`
comme une question. L'atelier montre, à l'ouverture d'un dossier, ce que
chaque citation deviendra.

Le rattachement d'un acte à un thème ne peut pas reposer sur une recherche
plein texte (voir § 3.6 : « station » ramène la station de ski de Prat-Peyrot).
Il faut une **étiquette thématique** posée une fois par acte, par règles puis
contrôle — mécanisme à décider avec le chantier des résumés pour n'en avoir
qu'un.

## 3. Pilote — l'eau à Lasalle (30140) : inventaire

Relevé le 30/09/2026 sur `Lasalle-v3/db/30140.db` et Hub'Eau.

### 3.1 Qui décide — **partiel, deux énigmes**

| Acteur | Trace dans la base | Source |
|--------|--------------------|--------|
| Régie communale (eau potable, assainissement collectif) | SISPEA `173063` / `173064`, indicateurs **jusqu'en 2022** | `sispea_services` |
| SIAEP de la région de Lasalle — 6 communes (30140, 30236, 30246, 30252, 30329, 30335), **délégation** | SISPEA `173349`, SIREN **253000426**, entité 2139 | `sispea_services`, `entities` |
| « SIAEP DE LASALLE », budget M49 2020→2025 | SIREN **200091197** | `comptes_syndicats` |
| Veolia Eau – CGE | entité 8714, sans lien ni contrat | `entities` |
| CC Causses Aigoual Cévennes : eau et assainissement **optionnels** ; budget annexe M49 créé le 09/11/2022 ; « Régie eau et assainissement CAC » acheteuse en 2024 | `epci_competences`, `events`, `marches_publics` | BANATIC, actes CC |

- **Énigme 1 — deux SIREN pour un syndicat.** 253000426 (SISPEA, fiche) et
  200091197 (comptes depuis 2020). Recréation, fusion, ou deux structures ?
  Les habitants desservis par le syndicat passent de 884 (2019) à 1 091 (2020).
- **Énigme 2 — qui exploite aujourd'hui.** Les indicateurs de la régie
  communale s'arrêtent en 2022, date à laquelle la CC crée son budget eau ; la
  régie de la CC n'apparaît pas dans `sispea_services`. Date effective du
  transfert, sort du contrat Veolia (date, durée, avenants) : inconnus.

### 3.2 L'objet physique — **lacune**

Aucune donnée sur les ouvrages de Lasalle. Hub'Eau (`communes_udi`) montre que
**la commune est desservie par trois réseaux** (UDI), ce qui explique les deux
services SISPEA :

| UDI | Nom | Depuis |
|-----|-----|--------|
| 030000473 | LASALLE | ≤ 2022 |
| 030000476 | THOIRAS – ST BONNET SALEND. – ST FÉLIX PAILL. | ≤ 2021 |
| 030008363 | ROUTE ST HIPPOLYTE DU FORT | 2024 |

À combler : UDI et captages (Hub'Eau), arrêtés de DUP des captages (RAA —
`raa_scans`), réservoirs et stations (OSM), station d'épuration (portail
assainissement, ERU). Le chapitre relief explique le reste : pompage, pression,
hameaux en bout de réseau.

### 3.3 Le service rendu — **faux plein, puis lacune comblable**

- ⚠️ `eau_stations` / `eau_analyses` (28 stations, 91 600 analyses) ne sont
  **pas** de l'eau potable : ce sont des stations de **qualité des rivières**
  (Hub'Eau `station_pc`) et des prises d'eau, toutes du côté Aigoual de la CC
  (Dourbies, Lanuéjols, Camprieu, Valleraugue…). **Aucune n'est à Lasalle ni
  dans le périmètre du SIAEP.** Ne pas les servir dans ce dossier.
- SISPEA donne les taux de conformité : régie, microbiologie 86,7 à 100 %
  (2016-2022) ; syndicat, physico-chimie 60 % en 2013, 100 % depuis 2020.
- **Collecteur écrit** : `collectors/eau_potable.py` (step `eau_potable`),
  joué le 30/09 sur une copie de la base : 3 réseaux, 11 243 résultats
  depuis 2016. Réseau du bourg : 126 prélèvements, **14 hors limites
  bactériologiques** (dont 3 en mai-juin 2026) et 2 physico-chimiques ;
  réseau Thoiras (syndicat, Veolia Gard-Lozère) : 119 prélèvements, 1 et 4.
- ⚠️ Maître d'ouvrage et exploitant publiés par prélèvement ne suivent pas
  les délibérations : le bourg est dit exploité par la CC de 2016 à 2020, puis
  par la mairie depuis 2021 — l'inverse de la chronologie du transfert.
  Référentiel ARS relu rétroactivement ? À ne pas servir comme chronologie
  sans recoupement.

### 3.4 Le prix — **rempli en série, lacune en décomposition**

SISPEA D102.0 (TTC, pour 120 m³) :

| Service | 2009 | 2016 | 2020 | 2022 | 2024 |
|---------|-----:|-----:|-----:|-----:|-----:|
| Régie communale — eau | 1,60 | 2,28 | 2,43 | 2,43 | — |
| SIAEP — eau | 2,62 | — | 3,70 | 4,00 | **4,63** |
| Régie communale — assainissement | — | 0,91 | 1,72 | — | — |

Dans la même commune, en 2022, le m³ coûte **2,43 € ou 4,00 €** selon le
réseau auquel on est raccordé. Inconnu : la décomposition (abonnement, part
variable, part de l'exploitant, redevances de l'Agence de l'eau, TVA) et le
tarif depuis le transfert à la CC. Sources : RPQS, délibération tarifaire du
28/07/2021, délibérations tarifaires de la CC depuis 2023, facture type.

### 3.5 L'argent public — **partiel**

- SIAEP 200091197 : comptes M49 2020-2025 (fonctionnement, investissement,
  dette, ventes et redevances, subventions).
- Budget annexe eau communal : `budget_annexe` **vide**.
- Subventions « AEP / eaux usées / réseaux humides » dans `financial_flows`
  (2018-2025) : la plupart concernent d'autres communes de la CC (Valleraugue,
  Notre-Dame-de-la-Rouvière) — **le rattachement communal est à contrôler**
  avant de servir une somme.
- Marchés : étude de faisabilité du transfert (2017), schéma stratégique AEP et
  assainissement (2024), caractérisation de la ressource (2024).

### 3.6 La frise — **abondante mais bruitée**

~730 actes remontent sur « eau / potable / captage / assainissement / SIAEP /
Veolia » (494 CC, 233 commune), en hausse nette depuis 2022. Le bruit : la
station de ski et l'éco-station de Prat-Peyrot, la « station d'épuration » d'une
autre commune, et des fragments de découpage titrés comme des actes (CC du
09/11/2022 : « 79 345 EHT », « é oual ARRONDISSEME:N »). Jalons déjà visibles :

| Date | Acte |
|------|------|
| 17/02/2016 | Lasalle — motion pour le maintien du SIAEP |
| 18/01/2017 | CC — marché, étude de faisabilité du transfert eau/assainissement |
| 18/06/2018 | Lasalle — RPQS 2017 eau |
| 16/12/2020 | Lasalle — transfert de la compétence « eau et assainissement » |
| 28/07/2021 | Lasalle — tarif eau et assainissement |
| 28/09/2022 | Lasalle — transfert de la compétence eau ; CC — subventions eau et assainissement |
| 09/11/2022 | CC — création du budget annexe M49 « eau » et « assainissement collectif » |
| 2024 | Régie eau et assainissement CAC — schéma stratégique |

### 3.7 Ce qu'on ne sait pas — premier état

| Lacune / énigme | Comblable par | Effort |
|-----------------|---------------|--------|
| ~~Potabilité au robinet~~ | `eau_potable.py` — écrit, à déployer | fait |
| Captages, ouvrages (réseaux : faits) | RAA (DUP), OSM | lecture RAA |
| Deux SIREN du SIAEP | SIRENE (dates de création/cessation) | requête |
| Date effective du transfert à la CC ; régie CC absente de SISPEA | actes CC 2022-2023, SISPEA par SIREN de la CC | lecture |
| Contrat Veolia (objet, durée, avenants) | actes du SIAEP, RPQS | CADA si absent |
| Décomposition du prix, tarif depuis 2023 | RPQS, délibérations tarifaires CC, facture | lecture / CADA |
| Budget annexe eau communal | comptes communaux (budget M49) | collecteur existant à vérifier |
| Rattachement communal des subventions eau | `financial_flows` → bénéficiaire | contrôle |
| Frise propre | étiquette thématique + nettoyage des fragments | mécanisme à décider |

## 4. Suite

1. Décider le format de déclaration (TOML ci-dessus ou table SQLite) et le
   mécanisme d'étiquette thématique, avec le chantier des résumés.
2. Combler « potabilité » et « réseaux » (Hub'Eau) : c'est ce qui transforme le
   dossier eau de chronique administrative en dossier sur **l'eau**.
3. Jouer le même gabarit sur Saillans et Brassac (12 et 29 stations
   `eau_stations`, 2 services SISPEA chacune) pour vérifier qu'il est générique
   — et que leurs stations sont bien de l'eau potable, ce dont Lasalle fait
   douter.
