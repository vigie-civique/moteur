"""cle_acte.py — l'identité datée d'un acte : une clé lisible, stable, qui sert d'ancre.

Jusqu'au 03/10/2026, la page publique d'un acte était `/deliberations/{annee}#a{events.id}`.
Or `events.id` change à chaque rejeu — recollecte, ré-OCR, re-découpage d'un
procès-verbal. Un lien posé aujourd'hui dans un dossier, un courriel ou un
article cassait au rejeu suivant, sans que rien ne le signale : l'ancre
tombait sur un autre acte de la même année, ou sur rien.

La clé reprend l'identité que la collecte utilisait DÉJÀ pour dédoublonner
(`collectors/conseils.py::enregistrer_deliberation`) et l'écrit une fois pour
toutes, ici. Collecte, snapshot et résolveur de citations l'appellent ; aucun
ne la recompose à sa façon — trois définitions de « le même acte » finiraient
par désigner trois actes différents.

    c-2021-41              commune, 2021, acte n° 41
    cc-2025-12             intercommunalité, 2025, acte n° 12
    c-2021-03-04-s3        sans numéro d'acte : date de séance + n° dans la séance
    c-2021-03-04-t1a2b3c4  sans aucun numéro : date + empreinte du titre — FAIBLE
    c-2021-03-04           la séance elle-même (conseil municipal du 04/03/2021)

Trois règles, toutes héritées de la docstring de `enregistrer_deliberation` :

  - un numéro d'acte n'est unique que DANS SON ANNÉE (une intercommunalité
    reprend à 1 en janvier) : l'année entre dans la clé ;
  - c'est l'ANNÉE qui compte, pas la date : un portail d'actes affiche la date
    de télétransmission avant que la date de séance ne soit lue, et le même acte
    doit garder sa clé quand elle change ;
  - la PORTÉE (commune ou intercommunalité) vient du TYPE d'événement, comme
    dans `conseils.PORTEES` — jamais du texte de l'acte.

⚠️ Le dernier repli (date + titre) est une clé FAIBLE : il suffit qu'une
relecture OCR corrige une lettre du titre pour qu'elle change. Elle reste utile
pour dédoublonner, mais elle n'est jamais présentée comme stable : le site
n'ancre pas dessus (il garde `#a{id}`), et un lien de dossier qui y mène est
signalé comme tel.

Ce module n'importe rien du reste des collecteurs : le snapshot et l'API le
chargent sans `pdfplumber` ni réseau.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

#: Le préfixe de portée, par type d'événement. Le miroir de `conseils.PORTEES`
#: (`seance` et `delib` de chaque portée) — `tests/test_cle_acte.py` vérifie
#: que les deux tables disent la même chose.
PREFIXE_PAR_TYPE = {
    "deliberation": "c",
    "conseil_municipal": "c",
    "deliberation_cc": "cc",
    "conseil_communautaire": "cc",
}
TYPES_ACTES = ("deliberation", "deliberation_cc")
TYPES_SEANCES = ("conseil_municipal", "conseil_communautaire")

#: Le libellé d'une portée, pour l'humain qui lit une clé.
ASSEMBLEE = {"c": "Conseil municipal", "cc": "Conseil communautaire"}

#: Le type d'acte et de séance d'un préfixe — le chemin inverse.
TYPE_ACTE = {"c": "deliberation", "cc": "deliberation_cc"}
TYPE_SEANCE = {"c": "conseil_municipal", "cc": "conseil_communautaire"}

#: Ce qu'une clé peut contenir : elle sert telle quelle d'ancre d'URL et
#: d'attribut `id`, sans échappement.
FORME = re.compile(r"^(c|cc)-\d{4}(-[a-z0-9]+)+$")

_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


@dataclass(frozen=True)
class Cle:
    valeur: str
    #: Vraie pour le repli (date, titre) : jamais présentée comme stable.
    faible: bool = False
    #: Ce qui l'a établie : numero | seance | titre | date (une séance).
    par: str = "numero"

    def __str__(self) -> str:
        return self.valeur


def _ascii(texte: str) -> str:
    return (unicodedata.normalize("NFKD", texte)
            .encode("ascii", "ignore").decode().lower())


def numero_normalise(numero, annee: str | None = None) -> str | None:
    """Un numéro d'acte tel qu'il entre dans la clé : minuscules, chiffres,
    tirets — rien qui ait besoin d'être échappé dans une URL.

    « 41 », « n°41 », « 041 » et « 41/2021 » (en 2021) donnent tous « 41 » :
    ce sont des écritures du même numéro, que les portails et les registres
    alternent d'une année à l'autre. L'année n'est retirée que si elle est
    SÉPARÉE du reste (« 41/2021 », « 2021-041 ») : dans « DE2026116BIS »,
    rien ne dit où elle finit, et deviner fabriquerait un autre numéro.
    """
    if numero is None:
        return None
    n = _ascii(str(numero)).strip()
    n = re.sub(r"^(?:numero|num|no|n)\.?\s*(?=\d)", "", n)
    morceaux = [m for m in re.split(r"[^a-z0-9]+", n) if m]
    if annee and len(morceaux) > 1:
        morceaux = [m for m in morceaux if m != annee] or morceaux
    morceaux = [m.lstrip("0") or "0" if m.isdigit() else m for m in morceaux]
    sortie = "-".join(morceaux)
    return sortie or None


def _jour(date: str | None) -> tuple[str, str] | None:
    """(année, « AAAA-MM-JJ ») d'une date ISO, ou None."""
    m = _DATE.match(date or "")
    if not m:
        return None
    return m.group(1), f"{m.group(1)}-{m.group(2)}-{m.group(3)}"


