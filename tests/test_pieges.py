"""Les pièges : ce qui ne doit jamais sortir, semé dans la base, et cherché dehors.

Une revue externe (05/10/2026) a semé trente-deux marqueurs dans la base de la
CI — une naissance dans un titre, un domicile dans l'objet d'un marché, une
piste dans les liens d'une élue, un particulier au registre des installations
classées. Vingt-huit sortaient, et le contrôleur rendait « OK ».

Cet essai refait ce geste à chaque passage. Tout ce qui ne doit pas sortir
porte `PIEGE_` ; ce qui doit sortir porte `TEMOIN_`, pour qu'un snapshot vide ne
passe pas pour un snapshot propre. Un filtre nouveau, une sortie nouvelle : son
piège s'ajoute ICI d'abord, et l'essai échoue tant que le filtre ne tient pas.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from snapshot_reference import ROOT, construire  # noqa: E402

NE = "né le 05/03/1961"


def _pieger_les_textes(racine: Path) -> None:
    """Un dossier et une feuille de séance, relus — et porteurs d'un domicile."""
    dossier = racine / "tests" / "fixtures" / "dossiers" / "eau.md"
    dossier.write_text(
        dossier.read_text(encoding="utf-8")
        + f"\nM. Gaston PIEGE_DOSSIER, {NE}, domicilié 5 rue des Lilas.\n", encoding="utf-8")
    releve = racine / "tests" / "fixtures" / "conseils" / "2021-04-14-cm" / "releve.json"
    r = json.loads(releve.read_text(encoding="utf-8"))
    # Sans chiffre : le vérificateur des feuilles refuse déjà tout nombre absent
    # du procès-verbal, et ce n'est pas lui qu'on éprouve ici.
    r["en_clair"]["apres"]["chapeau"] += " Demande de M. Gaston PIEGE_SEANCE, né à Castres."
    releve.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")


def _pieger_la_base(db: Path) -> None:
    conn = sqlite3.connect(db)

    def un(sql, *p):
        return conn.execute(sql, p).fetchone()[0]

    mairie = un("SELECT id FROM entities WHERE name = 'Mairie d''épreuve'")
    boulangerie = un("SELECT id FROM entities WHERE name = 'Boulangerie d''épreuve'")
    elue = un("SELECT id FROM entities WHERE name = 'Élue de Testonville'")

    # Une piste : l'élue dirigerait la boulangerie, que la commune subventionne.
    conn.execute("INSERT INTO relations (from_id, to_id, relation_type, confidence)"
                 " VALUES (?, ?, 'dirigeant', 'hypothesis')", (elue, boulangerie))
    conn.execute("INSERT INTO financial_flows (from_id, to_id, type, year, amount, description,"
                 " source, confidence) VALUES (?, ?, 'subvention', 2025, 1500,"
                 " 'Subvention TEMOIN_FLUX', 'ofgl', 'verified')", (mairie, boulangerie))
    # Le déport qui l'accompagnerait, dans un acte que rien n'autorise à sortir.
    conn.execute("INSERT INTO events (type, date, title, source, metadata) VALUES"
                 " ('deliberation', '2025-04-02', ?, 'source_inconnue', ?)",
                 (f"Subvention à la Boulangerie — Mme PIEGE_DEPORT, {NE}",
                  json.dumps({"conflit_interet": "Élue de Testonville ne participe pas"})))

    # Un acte publié, lui : le nom reste, la naissance et le domicile non.
    acte = conn.execute(
        "INSERT INTO events (type, date, title, content, source) VALUES ('deliberation',"
        " '2026-02-01', ?, 'Le conseil décide.', 'interieur')",
        (f"Aide à M. Jean TEMOIN_ACTE, {NE}, demeurant 5 rue PIEGE_TITRE",)).lastrowid
    # Une note de travail sur cet acte, sans rien y corriger.
    conn.execute("INSERT INTO annotations (object_type, object_id, review_status, note)"
                 " VALUES ('deliberation', ?, 'retenu', 'voir M. PIEGE_NOTE, 5 rue des Lilas')",
                 (acte,))

    # Le registre des installations classées nomme et situe un particulier.
    conn.execute(
        "INSERT INTO icpe_installations (code_aiot, raison_sociale, insee, commune, adresse,"
        " regime, lat, lng) VALUES ('PIEGE_AIOT', 'PIEGE_ICPE Gaston (élevage)', '99001',"
        " 'Testonville', '5 chemin PIEGE_FERME', 'Enregistrement', 44.1, 3.9)")

    # Des champs courts, écrits par un acheteur, lus dans un PV ou saisis.
    conn.execute(
        "INSERT INTO marches_publics (acheteur_siren, acheteur_nom, titulaire_id, titulaire_nom,"
        " objet, montant, date_notif, lieu_exec, source, confidence) VALUES ('219900010',"
        " 'Testonville', ?, 'Boulangerie d''épreuve', ?, 9000, '2026-03-01', ?, 'DECP',"
        " 'verified')",
        (boulangerie, "TEMOIN_MARCHE — mur de M. Durand, demeurant 5 rue PIEGE_MARCHE",
         "chez M. Durand, domicilié 5 rue PIEGE_LIEU"))
    conn.execute(
        "INSERT INTO approbations_projets (date, objet, montant_ht, citation, source,"
        " confidence) VALUES ('2026-02-01', 'TEMOIN_APPROBATION', 1000, ?, 'CM', 'verified')",
        ("participation de M. Durand, demeurant 5 rue PIEGE_CITATION",))
    conn.execute(
        "INSERT INTO budget_vote (year, agregat, value, note, source) VALUES (2026,"
        " 'fonctionnement', 1000, 'vu avec M. Durand, demeurant 5 rue PIEGE_BUDGET', 'CM')")
    conn.execute(
        "UPDATE relations SET metadata = ? WHERE relation_type = 'maire'",
        (json.dumps({"precision": "élue domiciliée 5 rue PIEGE_LIEN", "birth_year": 1961,
                     "note": "PIEGE_META"}),))
    conn.commit()
    conn.close()


