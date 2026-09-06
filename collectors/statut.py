"""
Statut d'une instance — ce qu'elle est, et ce qu'un lecteur doit en savoir.

Trois sites servis par le même moteur peuvent n'avoir pas du tout le même
statut, et rien ne le disait : un lecteur arrivant sur un portage de
démonstration depuis un moteur de recherche n'avait aucun moyen de savoir que
personne, sur place, ne tenait ce site. Il lisait ses manques comme la qualité
du dispositif.

Ce qui distingue les trois états n'est PAS la véracité des données — elles
sortent des mêmes registres publics partout. C'est **qui relit avant
publication**, et à quel rythme.

    demonstration  le moteur rejoué pour éprouver son portage ; personne
                   sur place ne tient le site
    constitution   tenu sur place, l'atelier qui le relit se constitue
    tenue          tenu et relu sur place par un collectif identifié

Un statut déclaré est une promesse ; la DATE de dernière collecte, publiée à
côté, est un fait. C'est elle qui rend le statut vérifiable sans croire
personne : au bout de six mois, un portage affiche six mois. Le statut se
démontre au lieu de s'annoncer — même règle que la page de couverture, qui
publie les lacunes plutôt que de promettre l'exhaustivité.

Ce module ne contient AUCUNE donnée de commune : il ne connaît que des états.
"""

DEFAUT = "demonstration"

# L'ordre est celui de l'engagement croissant. Le défaut est le plus modeste :
# une instance neuve EST une démonstration tant que personne ne l'a prise en
# charge, et se déclarer tenue est un geste, pas un état de fait automatique.
TYPES = ("demonstration", "constitution", "tenue")

LIBELLES = {
    "demonstration": "Portage de démonstration",
    "constitution":  "Atelier local en constitution",
    "tenue":         "Instance tenue",
}

TEXTES = {
    "demonstration": (
        "Ce site a été produit pour éprouver le moteur de Vigie Civique sur un "
        "autre territoire. Les données viennent des mêmes registres publics que "
        "partout ailleurs, mais aucun collectif local ne tient ce site : rien "
        "n'y est relu par quelqu'un d'ici, et il n'est pas mis à jour au rythme "
        "de la commune."
    ),
    "constitution": (
        "Ce site est tenu sur place et remis à jour régulièrement ; l'atelier "
        "qui le relit se constitue — c'est ce que ce site cherche à rendre "
        "possible. Il comporte encore des manques et des erreurs : il est fait "
        "pour qu'on les lui signale."
    ),
    "tenue": (
        "Ce site est tenu sur place : relu avant publication, remis à jour "
        "régulièrement. Il comporte encore des manques et des erreurs : il est "
        "fait pour qu'on les lui signale."
    ),
}

# Commune aux trois : une expérimentation qui ne dit pas qu'elle en est une
# laisse croire à un produit fini, et un produit fini n'admet pas de lacunes.
MENTION_COMMUNE = (
    "Vigie Civique est une expérimentation ouverte. Ce qu'elle ne sait pas "
    "faire est écrit sur la page « Couverture et lacunes », et ce qui est faux "
    "se corrige : écrivez-nous."
)


def normaliser(brut) -> dict:
    """
    Rend un statut complet depuis ce que `config/instance.json` déclare.

    Un type inconnu n'est PAS corrigé en silence : il retombe sur le défaut le
    plus modeste. Annoncer « tenue » sur une faute de frappe serait la seule
    erreur vraiment coûteuse — elle promettrait une relecture humaine qui
    n'existe pas.
    """
    brut = brut if isinstance(brut, dict) else {}
    type_ = str(brut.get("type") or "").strip().lower()
    if type_ not in TYPES:
        type_ = DEFAUT
    tenue_par = str(brut.get("tenue_par") or "").strip()
    return {
        "type": type_,
        "libelle": LIBELLES[type_],
        "tenue_par": tenue_par or None,
        "texte": TEXTES[type_],
        "mention": MENTION_COMMUNE,
        "depuis": str(brut.get("depuis") or "").strip() or None,
    }
