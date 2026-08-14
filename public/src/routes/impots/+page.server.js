import { EPCI } from '$lib/instance.js'
// Taux de fiscalité locale, comparés entre communes de l'EPCI.
// Lu dans le snapshot au build — cf. marches/+page.server.js pour le motif.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

export const prerender = true

const lire = (nom, defaut = {}) => {
  try { return JSON.parse(readFileSync(join(process.cwd(), 'static', 'data', nom), 'utf8')) }
  catch { return defaut }  // snapshot absent : page vide plutôt que build cassé
}

export function load() {
  const d = lire('fiscalite.json', { taux: [] })
  const taux = d.taux || []
  const annee = taux.length ? Math.max(...taux.map((t) => t.annee)) : null
  return { taux, annee }
}
