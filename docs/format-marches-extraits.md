# Marchés lus dans les procès-verbaux : le format du rapport, et le chemin d'entrée

Les marchés d'une petite commune passent sous les seuils de publicité : ni le
BOAMP ni les données essentielles de la commande publique (DECP) n'en gardent
trace, et ils ne se lisent que dans les procès-verbaux du conseil. Relevé à
Lasalle le 04/10/2026 : le site servait 58 marchés, tous de
l'intercommunalité, aucun de la commune ; un outil d'extraction hors dépôt
(modèle local, garde par citation) en avait lu 180 dans les PV de 2016 à 2026,
dont 77 pour la commune. Ils dormaient dans un rapport JSON.

Ce document décrit le chemin qui les fait entrer, et le format que l'outil doit
produire pour l'emprunter.

## Le chemin

```
rapport JSON ─▶ dépôt (atelier, ou scripts/deposer_marches_extraits.py)
                 │ chaque ligne est contrôlée contre la BASE ; une ligne
                 │ attestée devient une proposition « en attente »
                 ▼
          /atelier/propositions?nature=marche
                 │ un VALIDATEUR relit chaque ligne, l'acte et la citation
                 │ sous les yeux : accepte, corrige puis accepte, ou écarte
                 ▼
          une saisie `marche` dans config/saisies.json (confirmed)
                 │ rejouée par le collecteur `saisies`, comme tout travail humain
                 ▼
          marches_publics — rattachée à son acte (event_id), à sa pièce
          (raw_document_id) et à son acheteur (SIREN) ─▶ snapshot ─▶ /marches
```

- **Rien n'est publié avant l'acceptation.** Le dépôt écrit des propositions,
  rien d'autre. Le snapshot en publie le **nombre** (`couverture.json`,
  `extraits.marches`), jamais les lignes (décision 6 du 04/10/2026).
- **Rejouer ne double rien.** Chaque ligne a une empreinte (l'acte, l'objet, le
  titulaire et le montant, sous forme compacte). L'acte y entre par sa clé
  datée (`events.cle_acte`) quand il en a une, pour qu'un redécoupage des
  procès-verbaux, qui renouvelle `events.id`, ne fasse pas reproposer ce qui a
  déjà été tranché ; une ligne en attente retrouve son acte de la même façon.
  Une empreinte déjà proposée
  ne l'est plus, que la proposition ait été acceptée, écartée ou soit en
  attente. L'acceptation écrit une saisie dont l'identifiant dérive de cette
  empreinte, et le rejeu des saisies ne réécrit pas une ligne déjà en base.
- **Une ligne acceptée survit à une reconstruction de la base** : elle vit dans
  `config/saisies.json`, que `run_all` rejoue. Sur une autre machine, l'acte se
  retrouve par sa clé datée (`events.cle_acte`) et la pièce par son empreinte
  (`raw_documents.sha256`), pas par des identifiants de ligne.
- **Qui fait quoi.** Déposer un rapport et trancher une ligne sont réservés au
  rôle validateur (ou administrateur). Un contributeur voit la file, pas les
  gestes.

## Le format

Un objet JSON, encodé en UTF-8 :

```json
{
  "format": "vigie-marches-extraits/1",
  "outil": "nom et version de l'outil, libre",
  "genere_le": "2026-10-04T18:00:00",
  "lignes": [
    {
      "event_id": 18342,
      "date": "2024-03-12",
      "type_acte": "deliberation",
      "titre_acte": "Toiture de l'école : attribution du marché",
      "source_url": "https://exemple.invalid/pv/2024-03-12.pdf",
      "deja_importe": false,
      "acheteur_nom": "Commune de Testonville",
      "acheteur_siren": "219900017",
      "objet": "Réfection de la toiture de l'école",
      "titulaire": "Toits du Causse",
      "montant": 18450.0,
      "devise_base": "HT",
      "procedure": "procédure adaptée",
      "nature": "travaux",
      "citation": "décide d'attribuer le marché de réfection de la toiture de l'école à l'entreprise Toits du Causse pour un montant de 18 450,00 € HT"
    }
  ]
}
```

Une **liste nue** de lignes est acceptée aussi (c'est la forme du rapport
existant). Un objet qui déclare un autre `format` est refusé entier.

