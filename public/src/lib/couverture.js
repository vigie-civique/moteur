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
  // `a_rapporte` (depuis le 04/10/2026) : une passe au moins a rapporté. Le
  // statut seul est celui de la dernière passe, `empty` pour un collecteur
  // incrémental qui n'a rien trouvé de NEUF. Absent : snapshot plus ancien.
  const utiles = tournes.filter((c) =>
    runs[c].a_rapporte ?? runs[c].statut !== 'empty')
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

/**
 * Ce que le site sait des marchés LUS dans les procès-verbaux, pour une portée
 * (`commune`, `intercommunalite`) : c'est ce qui donne sa raison à un zéro.
 *
 * Les marchés d'une petite commune passent sous les seuils de publicité : ils
 * ne se lisent que dans les procès-verbaux. Un zéro de marchés peut donc dire
 * trois choses que rien ne distinguait — les procès-verbaux n'ont pas été
 * dépouillés, ils l'ont été et des lignes attendent leur relecture, ou ils
 * l'ont été et rien n'y attend. `couverture.extraits.marches` (depuis le
 * 04/10/2026) porte les NOMBRES, jamais les lignes (décision 6).
 *
 * @returns {{cas: 'inconnu'|'non_depouilles'|'en_attente'|'depouilles',
 *            enAttente: number, autresEnAttente: number, dernier: string|null}}
 */
export function extraitsMarches(couverture, portee = 'commune') {
  const x = couverture && couverture.extraits && couverture.extraits.marches
  // Absent : snapshot plus ancien, ou base sans la table — le site ne sait pas.
  if (!x) return { cas: 'inconnu', enAttente: 0, autresEnAttente: 0, dernier: null }
  const attente = x.en_attente || {}
  const enAttente = attente[portee] || 0
  const autresEnAttente = (attente.total || 0) - enAttente
  const base = { enAttente, autresEnAttente, dernier: x.dernier_depot || null }
  if (enAttente) return { cas: 'en_attente', ...base }
  if (x.deposees) return { cas: 'depouilles', ...base }
  return { cas: 'non_depouilles', ...base }
}

/** « 1 attribution », « 3 attributions ». */
export function pluriel(n, mot, motPluriel = mot + 's') {
  return `${n.toLocaleString('fr-FR')} ${n > 1 ? motPluriel : mot}`
}
