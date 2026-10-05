"""La couverture : ce que le snapshot couvre, source par source, et depuis quand.

`couverture.json` dit pour chaque collecteur sa dernière passe et le rythme
qu'on en attend, et pour chaque période les actes qu'on a — ce que la page
`/couverture` publie pour qu'une lacune se voie au lieu de se deviner.
"""
from __future__ import annotations

from datetime import datetime

# Le rythme attendu de chaque collecteur. La page `/couverture` le publie :
# sans lui, elle jugeait tout le monde au même seuil (45 jours), et la source
# qui bouge le plus — le site municipal, déclaré à 3 jours — était celle que ce
# seuil couvrait le moins.
from collectors.config import STEP_META
from collectors.marches_extraits import releve as releve_extraits
from scripts.snapshot.socle import rows, table_exists, write_json


# Qui peut verser de l'argent public à un acteur, et quels collecteurs le
# relèvent. Une fiche d'association sans subvention du département ne disait
# pas qu'AUCUN collecteur ne lit le département : le lecteur concluait à
# l'absence d'aide, alors qu'il s'agit d'une absence de collecte
# (docs/refonte-du-contenu.md, défaut 4). Publiée une fois ici, pas dans chaque
# fiche : la table est la même pour toutes.
FINANCEURS = (
    ("commune", "La commune", ("cm", "cm_archive", "subv_ouvertes")),
    ("intercommunalite", "L'intercommunalité", ("cc_epci", "subv_ouvertes")),
    ("departement", "Le département", ()),
    ("region", "La région", ("region",)),
    ("etat", "L'État", ("jaune", "subventions")),
)


def financeurs(collecteurs: dict) -> list[dict]:
    """Pour chaque financeur : relevé ou non, et par quoi.

    `releve` : un de ses collecteurs a déjà rapporté quelque chose sur cette
    instance. Sans collecteur, ou sans passe utile, le financeur n'est pas
    relevé — et une fiche qui n'en montre rien ne dit rien de lui.
    """
    sortie = []
    for cle, libelle, noms in FINANCEURS:
        utiles = [n for n in noms if (collecteurs.get(n) or {}).get("a_rapporte")]
        sortie.append({"financeur": cle, "libelle": libelle,
                       "collecteurs": list(noms), "releve": bool(utiles)})
    return sortie


