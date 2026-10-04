"""La promotion fonctionne quand les emplacements sont sur des montages distincts.

Sous `atelier.service` et `collecte.service`, `audits`, `dashboard/static` et
`public` sont trois montages « bind » : `rename(2)` entre eux rend `EXDEV`. Or
`basculer` construisait la version neuve dans `audits/versions` puis la mettait
en service par `rename` vers `dashboard/static/public_api` et
`public/static/data` : la promotion était impossible sous l'unité, et n'a réussi
le 04/10/2026 qu'en l'appelant hors du bac à sable.

Ce que ces essais PROUVENT : `basculer` et `revenir_a_la_version_precedente`
ne demandent jamais au noyau un renommage entre deux montages, et gardent les
cinq propriétés de la promotion (version entière servie, contrôle avant service,
échec sans effet, rien de durable là où un build recopie, retour arrière).
Ce qu'ils ne prouvent PAS : que l'unité réelle a bien ces montages-là (cf. la
commande `systemd-run` de la description de la PR), ni le comportement d'un
build SvelteKit pendant l'opération.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from montages import Montages, reloger

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def publication():
    sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location(
        "publication_montages", ROOT / "scripts" / "publication.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def snapshot(dossier: Path, entites, marque="neuf"):
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "entite").mkdir(exist_ok=True)
    (dossier / "stats.json").write_text(json.dumps(
        {"entities_public": len(entites), "marque": marque, "exclusions": {}}),
        encoding="utf-8")
    for i in entites:
        (dossier / "entite" / f"{i}.json").write_text(
            json.dumps({"entity": {"id": i}}), encoding="utf-8")


def marque(dossier: Path) -> str:
    return json.loads((dossier / "stats.json").read_text())["marque"]


def vert(cible):
    return {"ok": True}


def rouge(cible):
    return {"ok": False, "erreurs": ["refusé"]}


def disposer(publication, racine: Path, monkeypatch, montages):
    """L'arbre du serveur sous `racine`, avec les montages de l'unité."""
    lieux = reloger(publication, racine, monkeypatch)
    for m in montages:
        (racine / m).mkdir(parents=True, exist_ok=True)
    return lieux


MONTAGES_DE_L_UNITE = ["audits", "dashboard/static", "public"]


@pytest.fixture
def serveur(publication, tmp_path, monkeypatch):
    racine = tmp_path / "vigie"
    lieux = disposer(publication, racine, monkeypatch, MONTAGES_DE_L_UNITE)
    fs = Montages(racine / m for m in MONTAGES_DE_L_UNITE).installer(monkeypatch)
    snapshot(lieux["PUBLIE"], [1], "en ligne")
    snapshot(lieux["SITE"], [1], "en ligne")
    snapshot(lieux["BROUILLON"], [2, 3], "neuf")
    return lieux, fs


def promouvoir(publication, lieux, controleur=vert):
    a = publication.basculer(lieux["BROUILLON"], lieux["PUBLIE"], controleur)
    b = publication.basculer(lieux["PUBLIE"], lieux["SITE"], controleur)
    return a, b


def test_la_promotion_traverse_les_montages(publication, serveur):
    lieux, _ = serveur
    a, b = promouvoir(publication, lieux)
    assert a["ok"] and b["ok"]
    assert marque(lieux["PUBLIE"]) == "neuf" and marque(lieux["SITE"]) == "neuf"
    # 1. ce qui est servi est entier : tout ce que contient la source, rien d'autre.
    assert sorted(p.name for p in (lieux["SITE"] / "entite").glob("*.json")) \
        == ["2.json", "3.json"]
    assert (lieux["SITE"] / "version.json").is_file()


def test_la_version_precedente_survit_a_la_promotion_et_revient(publication, serveur):
    """5. le retour arrière reste possible — et marche aussi entre montages."""
    lieux, _ = serveur
    promouvoir(publication, lieux)
    _, precedent = publication._voisins(lieux["SITE"])
    assert marque(precedent) == "en ligne"

    publication.revenir_a_la_version_precedente(lieux["SITE"])
    assert marque(lieux["SITE"]) == "en ligne"
    publication.revenir_a_la_version_precedente(lieux["SITE"])
    assert marque(lieux["SITE"]) == "neuf", "revenir deux fois ramène là d'où l'on vient"


def test_un_controle_rouge_laisse_l_ancienne_version_entiere(publication, serveur):
    """2 et 3. rien ne sert avant le contrôle ; un refus n'a pas d'effet."""
    lieux, _ = serveur
    r = publication.basculer(lieux["BROUILLON"], lieux["SITE"], rouge)
    assert not r["ok"]
    assert marque(lieux["SITE"]) == "en ligne"
    assert (lieux["SITE"] / "entite" / "1.json").is_file()


def test_ce_qui_sert_n_est_jamais_une_version_neuve_non_controlee(publication, serveur):
    """2. le contrôle porte sur la version neuve ; il est rendu AVANT toute
    modification du répertoire servi."""
    lieux, _ = serveur
    vus = []

    def espion(cible):
        vus.append(marque(lieux["SITE"]))
        return vert(cible)

    publication.basculer(lieux["BROUILLON"], lieux["SITE"], espion)
    assert vus == ["en ligne"]


def test_un_echec_de_la_mise_en_service_remet_l_ancienne_version(
        publication, serveur, monkeypatch):
    """3. le renommage final échoue (ici, autre chose qu'EXDEV) : l'ancienne
    version est de nouveau servie, entière."""
    lieux, _ = serveur
    vrai = os.rename

    pannes = []

    def casse(src, dst, *a, **kw):
        if Path(dst) == lieux["SITE"] and Path(src).name.endswith(".entrant"):
            pannes.append(src)             # la mise en service échoue, pas la remise
            raise OSError(5, "Input/output error", str(dst))
        return vrai(src, dst, *a, **kw)

    monkeypatch.setattr(os, "rename", casse)
    with pytest.raises(OSError):
        publication.basculer(lieux["BROUILLON"], lieux["SITE"], vert)
    monkeypatch.setattr(os, "rename", vrai)
    assert pannes
    assert marque(lieux["SITE"]) == "en ligne"
    assert (lieux["SITE"] / "entite" / "1.json").is_file()
    assert not (lieux["SITE"].parent.parent / ".bascule").exists()


def test_rien_de_durable_ne_reste_la_ou_un_build_recopie(publication, serveur):
    """4. `public/static/` est recopié par SvelteKit : ni retour arrière ni
    étape transitoire n'y reste. Même chose pour `dashboard/static`, que le
    build de l'atelier recopie."""
    lieux, _ = serveur
    promouvoir(publication, lieux)
    for dest in (lieux["SITE"], lieux["PUBLIE"]):
        assert sorted(p.name for p in dest.parent.iterdir()) == [dest.name], dest
    assert not (lieux["SITE"].parent.parent / ".bascule").exists()


def test_l_etape_transitoire_du_site_est_invisible_d_un_build(
        publication, serveur, monkeypatch):
    """4a. Le build de production (`publier-site.sh`, `npm run build`) ne prend
    aucun verrou du moteur : il peut recopier `public/static/` à n'importe quel
    instant de la promotion. L'étape transitoire du site vit donc HORS de
    `public/static/` — regardé avant chaque renommage et chaque copie."""
    lieux, _ = serveur
    static = lieux["SITE"].parent
    cachees = []
    renommer, copier = os.rename, shutil.copy2

    def regarder():
        cachees.extend(p.name for p in static.iterdir() if p.name.startswith("."))

    def rename_espion(src, dst, *a, **kw):
        regarder()
        return renommer(src, dst, *a, **kw)

    def copy_espion(src, dst, *a, **kw):
        regarder()
        return copier(src, dst, *a, **kw)

    monkeypatch.setattr(os, "rename", rename_espion)
    monkeypatch.setattr(shutil, "copy2", copy_espion)
    publication.basculer(lieux["PUBLIE"], lieux["SITE"], vert)
    assert cachees == [], f"un build concurrent recopierait {cachees}"


def test_un_plantage_pendant_la_copie_laisse_l_ancienne_version_servie(
        publication, serveur, monkeypatch):
    """4b. Processus tué (ici : `KeyboardInterrupt`, que rien n'attrape) alors
    que la version neuve est copiée dans le montage de la destination :
    l'ancienne reste servie, entière ; la publication suivante retire les traces."""
    lieux, _ = serveur
    vrai = publication.empreinte
    monkeypatch.setattr(publication, "empreinte",
                        lambda d: (_ for _ in ()).throw(KeyboardInterrupt("tué"))
                        if ".bascule" in Path(d).parts else vrai(d))
    with pytest.raises(KeyboardInterrupt):
        publication.basculer(lieux["BROUILLON"], lieux["SITE"], vert)
    monkeypatch.setattr(publication, "empreinte", vrai)

    racine = lieux["SITE"].parent.parent
    assert marque(lieux["SITE"]) == "en ligne"
    assert (lieux["SITE"] / "entite" / "1.json").is_file()
    assert list((racine / ".bascule").iterdir()), \
        "l'essai ne simule rien si le plantage ne laisse rien"

    publication.basculer(lieux["BROUILLON"], lieux["SITE"], vert)
    assert marque(lieux["SITE"]) == "neuf"
    assert not (racine / ".bascule").exists()


def test_un_plantage_entre_les_deux_renommages_ne_perd_pas_l_ancienne_version(
        publication, serveur, monkeypatch):
    """4b. Le pire instant : `dest` est écarté, la neuve n'a pas pris sa place.
    L'opération suivante remet l'ancienne AVANT de nettoyer — même si elle est
    refusée par le contrôle."""
    lieux, _ = serveur
    vrai = os.rename

    def tue(src, dst, *a, **kw):
        if Path(dst) == lieux["SITE"]:
            raise KeyboardInterrupt("tué")
        return vrai(src, dst, *a, **kw)

    monkeypatch.setattr(os, "rename", tue)
    with pytest.raises(KeyboardInterrupt):
        publication.basculer(lieux["BROUILLON"], lieux["SITE"], vert)
    monkeypatch.setattr(os, "rename", vrai)
    assert not lieux["SITE"].exists()

    r = publication.basculer(lieux["BROUILLON"], lieux["SITE"], rouge)
    assert not r["ok"]
    assert marque(lieux["SITE"]) == "en ligne"


def test_une_premiere_publication_entre_montages(publication, tmp_path, monkeypatch):
    """Une instance neuve : ni `public/static/` ni `dashboard/static/public_api`."""
    racine = tmp_path / "neuf"
    lieux = disposer(publication, racine, monkeypatch, MONTAGES_DE_L_UNITE)
    Montages(racine / m for m in MONTAGES_DE_L_UNITE).installer(monkeypatch)
    snapshot(lieux["BROUILLON"], [1], "premier")
    a, b = promouvoir(publication, lieux)
    assert a["ok"] and b["ok"] and marque(lieux["SITE"]) == "premier"
    assert a["precedent"] is None


def test_un_snapshot_qui_porte_une_etape_transitoire_est_refuse(publication, tmp_path):
    """4c. Si une étape transitoire se retrouvait publiée, le contrôle la refuse.
    Comparé à un snapshot sain : les autres griefs du contrôle sur un snapshot
    minimal ne comptent pas."""
    spec = importlib.util.spec_from_file_location(
        "verify_snapshot_montages", ROOT / "scripts" / "verify_snapshot.py")
    verif = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verif)

    def erreurs(base):
        rep = verif.Report()
        verif.check_dir(base, rep)
        return set(rep.errors)

    sain = tmp_path / "sain"
    snapshot(sain, [1])
    for nom in (".data.precedent", ".bascule", ".data.neuf"):
        base = tmp_path / nom.strip(".")
        snapshot(base, [1])
        snapshot(base / nom, [1], "ancien")
        neuves = erreurs(base) - erreurs(sain)
        assert any("caché" in e for e in neuves), \
            f"{nom} n'est pas refusé par verify_snapshot : {neuves}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node absent")
