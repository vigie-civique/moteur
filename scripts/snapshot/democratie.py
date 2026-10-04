"""La vie démocratique : scrutins, intercommunalité, élus, transparence.

Des registres publics — résultats électoraux, répartition des sièges,
Répertoire National des Élus, déclarations HATVP, décisions de justice
administrative. Chaque étape lit ses tables et écrit son fichier.
"""
from __future__ import annotations

from scripts.snapshot.socle import rows, table_exists, write_json


def etape_elections(conn, out) -> dict:
    # ── Lot 2 : élections, fiscalité, élus officiels, urbanisme ───────────
    # Publication arbitrée le 26/07/2026. Aucune de ces sources ne portait de
    # page publique alors qu'elles répondent à des questions de premier plan
    # (« combien ont voté ? », « de combien sont mes impôts ? »).
    elections = {}
    if table_exists(conn, "elections_resultats"):
        elections["resultats"] = rows(conn, """
            SELECT scrutin, tour, date_tour, insee, commune, inscrits, votants,
                   abstentions, exprimes, blancs, nuls,
                   ROUND(100.0*votants/NULLIF(inscrits,0), 2) AS participation_pct
            FROM elections_resultats ORDER BY scrutin, tour, commune
        """)
        elections["listes"] = rows(conn, """
            SELECT scrutin, tour, insee, rang, libelle, libelle_abrege, nuance,
                   tete_de_liste, voix, pct_exprimes, sieges_cm, sieges_cc
            FROM elections_listes ORDER BY scrutin, tour, insee, voix DESC
        """)
    write_json(out / "elections.json", elections)

    return {"elections": elections}
