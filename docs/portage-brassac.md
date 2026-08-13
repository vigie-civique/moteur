# Journal de portage — Brassac (Tarn), 13 août 2026

Ce document est le compte rendu d'une expérience, pas une notice. Le dispositif
avait été écrit pour une commune ; il a été rejoué sur une autre, choisie pour
n'avoir rien en commun avec la première : autre département, autre
intercommunalité, autre CMS, aucun lien personnel. Ce qui suit est ce que le
portage a réellement coûté, et où.

Il est écrit **avant** d'avoir décidé où passe la frontière entre le moteur et
l'instance, parce que c'est lui qui doit en décider. Écrit après, il justifierait
des choix déjà faits.

Instance d'origine : Lasalle (Gard, 30140), 1 202 habitants.
Instance de portage : Brassac (Tarn, 81037), 1 289 habitants,
CC Sidobre Vals et Plateaux (16 communes).

---

## Ce qui s'est porté sans une ligne de code

Quatorze collecteurs sur vingt-trois n'ont demandé que de la configuration :
SIRENE, RNA/JO, BODACC, DVF, OFGL, RNE, Sitadel, DECP/BOAMP, Géorisques, INSEE
Melodi, fiscalité locale, élections, BANATIC, monuments historiques.

Ils interrogent des API nationales indexées par code INSEE, code postal ou
SIREN. Changer de commune, pour eux, c'est changer trois constantes. C'est la
partie du dispositif qui est réellement générique, et elle représente
l'essentiel du volume collecté : sur Brassac, 5 716 entreprises, 798
associations, 1 919 mutations foncières, 941 autorisations d'urbanisme, 4 563
indicateurs et 9 054 annonces BODACC.

Cette observation est le fondement de tout ce qui suit : **le moteur est
national, la particularité est locale et se limite aux sites officiels.**

## Ce qui a demandé du travail, et pourquoi

### 1. Les sites officiels — la partie irréductible

Il n'existe pas de format commun aux sites de mairie. Les collecteurs
`events_scraper`, `cc_cac_scraper` et la chaîne `cm_*` étaient écrits pour un
thème Drupal et pour une arborescence `/CR/` : ils n'ont rien à analyser
ailleurs.

Ce que le portage a appris, et qui n'était pas prévisible : **les deux sites du
territoire de Brassac exposent l'API REST de WordPress en lecture anonyme.** Il
n'y a donc rien à scraper au sens HTML — on lit des objets typés (date ISO,
catégories, lien canonique, contenu rendu). Le connecteur écrit pour Brassac
fait 200 lignes contre 440 pour son équivalent Lasalle, et il est plus fiable.

Corollaire à ne pas perdre : ce n'est pas « WordPress est plus simple que
Drupal », c'est **« une API déclarée bat toujours une structure devinée »**. La
première question à poser sur une nouvelle commune n'est pas « quel CMS ? » mais
« y a-t-il un point d'accès en lecture ? ».

### 2. La qualité de la source varie plus que le code

La commune de portage publie **217 procès-verbaux de conseil municipal en PDF,
de 2004 à 2026**, sur une seule page, avec des libellés datés réguliers. Sur
l'instance d'origine, 4,2 % des actes seulement renvoyaient à la pièce
elle-même ; ici, 17,7 %.

Autrement dit : **la reproductibilité du dispositif dépend moins de son code que
des habitudes de publication de la commune.** Un moteur parfaitement générique
rendra un site pauvre sur une commune qui ne publie rien, et un site riche là où
le secrétariat de mairie tient ses archives. Le dispositif ne crée pas de la
transparence, il la rend lisible quand elle existe.

Trois régimes de documents ont été rencontrés dans le même corpus :

