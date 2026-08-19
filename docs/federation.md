# Fédérer les instances

Note d'architecture — 16 août 2026. Statut : proposition, non implémentée.

Ce document décrit comment plusieurs instances du moteur peuvent coexister,
être découvertes et être recoupées, **sans que personne n'ait à les héberger ni
à en répondre**. Il sert aussi de base à la consultation juridique : le
périmètre du moissonnage et le partage des responsabilités y sont posés
explicitement.

---

## 1. Le principe

Une plateforme héberge et contrôle. Une fédération référence et recoupe. Le
dispositif ne peut être que le second, pour deux raisons qui n'ont rien à voir
entre elles et qui pointent au même endroit.

**La raison matérielle.** Le site public est statique et la base ne quitte
jamais la machine qui la construit (cf. `deploy/README.md`). Héberger N
instances signifierait rapatrier N bases de travail, donc N corpus non filtrés
contenant du `probable`, du `hypothesis` et du nominatif. C'est exactement ce
que l'architecture actuelle interdit, et à raison.

**La raison politique.** Un outil destiné à être repris n'impose pas son
hébergeur. Qui tient la base tient l'arbitrage éditorial ; qui tient
l'arbitrage doit en répondre. Centraliser l'hébergement, c'est reprendre d'une
main la liberté qu'on donne de l'autre.

D'où la règle qui commande tout le reste :

> **Chaque instance est souveraine sur ses données, son domaine, son atelier et
> sa ligne éditoriale. L'échelon fédéral ne détient que des index et des
> liens.**

---

## 2. Les trois cercles

| | Ce que c'est | Qui le tient | Ce que ça coûte à l'échelon fédéral |
|---|---|---|---|
| **Noyau** | le moteur : code, schéma, collecteurs, site | un dépôt public | maintenance du code |
| **Protocole** | un manifeste + un schéma de données + un contrôleur de conformité | spécifié dans le noyau, servi par chaque instance | rien |
| **Annuaire** | carte des instances, moissonnage des index, recherche transverse | l'association | une base légère et un cron |

L'**atelier ne se fédère pas**. Il contient la base de travail entière, non
filtrée. Un atelier par collectif, sur son serveur, et rien n'en sort que par
le snapshot public. C'est ce qui protège la fédération : le sensible ne quitte
jamais l'instance, donc une fuite reste locale par construction.

---

## 3. Le manifeste

Chaque site public sert un fichier à une adresse fixe :

```
https://<domaine-de-l-instance>/.well-known/vigie.json
```

En SvelteKit statique, il se dépose dans `public/static/.well-known/vigie.json`
et se retrouve tel quel dans `public/build/`.

C'est le seul point de contact obligatoire entre une instance et le reste du
monde. Tout le reste — l'annuaire, la conformité, le label — s'en déduit.

```json
{
  "vigie": 1,

  "instance": {
    "id": "lasalle",
    "nom_public": "Vigie Civique Lasalle",
    "url": "https://vigie-civique-lasalle.fr",
    "insee": "30139",
    "epci_siren": "200066389",
    "communes": ["30139", "30079", "30187"]
  },

  "editeur": {
    "nom": "Association Xxx",
    "type": "association",
    "directeur_publication": "Prénom Nom",
    "contact": "contact@exemple.fr",
    "mentions_legales": "https://vigie-civique-lasalle.fr/mentions-legales"
  },

  "moteur": {
    "version": "1.2.0",
    "schema_version": 4,
    "depot": "https://github.com/…/vigie-civique"
  },

  "snapshot": {
    "genere_le": "2026-08-16T19:31:26",
    "licence": "ODbL-1.0",
    "licence_url": "https://opendatacommons.org/licenses/odbl/1-0/",
    "attribution": "Vigie Civique Lasalle"
  },

  "endpoints": {
    "base": "/public_api/",
    "entities": "entities.json",
    "events": "events.json",
    "flows": "flows.json",
    "marches": "marches.json",
    "couverture": "couverture.json",
    "stats": "stats.json"
  },

  "compteurs": { "entites": 1807, "actes": 1450, "flux": 312, "marches": 47 },

  "moissonnage": {
    "autorise": true,
    "portee": ["entites_morales", "actes", "flux", "marches"],
    "frequence_jours": 1
  }
}
```

