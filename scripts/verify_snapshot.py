#!/usr/bin/env python3
"""Contrôleur d'étanchéité du snapshot public — écrit comme un adversaire.

Indépendant de build_public_snapshot.py : il ne partage aucun code avec le
builder, lit config/publication_rules.json et attaque le répertoire publié.
Si le builder et le contrôleur ont le même bug, la fuite passe — c'est
précisément pourquoi ce fichier ne doit jamais importer le builder ni être
« aligné » sur lui. Toute assertion retirée ici est une décision éditoriale.

Usage :
    ~/venvs/agents/bin/python3 scripts/verify_snapshot.py [DIR ...]
    (défaut : dashboard/static/public_api, public/static/data, public/build)

Sortie : rapport groupé par règle, exit 1 à la moindre violation bloquante.
À câbler à la fin de toute génération/déploiement : un build qui fuit échoue.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RULES = json.loads((ROOT / "config" / "publication_rules.json").read_text())

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

    def dump(self):
        for label, bucket in (("BLOQUANT", self.errors), ("avertissement", self.warnings)):
            for rule, examples in sorted(bucket.items()):
                print(f"[{label}] {rule} — {len(examples)} cas")
                for ex in examples[:MAX_EXAMPLES]:
                    print(f"    {ex}")
                if len(examples) > MAX_EXAMPLES:
                    print(f"    … {len(examples) - MAX_EXAMPLES} autres")


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


def main(argv):
    targets = [Path(a) for a in argv] or [
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
        print("Aucun répertoire de snapshot trouvé.", file=sys.stderr)
        return 2
    print(f"Répertoires : {', '.join(str(s) for s in scanned)}")
    print(f"Fichiers inspectés : {rep.files}")
    rep.dump()
    n_err = sum(len(v) for v in rep.errors.values())
    n_warn = sum(len(v) for v in rep.warnings.values())
    print(f"\n{n_err} violation(s) bloquante(s), {n_warn} avertissement(s).")
    if n_err:
        print("ÉCHEC — ne pas publier ce snapshot.")
        return 1
    print("OK — étanchéité vérifiée sur les règles connues.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
