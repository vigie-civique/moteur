## Ce que ça change, et pourquoi

<!-- Le pourquoi surtout. Le quoi se lit dans le diff. Quand la modification
     vient d'un défaut constaté, le dire : c'est ce qui empêche de la défaire
     six mois plus tard. -->

## Contrôles

```
python3 -m pytest
python3 scripts/verifier_generique.py
python3 scripts/build_kit.py
```

- [ ] la suite passe, et **aucun test n'est sauté** avec les dépendances installées
- [ ] `verifier_generique.py` est vert — aucune particularité locale n'est entrée
      dans le moteur (ni code INSEE, ni SIREN, ni URL de mairie, ni identifiant
      de ligne en dur)
- [ ] `build_kit.py` construit l'archive
- [ ] aucune donnée versionnée : ni base, ni snapshot, ni `config/instance.json`,
      ni fichier nommant une personne physique

## Si l'une de ces trois fonctions est touchée

Elles décident de ce qui SORT du dispositif. Chacune a déjà laissé passer un
défaut réel. Une modification sans test correspondant ne sera pas fusionnée.

- [ ] `public_entity` → `tests/test_publication.py`
- [ ] `publiable_dans_perimetre` → `tests/test_perimetre.py`
- [ ] `build_kit.fichiers` → `tests/test_kit.py`
- [ ] aucune des trois n'est touchée

## Si un collecteur est ajouté ou modifié

- [ ] il journalise ses apports NEUFS, pas ses trouvailles — sinon
      `stale_source` ne peut plus repérer une source figée
- [ ] son `origine` est reconnue par `collectors/origine.py`, sinon la ligne
      n'est ni protégée ni ouverte à la saisie
- [ ] rien n'oblige à sortir sur le réseau pour lancer les tests
