"""taches.py — les tâches nées des lacunes : ce qu'un bénévole peut faire en vingt minutes.

Chantier 2 du graphe des liens, 03/10/2026. Les dossiers disent ce qu'ils ne
savent pas (`collectors/lacunes.py`) : une question ouverte du tableau « Ce
qu'on ne sait pas », une citation qui ne mène à aucun acte publié. Jusqu'ici
c'était un constat, publié et laissé là. Chaque lacune devient ici une TÂCHE de
l'écran « Aujourd'hui », dans une file nommée comme les autres
(`collectors/files.py`, file `lacunes`) — pas une liste à côté.

Trois natures, chacune faisable par quelqu'un qui n'a jamais ouvert un terminal :

  relier     choisir, parmi des actes publiés proposés, celui qu'une citation
             voulait dire — ou dire qu'aucun ne convient ;
  demander   préparer la question écrite ou la demande de document qui
             comblerait la lacune : à qui, quoi, et la date d'envoi ;
  verser     la réponse est arrivée : la résumer et dire où elle se trouve,
             pour que l'éditeur la porte au dossier.

Une question passe de « demander » à « verser » quand la demande est envoyée :
c'est la même tâche, avec son historique. La date d'envoi est gardée
(`envoye_le`) : le suivi des demandes — délai d'un mois, saisine de la CADA,
relance — est le chantier suivant, et il se branchera dessus.

Le cycle de vie suit le DOSSIER, jamais l'inverse :

  - une lacune qui disparaît du dossier ferme sa tâche toute seule, avec la
    raison ;
  - une lacune dont l'état change (`ouvert` → `en partie`) garde sa tâche et
    son historique — l'identifiant de la lacune est stable (cf. lacunes.py) ;
  - ⚖️ une tâche n'écrit JAMAIS dans le markdown du dossier. Une réponse
    validée attend que l'éditeur humain change le texte ; c'est ce changement
    qui ferme la tâche, au relevé suivant.

Les rôles sont ceux de l'atelier : un contributeur répond (il PROPOSE), un
validateur valide ou renvoie avec un motif. Personne ne valide sa propre
réponse quand la relecture croisée est active (`RELECTURE_CROISEE`, active par
défaut ; une instance à un seul validateur la coupe dans `config/instance.json`,
clé `atelier.relecture_croisee`).
"""
from __future__ import annotations

import json
import re


# ─── Le schéma ───────────────────────────────────────────────────────────────

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS taches (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        lacune_id     TEXT NOT NULL UNIQUE,     -- dossier:q-… ou dossier:c-…
        dossier       TEXT NOT NULL,            -- le slug
        nature        TEXT NOT NULL,            -- relier | demander | verser
        etat          TEXT NOT NULL DEFAULT 'ouverte',
                      -- ouverte | proposee | validee | fermee
        libelle       TEXT NOT NULL,            -- la question, en français
        lacune        TEXT,                     -- la lacune telle que relevée (JSON)
        etat_lacune   TEXT,                     -- ouvert | en_partie | …
        reponse       TEXT,                     -- ce que le bénévole a apporté (JSON)
        propose_par   INTEGER REFERENCES users(id),
        propose_le    TEXT,
        valide_par    INTEGER REFERENCES users(id),
        valide_le     TEXT,
        envoye_le     TEXT,                     -- une demande partie : le suivi s'y branchera
        cree_le       TEXT DEFAULT (datetime('now')),
        ferme_le      TEXT,
        raison        TEXT                      -- pourquoi elle est fermée
    )""",
    """CREATE TABLE IF NOT EXISTS taches_journal (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        tache_id  INTEGER NOT NULL REFERENCES taches(id),
        le        TEXT DEFAULT (datetime('now')),
        par       INTEGER REFERENCES users(id),   -- NULL : le relevé du dossier
        quoi      TEXT NOT NULL,
        detail    TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_taches_etat ON taches(etat)",
)

NATURES = {
    "relier": {"titre": "Relier une citation",
               "geste": "Choisir l'acte que la phrase voulait dire, parmi ceux proposés"},
    "demander": {"titre": "Préparer une demande",
                 "geste": "Écrire à qui demander, quoi, et noter la date d'envoi"},
    "verser": {"titre": "Verser une réponse",
               "geste": "Résumer la réponse reçue et dire où elle se trouve"},
}
ETATS = ("ouverte", "proposee", "validee", "fermee")

#: Ce qu'un dossier écrit d'une question à laquelle il a été répondu. Une
#: lacune dans cet état n'appelle plus de geste : sa tâche se ferme.
ETATS_RESOLUS = {"resolu", "resolue", "repondu", "repondue", "connu", "connue",
                 "ferme", "fermee", "comble", "comblee"}


