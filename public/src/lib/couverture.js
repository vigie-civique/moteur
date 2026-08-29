// Ce qui n'a pas été collecté ne doit pas s'afficher comme un zéro.
//
// « 0 événement » et « nous n'avons pas interrogé l'agenda » sont deux
// affirmations différentes, et la seconde n'est pas dans les données : elle est
// dans `couverture.json`, qui liste les collecteurs ayant réellement tourné.
// Un dossier national, par exemple, exclut par conception les collecteurs de
// sites locaux — sa page « Vie locale » affichait pourtant « 0 — aucun
// événement » sous un texte annonçant qu'elle avait interrogé le site de la
// commune. Le lecteur en concluait qu'il ne se passe rien chez lui.
//
// Trois états, à ne jamais confondre :
//   absente   — le collecteur n'a jamais tourné sur cette base : le zéro
//               n'est pas un résultat, c'est une question non posée ;
//   vide      — il a tourné et n'a rien rapporté : le zéro est un résultat ;
//   servie    — il a rapporté quelque chose.

/** Domaine du site → collecteurs qui l'alimentent (cf. collectors/run_all.py). */
export const SOURCES = {
  deliberations: ['cm', 'cm_archive', 'cc_epci'],
  agenda:        ['events', 'web'],
  carte:         ['osm'],
  budget_vote:   ['budgets_votes'],
  approbations:  ['approbations'],
  commissions:   ['commissions'],
  urbanisme:     ['urbanisme', 'sitadel'],
  marches:       ['marches'],
}

/** Libellés lisibles, pour nommer au lecteur la source qui manque. */
export const LIBELLE_SOURCE = {
  cm:            'les procès-verbaux du conseil municipal',
  cm_archive:    "les procès-verbaux archivés du site de la commune",
  cc_epci:       "les délibérations de l'intercommunalité",
  events:        "l'agenda publié par la commune",
  web:           'le site de la commune et des associations',
  osm:           'les points d’intérêt OpenStreetMap',
  budgets_votes: 'les budgets primitifs votés',
  approbations:  'les projets approuvés en conseil',
  commissions:   'les commissions municipales',
  urbanisme:     "les autorisations d'urbanisme",
  sitadel:       'la base Sitadel',
  marches:       'les marchés publics',
}

/**
 * État d'un domaine au regard de la collecte.
 * @returns {{etat: 'absente'|'vide'|'servie', sources: string[], dernier: string|null}}
 */
export function etatSource(couverture, domaine) {
  const attendus = SOURCES[domaine] || []
  const runs = (couverture && couverture.collecteurs) || {}
  const tournes = attendus.filter((c) => runs[c])
  if (!tournes.length) {
    return { etat: 'absente', sources: attendus.map((c) => LIBELLE_SOURCE[c] || c), dernier: null }
  }
  const utiles = tournes.filter((c) => runs[c].statut !== 'empty')
  const dernier = tournes.map((c) => runs[c].dernier).filter(Boolean).sort().pop() || null
  return {
    etat: utiles.length ? 'servie' : 'vide',
    sources: tournes.map((c) => LIBELLE_SOURCE[c] || c),
    dernier,
  }
}

/** Énumération en français : « a, b et c ». */
export function enumerer(l) {
  if (!l || !l.length) return ''
  if (l.length === 1) return l[0]
  return l.slice(0, -1).join(', ') + ' et ' + l[l.length - 1]
}
