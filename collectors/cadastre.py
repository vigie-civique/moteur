"""
cadastre.py — Le parcellaire de la commune (plan cadastral informatisé, Etalab).

Une délibération dit « parcelle AC 323 », un acte d'urbanisme dit « section B
n° 1204 » : sans le parcellaire, ces références ne désignent rien qu'on puisse
situer. Le fichier d'Etalab donne, pour chaque parcelle, sa référence, sa
contenance et son tracé — de quoi RÉSOUDRE une référence citée dans un acte, et
poser sur la carte une mutation qui n'avait pas d'adresse.

🔴 CE QUE LE CADASTRE OUVERT NE DIT PAS : QUI POSSÈDE.

La proposition d'audit visait « l'emprise du foncier communal ». Elle n'est pas
atteignable ici : le plan cadastral ouvert porte la géométrie et la contenance,
jamais le propriétaire. La propriété se lit dans les fichiers fonciers (MAJIC),
dont l'accès est restreint et soumis à autorisation. Ce collecteur ne prétend
donc pas dire ce que la commune possède — il dit ce qu'est chaque parcelle, et
laisse la propriété à la source qui l'établit.

⚠️ LA RÉFÉRENCE DE DVF N'EST PAS L'IDENTIFIANT DU CADASTRE. DVF écrit une
section et un numéro (`AC` / `0323`) ; le cadastre écrit un identifiant de
quatorze caractères qui colle le code INSEE, le préfixe de commune déléguée, la
section CALÉE SUR DEUX CARACTÈRES et le numéro sur quatre — `30140` + `000` +
`0A` + `0028`. Rapprocher les deux sans ce calage ne trouve rien, et le silence
se lirait comme « aucune parcelle connue ».

⚠️ ET LE PLAN EST UN ÉTAT, PAS UNE HISTOIRE. Le millésime publié décrit les
parcelles TELLES QU'ELLES SONT ; une parcelle vendue puis divisée n'y figure
plus sous son ancien numéro. Mesuré sur la commune d'essai : 2 des 339 mutations
DVF (0,6 %) citent une référence que le plan courant ne connaît plus — ce ne
sont ni des fautes de DVF ni un défaut de collecte, ce sont des parcelles qui
ont changé depuis la vente. Le compte est publié plutôt que tu.

Source : `cadastre.data.gouv.fr`, millésime courant, un fichier par commune.

Usage :
  python3 -m collectors.cadastre
  python3 -m collectors.cadastre --insee 30140
  python3 -m collectors.cadastre --stats
"""
import argparse
import gzip
import json
import time
import urllib.request

from .archive import HEADERS, archive_fetch
from .config import COMMUNES, NATIONAL_STORE, REQUEST_DELAY, communes_du_step
from .db import get_conn, transaction
from .national_store import ecrire_atomiquement, est_frais

SOURCE = "cadastre"
BASE = ("https://cadastre.data.gouv.fr/data/etalab-cadastre/latest/geojson/"
        "communes/{dep}/{insee}/cadastre-{insee}-parcelles.json.gz")
CACHE = NATIONAL_STORE / "cadastre"

# Le plan est mis à jour tous les trimestres environ ; une parcelle bouge peu.
CACHE_JOURS = 90


def _departement(insee: str) -> str:
    """`30140` → `30`, `2A004` → `2A`, `97401` → `974`."""
    return insee[:3] if insee.startswith("97") else insee[:2]


def telecharger(insee: str) -> bytes:
    """Le parcellaire de la commune, depuis le magasin ou depuis la source."""
    cache = CACHE / f"cadastre-{insee}-parcelles.json.gz"
    if est_frais(cache, CACHE_JOURS):
        return cache.read_bytes()
    url = BASE.format(dep=_departement(insee), insee=insee)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=180) as r:
        brut = r.read()
        archive_fetch(SOURCE, url, brut, content_type=r.headers.get_content_type(),
                      http_status=r.status)
    ecrire_atomiquement(cache, brut)
    return brut


def identifiant_dvf(insee: str, section: str, numero: str,
                    prefixe: str = "000") -> str:
    """La référence telle que DVF l'écrit → l'identifiant du cadastre.

    La section est calée à DEUX caractères par la gauche (`A` → `0A`), le numéro
    à QUATRE (`28` → `0028`). C'est ce calage qui manquait pour que les deux
    sources se parlent.
    """
    section = (section or "").strip().upper()
    numero = (numero or "").strip()
    if not section or not numero:
        return ""
    return f"{insee}{(prefixe or '000').zfill(3)}{section.rjust(2, '0')}{numero.zfill(4)}"


def centroide(geom: dict) -> tuple[float | None, float | None]:
    """Le centre des sommets du contour — suffisant pour poser un repère.

    Ce n'est pas le centre de masse ; sur une parcelle, l'écart se compte en
    mètres et ne change rien à ce qu'on en fait (situer, pas mesurer).
    """
    try:
        anneau = geom["coordinates"][0]
    except (KeyError, IndexError, TypeError):
        return None, None
    if not anneau:
        return None, None
    return (sum(p[1] for p in anneau) / len(anneau),
            sum(p[0] for p in anneau) / len(anneau))


def ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cadastre_parcelles (
            id          TEXT PRIMARY KEY,     -- identifiant à 14 caractères
            insee       TEXT NOT NULL,
            prefixe     TEXT,
            section     TEXT,
            numero      TEXT,
            contenance  INTEGER,              -- en m², telle que le cadastre l'écrit
            lat         REAL,
            lng         REAL,
            arpente     INTEGER,
            maj_source  TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_parcelle_ref"
                 " ON cadastre_parcelles(insee, section, numero)")
    conn.commit()


def import_commune(insee: str, commune_nom: str) -> dict:
    brut = telecharger(insee)
    traits = json.loads(gzip.decompress(brut)).get("features") or []
    releve = {"parcelles": len(traits), "contenance": 0, "dvf_situees": 0,
              "dvf_sans_parcelle": 0}

    lignes = []
    for f in traits:
        p = f.get("properties") or {}
        lat, lng = centroide(f.get("geometry") or {})
        contenance = p.get("contenance") or 0
        releve["contenance"] += contenance
        lignes.append((p.get("id"), insee, p.get("prefixe"), p.get("section"),
                       p.get("numero"), contenance, lat, lng,
                       int(bool(p.get("arpente"))), p.get("updated")))

    with transaction() as conn:
        ensure_table(conn)
        for l in lignes:
            conn.execute(
                "INSERT INTO cadastre_parcelles"
                " (id,insee,prefixe,section,numero,contenance,lat,lng,arpente,maj_source)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET contenance=excluded.contenance,"
                " lat=excluded.lat, lng=excluded.lng, maj_source=excluded.maj_source", l)

        # ── Ce que le parcellaire rend aux mutations ────────────────────────
        # Une mutation DVF sans coordonnées n'apparaît sur aucune carte. Sa
        # parcelle, elle, en a. Rien n'est écrasé : seule une position ABSENTE
        # est complétée, et la source de la position reste vérifiable puisque la
        # référence cadastrale est déjà en base.
        manquantes = conn.execute(
            "SELECT id, insee, section, numero FROM dvf_transactions"
            " WHERE (lat IS NULL OR lng IS NULL) AND insee=?", (insee,)).fetchall()
        for m in manquantes:
            ref = identifiant_dvf(m["insee"], m["section"], m["numero"])
            parcelle = conn.execute(
                "SELECT lat, lng FROM cadastre_parcelles WHERE id=?", (ref,)).fetchone()
            if parcelle and parcelle["lat"] is not None:
                conn.execute("UPDATE dvf_transactions SET lat=?, lng=? WHERE id=?",
                             (parcelle["lat"], parcelle["lng"], m["id"]))
                releve["dvf_situees"] += 1

        # Contrôle de cohérence : une référence citée par DVF que le plan ne
        # connaît plus. Le plus souvent, la parcelle a été divisée ou remembrée
        # depuis la vente ; parfois, c'est une commune déléguée dont le préfixe
        # n'est pas `000`. Les deux méritent d'être comptées, pas ignorées.
        for r in conn.execute(
                "SELECT insee, section, numero FROM dvf_transactions WHERE insee=?",
                (insee,)):
            ref = identifiant_dvf(r["insee"], r["section"], r["numero"])
            if ref and not conn.execute(
                    "SELECT 1 FROM cadastre_parcelles WHERE id=?", (ref,)).fetchone():
                releve["dvf_sans_parcelle"] += 1

    print(f"  [cadastre] {commune_nom} — {releve['parcelles']} parcelle(s), "
          f"{releve['contenance'] / 1e6:.2f} km² cadastrés"
          + (f", {releve['dvf_situees']} mutation(s) situées"
             if releve["dvf_situees"] else "")
          + (f" ; {releve['dvf_sans_parcelle']} référence(s) DVF absente(s) du "
             "plan courant (parcelle divisée ou remembrée depuis)"
             if releve["dvf_sans_parcelle"] else ""))
    return releve


def run(insee: str | None = None) -> int:
    cibles = [insee] if insee else communes_du_step("cadastre")
    total = 0
    for i, code in enumerate(cibles):
        nom = COMMUNES.get(code, {}).get("nom", code)
        try:
            total += import_commune(code, nom)["parcelles"]
        except Exception as e:                          # noqa: BLE001
            print(f"  [cadastre] {nom} — ÉCHEC : {e}")
        if i < len(cibles) - 1:
            time.sleep(REQUEST_DELAY)
    print(f"[cadastre] {total} parcelle(s) sur {len(cibles)} commune(s)")
    return total


def stats():
    conn = get_conn()
    ensure_table(conn)
    for r in conn.execute(
            "SELECT insee, COUNT(*) n, SUM(contenance) c,"
            " COUNT(DISTINCT section) s FROM cadastre_parcelles"
            " GROUP BY insee ORDER BY insee"):
        print(f"  {r['insee']} — {r['n']:>6} parcelle(s), {r['s']} section(s), "
              f"{(r['c'] or 0) / 1e6:.2f} km²")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--insee", help="une seule commune")
    p.add_argument("--stats", action="store_true")
    a = p.parse_args()
    if a.stats:
        stats()
    else:
        run(a.insee)
