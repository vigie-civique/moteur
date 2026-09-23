#!/usr/bin/env python3
"""files.py — les files de travail de l'atelier : une question, un geste, un reste.

Posé le 23/09/2026, lot B du chantier « L'atelier du premier jour ».

Jusqu'ici la porte d'entrée de l'atelier était UNE liste de 5 484 fiches
`unverified`, triée par type et par nom, sans fin et sans question. Personne ne
peut commencer par là : rien n'y dit ce qu'on attend de vous, ni combien il
reste, ni si quelqu'un d'autre s'en occupe déjà. Et trois files utiles étaient
DÉJÀ écrites — `/api/candidates`, `/api/atelier/geo-review`,
`/api/atelier/queue/websites` — sans jamais être rassemblées : deux d'entre
elles n'avaient même pas d'entrée dans le menu.

Une file, ici, c'est quatre choses et pas une de plus :

  la QUESTION   ce qu'on demande, en français, à quelqu'un qui n'a pas lu le
                schéma — « Ces deux-là sont-ils vraiment liés ? »
  le GESTE      ce que trancher fait, et ce que ça change sur le site
  le RESTE      combien attendent un geste, maintenant
  l'AVANCEMENT  ce qui est déjà tranché, et ce que quelqu'un a EN COURS

⭐ **Une file vide doit dire POURQUOI elle est vide.** C'est la règle qui a
coûté le plus cher au projet (cf. `feedback-un-zero-qui-vient-dune-absence`), et
elle se pose ici exactement : relevé le 23/09, Lasalle a 87 relations
présumées, Saillans et Brassac en ont ZÉRO — non parce que le travail y est
fait, mais parce que le détecteur `commissions` y est passé et n'a rien trouvé
dans leurs procès-verbaux. Les deux zéros se ressemblent et ne disent pas la
même chose. Chaque file nomme donc les collecteurs qui la remplissent, et le
relevé va lire dans `collector_runs` QUAND ils sont passés pour la dernière
fois et ce qu'ils ont rapporté. Une file vide dont le détecteur n'a jamais
tourné n'est pas une file finie : c'est une file qui n'a jamais été mesurée.

⚖️ **Le prédicat de chaque file vit ICI, et les endpoints le réemploient.** Une
file dont le compte est calculé d'un côté et la liste de l'autre finit par
annoncer « 12 à faire » et n'en montrer que 9 — c'est le défaut des deux scripts
jumeaux (`feedback-deux-scripts-qui-portent-la-meme-cible`), transposé à l'API.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

#: Combien de temps une réservation tient avant de retomber. Une seule valeur :
#: l'API la lit ici pour poser et lever les réservations, le relevé pour dire
#: « en cours ». Les deux ont besoin du MÊME nombre pour ne pas se contredire.
RESERVATION_MINUTES = 10

# ─── Le prédicat de la file géographique ──────────────────────────────────────
# Extrait de `api.geo_review` le 23/09/2026 pour que le compte et la liste aient
# la même définition. `geo_review` construisait son `geo_status` en Python après
# coup ; le voici en SQL, mot pour mot, et l'endpoint le réemploie.
#
# Trois paramètres, dans cet ordre : commune, commune, code postal.
GEO_DEPUIS = """
    FROM entities e
    WHERE e.confidence IN ('verified','confirmed')
      AND e.type IN ('business','association','service','place')
      AND (e.commune = ?
           OR UPPER(e.address) LIKE '%' || UPPER(?) || '%'
           OR e.address LIKE '%' || ? || '%')
      AND e.name NOT LIKE 'Commission %'
      AND e.name NOT LIKE 'Conseil %'
"""

#: L'état géographique d'une fiche, en SQL. `manual` gagne sur `imprecise` —
#: un point posé à la main est le dernier mot, c'est tout l'objet de la file.
#: Un point ABSENT gagne sur tout le reste : il n'y a rien à juger.
GEO_ETAT = """
    CASE
        WHEN e.lat IS NULL THEN 'absent'
        WHEN e.geocode_source = 'manual' THEN 'pose_a_la_main'
        WHEN COALESCE(e.geocode_score, 0) < 0.6
             OR e.geocode_source IS NULL
             OR e.geocode_source IN ('osm','ban') THEN 'approximatif'
        ELSE 'sur'
    END
"""

#: Ce qui attend un geste dans la file géographique.
GEO_A_FAIRE = f"({GEO_ETAT}) IN ('absent','approximatif')"


def geo_params(commune: str, code_postal: str) -> tuple:
    """Les trois paramètres de `GEO_DEPUIS`, dans l'ordre — une seule fois écrit."""
    return (commune, commune, code_postal)