def empreinte_titre(titre: str | None) -> str:
    """Huit caractères qui ne dépendent ni de la casse ni des espaces : un titre
    relu à l'OCR qui gagne une majuscule garde sa clé. Une lettre corrigée la
    change — c'est pourquoi la clé est dite faible."""
    t = re.sub(r"\s+", " ", _ascii(titre or "")).strip()
    return hashlib.sha256(t.encode()).hexdigest()[:8]


def cle_acte(type_: str, date: str | None, numero_acte=None, numero_seance=None,
             titre: str | None = None) -> Cle | None:
    """La clé d'une délibération. None si le type n'est pas un acte d'assemblée,
    ou si l'acte n'a pas de date (sans année, un numéro ne désigne rien).

    L'ordre des replis est celui de `enregistrer_deliberation` : numéro d'acte
    dans l'année, à défaut numéro dans la séance du jour, à défaut le titre.
    """
    prefixe = PREFIXE_PAR_TYPE.get(type_)
    jour = _jour(date)
    if type_ not in TYPES_ACTES or not prefixe or not jour:
        return None
    annee, iso = jour
    numero = numero_normalise(numero_acte, annee)
    if numero:
        return Cle(f"{prefixe}-{annee}-{numero}", par="numero")
    rang = numero_normalise(numero_seance)
    if rang:
        return Cle(f"{prefixe}-{iso}-s{rang}", par="seance")
    return Cle(f"{prefixe}-{iso}-t{empreinte_titre(titre)}", faible=True, par="titre")


def cle_seance(type_: str, date: str | None) -> Cle | None:
    """La clé d'une séance : son assemblée et son jour — l'identité que pose
    `conseils.enregistrer_seance`. Elle est le préfixe des clés de repli de ses
    actes : `c-2021-03-04-s3` est le troisième acte de la séance `c-2021-03-04`."""
    prefixe = PREFIXE_PAR_TYPE.get(type_)
    jour = _jour(date)
    if type_ not in TYPES_SEANCES or not prefixe or not jour:
        return None
    return Cle(f"{prefixe}-{jour[1]}", par="date")


def cle_de_ligne(type_: str, date: str | None, metadata: dict | None,
                 titre: str | None = None) -> Cle | None:
    """La clé d'une ligne `events`, acte ou séance, lue dans ses métadonnées."""
    if type_ in TYPES_SEANCES:
        return cle_seance(type_, date)
    m = metadata if isinstance(metadata, dict) else {}
    return cle_acte(type_, date, m.get("numero_acte"), m.get("numero_seance"), titre)


def seance_de(valeur: str) -> str | None:
    """La clé de la séance d'un acte, quand la clé de l'acte la contient
    (replis par séance et par titre). Un acte numéroté ne dit pas son jour."""
    m = re.match(r"^((?:c|cc)-\d{4}-\d{2}-\d{2})-[st][a-z0-9]+$", valeur or "")
    return m.group(1) if m else None


# ─── La colonne en base ──────────────────────────────────────────────────────

def a_la_colonne(conn) -> bool:
    return "cle_acte" in {r[1] for r in conn.execute("PRAGMA table_info(events)")}


def assurer_colonne(conn) -> None:
    """`events.cle_acte` et son index, sur une base antérieure au 03/10/2026.

    Même rattrapage que `collectors/db.py::_COLONNES_AJOUTEES` (qui la déclare
    aussi) : l'API ne passe pas par `init_db()`. La colonne n'est PAS unique —
    une base réelle porte des collisions (deux fiches pour le même acte, ou deux
    actes que rien ne distingue), et une contrainte ferait échouer la collecte
    au lieu de les montrer. `scripts/migrer_cles_actes.py` les liste.
    """
    if not a_la_colonne(conn):
        conn.execute("ALTER TABLE events ADD COLUMN cle_acte TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_cle_acte ON events(cle_acte)")
