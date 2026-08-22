// Agenda culturel et vie associative.
// Lu dans le snapshot au build — cf. marches/+page.server.js pour le motif.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { AGENDA_TYPES } from '$lib/actes.js'
import { DATA_DIR } from '$lib/donnees.server.js'

export const prerender = true

const lire = (nom, defaut = {}) => {
  try { return JSON.parse(readFileSync(join(DATA_DIR, nom), 'utf8')) }
  catch { return defaut }  // snapshot absent : page vide plutôt que build cassé
}

export function load() {
  const d = lire('events.json', { events: [] })
  return {
    all: (d.events || []).filter((e) => AGENDA_TYPES.has(e.type))
      .sort((a, b) => (b.date || '').localeCompare(a.date || '')),
  }
}
