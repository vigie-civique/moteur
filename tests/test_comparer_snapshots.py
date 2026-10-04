"""Le comparateur de snapshots, et l'horloge qui rend une construction rejouable.

Ce que ces tests protègent :
  - deux snapshots ne sont dits identiques que s'ils le sont à l'octet près,
    une fois neutralisés les SEULS champs déclarés volatils ;
  - un écart s'explique : fichiers absents, nouveaux, modifiés ; objets
    ajoutés, retirés, modifiés dans une liste à `id` ; ordre de tri ; premier
    chemin de clé qui diffère ;
  - le comparateur n'importe ni le builder ni le contrôleur ;
  - le builder lit l'heure UNE fois, et on peut la lui donner : deux
    constructions à la même horloge sont identiques octet pour octet.

Tout passe par de vrais répertoires, et la seconde moitié par la vraie base de
la CI et le vrai builder.
"""
from __future__ import annotations

import ast
import filecmp
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import comparer_snapshots as C

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "comparer_snapshots.py"


# ── de vrais répertoires ─────────────────────────────────────────────────────

def _ecrire(racine: Path, rel: str, contenu) -> None:
    f = racine / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(contenu, str):
        f.write_text(contenu, encoding="utf-8")
    else:
        f.write_text(json.dumps(contenu, ensure_ascii=False, indent=2), encoding="utf-8")


def _snapshot(racine: Path, heure: str = "2026-10-04T09:45:04", **remplace) -> Path:
    """Un snapshot réduit, à la forme du vrai : racine, `entite/`, `layers/`,
    `conseils/`, un README. `remplace` substitue le contenu d'un fichier."""
    fichiers = {
        "stats.json": {"generated_at": heure, "entities_public": 2,
                       "exclusions": {"entities": {"hors_perimetre": 1}}},
        "popolo.json": {"@context": "x", "generated_at": heure, "persons": []},
        "actualite.json": {"items": [{"id": 1, "titre": "Budget"}], "total": 1,
                           "arrete_le": heure[:10], "genere_le": heure},
        "couverture.json": {"arrete_le": heure, "sources": []},
        "entities.json": {"entities": [{"id": 1, "name": "Boulangerie", "citations": 2},
                                       {"id": 2, "name": "Mairie", "citations": 0}],
                          "total": 2},
        "entite/1.json": {"id": 1, "name": "Boulangerie"},
        "layers/businesses.geojson": {"type": "FeatureCollection", "features": []},
        "README.md": f"# Données publiques\n\nGénéré le {heure} depuis la base de "
                     "travail, sans la modifier.\n\n## Compteurs\n\n- entités : 2\n",
        "conseils/cm-2026-01-10.html": "<p>Relevé de 3 actes vérifié le 4 octobre 2026 : "
                                       "chaque citation est retrouvée.</p>",
    }
    fichiers.update(remplace)
    for rel, contenu in fichiers.items():
        if contenu is not None:
            _ecrire(racine, rel, contenu)
    return racine


def _modifie(rapport: dict, fichier: str) -> dict:
    [m] = [m for m in rapport["modifies"] if m["fichier"] == fichier]
    return m


def test_deux_snapshots_identiques(tmp_path):
    a, b = _snapshot(tmp_path / "a"), _snapshot(tmp_path / "b")
    r = C.comparer_snapshots(a, b)
    assert r["identiques"] and not r["identiques_apres_neutralisation"]
    assert C.main([str(a), str(b)]) == 0


def test_les_seuls_horodatages_ne_font_pas_un_ecart(tmp_path):
    a = _snapshot(tmp_path / "a")
    b = _snapshot(tmp_path / "b", heure="2026-10-05T23:59:59")
    _ecrire(b, "conseils/cm-2026-01-10.html",
            "<p>Relevé de 3 actes vérifié le 1er novembre 2026 : chaque citation est retrouvée.</p>")
    r = C.comparer_snapshots(a, b)
    assert r["identiques"], r["modifies"]
    # Les fichiers qui ne tiennent que par la neutralisation sont NOMMÉS : la
    # liste des volatils ne couvre que ce qu'elle déclare.
    assert set(r["identiques_apres_neutralisation"]) == {
        "stats.json", "popolo.json", "actualite.json", "couverture.json",
        "README.md", "conseils/cm-2026-01-10.html"}


def test_un_horodatage_non_declare_reste_un_ecart(tmp_path):
    """`generated_at` n'est volatil que là où la liste le dit."""
    a = _snapshot(tmp_path / "a", **{"entities.json": {"generated_at": "2026-10-04T09:00:00"}})
    b = _snapshot(tmp_path / "b", **{"entities.json": {"generated_at": "2026-10-04T10:00:00"}})
    r = C.comparer_snapshots(a, b)
    assert not r["identiques"]
    assert _modifie(r, "entities.json")["ecarts"][0]["chemin"] == "generated_at"


