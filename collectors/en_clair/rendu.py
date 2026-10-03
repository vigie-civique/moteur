#!/usr/bin/env python3
"""Rend « le conseil en clair » d'une séance en A4 : avant, après, comprendre, documents.

    python -m collectors.en_clair.rendu data/conseils/2026-03-04-cc/releve.json

Écrit `en-clair.html` et `en-clair.pdf` à côté du relevé. Le PDF est imprimé
par Chrome en mode headless : aucune dépendance Python à installer, et les
polices sont celles du Mac (pas de réseau). `scripts/resume_conseils.py`
réutilise `feuilles()` pour assembler toutes les séances en un document.

Garde-fous :
  - le relevé passe d'abord par `collectors/en_clair/verifier.py` ; à la première
    faute, rien n'est rendu ;
  - tant que `origine.relu_par` est vide, chaque feuille porte « À RELIRE » ;
  - une feuille qui déborde continue sur la page suivante : rien n'est coupé
    en silence (le premier gabarit, à hauteur fixe, masquait le surplus).

Variantes, déclarées dans le relevé :
  en_clair.avant.statut = "non_publie"  pas de convocation publiée avant la
      séance : la feuille le dit, et l'ordre du jour est donné comme
      RECONSTITUÉ depuis les actes ;
  en_clair.apres.statut = "non_publie"  les actes ne sont pas encore en ligne.
"""
from __future__ import annotations

import html
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .verifier import verifier

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]

