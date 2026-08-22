// Flux financiers (subventions, versements).
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
  const d = lire('flows.json', [])
  const flows = Array.isArray(d) ? d : d.flows || []

  // Constat sur les VERSEMENTS de la commune.
  //
  // Piège à ne pas reproduire : une cession de patrimoine est une VENTE. Le
  // flux est stocké commune → acquéreur (le sens du bien), mais l'argent va
  // dans l'autre sens — la commune encaisse. Compter les cessions parmi les
  // versements ferait apparaître l'acquéreur d'un terrain communal comme
  // premier bénéficiaire de l'argent public alors qu'il a payé la commune.
  // La page applique déjà cette règle ; le constat doit l'appliquer aussi.
  const versements = flows.filter((f) =>
    f.sens === 'sortant' && f.amount && f.statut !== 'demande'
    && !/cession/i.test(f.type || ''))

  const total = versements.reduce((s, f) => s + f.amount, 0)
  const parBenef = new Map()
  for (const f of versements) {
    parBenef.set(f.to_name, (parBenef.get(f.to_name) || 0) + f.amount)
  }
  const classement = [...parBenef.values()].sort((a, b) => b - a)

  // Combien de bénéficiaires réunissent 80 % des montants versés.
  let cumul = 0, pour80 = 0
  for (const v of classement) {
    cumul += v; pour80++
    if (cumul >= total * 0.8) break
  }

  const annees = [...new Set(versements.map((f) => f.year).filter(Boolean))].sort()

  return {
    flows,
    constat: versements.length ? {
      nb: versements.length,
      total,
      beneficiaires: parBenef.size,
      pour80,
      periode: annees.length ? [annees[0], annees[annees.length - 1]] : null,
    } : null,
  }
}
