// Chiffres des cartes du hub, lus au build dans le snapshot.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

export const prerender = true

const DATA_DIR = join(process.cwd(), 'static', 'data')
const lire = (nom, defaut = {}) => {
  try { return JSON.parse(readFileSync(join(DATA_DIR, nom), 'utf8')) }
  catch { return defaut }
}

export function load() {
  const stats = lire('stats.json')
  const elections = lire('elections.json', {})
  const elus = lire('elus_rne.json', {})
  const events = lire('events.json', {})
  const relations = lire('relations.json', {})
  const conflits = lire('conflits.json', {})

  const listeElus = Array.isArray(elus) ? elus : elus.elus || elus.rows || []
  const listeEvents = Array.isArray(events) ? events : events.events || []
  const listeRel = Array.isArray(relations) ? relations : relations.relations || []
  const listeConflits = Array.isArray(conflits) ? conflits : conflits.cas || []

  const deliberations = listeEvents.filter((e) =>
    ['deliberation', 'conseil_municipal', 'délibérations_cc', 'pv_cc'].includes(e.type)).length

  // Conseil de Lasalle : les élus de la commune, hors délégués intercommunaux.
  const elusLasalle = listeElus.filter((e) => (e.commune || '').toLowerCase().includes('lasalle')).length

  return {
    elus: listeElus.length || null,
    elusLasalle: elusLasalle || null,
    deliberations: deliberations || stats.events_public || null,
    relations: listeRel.length || stats.relations_public || null,
    conflits: listeConflits.length || null,
    // Compté sur le snapshot, jamais écrit en dur : la carte a annoncé « 7
    // communes » jusqu'au 12/08/2026, chiffre hérité de l'ancien périmètre du
    // vallon, alors que l'intercommunalité en compte 15.
    communes: new Set((elections.resultats || []).map((r) => r.commune).filter(Boolean)).size || null,
  }
}
