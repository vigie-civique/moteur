#!/usr/bin/env python3
"""Vérifie un relevé de séance (« le conseil en clair ») contre ses sources.

    python -m collectors.en_clair.verifier data/conseils/2026-03-04-cc/releve.json

Le relevé est écrit par un LLM ou à la main ; ce script ne fait confiance ni à
l'un ni à l'autre. Il n'écrit rien. Il contrôle :

  1. COMPLÉTUDE  les numéros relevés = les marques d'acte lisibles dans le PV
                 (« Délibération n°N/2026 ») — ni trou, ni doublon, ni ajout ;
  2. BORNES      chaque citation est dans le PV ET entre la marque de son acte
                 et la suivante. Une citation prouve la présence d'une phrase,
                 pas son appartenance (leçon du 15/09) : sans la borne, un acte
                 peut porter la décision de son voisin sans que rien ne bouge ;
  3. MONTANTS    chaque montant déclaré existe dans une source ;
  4. VOTES       pour + contre + abstentions ≤ votants annoncés ;
  5. CALCULS     chaque chiffre dérivé (hausse en %, total) est recalculé ;
  6. EN CLAIR    chaque nombre écrit dans les feuilles figure dans une
                 source ou dans un calcul vérifié. C'est le contrôle qui compte :
                 la rédaction est l'étape où un chiffre s'invente ;
  7. DITS        chaque citation de la feuille « comprendre » est retrouvée mot
                 pour mot dans la portée des actes qu'elle déclare.

Code de sortie 0 si tout passe, 1 sinon — la feuille ne se publie pas en 1.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

_ESPACES = re.compile(r"\s+")
# « 1 590 200 », « 205 628,53 », « 97 606.28 », « 6,59 », « 42 »
_NOMBRE = re.compile(r"\d{1,3}(?:[   ]\d{3})+(?:[,.]\d+)?|\d+(?:[,.]\d+)?")


def _norm(texte: str) -> str:
    texte = texte.replace("’", "'").replace(" ", " ").replace(" ", " ")
    return _ESPACES.sub(" ", texte)


def _cle_nombre(n: str) -> str:
    n = re.sub(r"[   ]", "", n).replace(".", ",")
    return n.rstrip("0").rstrip(",") if "," in n else n


def _nombres(texte: str) -> set[str]:
    """Tous les nombres d'un texte, groupés (« 1 590 200 ») ET nus (« 590 »)."""
    sortie = {_cle_nombre(m) for m in _NOMBRE.findall(texte)}
    sortie |= {_cle_nombre(m) for m in re.findall(r"\d+(?:[,.]\d+)?", texte)}
    return sortie


# ─── Les formules des relevés ─────────────────────────────────────────────────
# « Calculs — recalculés, jamais crus » : chaque nombre calculé d'une feuille
# porte sa formule, rejouée ici. Elle passait par `eval()` avec des `builtins`
# réduits — ce qui n'enferme rien : `().__class__.__base__.__subclasses__()`
# rend tout Python. Or un relevé est RÉDIGÉ à partir de documents que personne
# ne maîtrise, souvent avec un modèle de langage : une phrase glissée dans un
# procès-verbal pouvait devenir une formule, et cette fonction tourne dans
# l'API de l'atelier à chaque affichage de la file.
#
# Une formule est donc LUE (arbre syntaxique) et n'est calculée que si elle ne
# contient que ce dont une formule a besoin : nombres, opérations, comparaisons,
# les six fonctions ci-dessous, la lecture d'un acte (`a['vote']`, `.get('pour')`)
# et le parcours des actes. Rien d'autre n'atteint Python.

class FormuleRefusee(ValueError):
    pass


_FONCTIONS = {"round": round, "sum": sum, "len": len, "min": min, "max": max}
_NOEUDS = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp,
           ast.Constant, ast.Name, ast.Load, ast.Store, ast.Call, ast.Attribute,
           ast.Subscript, ast.Dict, ast.List, ast.Tuple, ast.GeneratorExp, ast.ListComp,
           ast.comprehension,
           ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.USub, ast.UAdd,
           ast.Not, ast.And, ast.Or, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
           ast.In, ast.NotIn)


