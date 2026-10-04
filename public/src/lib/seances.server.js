// Les séances, lues une fois par build : l'index (`seances.json`) et les
// délibérations de chacune, relues dans `events.json` — l'index ne les recopie
// pas (cf. scripts/snapshot/seances.py).
import { lireJSON } from '$lib/donnees.server.js'
import { ancreActe, anneeDe } from '$lib/actes.js'

let cache = null

/** `null` : snapshot antérieur aux pages de séance (avant le 04/10/2026). */
export function lireSeances() {
  if (cache) return cache
  const index = lireJSON('seances.json', null)
  if (!index) return (cache = { seances: null, actes: new Map() })
  // Les délibérations d'une séance : même date, même portée — la clé du
  // snapshot, parce que les deux conseils peuvent siéger le même jour.
  const actes = new Map()
  for (const e of (lireJSON('events.json', { events: [] }).events || [])) {
    if (e.type !== 'deliberation' && e.type !== 'deliberation_cc') continue
    const cle = `${e.date}|${e.portee}`
    if (!actes.has(cle)) actes.set(cle, [])
    actes.get(cle).push({ id: e.id, titre: e.title, vote: e.vote || null,
                          lien: `/deliberations/${anneeDe(e)}#${ancreActe(e)}` })
  }
  // Dans l'ordre de leur clé (« c-2021-41 » avant « c-2021-42 »), qui suit le
  // numéro d'acte quand il a été lu.
  const ordre = (a, b) => a.lien.localeCompare(b.lien, 'fr', { numeric: true })
  for (const l of actes.values()) l.sort(ordre)
  return (cache = { seances: index.seances || [], actes })
}

export const actesDe = (s) => lireSeances().actes.get(`${s.date}|${s.portee}`) || []
