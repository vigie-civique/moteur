// Les actes d'un millésime — une page HTML statique par année.
// `entries()` + `load()` ne tournent qu'au build : on lit le disque avec
// `node:fs` sans rien embarquer dans le bundle client (même motif que
// entite/[id]/+page.server.js).
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { error } from '@sveltejs/kit'
import { INSTITUTIONAL, anneeDe } from '$lib/actes.js'
import { DATA_DIR } from '$lib/donnees.server.js'

export const prerender = true

const lireActes = () => {
  try {
    const d = JSON.parse(readFileSync(join(DATA_DIR, 'events.json'), 'utf8'))
    return (d.events || []).filter((e) => INSTITUTIONAL[e.type])
  } catch { return [] }
}

/** Une page par millésime présent dans le snapshot, « sans-date » compris. */
export function entries() {
  return [...new Set(lireActes().map(anneeDe))].map((annee) => ({ annee }))
}

export function load({ params }) {
  const actes = lireActes()
  const items = actes
    .filter((e) => anneeDe(e) === params.annee)
    .sort((a, b) => (b.date || '').localeCompare(a.date || ''))

  if (!items.length) throw error(404, 'Aucun acte pour cette année.')

  // Années voisines, pour naviguer de millésime en millésime sans repasser
  // par le sommaire.
  const annees = [...new Set(actes.map(anneeDe))]
    .sort((a, b) => (a === 'sans-date' ? 1 : b === 'sans-date' ? -1 : b.localeCompare(a)))
  const i = annees.indexOf(params.annee)

  return {
    annee: params.annee,
    items,
    nCM: items.filter((e) => INSTITUTIONAL[e.type].instance === 'CM').length,
    nCC: items.filter((e) => INSTITUTIONAL[e.type].instance === 'CC').length,
    precedente: annees[i + 1] ?? null,   // plus ancienne
    suivante: annees[i - 1] ?? null,     // plus récente
    annees,
  }
}
