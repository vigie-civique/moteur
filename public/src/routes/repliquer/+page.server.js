// Page « répliquer » — les chiffres viennent du snapshot, jamais de la main.
//
// Elle offrait auparavant une archive du dépôt en téléchargement, avec son
// empreinte SHA-256 : c'était le seul canal de distribution, faute de pouvoir
// créer un compte sur une forge. Le code étant désormais publié, l'archive n'a
// plus d'objet — et versionnée dans le dépôt qu'elle contenait, elle dérivait
// de HEAD à chaque commit sans que personne ne la refasse.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { DATA_DIR } from '$lib/donnees.server.js'

export const prerender = true

export function load() {
  let stats = {}
  try {
    stats = JSON.parse(readFileSync(
      join(DATA_DIR, 'stats.json'), 'utf8'))
  } catch { /* pas de snapshot : la page s'affiche sans ses chiffres */ }

  return { replicabilite: stats.replicabilite || null }
}