# ─── Ce qui attend un arbitrage, par type d'objet ─────────────────────────────
# Une seule définition, trois lectures : le COMPTE de la carte « Aujourd'hui »,
# la PREMIÈRE ligne qu'ouvre « Commencer », et le RESTE affiché par l'écran de
# décision. Le 23/09/2026, l'écran comptait toutes les lignes de la table — 544
# flux — quand la carte en annonçait 79 : deux définitions du même « à faire »,
# et c'est l'écran qui aurait décidé le bénévole à abandonner.
ECRANS = (
    ("flow", "SELECT id FROM financial_flows "
             "WHERE confidence IN ('probable','hypothesis') "
             "ORDER BY year DESC, amount DESC"),
    ("marche", "SELECT id FROM marches_publics "
               "WHERE confidence IN ('probable','hypothesis') "
               "ORDER BY date_notif DESC"),
)

REQUETE_ECRAN = dict(ECRANS)


@dataclass(frozen=True)
class FileDeTravail:
    """Une file : ce qu'on demande, ce que ça fait, et où on le fait.

    `reste` et `fait` sont des requêtes COUNT complètes. `params` leur est passé
    tel quel — jamais d'interpolation de valeur dans le SQL, même venue de la
    configuration de l'instance.
    """
    cle: str
    titre: str
    question: str
    geste: str
    effet: str          # ce que le geste change sur le site public
    route: str
    role_min: str
    reste: str
    fait: Optional[str] = None
    #: Table portant `locked_by` / `locked_at` — sert à dire qui travaille dessus.
    table: Optional[str] = None
    #: Les steps de collecte qui alimentent la file : d'où vient un zéro.
    steps: tuple[str, ...] = ()
    #: Vraie pour la vue experte : atteignable, mais ce n'est pas par là qu'on
    #: commence. Elle ne se termine jamais — 22 783 fiches — et une file qu'on
    #: ne peut pas finir ne se met pas devant quelqu'un qui arrive.
    experte: bool = False
    params: tuple = ()
    #: Les types d'`annotations` que cette file fait trancher, et la requête qui
    #: rend leurs identifiants dans l'ordre de traitement. Renseignés, le relevé
    #: y cherche la PREMIÈRE ligne non tranchée : c'est ce qui permet à
    #: « Commencer » d'ouvrir un écran de décision plutôt qu'un tableau.
    ecran: tuple[tuple[str, str], ...] = ()


