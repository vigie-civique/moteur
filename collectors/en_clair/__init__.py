"""« Le conseil en clair » : une séance lue, vérifiée, rendue en A4.

Un RELEVÉ (`data/conseils/<date>-<cm|cc>/releve.json`) décrit une séance : ses
actes avec une citation littérale, leurs votes et montants, et deux feuilles en
langage courant (avant, après). Il est écrit hors de la chaîne automatique —
à la main ou avec un LLM sur le poste de l'opérateur —, jamais sur le serveur.

  verifier   confronte le relevé à ses sources ; une seule faute bloque tout ;
  rendu      rend les feuilles (HTML A4, PDF si Chrome est présent).

La publication (`scripts/build_public_snapshot.py`) n'en retient que ce qu'un
validateur a RETENU à l'atelier : cf. `collectors/verdict.py`, OBJETS_A_RETENIR.
"""
