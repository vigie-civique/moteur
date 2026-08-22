// Intercommunalité : compétences, délégués, actes.
// Lu dans le snapshot au build — cf. marches/+page.server.js pour le motif.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { DATA_DIR } from '$lib/donnees.server.js'

export const prerender = true

const lire = (nom, defaut = {}) => {
  try { return JSON.parse(readFileSync(join(DATA_DIR, nom), 'utf8')) }
  catch { return defaut }  // snapshot absent : page vide plutôt que build cassé
}

export function load() {
  // Ne sont listés que les actes de décision rattachables à la CC : une version
  // antérieure affichait « Protégez votre compteur » au milieu des PV.
  const TYPES_ACTES = new Set([
    'délibérations_cc', 'pv_cc', 'deliberation', 'arrete_prefectoral_epci',
  ])
  const CC_RE = /caussesaigoual|cc[\s_.-]?cac|intercommunal|communaut/i

  const events = (lire('events.json', { events: [] }).events || [])
    .filter((x) => TYPES_ACTES.has(x.type)
                && (CC_RE.test(x.source || '') || CC_RE.test(x.title || '')))
    .sort((a, b) => (b.date || '').localeCompare(a.date || ''))
    .slice(0, 40)

  return { events, cc: lire('intercommunalite.json', {}) }
}
