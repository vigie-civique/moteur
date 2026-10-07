"""Les échecs qu'un collecteur ne doit jamais présenter comme un résultat."""
from __future__ import annotations


class ConfigurationManquante(RuntimeError):
    """Il manque à `config/instance.json` ce que le collecteur exige.

    Une exception, et non `sys.exit` : sortir du processus depuis un collecteur
    arrête la collecte entière, là où il ne manque qu'un réglage à UN step.
    `tests/test_run_step.py` refuse tout `sys.exit` sous `collectors/`, hors
    des points d'entrée en ligne de commande.
    """


class SourceInterrompue(RuntimeError):
    """La source a cessé de répondre avant la fin de la collecte.

    Ce n'est pas la même chose qu'une pièce retirée du site : là, on SAIT ce
    qu'on n'a pas lu, la lacune est connue et la collecte reste complète. Ici,
    non — on ignore ce qu'on n'a pas pu ouvrir.

    Deux incidents ont montré pourquoi cette distinction doit être portée par le
    code, et non laissée au lecteur du journal :

    - **24/08/2026, `raa_prefecture`** : 74 recueils lus sur 263, 189 échecs en
      série (« Remote end closed connection »), et le step déclaré `ok` dans
      `collector_runs`.
    - **25/08/2026, `wayback`** : les 12 instantanés de Brassac injoignables
      (panne DNS passagère), et le collecteur a conclu « aucun procès-verbal
      archivé trouvé » puis « ✓ cm_archive terminé ». Le pire des deux, parce
      que la conclusion était PLAUSIBLE : sur une commune dont le site n'a pas
      été refondu, « aucun PV archivé » est le résultat attendu, et personne ne
      l'aurait questionnée.

    La règle : ce qui a été lu est écrit en base AVANT que l'exception parte —
    elle ne défait rien, elle refuse seulement d'appeler « ok » un passage
    tronqué. La reprise est incrémentale.
    """
