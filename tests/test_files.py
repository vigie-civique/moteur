"""Les files de travail de l'atelier — `collectors/files.py`.

Trois choses seulement, mais ce sont les trois qui ont déjà coûté cher ailleurs :

1. **Le compte et la liste ne peuvent pas diverger.** Une file qui annonce
   « 12 à faire » et n'en montre que 9 est pire qu'une file absente : on croit
   avoir fini. C'est le défaut des deux scripts jumeaux transposé à l'API — le
   prédicat vit dans `files.py` et l'endpoint le réemploie, ces tests le tiennent.
2. **Un zéro porte sa raison.** Relevé le 23/09/2026 : Lasalle a 87 liens
   présumés, Saillans et Brassac zéro — parce que le détecteur y est passé sans
   rien trouver, pas parce que le travail y est fait. Le relevé doit distinguer
   « mesuré hier, rien » de « jamais mesuré ici ».
3. **Une file mène quelque part.** Chaque route du registre doit correspondre à
   une page du dashboard. Deux des trois files qui existaient avant ce lot
   n'avaient aucune page ou aucune entrée de menu : c'est exactement ce qu'un
   contrôle attrape et qu'une relecture laisse passer.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from collectors.files import (GEO_A_FAIRE, GEO_DEPUIS, RESERVATION_MINUTES,
                              files, geo_params, relever)

ROOT = Path(__file__).resolve().parent.parent
COMMUNE, CP = "Villeneuve-d'Épreuve", "00000"


@pytest.fixture
def registre():
    return files(COMMUNE, CP)


# ── Le registre tient debout sur une base réelle ──────────────────────────────

def test_chaque_requete_du_registre_sexecute(base, registre):
    """Une faute de frappe dans un COUNT ne se voit qu'à l'écran, sinon."""
    for f in registre:
        base.execute(f.reste, f.params).fetchone()
        if f.fait:
            base.execute(f.fait, f.params).fetchone()


def test_une_base_vide_rend_des_zeros_pas_des_erreurs(base, registre):
    releve = relever(base, COMMUNE, CP)
    assert len(releve) == len(registre)
    for ligne in releve:
        assert "indisponible" not in ligne, ligne.get("indisponible")
        assert ligne["reste"] == 0


def test_chaque_file_dit_sa_question_son_geste_et_son_effet(registre):
    for f in registre:
        assert f.question.endswith("?"), f.cle
        assert f.geste and f.effet, f.cle
        # Le rôle est nommé : l'écran doit pouvoir montrer une file fermée
        # plutôt que de la cacher (lot D).
        assert f.role_min in ("contributor", "validator", "admin"), f.cle


def test_chaque_file_mene_a_une_page_qui_existe(registre):
    """Le registre ne pointe jamais vers un 404.

    `/atelier/relations` n'existait pas avant ce lot alors que son API tournait
    depuis des mois : la file était écrite et inatteignable.
    """
    for f in registre:
        page = ROOT / "dashboard" / "src" / "routes" / f.route.lstrip("/") / "+page.svelte"
        assert page.exists(), f"{f.cle} → {f.route} n'a pas de page ({page})"


def test_chaque_file_figure_dans_le_menu_de_latelier(registre):
    """Une file qu'aucun menu ne nomme n'existe pas pour un bénévole.

    `/atelier/geo` a vécu ainsi : page écrite, endpoint écrit, aucune entrée.
    """
    menu = (ROOT / "dashboard" / "src" / "routes" / "atelier"
            / "+layout.svelte").read_text(encoding="utf-8")
    for f in registre:
        assert f"'{f.route}'" in menu, f"{f.cle} → {f.route} absent du menu"


# ── Le compte et la liste ne divergent pas ────────────────────────────────────

def _fiche_geolocalisable(conn, nom, lat, source, score):
    cur = conn.execute(
        "INSERT INTO entities(type, name, commune, confidence, address, "
        "lat, lng, geocode_source, geocode_score) "
        "VALUES('business', ?, ?, 'verified', ?, ?, 3.0, ?, ?)",
        (nom, COMMUNE, f"1 rue du Test, {CP} {COMMUNE}", lat, source, score))
    return cur.lastrowid


def test_le_compte_geo_et_la_liste_geo_sont_le_meme_predicat(base):
    """Le garde-fou du lot B : une seule définition, deux lectures.

    Si quelqu'un réécrit le filtre dans l'endpoint sans toucher au registre, ce
    test tombe — et c'est tout son objet.
    """
    _fiche_geolocalisable(base, "Sans point", None, None, None)        # absent
    _fiche_geolocalisable(base, "Point vague", 44.0, "osm", 0.9)       # approximatif
    _fiche_geolocalisable(base, "Point faible", 44.0, "ban", 0.3)      # approximatif
    _fiche_geolocalisable(base, "Point posé", 44.0, "manual", 1.0)     # fait
    _fiche_geolocalisable(base, "Point sûr", 44.0, "addok", 0.95)      # rien à faire
    base.commit()

    params = geo_params(COMMUNE, CP)
    compte = base.execute(
        f"SELECT COUNT(*) {GEO_DEPUIS} AND {GEO_A_FAIRE}", params).fetchone()[0]
    # La même requête que sert l'endpoint : la colonne `a_faire` de sa liste.
    liste = base.execute(
        f"SELECT COUNT(*) FROM (SELECT CASE WHEN {GEO_A_FAIRE} THEN 1 ELSE 0 END "
        f"AS a_faire {GEO_DEPUIS}) WHERE a_faire = 1", params).fetchone()[0]

    assert compte == liste == 3
    geo = next(f for f in files(COMMUNE, CP) if f.cle == "points-a-situer")
    assert base.execute(geo.reste, geo.params).fetchone()[0] == 3
    assert base.execute(geo.fait, geo.params).fetchone()[0] == 1


def test_un_point_pose_a_la_main_ne_revient_pas_dans_la_file(base):
    """Même avec un mauvais score : un humain est passé, c'est le dernier mot."""
    _fiche_geolocalisable(base, "Posé malgré un score bas", 44.0, "manual", 0.1)
    base.commit()
    geo = next(f for f in files(COMMUNE, CP) if f.cle == "points-a-situer")
    assert base.execute(geo.reste, geo.params).fetchone()[0] == 0


