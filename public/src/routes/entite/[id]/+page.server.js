// Fiche acteur — PRÉRENDUE, une page HTML statique par acteur public.
//
// Avant le 26/07/2026 cette route était `prerender = false, ssr = false`. Avec
// `adapter-static` et `fallback: '404.html'`, Cloudflare Pages répondait donc un
// **404 HTTP** sur chaque fiche, le contenu n'apparaissant qu'après exécution du
// JS : les 2 789 fiches étaient invisibles des moteurs de recherche et un lien
// partagé n'affichait rien à l'ouverture. Or ces fiches sont le cœur du site.
//
// `+page.server.js` (et pas `+page.js`) parce que `entries()` et `load()` ne
// tournent qu'au build : on peut lire le disque avec `node:fs` sans embarquer
// quoi que ce soit dans le bundle client.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { error } from '@sveltejs/kit'
import { DATA_DIR } from '$lib/donnees.server.js'

export const prerender = true

/** Liste des pages à prérendre : les acteurs présents dans l'index public.
 *
 * Snapshot absent → aucune fiche à prérendre, pas un build cassé. C'était la
 * seule route à ne pas tolérer cette absence : le reste du site se construit
 * vide et le dit, celle-ci s'arrêtait sur un ENOENT. Un dépôt fraîchement
 * cloné n'a pas de données — c'est même son état normal.
 */
export function entries() {
  try {
    const index = JSON.parse(readFileSync(join(DATA_DIR, 'entity_index.json'), 'utf8'))
    return (index.entities || []).map((e) => ({ id: String(e.id) }))
  } catch {
    return []
  }
}

/**
 * Un seul fichier par fiche (`data/entite/<id>.json`), déjà filtré et résolu
 * par build_public_snapshot.py. La page téléchargeait auparavant six JSON
 * complets — près de 3 Mo — pour n'en afficher qu'une fraction.
 */
export function load({ params }) {
  try {
    const bundle = readFileSync(join(DATA_DIR, 'entite', `${params.id}.json`), 'utf8')
    return JSON.parse(bundle)
  } catch {
    throw error(404, 'Acteur introuvable ou non publié.')
  }
}