Trois champs portent tout le poids.

**`moissonnage.autorise`** — le moissonnage est **opt-in**. À `false`,
l'annuaire liste l'instance sur la carte avec son lien, et n'indexe rien. Une
instance peut donc exister dans la fédération sans y verser une ligne. C'est la
traduction technique du principe de souveraineté : le consentement au
recoupement est un réglage de l'instance, pas une politique de l'annuaire.

**`moissonnage.portee`** — la liste blanche de ce que l'instance accepte de
voir indexé. L'annuaire ne moissonne que l'intersection de cette liste et de sa
propre portée (§4). Retirer une valeur suffit à sortir un jeu du recoupement.

**`editeur.directeur_publication`** — nommé, publiquement. Une instance sans
directeur de publication déclaré n'entre pas dans la fédération. Ce n'est pas
une formalité : c'est ce qui garantit que la responsabilité éditoriale a un
titulaire identifié, et donc que l'annuaire n'en hérite pas par défaut (§6).

Le manifeste doit être **généré**, jamais écrit à la main :
`build_public_snapshot.py` l'émet à partir de `collectors/config.py` et
`config/publication_rules.json`, et `verify_snapshot.py` le contrôle comme le
reste — un endpoint annoncé qui n'existe pas, ou un compteur qui ne correspond
pas au fichier, est une erreur bloquante. Un manifeste qui ment est pire que
pas de manifeste : l'annuaire le croit.

---

## 4. Ce que l'annuaire indexe, et ce qu'il n'indexera jamais

L'annuaire moissonne les manifestes une fois par jour, puis les endpoints
autorisés. Il stocke des index et des liens ; l'instance reste la source qui
fait foi, et chaque résultat renvoie vers elle.

**Indexé :** personnes morales (entreprises, associations, services, lieux —
identifiées par SIREN/SIRET/RNA), actes (délibérations, arrêtés, annonces),
flux financiers publics, marchés publics et attributaires, compteurs et
couverture.

**Jamais indexé :** les personnes physiques. Concrètement, l'annuaire ne
moissonne ni `popolo.json` (qui porte `persons` et `memberships`), ni
`elus_rne.json`, ni `conflits.json`, ni les fiches `entite/<id>.json`, ni les
entités dont le type est une personne dans `entities.json`.

La raison n'est pas la pudeur, c'est le changement de nature. Publier les élus
d'une commune sur le site de cette commune relève d'une information de
proximité, adossée à des données publiques et à un intérêt local manifeste.
Constituer un index national interrogeable de personnes physiques est un autre
traitement, avec une autre finalité, une autre base légale, et un profilage
possible que le site local ne permet pas. La ligne est nette et doit le rester
— **elle est un invariant du moissonneur, contrôlé par un test, pas une
intention.**

Corollaire : le croisement inter-instances porte sur les personnes morales.
« Ce prestataire est attributaire dans onze communes » est le cas d'usage
central, il est licite, et il suffit largement à justifier l'annuaire.

---

## 5. Conformité et label

Le protocole est vérifiable, donc le label peut l'être aussi.

- **`docs/schema/public-snapshot-v1.json`** — un JSON Schema versionné qui
  décrit le manifeste et la forme des fichiers publiés. Versionné avec le
  moteur, il est le contrat.
- **`vigie doctor`** — valide un snapshot local avant publication, ou une
  instance distante par son URL. C'est le même contrôle dans les deux sens.
- **Le label** « Vigie Civique » s'accorde à une instance qui passe
  `vigie doctor`, déclare un directeur de publication et respecte la charte.
  L'annuaire l'affiche ; il n'est pas nécessaire pour utiliser le moteur.

