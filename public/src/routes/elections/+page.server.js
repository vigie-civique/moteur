// Résultats électoraux lus au build (cf. marches/+page.server.js pour le motif).
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

export const prerender = true

const lire = (nom) => {
  try {
    return JSON.parse(readFileSync(join(process.cwd(), 'static', 'data', nom), 'utf8'))
  } catch {
    return {}   // snapshot absent : page vide plutôt que build cassé
  }
}

export function load() {
  const d = lire('elections.json')
  const resultats = d.resultats || []
  const listes = d.listes || []

  // Communes de l'intercommunalité absentes des fichiers nationaux. Il y en a
  // toujours : un conseil élu hors des dates des scrutins généraux (démission
  // collective, commune nouvelle, second tour reporté) ne figure dans aucun des
  // deux fichiers publiés. Cette page nommait la commune concernée en dur — ce
  // qui la rendait fausse dès le scrutin suivant, et fausse partout ailleurs.
  // La lacune est donc CALCULÉE, comme le reste des lacunes du site.
  const membres = lire('intercommunalite.json').membres || []
  const avecResultats = new Set(resultats.map((r) => r.insee))
  const communesAbsentes = membres
    .filter((m) => !avecResultats.has(m.insee))
    .map((m) => m.nom)
    .sort((a, b) => a.localeCompare(b, 'fr'))

  return { resultats, listes, communesAbsentes, communesEpci: membres.length }
}