def calculer(formule: str, valeurs: dict):
    """La valeur d'une formule de relevé, ou `FormuleRefusee`."""
    if len(formule) > 400:
        raise FormuleRefusee("formule trop longue")
    try:
        arbre = ast.parse(formule, mode="eval")
    except SyntaxError as e:
        raise FormuleRefusee(f"formule illisible ({e.msg})")
    fonctions = {**_FONCTIONS, **{n: v for n, v in valeurs.items() if callable(v)}}
    parcours = [c for c in ast.walk(arbre) if isinstance(c, ast.comprehension)]
    if len(parcours) > 2:
        # Trente actes parcourus dix fois de suite, c'est 30^10 tours.
        raise FormuleRefusee("trop de parcours imbriqués")
    locaux = {n.id for c in parcours for n in ast.walk(c.target) if isinstance(n, ast.Name)}
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, _NOEUDS):
            raise FormuleRefusee(f"« {type(noeud).__name__} » n'a pas sa place dans une formule")
        if isinstance(noeud, ast.Name) and (
                noeud.id.startswith("_") or noeud.id not in {*valeurs, *fonctions, *locaux}):
            raise FormuleRefusee(f"nom inconnu : {noeud.id}")
        if isinstance(noeud, ast.Attribute) and noeud.attr != "get":
            raise FormuleRefusee(f"attribut refusé : .{noeud.attr}")
        if isinstance(noeud, ast.Call):
            appelee = noeud.func
            if noeud.keywords or not (
                    (isinstance(appelee, ast.Name) and appelee.id in fonctions)
                    or (isinstance(appelee, ast.Attribute) and appelee.attr == "get")):
                raise FormuleRefusee("appel refusé")
        # `'x' * 10**9` : une chaîne ne se multiplie ni ne s'additionne.
        if isinstance(noeud, ast.BinOp) and any(
                isinstance(c, ast.Constant) and isinstance(c.value, str)
                for c in (noeud.left, noeud.right)):
            raise FormuleRefusee("opération sur un texte")
    try:
        return eval(compile(arbre, "<formule>", "eval"),                    # noqa: S307
                    {"__builtins__": {}}, {**valeurs, **_FONCTIONS})
    except FormuleRefusee:
        raise
    except Exception as e:                                                  # noqa: BLE001
        raise FormuleRefusee(f"calcul impossible ({type(e).__name__} : {e})")


def _jours(a: str, b: str) -> int:
    """Écart en jours entre deux dates ISO — pour un délai calculé, jamais tapé."""
    from datetime import date
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _instance(chemin: Path) -> Path:
    for p in chemin.resolve().parents:
        if (p / "collectors").is_dir():
            return p
    sys.exit(f"Aucune instance du moteur au-dessus de {chemin}.")


