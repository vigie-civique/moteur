// Projets approuvés en conseil.
// Lu dans le snapshot au build — cf. marches/+page.server.js pour le motif.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

export const prerender = true

const lire = (nom, defaut = {}) => {
  try { return JSON.parse(readFileSync(join(process.cwd(), 'static', 'data', nom), 'utf8')) }
  catch { return defaut }  // snapshot absent : page vide plutôt que build cassé
}

export function load() {
  const d = lire('approbations.json', { approbations: [] })
  return {
    approbations: (d.approbations || [])
      .sort((a, b) => (b.date || '').localeCompare(a.date || '')),
  }
}
