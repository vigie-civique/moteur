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
      html: statut === 'a_developper' ? '' : marked.parse(corps.replace(/^# .*\n/, '')),
    })
  }
  return dossiers.sort((a, b) => (b.maj || '').localeCompare(a.maj || ''))
}