def test_un_build_qui_porte_un_repertoire_cache_est_refuse(tmp_path):
    """4c. `verifier_build.mjs`, comme `publier-site.sh`, refuse ce qu'un site
    statique n'a pas à servir : un répertoire caché (sauf `.well-known`)."""
    page = "<html><body>" + "<p>contenu réel de la page</p>" * 400 + "</body></html>"

    def lancer(build):
        return subprocess.run(
            ["node", str(ROOT / "public" / "scripts" / "verifier_build.mjs")],
            cwd=str(tmp_path), env={**os.environ, "VIGIE_BUILD_DIR": str(build)},
            capture_output=True, text=True)

    sain = tmp_path / "sain"
    sain.mkdir()
    (sain / "index.html").write_text(page, encoding="utf-8")
    (sain / ".well-known").mkdir()
    (sain / ".well-known" / "security.txt").write_text("Contact: x", encoding="utf-8")
    assert lancer(sain).returncode == 0, lancer(sain).stderr

    for nom in (".data.precedent", ".bascule"):
        sale = tmp_path / ("sale" + nom)
        shutil.copytree(sain, sale)
        (sale / nom).mkdir()
        (sale / nom / "stats.json").write_text("{}", encoding="utf-8")
        r = lancer(sale)
        assert r.returncode != 0 and nom in r.stderr, (nom, r.stdout, r.stderr)