CSS = """
@page { size: A4; margin: 11mm 12mm; }
:root { --ink:#17232b; --muted:#56646c; --rule:#c9d0d0; --accent:#1f5a73;
  --accent-soft:#dbe8ee; --ok:#2e6b47; --ok-soft:#e1efe5; --split:#8a5a12;
  --split-soft:#f6ead3; --warn:#8a2c1f; --warn-soft:#f7e3de;
  --display:"Avenir Next Condensed","Arial Narrow",sans-serif;
  --body:"Charter","Iowan Old Style",Georgia,serif; --mono:Menlo,monospace; }
* { box-sizing:border-box; }
html { -webkit-print-color-adjust:exact; print-color-adjust:exact; }
body { margin:0; color:var(--ink); background:#fff; font:9.6pt/1.4 var(--body); }
a { color:var(--accent); }
.sheet { position:relative; min-height:275mm; display:flex; flex-direction:column;
  gap:3.2mm; break-after:page; }
.sheet:last-child { break-after:auto; }
.label { font:600 7pt/1 var(--display); letter-spacing:.14em; text-transform:uppercase;
  color:var(--muted); display:flex; justify-content:space-between; gap:4mm; }
.mast { border-bottom:2.2pt solid var(--ink); padding-bottom:2.4mm; display:grid; gap:1.2mm; }
.name { font:700 9pt/1 var(--display); letter-spacing:.1em; text-transform:uppercase; }
h1 { font:700 23pt/1.02 var(--display); margin:0; }
.meta { color:var(--muted); font-size:9pt; }
.box { background:var(--accent-soft); padding:2.6mm 3.2mm; }
.box.warn { background:var(--warn-soft); }
.box b { font-family:var(--display); font-size:10pt; }
ol.agenda { list-style:none; margin:0; padding:0; counter-reset:pt; }
ol.agenda li { display:grid; grid-template-columns:7mm 1fr; padding:1.7mm 0;
  border-bottom:.5pt dotted var(--rule); break-inside:avoid; }
ol.agenda li::before { counter-increment:pt; content:counter(pt, decimal-leading-zero);
  font:8pt/1.5 var(--mono); color:var(--accent); }
ol.agenda b { font:600 10.5pt/1.2 var(--display); }
ol.agenda p { grid-column:2; margin:.6mm 0 0; font-size:8.8pt; color:var(--muted); }
.odj h3, .aussi h3 { font:700 8pt/1 var(--display); letter-spacing:.12em;
  text-transform:uppercase; color:var(--muted); margin:1mm 0 1.4mm; }
.odj ol { columns:2; column-gap:7mm; font-size:8.2pt; line-height:1.35; color:var(--muted);
  margin:0; padding-left:6mm; }
.odj li { break-inside:avoid; }
.facts { display:grid; grid-template-columns:repeat(4,1fr); border:.6pt solid var(--rule); }
.facts div { padding:1.8mm 2.2mm; border-right:.6pt solid var(--rule); }
.facts div:last-child { border-right:0; }
.facts b { display:block; font:700 17pt/1 var(--display); font-variant-numeric:tabular-nums; }
.facts span { font-size:8pt; color:var(--muted); }
.cols { columns:2; column-gap:6mm; column-rule:.5pt solid var(--rule); column-fill:balance; }
.item { break-inside:avoid; padding-bottom:2mm; margin-bottom:2mm;
  border-bottom:.5pt dotted var(--rule); }
.item h2 { font:700 11pt/1.15 var(--display); margin:0 0 .8mm; }
.item.une h2 { font-size:12.5pt; }
.item p { margin:0; font-size:8.9pt; }
.row { display:flex; flex-wrap:wrap; gap:1.5mm; align-items:center; margin-top:1.2mm; }
.acte { font:7.2pt var(--mono); color:var(--muted); }
.vote { font:600 7pt/1 var(--display); letter-spacing:.05em; text-transform:uppercase;
  padding:.8mm 1.4mm; border-radius:1pt; }
.vote.ok { background:var(--ok-soft); color:var(--ok); }
.vote.split { background:var(--split-soft); color:var(--split); }
.aussi ul { margin:0; padding-left:4mm; font-size:8.6pt; }
.foot { border-top:.8pt solid var(--ink); padding-top:1.6mm; font-size:7.4pt;
  color:var(--muted); display:grid; gap:.6mm; margin-top:auto; }
.foot .src { word-break:break-all; }
ul.err { margin:0; padding-left:5mm; font-size:10pt; line-height:1.5; display:grid; gap:2.2mm; }
.item p.pq { margin-top:1mm; font-size:8.5pt; color:var(--ink); border-left:1.6pt solid var(--accent);
  padding-left:2mm; }
.item p.pq b { font:600 7.4pt/1 var(--display); letter-spacing:.06em; text-transform:uppercase;
  color:var(--accent); }
.bloc h3 { font:700 8.4pt/1 var(--display); letter-spacing:.12em; text-transform:uppercase;
  color:var(--accent); margin:0 0 1.6mm; border-bottom:.6pt solid var(--rule); padding-bottom:1mm; }
.sheet.serre { gap:2.2mm; }
.serre .dit p { font-size:8.6pt; line-height:1.35; }
.serre .dit blockquote { margin-top:.6mm; font-size:8.3pt; line-height:1.3; }
.serre ul.suivre { gap:.9mm; font-size:8.6pt; }
.serre dl.mots { font-size:8.1pt; line-height:1.3; }
.dit { break-inside:avoid; padding:1.1mm 0 1.5mm; border-bottom:.5pt dotted var(--rule); }
.dit h4 { font:700 10pt/1.15 var(--display); margin:0 0 .5mm; display:flex; flex-wrap:wrap;
  align-items:baseline; gap:1.5mm 2.5mm; }
.dit h4 .row { margin:0; }
.dit p { margin:0; font-size:8.8pt; }
.dit blockquote { margin:1mm 0 0; padding:.4mm 0 .4mm 2.4mm; border-left:1.6pt solid var(--rule);
  font-style:italic; font-size:8.6pt; color:var(--muted); }
ul.suivre { list-style:none; margin:0; padding:0; display:grid; gap:1.4mm; font-size:8.8pt; }
ul.suivre li { display:grid; grid-template-columns:5mm 1fr; break-inside:avoid; }
ul.suivre li::before { content:"□"; color:var(--accent); font-size:10pt; line-height:1.1; }
dl.mots { columns:3; column-gap:5mm; margin:0; font-size:8.4pt; }
dl.mots div { break-inside:avoid; margin-bottom:1.4mm; }
dl.mots dt { font:700 8.8pt/1.2 var(--display); display:inline; }
dl.mots dd { display:inline; margin:0; }
.tampon { position:absolute; bottom:24mm; right:4mm; transform:rotate(-8deg);
  font:700 26pt/1 var(--display); letter-spacing:.12em; color:rgba(160,40,30,.28);
  border:3pt solid rgba(160,40,30,.28); padding:2mm 5mm; pointer-events:none; }
.ecran, .u-court { display:none; }

/* À l'écran, la même page se lit comme le site : les feuilles deviennent des
   cartes sur fond papier, au corps et aux jetons de la charte publique
   (public/src/routes/+layout.svelte). Sans ce bloc, la page servait le gabarit
   d'impression tel quel : 9 pt, collé aux bords, et 275 mm de hauteur forcée
   qui laissait un vide d'une demi-page sous une feuille courte. */
@media screen {
  :root { --ink:#14202a; --muted:#5c6b72; --rule:#dde2df; --accent:#14556b;
    --accent-soft:#eef3f5; --ok:#2c6e4f; --ok-soft:#e6f1ea; --split:#9a6b12;
    --split-soft:#f7f1e4; --warn:#a4453a; --warn-soft:#f8ebe8;
    --display:"Iowan Old Style","Palatino Linotype",Palatino,"Book Antiqua",Georgia,serif;
    --texte:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
    --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace; }
  body { background:#f6f7f5; font:16px/1.6 var(--texte); -webkit-font-smoothing:antialiased;
    padding:0 1rem 3rem; }
  a { text-underline-offset:2px; }
  .ecran { display:flex; flex-wrap:wrap; gap:.4rem 1rem; align-items:center;
    justify-content:space-between; max-width:820px; margin:0 auto; padding:1rem 0 .2rem;
    font-size:.88rem; color:var(--muted); }
  .ecran a { color:var(--accent); text-decoration:none; }
  .ecran a:hover { text-decoration:underline; }
  .ecran button { font:inherit; color:var(--accent); background:#fff; cursor:pointer;
    border:1px solid var(--rule); border-radius:5px; padding:.3rem .8rem; }
  .ecran button:hover { border-color:var(--accent); }
  .sheet, .sheet.serre { min-height:0; max-width:820px; margin:1.2rem auto 0; gap:1.4rem;
    background:#fff; border:1px solid var(--rule); border-radius:6px;
    padding:2rem 2.6rem 1.6rem; overflow:hidden;
    box-shadow:0 1px 2px rgba(20,32,42,.05), 0 6px 18px rgba(20,32,42,.05); }
  .label { font:600 .72rem/1.3 var(--texte); letter-spacing:.08em; flex-wrap:wrap; }
  .label span:first-child { color:var(--accent); }
  .mast { gap:.5rem; padding-bottom:1.1rem; border-bottom:2px solid var(--ink); }
  .name { font:600 .78rem/1.3 var(--texte); letter-spacing:.08em; color:var(--muted); }
  h1 { font:600 2rem/1.15 var(--display); letter-spacing:-.01em; }
  .meta { font-size:1.02rem; line-height:1.55; }
  .box { padding:.9rem 1.1rem; border-radius:5px; border-left:3px solid var(--accent);
    font-size:.95rem; line-height:1.55; }
  .box.warn { border-left-color:var(--warn); }
  .box b { font:600 1rem var(--texte); }
  ol.agenda li { grid-template-columns:2.4rem 1fr; padding:.8rem 0; }
  ol.agenda li::before { font:.85rem/1.7 var(--mono); }
  ol.agenda b { font:600 1.12rem/1.3 var(--display); }
  ol.agenda p { margin-top:.25rem; font-size:.95rem; line-height:1.55; }
  .odj h3, .aussi h3, .bloc h3 { font:600 .75rem/1.3 var(--texte); letter-spacing:.08em;
    margin:0 0 .7rem; }
  .bloc h3 { padding-bottom:.4rem; }
  .odj ol { font-size:.95rem; line-height:1.5; column-gap:2.4rem; padding-left:1.6rem; }
  .odj li { padding:.15rem 0; }
  .facts { border-radius:5px; overflow:hidden; }
  .facts div { padding:.9rem 1rem; }
  .facts b { font:600 1.9rem/1.1 var(--display); }
  .facts span { display:block; margin-top:.2rem; font-size:.85rem; line-height:1.4; }
  .cols { column-gap:2.6rem; }
  .item { padding-bottom:1rem; margin-bottom:1rem; border-bottom:1px solid var(--rule); }
  .item h2 { font:600 1.2rem/1.3 var(--display); margin:0 0 .35rem; }
  .item.une h2 { font-size:1.4rem; }
  .item p { font-size:.97rem; line-height:1.6; }
  .item p.pq { margin-top:.6rem; font-size:.93rem; padding:.1rem 0 .1rem .8rem; border-left-width:2px; }
  .item p.pq b { display:block; font:600 .7rem/1.6 var(--texte); letter-spacing:.08em; }
  .row { gap:.4rem .5rem; margin-top:.6rem; }
  .acte { font-size:.78rem; }
  .vote { font:600 .7rem/1 var(--texte); letter-spacing:.04em; padding:.3rem .5rem; border-radius:3px; }
  .aussi ul { font-size:.95rem; line-height:1.6; padding-left:1.2rem; }
  .aussi li { margin-bottom:.4rem; }
  .aussi .vote { margin-left:.3rem; vertical-align:.1em; }
  .dit { padding:.8rem 0 1rem; border-bottom:1px solid var(--rule); }
  .dit h4 { font:600 1.1rem/1.3 var(--display); gap:.3rem .7rem; margin-bottom:.3rem; }
  .dit p, .serre .dit p { font-size:.97rem; line-height:1.6; }
  .dit blockquote, .serre .dit blockquote { margin-top:.5rem; padding:.1rem 0 .1rem .9rem;
    border-left-width:2px; font-size:.95rem; line-height:1.55; }
  ul.suivre, .serre ul.suivre { gap:.55rem; font-size:.97rem; line-height:1.55; }
  ul.suivre li { grid-template-columns:1.6rem 1fr; }
  ul.suivre li::before { font-size:1.05rem; line-height:1.4; }
  dl.mots, .serre dl.mots { columns:2; column-gap:2.4rem; font-size:.93rem; line-height:1.55; }
  dl.mots div { margin-bottom:.6rem; }
  dl.mots dt { font:600 1rem/1.4 var(--display); }
  ul.err { font-size:1rem; line-height:1.6; gap:.8rem; padding-left:1.3rem; }
  .foot { border-top:1px solid var(--rule); padding-top:.9rem; font-size:.8rem; line-height:1.5;
    gap:.3rem; }
  .u-long { display:none; }
  .u-court { display:inline; }
  .foot .src { word-break:normal; overflow-wrap:anywhere; }
  .tampon { bottom:5rem; right:1.4rem; font-size:1.8rem; }
}
@media screen and (max-width:720px) {
  body { padding:0 .6rem 2rem; }
  .sheet, .sheet.serre { padding:1.3rem 1.1rem 1.1rem; border-radius:4px; gap:1.1rem; }
  h1 { font-size:1.55rem; }
  .facts { grid-template-columns:repeat(2,1fr); }
  .facts div:nth-child(2n) { border-right:0; }
  .facts div:nth-child(-n+2) { border-bottom:.6pt solid var(--rule); }
  .facts b { font-size:1.5rem; }
  .cols, .odj ol, dl.mots, .serre dl.mots { columns:1; }
  .label { flex-direction:column; gap:.2rem; }
}
@media print { .ecran { display:none; } }
"""


