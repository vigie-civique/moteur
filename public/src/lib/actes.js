// Types d'actes institutionnels retenus par /deliberations.
// Partagé entre le chargement au build (+page.server.js) et l'affichage
// (+page.svelte) : les deux doivent filtrer exactement la même chose, et une
// liste recopiée à deux endroits finit toujours par diverger.
//
// ⚠️ Cette table a déjà vieilli une fois, en silence : elle attendait
// `délibérations_cc` et `pv_cc` alors que les collecteurs écrivent
// `deliberation_cc` et `conseil_communautaire`. Les 833 délibérations
// communautaires de Lasalle n'étaient donc comptées nulle part, et le filtre
// « Intercommunal » de la page ne rendait jamais rien — la page annonçait
// « 1 407 actes · 1 407 conseil municipal · 0 intercommunalité » quand le site
// en publiait 2 128. Le même défaut avait déjà été corrigé dans
// qui-decide/+page.server.js sans être porté ici. `scripts/verify_snapshot.py`
// refuse désormais un type institutionnel absent de cette table.
//
// Les annonces BODACC (vie économique) et les événements culturels
// (→ /vie-locale) sont exclus. Les ÉLECTIONS aussi : un scrutin n'est pas un
// acte pris par une assemblée, et les compter ici faisait dire à un dossier
// national — qui ne collecte aucune délibération — qu'il recensait « 87 actes
// du conseil municipal » alors qu'il n'avait que 87 résultats électoraux.
// Elles ont leur page : /elections.
export const INSTITUTIONAL = {
  deliberation:          { label: 'Délibération' },
  conseil_municipal:     { label: 'Conseil municipal' },
  deliberation_cc:       { label: 'Délibération intercommunale' },
  conseil_communautaire: { label: 'Conseil communautaire' },
}

// L'assemblée qui a pris l'acte se lit sur sa PORTÉE, calculée à la collecte
// (collectors/portee.py) et publiée dans le snapshot — pas sur une
// correspondance type → instance écrite à la main. Un même type peut relever
// des deux : c'est la donnée qui tranche, jamais la table.
export const instanceDe = (e) =>
  (e.portee === 'intercommunalite' || e.portee === 'territoire') ? 'CC' : 'CM'

export const LIBELLE_INSTANCE = { CM: 'Conseil municipal', CC: 'Intercommunalité' }

// Types d'entités listées par /acteurs-publics.
export const TYPES_ACTEURS = ['service', 'association', 'business', 'place']

// Types d'événements de l'agenda (/vie-locale) — par opposition aux actes
// institutionnels ci-dessus.
export const AGENDA_TYPES = new Set(['local_event', 'evenement_culturel', 'exposition'])

// Année d'un acte, ou 'sans-date' pour les actes dont la source ne porte pas de
// date exploitable. Ils ont leur page comme les autres : sur un site de
// transparence, un acte qu'on ne sait pas dater ne doit pas disparaître.
export const anneeDe = (e) => (e.date || '').slice(0, 4) || 'sans-date'

export const libelleAnnee = (a) => (a === 'sans-date' ? 'Sans date' : a)
