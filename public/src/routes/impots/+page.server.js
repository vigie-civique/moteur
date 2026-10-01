import { EPCI, INSEE } from '$lib/instance.js'
// Taux de fiscalité locale, comparés entre communes de l'EPCI.
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
  const d = lire('fiscalite.json', { taux: [] })
  const taux = d.taux || []
  const annee = taux.length ? Math.max(...taux.map((t) => t.annee)) : null
  // Où se place le taux de la commune parmi celles qui lèvent la même taxe —
  // calculé à la collecte (`fiscalite_reperes`), pour le dernier exercice connu.
  const reperes = (d.reperes || []).filter((r) => r.insee === INSEE)
  const situer = (indicateur) => {
    const lignes = reperes.filter((r) => r.indicateur === indicateur)
    const an = lignes.length ? Math.max(...lignes.map((r) => r.annee)) : null
    const de = (portee) => lignes.find((r) => r.annee === an && r.portee === portee) || null
    return de('france') ? { annee: an, france: de('france'), departement: de('departement') } : null
  }
  return { taux, annee, teom: situer('TEOM') }
}