def e(t) -> str:
    """Échappe, et colle ce que la typographie française ne coupe pas :
    les groupes de chiffres (« 2 226 964,89 ») et l'espace avant : ; % €."""
    t = html.escape(str(t))
    while re.search(r"(\d) (\d{3})", t):
        t = re.sub(r"(\d) (\d{3})", "\\1\u202f\\2", t)
    return re.sub(r" ([:;%€])", "\u202f\\1", t)


def date_longue(iso: str) -> str:
    a, m, j = map(int, iso.split("-"))
    return f"{'1er' if j == 1 else j} {MOIS[m - 1]} {a}"


def _vote(actes: dict, numeros: list[int]) -> str:
    """Le vote d'un paragraphe, lu dans ses actes — jamais écrit à la main."""
    if not numeros:
        return ""               # une déclaration n'est pas un vote
    divises, muets = [], []
    for n in numeros:
        v = actes[n].get("vote")
        if v is None:
            muets.append(n)
        elif not v.get("unanimite"):
            parts = [f"{v[k]} {k.rstrip('s') if v[k] == 1 else k}"
                     for k in ("pour", "contre", "abstentions") if v.get(k)]
            divises.append(f"n°{n} : " + " · ".join(parts))
    puces = [f'<span class="vote split">{e(d)}</span>' for d in divises]
    if muets:
        puces.append(f'<span class="vote split">vote non indiqué (n°'
                     f'{", ".join(map(str, muets))})</span>')
    if not puces:
        puces.append('<span class="vote ok">Unanimité</span>')
    return "".join(puces)


