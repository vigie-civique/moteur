"""Ce qu'un montant est devenu — et rien de plus.

La base stockait `statut='realise'` sur les 193 flux de Lasalle sans exception :
la subvention votée en conseil, la dotation lue dans les comptes administratifs,
le marché notifié et la demande de DSIL portaient le même mot. Le site en tirait
« la commune a versé 10 k€ » pour un exercice 2026 dont aucun paiement n'est
consolidé, et la page ne rattrapait la nuance qu'en cherchant « demandée » dans
le NOM du type — un accident de libellé tenait lieu de modèle de données.

Une subvention votée a vocation à être payée. Le site doit décrire la pièce
disponible aujourd'hui, pas la suite probable de l'histoire.

L'état se DÉDUIT de la provenance, il ne s'invente pas :
un compte administratif atteste un paiement, une délibération atteste un vote,
un avis de notification atteste un engagement. Quand la provenance ne dit rien,
l'état est `inconnu` — jamais `paye` par défaut.
"""

from __future__ import annotations

import re

# Ordre du cycle de vie. Sert aussi à trier un affichage.
ETATS = ("demande", "vote", "engage", "paye", "annule", "inconnu")

LIBELLES = {
    "demande": "demandé",
    "vote": "voté",
    "engage": "engagé",
    "paye": "payé",
    "annule": "annulé",
    "inconnu": "état inconnu",
}

# Ce que chaque état atteste, mot pour mot — repris tel quel par le site et par
# le dictionnaire de données, pour qu'une seule phrase circule.
DEFINITIONS = {
    "demande": "Sollicité auprès d'un financeur. Ni accordé, ni versé.",
    "vote": "Décidé par une délibération. Le paiement n'est pas attesté.",
    "engage": "Engagé par un marché notifié ou un acte d'attribution.",
    "paye": "Constaté dans les comptes de la collectivité.",
    "annule": "Annulé ou abandonné après décision.",
    "inconnu": "La source ne permet pas de dire où en est ce montant.",
}

# Une saisie humaine dans l'atelier prime toujours sur la déduction : quelqu'un
# a lu la pièce. Les deux valeurs héritées de l'ancien modèle sont retraduites.
_STATUTS_SAISIS = {
    "demande": "demande",
    "vote": "vote",
    "engage": "engage",
    "paye": "paye",
    "annule": "annule",
    # `realise` était la valeur par défaut de la colonne, posée par tous les
    # collecteurs sans y penser : elle n'atteste rien et ne prime sur rien.
    "realise": None,
    "": None,
}

_DEMANDE = re.compile(r"demand[eé]", re.I)
_ANNULE = re.compile(r"annul|abandonn|caduc", re.I)

# Sources qui attestent un paiement : comptes administratifs et agrégats
# d'exécution budgétaire. Ce sont des comptes clos, pas des intentions.
_SOURCES_PAYE = re.compile(r"\bOFGL\b|compte[s]? administratif|balance", re.I)
# Sources qui attestent un engagement : un marché notifié est signé.
_SOURCES_ENGAGE = re.compile(r"\bDECP\b|\bBOAMP\b|march[ée]s?[ _-]publics?", re.I)
# Sources qui attestent un vote : comptes rendus et procès-verbaux de conseil.
_SOURCES_VOTE = re.compile(r"^CR\b|^CM\b|conseil|d[ée]lib|proc[eè]s.verbal|\bPV\b", re.I)


def etat_du_flux(type_: str | None, source: str | None,
                 statut: str | None = None) -> str:
    """L'état d'un montant, déduit de ce qui le documente.

    `statut` est la saisie de l'atelier : quand elle dit quelque chose, elle
    gagne. Sinon on lit le type puis la source, dans cet ordre — un type
    « DSIL_demande » reste une demande même s'il figure dans un compte rendu de
    conseil, puisque c'est le conseil qui décide de la solliciter.
    """
    saisi = _STATUTS_SAISIS.get((statut or "").strip().lower(), "inconnu")
    if saisi:
        return saisi

    type_ = type_ or ""
    if _ANNULE.search(type_):
        return "annule"
    if _DEMANDE.search(type_):
        return "demande"

    source = source or ""
    if _SOURCES_PAYE.search(source):
        return "paye"
    if _SOURCES_ENGAGE.search(source) or _SOURCES_ENGAGE.search(type_):
        return "engage"
    if _SOURCES_VOTE.search(source):
        return "vote"
    return "inconnu"


def est_verse(etat: str | None) -> bool:
    """Vrai seulement si de l'argent est effectivement sorti.

    Le seul prédicat qui autorise le mot « versé » à l'écran.
    """
    return etat == "paye"
