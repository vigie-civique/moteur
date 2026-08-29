// La carte reste rendue côté client (Leaflet a besoin du DOM), mais son
// dénominateur, lui, se lit au build.
//
// « 1 807 acteurs » sur l'accueil et « 795 » sur la carte : le même mot, deux
// nombres, aucune explication au point de lecture. L'écart est parfaitement
// légitime — tous les acteurs n'ont pas de localisation publique fiable — mais
// un lecteur qui ne le sait pas conclut au bug, et un lecteur hostile conclut
// qu'on ne sait pas compter.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { DATA_DIR, lireJSON } from '$lib/donnees.server.js'
import { etatSource } from '$lib/couverture.js'

export const prerender = true

export function load() {
  let s = {}
  try {
    s = JSON.parse(readFileSync(join(DATA_DIR, 'stats.json'), 'utf8'))
  } catch { /* snapshot absent : la carte s'affiche sans son dénominateur */ }

  const q = s.location_quality || {}

  return {
    surCarte: s.map_features_public ?? null,
    total: s.entities_public ?? null,
    // Les trois motifs d'absence, dans l'ordre de fréquence.
    sansLocalisation: q.missing ?? null,
    domicileMasque: q.hidden_ei_domicile ?? null,
    personneMasquee: q.hidden_person ?? null,
    // Sans POI collecté, la carte est vide : le dire plutôt que de laisser
    // croire qu'il n'y a rien à voir sur ce territoire.
    source: etatSource(lireJSON('couverture.json', {}), 'carte'),
  }
}
