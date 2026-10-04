"""Le périmètre : quelles entités ont droit à une fiche, et la base est-elle classée.

C'est la PREMIÈRE étape du snapshot : une base dont aucune entité n'a de
périmètre ne produit pas un site vide, elle produit une erreur
(`PerimetreNonClasse`), avant toute autre lecture.
"""
from __future__ import annotations



# Types d'entités publiés en fiche pour les communes de l'intercommunalité.
# Une mairie, l'EPCI, un syndicat d'eau : ce sont les institutions qui décident,
# elles doivent être identifiables. Pas les entreprises, associations et lieux
# des 14 autres communes — cf. `publiable_dans_perimetre`.
TYPES_INSTITUTIONNELS = {"service"}


def publiable_dans_perimetre(perimetre: str | None, entity_type: str | None,
                             siege_a_l_epci: bool) -> bool:
    """Le périmètre autorise-t-il une FICHE publique pour cette entité ?

    Le site public est celui de la commune. La collecte, elle, porte sur toute
    l'intercommunalité : sur une instance ordinaire la base contient deux à
    quatre fois plus d'entités C2 que de C1. Les publier toutes ferait passer un
    annuaire intercommunal pour l'annuaire communal, et un lecteur croirait que
    la boulangerie d'une commune membre est dans la commune-siège.

    Sont publiées en fiche :
      - C1   tout ce que les autres règles autorisent ;
      - C2   les institutions (mairies, EPCI, syndicats) et les seules
             personnes qui SIÈGENT au conseil communautaire — celles-là votent
             le budget et les compétences qui s'appliquent à la commune, les
             masquer amputerait la chaîne de décision de sa moitié
             intercommunale. En revanche, publier les conseils municipaux
             entiers des autres communes membres serait à la fois hors sujet et
             difficilement justifiable au regard du RGPD : ces élus n'ont
             aucun pouvoir de décision sur la commune ;
      - C3   les institutions supra-communales, même raison ;
      - lien les entités rattachées à un acteur de la commune (SCI d'élus,
             titulaires de marchés) : matériau du graphe d'influence, les
             règles de pertinence existantes s'appliquent inchangées.

    Les données des communes C2 restent publiées de façon AGRÉGÉE
    (`intercommunalite.json`, `fiscalite.json`, `territoire.json`) : comparer
    la commune à ses pairs informe, lister leurs commerces non.

    NULL n'est pas C1. Une entité non classée est une entité dont on ignore si
    elle appartient au territoire : la publier par défaut, c'est publier toute
    l'intercommunalité le jour où le classement n'a pas tourné. Mesuré le
    14/08/2026 sur deux instances neuves : 4 944 fiches publiées au lieu de
    1 807, et un site de commune dont 57 % des fiches relevaient d'une voisine.
    Le classement absent doit produire un site vide et un message, pas un
    annuaire de vallée — `exiger_perimetre_classe()` s'en charge en amont.
    """
    if perimetre in ("C1", "lien"):
        return True
    if perimetre in ("C2", "C3"):
        return entity_type in TYPES_INSTITUTIONNELS or siege_a_l_epci
    return False


class PerimetreNonClasse(RuntimeError):
    """`entities.perimetre` n'a jamais été renseignée sur cette base."""


def exiger_perimetre_classe(conn) -> int:
    """Refuse de construire un snapshot sur une base jamais classée.

    Retourne le nombre d'entités sans périmètre (exclues silencieusement de la
    publication, ce qui est le comportement sûr). Lève si AUCUNE ne l'a : ce
    n'est plus une lacune, c'est une étape qui n'a pas eu lieu, et le snapshot
    produit serait vide sans que rien ne le dise.
    """
    total = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    if not total:
        return 0
    classees = conn.execute(
        "SELECT COUNT(*) FROM entities WHERE perimetre IS NOT NULL").fetchone()[0]
    if not classees:
        raise PerimetreNonClasse(
            f"{total} entités en base, aucune classée par périmètre.\n"
            "  Le snapshot serait vide : sans classement, aucune entité n'est\n"
            "  publiable (et le défaut inverse publierait l'intercommunalité).\n"
            "  Lancer :  python3 scripts/classer_perimetre.py\n"
            "  Le step `perimetre` de `python3 -m collectors.run_all` le fait\n"
            "  en fin de collecte."
        )
    return total - classees


def etape_perimetre(conn) -> dict:
    """Avant toute lecture : une base non classée ne produit pas un snapshot,
    elle produit une erreur. Rend le nombre d'entités sans périmètre, exclues
    de la publication et comptées dans `stats.json`."""
    return {"sans_perimetre": exiger_perimetre_classe(conn)}
