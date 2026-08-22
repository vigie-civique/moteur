// Eau, risques, ICPE, catastrophes naturelles.
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
  const d = lire('environnement.json', {})
  return {
    stations: d.eau_stations || [], series: d.eau_series || [],
    couverture: d.eau_couverture || [], risques: d.risques || [],
    icpe: d.icpe || [], catnat: d.catnat || [],
  }
}
