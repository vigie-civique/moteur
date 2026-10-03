// Le brouillon d'une fiche : tout ce que l'éditeur a changé et qui n'est pas
// encore envoyé. Rien ne s'enregistre plus « tout seul » — ajouter un contact,
// déplacer le point ou modifier une relation remplit ce brouillon, et un seul
// bouton, toujours visible, dit ce qu'il va enregistrer puis l'envoie.
import { LIBELLES } from '$lib/champs.js'
import { VERDICT } from '$lib/axes.js'

let compteur = 0
// Clé d'un ajout pas encore créé côté serveur (il n'a pas d'id).
export const cleLocale = () => ++compteur

export function brouillonVide() {
  return {
    verdict:   null,
    relations: { ajouts: [], modifs: {}, suppr: [] },
    contacts:  { ajouts: [], suppr: [] },
    sites:     { ajouts: [], statuts: {}, suppr: [] },
    notes:     { ajouts: [], modifs: {}, suppr: [] },
    budget:    { ajouts: [], suppr: [] },
  }
}

// nom singulier, pluriel, féminin
const NOMS = {
  relations: ['relation', 'relations', true],
  contacts:  ['contact', 'contacts', false],
  sites:     ['site', 'sites', false],
  notes:     ['note', 'notes', true],
  budget:    ['ligne de budget', 'lignes de budget', true],
}

function accord(participe, fem, pl) {
  return participe + (fem ? 'e' : '') + (pl ? 's' : '')
}

function phrases(cle, b) {
  const [sing, plur, fem] = NOMS[cle]
  const dire = (n, participe) =>
    n ? [`${n} ${n > 1 ? plur : sing} ${accord(participe, fem, n > 1)}`] : []
  return [
    ...dire(b.ajouts.length, 'ajouté'),
    ...dire(Object.keys(b.modifs ?? {}).length, 'modifié'),
    ...dire(Object.keys(b.statuts ?? {}).length, 'tranché'),
    ...dire(b.suppr.length, 'supprimé'),
  ]
}

function compte(b) {
  return b.ajouts.length + b.suppr.length
       + Object.keys(b.modifs ?? {}).length + Object.keys(b.statuts ?? {}).length
}

// Ce que le bouton va enregistrer, en mots.
export function resumer(champs, coords, b) {
  const parts = []
  if (b.verdict) parts.push(`verdict « ${VERDICT[b.verdict]?.libelle ?? b.verdict} »`)
  if (champs.length > 3) parts.push(`${champs.length} champs de la fiche`)
  else parts.push(...champs.map(c => LIBELLES[c] ?? c))
  if (coords) parts.push('position sur la carte')
  for (const cle of Object.keys(NOMS)) parts.push(...phrases(cle, b[cle]))
  return parts
}

// Changements en attente, par onglet : le badge de chaque onglet.
export function parOnglet(champs, coords, b) {
  return {
    essentiel:  (b.verdict ? 1 : 0) + champs.length + (coords ? 1 : 0) + compte(b.budget),
    liens:      compte(b.relations) + compte(b.contacts) + compte(b.sites),
    historique: compte(b.notes),
  }
}

// « a, b et c »
export function enumerer(parts) {
  if (parts.length < 2) return parts.join('')
  return parts.slice(0, -1).join(', ') + ' et ' + parts[parts.length - 1]
}