@pytest.fixture(scope="module")
def piege(tmp_path_factory):
    travail = tmp_path_factory.mktemp("pieges")
    out = construire(ROOT, travail, avant_amorcage=_pieger_les_textes,
                     apres_amorcage=_pieger_la_base)
    return out, travail / "moteur" / "db" / "ci.regles.json"


def _textes(out: Path) -> dict[str, str]:
    return {str(f.relative_to(out)): f.read_text(encoding="utf-8", errors="replace")
            for f in sorted(out.rglob("*")) if f.is_file()}


def test_le_snapshot_piege_nest_pas_vide(piege):
    """Sans témoins, « aucun piège dehors » se prouverait en ne publiant rien."""
    textes = _textes(piege[0])
    for temoin, fichier in (("TEMOIN_ACTE", "events.json"), ("TEMOIN_MARCHE", "marches.json"),
                            ("TEMOIN_FLUX", "flows.json"),
                            ("TEMOIN_APPROBATION", "approbations.json")):
        assert temoin in textes[fichier], f"{temoin} absent de {fichier}"


def test_aucun_piege_ne_sort(piege):
    fuites = sorted(nom for nom, texte in _textes(piege[0]).items() if "PIEGE_" in texte)
    assert fuites == [], f"pièges publiés dans : {fuites}"


def test_ni_naissance_ni_piste_ni_note_de_travail(piege):
    out = piege[0]
    tout = "\n".join(_textes(out).values())
    assert "1961" not in tout
    assert json.loads((out / "conflits.json").read_text(encoding="utf-8"))["cas"] == []
    stats = json.loads((out / "stats.json").read_text(encoding="utf-8"))
    assert stats["dossiers"]["donnee_personnelle"] == ["eau"]
    assert len(stats["conseils_en_clair"]["donnee_personnelle"]) == 1


def _controler(dossier: Path, regles: Path) -> dict:
    r = subprocess.run([sys.executable, "scripts/verify_snapshot.py", str(dossier), "--json"],
                       cwd=ROOT, env={**os.environ, "VIGIE_RULES": str(regles)},
                       capture_output=True, text=True)
    return json.loads(r.stdout)


def test_le_controleur_passe_sur_le_snapshot_filtre(piege):
    rapport = _controler(*piege)
    assert rapport["ok"], rapport["rapport"]


def test_le_controleur_refuse_ce_que_le_filtre_aurait_laisse(piege, tmp_path):
    """Le builder défait à la main : le contrôleur, qui ne partage rien avec
    lui, doit le voir seul."""
    out, regles = piege
    fuite = tmp_path / "snap"
    shutil.copytree(out, fuite)
    actes = fuite / "events.json"
    actes.write_text(actes.read_text(encoding="utf-8")
                     .replace("[date masquée]", "05/03/1961")
                     .replace("[domicile masqué]", "5 rue des Lilas"), encoding="utf-8")
    regles_vues = {e["regle"] for e in _controler(fuite, regles)["erreurs"]}
    assert {"date de naissance publiée", "domicile publié"} <= regles_vues, regles_vues
