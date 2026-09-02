import { COMMUNE, COMMUNE_DE } from '$lib/instance.js'
// Chiffres des cartes du hub, lus au build dans le snapshot.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { DATA_DIR } from '$lib/donnees.server.js'

export const prerender = true

const lire = (nom, defaut = {}) => {
  try { return JSON.parse(readFileSync(join(DATA_DIR, nom), 'utf8')) }
  catch { return defaut }
}

export function load() {
  const stats = lire('stats.json')
  const elections = lire('elections.json', {})
  const elus = lire('elus_rne.json', {})
  const relations = lire('relations.json', {})
  const conflits = lire('conflits.json', {})

  const listeElus = Array.isArray(elus) ? elus : elus.elus || elus.rows || []
  const listeRel = Array.isArray(relations) ? relations : relations.relations || []
  const listeConflits = Array.isArray(conflits) ? conflits : conflits.cas || []

  // Le compte des délibérations vient de `stats.json`, qui le calcule déjà par
  // portée. Il était refait ici sur une liste de types PÉRIMÉE
  // (`délibérations_cc`, `pv_cc` — les types réels sont `deliberation_cc` et
  // `conseil_communautaire`) : les 833 délibérations communautaires de Lasalle
  // n'étaient donc comptées nulle part, et la carte de l'intercommunalité
  // n'affichait aucun chiffre. Un décompte recopié à trois endroits finit
  // toujours par diverger d'un des trois.
  const parPortee = stats.deliberations_public_par_portee || {}
  const deliberations = parPortee.commune ?? null
  const deliberationsInterco = parPortee.intercommunalite ?? null

  // Le conseil municipal seul : les élus de la commune, hors délégués
  // intercommunaux. Le rattachement se lit sur `commune`, comparé au nom
  // déclaré par l'instance — pas à un nom écrit ici.
  const elusCommune = listeElus.filter(
    (e) => (e.commune || '').toLowerCase() === COMMUNE.toLowerCase()).length

  const transparence = lire('transparence.json', {})

  return {
    hatvp: transparence.hatvp || [],
    justice: transparence.justice || [],
    elus: listeElus.length || null,
    elusCommune: elusCommune || null,
    deliberations,
    deliberationsInterco,
    relations: listeRel.length || stats.relations_public || null,
    conflits: listeConflits.length || null,
    // Compté sur le snapshot, jamais écrit en dur : la carte a annoncé « 7
    // communes » jusqu'au 12/08/2026, chiffre hérité de l'ancien périmètre du
    // ancien périmètre, plus étroit que celui de l'intercommunalité.
    communes: new Set((elections.resultats || []).map((r) => r.commune).filter(Boolean)).size || null,
  }
}