def _url_courte(u: str) -> str:
    """« www.lasalle.fr › CM 28.05.26 DELIBERATIONS.pdf » : ce qu'on lit à
    l'écran, où le lien se suit. Le papier garde l'adresse entière."""
    p = urlsplit(u)
    fichier = unquote(p.path.rstrip("/").rsplit("/", 1)[-1])
    return f"{p.netloc} › {fichier}" if fichier else p.netloc or u


def _sources(releve: dict, seule: str | None = None) -> str:
    """Les pièces, avec leur adresse : le lecteur doit pouvoir remonter à tout.
    `seule` : la seule pièce de la séance, quand la feuille ne cite qu'elle."""
    libelles = releve.get("sources_libelles", {})
    lignes = [f'<div class="src">{e(libelles.get(k, k))} : '
              f'<a href="{html.escape(u)}"><span class="u-long">{html.escape(u)}</span>'
              f'<span class="u-court">{html.escape(_url_courte(u))}</span></a></div>'
              for k, u in releve.get("sources_url", {}).items() if seule in (None, k)]
    return "".join(lignes)


def feuilles(releve: dict, relu: str | None = None, liens: dict | None = None) -> str:
    """Les deux feuilles d'une séance, en <section> — sans l'enveloppe HTML.

    `liens` : n° d'acte → URL de l'acte publié (posé par la publication, par
    la clé datée de l'acte). Sans lui — l'aperçu de l'atelier, le PDF —, les
    numéros restent du texte."""
    s, ec = releve["seance"], releve["en_clair"]
    actes = {a["n"]: a for a in releve["actes"]}
    # `relu` : la mention que pose la PUBLICATION quand l'atelier a retenu la
    # séance (« relu à l'atelier le … »). Elle prime sur le relevé, qu'elle ne
    # modifie pas, et ne porte jamais l'adresse du relecteur.
    relu = relu or releve["origine"].get("relu_par")
    tampon = "" if relu else '<div class="tampon">À RELIRE</div>'
    nom = f"{e(s['assemblee_court'])} · le conseil en clair"
    av, ap = ec["avant"], ec["apres"]
    sources = _sources(releve)
    ancre = f'id="seance-{s["date"]}-{releve.get("code", "")}"'

    # ── avant ──
    if av.get("statut") == "non_publie":
        intro = (f'<div class="box warn"><b>Pas de convocation publiée.</b> '
                 f'{e(av["avertissement"])}</div>')
        label_d = "ordre du jour reconstitué après la séance"
    else:
        intro = ""
        label_d = "à diffuser dès la convocation"
    if av.get("encadre"):
        tete, _, reste = av["encadre"].partition(". ")
        intro += f'<div class="box"><b>{e(tete)}.</b> {e(reste)}</div>'
    points = "".join(f"<li><b>{e(p['titre'])}</b><p>{e(p['contexte'])}</p></li>"
                     for p in av.get("points", []))
    odj = ""
    if av.get("ordre_du_jour"):
        odj = (f'<div class="odj"><h3>{e(av.get("titre_odj", "L’ordre du jour complet"))}'
               f' · {len(av["ordre_du_jour"])} points</h3><ol>'
               + "".join(f"<li>{e(x)}</li>" for x in av["ordre_du_jour"]) + "</ol></div>")
    avant = f"""
<section class="sheet" {ancre}>{tampon}
  <div class="label"><span>Feuille 1 · avant la séance</span><span>{label_d}</span></div>
  <div class="mast"><div class="name">{nom}</div><h1>{e(av['titre'])}</h1>
    <div class="meta">{e(av['chapeau'])}</div></div>
  {intro}
  {'<ol class="agenda">' + points + '</ol>' if points else ''}
  {odj}
  <div class="foot"><div>{e(av['pied'])}</div>{sources}</div>
</section>"""

    # ── après ──
    if ap.get("statut") == "non_publie":
        corps = f'<div class="box warn"><b>Actes non publiés.</b> {e(ap["texte"])}</div>'
    else:
        faits = "".join(f"<div><b>{e(c['valeur'])}</b><span>{e(c['dit'])}</span></div>"
                        for c in ap["chiffres"])
        items = ""
        for it in sorted(ap["items"], key=lambda i: not i.get("une")):
            ns = it["actes"]
            items += (f'<div class="item{" une" if it.get("une") else ""}">'
                      f"<h2>{e(it['titre'])}</h2><p>{e(it['texte'])}</p>"
                      + (f'<p class="pq"><b>Pourquoi ça compte</b> {e(it["pourquoi"])}</p>'
                         if it.get("pourquoi") else "")
                      + f'<div class="row">{_vote(actes, ns)}'
                      f'<span class="acte">{"n°" + _liste(ns, liens) if ns else ""}'
                      f'</span></div></div>')
        aussi = "".join(f"<li>{e(a['texte'])} {_vote(actes, a['actes'])}</li>"
                        for a in ap.get("aussi", []))
        corps = (f'<div class="facts">{faits}</div><div class="cols">{items}'
                 + (f'<div class="aussi"><h3>Et aussi</h3><ul>{aussi}</ul></div>' if aussi else "")
                 + "</div>")
    verif = (f"Relevé de {len(releve['actes'])} actes vérifié le "
             f"{date_longue(date.today().isoformat())} : chaque citation, montant et "
             f"chiffre est retrouvé dans les documents sources.") if releve["actes"] else ""
    apres = f"""
<section class="sheet">{tampon}
  <div class="label"><span>Feuille 2 · après la séance</span><span>séance du {date_longue(s['date'])}</span></div>
  <div class="mast"><div class="name">{nom}</div><h1>{e(ap['titre'])}</h1>
    <div class="meta">{e(ap['chapeau'])}</div></div>
  {corps}
  <div class="foot"><div>{e(ap['pied'])}</div>{'<div>' + e(verif) + '</div>' if verif else ''}
    <div>Relevé : {e(releve['origine']['releve'])}{', ' + e(relu) if relu and relu.startswith('relu') else (', relu par ' + e(relu) if relu else ', non relu')}.
    Une erreur ? Signalez-la : chaque correction est publiée.</div>{sources}</div>
</section>"""
    return avant + apres + comprendre(releve, tampon, liens)