def verifier(chemin: Path) -> list[str]:
    releve = json.loads(chemin.read_text())
    inst = _instance(chemin)
    # Une source absente ou illisible est une faute de LA séance, pas une panne
    # du générateur : un cache de texte non porté lors d'un déménagement
    # d'instance (PV-du-04.02.2026.pdf.txt) levait FileNotFoundError, qui
    # arrêtait toute la génération du snapshot au milieu. Sans la pièce rien
    # ne se vérifie : on rend les fautes tout de suite, en nommant le fichier.
    sources, absentes = {}, []
    for k, v in releve["sources"].items():
        try:
            sources[k] = _norm((inst / v).read_text(errors="replace"))
        except OSError as e:
            absentes.append(f"SOURCE « {k} » absente ou illisible : {v} "
                            f"({type(e).__name__}) — la séance ne peut pas être vérifiée")
    if absentes:
        verifier.avis = []
        return absentes
    pv = sources[releve.get("source_actes", "pv")]
    actes = releve["actes"]
    fautes: list[str] = []
    avis: list[str] = []

    # 1. Complétude — les marques d'acte de la pièce principale font foi.
    # Trois façons de marquer un acte, selon ce que la pièce imprime :
    #   marque_acte          « Délibération n°{n}/2026 » — le numéro est lu ;
    #   marque_acte_ordinale une tête répétée (« EXTRAIT DU REGISTRE ») dont la
    #                        k-ième occurrence ouvre l'acte n°k — quand l'OCR
    #                        abîme les numéros mais pas la tête ;
    #   rien                 un compte rendu rédigé : la complétude n'est pas
    #                        vérifiable, et le rapport le DIT.
    marques: dict[int, int] = {}
    if releve.get("marque_acte"):
        motif = re.escape(releve["marque_acte"]).replace(r"\{n\}", r"(\d+)")
        marques = {int(m.group(1)): m.start() for m in re.finditer(motif, pv)}
    elif releve.get("marque_acte_regex"):
        # Une expression dont le premier groupe est le numéro : pour une pièce
        # qui écrit parfois « Délibérations n°20/2026 », au pluriel.
        marques = {int(m.group(1)): m.start()
                   for m in re.finditer(releve["marque_acte_regex"], pv)}
    elif releve.get("marque_acte_ordinale"):
        marques = {k: m.start() for k, m in enumerate(
            re.finditer(releve["marque_acte_ordinale"], pv, re.I), 1)}
    else:
        avis.append("complétude NON vérifiable : la pièce ne marque pas ses actes")
    releves = [a["n"] for a in actes]
    if doublons := {n for n in releves if releves.count(n) > 1}:
        fautes.append(f"COMPLÉTUDE numéros relevés deux fois : {sorted(doublons)}")
    if marques:
        if manquants := sorted(set(marques) - set(releves)):
            fautes.append(f"COMPLÉTUDE actes de la pièce absents du relevé : {manquants}")
        if inventes := sorted(set(releves) - set(marques)):
            fautes.append(f"COMPLÉTUDE actes relevés sans marque dans la pièce : {inventes}")

    # 2. Bornes — la citation tombe entre sa marque et la marque suivante ;
    # sans marques, elle doit au moins se trouver dans la pièce.
    positions = sorted(marques.values())
    for a in actes:
        cit = _norm(a["citation"])
        if a["n"] not in marques:
            if pv.find(cit) == -1:
                fautes.append(f"BORNES n°{a['n']} citation introuvable : « {cit[:70]} »")
            continue
        debut = marques[a["n"]]
        fin = next((p for p in positions if p > debut), len(pv))
        ou = pv.find(cit, debut)
        if ou == -1 and pv.find(cit) == -1:
            fautes.append(f"BORNES n°{a['n']} citation introuvable : « {cit[:70]} »")
        elif ou == -1 or ou >= fin:
            fautes.append(f"BORNES n°{a['n']} citation hors de son acte "
                          f"(elle appartient à un autre) : « {cit[:70]} »")

    # 2 bis. Preuves — ce qu'un acte tire d'une autre pièce que le PV (le vote
    # d'un extrait signé, par exemple) y est cité, littéralement.
    for a in actes:
        for pr in a.get("preuves", []):
            if _norm(pr["citation"]) not in sources[pr["source"]]:
                fautes.append(f"PREUVE n°{a['n']} introuvable dans {pr['source']} : "
                              f"« {pr['citation'][:60]} »")

    # 3. Montants — chacun existe dans une source.
    tous = set().union(*(_nombres(t) for t in sources.values()))
    for a in actes:
        for m in a.get("montants", []):
            if _cle_nombre(m) not in tous:
                fautes.append(f"MONTANT n°{a['n']} « {m} » absent des sources")

    # 4. Votes — jamais plus de voix que de votants.
    # Le nombre de votants peut venir d'une autre pièce que le PV (un extrait
    # signé qui le contredit, par exemple) : la pièce est déclarée et citée.
    votants = releve["seance"].get("votants")
    q = releve["seance"].get("quorum") or (
        {"source": "pv", "citation": releve["seance"]["citation_quorum"]}
        if releve["seance"].get("citation_quorum") else None)
    if q and _norm(q["citation"]) not in sources[q["source"]]:
        fautes.append(f"VOTES le nombre de votants n'est pas cité tel quel "
                      f"dans {q['source']}")
    if votants is None:
        avis.append("votants non déclarés : contrôle des voix sauté")
        votants = 10 ** 6
    alertes = []
    for a in actes:
        v = a.get("vote") or {}
        total = sum(v.get(k, 0) for k in ("pour", "contre", "abstentions"))
        if total > votants:
            alertes.append(f"n°{a['n']} : {total} voix pour {votants} votants")
    # Une incohérence DU PV n'est pas une faute du relevé, si le relevé la dit.
    dite = " ".join(releve.get("anomalies_seance", []))
    for al in alertes:
        n = al.split(" ")[0]
        if n not in dite:
            fautes.append(f"VOTES {al} — incohérence du PV non signalée")

    # 5. Calculs — recalculés, jamais crus.
    unanimes = sum(1 for a in actes if (a.get("vote") or {}).get("unanimite"))
    calcules = set()
    for c in releve.get("calculs", []):
        try:
            obtenu = calculer(c["formule"], {"unanimes": unanimes, "n_actes": len(actes),
                                             "actes": actes, "jours": _jours})
        except FormuleRefusee as e:
            fautes.append(f"CALCUL « {c['dit']} » : formule refusée — {e}")
            continue
        attendu = float(re.sub(r"[ \u00a0\u202f]", "", c["valeur"]).replace(",", "."))
        if abs(float(obtenu) - attendu) > 1e-9:
            fautes.append(f"CALCUL « {c['dit']} » : écrit {c['valeur']}, "
                          f"recalculé {obtenu}")
        calcules.add(_cle_nombre(c["valeur"]))

    # 6. En clair — tout nombre écrit est sourcé ou calculé, et sourcé LÀ OÙ
    # le paragraphe le dit : un petit nombre (« 9 % ») existe toujours quelque
    # part dans un PV de 80 pages, donc l'existence seule ne prouve rien. Un
    # paragraphe qui cite ses actes n'a droit qu'aux nombres de ces actes — de
    # la marque précédente à la suivante, pour garder le débat qui précède la
    # délibération.
    def portee(n: int) -> str:
        if n not in marques:
            return pv            # sans marques, la pièce entière
        debut = marques[n]
        avant = max((p for p in positions if p < debut), default=0)
        fin = next((p for p in positions if p > debut), len(pv))
        return pv[avant:fin]

    # L'en-tête : ce qui précède le premier acte. Un registre d'extraits
    # s'ouvre SUR un acte, et chaque extrait porte son propre cartouche de
    # présences : on lit alors les premiers extraits.
    if positions and positions[0] > 200:
        tete = _nombres(pv[: positions[0]])
    else:
        tete = _nombres(pv[:4000])
    if q:
        tete |= _nombres(sources[q["source"]][:2500])
    # Un paragraphe qui s'appuie sur une AUTRE séance le déclare : source,
    # citation, et portée en caractères après la citation — pas la source
    # entière, sinon le renvoi redevient « le nombre existe quelque part ».
    # Ce que Vigie établit elle-même (la date où l'on a vérifié un site, par
    # exemple) n'est dans aucune pièce : c'est déclaré, et imprimé comme tel.
    for c in releve.get("constats", []):
        calcules |= _nombres(c["valeur"])
        avis.append(f"constat Vigie : {c['dit']} — {c['valeur']}")
    for feuille, bloc in releve["en_clair"].items():
        for texte, cites, ses_renvois in _paragraphes(bloc):
            if cites is not None:
                permis = set().union(set(), *(_nombres(portee(n)) for n in cites)) | calcules
                lieu = f"actes {cites}"
            elif feuille == "apres":
                permis = tete | calcules | {x for x in tous if len(x.split(",")[0]) >= 3}
                lieu = "en-tête du PV"
            else:
                permis = tous | calcules
                lieu = "sources de la séance"
            for r in ses_renvois:
                src = sources[r["source"]]
                cit = _norm(r["citation"])
                ou = src.find(cit)
                if ou == -1:
                    fautes.append(f"RENVOI citation introuvable dans "
                                  f"{r['source']} : « {r['citation'][:60]} »")
                    continue
                # La fenêtre s'ouvre des deux côtés : dans un tableau, le
                # nombre précède souvent son libellé.
                p = r.get("portee", 300)
                permis |= _nombres(src[max(0, ou - p): ou + len(cit) + p])
                lieu += f" + renvoi {r['source']}"
            for n in _NOMBRE.findall(texte):
                if _cle_nombre(n) not in permis:
                    fautes.append(f"EN CLAIR ({feuille}) « {n} » introuvable dans "
                                  f"{lieu} : « {texte[:60]} »")
    # 7. Dits — une parole rapportée l'est mot pour mot, et dans son acte :
    # c'est la phrase qu'on prêterait à quelqu'un, la faute la plus grave.
    # La borne n'est stricte que là où la marque OUVRE à coup sûr un acte
    # entier : la tête répétée d'un recueil d'extraits (« EXTRAIT DU
    # REGISTRE »), où l'exposé suit la marque. Partout ailleurs la parole peut
    # précéder la marque — le débat d'un PV de conseil communautaire vient
    # avant « Délibération n°1/2026 », celui d'un PV municipal avant « après
    # en avoir délibéré » — et la frontière avec l'acte voisin n'est pas
    # lisible : la portée large s'applique.
    ordinale = releve.get("marque_acte_ordinale") or ""
    stricte = bool(ordinale) and "avoir" not in ordinale

    def acte_seul(n: int) -> str:
        if n not in marques or not stricte:
            return portee(n)
        debut = marques[n]
        return pv[debut: next((p for p in positions if p > debut), len(pv))]

    for feuille, bloc in releve["en_clair"].items():
        for d in _cites(bloc):
            cit = _norm(d["citation"])
            lieux = [acte_seul(n) for n in d.get("actes") or []] or [pv]
            if not any(cit in lieu for lieu in lieux):
                ou = "introuvable" if cit not in pv else "hors de ses actes"
                fautes.append(f"DIT ({feuille}) citation {ou} : « {cit[:70]} »")
    verifier.avis = avis
    return fautes