def test_fichiers_absents_et_nouveaux_sous_dossiers_compris(tmp_path):
    a = _snapshot(tmp_path / "a")
    b = _snapshot(tmp_path / "b", **{"entite/1.json": None})
    _ecrire(b, "extrait/7.json", {"texte": "Le conseil décide."})
    _ecrire(b, "manifeste.json", {})
    r = C.comparer_snapshots(a, b)
    assert r["absents"] == ["entite/1.json"]
    assert r["nouveaux"] == ["extrait/7.json", "manifeste.json"]
    assert not r["identiques"] and C.main([str(a), str(b)]) == 1


def test_une_liste_d_objets_a_id_se_compte(tmp_path):
    a = _snapshot(tmp_path / "a")
    b = _snapshot(tmp_path / "b", **{"entities.json": {
        "entities": [{"id": 1, "name": "Boulangerie d'épreuve", "citations": 2},
                     {"id": 3, "name": "Club"}, {"id": 4, "name": "Régie"}],
        "total": 3}})
    m = _modifie(C.comparer_snapshots(a, b), "entities.json")
    [bloc] = m["listes"]
    assert bloc["chemin"] == "entities"
    assert (bloc["ajoutes"], bloc["retires"]) == ([3, 4], [2])
    [objet] = bloc["modifies"]
    assert objet["id"] == 1
    assert objet["ecarts"] == [{"chemin": "entities[id=1].name",
                                "ancien": "Boulangerie", "nouveau": "Boulangerie d'épreuve"}]
    # Le reste du fichier : le premier chemin de clé qui diffère.
    assert m["ecarts"][0] == {"chemin": "total", "ancien": 2, "nouveau": 3}


def test_un_ordre_de_tri_qui_change_est_un_ecart(tmp_path):
    """Les mêmes objets rangés autrement : une comparaison par `id` seule
    dirait « rien n'a changé ». L'ordre fait partie de la sortie."""
    a = _snapshot(tmp_path / "a")
    b = _snapshot(tmp_path / "b", **{"entities.json": {
        "entities": [{"id": 2, "name": "Mairie", "citations": 0},
                     {"id": 1, "name": "Boulangerie", "citations": 2}],
        "total": 2}})
    r = C.comparer_snapshots(a, b)
    [bloc] = _modifie(r, "entities.json")["listes"]
    assert bloc["ordre_change"] and not (bloc["ajoutes"] or bloc["retires"] or bloc["modifies"])
    assert not r["identiques"]


def test_hors_liste_le_premier_chemin_qui_differe(tmp_path):
    a = _snapshot(tmp_path / "a")
    b = _snapshot(tmp_path / "b", **{"stats.json": {
        "generated_at": "2026-10-04T09:45:04", "entities_public": 2,
        "exclusions": {"entities": {"hors_perimetre": 4}}}})
    m = _modifie(C.comparer_snapshots(a, b), "stats.json")
    assert m["ecarts"] == [{"chemin": "exclusions.entities.hors_perimetre",
                            "ancien": 1, "nouveau": 4}]


def test_la_forme_du_json_compte_meme_a_donnees_egales(tmp_path):
    """« Pas un octet » : une indentation, un ordre de clés ou un entier devenu
    flottant ne changent rien pour qui relit le JSON, et sont pourtant des
    écarts de sortie."""
    a = _snapshot(tmp_path / "a")
    b = _snapshot(tmp_path / "b")
    (b / "entite" / "1.json").write_text('{"id":1,"name":"Boulangerie"}', encoding="utf-8")
    (b / "layers" / "businesses.geojson").write_text(
        json.dumps({"features": [], "type": "FeatureCollection"}, indent=2), encoding="utf-8")
    _ecrire(b, "stats.json", {"generated_at": "2026-10-04T09:45:04", "entities_public": 2.0,
                              "exclusions": {"entities": {"hors_perimetre": 1}}})
    r = C.comparer_snapshots(a, b)
    assert _modifie(r, "entite/1.json")["nature"] == "forme"
    assert _modifie(r, "layers/businesses.geojson")["ecarts"][0]["nature"] == "ordre_des_cles"
    assert _modifie(r, "stats.json")["ecarts"] == [
        {"chemin": "entities_public", "ancien": 2, "nouveau": 2.0}]


