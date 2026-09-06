// Le statut de l'instance, lu au build pour TOUTES les pages.
//
// Il vit dans `stats.json` — donc dans les données publiées, pas seulement
// dans le gabarit : un export, une API ou un moissonneur doivent pouvoir dire
// à quoi ils ont affaire. Le bandeau n'en tire que la date de dernière
// collecte ; les libellés, eux, viennent de `instance.js`, qui est généré
// depuis la même source (collectors/statut.py).
//
// `prerender` est déclaré dans +layout.js et vaut pour cette charge aussi :
// rien n'est lu à l'exécution chez le lecteur.
import { lireJSON } from '$lib/donnees.server.js'

export function load() {
  const stats = lireJSON('stats.json', {}) || {}
  const statut = stats.statut || {}
  // Le défaut n'est pas « rien » : une page qui ne sait pas ce qu'elle est ne
  // doit pas se taire. Elle affiche l'état le plus modeste, sans date.
  return {
    derniereCollecte: statut.derniere_collecte || '',
  }
}