def _liste(ns, liens: dict | None = None) -> str:
    """« 41 · 42 », chaque numéro lié à son acte quand il est publié."""
    liens = liens or {}
    return " · ".join(f'<a href="{html.escape(liens[n])}">{n}</a>' if n in liens else str(n)
                      for n in ns)


def _numeros(ns, liens: dict | None = None) -> str:
    return f'<span class="acte">n°{_liste(ns, liens)}</span>' if ns else ""


def comprendre(releve: dict, tampon: str = "", liens: dict | None = None) -> str:
    """Feuille 3 (facultative) : ce qui s'est dit, ce qui reste à suivre, les
    mots de la séance. Absente du relevé, rien n'est rendu.

    Chaque citation y est retrouvée mot pour mot DANS son acte par le
    vérificateur, comme celles des actes : l'éditorial n'est pas la partie
    du document où l'on cesse de contrôler."""
    c = releve["en_clair"].get("comprendre")
    if not c:
        return ""
    s = releve["seance"]
    actes = {a["n"]: a for a in releve["actes"]}
    blocs = []
    if c.get("debats"):
        dits = "".join(
            f'<div class="dit"><h4>{e(d["titre"])}<span class="row">'
            f'{_vote(actes, d.get("actes", []))}{_numeros(d.get("actes"), liens)}</span></h4>'
            f'<p>{e(d["texte"])}</p>'
            + (f'<blockquote>« {e(d["citation"])} »</blockquote>' if d.get("citation") else "")
            + "</div>"
            for d in c["debats"])
        intro = f'<div class="box warn">{e(c["avertissement"])}</div>' if c.get("avertissement") else ""
        blocs.append(f'<div class="bloc"><h3>Ce qui s’est dit</h3>{intro}{dits}</div>')
    if c.get("a_suivre"):
        lis = "".join(f'<li><span>{e(x["texte"])} {_numeros(x.get("actes"), liens)}</span></li>'
                      for x in c["a_suivre"])
        blocs.append(f'<div class="bloc"><h3>À suivre</h3><ul class="suivre">{lis}</ul></div>')
    if c.get("lexique"):
        mots = "".join(f'<div><dt>{e(m["terme"])}</dt> <dd>: {e(m["definition"])}</dd></div>'
                       for m in c["lexique"])
        blocs.append(f'<div class="bloc"><h3>Les mots de la séance</h3><dl class="mots">{mots}</dl></div>')
    return f"""
<section class="sheet serre">{tampon}
  <div class="label"><span>Feuille 3 · comprendre la séance</span><span>séance du {date_longue(s['date'])}</span></div>
  <div class="mast"><div class="name">{e(s['assemblee_court'])} · le conseil en clair</div>
    <h1>{e(c.get('titre', 'Comprendre la séance'))}</h1>
    {'<div class="meta">' + e(c['chapeau']) + '</div>' if c.get('chapeau') else ''}</div>
  {''.join(blocs)}
  <div class="foot"><div>{e(c.get('pied', ''))}</div>{_sources(releve, seule=releve.get('source_actes', 'pv'))}</div>
</section>"""