def test_un_fichier_texte_rend_sa_premiere_ligne_differente(tmp_path):
    a = _snapshot(tmp_path / "a")
    b = _snapshot(tmp_path / "b", heure="2026-10-05T08:00:00")
    (b / "README.md").write_text(
        (b / "README.md").read_text(encoding="utf-8").replace("entités : 2", "entités : 3"),
        encoding="utf-8")
    m = _modifie(C.comparer_snapshots(a, b), "README.md")
    assert m["nature"] == "texte"
    assert (m["premier_ecart"]["ancien"], m["premier_ecart"]["nouveau"]) == (
        "- entités : 2", "- entités : 3")


def test_le_rapport_json_est_complet_et_le_code_de_sortie_juste(tmp_path):
    """`--json` n'est pas un résumé : là où le texte montre trois exemples, il
    rend tous les identifiants."""
    a = _snapshot(tmp_path / "a")
    ajoutes = [{"id": i, "name": f"Acteur {i}"} for i in range(10, 30)]
    b = _snapshot(tmp_path / "b", **{"entities.json": {
        "entities": [{"id": 1, "name": "Boulangerie", "citations": 2},
                     {"id": 2, "name": "Mairie", "citations": 0}, *ajoutes],
        "total": 22}})
    p = subprocess.run([sys.executable, str(SCRIPT), str(a), str(b), "--json"],
                       capture_output=True, text=True)
    assert p.returncode == 1
    r = json.loads(p.stdout)
    [bloc] = _modifie(r, "entities.json")["listes"]
    assert bloc["ajoutes"] == list(range(10, 30))
    assert {v["fichiers"] for v in r["volatils"]} >= {"stats.json", "README.md"}

    texte = subprocess.run([sys.executable, str(SCRIPT), str(a), str(b)],
                           capture_output=True, text=True)
    assert texte.returncode == 1
    assert "20 ajouté(s)" in texte.stdout and "10, 11, 12, …" in texte.stdout

    memes = subprocess.run([sys.executable, str(SCRIPT), str(a), str(a), "--json"],
                           capture_output=True, text=True)
    assert memes.returncode == 0 and json.loads(memes.stdout)["identiques"] is True


def test_un_repertoire_absent_n_est_pas_un_snapshot_identique(tmp_path):
    a = _snapshot(tmp_path / "a")
    assert C.main([str(a), str(tmp_path / "nulle-part")]) == 2


# ── ce que le comparateur a le droit de connaître ────────────────────────────

def test_le_comparateur_n_importe_ni_le_builder_ni_le_controleur():
    """Il juge la sortie du builder : s'il empruntait son code, ou celui du
    contrôleur, un défaut partagé se dirait « identique »."""
    arbre = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    importes = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            importes |= {a.name.split(".")[0] for a in noeud.names}
        elif isinstance(noeud, ast.ImportFrom):
            importes.add((noeud.module or "").split(".")[0])
    assert importes <= set(sys.stdlib_module_names), importes


def test_chaque_volatil_est_declare_une_fois_et_justifie():
    vus = set()
    for v in C.VOLATILS:
        assert v.pourquoi.strip(), f"{v.fichiers} : volatil sans justification"
        assert bool(v.cle) != bool(v.motif), f"{v.fichiers} : une clé OU un motif"
        assert (v.fichiers, v.cle, v.motif) not in vus
        vus.add((v.fichiers, v.cle, v.motif))


# ── l'horloge du builder ─────────────────────────────────────────────────────

def test_l_horloge_se_donne_et_refuse_ce_qu_elle_ne_sait_pas_lire(monkeypatch):
    from scripts.build_public_snapshot import VARIABLE_HORLOGE, jour_utc, lire_horloge
    monkeypatch.delenv(VARIABLE_HORLOGE, raising=False)
    assert abs(lire_horloge() - datetime.now()) < timedelta(seconds=5)

    monkeypatch.setenv(VARIABLE_HORLOGE, "2026-10-04T09:45:04")
    assert lire_horloge() == datetime(2026, 10, 4, 9, 45, 4)
    # L'argument passe avant la variable d'environnement.
    assert lire_horloge("2031-01-02T03:04:05") == datetime(2031, 1, 2, 3, 4, 5)

    # Une heure donnée avec son fuseau revient en heure locale, sans fuseau :
    # `generated_at` garde sa forme.
    avec_fuseau = lire_horloge("2026-10-04T09:45:04+00:00")
    assert avec_fuseau.tzinfo is None
    assert avec_fuseau == datetime(2026, 10, 4, 9, 45, 4, tzinfo=timezone.utc) \
        .astimezone().replace(tzinfo=None)
    # Le jour de SQLite (`date('now')`) est le jour UTC de cet instant.
    assert jour_utc(avec_fuseau) == "2026-10-04"

    with pytest.raises(ValueError, match=VARIABLE_HORLOGE):
        lire_horloge("hier soir")


