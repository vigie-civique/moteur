"""Les marchés lus dans les procès-verbaux entrent par l'atelier, jamais d'eux-mêmes.

Relevé à Lasalle le 04/10/2026 : 58 marchés publiés, tous de
l'intercommunalité ; 180 lignes lues dans les PV par un outil d'extraction,
dont 77 pour la commune, dormaient dans un rapport JSON faute de chemin pour
entrer. Ces essais tiennent les quatre promesses de ce chemin :

  - une ligne n'est PROPOSÉE que si sa citation se lit dans son acte ;
  - rien n'atteint `marches_publics` avant qu'un validateur l'accepte ;
  - une ligne acceptée est rattachée à son acte, à sa pièce et à son acheteur ;
  - rejouer le même rapport ne crée aucun doublon, à aucune étape.

La base est celle du schéma réel ; les essais d'API passent par de vrais jetons.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from collectors import marches_extraits as mx
from collectors.config import COMMUNE_SIREN, EPCI_NOM, EPCI_SIREN

TEXTE = ("Le conseil municipal, après en avoir délibéré, décide d'attribuer le "
         "marché de réfection de la toiture de l'école à l'entreprise Toits du "
         "Causse pour un montant de 18 450,00 € HT, au terme d'une procédure adaptée.")
CITATION = ("décide d'attribuer le marché de réfection de la toiture de l'école à "
            "l'entreprise Toits du Causse pour un montant de 18 450,00 € HT")


def _acte(conn, texte=TEXTE, date="2024-03-12", type_="deliberation", doc=True):
    doc_id = None
    if doc:
        doc_id = conn.execute(
            "INSERT INTO raw_documents(source, url, doc_type, sha256, local_path) "
            "VALUES('exemple.invalid', ?, 'pdf', ?, 'raw/pv.pdf')",
            (f"https://exemple.invalid/pv/{date}.pdf", f"sha-{date}-{type_}")).lastrowid
    eid = conn.execute(
        "INSERT INTO events(type, date, title, content, source, source_url, "
        "raw_document_id, cle_acte) VALUES(?,?,?,?,?,?,?,?)",
        (type_, date, "Toiture de l'école : attribution", texte, "exemple.invalid",
         f"https://exemple.invalid/pv/{date}.pdf", doc_id, f"c-{date[:4]}-7")).lastrowid
    conn.commit()
    return eid


def _ligne(eid, **autres):
    ligne = {"event_id": eid, "date": "2024-03-12", "type_acte": "deliberation",
             "titre_acte": "Toiture de l'école", "objet": "Réfection de la toiture de l'école",
             "citation": CITATION, "acheteur_nom": "Commune de Testonville",
             "acheteur_siren": COMMUNE_SIREN, "titulaire": "Toits du Causse",
             "montant": 18450, "devise_base": "HT", "procedure": "adaptée",
             "nature": "travaux", "source_url": "https://exemple.invalid/pv/2024-03-12.pdf",
             "deja_importe": False}
    ligne.update(autres)
    return ligne


@pytest.fixture
def depot(base):
    base.execute("INSERT INTO users(email, password_hash, role) "
                 "VALUES('valid@exemple.fr', 'x', 'validator')")
    auteur = {"id": base.execute("SELECT id FROM users").fetchone()[0],
              "email": "valid@exemple.fr"}

    def deposer(rapport):
        bilan = mx.deposer(base, rapport, auteur, "rapport-essai")
        base.commit()
        return bilan
    return deposer


def _en_attente(conn):
    return conn.execute("SELECT COUNT(*) FROM propositions WHERE nature='marche' "
                        "AND etat='en_attente'").fetchone()[0]


class TestDepot:
    def test_une_ligne_attestee_devient_une_proposition_et_rien_d_autre(self, base, depot):
        eid = _acte(base)
        bilan = depot({"format": mx.FORMAT, "lignes": [_ligne(eid)]})
        assert bilan["proposees"] == 1 and bilan["refusees"] == []
        assert bilan["par_portee"] == {"commune": 1}
        [p] = base.execute("SELECT object_type, object_id, charge, etat FROM propositions")
        assert (p[0], p[1], p[3]) == ("deliberation", eid, "en_attente")
        charge = json.loads(p[2])
        assert charge["citation"] == CITATION and charge["trouvee_dans"] == "acte"
        assert charge["montant_dans_citation"] is True and charge["rapport"] == "rapport-essai"
        # Extraction n'est pas publication : la table des marchés n'a pas bougé.
        assert base.execute("SELECT COUNT(*) FROM marches_publics").fetchone()[0] == 0

    def test_rejouer_le_meme_rapport_ne_propose_rien_de_plus(self, base, depot):
        eid = _acte(base)
        rapport = [_ligne(eid), _ligne(eid, objet="Fourniture de tables", titulaire="Bois d'ici",
                                       montant=None)]
        rapport[1]["citation"] = CITATION       # même acte, autre marché lu
        assert depot(rapport)["proposees"] == 2
        bilan = depot(rapport)
        assert (bilan["proposees"], bilan["deja_proposees"]) == (0, 2)
        assert _en_attente(base) == 2

    def test_la_cle_ignore_la_casse_et_les_blancs_pas_le_montant(self, base, depot):
        eid = _acte(base)
        depot([_ligne(eid)])
        assert depot([_ligne(eid, objet="RÉFECTION  de la toiture de l'école ")])[
            "deja_proposees"] == 1
        # Un autre montant est une autre lecture : à relire.
        assert depot([_ligne(eid, montant=18451)])["proposees"] == 1

    def test_une_ligne_ecartee_n_est_pas_reproposee(self, base, depot):
        eid = _acte(base)
        depot([_ligne(eid)])
        base.execute("UPDATE propositions SET etat='refusee'")
        base.commit()
        assert depot([_ligne(eid)])["deja_proposees"] == 1
        assert _en_attente(base) == 0

    @pytest.mark.parametrize("modif, motif", [
        ({"citation": "le conseil décide d'acheter une pelleteuse neuve pour la voirie"},
         "citation introuvable"),
        ({"citation": "18 450,00 €"}, "citation trop courte"),
        ({"date": "2024-03-13"}, "autre base"),
        ({"event_id": 999999}, "absent de cette base"),
        ({"montant": "beaucoup"}, "montant attendu"),
        ({"acheteur_siren": "12345"}, "SIREN"),
        ({"objet": ""}, "objet : champ obligatoire"),
        ({"devise_base": "HTVA"}, "valeurs admises"),
        # Relecture du 05/10/2026 : `float()` les lit sans erreur, et une charge
        # portant un NaN ne se sérialise plus.
        ({"montant": "nan"}, "montant attendu"),
        ({"montant": float("inf")}, "montant attendu"),
    ])
    def test_ce_qui_ne_s_atteste_pas_est_refuse_avec_sa_raison(self, base, depot, modif, motif):
        eid = _acte(base)
        bilan = depot([_ligne(eid, **modif)])
        assert bilan["proposees"] == 0
        [refus] = bilan["refusees"]
        assert refus["ligne"] == 1 and motif in refus["motif"]

    def test_un_evenement_qui_n_est_pas_un_acte_d_assemblee_est_refuse(self, base, depot):
        eid = _acte(base, type_="marché_public")
        [refus] = depot([_ligne(eid)])["refusees"]
        assert "pas un acte d'assemblée" in refus["motif"]

    def test_la_citation_peut_se_lire_dans_un_autre_acte_de_la_meme_piece(self, base, depot):
        eid = _acte(base, texte="Attribution du marché de la toiture : voir annexe.")
        doc = base.execute("SELECT raw_document_id FROM events WHERE id=?", (eid,)).fetchone()[0]
        base.execute("INSERT INTO events(type, date, title, content, raw_document_id) "
                     "VALUES('conseil_municipal', '2024-03-12', 'Séance', ?, ?)", (TEXTE, doc))
        base.commit()
        assert depot([_ligne(eid)])["proposees"] == 1
        charge = json.loads(base.execute("SELECT charge FROM propositions").fetchone()[0])
        assert charge["trouvee_dans"] == "seance"

    def test_deja_importe_n_est_pas_propose(self, base, depot):
        eid = _acte(base)
        bilan = depot([_ligne(eid, deja_importe=True)])
        assert (bilan["proposees"], bilan["deja_importees"]) == (0, 1)

    def test_les_colonnes_inconnues_sont_nommees_pas_stockees(self, base, depot):
        eid = _acte(base)
        bilan = depot([_ligne(eid, score_llm=0.93)])
        assert bilan["cles_ignorees"] == ["score_llm"]
        charge = json.loads(base.execute("SELECT charge FROM propositions").fetchone()[0])
        assert "score_llm" not in charge

    def test_un_autre_format_est_refuse_entier(self, base, depot):
        with pytest.raises(mx.RapportRefuse):
            depot({"format": "autre-outil/3", "lignes": []})
        with pytest.raises(mx.RapportRefuse):
            depot({"marches": []})

    def test_le_montant_hors_citation_est_signale_pas_refuse(self, base, depot):
        eid = _acte(base)
        depot([_ligne(eid, montant=22140)])
        charge = json.loads(base.execute("SELECT charge FROM propositions").fetchone()[0])
        assert charge["montant_dans_citation"] is False

    @pytest.mark.parametrize("ecrit, lu", [
        ("13 766.98 € TTC", 13766.98),       # la graphie des PV de Lasalle
        ("91 469.50 € HT", 91469.5),
        ("18 450,00 € HT", 18450.0),
        ("1.234 €", 1234.0),                 # trois chiffres : des milliers
        ("1.234.567,89 euros", 1234567.89),
        ("12.5 €", 12.5),
    ])
    def test_un_montant_se_lit_avec_un_point_decimal(self, ecrit, lu):
        from collectors.citations import montants_cites
        assert montants_cites(f"pour un montant de {ecrit} par an") == {lu}


class TestRedecoupage:
    """`events.id` change quand `redecouper_pv` ou une purge refont les actes.
    La clé datée, elle, reste : c'est elle qui tient la ligne à son acte."""

    def _redecouper(self, base, ancien):
        r = base.execute("SELECT type, date, title, content, source, source_url, "
                         "raw_document_id, cle_acte FROM events WHERE id=?", (ancien,)).fetchone()
        base.execute("DELETE FROM events WHERE id=?", (ancien,))
        nouveau = base.execute(
            "INSERT INTO events(type, date, title, content, source, source_url, "
            "raw_document_id, cle_acte) VALUES(?,?,?,?,?,?,?,?)", tuple(r)).lastrowid
        base.commit()
        return nouveau

    def test_un_rapport_regenere_ne_repropose_pas_ce_qui_a_ete_ecarte(self, base, depot):
        eid = _acte(base)
        depot([_ligne(eid)])
        base.execute("UPDATE propositions SET etat='refusee'")
        base.commit()
        nouveau = self._redecouper(base, eid)
        assert nouveau != eid
        assert depot([_ligne(nouveau)])["deja_proposees"] == 1

    def test_une_ligne_en_attente_retrouve_son_acte(self, base, depot):
        eid = _acte(base)
        depot([_ligne(eid)])
        nouveau = self._redecouper(base, eid)
        prop = {"object_id": eid,
                "charge": json.loads(base.execute("SELECT charge FROM propositions").fetchone()[0])}
        assert mx.acte_de_proposition(base, prop)["id"] == nouveau

    def test_sans_cle_datee_l_identifiant_reste_la_reference(self, base, depot):
        eid = _acte(base)
        base.execute("UPDATE events SET cle_acte=NULL")
        base.commit()
        depot([_ligne(eid)])
        assert "acte_cle" not in json.loads(
            base.execute("SELECT charge FROM propositions").fetchone()[0])


