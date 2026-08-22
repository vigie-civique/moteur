// Ce que la collecte couvre, et ce qu'elle ne couvre pas.
// Données produites par export_couverture() dans build_public_snapshot.py.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { DATA_DIR } from '$lib/donnees.server.js'

export const prerender = true

export function load() {
  let c = {}
  try {
    c = JSON.parse(readFileSync(join(DATA_DIR, 'couverture.json'), 'utf8'))
  } catch { /* snapshot absent : page vide plutôt que build cassé */ }
  return { couverture: c }
}