# ── la vraie base de la CI, le vrai builder ──────────────────────────────────

def _construire(db: Path, out: Path, horloge: str | None) -> Path:
    env = {**os.environ, "VIGIE_INSTANCE": str(ROOT / "tests" / "instance_test.json"),
           "VIGIE_DB": str(db), "VIGIE_RULES": str(db.with_suffix(".regles.json"))}
    env.pop("VIGIE_HORLOGE", None)
    if horloge:
        env["VIGIE_HORLOGE"] = horloge
    # `build_snapshot` et lui seul : `main()` régénère aussi les libellés du
    # site, qu'un test n'a pas à réécrire avec « Testonville ».
    code = ("import sys; sys.path.insert(0, 'scripts'); "
            "import build_public_snapshot as b; from pathlib import Path; "
            f"b.build_snapshot(Path({str(out)!r}))")
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    return out


@pytest.fixture(scope="module")
def base_ci(tmp_path_factory):
    d = tmp_path_factory.mktemp("comparateur")
    db = d / "ci.db"
    env = {**os.environ, "VIGIE_INSTANCE": str(ROOT / "tests" / "instance_test.json"),
           "VIGIE_DB": str(db)}
    env.pop("VIGIE_CI_DOSSIERS", None)
    r = subprocess.run([sys.executable, "tests/amorcer_base_ci.py"], cwd=ROOT, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return d, db


@pytest.fixture(scope="module")
def matin(base_ci):
    d, db = base_ci
    return _construire(db, d / "matin", "2026-10-04T09:45:04")


def _fichiers_differents(a: Path, b: Path) -> list[str]:
    noms = sorted(f.relative_to(a).as_posix() for f in a.rglob("*") if f.is_file())
    assert noms == sorted(f.relative_to(b).as_posix() for f in b.rglob("*") if f.is_file())
    return [n for n in noms if not filecmp.cmp(a / n, b / n, shallow=False)]


def test_a_la_meme_horloge_deux_constructions_sont_identiques_a_l_octet(base_ci, matin):
    d, db = base_ci
    rejoue = _construire(db, d / "matin-rejoue", "2026-10-04T09:45:04")
    assert _fichiers_differents(matin, rejoue) == []
    # Une seule heure pour tous les fichiers d'une construction.
    heures = {json.loads((matin / f).read_text())[cle]
              for f, cle in (("stats.json", "generated_at"), ("popolo.json", "generated_at"),
                             ("actualite.json", "genere_le"), ("couverture.json", "arrete_le"))}
    assert heures == {"2026-10-04T09:45:04"}


def test_deux_heures_du_meme_jour_ne_different_que_par_les_volatils(base_ci, matin):
    """La liste des volatils est COMPLÈTE : rien d'autre ne bouge quand seule
    l'heure change. Si un nouveau fichier se met à porter l'heure, ce test le
    nomme — et il faudra le déclarer, ou cesser de l'y écrire."""
    d, db = base_ci
    soir = _construire(db, d / "soir", "2026-10-04T18:30:05")
    assert _fichiers_differents(matin, soir) == [
        "README.md", "actualite.json", "couverture.json", "manifeste.json",
        "popolo.json", "stats.json"]
    r = C.comparer_snapshots(matin, soir)
    assert r["identiques"], r["modifies"]
    assert sorted(r["identiques_apres_neutralisation"]) == [
        "README.md", "actualite.json", "couverture.json", "manifeste.json",
        "popolo.json", "stats.json"]


def test_une_autre_date_change_la_sortie_et_le_comparateur_le_dit(base_ci, matin):
    """Ce que la date DÉCIDE n'est pas volatil : construit en 2020, le même
    snapshot range tous ses actes « à venir ». L'horloge injectée sert à ne
    PAS comparer deux jours quand on veut comparer deux codes."""
    d, db = base_ci
    autrefois = _construire(db, d / "autrefois", "2020-01-01T08:00:00")
    r = C.comparer_snapshots(matin, autrefois)
    assert not r["identiques"]
    assert {m["fichier"] for m in r["modifies"]} == {"couverture.json", "stats.json"}
    assert {"chemin": "actualite_a_venir", "ancien": 0, "nouveau": 9} in \
        _modifie(r, "stats.json")["ecarts"]


def test_sans_horloge_donnee_c_est_l_heure_qu_il_est(base_ci):
    d, db = base_ci
    avant = datetime.now().replace(microsecond=0)
    maintenant = _construire(db, d / "maintenant", None)
    lue = datetime.fromisoformat(json.loads((maintenant / "stats.json").read_text())["generated_at"])
    assert avant <= lue <= datetime.now()
    assert json.loads((maintenant / "popolo.json").read_text())["generated_at"] == lue.isoformat()