class TestSousLesYeux:
    def test_un_marche_deja_en_base_du_meme_acheteur_et_montant_est_signale(self, base):
        base.execute("INSERT INTO marches_publics(acheteur_siren, acheteur_nom, objet, montant, "
                     "date_notif, source, raw_id) VALUES(?, 'Mairie', 'Toiture', 18450.4, "
                     "'2024-03-20', 'atelier:x', 'atelier:x')", (COMMUNE_SIREN,))
        base.commit()
        charge = {"acheteur_siren": COMMUNE_SIREN, "montant": 18450}
        [d] = mx.doublons(base, charge)
        assert d["source"] == "atelier:x"
        assert mx.doublons(base, {**charge, "montant": 9000}) == []
        assert mx.doublons(base, {**charge, "acheteur_siren": EPCI_SIREN}) == []

    def test_le_passage_se_surligne_comme_la_citation_se_controle(self):
        # Sans accents ni apostrophes : `citation_presente` l'accepte, le
        # surlignage doit le retrouver aussi, sur le texte d'origine.
        cite = "decide d attribuer le marche de refection de la toiture"
        e = mx.extrait(TEXTE, cite, marge=20)
        assert e["cite"] == "décide d'attribuer le marché de réfection de la toiture"
        assert e["avant"].startswith("…") and e["apres"].endswith("…")
        assert mx.extrait(TEXTE, "une phrase qui n'y figure pas du tout") is None