def export_couverture(conn, public_events: list[dict], stats: dict) -> dict:
    """Ce que la collecte couvre, et surtout ce qu'elle ne couvre pas.

    Un observatoire qui n'affiche que ce qu'il sait ressemble à une boîte
    noire : le lecteur ne peut pas distinguer « il ne s'est rien passé en
    2019 » de « nous n'avons pas collecté 2019 ». Publier les trous coûte peu
    et vaut mieux que de paraître complet.

    Trois choses différentes, à ne pas confondre :
      - la PÉRIODE réellement couverte par source ;
      - la FRAÎCHEUR, c'est-à-dire la dernière collecte et son issue ;
      - les EXCLUSIONS délibérées (périmètre, vie privée), qui ne sont pas
        des lacunes mais des choix, et qui sont déjà dans `stats`.
    """
    # La période couverte s'arrête à la date d'arrêt : un concert annoncé pour
    # le 14/11 faisait « couvrir » lasalle.fr jusqu'en novembre, deux mois après
    # la collecte (audit du 24/09/2026). L'agenda à venir est compté à part.
    arret = (stats.get("generated_at") or datetime.now().isoformat())[:10]
    par_source: dict[str, dict] = {}
    for e in public_events:
        src = e.get("source") or "inconnue"
        d = par_source.setdefault(src, {"source": src, "actes": 0,
                                        "debut": None, "fin": None,
                                        "avec_document": 0,
                                        "a_venir": 0, "annonce_jusqu_au": None})
        d["actes"] += 1
        if e.get("document") == "acte":
            d["avec_document"] += 1
        date = e.get("date")
        if date and date[:10] > arret:
            d["a_venir"] += 1
            if d["annonce_jusqu_au"] is None or date > d["annonce_jusqu_au"]:
                d["annonce_jusqu_au"] = date
        elif date:
            if d["debut"] is None or date < d["debut"]:
                d["debut"] = date
            if d["fin"] is None or date > d["fin"]:
                d["fin"] = date

    # Dernier passage de chaque collecteur : un collecteur muet depuis des mois
    # est une lacune en formation, pas encore visible dans les compteurs.
    derniers = {}
    if table_exists(conn, "collector_runs"):
        for r in rows(conn, """
            SELECT collector, status, MAX(started_at) AS dernier,
                   SUM(CASE WHEN status = 'ok' OR items_added > 0 THEN 1 ELSE 0 END)
                       AS passes_utiles
            FROM collector_runs GROUP BY collector
        """):
            derniers[r["collector"]] = {
                "statut": r["status"],
                "dernier": r["dernier"],
                # `statut` est celui de la DERNIÈRE passe : un collecteur
                # incrémental qui n'a rien trouvé de neuf vaut `empty` alors
                # que ses lignes sont publiées — `marches` valait `empty` sur
                # les trois instances à côté de 58 marchés (04/10/2026). Un
                # zéro se juge sur « a déjà rapporté », pas sur la dernière fois.
                "a_rapporte": bool(r["passes_utiles"]),
                # Le seuil vient de la source unique de vérité, jamais d'un
                # nombre écrit dans la page : un collecteur dont on change le
                # rythme change de seuil le jour même.
                "ttl": STEP_META[r["collector"]][0] if r["collector"] in STEP_META else None,
            }

    doc = stats.get("provenance", {}).get("document", {})
    total_actes = sum(doc.values()) or 1

    return {
        "arrete_le": stats.get("generated_at"),
        "sources": sorted(par_source.values(), key=lambda d: -d["actes"]),
        "collecteurs": derniers,
        "financeurs": financeurs(derniers),
        # Ce qui a été lu dans les textes et attend une relecture : des
        # NOMBRES, jamais les lignes (décision 6 du 04/10/2026). C'est ce qui
        # permet à /marches de dire « 77 attributions lues, en attente » au
        # lieu d'un zéro nu. None : aucun rapport n'a jamais été déposé.
        "extraits": {"marches": releve_extraits(conn)},
        # Le chiffre le plus inconfortable du site, donc celui qu'il faut donner
        # en premier : la proportion d'actes dont la pièce elle-même est
        # consultable, par opposition à la page qui la contient.
        "actes_avec_piece": doc.get("acte", 0),
        "actes_total": total_actes,
        "part_avec_piece": round(100 * doc.get("acte", 0) / total_actes, 1),
        "lacunes_connues": [
            {
                "sujet": "Documents des délibérations",
                "etat": "partiel",
                "detail": ("La très grande majorité des actes renvoient vers la page du "
                           "compte rendu qui les contient, et non vers la délibération "
                           "elle-même. Il faut donc chercher le passage dans le document."),
            },
            {
                "sujet": "Mandatures antérieures à 2020",
                "etat": "incomplet",
                "detail": ("L'historique des mandats est lacunaire avant 2020, ce qui empêche "
                           "de dire si une personne était élue à la date d'un versement "
                           "ancien. Les situations concernées sont signalées comme telles."),
            },
            {
                "sujet": "Dirigeants d'associations",
                "etat": "incomplet",
                "detail": ("Aucune source ouverte ne publie les dirigeants d'associations. "
                           "Ceux qui figurent ici proviennent de documents publics les "
                           "nommant, jamais d'un registre exhaustif."),
            },
            {
                "sujet": "Recoupement entre sources",
                "etat": "absent",
                "detail": ("Aucune donnée n'est aujourd'hui confirmée par deux sources "
                           "indépendantes : la chaîne ne sait pas encore le faire."),
            },
        ],
    }


def etape_compteurs_provisoires(out, stats) -> None:
    """`stats.json` tel qu'il est à ce point, premier fichier écrit.

    L'étape `stats` le réécrit en dernier, complet : c'est cette version-là
    qui fait foi. Celle-ci n'a jamais servi qu'à ce qu'un snapshot interrompu
    en porte au moins une — elle ne prouve donc pas qu'un snapshot est entier.
    """
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "stats.json", stats)


def etape_couverture(conn, out, public_events, stats) -> None:
    write_json(out / "couverture.json", export_couverture(conn, public_events, stats))
