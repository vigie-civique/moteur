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
import { lireDossiers } from '$lib/dossiers.server.js'

export function load() {
  const stats = lireJSON('stats.json', {}) || {}
  const statut = stats.statut || {}
  // Le défaut n'est pas « rien » : une page qui ne sait pas ce qu'elle est ne
  // doit pas se taire. Elle affiche l'état le plus modeste, sans date.
  return {
    derniereCollecte: statut.derniere_collecte || '',
    // L'en-tête met en avant les séances relues et les dossiers — seulement
    // s'il y en a : une instance qui n'a encore rien publié ne pousse pas le
    // lecteur vers une page vide.
    // Depuis le 04/10/2026, toute séance publiée a sa page : la rubrique est
    // mise en avant dès qu'il y a une séance, relue ou non (`seances.json`,
    // `conseils.json` pour un snapshot plus ancien).
    aConseils: ((lireJSON('seances.json', null) || lireJSON('conseils.json', {}) || {})
      .seances || []).length > 0,
    aDossiers: lireDossiers().length > 0,
  }
}