def test_le_depot_se_journalise_et_s_archive_par_tout_chemin(base, depot, tmp_path):
    octets = json.dumps([{"x": 1}]).encode()
    chemin = mx.archiver(octets, tmp_path)
    assert chemin.read_bytes() == octets and chemin.parent == tmp_path
    assert mx.archiver(octets, tmp_path) == chemin          # rejouer n'écrit rien de plus
    mx.journaliser(base, {"id": 1, "email": "v"}, "abc", {"lignes": 2, "refusees": ["…"]})
    [j] = base.execute("SELECT action, field, new_value FROM audit_log").fetchall()
    assert (j[0], j[1]) == ("deposer_marches_extraits", "rapport/abc")
    assert "refusees" not in json.loads(j[2])


class TestPortee:
    """L'acheteur donne la portée, jamais l'acte : un acte de l'intercommunalité
    n'est pas un acte de la commune, et inversement."""

    def test_par_le_siren(self):
        assert mx.portee_de(COMMUNE_SIREN, "n'importe quoi") == "commune"
        assert mx.portee_de(EPCI_SIREN + "00012", "") == "intercommunalite"   # un SIRET
        assert mx.portee_de("123456789", "Commune de Testonville") == "autre"

    def test_par_le_nom_a_defaut(self):
        assert mx.portee_de(None, "Mairie de Testonville") == "commune"
        assert mx.portee_de(None, EPCI_NOM) == "intercommunalite"
        assert mx.portee_de(None, "Syndicat des eaux") == "non_etabli"


