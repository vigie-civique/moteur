"""La profondeur de collecte — jusqu'où on descend, commune par commune.

Le périmètre dit QUI est suivi ; la profondeur dit à quel niveau. Les deux
étaient confondus dans un unique registre plat, et tous les collecteurs
bouclaient dessus : les commerces, les associations, les mutations immobilières
et les points d'intérêt des quinze communes de l'intercommunalité entraient au
même titre que ceux de la commune de collecte. Un site communal se retrouvait à
parler surtout d'ailleurs.

Ce qui est verrouillé ici :

  - le DÉFAUT est la règle du moteur, pas une clé à écrire dans chaque
    instance. Une instance qui ne déclare rien collecte sa commune en
    profondeur et le reste en contexte institutionnel ;
  - le registre de RECONNAISSANCE (`COMMUNES`) ne se réduit pas avec la
    profondeur — sans quoi un acte du conseil communautaire portant sur une
    commune membre ne se rattacherait plus à rien ;
  - une commune déléguée suit sa commune de rattachement, jamais l'inverse ;
  - une surcharge fautive s'arrête au chargement, pas à la collecte.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INSTANCE_TEST = Path(__file__).parent / "instance_test.json"


def charger_config(instance: Path):
    """Charge `collectors/config.py` sur une instance donnée, isolément.

    Chargé par chemin sous un nom jetable : le module est déjà importé par le
    reste de la suite sur l'instance factice, et le relire n'est possible qu'en
    dehors de `sys.modules`.
    """
    import os
    ancien = os.environ.get("VIGIE_INSTANCE")
    os.environ["VIGIE_INSTANCE"] = str(instance)
    try:
        spec = importlib.util.spec_from_file_location(
            f"_config_{instance.stem}", ROOT / "collectors" / "config.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if ancien is None:
            os.environ.pop("VIGIE_INSTANCE", None)
        else:
            os.environ["VIGIE_INSTANCE"] = ancien


@pytest.fixture
def instance(tmp_path):
    """Fabrique une instance dérivée de l'instance factice."""
    def _fabriquer(**surcharges):
        data = json.loads(INSTANCE_TEST.read_text(encoding="utf-8"))
        data.update(surcharges)
        chemin = tmp_path / "instance.json"
        chemin.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return chemin
    return _fabriquer


# ── Le défaut ────────────────────────────────────────────────────────────────

def test_sans_declaration_le_fond_est_la_commune_de_collecte(instance):
    """Une instance qui ne dit rien suit sa commune, et elle seule, en profondeur."""
    cfg = charger_config(instance())
    assert cfg.COMMUNES_FOND_INSEE == ["99001"]
    assert cfg.communes_du_step("sirene") == ["99001"]
    assert cfg.communes_du_step("osm") == ["99001"]
    assert cfg.communes_du_step("eau") == ["99001"]


def test_les_steps_institutionnels_couvrent_tout_le_perimetre(instance):
    """Ce qui se décide à plusieurs se collecte partout, C1 compris.

    Le Répertoire National des Élus en est le cas le plus net : les délégués
    communautaires sont élus dans les communes membres. Les en retirer, c'est
    perdre la moitié du conseil communautaire.
    """
    cfg = charger_config(instance())
    assert sorted(cfg.communes_du_step("rne")) == ["99001", "99002", "99003"]
    assert sorted(cfg.communes_du_step("fiscalite")) == ["99001", "99002", "99003"]


def test_le_registre_de_reconnaissance_ne_se_reduit_pas(instance):
    """`COMMUNES` reste le périmètre entier, quelle que soit la profondeur.

    C'est lui que lisent `marches_publics`, `raa_prefecture` et
    `classer_perimetre` pour RATTACHER un acte à une commune. Le réduire avec la
    profondeur ferait tomber en « hors » tout ce que le conseil communautaire
    décide sur ses communes membres.
    """
    cfg = charger_config(instance())
    assert len(cfg.COMMUNES) == 3
    assert len(cfg.COMMUNES_CP) == 2


# ── Codes postaux ────────────────────────────────────────────────────────────

def test_les_cp_interroges_suivent_la_profondeur(instance):
    """RNA et BODACC n'interrogent plus que les CP des communes de fond."""
    cfg = charger_config(instance())
    assert cfg.cp_du_step("rna") == ["99000"]        # celui de Testonville
    assert cfg.cp_du_step("fiscalite") == ["99000", "99010"]


# ── Communes déléguées ───────────────────────────────────────────────────────

