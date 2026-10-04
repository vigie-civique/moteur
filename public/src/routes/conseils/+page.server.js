// Les conseils en clair : toutes les séances publiées, relues ou non.
//
// La page ne listait que les séances relues — aucune à Saillans ni à Brassac,
// qui ont pourtant 105 et 314 séances publiées. Depuis le 04/10/2026 chaque
// séance a sa page (docs/refonte-du-contenu.md, décision 5), et la liste dit
// pour chacune si elle est mise en clair : sous ce titre, la plupart ne le sont
// pas encore, et la ligne doit le dire plutôt que le laisser croire.
import { lireJSON } from '$lib/donnees.server.js'
import { lireSeances } from '$lib/seances.server.js'
import { etatSource } from '$lib/couverture.js'

export const prerender = true

export function load() {
  const { seances } = lireSeances()
  const stats = lireJSON('stats.json', {})
  return {
    // `null` : snapshot antérieur aux pages de séance. La page le dit plutôt
    // que d'écrire « aucune séance », qui serait une affirmation.
    // Les seuls champs que la liste affiche : 216 séances à Lasalle, et la
    // page porte ses données deux fois (HTML et hydratation).
    seances: seances && seances.map(({ id, date, code, assemblee, nb_actes, en_clair }) =>
      ({ id, date, code, assemblee, nb_actes,
         ...(en_clair ? { en_clair: { titre: en_clair.titre, relu_le: en_clair.relu_le } } : {}) })),
    // Une instance sans procès-verbal collecté : une question non posée,
    // pas une absence de séances.
    source: etatSource(lireJSON('couverture.json', {}), 'deliberations'),
    arreteLe: stats.generated_at || null,
  }
}