def erreurs(releve: dict) -> list[str]:
    """Ce que les documents publics de la séance ont de faux ou d'incomplet."""
    return list(releve.get("anomalies_seance", [])) + [
        f"Délibération n°{a['n']} : {a['anomalie']}" for a in releve["actes"] if a.get("anomalie")]


def page_erreurs(releve: dict) -> str:
    """Dernière feuille d'une séance : les défauts relevés dans ses pièces."""
    s = releve["seance"]
    liste = erreurs(releve)
    corps = ("<ul class=\"err\">" + "".join(f"<li>{e(x)}</li>" for x in liste) + "</ul>"
             if liste else "<p>Aucune erreur ni lacune relevée dans les pièces de cette séance.</p>")
    return f"""
<section class="sheet">
  <div class="label"><span>Feuille {4 if releve['en_clair'].get('comprendre') else 3} · les documents</span><span>séance du {date_longue(s['date'])}</span></div>
  <div class="mast"><div class="name">{e(s['assemblee_court'])} · le conseil en clair</div>
    <h1>Ce que les documents publics ont de faux ou d’incomplet</h1>
    <div class="meta">Relevé par Vigie Civique en confrontant les pièces de la séance entre elles
    et avec les séances voisines. Ces constats portent sur les documents, pas sur les décisions.</div></div>
  {corps}
  <div class="foot"><div>Une erreur dans ce relevé ? Signalez-la : chaque correction est publiée.</div>{_sources(releve)}</div>
</section>"""