| Champ | Obligatoire | Forme | Ce qu'il dit, et ce qui est vérifié |
|---|---|---|---|
| `event_id` | oui | entier | L'acte d'où la ligne est lue : `events.id` **de la base de l'instance où l'on dépose**. Doit désigner un acte d'assemblée (`deliberation`, `deliberation_cc`, `conseil_municipal`, `conseil_communautaire`). |
| `date` | oui | `AAAA-MM-JJ` | La date de l'acte. **Doit égaler celle de l'acte en base** : c'est ce qui refuse un rapport produit sur une autre base, dont les identifiants désigneraient d'autres actes. |
| `citation` | oui | texte | Le passage **littéral** de l'acte qui atteste la ligne. Il doit se retrouver dans le texte de l'acte (`events.content`), ou à défaut dans celui d'un autre acte de la même pièce (même document archivé, ou même adresse et même date). Le contrôle est `collectors/extraction.py::citation_presente` : casse, accents, ponctuation et blancs ignorés ; au moins 15 caractères. |
| `objet` | oui | texte | L'objet du marché. |
| `acheteur_nom` | oui | texte | L'acheteur, tel que l'acte le nomme. Conservé tel quel ; le site publie le nom de la **fiche** de l'acheteur. |
| `acheteur_siren` | non | 9 chiffres (ou un SIRET de 14) | Rattache l'acheteur à sa fiche. L'outil de Lasalle le **déduit de l'assemblée** plutôt qu'il ne le lit : l'atelier le dit au validateur. Sans lui, la portée est déduite du nom (`attribution_acheteur`), et reste « non établie » quand le nom ne suffit pas. |
| `titulaire` | non | texte | L'attributaire. Sans titulaire, la ligne est un avis, pas un marché attribué. |
| `montant` | non | nombre ≥ 0 | En euros, tel que l'acte le donne. `"18 450,00"` est lu aussi. |
| `devise_base` | non | `HT` ou `TTC` | Conservé dans `marches_publics.montant_base`. |
| `procedure`, `nature` | non | texte | Reportés tels quels. |
| `type_acte`, `titre_acte`, `source_url` | non | texte | Montrés au relecteur, jamais écrits en base. |
| `deja_importe` | non | booléen | Vrai : l'outil sait la ligne déjà en base (BOAMP, DECP). Elle n'est pas proposée — elle serait publiée deux fois. |

Toute autre clé est **ignorée**, et le bilan du dépôt la nomme (`cles_ignorees`).

### Ce que le dépôt rend

```json
{"lignes": 180, "proposees": 171, "deja_proposees": 0, "deja_importees": 4,
 "refusees": [{"ligne": 37, "motif": "citation introuvable dans le texte de l'acte"}],
 "cles_ignorees": ["score"], "par_portee": {"commune": 74, "intercommunalite": 97}}
```

Une ligne refusée l'est avec sa raison, et le reste du rapport est déposé.
Raisons possibles : champ obligatoire manquant ou mal formé ; acte absent de
la base, ou qui n'est pas un acte d'assemblée ; date différente de celle de
l'acte ; citation trop courte ou introuvable.

### Ce qui n'est pas refusé, mais signalé au relecteur

- le montant ne figure pas dans la citation (il peut se lire ailleurs dans l'acte) ;
- la citation se lit dans un autre acte de la même pièce, pas dans celui-ci ;
- un marché **déjà en base** porte le même acheteur (par SIREN) et le même
  montant à l'euro près : doublon, ou autre marché ? L'outil calcule
  `deja_importe` par acte, pas par marché, et ne le voit pas ;
- l'acheteur lu est la commune alors que l'acte est communautaire, ou
  l'inverse — un compte rendu, ou une erreur de lecture : un acte de
  l'intercommunalité n'est pas un acte de la commune.

### Ce qu'un validateur peut corriger

`objet`, `acheteur_nom`, `acheteur_siren`, `titulaire`, `montant`,
`devise_base`, `procedure`, `nature`. **Ni l'acte ni la citation** : ce sont
les preuves relues, et les changer reviendrait à accepter autre chose que ce
qui a été lu. La proposition acceptée garde la trace des champs corrigés.

### La date

Un procès-verbal donne la date de la **décision** d'attribuer ; la
notification suit. C'est la seule date que la pièce connaît : elle est écrite
dans `date_notif`, qui range le marché dans son année sur /marches.

## Faire entrer l'extraction dans le dépôt

Ce qui existe déjà :

- `collectors/extraction.py` lit un texte avec un modèle de langage, sans
  connaître le fournisseur, et vérifie chaque citation ; son gabarit `marche`
  demande objet, acheteur, titulaire, montant, date et citation ;
- `POST /api/atelier/ia/extraire` l'expose à l'atelier, acte par acte, quand
  `RAG_ENABLED=1` (Ollama sur la machine) ;
- `scripts/banc_essai_ia.py` compare des modèles sur ce même gabarit.

Ce qui manque pour remplacer l'outil externe :

1. un script de passe sur les actes d'assemblée qui ont un texte
   (`events.content`), qui appelle `extraire(texte, "marche", appel)` et écrit
   un rapport **dans ce format** — l'`event_id` et la `date` y viennent de la
   base, pas du modèle ;
2. le gabarit `marche` enrichi de `devise_base`, `procedure` et `nature` ;
3. le SIREN de l'acheteur posé **par le code** et non par le modèle : celui de
   la commune ou de l'intercommunalité quand `attribution_acheteur` les
   reconnaît, rien sinon ;
4. `deja_importe` calculé contre `marches_publics` (même acheteur, même année,
   montant égal à l'euro près) ;
5. une passe qui tourne là où le modèle tourne (le poste qui a Ollama), le
   rapport étant ensuite déposé sur le serveur par l'atelier.

Rien de cela ne publie quoi que ce soit : la relecture reste la seule porte.
C'est un travail de l'ordre d'un script et de ses essais, avec un modèle
simulé comme ceux de `tests/test_extraction.py`. Il n'est **pas** fait ici :
l'outil externe a déjà produit les 180 lignes de Lasalle, et la priorité était
qu'elles puissent entrer.
