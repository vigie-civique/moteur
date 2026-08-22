// Les marchés sont lus dans le snapshot au build, pas en `onMount` côté client.
// Avant cette bascule, le HTML livré ne contenait que « Chargement des
// marchés… » : invisible pour les moteurs de recherche, vide pour Internet
// Archive, page blanche au moindre échec de fetch. Les données étant figées au
// build, le chargement client n'apportait rien.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { DATA_DIR } from '$lib/donnees.server.js'

export const prerender = true

const lire = (nom, defaut = {}) => {
  try { return JSON.parse(readFileSync(join(DATA_DIR, nom), 'utf8')) }
  catch { return defaut }
}

export function load() {
  const d = lire('marches.json', { marches: [] })
  const marches = (d.marches || [])
    .sort((a, b) => (b.date_notif || '').localeCompare(a.date_notif || ''))

  // Constat : ce que les données disent d'elles-mêmes, calculé plutôt que
  // laissé au lecteur. Un observatoire qui aligne 78 lignes sans jamais dire
  // ce qu'on y voit reste un portail ; c'est la différence entre une base
  // consultable et quelque chose qu'on cite en conseil municipal.
  const attribues = marches.filter((m) => m.titulaire_nom && m.montant)
  const total = attribues.reduce((s, m) => s + m.montant, 0)

  const parTitulaire = new Map()
  for (const m of attribues) {
    parTitulaire.set(m.titulaire_nom, (parTitulaire.get(m.titulaire_nom) || 0) + m.montant)
  }
  const classement = [...parTitulaire.values()].sort((a, b) => b - a)

  // Combien de titulaires réunissent la moitié des montants.
  let cumul = 0, pourMoitie = 0
  for (const v of classement) {
    cumul += v; pourMoitie++
    if (cumul >= total / 2) break
  }

  const recurrents = [...new Map(
    attribues.reduce((acc, m) => {
      acc.set(m.titulaire_nom, (acc.get(m.titulaire_nom) || 0) + 1)
      return acc
    }, new Map())
  ).values()].filter((n) => n > 1).length

  return {
    marches,
    constat: attribues.length ? {
      attribues: attribues.length,
      total,
      titulaires: parTitulaire.size,
      pourMoitie,
      partMoitie: Math.round(100 * classement.slice(0, pourMoitie).reduce((s, v) => s + v, 0) / total),
      recurrents,
    } : null,
  }
}
