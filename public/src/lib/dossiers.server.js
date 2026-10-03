// Les dossiers : le seul endroit du site où un humain écrit.
//
// Tout le reste est de la donnée transformée mécaniquement. Un dossier relie des
// faits épars autour d'une question d'intérêt public ; il vit dans l'INSTANCE,
// un fichier markdown par dossier (`dossiers/<slug>.md`), hors du dépôt du
// moteur parce qu'il nomme des personnes (cf. .gitignore).
//
//   ---
//   titre: L'eau à Lasalle
//   chapeau: Deux services d'eau dans une même commune…
//   statut: a_developper    # facultatif : annonce le sujet, sans le corps
//   maj: 2026-09-30
//   ---
//
// Ce qui se publie n'est PLUS décidé ici (01/10/2026). Un dossier sort RETENU à
// l'atelier, et tel qu'il a été relu : c'est le snapshot qui l'établit
// (`collectors/dossiers.py::publiables`) et qui écrit `dossiers.json`. Ce
// fichier ne contient que ce qui sort ; le site ne lit plus `dossiers/`.
//
// Le grand écart : un dossier se lit par un habitant pressé ET par un
// spécialiste. Trois conventions d'écriture, mises en forme ici, le servent :
//
//   ## L'essentiel            → encadré en tête : la réponse en quelques phrases
//   <details class="plus">    → « pour aller plus loin » : le détail, replié
//   <summary>…</summary>        (un bouton de la page déplie tout d'un coup)
//   ## Les mots du dossier    → lexique : chaque sigle expliqué une fois
//
// Chaque partie (`## …`) reçoit une ancre et entre au sommaire.
//
// Seule exception : l'aperçu local avec VIGIE_DOSSIERS_BROUILLONS=1 lit tout
// le répertoire, sans verdict, et marque chaque page d'un bandeau. Un dossier
// `a_developper` annonce son sujet et rien d'autre : ni faits, ni personne
// nommée, donc rien à quoi répondre (le statut vient de la v1).
import { readdirSync, readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { markdownSur } from '$lib/markdown.js'
import { lireJSON } from '$lib/donnees.server.js'

const REPERTOIRE = resolve(process.env.VIGIE_DOSSIERS_DIR || join(process.cwd(), '..', 'dossiers'))
const AVEC_BROUILLONS = process.env.VIGIE_DOSSIERS_BROUILLONS === '1'

export function entete(texte) {
  const m = /^---\n([\s\S]*?)\n---\n?/.exec(texte)
  if (!m) return { meta: {}, corps: texte }
  const meta = {}
  for (const ligne of m[1].split('\n')) {
    const k = /^([a-z_]+)\s*:\s*(.*?)\s*(#.*)?$/.exec(ligne)
    if (k) meta[k[1]] = k[2].replace(/^["']|["']$/g, '')
  }
  return { meta, corps: texte.slice(m[0].length) }
}

const ENTITES = { '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#39;': "'", '&nbsp;': ' ' }
const TEXTE = (html) => html.replace(/<[^>]+>/g, '')
  .replace(/&[a-z#0-9]+;/gi, (e) => ENTITES[e] ?? ' ').trim()

export function ancre(titre) {
  return TEXTE(titre).toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'partie'
}

const CLASSES = { 'l-essentiel': 'essentiel', 'les-mots-du-dossier': 'mots' }

/** Découpe le HTML en parties (une par `<h2>`), ancrées, et rend le sommaire. */
export function mettreEnForme(html) {
  const vues = new Set()
  const unique = (id) => { let u = id, n = 2; while (vues.has(u)) u = `${id}-${n++}`; vues.add(u); return u }
  // Un tableau large défile dans un cadre focalisable et nommé : le tableau
  // lui-même garde son rôle (un `display: block` sur <table> le fait perdre
  // aux lecteurs d'écran).
  html = html.replace(/<table>/g, '<div class="tableau" role="region" tabindex="0" aria-label="Tableau, défilable"><table>')
             .replace(/<\/table>/g, '</table></div>')
  html = html.replace(/<h3>([\s\S]*?)<\/h3>/g, (_, t) => `<h3 id="${unique(ancre(t))}">${t}</h3>`)
  const morceaux = html.split(/(?=<h2>)/)
  const sommaire = []
  const corps = morceaux.map((m) => {
    const h = /^<h2>([\s\S]*?)<\/h2>/.exec(m)
    if (!h) return m
    const id = unique(ancre(h[1]))
    const classe = CLASSES[ancre(h[1])] || 'partie'
    sommaire.push({ id, titre: TEXTE(h[1]) })
    return `<section class="${classe}" aria-labelledby="${id}"><h2 id="${id}">${h[1]}</h2>${m.slice(h[0].length)}</section>`
  }).join('')
  // Deux durées : le texte courant seul, et avec le détail replié.
  const minutes = (h) => Math.max(1, Math.round(TEXTE(h).split(/\s+/).length / 200))
  return { html: corps, sommaire, minutes: minutes(html.replace(/<details[\s\S]*?<\/details>/g, '')),
           minutesTout: minutes(html),
           replis: (html.match(/<details/g) || []).length }
}

/** Les textes à mettre en page : ceux du snapshot, ou tout le répertoire en aperçu local. */
function sources() {
  if (!AVEC_BROUILLONS) return (lireJSON('dossiers.json', { dossiers: [] }).dossiers || [])
  let fichiers = []
  try { fichiers = readdirSync(REPERTOIRE).filter((f) => /^[a-z0-9-]+\.md$/.test(f)) }
  catch { return [] }  // pas de répertoire : l'instance n'a pas de dossier
  return fichiers.map((f) => ({ slug: f.slice(0, -3), texte: readFileSync(join(REPERTOIRE, f), 'utf8') }))
}

export function lireDossiers() {
  const dossiers = []
  for (const { slug, texte } of sources()) {
    const { meta, corps } = entete(texte)
    const statut = meta.statut === 'a_developper' ? 'a_developper'
      : AVEC_BROUILLONS ? 'brouillon' : 'publie'
    dossiers.push({
      slug,
      titre: meta.titre || slug,
      chapeau: meta.chapeau || '',
      maj: meta.maj || '',
      statut,
      // Le corps d'un dossier « à développer » ne sort pas, même s'il existe.
      ...(statut === 'a_developper'
        ? { html: '', sommaire: [], minutes: 0, minutesTout: 0, replis: 0 }
        : mettreEnForme(markdownSur(corps.replace(/^# .*\n/, '')))),
    })
  }
  // Alphabétique, article initial ignoré (« L'eau » se range à E). Par date de
  // mise à jour, le dernier dossier retouché prenait la tête de la liste : la
  // place d'un sujet ne doit rien dire de son importance.
  const cle = (d) => d.titre.replace(/^(?:(?:les|le|la)\s+|l['’])/i, '')
  return dossiers.sort((a, b) => cle(a).localeCompare(cle(b), 'fr', { sensitivity: 'base' }))
}
