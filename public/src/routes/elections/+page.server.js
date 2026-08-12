// Résultats électoraux lus au build (cf. marches/+page.server.js pour le motif).
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

export const prerender = true

export function load() {
  let d = {}
  try {
    d = JSON.parse(readFileSync(join(process.cwd(), 'static', 'data', 'elections.json'), 'utf8'))
  } catch { /* snapshot absent : page vide plutôt que build cassé */ }

  return { resultats: d.resultats || [], listes: d.listes || [] }
}
