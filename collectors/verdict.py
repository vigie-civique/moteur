#!/usr/bin/env python3
"""verdict.py — ce qu'un humain a dit d'un objet, et ce que la publication en fait.

Décidé le 21/09/2026 : « séparer l'origine du verdict ». Jusque-là un même mot
portait deux questions. `confidence="verified"` était la valeur par défaut d'un
paramètre de collecteur (`collectors/db.py::upsert_entity`) — « vérifié »
voulait dire « écrit par un script » — et `entities.validation_status`, le seul
champ où l'atelier écrivait un jugement sur une fiche, n'était lu par AUCUNE
étape de publication. Relevé le 21/09 sur les trois instances : 22 783 fiches,
100 % `unverified`, et le ✓ de la file de travail sans le moindre effet.

Trois axes, trois questions, et plus un seul mot qui en porte deux :

  origine     comment le fait est entré (`collectors/origine.py`) :
              institutionnel · verbatim · atelier
  confidence  ce que la MACHINE en sait : verified · confirmed · probable ·
              hypothesis — posée par les collecteurs, jamais par un regard
  verdict     ce qu'un HUMAIN en a dit — ce module

Le verdict vit dans `annotations.review_status`, une ligne par objet. L'ABSENCE
de ligne vaut `jamais_relu` : on ne matérialise pas 22 783 lignes pour dire que
personne n'a regardé.

Ce que la publication en fait — règle confirmée par Julien le 21/09 :

  jamais_relu  publié si les règles de publication l'admettent. L'inverse
               aurait vidé les trois sites du jour au lendemain.
  retenu       publié, et signé : quelqu'un a regardé et l'assume.
  a_revoir     publié comme `jamais_relu` — c'est une file de travail, pas un
               retrait. Retirer en attendant d'avoir relu, c'est `ecarte`.
  ecarte       RETIRÉ du site, quelle que soit sa confiance. Écarter n'exige pas
               de connaître un meilleur chiffre : c'est pourquoi c'est permis
               même sur une ligne institutionnelle (cf. `origine.modifiable`).

Un verdict ne rend JAMAIS publique une donnée que les règles tiennent privée :
une relation familiale reste privée même `retenu`. Le verdict retire ; il
n'ouvre pas ce que le filtre RGPD ferme.
"""
from __future__ import annotations

JAMAIS_RELU = "jamais_relu"
RETENU      = "retenu"
A_REVOIR    = "a_revoir"
ECARTE      = "ecarte"

VERDICTS = (JAMAIS_RELU, RETENU, A_REVOIR, ECARTE)

#: Ce qu'on lit à l'écran. Le code et la base gardent les clés sans accent.
LIBELLES = {
    JAMAIS_RELU: "Jamais relu",
    RETENU:      "Retenu",
    A_REVOIR:    "À revoir",
    ECARTE:      "Écarté",
}

#: Les types d'objets qui portent un verdict, et que la publication DOIT lire.
#: `tests/test_verdict.py` écarte un objet de chaque type sur une vraie
#: publication et vérifie qu'il sort : un type ajouté ici sans lecture dans
#: `build_public_snapshot.py` fait échouer la suite — c'est le garde-fou qui a
#: manqué à `validation_status` pendant treize mois.
OBJETS = ("entity", "relation", "deliberation", "flow", "marche")

# Les anciens mots, et ce qu'ils voulaient dire. Deux vocabulaires ont coexisté :
# `annotations.review_status` (pending / validated / rejected) et
# `entities.validation_status` (six états, dont `published`, qui ne publiait
# rien, et `validated`, que `collectors/saisies.py` écrivait alors que l'API le
# refusait). Ils restent LISIBLES — une base non migrée, un export de décisions
# d'avant le 21/09, un script qui n'a pas suivi — mais on n'en écrit plus.
_ANCIENS = {
    "pending":    JAMAIS_RELU,
    "unverified": JAMAIS_RELU,
    "draft":      JAMAIS_RELU,
    "reviewing":  A_REVOIR,
    "validated":  RETENU,
    "verified":   RETENU,
    "published":  RETENU,
    "rejected":   ECARTE,
}


def verdict_de(valeur: str | None) -> str | None:
    """Le verdict qu'exprime `valeur`, ancien ou nouveau mot ; None si inconnu.

    Une valeur ABSENTE (None, vide) vaut `jamais_relu` : c'est le cas d'un objet
    sans ligne d'annotation. Une valeur INCONNUE rend None — l'appelant refuse,
    il ne devine pas. Ranger « peut-être » dans `retenu` signerait au nom de
    quelqu'un ; le ranger dans `ecarte` retirerait du site sans que personne
    l'ait décidé.
    """
    if valeur is None or not str(valeur).strip():
        return JAMAIS_RELU
    v = str(valeur).strip().lower()
    if v in VERDICTS:
        return v
    return _ANCIENS.get(v)


def ecarte(valeur: str | None) -> bool:
    """L'objet doit-il sortir de la publication ?"""
    return verdict_de(valeur) == ECARTE
