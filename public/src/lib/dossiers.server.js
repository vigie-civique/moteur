// Les dossiers : le seul endroit du site où un humain écrit.
//
// Tout le reste est de la donnée transformée mécaniquement. Un dossier relie des
// faits épars autour d'une question d'intérêt public ; il vit dans l'INSTANCE,
// un fichier markdown par dossier (`dossiers/<slug>.md`), hors du dépôt du
// moteur parce qu'il nomme des personnes (cf. .gitignore). Son en-tête dit s'il
// se publie :
//
//   ---
//   titre: L'eau à Lasalle
//   chapeau: Deux services d'eau dans une même commune…
//   statut: publie          # brouillon | a_developper | publie
//   maj: 2026-09-30
//   ---
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
// `brouillon` ne sort jamais — sauf dans l'aperçu local, avec
// VIGIE_DOSSIERS_BROUILLONS=1, qui marque chaque page d'un bandeau. Un dossier
// `a_developper` annonce son sujet et rien d'autre : ni faits, ni personne
// nommée, donc rien à quoi répondre (le statut vient de la v1).
import { readdirSync, readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { marked } from 'marked'

const REPERTOIRE = resolve(process.env.VIGIE_DOSSIERS_DIR || join(process.cwd(), '..', 'dossiers'))
const STATUTS = new Set(['brouillon', 'a_developper', 'publie'])
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

function publiable(statut) {
  return statut === 'publie' || statut === 'a_developper' || (AVEC_BROUILLONS && statut === 'brouillon')
}

export function lireDossiers() {
  let fichiers = []
  try { fichiers = readdirSync(REPERTOIRE).filter((f) => /^[a-z0-9-]+\.md$/.test(f)) }
  catch { return [] }  // pas de répertoire : l'instance n'a pas de dossier
  const dossiers = []
  for (const f of fichiers) {
    const { meta, corps } = entete(readFileSync(join(REPERTOIRE, f), 'utf8'))
    // Un statut absent ou mal écrit vaut brouillon : on ne publie pas par défaut.
    const statut = STATUTS.has(meta.statut) ? meta.statut : 'brouillon'
    if (!publiable(statut)) continue
    dossiers.push({
      slug: f.slice(0, -3),
      titre: meta.titre || f.slice(0, -3),
      chapeau: meta.chapeau || '',
      maj: meta.maj || '',
      statut,
      // Le corps d'un dossier « à développer » ne sort pas, même s'il existe.
      ...(statut === 'a_developper'
        ? { html: '', sommaire: [], minutes: 0, minutesTout: 0, replis: 0 }
        : mettreEnForme(marked.parse(corps.replace(/^# .*\n/, '')))),
    })
  }
  return dossiers.sort((a, b) => (b.maj || '').localeCompare(a.maj || ''))
}