def _cites(bloc):
    """Les paragraphes d'une feuille qui rapportent une citation."""
    if isinstance(bloc, list):
        for x in bloc:
            yield from _cites(x)
    elif isinstance(bloc, dict):
        # Un renvoi porte aussi une citation, mais dans SA source : contrôlé
        # plus haut, il n'est pas une parole de la séance.
        if isinstance(bloc.get("citation"), str) and "source" not in bloc:
            yield bloc
        for x in bloc.values():
            yield from _cites(x)


def _paragraphes(bloc, cites=None, renvois=()):
    """(texte, actes cités ou None, renvois) pour chaque texte d'une feuille.

    Actes et renvois valent pour tout le paragraphe, titre compris."""
    if isinstance(bloc, str):
        yield bloc, cites, renvois
    elif isinstance(bloc, list):
        for x in bloc:
            yield from _paragraphes(x, cites, renvois)
    elif isinstance(bloc, dict):
        cites = bloc.get("actes", cites)
        renvois = bloc.get("renvois", renvois)
        for k, x in bloc.items():
            if k not in ("actes", "renvois", "constats"):
                yield from _paragraphes(x, cites, renvois)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    chemin = Path(sys.argv[1]).expanduser()
    releve = json.loads(chemin.read_text())
    fautes = verifier(chemin)
    print(f"{releve['seance']['assemblee_court']} — {releve['seance']['date']} : "
          f"{len(releve['actes'])} actes relevés")
    for f in fautes:
        print(f"  ✗ {f}")
    for a in releve["actes"]:
        if "anomalie" in a:
            print(f"  ⚠ n°{a['n']} (source) : {a['anomalie']}")
    for an in releve.get("anomalies_seance", []):
        print(f"  ⚠ séance (source) : {an}")
    for av in getattr(verifier, "avis", []):
        print(f"  ℹ {av}")
    print("  ✓ tout est sourcé" if not fautes else f"  {len(fautes)} faute(s) : ne pas publier")
    return 1 if fautes else 0


if __name__ == "__main__":
    raise SystemExit(main())