def relecture_croisee() -> bool:
    """La règle « personne ne valide sa propre réponse » : active sauf si
    l'instance la coupe explicitement."""
    try:
        from .config import _I
        return bool((_I.get("atelier") or {}).get("relecture_croisee", True))
    except Exception:
        return True


def assurer_schema(conn) -> None:
    """L'API ne passe pas par `init_db()` : sur une base antérieure, la table
    naît au premier relevé."""
    for sql in SCHEMA:
        conn.execute(sql)


# ─── La question ─────────────────────────────────────────────────────────────

def libelle(nature: str, lacune: dict) -> str:
    """Le libellé de la tâche : une question en français, jamais un identifiant.

    Une ligne du tableau « Ce qu'on ne sait pas » est souvent un intitulé (« Le
    contrat du syndicat avec son exploitant ») : on en fait une question sans
    le réécrire, pour que le bénévole reconnaisse la phrase du dossier.
    """
    q = (lacune.get("question") or "").strip().rstrip(".")
    if nature == "relier":
        return q if q.endswith("?") else f"À quel acte renvoie « {q} » ?"
    if nature == "verser":
        return f"La réponse sur « {q.rstrip(' ?')} » est-elle arrivée ?"
    if q.endswith("?"):
        return f"Que faut-il demander, et à qui, pour répondre à : {q}"
    return f"Que faut-il demander, et à qui, pour connaître « {q} » ?"


def nature_de(lacune: dict) -> str:
    return "relier" if lacune.get("nature") == "citation" else "demander"


# ─── Le relevé : synchroniser les tâches avec les dossiers ───────────────────

def _journal(conn, tache_id: int, quoi: str, detail=None, par: int | None = None) -> None:
    conn.execute("INSERT INTO taches_journal(tache_id, par, quoi, detail) VALUES(?,?,?,?)",
                 (tache_id, par, quoi,
                  json.dumps(detail, ensure_ascii=False) if isinstance(detail, (dict, list))
                  else detail))


def _fermer(conn, t, raison: str) -> None:
    conn.execute("UPDATE taches SET etat='fermee', ferme_le=datetime('now'), raison=? WHERE id=?",
                 (raison, t["id"]))
    _journal(conn, t["id"], "fermee", raison)


def synchroniser(conn, lacunes: list[dict], titres: dict[str, str] | None = None) -> dict:
    """Met les tâches d'accord avec les lacunes des dossiers, maintenant.

    `lacunes` : TOUTES les lacunes de TOUS les dossiers de l'instance — une
    lacune absente de la liste est une lacune disparue. Idempotent : rejoué
    sans changement de dossier, il n'écrit rien.
    """
    titres = titres or {}
    bilan = {"creees": 0, "fermees": 0, "reouvertes": 0, "etat_change": 0}
    existantes = {r["lacune_id"]: r for r in _lignes(conn, "SELECT * FROM taches")}
    vues = set()
    for l in lacunes:
        vues.add(l["id"])
        t = existantes.get(l["id"])
        resolue = l.get("etat") in ETATS_RESOLUS
        if t is None:
            if resolue:
                continue
            nature = nature_de(l)
            tid = conn.execute(
                "INSERT INTO taches(lacune_id, dossier, nature, libelle, lacune, etat_lacune) "
                "VALUES(?,?,?,?,?,?)",
                (l["id"], l["dossier"], nature, libelle(nature, l),
                 json.dumps(l, ensure_ascii=False), l.get("etat"))).lastrowid
            _journal(conn, tid, "creee", f"relevée dans le dossier « {titres.get(l['dossier'], l['dossier'])} »")
            bilan["creees"] += 1
            continue
        if t["etat"] == "fermee":
            if resolue:
                continue
            # La question est revenue (l'éditeur l'avait retirée, puis remise) :
            # même identifiant, donc même tâche, et son historique avec elle.
            conn.execute("UPDATE taches SET etat='ouverte', ferme_le=NULL, raison=NULL, "
                         "lacune=?, etat_lacune=? WHERE id=?",
                         (json.dumps(l, ensure_ascii=False), l.get("etat"), t["id"]))
            _journal(conn, t["id"], "reouverte", "la lacune est revenue dans le dossier")
            bilan["reouvertes"] += 1
            continue
        if resolue:
            _fermer(conn, t, f"le dossier la dit désormais « {l.get('etat_libelle') or l.get('etat')} »")
            bilan["fermees"] += 1
            continue
        if t["etat_lacune"] != l.get("etat"):
            _journal(conn, t["id"], "etat_lacune",
                     f"« {t['etat_lacune'] or '—'} » → « {l.get('etat')} »")
            bilan["etat_change"] += 1
        conn.execute("UPDATE taches SET lacune=?, etat_lacune=? WHERE id=?",
                     (json.dumps(l, ensure_ascii=False), l.get("etat"), t["id"]))
    for lid, t in existantes.items():
        if lid in vues or t["etat"] == "fermee":
            continue
        titre = titres.get(t["dossier"], t["dossier"])
        if t["dossier"] not in titres:
            raison = f"le dossier « {t['dossier']} » n'existe plus"
        elif t["nature"] == "relier":
            raison = (f"la citation n'est plus sans cible dans « {titre} » : "
                      "le dossier a été corrigé, ou la phrase retirée")
        else:
            raison = f"la question a disparu du dossier « {titre} » (retirée ou reformulée)"
        _fermer(conn, t, raison)
        bilan["fermees"] += 1
    return bilan