# ── Dans de vrais montages ───────────────────────────────────────────────────

SCENARIO = textwrap.dedent("""
    import importlib.util, json, subprocess, sys
    from pathlib import Path
    racine = Path(sys.argv[1])
    for m in ("audits", "dashboard/static", "public"):
        subprocess.run(["mount", "--bind", str(racine / m), str(racine / m)], check=True)
    spec = importlib.util.spec_from_file_location("p", sys.argv[2])
    p = importlib.util.module_from_spec(spec); spec.loader.exec_module(p)
    p.ROOT = racine
    p.PUBLIE = racine / "dashboard/static/public_api"
    p.SITE = racine / "public/static/data"
    p.VERSIONS = racine / "audits/versions"
    ok = lambda c: {"ok": True}
    a = p.basculer(racine / "audits/brouillon", p.PUBLIE, ok)
    b = p.basculer(p.PUBLIE, p.SITE, ok)
    p.revenir_a_la_version_precedente(p.SITE)
    print(json.dumps({"a": a["ok"], "b": b["ok"],
                      "site": json.loads((p.SITE / "stats.json").read_text())["marque"]}))
""")


@pytest.mark.skipif(os.geteuid() != 0 or shutil.which("unshare") is None,
                    reason="monter exige root et unshare")
def test_dans_de_vrais_montages(tmp_path):
    racine = tmp_path / "vigie"
    for m in MONTAGES_DE_L_UNITE:
        (racine / m).mkdir(parents=True)
    snapshot(racine / "audits" / "brouillon", [1, 2], "neuf")
    snapshot(racine / "public" / "static" / "data", [1], "en ligne")
    scenario = tmp_path / "scenario.py"
    scenario.write_text(SCENARIO, encoding="utf-8")
    r = subprocess.run(
        ["unshare", "-m", "--propagation", "private", sys.executable,
         str(scenario), str(racine), str(ROOT / "scripts" / "publication.py")],
        capture_output=True, text=True)
    if r.returncode != 0 and ("mount:" in r.stderr or "Operation not permitted" in r.stderr
                              or "permission denied" in r.stderr.lower()):
        pytest.skip(f"l'exécuteur ne laisse pas monter : {r.stderr.strip()[-200:]}")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout.strip().splitlines()[-1]) == \
        {"a": True, "b": True, "site": "en ligne"}