def files(commune: str, code_postal: str) -> tuple[FileDeTravail, ...]:
    """Le registre, construit pour une instance (la file géo a besoin des deux).

    L'ordre est celui de l'écran : ce qui se tranche vite et sans contexte
    d'abord, la vue experte en dernier.
    """
    return (
        FileDeTravail(
            cle="relations-presumees",
            titre="Liens présumés",
            question="Ces deux-là sont-ils vraiment liés ?",
            geste="Confirmer le lien, ou l'écarter",
            effet="Un lien confirmé devient une relation, et peut rendre une "
                  "personne publiable au titre de son mandat.",
            route="/atelier/relations",
            role_min="validator",
            reste="SELECT COUNT(*) FROM relation_candidates "
                  "WHERE review_status = 'pending'",
            fait="SELECT COUNT(*) FROM relation_candidates "
                 "WHERE review_status <> 'pending'",
            table="relation_candidates",
            # `liens` (détection de rapprochements) est câblé depuis le
            # 23/09/2026 seulement : avant, `collectors/detect_links.py`
            # n'était appelé par rien. Une file vide AVANT cette date ne
            # voulait donc pas dire ce qu'elle avait l'air de dire.
            steps=("liens", "commissions", "dir_deports", "dir_web"),
        ),
        FileDeTravail(
            cle="sites-candidats",
            titre="Adresses de sites",
            question="Ce site web est-il bien celui de cet acteur ?",
            geste="Confirmer l'adresse, ou l'écarter",
            effet="Une adresse confirmée s'affiche sur la fiche publique ; "
                  "une adresse écartée n'est plus proposée.",
            route="/atelier/queue/websites",
            role_min="validator",
            reste="SELECT COUNT(*) FROM entity_websites WHERE status = 'candidate'",
            fait="SELECT COUNT(*) FROM entity_websites WHERE status <> 'candidate'",
            table="entity_websites",
            steps=("web",),
        ),
        FileDeTravail(
            cle="points-a-situer",
            titre="Points sur la carte",
            question="Où se trouve exactement ce lieu ?",
            geste="Poser le point à la bonne adresse",
            effet="Le point posé à la main fait autorité : c'est lui qui "
                  "s'affiche sur la carte publique.",
            route="/atelier/geo",
            role_min="validator",
            reste=f"SELECT COUNT(*) {GEO_DEPUIS} AND {GEO_A_FAIRE}",
            fait=f"SELECT COUNT(*) {GEO_DEPUIS} AND ({GEO_ETAT}) = 'pose_a_la_main'",
            params=geo_params(commune, code_postal),
            steps=("osm", "sirene", "rna"),
        ),
        FileDeTravail(
            cle="donnees-a-arbitrer",
            titre="Chiffres à confirmer",
            question="Ce montant est-il bien celui que l'acte a voté ?",
            geste="Retenir la ligne, ou l'écarter",
            effet="Une ligne lue dans un procès-verbal ne sort JAMAIS sur le "
                  "site tant qu'un humain ne l'a pas retenue.",
            route="/atelier/donnees",
            role_min="validator",
            # Ce que les collecteurs n'ont pas su affirmer, et que personne n'a
            # encore tranché. `jamais_relu` vaut absence de ligne d'annotation :
            # cf. `collectors/verdict.py`.
            reste="""
                SELECT (SELECT COUNT(*) FROM marches_publics m
                         WHERE m.confidence IN ('probable','hypothesis')
                           AND NOT EXISTS (SELECT 1 FROM annotations a
                                            WHERE a.object_type = 'marche'
                                              AND a.object_id = m.id
                                              AND a.review_status <> 'jamais_relu'))
                     + (SELECT COUNT(*) FROM financial_flows f
                         WHERE f.confidence IN ('probable','hypothesis')
                           AND NOT EXISTS (SELECT 1 FROM annotations a
                                            WHERE a.object_type = 'flow'
                                              AND a.object_id = f.id
                                              AND a.review_status <> 'jamais_relu'))
            """,
            fait="SELECT COUNT(*) FROM annotations "
                 "WHERE object_type IN ('marche','flow') "
                 "AND review_status <> 'jamais_relu'",
            steps=("cm_flux", "marches", "seed", "saisies"),
            # Les flux d'abord : ce sont eux qui portent les baux et les
            # subventions lues dans les procès-verbaux, là où le texte de
            # l'acte permet vraiment de trancher. La définition vit dans
            # `ECRANS` — l'écran de décision la relit pour son « reste ».
            ecran=ECRANS,
        ),
        FileDeTravail(
            cle="fiches",
            titre="Toutes les fiches",
            question="Cette fiche décrit-elle bien ce qu'elle prétend décrire ?",
            geste="Retenir, écarter, ou remettre à relire",
            effet="Une fiche écartée sort du site ; une fiche jamais relue y "
                  "reste, et c'est voulu — l'inverse viderait le site.",
            route="/atelier/fiches",
            role_min="validator",
            # Il n'y a pas de « reste » honnête ici : personne ne relira 22 783
            # fiches. Le nombre est affiché comme une CONTENANCE, pas comme une
            # tâche — c'est pourquoi cette file est `experte`.
            reste="SELECT COUNT(*) FROM entities e "
                  "WHERE NOT EXISTS (SELECT 1 FROM annotations a "
                  "WHERE a.object_type = 'entity' AND a.object_id = e.id "
                  "AND a.review_status <> 'jamais_relu')",
            fait="SELECT COUNT(*) FROM annotations "
                 "WHERE object_type = 'entity' AND review_status <> 'jamais_relu'",
            experte=True,
        ),
    )


# ─── Le relevé ────────────────────────────────────────────────────────────────

def _un_nombre(conn, sql: str, params: tuple = ()) -> int:
    return conn.execute(sql, params).fetchone()[0] or 0


def _en_cours(conn, table: Optional[str]) -> list[dict]:
    """Qui travaille sur cette file EN CE MOMENT, et depuis quand.

    « Repérer les chantiers en cours » est la demande d'origine, et la
    réservation existe depuis le premier lot — mais rien ne la lisait ailleurs
    que dans la file elle-même. Une réservation expirée n'en est plus une : le
    seuil est `RESERVATION_MINUTES`, et il n'est écrit qu'à un endroit.
    """
    if not table:
        return []
    lignes = conn.execute(
        f"SELECT locked_by, COUNT(*) AS n, MIN(locked_at) AS depuis "
        f"FROM {table} "
        f"WHERE locked_by IS NOT NULL AND locked_at IS NOT NULL "
        f"  AND (julianday('now') - julianday(locked_at)) * 1440 < ? "
        f"GROUP BY locked_by ORDER BY n DESC",
        (RESERVATION_MINUTES,)).fetchall()
    return [{"par": r[0], "combien": r[1], "depuis": r[2]} for r in lignes]