class TestReleve:
    def test_des_nombres_jamais_des_lignes(self, base, depot):
        assert mx.releve(base)["deposees"] == 0
        eid = _acte(base)
        depot([_ligne(eid), _ligne(eid, acheteur_siren=EPCI_SIREN, acheteur_nom=EPCI_NOM,
                                   montant=9000, objet="Étude")])
        r = mx.releve(base)
        assert r["deposees"] == 2 and r["dernier_depot"]
        assert r["en_attente"]["commune"] == 1 and r["en_attente"]["intercommunalite"] == 1
        assert r["en_attente"]["total"] == 2
        assert not any(isinstance(v, (list, str)) and "Toits" in str(v) for v in r.values())


# ─── Par l'API, avec de vrais comptes ────────────────────────────────────────

MDP = "mot-de-passe-de-test"


@pytest.fixture
def atelier(tmp_path, monkeypatch, schema_sql):
    pytest.importorskip("fastapi", reason="job « tests-deps » : pip install -r requirements.txt")
    from fastapi.testclient import TestClient

    chemin_db = tmp_path / "instance.db"
    conn = sqlite3.connect(chemin_db)
    conn.executescript(schema_sql)
    conn.close()

    import api
    import api_auth
    from collectors import db as db_mod, saisies as saisies_mod
    for module in (api, api_auth, db_mod):
        monkeypatch.setattr(module, "DB_PATH", chemin_db)
    monkeypatch.setattr(saisies_mod, "SAISIES", tmp_path / "saisies.json")
    monkeypatch.setattr(api, "RAPPORTS_EXTRAITS", tmp_path / "extraits")
    monkeypatch.delenv("ADMIN_KEY", raising=False)
    monkeypatch.setattr(api, "ADMIN_KEY", "")
    client = TestClient(api.app)

    def sql(requete, params=()):
        c = sqlite3.connect(chemin_db)
        c.row_factory = sqlite3.Row
        try:
            cur = c.execute(requete, params)
            c.commit()
            return [dict(r) for r in cur.fetchall()]
        finally:
            c.close()

    def compte(email, role):
        sql("INSERT INTO users(email, password_hash, role) VALUES(?,?,?)",
            (email, api_auth._hash_pw(MDP), role))
        j = client.post("/api/auth/login", json={"email": email, "password": MDP}).json()
        return {"Authorization": f"Bearer {j['access_token']}"}

    c = sqlite3.connect(chemin_db)
    eid = _acte(c)
    c.close()
    return {"client": client, "sql": sql, "eid": eid, "tmp": tmp_path,
            "contrib": compte("contrib@exemple.fr", "contributor"),
            "valid": compte("valid@exemple.fr", "validator")}


