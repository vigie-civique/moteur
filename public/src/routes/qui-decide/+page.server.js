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
  const events = lire('events.json', {})
  const relations = lire('relations.json', {})
  const conflits = lire('conflits.json', {})

  const listeElus = Array.isArray(elus) ? elus : elus.elus || elus.rows || []
  const listeEvents = Array.isArray(events) ? events : events.events || []
  const listeRel = Array.isArray(relations) ? relations : relations.relations || []
  const listeConflits = Array.isArray(conflits) ? conflits : conflits.cas || []

  // La carte annonce « la chronologie des votes du conseil municipal » : elle
  // doit compter le conseil municipal. Elle comptait les deux conseils — 1 997
  // à Lasalle, dont 833 votées par la communauté de communes.
  const ACTES = ['deliberation', 'conseil_municipal', 'délibérations_cc', 'pv_cc']
  const listeActes = listeEvents.filter((e) => ACTES.includes(e.type))
  const communal = (e) => !e.portee || e.portee === 'commune'
  const deliberations = listeActes.filter(communal).length
  const deliberationsInterco = listeActes.length - deliberations

  // Le conseil municipal seul : les élus de la commune, hors délégués
  // intercommunaux. Le rattachement se lit sur `commune`, comparé au nom
  // déclaré par l'instance — pas à un nom écrit ici.
  const elusCommune = listeElus.filter(
    (e) => (e.commune || '').toLowerCase() === COMMUNE.toLowerCase()).length

  return {
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
