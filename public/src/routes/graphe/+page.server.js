// Acteurs et relations du graphe. Le rendu D3 reste côté client :
// c'est de la mise en page interactive, pas de la donnée.
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
  const rel = lire('relations.json', { relations: [] })
  const ent = lire('entities.json', { entities: [] })

  // Seul le type de chaque entité sert au rendu : embarquer les fiches
  // complètes ajouterait ~900 Ko au HTML pour rien.
  const entType = (ent.entities || []).map((e) => [e.id, e.type])

  return { relations: rel.relations || [], entType }
}