def test_une_deleguee_suit_sa_commune_de_rattachement(instance):
    """Ancienville est rattachée à Voisinbourg, qui n'est pas collectée en fond.

    Une fusion ne change pas la profondeur à laquelle on suit un territoire,
    seulement le code sous lequel les répertoires continuent de l'indexer.
    """
    cfg = charger_config(instance())
    assert cfg.communes_du_step("sirene", adresse=True) == ["99001"]
    assert "99004" in cfg.COMMUNES_INSEE_ADRESSE     # toujours reconnue


def test_la_deleguee_entre_en_fond_avec_sa_commune(instance):
    cfg = charger_config(instance(collecte={"fond": ["99001", "99002"]}))
    assert sorted(cfg.communes_du_step("dvf", adresse=True)) == [
        "99001", "99002", "99004"]


# ── Surcharge ────────────────────────────────────────────────────────────────

def test_plusieurs_communes_en_fond(instance):
    """Le cas d'un média qui couvre plusieurs communes du même territoire."""
    cfg = charger_config(instance(collecte={"fond": ["99001", "99003"]}))
    assert sorted(cfg.communes_du_step("rna")) == ["99001", "99003"]
    assert cfg.cp_du_step("rna") == ["99000", "99010"]


def test_un_step_peut_changer_de_profondeur(instance):
    cfg = charger_config(instance(
        collecte={"profondeur_steps": {"dvf": "institution", "rne": "fond"}}))
    assert len(cfg.communes_du_step("dvf")) == 3
    assert cfg.communes_du_step("rne") == ["99001"]
    assert cfg.communes_du_step("sirene") == ["99001"]   # les autres inchangés


# ── Gardes ───────────────────────────────────────────────────────────────────

def test_une_commune_de_fond_hors_registre_arrete_le_chargement(instance):
    """Une commune collectée en profondeur doit d'abord être dans le périmètre.

    Sinon les collecteurs l'interrogent et `classer_perimetre` écarte ensuite
    comme « hors » tout ce qu'ils en ont rapporté : du travail fait, jeté, et
    rien pour le dire.
    """
    with pytest.raises(SystemExit, match="99042"):
        charger_config(instance(collecte={"fond": ["99001", "99042"]}))


def test_un_step_inconnu_dans_la_surcharge_arrete_le_chargement(instance):
    with pytest.raises(SystemExit, match="sirenne"):
        charger_config(instance(
            collecte={"profondeur_steps": {"sirenne": "fond"}}))


def test_une_profondeur_inconnue_arrete_le_chargement(instance):
    with pytest.raises(SystemExit, match="maximale"):
        charger_config(instance(
            collecte={"profondeur_steps": {"dvf": "maximale"}}))


def test_un_step_sans_profondeur_declaree_est_refuse(instance):
    """Un collecteur qui boucle sur des communes doit dire lesquelles."""
    cfg = charger_config(instance())
    with pytest.raises(SystemExit, match="nawak"):
        cfg.communes_du_step("nawak")


# ── Cohérence avec la table des steps ────────────────────────────────────────

def test_les_steps_a_profondeur_existent_dans_run_all():
    """Une faute de frappe dans PROFONDEUR_STEP ne doit pas passer inaperçue.

    Elle produirait un step réglable que personne n'appelle, et un collecteur
    qui continue de tourner à la profondeur qu'il veut.
    """
    # `run_all` importe les quarante collecteurs, donc la lecture des PDF. Le
    # job de tests léger ne les installe pas — la suite ne doit dépendre ni des
    # collecteurs ni de l'API —, `tests-deps` les joue.
    pytest.importorskip("pdfplumber", reason="job « tests-deps »")
    from collectors.config import PROFONDEUR_STEP
    from collectors.run_all import STEPS
    assert set(PROFONDEUR_STEP) <= set(STEPS), (
        f"steps déclarés sans exister : {sorted(set(PROFONDEUR_STEP) - set(STEPS))}")


def test_les_collecteurs_de_fond_ne_bouclent_plus_sur_le_perimetre_entier():
    """Le registre plat ne doit plus servir de cible dans ces collecteurs.

    Contrôle textuel, comme `verifier_generique` : c'est le seul moyen de voir
    qu'un collecteur est retourné au registre entier, la profondeur n'étant
    observable qu'à la collecte.
    """
    fichiers = ["rna.py", "rna_enrich.py", "bodacc.py", "osm.py",
                "education.py", "pop_culture.py", "qualite_eau.py"]
    fautifs = []
    for nom in fichiers:
        texte = (ROOT / "collectors" / nom).read_text(encoding="utf-8")
        for interdit in ("COMMUNES_INSEE", "COMMUNES_CP", "COMMUNES_INSEE_ADRESSE"):
            if interdit in texte:
                fautifs.append(f"{nom} → {interdit}")
    assert not fautifs, "registre entier employé comme cible : " + ", ".join(fautifs)
