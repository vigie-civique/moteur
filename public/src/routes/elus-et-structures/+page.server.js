// Liens élus / structures, lus au build (cf. marches/+page.server.js pour le motif).
// Page sensible : c'est justement celle qui doit être archivable et citable
// telle qu'elle était à une date donnée, donc surtout pas rendue côté client.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { DATA_DIR } from '$lib/donnees.server.js'

export const prerender = true

export function load() {
  let conflits = null
  try {
    conflits = JSON.parse(readFileSync(join(DATA_DIR, 'conflits.json'), 'utf8'))
  } catch { /* snapshot absent : page vide plutôt que build cassé */ }

  return { conflits }
}
