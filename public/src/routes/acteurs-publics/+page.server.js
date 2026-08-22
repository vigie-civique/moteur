// Services publics et administrations présents sur le territoire.
// Lu dans le snapshot au build — cf. marches/+page.server.js pour le motif.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { TYPES_ACTEURS } from '$lib/actes.js'
import { DATA_DIR } from '$lib/donnees.server.js'

export const prerender = true

const lire = (nom, defaut = {}) => {
  try { return JSON.parse(readFileSync(join(DATA_DIR, nom), 'utf8')) }
  catch { return defaut }  // snapshot absent : page vide plutôt que build cassé
}

export function load() {
  const d = lire('entities.json', { entities: [] })
  // La page n'affiche que ces quatre champs : embarquer les fiches complètes
  // (16 champs, dont urls et object) triplait le poids de la page.
  return {
    all: (d.entities || [])
      .filter((e) => TYPES_ACTEURS.includes(e.type))
      .map(({ id, type, name, citations }) => ({ id, type, name, citations })),
  }
}
