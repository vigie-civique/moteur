// Ce que la collecte couvre, et ce qu'elle ne couvre pas.
// Données produites par export_couverture() dans build_public_snapshot.py.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { DATA_DIR } from '$lib/donnees.server.js'
import { AGENDA_TYPES, INSTITUTIONAL, estSeance, instanceDe } from '$lib/actes.js'

export const prerender = true

export function load() {
  let c = {}
  try {
    c = JSON.parse(readFileSync(join(DATA_DIR, 'couverture.json'), 'utf8'))
  } catch { /* snapshot absent : page vide plutôt que build cassé */ }
  return { couverture: c, totaux: totaux() }
}

// La correspondance entre les grands totaux du site. L'accueil, /deliberations
// et cette page annonçaient 1 179, 2 660 et 4 056 sans dire ce qu'ils
// comptent — tous justes, aucun relié aux autres (audit du 24/09/2026).
// Chaque pièce publiée tombe dans UNE ligne, et les lignes font le total.
function totaux() {
  let events = []
  try {
    events = JSON.parse(readFileSync(join(DATA_DIR, 'events.json'), 'utf8')).events || []
  } catch { return null }
  const lignes = [
    ['Délibérations municipales', '/deliberations', (e) => INSTITUTIONAL[e.type] && !estSeance(e) && instanceDe(e) === 'CM'],
    ['Séances du conseil municipal', '/deliberations', (e) => INSTITUTIONAL[e.type] && estSeance(e) && instanceDe(e) === 'CM'],
    ['Délibérations intercommunales', '/deliberations', (e) => INSTITUTIONAL[e.type] && !estSeance(e) && instanceDe(e) === 'CC'],
    ['Séances du conseil communautaire', '/deliberations', (e) => INSTITUTIONAL[e.type] && estSeance(e) && instanceDe(e) === 'CC'],
    ["Autorisations d'urbanisme", '/urbanisme', (e) => e.type === 'autorisation_urbanisme'],
    ['Annonces légales (BODACC)', '/acteurs-publics', (e) => (e.type || '').startsWith('bodacc')],
    ['Avis et attributions de marchés', '/marches', (e) => e.type === 'marché_public'],
    ['Agenda local', '/vie-locale', (e) => AGENDA_TYPES.has(e.type)],
    ['Élections', '/elections', (e) => e.type === 'election'],
  ]
  const n = lignes.map(() => 0)
  let autres = 0
  for (const e of events) {
    const i = lignes.findIndex(([, , test]) => test(e))
    if (i < 0) autres++
    else n[i]++
  }
  const rangs = lignes.map(([libelle, href], i) => ({ libelle, href, n: n[i] })).filter((l) => l.n)
  if (autres) rangs.push({ libelle: 'Autres pièces', href: null, n: autres })
  return { total: events.length, lignes: rangs }
}