| Période | Forme | Traitement |
|---|---|---|
| depuis 2016 | actes numérotés `48/2026 : n° 4713` | découpage par acte |
| 2014-2015 | comptes rendus synthétiques à puces | découpage par puce |
| avant 2014 | texte suivi, titres en gras (perdu à l'extraction) | **pas de découpage** |
| 10 documents | PDF scannés sans couche texte | OCR séparé |

Le troisième cas est le plus instructif : il valait mieux publier la séance avec
son texte intégral et le fait que le découpage a échoué (`decoupage_delib:
false`) que de fabriquer des délibérations en devinant où elles commencent. Un
moteur générique doit prévoir de ne pas savoir.

### 3. Des données locales déguisées en code

C'est la catégorie qui a fait le plus de dégâts, et la moins visible : elle ne
se détecte pas en cherchant le nom de la commune d'origine.

- `COMMUNE_ID = 63`, `ETAT_ID = 2044`, `PREFET_ID = 3576`, `CAC_ID = 1645` :
  des **numéros de ligne** de la base d'origine, en dur dans quatre collecteurs
  et dans le script de publication. Rejoués sur une autre base, ils désignent
  des entités quelconques. Un flux financier de l'État vers la commune devenait
  un flux entre deux entreprises tirées au hasard, sans qu'aucun contrôle ne
  s'en aperçoive.
- `DB_PATH` codé sur le nom de la base d'origine dans **dix fichiers** : ces
  collecteurs écrivaient dans une base fantôme, créée vide à côté de la vraie.
- `urbanisme.py` insérait « la commune est sous RNU, PLU en cours » — un fait
  sur la commune d'origine — dans la base de la commune de portage, daté et
  sourcé comme s'il avait été vérifié.
- Registre d'alias d'associations et libellé d'un budget annexe : de la saisie,
  pas du code.

**Règle qui en découle : aucune donnée de commune dans le code, jamais.** Ni
identifiant, ni fait, ni nom d'équipement. Une configuration et un fichier de
saisie, et le code ne connaît que des schémas.

### 4. Le schéma publié était en retard sur son propre script

Le `schema.sql` du kit ne créait pas cinq colonnes que
`build_public_snapshot.py` interroge (`entities.geocode_source`,
`entities.perimetre`, `financial_flows.perimetre/statut/type_norm`). Le script
de classement du périmètre (`migrate_perimetre.py`) était cité mais absent.

Conséquence directe : sur une base neuve, la publication échoue ; et si l'on
ajoute les colonnes sans le classement, `perimetre` vaut NULL, ce que
`publiable_dans_perimetre()` traite comme « commune de collecte » — les 10 709
entités des quinze autres communes seraient publiées comme si elles étaient de
la commune-siège. Le filtre existait, la donnée qui l'alimente non.

**Un kit doit être vérifié en le rejouant à froid, pas en le relisant.**

### 5. Frictions techniques, notables parce qu'elles se reproduiront

- **Plafond d'API silencieux** : l'open data BODACC refuse `offset > 10000` par
  un HTTP 400. Sur la commune d'origine aucun code postal n'atteignait le
  plafond ; ici, un code postal partagé avec une aire urbaine rend 32 807
  annonces et la collecte s'arrêtait en erreur au tiers du volume. Corrigé par
  un découpage en fenêtres annuelles.
- **Verrou d'écriture** : lire deux cents PDF à l'intérieur d'une seule
  transaction SQLite garde le verrou pendant vingt minutes et fait échouer tout
  autre collecteur sur `database is locked` — huit étapes nationales perdues
  d'un coup. Commiter par document, jamais par lot.
- **URL accentuées** : `urllib` transmet le chemin en ASCII et lève sur un
  fichier nommé `Séance-du-23-juillet-2018.pdf`. Vingt-et-un documents comptés
  « inaccessibles » alors qu'ils étaient en ligne.
- **Blocage par adresse IP** : le site de la préfecture coupe les connexions
  quand on enchaîne les requêtes, et l'arborescence de ses recueils (année →
  mois → acte, avec pagination) en demande plus de deux cents par année. Le
  blocage porte sur l'IP et survit au processus.
- **Le repli d'une expression régulière ne se déclenche pas** si la capture
  réussit déjà : `[a-zà-ÿ'’\-]*` sur « Jean-Claude » s'arrête sur « Jean- » et
  le moteur n'a aucune raison de revenir en arrière. Trois occurrences du même
  piège dans trois analyseurs différents.
- **Une date lue n'est pas une date d'événement** : un article de fond sur la
  Résistance a fait entrer une animation municipale à l'agenda du 2 septembre
  1944. Toute date extraite d'un texte doit être bornée par le contexte qui la
  produit.

### 6. Ce que la commune nouvelle a révélé

L'instance d'origine n'était concernée par aucune fusion de communes ; son
registre `COMMUNES_DELEGUEES` était vide, et le code qui l'exploite n'avait
donc jamais tourné. Le territoire de portage contient une commune nouvelle
(Fontrieu, 2016, trois communes fusionnées), dont les anciennes entités
existent toujours au répertoire SIRENE et dans BODACC sous leurs anciens noms.

Un registre vide n'est pas un registre testé. Les branches jamais empruntées de
l'instance de référence sont exactement celles qui casseront ailleurs.

---

## Chiffres

| | |
|---|---|
| Durée du portage | une journée |
| Occurrences du nom de la commune d'origine dans le moteur, avant | 120 (30 fichiers) |
| … après | 3 (2 fichiers, en commentaire) |
| Collecteurs portés sans modification | 14 sur 23 |
| Connecteurs de site réécrits | 4 (dont 2 supprimés, sans remplacement nécessaire) |
| Base produite | 12 443 entités, 13 013 événements, 2 012 délibérations |
| Snapshot public | 1 013 acteurs, 12 914 décisions, 1 067 pages |
| Occurrences restantes dans le site éditorial | 2 205 |

La métrique retenue reste le **temps jusqu'à première publication**, pas le
compteur d'occurrences. Il a été d'une journée pour quelqu'un qui connaissait
le dispositif. C'est la borne basse : elle ne dit rien du temps qu'il faudrait
à un tiers.

---

## Ce que ce journal impose au moteur

1. **La couche nationale est le moteur.** Elle ne prend que trois constantes et
   un registre de communes : c'est la frontière, et elle est nette.
2. **Les sites officiels sont des connecteurs**, avec une interface mince
   dictée par ce dont le reste a besoin — un catalogue de procès-verbaux, des
   articles datés, des avis de marché. Rien de plus tant qu'une troisième
   commune n'a pas été rejouée.
3. **Aucune donnée de commune dans le code**, et un contrôle automatique qui le
   vérifie plutôt qu'une relecture qui l'espère.
4. **Le schéma, l'atelier et la publication doivent être livrés ensemble** et
   testés sur une base neuve : ce qui n'est pas rejoué à froid est faux sans
   qu'on le sache.
5. **Prévoir de ne pas savoir** : un document non découpable, une source muette,
   une lacune, se publient en tant que tels.
