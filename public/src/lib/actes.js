// Types d'actes institutionnels retenus par /deliberations.
// Partagé entre le chargement au build (+page.server.js) et l'affichage
// (+page.svelte) : les deux doivent filtrer exactement la même chose, et une
// liste recopiée à deux endroits finit toujours par diverger.
//
// Les annonces BODACC (vie économique) et les événements culturels
// (→ /vie-locale) sont exclus.
export const INSTITUTIONAL = {
  conseil_municipal:  { label: 'Conseil municipal', instance: 'CM' },
  deliberation:       { label: 'Délibération', instance: 'CM' },
  election:           { label: 'Élection', instance: 'CM' },
  'délibérations_cc': { label: 'Délibération CC', instance: 'CC' },
  pv_cc:              { label: 'PV communautaire', instance: 'CC' },
  actualité_cc:       { label: 'Actualité CC', instance: 'CC' },
}

// Types d'entités listées par /acteurs-publics.
export const TYPES_ACTEURS = ['service', 'association', 'business', 'place']

// Types d'événements de l'agenda (/vie-locale) — par opposition aux actes
// institutionnels ci-dessus.
export const AGENDA_TYPES = new Set(['local_event', 'evenement_culturel', 'exposition'])

// Année d'un acte, ou 'sans-date' pour les 14 actes dont la source ne porte
// pas de date exploitable. Ils ont leur page comme les autres : sur un site de
// transparence, un acte qu'on ne sait pas dater ne doit pas disparaître.
export const anneeDe = (e) => (e.date || '').slice(0, 4) || 'sans-date'

export const libelleAnnee = (a) => (a === 'sans-date' ? 'Sans date' : a)
