# Contribuer

Ce dépôt est le **moteur** : le code qui collecte, filtre et publie. Il ne
contient aucune donnée de commune, et ne doit jamais en contenir.

## La règle qui prime sur toutes les autres

**Une particularité locale ne va pas dans le code.** Ni un code INSEE, ni un
SIREN, ni une URL de mairie, ni un identifiant de ligne (`XXX_ID = 63` — c'est
un numéro qui désigne autre chose dans une autre base), ni un nom de commune
dans une chaîne exécutée. Tout cela vit dans `config/instance.json`.

```bash
python3 scripts/verifier_generique.py
```

Ce contrôle échoue si une particularité est entrée dans le moteur. Il tourne
aussi en intégration continue et sert d'admission à l'archive distribuable.

## Lancer les contrôles

```bash
pip install pytest
python3 -m pytest                        # 74 tests, ~2 s, sans réseau
python3 scripts/verifier_generique.py    # généricité
python3 scripts/build_kit.py             # l'archive se construit-elle ?
```

Les tests tournent sur une instance **factice** (`tests/instance_test.json`) et
sur une base construite depuis `db/schema.sql`. Ils n'ont besoin ni d'une
instance configurée, ni du réseau, ni d'Ollama : un dépôt fraîchement cloné doit
pouvoir les lancer, sinon ils ne servent à rien.

## Ce qui doit être couvert par un test

Trois fonctions décident de ce qui sort du dispositif. Chacune a laissé passer
un défaut réel, et aucune n'était couverte avant août 2026 :

| Fonction | Ce qu'elle décide | Tests |
|---|---|---|
| `public_entity` | quelle fiche est publiée | `tests/test_publication.py` |
| `publiable_dans_perimetre` | ce que le périmètre autorise | `tests/test_perimetre.py` |
| `build_kit.fichiers` | ce qui entre dans l'archive publique | `tests/test_kit.py` |

Une modification de l'une des trois sans test correspondant ne sera pas
fusionnée. Ce n'est pas une exigence de forme : le défaut du 14/08/2026 —
`NULL` traité comme « dans le périmètre » — faisait publier 10 735 fiches dont
6 151 relevaient d'une commune voisine, et rien ne l'a signalé.

## Les données ne se versionnent pas

Ni base, ni snapshot publié, ni fichier nominatif, ni `config/instance.json`.
`build_kit.py` construit sa liste depuis `git ls-files` : ce qui n'est pas
versionné n'est pas distribué. Si un fichier de données arrive dans un commit,
c'est un incident, pas une inattention.

## Style

Commentaires et noms en français, comme le reste. Un commentaire explique
**pourquoi**, pas quoi : le quoi se lit dans le code. Quand une décision vient
d'un défaut constaté, le dire — c'est ce qui empêche de la défaire.
