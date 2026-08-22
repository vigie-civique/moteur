import { COMMUNE } from '$lib/instance.js'
// Composition des conseils municipaux, assemblée au build.
// Cf. marches/+page.server.js pour le motif de la lecture au build.
//
// Tout le croisement RNE × relations vit ici : c'est du calcul sur données
// figées, il n'a rien à faire dans le navigateur du lecteur.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { rangFonction } from '$lib/elus.js'
import { DATA_DIR } from '$lib/donnees.server.js'

export const prerender = true

const lire = (nom, defaut = {}) => {
  try { return JSON.parse(readFileSync(join(DATA_DIR, nom), 'utf8')) }
  catch { return defaut }  // snapshot absent : page vide plutôt que build cassé
}

export function load() {
  const rne = lire('elus_rne.json', { elus: [] })
  const rels = lire('relations.json', { relations: [] })

  const today = new Date().toISOString().slice(0, 10)
  const idsElus = new Set((rne.elus || []).map((e) => e.entity_id))

  // Un mandat communautaire est un rôle SECONDAIRE du conseiller municipal :
  // il s'affiche sur sa fiche, il ne crée pas une deuxième personne.
  const epci = new Map()
  for (const e of rne.elus || []) {
    if (e.mandat === 'epci') epci.set(e.entity_id, e)
  }

  // Commissions encore en cours seulement : les nominations qui se terminent
  // toutes au 15/03/2026 sont celles de la mandature précédente. Le côté
  // « élu » de la relation est identifié par le RNE, pas par « la première
  // extrémité publique » — une commission est elle aussi une entité publique.
  const commissions = new Map()
  for (const r of rels.relations || []) {
    if (r.relation_type !== 'membre_commission') continue
    if (r.until && r.until <= today) continue
    const pid = idsElus.has(r.from_id) ? r.from_id
              : idsElus.has(r.to_id) ? r.to_id : null
    const brut = pid === r.from_id ? r.to_name : r.from_name
    if (pid == null || !brut) continue
    // « Commission Finances et budgets — la commune » → « Finances et budgets » :
    // le préfixe et la commune sont déjà donnés par le contexte de la page.
    // Le suffixe « — <commune> » est construit à l'exécution : une expression
    // régulière littérale ne s'interpole pas.
    const suffixeCommune = new RegExp(`\\s+—\\s+${COMMUNE}$`)
    const label = brut.replace(/^Commission\s+/i, '').replace(suffixeCommune, '')
    commissions.set(pid, [...(commissions.get(pid) || []),
                          { label, role: r.role, precision: r.precision }])
  }

  const elus = (rne.elus || [])
    .filter((e) => e.mandat === 'cm')
    .map((e) => ({ ...e, epci: epci.get(e.entity_id) || null }))
    .sort((a, b) => rangFonction(a.fonction) - rangFonction(b.fonction)
                 || (a.nom || '').localeCompare(b.nom || ''))

  // Sérialisé en paires : la Map est reconstruite dans la page.
  return { elus, commissionsEntries: [...commissions] }
}