def lacunes_de_l_instance(racine, index) -> tuple[list[dict], dict[str, str]]:
    """Les lacunes de tous les dossiers, contre les actes publiables à
    l'instant (`index`), et le titre de chaque dossier. Un dossier « à
    développer » n'a pas encore de corps : il ne déclare rien."""
    from . import dossiers as D
    from . import lacunes as L
    from .citations import relier
    toutes, titres = [], {}
    for slug, p in D.lister(racine):
        texte = p.read_text(encoding="utf-8")
        meta, _ = D.entete(texte)
        titres[slug] = meta.get("titre") or slug
        if meta.get("statut") == "a_developper":
            continue
        toutes += L.questions(slug, texte)
        toutes += L.citations(slug, relier(texte, index).non_resolues)
    return toutes, titres


# ─── Lire ────────────────────────────────────────────────────────────────────

def _lignes(conn, sql: str, params=()) -> list[dict]:
    cur = conn.execute(sql, params)
    noms = [d[0] for d in cur.description]
    return [dict(zip(noms, r)) for r in cur.fetchall()]


def _decoder(t: dict) -> dict:
    for cle in ("lacune", "reponse"):
        try:
            t[cle] = json.loads(t[cle]) if t.get(cle) else None
        except (json.JSONDecodeError, TypeError):
            t[cle] = None
    return t


def lire(conn, tache_id: int) -> dict | None:
    r = _lignes(conn, "SELECT * FROM taches WHERE id=?", (tache_id,))
    if not r:
        return None
    t = _decoder(r[0])
    t["journal"] = _lignes(conn, "SELECT j.le, j.quoi, j.detail, u.email AS par FROM taches_journal j "
                                 "LEFT JOIN users u ON u.id = j.par WHERE j.tache_id=? ORDER BY j.id",
                           (tache_id,))
    return t


def lister(conn, etats: tuple[str, ...] = ("ouverte", "proposee", "validee")) -> list[dict]:
    marques = ",".join("?" for _ in etats)
    return [_decoder(t) for t in _lignes(
        conn, f"SELECT t.*, u.email AS propose_par_email FROM taches t "
              f"LEFT JOIN users u ON u.id = t.propose_par WHERE t.etat IN ({marques}) "
              f"ORDER BY CASE t.etat WHEN 'proposee' THEN 0 WHEN 'ouverte' THEN 1 ELSE 2 END, t.id",
        etats)]


# ─── Les gestes ──────────────────────────────────────────────────────────────

class Refus(Exception):
    """Le geste n'est pas permis ; le message dit pourquoi, en français."""

    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.code = code


_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _texte(contenu: dict, cle: str, requis: bool = True, maximum: int = 4000) -> str | None:
    v = (contenu.get(cle) or "").strip() if isinstance(contenu.get(cle, ""), str) else ""
    if requis and not v:
        raise Refus(f"Il manque « {cle} ».")
    return v[:maximum] or None


def _date(contenu: dict, cle: str) -> str | None:
    v = (contenu.get(cle) or "").strip()
    if v and not _DATE.match(v):
        raise Refus(f"« {cle} » attend une date AAAA-MM-JJ.")
    return v or None


def nettoyer_reponse(nature: str, contenu: dict, candidats: set[str] | None = None) -> dict:
    """Ce qu'une réponse peut porter, par nature — rien d'autre n'est gardé.
    Aux frontières de l'API : tout vient d'un formulaire."""
    if not isinstance(contenu, dict):
        raise Refus("La réponse doit être un objet.")
    if nature == "relier":
        cle = (contenu.get("cle") or "").strip() or None
        if cle and candidats is not None and cle not in candidats:
            raise Refus("Cet acte ne fait pas partie des actes publiés proposés.")
        note = _texte(contenu, "note", requis=not cle, maximum=1000)
        return {"cle": cle, "note": note}
    if nature == "demander":
        return {"destinataire": _texte(contenu, "destinataire", maximum=200),
                "objet": _texte(contenu, "objet", maximum=300),
                "texte": _texte(contenu, "texte"),
                "envoye_le": _date(contenu, "envoye_le")}
    if nature == "verser":
        return {"resume": _texte(contenu, "resume"),
                "recu_le": _date(contenu, "recu_le"),
                "ou": _texte(contenu, "ou", maximum=500)}
    raise Refus(f"Nature inconnue : {nature}.")


