#!/usr/bin/env python3
"""extraction.py — lire un procès-verbal avec un modèle de langage.

CE QUE FAIT CE MODULE, ET CE QU'IL NE FAIT PAS

Il PROPOSE des lignes structurées à partir d'un texte. Il n'écrit rien, nulle
part. Les propositions retournent à l'atelier, qui les affiche pré-remplies dans
le formulaire de saisie ; c'est un humain qui décide. Ce n'est pas de la prudence
de principe : ces données servent à mettre en cause des décisions publiques, et
une ligne fausse y coûte plus cher que dix lignes manquantes.

CHAQUE PROPOSITION CITE SA PHRASE, et la citation est vérifiée mécaniquement
contre le texte d'origine. Un modèle qui brode ne retrouve pas sa phrase : le
contrôle est automatique, et il ne dépend d'aucune confiance accordée au modèle.
Les lignes dont la citation est introuvable sont SIGNALÉES, jamais supprimées —
les masquer reviendrait à cacher le comportement réel du modèle, qui est
justement ce qu'on veut voir.

LE FOURNISSEUR N'EST PAS ICI. Ce module reçoit une fonction d'appel et ne sait
rien de qui répond — Ollama sur la machine, une passerelle distante, ou rien du
tout. C'est ce qui permet à `scripts/banc_essai_ia.py` de comparer deux modèles
avec exactement le prompt de l'atelier, sans en tenir une seconde copie.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from typing import Callable

EXTRACTION_SYSTEM = (
    "Tu extrais des données financières et administratives de procès-verbaux de "
    "conseils municipaux français. Tu ne réponds QUE par un objet JSON valide.\n"
    "Règles absolues :\n"
    "- N'invente RIEN. Si une information n'est pas dans le texte, omets la ligne.\n"
    "- Chaque ligne porte un champ `citation` : la phrase EXACTE du texte, "
    "recopiée mot pour mot, qui justifie la ligne.\n"
    "- Les montants sont des nombres, sans symbole ni espace (12345.67).\n"
    "- Les dates sont au format AAAA-MM-JJ.\n"
    "- Un montant cité dans un tableau de financement prévisionnel n'est PAS une "
    "dépense décidée : ne le retiens pas comme flux financier.\n"
    "- Mieux vaut une liste vide qu'une ligne incertaine."
)

# Le troisième point de ces règles vient d'un défaut réel : le 20/08/2026, 119
# lignes de tableau de financement (« CD30 8 800,00 € ») avaient été publiées
# comme délibérations, dont une en première page du site.

GABARITS = {
    "flux": (
        '{"flux": [{"type": "subvention|bail|cession|dotation|participation", '
        '"year": 2026, "amount": 1200.0, "sens": "verse|recu", '
        '"tiers_nom": "nom du bénéficiaire ou du payeur", '
        '"description": "objet en une phrase", "citation": "phrase exacte"}]}',
        "les sommes que la commune verse ou reçoit, effectivement décidées",
    ),
    "acte": (
        '{"acte": [{"date": "2026-04-27", "title": "objet de la délibération", '
        '"citation": "phrase exacte"}]}',
        "les délibérations soumises au vote",
    ),
    "marche": (
        '{"marche": [{"objet": "objet du marché", "acheteur_nom": "acheteur", '
        '"titulaire_nom": "entreprise retenue", "montant": 12345.0, '
        '"date_notif": "2026-04-27", "citation": "phrase exacte"}]}',
        "les marchés attribués à une entreprise nommée",
    ),
    "budget_vote": (
        '{"budget_vote": [{"year": 2026, "agregat": "intitulé de la ligne", '
        '"value": 2459773.03, "scope": "principal ou budget annexe", '
        '"citation": "phrase exacte"}]}',
        "les montants du budget primitif voté",
    ),
}

# ─── Taille des tranches ──────────────────────────────────────────────────────
# Mesuré au banc d'essai le 21/08/2026, et c'est un piège coûteux.
#
# Ollama sert ses modèles avec 8192 tokens de contexte par DÉFAUT, quelle que
# soit la fenêtre annoncée du modèle. Une tranche de 24 000 caractères français
# pèse 7 à 9 k tokens : ajoutée au prompt système et à la place réservée pour la
# réponse, elle déborde. Ollama tronque alors SANS RIEN DIRE — et ce qui saute
# en premier, c'est la consigne. Résultat mesuré sur deux vrais procès-verbaux :
# qwen2.5:14b ne trouvait plus rien dans le PV de 45 000 caractères, et
# gemma4:26b ne rendait plus de JSON exploitable du tout. Aucune erreur nulle
# part : deux modèles muets qu'on aurait pu croire mauvais.
#
# 10 000 caractères ≈ 3 000 tokens laissent de la place au système, au gabarit et
# à 2 048 tokens de réponse dans une fenêtre de 8 k. Un tableau chiffré pèse plus
# lourd en tokens qu'une phrase : la marge est là pour lui.
#
# Réglable pour qui sert un modèle à grande fenêtre — mais ce n'est pas au
# dispositif de le supposer.
# Le séparateur de milliers n'est pas cosmétique : `verifier_generique` cherche
# les codes INSEE écrits en dur, et « 10000 » a la forme de l'un d'eux. Un
# vérificateur qu'on apprend à ignorer ne vérifie plus rien.
TAILLE_TRANCHE = int(os.environ.get("IA_TAILLE_TRANCHE") or 10_000)
CHEVAUCHEMENT = 1_000

# Budget de réponse. Généreux à dessein : un modèle à raisonnement le dépense
# d'abord à réfléchir, et s'il n'en reste plus, il rend un contenu VIDE sans
# qu'aucune erreur ne le dise (cf. ReponseSansContenu). 2 048 suffisaient à un
# modèle ordinaire, et laissaient gemma4:26b muet sur les cinq tranches d'un
# procès-verbal.
MAX_TOKENS = int(os.environ.get("IA_MAX_TOKENS") or 4_096)


def tranches(texte: str) -> list[str]:
    if len(texte) <= TAILLE_TRANCHE:
        return [texte]
    morceaux, debut = [], 0
    while debut < len(texte):
        fin = min(debut + TAILLE_TRANCHE, len(texte))
        # Couper sur un saut de ligne plutôt qu'au milieu d'un mot : une
        # délibération coupée en deux devient deux délibérations imaginaires.
        if fin < len(texte):
            coupe = texte.rfind("\n", debut + TAILLE_TRANCHE // 2, fin)
            if coupe > 0:
                fin = coupe
        morceaux.append(texte[debut:fin])
        if fin >= len(texte):
            break
        debut = max(fin - CHEVAUCHEMENT, debut + 1)
    return morceaux


class ReponseSansContenu(RuntimeError):
    """Le modèle a répondu 200, mais sans texte exploitable.

    Diagnostiqué au banc du 21/08/2026, et c'est un piège coûteux : gemma4:26b
    est un modèle À RAISONNEMENT. Sa réponse porte DEUX champs — `reasoning`,
    où il réfléchit, et `content`, où il répond. Sur une extraction longue, tout
    le budget `max_tokens` part dans le raisonnement et `content` revient VIDE,
    avec un HTTP 200 et un `finish_reason` normal. Rien ne signale l'anomalie :
    on croit tenir un modèle incapable de produire du JSON, alors qu'il n'a
    simplement pas eu la place de conclure.
    """


def contenu_openai(charge: dict) -> str:
    """Texte d'une réponse « chat completions », ou une erreur qui dit pourquoi.

    Renvoyer une chaîne vide serait le pire choix : elle traverse tout le
    dispositif en silence et ressort en « aucune proposition », qui ressemble à
    un procès-verbal sans flux financier.
    """
    choix = (charge.get("choices") or [{}])[0]
    message = choix.get("message") or {}
    contenu = (message.get("content") or "").strip()
    if contenu:
        return contenu

    raisonnement = (message.get("reasoning")
                    or message.get("reasoning_content") or "").strip()
    if raisonnement:
        raise ReponseSansContenu(
            "modèle à raisonnement : le budget de tokens est parti dans son "
            "raisonnement, il n'est pas arrivé à la réponse. Augmenter "
            "IA_MAX_TOKENS, ou choisir un modèle sans raisonnement pour "
            "l'extraction.")
    if choix.get("finish_reason") == "length":
        raise ReponseSansContenu(
            "réponse coupée par la limite de tokens — augmenter IA_MAX_TOKENS.")
    raise ReponseSansContenu("le modèle a répondu sans aucun texte.")


def json_du_modele(reponse: str) -> dict:
    """Récupère l'objet JSON d'une réponse, même entourée de bavardage.

    Les fournisseurs qui ignorent `response_format` encadrent volontiers leur
    JSON de ```json … ``` ou d'une phrase d'introduction. Refuser ces
    réponses-là reviendrait à n'accepter que certains modèles — exactement ce
    que le dispositif s'interdit.
    """
    texte = (reponse or "").strip()
    if texte.startswith("```"):
        texte = re.sub(r"^```[a-z]*\s*|\s*```$", "", texte, flags=re.I | re.S)
    debut, fin = texte.find("{"), texte.rfind("}")
    if debut < 0 or fin <= debut:
        return {}
    try:
        return json.loads(texte[debut:fin + 1])
    except json.JSONDecodeError:
        return {}


def _aplatir(s: str) -> str:
    """Forme comparable : sans accents, sans ponctuation, espaces normalisés.

    Les accents sont RÉDUITS, pas supprimés. Sans cette étape, « aménagement »
    devenait « am nagement » — la lettre accentuée n'étant pas dans [a-z] — et
    un modèle qui écrit « amenagement » sans accent, ce qui est courant, se
    voyait accusé d'avoir inventé sa citation. Accuser à tort est aussi grave
    que laisser passer : dans les deux cas on cesse de croire le contrôle.
    """
    s = unicodedata.normalize("NFD", (s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def citation_presente(citation: str, texte: str) -> bool:
    """La phrase citée figure-t-elle vraiment dans le document ?

    Comparaison sur une forme aplatie : l'extraction d'un PDF laisse des
    césures, des espaces doubles et des retours à la ligne au milieu des
    phrases, qu'un modèle recopie proprement sans pour autant inventer. On exige
    une correspondance sur un fragment significatif, pas à la virgule près.

    Le seuil de 15 caractères écarte les citations trop courtes pour prouver
    quoi que ce soit : « 1 200 € » se retrouve dans n'importe quel PV.
    """
    aplatie = _aplatir(citation)
    if len(aplatie) < 15:
        return False
    return aplatie in _aplatir(texte)


def message_extraction(objet: str, tranche: str) -> str:
    forme, quoi = GABARITS[objet]
    return (f"Extrais {quoi} du procès-verbal ci-dessous.\n"
            f"Réponds exactement dans cette forme :\n{forme}\n\n"
            f"PROCÈS-VERBAL :\n{tranche}")


def extraire(texte: str, objet: str, appel: Callable[..., str]) -> dict:
    """Propose des lignes pour `objet`, lues dans `texte`.

    `appel(message, system=…, max_tokens=…, json_strict=…) -> str` : le modèle,
    quel qu'il soit. Ce module n'en connaît aucun.
    """
    if objet not in GABARITS:
        raise ValueError(f"objet inconnu : {objet} — {', '.join(GABARITS)}")

    morceaux = tranches(texte)
    propositions: list[dict] = []
    reponses_illisibles = 0
    motifs: list[str] = []
    for tranche in morceaux:
        try:
            brut = appel(message_extraction(objet, tranche),
                         system=EXTRACTION_SYSTEM, max_tokens=MAX_TOKENS,
                         json_strict=True)
        except ReponseSansContenu as e:
            # Une tranche perdue est signalée avec SON motif. « 5 réponses
            # illisibles » n'apprend rien ; « le modèle n'est pas arrivé à la
            # réponse » se corrige.
            reponses_illisibles += 1
            if str(e) not in motifs:
                motifs.append(str(e))
            continue
        charge = json_du_modele(brut)
        if not charge:
            reponses_illisibles += 1
            motif = "réponse sans objet JSON exploitable"
            if motif not in motifs:
                motifs.append(motif)
            continue
        for ligne in (charge.get(objet) or []):
            if isinstance(ligne, dict):
                propositions.append(ligne)

    for p in propositions:
        p["citation_verifiee"] = citation_presente(p.get("citation", ""), texte)

    verifiees = sum(1 for p in propositions if p["citation_verifiee"])
    return {
        "objet": objet,
        "tranches": len(morceaux),
        "propositions": propositions,
        "citations_verifiees": verifiees,
        "citations_introuvables": len(propositions) - verifiees,
        "reponses_illisibles": reponses_illisibles,
        "motifs_echec": motifs,
    }