def _derniere_passe(conn, steps: tuple[str, ...]) -> Optional[dict]:
    """La dernière fois qu'un des collecteurs de cette file est passé.

    C'est ce qui permet à un zéro de porter sa raison. `collector_runs` retient
    `status` (`ok` | `empty` | `error` | `timeout`) et `items_added` : « passé
    hier, rien trouvé » et « jamais passé ici » ne s'écrivent pas pareil.
    """
    if not steps:
        return None
    marques = ",".join("?" for _ in steps)
    r = conn.execute(
        f"SELECT collector, status, items_added, finished_at FROM collector_runs "
        f"WHERE collector IN ({marques}) AND finished_at IS NOT NULL "
        f"ORDER BY finished_at DESC LIMIT 1", steps).fetchone()
    if not r:
        return None
    return {"collecteur": r[0], "issue": r[1], "trouve": r[2], "le": r[3]}


def a_trancher(conn, ecran: tuple[tuple[str, str], ...] = ECRANS) -> list[dict]:
    """Tout ce qui attend un geste dans cette file, DANS L'ORDRE, tous types.

    Une seule définition, trois lectures : le compte de la carte
    « Aujourd'hui », la première ligne qu'ouvre « Commencer », et le reste que
    l'écran de décision affiche juste avant qu'on tranche.

    ⚠️ Elle traverse les types. La file « Chiffres à confirmer » porte des flux
    ET des marchés ; l'écran de décision, lui, est ouvert sur un type. Compter
    par type y annonçait 76 quand la carte en annonçait 79 — trois marchés
    invisibles, et une file qu'on croit finie alors qu'il reste à faire.
    """
    sortie = []
    for objet, requete in ecran:
        tranches = {r[0] for r in conn.execute(
            "SELECT object_id FROM annotations WHERE object_type = ? "
            "AND review_status <> 'jamais_relu'", (objet,))}
        sortie += [{"objet": objet, "id": oid}
                   for (oid,) in conn.execute(requete) if oid not in tranches]
    return sortie


def _premier_a_trancher(conn, ecran: tuple[tuple[str, str], ...]) -> Optional[dict]:
    """La première ligne que personne n'a tranchée — la porte de « Commencer ».

    Renvoie None quand tout est tranché : l'écran retombe alors sur la vue
    d'ensemble, qui, elle, existe toujours.
    """
    file = a_trancher(conn, ecran)
    return file[0] if file else None


def relever(conn, commune: str, code_postal: str) -> list[dict]:
    """L'état de toutes les files. Aucune écriture, aucun effet de bord.

    Une file dont une table manque (base d'une ancienne version, instance qui
    n'a pas encore tourné) rend `reste: None` plutôt que de faire échouer tout
    l'écran : une file cassée ne doit pas emporter les quatre autres.
    """
    releve = []
    for f in files(commune, code_postal):
        ligne = {
            "cle": f.cle, "titre": f.titre, "question": f.question,
            "geste": f.geste, "effet": f.effet, "route": f.route,
            "role_min": f.role_min, "experte": f.experte,
        }
        try:
            ligne["reste"] = _un_nombre(conn, f.reste, f.params)
            ligne["fait"] = _un_nombre(conn, f.fait, f.params) if f.fait else None
            ligne["en_cours"] = _en_cours(conn, f.table)
            ligne["premier"] = _premier_a_trancher(conn, f.ecran) if f.ecran else None
        except Exception as e:                       # table absente, colonne absente
            ligne.update(reste=None, fait=None, en_cours=[], premier=None,
                         indisponible=str(e))
        ligne["derniere_passe"] = _derniere_passe(conn, f.steps)
        releve.append(ligne)
    return releve