def _attente(a):
    r = a["client"].get("/api/atelier/propositions?nature=marche", headers=a["valid"])
    assert r.status_code == 200, r.text
    return r.json()["propositions"]


class TestAtelier:
    def test_un_contributeur_ne_depose_pas_un_rapport(self, atelier):
        r = atelier["client"].post("/api/atelier/marches-extraits", headers=atelier["contrib"],
                                   json=[_ligne(atelier["eid"])])
        assert r.status_code == 403

    def test_le_rapport_est_archive_sous_son_empreinte(self, atelier):
        r = atelier["client"].post("/api/atelier/marches-extraits", headers=atelier["valid"],
                                   json={"format": mx.FORMAT, "lignes": [_ligne(atelier["eid"])]})
        assert r.status_code == 201, r.text
        assert r.json()["proposees"] == 1
        archive = atelier["tmp"] / "extraits" / f"{r.json()['rapport']}.json"
        assert json.loads(archive.read_text())["lignes"][0]["citation"] == CITATION

    def test_le_validateur_relit_l_acte_sous_les_yeux(self, atelier):
        atelier["client"].post("/api/atelier/marches-extraits", headers=atelier["valid"],
                               json=[_ligne(atelier["eid"])])
        [p] = _attente(atelier)
        assert p["acte"]["id"] == atelier["eid"] and p["actuel"] == {}
        # Le passage et son contexte, pas le texte entier de l'acte.
        assert "content" not in p["acte"]
        assert p["acte"]["extrait"]["cite"] == CITATION
        assert p["doublons"] == []

    def test_accepter_corrige_et_rattache_a_l_acte_a_la_piece_et_a_l_acheteur(self, atelier):
        c = atelier["client"]
        rapport = [_ligne(atelier["eid"], acheteur_nom="Mairie de Testonville")]
        c.post("/api/atelier/marches-extraits", headers=atelier["valid"], json=rapport)
        [p] = _attente(atelier)
        r = c.post(f"/api/atelier/propositions/{p['id']}/decision", headers=atelier["valid"],
                   json={"accepter": True, "corrections": {"montant": "18 500"}})
        assert r.status_code == 200, r.text
        assert r.json()["etat"] == "acceptee" and r.json()["motif"] == "corrigée : montant"

        [m] = atelier["sql"]("SELECT * FROM marches_publics")
        [acte] = atelier["sql"]("SELECT raw_document_id FROM events WHERE id=?", (atelier["eid"],))
        [commune] = atelier["sql"]("SELECT id FROM entities WHERE name='Commune de Testonville'")
        assert m["event_id"] == atelier["eid"]
        assert m["raw_document_id"] == acte["raw_document_id"]
        assert m["acheteur_id"] == commune["id"] and m["acheteur_siren"] == COMMUNE_SIREN
        assert (m["montant"], m["montant_base"], m["confidence"], m["origine"]) == (
            18500.0, "HT", "confirmed", "atelier")
        # La graphie lue reste celle de la source ; le nom publié sera celui de
        # la fiche (`nommer_acheteurs`), rattachée par le SIREN.
        assert m["acheteur_nom"] == "Mairie de Testonville"
        assert m["date_notif"] == "2024-03-12" and m["titulaire_nom"] == "Toits du Causse"

        # Rejouer : ni le rapport, ni les saisies ne doublent rien.
        r = c.post("/api/atelier/marches-extraits", headers=atelier["valid"], json=rapport)
        assert r.json()["deja_proposees"] == 1
        from collectors import saisies
        assert saisies.import_saisies()["ecrites"] == 0
        assert len(atelier["sql"]("SELECT id FROM marches_publics")) == 1
        assert len(saisies.charger()["saisies"]) == 1

    def test_la_citation_ne_se_corrige_pas(self, atelier):
        c = atelier["client"]
        c.post("/api/atelier/marches-extraits", headers=atelier["valid"], json=[_ligne(atelier["eid"])])
        [p] = _attente(atelier)
        r = c.post(f"/api/atelier/propositions/{p['id']}/decision", headers=atelier["valid"],
                   json={"accepter": True, "corrections": {"citation": "autre chose"}})
        assert r.status_code == 400 and "non corrigeable" in r.text
        assert atelier["sql"]("SELECT id FROM marches_publics") == []

    def test_ecarter_demande_un_motif_et_n_ecrit_rien(self, atelier):
        c = atelier["client"]
        c.post("/api/atelier/marches-extraits", headers=atelier["valid"], json=[_ligne(atelier["eid"])])
        [p] = _attente(atelier)
        url = f"/api/atelier/propositions/{p['id']}/decision"
        assert c.post(url, headers=atelier["valid"], json={"accepter": False}).status_code == 400
        r = c.post(url, headers=atelier["valid"],
                   json={"accepter": False, "motif": "c'est un avenant, pas un marché"})
        assert r.status_code == 200 and r.json()["etat"] == "refusee"
        assert atelier["sql"]("SELECT id FROM marches_publics") == []

    def test_un_contributeur_ne_tranche_pas(self, atelier):
        c = atelier["client"]
        c.post("/api/atelier/marches-extraits", headers=atelier["valid"], json=[_ligne(atelier["eid"])])
        [p] = _attente(atelier)
        r = c.post(f"/api/atelier/propositions/{p['id']}/decision", headers=atelier["contrib"],
                   json={"accepter": True})
        assert r.status_code == 403
        assert atelier["sql"]("SELECT id FROM marches_publics") == []

    def test_corriger_n_est_ouvert_qu_aux_lignes_extraites(self, atelier):
        [u] = atelier["sql"]("SELECT id FROM users WHERE email='contrib@exemple.fr'")
        atelier["sql"]("INSERT INTO entities(type, name, confidence) VALUES('association', 'A', 'verified')")
        atelier["sql"]("INSERT INTO propositions(nature, object_type, object_id, charge, avant, propose_par) "
                       "VALUES('fiche', 'entity', 1, '{\"name\": \"B\"}', '{\"name\": \"A\"}', ?)", (u["id"],))
        [p] = atelier["sql"]("SELECT id FROM propositions")
        r = atelier["client"].post(f"/api/atelier/propositions/{p['id']}/decision",
                                   headers=atelier["valid"],
                                   json={"accepter": True, "corrections": {"name": "C"}})
        assert r.status_code == 400


