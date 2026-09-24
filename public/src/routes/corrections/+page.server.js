// Le journal des corrections. Données produites par export_corrections()
// dans build_public_snapshot.py : les erreurs du site reconnues par l'instance
// (config/journal_corrections.json) et les données rectifiées à l'atelier.
import { lireJSON } from '$lib/donnees.server.js'

export const prerender = true

export function load() {
  const j = lireJSON('corrections.json', null)
  const stats = lireJSON('stats.json', {})
  return {
    // `null` : snapshot antérieur au journal. La page le dit plutôt que
    // d'afficher « aucune correction », qui serait une affirmation.
    journal: j,
    arreteLe: stats.generated_at || null,
  }
}
