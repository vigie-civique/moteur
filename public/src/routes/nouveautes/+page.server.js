// Fil des nouveautés.
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
  const d = lire('actualite.json', {})
  return {
    items: d.items || [],
    genere: d.genere_le ?? null,
    arreteLe: d.arrete_le || (d.genere_le || '').slice(0, 10) || null,
  }
}
