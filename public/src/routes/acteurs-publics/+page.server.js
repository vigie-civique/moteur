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
  // C1 = la commune, C2 = une autre commune membre ou l'EPCI lui-même,
  // C3/lien = au-delà. Traduit ici une fois pour toutes : les pages n'ont pas
  // à connaître le vocabulaire du classement interne.
  const portee = (p) =>
    p === 'C1' ? 'commune' : p === 'C2' ? 'intercommunalite' : 'territoire'

  return {
    all: (d.entities || [])
      .filter((e) => TYPES_ACTEURS.includes(e.type))
      .map(({ id, type, name, citations, perimetre, actif, fin_activite, nature }) =>
        ({ id, type, name, citations, portee: portee(perimetre),
           // `actif` reste à `undefined` quand les registres se taisent : c'est
           // une ignorance, jamais une présomption d'activité.
           actif, fin: fin_activite || null, nature: nature || null })),
  }
}