# ─── Le premier jour — ce qu'un bénévole peut faire en arrivant ──────────────
# Lot D du chantier, 23/09/2026.
#
# Le constat qui l'a ouvert : les rôles emboîtés existent depuis le 21/09, mais
# **un contributeur qui se connectait n'avait rien à faire qui compte**. Le seul
# geste qui lui était ouvert écrivait dans `entities.validation_status`, que la
# publication ne lisait pas. Il pouvait cliquer toute une soirée sans rien
# changer, et rien ne le lui disait.
#
# Trois gestes, pas plus. Une liste de douze possibilités n'est pas un
# accueil : c'est un menu de plus. Et chacun dit ce qu'il APPORTE — un bénévole
# qui ne voit pas l'effet de son travail ne revient pas.

@dataclass(frozen=True)
class Geste_du_jour:
    titre: str
    pourquoi: str      # ce que ça apporte au dispositif, pas ce que ça fait au clic
    route: str


#: Par rôle, du plus simple au plus engageant. Les rôles sont EMBOÎTÉS : un
#: validateur fait tout ce que fait un contributeur, donc sa liste ne répète pas
#: la précédente, elle la prolonge — l'écran les enchaîne.
PREMIER_JOUR = {
    "contributor": (
        Geste_du_jour(
            titre="Corriger un nom, une adresse, une date",
            pourquoi="Vous proposez ; un validateur confirme. Une correction "
                     "garde votre nom dans l'historique de la fiche.",
            route="/atelier/fiches"),
        Geste_du_jour(
            titre="Saisir une donnée lue dans un procès-verbal",
            pourquoi="Elle entre en « probable » : elle ne part pas sur le site "
                     "tant que personne ne l'a retenue. Rien ne peut casser.",
            route="/atelier/saisie"),
        Geste_du_jour(
            titre="Lire une file et signaler ce qui cloche",
            pourquoi="Repérer une ligne douteuse vaut déjà beaucoup : les "
                     "validateurs ne peuvent pas tout relire.",
            route="/atelier"),
    ),
    "validator": (
        Geste_du_jour(
            titre="Trancher un chiffre, preuve sous les yeux",
            pourquoi="L'écran montre l'acte et le passage où le montant "
                     "apparaît. C'est le geste qui change le site.",
            route="/atelier"),
        Geste_du_jour(
            titre="Confirmer ou écarter un lien présumé",
            pourquoi="Un détecteur propose, vous décidez. Rien n'est publié "
                     "avant votre confirmation.",
            route="/atelier/relations"),
        Geste_du_jour(
            titre="Poser un point au bon endroit sur la carte",
            pourquoi="Un point posé à la main fait autorité : il remplace "
                     "l'approximation du géocodeur.",
            route="/atelier/geo"),
    ),
    "admin": (
        Geste_du_jour(
            titre="Inviter quelqu'un, et lui donner son rôle",
            pourquoi="L'atelier n'a de sens qu'à plusieurs. Chaque rôle est "
                     "décrit en une phrase au moment d'inviter.",
            route="/atelier/comptes"),
        Geste_du_jour(
            titre="Générer un aperçu du site avant de publier",
            pourquoi="L'aperçu est à vous : vous voyez l'effet des décisions "
                     "sans rien mettre en ligne.",
            route="/atelier/publication"),
        Geste_du_jour(
            titre="Lire le journal : qui a fait quoi",
            pourquoi="C'est ce qui rend le travail collectif vérifiable, et "
                     "ce qui permet de revenir sur une décision.",
            route="/atelier/journal"),
    ),
}

#: Les rôles, du moins au plus étendu — le miroir de `api_auth.ROLES`.
ROLES_EMBOITES = ("contributor", "validator", "admin")


def premier_jour(role: str) -> dict:
    """Les TROIS gestes du premier jour pour `role`, et ce qu'il hérite.

    Les rôles sont emboîtés, mais empiler neuf gestes devant un administrateur
    qui arrive n'est plus un accueil : c'est un menu de plus, et c'est
    exactement ce que ce lot devait supprimer. L'écran met en avant les trois
    du rôle, et rappelle d'une ligne que le reste lui est ouvert aussi.

    Un rôle inconnu rend une liste vide plutôt qu'une liste devinée : mieux
    vaut un accueil absent qu'un accueil qui propose un geste refusé ensuite.
    """
    if role not in ROLES_EMBOITES:
        return {"miens": [], "herites": []}
    rang = ROLES_EMBOITES.index(role)
    dire = lambda g, r: {"titre": g.titre, "pourquoi": g.pourquoi,
                         "route": g.route, "role": r}
    return {
        "miens": [dire(g, role) for g in PREMIER_JOUR.get(role, ())],
        "herites": [dire(g, r) for r in ROLES_EMBOITES[:rang]
                    for g in PREMIER_JOUR.get(r, ())],
    }
