# Ce que l'audit d'août 2026 a trouvé

Le moteur venait d'être vidé de toute commune et devait partir sur un dépôt
public. Huit jours de travail plus tard, il y est prêt. Ce document garde la
trace de ce qui n'allait pas, parce que la plupart des défauts trouvés se
ressemblaient : **des garde-fous qui donnaient un feu vert sans rien vérifier**.

## Les quatre silences

**Le filtre de périmètre publiait tout par défaut.** `publiable_dans_perimetre`
traitait `NULL` comme « dans le périmètre ». Une instance dont le classement
n'avait pas tourné publiait son intercommunalité entière : 10 735 fiches dont
6 151 relevaient d'une commune voisine, et 4 944 au lieu de 1 807 sur une autre.
Aucun test ne couvrait cette fonction.

**`build_kit` embarquait les bases.** Il énumérait le disque et testait les
suffixes à la main ; les sauvegardes s'appelant `<insee>.db.avant-<date>`, le
test sur `.db` les laissait passer. 175 Mo de données nominatives entraient dans
l'archive publique, et le contrôle de contenu les sautait en silence parce
qu'elles n'étaient pas décodables en UTF-8.

**Le contrôle de généricité ne cherchait que la commune courante.** Il annonçait
« aucune particularité locale » sur deux instances dont le code nommait 96 fois
la commune d'origine. Il en existait trois implémentations divergentes ; il n'en
reste qu'une.

**Un collecteur rendait « ok » avec 13 sources sur 15 en échec.** Overpass avait
répondu 429 puis coupé ; le site publié n'avait aucun lieu.

## La règle qui en sort

Une collecte partielle doit **lever**, pas rendre le nombre de lignes écrites.
Un défaut de configuration doit **fermer**, pas ouvrir. Un contrôle qui ne peut
pas lire doit **refuser**, pas passer. Les défauts de ce dispositif ne se
manifestent pas par des plantages mais par des silences.

## Ce qui a été mis en place

- 100 tests sur les trois fonctions qui décident de ce qui sort — le filtre de
  publication, le classement de périmètre, la liste des fichiers distribués ;
- une intégration continue en quatre travaux, dont la chaîne complète base →
  snapshot → étanchéité → site, sur une commune factice ;
- `deploy/`, qui n'existait que dans le dépôt de l'instance d'origine ;
- deux extracteurs — commissions communales et baux — pour de la donnée qui
  n'était dans aucun registre et avait été saisie à la main.

## Une leçon de méthode

Le banc d'essai des modèles locaux (`scripts/comparer_modeles.py`) a dû être
refait **trois fois**, et à chaque fois c'était la mesure qui avait tort : une
vérité de référence contaminée (un montant absent du texte qu'on demandait de
lire), un échantillon non représentatif (un filtre de longueur qui gardait 5 cas
sur 108, les plus faciles), puis une tâche mal posée. Sa conclusion tient en une
phrase : sur ce matériau, le choix du modèle importe moins que la précision de
la question qu'on lui pose.