# ─── Le snapshot : un acheteur, un libellé ──────────────────────────────────

def test_un_acheteur_sans_fiche_est_rattache_par_son_siren():
    from scripts.snapshot.argent import nommer_acheteurs, rattacher_acheteurs
    marches = [
        {"acheteur_id": 8, "acheteur_siren": EPCI_SIREN, "acheteur_nom": "COM COMMUNES ÉPREUVES"},
        {"acheteur_id": None, "acheteur_siren": EPCI_SIREN, "acheteur_nom": "CC Épreuves"},
        {"acheteur_id": None, "acheteur_siren": "", "acheteur_nom": "Syndicat des eaux"},
    ]
    assert rattacher_acheteurs(marches, {EPCI_SIREN: 8}) == 1
    nommer_acheteurs(marches, {8: EPCI_NOM})
    assert {m["acheteur_nom"] for m in marches[:2]} == {EPCI_NOM}
    assert marches[2]["acheteur_id"] is None and marches[2]["acheteur_nom"] == "Syndicat des eaux"
    # Le SIREN a servi de clé ; il n'entre pas dans le format publié.
    assert not any("acheteur_siren" in m for m in marches)


def test_le_collecteur_ne_rattache_plus_un_siren_inconnu_a_l_intercommunalite(base):
    from collectors.marches_publics import acheteur_par_siren
    base.execute("INSERT INTO entities(type, name, confidence) VALUES('business', 'SIAEP', 'verified')")
    sid = base.execute("SELECT id FROM entities WHERE name='SIAEP'").fetchone()[0]
    base.execute("INSERT INTO businesses(entity_id, siren) VALUES(?, '200000001')", (sid,))
    assert acheteur_par_siren(base, "20000000100015") == sid
    assert acheteur_par_siren(base, "999999999") is None
    assert acheteur_par_siren(base, "") is None
    epci = acheteur_par_siren(base, EPCI_SIREN)
    assert base.execute("SELECT name FROM entities WHERE id=?", (epci,)).fetchone()[0] == EPCI_NOM
