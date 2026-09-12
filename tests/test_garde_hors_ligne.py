"""Le dossier remis ne se lit pas comme le site en ligne — et la chaîne le sait.

Entre le 03 et le 11/09/2026, quatre dossiers nationaux ont été livrés avec le
même défaut : les liens internes tombaient sur une liste de fichiers, et le
sélecteur d'exercice du budget ne répondait pas. Le code n'était pas en cause —
le correctif de réactivité du 29/08 était bien dans les quatre bundles. C'est la
CONDITION DE LECTURE qui était fausse.

Le site est écrit en chemins absolus (`href="/argent"`) et son JavaScript les
repose au chargement. Servi par un serveur qui devine l'extension manquante —
celui qu'embarque l'archive — tout marche. Servi par n'importe quel autre, ou
ouvert au double-clic, une moitié tombe. `adapter-static` écrivait `argent.html`,
et `/argent` n'y menait pas.

Deux choses corrigent cela, et ce fichier vérifie qu'elles restent en place :

1. le dossier remis est construit avec `VIGIE_HORS_LIGNE=1`, qui écrit chaque
   route en `argent/index.html` — ce que tout serveur statique sait retrouver ;
2. un contrôle ouvre un vrai navigateur sur l'artefact. Les contrôles qui
   existaient lisaient du texte, et aucun ne pouvait voir ces défauts.

Ce test ne construit rien : il lit la règle là où elle est écrite. Une réécriture
qui la relâcherait sans y penser échoue ici.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAYOUT = ROOT / "public" / "src" / "routes" / "+layout.js"
VITE = ROOT / "public" / "vite.config.js"
PAQUET = ROOT / "public" / "package.json"
CONTROLE = ROOT / "public" / "scripts" / "verifier_hors_ligne.mjs"
CI = ROOT / ".github" / "workflows" / "controles.yml"


def test_la_forme_des_adresses_depend_du_build_et_pas_du_hasard():
    """`trailingSlash` décide de ce qui est écrit sur le disque.

    En ligne, la forme canonique ne bouge pas — c'est celle du sitemap. Hors
    ligne, chaque route devient un répertoire portant son index.
    """
    source = LAYOUT.read_text(encoding="utf-8")
    ligne = re.search(r"^export const trailingSlash = (.+)$", source, re.M)
    assert ligne, "trailingSlash n'est plus déclaré dans +layout.js"
    regle = ligne.group(1)
    assert "__VIGIE_HORS_LIGNE__" in regle, (
        "la forme des adresses ne dépend plus du build : le dossier remis "
        "redeviendrait illisible par un serveur statique ordinaire"
    )
    assert "'always'" in regle, "le dossier hors-ligne n'écrit plus ses routes en répertoires"
    assert "'ignore'" in regle, "le site en ligne a changé de forme d'adresses"


def test_la_constante_vient_de_l_environnement_du_build():
    """Elle ne peut pas se décider à l'exécution : le prérendu nomme les fichiers."""
    source = VITE.read_text(encoding="utf-8")
    assert "__VIGIE_HORS_LIGNE__" in source, "la constante n'est plus posée au build"
    assert "process.env.VIGIE_HORS_LIGNE" in source, (
        "la constante ne vient plus de l'environnement — le portail ne pourrait "
        "plus demander un build de dossier remis"
    )


def test_le_controle_navigateur_est_offert_par_le_paquet():
    paquet = json.loads(PAQUET.read_text(encoding="utf-8"))
    script = paquet["scripts"].get("verifier-hors-ligne")
    assert script, "le contrôle du dossier hors-ligne n'est plus lançable"
    assert "verifier_hors_ligne.mjs" in script
    assert CONTROLE.is_file()


def test_le_controle_eprouve_un_serveur_qui_ne_devine_rien():
    """Éprouver le serveur EMBARQUÉ aurait déclaré sain un dossier qui ne l'est
    que chez lui : c'est lui qui rattrapait les adresses absentes."""
    source = CONTROLE.read_text(encoding="utf-8")
    assert "serveurNu" in source
    assert "file://" in source or "pathToFileURL" in source, (
        "la lecture au double-clic n'est plus éprouvée"
    )
    assert "__sveltekit" in source, (
        "le contrôle ne vérifie plus que la page s'hydrate — une page qui "
        "s'affiche sans répondre repasserait"
    )


def test_un_navigateur_absent_fait_echouer_le_controle():
    """« ✓ 0 pages vérifiées » est plus dangereux qu'une erreur.

    Un contrôle qui se saute tout seul rend un vert qui ne veut rien dire. Celui
    du 23/08/2026 l'a fait devant un répertoire inexistant.
    """
    source = CONTROLE.read_text(encoding="utf-8")
    bloc = source[source.index("function trouverNavigateur"):]
    bloc = bloc[:bloc.index("\n}")]
    assert "process.exit(1)" in bloc, (
        "sans navigateur, le contrôle doit échouer — jamais passer en silence"
    )


def test_la_ci_eprouve_le_dossier_remis_et_pas_le_site_en_ligne():
    """Les deux ne s'écrivent pas pareil : contrôler l'un ne dit rien de l'autre."""
    source = CI.read_text(encoding="utf-8")
    assert "verifier_hors_ligne.mjs" in source, "la CI ne joue plus le contrôle"
    assert "VIGIE_HORS_LIGNE" in source, (
        "la CI éprouve le site en ligne au lieu du dossier remis"
    )
    # Le contrôle pilote Chrome par CDP, et `WebSocket` n'est global qu'à
    # partir de Node 22. Sur Node 20, il échouerait sur une erreur de portée
    # qui n'aurait aucun rapport avec ce qu'il cherche.
    assert 'node-version: "22"' in source or 'node-version: "2' in source