def repondre(conn, tache_id: int, user: dict, contenu: dict,
             candidats: set[str] | None = None) -> dict:
    """Un contributeur (ou plus) apporte une réponse : elle est PROPOSÉE."""
    t = lire(conn, tache_id)
    if not t:
        raise Refus("Tâche introuvable.", 404)
    if t["etat"] not in ("ouverte", "proposee"):
        raise Refus(f"Cette tâche n'attend pas de réponse : elle est « {t['etat']} ».", 409)
    reponse = nettoyer_reponse(t["nature"], contenu, candidats)
    conn.execute("UPDATE taches SET etat='proposee', reponse=?, propose_par=?, "
                 "propose_le=datetime('now'), valide_par=NULL, valide_le=NULL WHERE id=?",
                 (json.dumps(reponse, ensure_ascii=False), user["id"], tache_id))
    _journal(conn, tache_id, "proposee", reponse, user["id"])
    return lire(conn, tache_id)


def valider(conn, tache_id: int, user: dict, accepter: bool, motif: str = "") -> dict:
    """Un validateur tranche une réponse proposée.

    Accepter une DEMANDE déjà envoyée (date d'envoi connue) la fait passer à
    l'étape suivante — attendre et verser la réponse — dans la même tâche.
    Une autre réponse acceptée attend l'éditeur du dossier (`validee`).
    """
    t = lire(conn, tache_id)
    if not t:
        raise Refus("Tâche introuvable.", 404)
    if t["etat"] != "proposee":
        raise Refus("Aucune réponse n'attend de validation sur cette tâche.", 409)
    if relecture_croisee() and t["propose_par"] == user["id"]:
        raise Refus("Vous avez apporté cette réponse : un autre validateur doit la relire.", 403)
    if not accepter:
        if not (motif or "").strip():
            raise Refus("Renvoyer demande d'expliquer pourquoi : sans motif, la personne "
                        "qui a répondu ne saura pas quoi reprendre.")
        conn.execute("UPDATE taches SET etat='ouverte' WHERE id=?", (tache_id,))
        _journal(conn, tache_id, "renvoyee", motif.strip()[:1000], user["id"])
        return lire(conn, tache_id)
    conn.execute("UPDATE taches SET etat='validee', valide_par=?, valide_le=datetime('now') "
                 "WHERE id=?", (user["id"], tache_id))
    _journal(conn, tache_id, "validee", (motif or "").strip()[:1000] or None, user["id"])
    if t["nature"] == "demander" and (t["reponse"] or {}).get("envoye_le"):
        _passer_a_verser(conn, tache_id, t["reponse"]["envoye_le"], user)
    return lire(conn, tache_id)


def marquer_envoyee(conn, tache_id: int, user: dict, envoye_le: str) -> dict:
    """La demande validée est partie : on note la date, et la tâche attend la
    réponse. C'est cette date que le suivi des demandes lira."""
    t = lire(conn, tache_id)
    if not t:
        raise Refus("Tâche introuvable.", 404)
    if t["nature"] != "demander" or t["etat"] != "validee":
        raise Refus("Seule une demande validée peut être marquée envoyée.", 409)
    date = _date({"envoye_le": envoye_le}, "envoye_le")
    if not date:
        raise Refus("Il manque la date d'envoi.")
    _passer_a_verser(conn, tache_id, date, user)
    return lire(conn, tache_id)


def _passer_a_verser(conn, tache_id: int, envoye_le: str, user: dict) -> None:
    t = lire(conn, tache_id)
    conn.execute("UPDATE taches SET nature='verser', etat='ouverte', envoye_le=?, libelle=?, "
                 "reponse=NULL, propose_par=NULL, propose_le=NULL, valide_par=NULL, "
                 "valide_le=NULL WHERE id=?",
                 (envoye_le, libelle("verser", t["lacune"] or {}), tache_id))
    _journal(conn, tache_id, "envoyee",
             {"envoye_le": envoye_le, "demande": t["reponse"]}, user["id"])


# ─── Ce que la file compte ───────────────────────────────────────────────────

#: Ce qui attend un geste : une question sans réponse, ou une réponse à valider.
RESTE = "SELECT COUNT(*) FROM taches WHERE etat IN ('ouverte', 'proposee')"
#: Ce qui est fait : validé (en attente de l'éditeur) ou fermé par le dossier.
FAIT = "SELECT COUNT(*) FROM taches WHERE etat IN ('validee', 'fermee')"
