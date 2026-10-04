"""La fabrication du snapshot public, découpée.

`scripts/build_public_snapshot.py` reste le point d'entrée et la façade : les
appelants (`api.py`, `scripts/publication.py`, l'installateur, les essais)
continuent d'importer leurs noms de là, ou de lancer le script par son chemin.
Ce paquet porte le code qu'il appelle.

`scripts/verify_snapshot.py` et `scripts/comparer_snapshots.py` contrôlent ce
que ce paquet produit : ils ne l'importent jamais.
"""
