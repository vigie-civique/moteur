// Les feuilles « en clair » des séances. Données produites par export_en_clair()
// dans build_public_snapshot.py : seules les séances qu'un validateur a RETENUES
// à l'atelier, et dont le relevé passe le vérificateur au moment de publier.
import { lireJSON } from '$lib/donnees.server.js'

export const prerender = true

export function load() {
  const c = lireJSON('conseils.json', null)
  const stats = lireJSON('stats.json', {})
  return {
    // `null` : snapshot antérieur aux feuilles. La page le dit plutôt que
    // d'écrire « aucune séance », qui serait une affirmation.
    seances: c ? c.seances : null,
    arreteLe: stats.generated_at || null,
  }
}