# ── Un zéro porte sa raison ───────────────────────────────────────────────────

def test_un_zero_sans_passe_de_collecte_le_dit(base):
    ligne = next(f for f in relever(base, COMMUNE, CP) if f["cle"] == "relations-presumees")
    assert ligne["reste"] == 0
    assert ligne["derniere_passe"] is None      # jamais mesuré ici


def test_un_zero_mesure_nomme_son_collecteur_et_sa_date(base):
    base.execute("INSERT INTO collector_runs(collector, status, items_added, "
                 "finished_at) VALUES('commissions','empty',0,'2026-09-14 15:33:37')")
    base.commit()
    ligne = next(f for f in relever(base, COMMUNE, CP) if f["cle"] == "relations-presumees")
    assert ligne["reste"] == 0
    assert ligne["derniere_passe"] == {
        "collecteur": "commissions", "issue": "empty",
        "trouve": 0, "le": "2026-09-14 15:33:37"}


def test_la_passe_retenue_est_la_plus_recente(base):
    for le in ("2026-08-01 10:00:00", "2026-09-20 10:00:00", "2026-09-01 10:00:00"):
        base.execute("INSERT INTO collector_runs(collector, status, items_added, "
                     "finished_at) VALUES('web','ok',1,?)", (le,))
    base.commit()
    ligne = next(f for f in relever(base, COMMUNE, CP) if f["cle"] == "sites-candidats")
    assert ligne["derniere_passe"]["le"] == "2026-09-20 10:00:00"


def test_une_passe_inachevee_ne_compte_pas(base):
    """Une collecte encore en vol ne date rien : `finished_at` est NULL."""
    base.execute("INSERT INTO collector_runs(collector, status) VALUES('web','ok')")
    base.commit()
    ligne = next(f for f in relever(base, COMMUNE, CP) if f["cle"] == "sites-candidats")
    assert ligne["derniere_passe"] is None


# ── Ce qui est en cours, et par qui ───────────────────────────────────────────

_n = 0


def _lien_candidat(conn, locked_by=None, minutes=0):
    # Noms uniques : `entities` porte une contrainte UNIQUE(type, name), et
    # trois candidats d'affilée se marchent dessus sinon.
    global _n
    _n += 1
    a = conn.execute("INSERT INTO entities(type, name) VALUES('person', ?)",
                     (f"Alice {_n}",)).lastrowid
    b = conn.execute("INSERT INTO entities(type, name) VALUES('person', ?)",
                     (f"Bruno {_n}",)).lastrowid
    conn.execute(
        "INSERT INTO relation_candidates(from_id, to_id, relation_type, confidence, "
        "signal, score, review_status, locked_by, locked_at) "
        "VALUES(?,?,'membre_commission','probable','commission_pv',50,'pending',?, "
        "CASE WHEN ? IS NULL THEN NULL ELSE datetime('now', ?) END)",
        (a, b, locked_by, locked_by, f"-{minutes} minutes"))


def test_une_reservation_en_cours_dit_qui_et_combien(base):
    _lien_candidat(base, "marie@exemple.fr", minutes=2)
    _lien_candidat(base, "marie@exemple.fr", minutes=1)
    _lien_candidat(base)
    base.commit()
    ligne = next(f for f in relever(base, COMMUNE, CP) if f["cle"] == "relations-presumees")
    assert ligne["reste"] == 3          # réserver n'est pas trancher
    assert ligne["en_cours"] == [{"par": "marie@exemple.fr", "combien": 2,
                                  "depuis": ligne["en_cours"][0]["depuis"]}]


def test_une_reservation_expiree_nest_plus_un_chantier_en_cours(base):
    _lien_candidat(base, "parti@exemple.fr", minutes=RESERVATION_MINUTES + 1)
    base.commit()
    ligne = next(f for f in relever(base, COMMUNE, CP) if f["cle"] == "relations-presumees")
    assert ligne["en_cours"] == []