def document(titre: str, corps: str, retour: tuple[str, str] | None = None) -> str:
    """`retour` : (adresse, libellé) du lien de retour, montré à l'écran
    seulement — la page publiée renvoie à la liste des séances."""
    barre = ""
    if retour:
        barre = (f'<nav class="ecran"><a href="{html.escape(retour[0])}">← {e(retour[1])}</a>'
                 f'<button type="button" onclick="window.print()">Imprimer · PDF</button></nav>')
    return (f'<!doctype html><html lang="fr"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{e(titre)}</title><style>{CSS}</style></head>"
            f"<body>{barre}{corps}</body></html>")


def chrome_disponible() -> bool:
    return Path(CHROME).exists()


def imprimer(html_path: Path) -> Path:
    """HTML → PDF par Chrome headless. Absent (un serveur, par exemple), on s'en
    passe : la page HTML porte sa propre mise en page A4 et s'imprime telle quelle."""
    pdf = html_path.with_suffix(".pdf")
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={pdf}", html_path.as_uri()],
                   check=True, capture_output=True)
    return pdf


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    chemin = Path(sys.argv[1]).expanduser().resolve()
    if fautes := verifier(chemin):
        print("Relevé non conforme — rien n'est rendu :")
        for f in fautes:
            print(f"  ✗ {f}")
        return 1
    releve = json.loads(chemin.read_text())
    s = releve["seance"]
    sortie = chemin.with_name("en-clair.html")
    sortie.write_text(document(
        f"Le conseil en clair · {s['assemblee_court']} · {s['date']}",
        feuilles(releve) + page_erreurs(releve)))
    print(f"{sortie}\n{imprimer(sortie)}")
    if not releve["origine"].get("relu_par"):
        print("⚠ Non relu : les feuilles portent « À RELIRE ».")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