Le nom est le seul levier conservé. Tout le monde peut forker, déployer,
modifier, y compris de travers. Personne ne peut appeler ça une Vigie Civique
sans passer le contrôle. C'est le modèle OpenStreetMap et Mastodon : liberté
totale sur le code, exigence sur l'usage du nom.

---

## 6. Responsabilités — ce qui doit être tranché avec un avocat

Trois questions ouvertes, posées ici dans les termes où elles doivent l'être.

**a. Qualification de l'annuaire.** Un service qui moissonne des données
publiées ailleurs, en construit un index et renvoie vers la source : hébergeur
au sens de la LCEN (art. 6), éditeur, ou responsable de traitement autonome ?
La réponse détermine s'il doit un dispositif de signalement, une modération a
priori, un DPO. La position de départ à faire valider : l'annuaire est
responsable de traitement pour son index, et l'instance reste seule éditrice de
ses contenus.

**b. Base légale du recoupement.** Chaque instance publie sous ODbL et sous sa
propre base légale. Le fait de recouper N jeux crée-t-il un traitement nouveau
appelant sa propre analyse d'impact (AIPD) ? Vraisemblablement oui, même
restreint aux personnes morales, dès lors que le croisement produit une
information qui n'existait dans aucune source.

**c. Droit d'opposition et droit de suite.** Une instance qui retire une donnée
ou passe `moissonnage.autorise` à `false` doit voir l'index purgé. Le
mécanisme technique est trivial ; c'est le délai contractuel qui doit être
écrit. Proposition : purge au prochain passage, 24 h au plus.

À cadrer par un avocat en **droit des données et droit de la presse** — la
combinaison, pas l'un des deux. Le dépôt de marque relève d'un **conseil en
propriété industrielle**, pas du même professionnel.

---

## 7. Chantiers, dans l'ordre

Les trois premiers sont à faire **avant la première instance tierce**. Après,
le format est figé par l'usage et ne se corrige plus.

1. **`schema_version` et migrations versionnées.** Déjà identifié comme dette
   interne (trois instances, trois schémas). Devient un prérequis : sans
   version de schéma déclarée, un moissonneur ne peut pas savoir ce qu'il lit.
2. **Le manifeste** — émis par `build_public_snapshot.py`, contrôlé par
   `verify_snapshot.py`, servi depuis `public/static/.well-known/vigie.json`.
   Suppose d'étendre le bloc `project` de `publication_rules.json` et
   `init_instance.py` avec `editeur`, `directeur_publication`, `moissonnage`,
   et de renseigner enfin `depot_url`.
3. **Le JSON Schema** `docs/schema/public-snapshot-v1.json`, plus un travail CI
   qui valide le snapshot d'exemple contre lui.
4. **`vigie doctor`**, local puis distant.
5. **Distribution installable** — `pip install vigie-civique`, CLI
   `vigie init/collect/publish/doctor`, plutôt qu'un clone git à bricoler.
6. **L'annuaire** — dépôt séparé, FastAPI + SQLite, un cron de moissonnage, une
   carte. Après la consultation juridique, pas avant.

## 8. Ce qui n'est pas prévu, et pourquoi

- **Héberger des instances.** Voir §1. Si une offre hébergée devait exister un
  jour pour des mairies, ce serait une activité distincte, avec son contrat et
  sa facturation, et sûrement pas portée par l'association qui tient l'annuaire.
- **Une base fédérée unique.** L'index n'est pas une base : il ne conserve pas
  les données de fond, il pointe. Toute dérive vers une copie centrale
  reconstitue le problème qu'on évite.
- **Un compte utilisateur fédéré, un SSO, une identité inter-instances.**
  Aucune valeur, beaucoup de surface d'attaque.
- **L'indexation des personnes physiques.** Voir §4. Ce n'est pas une étape
  ultérieure, c'est un refus.