def test_une_file_sans_table_reservable_ne_rend_rien_en_cours(base):
    ligne = next(f for f in relever(base, COMMUNE, CP) if f["cle"] == "donnees-a-arbitrer")
    assert ligne["en_cours"] == []


# ── Ce qui attend un arbitrage tient compte des décisions déjà prises ─────────

def _marche_probable(conn) -> int:
    """Un marché que la machine n'a pas su affirmer. Le schéma réel exige un
    acheteur et une source : c'est bien pour ça qu'on ne simule pas la base."""
    return conn.execute(
        "INSERT INTO marches_publics(acheteur_siren, acheteur_nom, objet, source, "
        "confidence) VALUES('21000000000000', 'Commune', 'Un marché', "
        "'procès-verbal', 'probable')").lastrowid


def test_une_ligne_tranchee_quitte_la_file_des_chiffres(base):
    mid = _marche_probable(base)
    base.commit()
    reste = lambda: next(f for f in relever(base, COMMUNE, CP)
                         if f["cle"] == "donnees-a-arbitrer")["reste"]
    assert reste() == 1
    base.execute("INSERT INTO annotations(object_type, object_id, review_status) "
                 "VALUES('marche', ?, 'retenu')", (mid,))
    base.commit()
    assert reste() == 0


def test_une_ligne_remise_a_relire_reste_dans_la_file(base):
    """`jamais_relu` vaut absence de décision — cf. `collectors/verdict.py`."""
    mid = _marche_probable(base)
    base.execute("INSERT INTO annotations(object_type, object_id, review_status) "
                 "VALUES('marche', ?, 'jamais_relu')", (mid,))
    base.commit()
    ligne = next(f for f in relever(base, COMMUNE, CP) if f["cle"] == "donnees-a-arbitrer")
    assert ligne["reste"] == 1


def test_une_file_cassee_nemporte_pas_les_autres(base):
    """Une table absente rend `reste: None` — l'écran perd une carte, pas tout."""
    base.execute("DROP TABLE relation_candidates")
    base.commit()
    releve = relever(base, COMMUNE, CP)
    cassee = next(f for f in releve if f["cle"] == "relations-presumees")
    assert cassee["reste"] is None and "indisponible" in cassee
    assert all(f["reste"] is not None for f in releve if f["cle"] != "relations-presumees")


# ── L'endpoint, traversé pour de vrai ─────────────────────────────────────────
# Le relevé peut être juste et l'écran vide quand même : verrou global,
# dépendance d'authentification, sérialisation. On passe par un vrai jeton.

pytest.importorskip("fastapi", reason="job « tests-deps » : pip install -r requirements.txt")

from fastapi.testclient import TestClient  # noqa: E402

MDP = "mot-de-passe-de-test"


@pytest.fixture
def atelier(tmp_path, monkeypatch, schema_sql):
    chemin = tmp_path / "instance.db"
    conn = sqlite3.connect(chemin)
    conn.executescript(schema_sql)
    conn.close()

    import api
    import api_auth
    from collectors import db as db_mod
    for module in (api, api_auth, db_mod):
        monkeypatch.setattr(module, "DB_PATH", chemin)
    monkeypatch.delenv("ADMIN_KEY", raising=False)
    monkeypatch.setattr(api, "ADMIN_KEY", "")
    client = TestClient(api.app)

    def compte(email, role):
        c = sqlite3.connect(chemin)
        c.execute("INSERT INTO users(email, password_hash, role) VALUES(?,?,?)",
                  (email, api_auth._hash_pw(MDP), role))
        c.commit()
        c.close()
        j = client.post("/api/auth/login",
                        json={"email": email, "password": MDP}).json()
        return {"Authorization": f"Bearer {j['access_token']}"}

    return {"client": client, "compte": compte, "chemin": chemin}


def test_lendpoint_rend_toutes_les_files_avec_leur_question(atelier):
    h = atelier["compte"]("val@exemple.fr", "validator")
    r = atelier["client"].get("/api/atelier/files", headers=h)
    assert r.status_code == 200
    corps = r.json()
    assert corps["reservation_minutes"] == RESERVATION_MINUTES
    cles = {f["cle"] for f in corps["files"]}
    assert cles == {f.cle for f in files(COMMUNE, CP)}
    for f in corps["files"]:
        assert f["question"] and f["geste"] and f["effet"] and f["route"]


def test_un_contributeur_voit_les_files_quil_ne_peut_pas_trancher(atelier):
    """Ce qu'un rôle ne peut pas faire doit se VOIR, pas s'apprendre par un 403.

    L'écran s'en sert pour montrer la file sans son bouton — cf. lot D.
    """
    h = atelier["compte"]("contrib@exemple.fr", "contributor")
    r = atelier["client"].get("/api/atelier/files", headers=h)
    assert r.status_code == 200
    roles = {f["cle"]: f["role_min"] for f in r.json()["files"]}
    assert roles["relations-presumees"] == "validator"


def test_les_files_exigent_une_session(atelier):
    assert atelier["client"].get("/api/atelier/files").status_code == 401
