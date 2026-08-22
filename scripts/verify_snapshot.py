#!/usr/bin/env python3
"""Contrôleur d'étanchéité du snapshot public — écrit comme un adversaire.

Indépendant de build_public_snapshot.py : il ne partage aucun code avec le
builder, lit config/publication_rules.json et attaque le répertoire publié.
Si le builder et le contrôleur ont le même bug, la fuite passe — c'est
précisément pourquoi ce fichier ne doit jamais importer le builder ni être
« aligné » sur lui. Toute assertion retirée ici est une décision éditoriale.

Usage :
    venv/bin/python3 scripts/verify_snapshot.py [DIR ...] [--json]
    (défaut : dashboard/static/public_api, public/static/data, public/build)

Sortie : rapport groupé par règle, exit 1 à la moindre violation bloquante.
Avec `--json`, le même rapport sort en JSON, chaque cas décomposé (fichier,
champ, identifiants) pour que l'atelier puisse renvoyer vers la fiche fautive.
Le rapport texte intégral y figure sous `rapport` : le format machine n'est pas
un résumé, il ne masque rien.
À câbler à la fin de toute génération/déploiement : un build qui fuit échoue.
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# `VIGIE_RULES` — même surcharge que dans le builder : les tests tournent sur
# l'exemple versionné. Le contrôleur reste indépendant du builder, il lit
# seulement le même fichier de règles.
RULES = json.loads(Path(os.environ.get("VIGIE_RULES")
                        or ROOT / "config" / "publication_rules.json").read_text())

PUBLIC_CONFIDENCE = set(RULES["confidence"]["public"])
PRIVATE_MARKERS = [m.lower() for m in RULES["relations"]["private_markers"]]
RELATION_ALLOWLIST = set(RULES["relations"]["public_allowlist"]) | set(
    RULES["relations"].get("relevance_allowlist", [])
)
PUBLIC_EVENT_SOURCES = set(RULES["events"]["public_sources"])
EXCLUDED_EVENT_TYPES = set(RULES["events"]["exclude_types"])
GENERIC_DOMAINS = set(RULES["urls"]["exclude_generic_domains"])

# Fichiers qui n'ont RIEN à faire dans un répertoire publié.
FORBIDDEN_FILENAMES = re.compile(
    r"(^review_report.*\.json$|^qa_report.*\.json$|\.db$|\.sqlite3?$|^\.env)", re.I
)
# Chaînes qui trahissent une fuite d'environnement local ou de secret.
LEAKY_STRINGS = re.compile(
    r"file://|/Users/|/home/|sk-ant-|api[_-]?key|X-Admin-Key|Bearer\s+ey", re.I
)
# Clés interdites où qu'elles apparaissent dans un objet publié.
FORBIDDEN_KEYS = {"personnes_citees", "birth_date", "date_naissance", "adresse_personnelle"}
# Clés à signaler (non bloquant) si elles portent une valeur.
SUSPECT_KEYS = {"email", "mail", "telephone", "phone", "tel"}

MAX_EXAMPLES = 8
# Cas détaillés par règle dans la sortie `--json`. Au-delà, seul le compte est
# rendu : l'atelier affiche « 1 229 cas », pas 1 229 lignes.
MAX_CAS = 50

# Un exemple est écrit `<fichier>: <détail>` partout, sauf pour les renvois
# sortants qui portent `<fichier> · <champ> : <détail>`. Ces deux formes sont le
# contrat de sortie du contrôleur ; les relire ici lui évite d'être réécrit à
# vingt endroits pour ajouter un identifiant à chaque appel.
_RE_FICHE_ENTITE = re.compile(r"(?:^|/)entite/(\d+)\.json")
_RE_ID = re.compile(r"\bid=(\d+)")
_RE_IDS_LISTE = re.compile(r"ex\. \[([0-9,\s]+)\]")


def analyser_cas(exemple):
    """Décompose un exemple en fichier, champ, objet visé et identifiants.

    Rien n'est deviné : ce qui n'est pas reconnu reste `None`, et `message`
    porte toujours l'exemple entier. Un contrôle mal décomposé ne doit pas
    devenir un contrôle amputé.
    """
    texte = str(exemple)
    fichier = champ = None
    reste = texte
    if " · " in texte:
        fichier, _, apres = texte.partition(" · ")
        champ, _, reste = apres.partition(" : ")
        champ = champ.strip() or None
    elif ": " in texte:
        fichier, _, reste = texte.partition(": ")
    else:
        fichier = texte
    fichier = (fichier or "").strip() or None

    identifiants = []
    objet = None
    m = _RE_FICHE_ENTITE.search(fichier or "")
    if m:
        objet, identifiants = "entite", [int(m.group(1))]
    else:
        liste = _RE_IDS_LISTE.search(reste)
        if liste:
            objet = "entite"      # tous les champs de CHAMPS_RENVOI visent une entité
            identifiants = [int(n) for n in liste.group(1).replace(" ", "").split(",") if n]
        else:
            ids = _RE_ID.findall(reste)
            if ids:
                identifiants = [int(n) for n in ids]
                objet = "evenement" if (fichier or "").startswith("events") else None

    return {"message": texte, "fichier": fichier, "champ": champ,
            "objet": objet, "identifiants": identifiants}


class Report:
    def __init__(self):
        self.errors = {}   # règle -> [exemples]
        self.warnings = {}
        self.files = 0

    def _add(self, bucket, rule, example):
        bucket.setdefault(rule, []).append(example)

    def error(self, rule, example):
        self._add(self.errors, rule, example)

    def warn(self, rule, example):
        self._add(self.warnings, rule, example)

    def lignes(self):
        out = []
        for label, bucket in (("BLOQUANT", self.errors), ("avertissement", self.warnings)):
            for rule, examples in sorted(bucket.items()):
                out.append(f"[{label}] {rule} — {len(examples)} cas")
                for ex in examples[:MAX_EXAMPLES]:
                    out.append(f"    {ex}")
                if len(examples) > MAX_EXAMPLES:
                    out.append(f"    … {len(examples) - MAX_EXAMPLES} autres")
        return out

    def dump(self):
        for ligne in self.lignes():
            print(ligne)

    def groupes(self, bucket):
        """Le même contenu, décomposé — une entrée par règle, ses cas dedans.

        Le rapport texte reste la référence : ceci n'en retire rien, il ajoute
        ce qu'une interface peut suivre. `total` compte TOUS les cas, `cas` en
        détaille au plus MAX_CAS — une règle violée 1 229 fois se dit en un
        nombre, pas en 1 229 lignes envoyées au navigateur.
        """
        return [
            {
                "regle": regle,
                "total": len(exemples),
                "cas": [analyser_cas(ex) for ex in exemples[:MAX_CAS]],
            }
            for regle, exemples in sorted(bucket.items())
        ]


def domain_of(url):
    m = re.match(r"https?://([^/]+)", str(url))
    return m.group(1).lower().lstrip("www.") if m else None


# Clés sous lesquelles une URL est un site ATTRIBUÉ à une entité (la règle des
# domaines génériques ne vise que ça — pas les citations de source page_url etc.)
# (`url`/`page_url`/`source_url` sont des citations d'actes ou d'articles, pas
# des sites attribués — actualite.json cite lasalle.fr en permanence, c'est licite.)
ENTITY_URL_KEYS = {"urls", "website", "site"}


def walk(node, path, rep, loc, parent_key=None):
    """Parcourt récursivement tout objet JSON et applique les règles de fond."""
    if isinstance(node, dict):
        for key in node:
            if key in FORBIDDEN_KEYS:
                rep.error("clé interdite publiée", f"{loc}: clé '{key}'")
            elif key.lower() in SUSPECT_KEYS and node[key]:
                rep.warn("clé de contact avec valeur", f"{loc}: {key}={node[key]!r}")

        conf = node.get("confidence")
        if conf is not None and conf not in PUBLIC_CONFIDENCE:
            rep.error(
                "confidence hors whitelist publique",
                f"{loc}: confidence={conf!r} name={node.get('name') or node.get('title')!r}",
            )

        rtype = node.get("relation_type")
        if rtype is not None:
            low = str(rtype).lower()
            if any(m in low for m in PRIVATE_MARKERS):
                rep.error("relation avec marqueur privé", f"{loc}: {rtype!r}")
            elif rtype not in RELATION_ALLOWLIST:
                rep.error("relation_type hors allowlist", f"{loc}: {rtype!r}")
        role = node.get("role")
        if role and any(m in str(role).lower() for m in PRIVATE_MARKERS):
            rep.error("rôle avec marqueur privé", f"{loc}: {role!r}")

        if node.get("type") == "person" or node.get("entity_type") == "person":
            if node.get("lat") or node.get("lng") or node.get("coordinates"):
                rep.error(
                    "personne avec coordonnées",
                    f"{loc}: {node.get('name')!r} lat={node.get('lat')} lng={node.get('lng')}",
                )
        if node.get("has_public_location") is False and (node.get("lat") or node.get("lng")):
            rep.error(
                "coordonnées publiées malgré has_public_location=false",
                f"{loc}: {node.get('name')!r}",
            )

        for key, value in node.items():
            walk(value, path, rep, loc, parent_key=key)
    elif isinstance(node, list):
        for item in node:
            walk(item, path, rep, loc, parent_key=parent_key)
    elif isinstance(node, str):
        if parent_key in ENTITY_URL_KEYS and node.startswith(("http://", "https://")):
            dom = domain_of(node)
            if dom and any(dom == g or dom.endswith("." + g) for g in GENERIC_DOMAINS):
                rep.error("URL de domaine générique attribuée à une entité", f"{loc}: {node}")


def check_events_file(data, rep, loc):
    events = data.get("events") if isinstance(data, dict) else None
    if not isinstance(events, list):
        return
    for ev in events:
        src = ev.get("source")
        if src is not None and src not in PUBLIC_EVENT_SOURCES:
            rep.error("event de source hors allowlist", f"{loc}: id={ev.get('id')} source={src!r}")
        if ev.get("type") in EXCLUDED_EVENT_TYPES:
            rep.error("event de type exclu", f"{loc}: id={ev.get('id')} type={ev.get('type')!r}")


def check_file(fp, rep, base):
    loc = str(fp.relative_to(base))
    raw = fp.read_text(errors="replace")
    for m in set(LEAKY_STRINGS.findall(raw)):
        # Retrouver un extrait pour le rapport
        idx = raw.lower().find(m.lower())
        rep.error("chaîne locale ou secret", f"{loc}: …{raw[max(0, idx - 20):idx + 60]!r}…")
    if fp.suffix not in (".json", ".geojson"):
        return
    if fp.name == "__data.json":
        # Sérialisation SvelteKit `devalue` : clés→indices, illisible structurellement.
        # Le contenu vient du snapshot déjà contrôlé ; on se limite à un signal texte.
        for token in ('"hypothesis"', '"unverified"', '"retracted"'):
            if token in raw:
                rep.warn("token de confidence privée dans un __data.json", f"{loc}: {token}")
        return
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        rep.error("JSON invalide", f"{loc}: {exc}")
        return
    walk(data, fp, rep, loc)
    if fp.name == "events.json":
        check_events_file(data, rep, loc)


# ── Invariant de périmètre ───────────────────────────────────────────────────
# Le site d'une commune publie les fiches de cette commune. Si la majorité des
# fiches publiées relève d'ailleurs, le classement C1/C2 n'a pas tourné et le
# site est devenu l'annuaire de l'intercommunalité — c'est arrivé le 14/08/2026
# sur deux instances neuves.
#
# Mesuré ce jour-là sur quatre snapshots : instances correctes 94,4 % et 94,6 %,
# instances non classées 23,8 % et 57,4 %. Le seuil bloquant est donc placé à la
# majorité simple, qui est aussi la règle éditoriale énonçable : un site
# communal doit publier majoritairement sa commune. L'avertissement à 80 %
# signale la dérive avant qu'elle ne devienne bloquante.
#
# Le contrôle lit `entity_index.json` et la commune déclarée dans les règles :
# il ne touche pas à la base et n'importe pas le builder — même principe que le
# reste de ce fichier. Il porte donc sur le RÉSULTAT publié, et attraperait une
# fuite même si le builder classait correctement puis publiait de travers.
PART_MIN_BLOQUANTE = 0.50
PART_MIN_AVERTISSEMENT = 0.80


def check_perimetre(base, rep):
    fp = base / "entity_index.json"
    if not fp.is_file():
        return
    commune = (RULES.get("project") or {}).get("commune")
    if not commune:
        rep.warn("périmètre non vérifiable",
                 f"{fp.name}: publication_rules.project.commune absent")
        return
    try:
        entities = json.loads(fp.read_text()).get("entities") or []
    except json.JSONDecodeError:
        return  # déjà signalé par check_file

    communes = [e.get("c") for e in entities if e.get("c")]
    if not communes:
        return
    par_commune = {}
    for c in communes:
        par_commune[c] = par_commune.get(c, 0) + 1
    part = par_commune.get(commune, 0) / len(communes)
    top, n_top = max(par_commune.items(), key=lambda kv: kv[1])

    detail = (f"{commune} = {par_commune.get(commune, 0)}/{len(communes)} "
              f"({part:.1%}) ; commune la plus publiée : {top} ({n_top})")
    if top != commune or part < PART_MIN_BLOQUANTE:
        rep.error(
            "le site publie majoritairement une autre commune "
            "(classement de périmètre non appliqué ?)", detail)
    elif part < PART_MIN_AVERTISSEMENT:
        rep.warn("part de la commune inférieure aux instances de référence", detail)


def check_fiches_orphelines(base, rep):
    """Toute fiche servie doit correspondre à une entité publiée.

    Ce contrôle manquait, et son absence a laissé passer la seule vraie fuite du
    dispositif : le 19/08/2026, deux sites en ligne servaient des fiches
    `entite/<id>.json` d'entités écartées par le filtre, personnes physiques
    comprises. Le builder écrivait par-dessus l'ancien contenu sans purger, et la
    synchro miroir recopiait les périmées. Rien ne criait, parce que la PAGE de
    ces entités rendait bien 404 : seul le fichier de données restait joignable.

    D'où la règle que ce fichier applique partout ailleurs et qui valait ici
    aussi : contrôler ce qui est SERVI, jamais ce que le builder croit avoir
    produit. Le builder purge désormais — ce contrôle est là pour le cas où il
    cesserait de le faire.
    """
    dossier = base / "entite"
    fp = base / "entities.json"
    if not dossier.is_dir() or not fp.is_file():
        return
    try:
        entities = json.loads(fp.read_text()).get("entities") or []
    except json.JSONDecodeError:
        return  # déjà signalé par check_file
    publies = {str(e.get("id")) for e in entities}
    # Toutes signalées : c'est `Report.dump()` qui tronque l'affichage et annonce
    # le compte exact. Tronquer ici ferait mentir ce compte.
    for f in sorted(dossier.glob("*.json"), key=lambda p: p.stem):
        if f.stem not in publies:
            rep.error("fiche servie pour une entité non publiée", f"entite/{f.name}")


# Champs dont la valeur est un identifiant d'entité, et qui PROMETTENT donc une
# fiche `/entite/<id>`. La liste est explicite plutôt que déduite d'un suffixe :
# `id`, `from_id` ou `event_id` désignent autre chose, et un contrôle qui se
# trompe de champ finit désactivé.
CHAMPS_RENVOI = (
    "entity_id", "entite_id", "acteur_id", "person_id",
    "demandeur_entity_id", "titulaire_id", "acheteur_id",
    "titulaire_entity_id", "acheteur_entity_id", "autre_id",
    "from_id", "to_id",
)

# Fichiers qui portent volontairement un identifiant sans promettre de fiche.
# Un enregistrement s'en dispense en portant `"fiche": false` — voir
# `elus_rne.json`, où la composition d'un conseil municipal est publiée (donnée
# du RNE, registre public) sans que chaque élu ait droit à une page.
CLE_SANS_FICHE = "fiche"


def check_renvois_sortants(base, rep):
    """Tout identifiant publié qui promet une fiche doit désigner une fiche.

    Symétrique de `check_fiches_orphelines`, et il manquait. Celui-là vérifiait
    qu'aucune fiche n'est servie sans entité publiée ; personne ne vérifiait le
    sens inverse — un JSON public qui renvoie vers une fiche ABSENTE.

    Le défaut a vécu en production sur deux sites : `/elus` liait
    `/entite/<id>` pour tous les conseillers municipaux des communes de
    l'intercommunalité, dont 78 à 90 % n'ont pas de fiche (le filtre de
    périmètre ne l'accorde qu'à ceux qui siègent au conseil communautaire).
    152 liens morts sur Lasalle, 176 sur Brassac, 191 sur Saillans. Le
    contrôleur rendait « 0 violation » : il regardait le contenu des fiches, pas
    les promesses de lien entre les fichiers qu'il produit.

    C'est un invariant de CONTRAT DE DONNÉES, pas d'affichage : le snapshot est
    publié sous ODbL et lu par des tiers, qui suivent les identifiants sans
    avoir de page pour leur pardonner.

    Relevé par un audit externe le 21/08/2026. Second passage du même
    audit : le contrôle ne lisait que la racine et `fiche: false`
    dispensait tout un sous-arbre — deux façons d'annoncer un invariant
    plus large que ce qu'il tenait. Corrigé le jour même.
    """
    fp = base / "entities.json"
    if not fp.is_file():
        return
    try:
        entities = json.loads(fp.read_text()).get("entities") or []
    except json.JSONDecodeError:
        return  # déjà signalé par check_file
    publies = {e.get("id") for e in entities}
    if not publies:
        return  # base vide : rien à promettre, rien à contrôler

    morts = {}          # (fichier, champ) → {ids}
    occurrences = {}    # (fichier, champ) → compte

    def parcourir(noeud, fichier):
        if isinstance(noeud, dict):
            # Un enregistrement peut dire explicitement qu'il ne promet rien —
            # mais la dispense ne couvre QUE ses propres champs de renvoi. Elle
            # coupait la descente entière : un objet imbriqué sous une ligne
            # `fiche: false` échappait au contrôle sans l'avoir demandé.
            # `elus_rne.json` est plat aujourd'hui, il ne le restera pas.
            dispense = noeud.get(CLE_SANS_FICHE) is False
            for cle, val in noeud.items():
                if cle in CHAMPS_RENVOI and isinstance(val, int):
                    if not dispense and val not in publies:
                        morts.setdefault((fichier, cle), set()).add(val)
                        occurrences[(fichier, cle)] = occurrences.get((fichier, cle), 0) + 1
                else:
                    parcourir(val, fichier)
        elif isinstance(noeud, list):
            for v in noeud:
                parcourir(v, fichier)

    # `rglob`, pas `glob` : les fiches `entite/<id>.json` sont servies comme le
    # reste et portent des renvois (`relations`, `flows`, `marches`) que la
    # racine n'a pas. Un contrôle limité à la racine annonçait un invariant
    # qu'il ne tenait que sur une partie du snapshot — et `relations.json`
    # peut être propre pendant qu'une fiche pré-résolue renvoie dans le vide.
    for f in sorted(base.rglob("*.json")):
        rel = f.relative_to(base)
        if "node_modules" in rel.parts:
            continue
        try:
            parcourir(json.loads(f.read_text()), str(rel))
        except json.JSONDecodeError:
            continue  # déjà signalé par check_file

    for (fichier, champ), ids in sorted(morts.items()):
        rep.error(
            "renvoi vers une fiche non publiée",
            f"{fichier} · {champ} : {len(ids)} identifiant(s) mort(s), "
            f"{occurrences[(fichier, champ)]} occurrence(s) "
            f"— ex. {sorted(ids)[:5]}")


def check_dir(base, rep):
    for fp in sorted(base.rglob("*")):
        if not fp.is_file():
            continue
        rel = fp.relative_to(base)
        if "node_modules" in rel.parts:
            continue
        if FORBIDDEN_FILENAMES.search(fp.name):
            rep.error("fichier interdit dans le répertoire publié", str(rel))
            continue  # inutile de scanner : il doit disparaître
        rep.files += 1
        if fp.suffix in (".json", ".geojson", ".html", ".js", ".txt", ".md", ".css"):
            check_file(fp, rep, base)
    check_perimetre(base, rep)
    check_fiches_orphelines(base, rep)
    check_renvois_sortants(base, rep)


def main(argv):
    en_json = "--json" in argv
    targets = [Path(a) for a in argv if not a.startswith("-")] or [
        ROOT / "dashboard" / "static" / "public_api",
        ROOT / "public" / "static" / "data",
        ROOT / "public" / "build",
    ]
    rep = Report()
    scanned = []
    for t in targets:
        if t.is_dir():
            scanned.append(t)
            check_dir(t, rep)
    if not scanned:
        absent = "Aucun répertoire de snapshot trouvé."
        if en_json:
            print(json.dumps({"ok": False, "repertoires": [], "fichiers": 0,
                              "erreurs": [], "avertissements": [],
                              "compte_erreurs": 0, "compte_avertissements": 0,
                              "rapport": absent}, ensure_ascii=False))
        else:
            print(absent, file=sys.stderr)
        return 2

    n_err = sum(len(v) for v in rep.errors.values())
    n_warn = sum(len(v) for v in rep.warnings.values())
    lignes = [f"Répertoires : {', '.join(str(s) for s in scanned)}",
              f"Fichiers inspectés : {rep.files}",
              *rep.lignes(),
              "",
              f"{n_err} violation(s) bloquante(s), {n_warn} avertissement(s).",
              "ÉCHEC — ne pas publier ce snapshot." if n_err
              else "OK — étanchéité vérifiée sur les règles connues."]

    if en_json:
        print(json.dumps({
            "ok": not n_err,
            "repertoires": [str(s) for s in scanned],
            "fichiers": rep.files,
            "erreurs": rep.groupes(rep.errors),
            "avertissements": rep.groupes(rep.warnings),
            "compte_erreurs": n_err,
            "compte_avertissements": n_warn,
            "rapport": "\n".join(lignes),
        }, ensure_ascii=False, indent=2))
    else:
        print("\n".join(lignes))
    return 1 if n_err else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
